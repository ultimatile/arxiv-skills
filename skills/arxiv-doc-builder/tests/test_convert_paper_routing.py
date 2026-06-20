"""Contract tests for convert-paper routing decisions.

Contract: an explicit --tex-file override must always route to the
LaTeX conversion path, regardless of what the top-level source/*.tex
auto-detection finds. Silently falling through to the PDF branch (or
any other path) would make the explicit override unusable for source
layouts where the real entrypoint lives in a subdirectory, or where
source/ contains no top-level .tex files at all.
"""

import subprocess
import sys
from pathlib import Path

import arxiv_doc_builder


def test_tex_file_forces_latex_path_even_with_no_top_level_tex(tmp_path):
    # Build a source tree that has NO top-level .tex under source/ —
    # only a subdirectory entrypoint. Without the override guard,
    # auto-detection would fall through to the PDF branch and exit with
    # "PDF file not found", ignoring the user's explicit --tex-file.
    # Use a canonical-form placeholder so validate_arxiv_id accepts it;
    # the routing contract does not depend on the specific ID.
    arxiv_id = "2409.03108"
    paper_dir = tmp_path / arxiv_id
    source_dir = paper_dir / "source"
    subdir = source_dir / "sub"
    subdir.mkdir(parents=True)
    tex_file = subdir / "main.tex"
    # A minimally valid LaTeX document. We do not care whether pandoc
    # can actually convert it — the contract is about routing only, and
    # the routing decision happens and is logged before convert_latex
    # ever invokes pandoc.
    tex_file.write_text(
        "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n",
        encoding="utf-8",
    )
    # Seed a non-empty PDF so the idempotent fetch_pdf() skips the
    # network (existence-based: non-empty file → cache hit).
    pdf_dir = paper_dir / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / f"{arxiv_id}.pdf").write_bytes(b"%PDF-stub")

    script = Path(arxiv_doc_builder.__file__).parent / "convert_paper.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            arxiv_id,
            "--output-dir",
            str(tmp_path),
            "--tex-file",
            str(tex_file),
        ],
        capture_output=True,
        text=True,
    )

    # Positive assertion: the explicit-override routing marker must be
    # printed, proving the LaTeX branch was entered.
    assert "Using explicit --tex-file" in result.stdout, (
        "Expected convert-paper to route to LaTeX on --tex-file override.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Negative assertion: the PDF branch must NOT have been taken. Its
    # own marker string would indicate a routing regression.
    assert "falling back to naive PDF conversion" not in result.stdout, (
        "convert-paper silently fell through to the PDF branch despite "
        "--tex-file being explicitly provided.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
