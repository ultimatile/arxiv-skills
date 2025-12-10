#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pdfplumber", "pypdf"]
# ///
"""
Simple PDF to Markdown converter using pdfplumber.

This approach extracts text reliably without heavy OCR dependencies.
Mathematical formulas are preserved as-is from the PDF text layer.
"""

import argparse
import sys
from pathlib import Path
import pdfplumber
from pypdf import PdfReader


def clean_text(text):
    """Clean extracted text by removing excessive whitespace."""
    if not text:
        return ""

    # Replace multiple spaces with single space
    text = ' '.join(text.split())

    # Fix common PDF extraction issues
    text = text.replace('ﬁ', 'fi')
    text = text.replace('ﬂ', 'fl')
    text = text.replace('ﬀ', 'ff')

    return text


def extract_metadata(pdf_path):
    """Extract PDF metadata."""
    reader = PdfReader(pdf_path)
    meta = reader.metadata

    return {
        'title': meta.title if meta and meta.title else pdf_path.stem,
        'author': meta.author if meta and meta.author else 'Unknown',
        'subject': meta.subject if meta and meta.subject else '',
        'creator': meta.creator if meta and meta.creator else '',
    }


def is_likely_header(text):
    """Check if text is likely a page header."""
    if not text:
        return False

    # Common header patterns
    header_indicators = [
        'PHYSICAL REVIEW',
        'VOLUME',
        'NUMBER',
    ]

    return any(indicator in text.upper() for indicator in header_indicators)


def is_likely_footer(text):
    """Check if text is likely a page footer."""
    if not text:
        return False

    # Just page numbers or very short text
    if text.strip().isdigit():
        return True

    # Copyright or journal info
    footer_indicators = [
        'The American Physical Society',
        '©',
        'Copyright',
    ]

    return any(indicator in text for indicator in footer_indicators)


def extract_page_content(page, page_num):
    """Extract content from a single page."""
    text = page.extract_text()

    if not text:
        return f"\n<!-- Page {page_num}: No text extracted -->\n"

    lines = text.split('\n')
    cleaned_lines = []

    for i, line in enumerate(lines):
        # Skip headers on first few lines
        if i < 3 and is_likely_header(line):
            continue

        # Skip footers on last few lines
        if i >= len(lines) - 3 and is_likely_footer(line):
            continue

        cleaned = clean_text(line)
        if cleaned:
            cleaned_lines.append(cleaned)

    # Join lines with proper spacing
    content = '\n\n'.join(cleaned_lines)

    # Extract tables if any
    tables = page.extract_tables()
    if tables:
        table_content = "\n\n"
        for j, table in enumerate(tables):
            table_content += f"**Table {j+1}:**\n\n"

            # Convert to markdown table
            if table and len(table) > 0:
                # Header
                header = table[0]
                table_content += "| " + " | ".join(str(cell) if cell else "" for cell in header) + " |\n"
                table_content += "|" + "|".join(["---"] * len(header)) + "|\n"

                # Rows
                for row in table[1:]:
                    table_content += "| " + " | ".join(str(cell) if cell else "" for cell in row) + " |\n"

                table_content += "\n"

        content += table_content

    return content


def convert_pdf_to_markdown(pdf_path: Path, output_path: Path):
    """Convert PDF to Markdown using pdfplumber."""

    print(f"Converting PDF: {pdf_path}")
    print(f"Output: {output_path}")
    print()

    # Extract metadata
    metadata = extract_metadata(pdf_path)
    print(f"Title: {metadata['title']}")
    print(f"Author: {metadata['author']}")
    print()

    # Open PDF with pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"Total pages: {total_pages}")
        print()

        # Prepare markdown content
        markdown_parts = []

        # Add metadata header
        header = f"""# {metadata['title']}

**Author:** {metadata['author']}

**Source:** `{pdf_path.name}`

**Converted:** PDF to Markdown using pdfplumber

**Total Pages:** {total_pages}

---

"""
        markdown_parts.append(header)

        # Process each page
        for i, page in enumerate(pdf.pages, 1):
            print(f"Processing page {i}/{total_pages}...")

            try:
                page_content = extract_page_content(page, i)

                # Add page marker and content
                markdown_parts.append(f"\n\n<!-- Page {i} -->\n\n")
                markdown_parts.append(page_content)

                print(f"✓ Page {i} processed ({len(page_content)} chars)")

            except Exception as e:
                print(f"✗ Error processing page {i}: {e}")
                markdown_parts.append(f"\n\n<!-- Page {i}: Error - {e} -->\n\n")

        print()

        # Combine all content
        full_markdown = ''.join(markdown_parts)

        # Add notes section
        notes = """

---

## Notes

- This document was converted from PDF using pdfplumber
- Mathematical formulas are preserved from the PDF text layer
- Some formatting may require manual adjustment
- Complex equations may need to be formatted as LaTeX
- Please review and verify the content accuracy

"""
        full_markdown += notes

        # Save to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(full_markdown, encoding='utf-8')

        print("=" * 60)
        print("✓ Conversion complete!")
        print(f"Output saved to: {output_path}")
        print(f"Total size: {len(full_markdown)} characters")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to Markdown using pdfplumber (simple approach)"
    )
    parser.add_argument(
        "pdf_path",
        type=Path,
        help="Path to PDF file"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output Markdown file path (default: same name as PDF with .md extension)"
    )

    args = parser.parse_args()

    if not args.pdf_path.exists():
        print(f"Error: PDF file not found: {args.pdf_path}")
        sys.exit(1)

    output_path = args.output or args.pdf_path.with_suffix('.md')

    convert_pdf_to_markdown(args.pdf_path, output_path)


if __name__ == "__main__":
    main()
