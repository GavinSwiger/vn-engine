"""Studio's visual story editor glue (F46 ``04-technical.md`` §1, §6.7.7, §6.11).

Why this module exists: the Events tab and the Script text must show the same scene and stay
in step. ``StoryEditor`` holds which scene the Events tab shows (``ref``, ``key``), turns the
window's scene index into ``forms.rows`` for it, and maps rows to text lines both ways:

- selecting a row puts the Script peer's insert mark on the row's line (§6.7.7);
- showing Events, or a ``follow``, shows the scene holding the Script cursor and selects the
  row whose ``span`` holds it (the innermost one).

Step 3 adds the actions (04 §6.3): ``act(planner)`` guards the scene (editable, not a
duplicate label, its live chunk, found by its label (07 I-5), still the one drawn, and
parsing), plans, asks when the plan asks, verifies the plan in memory and applies it to the
file's text as one undo step, then follows at once. The Events actions: Insert… (the
picker, then the form, or a text-only doc's example), Edit (Enter, F2, a double-click: the
row's form), Alt+Up/Down, Delete, Ctrl+Z/Ctrl+Y (the file's own undo), and the Shoulds:
dragging a row onto another, Ctrl+C/X/V as script text (PR-F46-23).

``win`` is the ``EditorWindow`` (duck-typed: ``files``, ``scene_indexes``, ``side_text``,
``current``, ``reindex_scenes``, ``follow``, ``check_names``, ``story_ask``, ``jump_to``,
``show_side_tab``, ``apply_plan``, ``root``, ``mod``). Imports: ``tkinter`` (through the
view), ``scenes``, ``forms``, ``scriptedit``, ``formdialogs``, ``assist``, ``syntax``.
"""

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Any

from engine.core.constants import BUILTIN_POSITIONS
from engine.script.menu import Menu
from engine.script.messages import show
from engine.script.statement_docs import StatementDoc
from engine.tools.editor import assist, formdialogs, forms, scenes, scriptedit
from engine.tools.editor.eventsview import EventsView
from engine.tools.editor.forms import ChoiceItem, ChoiceValues, Row
from engine.tools.editor.scenes import Key, SceneIndex, SceneRead, Span
from engine.tools.editor.scriptedit import Ask, LineEdit, Plan, Refuse
from engine.tools.editor.syntax import indent_unit

Planner = Callable[..., scriptedit.Result]
Place = tuple[str, int]


class StoryEditor:
    """The Events tab of one Studio window."""

    def __init__(self, win: Any, view: EventsView) -> None:
        self.win = win
        self.view = view
        view.on_select = self.row_chosen
        view.on_open = self.row_opened
        view.on_action = self.action
        view.on_drop = self.drop
        self.ref: str | None = None
        self.key: Key | None = None
        self.read: SceneRead | None = None
        self.start = 0                          # absolute line of the label line
        self.stale = False
        self.rows: tuple[Row, ...] = ()
        self.drawn: bytes | None = None         # the live chunk's digest the rows show
        self.status = ""                        # the last status line (tests read it)
        self._bind_keys()
        self._cache: dict[tuple[str, Key], tuple[bytes, tuple[Row, ...]]] = {}

    # --- Which scene ------------------------------------------------------------------------

    def want(self) -> frozenset[str]:
        """The label to parse even when its text is unchanged (the scene shown)."""
        return frozenset() if self.key is None else frozenset((self.key[0],))

    def show(self, ref: str, name: str) -> None:
        """Show label ``name``'s first chunk in ``ref``."""
        self.ref, self.key = ref, (name, 0)
        self.refresh()

    def follow_cursor(self) -> None:
        """The scene holding the Script cursor (the last one shown when the cursor is above
        every label), its rows, and the row under the cursor."""
        peer, record = self.win.side_text, self.win.current
        if peer is None or record is None:
            self.refresh()
            return
        line = int(peer.index("insert").split(".")[0])
        index = self.win.scene_indexes.get(record.ref)
        if index is not None:
            key = _chunk_at(index, line)
            if key is not None:
                self.ref, self.key = record.ref, key
        self.refresh()
        if self.ref == record.ref:
            self.view.select(self.row_at(line), notify=False)

    def refresh(self) -> None:
        """Re-read the shown scene (parsing it when needed) and redraw its rows."""
        self.read, self.rows, self.stale, self.drawn = None, (), False, None
        index = None if self.ref is None else self._index()
        if index is None or self.key not in index.starts:
            self.view.set_rows((), title="")
            return
        assert self.ref is not None and self.key is not None
        self.start = index.starts[self.key]
        self.drawn = index.digests.get(self.key)
        read = index.reads.get(self.key)
        cached = self._cache.get((self.ref, self.key))
        if read is None or read.error is not None:
            self.stale = True
            read = index.good.get(self.key)
            rows = cached[1] if cached is not None else ()
        elif cached is not None and cached[0] == read.digest:
            rows = cached[1]
        else:
            rows = tuple(forms.rows(read, self._chunk_lines(index), positions=index.positions))
            self._cache[(self.ref, self.key)] = (read.digest, rows)
        self.read, self.rows = read, rows
        keep = self.view.index if self.view.rows == rows else None
        self.view.set_rows(rows, title=self.key[0], where=f"{show(self.ref)}:{self.start}",
                           stale=self.stale, select=keep)

    def _index(self) -> SceneIndex | None:
        """The shown file's index, with the shown scene parsed."""
        self.win.reindex_scenes()
        return self.win.scene_indexes.get(self.ref)

    def _chunk_lines(self, index: SceneIndex) -> list[str]:
        record = self.win.files.get(self.ref)
        assert record is not None and self.key is not None
        text = record.widget.get("1.0", "end-1c")
        lines = text.split("\n")
        later = [line for line in index.starts.values() if line > self.start]
        last = min(later) - 1 if later else len(lines)
        return lines[self.start - 1:last]

    # --- Rows and lines ---------------------------------------------------------------------

    def line_of(self, index: int) -> int | None:
        """Row ``index``'s absolute line: its head (a ◆ row: its block's last line)."""
        read = self.read
        if read is None or not 0 <= index < len(self.rows) or self.stale:
            return None
        row = self.rows[index]
        span: Span | None = None
        if row.kind == "stmt" and row.stmt is not None:
            span = read.statements[row.stmt].head
        elif row.kind == "header":
            block = read.blocks[row.block]
            span = block.head or (read.statements[row.stmt].head if row.stmt is not None
                                  else None)
        elif row.kind == "end":
            members = read.blocks[row.block].members
            if members:
                last = read.statements[members[-1]].span.last
                return self.start + last - 1
            return self.start + read.last - 1
        if span is None:
            return None
        return self.start + span.first - 1

    def row_at(self, line: int) -> int:
        """The row whose span holds absolute ``line`` (the innermost); the first row when
        none does."""
        read = self.read
        if read is None or not self.rows:
            return 0
        rel = line - self.start + 1
        best, size = 0, None
        for i, row in enumerate(self.rows):
            span = _span_of(read, row)
            if span is None or not span.first <= rel <= span.last:
                continue
            if size is None or span.last - span.first <= size:
                best, size = i, span.last - span.first
        if size is None and rel > read.last:
            ends = [i for i, row in enumerate(self.rows) if row.kind == "end" and row.depth == 0]
            return ends[-1] if ends else 0
        return best

    def row_chosen(self, index: int) -> None:
        """A row picked in the Events list: the Script cursor to its line."""
        line = self.line_of(index)
        peer = self.win.side_text
        if line is None or peer is None:
            return
        peer.mark_set("insert", f"{line}.0")
        peer.see("insert")
        self.win.text_cursor_moved()

    def row_opened(self, index: int) -> None:
        """Enter or a double-click on a row: a form row's form, Insert… on a ◆ row, else
        the Script page at its line."""
        self.edit(index)

    def texts(self) -> list[str]:
        return self.view.texts()

    # --- Status -------------------------------------------------------------------------------

    def say(self, text: str, place: Place | None = None) -> None:
        """The Events status line; ``place`` (ref, line) makes it a link there."""
        self.status = text
        self.view.say(text, link=None if place is None else (lambda: self.open_place(place)))

    def open_place(self, place: Place) -> None:
        """A status link: the Script page at ``place`` when it is the side text's file,
        else the Editor tab."""
        ref, line = place
        record, peer = self.win.files.get(ref), self.win.side_text
        if record is not None and peer is not None and self.win.current is record:
            peer.mark_set("insert", f"{line}.0")
            peer.see("insert")
            self.win.show_side_tab("script")
        else:
            self.win.jump_to(ref, line)

    # --- The action pipeline (04 §6.3) --------------------------------------------------------

    def guard(self) -> tuple[Any, SceneRead, str] | None:
        """Steps 1–2: ``(record, fresh read, text)`` when the shown scene can change now;
        else says why (when the text moved on, after following it) and gives None."""
        if self.ref is None or self.key is None:
            return None
        record = self.win.files.get(self.ref)
        if record is None:
            return None
        if not record.editable:
            self.say(record.error.format() if record.error is not None else "")
            return None
        name = self.key[0]
        doubles = scenes.duplicates(self.win.check_names.get("label", ()),
                                    self.win.scene_indexes)
        if name in doubles:
            here = (self.ref, self.start)
            self.say(scenes.duplicate_text(name, here, doubles[name]), here)
            return None
        text = record.widget.get("1.0", "end-1c")
        if self.drawn is None or _live_digest(text, self.key) != self.drawn:
            self.win.follow()
            self.refresh()
            self.say(scriptedit.STALE)
            return None
        index = self.win.scene_indexes.get(self.ref)
        read = None if index is None else index.reads.get(self.key)
        if read is None:
            self.refresh()
            self.say(scriptedit.STALE)
            return None
        if read.error is not None:
            if read.error[1] == scenes.SCENE_TOO_LONG:
                self.say(scenes.SCENE_TOO_LONG, (self.ref, self.start))
            else:
                line = self.start + read.error[0] - 1
                self.say(scriptedit.FIX_FIRST.format(
                    file=show(self.ref.removeprefix("script/")), line=line), (self.ref, line))
            return None
        return record, read, text

    def act(self, planner: Planner, *, answer: str = "confirm") -> Plan | None:
        """Guard, plan (an ``Ask``'s first button plans again with ``answer=True``),
        verify and apply as one undo step per file (``win.apply_plan``), follow. The plan
        applied, or None when nothing was written (the status line says why)."""
        got = self.guard()
        if got is None:
            return None
        _record, read, text = got
        lines = text.split("\n")
        extra: dict[str, bool] = {}
        while True:
            try:
                result = planner(read, lines, self.start, **extra)
            except Exception:           # a planner bug must never reach the text
                result = Refuse(scriptedit.UNSAFE)
            if not isinstance(result, Ask):
                break
            if extra or self.win.story_ask(result.text, result.buttons, escape=result.escape,
                                           default=result.default) != 0:
                return None
            extra = {answer: True}
        if result is None:
            self.say("")
            return None
        if isinstance(result, Refuse):
            self.say(result.text, result.place)
            return None
        records = {fp.ref: self.win.files.get(fp.ref) for fp in result.files}
        if any(r is None or not r.editable for r in records.values()):
            self.say(scriptedit.UNSAFE)         # only files already open (never opens one)
            return None
        index = self.win.scene_indexes.get(self.ref)
        positions = index.positions if index is not None else ()
        if not self.win.apply_plan(result, lambda texts: scriptedit.verify(
                result, texts, positions=positions)):
            self.say(scriptedit.UNSAFE)
            return None
        self._after(result)
        return result

    def act_on(self, ref: str, name: str, planner: Planner, *, answer: str = "confirm"
               ) -> Plan | None:
        """``act`` on scene ``name`` in ``ref`` (a map action: the arrow's source), then
        the Events tab back on the scene it showed."""
        before = (self.ref, self.key)
        self.ref, self.key = ref, (name, 0)
        self.refresh()
        try:
            return self.act(planner, answer=answer)
        finally:
            if (self.ref, self.key) != before or before[0] is None:
                status = self.status
                self.ref, self.key = before
                self.refresh()
                self.status = status

    def _after(self, plan: Plan) -> None:
        """Step 6: the Script cursor (and selection) to the plan's ``select``, follow now,
        and the row there."""
        mine = next((fp for fp in plan.files if fp.ref == self.ref), None)
        line = None
        if mine is not None and mine.select is not None:
            line, col0, col1 = mine.select
            widget = self._script_widget()
            if widget is not None:
                widget.tag_remove("sel", "1.0", "end")
                widget.mark_set("insert", f"{line}.{col0}")
                if col1 > col0:
                    widget.tag_add("sel", f"{line}.{col0}", f"{line}.{col1}")
                widget.see("insert")
        self.win.follow()
        self.win.map_plan_done(plan)        # one map step (04 §6.9)
        self.refresh()
        if line is not None and self.rows:
            self.view.select(self.row_at(line), notify=False)
        self.say(plan.status or "")

    def _script_widget(self) -> tk.Text | None:
        """The Script page's text when it shows the scene's file, else the file's own."""
        record = self.win.files.get(self.ref) if self.ref is not None else None
        if record is None:
            return None
        peer = self.win.side_text
        return peer if peer is not None and self.win.current is record else record.widget

    def _unit(self) -> str:
        record = self.win.files.get(self.ref) if self.ref is not None else None
        return indent_unit(record.widget.get("1.0", "end-1c")) if record is not None \
            else "    "

    # --- Events actions (§6.7.5–6, PR-F46-19–23) ---------------------------------------------

    def action(self, name: str) -> None:
        """A buttons-row click: insert, edit, up, down or delete on the chosen row."""
        index = self.view.selected()
        if name == "insert":
            self.insert(index)
        elif index is None:
            return
        elif name == "edit":
            self.edit(index)
        elif name in ("up", "down"):
            self.move(index, -1 if name == "up" else 1)
        elif name == "delete":
            self.delete(index)

    def _row(self, index: int | None) -> Row | None:
        if index is None or not 0 <= index < len(self.rows):
            return None
        return self.rows[index]

    def names(self) -> dict[str, list[str]]:
        """Name kind → the names a picker offers: the check's index, plus the indexed
        scenes for ``label`` and the built-in positions (§6.7.8)."""
        out: dict[str, list[str]] = {}
        for kind, entries in self.win.check_names.items():
            found = {name for entry in entries if (name := _name_of(entry)) is not None}
            out[kind] = sorted(found)
        labels = set(out.get("label", ()))
        for index in self.win.scene_indexes.values():
            labels.update(name for name, _ in index.starts)
        out["label"] = sorted(labels)
        out["position"] = sorted(set(out.get("position", ())) | set(BUILTIN_POSITIONS))
        return out

    def form_assets(self) -> Any:
        """The forms' thumbnails, ▶/■ and colour dots (F47 W5), read again for this form."""
        from engine.tools.editor.formassets import WindowAssets
        assets = getattr(self, "_form_assets", None)
        if assets is None:
            assets = self._form_assets = WindowAssets(self.win)
        else:
            assets.refresh()
        return assets

    def insert(self, index: int | None = None, doc: StatementDoc | None = None
               ) -> Plan | None:
        """Insert… (the button, Insert, Enter on a ◆ row): the picker, then the doc's form
        (Cancel inserts nothing), or a text-only doc's example with its first field
        selected in the Script page. It goes above the row (a ◆ row: its block's end).
        ``doc`` skips the picker (F47's Guide: Show me for a choice or an ending)."""
        if self.guard() is None or not self.rows:
            return None
        if index is None:
            index = len(self.rows) - 1
        row = self._row(index)
        if row is None or row.kind == "more":
            return None
        self.say("")
        if doc is None:
            doc = formdialogs.pick_insert(self.win.root, assist.insert_menu())
        if doc is None:
            return None
        unit = self._unit()
        if isinstance(doc, forms.CommandForm):          # Stop effects, Stop sound: no doc
            form, doc = doc, None
        else:
            form = forms.form_for_doc(doc)
        if form is None:
            code, field = assist.insert_text(doc, "", unit)
            plan = self.act(lambda read, lines, start: scriptedit.plan_insert(
                read, lines, start, row, code.split("\n")))
            if plan is not None:
                self._select_field(plan, code, field)
            return plan
        if form is forms.CHOICE:
            values: Any = formdialogs.edit_choice(
                self.win.root, ChoiceValues(choices=(ChoiceItem(""),)), names=self.names(),
                assets=self.form_assets())
        else:
            values = formdialogs.edit_form(self.win.root, form,
                                           formdialogs.new_values(form, doc),
                                           names=self.names(), assets=self.form_assets())
        if values is None:
            return None
        new = forms.insert_lines(form, values, "", unit)
        return self.act(lambda read, lines, start: scriptedit.plan_insert(
            read, lines, start, row, new))

    def _select_field(self, plan: Plan, code: str, field: tuple[int, int] | None) -> None:
        """After a text-only insert: the Script page with ``fields[0]`` selected."""
        mine = next((fp for fp in plan.files if fp.ref == self.ref), None)
        if mine is None or mine.select is None:
            return
        first, indent, _end = mine.select
        self.win.show_side_tab("script")
        widget = self._script_widget()
        if widget is None or field is None:
            return
        at, end = field
        line = first + code.count("\n", 0, at)
        column = indent + at - (code.rfind("\n", 0, at) + 1)
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", f"{line}.{column}", f"{line}.{column + end - at}")
        widget.mark_set("insert", f"{line}.{column + end - at}")
        widget.see("insert")

    def edit(self, index: int | None) -> Plan | None:
        """Edit (Enter, F2, a double-click): a form row's form; Insert… on a ◆ row; the
        Script page at a Script row's line."""
        row = self._row(index)
        if row is None or index is None:
            return None
        if row.kind == "end":
            return self.insert(index)
        if row.form is None or row.kind == "more":
            if self.line_of(index) is not None:
                self.row_chosen(index)
            self.win.show_side_tab("script")
            return None
        got = self.guard()
        if got is None:
            return None
        self.say("")
        _record, read, _text = got
        unit = self._unit()
        if row.form == forms.CHOICE_FORM:
            assert row.stmt is not None
            now = forms.read_choice(read, row.stmt)
            if now is None:
                return None
            values: Any = formdialogs.edit_choice(self.win.root, now, names=self.names(),
                                                  assets=self.form_assets())
            form = forms.CHOICE
        else:
            form = forms.form_by_key(row.form)
            if form is None:
                return None
            values = formdialogs.edit_form(self.win.root, form, dict(row.values or {}),
                                           names=self.names(), assets=self.form_assets())
        if values is None:
            return None
        return self.act(lambda read_, lines, start: scriptedit.plan_form(
            read_, lines, start, row, values, form=form, unit=unit))

    def move(self, index: int, step: int) -> Plan | None:
        """Alt+Up/Down: the row with its nested lines past its sibling."""
        row = self._row(index)
        if row is None:
            return None
        return self.act(lambda read, lines, start: scriptedit.plan_move(
            read, lines, start, row, step))

    def delete(self, index: int) -> Plan | None:
        """Delete: the row and its nested lines (asking first when it has some)."""
        row = self._row(index)
        if row is None:
            return None
        return self.act(lambda read, lines, start, **kw: scriptedit.plan_delete_row(
            read, lines, start, row, **kw))

    def undo(self, redo: bool = False) -> None:
        """Ctrl+Z / Ctrl+Y in Events: the scene file's own undo (the Script text's)."""
        record = self.win.files.get(self.ref) if self.ref is not None else None
        if record is None or not record.editable:
            return
        keep = self.view.selected()
        try:
            if redo:
                record.widget.edit_redo()
            else:
                record.widget.edit_undo()
        except tk.TclError:
            return                              # nothing to undo
        self.win.follow()
        self.refresh()
        if keep is not None and self.rows:
            self.view.select(min(keep, len(self.rows) - 1), notify=False)

    # --- Drag rows; copy and paste (PR-F46-23, Should) ----------------------------------------

    def _unit_of(self, read: SceneRead, row: Row) -> tuple[Span, str] | None:
        """The row's unit (chunk-relative) and indent: a statement's, or a choice's."""
        if row.kind == "stmt" and row.stmt is not None:
            stmt = read.statements[row.stmt]
            return stmt.unit, stmt.indent
        if row.kind == "header" and row.stmt is not None \
                and isinstance(read.statements[row.stmt].node, Menu):
            block = read.blocks[row.block]
            if block.unit is None or block.head is None:
                return None
            return block.unit, read.statements[row.stmt].indent + self._unit()
        return None

    def copy(self, index: int | None = None) -> bool:
        """Ctrl+C: the row's lines (its unit) on the clipboard as script text, without
        its block's indent."""
        index = self.view.selected() if index is None else index
        row = self._row(index)
        if row is None or self.read is None or self.stale or self.ref is None:
            return False
        found = self._unit_of(self.read, row)
        record = self.win.files.get(self.ref)
        if found is None or record is None:
            return False
        unit, indent = found
        first = self.start + unit.first - 1
        last = self.start + unit.last - 1
        lines = record.widget.get(f"{first}.0", f"{last}.end").split("\n")
        text = "\n".join(line[len(indent):] if line.startswith(indent) else line.lstrip()
                         for line in lines)
        root = self.win.root
        root.clipboard_clear()
        root.clipboard_append(text)
        return True

    def cut(self, index: int | None = None) -> Plan | None:
        """Ctrl+X: copy, then delete (one undo step)."""
        index = self.view.selected() if index is None else index
        if index is None or not self.copy(index):
            return None
        return self.delete(index)

    def paste(self, index: int | None = None) -> Plan | None:
        """Ctrl+V: the clipboard's lines above the row, at its block's indent."""
        index = self.view.selected() if index is None else index
        row = self._row(index)
        if row is None:
            return None
        try:
            text = self.win.root.clipboard_get()
        except tk.TclError:
            return None
        pasted = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while pasted and not pasted[-1].strip():
            pasted.pop()
        if not pasted:
            return None
        return self.act(lambda read, lines, start: scriptedit.plan_insert(
            read, lines, start, row, pasted))

    def drop(self, source: int, target: int) -> Plan | None:
        """A row dragged onto another of its block (a choice onto a choice of its menu, or
        onto the block's ◆): its unit moves above the target when dragged up, below it when
        dragged down. Anything else writes nothing."""
        src, dst = self._row(source), self._row(target)
        if src is None or dst is None:
            return None

        def planner(read: SceneRead, lines: Sequence[str], start: int) -> scriptedit.Result:
            moving = self._unit_of(read, src)
            if moving is None:
                return None
            unit = moving[0]
            if dst.kind == "end":
                members = read.blocks[dst.block].members
                if src.kind != "stmt" or src.block != dst.block or not members:
                    return None
                at = read.statements[members[-1]].span.last + 1
            else:
                there = self._unit_of(read, dst)
                same = (src.kind == dst.kind == "stmt" and src.block == dst.block) or (
                    src.kind == dst.kind == "header" and src.stmt == dst.stmt)
                if there is None or not same:
                    return None
                at = there[0].first if there[0].first < unit.first else there[0].last + 1
            if unit.first <= at <= unit.last + 1:
                return None
            body = tuple(lines[start + r - 2] for r in range(unit.first, unit.last + 1))
            return scriptedit.plan_patch(read, lines, start, "Move", (
                (at, at - 1, body), (unit.first, unit.last, ())))
        return self.act(planner)

    # --- Keys (design §6.3; on the Events list only, each returning "break") ------------------

    def _bind_keys(self) -> None:
        tree, mod = self.view.tree, getattr(self.win, "mod", "Control")

        def bind(sequence: str, run: Callable[[], object]) -> None:
            tree.bind(sequence, lambda _e: (run(), "break")[1])

        def chosen(run: Callable[[int], object]) -> Callable[[], object]:
            return lambda: None if self.view.selected() is None else run(
                self.view.selected())  # type: ignore[arg-type]

        bind("<Insert>", lambda: self.insert(self.view.selected()))
        bind("<F2>", chosen(self.edit))
        bind("<Delete>", chosen(self.delete))
        if mod == "Command":                    # 07 I-7: a Mac's Delete key is BackSpace
            bind("<BackSpace>", chosen(self.delete))
        bind("<Alt-Up>", chosen(lambda i: self.move(i, -1)))
        bind("<Alt-Down>", chosen(lambda i: self.move(i, 1)))
        for letter in "zZ":
            tree.bind(f"<{mod}-{letter}>", lambda e: (
                self.undo(redo=bool(int(e.state) & 0x1)), "break")[1])
        for letter in "yY":
            bind(f"<{mod}-{letter}>", lambda: self.undo(redo=True))
        for letter, run in (("c", self.copy), ("x", self.cut), ("v", self.paste)):
            bind(f"<{mod}-{letter}>", run)
            bind(f"<{mod}-{letter.upper()}>", run)


def apply_edits(widget: tk.Text, edits: Sequence[LineEdit]) -> None:
    """``edits`` on a Tk text, bottom-up (04 §6.3.5). Tk's last line has no break, so
    replacing it adds none and appending after it inserts a break first."""
    for edit in sorted(edits, key=lambda e: (e.first, e.last), reverse=True):
        total = int(widget.index("end-1c").split(".")[0])
        new = "\n".join(edit.lines)
        if edit.last >= edit.first:
            if edit.lines:
                widget.delete(f"{edit.first}.0", f"{edit.last}.end")
                widget.insert(f"{edit.first}.0", new)
            elif edit.last < total:
                widget.delete(f"{edit.first}.0", f"{edit.last + 1}.0")
            elif edit.first > 1:
                widget.delete(f"{edit.first - 1}.end", f"{edit.last}.end")
            else:
                widget.delete("1.0", "end-1c")
        elif edit.lines:
            if edit.first <= total:
                widget.insert(f"{edit.first}.0", new + "\n")
            else:
                widget.insert("end-1c", "\n" + new)


def _live_digest(text: str, key: Key) -> bytes | None:
    """The digest of chunk ``key`` in ``text``, found by its label (07 I-5) as ``scenes``
    digests it; None when the label is gone."""
    found = [(start, end) for name, _first, _last, start, end in scenes._chunk_spans(text)
             if name == key[0]]
    if key[1] >= len(found):
        return None
    start, end = found[key[1]]
    return scenes.digest(text[start:end])


def _name_of(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    name = getattr(entry, "name", None)
    if name is None and isinstance(entry, (tuple, list)) and entry:
        name = entry[0]
    return name if isinstance(name, str) else None


def _chunk_at(index: SceneIndex, line: int) -> Key | None:
    """The chunk holding absolute ``line``: the last label line at or above it."""
    found: Key | None = None
    for key, start in index.starts.items():
        if start <= line and (found is None or start >= index.starts[found]):
            found = key
    return found


def _span_of(read: SceneRead, row: Row) -> Span | None:
    if row.kind == "stmt" and row.stmt is not None:
        return read.statements[row.stmt].span
    if row.kind == "header" and 0 <= row.block < len(read.blocks):
        block = read.blocks[row.block]
        return block.span or block.head
    return None


__all__ = ["StoryEditor", "apply_edits"]
