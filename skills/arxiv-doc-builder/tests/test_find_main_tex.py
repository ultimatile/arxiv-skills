"""Contract tests for main .tex discovery.

Contract: find_main_tex must never silently guess between multiple
\\documentclass files. Conventional names (main.tex, paper.tex, ms.tex,
article.tex) take precedence; if none match and more than one
\\documentclass file is present, it must raise AmbiguousMainTexError so
the caller can fail explicitly and require --tex-file on re-run.
"""

import subprocess
import sys
from pathlib import Path

import pytest

import arxiv_doc_builder
from arxiv_doc_builder.convert_latex import (
    AmbiguousMainTexError,
    extract_title_from_latex,
    find_main_tex,
)


def _write_tex(dir_: Path, name: str, with_documentclass: bool = True) -> Path:
    path = dir_ / name
    body = "\\documentclass{article}\n" if with_documentclass else ""
    body += "\\begin{document}\nhello\n\\end{document}\n"
    path.write_text(body, encoding="utf-8")
    return path


def test_known_name_wins_over_ambiguity(tmp_path):
    # Even with multiple \documentclass files, a conventional main.tex
    # must short-circuit the ambiguity check.
    main = _write_tex(tmp_path, "main.tex")
    _write_tex(tmp_path, "supplement.tex")
    _write_tex(tmp_path, "appendix.tex")

    assert find_main_tex(tmp_path) == main


def test_single_documentclass_returned(tmp_path):
    only = _write_tex(tmp_path, "foo.tex")
    # A file without \documentclass must not count as a candidate.
    _write_tex(tmp_path, "bar.tex", with_documentclass=False)

    assert find_main_tex(tmp_path) == only


def test_multiple_documentclass_raises(tmp_path):
    a = _write_tex(tmp_path, "alpha.tex")
    b = _write_tex(tmp_path, "beta.tex")

    with pytest.raises(AmbiguousMainTexError) as exc_info:
        find_main_tex(tmp_path)

    # All candidates must be reported so the caller can surface them.
    assert set(exc_info.value.candidates) == {a, b}


def test_no_tex_files_returns_none(tmp_path):
    assert find_main_tex(tmp_path) is None


def test_cli_exits_2_on_ambiguity_with_candidates_in_stderr(tmp_path):
    # End-to-end CLI contract: invoking convert_latex.py against an
    # ambiguous source dir must exit 2 and report every candidate on stderr.
    # This guards against future refactors that swallow the exception.
    _write_tex(tmp_path, "alpha.tex")
    _write_tex(tmp_path, "beta.tex")

    script = Path(arxiv_doc_builder.__file__).parent / "convert_latex.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            # Canonical placeholder so validate_arxiv_id accepts it; the
            # ambiguity contract is independent of the specific ID.
            "2409.03108",
            "--source-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "out.md"),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "alpha.tex" in result.stderr
    assert "beta.tex" in result.stderr
    assert "--tex-file" in result.stderr


def test_extract_title_uses_selected_tex_not_arbitrary_sibling(tmp_path):
    # Contract: the fallback title must come from the file actually converted,
    # not an arbitrary .tex picked from the source directory.
    (tmp_path / "main.tex").write_text(r"\title{Correct Main Title}", encoding="utf-8")
    (tmp_path / "supplement.tex").write_text(
        r"\title{Wrong Supplement Title}", encoding="utf-8"
    )

    assert extract_title_from_latex(tmp_path / "main.tex") == "Correct Main Title"
    assert (
        extract_title_from_latex(tmp_path / "supplement.tex")
        == "Wrong Supplement Title"
    )


def test_extract_title_falls_back_to_sibling_when_selected_has_none(tmp_path):
    # The \title may sit in an included preamble; fall back to siblings rather
    # than reporting no title.
    (tmp_path / "main.tex").write_text(r"\documentclass{article}", encoding="utf-8")
    (tmp_path / "preamble.tex").write_text(
        r"\title{Title In Preamble}", encoding="utf-8"
    )

    assert extract_title_from_latex(tmp_path / "main.tex") == "Title In Preamble"


def test_extract_title_returns_none_when_absent(tmp_path):
    # No \title anywhere -> None, so the frontmatter title stays null rather than
    # a fabricated placeholder.
    (tmp_path / "main.tex").write_text(r"\documentclass{article}", encoding="utf-8")

    assert extract_title_from_latex(tmp_path / "main.tex") is None
