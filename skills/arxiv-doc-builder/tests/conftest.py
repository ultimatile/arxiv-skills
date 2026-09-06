"""Metadata-probe outcomes shared by the modules that need one as an input.

`test_arxiv_metadata.py` builds its own, because it tests how `MetadataFetch`
is constructed.
"""

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


@pytest.fixture
def failed_probe() -> MetadataFetch:
    """A request that never reached a record."""
    return MetadataFetch(METADATA_UNAVAILABLE, error=PROBE_ERROR)


@pytest.fixture
def probe_with_version() -> MetadataFetch:
    """A record that was read and carries a version tail."""
    return MetadataFetch(METADATA_OK, metadata=ArxivMetadata(version=PROBE_VERSION))


@pytest.fixture
def probe_without_version() -> MetadataFetch:
    """A record that was read but carries no version tail.

    The cell that separates "the request failed" from "no version to record":
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
