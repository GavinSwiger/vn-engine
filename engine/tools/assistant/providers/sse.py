"""A server-sent-events decoder bounded in bytes, and strict JSON (F48 ``04-technical.md``
§3.1; 01 §4.4, §7.2; ``05-security.md`` SEC-F48-19, AB-16).

Why this module exists: a provider's stream is untrusted bytes of unknown size. A hostile or
broken server can send one endless line, endless ``ping`` events (no text, so a character cap
never trips), invalid UTF-8 or JSON nested 100,000 deep. So the decoder counts bytes, not
characters: a line and an event's data are at most 1 MiB each, and a whole response at most
32 MiB, pings and ignored events included. Anything past a cap, or undecodable, is an
``SseError``, which the providers turn into 01 §4.4's "couldn't read" text.

- ``SseDecoder.feed(chunk)`` → the events completed by ``chunk``; ``finish()`` at the end.
  Lines end in LF, CRLF or CR (a CR at a chunk's end waits for the next chunk). ``:`` lines
  are comments; ``event`` and ``data`` are kept, other fields ignored.
- ``loads(text)``: ``json.loads`` that refuses ``NaN``/``Infinity``, too-deep nesting and lone
  surrogates (which can't be sent back as UTF-8), all as ``SseError``.
"""

import json
import re
from dataclasses import dataclass
from typing import Final

SSE_LINE_MAX_BYTES: Final = 1024 * 1024
SSE_DATA_MAX_BYTES: Final = 1024 * 1024
STREAM_MAX_BYTES: Final = 32 * 1024 * 1024
_LINE_END: Final = re.compile(rb"\r\n|\r|\n")
_SURROGATE: Final = re.compile("[\ud800-\udfff]")


class SseError(ValueError):
    """The stream can't be read: ``reason`` is a short engine word (for logs), never text
    from the stream."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str          # "" when the server sent no ``event:`` line ("message")
    data: str


class SseDecoder:
    """Feed it the response bytes; it returns whole events."""

    def __init__(self, *, line_max: int = SSE_LINE_MAX_BYTES,
                 data_max: int = SSE_DATA_MAX_BYTES, total_max: int = STREAM_MAX_BYTES) -> None:
        self._line_max = line_max
        self._data_max = data_max
        self._total_max = total_max
        self.total = 0
        self._pending = bytearray()
        self._event = ""
        self._data: list[str] = []
        self._data_size = 0
        self._first = True

    def feed(self, chunk: bytes) -> list[SseEvent]:
        self.total += len(chunk)
        if self.total > self._total_max:
            raise SseError("stream too large")
        self._pending += chunk
        return self._lines(final=False)

    def finish(self) -> list[SseEvent]:
        """The events left at the end of the stream (an unterminated last event counts)."""
        events = self._lines(final=True)
        if self._pending:
            events += self._line(bytes(self._pending))
            self._pending.clear()
        events += self._line(b"")
        return events

    def _lines(self, *, final: bool) -> list[SseEvent]:
        events: list[SseEvent] = []
        start = 0
        pending = self._pending
        for match in _LINE_END.finditer(pending):
            if match.group() == b"\r" and match.end() == len(pending) and not final:
                break                       # maybe the CR of a CRLF split across chunks
            events += self._line(bytes(pending[start:match.start()]))
            start = match.end()
        if start:
            del pending[:start]
        if len(pending) > self._line_max:
            raise SseError("line too long")
        return events

    def _line(self, raw: bytes) -> list[SseEvent]:
        if len(raw) > self._line_max:
            raise SseError("line too long")
        if self._first:
            self._first = False
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
        if not raw:
            if not self._data:
                self._event = ""
                return []
            event = SseEvent(self._event, "\n".join(self._data))
            self._event, self._data, self._data_size = "", [], 0
            return [event]
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SseError("not UTF-8") from None
        if line.startswith(":"):
            return []
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            self._data_size += len(raw) + 1
            if self._data_size > self._data_max:
                raise SseError("event too large")
            self._data.append(value)
        elif name == "event":
            self._event = value
        return []


def _no_constant(name: str) -> object:
    raise ValueError(name)


def loads(text: str) -> object:
    """Strict JSON: ``SseError`` for bad JSON, ``NaN``/``Infinity``, too-deep nesting or a
    lone surrogate anywhere (keys included)."""
    try:
        value = json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise SseError("bad JSON") from None
    if _SURROGATE.search(text) is None and "\\u" not in text:
        return value
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _SURROGATE.search(item):
                raise SseError("lone surrogate")
        elif isinstance(item, dict):
            for key, inner in item.items():
                if _SURROGATE.search(key):
                    raise SseError("lone surrogate")
                stack.append(inner)
        elif isinstance(item, list):
            stack.extend(item)
    return value


__all__ = ["SSE_DATA_MAX_BYTES", "SSE_LINE_MAX_BYTES", "STREAM_MAX_BYTES", "SseDecoder",
           "SseError", "SseEvent", "loads"]
