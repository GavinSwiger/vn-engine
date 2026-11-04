"""Lock's pure rules (F53 ``01`` §3.1, §3.4, §4.1; ``04`` §3.1, §3.2, §3.5).

Why this module exists: everything about the Lock (``code_lock``) that can be decided without a
window lives here, so the hooks (``check_args``, ``outcome_for``) and the playable session
(``code_lock``) share one copy and the tests can call it directly:

- **Checks.** ``problem(args)``: L1–L8 in table order, the first problem only, never raises,
  never changes ``args``. Codes are checked against explicit ASCII sets (never ``isdigit`` or
  ``isalpha``, which accept "²" and "é"). ``keypad_problem``/``dial_problem`` are L3/L4,
  which Studio mirrors (ADR-0008).
- **Play.** ``alphabet(kind, code)``, ``matches`` (ignoring case), ``wrong_message`` (the
  tries left in words), ``locked_out``, ``hint_shown``, ``w280_text``.
- **Look.** ``keypad_layout`` (stacked with gaps of 12, then 4, then side by side) and
  ``dial_layout``: every rectangle inside the content area; ``shake_offset`` and
  ``slide_offset`` for the motion (0 under Reduce motion, decided by the caller).

Pure: no clock, no randomness, no I/O. Imports only ``engine.minigames.api``,
``bundled.rule_text`` and the stdlib (AC-F53-01).
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from engine.minigames.api import closest
from engine.minigames.bundled.rule_text import (choice_problem, fill, flag_problem,
                                                kind_words, text_problem, value_echo,
                                                whole_problem)

KINDS: Final = ("keypad", "dial")
DIGITS: Final = "0123456789"
LETTERS: Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LOWER: Final = LETTERS.lower()
KEYPAD_LEN: Final = range(1, 13)
DIAL_LEN: Final = range(3, 7)
TRIES_MAX: Final = 99
HINT_MAX: Final = 120
# The arguments in declared order (the Studio form's order); code is required.
DEFAULTS: Final = {"kind": "keypad", "code": None, "tries": 0, "hint": None, "hint_after": 3,
                   "leave": True}
REQUIRED: Final = ("code",)

OPEN_HOLD: Final = 0.7                # "Open!" shows this long before the finish
SHAKE_S, SHAKE_UNITS = 0.3, 8         # a wrong code shakes the display ±8 for 0.3 s
SLIDE_S: Final = 0.12                 # a dial turn slides the face for 120 ms
EPSILON: Final = 1e-9

# Sizes (01 §4.1), canvas units at 100 % text.
PAD: Final = 16
PANEL_W: Final = 400
DISPLAY: Final = (368, 72)
KEY: Final = (112, 60)
GAPS: Final = (12, 4)
WHEEL_W, WHEEL_ZONE, FACE_MIN, WHEEL_GAP = 96, 56, 104, 16
COLUMN_GAP, COLUMN_W = 64, 220
DISPLAY_TEXT: Final = (48, 32, 64)    # display.text_size: default, lo, hi
FACE_TEXT: Final = 64
MESSAGE_TEXT: Final = 24

Rect = tuple[float, float, float, float]


# --- The checks (L1–L8) ---------------------------------------------------------------------

def _all_in(text: str, allowed: str) -> bool:
    return all(ch in allowed for ch in text)


def keypad_problem(code: str) -> str | None:
    """L3: a keypad code is 1–12 ASCII digits."""
    if len(code) in KEYPAD_LEN and _all_in(code, DIGITS):
        return None
    return f"a keypad code is 1 to 12 digits from 0 to 9, but code is {value_echo(code)}."


def dial_problem(code: str) -> str | None:
    """L4: a dial code is 3–6 ASCII digits, or 3–6 ASCII letters (either case)."""
    if len(code) in DIAL_LEN and (_all_in(code, DIGITS) or _all_in(code, LETTERS + _LOWER)):
        return None
    return ("a dial code is 3 to 6 digits, or 3 to 6 letters from A to Z, but code is "
            f"{value_echo(code)}.")


def problem(args: dict) -> str | None:
    """The first refused argument's reason (L1–L8), or None."""
    kind = args.get("kind", DEFAULTS["kind"])
    found = choice_problem("kind", kind, KINDS, closest=closest(kind, KINDS))
    if found is not None:
        return found
    code = args.get("code")
    if type(code) is not str:
        return ('code must be text in quotes, such as code="0417", but it is '
                f"{kind_words(code)}.")
    found = keypad_problem(code) if kind == "keypad" else dial_problem(code)
    if found is not None:
        return found
    return (whole_problem("tries", args.get("tries", DEFAULTS["tries"]), 0, TRIES_MAX,
                          lo_words="0 (no limit)")
            or text_problem("hint", args.get("hint", DEFAULTS["hint"]), HINT_MAX)
            or whole_problem("hint_after", args.get("hint_after", DEFAULTS["hint_after"]),
                             0, TRIES_MAX)
            or flag_problem("leave", args.get("leave", DEFAULTS["leave"])))


@dataclass(frozen=True, slots=True)
class LockSpec:
    kind: str
    code: str
    tries: int
    hint: str | None
    hint_after: int
    leave: bool

    @property
    def size(self) -> int:
        return len(self.code)


def parse(args: dict) -> LockSpec:
    """Checked arguments as a ``LockSpec`` (defaults filled in)."""
    a = {**DEFAULTS, **args}
    return LockSpec(a["kind"], a["code"], a["tries"], a["hint"], a["hint_after"], a["leave"])


def w280_text(spec: LockSpec) -> str | None:
    """W280 (dev): a lock that can't be left, with no try limit and no hint."""
    if spec.leave or spec.tries or spec.hint is not None:
        return None
    return ("code_lock can't be left: leave=False, tries=0 and no hint, so a player who missed "
            "the code can only skip or load. Add a hint, a try limit, or leave=True.")


# --- Play ------------------------------------------------------------------------------------

def alphabet(kind: str, code: str) -> str:
    """The symbols the player can enter: digits, or A–Z for a dial with a letter code."""
    if kind == "dial" and code and _all_in(code, LETTERS + _LOWER):
        return LETTERS
    return DIGITS


def matches(entered: str, code: str) -> bool:
    """Whether ``entered`` opens a lock with ``code`` (ignoring case)."""
    return entered.upper() == code.upper()


def locked_out(wrong: int, tries: int) -> bool:
    return tries > 0 and wrong >= tries


def wrong_message(wrong: int, tries: int, words: Callable[[str], str]) -> str:
    """After a wrong code: ``wrong``, then the tries left (none with ``tries=0``); out of
    tries: ``locked_out``. ``words`` reads ``[words.plugin.code_lock]``."""
    if locked_out(wrong, tries):
        return words("locked_out")
    text = words("wrong")
    if tries <= 0:
        return text
    left = tries - wrong
    more = words("try_left") if left == 1 else fill(words("tries_left"), n=left)
    return f"{text} {more}"


def hint_shown(wrong: int, hint_after: int, hint: str | None) -> bool:
    """The hint bar shows the hint after ``hint_after`` wrong tries (0: from the start)."""
    return hint is not None and wrong >= hint_after


def turn(symbols: str, current: str, by: int) -> str:
    """A wheel turned ``by`` steps (up is +1), wrapping 9↔0 and Z↔A."""
    return symbols[(symbols.index(current) + by) % len(symbols)]


def shake_offset(t: float) -> float:
    """The wrong-code shake at ``t`` seconds: 8·sin(6πt/0.3)·(1 − t/0.3), 0 after."""
    if t < 0 or t >= SHAKE_S:
        return 0.0
    return SHAKE_UNITS * math.sin(6 * math.pi * t / SHAKE_S) * (1 - t / SHAKE_S)


def ease_in_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def slide_offset(t: float, by: int, face_h: float) -> float:
    """A turn's slide: the old face leaves over 120 ms (``by`` +1 slides up). 0 after."""
    if t >= SLIDE_S or by == 0:
        return 0.0
    return (1 - ease_in_out(t / SLIDE_S)) * face_h * (1 if by > 0 else -1)


def clamp_size(value: object, default: int, lo: int, hi: int) -> int:
    """A size token: a whole number clamped to ``lo..hi`` (else ``default``)."""
    if type(value) is not int:
        return default
    return min(hi, max(lo, value))


# --- Layout (04 §3.5) --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class KeypadLayout:
    panel: Rect
    display: Rect
    message: Rect
    keys: tuple[Rect, ...]        # 1–9, Clear, 0, Enter
    leave: Rect | None
    continue_: Rect               # out of tries: where Continue shows (the keys' place)
    gap: int
    side: bool


def _inside(area: Rect, w: float, h: float) -> tuple[float, float]:
    """The top-left of a ``w`` × ``h`` group centered in ``area`` (kept inside it)."""
    ax, ay, aw, ah = area
    return ax + max(0.0, (aw - w) / 2), ay + max(0.0, (ah - h) / 2)


def keypad_layout(area: Sequence[float], *, button_h: int, message_h: int,
                  leave: bool) -> KeypadLayout:
    """The keypad panel: stacked with gaps of 12, then of 4, else side by side (display,
    message and Step back left, the keys right). Keys are 112 wide and at least 60 tall."""
    a = tuple(float(v) for v in area)
    key_w, key_h = KEY[0], max(KEY[1], button_h)
    dw, dh = DISPLAY
    leave_h = button_h if leave else 0
    tries = [(side, gap) for side in (False, True) for gap in GAPS]
    for side, gap in tries:
        keys_w, keys_h = 3 * key_w + 2 * gap, 4 * key_h + 3 * gap
        left_h = dh + gap + message_h + ((gap + leave_h) if leave else 0)
        if side:
            w, h = 2 * PAD + dw + gap + keys_w, 2 * PAD + max(left_h, keys_h)
        else:
            w, h = PANEL_W, 2 * PAD + left_h + gap + keys_h
        if w <= a[2] and h <= a[3]:
            break
    x, y = _inside(a, w, h)
    lx, top = x + PAD, y + PAD
    display = (lx, top, float(dw), float(dh))
    message = (lx, top + dh + gap, float(dw), float(message_h))
    if side:
        kx, ky = lx + dw + gap, top + max(0.0, (max(left_h, keys_h) - keys_h) / 2)
        leave_box = (lx, message[1] + message_h + gap, float(dw), float(leave_h))
    else:
        kx, ky = x + (w - keys_w) / 2, message[1] + message_h + gap
        leave_box = (lx, ky + keys_h + gap, float(dw), float(leave_h))
    keys = tuple((kx + c * (key_w + gap), ky + r * (key_h + gap), float(key_w), float(key_h))
                 for r in range(4) for c in range(3))
    cont = (kx, ky + (keys_h - button_h) / 2, float(keys_w), float(button_h))
    return KeypadLayout((x, y, w, h), display, message, keys,
                        leave_box if leave else None, cont, gap, side)


@dataclass(frozen=True, slots=True)
class DialLayout:
    panel: Rect
    wheels: tuple[Rect, ...]
    face_h: float
    message: Rect
    open: Rect
    leave: Rect | None
    continue_: Rect


def dial_layout(area: Sequence[float], *, count: int, button_h: int, message_h: int,
                face_pitch: int, leave: bool) -> DialLayout:
    """``count`` wheels (96 wide: ▲ 56, the face, ▼ 56; 16 apart), then 64 to their right a
    column of Open and Step back (220 wide); the message under the wheels. The face is
    ``max(104, pitch)`` tall. Gaps fall back from 12 to 4 when the group doesn't fit."""
    a = tuple(float(v) for v in area)
    face_h = float(max(FACE_MIN, face_pitch))
    wheel_h = 2 * WHEEL_ZONE + face_h
    wheels_w = count * WHEEL_W + (count - 1) * WHEEL_GAP
    for gap in GAPS:
        col_h = button_h + ((gap + button_h) if leave else 0)
        left_h = wheel_h + gap + message_h
        w = 2 * PAD + wheels_w + COLUMN_GAP + COLUMN_W
        h = 2 * PAD + max(left_h, col_h)
        if h <= a[3]:
            break
    x, y = _inside(a, w, h)
    lx, top = x + PAD, y + PAD
    wheels = tuple((lx + i * (WHEEL_W + WHEEL_GAP), top, float(WHEEL_W), wheel_h)
                   for i in range(count))
    message = (lx, top + wheel_h + gap, float(wheels_w), float(message_h))
    cx = lx + wheels_w + COLUMN_GAP
    cy = top + max(0.0, (wheel_h - col_h) / 2)
    open_box = (cx, cy, float(COLUMN_W), float(button_h))
    leave_box = (cx, cy + button_h + gap, float(COLUMN_W), float(button_h)) if leave else None
    return DialLayout((x, y, w, h), wheels, face_h, message, open_box, leave_box, open_box)


__all__ = ["DEFAULTS", "DIGITS", "DialLayout", "KINDS", "KeypadLayout", "LETTERS", "LockSpec",
           "alphabet", "clamp_size", "dial_layout", "dial_problem", "hint_shown",
           "keypad_layout", "keypad_problem", "locked_out", "matches", "parse", "problem",
           "shake_offset", "slide_offset", "turn", "w280_text", "wrong_message"]
