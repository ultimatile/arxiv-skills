# PDF to Markdown Conversion

## Overview

Extract and convert PDF content to Markdown when LaTeX source is unavailable.

## Conversion Strategy

### 1. Text Extraction

**Using pdfplumber (recommended):**
```python
import pdfplumber

with pdfplumber.open("paper.pdf") as pdf:
    text = ""
    for page in pdf.pages:
        text += page.extract_text()
```

**Advantages:**
- Good layout preservation
- Table extraction support
- Character position information

### 2. Structure Detection

**Section Headers:**
- Detect by font size/style changes
- Common patterns: "1. Introduction", "2 Related Work"
- Use regex patterns:
  - `^\d+\.?\s+[A-Z]` for numbered sections
  - `^[A-Z][A-Za-z\s]+$` for all-caps headers

**Example:**
```python
import re

def detect_sections(text):
    lines = text.split('\n')
    sections = []
    for i, line in enumerate(lines):
        if re.match(r'^\d+\.?\s+[A-Z]', line):
            sections.append((i, line))
    return sections
```

### 3. Figure Extraction

**Extract images from PDF:**
```python
from pdf2image import convert_from_path

images = convert_from_path('paper.pdf', dpi=200)
for i, image in enumerate(images):
    image.save(f'figure_{i}.png', 'PNG')
```

**Or extract embedded images:**
```bash
pdfimages -j paper.pdf figures/fig
```

**Caption Detection:**
- Search for "Figure X:" or "Fig. X:"
- Extract text near image bounding boxes
- Use pdfplumber's layout analysis

### 4. Table Extraction

```python
with pdfplumber.open("paper.pdf") as pdf:
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            # Convert to Markdown table
            markdown_table = convert_to_markdown(table)
```

### 5. Mathematics Handling

**Challenge:** PDFs contain rendered math, not LaTeX source.

**Partial solutions:**
- OCR with specialized tools (limited accuracy)
- Preserve as images for complex equations
- Manual review recommended for critical formulas

**Best effort:**
```python
# Detect math-like patterns (symbols, Greek letters)
# Keep as verbatim or [Math expression - see PDF]
```

## Column Layout Handling

Academic PDFs often use 2-column layout.

**Problem:** Text extraction may interleave columns.

**Solutions:**
```python
# pdfplumber with layout analysis
with pdfplumber.open("paper.pdf") as pdf:
    for page in pdf.pages:
        # Define column boundaries
        left_bbox = (0, 0, page.width/2, page.height)
        right_bbox = (page.width/2, 0, page.width, page.height)

        left_text = page.crop(left_bbox).extract_text()
        right_text = page.crop(right_bbox).extract_text()

        text = left_text + "\n" + right_text
```

## Quality Considerations

### Limitations

PDF conversion is inherently lossy:
- ❌ Math formulas not in LaTeX
- ❌ Complex layouts may break
- ❌ Tables may need manual fixing
- ❌ References may be malformed

### When to Use

PDF conversion is acceptable when:
- ✅ No LaTeX source available
- ✅ Paper is primarily text (few equations)
- ✅ Need quick overview, not precise details
- ✅ Willing to manually verify/fix critical parts

### Quality Checks

After conversion:
1. Verify section structure
2. Check figure count matches PDF
3. Spot-check table formatting
4. Mark complex math as "[see PDF]"
5. Validate references section

## Tools Comparison

| Tool | Text Quality | Math Support | Tables | Speed |
|------|-------------|--------------|--------|-------|
| pdfplumber | Excellent | None | Good | Fast |
| PyPDF2 | Good | None | Poor | Very Fast |
| pdfminer | Good | None | Fair | Medium |
| OCR (tesseract) | Fair | None | Poor | Slow |

**Recommendation:** pdfplumber for most cases.

## Fallback Strategy

For papers with complex math/layout:
1. Extract structure and text
2. Keep PDF link for reference
3. Add note: "See [PDF](link) for mathematical details"
4. Focus on readable prose sections
