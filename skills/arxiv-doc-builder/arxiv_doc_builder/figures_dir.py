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


def read_record(figures_dir: Path) -> list[str] | None:
    """The file names the record in ``figures_dir`` lists, or None without one.

    A record that cannot be read or is not of the written shape gives an
    empty list, after a warning on stderr. An entry that is empty, is ``.``
    or ``..``, contains a path separator, or names the record is dropped.
    """
    record = _record_in(figures_dir)
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return None
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
    return [n for n in names if n == Path(n).name and n not in ("", "..", RECORD_NAME)]


def record_figures(figures_dir: Path, names: Iterable[str]) -> None:
    """Write the record in ``figures_dir``, naming ``names``."""
    _record_in(figures_dir).write_text(
        json.dumps({"copied": sorted(names)}, indent=2) + "\n", encoding="utf-8"
    )


def remove_figure(figures_dir: Path, name: str) -> bool:
    """Remove the file ``name`` from ``figures_dir``; return whether it was there.

    A name that is not a file there is passed over.
    """
    path = figures_dir / name
    if not path.is_file():
        return False
    path.unlink()
    return True


def discard_recorded_figures(figures_dir: Path) -> int:
    """Remove the recorded files and the record; return how many files went.

    ``figures_dir`` itself is removed when it is then empty, unless it is a
    symbolic link. Does nothing where there is no record.
    """
    recorded = read_record(figures_dir)
    if recorded is None:
        return 0
    removed = sum(remove_figure(figures_dir, name) for name in recorded)
    _record_in(figures_dir).unlink()
    if not figures_dir.is_symlink() and not any(figures_dir.iterdir()):
        figures_dir.rmdir()
    return removed
