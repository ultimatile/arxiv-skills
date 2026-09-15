"""Shared test fixtures: metadata-lookup outcomes and a network guard.

`test_arxiv_metadata.py` builds its own outcomes, because it tests how
`MetadataFetch` is constructed.
"""

import os
from pathlib import Path

import pytest

from arxiv_doc_builder.arxiv_metadata import (
    METADATA_OK,
    METADATA_UNAVAILABLE,
    ArxivMetadata,
    MetadataFetch,
)

PROBE_ERROR = "OSError: connection reset"
PROBE_VERSION = "2409.03108v2"

# The environment variable naming the file the network guard records into.
NETWORK_RECORD_ENV = "ARXIV_DOC_BUILDER_TEST_NETWORK_RECORD"

# Imported at startup by every Python process a test starts, through PYTHONPATH.
_NETWORK_GUARD = """\
import os
import urllib.request


def _refuse(url, *args, **kwargs):
    target = getattr(url, "full_url", url)
    with open(os.environ["ARXIV_DOC_BUILDER_TEST_NETWORK_RECORD"], "a", encoding="utf-8") as record:
        record.write(f"{target}\\n")
    raise OSError(f"network access is blocked in tests: {target}")


urllib.request.urlopen = _refuse
"""


@pytest.fixture(autouse=True)
def network_record(tmp_path_factory, monkeypatch):
    """Refuse and record every ``urlopen`` in the Python processes a test starts.

    A test that runs a script as a subprocess is out of reach of in-process
    patches, and a failed lookup only prints a warning, so a real request would
    pass unnoticed. The guard is a ``sitecustomize`` module on ``PYTHONPATH``,
    which a child interpreter imports at startup. It does not reach the pytest
    process itself, where tests replace the lookup or the transport directly,
    and it leaves non-Python children such as ``uv`` and ``curl`` alone.

    Yields the record file, and fails the test at teardown if a URL was
    appended to it.
    """
    guard_dir = tmp_path_factory.mktemp("network-guard")
    (guard_dir / "sitecustomize.py").write_text(_NETWORK_GUARD, encoding="utf-8")
    record = guard_dir / "attempts.log"
    record.write_text("", encoding="utf-8")
    inherited = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join(p for p in (str(guard_dir), inherited) if p)
    )
    monkeypatch.setenv(NETWORK_RECORD_ENV, str(record))
    yield record
    # Read with the builtin, not Path.read_text: a test may still have that
    # method patched when this teardown runs.
    with open(record, encoding="utf-8") as handle:
        attempts = handle.read()
    if attempts:
        pytest.fail(f"a subprocess tried to reach the network:\n{attempts}")


@pytest.fixture
def failed_probe() -> MetadataFetch:
    """A lookup that never reached a record."""
    return MetadataFetch(METADATA_UNAVAILABLE, error=PROBE_ERROR)


@pytest.fixture
def probe_with_version() -> MetadataFetch:
    """A record that was read and carries a version."""
    return MetadataFetch(METADATA_OK, metadata=ArxivMetadata(version=PROBE_VERSION))


@pytest.fixture
def probe_without_version() -> MetadataFetch:
    """A record that was read but carries no version.

    The cell that separates "the lookup failed" from "no version to record":
    both leave the sidecar unwritten, by different routes.
    """
    return MetadataFetch(METADATA_OK, metadata=ArxivMetadata(version=None))


@pytest.fixture
def patch_fetch(monkeypatch):
    """Point a module's ``fetch_metadata`` at a fixed outcome.

    Each caller-level test replaces the same name in one module or the other,
    so the module is the only thing that varies.
    """

    def install(module, probe: MetadataFetch) -> None:
        monkeypatch.setattr(module, "fetch_metadata", lambda _id: probe)

    return install


def status_of(document: Path) -> str:
    """The ``metadata_status`` value the document's frontmatter carries."""
    for line in document.read_text(encoding="utf-8").splitlines():
        if line.startswith("metadata_status:"):
            return line.split(":", 1)[1].strip().strip('"')
    raise AssertionError(f"no metadata_status line in {document}")


def refuse_lookup(_arxiv_id: str) -> MetadataFetch:
    """A ``fetch_metadata`` stand-in for steps that must not look anything up."""
    raise AssertionError("a step given a metadata handoff looked the record up")
