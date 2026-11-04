"""Stay still's pure rules (F53 ``01`` §3.2, §3.4, §4.2; ``04`` §3.3, §3.5).

Why this module exists: what counts as a flinch, and when, is the whole game, so it lives here
where tests can drive it without a window:

- **Checks.** ``problem(args)``: S1–S7 in table order, the first problem only.
- **Touch.** The game maps each event to a ``Touch`` (``key_down``, ``key_up``, ``button``,
  ``wheel``, ``pad``, ``stick``, ``motion``, ``focus_lost``, ``focus_gained``, ``other``).
- **Watch.** ``Watch.touch(t)`` returns COUNT, JOIN, SWALLOW or PASS (04 §3.3's table): a
  key press counts once while held; a modifier key alone never counts (C1); right click and
  gamepad east pass on (the game menu); the wheel echo on buttons 4/5 is swallowed (the wheel
  event counts); pointer travel counts only with ``mouse`` (24 units); presses within 0.25 s
  of a flinch join it; presses while the window is away or just refocused (0.25 s) are
  swallowed. ``Watch.advance(dt)`` is the only clock: READY (nothing counts) → GRACE (0.5 s
  after "I'm ready", or 1.0 s from the start with ``ready=False``) → WATCHING → DONE at 0 s
  with the count; with ``strict``, the first flinch is DONE with 1.
- **Look.** ``countdown`` (whole seconds, rounded up), ``bar_fraction`` (a step a second under
  Reduce motion), and ``still_layout`` (every rectangle inside the content area).

Pure: no clock, no randomness, no I/O. Imports only ``bundled.rule_text`` and the stdlib.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.bundled.rule_text import flag_problem, text_problem, whole_problem

SECONDS: Final = (3, 120)
LINE_MAX: Final = 160
SPEAKER_MAX: Final = 24
DEFAULTS: Final = {"seconds": 10, "line": None, "speaker": None, "flinch_line": None,
                   "strict": False, "mouse": False, "ready": True}

GRACE_READY: Final = 0.5              # after "I'm ready"
GRACE_START: Final = 1.0              # from the start, with ready=False
JOIN_S: Final = 0.25                  # presses this close to a flinch join it
REFOCUS_S: Final = 0.25               # presses this soon after refocusing are swallowed
FLINCH_S: Final = 2.0                 # the flinch line shows this long
TRAVEL: Final = 24.0                  # canvas units of pointer travel (mouse=True)
EPSILON: Final = 1e-9

COUNT, JOIN, SWALLOW, PASS = "count", "join", "swallow", "pass"
READY, GRACE, WATCHING, DONE = "ready", "grace", "watching", "done"

# Sizes (01 §4.2), canvas units at 100 % text.
SPEECH_W: Final = 880
PAD: Final = 16
COUNT_PANEL: Final = (240, 160)
COUNT_TEXT: Final = (96, 64)          # the countdown's size, then its fallback
BAR: Final = (480, 12)
READY_W: Final = 280
GAPS: Final = (24, 12, 4)
LINE_TEXT: Final = (32, 24, 40)       # line.text_size: default, lo, hi
LINE_MIN: Final = 24
LINES_MAX: Final = 3

Rect = tuple[float, float, float, float]


def problem(args: dict) -> str | None:
    """The first refused argument's reason (S1–S7), or None."""
    get = args.get
    return (whole_problem("seconds", get("seconds", DEFAULTS["seconds"]), *SECONDS)
            or text_problem("line", get("line"), LINE_MAX)
            or text_problem("speaker", get("speaker"), SPEAKER_MAX)
            or text_problem("flinch_line", get("flinch_line"), LINE_MAX)
            or flag_problem("strict", get("strict", False))
            or flag_problem("mouse", get("mouse", False))
            or flag_problem("ready", get("ready", True)))


@dataclass(frozen=True, slots=True)
class StillSpec:
    seconds: int
    line: str | None
    speaker: str | None
    flinch_line: str | None
    strict: bool
    mouse: bool
    ready: bool


def parse(args: dict) -> StillSpec:
    a = {**DEFAULTS, **args}
    return StillSpec(a["seconds"], a["line"], a["speaker"], a["flinch_line"], a["strict"],
                     a["mouse"], a["ready"])


@dataclass(frozen=True, slots=True)
class Touch:
    """One input as Stay still sees it. ``code``: the key, mouse button or pad button;
    ``modifier``: a modifier key alone; ``east``: gamepad B; ``pos``: a motion's canvas
    point (None outside the canvas)."""

    kind: str
    code: int = 0
    modifier: bool = False
    east: bool = False
    pos: tuple[float, float] | None = None


class Watch:
    """The flinch counter and its clock (module docstring)."""

    def __init__(self, spec: StillSpec) -> None:
        self.spec = spec
        self.state = READY if spec.ready else GRACE
        self.grace_left = 0.0 if spec.ready else GRACE_START
        self.now = 0.0
        self.remaining = float(spec.seconds)
        self.count = 0
        self.result: int | None = None
        self.last_flinch = -math.inf
        self.flinch_left = 0.0
        self.held: set[int] = set()
        self.away = False
        self.refocus_left = 0.0
        self.travel = 0.0
        self.point: tuple[float, float] | None = None

    def begin(self) -> None:
        """"I'm ready": the grace before watching."""
        if self.state == READY:
            self.state = GRACE
            self.grace_left = GRACE_READY

    @property
    def done(self) -> bool:
        return self.state == DONE

    def advance(self, dt: float) -> None:
        dt = max(0.0, float(dt))
        self.now += dt
        self.flinch_left = max(0.0, self.flinch_left - dt)
        self.refocus_left = max(0.0, self.refocus_left - dt)
        if self.state == GRACE:
            self.grace_left -= dt
            if self.grace_left > EPSILON:
                return
            dt = -self.grace_left              # the rest of the frame counts down
            self.grace_left = 0.0
            self.state = WATCHING
        if self.state == WATCHING:
            self.remaining -= dt
            if self.remaining <= EPSILON:
                self.remaining = 0.0
                self._end(self.count)

    def _end(self, result: int) -> None:
        self.state = DONE
        self.result = result

    def touch(self, t: Touch) -> str:
        kind = t.kind
        if kind == "key_up":
            self.held.discard(t.code)
            return PASS
        if kind in ("focus_lost", "focus_gained"):
            self.held.clear()
            self.away = kind == "focus_lost"
            self.refocus_left = 0.0 if self.away else REFOCUS_S
            self.point = None
            return PASS
        if kind == "key_down":
            repeat = t.code in self.held
            self.held.add(t.code)
            if self.state != WATCHING:
                return PASS
            if t.modifier or repeat:
                return SWALLOW
            return self._press()
        if self.state != WATCHING:
            return PASS
        if kind == "button":
            if t.code == 3:
                return PASS                    # right click: the game menu
            if t.code in (4, 5):
                return SWALLOW                 # pygame 2's wheel echo; the wheel counts
            return self._press()
        if kind == "pad":
            return PASS if t.east else self._press()
        if kind in ("wheel", "stick"):
            return self._press()
        if kind == "motion":
            return self._motion(t.pos)
        return PASS

    def _motion(self, pos: tuple[float, float] | None) -> str:
        if not self.spec.mouse:
            return PASS
        if pos is None:
            self.point = None                  # left the canvas: start again on return
            return PASS
        if self.point is not None:
            self.travel += math.dist(self.point, pos)
        self.point = pos
        if self.travel + EPSILON >= TRAVEL:
            verdict = self._press()
            self.travel = 0.0
            return verdict
        return PASS

    def _press(self) -> str:
        if self.away or self.refocus_left > EPSILON:
            return SWALLOW
        if self.now - self.last_flinch < JOIN_S - EPSILON:
            return JOIN
        self.count += 1
        self.last_flinch = self.now
        self.travel = 0.0
        self.flinch_left = FLINCH_S
        if self.spec.strict:
            self._end(1)
        return COUNT


def countdown(remaining: float) -> int:
    """Whole seconds left, rounded up."""
    return max(0, math.ceil(remaining - EPSILON))


def bar_fraction(remaining: float, seconds: int, *, reduce: bool) -> float:
    """The bar's filled share: draining every frame, or once a second under Reduce motion."""
    left = countdown(remaining) if reduce else remaining
    return min(1.0, max(0.0, left / seconds))


def clamp_size(value: object, default: int, lo: int, hi: int) -> int:
    if type(value) is not int:
        return default
    return min(hi, max(lo, value))


@dataclass(frozen=True, slots=True)
class StillLayout:
    speech: Rect
    count: Rect
    bar: Rect
    ready: Rect
    gap: int


def still_layout(area: Sequence[float], *, speech_h: float, count_h: float, button_h: int,
                 ready: bool) -> StillLayout:
    """The speech panel (880 wide), the countdown panel, the bar and "I'm ready", stacked
    and centered; the gap falls from 24 to 12 to 4 until they fit."""
    x, y, w, h = (float(v) for v in area)
    for gap in GAPS:
        total = speech_h + gap + count_h + gap + BAR[1] + ((gap + button_h) if ready else 0)
        if total <= h:
            break
    top = y + max(0.0, (h - total) / 2)
    cx = x + w / 2
    sw = min(float(SPEECH_W), w)
    speech = (cx - sw / 2, top, sw, float(speech_h))
    count = (cx - COUNT_PANEL[0] / 2, top + speech_h + gap, float(COUNT_PANEL[0]),
             float(count_h))
    bar = (cx - BAR[0] / 2, count[1] + count_h + gap, float(BAR[0]), float(BAR[1]))
    ready_box = (cx - READY_W / 2, bar[1] + BAR[1] + (gap if ready else 0), float(READY_W),
                 float(button_h if ready else 0))
    return StillLayout(speech, count, bar, ready_box, gap)


__all__ = ["COUNT", "DEFAULTS", "DONE", "GRACE", "JOIN", "PASS", "READY", "SWALLOW",
           "StillLayout", "StillSpec", "Touch", "WATCHING", "Watch", "bar_fraction",
           "clamp_size", "countdown", "parse", "problem", "still_layout"]
