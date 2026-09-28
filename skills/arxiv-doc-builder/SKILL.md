---
name: arxiv-doc-builder
description: Convert arXiv papers to Markdown documentation. Fetches available materials from arXiv (LaTeX source when available + PDF), converts LaTeX to Markdown via pandoc (happy path). PDF-only papers get a naive single-column fallback — the specialized PDF scripts in references/pdf-conversion.md give better results.
---

# arXiv Document Builder

Automatically converts arXiv papers into structured Markdown documentation for implementation reference.

## Capabilities

This skill automatically:

1. **Fetches paper materials from arXiv**
   - Attempts to download LaTeX source (preferred) and PDF, usually reusing files already downloaded
   - Handles all HTTP requests, extraction, and directory setup

2. **Converts LaTeX source to structured Markdown** (happy path)
   - LaTeX source → Markdown via pandoc (preserves all math and structure)
   - Preserves mathematical formulas in MathJax/LaTeX format (`$...$`, `$$...$$`)
   - Maintains section hierarchy and document structure
   - Includes abstracts, figures, and references

3. **PDF fallback** (naive — output quality must be verified)
   - When no LaTeX source is available, `convert-paper` runs `convert_pdf_simple.py` (single-column pdfplumber extraction) as a best-effort fallback
   - This produces usable output only for simple, single-column papers

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
1. Looks the paper's metadata record up once and hands the result to the steps below. Two sources can supply that record — arXiv's own API, and DataCite, where arXiv registers a DOI for every paper. `references/output-format.md` states which is asked when, that the wait for them is bounded, and how the frontmatter's `metadata_status` records the outcome
2. Calls `fetch_paper.py` to download available materials — source if available + PDF. Files already downloaded are usually reused
3. Detects available format (LaTeX source or PDF)
4. Calls the appropriate converter (`convert_latex.py` or `convert_pdf_simple.py`)
5. Outputs structured Markdown to `{output-dir}/{ARXIV_ID}/{ARXIV_ID}.md`

The metadata lookup, downloads (curl), file extraction (tar), and directory creation (mkdir) are handled automatically.

### Source Detection

- **LaTeX source available**: Converts with pandoc — this is the reliable path
- **PDF only**: Falls back to naive single-column text extraction

## Output Structure

Generated Markdown includes:
- A YAML frontmatter block with provenance metadata, whose schema
  `arxiv_doc_builder/arxiv_metadata.py` defines and
  `references/output-format.md` documents
- Full paper content with section hierarchy
- Inline math: `$f(x) = x^2$`
- Display math: `$$\int_0^\infty e^{-x} dx = 1$$`
- Preserved LaTeX commands for complex formulas
- References section

Output location: `{output-dir}/{ARXIV_ID}/{ARXIV_ID}.md` (default output-dir is current working directory)

## When Conversion Fails or Falls Back to PDF

If you edited a file under `{ARXIV_ID}/source/` and re-ran `convert-paper`, read `references/source-edits.md` first and follow it before any line below: the re-run may have replaced or deleted the edited source, and that file says what to do in each case.

When you made no such edit, or once that file no longer tells you to edit again or re-run, read the file that the line matching the output points to. For an output not listed here, act on what the output itself says.

Whichever file you follow, change the source only as it directs. Do NOT attempt broad preprocessing (replacing documentclass, expanding `\newcommand`, removing environments, etc.) — pandoc handles revtex4/revtex4-2, custom commands, `picture` environments, and theorem environments correctly.

- `convert-paper` exits with code 2 after printing `Error: Found N files with \documentclass` → `references/multiple-documentclass.md`
- It prints `Pandoc conversion failed:`, and the pandoc message after it contains `unexpected (` or `unexpected [` → `references/unknown-arity-macros.md`
- It prints `Pandoc conversion failed:`, and the pandoc message after it contains neither → `references/pandoc-failures.md`
- It prints `Pandoc did not finish within` or `Pandoc exceeded the <N> MB memory watchdog`, or a pandoc run has not returned → `references/pandoc-runaway.md`
- It prints `No LaTeX source, falling back to naive PDF conversion...` → `references/pdf-conversion.md`

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
