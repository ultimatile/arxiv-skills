#!/usr/bin/env python3
"""
Shared library for PDF-to-image conversion.

Importable helpers lifted from convert_pdf_with_vision.py and
convert_pdf_split_columns.py so the image tier can be unit-tested and
typechecked. The scripts themselves stay thin argv shims that run under
`uv run --no-project` with their own PEP 723 inline deps (pdf2image / pypdf /
pillow). This module imports only those third-party packages plus stdlib, so —
unlike pdf_converter_lib.py — it needs no package-or-bare dual import.

The two conversion entry points keep distinct contracts on purpose:
convert_pdf_to_images is metadata-aware (prints title/author/total, returns the
metadata dict alongside the paths) for the vision workflow, while
convert_pdf_split_columns is leaner (prints only the page count, returns the
paths). Do not unify them.
"""

from pathlib import Path

from pdf2image import convert_from_path
from pypdf import PdfReader


def extract_metadata(pdf_path: Path) -> dict:
    """Extract PDF metadata for display.

    Unlike pdf_converter_lib.extract_metadata (which returns None for missing
    title/author so the frontmatter renders null), this display-oriented variant
    falls back to the file stem / "Unknown" because its consumers print the
    values directly for the human running the vision workflow.
    """
    reader = PdfReader(pdf_path)
    meta = reader.metadata

    return {
        "title": meta.title if meta and meta.title else pdf_path.stem,
        "author": meta.author if meta and meta.author else "Unknown",
        "total_pages": len(reader.pages),
    }


def split_image_columns(image, num_columns=2):
    """Split image into vertical columns.

    The last column absorbs the integer-division remainder so the columns
    exactly tile the page width [0, width) with no gap or overlap.
    """
    width, height = image.size
    column_width = width // num_columns

    columns = []
    for i in range(num_columns):
        left = i * column_width
        right = (i + 1) * column_width if i < num_columns - 1 else width
        column = image.crop((left, 0, right, height))
        columns.append(column)

    return columns


def convert_pdf_to_images(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 300,
    split_columns: bool = True,
    num_columns: int = 2,
):
    """Convert PDF to images, optionally splitting each page into columns.

    Returns ``(image_paths, metadata)``; prints title/author/total pages plus
    per-page progress for the vision workflow.
    """

    print(f"Converting PDF to images: {pdf_path}")
    print(f"Output directory: {output_dir}")
    print(f"DPI: {dpi}")
    print(f"Column splitting: {'Yes' if split_columns else 'No'}")
    if split_columns:
        print(f"Columns per page: {num_columns}")
    print()

    # Extract metadata
    metadata = extract_metadata(pdf_path)
    print(f"Title: {metadata['title']}")
    print(f"Author: {metadata['author']}")
    print(f"Total pages: {metadata['total_pages']}")
    print()

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert PDF to images
    print("Converting pages to images...")
    images = convert_from_path(pdf_path, dpi=dpi)

    image_paths = []
    for i, image in enumerate(images, 1):
        # Save full page
        full_page_path = output_dir / f"page_{i:03d}_full.png"
        image.save(full_page_path, "PNG")
        image_paths.append(full_page_path)
        print(f"✓ Page {i}/{len(images)} saved: {full_page_path.name}")

        # Split into columns if enabled
        if split_columns:
            columns = split_image_columns(image, num_columns)
            for col_idx, column in enumerate(columns, 1):
                col_path = output_dir / f"page_{i:03d}_col{col_idx}.png"
                column.save(col_path, "PNG")
                image_paths.append(col_path)
                print(f"  └─ Column {col_idx}: {col_path.name}")

    print()
    print()
    print("=" * 60)
    print("✓ Conversion complete!")
    print(f"Total images: {len(image_paths)}")
    if split_columns:
        print(f"  - Full pages: {len(images)}")
        print(f"  - Column images: {len(images) * num_columns}")
    print(f"Images saved in: {output_dir}")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Use Claude's Read tool to view each image")
    print("2. Extract text and mathematical formulas in LaTeX format")
    print("3. Combine into a Markdown document")
    print()
    if split_columns:
        print(
            "Tip: Process columns separately for better detail on small text/formulas"
        )
        print()

    return image_paths, metadata


def convert_pdf_split_columns(
    pdf_path: Path, output_dir: Path, dpi: int = 300, num_columns: int = 2
):
    """Convert PDF to images with column splitting.

    Returns ``image_paths``; prints only the page count and per-page progress.
    """

    print(f"Converting PDF with column splitting: {pdf_path}")
    print(f"Output directory: {output_dir}")
    print(f"DPI: {dpi}")
    print(f"Columns per page: {num_columns}")
    print()

    # Extract metadata
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    print(f"Total pages: {total_pages}")
    print()

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert PDF to images
    print("Converting pages to images...")
    images = convert_from_path(pdf_path, dpi=dpi)

    image_paths = []
    for i, image in enumerate(images, 1):
        # Save full page
        full_page_path = output_dir / f"page_{i:03d}_full.png"
        image.save(full_page_path, "PNG")
        image_paths.append(full_page_path)
        print(f"✓ Page {i}/{len(images)} full: {full_page_path.name}")

        # Split into columns
        columns = split_image_columns(image, num_columns)
        for col_idx, column in enumerate(columns, 1):
            col_path = output_dir / f"page_{i:03d}_col{col_idx}.png"
            column.save(col_path, "PNG")
            image_paths.append(col_path)
            print(f"  └─ Column {col_idx}: {col_path.name}")

    print()
    print("=" * 60)
    print("✓ Conversion complete!")
    print(f"Total images: {len(image_paths)}")
    print(f"  - Full pages: {len(images)}")
    print(f"  - Column images: {len(images) * num_columns}")
    print(f"Images saved in: {output_dir}")
    print("=" * 60)

    return image_paths
