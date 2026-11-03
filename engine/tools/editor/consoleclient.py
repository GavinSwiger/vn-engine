"""Studio's side of the developer console channel (F40 ``04`` §3, §7.5; ``05`` SEC-F40-06,
SEC-F40-09). Tested with W2's wiring (AC-F40-30..33, -38).

Why this module exists: Studio drives the running game's console without typing code: Run ▸
Open console in the game, Jump the game here, and Database's **In the game now** with
**Change…**. It needs the stdin message lines to send and a safe reading of the answers.

- **Messages** (``open_line``, ``values_line``, ``jump_line``, ``set_line``): F39's channel,
  one ASCII JSON line each, ``{"v":1,"msg":"console","do":…}`` with exactly the keys of its
  ``do``. Studio sends values and scene names only, never code: a ``set`` value is literal
  text the game reads with F44's ``parse_literal``. A label, name or line over its limit
  gives None (the caller shows ``BAD_VALUE`` for a Change…, decision 10).
- **Events**: ``decode_console`` checks a decoded ``console`` report (exact keys and types,
  the caps of ``core/editorreport.py``) into a ``ConsoleEvent``; ``preview.py`` calls it.
- **Display**: the game's answer is untrusted text (game code can print a forged report
  line). ``shown`` escapes controls, line separators, bidi characters and lone surrogates,
  and cuts to ``CONSOLE_SHOWN_MAX``. Nothing is ever acted on (no path, command, code or
  place to open), and nothing here logs.
- ``ConsoleTracker``: one outstanding request per ``do`` with a ``CONSOLE_ANSWER_S``
  deadline. An event with no outstanding request is ignored; ``values`` names Studio doesn't
  know are ignored; a request past its deadline is ``overdue`` (``DIDNT_ANSWER``).

Imports ``engine.core`` and the standard library only (no pygame, no Tk).
"""

import json
import re
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

from engine.core.editorreport import (
    CONSOLE_ANSWER_S,
    CONSOLE_DO,
    CONSOLE_EVENT,
    CONSOLE_LABEL_MAX,
    CONSOLE_MESSAGE,
    CONSOLE_NAME_MAX,
    CONSOLE_SHOWN_MAX,
    CONSOLE_TEXT_MAX,
    CONSOLE_VALUE_TEXT_MAX,
    CONSOLE_VALUES_MAX,
    RELOAD_MESSAGE_MAX,
    REPORT_VERSION,
)
from engine.core.redact import escape_controls, truncate

# --- Texts (01 §6.4; 04 §18 decision 10) -----------------------------------------------------

STATUS = "Console: {text}"
DIDNT_ANSWER = "Console: the game didn't answer."
STATUS_SHOW_S = 5.0                     # a console status line shows this long
BAD_VALUE = ("That isn't a value the console understands. Use a number, True, False, None, "
             "text in quotes, a list or a dict.")    # 01 §6.3, for a Change… over 4 KiB

# --- Messages (Studio → the game's stdin) ----------------------------------------------------


def _line(do: str, **fields: str) -> bytes | None:
    data = json.dumps({"v": REPORT_VERSION, "msg": CONSOLE_MESSAGE, "do": do, **fields},
                      ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(data) > RELOAD_MESSAGE_MAX:
        return None
    return data + b"\n"


def _field(value: object, most: int) -> bool:
    return type(value) is str and 1 <= len(value) <= most


def open_line() -> bytes:
    """Open the console in the game."""
    return _line("open")  # type: ignore[return-value]


def values_line() -> bytes:
    """Ask for every story variable and meter value."""
    return _line("values")  # type: ignore[return-value]


def jump_line(label: str) -> bytes | None:
    """Jump the game to ``label``; None when it isn't 1 to ``CONSOLE_LABEL_MAX`` characters."""
    if not _field(label, CONSOLE_LABEL_MAX):
        return None
    return _line("jump", label=label)


def set_line(name: str, value: str) -> bytes | None:
    """Set ``name`` to the literal text ``value`` (never code); None when the name isn't 1 to
    ``CONSOLE_NAME_MAX`` characters, ``value`` isn't text, or the line passes 4 KiB."""
    if not _field(name, CONSOLE_NAME_MAX) or type(value) is not str:
        return None
    return _line("set", name=name, value=value)


# --- Events (the game → Studio) --------------------------------------------------------------

@dataclass(frozen=True)
class ConsoleEvent:
    """A checked ``console`` report, still untrusted text: show it only through ``shown``.
    ``story``, ``values`` and ``left_out`` are set only for ``do == "values"``."""

    do: str
    ok: bool
    text: str
    story: bool | None = None
    values: tuple[tuple[str, str], ...] = ()
    left_out: int = 0


_BASE_KEYS = frozenset({"v", "event", "do", "ok", "text"})
_VALUES_KEYS = _BASE_KEYS | {"story", "values", "left_out"}


def _text(value: object, most: int) -> bool:
    return type(value) is str and len(value) <= most


def decode_console(data: dict) -> ConsoleEvent | None:
    """A decoded report object whose ``event`` is ``console`` → ``ConsoleEvent``, or None
    when its keys or types are wrong (the line is dropped)."""
    do = data.get("do")
    if data.get("event") != CONSOLE_EVENT or do not in CONSOLE_DO:
        return None
    if data.keys() != (_VALUES_KEYS if do == "values" else _BASE_KEYS):
        return None
    ok, text = data["ok"], data["text"]
    if type(ok) is not bool or not _text(text, CONSOLE_TEXT_MAX):
        return None
    if do != "values":
        return ConsoleEvent(do, ok, text)
    story, values, left_out = data["story"], data["values"], data["left_out"]
    if type(story) is not bool or type(left_out) is not int or left_out < 0 or \
            type(values) is not list or len(values) > CONSOLE_VALUES_MAX:
        return None
    pairs = []
    for entry in values:
        if type(entry) is not list or len(entry) != 2 or \
                not _text(entry[0], CONSOLE_NAME_MAX) or \
                not _text(entry[1], CONSOLE_VALUE_TEXT_MAX):
            return None
        pairs.append((entry[0], entry[1]))
    return ConsoleEvent(do, ok, text, story, tuple(pairs), left_out)


# --- Display ---------------------------------------------------------------------------------

_SURROGATE = re.compile("[\ud800-\udfff]")


def shown(text: str, limit: int = CONSOLE_SHOWN_MAX) -> str:
    """``text`` as display text: controls, line separators and bidi characters escaped (F01's
    ``escape_controls``), lone surrogates as U+FFFD, cut to ``limit`` characters with ``…``.
    The input is cut first, so a long text costs no more than a short one."""
    if type(text) is not str:
        return ""
    head = _SURROGATE.sub("�", text[:limit + 1])
    return truncate(escape_controls(head), limit)


def status_text(event: ConsoleEvent) -> str:
    """The status-bar line for an answer: ``Console: {text}``."""
    return STATUS.format(text=shown(event.text))


# --- Tracking requests -----------------------------------------------------------------------

@dataclass(frozen=True)
class ConsoleAnswer:
    """An answer Studio may show: ``status`` (None for an empty text), and for ``values``
    the known names' display texts (``story`` False: no story running)."""

    do: str
    ok: bool
    status: str | None
    story: bool | None = None
    values: dict[str, str] = field(default_factory=dict)
    left_out: int = 0


class ConsoleTracker:
    """The requests Studio is waiting on: one per ``do``, each with a 2 s deadline."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 answer_s: float = CONSOLE_ANSWER_S) -> None:
        self._clock = clock
        self._answer_s = answer_s
        self._due: dict[str, float] = {}

    def sent(self, do: str) -> None:
        """A ``do`` request was sent now (a second one replaces the first's deadline)."""
        if do in CONSOLE_DO:
            self._due[do] = self._clock() + self._answer_s

    def waiting(self, do: str) -> bool:
        return do in self._due

    def receive(self, event: ConsoleEvent,
                known: Collection[str] | None = None) -> ConsoleAnswer | None:
        """The answer to an outstanding request, or None (no request outstanding: ignored).
        For ``values``, names not in ``known`` (when given) are ignored."""
        if type(event) is not ConsoleEvent or self._due.pop(event.do, None) is None:
            return None
        status = status_text(event) if event.text else None
        if event.do != "values":
            return ConsoleAnswer(event.do, event.ok, status)
        values = {name: shown(text, CONSOLE_VALUE_TEXT_MAX) for name, text in event.values
                  if known is None or name in known}
        return ConsoleAnswer(event.do, event.ok, status, event.story, values, event.left_out)

    def overdue(self) -> list[str]:
        """The requests past their deadline, now given up (show ``DIDNT_ANSWER``)."""
        now = self._clock()
        late = [do for do, due in self._due.items() if now >= due]
        for do in late:
            del self._due[do]
        return late

    def clear(self) -> None:
        """The game stopped: nothing is outstanding."""
        self._due.clear()


__all__ = ["BAD_VALUE", "ConsoleAnswer", "ConsoleEvent", "ConsoleTracker", "DIDNT_ANSWER",
           "STATUS", "STATUS_SHOW_S", "decode_console", "jump_line", "open_line", "set_line",
           "shown", "status_text", "values_line"]
