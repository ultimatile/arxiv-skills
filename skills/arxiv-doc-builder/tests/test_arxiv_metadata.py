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
    "source_type",
    "metadata_status",
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
    meta = ArxivMetadata(title="T", doi=None)
    fm = _fm(meta)
    assert "\ndoi:\n" in fm
    assert 'doi: ""' not in fm


def test_the_journal_key_is_not_part_of_the_schema():
    # DataCite's record carries no journal-reference string, so a `journal`
    # key could only ever be null and would read as a confirmed absence.
    assert "journal" not in _fm(_FULL)
    assert "journal" not in {
        f.name for f in arxiv_metadata.dataclasses.fields(ArxivMetadata)
    }


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
    assert parsed["source_type"] == "latex"
    # Abstract is whitespace-normalized to a single paragraph.
    assert parsed["abstract"] == "Line one. wrapped with odd spacing and a colon: here."


def test_absent_fields_parse_to_none():
    meta = ArxivMetadata(title="T", doi=None, abstract=None)
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
    meta = ArxivMetadata(title='Tricky: "quotes", colon: and \\backslash')
    parsed = _parse(_fm(meta, arxiv_id="x"))
    assert parsed["title"] == 'Tricky: "quotes", colon: and \\backslash'


def test_pdf_style_raw_author_with_newline_stays_valid_yaml():
    # The PDF fallback path builds ArxivMetadata from raw embedded metadata,
    # which bypasses the record-side normalization. An author carrying an
    # embedded newline (common in malformed PDF /Author fields) must not corrupt
    # the YAML; build_frontmatter normalizes it to a single line.
    meta = ArxivMetadata(title="T", authors=["Jane Doe\n--- affiliation"])
    parsed = _parse(_fm(meta, arxiv_id="x", source_type="pdf"))
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
    )
    parsed = _parse(_fm(meta, arxiv_id="x", source_type="pdf"))
    assert parsed["title"] == "AB"
    assert parsed["authors"] == "John"
    assert parsed["abstract"] == "CleanAbstract"


# --- lookup: the transport and DataCite's records ---------------------------


@pytest.fixture
def transport(monkeypatch):
    """Replace the HTTP transport so no test reaches DataCite.

    ``install`` takes the outcome of the request: bytes (the body
    ``fetch_metadata`` will parse), an exception instance (raised in place of
    the request), or a callable returning a response. It returns the list the
    requested URLs are appended to.
    """
    requested: list[str] = []

    def install(outcome):
        def fake_urlopen(url, timeout=None):
            requested.append(url)
            if isinstance(outcome, BaseException):
                raise outcome
            if callable(outcome):
                return outcome()
            return io.BytesIO(outcome)

        monkeypatch.setattr(arxiv_metadata.urllib.request, "urlopen", fake_urlopen)
        return requested

    return install


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

    assert requested == [arxiv_metadata._API_URL + arxiv_id]
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
    assert requested == [arxiv_metadata._API_URL + "2409.03108"]
    assert result.status == METADATA_OK
    assert result.metadata is not None
    assert result.metadata.version == f"2409.03108v{revision}"


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
    assert result.error == (
        "2409.03108v3 is later than v2, the latest revision DataCite lists for "
        "2409.03108"
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
    assert meta == ArxivMetadata()


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


def _http_error(code: int) -> urllib.error.HTTPError:
    from email.message import Message

    return urllib.error.HTTPError(
        "https://api.datacite.org", code, "msg", Message(), io.BytesIO()
    )


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
    assert result.error == cause


@pytest.mark.parametrize("body", [b"{not json", b"\xff\xfe\xfa"], ids=["json", "utf-8"])
def test_an_unparseable_body_is_unavailable(transport, body):
    transport(body)
    result = fetch_metadata("2606.09995")
    assert result.status == METADATA_UNAVAILABLE
    assert result.failure_cause.startswith("DataCite returned malformed JSON: ")


def test_an_unanticipated_exception_in_the_lookup_is_still_unavailable(
    transport, monkeypatch
):
    transport(_record("2409.03108"))

    def boom(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(arxiv_metadata, "_parse_record", boom)
    result = fetch_metadata("2409.03108")
    assert result.status == METADATA_UNAVAILABLE
    assert result.error == "RuntimeError: boom"


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
    result = fetch_metadata("2409.03108", deadline=0.2)
    elapsed = time.monotonic() - started

    assert result.status == METADATA_UNAVAILABLE
    assert result.error == "metadata lookup exceeded the 0.2 s budget"
    assert elapsed < 1.5


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
    assert result.error == "OSError: offline"


def test_the_request_uses_the_deadline_as_its_socket_timeout(monkeypatch):
    # A request that stalls outright ends on its own only because urlopen
    # receives the deadline as its timeout.
    timeouts: list[object] = []

    def fake_urlopen(url, timeout=None):
        timeouts.append(timeout)
        raise OSError("offline")

    monkeypatch.setattr(arxiv_metadata.urllib.request, "urlopen", fake_urlopen)
    fetch_metadata("2409.03108", deadline=0.75)
    assert timeouts == [0.75]


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
        MetadataFetch(METADATA_OK, metadata=ArxivMetadata()),
        MetadataFetch(
            METADATA_OK,
            metadata=ArxivMetadata(title='q"uote \\ back\nline é \x85', authors=[""]),
        ),
        MetadataFetch(
            METADATA_OK,
            metadata=ArxivMetadata(
                title="   ", categories=["\ud800"], doi="10.1/\udfff"
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
    "abstract": None,
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
        {
            **_handoff(),
            "fetch": {
                **_handoff()["fetch"],
                "metadata": {**_GOOD_METADATA, "journal": None},
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
    parsed = _parse(_fm(_FULL, arxiv_id=arxiv_id, metadata_status=status))
    assert parsed["metadata_status"] == status
    assert set(parsed.keys()) == FRONTMATTER_KEYS


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
