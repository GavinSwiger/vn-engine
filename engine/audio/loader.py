"""``SoundLoader``: effects, voice lines, and UI sounds decode off the frame loop (F08
``04-technical.md`` §7.3 as amended by ``07`` I-5; ADR-0007; TR-F08-05; AC-F08-27, 36, 44, 51,
56).

Why this module exists: decoding a 1 MB FLAC effect takes about 90 ms, so decoding it when
``play sound`` arrives gives a long frame (invariant 10). The service reads and sniffs the file
on the main thread, hands the sniffed bytes to one decode worker, and plays the result on the
main thread once it is ready.

The worker-thread rule (ADR-0007, I-5): the worker gets a ``DecodeJob`` (the file's name, the
``Sniffed`` bytes, the mixer generation) through a queue, holds the loader's own ``lock`` only
around ``decode``, and returns a ``DecodeResult`` holding the Sound it created or the reason it
failed. It never plays, stops, or changes anything, never logs, and never touches the cache,
``GamePaths``, the reader, or the slot model. Everything else happens on the main thread in
``update``, for every ready result: a stale-generation result is dropped (a step 11 device
reopen bumped ``mixer_gen``), a failure is the one W26 line, a Sound is charged to the shared
``SizedLru`` as ``("snd", file)`` with cost ``length_s × 192,000 + ENTRY_OVERHEAD``, and each
ticket still waiting gets it (its owner sets the ramp, picks the channel, and plays). A
cancelled ticket never plays; the decode it started is still cached.

``load`` answers at once when it can: a cache hit plays now (no worker), and a file that can't
be read is silence now (logged once by the reader). Duplicate files in flight share one decode.

``LOADER_THREADED = False`` (the per-OS fallback, chosen by ``sys.platform``, never by config)
runs the same steps on the main thread: ``load`` decodes and finishes the result at once, so
the effect plays in the same call, as before step 9. A backend whose decode costs nothing
(``NullMixer``, the tests' ``FakeMixer``) says so with ``threaded_decode = False`` and is never
given a thread either.

Loop points (step 10): a file with a loop point (``loop_start``, the ``oggloop`` verdict) is
cached as a ``LoopedSound``: the decoded Sound and its tail from the loop point on, cut in
``update`` on the main thread (``MixerBackend.sound_tail``), so the worker still only decodes.
Both are charged to the cache. ``whole(sound)`` is what a one-shot, a voice, or a UI sound
plays.

``reopen``, ``set_mono`` (step 11), and ``shutdown`` take ``lock`` before quitting the mixer,
so SDL is never closed under a decode. ``shutdown`` waits at most ``STOP_WAIT_S`` for the
worker; a daemon worker still decoding is abandoned (AC-F08-51). After a reopen (§7.9 step 2)
the service calls ``bump_gen`` (every result decoded for the old mixer is dropped in
``update``, I-13(e)) and ``discard_sounds`` (the ``("snd", …)`` cache entries belong to the old
mixer); ``set_backend`` points the decode at ``NullMixer`` when no device opened, and back.

Blips (F06 step 2; ``SPEC.md`` §5; ``07`` I-3, I-5): ``load(..., spread=p)`` with ``p > 0``
asks for a blip's five pitch variants, cached as one ``BlipSounds`` under ``("blip", file,
p)`` and charged the sum of its Sounds. The worker runs ``decode_variants`` under the lock
for its whole run: it decodes, and builds four more Sounds from ``pitch.resample`` of the
samples (the middle one is the decoded Sound, speed 1.0), each a Sound it created
(ADR-0007). The job carries the frame size (2 bytes per output channel), read on the main
thread with ``mixer_gen`` (I-3: mono has 2-byte frames). A file over ``BLIP_PITCH_MAX_S`` is
one unpitched Sound, and ``update`` logs W49 once per path. A blip without a spread is the
file's ``("snd", file)`` entry (I-6). The fallback runs the same steps in ``load``.
``discard_sounds`` drops the ``("blip", …)`` entries too.

Imports: ``engine.core`` and ``engine.audio`` only, plus ``threading`` and ``queue``; the
decode itself is ``MixerBackend.decode``, the only caller of ``pygame.mixer.Sound``.
"""

import queue
import sys
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from engine.audio.backend import DecodeError, MixerBackend
from engine.audio.limits import DECODED_BYTES_PER_SECOND
from engine.audio.pitch import BLIP_PITCH_MAX_S, BLIP_STEPS, resample, speed
from engine.audio.reading import AudioReader, w26_not_really, w49_long_blip
from engine.audio.sniff import Sniffed
from engine.core.constants import ENTRY_OVERHEAD
from engine.core.lru import SizedLru

# The per-OS fallback (ADR-0007): an OS where AC-F08-56 (``tests/audio/mixer/
# test_loader_thread.py``) fails decodes on the main thread. win32 passes (F08 step 9); linux
# and darwin are recorded by CI's mixer job; until one fails, it keeps the thread.
_THREADED_BY_PLATFORM: Final[dict[str, bool]] = {"win32": True, "linux": True, "darwin": True}
LOADER_THREADED: Final = _THREADED_BY_PLATFORM.get(sys.platform, True)
STOP_WAIT_S: Final = 1.0                  # shutdown: how long to wait for a decode (AC-F08-51)
WORKER_NAME: Final = "vn-audio-decoder"
SOUND_KEY: Final = "snd"
BLIP_KEY: Final = "blip"
TAIL_MIN_S: Final = 2.0           # an effect's loop tail lasts at least this (re-queued per pass)

# ``on_ready(sound, now)``: the decoded Sound, or None (silence: the reason was logged).
OnReady = Callable[[Any | None, float], None]
# A shared cache key: ``("snd", file)`` or ``("blip", file, spread)``.
Key = tuple[str, str] | tuple[str, str, float]


# ``loop_start(file, sniffed)``: the loop start in seconds of a file with a loop point, or None.
LoopStart = Callable[[str, Sniffed], float | None]


@dataclass(frozen=True, slots=True)
class LoopedSound:
    """A decoded file with a loop point: ``sound`` (the whole file, the first pass) and
    ``tail`` (from the loop point on, repeated to at least ``TAIL_MIN_S``)."""

    sound: Any
    tail: Any


@dataclass(frozen=True, slots=True)
class BlipSounds:
    """A blip's pitch variants (F06): one Sound per ``BLIP_STEPS`` entry, in that order, or
    only the decoded Sound when the file is longer than ``BLIP_PITCH_MAX_S`` (``too_long``).
    ``seconds``: the file's decoded length."""

    sounds: tuple[Any, ...]
    seconds: float

    @property
    def too_long(self) -> bool:
        return len(self.sounds) == 1

    def pick(self, step: int) -> Any:
        """The Sound of variant ``step`` (−2…2, clamped); the one Sound when ``too_long``."""
        if self.too_long:
            return self.sounds[0]
        low, high = BLIP_STEPS[0], BLIP_STEPS[-1]
        return self.sounds[max(low, min(high, step)) - low]


def whole(sound: Any) -> Any:
    """The Sound to play once: the whole file, also for a ``LoopedSound``."""
    return sound.sound if isinstance(sound, LoopedSound) else sound


def sound_key(file: str) -> tuple[str, str]:
    """The shared cache key of a decoded effect or voice line (``04`` §18 item 3)."""
    return (SOUND_KEY, file)


def blip_key(file: str, spread: float) -> Key:
    """The cache key of a blip: its variants with a spread, else the file's Sound (I-6)."""
    return (BLIP_KEY, file, spread) if spread > 0.0 else (SOUND_KEY, file)


@dataclass(frozen=True, slots=True)
class DecodeJob:
    """The worker's whole input, built on the main thread: ``file`` (the key), the bytes
    ``sniff`` accepted, and the mixer generation they were read for."""

    file: str
    sniffed: Sniffed
    gen: int
    loop_start: float | None = None
    spread: float = 0.0                   # F06: > 0 builds the pitch variants
    frame_bytes: int = 4                  # bytes per frame of the mixer (I-3)


@dataclass(frozen=True, slots=True)
class DecodeResult:
    """The worker's whole output: the Sound it created, or None and ``error`` (the
    exception's type name; never raised, never logged by the worker)."""

    file: str
    gen: int
    sound: Any | None
    error: str | None = None
    loop_start: float | None = None
    spread: float = 0.0

    @property
    def key(self) -> Key:
        return blip_key(self.file, self.spread)


class Ticket:
    """One request for a decoded sound (main thread). ``cancel`` keeps it from ever
    playing; ``done`` once its owner was answered. ``spread`` > 0: a blip's variants
    (``BlipSounds``, F06)."""

    __slots__ = ("file", "on_ready", "cancelled", "done", "spread")

    def __init__(self, file: str, on_ready: OnReady, spread: float = 0.0) -> None:
        self.file = file
        self.on_ready = on_ready
        self.cancelled = False
        self.done = False
        self.spread = spread

    @property
    def key(self) -> Key:
        return blip_key(self.file, self.spread)

    @property
    def waiting(self) -> bool:
        return not (self.cancelled or self.done)

    def cancel(self) -> None:
        self.cancelled = True

    def answer(self, sound: Any | None, now: float) -> None:
        if self.waiting:
            self.done = True
            self.on_ready(sound, now)


# ``variants(sniffed, spread, frame_bytes)``: a blip's ``BlipSounds`` (F06).
Variants = Callable[[Sniffed, float, int], BlipSounds]


def run_job(job: DecodeJob, decode: Callable[[Sniffed], Any], lock: threading.Lock,
            variants: Variants | None = None) -> DecodeResult:
    """One decode (with a spread: ``variants``, F06), under ``lock`` for its whole run: the
    Sound, or the reason it failed (any exception: a worker never raises, AC-F08-51)."""
    try:
        with lock:
            if job.spread > 0.0 and variants is not None:
                sound = variants(job.sniffed, job.spread, job.frame_bytes)
            else:
                sound = decode(job.sniffed)
    except DecodeError as error:
        return DecodeResult(job.file, job.gen, None, str(error) or "DecodeError",
                            spread=job.spread)
    except Exception as error:            # pygame.error, MemoryError, a bug: still W26
        return DecodeResult(job.file, job.gen, None, type(error).__name__, spread=job.spread)
    return DecodeResult(job.file, job.gen, sound, loop_start=job.loop_start,
                        spread=job.spread)


def _worker(inbox: "queue.SimpleQueue[DecodeJob | None]",
            outbox: "queue.SimpleQueue[DecodeResult]", decode: Callable[[Sniffed], Any],
            lock: threading.Lock, variants: Variants) -> None:
    """The decode thread: one job at a time until ``None``. Only queues, the lock, bytes,
    and the Sounds it creates (ADR-0007)."""
    while True:
        job = inbox.get()
        if job is None:
            return
        outbox.put(run_job(job, decode, lock, variants))


class SoundLoader:
    """§7.3 with I-5. ``backend``: whose ``decode`` runs on the worker; ``reader``: the
    main thread's reads and the audio log; ``cache``: the App's shared ``SizedLru``;
    ``frame``: ``GameTime.frame`` for the cache's recency; ``threaded``: None uses
    ``LOADER_THREADED`` when the backend's decode is worth a thread; ``loop_start``: a
    file's loop point (step 10), None: no file has one."""

    def __init__(self, backend: MixerBackend, reader: AudioReader, cache: SizedLru, *,
                 frame: Callable[[], int] = lambda: 0, threaded: bool | None = None,
                 loop_start: LoopStart | None = None) -> None:
        self.reader = reader
        self.cache = cache
        self._frame = frame
        self._backend = backend
        self._decode = backend.decode
        self._seconds = backend.sound_seconds
        self._tail = backend.sound_tail
        self.loop_start = loop_start
        if threaded is None:
            threaded = LOADER_THREADED and bool(getattr(backend, "threaded_decode", False))
        self.threaded = threaded
        self.lock = threading.Lock()                  # held by the worker around decode
        self.mixer_gen = 0                            # step 11's reopen bumps it
        self._waiting: dict[Key, list[Ticket]] = {}   # key -> tickets of its one decode
        self._inbox: queue.SimpleQueue[DecodeJob | None] = queue.SimpleQueue()
        self._outbox: queue.SimpleQueue[DecodeResult] = queue.SimpleQueue()
        self._ready: deque[DecodeResult] = deque()   # taken from the outbox by ``wait``
        self._thread: threading.Thread | None = None
        self._closed = False

    # --- the worker's one call -------------------------------------------------------------

    def decode(self, sniffed: Sniffed) -> Any:
        """The plain decode the worker runs (I-5; AC-F08-35/36's spy point, I-13(c)):
        ``MixerBackend.decode``. Raises ``DecodeError``."""
        return self._decode(sniffed)

    def decode_variants(self, sniffed: Sniffed, spread: float, frame_bytes: int) -> BlipSounds:
        """A blip's variants (F06 ``07`` I-5; the worker runs it under ``lock``): the decoded
        Sound and, when it lasts at most ``BLIP_PITCH_MAX_S``, a new Sound for each other
        step, from its samples resampled at ``1 + spread·step/2``. Raises ``DecodeError``."""
        backend = self._backend
        sound = self.decode(sniffed)
        seconds = max(0.0, float(backend.sound_seconds(sound)))
        if seconds > BLIP_PITCH_MAX_S:
            return BlipSounds((sound,), seconds)
        raw = backend.sound_raw(sound)
        return BlipSounds(tuple(
            sound if step == 0
            else backend.sound_from_raw(resample(raw, speed(spread, step), frame_bytes))
            for step in BLIP_STEPS), seconds)

    # --- main thread -----------------------------------------------------------------------

    @property
    def worker(self) -> threading.Thread | None:
        """The decode thread, once started (tests)."""
        return self._thread

    @property
    def pending(self) -> bool:
        """Whether a decode is still in flight (some result not yet finished)."""
        return bool(self._waiting)

    def in_flight(self, file: str, spread: float = 0.0) -> bool:
        return blip_key(file, spread) in self._waiting

    def load(self, file: str, on_ready: OnReady, now: float, *, what: str = "effect",
             restored: bool = False, spread: float = 0.0) -> Ticket:
        """Ask for ``file``'s decoded sound. ``on_ready(sound, now)`` is called exactly once
        unless the ticket is cancelled first: at once for a cache hit (the Sound) or a file
        that can't be read (None, logged once by the reader); otherwise from ``update``
        once the decode finished (or in this call when not threaded). ``what`` and
        ``restored`` pick the reader's messages (W26/W29). ``spread`` > 0: a blip's
        ``BlipSounds`` (F06)."""
        ticket = Ticket(file, on_ready, spread)
        if self._closed:
            ticket.answer(None, now)
            return ticket
        key = ticket.key
        sound = self.cache.get(key, self._frame())
        if sound is not None:
            ticket.answer(sound, now)
            return ticket
        waiting = self._waiting.get(key)
        if waiting is not None:                       # one decode for duplicate files
            waiting.append(ticket)
            return ticket
        sniffed = self.reader.read_sound(file, what=what, restored=restored)
        if sniffed is None:
            ticket.answer(None, now)                  # silence; logged once by the reader
            return ticket
        self._waiting[key] = [ticket]
        if spread > 0.0:                              # the frame size now, with the gen (I-3)
            job = DecodeJob(file, sniffed, self.mixer_gen, spread=spread,
                            frame_bytes=2 * self._backend.channels)
        else:
            loop_start = (self.loop_start(file, sniffed) if self.loop_start is not None
                          else None)
            job = DecodeJob(file, sniffed, self.mixer_gen, loop_start)
        if self.threaded:
            self._submit(job)
        else:                                         # the fallback: the same steps, now
            self._finish(run_job(job, self.decode, self.lock, self.decode_variants), now)
        return ticket

    def update(self, now: float) -> int:
        """Once per frame (the service's ``update``): finish every ready result. Returns
        how many tickets were answered with a Sound (so the service can pause what
        started while audio is paused)."""
        played = 0
        ready = self._ready
        while ready:
            played += self._finish(ready.popleft(), now)
        while True:
            try:
                result = self._outbox.get_nowait()
            except queue.Empty:
                return played
            played += self._finish(result, now)

    def wait(self, timeout: float) -> bool:
        """Block up to ``timeout`` seconds until a decode result is ready for ``update``
        (tests and tools; the frame loop never blocks). True when one is ready."""
        if self._ready:
            return True
        try:
            self._ready.append(self._outbox.get(timeout=max(0.0, timeout)))
        except queue.Empty:
            return False
        return True

    def set_backend(self, backend: MixerBackend) -> None:
        """Decode with ``backend`` from now on (step 11: ``NullMixer`` after a failed
        reopen, the device again once it opens). A decode already running finishes with the
        old one; its result has the old generation and is dropped."""
        self._backend = backend
        self._decode = backend.decode
        self._seconds = backend.sound_seconds
        self._tail = backend.sound_tail

    def discard_sounds(self) -> None:
        """Remove every decoded sound from the shared cache (§7.9 step 2), F06's blip
        variants too: they belong to the mixer that was closed. Their holders were dropped
        first."""
        cache = self.cache
        for key in cache.keys():
            if type(key) is tuple and ((len(key) == 2 and key[0] == SOUND_KEY)
                                       or (len(key) == 3 and key[0] == BLIP_KEY)):
                cache.discard(key)

    def bump_gen(self) -> None:
        """The mixer was (re)opened (step 11): results decoded for the old one are dropped,
        and the tickets waiting for them are cancelled (their owners forget them at their
        next ``update``; the rebuild replays what it keeps)."""
        self.mixer_gen += 1
        waiting, self._waiting = self._waiting, {}
        for tickets in waiting.values():
            for ticket in tickets:
                ticket.cancel()

    def shutdown(self, timeout: float = STOP_WAIT_S) -> bool:
        """Stop the worker (waits up to ``timeout``) and forget every ticket; nothing plays
        after it. Returns whether the worker ended (a daemon still decoding is abandoned).
        Safe to call twice."""
        self._closed = True
        self.bump_gen()
        self._ready.clear()
        thread, self._thread = self._thread, None
        if thread is None:
            return True
        while True:                                   # jobs not started never start
            try:
                self._inbox.get_nowait()
            except queue.Empty:
                break
        self._inbox.put(None)
        thread.join(max(0.0, timeout))
        return not thread.is_alive()

    def acquire(self, timeout: float = STOP_WAIT_S) -> bool:
        """Take ``lock`` before quitting the mixer (I-5): True when taken (release it
        with ``lock.release()``); False when a decode still holds it after ``timeout``."""
        return self.lock.acquire(timeout=max(0.0, timeout))

    # --- internals -------------------------------------------------------------------------

    def _submit(self, job: DecodeJob) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=_worker, name=WORKER_NAME, daemon=True,
                                            args=(self._inbox, self._outbox, self.decode,
                                                  self.lock, self.decode_variants))
            self._thread.start()
        self._inbox.put(job)

    def _finish(self, result: DecodeResult, now: float) -> int:
        """I-5 on the main thread: drop a stale result, log a failure once (W26), charge a
        Sound to the cache, and answer the tickets still waiting. A blip's variants are
        charged together; a blip too long for a pitch is W49 once per path (F06)."""
        if result.gen != self.mixer_gen:
            return 0                                  # decoded for a mixer that is gone
        key = result.key
        tickets = self._waiting.pop(key, [])
        file = result.file
        sound = result.sound
        if sound is None:
            reader = self.reader
            reader.log.problem("damaged", file, w26_not_really(file))
            reader.mark_failed(file)
            for ticket in tickets:
                ticket.answer(None, now)
            return 0
        if isinstance(sound, BlipSounds):
            seconds = sum(max(0.0, float(self._seconds(one))) for one in sound.sounds)
            if sound.too_long:
                self.reader.log.problem("long blip", file,
                                        w49_long_blip(file, sound.seconds), code="W49")
        else:
            seconds = max(0.0, float(self._seconds(sound)))
        if result.loop_start is not None:
            try:
                tail = self._tail(sound, result.loop_start, TAIL_MIN_S)
            except DecodeError:
                pass                                  # it loops from the start
            else:
                seconds += max(0.0, float(self._seconds(tail)))
                sound = LoopedSound(sound, tail)
        self.cache.put(key, sound, int(seconds * DECODED_BYTES_PER_SECOND) + ENTRY_OVERHEAD,
                       self._frame())
        played = 0
        for ticket in tickets:
            if ticket.waiting:
                ticket.answer(sound, now)
                played += 1
        return played


__all__ = ["BLIP_KEY", "BlipSounds", "DecodeJob", "DecodeResult", "Key", "LOADER_THREADED",
           "LoopStart", "LoopedSound", "OnReady", "SOUND_KEY", "STOP_WAIT_S", "SoundLoader",
           "TAIL_MIN_S", "Ticket", "Variants", "WORKER_NAME", "blip_key", "run_job",
           "sound_key", "whole"]
