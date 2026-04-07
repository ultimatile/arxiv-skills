#!/usr/bin/env python3
"""
Main orchestrator for converting arXiv papers to Markdown.

Handles fetching and conversion automatically.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def safe_arxiv_id(arxiv_id: str) -> str:
    """Normalize arXiv ID for filesystem paths."""
    return arxiv_id.replace("/", "_")


def run_script(script_name: str, args: list, use_uv: bool = False) -> bool:
    """Run a Python script with arguments."""
    script_path = Path(__file__).parent / script_name
    if use_uv:
        cmd = ["uv", "run", "--no-project", str(script_path)] + args
    else:
        cmd = [sys.executable, str(script_path)] + args

    result = subprocess.run(cmd)
    return result.returncode == 0


def has_documentclass(tex_file: Path) -> bool:
    """Return True when a .tex file looks like a primary LaTeX entrypoint."""
    try:
        content = tex_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "\\documentclass" in content


def list_tex_candidates(source_dir: Path, max_candidates: int = 10) -> list[Path]:
    """Select .tex candidates ordered by quality, then size (largest first)."""
    tex_files = [p for p in source_dir.glob("*.tex") if p.is_file()]
    if not tex_files:
        return []

    ranked = sorted(
        tex_files,
        key=lambda p: (
            0 if has_documentclass(p) else 1,
            -p.stat().st_size,
            p.name,
        ),
    )
    return ranked[:max_candidates]


def convert_with_pdf_fallback(paper_dir: Path, normalized_arxiv_id: str) -> bool:
    """Convert from PDF if LaTeX conversion is unavailable or failed."""
    print("Using PDF conversion fallback...")

    pdf_file = paper_dir / "pdf" / f"{normalized_arxiv_id}.pdf"
    if not pdf_file.exists():
        pdf_file = paper_dir / f"{normalized_arxiv_id}.pdf"
    if not pdf_file.exists():
        print(f"✗ PDF file not found in {paper_dir}")
        return False

    return run_script(
        "convert_pdf_simple.py",
        [str(pdf_file), "-o", str(paper_dir / f"{normalized_arxiv_id}.md")],
        use_uv=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert arXiv paper to Markdown documentation"
    )
    parser.add_argument("arxiv_id", help="arXiv ID (e.g., 2409.03108)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Output directory (default: current directory)"
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip fetching (use existing files)"
    )

    args = parser.parse_args()

    normalized_arxiv_id = safe_arxiv_id(args.arxiv_id)
    paper_dir = args.output_dir / normalized_arxiv_id
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
    if source_dir.exists():
        tex_candidates = list_tex_candidates(source_dir, max_candidates=10)
    else:
        tex_candidates = []

    if tex_candidates:
        print(
            f"LaTeX source detected, trying up to {len(tex_candidates)} .tex candidate(s)..."
        )
        output_md = paper_dir / f"{normalized_arxiv_id}.md"

        latex_success = False
        for index, tex_file in enumerate(tex_candidates, 1):
            print(
                f"[{index}/{len(tex_candidates)}] Trying LaTeX conversion with {tex_file.name}"
            )
            if run_script(
                "convert_latex.py",
                [
                    args.arxiv_id,
                    "--source-dir",
                    str(source_dir),
                    "--output",
                    str(output_md),
                    "--tex-file",
                    tex_file.name,
                ],
            ):
                latex_success = True
                break
            print(f"Failed with {tex_file.name}, trying next candidate...")

        if not latex_success:
            print("\nLaTeX conversion failed for all candidate .tex files")
            if not convert_with_pdf_fallback(paper_dir, normalized_arxiv_id):
                print("\n✗ PDF fallback conversion failed")
                sys.exit(1)
    else:
        print("No LaTeX source, using PDF conversion...")
        if not convert_with_pdf_fallback(paper_dir, normalized_arxiv_id):
            print("\n✗ PDF conversion failed")
            sys.exit(1)

    print()
    print("=" * 60)
    print("✓ Conversion complete!")
    print(f"Output: {paper_dir / f'{normalized_arxiv_id}.md'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
