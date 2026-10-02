"""Contract tests for convert-paper routing decisions.

Contract: an explicit --tex-file override must always route to the
LaTeX conversion path, regardless of what the top-level source/*.tex
auto-detection finds. Silently falling through to the PDF branch (or
any other path) would make the explicit override unusable for source
layouts where the real entrypoint lives in a subdirectory, or where
source/ contains no top-level .tex files at all.

Contract: the PDF fallback converts only the file the fetch step writes,
``pdf/{id}.pdf`` in the paper's directory. A PDF anywhere else in that
directory is not converted, and the run exits 1 naming the path it looked
for.

The --tex-file test runs ``main()`` in the test process with only its own
metadata lookup replaced. The steps it starts are real child processes,
which read that lookup from the handoff file. The PDF-location test
replaces the step launcher as well, since the lookup under test is
``main()``'s own. Nothing here reaches the network.
"""

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from arxiv_doc_builder import convert_paper
from arxiv_doc_builder.arxiv_metadata import (
    METADATA_OK,
    METADATA_SOURCE_ARXIV,
    ArxivMetadata,
    MetadataFetch,
)

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
    # Seed a non-empty PDF so fetch_pdf() reuses it without a network request.
    # It does so only while the drift record below matches the lookup's version.
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
        METADATA_OK,
        metadata=ArxivMetadata(
            title=_SENTINEL_TITLE, version=version, source=METADATA_SOURCE_ARXIV
        ),
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
        # the handoff at its drift check, so a child looking the record up for
        # itself would still be observable here.
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


def test_a_pdf_outside_pdf_dir_is_not_converted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    patch_fetch: Callable[[object, MetadataFetch], None],
    probe_with_version: MetadataFetch,
) -> None:
    arxiv_id = "2409.03108"
    paper_dir = tmp_path / arxiv_id
    paper_dir.mkdir()
    # Directly in the paper's directory, where no step writes a PDF.
    (paper_dir / f"{arxiv_id}.pdf").write_bytes(b"%PDF-stub")

    started: list[str] = []

    def fake_run_script(script_name: str, args: list[str], use_uv: bool = False) -> int:
        started.append(script_name)
        return 0

    patch_fetch(convert_paper, probe_with_version)
    monkeypatch.setattr(convert_paper, "run_script", fake_run_script)
    monkeypatch.setattr(
        sys, "argv", ["convert_paper.py", arxiv_id, "--output-dir", str(tmp_path)]
    )

    with pytest.raises(SystemExit) as exit_info:
        convert_paper.main()

    assert exit_info.value.code == 1
    # The fetch step ran and no converter followed it, so the exit is the PDF
    # lookup's and not an earlier step's.
    assert started == ["fetch_paper.py"]
    assert str(paper_dir / "pdf" / f"{arxiv_id}.pdf") in capsys.readouterr().out
