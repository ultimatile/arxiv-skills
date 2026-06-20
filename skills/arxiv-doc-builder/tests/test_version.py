"""Tests for the --version emitter and its source-tree fallback.

The skill is normally run straight from the checkout (no install), so the
fallback path — parsing pyproject.toml — is the *primary* path here, not a
rare edge. These tests pin that behavior and the CLI contract.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import arxiv_doc_builder
from arxiv_doc_builder._version import (
    _DIST_NAME,
    _version_from_pyproject,
    read_version,
)

# Resolve the package dir via the installed package, not this test file —
# tests live under tests/ while convert_paper.py and pyproject.toml sit at the
# package and project root respectively.
_PKG_DIR = Path(arxiv_doc_builder.__file__).parent
_PYPROJECT = _PKG_DIR.parent / "pyproject.toml"


def _expected_version() -> str:
    with _PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_dist_name_is_hyphenated():
    # The lookup name must be the distribution name, which intentionally
    # differs from the underscored import name. A regression to
    # "arxiv_doc_builder" would silently miss installed metadata.
    assert _DIST_NAME == "arxiv-doc-builder"
    assert _DIST_NAME != _PKG_DIR.name


def test_read_version_matches_pyproject_ssot():
    # In the source tree (uninstalled), read_version resolves via the
    # pyproject fallback and must equal the [project] version SSOT.
    assert read_version() == _expected_version()


def test_version_from_pyproject_matches_ssot():
    assert _version_from_pyproject() == _expected_version()


def test_read_version_prefers_installed_metadata(monkeypatch):
    # When dist-info exists, read_version must return the metadata version
    # (the installed-CLI SSOT) and query it under the hyphenated dist name —
    # NOT silently fall through to the pyproject parse. The sentinel differs
    # from the pyproject version so a fall-through would fail the assertion.
    from importlib import metadata

    seen = {}

    def _fake_version(dist):
        seen["dist"] = dist
        return "9.9.9-installed"

    monkeypatch.setattr(metadata, "version", _fake_version)
    assert read_version() == "9.9.9-installed"
    assert seen["dist"] == _DIST_NAME


@pytest.mark.parametrize("fault", ["missing_key", "decode_error", "os_error"])
def test_version_from_pyproject_degrades_to_unknown(monkeypatch, fault):
    # The never-crash contract: every caught failure mode in the fallback —
    # missing [project].version (KeyError), malformed TOML (TOMLDecodeError),
    # and an unreadable pyproject (OSError) — must degrade to "unknown"
    # instead of propagating. One case per member of the caught tuple, so a
    # future narrowing or re-raise of any arm is caught.
    import arxiv_doc_builder._version as v

    if fault == "missing_key":
        monkeypatch.setattr(v.tomllib, "load", lambda f: {})
    elif fault == "decode_error":

        def _raise_decode(f):
            raise v.tomllib.TOMLDecodeError("malformed")

        monkeypatch.setattr(v.tomllib, "load", _raise_decode)
    else:  # os_error — the pyproject exists path but cannot be opened

        def _raise_os(self, *args, **kwargs):
            raise OSError("unreadable")

        monkeypatch.setattr(v.Path, "open", _raise_os)

    assert v._version_from_pyproject() == "unknown"


def test_read_version_falls_back_when_not_installed(monkeypatch):
    # PackageNotFoundError (no dist-info — the source-tree run mode) must
    # route to the pyproject fallback rather than propagate.
    from importlib import metadata

    def _raise(dist):
        raise metadata.PackageNotFoundError(dist)

    monkeypatch.setattr(metadata, "version", _raise)
    assert read_version() == _expected_version()


def test_read_version_degrades_to_unknown_on_corrupt_metadata(monkeypatch):
    # The never-raise contract must hold for unexpected metadata failures,
    # not just PackageNotFoundError: a corrupt/unparseable installed
    # distribution makes metadata.version raise a generic error, which must
    # degrade to "unknown" rather than propagate.
    from importlib import metadata

    def _raise(dist):
        raise RuntimeError("corrupt metadata")

    monkeypatch.setattr(metadata, "version", _raise)
    assert read_version() == "unknown"


def test_cli_version_flag_emits_version():
    # `--version` must print and exit 0 without requiring the positional
    # arxiv_id (action="version" is eager).
    result = subprocess.run(
        [sys.executable, str(_PKG_DIR / "convert_paper.py"), "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert _expected_version() in result.stdout


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_cli_version_short_and_long(flag):
    result = subprocess.run(
        [sys.executable, str(_PKG_DIR / "convert_paper.py"), flag],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert _expected_version() in result.stdout
