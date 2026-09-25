#!/usr/bin/env python3
"""Fetch a paper's metadata record and render the document frontmatter.

Single source of truth for the YAML frontmatter prepended to a converted
paper by both conversion paths (``convert_latex.py`` and the PDF path through
``pdf_converter_lib.py``). The frontmatter is the provenance surface a
downstream consumer reads, so it must carry the same key set regardless of
which path produced it or whether the network was reachable.

The record comes from arXiv's Atom API, or from the DOI arXiv registers at
DataCite (``10.48550/arXiv.<id>``) when arXiv does not answer with one.
``ArxivMetadata.source`` says which; ``fetch_paper`` reads it, the document
does not carry it.

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
- **Record-supplied fields are transcribed, not interpreted.** ``published``,
  ``categories``, ``doi``, ``journal`` and ``abstract`` are present exactly
  when the answering record supplied a value this module could parse, and
  empty otherwise; what an empty field says about the paper is the
  arxiv-lookup skill's question. See ``references/output-format.md``.
- **The wait is bounded, not the request.** ``fetch_metadata`` stops waiting
  after a deadline and reports ``unavailable``; the request itself is not
  cancelled.
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

# Asked first: it is the system the downloads come from, so its revision matches.
_ARXIV_API_URL = "https://export.arxiv.org/api/query"

# arXiv asks API clients to identify themselves; urllib's default agent is
# the first a public API throttles.
_USER_AGENT = "arxiv-doc-builder (+https://github.com/ultimatile/arxiv-skills)"

# The Atom feed's namespaces. arXiv's extension carries primary_category, doi
# and journal_ref; everything else is plain Atom.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# DataCite's endpoint for an arXiv DOI (10.48550/arXiv.<id>; case-insensitive).
_DATACITE_URL = "https://api.datacite.org/dois/10.48550/arxiv."

# Seconds ``fetch_metadata`` waits for both attempts together, by default.
METADATA_DEADLINE_SECONDS = 5.0

# arXiv's share of the deadline; DataCite gets the rest. Over 31 measured
# lookups arXiv answered in 0.31 s (median) and its stalls did not recur when
# measured again, while DataCite took about 1.2 s, so an even split cuts off
# no healthy answer and, at the default deadline, leaves the fallback room
# even when arXiv spends its whole share.
_ARXIV_DEADLINE_SHARE = 0.5

# The frontmatter's ``metadata_status`` values.
METADATA_OK = "ok"
METADATA_UNAVAILABLE = "unavailable"
METADATA_NOT_REQUESTED = "not_requested"

METADATA_STATUSES = (METADATA_OK, METADATA_UNAVAILABLE, METADATA_NOT_REQUESTED)

# Which source answered. ``fetch_paper`` keeps a later recorded revision only
# when DataCite did, since only DataCite can trail what arXiv serves.
METADATA_SOURCE_ARXIV = "arxiv"
METADATA_SOURCE_DATACITE = "datacite"

METADATA_SOURCES = (METADATA_SOURCE_ARXIV, METADATA_SOURCE_DATACITE)

# What a fetch can report; no fetch produces ``not_requested``.
_FETCH_STATUSES = (METADATA_OK, METADATA_UNAVAILABLE)

# A validated arXiv id ends in ``v<N>`` exactly when it names a revision.
_VERSION_SUFFIX = re.compile(r"v(\d+)\Z")

# A legacy id's subject class ("math.GT/0309136"). Both sources know the paper
# only under the archive alone ("math/0309136").
_SUBJECT_CLASS = re.compile(r"^([a-z]+(?:-[a-z]+)?)\.[A-Za-z]+(?:-[A-Za-z]+)*/")

# An entity reference with its terminating semicolon: named, decimal or hex.
_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);")

# The revision at the front of a DataCite ``dateInformation`` label.
_REVISION_LABEL = re.compile(r"v(\d+)")

# Date types that list a revision. A withdrawal is still the latest revision.
_REVISION_DATE_TYPES = ("Submitted", "Withdrawn")

# A full date; DataCite also carries year-only and year-month values.
_CALENDAR_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# DataCite writes an arXiv subject as "Human Name (code)".
_SUBJECT_CODE = re.compile(r"\(([^()]+)\)\s*$")


@dataclass
class ArxivMetadata:
    """The fields of a metadata record that the frontmatter transcribes.

    ``None`` means only that no value was retained. The PDF path also builds
    one from a PDF's own title and author when no record was read.
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
    # One of ``METADATA_SOURCES``, or ``None`` when no record backs this.
    # Last, so the other fields keep their positions.
    source: Optional[str] = None

    def __post_init__(self) -> None:
        if self.source is not None and self.source not in METADATA_SOURCES:
            raise ValueError(f"source {self.source!r} is not one of {METADATA_SOURCES}")


@dataclass(frozen=True)
class MetadataFetch:
    """The outcome of one metadata lookup: ``ok`` with a record, or
    ``unavailable`` with the cause the user is shown."""

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
            # A blank cause would print a warning that says nothing.
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
    """Whether a code point may appear raw in YAML (its ``c-printable``)."""
    return (
        codepoint in (0x09, 0x0A, 0x0D, 0x85)
        or 0x20 <= codepoint <= 0x7E
        or 0xA0 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _normalize(text: Optional[str]) -> Optional[str]:
    """Record text with non-YAML characters dropped and whitespace collapsed.

    Dropping is needed because the abstract is a literal block scalar, which
    cannot escape, and both sources can deliver control characters. Returns
    ``None`` for empty or whitespace-only input.
    """
    if text is None:
        return None
    printable = "".join(ch for ch in text if _is_yaml_printable(ord(ch)))
    collapsed = re.sub(r"\s+", " ", printable).strip()
    return collapsed or None


def _prose(text: Optional[str]) -> Optional[str]:
    """``_normalize`` for DataCite prose, which keeps entities like ``&gt;``.

    Decodes only references ending in ``;``: numeric ones as HTML does
    (``&#128;`` reads as ``€``), named ones when the name is known.
    ``html.unescape`` alone would also turn literal ``&notation`` into
    ``¬ation``.
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
    """``arxiv_id`` without a legacy subject class, as both sources spell it.

    "math.GT/0309136v2" -> "math/0309136v2"; any other id is returned as is.
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
    """The dict entries of a JSON array, or ``[]`` when ``value`` is not one."""
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
    """The revisions DataCite lists under ``date_types``, with their raw dates.

    A label can carry a note after ``v<N>`` (``"v2; None"``). An entry without
    a date still lists its revision, with ``None`` as the date.
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

    DataCite holds one record per paper, so ``version`` is the latest revision
    it lists and ``published`` the first revision's date.
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
        # Not by nameType: some single-name people are tagged Organizational.
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
    """The versioned arXiv id at the end of an Atom ``<id>`` URL, or ``None``.

    <id>http://arxiv.org/abs/2409.03108v2</id>     -> "2409.03108v2"
    <id>http://arxiv.org/abs/hep-th/9901001v3</id> -> "hep-th/9901001v3"
    """
    if not id_url:
        return None
    try:
        path = urllib.parse.urlparse(id_url).path
    except ValueError:
        # An unclosed IPv6 bracket raises; the tail split below still works.
        path = ""
    if path.startswith("/abs/"):
        return path[len("/abs/") :] or None
    return id_url.rsplit("/", 1)[-1] or None


def _is_error_entry(entry: ET.Element) -> bool:
    """Whether the entry is arXiv's error report (its ``<id>`` is under
    ``/api/errors``), which otherwise reads like a record."""
    try:
        path = urllib.parse.urlparse(_atom_text(entry, "atom:id") or "").path
    except ValueError:
        return False
    return path.startswith("/api/errors")


def _parse_entry(entry: ET.Element) -> ArxivMetadata:
    """Map one Atom entry onto the frontmatter fields.

    ``_normalize``, not ``_prose``: the XML parser already decoded entities.
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
    """Why an entry whose ``<id>`` reads ``version`` is not ``query``'s record.

    ``None`` when it is: the id names a revision, the bare ids match, and so
    does the revision when ``query`` names one. Checked before the entry's
    other fields are read, since another paper's feed parses just the same.
    ``query`` has no subject class, as arXiv spells entry ids.
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
    """The body ``url`` answers with, or ``unavailable`` saying why not.

    ``http_cause`` words an HTTP error, and may read its body. Anything other
    than an HTTP, URL or OS error (``http.client.IncompleteRead``, say)
    propagates to ``_bounded``.
    """
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        # Before URLError, its base class. It holds an open socket, so close it.
        try:
            return _unavailable(http_cause(exc))
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        return _unavailable(f"URLError: {exc.reason}")
    except OSError as exc:
        return _unavailable(_cause(exc))


def _arxiv_error_cause(exc: urllib.error.HTTPError) -> str:
    """What an arXiv HTTP error says; a rejected id's 400 body explains why."""
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
    """One request to arXiv's Atom API, classified."""
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
    """One request to DataCite, classified. Unanticipated exceptions propagate
    to ``_bounded``."""
    bare_id, requested = split_version(arxiv_id)
    doi_id = _archive_form(bare_id)
    url = _DATACITE_URL + urllib.parse.quote(doi_id, safe="/")

    def http_cause(exc: urllib.error.HTTPError) -> str:
        if exc.code == 404:
            # ``doi_id``, not ``bare_id``: the DOI drops a subject class.
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
    # Another paper's record parses just the same, so check its DOI first.
    expected = f"10.48550/arxiv.{doi_id}".lower()
    named = data.get("id") if isinstance(data, dict) else None
    if not isinstance(named, str) or named.lower() != expected:
        return _unavailable(
            f"DataCite answered with a record for {named!r}, not {expected}"
        )

    # Under arXiv's spelling, so both sources' ``version`` compare equal.
    record = _parse_record(doi_id, attributes)
    if requested is not None:
        _, latest = split_version(record.version or "")
        if latest is not None and requested > latest:
            return _unavailable(
                f"{arxiv_id} is later than v{latest}, the latest revision "
                f"DataCite lists for {bare_id}"
            )
        record = dataclasses.replace(record, version=f"{doi_id}v{requested}")
    return MetadataFetch(METADATA_OK, metadata=record)


def _bounded(
    call: Callable[[], MetadataFetch], budget: float, what: str
) -> MetadataFetch:
    """``call``'s outcome, or ``unavailable`` once ``budget`` seconds pass.

    ``urlopen``'s timeout bounds each socket operation, not the request, so
    ``call`` runs in a daemon thread this stops waiting for; the request
    itself is not cancelled. Any failure of ``call`` or its thread comes back
    as ``unavailable``; an interrupt of the caller still propagates.
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
    # Read before the outcome, so a result appended just after the join wins.
    finished = not worker.is_alive()
    if outcome:
        return outcome[0]
    if not finished:
        return _unavailable(f"{what} exceeded the {budget:g} s budget")
    # An exception escaped run(): a BaseException, or one its handler raised.
    return _unavailable(f"{what} ended without a result")


def _lookup(arxiv_id: str, deadline: float) -> MetadataFetch:
    """arXiv's record, or DataCite's when arXiv does not supply one.

    arXiv gets ``_ARXIV_DEADLINE_SHARE`` of ``deadline`` and DataCite the rest.
    When both fail, the cause names what each said.
    """
    started = time.monotonic()
    share = deadline * _ARXIV_DEADLINE_SHARE
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
    """Look up the metadata record for ``arxiv_id``, waiting at most ``deadline`` s.

    A failed lookup is returned as ``unavailable`` with its cause, never
    raised (for an ``Exception``). A ``deadline`` that is not a positive
    ``int`` or ``float`` up to ``threading.TIMEOUT_MAX`` raises ``TypeError`` or
    ``ValueError`` before anything starts. ``arxiv_id`` must already be
    validated.
    """
    # Decimal and Fraction would pass the range check, then break join().
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        raise TypeError(
            f"deadline must be an int or float, got {type(deadline).__name__}"
        )
    # Also rejects NaN and infinity; above TIMEOUT_MAX join() overflows.
    if not 0 < deadline <= threading.TIMEOUT_MAX:
        raise ValueError(
            "deadline must be a positive number of seconds no greater than "
            f"threading.TIMEOUT_MAX ({threading.TIMEOUT_MAX:g}), got {deadline!r}"
        )

    try:
        return _lookup(arxiv_id, deadline)
    except Exception as exc:
        return _unavailable(_cause(exc))


# The handoff carries every record field: lists, and text-or-null scalars.
_HANDOFF_LISTS = tuple(
    f.name for f in dataclasses.fields(ArxivMetadata) if f.default_factory is list
)
_HANDOFF_SCALARS = tuple(
    f.name for f in dataclasses.fields(ArxivMetadata) if f.name not in _HANDOFF_LISTS
)


def write_metadata_handoff(path: Path, arxiv_id: str, fetch: MetadataFetch) -> None:
    """Write one lookup's outcome for a child process to read back.

    Refuses an ``ok`` outcome whose record names no source, which the reader
    would reject.
    """
    if fetch.status == METADATA_OK and fetch.metadata.source is None:  # type: ignore[union-attr]
        raise ValueError("an ok outcome names no source")
    payload = {"arxiv_id": arxiv_id, "fetch": dataclasses.asdict(fetch)}
    # ASCII-only, so a lone surrogate travels as \u rather than failing.
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
    # The constructor rejects an unknown ``source``.
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
    # Both lookups name a source, and ``fetch_paper`` branches on it.
    if outcome.status == METADATA_OK and outcome.metadata.source is None:  # type: ignore[union-attr]
        raise ValueError("an ok outcome names no source")
    return outcome


def read_metadata_handoff(path: Path, arxiv_id: str) -> MetadataFetch:
    """Read back what ``write_metadata_handoff`` wrote, raising no ``Exception``.

    A handoff that cannot be trusted yields ``unavailable`` with the reason.
    """
    try:
        return _read_handoff(Path(path), arxiv_id)
    except Exception as exc:
        return _unavailable(f"metadata handoff unreadable: {_cause(exc)}")


def add_metadata_handoff_option(parser: argparse.ArgumentParser) -> None:
    """Add the hidden ``--metadata-handoff`` option ``convert_paper`` passes.

    Not for users, so ``--help`` omits it. ``convert_paper`` passes an
    absolute path, so argparse never exits 2 on it, the code reserved for an
    ambiguous main ``.tex``.
    """
    parser.add_argument("--metadata-handoff", type=Path, help=argparse.SUPPRESS)


def resolve_metadata(
    arxiv_id: str,
    handoff: Optional[Path],
    lookup: Callable[[str], MetadataFetch],
) -> MetadataFetch:
    """The outcome handed over in ``handoff``, or a fresh ``lookup`` without one.

    ``lookup`` is passed in so a test that patches the caller's name catches it.
    """
    if handoff is not None:
        return read_metadata_handoff(handoff, arxiv_id)
    return lookup(arxiv_id)


def format_unavailable_warning(arxiv_id: str, *, cause: str) -> str:
    """The warning both conversion paths show when no usable record was read.

    ``cause`` is the ``MetadataFetch.error``.
    """
    return (
        f"WARNING: no usable metadata record for {arxiv_id}: {cause}\n"
        "  The frontmatter fields a record supplies are left null. Those nulls "
        "mean the value is unknown, since no record was read.\n"
        "  The document's frontmatter records "
        f"metadata_status: {METADATA_UNAVAILABLE}."
    )


def _yaml_dq(value: str) -> str:
    """Render any string as a YAML double-quoted scalar.

    Escapes backslash, double quote, ``\\n``, ``\\t``, ``\\r`` and every code
    point ``_is_yaml_printable`` rejects, so the result is valid YAML for any
    input, including fields that skip ``_normalize``.
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

    ``value`` must already be ``_normalize``-d: a literal block cannot escape.
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

    Every key is always present. ``arxiv_id`` is ``None`` only with
    ``metadata_status`` ``not_requested``; the status is passed in because the
    PDF path builds ``meta`` from the PDF itself when the lookup failed.
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
    # Again here: the PDF path builds ``m`` from raw PDF strings.
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
