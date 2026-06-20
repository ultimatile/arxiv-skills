#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pdf2image", "pypdf", "pillow"]
# ///
"""
Convert PDF to Markdown by converting pages to images and reading them.

This script converts PDFs to images, which can then be read by Claude
using the Read tool to extract text and mathematical formulas accurately.

Thin argv shim: the conversion logic lives in pdf_image_lib.convert_pdf_to_images.
"""

import argparse
import sys
from pathlib import Path

# Importable both as a package member (e.g. `python -m
# arxiv_doc_builder.convert_pdf_with_vision` after installing the `pdf` extra)
# and as a bare sibling script under `uv run --no-project` (sys.path[0] is this
# script's directory, where the package is not installed). Narrow to a missing
# top-level package so an ImportError raised *inside* pdf_image_lib isn't masked.
try:
    from arxiv_doc_builder.pdf_image_lib import convert_pdf_to_images
except ModuleNotFoundError as _exc:
    if _exc.name != "arxiv_doc_builder":
        raise
    from pdf_image_lib import convert_pdf_to_images


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to images for Claude vision-based processing"
    )
    parser.add_argument("pdf_path", type=Path, help="Path to PDF file")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Output directory for images (default: papers/PDFNAME/images)",
    )
    parser.add_argument(
        "--dpi", type=int, default=300, help="Image resolution in DPI (default: 300)"
    )
    parser.add_argument(
        "--no-split",
        action="store_true",
        help="Disable column splitting (default: split into 2 columns)",
    )
    parser.add_argument(
        "--columns", type=int, default=2, help="Number of columns to split (default: 2)"
    )

    args = parser.parse_args()

    if not args.pdf_path.exists():
        print(f"Error: PDF file not found: {args.pdf_path}")
        sys.exit(1)

    # Default output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        paper_name = args.pdf_path.stem
        output_dir = Path("papers") / paper_name / "images"

    convert_pdf_to_images(
        args.pdf_path,
        output_dir,
        args.dpi,
        split_columns=not args.no_split,
        num_columns=args.columns,
    )


if __name__ == "__main__":
    main()
