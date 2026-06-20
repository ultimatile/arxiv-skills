#!/usr/bin/env python3
"""Fetch arXiv metadata and render the document frontmatter.

Single source of truth for the YAML frontmatter prepended to a converted
paper by both conversion paths (``convert_latex.py`` and the PDF path through
``pdf_converter_lib.py``). The frontmatter is the provenance surface a
downstream consumer reads, so it must carry the same key set regardless of
which path produced it or whether the network was reachable.

Design constraints:

- **Runtime is dependency-free.** The LaTeX path runs as a plain ``python3``
  subprocess with no third-party packages installed, so the frontmatter is
  hand-emitted rather than routed through PyYAML. A round-trip contract test
  (which *may* use PyYAML, a test-only dependency) pins the emitted text to
  valid, re-parseable YAML.
- **The schema is total.** ``build_frontmatter`` always emits every key, even
  when the arXiv fetch failed. Unknown values render as YAML null (a bare
  ``key:``), which a parser reads as ``None``. This deliberately distinguishes
  "arXiv reported no value" (e.g. a preprint with no journal DOI) from a key
  that was simply never written — the consumer needs the former for an
  absence-confirmation ("preprint, no journal DOI") judgement.

Responsibility boundary: the DOI/journal reported here are whatever arXiv's own
record carries (passive transcription). Resolving a DOI that arXiv does not
carry (e.g. via OpenAlex) belongs to the arxiv-lookup skill, not here.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

# arXiv's API serves Atom with an arxiv-specific extension namespace; the
# primary_category / doi / journal_ref fields live in the latter.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_API_URL = "https://export.arxiv.org/api/query"


@dataclass
class ArxivMetadata:
    """The subset of an arXiv record that the frontmatter transcribes.

    Every field is optional: a failed or partial fetch yields ``None`` / empty
    lists rather than raising, so callers can always render a (sparser)
    frontmatter instead of aborting the conversion.
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
    """Make Atom text safe and stable for the frontmatter.

    Two steps: drop characters YAML cannot carry (see ``_is_yaml_printable``),
    then collapse whitespace runs to single spaces. Stripping is required
    because the abstract is emitted as a literal block scalar, which — unlike a
    double-quoted scalar — cannot escape a stray control character; XML 1.0
    permits raw C1 controls (0x80–0x9F) that YAML forbids, so an arXiv summary
    can carry one. Collapsing keeps every field single-line. Returns ``None``
    for empty/whitespace-only input.
    """
    if text is None:
        return None
    printable = "".join(ch for ch in text if _is_yaml_printable(ord(ch)))
    collapsed = re.sub(r"\s+", " ", printable).strip()
    return collapsed or None


def _text(entry: ET.Element, path: str) -> Optional[str]:
    """Return the text of the first matching child element, or None."""
    el = entry.find(path, _NS)
    return el.text if el is not None else None


def parse_version_from_id(id_url: Optional[str]) -> Optional[str]:
    """Extract the full versioned arXiv id from an Atom ``<id>`` URL.

    Returns the full path tail *including* the version suffix, e.g.
    ``"2409.03108v2"`` or the legacy ``"hep-th/9901001v3"`` — identical to what
    the version-drift sidecar persists, so ``fetch_paper`` can delegate here
    without changing the cached value. Returns ``None`` when no tail is present.

        <id>http://arxiv.org/abs/2409.03108v2</id>     -> "2409.03108v2"
        <id>http://arxiv.org/abs/hep-th/9901001v3</id> -> "hep-th/9901001v3"
    """
    if not id_url:
        return None
    path = urllib.parse.urlparse(id_url).path
    if path.startswith("/abs/"):
        return path[len("/abs/") :] or None
    return id_url.rsplit("/", 1)[-1] or None


def fetch_metadata(arxiv_id: str, *, timeout: int = 10) -> Optional[ArxivMetadata]:
    """Fetch the full arXiv record for ``arxiv_id`` in a single API call.

    Returns ``None`` on any network or parse failure so callers can fall back
    to a local title source (LaTeX ``\\title``, PDF embedded metadata) without
    special-casing exceptions. Assumes ``arxiv_id`` is already validated to
    canonical form; no zero-padding is performed here.
    """
    url = _API_URL + "?" + urllib.parse.urlencode({"id_list": arxiv_id})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            tree = ET.parse(resp)
    except Exception:
        return None

    entry = tree.find(".//atom:entry", _NS)
    if entry is None:
        return None

    primary = entry.find("arxiv:primary_category", _NS)
    return ArxivMetadata(
        title=_normalize(_text(entry, "atom:title")),
        authors=[
            name
            for name in (
                _normalize(n.text) for n in entry.findall("atom:author/atom:name", _NS)
            )
            if name
        ],
        version=parse_version_from_id(_text(entry, "atom:id")),
        # arXiv 'published' is an ISO timestamp; the frontmatter keeps the
        # calendar date (the paper's date), distinct from conversion_date.
        published=(_text(entry, "atom:published") or "")[:10] or None,
        primary_category=primary.get("term") if primary is not None else None,
        categories=[
            term
            for term in (c.get("term") for c in entry.findall("atom:category", _NS))
            if term
        ],
        doi=_normalize(_text(entry, "arxiv:doi")),
        journal=_normalize(_text(entry, "arxiv:journal_ref")),
        abstract=_normalize(_text(entry, "atom:summary")),
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
    fallback_title: Optional[str] = None,
) -> str:
    """Render the YAML frontmatter block for a converted paper.

    Every key is always present (a total schema) so a consumer can read
    provenance from a fixed location regardless of conversion path or whether
    the arXiv fetch succeeded. ``arxiv_id`` is optional: manual PDF scripts
    invoke the converter without an id, in which case it renders as null like
    any other unknown field.
    """
    m = meta or ArxivMetadata()
    # Normalize every emitted text scalar here, so the block is clean and valid
    # regardless of how the metadata was built — the PDF fallback path
    # constructs ArxivMetadata straight from raw PDF-embedded strings, which
    # never passed through the Atom-side normalization in fetch_metadata.
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
        _scalar_line("conversion_date", conversion_date),
        _block_lines("abstract", _normalize(m.abstract)),
        "---",
        "",
        "",
    ]
    return "\n".join(lines)
