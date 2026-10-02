"""What ``convert-paper`` leaves in the paper's ``figures/`` directory.

The File Organization section of ``references/output-format.md`` states the
behavior for ``convert-paper``, and the ``--replace-figures`` help in
``convert_latex.py`` states it for that script. Each test name says which
part it holds.

The ``convert_latex.main`` tests replace pandoc and the post-processing, and
the ``convert_paper.main`` tests replace the step launcher, so nothing here
needs pandoc or reaches the network.
"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import LAUNCH_ARXIV_ID, seed_cached_source, seed_pdf

from arxiv_doc_builder import convert_latex
from arxiv_doc_builder.figures_dir import remove_figures_dir

_STALE = b"earlier revision"
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


def _seed_stale(figures: Path, name: str = "stale.png") -> Path:
    figures.mkdir(parents=True, exist_ok=True)
    stale = figures / name
    stale.write_bytes(_STALE)
    return stale


def _link_figures(figures: Path, target: Path, kind: str) -> None:
    """Make ``figures`` a link to ``target``, which holds a file when ``live``."""
    if kind == "live":
        _seed_stale(target, "theirs.png")
    figures.symlink_to(target, target_is_directory=True)


def _names(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


def _files(root: Path) -> dict[Path, bytes]:
    """Every regular file under ``root`` with its content, links not followed."""
    return {
        path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


# --- remove_figures_dir ---------------------------------------------------


@pytest.mark.parametrize("link", ["live", "dangling"])
def test_remove_figures_dir_raises_on_a_symbolic_link(tmp_path, link):
    # The callers refuse a link before they get here. Reached anyway, the
    # removal raises instead of following the link or reporting nothing to do.
    figures = tmp_path / "figures"
    _link_figures(figures, tmp_path / "elsewhere", link)
    before = _files(tmp_path)

    with pytest.raises(OSError):
        remove_figures_dir(figures)

    assert figures.is_symlink()
    assert _files(tmp_path) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list any directory")
def test_remove_figures_dir_raises_when_the_removal_fails(tmp_path):
    # A removal that fails must not pass for a removal: the run would go on to
    # report success with the earlier files still in place.
    figures = tmp_path / "figures"
    locked = figures / "locked"
    _seed_stale(locked)
    locked.chmod(0)
    try:
        with pytest.raises(OSError):
            remove_figures_dir(figures)
    finally:
        locked.chmod(0o755)

    assert (locked / "stale.png").read_bytes() == _STALE


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

    def run(*options: str, pandoc_succeeds: bool = True) -> None:
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
                *options,
            ],
        )
        convert_latex.main()

    state.run = run
    return state


def test_replace_figures_leaves_only_what_the_run_copies(paper, run_latex_main):
    # The earlier revision had three figures at the top level. The new one
    # dropped the first, moved the second into a subdirectory, and changed the
    # third. A link to the moved figure is rewritten to figures/moved.png, and
    # must not find the earlier revision's file there.
    _seed_stale(paper.figures, "dropped.png")
    _seed_stale(paper.figures, "moved.png")
    _seed_stale(paper.figures, "kept.png")
    (paper.source / "kept.png").write_bytes(b"new revision")
    (paper.source / "added.pdf").write_bytes(b"new figure")
    (paper.source / "sub").mkdir()
    (paper.source / "sub" / "moved.png").write_bytes(b"new revision")

    run_latex_main.run("--replace-figures")

    assert _names(paper.figures) == ["added.pdf", "kept.png"]
    assert (paper.figures / "kept.png").read_bytes() == b"new revision"


def test_replace_figures_removes_what_was_placed_by_hand(paper, run_latex_main):
    _seed_stale(paper.figures, "notes.txt")
    _seed_stale(paper.figures / "extra", "diagram.png")

    run_latex_main.run("--replace-figures")

    assert _names(paper.figures) == []


def test_replace_figures_creates_the_directory_for_a_source_without_images(
    paper, run_latex_main
):
    assert not paper.figures.exists()

    run_latex_main.run("--replace-figures")

    assert paper.figures.is_dir()
    assert _names(paper.figures) == []


def test_without_replace_figures_nothing_is_removed(paper, run_latex_main):
    # convert_latex.py run by hand may write beside files it does not own, so
    # it removes nothing unless asked to.
    _seed_stale(paper.figures)
    (paper.source / "fig.png").write_bytes(b"new revision")

    run_latex_main.run()

    assert _names(paper.figures) == ["fig.png", "stale.png"]
    assert (paper.figures / "stale.png").read_bytes() == _STALE


def test_replace_figures_keeps_figures_when_pandoc_fails(paper, run_latex_main):
    # A failed conversion writes no document, so a document an earlier run
    # wrote would still be the one on disk, linking into figures/.
    stale = _seed_stale(paper.figures)
    (paper.source / "fig.png").write_bytes(b"new revision")

    with pytest.raises(SystemExit) as exit_info:
        run_latex_main.run("--replace-figures", pandoc_succeeds=False)

    assert exit_info.value.code == 1
    assert run_latex_main.converted
    assert _names(paper.figures) == ["stale.png"]
    assert stale.read_bytes() == _STALE


@pytest.mark.parametrize("link", ["live", "dangling"])
def test_replace_figures_refuses_a_symbolic_link(
    paper, run_latex_main, capsys, tmp_path, link
):
    # Refused before pandoc runs: converting first would leave a new document
    # beside figures that were never replaced. A removal that followed a live
    # link would delete the files behind it, so the state is asserted too.
    _link_figures(paper.figures, tmp_path / "elsewhere", link)
    before = _files(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        run_latex_main.run("--replace-figures")

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert str(paper.figures) in err
    assert "symbolic link" in err
    assert not run_latex_main.converted
    assert paper.figures.is_symlink()
    assert _files(tmp_path) == before


# --- convert_paper.main ---------------------------------------------------


@pytest.fixture
def launched_paper(launch) -> SimpleNamespace:
    """The directory of the paper the ``launch`` fixture converts."""
    paper_dir = launch.output_dir / LAUNCH_ARXIV_ID
    paper_dir.mkdir()
    return SimpleNamespace(dir=paper_dir, figures=paper_dir / "figures")


def test_latex_path_asks_the_latex_step_to_replace_figures(launch, launched_paper):
    # convert_paper itself removes nothing on this branch: the LaTeX step
    # fills figures/ last, and removing it afterwards would delete those
    # figures while the run still reported success.
    seed_cached_source(launched_paper.dir)
    stale = _seed_stale(launched_paper.figures)

    launch.run()

    assert [child.script for child in launch.children] == [
        "fetch_paper.py",
        "convert_latex.py",
    ]
    assert "--replace-figures" in launch.children[1].args
    assert stale.read_bytes() == _STALE


def test_pdf_fallback_removes_figures(launch, launched_paper, capsys):
    seed_pdf(launched_paper.dir)
    _seed_stale(launched_paper.figures)
    document = launched_paper.dir / f"{LAUNCH_ARXIV_ID}.md"
    document.write_text("earlier document\n", encoding="utf-8")

    launch.run()

    assert [child.script for child in launch.children] == [
        "fetch_paper.py",
        "convert_pdf_simple.py",
    ]
    assert not launched_paper.figures.exists()
    assert f"Removed {launched_paper.figures}" in capsys.readouterr().out
    # Only figures/ went: the rest of the paper's directory is untouched.
    assert _names(launched_paper.dir) == [f"{LAUNCH_ARXIV_ID}.md", "pdf"]


def test_pdf_fallback_reports_no_removal_without_figures(
    launch, launched_paper, capsys
):
    seed_pdf(launched_paper.dir)

    launch.run()

    assert "Removed" not in capsys.readouterr().out
    assert not launched_paper.figures.exists()


def test_pdf_fallback_keeps_figures_when_the_conversion_fails(launch, launched_paper):
    # A failed conversion writes no document, so a document an earlier LaTeX
    # run wrote would still be the one on disk, linking into figures/.
    seed_pdf(launched_paper.dir)
    stale = _seed_stale(launched_paper.figures)

    with pytest.raises(SystemExit) as exit_info:
        launch.run(exit_codes={"convert_pdf_simple.py": 1})

    assert exit_info.value.code == 1
    assert stale.read_bytes() == _STALE


@pytest.mark.parametrize("link", ["live", "dangling"])
def test_pdf_fallback_refuses_a_symbolic_link(
    launch, launched_paper, capsys, tmp_path, link
):
    # A dangling link does not "exist", so a check built on exists() alone
    # would let the run finish with the link left behind. A live one must not
    # have the files behind it deleted. Either way the converter never starts.
    seed_pdf(launched_paper.dir)
    _link_figures(launched_paper.figures, tmp_path / "elsewhere", link)
    before = _files(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        launch.run()

    assert exit_info.value.code == 1
    assert [child.script for child in launch.children] == ["fetch_paper.py"]
    err = capsys.readouterr().err
    assert str(launched_paper.figures) in err
    assert "symbolic link" in err
    assert launched_paper.figures.is_symlink()
    assert _files(tmp_path) == before
