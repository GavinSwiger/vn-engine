"""Studio's edit engine: every story-map and Events action as a plan of line edits (F46
``04-technical.md`` §3.2, §4, §6.2-§6.7; ``06`` AC-F46-11, 12, 17, 28-31, 35, 38, 40, 41).

Why this module exists: the ``.vns`` text stays the only truth, so an action never rebuilds a
scene. It plans the few physical lines that change, guarded by the scene's chunk digest, and
the caller checks the plan (``verify``: re-parse the changed chunks in memory, then the
action's own ``expect``) before applying it to the file's ``tk.Text`` as one undo step. Pure:
no Tk, no file access.

- Planners take ``(scene, lines, start, ...)``: a fresh ``SceneRead``, the file's lines as the
  editor holds them (``text.split("\\n")``, no endings: ``document.encode`` gives them the
  file's endings and BOM again), and the absolute line of the scene's label line. They return
  a ``Plan``, an ``Ask`` (plan again with the answer: ``choice=True`` / ``confirm=True``), a
  ``Refuse``, or None when there is nothing to write.
- Rows (``forms.Row``) are duck-typed: ``row.stmt`` indexes ``scene.statements`` (None: the ◆
  row ending ``scene.blocks[row.block]``). A choice or an ``if`` branch header row has
  ``row.stmt`` = the menu's (or ``if``'s) statement and ``row.block`` = that choice's (branch's)
  block, so ``scene.blocks[row.block].owner == scene.statements[row.stmt].path``.
- Indents: new lines take their block's indent, else ``unit`` (the file's
  ``syntax.indent_unit``), which the caller passes.
- Rename (§6.5) edits only ``RENAME_SLOTS`` words and the label line. Python code that names
  the scene (``$`` lines, conditions, ``define``/``default`` values, a name in a string) is
  counted and never changed.
"""

import re
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from engine.script.flowchart import Flowchart
from engine.script.labelgraph import LINK_RULES, LabelLink
from engine.script.menu import MENU_MAX_CHOICES, Menu
from engine.script.messages import show
from engine.script.nodes import Call, If, Jump, PythonLine, Return, Statement
from engine.script.words import canonical_name
from engine.tools.editor.files import label_problem
from engine.tools.editor.scenes import (
    LABEL_START, SCENE_TOO_LONG, BlockRead, SceneRead, chunks, digest, parse_chunk)

# --- Texts (design §6.5, 04 §17.3, 07 §6) -----------------------------------------------------

UNSAFE: Final = "Studio couldn't make this change safely. Change it in the text."
STALE: Final = "This scene changed in the text, so nothing was changed. Try again."
FIX_FIRST: Final = "Fix the problem in `{file}`, line {line} first."
MAKE_CHOICE: Final = "`{src}` already goes to `{dst}`. Turn this into a choice?"
RETURN_REPLACED: Final = "Replaced 'return' with 'go to `{dst}`'."
TOO_MANY_CHOICES: Final = "A choice can have at most 6 options."
FROM_IF: Final = "This arrow comes from a line inside an 'if'. Change it in the text."
FROM_MANY: Final = "This arrow comes from {count} lines. Change them in the text."
EMPTIES_CHOICE: Final = ("Deleting this arrow would leave the choice with nothing in it. "
                         "Delete the choice instead.")
EMPTIES_SCENE: Final = ("Deleting this arrow would leave the scene with nothing in it. "
                        "Delete the scene instead.")
DELETE_CHOICE: Final = 'Delete the choice "{text}" and its {lines}?'
DELETE_INSIDE: Final = "This row has {lines} inside it. Delete them all?"
DELETE_SCENE: Final = "Delete the scene `{name}` and its {lines}?"
ARROWS_IN: Final = "{arrows} here; those lines will show an error until you change them."
DELETE_START: Final = "The start scene can't be deleted. It's where the story begins."
NAME_TAKEN: Final = "There is already a scene named `{name}`."
RENAME_START: Final = "The story starts at `start`, so it keeps its name."
RENAME_ASK: Final = "Rename `{old}` to `{new}`?"
RENAME_SLOTS_TEXT: Final = "{lines} that {verb} to it {change} too."
RENAME_PYTHON: Final = "Python code that names it doesn't."
RENAME_PLACES: Final = "({places}, first `{file}`, line {line})"
RENAME_SAVES: Final = "Saves made inside this scene will start it from the beginning."
AT_TOP: Final = "Already at the top."
AT_BOTTOM: Final = "Already at the bottom."
PLACEHOLDER: Final = "(Write what happens in this scene.)"

DELETE: Final = "Delete"
CANCEL: Final = "Cancel"
RENAME: Final = "Rename"
MAKE_CHOICE_BUTTON: Final = "Make a choice"
GRID: Final = 20                                    # px, new-box snap (04 §6.6)
START: Final = "start"
THEN_CHOICE_TEXT: Final = "choice_text"

EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})

# After a plan: ref → label → the read of every chunk the plan changed or guarded.
After = Mapping[str, Mapping[str, SceneRead]]
Expect = Callable[[After], bool]


# --- Plans (§3.2) ------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class LineEdit:
    """Absolute lines ``first``..``last`` replaced by ``lines``; ``last == first - 1``
    inserts before ``first`` (``first = len + 1`` appends)."""

    first: int
    last: int
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FilePlan:
    ref: str
    guards: tuple[tuple[str, bytes], ...]             # (scene, digest) planned from
    edits: tuple[LineEdit, ...]                       # non-overlapping
    select: tuple[int, int, int] | None = None        # (line, col0, col1) afterwards


@dataclass(frozen=True, slots=True)
class Plan:
    title: str                                        # map-history title
    files: tuple[FilePlan, ...]
    places: Mapping[str, tuple[int, int] | None] = EMPTY
    status: str | None = None
    then: tuple[str, str] | None = None               # ("choice_text", target): opens next
    expect: Expect | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class Ask:
    """Ask, then plan again with the answer."""

    text: str
    buttons: tuple[str, ...]
    escape: int
    default: int


@dataclass(frozen=True, slots=True)
class Refuse:
    text: str
    place: tuple[str, int] | None = None              # "Open text" / link target (ref, line)


Result = Plan | Ask | Refuse | None


def _flowchart_target(node: Statement) -> str | None:
    return node.target if node.form == "forget" else None   # type: ignore[attr-defined]


# type → (getter of the label it names, index of that word on the line), TR-F46-08.
RENAME_SLOTS: Final[Mapping[type, tuple[Callable[[Statement], str | None], int]]] = \
    MappingProxyType({
        **{node_type: (getter, 1) for node_type, getter in LINK_RULES.values()},
        Flowchart: (_flowchart_target, 2),
    })


# --- Applying and verifying (§6.3.4) -----------------------------------------------------------

def apply_lines(lines: list[str], edits: Sequence[LineEdit]) -> list[str]:
    """A copy of ``lines`` with ``edits`` applied. Raises ValueError on edits that overlap or
    fall outside the lines."""
    out = list(lines)
    ordered = sorted(edits, key=lambda e: (e.first, e.last))
    floor = 0
    for edit in ordered:
        if edit.last < edit.first - 1 or edit.first < 1 or edit.last > len(lines) \
                or edit.first <= floor:
            raise ValueError(f"bad edit {edit!r}")
        floor = max(floor, edit.last)
    for edit in reversed(ordered):
        out[edit.first - 1:edit.last] = list(edit.lines)
    return out


def _chunk_texts(lines: Sequence[str]) -> list[tuple[str, int, int, str]]:
    """``(label, first, last, chunk text)`` per chunk, the text as ``scenes`` digests it."""
    out = []
    for name, first, last in chunks("\n".join(lines)):
        text = "\n".join(lines[first - 1:last])
        if last < len(lines):
            text += "\n"
        out.append((name, first, last, text))
    return out


def verify(plan: Plan, texts: Mapping[str, str], expect: Expect | None = None,
           positions: Collection[str] = ()) -> bool:
    """True when ``plan`` still fits ``texts`` (ref → editor text; every guard's chunk has
    its digest), every chunk it changes re-parses without error, and ``expect`` (else the
    plan's own) holds. Never raises."""
    check = expect if expect is not None else plan.expect
    after: dict[str, dict[str, SceneRead]] = {}
    try:
        for file_plan in plan.files:
            text = texts.get(file_plan.ref)
            if text is None:
                return False
            old = text.split("\n")
            before = _chunk_texts(old)
            first_digest: dict[str, bytes] = {}
            for name, _, _, chunk in before:
                first_digest.setdefault(name, digest(chunk))
            if any(first_digest.get(name) != want for name, want in file_plan.guards):
                return False
            old_digests = {digest(chunk) for *_, chunk in before}
            old_bare = {chunk.rstrip() for *_, chunk in before}
            guarded = {name for name, _ in file_plan.guards}
            reads = after.setdefault(file_plan.ref, {})
            for name, _, _, chunk in _chunk_texts(apply_lines(old, file_plan.edits)):
                if name in reads:
                    continue
                if digest(chunk) in old_digests and name not in guarded:
                    continue
                read = parse_chunk(file_plan.ref, chunk, positions=positions)
                if read is None or read.error is not None:
                    if chunk.rstrip() in old_bare:
                        # Broken before, and the plan only added blank lines after it (a
                        # new scene after F45's new file's lone ``label x:``).
                        continue
                    return False
                reads[name] = read
        return check is None or bool(check(after))
    except Exception:          # a planner bug must never reach the text (TR-F46-03)
        return False


# --- Small helpers -----------------------------------------------------------------------------

_STRING: Final = re.compile(r'"(?:[^"\\\n]|\\.)*"')
_LEAD_STRING: Final = re.compile(r'^([ \t]*)("(?:[^"\\\n]|\\.)*")')
_TOKEN: Final = re.compile(r"[^ \t]+")


def quote(text: str) -> str:
    """``text`` as a script string: ``\\``, ``"`` and line breaks escaped (forms.quote)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def code_of(lines: Sequence[str]) -> tuple[str, str]:
    """(code, trailing comment) of a statement's head lines: the comment starts at the first
    ``#`` outside a string, with the blanks before it, and runs to its line's end."""
    text = "\n".join(lines)
    quote_char = ""
    i = 0
    while i < len(text):
        char = text[i]
        if quote_char:
            if char == "\\":
                i += 2
                continue
            if char == quote_char:
                quote_char = ""
        elif char in "\"'":
            quote_char = char
        elif char == "#":
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            code = text[:i].rstrip(" \t")
            return code.strip(), text[len(code):end]
        i += 1
    return text.strip(), ""


def _forms() -> Any:
    """``forms`` when its builder's module is there (imported late: it may not be yet)."""
    try:
        from engine.tools.editor import forms  # noqa: PLC0415
    except ImportError:
        return None
    return forms


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def snap(point: tuple[int, int]) -> tuple[int, int]:
    """A map point snapped to the 20 px grid (a new box's corner, 04 §6.6)."""
    return (int((point[0] + GRID // 2) // GRID * GRID), int((point[1] + GRID // 2) // GRID * GRID))


def _file(ref: str) -> str:
    return show(ref.removeprefix("script/"))


def _names(text: str, name: str) -> bool:
    """``name`` appears in ``text`` as a whole identifier (after NFKC)."""
    if not text.isascii():
        text = unicodedata.normalize("NFKC", text)
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) is not None


@dataclass(frozen=True, slots=True)
class _At:
    """A scene in its file: chunk-relative line ``r`` is absolute ``start + r - 1``."""

    scene: SceneRead
    lines: Sequence[str]
    start: int

    def abs(self, r: int) -> int:
        return self.start + r - 1

    def line(self, r: int) -> str:
        return self.lines[self.start + r - 2]

    def guards(self) -> tuple[tuple[str, bytes], ...]:
        return ((self.scene.name, self.scene.digest),)

    def edit(self, first: int, last: int, new: Sequence[str]) -> LineEdit:
        return LineEdit(self.abs(first), self.abs(last), tuple(new))

    def plan(self, title: str, edits: Sequence[LineEdit], expect: Expect | None, **extra: Any
             ) -> Plan:
        select = extra.pop("select", None)
        return Plan(title, (FilePlan(self.scene.ref, self.guards(), tuple(edits), select),),
                    expect=expect, **extra)


def _refused(at: _At) -> Refuse | None:
    """The refusal for a scene that doesn't parse (04 §6.1.7, 07 I-2), else None."""
    error = at.scene.error
    if error is None:
        return None
    if error[1] == SCENE_TOO_LONG:
        return Refuse(SCENE_TOO_LONG, (at.scene.ref, at.start))
    line = at.abs(error[0])
    return Refuse(FIX_FIRST.format(file=_file(at.scene.ref), line=line), (at.scene.ref, line))


def _top(scene: SceneRead) -> int:
    return next(i for i, block in enumerate(scene.blocks) if block.owner is None)


def block_of(scene: SceneRead, stmt: int) -> int:
    """The index in ``scene.blocks`` of the block holding statement ``stmt``."""
    return next(i for i, block in enumerate(scene.blocks) if stmt in block.members)


def _branches(scene: SceneRead, owner: tuple[int, ...]) -> list[int]:
    """The blocks (choices, ``if`` branches) of the statement at ``owner``, in order."""
    found = [(block.branch, i) for i, block in enumerate(scene.blocks) if block.owner == owner]
    return [i for _, i in sorted(found)]


def _ancestors(scene: SceneRead, stmt: int) -> list[Statement]:
    by_path = {s.path: s.node for s in scene.statements}
    path = scene.statements[stmt].path
    out = []
    while len(path) > 2:
        path = path[:-2]
        out.append(by_path[path])
    return out


def _links(after: After, ref: str, name: str) -> tuple[LabelLink, ...] | None:
    read = after.get(ref, {}).get(name)
    return None if read is None else read.links


def _has_link(ref: str, src: str, dst: str, kind: str | None = None) -> Expect:
    def check(after: After) -> bool:
        links = _links(after, ref, src)
        return links is not None and any(
            link.dst == dst and (kind is None or link.kind == kind) for link in links)
    return check


def _same_links(ref: str, scene: SceneRead) -> Expect:
    """The scene still parses and leads where it did (moves, inserts, forms)."""
    want = sorted((link.dst, link.kind) for link in scene.links)

    def check(after: After) -> bool:
        links = _links(after, ref, scene.name)
        return links is not None and sorted((link.dst, link.kind) for link in links) == want
    return check


# --- Arrows (§6.4) -----------------------------------------------------------------------------

def _go_line(indent: str, target: str) -> str:
    """The written ``jump`` line (AC-F46-12 patches it)."""
    return f"{indent}jump {target}"


def _choice_ends_in_jump(scene: SceneRead, block: BlockRead) -> bool:
    return bool(block.members) and isinstance(scene.statements[block.members[-1]].node, Jump)


def plan_add_arrow(scene: SceneRead, lines: Sequence[str], start: int, target: str,
                   unit: str, *, choice: bool = False) -> Result:
    """A new arrow ``scene → target`` (04 §6.4's table). ``choice``: the answer to the
    Make a choice question."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    top = scene.blocks[_top(scene)]
    indent = top.indent or unit
    ref, src = scene.ref, scene.name
    if not top.members:
        return at.plan("Add arrow", [at.edit(2, 1, [_go_line(unit, target)])],
                       _has_link(ref, src, target))
    last = scene.statements[top.members[-1]]
    node = last.node
    if isinstance(node, Return):
        code, comment = code_of([at.line(r) for r in range(last.head.first, last.head.last + 1)])
        return at.plan("Add arrow",
                       [at.edit(last.head.first, last.head.last,
                                [_go_line(last.indent, target) + comment])],
                       _has_link(ref, src, target),
                       status=RETURN_REPLACED.format(dst=show(target)))
    if isinstance(node, Jump):
        if not choice:
            return Ask(MAKE_CHOICE.format(src=show(src), dst=show(node.target)),
                       (MAKE_CHOICE_BUTTON, CANCEL), escape=1, default=0)
        i = last.indent
        block = [f"{i}menu:",
                 f"{i}{unit}{quote('Go to ' + node.target)}:",
                 _go_line(i + unit * 2, node.target),
                 f"{i}{unit}{quote('Go to ' + target)}:",
                 _go_line(i + unit * 2, target)]
        old_target = node.target

        def made(after: After) -> bool:
            return _has_link(ref, src, target, "menu")(after) \
                and _has_link(ref, src, old_target, "menu")(after)
        return at.plan("Make a choice", [at.edit(last.span.first, last.span.last, block)],
                       made, then=(THEN_CHOICE_TEXT, target))
    if isinstance(node, Menu):
        options = [scene.blocks[b] for b in _branches(scene, last.path)]
        if options and all(_choice_ends_in_jump(scene, b) for b in options):
            if len(options) >= MENU_MAX_CHOICES:
                return Refuse(TOO_MANY_CHOICES)
            end = options[-1]
            header = at.line(end.head.first)
            header_indent = header[:len(header) - len(header.lstrip(" \t"))]
            new = [f"{header_indent}{quote('Go to ' + target)}:", _go_line(end.indent, target)]
            return at.plan("Add choice", [at.edit(end.span.last + 1, end.span.last, new)],
                           _has_link(ref, src, target, "menu"),
                           then=(THEN_CHOICE_TEXT, target))
    return at.plan("Add arrow", [at.edit(last.span.last + 1, last.span.last,
                                         [_go_line(indent, target)])],
                   _has_link(ref, src, target))


def _link_statements(scene: SceneRead, target: str, kind: str) -> list[int]:
    """The statements of ``scene`` that make its ``(target, kind)`` arrow."""
    found = []
    for i, stmt in enumerate(scene.statements):
        node = stmt.node
        if not isinstance(node, Jump | Call) or node.target != target:
            continue
        in_menu = any(isinstance(a, Menu) for a in _ancestors(scene, i))
        here = "call" if isinstance(node, Call) else "menu" if in_menu else "jump"
        if here == kind:
            found.append(i)
    return found


def _no_link(ref: str, src: str, dst: str, kind: str) -> Expect:
    def check(after: After) -> bool:
        links = _links(after, ref, src)
        return links is not None and not any(
            link.dst == dst and link.kind == kind for link in links)
    return check


def _only_member(scene: SceneRead, block: int, at: _At, stmt: int) -> Refuse | None:
    if len(scene.blocks[block].members) > 1:
        return None
    text = EMPTIES_SCENE if scene.blocks[block].owner is None else EMPTIES_CHOICE
    return Refuse(text, (scene.ref, at.abs(scene.statements[stmt].head.first)))


def plan_delete_arrow(scene: SceneRead, lines: Sequence[str], start: int, target: str,
                      kind: str, *, confirm: bool = False) -> Result:
    """Remove the arrow ``scene → target`` of ``kind`` (04 §6.4, 07 I-8)."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    found = _link_statements(scene, target, kind)
    if not found:
        return Refuse(STALE)
    inside_if = [i for i in found if any(isinstance(a, If) for a in _ancestors(scene, i))]
    if inside_if:
        line = at.abs(scene.statements[inside_if[0]].head.first)
        return Refuse(FROM_IF, (scene.ref, line))
    if len(found) > 1:
        return Refuse(FROM_MANY.format(count=len(found)))
    i = found[0]
    stmt = scene.statements[i]
    block_index = block_of(scene, i)
    expect = _no_link(scene.ref, scene.name, target, kind)
    if kind != "menu":
        empties = _only_member(scene, block_index, at, i)
        if empties is not None:
            return empties
        return at.plan("Delete arrow", [at.edit(stmt.unit.first, stmt.unit.last, [])], expect)
    block = scene.blocks[block_index]
    assert block.owner is not None and block.unit is not None and block.span is not None
    menu_index = next(n for n, s in enumerate(scene.statements) if s.path == block.owner)
    menu = scene.statements[menu_index]
    choice = menu.node.choices[block.branch]                  # type: ignore[attr-defined]
    extra = any(not (m == i or _is_pass(scene.statements[m].node)) for m in block.members)
    options = _branches(scene, block.owner)
    if len(options) == 1:
        empties = _only_member(scene, block_of(scene, menu_index), at, menu_index)
        if empties is not None:
            return empties
        span = menu.unit
        ask = extra or menu.node.question is not None        # type: ignore[attr-defined]
        size = menu.span.last - menu.span.first + 1
    else:
        span = block.unit
        ask = extra
        size = block.span.last - block.span.first + 1
    if ask and not confirm:
        return Ask(DELETE_CHOICE.format(text=show(choice.text), lines=_count(size, "line")),
                   (DELETE, CANCEL), escape=1, default=1)
    return at.plan("Delete arrow", [at.edit(span.first, span.last, [])], expect)


def _is_pass(node: Statement) -> bool:
    return isinstance(node, PythonLine) and node.py.source.strip() == "pass"


def _replace_word(line: str, word: int, new: str) -> str | None:
    """``line`` with its ``word``-th blank-separated word (0-based) replaced."""
    tokens = list(_TOKEN.finditer(line))
    if word >= len(tokens):
        return None
    token = tokens[word]
    return line[:token.start()] + new + line[token.end():]


def plan_retarget(scene: SceneRead, lines: Sequence[str], start: int, old: str, new: str,
                  kind: str) -> Result:
    """Point the arrow ``scene → old`` of ``kind`` at ``new``: only the target word changes
    (04 §6.4 Retarget, PR-F46-10)."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    if old == new:
        return None
    found = _link_statements(scene, old, kind)
    if not found:
        return Refuse(STALE)
    if len(found) > 1:
        return Refuse(FROM_MANY.format(count=len(found)))
    stmt = scene.statements[found[0]]
    rewritten = _replace_word(at.line(stmt.head.first), 1, new)
    if rewritten is None:
        return Refuse(UNSAFE)

    def check(after: After) -> bool:
        return _has_link(scene.ref, scene.name, new, kind)(after) \
            and _no_link(scene.ref, scene.name, old, kind)(after)
    return at.plan("Change target", [at.edit(stmt.head.first, stmt.head.first, [rewritten])],
                   check)


def plan_choice_text(scene: SceneRead, lines: Sequence[str], start: int,
                     path: tuple[int, ...], text: str) -> Result:
    """A choice's text: ``path`` is the menu's statement path plus the choice's index. Only
    the header's leading string changes (04 §6.4 Choice text)."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    owner, branch = tuple(path[:-1]), path[-1]
    block = next((b for b in scene.blocks if b.owner == owner and b.branch == branch), None)
    menu = next((s for s in scene.statements if s.path == owner), None)
    if block is None or block.head is None or menu is None or not isinstance(menu.node, Menu):
        return Refuse(STALE)
    if menu.node.choices[branch].text == text:
        return None
    line = at.line(block.head.first)
    match = _LEAD_STRING.match(line)
    if match is None:
        return Refuse(UNSAFE)
    new_line = line[:match.start(2)] + quote(text) + line[match.end(2):]

    def check(after: After) -> bool:
        read = after.get(scene.ref, {}).get(scene.name)
        if read is None:
            return False
        node = next((s.node for s in read.statements if s.path == owner), None)
        return isinstance(node, Menu) and node.choices[branch].text == text
    return at.plan("Edit choice text", [at.edit(block.head.first, block.head.first, [new_line])],
                   check)


# --- New and deleted scenes (§6.6) -------------------------------------------------------------

def plan_new_scene(file_lines: Sequence[str], ref: str, name: str, unit: str,
                   place: tuple[int, int] | None, *, taken: Collection[str] = ()) -> Result:
    """Append ``label name:`` and a placeholder line to ``ref``. ``place``: the click point
    (snapped to 20 px) or the caller's ``place_free`` spot; None places it automatically.
    ``taken``: every scene name on the map and in the indexes."""
    problem = label_problem(name)
    if problem is not None:
        return Refuse(problem)
    name = canonical_name(name)
    if name in taken:
        return Refuse(NAME_TAKEN.format(name=show(name)))
    count = len(file_lines)
    empty = count == 0 or (count == 1 and file_lines[0] == "")
    new = [f"label {name}:", f"{unit}{quote(PLACEHOLDER)}"]
    if empty:
        edit = LineEdit(1, max(count, 0), tuple(new))
        label_line = 1
    else:
        if file_lines[-1].strip():
            new.insert(0, "")
        edit = LineEdit(count + 1, count, tuple(new))
        label_line = count + len(new) - 1
    found = _chunk_texts(file_lines)
    guards = ((found[-1][0], digest(found[-1][3])),) if found else ()
    select = (label_line + 1, len(unit) + 1, len(unit) + 1 + len(PLACEHOLDER))

    def check(after: After) -> bool:
        return name in after.get(ref, {})
    return Plan("New scene", (FilePlan(ref, guards, (edit,), select),),
                MappingProxyType({name: None if place is None else snap(place)}),
                expect=check)


def plan_delete_scene(scene: SceneRead, lines: Sequence[str], start: int, *, arrows: int = 0,
                      confirm: bool = False) -> Result:
    """Remove ``label`` through the block's last line (04 §6.6). ``arrows``: the edges into
    the box. Lines after the block (top-level ones) stay."""
    if scene.name == START:
        return Refuse(DELETE_START)
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    if not confirm:
        text = DELETE_SCENE.format(name=show(scene.name), lines=_count(scene.last, "line"))
        if arrows:
            verb = "arrow leads" if arrows == 1 else "arrows lead"
            text += " " + ARROWS_IN.format(arrows=f"{arrows} {verb}")
        return Ask(text, (DELETE, CANCEL), escape=1, default=1)
    first, last = start, at.abs(scene.last)
    if first > 1 and not lines[first - 2].strip() and last < len(lines) \
            and not lines[last].strip():
        last += 1

    def check(after: After) -> bool:
        return scene.name not in after.get(scene.ref, {})
    return Plan("Delete scene", (FilePlan(scene.ref, at.guards(),
                                          (LineEdit(first, last, ()),)),),
                MappingProxyType({scene.name: None}), expect=check)


# --- Rename (§6.5) -----------------------------------------------------------------------------

Hit = tuple[SceneRead, Sequence[str], int]


def rename_hits(ref: str, text: str, old: str, *, positions: Collection[str] = ()
                ) -> list[Hit]:
    """The chunks of ``ref``'s ``text`` with a line naming ``old`` (as a whole identifier),
    parsed: ``plan_rename``'s ``hits`` for one file."""
    lines = text.split("\n")
    out: list[Hit] = []
    for name, first, _, chunk in _chunk_texts(lines):
        if name != old and not _names(chunk, old):
            continue
        read = parse_chunk(ref, chunk, positions=positions)
        if read is not None:
            out.append((read, lines, first))
    return out


def _python_places(at: _At, old: str) -> list[int]:
    """Absolute lines where Python code in the scene names ``old``."""
    scene = at.scene
    found: list[int] = []
    for i, stmt in enumerate(scene.statements):
        node = stmt.node
        if isinstance(node, PythonLine):
            code = code_of([at.line(r) for r in range(stmt.head.first, stmt.head.last + 1)])[0]
            if _names(code, old):
                found.append(at.abs(stmt.head.first))
            continue
        conditions = (node.branches if isinstance(node, If)       # type: ignore[union-attr]
                      else node.choices if isinstance(node, Menu) else ())
        for item in conditions:
            if item.condition is not None and _names(item.condition.source, old):
                found.append(at.abs(item.line))
    # define/default values after the block, still inside this chunk
    r = scene.last + 1
    while at.abs(r) <= len(at.lines):
        line = at.line(r)
        if LABEL_START.match(line):
            break
        if _top_python(line, old):
            found.append(at.abs(r))
        r += 1
    return found


def _top_python(line: str, old: str) -> bool:
    words = line.split(None, 1)
    return bool(words) and words[0] in ("define", "default") and len(words) > 1 \
        and _names(code_of([line])[0].split("=", 1)[-1], old)


def plan_rename(hits: Mapping[str, Sequence[Hit]], old: str, new: str, *,
                taken: Collection[str] = (), locked: Mapping[str, str] = EMPTY,
                texts: Mapping[str, Sequence[str]] = EMPTY,
                place: tuple[int, int] | None = None, confirm: bool = False) -> Result:
    """Rename scene ``old`` to ``new`` in every file (04 §6.5): its label line and every
    ``RENAME_SLOTS`` word. ``hits``: ref → ``rename_hits``; ``locked``: ref → F44's read-only
    reason; ``texts``: ref → lines of files to scan for ``define``/``default`` lines above
    the first scene; ``place``: the box's place, moved to the new key. All or nothing."""
    if old == START:
        return Refuse(RENAME_START)
    problem = label_problem(new)
    if problem is not None:
        return Refuse(problem)
    new = canonical_name(new)
    if new == old:
        return None
    if new in taken:
        return Refuse(NAME_TAKEN.format(name=show(new)))
    files: list[FilePlan] = []
    slots = 0
    python: list[tuple[str, int]] = []
    for ref, entries in hits.items():
        if entries and ref in locked:
            return Refuse(locked[ref])
        edits: list[LineEdit] = []
        guards: list[tuple[str, bytes]] = []
        for scene, lines, start in entries:
            at = _At(scene, lines, start)
            refused = _refused(at)
            if refused is not None:
                return refused
            guards.append((scene.name, scene.digest))
            python.extend((ref, line) for line in _python_places(at, old))
            if scene.name == old:
                line = at.line(1)
                match = LABEL_START.match(line)
                if match is None:
                    return Refuse(UNSAFE)
                edits.append(at.edit(1, 1, [line[:match.start(1)] + new + line[match.end(1):]]))
            for stmt in scene.statements:
                rule = RENAME_SLOTS.get(type(stmt.node))
                if rule is None or rule[0](stmt.node) != old:
                    continue
                line = at.line(stmt.head.first)
                tokens = list(_TOKEN.finditer(line))
                if len(tokens) <= rule[1] or canonical_name(tokens[rule[1]].group()) != old:
                    return Refuse(UNSAFE)
                edits.append(at.edit(stmt.head.first, stmt.head.first,
                                     [_replace_word(line, rule[1], new) or line]))
                slots += 1
        if edits:
            files.append(FilePlan(ref, tuple(guards), tuple(edits)))
    for ref, lines in texts.items():
        for number, line in enumerate(lines, start=1):
            if LABEL_START.match(line):
                break
            if _top_python(line, old):
                python.append((ref, number))
    if not confirm:
        parts = [RENAME_ASK.format(old=show(old), new=show(new))]
        if slots:
            parts[0] += " " + RENAME_SLOTS_TEXT.format(
                lines=_count(slots, "line"), verb="goes" if slots == 1 else "go",
                change="changes" if slots == 1 else "change")
        if python:
            first_ref, first_line = min(python, key=lambda p: (list(hits).index(p[0])
                                                               if p[0] in hits else len(hits),
                                                               p[1]))
            parts.append(RENAME_PYTHON)
            parts.append(RENAME_PLACES.format(places=_count(len(python), "place"),
                                              file=_file(first_ref), line=first_line))
        parts.append(RENAME_SAVES)
        return Ask(" ".join(parts), (RENAME, CANCEL), escape=1, default=1)
    refs = [plan.ref for plan in files]

    def check(after: After) -> bool:
        if not any(new in after.get(ref, {}) for ref in refs):
            return False
        for ref in refs:
            for read in after.get(ref, {}).values():
                if read.name == old or any(link.dst == old for link in read.links):
                    return False
                if any(_flowchart_target(s.node) == old for s in read.statements
                       if isinstance(s.node, Flowchart)):
                    return False
        return True
    places: dict[str, tuple[int, int] | None] = {old: None}
    if place is not None:
        places[new] = place
    return Plan("Rename scene", tuple(files), MappingProxyType(places), expect=check)


# --- Rows (§6.7.5-6) ---------------------------------------------------------------------------

def _row_target(scene: SceneRead, row: Any) -> tuple[str, int]:
    """("stmt", statement) | ("header", block) for a choice / elif / else row |
    ("end", block) for a ◆ row | ("more", -1) for the row-cap line. An ``if`` branch 0
    row is its ``if`` statement. ``forms.Row.kind`` agrees when it is there."""
    if getattr(row, "kind", None) == "more":
        return "more", -1
    if row.stmt is None:
        return "end", row.block
    block = scene.blocks[row.block]
    stmt = scene.statements[row.stmt]
    if block.owner == stmt.path:
        if isinstance(stmt.node, If) and block.branch == 0:
            return "stmt", row.stmt
        return "header", row.block
    return "stmt", row.stmt


def plan_move(scene: SceneRead, lines: Sequence[str], start: int, row: Any, step: int
              ) -> Result:
    """Swap a row's unit with its sibling's (``step`` -1 up, +1 down); the lines between
    stay. ``elif``/``else`` rows don't move (04 §6.7.6)."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    kind, index = _row_target(scene, row)
    if kind in ("end", "more"):
        return None
    if kind == "header":
        block = scene.blocks[index]
        owner = scene.statements[row.stmt].node
        if not isinstance(owner, Menu):
            return None                                 # elif / else rows stay
        siblings = _branches(scene, block.owner)        # type: ignore[arg-type]
        units = [scene.blocks[b].unit for b in siblings]
    else:
        siblings = list(scene.blocks[block_of(scene, index)].members)
        units = [scene.statements[m].unit for m in siblings]
    here = siblings.index(index)
    there = here + step
    if there < 0:
        return Refuse(AT_TOP)
    if there >= len(siblings):
        return Refuse(AT_BOTTOM)
    upper, lower = sorted((units[here], units[there]), key=lambda u: u.first)  # type: ignore
    assert upper is not None and lower is not None
    get = at.line
    new = ([get(r) for r in range(lower.first, lower.last + 1)]
           + [get(r) for r in range(upper.last + 1, lower.first)]
           + [get(r) for r in range(upper.first, upper.last + 1)])
    moved = units[here]
    assert moved is not None
    first = upper.first if step < 0 else lower.last - (moved.last - moved.first)
    return at.plan("Move up" if step < 0 else "Move down",
                   [at.edit(upper.first, lower.last, new)], _same_links(scene.ref, scene),
                   select=(at.abs(first), 0, 0))


def plan_delete_row(scene: SceneRead, lines: Sequence[str], start: int, row: Any, *,
                    confirm: bool = False) -> Result:
    """Delete a row's unit, asking first when it has lines inside (N physical lines after its
    head). A block's only row becomes ``$ pass`` (decision 4)."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    kind, index = _row_target(scene, row)
    if kind in ("end", "more"):
        return None
    if kind == "header":
        block = scene.blocks[index]
        assert block.head is not None and block.span is not None and block.unit is not None
        inside = block.span.last - block.head.last
        if len(_branches(scene, block.owner)) == 1:    # type: ignore[arg-type]
            kind, index = "stmt", row.stmt              # the last choice: the whole menu
        else:
            if block.branch == 0:                       # an if's first branch: never alone
                return None
            if inside and not confirm:
                return _ask_inside(inside)
            return at.plan("Delete", [at.edit(block.unit.first, block.unit.last, [])],
                           None)
    stmt = scene.statements[index]
    inside = stmt.span.last - stmt.head.last
    if inside and not confirm:
        return _ask_inside(inside)
    holder = scene.blocks[block_of(scene, index)]
    new = [f"{stmt.indent}$ pass"] if len(holder.members) == 1 else []
    return at.plan("Delete", [at.edit(stmt.unit.first, stmt.unit.last, new)], None)


def _ask_inside(count: int) -> Ask:
    return Ask(DELETE_INSIDE.format(lines=_count(count, "line")), (DELETE, CANCEL),
               escape=1, default=1)


def plan_insert(scene: SceneRead, lines: Sequence[str], start: int, row: Any,
                text_lines: Sequence[str]) -> Result:
    """Insert ``text_lines`` (code relative to the block: each gets the block's indent)
    above the row's unit; on a ◆ row after the block's last span; on a choice / branch row
    at the top of its block. A block that is only ``$ pass`` has it replaced (G2)."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    kind, index = _row_target(scene, row)
    if not text_lines or kind == "more":
        return None
    block_index = index if kind in ("end", "header") else block_of(scene, index)
    block = scene.blocks[block_index]
    members = [scene.statements[m] for m in block.members]
    indent = block.indent
    new = [indent + line if line.strip() else line for line in text_lines]
    if len(members) == 1 and _is_pass(members[0].node):
        unit = members[0].unit
        edit = at.edit(unit.first, unit.last, new)
        first = unit.first
    elif kind == "end":
        last = members[-1].span.last if members else (block.head.last if block.head else 1)
        edit = at.edit(last + 1, last, new)
        first = last + 1
    else:
        unit = (scene.statements[index].unit if kind == "stmt" else members[0].unit)
        edit = at.edit(unit.first, unit.first - 1, new)
        first = unit.first
    count = len(scene.statements)

    def check(after: After) -> bool:
        read = after.get(scene.ref, {}).get(scene.name)
        return read is not None and len(read.statements) >= count
    code = new[0]
    return at.plan("Insert", [edit], check,
                   select=(at.abs(first), len(indent), len(code)))


def plan_form(scene: SceneRead, lines: Sequence[str], start: int, row: Any,
              values: Any, *, form: Any = None, unit: str = "    ") -> Result:
    """A row's form, OK'd (04 §6.7.3): its head (an ``if``/``elif``/``else`` row: that
    header) becomes one line, the indent then the written code then the old trailing
    comment; nested blocks stay. ``values``: the form's values, written with ``form.write``
    (``form`` defaults to ``forms.form_by_key(row.form)``), or the code line already written.
    The Choice form's ``forms.ChoiceValues`` become ``forms.choice_patches``' raw patches
    (§6.7.4). None when nothing changes."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    forms = _forms()
    kind, index = _row_target(scene, row)
    if forms is not None and isinstance(values, forms.ChoiceValues):
        if row.stmt is None or not isinstance(scene.statements[row.stmt].node, Menu):
            return None
        patches = forms.choice_patches(scene, row.stmt, lines[start - 1:], values, unit=unit)
        if isinstance(patches, str):
            return Refuse(patches)
        return plan_patch(scene, lines, start, "Edit choice", patches)
    if kind == "stmt":
        stmt = scene.statements[index]
        span, indent, node = stmt.head, stmt.indent, stmt.node
    elif kind == "header" and isinstance(scene.statements[row.stmt].node, If):
        block = scene.blocks[index]
        assert block.head is not None
        span, node = block.head, scene.statements[row.stmt].node
        header = at.line(span.first)
        indent = header[:len(header) - len(header.lstrip(" \t"))]
    else:
        return None
    head = [at.line(r) for r in range(span.first, span.last + 1)]
    split = forms.code_of if forms is not None else code_of
    code_now, comment = split(head)
    if isinstance(values, str):
        code = values.strip()
    else:
        if form is None and forms is not None:
            form = forms.form_by_key(getattr(row, "form", None) or "")
        if form is None:
            return Refuse(UNSAFE)
        read = getattr(form, "read", None)
        if read is not None:
            try:
                if read(node, code_now) == dict(values):
                    return None
            except Exception:           # a form that can't read its own row: write it
                pass
        code = form.write(values).strip()
    if code == code_now:
        return None
    kinds = [type(s.node) for s in scene.statements]

    def check(after: After) -> bool:
        read_after = after.get(scene.ref, {}).get(scene.name)
        return read_after is not None and kinds == [
            type(s.node) for s in read_after.statements]
    return at.plan("Edit", [at.edit(span.first, span.last, [indent + code + comment])], check,
                   select=(at.abs(span.first), len(indent), len(indent) + len(code)))


def plan_patch(scene: SceneRead, lines: Sequence[str], start: int, title: str,
               edits: Sequence[Any], expect: Expect | None = None) -> Result:
    """Raw patches in chunk-relative lines (the Choice form, §6.7.4): ``forms.Patch``es or
    ``(first, last, lines)`` tuples, guarded and verified like any plan. ``expect``
    defaults to "the scene still parses"."""
    at = _At(scene, lines, start)
    refused = _refused(at)
    if refused is not None:
        return refused
    if not edits:
        return None

    def parses(after: After) -> bool:
        return scene.name in after.get(scene.ref, {})
    triples = [(e.first, e.last, e.lines) if hasattr(e, "first") else tuple(e) for e in edits]
    return at.plan(title, [at.edit(first, last, new) for first, last, new in triples],
                   expect or parses)


__all__ = ["AT_BOTTOM", "AT_TOP", "After", "Ask", "CANCEL", "DELETE", "EMPTIES_CHOICE",
           "EMPTIES_SCENE", "Expect", "FilePlan", "LineEdit", "Plan", "RENAME", "RENAME_SLOTS",
           "Refuse", "STALE", "UNSAFE", "apply_lines", "block_of", "code_of", "plan_add_arrow",
           "plan_choice_text", "plan_delete_arrow", "plan_delete_row", "plan_delete_scene",
           "plan_form", "plan_insert", "plan_move", "plan_new_scene", "plan_patch",
           "plan_rename", "plan_retarget", "quote", "rename_hits", "snap", "verify"]
