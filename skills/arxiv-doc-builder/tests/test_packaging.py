"""Guards for the dependency-declaration contract.

The core install must stay dependency-free (the LaTeX happy path pulls nothing),
and the heavy PDF stack must remain an opt-in extra. Encoding this as a test —
rather than a comment in pyproject.toml — makes a regression (a stray runtime
dep added to the core, or the pdf extra losing a member) fail CI loudly.
"""

import tomllib
from pathlib import Path

import arxiv_doc_builder

# Resolve pyproject via the package location, matching test_version.py: tests
# live under tests/ while pyproject.toml sits at the project root.
_PYPROJECT = Path(arxiv_doc_builder.__file__).parent.parent / "pyproject.toml"


def _load() -> dict:
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def test_core_is_dependency_free():
    assert _load()["project"]["dependencies"] == []


def test_pdf_extra_lists_the_heavy_stack():
    extras = _load()["project"]["optional-dependencies"]["pdf"]
    # Compare on package names only, tolerant of any future version pins.
    names = {dep.split(">=")[0].split("==")[0].split("[")[0].strip() for dep in extras}
    assert names == {"pdfplumber", "pdf2image", "pypdf", "pillow"}
