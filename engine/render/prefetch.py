"""``ImagePrefetcher``: decodes the images the story will show soon, off the frame loop
(F04 ``04-technical.md`` §7.7; ADR-0007; PR-F04-21).

Why this module exists: decoding one large PNG takes about 36 ms, so loading it in the frame
loop when a line shows it gives a long frame. The interpreter's look-ahead names the images
the next lines may show (``PrefetchImages``); this module reads them on the main thread,
hands the bytes to one decode worker, and puts each finished image into the shared asset
cache on the main thread, at most one per frame, so the later ``show`` finds it cached.

The worker-thread rule (ADR-0007): the worker gets immutable input (``DecodeJob``: a ref,
bytes, a size) through a queue and returns only surfaces it created (``Decoded``). It never
touches ``AssetManager``, the cache, ``GamePaths``, story state, or the log; it never plays
or shows anything. Every file read, header check, conversion, and cache write happens in
``pump()`` on the main thread. ``PREFETCH_THREADED = False`` runs the same decode inside
``pump()`` instead (the per-OS fallback, I-14: chosen by ``sys.platform``, never by config;
AC-F04-44 (c) shows the pixels are the same either way).

Budget (§7.7): an image whose header estimate (``w·h·4``) is over ``PREFETCH_ONE_MAX`` of
``[engine] cache_mb`` is never decoded ahead; one request stops before its total passes
``PREFETCH_TOTAL_MAX``. Prefetched images are not held, so the cache may evict them; images
on stage are held by ``StageView``. A failed read or decode is dropped silently: a later
``image()`` loads the file and logs its one F01 line.

Measured on win32 (AC-F04-45): a 23–28 ms decode plus pre-scale of a 1200×2000 RGBA PNG
stalls a 60 fps main thread by under 0.01 ms, and by at most 0.54 ms when the main thread
never sleeps. SDL reads the job's ``BytesIO`` through Python callbacks that take the GIL, so
a main thread that never sleeps (no frame limiter) slows each decode to seconds; the frame
loop's limiter sleep is what gives the worker its time.

Imports: ``engine.core`` only, plus ``threading``, ``queue``, ``io``, and ``pygame``
(AC-F04-47); the asset manager comes in duck-typed as ``PrefetchAssets``.
"""

import io
import queue
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final, Protocol

import pygame

# I-14: an OS where AC-F04-45 (``tests/render/test_prefetch_thread.py``) fails decodes on the
# main thread. Results so far (pygame-ce 2.5.8): win32 passes (F04 step 7). linux and darwin
# are recorded by CI; until one fails, it keeps the thread.
_THREADED_BY_PLATFORM: Final[dict[str, bool]] = {"win32": True, "linux": True, "darwin": True}
PREFETCH_THREADED: Final = _THREADED_BY_PLATFORM.get(sys.platform, True)
PREFETCH_ONE_MAX: Final = 0.25            # of the budget: a bigger image is never prefetched
PREFETCH_TOTAL_MAX: Final = 0.5           # of the budget: one request stops before passing it
STOP_WAIT_S: Final = 1.0                  # stop(): how long to wait for a decode to finish
WORKER_NAME: Final = "vn-image-decoder"

# A target for the pre-scaled variant, given the source size from the header:
# ``((width, height), flip_x)`` in device pixels, or None for no variant.
Target = tuple[tuple[int, int], bool] | None


class PrefetchAssets(Protocol):
    """What the prefetcher uses of ``AssetManager`` (main thread only)."""

    scale_filter: str

    @property
    def budget_bytes(self) -> int: ...

    def is_cached(self, ref: str) -> bool: ...

    def read_image_bytes(self, ref: str) -> tuple[bytes, str, int, int] | None: ...

    def convert(self, surface: pygame.Surface) -> pygame.Surface: ...

    def variant_key(self, ref: str, size_px: tuple[int, int], flip_x: bool = False) -> tuple: ...

    def adopt(self, ref: str, source: pygame.Surface,
              variants: dict[tuple, pygame.Surface]) -> None: ...


@dataclass(frozen=True, slots=True)
class PrefetchRequest:
    """One image to decode ahead: its file ``ref`` and, optionally, how to choose its
    pre-scaled size once the header gives the source size (main thread, at send time)."""

    ref: str
    target: Callable[[int, int], Target] | None = None
    # F38: decode again for the pre-scaled variant even when the source is cached (a frame
    # whose variant at a new size or place is missing; the stage asks only when it is).
    rescale: bool = False


@dataclass(frozen=True, slots=True)
class DecodeJob:
    """The worker's whole input: immutable, built on the main thread."""

    ref: str
    data: bytes
    hint: str                             # "image.png": the type hint SDL gets (PR-F01-06)
    size: tuple[int, int] | None          # pre-scale to this size (24/32-bit only), or not
    flip_x: bool = False


@dataclass(frozen=True, slots=True)
class Decoded:
    """The worker's whole output: surfaces it created (None: the decode failed)."""

    ref: str
    source: pygame.Surface | None
    variant: pygame.Surface | None = None
    flip_x: bool = False


def decode_image(job: DecodeJob) -> Decoded:
    """Decode ``job`` and pre-scale it with ``smoothscale`` (then mirror), the same steps
    ``AssetManager.variant`` takes, so the pixels match (TR-F04-04). Touches only what it
    creates; never logs; never raises."""
    try:
        source = pygame.image.load(io.BytesIO(job.data), job.hint)
    except Exception:                     # pygame.error, OSError, ValueError, MemoryError
        return Decoded(job.ref, None)
    variant = None
    if job.size is not None and source.get_bitsize() in (24, 32):
        try:
            variant = pygame.transform.smoothscale(source, job.size)
            if job.flip_x:
                variant = pygame.transform.flip(variant, True, False)
        except Exception:
            variant = None
    return Decoded(job.ref, source, variant, job.flip_x)


def _worker(inbox: "queue.SimpleQueue[DecodeJob | None]", outbox: "queue.SimpleQueue[Decoded]",
            decode: Callable[[DecodeJob], Decoded]) -> None:
    """The decode thread: one job at a time until ``None``. Only queues, bytes, and its
    own surfaces (ADR-0007)."""
    while True:
        job = inbox.get()
        if job is None:
            return
        try:
            done = decode(job)
        except Exception:
            done = Decoded(job.ref, None)
        outbox.put(done)


class DecodeWorker:
    """One daemon decode thread, started on the first ``submit``."""

    def __init__(self, decode: Callable[[DecodeJob], Decoded] = decode_image) -> None:
        self._decode = decode
        self._inbox: queue.SimpleQueue[DecodeJob | None] = queue.SimpleQueue()
        self._outbox: queue.SimpleQueue[Decoded] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    def submit(self, job: DecodeJob) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=_worker, name=WORKER_NAME, daemon=True,
                                            args=(self._inbox, self._outbox, self._decode))
            self._thread.start()
        self._inbox.put(job)

    def poll(self) -> Decoded | None:
        """A finished result, or None; never blocks."""
        try:
            return self._outbox.get_nowait()
        except queue.Empty:
            return None

    def stop(self, timeout: float = STOP_WAIT_S) -> bool:
        """Ask the thread to end after its current job and wait up to ``timeout`` seconds.
        Returns whether it ended; a daemon thread still decoding is abandoned."""
        thread, self._thread = self._thread, None
        if thread is None:
            return True
        self._inbox.put(None)
        thread.join(timeout)
        return not thread.is_alive()


class _SyncDecoder:
    """``PREFETCH_THREADED = False``: the same decode, run inside ``pump()``."""

    def __init__(self, decode: Callable[[DecodeJob], Decoded] = decode_image) -> None:
        self._decode = decode
        self._done: Decoded | None = None

    def submit(self, job: DecodeJob) -> None:
        try:
            self._done = self._decode(job)
        except Exception:
            self._done = Decoded(job.ref, None)

    def poll(self) -> Decoded | None:
        done, self._done = self._done, None
        return done

    def stop(self, timeout: float = STOP_WAIT_S) -> bool:
        self._done = None
        return True


class ImagePrefetcher:
    """§7.7: ``request`` replaces the queue; ``pump`` runs once per frame on the main
    thread, adopts at most one finished image and sends at most one more."""

    def __init__(self, assets: PrefetchAssets, *, threaded: bool | None = None,
                 decode: Callable[[DecodeJob], Decoded] = decode_image) -> None:
        self.assets = assets
        self.threaded = PREFETCH_THREADED if threaded is None else threaded
        self._decoder: DecodeWorker | _SyncDecoder = (
            DecodeWorker(decode) if self.threaded else _SyncDecoder(decode))
        self._queue: deque[PrefetchRequest] = deque()
        self._in_flight: str | None = None            # the ref the decoder has
        self._batch_bytes = 0                         # header estimates sent for this request
        self._stopped = False

    @property
    def pending(self) -> bool:
        """Whether a request is still being worked on: queued refs or a job in flight (F15
        I-7 reads it through ``StageView.prefetch_pending``)."""
        return bool(self._queue) or self._in_flight is not None

    @property
    def worker(self) -> threading.Thread | None:
        """The decode thread, once started (tests)."""
        decoder = self._decoder
        return decoder.thread if isinstance(decoder, DecodeWorker) else None

    def request(self, wanted: Iterable[PrefetchRequest]) -> None:
        """Replace the queue with ``wanted``, nearest first, without refs already cached,
        already in flight, or repeated; the budget for this request starts again."""
        if self._stopped:
            return
        queue_: deque[PrefetchRequest] = deque()
        seen: set[str] = set()
        for item in wanted:
            ref = item.ref
            if ref in seen or ref == self._in_flight or (
                    self.assets.is_cached(ref) and not item.rescale):
                continue
            seen.add(ref)
            queue_.append(item)
        self._queue = queue_
        self._batch_bytes = 0

    def pump(self) -> None:
        """Once per frame, main thread: (1) adopt a finished image, if any; (2) if the
        decoder is idle, read the next queued file and send it."""
        if self._stopped:
            return
        done = self._decoder.poll()
        if done is not None:
            self._adopt(done)
        if self._in_flight is None:
            self._send_next()

    def stop(self, timeout: float = STOP_WAIT_S) -> bool:
        """At shutdown: drop the queue and end the worker (waits up to ``timeout``)."""
        self._stopped = True
        self._queue.clear()
        self._in_flight = None
        return self._decoder.stop(timeout)

    def _adopt(self, done: Decoded) -> None:
        self._in_flight = None
        assets = self.assets
        if done.source is None:
            return                    # failed (a later image() logs it)
        cached = assets.is_cached(done.ref)       # loaded meanwhile, or an F38 rescale
        variants: dict[tuple, pygame.Surface] = {}
        if done.variant is not None and assets.scale_filter != "pixel":   # changed meanwhile
            key = assets.variant_key(done.ref, done.variant.get_size(), done.flip_x)
            variants[key] = assets.convert(done.variant)
        if cached and not variants:
            return
        assets.adopt(done.ref, None if cached else assets.convert(done.source), variants)

    def _send_next(self) -> None:
        """At most one file read: cached refs are passed over without one."""
        assets = self.assets
        while self._queue:
            item = self._queue.popleft()
            if assets.is_cached(item.ref) and not item.rescale:
                continue
            found = assets.read_image_bytes(item.ref)
            if found is None:
                return                                    # dropped; image() logs it later
            data, hint, width, height = found
            cost = width * height * 4
            budget = assets.budget_bytes
            if cost > PREFETCH_ONE_MAX * budget:
                return                                    # never decoded ahead
            if self._batch_bytes + cost > PREFETCH_TOTAL_MAX * budget:
                self._queue.clear()                       # the request stops here
                return
            self._batch_bytes += cost
            target = item.target(width, height) if item.target is not None else None
            if assets.scale_filter == "pixel":
                target = None         # I-8: the worker only smoothscales; pixel art isn't pre-scaled
            size, flip = (None, False) if target is None else target
            self._in_flight = item.ref
            self._decoder.submit(DecodeJob(item.ref, data, hint, size, flip))
            return


__all__ = ["PREFETCH_ONE_MAX", "PREFETCH_THREADED", "PREFETCH_TOTAL_MAX", "DecodeJob",
           "DecodeWorker", "Decoded", "ImagePrefetcher", "PrefetchAssets", "PrefetchRequest",
           "decode_image"]
