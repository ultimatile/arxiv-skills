"""Contract tests for arXiv ID validation and filesystem helpers.

Contract: ``validate_arxiv_id`` accepts IDs that are already in canonical
form (and only those); it refuses non-canonical new-style inputs that
would otherwise silently resolve to a *different* paper via arXiv's
zero-padding redirect (e.g. 2202.1173 → 2202.01173).
"""

import pytest

from arxiv_doc_builder.arxiv_id import safe_arxiv_id, validate_arxiv_id


# --- accepted forms -----------------------------------------------------


@pytest.mark.parametrize(
    "arxiv_id",
    [
        # Post-2015 5-digit IDs (with and without version suffix)
        "2506.01376",
        "2506.01376v1",
        "2506.01376v12",
        "1501.00001",  # first month of 5-digit era
        "2202.11737",
        # 2007-04 through 2014-12 4-digit IDs
        "0704.0001",  # first month of new-style scheme
        "1412.7890",  # last 4-digit month
        "1412.0789v3",
        # Legacy archive/YYMMNNN IDs — short-uppercase subclass form
        "hep-th/9901001",
        "math/0703001",
        "cond-mat/0601234",
        "math.AG/0703001",
        "nlin.AO/0601001",
        "hep-th/9901001v2",
        # Legacy boundary months (first and last months of the scheme)
        "hep-th/9108001",
        "hep-th/0703999",
        # Legacy IDs with lowercase / hyphenated subject classes
        "physics.optics/0501001",
        "physics.comp-ph/0612001",
        "cond-mat.str-el/0601234",
        "cond-mat.stat-mech/0601234v2",
    ],
)
def test_canonical_ids_accepted(arxiv_id):
    assert validate_arxiv_id(arxiv_id) == arxiv_id


# --- rejected forms -----------------------------------------------------


@pytest.mark.parametrize(
    "arxiv_id",
    [
        # Post-2015 paper with 4 digits: would silently remap to a zero-padded
        # neighbour. The exact case that motivated the validator.
        "2202.1173",
        "1501.0001",  # boundary month
        "2506.1376",
        "2506.1376v2",
        # Pre-2015 paper with 5 digits: no such paper exists in that window.
        "1412.00001",
        "0704.00001",
        # Before April 2007 (new-style scheme hadn't started yet).
        "0701.0001",
        "0703.0001",
        # Invalid month.
        "2013.0001",  # month 13
        "2500.00001",  # month 00
        # Structurally malformed.
        "2506",
        "2506.",
        "2506.123",  # 3 digits: neither canonical width
        "2506.1234567",  # too many digits
        "abcd.12345",
        "",
        # Semantically impossible: sequences start at 1, not 0.
        "2506.00000",
        "1412.0000",
        "hep-th/9901000",
        # Semantically impossible: versions start at v1.
        "2506.01376v0",
        "1412.1234v0",
        "hep-th/9901001v0",
        # Legacy form but YYMM outside the scheme (Apr 2007 onwards is new-style).
        "hep-th/0704001",
        "hep-th/0801001",
        "hep-th/1501001",
        # Legacy form with pre-arXiv YYMM (before Aug 1991).
        "hep-th/9101001",
        "hep-th/9107001",
        # Legacy form with YY outside any known window.
        "hep-th/4501001",
        # Legacy form with invalid month.
        "hep-th/9913001",
    ],
)
def test_noncanonical_ids_rejected(arxiv_id):
    with pytest.raises(ValueError):
        validate_arxiv_id(arxiv_id)


# --- filesystem helper --------------------------------------------------


@pytest.mark.parametrize(
    "arxiv_id, expected",
    [
        ("2506.01376", "2506.01376"),  # new-style: no change
        ("hep-th/9901001", "hep-th_9901001"),  # legacy: slash → underscore
        ("math.AG/0703001v2", "math.AG_0703001v2"),
    ],
)
def test_safe_arxiv_id(arxiv_id, expected):
    assert safe_arxiv_id(arxiv_id) == expected
