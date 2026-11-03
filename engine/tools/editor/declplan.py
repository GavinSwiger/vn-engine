"""Plans for the Database's writes: new, edit and delete a declaration (F47 ``04-technical.md``
§3.1, §7.1; design PR-F47-01, PR-F47-03, decision 3; AC-F47-05..08, 14).

Why this module exists: a Database change is ordinary line edits in open documents, made
like F46's map and Events actions: a ``scriptedit.Plan`` (one ``FilePlan`` per file, so one
undo step per file), checked against the live texts right before it is applied.

- **Where new lines go** (decision 3): ``script/database.vns`` (``DATABASE_REF``), after the
  last declaration of the same kind there, else at its end. When the file is missing, the plan
  is made against the editor text of ``DATABASE_TEXT`` and says so (``DeclPlan.create``): the caller writes that
  file with exactly ``DATABASE_TEXT``, opens it, then verifies and applies the plan. When no
  script includes it, the plan also inserts ``include "database.vns"`` into ``main.vns`` at
  ``files.include_position`` (once: the next plan sees the include).
- **Edits stay where the declaration is**: only its line(s) are replaced, by one line that
  keeps the trailing comment.
- **Stale-safe** (§7.1 step 4). Declarations sit outside F46's chunk digests, so each plan
  carries line guards (the old text of each line it replaces) and the line count of each
  file it inserts into. ``verify_decl`` fails when a guard no longer holds, when the changed
  file's declarations parse with a problem they didn't have, or when ``declarations.scan``
  doesn't read back the written values. The caller then shows ``scriptedit.STALE``.

``texts`` maps every script ref (open or on disk) to its editor text (LF lines). Pure: no Tk,
no file access.
"""

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from engine.script.diagnostics import DiagnosticSink
from engine.script.nodes import ScriptFile
from engine.script.parser import parse_file
from engine.script.statements import ParseContext
from engine.tools.editor import declarations as dec
from engine.tools.editor.files import MAIN_REF, include_line, include_position
from engine.tools.editor.forms import code_of
from engine.tools.editor.scriptedit import STALE, FilePlan, LineEdit, Plan, Refuse, apply_lines

# --- Decision 3 and texts (design §6.4) --------------------------------------------------------

DATABASE_REF: Final = "script/database.vns"
DATABASE_INCLUDE: Final = "database.vns"                     # as an include line names it
DATABASE_HEADER: Final = "# Made in Studio's Database. You can also edit it by hand."
DATABASE_TEXT: Final = DATABASE_HEADER + "\n"    # a new database.vns's bytes (UTF-8)

NAME_CLASH: Final = "There's already something called {name}. Pick another name."
BAD_NAME: Final = "{name} can't be used as a name in the script. Pick another name."
COMPLEX: Final = "This one is written in a way the form can't edit."
CANT_WRITE: Final = "Studio can't write that value. Check the fields and try again."
NO_MAIN: Final = "main.vns can't be found, so Studio can't add the Database to the story."

KIND_WORDS: Final[Mapping[str, str]] = {
    dec.CHARACTER: "character", dec.COLOR: "colour background", dec.VARIABLE: "variable"}

_INCLUDE: Final = re.compile(r'include[ \t]+"([^"\n]*)"')
_SINK_LIMIT: Final = 10_000


@dataclass(frozen=True, slots=True)
class DeclPlan:
    """A Database write. ``plan`` is applied as usual (one undo step per ``FilePlan``);
    ``guards`` are ``(ref, line, text)`` that must still hold and ``sizes`` ``(ref, line
    count)``; ``create`` is ``DATABASE_REF`` when that file must first be created holding
    ``DATABASE_TEXT``. ``kind``/``name``/``ref`` say what ``verify_decl`` reads back:
    ``values`` (None: the declaration is gone) and ``count``, how many ``kind`` ``name``
    declarations ``ref`` holds afterwards."""

    plan: Plan
    guards: tuple[tuple[str, int, str], ...]
    sizes: tuple[tuple[str, int], ...]
    create: str | None
    kind: str
    name: str
    ref: str
    values: Mapping[str, object] | None
    count: int


# --- Helpers -----------------------------------------------------------------------------------

def includes_database(texts: Mapping[str, str]) -> bool:
    """True when a script has a top-level ``include "database.vns"``."""
    for text in texts.values():
        for line in text.split("\n"):
            match = _INCLUDE.match(line)
            if match is not None and match.group(1).strip().casefold() == DATABASE_INCLUDE:
                return True
    return False


def _count(text: str, kind: str, name: str, ref: str) -> int:
    return sum(1 for d in dec.scan({ref: text}) if d.kind == kind and d.name == name)


def _expected(kind: str, name: str, line: str) -> Mapping[str, object] | None:
    """The values ``line`` reads back as (None when it doesn't read as ``kind`` ``name``)."""
    decl = dec.read("", 1, 1, [line])
    if decl is None or decl.kind != kind or decl.name != name:
        return None
    return decl.values


def _name_refusal(kind: str, name: str, texts: Mapping[str, str],
                  old: str | None = None) -> Refuse | None:
    if dec.name_problem(name, kind):
        return Refuse(BAD_NAME.format(name=name))
    taken = {n.casefold() for n in dec.taken_names(dec.scan(texts), kind)}
    if name.casefold() in taken and (old is None or name.casefold() != old.casefold()):
        return Refuse(NAME_CLASH.format(name=name))
    return None


def _title(verb: str, kind: str, name: str) -> str:
    return f"{verb} {KIND_WORDS.get(kind, kind)} {name}"


# --- Planners ----------------------------------------------------------------------------------

def plan_new(kind: str, name: str, values: Mapping[str, object],
             texts: Mapping[str, str]) -> DeclPlan | Refuse:
    """Add a ``kind`` declaration of ``name`` (from ``declarations.script_name``) to
    ``database.vns``, with the include line when no script has one."""
    refusal = _name_refusal(kind, name, texts)
    if refusal is not None:
        return refusal
    try:
        line = dec.line_for(kind, name, values)
    except ValueError:
        return Refuse(CANT_WRITE)
    expected = _expected(kind, name, line)
    if expected is None:
        return Refuse(CANT_WRITE)
    db_text = texts.get(DATABASE_REF)
    create = None
    if db_text is None:
        db_text, create = DATABASE_HEADER, DATABASE_REF  # the editor's text of DATABASE_TEXT
    lines = db_text.split("\n")
    same = [d for d in dec.scan({DATABASE_REF: db_text}) if d.kind == kind]
    guards: list[tuple[str, int, str]] = []
    if lines == [""]:                                  # an empty file: its one line
        edit = LineEdit(1, 1, (line,))
        guards.append((DATABASE_REF, 1, ""))
    else:
        at = same[-1].last + 1 if same else len(lines) + 1
        edit = LineEdit(at, at - 1, (line,))
        guards.append((DATABASE_REF, at - 1, lines[at - 2]))
    sizes = [(DATABASE_REF, len(lines))]
    files = [FilePlan(DATABASE_REF, (), (edit,))]
    if not includes_database(texts):
        main = texts.get(MAIN_REF)
        if main is None:
            return Refuse(NO_MAIN)
        main_lines = main.split("\n")
        pos = include_position(main)
        files.append(FilePlan(MAIN_REF, (), (
            LineEdit(pos, pos - 1, (include_line(DATABASE_REF),)),)))
        sizes.append((MAIN_REF, len(main_lines)))
        if pos > 1:
            guards.append((MAIN_REF, pos - 1, main_lines[pos - 2]))
    count = _count(db_text, kind, name, DATABASE_REF) + 1
    return DeclPlan(Plan(_title("Add", kind, name), tuple(files)), tuple(guards), tuple(sizes),
                    create, kind, name, DATABASE_REF, expected, count)


def _current(decl: dec.Decl, texts: Mapping[str, str]) -> list[str] | Refuse:
    """The declaration's lines as the text holds them now, or a Refuse."""
    text = texts.get(decl.ref)
    if text is None:
        return Refuse(STALE)
    lines = text.split("\n")
    if decl.last > len(lines):
        return Refuse(STALE)
    now = dec.read(decl.ref, decl.first, decl.last, lines[decl.first - 1:decl.last])
    if now != decl:
        return Refuse(STALE)
    return lines


def plan_edit(decl: dec.Decl, values: Mapping[str, object], texts: Mapping[str, str],
              name: str | None = None) -> DeclPlan | Refuse | None:
    """Rewrite ``decl``'s line(s) as one line with ``values`` (and, while the entry is
    unused, a new ``name``), keeping its trailing comment. None: the values (and name)
    are the ones it has, so nothing is written."""
    if decl.kind not in dec.EDITABLE_KINDS or decl.values is None:
        return Refuse(COMPLEX)
    lines = _current(decl, texts)
    if isinstance(lines, Refuse):
        return lines
    new_name = decl.name if name is None else name
    if new_name != decl.name:
        refusal = _name_refusal(decl.kind, new_name, texts, old=decl.name)
        if refusal is not None:
            return refusal
    try:
        code = dec.line_for(decl.kind, new_name, values)
    except ValueError:
        return Refuse(CANT_WRITE)
    expected = _expected(decl.kind, new_name, code)
    if expected is None:
        return Refuse(CANT_WRITE)
    if new_name == decl.name and expected == decl.values:
        return None                        # same values: the line stays as written
    old = lines[decl.first - 1:decl.last]
    _code, comment = code_of(old)
    new_line = code + comment
    guards = tuple((decl.ref, decl.first + k, text) for k, text in enumerate(old))
    text = texts[decl.ref]
    count = _count(text, decl.kind, new_name, decl.ref) + (new_name != decl.name)
    plan = Plan(_title("Change", decl.kind, new_name),
                (FilePlan(decl.ref, (), (LineEdit(decl.first, decl.last, (new_line,)),)),))
    return DeclPlan(plan, guards, (), None, decl.kind, new_name, decl.ref, expected, count)


def plan_delete(decl: dec.Decl, texts: Mapping[str, str]) -> DeclPlan | Refuse:
    """Remove ``decl``'s line(s). The caller refuses first while it is used
    (``dbmodel.delete_refusal``)."""
    lines = _current(decl, texts)
    if isinstance(lines, Refuse):
        return lines
    old = lines[decl.first - 1:decl.last]
    guards = tuple((decl.ref, decl.first + k, text) for k, text in enumerate(old))
    count = _count(texts[decl.ref], decl.kind, decl.name, decl.ref) - 1
    plan = Plan(_title("Delete", decl.kind, decl.name),
                (FilePlan(decl.ref, (), (LineEdit(decl.first, decl.last, ()),)),))
    return DeclPlan(plan, guards, (), None, decl.kind, decl.name, decl.ref, None, count)


# --- Verifying (§7.1 step 4) -------------------------------------------------------------------

def _declaration_text(text: str) -> str:
    """``text`` with only its top-level declarations and include lines kept (every other
    line blank, so line numbers hold): what a Database write can change."""
    lines = text.split("\n")
    out = [""] * len(lines)
    for first, last, _ in dec.statements(text):
        out[first - 1:last] = lines[first - 1:last]
    for number, line in enumerate(lines):
        if _INCLUDE.match(line):
            out[number] = line
    return "\n".join(out)


def problems(ref: str, text: str) -> Counter[str]:
    """The parser's problem codes for ``text``'s declarations (``_declaration_text``)."""
    ctx = ParseContext(sink=DiagnosticSink(limit=_SINK_LIMIT))
    parse_file(ScriptFile(ref, ref.removeprefix("script/"), 0), _declaration_text(text), ctx)
    return Counter(diag.code for diag in ctx.sink.kept())


def verify_decl(decl_plan: DeclPlan, texts: Mapping[str, str]) -> bool:
    """True when ``decl_plan`` still fits ``texts`` and writes what it says. Never raises."""
    try:
        guards = {(ref, line): text for ref, line, text in decl_plan.guards}
        sizes = dict(decl_plan.sizes)
        after: dict[str, str] = {}
        for file_plan in decl_plan.plan.files:
            text = texts.get(file_plan.ref)
            if text is None:
                return False
            lines = text.split("\n")
            if file_plan.ref in sizes and len(lines) != sizes[file_plan.ref]:
                return False
            for (ref, line), want in guards.items():
                if ref == file_plan.ref and (line > len(lines) or lines[line - 1] != want):
                    return False
            new = "\n".join(apply_lines(lines, file_plan.edits))
            if problems(file_plan.ref, new) - problems(file_plan.ref, text):
                return False
            after[file_plan.ref] = new
        if decl_plan.ref not in after:
            return False
        found = [d for d in dec.scan({decl_plan.ref: after[decl_plan.ref]})
                 if d.kind == decl_plan.kind and d.name == decl_plan.name]
        if len(found) != decl_plan.count:
            return False
        return decl_plan.values is None or any(d.values == decl_plan.values for d in found)
    except Exception:          # a planner bug must never reach the text (TR-F46-03)
        return False


__all__ = ["BAD_NAME", "CANT_WRITE", "COMPLEX", "DATABASE_HEADER", "DATABASE_INCLUDE",
           "DATABASE_REF", "DATABASE_TEXT", "KIND_WORDS", "NAME_CLASH", "NO_MAIN", "DeclPlan",
           "includes_database", "plan_delete", "plan_edit", "plan_new", "problems",
           "verify_decl"]
