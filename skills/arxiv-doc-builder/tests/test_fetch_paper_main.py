"""When the fetch entry point warns that the drift record stood still.

`test_version_drift.py` covers the parts. `main()` holds only their
composition, and an inverted operand there passes every test of either part.
These drive `main()` with the lookup and both downloads replaced.
"""

import sys

import pytest
from conftest import PROBE_ERROR, PROBE_VERSION, refuse_lookup

from arxiv_doc_builder import fetch_paper
from arxiv_doc_builder.arxiv_metadata import write_metadata_handoff


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    """Invoke ``main()`` with the lookup and both downloads replaced.

    The lookup outcome comes either from ``probe``, standing in for the lookup
    ``main()`` makes itself, or from a handoff file written with ``handoff``, in
    which case a lookup would fail the test. Returns the paper directory the run
    wrote into, so a caller can check whether the sidecar landed.
    """

    def run(*, probe=None, handoff=None, has_source, has_pdf):
        argv = ["fetch_paper.py", "2409.03108", "--output-dir", str(tmp_path)]
        if handoff is not None:
            handoff_file = tmp_path / "handoff.json"
            write_metadata_handoff(handoff_file, "2409.03108", handoff)
            argv += ["--metadata-handoff", str(handoff_file)]
            monkeypatch.setattr(fetch_paper, "_probe_metadata", refuse_lookup)
        else:
            monkeypatch.setattr(fetch_paper, "_probe_metadata", lambda _id: probe)
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(fetch_paper, "fetch_source", lambda *a, **k: has_source)
        monkeypatch.setattr(fetch_paper, "fetch_pdf", lambda *a, **k: has_pdf)
        fetch_paper.main()
        return tmp_path / "2409.03108"

    return run


def test_material_without_a_version_warns_and_writes_no_sidecar(
    run_main, capsys, failed_probe
):
    paper_dir = run_main(probe=failed_probe, has_source=True, has_pdf=False)
    assert not (paper_dir / fetch_paper._METADATA_FILE).exists()
    assert fetch_paper._METADATA_FILE in capsys.readouterr().err


def test_material_with_a_version_records_it_and_stays_silent(
    run_main, capsys, probe_with_version
):
    # The other side of the composed condition: warning here would fire on
    # every ordinary successful run.
    paper_dir = run_main(probe=probe_with_version, has_source=True, has_pdf=True)
    assert fetch_paper._read_cached_version(paper_dir) == PROBE_VERSION
    assert capsys.readouterr().err == ""


def test_a_run_that_obtained_nothing_fails_instead_of_warning(
    run_main, capsys, failed_probe
):
    # No material means no successful-looking result to qualify, so the run
    # exits non-zero on its own and the drift warning would only add noise.
    with pytest.raises(SystemExit) as exit_info:
        run_main(probe=failed_probe, has_source=False, has_pdf=False)
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == ""


def test_a_read_record_without_a_version_warns_the_same_way(
    run_main, capsys, probe_without_version
):
    # The cell that separates branching on the version from branching on the
    # status. The lookup succeeded here, so a warning gated on `unavailable`
    # would stay silent while the sidecar still went unwritten.
    paper_dir = run_main(probe=probe_without_version, has_source=True, has_pdf=False)
    assert not (paper_dir / fetch_paper._METADATA_FILE).exists()
    assert fetch_paper._METADATA_FILE in capsys.readouterr().err


def test_a_handed_over_record_drives_the_sidecar_without_a_lookup(
    run_main, capsys, probe_with_version
):
    paper_dir = run_main(handoff=probe_with_version, has_source=True, has_pdf=True)
    assert fetch_paper._read_cached_version(paper_dir) == PROBE_VERSION
    assert capsys.readouterr().err == ""


def test_a_handed_over_failure_is_quoted_in_the_warning(run_main, capsys, failed_probe):
    paper_dir = run_main(handoff=failed_probe, has_source=True, has_pdf=False)
    assert not (paper_dir / fetch_paper._METADATA_FILE).exists()
    assert PROBE_ERROR in capsys.readouterr().err
