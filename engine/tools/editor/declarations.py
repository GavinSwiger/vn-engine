"""Studio's Database readers and writers for declaration lines (F47 ``04-technical.md`` §3.1,
§7.1; design §4.3, PR-F47-02, PR-F47-10; AC-F47-05, 06, 08, 14).

Why this module exists: the Database edits characters, colour backgrounds and variables, but
the ``.vns`` text stays the only truth. So the Database reads each declaring line here and
writes it back as one line. A reader takes literals only (``ast.literal_eval`` per argument);
anything else (an expression, an unknown option) reads as ``values=None``, which Studio shows
read-only with **Edit as script**. Pure: no Tk, no file access, never runs author code.

- ``scan(texts)`` reads every top-level ``define``, ``default`` and ``image`` line (column 0,
  outside an open bracket of the line before) of each script text. It doesn't parse whole
  files, so it stays fast on long stories (04 §11); ``declplan.verify_decl`` re-parses what
  it writes with the real parser.
- Kinds: ``CHARACTER`` (``define x = Character(...)``), ``COLOR`` (``image <name> =
  "#rrggbb"``), ``VARIABLE`` (``default x = <literal>``); and, read-only, ``DEFINE`` (another
  ``define``), ``IMAGE`` (an image file), ``PERSISTENT`` (``default persistent.x``, P2).
- ``CHARACTER_OPTIONS`` is Studio's own copy of the runtime's option table, in doc order with
  each default (``tests/tools/editor/test_declarations.py`` compares it with
  ``engine/runtime/character.py``, which Studio may not import).
- ``script_name(shown, taken)`` is PR-F47-10's slug: lowercase, letters, digits and ``_``;
  a clash or a reserved word gets ``_2``, ``_3``…
"""

import ast
import math
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from engine.script.words import (
    MODIFIER_WORDS, canonical_name, check_name, is_image_word, is_word_char)
from engine.tools.editor.forms import code_of, quote

# --- Kinds and tables --------------------------------------------------------------------------

CHARACTER: Final = "character"
COLOR: Final = "color"            # a colour picture: image bg sunset = "#112233"
VARIABLE: Final = "variable"
DEFINE: Final = "define"          # any other define (read-only in P1)
IMAGE: Final = "image"            # an image file declaration (read-only)
PERSISTENT: Final = "persistent"  # default persistent.x (P2)
EDITABLE_KINDS: Final = frozenset((CHARACTER, COLOR, VARIABLE))

# Character(...) options in doc order (docs/script-language.md), each with its default. The
# shown name is the first argument, kept under "name" in values.
CHARACTER_OPTIONS: Final[tuple[tuple[str, object], ...]] = (
    ("color", None),
    ("name_from", None),
    ("image_tag", None),
    ("text_color", None),
    ("text_italic", False),
    ("blip", None),
    ("blip_every", 2),
    ("blip_pitch", 0.0),
    ("blip_volume", 100),
)
OPTION_DEFAULTS: Final[Mapping[str, object]] = MappingProxyType(dict(CHARACTER_OPTIONS))
NAME: Final = "name"              # values key of the shown name (None with name_from)

# Variables (design §4.3): kind word → Python type of the starting value.
NUMBER: Final = "number"
TEXT: Final = "text"
YES_NO: Final = "yesno"
VARIABLE_KINDS: Final = (NUMBER, TEXT, YES_NO)
KIND_TITLES: Final[Mapping[str, str]] = MappingProxyType(
    {NUMBER: "Number", TEXT: "Text", YES_NO: "Yes-No"})
VARIABLE_STARTS: Final[Mapping[str, object]] = MappingProxyType(
    {NUMBER: 0, TEXT: "", YES_NO: False})

BACKGROUND_TAG: Final = "bg"
SLUG_MAX_CHARS: Final = 40
CONTINUATION_MAX_LINES: Final = 200          # one declaration's lines, at most

_HEAD = re.compile(r"(define|default|image)[ \t]")
_DEFINE = re.compile(r"define[ \t]+([^\W\d]\w*)[ \t]*=(.*)", re.DOTALL)
_DEFAULT = re.compile(r"default[ \t]+([^\W\d]\w*)[ \t]*=(.*)", re.DOTALL)
_PERSISTENT = re.compile(r"default[ \t]+persistent[ \t]*\.[ \t]*([^\W\d]\w*)[ \t]*=", re.DOTALL)
_IMAGE = re.compile(r'image[ \t]+([^=]+?)[ \t]*=[ \t]*"([^"\\\n]*)"[ \t]*', re.DOTALL)
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_OPENER = re.compile(r"[(\[{]")


@dataclass(frozen=True, slots=True)
class Decl:
    """One declaration: ``kind``, its script ``name`` (an image's words joined by one space),
    ``ref`` and lines ``first``..``last`` (1-based), and its ``values`` (None: Edit as
    script). Character values hold ``NAME`` and every option (defaults filled in); variable
    values ``{"kind", "value"}``; colour values ``{"color"}``."""

    kind: str
    name: str
    ref: str
    first: int
    last: int
    values: Mapping[str, object] | None

    @property
    def place(self) -> tuple[str, int]:
        return self.ref, self.first


# --- Reading -----------------------------------------------------------------------------------

def _depth_after(line: str, depth: int) -> int:
    """Bracket depth after ``line`` (strings and a ``#`` comment skipped), from ``depth``."""
    if depth == 0 and _OPENER.search(line) is None:
        return 0                                        # most story lines: no bracket at all
    quote_char = ""
    i, n = 0, len(line)
    while i < n:
        char = line[i]
        if quote_char:
            if char == "\\":
                i += 2
                continue
            if char == quote_char:
                quote_char = ""
        elif char in "\"'":
            quote_char = char
        elif char == "#":
            break
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(depth - 1, 0)
        i += 1
    return depth


def statements(text: str) -> Iterable[tuple[int, int, list[str]]]:
    """``(first, last, lines)`` of each top-level ``define``/``default``/``image`` statement
    in ``text`` (lines without endings), continuation lines included."""
    lines = text.split("\n")
    depth = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if depth > 0 and (_HEAD.match(line) or line.startswith("label ")):
            depth = 0                    # a broken bracket above doesn't swallow the file
        if depth == 0 and _HEAD.match(line):
            first = i
            depth = _depth_after(line, 0)
            while (depth > 0 or lines[i].rstrip().endswith("\\")) and i + 1 < len(lines) \
                    and i - first < CONTINUATION_MAX_LINES:
                i += 1
                depth = _depth_after(lines[i], depth)
            yield first + 1, i + 1, lines[first:i + 1]
            depth = 0
        else:
            depth = _depth_after(line, depth)
        i += 1


def _literal(node: ast.AST) -> tuple[bool, object]:
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _expression(source: str) -> ast.expr | None:
    try:
        return ast.parse(source.strip(), mode="eval").body
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None


def is_character_call(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
        and node.func.id == "Character"


def character_values(node: ast.Call) -> dict[str, object] | None:
    """A literal ``Character(...)`` call's values (every option, defaults filled in), or
    None when any argument isn't a literal Studio can edit."""
    if len(node.args) > 1 or any(isinstance(a, ast.Starred) for a in node.args):
        return None
    values: dict[str, object] = {NAME: None, **OPTION_DEFAULTS}
    if node.args:
        ok, name = _literal(node.args[0])
        if not ok or type(name) is not str:
            return None
        values[NAME] = name
    seen: set[str] = set()
    for keyword in node.keywords:
        if keyword.arg is None or keyword.arg not in OPTION_DEFAULTS or keyword.arg in seen:
            return None
        ok, value = _literal(keyword.value)
        if not ok or not _option_ok(keyword.arg, value):
            return None
        seen.add(keyword.arg)
        values[keyword.arg] = value
    if (values[NAME] is None) == (values["name_from"] is None):
        return None                                  # neither or both: the check's E75d
    return values


def _option_ok(option: str, value: object) -> bool:
    default = OPTION_DEFAULTS[option]
    if option == "text_italic":
        return type(value) is bool
    if option == "blip_pitch":
        return type(value) in (int, float)
    if isinstance(default, int):
        return type(value) is int
    return type(value) is str


def variable_values(source: str) -> dict[str, object] | None:
    """``{"kind", "value"}`` for a Number, Text or Yes-No literal, else None."""
    node = _expression(source)
    if node is None:
        return None
    ok, value = _literal(node)
    if not ok:
        return None
    if type(value) is bool:
        return {"kind": YES_NO, "value": value}
    if type(value) in (int, float) and math.isfinite(value):          # type: ignore[arg-type]
        return {"kind": NUMBER, "value": value}
    if type(value) is str:
        return {"kind": TEXT, "value": value}
    return None


def _image_name(words: str) -> str | None:
    parts = words.split()
    if not parts or not all(is_image_word(word) for word in parts):
        return None
    return " ".join(canonical_name(word) for word in parts)


def read(ref: str, first: int, last: int, lines: list[str]) -> Decl | None:
    """One statement's ``Decl``, or None when it isn't a declaration ``scan`` lists."""
    code, _comment = code_of(lines)
    if code.startswith("image"):
        match = _IMAGE.fullmatch(code)
        if match is None:
            head = re.match(r"image[ \t]+([^=]+?)[ \t]*=", code)
            name = _image_name(head.group(1)) if head else None
            return None if name is None else Decl(IMAGE, name, ref, first, last, None)
        name = _image_name(match.group(1))
        if name is None:
            return None
        value = match.group(2)
        if _HEX.fullmatch(value):
            return Decl(COLOR, name, ref, first, last, {"color": value})
        return Decl(IMAGE, name, ref, first, last, None)
    if code.startswith("default"):
        persistent = _PERSISTENT.match(code)
        if persistent is not None:
            return Decl(PERSISTENT, canonical_name(persistent.group(1)), ref, first, last, None)
        match = _DEFAULT.fullmatch(code)
        if match is None:
            return None
        return Decl(VARIABLE, canonical_name(match.group(1)), ref, first, last,
                    variable_values(match.group(2)))
    match = _DEFINE.fullmatch(code)
    if match is None:
        return None
    name = canonical_name(match.group(1))
    node = _expression(match.group(2))
    if is_character_call(node):
        return Decl(CHARACTER, name, ref, first, last,
                    character_values(node))                           # type: ignore[arg-type]
    return Decl(DEFINE, name, ref, first, last, None)


def scan(texts: Mapping[str, str]) -> tuple[Decl, ...]:
    """Every declaration of ``texts`` (ref → text), in ref order, then line order."""
    found: list[Decl] = []
    for ref in sorted(texts):
        for first, last, lines in statements(texts[ref]):
            decl = read(ref, first, last, lines)
            if decl is not None:
                found.append(decl)
    return tuple(found)


def find(decls: Iterable[Decl], kind: str, name: str, ref: str | None = None) -> Decl | None:
    """The first ``kind`` declaration of ``name`` (in ``ref`` when given)."""
    for decl in decls:
        if decl.kind == kind and decl.name == name and (ref is None or decl.ref == ref):
            return decl
    return None


# --- Writing -----------------------------------------------------------------------------------

def _literal_text(value: object) -> str:
    if type(value) is str:
        return quote(value)                                          # type: ignore[arg-type]
    if type(value) is bool or type(value) is int:
        return repr(value)
    if type(value) is float:
        if not math.isfinite(value):                                 # type: ignore[arg-type]
            raise ValueError("not a finite number")
        return repr(value)
    raise ValueError(f"not a literal Studio writes: {type(value).__name__}")


def character_call(values: Mapping[str, object]) -> str:
    """``Character(...)`` with the shown name first, then only non-default options in doc
    order (AC-F47-06). Raises ValueError for a value it can't write."""
    parts: list[str] = []
    name = values.get(NAME)
    if name is not None:
        parts.append(_literal_text(name))
    for option, default in CHARACTER_OPTIONS:
        value = values.get(option, default)
        if value is None or value == default:
            continue
        if not _option_ok(option, value):
            raise ValueError(f"bad {option}")
        parts.append(f"{option}={_literal_text(value)}")
    return f"Character({', '.join(parts)})"


def line_for(kind: str, name: str, values: Mapping[str, object]) -> str:
    """The one code line declaring ``name`` (no indent, no comment). Raises ValueError for
    values it can't write."""
    if kind == CHARACTER:
        return f"define {name} = {character_call(values)}"
    if kind == VARIABLE:
        value, var_kind = values.get("value"), values.get("kind")
        ok = {NUMBER: type(value) in (int, float), TEXT: type(value) is str,
              YES_NO: type(value) is bool}.get(var_kind, False)        # type: ignore[arg-type]
        if not ok:
            raise ValueError("bad variable value")
        return f"default {name} = {_literal_text(value)}"
    if kind == COLOR:
        color = values.get("color")
        if type(color) is not str or not _HEX.fullmatch(color):
            raise ValueError("bad colour")
        return f"image {name} = {quote(color)}"
    raise ValueError(f"Studio doesn't write {kind!r} declarations")


# --- Script names (PR-F47-10, AC-F47-08) -------------------------------------------------------

def _slug(shown: str) -> str:
    out: list[str] = []
    for char in canonical_name(shown.strip()).lower():
        out.append(char if is_word_char(char) else "_")
    slug = re.sub(r"_+", "_", "".join(out)).strip("_")
    return slug[:SLUG_MAX_CHARS].rstrip("_")


def name_problem(name: str, kind: str = CHARACTER) -> bool:
    """True when ``name`` can't be written as a ``kind`` script name (a reserved word, a
    keyword, an engine name, not a word…)."""
    if kind == COLOR:
        return _image_name(name) is None
    return check_name(name) is not None or name.lower() in MODIFIER_WORDS


def script_name(shown: str, taken: Collection[str], kind: str = CHARACTER) -> str:
    """The script name for a new ``kind`` entry shown as ``shown``: lowercase, letters, digits
    and ``_`` (a leading digit gets the kind's word first; nothing left: the kind's word); a
    reserved word or a name in ``taken`` (compared case-insensitively) gets ``_2``, ``_3``…
    A ``COLOR`` name is one image word after ``bg ``."""
    fallback = {COLOR: "color", VARIABLE: "variable"}.get(kind, "character")
    base = _slug(shown) or fallback
    if base[0].isdigit():
        base = f"{fallback}_{base}"
    folded = {name.casefold() for name in taken}

    def full(name: str) -> str:
        return f"{BACKGROUND_TAG} {name}" if kind == COLOR else name

    def free(name: str) -> bool:
        return not name_problem(full(name), kind) and full(name).casefold() not in folded

    if free(base):
        return full(base)
    number = 2
    while not free(f"{base}_{number}"):
        number += 1
    return full(f"{base}_{number}")


def taken_names(decls: Iterable[Decl], kind: str = CHARACTER) -> frozenset[str]:
    """Names a new ``kind`` entry may not take: every image name for ``COLOR``, else every
    define and default name (one Python namespace)."""
    if kind == COLOR:
        return frozenset(d.name for d in decls if d.kind in (COLOR, IMAGE))
    return frozenset(d.name for d in decls if d.kind in (CHARACTER, DEFINE, VARIABLE))


__all__ = ["BACKGROUND_TAG", "CHARACTER", "CHARACTER_OPTIONS", "COLOR", "DEFINE",
           "EDITABLE_KINDS", "IMAGE", "KIND_TITLES", "NAME", "NUMBER", "OPTION_DEFAULTS",
           "PERSISTENT", "TEXT", "VARIABLE", "VARIABLE_KINDS", "VARIABLE_STARTS", "YES_NO",
           "Decl", "character_call", "character_values", "find", "is_character_call",
           "line_for", "name_problem", "read", "scan", "script_name", "statements",
           "taken_names", "variable_values"]
