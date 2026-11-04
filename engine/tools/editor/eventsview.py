"""The Story map side pane's Events tab (F46 ``04-technical.md`` §6.7, §6.11; design §6.1,
§6.4).

Why this module exists: the Events tab shows a scene as RPG Maker-style rows, one per
statement (``forms.Row``), indented by depth, each block ending in a ◆ row. A row reads as its
command word in **muted** text and its summary in **text**; Script rows show their line in
the code font. A ``ttk.Treeview`` can colour only whole rows, so ``tree`` is a read-only
``tk.Text`` that behaves as a one-choice list: click, Up/Down/Home/End/Page keys, Enter or a
double-click (``on_open``), the focus ring, and F6 lands on it. ``on_select(i)`` runs when the
author picks row ``i`` (never for ``select(..., notify=False)``).

Imports: ``tkinter``, ``forms``, ``theme`` (no pygame; ADR-0008 Amendment 1 §6).
"""

import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from tkinter import font as tkfont
from tkinter import ttk

from engine.tools.editor import icons
from engine.tools.editor.forms import Row
from engine.tools.editor.theme import THEME

NO_SCENE = "Select a scene to see what happens in it."      # design PR-F46-27
NO_SCENE_TITLE = "No scene selected"                        # 08 §9's pattern (AC-F46-37)
OUT_OF_DATE = "out of date"
ROW_PAD_PX = 4              # above and below each row's text, at 100 %
INSET_PX = 12               # the rows' left edge
INDENT_PX = 22              # per depth
WORD_GAP_PX = 14            # between the word column and the summary
WORD_MAX_PX = 150           # the word column at most (a longer word pushes its summary on)
LIST_KEYS = ("<Up>", "<Down>", "<Home>", "<End>", "<Prior>", "<Next>")
# The buttons row (step 3): (label, action name), the actions ``StoryEditor`` runs.
BUTTONS = (("Insert…", "insert"), ("Edit", "edit"), ("↑", "up"), ("↓", "down"),
           ("Delete", "delete"))
DRAG_PX = 6                 # a press must move this far before it drags a row


class EventsView:
    """The Events page: the scene's name and place over the row list."""

    def __init__(self, parent: tk.Misc, *, fonts: Mapping[str, tkfont.Font],
                 scale: float = 1.0, on_select: Callable[[int], None] | None = None,
                 on_open: Callable[[int], None] | None = None) -> None:
        self.scale = scale
        self.on_action: Callable[[str], None] | None = None   # a buttons-row click
        self.on_drop: Callable[[int, int], None] | None = None  # row dragged onto row
        self._drag: tuple[int, int] | None = None              # (row, press y)
        self._dragging = False
        self.fonts = fonts
        self.on_select = on_select
        self.on_open = on_open
        self.rows: tuple[Row, ...] = ()
        self.index: int | None = None
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(3, weight=1)
        px = self._px
        head = ttk.Frame(self.frame)
        head.grid(row=0, column=0, columnspan=2, sticky="ew",
                  padx=px(INSET_PX), pady=(px(10), px(6)))
        self.title = ttk.Label(head, text="", style="Title.TLabel")
        self.title.pack(side="left")
        self.where = ttk.Label(head, text="", foreground=THEME["muted"],
                               font=fonts.get("detail"))
        self.where.pack(side="left", padx=(px(10), 0), pady=(px(2), 0))
        self.stale = ttk.Label(head, text="", foreground=THEME["marker.warning"],
                               font=fonts.get("detail"))
        self.stale.pack(side="left", padx=(px(10), 0), pady=(px(2), 0))
        tools = self.tools = ttk.Frame(self.frame)
        # What the scene needs before the story can get here (``script/reach.py``).
        self.reach = ReachBox(self.frame, fonts=fonts, scale=scale)
        self.reach.frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                              padx=px(INSET_PX), pady=(0, px(6)))
        self.reach.frame.grid_remove()
        tools.grid(row=2, column=0, columnspan=2, sticky="ew",
                   padx=px(INSET_PX - 4), pady=(0, px(6)))
        self.buttons: dict[str, ttk.Button] = {}
        self._icons: list[object] = []          # drawn arrows (an emoji font colours ↑ ↓)
        for label, name in BUTTONS:
            options: dict[str, object] = {"text": label}
            if name in ("up", "down"):
                image = icons.photo(self.frame, name, px(14), THEME["foreground"])
                self._icons.append(image)
                options = {"image": image, "text": label, "compound": "image"}
            button = ttk.Button(tools, takefocus=0, style="Events.Ghost.TButton",
                                width=-1, command=lambda n=name: self._action(n), **options)
            button.pack(side="left", padx=(0, px(2)))
            self.buttons[name] = button
        style = ttk.Style(self.frame)
        style.configure("Events.Ghost.TButton", padding=(px(10), px(3)))
        surface = self.background = THEME["editor.background"]
        body = fonts.get("body")
        self.tree = tk.Text(
            self.frame, wrap="word", width=1, height=1, cursor="arrow", font=body,
            background=surface, foreground=THEME["foreground"], borderwidth=0,
            highlightthickness=1, highlightbackground=surface,
            highlightcolor=THEME["focusBorder"], padx=0, pady=px(2),
            spacing1=px(ROW_PAD_PX), spacing3=px(ROW_PAD_PX), insertwidth=0,
            selectbackground=surface, inactiveselectbackground=surface,
            selectforeground=THEME["foreground"], exportselection=False, takefocus=1,
            undo=False)
        self.tree.grid(row=3, column=0, sticky="nsew")
        # The status line under the list: what an action did or why it didn't (a link when
        # it names a place).
        self.message = ttk.Label(self.frame, text="", foreground=THEME["muted"],
                                 font=fonts.get("small"), wraplength=1, justify="left")
        self.message.grid(row=4, column=0, columnspan=2, sticky="ew",
                          padx=px(INSET_PX), pady=(px(6), px(8)))
        self.message.grid_remove()
        self.message.bind("<Configure>", lambda e: self.message.configure(
            wraplength=max(1, e.width)), add="+")
        self.message.bind("<Button-1>", lambda _e: self._open_link())
        self.on_link: Callable[[], None] | None = None
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self._bar = bar
        self.tree.configure(yscrollcommand=self._yscroll)
        self.tree.tag_configure("word", foreground=THEME["muted"])
        self.tree.tag_configure("summary", foreground=THEME["foreground"])
        self.tree.tag_configure("code", foreground=THEME["editor.foreground"],
                                font=fonts.get("codeSmall") or body)
        self.tree.tag_configure("choice", foreground=THEME["strongForeground"])
        self.tree.tag_configure("end", foreground=THEME["muted"])
        self.tree.tag_configure("plain", foreground=THEME["muted"])
        self.tree.tag_configure("hover", background=THEME["list.hoverBackground"],
                                lmargincolor=THEME["list.hoverBackground"])
        self.tree.tag_configure("chosen", background=THEME["list.inactiveSelection"],
                                lmargincolor=THEME["list.inactiveSelection"])
        self.tree.tag_raise("chosen", "hover")
        self.tree.tag_configure("chosenword", foreground=THEME["foreground"])
        self.tree.tag_raise("chosenword", "word")
        self.tree.configure(state="disabled")
        self._depths: set[int] = set()
        self._hovered: int | None = None
        tree = self.tree
        tree.bind("<Button-1>", self._click)
        tree.bind("<Double-Button-1>", self._double)
        tree.bind("<B1-Motion>", self._drag_motion)
        tree.bind("<ButtonRelease-1>", self._drag_release)
        for key in ("<Shift-Button-1>", "<Triple-Button-1>", "<Control-Button-1>"):
            tree.bind(key, lambda _e: "break")
        tree.bind("<Motion>", self._motion)
        tree.bind("<Leave>", lambda _e: self._hover(None))
        for key, step in (("<Up>", -1), ("<Down>", 1)):
            tree.bind(key, lambda _e, s=step: self._step(s))
        tree.bind("<Home>", lambda _e: self._go(0))
        tree.bind("<End>", lambda _e: self._go(len(self.rows) - 1))
        tree.bind("<Prior>", lambda _e: self._page(-1))
        tree.bind("<Next>", lambda _e: self._page(1))
        for key in ("<Return>", "<KP_Enter>"):
            tree.bind(key, self._enter)
        tree.bind("<FocusIn>", lambda _e: self._paint_chosen(True), add="+")
        tree.bind("<FocusOut>", lambda _e: (self.cancel_drag(), self._paint_chosen(False)),
                  add="+")
        # No scene shown (PR-F46-27): the empty state over the list (08 §9).
        from engine.tools.editor.views import EmptyState
        self.empty = EmptyState(self.frame, icon="events", title=NO_SCENE_TITLE,
                                hint=NO_SCENE, scale=scale)
        self.set_rows((), title="")

    def set_reach(self, rows: Sequence[object]) -> None:
        """The scene's ``reach`` rows (``checker.ReachRow``): shown above the buttons, or
        nothing when it has none."""
        self.reach.show(rows)
        if self.reach.rows:
            self.reach.frame.grid()
        else:
            self.reach.frame.grid_remove()

    def _px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def _yscroll(self, first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._bar.grid_remove()
        else:
            self._bar.grid(row=3, column=1, sticky="ns")
        self._bar.set(first, last)

    # --- Content ------------------------------------------------------------------------------

    def set_rows(self, rows: Sequence[Row], *, title: str, where: str = "",
                 stale: bool = False, select: int | None = None) -> None:
        """Show ``rows`` under ``title`` (the scene) and ``where`` (its file and line); with
        no title, the "select a scene" note. ``select`` picks a row without notifying."""
        rows = tuple(rows)
        self.title.configure(text=title, style="Title.TLabel")
        if title:
            self.empty.hide()
        else:
            self.empty.show(self.tree)
        self.where.configure(text=where)
        self.stale.configure(text=OUT_OF_DATE if stale else "")
        tree = self.tree
        if rows != self.rows:
            self.rows = rows
            self._hovered = None
            tree.configure(state="normal")
            tree.delete("1.0", "end")
            words = [r for r in rows if r.kind in ("stmt", "header") and r.summary
                     and not r.word.startswith('"')]
            measure = self.fonts["body"].measure if "body" in self.fonts else \
                tkfont.nametofont("TkDefaultFont").measure
            word_px = min(self._px(WORD_MAX_PX),
                          max((measure(r.word) for r in words), default=0))
            for row in rows:
                self._depth_tag(row.depth, word_px)
                self._insert_row(row)
            tree.delete("end-1c", "end")         # no empty line after the last row
            tree.configure(state="disabled")
        self.index = None
        if select is not None and rows:
            self.select(select, notify=False)
        else:
            self._paint_chosen()

    def _depth_tag(self, depth: int, word_px: int) -> None:
        margin = self._px(INSET_PX) + depth * self._px(INDENT_PX)
        column = margin + word_px + self._px(WORD_GAP_PX)
        # A long summary wraps under itself, not under the word.
        self.tree.tag_configure(f"d{depth}", lmargin1=margin, lmargin2=column,
                                tabs=(column,))
        self._depths.add(depth)

    def _insert_row(self, row: Row) -> None:
        tree, depth = self.tree, f"d{row.depth}"
        if row.kind in ("end", "more") or not row.summary and row.form is None \
                and row.kind == "stmt" and row.word != "Script":
            tag = "end" if row.kind == "end" else "plain"
            tree.insert("end", row.word, (depth, tag))
        elif row.kind == "header" and row.word.startswith('"'):
            tree.insert("end", row.word, (depth, "choice"))
            if row.summary:
                tree.insert("end", "  " + row.summary, (depth, "word"))
        else:
            tree.insert("end", row.word, (depth, "word" if row.summary else "summary"))
            if row.summary:
                code = "code" if row.form is None else "summary"
                tree.insert("end", "\t", (depth,))
                tree.insert("end", row.summary, (depth, code))
        tree.insert("end", "\n", (depth,))

    def say(self, text: str, *, link: Callable[[], None] | None = None) -> None:
        """The status line: ``text`` (none: hidden); with ``link``, a click on it runs it."""
        self.on_link = link
        self.message.configure(
            text=text, cursor="hand2" if link else "",
            foreground=THEME["link"] if link else THEME["muted"],
            font=self._link_font() if link else self.fonts.get("small"))
        if text:
            self.message.grid()
        else:
            self.message.grid_remove()

    def said(self) -> str:
        return str(self.message.cget("text"))

    def _link_font(self) -> tkfont.Font | None:
        small = self.fonts.get("small")
        if small is None:
            return None
        if not hasattr(self, "_underlined"):
            self._underlined = tkfont.Font(**small.actual())
            self._underlined.configure(underline=True)
        return self._underlined

    def _open_link(self) -> None:
        if self.on_link is not None:
            self.on_link()

    def _action(self, name: str) -> None:
        if self.on_action is not None:
            self.on_action(name)

    def texts(self) -> list[str]:
        """Every row as ``forms.Row.text`` (word, two spaces, summary), in order."""
        return [row.text for row in self.rows]

    # --- Selection ----------------------------------------------------------------------------

    def select(self, index: int, *, notify: bool = True) -> None:
        """Choose row ``index`` (clamped) and scroll it into view."""
        if not self.rows:
            return
        index = max(0, min(index, len(self.rows) - 1))
        self.index = index
        self._paint_chosen()
        self.tree.see(f"{index + 1}.0")
        if notify and self.on_select is not None:
            self.on_select(index)

    def selected(self) -> int | None:
        return self.index

    def _paint_chosen(self, focused: bool | None = None) -> None:
        """The chosen row's background: **selection** with the focus, else inactive."""
        tree = self.tree
        tree.tag_remove("chosen", "1.0", "end")
        tree.tag_remove("chosenword", "1.0", "end")
        if self.index is None or not tree.winfo_exists():
            return
        if focused is None:
            try:
                focused = tree.focus_get() is tree
            except (KeyError, tk.TclError):
                focused = False
        color = THEME["list.activeSelection" if focused else "list.inactiveSelection"]
        tree.tag_configure("chosen", background=color, lmargincolor=color)
        line = self.index + 1
        tree.tag_add("chosen", f"{line}.0", f"{line + 1}.0")
        # The command word turns from muted to text on the chosen row (AC-F46-36).
        found = tree.tag_nextrange("word", f"{line}.0", f"{line}.end")
        while found:
            tree.tag_add("chosenword", *found)
            found = tree.tag_nextrange("word", found[1], f"{line}.end")

    def _row_at(self, y: int) -> int | None:
        if not self.rows:
            return None
        line = int(self.tree.index(f"@0,{y}").split(".")[0])
        last = self.tree.dlineinfo("end-1c")
        if last is not None and y > last[1] + last[3]:
            return None                          # below the last row
        return min(line, len(self.rows)) - 1

    def _click(self, event: tk.Event) -> str:
        self.tree.focus_set()
        index = self._row_at(event.y)
        self._drag, self._dragging = (None if index is None else (index, event.y)), False
        if index is not None:
            self.select(index)
        else:
            self._paint_chosen()
        return "break"

    def _drag_motion(self, event: tk.Event) -> str:
        """A press that moves ``DRAG_PX`` drags its row; the row under the pointer shows
        where it lands (PR-F46-23)."""
        if self._drag is None:
            index = self._row_at(event.y)
            if index is None:
                return "break"
            self._drag = (index, event.y)
        if not self._dragging and abs(event.y - self._drag[1]) >= self._px(DRAG_PX):
            self._dragging = True
            self.tree.configure(cursor="fleur")
        if self._dragging:
            self._hover(self._row_at(event.y))
        return "break"

    def _drag_release(self, event: tk.Event) -> str | None:
        drag, dragging = self._drag, self._dragging
        self._drag, self._dragging = None, False
        self.tree.configure(cursor="arrow")
        if drag is None or not dragging:
            return None
        target = self._row_at(event.y)
        if target is not None and target != drag[0] and self.on_drop is not None:
            self.on_drop(drag[0], target)
        return "break"

    def cancel_drag(self) -> None:
        self._drag, self._dragging = None, False
        self.tree.configure(cursor="arrow")

    def _double(self, event: tk.Event) -> str:
        index = self._row_at(event.y)
        if index is not None and self.on_open is not None:
            self.select(index, notify=False)
            self.on_open(index)
        return "break"

    def _enter(self, _event: tk.Event | None = None) -> str:
        if self.index is not None and self.on_open is not None:
            self.on_open(self.index)
        return "break"

    def _step(self, step: int) -> str:
        if self.rows:
            self.select(0 if self.index is None else self.index + step)
        return "break"

    def _go(self, index: int) -> str:
        if self.rows:
            self.select(index)
        return "break"

    def _page(self, step: int) -> str:
        if self.rows:
            height = self.tree.winfo_height()
            line = self.tree.dlineinfo("1.0") or self.tree.dlineinfo("@0,0")
            per = max(1, height // max(1, line[3] if line else 20) - 1)
            self.select((self.index or 0) + step * per)
        return "break"

    def _motion(self, event: tk.Event) -> None:
        self._hover(self._row_at(event.y))

    def _hover(self, index: int | None) -> None:
        if index == self._hovered:
            return
        self._hovered = index
        self.tree.tag_remove("hover", "1.0", "end")
        if index is not None:
            self.tree.tag_add("hover", f"{index + 1}.0", f"{index + 2}.0")



# --- To get here (``script/reach.py`` via the check child) ----------------------------------

REACH_HEADING = "TO GET HERE"
REACH_SET_HEADING = "SET BY"
REACH_ROWS_MAX = 8
REACH_MORE = "…and {n} more"


class ReachBox:
    """What a scene needs before the story can get there: a warning when no playthrough
    can, each way in with its conditions, and the lines that set what they read. A row
    with a place opens it (``on_place(file, line)``)."""

    def __init__(self, parent: tk.Misc, *, fonts: Mapping[str, tkfont.Font],
                 scale: float = 1.0) -> None:
        self.scale = scale
        self.fonts = fonts
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.rows: tuple = ()
        self.labels: list[ttk.Label] = []
        self.on_place: Callable[[str, int], None] | None = None
        self.frame.bind("<Configure>", lambda e: [label.configure(
            wraplength=max(1, e.width - 4)) for label in self.labels], add="+")

    def texts(self) -> list[str]:
        """What it shows, top to bottom (tests read it)."""
        return [str(label.cget("text")) for label in self.labels]

    def show(self, rows: Sequence[object]) -> None:
        rows = tuple(rows)
        if rows == self.rows:
            return
        self.rows = rows
        for label in self.labels:
            label.destroy()
        self.labels = []
        small = self.fonts.get("small")
        blocked = [r for r in rows if r.kind == "blocked"]
        ways = [r for r in rows if r.kind == "way"]
        sets = [r for r in rows if r.kind == "set"]
        for row in blocked:
            self._add("⚠ " + row.text, row, foreground=THEME["marker.warning"])
        for heading, group in ((REACH_HEADING, ways), (REACH_SET_HEADING, sets)):
            if not group:
                continue
            self._add(heading, None, foreground=THEME["muted"], font=small,
                      pady=(round(4 * self.scale), 0))
            for row in group[:REACH_ROWS_MAX]:
                never = "(never:" in row.text
                self._add("• " + row.text, row, font=small,
                          foreground=THEME["marker.warning"] if never else THEME["foreground"])
            if len(group) > REACH_ROWS_MAX:
                self._add(REACH_MORE.format(n=len(group) - REACH_ROWS_MAX), None,
                          foreground=THEME["muted"], font=small)

    def _add(self, text: str, row: object | None, *, foreground: str, font: object = None,
             pady: tuple[int, int] = (0, 0)) -> None:
        label = ttk.Label(self.frame, text=text, foreground=foreground, justify="left",
                          wraplength=max(1, self.frame.winfo_width() - 4))
        if font is not None:
            label.configure(font=font)
        label.grid(row=len(self.labels), column=0, sticky="w", pady=pady)
        place = (getattr(row, "file", None), getattr(row, "line", None)) if row else None
        if place and place[0] and place[1]:
            label.configure(cursor="hand2")
            label.bind("<Button-1>", lambda _e, p=place: self._open(*p))
        self.labels.append(label)

    def _open(self, file: str, line: int) -> None:
        if self.on_place is not None:
            self.on_place(file, line)


__all__ = ["EventsView", "NO_SCENE", "NO_SCENE_TITLE", "OUT_OF_DATE", "REACH_HEADING",
           "REACH_SET_HEADING", "ReachBox"]
