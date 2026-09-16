"""The conftest network guard refuses and records a child's request.

Every other test relies on the guard being silent, so a guard that stopped
loading would leave them all green. This drives it directly.
"""

import os
import subprocess
import sys
import textwrap

_URL = "https://api.datacite.org/dois/10.48550/arxiv.2409.03108"


def test_a_child_request_is_refused_and_recorded(network_record):
    program = textwrap.dedent(
        f"""
        import urllib.request
        try:
            urllib.request.urlopen({_URL!r}, timeout=5)
        except OSError as exc:
            print("refused:", exc)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("refused: network access is blocked in tests")
    assert network_record.read_text(encoding="utf-8") == _URL + "\n"
    # Emptied so this test's own teardown check passes.
    network_record.write_text("", encoding="utf-8")


def test_the_guard_chains_to_the_sitecustomize_it_displaces(
    tmp_path, monkeypatch, network_record
):
    # Python imports only the first sitecustomize on sys.path. Without the
    # chain, an environment shipping its own would lose it in every Python
    # process a test starts, silently and only under pytest.
    displaced = tmp_path / "displaced"
    displaced.mkdir()
    marker = tmp_path / "marker.txt"
    (displaced / "sitecustomize.py").write_text(
        f"open({str(marker)!r}, 'w', encoding='utf-8').write('loaded')\n",
        encoding="utf-8",
    )
    # After the guard's own directory, which the fixture put first.
    monkeypatch.setenv(
        "PYTHONPATH", os.environ["PYTHONPATH"] + os.pathsep + str(displaced)
    )

    result = subprocess.run(
        [sys.executable, "-c", "import urllib.request"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "loaded"
