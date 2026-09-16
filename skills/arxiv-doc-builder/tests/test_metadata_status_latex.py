"""The LaTeX path's recorded status, and when it warns.

``test_arxiv_metadata.py`` covers the frontmatter producer. Handing it a token
cannot catch a caller that always reports ``ok`` or never warns, which is why
these drive the caller and read the status back out of the document it wrote.

Kept apart from the PDF-path tests to stay importable without the optional PDF
dependencies. Each test replaces the caller's ``fetch_metadata`` or hands it a
lookup, so nothing here reaches the network.
"""

import subprocess
import sys

from conftest import PROBE_ERROR, refuse_lookup, status_of

from arxiv_doc_builder import convert_latex
from arxiv_doc_builder.arxiv_metadata import (
    METADATA_OK,
    METADATA_UNAVAILABLE,
    write_metadata_handoff,
)
import pytest


@pytest.fixture
def latex_inputs(tmp_path):
    """A converted-markdown file and the ``.tex`` its title falls back to."""
    tex = tmp_path / "main.tex"
    tex.write_text(r"\title{Fallback~Title}" + "\n", encoding="utf-8")
    md = tmp_path / "2606.09995.md"
    md.write_text("body\n", encoding="utf-8")
    return md, tex


def test_latex_path_records_unavailable_and_warns(
    patch_fetch, capsys, latex_inputs, failed_probe
):
    md, tex = latex_inputs
    patch_fetch(convert_latex, failed_probe)

    convert_latex.post_process_markdown(md, "2606.09995", tex)

    assert status_of(md) == METADATA_UNAVAILABLE
    err = capsys.readouterr().err
    assert "2606.09995" in err
    assert PROBE_ERROR in err
    # The title still comes from the LaTeX source, and reaches the document
    # with the non-breaking space normalized.
    assert 'title: "Fallback Title"' in md.read_text(encoding="utf-8")


def test_latex_path_records_ok_and_stays_silent(
    patch_fetch, capsys, latex_inputs, probe_with_version
):
    # Without this, a path that warns unconditionally would pass the test above.
    md, tex = latex_inputs
    patch_fetch(convert_latex, probe_with_version)

    convert_latex.post_process_markdown(md, "2606.09995", tex)

    assert status_of(md) == METADATA_OK
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("probe_name", "status"),
    [("probe_with_version", METADATA_OK), ("failed_probe", METADATA_UNAVAILABLE)],
)
def test_latex_path_given_a_handoff_uses_it_without_looking_up(
    monkeypatch, request, capsys, tmp_path, latex_inputs, probe_name, status
):
    md, tex = latex_inputs
    handoff = tmp_path / "handoff.json"
    write_metadata_handoff(handoff, "2606.09995", request.getfixturevalue(probe_name))
    monkeypatch.setattr(convert_latex, "fetch_metadata", refuse_lookup)

    convert_latex.post_process_markdown(md, "2606.09995", tex, metadata_handoff=handoff)

    assert status_of(md) == status
    # A handed-over failure still reaches the user with its cause.
    err = capsys.readouterr().err
    assert (PROBE_ERROR in err) == (status == METADATA_UNAVAILABLE)


def test_latex_main_hands_its_handoff_path_to_post_processing(monkeypatch, tmp_path):
    # Observed without pandoc: conversion and figure copying are replaced, so
    # the only thing left to check is what main() passes on.
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    handoff = tmp_path / "handoff.json"
    received = {}

    def record(md_file, arxiv_id, tex_file, **kwargs):
        received.update(kwargs, arxiv_id=arxiv_id)

    monkeypatch.setattr(
        convert_latex.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    monkeypatch.setattr(convert_latex, "convert_with_pandoc", lambda tex, out: True)
    monkeypatch.setattr(convert_latex, "post_process_markdown", record)
    monkeypatch.setattr(convert_latex, "copy_figures", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "convert_latex.py",
            "2606.09995",
            "--source-dir",
            str(source),
            "--output",
            str(tmp_path / "out.md"),
            "--metadata-handoff",
            str(handoff),
        ],
    )

    convert_latex.main()

    assert received == {"arxiv_id": "2606.09995", "metadata_handoff": handoff}
