"""Service S (F08 ``06`` §0.5): ``AudioService(paths, cache, cfg, backend=FakeMixer(),
clock=FakeClock())`` over a game folder in ``tmp_path`` holding Template A's effect files
(synthetic bytes that pass ``sniff``, registered with the FakeMixer by name and length).

The FakeMixer's decode costs nothing, so the service's ``SoundLoader`` decodes in the calling
thread and every sound plays when its command arrives. ``make_service(..., threaded=True)``
gives the loader its worker (F08 step 9); ``decoded()`` then waits (bounded) for the
decodes in flight and runs the ``update`` that plays them.

The mixer is a ``BlipMixer``: ``tests/fakes``' ``FakeMixer`` plus the two raw-sample calls F06
step 2 added to ``MixerBackend`` (``sound_raw``, ``sound_from_raw``) for the blip variants."""

from pathlib import Path

import pytest

from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from tests.fakes.fake_mixer import FakeMixer, FakeSound, ogg_bytes
from tests.fakes.loop import FakeClock

# Template A's audio (06 §0.4): file -> seconds.
TEMPLATE_AUDIO = {
    "bgm/festival.ogg": 12.0, "bgm/festival_muffled.ogg": 12.0, "bgm/omen.ogg": 3.0,
    "bgm/shrine_steps.ogg": 4.0, "sfx/door.ogg": 0.5, "sfx/rain.ogg": 2.0,
    "sfx/crowd.ogg": 2.0, "sfx/firework.ogg": 1.0, "voice/hana_014.ogg": 1.5,
    "voice/hana_015.ogg": 1.5, "voice/hana_041.ogg": 1.5,
}
CACHE_BYTES = 256 * 1_048_576
RATE = 48_000


class BlipMixer(FakeMixer):
    """``FakeMixer`` with F06's raw samples: a FakeSound's samples are silent 16-bit frames
    of its length at 48 kHz in the mixer's channel count (2; 1 after a mono reopen), and a
    Sound made of samples is ``raw:<frames>``, lasting their length."""

    def sound_raw(self, sound: FakeSound) -> bytes:
        self._record("sound_raw", sound.name)
        return bytes(round(sound.seconds * RATE) * 2 * self.channels)

    def sound_from_raw(self, raw: bytes) -> FakeSound:
        frames = len(raw) // (2 * self.channels)
        self._record("sound_from_raw", frames)
        return FakeSound(f"raw:{frames}", frames / RATE)


class ServiceS:
    """One Service S: ``service``, ``mixer``, ``clock``, ``cache``, ``root``, and ``feed``
    (each command through the router, as a burst)."""

    def __init__(self, root: Path, cfg: AudioConfig, *, paths: bool = True,
                 threaded: bool | None = None, cache_bytes: int = CACHE_BYTES) -> None:
        from engine.app.dispatch import CommandRouter

        self.root = root
        self.clock = FakeClock(start=100.0)
        self.mixer = BlipMixer(clock=self.clock)
        self.cache: SizedLru = SizedLru(cache_bytes)
        self.frame = 1
        self.service = AudioService(GamePaths(root.resolve()) if paths else None, self.cache,
                                    cfg, backend=self.mixer, clock=self.clock,
                                    frame=lambda: self.frame, loader_threaded=threaded)
        self.router = CommandRouter()
        self.service.register(self.router)

    def add(self, file: str, data: bytes, seconds: float | None = None) -> None:
        path = self.root / "audio" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if seconds is not None:
            self.mixer.register(data, file, seconds)

    def feed(self, *commands: object) -> None:
        for command in commands:
            self.router.dispatch(command)

    def pump(self) -> None:
        """The frame's events: the FakeMixer's posted music-end events reach
        ``handle_event`` (which must consume them)."""
        for event in self.mixer.take_events():
            assert self.service.handle_event(event)

    def advance(self, seconds: float) -> None:
        """Time passes and one frame runs: its events, then ``update``."""
        self.clock.now = round(self.clock.now + seconds, 9)     # steps land exactly
        self.frame += 1
        self.pump()
        self.service.update(self.clock())

    def decoded(self, timeout: float = 5.0) -> None:
        """Wait (at most ``timeout`` seconds per result) until no decode is in flight, then
        run the ``update`` that plays them (no time passes)."""
        loader = self.service.loader
        while loader.pending:
            assert loader.wait(timeout), "the decode worker did not answer"
            self.service.update(self.clock())

    def run(self, seconds: float, step: float = 0.01) -> None:
        """Frames of ``step`` seconds for ``seconds``."""
        end = self.clock.now + seconds
        while self.clock.now < end - 1e-9:
            self.advance(min(step, end - self.clock.now))


def make_service(tmp_path: Path, cfg: AudioConfig | None = None, *,
                 paths: bool = True, threaded: bool | None = None,
                 cache_bytes: int = CACHE_BYTES) -> ServiceS:
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    s = ServiceS(root, cfg or AudioConfig(), paths=paths, threaded=threaded,
                 cache_bytes=cache_bytes)
    for index, (file, seconds) in enumerate(TEMPLATE_AUDIO.items()):
        s.add(file, ogg_bytes(seconds, salt=bytes([index])), seconds)
    return s


@pytest.fixture
def service_s(tmp_path) -> ServiceS:
    return make_service(tmp_path)
