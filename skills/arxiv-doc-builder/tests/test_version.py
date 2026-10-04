"""Tests for the --version emitter and its source-tree fallback.

The skill is normally run straight from the checkout (no install), so the
fallback path — parsing pyproject.toml — is the *primary* path here, not a
rare edge. These tests pin that behavior and the CLI contract.
"""

import subprocess
import sys
import tomllib
from importlib import metadata

import pytest

from conftest import PACKAGE_DIR, SKILL_DIR
from arxiv_doc_builder import _version as version_module
from arxiv_doc_builder import convert_paper
from arxiv_doc_builder._version import (
    _DIST_NAME,
    _version_from_pyproject,
    read_version,
)

_PYPROJECT = SKILL_DIR / "pyproject.toml"


def _expected_version() -> str:
    with _PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


@pytest.fixture
def not_installed(monkeypatch):
    """Make the distribution look uninstalled, so the pyproject fallback runs."""

    def _raise(dist):
        raise metadata.PackageNotFoundError(dist)

    monkeypatch.setattr(metadata, "version", _raise)


@pytest.fixture
def sibling_pyproject(tmp_path, monkeypatch):
    """Point the fallback at ``tmp_path / "pyproject.toml"``; return its writer.

    The fallback locates pyproject.toml relative to the module's ``__file__``,
    so moving that is what redirects it. Nothing is written until the returned
    function is called, which leaves the file absent for a test that never
    calls it.
    """
    monkeypatch.setattr(
        version_module, "__file__", str(tmp_path / "pkg" / "_version.py")
    )

    def _write(content: bytes) -> None:
        (tmp_path / "pyproject.toml").write_bytes(content)

    return _write


def test_dist_name_is_hyphenated():
    # The lookup name must be the distribution name, which intentionally
    # differs from the underscored import name. A regression to
    # "arxiv_doc_builder" would silently miss installed metadata.
    assert _DIST_NAME == "arxiv-doc-builder"
    assert _DIST_NAME != PACKAGE_DIR.name


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


@pytest.mark.parametrize(
    "fault", ["missing_key", "decode_error", "os_error", "resolve_error"]
)
def test_version_from_pyproject_degrades_to_unknown(monkeypatch, fault):
    # The never-crash contract: a failure at each step of the fallback —
    # locating the pyproject (resolve_error), opening it (OSError), parsing
    # it (TOMLDecodeError), and looking up [project].version (KeyError) —
    # must degrade to "unknown" instead of propagating.
    import arxiv_doc_builder._version as v

    if fault == "missing_key":
        monkeypatch.setattr(v.tomllib, "load", lambda f: {})
    elif fault == "decode_error":

        def _raise_decode(f):
            raise v.tomllib.TOMLDecodeError("malformed")

        monkeypatch.setattr(v.tomllib, "load", _raise_decode)
    elif fault == "os_error":  # the pyproject exists path but cannot be opened

        def _raise_os(self, *args, **kwargs):
            raise OSError("unreadable")

        monkeypatch.setattr(v.Path, "open", _raise_os)
    else:  # resolve_error — the path to the pyproject cannot be built

        def _raise_resolve(self, *args, **kwargs):
            raise RuntimeError("symlink loop")

        monkeypatch.setattr(v.Path, "resolve", _raise_resolve)

    assert v._version_from_pyproject() == "unknown"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            b'[project]\nname = "\xff"\nversion = "1.2.3"\n', id="undecodable_byte"
        ),
        pytest.param(b'project = "x"\n', id="project_not_a_table"),
        pytest.param(b"[project]\nversion = 1\n", id="integer_version"),
        pytest.param(b"[project]\nversion = 2026-10-04\n", id="date_version"),
        pytest.param(b"[tool]\nx = 1\n", id="no_project_table"),
    ],
)
def test_malformed_pyproject_file_degrades_to_unknown(sibling_pyproject, content):
    # Real bytes through the real parser, so the failure each file provokes
    # is the parser's own and not one a stub chose.
    sibling_pyproject(content)
    assert _version_from_pyproject() == "unknown"


def test_absent_pyproject_file_degrades_to_unknown(sibling_pyproject):
    assert _version_from_pyproject() == "unknown"


def test_well_formed_pyproject_file_yields_its_version(sibling_pyproject):
    # The control for the two tests above: the value differs from the
    # repository's own [project] version, so it can only have come from the
    # redirected file.
    sibling_pyproject(b'[project]\nversion = "1.2.3"\n')
    assert _version_from_pyproject() == "1.2.3"


def test_read_version_falls_back_when_not_installed(not_installed):
    # PackageNotFoundError (no dist-info — the source-tree run mode) must
    # route to the pyproject fallback rather than propagate.
    assert read_version() == _expected_version()


def test_read_version_degrades_to_unknown_on_malformed_fallback_file(
    not_installed, sibling_pyproject
):
    # The route --version takes from a checkout: not installed, then a
    # pyproject the parser rejects.
    sibling_pyproject(b'[project]\nname = "\xff"\nversion = "1.2.3"\n')
    assert read_version() == "unknown"


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


def test_read_version_degrades_to_unknown_on_non_string_metadata(monkeypatch):
    # metadata.version returns None, without raising, for a distribution
    # whose METADATA carries no Version field.
    monkeypatch.setattr(metadata, "version", lambda dist: None)
    assert read_version() == "unknown"


@pytest.mark.parametrize("version", ["1%", "%(prog)s"])
def test_cli_version_prints_percent_signs_literally(monkeypatch, capsys, version):
    # argparse %-formats the whole version string, so an unescaped "%" in the
    # resolved version either raises ("1%") or is expanded ("%(prog)s").
    monkeypatch.setattr(convert_paper, "read_version", lambda: version)
    monkeypatch.setattr(sys, "argv", ["convert_paper.py", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        convert_paper.main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"convert_paper.py {version}\n"


def test_cli_version_flag_emits_version():
    # `--version` must print and exit 0 without requiring the positional
    # arxiv_id (action="version" is eager).
    result = subprocess.run(
        [sys.executable, str(PACKAGE_DIR / "convert_paper.py"), "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert _expected_version() in result.stdout


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_cli_version_short_and_long(flag):
    result = subprocess.run(
        [sys.executable, str(PACKAGE_DIR / "convert_paper.py"), flag],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert _expected_version() in result.stdout
