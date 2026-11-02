"""The mixer backend: the only caller of ``pygame.mixer`` (F08 ``04-technical.md`` §5.2, §7.2,
§8; TR-F08-04; W30).

Why this module exists: ``AudioService`` keeps its own model of what is audible and drives
SDL_mixer only through ``MixerBackend``, so its state machines are testable with a fake
backend and no device (``tests/fakes/fake_mixer.py``), and a machine with no sound device runs
the same code on ``NullMixer``. SDL only ever gets bytes (``BytesIO``), never a path, and
``decode`` only takes bytes ``sniff`` accepted (``Sniffed``).

Channels: 21, all reserved so SDL never picks one itself: 0 voice, 1–4 pool, 5–20 story
effects (``limits.py``). Effect and voice fades are the service's volume ramps, never SDL
channel fades, which overwrite volume changes (G1); so there is no ``channel_fadeout``.

Music (F08 step 5, §7.1): one stream. ``music_start`` always calls ``stop()`` and drains
pending end events before ``load`` and ``play`` (TR-F08-02), so it never loads while a
fade-out runs (``load`` would block until the fade ends, 1.1 s for 1 s) and no stale end event
is left in SDL's queue; ``music_stop`` drains the one event ``stop()`` posts. ``music_arm``
fills pygame's one-slot queue, which SDL starts with no gap when the stream ends. Music gets
the extension as SDL's type hint (``ogg``, ``mp3``, …), which refuses every other decoder.
pygame-ce 2.5.8 facts relied on (TR-F08-06, ``tests/audio/mixer/test_pygame_contract.py``):
``stop()`` clears the queue slot and posts one end event, ``load``/``play`` post none,
``fadeout`` drops the queue slot, a queue transition posts one, ``get_pos`` restarts at each
play or transition and freezes while paused, and ``get_busy`` is False while paused. SDL_mixer
2.8.2 times a native fade in steps of ``int(512 · 1000 / 48,000)`` = 10 ms, but each step is
one 10.67 ms buffer, so a fade would last 6.7 % longer than asked: ``sdl_fade_ms`` asks for
less so it lasts as long as the script says (AC-F08-32).

Loop points (step 10, ``oggloop.py``): music loops natively from the ``LOOPSTART`` tag SDL
reads. An effect can't, so ``sound_tail`` cuts a second Sound from the loop point on, and the
effect plays the whole sound once with the tail in its channel's queue (``channel_queue``),
which SDL_mixer starts in the same buffer (0 frames between, measured). pygame-ce 2.5.8 plays
the queued sound when a channel is stopped, so ``channel_stop`` stops twice.

``window_change`` (step 7) reads the window's focus and minimize events for the service's
background rules (§7.8), so pygame's event constants stay in this module too.

``threaded_decode`` says whether ``decode`` is worth the ``SoundLoader``'s worker thread
(step 9): True for SDL, False for ``NullMixer``, whose decode costs nothing. ``decode`` only
creates a Sound from bytes, so the worker may call it (under the loader's lock, I-5).

Device loss and mono (step 11, §7.9): ``reopen(channels)`` quits SDL_mixer and opens it again
(2 output channels, or 1 for mono) with 21 reserved channels and the music-end event, as at
the first open; it raises ``DeviceError`` when no device opens. The caller holds the loader's
lock (I-5). Every open of the mixer makes SDL post one ``AUDIODEVICEADDED`` per device
(measured on pygame-ce 2.5.8, the dummy driver too), so ``PygameMixer`` clears the device
events its own open posted; otherwise each reopen would schedule the next one.
``open_device`` (step 12) opens a first device for a game that started with ``NullMixer``.
``device_change`` reads the device events for the service. ``silent`` is True only for
``NullMixer``: its stream is never busy, so a track ending "early" there is no damage (W27).

Blip variants (F06 step 2, ``07`` I-3, I-5): ``sound_raw`` gives a decoded Sound's samples
in the mixer's format and ``sound_from_raw`` makes a Sound of such samples; the loader's
worker calls both (under the loader's lock) to build the pitch variants from the samples
``pitch.resample`` returns. ``channels`` is the output channel count of the open mixer (2;
1 after ``set_mono``), so the loader knows a frame's size.
"""

import io
import math
from collections import deque
from typing import Any, Protocol

import pygame

from engine.audio.limits import MIXER_BUFFER, MIXER_CHANNELS, MIXER_RATE, MIXER_SIZE
from engine.audio.sniff import Sniffed
from engine.core.logsetup import get_logger

W30_NO_DEVICE = "No sound device could be opened, so the game runs without sound."
W30_STOPPED = "The sound device stopped working, so the game continues without sound."

_log = get_logger("audio")


class DecodeError(Exception):
    """SDL could not decode bytes ``sniff`` accepted (damaged, or not really that format):
    the caller logs W26 and plays silence."""


class DeviceError(Exception):
    """No sound device could be opened again (step 11): the service goes on with
    ``NullMixer`` and W30's second form."""


class MixerBackend(Protocol):
    """What the service needs of SDL_mixer. Channel numbers are 0–20."""

    threaded_decode: bool          # decode is slow enough for the loader's worker (step 9)
    silent: bool                   # NullMixer: nothing ever plays (step 11)
    channels: int                  # output channels of the open mixer: 2, or 1 (mono)

    def channel_play(self, channel: int, sound: Any, loops: int) -> None:
        """Play ``sound`` on ``channel`` (``loops`` -1 = forever, 0 = once), no SDL fade."""

    def channel_stop(self, channel: int) -> None:
        """Stop ``channel`` and drop what is queued on it."""

    def channel_queue(self, channel: int, sound: Any) -> None:
        """Queue ``sound`` to play once on ``channel`` when its sound ends (step 10)."""

    def channel_queued(self, channel: int) -> bool:
        """Whether something waits in ``channel``'s queue."""

    def channel_busy(self, channel: int) -> bool: ...

    def channel_volume(self, channel: int, volume: float) -> None:
        """Set the channel's level, 0.0–1.0 (already quantized)."""

    def pause_all(self) -> None: ...

    def resume_all(self) -> None: ...

    def music_start(self, track: Sniffed, *, loops: int, start: float, fade_ms: int) -> float:
        """``stop()``, drain end events, then load ``track`` and play it ``loops`` extra
        times (-1 forever) from ``start`` seconds, fading in over ``fade_ms``. Returns the
        start actually used (0 when the format can't seek). Raises ``DecodeError``."""

    def music_arm(self, track: Sniffed, *, loops: int) -> None:
        """Put ``track`` in the one-slot queue (replacing what is there). Raises
        ``DecodeError``."""

    def music_fadeout(self, ms: int) -> None: ...

    def music_stop(self) -> None:
        """Stop the stream at once, clear the slot, and drain the end event it posts."""

    def music_busy(self) -> bool: ...

    def music_pos_ms(self) -> int:
        """Milliseconds mixed since the last play or queue transition; -1 if unknown."""

    def music_volume(self, volume: float) -> None:
        """The stream's level, 0.0–1.0 (already quantized)."""

    def is_music_end(self, raw: object) -> bool:
        """True if the raw event is this backend's music-end event."""

    def decode(self, sniffed: Sniffed) -> Any:
        """A playable sound from sniffed bytes; raises ``DecodeError``. Runs on the loader's
        worker: it touches nothing but the bytes and the Sound it creates."""

    def sound_seconds(self, sound: Any) -> float:
        """The decoded length of ``sound`` in seconds (its cache cost)."""

    def sound_tail(self, sound: Any, start: float, min_seconds: float) -> Any:
        """A new sound of ``sound``'s samples from ``start`` seconds on, repeated until it
        lasts at least ``min_seconds`` (an effect's loop, step 10). Main thread. Raises
        ``DecodeError``."""

    def sound_raw(self, sound: Any) -> bytes:
        """``sound``'s samples: signed 16-bit frames of ``channels`` samples (F06). May run
        on the loader's worker. Raises ``DecodeError``."""

    def sound_from_raw(self, raw: bytes) -> Any:
        """A new sound of ``raw`` (``sound_raw``'s format; F06's pitch variants). May run on
        the loader's worker. Raises ``DecodeError``."""

    def reopen(self, channels: int) -> None:
        """Close the device and open it again with ``channels`` output channels (2; 1 for
        mono): every sound and the stream are gone, and sounds decoded before belong to the
        old device. Raises ``DeviceError`` when none opens; then only ``reopen`` and
        ``shutdown`` may follow. The caller holds the loader's lock (I-5)."""

    def shutdown(self) -> None:
        """Stop everything and close the device; nothing is called after it."""


_STEP_MS = MIXER_BUFFER * 1000 / MIXER_RATE      # 10.67 ms: one SDL_mixer fade step
_SDL_STEP_MS = int(_STEP_MS)                      # what SDL_mixer counts it as


def sdl_fade_ms(ms: int) -> int:
    """The ``fade_ms`` to give SDL_mixer for a fade of ``ms`` real milliseconds."""
    return 0 if ms <= 0 else max(1, round(ms * _SDL_STEP_MS / _STEP_MS))


class PygameMixer:
    """``MixerBackend`` on ``pygame.mixer``: 48,000 Hz, signed 16-bit, ``channels`` output
    channels (2; 1 for mono, step 11), a 512-frame buffer, and ``allowedchanges=0`` so SDL
    converts to exactly that. Raises ``pygame.error`` when no device opens."""

    threaded_decode = True
    silent = False

    def __init__(self, *, channels: int = 2) -> None:
        self.end_event = pygame.event.custom_type()
        # The BytesIO objects SDL may still read from (current, armed, and the one before).
        self._music_files: deque[io.BytesIO] = deque(maxlen=3)
        self._channels: list[Any] = []
        self.channels = channels
        self._open = False
        self._init(channels)                  # raises pygame.error: no device

    def _init(self, channels: int) -> None:
        mixer = pygame.mixer
        if mixer.get_init():                  # pygame.init() opened it with SDL's defaults
            mixer.quit()
        mixer.init(frequency=MIXER_RATE, size=MIXER_SIZE, channels=channels,
                   buffer=MIXER_BUFFER, allowedchanges=0)
        mixer.set_num_channels(MIXER_CHANNELS)
        mixer.set_reserved(MIXER_CHANNELS)
        self._channels = [mixer.Channel(number) for number in range(MIXER_CHANNELS)]
        mixer.music.set_endevent(self.end_event)
        self.channels = channels
        self._open = True
        _clear_device_events()                # the ADDED events this open posted

    def reopen(self, channels: int) -> None:
        self._open = False
        self._channels = []
        try:
            self._init(channels)
        except (pygame.error, NotImplementedError, OSError) as error:
            raise DeviceError(type(error).__name__) from None
        finally:
            self._music_files.clear()
        self._drain()                         # the old stream's end events

    def channel_play(self, channel: int, sound: Any, loops: int) -> None:
        self._channels[channel].play(sound, loops=loops)

    def channel_stop(self, channel: int) -> None:
        sdl_channel = self._channels[channel]
        sdl_channel.stop()
        sdl_channel.stop()            # the first stop started the queued sound, if any

    def channel_queue(self, channel: int, sound: Any) -> None:
        self._channels[channel].queue(sound)

    def channel_queued(self, channel: int) -> bool:
        return self._channels[channel].get_queue() is not None

    def channel_busy(self, channel: int) -> bool:
        return bool(self._channels[channel].get_busy())

    def channel_volume(self, channel: int, volume: float) -> None:
        self._channels[channel].set_volume(volume)

    def pause_all(self) -> None:
        pygame.mixer.pause()
        pygame.mixer.music.pause()

    def resume_all(self) -> None:
        pygame.mixer.unpause()
        pygame.mixer.music.unpause()

    def music_start(self, track: Sniffed, *, loops: int, start: float, fade_ms: int) -> float:
        if not isinstance(track, Sniffed):
            raise TypeError("music_start takes only bytes sniff() accepted")
        music = pygame.mixer.music
        music.stop()
        self._drain()
        file = io.BytesIO(track.data)
        try:
            music.load(file, track.ext[1:])
            try:
                music.play(loops=loops, start=start, fade_ms=sdl_fade_ms(fade_ms))
            except pygame.error:
                if start <= 0.0:
                    raise
                music.play(loops=loops, start=0.0, fade_ms=sdl_fade_ms(fade_ms))  # no seek
                start = 0.0
        except (pygame.error, ValueError, OSError, MemoryError, NotImplementedError) as error:
            raise DecodeError(type(error).__name__) from None
        self._music_files.append(file)
        return start

    def music_arm(self, track: Sniffed, *, loops: int) -> None:
        if not isinstance(track, Sniffed):
            raise TypeError("music_arm takes only bytes sniff() accepted")
        file = io.BytesIO(track.data)
        try:
            pygame.mixer.music.queue(file, track.ext[1:], loops)
        except (pygame.error, ValueError, OSError, MemoryError, NotImplementedError) as error:
            raise DecodeError(type(error).__name__) from None
        self._music_files.append(file)

    def music_fadeout(self, ms: int) -> None:
        pygame.mixer.music.fadeout(sdl_fade_ms(ms))

    def music_stop(self) -> None:
        pygame.mixer.music.stop()
        self._drain()

    def music_busy(self) -> bool:
        return bool(pygame.mixer.music.get_busy())

    def music_pos_ms(self) -> int:
        return int(pygame.mixer.music.get_pos())

    def music_volume(self, volume: float) -> None:
        pygame.mixer.music.set_volume(volume)

    def is_music_end(self, raw: object) -> bool:
        return getattr(raw, "type", None) == self.end_event

    def _drain(self) -> None:
        """Drop the music-end events waiting in SDL's queue (there are none without a
        display: SDL posts them only while the video system is up)."""
        try:
            pygame.event.clear(self.end_event)
        except pygame.error:
            pass

    def decode(self, sniffed: Sniffed) -> Any:
        if not isinstance(sniffed, Sniffed):
            raise TypeError("decode takes only bytes sniff() accepted")
        try:
            return pygame.mixer.Sound(io.BytesIO(sniffed.data))
        except (pygame.error, ValueError, OSError, MemoryError) as error:
            raise DecodeError(type(error).__name__) from None

    def sound_seconds(self, sound: Any) -> float:
        return float(sound.get_length())

    def sound_tail(self, sound: Any, start: float, min_seconds: float) -> Any:
        init = pygame.mixer.get_init()
        if not init:
            raise DecodeError("closed")
        rate, size, channels = init
        frame = channels * abs(size) // 8
        try:
            raw = sound.get_raw()
            tail = raw[round(start * rate) * frame:]
            if not tail:
                raise DecodeError("empty")
            wanted = math.ceil(min_seconds * rate) * frame
            copies = max(1, -(-wanted // len(tail)))
            return pygame.mixer.Sound(buffer=tail * copies)
        except (pygame.error, ValueError, MemoryError) as error:
            raise DecodeError(type(error).__name__) from None

    def sound_raw(self, sound: Any) -> bytes:
        try:
            return bytes(sound.get_raw())
        except (pygame.error, MemoryError) as error:
            raise DecodeError(type(error).__name__) from None

    def sound_from_raw(self, raw: bytes) -> Any:
        try:
            return pygame.mixer.Sound(buffer=raw)
        except (pygame.error, ValueError, MemoryError) as error:
            raise DecodeError(type(error).__name__) from None

    def shutdown(self) -> None:
        if not self._open:
            return
        self._open = False
        try:
            pygame.mixer.stop()
            pygame.mixer.music.stop()
            self._drain()
        finally:
            pygame.mixer.quit()
            self._music_files.clear()


class NullSound:
    """What ``NullMixer.decode`` returns: nothing to play, no length."""

    __slots__ = ()


class NullMixer:
    """No sound device: every call does nothing and nothing is ever busy (§8 item 6). Files
    are still read and sniffed, so their problems are still logged."""

    threaded_decode = False
    silent = True
    channels = 2

    def channel_play(self, channel: int, sound: Any, loops: int) -> None:
        pass

    def channel_stop(self, channel: int) -> None:
        pass

    def channel_queue(self, channel: int, sound: Any) -> None:
        pass

    def channel_queued(self, channel: int) -> bool:
        return False

    def channel_busy(self, channel: int) -> bool:
        return False

    def channel_volume(self, channel: int, volume: float) -> None:
        pass

    def pause_all(self) -> None:
        pass

    def resume_all(self) -> None:
        pass

    def music_start(self, track: Sniffed, *, loops: int, start: float, fade_ms: int) -> float:
        if not isinstance(track, Sniffed):
            raise TypeError("music_start takes only bytes sniff() accepted")
        return start

    def music_arm(self, track: Sniffed, *, loops: int) -> None:
        pass

    def music_fadeout(self, ms: int) -> None:
        pass

    def music_stop(self) -> None:
        pass

    def music_busy(self) -> bool:
        return False

    def music_pos_ms(self) -> int:
        return -1

    def music_volume(self, volume: float) -> None:
        pass

    def is_music_end(self, raw: object) -> bool:
        return False

    def decode(self, sniffed: Sniffed) -> Any:
        if not isinstance(sniffed, Sniffed):
            raise TypeError("decode takes only bytes sniff() accepted")
        return NullSound()

    def sound_seconds(self, sound: Any) -> float:
        return 0.0

    def sound_tail(self, sound: Any, start: float, min_seconds: float) -> Any:
        return NullSound()

    def sound_raw(self, sound: Any) -> bytes:
        return b""

    def sound_from_raw(self, raw: bytes) -> Any:
        return NullSound()

    def reopen(self, channels: int) -> None:
        raise DeviceError("no device")

    def shutdown(self) -> None:
        pass


def open_backend(*, channels: int = 2) -> MixerBackend:
    """The session's backend: ``PygameMixer``, or ``NullMixer`` with one W30 when no device
    can be opened (PR-F08-18). The device's name is never logged (§8 item 2)."""
    try:
        return PygameMixer(channels=channels)
    except (pygame.error, NotImplementedError, OSError):
        _log.warning("%s", W30_NO_DEVICE, extra={"code": "W30"})
        return NullMixer()


def open_device(channels: int = 2) -> MixerBackend:
    """A device plugged in after the game started without one (step 12): ``PygameMixer``
    with ``channels`` output channels, or ``DeviceError`` (no log: the start's W30 said it
    already). The caller holds the loader's lock (I-5)."""
    try:
        return PygameMixer(channels=channels)
    except (pygame.error, NotImplementedError, OSError) as error:
        raise DeviceError(type(error).__name__) from None


# --- Window events (§7.8): the service watches them without consuming them ----------------------

# The App's own lists (``app.py``'s ``_UNMINIMIZE_EVENTS``): any of these ends "minimized".
_UNMINIMIZE_EVENTS = frozenset((pygame.WINDOWRESTORED, pygame.WINDOWMAXIMIZED,
                                pygame.WINDOWSHOWN, pygame.WINDOWEXPOSED))
_WINDOW_CHANGES: dict[int, tuple[str, bool]] = {
    pygame.WINDOWFOCUSLOST: ("unfocused", True),
    pygame.WINDOWFOCUSGAINED: ("unfocused", False),
    pygame.WINDOWMINIMIZED: ("minimized", True),
    **{kind: ("minimized", False) for kind in _UNMINIMIZE_EVENTS},
}


def window_change(raw: object) -> tuple[str, bool] | None:
    """What a raw pygame event says about the window: ``("unfocused", bool)``,
    ``("minimized", bool)``, or None for any other event (the service only reads the
    event's ``type``; pygame's event constants live here, ``04`` §3)."""
    kind = getattr(raw, "type", None)
    return _WINDOW_CHANGES.get(kind) if type(kind) is int else None


# --- Device events (§7.9): pygame doesn't say which device is ours -----------------------------

_DEVICE_EVENTS: dict[int, str] = {pygame.AUDIODEVICEADDED: "added",
                                  pygame.AUDIODEVICEREMOVED: "removed"}


def device_change(raw: object) -> tuple[str, bool] | None:
    """What a raw pygame event says about the sound devices: ``("added" | "removed",
    iscapture)``, or None for any other event."""
    kind = getattr(raw, "type", None)
    what = _DEVICE_EVENTS.get(kind) if type(kind) is int else None
    if what is None:
        return None
    return what, bool(getattr(raw, "iscapture", 0))


def _clear_device_events() -> None:
    """Drop the device events waiting in SDL's queue (each open of the mixer posts one
    ``AUDIODEVICEADDED`` per device). Without a display there is no queue to clear."""
    try:
        pygame.event.clear(tuple(_DEVICE_EVENTS))
    except pygame.error:
        pass


__all__ = ["DecodeError", "DeviceError", "MixerBackend", "NullMixer", "NullSound",
           "PygameMixer", "W30_NO_DEVICE", "W30_STOPPED", "device_change", "open_backend",
           "open_device", "sdl_fade_ms", "window_change"]
