"""Contract tests for the pandoc runaway bounds in convert_with_pandoc.

Contract: convert_with_pandoc must never hang on a runaway pandoc. It bounds
execution by a wall-clock timeout and an RSS watchdog; on either trip it kills
the child and returns False (it does not raise and does not block past the
timeout). _process_rss_mb must parse `ps -o rss=` output defensively, returning
None rather than raising when the output is unparseable or `ps` fails.

These use fakes for subprocess.Popen / subprocess.run / time.monotonic so the
control flow is exercised without depending on a real pandoc or on timing.
"""

import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from arxiv_doc_builder import convert_latex
from arxiv_doc_builder.convert_latex import _process_rss_mb, convert_with_pandoc


@pytest.fixture(autouse=True)
def _which_resolves_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve any binary to a fake absolute path so the suite does not depend on
    the host actually having pandoc / ps installed (convert_with_pandoc and
    _process_rss_mb now go through shutil.which before launching a subprocess)."""
    monkeypatch.setattr(convert_latex.shutil, "which", lambda name: f"/usr/bin/{name}")


class _FakeCompleted:
    """Stand-in for subprocess.run's CompletedProcess (stdout only)."""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


class _FakeProc:
    """Stand-in for the Popen handle convert_with_pandoc drives.

    ``finishes`` controls whether ``wait(timeout=...)`` returns or raises
    TimeoutExpired. ``kill()`` flips it to finished so the subsequent
    bounded ``wait()`` returns instead of hanging the test.
    """

    def __init__(self, *, finishes: bool, returncode: int = 0) -> None:
        self._finishes = finishes
        self.returncode = returncode
        self.pid = 4321
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        if self._finishes:
            return self.returncode
        # The bounded-wait path is only ever driven with a real float timeout;
        # narrow it so TimeoutExpired (which requires a float) typechecks.
        assert timeout is not None
        raise subprocess.TimeoutExpired(cmd="pandoc", timeout=timeout)

    def kill(self) -> None:
        self.killed = True
        self._finishes = True


def _patch_popen(monkeypatch: pytest.MonkeyPatch, proc: _FakeProc) -> None:
    monkeypatch.setattr(convert_latex.subprocess, "Popen", lambda *a, **k: proc)


# ---- _process_rss_mb ----


def test_process_rss_mb_parses_kb_to_mb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        convert_latex.subprocess, "run", lambda *a, **k: _FakeCompleted("2048\n")
    )
    assert _process_rss_mb(1234) == 2  # 2048 KB -> 2 MB


def test_process_rss_mb_none_on_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        convert_latex.subprocess, "run", lambda *a, **k: _FakeCompleted("")
    )
    assert _process_rss_mb(1234) is None


def test_process_rss_mb_none_on_ps_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> NoReturn:
        raise OSError("ps unavailable")

    monkeypatch.setattr(convert_latex.subprocess, "run", boom)
    assert _process_rss_mb(1234) is None


# ---- convert_with_pandoc bounds ----


def test_timeout_kills_and_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(finishes=False)
    _patch_popen(monkeypatch, proc)
    # start = 0.0, then the loop's clock reads past the timeout on first check.
    times = iter([0.0, 1000.0, 1000.0])
    monkeypatch.setattr(convert_latex.time, "monotonic", lambda: next(times))
    # RSS stays low so only the timeout can trip.
    monkeypatch.setattr(convert_latex, "_process_rss_mb", lambda pid: 1)

    ok = convert_with_pandoc(Path("x.tex"), Path("out.md"), timeout=5, rss_cap_mb=8192)

    assert ok is False
    assert proc.killed


def test_rss_watchdog_kills_and_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(finishes=False)
    _patch_popen(monkeypatch, proc)
    # Clock never advances past the (large) timeout, so only RSS can trip.
    monkeypatch.setattr(convert_latex.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(convert_latex, "_process_rss_mb", lambda pid: 9000)

    ok = convert_with_pandoc(
        Path("x.tex"), Path("out.md"), timeout=300, rss_cap_mb=8192
    )

    assert ok is False
    assert proc.killed


def test_returns_false_when_pandoc_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail closed (not hang, not crash) when pandoc cannot be resolved on PATH.
    monkeypatch.setattr(convert_latex.shutil, "which", lambda _name: None)

    def _no_popen(*_a: object, **_k: object) -> NoReturn:
        raise AssertionError("Popen must not run when pandoc is unresolved")

    monkeypatch.setattr(convert_latex.subprocess, "Popen", _no_popen)

    assert convert_with_pandoc(Path("x.tex"), Path("out.md")) is False


def test_returns_false_when_pandoc_path_relative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A relative which() result (relative PATH entry) must be rejected, since it
    # would re-resolve against the untrusted cwd.
    monkeypatch.setattr(convert_latex.shutil, "which", lambda _name: "pandoc")

    def _no_popen(*_a: object, **_k: object) -> NoReturn:
        raise AssertionError("Popen must not run for a relative pandoc path")

    monkeypatch.setattr(convert_latex.subprocess, "Popen", _no_popen)

    assert convert_with_pandoc(Path("x.tex"), Path("out.md")) is False


def test_process_rss_mb_none_when_ps_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(convert_latex.shutil, "which", lambda _name: None)

    def _no_run(*_a: object, **_k: object) -> NoReturn:
        raise AssertionError("subprocess.run must not run when ps is unresolved")

    monkeypatch.setattr(convert_latex.subprocess, "run", _no_run)
    assert _process_rss_mb(1234) is None


def test_process_rss_mb_none_when_ps_path_relative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(convert_latex.shutil, "which", lambda _name: "ps")

    # The relative path must be rejected BEFORE any exec, so run must not fire.
    def _no_run(*_a: object, **_k: object) -> NoReturn:
        raise AssertionError("subprocess.run must not run for a relative ps path")

    monkeypatch.setattr(convert_latex.subprocess, "run", _no_run)
    assert _process_rss_mb(1234) is None


def test_success_returns_true_without_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(finishes=True, returncode=0)
    _patch_popen(monkeypatch, proc)
    monkeypatch.setattr(convert_latex.time, "monotonic", lambda: 0.0)

    ok = convert_with_pandoc(Path("x.tex"), Path("out.md"))

    assert ok is True
    assert not proc.killed


def test_nonzero_exit_returns_false_without_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc(finishes=True, returncode=1)
    _patch_popen(monkeypatch, proc)
    monkeypatch.setattr(convert_latex.time, "monotonic", lambda: 0.0)

    ok = convert_with_pandoc(Path("x.tex"), Path("out.md"))

    assert ok is False
    assert not proc.killed


def test_post_kill_wait_timeout_does_not_rehang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A child that does not reap within the post-kill grace window must not
    # re-hang convert_with_pandoc: the bounded wait swallows TimeoutExpired.
    class _StuckProc(_FakeProc):
        def kill(self) -> None:
            self.killed = True  # but leave _finishes False so wait() keeps raising

    proc = _StuckProc(finishes=False)
    _patch_popen(monkeypatch, proc)
    times = iter([0.0, 1000.0, 1000.0])
    monkeypatch.setattr(convert_latex.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(convert_latex, "_process_rss_mb", lambda pid: 1)

    ok = convert_with_pandoc(Path("x.tex"), Path("out.md"), timeout=5)

    assert ok is False
    assert proc.killed


# ---- _int_env (env-override parsing) ----


def test_int_env_uses_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARXIV_TEST_INT", raising=False)
    assert convert_latex._int_env("ARXIV_TEST_INT", 7) == 7


def test_int_env_parses_valid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARXIV_TEST_INT", "42")
    assert convert_latex._int_env("ARXIV_TEST_INT", 7) == 42


def test_int_env_falls_back_on_non_numeric(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARXIV_TEST_INT", "3m")
    assert convert_latex._int_env("ARXIV_TEST_INT", 7) == 7
    # A malformed override warns on stderr rather than raising (would crash import).
    assert "Ignoring non-integer" in capsys.readouterr().err


def test_int_env_falls_back_on_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 0 is syntactically valid but a zero timeout / RSS cap would trip instantly.
    monkeypatch.setenv("ARXIV_TEST_INT", "0")
    assert convert_latex._int_env("ARXIV_TEST_INT", 7) == 7
    assert "Ignoring non-positive" in capsys.readouterr().err


def test_int_env_falls_back_on_negative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARXIV_TEST_INT", "-5")
    assert convert_latex._int_env("ARXIV_TEST_INT", 7) == 7
    assert "Ignoring non-positive" in capsys.readouterr().err
