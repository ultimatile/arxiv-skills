# Troubleshooting: Conversion Hangs / Runaway Memory (pandoc never returns)

A brace-mismatch failure is *fast* — pandoc errors in seconds. A different failure mode is the **hang**: `convert-paper` never returns. `convert_latex.py` bounds pandoc on two axes so this surfaces as a fast error instead of an indefinite hang (both env-overridable):

- **Wall-clock timeout** (`PANDOC_TIMEOUT_SECONDS`, default 180s; `ARXIV_PANDOC_TIMEOUT`). This is the *reliable* control — every observed runaway is killed by it.
- **RSS watchdog** (`PANDOC_RSS_CAP_MB`, default 8192; `ARXIV_PANDOC_RSS_CAP_MB`). Polls the child's real resident memory and kills early; defense-in-depth for a fast-allocating runaway the timeout alone wouldn't contain in time.

Why both, and not the obvious one-liners: observed runaways come in two shapes — a CPU spin at flat memory, and a slow leak (~10 MB/s, reaching tens of GB only after *many minutes*). A timeout catches both, and for the slow leak it also bounds peak memory (≈ timeout × leak-rate, so ~1.8 GB at 180s). A memory cap alone would miss the CPU-spin shape. The naive memory caps were **measured not to work** on this failure: GHC's `pandoc +RTS -M2g -RTS` heap limit did not stop the runaway (major-GC checks don't fire fast enough), and a macOS `RLIMIT_AS` cap (4/8/16 GB) didn't kill it either (enforcement is unreliable and collides with the GHC RTS reserving a huge virtual address space). Hence the watchdog polls **RSS externally** (`ps -o rss=`), which is what actually correlates with swap thrash. You may still hit a hang when driving pandoc manually without these bounds.

## Is it slow or hung?

Find the pandoc PID (`ps aux | rg pandoc`) and read its state in one shot:

```bash
ps -o pid,etime,time,%cpu,rss,state -p <PID>
```

- the **state** column shows `R` (running) and CPU `time` tracks `etime` → on-CPU (slow or runaway), not deadlocked.
- **`rss` climbing into the GB/tens-of-GB** → a parser blowup that will not finish. (A 100-page paper converts in seconds and well under ~1 GB.)
- The output `.md` size is **not** a progress signal: pandoc buffers the whole document and writes it only at the end (0 bytes until done).

## Root cause: pandoc reads bundled style `.sty` files

pandoc's only channel from a `.sty` is the **macro table** it extracts (there is no per-package special-casing for names like `arxiv`). arXiv source tarballs commonly *bundle* a style file (`arxiv.sty`, conference styles, classicthesis-derived headers) right in the source directory, and pandoc reads any local `.sty` whose name matches a `\usepackage`. The blowup is triggered by a **self-referential macro redefinition that is then invoked**, e.g. the "reduced leading" idiom:

```latex
\renewcommand{\normalsize}{\@setfontsize\normalsize\@xpt\@xipt ...}
\normalsize   % invoking it
```

TeX is fine (`\@setfontsize` consumes `\normalsize` as a non-expanded argument); pandoc does not know `\@setfontsize`, so on the invocation it re-expands `\normalsize` inside its own body without bound. Verified minimal repro: self-reference **+ invocation** blows up; the same definition **without** invocation, or a non-self-referential body, converts instantly.

## Fix: strip the style-only `.sty` (safe, and provably output-neutral here)

Move the style `.sty` out of the source directory (reversible) or comment its `\usepackage`, then re-run. Then check that the change survived, as `references/source-edits.md` describes:

```bash
mv source/arxiv.sty source/arxiv.sty.bak   # pandoc no longer reads it
```

Removing a `.sty` is **not** a blanket no-op, but the impact is decidable: it changes output only on `(commands the .sty defines/redefines) ∩ (commands used in the body)`. For a style-only package that intersection is layout scaffolding — `\section`/`\subsection`/`\maketitle` (which pandoc renders *better* from its built-ins; the `.sty`'s `\@startsection` redefinition actually mangles headings) plus front-matter like `\keywords`. Prose, math, citations, and glossary terms are untouched. Before stripping, confirm the `.sty` defines no **content macro** used in the body (e.g. `\newcommand{\co}{ACME}`); if it does, stripping would lose that text, so strip the `.sty` anyway and also copy that macro's definition from the `.sty` into a `\providecommand` placed just before `\begin{document}`. For style-only packages the intersection contains no content macro, so stripping is output-equivalent on the substantive content.
