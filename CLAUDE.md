# CLAUDE.md

Repo-specific rules for Claude Code when editing this repository.
Violations of any rule below are blockers — fix before declaring a task complete.

## Commit message conventions

These rules apply to every commit message and to every PR title.
A PR lands by squash merge, so its title becomes the commit message on `main`.

**Prohibited forms:**

- `refactor(<anything>): ...` on a commit that touches skill text (`SKILL.md` or anything under `references/`). The agent executes skill text, and no test shows that a reorganized instruction leaves the agent's behavior unchanged, so the claim `refactor` makes cannot be backed. `refactor` is available for code-only commits (see "Type selection").
- `<type>(skills): ...` — the literal scope name `skills` is forbidden. The `skills/` tree is the global context of this repo; using `skills` as a scope adds no information. Use a bare `<type>: ...` (no scope) for repo-wide changes, or name the specific skill(s).

**Type selection:**

Surface-specific overrides (apply first):

- **Documentation-only** change (top-level doc files including `README.md` and `CLAUDE.md`, anything under `docs/` if added later) → `docs` (regardless of add/remove). `SKILL.md` and `references/` are not documentation: the agent executes them, so they take the skill-text rule below.
- **Development tooling and repo metadata** — a surface no consumer of the installed plugin can observe, because no `SKILL.md` step reads or runs it: `.claude-plugin/marketplace.json`, `.pre-commit-config.yaml`, `.gitignore`, `ruff.toml`, other linter / formatter config, and a bundled test no `SKILL.md` invokes → `chore` (regardless of add/remove). Routine version bumps with no other change fall here (`chore: bump to <version>`). A file under `skills/` qualifies only when no `SKILL.md` step names it; anything a step names is skill content and takes the rules below.
- **Pure formatting pass** (whitespace, table padding, list renumbering, or any other output of a formatter such as `ruff format` with no semantic content change) → `style`, regardless of which files it touches (`skills/` included).

For changes to skill text (`SKILL.md`, `references/`), decide by the shape of the diff, not by intent:

- **Additions only** (new skill, new lines, no content removed or swapped) → `feat`
- **Removals or replacements** (line deletions, content swaps, reorganization) → `fix`

Here `feat` and `fix` name the diff shape, not "new capability" and "bug repair".
The plugin version is CalVer, so the type decides no version component, and a rule that needs no judgment keeps the log consistent.

For changes to code (the Python a skill ships, such as `arxiv_doc_builder/` and `scripts/`, and its packaging files), decide by behavior:

- New capability → `feat`
- Corrected behavior → `fix`
- Restructuring with behavior unchanged → `refactor`

For a commit that touches both skill text and code:

- The code part changes behavior → the code part's type (`feat` / `fix`).
- The code part only restructures → the skill-text rule decides. Never `refactor`.

**Scope selection:**

- Single skill change → `feat(<skill-name>): ...` / `fix(<skill-name>): ...` / `refactor(<skill-name>): ...`
- Multiple skills changed in one commit → `feat(<skill1>,<skill2>): ...` (comma-separated, no spaces)
- Repo-global change that touches no skill and doesn't fit a `docs` / `chore` surface override → no scope: `feat: ...` / `fix: ...`

`docs` commits per the type-selection overrides above carry no scope — that surface IS the entire change.
A `chore` commit takes the scope rules above: confined to one skill's directory it carries that skill's name, and a repo-global tooling surface leaves it bare.

## Worktree development

Before changing any file, create a git worktree on a new branch and do the work there.
Do not edit in the main checkout.
