"""The PDF path's recorded status, and when it warns.

Counterpart to the LaTeX-path module, kept apart because building a fixture
document here needs the optional PDF dependencies.

Nothing reaches the network. Tests that supply an arXiv id replace the caller's
``fetch_metadata``, and the rest ask arXiv nothing.
"""

from pathlib import Path

import pytest
from conftest import PROBE_ERROR, status_of
from pypdf import PdfWriter

from arxiv_doc_builder import pdf_converter_lib
from arxiv_doc_builder.arxiv_metadata import (
    METADATA_NOT_REQUESTED,
    METADATA_OK,
    METADATA_UNAVAILABLE,
)


def _blank_pdf(path: Path, *, title: str, author: str) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title, "/Author": author})
    with path.open("wb") as fh:
        writer.write(fh)
    return path


@pytest.fixture
def pdf_inputs(tmp_path):
    """A PDF carrying an embedded title and author, and the output path."""
    pdf = _blank_pdf(tmp_path / "p.pdf", title="Embedded Title", author="Jane Doe")
    return pdf, tmp_path / "p.md"


def test_pdf_path_records_unavailable_and_warns(
    patch_fetch, capsys, pdf_inputs, failed_probe
):
    pdf, out = pdf_inputs
    patch_fetch(pdf_converter_lib, failed_probe)

    pdf_converter_lib.convert_pdf_to_markdown(pdf, out, arxiv_id="2606.09995")

    assert status_of(out) == METADATA_UNAVAILABLE
    assert PROBE_ERROR in capsys.readouterr().err
    # Both fields the PDF can supply are filled from it, which is why neither
    # is evidence that arXiv was reached. The status is.
    text = out.read_text(encoding="utf-8")
    assert 'title: "Embedded Title"' in text
    assert 'authors: "Jane Doe"' in text
    assert "\ndoi:\n" in text


def test_pdf_path_records_ok_when_the_record_was_read(
    patch_fetch, capsys, pdf_inputs, probe_with_version
):
    pdf, out = pdf_inputs
    patch_fetch(pdf_converter_lib, probe_with_version)

    pdf_converter_lib.convert_pdf_to_markdown(pdf, out, arxiv_id="2606.09995")

    assert status_of(out) == METADATA_OK
    assert capsys.readouterr().err == ""


def test_pdf_path_records_not_requested_and_stays_silent(capsys, pdf_inputs):
    # The manual PDF scripts run this way on every invocation, so treating it
    # as degraded would make the ordinary case look like an outage.
    pdf, out = pdf_inputs

    pdf_converter_lib.convert_pdf_to_markdown(pdf, out, arxiv_id=None)

    assert status_of(out) == METADATA_NOT_REQUESTED
    assert capsys.readouterr().err == ""


def test_an_empty_arxiv_id_is_treated_as_no_id_at_all(capsys, pdf_inputs):
    # argparse yields None for an omitted --arxiv-id, but a caller can pass an
    # empty string. Normalizing it at entry is what keeps the frontmatter
    # builder's id/status equivalence from rejecting the document: without it
    # the status says no id was supplied while the id argument says one was.
    pdf, out = pdf_inputs

    pdf_converter_lib.convert_pdf_to_markdown(pdf, out, arxiv_id="")

    assert status_of(out) == METADATA_NOT_REQUESTED
    assert "arxiv_id:\n" in out.read_text(encoding="utf-8")
    assert capsys.readouterr().err == ""
