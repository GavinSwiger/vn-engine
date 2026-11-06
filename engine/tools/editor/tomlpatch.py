"""The shared ``config.toml`` key writer: set or remove one key as a plan of line edits (F47
``04-technical.md`` §7.2, PR-F47-04, AC-F47-18; F42 PR-F42-09, AC-F42-14, SEC-F42-13).

Why this module exists: ``config.toml`` is hand-written and commented, and it stays the only
truth, so Game settings (F47) and the Build dialog (F42) never rewrite the file. They plan
the few lines one key needs, guarded by those lines' old texts, and the caller checks the
plan (``verify``) against the live editor text before applying it as one undo step
(``TomlPlan.as_plan`` gives F46's ``scriptedit.Plan`` shape). Pure: no Tk, no file access.

- Works on the editor's LF text (``ScriptDocument.text``: no final break); ``document.encode``
  gives the file its line endings and BOM again, so those are kept.
- Set: an existing key keeps its key text, spacing and trailing comment; only the value span
  changes (a multi-line value is one span). Else a commented ``# key = …`` line under the
  **live** section header becomes the key (F42's ``# id``); one under a commented header
  (``# [content_warning]``) is left alone. Else the key goes after the section's last key
  line, or right under its header; with no header, ``[section]`` and the key are appended.
- Remove ("Use default"): the key's lines go; the header stays (unless ``drop_empty`` and
  nothing but blank lines would stay under it).
- The text's end: an edit that reaches it keeps the text's ending (a final break when it
  had one, never a pile of blank lines), so config.toml keeps exactly one final newline.
- Refused (``scriptedit.Refuse``): a broken or too large document, a key that isn't a
  ``config_schema`` setting, a value its validator refuses, and shapes this writer can't
  change safely: a key inside an inline table or an array of tables (``[[…]]``), or a key
  that is itself a table.
- Values are written by ``toml_literal``: strings as TOML basic strings with ``"``, ``\\``
  and every control escaped (SEC-F42-13). Every plan is checked by ``verify`` before it is
  returned, and ``verify`` is the gate every caller (F47 Settings, F42 Build) passes to
  ``apply_plan``: the new text must parse with ``tomllib`` to exactly the old document with
  the planned changes applied (set: that value; remove: absent, and a table only that
  removal emptied may go too; a new section may appear) and nothing else, and the schema
  validator must accept each value (F42 ``07`` I-8, SEC-F42-13). ``[window] icon`` must also
  pass ``check_ref``.
- Several keys as one undo step (F42's Build: title, version, id, icon): ``plan_changes``
  plans them one after another and returns one plan whose single edit spans the changed
  lines; ``verify`` checks all of them.
"""

import copy
import math
import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from engine.core.config_schema import (
    EntryMap, HexColor, RawPluginTables, Table, Validator, ValueProblem, config_fields,
    section_class)
from engine.core.constants import CONFIG_FILENAME, CONFIG_MAX_BYTES
from engine.core.errors import AssetRefError
from engine.core.paths import check_ref
from engine.tools.editor.scriptedit import (
    FIX_FIRST, UNSAFE, FilePlan, LineEdit, Plan, Refuse, apply_lines)

# --- Texts (F47 01 §6.4) -------------------------------------------------------------------

COMPLEX: Final = "This one is written in a way the form can't edit."
NOT_A_SETTING: Final = "[{section}] {key} isn't a config.toml setting."
BAD_VALUE: Final = "[{section}] {key} must be {expected}."
SET_TITLE: Final = "Change [{section}] {key}"
REMOVE_TITLE: Final = "Use the default for [{section}] {key}"
CHANGES_TITLE: Final = "Change config.toml"

# Settings whose value is a game-folder ref: it must also pass ``check_ref`` (SEC-F42-13).
_REF_KEYS: Final = frozenset({("window", "icon")})

Path_ = tuple[str, ...]

_BARE: Final = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
_KEY_PART: Final = r"""(?:[A-Za-z0-9_-]+|"(?:[^"\\\n]|\\.)*"|'[^'\n]*')"""
_KEY: Final = re.compile(rf"{_KEY_PART}(?:[ \t]*\.[ \t]*{_KEY_PART})*")
_AT_LINE: Final = re.compile(r"at line (\d+)")
_NAMED_ESCAPES: Final = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r",
                         '"': '\\"', "\\": "\\\\"}


# --- The plan ----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TomlPlan:
    """One key set (``value`` as ``tomllib`` reads it back) or removed (``value`` None);
    ``more`` holds further ``(section, key, value)`` changes of a ``plan_changes`` plan."""

    title: str
    ref: str
    section: str                                      # dotted: "theme.textbox"
    key: str
    value: Any
    edits: tuple[LineEdit, ...]                       # one, non-overlapping
    guards: tuple[tuple[int, str], ...]               # (line, old text) the plan read
    select: tuple[int, int, int] | None = None        # (line, col0, col1): the new value
    more: tuple[tuple[str, str, Any], ...] = ()       # plan_changes: the other changes

    @property
    def removed(self) -> bool:
        return self.value is None

    @property
    def changes(self) -> tuple[tuple[str, str, Any], ...]:
        """Every ``(section, key, value)`` this plan makes (value None: removed)."""
        return ((self.section, self.key, self.value), *self.more)

    def as_plan(self) -> Plan:
        """F46's plan shape for the window's document API (one undo step); its chunk guards
        are empty because ``verify`` (this module's) is the gate."""
        return Plan(self.title, (FilePlan(self.ref, (), self.edits, self.select),))


# --- Values ------------------------------------------------------------------------------

def _basic(text: str) -> str:
    """``text`` as a one-line TOML basic string: ``"``, ``\\`` and every control escaped."""
    out = ['"']
    for char in text:
        code = ord(char)
        if char in _NAMED_ESCAPES:
            out.append(_NAMED_ESCAPES[char])
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        elif 0xD800 <= code <= 0xDFFF:
            raise ValueError("lone surrogate")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def toml_literal(value: object, validator: Validator | None = None) -> str:
    """``value`` as TOML value text. Takes ``tomllib``'s types (str, int, float, bool, list)
    and what validators store: a ``HexColor``'s ``(r, g, b)`` is written ``"#RRGGBB"``, other
    tuples as arrays. Raises ValueError for anything TOML can't hold (nan, inf, None, dicts,
    lone surrogates)."""
    if isinstance(validator, HexColor) and isinstance(value, tuple) and len(value) == 3 \
            and all(type(c) is int and 0 <= c <= 255 for c in value):
        return _basic("#{:02X}{:02X}{:02X}".format(*value))
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("not a finite number")
        text = repr(value)
        return text if any(c in text for c in ".e") else text + ".0"
    if type(value) is str:
        return _basic(value)
    if type(value) in (list, tuple):
        return "[" + ", ".join(toml_literal(item) for item in value) + "]"   # type: ignore[union-attr]
    raise ValueError(f"can't write a {type(value).__name__}")


def _check_value(section: str, key: str, validator: Validator, value: Any) -> None:
    """The schema validator's check, plus ``check_ref`` for ref settings (SEC-F42-13).
    Raises ValueProblem, AssetRefError or ValueError."""
    validator.check(value)
    if (section, key) in _REF_KEYS:
        if type(value) is not str:
            raise ValueError("not a ref")
        check_ref(value)


def _key_text(part: str) -> str:
    return part if _BARE.fullmatch(part) else _basic(part)


def validator_for(section: str, key: str) -> Validator | None:
    """The validator of the setting ``[section] key`` (a value key of a section or table,
    or an entry of an ``EntryMap`` like ``[stage.positions]``), else None."""
    cls = section_class(section)
    if cls is not None:
        found = config_fields(cls).get(key)
        validator = found.metadata["validator"] if found is not None else None
        return None if isinstance(validator, (Table, EntryMap, RawPluginTables)) else validator
    parent, _, name = section.rpartition(".")
    owner = section_class(parent) if parent else None
    found = config_fields(owner).get(name) if owner is not None else None
    validator = found.metadata["validator"] if found is not None else None
    if not isinstance(validator, EntryMap):
        return None
    try:
        validator.key_check.check(key)
    except ValueProblem:
        return None
    return validator.value_validator


# --- Reading the lines (§7.2 step 1) -----------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Key:
    path: Path_                                       # header parts + key parts
    first: int                                        # 1-based lines of the whole span
    last: int
    value_col: int                                    # in line ``first`` (uncommented)
    end_col: int                                      # value end in line ``last``
    live: bool                                        # False: a ``# key = …`` line
    line: str                                         # line ``first`` (uncommented)


@dataclass(frozen=True, slots=True)
class _Header:
    path: Path_
    line: int
    array: bool


@dataclass(frozen=True, slots=True)
class _Index:
    headers: tuple[_Header, ...]
    keys: tuple[_Key, ...]
    count: int


def _decode_key(text: str) -> Path_:
    """The parts of key text (``a."b c".d``), read by ``tomllib`` itself."""
    node: Any = tomllib.loads(text + " = 0")
    parts: list[str] = []
    while isinstance(node, dict):
        (name, node), = node.items()
        parts.append(name)
    return tuple(parts)


def _header_at(body: str) -> tuple[Path_, bool] | None:
    """(path, array) when ``body`` (a line without its indent) is a table header."""
    array = body.startswith("[[")
    start = 2 if array else 1
    pos = len(body[start:]) - len(body[start:].lstrip(" \t")) + start
    match = _KEY.match(body, pos)
    if match is None:
        return None
    rest = body[match.end():].lstrip(" \t")
    close = "]]" if array else "]"
    if not rest.startswith(close):
        return None
    tail = rest[len(close):].lstrip(" \t")
    if tail and not tail.startswith("#"):
        return None
    try:
        return _decode_key(match.group()), array
    except tomllib.TOMLDecodeError:
        return None


def _key_at(line: str, pos: int) -> tuple[Path_, int] | None:
    """(key parts, value column) for a ``key = value`` line whose key starts at ``pos``."""
    match = _KEY.match(line, pos)
    if match is None:
        return None
    rest = line[match.end():]
    after = rest.lstrip(" \t")
    if not after.startswith("="):
        return None
    col = match.end() + len(rest) - len(after) + 1
    col += len(line[col:]) - len(line[col:].lstrip(" \t"))
    try:
        return _decode_key(match.group()), col
    except tomllib.TOMLDecodeError:
        return None


def _value_end(lines: Sequence[str], first: int, col: int) -> tuple[int, int]:
    """(0-based last line, end column) of the value starting at ``lines[first][col]``:
    strings (one- and multi-line), arrays and inline tables across lines, comments."""
    i, depth = first, 0
    while i < len(lines):
        line = lines[i]
        stop = len(line)
        while col < len(line):
            char = line[col]
            if line.startswith(('"""', "'''"), col):
                quote = line[col:col + 3]
                col += 3
                while True:
                    line = lines[i]
                    if quote == '"""' and line.startswith("\\", col) and col + 1 < len(line):
                        col += 2
                        continue
                    if line.startswith(quote, col):
                        col += 3
                        while col < len(line) and line[col] == quote[0]:
                            col += 1
                        break
                    if col >= len(line):
                        i, col = i + 1, 0
                        if i >= len(lines):
                            raise ValueError("unclosed string")
                        continue
                    col += 1
                stop = len(line)
                continue
            if char in "\"'":
                col += 1
                while col < len(line) and line[col] != char:
                    col += 2 if char == '"' and line[col] == "\\" else 1
                col += 1
                continue
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
            elif char == "#":
                stop = col
                break
            col += 1
        if depth == 0:
            return i, len(line[:stop].rstrip(" \t"))
        i, col = i + 1, 0
    raise ValueError("unclosed value")


def _commented_key(line: str) -> tuple[str, Path_, int, int] | None:
    """(uncommented line, key parts, value column, end column) for ``# key = <value>``
    whose value is one line of TOML; prose comments give None."""
    indent = line[:len(line) - len(line.lstrip(" \t"))]
    body = line[len(indent) + 1:].lstrip(" \t")
    text = indent + body
    found = _key_at(text, len(indent))
    if found is None:
        return None
    parts, col = found
    try:
        tomllib.loads("v = " + text[col:])
        _, end = _value_end([text], 0, col)
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    return text, parts, col, end


def _index(lines: Sequence[str]) -> _Index:
    """Headers (live; commented ones only switch commented keys off) and key spans."""
    headers: list[_Header] = []
    keys: list[_Key] = []
    section: Path_ = ()
    commented_ok = True               # no commented header since the last live one
    i = 0
    while i < len(lines):
        line = lines[i]
        body = line.lstrip(" \t")
        indent = len(line) - len(body)
        if not body:
            i += 1
        elif body.startswith("#"):
            inner = body[1:].lstrip(" \t")
            if inner.startswith("[") and _header_at(inner) is not None:
                commented_ok = False
            elif commented_ok:
                found = _commented_key(line)
                if found is not None:
                    text, parts, col, end = found
                    keys.append(_Key(section + parts, i + 1, i + 1, col, end, False, text))
            i += 1
        elif body.startswith("["):
            header = _header_at(body)
            if header is None:
                raise ValueError(f"line {i + 1}")
            section, array = header
            headers.append(_Header(section, i + 1, array))
            commented_ok = True
            i += 1
        else:
            found = _key_at(line, indent)
            if found is None:
                raise ValueError(f"line {i + 1}")
            parts, col = found
            last, end = _value_end(lines, i, col)
            keys.append(_Key(section + parts, i + 1, last + 1, col, end, True, line))
            i = last + 1
    return _Index(tuple(headers), tuple(keys), len(lines))


# --- Planning (§7.2 steps 2-4) -----------------------------------------------------------

def _broken(text: str) -> Refuse | None:
    """The refusal for text this writer won't touch: too large, or not TOML."""
    if len(text.encode("utf-8", "surrogatepass")) > CONFIG_MAX_BYTES:
        return Refuse(UNSAFE)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        match = _AT_LINE.search(str(exc))
        line = int(match.group(1)) if match else text.count("\n") + 1
        return Refuse(FIX_FIRST.format(file=CONFIG_FILENAME, line=line),
                      (CONFIG_FILENAME, line))
    return None


def _complex(index: _Index, path: Path_, ref: str) -> Refuse | None:
    """A refusal when ``path`` sits in a shape this writer can't change: inside an inline
    table or a dotted value (a live key whose path is a prefix of it), inside an array of
    tables, or when it names a table itself."""
    for key in index.keys:
        if key.live and (path[:len(key.path)] == key.path or key.path[:len(path)] == path) \
                and key.path != path:
            return Refuse(COMPLEX, (ref, key.first))
    for header in index.headers:
        if (header.array and path[:len(header.path)] == header.path) \
                or header.path[:len(path)] == path:
            return Refuse(COMPLEX, (ref, header.line))
    return None


def _prepare(text: str, section: str, key: str, ref: str
             ) -> tuple[list[str], _Index, Path_] | Refuse:
    refused = _broken(text)
    if refused is not None:
        return refused
    lines = text.split("\n")
    try:
        index = _index(lines)
    except ValueError:
        return Refuse(UNSAFE)
    path = (*section.split("."), key)
    refused = _complex(index, path, ref)
    return refused if refused is not None else (lines, index, path)


def _replaced(line: str, col: int, end: int, literal: str) -> str:
    return line[:col] + literal + line[end:]


def _insert_at(index: _Index, lines: Sequence[str], section: Path_) -> tuple[int, str] | None:
    """(line to insert before, indent) under the live header ``section``, else None."""
    header = next((h for h in index.headers if h.path == section and not h.array), None)
    if header is None:
        return None
    end = next((h.line for h in index.headers if h.line > header.line), index.count + 1)
    inside = [k for k in index.keys if header.line < k.first < end]
    if not inside:
        return header.line + 1, ""
    anchor = inside[-1]
    line = lines[anchor.first - 1]
    return anchor.last + 1, line[:len(line) - len(line.lstrip(" \t"))]


def plan_set(text: str, section: str, key: str, value: object, *, title: str | None = None,
             ref: str = CONFIG_FILENAME) -> TomlPlan | Refuse | None:
    """The plan that sets ``[section] key`` to ``value`` in editor ``text`` (§7.2), a
    ``Refuse``, or None when the key already holds that value. ``section`` is dotted
    (``"theme.textbox"``); ``key`` is one key, quoted in the file when it must be."""
    validator = validator_for(section, key)
    if validator is None:
        return Refuse(NOT_A_SETTING.format(section=section, key=key))
    bad = Refuse(BAD_VALUE.format(section=section, key=key, expected=validator.expected))
    try:
        literal = toml_literal(value, validator)
        wanted = tomllib.loads("v = " + literal)["v"]
        _check_value(section, key, validator, wanted)
    except (ValueError, ValueProblem, AssetRefError, tomllib.TOMLDecodeError):
        return bad
    prepared = _prepare(text, section, key, ref)
    if isinstance(prepared, Refuse):
        return prepared
    lines, index, path = prepared
    title = title if title is not None else SET_TITLE.format(section=section, key=key)

    live = next((k for k in index.keys if k.live and k.path == path), None)
    if live is not None and _same(_get(tomllib.loads(text), path), wanted):
        return None
    target = live or next((k for k in index.keys if not k.live and k.path == path), None)
    if target is not None:
        head = target.line
        tail = lines[target.last - 1] if target.last > target.first else head
        tail_col = target.end_col
        if target.last == target.first:
            new = _replaced(head, target.value_col, tail_col, literal)
        else:
            new = head[:target.value_col] + literal + tail[tail_col:]
        guards = tuple((n, lines[n - 1]) for n in range(target.first, target.last + 1))
        edit = LineEdit(target.first, target.last, (new,))
        select = (target.first, target.value_col, target.value_col + len(literal))
    else:
        spot = _insert_at(index, lines, path[:-1])
        key_line = f"{_key_text(key)} = {literal}"
        if spot is not None:
            at, indent = spot
            guards = ((at - 1, lines[at - 2]),)
            edit = LineEdit(at, at - 1, (indent + key_line,))
            select = (at, len(indent) + len(key_line) - len(literal), len(indent) + len(key_line))
        else:
            header = "[" + ".".join(_key_text(part) for part in path[:-1]) + "]"
            last = len(lines)
            new_lines = (header, key_line)
            if lines[-1].strip():
                new_lines = ("", *new_lines)
            elif last == 1:
                last = 0                              # an empty document: replace its line
            guards = ((len(lines), lines[-1]),)
            if last == 0:
                edit = LineEdit(1, 1, new_lines)
            else:
                edit = LineEdit(last + 1, last, new_lines)
            at = edit.first + len(new_lines) - 1
            select = (at, len(key_line) - len(literal), len(key_line))
    edit, guards = _keep_end(lines, edit, guards)
    plan = TomlPlan(title, ref, section, key, wanted, (edit,), guards, select)
    return plan if verify(plan, text) else Refuse(UNSAFE)


def plan_remove(text: str, section: str, key: str, *, title: str | None = None,
                ref: str = CONFIG_FILENAME, drop_empty: bool = False
                ) -> TomlPlan | Refuse | None:
    """The plan that removes ``[section] key`` ("Use default"; the header stays), a
    ``Refuse``, or None when the key isn't set. ``drop_empty`` (F62's ``[meter.<name>]``):
    when only blank lines would be left under the header, the header goes too, with one
    blank line before it."""
    prepared = _prepare(text, section, key, ref)
    if isinstance(prepared, Refuse):
        return prepared
    lines, index, path = prepared
    live = next((k for k in index.keys if k.live and k.path == path), None)
    if live is None:
        return None
    title = title if title is not None else REMOVE_TITLE.format(section=section, key=key)
    first, last = live.first, live.last
    if drop_empty:
        first, last = _with_empty_header(index, lines, path[:-1], first, last)
    guards = tuple((n, lines[n - 1]) for n in range(first, last + 1))
    edit, guards = _keep_end(lines, LineEdit(first, last, ()), guards)
    plan = TomlPlan(title, ref, section, key, None, (edit,), guards)
    return plan if verify(plan, text) else Refuse(UNSAFE)


def _keep_end(lines: Sequence[str], edit: LineEdit, guards: tuple[tuple[int, str], ...]
              ) -> tuple[LineEdit, tuple[tuple[int, str], ...]]:
    """``edit`` (and its guards) widened, when only blank lines follow it, so the text keeps
    its ending: one final break if it had one (an empty last line), else none, and no blank
    lines left piled up at the end. So a table appended and then removed again gives back
    the text as it was, and config.toml keeps exactly one final newline."""
    if any(line.strip() for line in lines[max(0, edit.last):]):   # text after it: not the end
        return edit, guards
    out = apply_lines(list(lines), (edit,))
    while out and not out[-1].strip():
        out.pop()
    if not out or (len(lines) > 1 and lines[-1] == ""):
        out.append("")
    same = 0
    while same < min(len(out), edit.first - 1) and lines[same] == out[same]:
        same += 1
    widened = LineEdit(same + 1, len(lines), tuple(out[same:]))
    if widened == LineEdit(edit.first, edit.last, tuple(edit.lines)):
        return edit, guards
    seen = dict(guards)
    seen.update((n, lines[n - 1]) for n in range(same + 1, len(lines) + 1))
    return widened, tuple(sorted(seen.items()))


def _with_empty_header(index: _Index, lines: Sequence[str], section: Path_, first: int,
                       last: int) -> tuple[int, int]:
    """The lines to remove so that removing lines ``first``..``last`` also takes the live
    header ``section`` when nothing but blank lines would stay under it (and no table
    inside it follows); else ``(first, last)``."""
    header = next((h for h in index.headers if h.path == section and not h.array), None)
    if header is None or header.line > first:
        return first, last
    nxt = next((h for h in index.headers if h.line > header.line), None)
    end = nxt.line - 1 if nxt is not None else index.count
    if nxt is not None and nxt.path[:len(section)] == section:
        return first, last
    if any(lines[n - 1].strip() for n in range(header.line + 1, end + 1)
           if not first <= n <= last):
        return first, last
    start = header.line
    if start > 1 and not lines[start - 2].strip():
        start -= 1
    elif start == 1:                                  # the file's top: no gap left above
        while last < index.count - 1 and not lines[last].strip():
            last += 1
    return start, last


def plan_changes(text: str, changes: Sequence[tuple[str, str, Any]], *,
                 title: str | None = None, ref: str = CONFIG_FILENAME,
                 drop_empty: bool = False) -> TomlPlan | Refuse | None:
    """One plan for several ``(section, key, value)`` changes (value None: "Use default"),
    as one undo step (F42 04 §7.6: Build's title, version, id, icon). Each change is planned
    on the text the earlier ones made; the result is one edit over the lines that differ,
    guarded by the original lines around it, and checked by ``verify`` against every
    change. The first refusal wins; None when nothing changes. A single change gives its
    own plan (with its selection). ``drop_empty``: as ``plan_remove``'s."""
    current, done = text, []
    for section, key, value in changes:
        if value is None:
            step = plan_remove(current, section, key, ref=ref, drop_empty=drop_empty)
        else:
            step = plan_set(current, section, key, value, ref=ref)
        if isinstance(step, Refuse):
            return step
        if step is not None:
            done.append(step)
            current = "\n".join(apply_lines(current.split("\n"), step.edits))
    if not done:
        return None
    if len(done) == 1:
        one = done[0]
        return one if title is None else TomlPlan(title, one.ref, one.section, one.key,
                                                  one.value, one.edits, one.guards,
                                                  one.select)
    old, new = text.split("\n"), current.split("\n")
    head = 0
    while head < min(len(old), len(new)) and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < min(len(old), len(new)) - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    first, last = head + 1, len(old) - tail               # replaced old lines (may be none)
    edit = LineEdit(first, last, tuple(new[head:len(new) - tail]))
    low, high = max(1, first - 1), min(len(old), max(last, first))
    guards = tuple((n, old[n - 1]) for n in range(low, high + 1))
    plan = TomlPlan(title if title is not None else CHANGES_TITLE, ref, done[0].section,
                    done[0].key, done[0].value, (edit,), guards,
                    more=tuple((p.section, p.key, p.value) for p in done[1:]))
    return plan if verify(plan, text) else Refuse(UNSAFE)


# --- Verifying (§7.2 step 5, SEC-F42-13) -------------------------------------------------

def _get(doc: Any, path: Path_) -> Any:
    for part in path:
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def _same(a: Any, b: Any) -> bool:
    """Equal values of the same types (``1``, ``1.0`` and ``true`` differ)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and math.isnan(a):
        return math.isnan(b)
    return bool(a == b)


def _has(doc: Any, path: Path_) -> bool:
    for part in path:
        if not isinstance(doc, dict) or part not in doc:
            return False
        doc = doc[part]
    return True


def _drop_emptied(expected: dict, got: dict, emptied: set[Path_]) -> None:
    """Remove from ``expected`` each table in ``emptied`` (deepest first) that is empty
    there and absent from ``got``: a removal may take the table it alone filled with it (a
    top-level dotted key), but no other table may vanish."""
    for path in sorted(emptied, key=len, reverse=True):
        parent = _get(expected, path[:-1]) if len(path) > 1 else expected
        if isinstance(parent, dict) and parent.get(path[-1]) == {} and not _has(got, path):
            del parent[path[-1]]


def verify(plan: TomlPlan, text: str) -> bool:
    """True when ``plan`` still fits editor ``text`` (F42 07 I-8, SEC-F42-13): its guarded
    lines hold their old texts, and the new text parses with ``tomllib`` to exactly the old
    document with the plan's changes applied: a set key holds its planned value (same type),
    a removed key is gone (with any table only it filled), a new section may appear, and
    nothing else differs, not even an empty table. Every set value passes its schema
    validator (and ``check_ref`` for ``[window] icon``). Never raises."""
    try:
        lines = text.split("\n")
        if any(not 1 <= n <= len(lines) or lines[n - 1] != old for n, old in plan.guards):
            return False
        new_text = "\n".join(apply_lines(lines, plan.edits))
        if len(new_text.encode("utf-8")) > CONFIG_MAX_BYTES:
            return False
        expected = copy.deepcopy(tomllib.loads(text))
        got = tomllib.loads(new_text)
        emptied: set[Path_] = set()
        for section, key, value in plan.changes:
            path = (*section.split("."), key)
            table = expected
            for part in path[:-1]:
                table = table.setdefault(part, {})
                if not isinstance(table, dict):
                    return False
            if value is None:
                if path[-1] not in table:
                    return False
                del table[path[-1]]
                emptied.update(path[:i] for i in range(1, len(path)))
            else:
                validator = validator_for(section, key)
                if validator is None:
                    return False
                _check_value(section, key, validator, value)
                table[path[-1]] = value
        _drop_emptied(expected, got, emptied)
        return _same(got, expected)
    except Exception:          # a planner bug must never reach the text (TR-F46-03)
        return False


__all__ = ["BAD_VALUE", "CHANGES_TITLE", "COMPLEX", "NOT_A_SETTING", "REMOVE_TITLE",
           "SET_TITLE", "TomlPlan", "plan_changes", "plan_remove", "plan_set", "toml_literal",
           "validator_for", "verify"]
