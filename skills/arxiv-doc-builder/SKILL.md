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

**From PDF**:

- **If pdf skill is available**: Use the pdf skill for better extraction quality
- Otherwise, extract text with pdfplumber
- Detect section structure
- Extract figures
- Handle tables
- See [pdf-conversion.md](references/pdf-conversion.md) for details

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

- `scripts/fetch_paper.py` - Unified paper fetching (tries source, falls back to PDF)
- `scripts/convert_latex.py` - LaTeX to Markdown conversion
- `scripts/convert_pdf.py` - PDF to Markdown conversion
- `scripts/convert_paper.py` - Main conversion orchestrator

## Directory Structure

```
papers/
├── ARXIV_ID/
│   ├── source/          # LaTeX source files
│   ├── pdf/             # PDF file
│   ├── figures/         # Extracted figures
│   └── ARXIV_ID.md      # Generated Markdown
```
