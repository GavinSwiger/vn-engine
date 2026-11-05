"""Loading ``config.toml``: contained read, decoding, parsing, validation, line numbers.

Why this module exists: the author's first contact with the engine is usually a mistake in
``config.toml``, and every mistake must end in a clear message with the file, line, key,
and what was expected, never a stack trace (PR-F01-08..13). The file also comes from a
downloaded game folder, so reading it must stay inside the folder, be size-limited, and
never crash or hang on hostile input (SEC-F01-01, 07, 08).

``load_config`` collects **all** problems in one pass and returns valid values (defaults
for anything invalid), so the error screen can still show a valid ``[game] title``.
"""

import difflib
import logging
import re
import tomllib
from collections.abc import Iterable
from types import MappingProxyType

from engine.core.config_schema import (
    LOOK_SECTIONS,
    LOOK_WORDS_REFUSED,
    PLAYTHROUGH_AREAS,
    SECTIONS,
    STYLE_AREAS,
    Config,
    ConfigResult,
    PLUGIN_TABLE_DEPTH,
    PLUGIN_TABLE_KEYS_MAX,
    PLUGIN_TABLES_MAX,
    EntryMap,
    HexColor,
    LookTable,
    RawPluginTable,
    RawPluginTables,
    RawValue,
    Table,
    ThemeConfig,
    Validator,
    ValueProblem,
    config_fields,
    toml_key,
    word_fields,
)
from engine.core.minigame_types import PLUGIN_NAME_RE
from engine.core.constants import (
    CONFIG_FILENAME,
    CONFIG_MAX_BYTES,
    LOCATE_MAX_LINE_CHARS,
    PLAYTHROUGH_MAX,
    PLAYTHROUGH_TABLES_MAX,
    STATEMENT_WORDS,
    STYLE_NAME_RE,
    STYLES_MAX,
    VALUE_ECHO_MAX_CHARS,
)
from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
    ConfigError,
)
from engine.core.paths import GamePaths
from engine.core.redact import echo, escape_controls, truncate
from engine.core.schemes import DEFAULT_SCHEME, ROLES, SCHEMES, custom_colors, scheme_colors

# --- Messages (§7.2.1, §7.2.2) -----------------------------------------------------------

MSG_NOT_FOUND = "config.toml not found — using default settings"
MSG_OUTSIDE = ("config.toml points to a place outside the game folder, which is not allowed. "
               "Replace it with a normal file.")
MSG_NOT_FILE = "config.toml is not a normal file. Replace it with a text file."
MSG_TOO_LARGE = "config.toml is larger than 1 MB. Check that you opened the right file."
MSG_UNREADABLE = ("config.toml could not be read. Check that it is not open in another program "
                  "and that you may read it.")
MSG_NOT_UTF8 = "config.toml is not saved as UTF-8 text. Save it as UTF-8 in your editor."
MSG_TOO_DEEP = 'config.toml is nested too deeply (too many "[" or "{" inside each other)'
MSG_VALUE_TOO_LARGE = ("config.toml contains a value that is too large to read, such as a "
                       "number with thousands of digits")
MSG_TOO_COMPLEX = "config.toml is too large or complex to read"

MSG_MISSING_QUOTE = "text is missing its closing quote"

# tomllib message prefix → plain-language message (§7.2.2). "Illegal character" is
# decided separately: only an unterminated string gets the missing-quote message (I-1).
_DECODE_MESSAGES = (
    ("Invalid value", 'expected a value after "=". Text values need quotes: title = "My Game"'),
    ("Expected '=' after a key", 'expected "=" after the key name. Write settings as key = value'),
    ("Unclosed array", 'a "[" or "{" is never closed'),
    ("Unclosed inline table", 'a "[" or "{" is never closed'),
    ("Cannot overwrite a value", "this key or section is written twice"),
    ("Cannot declare", "this key or section is written twice"),
    ("Unterminated string", MSG_MISSING_QUOTE),
    ("Invalid statement", "this line is not a valid setting. Write settings as key = value"),
)

_POSITION_RE = re.compile(r"\(at line (\d+), column (\d+)\)\Z")
_END_OF_DOCUMENT = "(at end of document)"

_log = logging.getLogger("vn.config")


def load_config(paths: GamePaths) -> ConfigResult:
    """Read, parse, and validate ``config.toml`` in the game folder (§7.2).

    Never raises for problems in the file: a missing file gives defaults and one warning;
    every other problem is a ``ConfigError`` in ``errors``.
    """
    try:
        data = paths.read_file(CONFIG_FILENAME, max_bytes=CONFIG_MAX_BYTES)
    except AssetMissing as exc:
        if exc.suggestion is None:
            warning = MSG_NOT_FOUND
        else:
            warning = (f"config.toml not found — did you mean {echo(exc.suggestion)}? "
                       "Using default settings")
        return ConfigResult(Config(), [warning], [], loaded=False)
    except AssetRefError:
        return _failed(MSG_OUTSIDE)
    except AssetNotFile:
        return _failed(MSG_NOT_FILE)
    except AssetTooLarge:
        return _failed(MSG_TOO_LARGE)
    except AssetUnreadable:
        return _failed(MSG_UNREADABLE)

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _failed(MSG_NOT_UTF8)

    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:          # a ValueError, so it is caught first
        return _failed_with(map_decode_error(exc, text))
    except RecursionError:
        _log.debug("tomllib raised RecursionError", exc_info=True)
        return _failed(MSG_TOO_DEEP)
    except ValueError:
        _log.debug("tomllib raised ValueError", exc_info=True)
        return _failed(MSG_VALUE_TOO_LARGE)
    except MemoryError:
        _log.debug("tomllib raised MemoryError", exc_info=True)
        return _failed(MSG_TOO_COMPLEX)

    config, warnings, errors = _validate(doc, KeyLocator(text))
    return ConfigResult(config, warnings, errors, loaded=not errors)


def _failed(message: str) -> ConfigResult:
    """A whole-file problem: defaults and one error naming only ``config.toml``."""
    return _failed_with(ConfigError(message, file=CONFIG_FILENAME))


def _failed_with(error: ConfigError) -> ConfigResult:
    return ConfigResult(Config(), [], [error], loaded=False)


def map_decode_error(exc: tomllib.TOMLDecodeError, text: str) -> ConfigError:
    """Turn a tomllib error into a plain-language ``ConfigError`` with line and column
    (§7.2.2), including the end-of-file rule for ``(at end of document)``."""
    message = str(exc)
    line: int | None = None
    column: int | None = None
    position = _POSITION_RE.search(message)
    if position is not None:
        line, column = int(position.group(1)), int(position.group(2))
        prefix = message[:position.start()].rstrip()
    elif message.endswith(_END_OF_DOCUMENT):
        prefix = message[:-len(_END_OF_DOCUMENT)].rstrip()
        lines = text.splitlines()
        line, column = (len(lines), len(lines[-1]) + 1) if lines else (1, 1)
    else:
        prefix = message
    return ConfigError(_plain_decode_message(prefix, text, line, column),
                       file=CONFIG_FILENAME, line=line, column=column)


def _plain_decode_message(prefix: str, text: str, line: int | None,
                          column: int | None) -> str:
    if prefix.startswith("Illegal character"):
        char = _char_at(text, line, column)
        if char is None or char == "\n":
            return MSG_MISSING_QUOTE
        return f"this text contains a character that is not allowed (U+{ord(char):04X})"
    for start, plain in _DECODE_MESSAGES:
        if prefix.startswith(start):
            return plain
    return escape_controls(prefix)


def _char_at(text: str, line: int | None, column: int | None) -> str | None:
    """The character tomllib pointed at; a position past the end of a line is its newline.
    Positions count lines as tomllib does, after CRLF is normalized to LF."""
    if line is None or column is None:
        return None
    rows = text.replace("\r\n", "\n").split("\n")
    if not 1 <= line <= len(rows):
        return None
    row = rows[line - 1]
    return row[column - 1] if 1 <= column <= len(row) else "\n"


# --- Validation walk (§7.2.3) -------------------------------------------------------------

def _where(line: int | None) -> str:
    return f"config.toml, line {line}" if line is not None else "config.toml"


def _line_order(line: int | None) -> tuple[bool, int]:
    return (line is None, line or 0)


DID_YOU_MEAN_CUTOFF = 0.75


def did_you_mean(name: str, names: Iterable[str]) -> str | None:
    """The one did-you-mean rule for names an author wrote (unknown sections and keys here,
    F10's W66 for ``[title]``/``[quick_menu] entries``, F10 07 I-10): the closest of
    ``names`` by ``difflib`` with cutoff 0.75, or None."""
    close = difflib.get_close_matches(name, list(names), 1, DID_YOU_MEAN_CUTOFF)
    return close[0] if close else None


def _validate(doc: dict, locator: "KeyLocator") -> tuple[Config, list[str], list[ConfigError]]:
    walk = _Walk(locator)
    sections: dict[str, object] = {}
    doc = _with_scheme(doc, walk)                                         # F49

    for section, content in doc.items():
        if section in SECTIONS and isinstance(content, dict):
            sections[section] = walk.table(SECTIONS[section], content, (section,))
        elif section in LOOK_SECTIONS and isinstance(content, dict):          # F32
            sections[section] = walk.looks(section, content)
        elif isinstance(content, dict):
            line = locator.line_of(section)
            message = f"{_where(line)}: unknown section [{echo(section)}]"
            close = did_you_mean(section, [*SECTIONS, *LOOK_SECTIONS])
            if close is not None:
                message += f" — did you mean [{close}]?"
            walk.warnings.append((line, message))
        else:
            line = locator.line_of(section)
            walk.warnings.append((line, f'{_where(line)}: "{echo(section)}" must be inside a '
                                        "section such as [game]"))

    config = Config(**{name: sections.get(name, cls()) for name, cls in SECTIONS.items()},
                    **{name: sections[name] for name in LOOK_SECTIONS if name in sections})
    walk.errors.extend(_content_warning_errors(config, doc, locator))
    walk.warnings.sort(key=lambda item: _line_order(item[0]))
    walk.errors.sort(key=lambda error: _line_order(error.line))
    return config, [message for _, message in walk.warnings], walk.errors


# --- F49: color schemes (SPEC §5) ---------------------------------------------------------

def _with_scheme(doc: dict, walk: "_Walk") -> dict:
    """``doc`` with ``[theme] preset``'s scheme laid *under* the author's ``[theme]`` keys
    (F49 §5): a known id gives a copy whose ``theme`` table also holds every scheme color
    the author didn't set, as raw ``"#RRGGBB"`` text the walk then checks as usual; a path
    that meets a non-table is skipped (the walk reports that value). An unknown id warns
    once and is dropped from the copy, so the engine colors show. A value that isn't text
    is left for the walk's usual ``Choice`` error. ``doc`` itself is never changed.
    2026-11-05: the role colors of ``[theme.scheme]`` replace those of the preset's scheme
    (Sakura with no preset), as ``schemes.custom_colors``; the table stays for the walk."""
    theme = doc.get("theme")
    if not isinstance(theme, dict) or ("preset" not in theme and "scheme" not in theme):
        return doc
    preset: object = DEFAULT_SCHEME
    if "preset" in theme:
        preset = _scheme_id(theme["preset"], walk, ("theme", "preset"))
    roles = _scheme_roles(theme.get("scheme"))
    if preset is _NOT_TEXT and not roles:
        return doc
    out = dict(doc)
    table = theme
    if preset is None:
        table = {key: value for key, value in theme.items() if key != "preset"}
    if isinstance(preset, str) or roles:
        base = preset if isinstance(preset, str) else DEFAULT_SCHEME
        table = _merged_under(table, custom_colors(base, roles).items())
    out["theme"] = table
    return out


def _scheme_roles(table: object) -> dict[str, str]:
    """``[theme.scheme]``'s role colors written right (role → ``"#RRGGBB"``); a wrong one is
    left out here and reported by the walk."""
    if not isinstance(table, dict):
        return {}
    return {role: value for role, value in table.items() if role in ROLES
            and isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value)}


_NOT_TEXT = object()


def _scheme_id(value: object, walk: "_Walk", path: tuple[str, ...]) -> object:
    """A ``preset`` value: its id when it names a scheme; None (after the unknown-scheme
    warning) for other text; ``_NOT_TEXT`` for a value that isn't text."""
    if type(value) is not str:
        return _NOT_TEXT
    if value in SCHEMES:
        return value
    line = walk.locator.line_of(*path)
    label = f"[{'.'.join(path[:-1])}] {path[-1]}"
    message = f'{_where(line)}: unknown color scheme "{echo(value)}" in {label}'
    close = did_you_mean(value, SCHEMES)
    if close is not None:
        message += f' — did you mean "{close}"?'
    else:
        message += ". Use one of " + ", ".join(f'"{key}"' for key in SCHEMES) + "."
    walk.warnings.append((line, message))
    return None


def _merged_under(table: dict, colors: Iterable[tuple[str, str]]) -> dict:
    """A copy of ``table`` with each dotted ``path`` → value set where the author set
    nothing; ``table``'s own tables are copied, never changed."""
    out = _copy_tables(table)
    for path, value in colors:
        node = out
        *heads, key = path.split(".")
        for head in heads:
            child = node.setdefault(head, {})
            if not isinstance(child, dict):
                break                   # a non-table on the path: the walk reports it
            node = child
        else:
            node.setdefault(key, value)
    return out


def _copy_tables(table: dict) -> dict:
    """``table`` with every nested table copied (values are shared; they are immutable or
    never changed)."""
    return {key: _copy_tables(value) if isinstance(value, dict) else value
            for key, value in table.items()}


def _content_warning_errors(config: Config, doc: dict,
                            locator: "KeyLocator") -> list[ConfigError]:
    """F33's one cross-key check (SR-F33-03, 07 I-4), at ``show``'s line: a valid ``show``
    other than ``"never"`` needs a ``text`` with a visible character. A ``text`` refused by
    its own validator already has its error, so it gives none here."""
    warning = config.content_warning
    raw = doc.get("content_warning")
    if warning.show == "never" or not isinstance(raw, dict):
        return []
    if warning.text.strip() or raw.get("text", "") != warning.text:
        return []
    return [ConfigError(f'[content_warning] text must be set when show is "{warning.show}", '
                        "but found nothing", file=CONFIG_FILENAME,
                        line=locator.line_of("content_warning", "show"))]


# F32 (01 §5.2 "Config errors"): a look table's name, area, and word errors.
_LOOK_NAME_TEXTS = {
    "style": ("isn't a usable style name. Use lower-case letters, digits, and _, starting "
              "with a letter, up to 32 characters, and not off."),
    "playthrough": f"must be a whole number from 0 to {PLAYTHROUGH_MAX}.",
}
_LOOK_AREA_TEXTS = {
    "style": ("isn't something a style can change. A style can change textbox, choice, nvl, "
              "and quick_menu."),
    "playthrough": ("isn't something a playthrough look can change. It can change title; use "
                    "a style for the rest."),
}
_LOOK_KINDS = {"style": "a style", "playthrough": "a playthrough look"}
_PLAYTHROUGH_KEY_RE = re.compile(r"0|[1-9][0-9]?", re.ASCII)       # 0 to PLAYTHROUGH_MAX


def _look_key(section: str, name: str) -> str | int | None:
    """A table's key in ``Config.style`` (the name) or ``Config.playthrough`` (N), or None
    when ``name`` isn't usable (SR-F32-07): a style name is ``STYLE_NAME_RE``, not ``off``,
    and not a reserved word; N is a whole number 0–99 written without leading zeros."""
    if section == "style":
        usable = (STYLE_NAME_RE.fullmatch(name) is not None and name != "off"
                  and name not in STATEMENT_WORDS)
        return name if usable else None
    return int(name) if _PLAYTHROUGH_KEY_RE.fullmatch(name) is not None else None


class _Walk:
    """One validation pass: sections and the nested ``Table``/``EntryMap`` values in them
    (F04 §7.8). Every label comes from the section path, every line from ``locator``."""

    def __init__(self, locator: "KeyLocator") -> None:
        self.locator = locator
        self.warnings: list[tuple[int | None, str]] = []
        self.errors: list[ConfigError] = []

    def table(self, cls: type, content: dict, path: tuple[str, ...]) -> object:
        """``cls`` built from the valid keys of ``content``; defaults for the rest."""
        label = ".".join(path)
        # Only fields with a validator are keys; the others are not read yet (``Table``).
        fields = config_fields(cls)
        values: dict[str, object] = {}
        for key, value in content.items():
            line = self.locator.line_of(*path, key)
            field = fields.get(key)
            if field is None:
                self.unknown(line, label, key, fields)
                continue
            validator: Validator = field.metadata["validator"]
            if isinstance(value, dict) and isinstance(validator, Table):
                values[field.name] = self.table(validator.cls, value, path + (key,))
            elif isinstance(value, dict) and isinstance(validator, EntryMap):
                values[field.name] = self.entry_map(validator, value, path + (key,))
            elif isinstance(value, dict) and isinstance(validator, RawPluginTables):
                values[field.name] = self.raw_tables(validator, value, path + (key,))
            else:
                try:
                    values[field.name] = validator.check(value)
                except ValueProblem:
                    self.error(line, f"[{label}] {key}", validator, value)
        return cls(**values)

    def entry_map(self, validator: EntryMap, content: dict, path: tuple[str, ...]) -> object:
        """The valid entries of ``content`` over ``validator.base``, read-only. Too many
        entries give one error (at the table's line) and ``base`` alone."""
        label = ".".join(path)
        if len(content) > validator.max_entries:
            self.errors.append(ConfigError(
                f"[{'.'.join(path[:-1])}] {path[-1]} must have at most "
                f"{validator.max_entries} entries, but found {len(content)}",
                file=CONFIG_FILENAME, line=self.locator.line_of(*path)))
            return validator.base
        entries = dict(validator.base)
        for key, value in content.items():
            line = self.locator.line_of(*path, key)
            name = f"[{label}] {validator.label(key)}"
            try:
                stored_key = validator.key_check.check(key)
            except ValueProblem:
                self.errors.append(ConfigError(
                    f"{name} must be {validator.key_check.expected}, "
                    f'but found "{echo(key, VALUE_ECHO_MAX_CHARS)}"',
                    file=CONFIG_FILENAME, line=line))
                continue
            try:
                entries[stored_key] = validator.value_validator.check(value)
            except ValueProblem:
                self.error(line, name, validator.value_validator, value)
        return MappingProxyType(entries)

    def raw_tables(self, validator: RawPluginTables, content: dict,
                   path: tuple[str, ...]) -> object:
        """F23 ``04`` §7.9: ``[theme.plugin]`` / ``[words.plugin]`` stored raw, with lines;
        only the bounds are checked here (``RawPluginTables``). A name or table that breaks
        them gives one error and is left out."""
        label = ".".join(path)
        if len(content) > PLUGIN_TABLES_MAX:
            self.errors.append(ConfigError(
                f"[{label}] must have at most {PLUGIN_TABLES_MAX} minigame tables, but found "
                f"{len(content)}", file=CONFIG_FILENAME, line=self.locator.line_of(*path)))
            return MappingProxyType({})
        tables: dict[str, RawPluginTable] = {}
        for name, table in content.items():
            line = self.locator.line_of(*path, name)
            if PLUGIN_NAME_RE.fullmatch(name) is None:
                self.errors.append(ConfigError(
                    f"[{label}] {toml_key(name)} must be {validator.name_expected}, but found "
                    f'"{echo(name, VALUE_ECHO_MAX_CHARS)}"', file=CONFIG_FILENAME, line=line))
                continue
            if not isinstance(table, dict):
                self.errors.append(ConfigError(
                    f"[{label}] {name} must be a section, such as [{label}.{name}], but found "
                    f"{describe(table)}", file=CONFIG_FILENAME, line=line))
                continue
            values: dict[str, RawValue] = {}
            if self._raw_values(validator, table, path + (name,), (), values):
                tables[name] = RawPluginTable(line, MappingProxyType(values))
        return MappingProxyType(tables)

    def _raw_values(self, validator: RawPluginTables, table: dict, path: tuple[str, ...],
                    keys: tuple[str, ...], out: dict[str, RawValue]) -> bool:
        """Flatten one table below a minigame name into ``out``; False on a bound error."""
        label = ".".join(path + keys)
        if len(table) > PLUGIN_TABLE_KEYS_MAX:
            self.errors.append(ConfigError(
                f"[{label}] must have at most {PLUGIN_TABLE_KEYS_MAX} keys, but found "
                f"{len(table)}", file=CONFIG_FILENAME, line=self.locator.line_of(*path, *keys)))
            return False
        ok = True
        for key, value in table.items():
            line = self.locator.line_of(*path, *keys, key)
            if isinstance(value, dict):
                if len(keys) + 1 >= PLUGIN_TABLE_DEPTH:
                    self.errors.append(ConfigError(
                        f"[{label}.{toml_key(key)}] is nested too deeply: a minigame's tables "
                        f"go at most {PLUGIN_TABLE_DEPTH - 1} level below its name, such as "
                        f"[{'.'.join(path)}.card]", file=CONFIG_FILENAME, line=line))
                    ok = False
                    continue
                ok = self._raw_values(validator, value, path, keys + (key,), out) and ok
            elif type(value) in (str, int, float, bool):
                out[".".join(keys + (key,))] = RawValue(value, line)
            else:
                self.errors.append(ConfigError(
                    f"[{label}] {toml_key(key)} must be {validator.value_expected}, but found "
                    f"{describe(value)}", file=CONFIG_FILENAME, line=line))
                ok = False
        return ok

    # --- F32: [style.<name>] and [playthrough.N] (04 §6.1) --------------------------------

    def looks(self, section: str, content: dict) -> object:
        """The valid tables of ``[style]`` (by name) or ``[playthrough]`` (by N), read-only.
        Too many tables give one error and none is read; a bad name skips its table. A table
        with errors keeps its valid keys (the launch stops anyway)."""
        limit = STYLES_MAX if section == "style" else PLAYTHROUGH_TABLES_MAX
        if len(content) > limit:
            self.errors.append(ConfigError(
                f"there are {len(content)} [{section}] tables, but at most {limit} are "
                "allowed.", file=CONFIG_FILENAME, line=self.locator.line_of(section)))
            return MappingProxyType({})
        tables: dict[object, LookTable] = {}
        for name, table in content.items():
            path = (section, name)
            line = self.locator.line_of(*path)
            key = _look_key(section, name)
            if key is None:
                self.errors.append(ConfigError(f"[{section}.{toml_key(name)}] "
                                               + _LOOK_NAME_TEXTS[section],
                                               file=CONFIG_FILENAME, line=line))
                continue
            if not isinstance(table, dict):
                self.errors.append(ConfigError(
                    f"[{section}] {name} must be a section, such as [{section}.{name}], but "
                    f"found {describe(table)}", file=CONFIG_FILENAME, line=line))
                continue
            tables[key] = self._look_table(section, table, path, line)
        return MappingProxyType(tables)

    def _look_table(self, section: str, content: dict, path: tuple[str, ...],
                    line: int | None) -> LookTable:
        label = ".".join(path)
        fields = config_fields(LOOK_SECTIONS[section])
        tokens: dict[str, object] = {}
        words: dict[str, str] = {}
        entries = None
        preset: str | None = None
        for key, value in content.items():
            key_line = self.locator.line_of(*path, key)
            found = fields.get(key)
            if found is None:
                self.unknown(key_line, label, key, fields)
                continue
            validator: Validator = found.metadata["validator"]
            if not isinstance(validator, Table):                # title_entries
                try:
                    entries = validator.check(value)
                except ValueProblem:
                    self.error(key_line, f"[{label}] {key}", validator, value)
            elif not isinstance(value, dict):
                self.error(key_line, f"[{label}] {key}", validator, value)
            elif key == "theme":
                preset = self._look_theme(section, value, path + (key,), tokens)
            else:
                self._look_words(section, value, path + (key,), words)
        return LookTable(MappingProxyType(tokens), MappingProxyType(words), entries, line,
                         preset)

    def _look_theme(self, section: str, content: dict, path: tuple[str, ...],
                    out: dict[str, object]) -> str | None:
        """Each allowed area's set tokens into ``out`` as ``"area.key"`` paths. F49: a
        style's ``preset`` is read before the area check; a known one then adds every
        scheme color outside ``title`` the style didn't set, and its id is returned. (A
        playthrough table's ``preset`` gets the usual area error.)"""
        label = ".".join(path)
        areas = STYLE_AREAS if section == "style" else PLAYTHROUGH_AREAS
        theme_fields = config_fields(ThemeConfig)
        preset: str | None = None
        for area, value in content.items():
            line = self.locator.line_of(*path, area)
            if area == "preset" and section == "style":
                found = _scheme_id(value, self, path + (area,))
                if found is _NOT_TEXT:
                    self.error(line, f"[{label}] {area}",
                               theme_fields[area].metadata["validator"], value)
                elif found is not None:
                    preset = found                                   # type: ignore[assignment]
                continue
            if area not in areas:
                self.errors.append(ConfigError(f"[{label}.{toml_key(area)}] "
                                               + _LOOK_AREA_TEXTS[section],
                                               file=CONFIG_FILENAME, line=line))
                continue
            validator = theme_fields[area].metadata["validator"]
            if isinstance(value, dict):
                self.sparse(validator.cls, value, path + (area,), area + ".", out)
            else:
                self.error(line, f"[{label}] {area}", validator, value)
        if preset is not None:
            color = HexColor()
            for token, value in scheme_colors(preset).items():
                if not token.startswith("title."):                   # D2: never the title
                    out.setdefault(token, color.check(value))
        return preset

    def _look_words(self, section: str, content: dict, path: tuple[str, ...],
                    out: dict[str, str]) -> None:
        """Each word key's text into ``out``; F30's words and ``plugin`` are refused."""
        label = ".".join(path)
        fields = word_fields()
        for key, value in content.items():
            line = self.locator.line_of(*path, key)
            if key in LOOK_WORDS_REFUSED or key == "plugin":
                self.errors.append(ConfigError(
                    f"[{label}] {key} can't be changed by {_LOOK_KINDS[section]}. "
                    + ("Minigame words come only from [words.plugin]." if key == "plugin" else
                       "Fake-crash and user-name words come only from [words]."),
                    file=CONFIG_FILENAME, line=line))
                continue
            found = fields.get(key)
            if found is None:
                self.unknown(line, label, key, fields)
                continue
            validator: Validator = found.metadata["validator"]
            try:
                out[key] = validator.check(value)
            except ValueProblem:
                self.error(line, f"[{label}] {key}", validator, value)

    def sparse(self, cls: type, content: dict, path: tuple[str, ...], prefix: str,
               out: dict[str, object]) -> None:
        """``table`` without defaults (F32 04 §6.1 step 4): the same unknown-key warning and
        validators, labelled with the full path; each valid value goes to ``out`` under
        ``prefix + key``, and nested ``Table`` fields recurse."""
        label = ".".join(path)
        fields = config_fields(cls)
        for key, value in content.items():
            line = self.locator.line_of(*path, key)
            found = fields.get(key)
            if found is None:
                self.unknown(line, label, key, fields)
                continue
            validator: Validator = found.metadata["validator"]
            if isinstance(value, dict) and isinstance(validator, Table):
                self.sparse(validator.cls, value, path + (key,), f"{prefix}{key}.", out)
                continue
            try:
                out[prefix + key] = validator.check(value)
            except ValueProblem:
                self.error(line, f"[{label}] {key}", validator, value)

    def unknown(self, line: int | None, label: str, key: str, names: Iterable[str]) -> None:
        """The unknown-key warning, with a did-you-mean from ``names``."""
        message = f"{_where(line)}: unknown key [{label}] {echo(key)}"
        close = did_you_mean(key, names)
        if close is not None:
            message += f' — did you mean "{close}"?'
        self.warnings.append((line, message))

    def error(self, line: int | None, name: str, validator: Validator, value: object) -> None:
        """``<name> must be <phrase>, but found <value>[. Remove the quotes.]`` (§7.2.3)."""
        self.errors.append(ConfigError(value_problem_text(name, validator, value),
                                       file=CONFIG_FILENAME, line=line))


def value_problem_text(name: str, validator: Validator, value: object) -> str:
    """The one invalid-value text, ``<name> must be <phrase>, but found <value>[. Remove the
    quotes.]`` (§7.2.3); also F23's plugin tables, checked after the plugins load."""
    found = validator.found(value)          # F30's OneLine: "it has 2 lines."
    if found is not None:
        return f"{name} must be {validator.expected}, but {found}"
    return (f"{name} must be {validator.expected}, "
            f"but found {describe(value)}{_quotes_hint(value, validator)}")


def describe(value: object) -> str:
    """How a config value is shown after "but found" (§7.2.3 step 5). Every type is cut to
    40 characters (SEC-F01-07 (c)); text is redacted and escaped first."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'the text "{echo(value, VALUE_ECHO_MAX_CHARS)}"'
    if isinstance(value, int):
        return truncate(str(value), VALUE_ECHO_MAX_CHARS)
    if isinstance(value, float):
        return truncate(repr(value), VALUE_ECHO_MAX_CHARS)
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "a section"
    return "a date or time"          # the only other types tomllib produces


_DECIMAL_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", re.ASCII)


def _quotes_hint(value: object, validator: Validator) -> str:
    """``. Remove the quotes.`` when the unquoted text would be valid (§7.2.3 step 6):
    true/false, a whole number, or a decimal number such as ``"0.85"`` or ``"1.5"`` (for
    ``Opacity`` and ``Seconds``). Only for strings of at most 20 characters
    (SEC-F01-07 (d))."""
    if type(value) is not str or len(value) > 20:
        return ""
    if value in ("true", "false"):
        unquoted: object = value == "true"
    else:
        try:
            unquoted = int(value)
        except ValueError:
            if _DECIMAL_RE.fullmatch(value) is None:
                return ""
            unquoted = float(value)
    try:
        validator.check(unquoted)
    except ValueProblem:
        return ""
    return ". Remove the quotes."


# --- Line numbers (§7.2.5) ----------------------------------------------------------------

_BARE_KEY_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
_BASIC_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


class KeyLocator:
    """Line-tracking TOML scan (§7.2.5). Built once per load, lazily."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._first_seen: dict[tuple[str, ...], int] | None = None

    def line_of(self, *path: str) -> int | None:
        """1-based line where the table or key path was first defined, e.g.
        line_of('window') or line_of('window', 'width'); None only if absent."""
        if self._first_seen is None:
            self._first_seen = _KeyScan(self._text).run()
        return self._first_seen.get(path)


class _KeyScan:
    """One forward pass over the characters of a TOML text that tomllib accepted.

    No regular expressions; each character is visited a bounded number of times, so the
    scan is O(len(text)) (SEC-F01-08). Keys and headers are recognized only in the first
    ``LOCATE_MAX_LINE_CHARS`` characters of a line, but strings are tracked everywhere, so
    the string state and later line numbers stay correct.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0
        self.line = 1
        self.line_start = 0
        self.first_seen: dict[tuple[str, ...], int] = {}

    def run(self) -> dict[tuple[str, ...], int]:
        text, n = self.text, self.n
        table: tuple[str, ...] = ()
        ctx: list[tuple[str, tuple[str, ...]]] = []     # ('{' or '[', base key path)
        expect_key = True
        value_key: tuple[str, ...] = ()
        while self.i < n:
            i = self.i
            c = text[i]
            if c == "\n":
                self._newline(i)
                self.i = i + 1
                if not ctx:
                    expect_key = True
                continue
            if c in " \t\r":
                self.i = i + 1
                continue
            if c == "#":
                end = text.find("\n", i)
                self.i = n if end < 0 else end
                continue
            if c in "\"'" and text.startswith(c * 3, i):
                self._skip_multiline_string(c)
                continue
            if expect_key and i - self.line_start < LOCATE_MAX_LINE_CHARS:
                if c == "[" and not ctx:
                    self.i = i + (2 if text.startswith("[[", i) else 1)
                    table = self._read_key_path()
                    self._record(table)
                    end = text.find("\n", self.i)
                    self.i = n if end < 0 else end
                    continue
                if c in _BARE_KEY_CHARS or c in "\"'":
                    base = ctx[-1][1] if ctx else table
                    value_key = base + self._read_key_path()
                    self._record(value_key)
                    expect_key = False
                    continue
            if c in "\"'":
                self._skip_string(c)
                continue
            if c == "{":
                ctx.append(("{", value_key))
                expect_key = True
            elif c == "[":
                ctx.append(("[", value_key))
                expect_key = False
            elif c in "}]":
                if ctx:
                    ctx.pop()
                expect_key = False
            elif c == ",":
                expect_key = bool(ctx) and ctx[-1][0] == "{"
            self.i = i + 1
        return self.first_seen

    def _newline(self, index: int) -> None:
        self.line += 1
        self.line_start = index + 1

    def _record(self, path: tuple[str, ...]) -> None:
        """Record the path and every prefix of it at the current line (first one wins)."""
        for length in range(1, len(path) + 1):
            self.first_seen.setdefault(path[:length], self.line)

    def _skip_blanks(self) -> None:
        while self.i < self.n and self.text[self.i] in " \t":
            self.i += 1

    def _read_key_path(self) -> tuple[str, ...]:
        """Read ``part(.part)*`` where a part is bare or a one-line quoted string."""
        text, n = self.text, self.n
        parts: list[str] = []
        while True:
            self._skip_blanks()
            if self.i >= n:
                break
            c = text[self.i]
            if c == '"':
                parts.append(self._read_basic_key())
            elif c == "'":
                parts.append(self._read_literal_key())
            else:
                start = self.i
                while self.i < n and text[self.i] in _BARE_KEY_CHARS:
                    self.i += 1
                parts.append(text[start:self.i])
            self._skip_blanks()
            if self.i < n and text[self.i] == ".":
                self.i += 1
                continue
            break
        return tuple(parts)

    def _read_basic_key(self) -> str:
        """A one-line basic string, decoded, so quoted keys match tomllib's keys."""
        text, n = self.text, self.n
        self.i += 1
        out: list[str] = []
        while self.i < n:
            c = text[self.i]
            if c == '"':
                self.i += 1
                break
            if c == "\n":
                break
            if c == "\\" and self.i + 1 < n:
                escape = text[self.i + 1]
                if escape in _BASIC_ESCAPES:
                    out.append(_BASIC_ESCAPES[escape])
                    self.i += 2
                elif escape in "uU":
                    width = 4 if escape == "u" else 8
                    digits = text[self.i + 2:self.i + 2 + width]
                    try:
                        out.append(chr(int(digits, 16)))
                    except ValueError:
                        pass
                    self.i += 2 + width
                else:
                    out.append(escape)
                    self.i += 2
                continue
            out.append(c)
            self.i += 1
        return "".join(out)

    def _read_literal_key(self) -> str:
        text = self.text
        start = self.i + 1
        line_end = text.find("\n", start)
        line_end = self.n if line_end < 0 else line_end
        close = text.find("'", start, line_end)
        end = line_end if close < 0 else close
        self.i = end + 1 if close >= 0 else end
        return text[start:end]

    def _skip_string(self, quote: str) -> None:
        """Skip a one-line string value (basic strings honor backslash escapes)."""
        text, n = self.text, self.n
        i = self.i + 1
        if quote == "'":
            line_end = text.find("\n", i)
            line_end = n if line_end < 0 else line_end
            close = text.find("'", i, line_end)
            self.i = line_end if close < 0 else close + 1
            return
        while i < n:
            c = text[i]
            if c == "\\":
                i += 2
                continue
            if c == '"':
                i += 1
                break
            if c == "\n":
                break
            i += 1
        self.i = i

    def _skip_multiline_string(self, quote: str) -> None:
        """Skip a ``\"\"\"`` or ``'''`` string, counting every newline in it."""
        text, n = self.text, self.n
        delimiter = quote * 3
        i = self.i + 3
        while i < n:
            c = text[i]
            if c == "\n":
                self._newline(i)
                i += 1
                continue
            if c == "\\" and quote == '"':
                if i + 1 < n and text[i + 1] == "\n":
                    self._newline(i + 1)
                i += 2
                continue
            if text.startswith(delimiter, i):
                i += 3
                extra = 0
                while extra < 2 and i < n and text[i] == quote:   # up to 2 quotes of content
                    i += 1
                    extra += 1
                break
            i += 1
        self.i = i
