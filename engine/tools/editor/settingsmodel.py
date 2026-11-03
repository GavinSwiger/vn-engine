"""Studio's Game settings, the pure half (F47 PR-F47-14, 15, 18; AC-F47-16, 17).

Why this module exists: a non-programmer edits ``config.toml`` through friendly fields, not
TOML. Everything here is read from ``core.config_schema``, so a key a later feature adds
shows up in **All settings** with no change here (the "Settings key coverage" rule):

- ``PAGES``: the hand-picked pages (P1: Game, Title screen, Text box, Content warning) as
  rows of section paths and keys, then **All settings**, generated from every section.
  P2 pages are new ``PageDef`` rows.
- ``page(key)`` → a ``Page`` of ``Section``s of ``Field``s (key, label, widget, default,
  help). ``all_settings()`` is the generated page; ``search(query)`` filters it.
- ``widget_for(found)`` → ``WidgetSpec``: the widget kind follows the key's validator
  (Bool → toggle, Choice → choice, HexColor → color, a ranged number → number, a file key
  → file from its asset group, a table of the author's own entries → table, anything
  else → text).
- ``values(text)`` reads the current values (raw TOML values by dotted path) with
  ``tomllib``; ``broken(text)`` is the line of a parse mistake (``broken_message``).
- ``all_keys()`` / ``text_only(path)``: the coverage registry (every key is on All
  settings, or text only with a reason shown to authors).

Values are **raw TOML values** throughout (a color is ``"#RRGGBB"``, a name list a list),
what ``tomllib`` returns and what ``tomlpatch`` writes; ``Field.default`` is in the same
form (None: not set). Writing goes through ``tomlpatch`` in the Tk view (W4), not here.

Pure Python: ``core``, ``script`` and stdlib only; no Tk, no pygame (ADR-0008).
"""

import dataclasses
import functools
import math
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from engine.core.config import map_decode_error, value_problem_text
from engine.core.config_schema import (
    LOOK_SECTIONS, SECTIONS, AudioRef, Bool, Choice, EntryMap, FontRef, GuiImageRef,
    HexColor, IconRef, IntRange, OffOrRange, Opacity, RawPluginTables, Seconds, Table,
    Validator, WarningText, config_fields, key_doc, section_class)
from engine.core.constants import CONFIG_FILENAME

WidgetKind = Literal["toggle", "choice", "color", "number", "file", "text", "table"]
KINDS: Final = ("toggle", "choice", "color", "number", "file", "text", "table")

ALL_SETTINGS: Final = "all"
BROKEN_TEXT: Final = ("config.toml has a mistake on line {line}, so these settings can't be "
                      "shown. Fix it in the Editor.")
DEFAULT_TEXT: Final = "Default: {value}"
NOT_SET: Final = "not set"
TABLE_REASON: Final = "A list of your own entries. Edit it in the Editor."
LOOK_REASON: Final = ("Styles and playthrough looks get their own page later. Edit them in "
                      "the Editor for now.")


# --- Widgets ------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WidgetSpec:
    """How a field is edited. ``kind`` is one of ``KINDS``.

    - ``choice``: ``options`` (the words, in the schema's order).
    - ``number``: ``lo``..``hi`` with ``step``; ``integer`` for whole numbers; ``off`` when
      0 also means off below ``lo`` (``[saves] autosave_interval``). ``clamp`` keeps a
      typed number in range.
    - ``file``: ``group`` (``script.assetgroups`` key) to pick from, ``suffixes`` it
      takes, ``strip`` the folder the stored value leaves out (``audio/``: a sound key
      says ``bgm/x.ogg`` for ``audio/bgm/x.ogg``), ``preview`` ``"thumb"`` or ``"play"``.
    - ``text``: ``multiline`` for long texts; ``names`` for a list of names (one text,
      comma separated: ``to_text`` / ``from_text``).
    - ``table``: not editable here; ``reason`` is shown with Open in Editor.
    ``expected`` is what the key accepts (the validator's phrase)."""

    kind: WidgetKind
    expected: str = ""
    options: tuple[str, ...] = ()
    lo: float | None = None
    hi: float | None = None
    step: float = 1
    integer: bool = True
    off: bool = False
    group: str = ""
    suffixes: tuple[str, ...] = ()
    strip: str = ""
    preview: Literal["", "thumb", "play"] = ""
    multiline: bool = False
    names: bool = False
    reason: str = ""

    def clamp(self, value: float) -> float | int:
        """``value`` brought into the number range (0 stays 0 for an ``off`` field, and
        a value below ``lo`` there becomes 0 when nearer to it); a whole number for an
        ``integer`` field. NaN clamps to ``lo``."""
        if self.lo is None or self.hi is None:
            return value
        if math.isnan(value):
            value = self.lo
        if self.off and value < self.lo:
            value = 0 if value < self.lo / 2 else self.lo
        else:
            value = min(max(value, self.lo), self.hi)
        return int(round(value)) if self.integer else float(value)

    def to_text(self, value: object) -> str:
        """A raw value as the text field shows it (a name list joined with ", ")."""
        if value is None:
            return ""
        if self.names and isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def from_text(self, text: str) -> object:
        """The raw value for what was typed into a text or number field: a name list for
        ``names``, an int or float for ``number`` (ValueError if it isn't one), else the
        text."""
        if self.names:
            return [part.strip() for part in text.split(",") if part.strip()]
        if self.kind == "number":
            text = text.strip()
            return int(text) if self.integer else float(text)
        return text


def _file(group: str, suffixes: tuple[str, ...], preview: Literal["thumb", "play"],
          expected: str, strip: str = "") -> WidgetSpec:
    return WidgetSpec("file", expected, group=group, suffixes=suffixes, strip=strip,
                      preview=preview)


def widget_for(found: dataclasses.Field) -> WidgetSpec:
    """The widget for a config key's field, by its validator (PR-F47-14)."""
    from engine.core.constants import FONT_SUFFIXES, IMAGE_SUFFIXES
    from engine.script.audio import PLAYABLE_EXTS

    validator: Validator = found.metadata["validator"]
    expected = validator.expected
    if isinstance(validator, Bool):
        return WidgetSpec("toggle", expected)
    if isinstance(validator, Choice):
        return WidgetSpec("choice", expected, options=tuple(validator.options))
    if isinstance(validator, HexColor):
        return WidgetSpec("color", expected)
    if isinstance(validator, OffOrRange):
        return WidgetSpec("number", expected, lo=validator.range.lo, hi=validator.range.hi,
                          off=True)
    if isinstance(validator, IntRange):
        return WidgetSpec("number", expected, lo=validator.lo, hi=validator.hi)
    if isinstance(validator, Opacity):
        return WidgetSpec("number", expected, lo=validator.low, hi=validator.high,
                          step=0.05, integer=False)
    if isinstance(validator, Seconds):
        step = 0.01 if validator.hi <= 1 else 0.1
        return WidgetSpec("number", expected, lo=validator.lo, hi=validator.hi, step=step,
                          integer=False)
    if isinstance(validator, FontRef):
        return _file("fonts", FONT_SUFFIXES, "thumb", expected)
    if isinstance(validator, GuiImageRef):
        return _file("gui", IMAGE_SUFFIXES, "thumb", expected)
    if isinstance(validator, IconRef):
        return _file("gui", (".png",), "thumb", expected)
    if isinstance(validator, AudioRef):
        return _file("audio", tuple(sorted(PLAYABLE_EXTS)), "play", expected, strip="audio/")
    if isinstance(validator, (Table, EntryMap, RawPluginTables)):
        return WidgetSpec("table", expected, reason=TABLE_REASON)
    if isinstance(validator, WarningText):
        return WidgetSpec("text", expected, multiline=True)
    if type(found.default) is tuple or "list" in expected:     # NameList
        return WidgetSpec("text", expected, names=True)
    return WidgetSpec("text", expected)


# --- Fields, sections, pages --------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Field:
    """One key on a page. ``section`` is its dotted header path (``theme.textbox.name_tab``)
    and ``key`` its name as written; ``path`` is both. ``default`` is the raw TOML default
    (None: not set by default); ``default_text`` the Use default caption. ``help`` is the
    key's description (``key_doc``), else what it accepts."""

    section: str
    key: str
    label: str
    help: str
    default: object
    default_text: str
    widget: WidgetSpec
    validator: Validator

    @property
    def path(self) -> str:
        return f"{self.section}.{self.key}"

    @property
    def kind(self) -> WidgetKind:
        return self.widget.kind

    def current(self, found: Mapping[str, object]) -> object:
        """This key's value in ``values(text)``, else its default."""
        return found.get(self.path, self.default)

    def is_set(self, found: Mapping[str, object]) -> bool:
        """True when ``config.toml`` sets this key (Use default would remove the line; the
        view's 2 px changed bar shows when the value also differs from ``default``)."""
        return self.path in found

    def changed(self, found: Mapping[str, object]) -> bool:
        """True when the file sets the key to something other than its default."""
        return self.path in found and found[self.path] != self.default

    def problem(self, value: object) -> str | None:
        """None when the key accepts the raw ``value``, else the engine's message."""
        try:
            self.validator.check(value)
        except Exception:                      # ValueProblem, or a bad type for check
            return value_problem_text(f"[{self.section}] {self.key}", self.validator, value)
        return None


@dataclass(frozen=True, slots=True)
class Section:
    """A captioned group of fields: ``title`` for the caption, ``path`` its header (a muted
    hint), ``help`` the section's description."""

    path: str
    title: str
    help: str
    fields: tuple[Field, ...]


@dataclass(frozen=True, slots=True)
class Page:
    key: str
    title: str
    sections: tuple[Section, ...]
    preview: Literal["", "textbox", "title"] = ""

    @property
    def fields(self) -> tuple[Field, ...]:
        return tuple(f for section in self.sections for f in section.fields)


@dataclass(frozen=True, slots=True)
class Row:
    """A hand-picked section of a page: the keys of ``path`` (all of its own keys, without
    nested tables, when ``keys`` is empty), under ``title``."""

    path: str
    title: str
    keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PageDef:
    key: str
    title: str
    rows: tuple[Row, ...]
    preview: Literal["", "textbox", "title"] = ""


PAGES: Final[tuple[PageDef, ...]] = (
    PageDef("game", "Game", (
        Row("game", "Game", ("title", "version")),
        Row("window", "Window", ("width", "height", "fullscreen", "icon")))),
    PageDef("title", "Title screen", (
        Row("title", "Title screen"),
        Row("theme.title", "Look"),
        Row("theme.title.logo", "Game name (when there is no logo picture)"),
        Row("theme.title.version", "Version text"),
        Row("theme.title.loading", "Loading text")), preview="title"),
    PageDef("textbox", "Text box", (
        Row("textbox", "Typing", ("cps",)),
        Row("theme.textbox", "Text box"),
        Row("theme.textbox.name_tab", "Name tab"),
        Row("theme.textbox.indicator", "Click-to-continue mark")), preview="textbox"),
    PageDef("content_warning", "Content warning", (
        Row("content_warning", "Content warning"),)),
    PageDef(ALL_SETTINGS, "All settings", ()),          # generated: all_settings()
)

# Labels a key's name doesn't say well, by dotted path, then by key name.
LABELS: Final[Mapping[str, str]] = MappingProxyType({
    "game.title": "Game title", "game.id": "Save folder name",
    "window.width": "Window width", "window.height": "Window height",
    "window.fullscreen": "Start in fullscreen", "window.icon": "Window icon",
    "textbox.cps": "Text speed (characters per second)",
    "title.enabled": "Show the title screen", "title.show_version": "Show the version",
    "title.entries": "Buttons",
    "content_warning.show": "Show it", "content_warning.text": "Warning text",
    "content_warning.version": "Warning version",
    "content_warning.min_seconds": "Wait before continuing (seconds)",
    "engine.fps": "Frames per second", "engine.cache_mb": "Image memory (MB)",
})
_WORDS: Final = {"ms": "(ms)", "mb": "(MB)", "cps": "(characters per second)", "id": "ID",
                 "fps": "frames per second"}


def label_for(section: str, key: str) -> str:
    """The field's label: ``LABELS`` by path, else its words (``fade_in_ms`` → "Fade in
    (ms)")."""
    shown = LABELS.get(f"{section}.{key}")
    if shown is not None:
        return shown
    words = [_WORDS.get(word, word) for word in key.split("_") if word]
    text = " ".join(words) or key
    return text[:1].upper() + text[1:]


def section_title(path: str) -> str:
    """A generated caption: each part of the path in words (``theme.textbox.name_tab`` →
    "Theme › Textbox › Name tab")."""
    return " › ".join(label_for("", part) for part in path.split("."))


def raw_default(found: dataclasses.Field) -> object:
    """The key's default as a raw TOML value (a color ``"#RRGGBB"``, a name list a list),
    or None when it has none (not set, or a table)."""
    if found.default is dataclasses.MISSING:
        return None
    value = found.default
    if value is None or isinstance(value, Mapping):
        return None
    if isinstance(value, tuple):
        if isinstance(found.metadata["validator"], HexColor):
            return "#{:02X}{:02X}{:02X}".format(*value)
        return list(value)
    return value


def default_caption(widget: WidgetSpec, default: object) -> str:
    """``Default: {value}`` in the field's own words (On/Off, a color's hex, plain text)."""
    if default is None:
        value = NOT_SET
    elif isinstance(default, bool):
        value = "On" if default else "Off"
    elif default == "" and widget.kind == "text":
        value = "empty"
    elif widget.kind == "number" and widget.off and default == 0:
        value = "0 (off)"
    else:
        value = widget.to_text(default)
    return DEFAULT_TEXT.format(value=value)


def _make_field(section: str, key: str, found: dataclasses.Field) -> Field:
    widget = widget_for(found)
    default = raw_default(found)
    return Field(section, key, label_for(section, key),
                 key_doc(section, key) or f"Accepts {widget.expected}",
                 default, default_caption(widget, default), widget,
                 found.metadata["validator"])


def _section(path: str, title: str, keys: tuple[str, ...] = ()) -> Section:
    cls = section_class(path)
    if cls is None:
        raise KeyError(path)
    fields = config_fields(cls)
    names = keys or tuple(key for key, found in fields.items()
                          if not isinstance(found.metadata["validator"], Table))
    return Section(path, title, key_doc(path, ""),
                   tuple(_make_field(path, key, fields[key]) for key in names))


def _walk(path: str, cls: type) -> Iterator[tuple[str, type]]:
    yield path, cls
    for key, found in config_fields(cls).items():
        validator = found.metadata["validator"]
        if isinstance(validator, Table):
            yield from _walk(f"{path}.{key}", validator.cls)


def table_paths() -> tuple[str, ...]:
    """Every section and nested table path of ``SECTIONS``, in declaration order."""
    return tuple(path for name, cls in SECTIONS.items() for path, _ in _walk(name, cls))


@functools.cache
def all_settings() -> Page:
    """**All settings**: one section per section or nested table that has keys of its own
    (every key of ``SECTIONS``), in the schema's order."""
    sections = (_section(path, section_title(path)) for path in table_paths())
    return Page(ALL_SETTINGS, "All settings", tuple(s for s in sections if s.fields))


@functools.cache
def page(key: str) -> Page:
    """The page ``key`` of ``PAGES`` (KeyError for an unknown one)."""
    if key == ALL_SETTINGS:
        return all_settings()
    for found in PAGES:
        if found.key == key:
            return Page(found.key, found.title,
                        tuple(_section(row.path, row.title, row.keys) for row in found.rows),
                        found.preview)
    raise KeyError(key)


def pages() -> tuple[Page, ...]:
    """Every page in ``PAGES`` order (All settings last)."""
    return tuple(page(found.key) for found in PAGES)


@functools.cache
def fields_by_path() -> Mapping[str, Field]:
    """Every field of All settings by dotted path."""
    return MappingProxyType({f.path: f for f in all_settings().fields})


def search(query: str) -> tuple[Section, ...]:
    """All settings' sections cut to the fields whose label, path or help contains
    ``query`` (any case, ``_`` as a space), or every field of a section whose title or path
    contains it; every section for a blank query."""
    def fold(text: str) -> str:
        return " ".join(text.casefold().replace("_", " ").split())

    folded = fold(query)
    if not folded:
        return all_settings().sections
    found = []
    for section in all_settings().sections:
        whole = folded in fold(section.title) or folded in fold(section.path)
        hits = tuple(f for f in section.fields if whole or any(
            folded in fold(text) for text in (f.label, f.path, f.help)))
        if hits:
            found.append(dataclasses.replace(section, fields=hits))
    return tuple(found)


# --- Coverage registry --------------------------------------------------------------------

def all_keys() -> tuple[str, ...]:
    """Every ``config.toml`` key by dotted path: each key of ``SECTIONS`` and its nested
    tables, then the own keys of F32's look tables (``playthrough.<N>.title_entries``;
    their ``theme`` and ``words`` tables repeat keys already listed)."""
    keys = [f"{path}.{key}" for path in table_paths()
            for key, found in config_fields(section_class(path)).items()
            if not isinstance(found.metadata["validator"], Table)]
    for name, cls in LOOK_SECTIONS.items():
        keys += [f"{name}.<{'N' if name == 'playthrough' else 'name'}>.{key}"
                 for key, found in config_fields(cls).items()
                 if not isinstance(found.metadata["validator"], Table)]
    return tuple(keys)


TEXT_ONLY: Final[Mapping[str, str]] = MappingProxyType({
    "style": LOOK_REASON, "playthrough": LOOK_REASON})


def text_only(path: str) -> str | None:
    """The reason shown to authors when the key at ``path`` is on purpose not a field, or
    None (keyed by the path's first part)."""
    return TEXT_ONLY.get(path.partition(".")[0])


# --- Reading config.toml ------------------------------------------------------------------

def broken(text: str) -> int | None:
    """The line of ``text``'s parse mistake (1 when the parser gives none), or None when it
    parses."""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return map_decode_error(exc, text).line or 1
    return None


def broken_message(line: int) -> str:
    """PR-F47-18's text for a ``config.toml`` that doesn't parse."""
    return BROKEN_TEXT.format(line=line)


def values(text: str) -> Mapping[str, object] | None:
    """The values ``text`` sets, as raw TOML values by dotted path (``"window.width"``,
    ``"theme.textbox.name_tab.text_color"``), or None when it doesn't parse. A table the
    schema knows as one key (``stage.positions``) is one value; its entries are not split."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    found: dict[str, object] = {}

    def walk(path: str, table: Mapping[str, object]) -> None:
        cls = section_class(path)
        known = config_fields(cls) if cls is not None else {}
        for key, value in table.items():
            inner = known.get(key)
            nested = inner is not None and isinstance(inner.metadata["validator"], Table)
            if isinstance(value, dict) and (nested or inner is None):
                walk(f"{path}.{key}", value)
            else:
                found[f"{path}.{key}"] = value

    for name, value in doc.items():
        if isinstance(value, dict):
            walk(name, value)
        else:
            found[name] = value
    return MappingProxyType(found)


__all__ = ["ALL_SETTINGS", "BROKEN_TEXT", "CONFIG_FILENAME", "DEFAULT_TEXT", "Field", "KINDS",
           "LABELS", "LOOK_REASON", "NOT_SET", "PAGES", "Page", "PageDef", "Row", "Section",
           "TABLE_REASON", "TEXT_ONLY", "WidgetKind", "WidgetSpec", "all_keys",
           "all_settings", "broken", "broken_message", "default_caption", "fields_by_path",
           "label_for", "page", "pages", "raw_default", "search", "section_title",
           "table_paths", "text_only", "values", "widget_for"]
