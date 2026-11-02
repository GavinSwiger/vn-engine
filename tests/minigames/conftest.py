"""Loader L (F23 ``06`` §0.3): ``PluginLoadJob`` stepped to the end in-process on a
``minigames/`` folder each test builds, inside an import sandbox.

``import_sandbox`` (autouse) snapshots and fully restores ``sys.meta_path``, ``sys.path``,
``sys.path_hooks``, ``sys.path_importer_cache``, every ``sys.modules`` entry under
``_vn_minigames``, ``linecache.cache``, ``sys.dont_write_bytecode``, and the API's registry
slot, so no test leaves import state changed. ``load`` also runs §0.4's "every Loader L row"
checks: the game folder's tree is unchanged, ``sys.path`` and ``sys.path_importer_cache`` are
unchanged, no new module outside ``_vn_minigames*`` comes from the game folder, and no
message or record names a full path.
"""

import linecache
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.minigames import api
from engine.minigames.loader import PREFIX, PluginLoadJob, PluginLoadResult
from engine.runtime.guard import NO_GUARD

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "F23" / "plugins"


def _prefixed(name: str) -> bool:
    return name == PREFIX or name.startswith(PREFIX + ".")


@pytest.fixture(autouse=True)
def import_sandbox(tmp_path):
    meta_path = list(sys.meta_path)
    path = list(sys.path)
    hooks = list(sys.path_hooks)
    importer_cache = dict(sys.path_importer_cache)
    modules = {k: v for k, v in sys.modules.items() if _prefixed(k)}
    # An earlier in-process App launch (its plugin phase) may have left ``_vn_minigames``
    # behind; each row starts without it (restored below), so its own load is what it sees.
    for name in modules:
        del sys.modules[name]
    known = set(sys.modules)
    lines = dict(linecache.cache)
    bytecode = sys.dont_write_bytecode
    registry = api._registry
    try:
        yield
    finally:
        sys.meta_path[:] = meta_path
        sys.path[:] = path
        sys.path_hooks[:] = hooks
        sys.path_importer_cache.clear()
        sys.path_importer_cache.update(importer_cache)
        for name in [k for k in sys.modules if _prefixed(k)]:
            del sys.modules[name]
        sys.modules.update(modules)
        temp = os.path.normcase(str(tmp_path))
        for name in set(sys.modules) - known:      # anything planted under tmp_path
            origin = getattr(getattr(sys.modules[name], "__spec__", None), "origin", None)
            if type(origin) is str and os.path.normcase(origin).startswith(temp):
                del sys.modules[name]
        linecache.cache.clear()
        linecache.cache.update(lines)
        sys.dont_write_bytecode = bytecode
        api._set_registry(registry)


def write(game: Path, rel: str, text: str | bytes) -> Path:
    """A file under the game folder, with LF line ends (bytes are written as given)."""
    path = game / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path


def plugin(name: str, *, body: str = "", extra: str = "") -> str:
    """A one-minigame plugin source registering ``name``."""
    return ("from engine.minigames.api import Arg, Minigame, Outcome, register\n"
            f"{extra}"
            "@register\n"
            "class Game(Minigame):\n"
            f"    name = {name!r}\n"
            f"{body}")


def tree(game: Path) -> list[tuple[str, int, int]]:
    """(relative path, size, mtime_ns) of everything under the game folder, links not
    followed."""
    found = []
    for folder, dirs, files in os.walk(game):
        for name in dirs + files:
            full = Path(folder) / name
            st = full.lstat()
            found.append((full.relative_to(game).as_posix(), st.st_size, st.st_mtime_ns))
    return sorted(found)


@dataclass
class Loaded:
    result: PluginLoadResult
    records: list[logging.LogRecord]
    job: PluginLoadJob

    @property
    def errors(self) -> list[str]:
        return [e.format() for e in self.result.errors]

    @property
    def codes(self) -> list[str]:
        return [e.code for e in self.result.errors]

    def warnings(self, code: str | None = None) -> list[str]:
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING
                and (code is None or getattr(r, "code", None) == code)]

    def infos(self) -> list[str]:
        return [r.getMessage() for r in self.records if r.levelno == logging.INFO]

    @property
    def names(self) -> list[str]:
        return list(self.result.signatures())


@pytest.fixture
def game(tmp_path) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    return root.resolve()


@pytest.fixture
def load(caplog):
    """``load(game, dev=True, guard=NO_GUARD)``: run the plugin phase with every Loader L
    check."""
    caplog.set_level(logging.DEBUG, logger="vn.plugin")

    def run(game: Path, *, dev: bool = True, guard=NO_GUARD, paths: GamePaths | None = None,
            check_tree: bool = True) -> Loaded:
        before = tree(game)
        sys_path = list(sys.path)
        importer_cache = dict(sys.path_importer_cache)
        known = set(sys.modules)
        caplog.clear()
        job = PluginLoadJob(paths or GamePaths.for_game(game), guard, dev=dev,
                            log=logging.getLogger("vn.plugin"))
        result = job.run()
        records = [r for r in caplog.records if r.name == "vn.plugin"]
        if check_tree:
            assert tree(game) == before
        assert sys.path == sys_path
        assert sys.path_importer_cache == importer_cache
        roots = [os.path.normcase(str(game)), os.path.normcase(os.getcwd())]
        for name in set(sys.modules) - known:
            if _prefixed(name) or name.startswith("engine."):
                continue
            origin = getattr(getattr(sys.modules[name], "__spec__", None), "origin", None)
            assert not (type(origin) is str
                        and any(os.path.normcase(origin).startswith(r) for r in roots)), name
        assert PREFIX in sys.modules and sys.meta_path[0] is job.finder
        private = [str(game), str(game.parent), str(game).replace("\\", "/")]
        texts = [e.format() for e in result.errors]
        texts += [r.getMessage() for r in records]
        texts += [r.exc_text for r in records if r.exc_text]
        for text in texts:
            assert not any(p in text for p in private), text
        return Loaded(result, records, job)

    return run
