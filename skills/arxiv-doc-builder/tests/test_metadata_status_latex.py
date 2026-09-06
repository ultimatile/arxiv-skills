"""The LaTeX path's recorded status, and when it warns.

``test_arxiv_metadata.py`` covers the frontmatter producer. Handing it a token
cannot catch a caller that always reports ``ok`` or never warns, which is why
these drive the caller and read the status back out of the document it wrote.

Kept apart from the PDF-path tests to stay importable without the optional PDF
dependencies. Each test replaces the caller's ``fetch_metadata``, so nothing
here reaches arXiv.
"""

from conftest import PROBE_ERROR, status_of

from arxiv_doc_builder import convert_latex
from arxiv_doc_builder.arxiv_metadata import METADATA_OK, METADATA_UNAVAILABLE
import pytest


@pytest.fixture
def latex_inputs(tmp_path):
    """A converted-markdown file and the ``.tex`` its title falls back to."""
    tex = tmp_path / "main.tex"
    tex.write_text(r"\title{Fallback~Title}" + "\n", encoding="utf-8")
    md = tmp_path / "2606.09995.md"
    md.write_text("body\n", encoding="utf-8")
    return md, tex


def test_latex_path_records_unavailable_and_warns(
    patch_fetch, capsys, latex_inputs, failed_probe
):
    md, tex = latex_inputs
    patch_fetch(convert_latex, failed_probe)

    convert_latex.post_process_markdown(md, "2606.09995", tex)

    assert status_of(md) == METADATA_UNAVAILABLE
    err = capsys.readouterr().err
    assert "2606.09995" in err
    assert PROBE_ERROR in err
    # The title still comes from the LaTeX source, and reaches the document
    # with the non-breaking space normalized.
    assert 'title: "Fallback Title"' in md.read_text(encoding="utf-8")


def test_latex_path_records_ok_and_stays_silent(
    patch_fetch, capsys, latex_inputs, probe_with_version
):
    # Without this, a path that warns unconditionally would pass the test above.
    md, tex = latex_inputs
    patch_fetch(convert_latex, probe_with_version)

    convert_latex.post_process_markdown(md, "2606.09995", tex)

    assert status_of(md) == METADATA_OK
    assert capsys.readouterr().err == ""
