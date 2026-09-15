"""Contract tests for convert-paper routing decisions.

Contract: an explicit --tex-file override must always route to the
LaTeX conversion path, regardless of what the top-level source/*.tex
auto-detection finds. Silently falling through to the PDF branch (or
any other path) would make the explicit override unusable for source
layouts where the real entrypoint lives in a subdirectory, or where
source/ contains no top-level .tex files at all.

``main()`` runs in the test process with only its own metadata lookup
replaced. The steps it starts are real child processes, which read that
lookup from the handoff file, so nothing here reaches the network.
"""

import json
import shutil
import sys

import pytest

from arxiv_doc_builder import convert_paper
from arxiv_doc_builder.arxiv_metadata import METADATA_OK, ArxivMetadata, MetadataFetch

_SENTINEL_TITLE = "Routing Sentinel Title"


def test_tex_file_forces_latex_path_even_with_no_top_level_tex(
    tmp_path, monkeypatch, capfd
):
    # Build a source tree that has NO top-level .tex under source/ —
    # only a subdirectory entrypoint. Without the override guard,
    # auto-detection would fall through to the PDF branch and exit with
    # "PDF file not found", ignoring the user's explicit --tex-file.
    # Use a canonical-form placeholder so validate_arxiv_id accepts it;
    # the routing contract does not depend on the specific ID.
    arxiv_id = "2409.03108"
    version = f"{arxiv_id}v2"
    paper_dir = tmp_path / arxiv_id
    source_dir = paper_dir / "source"
    subdir = source_dir / "sub"
    subdir.mkdir(parents=True)
    tex_file = subdir / "main.tex"
    tex_file.write_text(
        "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n",
        encoding="utf-8",
    )
    # Seed a non-empty PDF so the idempotent fetch_pdf() skips the
    # network (existence-based: non-empty file → cache hit).
    pdf_dir = paper_dir / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / f"{arxiv_id}.pdf").write_bytes(b"%PDF-stub")
    # Seed the drift record with the lookup's version. Without it any reported
    # version reads as drift, and the fetch step discards the seeded source and
    # downloads again.
    (paper_dir / ".arxiv-fetch.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )

    lookup = MetadataFetch(
        METADATA_OK, metadata=ArxivMetadata(title=_SENTINEL_TITLE, version=version)
    )
    monkeypatch.setattr(convert_paper, "fetch_metadata", lambda _id: lookup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "convert_paper.py",
            arxiv_id,
            "--output-dir",
            str(tmp_path),
            "--tex-file",
            str(tex_file),
        ],
    )

    if shutil.which("pandoc"):
        convert_paper.main()
        out = capfd.readouterr().out
        # Only a LaTeX child that read the handoff can have written this title.
        document = (paper_dir / f"{arxiv_id}.md").read_text(encoding="utf-8")
        assert f'title: "{_SENTINEL_TITLE}"' in document
    else:
        # Without pandoc the LaTeX child exits before it reads metadata. Step 2
        # is printed only after the fetch child exited 0, and that child reads
        # the handoff at its drift check, so the network guard still covers it.
        with pytest.raises(SystemExit) as exit_info:
            convert_paper.main()
        assert exit_info.value.code == 1
        out = capfd.readouterr().out
        assert "Step 2: Converting to Markdown" in out

    # Positive assertion: the explicit-override routing marker must be
    # printed, proving the LaTeX branch was entered.
    assert "Using explicit --tex-file" in out, out

    # Negative assertion: the PDF branch must NOT have been taken. Its
    # own marker string would indicate a routing regression.
    assert "falling back to naive PDF conversion" not in out, out
