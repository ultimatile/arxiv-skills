"""Cross-script CLI-level contracts.

Promoted from review findings that revealed untested specifications:

  - Exit-code disjointness: exit code 2 is reserved for the
    "ambiguous main .tex" signal propagated through convert_latex →
    convert_paper so wrappers may retry with --tex-file. Any other
    failure — including validator rejection — must use a different code
    (currently 1) so a plain ID typo is never interpreted as a
    source-selection problem.

  - Default-path safe-normalization: when a CLI builds a default
    "<id>/..." path for a legacy ID like hep-th/9901001, the
    slash must be normalized away by safe_arxiv_id before becoming a
    Path component, otherwise the resulting tree (hep-th/9901001/...)
    does not match the fetch-side cache (hep-th_9901001/).
"""

import subprocess
import sys
from pathlib import Path

import pytest

from arxiv_doc_builder import convert_latex
from conftest import PACKAGE_DIR


def _run(args: list, cwd: Path) -> subprocess.CompletedProcess:
    """Run the current interpreter with ``args`` in ``cwd``, capturing its text."""
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, cwd=str(cwd)
    )


@pytest.mark.parametrize(
    "script",
    ["fetch_paper.py", "convert_paper.py", "convert_latex.py"],
)
def test_validator_failure_exits_1_leaving_2_reserved(script, tmp_path):
    # "2506.1376" is a structurally-valid-but-non-canonical new-style ID
    # (4-digit sequence on a post-2015 paper). Every CLI entry point
    # routes this through validate_arxiv_id at argparse time and must
    # exit 1, never 2 — exit 2 belongs to the ambiguous-main-tex channel.
    result = _run([str(PACKAGE_DIR / script), "2506.1376"], tmp_path)
    assert result.returncode == 1, (
        f"{script}: validator failure exited {result.returncode}, "
        f"expected 1 (exit 2 is reserved for ambiguous main .tex).\n"
        f"stderr: {result.stderr}"
    )
    assert "Error:" in result.stderr


def test_convert_latex_default_path_normalizes_slash_for_legacy_id(tmp_path):
    # Legacy IDs contain a slash. Running convert_latex with no
    # --source-dir must build the default path via safe_arxiv_id so
    # the directory name has an underscore, not a slash. We verify by
    # observing the "source directory not found" diagnostic, which
    # echoes the constructed path.
    result = _run([str(PACKAGE_DIR / "convert_latex.py"), "hep-th/9901001"], tmp_path)
    # Expected failure: the working directory holds no source tree.
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    # The whole default, so a directory put in front of it shows up too.
    assert f"not found: {Path('hep-th_9901001') / 'source'}\n" in combined, combined
    assert "hep-th_9901001" in combined, (
        "Expected the safe-normalized legacy-ID directory in the path "
        "message, so that convert_latex matches the fetch-side cache.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # The unnormalized form would only appear if a slash leaked into a
    # Path component. Assert its absence to pin down the contract.
    assert "hep-th/9901001" not in combined, (
        "Unnormalized legacy ID leaked into a path component; "
        "safe_arxiv_id must run before Path construction.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_convert_latex_defaults_are_the_paper_directory_under_cwd(
    monkeypatch, tmp_path
):
    # Observed without pandoc: main() checks for it, converts, post-processes
    # and copies figures, and each of those is replaced. The last two record
    # the paths main() builds when neither --source-dir nor --output is given.
    monkeypatch.chdir(tmp_path)
    source = Path("hep-th_9901001") / "source"
    source.mkdir(parents=True)
    (source / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    received = {}
    monkeypatch.setattr(
        convert_latex.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    monkeypatch.setattr(convert_latex, "convert_with_pandoc", lambda tex, out: True)
    monkeypatch.setattr(
        convert_latex,
        "post_process_markdown",
        lambda md_file, *args, **kwargs: received.update(markdown=md_file),
    )
    monkeypatch.setattr(
        convert_latex,
        "copy_figures",
        lambda source_dir, output_dir: received.update(source=source_dir),
    )
    monkeypatch.setattr(sys, "argv", ["convert_latex.py", "hep-th/9901001"])

    convert_latex.main()

    assert received == {
        "markdown": Path("hep-th_9901001") / "hep-th_9901001.md",
        "source": source,
    }


@pytest.mark.parametrize(
    ("module", "function", "subdirectory"),
    [
        ("convert_pdf_with_vision", "convert_pdf_to_images", "images"),
        ("convert_pdf_split_columns", "convert_pdf_split_columns", "images_split"),
    ],
)
def test_image_script_default_directory_is_named_after_the_pdf_under_cwd(
    module, function, subdirectory, tmp_path
):
    # The PDF sits in a subdirectory and its name has two dots, so a default
    # built from the PDF's directory, or from a stem cut at the first dot, would
    # print a different path. Each script imports its converter by name, so the
    # stand-in replaces the name bound in the script module.
    pdf = tmp_path / "sub" / "2409.03108.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-stub")
    program = f"""
import sys
sys.path.insert(0, {str(PACKAGE_DIR)!r})
import {module}

def record(pdf_path, output_dir, *args, **kwargs):
    print(output_dir)

{module}.{function} = record
sys.argv = [{module + ".py"!r}, "sub/2409.03108.pdf"]
{module}.main()
"""
    result = _run(["-c", program], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(Path("2409.03108") / subdirectory)


@pytest.mark.parametrize(
    "script",
    ["fetch_paper.py", "convert_latex.py", "convert_pdf_simple.py"],
)
def test_the_metadata_handoff_option_is_not_advertised(script, tmp_path):
    # The option carries convert_paper's lookup between its own steps. It is not
    # an interface for users, so --help leaves it out.
    result = _run([str(PACKAGE_DIR / script), "--help"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--metadata-handoff" not in result.stdout


def test_argparse_accepts_a_metadata_handoff_path_without_exit_2(tmp_path):
    # The option converts its value with Path, which accepts any string argparse
    # hands to it. A converter that rejected a value would make argparse exit 2,
    # which convert_paper would report as an ambiguous main .tex. The run stops
    # at the empty source directory, before the handoff is read.
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    result = _run(
        [
            str(PACKAGE_DIR / "convert_latex.py"),
            "2409.03108",
            "--source-dir",
            str(source_dir),
            "--metadata-handoff",
            "not/a/real/handoff.json",
        ],
        tmp_path,
    )
    # No main .tex in an empty source directory is a generic failure.
    assert result.returncode == 1, f"stdout: {result.stdout}\nstderr: {result.stderr}"


def test_convert_pdf_simple_refuses_a_handoff_with_no_arxiv_id(tmp_path):
    # --arxiv-id is optional there, so this pairing is reachable from the
    # command line. Refused at the entry the user invoked, naming the option,
    # rather than as a ValueError out of the converter — and with exit 1, since
    # exit 2 is reserved.
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF-stub")
    result = _run(
        [
            str(PACKAGE_DIR / "convert_pdf_simple.py"),
            str(pdf),
            "--metadata-handoff",
            str(tmp_path / "handoff.json"),
        ],
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    # On stderr, where the other scripts report their argument errors, so a
    # wrapper that reports a failed child from its stderr has the reason.
    assert "--metadata-handoff" in result.stderr
    assert "Traceback" not in combined


def test_convert_pdf_simple_passes_the_handoff_path_through(tmp_path):
    # The PDF step runs under uv with its dependencies, so the forwarding is
    # observed by replacing the converter inside a plain child interpreter.
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF-stub")
    handoff = tmp_path / "handoff.json"
    program = f"""
import sys
sys.path.insert(0, {str(PACKAGE_DIR)!r})
import convert_pdf_simple

def record(**kwargs):
    print(repr(kwargs["arxiv_id"]), repr(str(kwargs["metadata_handoff"])))

convert_pdf_simple.convert_pdf_to_markdown = record
sys.argv = ["convert_pdf_simple.py", {str(pdf)!r}, "--arxiv-id", "2409.03108",
            "--metadata-handoff", {str(handoff)!r}]
convert_pdf_simple.main()
"""
    result = _run(["-c", program], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"'2409.03108' {str(handoff)!r}"
