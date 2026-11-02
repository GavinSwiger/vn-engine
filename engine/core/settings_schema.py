"""The player settings key table (F16 ``04-technical.md`` §4, §5.1, §12; design §7).

Why this module exists: ``persist`` (checking ``settings.json``) and ``ui`` (slider ranges)
both need the one table, and neither may import the other, so it lives in ``core``.

``KEYS`` holds the 18 stored keys in the design's order (W71 lines follow it); F33's
``warning_seen`` (the content warning ``version`` the player continued past, 0 = none) is
last, not on the Settings page. Each key is an ``IntKey`` (whole numbers in a fixed range; ``text_cps`` also allows 0), a ``BoolKey``, or
the one ``SizeKey`` (``window_size``, two whole numbers). Types are exact: ``true`` is not
a number and ``1`` is not a boolean. ``found_word`` names a refused value for W71 without
ever echoing text from the file: an integer of at most 7 characters, ``true``/``false``,
or a fixed kind word (07 G4).

**Adding a key bumps ``FORMAT``** (07 G6, I-7). A key is never removed or retyped; a retype
needs a new name. A snapshot test pins ``KEYS`` to ``FORMAT``.

Standard library only; imports nothing from ``engine``; no side effects.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

Value = int | bool | tuple[int, int]

FORMAT: Final = 2                       # 2: F33's warning_seen
MAX_FILE_BYTES: Final = 65_536          # 64 KiB read cap (PR-F16-22)
MAX_INT_DIGITS: Final = 20              # longer integers parse as "a long number"
MAX_FOUND_CHARS: Final = 7              # TR-F16-03: no file text longer than 7 characters
TEXT_SIZE_MAX: Final = 48               # F05's largest text size (TEXT_SIZE_RANGE)
# F30 (SEC-F30-07): the consent defaults are engine constants, never read from config.toml.
# Their keys (``username_use``, ``crash_label``) and FORMAT 3 come with F30 step 5.
USERNAME_USE_DEFAULT: Final = 0         # 0 never answered, 1 don't allow, 2 allow
CRASH_LABEL_DEFAULT: Final = False      # "Label fake error screens" off

LONG_NUMBER: Final = "a long number"


@dataclass(frozen=True, slots=True)
class IntKey:
    """A whole number from ``lo`` to ``hi``; ``zero``: 0 is also allowed (``text_cps``,
    where 0 shows text instantly)."""

    lo: int
    hi: int
    zero: bool = False

    @property
    def must(self) -> str:
        phrase = f"a whole number from {self.lo} to {self.hi}"
        return f"0 or {phrase}" if self.zero else phrase

    def accepts(self, value: object) -> bool:
        if type(value) is not int:
            return False
        return (self.zero and value == 0) or self.lo <= value <= self.hi


@dataclass(frozen=True, slots=True)
class BoolKey:
    """Exactly ``true`` or ``false``."""

    @property
    def must(self) -> str:
        return "true or false"

    def accepts(self, value: object) -> bool:
        return type(value) is bool


@dataclass(frozen=True, slots=True)
class SizeKey:
    """``[width, height]`` in requested units: exactly two whole numbers in range."""

    w: tuple[int, int] = (640, 7680)
    h: tuple[int, int] = (360, 4320)

    @property
    def must(self) -> str:
        return (f"a list of two whole numbers, {self.w[0]} to {self.w[1]} and "
                f"{self.h[0]} to {self.h[1]}")

    def accepts(self, value: object) -> bool:
        if type(value) not in (list, tuple) or len(value) != 2:     # type: ignore[arg-type]
            return False
        width, height = value                                       # type: ignore[misc]
        return (type(width) is int and type(height) is int
                and self.w[0] <= width <= self.w[1] and self.h[0] <= height <= self.h[1])


KeySpec = IntKey | BoolKey | SizeKey

KEYS: Final[Mapping[str, KeySpec]] = MappingProxyType({
    "text_cps": IntKey(10, 200, zero=True),
    "text_size_pct": IntKey(100, 150),
    "auto_scale_pct": IntKey(25, 400),
    "auto_wait_voice": BoolKey(),
    "skip_all": BoolKey(),
    "master_volume": IntKey(0, 100),
    "music_volume": IntKey(0, 100),
    "sound_volume": IntKey(0, 100),
    "voice_volume": IntKey(0, 100),
    "text_blips": BoolKey(),
    "voice_sustain": BoolKey(),
    "audio_unfocused": BoolKey(),
    "audio_minimized": BoolKey(),
    "mono": BoolKey(),
    "fullscreen": BoolKey(),
    "reduce_motion": BoolKey(),
    "window_size": SizeKey(),
    "warning_seen": IntKey(1, 1000, zero=True),       # F33 (format 2)
})


@dataclass(frozen=True, slots=True)
class Problem:
    """W71's three fills: ``<key> must be <must>, but found <found>``."""

    key: str
    must: str
    found: str


class LongNumber:
    """What the settings parser puts in place of an integer of more than
    ``MAX_INT_DIGITS`` digits, so a huge number is never converted. It fails every check
    and is found as "a long number"."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "LongNumber()"


def found_word(value: object) -> str:
    """W71's found text: an integer whose digits (with its sign) are at most 7 characters
    as those digits, a longer one as "a long number"; ``true``/``false``; "a decimal
    number", "text", "a list", "an object", "null". Never any text from the file."""
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        if abs(value) >= 10 ** MAX_INT_DIGITS:          # never stringify a huge number
            return LONG_NUMBER
        text = str(value)
        return text if len(text) <= MAX_FOUND_CHARS else LONG_NUMBER
    if isinstance(value, LongNumber):
        return LONG_NUMBER
    if isinstance(value, float):
        return "a decimal number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, (list, tuple)):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    return "a value"


def check(key: str, value: object) -> Problem | None:
    """None if ``value`` may be stored for ``key``, else W71's ``Problem``. Types are exact
    (an int key refuses ``true`` and ``40.0``; ``window_size`` takes a list or tuple of
    exactly two ints). ``ValueError`` for a key not in ``KEYS`` (a programmer error)."""
    spec = KEYS.get(key)
    if spec is None:
        raise ValueError("not a settings key")
    if spec.accepts(value):
        return None
    return Problem(key, spec.must, found_word(value))


def effective_text_size(base: int, pct: int) -> int:
    """``min(48, round_half_up(base * pct / 100))`` in exact integer arithmetic (TR-F16-09)."""
    return min(TEXT_SIZE_MAX, (2 * base * pct + 100) // 200)


__all__ = ["BoolKey", "FORMAT", "IntKey", "KEYS", "KeySpec", "LONG_NUMBER", "LongNumber",
           "MAX_FILE_BYTES", "MAX_FOUND_CHARS", "MAX_INT_DIGITS", "Problem", "SizeKey",
           "TEXT_SIZE_MAX", "Value", "check", "effective_text_size", "found_word"]
