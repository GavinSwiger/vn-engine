"""Studio's Game settings tab (F47 ``01-design.md`` §4.4, §6.3; ``04-technical.md`` §3.2, §7.2,
§7.3; PR-F47-14..16, 18; AC-F47-19, 20).

Why this module exists: a non-programmer changes the game's look and settings (its title,
window size, title screen, text box, content warning) with fields instead of editing
``config.toml``. ``config.toml`` stays the only truth: every field shows the open document's
value (unsaved edits included), and every change is a ``tomlpatch`` plan applied with
``win.apply_plan`` as one undo step of that document, so the Editor and this tab share one
text and one undo history. Three columns: the **pages** (180 px), the **form** (scrolls) and,
on Text box and Title screen, a 16:9 **preview** card (40 %; under 1000 px it goes below the
form) showing a still the helper child draws from the unsaved text, 500 ms after the last
change.

- Fields come from ``settingsmodel`` (by ``config_schema``): toggle, choice, colour, number,
  file (from its asset group, with a thumbnail or ▶), text (a name list as one line, a long
  text as a box), and tables, which are edited in the Editor (their reason and Open in
  Editor). Each row has a plain label, a hint (what it does, its range, ``Default: …``),
  the 2 px changed bar and **Use default** (removes the line).
- A key ``tomlpatch`` can't change safely (an inline table, an array of tables) shows
  "This one is written in a way the form can't edit." and **Edit as script**.
- A ``config.toml`` that doesn't parse shows only PR-F47-18's message and **Open in Editor**.
- **All settings** lists every section, built a few sections at a time, with a search box.
- **Styles & playthrough looks** (F47 W9): a picker of the file's ``[style.<name>]`` and
  ``[playthrough.N]`` tables, **+ New style** and **+ New playthrough look** (a name, then
  one key written so the table exists), and the shown look's fields (``settingsmodel``'s
  ``look_page``; a key not set keeps the main look).

The tab reads ``config.toml`` again when it shows, after each check (``win.on_check_done``),
after each of its writes and when the document's text changed since it last looked.
Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from tkinter import ttk
from typing import Any

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor import tomlpatch
from engine.tools.editor.dbmodel import EDIT_AS_SCRIPT
from engine.tools.editor.dialogs import ask, ask_text, show_error
from engine.tools.editor.document import SaveError, encode
from engine.tools.editor.fieldwidgets import (
    AssetPicker,
    ChoiceField,
    ColorField,
    FormGrid,
    FormRow,
    NumberField,
    ScrollFrame,
    TextField,
    ToggleField,
    _Field,
)
from engine.tools.editor.helperhub import CANT_PLAY, ThumbLoader, hub_for
from engine.tools.editor.scriptedit import STALE, Refuse
from engine.tools.editor.theme import ROLES, THEME
from engine.tools.editor.views import EmptyState, panel_header

# --- Texts (design §4.4, §6.4; the rest are this step's, in the same voice) -----------------

PAGES_HEADING = "Pages"
OPEN_IN_EDITOR = "Open in Editor"
UPDATING = "Updating preview…"
NOT_AVAILABLE = "Preview not available: {reason}"
PREVIEW_HEADING = "Preview"
PREVIEW_NOTE = "A still of how it looks in the game, with your unsaved changes."
SEARCH_HINT = "Search settings…"
NO_MATCH = "No setting matches “{text}”."
EMPTY_PAGE = "Nothing to set here yet."
RANGE = "{lo} to {hi}"
OFF_RANGE = "0 (off), or {lo} to {hi}"
NONE_FILE = "None"
COMPLEX_BUTTONS = (EDIT_AS_SCRIPT, "Cancel")
CANT_EDIT = "{reason} Open it in the Editor to change it there."
# Beside a section's caption, muted: where its settings live, for authors who also open the
# file (a bare "[textbox]" read as jargon, 2026-11-02).
SECTION_PATH = "In config.toml: [{path}]"
INTRO: Mapping[str, str] = {
    "game": "Your game's name and version, and its window.",
    "title": "The first screen players see.",
    "textbox": "Where the story's lines appear.",
    "content_warning": "A message shown before the title screen, if your game needs one.",
    "choices": "The choices players pick from in a menu.",
    "saves": "Saving, loading, and how far players can go back.",
    "sound": "How loud the game starts, and how music and sounds fade.",
    "effects": "Screen effects, and comfort for players who need less motion.",
    "chapters": "The chapter title card and the Codex of tips and items.",
    "flowchart": "The players' map of the story, from the game menu.",
    "fourth_wall": "Moments where the game reaches outside itself.",
    "words": "Every word the game shows. Change one to rename or translate it.",
    "extras": "The Extras screen players open from the title: the gallery of pictures "
              "they've seen, and more.",
    sm.ALL_SETTINGS: "Every setting in config.toml. Type to find one.",
    sm.LOOKS: ("A style changes the text box, choices, full-screen text and quick menu while "
               "the story says so (a Game UI line). A playthrough look changes the title "
               "screen from that playthrough on. Anything a look doesn't set keeps the main "
               "look."),
}
# W9: the Styles & playthrough looks page (design §4.4 PR-F47-17).
LOOK_LABEL = "Look"
NEW_STYLE = "+ New style"
NEW_PLAYTHROUGH = "+ New playthrough look"
NO_LOOKS = "No styles or playthrough looks yet."
NO_LOOKS_HINT = "Add one with + New style."
NEW_STYLE_ASK = ("Name the new style. The story turns it on with a Game UI line "
                 "(ui style <name>).")
NEW_PLAYTHROUGH_ASK = ("Which playthrough is this title look for? It shows once "
                       "persistent.playthrough reaches this number.")
CREATE = "Create"
LOOK_DELETE_HINT = "To delete a look, remove its tables in the Editor."

# --- Sizes (px at 100 %) ----------------------------------------------------------------------

PAGE_LIST_WIDTH = 180
FORM_MIN_WIDTH = 360
COMPACT_BELOW = 1000            # tab width under which the preview goes below the form
PREVIEW_SHARE = 0.4
PREVIEW_DELAY_MS = 500          # PR-F47-16: after typing stops
PREVIEW_MAX = 640               # the helper's widest still
THUMB_SIDE = 48
SECTIONS_PER_STEP = 4           # All settings builds this many sections per idle step
SEARCH_DELAY_MS = 200
TEXT_WIDTH = 36
LABEL_WIDTH = 170
HINT_WRAP = 420                 # until the form's width is known
COMPACT_CARD_SHARE = 0.3        # compact: the card's height, as a share of the tab's
COMPACT_CARD_MAX = 200


def sentence(text: str) -> str:
    """``text`` with a capital first letter and a full stop (key docs are lower-case
    phrases)."""
    text = text.strip()
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def number_text(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def field_hint(field: sm.Field) -> str:
    """The muted line under a field: what it does, its range, and its default."""
    parts = [sentence(field.help)]
    spec = field.widget
    if spec.kind == "number" and spec.lo is not None and spec.hi is not None:
        words = OFF_RANGE if spec.off else RANGE
        parts.append(sentence(words.format(lo=number_text(spec.lo), hi=number_text(spec.hi))))
    if spec.kind != "table":
        parts.append(sentence(field.default_text))     # no "Allow it?." after a question
    return " ".join(part for part in parts if part)


def same_value(field: sm.Field, a: object, b: object) -> bool:
    """Equal as the game reads them (a colour in any case)."""
    if field.kind == "color" and isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()
    return a == b and type(a) is type(b) or (field.kind == "number" and a == b)


def section_line(text: str, path: str) -> int:
    """The line of ``[path]`` in ``text`` (1 when it isn't there)."""
    want = "[" + path + "]"
    for number, line in enumerate(text.split("\n"), 1):
        if line.strip().replace(" ", "") == want:
            return number
    return 1


class LongTextField(_Field):
    """A few lines of text (``[content_warning] text``); applied on focus-out or Ctrl+Enter
    (Enter starts a new line)."""

    def __init__(self, parent: tk.Misc, value: str, *,
                 on_change: Callable[[object], object] | None = None,
                 width: int = TEXT_WIDTH, height: int = 5) -> None:
        super().__init__(value, on_change)
        self.widget = self.text = tk.Text(
            parent, width=width, height=height, wrap="word", undo=True,
            background=THEME["input.background"], foreground=THEME["input.foreground"],
            insertbackground=THEME["input.foreground"], relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=THEME["border"],
            highlightcolor=THEME["focusBorder"])
        self.text.bind("<FocusOut>", lambda _e: self._done(), add="+")
        self.text.bind("<Control-Return>", lambda _e: (self._done(), "break")[1])
        self._show()

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _show(self) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", str(self.value or ""))
        self.text.edit_reset()

    def _done(self) -> None:
        self._commit(self.get())


@dataclass
class Shown:
    """One field on screen: its model, its widget and its row."""

    field: sm.Field
    widget: Any                 # a fieldwidgets field, or None for a table
    row: FormRow
    complex: bool = False


class SettingsPane:
    """The Game settings tab of ``win`` (an ``EditorWindow``): ``frame`` is the notebook
    page."""

    def __init__(self, win: Any, parent: tk.Misc) -> None:
        self.win = win
        self.root = win.root
        self.scale = win.scale
        px = self._px
        self.pages = sm.pages()
        self.page = self.pages[0]
        self.text: str | None = None            # config.toml's text as last read
        self.found: Mapping[str, object] = {}   # its values (settingsmodel.values)
        self.shown_fields: dict[str, Shown] = {}
        self.complex_paths: frozenset[str] = frozenset()
        self.form_key: tuple | None = None
        self.state = "form"                     # "form", "broken" or "unavailable"
        self.status = ""                        # the preview card's line
        self._refresh_id: str | None = None
        self._preview_id: str | None = None
        self._search_id: str | None = None
        self._build_id: str | None = None
        self._pending: list[sm.Section] = []    # All settings sections still to build
        self._previewed: tuple[str, str] | None = None   # (kind, text) last asked for
        self._serial: int | None = None
        self._listening = False
        self._sound_listening = False
        self._playing_path: str | None = None
        self._image: tk.PhotoImage | None = None
        self.compact = False
        self.look: tuple[str, str] | None = None    # W9: the look the Looks page shows

        style = ttk.Style(self.root)
        style.configure("Caption.TLabel", background=THEME["editor.background"],
                        foreground=THEME["muted"], font=win.fonts["caption"])
        style.configure("Card.TFrame", background=THEME["card.background"])
        style.configure("Card.TLabel", background=THEME["card.background"],
                        foreground=THEME["muted"], font=win.fonts["small"])
        style.configure("Intro.TLabel", background=THEME["editor.background"],
                        foreground=THEME["muted"])

        self.frame = ttk.Frame(parent)
        self.paned = tk.PanedWindow(self.frame, orient="horizontal", sashwidth=px(4),
                                    borderwidth=0, sashrelief="flat",
                                    background=THEME["sash"])
        self.paned.pack(fill="both", expand=True)

        # The pages (chrome, like the Database's categories).
        self.page_frame = ttk.Frame(self.paned, style="Side.TFrame")
        panel_header(self.page_frame, PAGES_HEADING, self.scale).pack(fill="x")
        self.page_tree = ttk.Treeview(self.page_frame, show="tree", selectmode="browse",
                                      height=1)
        self.page_tree.column("#0", width=px(PAGE_LIST_WIDTH - 20), stretch=True)
        self.page_tree.pack(fill="both", expand=True)
        for page in self.pages:
            self.page_tree.insert("", "end", iid=page.key, text=page.title)
        self.page_tree.selection_set(self.page.key)
        self.page_tree.focus(self.page.key)
        self.page_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_page(), add="+")
        for key in ("<Return>", "<KP_Enter>"):
            self.page_tree.bind(key, lambda _e: (self._focus_form(), "break")[1])

        # The form and the preview card share the right column.
        self.body = ttk.Frame(self.paned)
        self.body.rowconfigure(0, weight=1)
        self.form_frame = ttk.Frame(self.body)
        self.form_frame.columnconfigure(0, weight=1)
        self.form_frame.rowconfigure(2, weight=1)
        self.title_label = ttk.Label(self.form_frame, text="", style="EmptyTitle.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w", padx=px(16), pady=(px(12), 0))
        self.search_var = tk.StringVar(master=self.root)
        self.search = ttk.Entry(self.form_frame, textvariable=self.search_var)
        self._placeholder = False
        self.search.bind("<FocusIn>", lambda _e: self._search_placeholder(False), add="+")
        self.search.bind("<FocusOut>", lambda _e: self._search_placeholder(
            not self.search_var.get()), add="+")
        self.search_var.trace_add("write", lambda *_a: self._on_search())
        self.scroll = ScrollFrame(self.form_frame)
        self.scroll.frame.grid(row=2, column=0, sticky="nsew")
        self.grid: ttk.Frame | None = None     # the form's body (one FormGrid a section)

        self.card_outer = ttk.Frame(self.body)
        panel_header(self.card_outer, PREVIEW_HEADING, self.scale).pack(fill="x")
        self.card = tk.Frame(self.card_outer, background=THEME["card.background"],
                             highlightthickness=0, borderwidth=0)
        self.card.pack(fill="x", padx=px(12), pady=(px(4), 0))
        self.picture = tk.Label(self.card, background=THEME["card.background"],
                                foreground=THEME["muted"], borderwidth=0, anchor="center",
                                justify="center")
        self.picture.pack(fill="both", expand=True)
        self.card_status = ttk.Label(self.card_outer, text="", style="Hint.TLabel",
                                     wraplength=px(320), justify="left")
        self.card_status.pack(fill="x", padx=px(12), pady=(px(6), 0))
        self.card_note = ttk.Label(self.card_outer, text=PREVIEW_NOTE, style="Hint.TLabel",
                                   wraplength=px(320), justify="left")
        self.card_note.pack(fill="x", padx=px(12), pady=(px(4), 0))
        self.card.bind("<Configure>", lambda _e: self._fit_card(), add="+")
        self._wrap = px(HINT_WRAP)
        self.scroll.canvas.bind("<Configure>", self._wrap_hints, add="+")

        self.paned.add(self.page_frame, width=px(PAGE_LIST_WIDTH), minsize=px(120),
                       stretch="never")
        self.paned.add(self.body, minsize=px(FORM_MIN_WIDTH), stretch="always")

        # A config.toml that can't be shown covers the whole tab (PR-F47-18).
        self.empty = EmptyState(self.frame, icon="warning", title="", hint="",
                                button=OPEN_IN_EDITOR, command=self.open_in_editor,
                                scale=self.scale)
        self.empty.title.pack_forget()
        self.problem_line = 1

        self.thumbs = ThumbLoader(win, self.frame, px(THUMB_SIDE), self._thumb_ready)
        self.frame.bind("<Configure>", lambda _e: self._layout(), add="+")
        win.on_check_done.append(lambda _result: self._schedule_refresh())
        win.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab_changed(),
                          add="+")
        self._layout(force=True)

    # --- Small helpers ----------------------------------------------------------------------

    def _px(self, value: float) -> int:
        return round(value * self.scale)

    @property
    def shown(self) -> bool:
        try:
            return self.win.current_tab() == "settings"
        except (tk.TclError, StopIteration, IndexError):
            return False

    @property
    def focus_widget(self) -> tk.Widget:
        return self.page_tree

    def _focus_form(self) -> None:
        if self.page.key == sm.ALL_SETTINGS:
            self.search.focus_set()
            return
        for item in self.shown_fields.values():
            if item.widget is not None:
                widget = getattr(item.widget, "entry", None) or getattr(
                    item.widget, "box", None) or item.widget.widget
                widget.focus_set()
                return

    def _record(self) -> Any:
        return self.win.record_for(CONFIG_REF)

    def config_text(self) -> str | None:
        """``config.toml``'s editor text, or None when it can't be edited here."""
        record = self._record()
        if not record.editable:
            return None
        return record.widget.get("1.0", "end-1c")

    # --- Pages and layout -------------------------------------------------------------------

    def select_page(self, key: str) -> None:
        """Show the page ``key`` (``settingsmodel.PAGES``)."""
        if self.page_tree.selection() != (key,):
            self.page_tree.selection_set(key)
            self.page_tree.focus(key)
        self._on_page()

    def _on_page(self) -> None:
        chosen = self.page_tree.selection()
        if not chosen:
            return
        page = next(p for p in self.pages if p.key == chosen[0])
        if page is self.page and self.form_key is not None:
            return
        self.stop_sound()
        self._cancel_preview()
        self.page = page
        self.form_key = None
        self._previewed = None          # each page asks for its own still
        self._serial = None
        self._image = None
        self.picture.configure(image="", text="")
        self._set_status("")
        if page.key != sm.ALL_SETTINGS:
            self._search_placeholder(True)
        self._layout(force=True)
        if self.shown:
            self.refresh()              # else when the tab shows (its on_show)

    def _layout(self, force: bool = False) -> None:
        """Place the form and the preview card: side by side (60/40), or the card under the
        form below ``COMPACT_BELOW`` px; no card on a page without a preview."""
        width = self.frame.winfo_width()
        compact = 1 < width < self._px(COMPACT_BELOW)
        if not force and compact == self.compact:
            if compact:
                self._fit_card()        # its height follows the tab's
            return
        self.compact = compact
        if compact:
            self.card.pack_configure(fill="none", anchor="w")
            self.card_note.pack_forget()
        else:
            self.card.pack_configure(fill="x", anchor="center")
            self.card_note.pack(fill="x", padx=self._px(12), pady=(self._px(4), 0),
                                after=self.card_status)
        preview = bool(self.page.preview)
        self.form_frame.grid_forget()
        self.card_outer.grid_forget()
        for column in (0, 1):
            self.body.columnconfigure(column, weight=0, uniform="")
        self.body.rowconfigure(1, weight=0)
        if not preview:
            self.form_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
            self.body.columnconfigure(0, weight=1)
        elif compact:
            self.form_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
            self.card_outer.grid(row=1, column=0, columnspan=2, sticky="ew",
                                 pady=(0, self._px(12)))
            self.body.columnconfigure(0, weight=1)
        else:
            self.form_frame.grid(row=0, column=0, sticky="nsew")
            self.card_outer.grid(row=0, column=1, sticky="new", pady=(self._px(12), 0))
            share = round(PREVIEW_SHARE * 10)
            self.body.columnconfigure(0, weight=10 - share, uniform="split")
            self.body.columnconfigure(1, weight=share, uniform="split")
        title = self.page.title
        self.title_label.configure(text=title)
        if self.page.key == sm.ALL_SETTINGS:
            self.search.grid(row=1, column=0, sticky="ew", padx=self._px(16),
                             pady=(self._px(8), self._px(4)))
        else:
            self.search.grid_forget()

    def _fit_card(self) -> None:
        """Keep the card 16:9: as wide as its column, or (compact, under the form) as high as
        ``COMPACT_CARD_SHARE`` of the tab, so the form keeps most of the height."""
        self.card.pack_propagate(False)
        if self.compact:
            height = max(self._px(90), min(self._px(COMPACT_CARD_MAX), round(
                self.frame.winfo_height() * COMPACT_CARD_SHARE)))
            width = round(height * 16 / 9)
        else:
            width = self.card.winfo_width()
            if width <= 1:
                return
            height = round(width * 9 / 16)
        if int(self.card.cget("height")) != height:
            self.card.configure(height=height)
        if self.compact and int(self.card.cget("width")) != width:
            self.card.configure(width=width)

    def _wrap_hints(self, event: tk.Event) -> None:
        """Hints wrap to the form's width (beside the label column)."""
        wrap = max(self._px(160), event.width - self._px(LABEL_WIDTH + 64))
        if abs(wrap - self._wrap) < self._px(8):
            return
        self._wrap = wrap
        for item in self.shown_fields.values():
            if item.row.hint is not None:
                item.row.hint.configure(wraplength=wrap)

    # --- Reading config.toml ----------------------------------------------------------------

    def _schedule_refresh(self) -> None:
        """After a check: read again, while the tab shows (showing it reads anyway)."""
        if self.win.closed or self._refresh_id is not None or not self.shown:
            return
        self._refresh_id = self.root.after_idle(self.refresh)

    def refresh(self) -> None:
        """Read ``config.toml``'s open text again and show it: the form's values, the
        broken-file message, or the reason it can't be edited. The preview is asked for when
        the text changed."""
        self._refresh_id = None
        if self.win.closed:
            return
        record = self._record()
        if not record.editable:
            message = record.error.message if record.error is not None else ""
            self._cover(CANT_EDIT.format(reason=message), 1)
            self.text = None
            return
        text = record.widget.get("1.0", "end-1c")
        line = sm.broken(text)
        if line is not None:
            self.text = text
            self._cover(sm.broken_message(line), line)
            return
        self.empty.hide()
        self.state = "form"
        changed = text != self.text
        self.text = text
        found = sm.values(text)
        self.found = found if found is not None else {}
        if changed or self.form_key is None:
            self.complex_paths = self._complex_paths(text)
        key = (self.page.key, self.complex_paths, self.search_text(), self._looks_key())
        if key != self.form_key:
            self._build_form()
            self.form_key = key
        else:
            for item in self.shown_fields.values():
                self._show_value(item)
        if self.page.preview and self.shown:
            self._schedule_preview()

    def _cover(self, message: str, line: int) -> None:
        self.state = "broken"
        self.problem_line = line
        self.empty.hint.configure(text=message)
        self.empty.show(self.frame)
        self._cancel_preview()

    def open_in_editor(self) -> None:
        """Open in Editor: ``config.toml`` at the mistake's line."""
        self.win.jump_to(CONFIG_REF, self.problem_line)

    def _complex_paths(self, text: str) -> frozenset[str]:
        """The keys of the page on screen that ``tomlpatch`` refuses as too complex."""
        fields = self._page_fields() if self.page.key != sm.ALL_SETTINGS \
            else self._interesting(text)
        return frozenset(f.path for f in fields if self._is_complex(text, f))

    def _interesting(self, text: str) -> tuple[sm.Field, ...]:
        """All settings: only fields under a table the file writes inline or as an array
        can be refused, so only those are tried."""
        if "{" not in text and "[[" not in text:
            return ()
        return sm.all_settings().fields

    @staticmethod
    def _is_complex(text: str, field: sm.Field) -> bool:
        if field.kind == "table":
            return False
        found = tomlpatch.plan_remove(text, field.section, field.key)
        return isinstance(found, Refuse) and found.text == tomlpatch.COMPLEX

    # --- The form ---------------------------------------------------------------------------

    def _new_body(self) -> ttk.Frame:
        """A fresh form: the old one goes, with any sections still waiting to be built."""
        if self.grid is not None:
            self.grid.destroy()
        if self._build_id is not None:
            self.root.after_cancel(self._build_id)
            self._build_id = None
        self._pending = []
        self.shown_fields = {}
        self.grid = ttk.Frame(self.scroll.inner)
        self.grid.pack(fill="x", padx=self._px(16), pady=(self._px(8), self._px(24)))
        self.scroll.top()
        return self.grid

    def _build_form(self) -> None:
        body = self._new_body()
        intro = INTRO.get(self.page.key, "")
        if intro:
            ttk.Label(body, text=intro, style="Intro.TLabel", wraplength=self._px(520),
                      justify="left").pack(anchor="w", pady=(0, self._px(8)))
        if self.page.key == sm.ALL_SETTINGS:
            query = self.search_text()
            sections = sm.search(query)
            if not sections:
                ttk.Label(body, text=NO_MATCH.format(text=query.strip()),
                          style="Hint.TLabel").pack(anchor="w", pady=(self._px(8), 0))
            self._pending = list(sections)
            self._build_more()
            return
        if self.page.key == sm.LOOKS:
            self._build_looks(body)
            return
        for section in self.page.sections:
            self._build_section(body, section)
        if not self.page.sections:
            ttk.Label(body, text=EMPTY_PAGE, style="Hint.TLabel").pack(
                anchor="w", pady=(self._px(8), 0))

    # --- Styles & playthrough looks (W9) -----------------------------------------------------

    def looks(self) -> tuple[tuple[str, str], ...]:
        """The look tables in ``config.toml``'s open text."""
        return sm.looks(self.text or "")

    def _looks_key(self) -> tuple:
        """The Looks page's part of the form key: the looks and the one shown (kept, else
        the first); () on other pages."""
        if self.page.key != sm.LOOKS:
            return ()
        found = self.looks()
        if self.look not in found:
            self.look = found[0] if found else None
        return (found, self.look)

    def _page_fields(self) -> tuple[sm.Field, ...]:
        if self.page.key == sm.LOOKS:
            self._looks_key()
            return sm.look_page(*self.look).fields if self.look is not None else ()
        return sm.page(self.page.key).fields

    def _build_looks(self, body: ttk.Frame) -> None:
        """The look picker, + New style and + New playthrough look, then the shown look's
        sections (or the empty state)."""
        px = self._px
        found = self.looks()
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(px(4), 0))
        self.look_box: ttk.Combobox | None = None
        if found:
            ttk.Label(bar, text=LOOK_LABEL).pack(side="left", padx=(0, px(8)))
            titles = [sm.look_title(*look) for look in found]
            box = self.look_box = ttk.Combobox(bar, values=titles, state="readonly",
                                               width=28)
            if self.look in found:
                box.current(found.index(self.look))
            box.bind("<<ComboboxSelected>>",
                     lambda _e: self.select_look(found[box.current()]), add="+")
            box.pack(side="left")
        buttons = ttk.Frame(body)                 # their own row: they fit a narrow form
        buttons.pack(fill="x", pady=(px(8), 0))
        self.new_style_button = ttk.Button(buttons, text=NEW_STYLE, style="Secondary.TButton",
                                           command=lambda: self.new_look(sm.STYLE))
        self.new_style_button.pack(side="left")
        self.new_playthrough_button = ttk.Button(
            buttons, text=NEW_PLAYTHROUGH, style="Secondary.TButton",
            command=lambda: self.new_look(sm.PLAYTHROUGH))
        self.new_playthrough_button.pack(side="left", padx=(px(8), 0))
        if self.look is None:
            ttk.Label(body, text=NO_LOOKS, style="EmptyTitle.TLabel").pack(
                anchor="w", pady=(px(24), 0))
            ttk.Label(body, text=NO_LOOKS_HINT, style="Hint.TLabel").pack(anchor="w")
            return
        ttk.Label(body, text=LOOK_DELETE_HINT, style="Hint.TLabel").pack(
            anchor="w", pady=(px(6), 0))
        for section in sm.look_page(*self.look).sections:
            self._build_section(body, section)

    def select_look(self, look: tuple[str, str]) -> None:
        """Show ``look`` ((kind, name)) on the Looks page."""
        if look == self.look:
            return
        self.look = look
        self.form_key = None
        self.complex_paths = self._complex_paths(self.text or "")
        self.refresh()

    def new_look(self, kind: str, name: str | None = None) -> bool:
        """+ New style / + New playthrough look: ask for its name (``name``: tests), then
        write its first key as one undo step and show it."""
        text = self.config_text()
        if text is None:
            return False
        if name is None:
            taken = [n for k, n in sm.looks(text) if k == kind]
            start = "" if kind == sm.STYLE else str(
                next((n for n in range(2, 100) if str(n) not in taken), 2))
            answer = ask_text(self.root, NEW_STYLE_ASK if kind == sm.STYLE
                              else NEW_PLAYTHROUGH_ASK, start, ok=CREATE,
                              hint=lambda typed: sm.new_look_problem(kind, typed, text)
                              if typed.strip() else None, select_stem=False)
            if answer is None:
                return False
            name = answer[0]
        name = name.strip()
        problem = sm.new_look_problem(kind, name, text)
        if problem is not None:
            show_error(self.root, problem)
            return False
        section, key, value = sm.new_look_change(kind, name, self.found)
        found = sm.look_page(kind, name).fields
        field = next(f for f in found if f.section == section and f.key == key)
        self.look = (kind, name)
        self.form_key = None
        return self._apply(tomlpatch.plan_set(text, section, key, value), field)

    def _build_more(self) -> None:
        """All settings: the next few sections, then the rest on later idle steps (each
        section is its own grid, so adding one doesn't lay the others out again)."""
        self._build_id = None
        body = self.grid
        if body is None or not body.winfo_exists():
            return
        for _ in range(SECTIONS_PER_STEP):
            if not self._pending:
                return
            self._build_section(body, self._pending.pop(0))
        if self._pending:
            self._build_id = self.root.after(1, self._build_more)

    def finish_building(self) -> None:
        """Build every section still waiting (tests, search jumps)."""
        while self._pending:
            if self._build_id is not None:
                self.root.after_cancel(self._build_id)
            self._build_more()

    def _build_section(self, body: ttk.Frame, section: sm.Section) -> None:
        grid = FormGrid(body, scale=self.scale, label_width=LABEL_WIDTH)
        grid.frame.pack(fill="x", pady=(self._px(12), 0))
        grid.caption(section.title)
        line = grid.frame.grid_slaves(row=grid.next_row - 1, column=1)
        if line:
            ttk.Label(line[0], text=SECTION_PATH.format(path=section.path),
                      style="Hint.TLabel").pack(
                side="left", padx=(self._px(8), 0))
        for found in section.fields:
            self._build_field(grid, found)

    def _build_field(self, grid: FormGrid, found: sm.Field) -> None:
        spec = found.widget
        value = found.current(self.found)
        complex_ = found.path in self.complex_paths
        if spec.kind == "table":
            button = ttk.Button(grid.frame, text=OPEN_IN_EDITOR, style="Secondary.TButton",
                                command=lambda: self._open_section(found.section))
            row = grid.row(found.label, button,
                           hint=f"{sentence(found.help)} {spec.reason}".strip())
            row.label.configure(wraplength=self._px(LABEL_WIDTH - 12))
            if row.hint is not None:
                row.hint.configure(wraplength=self._wrap)
            self.shown_fields[found.path] = Shown(found, None, row)
            return
        widget = self._make_widget(grid.frame, found, value)
        hint = tomlpatch.COMPLEX if complex_ else field_hint(found)
        row = grid.row(found.label, widget,
                       on_default=lambda: self.use_default(found), hint=hint)
        row.label.configure(wraplength=self._px(LABEL_WIDTH - 12))
        if row.hint is not None:
            row.hint.configure(wraplength=self._wrap)
        item = Shown(found, widget, row, complex_)
        if complex_ and row.default is not None:
            widget.enable(False)
            row.default.configure(text=EDIT_AS_SCRIPT,
                                  command=lambda: self.edit_as_script(found))
        self.shown_fields[found.path] = item
        self._show_value(item)

    def _make_widget(self, parent: tk.Misc, found: sm.Field, value: object) -> _Field:
        spec = found.widget
        change = (lambda new, f=found: self.set_value(f, new))
        if spec.kind == "toggle":
            return ToggleField(parent, "", bool(value), on_change=change)
        if spec.kind == "choice":
            return ChoiceField(parent, [(o, o.replace("_", " ").capitalize())
                                        for o in spec.options], value, on_change=change)
        if spec.kind == "color":
            return ColorField(parent, value if isinstance(value, str) else None,
                              on_change=change, allow_none=found.default is None,
                              scale=self.scale)
        if spec.kind == "number":
            lo = 0 if spec.off else spec.lo
            start = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
                else (found.default if isinstance(found.default, (int, float)) else lo)
            return NumberField(parent, start, lo=lo, hi=spec.hi, step=spec.step,
                               whole=spec.integer, width=8,
                               on_change=lambda new, f=found: self.set_value(
                                   f, f.widget.clamp(new)))
        if spec.kind == "file":
            refs = self._refs(found)
            play = thumb = None
            if spec.preview == "play":
                play = (lambda name, f=found: self.toggle_sound(f, name))
            elif spec.group == "gui":
                thumb = (lambda ref: self.thumbs.get(ref))
            return AssetPicker(parent, refs, value if isinstance(value, str) else None,
                               on_change=change, none_text=NONE_FILE, play=play,
                               thumb=thumb, width=30, scale=self.scale)
        if spec.multiline:
            return LongTextField(parent, str(value or ""), on_change=change)
        if spec.names:
            return TextField(parent, spec.to_text(value), width=TEXT_WIDTH,
                             on_change=lambda text, f=found: self.set_value(
                                 f, f.widget.from_text(str(text))))
        return TextField(parent, "" if value is None else str(value), width=TEXT_WIDTH,
                         on_change=change)

    def _refs(self, found: sm.Field) -> list[str]:
        """The files ``found`` can pick, as the key writes them (``audio/`` left out)."""
        project = self.win.project
        spec = found.widget
        refs = project.file_refs(spec.group) if project is not None else []
        out = []
        for ref in refs:
            if spec.suffixes and not ref.lower().endswith(spec.suffixes):
                continue
            if spec.strip:
                if not ref.startswith(spec.strip):
                    continue
                ref = ref[len(spec.strip):]
            out.append(ref)
        return out

    def _show_value(self, item: Shown) -> None:
        found = item.field
        value = found.current(self.found)
        changed = found.is_set(self.found) and not same_value(found, value, found.default)
        item.row.bar.configure(background=ROLES["accent"] if changed
                               else THEME["editor.background"])
        if item.widget is None:
            return
        if not item.complex and item.row.default is not None:
            item.row.default.configure(
                state="normal" if found.is_set(self.found) else "disabled")
        widget = item.widget
        if found.kind == "file" and isinstance(widget, AssetPicker):
            widget.set_refs(self._refs(found))
        shown = self._widget_value(found, value)
        if shown != widget.value or type(shown) is not type(widget.value):
            widget.set(shown)

    @staticmethod
    def _widget_value(found: sm.Field, value: object) -> object:
        spec = found.widget
        if spec.kind == "toggle":
            return bool(value)
        if spec.kind == "number":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
            return found.default if isinstance(found.default, (int, float)) else spec.lo
        if spec.kind in ("color", "file"):
            return value if isinstance(value, str) else None
        return spec.to_text(value)

    # --- Writing (PR-F47-04, 04 §7.2) -------------------------------------------------------

    def set_value(self, found: sm.Field, value: object) -> bool:
        """Write ``value`` for ``found`` (None: Use default) as one undo step."""
        if value is None:
            return self.use_default(found)
        text = self.config_text()
        if text is None:
            self.refresh()
            return False
        if not found.is_set(self.found) and same_value(found, value, found.default) \
                and not sm.is_look(found):      # a look's "not set" is the main look
            self.refresh()
            return True                 # the default, unchanged: nothing to write
        return self._apply(tomlpatch.plan_set(text, found.section, found.key, value), found)

    def use_default(self, found: sm.Field) -> bool:
        """**Use default**: remove the key's line."""
        text = self.config_text()
        if text is None:
            self.refresh()
            return False
        return self._apply(tomlpatch.plan_remove(text, found.section, found.key), found)

    def _apply(self, plan: tomlpatch.TomlPlan | Refuse | None, found: sm.Field) -> bool:
        if plan is None:
            self.refresh()
            return True
        if isinstance(plan, Refuse):
            if plan.text == tomlpatch.COMPLEX:
                if ask(self.root, plan.text, COMPLEX_BUTTONS, escape=1) == 0:
                    self.edit_as_script(found, plan.place)
            else:
                show_error(self.root, plan.text)
            self.refresh()
            return False
        tp = plan
        if not self.win.apply_plan(tp.as_plan(),
                                   lambda texts: tomlpatch.verify(tp, texts[CONFIG_REF])):
            show_error(self.root, STALE)
            self.refresh()
            return False
        self.win._update_marks()
        self.refresh()
        return True

    def edit_as_script(self, found: sm.Field, place: tuple[str, int] | None = None) -> None:
        """Open ``config.toml`` at the line that holds ``found``'s table."""
        if place is None:
            text = self.config_text() or ""
            refused = tomlpatch.plan_remove(text, found.section, found.key)
            place = refused.place if isinstance(refused, Refuse) else None
        ref, line = place if place is not None else (CONFIG_REF, 1)
        self.win.jump_to(ref, line)

    def _open_section(self, path: str) -> None:
        self.win.jump_to(CONFIG_REF, section_line(self.config_text() or "", path))

    # --- All settings search ----------------------------------------------------------------

    def _search_placeholder(self, on: bool) -> None:
        if on and not self.search_var.get():
            self._placeholder = True
            self.search.configure(foreground=THEME["muted"])
            self.search_var.set(SEARCH_HINT)
        elif not on and self._placeholder:
            self._placeholder = False
            self.search_var.set("")
            self.search.configure(foreground=THEME["input.foreground"])

    def search_text(self) -> str:
        if self.page.key != sm.ALL_SETTINGS or self._placeholder:
            return ""
        return self.search_var.get()

    def set_search(self, text: str) -> None:
        """Type ``text`` into the search box (tests, keyboard helpers)."""
        self._search_placeholder(False)
        self.search_var.set(text)
        self._run_search()

    def _on_search(self) -> None:
        if self._placeholder or self.page.key != sm.ALL_SETTINGS:
            return
        if self._search_id is not None:
            self.root.after_cancel(self._search_id)
        self._search_id = self.root.after(SEARCH_DELAY_MS, self._run_search)

    def _run_search(self) -> None:
        if self._search_id is not None:
            self.root.after_cancel(self._search_id)
        self._search_id = None
        if self.page.key == sm.ALL_SETTINGS:
            self.refresh()

    # --- Preview (PR-F47-16, 04 §7.3) -------------------------------------------------------

    def _schedule_preview(self) -> None:
        """Ask for a still ``PREVIEW_DELAY_MS`` after the last change (only when the text
        or the page changed since the last still)."""
        kind = self.page.preview
        if not kind or self.text is None or self._previewed == (kind, self.text):
            return
        self._cancel_preview()
        self._set_status(UPDATING)
        self._preview_id = self.root.after(PREVIEW_DELAY_MS, self._ask_still)

    def _cancel_preview(self) -> None:
        if self._preview_id is not None:
            self.root.after_cancel(self._preview_id)
            self._preview_id = None

    def _ask_still(self) -> None:
        self._preview_id = None
        kind = self.page.preview
        record = self._record()
        if not kind or not record.editable or self.win.closed:
            return
        text = record.widget.get("1.0", "end-1c")
        try:
            data = encode(record.doc, text)
        except SaveError:
            data = text.encode("utf-8", "replace")
        hub = hub_for(self.win)
        if not self._listening:
            hub.listen(self._reply)
            self._listening = True
        width = self.card.winfo_width()
        width = min(PREVIEW_MAX, width if width > 16 else self._px(480))
        self._previewed = (kind, text)
        self._serial = hub.runner.still(kind, width, data)
        self._set_status(UPDATING)

    def _reply(self, reply: Any) -> None:
        if reply.op != "still" or reply.kind != self.page.preview or \
                reply.serial != self._serial:
            return
        if not reply.ok or not reply.data:
            self._image = None
            self.picture.configure(image="")
            self._set_status(NOT_AVAILABLE.format(reason=reply.reason or "unknown"))
            return
        try:
            image = tk.PhotoImage(master=self.frame, data=reply.data)
        except tk.TclError as exc:
            self._set_status(NOT_AVAILABLE.format(reason=str(exc)))
            return
        self._image = image
        self.picture.configure(image=image, text="")
        self._set_status("")

    def _set_status(self, text: str) -> None:
        self.status = text
        self.card_status.configure(text=text)
        if self._image is None:
            self.picture.configure(text=text, image="",
                                   wraplength=max(self._px(200), self.card.winfo_width() - 24))

    def preview_image(self) -> tk.PhotoImage | None:
        return self._image

    # --- Sounds (title music ▶) -------------------------------------------------------------

    def toggle_sound(self, found: sm.Field, name: str) -> None:
        hub = hub_for(self.win)
        if not self._sound_listening:
            hub.listen(self._sound_reply)
            self._sound_listening = True
        ref = found.widget.strip + name
        if hub.playing == ref:
            hub.stop_sound()
            self._playing_path = None
        else:
            hub.play(ref)
            self._playing_path = found.path
        self._sync_play()

    def stop_sound(self) -> None:
        hub = getattr(self.win, "helper_hub", None)
        if hub is not None and hub.playing is not None:
            hub.stop_sound()
        self._playing_path = None
        self._sync_play()

    def _sound_reply(self, reply: Any) -> None:
        if reply.op == "play" and not reply.ok:
            show_error(self.root, CANT_PLAY.format(reason=reply.reason or ""))
        if reply.op in ("play", "stop", "ended"):
            hub = getattr(self.win, "helper_hub", None)
            if hub is None or hub.playing is None:
                self._playing_path = None
            self._sync_play()

    def _sync_play(self) -> None:
        for path, item in self.shown_fields.items():
            if isinstance(item.widget, AssetPicker) and item.widget.play_button is not None:
                try:
                    item.widget.set_playing(path == self._playing_path)
                except tk.TclError:
                    pass

    def _thumb_ready(self, ref: str) -> None:
        for item in self.shown_fields.values():
            if isinstance(item.widget, AssetPicker) and item.widget.value == ref:
                item.widget._show()

    def _on_tab_changed(self) -> None:
        if not self.shown:
            self.stop_sound()
            self._cancel_preview()


__all__ = ["COMPLEX_BUTTONS", "LongTextField", "NOT_AVAILABLE", "OPEN_IN_EDITOR",
           "PREVIEW_DELAY_MS", "SECTION_PATH", "SettingsPane", "UPDATING", "field_hint",
           "section_line",
           "sentence"]
