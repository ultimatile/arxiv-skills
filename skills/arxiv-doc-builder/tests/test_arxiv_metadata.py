"""Contract tests for the frontmatter producer.

The frontmatter is the provenance surface a downstream consumer reads, so the
schema must be total (every key always present) and the emitted text must be
valid, re-parseable YAML, including the absence-confirmation contract where a
missing arXiv value renders as YAML null instead of an absent key. That null
confirms an absence only under ``metadata_status: ok``. Under the other tokens
the record was never read and the same null reports ignorance, which is why the
tests below pin the status alongside the fields it qualifies.

The round-trip assertions use PyYAML (a test-only dependency) as an independent
oracle; ``importorskip`` keeps the suite green in a bare environment without it,
while the structural assertions below pin the contract with no dependency.
"""

from typing import Optional

import pytest

from arxiv_doc_builder.arxiv_metadata import (
    METADATA_NOT_REQUESTED,
    METADATA_OK,
    METADATA_STATUSES,
    METADATA_UNAVAILABLE,
    ArxivMetadata,
    MetadataFetch,
    build_frontmatter,
    fetch_metadata,
    format_unavailable_warning,
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
    "metadata_status",
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


def _fm(meta: Optional[ArxivMetadata] = None, **kwargs) -> str:
    """``build_frontmatter`` with the provenance arguments defaulted.

    Every call needs an id, a source type, a date and a status. Defaulting them
    keeps each test's arguments down to what it asserts about.
    """
    kwargs.setdefault("arxiv_id", "2606.09995")
    kwargs.setdefault("source_type", "latex")
    kwargs.setdefault("conversion_date", "d")
    kwargs.setdefault("metadata_status", METADATA_OK)
    return build_frontmatter(meta, **kwargs)


def _parse(frontmatter: str):
    """Parse the inner YAML of a ``---``-fenced frontmatter block via PyYAML."""
    import pytest

    yaml = pytest.importorskip("yaml")
    inner = frontmatter.split("---\n", 1)[1].rsplit("\n---", 1)[0]
    return yaml.safe_load(inner)


# --- structural contract (no third-party dependency) ----------------------


def test_all_keys_present_in_full_metadata():
    fm = _fm(_FULL, conversion_date="2026-06-11T10:00:00")
    for key in FRONTMATTER_KEYS:
        assert f"{key}:" in fm, f"missing key {key!r} in frontmatter"
    assert fm.startswith("---\n")
    assert "\n---\n" in fm


def test_absent_doi_journal_render_as_bare_null_keys():
    # The absence-confirmation contract: an arXiv record with no DOI must emit
    # `doi:` (null), distinct from omitting the key. A bare `key:` line, not
    # `key: ""`, is what a parser reads as None.
    meta = ArxivMetadata(title="T", doi=None, journal=None)
    fm = _fm(meta)
    assert "\ndoi:\n" in fm
    assert "\njournal:\n" in fm
    assert 'doi: ""' not in fm


def test_absent_arxiv_id_renders_as_null():
    # Manual PDF scripts invoke the converter without an id.
    fm = _fm(
        None,
        arxiv_id=None,
        source_type="pdf",
        metadata_status=METADATA_NOT_REQUESTED,
        fallback_title="From PDF",
    )
    assert "\narxiv_id:\n" in fm
    assert "From PDF" in fm


# --- round-trip contract (PyYAML oracle) ----------------------------------


def test_full_metadata_round_trips():
    fm = _fm(_FULL, conversion_date="2026-06-11T10:00:00")
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
    parsed = _parse(_fm(meta))
    assert "doi" in parsed and parsed["doi"] is None
    assert "journal" in parsed and parsed["journal"] is None
    assert "abstract" in parsed and parsed["abstract"] is None
    assert parsed["categories"] == []
    assert parsed["authors"] is None


def test_no_metadata_keeps_title_null_not_fabricated():
    # A PDF with no embedded title and no arXiv id keeps the title null rather
    # than fabricating one from the file name — "unknown stays unknown".
    parsed = _parse(
        _fm(
            None,
            arxiv_id=None,
            source_type="pdf",
            metadata_status=METADATA_NOT_REQUESTED,
        )
    )
    assert parsed["title"] is None
    assert parsed["authors"] is None
    assert parsed["arxiv_id"] is None
    assert parsed["source_type"] == "pdf"


def test_offline_metadata_keeps_total_schema_with_fallback_title():
    parsed = _parse(
        _fm(
            None,
            metadata_status=METADATA_UNAVAILABLE,
            fallback_title="LaTeX Title",
        )
    )
    assert set(parsed.keys()) == FRONTMATTER_KEYS
    assert parsed["title"] == "LaTeX Title"
    assert parsed["version"] is None
    assert parsed["arxiv_id"] == "2606.09995"


def test_tricky_title_round_trips():
    meta = ArxivMetadata(title='Tricky: "quotes", colon: and \\backslash')
    parsed = _parse(_fm(meta, arxiv_id="x"))
    assert parsed["title"] == 'Tricky: "quotes", colon: and \\backslash'


def test_pdf_style_raw_author_with_newline_stays_valid_yaml():
    # The PDF fallback path builds ArxivMetadata from raw embedded metadata,
    # which bypasses the Atom-side normalization. An author carrying an embedded
    # newline (common in malformed PDF /Author fields) must not corrupt the
    # YAML; build_frontmatter normalizes it to a single line.
    meta = ArxivMetadata(title="T", authors=["Jane Doe\n--- affiliation"])
    parsed = _parse(_fm(meta, arxiv_id="x", source_type="pdf"))
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
    parsed = _parse(_fm(meta, arxiv_id="x", source_type="pdf"))
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


# --- fetch outcome: status, cause, and what each one licenses ---------------

_ATOM_ENTRY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2606.09995v1</id>
    <title>A Study of Things</title>
    <published>2026-06-08T00:00:00Z</published>
    <summary>An abstract.</summary>
    <author><name>Chiara Capecci</name></author>
    <arxiv:primary_category term="quant-ph"/>
    <category term="quant-ph"/>
    <arxiv:doi>10.1103/PhysRevD.76.013009</arxiv:doi>
  </entry>
</feed>
"""

_ATOM_NO_ENTRY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


@pytest.fixture
def transport(monkeypatch):
    """Replace the HTTP transport so no test reaches arXiv.

    Yields a setter taking either bytes (the body ``fetch_metadata`` will
    parse) or an exception instance (raised in place of the request).
    """
    import io

    import arxiv_doc_builder.arxiv_metadata as m

    def install(outcome):
        def fake_urlopen(url, timeout=None):
            if isinstance(outcome, BaseException):
                raise outcome
            return io.BytesIO(outcome)

        monkeypatch.setattr(m.urllib.request, "urlopen", fake_urlopen)

    return install


def test_fetch_reports_ok_and_the_record_when_the_request_succeeds(transport):
    transport(_ATOM_ENTRY)
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_OK
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata.title == "A Study of Things"
    assert result.metadata.version == "2606.09995v1"


def test_fetch_reports_the_transport_failure_rather_than_discarding_it(transport):
    # The captured cause is the whole point: without it the warning could say
    # only that something went wrong, which does not distinguish an outage from
    # a rate limit from a bad id.
    transport(OSError("connection reset"))
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.metadata is None
    assert result.error is not None
    assert "OSError" in result.error
    assert "connection reset" in result.error


def test_fetch_reports_a_parse_failure_as_unavailable(transport):
    transport(b"<feed>not closed")
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.metadata is None
    assert result.error


def test_fetch_reports_a_response_without_an_entry_as_unavailable(transport):
    # Same status as an outage, since the caller learns as little either way.
    # The cause text is what tells the two apart.
    transport(_ATOM_NO_ENTRY)
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.metadata is None
    assert result.error == "arXiv returned no record for this id"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "bogus"},
        {"status": METADATA_NOT_REQUESTED, "error": "e"},
        {"status": METADATA_OK},
        {"status": METADATA_OK, "metadata": ArxivMetadata(), "error": "e"},
        {"status": METADATA_UNAVAILABLE},
        {"status": METADATA_UNAVAILABLE, "error": ""},
        {"status": METADATA_UNAVAILABLE, "error": "   "},
        {"status": METADATA_UNAVAILABLE, "metadata": ArxivMetadata(), "error": "e"},
    ],
    ids=[
        "unknown-token",
        "not-a-fetch-outcome",
        "ok-without-record",
        "ok-with-error",
        "failed-without-cause",
        "failed-with-empty-cause",
        "failed-with-blank-cause",
        "failed-with-record",
    ],
)
def test_incoherent_fetch_outcomes_are_rejected(kwargs):
    with pytest.raises(ValueError):
        MetadataFetch(**kwargs)


def test_warning_names_the_paper_the_cause_and_what_the_document_records():
    text = format_unavailable_warning("2606.09995", cause="OSError: connection reset")
    assert "2606.09995" in text
    assert "OSError: connection reset" in text
    # A human reads "unknown", a machine reads the token.
    assert "unknown" in text
    assert METADATA_UNAVAILABLE in text


# --- metadata_status in the frontmatter ------------------------------------


@pytest.mark.parametrize(
    ("status", "arxiv_id"),
    [
        (METADATA_OK, "2606.09995"),
        (METADATA_UNAVAILABLE, "2606.09995"),
        (METADATA_NOT_REQUESTED, None),
    ],
    ids=list(METADATA_STATUSES),
)
def test_every_status_token_round_trips_into_the_document(status, arxiv_id):
    # Each token needs the id state that can produce it. The guard rejects
    # every other pairing. Taking the ids from METADATA_STATUSES while
    # spelling the cases out means a token added there and not here leaves the
    # two lengths unequal, and pytest fails at collection.
    parsed = _parse(_fm(_FULL, arxiv_id=arxiv_id, metadata_status=status))
    assert parsed["metadata_status"] == status
    assert set(parsed.keys()) == FRONTMATTER_KEYS


def test_unknown_status_token_is_rejected_rather_than_rendered():
    # A consumer branches on this key. An unrecognized token would render as
    # one more state to handle.
    with pytest.raises(ValueError):
        _fm(_FULL, metadata_status="degraded")


def test_a_populated_record_does_not_imply_the_arxiv_record_was_read():
    # The PDF path supplies a record built from the PDF's own title when arXiv
    # is unreachable. The status, not the presence of a record, is what says
    # whether arXiv was reached.
    from_pdf = ArxivMetadata(title="From The PDF", authors=["Jane Doe"])
    parsed = _parse(
        _fm(from_pdf, source_type="pdf", metadata_status=METADATA_UNAVAILABLE)
    )
    assert parsed["title"] == "From The PDF"
    assert parsed["metadata_status"] == METADATA_UNAVAILABLE
    assert parsed["doi"] is None


def test_parse_version_survives_a_url_the_parser_rejects():
    # The Atom <id> is an untrusted field of a fetched document, and an
    # unclosed IPv6 bracket makes urlparse raise. fetch_metadata reads this
    # after its try block and documents parse failures as captured, so a raise
    # here would escape that guarantee.
    assert parse_version_from_id("http://[::1/abs/2409.03108v2") == "2409.03108v2"


def test_failure_cause_is_a_plain_string_for_every_failed_outcome():
    # Callers formatting a warning need the cause unconditionally. Reading it
    # off the optional field instead would have each of them add a fallback
    # for a state __post_init__ already rules out.
    probe = MetadataFetch(METADATA_UNAVAILABLE, error="OSError: connection reset")
    assert probe.failure_cause == "OSError: connection reset"


def test_failure_cause_refuses_an_outcome_that_did_not_fail():
    with pytest.raises(ValueError):
        MetadataFetch(METADATA_OK, metadata=ArxivMetadata()).failure_cause


@pytest.mark.parametrize("status", [METADATA_OK, METADATA_UNAVAILABLE])
def test_a_document_with_no_arxiv_id_cannot_claim_a_record_was_sought(status):
    # Without an id there is nothing to ask arXiv, so neither "the record was
    # read" nor "the request failed" describes the document. Only
    # not_requested does, and rendering either other token would put a state
    # into the provenance surface that no run can produce.
    with pytest.raises(ValueError):
        _fm(None, arxiv_id=None, source_type="pdf", metadata_status=status)


def test_a_document_with_an_arxiv_id_cannot_claim_none_was_sought():
    # This is the converse the equivalence adds. An id was supplied, arXiv was
    # asked, and the answer is either ok or unavailable.
    with pytest.raises(ValueError):
        _fm(_FULL, arxiv_id="2606.09995", metadata_status=METADATA_NOT_REQUESTED)


_ATOM_ERROR_ENTRY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/api/errors#incorrect_id_format_for_2409.3108</id>
    <title>Error</title>
    <summary>incorrect id format for 2409.3108</summary>
    <author><name>arXiv api core</name></author>
  </entry>
</feed>
"""


def test_fetch_reports_an_arxiv_error_report_as_unavailable(transport):
    # arXiv answers a rejected id with an entry, not with an empty feed, and
    # that entry parses like a record. Taken at face value it writes title
    # "Error" and author "arXiv api core" into a document reporting ok, where
    # a null field reads as a confirmed absence.
    transport(_ATOM_ERROR_ENTRY)
    result = fetch_metadata("2409.3108")
    assert result.status == METADATA_UNAVAILABLE
    assert result.metadata is None
    assert result.error == "incorrect id format for 2409.3108"


_ATOM_ERROR_WITHOUT_SUMMARY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/api/errors#unspecified</id>
    <title>Error</title>
  </entry>
</feed>
"""

_ATOM_UNPARSEABLE_ID = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://[::1/abs/2409.03108v2</id>
    <title>A Study of Things</title>
  </entry>
</feed>
"""


def test_fetch_names_a_cause_when_the_error_entry_carries_no_summary(transport):
    # The warning prints the cause verbatim. An error entry can arrive without
    # a summary, and the fallback literal is what keeps that line from being
    # blank.
    transport(_ATOM_ERROR_WITHOUT_SUMMARY)
    result = fetch_metadata("2409.3108")
    assert result.status == METADATA_UNAVAILABLE
    assert result.error == "arXiv reported an error for this id"


def test_fetch_survives_an_entry_id_the_url_parser_rejects(transport):
    # The entry id is untrusted text, and an unclosed IPv6 bracket makes
    # urlparse raise. Both places that parse it run outside fetch_metadata's
    # try block, so a raise here would escape the docstring's guarantee that
    # parse failures are captured.
    transport(_ATOM_UNPARSEABLE_ID)
    result = fetch_metadata("2409.03108")
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.version == "2409.03108v2"


def test_the_status_tokens_are_the_documented_literals():
    # Every other status test takes both its input and its expectation from
    # these constants, so renaming one would leave the suite green while
    # breaking the frontmatter contract that consumers branch on.
    assert METADATA_OK == "ok"
    assert METADATA_UNAVAILABLE == "unavailable"
    assert METADATA_NOT_REQUESTED == "not_requested"
