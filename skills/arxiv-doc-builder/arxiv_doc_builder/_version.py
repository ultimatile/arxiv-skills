"""Resolve the package version for the CLI ``--version`` output.

The SSOT is the installed distribution metadata: once built, the version is
baked into ``arxiv_doc_builder-<ver>.dist-info/METADATA`` and read at runtime
via ``importlib.metadata.version``. That is the only source needed for an
installed CLI.

A fallback to parsing ``pyproject.toml`` directly *is* warranted here, unlike
the usual uv-tool-install workflow. This skill is run straight from the
checkout — ``uv run arxiv_doc_builder/convert_paper.py`` and the
``uv run --no-project`` / bare-interpreter calls in ``convert_paper.run_script``
never install the package, so no ``.dist-info`` exists and
``importlib.metadata.version`` raises ``PackageNotFoundError``. The fallback is
what makes ``--version`` report the real number in that mode instead of crashing.

Note the distribution name passed to ``metadata.version`` is the hyphenated
``arxiv-doc-builder`` (``pyproject``'s ``[project] name``), not the underscored
import name ``arxiv_doc_builder`` — they intentionally differ.

Every failure degrades to ``"unknown"`` rather than propagating, so
``--version`` never raises regardless of how the code was reached: an
unexpected metadata-resolution error (corrupt installed distribution) and
every pyproject fallback failure (missing file, parse error, absent key) are
all absorbed. ``tomllib`` is always available because ``requires-python`` is
``>=3.11``.
"""

import tomllib
from pathlib import Path

# Distribution name from pyproject's [project] name. A literal, not derived
# from __package__, so a rename surfaces as a lookup miss instead of a wrong
# answer (see the dist-name/import-name pitfall in the design notes).
_DIST_NAME = "arxiv-doc-builder"


def read_version() -> str:
    """Return the package version, or ``"unknown"`` if unresolvable."""
    from importlib import metadata

    try:
        return metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        # No dist-info — the common source-tree case. Fall through.
        return _version_from_pyproject()
    except Exception:
        # Any other resolution failure (e.g. corrupt or unparseable
        # installed metadata) is an unexpected state, not the "not
        # installed" signal — degrade straight to "unknown" to honor the
        # never-raise contract rather than trusting the pyproject fallback.
        return "unknown"


def _version_from_pyproject() -> str:
    """Read ``[project] version`` from the sibling ``pyproject.toml``.

    Walks up from this module to the package root's parent, where the project's
    pyproject lives. All I/O and parse failures collapse to ``"unknown"``.
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"

    try:
        with pyproject.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"
