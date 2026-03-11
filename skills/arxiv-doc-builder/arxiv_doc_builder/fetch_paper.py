#!/usr/bin/env python3
"""
Fetch arXiv paper materials (source and/or PDF).

Tries to fetch LaTeX source first, falls back to PDF if unavailable.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def safe_arxiv_id(arxiv_id: str) -> str:
    """Normalize arXiv ID for filesystem paths."""
    return arxiv_id.replace("/", "_")


def _detect_file_type(path: Path) -> str:
    """Detect downloaded file type using the file command.

    arXiv source downloads come in several formats:
      - gzip-compressed tar archive (most common for multi-file submissions)
      - gzip-compressed single .tex file (common for older papers)
      - plain text .tex file (rare)

    The file command on the outer gzip layer cannot distinguish between a
    tar archive and a single file inside, so for gzip files we decompress
    and check the inner content.

    Returns one of: "tar", "gzip_single", "latex", "unknown"
    """
    result = subprocess.run(
        ["file", "--brief", str(path)],
        capture_output=True, text=True
    )
    desc = result.stdout.strip().lower()

    if "tar archive" in desc:
        return "tar"

    if "gzip" in desc:
        # Decompress and check the inner content type via pipe
        inner = subprocess.run(
            f'gunzip -c "{path}" | file --brief -',
            shell=True, capture_output=True, text=True
        )
        inner_desc = inner.stdout.strip().lower()
        if "tar archive" in inner_desc:
            return "tar"
        # Single file (LaTeX, text, etc.)
        return "gzip_single"

    if "latex" in desc or "tex" in desc or "ascii text" in desc:
        return "latex"
    return "unknown"


def _extract_gzip_single(downloaded: Path, source_dir: Path) -> bool:
    """Extract a single gzip-compressed file (not a tar archive).

    The file command output often contains the original filename, e.g.:
      "gzip compressed data, was \"main.tex\", ..."
    We use that to name the output file, falling back to main.tex.
    """
    # Try to recover the original filename from gzip metadata
    result = subprocess.run(
        ["file", "--brief", str(downloaded)],
        capture_output=True, text=True
    )
    desc = result.stdout.strip()

    original_name = "main.tex"
    if 'was "' in desc:
        # Extract name between quotes: was "foo.tex"
        start = desc.index('was "') + 5
        end = desc.index('"', start)
        original_name = desc[start:end]

    source_dir.mkdir(exist_ok=True)
    out_path = source_dir / original_name

    decompress = subprocess.run(
        ["gunzip", "-c", str(downloaded)],
        capture_output=True
    )
    if decompress.returncode != 0:
        print(f"Failed to decompress: {decompress.stderr.decode()}")
        return False

    out_path.write_bytes(decompress.stdout)
    print(f"✓ Source extracted to {out_path} (single gzip file)")
    return True


def fetch_source(arxiv_id: str, output_dir: Path, file_id: str) -> bool:
    """
    Fetch LaTeX source from arXiv.

    Handles three arXiv source formats:
      - tar.gz archive (most common)
      - single gzip-compressed .tex file (common for older papers)
      - plain text .tex file (rare)

    Returns:
        True if source was successfully fetched, False otherwise
    """
    source_url = f"https://arxiv.org/src/{arxiv_id}"
    downloaded = output_dir / f"{file_id}-src.tar.gz"
    source_dir = output_dir / "source"

    print(f"Fetching source from {source_url}...")

    result = subprocess.run(
        ["curl", "-f", "-L", "-o", str(downloaded), source_url],
        capture_output=True
    )

    if result.returncode != 0:
        print("Source not available (paper may be PDF-only)")
        return False

    # Detect file type and extract accordingly
    file_type = _detect_file_type(downloaded)
    print(f"  Detected source format: {file_type}")

    if file_type == "tar":
        source_dir.mkdir(exist_ok=True)
        result = subprocess.run(
            ["tar", "-xzf", str(downloaded), "-C", str(source_dir)],
            capture_output=True
        )
        if result.returncode != 0:
            print(f"Failed to extract source: {result.stderr.decode()}")
            return False
        print(f"✓ Source extracted to {source_dir}")

    elif file_type == "gzip_single":
        if not _extract_gzip_single(downloaded, source_dir):
            return False

    elif file_type == "latex":
        # Plain uncompressed .tex file
        source_dir.mkdir(exist_ok=True)
        dest = source_dir / "main.tex"
        dest.write_bytes(downloaded.read_bytes())
        print(f"✓ Source saved to {dest} (uncompressed)")

    else:
        print(f"Unknown source format: {file_type}")
        return False

    downloaded.unlink()  # Clean up downloaded file
    return True


def fetch_pdf(arxiv_id: str, output_dir: Path, file_id: str) -> bool:
    """
    Fetch PDF from arXiv.

    Returns:
        True if PDF was successfully fetched, False otherwise
    """
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_dir = output_dir / "pdf"
    pdf_file = pdf_dir / f"{file_id}.pdf"

    print(f"Fetching PDF from {pdf_url}...")

    pdf_dir.mkdir(exist_ok=True)
    result = subprocess.run(
        ["curl", "-f", "-L", "-o", str(pdf_file), pdf_url],
        capture_output=True
    )

    if result.returncode != 0:
        print(f"Failed to fetch PDF: {result.stderr.decode()}")
        return False

    print(f"✓ PDF saved to {pdf_file}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fetch arXiv paper materials")
    parser.add_argument("arxiv_id", help="arXiv ID (e.g., 2409.03108)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("papers"),
        help="Output directory (default: ./papers)"
    )
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="Skip source, fetch PDF only"
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Skip PDF, fetch source only"
    )

    args = parser.parse_args()

    normalized_arxiv_id = safe_arxiv_id(args.arxiv_id)

    # Create paper directory
    paper_dir = args.output_dir / normalized_arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching materials for arXiv:{args.arxiv_id}")
    print(f"Output directory: {paper_dir}")
    print()

    has_source = False
    has_pdf = False

    # Fetch source unless --pdf-only
    if not args.pdf_only:
        has_source = fetch_source(args.arxiv_id, paper_dir, normalized_arxiv_id)

    # Fetch PDF unless --source-only
    if not args.source_only:
        has_pdf = fetch_pdf(args.arxiv_id, paper_dir, normalized_arxiv_id)

    # Summary
    print()
    print("=" * 50)
    if has_source:
        print("✓ LaTeX source available")
    if has_pdf:
        print("✓ PDF available")

    if not has_source and not has_pdf:
        print("✗ Failed to fetch any materials")
        sys.exit(1)

    print(f"\nMaterials saved to: {paper_dir}")


if __name__ == "__main__":
    main()
