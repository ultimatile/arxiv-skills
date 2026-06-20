#!/usr/bin/env python3
"""
Main orchestrator for converting arXiv papers to Markdown.

Handles fetching and conversion automatically.
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Importable both as a package member (entry point) and as a bare script.
# Narrow to ModuleNotFoundError + name check so an ImportError raised
# *inside* arxiv_id.py isn't silently masked by the script-mode fallback.
try:
    from arxiv_doc_builder.arxiv_id import safe_arxiv_id, validate_arxiv_id
    from arxiv_doc_builder._version import read_version
except ModuleNotFoundError as _exc:
    if _exc.name != "arxiv_doc_builder":
        raise
    from arxiv_id import safe_arxiv_id, validate_arxiv_id
    from _version import read_version


def run_script(script_name: str, args: list, use_uv: bool = False) -> int:
    """Run a Python script with arguments and return its exit code.

    Returning the raw returncode (instead of a bool) lets callers distinguish
    semantically meaningful non-zero codes — e.g., exit code 2 from
    convert_latex.py signals "ambiguous main .tex" and must be propagated
    instead of collapsed into a generic failure.
    """
    script_path = Path(__file__).parent / script_name
    if use_uv:
        cmd = ["uv", "run", "--no-project", str(script_path)] + args
    else:
        cmd = [sys.executable, str(script_path)] + args

    result = subprocess.run(cmd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Convert arXiv paper to Markdown documentation"
    )
    # action="version" prints and exits before any other parsing, so
    # `convert-paper --version` works without a positional arxiv_id.
    # read_version() runs at parser-build time, but it is a cheap metadata
    # / TOML read.
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {read_version()}",
    )
    parser.add_argument("arxiv_id", help="arXiv ID (e.g., 2409.03108)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--tex-file",
        type=Path,
        help="Specify the main .tex file directly "
        "(required when multiple \\documentclass files are present)",
    )

    args = parser.parse_args()

    try:
        validate_arxiv_id(args.arxiv_id)
    except ValueError as e:
        # Exit 1 (generic failure). Exit 2 is reserved for the
        # "ambiguous main .tex" signal propagated from convert_latex.py
        # below, which wrappers may retry with --tex-file.
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    normalized_arxiv_id = safe_arxiv_id(args.arxiv_id)
    paper_dir = args.output_dir / normalized_arxiv_id
    source_dir = paper_dir / "source"

    print("=" * 60)
    print("arXiv Paper to Markdown Converter")
    print(f"Paper ID: {args.arxiv_id}")
    print("=" * 60)
    print()

    # Step 1: Fetch materials (idempotent — skips network when files exist)
    print("Step 1: Fetching paper materials...")
    print("-" * 60)
    rc = run_script(
        "fetch_paper.py", [args.arxiv_id, "--output-dir", str(args.output_dir)]
    )
    if rc != 0:
        print("\n✗ Fetching failed")
        sys.exit(1)
    print()

    # Step 2: Convert to Markdown
    print("Step 2: Converting to Markdown...")
    print("-" * 60)

    # Decide LaTeX vs PDF path. An explicit --tex-file always forces the
    # LaTeX path: the auto-detection here only globs the top level of
    # source/, but some arXiv layouts put the real entrypoint in a
    # subdirectory, and --tex-file is advertised as a direct override.
    has_top_level_tex = source_dir.exists() and list(source_dir.glob("*.tex"))
    if args.tex_file or has_top_level_tex:
        if args.tex_file:
            print(
                f"Using explicit --tex-file {args.tex_file}, running LaTeX conversion..."
            )
        else:
            print("LaTeX source detected, using LaTeX conversion...")
        latex_args = [
            args.arxiv_id,
            "--source-dir",
            str(source_dir),
            "--output",
            str(paper_dir / f"{normalized_arxiv_id}.md"),
        ]
        if args.tex_file:
            latex_args += ["--tex-file", str(args.tex_file)]
        rc = run_script("convert_latex.py", latex_args)
        if rc != 0:
            # Exit code 2 signals ambiguous main .tex — the child already
            # printed a detailed stderr message with candidate paths and
            # a re-run suggestion, so we just propagate the code.
            if rc == 2:
                sys.exit(2)
            print("\n✗ LaTeX conversion failed")
            sys.exit(1)
    else:
        print("No LaTeX source, falling back to naive PDF conversion...")
        print("⚠ This uses single-column text extraction only.")
        print("  Output quality varies — inspect the result and consider")
        print("  using convert_pdf_double_column.py or convert_pdf_extract.py")
        print("  if the output is garbled.")
        # Check both possible PDF locations
        pdf_file = paper_dir / "pdf" / f"{normalized_arxiv_id}.pdf"
        if not pdf_file.exists():
            pdf_file = paper_dir / f"{normalized_arxiv_id}.pdf"
        if not pdf_file.exists():
            print(f"✗ PDF file not found in {paper_dir}")
            sys.exit(1)

        rc = run_script(
            "convert_pdf_simple.py",
            [
                str(pdf_file),
                "-o",
                str(paper_dir / f"{normalized_arxiv_id}.md"),
                "--arxiv-id",
                args.arxiv_id,
            ],
            use_uv=True,
        )
        if rc != 0:
            print("\n✗ PDF conversion failed")
            sys.exit(1)

    print()
    print("=" * 60)
    print("✓ Conversion complete!")
    print(f"Output: {paper_dir / f'{normalized_arxiv_id}.md'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
