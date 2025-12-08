# Custom Skills Repository

This repository contains custom skills for Claude.

## Structure

```
.
├── skills/           # Your custom skills go here
├── template/         # Template for creating new skills
│   ├── SKILL.md
│   ├── scripts/      # Executable scripts
│   ├── references/   # Reference documentation
│   └── assets/       # Templates, images, fonts, etc.
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
