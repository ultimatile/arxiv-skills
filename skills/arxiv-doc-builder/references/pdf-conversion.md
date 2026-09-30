# PDF Conversion

## PDF Conversion Scripts

`convert-paper` only calls `convert_pdf_simple.py` as a naive fallback. The other scripts below are for manual or agent-driven use when the naive output is insufficient. Iterate by trying different scripts and inspecting results.

Replace `SKILL_DIR` in the commands below as SKILL.md's Procedure step 1 says. Relative paths you pass as arguments, such as `paper.pdf` and `output.md`, resolve against your own working directory.

### convert_pdf_simple.py

Convert all pages as single-column layout.

```bash
uv run SKILL_DIR/arxiv_doc_builder/convert_pdf_simple.py paper.pdf -o output.md
```

### convert_pdf_double_column.py

Convert all pages as double-column layout (for academic papers).

```bash
uv run SKILL_DIR/arxiv_doc_builder/convert_pdf_double_column.py paper.pdf -o output.md
```

### convert_pdf_extract.py

Extract specific pages with optional double-column processing.

```bash
# Extract specific pages
uv run SKILL_DIR/arxiv_doc_builder/convert_pdf_extract.py paper.pdf --pages 1-5,10 -o output.md

# Extract with mixed column layouts
uv run SKILL_DIR/arxiv_doc_builder/convert_pdf_extract.py paper.pdf --pages 1-10 --double-column-pages 3-7 -o output.md
```

**Note:** `--double-column-pages` must be a subset of `--pages`. Invalid page ranges cause immediate error.

## Advanced: Vision-Based PDF Conversion

For papers with complex mathematical formulas where text extraction fails, a vision-based approach is available as a manual fallback:

```bash
# Generate high-resolution images from PDF
uv run SKILL_DIR/arxiv_doc_builder/convert_pdf_with_vision.py paper.pdf --dpi 300 --columns 2
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
