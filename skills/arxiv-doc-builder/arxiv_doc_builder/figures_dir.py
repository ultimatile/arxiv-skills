"""The ``figures/`` directory ``convert-paper`` keeps beside a paper's document.

A LaTeX conversion started by ``convert-paper`` replaces the directory, and
the PDF fallback removes it, both through ``remove_figures_dir``.
"""

import shutil
import sys
from pathlib import Path


def figures_dir_in(directory: Path) -> Path:
    """The ``figures/`` directory of the document written into ``directory``."""
    return directory / "figures"


def exit_if_symlink(figures_dir: Path) -> None:
    """Exit with status 1 when ``figures_dir`` is a symbolic link, dangling or not.

    The reason goes to stderr.
    """
    if figures_dir.is_symlink():
        print(
            f"Error: {figures_dir} is a symbolic link. A conversion replaces "
            "or removes this directory, and a link cannot be removed that "
            "way. Remove the link and run again.",
            file=sys.stderr,
        )
        sys.exit(1)


def remove_figures_dir(figures_dir: Path) -> bool:
    """Remove ``figures_dir`` with everything in it.

    Returns whether there was anything to remove. Raises OSError when the
    removal fails, as it does when ``figures_dir`` is a symbolic link.
    """
    # exists() is false for a dangling link, so is_symlink() is what sends one
    # on to rmtree.
    if not (figures_dir.is_symlink() or figures_dir.exists()):
        return False
    shutil.rmtree(figures_dir)
    return True
