"""Tests for the pdf2image-based image library.

The pure kernel (split_image_columns) and the pypdf metadata helper run with no
external binary. The full convert_pdf_to_images path needs poppler
(pdf2image.convert_from_path shells out to pdftoppm), so its smoke test is
skipped when poppler is absent rather than failing the suite.
"""

import importlib
import shutil
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from arxiv_doc_builder.pdf_image_lib import (
    convert_pdf_to_images,
    extract_metadata,
    split_image_columns,
)

_NO_POPPLER = shutil.which("pdftoppm") is None


def _write_pdf(path: Path, *, title: str | None = None, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if title is not None:
        writer.add_metadata({"/Title": title})
    with path.open("wb") as fh:
        writer.write(fh)
    return path


class TestSplitImageColumns:
    @pytest.mark.parametrize("width", [100, 101])
    def test_two_columns_tile_width_exactly(self, width):
        # Boundaries derived in the plan: i=0 -> [0, W//2), i=1 (last) -> [W//2, W),
        # an exact gapless non-overlapping cover. The right column is one pixel
        # wider for odd W.
        img = Image.new("RGB", (width, 40))
        cols = split_image_columns(img, num_columns=2)
        assert [c.size for c in cols] == [(width // 2, 40), (width - width // 2, 40)]
        assert sum(c.size[0] for c in cols) == width

    def test_three_columns_tile_width_exactly(self):
        width = 101
        img = Image.new("RGB", (width, 30))
        cols = split_image_columns(img, num_columns=3)
        # Last column absorbs the division remainder; widths still sum to W.
        assert sum(c.size[0] for c in cols) == width
        assert len(cols) == 3


class TestExtractMetadata:
    def test_title_from_embedded_metadata(self, tmp_path):
        pdf = _write_pdf(tmp_path / "m.pdf", title="Vision Paper", pages=2)
        meta = extract_metadata(pdf)
        assert meta["title"] == "Vision Paper"
        assert meta["total_pages"] == 2

    def test_missing_title_falls_back_to_stem(self, tmp_path):
        # Display-oriented variant: unlike the converter lib, a missing title
        # falls back to the file stem (and author to "Unknown") for direct print.
        pdf = _write_pdf(tmp_path / "fallback.pdf")
        meta = extract_metadata(pdf)
        assert meta["title"] == "fallback"
        assert meta["author"] == "Unknown"


class TestShimsImportAsPackageMembers:
    @pytest.mark.parametrize(
        "module",
        [
            "arxiv_doc_builder.convert_pdf_with_vision",
            "arxiv_doc_builder.convert_pdf_split_columns",
        ],
    )
    def test_shim_resolves_shared_lib_under_package_import(self, module):
        # The shims must resolve their pdf_image_lib import when loaded as
        # package members (the `python -m arxiv_doc_builder.<shim>` path), not
        # only as bare scripts under uv. A regression to a bare
        # `from pdf_image_lib import ...` raises ModuleNotFoundError here, since
        # pdf_image_lib is not a top-level module. Importing runs the module's
        # top level but not main() (guarded by __name__ == "__main__").
        importlib.import_module(module)


@pytest.mark.skipif(_NO_POPPLER, reason="poppler (pdftoppm) not installed")
class TestConvertPdfToImages:
    def test_single_page_produces_full_plus_two_columns(self, tmp_path):
        pdf = _write_pdf(tmp_path / "doc.pdf", title="T")
        out_dir = tmp_path / "images"
        image_paths, metadata = convert_pdf_to_images(pdf, out_dir, dpi=72)
        # One full-page image + two column images for the single page.
        assert len(image_paths) == 3
        assert metadata["total_pages"] == 1
        assert all(p.exists() for p in image_paths)
