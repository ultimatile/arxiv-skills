"""Shared arXiv ID helpers.

Canonical forms accepted:

  - New-style YYMM.NNNNN (5 digits) for YYMM >= 1501 (Jan 2015 onwards)
  - New-style YYMM.NNNN  (4 digits) for 0704 <= YYMM <= 1412
  - Legacy archive[.subject-class]/YYMMNNN for 9108 <= YYMM <= 0703
  - Any of the above with an optional vN (N >= 1) version suffix

Non-canonical new-style inputs (e.g. 2202.1173, which arXiv silently
redirects to 2202.01173 — a *different* paper) are rejected. The older
"zero-pad to canonical width" behaviour was removed because a 4-digit
user input on a post-2015 paper is almost never an intentional request
for the zero-padded 5-digit paper, and the silent remap masks typos.

The validator also rejects semantically impossible inputs: all-zero
sequence numbers, version zero, invalid months, and legacy-scheme
YYMM values that fall outside arXiv's actual legacy window.
"""

import re
from typing import Optional


# New-style ID with split YY/MM so we can range-check the boundary month.
_NEW_STYLE_RE = re.compile(r"^(\d{2})(\d{2})\.(\d{4,5})(v\d+)?$")

# Legacy ID, e.g. hep-th/9901001, math.AG/0703001, cond-mat/0601234v2,
# physics.optics/0501001, cond-mat.str-el/0601234. Subject classes come
# in both short-uppercase (math.AG, nlin.CD) and lowercase-with-hyphens
# (physics.optics, cond-mat.str-el, physics.comp-ph) forms.
_LEGACY_RE = re.compile(
    r"^[a-z]+(?:-[a-z]+)?(?:\.[A-Za-z]+(?:-[A-Za-z]+)*)?"
    r"/(\d{2})(\d{2})(\d{3})(v\d+)?$"
)

# Boundaries:
#   Aug 1991: first arXiv submission (hep-th/9108001)
#   Mar 2007: last legacy-scheme month
#   Apr 2007: first new-style month (0704.0001)
#   Jan 2015: first 5-digit sequence month
_LEGACY_MIN_YYYYMM = 199108
_LEGACY_MAX_YYYYMM = 200703
_FIRST_NEW_YYMM = 704
_FIVE_DIGIT_YYMM = 1501


def safe_arxiv_id(arxiv_id: str) -> str:
    """Make an arXiv ID safe for use as a filesystem path component."""
    return arxiv_id.replace("/", "_")


def _check_version(arxiv_id: str, version_group: Optional[str]) -> None:
    """Reject v0. arXiv version numbering starts at v1."""
    if not version_group:
        return
    if int(version_group[1:]) < 1:
        raise ValueError(
            f"arXiv ID {arxiv_id!r}: version numbers start at v1, "
            f"got {version_group!r}."
        )


def _check_sequence(arxiv_id: str, seq: str) -> None:
    """Reject all-zero sequence numbers. arXiv sequences start at 1."""
    if int(seq) < 1:
        raise ValueError(
            f"arXiv ID {arxiv_id!r}: sequence numbers start at 1, got {seq!r}."
        )


def _legacy_yyyymm(yy: str, mm: str) -> Optional[int]:
    """Expand legacy YY/MM to a comparable YYYYMM integer, or None.

    Legacy 2-digit years map to 1991-1999 (91..99) or 2000-2007 (00..07).
    YY outside those ranges has no legacy interpretation and returns None,
    which the caller turns into a validation error.
    """
    yy_int = int(yy)
    if 91 <= yy_int <= 99:
        year = 1900 + yy_int
    elif 0 <= yy_int <= 7:
        year = 2000 + yy_int
    else:
        return None
    return year * 100 + int(mm)


def validate_arxiv_id(arxiv_id: str) -> str:
    """Return ``arxiv_id`` unchanged if canonical, else raise ``ValueError``.

    Callers are expected to invoke this at argparse boundaries; internal
    code paths may then trust that IDs are in canonical form (no further
    zero-padding required before hitting the arXiv API).
    """
    legacy_m = _LEGACY_RE.match(arxiv_id)
    if legacy_m:
        yy, mm, seq, version = legacy_m.groups()
        month = int(mm)
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid month {mm!r} in arXiv ID {arxiv_id!r}.")
        ym = _legacy_yyyymm(yy, mm)
        if ym is None or not (_LEGACY_MIN_YYYYMM <= ym <= _LEGACY_MAX_YYYYMM):
            raise ValueError(
                f"arXiv ID {arxiv_id!r}: legacy scheme covers Aug 1991 "
                "through Mar 2007. Outside that window, use the new-style "
                "YYMM.NNNN(N) form."
            )
        _check_sequence(arxiv_id, seq)
        _check_version(arxiv_id, version)
        return arxiv_id

    m = _NEW_STYLE_RE.match(arxiv_id)
    if not m:
        raise ValueError(
            f"Unrecognized arXiv ID format: {arxiv_id!r}. "
            "Expected YYMM.NNNN / YYMM.NNNNN (optionally with vN), "
            "or legacy archive/YYMMNNN."
        )

    yy, mm, seq, version = m.groups()
    month = int(mm)
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month {mm!r} in arXiv ID {arxiv_id!r}.")

    yymm = int(yy + mm)
    if yymm < _FIRST_NEW_YYMM:
        raise ValueError(
            f"arXiv ID {arxiv_id!r}: new-style IDs begin in April 2007 "
            "(YYMM=0704). For earlier papers use the legacy "
            "archive/YYMMNNN form."
        )

    seq_len = len(seq)
    if yymm >= _FIVE_DIGIT_YYMM and seq_len != 5:
        raise ValueError(
            f"arXiv ID {arxiv_id!r}: papers from 2015-01 onwards use "
            "5-digit sequence numbers (YYMM.NNNNN). A 4-digit input on a "
            "post-2015 paper is refused to avoid silently resolving to a "
            "zero-padded neighbour (e.g. 2202.1173 → 2202.01173)."
        )
    if yymm < _FIVE_DIGIT_YYMM and seq_len != 4:
        raise ValueError(
            f"arXiv ID {arxiv_id!r}: papers from 2007-04 through 2014-12 "
            "use 4-digit sequence numbers (YYMM.NNNN)."
        )

    _check_sequence(arxiv_id, seq)
    _check_version(arxiv_id, version)
    return arxiv_id
