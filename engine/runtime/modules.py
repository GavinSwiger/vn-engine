"""``module(name)``: a Python module for a ``define`` (F03 ``04-technical.md`` §7.9;
SR-F03-17, 18; invariant 9(a)).

Why this module exists: a story may use Python's standard library and installed packages
(``define math = module("math")``), but never code from the game folder, the working
directory, or the engine's own repository, because that code would run with the player's
rights while looking like story content. Every import is checked here before and after it
happens. The runtime opens no file: the one question about the game folder is answered by
``game_has``, injected by ``app`` (``engine/app/loading.py``). The texts (E89, E89b, E89c)
are in ``engine/script/messages.py``.
"""

import importlib
import importlib.util
import os
import re
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path

from engine.runtime.errors import AuthorRefusal
from engine.script.suggest import suggest

_NAME_RE = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*")
_NAME_MAX = 200
_REPO_ROOT = Path(__file__).resolve().parents[2]


class ModuleRefused(AuthorRefusal):
    """A refused ``module(...)`` call: E89, E89b, or E89c (prefixed at launch)."""


def _not_text() -> ModuleRefused:
    return ModuleRefused.of("E89b")


def _not_found(name: str) -> ModuleRefused:
    return ModuleRefused.of("E89", name, suggest(name, sys.stdlib_module_names))


def _game_folder(name: str) -> ModuleRefused:
    return ModuleRefused.of("E89c", "game", name)


def _elsewhere(name: str) -> ModuleRefused:
    return ModuleRefused.of("E89c", "elsewhere", name)


def _engine(top: str) -> ModuleRefused:
    return ModuleRefused.of("E89c", "engine", top)


def _resolve(location: str) -> Path | None:
    try:
        return Path(location).resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def allowed_roots() -> list[Path]:
    """``sysconfig`` ``stdlib``, ``platstdlib``, ``purelib``, ``platlib``, and
    ``sys._MEIPASS`` when frozen."""
    paths = sysconfig.get_paths()
    found = [paths.get(key) for key in ("stdlib", "platstdlib", "purelib", "platlib")]
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and isinstance(meipass, str):
        found.append(meipass)
    roots = []
    for location in found:
        if location:
            resolved = _resolve(location)
            if resolved is not None and resolved not in roots:
                roots.append(resolved)
    return roots


def _check_spec(name: str, spec, game_root: Path | None) -> None:
    """§7.9 step 4: built-in or frozen, or every location under an allowed root and not
    under the game root, the working directory, or the repository root."""
    origin = getattr(spec, "origin", None)
    if origin in ("built-in", "frozen"):
        return
    locations = list(getattr(spec, "submodule_search_locations", None) or ())
    if origin and origin != "namespace":
        locations.append(origin)
    if not locations:
        raise _elsewhere(name)
    roots = allowed_roots()
    forbidden = [p for p in (game_root, _resolve(os.getcwd()), _REPO_ROOT) if p is not None]
    for location in locations:
        path = _resolve(location)
        if path is None:
            raise _elsewhere(name)
        if game_root is not None and _under(path, game_root):
            raise _game_folder(name)
        inside = [root for root in roots if _under(path, root)]
        if not inside:
            raise _elsewhere(name)
        # Reading of §7.9 step 4 (F03 step 5, kept in step 8; a question for the system
        # architect): "not under the working directory or the repository root" refuses a
        # module there only when the allowed root that holds it is not itself inside that
        # folder. A developer's virtual environment usually lives in the repository
        # (``.venv/Lib/site-packages`` is ``purelib``), and read literally the rule would
        # refuse every installed package there (TR-F03-10 accepts one). Loose ``.py`` files
        # in the repository, the working directory, or a ``sys.path`` entry outside the
        # allowed roots are still refused.
        for bad in forbidden:
            if _under(path, bad) and not any(_under(root, bad) for root in inside):
                raise _elsewhere(name)


def make_module(game_has: Callable[[str], bool] = lambda ref: False, *,
                game_root: Path | None = None) -> Callable[[object], object]:
    """The author-facing ``module`` function. ``game_has(ref)`` says whether the game
    folder has that file (``GamePaths.list_dir`` membership, no file opened); it is asked
    only when a name isn't found. ``game_root`` (optional) lets the origin check name the
    game folder."""

    def module(*args: object) -> object:
        if len(args) != 1 or type(args[0]) is not str:
            raise _not_text()
        name = args[0]
        if len(name) > _NAME_MAX or not _NAME_RE.fullmatch(name):
            raise ModuleRefused.of("E89", name, None)
        top = name.split(".")[0]
        if top in ("engine", "main"):
            raise _engine(top)
        try:
            spec = importlib.util.find_spec(top)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            refs = (f"{top}.py", f"{top}/__init__.py", f"script/{top}.py")
            if any(game_has(ref) for ref in refs):
                raise _game_folder(name)
            raise _not_found(name)
        _check_spec(name, spec, game_root)
        try:
            loaded = importlib.import_module(name)
        except ImportError:
            raise _not_found(name) from None
        _check_spec(name, getattr(loaded, "__spec__", None), game_root)
        return loaded

    module.__qualname__ = "module"
    return module


__all__ = ["ModuleRefused", "allowed_roots", "make_module"]
