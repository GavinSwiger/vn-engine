"""Studio's Game settings, the pure half (F47 PR-F47-14, 15, 18; AC-F47-16, 17).

Why this module exists: a non-programmer edits ``config.toml`` through friendly fields, not
TOML. Everything here is read from ``core.config_schema``, so a key a later feature adds
shows up in **All settings** with no change here (the "Settings key coverage" rule):

- ``PAGES``: the hand-picked pages (P1: Game, F49's generated **Color scheme** (``SCHEMES``,
  ``schememodel``), Title screen, Text box, Content warning; P2,
  ``P2_PAGES``: Choices, Saves & going back, Sound volumes, Effects & comfort, Chapters &
  codex, Flowchart, Fourth wall, F34's Extras, Button words) as rows of section paths and
  keys (a row whose section the schema doesn't have yet is left out), then
  **Styles & playthrough looks** (W9: ``looks``, ``look_page``, ``new_look_change``) and
  **All settings**, both generated.
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
import re
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
from engine.core.constants import (
    CONFIG_FILENAME, PLAYTHROUGH_MAX, PLAYTHROUGH_TABLES_MAX, STATEMENT_WORDS, STYLE_NAME_RE,
    STYLES_MAX)

WidgetKind = Literal["toggle", "choice", "color", "number", "file", "text", "table"]
KINDS: Final = ("toggle", "choice", "color", "number", "file", "text", "table")

ALL_SETTINGS: Final = "all"
LOOKS: Final = "looks"                  # W9: Styles & playthrough looks
SCHEMES: Final = "schemes"              # F49: Color scheme (cards: schememodel, schemecards)
BROKEN_TEXT: Final = ("config.toml has a mistake on line {line}, so these settings can't be "
                      "shown. Fix it in the Editor.")
DEFAULT_TEXT: Final = "Default: {value}"
NOT_SET: Final = "not set"
TABLE_REASON: Final = "A list of your own entries. Edit it in the Editor."


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
    ``expected`` is what the key accepts (the validator's phrase). ``labels``: a choice's
    shown names as ``(option, name)`` pairs, from the validator's ``Choice.labels`` (F49:
    "Pocket LCD" for ``pocket``); ``option_text`` reads them."""

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
    labels: tuple[tuple[str, str], ...] = ()

    def option_text(self, option: str) -> str:
        """How a choice's ``option`` is shown: its ``labels`` name, else its words
        (``slow_down`` → "Slow down")."""
        for value, name in self.labels:
            if value == option:
                return name
        return option.replace("_", " ").capitalize()

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
        return WidgetSpec("choice", expected, options=tuple(validator.options),
                          labels=tuple((o, validator.labels[o]) for o in validator.options
                                       if o in validator.labels))
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
    nested tables, when ``keys`` is empty), under ``title``. ``rest``: instead, the keys of
    ``path`` that no earlier row of the page shows (so a key a later feature adds to a split
    section, such as ``[words]``, still lands on the page); no section when there are none.
    ``later``: a feature's step running beside this one adds some of ``keys``; until it does,
    the row shows the keys the schema has (none: no section)."""

    path: str
    title: str
    keys: tuple[str, ...] = ()
    rest: bool = False
    later: bool = False


@dataclass(frozen=True, slots=True)
class PageDef:
    key: str
    title: str
    rows: tuple[Row, ...]
    preview: Literal["", "textbox", "title"] = ""


# F35's Music Room page words (SPEC §5.1; F35-S2 adds them to WordsConfig).
MUSIC_ROOM_WORDS: Final = ("music_room", "music_play", "music_pause", "music_previous",
                           "music_next", "music_play_all", "music_repeat_one", "music_locked",
                           "music_pick")
# F36's Endings and Scenes pages and the replay's words (01 §6.2; F36-W3 adds them to
# WordsConfig).
REPLAY_WORDS: Final = ("endings", "endings_count", "ending_locked", "ending_replay", "replays",
                       "replay_end", "replay_no_saving")
# F37's Achievements page and notice words (SPEC §5.1; F37-S2 adds them to WordsConfig).
ACHIEVEMENT_WORDS: Final = ("achievements", "achievement_unlocked", "achievements_progress",
                            "achievement_hidden", "achievement_hidden_text")
PAGES: Final[tuple[PageDef, ...]] = (
    PageDef("game", "Game", (
        Row("game", "Game", ("title", "version")),
        Row("window", "Window", ("width", "height", "fullscreen", "icon")))),
    # F49: generated by the view as LOOKS is (the scheme cards); its still is the text box.
    PageDef(SCHEMES, "Color scheme", (), preview="textbox"),
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
    # P2 (PR-F47-17, AC-F47-49). Choices and Chapters have no preview still yet. Styles and
    # playthrough looks (W9) are the generated LOOKS page: one look at a time (look_page).
    PageDef("choices", "Choices", (
        Row("choice", "Choices"),
        Row("theme.choice", "Look"),
        Row("theme.choice.focused", "Under the mouse"),
        Row("theme.choice.marker", "Marker"),
        Row("theme.choice.locked", "Locked choices"))),
    PageDef("saves", "Saves & going back", (
        Row("saves", "Saves"),
        Row("chapter", "Chapter saves"),
        Row("theme.save", "Save and Load pages"),
        Row("theme.save.badge", "Tags on a save"),
        Row("theme.save.newest", "Newest tag"),
        Row("theme.save.placeholder", "Empty, loading, and damaged slots"),
        Row("rollback", "Going back"),
        Row("theme.rollback", "When the player can't go back further"),
        Row("theme.rollback.mark", "Its mark"))),
    PageDef("sound", "Sound volumes", (
        Row("audio", "Starting volumes",
            ("master_volume", "music_volume", "sound_volume", "voice_volume")),
        Row("audio", "Fades", ("music_fadein", "music_fadeout", "sound_fadein",
                               "sound_fadeout", "restore_fadeout", "restore_fadein")),
        Row("audio", "In the background", ("play_unfocused", "play_minimized")),
        Row("audio", "Music loops", rest=True))),
    PageDef("effects", "Effects & comfort", (
        Row("effects", "Comfort", ("reduce", "timing_assist")),          # F50
        Row("effects", "Effect lengths and sizes", rest=True),
        Row("theme.effects", "Effect colors"),
        Row("animation", "Sprite animation"),           # F38 PR-F38-08
        Row("auto", "Auto-advance"),
        Row("skip", "Skipping"))),
    PageDef("chapters", "Chapters & codex", (
        Row("theme.chapter", "Chapter title card"),
        Row("theme.chapter.heading", "Card heading"),
        Row("theme.chapter.title", "Card title"),
        Row("codex", "Codex"),
        Row("theme.codex", "Codex page"),
        Row("theme.codex.new", "New entry mark"),
        Row("theme.codex.locked", "Locked entries"))),
    PageDef("flowchart", "Flowchart", (
        Row("flowchart", "Flowchart page"),
        Row("theme.flowchart", "Look"),
        Row("theme.flowchart.node", "Boxes the player has seen"),
        Row("theme.flowchart.start", "Start box"),
        Row("theme.flowchart.chapter", "Chapter boxes"),
        Row("theme.flowchart.choice", "Choice boxes"),
        Row("theme.flowchart.scene", "Scene boxes"),
        Row("theme.flowchart.ending", "Ending boxes"),
        Row("theme.flowchart.gate", "Locked route gates"),
        Row("theme.flowchart.unknown", "Boxes not seen yet"),
        Row("theme.flowchart.edge", "Lines between boxes"),
        Row("theme.flowchart.path", "This playthrough's path"),
        Row("theme.flowchart.here", "“You are here” tab"))),
    PageDef("content_warning", "Content warning", (
        Row("content_warning", "Content warning"),)),
    PageDef("fourth_wall", "Fourth wall", (
        Row("meta", "Player's user name"),
        Row("words", "Asking the player", ("ask_username", "ask_username_yes",
                                           "ask_username_no", "settings_username")),
        Row("words", "Fake crash screen", ("fake_crash_message", "fake_crash_hint",
                                           "fake_crash_label", "settings_crash_label")))),
    # F34 (design §7): the Extras screen's pages; F35-F37 add their rows here. A row whose
    # section isn't in config_schema yet is left out (page()).
    PageDef("extras", "Extras", (
        Row("gallery", "Gallery"),
        Row("theme.gallery.caption", "Gallery picture titles"),
        Row("theme.gallery.viewer", "Gallery picture viewer"),
        Row("words", "Music room words", MUSIC_ROOM_WORDS, later=True),
        Row("endings", "Endings list", ("list", "replay"), later=True),
        Row("words", "Endings and scene replay words", REPLAY_WORDS, later=True),
        Row("words", "Achievement words", ACHIEVEMENT_WORDS, later=True))),
    PageDef("words", "Button words", (
        Row("words", "Title screen and game menu", (
            "new_game", "load", "save", "settings", "history", "extras", "help", "codex",
            "flowchart", "main_menu", "quit", "return", "skip_minigame")),
        Row("words", "Quick menu", ("hide", "menu", "q_save", "q_load", "skip", "auto",
                                    "back")),
        Row("words", "Questions", (
            "yes", "no", "confirm_main_menu", "confirm_main_menu_autosave", "confirm_quit",
            "confirm_quit_autosave", "confirm_overwrite", "confirm_delete", "confirm_load",
            "confirm_nearest", "confirm_reset_settings", "confirm_delete_progress",
            "confirm_skip_minigame", "flowchart_confirm", "flowchart_confirm_autosave")),
        Row("words", "Notices", (
            "notice_quick_saved", "notice_no_quick_save", "notice_cant_save",
            "notice_save_failed", "save_reason_disk_full", "save_reason_folder",
            "save_reason_slots", "save_reason_other", "notice_too_large",
            "notice_load_damaged", "notice_load_no_fit", "notice_load_failed",
            "notice_delete_failed", "notice_persistent", "notice_settings_default")),
        Row("words", "Save and Load pages", (
            "save_page_auto", "save_page_quick", "save_slot", "save_newest", "save_empty",
            "save_loading", "save_no_picture", "save_none", "save_damaged", "save_newer",
            "save_other_game", "saving_off", "loading_off")),
        Row("words", "Player's Settings page", (
            "settings_display", "settings_text", "settings_sound", "settings_data",
            "fullscreen", "reduce_motion", "timing_assist", "timing_normal", "timing_slower",
            "timing_off", "text_speed", "text_instant", "text_size",
            "auto_wait", "auto_voice", "skip_unread", "master_volume", "music_volume",
            "sound_volume", "voice_volume", "text_blips", "voice_sustain", "audio_unfocused",
            "audio_minimized", "mono", "settings_username", "settings_crash_label",
            "reset_settings", "delete_progress")),
        Row("words", "Switches and empty pages", ("on", "off", "loading", "list_empty")),
        Row("words", "Codex", ("codex_tips", "codex_items", "codex_new_tip",
                               "codex_new_item", "codex_locked", "codex_empty")),
        Row("words", "Flowchart", (
            "flowchart_jump", "flowchart_start", "flowchart_chapter", "flowchart_choice",
            "flowchart_scene", "flowchart_ending", "flowchart_route", "flowchart_unknown",
            "flowchart_var", "flowchart_here", "flowchart_changed", "flowchart_no_state",
            "flowchart_no_jump", "flowchart_endings", "flowchart_nodes")),
        Row("words", "Content warning", ("warning_heading", "warning_continue")),
        Row("words", "Music room", MUSIC_ROOM_WORDS, later=True),
        Row("words", "Endings and scene replays", REPLAY_WORDS, later=True),
        Row("words", "Achievements", ACHIEVEMENT_WORDS, later=True),
        Row("words", "Fake crash and user name", (
            "fake_crash_message", "fake_crash_hint", "fake_crash_label", "ask_username",
            "ask_username_yes", "ask_username_no")),
        Row("words", "Other words", rest=True))),
    PageDef(LOOKS, "Styles & playthrough looks", ()),   # generated: looks(), look_page()
    PageDef(ALL_SETTINGS, "All settings", ()),          # generated: all_settings()
)
P2_PAGES: Final = ("choices", "saves", "sound", "effects", "chapters", "flowchart",
                   "fourth_wall", "extras", "words")

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
    "theme.preset": "Color scheme",                                 # F49 §4
    # P2 pages (AC-F47-49)
    "choice.show_locked": "Show locked choices",
    "saves.pages": "Save pages", "saves.autosave_interval": "Auto-save every (seconds)",
    "saves.autosave_choices": "Auto-save before choices",
    "saves.autosave_quit": "Auto-save when quitting",
    "chapter.autosave": "Auto-save at each chapter",
    "chapter.name_saves": "Name saves after chapters",
    "rollback.steps": "Steps back", "rollback.marker": "Show the rewind marker",
    "audio.play_unfocused": "Play in the background",
    "audio.play_minimized": "Play while minimized", "audio.loop_start": "Loop points",
    "effects.reduce": "Reduce motion and flashing",
    "effects.timing_assist": "Timing assist for new players",       # F50 §6
    "animation.enabled": "Blinking and talking sprites",            # F38 §4
    "animation.blink_every": "Blink about every (seconds)",
    "animation.blink_frame": "Seconds per blink frame",
    "animation.talk_frame": "Seconds per talking frame",
    "auto.delay": "Wait after a line (seconds)",
    "auto.per_char": "Extra wait per character (seconds)",
    "skip.all": "Skip unread text too",
    "codex.notify": "Notice for new entries", "codex.show_locked": "Show locked tips",
    "flowchart.enabled": "Show the Flowchart", "flowchart.menus": "Choice menus shown",
    "flowchart.unvisited": "Scenes not seen yet", "flowchart.jump": "Let players jump",
    "meta.username": "Offer the player's user name",
    "meta.username_fallback": "Name shown otherwise",
    "words.plugin": "Minigames' own words", "theme.plugin": "Minigames' own look",
    "gallery.show_locked": "Show locked pictures as ???",           # F34 §7
    "words.music_room": "Music Room heading", "words.music_play": "Play button",  # F35 §4
    "words.music_pause": "Pause button", "words.music_previous": "Previous button",
    "words.music_next": "Next button", "words.music_play_all": "Play all button",
    "words.music_repeat_one": "Repeat track button", "words.music_locked": "Locked track",
    "words.music_pick": "Nothing picked yet",
    "endings.list": "Show an Endings page in Extras",                # F36 §7
    "endings.replay": "Let players replay endings they've reached",
    "words.endings": "Endings page heading", "words.endings_count": "Endings reached",
    "words.ending_locked": "Ending not reached yet", "words.ending_replay": "Replay button",
    "words.replays": "Scenes page heading", "words.replay_end": "End Replay button",
    "words.replay_no_saving": "No saving during a replay",
    "words.achievements": "Achievements page heading",             # F37 §5.1
    "words.achievement_unlocked": "Unlock notice",
    "words.achievements_progress": "Unlocked count",
    "words.achievement_hidden": "Hidden achievement title",
    "words.achievement_hidden_text": "Hidden achievement text",
})
_WORDS: Final = {"ms": "(ms)", "mb": "(MB)", "cps": "(characters per second)", "id": "ID",
                 "fps": "frames per second", "fadein": "fade in", "fadeout": "fade out",
                 "autosave": "auto-save", "cant": "can't", "char": "character",
                 "var": "variable", "q": "quick"}


# Hints a key's config description doesn't say well for Studio, by dotted path.
HELPS: Final[Mapping[str, str]] = MappingProxyType({
    "effects.timing_assist": "The Timing assist a new player starts with. Players change it "
                             "on the Settings page.",                # F50 §6
})


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
                 HELPS.get(f"{section}.{key}") or key_doc(section, key)
                 or f"Accepts {widget.expected}",
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
            sections: list[Section] = []
            for row in found.rows:
                if section_class(row.path) is None:       # a later step adds it
                    continue
                if not row.rest:
                    keys = row.keys
                    if row.later:
                        have = config_fields(section_class(row.path))
                        keys = tuple(k for k in keys if k in have)
                        if not keys:
                            continue
                    sections.append(_section(row.path, row.title, keys))
                    continue
                shown = {f.key for s in sections if s.path == row.path for f in s.fields}
                rest = tuple(k for k, f in config_fields(section_class(row.path)).items()
                             if k not in shown and not isinstance(f.metadata["validator"],
                                                                  Table))
                if rest:
                    sections.append(_section(row.path, row.title, rest))
            return Page(found.key, found.title, tuple(sections), found.preview)
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


# W9 put the look tables on their own page (``LOOKS``), so no key is text only now; the map
# stays for a later feature's tables.
TEXT_ONLY: Final[Mapping[str, str]] = MappingProxyType({})


def text_only(path: str) -> str | None:
    """The reason shown to authors when the key at ``path`` is on purpose not a field, or
    None (keyed by the path's first part)."""
    return TEXT_ONLY.get(path.partition(".")[0])


# --- Styles & playthrough looks (F47 W9, PR-F47-17; F32 PR-F32-02, 05) ---------------------
# The page lists the file's ``[style.<name>]`` and ``[playthrough.N]`` tables; each look's
# fields are its base keys (a style: the in-game areas, a playthrough look: the title) under
# the look's path, so ``tomlpatch`` writes ``[style.ashes.theme.textbox] fill_color``. A key
# not set keeps the main look. + New style / + New playthrough look write one key, the main
# look's value of ``NEW_LOOK_KEYS``, which creates the table for the author to change.

STYLE: Final = "style"
PLAYTHROUGH: Final = "playthrough"
LOOK_UNSET: Final = "Not set: the main look"
STYLE_NAME_RULE: Final = ("A style name is lowercase letters, digits and _, starting with a "
                          "letter (up to 32), and not off.")
STYLES_FULL: Final = f"A game can have at most {STYLES_MAX} styles."
PLAYTHROUGH_RULE: Final = f"A playthrough look is a whole number from 0 to {PLAYTHROUGH_MAX}."
PLAYTHROUGHS_FULL: Final = f"A game can have at most {PLAYTHROUGH_TABLES_MAX} playthrough looks."
LOOK_TAKEN: Final = "There's already {what} called {name}. Pick another name."
LOOK_TITLES: Final = {STYLE: "Style {name}", PLAYTHROUGH: "Playthrough {name} look"}
NEW_LOOK_KEYS: Final = {STYLE: ("theme.textbox", "fill_color"),
                        PLAYTHROUGH: ("theme.title", "fill_top_color")}
STYLE_ROWS: Final = (
    Row("theme", "Color scheme", ("preset",)),                     # F49: not set: the main one
    Row("theme.textbox", "Text box"), Row("theme.textbox.name_tab", "Name tab"),
    Row("theme.textbox.indicator", "Click-to-continue mark"),
    Row("theme.choice", "Choices"), Row("theme.choice.focused", "Choice under the mouse"),
    Row("theme.choice.marker", "Choice marker"),
    Row("theme.choice.locked", "Locked choices"),
    Row("theme.nvl", "Full-screen text"), Row("theme.nvl.name", "Full-screen names"),
    Row("theme.nvl.indicator", "Full-screen click-to-continue mark"),
    Row("theme.quick_menu", "Quick menu"),
    Row("theme.quick_menu.focused", "Quick menu under the mouse"),
    Row("words", "Words while the style is on", (
        "hide", "menu", "q_save", "q_load", "skip", "auto", "back", "saving_off",
        "loading_off")))
PLAYTHROUGH_ROWS: Final = (
    Row("", "Title buttons", ("title_entries",)),
    Row("theme.title", "Title screen"), Row("theme.title.logo", "Game name"),
    Row("theme.title.version", "Version text"),
    Row("words", "Title screen words", (
        "new_game", "load", "settings", "extras", "help", "quit")))


def _look_name_ok(kind: str, name: str) -> bool:
    if kind == STYLE:
        return (STYLE_NAME_RE.fullmatch(name) is not None and name != "off"
                and name not in STATEMENT_WORDS)
    return re.fullmatch(r"0|[1-9][0-9]?", name) is not None


def looks(text: str) -> tuple[tuple[str, str], ...]:
    """The look tables ``text`` has, as (kind, name): styles by name, then playthrough looks
    by number; tables with an unusable name are left out (the check names them)."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return ()
    found: list[tuple[str, str]] = []
    for kind in (STYLE, PLAYTHROUGH):
        tables = doc.get(kind)
        if not isinstance(tables, dict):
            continue
        names = [n for n, t in tables.items() if isinstance(t, dict) and _look_name_ok(kind, n)]
        names.sort(key=int if kind == PLAYTHROUGH else str)
        found += [(kind, n) for n in names]
    return tuple(found)


def style_names(text: str) -> tuple[str, ...]:
    """The ``[style.<name>]`` names in ``text`` (the Game UI form's style picker)."""
    return tuple(name for kind, name in looks(text) if kind == STYLE)


def look_title(kind: str, name: str) -> str:
    return LOOK_TITLES[kind].format(name=name)


def is_look(found: Field) -> bool:
    """True for a field of a look table (its "not set" means the main look)."""
    return found.section.partition(".")[0] in LOOK_SECTIONS


def _look_section(prefix: str, row: Row) -> Section:
    if not row.path:                                   # the table's own keys
        cls = LOOK_SECTIONS[prefix.partition(".")[0]]
        fields = config_fields(cls)
        made = tuple(_make_field(prefix, key, fields[key]) for key in row.keys)
        base_help = ""
    else:
        base = _section(row.path, row.title, row.keys)
        made = tuple(dataclasses.replace(f, section=f"{prefix}.{f.section}")
                     for f in base.fields)
        base_help = base.help
    shown = tuple(dataclasses.replace(f, default_text=LOOK_UNSET) for f in made)
    path = f"{prefix}.{row.path}" if row.path else prefix
    return Section(path, row.title, base_help, shown)


@functools.cache
def look_page(kind: str, name: str) -> Page:
    """One look's fields (``STYLE_ROWS`` or ``PLAYTHROUGH_ROWS`` under ``[kind.name]``)."""
    rows = STYLE_ROWS if kind == STYLE else PLAYTHROUGH_ROWS
    prefix = f"{kind}.{name}"
    return Page(f"{LOOKS}:{kind}:{name}", look_title(kind, name),
                tuple(_look_section(prefix, row) for row in rows))


def on_looks_page(path: str) -> bool:
    """True for an ``all_keys`` look key (``playthrough.<N>.title_entries``) that the Looks
    page edits (the coverage rule); a look's theme and words keys are their base keys'."""
    kind, _, rest = path.partition(".")
    if kind not in LOOK_SECTIONS:
        return False
    key = rest.partition(".")[2]
    rows = STYLE_ROWS if kind == STYLE else PLAYTHROUGH_ROWS
    return any(not row.path and key in row.keys for row in rows)


def new_look_problem(kind: str, name: str, text: str) -> str | None:
    """Why ``name`` can't be a new look of ``kind`` in ``text``, or None."""
    name = name.strip()
    taken = [n for k, n in looks(text) if k == kind]
    if not _look_name_ok(kind, name):
        return STYLE_NAME_RULE if kind == STYLE else PLAYTHROUGH_RULE
    if name in taken:
        what = "a style" if kind == STYLE else "a playthrough look"
        return LOOK_TAKEN.format(what=what, name=name)
    limit = STYLES_MAX if kind == STYLE else PLAYTHROUGH_TABLES_MAX
    if len(taken) >= limit:
        return STYLES_FULL if kind == STYLE else PLAYTHROUGHS_FULL
    return None


def new_look_change(kind: str, name: str, found: Mapping[str, object]
                    ) -> tuple[str, str, object]:
    """The one ``(section, key, value)`` that creates the look: ``NEW_LOOK_KEYS``' key at
    the main look's value (``found``: ``values(text)``)."""
    section, key = NEW_LOOK_KEYS[kind]
    main = fields_by_path()[f"{section}.{key}"]
    return f"{kind}.{name.strip()}.{section}", key, main.current(found)


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


def section_values(section: str, text: str | None) -> dict[str, object]:
    """``[section]``'s own keys as the game would use them: each value ``text``
    (``config.toml``'s) sets that its key accepts, else the key's default (a file that
    doesn't parse, or None, gives every default). F38's look panel reads its preview timings
    with this (``[animation]``), never through the engine's config loading (07 I-10)."""
    found = (values(text) if text is not None else None) or {}
    out: dict[str, object] = {}
    for key, spec in config_fields(section_class(section)).items():
        if isinstance(spec.metadata["validator"], Table):
            continue
        made = _make_field(section, key, spec)
        value = found.get(made.path, made.default)
        out[key] = made.default if made.problem(value) is not None else value
    return out


__all__ = ["ALL_SETTINGS", "BROKEN_TEXT", "CONFIG_FILENAME", "DEFAULT_TEXT", "Field", "HELPS",
           "KINDS", "LABELS", "LOOKS", "NOT_SET", "P2_PAGES", "PAGES", "Page", "PageDef", "Row", "SCHEMES",
           "Section",
           "TABLE_REASON", "TEXT_ONLY", "WidgetKind", "WidgetSpec", "all_keys", "is_look",
           "look_page", "look_title", "looks", "new_look_change", "new_look_problem",
           "on_looks_page", "style_names",
           "all_settings", "broken", "broken_message", "default_caption", "fields_by_path",
           "label_for", "page", "pages", "raw_default", "search", "section_title", "section_values",
           "table_paths", "text_only", "values", "widget_for"]
