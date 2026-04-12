# arXiv Skills Repository

Custom Claude skills for working with arXiv papers - fetching, searching, and converting to reference documentation.

## Available Skills

### 1. arxivterminal

> [!WARNING]
> **Deprecated — scheduled for removal at the end of April 2026.**
> The upstream `arxivterminal` CLI is effectively unmaintained, requires building and maintaining a local paper database up front before it can be used (heavier than the lightweight workflow this repo aims to provide), and has fallen behind newer arXiv API features.

CLI tool integration for fetching, searching, and managing arXiv papers locally using the `arxivterminal` command.

**Description:** Enables Claude to work with the arxivterminal CLI tool for fetching new papers by category, searching the local database, viewing papers from specific dates, and managing the local paper database.

**Use when:** You need Claude to manage arXiv papers using the `arxiv` command (from the arxivterminal package).

**Capabilities:**

- Fetch papers from arXiv by category and date range
- Search local database with semantic search
- View papers by publication date
- Check database statistics and manage stored papers

### 2. arxiv-doc-builder

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

### 3. arxiv-lookup

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
# Clone this repository if you haven't already
git clone https://github.com/ultimatile/arxiv-skills.git arxiv-skills

# Install with uv (editable: changes from git pull are reflected immediately)
uv tool install --editable arxiv-skills/skills/arxiv-doc-builder
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
