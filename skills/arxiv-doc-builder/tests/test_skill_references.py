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
# resolves only if it starts with the literal placeholder `SKILL_DIR/`, which
# SKILL.md tells the agent to replace with the skill root's absolute path. The
# whole path sits in double quotes, so a skill root containing spaces stays one
# argument. Prose outside fenced blocks may name a module without being a
# command.
_FENCE = re.compile(r"^\s*```")
_SCRIPT_PATH = re.compile(r'(\S*?)arxiv_doc_builder/([\w.-]+\.py)("?)')
_QUOTED_PREFIX = '"SKILL_DIR/'

# The files that carry such commands; without them the check below could pass
# on nothing, for instance if an indented fence stopped being recognized.
_FILES_WITH_SCRIPT_COMMANDS = {"SKILL.md", "references/pdf-conversion.md"}


def _fenced_lines(text: str) -> list[str]:
    """The lines inside fenced code blocks, fences excluded."""
    lines = []
    inside = False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
        elif inside:
            lines.append(line)
    return lines


def _script_commands(text: str) -> list[tuple[str, str, str]]:
    """Each script a fenced line names, as (prefix, name, closing quote).

    The prefix is the non-space text right before ``arxiv_doc_builder/``; the
    closing quote is ``'"'`` when one follows the name, else ``""``.
    """
    return [c for line in _fenced_lines(text) for c in _SCRIPT_PATH.findall(line)]


def test_script_commands_scan_fenced_lines_only() -> None:
    text = (
        "See `arxiv_doc_builder/prose.py`.\n"
        "   ```bash\n"
        "   uv run arxiv_doc_builder/bare.py x\n"
        '   uv run --project "SKILL_DIR" "SKILL_DIR/arxiv_doc_builder/quoted.py" x\n'
        "   ```\n"
        "arxiv_doc_builder/after.py\n"
    )
    assert _script_commands(text) == [
        ("", "bare.py", ""),
        (_QUOTED_PREFIX, "quoted.py", '"'),
    ]


_MARKDOWN = _markdown_sources()


@pytest.mark.parametrize(
    ("name", "text"), _MARKDOWN, ids=[name for name, _ in _MARKDOWN]
)
def test_script_commands_start_at_skill_dir(name: str, text: str) -> None:
    commands = _script_commands(text)
    unquoted = [
        script
        for prefix, script, closing in commands
        if prefix != _QUOTED_PREFIX or closing != '"'
    ]
    assert not unquoted, f'{name} runs scripts not written "SKILL_DIR/...": {unquoted}'
    missing = [s for _, s, _ in commands if not (PACKAGE_DIR / s).is_file()]
    assert not missing, f"{name} runs scripts that do not exist: {missing}"


def test_script_commands_are_found() -> None:
    carrying = {name for name, text in _MARKDOWN if _script_commands(text)}
    assert _FILES_WITH_SCRIPT_COMMANDS <= carrying


# A script with a PEP 723 header gets an environment built from that header.
# One without it runs in whatever project uv picks, which older uv releases
# take from the working directory; there the skill's `requires-python` and
# dependencies are not guaranteed. Such a script's command therefore names
# the skill's own project.
_PEP_723_HEADER = "# /// script"
_SKILL_PROJECT = '--project "SKILL_DIR"'


def _has_inline_metadata(script: str) -> bool:
    return _PEP_723_HEADER in (PACKAGE_DIR / script).read_text(encoding="utf-8")


def test_scripts_without_inline_metadata_run_in_the_skill_project() -> None:
    headerless = [
        (name, line.strip())
        for name, text in _MARKDOWN
        for line in _fenced_lines(text)
        for _, script, _ in _SCRIPT_PATH.findall(line)
        if not _has_inline_metadata(script)
    ]
    # convert_paper.py is such a script, so the check has something to cover.
    assert headerless, "no command runs a script without a PEP 723 header"
    lacking = [(name, line) for name, line in headerless if _SKILL_PROJECT not in line]
    assert not lacking, f"commands without {_SKILL_PROJECT}: {lacking}"
