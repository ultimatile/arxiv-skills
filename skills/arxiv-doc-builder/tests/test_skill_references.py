"""Every `references/*.md` path the agent is sent to names a file that exists.

SKILL.md keeps only the condition under which a procedure applies and the
reference file that holds it, so a pointer naming a missing file leaves the
agent with the condition and no procedure. Pointers reach the agent from
SKILL.md, from the reference files themselves, and from the remedy
`convert_latex.py` prints when it kills a runaway pandoc.
"""

import re
from pathlib import Path

import pytest

import arxiv_doc_builder
from arxiv_doc_builder import convert_latex

# Resolve the skill root via the package location, matching test_packaging.py:
# tests live under tests/ while SKILL.md and references/ sit at the skill root.
_SKILL_DIR = Path(arxiv_doc_builder.__file__).parent.parent
_REFERENCE = re.compile(r"references/[\w.-]+\.md")

# The procedures that apply only after a failure or on the PDF-only path. Each
# must be reachable from SKILL.md, since SKILL.md is what the agent has loaded.
_CONDITIONAL_REFERENCES = {
    "references/multiple-documentclass.md",
    "references/pandoc-failures.md",
    "references/unknown-arity-macros.md",
    "references/pandoc-runaway.md",
    "references/pdf-conversion.md",
    "references/source-edits.md",
}


def _pointer_sources() -> list[tuple[str, str]]:
    sources = [("SKILL.md", (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))]
    reference_files = sorted((_SKILL_DIR / "references").glob("*.md"))
    assert reference_files, "no reference files found"
    sources += [
        (f"references/{p.name}", p.read_text(encoding="utf-8")) for p in reference_files
    ]
    # The source text covers comments; the evaluated remedy covers the string
    # the user sees, which the source splits across adjacent literals.
    convert_latex_py = Path(convert_latex.__file__)
    sources.append(("convert_latex.py", convert_latex_py.read_text(encoding="utf-8")))
    sources.append(("_RUNAWAY_REMEDY", convert_latex._RUNAWAY_REMEDY))
    return sources


_SOURCES = _pointer_sources()


@pytest.mark.parametrize(("name", "text"), _SOURCES, ids=[name for name, _ in _SOURCES])
def test_every_reference_path_exists(name: str, text: str) -> None:
    missing = [
        ref for ref in _REFERENCE.findall(text) if not (_SKILL_DIR / ref).is_file()
    ]
    assert not missing, f"{name} points at missing files: {missing}"


def test_skill_md_points_at_every_conditional_procedure() -> None:
    skill_md = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert _CONDITIONAL_REFERENCES <= set(_REFERENCE.findall(skill_md))


def test_runaway_remedy_names_a_reference_file() -> None:
    # Without a token, the existence check above passes on nothing.
    assert "references/pandoc-runaway.md" in _REFERENCE.findall(
        convert_latex._RUNAWAY_REMEDY
    )
