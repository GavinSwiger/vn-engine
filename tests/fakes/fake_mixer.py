"""``FakeMixer``: the ``MixerBackend`` of F08's unit tests (``06`` §0.2), and builders for audio
bytes that pass ``sniff``.

FakeMixer records every call as ``(t, name, args)`` in ``calls`` (``t`` from the fake clock),
identifies audio by the SHA-256 of the bytes it decodes (``register`` maps them back to fixture
names and lengths), and models ``busy`` on the fake clock: a channel is busy from its
``channel_play`` until the sound's length × passes has elapsed (forever for ``loops=-1``) or
``channel_stop``. ``actions()`` leaves out the queries (``channel_busy``, ``sound_seconds``,
``music_busy``, ``music_pos_ms``).

Music (F08 step 5) is modelled like SDL on the fake clock: one stream and a one-slot queue
(``music_arm``). A play of ``loops`` 0 lasts the sound's length minus its start; ``loops=-1``
never ends. When the stream ends (its length, or the end of a ``music_fadeout``) one end event
is posted and the armed item starts with no gap; ``music_stop`` posts one and clears the slot,
``music_fadeout`` clears the slot (pygame-ce 2.5.8 frees the queue), and ``music_start`` and
``music_stop`` drain the posted events. A second ``music_fadeout`` rescales the running fade
as SDL does. ``music_start`` while the stream is busy fails the test (two streams).
``pause_all`` freezes the channels and the stream that play at that moment (a paused channel
stays busy, paused music isn't busy and keeps its position) and ``resume_all`` shifts them on,
as SDL does; something started after a pause plays until the next ``pause_all`` (F08 step 7).
Step 10: ``channel_queue`` puts a sound in a channel's one-slot queue; when the playing sound
ends it starts there with no gap, once (as SDL_mixer's channel queue). ``sound_tail(sound,
start, min_seconds)`` is a ``FakeSound`` named ``<name>#tail`` lasting ``length − start``
repeated to at least ``min_seconds``. ``channel_stop`` drops the queue too.
``take_events()`` hands the posted events over (the App's ``event.get``); ``drop_events``
loses them and ``stuck_fades`` keeps a fade-out from ever ending (the watchdog tests).
Step 11: ``reopen(channels)`` loses every sound, the stream, its slot, and the posted events,
and records ``channels``; with ``fail_reopen`` it raises ``DeviceError`` instead (the device
is gone). ``silent`` is False (only ``NullMixer`` is silent).

``ogg_bytes``, ``opus_bytes``, ``wav_bytes``, ``flac_bytes``: minimal files whose headers
declare a length; enough for the sniff and the length check, not for a real decoder.
"""

import hashlib
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from engine.audio.backend import DecodeError, DeviceError
from engine.audio.sniff import Sniffed, declared_seconds

QUERIES = frozenset(("channel_busy", "channel_queued", "sound_seconds", "music_busy",
                     "music_pos_ms"))
MUSIC_END = "music_end"


@dataclass(frozen=True)
class FakeSound:
    name: str
    seconds: float


@dataclass
class _Playing:
    sound: FakeSound
    started: float
    loops: int
    paused_at: float | None = None        # pause_all froze it (SDL: still busy)
    queued: FakeSound | None = None       # step 10: starts when this one ends

    def end(self) -> float:
        return self.started + self.sound.seconds * (self.loops + 1)


@dataclass(frozen=True)
class FakeEvent:
    """A posted music-end event; ``at`` is when SDL posted it."""

    type: str
    at: float


@dataclass
class _Music:
    sound: FakeSound
    loops: int
    start: float              # offset into the sound at this play
    t0: float                 # clock time this play (or transition) began
    fade_t0: float | None = None
    fade_end: float | None = None
    paused_at: float | None = None        # pause_all froze it (not busy, position kept)

    def natural_end(self) -> float:
        if self.loops < 0:
            return float("inf")
        return self.t0 + max(0.0, self.sound.seconds - self.start)

    def end(self, stuck: bool) -> float:
        if self.fade_end is not None and not stuck:
            return min(self.natural_end(), self.fade_end)
        return self.natural_end()


@dataclass
class FakeMixer:
    clock: Callable[[], float] = lambda: 0.0
    calls: list[tuple] = field(default_factory=list)
    volumes: dict[int, float] = field(default_factory=dict)
    playing: dict[int, _Playing] = field(default_factory=dict)
    decoded: list[str] = field(default_factory=list)
    fail_decode: set[str] = field(default_factory=set)      # names whose decode raises
    paused: bool = False
    closed: bool = False
    # Music (step 5).
    music: _Music | None = None
    armed: tuple[FakeSound, int] | None = None
    music_level: float = 1.0
    events: list[FakeEvent] = field(default_factory=list)
    drop_events: bool = False
    stuck_fades: bool = False
    # Step 9: the service's ``SoundLoader`` decodes in the calling thread for this backend
    # (its decode costs nothing), so every unit test plays when its command arrives; tests
    # of the worker pass ``loader_threaded=True`` to the service.
    threaded_decode: bool = False
    silent: bool = False
    # Step 11: the output channels of the last (re)open, and whether the next reopen fails.
    channels: int = 2
    fail_reopen: bool = False
    # ``decode_hook(name)`` runs inside ``decode`` (on the loader's worker when threaded):
    # a test blocks it on an Event or raises from it. ``threads`` records the thread of
    # every call as ``(name, thread name)`` (ADR-0007: only ``decode`` leaves the main one).
    decode_hook: Callable[[str], None] | None = None
    threads: list[tuple[str, str]] = field(default_factory=list)
    _names: dict[str, tuple[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from engine.audio.music import SILENT_WAV_BYTES

        self.register(SILENT_WAV_BYTES, "SILENT_WAV", 1 / 48_000)

    # --- test helpers ------------------------------------------------------------------------

    def register(self, data: bytes, name: str, seconds: float) -> None:
        self._names[hashlib.sha256(data).hexdigest()] = (name, seconds)

    def actions(self, *names: str) -> list[tuple]:
        """The calls that change something (queries left out), or only those named."""
        return [c for c in self.calls if c[1] not in QUERIES and (not names or c[1] in names)]

    def busy_channels(self) -> set[int]:
        return {channel for channel in list(self.playing) if self._busy(channel)}

    def name_on(self, channel: int) -> str | None:
        playing = self.playing.get(channel)
        return playing.sound.name if playing is not None and self._busy(channel) else None

    def occupy(self, channel: int, name: str) -> None:
        """Something outside the story effects (a voice, a UI sound) plays on ``channel``
        forever; no call is recorded."""
        self.playing[channel] = _Playing(FakeSound(name, 1.0), self.clock(), -1)

    def finish(self, channel: int) -> None:
        """The sound on ``channel`` ends now (a one-shot reached its end)."""
        self.playing.pop(channel, None)

    def take_events(self) -> list[FakeEvent]:
        """The music-end events posted up to now (and forgets them), as ``event.get``."""
        self._advance()
        events, self.events = self.events, []
        return events

    def music_name(self) -> str | None:
        """The name of the sound the stream plays now (None: not busy)."""
        self._advance()
        return self.music.sound.name if self.music is not None else None

    def armed_name(self) -> str | None:
        self._advance()
        return self.armed[0].name if self.armed is not None else None

    def fake_music_end(self) -> None:
        """Post a music-end event now, as SDL would (a test's stale event)."""
        self.events.append(FakeEvent(MUSIC_END, self.clock()))

    # --- MixerBackend ------------------------------------------------------------------------

    def _record(self, name: str, *args: object) -> None:
        self.calls.append((self.clock(), name, args))
        self.threads.append((name, threading.current_thread().name))

    def _roll(self, channel: int) -> _Playing | None:
        """The queued sound starts when the playing one ends (no gap), once."""
        playing = self.playing.get(channel)
        while playing is not None and playing.loops >= 0 and playing.queued is not None:
            now = playing.paused_at if playing.paused_at is not None else self.clock()
            if now < playing.end():
                break
            playing = _Playing(playing.queued, playing.end(), 0, playing.paused_at)
            self.playing[channel] = playing
        return playing

    def _busy(self, channel: int) -> bool:
        playing = self._roll(channel)
        if playing is None:
            return False
        if playing.loops < 0:
            return True
        now = playing.paused_at if playing.paused_at is not None else self.clock()
        return now < playing.end()

    def queued_on(self, channel: int) -> str | None:
        """The name of the sound waiting in ``channel``'s queue (None: nothing)."""
        playing = self._roll(channel)
        if playing is None or playing.queued is None or not self._busy(channel):
            return None
        return playing.queued.name

    def channel_play(self, channel: int, sound: FakeSound, loops: int) -> None:
        self._record("channel_play", channel, sound.name, loops)
        self.playing[channel] = _Playing(sound, self.clock(), loops)

    def channel_stop(self, channel: int) -> None:
        self._record("channel_stop", channel)
        self.playing.pop(channel, None)

    def channel_queue(self, channel: int, sound: FakeSound) -> None:
        self._record("channel_queue", channel, sound.name)
        playing = self._roll(channel)
        if playing is None or not self._busy(channel):
            self.playing[channel] = _Playing(sound, self.clock(), 0)   # pygame: plays now
        else:
            playing.queued = sound

    def channel_queued(self, channel: int) -> bool:
        self._record("channel_queued", channel)
        return self.queued_on(channel) is not None

    def channel_busy(self, channel: int) -> bool:
        self._record("channel_busy", channel)
        return self._busy(channel)

    def channel_volume(self, channel: int, volume: float) -> None:
        self._record("channel_volume", channel, volume)
        self.volumes[channel] = volume

    def pause_all(self) -> None:
        """As SDL's ``Mix_Pause(-1)`` and ``Mix_PauseMusic``: what plays now freezes (a
        paused channel stays busy; paused music isn't busy and keeps its position). A sound
        or track started later plays unpaused until the next ``pause_all``, as in SDL."""
        self._record("pause_all")
        self._advance()
        now = self.clock()
        for playing in self.playing.values():
            if playing.paused_at is None:
                playing.paused_at = now
        if self.music is not None and self.music.paused_at is None:
            self.music.paused_at = now
        self.paused = True

    def resume_all(self) -> None:
        self._record("resume_all")
        now = self.clock()
        for playing in self.playing.values():
            if playing.paused_at is not None:
                playing.started += now - playing.paused_at
                playing.paused_at = None
        music = self.music
        if music is not None and music.paused_at is not None:
            shift = now - music.paused_at
            music.t0 += shift
            if music.fade_end is not None and music.fade_t0 is not None:
                music.fade_t0 += shift
                music.fade_end += shift
            music.paused_at = None
        self.paused = False

    # --- music ---------------------------------------------------------------------------------

    def _post(self, at: float) -> None:
        if not self.drop_events:
            self.events.append(FakeEvent(MUSIC_END, at))

    def _advance(self) -> None:
        """Run the stream up to now: ends post an event and start the armed item."""
        while self.music is not None and self.music.paused_at is None:
            end = self.music.end(self.stuck_fades)
            if self.clock() < end:
                return
            self._post(end)
            if self.armed is not None:
                sound, loops = self.armed
                self.armed = None
                self.music = _Music(sound, loops, 0.0, end)
            else:
                self.music = None

    def _sound_of(self, track: Sniffed) -> FakeSound:
        if not isinstance(track, Sniffed):
            raise TypeError("music takes only bytes sniff() accepted")
        digest = hashlib.sha256(track.data).hexdigest()
        name, seconds = self._names.get(digest, (f"sha:{digest[:12]}", 1.0))
        if name in self.fail_decode:
            raise DecodeError("fake")
        return FakeSound(name, seconds)

    def _drain(self) -> None:
        self.events = [event for event in self.events if event.type != MUSIC_END]

    def music_start(self, track: Sniffed, *, loops: int, start: float, fade_ms: int) -> float:
        sound = self._sound_of(track)
        self._record("music_start", sound.name, loops, start, fade_ms)
        self._advance()
        assert self.music is None, f"music_start({sound.name}) while {self.music.sound.name} is busy"
        self.armed = None                       # stop() clears the slot; drained below
        self._drain()
        self.music = _Music(sound, loops, start, self.clock())
        return start

    def music_arm(self, track: Sniffed, *, loops: int) -> None:
        sound = self._sound_of(track)
        self._record("music_arm", sound.name, loops)
        self._advance()
        self.armed = (sound, loops)

    def music_fadeout(self, ms: int) -> None:
        self._record("music_fadeout", ms)
        self._advance()
        music = self.music
        self.armed = None                       # pygame-ce frees the queue slot
        if music is None:
            return
        now = music.paused_at if music.paused_at is not None else self.clock()
        seconds = ms / 1000
        if music.fade_end is not None and music.fade_t0 is not None and now < music.fade_end:
            done = (now - music.fade_t0) / (music.fade_end - music.fade_t0)
            music.fade_t0 = now - done * seconds          # SDL rescales the running fade
            music.fade_end = now + (1 - done) * seconds
        else:
            music.fade_t0, music.fade_end = now, now + seconds

    def music_stop(self) -> None:
        self._record("music_stop")
        self._advance()
        if self.music is not None and self.music.paused_at is None:
            self._post(self.clock())
        self.music = None
        self.armed = None
        self._drain()

    def music_busy(self) -> bool:
        self._record("music_busy")
        self._advance()
        return self.music is not None and self.music.paused_at is None

    def music_pos_ms(self) -> int:
        self._record("music_pos_ms")
        self._advance()
        if self.music is None:
            return -1
        paused_at = self.music.paused_at
        now = paused_at if paused_at is not None else self.clock()
        return int(round((now - self.music.t0) * 1000))

    def music_volume(self, volume: float) -> None:
        self._record("music_volume", volume)
        self.music_level = volume

    def is_music_end(self, raw: object) -> bool:
        return isinstance(raw, FakeEvent) and raw.type == MUSIC_END

    def decode(self, sniffed: Sniffed) -> FakeSound:
        if not isinstance(sniffed, Sniffed):
            raise TypeError("decode takes only bytes sniff() accepted")
        digest = hashlib.sha256(sniffed.data).hexdigest()
        # An unregistered file lasts what its header declares (F06: the example's blips in
        # launches), else 1 s.
        name, seconds = self._names.get(digest, (f"sha:{digest[:12]}",
                                                 declared_seconds(sniffed) or 1.0))
        self._record("decode", name)
        if self.decode_hook is not None:
            self.decode_hook(name)
        if name in self.fail_decode:
            raise DecodeError("fake")
        self.decoded.append(name)
        return FakeSound(name, seconds)

    def sound_seconds(self, sound: FakeSound) -> float:
        self._record("sound_seconds", sound.name)
        return sound.seconds

    def sound_raw(self, sound: FakeSound) -> bytes:
        """F06: silent 16-bit frames of the sound's length at 48 kHz (``tests/audio``'s
        ``BlipMixer`` records these calls)."""
        return bytes(round(sound.seconds * 48_000) * 2 * self.channels)

    def sound_from_raw(self, raw: bytes) -> FakeSound:
        frames = len(raw) // (2 * self.channels)
        return FakeSound(f"raw:{frames}", frames / 48_000)

    def sound_tail(self, sound: FakeSound, start: float, min_seconds: float) -> FakeSound:
        self._record("sound_tail", sound.name, start)
        span = sound.seconds - start
        if span <= 0.0:
            raise DecodeError("fake")
        copies = max(1, -(-min_seconds // span))
        return FakeSound(sound.name + "#tail", span * copies)

    def reopen(self, channels: int) -> None:
        self._record("reopen", channels)
        self.playing.clear()
        self.music = None
        self.armed = None
        self.events.clear()
        self.paused = False
        if self.fail_reopen:
            raise DeviceError("fake")
        self.channels = channels

    def shutdown(self) -> None:
        self._record("shutdown")
        self.closed = True
        self.playing.clear()
        self.music = None
        self.armed = None


# --- Audio bytes ------------------------------------------------------------------------------

def _ogg_page(packet: bytes, granule: int, sequence: int, flags: int = 0) -> bytes:
    lacing = [255] * (len(packet) // 255) + [len(packet) % 255]
    return (b"OggS" + bytes([0, flags]) + struct.pack("<qII", granule, 1, sequence)
            + b"\0\0\0\0" + bytes([len(lacing)]) + bytes(lacing) + packet)


def ogg_bytes(seconds: float, *, rate: int = 48_000, salt: bytes = b"") -> bytes:
    """An ``.ogg`` (Vorbis) file: the identification header, then one page whose granule
    declares ``seconds``. ``salt`` makes files with the same length differ."""
    ident = b"\x01vorbis" + struct.pack("<IBIiii", 0, 2, rate, 0, 0, 0) + b"\xb8\x01"
    body = _ogg_page(b"\x05" + salt + b"\0" * 64, 0, 1)
    return (_ogg_page(ident, 0, 0, flags=2) + body
            + _ogg_page(b"\0" * 16, round(seconds * rate), 2, flags=4))


def opus_bytes(seconds: float, *, pre_skip: int = 312, salt: bytes = b"") -> bytes:
    head = b"OpusHead" + struct.pack("<BBHIhB", 1, 2, pre_skip, 48_000, 0, 0)
    return (_ogg_page(head, 0, 0, flags=2) + _ogg_page(b"OpusTags" + salt, 0, 1)
            + _ogg_page(b"\0" * 16, round(seconds * 48_000) + pre_skip, 2, flags=4))


def wav_bytes(seconds: float, *, rate: int = 8_000, data_size: int | None = None) -> bytes:
    """A 16-bit mono WAV; ``data_size`` overrides the declared ``data`` size (the bytes
    present are ``seconds`` long)."""
    pcm = b"\0\0" * round(seconds * rate)
    size = len(pcm) if data_size is None else data_size
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE" + b"fmt "
            + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", size) + pcm)


def flac_bytes(seconds: float, *, rate: int = 44_100) -> bytes:
    total = round(seconds * rate)
    packed = (rate << 44) | (1 << 41) | (15 << 36) | total     # 2 channels, 16 bits
    info = struct.pack(">HH", 4096, 4096) + b"\0" * 6 + packed.to_bytes(8, "big") + b"\0" * 16
    return b"fLaC" + bytes([0x80, 0, 0, len(info)]) + info


def mp3_bytes(salt: bytes = b"") -> bytes:
    return b"\xff\xfb\x90\x00" + salt + b"\0" * 400


__all__ = ["FakeEvent", "FakeMixer", "FakeSound", "MUSIC_END", "QUERIES", "flac_bytes", "mp3_bytes", "ogg_bytes",
           "opus_bytes", "wav_bytes"]
