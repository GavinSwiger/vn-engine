"""Studio's side of the helper child: argv, the request lines, reply decoding, the thumbnail
cache, and ``HelperRunner`` (F47 ``04-technical.md`` §3.1, §7.3, §8, §11; AC-F47-21).

Pure Python, no Tk, no pygame. The helper (``python -B -m engine helper GAME``,
``tools/helper.py``) is one long-lived child that draws settings stills, makes JPEG/WebP
thumbnails and plays sounds, so Studio never imports pygame (ADR-0008). Requests are one
ASCII JSON line each on its stdin (a ``still`` with unsaved ``config.toml`` text is followed
by ``checker.encode_overlay``'s bytes); replies come back in F44's framing
(``core/editorreport.py``), read by ``preview.read_child_output`` with ``decode_helper_line``.

- **Never blocks.** ``still``/``thumb``/``play``/``stop_sound`` only queue bytes; one daemon
  thread per child spawns it and writes the queue to its stdin, and a second reads its stdout
  into a queue. ``poll`` (from the window's runner loop, every 100 ms) turns replies into
  ``HelperReply`` events.
- **Started on demand, restarted after a crash.** The first request spawns the child. If it
  exits, or a request has no answer after ``HELPER_REPLY_TIMEOUT_S`` (then it is killed),
  every request in flight fails with a reason, and the next request starts a new child.
  Stills waiting behind a dead one and queued thumbnails go to the new child.
- **Newest wins per kind.** Each still kind (``textbox``, ``title``, ``stage``) is one
  lane (``stage`` stills carry their ``stage`` object; ``stagestills`` sends one at a time
  so nothing it asks for is dropped): while one
  still is in flight a newer one waits, replacing any older waiting one, and only the newest
  serial's reply is reported. ``play`` and ``stop_sound`` share the sound lane likewise.
- **Thumbnails** are cached in ``ThumbCache`` by (ref, size, file stamp), LRU 512, failures
  included, so a changed file (new size or modification time) is asked again; at most
  ``THUMBS_IN_FLIGHT`` are in flight and the rest wait.
- **Bounded.** ``decode_helper_line`` checks every reply's shape, and that a ``png`` reply's
  data is base64 of a PNG within the size caps (never raises).

``HelperRunnerLike`` is what views need, so Tk tests pass a fake, as with ``CheckRunnerLike``.

Imports ``engine.core``, its own package, and the standard library.
"""

import base64
import binascii
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from engine.core.constants import CONFIG_FILENAME
from engine.core.editorreport import (
    HELPER_EVENTS,
    HELPER_REPLY_TIMEOUT_S,
    HELPER_REQUEST_MAX,
    HELPER_STILL_KINDS,
    HELPER_STILL_MAX_WIDTH,
    HELPER_THUMB_MAX,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.paths import engine_root
from engine.core.redact import echo
from engine.tools.build.procs import without_keys
from engine.tools.editor.checker import encode_overlay
from engine.tools.editor.preview import CHILD_ENCODING, EOF, KILL_AFTER_S, read_child_output

_IS_WINDOWS = os.name == "nt"
THUMB_CACHE_ENTRIES = 512
THUMBS_IN_FLIGHT = 8
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SOUND_LANE = "sound"

# Reasons (drafts for the narrative designer; shown after "Preview not available: " or
# "This sound can't be played: ").
HELPER_STOPPED = "the helper stopped unexpectedly"
HELPER_TOO_SLOW = "the helper took too long"
COULDNT_START = "the helper couldn't start: {reason}"
CONFIG_TOO_LARGE = "config.toml is too large to preview"
STAGE_TOO_LARGE = "the stage is too large to preview"


# --- Argv and requests (04 §7.3) -------------------------------------------------------------

def helper_argv(game_dir: Path) -> list[str]:
    """The helper child's command line."""
    return [sys.executable, "-B", "-m", "engine", "helper", str(game_dir)]


def request_line(op: str, serial: int, **fields: object) -> bytes:
    """One request line, newline included."""
    return json.dumps({"v": REPORT_VERSION, "op": op, "serial": serial, **fields},
                      ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def file_stamp(game_dir: Path, ref: str) -> tuple[int, int] | None:
    """(size, modification time in ns) of ``ref`` in ``game_dir``, or None when it can't be
    read: ``ThumbCache``'s stamp."""
    try:
        found = os.stat(Path(game_dir).joinpath(*ref.split("/")))
    except (OSError, ValueError):
        return None
    return found.st_size, found.st_mtime_ns


# --- Replies ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class HelperReply:
    """The answer to one request (``op`` ``still``, ``thumb``, ``play`` or ``stop``), or a
    failure made here (a crash, a timeout, a child that didn't start). ``data`` is base64
    PNG (Tk's ``PhotoImage(data=…)`` reads it as is); ``kind`` is a still's, ``ref`` a
    thumbnail's or sound's; ``seconds`` a played sound's length (None: a streamed track)."""

    op: str
    serial: int
    ok: bool
    data: str | None = None
    width: int = 0
    height: int = 0
    seconds: float | None = None
    reason: str | None = None
    kind: str | None = None
    ref: str | None = None


def _serial(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2 ** 53


def _png(data: dict) -> dict | None:
    op, width, height, text = data.get("op"), data.get("width"), data.get("height"), \
        data.get("data")
    side = HELPER_STILL_MAX_WIDTH if op == "still" else HELPER_THUMB_MAX
    if op not in ("still", "thumb") or type(width) is not int or type(height) is not int \
            or not (1 <= width <= side and 1 <= height <= side) \
            or not isinstance(text, str) or not text:
        return None
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        return None
    if not raw.startswith(PNG_SIGNATURE):
        return None
    return {"op": op, "width": width, "height": height, "data": text}


def decode_helper_line(body: bytes) -> tuple[str, dict] | None:
    """One stdout line without its line break → ``(event, payload)``, or None when it isn't
    a helper reply or breaks a rule (ASCII JSON ≤ 1 MiB with the marker, ``v`` 1, a known
    event, a serial, ``png`` data that is base64 of a PNG within the size caps, a reason
    within ``REPORT_TEXT_MAX_CHARS``). Never raises."""
    if not isinstance(body, bytes) or not body.startswith(REPORT_MARKER) \
            or len(body) > REPORT_MAX_BYTES:
        return None
    try:
        data = json.loads(body[len(REPORT_MARKER):].decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or type(data.get("v")) is not int \
            or data["v"] != REPORT_VERSION or data.get("event") not in HELPER_EVENTS:
        return None
    event = data["event"]
    if event == "ready":
        return event, {}
    serial = data.get("serial")
    if not _serial(serial):
        return None
    payload: dict | None = None
    if event == "png":
        payload = _png(data)
    elif event == "played":
        seconds = data.get("seconds")
        if seconds is None or (type(seconds) in (int, float) and math.isfinite(seconds)
                               and seconds >= 0):
            payload = {"seconds": None if seconds is None else float(seconds)}
    elif event == "stopped":
        payload = {}
    elif event == "failed":
        reason = data.get("reason")
        if isinstance(reason, str) and len(reason) <= REPORT_TEXT_MAX_CHARS:
            payload = {"reason": reason}
    if payload is None:
        return None
    payload["serial"] = serial
    return event, payload


# --- Thumbnail cache (04 §3.1, §11) ----------------------------------------------------------

class ThumbCache:
    """``HelperReply``s of thumbnails by (ref, size, stamp), least recently used out first.
    Failures are kept too, so a broken file isn't asked for again until it changes."""

    def __init__(self, entries: int = THUMB_CACHE_ENTRIES) -> None:
        self.entries = entries
        self._items: OrderedDict[Hashable, HelperReply] = OrderedDict()

    def get(self, key: Hashable) -> HelperReply | None:
        found = self._items.get(key)
        if found is not None:
            self._items.move_to_end(key)
        return found

    def put(self, key: Hashable, reply: HelperReply) -> None:
        self._items[key] = reply
        self._items.move_to_end(key)
        while len(self._items) > self.entries:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


# --- The runner (04 §7.3) --------------------------------------------------------------------

class HelperRunnerLike(Protocol):
    """What Settings, the Database and the form pickers need; Tk tests pass a fake."""

    def still(self, kind: str, width: int, config: bytes | None,
              stage: dict | None = None) -> int: ...

    def thumb(self, ref: str, size: int, stamp: Hashable = None) -> HelperReply | None: ...

    def play(self, ref: str) -> int: ...

    def stop_sound(self) -> int | None: ...

    def poll(self) -> list[HelperReply]: ...

    def stop(self) -> None: ...


_SPAWNED = "spawned"
_SPAWN_FAILED = "spawn failed"


def _drop(line: bytes) -> None:
    """The helper's other stdout lines go nowhere (its own stdout is the null device)."""


def _run_child(popen: Callable[..., subprocess.Popen], argv: list[str], kwargs: dict,
               outbox: "queue.SimpleQueue[bytes | None]",
               put: Callable[[tuple[str, object]], None]) -> None:
    """The child's writer thread: spawn, start the reader thread, then write each queued
    request to stdin until a None (or a broken pipe), and close it. Touches only the pipes,
    ``outbox`` and ``put``."""
    try:
        proc = popen(argv, **kwargs)
    except (OSError, ValueError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
        put((_SPAWN_FAILED, echo(reason)))
        put((EOF, None))
        return
    put((_SPAWNED, proc))
    threading.Thread(target=read_child_output, name="vn-helper-reader", daemon=True,
                     args=(proc.stdout, put, _drop, decode_helper_line)).start()
    try:
        while True:
            data = outbox.get()
            if data is None:
                break
            proc.stdin.write(data)
            proc.stdin.flush()
    except (OSError, ValueError, AttributeError):
        pass                                        # the child ended
    finally:
        try:
            proc.stdin.close()
        except (OSError, ValueError, AttributeError):
            pass


@dataclass
class _Request:
    op: str
    serial: int
    lane: str
    data: bytes
    kind: str | None = None
    ref: str | None = None
    key: Hashable = None
    sent_at: float = 0.0


class _Child:
    def __init__(self, thread: threading.Thread,
                 outbox: "queue.SimpleQueue[bytes | None]",
                 messages: "queue.SimpleQueue[tuple[str, object]]") -> None:
        self.thread = thread
        self.outbox = outbox
        self.messages = messages
        self.proc: subprocess.Popen | None = None
        self.spawn_failed: str | None = None
        self.eof = False
        self.ready = False


class HelperRunner:
    """Talks to one helper child for one game folder (module docstring). ``popen``,
    ``clock`` and ``argv`` are for tests; ``cache`` is the ``ThumbCache``."""

    def __init__(self, game_dir: Path, *,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic,
                 argv: Callable[[Path], list[str]] = helper_argv) -> None:
        self.game_dir = Path(game_dir)
        self.cache = ThumbCache()
        self._popen = popen
        self._clock = clock
        self._argv = argv
        self._child: _Child | None = None
        self._serial = 0
        self._latest: dict[str, int] = {}           # lane → newest serial asked
        self._held: dict[str, _Request] = {}         # still lane → newest waiting request
        self._inflight: deque[_Request] = deque()    # sent, unanswered, in order
        self._waiting: deque[_Request] = deque()     # thumbnails past THUMBS_IN_FLIGHT
        self._asked: set[Hashable] = set()           # thumbnail keys waiting or in flight
        self._events: list[HelperReply] = []         # replies made here, for the next poll

    @property
    def alive(self) -> bool:
        """A child is spawned or starting."""
        return self._child is not None

    @property
    def process(self) -> subprocess.Popen | None:
        return self._child.proc if self._child is not None else None

    @property
    def busy(self) -> bool:
        """Requests are in flight or waiting (Settings' "Updating preview…")."""
        return bool(self._inflight or self._held or self._waiting)

    # --- Requests ---------------------------------------------------------------------

    def _next(self) -> int:
        self._serial += 1
        return self._serial

    def still(self, kind: str, width: int, config: bytes | None,
              stage: dict | None = None) -> int:
        """Ask for a ``kind`` still ``width`` px wide (≤ 640) from ``config`` (the unsaved
        ``config.toml`` bytes; None: the saved file). A ``stage`` still needs ``stage``
        (``tools/helper.parse_stage``'s shape). Returns its serial; only the newest serial
        of ``kind`` is ever reported."""
        if kind not in HELPER_STILL_KINDS or (kind == "stage") != (stage is not None):
            raise ValueError(f"unknown still kind {kind!r}")
        serial = self._next()
        lane = "still:" + kind
        self._latest[lane] = serial
        width = max(16, min(HELPER_STILL_MAX_WIDTH, int(width)))
        extra = {} if stage is None else {"stage": stage}
        data = request_line("still", serial, kind=kind, width=width,
                            overlay=config is not None, **extra)
        if len(data) - 1 > HELPER_REQUEST_MAX:
            self._events.append(HelperReply("still", serial, False, kind=kind,
                                            reason=STAGE_TOO_LARGE))
            return serial
        if config is not None:
            overlay = encode_overlay([(CONFIG_FILENAME, config)])
            if overlay is None:
                self._events.append(HelperReply("still", serial, False, kind=kind,
                                                reason=CONFIG_TOO_LARGE))
                return serial
            data += overlay
        request = _Request("still", serial, lane, data, kind=kind)
        if any(sent.lane == lane for sent in self._inflight):
            self._held[lane] = request                  # replaces an older waiting one
        else:
            self._send(request)
        return serial

    def thumb(self, ref: str, size: int, stamp: Hashable = None) -> HelperReply | None:
        """The cached thumbnail of ``ref`` fitting ``size`` px (≤ 384), or None after asking
        the helper for it (its reply comes from ``poll`` and is cached). ``stamp`` defaults
        to ``file_stamp``: a changed file is asked for again."""
        size = max(8, min(HELPER_THUMB_MAX, int(size)))
        if stamp is None:
            stamp = file_stamp(self.game_dir, ref)
        key = (ref, size, stamp)
        found = self.cache.get(key)
        if found is not None or key in self._asked:
            return found
        self._asked.add(key)
        serial = self._next()
        request = _Request("thumb", serial, "thumb", request_line("thumb", serial, ref=ref,
                                                                  size=size),
                           ref=ref, key=key)
        if self._thumbs_in_flight() < THUMBS_IN_FLIGHT:
            self._send(request)
        else:
            self._waiting.append(request)
        return None

    def play(self, ref: str) -> int:
        """Play ``ref`` (``audio/…``), stopping any other sound. Returns its serial."""
        serial = self._next()
        self._latest[SOUND_LANE] = serial
        self._send(_Request("play", serial, SOUND_LANE, request_line("play", serial, ref=ref),
                            ref=ref))
        return serial

    def stop_sound(self) -> int | None:
        """Stop the playing sound (switching tab, file or category). None, and nothing sent,
        when no child runs (so nothing plays)."""
        if self._child is None:
            return None
        serial = self._next()
        self._latest[SOUND_LANE] = serial
        self._send(_Request("stop", serial, SOUND_LANE, request_line("stop", serial)))
        return serial

    # --- Polling ----------------------------------------------------------------------

    def poll(self) -> list[HelperReply]:
        """Every reply since the last call, oldest first. Never blocks."""
        events, self._events = self._events, []
        child = self._child
        if child is not None:
            self._drain(child, events)
            self._watch(child, events)
        return events

    def stop(self, timeout_s: float = KILL_AFTER_S) -> None:
        """End the child (Studio closing): close its stdin, wait up to ``timeout_s``, then
        terminate and kill. Nothing waiting is sent."""
        child, self._child = self._child, None
        self._inflight.clear()
        self._held.clear()
        self._waiting.clear()
        self._asked.clear()
        if child is None:
            return
        child.outbox.put(None)
        proc = child.proc
        if proc is None and child.spawn_failed is None:
            end = self._clock() + timeout_s
            while proc is None:
                try:
                    kind, payload = child.messages.get(timeout=max(0.0, end - self._clock()))
                except queue.Empty:
                    break
                if kind == _SPAWNED:
                    proc = payload                  # type: ignore[assignment]
                elif kind in (_SPAWN_FAILED, EOF):
                    break
        if proc is not None:
            for end in (None, _terminate, _kill):
                if end is not None:
                    end(proc)
                try:
                    proc.wait(timeout_s)
                    break
                except subprocess.TimeoutExpired:
                    continue
        child.thread.join(timeout_s)

    # --- Internals --------------------------------------------------------------------

    def _thumbs_in_flight(self) -> int:
        return sum(1 for sent in self._inflight if sent.op == "thumb")

    def _spawn(self) -> _Child:
        env = without_keys()             # F48 SEC-F48-22
        env["PYTHONIOENCODING"] = CHILD_ENCODING
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        kwargs: dict = {"cwd": str(engine_root()), "stdin": subprocess.PIPE,
                        "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL, "env": env}
        if _IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        outbox: "queue.SimpleQueue[bytes | None]" = queue.SimpleQueue()
        messages: "queue.SimpleQueue[tuple[str, object]]" = queue.SimpleQueue()
        thread = threading.Thread(target=_run_child, name="vn-helper-child", daemon=True,
                                  args=(self._popen, self._argv(self.game_dir), kwargs,
                                        outbox, messages.put))
        child = _Child(thread, outbox, messages)
        thread.start()
        return child

    def _send(self, request: _Request) -> None:
        if self._child is None:
            self._child = self._spawn()
        request.sent_at = self._clock()
        self._inflight.append(request)
        self._child.outbox.put(request.data)

    def _drain(self, child: _Child, events: list[HelperReply]) -> None:
        while True:
            try:
                kind, payload = child.messages.get_nowait()
            except queue.Empty:
                return
            if kind == _SPAWNED:
                child.proc = payload                # type: ignore[assignment]
            elif kind == _SPAWN_FAILED:
                child.spawn_failed = str(payload)
            elif kind == EOF:
                child.eof = True
            elif kind == "ready":
                child.ready = True
            else:
                self._answer(kind, payload, events)  # type: ignore[arg-type]

    def _answer(self, event: str, payload: dict, events: list[HelperReply]) -> None:
        """A reply answers the request in flight with its serial (the child answers in
        order, but nothing here relies on it); one that matches nothing is dropped."""
        serial = payload["serial"]
        request = next((sent for sent in self._inflight if sent.serial == serial), None)
        if request is None:
            return
        self._inflight.remove(request)
        if event == "png":
            reply = HelperReply(request.op, serial, True, data=payload["data"],
                                width=payload["width"], height=payload["height"],
                                kind=request.kind, ref=request.ref)
        elif event == "failed":
            reply = HelperReply(request.op, serial, False, reason=payload["reason"],
                                kind=request.kind, ref=request.ref)
        else:
            reply = HelperReply(request.op, serial, True, seconds=payload.get("seconds"),
                                kind=request.kind, ref=request.ref)
        self._deliver(request, reply, events)

    def _deliver(self, request: _Request, reply: HelperReply,
                 events: list[HelperReply]) -> None:
        if request.op == "thumb":
            self.cache.put(request.key, reply)
            self._asked.discard(request.key)
            events.append(reply)
            while self._waiting and self._thumbs_in_flight() < THUMBS_IN_FLIGHT:
                self._send(self._waiting.popleft())
            return
        if request.serial == self._latest.get(request.lane):
            events.append(reply)
        held = self._held.pop(request.lane, None)
        if held is not None:
            self._send(held)

    def _watch(self, child: _Child, events: list[HelperReply]) -> None:
        proc = child.proc
        if child.spawn_failed is not None:
            self._lost(COULDNT_START.format(reason=child.spawn_failed), events)
            return
        code = proc.poll() if proc is not None else None
        if code is not None or child.eof:
            if code is None and proc is not None:
                _kill(proc)                         # its stdout closed: no reply can come
            self._lost(HELPER_STOPPED, events)
            return
        if self._inflight and self._clock() - self._inflight[0].sent_at \
                >= HELPER_REPLY_TIMEOUT_S:
            if proc is not None:
                _kill(proc)
            self._lost(HELPER_TOO_SLOW, events)

    def _lost(self, reason: str, events: list[HelperReply]) -> None:
        """The child is gone: each request in flight fails with ``reason``; stills waiting
        behind them and queued thumbnails go to a new child."""
        child, self._child = self._child, None
        if child is not None:
            child.outbox.put(None)
        lost, self._inflight = list(self._inflight), deque()
        for request in lost:
            self._deliver_lost(request, reason, events)
        retry = [self._held.pop(lane) for lane in list(self._held)] + list(self._waiting)
        self._waiting.clear()
        for request in retry:
            self._send(request)

    def _deliver_lost(self, request: _Request, reason: str,
                      events: list[HelperReply]) -> None:
        reply = HelperReply(request.op, request.serial, False, reason=reason,
                            kind=request.kind, ref=request.ref)
        if request.op == "thumb":
            self._asked.discard(request.key)        # not cached: asked again next time
            events.append(reply)
        elif request.serial == self._latest.get(request.lane):
            events.append(reply)


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except OSError:
        pass


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass


__all__ = ["HelperReply", "HelperRunner", "HelperRunnerLike", "ThumbCache",
           "decode_helper_line", "file_stamp", "helper_argv", "request_line"]
