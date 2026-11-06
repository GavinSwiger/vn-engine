"""The Database's P2 categories (F47 ``01-design.md`` §4.3, §6.4; ``04-technical.md`` W7;
AC-F47-38, 40).

Why this module exists: the DDLC-style declarations a non-programmer makes (meters, codex
tips and items, routes, transitions, stage positions, remembered variables) get the same
list-and-form treatment as characters, and the story's endings and chapters are listed
read-only with **Go to**. ``MoreCategories`` is a mixin of ``database.DatabasePane``: it
builds these categories' rows and forms and writes through the pane's plan path (declaration
plans) or, for positions, ``tomlpatch`` plans on ``config.toml``'s open document.

- **Meters**: script name, an optional lowest/highest range, the start (``points``), ranks;
  + New offers ready-made meters, and On screen sets the look (``dbmeters``, F62).
- **Codex**: Tip or Item (a switch), title, category, picture, text paragraphs.
- **Endings & routes**: routes (title, the endings that open it, multi-pick); the
  endings, read-only, with Go to.
- **Chapters**: read-only, in story order, with Go to and ▶ Play its scene.
- **Transitions**: Dissolve, Fade or Mask with seconds, colour, mask picture, soft and
  reverse. **Try it** (P2-F, ``trywiring``) plays the form's values onto the first
  background in a small game window (``stageat.transition_entry_lines``).
- **Positions**: ``stagecanvas.StageCanvas`` (drag a marker), x and y fields, **Use
  default** for a moved built-in, Delete for one of the author's.
- **Variables** gain "Remembered across playthroughs" (``default persistent.<n>``).

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from tkinter import ttk
from typing import Any

from engine.core.constants import STAGE_COORD_RANGE
from engine.script.assetgroups import CONFIG_REF
from engine.script.messages import show
from engine.script.points import POINTS_LIMIT
from engine.tools.editor import dbmodel as db
from engine.tools.editor.dbmeters import MeterSetup
from engine.tools.editor import declarations as dec
from engine.tools.editor import declrename
from engine.tools.editor import (declplan, fieldhints, fieldwidgets, files, stageat, tomlpatch,
                                  trywiring)
from engine.tools.editor.dialogs import ask, ask_text, show_error
from engine.tools.editor.fieldwidgets import (
    AssetPicker,
    ChoiceField,
    ColorField,
    FormGrid,
    NumberField,
    TextField,
    ToggleField,
)
from engine.tools.editor.formdialogs import pick_scene
from engine.tools.editor.scriptedit import STALE, UNSAFE, Ask, Refuse
from engine.tools.editor.settingsview import LongTextField
from engine.tools.editor.stagecanvas import STAGE_H, STAGE_W, StageCanvas

# --- Texts (design §6.4's voice) ---------------------------------------------------------------

ABOUT_MORE: Mapping[str, str] = {
    db.CATEGORY_METER: "Meters count something while the game plays, such as how much a "
                       "character likes the player. Change one with a Change meter line.",
    db.CATEGORY_CODEX: "The codex is a page players open while they play. Tips are things the player "
                       "learns and keeps; items are things they hold in this playthrough.",
    db.CATEGORY_ENDING: "A route opens once the player has reached the endings you pick. "
                        + db.ENDINGS_HINT,
    db.CATEGORY_CHAPTER: db.CHAPTERS_HINT,
    db.CATEGORY_TRANSITION: "Your own transitions: a slower dissolve, a fade to white, or a "
                            "wipe through a picture. Use one with “with” like a built-in one.",
    db.CATEGORY_POSITION: "Where characters stand on the stage."}
ROUTES = "Routes"
ENDINGS = "Endings"
GO_TO = "Go to"
PLAY_SCENE = "▶ Play its scene"
NEW_TIP = "New tip…"
NEW_ITEM = "New item…"
NEW_METER_ASK = "Name of the new meter:"
NEW_CODEX_ASK = "Title of the new {kind}, as players will see it:"
NEW_ROUTE_PICK = "Where does the route start?"
NEW_ROUTE_ASK = "Title of the route, as players will see it:"
NEW_TRANSITION_ASK = "Name of the new transition:"
NEW_POSITION_ASK = "Name of the new position:"
NO_SCENES = "A route starts at a scene. Write a scene first, then add the route."
CONFIG_BROKEN = ("The game's settings file has a mistake, so the positions can't be shown. "
                 "Open it in the Editor to fix it.")
OPEN_CONFIG = "Open in Editor"
BUILT_IN = "Built-in"
MOVED = "Moved"
REMEMBERED_SHORT = "Remembered"
REMEMBERED_HINT = "Kept after the game ends, in every playthrough (persistent.{name})."
RANGE = "Has a lowest and highest"
LOW_HIGH_BAD = "The lowest must be below the highest."
START_BAD = "The start must be from {low} to {high}."
METER_HINT = "In the script: points.{name}"
ADD_RANK = "+ Rank"
REMOVE_RANK = "Remove this rank"
RANKS_NONE = "No ranks. Ranks name parts of the range, like Stranger, Friend, Close."
RANKS_HINT = 'In the script: points.rank("{name}") == "{label}"'
RANK_NO_ROOM = "There's no room above {at} for another rank. Raise the highest first."
KIND_TIP_ITEM = "Tips stay learned in every playthrough; items reset."
CATEGORY_HINT = "Empty: listed under “{default}”."
NO_PICTURE = "No picture"
TEXT_HINT = "One paragraph per line."
STARTS_AT = "Starts at"
UNTIL_CAPTION = "Opens when the player has reached"
UNTIL_HINT = "With none ticked, only an Unlock route line opens it."
NO_ENDINGS = "No endings yet. Endings come from the Ending lines of your story."
ROUTES_EMPTY = "No routes yet. Add one with + New."
IN_FILE = "{ref}, line {line}"
SEEN_BY = "Routes waiting for it: {n}"
TRY_IT = trywiring.TRY_IT
TRY_HINT = "Plays it onto your first background in a small game window. A Mask uses " \
           "its saved picture."
TRY_CANT = "This transition can't play yet: check its seconds and picture."
MASK_NEEDS = "A Mask needs a picture. Add one under Pictures first."
REVERSE = "Uncover the white parts first"
SECONDS_HINT = "The built-in length is {seconds} s."
COLOR_DEFAULT = "Black"
STAGE_HINT = "Drag a marker where the character should stand (the bottom middle of the " \
             "picture). Arrow keys move the chosen one."
X_HINT = "0 is the left edge, 1280 the right."
Y_HINT = "720 is the bottom edge."
POSITION_IN_SCRIPT = "show hana happy at {name}"
IN_SCRIPT = "In the script: {line}"
RENAME_LOCKED = "The script uses this name, so it can't change here yet."
RENAME_BUTTON = "Rename…"
RENAME_HINT = "Rename… changes every line that uses it too."
DELETE = "Delete"
DELETE_BUTTONS = ("Delete", "Cancel")
DELETE_POSITION_ASK = ("Delete {name}? Its line goes from the game's settings file; Edit "
                       "▸ Undo there brings it back.")

LABEL_SCRIPT_NAME = "Script name"
LABEL_LOW = "Lowest"
LABEL_HIGH = "Highest"
LABEL_START = "Start"
LABEL_RANKS = "Ranks"
LABEL_KIND = "Kind"
LABEL_TITLE = "Title"
LABEL_CATEGORY = "Category"
LABEL_PICTURE = "Picture"
LABEL_TEXT = "Text"
LABEL_COUNT = "Count"                    # F64: an item held many times
LABEL_MOST = "Most held"
LABEL_MONEY = "Money"
COUNT_TEXT = "Can hold more than one"
MONEY_TEXT = "This is the money"
LABEL_PRICE = "Price"                    # F64 round 2: a shop's default price
LABEL_USE = "Use scene"                  # F64 round 2: the scene the bag's Use runs
USE_NONE = "(none: no Use button)"
LABEL_HEADING = "Heading"
LABEL_WHERE = "Where"
LABEL_SECONDS = "Seconds"
LABEL_COLOR = "Colour"
LABEL_MASK = "Mask picture"
LABEL_SOFT = "Soft edge"
LABEL_REVERSE = "Direction"
LABEL_X = "Across (x)"
LABEL_Y = "Down (y)"

NEW_METER_RANGE = (0, 100)              # a new meter: points <n> 0 to 100
NEW_TRANSITION_SECONDS = 1.0
STAGE_PX = 480                          # the Positions canvas' stage width at 100 %, at most
STAGE_MIN_PX = 240                      # ... and at least
HINT_WRAP_PX = 180                      # a form's hint lines wrap at this width
FORM_ROOM = 28                          # the form's padding and scroll bar, each side
SECONDS_DEFAULTS = {dec.DISSOLVE: 0.5, dec.FADE: 1.0, dec.MASK: 1.0}
CODEX_PREFIX = {dec.TIP: "t:", dec.ITEM: "i:"}
PREFIXES = {dec.CHARACTER: "c:", dec.VARIABLE: "v:", dec.COLOR: "k:", dec.PERSISTENT: "pv:",
            dec.METER: "m:", dec.TIP: "t:", dec.ITEM: "i:", dec.ROUTE: "r:",
            dec.TRANSITION: "x:", dec.CONTACT: "ct:"}
READ_ONLY = (db.CATEGORY_CHAPTER,)      # no + New
IMAGE_GROUPS = ("images", "gui")


@dataclass(frozen=True)
class Row:
    """One list row: an entry, or a group (``entry`` None) of pictures, sounds, codex
    entries, routes or endings."""

    iid: str
    text: str
    detail: str
    entry: db.Entry | None = None
    parent: str = ""
    ref: str | None = None              # a file's ref (pictures, sounds)
    color: str | None = None            # a character's name colour (the dot)
    group: str | None = None            # a group's key
    title: str = ""                     # a group's title


def _label_at(text: str, line: int) -> str | None:
    """The label whose block holds line ``line`` (1-based) of ``text``."""
    lines = text.split("\n")
    for index in range(min(line, len(lines)) - 1, -1, -1):
        words = lines[index].split()
        if len(words) >= 2 and words[0] == "label" and not lines[index][:1].isspace():
            return words[1].rstrip(":").split("(")[0] or None
    return None


def _paragraphs(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in str(text).split("\n") if line.strip())



def _ranks_hint(name: str, values: Mapping[str, object]) -> str:
    """F62: how the script reads the meter's rank (its top label), or what ranks are."""
    ranks = values.get("ranks") or ()
    if not ranks:
        return RANKS_NONE
    return RANKS_HINT.format(name=name, label=ranks[-1][0])

def _price_text(price: object) -> str:
    """F64 round 2: the Price field's text ("" for no price)."""
    return str(price) if type(price) is int else ""


def _price_value(text: str) -> "int | None | bool":
    """F64 round 2: the Price field's value: None (empty), a whole number 0 to the most an
    item can hold, or False for anything else."""
    text = text.strip().replace(",", "")
    if not text:
        return None
    if text.isascii() and text.isdigit() and int(text) <= dec.ITEM_COUNT_MAX:
        return int(text)
    return False


class MoreCategories(MeterSetup):
    """The P2 categories of ``database.DatabasePane`` (a mixin: it uses the pane's rows,
    forms and writers)."""

    win: Any
    root: Any
    scale: float
    texts: dict[str, str]
    decls: tuple[dec.Decl, ...]
    names: Mapping
    rows: dict[str, list[Row]]
    form: Any
    fonts: Any
    category: str
    chosen: dict[str, str | None]
    new_button: Any
    form_frame: Any
    body: Any
    thumbs: Any
    # The pane's helpers this mixin calls (database.DatabasePane defines them).
    _px: Callable[[float], int]
    _short: Callable[[db.Entry], str]
    _detail: Callable[[db.Entry], str]
    _check_ran: Callable[[], bool]
    _new_body: Callable[[tuple], tuple[ttk.Frame, Any]]
    _title: Callable[..., ttk.Label]
    _uses_line: Callable[[tk.Misc, db.Entry], ttk.Frame]
    _bottom: Callable[..., None]
    _complex: Callable[..., None]
    _fresh: Callable[[db.Entry], dec.Decl | None]
    _edit: Callable[[db.Entry, Mapping[str, object]], bool]
    _rename: Callable[[db.Entry, str], bool]
    _write: Callable[..., bool]
    _delete_decl: Callable[[db.Entry], bool]
    _taken: Callable[[str], frozenset[str]]
    _project_refs: Callable[[str], list[str]]
    _read_texts: Callable[[], dict[str, str]]
    refresh: Callable[..., None]
    select: Callable[[str], None]
    select_category: Callable[[str], None]
    selected_row: Callable[[], Row | None]
    delete_entry: Callable[..., None]
    marks: tuple[dec.Decl, ...] = ()
    positions: list[db.Entry] | None = None
    stage: StageCanvas | None = None

    # --- Rows -------------------------------------------------------------------------------

    def _p2_rows(self) -> dict[str, list[Row]]:
        self.marks = dec.marks(self.texts)
        short = self._short
        rows: dict[str, list[Row]] = {}
        rows[db.CATEGORY_METER] = [Row(f"m:{e.name}", e.shown, short(e), e)
                                   for e in db.meter_entries(self.decls, self.names)]
        codex = db.codex_entries(self.decls, self.names)
        rows[db.CATEGORY_CODEX] = self._grouped([
            (dec.TIP, db.TIPS, [(CODEX_PREFIX[dec.TIP], e) for e in codex[dec.TIP]]),
            (dec.ITEM, db.ITEMS, [(CODEX_PREFIX[dec.ITEM], e) for e in codex[dec.ITEM]])])
        rows[db.CATEGORY_ENDING] = self._grouped([
            ("routes", ROUTES, [("r:", e) for e in db.route_entries(self.decls, self.names)]),
            ("endings", ENDINGS, [("e:", e) for e in db.ending_entries(self.marks,
                                                                       self.names)])],
            short=lambda e: self._waiting(e) if e.kind == dec.ENDING else self._short(e))
        rows[db.CATEGORY_CHAPTER] = [
            Row(f"h:{e.name}", e.shown, self._place_short(e), e)
            for e in db.chapter_entries(self.marks, self.names)]
        rows[db.CATEGORY_TRANSITION] = [
            Row(f"x:{e.name}", e.name, short(e), e)
            for e in db.transition_entries(self.decls, self.names)]
        self.positions = db.position_entries(self.config_text() or "", self.names) \
            if self.config_text() is not None else None
        rows[db.CATEGORY_POSITION] = [
            Row(f"o:{e.name}", e.name, self._position_short(e), e)
            for e in self.positions or ()]
        return rows

    def _grouped(self, groups: Sequence[tuple[str, str, list[tuple[str, db.Entry]]]],
                 short: Callable[[db.Entry], str] | None = None) -> list[Row]:
        short = short or self._short
        rows: list[Row] = []
        for key, title, members in groups:
            gid = f"g:{key}"
            rows.append(Row(gid, title, str(len(members)) if members else "", group=key,
                            title=title))
            rows += [Row(f"{prefix}{e.name}", e.shown, short(e), e, gid, group=key)
                     for prefix, e in members]
        return rows

    def _waiting(self, entry: db.Entry) -> str:
        """An ending's list detail: how many routes wait for it."""
        if not self._check_ran() or entry.uses <= 0:
            return ""
        return f"{entry.uses} route" if entry.uses == 1 else f"{entry.uses} routes"

    def _remembered_rows(self) -> list[Row]:
        return [Row(f"pv:{e.name}", e.name, REMEMBERED_SHORT, e)
                for e in db.remembered_entries(self.decls, self.names)]

    @staticmethod
    def _place_short(entry: db.Entry) -> str:
        if entry.place is None:
            return ""
        ref, line = entry.place
        return f"{ref.rsplit('/', 1)[-1]}:{line}"

    def _position_short(self, entry: db.Entry) -> str:
        values = entry.values or {}
        if values.get("builtin"):
            return MOVED if values.get("written") else BUILT_IN
        return self._short(entry)

    # --- config.toml ------------------------------------------------------------------------

    def config_text(self) -> str | None:
        """``config.toml``'s editor text (the file's when it isn't open); None when it
        can't be read."""
        record = self.win.files.get(CONFIG_REF)
        if record is not None:
            return record.widget.get("1.0", "end-1c") if record.editable else None
        try:
            return (self.win.paths.root / CONFIG_REF).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def _write_toml(self, plan: object, select: str | None = None) -> bool:
        if plan is None:
            self.refresh(select=select)
            return True
        if isinstance(plan, Refuse):
            show_error(self.root, plan.text)
            self.refresh()
            return False
        assert isinstance(plan, tomlpatch.TomlPlan)
        tp = plan
        if not self.win.apply_plan(tp.as_plan(),
                                   lambda texts: tomlpatch.verify(tp, texts[CONFIG_REF])):
            show_error(self.root, STALE)
            self.refresh()
            return False
        self.win._update_marks()
        self.refresh(select=select)
        return True

    def _live_config(self) -> str | None:
        record = self.win.record_for(CONFIG_REF)
        return record.widget.get("1.0", "end-1c") if record.editable else None

    # --- Dispatch ---------------------------------------------------------------------------

    def _p2_form(self, row: Row, key: tuple) -> bool:
        """Show ``row``'s P2 form; False when it isn't a P2 entry."""
        entry = row.entry
        if entry is None:
            return False
        kind = entry.kind
        if kind == dec.METER:
            self._meter_form(row, key)
        elif kind in (dec.TIP, dec.ITEM):
            self._codex_form(row, key)
        elif kind == dec.ROUTE:
            self._route_form(row, key)
        elif kind in (dec.ENDING, dec.CHAPTER):
            self._mark_form(row, key)
        elif kind == dec.TRANSITION:
            self._transition_form(row, key)
        elif kind == dec.POSITION:
            self._positions_form(row, key)
        else:
            return False
        return True

    def _p2_key(self, entry: db.Entry, shape: tuple) -> tuple | None:
        """The P2 part of a form key (positions share one form, so the canvas stays)."""
        values = entry.decl.values if entry.decl is not None else None
        if entry.kind == dec.POSITION:
            return ("stage",)
        if entry.kind == dec.METER and values is not None:
            return shape + (values.get("low") is None, entry.decl.group,
                            len(values.get("ranks") or ()))
        if entry.kind == dec.TRANSITION and values is not None:
            return shape + (values.get("kind"),)
        if entry.kind == dec.ROUTE:
            return shape + (db.ending_names(self.marks, self.names),)
        return None

    def _p2_group_form(self, row: Row, key: tuple) -> None:
        body, _form = self._new_body(key)
        self._title(body, row.title)
        members = [r for r in self.rows[self.category] if r.parent == row.iid]
        buttons = ttk.Frame(body)
        buttons.grid(row=1, column=0, sticky="w", pady=(0, self._px(12)))
        if row.group in (dec.TIP, dec.ITEM):
            kind = str(row.group)
            ttk.Button(buttons, text="+ " + (NEW_TIP if kind == dec.TIP else NEW_ITEM),
                       style="Secondary.TButton",
                       command=lambda: self.new_codex(kind)).pack(side="left")
            empty = db.EMPTY_TITLE.format(things=row.title.casefold())
        elif row.group == "routes":
            ttk.Button(buttons, text="+ New route…", style="Secondary.TButton",
                       command=self.new_route).pack(side="left")
            empty = ROUTES_EMPTY
        else:
            empty = NO_ENDINGS
        text = "\n".join(r.text for r in members) if members else empty
        fieldwidgets.fit_wrap(ttk.Label(body, text=text, style="Hint.TLabel", justify="left"),
                              self._px(360)).grid(row=2, column=0, sticky="ew")
        if row.group == "endings" and members:
            ttk.Label(body, text=db.ENDINGS_HINT, style="Hint.TLabel").grid(
                row=3, column=0, sticky="w", pady=(self._px(12), 0))

    # --- Shared bits ------------------------------------------------------------------------

    def _read_only(self, row: Row, key: tuple) -> bool:
        """The Edit as script form for an entry the form can't read; True when shown."""
        entry = row.entry
        assert entry is not None
        if entry.editable and entry.decl is not None and entry.decl.values is not None:
            return False
        body, _form = self._new_body(key)
        self._title(body, entry.shown)
        self._complex(body, 1, entry)
        body.rowconfigure(2, minsize=self._px(12))
        self._uses_line(body, entry).grid(row=3, column=0, sticky="w")
        return True

    def _name_row(self, grid: FormGrid, form: Any, entry: db.Entry) -> None:
        if entry.name_editable:
            form.fields["name"] = TextField(
                grid.frame, entry.name, width=18, check=lambda t: bool(t.strip()),
                on_change=lambda v: self._rename(entry, str(v).strip()))
            grid.row(LABEL_SCRIPT_NAME, form.fields["name"])
        elif entry.kind in declrename.RENAMABLE:
            grid.row(LABEL_SCRIPT_NAME, self._rename_box(grid.frame, entry.name),
                     hint=RENAME_HINT)
        else:
            grid.row(LABEL_SCRIPT_NAME, ttk.Label(grid.frame, text=entry.name),
                     hint=RENAME_LOCKED)

    # --- Rename everywhere (P3-B, AC-F47-52) ------------------------------------------------

    def _rename_box(self, parent: tk.Misc, name: str) -> ttk.Frame:
        """The script name with **Rename…** beside it (for a used entry)."""
        box = ttk.Frame(parent)
        ttk.Label(box, text=name).pack(side="left")
        ttk.Button(box, text=RENAME_BUTTON, style="Link.Ghost.TButton",
                   command=self.rename_selected).pack(side="left", padx=(self._px(8), 0))
        return box

    def _rename_inputs(self) -> tuple[dict[str, str], dict[str, str], frozenset[str],
                                      str | None]:
        """Every script's text, the read-only ones' reasons, the story's position names and
        config.toml's text, for ``declrename.plan_rename``."""
        texts: dict[str, str] = {}
        locked: dict[str, str] = {}
        for ref in self.win._script_refs():
            text, reason = self.win._script_text(ref)
            texts[ref] = text
            if reason is not None:
                locked[ref] = reason
        config = self.config_text()
        if config is not None and CONFIG_REF in self.win.files \
                and not self.win.files[CONFIG_REF].editable:
            locked[CONFIG_REF] = CONFIG_BROKEN
        rows = dec.position_rows(config) if config is not None else None
        positions = frozenset(self.win._positions()) | {r.name for r in rows or ()}
        return texts, locked, positions, config

    def rename_everywhere(self, kind: str, old: str, new: str,
                          simple: Callable[[], bool] | None = None,
                          select: str | None = None) -> bool:
        """Rename ``kind`` ``old`` to ``new`` and every use of it, after the Ask ("N places
        in M files will change", and what happens to saves). When only the declaration
        changes, nothing is asked (``simple``, the old in-place edit, does it when given)."""
        texts, locked, positions, config = self._rename_inputs()
        taken = positions if kind == dec.POSITION else ()

        def plan(confirm: bool) -> object:
            try:
                return declrename.plan_rename(kind, old, new, texts, locked=locked,
                                              config_text=config, positions=positions,
                                              taken=taken, confirm=confirm)
            except Exception:           # a planner bug must never reach the text
                return Refuse(UNSAFE)
        result = plan(True)
        if result is None:
            return True
        if isinstance(result, Refuse):
            show_error(self.root, result.text)
            self.refresh()
            return False
        assert isinstance(result, declrename.RenamePlan)
        if result.places <= 1 and simple is not None:
            return simple()
        if result.places > 1:
            question = plan(False)
            if not isinstance(question, Ask):
                return False
            if ask(self.root, question.text, question.buttons, escape=question.escape,
                   default=question.default) != 0:
                self.refresh()
                return False
        rename = result
        if not self.win.apply_plan(rename.plan, lambda now: declrename.verify_rename(
                rename, now, positions)):
            show_error(self.root, STALE)
            self.refresh()
            return False
        self.win._update_marks()
        self.refresh(select=select)
        return True

    def _wrap_hints(self) -> None:
        """Hint lines in the form wrap instead of running out of a narrow form."""
        stack = [self.body] if self.body is not None else []
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, ttk.Label) and str(widget.cget("style")) == "Hint.TLabel"                     and not str(widget.cget("wraplength")).strip("0"):
                widget.configure(wraplength=self._px(HINT_WRAP_PX))

    def _go_to(self, parent: tk.Misc, entry: db.Entry) -> ttk.Button | None:
        if entry.place is None:
            return None
        ref, line = entry.place
        return ttk.Button(parent, text=GO_TO, style="Secondary.TButton",
                          command=lambda: self.win.jump_to(ref, line))

    def _swap(self, entry: db.Entry, kind: str, change: Mapping[str, object] | None = None
              ) -> bool:
        """Switch ``entry`` to ``kind`` (Tips / Items, Remembered across playthroughs)."""
        decl = self._fresh(entry)
        if decl is None or decl.values is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        values = {**decl.values, **(change or {})}
        return self._write(declplan.plan_edit(decl, values, self.texts, kind=kind),
                           select=PREFIXES[kind] + decl.name)

    def _refuse_field(self, field: Any, text: str) -> None:
        show_error(self.root, text)
        row = self.selected_row()
        if self.form is not None and self.form.update is not None and row is not None:
            self.form.update(row)
        else:
            field.set(field.value)

    # --- Meters -----------------------------------------------------------------------------

    def _meter_form(self, row: Row, key: tuple) -> None:
        if self._read_only(row, key):
            return
        entry = row.entry
        assert entry is not None and entry.decl is not None and entry.decl.values is not None
        body, form = self._new_body(key)
        title = self._title(body, entry.name)
        values = dict(entry.decl.values)
        ranged = values.get("low") is not None
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_METER))
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        self._name_row(grid, form, entry)
        f["range"] = ToggleField(grid.frame, RANGE, ranged,
                                 on_change=lambda v: self._meter_range(entry, bool(v)))
        grid.widget(f["range"].widget, pady=(4, 4))
        low, high = NEW_METER_RANGE if not ranged else (values["low"], values["high"])
        f["low"] = NumberField(grid.frame, int(low), lo=-POINTS_LIMIT, hi=POINTS_LIMIT,
                               width=10, on_change=lambda v: self._meter_bound(entry, "low", v))
        grid.row(LABEL_LOW, f["low"])
        f["high"] = NumberField(grid.frame, int(high), lo=-POINTS_LIMIT, hi=POINTS_LIMIT,
                                width=10,
                                on_change=lambda v: self._meter_bound(entry, "high", v))
        grid.row(LABEL_HIGH, f["high"])
        for name in ("low", "high"):
            f[name].enable(ranged)
        f["start"] = NumberField(grid.frame, dec.meter_start(values), lo=-POINTS_LIMIT,
                                 hi=POINTS_LIMIT, width=10,
                                 on_change=lambda v: self._meter_start(entry, v))
        grid.row(LABEL_START, f["start"])
        ranks_hint = self._ranks_rows(grid, form, entry, values)        # F62
        self._game_now_row(grid, entry.name)            # type: ignore[attr-defined]  (F40)
        hint = ttk.Label(grid.frame, text=METER_HINT.format(name=entry.name),
                         style="Hint.TLabel")
        grid.widget(hint, pady=(6, 2))
        grid.widget(self._uses_line(grid.frame, entry), pady=(2, 0))
        show_look = self._look_rows(grid, form, entry, values)          # F62 round 2
        self._bottom(body, 2, entry, lambda: self._delete_decl(entry))

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            now = entry.decl.values
            title.configure(text=entry.name)
            if "name" in f:
                f["name"].set(entry.name)
            if now.get("low") is not None:
                f["low"].set(int(now["low"]))
                f["high"].set(int(now["high"]))
            f["start"].set(dec.meter_start(now))
            for index, (label, at) in enumerate(now.get("ranks") or ()):
                if f"rank{index}" in f:
                    f[f"rank{index}"].set(str(label))
                    f[f"at{index}"].set(int(at))
            ranks_hint.configure(text=_ranks_hint(entry.name, now))
            hint.configure(text=METER_HINT.format(name=entry.name))
            show_look(entry, now)

        form.update = update

    def _ranks_rows(self, grid: FormGrid, form: Any, entry: db.Entry,
                    values: Mapping[str, object]) -> ttk.Label:
        """F62: the Ranks table, a label and its starting number per row, lowest first, with
        **+ Rank** and a remove button per row. Returns the hint under it."""
        f = form.fields
        ranks = values.get("ranks") or ()
        for index, (label, at) in enumerate(ranks):
            line = ttk.Frame(grid.frame)
            f[f"rank{index}"] = TextField(
                line, str(label), width=16, check=lambda t: bool(t.strip()),
                on_change=lambda v, i=index: self._rank_change(entry, i, label=str(v)))
            f[f"rank{index}"].widget.pack(side="left")
            ttk.Label(line, text=STARTS_AT).pack(side="left", padx=(self._px(8), self._px(4)))
            f[f"at{index}"] = NumberField(
                line, int(at), lo=-POINTS_LIMIT, hi=POINTS_LIMIT, width=8,
                on_change=lambda v, i=index: self._rank_change(entry, i, at=int(v)))
            f[f"at{index}"].widget.pack(side="left")
            ttk.Button(line, text="×", width=2, style="Ghost.TButton",
                       command=lambda i=index: self._rank_remove(entry, i)).pack(
                side="left", padx=(self._px(6), 0))
            grid.row("" if index else LABEL_RANKS, line)
        add = ttk.Button(grid.frame, text=ADD_RANK, style="Secondary.TButton",
                         command=lambda: self._rank_add(entry))
        f["add_rank"] = add
        row = grid.row("" if ranks else LABEL_RANKS, add, hint=_ranks_hint(entry.name, values))
        assert row.hint is not None
        return row.hint

    def _rank_edit(self, entry: db.Entry, ranks: list[tuple[str, int]],
                   field: Any = None) -> bool:
        values = self._now_values(entry)
        if values is None:
            return self._edit(entry, {})
        problem = dec.ranks_problem({**values, "ranks": tuple(ranks)})
        if problem is not None:
            if field is not None:
                self._refuse_field(field, problem)
            else:
                show_error(self.root, problem)
            return False
        return self._edit(entry, {"ranks": tuple(ranks)})

    def _rank_change(self, entry: db.Entry, index: int, *, label: str | None = None,
                     at: int | None = None) -> bool:
        values = self._now_values(entry)
        ranks = list((values or {}).get("ranks") or ())
        if index >= len(ranks):
            return self._edit(entry, {})
        old_label, old_at = ranks[index]
        ranks[index] = (old_label if label is None else label.strip(),
                        old_at if at is None else at)
        field = self.form.fields.get(f"rank{index}" if label is not None else f"at{index}")
        return self._rank_edit(entry, ranks, field)

    def _rank_add(self, entry: db.Entry) -> bool:
        values = self._now_values(entry)
        if values is None:
            return self._edit(entry, {})
        ranks = list(values.get("ranks") or ())
        high = values.get("high")
        if ranks:
            at = int(ranks[-1][1]) + 1
            if type(high) is int and at > high:
                show_error(self.root, RANK_NO_ROOM.format(at=ranks[-1][1]))
                return False
        else:
            at = dec.meter_start(values)
        taken = {label for label, _ in ranks}
        number = len(ranks) + 1
        while f"Rank {number}" in taken:
            number += 1
        return self._rank_edit(entry, ranks + [(f"Rank {number}", at)])

    def _rank_remove(self, entry: db.Entry, index: int) -> bool:
        values = self._now_values(entry)
        ranks = list((values or {}).get("ranks") or ())
        if index >= len(ranks):
            return self._edit(entry, {})
        del ranks[index]
        return self._rank_edit(entry, ranks)

    def _now_values(self, entry: db.Entry) -> dict[str, object] | None:
        decl = self._fresh(entry)
        return dict(decl.values) if decl is not None and decl.values is not None else None

    def _meter_range(self, entry: db.Entry, on: bool) -> bool:
        values = self._now_values(entry)
        if values is None:
            return self._edit(entry, {})
        if not on:
            return self._edit(entry, {"low": None, "high": None})
        start = dec.meter_start(values)
        ats = [int(at) for _, at in values.get("ranks") or ()]       # F62: keep ranks inside
        low = min(NEW_METER_RANGE[0], start, *ats)
        high = max(NEW_METER_RANGE[1], start, *ats)
        return self._edit(entry, {"low": low, "high": high})

    def _meter_bound(self, entry: db.Entry, which: str, value: object) -> bool:
        values = self._now_values(entry)
        if values is None or values.get("low") is None:
            return self._edit(entry, {})
        values[which] = int(value)
        low, high = int(values["low"]), int(values["high"])
        if not low < high:
            self._refuse_field(self.form.fields[which], LOW_HIGH_BAD)
            return False
        problem = dec.ranks_problem(values)                  # F62: ranks stay in range
        if problem is not None:
            self._refuse_field(self.form.fields[which], problem)
            return False
        change: dict[str, object] = {which: int(value)}
        start = values.get("start")
        if isinstance(start, int) and not low <= start <= high:      # keep the start inside
            change["start"] = min(high, max(low, start))
        return self._edit(entry, change)

    def _meter_start(self, entry: db.Entry, value: object) -> bool:
        values = self._now_values(entry)
        start = int(value)
        if values is not None and values.get("low") is not None:
            low, high = int(values["low"]), int(values["high"])
            if not low <= start <= high:
                self._refuse_field(self.form.fields["start"],
                                   START_BAD.format(low=low, high=high))
                return False
        return self._edit(entry, {"start": start})

    # --- Codex ------------------------------------------------------------------------------

    def _image_names(self) -> dict[str, str]:
        """Image name → file ref, for the codex picture."""
        out: dict[str, str] = {}
        for ref in self._project_refs("images"):
            name = files.image_name_of(ref)
            if name:
                out.setdefault(name, ref)
        return out

    def _codex_form(self, row: Row, key: tuple) -> None:
        if self._read_only(row, key):
            return
        entry = row.entry
        assert entry is not None and entry.decl is not None and entry.decl.values is not None
        body, form = self._new_body(key)
        title = self._title(body, entry.shown)
        values = dict(entry.decl.values)
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_CODEX))
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        f["kind"] = ChoiceField(grid.frame, [(dec.TIP, "Tip"), (dec.ITEM, "Item")],
                                entry.kind, width=12,
                                on_change=lambda v: self._swap(entry, str(v)))
        grid.row(LABEL_KIND, f["kind"], hint=KIND_TIP_ITEM)
        f["title"] = TextField(grid.frame, str(values["title"]), width=26,
                               check=lambda t: bool(t.strip()),
                               on_change=lambda v: self._edit(entry, {"title": str(v).strip()}))
        grid.row(LABEL_TITLE, f["title"])
        categories = db.codex_categories(self.decls, self.names)
        var = tk.StringVar(master=self.root, value=str(values.get("category") or ""))
        box = ttk.Combobox(grid.frame, textvariable=var, values=list(categories), width=24)

        def category_done(_event: object = None) -> None:
            text = var.get().strip()
            now = self._now_values(entry) or {}
            if (text or None) != now.get("category"):
                self._edit(entry, {"category": text or None})

        for sequence in ("<Return>", "<KP_Enter>", "<FocusOut>", "<<ComboboxSelected>>"):
            box.bind(sequence, category_done, add="+")
        f["category"] = box
        default = db.TIPS if entry.kind == dec.TIP else db.ITEMS
        grid.row(LABEL_CATEGORY, box, hint=CATEGORY_HINT.format(default=default))
        images = self._image_names()
        pictures = sorted(images, key=str.casefold)

        def thumb(name: str) -> object:
            ref = images.get(name)
            self._preview_ref = ref
            return self.thumbs.get(ref) if ref else None

        f["image"] = AssetPicker(grid.frame, pictures, values.get("image"), width=18,
                                 none_text=NO_PICTURE, thumb=thumb, scale=self.scale,
                                 on_change=lambda v: self._edit(entry, {"image": v}))
        grid.row(LABEL_PICTURE, f["image"])
        if entry.kind == dec.ITEM:                                   # F64: counts, money
            self._count_rows(grid, f, entry, values)
        f["text"] = LongTextField(grid.frame, "\n\n".join(values.get("text") or ()),
                                  width=40, height=6,
                                  on_change=lambda v: self._codex_text(entry, str(v)))
        f["text"].text.configure(font=self.fonts.get("body"), padx=self._px(6),
                                 pady=self._px(4))
        grid.row(LABEL_TEXT, f["text"], hint=TEXT_HINT)
        self._name_row(grid, form, entry)
        grid.widget(self._uses_line(grid.frame, entry), pady=(8, 0))
        self._bottom(body, 2, entry, lambda: self._delete_decl(entry))

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            now = entry.decl.values
            title.configure(text=entry.shown)
            f["kind"].set(entry.kind)
            f["title"].set(str(now["title"]))
            var.set(str(now.get("category") or ""))
            f["image"].set(now.get("image"))
            if "count" in f:                                         # F64
                f["count"].set(now.get("count") is not None)
                f["most"].set(int(now.get("count") or dec.ITEM_COUNT_MAX))
                f["money"].set(now.get("money") is True)
                f["price"].set(_price_text(now.get("price")))
                if "use" in f:                                       # F64 round 2
                    f["use"].set(now.get("use"))
            f["text"].set("\n\n".join(now.get("text") or ()))
            if "name" in f:
                f["name"].set(entry.name)

        form.update = update

    def _count_rows(self, grid: FormGrid, f: dict, entry: db.Entry,
                    values: Mapping[str, object]) -> None:
        """F64: Count (can hold more than one), Most held, and This is the money."""
        count = values.get("count")
        f["count"] = ToggleField(grid.frame, COUNT_TEXT, count is not None,
                                 on_change=lambda v: self._codex_count(entry, bool(v)))
        grid.row(LABEL_COUNT, f["count"].widget)
        f["most"] = NumberField(grid.frame, int(count or dec.ITEM_COUNT_MAX), lo=1,
                                hi=dec.ITEM_COUNT_MAX, width=10,
                                on_change=lambda v: self._edit(entry, {"count": int(v)}))
        grid.row(LABEL_MOST, f["most"])
        f["money"] = ToggleField(grid.frame, MONEY_TEXT, values.get("money") is True,
                                 on_change=lambda v: self._codex_money(entry, bool(v)))
        grid.row(LABEL_MONEY, f["money"].widget)
        f["price"] = TextField(grid.frame, _price_text(values.get("price")), width=10,
                               check=lambda t: _price_value(t) is not False,
                               on_change=lambda v: self._edit(
                                   entry, {"price": _price_value(str(v))}))
        grid.row(LABEL_PRICE, f["price"].widget)
        scenes = sorted(self.win._scene_names()) if hasattr(self.win, "_scene_names") else []
        use = values.get("use")
        if use is not None and use not in scenes:
            scenes.append(str(use))                     # a scene not found keeps its name
        f["use"] = ChoiceField(grid.frame, [(None, USE_NONE)] + [(s, s) for s in scenes],
                               use, width=24,
                               on_change=lambda v: self._edit(entry, {"use": v or None}))
        grid.row(LABEL_USE, f["use"].widget)

    def _codex_count(self, entry: db.Entry, on: bool) -> bool:
        """F64: Count on keeps (or sets) the most held; off makes a plain item again."""
        now = self._now_values(entry) or {}
        if on:
            return self._edit(entry, {"count": now.get("count") or dec.ITEM_COUNT_MAX})
        return self._edit(entry, {"count": None, "money": False})

    def _codex_money(self, entry: db.Entry, on: bool) -> bool:
        """F64: the money is always counted, so turning it on turns Count on too."""
        now = self._now_values(entry) or {}
        if on:
            return self._edit(entry, {"money": True,
                                      "count": now.get("count") or dec.ITEM_COUNT_MAX})
        return self._edit(entry, {"money": False})

    def _codex_text(self, entry: db.Entry, text: str) -> bool:
        paragraphs = _paragraphs(text)
        now = self._now_values(entry) or {}
        if tuple(now.get("text") or ()) == paragraphs:
            return True
        return self._edit(entry, {"text": paragraphs})

    # --- Endings & routes, chapters ---------------------------------------------------------

    def _route_form(self, row: Row, key: tuple) -> None:
        if self._read_only(row, key):
            return
        entry = row.entry
        assert entry is not None and entry.decl is not None and entry.decl.values is not None
        body, form = self._new_body(key)
        title = self._title(body, entry.shown)
        values = dict(entry.decl.values)
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(fieldhints.ROUTE))
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        f["title"] = TextField(grid.frame, str(values["title"]), width=26,
                               check=lambda t: bool(t.strip()),
                               on_change=lambda v: self._edit(entry, {"title": str(v).strip()}))
        grid.row(LABEL_TITLE, f["title"])
        start = ttk.Frame(grid.frame)
        ttk.Label(start, text=entry.name).pack(side="left")
        go = self._scene_button(start, entry.name)
        if go is not None:
            go.pack(side="left", padx=(self._px(8), 0))
        grid.row(STARTS_AT, start)
        grid.caption(UNTIL_CAPTION)
        until = tuple(values.get("until") or ())
        endings = list(db.ending_names(self.marks, self.names))
        endings += [n for n in until if n not in endings]
        shown = {e.name: e.shown for e in db.ending_entries(self.marks, self.names)}
        f["until"] = {}
        for name in endings:
            label = f"{shown[name]} ({name})" if shown.get(name, name) != name else name
            toggle = ToggleField(grid.frame, label, name in until,
                                 on_change=lambda v, n=name: self._route_until(entry, n,
                                                                               bool(v)))
            f["until"][name] = toggle
            grid.widget(toggle.widget, pady=(1, 1))
        if not endings:
            grid.widget(ttk.Label(grid.frame, text=NO_ENDINGS, style="Hint.TLabel"))
        grid.widget(ttk.Label(grid.frame, text=UNTIL_HINT, style="Hint.TLabel"), pady=(4, 2))
        grid.widget(self._uses_line(grid.frame, entry), pady=(8, 0))
        self._bottom(body, 2, entry, lambda: self._delete_decl(entry))

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            now = entry.decl.values
            title.configure(text=entry.shown)
            f["title"].set(str(now["title"]))
            picked = tuple(now.get("until") or ())
            for name, toggle in f["until"].items():
                toggle.set(name in picked)

        form.update = update

    def _route_until(self, entry: db.Entry, name: str, on: bool) -> bool:
        now = self._now_values(entry) or {}
        until = list(now.get("until") or ())
        if on and name not in until:
            until.append(name)
        elif not on and name in until:
            until.remove(name)
        return self._edit(entry, {"until": tuple(until)})

    def _scene_button(self, parent: tk.Misc, label: str | None) -> ttk.Button | None:
        if not label:
            return None
        return ttk.Button(parent, text=PLAY_SCENE, style="Secondary.TButton",
                          command=lambda: self.win.play(label))

    def _mark_form(self, row: Row, key: tuple) -> None:
        """An ending or a chapter: read-only, with Go to (and, for a chapter, ▶ Play)."""
        entry = row.entry
        assert entry is not None
        body, _form = self._new_body(key)
        values = entry.decl.values if entry.decl is not None and entry.decl.values else {}
        self._title(body, entry.shown)
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_ENDING))
        grid.frame.grid(row=1, column=0, sticky="ew")
        if values.get("heading"):
            grid.row(LABEL_HEADING, ttk.Label(grid.frame, text=str(values["heading"])))
        grid.row(LABEL_SCRIPT_NAME, ttk.Label(grid.frame, text=entry.name))
        if entry.place is not None:
            ref, line = entry.place
            grid.row(LABEL_WHERE, ttk.Label(grid.frame, text=IN_FILE.format(
                ref=show(ref), line=line)))
        buttons = ttk.Frame(grid.frame)
        go = self._go_to(buttons, entry)
        if go is not None:
            go.pack(side="left")
        if entry.kind == dec.CHAPTER and entry.place is not None:
            label = _label_at(self.texts.get(entry.place[0], ""), entry.place[1])
            play = self._scene_button(buttons, label)
            if play is not None:
                play.pack(side="left", padx=(self._px(8), 0))
        replay = getattr(self, "ending_replay_button", None)      # F36: dbreplays
        if entry.kind == dec.ENDING and entry.place is not None and callable(replay):
            label = _label_at(self.texts.get(entry.place[0], ""), entry.place[1])
            button = replay(buttons, label)
            if button is not None:
                button.pack(side="left", padx=(self._px(8), 0))
        grid.widget(buttons, pady=(8, 8))
        if entry.kind == dec.ENDING:
            grid.widget(ttk.Label(grid.frame, text=SEEN_BY.format(n=entry.uses)
                                  if self._check_ran() else self._detail(entry)))
        grid.widget(ttk.Label(grid.frame, text=db.ENDINGS_HINT if entry.kind == dec.ENDING
                              else db.CHAPTERS_HINT, style="Hint.TLabel"), pady=(8, 0))

    # --- Transitions ------------------------------------------------------------------------

    def _mask_refs(self) -> list[str]:
        refs: list[str] = []
        for group in IMAGE_GROUPS:
            refs += self._project_refs(group)
        return refs

    def _transition_form(self, row: Row, key: tuple) -> None:
        if self._read_only(row, key):
            return
        entry = row.entry
        assert entry is not None and entry.decl is not None and entry.decl.values is not None
        body, form = self._new_body(key)
        self._title(body, entry.name)
        values = dict(entry.decl.values)
        kind = str(values["kind"])
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_TRANSITION))
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        self._name_row(grid, form, entry)
        f["kind"] = ChoiceField(grid.frame, list(dec.TRANSITION_KINDS.items()), kind, width=12,
                                on_change=lambda v: self._transition_kind(entry, str(v)))
        grid.row(LABEL_KIND, f["kind"])
        default = SECONDS_DEFAULTS[kind]
        seconds = values.get("seconds")
        f["seconds"] = NumberField(grid.frame, float(seconds if seconds is not None
                                                     else default), lo=0, hi=30, step=0.1,
                                   whole=False,
                                   on_change=lambda v: self._edit(entry, {"seconds": v}))
        grid.row(LABEL_SECONDS, f["seconds"], hint=SECONDS_HINT.format(seconds=f"{default:g}"))
        if kind == dec.FADE:
            f["color"] = ColorField(grid.frame, values.get("color"), allow_none=True,
                                    none_text=COLOR_DEFAULT, scale=self.scale,
                                    on_change=lambda v: self._edit(entry, {"color": v}))
            grid.row(LABEL_COLOR, f["color"])
        if kind == dec.MASK:
            refs = self._mask_refs()
            current = str(values.get("file"))
            if current not in refs:
                refs.insert(0, current)
            f["file"] = ChoiceField(grid.frame, [(r, show(r)) for r in refs], current,
                                    width=34,
                                    on_change=lambda v: self._edit(entry, {"file": v}))
            grid.row(LABEL_MASK, f["file"])
            f["soft"] = NumberField(grid.frame, float(values.get("soft", 0.1)), lo=0, hi=0.5,
                                    step=0.05, whole=False,
                                    on_change=lambda v: self._edit(entry, {"soft": v}))
            grid.row(LABEL_SOFT, f["soft"])
            f["reverse"] = ToggleField(grid.frame, REVERSE, bool(values.get("reverse")),
                                       on_change=lambda v: self._edit(entry, {"reverse": v}))
            grid.row(LABEL_REVERSE, f["reverse"])
        hint = ttk.Label(grid.frame, text=IN_SCRIPT.format(line=f"scene bg … with {entry.name}"),
                         style="Hint.TLabel")
        grid.widget(hint, pady=(6, 2))
        tryline = ttk.Frame(grid.frame)
        try_note = ttk.Label(tryline, text=TRY_HINT, style="Hint.TLabel",
                             wraplength=self._px(280), justify="left")
        f["try"] = ttk.Button(tryline, text=TRY_IT, style="Secondary.TButton",
                              command=lambda: self.try_transition(entry, try_note))
        f["try"].pack(anchor="w")
        try_note.pack(anchor="w", pady=(self._px(4), 0))
        f["try_note"] = try_note
        grid.widget(tryline, pady=(4, 4))
        grid.widget(self._uses_line(grid.frame, entry), pady=(4, 0))
        self._bottom(body, 2, entry, lambda: self._delete_decl(entry))

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            now = entry.decl.values
            now_kind = str(now["kind"])
            f["kind"].set(now_kind)
            secs = now.get("seconds")
            f["seconds"].set(float(secs if secs is not None else
                                   SECONDS_DEFAULTS[now_kind]))
            if "color" in f:
                f["color"].set(now.get("color"))
            if "file" in f:
                f["file"].set(now.get("file"))
                f["soft"].set(float(now.get("soft", 0.1)))
                f["reverse"].set(bool(now.get("reverse")))
            if "name" in f:
                f["name"].set(entry.name)
            hint.configure(text=IN_SCRIPT.format(line=f"scene bg … with {entry.name}"))

        form.update = update

    def try_background(self) -> str | None:
        """Try it's background: the first ``bg …`` picture (the project's ``images/``
        files, then the check's image names), else None (black)."""
        project = getattr(self.win, "project", None)
        names = [name for ref in (project.file_refs("images") if project is not None else ())
                 if (name := files.image_name_of(ref)) is not None]
        for entry in (getattr(self.win, "check_names", {}) or {}).get("image", ()):
            name = entry if isinstance(entry, str) else getattr(entry, "name", None)
            if isinstance(name, str):
                names.append(name)
        return stageat.first_background(names)

    def try_transition(self, entry: db.Entry, note: ttk.Label) -> None:
        """Try it (F47 P2-F): the transition as the form shows it now, onto the first
        background, in a small game window; a failure shows in ``note``."""
        values = self._now_values(entry)
        try:
            lines = stageat.transition_entry_lines(entry.name, values or {},
                                                   self.try_background())
        except (ValueError, KeyError, TypeError):
            note.configure(text=TRY_CANT)
            return
        note.configure(text=TRY_HINT)

        def problem(text: str) -> None:
            if note.winfo_exists():
                note.configure(text=text)

        trywiring.try_it(self.win).play(lines, problem)

    def _transition_kind(self, entry: db.Entry, kind: str) -> bool:
        change: dict[str, object] = {"kind": kind}
        if kind == dec.MASK:
            now = self._now_values(entry) or {}
            if not now.get("file"):
                refs = self._mask_refs()
                if not refs:
                    self._refuse_field(self.form.fields["kind"], MASK_NEEDS)
                    return False
                change["file"] = refs[0]
        return self._edit(entry, change)

    # --- Positions --------------------------------------------------------------------------

    def _positions_form(self, row: Row, key: tuple) -> None:
        body, form = self._new_body(key)
        title = self._title(body, "")
        f = form.fields
        stage = self.stage = StageCanvas(
            body, width=self._px(STAGE_PX), scale=self.scale,
            font=self.fonts.get("small"),
            on_pick=lambda name: self.select(f"o:{name}"),
            on_move=self.move_position)
        stage.widget.grid(row=1, column=0, sticky="w")
        self._stage_hint = ttk.Label(body, text=STAGE_HINT, style="Hint.TLabel",
                                     wraplength=self._px(STAGE_PX), justify="left")
        self._stage_hint.grid(row=2, column=0, sticky="w", pady=(self._px(4), 0))
        if not getattr(self, "_stage_fit_bound", False):
            self._stage_fit_bound = True
            self.form_frame.bind("<Configure>", lambda _e: self._fit_stage(), add="+")
        self._fit_stage()
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_POSITION))
        grid.frame.grid(row=3, column=0, sticky="ew", pady=(self._px(12), 0))
        state: dict[str, db.Entry] = {}

        def typed(axis: str, value: object) -> None:
            entry = state.get("entry")
            if entry is None or not entry.values or entry.values.get("x") is None:
                return
            x = float(value) if axis == "x" else float(entry.values["x"])
            y = float(value) if axis == "y" else float(entry.values["y"])
            self.move_position(entry.name, x, y)

        lo, hi = STAGE_COORD_RANGE
        f["x"] = NumberField(grid.frame, 0, lo=lo, hi=hi, width=8, whole=False,
                             on_change=lambda v: typed("x", v))
        grid.row(LABEL_X, f["x"], hint=X_HINT)
        f["y"] = NumberField(grid.frame, STAGE_H, lo=lo, hi=hi, width=8, whole=False,
                             on_change=lambda v: typed("y", v))
        grid.row(LABEL_Y, f["y"], hint=Y_HINT)
        hint = ttk.Label(grid.frame, text="", style="Hint.TLabel")
        grid.widget(hint, pady=(6, 2))
        uses = ttk.Frame(grid.frame)
        grid.widget(uses, pady=(2, 0))
        bottom = ttk.Frame(body)
        bottom.grid(row=4, column=0, sticky="ew", pady=(self._px(20), 0))

        def update(new: Row) -> None:
            entry = new.entry
            assert entry is not None
            state["entry"] = entry
            values = entry.values or {}
            title.configure(text=entry.name)
            points = [(e.name, float(e.values["x"]), float(e.values["y"]))
                      for e in self.positions or () if e.values and e.values.get("x") is not None]
            locked = [e.name for e in self.positions or () if not e.editable]
            stage.set_points(points, entry.name, locked)
            editable = values.get("x") is not None
            if editable:
                f["x"].set(float(values["x"]))
                f["y"].set(float(values["y"]))
            f["x"].enable(editable)
            f["y"].enable(editable)
            hint.configure(text=IN_SCRIPT.format(line=POSITION_IN_SCRIPT.format(
                name=entry.name)))
            for child in uses.winfo_children() + bottom.winfo_children():
                child.destroy()
            self._uses_line(uses, entry).pack(side="left")
            if not editable:
                ttk.Label(bottom, text=declplan.COMPLEX, wraplength=self._px(360)).pack(
                    side="left")
                ttk.Button(bottom, text=db.EDIT_AS_SCRIPT, style="Secondary.TButton",
                           command=self.open_config).pack(side="left",
                                                          padx=(self._px(8), 0))
            if values.get("builtin"):
                default = ttk.Button(bottom, text=fieldwidgets.USE_DEFAULT, style="Secondary.TButton",
                                     command=lambda: self.position_default(entry))
                default.pack(side="right")
                if not values.get("written"):
                    default.configure(state="disabled")
            else:
                ttk.Button(bottom, text=DELETE, style="Secondary.TButton",
                           command=lambda: self.delete_entry(
                               entry, lambda: self.delete_position(entry))).pack(side="right")
                if editable:
                    ttk.Button(bottom, text=RENAME_BUTTON, style="Secondary.TButton",
                               command=self.rename_selected).pack(
                                   side="right", padx=(0, self._px(8)))

        form.update = update
        update(row)

    def _fit_stage(self) -> None:
        """Size the stage to the form's width (at most ``STAGE_PX``)."""
        stage = self.stage
        if stage is None or not stage.widget.winfo_exists():
            return
        room = self.form_frame.winfo_width() - 2 * self._px(FORM_ROOM) - 2 * stage.pad
        if room <= 1:
            return
        width = max(self._px(STAGE_MIN_PX), min(self._px(STAGE_PX), room))
        stage.resize(width)
        hint = getattr(self, "_stage_hint", None)
        if hint is not None and hint.winfo_exists():
            hint.configure(wraplength=width + 2 * stage.pad)

    def _broken_positions_form(self) -> None:
        body, _form = self._new_body(("positions-broken",))
        fieldwidgets.fit_wrap(ttk.Label(body, text=CONFIG_BROKEN, justify="left"),
                              self._px(360)).grid(row=0, column=0, sticky="ew")
        ttk.Button(body, text=OPEN_CONFIG, style="Secondary.TButton",
                   command=self.open_config).grid(row=1, column=0, sticky="w",
                                                  pady=(self._px(8), 0))

    def open_config(self) -> None:
        self.win.jump_to(CONFIG_REF, 1)

    def _position_names(self) -> list[str]:
        return [e.name for e in self.positions or ()]

    def move_position(self, name: str, x: float, y: float) -> bool:
        """A marker dropped (or x, y typed): write ``[stage.positions] name``."""
        text = self._live_config()
        if text is None:
            show_error(self.root, STALE)
            return False
        lo, hi = STAGE_COORD_RANGE
        x, y = max(lo, min(hi, float(x))), max(lo, min(hi, float(y)))
        return self._write_toml(declplan.plan_position(text, name, x, y), select=f"o:{name}")

    def position_default(self, entry: db.Entry) -> bool:
        """Use default: a moved built-in position goes back to where the engine puts it."""
        text = self._live_config()
        if text is None:
            return False
        return self._write_toml(declplan.plan_position_remove(text, entry.name),
                                select=f"o:{entry.name}")

    def delete_position(self, entry: db.Entry) -> bool:
        text = self._live_config()
        if text is None:
            return False
        if ask(self.root, DELETE_POSITION_ASK.format(name=entry.name), DELETE_BUTTONS,
               escape=1, default=1) != 0:
            return False
        self.chosen[self.category] = None
        return self._write_toml(declplan.plan_position_remove(text, entry.name))

    # --- + New ------------------------------------------------------------------------------

    def _p2_new(self) -> bool:
        """+ New for a P2 category; False when the category has none."""
        category = self.category
        if category == db.CATEGORY_METER:
            self.show_meter_menu()                      # F62 round 2: presets first
        elif category == db.CATEGORY_ENDING:
            self.new_route()
        elif category == db.CATEGORY_TRANSITION:
            self.new_transition()
        elif category == db.CATEGORY_POSITION:
            self.new_position()
        elif category == db.CATEGORY_CODEX:
            menu = tk.Menu(self.root, tearoff=False)
            menu.add_command(label=NEW_TIP, command=lambda: self.new_codex(dec.TIP))
            menu.add_command(label=NEW_ITEM, command=lambda: self.new_codex(dec.ITEM))
            self.last_menu = menu
            button = self.new_button
            try:
                menu.tk_popup(button.winfo_rootx(),
                              button.winfo_rooty() + button.winfo_height())
            finally:
                menu.grab_release()
        else:
            return category in READ_ONLY
        return True

    def _new_decl(self, kind: str, category: str, question: str,
                  values: Callable[[str], Mapping[str, object]],
                  hint: Callable[[str], str]) -> bool:
        """Ask a name (or title), then add a ``kind`` declaration to database.vns."""
        self.texts = self._script_texts()
        taken = self._taken(kind)
        answer = ask_text(self.root, question, "", ok="Add",
                          hint=lambda shown: IN_SCRIPT.format(
                              line=hint(dec.script_name(shown, taken, kind)))
                          if shown.strip() else None)
        if answer is None or not answer[0].strip():
            return False
        shown = answer[0].strip()
        name = dec.script_name(shown, taken, kind)
        self.select_category(category)
        return self._write(declplan.plan_new(kind, name, values(shown), self.texts),
                           select=PREFIXES[kind] + name)

    def _script_texts(self) -> dict[str, str]:
        return self._read_texts()

    def new_meter(self) -> bool:
        low, high = NEW_METER_RANGE
        return self._new_decl(dec.METER, db.CATEGORY_METER, NEW_METER_ASK,
                              lambda _s: {"low": low, "high": high, "start": None},
                              lambda n: f"points {n} {low} to {high}")

    def new_codex(self, kind: str) -> bool:
        word = "tip" if kind == dec.TIP else "item"
        return self._new_decl(kind, db.CATEGORY_CODEX, NEW_CODEX_ASK.format(kind=word),
                              lambda shown: {"title": shown, "category": None,
                                             "image": None, "text": ()},
                              lambda n: f"unlock {word} {n}")

    def new_transition(self) -> bool:
        return self._new_decl(dec.TRANSITION, db.CATEGORY_TRANSITION, NEW_TRANSITION_ASK,
                              lambda _s: {"kind": dec.DISSOLVE, **dec.TRANSITION_DEFAULTS,
                                          "seconds": NEW_TRANSITION_SECONDS},
                              lambda n: f"scene bg … with {n}")

    def new_route(self) -> bool:
        """+ New route: the scene it starts at, then its title."""
        scenes = sorted(self.win._scene_names()) if hasattr(self.win, "_scene_names") else []
        self.texts = self._script_texts()
        routes = self._taken(dec.ROUTE)
        scenes = [s for s in scenes if s not in routes]
        if not scenes:
            show_error(self.root, NO_SCENES)
            return False
        label = pick_scene(self.root, scenes, title=NEW_ROUTE_PICK, ok="Next")
        if not label:
            return False
        answer = ask_text(self.root, NEW_ROUTE_ASK, label.replace("_", " ").title(), ok="Add")
        if answer is None or not answer[0].strip():
            return False
        self.select_category(db.CATEGORY_ENDING)
        return self._write(declplan.plan_new(dec.ROUTE, label, {"title": answer[0].strip(),
                                                                "until": ()}, self.texts),
                           select=f"r:{label}")

    def new_position(self) -> bool:
        text = self._live_config()
        if text is None or self.positions is None:
            show_error(self.root, CONFIG_BROKEN)
            return False
        taken = self._position_names()
        answer = ask_text(self.root, NEW_POSITION_ASK, "", ok="Add",
                          hint=lambda shown: IN_SCRIPT.format(line=POSITION_IN_SCRIPT.format(
                              name=dec.script_name(shown, taken, dec.POSITION)))
                          if shown.strip() else None)
        if answer is None or not answer[0].strip():
            return False
        name = dec.script_name(answer[0].strip(), taken, dec.POSITION)
        self.select_category(db.CATEGORY_POSITION)
        return self._write_toml(declplan.plan_position(text, name, STAGE_W / 2, STAGE_H,
                                                       taken=taken), select=f"o:{name}")


__all__ = ["ABOUT_MORE", "MoreCategories", "PREFIXES", "READ_ONLY", "Row"]
