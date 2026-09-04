"""The package/script import pairs stay usable in both configurations.

Several modules are reachable two ways. They import their siblings through the
installed package, falling back on ``ModuleNotFoundError`` to a bare sibling
import for when the file runs as a script.

The rest of the suite exercises only the package branch, leaving two failures
invisible. A name added to one branch and not the other surfaces as a
``NameError`` whenever the missing name is first used. A wrong sibling module
name surfaces as an ``ImportError`` on the bare-script path alone. The static
check below catches the first, the executing one the second.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import arxiv_doc_builder

_PACKAGE_DIR = Path(arxiv_doc_builder.__file__).parent
_PACKAGE = arxiv_doc_builder.__name__


def _import_pair(tree: ast.Module):
    """The (package-branch, fallback-branch) imports of a dual-import ``try``.

    Returns ``None`` for a module that carries no such pair, so the discovery
    below stays a scan instead of a hardcoded list. A module that grows the
    pattern later is covered without editing this file.
    """
    for node in tree.body:
        if not isinstance(node, ast.Try):
            continue
        primary = [
            n
            for n in node.body
            if isinstance(n, ast.ImportFrom)
            and (n.module or "").startswith(f"{_PACKAGE}.")
        ]
        if not primary:
            continue
        fallback = [
            n for h in node.handlers for n in h.body if isinstance(n, ast.ImportFrom)
        ]
        return primary, fallback
    return None


def _modules_with_import_pair():
    found = []
    for path in sorted(_PACKAGE_DIR.glob("*.py")):
        pair = _import_pair(ast.parse(path.read_text(encoding="utf-8")))
        if pair is not None:
            found.append(pytest.param(path, pair, id=path.stem))
    return found


_DUAL_IMPORT_MODULES = _modules_with_import_pair()


def test_the_scan_found_the_dual_import_modules():
    # A scan that silently matched nothing would make every parametrized test
    # below vacuous.
    assert _DUAL_IMPORT_MODULES


@pytest.mark.parametrize(("path", "pair"), _DUAL_IMPORT_MODULES)
def test_both_branches_import_the_same_names_from_the_same_modules(path, pair):
    primary, fallback = pair

    def names(imports):
        return {(alias.name, alias.asname) for node in imports for alias in node.names}

    def modules(imports, strip_package: bool):
        return {
            (node.module or "").removeprefix(f"{_PACKAGE}.")
            if strip_package
            else (node.module or "")
            for node in imports
        }

    assert names(primary) == names(fallback), (
        f"{path.name}: the package and script import branches name different "
        f"symbols, so one configuration would fail on a name the other has"
    )
    assert modules(primary, strip_package=True) == modules(fallback, False), (
        f"{path.name}: the script branch imports from a different module than "
        f"the package branch"
    )


# Blocks ``arxiv_doc_builder`` in the child exactly as its genuine absence
# would: the exception names the top-level package, which is what the modules'
# own ``_exc.name`` guard re-raises on when it does not match. Blocking by any
# route that names the submodule instead would trip that guard and prove
# nothing about the fallback. Filtering ``sys.path`` would also work, but it
# removes the directory the third-party dependencies live in whenever the
# package is installed there, so the fallback would fail for the wrong reason.
_BLOCK_PACKAGE = f'''
import sys


class _Block:
    def find_spec(self, name, path=None, target=None):
        if name == "{_PACKAGE}" or name.startswith("{_PACKAGE}."):
            raise ModuleNotFoundError(f"blocked {{name}}", name="{_PACKAGE}")
        return None


sys.meta_path.insert(0, _Block())
sys.path.insert(0, {str(_PACKAGE_DIR)!r})
'''


@pytest.mark.parametrize(("path", "pair"), _DUAL_IMPORT_MODULES)
def test_the_fallback_branch_actually_resolves(path, pair, tmp_path):
    # Importing the module is the whole check: the fallback branch resolves or
    # it does not. Whether it names the same symbols as the package branch is
    # the static check's job above, not something an import can observe.
    program = _BLOCK_PACKAGE + f"import {path.stem}\n"
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, (
        f"{path.name} does not import with {_PACKAGE} absent:\n{result.stderr}"
    )
