"""``propose_edit``: a model's exact-text changes made into a checked, guarded plan (F48
``04-technical.md`` §7.1, §7.2, §7.4; ``05-security.md`` SEC-F48-02, SEC-F48-04 (as amended
in §10), SEC-F48-10; 01 PR-F48-07, PR-F48-08, §4.4, §6.3).

Why this module exists: a model writes text, but the ``.vns`` files stay the only truth and
nothing is written until the author acts. So a proposal is never stored text: it is a
``scriptedit`` plan of line edits guarded by the touched scenes' digests (F46's mechanism),
verified, parsed, and checked as an overlay against the same files without the change.

- ``propose(workspace, args)`` follows §7.1: exact argument shapes and SEC-F48-10's bounds;
  listed script refs through ``select``, a new ref through ``new_ref_problem``; each
  ``old_text`` found exactly once, widened to whole lines, trimmed to the lines that really
  change; F02's parser on each changed file (an error inside a changed range, or anywhere in
  a new file, refuses with its text and no proposal); ``scriptedit.verify``; then the check
  of the base and of the proposal in the same launch mode. A check that can't finish keeps
  the proposal with "Couldn't check this change: {reason}".
- ``code_bearing`` is SEC-F48-04's rule (§7.2), failing closed: a parse error in a changed
  file, a changed code line in no parsed node, a changed top-level statement other than a
  label (everything the launch phase evaluates, so a new registered declaration is covered
  without a list), a ``PyCode`` in a changed node (``$``, ``python``, conditions), a pure
  deletion touching one of those (old or new text), or the line backstop. Then both checks
  run ``--no-launch`` and the result carries §6.3's two code texts.
- ``numbered_diff`` gives unified-order hunks with every content line numbered
  (`` 14 ``/``-15 ``/``+15 ``, SEC-F48-09 (a)); ``problem_delta`` compares the two checks by
  (code, file, line mapped through the edits, text); ``rebase`` moves a plan onto a changed
  text when every touched scene kept its digest (the pane's Apply).
- ``propose_settings`` (2026-11-04) is the same flow for ``config.toml``: the model names
  ``(section, key, value)`` settings, never text; ``tomlpatch.plan_changes`` (Game settings'
  own writer) plans the lines, refusing a key that isn't a setting or a value its validator
  refuses, and ``tomlpatch.verify`` is the gate again at Apply (``verify_file``). The file
  must be unchanged since the proposal: a settings plan never rebases.
- ``Proposal`` and ``ProposalFile`` hold plans, SHAs, guards and the numbered diff, never a
  file's text. ``render`` is the tool result (MCP adds the id; the pane says a card is shown).

Imports ``engine.core``, ``engine.script``, the pure editor modules ``checker``, ``scenes``
and ``scriptedit``, and its own package.
"""

import threading
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Final

from engine.core.constants import BUILTIN_POSITIONS
from engine.script.assetgroups import CONFIG_REF
from engine.script.diagnostics import DiagnosticSink
from engine.script.nodes import Label, Node, PyCode, ScriptFile
from engine.script.parser import parse_file
from engine.script.source import normalize_line_ends
from engine.script.statements import ParseContext
from engine.tools.assistant.refs import (
    NOT_EDITABLE, ToolError, check_keys, new_ref_problem, one_line, text_arg)
from engine.tools.assistant.textout import (
    PROBLEMS_MAX, TextOut, ToolText, line_width, numbered_line)
from engine.tools.assistant.workspace import Workspace, text_sha
from engine.tools.editor.checker import CheckItem
from engine.tools.editor.scenes import SceneIndex, chunks, digest
from engine.tools.editor.tomlpatch import TomlPlan, plan_changes
from engine.tools.editor.tomlpatch import verify as settings_fit
from engine.tools.editor.scriptedit import (
    UNSAFE, FilePlan, LineEdit, Plan, Refuse, apply_lines, verify)

# --- Bounds (01 PR-F48-08; SEC-F48-10) ------------------------------------------------------

SUMMARY_MAX_CHARS: Final = 200
CHANGES_MAX: Final = 64
CHANGE_TEXT_MAX_BYTES: Final = 64 * 1024
FILES_MAX: Final = 8
SETTINGS_MAX: Final = 32                # settings in one propose_settings
NEW_TEXT_MAX_BYTES: Final = 64 * 1024
CONTEXT_LINES: Final = 3
ADDED_SHOWN: Final = 3                  # 01 §6.3: "up to 3"
PARSE_SINK_LIMIT: Final = 1_000
WALK_MAX_ITEMS: Final = 2_000_000       # a node walk past this fails closed

# --- Texts (01 §4.4, §6.3; refusals worded here) --------------------------------------------

NOT_FOUND: Final = "That text isn't in {file}."
FOUND_MANY: Final = "That text is in {file} {n} times; include more lines around it."
CHANGES_SHAPE: Final = "changes must be a list of 1 to 64 changes."
CHANGE_SHAPE: Final = "Each change must be an object with file, old_text and new_text."
TEXT_TOO_LONG: Final = "{key} must be text of at most 65,536 bytes."
TEXT_NOT_SAVABLE: Final = "{key} holds a character that can't be saved in a file."
TOO_MANY_FILES: Final = "A proposal can change at most 8 files."
NEW_TEXT_TOO_LONG: Final = "A proposal can add at most 65,536 bytes of new text."
EMPTY_OLD: Final = ("old_text is empty, but {file} already exists. Put the lines to change in "
                    "old_text and their new text in new_text.")
NEW_FILE_ONCE: Final = "A new file takes exactly one change, with an empty old_text."
OVERLAP: Final = "Two changes to {file} touch the same lines; make them one change."
NO_CHANGE: Final = "This change doesn't change anything."
DOESNT_PARSE: Final = "This change doesn't parse: {file}, line {line}: {message}"
FIX_FIRST: Final = ("{file} has a problem at line {line} that stops this change being made "
                    "safely: {message}")
NEW_FILE_MARK: Final = " (new file)"
HUNK_GAP: Final = "…"
SETTINGS_SHAPE: Final = "changes must be a list of 1 to 32 settings."
SETTING_SHAPE: Final = ("Each setting must be an object with section (like \"window\" or "
                        "\"theme.textbox\"), key, and value (null puts the default back).")
NO_CONFIG: Final = "This game has no config.toml."

PROPOSED: Final = "Proposed change: "
NO_NEW_PROBLEMS: Final = "No new problems."
ADDS: Final = "This change adds {n} problem(s):"
ADD_ROW: Final = "{code} line {line}: {text}"
ADD_ROW_FILE: Final = "{code} {file} line {line}: {text}"
ADD_ROW_NO_LINE: Final = "{code}: {text}"
FIXES: Final = "Fixes {n} problem(s)."
NO_CODE_RUN: Final = "Checked without running its Python code. That runs after you apply."
CODE_NOTICE: Final = "⚠ This change adds or changes Python code. Read it before you apply."
CHECK_UNKNOWN: Final = "Couldn't check this change: {reason}"
CARD_SHOWN: Final = "Shown to the author as a card."
ID_LINE: Final = "id: {id}"
APPLY_HINT: Final = "apply_edit with this id writes it; nothing is written until then."

# The line backstop (§7.2): an added line starting with one of these words (indent stripped),
# or holding ``module(``, is code-bearing whatever the parser made of it.
CODE_WORDS: Final = ("define", "default", "python", "init", "include", "if", "elif", "while")
MODULE_CALL: Final = "module("
NL: Final = "\n"


# --- Shapes ---------------------------------------------------------------------------------

Key = tuple[str, int]                   # a chunk: (label, ordinal in its file)


@dataclass(frozen=True, slots=True)
class ProposalFile:
    """One file of a proposal. ``base_sha``: the SHA-256 of what the workspace read (MCP:
    the file's bytes; pane: its editor text); None for a new file. ``plan`` is the file's
    guarded line edits. ``touched`` names, per edit, the chunks it touches (None: the lines
    above the first label); ``marks`` each touched chunk's first line and digest when
    proposed; ``preamble`` the digest of the lines above the first label when an edit
    touches them. ``diff`` is the numbered diff (``numbered_diff``) and ``sent`` the line
    ranges of the old text it shows."""

    ref: str
    base_sha: str | None
    plan: FilePlan
    new: bool
    code: bool
    added: int
    removed: int
    diff: tuple[str, ...]
    sent: tuple[tuple[int, int], ...] = ()
    touched: tuple[tuple[Key | None, ...], ...] = ()
    marks: tuple[tuple[Key, int, bytes], ...] = ()
    preamble: bytes | None = None
    settings: TomlPlan | None = None    # propose_settings: config.toml's plan


@dataclass(frozen=True, slots=True)
class Proposal:
    """A checked proposal. ``launch``: whether its checks ran the launch phase; ``added``
    the problems the change adds (at most ``PROBLEMS_MAX``), ``fixed`` how many it fixes;
    ``reason`` why the check couldn't finish (None when it did)."""

    summary: str
    files: tuple[ProposalFile, ...]
    code: bool
    launch: bool
    added: tuple[CheckItem, ...] = ()
    fixed: int = 0
    reason: str | None = None
    checked: bool = True

    @property
    def plan(self) -> Plan:
        """The whole proposal as one ``scriptedit.Plan`` (its title is the summary)."""
        return Plan(self.summary, tuple(f.plan for f in self.files))

    @property
    def new_refs(self) -> tuple[str, ...]:
        return tuple(f.ref for f in self.files if f.new)


# --- Arguments ------------------------------------------------------------------------------

def _size(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass"))


def _change_text(change: Mapping[str, object], key: str) -> str:
    value = change[key]
    if type(value) is not str or len(value) > CHANGE_TEXT_MAX_BYTES \
            or _size(value) > CHANGE_TEXT_MAX_BYTES:
        raise ToolError(TEXT_TOO_LONG.format(key=key))
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ToolError(TEXT_NOT_SAVABLE.format(key=key)) from None
    return normalize_line_ends(value)


def _count(text: str, needle: str, first: int, cap: int = 1_000) -> int:
    """How many places (overlapping ones too) hold ``needle``, from the one at ``first``."""
    found, at = 0, first
    while at >= 0 and found < cap:
        found += 1
        at = text.find(needle, at + 1)
    return found


# --- Lines, chunks and guards ---------------------------------------------------------------

def _chunk_marks(text: str, lines: Sequence[str]) -> list[tuple[Key, int, int, bytes]]:
    """``((label, ordinal), first, last, digest)`` per chunk, digests as ``scenes`` and
    ``scriptedit.verify`` take them."""
    out: list[tuple[Key, int, int, bytes]] = []
    seen: Counter[str] = Counter()
    for name, first, last in chunks(text):
        body = "\n".join(lines[first - 1:last]) + ("\n" if last < len(lines) else "")
        out.append(((name, seen[name]), first, last, digest(body)))
        seen[name] += 1
    return out


def _preamble_digest(lines: Sequence[str], marks: Sequence[tuple[Key, int, int, bytes]]) -> bytes:
    end = marks[0][1] - 1 if marks else len(lines)
    return digest("\n".join(lines[:end]))


def _touched_lines(edit: LineEdit) -> range:
    """The old lines an edit touches; an insertion touches the line above it (0: the top)."""
    if edit.last >= edit.first:
        return range(edit.first, edit.last + 1)
    return range(edit.first - 1, edit.first)


def _guards(text: str, lines: Sequence[str], edits: Sequence[LineEdit]
            ) -> tuple[tuple[tuple[str, bytes], ...], tuple[tuple[Key | None, ...], ...],
                       tuple[tuple[Key, int, bytes], ...], bytes | None]:
    """The plan's guards (first chunk of each touched name, as ``verify`` reads them), each
    edit's touched chunks, their marks, and the preamble digest when touched."""
    marks = _chunk_marks(text, lines)
    first_of: dict[str, bytes] = {}
    for (name, ordinal), _, _, chunk_digest in marks:
        if ordinal == 0:
            first_of[name] = chunk_digest
    touched: list[tuple[Key | None, ...]] = []
    used: dict[Key, tuple[int, bytes]] = {}
    preamble = False
    for edit in edits:
        keys: list[Key | None] = []
        for line in _touched_lines(edit):
            key: Key | None = None
            for mark_key, first, last, chunk_digest in marks:
                if first <= line <= last:
                    key = mark_key
                    used[mark_key] = (first, chunk_digest)
                    break
            if key is None:
                preamble = True
            if key not in keys:
                keys.append(key)
        touched.append(tuple(keys))
    guards = tuple(sorted({(key[0], first_of[key[0]]) for key in used}))
    return (guards, tuple(touched),
            tuple((key, first, chunk_digest) for key, (first, chunk_digest) in used.items()),
            _preamble_digest(lines, marks) if preamble else None)


def new_ranges(edits: Sequence[LineEdit]) -> list[tuple[int, int]]:
    """Each edit's lines in the new text (a pure deletion: the two lines now meeting)."""
    out = []
    shift = 0
    for edit in sorted(edits, key=lambda e: e.first):
        start = edit.first + shift
        if edit.lines:
            out.append((start, start + len(edit.lines) - 1))
        else:
            out.append((start - 1, start))
        shift += len(edit.lines) - (edit.last - edit.first + 1)
    return out


def line_map(edits: Sequence[LineEdit]) -> Callable[[int], int | None]:
    """Old line → new line through ``edits``; None for a line an edit replaced."""
    ordered = sorted(edits, key=lambda e: e.first)

    def mapped(line: int) -> int | None:
        shift = 0
        for edit in ordered:
            if line < edit.first:
                break
            if line <= edit.last:
                return None
            shift += len(edit.lines) - (edit.last - edit.first + 1)
        return line + shift
    return mapped


# --- The numbered diff (§7.1 step 7; SEC-F48-09 (a)) ----------------------------------------

def numbered_diff(old_lines: Sequence[str], edits: Sequence[LineEdit], *,
                  context: int = CONTEXT_LINES, new: bool = False
                  ) -> tuple[list[str], list[tuple[int, int]]]:
    """The hunks of ``edits`` over ``old_lines`` in unified order, every content line
    numbered: context `` 14 `` (new numbering), removed ``-15 `` (old), added ``+15 ``
    (new); hunks apart by ``…``. Returns the rows and the old line ranges they show. A new
    file is all ``+`` lines."""
    ordered = sorted(edits, key=lambda e: e.first)
    if new:
        added = [line for edit in ordered for line in edit.lines]
        width = line_width(len(added))
        return [numbered_line(n, text, width, "+") for n, text in enumerate(added, 1)], []
    before: list[int] = []
    shift = 0
    for edit in ordered:
        before.append(shift)
        shift += len(edit.lines) - (edit.last - edit.first + 1)
    width = line_width(max(len(old_lines), len(old_lines) + shift))
    groups: list[list[int]] = []
    for index, edit in enumerate(ordered):
        if groups and edit.first - ordered[groups[-1][-1]].last - 1 <= 2 * context:
            groups[-1].append(index)
        else:
            groups.append([index])
    rows: list[str] = []
    shown: list[tuple[int, int]] = []
    for group in groups:
        if rows:
            rows.append(HUNK_GAP)
        first_edit, last_edit = ordered[group[0]], ordered[group[-1]]
        start = max(1, first_edit.first - context)
        end = min(len(old_lines), max(last_edit.last, last_edit.first - 1) + context)
        line = start
        for index in group:
            edit, offset = ordered[index], before[index]
            while line < edit.first:
                rows.append(numbered_line(line + offset, old_lines[line - 1], width, " "))
                line += 1
            for number in range(edit.first, edit.last + 1):
                rows.append(numbered_line(number, old_lines[number - 1], width, "-"))
            for number, text in enumerate(edit.lines, edit.first + offset):
                rows.append(numbered_line(number, text, width, "+"))
            line = max(line, edit.last + 1)
        after = before[group[-1]] + len(last_edit.lines) - (last_edit.last - last_edit.first + 1)
        while line <= end:
            rows.append(numbered_line(line + after, old_lines[line - 1], width, " "))
            line += 1
        if end >= start:
            shown.append((start, end))
    return rows, shown


# --- Problems (§7.1 step 6) -----------------------------------------------------------------

def problem_delta(base: Iterable[CheckItem], proposed: Iterable[CheckItem],
                  maps: Mapping[str, Callable[[int], int | None]]
                  ) -> tuple[tuple[CheckItem, ...], tuple[CheckItem, ...]]:
    """(added, fixed): problems of ``proposed`` not in ``base`` and the other way round,
    keyed by (code, file, line, text) with each base line mapped through its file's edits
    (``maps``, from ``line_map``)."""
    remaining: Counter[tuple] = Counter()
    base_items: list[tuple[tuple, CheckItem]] = []
    for item in base:
        line = item.line
        if line is not None and item.file in maps:
            line = maps[item.file](line)
        key = (item.code, item.file, line, item.text)
        remaining[key] += 1
        base_items.append((key, item))
    added: list[CheckItem] = []
    for item in proposed:
        key = (item.code, item.file, item.line, item.text)
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            added.append(item)
    fixed: list[CheckItem] = []
    for key, item in base_items:
        if remaining[key] > 0:
            remaining[key] -= 1
            fixed.append(item)
    return tuple(added), tuple(fixed)


# --- SEC-F48-04: code-bearing (§7.2, failing closed) ----------------------------------------

def _parse(ref: str, text: str, positions: Iterable[str]) -> tuple[list[Node] | None, list]:
    """F02's parser on one file (no execution): its top-level nodes without errors and the
    kept diagnostics; nodes None when parsing blew the stack or memory."""
    ctx = ParseContext(sink=DiagnosticSink(limit=PARSE_SINK_LIMIT),
                       position_names=frozenset(BUILTIN_POSITIONS) | frozenset(positions))
    try:
        nodes = parse_file(ScriptFile(ref, ref.removeprefix("script/"), 0), text, ctx)
    except (RecursionError, MemoryError):
        return None, []
    return nodes, ctx.sink.kept()


def _starts_with_word(text: str, word: str) -> bool:
    if not text.startswith(word):
        return False
    after = text[len(word):len(word) + 1]
    return not after or not (after.isalnum() or after == "_")


def backstop(line: str) -> bool:
    """§7.2's line backstop: ``$`` or a code word first (indent stripped), or ``module(``."""
    stripped = line.lstrip(" \t")
    if stripped.startswith("$") or MODULE_CALL in line:
        return True
    return any(_starts_with_word(stripped, word) for word in CODE_WORDS)


class _TooBig(Exception):
    pass


def _span(value: object) -> tuple[int, int] | None:
    """The lines of a node or of a line-bearing part (a menu ``Choice``, an ``IfBranch``)."""
    line = getattr(value, "line", None)
    if type(line) is not int:
        return None
    end = getattr(value, "end_line", None)
    return line, max(end, line) if type(end) is int else line


def _code_parts(node: Node, budget: list[int]
                ) -> tuple[list[PyCode], list[Node], list[tuple[int, int]]]:
    """The ``PyCode`` in ``node``'s own fields (through tuples, mappings and plain
    dataclasses such as an ``IfBranch`` or a menu ``Choice``), the nodes nested in it (not
    entered), and the lines of those plain parts. Iterative; ``_TooBig`` past
    ``WALK_MAX_ITEMS`` in all."""
    codes: list[PyCode] = []
    children: list[Node] = []
    spans: list[tuple[int, int]] = []
    stack: list[object] = [getattr(node, f.name) for f in fields(node) if f.name != "file"]
    seen: set[int] = set()
    while stack:
        budget[0] += 1
        if budget[0] > WALK_MAX_ITEMS:
            raise _TooBig
        value = stack.pop()
        if value is None or isinstance(value, (str, bytes, int, float, ScriptFile)):
            continue
        if isinstance(value, PyCode):
            codes.append(value)
        elif isinstance(value, Node):
            children.append(value)
        elif id(value) in seen:
            continue
        elif isinstance(value, (tuple, list, frozenset, set)):
            seen.add(id(value))
            stack.extend(value)
        elif isinstance(value, Mapping):
            seen.add(id(value))
            stack.extend(value.values())
        elif is_dataclass(value) and not isinstance(value, type):
            seen.add(id(value))
            span = _span(value)
            if span is not None:
                spans.append(span)
            stack.extend(getattr(value, f.name) for f in fields(value))
    return codes, children, spans


def _meets(first: int, last: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(first <= high and low <= last for low, high in ranges)


def _scan(nodes: Sequence[Node], ranges: Sequence[tuple[int, int]]
          ) -> tuple[bool, list[tuple[int, int]]]:
    """Every node and part, walked iteratively: whether code meets ``ranges`` (a top-level
    statement other than a label, or a ``PyCode``: anywhere in a node with no nested
    statements, on the code's own lines in one with them), and every line span covered."""
    budget = [0]
    hit = False
    covered: list[tuple[int, int]] = []
    stack: list[tuple[Node, bool]] = [(node, True) for node in nodes]
    while stack:
        node, top = stack.pop()
        first, last = _span(node) or (node.line, node.line)
        covered.append((first, last))
        meets = _meets(first, last, ranges)
        if top and meets and not isinstance(node, Label):
            hit = True
        codes, children, spans = _code_parts(node, budget)
        covered += spans
        if codes and not children and meets:
            hit = True
        elif any(_meets(code.line, code.line + code.source.count(NL), ranges)
                 for code in codes):
            hit = True
        stack.extend((child, False) for child in children)
    return hit, covered


def _is_quiet(line: str) -> bool:
    """A blank or comment line, which holds no code wherever it is."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def code_bearing(ref: str, old_lines: Sequence[str], edits: Sequence[LineEdit], *,
                 new: bool = False, positions: Iterable[str] = ()) -> bool:
    """SEC-F48-04 (§7.2, amended in 05 §10): True when the edits add or change text the
    launch phase or the story could run, or when that can't be ruled out."""
    if any(backstop(line) for edit in edits for line in edit.lines):
        return True
    try:
        new_lines = apply_lines(list(old_lines), edits)
    except ValueError:
        return True
    changed = new_ranges(edits)
    try:
        nodes, errors = _parse(ref, NL.join(new_lines), positions)
        if nodes is None or errors:
            return True                     # fails closed: any error in a changed file
        hit, covered = _scan(nodes, changed)
        if hit:
            return True
        for low, high in changed:
            for number in range(max(low, 1), min(high, len(new_lines)) + 1):
                if not _is_quiet(new_lines[number - 1]) and not _meets(number, number, covered):
                    return True             # a changed line in no parsed node
        if not new:
            old_nodes, _ = _parse(ref, NL.join(old_lines), positions)
            removed = [(e.first, e.last) for e in edits if e.last >= e.first]
            if old_nodes is None or (removed and _scan(old_nodes, removed)[0]):
                return True
    except _TooBig:
        return True
    return False


# --- Rebase (§7.4, the pane's Apply) --------------------------------------------------------

def rebase(file: ProposalFile, live_text: str, *,
           index: SceneIndex | None = None) -> FilePlan | None:
    """``file``'s plan for the live text: as made when the text's SHA is the base; else each
    edit moved by its chunks' shift when every touched chunk (label, ordinal) kept its digest
    and the preamble, if touched, is unchanged. None: stale (01 §6.3).

    F58 (P0's ``rebase`` row): ``index``, the editor's ``SceneIndex`` of exactly
    ``live_text``, gives each chunk's first line and digest, so only the preamble (when an
    edit touches it) is digested here; without it every chunk is joined and digested."""
    if file.base_sha is not None and text_sha(live_text) == file.base_sha:
        return file.plan
    if file.new or file.settings is not None or len(file.touched) != len(file.plan.edits):
        return None                     # a settings plan (or one without marks) never moves
    lines: list[str] | None = None
    if index is not None:
        live = {key: (first, index.digests[key]) for key, first in index.starts.items()}
        first_label = next(iter(index.starts.values()), None)
    else:
        lines = live_text.split("\n")
        found = _chunk_marks(live_text, lines)
        live = {key: (first, chunk_digest) for key, first, _, chunk_digest in found}
        first_label = found[0][1] if found else None
    marks = {key: (first, chunk_digest) for key, first, chunk_digest in file.marks}
    preamble_now: bytes | None = None
    moved: list[LineEdit] = []
    for edit, keys in zip(file.plan.edits, file.touched):
        shift: int | None = None
        for key in keys:
            if key is None:
                if preamble_now is None:
                    if lines is None:
                        lines = live_text.split("\n")
                    end = first_label - 1 if first_label is not None else len(lines)
                    preamble_now = digest("\n".join(lines[:end]))
                if file.preamble is None or preamble_now != file.preamble:
                    return None
                step = 0
            else:
                then, now = marks.get(key), live.get(key)
                if then is None or now is None or then[1] != now[1]:
                    return None
                step = now[0] - then[0]
            if shift is not None and step != shift:
                return None
            shift = step
        shift = shift or 0
        moved.append(LineEdit(edit.first + shift, edit.last + shift, edit.lines))
    return FilePlan(file.ref, file.plan.guards, tuple(moved), None)


# --- propose (§7.1) -------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Planned:
    file: ProposalFile
    data: bytes                         # the proposed bytes (for the overlay check only)
    edits: tuple[LineEdit, ...]


def _new_file_lines(text: str) -> list[str]:
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n")


def _edit_for(text: str, ref: str, old: str, new: str) -> tuple[tuple[int, int], LineEdit | None]:
    """The whole-line span ``old`` sits in (old numbering) and the trimmed edit (None when
    nothing changes)."""
    shown = one_line(ref)
    at = text.find(old)
    if at < 0:
        raise ToolError(NOT_FOUND.format(file=shown))
    again = text.find(old, at + 1)
    if again >= 0:
        raise ToolError(FOUND_MANY.format(file=shown, n=_count(text, old, at)))
    start = text.rfind("\n", 0, at) + 1
    stop = at + len(old)
    end = text.find("\n", stop)
    end = len(text) if end < 0 else end
    old_lines = text[start:end].split("\n")
    new_lines = (text[start:at] + new + text[stop:end]).split("\n")
    first = text.count("\n", 0, start) + 1
    span = (first, first + len(old_lines) - 1)
    head = 0
    while head < min(len(old_lines), len(new_lines)) and old_lines[head] == new_lines[head]:
        head += 1
    tail = 0
    while (tail < len(old_lines) - head and tail < len(new_lines) - head
           and old_lines[-1 - tail] == new_lines[-1 - tail]):
        tail += 1
    if head == len(old_lines) == len(new_lines):
        return span, None
    return span, LineEdit(first + head, first + len(old_lines) - 1 - tail,
                          tuple(new_lines[head:len(new_lines) - tail]))


def _first_error(errors: Sequence, ranges: Sequence[tuple[int, int]] | None):
    """The first diagnostic inside ``ranges`` (None: anywhere); a lineless one counts."""
    for diag in errors:
        if ranges is None or diag.line is None or _meets(diag.line, diag.line, ranges):
            return diag
    return None


def _refuse_parse(ref: str, diag) -> ToolError:
    return ToolError(DOESNT_PARSE.format(file=one_line(ref), line=diag.line or 1,
                                         message=one_line(diag.message(), 300)))


def _plan_file(ws: Workspace, ref: str, items: Sequence[tuple[str, str]], *, new: bool,
               positions: frozenset[str]) -> _Planned:
    shown = one_line(ref)
    if new:
        if len(items) != 1 or items[0][0] != "":
            raise ToolError(NEW_FILE_ONCE)
        body = _new_file_lines(items[0][1])
        if body == [""]:
            raise ToolError(NO_CHANGE)
        edits = (LineEdit(1, 1, tuple(body)),)
        text, lines, source = "", [""], None
    else:
        source = ws.read(ref)
        text, lines = source.text, source.lines
        spans: list[tuple[tuple[int, int], LineEdit | None]] = []
        for old, new_text in items:
            if old == "":
                raise ToolError(EMPTY_OLD.format(file=shown))
            spans.append(_edit_for(text, ref, old, new_text))
        spans.sort(key=lambda item: item[0])
        for (one, _), (two, _) in zip(spans, spans[1:]):
            if two[0] <= one[1]:
                raise ToolError(OVERLAP.format(file=shown))
        edits = tuple(edit for _, edit in spans if edit is not None)
        if not edits:
            raise ToolError(NO_CHANGE)
    new_lines = apply_lines(lines, edits)
    new_text = "\n".join(new_lines)
    nodes, errors = _parse(ref, new_text, positions)
    if nodes is None:
        raise ToolError(DOESNT_PARSE.format(file=shown, line=1,
                                            message="it is nested too deeply to read"))
    found = _first_error(errors, None if new else new_ranges(edits))
    if found is not None:
        raise _refuse_parse(ref, found)
    guards, touched, marks, preamble = _guards(text, lines, edits) if not new else \
        ((), (), (), None)
    plan = FilePlan(ref, guards, edits)
    if not verify(Plan("", (plan,)), {ref: text}, positions=positions):
        other = _first_error(errors, None)
        if other is not None:
            raise ToolError(FIX_FIRST.format(file=shown, line=other.line or 1,
                                              message=one_line(other.message(), 300)))
        raise ToolError(UNSAFE)
    code = code_bearing(ref, lines, edits, new=new, positions=positions)
    diff, sent = numbered_diff(lines, edits, new=new)
    added = sum(len(e.lines) for e in edits)
    removed = 0 if new else sum(e.last - e.first + 1 for e in edits)
    data = ((new_text + "\n").encode("utf-8") if new
            else source.encode(new_text))          # type: ignore[union-attr]
    return _Planned(ProposalFile(ref, None if new else source.sha, plan, new, code,  # type: ignore[union-attr]
                                 added, removed, tuple(diff), tuple(sent), touched, marks,
                                 preamble), data, edits)


def _read_changes(ws: Workspace, args: object) -> tuple[str, dict[str, list[tuple[str, str]]],
                                                         set[str]]:
    args = check_keys(args, ("summary", "changes"))
    summary = text_arg(args, "summary", limit=SUMMARY_MAX_CHARS)
    changes = args["changes"]
    if type(changes) is not list or not 1 <= len(changes) <= CHANGES_MAX:
        raise ToolError(CHANGES_SHAPE)
    table = ws.table()
    by_file: dict[str, list[tuple[str, str]]] = {}
    new_refs: set[str] = set()
    new_bytes = 0
    for change in changes:
        if type(change) is not dict:
            raise ToolError(CHANGE_SHAPE)
        check_keys(change, ("file", "old_text", "new_text"))
        old = _change_text(change, "old_text")
        new = _change_text(change, "new_text")
        new_bytes += _size(new)
        target = change["file"]
        if table.is_script(target):
            ref = target
        elif target == CONFIG_REF:
            raise ToolError(NOT_EDITABLE)
        elif old == "":
            problem = new_ref_problem(ws.paths, target, table.scripts)
            if problem is not None:
                raise ToolError(problem)
            ref = target
            new_refs.add(ref)
        else:
            ref = table.script(target)
        by_file.setdefault(ref, []).append((old, new))    # type: ignore[arg-type]
        if len(by_file) > FILES_MAX:
            raise ToolError(TOO_MANY_FILES)
    if new_bytes > NEW_TEXT_MAX_BYTES:
        raise ToolError(NEW_TEXT_TOO_LONG)
    return summary, by_file, new_refs


def propose(ws: Workspace, args: object, *, check: bool = True,
            cancel: threading.Event | None = None) -> Proposal:
    """§7.1. ``ToolError`` for a refused proposal (bad arguments, a ref that isn't a script
    file or a valid new one, text not found once, overlaps, a parse error, a plan that
    doesn't verify). ``check=False`` skips the two checks (tests)."""
    summary, by_file, new_refs = _read_changes(ws, args)
    positions = ws.position_names()
    planned = [_plan_file(ws, ref, items, new=ref in new_refs, positions=positions)
               for ref, items in by_file.items()]
    files = tuple(item.file for item in planned)
    code = any(f.code for f in files)
    launch = ws.launch_allowed and not code
    if not check:
        return Proposal(summary, files, code, launch, checked=False)
    base = ws.base_check(launch=launch, cancel=cancel)
    if base.result is None:
        return Proposal(summary, files, code, launch, reason=base.reason)
    done = ws.check_with([(item.file.ref, item.data) for item in planned],
                         [item.file.ref for item in planned if item.file.new],
                         launch=launch, cancel=cancel)
    if done.result is None:
        return Proposal(summary, files, code, launch, reason=done.reason)
    maps = {item.file.ref: line_map(item.edits) for item in planned if not item.file.new}
    added, fixed = problem_delta(base.result.problems, done.result.problems, maps)
    return Proposal(summary, files, code, launch, added[:PROBLEMS_MAX], len(fixed))


def verify_file(file: ProposalFile, text: str, *, positions: frozenset[str] | None = None
                ) -> bool:
    """``file``'s plan still fits ``text``: ``tomlpatch.verify`` for a settings plan, else
    ``scriptedit.verify``. Every Apply passes this gate."""
    if file.settings is not None:
        return file.ref == CONFIG_REF and settings_fit(file.settings, text)
    return verify(Plan("", (file.plan,)), {file.ref: text}, positions=positions or ())


# --- propose_settings (2026-11-04) ----------------------------------------------------------

def _read_settings(args: object) -> tuple[str, list[tuple[str, str, object]]]:
    args = check_keys(args, ("summary", "changes"))
    summary = text_arg(args, "summary", limit=SUMMARY_MAX_CHARS)
    changes = args["changes"]
    if type(changes) is not list or not 1 <= len(changes) <= SETTINGS_MAX:
        raise ToolError(SETTINGS_SHAPE)
    out: list[tuple[str, str, object]] = []
    for change in changes:
        if type(change) is not dict:
            raise ToolError(SETTING_SHAPE)
        check_keys(change, ("section", "key", "value"))
        section, key = change["section"], change["key"]
        if type(section) is not str or type(key) is not str or not section or not key \
                or len(section) > 200 or len(key) > 200:
            raise ToolError(SETTING_SHAPE)
        value = change["value"]
        if isinstance(value, str) and _size(value) > CHANGE_TEXT_MAX_BYTES:
            raise ToolError(TEXT_TOO_LONG.format(key="value"))
        out.append((section, key, value))
    return summary, out


def propose_settings(ws: Workspace, args: object, *, check: bool = True,
                     cancel: threading.Event | None = None) -> Proposal:
    """``propose_settings``: ``config.toml`` settings by section and key (value None: the
    default again), planned by ``tomlpatch`` and checked like ``propose``. ``ToolError`` for a
    key that isn't a setting, a value it refuses, or a change that changes nothing."""
    summary, changes = _read_settings(args)
    if not ws.table().config:
        raise ToolError(NO_CONFIG)
    source = ws.read(CONFIG_REF)
    planned = plan_changes(source.text, changes, title=summary)
    if isinstance(planned, Refuse):
        raise ToolError(planned.text)
    if planned is None:
        raise ToolError(NO_CHANGE)
    edits = planned.edits
    diff, sent = numbered_diff(source.lines, edits, new=False)
    new_text = NL.join(apply_lines(source.lines, edits))
    file = ProposalFile(CONFIG_REF, source.sha, FilePlan(CONFIG_REF, (), edits), False, False,
                        sum(len(e.lines) for e in edits),
                        sum(e.last - e.first + 1 for e in edits), tuple(diff), tuple(sent),
                        settings=planned)
    launch = ws.launch_allowed
    if not check:
        return Proposal(summary, (file,), False, launch, checked=False)
    base = ws.base_check(launch=launch, cancel=cancel)
    if base.result is None:
        return Proposal(summary, (file,), False, launch, reason=base.reason)
    done = ws.check_with([(CONFIG_REF, source.encode(new_text))], [], launch=launch,
                         cancel=cancel)
    if done.result is None:
        return Proposal(summary, (file,), False, launch, reason=done.reason)
    added, fixed = problem_delta(base.result.problems, done.result.problems,
                                 {CONFIG_REF: line_map(edits)})
    return Proposal(summary, (file,), False, launch, added[:PROBLEMS_MAX], len(fixed))


# --- The result (§7.1 step 7; 01 §6.3) ------------------------------------------------------

def _problem_row(item: CheckItem, many: bool) -> str:
    code = item.code or item.severity
    text = one_line(item.text)
    if item.line is None:
        return ADD_ROW_NO_LINE.format(code=code, text=text)
    if many and item.file is not None:
        return ADD_ROW_FILE.format(code=code, file=one_line(item.file), line=item.line,
                                   text=text)
    return ADD_ROW.format(code=code, line=item.line, text=text)


def check_lines(proposal: Proposal) -> list[str]:
    """01 §6.3's check texts for ``proposal``, then the two code texts when code-bearing."""
    rows: list[str] = []
    if proposal.reason is not None:
        rows.append(CHECK_UNKNOWN.format(reason=proposal.reason + "."))
    elif proposal.checked:
        if proposal.added:
            rows.append(ADDS.format(n=len(proposal.added)))
            many = len(proposal.files) > 1
            rows += [_problem_row(item, many) for item in proposal.added[:ADDED_SHOWN]]
        else:
            rows.append(NO_NEW_PROBLEMS)
        if proposal.fixed:
            rows.append(FIXES.format(n=proposal.fixed))
    if proposal.code:
        rows += [NO_CODE_RUN, CODE_NOTICE]
    return rows


def render(proposal: Proposal, *, id: str | None = None, card: bool = False) -> ToolText:
    """The ``propose_edit`` result: the summary, the id (MCP), each file's numbered diff,
    the check texts, and how it is applied."""
    out = TextOut()
    out.echo(PROPOSED, proposal.summary)
    if id is not None:
        out.line(ID_LINE.format(id=id))
    for file in proposal.files:
        out.line(f"{one_line(file.ref)}{NEW_FILE_MARK if file.new else ''}, "
                 f"+{file.added} −{file.removed}:")
        for row in file.diff:
            out.line(row)
        for first, last in file.sent:
            out.record_range(file.ref, first, last)
    rows = check_lines(proposal)
    out.record_problems(min(len(proposal.added), ADDED_SHOWN))
    for row in rows:
        out.line(row)
    if card:
        out.line(CARD_SHOWN)
    elif id is not None:
        out.line(APPLY_HINT)
    return out.result()


__all__ = ["propose_settings", "verify_file",
           "ADDS", "APPLY_HINT", "CARD_SHOWN", "CHANGES_MAX", "CHANGE_TEXT_MAX_BYTES",
           "CHECK_UNKNOWN", "CODE_NOTICE", "CODE_WORDS", "DOESNT_PARSE", "EMPTY_OLD",
           "FILES_MAX", "FIXES", "FIX_FIRST", "FOUND_MANY", "NEW_FILE_ONCE",
           "NEW_TEXT_MAX_BYTES", "NOT_FOUND", "NO_CHANGE", "NO_CODE_RUN", "NO_NEW_PROBLEMS",
           "OVERLAP", "Proposal", "ProposalFile", "SUMMARY_MAX_CHARS", "TOO_MANY_FILES",
           "backstop", "check_lines", "code_bearing", "line_map", "new_ranges",
           "numbered_diff", "problem_delta", "propose", "rebase", "render"]
