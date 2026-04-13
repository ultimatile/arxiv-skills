"""Tests for version drift detection logic.

These tests verify the pure decision logic (_needs_refresh,
_read_cached_version, _write_cached_version) without network access.
"""

from arxiv_doc_builder.fetch_paper import (
    _needs_refresh,
    _read_cached_version,
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
