"""Resolve the package version for the CLI ``--version`` output.

The SSOT is the installed distribution metadata: once built, the version is
baked into ``arxiv_doc_builder-<ver>.dist-info/METADATA`` and read at runtime
via ``importlib.metadata.version``. That is the only source needed for an
installed CLI.

A fallback to parsing ``pyproject.toml`` directly *is* warranted here, unlike
the usual uv-tool-install workflow. This skill's scripts sit in the checkout,
and ``convert_paper.py`` can be run from there by an interpreter the package
was never installed into — ``uv run --no-project``, or a bare ``python`` —
where no ``.dist-info`` exists and ``importlib.metadata.version`` raises
``PackageNotFoundError``. The fallback is what makes ``--version`` report the
real number in that mode instead of crashing.

Note the distribution name passed to ``metadata.version`` is the hyphenated
``arxiv-doc-builder`` (``pyproject``'s ``[project] name``), not the underscored
import name ``arxiv_doc_builder`` — they intentionally differ.

Every failure degrades to ``"unknown"`` rather than propagating, so
``read_version`` lets no ``Exception`` out and returns nothing but a ``str``,
regardless of how the code was reached. An unexpected metadata-resolution
error (corrupt installed distribution) is absorbed, and so is any exception
from locating, reading or parsing the fallback pyproject, or from looking up
``[project] version`` in it. A resolved value that is not a string is
replaced by ``"unknown"`` as well: a ``[project] version`` written as a TOML
number, or the ``None`` that ``importlib.metadata.version`` was observed to
return, on Python 3.11, 3.13 and 3.14, for a distribution with no ``Version``
field.
``tomllib`` is always available because ``requires-python`` is ``>=3.11``.
"""

import tomllib
from pathlib import Path

# Distribution name from pyproject's [project] name. A literal, not derived
# from __package__, so a rename surfaces as a lookup miss instead of a wrong
# answer (see the dist-name/import-name pitfall in the design notes).
_DIST_NAME = "arxiv-doc-builder"

_UNKNOWN = "unknown"


def read_version() -> str:
    """Return the package version, or ``"unknown"`` if unresolvable."""
    try:
        from importlib import metadata

        try:
            return _str_or_unknown(metadata.version(_DIST_NAME))
        except metadata.PackageNotFoundError:
            # No dist-info — the common source-tree case. Fall through.
            return _version_from_pyproject()
    except Exception:
        # Any other resolution failure (e.g. corrupt or unparseable
        # installed metadata) is an unexpected state, not the "not
        # installed" signal — degrade straight to "unknown" rather than
        # trusting the pyproject fallback.
        # The import is inside the outer try as well, so an import failure
        # degrades the same way.
        return _UNKNOWN


def _version_from_pyproject() -> str:
    """Read ``[project] version`` from the sibling ``pyproject.toml``.

    Walks up from this module to the package root's parent, where the project's
    pyproject lives. Any exception from locating, reading or parsing it, or
    from looking up the key, and a value that is not a string, collapse to
    ``"unknown"``.
    """
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as f:
            version = tomllib.load(f)["project"]["version"]
    except Exception:
        return _UNKNOWN
    return _str_or_unknown(version)


def _str_or_unknown(value: object) -> str:
    return value if isinstance(value, str) else _UNKNOWN
