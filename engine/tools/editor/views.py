"""Studio's views: the project panel's tree, the Asset tab, the Help pane, the completion
list, and the story map canvas (F45 ``01`` §6.1, §6.2, PR-F45-01, PR-F45-13, PR-F45-16,
PR-F45-18..20, UI-F45-04, UI-F45-06; ``04`` §3, §7.4, §7.6, §7.7).

``ProjectView`` draws a ``files.ProjectTree`` in a ``ttk.Treeview`` whose item ids are game
refs (a group's is its folder, ``config.toml``'s is ``config.toml``). Refilling keeps which
folders are open and what is selected. ``AssetPane`` shows a file's facts and, for a PNG or
GIF within the caps, a thumbnail decoded by Tk from bytes (``read_asset``; Tk never opens a
path). ``HelpPane`` shows ``assist.help_sections``. ``CompletionPopup`` is the borderless
list under the cursor; the editor keeps the keyboard focus while it is open. ``StoryMapView``
draws ``storymap.layout`` on a canvas and moves a focus ring with the keys. ``StatusBar`` is
the neutral strip along the window's bottom edge (F45 ``01`` §6.5, ``08`` D1). ``MenuBar`` is
the dark in-window menu bar of Windows and Linux (``08`` D5). Colors come from
``theme.THEME``; every size is px at 100 % times the window's ``scale`` (``08`` §10).

Imports only ``engine.core``, ``engine.script``, ``engine.tools.editor`` and the standard
library (ADR-0008).
"""

import base64
import math
import os
import struct
import sys
import time
import tkinter as tk
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from engine.core.errors import AssetTooLarge, EngineError
from engine.core.imageheader import image_dimensions
from engine.core.paths import GamePaths
from engine.script.imagenames import image_suffix, name_of
from engine.tools.editor import icons
from engine.tools.editor.assist import (
    COMPLETION_VISIBLE,
    Candidate,
    Context,
    help_sections,
)
from engine.tools.editor.files import ProjectTree, Refusal, TreeNode
from engine.tools.editor.storymap import (
    BOX_HEIGHT,
    BOX_WIDTH,
    CHIP_SLOTS,
    PLACE_STEP,
    ROW_STEP,
    LINK_KINDS,
    MARK_DELETES_SAVES,
    MARK_ENDING,
    MARK_START,
    Box,
    MapLayout,
    Notes,
    chip_text,
    curve_at,
    curve_points,
    hidden_text,
    label_files,
    layout,
    layout_places,
    neighbour,
    out_edges,
)
from engine.tools.editor.scriptedit import snap
from engine.tools.editor.outline import NO_OUTLINE
from engine.tools.editor.outline import Row as OutlineRow
from engine.tools.editor.syntax import PLAIN_COLOR
from engine.tools.editor.theme import THEME

DIRTY_MARK = "* "
MESSAGE_ID = "!message"                 # the one row shown when the game folder is gone
MUTED = THEME["muted"]
PANEL_BACKGROUND = THEME["panel.background"]
CHOSEN_BACKGROUND = THEME["list.activeSelection"]
CHOSEN_FOREGROUND = THEME["list.activeSelectionForeground"]
SELECTION_BACKGROUND = THEME["editor.selection"]
FOCUS_BORDER = THEME["focusBorder"]
NO_PREVIEW = "No preview for this file."
ASSET_EMPTY_TITLE = "Nothing selected"                          # 08 §9
ASSET_EMPTY_HINT = "Pick an image or sound in the Project panel."
CHECK_NOW_BUTTON = "Check now (F7)"
COPY_NAME = "Copy name"
NO_HELP_DOC = object()                  # HelpPane.doc before anything is shown

# --- Asset preview (04 §7.7, C-3) ---------------------------------------------------------

PREVIEW_MAX_BYTES = 32 * 1024 * 1024    # read cap; past it only the facts show
PREVIEW_MAX_PIXELS = 16_777_216         # 16 Mpx: Tk holds full pixels on its main thread
PREVIEW_FORMATS = ("png", "gif")        # what Tk decodes natively (JPEG and WebP: 04 Q7)
PREVIEW_BOX = (320, 240)                # thumbnail box while the pane has no size yet
_GIF_SIGNATURES = (b"GIF87a", b"GIF89a")


@dataclass(frozen=True, slots=True)
class AssetInfo:
    """What the Asset tab shows for ``ref``: its facts, and ``data`` to decode for a
    thumbnail (None: facts only)."""

    ref: str
    size: int | None                    # bytes on disk
    kind: str | None                    # "png", "gif", "jpeg", "webp", or None
    width: int | None
    height: int | None
    image_name: str | None
    name_problem: bool                  # an image file whose name gives no image name
    data: bytes | None

    def facts(self) -> list[str]:
        lines: list[str] = []
        if self.width is not None and self.height is not None:
            lines.append(f"Size: {self.width} × {self.height} pixels")
        if self.size is not None:
            lines.append(f"File size: {self.size:,} bytes")
        else:
            lines.append("This file can't be read.")
        if self.image_name is not None:
            lines.append(f"Image name: {self.image_name}")
        elif self.name_problem:
            lines.append("This file gives no image name.")
        return lines


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if data[:6] not in _GIF_SIGNATURES or len(data) < 10:
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return (width, height) if width and height else None


def read_asset(paths: GamePaths, ref: str) -> AssetInfo:
    """Read ``ref`` for the Asset tab (04 §7.7): ``read_file(regular=True)`` under
    ``PREVIEW_MAX_BYTES`` (past it the size comes from ``os.stat`` and nothing more is
    read), the header's format and size, and the image name. ``data`` is set only for a PNG
    or GIF of at most ``PREVIEW_MAX_PIXELS``."""
    image_name: str | None = None
    name_problem = False
    file_name = ref.rsplit("/", 1)[-1]
    if ref.startswith("images/") and image_suffix(file_name) is not None:
        image_name, problem = name_of(ref)
        name_problem = problem is not None
    size: int | None = None
    data: bytes | None = None
    try:
        data = paths.read_file(ref, max_bytes=PREVIEW_MAX_BYTES, regular=True)
        size = len(data)
    except AssetTooLarge:
        try:
            size = os.stat(paths.resolve(ref)).st_size
        except (OSError, EngineError):
            size = None
    except (OSError, EngineError):
        pass
    kind = width = height = None
    if data is not None:
        found = image_dimensions(data)
        if found is not None:
            kind, width, height = found
        else:
            gif = _gif_dimensions(data)
            if gif is not None:
                kind, (width, height) = "gif", gif
    decodable = (data is not None and kind in PREVIEW_FORMATS and width is not None
                 and height is not None and width * height <= PREVIEW_MAX_PIXELS)
    return AssetInfo(ref, size, kind, width, height, image_name, name_problem,
                     data if decodable else None)


def autohide(bar: ttk.Scrollbar, **grid: object) -> Callable[[str, str], None]:
    """A scroll command that shows ``bar`` (gridded with ``grid``) only while there is
    something to scroll, as VS Code does."""

    def set_view(first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            bar.grid_remove()
        else:
            bar.grid(**grid)
        bar.set(first, last)

    return set_view


def thumbnail_step(width: int, height: int, box: tuple[int, int]) -> int:
    """The ``subsample`` factor: the smallest integer n ≥ 1 that fits the box (never
    upscales)."""
    box_w, box_h = max(1, box[0]), max(1, box[1])
    return max(1, math.ceil(width / box_w), math.ceil(height / box_h))


def node_text(node: TreeNode, dirty: bool) -> str:
    """A row's text: ``Images (4)``, ``hana``, ``* ch2.vns``, ``happy.png (hana happy)``."""
    if node.kind == "group":
        return f"{node.name} ({node.count})"
    text = (DIRTY_MARK if dirty else "") + node.name
    if node.image_name is not None:
        text += f" ({node.image_name})"
    return text


# A row's icon (08 §6, P2): groups and folders are folders, a file shows its group's kind.
TREE_ICON_PX = 16
GROUP_ICONS = {"script": "script", "images": "image", "gui": "image", "audio": "audio",
               "fonts": "font", "minigames": "code"}


def node_icon(node: TreeNode) -> str:
    """The ``icons`` name of a project row."""
    if node.kind in ("group", "folder"):
        return "folder"
    if node.kind == "config":
        return "config"
    return GROUP_ICONS.get(node.group, "file")


class ProjectView:
    """The project panel's tree (``04`` §7.4). ``on_select(ref)`` runs when the author
    selects a row; programmatic selection of the current row doesn't call it again. Each
    row shows its kind's muted icon (``node_icon``)."""

    def __init__(self, parent: tk.Misc, *, font: object, background: str,
                 on_select: Callable[[str], None], scale: float = 1.0) -> None:
        self.icons = {name: icons.photo(parent, name, round(TREE_ICON_PX * scale), MUTED,
                                        gap=round(6 * scale))
                      for name in {"folder", "config", "file", *GROUP_ICONS.values()}}
        self.frame = ttk.Frame(parent, style="Side.TFrame")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(self.frame, show="tree", selectmode="browse", height=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview,
                            style="Side.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=autohide(bar, row=0, column=1, sticky="ns"))
        self.tree.tag_configure("message", foreground=MUTED)
        self.on_select = on_select
        self.project: ProjectTree | None = None
        self.message: str | None = None
        self._nodes: dict[str, TreeNode] = {}
        self._quiet = False
        self._sized = False
        self.tree.bind("<<TreeviewSelect>>", self._selected, add="+")
        self.tree.bind("<Configure>", self._first_size, add="+")

    def _first_size(self, event: tk.Event) -> None:
        """A selection made before the tree had its height scrolled it to the top row; once
        it has a real height, show the list from the top with the selection in view."""
        if self._sized or event.height <= 1:
            return
        self._sized = True
        self.tree.yview_moveto(0)
        chosen = self.tree.selection()
        if chosen:
            self.tree.see(chosen[0])

    # --- Filling ----------------------------------------------------------------------------

    def fill(self, project: ProjectTree | Refusal, dirty: Callable[[str], bool]) -> None:
        """Show ``project`` (or one gray row with a refusal's text). Open folders and the
        selection are kept where their refs still exist; groups start open."""
        tree = self.tree
        first = self.project is None
        opened = {iid for iid in self._all_items() if tree.item(iid, "open")}
        selected = self.selected()
        self._quiet = True
        try:
            tree.delete(*tree.get_children(""))
            self._nodes = {}
            if isinstance(project, Refusal):
                self.project = None
                self.message = project.text
                tree.insert("", "end", iid=MESSAGE_ID, text=project.text, tags=("message",))
                return
            self.project = project
            self.message = None
            for top in (*project.groups, project.config):
                self._insert("", top, dirty)
            for iid in self._nodes:
                node = self._nodes[iid]
                if (node.kind == "group" and first) or iid in opened:
                    tree.item(iid, open=True)
            if selected is not None and tree.exists(selected):
                tree.selection_set(selected)
                tree.focus(selected)
        finally:
            self._release()

    def _insert(self, parent: str, top: TreeNode, dirty: Callable[[str], bool]) -> None:
        stack = [(parent, top)]
        while stack:
            under, node = stack.pop(0)
            self._nodes[node.ref] = node
            self.tree.insert(under, "end", iid=node.ref, image=self.icons[node_icon(node)],
                             text=node_text(node, node.is_file and dirty(node.ref)))
            stack[0:0] = [(node.ref, child) for child in node.children]

    def _all_items(self) -> list[str]:
        found: list[str] = []
        stack = list(self.tree.get_children(""))
        while stack:
            iid = stack.pop()
            found.append(iid)
            stack.extend(self.tree.get_children(iid))
        return found

    # --- Queries and updates ----------------------------------------------------------------

    def node(self, ref: str | None) -> TreeNode | None:
        return self._nodes.get(ref) if ref is not None else None

    def selected(self) -> str | None:
        chosen = self.tree.selection()
        if not chosen or chosen[0] == MESSAGE_ID:
            return None
        return chosen[0]

    def select(self, ref: str) -> None:
        """Select ``ref``'s row and scroll to it, without calling ``on_select``."""
        tree = self.tree
        if not tree.exists(ref):
            return
        if self.selected() != ref:
            self._quiet = True
            tree.selection_set(ref)
            self._release()
        tree.focus(ref)
        tree.see(ref)

    def set_dirty(self, ref: str, dirty: bool) -> None:
        node = self._nodes.get(ref)
        if node is not None:
            text = node_text(node, dirty)
            if self.tree.item(ref, "text") != text:
                self.tree.item(ref, text=text)

    def row_text(self, ref: str) -> str:
        return str(self.tree.item(ref, "text"))

    def _release(self) -> None:
        # <<TreeviewSelect>> arrives at idle time: stay quiet until it has passed.
        self.tree.after_idle(self._unquiet)

    def _unquiet(self) -> None:
        self._quiet = False

    def _selected(self, _event: tk.Event) -> None:
        if self._quiet:
            return
        ref = self.selected()
        if ref is not None:
            self.on_select(ref)


class AssetPane:
    """The Asset tab (PR-F45-20): the file's ref, a thumbnail for a PNG or GIF within the
    caps (fit to the pane, never upscaled), its facts, and **Copy name**."""

    def __init__(self, parent: tk.Misc, *, scale: float = 1.0,
                 on_add: Callable[[], None] | None = None, add_label: str = "Add files…") -> None:
        # A 1 px ring shows the keyboard focus (the frame itself takes it, for F6).
        gap = round(6 * scale)
        self.frame = ttk.Frame(parent, padding=round(12 * scale), takefocus=1,
                               style="Pane.TFrame")
        self.frame.bind("<FocusIn>", lambda _e: self.frame.configure(style="Focus.TFrame"),
                        add="+")
        self.frame.bind("<FocusOut>", lambda _e: self.frame.configure(style="Pane.TFrame"),
                        add="+")
        self.frame.columnconfigure(0, weight=1)
        self.title = ttk.Label(self.frame, text="", justify="left", style="Title.TLabel")
        self.title.grid(row=0, column=0, sticky="w")
        self.picture = ttk.Label(self.frame)
        self.picture.grid(row=1, column=0, sticky="w", pady=(gap, 0))
        self.facts = ttk.Label(self.frame, text="", justify="left")
        self.facts.grid(row=2, column=0, sticky="w", pady=(gap, 0))
        self.note = ttk.Label(self.frame, text="", foreground=MUTED, justify="left")
        self.note.grid(row=3, column=0, sticky="w", pady=(gap, 0))
        self.copy_button = ttk.Button(self.frame, text=COPY_NAME, command=self.copy_name,
                                      state="disabled", style="Secondary.TButton")
        self._button_pad = round(12 * scale)    # gridded by the first ``show``
        self.ref: str | None = None
        self.info: AssetInfo | None = None
        self.photo: tk.PhotoImage | None = None
        self.step: int | None = None     # the subsample factor of the thumbnail shown
        # Until a file is picked: the empty state (08 §9), inside the focus ring.
        self.empty = EmptyState(self.frame, icon="image", title=ASSET_EMPTY_TITLE,
                                hint=ASSET_EMPTY_HINT, button=add_label, command=on_add,
                                scale=scale)
        self.empty.show(self.frame, inset=1)

    def show(self, info: AssetInfo, *, box: tuple[int, int] | None = None) -> None:
        """Show ``info``; the thumbnail fits ``box`` (default: the pane's free space)."""
        self.empty.hide()
        self.copy_button.grid(row=4, column=0, sticky="w", pady=(self._button_pad, 0))
        self.ref = info.ref
        self.info = info
        self.title.configure(text=info.ref)
        self.facts.configure(text="\n".join(info.facts()))
        self.picture.configure(image="")
        self.photo = None
        self.step = None
        shown = False
        if info.data is not None and info.width is not None and info.height is not None:
            step = thumbnail_step(info.width, info.height, box or self._box())
            try:
                full = tk.PhotoImage(master=self.frame,
                                     data=base64.b64encode(info.data).decode("ascii"))
                self.photo = full if step == 1 else full.subsample(step)
                shown = True
                self.step = step
            except tk.TclError:          # a valid header over a body Tk can't decode
                self.photo = None
        if shown:
            self.picture.configure(image=self.photo)
        self.note.configure(text="" if shown else NO_PREVIEW)
        self.copy_button.configure(state="normal" if info.image_name else "disabled")

    def _box(self) -> tuple[int, int]:
        width, height = self.frame.winfo_width(), self.frame.winfo_height()
        if width <= 1 or height <= 1:
            return PREVIEW_BOX
        # Leave room for the ref, facts, note and button below the picture.
        return max(32, width - 24), max(32, height - 160)

    def copy_name(self) -> None:
        """Copy name: the image name onto the clipboard."""
        if self.info is not None and self.info.image_name:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(self.info.image_name)

    def text(self) -> str:
        return "\n".join(str(w.cget("text")) for w in (self.title, self.facts, self.note))


# --- Help pane (PR-F45-16) ----------------------------------------------------------------

HELP_HEADING = "Help"
HELP_CARDS = ("syntax", "example")      # the parts shown as code cards


PANEL_HEADER_PX = 28
PANEL_INSET_PX = 12


def panel_header(parent: tk.Misc, text: str, scale: float = 1.0) -> ttk.Frame:
    """A panel's header (``08`` §7): VS Code's small upper-case caption (``PROBLEMS``,
    ``HELP``) 28 px high and inset 12, on the panel's own tone, so there is no separate
    strip. More widgets may be packed on its right."""
    strip = ttk.Frame(parent, style="Header.TFrame", height=round(PANEL_HEADER_PX * scale))
    strip.pack_propagate(False)
    ttk.Label(strip, text=text.upper(), style="Header.TLabel").pack(
        side="left", padx=round(PANEL_INSET_PX * scale))
    return strip


class HelpPane:
    """The Help pane beside the problems panel: the doc of the statement on the cursor's
    line (title, syntax, summary, example, ``Docs: …``), or ``No help for this line.``"""

    def __init__(self, parent: tk.Misc, *, font: tkfont.Font, code_font: tkfont.Font,
                 title_font: tkfont.Font | None = None, background: str = "",
                 scale: float = 1.0) -> None:
        background = background or PANEL_BACKGROUND
        self.frame = ttk.Frame(parent, style="Side.TFrame")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        panel_header(self.frame, HELP_HEADING, scale).grid(row=0, column=0, columnspan=2,
                                                           sticky="ew")
        inset, pad = round(PANEL_INSET_PX * scale), round(4 * scale)
        self.text = tk.Text(
            self.frame, wrap="word", width=1, height=1, font=font, background=background,
            foreground=PLAIN_COLOR, selectbackground=SELECTION_BACKGROUND,
            inactiveselectbackground=THEME["editor.inactiveSelection"], padx=inset - 1,
            pady=pad, highlightthickness=1, highlightbackground=background,
            highlightcolor=FOCUS_BORDER, borderwidth=0, takefocus=1, cursor="arrow")
        bold = title_font or tkfont.Font(root=parent, **{**font.actual(), "weight": "bold"})
        self._bold = bold
        text = self.text
        text.tag_configure("title", font=bold, foreground=THEME["strongForeground"])
        text.tag_configure("docs", foreground=MUTED)
        text.tag_configure("none", foreground=MUTED)
        text.tag_configure("gap", spacing1=round(8 * scale))
        # Syntax and example sit in code cards (08 §7): a raised fill to the right edge, the
        # code inset 12 on the card's color, 4 above and below. Made after "gap", so their
        # own spacing wins.
        card, edge = THEME["card.background"], round(4 * scale)
        for part in HELP_CARDS:
            text.tag_configure(part, font=code_font, background=card, lmargin1=inset,
                               lmargin2=inset, lmargincolor=card, rmargin=inset,
                               rmargincolor=card, spacing1=edge, spacing3=edge)
        text.tag_configure("sel", foreground=PLAIN_COLOR)   # every color stays readable
        text.tag_raise("sel")
        text.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=text.yview,
                            style="Side.Vertical.TScrollbar")
        text.configure(yscrollcommand=autohide(bar, row=1, column=1, sticky="ns"),
                       state="disabled")
        text.bind("<Button-1>", lambda _e: text.focus_set(), add="+")
        self.doc: object = NO_HELP_DOC

    def show(self, doc: object) -> None:
        """Show ``doc`` (a ``StatementDoc``, a ``TagDoc``, or None); nothing is redrawn for
        the same doc."""
        if doc is self.doc:
            return
        self.doc = doc
        text = self.text
        text.configure(state="normal")
        text.delete("1.0", "end")
        previous = ""
        for index, (part, body) in enumerate(help_sections(doc)):  # type: ignore[arg-type]
            start = text.index("end-1c")
            text.insert("end", ("\n" if index else "") + body)
            if previous in HELP_CARDS:   # a card's newline: its fill reaches the right edge
                text.tag_add(previous, start)
            tags = (part,) if index == 0 else (part, "gap")
            for tag in tags:
                text.tag_add(tag, start if index == 0 else f"{start}+1c", "end-1c")
            previous = part
        if previous in HELP_CARDS:
            text.tag_add(previous, "end-1c")
        text.configure(state="disabled")
        text.yview_moveto(0)

    def content(self) -> str:
        return self.text.get("1.0", "end-1c")


# --- Completion list (PR-F45-13, UI-F45-04, design §6.1) ----------------------------------

COMPLETION_NAME_CHARS = 40              # widest name column, in characters


class CompletionPopup:
    """A borderless ``Toplevel`` with two side-by-side ``Listbox``es: the names, and their
    kind words in the muted color (``theme``). At most ``COMPLETION_VISIBLE`` rows show; the
    editor keeps the focus, and the window drives ``move``, ``chosen`` and ``close``.
    ``on_pick(index)`` runs when a row is clicked. The ``Toplevel`` is made on first use, so a window that
    never completes has no extra toplevel."""

    def __init__(self, parent: tk.Misc, *, font: tkfont.Font) -> None:
        self.parent = parent
        self.font = font
        self.window: tk.Toplevel | None = None
        self.rows: list[Candidate] = []
        self.index = 0
        self.ctx: Context | None = None
        self.widget: tk.Text | None = None
        self.line: int | None = None
        self.on_pick: Callable[[int], None] = lambda _i: None

    def _build(self) -> None:
        font = self.font
        self.window = tk.Toplevel(self.parent)
        self.window.withdraw()
        self.window.overrideredirect(True)
        frame = tk.Frame(self.window, background=THEME["widget.border"], borderwidth=0)
        frame.pack(fill="both", expand=True)
        common = dict(font=font, activestyle="none", exportselection=False, takefocus=0,
                      borderwidth=0, highlightthickness=0,
                      background=THEME["widget.background"],
                      selectbackground=CHOSEN_BACKGROUND, selectborderwidth=0,
                      selectforeground=CHOSEN_FOREGROUND)
        self.names = tk.Listbox(frame, foreground=PLAIN_COLOR, **common)
        self.kinds = tk.Listbox(frame, foreground=MUTED, **common)
        self.names.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
        self.kinds.grid(row=0, column=1, sticky="nsew", padx=(0, 1), pady=1)
        for box in (self.names, self.kinds):
            box.bind("<ButtonRelease-1>", self._clicked, add="+")
            box.bind("<MouseWheel>", self._wheel, add="+")

    @property
    def is_open(self) -> bool:
        return bool(self.rows)

    def open(self, widget: tk.Text, line: int, ctx: Context, rows: Sequence[Candidate],
             x: int, y: int) -> None:
        if self.window is None:
            self._build()
        assert self.window is not None
        self.widget, self.line = widget, line
        self.fill(ctx, rows)
        self.window.geometry(f"+{x}+{y}")
        self.window.deiconify()
        self.window.lift()

    def fill(self, ctx: Context, rows: Sequence[Candidate]) -> None:
        self.ctx = ctx
        self.rows = list(rows)
        for box in (self.names, self.kinds):
            box.delete(0, "end")
        self.names.insert("end", *(c.text for c in self.rows))
        self.kinds.insert("end", *(c.kind for c in self.rows))
        height = max(1, min(COMPLETION_VISIBLE, len(self.rows)))
        widest = max((len(c.text) for c in self.rows), default=1)
        kind_width = max((len(c.kind) for c in self.rows), default=1)
        self.names.configure(height=height, width=min(COMPLETION_NAME_CHARS, widest + 1))
        self.kinds.configure(height=height, width=kind_width + 1)
        self.select(0)

    def select(self, index: int) -> None:
        if not self.rows:
            return
        self.index = max(0, min(len(self.rows) - 1, index))
        for box in (self.names, self.kinds):
            box.selection_clear(0, "end")
            box.selection_set(self.index)
            box.see(self.index)

    def move(self, step: int) -> None:
        self.select(self.index + step)

    def chosen(self) -> Candidate | None:
        return self.rows[self.index] if self.rows else None

    def close(self) -> None:
        self.rows = []
        self.ctx = None
        self.widget = None
        self.line = None
        if self.window is not None:
            try:
                self.window.withdraw()
            except tk.TclError:
                pass

    def visible_rows(self) -> int:
        return int(self.names.cget("height"))

    def owns(self, widget: object) -> bool:
        return self.window is not None and widget in (self.window, self.names, self.kinds)

    def _clicked(self, event: tk.Event) -> None:
        if self.rows:
            self.on_pick(int(event.widget.nearest(event.y)))

    def _wheel(self, event: tk.Event) -> str:
        step = -1 if event.delta > 0 else 1
        for box in (self.names, self.kinds):
            box.yview_scroll(step, "units")
        return "break"


# --- Story map (PR-F45-18, PR-F45-19, design §6.2, 08 §8) ---------------------------------

MAP_MARGIN = 16
MAP_ZOOM_MIN = 50
MAP_ZOOM_MAX = 200
MAP_ZOOM_STEP = 25
MAP_NAME_PX = 13
MAP_DETAIL_PX = 11
MAP_PAD = 8                             # a box's text inset
BOX_FILL = THEME["map.box"]
BOX_OUTLINE = THEME["map.boxBorder"]
BOX_HOVER = THEME["map.boxHoverBorder"]
START_COLOR = THEME["map.start"]
START_BAR = 3                           # the start box's bar inside its left edge
RING_COLOR = THEME["map.ring"]
RING_GAP = 3
LINK_COLOR = THEME["map.link"]
ENDING_COLOR = THEME["map.ending"]
CHAPTER_COLOR = THEME["map.chapter"]
MINIGAME_COLOR = THEME["map.minigame"]
WARNING_COLOR = THEME["marker.warning"]  # F32: "deletes saves" under a box
CHIP_FILL = THEME["map.chip"]           # F46: a choice arrow's text chip (08 §8, 04 §4.1)
CHIP_BORDER = THEME["map.chipBorder"]
CHIP_TEXT = THEME["map.chipText"]
CHIP_IF = THEME["map.chipIf"]
CHIP_IF_TEXT = "if"                     # a conditional choice's mark, before its text
CHIP_RADIUS = 4
CHIP_PAD_X = 6
CHIP_PAD_Y = 1                          # 18 high: it fits the 20 px row gap
CHIP_FONT_PX = 12                       # ``small`` at 100 % zoom
DRAG_START_PX = 4                       # F46: a press moves this far before it drags a box
BIG_STEP = 5                            # F46: Shift+Alt+arrows move PLACE_STEP × this
# Ctrl, plus Alt (Windows 0x20000, X11 Mod1) or Cmd/Option (macOS Mod1/Mod2): a W A S D
# press with one of these held is a shortcut, not a map scroll. NumLock (Windows Mod1,
# X11 Mod2) is left out.
CHORD_STATE = 0x4 | {"win32": 0x20000, "darwin": 0x8 | 0x10}.get(sys.platform, 0x8)
TIDY_UP = "Tidy up"                     # F46 design §6.2 toolbar; one map step
MOVE_TITLE = "Move box"
NEW_SCENE_BUTTON = "+ New scene"        # F46 design §6.1 toolbar
SELECT_COLOR = THEME["map.selected"]    # F46: selected box / arrow, drop target, drag line
HANDLE_COLOR = THEME["map.handle"]
HANDLE_PX = 8                           # F46: the arrow handle on a hovered box's right edge
EDGE_HIT_PX = 4                         # F46: a click this near an arrow selects it
CHOICE_FIELD_PX = 220                   # F46: the inline choice-text field's least width
START_ONLY_TITLE = "Your story has one scene"                   # PR-F46-27, 08 §9 pattern
START_ONLY_HINT = ("Double-click empty space to add a scene. Drag from one scene to another "
                   "to connect them.")
START_ONLY_BUTTON = "New scene…"
ARROW_SHAPE = (8, 10, 4)
LEGEND_SAMPLE = 24                      # a legend sample's width; 16 between entries
LEGEND_GAP = 16
LEGEND_HEIGHT = 20
LEGEND_EXTRA = ("ending", "chapter", "minigame")      # after the link kinds (2026-11-02)
MAP_FILE_WIDTH = 200                    # the file filter's width (08 §8)
MAP_BANNER_PX = 28
MAP_BANNER_INSET = 12
EDGE_STYLES: dict[str, tuple[tuple[int, ...], str]] = {   # told apart by line style
    "jump": ((), LINK_COLOR),           # solid
    "call": ((6, 4), LINK_COLOR),       # dashed
    "menu": ((2, 4), LINK_COLOR),       # dotted
}
ALL_FILES = "All files"
MAP_EMPTY_TITLE = "No story map yet"                            # 08 §9
MAP_EMPTY_HINT = "It is drawn from the last check that loaded the script."
MAP_EMPTY = f"{MAP_EMPTY_TITLE}. {MAP_EMPTY_HINT}"
MAP_OUT_OF_DATE = "out of date: the last check didn't load the script"
TAG_BOX = "box"
TAG_EDGE = "edge"
TAG_RING = "ring"


_STEPS: dict[str, tuple[int, int]] = {"left": (-1, 0), "right": (1, 0), "up": (0, -1),
                                      "down": (0, 1)}


@dataclass(slots=True)
class _Drag:
    """A box being moved (F46): its index, its layout corner, where the press was (canvas
    px), whether Ctrl was held (the release opens a tab), the newest pointer, and whether it
    has moved past ``DRAG_START_PX``."""

    box: int
    origin: tuple[float, float]
    press: tuple[float, float]
    tab: bool
    pointer: tuple[float, float] | None = None
    moved: bool = False


HEAD_HIT_PX = 10                        # a selected arrow's head grabs within this (× dpi)


@dataclass(slots=True)
class _Link:
    """An arrow being drawn from box ``src``'s handle (F46 04 §6.8): the dashed line's
    item and the box under the pointer (outlined as the drop target)."""

    src: int
    line: int | None = None
    target: int | None = None
    away: bool = False                  # the pointer has left the source (a loop needs it)
    edge: int | None = None             # a selected arrow's head being dragged (retarget)


@dataclass(slots=True)
class _Field:
    """The inline choice-text field over edge ``edge``'s chip (F46 PR-F46-13)."""

    edge: int
    entry: ttk.Entry
    item: int


def round_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> list[float]:
    """A rounded rectangle's points for ``create_polygon(smooth=True)`` (08 §2 radii)."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


class StoryMapView:
    """The Story map tab: the file filter and a legend above a scrolling canvas of label
    boxes and link arrows, with the "hidden" and "out of date" note on its own wrapping line
    between them (never clipped). Arrows move the focus ring (``storymap.neighbour``), Tab
    selects the focused box's outgoing arrows (``out_edges``, F46 C2), and a click or Enter
    calls ``on_open(box)``; with Ctrl it calls ``on_open_tab(box)`` (2026-11-02). Zoom is
    50–200 %, on top of the screen's ``scale``. F46 step 5: the handle draws arrows, a
    click selects an arrow, F2 edits a choice's text, a double-click on empty space adds a
    scene, and the ``on_*`` callbacks (set by the window) carry them out."""

    def __init__(self, parent: tk.Misc, *, background: str, family: str, mod: str,
                 on_open: Callable[[Box], None],
                 on_open_tab: Callable[[Box], None] | None = None,
                 fonts: dict[str, tkfont.Font] | None = None, scale: float = 1.0,
                 on_check: Callable[[], None] | None = None,
                 on_step: Callable[[str, dict, dict], None] | None = None) -> None:
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        self.on_open = on_open
        self.on_open_tab = on_open_tab or on_open
        # F46 (04 §6.8): a move or Tidy up calls on_step(title, before, after) with the
        # places it changed (None: automatic); the window keeps the map history and file.
        self.on_step = on_step
        self.dpi = scale
        gap = round(4 * scale)
        # The toolbar (08 §8): 40 high around the 28 px combo box, inset 12 with the tab's 8.
        bar = self.bar = ttk.Frame(self.frame, padding=(gap, round(6 * scale)))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(1, weight=1)
        fonts = fonts or {}
        name_spec = fonts["bodyStrong"].actual() if "bodyStrong" in fonts else {"family": family}
        detail_spec = fonts["detail"].actual() if "detail" in fonts else {"family": family}
        self.name_font = tkfont.Font(root=parent, **{**name_spec, "size": -MAP_NAME_PX})
        self.detail_font = tkfont.Font(root=parent, **{**detail_spec, "size": -MAP_DETAIL_PX})
        self.legend_font = fonts.get("small") or tkfont.Font(
            root=parent, family=family, size=-round(12 * scale))
        self.chip_font = tkfont.Font(root=parent, **{**self.legend_font.actual(),
                                                     "size": -CHIP_FONT_PX})
        self.filter = ttk.Frame(bar)
        self.filter.grid(row=0, column=0, sticky="w")
        # F46 (design §6.1): New scene and the map actions are the window's (on_* below).
        self.on_new_scene: Callable[[tuple[int, int] | None], None] | None = None
        self.on_arrow: Callable[[int, int], None] | None = None
        self.on_edge: Callable[[int | None], None] | None = None
        self.on_choice_text: Callable[[int, str], None] | None = None
        self.on_delete: Callable[[], None] | None = None
        self.on_rename: Callable[[], None] | None = None
        self.on_retarget: Callable[[int, int], None] | None = None
        self.on_edit_choice: Callable[[], None] | None = None
        self.on_context: Callable[[str, object, int, int], None] | None = None
        self.new_button = ttk.Button(self.filter, text=NEW_SCENE_BUTTON, takefocus=0,
                                     style="Ghost.TButton",
                                     command=lambda: self._new_scene(None))
        self.new_button.pack(side="left", padx=(0, round(4 * scale)))
        self.tidy_button = ttk.Button(self.filter, text=TIDY_UP, takefocus=0,
                                      style="Ghost.TButton", command=self.tidy_up)
        self.tidy_button.pack(side="left", padx=(0, round(12 * scale)))
        ttk.Label(self.filter, text="File:").pack(side="left", padx=(0, round(8 * scale)))
        zero = max(1, tkfont.nametofont("TkDefaultFont", root=parent).measure("0"))
        self.file_choice = ttk.Combobox(self.filter, state="readonly",
                                        width=round(MAP_FILE_WIDTH * scale / zero),
                                        values=(ALL_FILES,))
        self.file_choice.set(ALL_FILES)
        self.file_choice.pack(side="left")
        self.file_choice.bind("<<ComboboxSelected>>", self._on_file, add="+")
        self.legend = tk.Canvas(bar, height=round(LEGEND_HEIGHT * scale), width=1,
                                background=background, highlightthickness=0, borderwidth=0,
                                takefocus=0)
        self._draw_legend()
        self._legend_row: int | None = None
        bar.bind("<Configure>", self._place_legend, add="+")
        self._place_legend()
        # The note ("hidden", "out of date") is a banner above the canvas while it isn't
        # empty (08 §8): a raised strip at least 28 high with the warning icon; it wraps to
        # the tab's width and never clips.
        card, inset = THEME["card.background"], round(MAP_BANNER_INSET * scale)
        self.banner = tk.Frame(self.frame, background=card, highlightthickness=0,
                               height=round(MAP_BANNER_PX * scale))
        family = icon_family(parent)
        self.banner_font = tkfont.Font(root=parent, family=family or self.legend_font.actual("family"),
                                       size=-round(14 * scale))
        self.banner_icon = tk.Label(self.banner, text=glyph("warning", family),
                                    font=self.banner_font, background=card,
                                    foreground=THEME["marker.warning"], borderwidth=0)
        self.banner_icon.pack(side="left", anchor="n", padx=(inset, round(8 * scale)),
                              pady=round(5 * scale))
        self.note = tk.Label(self.banner, text="", background=card,
                             foreground=THEME["foreground"], font=self.legend_font,
                             justify="left", anchor="w", borderwidth=0)
        self.note.pack(side="left", fill="x", expand=True, pady=round(5 * scale),
                       padx=(0, inset))
        icon_room = self.banner_font.measure(self.banner_icon.cget("text") or " ")
        self.frame.bind("<Configure>", lambda e: self.note.configure(
            wraplength=max(40, e.width - icon_room - 3 * inset)), add="+")

        self.canvas = tk.Canvas(self.frame, background=background, highlightthickness=1,
                                borderwidth=0, takefocus=1, highlightcolor=RING_COLOR,
                                highlightbackground=background)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        hbar = ttk.Scrollbar(self.frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=autohide(vbar, row=2, column=1, sticky="ns"),
                              xscrollcommand=self._xscrolled(
                                  autohide(hbar, row=3, column=0, sticky="ew")))

        # No boxes: the empty state over the canvas (08 §9).
        self.empty = EmptyState(self.frame, icon="storymap", title=MAP_EMPTY_TITLE,
                                hint=MAP_EMPTY_HINT, button=CHECK_NOW_BUTTON,
                                command=on_check, scale=scale)
        self.empty.show(self.canvas)
        # Only `start` on the map (PR-F46-27): the same pattern under the start box.
        self.start_only = EmptyState(self.frame, icon="storymap", title=START_ONLY_TITLE,
                                     hint=START_ONLY_HINT, button=START_ONLY_BUTTON,
                                     command=lambda: self._new_scene(None), scale=scale)

        self.labels: tuple[object, ...] = ()
        self.links: tuple[object, ...] = ()
        self.notes: dict[str, Notes] = {}
        self.stale = False
        self.out_of_date: frozenset[str] = frozenset()
        self.file: str | None = None
        self.layout: MapLayout | None = None
        self.zoom = 100
        self.focused: int | None = None
        self.anchor: int | None = None   # where a run of Tab presses started
        self.edge_items: list[tuple[int, str]] = []    # (canvas item, link kind)
        self.ports: dict[int, float] = {}   # edge index -> its port on the source (F46)
        self.ends: dict[int, float] = {}    # edge index -> its end height (same-pair arrows)
        self.ring: int | None = None
        self.hovered: int | None = None  # the box under the pointer
        # F46 places and moves (04 §6.8): the remembered corners (label → (x, y) at 100 %),
        # the message line in the banner, a box drag or Move box mode in progress, and the
        # boxes shown away from their layout place while it runs (box → corner).
        self.places: dict[str, tuple[int, int]] = {}
        self.message = ""
        self.drag: _Drag | None = None
        self.moving: _Drag | None = None        # Move box mode (G3)
        self._shifted: dict[int, tuple[float, float]] = {}
        self._incident: dict[int, list[int]] = {}   # box → its edges (drawn at draw time)
        self._drag_id: str | None = None
        # F46 arrows (04 §6.8): the selected box (the one opened), the selected arrow, an
        # arrow being drawn, the inline choice-text field, and the box Esc goes back to
        # after Enter on a Tab-selected arrow.
        self.selected: int | None = None
        self.edge: int | None = None
        self.link: _Link | None = None
        self.field: _Field | None = None
        self.back: int | None = None

        canvas = self.canvas
        # Arrows and W A S D scroll the map (Shift: further); Ctrl+arrows go from box to
        # box (the keyboard way to reach a box); in Move box mode the arrows move the box.
        for key, way in (("<Left>", "left"), ("<Right>", "right"), ("<Up>", "up"),
                         ("<Down>", "down")):
            canvas.bind(key, lambda _e, w=way: self._arrow(w))
            canvas.bind(f"<Shift-{key[1:]}", lambda _e, w=way: self._arrow(w, big=True))
            canvas.bind(f"<{mod}-{key[1:]}", lambda _e, w=way: self._hop(w))
            # Alt+arrows move the box; no "break", so the menu bar sees Alt wasn't alone.
            canvas.bind(f"<Alt-{key[1:]}", lambda _e, w=way: self.nudge(w))
            canvas.bind(f"<Shift-Alt-{key[1:]}", lambda _e, w=way: self.nudge(w, big=True))
        for letter, way in (("w", "up"), ("a", "left"), ("s", "down"), ("d", "right")):
            canvas.bind(f"<Key-{letter}>", lambda e, w=way: self._pan_key(e, w))
            canvas.bind(f"<Key-{letter.upper()}>", lambda e, w=way: self._pan_key(e, w, True))
        canvas.bind("<Tab>", self._tab)
        for key in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            try:
                canvas.bind(key, lambda _e: self._tab(step=-1))
            except tk.TclError:
                pass                        # a keysym this Tk doesn't know
        canvas.bind("<F2>", lambda _e: self._f2())
        canvas.bind("<Delete>", lambda _e: self._delete())
        if mod == "Command":                # 07 I-7: Mac keyboards' Delete is BackSpace
            canvas.bind("<BackSpace>", lambda _e: self._delete())
        canvas.bind("<Double-Button-1>", self._double)
        canvas.bind("<Button-3>", self._context_click)
        if mod == "Command":
            canvas.bind("<Button-2>", self._context_click)
        for key in ("<Shift-F10>", "<App>", "<Menu>"):
            try:
                canvas.bind(key, lambda _e: self._context_key())
            except tk.TclError:
                pass
        for key in ("<Return>", "<KP_Enter>"):
            canvas.bind(key, lambda _e: self._open_focused())
            canvas.bind(f"<{mod}-{key[1:]}", lambda _e: self._open_focused(tab=True))
        canvas.bind("<FocusOut>", lambda _e: (self.cancel_move(), self.cancel_link()),
                    add="+")
        canvas.bind("<Button-1>", self._click)
        canvas.bind(f"<{mod}-Button-1>", lambda e: self._click(e, tab=True))
        canvas.bind("<B1-Motion>", self._drag_motion)
        canvas.bind("<ButtonRelease-1>", self._release)
        canvas.bind("<MouseWheel>", self._wheel)
        canvas.bind("<Shift-MouseWheel>", self._wheel_x)
        canvas.bind(f"<{mod}-MouseWheel>", self._wheel_zoom)
        canvas.bind("<FocusIn>", lambda _e: self._ensure_focus(), add="+")
        canvas.bind("<Motion>", self._motion, add="+")
        canvas.bind("<Leave>", lambda _e: self._hover(None), add="+")

    # --- Data -------------------------------------------------------------------------------

    def set_data(self, labels: Iterable[object], links: Iterable[object] | None,
                 stale: bool, notes: dict[str, Notes] | None = None,
                 out_of_date: Iterable[str] = ()) -> None:
        """New labels and links (the last good check's, with the open files' scenes
        swapped in, F46) and each label's ``Notes``; ``out_of_date`` names the scenes whose
        text doesn't parse now (they keep their last links and read "out of date"). Keeps
        the file filter while its file still holds labels, and the focus on the same label
        name."""
        self.labels = tuple(labels)
        self.links = tuple(links or ())
        self.notes = dict(notes or {})
        self.stale = stale
        self.out_of_date = frozenset(out_of_date)
        choices = label_files(self.labels)
        if self.file is not None and self.file not in choices:
            self.file = None
        self.file_choice.configure(values=(ALL_FILES, *choices))
        self.file_choice.set(self.file or ALL_FILES)
        self._relayout()

    def _on_file(self, _event: tk.Event | None = None) -> None:
        choice = self.file_choice.get()
        self.set_file(None if choice == ALL_FILES else choice)

    def set_file(self, file: str | None) -> None:
        """Show one file's labels (None: all)."""
        self.file = file
        self.file_choice.set(file or ALL_FILES)
        self._relayout()

    def _relayout(self) -> None:
        name = self.focused_name()
        chosen = self.selected_name()
        self.layout = layout(self.links, self.labels, file=self.file, notes=self.notes,
                             stale=self.out_of_date, places=self.places)
        self.anchor = None
        self.focused = None
        self.edge = self.back = None
        self.selected = None if chosen is None else self.layout.index_of(chosen)
        if name is not None:
            self.focused = self.layout.index_of(name)
        if self.focused is None:
            self.focused = self._first_box()
        self._show_note()
        self.draw()

    def _show_note(self) -> None:
        assert self.layout is not None
        parts = [hidden_text(self.layout)]
        if self.stale:
            parts.append(MAP_OUT_OF_DATE)
        parts.append(self.message)
        note = " · ".join(p for p in parts if p)
        self.note.configure(text=note)
        if note:
            self.banner.grid(row=1, column=0, columnspan=2, sticky="ew",
                             pady=(0, round(8 * self.dpi)))
        else:
            self.banner.grid_remove()

    def say(self, text: str) -> None:
        """The map's message line (F46: the layout file, Undo blocked), in the banner;
        ``""`` clears it."""
        self.message = text
        if self.layout is not None:
            self._show_note()

    def _first_box(self) -> int | None:
        if self.layout is None or not self.layout.boxes:
            return None
        found = self.layout.index_of("start")
        return 0 if found is None else found

    def focused_name(self) -> str | None:
        if self.layout is None or self.focused is None:
            return None
        return self.layout.boxes[self.focused].name

    def selected_name(self) -> str | None:
        if self.layout is None or self.selected is None \
                or self.selected >= len(self.layout.boxes):
            return None
        return self.layout.boxes[self.selected].name

    # --- Drawing ----------------------------------------------------------------------------

    def _draw_legend(self) -> None:
        """Each link kind's line, then the ending, chapter and minigame samples, each with
        its word; measured, 16 px apart (``08`` §8). Each sample and its word is one entry
        (tag ``legend-entry<n>``), so a narrow toolbar wraps whole entries (``_wrap_legend``)
        and never clips a word."""
        legend, font, k = self.legend, self.legend_font, self.dpi
        middle = round(LEGEND_HEIGHT * k / 2)
        sample, word_gap = round(LEGEND_SAMPLE * k), round(6 * k)
        x = 0
        entries: list[tuple[str, int, int]] = []        # (tag, left, right) on one line
        made = [0]                                      # the last item id of an entry

        def word(text: str, at: float) -> float:
            item = legend.create_text(at, middle, anchor="w", text=text, fill=PLAIN_COLOR,
                                      font=font, tags=("legend", "legend-word"))
            tag = f"legend-entry{len(entries)}"
            for made_item in legend.find_all():
                if made_item > made[0]:
                    legend.addtag_withtag(tag, made_item)
            left, right = legend.bbox(tag)[0], legend.bbox(item)[2]
            entries.append((tag, max(0, left), right))
            made[0] = max(legend.find_all())
            return right + round(LEGEND_GAP * k)

        arrow = tuple(round(n * k) for n in ARROW_SHAPE)
        for kind in LINK_KINDS:
            dash, color = EDGE_STYLES[kind]
            options: dict = {"fill": color, "arrow": "last", "width": max(1, round(k)),
                             "arrowshape": arrow}
            if dash:
                options["dash"] = dash
            legend.create_line(x, middle, x + sample, middle,
                               tags=("legend", f"legend-{kind}"), **options)
            x = word(kind, x + sample + word_gap)
        half = round(7 * k)
        legend.create_rectangle(x, middle - half, x + sample, middle + half,
                                outline=ENDING_COLOR, fill=BOX_FILL,
                                tags=("legend", "legend-ending"))
        inset = round(3 * k)
        legend.create_rectangle(x + inset, middle - half + inset, x + sample - inset,
                                middle + half - inset, outline=ENDING_COLOR, tags=("legend",))
        x = word("ending", x + sample + word_gap)
        item = legend.create_text(x, middle, anchor="w", text="Aa", fill=CHAPTER_COLOR,
                                  font=font, tags=("legend", "legend-chapter"))
        x = word("chapter", legend.bbox(item)[2] + word_gap)
        chip = round(5 * k)
        legend.create_rectangle(x, middle - chip, x + round(18 * k), middle + chip,
                                outline=MINIGAME_COLOR, tags=("legend", "legend-minigame"))
        x = word("minigame", x + round(18 * k) + word_gap)
        self._legend_entries = entries
        self._legend_full = x - round(LEGEND_GAP * k) + 1
        self._legend_moved: dict[str, tuple[float, float]] = {}
        self._legend_limit: int | None = -1
        self._wrap_legend(None)

    def _wrap_legend(self, limit: int | None) -> None:
        """Lay the legend's entries out in rows at most ``limit`` wide (None: one row),
        moving whole entries; the canvas takes the rows' size."""
        if limit == self._legend_limit:
            return
        self._legend_limit = limit
        legend, k = self.legend, self.dpi
        gap, height = round(LEGEND_GAP * k), round(LEGEND_HEIGHT * k)
        x, row, widest = 0, 0, 0
        for tag, left, right in self._legend_entries:
            size = right - left
            if limit is not None and x > 0 and x + size > limit:
                x, row = 0, row + 1
            want = (x - left, row * height)
            have = self._legend_moved.get(tag, (0, 0))
            legend.move(tag, want[0] - have[0], want[1] - have[1])
            self._legend_moved[tag] = want
            widest = max(widest, x + size)
            x += size + gap
        legend.configure(width=widest + 1, height=(row + 1) * height)

    def _place_legend(self, _event: tk.Event | None = None) -> None:
        """The legend right of the file filter while both fit, else on a line below it,
        wrapped into rows when even that line is too narrow (no word is ever cut)."""
        bar = self.bar
        width = bar.winfo_width()
        inset = round(4 * self.dpi)                     # the bar's padding, each side
        need = self.filter.winfo_reqwidth() + round(LEGEND_GAP * self.dpi) + self._legend_full
        row = 0 if width <= 1 or width >= need else 1
        self._wrap_legend(None if row == 0 else max(1, width - 2 * inset))
        if row == self._legend_row:
            return
        self._legend_row = row
        if row == 0:
            self.legend.grid(row=0, column=1, sticky="e")
        else:
            self.legend.grid(row=1, column=0, columnspan=2, sticky="w",
                             pady=(round(4 * self.dpi), 0))

    def legend_rows(self) -> list[list[str]]:
        """The legend's words, row by row as laid out."""
        found: dict[int, list[tuple[float, str]]] = {}
        legend = self.legend
        for item in legend.find_withtag("legend-word"):
            x, y = legend.coords(item)
            found.setdefault(round(y), []).append((x, str(legend.itemcget(item, "text"))))
        return [[text for _x, text in sorted(row)] for _y, row in sorted(found.items())]

    def legend_words(self) -> list[str]:
        return [str(self.legend.itemcget(i, "text"))
                for i in self.legend.find_withtag("legend-word")]

    def _scale(self) -> float:
        return self.zoom / 100 * self.dpi

    def box_rect(self, index: int) -> tuple[float, float, float, float]:
        """Box ``index``'s rectangle on the canvas at the current zoom."""
        assert self.layout is not None
        box = self.layout.boxes[index]
        x, y = self._shifted.get(index, (box.x, box.y))     # F46: a box being moved
        s = self._scale()
        x0, y0 = MAP_MARGIN * self.dpi + x * s, MAP_MARGIN * self.dpi + y * s
        return x0, y0, x0 + BOX_WIDTH * s, y0 + BOX_HEIGHT * s

    def draw(self) -> None:
        canvas = self.canvas
        self._drop_field()
        canvas.delete("all")
        self._shifted = {}
        self.drag = self.moving = self.link = None
        self.edge_items = []
        self.ring = None
        self.hovered = None
        found = self.layout
        if found is not None and self.edge is not None and self.edge >= len(found.edges):
            self.edge = None
        self._sync_escape()
        s = self._scale()
        line = max(1, round(self.dpi))
        self.name_font.configure(size=-max(6, round(MAP_NAME_PX * s)))
        self.detail_font.configure(size=-max(5, round(MAP_DETAIL_PX * s)))
        margin = MAP_MARGIN * self.dpi
        if found is None or not found.boxes:
            self.start_only.hide()
            self.empty.show(canvas)
            canvas.configure(scrollregion=(0, 0, 1, 1))
            return
        self.empty.hide()
        if len(found.boxes) == 1 and not found.edges and found.hidden == 0 \
                and self.file is None:
            # PR-F46-27: under the start box, the canvas still usable around it.
            self.start_only.frame.place(in_=canvas, relx=0, rely=0, relwidth=1, relheight=1,
                                        y=round((MAP_MARGIN + BOX_HEIGHT + 24) * s),
                                        height=-round((MAP_MARGIN + BOX_HEIGHT + 24) * s))
            self.start_only.shown = True
        else:
            self.start_only.hide()
        self.ports = {}                  # F46 (04 §6.8): out edges fan out by target y
        for box in range(len(found.boxes)):
            order = out_edges(found, box)
            for k, index in enumerate(order):
                self.ports[index] = (k + 1) / (len(order) + 1)
        self._incident = {}
        # Several arrows between the same two boxes enter (and, same column, leave) at
        # their own heights, so they never lie on top of each other (step 5).
        pairs: dict[tuple[int, int], list[int]] = {}
        for index, edge in enumerate(found.edges):
            if edge.src != edge.dst:
                pairs.setdefault((edge.src, edge.dst), []).append(index)
        self.ends = {i: (k + 1) / (len(group) + 1) for group in pairs.values()
                     if len(group) > 1 for k, i in enumerate(group)}
        for index, edge in enumerate(found.edges):
            item = self.draw_edge(edge.src, edge.dst, edge.kind, self.ports.get(index, 0.5),
                                  end=self.ends.get(index))
            canvas.addtag_withtag(f"edge{index}", item)
            self.edge_items.append((item, edge.kind))
            self._incident.setdefault(edge.src, []).append(index)
            if edge.dst != edge.src:
                self._incident.setdefault(edge.dst, []).append(index)
        pad = MAP_PAD * s
        for index, box in enumerate(found.boxes):
            x0, y0, x1, y1 = self.box_rect(index)
            tags = (TAG_BOX, f"box{index}")
            start = MARK_START in box.marks
            ending = MARK_ENDING in box.marks
            color, width = self._outline(index)
            canvas.create_rectangle(x0, y0, x1, y1, outline=color, fill=BOX_FILL, width=width,
                                    tags=(*tags, f"rect{index}"))
            if ending:                   # an end box: a second border inside the first
                inset = 3 * s
                canvas.create_rectangle(x0 + inset, y0 + inset, x1 - inset, y1 - inset,
                                        outline=ENDING_COLOR, width=line,
                                        tags=(*tags, f"inner{index}"))
            if start:                    # the start box: an accent bar inside its left edge
                canvas.create_rectangle(x0 + line, y0 + line,
                                        x0 + line + max(2, round(START_BAR * s)), y1,
                                        fill=START_COLOR, outline="",
                                        tags=(*tags, f"startbar{index}"))
            tag_x = x0
            box_marks = tuple(m for m in box.marks if m != MARK_DELETES_SAVES)
            if MARK_DELETES_SAVES in box.marks:     # F32: a warning tag under the box
                item = canvas.create_text(tag_x + 4 * s, y1 + 3 * s, anchor="nw",
                                          text=f"⚠ {MARK_DELETES_SAVES}",
                                          font=self.detail_font, fill=WARNING_COLOR,
                                          tags=(*tags, f"wipe{index}"))
                bx0, by0, bx1, by1 = canvas.bbox(item)
                canvas.create_rectangle(bx0 - 3 * s, by0 - 1, bx1 + 3 * s, by1 + 1,
                                        outline=WARNING_COLOR, tags=(*tags,))
                tag_x = bx1 + 6 * s
            for game in box.minigames[:2]:   # small tags under the box (in the row gap)
                item = canvas.create_text(tag_x + 4 * s, y1 + 3 * s, anchor="nw",
                                          text=f"▶ {game}", font=self.detail_font,
                                          fill=MINIGAME_COLOR,
                                          tags=(*tags, f"minigame{index}"))
                bx0, by0, bx1, by1 = canvas.bbox(item)
                canvas.create_rectangle(bx0 - 3 * s, by0 - 1, bx1 + 3 * s, by1 + 1,
                                        outline=MINIGAME_COLOR, tags=(*tags,))
                tag_x = bx1 + 6 * s
            canvas.create_text(x0 + pad, y0 + 4 * s, anchor="nw", text=box.name,
                               font=self.name_font, fill=PLAIN_COLOR,
                               tags=(*tags, f"name{index}"))
            if box.scene is not None:   # F20: the scene title after the name, elided
                left = x0 + 2 * pad + self.name_font.measure(box.name)
                marks = self.detail_font.measure(", ".join(box_marks)) + pad if box_marks else 0
                shown = elide(f"“{box.scene}”", int(x1 - pad - marks - left),
                              self.detail_font.measure)
                if shown:
                    canvas.create_text(left, y0 + 4 * s, anchor="nw", text=shown,
                                       font=self.detail_font, fill=MUTED,
                                       tags=(*tags, f"scene{index}"))
            where = f"{box.file}:{box.line}" if box.file is not None else ""
            if box.chapter is not None:  # bottom right; the place gives way (elided)
                canvas.create_text(x1 - pad, y1 - 4 * s, anchor="se", text=box.chapter,
                                   font=self.detail_font, fill=CHAPTER_COLOR,
                                   tags=(*tags, f"chapter{index}"))
                room = int(x1 - x0 - 3 * pad - self.detail_font.measure(box.chapter))
                where = elide(where, room, self.detail_font.measure)
            canvas.create_text(x0 + pad, y1 - 4 * s, anchor="sw", text=where,
                               font=self.detail_font, fill=MUTED, tags=(*tags, f"where{index}"))
            # The marks give way to the name (step 5: long scene names), cut with "…".
            room = int(x1 - x0 - 3 * pad - self.name_font.measure(box.name))
            marks = elide(", ".join(box_marks), room, self.detail_font.measure) \
                if box_marks and box.scene is None else ", ".join(box_marks)
            if marks:
                canvas.create_text(x1 - pad, y0 + 4 * s, anchor="ne", text=marks,
                                   font=self.detail_font, fill=MUTED,
                                   tags=(*tags, f"marks{index}"))
        self.chip_font.configure(size=-max(6, round(CHIP_FONT_PX * s)))
        for index, edge in enumerate(found.edges):     # chips last, over boxes and arrows
            if edge.choice:
                self.draw_chip(index)
        width = 2 * margin + found.width * s
        height = 2 * margin + found.height * s
        chips = canvas.bbox("chip")         # a chip may sit past the boxes
        if chips:
            width, height = max(width, chips[2] + margin), max(height, chips[3] + margin)
        canvas.configure(scrollregion=(0, 0, width, height))
        if self.edge is not None:
            self._paint_edge(self.edge, True)
        self._draw_ring()
        self._stuck = set()
        self.stick_names()

    def _outline(self, index: int) -> tuple[str, int]:
        """Box ``index``'s border: 2 px accent while selected or a drop target (F46), the
        hover colour under the pointer, an ending's own colour, else the plain border."""
        assert self.layout is not None
        line = max(1, round(self.dpi))
        if index == self.selected or (self.link is not None and index == self.link.target):
            return SELECT_COLOR, max(2, round(2 * self.dpi))
        if MARK_ENDING in self.layout.boxes[index].marks:
            return ENDING_COLOR, line
        return (BOX_HOVER if index == self.hovered else BOX_OUTLINE), line

    def _paint_box(self, index: int | None) -> None:
        if index is None or self.layout is None or index >= len(self.layout.boxes):
            return
        color, width = self._outline(index)
        self.canvas.itemconfigure(f"rect{index}", outline=color, width=width)

    def select_box(self, index: int | None) -> None:
        """The box shown in the side pane (F46): a 2 px accent border."""
        old, self.selected = self.selected, index
        self._paint_box(old)
        self._paint_box(index)

    def _paint_edge(self, index: int, chosen: bool) -> None:
        """Edge ``index`` drawn selected (2 px accent, raised over the others) or plain."""
        if not 0 <= index < len(self.edge_items):
            return
        item, kind = self.edge_items[index]
        if chosen:
            self.canvas.itemconfigure(item, fill=SELECT_COLOR,
                                      width=max(2, round(2 * self.dpi)))
            self.canvas.tag_raise(item)
            self.canvas.tag_raise("chip")
        else:
            self.canvas.itemconfigure(item, fill=EDGE_STYLES.get(kind, ((), LINK_COLOR))[1],
                                      width=max(1, round(self.dpi)))

    def select_edge(self, index: int | None, *, notify: bool = True) -> None:
        """Select arrow ``index`` (None: no arrow); the window shows its choice text."""
        if self.edge is not None and self.edge != index:
            self._paint_edge(self.edge, False)
        self.edge = index
        if index is not None:
            self._paint_edge(index, True)
        self._sync_escape()
        if notify and self.on_edge is not None:
            self.on_edge(index)

    def selected_edge(self) -> tuple[str, str, str, str | None] | None:
        """The selected arrow as (source, target, kind, choice text), or None."""
        if self.layout is None or self.edge is None or self.edge >= len(self.layout.edges):
            return None
        edge = self.layout.edges[self.edge]
        boxes = self.layout.boxes
        return boxes[edge.src].name, boxes[edge.dst].name, edge.kind, edge.choice

    def edge_index(self, src: str, dst: str, kind: str | None = None) -> int | None:
        """The first edge ``src → dst`` (of ``kind``), or None."""
        if self.layout is None:
            return None
        for i, edge in enumerate(self.layout.edges):
            boxes = self.layout.boxes
            if boxes[edge.src].name == src and boxes[edge.dst].name == dst \
                    and (kind is None or edge.kind == kind):
                return i
        return None

    def draw_edge(self, src: int, dst: int, kind: str, port: float = 0.5,
                  end: float | None = None) -> int:
        """The one place a link arrow is drawn (08 §8): a smooth curve from box ``src`` to
        box ``dst`` in ``kind``'s line style; returns its canvas item. F46 draws an edge's
        choice text along ``edge_points(src, dst, port)`` (``draw_chip``)."""
        s = self._scale()
        dash, color = EDGE_STYLES.get(kind, ((), LINK_COLOR))
        options: dict = {"fill": color, "arrow": "last", "width": max(1, round(self.dpi)),
                         "arrowshape": tuple(max(1, round(n * s)) for n in ARROW_SHAPE),
                         "smooth": True}
        if dash:
            options["dash"] = dash
        return self.canvas.create_line(*self.edge_points(src, dst, port, end),
                                       tags=(TAG_EDGE, f"edge-{kind}"), **options)

    def edge_points(self, src: int, dst: int, port: float = 0.5,
                    end: float | None = None) -> list[float]:
        """An arrow's control points (``storymap.curve_points``, which also slots the
        chips): it leaves and enters its boxes horizontally (drawn with ``smooth``, so the
        line is a curve through the first and last points). A forward or backward arrow
        leaves at ``port`` of the source's height (F46: the k-th of n out edges at
        (k+1)/(n+1)), so parallel arrows stay apart."""
        return curve_points(self.box_rect(src), self.box_rect(dst), port,
                            bend=20 * self._scale(), loop=src == dst, end=end)

    def draw_chip(self, index: int, *, reslot: bool = False) -> tuple[int, ...]:
        """Edge ``index``'s choice chip (F46, 08 §8): ``chip_text`` in ``small`` muted on a
        ``raised`` rounded box (radius 4), led by an ``if`` mark when the choice has a
        condition, centred at its ``slot`` along the drawn curve (the measured chip takes
        the next of ``CHIP_SLOTS`` when that covers a box or an earlier chip; ``reslot``,
        while a box is dragged: the first free of them). Tags: ``chip``, ``chip<i>``,
        ``chiptext<i>`` and ``chipif<i>``."""
        assert self.layout is not None
        edge = self.layout.edges[index]
        canvas, font, s = self.canvas, self.chip_font, self._scale()
        text = chip_text(edge.choice)
        pad_x, pad_y, gap = CHIP_PAD_X * s, CHIP_PAD_Y * s, 4 * s
        mark = font.measure(CHIP_IF_TEXT) + gap if edge.conditional else 0
        w = 2 * pad_x + mark + font.measure(text)
        h = font.metrics("linespace") + 2 * pad_y
        points = self.edge_points(edge.src, edge.dst, self.ports.get(index, 0.5),
                                  self.ends.get(index))
        for t in (CHIP_SLOTS if reslot else (edge.slot, *CHIP_SLOTS)):
            cx, cy = self.curve_at(points, t)
            if not self._chip_blocked(cx, cy, w, h):
                break
        else:
            cx, cy = self.curve_at(points, 0.5 if reslot else edge.slot)
        if self._chip_blocked(cx, cy, w, h):    # too wide for the gap: the row gap below
            a, b = self.box_rect(edge.src), self.box_rect(edge.dst)   # or above the boxes
            gap = (ROW_STEP - BOX_HEIGHT) * s / 2
            for y in (max(a[3], b[3]) + gap, min(a[1], b[1]) - gap):
                if y - h / 2 >= 0 and not self._chip_blocked(cx, y, w, h):
                    cy = y
                    break
        x0, y0 = cx - w / 2, cy - h / 2
        tags = ("chip", f"chip{index}")
        items = [canvas.create_polygon(*round_rect(x0, y0, x0 + w, y0 + h, CHIP_RADIUS * s),
                                       smooth=True, fill=CHIP_FILL, outline=CHIP_BORDER,
                                       width=max(1, round(self.dpi)),
                                       tags=(*tags, f"chipbox{index}"))]
        if edge.conditional:
            items.append(canvas.create_text(x0 + pad_x, cy, anchor="w", text=CHIP_IF_TEXT,
                                            font=font, fill=CHIP_IF,
                                            tags=(*tags, f"chipif{index}")))
        items.append(canvas.create_text(x0 + pad_x + mark, cy, anchor="w", text=text,
                                        font=font, fill=CHIP_TEXT,
                                        tags=(*tags, f"chiptext{index}")))
        return tuple(items)

    def _chip_blocked(self, cx: float, cy: float, w: float, h: float) -> bool:
        """Whether a chip of ``w``×``h`` centred at (``cx``, ``cy``) would cover a box
        (its text or tags) or an earlier chip."""
        canvas = self.canvas
        for item in canvas.find_overlapping(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2):
            tags = canvas.gettags(item)
            if TAG_BOX in tags or "chip" in tags:
                return True
        return False

    @staticmethod
    def curve_at(points: Sequence[float], t: float) -> tuple[float, float]:
        """``storymap.curve_at``: the point a fraction ``t`` of the way along the curve Tk
        draws through ``points`` with ``smooth``, by length. On a forward or backward
        arrow's S, ``t`` = 0.5 is ``curve_middle``."""
        return curve_at(points, t)

    @staticmethod
    def curve_middle(points: Sequence[float]) -> tuple[float, float]:
        """The middle of an arrow from ``edge_points``: halfway between its two middle
        control points (where F46 puts a choice's chip)."""
        pairs = len(points) // 2
        left, right = (pairs - 1) // 2, pairs // 2
        return ((points[2 * left] + points[2 * right]) / 2,
                (points[2 * left + 1] + points[2 * right + 1]) / 2)

    def _draw_ring(self) -> None:
        canvas = self.canvas
        if self.ring is not None:
            canvas.delete(self.ring)
            self.ring = None
        if self.layout is None or self.focused is None:
            return
        x0, y0, x1, y1 = self.box_rect(self.focused)
        gap = RING_GAP * self.dpi
        self.ring = canvas.create_rectangle(x0 - gap, y0 - gap, x1 + gap, y1 + gap,
                                            outline=RING_COLOR, width=round(2 * self.dpi),
                                            tags=(TAG_RING,))

    def _xscrolled(self, setter: Callable[[str, str], None]) -> Callable[[str, str], None]:
        def scrolled(first: str, last: str) -> None:
            setter(first, last)
            self.stick_names()
        return scrolled

    def stick_names(self) -> None:
        """A box cut by the map's left edge (scrolled, e.g. after the side pane opened)
        keeps its name and place readable: they move into its visible part, and its marks
        hide while there is no room for both (F46 step 5)."""
        if self.layout is None:
            return
        canvas, s = self.canvas, self._scale()
        left, pad = canvas.canvasx(0), MAP_PAD * s
        cut = {i for i in range(len(self.layout.boxes))
               if (r := self.box_rect(i))[0] < left < r[2] - pad}
        stuck = getattr(self, "_stuck", set())
        for index in cut | {i for i in stuck if i < len(self.layout.boxes)}:
            x0, _y0, x1, _y1 = self.box_rect(index)
            shift = max(0.0, min(left - x0, x1 - x0 - 2 * pad))
            for tag in (f"name{index}", f"where{index}"):
                at = canvas.coords(tag)
                if at and abs(at[0] - (x0 + pad + shift)) > 0.5:
                    canvas.coords(tag, x0 + pad + shift, at[1])
            marks = canvas.find_withtag(f"marks{index}")
            if marks:
                name = canvas.bbox(f"name{index}")
                crowded = shift > 0 and name is not None and \
                    name[2] + pad > x1 - pad - self.detail_font.measure(
                        str(canvas.itemcget(marks[0], "text")))
                canvas.itemconfigure(marks[0], state="hidden" if crowded else "normal")
        self._stuck = cut

    def _motion(self, event: tk.Event) -> None:
        found = self.box_at(event.x, event.y)
        self._hover(found)
        if found is not None:               # F46: the handle draws an arrow
            on = self.on_handle(found, self.canvas.canvasx(event.x))
            self.canvas.configure(cursor="crosshair" if on else "hand2")

    def _hover(self, index: int | None) -> None:
        """The box under the pointer gets a lighter border (an ending keeps its own; a
        selected box its accent) and, F46, the arrow handle on its right edge."""
        if index == self.hovered:
            return
        old, self.hovered = self.hovered, index
        self._paint_box(old)
        self._paint_box(index)
        self.canvas.delete("handle")
        if index is not None and self.layout is not None and index < len(self.layout.boxes):
            x0, y0, x1, y1 = self.box_rect(index)
            line = max(1, round(self.dpi))
            self.canvas.create_rectangle(x1 - self.handle_px(), y0 + line, x1 - line,
                                         y1 - line, fill=HANDLE_COLOR, outline="",
                                         tags=("handle", f"box{index}"))
        self.canvas.configure(cursor="hand2" if index is not None else "")

    def handle_px(self) -> int:
        """The arrow handle's width: 8 px times the screen scale (12 at 150 %)."""
        return round(HANDLE_PX * self.dpi)

    def on_handle(self, index: int, cx: float) -> bool:
        """Whether canvas x ``cx`` is on box ``index``'s handle (its right 8 px)."""
        x0, _y0, x1, _y1 = self.box_rect(index)
        return x1 - self.handle_px() <= cx <= x1

    def see(self, index: int) -> None:
        """Scroll box ``index`` into view."""
        canvas = self.canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        region = canvas.cget("scrollregion").split()
        if width <= 1 or height <= 1 or len(region) != 4:
            return
        total_w, total_h = float(region[2]) or 1.0, float(region[3]) or 1.0
        x0, y0, x1, y1 = self.box_rect(index)
        left, top = canvas.canvasx(0), canvas.canvasy(0)
        gap, margin = RING_GAP * self.dpi, MAP_MARGIN * self.dpi
        # The least scroll that shows it (F46: so the side pane opening keeps the map's
        # left part in view while the box comes out from under it).
        if x0 - gap < left or x1 - x0 + 2 * margin > width:
            canvas.xview_moveto(max(0.0, (x0 - margin) / total_w))
        elif x1 + gap > left + width:
            canvas.xview_moveto(max(0.0, (x1 + margin - width) / total_w))
        if y0 - gap < top or y1 - y0 + 2 * margin > height:
            canvas.yview_moveto(max(0.0, (y0 - margin) / total_h))
        elif y1 + gap > top + height:
            canvas.yview_moveto(max(0.0, (y1 + margin - height) / total_h))

    # --- Keys, clicks, zoom -----------------------------------------------------------------

    def focus_box(self, index: int | None, *, from_tab: bool = False) -> None:
        if not from_tab:
            self.anchor = None
            self.back = None
            if self.edge is not None:
                self.select_edge(None)
        self.focused = index
        self._sync_escape()
        self._draw_ring()
        if index is not None:
            self.see(index)

    def _ensure_focus(self) -> None:
        if self.focused is None:
            self.focus_box(self._first_box())

    def _arrow(self, way: str, big: bool = False) -> str:
        if self.moving is not None:             # Move box mode: the arrows move the box
            dx, dy = _STEPS[way]
            step = PLACE_STEP * (BIG_STEP if big else 1)
            x, y = self._shifted.get(self.moving.box, self.moving.origin)
            self._show_at(self.moving.box, (max(0, x + dx * step), max(0, y + dy * step)))
            return "break"
        return self.pan(way, big)

    def pan(self, way: str, big: bool = False) -> str:
        """Scroll the map a tenth of the view that way (``BIG_STEP`` tenths with Shift)."""
        dx, dy = _STEPS[way]
        units = BIG_STEP if big else 1
        if dx:
            self.canvas.xview_scroll(dx * units, "units")
        if dy:
            self.canvas.yview_scroll(dy * units, "units")
        return "break"

    def _pan_key(self, event: tk.Event, way: str, big: bool = False) -> str | None:
        """W A S D; a Ctrl, Alt or Cmd chord (Ctrl+S saves) goes on to its own binding."""
        if int(event.state) & CHORD_STATE:
            return None
        return self.pan(way, big)

    def _hop(self, way: str) -> str:
        """Ctrl+arrows: focus the next box that way (the first box if none is focused)."""
        if self.layout is not None:
            if self.focused is None:
                self._ensure_focus()
            else:
                found = neighbour(self.layout, self.focused, way)
                if found is not None:
                    self.focus_box(found)
        return "break"

    def _tab(self, _event: tk.Event | None = None, step: int = 1) -> str:
        """Tab / Shift+Tab (F46 C2): the focused box's next / previous outgoing arrow, in
        ``out_edges`` order (wrapping); Enter then focuses its target, Esc goes back."""
        if self.layout is not None and self.focused is not None:
            anchor = self.anchor if self.anchor is not None else self.focused
            order = out_edges(self.layout, anchor)
            if order:
                if self.edge in order:
                    at = (order.index(self.edge) + step) % len(order)
                else:
                    at = 0 if step > 0 else len(order) - 1
                self.back = None
                self.anchor = anchor
                self.select_edge(order[at])
        return "break"

    def _open_focused(self, tab: bool = False) -> str:
        if self.moving is not None:             # Move box mode: Enter makes the map step
            moving, self.moving = self.moving, None
            self._sync_escape()
            x, y = self._shifted.get(moving.box, moving.origin)
            self.move_to(moving.box, (round(x), round(y)))
            return "break"
        if self.layout is not None and self.edge is not None and not tab:
            edge = self.layout.edges[self.edge]     # F46: Enter on an arrow: its target
            self.focus_box(edge.dst)
            self.back = edge.src
            self._sync_escape()
            return "break"
        if self.layout is not None and self.focused is not None:
            (self.on_open_tab if tab else self.on_open)(self.layout.boxes[self.focused])
        return "break"

    def box_at(self, x: int, y: int) -> int | None:
        """The box under window point (``x``, ``y``) of the canvas, or None."""
        canvas = self.canvas
        cx, cy = canvas.canvasx(x), canvas.canvasy(y)
        for item in reversed(canvas.find_overlapping(cx, cy, cx, cy)):
            for tag in canvas.gettags(item):
                if tag.startswith("box") and tag[3:].isdigit():
                    return int(tag[3:])
        return None

    def _click(self, event: tk.Event, tab: bool = False) -> None:
        """A press on a box focuses it and may start a drag (F46); the release opens it
        (``_release``) unless the box moved."""
        self.cancel_move()
        self.cancel_link()
        self._drop_field()
        self.canvas.focus_set()
        head = self.head_at(event.x, event.y)
        if head is not None and self.layout is not None and self.on_retarget is not None:
            self.link = _Link(self.layout.edges[head].src, edge=head, away=True)
            self._sync_escape()                 # F46: the selected arrow's head moves
            return
        found = self.box_at(event.x, event.y)
        if found is None and self.layout is not None:
            self.select_edge(self.edge_at(event.x, event.y))   # F46: an arrow or its chip
            return
        if found is not None and self.layout is not None:
            self.anchor = None
            self.back = None
            if self.edge is not None:
                self.select_edge(None)
            self.focused = found
            self._draw_ring()
            if self.on_handle(found, self.canvas.canvasx(event.x)):
                self.link = _Link(found)        # F46: the handle starts an arrow
                self._sync_escape()
                return
            box = self.layout.boxes[found]
            self.drag = _Drag(found, (box.x, box.y), (self.canvas.canvasx(event.x),
                                                      self.canvas.canvasy(event.y)), tab)
            self._sync_escape()

    # --- Moving boxes (F46 04 §6.8, PR-F46-05, AC-F46-25) ----------------------------------

    def _drag_motion(self, event: tk.Event) -> None:
        """``<B1-Motion>``: keep the newest pointer, moved once per idle (coalesced)."""
        if self.link is not None:
            self._link_to(event)
            return
        drag = self.drag
        if drag is None:
            return
        drag.pointer = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if self._drag_id is None:
            self._drag_id = self.canvas.after_idle(self._drag_step)

    def _drag_step(self) -> None:
        self._drag_id = None
        drag = self.drag
        if drag is None or drag.pointer is None:
            return
        dx, dy = drag.pointer[0] - drag.press[0], drag.pointer[1] - drag.press[1]
        if not drag.moved and math.hypot(dx, dy) < DRAG_START_PX * self.dpi:
            return
        drag.moved = True
        s = self._scale()
        self._show_at(drag.box, (max(0.0, drag.origin[0] + dx / s),
                                 max(0.0, drag.origin[1] + dy / s)))

    def _show_at(self, index: int, place: tuple[float, float]) -> None:
        """Draw box ``index`` with its corner at ``place`` (100 %) while it is moved: its
        items and the ring move, its edges get new coordinates and their chips a new slot.
        Nothing else is touched (O(degree), UI-F46-04)."""
        assert self.layout is not None
        canvas = self.canvas
        old = self.box_rect(index)
        self._shifted[index] = place
        new = self.box_rect(index)
        ddx, ddy = new[0] - old[0], new[1] - old[1]
        canvas.move(f"box{index}", ddx, ddy)
        if self.focused == index and self.ring is not None:
            canvas.move(self.ring, ddx, ddy)
        edges = self.layout.edges
        chips = []
        for e in self._incident.get(index, ()):
            edge = edges[e]
            item = self.edge_items[e][0]
            canvas.coords(item, *self.edge_points(edge.src, edge.dst, self.ports.get(e, 0.5),
                                                  self.ends.get(e)))
            if edge.choice:
                canvas.delete(f"chip{e}")
                chips.append(e)
        for e in chips:
            self.draw_chip(e, reslot=True)

    def _release(self, event: tk.Event) -> None:
        """A release ends a drag: snapped to 20 px (Shift: as dropped), never below 0, one
        map step. Without a drag it opens the box, as F45's click did."""
        if self.link is not None:
            self._link_to(event)
            link, target = self.link, self.link.target
            self.cancel_link()
            if link.edge is not None:
                if target is not None and self.on_retarget is not None                         and self.layout is not None                         and target != self.layout.edges[link.edge].dst:
                    self.on_retarget(link.edge, target)
                return
            if target is not None and self.on_arrow is not None:
                self.on_arrow(link.src, target)
            return
        drag, self.drag = self.drag, None
        self._sync_escape()
        if drag is None or self.layout is None:
            return
        if self._drag_id is not None:
            self.canvas.after_cancel(self._drag_id)
            self._drag_id = None
        pointer = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        dx, dy = pointer[0] - drag.press[0], pointer[1] - drag.press[1]
        if not drag.moved and math.hypot(dx, dy) < DRAG_START_PX * self.dpi:
            self.cancel_move()
            self.focus_box(drag.box)
            (self.on_open_tab if drag.tab else self.on_open)(self.layout.boxes[drag.box])
            return
        s = self._scale()
        x, y = round(drag.origin[0] + dx / s), round(drag.origin[1] + dy / s)
        self.move_to(drag.box, (x, y) if event.state & 0x0001 else snap((x, y)))

    def _escape(self, _event: tk.Event | None = None) -> str | None:
        """Esc cancels a drag, an arrow drag or Move box mode (the box goes back); with an
        arrow selected it goes back to its source box, and after Enter on an arrow back to
        where Tab started (F46 C2); else it isn't ours."""
        if self.link is not None:
            self.cancel_link()
            return "break"
        if self.drag is not None or self.moving is not None:
            self.cancel_move()
            return "break"
        if self.edge is not None and self.layout is not None:
            src = self.layout.edges[self.edge].src
            self.focus_box(src)
            return "break"
        if self.back is not None:
            self.focus_box(self.back)
            return "break"
        return None

    def _sync_escape(self) -> None:
        """Esc is bound on the canvas only while a drag, Move box mode, an arrow drag or a
        selected arrow is in progress (F44 I-6: no main-window binding reacts to Esc at
        rest)."""
        held = self.drag is not None or self.moving is not None or self.link is not None \
            or self.edge is not None or self.back is not None
        if held != bool(self.canvas.bind("<Escape>")):
            if held:
                self.canvas.bind("<Escape>", self._escape)
            else:
                self.canvas.unbind("<Escape>")

    def cancel_move(self) -> None:
        """A drag or Move box mode ends with no map step and the box back where it was
        (Esc, the canvas losing the focus, G9)."""
        if self._drag_id is not None:
            try:
                self.canvas.after_cancel(self._drag_id)
            except tk.TclError:
                pass
            self._drag_id = None
        moved = bool(self._shifted) or self.moving is not None
        self.drag = self.moving = None
        self._sync_escape()
        if moved:
            self.draw()

    # --- Arrows, choice text, new scenes, context menus (F46 step 5, 04 §6.4, §6.8) ---------

    def _link_to(self, event: tk.Event) -> None:
        """An arrow drag's pointer: the dashed accent line follows it; the box under it
        (the source itself only once the pointer has left it) is the drop target."""
        link, canvas = self.link, self.canvas
        if link is None or self.layout is None:
            return
        cx, cy = canvas.canvasx(event.x), canvas.canvasy(event.y)
        x0, y0, x1, y1 = self.box_rect(link.src)
        start = (x1 - self.handle_px() / 2, (y0 + y1) / 2)
        if link.line is None:
            link.line = canvas.create_line(*start, cx, cy, fill=SELECT_COLOR, dash=(6, 4),
                                           width=max(2, round(2 * self.dpi)), arrow="last",
                                           tags=("linkline",))
        else:
            canvas.coords(link.line, *start, cx, cy)
        found = self.box_at(event.x, event.y)
        if found != link.src:
            link.away = link.away or found is None or found != link.src
        target = found if found is not None and (found != link.src or link.away) else None
        if target != link.target:
            old, link.target = link.target, target
            self._paint_box(old)
            self._paint_box(target)

    def cancel_link(self) -> None:
        """An arrow drag ends: its line and the target's outline go (Esc, focus loss)."""
        link, self.link = self.link, None
        if link is None:
            return
        if link.line is not None:
            self.canvas.delete(link.line)
        self._paint_box(link.target)
        self._sync_escape()

    def head_at(self, x: int, y: int) -> int | None:
        """The selected arrow, when window point (``x``, ``y``) is on its head (dragging
        it onto another box changes the target, PR-F46-10), else None."""
        if self.edge is None:
            return None
        canvas = self.canvas
        cx, cy = canvas.canvasx(x), canvas.canvasy(y)
        for item in canvas.find_withtag(f"edge{self.edge}"):
            if canvas.type(item) != "line":
                continue
            coords = canvas.coords(item)
            if len(coords) >= 4 and math.hypot(cx - coords[-2], cy - coords[-1])                     <= HEAD_HIT_PX * self.dpi:
                return self.edge
        return None

    def edge_at(self, x: int, y: int) -> int | None:
        """The arrow (or choice chip) within 4 px of window point (``x``, ``y``), or None."""
        canvas = self.canvas
        cx, cy = canvas.canvasx(x), canvas.canvasy(y)
        r = EDGE_HIT_PX * self.dpi
        for item in reversed(canvas.find_overlapping(cx - r, cy - r, cx + r, cy + r)):
            for tag in canvas.gettags(item):
                for head in ("chip", "edge"):
                    if tag.startswith(head) and tag[len(head):].isdigit():
                        return int(tag[len(head):])
        return None

    def map_point(self, x: int, y: int) -> tuple[int, int]:
        """Window point (``x``, ``y``) as a map place at 100 % (never below 0)."""
        canvas, s = self.canvas, self._scale()
        margin = MAP_MARGIN * self.dpi
        return (max(0, round((canvas.canvasx(x) - margin) / s)),
                max(0, round((canvas.canvasy(y) - margin) / s)))

    def _new_scene(self, place: tuple[int, int] | None) -> None:
        if self.on_new_scene is not None:
            self.on_new_scene(place)

    def _double(self, event: tk.Event) -> str:
        """A double-click: on a choice arrow, its text field; on empty space, New scene
        there (PR-F46-14); on a box, its name (Rename, step 6)."""
        found = self.box_at(event.x, event.y)
        if found is not None:
            if self.on_handle(found, self.canvas.canvasx(event.x)):
                self._click(event)              # a quick second press on the handle
                return "break"
            if self.on_rename is not None:
                self.on_rename()
            return "break"
        edge = self.edge_at(event.x, event.y)
        if edge is not None:
            self.select_edge(edge)
            self.open_choice_field(edge)
            return "break"
        self._new_scene(self.map_point(event.x, event.y))
        return "break"

    def _f2(self) -> str:
        """F2: a selected choice arrow's text field, else the focused box's name."""
        if self.edge is not None:
            if self.on_edit_choice is not None:
                self.on_edit_choice()
            else:
                self.open_choice_field(self.edge)
        elif self.on_rename is not None:
            self.on_rename()
        return "break"

    def _delete(self) -> str:
        if self.on_delete is not None and self.moving is None and self.drag is None:
            self.on_delete()
        return "break"

    def _context_click(self, event: tk.Event) -> str:
        """Button-3: the menu for the box, arrow or empty spot under the pointer (a box
        or arrow is focused or selected first)."""
        self.cancel_move()
        self.cancel_link()
        self.canvas.focus_set()
        found = self.box_at(event.x, event.y)
        if found is not None:
            self.focus_box(found)
            target: tuple[str, object] = ("box", found)
        else:
            edge = self.edge_at(event.x, event.y)
            if edge is not None:
                self.select_edge(edge)
                target = ("edge", edge)
            else:
                self.select_edge(None)
                target = ("map", self.map_point(event.x, event.y))
        if self.on_context is not None:
            self.on_context(target[0], target[1], event.x_root, event.y_root)
        return "break"

    def _context_key(self) -> str:
        """Shift+F10 / the Menu key: the selected arrow's or the focused box's menu, at
        its middle."""
        canvas = self.canvas
        if self.layout is None or self.on_context is None:
            return "break"
        if self.edge is not None:
            x0, y0, x1, y1 = canvas.bbox(f"chip{self.edge}") or canvas.bbox(
                self.edge_items[self.edge][0])
            kind, what = "edge", self.edge
        elif self.focused is not None:
            x0, y0, x1, y1 = self.box_rect(self.focused)
            kind, what = "box", self.focused
        else:
            return "break"
        x = canvas.winfo_rootx() + int((x0 + x1) / 2 - canvas.canvasx(0))
        y = canvas.winfo_rooty() + int((y0 + y1) / 2 - canvas.canvasy(0))
        self.on_context(kind, what, x, y)
        return "break"

    def open_choice_field(self, index: int) -> ttk.Entry | None:
        """F2 or a double-click on a choice arrow (PR-F46-13): an inline field over its
        chip holding the full text; Enter writes it (``on_choice_text``), Esc or leaving
        it writes nothing."""
        if self.layout is None or not 0 <= index < len(self.layout.edges):
            return None
        edge = self.layout.edges[index]
        if edge.kind != "menu":
            return None
        self._drop_field()
        canvas = self.canvas
        box = canvas.bbox(f"chip{index}")
        if box is None:
            points = self.edge_points(edge.src, edge.dst, self.ports.get(index, 0.5),
                                      self.ends.get(index))
            cx, cy = self.curve_at(points, 0.5)
            w = 0.0
        else:
            cx, cy, w = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, box[2] - box[0]
        entry = ttk.Entry(canvas, font=self.chip_font)
        entry.insert(0, edge.choice or "")
        width = max(w + 24 * self.dpi, CHOICE_FIELD_PX * self.dpi)
        item = canvas.create_window(cx, cy, window=entry, width=width, anchor="center",
                                    tags=("field",))
        self.field = _Field(index, entry, item)
        entry.select_range(0, "end")
        entry.icursor("end")
        entry.focus_set()
        for key in ("<Return>", "<KP_Enter>"):
            entry.bind(key, lambda _e: self._commit_field())
        entry.bind("<Escape>", lambda _e: (self._drop_field(), "break")[1])
        entry.bind("<FocusOut>", lambda _e: self._drop_field(focus=False), add="+")
        return entry

    def _commit_field(self) -> str:
        field = self.field
        if field is None:
            return "break"
        text = field.entry.get()
        self._drop_field()
        if self.on_choice_text is not None:
            self.on_choice_text(field.edge, text)
        return "break"

    def _drop_field(self, focus: bool = True) -> None:
        """Close the inline field writing nothing; the map gets the focus back."""
        field, self.field = self.field, None
        if field is None:
            return
        try:
            self.canvas.delete(field.item)
            field.entry.destroy()
        except tk.TclError:
            pass
        if focus:
            self.canvas.focus_set()

    def start_move(self) -> None:
        """**Move box** (G3): the focused box follows the arrow keys (20 px, Shift 100)
        until Enter makes one map step; Esc or the focus leaving puts it back."""
        if self.layout is None or self.focused is None:
            return
        self.cancel_move()
        box = self.layout.boxes[self.focused]
        self.canvas.focus_set()
        self.moving = _Drag(self.focused, (box.x, box.y), (0.0, 0.0), False)
        self._sync_escape()
        if self.ring is not None:               # the ring turns dashed while it moves
            self.canvas.itemconfigure(self.ring, dash=(4, 3))

    def nudge(self, way: str, big: bool = False) -> None:
        """Alt+arrows: the focused box 20 px that way (Shift: 100), one map step."""
        if self.layout is None or self.focused is None or self.moving is not None:
            return
        box = self.layout.boxes[self.focused]
        dx, dy = _STEPS[way]
        step = PLACE_STEP * (BIG_STEP if big else 1)
        self.move_to(self.focused, (box.x + dx * step, box.y + dy * step))

    def move_to(self, index: int, place: tuple[int, int], title: str = MOVE_TITLE) -> None:
        """Box ``index``'s corner to ``place`` (never below 0) as one map step. The first
        move also records every shown box's place, so automatic placement can't shuffle
        the map later (04 §6.8). Back where it was: no step, just redrawn."""
        assert self.layout is not None
        name = self.layout.boxes[index].name
        place = (max(0, int(place[0])), max(0, int(place[1])))
        shown = layout_places(self.layout)
        if shown.get(name) == place:
            self.cancel_move()
            self.draw()
            self.focus_box(index)
            return
        before: dict[str, tuple[int, int] | None] = {
            n: None for n in shown if n not in self.places}
        before[name] = self.places.get(name)
        after: dict[str, tuple[int, int] | None] = {n: shown[n] for n in before}
        after[name] = place
        self._step(title, before, after)

    def tidy_up(self) -> None:
        """Tidy up (PR-F46-11): every box back to F45's columns, as one map step."""
        if not self.places:
            return
        before: dict[str, tuple[int, int] | None] = dict(self.places)
        self._step(TIDY_UP, before, {n: None for n in before})

    def _step(self, title: str, before: dict, after: dict) -> None:
        self.message = ""
        self.apply_places(after)
        if self.on_step is not None:
            self.on_step(title, before, after)
        if self.focused is not None:
            self.see(self.focused)

    def apply_places(self, changes: Mapping[str, tuple[int, int] | None]) -> None:
        """Set (or, for None, forget) these places and redraw: a step, its undo or redo."""
        for name, place in changes.items():
            if place is None:
                self.places.pop(name, None)
            else:
                self.places[name] = (int(place[0]), int(place[1]))
        self._relayout()

    def set_places(self, places: Mapping[str, tuple[int, int]]) -> None:
        """The remembered places (the layout file's, at the first draw)."""
        self.places = {name: (int(x), int(y)) for name, (x, y) in places.items()}
        self._relayout()

    def saved_places(self) -> dict[str, tuple[int, int]]:
        """What the layout file keeps: the remembered places, plus, once any box is
        placed, each shown box's place (a box new since then: ``place_free``'s spot)."""
        if not self.places or self.layout is None:
            return dict(self.places)
        return {**layout_places(self.layout), **self.places}

    def _wheel(self, event: tk.Event) -> str:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _wheel_x(self, event: tk.Event) -> str:
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _wheel_zoom(self, event: tk.Event) -> str:
        self.zoom_by(1 if event.delta > 0 else -1)
        return "break"

    def zoom_by(self, step: int) -> None:
        """Ctrl+= (``step`` > 0), Ctrl+- (< 0), Ctrl+0 (0: 100 %), within 50–200 %."""
        zoom = 100 if step == 0 else min(MAP_ZOOM_MAX, max(
            MAP_ZOOM_MIN, self.zoom + (MAP_ZOOM_STEP if step > 0 else -MAP_ZOOM_STEP)))
        if zoom != self.zoom:
            self.zoom = zoom
            self.draw()
            if self.focused is not None:
                self.see(self.focused)


# --- Icon glyphs (08 §6) -------------------------------------------------------------------

ICON_FAMILIES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
GLYPHS: dict[str, tuple[str, str]] = {   # name -> (Fluent code point, fallback; "" = none)
    "editor": ("\uE70F", "✎"),
    "storymap": ("\uE826", ""),
    "image": ("\uEB9F", ""),
    "outline": ("\uE8FD", "≡"),
    "add": ("\uE710", "+"),
    "play": ("\uE768", "▶"),
    "warning": ("\uE7BA", "⚠"),
    "script": ("\uE8A5", ""),
    "events": ("\uE9D5", ""),           # F46: the side pane's Events tab (Checklist)
    "database": ("\uE8F1", ""),         # F47: the Database tab (Library)
    "settings": ("\uE713", ""),         # F47 W4: the Game settings tab (Settings)
}


def icon_family(root: tk.Misc) -> str | None:
    """The first icon font Tk knows (Windows), or None: then the fallback symbols show."""
    known = set(tkfont.families(root))
    return next((name for name in ICON_FAMILIES if name in known), None)


def glyph(name: str, family: str | None) -> str:
    """Icon ``name``'s character in ``family``, or its fallback symbol."""
    fluent, fallback = GLYPHS[name]
    return fluent if family is not None else fallback


# --- Empty states (08 §9, P2) --------------------------------------------------------------

EMPTY_ICON_PX = 40
EMPTY_HINT_WRAP = 360
EMPTY_AT = 0.4                          # the block's centre, as a share of the area's height


class EmptyState:
    """An area with nothing to show: a 40 px muted icon, a title, a muted hint (wrap 360)
    and one primary button that runs an existing command, as a block centred at 40 % of the
    area's height. ``show(over)`` covers widget ``over`` (placed on it); ``hide`` uncovers
    it. The button is in the area's focus order (``focus_widget``)."""

    def __init__(self, parent: tk.Misc, *, icon: str, title: str, hint: str,
                 button: str | None = None, command: Callable[[], None] | None = None,
                 scale: float = 1.0) -> None:
        back = THEME["editor.background"]
        self.frame = tk.Frame(parent, background=back, highlightthickness=0, borderwidth=0)
        block = tk.Frame(self.frame, background=back)
        block.place(relx=0.5, rely=EMPTY_AT, anchor="center")
        family = icon_family(parent)
        mark = glyph(icon, family)
        if mark:
            self.icon_font = tkfont.Font(root=parent, family=family or "TkDefaultFont",
                                         size=-round(EMPTY_ICON_PX * scale))
            tk.Label(block, text=mark, font=self.icon_font, background=back,
                     foreground=MUTED).pack(pady=(0, round(12 * scale)))
        self.title = ttk.Label(block, text=title, style="EmptyTitle.TLabel")
        self.title.pack()
        self.hint = ttk.Label(block, text=hint, style="Hint.TLabel", justify="center",
                              wraplength=round(EMPTY_HINT_WRAP * scale))
        self.hint.pack(pady=(round(4 * scale), 0))
        self.button: ttk.Button | None = None
        if button is not None and command is not None:
            self.button = ttk.Button(block, text=button, command=command)
            self.button.pack(pady=(round(16 * scale), 0))
            for key in ("<Return>", "<KP_Enter>"):
                self.button.bind(key, lambda _e: (command(), "break")[1])
        self.shown = False

    def show(self, over: tk.Widget, inset: int = 0) -> None:
        if not self.shown:
            self.frame.place(in_=over, x=inset, y=inset, relwidth=1, relheight=1,
                             width=-2 * inset, height=-2 * inset)
            self.frame.lift()
            self.shown = True

    def hide(self) -> None:
        if self.shown:
            self.frame.place_forget()
            self.shown = False

    def focus_widget(self) -> tk.Widget | None:
        """The button while the state shows (F6 and Tab land on it), else None."""
        return self.button if self.shown else None


# --- Tab strip (08 §7, P2) ------------------------------------------------------------------

TAB_STRIP_PX = 32
TAB_PAD_PX = 12
TAB_ICON_PX = 14
TAB_BAR_PX = 2


class TabStrip:
    """The 32-high chrome row over the notebook (whose own tabs are hidden): each tab a 14 px
    icon and its word, padding 12; inactive tabs muted (text on hover), the active one on
    the surface in white over a 2 px accent bar. A click selects the notebook's tab; tabs
    never take the keyboard focus. ``sync`` follows the notebook's selection."""

    def __init__(self, parent: tk.Misc, notebook: ttk.Notebook,
                 tabs: Sequence[tuple[str, str]], *, font: tkfont.Font,
                 scale: float = 1.0) -> None:
        self.notebook = notebook
        chrome = THEME["tab.barBackground"]
        self.frame = tk.Frame(parent, background=chrome, height=round(TAB_STRIP_PX * scale),
                              highlightthickness=0, borderwidth=0)
        self.frame.pack_propagate(False)
        family = icon_family(parent)
        self.icon_font = tkfont.Font(root=parent, family=family or font.actual("family"),
                                     size=-round(TAB_ICON_PX * scale))
        pad, gap = round(TAB_PAD_PX * scale), round(6 * scale)
        self.cells: list[tuple[tk.Frame, tk.Label, tk.Label, tk.Frame]] = []
        self.hovered: int | None = None
        for index, (word, icon) in enumerate(tabs):
            cell = tk.Frame(self.frame, background=chrome, cursor="hand2")
            cell.pack(side="left", fill="y")
            bar = tk.Frame(cell, background=chrome, height=round(TAB_BAR_PX * scale))
            bar.pack(side="bottom", fill="x")
            mark = glyph(icon, family)
            symbol = tk.Label(cell, text=mark, font=self.icon_font, background=chrome,
                              borderwidth=0, padx=0)
            if mark:
                symbol.pack(side="left", padx=(pad, gap))
            label = tk.Label(cell, text=word, font=font, background=chrome, borderwidth=0,
                             padx=0)
            label.pack(side="left", padx=(0 if mark else pad, pad))
            for widget in (cell, symbol, label, bar):
                widget.bind("<Button-1>", lambda _e, i=index: self.notebook.select(i))
                widget.bind("<Enter>", lambda _e, i=index: self._hover(i))
                widget.bind("<Leave>", lambda _e: self._hover(None))
            self.cells.append((cell, symbol, label, bar))
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self.sync(), add="+")
        self.sync()

    def words(self) -> list[str]:
        return [str(label.cget("text")) for _cell, _symbol, label, _bar in self.cells]

    def active(self) -> int:
        try:
            return int(self.notebook.index("current"))
        except tk.TclError:
            return 0

    def _hover(self, index: int | None) -> None:
        self.hovered = index
        self.sync()

    def sync(self) -> None:
        current = self.active()
        for index, (cell, symbol, label, bar) in enumerate(self.cells):
            on = index == current
            back = THEME["tab.activeBackground" if on else "tab.inactiveBackground"]
            fore = THEME["tab.activeForeground" if on else "tab.hoverForeground"
                         if index == self.hovered else "tab.inactiveForeground"]
            for widget in (cell, symbol, label):
                widget.configure(background=back)
            symbol.configure(foreground=fore)
            label.configure(foreground=fore)
            bar.configure(background=THEME["tab.indicator"] if on else back)


# --- Status bar (F45 01 §6.5, amended 2026-11-02; 08 D1: neutral, with a divider) --------

ELLIPSIS = "…"
STATUS_ITEM_PAD = 7                     # px either side of an item's text, at 100 %


# --- Outline (2026-11-02, AC-F45-54) ---------------------------------------------------------

class OutlineView:
    """The Outline tab: a read-only tree of ``outline.Row`` rows. Enter or a double-click on
    a row with a place calls ``on_open(file, line)``. Sections start open."""

    def __init__(self, parent: tk.Misc, *,
                 on_open: Callable[[str, int], None], scale: float = 1.0,
                 on_check: Callable[[], None] | None = None) -> None:
        self.frame = ttk.Frame(parent, padding=round(8 * scale))
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.note = ttk.Label(self.frame, text=NO_OUTLINE, foreground=MUTED)
        self.note.grid(row=0, column=0, columnspan=2, sticky="w",
                       padx=round(4 * scale), pady=(0, round(8 * scale)))
        self.tree = ttk.Treeview(self.frame, show="tree", selectmode="browse", height=1,
                                 style="Surface.Treeview")
        self.tree.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=autohide(bar, row=1, column=1, sticky="ns"))
        self.tree.tag_configure("section", foreground=THEME["syntax.keyword"])
        self.tree.tag_configure("place", foreground=PLAIN_COLOR)
        self.tree.tag_configure("plain", foreground=MUTED)
        self.on_open = on_open
        self.places: dict[str, tuple[str, int]] = {}
        self.rows: tuple[OutlineRow, ...] = ()
        for key in ("<Return>", "<KP_Enter>", "<Double-Button-1>"):
            self.tree.bind(key, self._open, add="+")
        # No rows: the empty state over the whole tab (08 §9), NO_OUTLINE's words.
        title, _dot, hint = NO_OUTLINE.partition(". ")
        self.empty = EmptyState(self.frame, icon="outline", title=title, hint=hint,
                                button=CHECK_NOW_BUTTON, command=on_check, scale=scale)
        self.empty.show(self.frame)

    def set_rows(self, rows: Sequence[OutlineRow]) -> None:
        """Replace the tree; keeps which sections are open by their title word."""
        rows = tuple(rows)
        if rows == self.rows:
            return
        closed = {self.tree.item(i, "text").split(" (")[0] for i in self.tree.get_children()
                  if not self.tree.item(i, "open")}
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        self.places = {}
        stack: list[tuple[str, OutlineRow, bool]] = [("", r, True) for r in reversed(rows)]
        while stack:
            parent, row, top = stack.pop()
            if row.file is not None and row.line is not None:
                where = f"   {row.file}:{row.line}"
                tag = "place"
            else:
                where, tag = "", "section" if top else "plain"
            item = self.tree.insert(parent, "end", text=row.text + where, tags=(tag,),
                                    open=not (top and row.text.split(" (")[0] in closed))
            if row.file is not None and row.line is not None:
                self.places[item] = (row.file, row.line)
            stack.extend((item, child, False) for child in reversed(row.children))
        empty = not any(r.children for r in rows)
        self.note.configure(text=NO_OUTLINE if empty else
                            "Enter or double-click a row to open its line.")
        if empty:
            self.empty.show(self.frame)
        else:
            self.empty.hide()

    def texts(self) -> list[str]:
        """Every row's text, depth first (for tests)."""
        out: list[str] = []
        stack = list(reversed(self.tree.get_children()))
        while stack:
            item = stack.pop()
            out.append(self.tree.item(item, "text"))
            stack.extend(reversed(self.tree.get_children(item)))
        return out

    def _open(self, _event: tk.Event | None = None) -> str:
        chosen = self.tree.focus() or next(iter(self.tree.selection()), "")
        place = self.places.get(chosen)
        if place is not None:
            self.on_open(*place)
        return "break"


def elide(text: str, width: int, measure: Callable[[str], int]) -> str:
    """``text``, cut at the end with ``…`` so that ``measure`` of it is at most ``width``
    pixels; ``""`` when not even ``…`` fits. Never wraps."""
    if measure(text) <= width:
        return text
    if measure(ELLIPSIS) > width:
        return ""
    low, high = 0, len(text)
    while low < high:                   # the longest prefix that fits with the ellipsis
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + ELLIPSIS) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ELLIPSIS


class StatusItem:
    """One entry of the status bar: a ``tk.Label`` showing ``prefix`` and the text, cut with
    ``…`` when the bar is too short. Like a label, ``configure(text=…)`` and
    ``cget("text")`` set and read the full text (without the prefix); an empty text hides
    the item. A clickable item runs ``on_click`` and shows the hover color."""

    def __init__(self, bar: "StatusBar", side: str, prefix: str, shrink: int,
                 on_click: Callable[[], object] | None) -> None:
        self.bar = bar
        self.side = side
        self.prefix = prefix
        self.shrink = shrink            # who gives up width first when space runs out
        self.text = ""
        self.label = tk.Label(bar.frame, text="", font=bar.font, background=bar.background,
                              foreground=bar.foreground, padx=bar.pad, pady=0,
                              borderwidth=0, highlightthickness=0, anchor="w", takefocus=0)
        if on_click is not None:
            label = self.label
            label.configure(cursor="hand2")
            label.bind("<Button-1>", lambda _e: on_click(), add="+")
            label.bind("<Enter>", lambda _e: label.configure(background=bar.hover), add="+")
            label.bind("<Leave>", lambda _e: label.configure(background=bar.background),
                       add="+")

    def configure(self, text: str | None = None, **_options: object) -> None:
        if text is not None and str(text) != self.text:
            self.text = str(text)
            self.bar.layout()

    config = configure

    def cget(self, option: str) -> object:
        return self.text if option == "text" else self.label.cget(option)

    def shown(self) -> str:
        """The text on screen: the prefix and the (maybe cut) text, or ``""`` when hidden."""
        return str(self.label.cget("text")) if self.text else ""


class StatusBar:
    """A full-width strip along the window's bottom edge, VS Code's status bar: items on the
    left and on the right, in the UI text color on the chrome tone (``08`` D1), one line
    high, under a 1 px divider (``divider``, packed by the window just above ``frame``). Long
    texts are cut with ``…`` (never wrapped): when the items don't fit, the one with the
    highest ``shrink`` gives up width first. Items take no keyboard focus; what they show is
    reachable elsewhere."""

    def __init__(self, parent: tk.Misc, *, font: tkfont.Font, height: int,
                 scale: float = 1.0) -> None:
        self.font = font
        self.background = THEME["statusBar.background"]
        self.foreground = THEME["statusBar.foreground"]
        self.hover = THEME["statusBar.hoverBackground"]
        self.pad = round(STATUS_ITEM_PAD * scale)
        self.frame = tk.Frame(parent, background=self.background, height=height,
                              borderwidth=0, highlightthickness=0)
        self.frame.pack_propagate(False)
        self.divider = tk.Frame(parent, background=THEME["statusBar.border"],
                                height=max(1, round(scale)), borderwidth=0,
                                highlightthickness=0)
        self.items: list[StatusItem] = []
        self._packed: list[StatusItem] = []
        self._width = 0
        self.frame.bind("<Configure>", self._resized, add="+")

    def add(self, *, side: str = "left", prefix: str = "", shrink: int = 0,
            on_click: Callable[[], object] | None = None, text: str = "") -> StatusItem:
        """A new item at the end of its side (``left`` or ``right``, both in reading
        order)."""
        item = StatusItem(self, side, prefix, shrink, on_click)
        self.items.append(item)
        item.configure(text=text)
        return item

    def _resized(self, event: tk.Event) -> None:
        if event.width != self._width:
            self._width = event.width
            self.layout()

    def layout(self) -> None:
        """Fit the items' texts to the bar's width and pack the shown ones."""
        measure = self.font.measure
        shown = [item for item in self.items if item.text]
        natural = {id(item): measure(item.prefix + item.text) + 2 * self.pad for item in shown}
        width = self.frame.winfo_width()
        over = sum(natural.values()) - width if width > 1 else 0
        room = dict(natural)
        for item in sorted(shown, key=lambda entry: -entry.shrink):
            if over <= 0 or item.shrink <= 0:
                break
            floor = measure(item.prefix + ELLIPSIS) + 2 * self.pad
            give = max(0, min(over, room[id(item)] - floor))
            room[id(item)] -= give
            over -= give
        for item in self.items:
            text = ""
            if item.text:
                space = room[id(item)] - 2 * self.pad - measure(item.prefix)
                text = item.prefix + elide(item.text, space, measure)
            if str(item.label.cget("text")) != text:
                item.label.configure(text=text)
        if shown != self._packed:
            for item in self._packed:
                item.label.pack_forget()
            for item in shown:
                if item.side == "left":
                    item.label.pack(side="left", fill="y")
            for item in reversed(shown):
                if item.side == "right":
                    item.label.pack(side="right", fill="y")
            self._packed = shown


# --- Menu bar (08 §7, D5: dark and in the window on Windows and Linux) ---------------------

MENU_TITLE_PAD = 8                      # px either side of a title, at 100 %
_WH_MSGFILTER, _MSGF_MENU = -1, 2
_WM_KEYDOWN, _WM_MOUSEMOVE, _WM_LBUTTONDOWN = 0x0100, 0x0200, 0x0201
_VK_LEFT, _VK_RIGHT, _VK_DOWN = 0x25, 0x27, 0x28
_MN_GETHMENU = 0x01E1
_MF_BYPOSITION, _MF_HILITE = 0x0400, 0x0080


# Tk on Windows draws a disabled menu entry "embossed": its text again in the system's white
# highlight, one pixel off, which reads brighter than the enabled entries on Studio's dark
# menus. There an entry that can't be used now stays "normal" but is drawn in the theme's
# disabled color with no hover, and its command does nothing (``set_entry_enabled``).
MENU_DIM_ENTRIES = sys.platform == "win32"


def _menu_off(menu: tk.Menu) -> set[str]:
    off = getattr(menu, "_studio_off", None)
    if off is None:
        off = set()
        menu._studio_off = off              # type: ignore[attr-defined]
    return off


def menu_command(menu: tk.Menu, label: str, run: Callable[[], object]) -> Callable[[], None]:
    """``run`` as entry ``label``'s command: it does nothing while the entry is off."""
    def command() -> None:
        if label not in _menu_off(menu):
            run()
    return command


def set_entry_enabled(menu: tk.Menu, entry: str | int, enabled: bool) -> None:
    """Turn a menu entry on or off; on Windows, without Tk's embossed disabled look (its
    command must come from ``menu_command``)."""
    if not MENU_DIM_ENTRIES:
        menu.entryconfigure(entry, state="normal" if enabled else "disabled")
        return
    label = str(menu.entrycget(entry, "label"))
    off = _menu_off(menu)
    if enabled:
        off.discard(label)
        menu.entryconfigure(entry, state="normal", foreground="", activeforeground="",
                            activebackground="")
    else:
        off.add(label)
        dim = THEME["button.disabledForeground"]
        menu.entryconfigure(entry, state="normal", foreground=dim, activeforeground=dim,
                            activebackground=str(menu.cget("background")))


def entry_enabled(menu: tk.Menu, entry: str | int) -> bool:
    """Whether a menu entry is on (``set_entry_enabled``)."""
    if str(menu.entrycget(entry, "state")) == "disabled":
        return False
    return str(menu.entrycget(entry, "label")) not in _menu_off(menu)


class MenuBar:
    """A row of menu titles on the chrome tone that posts the window's own ``tk.Menu``
    drop-downs (so their entries, accelerators and states are the native menu's), for
    Windows and Linux, where Tk can't color the native bar (``08`` D5; macOS keeps its
    own). Each title shows its first letter underlined; hover uses ``hover`` and an open
    menu ``selection``. Alt+letter opens that menu, Alt alone and F10 the first one with its
    first entry chosen; in an open menu the arrows move (Left and Right go on to the next
    menu, as in a native bar), and Esc or a click outside closes it. The titles take no
    keyboard focus.

    On Windows a posted menu runs its own modal loop; a message-filter hook watches it for
    Left, Right and the pointer crossing to another title, ends the menu and opens the
    other one."""

    def __init__(self, root: tk.Tk, menus: Sequence[tuple[str, tk.Menu]], *,
                 font: tkfont.Font, height: int, scale: float = 1.0) -> None:
        self.root = root
        self.background = THEME["menubar.background"]
        self.foreground = THEME["menubar.foreground"]
        self.hover = THEME["menubar.hoverBackground"]
        self.open_background = THEME["menubar.openBackground"]
        self.frame = tk.Frame(root, background=self.background, height=height,
                              borderwidth=0, highlightthickness=0)
        self.frame.pack_propagate(False)
        self.menus = [menu for _label, menu in menus]
        self.titles: list[tk.Label] = []
        self.open_index: int | None = None
        self._next: tuple[int, bool] | None = None
        self._closed: tuple[int, float] | None = None     # (menu, when) it last closed
        self._alt_alone = False
        for index, (label, _menu) in enumerate(menus):
            title = tk.Label(self.frame, text=label, underline=0, font=font,
                             background=self.background, foreground=self.foreground,
                             padx=round(MENU_TITLE_PAD * scale), pady=0, borderwidth=0,
                             highlightthickness=0, takefocus=0)
            title.pack(side="left", fill="y")
            title.bind("<Button-1>", lambda _e, i=index: self._clicked(i), add="+")
            title.bind("<Enter>", lambda _e, i=index: self._paint(i, hover=True), add="+")
            title.bind("<Leave>", lambda _e, i=index: self._paint(i), add="+")
            self.titles.append(title)
        for menu in self.menus:
            for key, step in (("<Left>", -1), ("<Right>", 1)):
                menu.bind(key, lambda e, s=step: self._menu_arrow(e, s), add="+")
        root.bind("<Alt-KeyPress>", self._alt_key, add="+")
        root.bind("<KeyPress-F10>", lambda _e: self._keyboard_open(0), add="+")
        for side in ("L", "R"):
            root.bind(f"<KeyPress-Alt_{side}>", self._alt_down, add="+")
            root.bind(f"<KeyRelease-Alt_{side}>", self._alt_up, add="+")
        root.bind("<KeyPress>", self._other_key, add="+")
        root.bind("<FocusOut>", self._other_key, add="+")

    def labels(self) -> list[str]:
        return [str(title.cget("text")) for title in self.titles]

    def _paint(self, index: int, hover: bool = False) -> None:
        if index == self.open_index:
            color = self.open_background
        else:
            color = self.hover if hover else self.background
        self.titles[index].configure(background=color)

    def _paint_all(self) -> bool:
        """Repaint every title; False once the window is gone."""
        try:
            for index in range(len(self.titles)):
                self._paint(index)
        except tk.TclError:
            return False
        return True

    def _clicked(self, index: int) -> None:
        """A click on a title opens its menu; on the title of the menu that this very click
        closed, it stays closed (a toggle, as in a native bar)."""
        closed = self._closed
        if closed is not None and closed[0] == index and time.monotonic() - closed[1] < 0.3:
            return
        self.open(index)

    # --- Keys ----------------------------------------------------------------------------

    def _index_of(self, letter: str) -> int | None:
        letter = letter.lower()
        return next((i for i, title in enumerate(self.titles)
                     if str(title.cget("text"))[:1].lower() == letter), None)

    def _alt_key(self, event: tk.Event) -> str | None:
        if event.keysym.startswith("Alt_"):
            return None
        self._alt_alone = False
        index = self._index_of(event.keysym) if len(event.keysym) == 1 else None
        if index is None:
            return None
        self._keyboard_open(index)
        return "break"

    def _alt_down(self, _event: tk.Event) -> None:
        self._alt_alone = True

    def _alt_up(self, _event: tk.Event) -> str | None:
        if not self._alt_alone:
            return None
        self._alt_alone = False
        self._keyboard_open(0)
        return "break"

    def _other_key(self, event: tk.Event) -> None:
        if not str(getattr(event, "keysym", "")).startswith("Alt_"):
            self._alt_alone = False

    def _keyboard_open(self, index: int) -> str:
        self.root.after_idle(lambda: self.open(index, keyboard=True))
        return "break"

    def _menu_arrow(self, event: tk.Event, step: int) -> str | None:
        """Linux: Left in a top menu, or Right on an entry without a submenu, goes on to
        the next title's menu (Windows does this in its hook)."""
        menu = event.widget
        if self.open_index is None or menu is not self.menus[self.open_index]:
            return None
        if step > 0:
            active = menu.index("active")
            if active is not None and menu.type(active) == "cascade":
                return None
        self._next = ((self.open_index + step) % len(self.menus), True)
        menu.unpost()
        self.root.after_idle(self._open_next)
        return "break"

    # --- Posting -------------------------------------------------------------------------

    def open(self, index: int, keyboard: bool = False) -> None:
        """Post menu ``index`` under its title (with its first entry chosen when opened from
        the keyboard). On Windows this returns when the menu closes, after following any
        Left, Right or pointer move to another title."""
        if self.open_index is not None:
            return
        while True:
            self._next = None
            self.open_index = index
            self._paint_all()
            title = self.titles[index]
            x, y = title.winfo_rootx(), title.winfo_rooty() + title.winfo_height()
            menu = self.menus[index]
            if sys.platform == "win32":
                try:
                    self._post_windows(index, menu, x, y, keyboard)
                finally:
                    self.open_index = None
                    self._closed = (index, time.monotonic())
                if not self._paint_all() or self._next is None:
                    return
                index, keyboard = self._next
                continue
            self._post_other(menu, x, y, keyboard)
            return

    def _open_next(self) -> None:
        self.open_index = None
        if self._paint_all() and self._next is not None:
            index, keyboard = self._next
            self._next = None
            self.open(index, keyboard)

    def _post_other(self, menu: tk.Menu, x: int, y: int, keyboard: bool) -> None:
        def closed(_event: tk.Event) -> None:
            if self._next is None and self.open_index is not None:
                self.open_index = None
                self._paint_all()

        menu.bind("<Unmap>", closed)
        menu.tk.call("tk_popup", menu, x, y)
        if keyboard:
            try:
                menu.activate(0)
            except tk.TclError:
                pass

    def _post_windows(self, index: int, menu: tk.Menu, x: int, y: int,
                      keyboard: bool) -> None:
        """Post ``menu`` and watch its modal loop with a ``WH_MSGFILTER`` hook (it calls no
        Tk: Tk is inside ``TrackPopupMenu``)."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")
        kernel32 = ctypes.WinDLL("kernel32")
        lresult = ctypes.c_ssize_t
        hookproc = ctypes.WINFUNCTYPE(lresult, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hookproc, wintypes.HINSTANCE,
                                             wintypes.DWORD)
        user32.CallNextHookEx.restype = lresult
        user32.CallNextHookEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM,
                                          wintypes.LPARAM)
        user32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
        user32.SendMessageW.restype = lresult
        user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                        wintypes.LPARAM)
        user32.GetMenuItemCount.argtypes = (wintypes.HMENU,)
        user32.GetMenuState.argtypes = (wintypes.HMENU, wintypes.UINT, wintypes.UINT)
        user32.GetMenuState.restype = wintypes.UINT
        user32.GetSubMenu.argtypes = (wintypes.HMENU, ctypes.c_int)
        user32.GetSubMenu.restype = wintypes.HMENU
        user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumThreadWindows.argtypes = (wintypes.DWORD, enum_proc, wintypes.LPARAM)
        thread = kernel32.GetCurrentThreadId()
        rects = [(t.winfo_rootx(), t.winfo_rooty(), t.winfo_rootx() + t.winfo_width(),
                  t.winfo_rooty() + t.winfo_height()) for t in self.titles]
        count = len(self.menus)

        def open_menus() -> list[int]:
            """The HMENUs of this thread's visible menu windows (class ``#32768``)."""
            found: list[int] = []

            def each(hwnd: int, _param: int) -> bool:
                name = ctypes.create_unicode_buffer(16)
                user32.GetClassNameW(hwnd, name, 16)
                if name.value == "#32768" and user32.IsWindowVisible(hwnd):
                    handle = user32.SendMessageW(hwnd, _MN_GETHMENU, 0, 0)
                    if handle:
                        found.append(handle)
                return True

            user32.EnumThreadWindows(thread, enum_proc(each), 0)
            return found

        def chosen(handle: int) -> int | None:
            for position in range(max(0, user32.GetMenuItemCount(handle))):
                if user32.GetMenuState(handle, position, _MF_BYPOSITION) & _MF_HILITE:
                    return position
            return None

        def right_opens_submenu() -> bool:
            handles = open_menus()
            shown = set(handles)
            for handle in handles:       # the deepest menu: its choice opens nothing shown
                position = chosen(handle)
                sub = user32.GetSubMenu(handle, position) if position is not None else None
                if not sub or sub not in shown:
                    return bool(sub)
            return False

        def switch(target: int, by_keys: bool) -> int:
            self._next = (target % count, by_keys)
            user32.EndMenu()
            return 1

        def hook(code: int, wparam: int, lparam: int) -> int:
            try:
                if code == _MSGF_MENU and lparam:
                    msg = wintypes.MSG.from_address(lparam)
                    if msg.message == _WM_KEYDOWN and msg.wParam == _VK_LEFT \
                            and len(open_menus()) <= 1:
                        return switch(index - 1, True)
                    if msg.message == _WM_KEYDOWN and msg.wParam == _VK_RIGHT \
                            and not right_opens_submenu():
                        return switch(index + 1, True)
                    if msg.message in (_WM_MOUSEMOVE, _WM_LBUTTONDOWN):
                        px, py = msg.pt.x, msg.pt.y
                        if msg.message == _WM_MOUSEMOVE:  # only a real move: the pointer
                            if (px, py) == pointer[0]:    # may rest on another title
                                return user32.CallNextHookEx(None, code, wparam, lparam)
                            pointer[0] = (px, py)
                        for other, (x0, y0, x1, y1) in enumerate(rects):
                            if x0 <= px < x1 and y0 <= py < y1:
                                if other != index:
                                    return switch(other, False)
                                if msg.message == _WM_LBUTTONDOWN:   # its own title: close
                                    user32.EndMenu()
                                    return 1
            except Exception:  # noqa: BLE001  (never break the menu loop)
                pass
            return user32.CallNextHookEx(None, code, wparam, lparam)

        start = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(start))
        pointer = [(start.x, start.y)]
        callback = hookproc(hook)
        handle = user32.SetWindowsHookExW(_WH_MSGFILTER, callback, None, thread)
        if keyboard:                     # the menu loop reads it first: its first entry
            focus = user32.GetFocus()
            if focus:
                user32.PostMessageW(focus, _WM_KEYDOWN, _VK_DOWN, 0)
        try:
            menu.post(x, y)              # returns when the menu closes
        finally:
            if handle:
                user32.UnhookWindowsHookEx(handle)


__all__ = ["ALL_FILES", "AssetInfo", "AssetPane", "COPY_NAME", "CompletionPopup",
           "OutlineView",
           "DIRTY_MARK", "EDGE_STYLES", "ELLIPSIS", "HelpPane", "MAP_EMPTY", "MAP_OUT_OF_DATE",
           "MenuBar",
           "MAP_ZOOM_MAX", "MAP_ZOOM_MIN", "NO_PREVIEW", "PREVIEW_MAX_BYTES",
           "PREVIEW_MAX_PIXELS", "ProjectView", "RING_COLOR", "StatusBar", "StatusItem",
           "StoryMapView", "autohide", "elide", "node_text", "panel_header", "read_asset",
           "thumbnail_step"]
