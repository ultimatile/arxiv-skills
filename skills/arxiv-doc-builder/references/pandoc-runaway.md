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

pandoc's only channel from a `.sty` is the **macro table** it extracts (there is no per-package special-casing for names like `arxiv`). arXiv source tarballs commonly *bundle* a style file (`arxiv.sty`, conference styles, classicthesis-derived headers) right in the source directory, and pandoc reads any local `.sty` whose name matches a `\usepackage`. Every observed blowup is triggered by a **self-referential macro redefinition that is then invoked**, e.g. the "reduced leading" idiom:

```latex
\renewcommand{\normalsize}{\@setfontsize\normalsize\@xpt\@xipt ...}
\normalsize   % invoking it
```

TeX is fine (`\@setfontsize` consumes `\normalsize` as a non-expanded argument); pandoc does not know `\@setfontsize`, so on the invocation it re-expands `\normalsize` inside its own body without bound. Verified minimal repro: self-reference **+ invocation** blows up; the same definition **without** invocation, or a non-self-referential body, converts instantly.

## Fix

`{SAFE_ID}` is the name of the paper's directory, as SKILL.md's Procedure step 1 defines it. A path below that starts with `{SAFE_ID}/` resolves from the directory `convert-paper` wrote the paper's directory into. When that is not your working directory, put its path in front of each such path.

A file to strip is a `.sty` file under `{SAFE_ID}/source/` that holds a definition whose body uses the command it defines, as the `\renewcommand{\normalsize}` above does. Do steps 1 and 2 for each such file. When no `.sty` file under `{SAFE_ID}/source/` holds one, this file has no fix for the runaway: stop following it and tell the user that. When `{SAFE_ID}/pdf/{SAFE_ID}.pdf` exists, also tell the user that the paper can still be converted from that PDF, as `references/pdf-conversion.md` describes.

1. Find the commands the paper takes from the file: each command that the file defines and the paper uses after `\begin{document}`, directly or through a command the paper defines itself (e.g. `\newcommand{\co}{ACME}`, `\newcommand{\vect}[1]{\mathbf{#1}}`, or the `\subsubsubsection` that `arxiv.sty` defines). Leave out three kinds, however the file defines them: a command that exists without the file, in LaTeX or in a package the paper loads, such as `\section`, `\small` or `\citep`; a command for the title block or other front matter, such as `\keywords`; and a command whose definition uses the command itself. Without the file, pandoc does not know the remaining commands, and in running text it drops each one together with the text in braces after it, so copy each one's definition from the `.sty`, exactly as the file writes it, and every one of them when the file defines the command more than once. Put the copies together in one block, on lines before the first use of any of those commands anywhere in the source. Then add to the block the definition of each command that a definition you copied uses, when the file defines that command and it is none of those three kinds, and repeat until none is left. When a line of the block has an `@` in it, put a `\makeatletter` line before the block and a `\makeatother` line after it. When the paper takes no such command from the file, this step changes nothing.
2. Rename the file by appending `.bak`, so that pandoc no longer reads it. For `arxiv.sty`:

   ```bash
   mv {SAFE_ID}/source/arxiv.sty {SAFE_ID}/source/arxiv.sty.bak
   ```

3. Re-run `convert-paper` with the arguments you last gave it for this paper. Then follow `references/source-edits.md`, where each renamed file and each copied definition is an edit. Where it tells you to apply the edit again, do this section again on the downloaded source, from its start through step 2.
