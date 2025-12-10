# arXiv Skills Repository

Custom Claude skills for working with arXiv papers - fetching, searching, and converting to reference documentation.

## Available Skills

### 1. arxivterminal

CLI tool integration for fetching and searching arXiv papers locally.

**Use when:** Managing arXiv papers with the `arxiv` command (arxivterminal package).

**Features:**

- Fetch papers by category and date range
- Search local database (with semantic search)
- View papers by publication date
- Database management and statistics

### 2. arxiv-doc-builder

Convert arXiv papers (PDF or LaTeX source) into well-structured Markdown documentation.

**Use when:** Creating readable reference documentation from arXiv papers for implementation work.

**Features:**

- **Vision-based PDF conversion**: High-accuracy extraction of mathematical formulas using Claude's vision capabilities
- Automatic PDF/LaTeX source fetching
- LaTeX → Markdown conversion (with pandoc)
- Column splitting for 2-column papers (better detail on small text)
- Mathematical formula preservation in LaTeX format (MathJax compatible)
- Section structure preservation
- Multiple conversion approaches: vision-based (accurate), text extraction (fast)

## Repository Structure

```
.
├── skills/              # Custom skills
│   ├── arxivterminal/   # arXiv CLI tool integration
│   └── arxiv-doc-builder/  # Paper to Markdown converter
├── template/            # Template for creating new skills
├── papers/              # Generated paper documentation (gitignored)
└── README.md
```

## Creating a New Skill

### Option 1: Manual Creation

1. Copy the template folder:

   ```bash
   cp -r template skills/your-skill-name
   ```

2. Edit `skills/your-skill-name/SKILL.md`:
   - Update `name` to match your skill folder name
   - Write a comprehensive `description` (this is how Claude decides when to use the skill)
   - Add your instructions in the body

3. Add resources as needed:
   - `scripts/` - Python/Bash scripts for deterministic operations
   - `references/` - Documentation to load into context as needed
   - `assets/` - Files used in output (templates, images, etc.)

### Option 2: Using skill-creator (from Anthropic repo)

If you have access to the Anthropic skills repository's `skill-creator`:

```bash
python /path/to/skill-creator/scripts/init_skill.py your-skill-name --path ./skills/
```

## Skill Design Principles

1. **Concise descriptions** - The context window is shared
2. **Progressive disclosure** - Keep SKILL.md under 500 lines, use references for details
3. **Clear triggers** - Specify when Claude should use this skill
4. **Self-contained** - Include all necessary scripts and references

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

## Quick Start

### arxivterminal

Fetch and search arXiv papers:

```bash
# Fetch papers from the last 3 days
arxiv fetch --num-days 3 --categories cs.AI,cs.CL

# Search for papers
arxiv search -e -l 20 "large language models"

# Check statistics
arxiv stats
```

### arxiv-doc-builder

**Option 1: Vision-based conversion (recommended for accurate math)**

```bash
# Step 1: Convert PDF to high-resolution images
cd skills/arxiv-doc-builder
./scripts/convert_pdf_with_vision.py "paper.pdf"
# Generates: papers/paper_name/images/ with page images at 300 DPI + column splits

# Step 2: Use Claude to read images and extract content with accurate LaTeX formulas
```

**Option 2: Quick text extraction**

```bash
# Fast but less accurate for complex formulas
./scripts/convert_pdf_simple.py "paper.pdf" -o output.md
```

**Option 3: Full workflow with arXiv ID**

```bash
# Automatically fetch and convert
python scripts/convert_paper.py 2409.03108
# Output: papers/2409.03108/2409.03108.md
```

**Requirements:**

- Python 3.8+
- pandoc (for LaTeX conversion: `brew install pandoc`)
- poppler-utils (for PDF to image: `brew install poppler`)
- Dependencies auto-installed via uv

## Using Your Skills

### In Claude Code

Install as a local plugin:

```bash
/plugin install /path/to/this/repo
```

### In Claude.ai

Upload the skill folder or packaged .skill file via the Skills menu.

## Resources

- [Agent Skills Specification](https://github.com/anthropics/skills/blob/main/spec/agent-skills-spec.md)
- [Creating Custom Skills Guide](https://support.claude.com/en/articles/12512198-creating-custom-skills)
- [Example Skills](https://github.com/anthropics/skills)
- [arXiv API Documentation](https://arxiv.org/help/api)
