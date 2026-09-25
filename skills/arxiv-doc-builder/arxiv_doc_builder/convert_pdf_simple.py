#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pdfplumber", "pypdf"]
# ///
"""
Simple PDF to Markdown converter - converts all pages as single-column.

This is the basic converter that processes all pages with single-column layout.
For double-column papers, use convert_pdf_double_column.py or convert_pdf_extract.py.
"""

import argparse
import sys
from pathlib import Path

# Import shared library
from arxiv_metadata import add_metadata_handoff_option
from pdf_converter_lib import convert_pdf_to_markdown


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to Markdown (all pages, single-column)",
        epilog="Example: %(prog)s paper.pdf -o output.md",
    )
    parser.add_argument("pdf_path", type=Path, help="Path to PDF file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output Markdown file path (default: same name as PDF with .md extension)",
    )
    parser.add_argument(
        "--arxiv-id", help="arXiv ID for authoritative frontmatter metadata (optional)"
    )
    add_metadata_handoff_option(parser)

    args = parser.parse_args()

    # A handoff describes one id's lookup, and --arxiv-id is optional here, so
    # this pairing is reachable from the command line. Refused by name at the
    # entry the user invoked: the converter refuses it too, but as a ValueError
    # naming neither the option nor this script. Exit 1, since exit 2 belongs
    # to the ambiguous-main-tex channel.
    if args.metadata_handoff is not None and not args.arxiv_id:
        print("Error: --metadata-handoff needs --arxiv-id", file=sys.stderr)
        sys.exit(1)

    if not args.pdf_path.exists():
        print(f"Error: PDF file not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or args.pdf_path.with_suffix(".md")

    # Convert all pages as single-column
    convert_pdf_to_markdown(
        pdf_path=args.pdf_path,
        output_path=output_path,
        pages_to_extract=None,  # All pages
        double_column_pages=None,  # Single-column
        arxiv_id=args.arxiv_id,
        metadata_handoff=args.metadata_handoff,
    )


if __name__ == "__main__":
    main()
