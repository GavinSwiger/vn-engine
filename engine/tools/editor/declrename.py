"""Rename everywhere: a used Database entry gets a new script name, and every use in every
script file follows (F47 ``04-technical.md`` P3-B; design §4.3 "P3: rename everywhere";
AC-F47-52).

Why this module exists: PR-F47-10 let a name change only while nothing used it. Like RPG
Maker, a rename should follow every use. This is F46's scene rename pattern
(``scriptedit.rename_hits`` / ``plan_rename``) for declarations: find every use, refuse the
whole rename when a file can't be changed, ask "Rename `a` to `b`? N places in M files will
change.", then apply one ``scriptedit.Plan`` (one undo step per file).

- **Where uses are** comes from the real parser (each file parsed whole), never from a text
  search, so a word in dialogue or another kind's name never changes. Python code (``$``
  lines, conditions, ``define``/``default`` values, minigame arguments, ``points`` amounts)
  is read with ``ast``: a character, variable, transition or minigame data set is a bare
  name; a meter is ``points.n``, ``points["n"]`` or ``points.highest("n")``; a remembered
  variable is ``persistent.n``; a tip or item is ``"n" in codex.tips|items``.
- **Statement slots**: who speaks (a say line's first word), ``points n …``,
  ``lock|unlock tip|item n``, ``with n``, ``at n``, ``minigame … into n``, ``{var=n}`` and
  ``{username=n}`` tags, and the declaration itself. Positions also move their
  ``[stage.positions]`` key in config.toml (``tomlpatch``). F65 round 3: a contact is
  ``lock contact n`` and ``send … from n``; a message (a data set) is ``send n from …``
  and the string in ``inbox.reply("n")``.
- **A character's pictures stay where they are**: renaming one without ``image_tag`` writes
  ``image_tag="<old>"``, so ``show old smile`` and its ``images/old/`` folder keep working.
- **All or nothing**: a file that names the old name and can't be read whole (a parse
  problem) or is read-only refuses the whole rename; so does a clash.
- **Saves**: variables, meters and remembered variables are stored by name, so the Ask says
  plainly that older saves keep the old name (like F46's "Saves made inside this scene…").

Routes aren't renamed here: a route is named after its scene (``lock route <label>``).
Pure: no Tk, no file access.
"""

import ast
import re
import unicodedata
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Final

from engine.core.constants import BUILTIN_POSITIONS
from engine.script.codex import CodexLock
from engine.script.diagnostics import DiagnosticSink
from engine.script.effects import WithClause
from engine.script.inbox import ContactDecl, SendStep
from engine.script.messages import show
from engine.script.minigame import Minigame
from engine.script.nodes import Define, Default, PersistentDefault, PyCode, Say, ScriptFile
from engine.script.parser import parse_file
from engine.script.points import PointsChange
from engine.script.stage import At
from engine.script.statements import ParseContext
from engine.script.texttags import NameMark, TaggedText, VarMark
from engine.tools.editor import declarations as dec
from engine.tools.editor import tomlpatch
from engine.tools.editor.declplan import (
    BAD_NAME, KIND_WORDS, NAME_CLASH, POSITIONS_SECTION, problems)
from engine.tools.editor.forms import code_of
from engine.tools.editor.scriptedit import (
    CANCEL, FIX_FIRST, RENAME, UNSAFE, Ask, FilePlan, LineEdit, Plan, Refuse, apply_lines)
from engine.tools.editor.tomlpatch import TomlPlan

# --- Kinds and texts ---------------------------------------------------------------------------

DATA: Final = "data"          # a minigame data set: define n = [...] / {...}
CONFIG_REF: Final = "config.toml"
RENAMABLE: Final = frozenset((dec.CHARACTER, dec.VARIABLE, dec.PERSISTENT, dec.METER, dec.TIP,
                              dec.ITEM, dec.TRANSITION, dec.POSITION, dec.CONTACT, DATA))
_PYTHON_KINDS: Final = frozenset((dec.CHARACTER, dec.VARIABLE, dec.TRANSITION, DATA))

ASK: Final = "Rename `{old}` to `{new}`?"
PLACES: Final = "{places} in {files} will change."
SAVES_NOTE: Final = ("Saves made before this keep the old name, so in those saves `{new}` "
                     "starts again from its starting value.")
REMEMBERED_NOTE: Final = ("What the game remembered from earlier playthroughs keeps the old "
                          "name, so `{new}` starts again from its starting value.")
CODEX_NOTE: Final = ("Players who already unlocked it keep the old name, so they'll see it "
                     "locked again until the story unlocks it.")
CONTACT_NOTE: Final = ("Messages already in older saves stay in the thread with the same "
                       "name shown.")
PICTURES_NOTE: Final = "Its pictures stay in images/{old}/."
ROUTE_REFUSED: Final = ("A route is named after its scene. Rename the scene on the Story map "
                        "and change the route's lines in the text.")
BUILTIN_REFUSED: Final = "`{name}` is a built-in position, so it keeps its name."
CANT_RENAME: Final = "Studio can't rename this one. Change it in the text."
NOTES: Final[Mapping[str, str]] = MappingProxyType({
    dec.VARIABLE: SAVES_NOTE, dec.METER: SAVES_NOTE, dec.PERSISTENT: REMEMBERED_NOTE,
    dec.TIP: CODEX_NOTE, dec.ITEM: CODEX_NOTE, dec.CONTACT: CONTACT_NOTE})

_SINK_LIMIT: Final = 10_000
_DEPTH: Final = 12
_STRING: Final = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')


@dataclass(frozen=True, slots=True)
class Span:
    """Characters ``col0``..``col1`` (0-based, end excluded) of line ``line`` become ``text``."""

    line: int
    col0: int
    col1: int
    text: str


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """A rename: ``plan`` (one ``FilePlan`` per file; config.toml's too for a position),
    ``guards`` ``(ref, line, old text)`` that must still hold, ``toml`` the config.toml part
    (checked with ``tomlpatch.verify``), and ``places``/``files`` as the Ask counted them."""

    plan: Plan
    guards: tuple[tuple[str, int, str], ...]
    toml: TomlPlan | None
    kind: str
    old: str
    new: str
    places: int
    files: int


# --- Reading a file's nodes --------------------------------------------------------------------

def _parse(ref: str, text: str, positions: Collection[str]) -> tuple[list, int | None]:
    """The file's nodes and the line of its first problem (None: none)."""
    ctx = ParseContext(sink=DiagnosticSink(limit=_SINK_LIMIT),
                       position_names=frozenset(BUILTIN_POSITIONS) | frozenset(positions))
    nodes = parse_file(ScriptFile(ref, ref.removeprefix("script/"), 0), text, ctx)
    kept = ctx.sink.kept()
    return nodes, (kept[0].line or 1) if kept else None


def _walk(obj: object, line: int, end: int, depth: int = 0
          ) -> Iterator[tuple[object, int, int]]:
    """Every dataclass object under ``obj`` with the line range of its statement."""
    if depth > _DEPTH or obj is None or isinstance(obj, (str, int, float, bool, bytes)):
        return
    if isinstance(obj, (tuple, list)):
        for item in obj:
            yield from _walk(item, line, end, depth + 1)
        return
    if not is_dataclass(obj) or isinstance(obj, type) or isinstance(obj, ScriptFile):
        return
    own = getattr(obj, "line", None)
    if type(own) is int:
        line = own
        last = getattr(obj, "end_line", None)
        end = last if type(last) is int and last >= own else max(end, own)
    yield obj, line, end
    if isinstance(obj, PyCode):
        return
    for item in fields(obj):
        if item.name not in ("file", "sid", "label", "path"):
            yield from _walk(getattr(obj, item.name, None), line, end, depth + 1)


def _names(text: str, name: str) -> bool:
    """``name`` appears in ``text`` as a whole identifier (after NFKC)."""
    if not text.isascii():
        text = unicodedata.normalize("NFKC", text)
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) is not None


def _masked(line: str) -> str:
    """``line`` with its comment cut and each string's inside blanked (same length), so a
    search finds code words only."""
    code = line[:len(line) - len(code_of([line])[1])] if "#" in line else line
    return _STRING.sub(lambda m: m.group()[0] + "\0" * (len(m.group()) - 2) + m.group()[-1],
                       code)


# --- Python code (ast) -------------------------------------------------------------------------

def _col(rows: list[str], row: int, byte: int) -> int:
    """A code-point column in ``rows[row - 1]`` from ``ast``'s UTF-8 byte offset."""
    return len(rows[row - 1].encode("utf-8")[:byte].decode("utf-8", "replace"))


def _is(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _const(node: ast.AST, text: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == text


def _py_targets(tree: ast.AST, kind: str, old: str) -> Iterator[tuple[ast.AST, str]]:
    """``(node, how)``: ``how`` is "name" (the node's whole span is ``old``), "attr" (its
    attribute is ``old``, at its end) or "string" (a string literal holding ``old``)."""
    for node in ast.walk(tree):
        if kind in _PYTHON_KINDS and isinstance(node, ast.Name) and node.id == old:
            yield node, "name"
        elif kind == dec.VARIABLE and isinstance(node, ast.Call) \
                and _is(node.func, "Character"):
            for keyword in node.keywords:
                if keyword.arg == "name_from" and _const(keyword.value, old):
                    yield keyword.value, "string"
        elif kind in (dec.METER, dec.PERSISTENT) and isinstance(node, ast.Attribute) \
                and node.attr == old \
                and _is(node.value, "points" if kind == dec.METER else "persistent"):
            yield node, "attr"
        elif kind == dec.METER and isinstance(node, ast.Subscript) \
                and _is(node.value, "points") and _const(node.slice, old):
            yield node.slice, "string"
        elif kind == dec.METER and isinstance(node, ast.Call) \
                and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("highest", "rank") \
                and _is(node.func.value, "points"):
            for arg in node.args:
                if _const(arg, old):
                    yield arg, "string"
        elif kind == DATA and isinstance(node, ast.Call) \
                and isinstance(node.func, ast.Attribute) and node.func.attr == "reply" \
                and _is(node.func.value, "inbox"):
            for arg in node.args[:1]:                   # inbox.reply("<message>")
                if _const(arg, old):
                    yield arg, "string"
        elif kind in (dec.TIP, dec.ITEM) and isinstance(node, ast.Compare) \
                and _const(node.left, old) and len(node.comparators) == 1:
            view = node.comparators[0]
            if isinstance(view, ast.Attribute) and _is(view.value, "codex") \
                    and view.attr == ("tips" if kind == dec.TIP else "items"):
                yield node.left, "string"


def _py_spans(py: PyCode, kind: str, old: str, new: str, lines: list[str]
              ) -> list[Span] | None:
    """The spans of ``py`` naming ``old``; None when one can't be placed safely."""
    try:
        tree = ast.parse(py.source, mode=py.mode)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return []
    rows = py.source.split("\n")
    out: list[Span] = []
    for node, how in _py_targets(tree, kind, old):
        row, end_row = node.lineno, node.end_lineno            # type: ignore[attr-defined]
        if row != end_row:
            return None
        c0 = _col(rows, row, node.col_offset)                  # type: ignore[attr-defined]
        c1 = _col(rows, row, node.end_col_offset)              # type: ignore[attr-defined]
        if how == "attr":
            c0 = c1 - len(old)
        elif how == "string":
            c0, c1 = c0 + 1, c1 - 1                            # inside the quotes
        line = py.line + row - 1
        shift = py.column - 1 if row == 1 else 0
        if line > len(lines) or lines[line - 1][shift + c0:shift + c1] != old:
            return None
        out.append(Span(line, shift + c0, shift + c1, new))
    return out


# --- Statement slots ---------------------------------------------------------------------------

def _regex_spans(lines: list[str], first: int, last: int, pattern: str, new: str,
                 masked: bool = True) -> list[Span]:
    """Group 1 of each ``pattern`` match on lines ``first``..``last``."""
    out: list[Span] = []
    for number in range(first, min(last, len(lines)) + 1):
        line = lines[number - 1]
        hay = _masked(line) if masked else line
        for match in re.finditer(pattern, hay):
            out.append(Span(number, match.start(1), match.end(1), new))
    return out


def _word(old: str) -> str:
    return "(" + re.escape(old) + r")(?!\w)"


_TAG: Final = ", image_tag="


def _keep_pictures(py: PyCode, old: str, lines: list[str]) -> list[Span]:
    """A ``Character(...)`` without ``image_tag``: ``, image_tag="<old>"`` inserted before
    its closing bracket, so its pictures (``images/<old>/``, ``show old …``) keep working."""
    try:
        call = ast.parse(py.source, mode="eval").body
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return []
    if not isinstance(call, ast.Call) or not _is(call.func, "Character") \
            or any(k.arg in ("image_tag", None) for k in call.keywords):
        return []
    rows = py.source.split("\n")
    row = call.end_lineno or 1
    col = _col(rows, row, (call.end_col_offset or 1) - 1)
    line = py.line + row - 1
    col += py.column - 1 if row == 1 else 0
    if line > len(lines) or lines[line - 1][col:col + 1] != ")":
        return []
    text = _TAG + '"' + old + '"' if call.args or call.keywords else _TAG[2:] + '"' + old + '"'
    return [Span(line, col, col, text)]


def _slot_spans(obj: object, line: int, end: int, kind: str, old: str, new: str,
                lines: list[str]) -> list[Span]:
    """The non-Python places ``obj`` (a node of the parse) names ``old``."""
    w = _word(old)
    if kind in _PYTHON_KINDS and isinstance(obj, (Define, Default)) and obj.name == old \
            and not isinstance(obj, PersistentDefault):
        keyword = "define" if isinstance(obj, Define) else "default"
        spans = _regex_spans(lines, line, line, rf"^[ \t]*{keyword}[ \t]+{w}", new)
        if kind == dec.CHARACTER and isinstance(obj, Define):
            spans += _keep_pictures(obj.value, old, lines)
        return spans
    if kind == dec.PERSISTENT and isinstance(obj, PersistentDefault) and obj.name == old:
        return _regex_spans(lines, line, line, rf"^[ \t]*default[ \t]+persistent[ \t]*\.[ \t]*{w}",
                            new)
    if kind == dec.CHARACTER and isinstance(obj, Say) and obj.speaker == old:
        return _regex_spans(lines, line, line, rf"^[ \t]*{w}", new)
    if kind == dec.VARIABLE and isinstance(obj, TaggedText):
        if any((isinstance(p, VarMark) and p.name == old)
               or (isinstance(p, NameMark) and p.var == old) for p in obj.pieces):
            return _regex_spans(lines, line, end, rf"\{{(?:var|username)[ \t]*=[ \t]*{w}", new,
                                masked=False)
        return []
    if kind == dec.VARIABLE and isinstance(obj, Minigame) and obj.target == old:
        return _regex_spans(lines, line, end, rf"(?<!\w)into[ \t]+{w}", new)
    if kind == dec.METER and isinstance(obj, PointsChange) and obj.name == old:
        return _regex_spans(lines, line, line, rf"^[ \t]*points[ \t]+{w}", new)
    if kind == dec.METER and type(obj).__name__ == "PointsDecl" \
            and old in getattr(obj, "names", ()):
        spans = _regex_spans(lines, line, line, rf"(?<![\w.]){w}", new)
        return [s for s in spans if s.col0 > len(lines[line - 1]) - len(
            lines[line - 1].lstrip()) + len("points")]
    if kind in (dec.TIP, dec.ITEM) and getattr(obj, "kind", None) == kind \
            and getattr(obj, "name", None) == old \
            and (isinstance(obj, CodexLock) or type(obj).__name__ == "CodexEntryDecl"):
        return _regex_spans(lines, line, line, rf"^[ \t]*(?:lock|unlock)[ \t]+{kind}[ \t]+{w}",
                            new)
    if kind == dec.TRANSITION and isinstance(obj, WithClause) and obj.name == old:
        return _regex_spans(lines, line, line, rf"(?<!\w)with[ \t]+{w}", new)
    if kind == dec.POSITION and isinstance(obj, At) and obj.name == old:
        return _regex_spans(lines, line, end, rf"(?<!\w)at[ \t]+{w}", new)
    if kind == dec.CONTACT and isinstance(obj, ContactDecl) and obj.name == old:
        return _regex_spans(lines, line, line, rf"^[ \t]*lock[ \t]+contact[ \t]+{w}", new)
    if kind == dec.CONTACT and isinstance(obj, SendStep) and obj.contact == old:
        return _regex_spans(lines, line, line, rf"(?<!\w)from[ \t]+{w}", new)
    if kind == DATA and isinstance(obj, SendStep) and obj.message == old:
        return _regex_spans(lines, line, line, rf"^[ \t]*send[ \t]+{w}", new)
    return []


# --- Finding the places ------------------------------------------------------------------------

def file_spans(ref: str, text: str, kind: str, old: str, new: str,
               positions: Collection[str] = ()) -> list[Span] | Refuse:
    """Every place ``ref``'s ``text`` names ``kind`` ``old``, as spans that write ``new``;
    a Refuse when the file can't be read whole or a place can't be changed safely."""
    if not _names(text, old):
        return []
    lines = text.split("\n")
    nodes, problem = _parse(ref, text, {*positions, old, new})
    if problem is not None:
        return Refuse(FIX_FIRST.format(file=show(ref.removeprefix("script/")), line=problem),
                      (ref, problem))
    found: dict[tuple[int, int], Span] = {}
    for obj, line, end in _walk(nodes, 1, 1):
        if isinstance(obj, PyCode):
            spans = _py_spans(obj, kind, old, new, lines)
            if spans is None:
                return Refuse(UNSAFE, (ref, obj.line))
        else:
            spans = _slot_spans(obj, line, end, kind, old, new, lines)
        for span in spans:
            found[(span.line, span.col0)] = span
    return sorted(found.values(), key=lambda s: (s.line, s.col0))


def _apply_spans(line: str, spans: Iterable[Span]) -> str:
    for span in sorted(spans, key=lambda s: -s.col0):
        line = line[:span.col0] + span.text + line[span.col1:]
    return line


def _python_names(texts: Mapping[str, str], name: str, positions: Collection[str]) -> bool:
    """True when some Python code already names ``name`` (a clash with an undeclared one)."""
    for ref, text in texts.items():
        if not _names(text, name):
            continue
        nodes, _ = _parse(ref, text, positions)
        for obj, _l, _e in _walk(nodes, 1, 1):
            if isinstance(obj, PyCode):
                try:
                    tree = ast.parse(obj.source, mode=obj.mode)
                except (SyntaxError, ValueError, MemoryError, RecursionError):
                    continue
                if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(tree)):
                    return True
    return False


# --- The plan ----------------------------------------------------------------------------------

def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _name_check(kind: str, old: str, new: str, texts: Mapping[str, str],
                taken: Collection[str], positions: Collection[str]) -> Refuse | None:
    if dec.name_problem(new, dec.DEFINE if kind == DATA else kind):
        return Refuse(BAD_NAME.format(name=new))
    space = dec.taken_names(dec.scan(texts), dec.VARIABLE if kind == DATA else kind)
    folded = {n.casefold() for n in (*space, *taken) if n != old}
    if new.casefold() in folded and new.casefold() != old.casefold():
        return Refuse(NAME_CLASH.format(name=new))
    if kind in _PYTHON_KINDS and _python_names(texts, new, positions):
        return Refuse(NAME_CLASH.format(name=new))
    return None


def plan_rename(kind: str, old: str, new: str, texts: Mapping[str, str], *,
                locked: Mapping[str, str] = MappingProxyType({}),
                config_text: str | None = None, positions: Collection[str] = (),
                taken: Collection[str] = (), confirm: bool = False
                ) -> RenamePlan | Ask | Refuse | None:
    """Rename ``kind`` entry ``old`` to ``new`` in every script of ``texts`` (ref → editor
    text) and, for a position, config.toml's ``config_text``. ``locked``: ref → F44's
    read-only reason; ``positions``: the story's position names; ``taken``: more names the
    new one may not take (a minigame data set's siblings). Without ``confirm``, an Ask with
    the count and the save note; with it, the plan. None: the name is the same."""
    new = new.strip()
    if kind == dec.ROUTE:
        return Refuse(ROUTE_REFUSED)
    if kind not in RENAMABLE:
        return Refuse(CANT_RENAME)
    if new == old:
        return None
    if kind == dec.POSITION and old in BUILTIN_POSITIONS:
        return Refuse(BUILTIN_REFUSED.format(name=old))
    refusal = _name_check(kind, old, new, texts, taken, positions)
    if refusal is not None:
        return refusal
    files: list[FilePlan] = []
    guards: list[tuple[str, int, str]] = []
    places = 0
    pictures = False
    for ref, text in texts.items():
        spans = file_spans(ref, text, kind, old, new, positions)
        if ref in locked and (isinstance(spans, Refuse) or spans):
            return Refuse(locked[ref], (ref, 1))
        if isinstance(spans, Refuse):
            return spans
        if not spans:
            continue
        lines = text.split("\n")
        pictures = pictures or any("image_tag=" in span.text for span in spans)
        by_line: dict[int, list[Span]] = {}
        for span in spans:
            by_line.setdefault(span.line, []).append(span)
        edits: list[LineEdit] = []
        for number, group in sorted(by_line.items()):
            guards.append((ref, number, lines[number - 1]))
            edits.append(LineEdit(number, number, (_apply_spans(lines[number - 1], group),)))
            places += 1
        files.append(FilePlan(ref, (), tuple(edits)))
    toml: TomlPlan | None = None
    if kind == dec.POSITION:
        if config_text is None:
            return Refuse(CANT_RENAME)
        row = next((r for r in dec.position_rows(config_text) or () if r.name == old), None)
        if row is None or row.x is None or not row.written:
            return Refuse(CANT_RENAME)
        changed = tomlpatch.plan_changes(
            config_text, [(POSITIONS_SECTION, old, None),
                          (POSITIONS_SECTION, new, dec.position_value(row.x, row.y))],
            title=f"Rename {KIND_WORDS[kind]} {old}")
        if isinstance(changed, Refuse):
            return changed
        if changed is not None:
            if CONFIG_REF in locked:
                return Refuse(locked[CONFIG_REF], (CONFIG_REF, 1))
            toml = changed
            files.append(toml.as_plan().files[0])
            places += 1
    if not confirm:
        parts = [ASK.format(old=show(old), new=show(new)),
                 PLACES.format(places=_count(places, "place"), files=_count(len(files), "file"))]
        note = NOTES.get(kind)
        if note is not None:
            parts.append(note.format(new=show(new)))
        if pictures:
            parts.append(PICTURES_NOTE.format(old=old))
        return Ask(" ".join(parts), (RENAME, CANCEL), escape=1, default=1)
    title = f"Rename {KIND_WORDS.get(kind, 'data set')} {old}"
    return RenamePlan(Plan(title, tuple(files)), tuple(guards), toml, kind, old, new, places,
                      len(files))


def verify_rename(rename: RenamePlan, texts: Mapping[str, str],
                  positions: Collection[str] = ()) -> bool:
    """True when ``rename`` still fits ``texts`` (every guarded line as planned), each
    changed script parses with no new problem, and the old name's places are gone. Never
    raises."""
    try:
        guards = {(ref, line): text for ref, line, text in rename.guards}
        for file_plan in rename.plan.files:
            text = texts.get(file_plan.ref)
            if text is None:
                return False
            if rename.toml is not None and file_plan.ref == rename.toml.ref:
                if not tomlpatch.verify(rename.toml, text):
                    return False
                continue
            lines = text.split("\n")
            for (ref, line), want in guards.items():
                if ref == file_plan.ref and (line > len(lines) or lines[line - 1] != want):
                    return False
            new = "\n".join(apply_lines(lines, file_plan.edits))
            if problems(file_plan.ref, new) - problems(file_plan.ref, text) \
                    or _parse(file_plan.ref, new, {*positions, rename.new})[1] is not None:
                return False
            left = file_spans(file_plan.ref, new, rename.kind, rename.old, rename.new,
                              {*positions, rename.new})
            if isinstance(left, Refuse) or left:
                return False
        return True
    except Exception:          # a planner bug must never reach the text (TR-F46-03)
        return False


__all__ = ["ASK", "BUILTIN_REFUSED", "CANT_RENAME", "CODEX_NOTE", "CONFIG_REF", "DATA",
           "CONTACT_NOTE", "NOTES", "PICTURES_NOTE", "PLACES", "REMEMBERED_NOTE", "RENAMABLE",
           "ROUTE_REFUSED", "SAVES_NOTE", "RenamePlan", "Span", "file_spans", "plan_rename",
           "verify_rename"]
