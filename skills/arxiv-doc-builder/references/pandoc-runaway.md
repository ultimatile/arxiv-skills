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

## Fix

`{SAFE_ID}` is the name of the paper's directory, as SKILL.md's Procedure step 1 defines it. Paths below start with it, so they resolve from the directory `convert-paper` wrote the paper's directory into.

A file to strip is a `.sty` file under `{SAFE_ID}/source/` that holds a definition whose body uses the command it defines, as the `\renewcommand{\normalsize}` above does. Do steps 1 and 2 for each such file. When no `.sty` file under `{SAFE_ID}/source/` holds one, this file has no fix for the runaway: stop following it and tell the user that. When `{SAFE_ID}/pdf/{SAFE_ID}.pdf` exists, also tell the user that the paper can still be converted from that PDF, as `references/pdf-conversion.md` describes.

1. Find the file's content macros. A content macro is a command that the file defines and has no `\renewcommand` of, that the paper uses after `\begin{document}`, and whose definition puts text or math into the paper (e.g. `\newcommand{\co}{ACME}` or `\newcommand{\vect}[1]{\mathbf{#1}}`). Stripping the file would lose that text, so copy each one's definition from the `.sty` into a `\providecommand` placed before the macro's first use anywhere in the source. Then copy in the same way each command that a definition you copied uses, when the file defines that command and has no `\renewcommand` of it either, and repeat until none is left. When the file has no content macro, this step changes nothing.
2. Rename the file by appending `.bak`, so that pandoc no longer reads it. For `arxiv.sty`:

   ```bash
   mv {SAFE_ID}/source/arxiv.sty {SAFE_ID}/source/arxiv.sty.bak
   ```

3. Re-run `convert-paper`. Then follow `references/source-edits.md`, where each renamed file and each added `\providecommand` is an edit. Where it tells you to apply the edit again, do this section again from its start on the downloaded source.
