"""The real mixer for F08's ``integration (mixer)`` ACs (``06`` §0.2, §0.6; ``04`` §15; G11).

``disk`` opens ``PygameMixer`` on SDL's **disk** audio driver, so the output can be compared
sample by sample. pygame-ce 2.5.8 ignores ``SDL_DISKAUDIOFILE`` (``06`` §0.6 item 1), so each
test runs with a fresh output folder as its working directory and reads the one file SDL
wrote there. ``SDL_DISKAUDIODELAY=1`` runs the device about 6× faster than real time (``delay=0``, for
tests that only play and wait, about 300×), and the
service's clock is **audio time**: the bytes written so far over 192,000 bytes per second
(48 kHz, stereo, 16-bit). Timers, ramps, and the watchdog therefore follow what was mixed,
not the wall clock, and a 3 s scenario takes about half a second. Only the display is
initialized (SDL posts music-end events only while video is up), never ``pygame.init()``,
which would open the mixer with SDL's defaults first.

``dummy`` builds a real ``AudioService`` on SDL's **dummy** driver instead, on the wall
clock: for tests that reopen the mixer (the disk driver starts a new file at each open) or
only look at what was decoded (``settle`` runs frames until no decode is in flight).

Timing rule (test-review-F08.md): the Python thread can be descheduled for many buffers
under load, so a test that acts "0.5 s in" reads ``clock()`` after it acts and measures the
output from that moment, never from when it meant to act.

Under pytest-xdist every ``mixer``-marked test (here and elsewhere, e.g.
``test_example_audio.py``) gets ``xdist_group("mixer")``, so ``--dist loadgroup`` runs them
all on one worker, one at a time, while the other workers run the rest.
"""

import os
import time
from array import array
from collections.abc import Callable
from pathlib import Path

import pygame
import pytest

from engine.app.dispatch import CommandRouter
from engine.audio.backend import PygameMixer
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths

BYTES_PER_SECOND = 48_000 * 4
RATE = 48_000
WAIT_S = 10.0                                    # a hung decode worker


@pytest.hookimpl(tryfirst=True)                  # before xdist's loadgroup reads the marks
def pytest_collection_modifyitems(config, items):
    """``xdist_group("mixer")`` on every ``mixer``-marked test (a session hook: it sees all
    collected items, not only this folder's). Grouping only; nothing is skipped here."""
    if not config.pluginmanager.hasplugin("xdist"):
        return                                   # the mark is xdist's (unknown without it)
    group = pytest.mark.xdist_group("mixer")
    loadgroup = config.getvalue("loadgroup") if hasattr(config.option, "loadgroup") else False
    for item in items:
        if item.get_closest_marker("mixer") and not item.get_closest_marker("xdist_group"):
            item.add_marker(group)
            if loadgroup and "@" not in item.nodeid and hasattr(item, "_id"):
                # xdist 3.8 groups by renaming ``item._nodeid`` to ``<id>@<group>``; pytest 9.2
                # derives ``nodeid`` from ``item._id``, so that rename has no effect and the
                # group is silently ignored. Do xdist's rename the pytest 9 way.
                item._id = type(item._id).parse(f"{item.nodeid}@mixer")


class Disk:
    """One disk-driver session: ``service`` (a real ``AudioService`` on ``backend``),
    ``clock()`` (audio seconds written), ``run_until``, then ``close()`` and ``frames()``."""

    def __init__(self, root: Path, out: Path, cfg: AudioConfig) -> None:
        self.root = root
        self.out = out
        self.backend = PygameMixer()
        written = [p for p in out.iterdir() if p.is_file()]
        assert len(written) == 1, written                       # sdlaudio.raw, or "0"
        self.file = written[0]
        self.service = AudioService(GamePaths(root.resolve()), SizedLru(256 << 20), cfg,
                                    backend=self.backend, clock=self.clock)
        self.router = CommandRouter()
        self.service.register(self.router)
        self.closed = False

    def clock(self) -> float:
        return os.path.getsize(self.file) / BYTES_PER_SECOND

    def feed(self, *commands: object) -> None:
        """Dispatch ``commands``, then run frames until no decode is in flight (step 9: an
        uncached effect or voice starts at the first ``update`` after its decode on the
        loader's worker). The clock is audio time, which at ``delay=0`` runs about 300×
        faster than the wall clock, so without this a scenario's audio budget would be
        spent while the worker decodes."""
        for command in commands:
            self.router.dispatch(command)
        self.settle()

    def settle(self) -> None:
        """Frames until the loader has no decode in flight (fails after 10 s of wall
        clock: a hung worker)."""
        loader = self.service.loader
        wall = time.perf_counter() + 10.0
        while loader.pending:
            assert time.perf_counter() < wall, "the decode worker did not answer"
            self.frame()
            time.sleep(0.0005)

    def frame(self) -> None:
        """One App frame: the events, then ``update``."""
        for event in pygame.event.get():
            self.service.handle_event(event)
        self.service.update(self.clock())

    def run_until(self, done: Callable[[], bool], *, audio_s: float) -> float:
        """Frames until ``done()`` or ``audio_s`` more seconds were mixed; the clock then.
        Fails if the wall clock passes 10 s (a hang)."""
        end = self.clock() + audio_s
        wall = time.perf_counter() + 10.0
        while not done() and self.clock() < end:
            assert time.perf_counter() < wall, "the mixer stopped advancing"
            self.frame()
            time.sleep(0.0005)
        return self.clock()

    def run(self, audio_s: float) -> float:
        return self.run_until(lambda: False, audio_s=audio_s)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.service.shutdown()

    def frames(self) -> array:
        """The whole output as interleaved signed 16-bit samples (after ``close``)."""
        self.close()
        samples = array("h")
        samples.frombytes(self.file.read_bytes())
        return samples


@pytest.fixture
def disk_session(tmp_path, monkeypatch):
    """``disk_session(cfg=…)`` opens a ``Disk`` over the game folder ``tmp_path/game`` (write
    files with ``add``); at most one per test."""
    game = tmp_path / "game"
    (game / "audio").mkdir(parents=True)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    monkeypatch.setenv("SDL_AUDIODRIVER", "disk")
    if pygame.mixer.get_init():
        pygame.mixer.quit()
    pygame.display.init()
    sessions: list[Disk] = []

    def open_session(cfg: AudioConfig | None = None, *, delay: int = 1) -> Disk:
        assert not sessions
        monkeypatch.setenv("SDL_DISKAUDIODELAY", str(delay))
        session = Disk(game, out, cfg or AudioConfig(master_volume=100, music_volume=100,
                                                      sound_volume=100))
        sessions.append(session)
        return session

    yield open_session
    for session in sessions:
        session.close()
    pygame.quit()


@pytest.fixture
def dummy(tmp_path, monkeypatch):
    """``dummy()``: a real ``AudioService`` on ``PygameMixer`` over SDL's dummy driver and
    its router, over the game folder ``dummy.root``; shut down after."""
    root = tmp_path / "game"
    (root / "audio").mkdir(parents=True)
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    if pygame.mixer.get_init():
        pygame.mixer.quit()
    pygame.display.init()
    made: list[AudioService] = []

    def build() -> tuple[AudioService, CommandRouter]:
        service = AudioService(GamePaths(root.resolve()), SizedLru(256 << 20),
                               AudioConfig(master_volume=100, music_volume=100,
                                           sound_volume=100),
                               backend=PygameMixer(), clock=time.perf_counter)
        router = CommandRouter()
        service.register(router)
        made.append(service)
        return service, router

    build.root = root
    yield build
    for service in made:
        service.shutdown()
    pygame.quit()


def settle(service: AudioService) -> None:
    """Frames until no decode is in flight (bounded)."""
    wall = time.perf_counter() + WAIT_S
    while service.loader.pending:
        assert time.perf_counter() < wall, "the decode worker did not answer"
        service.loader.wait(0.05)
        service.update(time.perf_counter())


def add(root: Path, file: str, data: bytes) -> None:
    path = root / "audio" / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def regions(left: array, *, threshold: int, gap_s: float = 0.2,
            min_s: float = 0.05) -> list[tuple[int, int]]:
    """``(first, last)`` frame of each stretch of ``left`` (one channel) louder than
    ``threshold``, split at silences of ``gap_s`` or more; stretches shorter than ``min_s``
    are left out (the device's first buffer can hold a few frames left over from an
    earlier mixer session in the same process). Scans 10 ms chunks with the C-speed
    ``max``/``min`` first."""
    chunk = RATE // 100
    loud_chunks = [c for c in range(0, len(left), chunk)
                   if max(left[c:c + chunk], default=0) > threshold
                   or min(left[c:c + chunk], default=0) < -threshold]
    found: list[tuple[int, int]] = []
    for c in loud_chunks:
        part = left[c:c + chunk]
        first = c + next(i for i, v in enumerate(part) if abs(v) > threshold)
        last = c + max(i for i, v in enumerate(part) if abs(v) > threshold)
        if found and first - found[-1][1] < gap_s * RATE:
            found[-1] = (found[-1][0], last)
        else:
            found.append((first, last))
    return [(a, b) for a, b in found if b - a >= min_s * RATE]


def find_all(haystack: bytes, needle: bytes) -> list[int]:
    """Every frame index (4 bytes) where ``needle`` starts in ``haystack``."""
    found, at = [], haystack.find(needle)
    while at >= 0:
        if at % 4 == 0:
            found.append(at // 4)
        at = haystack.find(needle, at + 1)
    return found
