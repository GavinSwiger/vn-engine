"""The build's plugin import scan (F42 ``04-technical.md`` §3.1, PR-F42-06, SEC-F42-03;
``07`` I-4).

Why this module exists: a built game has no Python installation, only the modules PyInstaller
put in ``_internal``. A plugin in ``minigames/`` may use any standard-library module, so the
build has to know which ones to bundle, and it has to stop when a plugin needs a package that
isn't there (``numpy``), because the built game would fail on the player's PC. The build child
never runs author code (SEC-F42-03), so the plugins are read as text and parsed with ``ast``;
nothing is imported, compiled to bytecode or executed.

``scan_imports(game_root)`` walks the real ``minigames/`` folder (no link, junction or reparse
point is followed; hidden names and ``__pycache__`` are skipped, as the copy leaves them out)
and returns a ``PluginScan``:

- ``modules``: the standard-library modules the plugins import, as dotted names for the spec's
  ``hiddenimports`` (``from email import mime`` gives ``email`` and ``email.mime``; a submodule
  is added only when it exists as a file in the standard library, checked without importing).
- ``foreign``: the first import, in file then line order, that a build can't include, as
  ``PluginImport(ref, module, line)`` for ``B_PLUGIN_IMPORT`` ("minigames/<ref> uses
  <module>"). Not foreign (I-4): relative imports, ``engine`` and ``engine.*``, ``pygame`` and
  ``pygame.*`` (every build ships pygame-ce; main session 2026-11-02),
  ``_vn_minigames.*`` (the loader's package), and the plugins' own top-level names (a
  sibling ``minigames/foo.py`` or ``minigames/foo/``).
- ``skipped``: refs not scanned because they are over F23's 1 MiB file cap, aren't UTF-8 or
  don't parse. The build's check step reports those files (F23's loader refuses them), so a
  syntax error is a check message, never a crash here.

Standard-library modules that builds leave out (``tkinter`` and the modules built on it, plus
the installer and test packages) count as foreign: the plugin would fail in the built game.

Child-only (imported by the ``build`` handler); imports ``core`` and the standard library.
"""

import ast
import os
import stat
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core import paths, safefile

FOLDER: Final = "minigames"
MAX_FILE_BYTES: Final = 1 << 20          # F23's per-file cap (minigames/loader.py)
MAX_TOTAL_BYTES: Final = 8 << 20         # F23's source total
MAX_DEPTH: Final = 32                    # the build's folder depth cap (B_TOO_BIG)

# Always allowed top-level names besides the plugins' own (07 I-4); pygame ships in every build.
ALLOWED_TOP: Final = frozenset({"engine", "_vn_minigames", "pygame"})

# In the standard library but not in a build (the spec excludes tkinter; the rest are
# installers, IDLE and the test suite, which builds never bundle).
NOT_BUNDLED: Final = frozenset({"tkinter", "_tkinter", "turtle", "turtledemo", "idlelib",
                                "ensurepip", "venv", "test", "lib2to3", "pydoc_data"})

_SKIPPED_NAMES: Final = frozenset({"__pycache__"})
_REPARSE_POINT: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True, slots=True)
class PluginImport:
    """A top-level import a build can't include: ``ref`` is relative to ``minigames/``
    (``/`` separators), ``module`` the top-level name, ``line`` 1-based."""

    ref: str
    module: str
    line: int


@dataclass(frozen=True, slots=True)
class PluginScan:
    modules: tuple[str, ...] = ()
    foreign: PluginImport | None = None
    skipped: tuple[str, ...] = ()


def scan_imports(game_root: Path) -> PluginScan:
    """Scan the real ``<game_root>/minigames/**.py``; see the module docstring. A missing or
    linked ``minigames`` folder gives an empty scan (the copy leaves a link out)."""
    folder = Path(game_root) / FOLDER
    if not _is_real_dir(folder):
        return PluginScan()
    files = _real_py_files(folder)
    siblings = _own_names(folder)
    modules: set[str] = set()
    skipped: list[str] = []
    total = 0
    for ref, path in files:
        text = _read_text(path)
        if text is None or total + len(text) > MAX_TOTAL_BYTES:
            skipped.append(ref)
            continue
        total += len(text)
        try:
            tree = ast.parse(text, filename=f"<minigames/{ref}>")
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            skipped.append(ref)
            continue
        for line, dotted in _imports(tree):
            top = dotted.split(".", 1)[0]
            if top in ALLOWED_TOP:
                continue
            if top in sys.stdlib_module_names and top not in NOT_BUNDLED:
                modules.update(_bundle_names(dotted))     # even if a plugin shares the name
                continue
            if top in siblings:
                continue
            return PluginScan(tuple(sorted(modules)), PluginImport(ref, top, line),
                              tuple(skipped))
    return PluginScan(tuple(sorted(modules)), None, tuple(skipped))


def _real_py_files(folder: Path) -> list[tuple[str, Path]]:
    """``(ref, path)`` of every real ``.py`` file under ``folder``, sorted by ref; links,
    hidden names and ``__pycache__`` are not entered. Iterative, depth-capped."""
    found: list[tuple[str, Path]] = []
    stack: list[tuple[Path, tuple[str, ...]]] = [(folder, ())]
    while stack:
        current, parts = stack.pop()
        try:
            with os.scandir(current) as entries:
                listed = [(entry.name, paths.dir_entry_kind(entry)) for entry in entries]
        except OSError:
            continue
        for name, kind in listed:
            if name.startswith(".") or name in _SKIPPED_NAMES:
                continue
            if kind == paths.ENTRY_DIR and len(parts) < MAX_DEPTH:
                stack.append((current / name, (*parts, name)))
            elif kind == paths.ENTRY_FILE and name.casefold().endswith(".py"):
                found.append(("/".join((*parts, name)), current / name))
    found.sort(key=lambda item: item[0])
    return found


def _is_real_dir(path: Path) -> bool:
    """A real folder by ``lstat``: not a link, junction or other reparse point."""
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISDIR(st.st_mode) and not (
        getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _own_names(folder: Path) -> frozenset[str]:
    """The plugins' top-level module names: ``foo`` for ``foo.py`` and for a folder ``foo``."""
    names: set[str] = set()
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                kind = paths.dir_entry_kind(entry)
                if kind == paths.ENTRY_DIR:
                    names.add(entry.name)
                elif kind == paths.ENTRY_FILE and entry.name.casefold().endswith(".py"):
                    names.add(entry.name[:-3])
    except OSError:
        pass
    return frozenset(name for name in names if name.isidentifier())


def _read_text(path: Path) -> str | None:
    result = safefile.read_regular(path, MAX_FILE_BYTES)
    if not result.ok or result.data is None:
        return None
    try:
        return result.data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return None


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, dotted name)`` of every absolute import, in source order. ``from a.b import
    c`` gives ``a.b`` and ``a.b.c`` (the second is kept only if it is a real submodule, by
    ``_bundle_names``). Relative imports (level > 0) are the plugin's own package."""
    found: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, node.col_offset, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.append((node.lineno, node.col_offset, node.module))
            found.extend((node.lineno, node.col_offset, f"{node.module}.{alias.name}")
                         for alias in node.names if alias.name != "*")
    found.sort()
    return [(line, name) for line, _, name in found]


def _bundle_names(dotted: str) -> list[str]:
    """The top-level name, plus each longer prefix of ``dotted`` that is a real module or
    package file in the standard library (``os.path`` isn't one; ``xml.etree.ElementTree``
    is). Checked on disk; nothing is imported."""
    parts = dotted.split(".")
    names = [parts[0]]
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    for end in range(2, len(parts) + 1):
        base = stdlib.joinpath(*parts[:end])
        if (base / "__init__.py").is_file() or base.with_name(parts[end - 1] + ".py").is_file():
            names.append(".".join(parts[:end]))
        else:
            break
    return names


__all__ = ["ALLOWED_TOP", "FOLDER", "NOT_BUNDLED", "PluginImport", "PluginScan",
           "scan_imports"]
