"""When the fetch entry point warns that the drift record stood still.

`test_version_drift.py` covers the parts. `main()` holds only their
composition, and an inverted operand there passes every test of either part.
These drive `main()` with the lookup and both downloads replaced.
"""

import inspect
import sys

import pytest
from conftest import PROBE_ERROR, PROBE_VERSION, refuse_lookup, seed_cached_source

from arxiv_doc_builder import fetch_paper
from arxiv_doc_builder.arxiv_metadata import (
    METADATA_OK,
    METADATA_SOURCE_DATACITE,
    ArxivMetadata,
    MetadataFetch,
    write_metadata_handoff,
)


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    """Invoke ``main()`` with the lookup and both downloads replaced.

    The lookup outcome comes either from ``probe``, standing in for the lookup
    ``main()`` makes itself, or from a handoff file written with ``handoff``, in
    which case a lookup would fail the test. Each download reports
    ``has_source`` / ``has_pdf``, or runs ``download`` when one is given, so a
    caller can see what was asked for. Returns the paper directory the run
    wrote into, so a caller can check whether the sidecar landed.
    """

    def run(*, probe=None, handoff=None, has_source=True, has_pdf=True, download=None):
        argv = ["fetch_paper.py", "2409.03108", "--output-dir", str(tmp_path)]
        if handoff is not None:
            handoff_file = tmp_path / "handoff.json"
            write_metadata_handoff(handoff_file, "2409.03108", handoff)
            argv += ["--metadata-handoff", str(handoff_file)]
            monkeypatch.setattr(fetch_paper, "_probe_metadata", refuse_lookup)
        else:
            monkeypatch.setattr(fetch_paper, "_probe_metadata", lambda _id: probe)
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(
            fetch_paper, "fetch_source", download or (lambda *a, **k: has_source)
        )
        monkeypatch.setattr(
            fetch_paper, "fetch_pdf", download or (lambda *a, **k: has_pdf)
        )
        fetch_paper.main()
        return tmp_path / "2409.03108"

    return run


def test_the_probe_takes_exactly_one_positional_argument():
    # Every stand-in for it across the suite is a one-argument callable, and
    # those stand-ins are what keep this module off the network. A second
    # positional parameter would keep the production call working while each
    # of them raised.
    positional = [
        parameter
        for parameter in inspect.signature(
            fetch_paper._probe_metadata
        ).parameters.values()
        if parameter.kind
        in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert [parameter.name for parameter in positional] == ["arxiv_id"]


@pytest.mark.parametrize(
    ("probe_name", "downloaded"),
    [("probe_with_version", PROBE_VERSION), ("failed_probe", "2409.03108")],
)
def test_the_downloads_name_the_revision_the_sidecar_records(
    run_main, request, probe_name, downloaded
):
    # While the fallback has yet to list a revision arXiv already serves, an
    # unversioned download would put that newer revision on disk under the
    # older version the sidecar records.
    probe = request.getfixturevalue(probe_name)
    ids: list[str] = []

    def record(arxiv_id, *_args, **_kwargs):
        ids.append(arxiv_id)
        return True

    run_main(probe=probe, download=record)
    assert ids == [downloaded, downloaded]


def test_a_record_of_a_later_revision_is_kept_while_the_lookup_lags(
    run_main, tmp_path, capsys
):
    # The fallback reports PROBE_VERSION while the sidecar already records a
    # later revision. Refreshing would delete the cached source, edits
    # included, and record the older revision over newer material. Only the
    # fallback's record can trail arXiv, which is why the probe names it.
    probe_with_version = MetadataFetch(
        METADATA_OK,
        metadata=ArxivMetadata(version=PROBE_VERSION, source=METADATA_SOURCE_DATACITE),
    )
    paper_dir = tmp_path / "2409.03108"
    seed_cached_source(paper_dir)
    later = PROBE_VERSION.rsplit("v", 1)[0] + "v99"
    fetch_paper._write_cached_version(paper_dir, later)
    calls: list[tuple[str, bool]] = []

    def record(arxiv_id, *_args, refresh, **_kwargs):
        calls.append((arxiv_id, refresh))
        return True

    run_main(probe=probe_with_version, download=record)
    assert calls == [(later, False), (later, False)]
    assert fetch_paper._read_cached_version(paper_dir) == later
    # The document will name PROBE_VERSION while the body is `later`, so the
    # run says which it kept.
    err = capsys.readouterr().err
    assert PROBE_VERSION in err
    assert later in err


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
