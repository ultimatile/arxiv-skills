"""The conftest network guard refuses and records a child's request.

Every other test relies on the guard being silent, so a guard that stopped
loading would leave them all green. This drives it directly. Its teardown check
is a single emptiness test on the record file and is not run through a nested
pytest session, since the suite does not enable the ``pytester`` plugin.
"""

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
