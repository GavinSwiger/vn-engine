"""The Database's **Achievements** category (F37 ``SPEC.md`` §4, step 3; AC-F37-11, 12).

Why this module exists: achievements reward players across playthroughs, with a notice and a
list under the title screen's Extras. A non-programmer never types ``lock achievement``: in
Database ▸ **Achievements** they click **+ New achievement**, type the name players see, and
Studio writes one line into ``database.vns`` (the script name made from it, unique). The form
changes the name shown, the description, the icon (a thumbnail picker), **Hidden** and how
players earn it: **By an Unlock achievement line in the story** (Events ▸ Insert… ▸
Unlock achievement) or **Automatically, when:** a condition comes true, built with the If form's
condition builder (``formtools.ConditionBuilder`` over ``conditions.py``; "Written as script"
when the builder can't show it). **▲ Move up** / **▼ Move down** reorder the Achievements page
(``declplan.plan_move``); **▶ Preview achievements** runs the game's dev ``run --extras
achievements`` through the Play bar, every achievement unlocked in memory.

``AchievementsCategory`` is a mixin of ``database.DatabasePane`` (as ``dbextras``'s and
``dbreplays``'s): the pane's tree holds the numbered rows in the page's order; a small bar
under it holds the move and preview buttons. Every write is a ``declplan`` plan applied
through the pane's ``_write``; each field applies on Enter or focus-out (the builder: on a
pick, on Enter or focus-out of a typed value, and on removing a check), one undo step each.
Delete is refused while an ``unlock achievement`` line names it. The script name can't be
changed here: players' unlocked achievements are kept under it (as tracks and replays).

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import importlib.util
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from tkinter import ttk
from typing import Any

from engine.script.achievements import ACHIEVEMENTS_MAX, WHEN_MAX
from engine.tools.editor import conditions as C
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, formtools
from engine.tools.editor.dbmore import IN_SCRIPT, Row
from engine.tools.editor.dbreplays import _Picker
from engine.tools.editor.dialogs import ask, ask_text, show_error
from engine.tools.editor.fieldwidgets import FormGrid, TextField, ToggleField, fit_wrap
from engine.tools.editor.scriptedit import STALE
from engine.tools.editor.theme import THEME

# --- Texts (SPEC §4; the rest in the same voice) -----------------------------------------------

ABOUT_ACHIEVEMENTS = ("Achievements reward players for what they do, with a notice and a list "
                      "under the title screen's Extras. Click + New achievement to make one.")
EMPTY_HINT = "Reward players for what they do."
NEW_ACHIEVEMENT = "+ New achievement"
NEW_ASK = "Name shown:"
NEW_OK = "Add"
MOVE_UP = "▲ Move up"
MOVE_DOWN = "▼ Move down"
ACROSS_FILES = "This achievement is declared in another file; move it there."
PREVIEW = "▶ Preview achievements"
PREVIEW_TIP = "Opens Extras ▸ Achievements with every achievement unlocked. Nothing is saved."
NOT_YET = ("This engine can't show achievements yet; it comes with the Achievements page in "
           "Extras.")
LABEL_TITLE = "Name shown"
LABEL_DESCRIPTION = "Description"
LABEL_ICON = "Icon"
LABEL_HIDDEN = "Hidden"
LABEL_UNLOCKED = "Unlocked"
LABEL_SCRIPT_NAME = "Script name"
NO_ICON = "(no icon)"
ICON_HINT = "A square picture, 64 × 64 or larger, looks best."
HIDDEN_TEXT = "Players see “Hidden achievement” until they unlock it."
BY_LINE = "By an Unlock achievement line in the story"
AUTOMATIC = "Automatically, when:"
WHEN_HINT = "Checked at every line and choice, and when the story ends."
NEEDS_CHECK = "Add a check, or pick By an Unlock achievement line."
BAD_SCRIPT = "This condition can't be read as script. Fix it, or use the builder instead."
WHEN_FULL = ("A story can have up to {n} automatic achievements. Give this one with an Unlock "
             "achievement line instead.")
NO_LINE = ("No line gives this achievement yet. In Events, add Unlock achievement where the "
           "player earns it.")
NAME_KEPT = "Players' unlocked achievements are kept under this name, so it can't change."
HOOK_HINT = ("Store achievements (such as Steam) need a platform hook written in Python: see "
             "docs/minigames.md, \"Achievement hook\". Achievements always work without one.")
USED_IN = "Used in {lines}"
NOT_USED = "Not used yet"
USES_HEAD = "{name} is given by {lines}:"
DELETE = "Delete"
DELETE_ASK = ("Delete the achievement “{title}”? Its line is removed from {ref}; Edit ▸ Undo "
              "there brings it back.")
DELETE_BUTTONS = ("Delete", "Cancel")
USED_REFUSED = ("“{title}” is given by {lines} (Unlock achievement), so it can't be deleted "
                "yet.")
REFUSED_BUTTONS = (db.SHOW_USES, "OK")
TOO_MANY = "A story holds up to {n} achievements."
DETAIL_HIDDEN = "hidden"
DETAIL_AUTOMATIC = "automatic"
DETAIL_BOTH = "hidden · auto"           # both, in the list's narrow detail column

ACHIEVEMENT_PREFIX = "a:"
EXTRAS_PAGE = "achievements"
MOVE_STYLE = "Move.Secondary.TButton"
LINE, AUTO = "line", "auto"
# The builder's drop-downs in a narrow form column (two lines a check): name, is, value.
NAME_CHARS, OP_CHARS, VALUE_CHARS, YES_NO_CHARS = 12, 12, 8, 6
WRAP_PX = 420
CARD_INDENT = 12


def preview_ready() -> bool:
    """True when this engine has the Achievements page (F37-S2's
    ``engine/app/achievements.py``), so ``run --extras achievements`` opens it; reads no
    code."""
    try:
        return importlib.util.find_spec("engine.app.achievements") is not None
    except (ImportError, ValueError):
        return False


def lines_word(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def detail_of(values: Mapping[str, object] | None) -> str:
    """The list's detail column: "hidden", "automatic", both or nothing."""
    if not values:
        return ""
    hidden, auto = bool(values.get("hidden")), values.get("when") is not None
    if hidden and auto:
        return DETAIL_BOTH
    return DETAIL_HIDDEN if hidden else DETAIL_AUTOMATIC if auto else ""


class _WhenBuilder(formtools.ConditionBuilder):
    """The If form's condition builder in a Database form: ``commit()`` is called on a pick,
    on Enter or focus-out of a typed value, and after a check is removed (never per
    keystroke, so one change is one undo step)."""

    def __init__(self, parent: tk.Misc, var: tk.StringVar, names: Mapping[str, Sequence[str]],
                 commit: Callable[[], object]) -> None:
        self._commit = commit
        self._bound: set[str] = set()
        super().__init__(parent, var, names, required=False)
        self.problem_label.pack_forget()            # never says anything here (not required)
        self._bind_all()

    def _blank(self) -> C.Row:
        """A new check: the story's first ending was seen (else the If form's blank row)."""
        endings = self.names_of(C.ENDING)
        if endings:
            return C.Row(C.ENDING, endings[0], C.HAS, "")
        return super()._blank()

    def grid_rows(self) -> None:
        """Each check on two lines (what and which; then is and the value), so the builder
        fits the Database's narrow form column."""
        gap = round(6 * self.scale)
        if len(self.checks) > 1:
            self.join_box.pack(side="left")
            self.join_label.pack(side="left", padx=(gap, 0))
            self._head.pack(anchor="w", fill="x", pady=(0, gap), before=self.rows_frame)
        else:
            self._head.pack_forget()
        for n, check in enumerate(self.checks):
            kind = check.kind_key
            row = 3 * n
            top = (2 * gap if n else 0, 0)
            check.name_box.configure(width=NAME_CHARS)
            check.op_box.configure(width=OP_CHARS)
            check.value_entry.configure(width=VALUE_CHARS)
            check.value_box.configure(width=YES_NO_CHARS)
            check.kind_box.grid(row=row, column=0, sticky="w", pady=top)
            if kind == C.PLAYTHROUGH:
                check.name_box.grid_remove()
            else:
                check.name_box.grid(row=row, column=1, columnspan=2, sticky="w",
                                    padx=(gap, 0), pady=top)
            check.remove.grid(row=row + 1, column=1 if kind in formtools.HAS_WORDS else 2,
                              sticky="w", padx=(gap, 0), pady=(gap // 2, 0))
            check.op_box.grid(row=row + 1, column=0, sticky="w", pady=(gap // 2, 0))
            for value in (check.value_box, check.value_entry):
                wanted = check.value_box if kind == C.VARIABLE else check.value_entry
                if kind not in formtools.HAS_WORDS and value is wanted:
                    value.grid(row=row + 1, column=1, sticky="w", padx=(gap, 0),
                               pady=(gap // 2, 0))
                else:
                    value.grid_remove()
            check.hint.grid(row=row + 2, column=0, columnspan=3, sticky="w")
        if len(self.checks) >= C.MAX_ROWS:
            self.add_button.state(["disabled"])
        else:
            self.add_button.state(["!disabled"])
        self._bind_all()

    def _bind_all(self) -> None:
        if not hasattr(self, "_bound"):
            return
        widgets: list[tk.Widget] = [self.join_box, self.script_entry]
        for check in self.checks:
            widgets += [check.kind_box, check.name_box, check.op_box, check.value_box,
                        check.value_entry]
        for widget in widgets:
            if str(widget) in self._bound:
                continue
            self._bound.add(str(widget))
            for sequence in ("<<ComboboxSelected>>", "<FocusOut>", "<Return>", "<KP_Enter>"):
                widget.bind(sequence, lambda _e: self._fire(), add="+")

    def _fire(self) -> None:
        try:
            if self.frame.winfo_exists():
                self._commit()
        except tk.TclError:                         # the write rebuilt the form
            pass

    def remove(self, check: Any) -> None:
        super().remove(check)
        self._fire()


# --- The mixin --------------------------------------------------------------------------------

class AchievementsCategory:
    """Database ▸ Achievements (a mixin of ``database.DatabasePane``: it uses the pane's rows,
    forms and writers)."""

    win: Any
    root: Any
    scale: float
    texts: dict[str, str]
    decls: tuple[dec.Decl, ...]
    names: Mapping
    marks: tuple[dec.Decl, ...]
    rows: dict[str, list[Row]]
    form: Any
    category: str
    chosen: dict[str, str | None]
    list_body: Any
    list_tree: Any
    new_button: Any
    empty: Any
    _px: Callable[[float], int]
    _new_body: Callable[[tuple], tuple[ttk.Frame, Any]]
    _title: Callable[..., ttk.Label]
    _fresh: Callable[[db.Entry], dec.Decl | None]
    _edit: Callable[[db.Entry, Mapping[str, object]], bool]
    _write: Callable[..., bool]
    _read_texts: Callable[[], dict[str, str]]
    _read_only: Callable[[Row, tuple], bool]
    picture_names: Callable[[], list[str]]
    picture_thumb: Callable[[str], object | None]
    refresh: Callable[..., None]
    select_category: Callable[[str], None]
    selected_row: Callable[[], Row | None]
    search_text: Callable[[], str]
    achievement_bar: Any = None
    achievement_moves: tuple[Any, Any] | None = None
    achievement_note: Any = None
    achievement_preview: Any = None
    achievement_preview_tip: Any = None

    # --- Rows -------------------------------------------------------------------------------

    def _achievement_rows(self) -> list[Row]:
        return [Row(ACHIEVEMENT_PREFIX + e.name, f"{n}.  {e.shown}",
                    detail_of(e.decl.values if e.decl is not None else None), e)
                for n, e in enumerate(db.achievement_entries(self.decls, self.texts), start=1)]

    def achievement_entries(self) -> list[db.Entry]:
        """The Achievements category's entries in the page's order (as listed)."""
        return [r.entry for r in self.rows.get(db.CATEGORY_ACHIEVEMENT, ())
                if r.entry is not None]

    def _achievement_places(self, name: str) -> list[tuple[str, int]]:
        """The ``unlock achievement`` lines naming ``name``."""
        return list(dict.fromkeys((ref, line) for found, ref, line in
                                  dec.achievement_uses(self.texts) if found == name))

    def condition_names(self) -> dict[str, list[str]]:
        """What the condition builder's pickers offer: name kind → names (the declarations,
        the endings of the story and the last check's)."""
        out: dict[str, list[str]] = {kind: [] for kind in formtools.NAME_KINDS.values()}
        kinds = {dec.VARIABLE: "variable", dec.PERSISTENT: "variable", dec.METER: "meter",
                 dec.TIP: "tip", dec.ITEM: "item", dec.ROUTE: "route"}
        for decl in self.decls:
            kind = kinds.get(decl.kind)
            if kind is not None:
                out[kind].append(f"persistent.{decl.name}" if decl.kind == dec.PERSISTENT
                                 else decl.name)
        out["variable"] += db.variable_names(self.decls, self.names)
        out["ending"] += db.ending_names(dec.marks(self.texts), self.names)
        return {kind: list(dict.fromkeys(names)) for kind, names in out.items()}

    # --- The list column --------------------------------------------------------------------

    def _build_achievement_bar(self) -> None:
        px = self._px
        bar = self.achievement_bar = ttk.Frame(self.list_body)
        moves = ttk.Frame(bar)
        moves.pack(fill="x")
        moves.columnconfigure((0, 1), weight=1, uniform="move")
        ttk.Style(self.root).configure(MOVE_STYLE, padding=(px(4), px(4)))
        up = ttk.Button(moves, text=MOVE_UP, style=MOVE_STYLE, width=1,
                        command=lambda: self.move_achievement(-1))
        up.grid(row=0, column=0, sticky="ew")
        down = ttk.Button(moves, text=MOVE_DOWN, style=MOVE_STYLE, width=1,
                          command=lambda: self.move_achievement(1))
        down.grid(row=0, column=1, sticky="ew", padx=(px(6), 0))
        self.achievement_moves = (up, down)
        self.achievement_note = ttk.Label(bar, text="", style="Hint.TLabel", justify="left",
                                          wraplength=px(200))
        ready = preview_ready()
        self.achievement_preview = ttk.Button(bar, text=PREVIEW,
                                              command=self.preview_achievements,
                                              state="normal" if ready else "disabled")
        self.achievement_preview.pack(anchor="w", pady=(px(8), 0))
        from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
        self.achievement_preview_tip = Tooltip(
            self.achievement_preview, PREVIEW_TIP if ready else f"{PREVIEW_TIP} {NOT_YET}")
        for key, step in (("<Alt-Up>", -1), ("<Alt-Down>", 1)):
            self.list_tree.bind(key, lambda _e, s=step: (self.move_achievement(s), "break")[1]
                                if self.category == db.CATEGORY_ACHIEVEMENT else None,
                                add="+")

    def _achievement_after_fill(self, has_entries: bool) -> None:
        """After the list is filled: the bar under it, the + button's and empty state's
        words."""
        on = self.category == db.CATEGORY_ACHIEVEMENT
        if on and self.achievement_bar is None:
            self._build_achievement_bar()
        bar = self.achievement_bar
        if bar is not None:
            if on and has_entries and not bar.winfo_ismapped():
                bar.pack(side="bottom", fill="x", padx=self._px(8),
                         pady=(self._px(6), self._px(8)), before=self.list_tree)
            elif not (on and has_entries) and bar.winfo_ismapped():
                bar.pack_forget()
        if not on:
            return
        self.new_button.configure(text=NEW_ACHIEVEMENT)
        if not has_entries:
            self.empty.hint.configure(text=EMPTY_HINT)
            if self.empty.button is not None:
                self.empty.button.configure(text=NEW_ACHIEVEMENT)
        self._sync_achievement_moves()

    def _sync_achievement_moves(self) -> None:
        if self.achievement_moves is None:
            return
        up, down = self.achievement_moves
        row = self.selected_row() if self.category == db.CATEGORY_ACHIEVEMENT else None
        entries = self.achievement_entries()
        note = ""
        states = ["disabled", "disabled"]
        if row is not None and row.entry is not None and not self.search_text().strip():
            names = [e.name for e in entries]
            at = names.index(row.entry.name) if row.entry.name in names else -1
            for side, step in ((0, -1), (1, 1)):
                other = at + step
                if at < 0 or not 0 <= other < len(entries):
                    continue
                if entries[other].place is not None and row.entry.place is not None \
                        and entries[other].place[0] != row.entry.place[0]:
                    note = ACROSS_FILES
                    continue
                if row.entry.editable and entries[other].editable:
                    states[side] = "normal"
        up.configure(state=states[0])
        down.configure(state=states[1])
        ready = preview_ready()
        self.achievement_preview.configure(state="normal" if ready else "disabled")
        self.achievement_preview_tip.text = PREVIEW_TIP if ready else \
            f"{PREVIEW_TIP} {NOT_YET}"
        self.achievement_note.configure(text=note)
        if note and not self.achievement_note.winfo_ismapped():
            self.achievement_note.pack(anchor="w", pady=(self._px(4), 0),
                                       before=self.achievement_preview)
        elif not note and self.achievement_note.winfo_ismapped():
            self.achievement_note.pack_forget()

    # --- Writes -----------------------------------------------------------------------------

    def new_achievement(self) -> bool:
        """+ New achievement: asks the name shown; the achievement joins the end of the page
        with a script name made from it."""
        self.texts = self._read_texts()
        decls = dec.scan(self.texts)
        if len({d.name for d in decls if d.kind == dec.ACHIEVEMENT}) >= ACHIEVEMENTS_MAX:
            show_error(self.root, TOO_MANY.format(n=ACHIEVEMENTS_MAX))
            return False
        taken = dec.taken_names(decls, dec.ACHIEVEMENT)
        answer = ask_text(self.root, NEW_ASK, "", ok=NEW_OK,
                          hint=lambda shown: IN_SCRIPT.format(
                              line="unlock achievement "
                                   f"{dec.script_name(shown, taken, dec.ACHIEVEMENT)}")
                          if shown.strip() else None)
        if answer is None or not answer[0].strip():
            return False
        return self.add_achievement(answer[0].strip())

    def add_achievement(self, title: str) -> bool:
        """Add an achievement shown as ``title`` at the end (one undo step) and show it."""
        self.texts = self._read_texts()
        title = title.strip()[:dec.ACHIEVEMENT_TITLE_MAX].strip()
        name = dec.script_name(title, dec.taken_names(dec.scan(self.texts), dec.ACHIEVEMENT),
                               dec.ACHIEVEMENT)
        values = {"title": title, "description": "", "image": None, "hidden": False,
                  "when": None}
        if self.category != db.CATEGORY_ACHIEVEMENT:
            self.select_category(db.CATEGORY_ACHIEVEMENT)
        return self._write(declplan.plan_new(dec.ACHIEVEMENT, name, values, self.texts),
                           select=ACHIEVEMENT_PREFIX + name)

    def set_achievement_when(self, entry: db.Entry, when: str | None) -> bool:
        """How players earn it: None (by an Unlock achievement line) or a condition."""
        if when is not None:
            when = when.strip()
            if not dec.condition_ok(when):
                return False
            decl = self._fresh(entry)
            if decl is None or decl.values is None:
                show_error(self.root, STALE)
                self.refresh()
                return False
            if decl.values.get("when") == when:
                return True
            others = {d.name for d in dec.scan(self.texts) if d.kind == dec.ACHIEVEMENT
                      and d.values is not None and d.values.get("when") is not None}
            if entry.name not in others and len(others) >= WHEN_MAX:
                show_error(self.root, WHEN_FULL.format(n=WHEN_MAX))
                return False
        return self._edit(entry, {"when": when})

    def delete_achievement(self, entry: db.Entry | None = None, *,
                           confirm: bool = True) -> bool:
        """Delete (asks): refused while an Unlock achievement line names it."""
        if entry is None:
            row = self.selected_row()
            entry = row.entry if row is not None else None
            if entry is None or entry.kind != dec.ACHIEVEMENT:
                return False
        self.texts = self._read_texts()
        places = self._achievement_places(entry.name)
        if places:
            text = USED_REFUSED.format(title=entry.shown, lines=lines_word(len(places)))
            if ask(self.root, text, REFUSED_BUTTONS, escape=1, default=1) == 0:
                self.show_achievement_uses(entry.shown, places)
            return False
        decl = self._fresh(entry)
        if decl is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        if confirm and ask(self.root, DELETE_ASK.format(title=entry.shown, ref=decl.ref),
                           DELETE_BUTTONS, escape=1, default=1) != 0:
            return False
        if self.category == db.CATEGORY_ACHIEVEMENT:
            self.chosen[db.CATEGORY_ACHIEVEMENT] = None
        return self._write(declplan.plan_delete(decl, self.texts))

    def move_achievement(self, step: int) -> bool:
        """▲ Move up (-1) / ▼ Move down (+1): swap the selected achievement's line with its
        neighbour's (``declplan.plan_move``; refused across files)."""
        row = self.selected_row()
        if row is None or row.entry is None or row.entry.kind != dec.ACHIEVEMENT \
                or self.search_text().strip():
            return False
        entries = self.achievement_entries()
        names = [e.name for e in entries]
        at = names.index(row.entry.name)
        if not 0 <= at + step < len(entries):
            return False
        decl, other = self._fresh(row.entry), self._fresh(entries[at + step])
        if decl is None or other is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        return self._write(declplan.plan_move(decl, other, self.texts, across=ACROSS_FILES),
                           select=row.iid)

    def preview_achievements(self) -> None:
        """▶ Preview achievements: the game opens on Extras ▸ Achievements with every
        achievement unlocked in memory (dev ``run --extras achievements``)."""
        play = getattr(self.win, "play_extras", None)
        if callable(play) and preview_ready():
            play(EXTRAS_PAGE)

    def show_achievement_uses(self, title: str, places: Sequence[tuple[str, int]]) -> None:
        """Show uses: the Unlock achievement lines, in the Problems panel."""
        from engine.tools.editor.database import UseItem
        from engine.tools.editor.preview import Report
        items = []
        for ref, line in places:
            lines = self.texts.get(ref, "").split("\n")
            text = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            items.append(UseItem(f"{ref}:{line}: {text}" if text else f"{ref}:{line}", ref,
                                 line))
        head = USES_HEAD.format(name=title, lines=lines_word(len(places)))
        self.win.show_report(Report("editor", head, tuple(items)))   # type: ignore[arg-type]

    # --- The form ---------------------------------------------------------------------------

    def _achievement_thumb_ready(self, _ref: str) -> None:
        """A thumbnail arrived: the Icon field shows it."""
        field = self.form.fields.get("icon") if self.form is not None and \
            self.category == db.CATEGORY_ACHIEVEMENT else None
        if isinstance(field, _Picker):
            field._show()

    def _achievement_key(self, entry: db.Entry, shape: tuple) -> tuple:
        """What rebuilds the form: not the texts and the condition, which the fields show in
        place (``update``), but whether it is automatic."""
        values = dict(entry.decl.values or {}) if entry.decl is not None else {}
        return shape + (values.get("image"), values.get("when") is not None,
                        tuple(self._achievement_places(entry.name)),
                        tuple(self.picture_names()),
                        tuple(sorted((k, tuple(v)) for k, v in self.condition_names().items())))

    def _achievement_form(self, row: Row, key: tuple) -> None:
        if self._read_only(row, key):
            return
        entry = row.entry
        assert entry is not None and entry.decl is not None and entry.decl.values is not None
        values = entry.decl.values
        px = self._px
        body, form = self._new_body(key)
        title = self._title(body, entry.shown)
        grid = FormGrid(body, scale=self.scale)
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        places = self._achievement_places(entry.name)

        f["title"] = TextField(grid.frame, str(values["title"]), width=30,
                               check=lambda t: 0 < len(t.strip()) <= dec.ACHIEVEMENT_TITLE_MAX,
                               on_change=lambda v: self._edit(entry, {"title": str(v).strip()}))
        grid.row(LABEL_TITLE, f["title"])
        f["description"] = TextField(
            grid.frame, str(values.get("description") or ""), width=30,
            check=lambda t: len(t.strip()) <= dec.ACHIEVEMENT_DESCRIPTION_MAX,
            on_change=lambda v: self._edit(entry, {"description": str(v).strip()}))
        grid.row(LABEL_DESCRIPTION, f["description"])

        image = values.get("image")
        pictures = self.picture_names()
        if isinstance(image, str) and image not in pictures:
            pictures.append(image)
        f["icon"] = _Picker(grid.frame, pictures, image if isinstance(image, str) else None,
                            width=22, none_text=NO_ICON, thumb=self.picture_thumb,
                            scale=self.scale,
                            on_change=lambda v: self._edit(entry, {"image": v}))
        grid.row(LABEL_ICON, f["icon"], hint=ICON_HINT)

        f["hidden"] = ToggleField(grid.frame, "", bool(values.get("hidden")),
                                  on_change=lambda v: self._edit(entry, {"hidden": bool(v)}))
        grid.row(LABEL_HIDDEN, f["hidden"], hint=HIDDEN_TEXT)

        self._achievement_when(grid, form, entry, values, places)

        name_line = ttk.Frame(grid.frame)
        ttk.Label(name_line, text=entry.name).pack(side="left")
        grid.row(LABEL_SCRIPT_NAME, name_line, hint=NAME_KEPT)
        uses = ttk.Frame(grid.frame)
        ttk.Label(uses, text=USED_IN.format(lines=lines_word(len(places))) if places
                  else NOT_USED).pack(side="left")
        if places:
            ttk.Button(uses, text=db.SHOW_USES, style="Link.Ghost.TButton", cursor="hand2",
                       command=lambda: self.show_achievement_uses(entry.shown, places)).pack(
                side="left", padx=(px(8), 0))
        grid.widget(uses, pady=(4, 0))
        grid.widget(ttk.Label(grid.frame, text=IN_SCRIPT.format(
            line=f"unlock achievement {entry.name}"), style="Hint.TLabel", justify="left"),
            pady=(2, 0))

        bottom = ttk.Frame(body)
        bottom.grid(row=2, column=0, sticky="ew", pady=(px(20), 0))
        f["delete"] = ttk.Button(bottom, text=DELETE, style="Secondary.TButton",
                                 command=lambda: self.delete_achievement(entry))
        f["delete"].pack(side="right")
        f["hook"] = fit_wrap(ttk.Label(body, text=HOOK_HINT, style="Hint.TLabel",
                                       justify="left"), px(WRAP_PX))
        f["hook"].grid(row=3, column=0, sticky="ew", pady=(px(16), 0))

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            now = entry.decl.values
            title.configure(text=entry.shown)
            f["title"].set(str(now["title"]))
            f["description"].set(str(now.get("description") or ""))
            f["hidden"].set(bool(now.get("hidden")))
            builder = f.get("when")
            when = now.get("when")
            if isinstance(builder, _WhenBuilder) and isinstance(when, str) \
                    and builder.var.get().strip() != when:
                builder.var.set(when)                       # Undo, or the text changed
                builder.load(when)

        form.update = update
        self._sync_achievement_moves()

    def _achievement_when(self, grid: FormGrid, form: Any, entry: db.Entry,
                          values: Mapping[str, object], places: Sequence[object]) -> None:
        """Unlocked: by an Unlock achievement line, or automatically when the builder's
        condition comes true."""
        from engine.tools.editor.dbextras import _radio_style
        px = self._px
        f = form.fields
        when = values.get("when")
        box = ttk.Frame(grid.frame)
        style = _radio_style(self.root)
        var = f["unlocked_var"] = tk.StringVar(master=box, value=AUTO if when is not None
                                               else LINE)
        f["unlocked"] = {}
        f["unlocked"][LINE] = ttk.Radiobutton(box, text=BY_LINE, value=LINE, variable=var,
                                              style=style,
                                              command=lambda: self._when_choice(entry, LINE))
        f["unlocked"][LINE].pack(anchor="w", pady=(px(2), px(2)))
        if when is None and not places:
            f["no_line"] = fit_wrap(ttk.Label(box, text=NO_LINE, style="Hint.TLabel",
                                              justify="left"), px(WRAP_PX))
            f["no_line"].pack(anchor="w", fill="x", padx=(px(24), 0), pady=(0, px(4)))
        f["unlocked"][AUTO] = ttk.Radiobutton(box, text=AUTOMATIC, value=AUTO, variable=var,
                                              style=style,
                                              command=lambda: self._when_choice(entry, AUTO))
        f["unlocked"][AUTO].pack(anchor="w", pady=(px(2), px(2)))
        card = f["when_card"] = ttk.Frame(box, style="Dialog.TFrame", padding=(px(10), px(8)))
        when_var = tk.StringVar(master=box, value=when if isinstance(when, str) else "")
        f["when"] = _WhenBuilder(card, when_var, self.condition_names(),
                                 commit=lambda: self._commit_when(entry))
        f["when"].frame.pack(anchor="w", fill="x")
        f["when_problem"] = fit_wrap(ttk.Label(card, text="", style="Dialog.Hint.TLabel",
                                               foreground=THEME["marker.warning"],
                                               justify="left"), px(WRAP_PX))
        f["when_hint"] = fit_wrap(ttk.Label(card, text=WHEN_HINT, style="Dialog.Hint.TLabel",
                                            justify="left"), px(WRAP_PX))
        f["when_hint"].pack(anchor="w", fill="x", pady=(px(6), 0))
        if when is not None:
            card.pack(anchor="w", fill="x", padx=(px(CARD_INDENT), 0), pady=(px(2), px(4)))
        grid.caption(LABEL_UNLOCKED)
        grid.widget(box, pady=(0, 2))

    def _when_choice(self, entry: db.Entry, choice: str) -> bool:
        """The Unlocked radios: "By a line" removes ``when …`` at once; "Automatically"
        shows the builder and writes once its condition is complete."""
        if choice == LINE:
            return self.set_achievement_when(entry, None)
        f = self.form.fields if self.form is not None else {}
        card, builder = f.get("when_card"), f.get("when")
        if card is None or not isinstance(builder, _WhenBuilder):
            return False
        if not card.winfo_ismapped():
            card.pack(anchor="w", fill="x", padx=(self._px(CARD_INDENT), 0),
                      pady=(self._px(2), self._px(4)))
        no_line = f.get("no_line")
        if no_line is not None:
            no_line.pack_forget()
        if not builder.scripted and not builder.checks:
            builder.add()
        self._commit_when(entry)
        return True

    def _commit_when(self, entry: db.Entry) -> bool:
        """Write the builder's condition when it is complete and new (else say why)."""
        f = self.form.fields if self.form is not None else {}
        builder, problem = f.get("when"), f.get("when_problem")
        if not isinstance(builder, _WhenBuilder) or f["unlocked_var"].get() != AUTO:
            return False
        text = builder.text()
        why = ""
        if text is None:
            why = ""                                # the row's own hint says why
        elif not text.strip():
            why = NEEDS_CHECK
        elif not dec.condition_ok(text):
            why = BAD_SCRIPT
        if problem is not None:
            problem.configure(text=why)
            if why and not problem.winfo_ismapped():
                problem.pack(anchor="w", fill="x", before=f["when_hint"])
            elif not why:
                problem.pack_forget()
        if text is None or why:
            return False
        return self.set_achievement_when(entry, text)


__all__ = ["ABOUT_ACHIEVEMENTS", "ACHIEVEMENT_PREFIX", "ACROSS_FILES", "AUTOMATIC", "BY_LINE",
           "EMPTY_HINT", "HOOK_HINT", "ICON_HINT", "MOVE_DOWN", "MOVE_UP", "NEW_ACHIEVEMENT",
           "NOT_YET", "NO_LINE", "PREVIEW", "AchievementsCategory", "detail_of",
           "lines_word", "preview_ready"]
