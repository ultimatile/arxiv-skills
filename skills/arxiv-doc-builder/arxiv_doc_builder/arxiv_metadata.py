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
answered, and the frontmatter carries it as ``metadata_source``.

Design constraints:

- **Runtime is dependency-free.** The LaTeX path runs as a plain ``python3``
  subprocess with no third-party packages installed, so the frontmatter is
  hand-emitted rather than routed through PyYAML. A round-trip contract test
  (which *may* use PyYAML, a test-only dependency) pins the emitted text to
  valid, re-parseable YAML.
- **The schema is total.** ``build_frontmatter`` always emits every key, even
  when the lookup failed. Unknown values render as YAML null (a bare
  ``key:``), which a parser reads as ``None``.
- **A null is read together with ``metadata_status`` and ``metadata_source``.**
  Only under ``ok`` does a null confirm an absence, and only from the record
  ``metadata_source`` names: DataCite's registration carries no journal
  reference, so ``journal`` is null under ``datacite`` whatever the paper's
  publication history. Under the other status tokens no usable record was read
  at all, and the null reports ignorance. See ``references/output-format.md``.
- **The wait for the lookup is bounded.** Metadata is secondary to the
  Markdown, so ``fetch_metadata`` gives up after a deadline and reports
  ``unavailable`` rather than holding the conversion.

Responsibility boundary: the DOI reported here is whatever DataCite's record
carries (passive transcription). Resolving a DOI that record does not carry
belongs to the arxiv-lookup skill, not here.
"""

from __future__ import annotations

import argparse
import dataclasses
import html
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
from typing import Any, Callable, Optional

# arXiv's own Atom API, the source asked first. It answers out of the system the
# source and PDF downloads come from, so the revision it reports is the revision
# those downloads serve.
_ARXIV_API_URL = "https://export.arxiv.org/api/query"

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

# The share of that budget the arXiv attempt may spend before the DataCite
# attempt gets what is left. The two differ in shape: over 15 measured
# lookups arXiv answered in 0.04 s to 1.5 s except for one transient stall,
# while DataCite took 1.1 s to 1.4 s every time. An even split therefore cuts
# off no healthy arXiv response and still leaves the fallback well over the
# time it needs, which matters because the fallback runs exactly when the
# arXiv attempt spent its whole share.
_ARXIV_DEADLINE_SHARE = 0.5

# The ``metadata_status`` frontmatter vocabulary. Anything that keeps a usable
# record from being read gives ``unavailable``, and the warning says what did.
METADATA_OK = "ok"
METADATA_UNAVAILABLE = "unavailable"
METADATA_NOT_REQUESTED = "not_requested"

METADATA_STATUSES = (METADATA_OK, METADATA_UNAVAILABLE, METADATA_NOT_REQUESTED)

# Which source supplied the record, reported in the frontmatter as
# ``metadata_source``. The two records do not carry the same fields — only
# arXiv's has a journal reference — so a null under ``ok`` is read against the
# source that answered.
METADATA_SOURCE_ARXIV = "arxiv"
METADATA_SOURCE_DATACITE = "datacite"

METADATA_SOURCES = (METADATA_SOURCE_ARXIV, METADATA_SOURCE_DATACITE)

# What a fetch can report. ``not_requested`` is a frontmatter token for a
# document nobody asked for a record about, and no fetch produces it.
_FETCH_STATUSES = (METADATA_OK, METADATA_UNAVAILABLE)

# A validated arXiv id ends in ``v<N>`` exactly when it names a revision.
_VERSION_SUFFIX = re.compile(r"v(\d+)$")

# A legacy id may name a subject class ("math.GT/0309136"). arXiv registers the
# paper's DOI under the archive alone ("math/0309136"), and DataCite answers 404
# for the subject-class form.
_SUBJECT_CLASS = re.compile(r"^([a-z]+(?:-[a-z]+)?)\.[A-Za-z]+(?:-[A-Za-z]+)*/")

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


@dataclass(kw_only=True)
class ArxivMetadata:
    """The subset of a paper's metadata record that the frontmatter transcribes.

    Every field is optional. In an instance built from DataCite's record a
    ``None`` means the record reports no value there.

    The PDF path also builds this type from a PDF's own title and author when no
    record backs the document, and then a ``None`` means only that nothing
    supplied the field. Which kind of instance this is shows in
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
    # Which record this was read from, one of ``METADATA_SOURCES``. ``None`` in
    # an instance no record backs, such as the one the PDF path builds from a
    # PDF's own title. DataCite's record carries no journal reference, so
    # ``journal`` is always ``None`` under ``datacite``.
    source: Optional[str] = None


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
    double-quoted scalar — cannot escape a stray control character; a JSON
    string can carry any code point through a ``\\u`` escape, raw C1 controls
    (0x80–0x9F) included, so a record's abstract can carry one. Collapsing keeps
    every field single-line. Returns ``None`` for empty/whitespace-only input.
    """
    if text is None:
        return None
    printable = "".join(ch for ch in text if _is_yaml_printable(ord(ch)))
    collapsed = re.sub(r"\s+", " ", printable).strip()
    return collapsed or None


def _prose(text: Optional[str]) -> Optional[str]:
    """``_normalize`` for record prose, after decoding its HTML entities.

    DataCite stores the title, author names and abstract with entities such as
    ``&gt;`` left encoded.
    """
    if text is None:
        return None
    return _normalize(html.unescape(text))


def _split_version(arxiv_id: str) -> tuple[str, Optional[int]]:
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


def _revision_dates(
    attributes: dict[str, Any], *, date_types: tuple[str, ...]
) -> dict[int, str]:
    """The revisions DataCite lists under ``date_types``, mapped to their dates.

    DataCite labels a revision ``v<N>``, sometimes with a note after it
    (``"v2; None"`` on a withdrawal), so the number is read off the front of
    the label rather than matched against the whole of it.
    """
    versions: dict[int, str] = {}
    for entry in _dicts(attributes.get("dates")):
        if entry.get("dateType") not in date_types:
            continue
        match = _REVISION_LABEL.match(_text(entry, "dateInformation") or "")
        date = _text(entry, "date")
        if match and date:
            versions[int(match.group(1))] = date
    return versions


def _parse_record(arxiv_id: str, attributes: dict[str, Any]) -> ArxivMetadata:
    """Map DataCite's ``data.attributes`` onto the frontmatter fields.

    ``arxiv_id`` is the id as requested. When it names a revision, ``version``
    records that revision; every other field describes the record DataCite
    holds for the paper, which follows the latest revision.
    """
    bare_id, requested = _split_version(arxiv_id)

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

    listed = _revision_dates(attributes, date_types=_REVISION_DATE_TYPES)
    submitted = _revision_dates(attributes, date_types=("Submitted",))
    if requested is not None:
        version: Optional[str] = arxiv_id
    elif listed:
        version = f"{bare_id}v{max(listed)}"
    else:
        version = None

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


def _arxiv_http_cause(code: int) -> str:
    if code == 429:
        return "arXiv rate-limited the request (HTTP 429)"
    if 500 <= code <= 599:
        return f"arXiv server error (HTTP {code})"
    return f"HTTP {code}"


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
    return _arxiv_http_cause(exc.code)


def _lookup_arxiv(arxiv_id: str, timeout: float) -> MetadataFetch:
    """One request to arXiv's Atom API and the classification of its outcome.

    A legacy id loses its subject class first. arXiv answers such an id only
    under the archive alone and returns an empty feed for the other spelling,
    which would send every one of those papers to the fallback.
    """
    query = _SUBJECT_CLASS.sub(r"\1/", arxiv_id)
    url = _ARXIV_API_URL + "?" + urllib.parse.urlencode({"id_list": query})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            tree = ET.parse(resp)
    except urllib.error.HTTPError as exc:
        # HTTPError subclasses URLError, so it must be caught first.
        return _unavailable(_arxiv_error_cause(exc))
    except urllib.error.URLError as exc:
        return _unavailable(f"URLError: {exc.reason}")
    except OSError as exc:
        return _unavailable(_cause(exc))
    except ET.ParseError as exc:
        return _unavailable(f"arXiv returned malformed XML: {exc}")

    entry = tree.find(".//atom:entry", _NS)
    if entry is None:
        return _unavailable("arXiv returned no record for this id")
    if _is_error_entry(entry):
        return _unavailable(
            _normalize(_atom_text(entry, "atom:summary"))
            or "arXiv reported an error for this id"
        )
    return MetadataFetch(METADATA_OK, metadata=_parse_entry(entry))


def _datacite_http_cause(code: int, bare_id: str) -> str:
    if code == 404:
        return f"DataCite has no record for 10.48550/arXiv.{bare_id} (HTTP 404)"
    if code == 429:
        return "DataCite rate-limited the request (HTTP 429)"
    if 500 <= code <= 599:
        return f"DataCite server error (HTTP {code})"
    return f"HTTP {code}"


def _lookup_datacite(arxiv_id: str, timeout: float) -> MetadataFetch:
    """One request to DataCite and the classification of its outcome.

    Returns ``unavailable`` with a cause for every failure it anticipates. An
    unanticipated exception still propagates, and ``fetch_metadata`` turns it
    into ``unavailable`` too.
    """
    bare_id, requested = _split_version(arxiv_id)
    doi_id = _SUBJECT_CLASS.sub(r"\1/", bare_id)
    url = _DATACITE_URL + urllib.parse.quote(doi_id, safe="/")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        # HTTPError subclasses URLError, so it must be caught first.
        return _unavailable(_datacite_http_cause(exc.code, doi_id))
    except urllib.error.URLError as exc:
        return _unavailable(f"URLError: {exc.reason}")
    except OSError as exc:
        return _unavailable(_cause(exc))

    try:
        document = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        # Covers both JSONDecodeError and UnicodeDecodeError.
        return _unavailable(f"DataCite returned malformed JSON: {exc}")

    data = document.get("data") if isinstance(document, dict) else None
    attributes = data.get("attributes") if isinstance(data, dict) else None
    if not isinstance(attributes, dict):
        return _unavailable("DataCite response has no data.attributes")

    listed = _revision_dates(attributes, date_types=_REVISION_DATE_TYPES)
    if requested is not None and listed and requested > max(listed):
        return _unavailable(
            f"{arxiv_id} is later than v{max(listed)}, the latest revision "
            f"DataCite lists for {bare_id}"
        )
    # Parsed under the id arXiv itself uses — the archive alone, without the
    # subject class — so both sources spell ``version`` the same way. Two
    # spellings would read as two papers at the version-drift check, which
    # deletes the cached source and downloads it again on every swing.
    canonical = doi_id if requested is None else f"{doi_id}v{requested}"
    return MetadataFetch(METADATA_OK, metadata=_parse_record(canonical, attributes))


def _lookup(arxiv_id: str, deadline: float) -> MetadataFetch:
    """arXiv's record, or DataCite's when arXiv does not supply one.

    arXiv is asked first because its record and the downloaded files come from
    the same system: the revision it reports is the revision ``fetch_paper``
    then downloads, and it carries a journal reference, which DataCite's
    registration does not. DataCite answers when arXiv cannot — a rate limit,
    an outage, a malformed feed — which is what keeps a run that would
    otherwise record nothing supplied with a record.

    The arXiv attempt may spend only ``_ARXIV_DEADLINE_SHARE`` of ``deadline``,
    so the fallback still has time to answer. When both fail, the returned
    cause names what each of them said.
    """
    started = time.monotonic()
    try:
        primary = _lookup_arxiv(arxiv_id, deadline * _ARXIV_DEADLINE_SHARE)
    except Exception as exc:
        # An exception the arXiv leg does not classify must not take the
        # fallback with it. ``http.client``'s HTTPException subclasses — a
        # connection dropped mid-response, say — are not ``OSError``, and a
        # dropped response is exactly when DataCite should answer.
        primary = _unavailable(_cause(exc))
    if primary.status == METADATA_OK:
        return primary

    remaining = deadline - (time.monotonic() - started)
    if remaining <= 0:
        return _unavailable(
            f"arXiv: {primary.failure_cause}; no time left to ask DataCite"
        )
    fallback = _lookup_datacite(arxiv_id, remaining)
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
    instead of propagating — an unanticipated ``Exception`` in the request, a
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
    outside it, so the request runs in a daemon thread that this call stops
    waiting for. The thread passes the same value as the socket timeout, so a
    request that stalls outright still ends on its own; one that keeps trickling
    can outlive the call, and being a daemon keeps it from holding the process
    open.

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

    outcome: list[MetadataFetch] = []

    def run() -> None:
        try:
            outcome.append(_lookup(arxiv_id, deadline))
        except Exception as exc:
            outcome.append(_unavailable(_cause(exc)))

    try:
        worker = threading.Thread(target=run, name="arxiv-metadata-lookup", daemon=True)
        worker.start()
    except Exception as exc:
        return _unavailable(_cause(exc))
    worker.join(deadline)
    # Read the thread's state before the outcome. A result the worker appends
    # after the join timed out but before this read is still returned below,
    # since the outcome is checked first.
    finished = not worker.is_alive()
    if outcome:
        return outcome[0]
    if not finished:
        return _unavailable(f"metadata lookup exceeded the {deadline:g} s budget")
    # The worker ended without appending, which means an exception escaped
    # run(): a BaseException, or an exception raised inside its handler.
    return _unavailable("metadata lookup ended without a result")


_HANDOFF_SCALARS = (
    "title",
    "version",
    "published",
    "primary_category",
    "doi",
    "journal",
    "abstract",
    "source",
)
_HANDOFF_LISTS = ("authors", "categories")


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
    return MetadataFetch(
        fetch["status"],
        metadata=_handoff_metadata(fetch["metadata"]),
        error=fetch["error"],
    )


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
        "  The frontmatter fields that record supplies are left null. Those "
        "nulls mean the value is unknown, not that the record has none.\n"
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

    ``metadata_source`` is not a parameter: it comes from ``meta.source``, so a
    record renders under the source it was read from, and a document no record
    backs renders it null.

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
    # never passed through the record-side normalization in _parse_record.
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
        _scalar_line("metadata_source", m.source),
        _scalar_line("conversion_date", conversion_date),
        _block_lines("abstract", _normalize(m.abstract)),
        "---",
        "",
        "",
    ]
    return "\n".join(lines)
