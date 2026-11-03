"""The ``config.toml`` schema: one frozen dataclass per section, one validator per key.

Why this module exists: config keys are an author-facing contract (PR-F01-09), and every
invalid value must produce the same message shape, ``[section] key must be <phrase>, but
found <value>`` (PR-F01-11, §7.2.4). Keeping each key's default, type, and validator in one
declaration makes the defaults, the accepted values, and the exact phrases impossible to
drift apart. Later features add their sections **here** (no plugin registry).
"""

import dataclasses
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from engine.core.constants import (
    ART_HEIGHT_RANGE,
    AUDIO_FADE_RANGE,
    AUDIO_LOOP_START_RANGE,
    AUDIO_LOOP_STARTS_MAX,
    AUDIO_VOLUME_RANGE,
    BUILTIN_POSITIONS,
    CANVAS_SIZE,
    DEFAULT_TEXT_SIZE,
    DEFAULT_TEXTBOX_CPS,
    DEFAULT_WINDOW_SIZE,
    FLASH_SECONDS_RANGE,
    FONT_SUFFIXES,
    GLITCH_SECONDS_RANGE,
    GLITCH_SIZES,
    IMAGE_SUFFIXES,
    MENU_ENTRIES_MAX,
    MENU_ENTRY_NAME_MAX_CHARS,
    MESSAGE_WORD_MAX_CHARS,
    SHAKE_SECONDS_RANGE,
    SHAKE_SIZES,
    STAGE_COORD_RANGE,
    STAGE_POSITIONS_MAX,
    STAGE_WORDS,
    STATEMENT_WORDS,
    TEXT_SIZE_RANGE,
    TEXTBOX_CPS_RANGE,
    TEXTBOX_WIDTH_RANGE,
    TRANSITION_SECONDS_RANGE,
    USERNAME_MAX,
    VALUE_ECHO_MAX_CHARS,
    WORD_MAX_CHARS,
)
from engine.core.errors import AssetRefError, ConfigError
from engine.core.paths import check_ref, is_valid_app_id
from engine.core.redact import echo

RGB = tuple[int, int, int]
Point = tuple[float, float]


class ValueProblem(Exception):
    """Raised by ``Validator.check`` when a value is not accepted."""


class Validator:
    """Checks one key's value. ``expected`` is the phrase after "must be" (§7.2.4)."""

    expected: str = ""

    def check(self, value: object) -> object:
        """Return the value to store (possibly converted), or raise ValueProblem."""
        raise NotImplementedError

    def found(self, value: object) -> str | None:
        """What is wrong with a refused ``value``, when the validator says it better than
        "found <value>" (the text after "but "); None: the usual "found <value>"."""
        return None


class IntRange(Validator):
    """``note`` is added in parentheses, e.g. ``(0 shows text instantly)`` (F05 02 §5.3)."""

    def __init__(self, lo: int, hi: int, *, note: str = "") -> None:
        self.lo, self.hi = lo, hi
        self.expected = f"a whole number from {lo} to {hi}" + (f" ({note})" if note else "")

    def check(self, value: object) -> object:
        if type(value) is int and self.lo <= value <= self.hi:   # rejects bool and float
            return value
        raise ValueProblem


class Bool(Validator):
    expected = "true or false"

    def check(self, value: object) -> object:
        if type(value) is bool:
            return value
        raise ValueProblem


class Choice(Validator):
    def __init__(self, *options: str) -> None:
        self.options = options
        self.expected = "one of " + ", ".join(f'"{option}"' for option in options)

    def check(self, value: object) -> object:
        if type(value) is str and value in self.options:          # case-sensitive
            return value
        raise ValueProblem


class HexColor(Validator):
    """``#RRGGBB`` -> ``(r, g, b)``. F05's keys pass their shorter phrase (F05 02 §5.3)."""

    expected = 'a color written as "#RRGGBB", for example "#000000"'
    _PATTERN = re.compile(r"#[0-9A-Fa-f]{6}", re.ASCII)

    def __init__(self, expected: str | None = None) -> None:
        if expected is not None:
            self.expected = expected

    def check(self, value: object) -> object:
        if type(value) is str and self._PATTERN.fullmatch(value):
            return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))
        raise ValueProblem


class Text(Validator):
    """Text, optionally with a visible character (``non_empty``) and at most ``max_chars``
    characters, counted as code points (F10 ``[words]``, C11). An empty word passes here:
    F10 warns about it at install time (W65) and keeps the default."""

    def __init__(self, *, non_empty: bool = False, max_chars: int | None = None) -> None:
        self.non_empty = non_empty
        self.max_chars = max_chars
        if non_empty:
            self.expected = "text with at least one visible character" + (
                f" and at most {max_chars} characters" if max_chars is not None else "")
        else:
            self.expected = "text" + (
                f" of at most {max_chars} characters" if max_chars is not None else "")

    def check(self, value: object) -> object:
        if (type(value) is str and (not self.non_empty or value.strip() != "")
                and (self.max_chars is None or len(value) <= self.max_chars)):
            return value
        raise ValueProblem


# Line breaks and the characters OneLine and PlainText refuse (F30 04 §9, SEC-F30-10 (b)).
_LINE_BREAK_RE = re.compile(r"\r\n|[\n\r\u2028\u2029]")
_NOT_PLAIN_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))


def _has_control(text: str) -> bool:
    return any(unicodedata.category(c) in _NOT_PLAIN_CATEGORIES for c in text)


class OneLine(Validator):
    """One line of plain text of at most ``max_chars`` code points, for a word that a
    screen always shows on one line (F30's ``fake_crash_hint`` and ``fake_crash_label``,
    SEC-F30-10 (b)): no line break (``\\n``, ``\\r``, U+2028, U+2029) and no control or
    format character. An empty or blank value passes here: like any word it is W65 at
    install time and keeps its default (07 I-9)."""

    def __init__(self, max_chars: int, *, why: str) -> None:
        self.max_chars = max_chars
        self.expected = f"one line of plain text, 1 to {max_chars} characters, {why}"

    def _problem(self, value: str) -> str | None:
        lines = len(_LINE_BREAK_RE.split(value))
        if lines > 1:
            return f"it has {lines} lines."
        if _has_control(value):
            return "it has a control character."
        if len(value) > self.max_chars:
            return f"it has {len(value)} characters."
        return None

    def check(self, value: object) -> object:
        if type(value) is str and self._problem(value) is None:
            return value
        raise ValueProblem

    def found(self, value: object) -> str | None:
        return self._problem(value) if type(value) is str else None


class PlainText(Validator):
    """1 to ``max_chars`` code points with a visible character and no control, format, or
    line-break character (F30 ``[meta] username_fallback``)."""

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self.expected = (f"plain text of 1 to {max_chars} characters, with no control "
                         "characters")

    def check(self, value: object) -> object:
        if (type(value) is str and value.strip() != "" and len(value) <= self.max_chars
                and not _has_control(value)):
            return value
        raise ValueProblem


class NameList(Validator):
    """``[title] entries``, ``[quick_menu] entries`` (F10 §13, C11): a list of at most
    ``MENU_ENTRIES_MAX`` different names, each 1 to ``MENU_ENTRY_NAME_MAX_CHARS`` of
    ``a-z`` and ``_``, stored as a tuple. An empty list passes here; whether the names are
    registered for that menu is decided at install time (W66)."""

    _NAME = re.compile(rf"[a-z_]{{1,{MENU_ENTRY_NAME_MAX_CHARS}}}", re.ASCII)
    expected = (f"a list of at most {MENU_ENTRIES_MAX} different names, each 1 to "
                f'{MENU_ENTRY_NAME_MAX_CHARS} of a-z and _, e.g. ["new_game", "quit"]')

    def check(self, value: object) -> object:
        if (type(value) is list and len(value) <= MENU_ENTRIES_MAX
                and all(type(name) is str and self._NAME.fullmatch(name) for name in value)
                and len(set(value)) == len(value)):
            return tuple(value)
        raise ValueProblem


class IconRef(Validator):
    """``[window] icon``: any text. Non-PNG and blocked paths are decided when the icon
    is loaded (PR-F01-16, §7.11.7), so they fall back to the engine icon instead of
    stopping startup."""

    expected = 'text: a path to a .png file in the game folder, for example "gui/icon.png"'

    def check(self, value: object) -> object:
        if type(value) is str:
            return value
        raise ValueProblem


class AppId(Validator):
    """``[game] id``: the single app-id rule of ``paths.is_valid_app_id`` (SEC-F01-16)."""

    expected = ('1 to 40 characters, each a lower-case letter a-z, a digit 0-9, or "-", '
                'starting with a letter or digit, and not a reserved name such as "con"')

    def check(self, value: object) -> object:
        if is_valid_app_id(value):
            return value
        raise ValueProblem


class Position(Validator):
    """``[stage.positions]`` value: a number x (y is the bottom edge) or ``[x, y]``; each an
    int or float (not bool), finite, within ``STAGE_COORD_RANGE`` (SR-F04-24, §7.8)."""

    def __init__(self) -> None:
        self.lo, self.hi = STAGE_COORD_RANGE
        self.expected = f"a number or [x, y] with numbers from {self.lo} to {self.hi}"

    def check(self, value: object) -> object:
        if type(value) is list and len(value) == 2:
            return (self._coord(value[0]), self._coord(value[1]))
        return (self._coord(value), float(CANVAS_SIZE[1]))

    def _coord(self, value: object) -> float:
        # The range test also refuses nan and inf, and never converts a huge int to float.
        if type(value) in (int, float) and self.lo <= value <= self.hi:
            return float(value)
        raise ValueProblem


class PositionName(Validator):
    """``[stage.positions]`` key: an identifier already in NFKC form whose lower case is not
    a statement or stage word (§7.8). Not a number, since a digit cannot start a name."""

    expected = "one word of letters, digits, and _, not a number or statement word"

    def check(self, value: object) -> object:
        if (type(value) is str and value.isidentifier()
                and unicodedata.is_normalized("NFKC", value)
                and value.lower() not in STATEMENT_WORDS and value.lower() not in STAGE_WORDS):
            return value
        raise ValueProblem


class Opacity(Validator):
    """``*_opacity`` theme tokens: an int or float (not bool) from 0.0 to 1.0, stored as a
    float. With F08's ``Seconds``, one of the two ranges that are not whole numbers (F05
    07 §2.3). The range test also refuses nan and inf. ``low`` (F17 ``04`` §13) raises the
    bottom of the range, as ``[theme.nvl] fill_opacity``'s 0.5; ``high`` (F23 ``04`` §12)
    lowers the top, as ``[theme.minigame] stage_dim_opacity``'s 0.8."""

    expected = "a number from 0.0 to 1.0, such as 0.85 for 85%"

    def __init__(self, low: float = 0.0, high: float = 1.0) -> None:
        self.low = low
        self.high = high
        if high != 1.0:
            self.expected = f"a number from {low} to {high}, such as 0.3 for 30%"
        elif low != 0.0:
            self.expected = f"a number from {low} to 1.0, such as 0.85 for 85%"

    def check(self, value: object) -> object:
        if type(value) in (int, float) and self.low <= value <= self.high:  # type: ignore[operator]
            return float(value)                                  # type: ignore[arg-type]
        raise ValueProblem


class Seconds(Validator):
    """A time in seconds from ``lo`` to ``hi`` (F08 §13, 07 I-6): an int or float (not
    bool), stored as a float. The range test also refuses nan and inf, and never converts a
    huge int to float."""

    def __init__(self, lo: float, hi: float, *, expected: str | None = None) -> None:
        self.lo, self.hi = lo, hi
        self.expected = expected if expected is not None else f"seconds from {lo} to {hi}"

    def check(self, value: object) -> object:
        if type(value) in (int, float) and self.lo <= value <= self.hi:  # type: ignore[operator]
            return float(value)                                         # type: ignore[arg-type]
        raise ValueProblem


def _suffix(ref: str) -> str:
    """The lower-cased suffix of the last segment (``""`` if none), as ``AssetManager``
    reads it."""
    name = ref.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _game_ref(value: object) -> str | None:
    """``value`` if it is a game-folder ref that passes F01's syntax rules (PR-F01-55);
    no file-system call. Whether the file exists is decided at launch (W43, PR-F01-61)."""
    if type(value) is not str:
        return None
    try:
        check_ref(value)
    except AssetRefError:
        return None
    return value


class FontRef(Validator):
    """A theme font (``text_font``, ``bold_font``, ...): a ``.ttf`` or ``.otf`` ref inside
    the game folder (F05 §13). Fonts are referred to by path, like ``[window] icon``."""

    expected = "a .ttf or .otf file inside the game folder, written with /"

    def check(self, value: object) -> object:
        ref = _game_ref(value)
        if ref is not None and _suffix(ref) in FONT_SUFFIXES:
            return ref
        raise ValueProblem


class GuiImageRef(Validator):
    """A theme image (``frame_image``): a ref under ``gui/`` with an image suffix that
    ``AssetManager`` loads. Theme images are a separate asset kind from story images, so
    they are game-relative paths, not ``ImageIndex`` names (F05 07 §2.3)."""

    expected = 'an image in gui/, e.g. "gui/textbox.png"'

    def check(self, value: object) -> object:
        ref = _game_ref(value)
        if ref is not None and ref.startswith("gui/") and _suffix(ref) in IMAGE_SUFFIXES:
            return ref
        raise ValueProblem


def is_audio_ref(value: object) -> bool:
    """True if ``value`` names a file inside ``audio/`` as in F08 SR-F08-01/02: the one
    audio-ref check (F08 07 I-6, F10 07 I-5). Refused: a path starting with ``audio/`` in
    any case (E144), a last segment with no extension (E145), and anything
    ``check_ref("audio/" + value)`` refuses (E143). Any extension passes. No file-system
    call: whether the file exists is decided at launch."""
    return (type(value) is str and not value[:6].lower() == "audio/"
            and _suffix(value) != "" and _game_ref("audio/" + value) is not None)


class AudioRef(Validator):
    """A sound or music value (F10's ``*_sound`` tokens and ``[theme.title] music``, F07's
    sound tokens): ``is_audio_ref``, stored as written. Like every validator it works
    outside config loading too, e.g. for refs given to F10's ``UiOverrides`` (F10 07)."""

    expected = 'a file inside audio/ with its extension, e.g. "bgm/festival.ogg"'

    def check(self, value: object) -> object:
        if is_audio_ref(value):
            return value
        raise ValueProblem


class AudioFileKey(AudioRef):
    """A ``[audio.loop_start]`` key: ``AudioRef``'s check and phrase (07 I-6). A format
    that can't take loop points is W31 later (SR-F08-23). Whether the file exists is W25
    at launch."""


# --- Nested tables (F04 §7.8, I-6) --------------------------------------------------------
# These two validator kinds are walked by ``config._validate``, which gives each problem
# inside them its own line and its label from the section path; ``check`` only refuses the
# value so that the generic "Remove the quotes." hint never applies to them.

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)


def toml_key(key: str) -> str:
    """A key as it would be written in TOML: bare when it can be, else in double quotes
    (``"stall spot"``, ``"bgm/festival.ogg"``). The default label formatter of ``EntryMap``;
    like every label formatter, it returns text safe to embed: redacted, escaped, cut to
    ``VALUE_ECHO_MAX_CHARS``."""
    shown = echo(key, VALUE_ECHO_MAX_CHARS)
    return shown if _BARE_KEY.fullmatch(key) and shown == key else f'"{shown}"'


def quoted_key(key: str) -> str:
    """A key always in double quotes, even when it could be bare: the label formatter of
    ``[audio.loop_start]``, whose keys are files written in TOML quotes (F08 SR-F08-23,
    07 I-6). Redacted, escaped, and cut like ``toml_key``."""
    return f'"{echo(key, VALUE_ECHO_MAX_CHARS)}"'


class Table(Validator):
    """A sub-table with fixed keys, validated like a section into ``cls`` (a frozen
    dataclass whose fields carry ``spec`` metadata). Nests: a field of ``cls`` may itself be
    a ``Table``. Unknown keys warn, as in a section. A field **without** ``spec`` metadata
    is not read from ``config.toml`` yet (a token a later feature opens, as F10 opened
    F05's ``textbox.*``): it keeps its default, and setting it warns like an unknown key."""

    expected = "a section"

    def __init__(self, cls: type) -> None:
        self.cls = cls

    def check(self, value: object) -> object:
        raise ValueProblem


class EntryMap(Validator):
    """A sub-table whose keys the author chooses (``[stage.positions]``, F08's
    ``[audio.loop_start]``).

    ``key_check`` and ``value_validator`` are ordinary validators: each bad entry gives one
    ``ConfigError`` (the key is checked first), and the label of every message is
    ``label(key)`` (already safe to embed, see ``toml_key``). More than ``max_entries`` entries give one error and no entry is read.
    Valid entries, laid over ``base``, are stored in a read-only mapping under the key that
    ``key_check`` returns.
    """

    expected = "a section"

    def __init__(self, key_check: Validator, value_validator: Validator, max_entries: int, *,
                 label: Callable[[str], str] = toml_key,
                 base: Mapping[str, object] = MappingProxyType({})) -> None:
        self.key_check = key_check
        self.value_validator = value_validator
        self.max_entries = max_entries
        self.label = label
        self.base = base

    def check(self, value: object) -> object:
        raise ValueProblem


def spec(validator: Validator, doc: str = "", *, key: str | None = None) -> dict[str, Any]:
    """Field metadata for a config key: its validator and an optional description. ``key``
    is the key as written in ``config.toml`` when it can't be the field's name (a Python
    keyword: ``[words] return`` is the field ``return_``)."""
    metadata: dict[str, Any] = {"validator": validator, "doc": doc}
    if key is not None:
        metadata["key"] = key
    return metadata


def config_fields(cls: type) -> dict[str, dataclasses.Field]:
    """The keys of a section or ``Table`` class as written in ``config.toml`` → their
    fields, in declaration order. Only fields with ``spec`` metadata are keys."""
    return {f.metadata.get("key", f.name): f
            for f in dataclasses.fields(cls) if "validator" in f.metadata}


def word_fields() -> dict[str, dataclasses.Field]:
    """The ``[words]`` keys that are words (``config_fields(WordsConfig)`` without F23's raw
    ``plugin`` table): what ``Words`` serves and F32's ``set_word`` accepts."""
    return {key: f for key, f in config_fields(WordsConfig).items()
            if not isinstance(f.metadata["validator"], RawPluginTables)}


@dataclass(frozen=True)
class GameConfig:
    title: str = field(default="Untitled Visual Novel", metadata=spec(Text(non_empty=True),
        "the game's name: the window title and the title screen"))
    version: str = field(default="0.0.0", metadata=spec(Text(),
        "the game's version, shown on the title screen and kept in saves"))
    id: str | None = field(default=None, metadata=spec(AppId(),
        "the name of the folder that keeps players' saves and settings; set it once and "
        "never change it"))        # ADR-0003 §4, SEC-F01-16


@dataclass(frozen=True)
class WindowConfig:
    width: int = field(default=DEFAULT_WINDOW_SIZE[0], metadata=spec(IntRange(640, 7680),
        "the window's starting width in pixels"))
    height: int = field(default=DEFAULT_WINDOW_SIZE[1], metadata=spec(IntRange(360, 4320),
        "the window's starting height in pixels"))
    fullscreen: bool = field(default=False, metadata=spec(Bool(),
        "start the game in fullscreen (a player's own choice in Settings wins)"))
    resizable: bool = field(default=True, metadata=spec(Bool(), "let the player resize the window"))
    icon: str | None = field(default=None, metadata=spec(IconRef(),
        "the window icon, a .png in the game folder"))   # type check only (PR-F01-16)
    letterbox_color: RGB = field(default=(0, 0, 0), metadata=spec(HexColor(),
        "the color of the bars beside or above the game when the window is a different "
        "shape"))
    scale_filter: Literal["smooth", "pixel"] = field(default="smooth",
                                                     metadata=spec(Choice("smooth", "pixel"),
        "how art is stretched to fit the window: smooth suits painted art, pixel keeps "
        "pixel art crisp"))
    integer_scale: bool = field(default=False, metadata=spec(Bool(),             # PR-F01-26
        "only grow the game by whole steps (2×, 3×…): sharper pixel art, wider bars"))


@dataclass(frozen=True)
class EngineConfig:
    fps: int = field(default=60, metadata=spec(IntRange(30, 240),
        "how many times a second the screen is drawn"))
    cache_mb: int = field(default=512, metadata=spec(IntRange(64, 8192),
        "how many megabytes of pictures the game keeps ready in memory"))   # budget = cache_mb * MB
    log_level: Literal["debug", "info", "warning", "error"] = field(
        default="info", metadata=spec(Choice("debug", "info", "warning", "error"),
        "how much detail the game writes to its log file"))


@dataclass(frozen=True)
class StageConfig:
    art_height: int = field(default=CANVAS_SIZE[1], metadata=spec(IntRange(*ART_HEIGHT_RANGE),
        "the screen height your art is drawn for; pictures on the stage are scaled from it"))
    # Built-ins plus the author's entries (which may redefine left, center, right).
    positions: Mapping[str, Point] = field(
        default=BUILTIN_POSITIONS,
        metadata=spec(EntryMap(PositionName(), Position(), STAGE_POSITIONS_MAX,
                               base=BUILTIN_POSITIONS),
        "your own named spots on the stage for show … at, each set by how far across "
        "(and, if you like, how far down) it is"))


@dataclass(frozen=True)
class StageTheme:
    """``[theme.stage]`` tokens (03-ui "Theme tokens"; proposed by UI, F10 confirms)."""
    empty_color: RGB = field(default=(0, 0, 0), metadata=spec(HexColor()))


@dataclass(frozen=True)
class TextboxConfig:
    """``[textbox]``: textbox behavior (PR-F05-07). Look settings are ``[theme.textbox]``."""
    cps: int = field(default=DEFAULT_TEXTBOX_CPS, metadata=spec(
        IntRange(*TEXTBOX_CPS_RANGE, note="0 shows text instantly"),
        "how many characters appear each second as a line types out; 0 shows each line at "
        "once"))


# F05 02 §5.3: textbox colors say only 'a color "#RRGGBB"'.
_TEXTBOX_COLOR = HexColor('a color "#RRGGBB"')


@dataclass(frozen=True)
class NameTabTheme:
    """``[theme.textbox.name_tab]`` (F05 03-ui "Theme tokens"). ``text_color`` is F05
    §13's key; F10 opened the rest with F05 03-ui's ranges (PR-F10-16)."""
    text_color: RGB = field(default=(0xA0, 0x28, 0x60), metadata=spec(
        _TEXTBOX_COLOR, "the name color for characters who have no color of their own"))
    text_font: str | None = field(default=None, metadata=spec(FontRef()))  # None: textbox bold
    text_size: int = field(default=DEFAULT_TEXT_SIZE, metadata=spec(IntRange(*TEXT_SIZE_RANGE)))
    fill_color: RGB = field(default=(0xFF, 0xE6, 0xF0), metadata=spec(_TEXTBOX_COLOR))
    fill_opacity: float = field(default=1.0, metadata=spec(Opacity()))
    frame_image: str | None = field(default=None, metadata=spec(GuiImageRef()))  # nine-slice
    corner_radius: int = field(default=12, metadata=spec(IntRange(0, 24)))
    left_gap: int = field(default=24, metadata=spec(IntRange(0, 200)))
    side_padding: int = field(default=20, metadata=spec(IntRange(8, 40)))
    min_width: int = field(default=120, metadata=spec(IntRange(40, 500)))


@dataclass(frozen=True)
class IndicatorTheme:
    """``[theme.textbox.indicator]`` (F05 03-ui), opened by F10 (PR-F10-16)."""
    fill_color: RGB = field(default=(0xA0, 0x28, 0x60), metadata=spec(_TEXTBOX_COLOR))
    line_image: str | None = field(default=None, metadata=spec(GuiImageRef()))
    page_image: str | None = field(default=None, metadata=spec(GuiImageRef()))


@dataclass(frozen=True)
class TextboxTheme:
    """``[theme.textbox]`` tokens (F05 03-ui "Theme tokens"; PR-F05-04). F05 §13 read the
    first group; F10 opened the rest with F05 03-ui's ranges (PR-F10-16). Fonts and images
    are game-folder refs; ``None`` means the bundled face or the drawn box."""
    text_font: str | None = field(default=None, metadata=spec(FontRef()))
    bold_font: str | None = field(default=None, metadata=spec(FontRef()))
    italic_font: str | None = field(default=None, metadata=spec(FontRef()))
    bold_italic_font: str | None = field(default=None, metadata=spec(FontRef()))
    text_size: int = field(default=DEFAULT_TEXT_SIZE,
                           metadata=spec(IntRange(*TEXT_SIZE_RANGE)))
    text_color: RGB = field(default=(0x3D, 0x2B, 0x36), metadata=spec(_TEXTBOX_COLOR))
    fill_color: RGB = field(default=(0xFF, 0xF4, 0xF8), metadata=spec(_TEXTBOX_COLOR))
    fill_opacity: float = field(default=0.80, metadata=spec(Opacity()))
    frame_image: str | None = field(default=None, metadata=spec(GuiImageRef()))
    name_tab: NameTabTheme = field(default_factory=NameTabTheme,
                                   metadata=spec(Table(NameTabTheme)))
    indicator: IndicatorTheme = field(default_factory=IndicatorTheme,
                                      metadata=spec(Table(IndicatorTheme)))
    # Opened by F10 (canvas units).
    border_color: RGB = field(default=(0xF0, 0xA0, 0xC0), metadata=spec(_TEXTBOX_COLOR))
    border_width: int = field(default=2, metadata=spec(IntRange(0, 8)))
    corner_radius: int = field(default=16, metadata=spec(IntRange(0, 48)))
    frame_slice_width: int = field(default=24, metadata=spec(IntRange(0, 96)))  # both frames
    width: int = field(default=1000, metadata=spec(IntRange(*TEXTBOX_WIDTH_RANGE)))
    height: int = field(default=184, metadata=spec(IntRange(120, 216)))  # minimum (UI-F05-01)
    bottom_gap: int = field(default=32, metadata=spec(IntRange(0, 120)))
    side_padding: int = field(default=40, metadata=spec(IntRange(24, 120)))
    top_padding: int = field(default=28, metadata=spec(IntRange(8, 80)))
    bottom_padding: int = field(default=28, metadata=spec(IntRange(8, 80)))


# --- F10 theme areas (F10 03-ui "Theme tokens", 04 §4, §13) --------------------------------
# One Table per area and per nested state or element; every 03-ui row is exactly one field
# (tests/fixtures/F10/tokens.csv). Lengths and sizes are canvas units; ``_ms`` durations are
# whole milliseconds. ``None`` refs mean the drawn look, no image, or no sound.

_UI_COLOR = HexColor('a color like "#RRGGBB"')
_PLUM = (0x3D, 0x2B, 0x36)                    # body text
_PINK_WHITE = (0xFF, 0xF4, 0xF8)              # panel and button fill
_PINK = (0xF0, 0xA0, 0xC0)                    # borders, dividers
_BERRY = (0xA0, 0x28, 0x60)                   # focus, markers, headings
_BLUSH = (0xFF, 0xD6, 0xE8)                   # focused, pressed, on fills
_MAUVE = (0x6E, 0x5E, 0x68)                   # disabled and secondary text
_TRACK = (0x7E, 0x5C, 0x74)                   # off tracks
_WIDGET_TEXT_SIZE = IntRange(24, 48)          # panel and button labels


def _color(default: RGB) -> Any:
    return field(default=default, metadata=spec(_UI_COLOR))


def _opacity(default: float) -> Any:
    return field(default=default, metadata=spec(Opacity()))


def _length(default: int, lo: int, hi: int) -> Any:
    return field(default=default, metadata=spec(IntRange(lo, hi)))


def _image() -> Any:
    return field(default=None, metadata=spec(GuiImageRef()))


def _sound() -> Any:
    return field(default=None, metadata=spec(AudioRef()))


def _table(cls: type) -> Any:
    return field(default_factory=cls, metadata=spec(Table(cls)))


@dataclass(frozen=True)
class UiAreaTheme:
    """``[theme.ui]``. Fonts ``None``: the textbox's ``text_font`` / ``bold_font``."""
    text_font: str | None = field(default=None, metadata=spec(FontRef()))
    bold_font: str | None = field(default=None, metadata=spec(FontRef()))
    fade_ms: int = _length(150, 0, 1000)
    back_sound: str | None = _sound()


@dataclass(frozen=True)
class PanelHeadingTheme:
    """``[theme.panel.heading]``."""
    text_size: int = _length(32, 24, 64)
    text_color: RGB = _color(_BERRY)


@dataclass(frozen=True)
class PanelTheme:
    """``[theme.panel]``: sidebar, pages, dialog, backings, version pill."""
    fill_color: RGB = _color(_PINK_WHITE)
    fill_opacity: float = _opacity(0.94)
    border_color: RGB = _color(_PINK)
    border_width: int = _length(2, 0, 8)
    corner_radius: int = _length(16, 0, 48)
    frame_image: str | None = _image()                # nine-slice
    frame_slice_width: int = _length(24, 0, 96)
    text_size: int = field(default=28, metadata=spec(_WIDGET_TEXT_SIZE))
    text_color: RGB = _color(_PLUM)
    heading: PanelHeadingTheme = _table(PanelHeadingTheme)


@dataclass(frozen=True)
class ButtonFocusedTheme:
    """``[theme.button.focused]``: focused and selected fill; the focus outline of every
    widget."""
    fill_color: RGB = _color(_BLUSH)
    border_color: RGB = _color(_BERRY)
    border_width: int = _length(4, 2, 8)
    frame_image: str | None = _image()


@dataclass(frozen=True)
class ButtonPressedTheme:
    """``[theme.button.pressed]``."""
    fill_color: RGB = _color((0xFF, 0xC2, 0xDC))
    frame_image: str | None = _image()


@dataclass(frozen=True)
class ButtonSelectedTheme:
    """``[theme.button.selected]``."""
    frame_image: str | None = _image()


@dataclass(frozen=True)
class ButtonDisabledTheme:
    """``[theme.button.disabled]``: disabled text and tracks of every widget."""
    text_color: RGB = _color(_MAUVE)
    border_width: int = _length(0, 0, 8)
    track_color: RGB = _color((0xC8, 0xB8, 0xC2))
    frame_image: str | None = _image()


@dataclass(frozen=True)
class ButtonMarkerTheme:
    """``[theme.button.marker]``: marker, pip, selected bar."""
    fill_color: RGB = _color(_BERRY)


@dataclass(frozen=True)
class ButtonTheme:
    """``[theme.button]`` (grid cells use it too)."""
    text_size: int = field(default=28, metadata=spec(_WIDGET_TEXT_SIZE))
    text_color: RGB = _color(_PLUM)
    fill_color: RGB = _color(_PINK_WHITE)             # also disabled
    fill_opacity: float = _opacity(0.90)              # all states
    border_color: RGB = _color(_PINK)
    border_width: int = _length(2, 0, 8)
    corner_radius: int = _length(12, 0, 28)
    frame_image: str | None = _image()                # nine-slice, normal state
    frame_slice_width: int = _length(24, 0, 96)       # all states
    height: int = _length(56, 40, 120)                # minimum
    side_padding: int = _length(32, 24, 80)
    gap: int = _length(12, 0, 48)
    focused: ButtonFocusedTheme = _table(ButtonFocusedTheme)
    pressed: ButtonPressedTheme = _table(ButtonPressedTheme)
    selected: ButtonSelectedTheme = _table(ButtonSelectedTheme)
    disabled: ButtonDisabledTheme = _table(ButtonDisabledTheme)
    marker: ButtonMarkerTheme = _table(ButtonMarkerTheme)
    focus_sound: str | None = _sound()
    activate_sound: str | None = _sound()


@dataclass(frozen=True)
class ToggleOnTheme:
    """``[theme.toggle.on]``."""
    track_color: RGB = _color(_BERRY)
    knob_color: RGB = _color((0xFF, 0xFF, 0xFF))


@dataclass(frozen=True)
class ToggleTheme:
    """``[theme.toggle]``."""
    track_color: RGB = _color(_TRACK)                 # off track outline and knob
    on: ToggleOnTheme = _table(ToggleOnTheme)


@dataclass(frozen=True)
class SliderTheme:
    """``[theme.slider]``."""
    track_color: RGB = _color(_TRACK)
    fill_color: RGB = _color(_BERRY)
    thumb_color: RGB = _color(_BERRY)
    thumb_border_color: RGB = _color(_PINK_WHITE)


@dataclass(frozen=True)
class ListEmptyTheme:
    """``[theme.list.empty]``."""
    text_color: RGB = _color(_MAUVE)


@dataclass(frozen=True)
class ListTheme:
    """``[theme.list]``."""
    row_height: int = _length(48, 32, 120)            # minimum
    divider_color: RGB = _color(_PINK)
    scrollbar_color: RGB = _color(_BERRY)
    scrollbar_track_color: RGB = _color((0xF0, 0xD0, 0xDE))
    empty: ListEmptyTheme = _table(ListEmptyTheme)


@dataclass(frozen=True)
class TitleLogoTheme:
    """``[theme.title.logo]``: the title text drawn when there is no logo image."""
    text_size: int = _length(64, 40, 96)
    text_color: RGB = _color(_BERRY)


@dataclass(frozen=True)
class TitleVersionTheme:
    """``[theme.title.version]``."""
    text_size: int = _length(20, 16, 28)
    text_color: RGB = _color(_MAUVE)
    fill_opacity: float = _opacity(0.90)              # version pill


@dataclass(frozen=True)
class TitleLoadingTheme:
    """``[theme.title.loading]``."""
    text_color: RGB = _color((0xFF, 0xE6, 0xF0))      # loading text and dots


@dataclass(frozen=True)
class TitleTheme:
    """``[theme.title]``. ``music`` is a file inside ``audio/`` (the ``music`` type, 07 I-5),
    looped on the title."""
    background_image: str | None = _image()
    logo_image: str | None = _image()
    music: str | None = field(default=None, metadata=spec(AudioRef()))
    fill_top_color: RGB = _color(_PINK_WHITE)         # plain title gradient
    fill_bottom_color: RGB = _color(_BLUSH)
    logo: TitleLogoTheme = _table(TitleLogoTheme)
    button_width: int = _length(320, 200, 560)
    version: TitleVersionTheme = _table(TitleVersionTheme)
    loading: TitleLoadingTheme = _table(TitleLoadingTheme)
    fade_in_ms: int = _length(500, 0, 2000)


@dataclass(frozen=True)
class MenuTheme:
    """``[theme.menu]``: the game menu (its dim color also under the confirm dialog)."""
    dim_color: RGB = _color((0x2A, 0x1E, 0x26))
    dim_opacity: float = _opacity(0.55)
    button_width: int = _length(288, 200, 312)


@dataclass(frozen=True)
class QuickMenuFocusedTheme:
    """``[theme.quick_menu.focused]``: hover."""
    text_color: RGB = _color(_BERRY)
    underline_width: int = _length(2, 1, 4)


@dataclass(frozen=True)
class QuickMenuPressedTheme:
    """``[theme.quick_menu.pressed]``."""
    fill_color: RGB = _color(_BLUSH)


@dataclass(frozen=True)
class QuickMenuOnTheme:
    """``[theme.quick_menu.on]``: the chip of an item that is on (e.g. Hide)."""
    fill_color: RGB = _color(_BLUSH)
    border_color: RGB = _color(_BERRY)
    border_width: int = _length(2, 1, 4)


@dataclass(frozen=True)
class QuickMenuDisabledTheme:
    """``[theme.quick_menu.disabled]``."""
    text_color: RGB = _color(_MAUVE)


@dataclass(frozen=True)
class QuickMenuTheme:
    """``[theme.quick_menu]``. ``activate_sound`` ``None``: ``button.activate_sound``."""
    text_size: int = _length(20, 20, 24)              # scaling stops at 24
    text_color: RGB = _color(_PLUM)
    fill_color: RGB = _color(_PINK_WHITE)
    fill_opacity: float = _opacity(0.90)
    corner_radius: int = _length(14, 0, 16)
    frame_image: str | None = _image()                # nine-slice, replaces the pill
    frame_slice_width: int = _length(12, 0, 16)
    side_padding: int = _length(12, 4, 24)            # per item
    bottom_gap: int = _length(2, 0, 32)               # canvas bottom to pill
    focused: QuickMenuFocusedTheme = _table(QuickMenuFocusedTheme)
    pressed: QuickMenuPressedTheme = _table(QuickMenuPressedTheme)
    on: QuickMenuOnTheme = _table(QuickMenuOnTheme)
    disabled: QuickMenuDisabledTheme = _table(QuickMenuDisabledTheme)
    activate_sound: str | None = _sound()


@dataclass(frozen=True)
class ConfirmTheme:
    """``[theme.confirm]``."""
    dim_opacity: float = _opacity(0.35)               # extra dim under the dialog
    width: int = _length(640, 480, 1000)
    button_width: int = _length(200, 160, 280)        # Yes/No minimum


# --- [theme.save] and [theme.notice] (F11 03-ui "Theme tokens"; 04 §13) --------------------
# A color or opacity default ``None`` follows another token (03-ui "Default" names it): the
# notice's fill, opacity, border, and text follow ``panel.*``, its bar
# ``button.marker.fill_color``. ``ui/notice.py: notice_style`` resolves them.

def _follow_color() -> Any:
    return field(default=None, metadata=spec(_UI_COLOR))


def _follow_opacity() -> Any:
    return field(default=None, metadata=spec(Opacity()))


@dataclass(frozen=True)
class SaveBadgeTheme:
    """``[theme.save.badge]``: label, version, and "Loading…" tags; the delete × circle."""
    fill_color: RGB = _color(_PINK_WHITE)
    fill_opacity: float = _opacity(0.90)
    text_color: RGB = _color(_PLUM)


@dataclass(frozen=True)
class SaveNewestTheme:
    """``[theme.save.newest]``: the "Newest" tag (opaque)."""
    fill_color: RGB = _color(_BERRY)
    text_color: RGB = _color((0xFF, 0xFF, 0xFF))


@dataclass(frozen=True)
class SavePlaceholderTheme:
    """``[theme.save.placeholder]``: empty, loading, damaged areas; a missing thumbnail."""
    fill_color: RGB = _color((0xF0, 0xD0, 0xDE))
    text_color: RGB = _color(_PLUM)


@dataclass(frozen=True)
class SaveTheme:
    """``[theme.save]``: the Save and Load pages (F11)."""
    text_size: int = _length(24, 24, 36)              # dates, descriptions, tags, words
    badge: SaveBadgeTheme = _table(SaveBadgeTheme)
    newest: SaveNewestTheme = _table(SaveNewestTheme)
    placeholder: SavePlaceholderTheme = _table(SavePlaceholderTheme)
    no_picture_image: str | None = _image()           # scaled to cover a missing thumbnail
    load_fade_ms: int = _length(300, 0, 2000)


@dataclass(frozen=True)
class NoticeMarkerTheme:
    """``[theme.notice.marker]``: the problem bar. ``None``: ``button.marker.fill_color``."""
    fill_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class NoticeTheme:
    """``[theme.notice]``: the shared non-modal notice (F11, ui-system §9). ``None`` colors
    and opacity follow ``panel.*``."""
    fill_color: RGB | None = _follow_color()          # panel.fill_color
    fill_opacity: float | None = _follow_opacity()    # panel.fill_opacity
    border_color: RGB | None = _follow_color()        # panel.border_color
    border_width: int = _length(2, 0, 8)
    corner_radius: int = _length(12, 0, 28)
    frame_image: str | None = _image()                # nine-slice, replaces fill and border
    frame_slice_width: int = _length(24, 0, 96)
    text_size: int = _length(24, 24, 36)
    text_color: RGB | None = _follow_color()          # panel.text_color
    marker: NoticeMarkerTheme = _table(NoticeMarkerTheme)
    max_width: int = _length(560, 320, 800)
    duration_ms: int = _length(1500, 1000, 10000)     # shown time for ≤ 20 characters
    fade_ms: int = _length(200, 0, 1000)              # in, out, restack
    sound: str | None = _sound()                      # when a notice appears


# --- [theme.choice] (F07 01 §6.4, 04 §13) ---------------------------------------------------
# Every token with 04 §13's range (O2: the ranges the design doesn't give are the
# architect's). Colors are RGB; lengths canvas units. Sounds are files inside ``audio/``
# (07 I-4 O1), played through ``App.audio.play_ui``; a missing one is W48 and silence.

@dataclass(frozen=True)
class ChoiceFocusedTheme:
    """``[theme.choice.focused]``: the focused button (UI-F07-02)."""
    fill_color: RGB = _color((0xFF, 0xD6, 0xE8))
    border_color: RGB = _color((0xA0, 0x28, 0x60))
    border_width: int = _length(4, 0, 16)
    frame_image: str | None = _image()                # nine-slice, the focused state only


@dataclass(frozen=True)
class ChoiceMarkerTheme:
    """``[theme.choice.marker]``: the focus marker."""
    fill_color: RGB = _color((0xA0, 0x28, 0x60))


@dataclass(frozen=True)
class ChoiceLockedTheme:
    """``[theme.choice.locked]``: a locked choice's text and lock mark. ``fill_opacity`` is
    0.90, not the design's 0.60 (07 I-3, G2: locked text then meets 4.5:1)."""
    text_color: RGB = _color((0x6E, 0x5E, 0x68))
    fill_opacity: float = _opacity(0.90)


@dataclass(frozen=True)
class ChoiceTheme:
    """``[theme.choice]`` (F07 design §6.4, ``04`` §13). ``text_font``/``text_size``
    ``None``: the textbox's (bold and italic faces always come from ``[theme.textbox]``).
    The text width is ``max(100, width − 2 × side_padding)`` (07 I-4). ``frame_image``
    serves the normal and locked states, ``focused.frame_image`` the focused one; each
    replaces that state's fill and border (ui-system §3 "Per state")."""
    text_font: str | None = field(default=None, metadata=spec(FontRef()))
    text_size: int | None = field(default=None, metadata=spec(IntRange(*TEXT_SIZE_RANGE)))
    text_color: RGB = _color((0x3D, 0x2B, 0x36))
    fill_color: RGB = _color((0xFF, 0xF4, 0xF8))
    fill_opacity: float = _opacity(0.90)
    border_color: RGB = _color((0xF0, 0xA0, 0xC0))
    border_width: int = _length(2, 0, 16)
    corner_radius: int = _length(12, 0, 64)
    frame_image: str | None = _image()                # nine-slice
    frame_slice_width: int = _length(24, 1, 128)
    width: int = _length(800, 400, 1200)
    gap: int = _length(12, 0, 64)
    side_padding: int = _length(40, 0, 200)
    top_padding: int = _length(10, 0, 64)
    bottom_padding: int = _length(10, 0, 64)
    focused: ChoiceFocusedTheme = _table(ChoiceFocusedTheme)
    marker: ChoiceMarkerTheme = _table(ChoiceMarkerTheme)
    locked: ChoiceLockedTheme = _table(ChoiceLockedTheme)
    focus_sound: str | None = _sound()
    pick_sound: str | None = _sound()
    fade_in_ms: int = _length(120, 0, 1000)


# The ten F10 areas of ``ThemeConfig``, in 03-ui order.
@dataclass(frozen=True)
class EffectsTheme:
    """``[theme.effects]`` (F09 ``04`` §12): the flash color and the color ``fade`` goes
    through, when the script gives none."""
    flash_color: RGB = field(default=(0xFF, 0xFF, 0xFF), metadata=spec(HexColor()))
    fade_color: RGB = field(default=(0x00, 0x00, 0x00), metadata=spec(HexColor()))


@dataclass(frozen=True)
class ChapterHeadingTheme:
    """``[theme.chapter.heading]`` (F18 §4): the small line above a chapter's title.
    ``text_font`` None: ``ui.text_font`` (then the textbox's face)."""
    text_font: str | None = field(default=None, metadata=spec(FontRef()))
    text_size: int = _length(32, 20, 64)
    text_color: RGB = _color((0xF0, 0xA0, 0xC0))


@dataclass(frozen=True)
class ChapterTitleTheme:
    """``[theme.chapter.title]`` (F18 §4). ``text_font`` None: ``ui.bold_font``."""
    text_font: str | None = field(default=None, metadata=spec(FontRef()))
    text_size: int = _length(56, 24, 96)
    text_color: RGB = _color((0xFF, 0xF4, 0xF8))


@dataclass(frozen=True)
class ChapterTheme:
    """``[theme.chapter]`` (F18 §4 UI-F18-01): the chapter title card, in canvas units, never
    scaled by the player's text size."""
    fill_color: RGB = _color((0x2A, 0x1E, 0x26))
    fill_opacity: float = _opacity(1.0)
    heading: ChapterHeadingTheme = _table(ChapterHeadingTheme)
    title: ChapterTitleTheme = _table(ChapterTitleTheme)
    gap: int = _length(16, 0, 64)
    max_width: int = _length(1040, 400, 1240)


# --- [theme.nvl] (F17 04 §13; 06 AC-F17-31) ---------------------------------------------------
# A ``None`` default follows ``[theme.textbox]`` (its fill and text colors, text size, name tab
# text color, indicator color); ``render/nvllayout.nvl_look`` resolves them. Canvas units.

@dataclass(frozen=True)
class NvlNameTheme:
    """``[theme.nvl.name]``. ``text_color`` None: ``textbox.name_tab.text_color``."""
    text_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class NvlIndicatorTheme:
    """``[theme.nvl.indicator]``. ``fill_color`` None: ``textbox.indicator.fill_color``."""
    fill_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class NvlTheme:
    """``[theme.nvl]``: the full-screen text panel and page (F17 design §6.2). ``None``
    values follow ``[theme.textbox]``. The text area is ``width`` wide, centered, from
    ``top_gap`` to ``720 − bottom_gap``; ``line_gap`` is the space between two lines."""
    fill_color: RGB | None = _follow_color()
    fill_opacity: float = field(default=0.85, metadata=spec(Opacity(low=0.5)))
    width: int = _length(920, 640, 1200)
    top_gap: int = _length(64, 24, 200)
    bottom_gap: int = _length(72, 40, 200)
    line_gap: int = _length(20, 0, 80)
    text_size: int | None = field(default=None, metadata=spec(IntRange(*TEXT_SIZE_RANGE)))
    text_color: RGB | None = _follow_color()
    name: NvlNameTheme = _table(NvlNameTheme)
    indicator: NvlIndicatorTheme = _table(NvlIndicatorTheme)


# --- [theme.rollback] (F14 03-ui "Theme tokens"; 04 §13) -------------------------------------
# The limit cue's mark. The defaults are the default textbox's name-tab fill, border, and
# indicator colors; the rewind tag reuses ``quick_menu.*`` and has no tokens of its own.

@dataclass(frozen=True)
class RollbackMarkTheme:
    """``[theme.rollback.mark]``: the limit mark, an opaque 56×28 pill (border width
    ``textbox.border_width``) with a bar over an up-triangle. ``image`` replaces pill and
    glyph (a missing or unusable one: the drawn mark and W64)."""
    fill_color: RGB = _color((0xFF, 0xE6, 0xF0))
    border_color: RGB = _color(_PINK)
    glyph_color: RGB = _color(_BERRY)
    image: str | None = _image()


@dataclass(frozen=True)
class RollbackTheme:
    """``[theme.rollback]`` (F14 03-ui): the limit cue. ``bump_height`` 0 = no bump;
    ``limit_sound`` plays on F08's UI channel when the mark appears (none: silence)."""
    mark: RollbackMarkTheme = _table(RollbackMarkTheme)
    bump_height: int = _length(6, 0, 12)
    limit_sound: str | None = _sound()


# --- [theme.codex] (F21 01 §6 "Theme tokens", 04 §13) ----------------------------------------
# A ``None`` color follows another token: the unread dot ``button.marker.fill_color``, a
# locked tip's ``???`` ``button.disabled.text_color`` (``ui/builtin/codex_page.py`` resolves
# them, so an author's changed value of the followed token is used).

@dataclass(frozen=True)
class CodexNewTheme:
    """``[theme.codex.new]``: the unread dot. ``None``: ``button.marker.fill_color``."""
    fill_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class CodexLockedTheme:
    """``[theme.codex.locked]``: a locked tip's ``???`` row (``[codex] show_locked``).
    ``None``: ``button.disabled.text_color``."""
    text_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class CodexTheme:
    """``[theme.codex]``: the codex page (F21). ``image_height`` 0 hides pictures."""
    new: CodexNewTheme = _table(CodexNewTheme)
    locked: CodexLockedTheme = _table(CodexLockedTheme)
    image_height: int = _length(200, 0, 320)


# --- [theme.gallery] (F34 01 §6.3 "Theme tokens") ----------------------------------------------

@dataclass(frozen=True)
class GalleryCaptionTheme:
    """``[theme.gallery.caption]``: the title under each unlocked tile."""
    text_size: int = _length(20, 14, 32)


@dataclass(frozen=True)
class GalleryViewerTheme:
    """``[theme.gallery.viewer]``: the full-screen viewer's fill around the picture."""
    fill_color: RGB = _color((0x00, 0x00, 0x00))


@dataclass(frozen=True)
class GalleryTheme:
    """``[theme.gallery]``: the Extras screen's Gallery page and viewer (F34)."""
    caption: GalleryCaptionTheme = _table(GalleryCaptionTheme)
    viewer: GalleryViewerTheme = _table(GalleryViewerTheme)


# --- [theme.flowchart] (F20 03-ui "Theme tokens", 04 §13) ------------------------------------
# A ``None`` color follows another token (03 "Default"): ``node.text_color`` ``panel.text_color``,
# ``gate.fill_color`` ``flowchart.fill_color``, ``unknown.text_color``
# ``button.disabled.text_color``, ``path.line_color`` ``button.marker.fill_color``, and
# ``here.*`` ``save.newest.*`` (``ui/builtin/flowchart_page.py: flow_color`` resolves them).

@dataclass(frozen=True)
class FlowchartNodeTheme:
    """``[theme.flowchart.node]``: a visited box (``width`` in layout units)."""
    width: int = field(default=240, metadata=spec(IntRange(200, 360),
                                                  "how wide each box on the Flowchart is"))
    fill_color: RGB = _color((0xFF, 0xE6, 0xF0))
    border_color: RGB = _color(_TRACK)
    text_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class FlowchartKindTheme:
    """``[theme.flowchart.<kind>]``: a nine-slice image replacing a visited box's fill and
    border (none: the drawn shape)."""
    frame_image: str | None = _image()


@dataclass(frozen=True)
class FlowchartGateTheme:
    """``[theme.flowchart.gate]``: a locked route's plate. ``None``: ``flowchart.fill_color``."""
    fill_color: RGB | None = _follow_color()
    frame_image: str | None = _image()


@dataclass(frozen=True)
class FlowchartUnknownTheme:
    """``[theme.flowchart.unknown]``: ``???``. ``None``: ``button.disabled.text_color``."""
    text_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class FlowchartEdgeTheme:
    """``[theme.flowchart.edge]``: taken edges (untaken: max(2, width − 1), dashed)."""
    line_color: RGB = _color(_TRACK)
    line_width: int = _length(3, 2, 6)


@dataclass(frozen=True)
class FlowchartPathTheme:
    """``[theme.flowchart.path]``: this playthrough's edges and box borders. ``None``:
    ``button.marker.fill_color``."""
    line_color: RGB | None = _follow_color()
    line_width: int = _length(6, 4, 10)


@dataclass(frozen=True)
class FlowchartHereTheme:
    """``[theme.flowchart.here]``: the "You are here" tab. ``None``: ``save.newest.*``."""
    fill_color: RGB | None = _follow_color()
    text_color: RGB | None = _follow_color()


@dataclass(frozen=True)
class FlowchartTheme:
    """``[theme.flowchart]``: the Flowchart page (F20)."""
    fill_color: RGB = _color((0xFF, 0xFA, 0xFC))
    text_size: int = _length(24, 24, 36)
    node: FlowchartNodeTheme = _table(FlowchartNodeTheme)
    start: FlowchartKindTheme = _table(FlowchartKindTheme)
    chapter: FlowchartKindTheme = _table(FlowchartKindTheme)
    choice: FlowchartKindTheme = _table(FlowchartKindTheme)
    scene: FlowchartKindTheme = _table(FlowchartKindTheme)
    ending: FlowchartKindTheme = _table(FlowchartKindTheme)
    gate: FlowchartGateTheme = _table(FlowchartGateTheme)
    unknown: FlowchartUnknownTheme = _table(FlowchartUnknownTheme)
    edge: FlowchartEdgeTheme = _table(FlowchartEdgeTheme)
    path: FlowchartPathTheme = _table(FlowchartPathTheme)
    here: FlowchartHereTheme = _table(FlowchartHereTheme)


# --- [theme.minigame], [theme.plugin], [words.plugin] (F23 03-ui "Theme tokens", 04 §7.9, §12) --

@dataclass(frozen=True)
class MinigameHintTheme:
    """``[theme.minigame.hint]``: the hint bar under a minigame (UI-F23-03)."""
    text_size: int = field(default=24, metadata=spec(
        IntRange(24, 36), "the text size of the hint bar under a minigame (scales with the "
                          "player's text size)"))


@dataclass(frozen=True)
class MinigameTheme:
    """``[theme.minigame]``: the frame around every minigame. A ``None`` fill color follows
    ``title.fill_top_color`` / ``title.fill_bottom_color``."""
    fade_ms: int = field(default=300, metadata=spec(
        IntRange(0, 1000, note="0 = cut"),
        "how long a minigame takes to fade in and out, in milliseconds; 0 switches at once"))
    background_image: str | None = field(default=None, metadata=spec(
        GuiImageRef(), "a picture behind full-screen minigames; when not set, the color "
                       "blend below is shown"))
    fill_top_color: RGB | None = field(default=None, metadata=spec(
        _UI_COLOR, "the top color of the blend behind minigames; when not set, the title "
                   "screen's"))
    fill_bottom_color: RGB | None = field(default=None, metadata=spec(
        _UI_COLOR, "the bottom color of the blend behind minigames; when not set, the title "
                   "screen's"))
    stage_dim_opacity: float = field(default=0.30, metadata=spec(
        Opacity(high=0.8), "how much the scene is darkened behind a minigame played over it"))
    hint: MinigameHintTheme = field(default_factory=MinigameHintTheme, metadata=spec(
        Table(MinigameHintTheme), "the hint bar under a minigame"))


PLUGIN_TABLES_MAX = 256          # minigame names in [theme.plugin] or [words.plugin]
PLUGIN_TABLE_KEYS_MAX = 200      # keys in each table below a name
PLUGIN_TABLE_DEPTH = 2           # key segments below a name ("card.back_color")


@dataclass(frozen=True)
class RawValue:
    """One value of a raw plugin table as written, with its ``config.toml`` line."""
    value: str | int | float | bool
    line: int | None


@dataclass(frozen=True)
class RawPluginTable:
    """One minigame's raw table: its line and its values by dotted key below the name
    (``"card.back_color"``, ``"hint"``)."""
    line: int | None
    values: Mapping[str, RawValue]


class RawPluginTables(Validator):
    """``[theme.plugin]`` and ``[words.plugin]`` (F23 ``04`` §7.9): ``config.toml`` is read
    before plugins load, so these are stored raw (``RawPluginTable`` by minigame name) and
    checked against each plugin's declarations by ``install_minigames``. ``config._Walk``
    walks them and checks only the bounds: at most ``PLUGIN_TABLES_MAX`` names, each a
    minigame name; at most ``PLUGIN_TABLE_DEPTH`` key segments below a name; at most
    ``PLUGIN_TABLE_KEYS_MAX`` keys per table; text, number, and true/false values only."""

    expected = "a section"
    value_expected = "text, a number, or true or false"
    name_expected = ("a minigame name: lower-case letters, digits, and _, starting with a "
                     "letter, at most 40 characters")

    def check(self, value: object) -> object:
        raise ValueProblem


def _no_plugin_tables() -> Mapping[str, RawPluginTable]:
    return MappingProxyType({})


UI_THEME_AREAS =("ui", "panel", "button", "toggle", "slider", "list", "title", "menu",
                  "quick_menu", "confirm")
# F11's two areas (F11 03-ui "Theme tokens").
F11_THEME_AREAS = ("save", "notice")


@dataclass(frozen=True)
class ThemeConfig:
    """``[theme.<area>]``: one ``Table`` field per area."""
    stage: StageTheme = field(default_factory=StageTheme, metadata=spec(Table(StageTheme)))
    textbox: TextboxTheme = field(default_factory=TextboxTheme,
                                  metadata=spec(Table(TextboxTheme)))
    ui: UiAreaTheme = _table(UiAreaTheme)
    panel: PanelTheme = _table(PanelTheme)
    button: ButtonTheme = _table(ButtonTheme)
    toggle: ToggleTheme = _table(ToggleTheme)
    slider: SliderTheme = _table(SliderTheme)
    list: ListTheme = _table(ListTheme)
    title: TitleTheme = _table(TitleTheme)
    menu: MenuTheme = _table(MenuTheme)
    quick_menu: QuickMenuTheme = _table(QuickMenuTheme)
    confirm: ConfirmTheme = _table(ConfirmTheme)
    save: SaveTheme = _table(SaveTheme)
    notice: NoticeTheme = _table(NoticeTheme)
    choice: ChoiceTheme = _table(ChoiceTheme)                           # F07
    effects: EffectsTheme = _table(EffectsTheme)                        # F09
    chapter: ChapterTheme = _table(ChapterTheme)                        # F18
    nvl: NvlTheme = _table(NvlTheme)                                    # F17
    rollback: RollbackTheme = _table(RollbackTheme)                     # F14
    codex: CodexTheme = _table(CodexTheme)                              # F21
    flowchart: FlowchartTheme = _table(FlowchartTheme)                  # F20
    gallery: GalleryTheme = _table(GalleryTheme)                        # F34
    minigame: MinigameTheme = field(default_factory=MinigameTheme, metadata=spec(  # F23
        Table(MinigameTheme), "the frame around every minigame"))
    plugin: Mapping[str, RawPluginTable] = field(                       # F23 (raw, §7.9)
        default_factory=_no_plugin_tables, metadata=spec(
            RawPluginTables(), "colors and sizes for a minigame's own parts, named as that "
                               "minigame says; checked when the minigames load"))


# --- [words], [title], [quick_menu] (F10 04 §13, 03-ui "Words") ---------------------------
# A menu id is also its [words] key (F10 07 "registry"); later ids add their field here.

_WORD = Text(max_chars=WORD_MAX_CHARS)
_MESSAGE_WORD = Text(max_chars=MESSAGE_WORD_MAX_CHARS)


def _word(default: str, *, key: str | None = None, doc: str = "") -> Any:
    return field(default=default, metadata=spec(_WORD, doc, key=key))


@dataclass(frozen=True)
class WordsConfig:
    """``[words]``: one field per word key, default the English word. An empty or blank
    word is W65 at install time, and the default is kept (F10 §7.10). Look a key up with
    ``config_fields(WordsConfig)`` (``return`` is the field ``return_``)."""
    new_game: str = _word("New Game")
    load: str = _word("Load")
    settings: str = _word("Settings")
    extras: str = _word("Extras")
    help: str = _word("Help")
    quit: str = _word("Quit")
    return_: str = _word("Return", key="return")
    history: str = _word("History")
    save: str = _word("Save")
    main_menu: str = _word("Main Menu")
    yes: str = _word("Yes")
    no: str = _word("No")
    hide: str = _word("Hide")
    menu: str = _word("Menu")
    on: str = _word("On")
    off: str = _word("Off")
    loading: str = _word("Loading")
    list_empty: str = _word("Nothing here yet.")
    confirm_main_menu: str = field(
        default="Return to the title screen? Unsaved progress will be lost.",
        metadata=spec(_MESSAGE_WORD))
    confirm_quit: str = field(default="Quit the game? Unsaved progress will be lost.",
                              metadata=spec(_MESSAGE_WORD))
    # F11 (03-ui "Words", 04 §13): page labels are the word, a space, and the number
    # ("Slot 3"); failure notices are word + " " + word ("Couldn't save: the disk is full.").
    q_save: str = _word("Q.Save")
    q_load: str = _word("Q.Load")
    save_page_auto: str = _word("Auto")
    save_page_quick: str = _word("Quick")
    save_slot: str = _word("Slot")
    save_newest: str = _word("Newest")
    save_empty: str = _word("Empty slot")
    save_loading: str = _word("Loading…")
    save_no_picture: str = _word("No picture")
    save_none: str = _word("No saves yet.")
    save_damaged: str = _word("Damaged save")
    save_newer: str = _word("Made by a newer version of the game.")
    save_other_game: str = _word("This save is from a different game.")
    confirm_overwrite: str = field(default="Overwrite this save?",
                                   metadata=spec(_MESSAGE_WORD))
    confirm_delete: str = field(default="Delete this save?", metadata=spec(_MESSAGE_WORD))
    confirm_load: str = field(default="Load this save? Unsaved progress will be lost.",
                              metadata=spec(_MESSAGE_WORD))
    confirm_nearest: str = field(
        default="The story has changed since this save. Continue from the nearest point?",
        metadata=spec(_MESSAGE_WORD))
    confirm_main_menu_autosave: str = field(default="Return to the title screen?",
                                            metadata=spec(_MESSAGE_WORD))
    confirm_quit_autosave: str = field(default="Quit the game?", metadata=spec(_MESSAGE_WORD))
    notice_quick_saved: str = _word("Quick saved.")
    notice_no_quick_save: str = _word("No quick save yet.")
    notice_cant_save: str = _word("Can't save right now.")
    notice_save_failed: str = _word("Couldn't save:")
    save_reason_disk_full: str = _word("the disk is full.")
    save_reason_folder: str = _word("the save folder can't be written.")
    save_reason_other: str = _word("the file couldn't be written.")
    save_reason_slots: str = _word(
        "every slot on that page holds a save this version can't replace.")
    notice_too_large: str = _word("This save is too large.")
    notice_load_damaged: str = _word("This save is damaged and can't be loaded.")
    notice_load_no_fit: str = _word("This save no longer fits the story and can't be loaded.")
    notice_load_failed: str = _word("This save couldn't be loaded.")
    notice_delete_failed: str = _word("Couldn't delete this save.")
    # F12 (SEC-F12-12): the one notice for the session's W50–W52 (persistent data that was
    # set aside, made by a newer version, or couldn't be saved); the log has the details.
    # Drafted by the F12 builder, for vn-narrative-designer.
    notice_persistent: str = _word(
        "Progress kept across playthroughs couldn't be read or saved. The log has details.")
    # F16 (design §6.6, 07 I-13): the Settings page's group headings, row labels, the
    # Instant value, the two buttons and their questions, and the W70 notice.
    settings_display: str = _word("Display")
    settings_text: str = _word("Text")
    settings_sound: str = _word("Sound")
    settings_data: str = _word("Data")
    fullscreen: str = _word("Fullscreen")
    reduce_motion: str = _word("Reduce motion and flashing")
    text_speed: str = _word("Text speed")
    text_instant: str = _word("Instant")
    text_size: str = _word("Text size")
    auto_wait: str = _word("Auto-advance wait")
    auto_voice: str = _word("Auto-advance waits for voices")
    skip_unread: str = _word("Skip unread text")
    master_volume: str = _word("Master volume")
    music_volume: str = _word("Music volume")
    sound_volume: str = _word("Sound volume")
    voice_volume: str = _word("Voice volume")
    text_blips: str = _word("Text blips")
    voice_sustain: str = _word("Let voices finish")
    audio_unfocused: str = _word("Play audio when unfocused")
    audio_minimized: str = _word("Play audio when minimized")
    mono: str = _word("Mono audio")
    reset_settings: str = _word("Reset settings")
    confirm_reset_settings: str = field(default="Reset every setting to its default?",
                                        metadata=spec(_MESSAGE_WORD))
    delete_progress: str = _word("Delete progress")
    confirm_delete_progress: str = field(
        default="Delete everything this game remembers between playthroughs, such as read "
                "text and unlocked extras? Your saves are kept. This can't be undone.",
        metadata=spec(_MESSAGE_WORD))
    notice_settings_default: str = _word(
        "Your settings couldn't be read, so the defaults are used.")
    # F15 (UI-F15-01): the quick menu's Skip and Auto, also the corner indicator's text.
    # Drafted by the F15 builder, for vn-narrative-designer.
    skip: str = _word("Skip")
    auto: str = _word("Auto")
    # F14 (UI-F14-01, 04 §13): the quick menu's Back. Drafted by the F14 builder.
    back: str = _word("Back")
    # F21 (01 §6 "Words"): the game-menu and title entry (also the page heading), the two
    # default categories, the two notice words ("New tip: Paper Lanterns"), a locked tip's
    # row, and the empty page. The pick button's word comes from its host (F25). Drafted by
    # the F21 designer, for vn-narrative-designer.
    codex: str = _word("Codex")
    codex_tips: str = _word("Tips")
    codex_items: str = _word("Items")
    codex_new_tip: str = _word("New tip")
    codex_new_item: str = _word("New item")
    codex_locked: str = _word("???")
    codex_empty: str = _word("Nothing here yet.")
    # F20 (01 §6, 03-ui "Words", 04 §13): the game-menu and title entry (also the page
    # heading), the box and panel words, the reasons, and the jump questions. Drafted by the
    # F20 designers, for vn-narrative-designer.
    flowchart: str = _word("Flowchart", doc="the menu button and heading of the Flowchart page")
    flowchart_jump: str = _word("Jump", doc="the Jump button in the Flowchart's side panel")
    flowchart_start: str = _word("Start", doc="the Flowchart's start box")
    flowchart_chapter: str = _word("Chapter", doc="what a chapter box is called in the side "
                                                  "panel")
    flowchart_choice: str = _word("Choice", doc="a choice box with no title or question")
    flowchart_scene: str = _word("Scene", doc="what a scene box is called in the side panel")
    flowchart_ending: str = _word("Ending", doc="what an ending box is called in the side "
                                                "panel")
    flowchart_route: str = _word("Locked route", doc="a locked route's gate, in the side panel")
    flowchart_unknown: str = _word("???", doc="a box, choice, or ending not seen yet")
    flowchart_var: str = _word("…", doc="what stands in for a variable in a choice or "
                                        "question on the Flowchart")
    flowchart_here: str = _word("You are here", doc="the tab over the box reached last")
    flowchart_changed: str = _word("This part of the story has changed.",
                                   doc="why a box can't be jumped to: the story changed")
    flowchart_no_state: str = _word("Reach this point again to jump here.",
                                    doc="why a box can't be jumped to: nothing was kept "
                                        "from it")
    flowchart_no_jump: str = _word("You can't jump to this point.",
                                   doc="why a box marked no jump has no Jump button")
    flowchart_confirm: str = field(
        default="Jump to this point? Unsaved progress will be lost.", metadata=spec(
            _MESSAGE_WORD, "the question before a jump"))
    flowchart_confirm_autosave: str = field(default="Jump to this point?", metadata=spec(
        _MESSAGE_WORD, "the question before a jump, when auto-save is on"))
    flowchart_endings: str = _word("Endings", doc="the Flowchart's count of endings")
    flowchart_nodes: str = _word("Nodes", doc="the Flowchart's count of boxes")
    # F33 (SPEC §3): the content warning's heading and its Continue button; its Quit button
    # is ``quit``. Drafted by the F33 builder, for vn-narrative-designer.
    warning_heading: str = _word(
        "Content warning", doc="the heading of the content warning shown before the title")
    warning_continue: str = _word(
        "I understand", doc="the content warning's button that goes on to the title")
    # F23 (03-ui "Words", UI-F23-12): the game menu's Skip Game, shown only while a skippable
    # minigame runs, and its question. Drafted by the F23 designer, for vn-narrative-designer.
    skip_minigame: str = _word(
        "Skip Game", doc="the game menu's button that skips a minigame you let players skip")
    confirm_skip_minigame: str = field(
        default="Skip this game and go on with the story?", metadata=spec(
            _MESSAGE_WORD, "the question Skip Game asks before it skips the minigame"))
    # F30 (01 §6.2, §6.3): the fake crash's default message, hint, and optional label; the
    # Settings rows; the first-launch question and its buttons. The hint and label are one
    # short line (SEC-F30-10 (b)). Drafted by the F30 designer, for vn-narrative-designer.
    fake_crash_message: str = field(default="Something went wrong.",
                                    metadata=spec(_MESSAGE_WORD))
    fake_crash_hint: str = field(default="Press Esc or Enter to continue", metadata=spec(
        OneLine(120, why="because the fake crash screen always shows it")))
    fake_crash_label: str = field(default="This is part of the story.", metadata=spec(
        OneLine(120, why="because the fake crash screen shows it when the player turns "
                         "the label on")))
    settings_username: str = _word("Use my computer's user name")
    settings_crash_label: str = _word("Label fake error screens")
    ask_username: str = field(
        default="This game can show your computer's user name in the story. It is never "
                "saved or sent anywhere. Allow it?",
        metadata=spec(_MESSAGE_WORD))
    ask_username_yes: str = _word("Allow")
    ask_username_no: str = _word("Don't allow")
    # F32 (04 §10, PR-F32-10): the Save or Load page's message while ``ui saving off`` or
    # ``ui loading off`` gives no reason of its own.
    saving_off: str = _word("Saving is turned off here.")
    loading_off: str = _word("Loading is turned off here.")
    # F34 (01 §6.3 "Words"): the Extras screen's Gallery button and page heading, and a
    # picture tile not seen yet. ``extras`` (the title button) is F10's.
    gallery: str = _word("Gallery")
    gallery_locked: str = _word("???")
    # F35 (SPEC.md §5.1): the Extras screen's Music Room button and page heading, its controls,
    # a track not open yet, and the line shown before a track is picked.
    music_room: str = _word("Music Room")
    music_play: str = _word("Play")
    music_pause: str = _word("Pause")
    music_previous: str = _word("Previous")
    music_next: str = _word("Next")
    music_play_all: str = _word("Play all")
    music_repeat_one: str = _word("Repeat track")
    music_locked: str = _word("???")
    music_pick: str = _word("Pick a track to play.")
    # F23 (04 §7.9): a minigame's own words, raw until the minigames load; not a word key
    # (``word_fields`` leaves it out).
    plugin: Mapping[str, RawPluginTable] = field(
        default_factory=_no_plugin_tables, metadata=spec(
            RawPluginTables(), "a minigame's own words, named as that minigame says; its "
                               "title word renames the minigame"))


@dataclass(frozen=True)
class TitleConfig:
    """``[title]``. ``entries`` ``None``: F10's default order; names that no feature
    registered for the title are W66 at install time."""
    enabled: bool = field(default=True, metadata=spec(Bool(),
        "show the title screen (when off, the story starts at once)"))   # False: no title screen
    show_version: bool = field(default=True, metadata=spec(Bool(),
        "show the game's version on the title screen"))
    entries: tuple[str, ...] | None = field(default=None, metadata=spec(NameList(),
        "which buttons the title screen shows, in order, by name"))


@dataclass(frozen=True)
class QuickMenuConfig:
    """``[quick_menu]``. ``entries`` as ``[title] entries``."""
    enabled: bool = field(default=True, metadata=spec(Bool(),
        "show the quick menu under the text box"))
    entries: tuple[str, ...] | None = field(default=None, metadata=spec(NameList(),
        "which buttons the quick menu shows, in order, by name"))


@dataclass(frozen=True)
class ChoiceConfig:
    """``[choice]`` (F07 §13, SR-F07-09). ``show_locked``: a choice whose condition is false
    is shown locked (never pickable) instead of hidden."""
    show_locked: bool = field(default=False, metadata=spec(Bool(),
        "show a choice whose condition isn't met as locked, instead of hiding it"))


class OffOrRange(Validator):
    """``0`` (off) or a whole number in ``IntRange(lo, hi)`` (F11 ``[saves]
    autosave_interval``, ``07`` I-7)."""

    def __init__(self, lo: int, hi: int) -> None:
        self.range = IntRange(lo, hi)
        self.expected = f"a whole number: 0 (off) or {lo}–{hi}"

    def check(self, value: object) -> object:
        if type(value) is int and value == 0:
            return value
        try:
            return self.range.check(value)
        except ValueProblem:
            raise ValueProblem from None


@dataclass(frozen=True)
class SavesConfig:
    """``[saves]`` (F11 ``04`` §13). ``pages``: numbered Save/Load pages of 6 slots;
    ``autosave_interval``: seconds of play between timer auto-saves (0: off)."""
    pages: int = field(default=10, metadata=spec(IntRange(1, 100),
        "how many numbered pages the Save and Load screens have, 6 slots each"))
    autosave_interval: int = field(default=300, metadata=spec(OffOrRange(60, 3600),
        "how many seconds of play pass between auto-saves; 0 turns timed auto-saves off"))
    autosave_choices: bool = field(default=True, metadata=spec(Bool(),
        "auto-save before every menu choice"))
    autosave_quit: bool = field(default=True, metadata=spec(Bool(),
        "auto-save when the player quits"))
    confirm_quick_load: bool = field(default=True, metadata=spec(Bool(),
        "ask the player before a quick load"))


_VOLUME = IntRange(*AUDIO_VOLUME_RANGE)
_FADE = Seconds(*AUDIO_FADE_RANGE)
_NO_LOOP_STARTS: Mapping[str, float] = MappingProxyType({})


@dataclass(frozen=True)
class AudioConfig:
    """``[audio]`` (F08 §13, 02 §3.6). Volumes are only defaults; F16's settings win
    (PR-F08-08). The mixer rate and buffer are constants, not keys."""
    master_volume: int = field(default=100, metadata=spec(_VOLUME,
        "the starting overall volume (a player's own choice in Settings wins)"))
    music_volume: int = field(default=70, metadata=spec(_VOLUME, "the starting music volume"))
    sound_volume: int = field(default=80, metadata=spec(_VOLUME,
        "the starting sound effect volume"))
    voice_volume: int = field(default=100, metadata=spec(_VOLUME, "the starting voice volume"))
    music_fadein: float = field(default=0.0, metadata=spec(_FADE,
        "how many seconds music fades in, when its Play music line doesn't say"))
    music_fadeout: float = field(default=0.5, metadata=spec(_FADE,
        "how many seconds music fades out when it stops or changes"))
    sound_fadein: float = field(default=0.0, metadata=spec(_FADE,
        "how many seconds a sound fades in, when its Play sound line doesn't say"))
    sound_fadeout: float = field(default=0.0, metadata=spec(_FADE,
        "how many seconds a sound fades out when it stops"))
    restore_fadeout: float = field(default=0.5, metadata=spec(_FADE,
        "how many seconds the music fades out when a save is loaded"))
    restore_fadein: float = field(default=1.0, metadata=spec(_FADE,
        "how many seconds the save's music fades in after it is loaded"))
    play_unfocused: bool = field(default=True, metadata=spec(Bool(),
        "keep playing audio while the window is in the background"))
    play_minimized: bool = field(default=True, metadata=spec(Bool(),
        "keep playing audio while the window is minimized"))
    # File (inside audio/, as written) -> loop start in seconds (SR-F08-23, 07 I-6).
    loop_start: Mapping[str, float] = field(
        default=_NO_LOOP_STARTS,
        metadata=spec(EntryMap(AudioFileKey(), Seconds(*AUDIO_LOOP_START_RANGE),
                               AUDIO_LOOP_STARTS_MAX, label=quoted_key),
        "where each music file loops back to, in seconds from its start"))


def _effect_seconds(default: float, lo: float, hi: float, doc: str = "") -> Any:
    return field(default=default, metadata=spec(
        Seconds(lo, hi, expected=f"a number from {lo} to {hi}"), doc))


@dataclass(frozen=True)
class EffectsConfig:
    """``[effects]`` (F09 ``04`` §12, PR-F09-07): the lengths a script leaves out, in
    seconds, the default shake size, and ``reduce``, the one config source of the "reduce
    motion and flashing" switch (07 I-6; F16's player setting is ORed with it). The runtime
    never reads these: a ``None`` in a command is resolved by the presentation, so headless
    output never depends on them. F28 (04 §10, 07 I-10): ``glitch`` is the default length of
    an ``effect`` burst and of ``with glitch`` (F09's rule: a key named after a built-in
    transition is its default length); ``glitch_size`` the default glitch size."""
    dissolve: float = _effect_seconds(0.5, *TRANSITION_SECONDS_RANGE,
        doc="how many seconds a dissolve lasts, when its line in the story doesn't say")
    fade: float = _effect_seconds(1.0, *TRANSITION_SECONDS_RANGE,
        doc="how many seconds a fade lasts, when its line in the story doesn't say")
    shake: float = _effect_seconds(0.5, *SHAKE_SECONDS_RANGE,
        doc="how many seconds a shake lasts, when its line in the story doesn't say")
    shake_size: str = field(default="medium", metadata=spec(Choice(*SHAKE_SIZES),
        "how far a shake moves, when its line in the story doesn't say"))
    flash: float = _effect_seconds(0.3, *FLASH_SECONDS_RANGE,
        doc="how many seconds a flash lasts, when its line in the story doesn't say")
    reduce: bool = field(default=False, metadata=spec(Bool(),
        "reduce motion and flashing for every player"))
    glitch: float = _effect_seconds(0.5, *GLITCH_SECONDS_RANGE,
        doc="how many seconds a glitch lasts, when its line in the story doesn't say")  # F28
    glitch_size: str = field(default="medium", metadata=spec(Choice(*GLITCH_SIZES),
        "how strong a glitch is, when its line in the story doesn't say"))


@dataclass(frozen=True)
class SkipConfig:
    """``[skip]`` (F15 ``SPEC.md`` §5): ``all`` true skips unseen lines too (F16's setting
    wins). Presentation only: the runtime never reads it."""
    all: bool = field(default=False, metadata=spec(Bool(),
        "skipping also skips text the player hasn't read"))


@dataclass(frozen=True)
class AutoConfig:
    """``[auto]`` (F15 §5, ``07`` I-5): the auto-advance wait after a segment is fully shown
    is ``delay + per_char × graphemes`` seconds (× F16's scale); ``wait_for_voice`` also waits
    for the line's voice (F16's setting wins)."""
    delay: float = _effect_seconds(1.0, 0, 10,
        doc="how many seconds auto-advance waits after a line, plus the time per character")
    per_char: float = _effect_seconds(0.04, 0, 0.5,
        doc="extra seconds auto-advance waits for each character in the line")
    wait_for_voice: bool = field(default=True, metadata=spec(Bool(),
        "auto-advance also waits for the line's voice to end"))


@dataclass(frozen=True)
class ChapterConfig:
    """``[chapter]`` (F18 PR-F18-05): ``autosave`` asks for an Auto save at the first line
    after every ``chapter``; ``name_saves`` names saves after their chapter (``heading:
    title``). Presentation only: the runtime never reads it."""
    autosave: bool = field(default=True, metadata=spec(Bool(),
        "auto-save at the first line of every chapter"))
    name_saves: bool = field(default=True, metadata=spec(Bool(), "name saves after their chapter"))


@dataclass(frozen=True)
class RollbackConfig:
    """``[rollback]`` (F14 ``04`` §13, I-15): ``steps`` is how many steps back the player can
    go (0 turns rollback off for the game: no Back entry, inputs do nothing; each kept step
    holds one checkpoint, about 0.2 MiB for a game with 1,000 variables); ``marker`` shows
    the rewind tag while rolled back (UI-F14-09). Read by the app, never by the runtime
    (``Interpreter(rollback_steps=)``)."""
    steps: int = field(default=100, metadata=spec(IntRange(0, 1000),
        "how many steps back through the story the player can go; 0 turns going back off"))
    marker: bool = field(default=True, metadata=spec(Bool(),
        "show the rewind marker while the player has gone back"))


@dataclass(frozen=True)
class CodexConfig:
    """``[codex]`` (F21 01 §5.4): ``notify`` shows a notice for each new tip or item;
    ``show_locked`` lists locked tips as disabled ``???`` rows. Presentation only: the
    runtime never reads it (a headless run releases the same ``CodexAdded``)."""
    notify: bool = field(default=True, metadata=spec(Bool(),
        "show a notice for each new tip or item"))
    show_locked: bool = field(default=False, metadata=spec(Bool(),
        "show locked tips as ??? rows instead of hiding them"))


@dataclass(frozen=True)
class GalleryConfig:
    """``[gallery]`` (F34 01 §5.3): ``show_locked`` shows gallery pictures not unlocked yet
    as ``???`` tiles (false: left out, order kept). Presentation only."""
    show_locked: bool = field(default=True, metadata=spec(Bool(),
        "show pictures the player hasn't seen yet as ??? squares instead of leaving them "
        "out"))


@dataclass(frozen=True)
class FlowchartConfig:
    """``[flowchart]`` (F20 ``02`` §3.6, ``04`` §13; SR-F20-13): ``enabled`` (the Flowchart
    page; marks are still checked when off), ``menus`` (which menus are choice nodes:
    ``"branching"``, ``"all"``, or ``"marked"``), ``unvisited`` (``"mystery"`` shows ``???``
    boxes, ``"hidden"`` hides them), ``jump`` (false: a map only, no Jump). The loader builds
    F20 s2's ``FlowOptions`` from it."""
    enabled: bool = field(default=True, metadata=spec(Bool(),
        "show the Flowchart page (story map marks are still checked when it's off)"))
    menus: str = field(default="branching", metadata=spec(Choice("branching", "all", "marked"),
        "which choice menus get a box: branching (choices that lead different ways), all, "
        "or marked (only menus you mark)"))
    unvisited: str = field(default="mystery", metadata=spec(Choice("mystery", "hidden"),
        "scenes the player hasn't seen: mystery shows them as ??? boxes, hidden leaves "
        "them out"))
    jump: bool = field(default=True, metadata=spec(Bool(),
        "let the player jump to a scene they've seen (when off, the Flowchart is only a "
        "map)"))


# --- [content_warning] (F33 SPEC §3; 07 I-4, I-8) -------------------------------------------

CONTENT_WARNING_MAX_CHARS = 2000
WARNING_SHOWS = ("never", "once", "always")


class WarningText(Validator):
    """``[content_warning] text`` (SR-F33-01): at most 2,000 code points; ``\\n`` is the
    only control character allowed (tomllib already turns a CRLF file's line ends into
    ``\\n``). Empty passes here: "set when show is not never" is ``config.py``'s cross-key
    check (07 I-4)."""

    expected = (f"text of at most {CONTENT_WARNING_MAX_CHARS} characters with no control "
                "characters other than line breaks")

    def check(self, value: object) -> object:
        if (type(value) is str and len(value) <= CONTENT_WARNING_MAX_CHARS
                and not any(c != "\n" and unicodedata.category(c) == "Cc" for c in value)):
            return value
        raise ValueProblem


def _warning_show() -> Choice:
    show = Choice(*WARNING_SHOWS)
    show.expected = '"never", "once", or "always"'          # SR-F33-03's phrase
    return show


@dataclass(frozen=True)
class ContentWarningConfig:
    """``[content_warning]`` (F33 PR-F33-01): a full-screen warning after the story loads and
    before the title (or the game with no title). ``show`` ``"once"`` shows it until the
    player continues (F16's ``warning_seen`` = ``version``); ``"always"`` every launch.
    ``text`` must be set unless ``show`` is ``"never"`` (``config.py``)."""
    show: str = field(default="never", metadata=spec(
        _warning_show(), "when the content warning shows before the title: never, once "
                         "(until the player continues), or always (every launch)"))
    text: str = field(default="", metadata=spec(
        WarningText(), "the warning's text, with no formatting; a blank line starts a new "
                       "paragraph"))
    version: int = field(default=1, metadata=spec(
        IntRange(1, 1000), "raise this number after changing the text, so players see a "
                           "once warning again"))
    min_seconds: float = field(default=2.0, metadata=spec(
        Seconds(0, 10), 'how long the "I understand" button waits before it can be pressed; '
                        "0 lets it be pressed at once"))


@dataclass(frozen=True)
class MetaConfig:
    """``[meta]`` (F30 ``04`` §9): the author's offer to show the player's computer user name
    with ``{username}`` (the player still has to allow it), and the word shown otherwise."""
    username: bool = field(default=False, metadata=spec(Bool(),
        "when on, the game offers to show each player's computer user name where your "
        "story writes {username}; each player is asked first"))
    username_fallback: str = field(default="friend", metadata=spec(PlainText(USERNAME_MAX),
        "what {username} shows when the name is off, not allowed, or can't be read"))


@dataclass(frozen=True)
class AnimationConfig:
    """``[animation]`` (F38 ``SPEC.md`` §3): blinking and talking sprites, from frames named
    after their looks (``script/spriteframes.py``). Presentation only: the runtime never
    reads it; ``render/spriteanim.py``'s ``AnimSettings`` is built from it. Reduce motion
    (``[effects] reduce`` or F16's setting) holds sprites still whatever ``enabled`` says."""
    enabled: bool = field(default=True, metadata=spec(Bool(),
        "characters on the stage blink and move their mouths, when their pictures have "
        "blink and talking frames"))
    blink_every: float = _effect_seconds(4.0, 1, 30,
        doc="about how many seconds pass between blinks (each gap is random, from half to "
            "one and a half times this)")
    blink_frame: float = _effect_seconds(0.08, 0.02, 0.5,
        doc="how many seconds each blink frame shows")
    talk_frame: float = _effect_seconds(0.1, 0.03, 0.5,
        doc="how many seconds each talking frame shows")


# --- [style.<name>] and [playthrough.N] (F32 04 §3, §6.1, §10) -------------------------------
# Sparse layers over [theme] and [words]: a table holds only the keys it sets, each checked by
# the [theme]/[words]/[title] key's own validator (config.py ``_Walk.looks``). A style changes
# only the in-game areas and a playthrough look only the title, so the two layers never set
# the same token. F30's words (and F23's raw ``plugin`` table) come only from [words].

STYLE_AREAS: tuple[str, ...] = ("textbox", "choice", "nvl", "quick_menu")
PLAYTHROUGH_AREAS: tuple[str, ...] = ("title",)
LOOK_WORDS_REFUSED: frozenset[str] = frozenset((
    "fake_crash_message", "fake_crash_hint", "fake_crash_label", "settings_username",
    "settings_crash_label", "ask_username", "ask_username_yes", "ask_username_no"))


@dataclass(frozen=True, slots=True)
class LookTable:
    """One valid ``[style.<name>]`` or ``[playthrough.N]``: ``tokens`` maps a dotted theme
    path (``"textbox.fill_color"``, ``"title.logo.text_size"``) to its checked value, and
    ``words`` a word key to its text, set keys only (read-only mappings);
    ``title_entries`` is a playthrough table's ``title_entries``; ``line`` the table's line."""
    tokens: Mapping[str, object]
    words: Mapping[str, str]
    title_entries: tuple[str, ...] | None = None
    line: int | None = None


@dataclass(frozen=True)
class StyleTableKeys:
    """The keys of one ``[style.<name>]`` table: what ``_Walk.looks`` reads and Studio's
    config Help describes. ``Config.style`` holds ``LookTable``s, not this class."""
    theme: ThemeConfig = field(default_factory=ThemeConfig, metadata=spec(Table(ThemeConfig),
        "how the style changes the text box, choices, full-screen text and quick menu; "
        "anything it doesn't set keeps the main look"))
    words: WordsConfig = field(default_factory=WordsConfig, metadata=spec(Table(WordsConfig),
        "words shown while the style is on; any it doesn't set keep the main words"))


@dataclass(frozen=True)
class PlaythroughTableKeys:
    """The keys of one ``[playthrough.N]`` table (as ``StyleTableKeys``)."""
    theme: ThemeConfig = field(default_factory=ThemeConfig, metadata=spec(Table(ThemeConfig),
        "the title screen's look from this playthrough on; anything it doesn't set keeps "
        "the main title look"))
    words: WordsConfig = field(default_factory=WordsConfig, metadata=spec(Table(WordsConfig),
        "words shown from this playthrough on; any it doesn't set keep the main words"))
    title_entries: tuple[str, ...] | None = field(default=None, metadata=spec(NameList(),
        "which buttons the title screen shows from this playthrough on, in order, by name; "
        "when not set, the main title buttons"))


# config.toml section → the keys of each of its named tables (``_validate`` routes these to
# ``_Walk.looks``; they are not in ``SECTIONS``, whose values are one dataclass each).
LOOK_SECTIONS: Mapping[str, type] = MappingProxyType({
    "style": StyleTableKeys, "playthrough": PlaythroughTableKeys})


def _no_looks() -> Mapping[Any, LookTable]:
    return MappingProxyType({})


@dataclass(frozen=True)
class Config:
    game: GameConfig = field(default_factory=GameConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    stage: StageConfig = field(default_factory=StageConfig)
    textbox: TextboxConfig = field(default_factory=TextboxConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    words: WordsConfig = field(default_factory=WordsConfig)
    title: TitleConfig = field(default_factory=TitleConfig)
    quick_menu: QuickMenuConfig = field(default_factory=QuickMenuConfig)
    choice: ChoiceConfig = field(default_factory=ChoiceConfig)          # F07
    saves: SavesConfig = field(default_factory=SavesConfig)             # F11
    effects: EffectsConfig = field(default_factory=EffectsConfig)       # F09
    skip: SkipConfig = field(default_factory=SkipConfig)                # F15
    auto: AutoConfig = field(default_factory=AutoConfig)                # F15
    chapter: ChapterConfig = field(default_factory=ChapterConfig)       # F18
    rollback: RollbackConfig = field(default_factory=RollbackConfig)    # F14
    codex: CodexConfig = field(default_factory=CodexConfig)             # F21
    flowchart: FlowchartConfig = field(default_factory=FlowchartConfig) # F20
    gallery: GalleryConfig = field(default_factory=GalleryConfig)       # F34
    content_warning: ContentWarningConfig = field(                      # F33
        default_factory=ContentWarningConfig)
    meta: MetaConfig = field(default_factory=MetaConfig)                # F30
    animation: AnimationConfig = field(default_factory=AnimationConfig) # F38
    # F32: the valid [style.<name>] tables by name and [playthrough.N] tables by N.
    style: Mapping[str, LookTable] = field(default_factory=_no_looks)
    playthrough: Mapping[int, LookTable] = field(default_factory=_no_looks)


@dataclass(frozen=True)
class ConfigResult:
    config: Config                    # valid values; defaults for anything invalid or missing
    warnings: list[str]               # unknown keys/sections, missing file (each logged as one record)
    errors: list[ConfigError]         # non-empty → startup goes to the error screen
    loaded: bool                      # True only if the file was read, parsed, and had no errors


# Section name in config.toml → its dataclass. The keys are also Config's field names.
SECTIONS: dict[str, type] = {
    "game": GameConfig,
    "window": WindowConfig,
    "engine": EngineConfig,
    "stage": StageConfig,
    "textbox": TextboxConfig,
    "theme": ThemeConfig,
    "audio": AudioConfig,
    "words": WordsConfig,
    "title": TitleConfig,
    "quick_menu": QuickMenuConfig,
    "choice": ChoiceConfig,
    "saves": SavesConfig,
    "effects": EffectsConfig,
    "skip": SkipConfig,
    "auto": AutoConfig,
    "chapter": ChapterConfig,
    "rollback": RollbackConfig,
    "codex": CodexConfig,
    "flowchart": FlowchartConfig,
    "gallery": GalleryConfig,
    "content_warning": ContentWarningConfig,
    "meta": MetaConfig,
    "animation": AnimationConfig,
}


# --- Key descriptions (F45 Studio's config Help, 2026-11-02) --------------------------------
# A key's description is its ``spec(…, doc=…)``. Theme tokens and words repeat one meaning in
# many tables, so a key with no ``doc`` is described here instead: by its dotted path
# (``"theme.title.music"``), else by its name (theme tokens, words). ``key_doc`` reads them;
# tests/test_config_docs.py fails for a key with no description and for a row no key uses.

SECTION_DOCS: Mapping[str, str] = MappingProxyType({
    "game": "the game's name, version, and save folder name",
    "window": "the game window: size, fullscreen, icon, and how art is stretched",
    "engine": "how often the screen is drawn, picture memory, and the log file",
    "stage": "the stage: the height your art is drawn for, and named spots",
    "textbox": "how the text box types out text",
    "theme": "the look: colors, fonts, and sizes for each part of the screen",
    "audio": "starting volumes, fades, and where music loops",
    "words": "every word the game shows, for renaming or translating",
    "title": "the title screen and its buttons",
    "quick_menu": "the quick menu under the text box and its buttons",
    "choice": "how menu choices are shown",
    "saves": "save pages and auto-saves",
    "effects": "how long and how strong screen effects are when the story doesn't say",
    "skip": "what skipping skips",
    "auto": "how long auto-advance waits",
    "chapter": "chapter auto-saves and save names",
    "rollback": "going back through the story",
    "codex": "the codex of tips and items",
    "flowchart": "the Flowchart page",
    "gallery": "the gallery of special pictures players have seen, on the Extras screen",
    "content_warning": "a content warning shown before the title",
    "meta": "showing the player's computer user name in the story",
    "animation": "characters blinking and moving their mouths while they talk",
    "style": "a named look the story can switch to while it plays",
    "playthrough": "a different title screen for players from a given playthrough on",
})

THEME_DOCS: Mapping[str, str] = MappingProxyType({
    # areas and nested tables
    "stage": "the stage behind the art", "textbox": "the text box",
    "ui": "fonts, fades, and sounds shared by every menu page",
    "panel": "panels: the side bar, pages, and pop-up boxes",
    "button": "menu buttons and grid squares",
    "toggle": "on/off switches", "slider": "sliders",
    "list": "scrolling panes of rows, like History",
    "title": "the title screen", "theme.chapter.title": "the chapter's title text",
    "menu": "the game menu",
    "quick_menu": "the quick menu under the text box", "confirm": "yes/no questions",
    "save": "the Save and Load pages", "notice": "short notices that fade away",
    "choice": "menu choices", "effects": "screen effect colors",
    "chapter": "the chapter title card", "nvl": "the full-screen text page",
    "rollback": "the cue that the player can't go back any further",
    "codex": "the codex page",
    "flowchart": "the Flowchart page", "theme.flowchart.node": "a visited box",
    "theme.flowchart.start": "the start box", "theme.flowchart.chapter": "chapter boxes",
    "theme.flowchart.choice": "choice boxes", "theme.flowchart.scene": "scene boxes",
    "theme.flowchart.ending": "ending boxes", "theme.flowchart.gate": "a locked route's gate",
    "theme.flowchart.unknown": "??? on unseen boxes and choices",
    "theme.flowchart.edge": "the lines between boxes",
    "theme.flowchart.path": "this playthrough's lines and boxes",
    "theme.flowchart.here": 'the "You are here" tab',
    "gallery": "the gallery page on the Extras screen",
    "theme.gallery.caption": "the picture titles under the squares",
    "theme.gallery.viewer": "a gallery picture shown on the whole screen",
    "line_color": "the line color", "line_width": "the line width",
    "name_tab": "the speaker's name tab", "indicator": "the click-to-continue mark",
    "heading": "headings",
    "focused": "the look when the mouse is over it or the keyboard is on it",
    "pressed": "the look while pressed", "selected": "the look when selected",
    "disabled": "the look when it can't be used", "marker": "the marker beside it",
    "on": "the look when switched on", "empty": 'the "nothing here" text',
    "logo": "the game's logo", "version": "the version text", "loading": "the loading text",
    "badge": "small tags on a save", "newest": 'the "Newest" tag',
    "placeholder": "empty, loading, and damaged slots", "name": "the speaker's name",
    "mark": "the limit mark", "new": "a new entry's mark", "locked": "a locked entry",
    # colors and opacity
    "fill_color": "the fill color",
    "fill_opacity": "how solid the fill is (0 is see-through, 1 is solid)",
    "fill_top_color": "the fill's top color, blending into the bottom color",
    "fill_bottom_color": "the fill's bottom color, blending from the top color",
    "text_color": "the text color", "border_color": "the border color",
    "divider_color": "the color of divider lines", "track_color": "the track color",
    "knob_color": "the knob color", "thumb_color": "the color of the handle you drag",
    "thumb_border_color": "the border color of the handle you drag",
    "scrollbar_color": "the scrollbar color",
    "scrollbar_track_color": "the scrollbar track color", "glyph_color": "the symbol's color",
    "dim_color": "the color that dims the game behind",
    "dim_opacity": "how much the game behind is dimmed",
    "empty_color": "the color shown where there is no background",
    "flash_color": "the color a flash shows", "fade_color": "the color a fade goes through",
    # fonts and sizes
    "text_font": "the text font, a .ttf or .otf file", "bold_font": "the bold font",
    "italic_font": "the italic font", "bold_italic_font": "the bold italic font",
    "text_size": "the text size", "width": "the width", "height": "the height",
    "min_width": "the smallest width", "max_width": "the largest width",
    "button_width": "the buttons' smallest width", "row_height": "each row's height",
    "image_height": "the picture height; 0 hides pictures",
    "border_width": "the border width; 0 means no border",
    "corner_radius": "how round the corners are",
    "underline_width": "the underline's thickness",
    "bump_height": "how far it bumps; 0 means no bump",
    # gaps and padding
    "gap": "the space between items", "line_gap": "the space between lines",
    "left_gap": "the space from the left edge", "top_gap": "the space from the top",
    "bottom_gap": "the space from the bottom of the screen",
    "side_padding": "the space inside, left and right",
    "top_padding": "the space inside, at the top",
    "bottom_padding": "the space inside, at the bottom",
    # images
    "frame_image": "a frame picture from gui/ that stretches to fit and keeps its corners "
                   "(when not set, a plain box is drawn)",
    "frame_slice_width": "the size of the frame picture's corners, which don't stretch",
    "background_image": "the background picture",
    "line_image": "the picture shown at the end of a line",
    "page_image": "the picture shown at the end of a page",
    "logo_image": "the logo picture", "image": "a picture from gui/",
    "no_picture_image": "the picture for a save with no screenshot",
    # timing
    "fade_ms": "how many milliseconds it takes to fade in or out",
    "fade_in_ms": "how many milliseconds it takes to fade in",
    "load_fade_ms": "how many milliseconds the game takes to fade in after a load",
    "duration_ms": "how many milliseconds it stays on screen",
    # sounds
    "focus_sound": "the sound when the mouse or keyboard moves onto it",
    "activate_sound": "the sound when it is clicked or pressed",
    "back_sound": "the sound when going back",
    "pick_sound": "the sound when a choice is picked", "limit_sound": "the sound at the limit",
    "sound": "the sound it plays", "music": "the music file",
    "theme.title.music": "the title screen's music, a file in audio/",
})

WORD_DOCS: Mapping[str, str] = MappingProxyType({
    "new_game": "the title screen's button that starts a new game",
    "load": "the menu button and page for loading a save",
    "settings": "the menu button and page for the player's settings",
    "extras": "the Extras menu button", "help": "the Help menu button",
    "quit": "the menu button that quits the game",
    "return": "the button that goes back to the game",
    "history": "the menu button and page of past lines",
    "save": "the menu button and page for saving",
    "main_menu": "the menu button that goes to the title screen",
    "yes": "the yes button on questions", "no": "the no button on questions",
    "hide": "the quick menu's button that hides the text box",
    "menu": "the quick menu's button that opens the game menu",
    "on": "how an on/off switch reads when on", "off": "how an on/off switch reads when off",
    "loading": "shown while something loads",
    "list_empty": "shown on a page with nothing in it yet",
    "confirm_main_menu": "the question before going to the title screen",
    "confirm_quit": "the question before quitting",
    "q_save": "the quick menu's Quick Save button",
    "q_load": "the quick menu's Quick Load button",
    "save_page_auto": "the Save and Load page of auto-saves",
    "save_page_quick": "the Save and Load page of quick saves",
    "save_slot": "the word before a save slot's number",
    "save_newest": "the tag on the newest save",
    "save_empty": "an empty save slot", "save_loading": "a save slot still loading",
    "save_no_picture": "a save with no screenshot", "save_none": "a page with no saves",
    "save_damaged": "a damaged save", "save_newer": "a save made by a newer version",
    "save_other_game": "a save from another game",
    "confirm_overwrite": "the question before saving over a save",
    "confirm_delete": "the question before deleting a save",
    "confirm_load": "the question before loading",
    "confirm_nearest": "the question when the story changed since the save was made",
    "confirm_main_menu_autosave": "the question before the title screen, when auto-save is on",
    "confirm_quit_autosave": "the question before quitting, when auto-save is on",
    "notice_quick_saved": "the notice after a quick save",
    "notice_no_quick_save": "the notice when there is no quick save yet",
    "notice_cant_save": "the notice when saving isn't allowed right now",
    "notice_save_failed": "the start of the notice when saving fails",
    "save_reason_disk_full": "why saving failed: the disk is full",
    "save_reason_folder": "why saving failed: the save folder",
    "save_reason_other": "why saving failed: anything else",
    "save_reason_slots": "why saving failed: no slot it may save over",
    "notice_too_large": "the notice when a save is too large",
    "notice_load_damaged": "the notice when a save is damaged",
    "notice_load_no_fit": "the notice when a save no longer fits the story",
    "notice_load_failed": "the notice when loading fails",
    "notice_delete_failed": "the notice when deleting a save fails",
    "notice_persistent": "the notice when progress kept between playthroughs can't be read "
                         "or saved",
    "settings_display": "a group heading on the player's Settings page",
    "settings_text": "a group heading on the player's Settings page",
    "settings_sound": "a group heading on the player's Settings page",
    "settings_data": "a group heading on the player's Settings page",
    "fullscreen": "a row on the player's Settings page",
    "reduce_motion": "a row on the player's Settings page",
    "text_speed": "a row on the player's Settings page",
    "text_instant": "what the fastest text speed is called",
    "text_size": "a row on the player's Settings page",
    "auto_wait": "a row on the player's Settings page",
    "auto_voice": "a row on the player's Settings page",
    "skip_unread": "a row on the player's Settings page",
    "master_volume": "a row on the player's Settings page",
    "music_volume": "a row on the player's Settings page",
    "sound_volume": "a row on the player's Settings page",
    "voice_volume": "a row on the player's Settings page",
    "text_blips": "a row on the player's Settings page",
    "voice_sustain": "a row on the player's Settings page",
    "audio_unfocused": "a row on the player's Settings page",
    "audio_minimized": "a row on the player's Settings page",
    "mono": "a row on the player's Settings page",
    "reset_settings": "a button on the player's Settings page",
    "confirm_reset_settings": "the question before resetting settings",
    "delete_progress": "a button on the player's Settings page",
    "confirm_delete_progress": "the question before deleting progress",
    "notice_settings_default": "the notice when the player's settings can't be read",
    "skip": "the quick menu's Skip button, and the mark shown while skipping",
    "auto": "the quick menu's Auto button, and the mark shown during auto-advance",
    "back": "the quick menu's Back button, which goes back through the story",
    "codex": "the menu button and heading of the Codex page",
    "codex_tips": "the Codex tab for tips that name no category of their own",
    "codex_items": "the Codex tab for items that name no category of their own",
    "codex_new_tip": "the start of the notice for a new tip",
    "codex_new_item": "the start of the notice for a new item",
    "codex_locked": "a locked tip's row", "codex_empty": "an empty Codex page",
    "fake_crash_message": "the fake crash's message when its Fake crash line doesn't give "
                          "one",
    "fake_crash_hint": "how to continue, always shown on the fake crash screen (one line)",
    "fake_crash_label": "the fake crash's label line, if players turn it on (one line)",
    "settings_username": "a row on the player's Settings page: show their computer's user "
                         "name",
    "settings_crash_label": "a row on the player's Settings page: label fake error screens",
    "ask_username": "the question on first launch about the user name",
    "ask_username_yes": "the question's Allow button",
    "ask_username_no": "the question's Don't allow button",
    "saving_off": "the Save page's message when the story turns saving off without a reason",
    "loading_off": "the Load page's message when the story turns loading off without a "
                   "reason",
    "gallery": "the Extras screen's button and heading of the Gallery page",
    "gallery_locked": "a gallery picture the player hasn't seen yet",
    "music_room": "the Extras screen's button and heading of the Music Room page",
    "music_play": "the Music Room's button that plays the chosen song or goes on after a pause",
    "music_pause": "the Music Room's button that pauses the song playing",
    "music_previous": "the Music Room's button for the song before",
    "music_next": "the Music Room's button for the next song",
    "music_play_all": "the Music Room's mode button while each song plays once, then the next",
    "music_repeat_one": "the Music Room's mode button while the same song plays again and "
                        "again",
    "music_locked": "a song in the Music Room the player can't play yet",
    "music_pick": "the Music Room's line before a song is chosen",
})


def look_base(section: str) -> str:
    """F32: a path inside a look table as the base path it layers over, for descriptions
    (``"style.ashes.theme.textbox"`` → ``"theme.textbox"``, ``"playthrough.2.words"`` →
    ``"words"``, ``"style.ashes"`` → ``"style"``); any other path unchanged."""
    head, _, rest = section.partition(".")
    if head not in LOOK_SECTIONS or not rest:
        return section
    inner = rest.partition(".")[2]
    if not inner:
        return head
    return inner if inner.partition(".")[0] in ("theme", "words") else section


def section_class(section: str) -> type | None:
    """The dataclass of the section or table at dotted path ``section`` (``"theme.save"``;
    a look table's path as ``look_base``'s), or None."""
    section = look_base(section)
    if section in LOOK_SECTIONS:
        return LOOK_SECTIONS[section]
    cls: type | None = SECTIONS.get(section.split(".")[0])
    for part in section.split(".")[1:]:
        found = config_fields(cls).get(part) if cls is not None else None
        validator = found.metadata["validator"] if found is not None else None
        cls = validator.cls if isinstance(validator, Table) else None
    return cls


def key_doc(section: str, key: str) -> str:
    """The description of ``key`` in the section at dotted path ``section``: its ``spec``
    ``doc``, else ``THEME_DOCS`` (path, then name) or ``WORD_DOCS``; ``""`` for none. With
    ``key`` ``""``, the section's own description. A look table's path reads as its base
    (``look_base``: ``[style.ashes.theme.textbox] fill_color`` is ``[theme.textbox]``'s)."""
    section = look_base(section)
    if not key:
        parent, _, name = section.rpartition(".")
        return key_doc(parent, name) if parent else SECTION_DOCS.get(section, "")
    cls = section_class(section)
    found = config_fields(cls).get(key) if cls is not None else None
    if found is not None and found.metadata.get("doc"):
        return found.metadata["doc"]
    if section == "theme" or section.startswith("theme."):
        return THEME_DOCS.get(f"{section}.{key}") or THEME_DOCS.get(key, "")
    if section == "words":
        return WORD_DOCS.get(key, "")
    return ""
