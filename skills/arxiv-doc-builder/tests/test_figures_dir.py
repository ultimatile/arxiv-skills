"""What a conversion leaves in the paper's ``figures/`` directory.

Contract: after a LaTeX conversion ``figures/`` holds exactly the image files
at the top level of the source that was converted, so a file an earlier
revision left there, or one placed there by hand, is gone. After a PDF
fallback there is no ``figures/``, since the document it writes links to no
figure. A run that fails before it writes the Markdown file leaves
``figures/`` as it found it.

Contract: the removal never deletes what it was not meant to. It follows no
symbolic link, and a ``figures/`` that overlaps the files being converted is
refused before anything is removed or converted.

The ``convert_latex.main`` tests replace pandoc and the post-processing, and
the ``convert_paper.main`` tests replace the step launcher, so nothing here
needs pandoc or reaches the network.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import LAUNCH_ARXIV_ID, seed_cached_source, seed_pdf

from arxiv_doc_builder import convert_latex

_STALE = b"earlier revision"
_ARXIV_ID = "2606.09995"


@pytest.fixture
def paper(tmp_path: Path) -> SimpleNamespace:
    """A paper's directory with a ``source/`` holding one main ``.tex``."""
    paper_dir = tmp_path / "paper"
    source = paper_dir / "source"
    source.mkdir(parents=True)
    (source / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    return SimpleNamespace(
        dir=paper_dir,
        source=source,
        figures=paper_dir / "figures",
        output=paper_dir / "paper.md",
    )


def _seed_stale(figures: Path, name: str = "stale.png") -> Path:
    figures.mkdir(parents=True, exist_ok=True)
    stale = figures / name
    stale.write_bytes(_STALE)
    return stale


def _names(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


def _files(root: Path) -> dict[Path, bytes]:
    """Every regular file under ``root`` with its content, links not followed."""
    return {
        path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


# --- copy_figures ---------------------------------------------------------


def test_copy_figures_keeps_only_the_sources_top_level_images(paper):
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

    convert_latex.copy_figures(paper.source, paper.dir)

    assert _names(paper.figures) == ["added.pdf", "kept.png"]
    assert (paper.figures / "kept.png").read_bytes() == b"new revision"


def test_copy_figures_removes_what_was_placed_by_hand(paper):
    _seed_stale(paper.figures, "notes.txt")
    _seed_stale(paper.figures / "extra", "diagram.png")

    convert_latex.copy_figures(paper.source, paper.dir)

    assert _names(paper.figures) == []


def test_copy_figures_creates_the_directory_for_a_source_without_images(paper):
    assert not paper.figures.exists()

    convert_latex.copy_figures(paper.source, paper.dir)

    assert paper.figures.is_dir()
    assert _names(paper.figures) == []


@pytest.fixture(params=["live", "dangling"])
def linked_figures(request, paper, tmp_path) -> SimpleNamespace:
    """``figures`` as a symbolic link, to a directory with a file or to nothing."""
    target = tmp_path / "elsewhere"
    if request.param == "live":
        _seed_stale(target, "theirs.png")
    paper.figures.symlink_to(target, target_is_directory=True)
    return SimpleNamespace(target=target, before=_files(tmp_path))


def test_copy_figures_refuses_a_symbolic_link(paper, linked_figures, tmp_path):
    # Emptying the directory entry by entry would delete the files behind a
    # live link without any error, so the state is asserted, not only the raise.
    with pytest.raises(OSError):
        convert_latex.copy_figures(paper.source, paper.dir)

    assert paper.figures.is_symlink()
    assert _files(tmp_path) == linked_figures.before


def _figures_inside_source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    return source, source


def _source_is_figures(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "figures", tmp_path


def _source_inside_figures(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "figures" / "src", tmp_path


def _overlap_only_once_resolved(tmp_path: Path) -> tuple[Path, Path]:
    # The output directory is a link to the source, so the two paths share no
    # prefix as written.
    source = tmp_path / "source"
    source.mkdir()
    (tmp_path / "out").symlink_to(source, target_is_directory=True)
    return source, tmp_path / "out"


@pytest.mark.parametrize(
    "layout",
    [
        _figures_inside_source,
        _source_is_figures,
        _source_inside_figures,
        _overlap_only_once_resolved,
    ],
)
def test_copy_figures_refuses_a_figures_dir_overlapping_the_source(tmp_path, layout):
    source, output_dir = layout(tmp_path)
    source.mkdir(parents=True, exist_ok=True)
    (source / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (source / "fig.png").write_bytes(b"source figure")
    _seed_stale(output_dir / "figures")
    before = _files(tmp_path)

    with pytest.raises(ValueError):
        convert_latex.copy_figures(source, output_dir)

    assert _files(tmp_path) == before


def test_copy_figures_accepts_a_sibling_sharing_a_name_prefix(tmp_path):
    # figures-src is not inside figures: containment is by path component.
    source = tmp_path / "figures-src"
    source.mkdir()
    (source / "fig.png").write_bytes(b"source figure")
    _seed_stale(tmp_path / "figures")

    convert_latex.copy_figures(source, tmp_path)

    assert _names(tmp_path / "figures") == ["fig.png"]
    assert (source / "fig.png").read_bytes() == b"source figure"


# --- convert_latex.main ---------------------------------------------------


@pytest.fixture
def run_latex_main(monkeypatch):
    """Run ``convert_latex.main()`` with pandoc and post-processing replaced.

    ``pandoc_succeeds`` is what the stand-in converter returns; it writes the
    Markdown file only when it succeeds. ``state.converted`` records whether
    the converter was reached.
    """
    state = SimpleNamespace(converted=False)

    def run(*args: str, pandoc_succeeds: bool = True) -> None:
        def fake_pandoc(tex_file: Path, output_md: Path) -> bool:
            state.converted = True
            if pandoc_succeeds:
                output_md.write_text("body\n", encoding="utf-8")
            return pandoc_succeeds

        # main() asks `which pandoc` before converting; answered here so the
        # run reaches the stand-in on a machine without pandoc too.
        monkeypatch.setattr(
            convert_latex.subprocess,
            "run",
            lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0),
        )
        monkeypatch.setattr(convert_latex, "convert_with_pandoc", fake_pandoc)
        monkeypatch.setattr(
            convert_latex, "post_process_markdown", lambda *a, **kw: None
        )
        monkeypatch.setattr(sys, "argv", ["convert_latex.py", _ARXIV_ID, *args])
        convert_latex.main()

    state.run = run
    return state


def test_latex_main_replaces_an_earlier_figures_dir(paper, run_latex_main):
    _seed_stale(paper.figures)
    (paper.source / "fig.png").write_bytes(b"new revision")

    run_latex_main.run("--source-dir", str(paper.source), "--output", str(paper.output))

    assert _names(paper.figures) == ["fig.png"]
    assert (paper.figures / "fig.png").read_bytes() == b"new revision"


def test_latex_main_leaves_figures_when_pandoc_fails(paper, run_latex_main):
    # The earlier document is still on disk and still links into figures/.
    stale = _seed_stale(paper.figures)
    (paper.source / "fig.png").write_bytes(b"new revision")

    with pytest.raises(SystemExit) as exit_info:
        run_latex_main.run(
            "--source-dir",
            str(paper.source),
            "--output",
            str(paper.output),
            pandoc_succeeds=False,
        )

    assert exit_info.value.code == 1
    assert run_latex_main.converted
    assert _names(paper.figures) == ["stale.png"]
    assert stale.read_bytes() == _STALE


def test_latex_main_refuses_an_output_inside_the_source(
    paper, run_latex_main, capsys, tmp_path
):
    # figures/ would then be the source's own figures/ subdirectory.
    _seed_stale(paper.source / "figures", "own.png")
    before = _files(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        run_latex_main.run(
            "--source-dir",
            str(paper.source),
            "--output",
            str(paper.source / "out.md"),
        )

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert str(paper.source / "figures") in err
    assert f"overlaps {paper.source}," in err
    assert not run_latex_main.converted
    assert _files(tmp_path) == before


def test_latex_main_refuses_a_tex_file_inside_figures(
    paper, run_latex_main, capsys, tmp_path
):
    # An explicit main file need not sit in the source directory, so the
    # source check alone would let this run delete the file it converted.
    _seed_stale(paper.figures)
    tex_file = paper.figures / "main.tex"
    tex_file.write_text("\\documentclass{article}\n", encoding="utf-8")
    before = _files(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        run_latex_main.run(
            "--source-dir",
            str(paper.source),
            "--output",
            str(paper.output),
            "--tex-file",
            str(tex_file),
        )

    assert exit_info.value.code == 1
    assert f"overlaps {paper.figures}," in capsys.readouterr().err
    assert not run_latex_main.converted
    assert _files(tmp_path) == before


# --- convert_paper.main ---------------------------------------------------


@pytest.fixture
def launched_paper(launch) -> SimpleNamespace:
    """The directory of the paper the ``launch`` fixture converts."""
    paper_dir = launch.output_dir / LAUNCH_ARXIV_ID
    paper_dir.mkdir()
    return SimpleNamespace(dir=paper_dir, figures=paper_dir / "figures")


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


def test_pdf_fallback_keeps_figures_when_the_conversion_fails(launch, launched_paper):
    # The earlier document is still on disk and still links into figures/.
    seed_pdf(launched_paper.dir)
    stale = _seed_stale(launched_paper.figures)

    with pytest.raises(SystemExit) as exit_info:
        launch.run(exit_codes={"convert_pdf_simple.py": 1})

    assert exit_info.value.code == 1
    assert stale.read_bytes() == _STALE


@pytest.mark.parametrize("link", ["live", "dangling"])
def test_pdf_fallback_refuses_a_symbolic_link(launch, launched_paper, tmp_path, link):
    # A dangling link does not "exist", so a removal guarded by exists() alone
    # would skip it and report success with the link left behind. A live one
    # must not have the files behind it deleted.
    seed_pdf(launched_paper.dir)
    target = tmp_path / "elsewhere"
    if link == "live":
        _seed_stale(target, "theirs.png")
    launched_paper.figures.symlink_to(target, target_is_directory=True)
    before = _files(tmp_path)

    with pytest.raises(OSError):
        launch.run()

    assert launched_paper.figures.is_symlink()
    assert _files(tmp_path) == before


def test_latex_path_leaves_figures_to_the_latex_step(launch, launched_paper):
    # convert_paper removes figures/ on the PDF branch only. On this branch the
    # LaTeX step has just filled the directory; removing it here would delete
    # those figures while the run still reported success.
    seed_cached_source(launched_paper.dir)
    stale = _seed_stale(launched_paper.figures)

    launch.run()

    assert [child.script for child in launch.children] == [
        "fetch_paper.py",
        "convert_latex.py",
    ]
    assert stale.read_bytes() == _STALE
