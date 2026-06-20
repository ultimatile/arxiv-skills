"""Cross-script CLI-level contracts.

Promoted from review findings that revealed untested specifications:

  - Exit-code disjointness: exit code 2 is reserved for the
    "ambiguous main .tex" signal propagated through convert_latex →
    convert_paper so wrappers may retry with --tex-file. Any other
    failure — including validator rejection — must use a different code
    (currently 1) so a plain ID typo is never interpreted as a
    source-selection problem.

  - Default-path safe-normalization: when a CLI builds a default
    "papers/<id>/..." path for a legacy ID like hep-th/9901001, the
    slash must be normalized away by safe_arxiv_id before becoming a
    Path component, otherwise the resulting tree (papers/hep-th/9901001/...)
    does not match the fetch-side cache (papers/hep-th_9901001/).
"""

import subprocess
import sys
from pathlib import Path

import pytest

import arxiv_doc_builder

# Resolve the scripts via the installed package location, not relative to this
# test file — the tests live under tests/ while the scripts ship under the
# arxiv_doc_builder package, and this stays correct wherever the package sits.
_SCRIPTS_DIR = Path(arxiv_doc_builder.__file__).parent


@pytest.mark.parametrize(
    "script",
    ["fetch_paper.py", "convert_paper.py", "convert_latex.py"],
)
def test_validator_failure_exits_1_leaving_2_reserved(script, tmp_path):
    # "2506.1376" is a structurally-valid-but-non-canonical new-style ID
    # (4-digit sequence on a post-2015 paper). Every CLI entry point
    # routes this through validate_arxiv_id at argparse time and must
    # exit 1, never 2 — exit 2 belongs to the ambiguous-main-tex channel.
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / script), "2506.1376"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
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
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "convert_latex.py"), "hep-th/9901001"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    # Expected failure: no papers/ tree exists.
    assert result.returncode != 0
    combined = result.stdout + result.stderr
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
