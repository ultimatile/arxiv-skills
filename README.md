# arXiv Skills Repository

Custom Claude skills for working with arXiv papers - fetching, searching, and converting to reference documentation.

## Available Skills

### 1. arxiv-doc-builder

Automatically convert arXiv papers to well-structured Markdown documentation for implementation reference.

**Description:** Automatically fetches arXiv papers (LaTeX source or PDF), converts them to Markdown, and generates implementation-ready reference documentation with preserved mathematics and section structure.

**Use when:** You need Claude to convert an arXiv paper into readable Markdown documentation for code implementation or research reference.

**Capabilities:**

- Automatic paper fetching with source→PDF fallback
- LaTeX source → Markdown conversion (via pandoc)
- PDF → Markdown text extraction
- Mathematical formula preservation in MathJax/LaTeX format
- Section structure and hierarchy preservation
- Advanced vision-based PDF conversion available for complex formulas

### 2. arxiv-lookup

Lightweight scripts for querying the arXiv API directly — get journal DOIs from arXiv IDs, or search for papers by title/keyword.

**Description:** Look up arXiv paper metadata via the arXiv API. Get journal DOIs from arXiv IDs (for OpenAlex integration), or find arXiv IDs from title/keyword search (for arxiv-doc-builder).

**Use when:** You need Claude to look up a paper's journal DOI, or find arXiv IDs by searching titles, authors, or categories.

**Capabilities:**

- Get journal DOI from an arXiv ID (`get_doi.py`)
- Search arXiv by title, author, abstract, or category (`search_id.py`)
- Supports arXiv API field prefixes (`ti:`, `au:`, `abs:`, `cat:`) and boolean operators

## Installation

```bash
claude plugin marketplace add ultimatile/arxiv-skills
claude plugin install arxiv-skills
```

### Install `convert-paper` as a Global CLI Tool

`arxiv-doc-builder` can also be installed as a standalone CLI tool to run `convert-paper` from anywhere:

```bash
uv tool install --from 'arxiv-doc-builder @ git+https://github.com/ultimatile/arxiv-skills.git#subdirectory=skills/arxiv-doc-builder'
```

```bash
# Usage
convert-paper 2409.03108
convert-paper 2409.03108 --output-dir ~/papers
```

**Requirements:**

- Python 3.8+
- pandoc (for LaTeX conversion: `brew install pandoc`)
- poppler-utils (for advanced PDF processing: `brew install poppler`)
- Python dependencies auto-installed via uv
