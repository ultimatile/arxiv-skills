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
   uv run --project "SKILL_DIR" "SKILL_DIR/arxiv_doc_builder/convert_paper.py" ARXIV_ID [--output-dir DIR]
   ```

   - `SKILL_DIR`: replace with the absolute path of the directory this SKILL.md is in. It is a placeholder, not a shell variable. Keep the double quotes around it, so a path containing spaces stays one argument. The command then runs from any working directory.
   - `--output-dir`: Directory where `{SAFE_ID}/{SAFE_ID}.md` will be created. **Default: current working directory** (not a `papers/` subdirectory).
     `{SAFE_ID}`, here and below, is `ARXIV_ID` with `/` replaced by `_`, as in `hep-th/9711200` → `hep-th_9711200`. A new-style ID contains no `/`, so it is used unchanged.
   - Use absolute paths to control output location precisely.

   `convert-paper` does the metadata lookup, downloads, extraction, and directory creation itself; do not run curl, tar, or mkdir for them.

2. On success, `convert-paper` prints the Markdown file's path on its `Output:` line. The file opens with a YAML frontmatter block of provenance metadata; `references/output-format.md` documents its fields, including what `metadata_status` records. The File Organization section of `references/output-format.md` shows the layout of the paper's directory, `{SAFE_ID}/`.

## When Conversion Fails or Falls Back to PDF

If you edited a file under `{SAFE_ID}/source/` and re-ran `convert-paper`, read `references/source-edits.md` first and follow it before any line below.

When you made no such edit, or once that file no longer tells you to edit again or re-run, read the file that the line matching the output points to. For an output not listed here, act on what the output itself says.

Whichever file you follow, change the source only as it directs. Do NOT attempt broad preprocessing (replacing documentclass, expanding `\newcommand`, removing environments, etc.) — pandoc handles revtex4/revtex4-2, custom commands, `picture` environments, and theorem environments correctly.

- `convert-paper` exits with code 2 after printing `Error: Found N files with \documentclass` → `references/multiple-documentclass.md`
- It prints `Pandoc conversion failed:`, and the pandoc message after it contains `unexpected (` or `unexpected [` → `references/unknown-arity-macros.md`
- It prints `Pandoc conversion failed:`, and the pandoc message after it contains neither → `references/pandoc-failures.md`
- It prints `Pandoc did not finish within` or `Pandoc exceeded the <N> MB memory watchdog`, or a pandoc run has not returned → `references/pandoc-runaway.md`
- It prints `No LaTeX source, falling back to naive PDF conversion...` → `references/pdf-conversion.md`
