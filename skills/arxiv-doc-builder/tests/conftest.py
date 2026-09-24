"""Metadata-lookup outcomes shared by the modules that need one as an input.

`test_arxiv_metadata.py` builds its own, because it tests how `MetadataFetch`
is constructed.
"""

from pathlib import Path

import pytest

from arxiv_doc_builder.arxiv_metadata import (
    METADATA_OK,
    METADATA_SOURCE_ARXIV,
    METADATA_UNAVAILABLE,
    ArxivMetadata,
    MetadataFetch,
)

PROBE_ERROR = "OSError: connection reset"
PROBE_VERSION = "2409.03108v2"


@pytest.fixture
def failed_probe() -> MetadataFetch:
    """A lookup that never reached a record."""
    return MetadataFetch(METADATA_UNAVAILABLE, error=PROBE_ERROR)


@pytest.fixture
def probe_with_version() -> MetadataFetch:
    """A record that was read and carries a version.

    Every ``ok`` outcome a lookup produces names the source it was read from,
    and a handoff written from one that does not is rejected, so these carry
    one.
    """
    return MetadataFetch(
        METADATA_OK,
        metadata=ArxivMetadata(version=PROBE_VERSION, source=METADATA_SOURCE_ARXIV),
    )


@pytest.fixture
def probe_without_version() -> MetadataFetch:
    """A record that was read but carries no version.

    The cell that separates "the lookup failed" from "no version to record":
    both leave the sidecar unwritten, by different routes.
    """
    return MetadataFetch(
        METADATA_OK,
        metadata=ArxivMetadata(version=None, source=METADATA_SOURCE_ARXIV),
    )


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


def seed_cached_source(paper_dir: Path) -> None:
    """Put a cached LaTeX source under ``paper_dir``.

    A recorded revision outranks the one a lookup reports only while a source
    is cached, since that material is what the record speaks for. A test of
    that rule therefore has to seed one, and one that seeds none is testing the
    opposite branch.
    """
    source = paper_dir / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "main.tex").write_text("x", encoding="utf-8")


def refuse_lookup(_arxiv_id: str) -> MetadataFetch:
    """A ``fetch_metadata`` stand-in for steps that must not look anything up."""
    raise AssertionError("a step given a metadata handoff looked the record up")
