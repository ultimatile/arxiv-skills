"""Contract tests for the metadata lookup and the frontmatter producer.

The frontmatter is the provenance surface a downstream consumer reads, so the
schema must be total (every key always present) and the emitted text must be
valid, re-parseable YAML, including the absence-confirmation contract where a
value missing from the record renders as YAML null instead of an absent key.
That null confirms an absence only under ``metadata_status: ok``. Under the
other tokens no usable record was read and the same null reports ignorance,
which is why the tests below pin the status alongside the fields it qualifies.

The round-trip assertions use PyYAML (a test-only dependency) as an independent
oracle; ``importorskip`` keeps the suite green in a bare environment without it,
while the structural assertions below pin the contract with no dependency.

The lookup tests replace the HTTP transport and read DataCite responses from
``fixtures/datacite``, reduced from real responses to the attributes the
mapping reads (each entry kept as DataCite serves it) plus the record's DOI,
type and version count, so nothing here reaches the network.
"""

import io
import math
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Optional

import pytest

import arxiv_doc_builder.arxiv_metadata as arxiv_metadata
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
    read_metadata_handoff,
    write_metadata_handoff,
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
    "metadata_source",
    "conversion_date",
    "abstract",
}

_FIXTURES = Path(__file__).parent / "fixtures" / "datacite"

_FULL = ArxivMetadata(
    title="A Study of Things",
    authors=["Chiara Capecci", "C. Balázs", "C. -P. Yuan"],
    version="2606.09995v1",
    published="2026-06-08",
    primary_category="quant-ph",
    categories=["quant-ph", "cond-mat.str-el"],
    doi="10.1103/PhysRevD.76.013009",
    journal="Phys. Rev. D 76, 013009 (2007)",
    abstract="Line one.\n  wrapped   with   odd spacing\nand a colon: here.",
    source=arxiv_metadata.METADATA_SOURCE_ARXIV,
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
    yaml = pytest.importorskip("yaml")
    inner = frontmatter.split("---\n", 1)[1].rsplit("\n---", 1)[0]
    return yaml.safe_load(inner)


def _record(arxiv_id: str) -> bytes:
    """The stored DataCite response for ``arxiv_id``."""
    return (_FIXTURES / (arxiv_id.replace("/", "_") + ".json")).read_bytes()


# --- structural contract (no third-party dependency) ----------------------


def test_all_keys_present_in_full_metadata():
    fm = _fm(_FULL, conversion_date="2026-06-11T10:00:00")
    for key in FRONTMATTER_KEYS:
        assert f"{key}:" in fm, f"missing key {key!r} in frontmatter"
    assert fm.startswith("---\n")
    assert "\n---\n" in fm


def test_absent_doi_renders_as_bare_null_key():
    # The absence-confirmation contract: a record with no DOI must emit `doi:`
    # (null), distinct from omitting the key. A bare `key:` line, not
    # `key: ""`, is what a parser reads as None.
    meta = ArxivMetadata(
        title="T", doi=None, source=arxiv_metadata.METADATA_SOURCE_ARXIV
    )
    fm = _fm(meta)
    assert "\ndoi:\n" in fm
    assert 'doi: ""' not in fm


def test_the_journal_key_reads_against_the_source_that_answered():
    # Only arXiv's record carries a journal reference. Under `datacite` the key
    # is null because that record has no such field, which is why the source is
    # in the frontmatter next to it.
    from_arxiv = _parse(_fm(_FULL))
    assert from_arxiv["journal"] == "Phys. Rev. D 76, 013009 (2007)"
    assert from_arxiv["metadata_source"] == arxiv_metadata.METADATA_SOURCE_ARXIV

    from_datacite = _parse(
        _fm(ArxivMetadata(title="T", source=arxiv_metadata.METADATA_SOURCE_DATACITE))
    )
    assert from_datacite["journal"] is None
    assert from_datacite["metadata_source"] == arxiv_metadata.METADATA_SOURCE_DATACITE


def test_a_record_no_source_backs_renders_the_source_null():
    # The PDF path builds a record from the PDF's own title; nothing read it
    # from arXiv or DataCite, and the null says so.
    parsed = _parse(
        _fm(
            ArxivMetadata(title="From PDF"),
            source_type="pdf",
            metadata_status=METADATA_UNAVAILABLE,
        )
    )
    assert parsed["metadata_source"] is None


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
    assert parsed["journal"] == "Phys. Rev. D 76, 013009 (2007)"
    assert parsed["source_type"] == "latex"
    assert parsed["metadata_source"] == arxiv_metadata.METADATA_SOURCE_ARXIV
    # Abstract is whitespace-normalized to a single paragraph.
    assert parsed["abstract"] == "Line one. wrapped with odd spacing and a colon: here."


def test_absent_fields_parse_to_none():
    meta = ArxivMetadata(
        title="T", doi=None, abstract=None, source=arxiv_metadata.METADATA_SOURCE_ARXIV
    )
    parsed = _parse(_fm(meta))
    assert "doi" in parsed and parsed["doi"] is None
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
    meta = ArxivMetadata(
        title='Tricky: "quotes", colon: and \\backslash',
        source=arxiv_metadata.METADATA_SOURCE_ARXIV,
    )
    parsed = _parse(_fm(meta, arxiv_id="x"))
    assert parsed["title"] == 'Tricky: "quotes", colon: and \\backslash'


def test_pdf_style_raw_author_with_newline_stays_valid_yaml():
    # The PDF fallback path builds ArxivMetadata from raw embedded metadata,
    # which bypasses the record-side normalization. An author carrying an
    # embedded newline (common in malformed PDF /Author fields) must not corrupt
    # the YAML; build_frontmatter normalizes it to a single line.
    meta = ArxivMetadata(title="T", authors=["Jane Doe\n--- affiliation"])
    parsed = _parse(
        _fm(
            meta,
            arxiv_id="x",
            source_type="pdf",
            metadata_status=METADATA_UNAVAILABLE,
        )
    )
    assert parsed["authors"] == "Jane Doe --- affiliation"


def test_non_printable_characters_are_stripped_and_yaml_stays_valid():
    # Control characters and the U+FFFE/U+FFFF noncharacters are garbage in
    # metadata, and the abstract's literal block scalar cannot escape them, so
    # normalization drops them outright. The frontmatter must stay parseable on
    # both the quoted-scalar (title, authors) and block-scalar (abstract) paths.
    # Reachable inputs: a JSON string can carry a raw C1 control through a \u
    # escape, and pypdf metadata can yield U+FFFF via a strict UTF-16BE decode
    # of \xff\xff.
    controls = "".join(chr(c) for c in (0x07, 0x1B, 0x80, 0x9F, 0x7F, 0xFFFE, 0xFFFF))
    meta = ArxivMetadata(
        title="A" + controls + "B",
        authors=["Jo" + controls + "hn"],
        abstract="Clean" + controls + "Abstract",
        source=arxiv_metadata.METADATA_SOURCE_ARXIV,
    )
    parsed = _parse(_fm(meta, arxiv_id="x", source_type="pdf"))
    assert parsed["title"] == "AB"
    assert parsed["authors"] == "John"
    assert parsed["abstract"] == "CleanAbstract"


# --- lookup: the transport, arXiv's feed and DataCite's records -------------

_ATOM_ENTRY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2606.09995v2</id>
    <title>A Study of Things</title>
    <published>2026-06-08T00:00:00Z</published>
    <summary>An abstract.</summary>
    <author><name>Chiara Capecci</name></author>
    <arxiv:primary_category term="quant-ph"/>
    <category term="quant-ph"/>
    <category term="cond-mat.str-el"/>
    <arxiv:doi>10.1103/PhysRevD.76.013009</arxiv:doi>
    <arxiv:journal_ref>Phys. Rev. D 76, 013009 (2007)</arxiv:journal_ref>
  </entry>
</feed>
"""

_ATOM_NO_ENTRY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""

_ATOM_ERROR_ENTRY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format</id>
    <title>Error</title>
    <summary>incorrect id format for nonsense</summary>
  </entry>
</feed>
"""


@pytest.fixture
def transport(monkeypatch):
    """Replace the HTTP transport so no test reaches arXiv or DataCite.

    ``install`` takes the DataCite leg's outcome and, optionally, the arXiv
    leg's: bytes (a body the lookup parses), an exception instance (raised in
    place of the request), or a callable returning a response. A test that
    installs no arXiv outcome gets a failing arXiv leg, which is what puts the
    DataCite leg under test. It returns the list the requested URLs are
    appended to, arXiv's first.
    """
    requested: list[str] = []

    def install(datacite, arxiv=None):
        if arxiv is None:
            arxiv = OSError("this test installed no arXiv outcome")

        def respond(outcome):
            if isinstance(outcome, BaseException):
                raise outcome
            if callable(outcome):
                return outcome()
            return io.BytesIO(outcome)

        def fake_urlopen(request, timeout=None):
            # The lookup passes a Request, so that it can name this client.
            url = getattr(request, "full_url", request)
            requested.append(url)
            on_arxiv = url.startswith(arxiv_metadata._ARXIV_API_URL)
            return respond(arxiv if on_arxiv else datacite)

        monkeypatch.setattr(arxiv_metadata.urllib.request, "urlopen", fake_urlopen)
        return requested

    return install


def _datacite_requests(requested: list[str]) -> list[str]:
    return [url for url in requested if url.startswith(arxiv_metadata._DATACITE_URL)]


def _http_error(code: int) -> urllib.error.HTTPError:
    from email.message import Message

    return urllib.error.HTTPError(
        "https://api.datacite.org", code, "msg", Message(), io.BytesIO()
    )


# --- lookup: arXiv's feed, and the fallback to DataCite ---------------------


def test_the_arxiv_record_maps_onto_the_frontmatter_fields(transport):
    requested = transport(b"unused", arxiv=_ATOM_ENTRY)
    result = fetch_metadata("2606.09995")

    assert requested == [arxiv_metadata._ARXIV_API_URL + "?id_list=2606.09995"], (
        "arXiv is asked first, and its answer ends the lookup"
    )
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.title == "A Study of Things"
    assert result.metadata.authors == ["Chiara Capecci"]
    assert result.metadata.version == "2606.09995v2"
    assert result.metadata.published == "2026-06-08"
    assert result.metadata.primary_category == "quant-ph"
    assert result.metadata.categories == ["quant-ph", "cond-mat.str-el"]
    assert result.metadata.doi == "10.1103/PhysRevD.76.013009"
    assert result.metadata.journal == "Phys. Rev. D 76, 013009 (2007)"
    assert result.metadata.abstract == "An abstract."
    assert result.metadata.source == arxiv_metadata.METADATA_SOURCE_ARXIV


@pytest.mark.parametrize(
    ("arxiv_outcome", "cause"),
    [
        (_http_error(429), "arXiv rate-limited the request (HTTP 429)"),
        (_http_error(503), "arXiv server error (HTTP 503)"),
        (_http_error(403), "HTTP 403"),
        (OSError("connection reset"), "OSError: connection reset"),
        (b"<feed>not closed", "arXiv returned malformed XML: "),
        (_ATOM_NO_ENTRY, "arXiv returned no record for this id"),
        (_ATOM_ERROR_ENTRY, "incorrect id format for nonsense"),
    ],
    ids=["429", "5xx", "other-http", "os-error", "malformed-xml", "no-entry", "error"],
)
def test_datacite_answers_when_arxiv_does_not(transport, arxiv_outcome, cause):
    requested = transport(_record("2409.03108"), arxiv=arxiv_outcome)
    result = fetch_metadata("2409.03108")

    assert _datacite_requests(requested) == [
        arxiv_metadata._DATACITE_URL + "2409.03108"
    ]
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.source == arxiv_metadata.METADATA_SOURCE_DATACITE
    assert cause  # the arXiv leg's cause, kept for the both-failed message


def test_a_failure_on_both_sources_names_what_each_one_said(transport):
    transport(_http_error(404), arxiv=_http_error(429))
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.failure_cause == (
        "arXiv: arXiv rate-limited the request (HTTP 429); "
        "DataCite: DataCite has no record for 10.48550/arXiv.2606.09995 (HTTP 404)"
    )


@pytest.mark.parametrize(
    ("id_url", "version"),
    [
        ("http://arxiv.org/abs/2409.03108v2", "2409.03108v2"),
        ("http://arxiv.org/abs/hep-th/9901001v3", "hep-th/9901001v3"),
        ("http://[unclosed", "[unclosed"),
        (None, None),
    ],
    ids=["canonical", "legacy", "unparseable-url", "absent"],
)
def test_the_version_comes_from_the_entry_id_tail(id_url, version):
    assert arxiv_metadata.parse_version_from_id(id_url) == version


@pytest.mark.parametrize(
    ("arxiv_id", "expected"),
    [
        (
            "2409.03108",
            {
                "title": "Loop Series Expansions for Tensor Networks",
                "authors": [
                    "Glen Evenbly",
                    "Nicola Pancotti",
                    "Ashley Milsted",
                    "Johnnie Gray",
                    "Garnet Kin-Lic Chan",
                ],
                "version": "2409.03108v2",
                "published": "2024-09-04",
                "primary_category": "quant-ph",
                "categories": ["quant-ph", "cond-mat.dis-nn"],
                "doi": "10.1103/vqks-cr6x",
            },
        ),
        (
            # A collaboration: DataCite gives only `name`.
            "1207.7214",
            {
                "authors": ["The ATLAS Collaboration"],
                "version": "1207.7214v2",
                "published": "2012-07-31",
                "primary_category": "hep-ex",
                "categories": ["hep-ex"],
                "doi": "10.1016/j.physletb.2012.08.020",
            },
        ),
        (
            # "Yu" is Personal without a givenName and "Hao" a single name tagged
            # Organizational; `name` holds each as arXiv lists them.
            "2609.14487",
            {
                "authors": ["Yu", "Hao"],
                "version": "2609.14487v1",
                "primary_category": "econ.GN",
                "doi": None,
            },
        ),
        (
            # A legacy id keeps its slash, and DataCite stores the DOI lowercased.
            "hep-th/9711200",
            {
                "authors": ["Juan M. Maldacena"],
                "version": "hep-th/9711200v3",
                "published": "1997-11-27",
                "categories": ["hep-th"],
                "doi": "10.1023/a:1026654312961",
            },
        ),
        (
            # The primary category comes first even though it is not the
            # alphabetically first code.
            "2203.02155",
            {
                "version": "2203.02155v1",
                "published": "2022-03-04",
                "primary_category": "cs.CL",
                "categories": ["cs.CL", "cs.AI", "cs.LG"],
                "doi": None,
            },
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_datacite_record_maps_onto_the_frontmatter_fields(
    transport, arxiv_id, expected
):
    requested = transport(_record(arxiv_id))
    result = fetch_metadata(arxiv_id)

    assert _datacite_requests(requested) == [arxiv_metadata._DATACITE_URL + arxiv_id]
    assert result.status == METADATA_OK
    assert result.metadata is not None
    for field_name, value in expected.items():
        assert getattr(result.metadata, field_name) == value, field_name
    assert result.metadata.title
    assert result.metadata.abstract


def test_the_abstract_is_the_abstract_description_not_the_comments(transport):
    transport(_record("2409.03108"))
    result = fetch_metadata("2409.03108")
    assert result.metadata is not None
    assert result.metadata.abstract is not None
    assert result.metadata.abstract.startswith("Belief propagation (BP)")
    assert "Main text: 6 pages" not in result.metadata.abstract


def test_html_entities_in_record_prose_are_decoded(transport):
    # DataCite's abstract for 1207.7214 stores "H->ZZ" as "H-&gt;ZZ".
    transport(_record("1207.7214"))
    result = fetch_metadata("1207.7214")
    assert result.metadata is not None
    assert result.metadata.abstract is not None
    assert "H->ZZ" in result.metadata.abstract
    assert "&gt;" not in result.metadata.abstract


def test_html_entities_in_titles_and_author_names_are_decoded():
    attributes = {
        "titles": [{"title": "A &amp; B"}],
        "creators": [
            {"givenName": "J&ouml;rg", "familyName": "M&uuml;ller"},
            {"name": "R&amp;D Group"},
        ],
    }
    meta = arxiv_metadata._parse_record("2001.00001", attributes)
    assert meta.title == "A & B"
    assert meta.authors == ["Jörg Müller", "R&D Group"]


@pytest.mark.parametrize("revision", [1, 2])
def test_a_requested_revision_is_recorded_and_looked_up_by_the_bare_id(
    transport, revision
):
    requested = transport(_record("2409.03108"))
    result = fetch_metadata(f"2409.03108v{revision}")
    assert _datacite_requests(requested) == [
        arxiv_metadata._DATACITE_URL + "2409.03108"
    ]
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.version == f"2409.03108v{revision}"


def test_the_arxiv_request_keeps_a_requested_revision(transport):
    # The two legs treat a pinned id oppositely, which is why the frontmatter
    # documents them apart. DataCite holds one record per paper, so the test
    # above asks it by the bare id and the record follows the latest revision.
    # arXiv answers per revision, so it is asked for the one requested and its
    # record describes that revision rather than the paper's latest.
    feed = _ATOM_ENTRY.replace(b"2606.09995v2", b"2606.09995v1")
    requested = transport(b"unused", arxiv=feed)
    result = fetch_metadata("2606.09995v1")

    assert requested == [arxiv_metadata._ARXIV_API_URL + "?id_list=2606.09995v1"]
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.version == "2606.09995v1"


@pytest.mark.parametrize(
    ("arxiv_id", "doi_id"),
    [
        ("math.GT/0309136", "math/0309136"),
        ("cond-mat.str-el/0601234v2", "cond-mat/0601234"),
        ("hep-th/9711200", "hep-th/9711200"),
    ],
)
def test_a_legacy_subject_class_is_left_out_of_the_doi_looked_up(
    transport, arxiv_id, doi_id
):
    # DataCite answers 404 for 10.48550/arXiv.math.GT/0309136 and 200 for
    # 10.48550/arXiv.math/0309136.
    requested = transport(_http_error(404))
    result = fetch_metadata(arxiv_id)
    assert _datacite_requests(requested) == [arxiv_metadata._DATACITE_URL + doi_id]
    assert result.failure_cause.endswith(
        f"DataCite: DataCite has no record for 10.48550/arXiv.{doi_id} (HTTP 404)"
    )


@pytest.mark.parametrize(
    ("arxiv_id", "version"),
    [
        ("math.GT/0309136", "math/0309136v2"),
        ("math.GT/0309136v1", "math/0309136v1"),
    ],
)
def test_both_sources_spell_a_legacy_version_the_way_arxiv_does(
    transport, arxiv_id, version
):
    # The version-drift check compares this string with the sidecar's. A
    # DataCite answer spelling it with the subject class would read as another
    # paper, and the fetch step would delete the cached source over it.
    transport(_record("2409.03108"))
    result = fetch_metadata(arxiv_id)
    assert result.metadata is not None
    assert result.metadata.version == version


def test_the_arxiv_request_drops_a_legacy_subject_class(transport):
    # arXiv answers a legacy id only under the archive alone; the subject-class
    # spelling returns an empty feed, which would send every such paper to the
    # fallback and lose the journal reference only arXiv's record carries.
    requested = transport(b"unused", arxiv=_ATOM_ENTRY)
    fetch_metadata("math.GT/0309136")
    assert requested == [arxiv_metadata._ARXIV_API_URL + "?id_list=math%2F0309136"]


def test_a_version_the_entry_id_does_not_support_is_dropped(transport):
    # `version` is the tail of the entry's id URL, and it reaches the download
    # URLs and the drift record. A feed whose id parses to something that names
    # no revision of this paper leaves the record versionless instead.
    feed = _ATOM_ENTRY.replace(
        b"<id>http://arxiv.org/abs/2606.09995v2</id>", b"<id>http://[unclosed</id>"
    )
    transport(b"unused", arxiv=feed)
    result = fetch_metadata("2606.09995")

    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.version is None
    assert result.metadata.title == "A Study of Things"


def test_a_rejected_id_is_reported_by_what_arxiv_said(transport):
    # arXiv answers a malformed id with HTTP 400 whose body holds an error
    # entry. The entry says what was wrong with the id; the status does not.
    from email.message import Message

    rejected = urllib.error.HTTPError(
        arxiv_metadata._ARXIV_API_URL,
        400,
        "Bad Request",
        Message(),
        io.BytesIO(_ATOM_ERROR_ENTRY),
    )
    transport(_http_error(404), arxiv=rejected)
    result = fetch_metadata("2606.09995")
    assert result.failure_cause.startswith(
        "arXiv: arXiv rejected the id: incorrect id format for nonsense"
    )


def test_a_withdrawn_revision_counts_as_the_latest(transport):
    # DataCite lists a withdrawal as `Withdrawn`, labelled "v2; None", while
    # arXiv's own record names v2 as the paper's latest. Counting only
    # `Submitted` entries would have the two sources disagree, and the
    # version-drift check reads a disagreement as a new revision.
    transport(_record("0705.1442"))
    result = fetch_metadata("0705.1442")
    assert result.metadata is not None
    assert result.metadata.version == "0705.1442v2"
    # `published` stays the first revision's date, as arXiv's record reports it.
    assert result.metadata.published == "2007-05-10"


def test_both_requests_name_this_client(monkeypatch):
    # arXiv asks API clients to identify themselves, and an unidentified one is
    # the first a public API throttles — the failure this lookup exists to
    # survive.
    agents: list[Optional[str]] = []

    def fake_urlopen(request, timeout=None):
        agents.append(request.get_header("User-agent"))
        raise OSError("offline")

    monkeypatch.setattr(arxiv_metadata.urllib.request, "urlopen", fake_urlopen)
    fetch_metadata("2409.03108")
    assert agents == [arxiv_metadata._USER_AGENT, arxiv_metadata._USER_AGENT]


def test_a_trickling_arxiv_leg_leaves_the_fallback_its_time(transport):
    # urlopen's timeout bounds each socket operation, not the request, so a
    # response arriving in slow pieces — what a rate-limited service often
    # does — would spend the whole deadline and the fallback would never be
    # asked, in exactly the case the fallback was added for.
    def trickle():
        time.sleep(1.0)
        return io.BytesIO(_ATOM_ENTRY)

    transport(_record("2409.03108"), arxiv=trickle)
    started = time.monotonic()
    result = fetch_metadata("2409.03108", deadline=0.4)
    elapsed = time.monotonic() - started

    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.source == arxiv_metadata.METADATA_SOURCE_DATACITE
    assert elapsed < 0.9, "the arXiv leg was abandoned, not waited out"


def test_an_error_response_is_closed_on_each_leg(transport):
    # An HTTPError is an open response holding a socket, and urlopen raises it
    # before any `with` can bind it, so each leg closes it by hand.
    from email.message import Message

    arxiv_body = io.BytesIO(_ATOM_ERROR_ENTRY)
    datacite_body = io.BytesIO(b"{}")
    transport(
        urllib.error.HTTPError(
            arxiv_metadata._DATACITE_URL, 404, "Not Found", Message(), datacite_body
        ),
        arxiv=urllib.error.HTTPError(
            arxiv_metadata._ARXIV_API_URL, 400, "Bad Request", Message(), arxiv_body
        ),
    )
    fetch_metadata("2606.09995")

    assert arxiv_body.closed
    assert datacite_body.closed


def test_an_unclassified_datacite_failure_keeps_the_arxiv_cause(transport):
    # The mirror image of the arXiv leg's guard: an exception DataCite's leg
    # does not classify must not report itself alone, dropping what arXiv said.
    import http.client

    transport(http.client.IncompleteRead(b"half"), arxiv=_http_error(429))
    result = fetch_metadata("2409.03108")
    assert result.status == METADATA_UNAVAILABLE
    assert result.failure_cause.startswith(
        "arXiv: arXiv rate-limited the request (HTTP 429); DataCite: IncompleteRead"
    )


def test_an_unclassified_arxiv_failure_still_reaches_the_fallback(transport):
    # http.client's exceptions are not OSError, so a response dropped midway —
    # which is what an overloaded arXiv does — must not skip DataCite.
    import http.client

    requested = transport(
        _record("2409.03108"), arxiv=http.client.IncompleteRead(b"half")
    )
    result = fetch_metadata("2409.03108")
    assert _datacite_requests(requested) == [
        arxiv_metadata._DATACITE_URL + "2409.03108"
    ]
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.source == arxiv_metadata.METADATA_SOURCE_DATACITE


def test_a_requested_revision_with_no_listed_revisions_is_ok(transport):
    # With no Submitted dates there is no latest revision to compare against, so
    # the requested one is not rejected.
    transport(b'{"data": {"attributes": {"titles": [{"title": "T"}]}}}')
    result = fetch_metadata("2001.00001v3")
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.version == "2001.00001v3"


def test_a_requested_revision_beyond_the_record_is_unavailable(transport):
    transport(_record("2409.03108"))
    result = fetch_metadata("2409.03108v3")
    assert result.status == METADATA_UNAVAILABLE
    assert result.failure_cause.endswith(
        "DataCite: 2409.03108v3 is later than v2, the latest revision DataCite "
        "lists for 2409.03108"
    )


# --- lookup: mapping rules on shapes the stored records do not cover --------


def _submitted(*labels: str) -> list[dict]:
    return [
        {
            "date": f"2020-01-{i + 1:02d}T00:00:00Z",
            "dateType": "Submitted",
            "dateInformation": label,
        }
        for i, label in enumerate(labels)
    ]


def test_the_latest_revision_compares_numerically():
    attributes = {"dates": _submitted("v1", "v9", "v10")}
    assert (
        arxiv_metadata._parse_record("2001.00001", attributes).version
        == "2001.00001v10"
    )


def test_no_submitted_date_leaves_version_and_published_null():
    attributes = {"dates": [{"date": "2020", "dateType": "Issued"}]}
    meta = arxiv_metadata._parse_record("2001.00001", attributes)
    assert meta.version is None
    assert meta.published is None


@pytest.mark.parametrize(
    ("date", "published"),
    [
        ("2020-01-02T03:04:05Z", "2020-01-02"),
        ("2020-01-02", "2020-01-02"),
        ("2020-01", None),
        ("2020", None),
    ],
)
def test_published_is_null_unless_the_v1_date_carries_a_calendar_date(date, published):
    attributes = {
        "dates": [{"date": date, "dateType": "Submitted", "dateInformation": "v1"}]
    }
    assert arxiv_metadata._parse_record("2001.00001", attributes).published == published


def test_a_record_with_wrongly_shaped_fields_parses_to_empty_fields():
    # DataCite is an external producer; a null or mistyped field must not raise.
    attributes = {
        "titles": "not a list",
        "creators": None,
        "dates": {"v1": "2020"},
        "subjects": [5, None],
        "relatedIdentifiers": 7,
        "descriptions": [["Abstract"]],
    }
    meta = arxiv_metadata._parse_record("2001.00001", attributes)
    assert meta == ArxivMetadata(source=arxiv_metadata.METADATA_SOURCE_DATACITE)


def test_the_first_non_empty_title_is_taken():
    attributes = {"titles": [{"title": "  "}, {"title": "Second"}]}
    assert arxiv_metadata._parse_record("2001.00001", attributes).title == "Second"


def test_a_creator_without_both_name_parts_falls_back_to_name():
    attributes = {
        "creators": [
            {"name": "Doe, Jane", "givenName": "Jane", "familyName": "Doe"},
            {"name": "Plato", "givenName": "Plato"},
            {"name": "Nobody Given", "familyName": "Given"},
            {"givenName": "", "familyName": ""},
        ]
    }
    authors = arxiv_metadata._parse_record("2001.00001", attributes).authors
    assert authors == ["Jane Doe", "Plato", "Nobody Given"]


def test_only_arxiv_subjects_with_a_code_become_categories():
    attributes = {
        "subjects": [
            {"subject": "Mathematical Physics (math-ph)", "subjectScheme": "arXiv"},
            {
                "subject": "FOS: Physical sciences",
                "subjectScheme": "Fields of Science and Technology (FOS)",
            },
            {"subject": "No code here", "subjectScheme": "arXiv"},
            {"subject": "Quantum Physics (quant-ph)", "subjectScheme": "arXiv"},
        ]
    }
    meta = arxiv_metadata._parse_record("2001.00001", attributes)
    assert meta.categories == ["math-ph", "quant-ph"]
    assert meta.primary_category == "math-ph"


def test_only_version_of_dois_are_transcribed_and_several_are_joined():
    attributes = {
        "relatedIdentifiers": [
            {
                "relationType": "IsVersionOf",
                "relatedIdentifierType": "DOI",
                "relatedIdentifier": "10.1/a",
            },
            {
                "relationType": "IsVersionOf",
                "relatedIdentifierType": "URL",
                "relatedIdentifier": "https://x",
            },
            {
                "relationType": "IsCitedBy",
                "relatedIdentifierType": "DOI",
                "relatedIdentifier": "10.1/c",
            },
            {
                "relationType": "IsVersionOf",
                "relatedIdentifierType": "DOI",
                "relatedIdentifier": "10.1/B",
            },
        ]
    }
    assert arxiv_metadata._parse_record("2001.00001", attributes).doi == "10.1/a 10.1/B"


def test_a_record_without_an_abstract_description_has_a_null_abstract():
    attributes = {
        "descriptions": [{"description": "5 pages", "descriptionType": "Other"}]
    }
    assert arxiv_metadata._parse_record("2001.00001", attributes).abstract is None


# --- lookup: failures, each with its own cause ------------------------------


@pytest.mark.parametrize(
    ("outcome", "cause"),
    [
        (
            _http_error(404),
            "DataCite has no record for 10.48550/arXiv.2606.09995 (HTTP 404)",
        ),
        (_http_error(429), "DataCite rate-limited the request (HTTP 429)"),
        (_http_error(503), "DataCite server error (HTTP 503)"),
        (_http_error(403), "HTTP 403"),
        (
            urllib.error.URLError("Name or service not known"),
            "URLError: Name or service not known",
        ),
        (OSError("connection reset"), "OSError: connection reset"),
        (b'{"data": {"attributes": null}}', "DataCite response has no data.attributes"),
        (b"[]", "DataCite response has no data.attributes"),
        (b'{"errors": []}', "DataCite response has no data.attributes"),
    ],
    ids=[
        "404",
        "429",
        "5xx",
        "other-http",
        "url-error",
        "os-error",
        "null-attributes",
        "top-level-list",
        "no-data",
    ],
)
def test_each_failure_is_unavailable_with_its_own_cause(transport, outcome, cause):
    transport(outcome)
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.metadata is None
    assert result.failure_cause.endswith(f"DataCite: {cause}")


@pytest.mark.parametrize("body", [b"{not json", b"\xff\xfe\xfa"], ids=["json", "utf-8"])
def test_an_unparseable_body_is_unavailable(transport, body):
    transport(body)
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert "DataCite: DataCite returned malformed JSON: " in result.failure_cause


def test_an_unanticipated_exception_in_the_lookup_is_still_unavailable(
    transport, monkeypatch
):
    transport(_record("2409.03108"))

    def boom(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(arxiv_metadata, "_parse_record", boom)
    result = fetch_metadata("2409.03108")
    assert result.status == METADATA_UNAVAILABLE
    # Each leg is guarded, so an exception neither of them anticipated is still
    # reported alongside what the other source said.
    assert result.failure_cause.endswith("DataCite: RuntimeError: boom")


def test_surrogates_in_codes_and_dois_are_dropped_before_they_reach_a_handoff(tmp_path):
    # A JSON string can carry a lone surrogate through a \u escape, which no
    # UTF-8 file can hold.
    attributes = arxiv_metadata.json.loads(
        r"""
        {
          "subjects": [{"subject": "Broken (\ud800)", "subjectScheme": "arXiv"}],
          "relatedIdentifiers": [
            {
              "relationType": "IsVersionOf",
              "relatedIdentifierType": "DOI",
              "relatedIdentifier": "10.1/a\udfff"
            }
          ]
        }
        """
    )
    meta = arxiv_metadata._parse_record("2001.00001", attributes)
    assert meta.categories == []
    assert meta.doi == "10.1/a"
    path = tmp_path / "handoff.json"
    fetch = MetadataFetch(METADATA_OK, metadata=meta)
    write_metadata_handoff(path, "2001.00001", fetch)
    assert read_metadata_handoff(path, "2001.00001") == fetch


def test_a_worker_that_cannot_start_is_unavailable(monkeypatch):
    class Unstartable:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(arxiv_metadata.threading, "Thread", Unstartable)
    result = fetch_metadata("2409.03108")
    assert result.status == METADATA_UNAVAILABLE
    assert result.error == "RuntimeError: can't start new thread"


# The test ends the worker with an uncaught SystemExit on purpose, which pytest
# reports as an unhandled thread exception.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_worker_that_ends_without_a_result_is_not_reported_as_late(monkeypatch):
    def exit_thread(*_args):
        raise SystemExit

    monkeypatch.setattr(arxiv_metadata, "_lookup", exit_thread)
    result = fetch_metadata("2409.03108", deadline=5)
    assert result.status == METADATA_UNAVAILABLE
    assert result.error == "metadata lookup ended without a result"


# --- lookup: the deadline ----------------------------------------------------


def test_the_deadline_bounds_how_long_the_call_waits(transport):
    def slow():
        time.sleep(2)
        return io.BytesIO(_record("2409.03108"))

    transport(slow)
    started = time.monotonic()
    result = fetch_metadata("2409.03108", deadline=0.5)
    elapsed = time.monotonic() - started

    assert result.status == METADATA_UNAVAILABLE
    assert elapsed < 1.5
    # The legs together may spend only _CHAIN_DEADLINE_SHARE of the deadline,
    # so the chain composes its answer inside the remaining headroom and the
    # caller learns what each source said. Without that headroom the outer
    # bound wins the race and replaces both causes with its own timeout.
    assert result.failure_cause.startswith("arXiv: ")
    assert "DataCite: the DataCite lookup exceeded" in result.failure_cause


def test_the_process_exits_without_waiting_for_an_abandoned_lookup():
    # A worker the interpreter joins at exit would hold the process until the
    # request ended, which is what a daemon thread avoids.
    program = textwrap.dedent(
        """
        import time, urllib.request
        import arxiv_doc_builder.arxiv_metadata as m

        def hang(url, timeout=None):
            time.sleep(30)

        urllib.request.urlopen = hang
        print(m.fetch_metadata("2409.03108", deadline=0.2).status)
        """
    )
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=60
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == METADATA_UNAVAILABLE
    assert elapsed < 10


@pytest.mark.parametrize(
    "deadline",
    [0, -1.0, math.nan, math.inf, threading.TIMEOUT_MAX * 2, 10**400],
    ids=["zero", "negative", "nan", "inf", "above-timeout-max", "huge-int"],
)
def test_a_deadline_that_cannot_bound_the_lookup_is_rejected(deadline, monkeypatch):
    # A finite value above threading.TIMEOUT_MAX would otherwise start the
    # request and then make worker.join raise OverflowError.
    started: list[object] = []
    monkeypatch.setattr(arxiv_metadata, "_lookup", lambda *a: started.append(a))
    with pytest.raises(ValueError):
        fetch_metadata("2409.03108", deadline=deadline)
    assert started == []


def test_the_largest_accepted_deadline_is_timeout_max(transport):
    transport(OSError("offline"))
    result = fetch_metadata("2409.03108", deadline=threading.TIMEOUT_MAX)
    assert result.failure_cause.endswith("DataCite: OSError: offline")


def test_each_leg_is_given_its_share_of_the_deadline_as_a_socket_timeout(monkeypatch):
    # A request that stalls outright ends on its own only because urlopen
    # receives a timeout. The arXiv leg gets a share of the deadline so a slow
    # failure there cannot spend what the DataCite leg needs.
    timeouts: list[float] = []

    def fake_urlopen(url, timeout=None):
        assert timeout is not None, "every leg passes its budget as the timeout"
        timeouts.append(timeout)
        raise OSError("offline")

    monkeypatch.setattr(arxiv_metadata.urllib.request, "urlopen", fake_urlopen)
    fetch_metadata("2409.03108", deadline=0.75)
    pool = 0.75 * arxiv_metadata._CHAIN_DEADLINE_SHARE
    assert timeouts[0] == pool * arxiv_metadata._ARXIV_DEADLINE_SHARE
    # Neither leg is handed the deadline itself: both draw on a pool smaller
    # than it, which leaves the chain room to compose its answer before the
    # outer bound fires. The legs run in sequence, so these budgets bound what
    # each may spend, not what the two spend together — the pool bounds that.
    assert 0 < timeouts[1] <= pool
    assert len(timeouts) == 2


def test_the_legs_may_not_spend_the_whole_deadline_between_them():
    # The behavioural test above reports the rule only when it wins a race it
    # is not guaranteed to win: let the legs have the whole deadline and the
    # chain finishes just as the outer bound fires, so which answer reaches the
    # caller is a coin toss. The rule that settles it is this one, and a
    # strictly smaller pool is what it says, so it is asserted on its own too.
    assert 0 < arxiv_metadata._CHAIN_DEADLINE_SHARE < 1


@pytest.mark.parametrize(
    "deadline",
    [Decimal("5"), Fraction(5), True, "5", None],
    ids=["decimal", "fraction", "bool", "str", "none"],
)
def test_a_deadline_that_is_not_an_int_or_float_is_rejected_before_the_lookup(
    deadline, monkeypatch
):
    # Decimal and Fraction pass the range check, so without the type check the
    # request would start and worker.join would raise afterwards.
    started: list[object] = []
    monkeypatch.setattr(arxiv_metadata, "_lookup", lambda *a: started.append(a))
    with pytest.raises(TypeError):
        fetch_metadata("2409.03108", deadline=deadline)
    assert started == []


# --- handoff between processes -----------------------------------------------


@pytest.mark.parametrize(
    "fetch",
    [
        MetadataFetch(METADATA_OK, metadata=_FULL),
        MetadataFetch(
            METADATA_OK,
            metadata=ArxivMetadata(source=arxiv_metadata.METADATA_SOURCE_ARXIV),
        ),
        MetadataFetch(
            METADATA_OK,
            metadata=ArxivMetadata(
                title='q"uote \\ back\nline é \x85',
                authors=[""],
                source=arxiv_metadata.METADATA_SOURCE_ARXIV,
            ),
        ),
        MetadataFetch(
            METADATA_OK,
            metadata=ArxivMetadata(
                title="   ",
                categories=["\ud800"],
                doi="10.1/\udfff",
                source=arxiv_metadata.METADATA_SOURCE_DATACITE,
            ),
        ),
        MetadataFetch(METADATA_UNAVAILABLE, error="URLError: timed out"),
    ],
    ids=[
        "full",
        "empty-record",
        "string-edges",
        "blank-and-unencodable",
        "unavailable",
    ],
)
def test_a_handoff_reads_back_equal_to_what_was_written(tmp_path, fetch):
    path = tmp_path / "handoff.json"
    write_metadata_handoff(path, "2606.09995", fetch)
    assert read_metadata_handoff(path, "2606.09995") == fetch


def test_the_handoff_schema_lists_every_field_of_the_record():
    # The two lists are hand-maintained, and the reader rejects a handoff whose
    # key set differs from them. A field added to the record without being
    # listed here would make every handoff unreadable, and `unavailable` is
    # what a child would then write — discarding a parent lookup that
    # succeeded, with the suite still green.
    listed = set(arxiv_metadata._HANDOFF_SCALARS) | set(arxiv_metadata._HANDOFF_LISTS)
    fields = {f.name for f in arxiv_metadata.dataclasses.fields(ArxivMetadata)}
    assert listed == fields


def test_a_handoff_path_given_as_a_string_is_read(tmp_path):
    path = tmp_path / "handoff.json"
    fetch = MetadataFetch(METADATA_OK, metadata=_FULL)
    write_metadata_handoff(path, "2606.09995", fetch)
    assert read_metadata_handoff(str(path), "2606.09995") == fetch  # type: ignore[arg-type]


_GOOD_METADATA = {
    "title": "T",
    "authors": ["A"],
    "version": None,
    "published": None,
    "primary_category": None,
    "categories": [],
    "doi": None,
    "journal": None,
    "abstract": None,
    "source": arxiv_metadata.METADATA_SOURCE_ARXIV,
}


def _handoff(**overrides) -> dict:
    fetch = {"status": METADATA_OK, "metadata": dict(_GOOD_METADATA), "error": None}
    fetch.update(overrides.pop("fetch", {}))
    payload = {"arxiv_id": "2606.09995", "fetch": fetch}
    payload.update(overrides)
    return payload


def _with_metadata(**fields) -> dict:
    return _handoff(fetch={"metadata": {**_GOOD_METADATA, **fields}})


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        _handoff(extra=1),
        _handoff(arxiv_id="2606.09995v1"),
        _handoff(fetch={"status": 5}),
        _handoff(fetch={"status": METADATA_UNAVAILABLE, "metadata": None, "error": 5}),
        _handoff(
            fetch={"status": METADATA_UNAVAILABLE, "metadata": None, "error": "  "}
        ),
        _handoff(fetch={"status": METADATA_OK, "metadata": None}),
        _handoff(fetch={"metadata": ["T"]}),
        {
            "arxiv_id": "2606.09995",
            "fetch": {"status": METADATA_OK, "metadata": _GOOD_METADATA},
        },
        _with_metadata(authors="A"),
        _with_metadata(authors=["A", 1]),
        _with_metadata(title=7),
        _with_metadata(title=True),
        _with_metadata(source="bogus"),
        _with_metadata(source=None),
        {
            **_handoff(),
            "fetch": {
                **_handoff()["fetch"],
                "metadata": {**_GOOD_METADATA, "bogus": None},
            },
        },
    ],
    ids=[
        "not-json",
        "not-an-object",
        "extra-top-level-key",
        "other-id",
        "status-not-a-string",
        "error-not-a-string",
        "blank-error",
        "ok-without-record",
        "metadata-not-an-object",
        "missing-error-key",
        "authors-a-string",
        "authors-with-a-number",
        "title-a-number",
        "title-a-bool",
        "source-outside-the-vocabulary",
        "ok-without-a-source",
        "unknown-metadata-key",
    ],
)
def test_an_untrustworthy_handoff_is_unavailable_with_a_cause(tmp_path, content):
    import json

    path = tmp_path / "handoff.json"
    path.write_text(
        content if isinstance(content, str) else json.dumps(content), encoding="utf-8"
    )
    result = read_metadata_handoff(path, "2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.failure_cause.startswith("metadata handoff unreadable: ")


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_a_handoff_path_that_is_not_a_readable_file_is_unavailable(tmp_path, kind):
    path = tmp_path / "handoff.json"
    if kind == "directory":
        path.mkdir()
    result = read_metadata_handoff(path, "2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.failure_cause.startswith("metadata handoff unreadable: ")


# --- fetch outcome: status, cause, and what each one licenses ---------------


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
    # Only `ok` may carry a record that names a source, so the other tokens get
    # a record with none — which is what they mean.
    record = _FULL if status == METADATA_OK else ArxivMetadata(title=_FULL.title)
    parsed = _parse(_fm(record, arxiv_id=arxiv_id, metadata_status=status))
    assert parsed["metadata_status"] == status
    assert parsed["metadata_source"] == (
        arxiv_metadata.METADATA_SOURCE_ARXIV if status == METADATA_OK else None
    )
    assert set(parsed.keys()) == FRONTMATTER_KEYS


@pytest.mark.parametrize(
    "source", [None, "bogus"], ids=["absent", "outside-the-vocabulary"]
)
def test_ok_needs_a_record_naming_one_of_the_two_sources(source):
    # The other half of the same invariant. `ok` says a record was read, so it
    # must say which one, in the vocabulary the document tells a consumer to
    # expect — a null there would read as "no record was read".
    with pytest.raises(ValueError):
        _fm(ArxivMetadata(title="T", source=source))


@pytest.mark.parametrize("status", [METADATA_UNAVAILABLE, METADATA_NOT_REQUESTED])
@pytest.mark.parametrize(
    "source",
    [arxiv_metadata.METADATA_SOURCE_ARXIV, "bogus"],
    ids=["in-the-vocabulary", "outside-it"],
)
def test_a_status_other_than_ok_cannot_carry_a_record_naming_a_source(status, source):
    # `metadata_source` is what tells a consumer which record a null field was
    # absent from. Emitting one beside a status that says no usable record was
    # read would claim a record answered when none did — and a token outside
    # the vocabulary claims it as loudly as a valid one, so null is the only
    # value these statuses admit.
    arxiv_id = None if status == METADATA_NOT_REQUESTED else "2606.09995"
    with pytest.raises(ValueError):
        _fm(
            ArxivMetadata(title="T", source=source),
            arxiv_id=arxiv_id,
            metadata_status=status,
        )


def test_unknown_status_token_is_rejected_rather_than_rendered():
    # A consumer branches on this key. An unrecognized token would render as
    # one more state to handle.
    with pytest.raises(ValueError):
        _fm(_FULL, metadata_status="degraded")


def test_a_populated_record_does_not_imply_the_record_was_read():
    # The PDF path builds a record from the PDF's own title when the lookup
    # failed. A present record is not evidence that DataCite was reached. Only
    # metadata_status answers that.
    from_pdf = ArxivMetadata(title="From The PDF", authors=["Jane Doe"])
    parsed = _parse(
        _fm(from_pdf, source_type="pdf", metadata_status=METADATA_UNAVAILABLE)
    )
    assert parsed["title"] == "From The PDF"
    assert parsed["metadata_status"] == METADATA_UNAVAILABLE
    assert parsed["doi"] is None


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
    # Without an id there is nothing to look up, so neither "the record was
    # read" nor "the request failed" describes the document. Only
    # not_requested does, and rendering either other token would put a state
    # into the provenance surface that no run can produce.
    with pytest.raises(ValueError):
        _fm(None, arxiv_id=None, source_type="pdf", metadata_status=status)


def test_a_document_with_an_arxiv_id_cannot_claim_none_was_sought():
    # This is the converse the equivalence adds. An id was supplied, the record
    # was looked up, and the answer is either ok or unavailable.
    with pytest.raises(ValueError):
        _fm(_FULL, arxiv_id="2606.09995", metadata_status=METADATA_NOT_REQUESTED)


def test_the_status_tokens_are_the_documented_literals():
    # Every other status test takes both its input and its expectation from
    # these constants, so renaming one would leave the suite green while
    # breaking the frontmatter contract that consumers branch on.
    assert METADATA_OK == "ok"
    assert METADATA_UNAVAILABLE == "unavailable"
    assert METADATA_NOT_REQUESTED == "not_requested"
