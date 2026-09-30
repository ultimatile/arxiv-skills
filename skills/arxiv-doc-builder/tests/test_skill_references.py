"""Every `references/*.md` path the agent is sent to names a file that exists.

SKILL.md keeps only the condition under which a procedure applies and the
reference file that holds it, so a pointer naming a missing file leaves the
agent with the condition and no procedure. The test scans SKILL.md, every
`.md` file in references/, the source of every module in the package (comments
and messages alike), and the evaluated remedy `convert_latex.py` prints when
it kills a runaway pandoc.

The same holds for the package scripts the agent is told to run: every one a
command in SKILL.md or references/ names exists, under a path the agent can
run from its own working directory.
"""

import re

import pytest

from arxiv_doc_builder import convert_latex
from conftest import PACKAGE_DIR, SKILL_DIR

_REFERENCE = re.compile(r"references/[\w.-]+\.md")

# The procedures SKILL.md sends the agent to when a situation it names holds.
# Each must be reachable from SKILL.md, since SKILL.md is what the agent has
# loaded.
_CONDITIONAL_REFERENCES = {
    "references/multiple-documentclass.md",
    "references/pandoc-failures.md",
    "references/unknown-arity-macros.md",
    "references/pandoc-runaway.md",
    "references/pdf-conversion.md",
    "references/source-edits.md",
}


def _markdown_sources() -> list[tuple[str, str]]:
    sources = [("SKILL.md", (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))]
    reference_files = sorted((SKILL_DIR / "references").glob("*.md"))
    assert reference_files, "no reference files found"
    sources += [
        (f"references/{p.name}", p.read_text(encoding="utf-8")) for p in reference_files
    ]
    return sources


def _pointer_sources() -> list[tuple[str, str]]:
    sources = _markdown_sources()
    # Module sources cover comments and single-literal messages; the evaluated
    # remedy covers the string the user sees, which its source splits across
    # adjacent literals.
    modules = sorted(PACKAGE_DIR.glob("*.py"))
    sources += [(p.name, p.read_text(encoding="utf-8")) for p in modules]
    sources.append(("_RUNAWAY_REMEDY", convert_latex._RUNAWAY_REMEDY))
    return sources


_SOURCES = _pointer_sources()


@pytest.mark.parametrize(("name", "text"), _SOURCES, ids=[name for name, _ in _SOURCES])
def test_every_reference_path_exists(name: str, text: str) -> None:
    missing = [
        ref for ref in _REFERENCE.findall(text) if not (SKILL_DIR / ref).is_file()
    ]
    assert not missing, f"{name} points at missing files: {missing}"


def test_skill_md_points_at_every_conditional_procedure() -> None:
    skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert _CONDITIONAL_REFERENCES <= set(_REFERENCE.findall(skill_md))


def test_runaway_remedy_names_a_reference_file() -> None:
    # Without a token, the existence check above passes on nothing.
    assert "references/pandoc-runaway.md" in _REFERENCE.findall(
        convert_latex._RUNAWAY_REMEDY
    )


# A command the agent runs names a package script by a path starting at the
# skill root. The agent runs it from its own working directory, where that path
# resolves only if the literal placeholder `SKILL_DIR/` (which SKILL.md tells
# the agent to replace with the skill root's absolute path) comes right before
# it. Prose outside fenced blocks may name a module without being a command.
_FENCE = re.compile(r"^\s*```")
_SCRIPT_PATH = re.compile(r"(\S*?)arxiv_doc_builder/([\w.-]+\.py)")

# The files that carry such commands; without them the check below could pass
# on nothing, for instance if an indented fence stopped being recognized.
_FILES_WITH_SCRIPT_COMMANDS = {"SKILL.md", "references/pdf-conversion.md"}


def _script_commands(text: str) -> list[tuple[str, str]]:
    """Each script a fenced line names, as (what precedes it, script name)."""
    commands = []
    inside = False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
        elif inside:
            commands += [m.groups() for m in _SCRIPT_PATH.finditer(line)]
    return commands


def test_script_commands_scan_fenced_lines_only() -> None:
    text = (
        "See `arxiv_doc_builder/prose.py`.\n"
        "   ```bash\n"
        "   uv run arxiv_doc_builder/bare.py x\n"
        "   uv run --project SKILL_DIR SKILL_DIR/arxiv_doc_builder/prefixed.py\n"
        "   ```\n"
        "arxiv_doc_builder/after.py\n"
    )
    assert _script_commands(text) == [("", "bare.py"), ("SKILL_DIR/", "prefixed.py")]


_MARKDOWN = _markdown_sources()


@pytest.mark.parametrize(
    ("name", "text"), _MARKDOWN, ids=[name for name, _ in _MARKDOWN]
)
def test_script_commands_start_at_skill_dir(name: str, text: str) -> None:
    commands = _script_commands(text)
    unprefixed = [script for prefix, script in commands if prefix != "SKILL_DIR/"]
    assert not unprefixed, f"{name} runs scripts without SKILL_DIR/: {unprefixed}"
    missing = [script for _, script in commands if not (PACKAGE_DIR / script).is_file()]
    assert not missing, f"{name} runs scripts that do not exist: {missing}"


def test_script_commands_are_found() -> None:
    carrying = {name for name, text in _MARKDOWN if _script_commands(text)}
    assert _FILES_WITH_SCRIPT_COMMANDS <= carrying
