"""Guards for the dependency-declaration contract.

The core install must stay dependency-free (the LaTeX happy path pulls nothing),
and the heavy PDF stack must remain an opt-in extra. Encoding this as a test —
rather than a comment in pyproject.toml — makes a regression (a stray runtime
dep added to the core, or the pdf extra losing a member) fail CI loudly.
"""

import re
import tomllib
from pathlib import Path

import arxiv_doc_builder

# A PEP 508 dependency string starts with the distribution name, followed by
# optional extras / version specifiers / environment markers. The leading run of
# name characters is the name regardless of which specifier operator (>=, ==, ~=,
# <, !=, …), marker, or extra follows, so match that rather than splitting on a
# hand-picked subset of operators.
_PEP508_NAME = re.compile(r"[A-Za-z0-9._-]+")

# Resolve pyproject via the package location, matching test_version.py: tests
# live under tests/ while pyproject.toml sits at the project root.
_PYPROJECT = Path(arxiv_doc_builder.__file__).parent.parent / "pyproject.toml"


def _load() -> dict:
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _dist_name(dep: str) -> str:
    """Return the distribution name of a PEP 508 dependency string."""
    m = _PEP508_NAME.match(dep.strip())
    assert m is not None, f"no PEP 508 name in {dep!r}"
    return m.group()


def test_core_is_dependency_free():
    assert _load()["project"]["dependencies"] == []


def test_pdf_extra_lists_the_heavy_stack():
    extras = _load()["project"]["optional-dependencies"]["pdf"]
    # Compare on package names only, tolerant of any future version pins / markers.
    names = {_dist_name(dep) for dep in extras}
    assert names == {"pdfplumber", "pdf2image", "pypdf", "pillow"}
