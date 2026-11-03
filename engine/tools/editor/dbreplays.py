"""The Database's **Scene replays** category (F36 ``01-design.md`` §7; ``04-technical.md``
§3, W4; AC-F36-29, 30, 31, 34).

Why this module exists: Extras ▸ Scenes lets players watch a scene again once they've
reached it. A non-programmer never types ``lock replay``: in Database ▸ **Scene replays**
they click **+ New replay…**, pick a scene, and Studio writes one line into
``database.vns`` with a title made from the scene (its Flowchart title, else its name). The
form changes the scene, the title, the tile's picture (a thumbnail picker whose first choice
is the scene's first background), where the replay ends (when the scene ends, or on
reaching another scene) and the **starting values** (a story variable and its value, the
value field following the variable's kind, up to 32). **◀ Move earlier** / **Move later ▶**
reorder the Scenes page (``declplan.plan_move``); **▶ Play replay** runs the game's dev
``run --replay <scene>`` and **▶ Preview Extras** its ``run --extras replays``, both through
the Play bar. Database ▸ Endings & routes gives each ending the same **▶ Play replay**
(``ending_replay_button``) while ``[endings] replay`` is on.

``ReplaysCategory`` is a mixin of ``database.DatabasePane`` (as ``dbextras``'s): the pane's
tree holds the numbered rows in the Scenes page's order; a small bar under it holds the move
and preview buttons. Every write is a ``declplan`` plan applied through the pane's
``_write``. Declarations are read from the script texts (``declarations.scan``), so the list
shows without a check. Delete is refused while an Unlock or Forget scene replay event
names the scene.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import importlib.util
import tkinter as tk
import tomllib
from collections.abc import Callable, Mapping, Sequence
from tkinter import ttk
from typing import Any

from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan
from engine.tools.editor.dbmore import Row
from engine.tools.editor.dialogs import ask, show_error
from engine.tools.editor.fieldwidgets import (
    AssetPicker,
    ChoiceField,
    FormGrid,
    TextField,
)
from engine.tools.editor.formdialogs import pick_scene
from engine.tools.editor.scriptedit import STALE

# --- Texts (design §7; the rest in the same voice) --------------------------------------------

ABOUT_REPLAYS = ("Scene replays let players watch a scene again from Extras. A replay never "
                 "changes their saves or progress.")
EMPTY_HINT = "Add scenes players can watch again."
NEW_REPLAY = "+ New replay…"
NEW = "+ New"
MOVE_EARLIER = "◀ Move earlier"
MOVE_LATER = "Move later ▶"
ACROSS_FILES = "This replay is declared in another file; move it there."
PREVIEW = "▶ Preview Extras"
PREVIEW_TIP = "Opens Extras ▸ Scenes with every scene open. Nothing is saved."
PLAY = "▶ Play replay"
PLAY_TIP = "Plays the scene as players see it from Extras. Nothing is saved."
NOT_YET = ("This engine can't play scene replays yet; it comes with the Scenes page in "
           "Extras.")
PICK_TITLE = "New scene replay"
PICK_OK = "Add"
NO_SCENES = "Every scene has a replay already, or the story has no scenes yet."
LABEL_SCENE = "Scene"
LABEL_TITLE = "Title"
LABEL_PICTURE = "Picture"
LABEL_ENDS = "Ends"
GO_TO = "Go to"
FIRST_BACKGROUND = "(scene's first background)"
ENDS_SCENE = "When the scene ends"
ENDS_AT = "At scene"
ENDS_PICK = "Pick the scene that ends the replay when the story reaches it."
STARTING = "Starting values"
STARTING_HELP = ("In a replay, variables start at their starting values. Set any the scene "
                 "needs, such as the player's name.")
ADD_VALUE = "+ Add a starting value"
NO_VARIABLES = "Your story has no variables yet. Add them under Variables."
VALUES_FULL = "A replay holds up to {n} starting values."
ALL_SET = "Every story variable has a starting value here."
REMOVE = "Remove"
YES, NO = "Yes", "No"
NOTHING = "(nothing)"
INFO = "Players unlock this replay the first time they reach the scene."
NO_SCENE = "⚠ There is no scene called {name}. Pick another scene."
SCENE_LOCKED = "Unlock or Forget scene replay events name this scene, so it can't change here."
NAMED_IN = "Named in {lines}"
NOT_NAMED = "No Unlock or Forget events name it yet"
USES_HEAD = "{name} is named in {lines}:"
DELETE = "Delete"
DELETE_ASK = ("Delete the scene replay “{title}”? Its line is removed from {ref}; Edit ▸ Undo "
              "there brings it back.")
DELETE_BUTTONS = ("Delete", "Cancel")
USED_REFUSED = ("“{title}” is named in {lines} (Unlock or Forget scene replay), so it can't be "
                "deleted yet.")
REFUSED_BUTTONS = (db.SHOW_USES, "OK")
TOO_MANY = "A story holds up to {n} scene replays."
REPLAY_ON_HINT = "Players can replay this ending from Extras once they've reached it."

REPLAY_PREFIX = "w:"
EXTRAS_PAGE = "replays"
REPLAYS_MAX = 500
MOVE_STYLE = "Move.Secondary.TButton"


def replay_ready() -> bool:
    """True when this engine's ``run`` has the dev ``--replay`` flag (F36-W3 adds it with
    ``engine/app/replays.py``); reads no code."""
    try:
        return importlib.util.find_spec("engine.app.replays") is not None
    except (ImportError, ValueError):
        return False


def lines_word(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def endings_replay_on(config_text: str | None) -> bool:
    """``[endings] replay`` of a config.toml text (on unless written ``false``; a text that
    doesn't read: on)."""
    if not config_text:
        return True
    try:
        data = tomllib.loads(config_text)
    except (tomllib.TOMLDecodeError, ValueError):
        return True
    section = data.get("endings")
    return not (isinstance(section, dict) and section.get("replay") is False)


def value_kind(value: object) -> str:
    """The Variables kind a starting value reads as (None: Text)."""
    if type(value) is bool:
        return dec.YES_NO
    if type(value) in (int, float):
        return dec.NUMBER
    return dec.TEXT


def number_of(text: str) -> int | float | None:
    """A typed number (``3``, ``-2``, ``2.5``), or None."""
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        value = float(text)
    except ValueError:
        return None
    return value if dec.start_value_ok(value) else None


def number_text(value: object) -> str:
    return repr(value) if isinstance(value, float) else str(value)


class _Rebuilt:
    """A drop-down whose pick rewrites the declaration, which rebuilds the form: showing the
    value afterwards on the destroyed widget does nothing."""

    box: Any

    def _show(self) -> None:
        try:
            if not self.box.winfo_exists():
                return
        except (tk.TclError, AttributeError):
            pass
        super()._show()                                             # type: ignore[misc]

    def _picked(self) -> None:
        try:
            super()._picked()                                       # type: ignore[misc]
        except tk.TclError:                                         # the write rebuilt it
            pass


class _Choice(_Rebuilt, ChoiceField):
    pass


class _Picker(_Rebuilt, AssetPicker):
    pass


# --- The mixin --------------------------------------------------------------------------------

class ReplaysCategory:
    """Database ▸ Scene replays and the ending rows' ▶ Play replay (a mixin of
    ``database.DatabasePane``: it uses the pane's rows, forms and writers)."""

    win: Any
    root: Any
    scale: float
    texts: dict[str, str]
    decls: tuple[dec.Decl, ...]
    names: Mapping
    rows: dict[str, list[Row]]
    form: Any
    category: str
    chosen: dict[str, str | None]
    list_body: Any
    list_tree: Any
    new_button: Any
    empty: Any
    _px: Callable[[float], int]
    _check_ran: Callable[[], bool]
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
    replay_bar: Any = None
    replay_moves: tuple[Any, Any] | None = None
    replay_note: Any = None
    replay_preview: Any = None
    replay_preview_tip: Any = None
    replay_play_tip: Any = None
    ending_play: Any = None                 # the ending form's ▶ Play replay (or None)

    # --- Rows -------------------------------------------------------------------------------

    def _replay_rows(self) -> list[Row]:
        return [Row(REPLAY_PREFIX + e.name, f"{n}.  {e.shown}", e.name, e)
                for n, e in enumerate(db.replay_entries(self.decls, self.texts), start=1)]

    def replay_entries(self) -> list[db.Entry]:
        """The Scene replays category's entries in the Scenes page's order (as listed)."""
        return [r.entry for r in self.rows.get(db.CATEGORY_REPLAY, ()) if r.entry is not None]

    def scene_names(self) -> list[str]:
        """Every scene (label) of the story: the texts' ``label`` lines and the window's
        scenes (the last check, the Story map), sorted."""
        names = set(dec.label_places(self.texts))
        more = getattr(self.win, "_scene_names", None)
        if callable(more):
            try:
                names.update(more())
            except Exception:  # noqa: BLE001  (the texts' labels are enough)
                pass
        return sorted(names, key=str.casefold)

    def story_variables(self) -> dict[str, tuple[str, object]]:
        """Each story variable (``default``, not remembered) → (kind, starting value), in
        the Variables list's order."""
        out: dict[str, tuple[str, object]] = {}
        for decl in self.decls:
            if decl.kind == dec.VARIABLE and decl.name not in out:
                values = decl.values or {}
                kind = str(values.get("kind") or "")
                out[decl.name] = (kind, values.get("value")) if kind else ("", None)
        for name in db.variable_names(self.decls, self.names):
            out.setdefault(name, ("", None))
        return out

    def _replay_places(self, name: str) -> list[tuple[str, int]]:
        """The ``lock|unlock replay`` lines naming scene ``name``."""
        return list(dict.fromkeys((ref, line) for scene, ref, line, _u in
                                  dec.replay_uses(self.texts) if scene == name))

    # --- The list column --------------------------------------------------------------------

    def _build_replay_bar(self) -> None:
        px = self._px
        bar = self.replay_bar = ttk.Frame(self.list_body)
        moves = ttk.Frame(bar)
        moves.pack(fill="x")
        moves.columnconfigure((0, 1), weight=1, uniform="move")
        ttk.Style(self.root).configure(MOVE_STYLE, padding=(px(4), px(4)))
        earlier = ttk.Button(moves, text=MOVE_EARLIER, style=MOVE_STYLE, width=1,
                             command=lambda: self.move_replay(-1))
        earlier.grid(row=0, column=0, sticky="ew")
        later = ttk.Button(moves, text=MOVE_LATER, style=MOVE_STYLE, width=1,
                           command=lambda: self.move_replay(1))
        later.grid(row=0, column=1, sticky="ew", padx=(px(6), 0))
        self.replay_moves = (earlier, later)
        self.replay_note = ttk.Label(bar, text="", style="Hint.TLabel", justify="left",
                                     wraplength=px(200))
        ready = replay_ready()
        self.replay_preview = ttk.Button(bar, text=PREVIEW, command=self.preview_replays,
                                         state="normal" if ready else "disabled")
        self.replay_preview.pack(anchor="w", pady=(px(8), 0))
        from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
        self.replay_preview_tip = Tooltip(self.replay_preview,
                                          PREVIEW_TIP if ready else f"{PREVIEW_TIP} {NOT_YET}")
        for key, step in (("<Alt-Up>", -1), ("<Alt-Down>", 1)):
            self.list_tree.bind(key, lambda _e, s=step: (self.move_replay(s), "break")[1]
                                if self.category == db.CATEGORY_REPLAY else None, add="+")

    def _replay_after_fill(self, has_entries: bool) -> None:
        """After the list is filled: the bar under it, the + button's and empty state's
        words."""
        on = self.category == db.CATEGORY_REPLAY
        if on and self.replay_bar is None:
            self._build_replay_bar()
        bar = self.replay_bar
        if bar is not None:
            if on and has_entries and not bar.winfo_ismapped():
                bar.pack(side="bottom", fill="x", padx=self._px(8),
                         pady=(self._px(6), self._px(8)), before=self.list_tree)
            elif not (on and has_entries) and bar.winfo_ismapped():
                bar.pack_forget()
        if not on:
            return
        self.new_button.configure(text=NEW_REPLAY)
        if not has_entries:
            self.empty.hint.configure(text=EMPTY_HINT)
            if self.empty.button is not None:
                self.empty.button.configure(text=NEW_REPLAY)
        self._sync_replay_moves()

    def _sync_replay_moves(self) -> None:
        if self.replay_moves is None:
            return
        earlier, later = self.replay_moves
        row = self.selected_row() if self.category == db.CATEGORY_REPLAY else None
        entries = self.replay_entries()
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
        earlier.configure(state=states[0])
        later.configure(state=states[1])
        ready = replay_ready()
        self.replay_preview.configure(state="normal" if ready else "disabled")
        self.replay_preview_tip.text = PREVIEW_TIP if ready else f"{PREVIEW_TIP} {NOT_YET}"
        self.replay_note.configure(text=note)
        if note and not self.replay_note.winfo_ismapped():
            self.replay_note.pack(anchor="w", pady=(self._px(4), 0), before=self.replay_preview)
        elif not note and self.replay_note.winfo_ismapped():
            self.replay_note.pack_forget()

    # --- Writes -----------------------------------------------------------------------------

    def new_replay(self) -> bool:
        """+ New replay…: pick a scene; its replay joins the end of the Scenes page with a
        title made from the scene."""
        self.texts = self._read_texts()
        decls = dec.scan(self.texts)
        taken = {d.name for d in decls if d.kind == dec.REPLAY}
        if len(taken) >= REPLAYS_MAX:
            show_error(self.root, TOO_MANY.format(n=REPLAYS_MAX))
            return False
        scenes = [s for s in self.scene_names() if s not in taken]
        if not scenes:
            show_error(self.root, NO_SCENES)
            return False
        label = pick_scene(self.root, scenes, title=PICK_TITLE, ok=PICK_OK)
        if not label:
            return False
        return self.add_replay(label)

    def add_replay(self, label: str) -> bool:
        """Add scene ``label``'s replay at the end (one undo step) and show it."""
        self.texts = self._read_texts()
        values = {"title": dec.scene_title(label, self.texts), "image": None, "to": None,
                  "values": ()}
        if self.category != db.CATEGORY_REPLAY:
            self.select_category(db.CATEGORY_REPLAY)
        return self._write(declplan.plan_new(dec.REPLAY, label, values, self.texts),
                           select=REPLAY_PREFIX + label)

    def _now_replay(self, entry: db.Entry) -> dec.Decl | None:
        decl = self._fresh(entry)
        if decl is None or decl.values is None:
            show_error(self.root, STALE)
            self.refresh()
            return None
        return decl

    def set_replay_scene(self, entry: db.Entry, scene: object) -> bool:
        """The Scene field: the replay plays another scene (kept in its place; a ``to``
        naming that scene is dropped)."""
        if not isinstance(scene, str) or scene == entry.name:
            return True
        decl = self._now_replay(entry)
        if decl is None:
            return False
        values = dict(decl.values)                                  # type: ignore[arg-type]
        if values.get("to") == scene:
            values["to"] = None
        return self._write(declplan.plan_edit(decl, values, self.texts, name=scene),
                           select=REPLAY_PREFIX + scene)

    def set_replay_end(self, entry: db.Entry, to: object) -> bool:
        """Ends: None (when the scene ends) or the scene that ends it."""
        if to is not None and not isinstance(to, str):
            return True
        return self._edit(entry, {"to": to})

    def _end_choice(self, entry: db.Entry, choice: str) -> bool:
        """The Ends radio: "When the scene ends" writes at once; "At scene" waits for a
        scene in its box."""
        if choice == "scene":
            return self.set_replay_end(entry, None)
        box = self.form.fields.get("to") if self.form is not None else None
        if box is not None:
            box.enable(True)
            hint = self.form.fields.get("to_hint")
            if hint is not None:
                hint.configure(text=ENDS_PICK)
        return True

    def set_start_value(self, entry: db.Entry, index: int, variable: str | None = None,
                        value: object = ...) -> bool:
        """Change starting value ``index`` (-1: add one at the end); a new variable of
        another kind starts from its own starting value."""
        decl = self._now_replay(entry)
        if decl is None:
            return False
        pairs = [tuple(p) for p in decl.values["values"]]           # type: ignore[union-attr]
        known = self.story_variables()
        if index < 0:
            if len(pairs) >= dec.REPLAY_VALUES_MAX:
                show_error(self.root, VALUES_FULL.format(n=dec.REPLAY_VALUES_MAX))
                return False
            used = {n for n, _v in pairs}
            variable = variable or next((n for n in known if n not in used), None)
            if variable is None:
                return False
            kind, start = known.get(variable, ("", None))
            pairs.append((variable, start if start is not None or kind else 0))
        else:
            old_name, old_value = pairs[index]
            name = variable or old_name
            if value is ...:
                value = old_value
                kind = known.get(name, ("", None))[0]
                if name != old_name and kind and kind != value_kind(old_value):
                    value = known[name][1]
            pairs[index] = (name, value)
        return self._write(declplan.plan_edit(decl, {**decl.values,  # type: ignore[dict-item]
                                                     "values": tuple(pairs)}, self.texts),
                           select=REPLAY_PREFIX + decl.name)

    def remove_start_value(self, entry: db.Entry, index: int) -> bool:
        decl = self._now_replay(entry)
        if decl is None:
            return False
        pairs = [p for i, p in enumerate(decl.values["values"])     # type: ignore[union-attr]
                 if i != index]
        return self._write(declplan.plan_edit(decl, {**decl.values,  # type: ignore[dict-item]
                                                     "values": tuple(pairs)}, self.texts),
                           select=REPLAY_PREFIX + decl.name)

    def delete_replay(self, entry: db.Entry | None = None, *, confirm: bool = True) -> bool:
        """Delete (asks): refused while an Unlock or Forget scene replay event names it."""
        if entry is None:
            row = self.selected_row()
            entry = row.entry if row is not None else None
            if entry is None or entry.kind != dec.REPLAY:
                return False
        self.texts = self._read_texts()
        places = self._replay_places(entry.name)
        if places:
            text = USED_REFUSED.format(title=entry.shown, lines=lines_word(len(places)))
            if ask(self.root, text, REFUSED_BUTTONS, escape=1, default=1) == 0:
                self.show_replay_uses(entry.shown, places)
            return False
        decl = self._fresh(entry)
        if decl is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        if confirm and ask(self.root, DELETE_ASK.format(title=entry.shown, ref=decl.ref),
                           DELETE_BUTTONS, escape=1, default=1) != 0:
            return False
        if self.category == db.CATEGORY_REPLAY:
            self.chosen[db.CATEGORY_REPLAY] = None
        return self._write(declplan.plan_delete(decl, self.texts))

    def move_replay(self, step: int) -> bool:
        """◀ Move earlier (-1) / Move later ▶ (+1): swap the selected replay's lines with its
        neighbour's (``declplan.plan_move``; refused across files)."""
        row = self.selected_row()
        if row is None or row.entry is None or row.entry.kind != dec.REPLAY \
                or self.search_text().strip():
            return False
        entries = self.replay_entries()
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

    def play_replay(self, label: str) -> None:
        """▶ Play replay: the game plays scene ``label`` as a replay (dev ``run --replay``),
        through the Play bar."""
        play = getattr(self.win, "play_replay", None)
        if callable(play) and replay_ready():
            play(label)

    def preview_replays(self) -> None:
        """▶ Preview Extras: the game opens on Extras ▸ Scenes with every scene open in
        memory (dev ``run --extras replays``)."""
        play = getattr(self.win, "play_extras", None)
        if callable(play) and replay_ready():
            play(EXTRAS_PAGE)

    def show_replay_uses(self, title: str, places: Sequence[tuple[str, int]]) -> None:
        """Show uses: the Unlock and Forget scene replay lines, in the Problems panel."""
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

    def replay_play_button(self, parent: tk.Misc, label: str, *,
                           tip: str = PLAY_TIP) -> ttk.Button:
        """A ▶ Play replay button for scene ``label`` (disabled, saying why, while this
        engine can't play replays)."""
        ready = replay_ready()
        button = ttk.Button(parent, text=PLAY, style="Secondary.TButton",
                            command=lambda: self.play_replay(label),
                            state="normal" if ready else "disabled")
        from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
        self.replay_play_tip = Tooltip(button, tip if ready else f"{tip} {NOT_YET}")
        return button

    def ending_replay_button(self, parent: tk.Misc, label: str | None) -> ttk.Button | None:
        """Endings & routes: an ending's ▶ Play replay (its scene), while ``[endings]
        replay`` is on."""
        self.ending_play = None
        if not label or not endings_replay_on(self._config_text()):
            return None
        self.ending_play = self.replay_play_button(parent, label, tip=REPLAY_ON_HINT)
        return self.ending_play

    def _config_text(self) -> str | None:
        live = getattr(self, "_live_config", None)
        try:
            text = live() if callable(live) else None
        except Exception:  # noqa: BLE001  (no open config: read the file)
            text = None
        if text is None:
            try:
                text = (self.win.paths.root / "config.toml").read_text("utf-8")
            except (OSError, AttributeError, UnicodeDecodeError):
                return None
        return text

    # --- The form ---------------------------------------------------------------------------

    def _replay_thumb_ready(self, _ref: str) -> None:
        """A thumbnail arrived: the Picture field shows it."""
        field = self.form.fields.get("picture") if self.form is not None and \
            self.category == db.CATEGORY_REPLAY else None
        if isinstance(field, _Picker):
            field._show()

    def _replay_key(self, entry: db.Entry, shape: tuple) -> tuple:
        values = dict(entry.decl.values or {}) if entry.decl is not None else {}
        return shape + (values.get("image"), values.get("to"), tuple(values.get("values") or ()),
                        tuple(self.scene_names()), tuple(self.story_variables().items()),
                        tuple(self._replay_places(entry.name)), replay_ready())

    def _replay_form(self, row: Row, key: tuple) -> None:
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
        scenes = self.scene_names()
        places = self._replay_places(entry.name)
        taken = {e.name for e in self.replay_entries()}

        line = ttk.Frame(grid.frame)
        if places:                      # events name it: the scene stays
            ttk.Label(line, text=entry.name).pack(side="left")
        else:
            free = [s for s in scenes if s not in taken or s == entry.name]
            if entry.name not in free:
                free.append(entry.name)
            f["scene"] = _Choice(line, [(s, s) for s in free], entry.name, width=14,
                                     on_change=lambda v: self.set_replay_scene(entry, v))
            f["scene"].widget.pack(side="left")
        place = dec.label_places(self.texts).get(entry.name)
        if place is not None:
            f["go"] = ttk.Button(line, text=GO_TO, style="Link.Ghost.TButton", cursor="hand2",
                                 command=lambda: self.win.jump_to(*place))
            f["go"].pack(side="left", padx=(px(8), 0))
        grid.row(LABEL_SCENE, line, hint=SCENE_LOCKED if places else None)
        if entry.name not in scenes:
            grid.widget(ttk.Label(grid.frame, text=NO_SCENE.format(name=entry.name),
                                  style="Hint.TLabel", justify="left"), pady=(0, 4))

        f["title"] = TextField(grid.frame, str(values["title"]), width=30,
                               check=lambda t: 0 < len(t.strip()) <= dec.REPLAY_TITLE_MAX,
                               on_change=lambda v: self._edit(entry, {"title": str(v).strip()}))
        grid.row(LABEL_TITLE, f["title"])

        image = values.get("image")
        pictures = self.picture_names()
        if isinstance(image, str) and image not in pictures:
            pictures.append(image)
        f["picture"] = _Picker(grid.frame, pictures, image if isinstance(image, str)
                                   else None, width=22, none_text=FIRST_BACKGROUND,
                                   thumb=self.picture_thumb, scale=self.scale,
                                   on_change=lambda v: self._edit(entry, {"image": v}))
        grid.row(LABEL_PICTURE, f["picture"])

        to = values.get("to")
        ends = ttk.Frame(grid.frame)
        from engine.tools.editor.dbextras import _radio_style
        style = _radio_style(self.root)
        var = f["ends_var"] = tk.StringVar(master=ends, value="at" if to else "scene")
        f["ends"] = {}
        f["ends"]["scene"] = ttk.Radiobutton(ends, text=ENDS_SCENE, value="scene", variable=var,
                                             style=style,
                                             command=lambda: self._end_choice(entry, "scene"))
        f["ends"]["scene"].pack(anchor="w", pady=(px(2), px(2)))
        at = ttk.Frame(ends)
        at.pack(anchor="w", fill="x")
        f["ends"]["at"] = ttk.Radiobutton(at, text=ENDS_AT, value="at", variable=var,
                                          style=style,
                                          command=lambda: self._end_choice(entry, "at"))
        f["ends"]["at"].pack(side="left", pady=(px(2), px(2)))
        others = [s for s in scenes if s != entry.name]
        if isinstance(to, str) and to not in others:
            others.append(to)
        f["to"] = _Choice(at, [(s, s) for s in others], to, width=18,
                              on_change=lambda v: self.set_replay_end(entry, v))
        f["to"].widget.pack(side="left", padx=(px(8), 0))
        f["to"].enable(bool(to))
        f["to_hint"] = ttk.Label(ends, text="", style="Hint.TLabel", justify="left")
        f["to_hint"].pack(anchor="w")
        if not others:
            f["ends"]["at"].configure(state="disabled")
        grid.caption(LABEL_ENDS)
        grid.widget(ends, pady=(2, 2))

        self._start_values(grid, form, entry, values)

        f["info"] = ttk.Label(grid.frame, text=INFO, style="Hint.TLabel", justify="left")
        grid.widget(f["info"], pady=(12, 2))
        uses = ttk.Frame(grid.frame)
        ttk.Label(uses, text=NAMED_IN.format(lines=lines_word(len(places))) if places
                  else NOT_NAMED).pack(side="left")
        if places:
            ttk.Button(uses, text=db.SHOW_USES, style="Link.Ghost.TButton", cursor="hand2",
                       command=lambda: self.show_replay_uses(entry.shown, places)).pack(
                side="left", padx=(px(8), 0))
        grid.widget(uses, pady=(2, 0))

        bottom = ttk.Frame(body)
        bottom.grid(row=2, column=0, sticky="ew", pady=(px(20), 0))
        f["play"] = self.replay_play_button(bottom, entry.name)
        f["play"].pack(side="left")
        f["delete"] = ttk.Button(bottom, text=DELETE, style="Secondary.TButton",
                                 command=lambda: self.delete_replay(entry))
        f["delete"].pack(side="right")

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            title.configure(text=entry.shown)
            f["title"].set(str(entry.decl.values["title"]))

        form.update = update
        self._sync_replay_moves()

    def _start_values(self, grid: FormGrid, form: Any, entry: db.Entry,
                      values: Mapping[str, object]) -> None:
        """Starting values: a variable picker, its value (by the variable's kind) and
        Remove per line; + Add a starting value."""
        px = self._px
        f = form.fields
        grid.caption(STARTING)
        grid.widget(ttk.Label(grid.frame, text=STARTING_HELP, style="Hint.TLabel",
                              justify="left"), pady=(0, 4))
        known = self.story_variables()
        pairs = list(values.get("values") or ())                    # type: ignore[call-overload]
        f["values"] = []
        table = ttk.Frame(grid.frame)
        table.columnconfigure(1, weight=1)
        for index, (name, value) in enumerate(pairs):
            names = [n for n in known if n == name or n not in {p[0] for p in pairs}]
            if name not in names:
                names.append(name)
            pick = _Choice(table, [(n, n) for n in names], name, width=12,
                           on_change=lambda v, i=index: self.set_start_value(
                               entry, i, variable=str(v)))
            pick.widget.grid(row=index, column=0, sticky="w", pady=(px(2), px(2)))
            kind = known.get(name, ("", None))[0] or value_kind(value)
            field = self._value_field(table, entry, index, kind, value)
            field.widget.grid(row=index, column=1, sticky="w", padx=(px(8), 0))
            remove = ttk.Button(table, text=REMOVE, style="Link.Ghost.TButton", cursor="hand2",
                                command=lambda i=index: self.remove_start_value(entry, i))
            remove.grid(row=index, column=2, sticky="w", padx=(px(4), 0))
            f["values"].append((pick, field, remove))
        if pairs:
            grid.widget(table, pady=(0, 2))
        free = [n for n in known if n not in {p[0] for p in pairs}]
        full = len(pairs) >= dec.REPLAY_VALUES_MAX
        f["add_value"] = ttk.Button(grid.frame, text=ADD_VALUE, style="Secondary.TButton",
                                    command=lambda: self.set_start_value(entry, -1),
                                    state="normal" if free and not full else "disabled")
        grid.widget(f["add_value"], pady=(4, 2))
        note = NO_VARIABLES if not known else VALUES_FULL.format(
            n=dec.REPLAY_VALUES_MAX) if full else ALL_SET if not free else ""
        if note:
            grid.widget(ttk.Label(grid.frame, text=note, style="Hint.TLabel",
                                  justify="left"), pady=(0, 4))

    def _value_field(self, parent: tk.Misc, entry: db.Entry, index: int, kind: str,
                     value: object) -> Any:
        """The value field a variable's kind takes: Yes/No, a number or a text."""
        def change(new: object) -> bool:
            return self.set_start_value(entry, index, value=new)

        if kind == dec.YES_NO:
            return _Choice(parent, [(True, YES), (False, NO)], bool(value), width=6,
                           on_change=change)
        if kind == dec.NUMBER:
            return TextField(parent, number_text(value), width=8,
                             check=lambda t: number_of(t) is not None,
                             on_change=lambda t: change(number_of(str(t))))
        return TextField(parent, "" if value is None else str(value), width=12,
                         check=lambda t: "\n" not in t, on_change=lambda t: change(str(t)))


__all__ = ["ABOUT_REPLAYS", "ACROSS_FILES", "ADD_VALUE", "EMPTY_HINT", "MOVE_EARLIER",
           "MOVE_LATER", "NEW_REPLAY", "NOT_YET", "PLAY", "PREVIEW", "REPLAY_PREFIX",
           "ReplaysCategory", "endings_replay_on", "lines_word", "number_of", "replay_ready",
           "value_kind"]
