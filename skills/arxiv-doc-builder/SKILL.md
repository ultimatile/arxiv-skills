---
name: arxiv-doc-builder
description: Automatically convert arXiv papers to well-structured Markdown documentation. Invoke with an arXiv ID to fetch materials (LaTeX source or PDF), convert to Markdown, and generate implementation-ready reference documentation with preserved mathematics and section structure.
---

# arXiv Document Builder

Automatically converts arXiv papers into structured Markdown documentation for implementation reference.

## Capabilities

This skill automatically:

1. **Fetches paper materials from arXiv**
   - Attempts to download LaTeX source first (preferred for accuracy)
   - Falls back to PDF if source is unavailable
   - Handles all HTTP requests, extraction, and directory setup

2. **Converts to structured Markdown**
   - LaTeX source → Markdown via pandoc (preserves all math and structure)
   - PDF → Markdown via text extraction with multiple conversion modes:
     - Simple single-column conversion (default)
     - Full double-column conversion for academic papers
     - Page-wise extraction with mixed column support
   - Preserves mathematical formulas in MathJax/LaTeX format (`$...$`, `$$...$$`)
   - Maintains section hierarchy and document structure
   - Includes abstracts, figures, and references

3. **Generates implementation-ready documentation**
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

The orchestrator:
1. Calls `fetch_paper.py` to download materials (with automatic source→PDF fallback)
2. Detects available format (LaTeX source or PDF)
3. Calls the appropriate converter (`convert_latex.py` or `convert_pdf_simple.py`)
4. Outputs structured Markdown to `{output-dir}/{ARXIV_ID}/{ARXIV_ID}.md`

All HTTP requests (curl), file extraction (tar), and directory creation (mkdir) are handled automatically.

### Automatic Source Detection and Fallback

The fetcher tries LaTeX source first, then PDF:
- **LaTeX source available**: Downloads `.tar.gz`, extracts to `papers/{ID}/source/`, converts with pandoc
- **PDF only**: Downloads PDF to `papers/{ID}/pdf/`, extracts text with pdfplumber

No manual intervention needed—the skill handles format detection and fallback automatically.

## Output Structure

Generated Markdown includes:
- Title, authors, and abstract
- Full paper content with section hierarchy
- Inline math: `$f(x) = x^2$`
- Display math: `$$\int_0^\infty e^{-x} dx = 1$$`
- Preserved LaTeX commands for complex formulas
- References section

Output location: `{output-dir}/{ARXIV_ID}/{ARXIV_ID}.md` (default output-dir is current working directory)

## PDF Conversion Scripts

Three specialized scripts for direct PDF conversion:

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

See [references/pdf-conversion.md](references/pdf-conversion.md) for details on vision-based conversion.

## Troubleshooting: Multiple \documentclass Files

Some arXiv papers (e.g., PRL with supplemental material) contain multiple `.tex` files, each with its own `\documentclass`. Automatic selection is unreliable in this case — the canonical example is `1911.04882`, which ships both the main PRL paper and an independent PRL supplement, and either can convert successfully. Since pandoc succeeding is not evidence that the selected file is the correct entry point, `convert-paper` refuses to guess: it fails explicitly with **exit code 2** and lists all candidates.

Example failure output:

```
Error: Found 2 files with \documentclass in /path/to/1911.04882/source:
  - /path/to/1911.04882/source/main_paper.tex
  - /path/to/1911.04882/source/supplemental_material.tex

Main .tex selection is ambiguous. Re-run with --tex-file pointing at the correct file, e.g.:
  convert-paper <ARXIV_ID> --skip-fetch --tex-file /path/to/1911.04882/source/main_paper.tex

If you originally passed --output-dir, include the same value in the re-run.
```

To resolve, re-run `convert-paper` with `--tex-file` pointing at the correct main file, combined with `--skip-fetch` to reuse the already-downloaded source:

```bash
convert-paper 1911.04882 --skip-fetch --tex-file /path/to/1911.04882/source/main_paper.tex
```

If the original run used `--output-dir`, pass the same value again so that `convert-paper` reconstructs the correct paper directory.

## Troubleshooting: pandoc Conversion Failures

When pandoc fails on a LaTeX source, the error may point to `\end{document}` with `unexpected \end`. This means pandoc's parser broke down due to a syntax issue elsewhere — `\end{document}` itself is not the cause. Do NOT attempt broad preprocessing (replacing documentclass, expanding `\newcommand`, removing environments, etc.) — pandoc handles revtex4/revtex4-2, custom commands, `picture` environments, and theorem environments correctly.

### Diagnosis steps

1. **Binary search for the failing line.** Extract the body (`\begin{document}` to `\end{document}`), then test pandoc with increasing prefixes to find the first line that causes failure.
2. **Check that line for brace mismatches.** The most common cause is an unbalanced `{` or `}` in the LaTeX source. LaTeX's TeX engine silently tolerates these, but pandoc's structured parser does not.
3. **Fix only the mismatch and retry.** A single-character fix (e.g., removing an orphaned `{`) is usually sufficient.

### Example

The source `(see, e.g., {\cite{makhlin})` has an unmatched `{`. LaTeX compiles fine but pandoc fails. Fix: remove the stray `{`.

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
