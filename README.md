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
- Automatic PDF/LaTeX source fetching
- LaTeX → Markdown conversion (with pandoc)
- Figure extraction and embedding
- Mathematical formula preservation (MathJax compatible)
- Section structure preservation

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
Convert a paper to Markdown:
```bash
# Convert paper 2409.03108
python skills/arxiv-doc-builder/scripts/convert_paper.py 2409.03108

# Output: papers/2409.03108/2409.03108.md
```

**Requirements:**
- Python 3.7+
- pandoc (install: `brew install pandoc`)
- curl

## Using Your Skills

### In Claude Code

Install as a local plugin:
```bash
/plugin install /path/to/this/repo
```

### In Claude.ai

Upload the skill folder or packaged .skill file via the Skills menu.

## Example Workflow

1. **Fetch papers** using `arxivterminal`:
   ```bash
   arxiv fetch --num-days 7 --categories cs.AI
   ```

2. **Search for relevant papers**:
   ```bash
   arxiv search -e "neural networks"
   ```

3. **Convert paper to documentation**:
   ```bash
   python skills/arxiv-doc-builder/scripts/convert_paper.py 2409.03108
   ```

4. **Use the Markdown documentation** for implementation reference

## Development

### Adding New Skills

Follow the skill creation guide in the template directory.

### Generated Files

The `papers/` directory contains generated documentation and is ignored by git. Add it to `.gitignore`:
```
papers/
*.skill
```

## Resources

- [Agent Skills Specification](https://github.com/anthropics/skills/blob/main/spec/agent-skills-spec.md)
- [Creating Custom Skills Guide](https://support.claude.com/en/articles/12512198-creating-custom-skills)
- [Example Skills](https://github.com/anthropics/skills)
- [arXiv API Documentation](https://arxiv.org/help/api)
