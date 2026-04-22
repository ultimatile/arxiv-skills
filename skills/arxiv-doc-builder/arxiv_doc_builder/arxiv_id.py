"""Shared arXiv ID helpers.

Canonical forms accepted:

  - New-style YYMM.NNNNN (5 digits) for YYMM >= 1501 (Jan 2015 onwards)
  - New-style YYMM.NNNN  (4 digits) for 0704 <= YYMM <= 1412
  - Legacy archive-class/YYMMNNN (e.g. hep-th/9901001)
  - Any of the above with an optional vN version suffix

Non-canonical new-style inputs (e.g. 2202.1173, which arXiv silently
redirects to 2202.01173 — a *different* paper) are rejected. The older
"zero-pad to canonical width" behaviour was removed because a 4-digit
user input on a post-2015 paper is almost never an intentional request
for the zero-padded 5-digit paper, and the silent remap masks typos.
"""

import re


# New-style ID with split YY/MM so we can range-check the boundary month.
_NEW_STYLE_RE = re.compile(r"^(\d{2})(\d{2})\.(\d{4,5})(v\d+)?$")

# Legacy ID, e.g. hep-th/9901001, math.AG/0703001, cond-mat/0601234v2.
_LEGACY_RE = re.compile(r"^[a-z]+(-[a-z]+)?(\.[A-Z]{2})?/\d{7}(v\d+)?$")

# First new-style month (April 2007) and first 5-digit month (January 2015).
_FIRST_NEW_YYMM = 704
_FIVE_DIGIT_YYMM = 1501


def safe_arxiv_id(arxiv_id: str) -> str:
    """Make an arXiv ID safe for use as a filesystem path component."""
    return arxiv_id.replace("/", "_")


def validate_arxiv_id(arxiv_id: str) -> str:
    """Return ``arxiv_id`` unchanged if canonical, else raise ``ValueError``.

    Callers are expected to invoke this at argparse boundaries; internal
    code paths may then trust that IDs are in canonical form (no further
    zero-padding required before hitting the arXiv API).
    """
    if _LEGACY_RE.match(arxiv_id):
        return arxiv_id

    m = _NEW_STYLE_RE.match(arxiv_id)
    if not m:
        raise ValueError(
            f"Unrecognized arXiv ID format: {arxiv_id!r}. "
            "Expected YYMM.NNNN / YYMM.NNNNN (optionally with vN), "
            "or legacy archive/YYMMNNN."
        )

    yy, mm, seq, _version = m.groups()
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

    return arxiv_id
