"""Tests for version drift detection logic.

They cover the pure decisions the drift check rests on, namely whether to
re-fetch, what version the lookup reports, whether to write the record, and
what to say when a run fetched material without advancing it. The cache read and
write helpers underneath are covered too. Nothing here touches the network.
"""

import pytest

from conftest import PROBE_ERROR, PROBE_VERSION

from arxiv_doc_builder.fetch_paper import (
    _format_sidecar_skip_warning,
    _latest_version,
    _needs_refresh,
    _read_cached_version,
    _record_version,
    _target_version,
    _write_cached_version,
    _METADATA_FILE,
)


def test_needs_refresh_no_cache_with_latest(tmp_path):
    """No metadata file → re-fetch to establish version record."""
    assert _needs_refresh(tmp_path, "2409.03108v2") is True


def test_needs_refresh_no_cache_lookup_failed(tmp_path):
    """No metadata and no version from the lookup → trust cache (no re-fetch)."""
    assert _needs_refresh(tmp_path, None) is False


def test_needs_refresh_version_matches(tmp_path):
    """Cached version matches latest → skip."""
    _write_cached_version(tmp_path, "2409.03108v2")
    assert _needs_refresh(tmp_path, "2409.03108v2") is False


def test_needs_refresh_version_differs(tmp_path):
    """Cached v1, latest v2 → re-fetch."""
    _write_cached_version(tmp_path, "2409.03108v1")
    assert _needs_refresh(tmp_path, "2409.03108v2") is True


def test_needs_refresh_lookup_failed_with_cache(tmp_path):
    """Lookup reports no version but cache exists → trust cache."""
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


@pytest.mark.parametrize(
    "content",
    ['{"version": 2}', '{"version": null}', '["2409.03108v2"]'],
    ids=["number", "null", "not-an-object"],
)
def test_a_version_that_is_not_text_reads_as_absent(tmp_path, content):
    # The readers downstream match this value against a pattern, which raises
    # on a non-string. A hand-edited sidecar must not end the run.
    (tmp_path / _METADATA_FILE).write_text(content, encoding="utf-8")
    assert _read_cached_version(tmp_path) is None
    assert _needs_refresh(tmp_path, "2409.03108v2") is True
    assert _target_version(tmp_path, "2409.03108v2", pinned=False) == "2409.03108v2"


def test_write_overwrites(tmp_path):
    """Second write overwrites the first."""
    _write_cached_version(tmp_path, "2409.03108v1")
    _write_cached_version(tmp_path, "2409.03108v2")
    assert _read_cached_version(tmp_path) == "2409.03108v2"


def test_a_pinned_id_after_a_record_of_another_revision_refreshes_once(tmp_path):
    """A pinned id reports its own revision; a sidecar naming another one re-fetches
    once, which downloads the same pinned revision, and is stable afterwards."""
    _write_cached_version(tmp_path, "2409.03108v2")
    assert _needs_refresh(tmp_path, "2409.03108v1") is True
    assert _record_version(tmp_path, "2409.03108v1", fetched=True) is True
    assert _needs_refresh(tmp_path, "2409.03108v1") is False


@pytest.mark.parametrize(
    ("cached", "latest", "pinned", "target"),
    [
        (None, "2409.03108v2", False, "2409.03108v2"),
        ("2409.03108v1", "2409.03108v2", False, "2409.03108v2"),
        ("2409.03108v2", "2409.03108v2", False, "2409.03108v2"),
        # DataCite can lag arXiv, and an earlier run may already hold the later
        # revision. Going back would delete the source only to fetch it again.
        ("2409.03108v3", "2409.03108v2", False, "2409.03108v3"),
        ("2409.03108v10", "2409.03108v9", False, "2409.03108v10"),
        # A requested revision is what the user asked for, whatever is cached.
        ("2409.03108v3", "2409.03108v2", True, "2409.03108v2"),
        # A record of another paper, or of a different spelling of the id, says
        # nothing about this lookup's revision.
        ("2409.03109v3", "2409.03108v2", False, "2409.03108v2"),
        ("math/0309136v3", "math/0309136v2", False, "math/0309136v3"),
        ("2409.03108v3", None, False, None),
    ],
    ids=[
        "no-record",
        "record-older",
        "record-equal",
        "record-newer",
        "record-newer-numerically",
        "pinned-overrides-newer-record",
        "record-of-another-paper",
        "legacy-record-newer",
        "no-version-from-lookup",
    ],
)
def test_target_version_keeps_a_later_recorded_revision_of_an_unpinned_id(
    tmp_path, cached, latest, pinned, target
):
    # The recorded revision speaks for material on disk, so these cases seed
    # some; the case without it is its own test below.
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "main.tex").write_text("x", encoding="utf-8")
    if cached is not None:
        _write_cached_version(tmp_path, cached)
    assert _target_version(tmp_path, latest, pinned=pinned) == target


def test_a_record_without_a_cached_source_cannot_outvote_the_lookup(tmp_path):
    # A sidecar naming a revision that no longer exists would otherwise be
    # re-confirmed on every run, while the source download for that revision
    # failed on every run and the LaTeX path never came back.
    _write_cached_version(tmp_path, "2409.03108v99")
    assert _target_version(tmp_path, "2409.03108v2", pinned=False) == "2409.03108v2"

    # A cached PDF does not change that: the source would still be fetched at
    # the recorded revision, which is the download that fails.
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "2409.03108.pdf").write_bytes(b"%PDF-stub")
    assert _target_version(tmp_path, "2409.03108v2", pinned=False) == "2409.03108v2"

    # A cached source is what the record speaks for, so it wins there.
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "main.tex").write_text("x", encoding="utf-8")
    assert _target_version(tmp_path, "2409.03108v2", pinned=False) == "2409.03108v99"


# --- what the lookup yields, and when the sidecar advances ------------------


def test_latest_version_reads_the_version_off_a_successful_probe(probe_with_version):
    assert _latest_version(probe_with_version) == PROBE_VERSION


def test_latest_version_is_none_when_the_probe_failed(failed_probe):
    assert _latest_version(failed_probe) is None


def test_latest_version_is_none_when_the_record_carried_no_version(
    probe_without_version,
):
    # A record can parse and still yield no version, reaching the same
    # decision as a failed lookup by a different route. That is why the
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
    # A usable record *was* read here, so the warning must not say otherwise. A
    # message shared with the conversion paths would, since theirs opens by
    # reporting that no usable record was read.
    assert "no usable" not in text


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
