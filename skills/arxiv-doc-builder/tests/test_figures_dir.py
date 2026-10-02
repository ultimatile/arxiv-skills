"""Which files a conversion removes from the paper's ``figures/`` directory.

The ``convert_latex.main`` tests replace pandoc and the post-processing, and
the ``convert_paper.main`` tests replace the step launcher, so nothing here
needs pandoc or reaches the network.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import LAUNCH_ARXIV_ID, seed_cached_source, seed_pdf

from arxiv_doc_builder import convert_latex
from arxiv_doc_builder.figures_dir import RECORD_NAME, read_record, record_figures

_EARLIER = b"earlier revision"
_ARXIV_ID = "2606.09995"


@pytest.fixture
def paper(tmp_path: Path) -> SimpleNamespace:
    """A paper's directory with a ``source/`` holding one main ``.tex``."""
    paper_dir = tmp_path / "paper"
    seed_cached_source(paper_dir)
    return SimpleNamespace(
        dir=paper_dir,
        source=paper_dir / "source",
        figures=paper_dir / "figures",
        output=paper_dir / "paper.md",
    )


def _seed_copied(figures: Path, *names: str) -> None:
    """Leave ``figures`` as a LaTeX conversion that copied ``names`` would."""
    figures.mkdir(parents=True, exist_ok=True)
    for name in names:
        (figures / name).write_bytes(_EARLIER)
    record_figures(figures, names)


def _seed_unrecorded(figures: Path, name: str) -> Path:
    """Put a file in ``figures`` that no record names."""
    figures.mkdir(parents=True, exist_ok=True)
    path = figures / name
    path.write_bytes(_EARLIER)
    return path


def _entries(directory: Path) -> list[str]:
    """The names in ``directory``."""
    return sorted(e.name for e in directory.iterdir())


def _figures(directory: Path) -> list[str]:
    """The names in ``directory``, the record aside."""
    return [name for name in _entries(directory) if name != RECORD_NAME]


def _recorded(figures: Path) -> list[str]:
    return json.loads((figures / RECORD_NAME).read_text(encoding="utf-8"))["copied"]


# --- copy_figures ---------------------------------------------------------


def test_a_copy_removes_the_recorded_figures_it_does_not_copy_again(paper):
    # The earlier revision had three figures at the top level. The new one
    # dropped the first, moved the second into a subdirectory, and changed the
    # third. A link to the moved figure is rewritten to figures/moved.png, and
    # must not find the earlier revision's file there.
    for name in ("dropped.png", "moved.png", "kept.png"):
        (paper.source / name).write_bytes(_EARLIER)
    convert_latex.copy_figures(paper.source, paper.dir)
    assert _figures(paper.figures) == ["dropped.png", "kept.png", "moved.png"]

    (paper.source / "dropped.png").unlink()
    (paper.source / "sub").mkdir()
    (paper.source / "moved.png").rename(paper.source / "sub" / "moved.png")
    (paper.source / "kept.png").write_bytes(b"new revision")
    (paper.source / "added.pdf").write_bytes(b"new figure")
    convert_latex.copy_figures(paper.source, paper.dir)

    assert _figures(paper.figures) == ["added.pdf", "kept.png"]
    assert (paper.figures / "kept.png").read_bytes() == b"new revision"
    assert _recorded(paper.figures) == ["added.pdf", "kept.png"]


def test_a_copy_keeps_a_file_placed_by_hand(paper):
    _seed_copied(paper.figures, "copied.png")
    mine = _seed_unrecorded(paper.figures, "mine.png")
    nested = _seed_unrecorded(paper.figures / "extra", "diagram.png")

    convert_latex.copy_figures(paper.source, paper.dir)

    assert _figures(paper.figures) == ["extra", "mine.png"]
    assert mine.read_bytes() == _EARLIER
    assert nested.read_bytes() == _EARLIER


def test_a_copy_keeps_and_reports_files_no_record_covers(paper, capsys):
    # A directory an earlier version of the converter filled has no record,
    # so nothing says which of its files were copied. They stay, and the run
    # says so once: the record it writes makes the next run silent.
    old = _seed_unrecorded(paper.figures, "old.png")
    (paper.source / "fig.png").write_bytes(b"new revision")

    convert_latex.copy_figures(paper.source, paper.dir)

    assert _figures(paper.figures) == ["fig.png", "old.png"]
    assert old.read_bytes() == _EARLIER
    err = capsys.readouterr().err
    assert str(paper.figures) in err
    assert "1 item(s)" in err

    convert_latex.copy_figures(paper.source, paper.dir)

    assert capsys.readouterr().err == ""
    assert _figures(paper.figures) == ["fig.png", "old.png"]


def test_a_copy_creates_the_directory_and_an_empty_record_without_images(paper):
    assert not paper.figures.exists()

    convert_latex.copy_figures(paper.source, paper.dir)

    assert paper.figures.is_dir()
    assert _figures(paper.figures) == []
    assert _recorded(paper.figures) == []


def test_a_copy_that_fails_partway_is_cleaned_up_by_the_next(paper):
    # A directory named like an image stops the copy after one file has
    # arrived: .png files are copied before .jpg ones. The file that arrived
    # is recorded, so the next run removes it once the source no longer has
    # it.
    (paper.source / "arrived.png").write_bytes(b"new revision")
    (paper.source / "blocks.jpg").mkdir()
    with pytest.raises(OSError):
        convert_latex.copy_figures(paper.source, paper.dir)
    assert _figures(paper.figures) == ["arrived.png"]
    assert _recorded(paper.figures) == ["arrived.png"]

    (paper.source / "arrived.png").unlink()
    (paper.source / "blocks.jpg").rmdir()
    convert_latex.copy_figures(paper.source, paper.dir)

    assert _figures(paper.figures) == []


def test_a_copy_that_fails_partway_keeps_the_figures_it_did_not_reach(paper):
    # The blocker is a .png and so comes before the .jpg an earlier run
    # copied. That figure is still in the source, so it is overwritten in
    # place when its turn comes, never removed ahead of the copy.
    _seed_copied(paper.figures, "kept.jpg")
    (paper.source / "kept.jpg").write_bytes(b"new revision")
    (paper.source / "blocks.png").mkdir()

    with pytest.raises(OSError):
        convert_latex.copy_figures(paper.source, paper.dir)

    assert (paper.figures / "kept.jpg").read_bytes() == _EARLIER
    assert _recorded(paper.figures) == ["kept.jpg"]


def test_a_copy_that_fails_partway_does_not_claim_a_file_placed_by_hand(paper):
    # The source has a figure of the same name as the hand-placed file, but
    # the copy stops before reaching it. The file was never overwritten, so it
    # is not recorded, and it outlives the source dropping that figure.
    mine = _seed_unrecorded(paper.figures, "mine.jpg")
    record_figures(paper.figures, [])
    (paper.source / "mine.jpg").write_bytes(b"new revision")
    (paper.source / "blocks.png").mkdir()
    with pytest.raises(OSError):
        convert_latex.copy_figures(paper.source, paper.dir)
    assert _recorded(paper.figures) == []

    (paper.source / "mine.jpg").unlink()
    (paper.source / "blocks.png").rmdir()
    convert_latex.copy_figures(paper.source, paper.dir)

    assert mine.read_bytes() == _EARLIER


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs a user that a read-only file stops",
)
def test_a_copy_that_cannot_write_a_file_does_not_record_it(paper):
    # The hand-placed file is read-only, so the copy over it fails. A name
    # joins the record only after its file is written, so this one does not,
    # and the file outlives the source dropping that figure.
    mine = _seed_unrecorded(paper.figures, "mine.png")
    record_figures(paper.figures, [])
    mine.chmod(0o444)
    (paper.source / "mine.png").write_bytes(b"new revision")
    with pytest.raises(OSError):
        convert_latex.copy_figures(paper.source, paper.dir)
    assert _recorded(paper.figures) == []

    (paper.source / "mine.png").unlink()
    convert_latex.copy_figures(paper.source, paper.dir)

    assert mine.read_bytes() == _EARLIER


def test_a_copy_into_the_source_directory_removes_no_source_figure(paper):
    # figures/ is a link to the source, so every figure this run copies is
    # also a recorded one from the run before. Only recorded names the run
    # does not copy again are removed, which leaves the source whole.
    paper.figures.symlink_to(paper.source, target_is_directory=True)
    (paper.source / "a.png").write_bytes(b"source figure")

    convert_latex.copy_figures(paper.source, paper.dir)
    convert_latex.copy_figures(paper.source, paper.dir)

    assert (paper.source / "a.png").read_bytes() == b"source figure"
    assert (paper.source / "main.tex").exists()


def test_a_copy_round_trips_names_json_has_to_escape(paper):
    names = ["a b.png", 'quo"te.png', "back\\slash.png", "図.png"]
    for name in names:
        (paper.source / name).write_bytes(_EARLIER)
    convert_latex.copy_figures(paper.source, paper.dir)
    assert _figures(paper.figures) == sorted(names)

    for name in names:
        (paper.source / name).unlink()
    convert_latex.copy_figures(paper.source, paper.dir)

    assert _figures(paper.figures) == []


@pytest.mark.parametrize(
    "record",
    [
        "not json",
        "[]",
        '{"copied": "a.png"}',
        '{"copied": [1]}',
        "[" * 100_000 + "]" * 100_000,
    ],
    ids=["not-json", "not-an-object", "not-a-list", "not-names", "too-deep"],
)
def test_a_record_that_cannot_be_used_removes_nothing(paper, capsys, record):
    kept = _seed_unrecorded(paper.figures, "a.png")
    (paper.figures / RECORD_NAME).write_text(record, encoding="utf-8")

    convert_latex.copy_figures(paper.source, paper.dir)

    assert kept.read_bytes() == _EARLIER
    assert str(paper.figures / RECORD_NAME) in capsys.readouterr().err
    assert _recorded(paper.figures) == []


def test_a_record_that_is_a_directory_removes_nothing_and_stops_the_copy(paper, capsys):
    kept = _seed_unrecorded(paper.figures, "a.png")
    (paper.figures / RECORD_NAME).mkdir()
    (paper.source / "fig.png").write_bytes(b"new revision")

    with pytest.raises(OSError):
        convert_latex.copy_figures(paper.source, paper.dir)

    assert kept.read_bytes() == _EARLIER
    assert str(paper.figures / RECORD_NAME) in capsys.readouterr().err
    assert _figures(paper.figures) == ["a.png"]


def test_a_record_cannot_name_a_file_outside_the_directory(paper):
    # An entry with a directory part is not honoured, so an edited record
    # cannot send the removal anywhere but into figures/ itself.
    outside = paper.dir / "outside.png"
    outside.write_bytes(_EARLIER)
    nested = _seed_unrecorded(paper.figures / "sub", "inner.png")
    (paper.figures / RECORD_NAME).write_text(
        json.dumps({"copied": ["../outside.png", str(outside), "sub/inner.png"]}),
        encoding="utf-8",
    )

    convert_latex.copy_figures(paper.source, paper.dir)

    assert outside.read_bytes() == _EARLIER
    assert nested.read_bytes() == _EARLIER


def test_read_record_drops_entries_that_are_not_plain_file_names(paper):
    paper.figures.mkdir()
    (paper.figures / RECORD_NAME).write_text(
        json.dumps({"copied": ["", "..", ".", "a/b.png", RECORD_NAME, "ok.png"]}),
        encoding="utf-8",
    )

    assert read_record(paper.figures) == ["ok.png"]


def test_a_recorded_name_that_is_now_a_directory_is_left(paper):
    _seed_copied(paper.figures, "gone.png")
    (paper.figures / "gone.png").unlink()
    inner = _seed_unrecorded(paper.figures / "gone.png", "inner.png")

    convert_latex.copy_figures(paper.source, paper.dir)

    assert inner.read_bytes() == _EARLIER


def test_a_copy_works_through_a_linked_figures_directory(paper, tmp_path):
    # Files are removed one by one, so a figures/ that is a link to a
    # directory behaves like the directory: what is not recorded stays.
    target = tmp_path / "elsewhere"
    _seed_copied(target, "stale.png")
    theirs = _seed_unrecorded(target, "theirs.png")
    paper.figures.symlink_to(target, target_is_directory=True)
    (paper.source / "fig.png").write_bytes(b"new revision")

    convert_latex.copy_figures(paper.source, paper.dir)

    assert paper.figures.is_symlink()
    assert _figures(target) == ["fig.png", "theirs.png"]
    assert theirs.read_bytes() == _EARLIER


# --- convert_latex.main ---------------------------------------------------


@pytest.fixture
def run_latex_main(monkeypatch, paper):
    """Run ``convert_latex.main()`` on ``paper`` with pandoc and post-processing replaced.

    ``pandoc_succeeds`` is what the stand-in converter returns; it writes the
    Markdown file only when it succeeds. ``state.converted`` records whether
    the converter was reached.
    """
    state = SimpleNamespace(converted=False)
    real_run = subprocess.run

    def answer_which_pandoc(cmd, **kwargs):
        # main() asks `which pandoc` before converting; answered here so the
        # run reaches the stand-in on a machine without pandoc too. Any other
        # command still runs.
        if cmd == ["which", "pandoc"]:
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, **kwargs)

    def run(*, pandoc_succeeds: bool = True) -> None:
        def fake_pandoc(tex_file: Path, output_md: Path) -> bool:
            state.converted = True
            if pandoc_succeeds:
                output_md.write_text("body\n", encoding="utf-8")
            return pandoc_succeeds

        monkeypatch.setattr(convert_latex.subprocess, "run", answer_which_pandoc)
        monkeypatch.setattr(convert_latex, "convert_with_pandoc", fake_pandoc)
        monkeypatch.setattr(
            convert_latex, "post_process_markdown", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "convert_latex.py",
                _ARXIV_ID,
                "--source-dir",
                str(paper.source),
                "--output",
                str(paper.output),
            ],
        )
        convert_latex.main()

    state.run = run
    return state


def test_latex_main_removes_the_recorded_figures_it_does_not_copy_again(
    paper, run_latex_main
):
    _seed_copied(paper.figures, "stale.png")
    (paper.source / "fig.png").write_bytes(b"new revision")

    run_latex_main.run()

    assert _figures(paper.figures) == ["fig.png"]


def test_latex_main_removes_nothing_when_pandoc_fails(paper, run_latex_main):
    # A failed conversion writes no document, so a document an earlier run
    # wrote would still be the one on disk, linking into figures/.
    _seed_copied(paper.figures, "stale.png")
    (paper.source / "fig.png").write_bytes(b"new revision")

    with pytest.raises(SystemExit) as exit_info:
        run_latex_main.run(pandoc_succeeds=False)

    assert exit_info.value.code == 1
    assert run_latex_main.converted
    assert _figures(paper.figures) == ["stale.png"]
    assert _recorded(paper.figures) == ["stale.png"]


# --- convert_paper.main ---------------------------------------------------


@pytest.fixture
def launched_paper(launch) -> SimpleNamespace:
    """The directory of the paper the ``launch`` fixture converts."""
    paper_dir = launch.output_dir / LAUNCH_ARXIV_ID
    paper_dir.mkdir()
    return SimpleNamespace(dir=paper_dir, figures=paper_dir / "figures")


def test_pdf_fallback_removes_the_copied_figures_and_the_record(
    launch, launched_paper, capsys
):
    seed_pdf(launched_paper.dir)
    _seed_copied(launched_paper.figures, "a.png", "b.pdf")
    mine = _seed_unrecorded(launched_paper.figures, "mine.png")

    launch.run()

    assert [child.script for child in launch.children] == [
        "fetch_paper.py",
        "convert_pdf_simple.py",
    ]
    # The record goes with the copied files; the file placed by hand stays.
    assert _entries(launched_paper.figures) == ["mine.png"]
    assert mine.read_bytes() == _EARLIER
    captured = capsys.readouterr()
    assert f"Removed 2 figure(s) from {launched_paper.figures}" in captured.out
    assert captured.err == ""


def test_pdf_fallback_does_not_count_the_record_as_a_figure(
    launch, launched_paper, capsys
):
    # A record naming itself would otherwise be unlinked as a figure and
    # reported as one.
    seed_pdf(launched_paper.dir)
    _seed_copied(launched_paper.figures, "a.png")
    record_figures(launched_paper.figures, ["a.png", RECORD_NAME])

    launch.run()

    assert f"Removed 1 figure(s) from {launched_paper.figures}" in (
        capsys.readouterr().out
    )


def test_pdf_fallback_removes_a_figures_directory_it_emptied(launch, launched_paper):
    seed_pdf(launched_paper.dir)
    _seed_copied(launched_paper.figures, "a.png")
    document = launched_paper.dir / f"{LAUNCH_ARXIV_ID}.md"
    document.write_text("earlier document\n", encoding="utf-8")

    launch.run()

    # Only figures/ went: the rest of the paper's directory is untouched.
    assert _entries(launched_paper.dir) == [f"{LAUNCH_ARXIV_ID}.md", "pdf"]


def test_pdf_fallback_keeps_a_linked_figures_directory_it_emptied(
    launch, launched_paper, capsys, tmp_path
):
    seed_pdf(launched_paper.dir)
    target = tmp_path / "elsewhere"
    _seed_copied(target, "copied.png")
    launched_paper.figures.symlink_to(target, target_is_directory=True)

    launch.run()

    assert launched_paper.figures.is_symlink()
    assert _entries(target) == []
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "seed",
    [
        lambda figures: None,
        lambda figures: _seed_unrecorded(figures, "old.png"),
        lambda figures: figures.mkdir(),
        lambda figures: figures.write_text("not a directory", encoding="utf-8"),
    ],
    ids=["no-figures", "no-record", "empty-figures", "figures-is-a-file"],
)
def test_pdf_fallback_leaves_figures_alone_without_a_record(
    launch, launched_paper, capsys, tmp_path, seed
):
    # Without a record the PDF fallback has nothing to remove, whatever is at
    # figures/, and none of these shapes stops it.
    seed_pdf(launched_paper.dir)
    seed(launched_paper.figures)
    before = sorted(str(p) for p in tmp_path.rglob("*"))

    launch.run()

    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    captured = capsys.readouterr()
    assert "Removed" not in captured.out
    assert captured.err == ""


def test_pdf_fallback_warns_about_a_record_that_is_a_directory(
    launch, launched_paper, capsys, tmp_path
):
    seed_pdf(launched_paper.dir)
    kept = _seed_unrecorded(launched_paper.figures, "a.png")
    (launched_paper.figures / RECORD_NAME).mkdir()

    launch.run()

    assert kept.read_bytes() == _EARLIER
    assert (launched_paper.figures / RECORD_NAME).is_dir()
    captured = capsys.readouterr()
    assert str(launched_paper.figures / RECORD_NAME) in captured.err
    assert "Removed" not in captured.out


def test_pdf_fallback_with_an_unusable_record_removes_only_the_record(
    launch, launched_paper, capsys
):
    # Nothing says which files were copied, so they stay and the run warns.
    seed_pdf(launched_paper.dir)
    kept = _seed_unrecorded(launched_paper.figures, "a.png")
    (launched_paper.figures / RECORD_NAME).write_text("not json", encoding="utf-8")

    launch.run()

    assert _entries(launched_paper.figures) == ["a.png"]
    assert kept.read_bytes() == _EARLIER
    captured = capsys.readouterr()
    assert str(launched_paper.figures / RECORD_NAME) in captured.err
    assert "Removed" not in captured.out


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs a user that a read-only directory stops",
)
def test_pdf_fallback_warns_when_the_figures_cannot_be_removed(
    launch, launched_paper, capsys
):
    # The document is already complete, so the run ends normally and says
    # what it could not remove.
    seed_pdf(launched_paper.dir)
    _seed_copied(launched_paper.figures, "copied.png")
    launched_paper.figures.chmod(0o555)
    try:
        launch.run()
    finally:
        launched_paper.figures.chmod(0o755)

    assert _figures(launched_paper.figures) == ["copied.png"]
    captured = capsys.readouterr()
    assert str(launched_paper.figures) in captured.err
    assert "Removed" not in captured.out


def test_pdf_fallback_removes_nothing_when_the_conversion_fails(launch, launched_paper):
    # A failed conversion writes no document, so a document an earlier LaTeX
    # run wrote would still be the one on disk, linking into figures/.
    seed_pdf(launched_paper.dir)
    _seed_copied(launched_paper.figures, "copied.png")

    with pytest.raises(SystemExit) as exit_info:
        launch.run(exit_codes={"convert_pdf_simple.py": 1})

    assert exit_info.value.code == 1
    assert _figures(launched_paper.figures) == ["copied.png"]
    assert _recorded(launched_paper.figures) == ["copied.png"]


def test_latex_path_leaves_figures_to_the_latex_step(launch, launched_paper):
    # convert_paper removes figures on the PDF branch only. On this branch the
    # LaTeX step has just copied them and written the record; discarding the
    # recorded files here would delete them while the run reported success.
    seed_cached_source(launched_paper.dir)
    _seed_copied(launched_paper.figures, "copied.png")

    launch.run()

    assert [child.script for child in launch.children] == [
        "fetch_paper.py",
        "convert_latex.py",
    ]
    assert _figures(launched_paper.figures) == ["copied.png"]
    assert _recorded(launched_paper.figures) == ["copied.png"]
