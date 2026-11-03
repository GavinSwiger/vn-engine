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
  ``define``), ``IMAGE`` (an image file).
- P2 kinds (P2-D; AC-F47-36..41): ``PERSISTENT`` (``default persistent.x = <literal>``, the
  Variables form's "Remembered across playthroughs"), ``METER`` (``points a b [lo to hi]
  [start n]``: one ``Decl`` per name, ``group`` the names sharing the line), ``TIP``/``ITEM``
  (``lock tip|item n "Title" [in "Category"] [image words][:]`` with one quoted paragraph per
  indented line), ``ROUTE`` (``lock route label "Title" [until a, b]``), ``TRANSITION``
  (``define n = Dissolve(...)``, ``Fade(...)``, ``Mask(...)``). ``marks(texts)`` reads the
  ``ending``/``chapter`` lines in labels (read-only ``ENDING``/``CHAPTER``), and
  ``position_rows(config_text)`` the ``[stage.positions]`` table with the built-ins.
- Titles and categories are values as shown (``{{`` read as ``{``, written back doubled);
  codex paragraphs are kept as written (their ``{b}``/``{i}``/``{color}`` tags stay).
- ``CHARACTER_OPTIONS`` is Studio's own copy of the runtime's option table, in doc order with
  each default (``tests/tools/editor/test_declarations.py`` compares it with
  ``engine/runtime/character.py``, which Studio may not import).
- ``script_name(shown, taken)`` is PR-F47-10's slug: lowercase, letters, digits and ``_``;
  a clash or a reserved word gets ``_2``, ``_3``…
"""

import ast
import keyword
import math
import re
import tomllib
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from engine.core.config_schema import Position, PositionName, ValueProblem
from engine.core.constants import (
    BUILTIN_POSITIONS, CANVAS_SIZE, COLOR_WORDS, IMAGE_SUFFIXES, MASK_SOFT_RANGE,
    TRANSITION_SECONDS_RANGE)
from engine.core.errors import AssetRefError
from engine.core.paths import check_ref
from engine.script.codex import CATEGORY_MAX as CODEX_CATEGORY_MAX
from engine.script.codex import NAME_MAX as CODEX_NAME_MAX
from engine.script.codex import PARAGRAPH_MAX as CODEX_PARAGRAPH_MAX
from engine.script.codex import PARAGRAPHS_MAX as CODEX_PARAGRAPHS_MAX
from engine.script.codex import TITLE_MAX as CODEX_TITLE_MAX
from engine.script.effects import BUILTIN_TRANSITION_NAMES
from engine.script.points import METER_NAME_MAX, POINTS_LIMIT, STATEMENT_PARTS
from engine.script.routes import PERSISTENT_VIEWS, ROUTE_TITLE_MAX
from engine.script.routes import UNTIL_MAX as ROUTE_UNTIL_MAX
from engine.script.words import (
    MODIFIER_WORDS, ROLE_METER, canonical_name, check_name, is_image_word, is_word_char)
from engine.tools.editor.forms import code_of, quote

# --- Kinds and tables --------------------------------------------------------------------------

CHARACTER: Final = "character"
COLOR: Final = "color"            # a colour picture: image bg sunset = "#112233"
VARIABLE: Final = "variable"
DEFINE: Final = "define"          # any other define (read-only in P1)
IMAGE: Final = "image"            # an image file declaration (read-only)
PERSISTENT: Final = "persistent"  # default persistent.x (P2: "Remembered across playthroughs")
METER: Final = "meter"            # points a b 0 to 10 start 5 (F22)
TIP: Final = "tip"                # lock tip n "Title" … : (F21)
ITEM: Final = "item"              # lock item n "Title" … : (F21)
ROUTE: Final = "route"            # lock route label "Title" until a, b (F19)
TRANSITION: Final = "transition"  # define n = Dissolve(…) / Fade(…) / Mask(…) (F09)
ENDING: Final = "ending"          # an ending line in a label (read-only: marks())
CHAPTER: Final = "chapter"        # a chapter line in a label (read-only: marks())
POSITION: Final = "position"      # a [stage.positions] key of config.toml (F04)
EDITABLE_KINDS: Final = frozenset((CHARACTER, COLOR, VARIABLE, PERSISTENT, METER, TIP, ITEM,
                                   ROUTE, TRANSITION))
# Kinds one form switches between (``declplan.plan_edit``'s ``kind``): the Variables form's
# "Remembered across playthroughs" and the Codex form's Tips / Items.
SWAPS: Final[Mapping[str, frozenset[str]]] = MappingProxyType({
    VARIABLE: frozenset((VARIABLE, PERSISTENT)), PERSISTENT: frozenset((VARIABLE, PERSISTENT)),
    TIP: frozenset((TIP, ITEM)), ITEM: frozenset((TIP, ITEM))})
_NAMESPACES: Final[Mapping[str, str]] = MappingProxyType({   # kinds sharing one set of names
    CHARACTER: "python", DEFINE: "python", VARIABLE: "python", TRANSITION: "python",
    PERSISTENT: "persistent", METER: "points", TIP: "codex", ITEM: "codex", ROUTE: "route",
    COLOR: "image", IMAGE: "image"})

# Meters (design §4.3): the values of a points declaration. None: not written (no range: the
# engine's ±1,000,000,000; no start: 0, or low when 0 is outside the range).
METER_KEYS: Final = ("low", "high", "start")

# Codex (design §4.3): title and category as shown, picture as image words, text paragraphs
# as written.
CODEX_KEYS: Final = ("title", "category", "image", "text")
CODEX_INDENT: Final = "    "

# Transitions (design §4.3, docs/script-language.md "Your own transitions"): kind word →
# constructor, and every values key with its default (the constructor's own).
DISSOLVE: Final = "dissolve"
FADE: Final = "fade"
MASK: Final = "mask"
TRANSITION_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {DISSOLVE: "Dissolve", FADE: "Fade", MASK: "Mask"})
TRANSITION_PARAMS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    DISSOLVE: ("seconds",), FADE: ("seconds", "color"),
    MASK: ("file", "seconds", "soft", "reverse")})
TRANSITION_DEFAULTS: Final[Mapping[str, object]] = MappingProxyType(
    {"seconds": None, "color": None, "file": None, "soft": 0.1, "reverse": False})

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

_HEAD = re.compile(r"(define|default|image|points|lock)[ \t]")
_DEFINE = re.compile(r"define[ \t]+([^\W\d]\w*)[ \t]*=(.*)", re.DOTALL)
_DEFAULT = re.compile(r"default[ \t]+([^\W\d]\w*)[ \t]*=(.*)", re.DOTALL)
_PERSISTENT = re.compile(r"default[ \t]+persistent[ \t]*\.[ \t]*([^\W\d]\w*)[ \t]*=(.*)",
                         re.DOTALL)
_PERSISTENT_HEAD = re.compile(r"default[ \t]+persistent[ \t]*\.")
_WORD_TOKEN = re.compile(r'"(?:[^"\\\n]|\\.)*"|[,:]|[^\s",:]+')
_STRING = re.compile(r'"((?:[^"\\\n]|\\["\\n])*)"')
_INT = re.compile(r"-?\d+")
_MARK = re.compile(r"[ \t]+(ending|chapter)[ \t]")
_POSITION: Final = Position()
_POSITION_NAME: Final = PositionName()
_IMAGE = re.compile(r'image[ \t]+([^=]+?)[ \t]*=[ \t]*"([^"\\\n]*)"[ \t]*', re.DOTALL)
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_OPENER = re.compile(r"[(\[{]")


@dataclass(frozen=True, slots=True)
class Decl:
    """One declaration: ``kind``, its script ``name`` (an image's words joined by one space),
    ``ref`` and lines ``first``..``last`` (1-based), and its ``values`` (None: Edit as
    script). Character values hold ``NAME`` and every option (defaults filled in); variable
    values ``{"kind", "value"}`` (``PERSISTENT`` too); colour values ``{"color"}``; meter
    values ``METER_KEYS``; codex values ``CODEX_KEYS``; route values ``{"title", "until"}``;
    transition values ``{"kind"}`` and every ``TRANSITION_DEFAULTS`` key; ending and chapter
    marks ``{"heading", "title"}``. ``group``: every name a shared ``points`` line declares
    (one name: ``()``)."""

    kind: str
    name: str
    ref: str
    first: int
    last: int
    values: Mapping[str, object] | None
    group: tuple[str, ...] = ()

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


def _block_end(lines: list[str], head: int) -> int:
    """The index of the last indented line of the block under ``lines[head]`` (``head``
    itself when there is none). Blank lines and column-0 comments between them belong to
    it; trailing ones don't."""
    last = head
    j = head + 1
    while j < len(lines) and j - head <= CONTINUATION_MAX_LINES:
        line = lines[j]
        if line.strip() and line[0] in " \t":
            last = j
        elif line.strip() and not line.startswith("#"):
            break
        j += 1
    return last


def statements(text: str) -> Iterable[tuple[int, int, list[str]]]:
    """``(first, last, lines)`` of each top-level ``define``/``default``/``image``/``points``/
    ``lock`` statement in ``text`` (lines without endings), continuation lines and a ``lock
    tip|item …:`` block included."""
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
            if line.startswith("lock") and code_of(lines[first:i + 1])[0].endswith(":"):
                i = _block_end(lines, i)
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


def _split(code: str) -> list[str] | None:
    """Words, quoted strings (with their quotes), ``,`` and ``:``; None if anything is left."""
    found = _WORD_TOKEN.findall(code)
    return found if not _WORD_TOKEN.sub("", code).strip() else None


def unquote(token: str) -> str | None:
    """The text of one script string token (``\\"``, ``\\\\``, ``\\n`` escapes), or None."""
    match = _STRING.fullmatch(token)
    if match is None:
        return None
    return re.sub(r'\\(["\\n])', lambda m: "\n" if m.group(1) == "n" else m.group(1),
                  match.group(1))


def shown_text(written: str) -> str | None:
    """A plain title as shown (``{{`` is ``{``), or None when it holds a tag."""
    if "{" in written.replace("{{", ""):
        return None
    return written.replace("{{", "{")


def written_text(shown: str) -> str:
    """A plain title as written: each ``{`` doubled."""
    return shown.replace("{", "{{")


def _title_token(token: str) -> str | None:
    text = unquote(token)
    return None if text is None else shown_text(text)


def _name_token(token: str, role: str | None = None) -> str | None:
    if token in (",", ":") or token.startswith('"'):
        return None
    problem = check_name(token) if role is None else check_name(token, role)
    return None if problem is not None else canonical_name(token)


def _head_lines(lines: list[str]) -> int:
    """How many of ``lines`` the head takes (``\\`` joins)."""
    count = 1
    while count < len(lines) and lines[count - 1].rstrip().endswith("\\"):
        count += 1
    return count


# --- Meters (F22 points) ---

def meter_start(values: Mapping[str, object]) -> int:
    """The start the engine gives a meter with ``values``: ``start``, else 0, or ``low``
    when 0 is outside the range."""
    start, low, high = values.get("start"), values.get("low"), values.get("high")
    if type(start) is int:
        return start
    if type(low) is int and type(high) is int and not low <= 0 <= high:
        return low
    return 0


def meter_ok(values: Mapping[str, object]) -> bool:
    """True when ``values`` make a valid ``points`` declaration (whole numbers within the
    engine's limit, low below high, start in range)."""
    low, high, start = (values.get(key) for key in METER_KEYS)
    for value in (low, high, start):
        if value is not None and (type(value) is not int or abs(value) > POINTS_LIMIT):
            return False
    if (low is None) != (high is None):
        return False
    if low is not None and not low < high:                           # type: ignore[operator]
        return False
    return start is None or low is None or low <= start <= high      # type: ignore[operator]


def _meter_name(token: str) -> str | None:
    if token in STATEMENT_PARTS:
        return None
    name = _name_token(token, ROLE_METER)
    if name is None or len(name) > METER_NAME_MAX or name in STATEMENT_PARTS:
        return None
    return name


def _int_token(token: str) -> int | None:
    return int(token) if _INT.fullmatch(token) and len(token) <= 12 else None


def meter_read(code: str) -> tuple[tuple[str, ...], dict[str, object] | None] | None:
    """``(names, values)`` of a ``points`` declaration (values None: Edit as script), or
    None when it doesn't declare meters."""
    tokens = _split(code)
    if tokens is None or not tokens or tokens[0] != "points" or "=" in code:
        return None
    rest = tokens[1:]
    names: list[str] = []
    i = 0
    while i < len(rest) and rest[i] not in ("to", "start", ",", ":") \
            and not rest[i].startswith('"') and not re.match(r"-?[\d.]", rest[i]):
        name = _meter_name(rest[i])
        if name is None:
            return None
        names.append(name)
        i += 1
    if not names:
        return None
    values: dict[str, object] = {"low": None, "high": None, "start": None}
    bad = len(set(names)) != len(names)
    if i < len(rest) and re.match(r"-?[\d.]", rest[i]):
        low = _int_token(rest[i])
        high = _int_token(rest[i + 2]) if i + 2 < len(rest) and rest[i + 1] == "to" else None
        values["low"], values["high"] = low, high
        bad = bad or low is None or high is None
        i += 3
    if i < len(rest) and rest[i] == "start":
        start = _int_token(rest[i + 1]) if i + 1 < len(rest) else None
        values["start"] = start
        bad = bad or start is None
        i += 2
    bad = bad or i != len(rest) or not meter_ok(values)
    return tuple(names), None if bad else values


def meter_line(names: Iterable[str], values: Mapping[str, object]) -> str:
    """``points <names> [lo to hi] [start n]``; ``start`` only when it isn't the engine's
    own start (``meter_start`` without it). Raises ValueError for values it can't write."""
    if not meter_ok(values):
        raise ValueError("bad meter")
    parts = ["points", *names]
    low, high, start = (values.get(key) for key in METER_KEYS)
    if low is not None:
        parts += [str(low), "to", str(high)]
    if start is not None and start != meter_start({"low": low, "high": high}):
        parts += ["start", str(start)]
    return " ".join(parts)


# --- Codex (F21 lock tip|item) and routes (F19 lock route) ---

def codex_ok(values: Mapping[str, object]) -> bool:
    """True when ``values`` make a valid codex entry (a title, lengths within the engine's
    limits, a picture name made of image words, paragraphs of text)."""
    title, category, image, text = (values.get(key) for key in CODEX_KEYS)
    if type(title) is not str or not title.strip() or len(title) > CODEX_TITLE_MAX:
        return False
    if category is not None and (type(category) is not str or not category.strip()
                                 or len(category) > CODEX_CATEGORY_MAX):
        return False
    if image is not None and (type(image) is not str or _image_name(image) != image):
        return False
    if type(text) not in (tuple, list) or len(text) > CODEX_PARAGRAPHS_MAX:  # type: ignore[arg-type]
        return False
    return all(type(p) is str and len(p) <= CODEX_PARAGRAPH_MAX for p in text)  # type: ignore[union-attr]


def _codex_read(tokens: list[str], body: list[str]) -> dict[str, object] | None:
    """A codex head's tokens after its name, and its block lines, as values (or None)."""
    colon = bool(tokens) and tokens[-1] == ":"
    rest = tokens[:-1] if colon else tokens
    if not rest:
        return None
    title = _title_token(rest[0])
    i = 1
    category: str | None = None
    if i < len(rest) and rest[i] == "in":
        category = _title_token(rest[i + 1]) if i + 1 < len(rest) else None
        if category is None:
            return None
        i += 2
    image: str | None = None
    if i < len(rest) and rest[i] == "image":
        words = rest[i + 1:]
        if any(word in (",", ":") or word.startswith('"') for word in words):
            return None
        image = _image_name(" ".join(words))
        if image is None:
            return None
        i = len(rest)
    if i != len(rest) or title is None:
        return None
    paragraphs: list[str] = []
    for line in body:
        if not line.strip():
            continue
        code, comment = code_of([line])
        paragraph = unquote(code) if code and not comment else None
        if paragraph is None:
            return None                              # a comment or anything else: as script
        paragraphs.append(paragraph)
    if colon and not paragraphs:
        return None
    values = {"title": title, "category": category, "image": image, "text": tuple(paragraphs)}
    return values if codex_ok(values) else None


def codex_lines(kind: str, name: str, values: Mapping[str, object]) -> tuple[str, ...]:
    """``lock tip|item <name> "Title" [in "Category"] [image words][:]`` and one indented
    quoted paragraph per line. Raises ValueError for values it can't write."""
    if kind not in (TIP, ITEM) or not codex_ok(values):
        raise ValueError("bad codex entry")
    head = f"lock {kind} {name} {quote(written_text(str(values['title'])))}"
    if values.get("category") is not None:
        head += f" in {quote(written_text(str(values['category'])))}"
    if values.get("image") is not None:
        head += f" image {values['image']}"
    text = tuple(values.get("text") or ())                           # type: ignore[arg-type]
    if not text:
        return (head,)
    return (head + ":", *(CODEX_INDENT + quote(p) for p in text))


def route_ok(values: Mapping[str, object]) -> bool:
    """True when ``values`` make a valid ``lock route`` (a title; 0–32 distinct endings)."""
    title, until = values.get("title"), values.get("until")
    if type(title) is not str or not title.strip() or len(title) > ROUTE_TITLE_MAX:
        return False
    if type(until) not in (tuple, list) or len(until) > ROUTE_UNTIL_MAX \
            or len(set(until)) != len(until):                        # type: ignore[arg-type]
        return False
    return all(type(n) is str and _name_token(n) == n for n in until)  # type: ignore[union-attr]


def _route_read(tokens: list[str]) -> dict[str, object] | None:
    if not tokens:
        return None
    title = _title_token(tokens[0])
    until: list[str] = []
    rest = tokens[1:]
    if rest:
        if rest[0] != "until" or len(rest) % 2 != 0:
            return None
        for index, token in enumerate(rest[1:]):
            if index % 2 == 1:
                if token != ",":
                    return None
                continue
            name = _name_token(token)
            if name is None:
                return None
            until.append(name)
    values = {"title": title, "until": tuple(until)}
    return values if title is not None and route_ok(values) else None


def route_line(name: str, values: Mapping[str, object]) -> str:
    """``lock route <label> "Title" [until a, b]``. Raises ValueError for bad values."""
    if not route_ok(values):
        raise ValueError("bad route")
    line = f"lock route {name} {quote(written_text(str(values['title'])))}"
    until = tuple(values.get("until") or ())                         # type: ignore[arg-type]
    return f"{line} until {', '.join(until)}" if until else line


def _lock_read(ref: str, first: int, last: int, lines: list[str]) -> Decl | None:
    count = _head_lines(lines)
    code, _comment = code_of(lines[:count])
    tokens = _split(code)
    if tokens is None or len(tokens) < 3 or tokens[0] != "lock" \
            or tokens[1] not in (TIP, ITEM, ROUTE):
        return None
    name = _name_token(tokens[2])
    if name is None:
        return None
    if tokens[1] == ROUTE:
        values = _route_read(tokens[3:]) if count == 1 else None
        return Decl(ROUTE, name, ref, first, last, values)
    values = _codex_read(tokens[3:], lines[count:]) if count == 1 else None
    return Decl(tokens[1], name, ref, first, last, values)


# --- Transitions (F09 Dissolve, Fade, Mask) ---

def _number_in(value: object, low: float, high: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) \
        and low <= value <= high                                    # type: ignore[operator]


def transition_ok(values: Mapping[str, object]) -> bool:
    """True when ``values`` make a valid transition of its ``kind`` (only that kind's
    arguments are looked at)."""
    kind = values.get("kind")
    if kind not in TRANSITION_KINDS:
        return False
    seconds = values.get("seconds")
    if seconds is not None and not _number_in(seconds, *TRANSITION_SECONDS_RANGE):
        return False
    if kind == FADE:
        color = values.get("color")
        return color is None or (type(color) is str and color_ok(color))
    if kind == MASK:
        file = values.get("file")
        if type(file) is not str or not file.lower().endswith(IMAGE_SUFFIXES):
            return False
        try:
            check_ref(file)
        except AssetRefError:
            return False
        return _number_in(values.get("soft", 0.1), *MASK_SOFT_RANGE) \
            and type(values.get("reverse", False)) is bool
    return True


def color_ok(color: str) -> bool:
    """A Fade colour: a colour word (white, black, red) or ``#RRGGBB`` (any case)."""
    return color in COLOR_WORDS or _HEX.fullmatch(color) is not None


def is_transition_call(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
        and node.func.id in TRANSITION_KINDS.values()


def transition_values(node: ast.Call) -> dict[str, object] | None:
    """A literal ``Dissolve``/``Fade``/``Mask`` call's values (``kind`` and every
    ``TRANSITION_DEFAULTS`` key), or None when Studio can't edit it."""
    kind = next(k for k, call in TRANSITION_KINDS.items()
                if call == node.func.id)                             # type: ignore[attr-defined]
    params = TRANSITION_PARAMS[kind]
    if len(node.args) > len(params) or any(isinstance(a, ast.Starred) for a in node.args):
        return None
    bound: dict[str, object] = {}
    for param, arg in zip(params, node.args):
        ok, value = _literal(arg)
        if not ok:
            return None
        bound[param] = value
    for item in node.keywords:
        if item.arg is None or item.arg not in params or item.arg in bound:
            return None
        ok, value = _literal(item.value)
        if not ok:
            return None
        bound[item.arg] = value
    values = {"kind": kind, **TRANSITION_DEFAULTS, **bound}
    return values if transition_ok(values) else None


def transition_call(values: Mapping[str, object]) -> str:
    """``Dissolve(…)``, ``Fade(…)`` or ``Mask(…)`` with only the kind's non-default
    arguments. Raises ValueError for values it can't write."""
    if not transition_ok(values):
        raise ValueError("bad transition")
    kind = str(values["kind"])
    parts: list[str] = []
    if kind == MASK:
        parts.append(quote(str(values["file"])))
    if values.get("seconds") is not None:
        parts.append(_literal_text(values["seconds"]))
    if kind == FADE and values.get("color") is not None:
        parts.append(f"color={quote(str(values['color']))}")
    if kind == MASK:
        soft = values.get("soft", TRANSITION_DEFAULTS["soft"])
        if soft != TRANSITION_DEFAULTS["soft"]:
            parts.append(f"soft={_literal_text(soft)}")
        if values.get("reverse"):
            parts.append("reverse=True")
    return f"{TRANSITION_KINDS[kind]}({', '.join(parts)})"


TRY_PAUSE: Final = "pause 2"


def transition_with(name: str, values: Mapping[str, object]) -> str:
    """What ``with`` names to play ``values`` now (design §4.3 "Try it"): a Dissolve or
    Fade as the built-in with its length and colour, so unsaved form values play as shown;
    a Mask by its ``name`` (its picture is only in the saved define). Raises ValueError for
    bad values."""
    if not transition_ok(values):
        raise ValueError("bad transition")
    kind = values["kind"]
    if kind == MASK:
        return name
    parts = [str(kind)]
    if values.get("seconds") is not None:
        parts.append(_literal_text(values["seconds"]))
    color = values.get("color") if kind == FADE else None
    if color is not None:
        parts.append(str(color) if color in COLOR_WORDS else quote(str(color)))
    return " ".join(parts)


def transition_try_lines(name: str, values: Mapping[str, object],
                         background: str) -> tuple[str, ...]:
    """The Try it lines (04 §7.5's ``--try-stdin`` label body) for a transition: the empty
    stage, then ``background`` (an image name, e.g. ``bg park``) through the transition,
    then a 2-second pause. Raises ValueError for bad values."""
    return ("scene", f"scene {background} with {transition_with(name, values)}", TRY_PAUSE)


# --- Reading one statement ---

def read_all(ref: str, first: int, last: int, lines: list[str]) -> list[Decl]:
    """Every ``Decl`` one statement declares (a shared ``points`` line: one per meter)."""
    if lines and lines[0].startswith("points"):
        found = meter_read(code_of(lines)[0])
        if found is None:
            return []
        names, values = found
        group = names if len(names) > 1 else ()
        return [Decl(METER, name, ref, first, last, values, group) for name in names]
    decl = read(ref, first, last, lines)
    return [] if decl is None else [decl]


def read(ref: str, first: int, last: int, lines: list[str]) -> Decl | None:
    """One statement's (first) ``Decl``, or None when it isn't a declaration ``scan``
    lists."""
    if lines and lines[0].startswith("points"):
        found = read_all(ref, first, last, lines)
        return found[0] if found else None
    if lines and lines[0].startswith("lock"):
        return _lock_read(ref, first, last, lines)
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
        persistent = _PERSISTENT.fullmatch(code)
        if persistent is not None:
            return Decl(PERSISTENT, canonical_name(persistent.group(1)), ref, first, last,
                        variable_values(persistent.group(2)))
        if _PERSISTENT_HEAD.match(code):
            return None                                      # persistent.a.b: an error
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
    if is_transition_call(node):
        return Decl(TRANSITION, name, ref, first, last,
                    transition_values(node))                          # type: ignore[arg-type]
    return Decl(DEFINE, name, ref, first, last, None)


def scan(texts: Mapping[str, str]) -> tuple[Decl, ...]:
    """Every declaration of ``texts`` (ref → text), in ref order, then line order."""
    found: list[Decl] = []
    for ref in sorted(texts):
        for first, last, lines in statements(texts[ref]):
            found.extend(read_all(ref, first, last, lines))
    return tuple(found)


def marks(texts: Mapping[str, str]) -> tuple[Decl, ...]:
    """Every ``ending``/``chapter`` line in a label (read-only ``ENDING``/``CHAPTER``
    ``Decl``s with ``{"heading", "title"}``; None when the texts aren't plain), in ref order,
    then line order. The Endings & routes and Chapters lists show them with Go to."""
    found: list[Decl] = []
    for ref in sorted(texts):
        for number, line in enumerate(texts[ref].split("\n"), start=1):
            if _MARK.match(line) is None:
                continue
            tokens = _split(code_of([line])[0])
            if tokens is None or len(tokens) < 2:
                continue
            name = _name_token(tokens[1])
            if name is None:
                continue
            texts_ = [t for t in tokens[2:4] if t.startswith('"')]
            shown = [_title_token(t) for t in texts_]
            values: dict[str, object] | None = None
            if shown and None not in shown:
                values = {"heading": shown[0] if len(shown) == 2 else None,
                          "title": shown[-1]}
            found.append(Decl(tokens[0], name, ref, number, number, values))
    return tuple(found)


# --- Positions (F04 [stage.positions] in config.toml) ---

@dataclass(frozen=True, slots=True)
class PositionRow:
    """One stage position: ``x``, ``y`` in canvas units (None: the value isn't one the
    form can show), ``builtin`` (left, center, right), ``written`` (config.toml has it)."""

    name: str
    x: float | None
    y: float | None
    builtin: bool
    written: bool


def position_point(value: object) -> tuple[float, float] | None:
    """A ``[stage.positions]`` value (x, or ``[x, y]``) as ``(x, y)``, or None."""
    try:
        point = _POSITION.check(value)
    except ValueProblem:
        return None
    return point                                                     # type: ignore[return-value]


def position_value(x: float, y: float) -> int | float | list[int | float]:
    """``(x, y)`` as config.toml writes it: x alone when y is the bottom edge; whole numbers
    as ints."""
    def plain(v: float) -> int | float:
        return int(v) if float(v).is_integer() else float(v)
    return plain(x) if y == CANVAS_SIZE[1] else [plain(x), plain(y)]


def position_rows(config_text: str) -> tuple[PositionRow, ...] | None:
    """The built-in positions (with their config.toml values when written), then the
    ``[stage.positions]`` keys in file order; None when config.toml isn't valid TOML."""
    try:
        data = tomllib.loads(config_text)
    except (tomllib.TOMLDecodeError, RecursionError):
        return None
    stage = data.get("stage")
    table = stage.get("positions") if isinstance(stage, dict) else None
    table = table if isinstance(table, dict) else {}
    rows: list[PositionRow] = []
    for name, (x, y) in BUILTIN_POSITIONS.items():
        point = position_point(table[name]) if name in table else (x, y)
        rows.append(PositionRow(name, *(point or (None, None)), True, name in table))
    for name, value in table.items():
        if name in BUILTIN_POSITIONS:
            continue
        point = position_point(value)
        rows.append(PositionRow(name, *(point or (None, None)), False, True))
    return tuple(rows)


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
    if kind in (VARIABLE, PERSISTENT):
        value, var_kind = values.get("value"), values.get("kind")
        ok = {NUMBER: type(value) in (int, float), TEXT: type(value) is str,
              YES_NO: type(value) is bool}.get(var_kind, False)        # type: ignore[arg-type]
        if not ok:
            raise ValueError("bad variable value")
        target = f"persistent.{name}" if kind == PERSISTENT else name
        return f"default {target} = {_literal_text(value)}"
    if kind == COLOR:
        color = values.get("color")
        if type(color) is not str or not _HEX.fullmatch(color):
            raise ValueError("bad colour")
        return f"image {name} = {quote(color)}"
    if kind == METER:
        return meter_line((name,), values)
    if kind == ROUTE:
        return route_line(name, values)
    if kind == TRANSITION:
        return f"define {name} = {transition_call(values)}"
    if kind in (TIP, ITEM):
        lines = codex_lines(kind, name, values)
        if len(lines) == 1:
            return lines[0]
    raise ValueError(f"Studio doesn't write {kind!r} declarations as one line")


def lines_for(kind: str, name: str, values: Mapping[str, object]) -> tuple[str, ...]:
    """The code lines declaring ``name`` (a codex entry with text: its head and one indented
    line per paragraph; every other kind: one line). Raises ValueError for bad values."""
    if kind in (TIP, ITEM):
        return codex_lines(kind, name, values)
    return (line_for(kind, name, values),)


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
    if kind == POSITION:
        try:
            _POSITION_NAME.check(name)
        except ValueProblem:
            return True
        return False
    if kind == PERSISTENT:              # a namespace of its own: only Python's rules (F12)
        return not name.isidentifier() or keyword.iskeyword(name) or name.startswith("_") \
            or canonical_name(name) != name or name in PERSISTENT_VIEWS
    if kind == METER:
        return _meter_name(name) != name
    if kind in (TIP, ITEM) and len(name) > CODEX_NAME_MAX:
        return True
    if kind == TRANSITION and name in BUILTIN_TRANSITION_NAMES:
        return True
    return check_name(name) is not None or name.lower() in MODIFIER_WORDS


def script_name(shown: str, taken: Collection[str], kind: str = CHARACTER) -> str:
    """The script name for a new ``kind`` entry shown as ``shown``: lowercase, letters, digits
    and ``_`` (a leading digit gets the kind's word first; nothing left: the kind's word); a
    reserved word or a name in ``taken`` (compared case-insensitively) gets ``_2``, ``_3``…
    A ``COLOR`` name is one image word after ``bg ``."""
    fallback = {COLOR: "color", VARIABLE: "variable", PERSISTENT: "variable",
                ROUTE: "route", TIP: "tip", ITEM: "item", METER: "meter",
                TRANSITION: "transition", POSITION: "position"}.get(kind, "character")
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
    """Names a new ``kind`` entry may not take: the names of every kind sharing its
    namespace (every image name for ``COLOR``; every define and default for a character,
    variable or transition; tips and items together; meters; routes; remembered variables).
    ``POSITION`` names come from ``position_rows``, so here they are empty."""
    space = _NAMESPACES.get(kind)
    if space is None:
        return frozenset()
    return frozenset(d.name for d in decls if _NAMESPACES.get(d.kind) == space)


__all__ = ["BACKGROUND_TAG", "CHAPTER", "CHARACTER", "CHARACTER_OPTIONS", "CODEX_INDENT",
           "CODEX_KEYS", "COLOR", "DEFINE", "DISSOLVE", "EDITABLE_KINDS", "ENDING", "FADE",
           "IMAGE", "ITEM", "KIND_TITLES", "MASK", "METER", "METER_KEYS", "NAME", "NUMBER",
           "OPTION_DEFAULTS", "PERSISTENT", "POSITION", "ROUTE", "SWAPS", "TEXT", "TIP",
           "TRANSITION", "TRANSITION_DEFAULTS", "TRANSITION_KINDS", "TRANSITION_PARAMS",
           "VARIABLE", "VARIABLE_KINDS", "VARIABLE_STARTS", "YES_NO", "Decl", "PositionRow",
           "character_call", "character_values", "codex_lines", "codex_ok", "color_ok",
           "find", "is_character_call", "is_transition_call", "line_for", "lines_for",
           "marks", "meter_line", "meter_ok", "meter_read", "meter_start", "name_problem",
           "position_point", "position_rows", "position_value", "read", "read_all",
           "route_line", "route_ok", "scan", "script_name", "shown_text", "statements",
           "taken_names", "transition_call", "transition_ok", "transition_try_lines",
           "transition_values", "transition_with", "unquote", "variable_values",
           "written_text"]
