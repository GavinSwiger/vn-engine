"""Shared fixtures of the F02 script tests.

- ``slow`` and ``perf`` tests are skipped unless ``VN_SLOW=1`` / ``VN_PERF=1`` is set or
  ``-m`` names the marker (06-acceptance §0.3; the rule is in ``tests/conftest.py``).
- ``corpus(*args)``: a ``gen_corpus.py`` corpus (06 §5.10), generated once and cached under
  the pytest cache keyed by its arguments and the generator's source.
- ``opened``: records the ``open``/``scandir`` audit events of a block (abuse conditions
  Y, 06 §0.5).
- ``game``: writes a game folder under ``tmp_path``.
"""

import contextlib
import hashlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

from engine.core.paths import GamePaths

GEN_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "F02" / "gen_corpus.py"


def load_gen_corpus():
    """``tests/fixtures/F02/gen_corpus.py`` as a module (it is not a package)."""
    spec = importlib.util.spec_from_file_location("gen_corpus", GEN_CORPUS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def corpus(request, tmp_path_factory):
    """``corpus("--words", "50000", "--files", "10", "--seed", "1")`` → the corpus folder
    (a game root holding ``script/`` and ``corpus.json``)."""
    gen = load_gen_corpus()
    source = GEN_CORPUS.read_bytes()

    def make(*args: str) -> Path:
        key = hashlib.sha256(source + b"\0" + "\0".join(args).encode()).hexdigest()[:16]
        try:
            base = Path(request.config.cache.mkdir(f"f02-corpus-{key}"))
        except (AttributeError, ValueError):
            base = tmp_path_factory.mktemp(f"corpus-{key}")
        if not (base / "corpus.json").exists():
            shutil.rmtree(base / "script", ignore_errors=True)
            gen.main([*args, "--out", str(base)])
        return base

    return make


_EVENTS = frozenset(("open", "os.scandir", "os.listdir"))


class _OpenRecorder:
    """One process-wide audit hook (hooks can't be removed); records only while active."""

    installed = False
    active: list[list[tuple[str, str]]] = []

    @classmethod
    def hook(cls, event: str, args: tuple) -> None:
        if event in _EVENTS and cls.active and args:
            target = args[0]
            if isinstance(target, os.PathLike):
                target = os.fspath(target)
            if not isinstance(target, (str, bytes)):
                return
            path = target if isinstance(target, str) else os.fsdecode(target)
            for sink in cls.active:
                sink.append((event, path))


@pytest.fixture
def opened():
    """``with opened() as events: …`` collects ``(event, path)`` for every ``open``,
    ``os.scandir``, and ``os.listdir`` audit event."""
    if not _OpenRecorder.installed:
        sys.addaudithook(_OpenRecorder.hook)
        _OpenRecorder.installed = True

    @contextlib.contextmanager
    def record():
        paths: list[tuple[str, str]] = []
        _OpenRecorder.active.append(paths)
        try:
            yield paths
        finally:
            _OpenRecorder.active.remove(paths)

    return record


def write_tree(folder: Path, files: dict[str, str | bytes | None]) -> None:
    """``{"a.vns": text, "routes/b.vns": bytes, "dir": None}`` (None = a folder)."""
    for name, content in files.items():
        path = folder / name
        if content is None:
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        path.write_bytes(content)


@pytest.fixture
def game(tmp_path):
    """``game({"main.vns": …})`` writes the files under ``<tmp>/game/script`` and returns
    the ``GamePaths``. ``game(None)`` makes a game folder with no ``script/``."""

    def make(files: dict[str, str | bytes | None] | None) -> GamePaths:
        root = tmp_path / "game"
        root.mkdir(exist_ok=True)
        if files is not None:
            (root / "script").mkdir(exist_ok=True)
            write_tree(root / "script", files)
        return GamePaths(root.resolve())

    return make
