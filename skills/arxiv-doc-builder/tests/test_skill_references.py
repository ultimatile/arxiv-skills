"""Every `references/*.md` path the agent is sent to names a file that exists.

SKILL.md keeps only the condition under which a procedure applies and the
reference file that holds it, so a pointer naming a missing file leaves the
agent with the condition and no procedure. The test scans SKILL.md, every
`.md` file in references/, the source of every module in the package (comments
and messages alike), and the evaluated remedy `convert_latex.py` prints when
it kills a runaway pandoc.
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


def _pointer_sources() -> list[tuple[str, str]]:
    sources = [("SKILL.md", (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))]
    reference_files = sorted((SKILL_DIR / "references").glob("*.md"))
    assert reference_files, "no reference files found"
    sources += [
        (f"references/{p.name}", p.read_text(encoding="utf-8")) for p in reference_files
    ]
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
