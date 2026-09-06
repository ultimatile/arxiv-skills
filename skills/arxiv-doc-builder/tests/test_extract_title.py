"""The LaTeX fallback title, used when arXiv supplies none.

Whatever survives this extraction is written verbatim into a YAML title a
reader sees. Leftover markup lands there as wrong text.
"""

import pytest

from arxiv_doc_builder.convert_latex import extract_title_from_latex


def _tex(tmp_path, body: str):
    path = tmp_path / "main.tex"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\title{Plain Title}", "Plain Title"),
        # LaTeX's non-breaking space. Left alone it glues the two words it was
        # written to keep on one line.
        (r"\title{Koopman-Mori-Zwanzig~formalism}", "Koopman-Mori-Zwanzig formalism"),
        # Consecutive tildes collapse with the surrounding whitespace rather
        # than leaving a run of spaces behind.
        (r"\title{A~~B}", "A B"),
        (r"\title{Multi~word~title}", "Multi word title"),
        # A tilde adjacent to a command keeps the single separating space.
        (r"\title{Section~\ref{intro} overview}", "Section intro overview"),
    ],
)
def test_spacing_markup_does_not_reach_the_title(tmp_path, source, expected):
    assert extract_title_from_latex(_tex(tmp_path, source)) == expected


def test_the_tilde_accent_is_left_as_it_is(tmp_path):
    # ``\~`` is the tilde accent, not a spacing token, so the normalization
    # must not touch it. Its markup is not resolved here either. This pins
    # that the case stays exactly where it already stood.
    assert extract_title_from_latex(_tex(tmp_path, r"\title{A\~{n}o study}")) == (
        r"A\~no study"
    )


def test_no_title_stays_none(tmp_path):
    assert extract_title_from_latex(_tex(tmp_path, "no title here\n")) is None
