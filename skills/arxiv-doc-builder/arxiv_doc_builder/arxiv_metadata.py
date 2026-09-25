#!/usr/bin/env python3
"""Fetch a paper's metadata record and render the document frontmatter.

Single source of truth for the YAML frontmatter prepended to a converted
paper by both conversion paths (``convert_latex.py`` and the PDF path through
``pdf_converter_lib.py``). The frontmatter is the provenance surface a
downstream consumer reads, so it must carry the same key set regardless of
which path produced it or whether the network was reachable.

The record comes from arXiv's own Atom API. When that does not answer with one
— a rate limit, an outage, a malformed feed — the lookup falls back to the
registration arXiv files at DataCite for the paper's DOI,
``10.48550/arXiv.<id>``. ``ArxivMetadata.source`` records which of the two
answered. ``fetch_paper``'s revision handling branches on it, and in a run
``convert_paper`` starts it reaches that step through the handoff file; the
document does not carry it.

Design constraints:

- **Runtime is dependency-free.** The LaTeX path runs as a plain ``python3``
  subprocess with no third-party packages installed, so the frontmatter is
  hand-emitted rather than routed through PyYAML. A round-trip contract test
  (which *may* use PyYAML, a test-only dependency) pins the emitted text to
  valid, re-parseable YAML.
- **The schema is total.** ``build_frontmatter`` always emits every key, even
  when the lookup failed. Unknown values render as YAML null (a bare
  ``key:``), which a parser reads as ``None``, except ``categories``, which
  renders as an empty list.
- **An empty field carries no inference about the paper.** For the fields a
  record supplies, a value is present exactly when the answering record
  supplied one this module could parse and retain, and the field is empty
  otherwise, rendered as the previous point says. What an empty field implies
  about the paper — whether it was published, say — is a bibliographic
  question this converter does not answer; the arxiv-lookup skill is where
  that belongs. See ``references/output-format.md``.
- **The wait for the lookup is bounded.** Metadata is secondary to the
  Markdown, so ``fetch_metadata`` stops waiting after a deadline and reports
  ``unavailable`` rather than holding the conversion. Nothing cancels the
  request itself; the wait is what ends.

Responsibility boundary: the DOI reported here is whatever the answering record
carries (passive transcription) — ``arxiv:doi`` on arXiv's feed, the
``IsVersionOf`` identifiers on DataCite's registration. Resolving a DOI neither
record carries belongs to the arxiv-lookup skill, not here.
"""

from __future__ import annotations

import argparse
import dataclasses
import html
import html.entities
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

# arXiv's own Atom API, the source asked first. It answers out of the system the
# source and PDF downloads come from, so the revision it reports is the revision
# those downloads serve.
_ARXIV_API_URL = "https://export.arxiv.org/api/query"

# Sent on every request. arXiv asks API clients to identify themselves, and a
# request carrying urllib's default agent is the first thing a public API
# throttles — which is the failure this module exists to survive.
_USER_AGENT = "arxiv-doc-builder (+https://github.com/ultimatile/arxiv-skills)"

# The Atom feed's namespaces. arXiv's extension carries primary_category, doi
# and journal_ref; everything else is plain Atom.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# DataCite's REST endpoint for one DOI, the fallback source. arXiv registers
# every paper under the 10.48550 prefix, and DataCite matches the suffix
# case-insensitively.
_DATACITE_URL = "https://api.datacite.org/dois/10.48550/arxiv."

# Default upper bound, in seconds, on how long ``fetch_metadata`` waits for the
# lookup — both attempts together.
METADATA_DEADLINE_SECONDS = 5.0

# The share of the deadline that the arXiv attempt may spend before the
# DataCite attempt gets the rest of it. The two differ in shape rather than in
# speed: over 31 measured lookups arXiv answered with a median of 0.31 s, and
# the few that stalled answered in 0.04 s to 0.14 s when asked again, so those
# stalls are transient and a wider share would not catch them. DataCite took
# 1.10 s to 1.19 s every time. An even split therefore cuts off no healthy
# arXiv response and still leaves the fallback well over the time it needs. At
# the default deadline the arXiv attempt may draw 2.5 s and the fallback gets
# whatever is left, so about the other 2.5 s. That floor is what matters: the
# fallback's shortest budget comes when the arXiv attempt spent its whole share,
# and a share it could spend whole is what keeps the fallback reachable at all.
_ARXIV_DEADLINE_SHARE = 0.5

# The ``metadata_status`` frontmatter vocabulary. Anything that keeps a usable
# record from being read gives ``unavailable``, and the warning says what did.
METADATA_OK = "ok"
METADATA_UNAVAILABLE = "unavailable"
METADATA_NOT_REQUESTED = "not_requested"

METADATA_STATUSES = (METADATA_OK, METADATA_UNAVAILABLE, METADATA_NOT_REQUESTED)

# Which source supplied the record. ``fetch_paper`` reads this to decide
# whether a recorded revision may outrank the one the record names: only the
# fallback's registrations trail what arXiv serves, so the rule applies there
# and nowhere else. The document does not carry the value.
METADATA_SOURCE_ARXIV = "arxiv"
METADATA_SOURCE_DATACITE = "datacite"

METADATA_SOURCES = (METADATA_SOURCE_ARXIV, METADATA_SOURCE_DATACITE)

# What a fetch can report. ``not_requested`` is a frontmatter token for a
# document nobody asked for a record about, and no fetch produces it.
_FETCH_STATUSES = (METADATA_OK, METADATA_UNAVAILABLE)

# A validated arXiv id ends in ``v<N>`` exactly when it names a revision.
_VERSION_SUFFIX = re.compile(r"v(\d+)\Z")

# A legacy id may name a subject class ("math.GT/0309136"). arXiv answers such
# an id only under the archive alone ("math/0309136"), and registers the
# paper's DOI under that form too, so both requests drop the subject class.
_SUBJECT_CLASS = re.compile(r"^([a-z]+(?:-[a-z]+)?)\.[A-Za-z]+(?:-[A-Za-z]+)*/")

# An entity reference with its terminating semicolon: named, decimal or hex.
_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);")

# The revision a DataCite date entry describes, read off the front of its
# ``dateInformation`` label.
_REVISION_LABEL = re.compile(r"v(\d+)")

# The date types that list a revision. A withdrawal is listed as ``Withdrawn``
# rather than ``Submitted``, and it is still the paper's latest revision — the
# one arXiv's own record names — so both types count towards the latest.
_REVISION_DATE_TYPES = ("Submitted", "Withdrawn")

# The leading calendar date of a DataCite date value. DataCite also carries
# year-only and year-month values, which have none.
_CALENDAR_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# DataCite writes an arXiv subject as "Human Name (code)".
_SUBJECT_CODE = re.compile(r"\(([^()]+)\)\s*$")


@dataclass
class ArxivMetadata:
    """The subset of a paper's metadata record that the frontmatter transcribes.

    Every field is optional, and a ``None`` means only that no value was
    retained for it — the answering record supplied none, or supplied one this
    module could not parse. Nothing further follows from a null, here or in the
    document.

    The PDF path also builds this type from a PDF's own title and author when no
    record backs the document at all. Which kind of instance this is shows in
    ``metadata_status``, not here.
    """

    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    version: Optional[str] = None
    published: Optional[str] = None
    primary_category: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    doi: Optional[str] = None
    journal: Optional[str] = None
    abstract: Optional[str] = None
    # Which record this was read from, one of ``METADATA_SOURCES``. ``None``
    # when no record backs the instance, as for the one the PDF path builds
    # from a PDF's own title. Appended last so the field order the other nine
    # have keeps working. ``fetch_paper`` branches on it, reading it through the
    # handoff file when ``convert_paper`` started it; the frontmatter does not
    # carry it.
    source: Optional[str] = None

    def __post_init__(self) -> None:
        if self.source is not None and self.source not in METADATA_SOURCES:
            raise ValueError(f"source {self.source!r} is not one of {METADATA_SOURCES}")


@dataclass(frozen=True)
class MetadataFetch:
    """The outcome of one metadata lookup.

    Keeps the reason a lookup failed, which a bare ``None`` return could not.
    The reason goes to the user. The document gets ``status``.

    ``__post_init__`` accepts only what a fetch can report, meaning ``ok`` with
    a record or ``unavailable`` with a cause.
    """

    status: str
    metadata: Optional[ArxivMetadata] = None
    error: Optional[str] = None

    @property
    def failure_cause(self) -> str:
        """Why no usable record was read. Defined only for a non-``ok`` outcome."""
        if self.error is None:
            raise ValueError("an ok outcome has no failure cause")
        return self.error

    def __post_init__(self) -> None:
        if self.status not in _FETCH_STATUSES:
            raise ValueError(
                f"{self.status!r} is not a fetch outcome. "
                f"Expected one of {_FETCH_STATUSES}"
            )
        if (self.status == METADATA_OK) != (self.metadata is not None):
            raise ValueError(
                f"status {self.status!r} disagrees with metadata="
                f"{'present' if self.metadata is not None else 'absent'}"
            )
        if self.status == METADATA_OK and self.error is not None:
            raise ValueError(f"an ok outcome carries no cause, got {self.error!r}")
        if self.status != METADATA_OK and not (self.error or "").strip():
            # Checked for content, not against None. The cause reaches the user
            # verbatim, and a blank one prints a warning saying nothing.
            raise ValueError(
                f"status {self.status!r} needs a cause, got {self.error!r}"
            )


def _unavailable(cause: str) -> MetadataFetch:
    return MetadataFetch(METADATA_UNAVAILABLE, error=cause)


def _cause(exc: BaseException) -> str:
    """An exception as the cause text a failed outcome carries."""
    return f"{type(exc).__name__}: {exc}"


def _request(url: str) -> urllib.request.Request:
    """``url`` as a request that names this client."""
    return urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})


def _is_yaml_printable(codepoint: int) -> bool:
    """Whether a code point may appear raw in YAML text.

    Mirrors YAML's ``c-printable`` production (which a parser's reader enforces
    on the whole stream, before quoting is even considered). Code points outside
    this set — C0/C1 controls, DEL, surrogates, the U+FFFE/U+FFFF noncharacters —
    are either escaped (in a double-quoted scalar) or stripped (during
    normalization, for the literal block scalar that cannot escape).
    """
    return (
        codepoint in (0x09, 0x0A, 0x0D, 0x85)
        or 0x20 <= codepoint <= 0x7E
        or 0xA0 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _normalize(text: Optional[str]) -> Optional[str]:
    """Make record text safe and stable for the frontmatter.

    Two steps: drop characters YAML cannot carry (see ``_is_yaml_printable``),
    then collapse whitespace runs to single spaces. Stripping is required
    because the abstract is emitted as a literal block scalar, which — unlike a
    double-quoted scalar — cannot escape a stray control character, and both
    sources can deliver one: XML 1.0 permits raw C1 controls (0x80–0x9F) in
    arXiv's feed, and a JSON string carries any code point through a ``\\u``
    escape. Collapsing keeps every field single-line. Returns ``None`` for
    empty/whitespace-only input.
    """
    if text is None:
        return None
    printable = "".join(ch for ch in text if _is_yaml_printable(ord(ch)))
    collapsed = re.sub(r"\s+", " ", printable).strip()
    return collapsed or None


def _prose(text: Optional[str]) -> Optional[str]:
    """``_normalize`` for record prose, after decoding its HTML entities.

    DataCite stores the title, author names and abstract with entities such as
    ``&gt;`` left encoded. The Atom leg uses ``_normalize`` instead, since an
    XML parser has already decoded them.

    Only a complete reference, terminated by ``;``, is decoded: a numeric one
    always, as HTML decodes it, which replaces, remaps or drops some code
    points (``&#128;`` reads as ``€``), and a named one when it names a known
    entity.
    ``html.unescape`` alone also decodes HTML's legacy forms without the
    semicolon, turning literal text such as ``&notation`` into ``¬ation``.
    """
    if text is None:
        return None
    return _normalize(_ENTITY.sub(_decode_entity, text))


def _decode_entity(match: re.Match[str]) -> str:
    reference = match.group()
    if reference.startswith("&#") or reference[1:] in html.entities.html5:
        return html.unescape(reference)
    return reference


def _archive_form(arxiv_id: str) -> str:
    """``arxiv_id`` with a legacy subject class dropped, as both sources spell it.

    "math.GT/0309136v2" -> "math/0309136v2"; any other id is returned as is.
    Both lookups ask under this form, and ``version`` is spelled in it, so a
    revision recorded from either source compares equal to the other's.
    """
    return _SUBJECT_CLASS.sub(r"\1/", arxiv_id)


def split_version(arxiv_id: str) -> tuple[str, Optional[int]]:
    """Split a validated id into its bare form and its revision number, if any.

    "2409.03108v2"   -> ("2409.03108", 2)
    "hep-th/9711200" -> ("hep-th/9711200", None)
    """
    match = _VERSION_SUFFIX.search(arxiv_id)
    if match is None:
        return arxiv_id, None
    return arxiv_id[: match.start()], int(match.group(1))


def _dicts(value: object) -> list[dict[str, Any]]:
    """The dict entries of a JSON array, or nothing when ``value`` is not one.

    DataCite is an external producer, so a field can arrive null or with the
    wrong shape. Reading every array through this keeps ``_parse_record`` from
    raising on such a record.
    """
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _text(entry: dict[str, Any], key: str) -> Optional[str]:
    """``entry[key]`` when it is a string, else ``None``."""
    value = entry.get(key)
    return value if isinstance(value, str) else None


def _revisions(
    attributes: dict[str, Any], *, date_types: tuple[str, ...]
) -> list[tuple[int, Optional[str]]]:
    """The revisions DataCite lists under ``date_types``, each with its date.

    DataCite labels a revision ``v<N>``, sometimes with a note after it
    (``"v2; None"`` on a withdrawal), so the number is read off the front of
    the label rather than matched against the whole of it. A listed revision
    counts whether or not its entry carries a date: the date is the entry's
    text as given, which the caller still has to parse, or ``None`` when the
    entry has no text there.
    """
    revisions: list[tuple[int, Optional[str]]] = []
    for entry in _dicts(attributes.get("dates")):
        if entry.get("dateType") not in date_types:
            continue
        match = _REVISION_LABEL.match(_text(entry, "dateInformation") or "")
        if match:
            revisions.append((int(match.group(1)), _text(entry, "date")))
    return revisions


def _parse_record(bare_id: str, attributes: dict[str, Any]) -> ArxivMetadata:
    """Map DataCite's ``data.attributes`` onto the frontmatter fields.

    ``bare_id`` names no revision, since DataCite holds one record per paper
    and every field describes it: ``version`` is the latest revision the record
    lists, and the other fields follow that revision too, except ``published``,
    which is the first revision's date.
    """

    title = next(
        (
            text
            for text in (
                _prose(_text(entry, "title"))
                for entry in _dicts(attributes.get("titles"))
            )
            if text
        ),
        None,
    )

    authors: list[str] = []
    for creator in _dicts(attributes.get("creators")):
        given = (_text(creator, "givenName") or "").strip()
        family = (_text(creator, "familyName") or "").strip()
        # nameType is not consulted: DataCite tags some single-name people
        # Organizational, and some Personal creators carry no givenName. In both
        # shapes ``name`` holds the author as arXiv lists it.
        name = f"{given} {family}" if given and family else _text(creator, "name")
        normalized = _prose(name)
        if normalized:
            authors.append(normalized)

    latest = max(
        (n for n, _ in _revisions(attributes, date_types=_REVISION_DATE_TYPES)),
        default=None,
    )
    submitted = {
        n: date for n, date in _revisions(attributes, date_types=("Submitted",)) if date
    }
    version = f"{bare_id}v{latest}" if latest is not None else None

    first_date = _CALENDAR_DATE.match(submitted.get(1) or "")
    published = first_date.group() if first_date else None

    categories: list[str] = []
    for subject in _dicts(attributes.get("subjects")):
        if subject.get("subjectScheme") != "arXiv":
            continue
        match = _SUBJECT_CODE.search(_text(subject, "subject") or "")
        code = _normalize(match.group(1)) if match else None
        if code:
            categories.append(code)

    dois = [
        doi
        for doi in (
            _normalize(_text(related, "relatedIdentifier"))
            for related in _dicts(attributes.get("relatedIdentifiers"))
            if related.get("relationType") == "IsVersionOf"
            and related.get("relatedIdentifierType") == "DOI"
        )
        if doi
    ]

    abstract = next(
        (
            text
            for text in (
                _prose(_text(entry, "description"))
                for entry in _dicts(attributes.get("descriptions"))
                if entry.get("descriptionType") == "Abstract"
            )
            if text
        ),
        None,
    )

    return ArxivMetadata(
        title=title,
        authors=authors,
        version=version,
        published=published,
        primary_category=categories[0] if categories else None,
        categories=categories,
        doi=" ".join(dois) or None,
        abstract=abstract,
        source=METADATA_SOURCE_DATACITE,
    )


def _atom_text(entry: ET.Element, path: str) -> Optional[str]:
    """The text of the first matching child element, or ``None``."""
    el = entry.find(path, _NS)
    return el.text if el is not None else None


def parse_version_from_id(id_url: Optional[str]) -> Optional[str]:
    """Extract the full versioned arXiv id from an Atom ``<id>`` URL.

    Returns the path tail *including* the version suffix, which is what the
    version-drift sidecar persists, so ``fetch_paper`` can compare the two
    directly. Returns ``None`` when no tail is present.

        <id>http://arxiv.org/abs/2409.03108v2</id>     -> "2409.03108v2"
        <id>http://arxiv.org/abs/hep-th/9901001v3</id> -> "hep-th/9901001v3"
    """
    if not id_url:
        return None
    try:
        path = urllib.parse.urlparse(id_url).path
    except ValueError:
        # A malformed authority (unclosed IPv6 bracket) raises here. Fall
        # through to the tail split, which needs no parsed path.
        path = ""
    if path.startswith("/abs/"):
        return path[len("/abs/") :] or None
    return id_url.rsplit("/", 1)[-1] or None


def _is_error_entry(entry: ET.Element) -> bool:
    """Whether the entry is arXiv's error report instead of a paper record.

    A malformed id does not give an empty feed. arXiv answers with one entry
    titled ``Error`` whose ``<id>`` points under ``/api/errors``, and whose
    author and summary read like a record. The path is what this checks.
    """
    try:
        path = urllib.parse.urlparse(_atom_text(entry, "atom:id") or "").path
    except ValueError:
        return False
    return path.startswith("/api/errors")


def _parse_entry(entry: ET.Element) -> ArxivMetadata:
    """Map one Atom entry onto the frontmatter fields.

    The text goes through ``_normalize`` rather than ``_prose``: an XML parser
    has already decoded the entities, and decoding a second time would turn a
    title that spells "&gt;" literally into ">".
    """
    primary = entry.find("arxiv:primary_category", _NS)
    published = _CALENDAR_DATE.match(_atom_text(entry, "atom:published") or "")
    return ArxivMetadata(
        title=_normalize(_atom_text(entry, "atom:title")),
        authors=[
            name
            for name in (
                _normalize(n.text) for n in entry.findall("atom:author/atom:name", _NS)
            )
            if name
        ],
        version=parse_version_from_id(_atom_text(entry, "atom:id")),
        published=published.group() if published else None,
        primary_category=primary.get("term") if primary is not None else None,
        categories=[
            term
            for term in (c.get("term") for c in entry.findall("atom:category", _NS))
            if term
        ],
        doi=_normalize(_atom_text(entry, "arxiv:doi")),
        journal=_normalize(_atom_text(entry, "arxiv:journal_ref")),
        abstract=_normalize(_atom_text(entry, "atom:summary")),
        source=METADATA_SOURCE_ARXIV,
    )


def _identity_cause(version: Optional[str], query: str) -> Optional[str]:
    """Why an entry whose id reads ``version`` does not describe ``query``.

    ``None`` when it does. ``version`` is what ``parse_version_from_id`` reads
    off the entry's ``<id>``, and nothing else of the entry is consulted.

    A feed naming another paper parses exactly like one naming this paper, so
    the entry has to identify itself before its fields are read. Four things
    are required: an entry id whose tail parses, that tail naming a revision
    (``v<N>``), the bare id equalling the one queried, and — when the query
    named a revision — that revision.

    The caller turns a cause into ``unavailable`` so the fallback runs.
    Discarding only ``version`` would not do: the record would still be read as
    ``ok``, which is the status the chain branches on, and the other paper's
    title, authors and DOI would reach the document.

    ``query`` is the id as requested, already stripped of any subject class,
    which is the form arXiv spells an entry id in.
    """
    if version is None:
        return "arXiv's entry carries no id to identify the paper by"
    bare_entry, revision = split_version(version)
    if revision is None:
        return f"arXiv's entry id names no revision: {version}"
    bare_query, requested = split_version(query)
    if bare_entry != bare_query:
        return f"arXiv answered with a record for {bare_entry}, not {bare_query}"
    if requested is not None and revision != requested:
        return f"arXiv answered with {version}, not the requested {query}"
    return None


def _http_cause(source: str, code: int) -> str:
    """What an HTTP failure from ``source`` says, worded alike for both sources."""
    if code == 429:
        return f"{source} rate-limited the request (HTTP 429)"
    if 500 <= code <= 599:
        return f"{source} server error (HTTP {code})"
    return f"HTTP {code}"


def _get(
    url: str, timeout: float, http_cause: Callable[[urllib.error.HTTPError], str]
) -> Union[bytes, MetadataFetch]:
    """The body ``url`` answers with, or ``unavailable`` saying why there is none.

    Classifies the failures urlopen and the read are documented to raise: an
    HTTP status, a URLError and an OSError. ``http_cause`` words an HTTP
    failure for its source, and may read the error response's body to do so.
    Anything else, such as ``http.client.IncompleteRead`` from a body cut
    short, propagates to ``_bounded``, which reports it as ``unavailable``.
    """
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        # HTTPError subclasses URLError, so it must be caught first. It is also
        # an open response holding a socket, which urlopen raised before any
        # ``with`` could bind it.
        try:
            return _unavailable(http_cause(exc))
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        return _unavailable(f"URLError: {exc.reason}")
    except OSError as exc:
        return _unavailable(_cause(exc))


def _arxiv_error_cause(exc: urllib.error.HTTPError) -> str:
    """What an arXiv HTTP failure says, preferring its error entry.

    A rejected id comes back as HTTP 400 whose body is a feed holding one
    error entry, and that entry's summary names what was wrong with the id,
    which the status code alone does not.
    """
    try:
        entry = ET.parse(exc).find(".//atom:entry", _NS)
    except Exception:
        entry = None
    if entry is not None and _is_error_entry(entry):
        summary = _normalize(_atom_text(entry, "atom:summary"))
        if summary:
            return f"arXiv rejected the id: {summary}"
    return _http_cause("arXiv", exc.code)


def _lookup_arxiv(arxiv_id: str, timeout: float) -> MetadataFetch:
    """One request to arXiv's Atom API and the classification of its outcome.

    A legacy id loses its subject class first. arXiv answers such an id only
    under the archive alone and returns an empty feed for the other spelling,
    which would send every one of those papers to the fallback.
    """
    query = _archive_form(arxiv_id)
    url = _ARXIV_API_URL + "?" + urllib.parse.urlencode({"id_list": query})
    raw = _get(url, timeout, _arxiv_error_cause)
    if isinstance(raw, MetadataFetch):
        return raw
    try:
        feed = ET.fromstring(raw)
    except ET.ParseError as exc:
        return _unavailable(f"arXiv returned malformed XML: {exc}")

    entry = feed.find(".//atom:entry", _NS)
    if entry is None:
        return _unavailable("arXiv returned no record for this id")
    if _is_error_entry(entry):
        return _unavailable(
            _normalize(_atom_text(entry, "atom:summary"))
            or "arXiv reported an error for this id"
        )
    mismatch = _identity_cause(
        parse_version_from_id(_atom_text(entry, "atom:id")), query
    )
    if mismatch is not None:
        return _unavailable(mismatch)
    return MetadataFetch(METADATA_OK, metadata=_parse_entry(entry))


def _lookup_datacite(arxiv_id: str, timeout: float) -> MetadataFetch:
    """One request to DataCite and the classification of its outcome.

    Returns ``unavailable`` with a cause for every failure it anticipates. An
    unanticipated exception still propagates, and ``_bounded``, which runs this
    leg, turns it into ``unavailable`` too.
    """
    bare_id, requested = split_version(arxiv_id)
    doi_id = _archive_form(bare_id)
    url = _DATACITE_URL + urllib.parse.quote(doi_id, safe="/")

    def http_cause(exc: urllib.error.HTTPError) -> str:
        if exc.code == 404:
            # ``doi_id`` is the id as the DOI spells it. For a legacy id naming
            # a subject class that is the archive alone, and so not
            # ``bare_id``; for every other id the two coincide.
            return f"DataCite has no record for 10.48550/arXiv.{doi_id} (HTTP 404)"
        return _http_cause("DataCite", exc.code)

    raw = _get(url, timeout, http_cause)
    if isinstance(raw, MetadataFetch):
        return raw

    try:
        document = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        # Covers both JSONDecodeError and UnicodeDecodeError.
        return _unavailable(f"DataCite returned malformed JSON: {exc}")

    data = document.get("data") if isinstance(document, dict) else None
    attributes = data.get("attributes") if isinstance(data, dict) else None
    if not isinstance(attributes, dict):
        return _unavailable("DataCite response has no data.attributes")
    # A record for another paper parses exactly like one for this paper, so it
    # has to name the DOI asked for before its fields are read, as an Atom
    # entry has to on the arXiv leg. DataCite spells the DOI in lower case.
    expected = f"10.48550/arxiv.{doi_id}".lower()
    named = data.get("id") if isinstance(data, dict) else None
    if not isinstance(named, str) or named.lower() != expected:
        return _unavailable(
            f"DataCite answered with a record for {named!r}, not {expected}"
        )

    # Parsed under the id arXiv itself uses — the archive alone, without the
    # subject class — so both sources spell ``version`` the same way. Two
    # spellings would read as two papers at the version-drift check, which
    # deletes the cached source and downloads it again on every swing.
    record = _parse_record(doi_id, attributes)
    if requested is not None:
        _, latest = split_version(record.version or "")
        if latest is not None and requested > latest:
            return _unavailable(
                f"{arxiv_id} is later than v{latest}, the latest revision "
                f"DataCite lists for {bare_id}"
            )
        # A requested revision is recorded as such; every other field still
        # describes the one record DataCite holds.
        record = dataclasses.replace(record, version=f"{doi_id}v{requested}")
    return MetadataFetch(METADATA_OK, metadata=record)


def _bounded(
    call: Callable[[], MetadataFetch], budget: float, what: str
) -> MetadataFetch:
    """``call``'s outcome, or ``unavailable`` once ``budget`` seconds have passed.

    ``urlopen``'s own ``timeout`` bounds each socket operation rather than the
    request: a response that trickles in can outlast it many times over, and
    host resolution runs outside it entirely. Only a thread the caller stops
    waiting for bounds wall time, so that is what this does — the wait ends,
    while the request itself runs on. Nothing can cancel it: with the
    connection closed from another thread, a blocked read was measured
    returning 59 s later, on its own socket timeout. The thread is a daemon, so
    an abandoned request cannot hold the process open, and every failure of
    ``call`` or its thread — an exception it raises, a thread that cannot
    start, one that ends without a result — comes back as ``unavailable``
    rather than propagating. An interrupt of the caller itself, such as a
    KeyboardInterrupt while it waits, still propagates.
    """
    outcome: list[MetadataFetch] = []

    def run() -> None:
        try:
            outcome.append(call())
        except Exception as exc:
            outcome.append(_unavailable(_cause(exc)))

    try:
        worker = threading.Thread(
            target=run, name=f"arxiv-metadata-{what}", daemon=True
        )
        worker.start()
    except Exception as exc:
        return _unavailable(_cause(exc))
    worker.join(budget)
    # Read the thread's state before the outcome. A result the worker appends
    # after the join timed out but before this read is still returned below,
    # since the outcome is checked first.
    finished = not worker.is_alive()
    if outcome:
        return outcome[0]
    if not finished:
        return _unavailable(f"{what} exceeded the {budget:g} s budget")
    # The worker ended without appending, which means an exception escaped
    # run(): a BaseException, or an exception raised inside its handler.
    return _unavailable(f"{what} ended without a result")


def _lookup(arxiv_id: str, deadline: float) -> MetadataFetch:
    """arXiv's record, or DataCite's when arXiv does not supply one.

    arXiv is asked first because its record and the downloaded files come from
    the same system: the revision it reports is the revision ``fetch_paper``
    then downloads, and it carries a journal reference, which DataCite's
    registration does not. DataCite answers when arXiv cannot — a rate limit,
    an outage, a malformed feed — which is what keeps a run that would
    otherwise record nothing supplied with a record.

    Each attempt is bounded in wall time, and the two together spend about
    ``deadline`` at most, the time to start and join each thread aside. The
    arXiv attempt may take ``_ARXIV_DEADLINE_SHARE`` of it, which leaves the
    fallback time to answer, and the DataCite attempt what is left. When both
    fail, the cause names what each of them said.
    """
    started = time.monotonic()
    share = deadline * _ARXIV_DEADLINE_SHARE
    # Bounded in wall time, not just per socket operation: an arXiv that
    # trickles its response — the shape a rate-limited service often takes —
    # would otherwise spend the whole deadline and leave the fallback, which
    # exists for exactly that case, unasked. The helper also absorbs whatever
    # the leg does not classify, so an ``http.client`` exception cannot take
    # the fallback with it either.
    primary = _bounded(
        lambda: _lookup_arxiv(arxiv_id, share), share, "the arXiv lookup"
    )
    if primary.status == METADATA_OK:
        return primary

    remaining = deadline - (time.monotonic() - started)
    if remaining <= 0:
        return _unavailable(
            f"arXiv: {primary.failure_cause}; no time left to ask DataCite"
        )
    # Bounded and guarded like the arXiv leg, and for the same reasons. An
    # exception escaping here would report itself alone, dropping what arXiv
    # said — the one thing a two-source lookup exists to tell the user.
    fallback = _bounded(
        lambda: _lookup_datacite(arxiv_id, remaining), remaining, "the DataCite lookup"
    )
    if fallback.status == METADATA_OK:
        return fallback
    return _unavailable(
        f"arXiv: {primary.failure_cause}; DataCite: {fallback.failure_cause}"
    )


def fetch_metadata(
    arxiv_id: str, *, deadline: float = METADATA_DEADLINE_SECONDS
) -> MetadataFetch:
    """Look up the metadata record for ``arxiv_id``, giving up after ``deadline``.

    Every failure of the lookup lands in the returned ``MetadataFetch.error``
    instead of propagating — an unanticipated ``Exception`` in a request, a
    worker thread that cannot start, and one that ends without a result
    included — letting callers fall back to a local title source (LaTeX
    ``\\title``, PDF embedded metadata) and still report the cause. A
    ``deadline`` that is not a positive number of seconds at most
    ``threading.TIMEOUT_MAX`` is a caller error: it raises ``ValueError``, or
    ``TypeError`` when it is not an ``int`` or ``float`` (``bool`` excluded).
    Both are raised before the lookup starts.

    ``deadline`` bounds how long this call waits for the lookup. ``urlopen``'s own
    ``timeout`` bounds each socket operation rather than the request, a response
    that trickles in can outlast it many times over, and host resolution runs
    outside it, so each request runs in a daemon thread that this call stops
    waiting for once that request's share of ``deadline`` is spent. Each leg
    passes its share as that socket timeout too, so a request that stalls
    outright still ends on its own; one that keeps trickling can outlive the
    call, and being a daemon keeps it from holding the process open.

    The record comes from arXiv's own API, or from DataCite when arXiv does not
    answer with one; ``ArxivMetadata.source`` says which, and ``_lookup``
    explains the order.

    Assumes ``arxiv_id`` is already validated to canonical form. On the
    DataCite leg an id that names a revision is looked up by its bare form,
    since DataCite holds one record per paper, and a legacy id that names a
    subject class by its archive alone, the form arXiv registers the DOI under.
    """
    # Checked before the worker starts. Decimal and Fraction pass the range
    # check below but make worker.join raise once the request is running.
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        raise TypeError(
            f"deadline must be an int or float, got {type(deadline).__name__}"
        )
    # threading.TIMEOUT_MAX is the largest value join and the socket timeout
    # both accept; above it they raise OverflowError. The chained comparison
    # also rejects NaN and infinity, and compares a huge int without
    # converting it to float.
    if not 0 < deadline <= threading.TIMEOUT_MAX:
        raise ValueError(
            "deadline must be a positive number of seconds no greater than "
            f"threading.TIMEOUT_MAX ({threading.TIMEOUT_MAX:g}), got {deadline!r}"
        )

    # Each leg already runs bounded and turns its own failures into
    # ``unavailable``; this catches what the chain's own code might raise.
    try:
        return _lookup(arxiv_id, deadline)
    except Exception as exc:
        return _unavailable(_cause(exc))


# The handoff carries every field of the record: the lists are the fields
# that default to an empty list, and every other field is text or null.
_HANDOFF_LISTS = tuple(
    f.name for f in dataclasses.fields(ArxivMetadata) if f.default_factory is list
)
_HANDOFF_SCALARS = tuple(
    f.name for f in dataclasses.fields(ArxivMetadata) if f.name not in _HANDOFF_LISTS
)


def write_metadata_handoff(path: Path, arxiv_id: str, fetch: MetadataFetch) -> None:
    """Write one lookup's outcome where a child process can read it back.

    ``convert_paper`` looks metadata up once and hands the outcome to each step
    it starts, so a failed lookup crosses the process boundary with its cause.
    """
    payload = {"arxiv_id": arxiv_id, "fetch": dataclasses.asdict(fetch)}
    # ASCII-only JSON: a lone surrogate from an external record then travels as
    # a \u escape instead of failing the UTF-8 write.
    path.write_text(json.dumps(payload), encoding="utf-8")


def _handoff_metadata(value: object) -> Optional[ArxivMetadata]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("metadata is neither null nor an object")
    expected = set(_HANDOFF_SCALARS) | set(_HANDOFF_LISTS)
    if set(value) != expected:
        raise ValueError(
            f"metadata keys {sorted(value)} differ from {sorted(expected)}"
        )
    for key in _HANDOFF_SCALARS:
        if value[key] is not None and not isinstance(value[key], str):
            raise ValueError(f"metadata field {key!r} is not a string or null")
    for key in _HANDOFF_LISTS:
        items = value[key]
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise ValueError(f"metadata field {key!r} is not a list of strings")
    # The constructor rejects a ``source`` outside the vocabulary, and the
    # ValueError reaches the caller like any other field of the wrong shape.
    return ArxivMetadata(**value)


def _read_handoff(path: Path, arxiv_id: str) -> MetadataFetch:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"arxiv_id", "fetch"}:
        raise ValueError("top level is not an object with exactly arxiv_id and fetch")
    if payload["arxiv_id"] != arxiv_id:
        raise ValueError(f"it describes {payload['arxiv_id']!r}, not {arxiv_id!r}")
    fetch = payload["fetch"]
    if not isinstance(fetch, dict) or set(fetch) != {"status", "metadata", "error"}:
        raise ValueError(
            "fetch is not an object with exactly status, metadata and error"
        )
    if not isinstance(fetch["status"], str):
        raise ValueError("status is not a string")
    if fetch["error"] is not None and not isinstance(fetch["error"], str):
        raise ValueError("error is not a string or null")
    # MetadataFetch.__post_init__ checks that status, metadata and error agree.
    outcome = MetadataFetch(
        fetch["status"],
        metadata=_handoff_metadata(fetch["metadata"]),
        error=fetch["error"],
    )
    # The last shape the field checks above let through: an ``ok`` outcome
    # whose record names no source. Both legs name one, so such a handoff did
    # not come from this module's lookup, and ``fetch_paper`` would read the
    # absent source as "not the fallback" and apply the wrong revision rule.
    if outcome.status == METADATA_OK and outcome.metadata.source is None:  # type: ignore[union-attr]
        raise ValueError("an ok outcome names no source")
    return outcome


def read_metadata_handoff(path: Path, arxiv_id: str) -> MetadataFetch:
    """Read back what ``write_metadata_handoff`` wrote, raising no ``Exception``.

    A handoff that cannot be trusted — missing or unreadable, not the JSON shape
    the writer produces, a field of the wrong type, an outcome
    ``MetadataFetch`` rejects, or one written for another id — yields
    ``unavailable`` with the reason, as a failed lookup would.
    """
    try:
        return _read_handoff(Path(path), arxiv_id)
    except Exception as exc:
        return _unavailable(f"metadata handoff unreadable: {_cause(exc)}")


def add_metadata_handoff_option(parser: argparse.ArgumentParser) -> None:
    """Add the hidden ``--metadata-handoff`` option a step started by ``convert_paper`` takes.

    The option carries ``convert_paper``'s lookup to its steps and is no setting
    for a user, so ``--help`` leaves it out. ``Path`` cannot reject a
    command-line string, so no value argparse hands to it makes argparse exit 2,
    the code ``convert_paper`` reserves for an ambiguous main ``.tex``. The
    option still exits 2 when nothing follows it, or when what follows starts
    with ``-`` and argparse reads it as another option. ``convert_paper``
    produces neither, since it always passes an absolute path.
    """
    parser.add_argument("--metadata-handoff", type=Path, help=argparse.SUPPRESS)


def resolve_metadata(
    arxiv_id: str,
    handoff: Optional[Path],
    lookup: Callable[[str], MetadataFetch],
) -> MetadataFetch:
    """The outcome handed over in ``handoff``, or a fresh ``lookup`` without one.

    ``lookup`` is the calling module's own lookup function, passed in so a test
    that replaces that module's name still intercepts it.
    """
    if handoff is not None:
        return read_metadata_handoff(handoff, arxiv_id)
    return lookup(arxiv_id)


def format_unavailable_warning(arxiv_id: str, *, cause: str) -> str:
    """Compose the warning a conversion path shows when no usable record was read.

    Both conversion paths write null record fields into a document and say the
    same thing about them, so the whole message lives here. A step that writes
    no such fields composes its own.

    ``cause`` is the captured ``MetadataFetch.error``. Returning the text
    instead of printing it leaves the destination to the caller.
    """
    return (
        f"WARNING: no usable metadata record for {arxiv_id}: {cause}\n"
        "  The frontmatter fields a record supplies are left null. Those nulls "
        "mean the value is unknown, since no record was read.\n"
        "  The document's frontmatter records "
        f"metadata_status: {METADATA_UNAVAILABLE}."
    )


def _yaml_dq(value: str) -> str:
    """Render ``value`` as a YAML double-quoted scalar.

    Total over arbitrary strings: backslash and double-quote are escaped, the
    line-breaking whitespace is escaped (``\\n`` / ``\\t`` / ``\\r``) to keep the
    scalar single-line, and any code point YAML cannot carry raw (see
    ``_is_yaml_printable``) is escaped as ``\\xNN`` / ``\\uNNNN``. The text
    fields are already control-stripped by ``_normalize``; the control escaping
    here is a backstop for the structured fields (id, version, dates) that skip
    normalization, so the emitter stays valid for any input.
    """
    out: list[str] = []
    for ch in value:
        codepoint = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif _is_yaml_printable(codepoint):
            out.append(ch)
        elif codepoint <= 0xFF:
            out.append(f"\\x{codepoint:02x}")
        else:
            out.append(f"\\u{codepoint:04x}")
    return '"' + "".join(out) + '"'


def _scalar_line(key: str, value: Optional[str]) -> str:
    """One ``key: "value"`` line, or a bare ``key:`` (YAML null) when absent."""
    if value is None:
        return f"{key}:"
    return f"{key}: {_yaml_dq(value)}"


def _list_lines(key: str, items: list[str]) -> str:
    """A YAML block list, or ``key: []`` when empty."""
    if not items:
        return f"{key}: []"
    body = "\n".join(f"  - {_yaml_dq(item)}" for item in items)
    return f"{key}:\n{body}"


def _block_lines(key: str, value: Optional[str]) -> str:
    """A literal block scalar (``key: |-``), or a bare ``key:`` when absent.

    ``value`` must be ``_normalize``-d upstream: a literal block scalar cannot
    escape, so it relies on normalization having stripped YAML-forbidden
    characters and collapsed the text to a single line. The ``-`` chomping
    indicator drops the trailing newline, so the block ends cleanly before the
    closing fence.
    """
    if value is None:
        return f"{key}:"
    return f"{key}: |-\n  {value}"


def build_frontmatter(
    meta: Optional[ArxivMetadata],
    *,
    arxiv_id: Optional[str],
    source_type: str,
    conversion_date: str,
    metadata_status: str,
    fallback_title: Optional[str] = None,
) -> str:
    """Render the YAML frontmatter block for a converted paper.

    Every key is always present (a total schema) so a consumer can read
    provenance from a fixed location whichever conversion path produced the
    document.

    ``arxiv_id`` is optional. Manual PDF scripts invoke the converter without
    one, and it then renders as null with ``metadata_status`` ``not_requested``.

    Which of the two sources answered is not emitted. A consumer reads the
    fields a record supplied, and a null among them says only that no value was
    retained, so nothing it could branch on depends on the record's origin.

    ``metadata_status`` cannot be derived from ``meta`` here. The PDF path
    passes a record built from the PDF's own title when the lookup failed,
    which makes a non-``None`` ``meta`` compatible with every status. Both it
    and its agreement with ``arxiv_id`` are checked at entry, because the key
    exists to be branched on.
    """
    if metadata_status not in METADATA_STATUSES:
        raise ValueError(
            f"unknown metadata_status {metadata_status!r}. "
            f"Expected one of {METADATA_STATUSES}"
        )
    if (arxiv_id is None) != (metadata_status == METADATA_NOT_REQUESTED):
        raise ValueError(
            f"metadata_status {metadata_status!r} does not match "
            f"arxiv_id={'absent' if arxiv_id is None else 'present'}. "
            f"{METADATA_NOT_REQUESTED!r} is the only status a document with no "
            f"id can carry, and the only one a document with an id cannot"
        )
    m = meta or ArxivMetadata()
    # Normalize every emitted text scalar here, so the block is clean and valid
    # regardless of how the metadata was built — the PDF fallback path
    # constructs ArxivMetadata straight from raw PDF-embedded strings, which
    # never passed through the record-side normalization in _parse_record
    # (DataCite) or _parse_entry (arXiv).
    title = _normalize(m.title) or _normalize(fallback_title)
    author_names = [name for name in (_normalize(a) for a in m.authors) if name]
    authors = ", ".join(author_names) if author_names else None

    lines = [
        "---",
        _scalar_line("title", title),
        _scalar_line("authors", authors),
        _scalar_line("arxiv_id", arxiv_id),
        _scalar_line("version", m.version),
        _scalar_line("published", m.published),
        _scalar_line("primary_category", m.primary_category),
        _list_lines("categories", m.categories),
        _scalar_line("doi", m.doi),
        _scalar_line("journal", m.journal),
        _scalar_line("source_type", source_type),
        _scalar_line("metadata_status", metadata_status),
        _scalar_line("conversion_date", conversion_date),
        _block_lines("abstract", _normalize(m.abstract)),
        "---",
        "",
        "",
    ]
    return "\n".join(lines)
