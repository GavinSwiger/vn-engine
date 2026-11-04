"""Heartbeat's pure rules (F57 SPEC §4–§6, §8).

Why this module exists: everything about Heartbeat that can be decided without a window lives
here, so it can be tested directly and shared by the hooks (``check_args``, ``check_story``,
``outcome_for``) and the playable session (``heartbeat``): the argument checks, the plan
(lead-in, beat interval and window under the player's Timing assist), the beat state machine
``Beats``, the ring's size, and the layout.

- **Plan.** ``make_plan(args, timed)`` takes ``timed``, the plugin's
  ``ctx.settings.timed`` (F50's one rule: ``seconds``, twice that, or ``None``), so no
  factor is chosen here (F50 07 I-6). ``None`` (No time limits) keeps the Normal interval
  and makes every ring wait on the circle (F50 07 finding 5).
- **Beats.** Beat *k* (from 1) meets the circle at ``lead_in + k × interval``; its ring
  starts closing when the previous beat falls (the first when the lead-in ends). A press in
  ``[b − w, b + w]`` is a hit, one in ``[b − interval / 2, b − w)`` a miss ("too soon"); a
  window that ends with no press is a miss; each beat is judged once. A waiting beat is hit
  by the first press at or after its arrival, and the next ring starts closing at that
  press. ``set_plan`` applies a new plan from the next beat whose ring hasn't started.
- **Ring.** ``ring_size``: ``128 + (top − 128) × clamp((b − t) / interval, 0, 1)``; under
  reduce motion only three sizes (``top``, the middle, 128).

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``, the shared
``bundled.rule_text``, and the stdlib (AC-F25-01's rule).
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.api import Outcome, StoryNames, closest
from engine.minigames.bundled.rule_text import line_problem, value_echo

BEATS: Final = range(4, 21)
BPM: Final = range(40, 121)
COST: Final = range(0, 21)
WINDOWS: Final = {"tight": 0.15, "normal": 0.25, "wide": 0.40}
WINDOW_SHARE: Final = 0.4             # a window is never more than 40 % of the interval
LEAD_IN: Final = 1.0                  # seconds of "Ready…" before the first ring closes
SOUND_MAX: Final = 260
DEFAULTS: Final = {"beats": 8, "bpm": 60, "window": "normal", "meter": None, "cost": 1,
                   "sound": None}
DT_MAX: Final = 0.1                   # a frame stall never eats a window
RESULT_S: Final = 1.5                 # the result shows this long (a press ends it early)
BORDER_S: Final = 0.3                 # a hit or miss colors the target's border this long
WORD_S: Final = 0.4                   # "Steady" / "Missed" shows this long
EPSILON: Final = 1e-9                 # inclusive boundaries under float sums

# Layout (§6), canvas units.
RING_MAX, RING_MIN, TARGET = 384, 256, 128
RING_LINE, TARGET_BORDER, FEEDBACK_BORDER = 6, 4, 8
GAP, STRIP_H, DOT, DOT_GAP, STRIP_PAD = 24, 40, 16, 12, 12
TEXT_SIZE, TEXT_MIN, TEXT_MAX = 24, 20, 36
RING_STEP: Final = 8                  # drawn ring sizes are a multiple of this (cached)

Rect = tuple[float, float, float, float]


# --- The checks (§5) -------------------------------------------------------------------------

def _whole(v: object, allowed: range) -> bool:
    return type(v) is int and v in allowed


def problem(args: dict) -> str | None:
    """The first refused argument's reason (§5, in argument order), or None. No side effects;
    never raises for frozen values."""
    beats = args.get("beats", DEFAULTS["beats"])
    if not _whole(beats, BEATS):
        return f"beats must be a whole number from 4 to 20, but it is {value_echo(beats)}."
    bpm = args.get("bpm", DEFAULTS["bpm"])
    if not _whole(bpm, BPM):
        return f"bpm must be a whole number from 40 to 120, but it is {value_echo(bpm)}."
    window = args.get("window", DEFAULTS["window"])
    if type(window) is not str or window not in WINDOWS:
        return ('window must be "tight", "normal" or "wide", but it is '
                f"{value_echo(window)}.")
    meter = args.get("meter", DEFAULTS["meter"])
    if meter is not None and (type(meter) is not str or meter == ""):
        return f"meter must be None or a meter's name, but it is {value_echo(meter)}."
    cost = args.get("cost", DEFAULTS["cost"])
    if not _whole(cost, COST):
        return f"cost must be a whole number from 0 to 20, but it is {value_echo(cost)}."
    sound = args.get("sound", DEFAULTS["sound"])
    if sound is not None and line_problem(sound, 1, SOUND_MAX) is not None:
        return ('sound must be None or a sound file in quotes, such as "sfx/heartbeat.ogg", '
                f"but it is {value_echo(sound)}.")
    return None


def story_problem(args: dict, story: StoryNames) -> str | None:
    """``meter`` against the story's declared meters, or None. Meant for arguments that pass
    ``problem``; never raises for others."""
    meter = args.get("meter", DEFAULTS["meter"])
    if type(meter) is not str or meter in story.meters:
        return None
    text = f"meter names {value_echo(meter)}, which no points line declares."
    hint = closest(meter, story.meters)
    return text + (f' Did you mean "{hint}"?' if hint is not None else "")


def fixed_outcome(args: dict) -> Outcome:
    """Skip Game and the test outcome: a full score, no meter change (PR-F57-06)."""
    beats = args.get("beats", DEFAULTS["beats"])
    return Outcome(beats if _whole(beats, BEATS) else DEFAULTS["beats"])


# --- The plan and the beats (§4) -------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Plan:
    """The lead-in, a ring's approach (the beat interval), the hit window, and ``wait``: No
    time limits (rings wait on the circle)."""

    lead_in: float
    interval: float
    window: float
    wait: bool = False


def make_plan(args: dict, timed: Callable[[float], float | None]) -> Plan:
    """The plan for checked ``args`` under ``timed`` (``ctx.settings.timed``)."""
    bpm = args.get("bpm", DEFAULTS["bpm"])
    base = 60 / bpm
    width = WINDOWS[args.get("window", DEFAULTS["window"])]
    interval = timed(base)
    if interval is None:                  # No time limits: the Normal pace, then wait
        return Plan(LEAD_IN, base, min(width, WINDOW_SHARE * base), wait=True)
    lead = timed(LEAD_IN)
    window = timed(width)
    return Plan(LEAD_IN if lead is None else lead, interval,
                min(width if window is None else window, WINDOW_SHARE * interval))


@dataclass(frozen=True, slots=True)
class Beat:
    """One scheduled beat: its ring starts closing at ``start`` and meets the circle at
    ``time``; ``window`` and ``wait`` are its plan's."""

    start: float
    time: float
    interval: float
    window: float
    wait: bool

    @property
    def early(self) -> float:
        """Where its early zone begins (a press from here to ``time − window`` misses)."""
        return self.time - self.interval / 2


def _beat(start: float, plan: Plan) -> Beat:
    return Beat(start, start + plan.interval, plan.interval, plan.window, plan.wait)


Event = tuple[str, int]                   # ("beat" | "hit" | "miss", beat index from 0)


class Beats:
    """The beat state machine (module docstring). ``advance(t)`` and ``press(t)`` take the
    game time in seconds and return what happened, in order."""

    def __init__(self, count: int, plan: Plan) -> None:
        self.count = count
        self.plan = plan
        self.marks: list[bool] = []           # judged beats in order: True = hit
        self.scheduled: list[Beat] = [_beat(plan.lead_in, plan)]
        self.sounded = 0                      # beats whose arrival has passed

    @property
    def index(self) -> int:
        """The earliest unjudged beat."""
        return len(self.marks)

    @property
    def done(self) -> bool:
        return len(self.marks) >= self.count

    @property
    def current(self) -> Beat | None:
        return None if self.done else self.scheduled[self.index]

    @property
    def hits(self) -> int:
        return sum(self.marks)

    @property
    def misses(self) -> int:
        return len(self.marks) - self.hits

    def set_plan(self, plan: Plan, t: float) -> None:
        """A new plan (the player changed Timing assist), used from the next beat whose ring
        hasn't started closing at ``t``."""
        self.plan = plan
        beat = self.current
        if beat is not None and t < beat.start - EPSILON and self.sounded <= self.index:
            self.scheduled[self.index] = _beat(beat.start, plan)

    def advance(self, t: float) -> list[Event]:
        events: list[Event] = []
        while True:
            if (self.sounded < len(self.scheduled) and self.sounded < self.count
                    and t >= self.scheduled[self.sounded].time - EPSILON):
                events.append(("beat", self.sounded))
                self.sounded += 1
                continue
            beat = self.current
            if beat is not None and not beat.wait and t > beat.time + beat.window + EPSILON:
                events.append(("miss", self.index))
                self._judge(False, beat.time + beat.window)
                continue
            return events

    def press(self, t: float) -> Event | None:
        beat = self.current
        if beat is None:
            return None
        k = self.index
        if beat.wait:
            if t < beat.time - EPSILON:
                return None                   # early presses do nothing
            self._judge(True, t)
            return ("hit", k)
        if beat.time - beat.window - EPSILON <= t <= beat.time + beat.window + EPSILON:
            self._judge(True, t)
            return ("hit", k)
        if beat.early - EPSILON <= t < beat.time - beat.window - EPSILON:
            self._judge(False, t)
            return ("miss", k)
        return None

    def _judge(self, hit: bool, t: float) -> None:
        beat = self.scheduled[self.index]
        self.marks.append(hit)
        if self.done or len(self.scheduled) > self.index:
            return
        self.scheduled.append(_beat(max(t, beat.time) if beat.wait else beat.time,
                                    self.plan))


# --- The look (§6) ---------------------------------------------------------------------------

def ring_size(t: float, beat: Beat | None, *, reduce: bool, top: float = RING_MAX) -> float:
    """The ring's diameter at ``t`` for ``beat`` (the earliest unjudged one)."""
    if beat is None:
        return TARGET
    if reduce:
        arrive = beat.time if beat.wait else beat.time - beat.window
        middle = (beat.start + arrive) / 2
        if t < middle - EPSILON:
            return top
        return (top + TARGET) / 2 if t < arrive - EPSILON else TARGET
    share = min(1.0, max(0.0, (beat.time - t) / beat.interval))
    return TARGET + (top - TARGET) * share


def drawn_size(size: float) -> int:
    """A ring size as drawn: rounded to ``RING_STEP`` so each size is built once."""
    return max(TARGET, int(math.floor(size / RING_STEP + 0.5)) * RING_STEP)


def text_px(scale: float) -> int:
    """The circle's text: 24 × the player's text scale, 20 to 36."""
    return min(TEXT_MAX, max(TEXT_MIN, math.floor(TEXT_SIZE * scale + 0.5)))


@dataclass(frozen=True, slots=True)
class Layout:
    center: tuple[float, float]
    top: float                            # the ring's start size (384, or less to fit)
    strip: Rect                           # the dots' panel
    dots: tuple[tuple[float, float], ...]  # each dot's center


def layout(area: Sequence[float], beats: int) -> Layout:
    """One group (the ring's start size, 24, the 40-tall dots strip) centered in ``area``;
    the ring shrinks to fit an area under 448 tall, not below 256."""
    x, y, w, h = (float(v) for v in area)
    top = max(float(RING_MIN), min(float(RING_MAX), h - GAP - STRIP_H))
    group = top + GAP + STRIP_H
    gy = y + max(0.0, (h - group) / 2)
    cx = x + w / 2
    strip_w = 2 * STRIP_PAD + beats * DOT + (beats - 1) * DOT_GAP
    strip = (cx - strip_w / 2, gy + top + GAP, float(strip_w), float(STRIP_H))
    dy = strip[1] + STRIP_H / 2
    dots = tuple((strip[0] + STRIP_PAD + DOT / 2 + i * (DOT + DOT_GAP), dy)
                 for i in range(beats))
    return Layout((cx, gy + top / 2), top, strip, dots)


__all__ = ["BEATS", "BPM", "Beat", "Beats", "COST", "DEFAULTS", "LEAD_IN", "Layout", "Plan",
           "WINDOWS", "drawn_size", "fixed_outcome", "layout", "make_plan", "problem",
           "ring_size", "story_problem", "text_px"]
