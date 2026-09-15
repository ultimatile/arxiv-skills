"""Which host the source download goes to.

`fetch_source` must download from `export.arxiv.org`; the reason is stated
where it builds `source_url`. Both hosts serve the same archive, so nothing
else notices if the URL drifts to `arxiv.org`; only this pin does.
"""

import subprocess

from arxiv_doc_builder import fetch_paper


def test_source_is_downloaded_from_the_export_host(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        # Fail the download so fetch_source returns before extraction.
        return subprocess.CompletedProcess(argv, returncode=22)

    monkeypatch.setattr(fetch_paper.subprocess, "run", fake_run)

    assert not fetch_paper.fetch_source("2409.03108", tmp_path, "2409.03108")
    assert calls[0][0] == "curl"
    assert calls[0][-1] == "https://export.arxiv.org/src/2409.03108"
