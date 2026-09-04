"""Tests for version drift detection logic.

The pure decisions the drift check rests on, meaning whether to re-fetch, what
version the probe reports, whether to write the record, and what to say when a
run fetched material without advancing it. Plus the cache helpers underneath.
None of them touches the network.
"""

import pytest

from conftest import PROBE_ERROR, PROBE_VERSION

from arxiv_doc_builder.fetch_paper import (
    _format_sidecar_skip_warning,
    _latest_version,
    _needs_refresh,
    _read_cached_version,
    _record_version,
    _write_cached_version,
    _METADATA_FILE,
)


def test_needs_refresh_no_cache_with_latest(tmp_path):
    """No metadata file → re-fetch to establish version record."""
    assert _needs_refresh(tmp_path, "2409.03108v2") is True


def test_needs_refresh_no_cache_api_offline(tmp_path):
    """No metadata and API offline → trust cache (no re-fetch)."""
    assert _needs_refresh(tmp_path, None) is False


def test_needs_refresh_version_matches(tmp_path):
    """Cached version matches latest → skip."""
    _write_cached_version(tmp_path, "2409.03108v2")
    assert _needs_refresh(tmp_path, "2409.03108v2") is False


def test_needs_refresh_version_differs(tmp_path):
    """Cached v1, latest v2 → re-fetch."""
    _write_cached_version(tmp_path, "2409.03108v1")
    assert _needs_refresh(tmp_path, "2409.03108v2") is True


def test_needs_refresh_api_offline_with_cache(tmp_path):
    """API offline but cache exists → trust cache."""
    _write_cached_version(tmp_path, "2409.03108v1")
    assert _needs_refresh(tmp_path, None) is False


def test_write_then_read_roundtrip(tmp_path):
    """Write and read back the version string."""
    _write_cached_version(tmp_path, "2409.03108v2")
    assert _read_cached_version(tmp_path) == "2409.03108v2"


def test_read_missing_file(tmp_path):
    """No metadata file → None."""
    assert _read_cached_version(tmp_path) is None


def test_read_corrupt_file(tmp_path):
    """Corrupt metadata → None (graceful fallback)."""
    (tmp_path / _METADATA_FILE).write_text("not json", encoding="utf-8")
    assert _read_cached_version(tmp_path) is None


def test_write_overwrites(tmp_path):
    """Second write overwrites the first."""
    _write_cached_version(tmp_path, "2409.03108v1")
    _write_cached_version(tmp_path, "2409.03108v2")
    assert _read_cached_version(tmp_path) == "2409.03108v2"


# --- what the probe yields, and when the sidecar advances -------------------


def test_latest_version_reads_the_tail_off_a_successful_probe(probe_with_version):
    assert _latest_version(probe_with_version) == PROBE_VERSION


def test_latest_version_is_none_when_the_probe_failed(failed_probe):
    assert _latest_version(failed_probe) is None


def test_latest_version_is_none_when_the_record_carried_no_version(
    probe_without_version,
):
    # A record can parse and still yield no version tail, reaching the same
    # decision as a failed request by a different route. That is why the
    # sidecar branches on the version and not on the status.
    assert _latest_version(probe_without_version) is None


@pytest.mark.parametrize(
    ("latest", "fetched", "expected"),
    [
        ("2409.03108v2", True, True),
        ("2409.03108v2", False, False),
        (None, True, False),
        (None, False, False),
    ],
    ids=[
        "version-and-material",
        "version-no-material",
        "no-version-but-material",
        "neither",
    ],
)
def test_record_version_writes_only_with_both_a_version_and_material(
    tmp_path, latest, fetched, expected
):
    assert _record_version(tmp_path, latest, fetched=fetched) is expected
    assert _read_cached_version(tmp_path) == (latest if expected else None)


def test_record_version_leaves_an_existing_record_alone_when_it_declines(tmp_path):
    # Declining must not clear what a previous run established, or the next
    # drift check would re-fetch a paper whose version it already knew.
    _write_cached_version(tmp_path, "2409.03108v1")
    assert _record_version(tmp_path, None, fetched=True) is False
    assert _read_cached_version(tmp_path) == "2409.03108v1"


def test_sidecar_skip_warning_reports_a_failed_request_by_its_cause(failed_probe):
    text = _format_sidecar_skip_warning("2409.03108", failed_probe)
    assert PROBE_ERROR in text
    assert _METADATA_FILE in text


def test_sidecar_skip_warning_names_the_missing_version_when_the_record_was_read(
    probe_without_version,
):
    # This is the cell a status-only branch would leave silent: the request
    # succeeded, so there is no error to quote, yet the sidecar still did not
    # advance and the user still needs to hear it.
    text = _format_sidecar_skip_warning("2409.03108", probe_without_version)
    assert "2409.03108" in text
    assert "no version" in text
    assert _METADATA_FILE in text
    # The record *was* read here, so the warning must not say otherwise. A
    # message shared with the conversion paths would, since theirs opens by
    # reporting an unread record.
    assert "could not read" not in text


def test_sidecar_skip_warning_stays_off_the_frontmatter(failed_probe):
    # This step writes no document, so it has no null fields to explain.
    # Borrowing the conversion paths' wording would describe a surface the
    # fetch step never touches.
    text = _format_sidecar_skip_warning("2409.03108", failed_probe)
    assert "null" not in text
    assert "frontmatter" not in text


def test_sidecar_skip_warning_refuses_a_probe_that_did_report_a_version(
    probe_with_version,
):
    # Its whole text asserts that no version was available. Called on a probe
    # that supplied one, every sentence it returns would be false.
    with pytest.raises(ValueError):
        _format_sidecar_skip_warning("2409.03108", probe_with_version)
