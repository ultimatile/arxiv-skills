---
name: arxiv-doc-builder
description: Convert an arXiv paper to Markdown for reading or implementation reference. Use when asked to convert, fetch, or create documentation for an arXiv paper by its ID, or when a paper with a known arXiv ID needs to be read or referenced. Fetches the LaTeX source when available (plus the PDF) and converts it with pandoc; PDF-only papers get a naive single-column fallback.
---

# arXiv Document Builder

## Procedure

1. Run the converter:

   ```bash
   # Using global command (recommended)
   convert-paper ARXIV_ID [--output-dir DIR]

   # Using script directly
   uv run arxiv_doc_builder/convert_paper.py ARXIV_ID [--output-dir DIR]
   ```

   - `--output-dir`: Directory where `{ARXIV_ID}/{ARXIV_ID}.md` will be created. **Default: current working directory** (not a `papers/` subdirectory).
   - Use absolute paths to control output location precisely.

   `convert-paper` does the metadata lookup, downloads, extraction, and directory creation itself; do not run curl, tar, or mkdir for them.

2. Before reading the output, go through "When Conversion Fails or Falls Back to PDF" below; it decides whether the run needs more work.

3. When that section leaves nothing more to do, read `{output-dir}/{ARXIV_ID}/{ARXIV_ID}.md`. It opens with a YAML frontmatter block of provenance metadata; `references/output-format.md` documents its fields, including what `metadata_status` records.

## When Conversion Fails or Falls Back to PDF

If you edited a file under `{ARXIV_ID}/source/` and re-ran `convert-paper`, read `references/source-edits.md` first and follow it before any line below.

When you made no such edit, or once that file no longer tells you to edit again or re-run, read the file that the line matching the output points to. For an output not listed here, act on what the output itself says.

Whichever file you follow, change the source only as it directs. Do NOT attempt broad preprocessing (replacing documentclass, expanding `\newcommand`, removing environments, etc.) — pandoc handles revtex4/revtex4-2, custom commands, `picture` environments, and theorem environments correctly.

- `convert-paper` exits with code 2 after printing `Error: Found N files with \documentclass` → `references/multiple-documentclass.md`
- It prints `Pandoc conversion failed:`, and the pandoc message after it contains `unexpected (` or `unexpected [` → `references/unknown-arity-macros.md`
- It prints `Pandoc conversion failed:`, and the pandoc message after it contains neither → `references/pandoc-failures.md`
- It prints `Pandoc did not finish within` or `Pandoc exceeded the <N> MB memory watchdog`, or a pandoc run has not returned → `references/pandoc-runaway.md`
- It prints `No LaTeX source, falling back to naive PDF conversion...` → `references/pdf-conversion.md`

## Output Layout

```
{output-dir}/
└── {ARXIV_ID}/
    ├── source/           # LaTeX source files (if available)
    ├── pdf/              # PDF file
    ├── {ARXIV_ID}.md     # Generated Markdown output
    └── figures/          # Extracted figures (if any)
```
