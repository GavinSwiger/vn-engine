"""The Database's Extras categories: **Music room** (F35 ``SPEC.md`` §4, step 3; AC-F35-11,
12, 13). F37-S3's Achievements live in ``dbachievements`` (F36/07's Studio chain: F34-W4 → F35-S3 →
F36-W4 → F37-S3).

Why this module exists: the music room is the Extras page where players listen again to the
songs they have heard. A non-programmer never types ``lock track``: in Database ▸ **Music
room** they click **+ Add track…**, pick music files (each with ▶ to listen first), and
Studio writes one line per track into ``database.vns``, the title made from the file's name.
The form changes the title, the file and when players get the track (when the story first
plays it, from the start, or after chosen endings); **▲ Move up** / **▼ Move down** reorder
the room (``declplan.plan_move``, the gallery's mover); **▶ Preview the music room** runs the
game's dev ``run --extras music_room``. A Sounds ▸ Music file's form has the same switch as a
picture's "In the gallery": **In the music room**, with the room's title for it.

``MusicRoomCategory`` is a mixin of ``database.DatabasePane`` (as ``dbgallery``'s): the
pane's tree holds the rows (numbered, in the room's order); a small bar under it holds the
move and preview buttons. Every write is a ``declplan`` plan applied through the pane's
``_write``. Track declarations are read from the script texts (``declarations.scan``), so
the room shows without a check.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import importlib.util
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from tkinter import ttk
from typing import Any

from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, dialogs
from engine.tools.editor.dbmore import Row
from engine.tools.editor.dialogs import ask, show_error
from engine.tools.editor.fieldwidgets import AssetPicker, FormGrid, TextField, ToggleField
from engine.tools.editor.scriptedit import STALE
from engine.tools.editor.theme import THEME

# --- Texts (SPEC §4; the rest in the same voice) -----------------------------------------------

ABOUT_MUSIC = ("The music room lets players listen to your soundtrack from the title "
               "screen's Extras. Click + Add track… to list a music file.")
EMPTY_HINT = "List the songs players can listen to again."
ADD_TRACK = "+ Add track…"
NEW = "+ New"
MOVE_UP = "▲ Move up"
MOVE_DOWN = "▼ Move down"
ACROSS_FILES = "This track is declared in another file; move it there."
PREVIEW = "▶ Preview the music room"
PREVIEW_TIP = "Opens Extras ▸ Music Room with every track open. Nothing is saved."
PREVIEW_NOT_YET = ("Opens Extras ▸ Music Room with every track open. This engine can't open "
                   "the music room yet; it comes with the Music Room page.")
LABEL_TITLE = "Title"
LABEL_FILE = "File"
LABEL_UNLOCKS = "When players get it"
RULE_HEARD = "When the story first plays it"
RULE_OPEN = "From the start"
RULE_UNTIL = "After these endings:"
UNTIL_PICK = "Tick the endings players must reach (all of them)."
NO_ENDINGS = "Your story has no Ending lines yet."
NO_FILE = "⚠ There is no such file in audio/. Pick another file."
NEVER_PLAYED = ("⚠ No Play music line plays this file, so players never get it. Pick From the "
                "start or After these endings, or play it in the story.")
PLAYED_BY = "Played by {lines}"
NOT_PLAYED = "Not played in the story yet"
NOT_CHECKED = "Not checked yet"
USES_HEAD = "{name} is played in {lines}:"
DELETE = "Delete"
REMOVE_ASK = 'Remove "{title}" from the music room? The music file stays.'
REMOVE_BUTTONS = ("Remove", "Cancel")
ROOM_FULL = "The music room holds up to {n} tracks."
DETAIL_HEARD = "when played"
DETAIL_OPEN = "from start"
DETAIL_UNTIL = "after {n} ending"
DETAIL_UNTILS = "after {n} endings"
IN_ROOM = "In the music room"
ROOM_TITLE = "Music room title"
SWITCH_HINT = "Players can listen to it again from Extras once the story has played it."
OPEN_IN_ROOM = "Open in Music room"
PICK_TITLE = "Add tracks to the music room"
PICK_HINT = ("Pick music files (Ctrl+click for several), ▶ to listen. They go at the end "
             "of the music room.")
PICK_NONE = "Every music file is in the music room already. Add music under Sounds first."
PICK_OK = "Add"
CANCEL = "Cancel"
PLAY = "▶ Play"
STOP = "■ Stop"

TRACK_PREFIX = "u:"
MOVE_STYLE = "Move.Secondary.TButton"
EXTRAS_PAGE = "music_room"
AUDIO_PREFIX = "audio/"
MUSIC_FOLDER = "music"
HEARD, OPEN, UNTIL = "heard", "open", "until"


def preview_ready() -> bool:
    """True when this engine has the music room's Extras page (F35-S2's
    ``engine/app/musicroom.py``) and so ``run --extras music_room`` opens it; reads no
    code."""
    try:
        return importlib.util.find_spec("engine.app.musicroom") is not None
    except (ImportError, ValueError):
        return False


def lines_word(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def rule_of(values: Mapping[str, object]) -> str:
    """``HEARD``, ``OPEN`` or ``UNTIL`` for a track's values."""
    if values.get("open"):
        return OPEN
    return UNTIL if values.get("until") else HEARD


def _radio_style(root: tk.Misc) -> str:
    """``TRadiobutton`` dressed like the theme's ``TCheckbutton`` (the theme styles only
    check boxes)."""
    style = ttk.Style(root)
    for option in ("background", "foreground", "indicatorbackground", "indicatorforeground",
                   "upperbordercolor", "lowerbordercolor", "indicatorsize", "indicatormargin",
                   "focuscolor"):
        value = style.lookup("TCheckbutton", option)
        if value not in ("", None):
            style.configure("TRadiobutton", **{option: value})
    for option in ("background", "indicatorbackground", "upperbordercolor",
                   "lowerbordercolor"):
        found = style.map("TCheckbutton", option)
        if found:
            style.map("TRadiobutton", **{option: found})
    return "TRadiobutton"


class _FilePicker(AssetPicker):
    """The track's File: an ``AssetPicker`` of music files with ▶ under it (the form is
    narrow beside the Guide), without a "none"."""

    def __init__(self, parent: tk.Misc, refs: Sequence[str], value: str, **kw: Any) -> None:
        super().__init__(parent, refs, value, **kw)
        if self.play_button is not None:
            self.box.pack_configure(side="top", anchor="w")
            self.play_button.configure(width=8)
            self.play_button.pack_configure(side="top", anchor="w", padx=0,
                                            pady=(round(6 * kw.get("scale", 1.0)), 0))

    def set_playing(self, on: bool) -> None:
        if self.play_button is not None:
            self.play_button.configure(text=STOP if on else PLAY)

    def _show(self) -> None:
        if not self.frame.winfo_exists():       # the write rebuilt the form
            return
        super()._show()
        if getattr(self, "play_button", None) is not None:
            self.set_playing(self.play_button.cget("text") == STOP)

    def _picked(self) -> None:
        try:
            super()._picked()
        except tk.TclError:                     # the write rebuilt the form
            pass

    def _choices(self, refs: Sequence[str]) -> list[tuple[object, str]]:
        return [(ref, ref) for ref in refs]


# --- + Add track… -------------------------------------------------------------------------------

class MusicPicker:
    """A modal list of music files (several can be picked) with ▶ Play / ■ Stop for the one
    under the cursor. ``play(file)`` toggles playback; ``playing()`` is the file playing now
    (or None). ``result``: the picked files in list order (None: Cancel)."""

    def __init__(self, parent: tk.Misc, files: Sequence[str],
                 play: Callable[[str], object], playing: Callable[[], str | None]) -> None:
        self.files = list(files)
        self.play, self.playing = play, playing
        self.result: list[str] | None = None
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(PICK_TITLE)
        body, scale = dialogs._body(dialog)
        ttk.Label(body, text=PICK_HINT if files else PICK_NONE, style="Dialog.Hint.TLabel",
                  wraplength=round(400 * scale), justify="left").pack(
            anchor="w", pady=(0, round(8 * scale)))
        back = THEME["widget.background"]
        self.list = tk.Listbox(body, height=min(12, max(4, len(files))), width=44,
                               selectmode="extended", activestyle="none",
                               exportselection=False, background=back,
                               foreground=THEME["foreground"],
                               selectbackground=THEME["list.activeSelection"],
                               selectforeground=THEME["foreground"], borderwidth=0,
                               highlightthickness=1, highlightbackground=THEME["border"])
        for file in self.files:
            self.list.insert("end", file)
        self.list.pack(fill="both", expand=True)
        self.play_button = ttk.Button(body, text=PLAY, style="Secondary.TButton",
                                      command=self.toggle,
                                      state="normal" if files else "disabled")
        self.play_button.pack(anchor="w", pady=(round(8 * scale), 0))
        if files:
            self.list.selection_set(0)
            self.list.activate(0)
        self.list.bind("<<ListboxSelect>>", lambda _e: self._sync(), add="+")
        self.list.bind("<space>", lambda _e: (self.toggle(), "break")[1])
        self.list.bind("<Double-Button-1>", lambda _e: self._pick(0))
        for key in ("<Return>", "<KP_Enter>"):
            self.list.bind(key, lambda _e: (self._pick(0), "break")[1])
        self.buttons = dialogs._buttons(dialog, body, (PICK_OK, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))

    def current(self) -> str | None:
        """The file under the cursor (the last one clicked)."""
        try:
            index = int(self.list.index("active"))
        except tk.TclError:
            return None
        return self.files[index] if 0 <= index < len(self.files) else None

    def choose(self, *files: str) -> None:
        """Pick ``files`` as clicks would (tests)."""
        self.list.selection_clear(0, "end")
        for file in files:
            self.list.selection_set(self.files.index(file))
        if files:
            self.list.activate(self.files.index(files[-1]))
        self._sync()

    def toggle(self) -> None:
        file = self.current()
        if file is not None:
            self.play(file)
        self._sync()

    def _sync(self) -> None:
        on = self.current() is not None and self.playing() == self.current()
        self.play_button.configure(text=STOP if on else PLAY)

    def _pick(self, index: int) -> None:
        if index == 0:
            picked = [self.files[i] for i in self.list.curselection()]
            if not picked:
                return
            self.result = picked
        if self.playing() is not None and self.playing() in self.files:
            self.play(str(self.playing()))                  # stop it: the dialog goes
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> list[str] | None:
        dialogs._run(parent, self.dialog, self.list)
        return self.result


def pick_music(parent: tk.Misc, files: Sequence[str], play: Callable[[str], object],
               playing: Callable[[], str | None]) -> list[str] | None:
    """The picker, modal: the picked files (inside ``audio/``), or None."""
    return MusicPicker(parent, files, play, playing).run(parent)


# --- The mixin ----------------------------------------------------------------------------------

class MusicRoomCategory:
    """Database ▸ Music room and the Sounds ▸ Music form's switch (a mixin of
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
    marks: tuple[dec.Decl, ...]
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
    _project_refs: Callable[[str], list[str]]
    toggle_sound: Callable[[str], None]
    hub_playing: Callable[[], str | None]
    refresh: Callable[..., None]
    select_category: Callable[[str], None]
    selected_row: Callable[[], Row | None]
    search_text: Callable[[], str]
    music_bar: Any = None
    music_moves: tuple[Any, Any] | None = None
    music_note: Any = None
    music_preview: Any = None
    music_preview_tip: Any = None

    # --- Rows -------------------------------------------------------------------------------

    def _track_rows(self) -> list[Row]:
        return [Row(TRACK_PREFIX + e.name, f"{n}.  {e.shown}", self._track_detail(e), e)
                for n, e in enumerate(db.track_entries(self.decls, self.texts), start=1)]

    def track_entries(self) -> list[db.Entry]:
        """The Music room's entries in the room's order (as listed)."""
        return [r.entry for r in self.rows.get(db.CATEGORY_MUSIC_ROOM, ())
                if r.entry is not None]

    @staticmethod
    def _track_detail(entry: db.Entry) -> str:
        values = entry.decl.values if entry.decl is not None else None
        if not values:
            return ""
        rule = rule_of(values)
        if rule == OPEN:
            return DETAIL_OPEN
        if rule == UNTIL:
            n = len(values["until"])                                # type: ignore[arg-type]
            return (DETAIL_UNTIL if n == 1 else DETAIL_UNTILS).format(n=n)
        return DETAIL_HEARD

    def music_files(self) -> list[str]:
        """The game's music files (Sounds ▸ Music), inside ``audio/``, sorted."""
        names = [ref[len(AUDIO_PREFIX):] for ref in self._project_refs("audio")]
        return sorted((n for n in names if db.sound_folder(n) == MUSIC_FOLDER),
                      key=str.casefold)

    def _track_files(self) -> dict[str, str]:
        """Each track's file → its name (the files the room already lists)."""
        out: dict[str, str] = {}
        for decl in dec.scan(self._read_texts()):
            if decl.kind == dec.TRACK and decl.values is not None:
                out.setdefault(str(decl.values["file"]), decl.name)
        return out

    def _played_places(self, file: str) -> list[tuple[str | None, int | None]]:
        """The lines that play ``file`` (the check's ``audio_use`` rows, without F41's
        track declaration and config.toml rows)."""
        return list(db.story_places(self.names, self.texts, db.SOUND, file))

    def _ending_choices(self, until: Sequence[str]) -> list[tuple[str, str]]:
        """Every ending (name, label) for the "After these endings" ticks, plus any the
        track names that the story doesn't have. The label is the ending's title (its script
        name too when two endings share a title)."""
        shown = {e.name: e.shown for e in db.ending_entries(self.marks, self.names)}
        names = list(db.ending_names(self.marks, self.names))
        names += [n for n in until if n not in names]
        titles = [shown.get(n, n) for n in names]
        return [(n, t if titles.count(t) == 1 else f"{t} ({n})") for n, t in zip(names, titles)]

    # --- The list column --------------------------------------------------------------------

    def _build_music_bar(self) -> None:
        px = self._px
        bar = self.music_bar = ttk.Frame(self.list_body)
        moves = ttk.Frame(bar)
        moves.pack(fill="x")
        moves.columnconfigure((0, 1), weight=1, uniform="move")
        ttk.Style(self.root).configure(MOVE_STYLE, padding=(px(4), px(4)))  # fits 240 px
        up = ttk.Button(moves, text=MOVE_UP, style=MOVE_STYLE, width=1,
                        command=lambda: self.move_track(-1))
        up.grid(row=0, column=0, sticky="ew")
        down = ttk.Button(moves, text=MOVE_DOWN, style=MOVE_STYLE, width=1,
                          command=lambda: self.move_track(1))
        down.grid(row=0, column=1, sticky="ew", padx=(px(6), 0))
        self.music_moves = (up, down)
        self.music_note = ttk.Label(bar, text="", style="Hint.TLabel", justify="left",
                                    wraplength=px(200))
        ready = preview_ready()
        self.music_preview = ttk.Button(bar, text=PREVIEW, command=self.preview_music_room,
                                        state="normal" if ready else "disabled")
        self.music_preview.pack(anchor="w", pady=(px(8), 0))
        from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
        self.music_preview_tip = Tooltip(self.music_preview,
                                         PREVIEW_TIP if ready else PREVIEW_NOT_YET)
        for key, step in (("<Alt-Up>", -1), ("<Alt-Down>", 1)):
            self.list_tree.bind(key, lambda _e, s=step: (self.move_track(s), "break")[1]
                                if self.category == db.CATEGORY_MUSIC_ROOM else None, add="+")

    def _music_after_fill(self, has_entries: bool) -> None:
        """After the list is filled: the bar under it, the + button's and empty state's
        words."""
        on = self.category == db.CATEGORY_MUSIC_ROOM
        if not on and self.category not in (db.CATEGORY_GALLERY,     # they set their own
                                            db.CATEGORY_REPLAY, db.CATEGORY_ACHIEVEMENT):
            self.new_button.configure(text=NEW)
            if self.empty.button is not None:
                self.empty.button.configure(text=NEW)
        if on and self.music_bar is None:
            self._build_music_bar()
        bar = self.music_bar
        if bar is not None:
            if on and has_entries and not bar.winfo_ismapped():
                bar.pack(side="bottom", fill="x", padx=self._px(8),
                         pady=(self._px(6), self._px(8)), before=self.list_tree)
            elif not (on and has_entries) and bar.winfo_ismapped():
                bar.pack_forget()
        if not on:
            return
        self.new_button.configure(text=ADD_TRACK)
        if not has_entries:
            self.empty.hint.configure(text=EMPTY_HINT)
            if self.empty.button is not None:
                self.empty.button.configure(text=ADD_TRACK)
        self._sync_track_moves()

    def _sync_track_moves(self) -> None:
        if self.music_moves is None:
            return
        up, down = self.music_moves
        row = self.selected_row() if self.category == db.CATEGORY_MUSIC_ROOM else None
        entries = self.track_entries()
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
        self.music_note.configure(text=note)
        if note and not self.music_note.winfo_ismapped():
            self.music_note.pack(anchor="w", pady=(self._px(4), 0), before=self.music_preview)
        elif not note and self.music_note.winfo_ismapped():
            self.music_note.pack_forget()

    # --- Writes -----------------------------------------------------------------------------

    def add_tracks(self) -> bool:
        """+ Add track…: pick music files; each joins the end of the room."""
        self.texts = self._read_texts()
        taken = self._track_files()
        free = [f for f in self.music_files() if f not in taken]
        picked = pick_music(self.root, free,
                            lambda f: self.toggle_sound(AUDIO_PREFIX + f),
                            lambda: (lambda p: p[len(AUDIO_PREFIX):] if p else None)(
                                self.hub_playing()))
        if not picked:
            return False
        return self.add_track_files(picked)

    def add_track_files(self, files: Sequence[str], *, go: bool = True,
                        select: str | None = None) -> bool:
        """Add a track for each of ``files`` at the end of the room (one undo step each):
        its title from the file's name, its name from the title. ``go``: show it in the
        Music room (else the list on screen keeps ``select``)."""
        done = False
        for file in files:
            self.texts = self._read_texts()
            decls = dec.scan(self.texts)
            if sum(1 for d in decls if d.kind == dec.TRACK) >= dec.TRACKS_MAX:
                show_error(self.root, ROOM_FULL.format(n=dec.TRACKS_MAX))
                return done
            title = dec.track_title(file)
            name = dec.script_name(title, dec.taken_names(decls, dec.TRACK), dec.TRACK)
            plan = declplan.plan_new(dec.TRACK, name, {"title": title, "file": file,
                                                       "open": False, "until": ()},
                                     self.texts)
            if go and self.category != db.CATEGORY_MUSIC_ROOM:
                self.select_category(db.CATEGORY_MUSIC_ROOM)
            if not self._write(plan, select=TRACK_PREFIX + name if go else select):
                return done
            done = True
        return done

    def _now_track(self, entry: db.Entry) -> dec.Decl | None:
        decl = self._fresh(entry)
        if decl is None or decl.values is None:
            show_error(self.root, STALE)
            self.refresh()
            return None
        return decl

    def set_track_rule(self, entry: db.Entry, rule: str) -> bool:
        """The Unlocks radio: When the story first plays it / From the start. "After these
        endings" writes nothing until an ending is ticked."""
        if rule == UNTIL:
            self._show_until(True)
            return True
        return self._edit(entry, {"open": rule == OPEN, "until": ()})

    def set_track_ending(self, entry: db.Entry, name: str, on: bool) -> bool:
        """An "After these endings" tick; the last one unticked goes back to the default
        rule."""
        decl = self._now_track(entry)
        if decl is None:
            return False
        until = [n for n in decl.values["until"]]                   # type: ignore[union-attr]
        if on and name not in until:
            until.append(name)
        elif not on and name in until:
            until.remove(name)
        return self._edit(entry, {"open": False, "until": tuple(until)})

    def set_track_file(self, entry: db.Entry, file: object) -> bool:
        if not isinstance(file, str):
            return True
        return self._edit(entry, {"file": file})

    def delete_track(self, entry: db.Entry | None = None, *, confirm: bool = True) -> bool:
        """Delete (asks; the music file stays). Nothing names a track, so it is never
        refused for being used."""
        if entry is None:
            row = self.selected_row()
            entry = row.entry if row is not None else None
            if entry is None or entry.kind != dec.TRACK:
                return False
        decl = self._fresh(entry)
        if decl is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        if confirm and ask(self.root, REMOVE_ASK.format(title=entry.shown), REMOVE_BUTTONS,
                           escape=1, default=1) != 0:
            return False
        if self.category == db.CATEGORY_MUSIC_ROOM:
            self.chosen[db.CATEGORY_MUSIC_ROOM] = None
        return self._write(declplan.plan_delete(decl, self.texts))

    def move_track(self, step: int) -> bool:
        """▲ Move up (-1) / ▼ Move down (+1): swap the selected track's line with its
        neighbour's (``declplan.plan_move``; refused across files)."""
        row = self.selected_row()
        if row is None or row.entry is None or row.entry.kind != dec.TRACK \
                or self.search_text().strip():
            return False
        entries = self.track_entries()
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

    def preview_music_room(self) -> None:
        """▶ Preview the music room: the game opens on Extras ▸ Music Room with every track
        open in memory (dev ``run --extras music_room``), through the Play bar."""
        play = getattr(self.win, "play_extras", None)
        if callable(play) and preview_ready():
            play(EXTRAS_PAGE)

    def show_plays(self, title: str, places: list[tuple[str | None, int | None]]) -> None:
        """Show uses: the lines that play the file, in the Problems panel."""
        from engine.tools.editor.database import UseItem
        from engine.tools.editor.preview import Report
        items = []
        for ref, line in places:
            text = ""
            if ref is not None and line is not None:
                lines = self.texts.get(ref, "").split("\n")
                text = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            where = f"{ref}:{line}" if ref is not None and line is not None else (ref or "")
            items.append(UseItem(f"{where}: {text}" if text else where, ref, line))
        head = USES_HEAD.format(name=title, lines=lines_word(len(places)))
        self.win.show_report(Report("editor", head, tuple(items)))   # type: ignore[arg-type]

    # --- The track form ---------------------------------------------------------------------

    def _track_key(self, entry: db.Entry, shape: tuple) -> tuple:
        values = entry.decl.values if entry.decl is not None else None
        file = str((values or {}).get("file", ""))
        played = len(self._played_places(file)) if self._check_ran() else None
        return shape + (rule_of(values or {}), tuple((values or {}).get("until") or ()),
                        file, played, tuple(self.music_files()),
                        db.ending_names(self.marks, self.names))

    def _show_until(self, on: bool) -> None:
        """Enable or disable the endings' ticks (the "After these endings" radio)."""
        if self.form is None:
            return
        for toggle in self.form.fields.get("until", {}).values():
            toggle.check.configure(state="normal" if on else "disabled")
        hint = self.form.fields.get("until_hint")
        if hint is not None:
            hint.configure(text=UNTIL_PICK if on else "")

    def _track_form(self, row: Row, key: tuple) -> None:
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
        f["title"] = TextField(grid.frame, str(values["title"]), width=30,
                               check=lambda t: 0 < len(t.strip()) <= dec.TRACK_TITLE_MAX,
                               on_change=lambda v: self._edit(entry, {"title": str(v).strip()}))
        grid.row(LABEL_TITLE, f["title"])
        file = str(values["file"])
        taken = self._track_files()
        files = [n for n in self.music_files() if n not in taken or n == file]
        if file not in files:
            files.append(file)
        f["file"] = _FilePicker(grid.frame, files, file, width=20, scale=self.scale,
                                play=lambda name: self.toggle_sound(AUDIO_PREFIX + name),
                                on_change=lambda v: self.set_track_file(entry, v))
        grid.row(LABEL_FILE, f["file"])
        if file not in self.music_files() and AUDIO_PREFIX + file not in \
                self._project_refs("audio"):
            grid.widget(ttk.Label(grid.frame, text=NO_FILE, style="Hint.TLabel",
                                  justify="left"), pady=(0, 4))
        self.sound_label = ttk.Label(grid.frame, text="", style="Detail.TLabel")
        grid.widget(self.sound_label, pady=(0, 2))

        rule = rule_of(values)
        until = tuple(values.get("until") or ())                    # type: ignore[arg-type]
        style = _radio_style(self.root)
        unlocks = ttk.Frame(grid.frame)
        var = f["rule_var"] = tk.StringVar(master=unlocks, value=rule)
        f["rule"] = {}
        endings = self._ending_choices(until)
        for value, text in ((HEARD, RULE_HEARD), (OPEN, RULE_OPEN), (UNTIL, RULE_UNTIL)):
            radio = ttk.Radiobutton(unlocks, text=text, value=value, variable=var, style=style,
                                    command=lambda v=value: self.set_track_rule(entry, v))
            radio.pack(anchor="w", pady=(px(2), px(2)))
            f["rule"][value] = radio
        f["until"] = {}
        ticks = ttk.Frame(unlocks)
        ticks.pack(anchor="w", padx=(px(24), 0))
        for name, label in endings:
            toggle = ToggleField(ticks, label, name in until,
                                 on_change=lambda v, n=name: self.set_track_ending(
                                     entry, n, bool(v)))
            toggle.check.pack(anchor="w", pady=(px(1), px(1)))
            f["until"][name] = toggle
        if not endings:
            f["rule"][UNTIL].configure(state="disabled")
            ttk.Label(ticks, text=NO_ENDINGS, style="Hint.TLabel").pack(anchor="w")
        f["until_hint"] = ttk.Label(ticks, text="", style="Hint.TLabel", justify="left")
        f["until_hint"].pack(anchor="w")
        grid.caption(LABEL_UNLOCKS)
        grid.widget(unlocks, pady=(2, 2))
        self._show_until(rule == UNTIL)
        if rule == UNTIL:
            f["until_hint"].configure(text="")

        places = self._played_places(file)
        never = self._check_ran() and not places and rule == HEARD
        if never:
            f["never"] = ttk.Label(grid.frame, text=NEVER_PLAYED, style="Hint.TLabel",
                                   justify="left")
            grid.widget(f["never"], pady=(10, 2))
        uses = ttk.Frame(grid.frame)
        text = (PLAYED_BY.format(lines=lines_word(len(places))) if places else NOT_PLAYED) \
            if self._check_ran() else NOT_CHECKED
        ttk.Label(uses, text=text).pack(side="left")
        if places:
            ttk.Button(uses, text=db.SHOW_USES, style="Link.Ghost.TButton", cursor="hand2",
                       command=lambda: self.show_plays(entry.shown, places)).pack(
                side="left", padx=(px(8), 0))
        if not never:                        # the warning above says it already
            grid.widget(uses, pady=(10, 0))
        bottom = ttk.Frame(body)
        bottom.grid(row=2, column=0, sticky="ew", pady=(px(20), 0))
        f["delete"] = ttk.Button(bottom, text=DELETE, style="Secondary.TButton",
                                 command=lambda: self.delete_track(entry))
        f["delete"].pack(side="right")

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            title.configure(text=entry.shown)
            f["title"].set(str(entry.decl.values["title"]))

        form.update = update
        self._sync_track_moves()

    # --- The Sounds ▸ Music form's switch ---------------------------------------------------

    def track_for(self, file: str) -> db.Entry | None:
        """The music room's entry that plays ``file``, or None."""
        for entry in self.track_entries() or db.track_entries(self.decls, self.texts):
            values = entry.decl.values if entry.decl is not None else None
            if values is not None and values.get("file") == file:
                return entry
        return None

    def _sound_music_shape(self, entry: db.Entry) -> tuple:
        if entry.folder != MUSIC_FOLDER and self.track_for(entry.name) is None:
            return ()
        track = self.track_for(entry.name)
        return ("room", track.name if track else None, track.editable if track else None)

    def _sound_music_rows(self, grid: FormGrid, form: Any, entry: db.Entry) -> None:
        """Under a music file's ▶: **In the music room**, its **Music room title** and
        **Open in Music room**."""
        track = self.track_for(entry.name)
        if entry.folder != MUSIC_FOLDER and track is None:
            return
        f = form.fields
        f["room"] = ToggleField(grid.frame, "", track is not None,
                                on_change=lambda v: self._room_switch(entry.name, bool(v)))
        grid.row(IN_ROOM, f["room"], hint=SWITCH_HINT)
        if track is None:
            return
        values = track.decl.values if track.decl is not None else None
        if track.editable and values is not None:
            f["room_title"] = TextField(
                grid.frame, str(values["title"]), width=26,
                check=lambda t: 0 < len(t.strip()) <= dec.TRACK_TITLE_MAX,
                on_change=lambda v: self._edit(track, {"title": str(v).strip()}))
            grid.row(ROOM_TITLE, f["room_title"])
        else:
            f["room"].check.configure(state="disabled")
            grid.row(ROOM_TITLE, ttk.Label(grid.frame, text=track.shown))
        line = ttk.Frame(grid.frame)
        f["room_go"] = ttk.Button(line, text=OPEN_IN_ROOM, style="Link.Ghost.TButton",
                                  cursor="hand2",
                                  command=lambda: self.show_in_music_room(track.name))
        f["room_go"].pack(side="left")
        grid.widget(line, pady=(0, 2))

    def _room_switch(self, file: str, on: bool) -> bool:
        track = self.track_for(file)
        select = self.chosen.get(self.category)
        if on and track is None:
            return self.add_track_files([file], go=False, select=select)
        if not on and track is not None:
            done = self.delete_track(track, confirm=False)
            self.refresh(select=select)
            return done
        return True

    def show_in_music_room(self, name: str) -> None:
        """Open in Music room: Database ▸ Music room with track ``name`` selected."""
        self.chosen[db.CATEGORY_MUSIC_ROOM] = TRACK_PREFIX + name
        self.select_category(db.CATEGORY_MUSIC_ROOM)


__all__ = ["ABOUT_MUSIC", "ACROSS_FILES", "ADD_TRACK", "MOVE_DOWN", "MOVE_UP",
           "MusicPicker", "MusicRoomCategory", "PREVIEW", "PREVIEW_NOT_YET", "PREVIEW_TIP",
           "REMOVE_ASK", "TRACK_PREFIX", "lines_word", "pick_music", "preview_ready",
           "rule_of"]
