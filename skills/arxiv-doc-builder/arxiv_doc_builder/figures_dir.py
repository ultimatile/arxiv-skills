"""The record of which files in ``figures/`` a LaTeX conversion copied there.

The record is what lets a later conversion remove those files and no others.
"""

import json
import sys
from collections.abc import Iterable
from pathlib import Path

RECORD_NAME = ".copied.json"


def figures_dir_in(directory: Path) -> Path:
    """The ``figures/`` directory of the document written into ``directory``."""
    return directory / "figures"


def _record_in(figures_dir: Path) -> Path:
    return figures_dir / RECORD_NAME


def _recorded_names(figures_dir: Path) -> list[str]:
    """The file names the record in ``figures_dir`` lists.

    Empty when there is no record. A record that cannot be read or is not of
    the written shape also gives none, after a warning on stderr. An entry
    that contains a path separator, or that names the record, is dropped.
    """
    record = _record_in(figures_dir)
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RecursionError) as e:
        print(
            f"Warning: {record} cannot be read ({type(e).__name__}), so the "
            f"figures copied earlier stay in {figures_dir}.",
            file=sys.stderr,
        )
        return []
    names = data.get("copied") if isinstance(data, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        print(
            f"Warning: {record} is not a record of copied figures, so the "
            f"figures copied earlier stay in {figures_dir}.",
            file=sys.stderr,
        )
        return []
    return [n for n in names if n == Path(n).name and n != RECORD_NAME]


def remove_recorded_figures(figures_dir: Path) -> int:
    """Remove the files the record in ``figures_dir`` names; return how many.

    A recorded name that is not a file there is passed over.
    """
    removed = 0
    for name in _recorded_names(figures_dir):
        path = figures_dir / name
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def record_figures(figures_dir: Path, names: Iterable[str]) -> None:
    """Write the record in ``figures_dir``, naming ``names``."""
    _record_in(figures_dir).write_text(
        json.dumps({"copied": sorted(names)}, indent=2) + "\n", encoding="utf-8"
    )


def discard_recorded_figures(figures_dir: Path) -> int:
    """Remove the recorded files and the record; return how many files went.

    Does nothing where there is no record file.
    """
    record = _record_in(figures_dir)
    if not record.is_file():
        return 0
    removed = remove_recorded_figures(figures_dir)
    record.unlink()
    return removed
