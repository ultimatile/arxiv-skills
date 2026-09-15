"""convert_paper's single metadata lookup, and how it reaches each step.

The steps run as child processes, so the lookup is handed over in a file. These
drive ``main()`` with the lookup and the child launcher replaced, and record
what each child would have received.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arxiv_doc_builder import convert_paper
from arxiv_doc_builder.arxiv_metadata import (
    METADATA_OK,
    ArxivMetadata,
    MetadataFetch,
    read_metadata_handoff,
)

ARXIV_ID = "2409.03108"
LOOKUP = MetadataFetch(
    METADATA_OK, metadata=ArxivMetadata(title="Handed Over", version="2409.03108v2")
)


@pytest.fixture
def launch(monkeypatch, tmp_path):
    """Run ``main()`` recording the lookups made and the children started.

    Each recorded child carries its script name, its handoff path, and what the
    handoff held when the child started (``None`` when no file was there).
    ``exit_codes`` maps a script name to the code its child returns.
    """
    state = SimpleNamespace(lookups=[], children=[], output_dir=tmp_path)

    def fake_fetch(arxiv_id):
        state.lookups.append(arxiv_id)
        return LOOKUP

    def run(arxiv_id=ARXIV_ID, *, exit_codes=None):
        codes = exit_codes or {}

        def fake_run_script(script_name, args, use_uv=False):
            handoff = Path(args[args.index("--metadata-handoff") + 1])
            state.children.append(
                SimpleNamespace(
                    script=script_name,
                    handoff=handoff,
                    read=read_metadata_handoff(handoff, ARXIV_ID)
                    if handoff.is_file()
                    else None,
                )
            )
            return codes.get(script_name, 0)

        monkeypatch.setattr(convert_paper, "fetch_metadata", fake_fetch)
        monkeypatch.setattr(convert_paper, "run_script", fake_run_script)
        monkeypatch.setattr(
            sys, "argv", ["convert_paper.py", arxiv_id, "--output-dir", str(tmp_path)]
        )
        convert_paper.main()

    state.run = run
    return state


def _seed_latex(output_dir: Path) -> None:
    source = output_dir / ARXIV_ID / "source"
    source.mkdir(parents=True)
    (source / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")


def _seed_pdf(output_dir: Path) -> None:
    pdf_dir = output_dir / ARXIV_ID / "pdf"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / f"{ARXIV_ID}.pdf").write_bytes(b"%PDF-stub")


@pytest.mark.parametrize(
    ("seed", "converter"),
    [(_seed_latex, "convert_latex.py"), (_seed_pdf, "convert_pdf_simple.py")],
    ids=["latex", "pdf"],
)
def test_one_lookup_reaches_every_step_through_one_file(launch, seed, converter):
    seed(launch.output_dir)

    launch.run()

    assert launch.lookups == [ARXIV_ID]
    assert [child.script for child in launch.children] == ["fetch_paper.py", converter]
    assert len({child.handoff for child in launch.children}) == 1
    assert all(child.read == LOOKUP for child in launch.children)
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
