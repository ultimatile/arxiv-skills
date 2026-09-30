"""SKILL.md's `{SAFE_ID}` examples are what `safe_arxiv_id` returns.

The agent builds paths under the output directory from `{SAFE_ID}` as SKILL.md
defines it, while `convert-paper` builds them with `safe_arxiv_id`. A change to
the replacement would update that function's own tests and leave the SKILL.md
example stale, so the example is checked against the function here.
"""

import re

from arxiv_doc_builder.arxiv_id import safe_arxiv_id, validate_arxiv_id
from conftest import read_skill_md

_OUTPUT_DIR_BULLET = re.compile(r"^(\s*)- `--output-dir`:")
# The failure section uses the same arrow to route an output to a reference
# file, so pairs are taken from the `--output-dir` bullet alone.
_EXAMPLE = re.compile(r"`([^`]+)` → `([^`]+)`")


def _output_dir_bullet(text: str) -> str:
    """The `--output-dir` bullet with its continuation lines."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _OUTPUT_DIR_BULLET.match(line)
        if match:
            indent = len(match.group(1))
            bullet = [line]
            for rest in lines[i + 1 :]:
                if len(rest) - len(rest.lstrip()) <= indent:
                    break
                bullet.append(rest)
            return "\n".join(bullet)
    raise AssertionError("SKILL.md has no `--output-dir` bullet")


def test_safe_id_examples_match_safe_arxiv_id() -> None:
    examples = _EXAMPLE.findall(_output_dir_bullet(read_skill_md()))
    # An ID without `/` maps to itself under any replacement, so only a
    # slash-bearing example exercises it.
    assert any("/" in arxiv_id for arxiv_id, _ in examples), examples
    for arxiv_id, safe_id in examples:
        validate_arxiv_id(arxiv_id)
        assert safe_arxiv_id(arxiv_id) == safe_id
