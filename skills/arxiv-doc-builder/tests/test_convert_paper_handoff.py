"""convert_paper's single metadata lookup, and how it reaches each step.

The steps run as child processes, so the lookup is handed over in a file. These
drive ``main()`` with the lookup and the child launcher replaced, and record
what each child would have received.
"""

from pathlib import Path

import pytest

from conftest import LAUNCH_ARXIV_ID, LAUNCH_LOOKUP


def _seed_latex(output_dir: Path) -> None:
    source = output_dir / LAUNCH_ARXIV_ID / "source"
    source.mkdir(parents=True)
    (source / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")


def _seed_pdf(output_dir: Path) -> None:
    pdf_dir = output_dir / LAUNCH_ARXIV_ID / "pdf"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / f"{LAUNCH_ARXIV_ID}.pdf").write_bytes(b"%PDF-stub")


@pytest.mark.parametrize(
    ("seed", "converter"),
    [(_seed_latex, "convert_latex.py"), (_seed_pdf, "convert_pdf_simple.py")],
    ids=["latex", "pdf"],
)
def test_one_lookup_reaches_every_step_through_one_file(launch, seed, converter):
    seed(launch.output_dir)

    launch.run()

    assert launch.lookups == [LAUNCH_ARXIV_ID]
    assert [child.script for child in launch.children] == ["fetch_paper.py", converter]
    assert len({child.handoff for child in launch.children}) == 1
    assert all(child.read == LAUNCH_LOOKUP for child in launch.children)
    assert not launch.children[0].handoff.exists()


@pytest.mark.parametrize(
    ("exit_codes", "expected_exit"),
    [({"fetch_paper.py": 1}, 1), ({"convert_latex.py": 2}, 2)],
    ids=["fetch-fails", "ambiguous-tex"],
)
def test_the_handoff_is_removed_when_a_step_ends_the_run(
    launch, exit_codes, expected_exit
):
    _seed_latex(launch.output_dir)

    with pytest.raises(SystemExit) as exit_info:
        launch.run(exit_codes=exit_codes)

    assert exit_info.value.code == expected_exit
    assert launch.children
    assert not launch.children[0].handoff.exists()


def test_an_invalid_id_is_rejected_before_any_lookup(launch):
    with pytest.raises(SystemExit) as exit_info:
        launch.run("2506.1376")

    assert exit_info.value.code == 1
    assert launch.lookups == []
    assert launch.children == []
