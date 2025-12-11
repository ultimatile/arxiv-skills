# arXiv Skills Repository

Custom Claude skills for working with arXiv papers - fetching, searching, and converting to reference documentation.

## Available Skills

### 1. arxivterminal

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

## Installation

### Install to Your Project

```bash
# Clone this repository
git clone <this-repo-url> arxiv-skills
cd arxiv-skills

# Install all skills to current project
./install-skills.sh

# Or install to custom location
SKILLS_INSTALL_PATH=/path/to/project/.claude/skills ./install-skills.sh

# Install only specific skill
./install-skills.sh --arxivterminal
./install-skills.sh --arxiv-doc-builder
```

Skills will be installed to `.claude/skills/` in your current directory by default.

**Requirements:**

- Python 3.8+
- pandoc (for LaTeX conversion: `brew install pandoc`)
- poppler-utils (for advanced PDF processing: `brew install poppler`)
- Python dependencies auto-installed via uv
