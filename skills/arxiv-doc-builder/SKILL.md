---
name: arxiv-doc-builder
description: Convert arXiv papers to Markdown documentation. Fetches available materials from arXiv (LaTeX source when available + PDF), converts LaTeX to Markdown via pandoc (happy path). PDF-only papers get a naive single-column fallback — use the specialized PDF scripts for better results.
---

# arXiv Document Builder

Automatically converts arXiv papers into structured Markdown documentation for implementation reference.

## Capabilities

This skill automatically:

1. **Fetches paper materials from arXiv**
   - Attempts to download LaTeX source (preferred) and PDF (idempotent — skips if cached)
   - Handles all HTTP requests, extraction, and directory setup

2. **Converts LaTeX source to structured Markdown** (happy path)
   - LaTeX source → Markdown via pandoc (preserves all math and structure)
   - Preserves mathematical formulas in MathJax/LaTeX format (`$...$`, `$$...$$`)
   - Maintains section hierarchy and document structure
   - Includes abstracts, figures, and references

3. **PDF fallback** (naive — output quality must be verified)
   - When no LaTeX source is available, `convert-paper` runs `convert_pdf_simple.py` (single-column pdfplumber extraction) as a best-effort fallback
   - This produces usable output only for simple, single-column papers
   - For 2-column papers, math-heavy papers, or complex layouts, inspect the output and use the specialized PDF scripts manually (see below)

4. **Generates implementation-ready documentation**
   - Output saved to `{ARXIV_ID}/{ARXIV_ID}.md` under the output directory (default: current working directory)
   - Easy to reference during code implementation
   - Optimized for Claude to read and understand

## When to Use This Skill

Invoke this skill when the user requests:
- "Convert arXiv paper {ID} to markdown"
- "Fetch and process paper {ID}"
- "Create documentation for arXiv:{ID}"
- "I need to read/reference paper {ID}"

## How It Works

### Single Entry Point

Use the main orchestrator script or the globally installed `convert-paper` command:

```bash
# Using global command (recommended)
convert-paper ARXIV_ID [--output-dir DIR]

# Using script directly
uv run arxiv_doc_builder/convert_paper.py ARXIV_ID [--output-dir DIR]
```

- `--output-dir`: Directory where `{ARXIV_ID}/{ARXIV_ID}.md` will be created. **Default: current working directory** (not a `papers/` subdirectory).
- Use absolute paths to control output location precisely.
- `-V` / `--version`: Print the version and exit. Resolves from installed
  distribution metadata, falling back to `pyproject.toml` when run straight
  from the source tree (the uninstalled case for `uv run …/convert_paper.py`).

The orchestrator:
1. Calls `fetch_paper.py` to download available materials — source if available + PDF (idempotent — cached files are reused)
2. Detects available format (LaTeX source or PDF)
3. Calls the appropriate converter (`convert_latex.py` or `convert_pdf_simple.py`)
4. Outputs structured Markdown to `{output-dir}/{ARXIV_ID}/{ARXIV_ID}.md`

All HTTP requests (curl), file extraction (tar), and directory creation (mkdir) are handled automatically.

### Source Detection

- **LaTeX source available**: Converts with pandoc — this is the reliable path
- **PDF only**: Falls back to naive single-column text extraction. Output quality varies and should be inspected. For better results, use the specialized PDF scripts below

## Output Structure

Generated Markdown includes:
- A YAML frontmatter block with provenance metadata (title, authors, arXiv id,
  version, published date, categories, DOI/journal, abstract) — see
  `references/output-format.md`; the schema is defined by
  `arxiv_doc_builder/arxiv_metadata.py`
- Full paper content with section hierarchy
- Inline math: `$f(x) = x^2$`
- Display math: `$$\int_0^\infty e^{-x} dx = 1$$`
- Preserved LaTeX commands for complex formulas
- References section

Output location: `{output-dir}/{ARXIV_ID}/{ARXIV_ID}.md` (default output-dir is current working directory)

## PDF Conversion Scripts

`convert-paper` only calls `convert_pdf_simple.py` as a naive fallback. The other scripts below are for manual or agent-driven use when the naive output is insufficient. Iterate by trying different scripts and inspecting results.

### convert_pdf_simple.py

Convert all pages as single-column layout.

```bash
uv run arxiv_doc_builder/convert_pdf_simple.py paper.pdf -o output.md
```

### convert_pdf_double_column.py

Convert all pages as double-column layout (for academic papers).

```bash
uv run arxiv_doc_builder/convert_pdf_double_column.py paper.pdf -o output.md
```

### convert_pdf_extract.py

Extract specific pages with optional double-column processing.

```bash
# Extract specific pages
uv run arxiv_doc_builder/convert_pdf_extract.py paper.pdf --pages 1-5,10 -o output.md

# Extract with mixed column layouts
uv run arxiv_doc_builder/convert_pdf_extract.py paper.pdf --pages 1-10 --double-column-pages 3-7 -o output.md
```

**Note:** `--double-column-pages` must be a subset of `--pages`. Invalid page ranges cause immediate error.

### Architecture

All three scripts share common conversion logic through `pdf_converter_lib.py`, ensuring consistent behavior while keeping each script focused on its specific use case.

## Advanced: Vision-Based PDF Conversion

For papers with complex mathematical formulas where text extraction fails, a vision-based approach is available as a manual fallback:

```bash
# Generate high-resolution images from PDF
python arxiv_doc_builder/convert_pdf_with_vision.py paper.pdf --dpi 300 --columns 2
```

This creates page images (with optional column splitting) that can be read manually with Claude's vision capabilities for maximum accuracy. This is NOT part of the automatic workflow—use it only when automatic conversion produces poor results.

### PDF Conversion Quality

PDF conversion is inherently lossy:
- Math formulas are not in LaTeX format
- Complex layouts (2-column with column-spanning elements) may break reading order
- Tables may need manual fixing
- References may be malformed

PDF conversion is acceptable when no LaTeX source is available and the paper is primarily text. For math-heavy papers, use the vision-based approach above or keep the PDF as the primary reference.

**Fallback strategy for complex papers:**
1. Extract structure and text via `convert_pdf_simple.py`
2. Keep PDF link for reference
3. Use vision-based conversion for pages with dense math
4. Focus on readable prose sections

## Troubleshooting: Multiple \documentclass Files

Some arXiv papers (e.g., PRL with supplemental material) contain multiple `.tex` files, each with its own `\documentclass`. Automatic selection is unreliable in this case — the canonical example is `1911.04882`, which ships both the main PRL paper and an independent PRL supplement, and either can convert successfully. Since pandoc succeeding is not evidence that the selected file is the correct entry point, `convert-paper` refuses to guess: it fails explicitly with **exit code 2** and lists all candidates.

Example failure output:

```
Error: Found 2 files with \documentclass in /path/to/1911.04882/source:
  - /path/to/1911.04882/source/main_paper.tex
  - /path/to/1911.04882/source/supplemental_material.tex

Main .tex selection is ambiguous. Re-run with --tex-file pointing at the correct file, e.g.:
  convert-paper <ARXIV_ID> --tex-file /path/to/1911.04882/source/main_paper.tex

If you originally passed --output-dir, include the same value in the re-run.
```

To resolve, re-run `convert-paper` with `--tex-file` pointing at the correct main file. The fetch step is idempotent, so the already-downloaded source is reused without touching the network:

```bash
convert-paper 1911.04882 --tex-file /path/to/1911.04882/source/main_paper.tex
```

If the original run used `--output-dir`, pass the same value again so that `convert-paper` reconstructs the correct paper directory.

## Troubleshooting: pandoc Conversion Failures

When pandoc fails on a LaTeX source, the error may point to `\end{document}` with `unexpected \end`. This means pandoc's parser broke down due to a syntax issue elsewhere — `\end{document}` itself is not the cause. Do NOT attempt broad preprocessing (replacing documentclass, expanding `\newcommand`, removing environments, etc.) — pandoc handles revtex4/revtex4-2, custom commands, `picture` environments, and theorem environments correctly.

### Diagnosis steps

1. **Binary search for the failing line.** Extract the body (`\begin{document}` to `\end{document}`), then test pandoc with increasing prefixes to find the first line that causes failure.
2. **Check that line for brace mismatches.** The most common cause is an unbalanced `{` or `}` in the LaTeX source. LaTeX's TeX engine silently tolerates these, but pandoc's structured parser does not.
3. **Fix only the mismatch and re-run `convert-paper`.** A single-character fix (e.g., removing an orphaned `{`) is usually sufficient. The fetch step is idempotent, so the cached source and PDF are reused without network access.

### Example

The source `(see, e.g., {\cite{makhlin})` has an unmatched `{`. LaTeX compiles fine but pandoc fails. Fix: remove the stray `{`.

## Troubleshooting: Conversion Hangs / Runaway Memory (pandoc never returns)

A brace-mismatch failure is *fast* — pandoc errors in seconds. A different failure mode is the **hang**: `convert-paper` never returns. `convert_latex.py` bounds pandoc on two axes so this surfaces as a fast error instead of an indefinite hang (both env-overridable):

- **Wall-clock timeout** (`PANDOC_TIMEOUT_SECONDS`, default 180s; `ARXIV_PANDOC_TIMEOUT`). This is the *reliable* control — every observed runaway is killed by it.
- **RSS watchdog** (`PANDOC_RSS_CAP_MB`, default 8192; `ARXIV_PANDOC_RSS_CAP_MB`). Polls the child's real resident memory and kills early; defense-in-depth for a fast-allocating runaway the timeout alone wouldn't contain in time.

Why both, and not the obvious one-liners: observed runaways come in two shapes — a CPU spin at flat memory, and a slow leak (~10 MB/s, reaching tens of GB only after *many minutes*). A timeout catches both, and for the slow leak it also bounds peak memory (≈ timeout × leak-rate, so ~1.8 GB at 180s). A memory cap alone would miss the CPU-spin shape. The naive memory caps were **measured not to work** on this failure: GHC's `pandoc +RTS -M2g -RTS` heap limit did not stop the runaway (major-GC checks don't fire fast enough), and a macOS `RLIMIT_AS` cap (4/8/16 GB) didn't kill it either (enforcement is unreliable and collides with the GHC RTS reserving a huge virtual address space). Hence the watchdog polls **RSS externally** (`ps -o rss=`), which is what actually correlates with swap thrash. You may still hit a hang when driving pandoc manually without these bounds.

### Is it slow or hung?

Find the pandoc PID (`ps aux | rg pandoc`) and read its state in one shot:

```bash
ps -o pid,etime,time,%cpu,rss,state -p <PID>
```

- the **state** column shows `R` (running) and CPU `time` tracks `etime` → on-CPU (slow or runaway), not deadlocked.
- **`rss` climbing into the GB/tens-of-GB** → a parser blowup that will not finish. (A 100-page paper converts in seconds and well under ~1 GB.)
- The output `.md` size is **not** a progress signal: pandoc buffers the whole document and writes it only at the end (0 bytes until done).

### Root cause: pandoc reads bundled style `.sty` files

pandoc's only channel from a `.sty` is the **macro table** it extracts (there is no per-package special-casing for names like `arxiv`). arXiv source tarballs commonly *bundle* a style file (`arxiv.sty`, conference styles, classicthesis-derived headers) right in the source directory, and pandoc reads any local `.sty` whose name matches a `\usepackage`. The blowup is triggered by a **self-referential macro redefinition that is then invoked**, e.g. the "reduced leading" idiom:

```latex
\renewcommand{\normalsize}{\@setfontsize\normalsize\@xpt\@xipt ...}
\normalsize   % invoking it
```

TeX is fine (`\@setfontsize` consumes `\normalsize` as a non-expanded argument); pandoc does not know `\@setfontsize`, so on the invocation it re-expands `\normalsize` inside its own body without bound. Verified minimal repro: self-reference **+ invocation** blows up; the same definition **without** invocation, or a non-self-referential body, converts instantly.

### Fix: strip the style-only `.sty` (safe, and provably output-neutral here)

Move the style `.sty` out of the source directory (reversible) or comment its `\usepackage`, then re-run — the fetch step is idempotent, so the cached source is reused:

```bash
mv source/arxiv.sty source/arxiv.sty.bak   # pandoc no longer reads it
```

Removing a `.sty` is **not** a blanket no-op, but the impact is decidable: it changes output only on `(commands the .sty defines/redefines) ∩ (commands used in the body)`. For a style-only package that intersection is layout scaffolding — `\section`/`\subsection`/`\maketitle` (which pandoc renders *better* from its built-ins; the `.sty`'s `\@startsection` redefinition actually mangles headings) plus front-matter like `\keywords`. Prose, math, citations, and glossary terms are untouched. Before stripping, confirm the `.sty` defines no **content macro** used in the body (e.g. `\newcommand{\co}{ACME}`); if it does, that text would be lost and you must instead provide a stub (next section). For style-only packages the intersection contains no content macro, so stripping is output-equivalent on the substantive content.

## Troubleshooting: glossaries / cleveref and other unknown-arity macros

Symptom: a fast `unexpected (` / `unexpected [` error, often reported at `\begin{document}` (the real cause is elsewhere — pandoc parsed to a boundary). Cause: a heavily-used package whose commands take **optional arguments** pandoc doesn't know the arity of — most commonly `glossaries` / `glossaries-extra` (`\gls`, `\glspl`, `\glsxtrlong`, …, including the `\gls[prereset]{key}` optional-arg form) and `cleveref` (`\cref`). pandoc mis-counts the braces it should consume and breaks once enough body follows.

Fix: inject **arity-correct `\providecommand` stubs** (optional-argument-tolerant) just before `\begin{document}`. `\providecommand` only defines them because pandoc never loaded the real package:

```latex
\makeatletter
\providecommand{\gls}[2][]{#2}\providecommand{\glspl}[2][]{#2}
\providecommand{\Gls}[2][]{#2}\providecommand{\Glspl}[2][]{#2}
\providecommand{\glsxtrlong}[2][]{#2}\providecommand{\glsxtrlongpl}[2][]{#2}
\providecommand{\glsxtrshort}[2][]{#2}\providecommand{\glsxtrshortpl}[2][]{#2}
\providecommand{\glsentryshort}[1]{#1}\providecommand{\glsentrylong}[1]{#1}
\providecommand{\glslink}[3][]{#3}\providecommand{\glsadd}[2][]{}
\providecommand{\cref}[1]{#1}\providecommand{\Cref}[1]{#1}
\makeatother
```

Quality note: this expands `\gls{AF}` to its **key** (`AF`), not the glossary long form ("activation function") — pandoc cannot resolve the glossary database. Keys are usually readable (`ReLU`, `NN`, `tanh`), which is acceptable for an implementation-reference doc; `\cref{sec:x}` likewise renders as the label `sec:x`, not a link.

This is a *targeted* exception to the "no broad preprocessing" rule above: stubbing a fixed set of known unknown-arity commands, not rewriting the document.

## Directory Structure

Output is created under `--output-dir` (default: current working directory):

```
{output-dir}/
└── {ARXIV_ID}/
    ├── source/           # LaTeX source files (if available)
    ├── pdf/              # PDF file
    ├── {ARXIV_ID}.md     # Generated Markdown output
    └── figures/          # Extracted figures (if any)
```
