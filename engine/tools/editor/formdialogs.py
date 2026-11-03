"""Studio's command forms as dialogs, and the Insert… picker (F46 ``04-technical.md`` §6.7;
design §4 PR-F46-19/20, §6.2).

Why this module exists: an Events row's form edits one line in plain words, and Insert…
picks a command by name. These are the Tk halves of ``forms``: one dialog per
``CommandForm``, built from its ``Field``s, the Choice form (up to six options, each with its
text, an optional condition and where it goes), and the picker grouped like F45's Insert
menu (``assist.insert_menu``).

- Fields: ``text`` and ``number`` are entries, ``pick`` a read-only combobox, ``flag`` a check
  box, ``name`` and ``scene`` comboboxes offering the check's names of the field's
  ``name_kind`` (filtered as you type). A name not offered is allowed, with ``NOT_FOUND``
  under it.
- Every form shows the line it will write (``FormDialog.preview``), updated as fields change.
- Pictures and sounds (F47 W5, AC-F47-13, AC-F47-22): given a ``FormAssets`` (the window's
  is ``formassets.WindowAssets``), a picture field (Background) shows a 96 px thumbnail
  beside its drop-down, a Look field becomes a drop-down of the speaker's or character's
  looks with the look's thumbnail, a sound field (Music, Sound) gets ▶/■, and a character
  field shows the character's colour dot and shown name. Closing the dialog stops the sound.
  Without one the dialog is F46's.
- F47 P2 (``formtools``): the If form's condition is the condition builder (rows, + / −, All
  of / Any of; "Written as script" for a condition it can't show), and a choice's "Only
  show when" is a button with the condition in words that opens it; Say's text has the text
  toolbar and its "Reads as" preview; a fade colour (Transition, Flash, Chapter) has a
  swatch and **Pick…**; Fake crash has **Insert player name**. A field that only one pick
  uses shows only for that pick (``SWITCHED``: Lock/Unlock show the name field of their
  "What"); a new Chapter's name is made from its title as you type, unique among the
  game's chapters. While the builder can't write its rows, the form says why and OK waits.
- Insert… also lists the forms with no doc of their own (``FORM_ENTRIES``: Stop effects,
  Stop sound), and a text-only entry shows its ``forms.TEXT_ONLY`` reason, muted, under it.
- F47 P2-F: the effect forms (``TRY_FORMS``) get **Try it** under the line (``add_try_it``):
  the line plays in a small game window over the row's stage (``FormAssets.try_line``).
- They share ``dialogs``' dark look (F45 ``08`` §7): ``overlay`` fill, padding 20, inputs with
  a 1 px border, a ``raised`` code card for the line, OK primary and right-aligned, Esc and
  the close box cancel.
- The window calls ``edit_form``, ``edit_choice`` and ``pick_insert`` through this module, so
  tests answer them by patching it. The classes build without running, for tests that drive
  the real widgets.

Imports: ``tkinter``, ``dialogs``, ``fieldwidgets``, ``forms``, ``theme`` (no pygame;
ADR-0008).
"""

import math
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from tkinter import font as tkfont
from tkinter import ttk

from engine.script.statement_docs import StatementDoc
from engine.tools.editor import dialogs, forms, forms_files_ui, forms_more, formtools
from engine.tools.editor.fieldwidgets import PLAY, STOP, THUMB_PX, color_dot
from engine.tools.editor.forms import ChoiceItem, ChoiceValues, CommandForm, Field
from engine.tools.editor.theme import ROLES, THEME, TYPE_SCALE, font_families, scale_of

NOT_FOUND = "Not found yet; the check will tell you."
NEW_NAME = {"ending": "A new ending."}         # name kinds where a new name is normal
# Name kinds made only in the Database: what the hint says while there is none (F37 §4).
EMPTY_NAMES = {"achievement": "Make achievements in Database ▸ Achievements."}
NO_PICTURE = "No picture"
DOT_PX = 12
PICTURE_KINDS = frozenset(("image", "gallery"))  # name kinds whose value is a picture
SOUND_KINDS = frozenset(("audio",))            # name kinds whose value is a sound file
WHO_KINDS = frozenset(("character", "sprite"))  # name kinds that name a character
LOOK_KEY = "look"
LINE_CAPTION = "Line"
LINES_CAPTION = "Lines"
OK = "OK"
INSERT = "Insert"
CANCEL = "Cancel"
PICKER_TITLE = "Insert"
PICKER_FILTER = "Type to filter"
QUESTION = "Question"
SPEAKER = "Speaker"
LOOK = "Look"
TEXT = "Text"
OPTIONS = "Options"
OPTION_TEXT = "Text"
OPTION_WHEN = "Only show when"
OPTION_GOES = "Goes to"
ADD = "Add"
REMOVE = "Remove"
UP = "Up"
DOWN = "Down"
NARRATION = "Narration"
STOP_MUSIC = "Stop music"
FIELD_CHARS = 32            # a text field's width in characters
NUMBER_CHARS = 8
GAP = 8                     # px between rows and columns (× scale)
PREVIEW_ROWS = 8            # the Choice form's line preview shows at most this many lines
COLOUR_KEYS = frozenset(("colour",))          # Transition, Flash, Chapter: the fade colour
CONDITION_FORMS = frozenset(("if",))          # forms whose ``condition`` is the builder
# Fields only one pick of another field uses: form key → (that field, pick → keys shown).
SWITCHED: Mapping[str, tuple[str, Mapping[str, tuple[str, ...]]]] = {
    "lock": ("what", {what: (what,) for what in forms_more.LOCK_WHAT}),
    "unlock": ("what", {what: (what,) for what in forms_more.UNLOCK_WHAT}),
    "transition": ("change", {"background": ("image",),
                              "show": ("character", "look", "position"),
                              "hide": ("character",)}),
    "window_title": ("action", {"set": ("title",), "off": ()}),
    "voice": ("action", {"play": ("file",), "stop": ("fade",)}),
    "if": ("keyword", {"if": ("condition",), "elif": ("condition",), "else": ()}),
    **forms_files_ui.SWITCHED,                  # W9: Meta file, Game UI
}


# --- Names and labels -------------------------------------------------------------------------

def field_tip(label: tk.Widget, form_key: str, field_key: str) -> object | None:
    """F47 P3-D: the field's plain-words hint (``fieldhints.form_hint``) as a tooltip on its
    label; None when it has none."""
    from engine.tools.editor import fieldhints
    from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
    text = fieldhints.form_hint(form_key, field_key)
    return Tooltip(label, text) if text else None


def entry_title(doc: StatementDoc) -> str:
    """The picker's plain-words name for ``doc``: its form's title when it has a form
    (Narration and Stop music by their own words), else the doc's title."""
    form = forms.form_for_doc(doc)
    if form is None:
        return doc.title
    if doc.key == "narration":
        return NARRATION
    if form.key == "music" and doc.key == "stop":
        return STOP_MUSIC
    return form.title


def new_values(form: CommandForm, doc: StatementDoc | None = None) -> dict[str, str]:
    """A new row's starting values: every field empty, a pick at its first option (Music:
    play or stop as the doc says)."""
    values = {f.key: (f.options[0] if f.kind == "pick" and f.options else "")
              for f in form.fields}
    if form.key == "music" and doc is not None and doc.key == "stop":
        values["action"] = "stop"
    if doc is not None:                         # W9: Insert's "Read a meta file" reads
        values.update(forms_files_ui.new_values(form.key, doc.syntax) or {})
    return values


def _code_font(dialog: tk.Misc) -> tkfont.Font:
    family, weight = font_families(dialog)["mono"]
    font = tkfont.Font(root=dialog, family=family, weight=weight,
                       size=-round(TYPE_SCALE["codeSmall"][0] * scale_of(dialog)))
    dialog.code_font = font             # type: ignore[attr-defined]  (Tk deletes a lost font)
    return font


def _card(parent: tk.Misc, font: tkfont.Font, scale: float, height: int = 1) -> tk.Text:
    """The line preview: code on a ``raised`` card, read-only."""
    card = tk.Text(parent, height=height, width=1, wrap="none", font=font,
                   background=THEME["card.background"], foreground=THEME["editor.foreground"],
                   borderwidth=0, highlightthickness=0, relief="flat", takefocus=0,
                   padx=round(10 * scale), pady=round(6 * scale), cursor="arrow",
                   selectbackground=THEME["editor.selection"],
                   inactiveselectbackground=THEME["card.background"])
    card.configure(state="disabled")
    return card


def _set_card(card: tk.Text, text: str, rows: int | None = None) -> None:
    card.configure(state="normal")
    card.delete("1.0", "end")
    card.insert("1.0", text)
    if rows is not None:
        card.configure(height=max(1, min(rows, text.count("\n") + 1)))
    card.configure(state="disabled")


class FormAssets:
    """What a form's pickers show besides names (W5): thumbnails, ▶/■ and colour dots.
    This base shows nothing; ``formassets.WindowAssets`` answers from the window (the
    Database's declarations, the project's pictures, the helper child), and a test may
    answer with a fake. Names are as a script writes them: ``who`` is a character
    (``define`` name) or a sprite tag, ``image`` an image name (``bg river``), ``audio`` a
    file under ``audio/``. ``changed()`` tells the open dialog that a thumbnail arrived or
    a sound started or stopped."""

    on_change: Callable[[], object] | None = None

    def names(self, kind: str) -> Sequence[str]:
        """Names of ``kind`` the Database knows beyond the check's (a character added a
        moment ago, a picture not checked yet); the pickers offer both."""
        return ()

    def tag(self, who: str) -> str:
        """The sprite tag whose pictures ``who`` shows (a Character's ``image_tag``)."""
        return who

    def looks(self, tag: str) -> Sequence[str]:
        """The looks of sprite ``tag`` (``hana smile`` → ``smile``), sorted."""
        return ()

    def color(self, who: str) -> str | None:
        """``who``'s name colour (``#rrggbb``), or None."""
        return None

    def shown(self, who: str) -> str | None:
        """The name the player sees for ``who``, or None."""
        return None

    def thumb(self, image: str) -> object | None:
        """A ``tk.PhotoImage`` at most ``THUMB_PX`` (× scale) square, or None (none yet)."""
        return None

    def play(self, audio: str) -> None:
        """Play ``audio``; any other sound stops."""

    def stop(self) -> None:
        """Stop the sound playing."""

    def playing(self) -> str | None:
        """The ``audio`` playing now, or None."""
        return None

    def changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def can_try(self) -> bool:
        """Whether ``try_line`` can play a line (F47 P2-F): a Studio window's assets can."""
        return getattr(self, "win", None) is not None

    def try_line(self, line: str, on_problem: Callable[[str], None]) -> None:
        """Try it: play ``line`` in a small game window over the stage at the form's row;
        a failure's text goes to ``on_problem`` (``trywiring``)."""
        from engine.tools.editor import trywiring

        trywiring.try_form_line(getattr(self, "win"), line, on_problem)


class _NameBox:
    """A combobox offering ``names`` (filtered as you type), with ``NOT_FOUND`` under it
    while its text is a name it doesn't offer (``new``: the hint for a name kind where a new
    name is normal; ``quiet``: no hint while it offers nothing; ``empty``: the hint while it
    offers nothing)."""

    def __init__(self, parent: tk.Misc, var: tk.StringVar, names: Sequence[str], *,
                 width: int, hint_parent: tk.Misc | None = None, wrap: int = 300,
                 new: str | None = None, quiet: bool = False,
                 empty: str | None = None) -> None:
        self.names = list(names)
        self.var = var
        self.new = new
        self.quiet = quiet
        self.empty = empty
        self.box = ttk.Combobox(parent, textvariable=var, values=self.names, width=width,
                                postcommand=self._filter)
        self.hint = ttk.Label(hint_parent or parent, text="", style="Dialog.Hint.TLabel",
                              wraplength=wrap, justify="left")

    def set_names(self, names: Sequence[str]) -> None:
        self.names = list(names)
        self.box.configure(values=self.names)

    def _filter(self) -> None:
        typed = self.var.get().strip().lower()
        starts = [n for n in self.names if n.lower().startswith(typed)]
        inside = [n for n in self.names if typed in n.lower() and n not in starts]
        self.box.configure(values=starts + inside if typed else self.names)

    def hint_text(self) -> str:
        value = self.var.get().strip()
        if not self.names and self.empty is not None:
            return self.empty
        if not value or value in self.names or (self.quiet and not self.names):
            return ""
        return self.new if self.new is not None else NOT_FOUND


# --- One command form -------------------------------------------------------------------------

class FormDialog:
    """``form``'s dialog over ``parent``, filled from ``values``; built hidden, so a test can
    drive it. ``names``: name kind → the names its pickers offer; ``assets``: thumbnails,
    ▶/■ and colour dots (module docstring), or None for none. ``result`` is the values
    after OK (every field's key), None after Cancel."""

    def __init__(self, parent: tk.Misc, form: CommandForm, values: Mapping[str, str], *,
                 names: Mapping[str, Sequence[str]], ok: str = OK,
                 assets: FormAssets | None = None) -> None:
        self.form = form
        self.result: dict[str, str] | None = None
        self.assets = assets
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(form.title)
        body, scale = dialogs._body(dialog)
        self.scale = scale
        gap = round(GAP * scale)
        grid = self.grid = ttk.Frame(body, style="Dialog.TFrame")
        grid.pack(anchor="w", fill="x")
        grid.columnconfigure(1, weight=1)
        self.vars: dict[str, tk.Variable] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self.names: dict[str, _NameBox] = {}
        self.thumbs: dict[str, tk.Canvas] = {}          # field key → its thumbnail card
        self.thumb_shows: dict[str, str | None] = {}    # field key → the image it shows
        self.play_buttons: dict[str, ttk.Button] = {}
        self.dots: dict[str, tuple[ttk.Label, ttk.Label]] = {}   # (dot, shown name)
        self._dot_images: dict[str | None, tk.PhotoImage] = {}
        self.owner = next((f.key for f in form.fields if f.name_kind in WHO_KINDS), None) \
            if assets is not None and any(f.key == LOOK_KEY for f in form.fields) else None
        self._ready = False
        self.labels: dict[str, ttk.Label] = {}
        self.tips: dict[str, object] = {}               # field key → its label's Tooltip
        self.holders: dict[str, ttk.Frame] = {}
        self.builder: formtools.ConditionBuilder | None = None    # the If form's condition
        self.toolbar: formtools.TextToolbar | None = None          # Say's text
        self.colours: dict[str, formtools.ColourBox] = {}
        self.player_name: ttk.Button | None = None                 # Fake crash
        self._auto_name = form.key == "chapter" and not str(values.get("name", "")).strip()
        self._naming = False
        self._chapters = tuple(names.get("chapter", ()))
        row = 0
        for field in form.fields:
            value = str(values.get(field.key, ""))
            widget, var = self._field(grid, field, value, names)
            tall = widget.winfo_class() == "TFrame"
            label = ttk.Label(grid, text=field.label, style="Dialog.TLabel")
            label.grid(row=row, column=0, sticky="nw" if tall else "w",
                       padx=(0, round(16 * scale)),
                       pady=(round(4 * scale) if tall and row == 0 else
                             gap + round(4 * scale) if tall else 0 if row == 0 else gap, 0))
            self.labels[field.key] = label
            self.tips[field.key] = field_tip(label, form.key, field.key)   # P3-D
            widget.grid(row=row, column=1,
                        sticky="w" if field.kind == "number" or tall else "ew",
                        pady=(0 if row == 0 else gap, 0))
            holder = self._holder(field)
            if holder is not None:                      # a thumbnail, ▶/■ or a colour dot
                self._extras(holder, field)
                holder.grid(row=row, column=2, sticky="w", padx=(gap, 0),
                            pady=(0 if row == 0 else gap, 0))
                self.holders[field.key] = holder
            self.vars[field.key], self.widgets[field.key] = var, widget
            row += 1
            if field.key in self.names:
                hint = self.names[field.key].hint
                hint.grid(row=row, column=1, sticky="w", pady=(round(4 * scale), 0))
                hint.grid_remove()
                row += 1
            var.trace_add("write", lambda *_a: self._changed())
        if self._auto_name and "name" in self.vars:     # typing a name stops making one
            self.vars["name"].trace_add("write", lambda *_a: self._name_typed())
        caption = ttk.Label(body, text=LINE_CAPTION, style="Dialog.Hint.TLabel")
        caption.pack(anchor="w", pady=(round(16 * scale), round(4 * scale)))
        self.card = _card(body, _code_font(dialog), scale)
        self.card.pack(anchor="w", fill="x")
        self.card.configure(width=max(28, math.ceil(400 * scale / max(
            1, dialog.code_font.measure("0")))))   # type: ignore[attr-defined]
        self.try_button, self.try_note = add_try_it(self, body)    # F47 P2-F
        self.buttons = dialogs._buttons(dialog, body, (ok, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        for widget in self.widgets.values():
            if isinstance(widget, (ttk.Entry, ttk.Combobox)):
                for key in ("<Return>", "<KP_Enter>"):
                    widget.bind(key, lambda _e: self._pick(0))
        if assets is not None:
            assets.on_change = self._sync_assets
        self._ready = True
        self._changed()

    def _offered(self, kind: str, names: Mapping[str, Sequence[str]]) -> list[str]:
        """The names a ``kind`` picker offers: the check's, then the Database's (assets)."""
        offered = list(names.get(kind, ()))
        if self.assets is not None:
            extra = [n for n in self.assets.names(kind) if n not in offered]
            if extra:
                offered = sorted([*offered, *extra], key=str.casefold)
        return offered

    def _special(self, parent: tk.Misc, field: Field, value: str,
                 names: Mapping[str, Sequence[str]]) -> tuple[tk.Widget, tk.Variable] | None:
        """F47 P2's visual fields (module docstring), or None for an ordinary one."""
        form, key = self.form.key, field.key
        gap = round(GAP * self.scale)
        var = tk.StringVar(parent, value=value)
        if form in CONDITION_FORMS and key == "condition":
            offered = {kind: self._offered(kind, names)
                       for kind in formtools.NAME_KINDS.values()}
            self.builder = formtools.ConditionBuilder(parent, var, offered, required=True,
                                                      on_change=self._changed)
            return self.builder.frame, var
        if form == "say" and key == "text":
            box = ttk.Frame(parent, style="Dialog.TFrame")
            entry = ttk.Entry(box, textvariable=var, width=FIELD_CHARS * 2)
            self.toolbar = formtools.TextToolbar(
                box, entry, var, names={"variable": self._offered("variable", names)})
            self.toolbar.frame.pack(anchor="w", pady=(0, round(6 * self.scale)))
            entry.pack(anchor="w", fill="x")
            self.toolbar.preview.pack(anchor="w", fill="x", pady=(round(4 * self.scale), 0))
            self.toolbar.problem.pack(anchor="w")
            for sequence in ("<Return>", "<KP_Enter>"):
                entry.bind(sequence, lambda _e: self._pick(0))
            self.text_entry = entry
            return box, var
        if key in COLOUR_KEYS:
            colour = self.colours[key] = formtools.ColourBox(parent, var)
            return colour.frame, var
        if form == "crash" and key == "message":
            box = ttk.Frame(parent, style="Dialog.TFrame")
            entry = ttk.Entry(box, textvariable=var, width=FIELD_CHARS)
            entry.pack(side="left", fill="x", expand=True)
            self.player_name = ttk.Button(box, text=formtools.PLAYER_NAME,
                                          style="Secondary.TButton",
                                          command=lambda: self.insert_player_name(entry))
            self.player_name.pack(side="left", padx=(gap, 0))
            for sequence in ("<Return>", "<KP_Enter>"):
                entry.bind(sequence, lambda _e: self._pick(0))
            self.text_entry = entry
            return box, var
        return None

    def insert_player_name(self, entry: ttk.Entry) -> None:
        """Fake crash's **Insert player name**: ``{username}`` at the caret."""
        entry.insert("insert", forms_more.CRASH_PLAYER_NAME)
        entry.focus_set()

    def _field(self, parent: tk.Misc, field: Field, value: str,
               names: Mapping[str, Sequence[str]]) -> tuple[tk.Widget, tk.Variable]:
        special = self._special(parent, field, value, names)
        if special is not None:
            return special
        if field.kind == "flag":
            var: tk.Variable = tk.StringVar(parent, value=value)
            box = ttk.Checkbutton(parent, variable=var, onvalue="True", offvalue="",
                                  style="Dialog.TCheckbutton")
            return box, var
        var = tk.StringVar(parent, value=value)
        if field.kind == "pick" and field.shown:
            return self._shown_pick(parent, field, var), var
        if field.kind == "pick":
            return ttk.Combobox(parent, textvariable=var, values=field.options,
                                state="readonly", width=FIELD_CHARS), var
        if field.kind in ("name", "scene"):
            kind = field.name_kind or "label"
            offered = self._offered(kind, names)
            if kind in PICTURE_KINDS:                   # backgrounds first (bg …)
                offered.sort(key=lambda n: not n.casefold().startswith("bg "))
            name_box = _NameBox(parent, var, offered, width=FIELD_CHARS,
                                wrap=round(300 * self.scale), new=NEW_NAME.get(kind),
                                empty=EMPTY_NAMES.get(kind))
            self.names[field.key] = name_box
            return name_box.box, var
        if field.key == LOOK_KEY and self.owner is not None:
            name_box = _NameBox(parent, var, self._looks(), width=FIELD_CHARS,
                                wrap=round(300 * self.scale), quiet=True)
            self.names[field.key] = name_box
            return name_box.box, var
        width = NUMBER_CHARS if field.kind == "number" else FIELD_CHARS
        return ttk.Entry(parent, textvariable=var, width=width), var

    def _shown_pick(self, parent: tk.Misc, field: Field, var: tk.StringVar) -> ttk.Combobox:
        """A pick that lists plain words (``field.shown``) while ``var`` keeps the script word:
        the two follow each other both ways."""
        words = tk.StringVar(parent, value=field.shown_for(var.get()))
        box = ttk.Combobox(parent, textvariable=words, values=field.shown,
                           state="readonly", width=FIELD_CHARS)
        box.shown_var = words          # type: ignore[attr-defined]  # keeps the Tk variable

        def to_script(*_a: object) -> None:
            option = field.option_for(words.get())
            if var.get() != option:
                var.set(option)

        def to_words(*_a: object) -> None:
            shown = field.shown_for(var.get())
            if words.get() != shown:
                words.set(shown)

        words.trace_add("write", to_script)
        var.trace_add("write", to_words)
        return box

    # --- Pictures, sounds and colour dots (W5) --------------------------------------------

    def _holder(self, field: Field) -> ttk.Frame | None:
        """A frame for a field with something beside it (assets only), else None."""
        if self.assets is None:
            return None
        if field.name_kind in PICTURE_KINDS | SOUND_KINDS | WHO_KINDS \
                or (field.key == LOOK_KEY and self.owner is not None):
            return ttk.Frame(self.grid, style="Dialog.TFrame")
        return None

    def _extras(self, holder: ttk.Frame, field: Field) -> None:
        if field.name_kind in SOUND_KINDS:
            button = ttk.Button(holder, text=PLAY, width=3, style="Secondary.TButton",
                                command=lambda: self.toggle_sound(field.key))
            button.pack(side="left")
            self.play_buttons[field.key] = button
        elif field.name_kind in WHO_KINDS:
            dot = ttk.Label(holder, style="Dialog.TLabel")
            dot.pack(side="left")
            shown = ttk.Label(holder, text="", style="Dialog.Hint.TLabel")
            shown.pack(side="left", padx=(round(6 * self.scale), 0))
            self.dots[field.key] = (dot, shown)
        else:
            side = round(THUMB_PX * self.scale)
            card = tk.Canvas(holder, width=side, height=side, background=ROLES["raised"],
                             highlightthickness=1, highlightbackground=THEME["border"],
                             borderwidth=0, takefocus=0)
            card.pack(side="left")
            self.thumbs[field.key] = card
            self.thumb_shows[field.key] = None

    def _who(self) -> str:
        return str(self.vars[self.owner].get()).strip() if self.owner in self.vars else ""

    def _looks(self) -> list[str]:
        if self.assets is None or self.owner is None:
            return []
        who = self._who()
        return list(self.assets.looks(self.assets.tag(who))) if who else []

    def picture_of(self, key: str) -> str | None:
        """The image name field ``key``'s thumbnail is for (None: none)."""
        value = str(self.vars[key].get()).strip() if key in self.vars else ""
        if key != LOOK_KEY or self.owner is None or self.assets is None:
            return value or None
        who = self._who()
        if not who:
            return None
        tag = self.assets.tag(who)
        return f"{tag} {value}" if value else tag

    def _draw_thumb(self, key: str) -> None:
        card = self.thumbs[key]
        image_name = self.picture_of(key)
        image = self.assets.thumb(image_name) if self.assets and image_name else None
        self.thumb_shows[key] = image_name if image is not None else None
        card.delete("all")
        side = round(THUMB_PX * self.scale)
        if image is not None:
            card.create_image(side // 2 + 1, side // 2 + 1, image=image)
            card.image = image                                       # type: ignore[attr-defined]
        else:
            card.create_text(side // 2 + 1, side // 2 + 1, text=NO_PICTURE,
                             fill=THEME["muted"], width=side - 8, justify="center")

    def _dot(self, color: str | None) -> tk.PhotoImage:
        image = self._dot_images.get(color)
        if image is None:
            image = self._dot_images[color] = color_dot(self.dialog, color,
                                                        round(DOT_PX * self.scale))
        return image

    def _sync_assets(self) -> None:
        """Thumbnails, looks, dots and ▶/■ as the fields are now."""
        assets = self.assets
        if assets is None or not self.dialog.winfo_exists():
            return
        if self.owner is not None and LOOK_KEY in self.names:
            box = self.names[LOOK_KEY]
            looks = self._looks()
            if looks != box.names:
                box.set_names(looks)
        for key in self.thumbs:
            self._draw_thumb(key)
        for key, (dot, shown) in self.dots.items():
            who = str(self.vars[key].get()).strip()
            name = assets.shown(who) if who else None
            dot.configure(image=self._dot(assets.color(who)) if who else "")
            shown.configure(text=name if name and name != who else "")
        playing = assets.playing()
        for key, button in self.play_buttons.items():
            value = str(self.vars[key].get()).strip()
            on = bool(value) and playing == value
            button.configure(text=STOP if on else PLAY,
                             state="normal" if value else "disabled")

    def toggle_sound(self, key: str) -> None:
        """▶ plays field ``key``'s sound; ■ (it is playing) stops it."""
        if self.assets is None:
            return
        value = str(self.vars[key].get()).strip()
        if not value:
            return
        if self.assets.playing() == value:
            self.assets.stop()
        else:
            self.assets.play(value)
        self._sync_assets()

    def _close_assets(self) -> None:
        if self.assets is not None:
            if self.assets.on_change == self._sync_assets:
                self.assets.on_change = None
            if self.assets.playing() is not None:
                self.assets.stop()

    def values(self) -> dict[str, str]:
        """Every field's value as typed (outer blanks dropped)."""
        return {key: str(var.get()).strip() for key, var in self.vars.items()}

    def preview(self) -> str:
        """The line the form writes now ("" while it can't write one)."""
        if self.problem() is not None:
            return ""
        try:
            return self.form.write(self.values())
        except (KeyError, ValueError, TypeError):
            return ""

    def _changed(self) -> None:
        if not self._ready:
            return
        self._name_chapter()
        _set_card(self.card, self.preview())
        self._sync_assets()                     # first: a new speaker changes the looks
        hidden = self.hidden()
        for key, name_box in self.names.items():
            text = name_box.hint_text()
            name_box.hint.configure(text=text)
            if text and key not in hidden:
                name_box.hint.grid()
            else:
                name_box.hint.grid_remove()
        for key, widget in self.widgets.items():
            parts = [self.labels[key], widget]
            if key in self.holders:
                parts.append(self.holders[key])
            for part in parts:
                if key in hidden:
                    part.grid_remove()
                else:
                    part.grid()
        # The builder says why under its rows; OK waits.
        self._show_problem()
        self.buttons[0].state(["disabled"] if self.problem() else ["!disabled"])

    def hidden(self) -> set[str]:
        """Field keys hidden now: ``SWITCHED`` fields another pick uses."""
        rule = SWITCHED.get(self.form.key)
        if rule is None or rule[0] not in self.vars:
            return set()
        switch, shows = rule
        every = {key for keys in shows.values() for key in keys}
        now = str(self.vars[switch].get()).strip()
        shown = shows.get(now, next(iter(shows.values())))
        return every - set(shown)

    def problem(self) -> str | None:
        """Why OK can't write the line yet (the condition builder's rows; W9: a meta file
        name or a reason the form's rule refuses), or None."""
        if self.builder is not None and "condition" not in self.hidden():
            return self.builder.problem()
        rule = forms_files_ui.PROBLEMS.get(self.form.key)
        return rule(self.values()) if rule is not None else None

    def _show_problem(self) -> None:
        """W9: a form rule's problem, under the line card (the builder shows its own)."""
        rule = forms_files_ui.PROBLEMS.get(self.form.key)
        if rule is None:
            return
        label = getattr(self, "problem_label", None)
        if label is None:
            label = self.problem_label = ttk.Label(
                self.card.master, text="", style="Dialog.Hint.TLabel", justify="left",
                wraplength=round(400 * self.scale))
        text = rule(self.values()) or ""
        label.configure(text=text)
        if text:
            label.pack(anchor="w", pady=(round(4 * self.scale), 0), after=self.card)
        else:
            label.pack_forget()

    def confirmed(self) -> bool:
        """W9: a pick that asks first (Delete all saves) is asked about; True to go on."""
        rule = forms_files_ui.CONFIRM.get(self.form.key)
        if rule is None:
            return True
        key, pick, message, buttons = rule
        if self.values().get(key) != pick:
            return True
        return dialogs.ask(self.dialog, message, buttons, escape=1, default=1) == 0

    def _name_chapter(self) -> None:
        """A new Chapter: its name made from the title, unique among the game's chapters."""
        if not self._auto_name or "name" not in self.vars or "title" not in self.vars:
            return
        title = str(self.vars["title"].get())
        made = forms_more.chapter_name(title, taken=self._chapters) if title.strip() else ""
        if str(self.vars["name"].get()) != made:
            self._naming = True
            try:
                self.vars["name"].set(made)
            finally:
                self._naming = False

    def _name_typed(self) -> None:
        if not self._naming:
            self._auto_name = False

    def hints(self) -> dict[str, str]:
        """Field key → the hint shown under it (name fields only)."""
        return {key: str(box.hint.cget("text")) for key, box in self.names.items()}

    def _pick(self, index: int) -> None:
        if index == 0:
            if self.problem() is not None or not self.confirmed():
                return
            self.result = self.values()
        self._close_assets()
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> dict[str, str] | None:
        first = next(iter(self.widgets.values()), self.buttons[0])
        dialogs._run(parent, self.dialog, first)
        self._close_assets()
        return self.result


# --- Try it (F47 P2-F, PR-F47-20) -------------------------------------------------------------

TRY_IT = "Try it"
TRY_FORMS = frozenset(("transition", "shake", "flash", "glitch", "jitter"))
TRY_NEEDS_LINE = "Fill in the form first; then Try it plays its line."


def add_try_it(form_dialog: FormDialog, body: ttk.Frame
               ) -> tuple[ttk.Button | None, ttk.Label | None]:
    """The effect forms' **Try it** under the line card, when the assets can play a line:
    a click plays the line the form writes now in a small game window (a failure shows
    under it). Returns the button and its note, or (None, None) for other forms."""
    assets = form_dialog.assets
    if assets is None or form_dialog.form.key not in TRY_FORMS or not assets.can_try():
        return None, None
    scale = form_dialog.scale
    row = ttk.Frame(body, style="Dialog.TFrame")
    row.pack(anchor="w", fill="x", pady=(round(GAP * scale), 0))
    note = ttk.Label(row, text="", style="Dialog.Hint.TLabel", justify="left",
                     wraplength=round(400 * scale))

    def show(text: str) -> None:
        if note.winfo_exists():
            note.configure(text=text)

    def try_now() -> None:
        line = form_dialog.preview()
        show("" if line else TRY_NEEDS_LINE)
        if line:
            assets.try_line(line, show)

    button = ttk.Button(row, text=TRY_IT, style="Secondary.TButton", command=try_now)
    button.pack(anchor="w")
    note.pack(anchor="w", pady=(round(4 * scale), 0))
    return button, note


def edit_form(parent: tk.Misc, form: CommandForm, values: Mapping[str, str], *,
              names: Mapping[str, Sequence[str]], ok: str = OK,
              assets: FormAssets | None = None) -> dict[str, str] | None:
    """``form``'s modal dialog: its values after OK, or None (Cancel, Esc, the close box).
    ``assets``: thumbnails, ▶/■ and colour dots (``FormAssets``)."""
    return FormDialog(parent, form, values, names=names, ok=ok, assets=assets).run(parent)


# --- The Choice form ----------------------------------------------------------------------------

class ChoiceDialog:
    """The Choice form (§6.7.4): the question (speaker, look, text) and up to six options,
    each with its text, an "only show when" condition and where it goes (a scene or
    ``forms.CONTINUES``; a choice whose lines the form can't hold reads ``forms.IN_TEXT`` and
    keeps them). Add, Remove, Up and Down act on the chosen option. "Only show when" is a
    button with the condition in words; it opens the condition builder
    (``formtools.ask_condition``). ``assets``: the Database's names for the builder.
    ``result``: the ``ChoiceValues`` after OK."""

    def __init__(self, parent: tk.Misc, values: ChoiceValues, *,
                 names: Mapping[str, Sequence[str]], ok: str = OK,
                 assets: FormAssets | None = None) -> None:
        self.result: ChoiceValues | None = None
        self.condition_names = {
            kind: sorted({*names.get(kind, ()), *(assets.names(kind) if assets else ())},
                         key=str.casefold)
            for kind in formtools.NAME_KINDS.values()}
        self.scenes = list(names.get("label", ()))
        self.characters = list(names.get("character", ()))
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(forms.CHOICE.title)
        body, scale = dialogs._body(dialog)
        self.scale = scale
        gap = round(GAP * scale)
        self.gap = gap
        # The question
        ttk.Label(body, text=QUESTION, style="Dialog.TLabel",
                  font=_strong(dialog)).pack(anchor="w")
        top = ttk.Frame(body, style="Dialog.TFrame")
        top.pack(anchor="w", fill="x", pady=(round(6 * scale), 0))
        top.columnconfigure(5, weight=1)
        self.speaker = tk.StringVar(dialog, value=values.speaker)
        self.look = tk.StringVar(dialog, value=values.look)
        self.question = tk.StringVar(dialog, value=values.question)
        self.tips: dict[str, object] = {}               # P3-D: field key → its Tooltip
        for column, text, key in ((0, SPEAKER, "speaker"), (2, LOOK, "look"),
                                  (4, TEXT, "question")):
            label = ttk.Label(top, text=text, style="Dialog.TLabel")
            label.grid(row=0, column=column, sticky="w")
            self.tips[key] = field_tip(label, forms.CHOICE_FORM, key)
        speaker = _NameBox(top, self.speaker, self.characters, width=12)
        self.speaker_box = speaker.box
        speaker.box.grid(row=0, column=1, sticky="w", padx=(gap, round(16 * scale)))
        ttk.Entry(top, textvariable=self.look, width=10).grid(
            row=0, column=3, sticky="w", padx=(gap, round(16 * scale)))
        self.question_entry = ttk.Entry(top, textvariable=self.question, width=30)
        self.question_entry.grid(row=0, column=5, sticky="ew", padx=(gap, 0))
        # The options
        ttk.Label(body, text=OPTIONS, style="Dialog.TLabel",
                  font=_strong(dialog)).pack(anchor="w", pady=(round(16 * scale), 0))
        self.table = ttk.Frame(body, style="Dialog.TFrame")
        self.table.pack(anchor="w", fill="x", pady=(round(6 * scale), 0))
        self.table.columnconfigure(1, weight=1)
        for column, text, key in ((1, OPTION_TEXT, "text"), (2, OPTION_WHEN, "condition"),
                                  (3, OPTION_GOES, "goes")):
            label = ttk.Label(self.table, text=text, style="Dialog.Hint.TLabel")
            label.grid(row=0, column=column, sticky="w", padx=(0, gap))
            self.tips[key] = field_tip(label, forms.CHOICE_FORM, key)
        self.items: list[dict] = []
        self.chosen = 0
        for item in values.choices:
            self._add_row(item)
        tools = ttk.Frame(body, style="Dialog.TFrame")
        tools.pack(anchor="w", fill="x", pady=(gap, 0))
        self.tool_buttons: dict[str, ttk.Button] = {}
        for label, command in ((ADD, self.add), (REMOVE, self.remove),
                               (UP, lambda: self.move(-1)), (DOWN, lambda: self.move(1))):
            button = ttk.Button(tools, text=label, command=command, style="Secondary.TButton")
            button.pack(side="left", padx=(0, gap))
            self.tool_buttons[label] = button
        self.problem = ttk.Label(body, text="", style="Dialog.TLabel")
        self.lines_caption = ttk.Label(body, text=LINES_CAPTION, style="Dialog.Hint.TLabel")
        self.lines_caption.pack(anchor="w", pady=(round(16 * scale), round(4 * scale)))
        self.card = _card(body, _code_font(dialog), scale, height=4)
        self.card.pack(anchor="w", fill="x")
        self.buttons = dialogs._buttons(dialog, body, (ok, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        for var in (self.speaker, self.look, self.question):
            var.trace_add("write", lambda *_a: self._changed())
        self._changed()

    def _add_row(self, item: ChoiceItem) -> None:
        dialog = self.dialog
        text = tk.StringVar(dialog, value=item.text)
        when = tk.StringVar(dialog, value=item.condition)
        goes = tk.StringVar(dialog, value=forms.choice_summary(item))
        mark = ttk.Label(self.table, text="", width=2, style="Dialog.TLabel",
                         foreground=THEME["focusBorder"])
        text_entry = ttk.Entry(self.table, textvariable=text, width=24)
        when_entry = ttk.Button(self.table, text=formtools.condition_label(item.condition),
                                width=formtools.SUMMARY_CHARS, style="Secondary.TButton")
        when.trace_add("write", lambda *_a: when_entry.configure(
            text=formtools.condition_label(when.get())))
        if item.in_text:
            goes_box = ttk.Combobox(self.table, textvariable=goes, values=(forms.IN_TEXT,),
                                    width=18, state="disabled")
        else:
            goes_box = ttk.Combobox(self.table, textvariable=goes, width=18,
                                    values=[forms.CONTINUES, *self.scenes])
        row = {"item": item, "text": text, "when": when, "goes": goes,
               "widgets": (mark, text_entry, when_entry, goes_box)}
        when_entry.configure(command=lambda: self.edit_when(row))
        self.items.append(row)
        for var in (text, when, goes):
            var.trace_add("write", lambda *_a: self._changed())
        for widget in (text_entry, when_entry, goes_box):
            widget.bind("<FocusIn>", lambda _e, r=row: self._choose(r), add="+")
        self._grid_rows()

    def edit_when(self, row: dict) -> str | None:
        """An option's "Only show when" button: the condition builder in a small dialog."""
        self._choose(row)
        got = formtools.ask_condition(self.dialog, row["when"].get(), self.condition_names)
        try:
            self.dialog.grab_set()          # the nested dialog took the grab
        except tk.TclError:
            pass
        if got is not None:
            row["when"].set(got)
        return got

    def _grid_rows(self) -> None:
        gap = self.gap
        for n, row in enumerate(self.items):
            mark, text_entry, when_entry, goes_box = row["widgets"]
            pad = (gap if n else 0, 0)
            mark.grid(row=n + 1, column=0, sticky="w", pady=pad)
            text_entry.grid(row=n + 1, column=1, sticky="ew", padx=(0, gap), pady=pad)
            when_entry.grid(row=n + 1, column=2, sticky="ew", padx=(0, gap), pady=pad)
            goes_box.grid(row=n + 1, column=3, sticky="ew", pady=pad)
        self.chosen = max(0, min(self.chosen, len(self.items) - 1))
        for n, row in enumerate(self.items):
            row["widgets"][0].configure(text="▸" if n == self.chosen else "")

    def _choose(self, row: dict) -> None:
        if row in self.items:
            self.chosen = self.items.index(row)
            for n, other in enumerate(self.items):
                other["widgets"][0].configure(text="▸" if n == self.chosen else "")

    def values(self) -> ChoiceValues:
        out = []
        for row in self.items:
            item: ChoiceItem = row["item"]
            goes_text = row["goes"].get().strip()
            if item.in_text:
                goes, in_text = item.goes, True
            else:
                goes = None if goes_text in ("", forms.CONTINUES) else goes_text
                in_text = False
            out.append(ChoiceItem(row["text"].get(), row["when"].get().strip(), goes,
                                  in_text, item.old))
        return ChoiceValues(self.speaker.get().strip(), self.look.get().strip(),
                            self.question.get(), tuple(out))

    def preview(self) -> str:
        try:
            return "\n".join(forms.choice_lines(self.values(), "", "    "))
        except (KeyError, ValueError, TypeError):
            return ""

    def _changed(self) -> None:
        text = self.preview()
        lines = text.split("\n")
        if len(lines) > PREVIEW_ROWS:
            text = "\n".join(lines[:PREVIEW_ROWS - 1] + ["…"])
        _set_card(self.card, text, rows=PREVIEW_ROWS)
        full = len(self.items) >= forms.MENU_MAX_CHOICES
        self.tool_buttons[ADD].state(["disabled"] if full else ["!disabled"])
        self.tool_buttons[REMOVE].state(["!disabled"] if self.items else ["disabled"])

    def add(self) -> None:
        if len(self.items) >= forms.MENU_MAX_CHOICES:
            self._problem(forms.CHOICE_LIMIT_TEXT)
            return
        self._problem("")
        self._add_row(ChoiceItem(""))
        self.chosen = len(self.items) - 1
        self._grid_rows()
        self._changed()
        self.items[-1]["widgets"][1].focus_set()

    def _problem(self, text: str) -> None:
        """The line under the options saying why OK or Add can't (takes no space empty)."""
        self.problem.configure(text=text)
        if text and not self.problem.winfo_manager():
            self.problem.pack(anchor="w", pady=(round(8 * self.scale), 0),
                              before=self.lines_caption)
        elif not text and self.problem.winfo_manager():
            self.problem.pack_forget()

    def remove(self) -> None:
        if not self.items:
            return
        row = self.items.pop(self.chosen)
        for widget in row["widgets"]:
            widget.destroy()
        self._problem("")
        self._grid_rows()
        self._changed()

    def move(self, step: int) -> None:
        there = self.chosen + step
        if not self.items or not 0 <= there < len(self.items):
            return
        self.items[self.chosen], self.items[there] = self.items[there], self.items[self.chosen]
        self.chosen = there
        self._grid_rows()
        self._changed()

    def _pick(self, index: int) -> None:
        if index == 0:
            if not self.items:
                self._problem(forms.CHOICE_EMPTY_TEXT)
                return
            self.result = self.values()
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> ChoiceValues | None:
        focus = self.items[0]["widgets"][1] if self.items else self.question_entry
        dialogs._run(parent, self.dialog, focus)
        return self.result


def _strong(dialog: tk.Misc) -> tkfont.Font:
    family, weight = font_families(dialog)["semibold"]
    font = tkfont.Font(root=dialog, family=family, weight=weight,
                       size=-round(TYPE_SCALE["bodyStrong"][0] * scale_of(dialog)))
    dialog.strong_font = font           # type: ignore[attr-defined]
    return font


def edit_choice(parent: tk.Misc, values: ChoiceValues, *,
                names: Mapping[str, Sequence[str]], ok: str = OK,
                assets: FormAssets | None = None) -> ChoiceValues | None:
    """The Choice form, modal: its values after OK, or None."""
    return ChoiceDialog(parent, values, names=names, ok=ok, assets=assets).run(parent)


# --- The Insert… picker -------------------------------------------------------------------------

# Forms with no statement doc of their own: form key → (group, the entry they follow).
FORM_ENTRIES: Mapping[str, tuple[str, str]] = {
    "effect_off": ("Effects", "Jitter character"),
    "stop_sound": ("Audio", STOP_MUSIC),
}
REASON_INDENT = "      "                    # a text-only entry's reason, under it


def _with_form_entries(menu: Sequence[tuple[str, Sequence[StatementDoc]]]
                       ) -> tuple[tuple[str, tuple[StatementDoc | CommandForm, ...]], ...]:
    """``menu`` with each ``FORM_ENTRIES`` form after the entry it follows."""
    out = []
    for group, docs in menu:
        entries: list[StatementDoc | CommandForm] = []
        for doc in docs:
            entries.append(doc)
            for key, (in_group, after) in FORM_ENTRIES.items():
                form = forms.form_by_key(key)
                if form is not None and group == in_group and entry_title(doc) == after:
                    entries.append(form)
        out.append((group, tuple(entries)))
    return tuple(out)


def text_only_reason(entry: StatementDoc | CommandForm) -> str | None:
    """Why ``entry`` goes in as a script line (``forms.TEXT_ONLY``), or None (a form)."""
    if isinstance(entry, CommandForm) or forms.form_for_doc(entry) is not None:
        return None
    return forms.TEXT_ONLY.get(entry.key) or forms.NO_FORM_YET_REASON


class InsertPicker:
    """Insert…: the commands grouped as F45's Insert menu (``menu``: ``(group, docs)``),
    one entry per statement doc, plus the forms with no doc (``FORM_ENTRIES``), filtered
    as you type; a text-only entry has its reason, muted, under it. Enter or a
    double-click picks the chosen entry; ``result`` is its doc, or the form for a
    ``FORM_ENTRIES`` entry."""

    def __init__(self, parent: tk.Misc,
                 menu: Sequence[tuple[str, Sequence[StatementDoc]]]) -> None:
        self.menu = _with_form_entries(menu)
        self.result: StatementDoc | CommandForm | None = None
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(PICKER_TITLE)
        dialog.resizable(False, True)
        body, scale = dialogs._body(dialog)
        self.filter = tk.StringVar(dialog)
        entry = self.entry = ttk.Entry(body, textvariable=self.filter, width=40)
        entry.pack(anchor="w", fill="x")
        self.hint = ttk.Label(body, text=PICKER_FILTER, style="Dialog.Hint.TLabel")
        self.hint.pack(anchor="w", pady=(round(4 * scale), round(GAP * scale)))
        style = ttk.Style(dialog)
        back = THEME["widget.background"]
        style.configure("Dialog.Treeview", background=back, fieldbackground=back,
                        foreground=THEME["foreground"], borderwidth=0)
        frame = ttk.Frame(body, style="Dialog.TFrame")
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, show="tree", selectmode="browse", height=14,
                                 style="Dialog.Treeview")
        self.tree.column("#0", width=round(480 * scale))
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.tag_configure("group", foreground=THEME["muted"])
        family, weight = font_families(dialog)["ui"]
        self.reason_font = tkfont.Font(root=dialog, family=family, weight=weight,
                                       size=-round(TYPE_SCALE["small"][0] * scale))
        self.tree.tag_configure("reason", foreground=THEME["muted"], font=self.reason_font)
        self.docs: dict[str, StatementDoc | CommandForm] = {}
        self.reasons: dict[str, str] = {}           # a reason row → the entry above it
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._off_reason())
        self.buttons = dialogs._buttons(dialog, body, (INSERT, CANCEL), self._pick)
        self.filter.trace_add("write", lambda *_a: self._fill())
        for widget in (entry, self.tree):
            for key in ("<Return>", "<KP_Enter>"):
                widget.bind(key, lambda _e: self._pick(0) or "break")
        entry.bind("<Down>", lambda _e: self._step(1))
        entry.bind("<Up>", lambda _e: self._step(-1))
        self.tree.bind("<Double-Button-1>", self._double)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        self._fill()

    def groups(self) -> list[tuple[str, list[str]]]:
        """(group, entry titles) as shown now (reasons left out: ``reason_of``)."""
        return [(self.tree.item(g, "text"), [self.tree.item(c, "text")
                                             for c in self.tree.get_children(g)
                                             if c in self.docs])
                for g in self.tree.get_children("")]

    def entries(self) -> list[tuple[str, StatementDoc | CommandForm]]:
        """(group, doc or form) per entry shown now, in order."""
        return [(self.tree.item(g, "text"), self.docs[c])
                for g in self.tree.get_children("") for c in self.tree.get_children(g)
                if c in self.docs]

    def reason_of(self, group: str, title: str) -> str | None:
        """The muted reason shown under entry ``title`` of ``group``, or None."""
        for g in self.tree.get_children(""):
            if self.tree.item(g, "text") != group:
                continue
            children = list(self.tree.get_children(g))
            for n, c in enumerate(children):
                if c in self.docs and self.tree.item(c, "text") == title:
                    after = children[n + 1] if n + 1 < len(children) else None
                    if after in self.reasons:
                        return str(self.tree.item(after, "text")).strip()
                    return None
        raise KeyError((group, title))

    def _off_reason(self) -> None:
        """A click on a reason chooses its entry."""
        chosen = self.tree.selection()
        if chosen and chosen[0] in self.reasons:
            entry = self.reasons[chosen[0]]
            self.tree.selection_set(entry)
            self.tree.focus(entry)

    def _fill(self) -> None:
        typed = self.filter.get().strip().lower()
        tree = self.tree
        tree.delete(*tree.get_children(""))
        self.docs.clear()
        self.reasons.clear()
        first = None
        for group, docs in self.menu:
            shown = [d for d in docs if not typed or typed in _title(d).lower()
                     or typed in d.title.lower() or typed in group.lower()]
            if not shown:
                continue
            node = tree.insert("", "end", text=group, open=True, tags=("group",))
            for doc in shown:
                item = tree.insert(node, "end", text=_title(doc))
                self.docs[item] = doc
                first = first or item
                reason = text_only_reason(doc)
                if reason:
                    note = tree.insert(node, "end", text=REASON_INDENT + reason,
                                       tags=("reason",))
                    self.reasons[note] = item
        if first is not None:
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)

    def choose(self, group: str, title: str) -> None:
        """Select the entry ``title`` under ``group`` (for tests and the keyboard)."""
        for g in self.tree.get_children(""):
            if self.tree.item(g, "text") != group:
                continue
            for c in self.tree.get_children(g):
                if c in self.docs and self.tree.item(c, "text") == title:
                    self.tree.selection_set(c)
                    self.tree.focus(c)
                    self.tree.see(c)
                    return
        raise KeyError((group, title))

    def _step(self, step: int) -> str:
        items = list(self.docs)
        if items:
            now = self.tree.selection()
            at = items.index(now[0]) if now and now[0] in self.docs else -step
            pick = items[max(0, min(len(items) - 1, at + step))]
            self.tree.selection_set(pick)
            self.tree.focus(pick)
            self.tree.see(pick)
        return "break"

    def _double(self, event: tk.Event) -> str:
        if self.tree.identify_row(event.y) in self.docs:
            self._pick(0)
        return "break"

    def _pick(self, index: int) -> None:
        if index == 0:
            chosen = self.tree.selection()
            if not chosen or chosen[0] not in self.docs:
                return
            self.result = self.docs[chosen[0]]
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> StatementDoc | CommandForm | None:
        dialogs._run(parent, self.dialog, self.entry)
        return self.result


def _title(entry: StatementDoc | CommandForm) -> str:
    return entry.title if isinstance(entry, CommandForm) else entry_title(entry)


def pick_insert(parent: tk.Misc, menu: Sequence[tuple[str, Sequence[StatementDoc]]]
                ) -> StatementDoc | CommandForm | None:
    """Insert…, modal: the picked doc (or form, for a ``FORM_ENTRIES`` entry), or None
    (Cancel, Esc, the close box)."""
    return InsertPicker(parent, menu).run(parent)

# --- New scene and the scene picker (F46 step 5, PR-F46-14, Ctrl+J) -------------------------

NEW_SCENE_TITLE = "New scene"
SCENE_NAME = "Scene name"
SCENE_FILE = "File"
SCENE_NAMED = "Its name in the script: {name}"
SCENE_CREATE = "Add scene"
NEW_FILE = "New file…"
PICK_SCENE_TITLE = "Go to scene"
PICK_SCENE_OK = "Go to"
NO_SCENES = "No scene matches."


def scene_name(text: str) -> str:
    """F45's name suggestion for a typed scene name: lower case, spaces to ``_``."""
    return "_".join(text.strip().lower().split())


class NewSceneDialog:
    """New scene: a name (its script name shown as you type, with the problem when it
    can't be one, or is taken) and the script file it goes in. ``result`` after OK is
    ``(name, ref)`` with the suggested name; OK stays disabled while there is a problem.
    **New file…** (PR-F46-15) runs ``new_file(dialog)`` (F45's new script flow, giving the
    new file's ref or None) and chooses the file it made."""

    def __init__(self, parent: tk.Misc, files: Sequence[str], default: str, *,
                 taken: Sequence[str] = (), problem: object = None,
                 new_file: Callable[[tk.Misc], str | None] | None = None) -> None:
        self.result: tuple[str, str] | None = None
        self.new_file = new_file
        self.taken = frozenset(taken)
        self.problem = problem              # (name) -> problem text | None (label_problem)
        self.refs = tuple(files)
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(NEW_SCENE_TITLE)
        body, scale = dialogs._body(dialog)
        gap = round(GAP * scale)
        grid = ttk.Frame(body, style="Dialog.TFrame")
        grid.pack(anchor="w", fill="x")
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text=SCENE_NAME, style="Dialog.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, round(16 * scale)))
        self.name = tk.StringVar(dialog)
        self.entry = ttk.Entry(grid, textvariable=self.name, width=FIELD_CHARS)
        self.entry.grid(row=0, column=1, sticky="ew")
        self.hint = ttk.Label(grid, text="", style="Dialog.Hint.TLabel",
                              wraplength=round(320 * scale), justify="left")
        self.hint.grid(row=1, column=1, sticky="w", pady=(round(4 * scale), 0))
        ttk.Label(grid, text=SCENE_FILE, style="Dialog.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, round(16 * scale)), pady=(gap, 0))
        shown = [show_ref(ref) for ref in self.refs]
        self.file = tk.StringVar(dialog, value=show_ref(default) if default in self.refs
                                 else (shown[0] if shown else ""))
        self.files = ttk.Combobox(grid, textvariable=self.file, values=shown,
                                  state="readonly", width=FIELD_CHARS)
        self.files.grid(row=2, column=1, sticky="ew", pady=(gap, 0))
        self.new_button: ttk.Button | None = None
        if new_file is not None:
            self.new_button = ttk.Button(grid, text=NEW_FILE, style="Secondary.TButton",
                                         command=self.add_file)
            self.new_button.grid(row=2, column=2, sticky="w", padx=(gap, 0), pady=(gap, 0))
        self.buttons = dialogs._buttons(dialog, body, (SCENE_CREATE, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        for key in ("<Return>", "<KP_Enter>"):
            self.entry.bind(key, lambda _e: self._pick(0) or "break")
        self.name.trace_add("write", lambda *_a: self._changed())
        self._changed()

    def why_not(self) -> str | None:
        """Why the typed name can't be added now, or None."""
        name = scene_name(self.name.get())
        if not name:
            return ""
        if callable(self.problem):
            found = self.problem(name)
            if found:
                return str(found)
        if name in self.taken:
            return f"There is already a scene named `{name}`."
        return None

    def add_file(self) -> str | None:
        """**New file…**: F45's new script flow; the file it made is listed and chosen."""
        if self.new_file is None:
            return None
        ref = self.new_file(self.dialog)
        try:
            self.dialog.grab_set()          # the nested dialog took the grab
        except tk.TclError:
            pass
        if not ref:
            return None
        if ref not in self.refs:
            self.refs = (*self.refs, ref)
            self.files.configure(values=[show_ref(r) for r in self.refs])
        self.file.set(show_ref(ref))
        self.entry.focus_set()
        return ref

    def _changed(self) -> None:
        name = scene_name(self.name.get())
        why = self.why_not()
        self.hint.configure(text=why if why else (SCENE_NAMED.format(name=name) if name
                                                  else ""))
        self.buttons[0].state(["!disabled"] if why is None else ["disabled"])

    def _pick(self, index: int) -> None:
        if index == 0:
            if self.why_not() is not None:
                return
            shown = [show_ref(ref) for ref in self.refs]
            at = shown.index(self.file.get()) if self.file.get() in shown else 0
            self.result = (scene_name(self.name.get()), self.refs[at])
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> tuple[str, str] | None:
        dialogs._run(parent, self.dialog, self.entry)
        return self.result


def show_ref(ref: str) -> str:
    """A script file as the dialog lists it (``script/`` left off)."""
    return ref.removeprefix("script/")


def ask_new_scene(parent: tk.Misc, files: Sequence[str], default: str, *,
                  taken: Sequence[str] = (), problem: object = None,
                  new_file: Callable[[tk.Misc], str | None] | None = None
                  ) -> tuple[str, str] | None:
    """New scene, modal: ``(name, ref)``, or None (Cancel, Esc, the close box)."""
    return NewSceneDialog(parent, files, default, taken=taken, problem=problem,
                          new_file=new_file).run(parent)


class ScenePicker:
    """Go to scene… (Ctrl+J) and Change target…: the scenes, filtered as you type; Enter or
    a double-click picks one. ``result`` is its name."""

    def __init__(self, parent: tk.Misc, names: Sequence[str], *,
                 title: str = PICK_SCENE_TITLE, ok: str = PICK_SCENE_OK) -> None:
        self.names = tuple(names)
        self.result: str | None = None
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(title)
        body, scale = dialogs._body(dialog)
        self.filter = tk.StringVar(dialog)
        self.entry = ttk.Entry(body, textvariable=self.filter, width=40)
        self.entry.pack(anchor="w", fill="x")
        self.hint = ttk.Label(body, text=PICKER_FILTER, style="Dialog.Hint.TLabel")
        self.hint.pack(anchor="w", pady=(round(4 * scale), round(GAP * scale)))
        back = THEME["widget.background"]
        self.list = tk.Listbox(body, height=10, activestyle="none", exportselection=False,
                               background=back, foreground=THEME["foreground"],
                               selectbackground=THEME["list.activeSelection"],
                               selectforeground=THEME["foreground"], borderwidth=0,
                               highlightthickness=1, highlightbackground=THEME["border"])
        self.list.pack(fill="both", expand=True)
        self.buttons = dialogs._buttons(dialog, body, (ok, CANCEL), self._pick)
        self.filter.trace_add("write", lambda *_a: self._fill())
        for widget in (self.entry, self.list):
            for key in ("<Return>", "<KP_Enter>"):
                widget.bind(key, lambda _e: self._pick(0) or "break")
        self.entry.bind("<Down>", lambda _e: self._step(1))
        self.entry.bind("<Up>", lambda _e: self._step(-1))
        self.list.bind("<Double-Button-1>", lambda _e: self._pick(0))
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        self._fill()

    def shown(self) -> list[str]:
        return list(self.list.get(0, "end"))

    def _fill(self) -> None:
        typed = self.filter.get().strip().lower()
        self.list.delete(0, "end")
        for name in self.names:
            if not typed or typed in name.lower() or scene_name(typed) in name:
                self.list.insert("end", name)
        if self.list.size():
            self.list.selection_set(0)
            self.hint.configure(text=PICKER_FILTER)
        else:
            self.hint.configure(text=NO_SCENES)

    def _step(self, step: int) -> str:
        size = self.list.size()
        if size:
            now = self.list.curselection()
            at = max(0, min(size - 1, (now[0] if now else -step) + step))
            self.list.selection_clear(0, "end")
            self.list.selection_set(at)
            self.list.see(at)
        return "break"

    def choose(self, name: str) -> None:
        self.filter.set("")
        at = self.shown().index(name)
        self.list.selection_clear(0, "end")
        self.list.selection_set(at)

    def _pick(self, index: int) -> None:
        if index == 0:
            now = self.list.curselection()
            if not now:
                return
            self.result = str(self.list.get(now[0]))
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> str | None:
        dialogs._run(parent, self.dialog, self.entry)
        return self.result


def pick_scene(parent: tk.Misc, names: Sequence[str], *, title: str = PICK_SCENE_TITLE,
               ok: str = PICK_SCENE_OK) -> str | None:
    """The scene picker, modal: the picked scene's name, or None."""
    return ScenePicker(parent, names, title=title, ok=ok).run(parent)


__all__ = ["ChoiceDialog", "FormAssets", "FormDialog", "InsertPicker", "NOT_FOUND", "NewSceneDialog",
           "ScenePicker", "ask_new_scene", "edit_choice", "edit_form", "entry_title",
           "new_values", "pick_insert", "pick_scene", "scene_name"]
