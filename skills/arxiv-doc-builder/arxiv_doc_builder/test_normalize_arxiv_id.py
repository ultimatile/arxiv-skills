"""Contract tests for arXiv ID normalization.

Contract: all valid representations of the same arXiv paper must
normalize to the canonical zero-padded form accepted by the Atom API.
"""

import pytest

from arxiv_doc_builder.convert_latex import normalize_arxiv_id


# New-style IDs (YYMM >= 1501): must be 5 digits after the dot
@pytest.mark.parametrize(
    "input_id, expected",
    [
        ("2506.1376", "2506.01376"),       # short → padded
        ("2506.01376", "2506.01376"),       # already canonical
        ("1501.1", "1501.00001"),           # boundary month, minimal digits
        ("1501.00001", "1501.00001"),       # boundary month, already canonical
        ("2506.1376v2", "2506.01376v2"),    # short with version suffix
        ("2506.01376v1", "2506.01376v1"),   # canonical with version suffix
    ],
)
def test_new_style_ids_padded_to_5_digits(input_id, expected):
    assert normalize_arxiv_id(input_id) == expected


# Old new-style IDs (0704 <= YYMM <= 1412): must be 4 digits after the dot
@pytest.mark.parametrize(
    "input_id, expected",
    [
        ("0704.1", "0704.0001"),           # short → padded
        ("0704.0001", "0704.0001"),        # already canonical
        ("1412.7890", "1412.7890"),        # last 4-digit month, already canonical
        ("1412.789v3", "1412.0789v3"),     # with version suffix
    ],
)
def test_old_new_style_ids_padded_to_4_digits(input_id, expected):
    assert normalize_arxiv_id(input_id) == expected


# Legacy IDs (subject-class/YYMMNNN): passed through unchanged
@pytest.mark.parametrize(
    "input_id",
    [
        "math/0703001",
        "hep-th/9901001",
        "cond-mat/0601234",
    ],
)
def test_legacy_ids_unchanged(input_id):
    assert normalize_arxiv_id(input_id) == input_id
