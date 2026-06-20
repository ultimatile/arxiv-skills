"""Tests for the pdfplumber-based converter library.

These import the tier as a package member, which only resolves when the `pdf`
extra is installed (the dev group pulls it in). The pure helpers
(parse_page_ranges / clean_text / header / footer detection) need no PDF at all;
extract_metadata and convert_pdf_to_markdown drive a pypdf-written PDF so the
text-extraction path is exercised without poppler.
"""

from pathlib import Path

import pytest
from pypdf import PdfWriter

from arxiv_doc_builder.pdf_converter_lib import (
    clean_text,
    convert_pdf_to_markdown,
    extract_metadata,
    is_likely_footer,
    is_likely_header,
    parse_page_ranges,
)


def _write_pdf(
    path: Path, *, title: str | None = None, author: str | None = None, pages: int = 1
) -> Path:
    """Write a blank-page PDF with optional embedded metadata.

    Blank pages carry no text layer, so pdfplumber's extract_text returns None —
    enough to exercise the no-text branch and the metadata/frontmatter paths
    without needing a real typeset document or the poppler binary.
    """
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    embedded = {}
    if title is not None:
        embedded["/Title"] = title
    if author is not None:
        embedded["/Author"] = author
    if embedded:
        writer.add_metadata(embedded)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


class TestParsePageRanges:
    def test_mixed_ranges_and_singles(self):
        assert parse_page_ranges("1-3,5,7-9") == {1, 2, 3, 5, 7, 8, 9}

    def test_whitespace_tolerated(self):
        assert parse_page_ranges(" 1 - 2 , 4 ") == {1, 2, 4}

    def test_single_page(self):
        assert parse_page_ranges("7") == {7}

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_is_empty_set(self, empty):
        assert parse_page_ranges(empty) == set()


class TestCleanText:
    def test_collapses_whitespace(self):
        assert clean_text("a   b\t c\n d") == "a b c d"

    def test_fixes_ligatures(self):
        assert clean_text("ﬁ ﬂ ﬀ") == "fi fl ff"

    def test_empty_returns_empty(self):
        assert clean_text("") == ""


class TestHeaderFooterDetection:
    def test_header_matches_journal_banner_case_insensitively(self):
        assert is_likely_header("physical review b") is True
        assert is_likely_header("VOLUME 12") is True

    def test_header_rejects_plain_text_and_empty(self):
        assert is_likely_header("Introduction") is False
        assert is_likely_header("") is False

    def test_footer_matches_page_number_only(self):
        assert is_likely_footer("  42 ") is True
        assert is_likely_footer("12 and text") is False

    def test_footer_matches_copyright_markers(self):
        assert is_likely_footer("© 2024 The American Physical Society") is True
        assert is_likely_footer("Copyright notice") is True

    def test_footer_rejects_empty(self):
        assert is_likely_footer("") is False


class TestExtractMetadata:
    def test_returns_embedded_title_and_author(self, tmp_path):
        pdf = _write_pdf(tmp_path / "m.pdf", title="A Title", author="An Author")
        meta = extract_metadata(pdf)
        assert meta["title"] == "A Title"
        assert meta["author"] == "An Author"

    def test_missing_title_author_stay_none(self, tmp_path):
        # No synthesis: absent title/author must surface as None so the
        # frontmatter renders null rather than a filename-derived guess.
        pdf = _write_pdf(tmp_path / "bare.pdf")
        meta = extract_metadata(pdf)
        assert meta["title"] is None
        assert meta["author"] is None


class TestConvertPdfToMarkdown:
    def test_blank_pdf_emits_frontmatter_and_no_text_marker(self, tmp_path):
        pdf = _write_pdf(tmp_path / "doc.pdf", title="Probe Paper")
        out = tmp_path / "doc.md"
        # arxiv_id=None keeps it offline: the PDF's embedded metadata drives the
        # frontmatter and no arXiv fetch is attempted.
        convert_pdf_to_markdown(pdf, out, arxiv_id=None)
        text = out.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "source_type: " in text
        assert "pdf" in text
        assert "Probe Paper" in text
        assert "No text extracted" in text
