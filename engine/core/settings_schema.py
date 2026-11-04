"""The player settings key table (F16 ``04-technical.md`` §4, §5.1, §12; design §7).

Why this module exists: ``persist`` (checking ``settings.json``) and ``ui`` (slider ranges)
both need the one table, and neither may import the other, so it lives in ``core``.

``KEYS`` holds the stored keys in the design's order (W71 lines follow it); F33's
``warning_seen`` (the content warning ``version`` the player continued past, 0 = none) is
not on the Settings page; F30's two keys, F43's ``language`` and F50's ``timing_assist``
follow it. Each key is an
``IntKey`` (whole numbers in a fixed range; ``text_cps`` also allows 0), a ``BoolKey``, the
one ``SizeKey`` (``window_size``, two whole numbers), or the one ``LanguageKey``
(``language``, a language code: F43, format 4, the first text value). Types are exact:
``true`` is not a number and ``1`` is not a boolean. ``found_word`` names a refused value
for W71 without ever echoing text from the file: an integer of at most 7 characters,
``true``/``false``, or a fixed kind word (07 G4); a refused language is "text".

**Adding a key bumps ``FORMAT``** (07 G6, I-7). A key is never removed or retyped; a retype
needs a new name. A snapshot test pins ``KEYS`` to ``FORMAT``.

Standard library only; imports nothing from ``engine``; no side effects.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

Value = int | bool | tuple[int, int] | str

FORMAT: Final = 5                       # 2: F33's warning_seen; 3: F30's two; 4: F43's language
#                                         5: F50's timing_assist
MAX_FILE_BYTES: Final = 65_536          # 64 KiB read cap (PR-F16-22)
MAX_INT_DIGITS: Final = 20              # longer integers parse as "a long number"
MAX_FOUND_CHARS: Final = 7              # TR-F16-03: no file text longer than 7 characters
TEXT_SIZE_MAX: Final = 48               # F05's largest text size (TEXT_SIZE_RANGE)
# F30 (SEC-F30-07): the consent defaults are engine constants, never read from config.toml.
USERNAME_USE_DEFAULT: Final = 0         # 0 never answered, 1 don't allow, 2 allow
CRASH_LABEL_DEFAULT: Final = False      # "Label fake error screens" off
# F43 (07 I-10): a language code is ASCII, 2-3 lower-case letters, optionally "-" and 2-8
# letters or digits (ja, pt-BR, zh-Hans), so at most 12 characters. core/langtags.py holds
# the same pattern (a test keeps them equal); this module imports nothing from engine.
LANGUAGE_CODE_RE: Final = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", re.ASCII)
LANGUAGE_CODE_MAX: Final = 12
LANGUAGE_NOT_CHOSEN: Final = ""         # the default: no language stored (first launch rule)
# F50 (PR-F50-01, 04): Timing assist, stored as 0/1/2; the ids are what config.toml and
# minigame plugins see (07 I-3: the file encoding stays private).
TIMING_NORMAL: Final = 0
TIMING_SLOWER: Final = 1
TIMING_OFF: Final = 2
TIMING_LEVELS: Final = ("normal", "slower", "off")    # index = the stored value

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


@dataclass(frozen=True, slots=True)
class LanguageKey:
    """A language code (F43 PR-F43-01): ASCII text matching ``LANGUAGE_CODE_RE``, at most
    ``LANGUAGE_CODE_MAX`` characters. Whether the game has that language is the app's
    question (W255), not the file's."""

    @property
    def must(self) -> str:
        return "a language code such as ja, pt-BR or zh-Hans"

    def accepts(self, value: object) -> bool:
        return (type(value) is str and len(value) <= LANGUAGE_CODE_MAX
                and LANGUAGE_CODE_RE.fullmatch(value) is not None)


def is_language_code(value: object) -> bool:
    """True for a value ``language`` may hold."""
    return LanguageKey().accepts(value)


KeySpec = IntKey | BoolKey | SizeKey | LanguageKey

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
    "username_use": IntKey(0, 2),                     # F30 (format 3): 2 = allowed
    "crash_label": BoolKey(),                         # F30 (format 3)
    "language": LanguageKey(),                        # F43 (format 4): absent = not chosen
    "timing_assist": IntKey(0, 2),                    # F50 (format 5): TIMING_LEVELS
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
    exactly two ints; ``language`` only a ``str`` code). ``ValueError`` for a key not in
    ``KEYS`` (a programmer error)."""
    spec = KEYS.get(key)
    if spec is None:
        raise ValueError("not a settings key")
    if spec.accepts(value):
        return None
    return Problem(key, spec.must, found_word(value))


def effective_text_size(base: int, pct: int) -> int:
    """``min(48, round_half_up(base * pct / 100))`` in exact integer arithmetic (TR-F16-09)."""
    return min(TEXT_SIZE_MAX, (2 * base * pct + 100) // 200)


def timing_limit(seconds: float, level: int | str) -> float | None:
    """F50's one rule (PR-F50-04, 07 I-6) for every timed part of a game: Normal gives
    ``seconds``, Slower ``seconds × 2``, No time limits ``None`` (wait for the player).
    ``level`` is the stored int (``TIMING_*``) or its id (``TIMING_LEVELS``); anything else
    counts as Normal. Nothing else in the engine multiplies a time limit by 2."""
    if type(level) is str:
        level = TIMING_LEVELS.index(level) if level in TIMING_LEVELS else TIMING_NORMAL
    if type(level) is not int:
        level = TIMING_NORMAL
    if level == TIMING_OFF:
        return None
    return float(seconds) * 2 if level == TIMING_SLOWER else float(seconds)


__all__ = ["BoolKey", "CRASH_LABEL_DEFAULT", "FORMAT", "IntKey", "KEYS", "KeySpec",
           "LANGUAGE_CODE_MAX", "LANGUAGE_CODE_RE", "LANGUAGE_NOT_CHOSEN", "LONG_NUMBER",
           "LanguageKey", "LongNumber", "MAX_FILE_BYTES", "MAX_FOUND_CHARS", "MAX_INT_DIGITS",
           "Problem", "SizeKey", "TEXT_SIZE_MAX", "TIMING_LEVELS", "TIMING_NORMAL", "TIMING_OFF",
           "TIMING_SLOWER", "USERNAME_USE_DEFAULT", "Value", "check", "effective_text_size",
           "found_word", "is_language_code", "timing_limit"]
