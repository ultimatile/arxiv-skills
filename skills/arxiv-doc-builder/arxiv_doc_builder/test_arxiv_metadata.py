"""Contract tests for the frontmatter producer.

The frontmatter is the provenance surface a downstream consumer reads, so the
schema must be total (every key always present) and the emitted text must be
valid, re-parseable YAML — including the absence-confirmation contract where a
missing arXiv value renders as YAML null rather than an absent key.

The round-trip assertions use PyYAML (a test-only dependency) as an independent
oracle; ``importorskip`` keeps the suite green in a bare environment without it,
while the structural assertions below pin the contract with no dependency.
"""

from arxiv_doc_builder.arxiv_metadata import (
    ArxivMetadata,
    build_frontmatter,
    parse_version_from_id,
)

# The total key set every frontmatter must carry, in any state.
FRONTMATTER_KEYS = {
    "title",
    "authors",
    "arxiv_id",
    "version",
    "published",
    "primary_category",
    "categories",
    "doi",
    "journal",
    "source_type",
    "conversion_date",
    "abstract",
}

_FULL = ArxivMetadata(
    title="A Study of Things",
    authors=["Chiara Capecci", "C. Balázs", "C. -P. Yuan"],
    version="2606.09995v1",
    published="2026-06-08",
    primary_category="quant-ph",
    categories=["quant-ph", "cond-mat.str-el"],
    doi="10.1103/PhysRevD.76.013009",
    journal="Phys.Rev.D76:013009,2007",
    abstract="Line one.\n  wrapped   with   odd spacing\nand a colon: here.",
)


def _parse(frontmatter: str):
    """Parse the inner YAML of a ``---``-fenced frontmatter block via PyYAML."""
    import pytest

    yaml = pytest.importorskip("yaml")
    inner = frontmatter.split("---\n", 1)[1].rsplit("\n---", 1)[0]
    return yaml.safe_load(inner)


# --- structural contract (no third-party dependency) ----------------------


def test_all_keys_present_in_full_metadata():
    fm = build_frontmatter(
        _FULL,
        arxiv_id="2606.09995",
        source_type="latex",
        conversion_date="2026-06-11T10:00:00",
    )
    for key in FRONTMATTER_KEYS:
        assert f"{key}:" in fm, f"missing key {key!r} in frontmatter"
    assert fm.startswith("---\n")
    assert "\n---\n" in fm


def test_absent_doi_journal_render_as_bare_null_keys():
    # The absence-confirmation contract: an arXiv record with no DOI must emit
    # `doi:` (null), distinct from omitting the key. A bare `key:` line, not
    # `key: ""`, is what a parser reads as None.
    meta = ArxivMetadata(title="T", doi=None, journal=None)
    fm = build_frontmatter(
        meta, arxiv_id="2606.09995", source_type="latex", conversion_date="d"
    )
    assert "\ndoi:\n" in fm
    assert "\njournal:\n" in fm
    assert 'doi: ""' not in fm


def test_absent_arxiv_id_renders_as_null():
    # Manual PDF scripts invoke the converter without an id.
    fm = build_frontmatter(
        None,
        arxiv_id=None,
        source_type="pdf",
        conversion_date="d",
        fallback_title="From PDF",
    )
    assert "\narxiv_id:\n" in fm
    assert "From PDF" in fm


# --- round-trip contract (PyYAML oracle) ----------------------------------


def test_full_metadata_round_trips():
    fm = build_frontmatter(
        _FULL,
        arxiv_id="2606.09995",
        source_type="latex",
        conversion_date="2026-06-11T10:00:00",
    )
    parsed = _parse(fm)

    assert set(parsed.keys()) == FRONTMATTER_KEYS
    assert parsed["title"] == "A Study of Things"
    # Authors are joined into a single citation-friendly string; Unicode is
    # preserved through the double-quoted scalar.
    assert parsed["authors"] == "Chiara Capecci, C. Balázs, C. -P. Yuan"
    assert parsed["arxiv_id"] == "2606.09995"
    assert parsed["version"] == "2606.09995v1"
    assert parsed["published"] == "2026-06-08"
    assert parsed["primary_category"] == "quant-ph"
    assert parsed["categories"] == ["quant-ph", "cond-mat.str-el"]
    assert parsed["doi"] == "10.1103/PhysRevD.76.013009"
    assert parsed["journal"] == "Phys.Rev.D76:013009,2007"
    assert parsed["source_type"] == "latex"
    # Abstract is whitespace-normalized to a single paragraph.
    assert parsed["abstract"] == "Line one. wrapped with odd spacing and a colon: here."


def test_absent_fields_parse_to_none():
    meta = ArxivMetadata(title="T", doi=None, journal=None, abstract=None)
    parsed = _parse(
        build_frontmatter(
            meta, arxiv_id="2606.09995", source_type="latex", conversion_date="d"
        )
    )
    assert "doi" in parsed and parsed["doi"] is None
    assert "journal" in parsed and parsed["journal"] is None
    assert "abstract" in parsed and parsed["abstract"] is None
    assert parsed["categories"] == []
    assert parsed["authors"] is None


def test_no_metadata_keeps_title_null_not_fabricated():
    # A PDF with no embedded title and no arXiv id keeps the title null rather
    # than fabricating one from the file name — "unknown stays unknown".
    parsed = _parse(
        build_frontmatter(None, arxiv_id=None, source_type="pdf", conversion_date="d")
    )
    assert parsed["title"] is None
    assert parsed["authors"] is None
    assert parsed["arxiv_id"] is None
    assert parsed["source_type"] == "pdf"


def test_offline_metadata_keeps_total_schema_with_fallback_title():
    parsed = _parse(
        build_frontmatter(
            None,
            arxiv_id="2606.09995",
            source_type="latex",
            conversion_date="d",
            fallback_title="LaTeX Title",
        )
    )
    assert set(parsed.keys()) == FRONTMATTER_KEYS
    assert parsed["title"] == "LaTeX Title"
    assert parsed["version"] is None
    assert parsed["arxiv_id"] == "2606.09995"


def test_tricky_title_round_trips():
    meta = ArxivMetadata(title='Tricky: "quotes", colon: and \\backslash')
    parsed = _parse(
        build_frontmatter(meta, arxiv_id="x", source_type="latex", conversion_date="d")
    )
    assert parsed["title"] == 'Tricky: "quotes", colon: and \\backslash'


def test_pdf_style_raw_author_with_newline_stays_valid_yaml():
    # The PDF fallback path builds ArxivMetadata from raw embedded metadata,
    # which bypasses the Atom-side normalization. An author carrying an embedded
    # newline (common in malformed PDF /Author fields) must not corrupt the
    # YAML; build_frontmatter normalizes it to a single line.
    meta = ArxivMetadata(title="T", authors=["Jane Doe\n--- affiliation"])
    parsed = _parse(
        build_frontmatter(meta, arxiv_id="x", source_type="pdf", conversion_date="d")
    )
    assert parsed["authors"] == "Jane Doe --- affiliation"


def test_non_printable_characters_are_stripped_and_yaml_stays_valid():
    # Control characters and the U+FFFE/U+FFFF noncharacters are garbage in
    # metadata, and the abstract's literal block scalar cannot escape them, so
    # normalization drops them outright. The frontmatter must stay parseable on
    # both the quoted-scalar (title, authors) and block-scalar (abstract) paths.
    # Reachable inputs: XML 1.0 permits raw C1 controls in an arXiv summary, and
    # pypdf metadata can yield U+FFFF via a strict UTF-16BE decode of \xff\xff.
    controls = "".join(chr(c) for c in (0x07, 0x1B, 0x80, 0x9F, 0x7F, 0xFFFE, 0xFFFF))
    meta = ArxivMetadata(
        title="A" + controls + "B",
        authors=["Jo" + controls + "hn"],
        abstract="Clean" + controls + "Abstract",
    )
    parsed = _parse(
        build_frontmatter(meta, arxiv_id="x", source_type="pdf", conversion_date="d")
    )
    assert parsed["title"] == "AB"
    assert parsed["authors"] == "John"
    assert parsed["abstract"] == "CleanAbstract"


# --- version parsing ------------------------------------------------------


def test_parse_version_canonical_full_tail():
    assert parse_version_from_id("http://arxiv.org/abs/2409.03108v2") == "2409.03108v2"


def test_parse_version_legacy_full_tail():
    # Legacy ids keep their slash and the version suffix; the sidecar stores
    # exactly this form, so the parser must not strip either.
    assert (
        parse_version_from_id("http://arxiv.org/abs/hep-th/9901001v3")
        == "hep-th/9901001v3"
    )


def test_parse_version_empty_and_none():
    assert parse_version_from_id("") is None
    assert parse_version_from_id(None) is None
