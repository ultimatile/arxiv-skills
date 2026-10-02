"""The ``figures/`` directory a conversion keeps beside its document.

A LaTeX conversion replaces the directory and the PDF fallback removes it,
both through ``remove_figures_dir``.
"""

import shutil
from collections.abc import Iterable
from pathlib import Path


def figures_dir_in(directory: Path) -> Path:
    """The ``figures/`` directory of the document written into ``directory``."""
    return directory / "figures"


def _dirs_overlap(first: Path, second: Path) -> bool:
    """Whether two directories, once resolved, are the same or nested."""
    a, b = first.resolve(), second.resolve()
    return a == b or a in b.parents or b in a.parents


def check_figures_dir(figures_dir: Path, input_dirs: Iterable[Path]) -> None:
    """Raise ValueError when ``figures_dir`` overlaps one of ``input_dirs``.

    Removing ``figures_dir`` would then delete files in that directory. The
    message names both directories and is written for the user.
    """
    for input_dir in input_dirs:
        if _dirs_overlap(figures_dir, input_dir):
            raise ValueError(
                f"A conversion replaces or removes {figures_dir}, but it "
                f"overlaps {input_dir}, which holds the files to convert. "
                "Keep the two directories apart and run again."
            )


def remove_figures_dir(figures_dir: Path, input_dirs: Iterable[Path]) -> bool:
    """Remove ``figures_dir`` with everything in it.

    Returns whether there was anything to remove.

    Raises as ``check_figures_dir`` does, before removing anything. Otherwise
    raises OSError when ``figures_dir`` is itself a symbolic link, dangling or
    not, and leaves the link and whatever is behind it in place.
    """
    check_figures_dir(figures_dir, input_dirs)
    # exists() is false for a dangling link, so is_symlink() is what sends one
    # to rmtree, which refuses a path that is a link.
    if not (figures_dir.is_symlink() or figures_dir.exists()):
        return False
    # No ignore_errors: a removal that fails must not pass for a removal.
    shutil.rmtree(figures_dir)
    return True
