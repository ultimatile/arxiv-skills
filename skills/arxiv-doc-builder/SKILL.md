---
name: arxiv-doc-builder
description: Convert arXiv papers (PDF or LaTeX source) into well-structured Markdown documentation optimized for reference during implementation. Use when you need to create readable documentation from arXiv papers for code implementation reference, understanding paper details, or building reference materials.
---

# arXiv Document Builder

Convert arXiv papers into reference-friendly Markdown documentation.

## Overview

This skill helps convert arXiv papers into structured Markdown documents that are:

- Easy to reference during implementation
- Preserve mathematical formulas (MathJax compatible)
- Include figures and captions
- Maintain section hierarchy
- Optimized for Claude to understand

## Workflow

### 1. Fetch Paper Materials

**For papers with LaTeX source** (preferred):

```bash
# Fetch source
curl -L -o /tmp/ARXIV_ID-src.tar.gz https://arxiv.org/src/ARXIV_ID

# Extract
mkdir -p /tmp/ARXIV_ID-src
tar -xzf /tmp/ARXIV_ID-src.tar.gz -C /tmp/ARXIV_ID-src
```

**For PDF-only papers**:

```bash
curl -L -o /tmp/ARXIV_ID.pdf https://arxiv.org/pdf/ARXIV_ID.pdf
```

See [arxiv-fetch.md](references/arxiv-fetch.md) for detailed fetching instructions.

### 2. Convert to Markdown

**From LaTeX source**:

- Parse `main.tex` or identified main file
- Extract document structure (sections, subsections)
- Convert LaTeX math to MathJax/LaTeX notation
- Process figures and captions
- See [latex-conversion.md](references/latex-conversion.md) for details

**From PDF** (2 approaches available):

1. **Vision-based conversion (Recommended for accurate math formulas)**:
   - Convert PDF pages to high-resolution images (300 DPI)
   - Automatically split 2-column papers for better detail
   - Use Claude's vision capabilities to read and extract content
   - Preserves mathematical formulas with LaTeX accuracy
   - Best for: Older papers, complex formulas, precise extraction
   - Script: `convert_pdf_with_vision.py`

2. **Simple text extraction (Fast but limited)**:
   - Extract text from PDF text layer using pdfplumber
   - Good for modern PDFs with embedded text
   - Limited accuracy for complex formulas and layouts
   - Best for: Quick previews, modern well-formatted PDFs
   - Script: `convert_pdf_simple.py`

### 3. Output Format

Generated Markdown includes:

- Title and authors
- Abstract
- Table of contents
- Sections with proper hierarchy
- Inline math: `$...$` or `\(...\)`
- Display math: `$$...$$` or `\[...\]`
- Figures with captions
- References section

See [output-format.md](references/output-format.md) for specification.

## Quick Start

```bash
# Example: Process paper 2409.03108
ARXIV_ID="2409.03108"

# 1. Try to fetch source first
curl -L -o /tmp/${ARXIV_ID}-src.tar.gz https://arxiv.org/src/${ARXIV_ID}

# 2. If source available, use LaTeX conversion
# Otherwise fall back to PDF conversion

# 3. Run conversion script
python scripts/convert_paper.py ${ARXIV_ID} --output ./docs/${ARXIV_ID}.md
```

## Scripts

### Core Scripts

- `scripts/convert_paper.py` - Main conversion orchestrator (auto-detects source type)
- `scripts/fetch_paper.py` - Unified paper fetching (tries source, falls back to PDF)

### Conversion Scripts

- `scripts/convert_latex.py` - LaTeX to Markdown conversion
- `scripts/convert_pdf_simple.py` - Simple PDF text extraction (pdfplumber-based)
- `scripts/convert_pdf_with_vision.py` - Vision-based PDF conversion (recommended for math)

### Recommended Usage

**For papers with complex math formulas:**

```bash
# Step 1: Convert PDF to images (DPI 300, 2-column split by default)
./scripts/convert_pdf_with_vision.py paper.pdf -o papers/paper_name/images

# Step 2: Read images with Claude and extract content manually
# This provides the highest accuracy for mathematical formulas
```

**For quick text extraction:**

```bash
./scripts/convert_pdf_simple.py paper.pdf -o output.md
```

## Directory Structure

```
papers/
├── ARXIV_ID/
│   ├── source/              # LaTeX source files (if available)
│   ├── pdf/                 # PDF file
│   ├── images/              # Vision-based: page images
│   │   ├── page_001_full.png    # Full page
│   │   ├── page_001_col1.png    # Left column
│   │   └── page_001_col2.png    # Right column
│   ├── figures/             # Extracted figures
│   └── ARXIV_ID.md          # Generated Markdown
```

## Vision-Based PDF Conversion Details

### Why Vision-Based Approach?

Traditional PDF text extraction struggles with:

- Small superscripts/subscripts (e.g., $K_2^x$, $K_4^\tau$)
- Complex mathematical formulas
- 2-column layouts causing text interleaving
- Scanned or older PDF papers

Vision-based conversion solves these by:

1. Converting PDF to high-resolution images (300 DPI default)
2. Splitting 2-column pages into separate column images
3. Using Claude's vision capabilities for accurate reading
4. Extracting formulas in proper LaTeX format

### Image Resolution Guide

| DPI | Use Case | File Size | Formula Clarity |
|-----|----------|-----------|----------------|
| 200 | Preview, modern PDFs | Small | Good |
| 300 | **Recommended default** | Medium | Excellent |
| 400+ | Very old/poor quality | Large | Maximum |

### Column Splitting

For 2-column academic papers, splitting provides:

- **2x larger text**: Each column processed at full image width
- **Better context**: Column-by-column reading matches natural flow
- **Clearer superscripts**: Small text becomes readable

**Default behavior**: Automatically splits into 2 columns at 300 DPI

```bash
# Default (recommended)
./scripts/convert_pdf_with_vision.py paper.pdf

# Disable splitting
./scripts/convert_pdf_with_vision.py paper.pdf --no-split

# Custom column count
./scripts/convert_pdf_with_vision.py paper.pdf --columns 3

# Higher resolution
./scripts/convert_pdf_with_vision.py paper.pdf --dpi 400
```
