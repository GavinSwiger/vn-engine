"""The console's state and rules, with no pygame (F40 ``04`` §3, §7.1, §7.4; ``01`` §4.2, §6).

Why this module exists: what the console shows and what each action does must be testable
without a window, and must be the same whether a key in the game or a Studio message asked
for it. ``panel.py`` only draws this model and turns raw input into calls on it; W1's
``DevConsole`` decides *when* an action is applied (only while the story rests, ``04``
§7.1) and answers Studio with ``Result.text``.

**Tabs.** Variables (every ``default`` in the program's order, then every meter, values cut
to 80 by ``valuetext``; a filter by name; Enter opens a prefilled value field, Enter again
sets), Jump (every label in reading order with its file and line; a filter) and Code (one
line, the last ``CODE_RESULTS`` results, Up/Down recall the last ``HISTORY_MAX`` lines). The
tab, the filters and the history live as long as the model, so the console reopens as it was
(PR-F40-06).

**Where the story is** (``04`` §7.1): ``where_now`` sorts the moment into ``Where``. Looking
works everywhere it may open; Set and Code need ``STORY``; Jump needs ``STORY`` or
``NO_STORY`` (then it starts a new game). A replay or a minigame refuses all three with its
text, before any author code runs (SEC-F40-10).

**Changes** go through ``Interpreter.console_change`` (Set, Switch, ±1, Code), so each one is
part of the current step and a wall, and is undone with ``CANT_SAVE`` when it can't be saved
(PR-F40-14, -15). A typed value is read only by F44's ``parse_literal`` (never evaluated) and
bound as its ``freeze`` copy; a meter takes a whole number and is clamped (PR-F40-08, -09).

**The interface to P1 and W1** (all passed in, so this module never imports the runner):

- ``run_code(interp, line) -> CodeOutcome``: P1's ``runner.run_code``. It checks the line
  (``codecheck``) and runs it guarded; ``.lines`` are the output lines (``print`` text, then
  the value or ``Done.``, or one error line) and ``.ok`` is False when the line was refused,
  raised or ran too long; ``.undone`` is why a change was undone. It makes the one
  ``console_change`` of the run itself, so the model doesn't wrap it.
- ``guarded(interp, fn)``: P1's ``runner.guarded``; the one call into author code that a
  Variables refresh or a ``values`` answer makes for author objects' ``repr`` (``TextBatch``).
  None: author objects show ``<can't show this value>``.
- ``jump(label, new_game) -> str | None``: W1's. ``new_game`` False: the shell's
  ``enter_game(lambda: interp.console_jump(label), choose=False)``; True (no story running):
  a new game at the label (Play from scene). Returns None, or the reason the live values
  can't be saved (``console_jump``'s E85e message).

**Logging** (PR-F40-17, SEC-F40-08): one INFO record in area ``console`` per action whose
variable or label name resolved, naming the action, that name and how it ended. Never the
typed text, a value, or code; a name that didn't resolve is never logged.
"""

import math
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from engine.core.editorreport import CONSOLE_LABEL_MAX, CONSOLE_NAME_MAX
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.core.startvalues import StartValueError, parse_literal
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.values import Unsaveable, freeze
from engine.script.program import Program
from engine.tools.console import texts
from engine.tools.console.valuetext import (CANT_SHOW, CODE_MAX, INT_BITS_MAX, ROW_MAX,
                                            VALUES_MAX, TextBatch, value_text)

LIST_ROWS = 9                             # rows the list shows at once (01 §6.1)
HISTORY_MAX = 50                          # Code lines Up/Down recall (PR-F40-13)
CODE_RESULTS = 6                          # Code results kept above the input (01 §6.2)
INPUT_MAX = CODE_MAX                      # any field: 2,000 (PR-F40-13, SEC-F40-12)
FILTER_MAX = 255
NAME_SHOWN = ROW_MAX                      # a name inside a result text

_log = get_logger("console")

# NUL, C0, DEL and C1 controls: never kept in a field (SEC-F40-12).
_CONTROLS = dict.fromkeys((*range(0x20), 0x7F, *range(0x80, 0xA0)))


class Tab(Enum):
    VARIABLES = "variables"
    JUMP = "jump"
    CODE = "code"


TABS = (Tab.VARIABLES, Tab.JUMP, Tab.CODE)
TAB_TEXTS = {Tab.VARIABLES: texts.TAB_VARIABLES, Tab.JUMP: texts.TAB_JUMP,
             Tab.CODE: texts.TAB_CODE}


class Where(Enum):
    """Where the story is when the console looks or acts (``04`` §7.1)."""

    STORY = "story"                       # a game waits at a line: everything works
    NO_STORY = "no story"                 # the title, or no line waiting: Jump starts a game
    REPLAY = "replay"                     # F36: looking only
    MINIGAME = "minigame"                 # F23: looking only


def where_now(interp: Interpreter | None, *, title: bool = False,
              minigame_host: bool = False) -> Where:
    """``04`` §7.1's table. ``title``: the shell is on the title (mode TITLE).
    ``minigame_host``: a minigame host runs. Loading, error mode and F30's screens are W1's
    (the console doesn't open there, and Studio's messages are dropped)."""
    if title or interp is None:
        return Where.NO_STORY
    if interp.minigame_wait is not None or minigame_host:
        return Where.MINIGAME
    if interp.replay is not None:
        return Where.REPLAY
    if interp.status is Status.WAITING and interp.current is not None:
        return Where.STORY
    return Where.NO_STORY


# --- Actions and results --------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SetValue:
    """Set a story variable or meter from literal text (Enter in the value field; Studio's
    ``set``)."""

    name: str
    text: str


@dataclass(frozen=True, slots=True)
class Nudge:
    """The ``-1`` / ``+1`` buttons on a whole-number row."""

    name: str
    delta: int


@dataclass(frozen=True, slots=True)
class Switch:
    """The ``Switch`` button on a ``True``/``False`` row."""

    name: str


@dataclass(frozen=True, slots=True)
class JumpTo:
    """Jump the story to a label (Enter on the Jump tab; Studio's ``jump``)."""

    label: str


@dataclass(frozen=True, slots=True)
class RunCode:
    """Run one Code line."""

    line: str


@dataclass(frozen=True, slots=True)
class Close:
    """Close the console (Esc, F12, a pad's east button, a click on ``F12 / Esc``)."""


Action = SetValue | Nudge | Switch | JumpTo | RunCode


@dataclass(frozen=True, slots=True)
class Result:
    """What an action did: ``text`` is shown on the console's output line and sent to Studio
    as the answer's ``text``. ``ok`` False draws it in the error color."""

    ok: bool
    text: str


class CodeOutcome(Protocol):
    """P1's ``CodeResult`` as the model reads it. ``undone``: why ``console_change`` undid a
    change that ran without an error, else None."""

    lines: Sequence[str]
    ok: bool
    undone: str | None


RunCodeFn = Callable[[Interpreter, str], CodeOutcome]
GuardedFn = Callable[[Interpreter, Callable[[], None]], object]
JumpFn = Callable[[str, bool], "str | None"]


@dataclass(frozen=True, slots=True)
class CodeEntry:
    """One Code run as the tab shows it: the line, its output lines, and whether it worked."""

    line: str
    lines: tuple[str, ...]
    ok: bool


@dataclass(frozen=True, slots=True)
class Row:
    """One list row. ``kind``: ``"group"`` (a caption: ``name`` is its text), ``"variable"``,
    ``"meter"`` or ``"label"``. ``text`` is the value text (80) or the label's place.
    ``buttons`` are the row's button texts. ``literal`` is the value field's prefill, None
    when the value isn't plain data (``NOT_PLAIN``)."""

    kind: str
    name: str
    text: str = ""
    buttons: tuple[str, ...] = ()
    literal: str | None = None

    @property
    def selectable(self) -> bool:
        return self.kind != "group"


# --- Text helpers ----------------------------------------------------------------------------

def clean_input(text: object, cap: int = INPUT_MAX) -> str:
    """What a field keeps of typed or pasted text: its first line, without NUL and C0/C1
    controls, cut to ``cap`` (SEC-F40-12). Bounded work on a huge paste."""
    if type(text) is not str:
        return ""
    lines = text[:cap * 4].splitlines()
    first = lines[0] if lines else ""
    return first.translate(_CONTROLS)[:cap]


def literal_text(value: object, cap: int = INPUT_MAX) -> str | None:
    """``value`` as literal text ``parse_literal`` reads back (the value field's prefill), or
    None when it isn't plain data (a tuple, an object, a non-text dict key, a cycle, too deep)
    or its text is over ``cap``. Walks with an explicit stack and a size budget, so a huge or
    self-containing value costs at most about ``cap`` steps; no author code runs."""
    budget = cap
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        kind = type(item)
        if item is None or kind is bool:
            budget -= 5
        elif kind is int:
            if item.bit_length() > min(INT_BITS_MAX, cap * 4):
                return None
            budget -= len(str(item))
        elif kind is float:
            if not math.isfinite(item):
                return None
            budget -= len(repr(item))
        elif kind is str:
            budget -= len(item) + 2
        elif kind is list or kind is dict:
            if depth >= 100:
                return None
            budget -= 2 + 2 * len(item)
            if budget < 0:
                return None
            if kind is list:
                stack.extend((x, depth + 1) for x in item)
            else:
                for key, x in item.items():
                    if type(key) is not str:
                        return None
                    stack.append((key, depth + 1))
                    stack.append((x, depth + 1))
        else:
            return None
        if budget < 0:
            return None
    text = repr(value)
    return text if len(text) <= cap else None


def _shown(name: object) -> str:
    return echo(str(name), NAME_SHOWN)


# --- Fields ----------------------------------------------------------------------------------

class Field:
    """One line of text with a cursor (a filter, the value field, the Code input)."""

    __slots__ = ("text", "cursor", "cap")

    def __init__(self, cap: int = INPUT_MAX) -> None:
        self.text = ""
        self.cursor = 0
        self.cap = cap

    def set(self, text: str) -> None:
        self.text = clean_input(text, self.cap)
        self.cursor = len(self.text)

    def insert(self, text: str) -> bool:
        piece = clean_input(text, self.cap)
        room = self.cap - len(self.text)
        piece = piece[:max(room, 0)]
        if not piece:
            return False
        self.text = self.text[:self.cursor] + piece + self.text[self.cursor:]
        self.cursor += len(piece)
        return True

    def backspace(self) -> bool:
        if self.cursor == 0:
            return False
        self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
        self.cursor -= 1
        return True

    def delete(self) -> bool:
        if self.cursor >= len(self.text):
            return False
        self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
        return True

    def move(self, delta: int) -> None:
        self.cursor = min(max(self.cursor + delta, 0), len(self.text))

    def home(self) -> None:
        self.cursor = 0

    def end(self) -> None:
        self.cursor = len(self.text)


# --- The model -------------------------------------------------------------------------------

class ConsoleModel:
    """The console's state for one run (module docstring). ``program`` is the running
    story's; W1 makes a new model when F39 reloads."""

    def __init__(self, program: Program, *, run_code: RunCodeFn, jump: JumpFn,
                 guarded: GuardedFn | None = None) -> None:
        self.program = program
        self._run_code = run_code
        self._jump = jump
        self._guarded = guarded
        self.tab = Tab.VARIABLES
        self.where = Where.NO_STORY
        self.header = texts.HEADER_NO_STORY
        self.filters = {Tab.VARIABLES: Field(FILTER_MAX), Tab.JUMP: Field(FILTER_MAX)}
        self.value = Field()                       # the Variables value field
        self.code = Field()                        # the Code input
        self.editing: str | None = None            # the row whose value field is open
        self.output: dict[Tab, Result | None] = {tab: None for tab in TABS}
        self.results: deque[CodeEntry] = deque(maxlen=CODE_RESULTS)
        self.history: deque[str] = deque(maxlen=HISTORY_MAX)
        self._recall: int | None = None            # index into history while recalling
        self._draft = ""
        self.version = 0                           # bumped on every visible change
        meters = tuple(meter.name for meter in program.meters)
        defaults: list[str] = []
        for node in program.defaults:
            if node.name not in defaults and node.name not in meters:
                defaults.append(node.name)
        self._defaults = tuple(defaults)
        self._meters = meters
        self._specs = {meter.name: meter for meter in program.meters}
        self._rows: dict[Tab, list[Row]] = {Tab.VARIABLES: [], Tab.JUMP: self._label_rows()}
        self._selected = {Tab.VARIABLES: 0, Tab.JUMP: 0}
        self._top = {Tab.VARIABLES: 0, Tab.JUMP: 0}
        self._visible: dict[Tab, tuple[tuple, list[Row]]] = {}

    # -- Names ---------------------------------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        """Every story variable the console knows: defaults, then meters."""
        return self._defaults + self._meters

    def is_variable(self, name: object) -> bool:
        return (type(name) is str and len(name) <= CONSOLE_NAME_MAX
                and (name in self._specs or name in self._defaults))

    def _label_rows(self) -> list[Row]:
        return [Row("label", name, texts.LABEL_PLACE.format(file=echo(label.file.ref, ROW_MAX),
                                                            line=label.line))
                for name, label in self.program.labels.items()]

    # -- Looking (no story change) ----------------------------------------------------------------

    def refresh(self, where: Where, interp: Interpreter | None) -> None:
        """Rebuild the header and the Variables rows (on open, after a change, on Studio's
        ``values``; never per frame). At most one guarded call for author objects."""
        self.where = where
        self.header = self._header(where, interp)
        rows: list[Row] = []
        if where is not Where.NO_STORY and interp is not None:
            entries = self._entries(interp, ROW_MAX)
            variables = [self._variable_row(name, value, shown) for kind, name, value, shown
                         in entries if kind == "variable"]
            meters = [self._meter_row(name, value, shown) for kind, name, value, shown
                      in entries if kind == "meter"]
            if variables:
                rows.append(Row("group", texts.GROUP_VARIABLES))
                rows.extend(variables)
            if meters:
                rows.append(Row("group", texts.GROUP_METERS))
                rows.extend(meters)
        self._rows[Tab.VARIABLES] = rows
        if self.editing is not None and not any(r.name == self.editing for r in rows):
            self.editing = None
        self._changed()

    def values(self, where: Where, interp: Interpreter | None
               ) -> tuple[bool, list[tuple[str, str]]]:
        """Studio's ``values`` answer: whether a story runs, and ``(name, text)`` for every
        default and meter, texts at most ``VALUES_MAX`` (one guarded call in all)."""
        if where is Where.NO_STORY or interp is None:
            return False, []
        return True, [(name, shown) for _, name, _, shown in self._entries(interp, VALUES_MAX)]

    def _entries(self, interp: Interpreter, cap: int) -> list[tuple[str, str, object, str]]:
        """``(kind, name, value, text)`` for every default then meter; one batch."""
        G = interp.G
        batch = TextBatch()
        found: list[tuple[str, str, object, int]] = []
        missing = object()
        for name in self._defaults:
            value = G.get(name, missing)
            found.append(("variable", name, value,
                          -1 if value is missing else batch.add(value, cap)))
        for name in self._meters:
            try:
                value = interp.points.get(name)
            except Exception:                 # noqa: BLE001 (a meter that can't be read)
                found.append(("meter", name, missing, -1))
                continue
            found.append(("meter", name, value, batch.add(value, cap)))
        call = None
        if self._guarded is not None and batch.needs_call:
            guarded = self._guarded

            def call(fn: Callable[[], None]) -> object:
                return guarded(interp, fn)
        shown = batch.texts(call)
        return [(kind, name, None if value is missing else value,
                 CANT_SHOW if index < 0 else shown[index])
                for kind, name, value, index in found]

    def _variable_row(self, name: str, value: object, shown: str) -> Row:
        kind = type(value)
        buttons = ((texts.SWITCH,) if kind is bool
                   else (texts.MINUS, texts.PLUS) if kind is int else ())
        return Row("variable", name, shown, buttons, literal_text(value))

    def _meter_row(self, name: str, value: object, shown: str) -> Row:
        spec = self._specs[name]
        if type(value) is not int:
            return Row("meter", name, shown)
        text = (texts.METER_VALUE.format(value=shown, low=spec.low, high=spec.high)
                if spec.ranged else shown)
        return Row("meter", name, text, (texts.MINUS, texts.PLUS), str(value))

    def _header(self, where: Where, interp: Interpreter | None) -> str:
        current = None if interp is None or where is Where.NO_STORY else interp.current
        if current is None:
            return texts.HEADER_NO_STORY
        return texts.HEADER.format(label=_shown(current.label),
                                   file=echo(current.file.ref, ROW_MAX), line=current.line)

    # -- The list ----------------------------------------------------------------------------------

    @property
    def field(self) -> Field:
        """The field typing goes to: the Code input, the open value field, or the tab's
        filter."""
        if self.tab is Tab.CODE:
            return self.code
        if self.tab is Tab.VARIABLES and self.editing is not None:
            return self.value
        return self.filters[self.tab]

    def visible(self, tab: Tab | None = None) -> list[Row]:
        """The list rows of ``tab`` (default: the current one) that match its filter, with
        each group caption kept only above a matching row. Cached until rows or filter
        change."""
        tab = self.tab if tab is None else tab
        if tab is Tab.CODE:
            return []
        rows = self._rows[tab]
        needle = self.filters[tab].text.strip().casefold()
        key = (id(rows), needle)
        cached = self._visible.get(tab)
        if cached is not None and cached[0] == key:
            return cached[1]
        if not needle:
            out = list(rows)
        else:
            out = []
            caption: Row | None = None
            for row in rows:
                if not row.selectable:
                    caption = row
                elif needle in row.name.casefold():
                    if caption is not None:
                        out.append(caption)
                        caption = None
                    out.append(row)
        self._visible[tab] = (key, out)
        return out

    @property
    def empty_text(self) -> str:
        """Why the current list is empty ("" when it isn't)."""
        if self.tab is Tab.CODE or self.visible():
            return ""
        flt = self.filters[self.tab].text.strip()
        if flt:
            return texts.NOTHING_MATCHES.format(filter=echo(flt, ROW_MAX))
        if self.tab is Tab.VARIABLES:
            return texts.NO_STORY if self.where is Where.NO_STORY else texts.NO_VARIABLES
        return ""

    @property
    def selected_index(self) -> int:
        """The selected row's index in ``visible()``, or -1."""
        if self.tab is Tab.CODE:
            return -1
        rows = self.visible()
        index = self._selected[self.tab]
        if not rows:
            return -1
        index = min(max(index, 0), len(rows) - 1)
        if not rows[index].selectable:
            index = self._next_selectable(rows, index, 1)
        return index

    @property
    def selected(self) -> Row | None:
        index = self.selected_index
        return None if index < 0 else self.visible()[index]

    @property
    def top(self) -> int:
        """The first visible row the list draws (LIST_ROWS at a time)."""
        if self.tab is Tab.CODE:
            return 0
        rows = self.visible()
        top = min(max(self._top[self.tab], 0), max(len(rows) - LIST_ROWS, 0))
        index = self.selected_index
        if index >= 0:
            if index < top:
                top = index
            elif index >= top + LIST_ROWS:
                top = index - LIST_ROWS + 1
            if top > 0 and index == top and not rows[top - 1].selectable:
                top -= 1                      # keep a group's caption above its first row
        self._top[self.tab] = top
        return top

    @staticmethod
    def _next_selectable(rows: list[Row], index: int, step: int) -> int:
        i = index
        while 0 <= i < len(rows):
            if rows[i].selectable:
                return i
            i += step
        i = index - step
        while 0 <= i < len(rows):
            if rows[i].selectable:
                return i
            i -= step
        return -1

    def select(self, index: int) -> None:
        """Select ``visible()[index]`` (a click); a caption selects the row after it."""
        if self.tab is Tab.CODE:
            return
        rows = self.visible()
        if not rows:
            return
        index = min(max(index, 0), len(rows) - 1)
        new = self._next_selectable(rows, index, 1)
        if new >= 0 and new != self.selected_index:
            self.editing = None
        self._selected[self.tab] = max(new, 0)
        self._changed()

    def move(self, delta: int) -> None:
        """Up/Down: the list selection, or on the Code tab the history (Up is older)."""
        if self.tab is Tab.CODE:
            self._recall_step(delta)
            return
        rows = self.visible()
        index = self.selected_index
        if index < 0:
            return
        step = 1 if delta > 0 else -1
        target = index
        for _ in range(abs(delta)):
            i = target + step
            while 0 <= i < len(rows) and not rows[i].selectable:
                i += step
            if not 0 <= i < len(rows):
                break
            target = i
        if target != index:
            self.editing = None
            self._selected[self.tab] = target
            self._changed()

    def scroll(self, delta: int) -> None:
        """The wheel: move the list's first row by ``delta`` (the selection stays)."""
        if self.tab is Tab.CODE:
            return
        rows = self.visible()
        top = min(max(self._top[self.tab] + delta, 0), max(len(rows) - LIST_ROWS, 0))
        index = self.selected_index
        if index >= 0 and not top <= index < top + LIST_ROWS:
            # Keep the selection on screen: it follows the view.
            inside = [i for i in range(top, min(top + LIST_ROWS, len(rows)))
                      if rows[i].selectable]
            if inside:
                self._selected[self.tab] = inside[0] if index < top else inside[-1]
                self.editing = None
        self._top[self.tab] = top
        self._changed()

    # -- Tabs and typing -----------------------------------------------------------------------------

    def select_tab(self, tab: Tab) -> None:
        if tab is not self.tab:
            self.tab = tab
            self.editing = None
            self._recall = None
            self._changed()

    def next_tab(self, step: int = 1) -> None:
        self.select_tab(TABS[(TABS.index(self.tab) + step) % len(TABS)])

    def insert(self, text: str) -> None:
        """Typed or pasted text, into the focused field."""
        field = self.field
        if field.insert(text):
            self._edited(field)

    def backspace(self) -> None:
        field = self.field
        if field.backspace():
            self._edited(field)

    def delete(self) -> None:
        field = self.field
        if field.delete():
            self._edited(field)

    def cursor(self, how: str) -> None:
        """``"left"``, ``"right"``, ``"home"`` or ``"end"`` in the focused field."""
        field = self.field
        if how == "left":
            field.move(-1)
        elif how == "right":
            field.move(1)
        elif how == "home":
            field.home()
        else:
            field.end()
        self._changed()

    def _edited(self, field: Field) -> None:
        if self.tab is not Tab.CODE and field is self.filters.get(self.tab):
            self._selected[self.tab] = 0
            self._top[self.tab] = 0
        if field is self.code:
            self._recall = None
        self._changed()

    def _recall_step(self, delta: int) -> None:
        history = self.history
        if not history:
            return
        if self._recall is None:
            if delta > 0:
                return
            self._draft = self.code.text
            index = len(history) - 1
        else:
            index = self._recall + (1 if delta > 0 else -1)
        if index < 0:
            index = 0
        if index >= len(history):
            self._recall = None
            self.code.set(self._draft)
        else:
            self._recall = index
            self.code.set(history[index])
        self._changed()

    # -- Enter, Esc and buttons -------------------------------------------------------------------------

    def enter(self) -> Action | None:
        """Enter on the current tab: opens the value field (no action), or returns the action
        to apply once the story rests."""
        if self.tab is Tab.CODE:
            line = clean_input(self.code.text)
            if not line.strip():
                return None
            if not self.history or self.history[-1] != line:
                self.history.append(line)
            self._recall = None
            self._draft = ""
            self.code.set("")
            self._changed()
            return RunCode(line)
        row = self.selected
        if row is None:
            return None
        if self.tab is Tab.JUMP:
            return JumpTo(row.name)
        if self.editing is not None:
            return SetValue(self.editing, self.value.text)
        if row.literal is None:
            self.output[Tab.VARIABLES] = Result(False, texts.NOT_PLAIN)
        else:
            self.editing = row.name
            self.value.set(row.literal)
        self._changed()
        return None

    def escape(self) -> bool:
        """Esc: closes an open value field (True), else the console should close (False)."""
        if self.tab is Tab.VARIABLES and self.editing is not None:
            self.editing = None
            self._changed()
            return True
        return False

    def press(self, name: str, button: str) -> Action | None:
        """A row's button: ``Switch``, ``-1`` or ``+1``."""
        if button == texts.SWITCH:
            return Switch(name)
        if button == texts.MINUS:
            return Nudge(name, -1)
        if button == texts.PLUS:
            return Nudge(name, 1)
        return None

    def primary(self) -> Action | None:
        """A pad's south button: Switch or +1 on a Variables row, jump on the Jump tab.
        Pads don't type, so the value field and the Code tab do nothing."""
        row = self.selected
        if row is None or self.tab is Tab.CODE:
            return None
        if self.tab is Tab.JUMP:
            return JumpTo(row.name)
        if row.buttons:
            return self.press(row.name, row.buttons[-1])
        return None

    def secondary(self) -> Action | None:
        """A pad's west button: -1 on a whole-number row."""
        row = self.selected
        if self.tab is Tab.VARIABLES and row is not None and texts.MINUS in row.buttons:
            return Nudge(row.name, -1)
        return None

    def opened(self, where: Where, interp: Interpreter | None) -> None:
        """The console opened: fresh values, same tab and filters (PR-F40-06)."""
        self.refresh(where, interp)

    def closed(self) -> None:
        """The console closed: an open value field and a history recall end."""
        self.editing = None
        self._recall = None
        self._changed()

    @staticmethod
    def studio_action(request: object) -> Action | None:
        """Studio's ``jump`` and ``set`` (P2's ``ConsoleRequest``) as actions; ``open`` and
        ``values`` aren't actions (None)."""
        do = getattr(request, "do", None)
        if do == "jump":
            return JumpTo(getattr(request, "label", None))      # type: ignore[arg-type]
        if do == "set":
            return SetValue(getattr(request, "name", None),     # type: ignore[arg-type]
                            getattr(request, "value", None))    # type: ignore[arg-type]
        return None

    # -- Applying actions --------------------------------------------------------------------------------

    def apply(self, action: Action, where: Where, interp: Interpreter | None) -> Result:
        """Do ``action`` now (W1 calls this only while the story rests). The result is also
        the tab's output line (Code: a new entry above the input). Refreshes the Variables
        rows after a Set or Code run."""
        self.where = where
        if isinstance(action, RunCode):
            result = self._code(action.line, where, interp)
        elif isinstance(action, JumpTo):
            result = self._jump_to(action.label, where)
            self.output[Tab.JUMP] = result
        else:
            result = self._set(action, where, interp)
            self.output[Tab.VARIABLES] = result
            if result.ok:
                self.editing = None
        if not isinstance(action, JumpTo):
            self.refresh(where, interp)
        self._changed()
        return result

    def _refusal(self, where: Where, *, jump: bool = False) -> str | None:
        if where is Where.MINIGAME:
            return texts.MINIGAME
        if where is Where.REPLAY:
            return texts.REPLAY
        if where is Where.NO_STORY and not jump:
            return texts.NO_STORY
        return None

    def _set(self, action: SetValue | Nudge | Switch, where: Where,
             interp: Interpreter | None) -> Result:
        name = action.name
        if not self.is_variable(name):
            return Result(False, texts.NOT_VARIABLE.format(name=_shown(name)))
        refusal = self._refusal(where)
        if refusal is not None or interp is None:
            _log.info("Console set %s: refused", name)
            return Result(False, refusal or texts.NO_STORY)
        meter = name in self._specs
        if isinstance(action, SetValue):
            text = action.text
            try:
                if type(text) is not str:
                    raise StartValueError(texts.BAD_VALUE)
                value = parse_literal(text)
            except StartValueError:
                _log.info("Console set %s: refused", name)
                return Result(False, texts.BAD_VALUE)
            if meter and type(value) is not int:
                _log.info("Console set %s: refused", name)
                return Result(False, texts.METER_WHOLE.format(name=_shown(name)))
        else:
            current = interp.points.get(name) if meter else interp.G.get(name)
            if isinstance(action, Switch):
                if type(current) is not bool:
                    return Result(False, texts.NOT_PLAIN)
                value = not current
            else:
                if type(current) is not int:
                    return Result(False, texts.NOT_PLAIN)
                value = current + action.delta
        if not meter:
            try:
                value = freeze(value)
            except Unsaveable:
                pass                          # console_change's save check refuses it

        def apply() -> bool:
            if meter:
                interp.points.set(name, value)
            else:
                interp.G[name] = value
            return True

        reason = self._change(interp, apply)
        if reason:
            _log.info("Console set %s: undone", name)
            return Result(False, texts.CANT_SAVE.format(reason=echo(reason, CODE_MAX)))
        _log.info("Console set %s", name)
        now = interp.points.get(name) if meter else interp.G.get(name)
        return Result(True, texts.SET_DONE.format(name=_shown(name),
                                                  value=value_text(now, ROW_MAX)))

    @staticmethod
    def _change(interp: Interpreter, apply: Callable[[], bool]) -> str | None:
        try:
            return interp.console_change(apply)
        except Exception as error:            # noqa: BLE001 (never stop the game)
            return echo(f"{type(error).__name__}: {error}", CODE_MAX)

    def _jump_to(self, label: object, where: Where) -> Result:
        if (type(label) is not str or len(label) > CONSOLE_LABEL_MAX
                or label not in self.program.labels):
            return Result(False, texts.NO_SCENE.format(label=_shown(label)))
        refusal = self._refusal(where, jump=True)
        if refusal is not None:
            _log.info("Console jump to %s: refused", label)
            return Result(False, refusal)
        new_game = where is Where.NO_STORY
        try:
            reason = self._jump(label, new_game)
        except Exception as error:            # noqa: BLE001 (never stop the game)
            reason = echo(f"{type(error).__name__}: {error}", CODE_MAX)
        if reason:
            _log.info("Console jump to %s: undone", label)
            return Result(False, texts.CANT_SAVE.format(reason=echo(reason, CODE_MAX)))
        _log.info("Console new game at %s" if new_game else "Console jump to %s", label)
        done = texts.JUMP_NEW_GAME if new_game else texts.JUMP_DONE
        return Result(True, done.format(label=_shown(label)))

    def _code(self, line: str, where: Where, interp: Interpreter | None) -> Result:
        line = clean_input(line)
        refusal = self._refusal(where)
        if refusal is not None or interp is None:
            _log.info("Console Code line: refused")
            return self._entry(line, (refusal or texts.NO_STORY,), False)
        try:                                  # run_code makes the one console_change itself
            outcome = self._run_code(interp, line)
        except Exception as error:            # noqa: BLE001 (never stop the game)
            outcome, reason = None, echo(f"{type(error).__name__}: {error}", CODE_MAX)
        else:
            reason = getattr(outcome, "undone", None)
        lines = [echo(str(text), CODE_MAX) for text in outcome.lines] if outcome else []
        ok = reason is None and outcome is not None and bool(outcome.ok)
        if reason:                            # undone ("" is the line's own failure)
            lines.append(texts.CANT_SAVE.format(reason=echo(reason, CODE_MAX)))
        if not lines and ok:
            lines.append(texts.CODE_DONE)
        _log.info("Console Code line: %s", "done" if ok else "undone" if reason else "failed")
        return self._entry(line, tuple(lines), ok)

    def _entry(self, line: str, lines: tuple[str, ...], ok: bool) -> Result:
        self.results.append(CodeEntry(line, lines, ok))
        result = Result(ok, "\n".join(lines))
        self.output[Tab.CODE] = result
        return result

    def _changed(self) -> None:
        self.version += 1

    # -- What the panel shows ---------------------------------------------------------------------------

    @property
    def hint(self) -> str:
        if self.tab is Tab.CODE:
            return texts.CODE_HINT
        if self.tab is Tab.JUMP:
            return texts.JUMP_HINT
        return texts.EDIT_HINT if self.editing is not None else texts.VARIABLES_HINT


__all__ = ["Action", "CODE_RESULTS", "Close", "CodeEntry", "CodeOutcome", "ConsoleModel",
           "Field", "GuardedFn", "HISTORY_MAX", "INPUT_MAX", "JumpFn", "JumpTo", "LIST_ROWS",
           "Nudge", "Result", "Row", "RunCode", "RunCodeFn", "SetValue", "Switch", "TABS",
           "TAB_TEXTS", "Tab", "Where", "clean_input", "literal_text", "where_now"]
