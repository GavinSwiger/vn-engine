"""The typewriter: which graphemes of a line are shown, and when (F05 ``04-technical.md`` §7.5).

Why this module exists: typing, pauses, click-waits, and page waits are pure timing, so they
live apart from fonts and drawing and are tested with a fake clock (06 §0.6). The layout
(``textlayout.LineLayout``) turns a body into one *timeline* per page: ``GlyphSlot``s
(spaces included, ``\\n`` not; SR-F05-09), ``PauseSlot`` (``{pause=X}``), ``WAIT``
(``{pause}``), and ``PAGE_BREAK`` or ``END``. The ``Typewriter`` walks it, driven only by
the frame loop's ``dt`` (``tick``) and by advances (``press``).

Rules (§7.5):

- A grapheme is shown at the start of its slot; the slot lasts ``1 / rate`` with
  ``rate = speed() × slot.speed``. ``speed()`` (the current cps: F16's setting or
  ``[textbox] cps``) is read per slot, so a live change applies at once; ``speed() == 0``
  (cps 0 or the player's instant setting) or ``INSTANT`` (``{speed=instant}``) costs 0.
  ``{speed}`` is relative and the inner tag wins (the parser resolves that into
  ``Style.speed``).
- Timed pauses apply even when text is instant (SR-F05-11).
- ``press()``: while typing, show everything up to the next ``{pause}``, page break, or the
  end, skipping timed pauses (SR-F05-12); at a wait, continue; at the end, ``ADVANCE``.

Events: ``run()`` and ``tick()`` return the events since the last call, including those of
``press()`` and ``complete_all()`` in between (``take_events()`` drains them directly). A
completing press emits ``Waiting`` or one ``Completed(True)`` and **no** ``GlyphShown``, so
per-character listeners (F06 blips) stop at once. ``TypingListener`` and ``deliver`` are the
seam the textbox screen fans these out through (F06, F15, F38; SPEC step 8).

Pure Python: no pygame, no fonts, no clock of its own (ADR-0005 determinism; F17 reuses it).
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol

from engine.runtime.commands import INSTANT

EPS: Final = 1e-9                   # slack when comparing summed frame times with costs


# --- Timeline slots (built by textlayout, consumed here) --------------------------------------

@dataclass(frozen=True, slots=True)
class GlyphSlot:
    """One shown grapheme. ``index`` counts the line's graphemes from 0 (spaces included,
    ``\\n`` not); ``speed`` is its ``Style.speed`` (× the current speed, or ``INSTANT``)."""

    index: int
    text: str
    speed: float = 1.0


@dataclass(frozen=True, slots=True)
class PauseSlot:
    """``{pause=X}``: typing stops for ``seconds``, with no indicator."""

    seconds: float


@dataclass(frozen=True, slots=True)
class WaitSlot:
    """``{pause}``: wait for an advance, with the line indicator."""


@dataclass(frozen=True, slots=True)
class PageBreakSlot:
    """The end of a page that is not the last: wait for an advance, with the page indicator."""


@dataclass(frozen=True, slots=True)
class EndSlot:
    """The end of the line."""


WAIT: Final = WaitSlot()
PAGE_BREAK: Final = PageBreakSlot()
END: Final = EndSlot()

Slot = GlyphSlot | PauseSlot | WaitSlot | PageBreakSlot | EndSlot


class Timeline(Protocol):
    """What the typewriter needs from a layout (``textlayout.LineLayout``)."""

    @property
    def glyph_count(self) -> int: ...

    def timeline(self, k: int) -> Sequence[Slot]:
        """Page ``k``'s slots, ending with ``PAGE_BREAK`` or (last page) ``END``."""
        ...

    def all_pages(self) -> int: ...


# --- States, results, events -------------------------------------------------------------------

class TypeState(Enum):
    TYPING = "typing"
    PAUSED = "paused"               # in a {pause=X}
    WAIT_CLICK = "wait_click"       # at a {pause}
    WAIT_PAGE = "wait_page"         # at a page break
    COMPLETE = "complete"           # the whole line is shown


class PressResult(Enum):
    COMPLETED = "completed"         # typing jumped to the next stop
    CONTINUED = "continued"         # a {pause} was dismissed
    NEXT_PAGE = "next_page"         # the next page started
    ADVANCE = "advance"             # the line was complete: the story may move on


class WaitKind(Enum):
    CLICK = "click"                 # {pause}: the line indicator
    PAGE = "page"                   # page break: the page indicator


@dataclass(frozen=True, slots=True)
class GlyphShown:
    index: int
    grapheme: str


@dataclass(frozen=True, slots=True)
class PauseStarted:
    seconds: float


@dataclass(frozen=True, slots=True)
class Waiting:
    kind: WaitKind


@dataclass(frozen=True, slots=True)
class Completed:
    by_press: bool                  # True: a press or complete_all() finished the line


TypeEvent = GlyphShown | PauseStarted | Waiting | Completed


class TypingListener(Protocol):
    """Per-character typing seam (F06 blips, F15 auto/skip timers, F38). A completing press
    gives one ``completed(True)`` and no ``glyph_shown``."""

    def glyph_shown(self, index: int, grapheme: str) -> None: ...

    def pause_started(self, seconds: float) -> None: ...

    def waiting(self, kind: WaitKind) -> None: ...

    def completed(self, by_press: bool) -> None: ...


def deliver(events: Iterable[TypeEvent], listeners: Sequence[TypingListener]) -> None:
    """Hand each event, in order, to every listener."""
    for event in events:
        for listener in listeners:
            match event:
                case GlyphShown(index, grapheme):
                    listener.glyph_shown(index, grapheme)
                case PauseStarted(seconds):
                    listener.pause_started(seconds)
                case Waiting(kind):
                    listener.waiting(kind)
                case Completed(by_press):
                    listener.completed(by_press)


# --- The typewriter ----------------------------------------------------------------------------

class Typewriter:
    """Types one line's timeline. Public, read-only: ``page`` (shown page), ``shown``
    (graphemes shown so far, over the whole line), ``state``."""

    def __init__(self, layout: Timeline, speed: Callable[[], float]) -> None:
        self.layout = layout
        self._speed = speed
        self.page = 0
        self.shown = 0
        self.state = TypeState.TYPING
        self._slots: Sequence[Slot] = layout.timeline(0)
        self._pos = 0
        self._acc = 0.0              # time available for the current slot, in seconds
        self._announced = -1         # position of the pause whose PauseStarted went out
        self._events: list[TypeEvent] = []

    # -- driving --

    def run(self) -> list[TypeEvent]:
        """Type as far as the time already available allows (the arrival frame: glyph 0,
        or everything up to the first stop at instant speed)."""
        if self.state in (TypeState.TYPING, TypeState.PAUSED):
            self._run()
        return self.take_events()

    def tick(self, dt: float) -> list[TypeEvent]:
        """Add ``dt`` seconds of typing time (nothing while waiting or complete)."""
        if self.state in (TypeState.TYPING, TypeState.PAUSED):
            self._acc += dt
            self._run()
        return self.take_events()

    def press(self) -> PressResult:
        """An advance (player, F15 auto). Its events come with the next ``run``/``tick``
        or ``take_events``."""
        state = self.state
        if state in (TypeState.TYPING, TypeState.PAUSED):
            slots, pos = self._slots, self._pos
            while True:
                slot = slots[pos]
                if type(slot) is GlyphSlot:
                    if self.shown <= slot.index:
                        self._show(slot.index + 1)
                elif type(slot) is not PauseSlot:
                    break
                pos += 1
            self._pos = pos
            self._stop(slot, by_press=True)
            return PressResult.COMPLETED
        if state is TypeState.WAIT_CLICK:
            self._pos += 1
            self._resume()
            return PressResult.CONTINUED
        if state is TypeState.WAIT_PAGE:
            self.page += 1
            self._slots = self.layout.timeline(self.page)
            self._pos = 0
            self._resume()
            return PressResult.NEXT_PAGE
        return PressResult.ADVANCE

    def complete_all(self) -> None:
        """Lay out every page and show the line complete on its last (restore, F15 skip).
        Emits one ``Completed(True)`` unless the line was already complete."""
        if self.state is TypeState.COMPLETE:
            return
        pages = self.layout.all_pages()
        self.page = pages - 1
        self._slots = self.layout.timeline(self.page)
        self._pos = len(self._slots) - 1
        self._show(self.layout.glyph_count)
        self._stop(self._slots[self._pos], by_press=True)

    def take_events(self) -> list[TypeEvent]:
        events, self._events = self._events, []
        return events

    # -- internals --

    def _run(self) -> None:
        slots = self._slots
        events = self._events
        while True:
            slot = slots[self._pos]
            kind = type(slot)
            if kind is GlyphSlot:
                if self.shown <= slot.index:
                    self._show(slot.index + 1)
                    events.append(GlyphShown(slot.index, slot.text))
                cost = self._cost(slot.speed)
                if self._acc + EPS < cost:
                    return
                self._acc -= cost
                self._pos += 1
            elif kind is PauseSlot:
                if self._announced != self._pos:
                    self._announced = self._pos
                    self.state = TypeState.PAUSED
                    events.append(PauseStarted(slot.seconds))
                if self._acc + EPS < slot.seconds:
                    return
                self._acc -= slot.seconds
                self._pos += 1
                self.state = TypeState.TYPING
            else:
                self._stop(slot, by_press=False)
                return

    def _cost(self, speed: float) -> float:
        cps = self._speed()
        if cps <= 0 or speed == INSTANT:
            return 0.0
        return 1.0 / (cps * speed)

    def _show(self, count: int) -> None:
        assert count <= self.layout.glyph_count, "shown past the line's grapheme count"
        self.shown = count

    def _stop(self, slot: Slot, *, by_press: bool) -> None:
        """Take the state of the stop ``slot`` (a wait, page break, or the end)."""
        self._acc = 0.0
        if type(slot) is WaitSlot:
            self.state = TypeState.WAIT_CLICK
            self._events.append(Waiting(WaitKind.CLICK))
        elif type(slot) is PageBreakSlot:
            self.state = TypeState.WAIT_PAGE
            self._events.append(Waiting(WaitKind.PAGE))
        else:
            assert type(slot) is EndSlot, slot
            self.state = TypeState.COMPLETE
            self._events.append(Completed(by_press))

    def _resume(self) -> None:
        self.state = TypeState.TYPING
        self._acc = 0.0
        self._announced = -1
        self._run()


__all__ = ["END", "EPS", "PAGE_BREAK", "WAIT", "Completed", "EndSlot", "GlyphShown",
           "GlyphSlot", "PageBreakSlot", "PauseSlot", "PauseStarted", "PressResult", "Slot",
           "Timeline", "TypeEvent", "TypeState", "Typewriter", "TypingListener", "WaitKind",
           "WaitSlot", "Waiting", "deliver"]
