#!/usr/bin/env python3
"""
Main orchestrator for converting arXiv papers to Markdown.

Handles fetching and conversion automatically.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_script(script_name: str, args: list) -> bool:
    """Run a Python script with arguments."""
    script_path = Path(__file__).parent / script_name
    cmd = [sys.executable, str(script_path)] + args

    result = subprocess.run(cmd)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Convert arXiv paper to Markdown documentation"
    )
    parser.add_argument("arxiv_id", help="arXiv ID (e.g., 2409.03108)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("papers"),
        help="Output directory (default: ./papers)"
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip fetching (use existing files)"
    )

    args = parser.parse_args()

    paper_dir = args.output_dir / args.arxiv_id
    source_dir = paper_dir / "source"

    print("=" * 60)
    print(f"arXiv Paper to Markdown Converter")
    print(f"Paper ID: {args.arxiv_id}")
    print("=" * 60)
    print()

    # Step 1: Fetch materials
    if not args.skip_fetch:
        print("Step 1: Fetching paper materials...")
        print("-" * 60)
        if not run_script(
            "fetch_paper.py",
            [args.arxiv_id, "--output-dir", str(args.output_dir)]
        ):
            print("\n✗ Fetching failed")
            sys.exit(1)
        print()

    # Step 2: Convert to Markdown
    print("Step 2: Converting to Markdown...")
    print("-" * 60)

    # Check if source is available
    if source_dir.exists() and list(source_dir.glob("*.tex")):
        print("LaTeX source detected, using LaTeX conversion...")
        if not run_script(
            "convert_latex.py",
            [args.arxiv_id, "--source-dir", str(source_dir)]
        ):
            print("\n✗ LaTeX conversion failed")
            sys.exit(1)
    else:
        print("No LaTeX source, using PDF conversion...")
        # PDF conversion not yet implemented
        print("✗ PDF conversion not yet implemented")
        print("  Please implement convert_pdf.py")
        sys.exit(1)

    print()
    print("=" * 60)
    print("✓ Conversion complete!")
    print(f"Output: {paper_dir / f'{args.arxiv_id}.md'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
