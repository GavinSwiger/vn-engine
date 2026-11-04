"""Studio's minigame setup panels and the Minigame form (F47 ``01-design.md`` §4.6, §4.5;
``04-technical.md`` §16 W8; PR-F47-23, PR-F47-24; AC-F47-45, AC-F47-46's form).

Why this module exists: the bundled minigames take their data as Python literals in a
``define`` (``docs/minigames.md``), and the ``minigame`` line takes Python arguments. A
non-programmer gets panels instead, RPG Maker style:

- **Database ▸ Minigame data** (``attach``: one line in ``window._build_database_tab``): a
  list of the story's data sets by game (+ New) and the selected set's editor. Each change
  is written at once (one undo step), as the Database's forms do; a change the game would
  refuse stays on screen with "Not saved yet: {problem}" until it is fixed.
  - **Poem words**: a table, one row per word and one column per meter, spinners 0–3.
  - **Evidence**: the witness's statements in order; each statement's text and the codex
    items that contradict it (the testimony and its answer ``define``\\ s together).
  - **Phone chat**: the steps (message from the contact, from me, from someone else, time,
    reply point); a reply point's buttons (up to 4) with their follow-up steps, and
    "Don't reply".
  - **Puzzle room**: the background drawn on a 16:9 canvas; hotspots are drawn, dragged and
    resized there, and the side form sets each one's name tag, what a click does, its text,
    items, wrong-item text, "appears after" and picture; then the combine recipes.
- **The Minigame form** (Events, Insert ▸ Minigame): the installed games; the fields of the
  picked game's declared arguments; data-set pickers with **Set up…** and **New…**; and
  "Result goes to" a variable.

Logic is ``minigamedata``'s (models, plans, checks, the form's fields); this module only
shows and edits. Imports the standard library, ``tkinter`` and its own package; never
pygame.
"""

import ast
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from tkinter import ttk
from typing import Any

from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, declrename, files
from engine.tools.editor import minigamedata as mg
from engine.tools.editor.dialogs import ask, ask_text, show_error
from engine.tools.editor.scriptedit import STALE, FilePlan, LineEdit, Plan, Refuse
from engine.tools.editor.theme import ROLES, THEME
from engine.tools.editor.views import EmptyState, panel_header

# --- Texts (this step's; drafts for the narrative designer) ------------------------------------

CATEGORY = "minigame"
CATEGORY_TITLE = "Minigame data"
CATEGORY_AFTER = db.CATEGORY_META   # Minigame data goes before Character files
GROUP_TITLES: Mapping[str, str] = {
    mg.POEM: "Poem word lists", mg.TESTIMONY: "Evidence", mg.CHAT: "Phone chats",
    mg.ROOM: "Puzzle rooms", mg.GIFTS: "Gift tables", mg.TERMINAL: "Terminals"}
THING: Mapping[str, str] = {
    mg.POEM: "poem word list", mg.TESTIMONY: "evidence", mg.CHAT: "phone chat",
    mg.ROOM: "puzzle room", mg.GIFTS: "gift table", mg.TERMINAL: "terminal"}
NEW_BUTTON = "+ New"
NEW_ITEM = "New {thing}…"
NEW_ASK = "Name of the new {thing}:"
IN_SCRIPT = "In the script: define {name}"
EMPTY_TITLE = "No minigame data yet"
EMPTY_HINT = "Add one with + New."
ABOUT = ("Word lists, testimony, phone chats, puzzle rooms and gift tables for the minigames. "
         "Make one here, then pick it in a Minigame row in Events.")
PICK_ENTRY = "Pick something in the list to see it here."
NOT_SAVED = "Not saved yet: {problem}"
COMMENTS_ASK = ("{name} has comments in the script. Saving it from here rewrites it without "
                "them.")
COMMENTS_BUTTONS = ("Save without comments", "Cancel")
ANSWER_ONLY = "This answer goes with a testimony. Open the testimony under Evidence to edit it."
NO_ITEMS_FOR_EVIDENCE = ("Evidence needs an item the player can present. Add one in the "
                         "Database ▸ Codex ▸ Items first.")
USED_IN = "Used in {lines}"
NOT_USED = "Not used yet"
DELETE = "Delete"
RENAME = "Rename…"
RENAME_ASK = "New script name for {name}:"
DELETE_ASK = "Delete {name}? Its lines are removed from {ref}; Edit ▸ Undo there brings it back."
DELETE_BUTTONS = ("Delete", "Cancel")
DELETE_REFUSED = "{name} is used in {lines}, so it can't be deleted yet."
EDIT_AS_SCRIPT = db.EDIT_AS_SCRIPT
NO_SOUND = "None"                    # F57: the sound field's empty choice
AUDIO_PREFIX = "audio/"

POEM_HINT = ("Points each word gives to each meter, 0 to 3. A few words with no points make "
             "the choice less obvious.")
POEM_NO_METERS = ("No meters yet. Add them in the Database ▸ Meters, then give each word "
                  "points here.")
WORD_HEAD = "Word"
ADD_WORD = "+ Add word"
NEW_WORD_ASK = "The new word, as the player sees it:"
WORDS_COUNT = "{n} words"
PAGE_TEXT = "Words {first}–{last} of {n}"
REMOVE = "✕"

STATEMENTS = "Statements"
ADD_STATEMENT = "+ Add statement"
NEW_STATEMENT_ASK = "What does the witness say?"
STATEMENT_TEXT = "What the witness says"
CONTRADICTED_BY = "Contradicted by"
OTHER_ITEM = "Other item…"
OTHER_ITEM_ASK = "The item's script name (as in lock item):"
EVIDENCE_HINT = ("The player wins by presenting one of these items at this statement. Items "
                 "come from the Database ▸ Codex.")
NO_ITEMS = "No items yet."
UP, DOWN = "▲", "▼"

STEPS = "Steps"
ADD_STEP = "+ Add ▾"
ADD_BUTTON = "+ Add button"
MESSAGE = "Message"
SENDER = "From"
TIME_TEXT = "Time"
KIND = "Kind"
STORY_NAME = "Name in the story"
DONT_REPLY_TOGGLE = "Add a “Don't reply” button"
DONT_REPLY_WORDS = "Its words"
BUTTON_TEXT = "Button text"
ASK_HINT = "Each button is a reply the player can pick (up to 4)."
REPLY_HINT = "Add follow-up steps under the button with + Add ▾."
CONTACT_WORD = "Contact"
ME_WORD = "Me"
NEW_MESSAGE = "New message"
NEW_TIME = "12:00 PM"
NEW_REPLY = "New reply"

BACKGROUND = "Background"
CANVAS_HINT = ("Drag on the picture to draw a hotspot; drag one to move it, or its corners "
               "to resize. Arrow keys move the selected one, Shift+arrows resize it.")
NO_PICTURE = "No picture for {name}"
HOTSPOT = "Hotspot"
NO_HOTSPOT = "Pick a hotspot on the picture, or draw one."
NAME_TAG = "Name tag"
WHEN_CLICKED = "When clicked"
DOES: tuple[tuple[str, str], ...] = (
    ("look", "Shows its text"), ("take", "Gives an item"), ("use", "Needs an item"),
    ("exit", "Leaves the room"))
LOOK_TEXT = "Text"
TAKE_ITEM = "Item it gives"
USE_ITEMS = "Items that work"
NOPE_TEXT = "Wrong-item text"
AFTER = "Appears after"
ALWAYS = "Always there"
PICTURE = "Picture"
NO_PICTURE_CHOICE = "None"
PLACE = "Place on the screen (1280 × 720)"
PLACE_WORDS = ("X", "Y", "Width", "Height")
DELETE_HOTSPOT = "Delete hotspot"
RECIPES = "Combine recipes"
ADD_RECIPE = "+ Add recipe"
RECIPE_PLUS, RECIPE_MAKES = "+", "makes"
NEW_HOTSPOT_LABEL = "Hotspot {n}"
EXIT_LABEL = "Door"

# Gift tables (F54 §4.2).
CHARACTER = "Character"
ADD_CHARACTER = "+ Add character"
REMOVE_CHARACTER = "Remove character"
ADD_CHARACTER_ASK = "The character, as its meter is named (letters, digits and _):"
GIFT_HEADS = ("Gift", "Reaction", "Points", "What they say")
ANY_GIFT_TEXT = "Any other gift"
ADD_GIFT = "+ Add gift"
NO_GIFT_ITEMS = "No items yet. Add them in Database ▸ Codex, then pick the gifts here."
NEW_GIFT = ("liked", 1)               # a new gift's reaction and points

GAME = "Game"
SET_UP = "Set up…"
NEW_SET = "New…"
SKIPPABLE = "The player can skip it"
LINE_CAPTION = "This row's line"
OK, CANCEL, CLOSE = "OK", "Cancel", "Close"

# --- Sizes (px at 100 %) ------------------------------------------------------------------------

LIST_WIDTH = 240
PAD = 16
CANVAS_WIDTH = 640               # the room canvas (screen px, at least; 16:9 of 1280 × 720):
#                                  half the game's width, so a full-size background shows whole
HANDLE_PX = 8
MIN_DRAG_PX = 6                  # a smaller drag on the canvas is a click
NUDGE = 8                        # arrow keys move or resize by this many screen units
LABEL_COLUMN = 190               # the Minigame form's label column
PAGE_ROWS = 100                  # the poem table shows this many words at a time
POINTS_MAX = max(mg.POINTS_PICK)


def _lines_word(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


# --- What the story names ----------------------------------------------------------------------

class Lookups:
    """Names the panels offer: codex items, meters, variables and image names (with the ref
    that shows each one), read from the scripts and the last check."""

    def __init__(self, win: Any, texts: Mapping[str, str]) -> None:
        names = getattr(win, "check_names", {}) or {}
        decls = dec.scan(texts)
        self.items = [(e.name, e.shown) for e in db.codex_entries(decls, names)[dec.ITEM]]
        written = [d.name for d in decls if d.kind == dec.METER and d.name]
        self.meters = list(dict.fromkeys(written + [e.name for e in db.meter_entries(decls,
                                                                                     names)]))
        self.variables = list(db.variable_names(decls, names))
        # F55: declared tips (name, title) and the tip categories (the default's key is
        # ``codex_tips``), for the Coded note's pick-lists.
        self.tips = [(e.name, e.shown) for e in db.codex_entries(decls, names)[dec.TIP]]
        cats: list[str] = []
        for d in decls:
            if d.kind == dec.TIP:
                cat = (d.values or {}).get("category") or "codex_tips"
                if cat not in cats:
                    cats.append(str(cat))
        self.tip_categories = cats
        self.images: dict[str, str | None] = {}         # image name → ref (None: a colour)
        self.colors: dict[str, str] = {}
        project = getattr(win, "project", None)
        for ref in (project.file_refs("images") if project is not None else []):
            name = files.image_name_of(ref)
            if name:
                self.images.setdefault(name, ref)
        for decl in decls:
            if decl.kind == dec.COLOR:
                self.images.setdefault(decl.name, None)
                if decl.values:
                    self.colors[decl.name] = str(decl.values.get("color"))

    @property
    def item_names(self) -> list[str]:
        return [name for name, _ in self.items]

    def item_title(self, name: str) -> str:
        return next((shown for n, shown in self.items if n == name), name)

    @property
    def backgrounds(self) -> list[str]:
        return sorted((n for n in self.images if n.casefold().startswith("bg ")),
                      key=str.casefold)


# --- Reading and writing -----------------------------------------------------------------------

class Store:
    """The story's data sets, and writes through ``win.apply_plan`` (``minigamedata``'s
    plans, ``database.vns`` made first when a plan says so)."""

    def __init__(self, win: Any) -> None:
        self.win = win
        self.texts: dict[str, str] = {}
        self.sets: tuple[mg.DataSet, ...] = ()
        self.lookups = Lookups(win, {})

    def read(self) -> None:
        from engine.tools.editor.database import script_texts
        self.texts = script_texts(self.win)
        self.sets = mg.scan(self.texts)
        self.lookups = Lookups(self.win, self.texts)

    def find(self, kind: str, name: str) -> mg.DataSet | None:
        kinds = (mg.TESTIMONY, mg.ANSWER) if kind in (mg.TESTIMONY, mg.ANSWER) else (kind,)
        found = next((ds for ds in self.sets if ds.name == name and ds.kind in kinds), None)
        if found is None and kind == mg.ANSWER:
            found = mg.data_set(self.texts, name, mg.ANSWER)
        return found

    def answer_of(self, testimony: mg.DataSet) -> mg.DataSet | None:
        """The answer ``define`` that goes with ``testimony``: the one a Present evidence
        line passes with it, else ``<testimony>_answer``."""
        found = mg.answer_for(testimony, self.texts)
        return found if found is not None and found.model is not None else None

    def answer_names(self) -> set[str]:
        return {a.name for t in self.sets if t.kind == mg.TESTIMONY
                for a in (self.answer_of(t),) if a is not None}

    def uses(self) -> dict[str, int]:
        """Data set name → how many ``minigame`` lines pass it."""
        out: dict[str, int] = {}
        for _ref, _line, call in mg.calls(self.texts):
            named = {part.strip() for _k, v in call.args for part in v.split("|")}
            for name in named:
                out[name] = out.get(name, 0) + 1
        return out

    def model_of(self, ds: mg.DataSet) -> object:
        """The panel's model: an ``Evidence`` for a testimony (with its answer)."""
        if ds.kind == mg.TESTIMONY:
            answer = self.answer_of(ds)
            return mg.evidence_of(ds.model, answer.model if answer else None)  # type: ignore
        return ds.model

    def apply(self, plan: mg.DataPlan | Refuse | None) -> bool:
        if plan is None:
            return True
        if isinstance(plan, Refuse):
            show_error(self.win.root, plan.text)
            return False
        if plan.create is not None:
            folder, name = plan.create.rsplit("/", 1)
            made = files.new_script(self.win.paths, folder, name, text=declplan.DATABASE_TEXT)
            if isinstance(made, files.Refusal):
                show_error(self.win.root, made.text)
                return False
            self.win.refresh_project()
        if not self.win.apply_plan(plan.plan, lambda texts: mg.verify(plan, texts)):
            show_error(self.win.root, STALE)
            return False
        self.win._update_marks()
        self.read()
        return True

    def save(self, kind: str, name: str, model: object) -> bool | str:
        """Write ``model`` over the data set ``name``: True when written (or unchanged),
        the problem's text when the game would refuse it, False when it couldn't be."""
        found = mg.problem(kind, model)
        if found is not None:
            return found
        self.read()
        ds = self.find(kind, name)
        if ds is None or ds.model is None:
            show_error(self.win.root, STALE)
            return False
        if kind == mg.TESTIMONY:
            answer = self.answer_of(ds)
            plan = mg.plan_evidence(ds, answer, model, self.texts)  # type: ignore[arg-type]
            comments = ds.comments or (answer is not None and answer.comments)
        else:
            plan = mg.plan_edit(ds, model, self.texts)
            comments = ds.comments
        if plan is None:
            return True
        if comments and not isinstance(plan, Refuse):
            if ask(self.win.root, COMMENTS_ASK.format(name=name), COMMENTS_BUTTONS,
                   escape=1, default=1) != 0:
                return False
        return self.apply(plan)

    def create(self, kind: str, name: str, model: object) -> bool:
        self.read()
        return self.apply(mg.plan_new(kind, name, model, self.texts))

    def delete(self, ds: mg.DataSet) -> bool:
        """Remove ``ds``'s lines (and an evidence's answer), one undo step per file."""
        self.read()
        sets = [ds] + ([a] if ds.kind == mg.TESTIMONY and (a := self.answer_of(ds)) else [])
        by_ref: dict[str, list[mg.DataSet]] = {}
        for one in sets:
            by_ref.setdefault(one.ref, []).append(one)
        plan = Plan(f"Delete {ds.name}", tuple(
            FilePlan(ref, (), tuple(LineEdit(s.first, s.last, ()) for s in sorted(
                group, key=lambda s: -s.first))) for ref, group in by_ref.items()))

        def verify(texts: Mapping[str, str]) -> bool:
            for one in sets:
                lines = texts.get(one.ref, "").split("\n")
                if tuple(lines[one.first - 1:one.last]) != one.lines:
                    return False
            return True
        if not self.win.apply_plan(plan, verify):
            show_error(self.win.root, STALE)
            return False
        self.win._update_marks()
        self.read()
        return True


def starter(kind: str, lookups: Lookups) -> object | None:
    """A new data set's first model: one the game accepts, for the author to change."""
    if kind == mg.POEM:
        meters = lookups.meters
        first = ((meters[0], 1),) if meters else ()
        return mg.PoemWords((mg.PoemWord("sunshine", first), mg.PoemWord("pencil")))
    if kind == mg.TESTIMONY:
        items = lookups.item_names
        if not items:
            return None
        return mg.Evidence((mg.Statement("door", "The door was locked all night.",
                                         (items[0],)),))
    if kind == mg.CHAT:
        return (mg.Step(mg.FROM_CONTACT, "hi!"), mg.Step(mg.FROM_ME, "hey"))  # a {"me": …}:
        #                                         so the scan knows it is a chat by its shape
    if kind == mg.TERMINAL:                                          # F56 (Q2)
        from engine.tools.editor import terminaldata
        return terminaldata.starter()
    if kind == mg.GIFTS:
        items = lookups.item_names
        rows = (mg.GiftRow(items[0], *NEW_GIFT),) if items else ()
        meters = lookups.meters
        return mg.GiftTable((mg.GiftSection(meters[0] if meters else "hana", rows),))
    backgrounds = lookups.backgrounds
    return mg.Room(backgrounds[0] if backgrounds else "bg room",
                   (mg.Hotspot("door", (1040, 200, 200, 400), EXIT_LABEL, exit=True),))


# --- Small widgets -----------------------------------------------------------------------------

class _Combo:
    """An editable drop-down that commits on a pick, Enter or focus-out (``on_change(text)``)."""

    def __init__(self, parent: tk.Misc, values: Sequence[str], value: str, *,
                 on_change: Callable[[str], object], width: int = 18,
                 readonly: bool = False) -> None:
        self.var = tk.StringVar(master=parent, value=value)
        self.value = value
        self.on_change = on_change
        self.widget = self.box = ttk.Combobox(parent, textvariable=self.var, values=list(values),
                                              width=width,
                                              state="readonly" if readonly else "normal")
        self.box.bind("<<ComboboxSelected>>", lambda _e: self.commit(), add="+")
        for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
            self.box.bind(key, lambda _e: self.commit(), add="+")

    def set(self, value: str) -> None:
        self.value = value
        self.var.set(value)

    def commit(self) -> None:
        text = self.var.get().strip()
        if text != self.value:
            self.value = text
            self.on_change(text)


class _Entry:
    """A one-line entry committing on Enter or focus-out; Escape puts the value back."""

    def __init__(self, parent: tk.Misc, value: str, *, on_change: Callable[[str], object],
                 width: int = 30) -> None:
        self.var = tk.StringVar(master=parent, value=value)
        self.value = value
        self.on_change = on_change
        self.widget = self.entry = ttk.Entry(parent, textvariable=self.var, width=width)
        for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
            self.entry.bind(key, lambda _e: self.commit(), add="+")
        self.entry.bind("<Escape>", lambda _e: self.var.set(self.value), add="+")

    def set(self, value: str) -> None:
        self.value = value
        self.var.set(value)

    def commit(self) -> None:
        text = self.var.get()
        if text != self.value:
            self.value = text
            self.on_change(text)


class _Message:
    """A few lines of text (a chat message: up to 4 line breaks), committing on focus-out
    or Ctrl+Enter."""

    def __init__(self, parent: tk.Misc, value: str, *, on_change: Callable[[str], object],
                 width: int = 40, height: int = 3) -> None:
        self.value = value
        self.on_change = on_change
        self.widget = self.text = tk.Text(
            parent, width=width, height=height, wrap="word", undo=True,
            background=THEME["input.background"], foreground=THEME["input.foreground"],
            insertbackground=THEME["editor.cursor"], relief="flat", highlightthickness=1,
            highlightbackground=THEME["input.border"], highlightcolor=ROLES["focus"])
        self.text.insert("1.0", value)
        self.text.bind("<FocusOut>", lambda _e: self.commit(), add="+")
        self.text.bind("<Control-Return>", lambda _e: (self.commit(), "break")[1])

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        self.value = value
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)

    def commit(self) -> None:
        text = self.get()
        if text != self.value:
            self.value = text
            self.on_change(text)


class _Checklist:
    """Check boxes for a set of names (``choices``: (name, shown)); ``on_change(names)`` with
    the ticked names in ``choices`` order, then any ticked name not among them."""

    def __init__(self, parent: tk.Misc, choices: Sequence[tuple[str, str]],
                 ticked: Sequence[str], *, on_change: Callable[[tuple[str, ...]], object],
                 empty: str = NO_ITEMS, columns: int = 2) -> None:
        self.widget = self.frame = ttk.Frame(parent)
        self.on_change = on_change
        names = [n for n, _ in choices]
        self.choices = list(choices) + [(n, n) for n in ticked if n not in names]
        self.vars: dict[str, tk.BooleanVar] = {}
        for i, (name, shown) in enumerate(self.choices):
            var = self.vars[name] = tk.BooleanVar(master=parent, value=name in ticked)
            ttk.Checkbutton(self.frame, text=shown, variable=var,
                            command=self._changed).grid(row=i // columns, column=i % columns,
                                                        sticky="w", padx=(0, 12))
        if not self.choices:
            ttk.Label(self.frame, text=empty, style="Hint.TLabel").grid(row=0, column=0,
                                                                       sticky="w")

    def ticked(self) -> tuple[str, ...]:
        return tuple(n for n, _ in self.choices if self.vars[n].get())

    def tick(self, name: str, on: bool = True) -> None:
        """Tick ``name`` as the author would (tests, keyboard helpers)."""
        self.vars[name].set(on)
        self._changed()

    def _changed(self) -> None:
        self.on_change(self.ticked())


# --- The editors -------------------------------------------------------------------------------

class Editor:
    """One data set's editor. ``model`` is what it shows; ``changed(model)`` writes it (or
    shows why it can't yet). ``pending``: a change on screen that isn't written."""

    kind = ""

    def __init__(self, host: "EditorHost", parent: tk.Misc, ds: mg.DataSet,
                 model: object) -> None:
        self.host = host
        self.ds = ds
        self.model = model
        self.pending = False
        self.px = host.px
        self.frame = ttk.Frame(parent)
        self.status = ttk.Label(self.frame, text="", foreground=ROLES["warning"],
                                wraplength=self.px(560), justify="left")

    @property
    def lookups(self) -> Lookups:
        return self.host.store.lookups

    def say(self, text: str) -> None:
        self.status.configure(text=text)

    def changed(self, model: object, *, rebuild: bool = False) -> bool:
        """Take ``model``: write it now when the game would accept it."""
        self.model = model
        result = self.host.store.save(self.kind, self.ds.name, model)
        if isinstance(result, str):
            self.pending = True
            self.say(NOT_SAVED.format(problem=result))
        elif result:
            self.pending = False
            self.say("")
            fresh = self.host.store.find(self.kind, self.ds.name)
            if fresh is not None:
                self.ds = fresh
            self.host.written(self)
        else:
            self.reload()
            return False
        if rebuild:
            self.rebuild()
        return result is True

    def reload(self) -> None:
        """Show the data as the script holds it now (a write was refused or cancelled)."""
        self.host.store.read()
        fresh = self.host.store.find(self.kind, self.ds.name)
        if fresh is not None and fresh.model is not None:
            self.ds = fresh
            self.model = self.host.store.model_of(fresh)
        self.pending = False
        self.say("")
        self.rebuild()

    def rebuild(self) -> None:
        raise NotImplementedError


# Poem words ----------------------------------------------------------------------------------

class PoemEditor(Editor):
    """The word table: a word per row, a meter per column, a 0–3 spinner per cell."""

    kind = mg.POEM

    def __init__(self, host: "EditorHost", parent: tk.Misc, ds: mg.DataSet,
                 model: object) -> None:
        super().__init__(host, parent, ds, model)
        px = self.px
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x")
        self.count = ttk.Label(bar, text="")
        self.count.pack(side="left")
        self.add_button = ttk.Button(bar, text=ADD_WORD, style="Secondary.TButton",
                                     command=self.add_word)
        self.add_button.pack(side="right")
        self.hint = ttk.Label(self.frame, text=POEM_HINT, style="Hint.TLabel",
                              wraplength=px(560), justify="left")
        self.hint.pack(anchor="w", pady=(px(8), px(8)))
        self.status.pack(anchor="w")
        self.page_bar = ttk.Frame(self.frame)
        self.prev = ttk.Button(self.page_bar, text="◀", width=3, style="Secondary.TButton",
                               command=lambda: self.turn(-1))
        self.prev.pack(side="left")
        self.page_text = ttk.Label(self.page_bar, text="")
        self.page_text.pack(side="left", padx=px(8))
        self.next = ttk.Button(self.page_bar, text="▶", width=3, style="Secondary.TButton",
                               command=lambda: self.turn(1))
        self.next.pack(side="left")
        self.table = ttk.Frame(self.frame)
        self.table.pack(anchor="w", fill="x", pady=(px(4), 0))
        self.page = 0
        self.cells: dict[tuple[int, str], tk.StringVar] = {}
        self.words: dict[int, _Entry] = {}
        self.rebuild()

    @property
    def words_model(self) -> mg.PoemWords:
        return self.model                                   # type: ignore[return-value]

    def meters(self) -> tuple[str, ...]:
        return mg.poem_meters(self.words_model, self.lookups.meters)

    def rebuild(self) -> None:
        for child in self.table.winfo_children():
            child.destroy()
        self.cells, self.words = {}, {}
        words = self.words_model.words
        n = len(words)
        self.count.configure(text=WORDS_COUNT.format(n=n))
        pages = max(1, -(-n // PAGE_ROWS))
        self.page = min(self.page, pages - 1)
        if pages > 1:
            first = self.page * PAGE_ROWS
            self.page_text.configure(text=PAGE_TEXT.format(
                first=first + 1, last=min(n, first + PAGE_ROWS), n=n))
            self.prev.configure(state="normal" if self.page else "disabled")
            self.next.configure(state="normal" if self.page < pages - 1 else "disabled")
            self.page_bar.pack(anchor="w", before=self.table, pady=(0, self.px(4)))
        else:
            self.page_bar.pack_forget()
        meters = self.meters()
        self.hint.configure(text=POEM_HINT if meters else POEM_NO_METERS)
        pad = self.px(6)
        ttk.Label(self.table, text=WORD_HEAD.upper(), style="Caption.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, pad))
        for c, meter in enumerate(meters, start=1):
            ttk.Label(self.table, text=meter.upper(), style="Caption.TLabel").grid(
                row=0, column=c, sticky="w", padx=(0, pad))
        start = self.page * PAGE_ROWS
        for r, index in enumerate(range(start, min(n, start + PAGE_ROWS)), start=1):
            row = words[index]
            word = _Entry(self.table, row.word, width=18,
                          on_change=lambda text, i=index: self.set_word(i, text))
            word.widget.grid(row=r, column=0, sticky="w", padx=(0, pad), pady=1)
            self.words[index] = word
            for c, meter in enumerate(meters, start=1):
                value = mg.poem_points(row, meter)
                var = tk.StringVar(master=self.table, value=str(value))
                spin = ttk.Spinbox(self.table, from_=0, to=max(POINTS_MAX, value),
                                   increment=1, width=4, textvariable=var,
                                   command=lambda i=index, m=meter: self.set_points(i, m))
                for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
                    spin.bind(key, lambda _e, i=index, m=meter: self.set_points(i, m),
                              add="+")
                spin.grid(row=r, column=c, sticky="w", padx=(0, pad), pady=1)
                self.cells[(index, meter)] = var
            ttk.Button(self.table, text=REMOVE, width=3, style="Ghost.TButton",
                       command=lambda i=index: self.remove(i)).grid(
                row=r, column=len(meters) + 1, sticky="w")

    def turn(self, step: int) -> None:
        self.page += step
        self.rebuild()

    def _replace(self, index: int, row: mg.PoemWord) -> None:
        words = list(self.words_model.words)
        if words[index] == row:
            return
        words[index] = row
        self.changed(mg.PoemWords(tuple(words)))

    def set_word(self, index: int, text: str) -> None:
        if index < len(self.words_model.words):
            self._replace(index, mg.PoemWord(text.strip(),
                                             self.words_model.words[index].scores))

    def set_points(self, index: int, meter: str) -> None:
        var = self.cells.get((index, meter))
        if var is None or index >= len(self.words_model.words):
            return
        row = self.words_model.words[index]
        try:
            points = int(var.get().strip())
        except ValueError:
            points = -1
        if not 0 <= points <= mg.SCORE_MAX:
            var.set(str(mg.poem_points(row, meter)))
            return
        self._replace(index, mg.poem_set(row, meter, points))

    def add_word(self) -> None:
        answer = ask_text(self.host.root, NEW_WORD_ASK, "", ok="Add")
        if answer is None or not answer[0].strip():
            return
        words = self.words_model.words + (mg.PoemWord(answer[0].strip()),)
        self.page = (len(words) - 1) // PAGE_ROWS
        self.changed(mg.PoemWords(words), rebuild=True)

    def remove(self, index: int) -> None:
        words = list(self.words_model.words)
        del words[index]
        self.changed(mg.PoemWords(tuple(words)), rebuild=True)


# Evidence ------------------------------------------------------------------------------------

class EvidenceEditor(Editor):
    """The statements, in order, each with its text and the items that contradict it."""

    kind = mg.TESTIMONY

    def __init__(self, host: "EditorHost", parent: tk.Misc, ds: mg.DataSet,
                 model: object) -> None:
        super().__init__(host, parent, ds, model)
        px = self.px
        head = ttk.Frame(self.frame)
        head.pack(fill="x")
        ttk.Label(head, text=STATEMENTS.upper(), style="Caption.TLabel").pack(side="left")
        ttk.Button(head, text=ADD_STATEMENT, style="Secondary.TButton",
                   command=self.add_statement).pack(side="right")
        self.status.pack(anchor="w", pady=(px(4), 0))
        middle = ttk.Frame(self.frame)
        middle.pack(fill="x", pady=(px(6), 0))
        self.tree = ttk.Treeview(middle, columns=("items",), show="tree headings",
                                 selectmode="browse", height=7, style="Surface.Treeview")
        self.tree.heading("#0", text=STATEMENT_TEXT)
        self.tree.heading("items", text=CONTRADICTED_BY)
        self.tree.column("#0", width=px(360), stretch=True)
        self.tree.column("items", width=px(160), stretch=False)
        self.tree.pack(side="left", fill="x", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_detail(), add="+")
        self.tree.bind("<Delete>", lambda _e: (self.remove(), "break")[1])
        moves = ttk.Frame(middle)
        moves.pack(side="left", anchor="n", padx=(px(6), 0))
        for text, step in ((UP, -1), (DOWN, 1)):
            ttk.Button(moves, text=text, width=3, style="Secondary.TButton",
                       command=lambda s=step: self.move(s)).pack(pady=(0, px(4)))
        ttk.Button(moves, text=DELETE, style="Secondary.TButton",
                   command=self.remove).pack(pady=(px(8), 0))
        self.detail = ttk.Frame(self.frame)
        self.detail.pack(fill="x", pady=(px(12), 0))
        self.text: _Entry | None = None
        self.items: _Checklist | None = None
        self.rebuild()

    @property
    def evidence(self) -> mg.Evidence:
        return self.model                                   # type: ignore[return-value]

    def selected(self) -> int | None:
        chosen = self.tree.selection()
        return int(chosen[0]) if chosen else None

    def rebuild(self, select: int | None = None) -> None:
        keep = self.selected() if select is None else select
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.evidence.statements):
            self.tree.insert("", "end", iid=str(i), text=f"{i + 1}.  {s.text}", values=(
                ", ".join(self.lookups.item_title(n) for n in s.items),))
        count = len(self.evidence.statements)
        if count:
            pick = min(keep if keep is not None else 0, count - 1)
            self.tree.selection_set(str(pick))
            self.tree.focus(str(pick))
        self.show_detail()

    def show_detail(self) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        index = self.selected()
        if index is None or index >= len(self.evidence.statements):
            return
        s = self.evidence.statements[index]
        px = self.px
        self.detail.columnconfigure(1, weight=1)
        ttk.Label(self.detail, text=STATEMENT_TEXT).grid(row=0, column=0, sticky="w",
                                                         padx=(0, px(12)))
        self.text = _Entry(self.detail, s.text, width=56,
                           on_change=lambda t, i=index: self._set(i, text=t.strip()))
        self.text.widget.grid(row=0, column=1, sticky="ew", pady=px(3))
        ttk.Label(self.detail, text=CONTRADICTED_BY).grid(row=1, column=0, sticky="nw",
                                                          padx=(0, px(12)), pady=px(3))
        box = ttk.Frame(self.detail)
        box.grid(row=1, column=1, sticky="w", pady=px(3))
        self.items = _Checklist(box, self.lookups.items, s.items,
                                on_change=lambda names, i=index: self._set(i, items=names))
        self.items.widget.pack(anchor="w")
        ttk.Button(box, text=OTHER_ITEM, style="Ghost.TButton",
                   command=lambda i=index: self.other_item(i)).pack(anchor="w")
        ttk.Label(self.detail, text=EVIDENCE_HINT, style="Hint.TLabel", wraplength=px(480),
                  justify="left").grid(row=2, column=1, sticky="w", pady=(px(4), 0))
        ttk.Label(self.detail, text=dec_name_line(s.key), style="Hint.TLabel").grid(
            row=3, column=1, sticky="w")

    def _set(self, index: int, **change: object) -> None:
        statements = list(self.evidence.statements)
        statements[index] = replace(statements[index], **change)   # type: ignore[arg-type]
        self.changed(replace(self.evidence, statements=tuple(statements)))
        self._row_text(index)

    def _row_text(self, index: int) -> None:
        if self.tree.exists(str(index)) and index < len(self.evidence.statements):
            s = self.evidence.statements[index]
            self.tree.item(str(index), text=f"{index + 1}.  {s.text}", values=(
                ", ".join(self.lookups.item_title(n) for n in s.items),))

    def other_item(self, index: int) -> None:
        answer = ask_text(self.host.root, OTHER_ITEM_ASK, "", ok="Add")
        if answer is None or not answer[0].strip():
            return
        s = self.evidence.statements[index]
        if answer[0].strip() not in s.items:
            self._set(index, items=s.items + (answer[0].strip(),))
            self.show_detail()

    def add_statement(self) -> None:
        answer = ask_text(self.host.root, NEW_STATEMENT_ASK, "", ok="Add")
        if answer is None or not answer[0].strip():
            return
        text = answer[0].strip()
        key = mg.slug(text, [s.key for s in self.evidence.statements], "line")
        statements = self.evidence.statements + (mg.Statement(key, text),)
        self.changed(replace(self.evidence, statements=statements))
        self.rebuild(select=len(statements) - 1)

    def move(self, step: int) -> None:
        index = self.selected()
        statements = list(self.evidence.statements)
        if index is None or not 0 <= index + step < len(statements):
            return
        statements[index], statements[index + step] = statements[index + step], statements[index]
        self.changed(replace(self.evidence, statements=tuple(statements)))
        self.rebuild(select=index + step)

    def remove(self) -> None:
        index = self.selected()
        if index is None:
            return
        statements = list(self.evidence.statements)
        del statements[index]
        self.changed(replace(self.evidence, statements=tuple(statements)))
        self.rebuild(select=max(0, index - 1))


def dec_name_line(name: str) -> str:
    return f"In the script: {name}"


# Phone chat ----------------------------------------------------------------------------------

PLAIN_KINDS: tuple[tuple[str, str], ...] = tuple(
    (k, mg.STEP_TITLES[k]) for k in (mg.FROM_CONTACT, mg.FROM_ME, mg.FROM_OTHER, mg.TIME))


def step_text(step: mg.Step) -> str:
    one = step.text.replace("\n", " ⏎ ")
    if step.kind == mg.TIME:
        return f"— {one} —"
    who = {mg.FROM_CONTACT: CONTACT_WORD, mg.FROM_ME: ME_WORD}.get(step.kind, step.sender)
    return f"{who}: {one}"


class ChatEditor(Editor):
    """The chat's steps as a tree: a reply point holds its buttons, a button its follow-ups.
    Ids: ``s<i>`` a step, ``s<i>.r<j>`` a button, ``s<i>.r<j>.f<k>`` a follow-up."""

    kind = mg.CHAT

    def __init__(self, host: "EditorHost", parent: tk.Misc, ds: mg.DataSet,
                 model: object) -> None:
        super().__init__(host, parent, ds, model)
        px = self.px
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x")
        ttk.Label(bar, text=STEPS.upper(), style="Caption.TLabel").pack(side="left")
        self.add_menu_button = ttk.Button(bar, text=ADD_STEP, style="Secondary.TButton",
                                          command=self.add_menu)
        self.add_menu_button.pack(side="right")
        self.add_button_button = ttk.Button(bar, text=ADD_BUTTON, style="Secondary.TButton",
                                            command=self.add_reply)
        self.add_button_button.pack(side="right", padx=(0, px(8)))
        self.status.pack(anchor="w", pady=(px(4), 0))
        middle = ttk.Frame(self.frame)
        middle.pack(fill="x", pady=(px(6), 0))
        self.tree = ttk.Treeview(middle, show="tree", selectmode="browse", height=16,
                                 style="Surface.Treeview")
        self.tree.column("#0", width=px(420), stretch=True)
        self.tree.pack(side="left", fill="x", expand=True)
        self.tree.tag_configure("ask", foreground=THEME["map.minigame"])
        self.tree.tag_configure("muted", foreground=THEME["muted"])
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_detail(), add="+")
        self.tree.bind("<Delete>", lambda _e: (self.remove(), "break")[1])
        moves = ttk.Frame(middle)
        moves.pack(side="left", anchor="n", padx=(px(6), 0))
        for text, step in ((UP, -1), (DOWN, 1)):
            ttk.Button(moves, text=text, width=3, style="Secondary.TButton",
                       command=lambda s=step: self.move(s)).pack(pady=(0, px(4)))
        ttk.Button(moves, text=DELETE, style="Secondary.TButton",
                   command=self.remove).pack(pady=(px(8), 0))
        self.detail = ttk.Frame(self.frame)
        self.detail.pack(fill="x", pady=(px(12), 0))
        self.fields: dict[str, Any] = {}
        self.last_menu: tk.Menu | None = None
        self.rebuild()

    @property
    def steps(self) -> tuple[mg.ChatStep, ...]:
        return self.model                                   # type: ignore[return-value]

    # Where things are.
    @staticmethod
    def parse(iid: str) -> tuple[int, int | None, int | None]:
        parts = [int(p[1:]) for p in iid.split(".")]
        return parts[0], parts[1] if len(parts) > 1 else None, \
            parts[2] if len(parts) > 2 else None

    def selected(self) -> str | None:
        chosen = self.tree.selection()
        return chosen[0] if chosen else None

    def select(self, iid: str) -> None:
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self.show_detail()

    def rebuild(self, select: str | None = None) -> None:
        keep = select or self.selected()
        self.tree.delete(*self.tree.get_children())
        for i, step in enumerate(self.steps):
            if isinstance(step, mg.AskStep):
                self.tree.insert("", "end", iid=f"s{i}", open=True, tags=("ask",),
                                 text=f"{mg.STEP_TITLES[mg.ASK]}: {step.name}")
                for j, reply in enumerate(step.replies):
                    self.tree.insert(f"s{i}", "end", iid=f"s{i}.r{j}", open=True,
                                     text=f"[ {reply.text} ]")
                    for k, after in enumerate(reply.follow):
                        self.tree.insert(f"s{i}.r{j}", "end", iid=f"s{i}.r{j}.f{k}",
                                         text=step_text(after))
                if step.ignore not in (None, False):
                    words = step.ignore if isinstance(step.ignore, str) else mg.DONT_REPLY
                    self.tree.insert(f"s{i}", "end", iid=f"s{i}.x", text=f"[ {words} ]",
                                     tags=("muted",))
            else:
                self.tree.insert("", "end", iid=f"s{i}", text=step_text(step))
        if keep and self.tree.exists(keep):
            self.select(keep)
        elif self.steps:
            self.select("s0")
        else:
            self.show_detail()

    def _set_steps(self, steps: Sequence[mg.ChatStep], select: str | None = None,
                   rebuild: bool = True) -> None:
        self.changed(tuple(steps))
        if rebuild:
            self.rebuild(select)

    def show_detail(self) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        self.fields = {}
        iid = self.selected()
        self.add_button_button.configure(state="disabled")
        if iid is None:
            return
        if iid.endswith(".x"):
            iid = iid[:-2]
        i, j, k = self.parse(iid)
        step = self.steps[i]
        px = self.px
        grid = self.detail
        grid.columnconfigure(1, weight=1)
        rows = 0

        def row(label: str, widget: tk.Widget, sticky: str = "w") -> None:
            nonlocal rows
            ttk.Label(grid, text=label).grid(row=rows, column=0, sticky="nw",
                                             padx=(0, px(12)), pady=px(3))
            widget.grid(row=rows, column=1, sticky=sticky, pady=px(3))
            rows += 1

        if isinstance(step, mg.AskStep):
            self.add_button_button.configure(
                state="normal" if len(step.replies) < mg.REPLIES_MAX else "disabled")
            if j is None:
                name = _Entry(grid, step.name, width=24,
                              on_change=lambda t: self._ask(i, name=t.strip()))
                row(STORY_NAME, name.widget)
                on = step.ignore not in (None, False)
                toggle_var = tk.BooleanVar(master=grid, value=on)
                words = _Entry(grid, step.ignore if isinstance(step.ignore, str) else "",
                               width=24, on_change=lambda t: self._ask(
                                   i, ignore=t.strip() or True))
                toggle = ttk.Checkbutton(grid, text=DONT_REPLY_TOGGLE, variable=toggle_var,
                                         command=lambda: self._ask(
                                             i, ignore=(words.value.strip() or True)
                                             if toggle_var.get() else None))
                row("", toggle)
                row(DONT_REPLY_WORDS, words.widget)
                words.entry.configure(state="normal" if on else "disabled")
                ttk.Label(grid, text=ASK_HINT, style="Hint.TLabel").grid(
                    row=rows, column=1, sticky="w")
                self.fields = {"name": name, "ignore": toggle_var, "words": words}
                return
            reply = step.replies[j]
            if k is None:
                text = _Entry(grid, reply.text, width=40,
                              on_change=lambda t: self._reply(i, j, text=t.strip()))
                row(BUTTON_TEXT, text.widget, "ew")
                key = _Entry(grid, reply.key, width=24,
                             on_change=lambda t: self._reply(i, j, key=t.strip()))
                row(STORY_NAME, key.widget)
                ttk.Label(grid, text=REPLY_HINT, style="Hint.TLabel").grid(
                    row=rows, column=1, sticky="w")
                self.fields = {"text": text, "key": key}
                return
            plain = reply.follow[k]
        else:
            plain = step
        kinds = PLAIN_KINDS
        kind = _Combo(grid, [t for _k, t in kinds], mg.STEP_TITLES[plain.kind], readonly=True,
                      width=26, on_change=lambda t: self._plain(
                          iid, kind=next(k_ for k_, t_ in kinds if t_ == t)))
        row(KIND, kind.widget)
        self.fields["kind"] = kind
        if plain.kind == mg.FROM_OTHER:
            sender = _Entry(grid, plain.sender, width=24,
                            on_change=lambda t: self._plain(iid, sender=t.strip()))
            row(SENDER, sender.widget)
            self.fields["sender"] = sender
        if plain.kind == mg.TIME:
            text: Any = _Entry(grid, plain.text, width=16,
                               on_change=lambda t: self._plain(iid, text=t.strip()))
            row(TIME_TEXT, text.widget)
        else:
            text = _Message(grid, plain.text, width=48,
                            on_change=lambda t: self._plain(iid, text=t.strip()))
            row(MESSAGE, text.widget, "ew")
        self.fields["text"] = text

    # Changes.
    def _ask(self, i: int, **change: object) -> None:
        steps = list(self.steps)
        steps[i] = replace(steps[i], **change)                      # type: ignore[arg-type]
        self._set_steps(steps, f"s{i}", rebuild="ignore" in change)
        if "name" in change and self.tree.exists(f"s{i}"):
            self.tree.item(f"s{i}", text=f"{mg.STEP_TITLES[mg.ASK]}: {change['name']}")

    def _reply(self, i: int, j: int, **change: object) -> None:
        steps = list(self.steps)
        ask_step = steps[i]
        assert isinstance(ask_step, mg.AskStep)
        replies = list(ask_step.replies)
        replies[j] = replace(replies[j], **change)                  # type: ignore[arg-type]
        steps[i] = replace(ask_step, replies=tuple(replies))
        self._set_steps(steps, rebuild=False)
        if self.tree.exists(f"s{i}.r{j}"):
            self.tree.item(f"s{i}.r{j}", text=f"[ {replies[j].text} ]")

    def _plain(self, iid: str, **change: object) -> None:
        i, j, k = self.parse(iid)
        steps = list(self.steps)
        if j is None:
            new = replace(steps[i], **change)                        # type: ignore[arg-type]
            if new.kind == mg.FROM_OTHER and not new.sender:         # type: ignore[union-attr]
                new = replace(new, sender=CONTACT_WORD)              # type: ignore[arg-type]
            steps[i] = new
        else:
            ask_step = steps[i]
            assert isinstance(ask_step, mg.AskStep) and k is not None
            replies = list(ask_step.replies)
            follow = list(replies[j].follow)
            new = replace(follow[k], **change)
            if new.kind == mg.FROM_OTHER and not new.sender:
                new = replace(new, sender=CONTACT_WORD)
            follow[k] = new
            replies[j] = replace(replies[j], follow=tuple(follow))
            steps[i] = replace(ask_step, replies=tuple(replies))
        self._set_steps(steps, iid, rebuild="kind" in change)
        if "kind" not in change and self.tree.exists(iid):
            self.tree.item(iid, text=step_text(new))                 # type: ignore[arg-type]

    def add_menu(self) -> None:
        iid = self.selected()
        inside = iid is not None and ".r" in iid           # a button or a follow-up
        menu = tk.Menu(self.host.root, tearoff=False)
        for kind, title in PLAIN_KINDS:
            menu.add_command(label=title, command=lambda k=kind: self.add_step(k))
        menu.add_command(label=mg.STEP_TITLES[mg.ASK], command=lambda: self.add_step(mg.ASK),
                         state="disabled" if inside else "normal")
        self.last_menu = menu
        button = self.add_menu_button
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    def _new_step(self, kind: str) -> mg.ChatStep:
        if kind == mg.ASK:
            taken = [s.name for s in self.steps if isinstance(s, mg.AskStep)]
            return mg.AskStep(mg.slug("reply", taken, "reply"),
                              (mg.Reply("yes", "Yes"), mg.Reply("no", "No")))
        if kind == mg.TIME:
            return mg.Step(mg.TIME, NEW_TIME)
        return mg.Step(kind, NEW_MESSAGE, CONTACT_WORD if kind == mg.FROM_OTHER else "")

    def add_step(self, kind: str) -> str:
        """Add a step after the selected one (inside a button: as its follow-up); returns
        the new step's id."""
        iid = self.selected()
        steps = list(self.steps)
        new = self._new_step(kind)
        if iid is not None and ".r" in iid and kind != mg.ASK:
            i, j, k = self.parse(iid.removesuffix(".x"))
            ask_step = steps[i]
            assert isinstance(ask_step, mg.AskStep) and j is not None
            replies = list(ask_step.replies)
            follow = list(replies[j].follow)
            at = len(follow) if k is None else k + 1
            follow.insert(at, new)                                   # type: ignore[arg-type]
            replies[j] = replace(replies[j], follow=tuple(follow))
            steps[i] = replace(ask_step, replies=tuple(replies))
            target = f"s{i}.r{j}.f{at}"
        else:
            at = len(steps) if iid is None else self.parse(iid.removesuffix(".x"))[0] + 1
            steps.insert(at, new)
            target = f"s{at}"
        self._set_steps(steps, target)
        text = self.fields.get("text")
        if text is not None:
            widget = text.widget
            widget.focus_set()
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end-1c")
            else:
                widget.selection_range(0, "end")
        return target

    def add_reply(self) -> None:
        iid = self.selected()
        if iid is None:
            return
        i = self.parse(iid.removesuffix(".x"))[0]
        steps = list(self.steps)
        ask_step = steps[i]
        if not isinstance(ask_step, mg.AskStep) or len(ask_step.replies) >= mg.REPLIES_MAX:
            return
        key = mg.slug(NEW_REPLY, [r.key for r in ask_step.replies] + [mg.ASK, mg.IGNORE],
                      "reply")
        steps[i] = replace(ask_step, replies=ask_step.replies + (mg.Reply(key, NEW_REPLY),))
        self._set_steps(steps, f"s{i}.r{len(ask_step.replies)}")

    def move(self, step: int) -> None:
        iid = self.selected()
        if iid is None or iid.endswith(".x"):
            return
        i, j, k = self.parse(iid)
        steps = list(self.steps)

        def swap(seq: list, at: int) -> bool:
            if not 0 <= at + step < len(seq):
                return False
            seq[at], seq[at + step] = seq[at + step], seq[at]
            return True
        if j is None:
            if swap(steps, i):
                self._set_steps(steps, f"s{i + step}")
            return
        ask_step = steps[i]
        assert isinstance(ask_step, mg.AskStep)
        replies = list(ask_step.replies)
        if k is None:
            if swap(replies, j):
                steps[i] = replace(ask_step, replies=tuple(replies))
                self._set_steps(steps, f"s{i}.r{j + step}")
            return
        follow = list(replies[j].follow)
        if swap(follow, k):
            replies[j] = replace(replies[j], follow=tuple(follow))
            steps[i] = replace(ask_step, replies=tuple(replies))
            self._set_steps(steps, f"s{i}.r{j}.f{k + step}")

    def remove(self) -> None:
        iid = self.selected()
        if iid is None:
            return
        if iid.endswith(".x"):
            i = self.parse(iid[:-2])[0]
            steps = list(self.steps)
            steps[i] = replace(steps[i], ignore=None)               # type: ignore[arg-type]
            self._set_steps(steps, f"s{i}")
            return
        i, j, k = self.parse(iid)
        steps = list(self.steps)
        if j is None:
            del steps[i]
            self._set_steps(steps, f"s{max(0, i - 1)}")
            return
        ask_step = steps[i]
        assert isinstance(ask_step, mg.AskStep)
        replies = list(ask_step.replies)
        if k is None:
            del replies[j]
            target = f"s{i}.r{j - 1}" if j else f"s{i}"
        else:
            follow = list(replies[j].follow)
            del follow[k]
            replies[j] = replace(replies[j], follow=tuple(follow))
            target = f"s{i}.r{j}.f{k - 1}" if k else f"s{i}.r{j}"
        steps[i] = replace(ask_step, replies=tuple(replies))
        self._set_steps(steps, target)


# Puzzle room ---------------------------------------------------------------------------------

def spot_does(spot: mg.Hotspot) -> str:
    if spot.exit is True:
        return "exit"
    if spot.take is not None:
        return "take"
    if spot.use:
        return "use"
    return "look"


Box = tuple[float, float, float, float]       # x0, y0, x1, y1 (canvas px)


def place_labels(spots: Sequence[tuple[Box, tuple[float, float]]], width: float,
                 height: float, *, pad: float = 2, gap: float = 2) -> list[Box]:
    """Where each hotspot's name label goes on the room canvas, so labels don't cover one
    another: ``spots`` are (the hotspot's box, the label's (w, h)) in drawing order; each label
    takes the first free place of: inside its box's top-left corner, stacked down inside the
    box, just under the box, just over it, then stacked down from its corner anywhere. Every
    label stays inside the canvas; one with no free place keeps its corner."""
    placed: list[Box] = []

    def fits(x: float, y: float, w: float, h: float) -> Box:
        x = min(max(x, gap), max(gap, width - w - gap))
        y = min(max(y, gap), max(gap, height - h - gap))
        return x, y, x + w, y + h

    def free(box: Box) -> bool:
        return all(box[2] + gap <= o[0] or o[2] + gap <= box[0] or box[3] + gap <= o[1]
                   or o[3] + gap <= box[1] for o in placed)

    for (x0, y0, x1, y1), (w, h) in spots:
        step = h + gap
        corner = fits(x0 + pad, y0 + pad, w, h)
        tries = [corner]
        down = y0 + pad + step
        while down + h <= y1:                               # stacked inside the box
            tries.append(fits(x0 + pad, down, w, h))
            down += step
        tries += [fits(x0 + pad, y1 + gap, w, h), fits(x0 + pad, y0 - h - gap, w, h)]
        down = y1 + gap + step
        while down + h <= height:                           # further down, anywhere
            tries.append(fits(x0 + pad, down, w, h))
            down += step
        placed.append(next((box for box in tries if free(box)), corner))
    return placed


class RoomEditor(Editor):
    """The room canvas (the background, scaled; hotspot rectangles drawn, dragged and
    resized), the selected hotspot's form, and the combine recipes."""

    kind = mg.ROOM

    def __init__(self, host: "EditorHost", parent: tk.Misc, ds: mg.DataSet,
                 model: object) -> None:
        super().__init__(host, parent, ds, model)
        px = self.px
        self.width = max(CANVAS_WIDTH, px(CANVAS_WIDTH * 3 / 4))
        self.height = round(self.width * mg.CANVAS[1] / mg.CANVAS[0])
        self.scale = self.width / mg.CANVAS[0]
        self.chosen: str | None = None
        self.drag: dict[str, Any] | None = None
        self.live: tuple[float, float, float, float] | None = None   # the rect being dragged
        top = ttk.Frame(self.frame)
        top.pack(fill="x")
        ttk.Label(top, text=BACKGROUND).pack(side="left", padx=(0, px(12)))
        self.background = _Combo(top, self.lookups.backgrounds, self.room.background,
                                 width=28, on_change=self.set_background)
        self.background.widget.pack(side="left")
        self.status.pack(anchor="w", pady=(px(4), 0))
        body = ttk.Frame(self.frame)
        body.pack(fill="x", pady=(px(8), 0))
        left = ttk.Frame(body)
        left.pack(side="left", anchor="n")
        self.canvas = tk.Canvas(left, width=self.width, height=self.height,
                                background=ROLES["raised"], highlightthickness=1,
                                highlightbackground=THEME["border"],
                                highlightcolor=ROLES["focus"], takefocus=1, cursor="crosshair")
        self.canvas.pack(anchor="w")
        ttk.Label(left, text=CANVAS_HINT, style="Hint.TLabel", wraplength=self.width,
                  justify="left").pack(anchor="w", pady=(px(6), 0))
        self.side = ttk.Frame(body)
        self.side.pack(side="left", anchor="n", fill="x", expand=True, padx=(px(16), 0))
        self.recipes = ttk.Frame(self.frame)
        self.recipes.pack(fill="x", pady=(px(16), 0))
        self.fields: dict[str, Any] = {}
        self.thumbs = host.thumb_loader(self.width, self._thumb_ready)
        self.photo: tk.PhotoImage | None = None
        c = self.canvas
        c.bind("<ButtonPress-1>", self.press)
        c.bind("<B1-Motion>", self.motion)
        c.bind("<ButtonRelease-1>", self.release)
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            c.bind(f"<Key-{key}>", lambda _e, x=dx, y=dy: (self.nudge(x, y), "break")[1])
            c.bind(f"<Shift-Key-{key}>",
                   lambda _e, x=dx, y=dy: (self.nudge(x, y, resize=True), "break")[1])
        c.bind("<Delete>", lambda _e: (self.remove_spot(), "break")[1])
        c.bind("<Escape>", lambda _e: self.choose(None))
        c.bind("<space>", lambda _e: self.cycle(1))
        if self.room.hotspots:
            self.chosen = self.room.hotspots[0].name
        self.rebuild()

    @property
    def room(self) -> mg.Room:
        return self.model                                   # type: ignore[return-value]

    def spot(self, name: str | None) -> mg.Hotspot | None:
        return next((s for s in self.room.hotspots if s.name == name), None)

    # Drawing.
    def rebuild(self) -> None:
        if self.spot(self.chosen) is None:
            self.chosen = None
        self.background.set(self.room.background)
        self.draw()
        self.show_side()
        self.show_recipes()

    def _thumb_ready(self, _ref: str) -> None:
        if self.frame.winfo_exists():
            self.draw()

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        name = self.room.background
        ref = self.lookups.images.get(name)
        color = self.lookups.colors.get(name)
        self.photo = self.thumbs.get(ref) if ref else None
        if self.photo is not None:
            c.create_image(self.width // 2, self.height // 2, image=self.photo)
        elif color:
            c.create_rectangle(0, 0, self.width, self.height, fill=color, outline="")
        else:
            c.create_text(self.width // 2, self.height // 2, fill=THEME["muted"],
                          text=NO_PICTURE.format(name=name))
        drawn = [(spot, spot.rect, False) for spot in self.room.hotspots
                 if spot.name != self.chosen]
        chosen = self.spot(self.chosen)
        if chosen is not None:
            drawn.append((chosen, self.live or chosen.rect, True))
        for spot, rect, picked in drawn:
            self._draw_spot(spot, rect, picked)
        self._draw_labels(drawn)
        c.tag_raise("handle")
        if chosen is None and self.live is not None:        # a new one being drawn
            x, y, w, h = self._box(self.live)
            c.create_rectangle(x, y, x + w, y + h, outline=ROLES["accent"], width=2,
                               dash=(4, 2), tags=("live",))

    def _box(self, rect: Sequence[float]) -> tuple[float, float, float, float]:
        x, y, w, h = rect
        if w < 0:
            x, w = x + w, -w
        if h < 0:
            y, h = y + h, -h
        s = self.scale
        return x * s, y * s, w * s, h * s

    def _draw_spot(self, spot: mg.Hotspot, rect: Sequence[float], chosen: bool) -> None:
        c = self.canvas
        x, y, w, h = self._box(rect)
        color = ROLES["accent"] if chosen else THEME["map.minigame"]
        dash = (4, 3) if spot.after is not None else ()
        c.create_rectangle(x, y, x + w, y + h, outline=color, width=3 if chosen else 2,
                           dash=dash, fill=color if chosen else "", stipple="gray25"
                           if chosen else "", tags=("spot", f"spot:{spot.name}"))
        if chosen:
            half = self.px(HANDLE_PX) / 2
            for hx, hy in self._corners(x, y, w, h):
                c.create_rectangle(hx - half, hy - half, hx + half, hy + half,
                                   fill=ROLES["accent"], outline=ROLES["text"],
                                   tags=("handle",))

    def _draw_labels(self, drawn: Sequence[tuple[mg.Hotspot, Sequence[float], bool]]) -> None:
        """Each hotspot's name on a small plate, nudged so no two plates overlap
        (``place_labels``); ``label_boxes``: name → its plate (tests)."""
        c = self.canvas
        texts, wanted = [], []
        for spot, rect, _picked in drawn:
            label = spot.label + ("  ⇥" if spot.exit else "")
            text = c.create_text(0, 0, anchor="nw", text=label, fill=ROLES["textStrong"],
                                 font=self.host.fonts.get("small"),
                                 tags=("label", f"spot:{spot.name}"))
            bx0, by0, bx1, by1 = c.bbox(text) or (0, 0, 0, 0)
            x, y, w, h = self._box(rect)
            texts.append((spot.name, text, bx0, by0))
            wanted.append(((x, y, x + w, y + h), (bx1 - bx0 + 4, by1 - by0 + 2)))
        self.label_boxes: dict[str, Box] = {}
        for (name, text, bx0, by0), box in zip(texts, place_labels(
                wanted, self.width, self.height), strict=True):
            c.coords(text, box[0] + 2 - bx0, box[1] + 1 - by0)
            back = c.create_rectangle(*box, fill=ROLES["surface"], outline="",
                                      tags=("label",))
            c.tag_lower(back, text)
            self.label_boxes[name] = box

    @staticmethod
    def _corners(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
        return [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]

    # Mouse (canvas px in, screen units kept).
    def _units(self, cx: float, cy: float) -> tuple[float, float]:
        return cx / self.scale, cy / self.scale

    def _hit(self, cx: float, cy: float) -> mg.Hotspot | None:
        ux, uy = self._units(cx, cy)
        order = sorted(self.room.hotspots, key=lambda s: s.name == self.chosen)
        for spot in reversed(order):
            x, y, w, h = spot.rect
            if x <= ux <= x + w and y <= uy <= y + h:
                return spot
        return None

    def press(self, event: Any) -> None:
        self.canvas.focus_set()
        cx, cy = event.x, event.y
        chosen = self.spot(self.chosen)
        if chosen is not None:
            x, y, w, h = self._box(chosen.rect)
            reach = self.px(HANDLE_PX)
            for n, (hx, hy) in enumerate(self._corners(x, y, w, h)):
                if abs(cx - hx) <= reach and abs(cy - hy) <= reach:
                    rx, ry, rw, rh = chosen.rect
                    fixed = (rx + rw if n in (0, 2) else rx, ry + rh if n in (0, 1) else ry)
                    self.drag = {"mode": "resize", "fixed": fixed, "start": (cx, cy)}
                    return
        hit = self._hit(cx, cy)
        if hit is not None:
            if hit.name != self.chosen:
                self.choose(hit.name)
            self.drag = {"mode": "move", "start": (cx, cy), "rect": hit.rect}
            return
        self.choose(None)
        ux, uy = self._units(cx, cy)
        self.drag = {"mode": "draw", "start": (cx, cy), "origin": (ux, uy)}

    def motion(self, event: Any) -> None:
        drag = self.drag
        if drag is None:
            return
        ux, uy = self._units(event.x, event.y)
        if drag["mode"] == "move":
            sx, sy = self._units(*drag["start"])
            x, y, w, h = drag["rect"]
            self.live = (x + ux - sx, y + uy - sy, w, h)
        elif drag["mode"] == "resize":
            fx, fy = drag["fixed"]
            self.live = (fx, fy, ux - fx, uy - fy)
        else:
            ox, oy = drag["origin"]
            self.live = (ox, oy, ux - ox, uy - oy)
        self.draw()

    def release(self, event: Any) -> None:
        drag, live = self.drag, self.live
        self.drag, self.live = None, None
        if drag is None:
            return
        sx, sy = drag["start"]
        moved = abs(event.x - sx) >= MIN_DRAG_PX or abs(event.y - sy) >= MIN_DRAG_PX
        if live is None or not moved:
            self.draw()
            return
        rect = mg.clamp_rect(live)
        if drag["mode"] == "draw":
            self.add_spot(rect)
        else:
            chosen = self.spot(self.chosen)
            if chosen is not None:
                self.set_spot(chosen.name, rect=rect)

    def nudge(self, dx: int, dy: int, *, resize: bool = False) -> None:
        spot = self.spot(self.chosen)
        if spot is None:
            return
        x, y, w, h = spot.rect
        rect = (x, y, w + dx * NUDGE, h + dy * NUDGE) if resize else \
            (x + dx * NUDGE, y + dy * NUDGE, w, h)
        self.set_spot(spot.name, rect=mg.clamp_rect(rect))

    def cycle(self, step: int) -> str:
        names = [s.name for s in self.room.hotspots]
        if names:
            at = names.index(self.chosen) + step if self.chosen in names else 0
            self.choose(names[at % len(names)])
        return "break"

    def choose(self, name: str | None) -> None:
        self.chosen = name
        self.draw()
        self.show_side()

    # Model changes.
    def _set_room(self, room: mg.Room, *, side: bool = False) -> None:
        self.changed(room)
        self.draw()
        if side:
            self.show_side()
            self.show_recipes()

    def set_background(self, name: str) -> None:
        if name and name != self.room.background:
            self._set_room(replace(self.room, background=name))

    def add_spot(self, rect: tuple[int, int, int, int]) -> str:
        """A new hotspot at ``rect`` (screen units), selected; returns its name."""
        n = len(self.room.hotspots) + 1
        taken = [s.name for s in self.room.hotspots]
        label = NEW_HOTSPOT_LABEL.format(n=n)
        while label.casefold() in {s.label.casefold() for s in self.room.hotspots}:
            n += 1
            label = NEW_HOTSPOT_LABEL.format(n=n)
        name = mg.slug(label, taken, "spot")
        spot = mg.Hotspot(name, rect, label)
        self.chosen = name
        self._set_room(replace(self.room, hotspots=self.room.hotspots + (spot,)), side=True)
        label_field = self.fields.get("label")
        if label_field is not None:
            label_field.entry.focus_set()
            label_field.entry.selection_range(0, "end")
        return name

    def set_spot(self, name: str, **change: object) -> None:
        spots = list(self.room.hotspots)
        at = next(i for i, s in enumerate(spots) if s.name == name)
        old = spots[at]
        new = replace(old, **change)                                 # type: ignore[arg-type]
        renamed = None
        if "label" in change and old.name == mg.slug(old.label, [
                s.name for s in spots if s.name != old.name], "spot"):
            fresh = mg.slug(str(change["label"]), [s.name for s in spots if s.name != old.name],
                            "spot")
            if fresh != old.name:
                renamed = fresh
                new = replace(new, name=fresh)
        spots[at] = new
        if renamed is not None:
            spots = [replace(s, after=renamed) if s.after == old.name else s for s in spots]
            self.chosen = renamed
        self._set_room(replace(self.room, hotspots=tuple(spots)), side=renamed is not None)

    def set_does(self, name: str, does: str) -> None:
        spot = self.spot(name)
        if spot is None or spot_does(spot) == does:
            return
        items = self.lookups.item_names
        first = items[0] if items else "item"
        change: dict[str, object] = {"take": None, "use": (), "nope": None,
                                     "exit": False if spot.exit is False else None}
        if does == "take":
            change.update(take=spot.take or first, look=None)
        elif does == "use":
            change.update(use=spot.use or (first,))
        elif does == "exit":
            change.update(exit=True, look=None)
        spots = [replace(s, **change) if s.name == name else s      # type: ignore[arg-type]
                 for s in self.room.hotspots]
        self._set_room(replace(self.room, hotspots=tuple(spots)), side=True)

    def remove_spot(self) -> None:
        spot = self.spot(self.chosen)
        if spot is None:
            return
        spots = [replace(s, after=None) if s.after == spot.name else s
                 for s in self.room.hotspots if s.name != spot.name]
        self.chosen = None
        self._set_room(replace(self.room, hotspots=tuple(spots)), side=True)

    # The side form.
    def show_side(self) -> None:
        for child in self.side.winfo_children():
            child.destroy()
        self.fields = {}
        spot = self.spot(self.chosen)
        px = self.px
        ttk.Label(self.side, text=HOTSPOT.upper(), style="Caption.TLabel").pack(
            anchor="w", pady=(0, px(6)))
        if spot is None:
            ttk.Label(self.side, text=NO_HOTSPOT, style="Hint.TLabel", wraplength=px(200),
                      justify="left").pack(anchor="w")
            return
        name = spot.name
        grid = self.side

        def row(label: str, widget: tk.Widget) -> None:
            """An inspector row: the label above its field (Adobe's panels)."""
            ttk.Label(grid, text=label, style="Detail.TLabel").pack(anchor="w",
                                                                   pady=(px(6), px(2)))
            widget.pack(anchor="w", in_=grid)

        def text_or_none(t: str) -> str | None:
            return t.strip() or None

        label = _Entry(grid, spot.label, width=24,
                       on_change=lambda t: self.set_spot(name, label=t.strip()))
        row(NAME_TAG, label.widget)
        does = spot_does(spot)
        does_box = _Combo(grid, [t for _k, t in DOES], dict(DOES)[does], readonly=True,
                          width=22, on_change=lambda t: self.set_does(
                              name, next(k for k, t_ in DOES if t_ == t)))
        row(WHEN_CLICKED, does_box.widget)
        self.fields.update(label=label, does=does_box)
        if does in ("look", "use"):
            look = _Entry(grid, spot.look or "", width=24,
                          on_change=lambda t: self.set_spot(name, look=text_or_none(t)))
            row(LOOK_TEXT, look.widget)
            self.fields["look"] = look
        if does == "take":
            take = _Combo(grid, self.lookups.item_names, spot.take or "", width=22,
                          on_change=lambda t: self.set_spot(name, take=t or None))
            row(TAKE_ITEM, take.widget)
            self.fields["take"] = take
        if does == "use":
            use = _Checklist(grid, self.lookups.items, spot.use, columns=1,
                             on_change=lambda names: self.set_spot(name, use=names))
            row(USE_ITEMS, use.widget)
            nope = _Entry(grid, spot.nope or "", width=24,
                          on_change=lambda t: self.set_spot(name, nope=text_or_none(t)))
            row(NOPE_TEXT, nope.widget)
            self.fields.update(use=use, nope=nope)
        others = [(s.name, s.label) for s in self.room.hotspots
                  if s.name != name and (s.take is not None or s.use)]
        after_choices = [ALWAYS] + [f"{shown} ({n})" for n, shown in others]
        current = next((f"{shown} ({n})" for n, shown in others if n == spot.after),
                       spot.after or ALWAYS)
        after = _Combo(grid, after_choices, current, readonly=True, width=22,
                       on_change=lambda t: self.set_spot(name, after=None if t == ALWAYS else
                                                         t.rsplit("(", 1)[-1].rstrip(")")))
        row(AFTER, after.widget)
        pictures = [NO_PICTURE_CHOICE] + sorted(
            (n for n, ref in self.lookups.images.items() if ref is not None
             and not n.casefold().startswith("bg ")), key=str.casefold)
        picture = _Combo(grid, pictures, spot.image or NO_PICTURE_CHOICE, width=22,
                         on_change=lambda t: self.set_spot(
                             name, image=None if t in ("", NO_PICTURE_CHOICE) else t))
        row(PICTURE, picture.widget)
        place = ttk.Frame(grid)
        numbers: list[tk.StringVar] = []
        for i, (word, value) in enumerate(zip(PLACE_WORDS, spot.rect)):
            ttk.Label(place, text=word).grid(row=i // 2, column=(i % 2) * 2, sticky="w",
                                             padx=(px(8) if i % 2 else 0, px(4)), pady=1)
            var = tk.StringVar(master=place, value=str(value))
            spin = ttk.Spinbox(place, from_=0, to=mg.CANVAS[i % 2], increment=NUDGE, width=5,
                               textvariable=var, command=lambda: self._place(name, numbers))
            for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
                spin.bind(key, lambda _e: self._place(name, numbers), add="+")
            spin.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", pady=1)
            numbers.append(var)
        row(PLACE, place)
        ttk.Label(grid, text=dec_name_line(name), style="Hint.TLabel").pack(
            anchor="w", pady=(px(8), 0))
        ttk.Button(grid, text=DELETE_HOTSPOT, style="Secondary.TButton",
                   command=self.remove_spot).pack(anchor="w", pady=(px(10), 0))
        self.fields.update(after=after, picture=picture, place=numbers)

    def _place(self, name: str, numbers: Sequence[tk.StringVar]) -> None:
        try:
            rect = tuple(int(float(v.get())) for v in numbers)
        except ValueError:
            self.show_side()
            return
        spot = self.spot(name)
        if spot is None:
            return
        fixed = mg.clamp_rect(rect)
        if fixed != spot.rect:
            self.set_spot(name, rect=fixed)
        if fixed != rect:
            for var, value in zip(numbers, fixed):
                var.set(str(value))

    # Recipes.
    def show_recipes(self) -> None:
        for child in self.recipes.winfo_children():
            child.destroy()
        px = self.px
        head = ttk.Frame(self.recipes)
        head.grid(row=0, column=0, columnspan=6, sticky="ew", pady=(0, px(6)))
        ttk.Label(head, text=RECIPES.upper(), style="Caption.TLabel").pack(side="left")
        ttk.Button(head, text=ADD_RECIPE, style="Secondary.TButton",
                   command=self.add_recipe).pack(side="left", padx=(px(16), 0))
        items = self.lookups.item_names
        for r, (made, a, b) in enumerate(self.room.combine, start=1):
            for c, (value, part) in enumerate(((a, 1), (b, 2), (made, 0))):
                if c == 1:
                    ttk.Label(self.recipes, text=RECIPE_PLUS).grid(row=r, column=1, padx=px(6))
                if c == 2:
                    ttk.Label(self.recipes, text=RECIPE_MAKES).grid(row=r, column=3,
                                                                    padx=px(6))
                box = _Combo(self.recipes, items, value, width=18,
                             on_change=lambda t, i=r - 1, p=part: self.set_recipe(i, p, t))
                box.widget.grid(row=r, column=c * 2, sticky="w", pady=px(2))
            ttk.Button(self.recipes, text=REMOVE, width=3, style="Ghost.TButton",
                       command=lambda i=r - 1: self.remove_recipe(i)).grid(
                row=r, column=5, padx=(px(6), 0))

    def add_recipe(self) -> None:
        items = self.lookups.item_names + ["item_a", "item_b", "item_c"]
        recipe = (items[2], items[0], items[1])
        self._set_room(replace(self.room, combine=self.room.combine + (recipe,)), side=True)

    def set_recipe(self, index: int, part: int, value: str) -> None:
        combine = [list(r) for r in self.room.combine]
        combine[index][part] = value
        self._set_room(replace(self.room, combine=tuple(tuple(r) for r in combine)))

    def remove_recipe(self, index: int) -> None:
        combine = list(self.room.combine)
        del combine[index]
        self._set_room(replace(self.room, combine=tuple(combine)), side=True)


# Gift tables ---------------------------------------------------------------------------------

class GiftsEditor(Editor):
    """F54 §4.2: one character's gifts at a time (the Character pick-list), a row per gift
    (the item, its reaction, its points, what the character says) under the "Any other gift"
    row, which can't be removed and is written only when it isn't Neutral, 0, empty."""

    kind = mg.GIFTS

    def __init__(self, host: "EditorHost", parent: tk.Misc, ds: mg.DataSet,
                 model: object) -> None:
        super().__init__(host, parent, ds, model)
        px = self.px
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x")
        ttk.Label(bar, text=CHARACTER).pack(side="left", padx=(0, px(8)))
        self.current = 0
        self.character = _Combo(bar, [], "", readonly=True, width=16,
                                on_change=self.choose_character)
        self.character.widget.pack(side="left")
        ttk.Button(bar, text=ADD_CHARACTER, style="Secondary.TButton",
                   command=self.add_character).pack(side="left", padx=(px(8), 0))
        self.remove_button = ttk.Button(bar, text=REMOVE_CHARACTER, style="Secondary.TButton",
                                        command=self.remove_character)
        self.remove_button.pack(side="left", padx=(px(4), 0))
        self.table = ttk.Frame(self.frame)
        self.table.pack(anchor="w", fill="x", pady=(px(8), 0))
        foot = ttk.Frame(self.frame)
        foot.pack(fill="x", pady=(px(8), 0))
        self.add_button = ttk.Button(foot, text=ADD_GIFT, style="Secondary.TButton",
                                     command=self.add_gift)
        self.add_button.pack(side="left")
        self.no_items = ttk.Label(foot, text=NO_GIFT_ITEMS, style="Hint.TLabel",
                                  wraplength=px(420), justify="left")
        self.status.pack(in_=foot, side="right")
        self.any_fields: dict[str, Any] = {}
        self.rows: list[dict[str, Any]] = []
        self.rebuild()

    @property
    def table_model(self) -> mg.GiftTable:
        return self.model                                   # type: ignore[return-value]

    @property
    def section(self) -> mg.GiftSection | None:
        sections = self.table_model.sections
        return sections[self.current] if 0 <= self.current < len(sections) else None

    def gifts(self) -> list[mg.GiftRow]:
        """The current character's gifts, the "Any other gift" row left out."""
        section = self.section
        return [r for r in section.rows if r.item != mg.ANY_GIFT] if section else []

    # -- building --

    def rebuild(self) -> None:
        for child in self.table.winfo_children():
            child.destroy()
        self.any_fields, self.rows = {}, []
        sections = self.table_model.sections
        self.current = min(self.current, max(0, len(sections) - 1))
        names = [s.character for s in sections]
        self.character.box.configure(values=names)
        self.character.set(names[self.current] if names else "")
        self.remove_button.configure(state="normal" if sections else "disabled")
        items = self.lookups.items
        if items:
            self.no_items.pack_forget()
            self.add_button.configure(state="normal" if sections else "disabled")
        else:
            self.add_button.configure(state="disabled")
            self.no_items.pack(side="left", padx=(self.px(8), 0))
        section = self.section
        if section is None:
            return
        pad = self.px(6)
        for c, head in enumerate(GIFT_HEADS):
            ttk.Label(self.table, text=head.upper(), style="Caption.TLabel").grid(
                row=0, column=c, sticky="w", padx=(0, pad))
        row = section.any_row or mg.GiftRow(mg.ANY_GIFT, "neutral", 0)
        ttk.Label(self.table, text=ANY_GIFT_TEXT).grid(row=1, column=0, sticky="w",
                                                       padx=(0, pad), pady=1)
        self.any_fields = self._cells(1, row, lambda **v: self.set_any(**v))
        titles = [t for _n, t in items]
        for r, gift in enumerate(self.gifts(), start=2):
            index = r - 2
            item = _Combo(self.table, titles, self.lookups.item_title(gift.item), width=18,
                          readonly=True,
                          on_change=lambda text, i=index: self.set_gift(
                              i, item=self._item_name(text)))
            item.widget.grid(row=r, column=0, sticky="w", padx=(0, pad), pady=1)
            fields = self._cells(r, gift, lambda i=index, **v: self.set_gift(i, **v))
            fields["item"] = item
            ttk.Button(self.table, text=REMOVE, width=3, style="Ghost.TButton",
                       command=lambda i=index: self.remove_gift(i)).grid(
                row=r, column=4, sticky="w")
            self.rows.append(fields)

    def _cells(self, r: int, row: mg.GiftRow, set_: Callable[..., object]) -> dict[str, Any]:
        """The Reaction, Points and What they say cells of grid row ``r``."""
        pad = self.px(6)
        titles = [mg.REACTION_TITLES[x] for x in mg.REACTIONS]
        reaction = _Combo(self.table, titles, mg.REACTION_TITLES.get(row.reaction, row.reaction),
                          width=10, readonly=True,
                          on_change=lambda text: set_(reaction=self._reaction(text)))
        reaction.widget.grid(row=r, column=1, sticky="w", padx=(0, pad), pady=1)
        var = tk.StringVar(master=self.table, value=str(row.points))
        lo, hi = mg.GIFT_POINTS
        spin = ttk.Spinbox(self.table, from_=lo, to=hi, increment=1, width=4, textvariable=var,
                           command=lambda: set_(points=self._points(var)))
        for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
            spin.bind(key, lambda _e: set_(points=self._points(var)), add="+")
        spin.grid(row=r, column=2, sticky="w", padx=(0, pad), pady=1)
        line = _Entry(self.table, row.line or "", width=30,
                      on_change=lambda text: set_(line=text.strip() or None))
        line.widget.grid(row=r, column=3, sticky="w", padx=(0, pad), pady=1)
        return {"reaction": reaction, "points": var, "spin": spin, "line": line}

    def _item_name(self, title: str) -> str:
        return next((n for n, t in self.lookups.items if t == title), title)

    @staticmethod
    def _reaction(title: str) -> str:
        return next((r for r, t in mg.REACTION_TITLES.items() if t == title), title.lower())

    @staticmethod
    def _points(var: tk.StringVar) -> int | None:
        try:
            value = int(str(var.get()).strip())
        except ValueError:
            return None
        lo, hi = mg.GIFT_POINTS
        return value if lo <= value <= hi else None

    # -- changes --

    def _set_section(self, section: mg.GiftSection, *, rebuild: bool = False) -> None:
        sections = list(self.table_model.sections)
        if sections[self.current] == section:
            return
        sections[self.current] = section
        self.changed(mg.GiftTable(tuple(sections)), rebuild=rebuild)

    def choose_character(self, name: str) -> None:
        names = [s.character for s in self.table_model.sections]
        if name in names:
            self.current = names.index(name)
            self.rebuild()

    def add_character(self) -> None:
        taken = {s.character for s in self.table_model.sections}
        free = next((m for m in self.lookups.meters if m not in taken), "")
        answer = ask_text(self.host.root, ADD_CHARACTER_ASK, free, ok="Add")
        if answer is None or not answer[0].strip():
            return
        name = answer[0].strip()
        if name in taken:
            self.choose_character(name)
            return
        sections = self.table_model.sections + (mg.GiftSection(name),)
        self.current = len(sections) - 1
        self.changed(mg.GiftTable(sections), rebuild=True)

    def remove_character(self) -> None:
        sections = list(self.table_model.sections)
        if not sections:
            return
        del sections[self.current]
        self.current = max(0, self.current - 1)
        self.changed(mg.GiftTable(tuple(sections)), rebuild=True)

    def set_any(self, *, reaction: str | None = None, points: int | None = None,
                line: object = ...) -> None:
        section = self.section
        if section is None:
            return
        row = section.any_row or mg.GiftRow(mg.ANY_GIFT, "neutral", 0)
        if points is None and reaction is None and line is ...:
            self.rebuild()                                   # a points value out of range
            return
        new = mg.gift_set_any(section, reaction or row.reaction,
                              row.points if points is None else points,
                              row.line if line is ... else line)   # type: ignore[arg-type]
        self._set_section(new)

    def set_gift(self, index: int, *, item: str | None = None, reaction: str | None = None,
                 points: int | None = None, line: object = ...) -> None:
        section = self.section
        gifts = self.gifts()
        if section is None or not 0 <= index < len(gifts):
            return
        old = gifts[index]
        if item is None and reaction is None and points is None and line is ...:
            self.rebuild()                                   # a points value out of range
            return
        new = mg.GiftRow(item or old.item, reaction or old.reaction,
                         old.points if points is None else points,
                         old.line if line is ... else line)  # type: ignore[arg-type]
        rows = [new if r is old else r for r in section.rows]
        self._set_section(mg.GiftSection(section.character, tuple(rows)),
                          rebuild=item is not None)

    def add_gift(self) -> None:
        section = self.section
        if section is None or not self.lookups.items:
            return
        used = {r.item for r in section.rows}
        name = next((n for n in self.lookups.item_names if n not in used),
                    self.lookups.item_names[0])
        rows = section.rows + (mg.GiftRow(name, *NEW_GIFT),)
        self._set_section(mg.GiftSection(section.character, rows), rebuild=True)

    def remove_gift(self, index: int) -> None:
        section = self.section
        gifts = self.gifts()
        if section is None or not 0 <= index < len(gifts):
            return
        rows = tuple(r for r in section.rows if r is not gifts[index])
        self._set_section(mg.GiftSection(section.character, rows), rebuild=True)


EDITORS: Mapping[str, type[Editor]] = {
    mg.POEM: PoemEditor, mg.TESTIMONY: EvidenceEditor, mg.CHAT: ChatEditor,
    mg.ROOM: RoomEditor, mg.GIFTS: GiftsEditor}
# F56: the Terminal editor lives in ``terminalview`` (imported where it is made).
EDITABLE_KINDS: tuple[str, ...] = (*EDITORS, mg.TERMINAL)


# --- The host (Database category, or a dialog) -------------------------------------------------

class EditorHost:
    """What an editor needs from where it is shown."""

    def __init__(self, win: Any, root: tk.Misc, store: Store) -> None:
        self.win = win
        self.root = root
        self.store = store
        self.scale = getattr(win, "scale", 1.0)
        self.fonts = getattr(win, "fonts", {})
        self.on_written: Callable[[Editor], object] | None = None

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def thumb_loader(self, size: int, ready: Callable[[str], object]) -> Any:
        from engine.tools.editor.helperhub import ThumbLoader
        return ThumbLoader(self.win, self.root, size, ready)

    def written(self, editor: Editor) -> None:
        if self.on_written is not None:
            self.on_written(editor)


def editor_for(host: EditorHost, parent: tk.Misc, ds: mg.DataSet) -> Editor | None:
    """The editor of ``ds``, or None when the panel can't hold how it is written."""
    model = host.store.model_of(ds)
    if ds.model is None or model is None:
        return None
    if ds.kind == mg.TERMINAL:                       # F56: here, so no import cycle
        from engine.tools.editor.terminalview import TerminalEditor
        return TerminalEditor(host, parent, ds, model)
    if ds.kind not in EDITORS:
        return None
    return EDITORS[ds.kind](host, parent, ds, model)


def complex_box(parent: tk.Misc, win: Any, ds: mg.DataSet, px: Callable[[float], int],
                text: str = declplan.COMPLEX) -> ttk.Frame:
    box = ttk.Frame(parent)
    ttk.Label(box, text=text, wraplength=px(360), justify="left").pack(anchor="w")
    ttk.Button(box, text=EDIT_AS_SCRIPT, style="Secondary.TButton",
               command=lambda: win.jump_to(ds.ref, ds.first)).pack(anchor="w", pady=(px(8), 0))
    return box


def new_data(win: Any, store: Store, kind: str) -> str | None:
    """+ New: a name, then a starter data set in ``database.vns``; returns its name."""
    store.read()
    model = starter(kind, store.lookups)
    if model is None:
        show_error(win.root, NO_ITEMS_FOR_EVIDENCE)
        return None
    taken = set(dec.taken_names(dec.scan(store.texts), dec.DEFINE)) | {
        s.name for s in store.sets}
    thing = THING[kind]

    def name_of(text: str) -> str:
        return mg.slug(text, taken, kind)
    answer = ask_text(win.root, NEW_ASK.format(thing=thing), "", ok="Add",
                      hint=lambda shown: IN_SCRIPT.format(name=name_of(shown))
                      if shown.strip() else None)
    if answer is None or not answer[0].strip():
        return None
    name = name_of(answer[0].strip())
    return name if store.create(kind, name, model) else None


# --- Database ▸ Minigame data --------------------------------------------------------------------

class MinigamePane:
    """The Minigame data category of a ``database.DatabasePane``: its own list and editor,
    shown in the Database's columns while the category is picked (``attach``)."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self.win = win = database.win
        self.root = win.root
        self.store = Store(win)
        self.host = EditorHost(win, database.frame, self.store)
        self.host.on_written = lambda _editor: self.refresh(keep_editor=True)
        px = self.host.px
        paned = database.paned
        self.list_frame = ttk.Frame(paned)
        head = panel_header(self.list_frame, CATEGORY_TITLE.upper(), self.host.scale)
        head.pack(fill="x")
        self.new_button = ttk.Button(head, text=NEW_BUTTON, command=self.new_menu,
                                     style="Chrome.Ghost.TButton", takefocus=1)
        self.new_button.pack(side="right", padx=(0, px(4)))
        self.list_body = ttk.Frame(self.list_frame)
        self.list_body.pack(fill="both", expand=True, pady=(px(8), 0))
        self.cat_choice: Any = None                 # the categories drop-down (``attach``)
        self.tree = ttk.Treeview(self.list_body, show="tree", selectmode="browse",
                                 columns=("detail",), height=1, style="Surface.Treeview")
        self.tree.column("#0", width=px(130), stretch=True)
        self.tree.column("detail", width=px(90), anchor="e", stretch=False)
        self.tree.tag_configure("group", foreground=THEME["muted"],
                                font=self.host.fonts.get("caption"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_row(), add="+")
        self.tree.bind("<Delete>", lambda _e: (self.delete_selected(), "break")[1])
        self.empty = EmptyState(self.list_body, icon="add", title=EMPTY_TITLE,
                                hint=EMPTY_HINT, button=NEW_BUTTON, command=self.new_menu,
                                scale=self.host.scale)
        self.editor_frame = ttk.Frame(paned)
        from engine.tools.editor.fieldwidgets import ScrollFrame
        self.scroll = ScrollFrame(self.editor_frame)
        self.scroll.frame.pack(fill="both", expand=True)
        self.body: ttk.Frame | None = None
        self.editor: Editor | None = None
        self.chosen: str | None = None
        self.showing = False
        self.last_menu: tk.Menu | None = None
        self._refresh_id: str | None = None
        win.on_check_done.append(lambda _result: self._schedule())

    @property
    def shown(self) -> bool:
        return self.showing

    def _schedule(self) -> None:
        if self.win.closed or self._refresh_id is not None:
            return
        self._refresh_id = self.root.after_idle(lambda: self.refresh(keep_editor=True))

    def show(self) -> None:
        if self.showing:
            return
        db_pane = self.database
        paned = db_pane.paned
        paned.forget(db_pane.list_frame)
        paned.forget(db_pane.form_frame)
        paned.add(self.list_frame, width=self.host.px(LIST_WIDTH), minsize=self.host.px(160),
                  stretch="never")
        paned.add(self.editor_frame, minsize=self.host.px(320), stretch="always")
        self.showing = True
        db_pane.show_category_choice(CATEGORY)
        self.refresh()

    def compact(self, on: bool) -> None:
        """Narrow windows: the categories drop-down over the list (the side bar is gone)."""
        if self.cat_choice is None:
            return
        if on:
            self.cat_choice.widget.pack(fill="x", padx=self.host.px(8),
                                        pady=(self.host.px(8), 0), before=self.list_body)
        else:
            self.cat_choice.widget.pack_forget()

    def hide(self) -> None:
        if not self.showing:
            return
        db_pane = self.database
        paned = db_pane.paned
        paned.forget(self.list_frame)
        paned.forget(self.editor_frame)
        from engine.tools.editor.database import FORM_MIN_WIDTH, LIST_WIDTH as DB_LIST
        paned.add(db_pane.list_frame, width=self.host.px(DB_LIST), minsize=self.host.px(160),
                  stretch="never")
        paned.add(db_pane.form_frame, minsize=self.host.px(FORM_MIN_WIDTH), stretch="always")
        self.showing = False
        db_pane.show_category_choice(db_pane.category)

    def on_category(self) -> None:
        chosen = self.database.cat_tree.selection()
        if tuple(chosen) == (CATEGORY,):
            self.show()
        else:
            self.hide()

    def select(self) -> None:
        """Pick the category (tests, Show me)."""
        self.database.cat_tree.selection_set(CATEGORY)
        self.on_category()

    # The list.
    def listed(self) -> list[mg.DataSet]:
        answers = self.store.answer_names()
        return [ds for ds in self.store.sets if not (ds.kind == mg.ANSWER and ds.name in answers)]

    def refresh(self, keep_editor: bool = False) -> None:
        self._refresh_id = None
        if self.win.closed:
            return
        self.store.read()
        sets = self.listed()
        try:
            self.database.cat_tree.item(CATEGORY, values=(str(len(
                [s for s in sets if s.kind != mg.ANSWER])),))
        except tk.TclError:
            pass
        if not self.showing:
            return
        uses = self.store.uses()
        tree = self.tree
        tree.delete(*tree.get_children())
        for kind in (mg.POEM, mg.TESTIMONY, mg.CHAT, mg.ROOM, mg.GIFTS, mg.TERMINAL):
            members = [ds for ds in sets if ds.kind == kind or
                       (kind == mg.TESTIMONY and ds.kind == mg.ANSWER)]
            if not members:
                continue
            tree.insert("", "end", iid=f"g:{kind}", text=GROUP_TITLES[kind],
                        values=(str(len(members)),), open=True, tags=("group",))
            for ds in members:
                n = uses.get(ds.name, 0)
                tree.insert(f"g:{kind}", "end", iid=f"d:{ds.name}", text=ds.name,
                            values=(_lines_word(n) if n else NOT_USED,))
        if sets:
            self.empty.hide()
        else:
            self.empty.show(self.list_body)
        chosen = self.chosen if self.chosen and tree.exists(f"d:{self.chosen}") else None
        if chosen is None and sets:
            chosen = sets[0].name
        self.chosen = chosen
        if chosen is not None:
            tree.selection_set(f"d:{chosen}")
            tree.focus(f"d:{chosen}")
            tree.see(f"d:{chosen}")
        self._show(keep_editor)

    def data(self, name: str | None) -> mg.DataSet | None:
        return next((ds for ds in self.listed() if ds.name == name), None)

    def _on_row(self) -> None:
        chosen = self.tree.selection()
        if not chosen or not chosen[0].startswith("d:"):
            return
        name = chosen[0][2:]
        if name != self.chosen or self.editor is None:
            self.chosen = name
            self._show(False)

    def pick(self, name: str) -> None:
        """Select the data set ``name`` (tests, the Minigame form's Set up…)."""
        self.chosen = name
        self.refresh()

    def _show(self, keep_editor: bool) -> None:
        ds = self.data(self.chosen)
        editor = self.editor
        if keep_editor and editor is not None and ds is not None and editor.ds.name == ds.name:
            if editor.pending or self.store.model_of(ds) == editor.model:
                editor.ds = ds
                self._detail(ds)
                return
        if self.body is not None:
            self.body.destroy()
        self.editor = None
        pad = self.host.px(PAD)
        body = self.body = ttk.Frame(self.scroll.inner, padding=(pad, pad, pad, pad))
        body.pack(fill="both", expand=True)
        if ds is None:
            text = ABOUT if not self.listed() else PICK_ENTRY
            ttk.Label(body, text=text, style="Hint.TLabel", wraplength=self.host.px(420),
                      justify="left").pack(anchor="w")
            return
        title = ttk.Frame(body)
        title.pack(fill="x", pady=(0, self.host.px(4)))
        ttk.Label(title, text=ds.name, style="Title.TLabel").pack(side="left")
        ttk.Button(title, text=DELETE, style="Secondary.TButton",
                   command=self.delete_selected).pack(side="right")
        if ds.kind != mg.ANSWER:
            ttk.Button(title, text=RENAME, style="Secondary.TButton",
                       command=self.rename_selected).pack(side="right",
                                                          padx=(0, self.host.px(8)))
        self.detail_label = ttk.Label(body, text="", style="Hint.TLabel")
        self.detail_label.pack(anchor="w", pady=(0, self.host.px(12)))
        self._detail(ds)
        if ds.kind == mg.ANSWER:
            complex_box(body, self.win, ds, self.host.px, ANSWER_ONLY).pack(anchor="w")
            return
        editor = editor_for(self.host, body, ds)
        if editor is None:
            complex_box(body, self.win, ds, self.host.px).pack(anchor="w")
            return
        self.editor = editor
        editor.frame.pack(fill="both", expand=True)
        self.scroll.top()

    def _detail(self, ds: mg.DataSet) -> None:
        n = self.store.uses().get(ds.name, 0)
        kind = mg.KIND_TITLES[ds.kind]
        used = USED_IN.format(lines=_lines_word(n)) if n else NOT_USED
        try:
            self.detail_label.configure(text=f"{kind} · {used} · {ds.ref}:{ds.first}")
        except (tk.TclError, AttributeError):
            pass

    # New and delete.
    def new_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        for kind in (mg.POEM, mg.TESTIMONY, mg.CHAT, mg.ROOM, mg.GIFTS, mg.TERMINAL):
            menu.add_command(label=NEW_ITEM.format(thing=THING[kind]),
                             command=lambda k=kind: self.new(k))
        self.last_menu = menu
        button = self.new_button
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    def new(self, kind: str) -> str | None:
        name = new_data(self.win, self.store, kind)
        if name is not None:
            self.chosen = name
            self.refresh()
        return name

    def rename_selected(self) -> bool:
        """Rename… (P3-B): a new script name for the data set, and every ``minigame`` line
        that passes it follows. A testimony's ``<name>_answer`` follows too."""
        ds = self.data(self.chosen)
        if ds is None or ds.kind == mg.ANSWER:
            return False
        answer = ask_text(self.root, RENAME_ASK.format(name=ds.name), ds.name, ok="Rename")
        if answer is None or not answer[0].strip() or answer[0].strip() == ds.name:
            return False
        new = answer[0].strip()
        pair = self.store.answer_of(ds) if ds.kind == mg.TESTIMONY else None
        if not self.database.rename_everywhere(declrename.DATA, ds.name, new):
            return False
        if pair is not None and pair.name == f"{ds.name}_answer":
            self.database.rename_everywhere(declrename.DATA, pair.name, f"{new}_answer")
        self.chosen = new
        self.refresh()
        return True

    def delete_selected(self) -> None:
        ds = self.data(self.chosen)
        if ds is None:
            return
        n = self.store.uses().get(ds.name, 0)
        if n:
            show_error(self.root, DELETE_REFUSED.format(name=ds.name, lines=_lines_word(n)))
            return
        from engine.script.messages import show
        if ask(self.root, DELETE_ASK.format(name=ds.name, ref=show(ds.ref)), DELETE_BUTTONS,
               escape=1, default=1) != 0:
            return
        if self.store.delete(ds):
            self.chosen = None
            self.refresh()


def attach(database: Any) -> MinigamePane:
    """Add **Minigame data** to the Database's categories (``database``: its
    ``DatabasePane``). The pane swaps its own list and editor into the Database's columns
    while the category is picked."""
    pane = MinigamePane(database)
    database.add_category(CATEGORY, CATEGORY_TITLE, before=CATEGORY_AFTER)   # design §4.3
    pane.cat_choice = database.category_choice(pane.list_frame)  # narrow windows
    database.on_compact.append(pane.compact)
    pane.compact(database.compact)
    database.cat_tree.bind("<<TreeviewSelect>>", lambda _e: pane.on_category(), add="+")
    database.minigames = pane
    pane.refresh()
    return pane


# --- The Minigame form (Events) ----------------------------------------------------------------

def shown_value(field: mg.ArgField, written: str) -> str:
    """A field's text as the form shows it: a quoted text unquoted (TEXT, CHOICE, METER,
    SOUND),
    ``None`` as empty; else as written."""
    text = written.strip()
    if text == "None" and not field.required:
        return ""
    if field.widget in mg.QUOTED:
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text
        if isinstance(value, str):
            return field.label_of(value) if field.widget == mg.CHOICE else value
    return text


def is_raw(field: mg.ArgField, written: str) -> bool:
    """A TEXT, CHOICE, METER or SOUND value written as an expression (``"hi " + name``): the form
    shows and keeps it as script."""
    text = written.strip()
    if field.widget not in mg.QUOTED or text in ("", "None"):
        return False
    try:
        return not isinstance(ast.literal_eval(text), str)
    except (ValueError, SyntaxError):
        return True


def written_value(field: mg.ArgField, shown: str, *, raw: bool = False) -> str:
    """The script text of what the form shows (``shown_value``'s inverse)."""
    text = shown if field.widget == mg.LONG_TEXT else shown.strip()
    if not text.strip() or (field.widget in (mg.TIP, mg.TIP_CATEGORY) and text == NONE_PICK):
        return ""
    if field.widget == mg.CHOICE and not raw:
        return mg.literal(field.choice_of(text))                     # F52: shown names
    if field.widget in mg.QUOTED and not raw:
        return mg.literal(text)
    if field.widget == mg.TOGGLE:
        return "True" if text in ("1", "True", "true") else "False"
    return text


NONE_PICK = "(none)"            # F55: a TIP or TIP_CATEGORY pick-list's empty row
LONG_TEXT_LINES = 4


class MinigameDialog:
    """The Minigame form over ``win``'s window, filled from ``values`` (``{"line": …}`` or
    None for a new row); built hidden so a test can drive it. ``result`` after OK."""

    def __init__(self, win: Any, values: Mapping[str, str] | None, *, ok: str = OK) -> None:
        from engine.tools.editor import dialogs
        self.win = win
        self.result: dict[str, str] | None = None
        self.store = Store(win)
        self.store.read()
        self.plugin_texts = plugin_texts(win)
        self.games = list(mg.games(self.plugin_texts))
        self.old = mg.read_call(values.get("line", "")) if values else None
        game = self.old.game if self.old is not None else (self.games[0] if self.games else "")
        if game not in self.games:
            self.games.append(game)
        self.dialog = dialog = dialogs._dialog(win.root)
        dialog.title("Minigame")
        body, scale = dialogs._body(dialog)
        self.scale = scale
        self.px = lambda v: round(v * scale)
        top = ttk.Frame(body, style="Dialog.TFrame")
        top.pack(fill="x")
        top.columnconfigure(0, minsize=self.px(LABEL_COLUMN))
        ttk.Label(top, text=GAME, style="Dialog.TLabel").grid(row=0, column=0, sticky="w",
                                                               padx=(0, self.px(16)))
        self.game_var = tk.StringVar(master=dialog, value=mg.game_title(game))
        self.game_box = ttk.Combobox(top, textvariable=self.game_var, state="readonly",
                                     width=26, values=[mg.game_title(g) for g in self.games])
        self.game_box.grid(row=0, column=1, sticky="w")
        self.game_box.bind("<<ComboboxSelected>>", lambda _e: self.set_game(
            self.games[self.game_box.current()]), add="+")
        self.grid = ttk.Frame(body, style="Dialog.TFrame")
        self.grid.pack(fill="x", pady=(self.px(12), 0))
        self.grid.columnconfigure(1, weight=1)
        self.grid.columnconfigure(0, minsize=self.px(LABEL_COLUMN))
        ttk.Label(body, text=LINE_CAPTION, style="Dialog.Hint.TLabel").pack(
            anchor="w", pady=(self.px(16), self.px(4)))
        self.line = ttk.Label(body, text="", style="Dialog.TLabel",
                              font=getattr(win, "fonts", {}).get("code"),
                              wraplength=self.px(520), justify="left")
        self.line.pack(anchor="w")
        self.buttons = dialogs._buttons(dialog, body, (ok, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        self.vars: dict[str, tk.Variable] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self.pickers: dict[str, Any] = {}           # F57: SOUND fields' AssetPickers
        self.tips: dict[str, Any] = {}              # field name → its label's Tooltip
        self.assets = self._assets()
        if self.assets is not None:
            self.assets.on_change = self._sync_play  # a sound ended: ■ back to ▶
        self.form: mg.GameForm | None = None
        self.skip_var = tk.BooleanVar(master=dialog,
                                      value=bool(self.old and self.old.skippable))
        self.set_game(game, first=True)

    def set_game(self, game: str, first: bool = False) -> None:
        for child in self.grid.winfo_children():
            child.destroy()
        self.stop_sound()
        self.vars, self.widgets, self.pickers, self.tips = {}, {}, {}, {}
        self.game = game
        self.game_var.set(mg.game_title(game))
        self.form = mg.form_fields(game, self.plugin_texts)
        if self.form is None:
            ttk.Label(self.grid, text=declplan.COMPLEX, style="Dialog.TLabel").grid(
                row=0, column=0, sticky="w")
            self._changed()
            return
        call = self.old if first or (self.old and self.old.game == game) else None
        values = mg.form_values(self.form, call)
        self.raw = {f.name for f in self.form.fields if is_raw(f, values.get(f.name, ""))}
        gap = self.px(6)
        r = 0
        for field in self.form.fields:
            label = ttk.Label(self.grid, text=field.label, style="Dialog.TLabel")
            label.grid(row=r, column=0, sticky="w", padx=(0, self.px(16)), pady=(gap, 0))
            self._tip(label, field)
            holder = ttk.Frame(self.grid, style="Dialog.TFrame")
            holder.grid(row=r, column=1, sticky="w", pady=(gap, 0))
            self._field(holder, field, shown_value(field, values.get(field.name, "")))
            r += 1
        ttk.Label(self.grid, text=mg.INTO_LABEL, style="Dialog.TLabel").grid(
            row=r, column=0, sticky="w", padx=(0, self.px(16)), pady=(gap, 0))
        into_var = tk.StringVar(master=self.dialog, value=values.get("into", ""))
        into = ttk.Combobox(self.grid, textvariable=into_var, width=24,
                            values=self.store.lookups.variables)
        into.grid(row=r, column=1, sticky="w", pady=(gap, 0))
        self.vars["into"], self.widgets["into"] = into_var, into
        into_var.trace_add("write", lambda *_a: self._changed())
        skip = ttk.Checkbutton(self.grid, text=SKIPPABLE, variable=self.skip_var,
                               style="Dialog.TCheckbutton", command=self._changed)
        skip.grid(row=r + 1, column=1, sticky="w", pady=(gap, 0))
        self._changed()

    def _field(self, holder: ttk.Frame, field: mg.ArgField, value: str) -> None:
        var: tk.Variable
        if field.widget == mg.TOGGLE:
            var = tk.StringVar(master=self.dialog, value="True" if value == "True" else "False")
            widget: tk.Widget = ttk.Checkbutton(holder, variable=var, onvalue="True",
                                                offvalue="False", style="Dialog.TCheckbutton")
        elif field.widget == mg.NUMBER and field.lo is not None and field.hi is not None:
            var = tk.StringVar(master=self.dialog, value=value)
            widget = ttk.Spinbox(holder, from_=field.lo, to=field.hi, increment=1, width=6,
                                 textvariable=var)
        elif field.widget in (mg.CHOICE, mg.DATA, mg.METER, mg.VARIABLE):
            var = tk.StringVar(master=self.dialog, value=value)
            if field.widget == mg.CHOICE:
                values = [field.label_of(c) for c in field.choices]
            elif field.widget == mg.DATA:
                values = self._choices(field)
            elif field.widget == mg.METER:
                values = [""] + self.store.lookups.meters
            else:
                values = [""] + self.store.lookups.variables
            widget = ttk.Combobox(holder, textvariable=var, values=values, width=24,
                                  state="readonly" if field.widget == mg.CHOICE else "normal")
        elif field.widget == mg.SOUND:
            var = tk.StringVar(master=self.dialog, value=value)
            widget = self._sound_field(holder, field, var, value)
        elif field.widget in (mg.TIP, mg.TIP_CATEGORY):                 # F55
            lookups = self.store.lookups
            names = ([n for n, _ in lookups.tips] if field.widget == mg.TIP
                     else list(lookups.tip_categories))
            var = tk.StringVar(master=self.dialog, value=value or NONE_PICK)
            widget = ttk.Combobox(holder, textvariable=var, values=[NONE_PICK] + names,
                                  width=24)
        elif field.widget == mg.LONG_TEXT:                               # F55: 4 lines
            var = tk.StringVar(master=self.dialog, value=value)
            widget = self._long_text(holder, var)
        else:
            var = tk.StringVar(master=self.dialog, value=value)
            widget = ttk.Entry(holder, textvariable=var, width=28)
        widget.pack(side="left")
        if field.widget == mg.DATA and field.data_kind in EDITABLE_KINDS:
            ttk.Button(holder, text=SET_UP, style="Secondary.TButton",
                       command=lambda f=field: self.set_up(f)).pack(side="left",
                                                                    padx=(self.px(8), 0))
            ttk.Button(holder, text=NEW_SET, style="Secondary.TButton",
                       command=lambda f=field: self.new_set(f)).pack(side="left",
                                                                     padx=(self.px(4), 0))
        self.vars[field.name], self.widgets[field.name] = var, widget
        var.trace_add("write", lambda *_a: self._changed())
        if field.data_kind == mg.TESTIMONY:
            var.trace_add("write", lambda *_a: self._answer_for(str(var.get()).strip()))

    # -- F57: hints and the Sound field --------------------------------------------------

    def _tip(self, label: ttk.Label, field: mg.ArgField) -> None:
        """The field's plain-words hint (``fieldhints.minigame_hint``) as its label's
        tooltip."""
        from engine.tools.editor.fieldhints import minigame_hint
        hint = minigame_hint(self.game, field.name)
        if hint:
            from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
            self.tips[field.name] = Tooltip(label, hint)

    def _assets(self) -> Any:
        """The window's form assets (▶/■ through the helper child), or None."""
        story = getattr(self.win, "story", None)
        make = getattr(story, "form_assets", None)
        return make() if make is not None else None

    def audio_refs(self) -> list[str]:
        """The game's sound files as a line writes them (``audio/`` left out)."""
        project = getattr(self.win, "project", None)
        refs = project.file_refs("audio") if project is not None else []
        return [ref[len(AUDIO_PREFIX):] for ref in refs if ref.startswith(AUDIO_PREFIX)]

    def _sound_field(self, holder: ttk.Frame, field: mg.ArgField, var: tk.StringVar,
                     value: str) -> tk.Widget:
        """Game settings' audio field (``fieldwidgets.AssetPicker``): the files in
        ``audio/`` and ▶/■; None (empty) writes nothing."""
        from engine.tools.editor.fieldwidgets import AssetPicker
        refs = self.audio_refs()
        if value and value not in refs:
            refs.append(value)
        picker = AssetPicker(holder, refs, value or None, none_text=NO_SOUND,
                             on_change=lambda new: var.set(new or ""),
                             play=lambda ref: self.toggle_sound(field.name), width=26,
                             scale=self.scale)

        def follow(*_a: object) -> None:
            shown = str(var.get()).strip() or None
            if picker.value != shown:
                picker.set(shown)
            self._sync_play()

        var.trace_add("write", follow)
        self.pickers[field.name] = picker
        return picker.widget

    def toggle_sound(self, name: str) -> None:
        """▶ plays field ``name``'s sound; ■ (it is playing) stops it."""
        value = str(self.vars[name].get()).strip()
        if self.assets is None or not value:
            return
        if self.assets.playing() == value:
            self.assets.stop()
        else:
            self.assets.play(value)
        self._sync_play()

    def stop_sound(self) -> None:
        assets = getattr(self, "assets", None)
        if assets is not None and assets.playing() is not None:
            assets.stop()

    def _sync_play(self) -> None:
        playing = self.assets.playing() if self.assets is not None else None
        for name, picker in self.pickers.items():
            value = str(self.vars[name].get()).strip() if name in self.vars else ""
            try:
                picker.set_playing(bool(value) and playing == value)
            except tk.TclError:
                pass

    def _choices(self, field: mg.ArgField) -> list[str]:
        found = list(mg.data_choices(field, self.store.sets))
        if field.data_kind == mg.ANSWER:        # Studio's new answers no line names yet
            found += sorted(self.store.answer_names() - set(found))
        return found

    def _answer_for(self, testimony: str) -> None:
        """Picking a testimony fills in its answer while the answer is empty."""
        answer = self.vars.get("answer")
        ds = self.store.find(mg.TESTIMONY, testimony)
        if answer is None or str(answer.get()).strip() or ds is None:
            return
        found = self.store.answer_of(ds)
        if found is not None:
            answer.set(found.name)

    def values(self) -> dict[str, str]:
        """Each field's script text (``minigamedata.call_from_form``'s values)."""
        assert self.form is not None
        out = {f.name: written_value(f, str(self.vars[f.name].get()), raw=f.name in self.raw)
               for f in self.form.fields}
        out["into"] = str(self.vars["into"].get()).strip()
        return out

    def call(self) -> mg.Call | Refuse | None:
        if self.form is None:
            return None
        old = self.old if self.old is not None and self.old.game == self.game else None
        return mg.call_from_form(self.form, self.values(), skippable=bool(self.skip_var.get()),
                                 old=old)

    def preview(self) -> str:
        call = self.call()
        if not isinstance(call, mg.Call):
            return ""
        return mg.call_line(replace(call, indent="", comment=""))

    def _changed(self) -> None:
        call = self.call()
        if isinstance(call, Refuse):
            self.line.configure(text=call.text, foreground=THEME["muted"])
        else:
            self.line.configure(text=self.preview(), foreground=THEME["foreground"])

    def set(self, name: str, text: str) -> None:
        """Type ``text`` into the field ``name`` as the form shows it (tests)."""
        self.vars[name].set(text)

    def _long_text(self, holder: ttk.Frame, var: tk.StringVar) -> tk.Text:
        """F55: a 4-line text box kept in step with ``var`` both ways."""
        box = tk.Text(holder, height=LONG_TEXT_LINES, width=40, wrap="word", undo=True)
        box.insert("1.0", var.get())

        def from_box(_event: object = None) -> None:
            text = box.get("1.0", "end-1c")
            if text != var.get():
                var.set(text)

        def from_var(*_args: object) -> None:
            if box.get("1.0", "end-1c") != var.get():
                box.delete("1.0", "end")
                box.insert("1.0", var.get())

        box.bind("<KeyRelease>", from_box, add="+")
        box.bind("<FocusOut>", from_box, add="+")
        var.trace_add("write", from_var)
        return box

    def _refresh_sets(self, field: mg.ArgField, pick: str | None = None) -> None:
        self.store.read()
        for other in self.form.fields if self.form is not None else ():
            widget = self.widgets.get(other.name)
            if other.widget == mg.DATA and isinstance(widget, ttk.Combobox):
                widget.configure(values=self._choices(other))
        if pick is not None:
            self.vars[field.name].set(pick)

    def set_up(self, field: mg.ArgField) -> None:
        """Set up…: the picked data set's editor in a window of its own."""
        name = str(self.vars[field.name].get()).strip()
        self.store.read()
        ds = self.store.find(field.data_kind or "", name)
        if ds is None:
            self.new_set(field)
            return
        DataDialog(self.win, self.dialog, ds).run()
        self._refresh_sets(field)

    def new_set(self, field: mg.ArgField) -> None:
        if field.data_kind not in EDITABLE_KINDS:
            return
        name = new_data(self.win, self.store, field.data_kind)
        if name is not None:
            self._refresh_sets(field, name)

    def _pick(self, index: int) -> None:
        if index == 0:
            call = self.call()
            if isinstance(call, Refuse):
                show_error(self.dialog, call.text)
                return
            if call is None:
                return
            self.result = {"line": mg.call_line(replace(call, indent="", comment=""))}
        self.stop_sound()                            # closing the form stops the sound
        if self.assets is not None and self.assets.on_change == self._sync_play:
            self.assets.on_change = None
        self.dialog.destroy()

    def run(self) -> dict[str, str] | None:
        from engine.tools.editor import dialogs
        dialogs._run(self.win.root, self.dialog, self.game_box)
        return self.result


class DataDialog:
    """One data set's editor in its own modal window (the Minigame form's Set up…)."""

    def __init__(self, win: Any, parent: tk.Misc, ds: mg.DataSet) -> None:
        from engine.tools.editor import dialogs
        self.parent = parent
        self.dialog = dialog = dialogs._dialog(parent)
        dialog.resizable(True, True)
        dialog.title(f"{mg.KIND_TITLES[ds.kind]}: {ds.name}")
        body, _scale = dialogs._body(dialog)
        self.store = Store(win)
        self.store.read()
        self.host = EditorHost(win, dialog, self.store)
        self.editor = editor_for(self.host, body, ds)
        if self.editor is None:
            complex_box(body, win, ds, self.host.px).pack(anchor="w")
        else:
            self.editor.frame.pack(fill="both", expand=True)
        self.buttons = dialogs._buttons(dialog, body, (CLOSE,), lambda _i: self.close())
        dialog.bind("<Escape>", lambda _e: self.close())
        dialog.protocol("WM_DELETE_WINDOW", self.close)

    def close(self) -> None:
        if self.editor is not None:
            focused = self.dialog.focus_get()
            if focused is not None:                 # commit a field still being typed in
                focused.event_generate("<FocusOut>")
        self.dialog.destroy()

    def run(self) -> None:
        from engine.tools.editor import dialogs
        dialogs._run(self.parent, self.dialog, self.buttons[0])


def plugin_texts(win: Any) -> dict[str, str]:
    """The game's minigame plugins (``minigames/*.py``): ref → source, read as text."""
    out: dict[str, str] = {}
    project = getattr(win, "project", None)
    for ref in (project.file_refs("minigames") if project is not None else []):
        if not ref.endswith(".py"):
            continue
        try:
            path = win.paths.root / ref
            if path.stat().st_size <= 256 * 1024:
                out[ref] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return out


def edit_minigame(win: Any, values: Mapping[str, str] | None) -> dict[str, str] | None:
    """The Minigame form, modal: ``{"line": …}`` after OK, None after Cancel."""
    return MinigameDialog(win, values).run()


__all__ = ["CATEGORY", "CATEGORY_TITLE", "ChatEditor", "DataDialog", "Editor", "EditorHost",
           "EvidenceEditor", "Lookups", "MinigameDialog", "MinigamePane", "PoemEditor",
           "RoomEditor", "Store", "attach", "edit_minigame", "editor_for", "new_data",
           "is_raw", "plugin_texts", "shown_value", "starter", "written_value"]
