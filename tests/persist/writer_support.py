"""Helpers for the writer tests (F12 checklist step 4): a fake clock and sleep, fault
injection by predicate, spies on ``safefile.write_atomic``, gates that hold a write on the
writer thread, and a fixture that ends every writer thread in teardown. Stdlib only.

Faults are injected by patching ``os`` calls inside ``engine.core.safefile`` (the same
``os`` module the writer uses) within ``monkeypatch.context()`` (06 §0.2 "FS faults")."""

import os
import threading
from pathlib import Path

import pytest

from engine.core import safefile
from engine.persist.writer import Writer

OLD = b'{"old":1}'
NEW = b'{"new":2}'
JOIN_TIMEOUT_S = 10.0


class FakeClock:
    """Monotonic seconds that move only by ``advance`` or, with ``step``, by ``step`` on
    every read (so a wait against a deadline ends after a bounded number of reads)."""

    def __init__(self, start: float = 100.0, step: float = 0.0) -> None:
        self.now = start
        self.step = step
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        now = self.now
        self.now += self.step
        return now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSleep(list):
    """Records the delays the writer asks for; never sleeps."""

    def __call__(self, seconds: float) -> None:
        self.append(seconds)


def fail_when(real, when, exc_factory, *, times: int | None = None):
    """A stand-in for ``real`` that raises ``exc_factory()`` when ``when(*args)`` holds,
    at most ``times`` times (None: always)."""
    left = [times]

    def call(*args, **kwargs):
        if when(*args) and (left[0] is None or left[0] > 0):
            if left[0] is not None:
                left[0] -= 1
            raise exc_factory()
        return real(*args, **kwargs)
    return call


def oserror(code: int, filename: str | None = None):
    return lambda: OSError(code, os.strerror(code), filename)


def is_temp(path, *_rest) -> bool:
    return str(path).endswith(".tmp")


def temps(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    return sorted(name for name in os.listdir(folder) if name.endswith(".tmp"))


class WriteSpy:
    """Wraps ``safefile.write_atomic``: the target names in call order, the thread of each
    call, and the most calls ever running at once."""

    def __init__(self) -> None:
        self.real = safefile.write_atomic
        self.names: list[str] = []
        self.threads: list[int] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, target, pieces, **kwargs):
        with self._lock:
            self.names.append(Path(target).name)
            self.threads.append(threading.get_ident())
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            return self.real(target, pieces, **kwargs)
        finally:
            with self._lock:
                self.active -= 1


class Gate:
    """Wraps ``safefile.write_all``. A write whose bytes are in ``held`` signals
    ``entered[data]`` and then blocks until released (a hung write). Records the bytes
    of every write in order."""

    def __init__(self) -> None:
        self.real = safefile.write_all
        self.order: list[bytes] = []
        self.held: dict[bytes, threading.Event] = {}
        self.entered: dict[bytes, threading.Event] = {}

    def hold(self, data: bytes) -> None:
        self.held[data] = threading.Event()
        self.entered[data] = threading.Event()

    def release(self, data: bytes | None = None) -> None:
        for key, event in self.held.items():
            if data is None or key == data:
                event.set()

    def __call__(self, fd: int, data: bytes) -> None:
        data = bytes(data)
        self.order.append(data)
        if data in self.held:
            self.entered[data].set()
            self.held[data].wait(JOIN_TIMEOUT_S)
        self.real(fd, data)


class HungFsync:
    """Replaces ``os.fsync``: off the main thread it blocks until released (an fsync
    "sleeping past the deadline"); the main thread's fsyncs pass straight through."""

    def __init__(self) -> None:
        self.real = os.fsync
        self.entered = threading.Event()
        self.go = threading.Event()

    def __call__(self, fd: int) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.entered.set()
            self.go.wait(JOIN_TIMEOUT_S)
        self.real(fd)


@pytest.fixture
def writers():
    """``make(**kwargs) -> Writer``; ``make.release`` collects events/gates to open in
    teardown. Every writer thread is ended (joined) before the test is over."""
    made: list[Writer] = []
    releases: list = []

    def make(**kwargs) -> Writer:
        writer = Writer(**kwargs)
        made.append(writer)
        return writer

    make.release = releases.append
    yield make
    for release in releases:
        release()
    for writer in made:
        thread = writer._thread
        if thread is None:
            continue
        with writer._cond:
            writer._stopping = True
            writer._cond.notify_all()
        thread.join(JOIN_TIMEOUT_S)
        assert not thread.is_alive(), "a writer thread outlived its test"


@pytest.fixture
def base(tmp_path) -> Path:
    """``tmp_path`` by its real path (macOS temp folders are reached through a link)."""
    return tmp_path.resolve()


@pytest.fixture
def game(base) -> Path:
    folder = base / "game"
    folder.mkdir()
    return folder


@pytest.fixture
def root(game) -> Path:
    """``<game>/persistent`` holding OLD as ``persistent.json``."""
    folder = game / "persistent"
    folder.mkdir()
    (folder / "persistent.json").write_bytes(OLD)
    return folder


@pytest.fixture
def outside(base) -> Path:
    folder = base / "outside"
    folder.mkdir()
    return folder


def link_dir(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows, a symlink elsewhere; skips if not allowed."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory links not permitted here: {exc}")


def tree(folder: Path) -> dict[str, bytes | None]:
    """Every entry under ``folder``: file bytes, or None for a folder."""
    out: dict[str, bytes | None] = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        for name in dirnames:
            out[os.path.relpath(os.path.join(dirpath, name), folder)] = None
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, folder)] = fh.read()
    return out
