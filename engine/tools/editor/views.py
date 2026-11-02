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
the blue strip along the window's bottom edge (F45 ``01`` §6.5, amended 2026-11-02). Colors
come from ``theme.THEME``.

Imports only ``engine.core``, ``engine.script``, ``engine.tools.editor`` and the standard
library (ADR-0008).
"""

import base64
import math
import os
import struct
import tkinter as tk
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from engine.core.errors import AssetTooLarge, EngineError
from engine.core.imageheader import image_dimensions
from engine.core.paths import GamePaths
from engine.script.imagenames import image_suffix, name_of
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
    LINK_KINDS,
    MARK_ENDING,
    MARK_START,
    Box,
    MapLayout,
    Notes,
    cycle_target,
    hidden_text,
    label_files,
    layout,
    neighbour,
)
from engine.tools.editor.outline import NO_OUTLINE
from engine.tools.editor.outline import Row as OutlineRow
from engine.tools.editor.syntax import PLAIN_COLOR
from engine.tools.editor.theme import THEME

DIRTY_MARK = "* "
MESSAGE_ID = "!message"                 # the one row shown when the game folder is gone
MUTED = THEME["muted"]
CHOSEN_BACKGROUND = THEME["list.activeSelection"]
CHOSEN_FOREGROUND = THEME["list.activeSelectionForeground"]
SELECTION_BACKGROUND = THEME["editor.selection"]
FOCUS_BORDER = THEME["focusBorder"]
NO_PREVIEW = "No preview for this file."
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


class ProjectView:
    """The project panel's tree (``04`` §7.4). ``on_select(ref)`` runs when the author
    selects a row; programmatic selection of the current row doesn't call it again."""

    def __init__(self, parent: tk.Misc, *, font: object, background: str,
                 on_select: Callable[[str], None]) -> None:
        self.frame = ttk.Frame(parent, style="Side.TFrame")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(self.frame, show="tree", selectmode="browse", height=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview,
                            style="Side.Vertical.TScrollbar")
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
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
            self.tree.insert(under, "end", iid=node.ref,
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

    def __init__(self, parent: tk.Misc) -> None:
        # A 1 px ring shows the keyboard focus (the frame itself takes it, for F6).
        self.frame = ttk.Frame(parent, padding=12, takefocus=1, style="Pane.TFrame")
        self.frame.bind("<FocusIn>", lambda _e: self.frame.configure(style="Focus.TFrame"),
                        add="+")
        self.frame.bind("<FocusOut>", lambda _e: self.frame.configure(style="Pane.TFrame"),
                        add="+")
        self.frame.columnconfigure(0, weight=1)
        self.title = ttk.Label(self.frame, text="", justify="left")
        self.title.grid(row=0, column=0, sticky="w")
        self.picture = ttk.Label(self.frame)
        self.picture.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.facts = ttk.Label(self.frame, text="", justify="left")
        self.facts.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.note = ttk.Label(self.frame, text="", foreground=MUTED, justify="left")
        self.note.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.copy_button = ttk.Button(self.frame, text=COPY_NAME, command=self.copy_name,
                                      state="disabled", style="Secondary.TButton")
        self.copy_button.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.ref: str | None = None
        self.info: AssetInfo | None = None
        self.photo: tk.PhotoImage | None = None
        self.step: int | None = None     # the subsample factor of the thumbnail shown

    def show(self, info: AssetInfo, *, box: tuple[int, int] | None = None) -> None:
        """Show ``info``; the thumbnail fits ``box`` (default: the pane's free space)."""
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


def panel_header(parent: tk.Misc, text: str, pad: int) -> ttk.Frame:
    """A panel's title strip: VS Code's small upper-case label (``PROBLEMS``, ``HELP``) on
    the panel-title background."""
    strip = ttk.Frame(parent, style="Header.TFrame")
    ttk.Label(strip, text=text.upper(), style="Header.TLabel").pack(
        side="left", padx=pad * 2, pady=(pad, pad))
    return strip


class HelpPane:
    """The Help pane beside the problems panel: the doc of the statement on the cursor's
    line (title, syntax, summary, example, ``Docs: …``), or ``No help for this line.``"""

    def __init__(self, parent: tk.Misc, *, font: tkfont.Font, code_font: tkfont.Font,
                 background: str, pad: int) -> None:
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        panel_header(self.frame, HELP_HEADING, pad).grid(row=0, column=0, columnspan=2,
                                                         sticky="ew")
        self.text = tk.Text(
            self.frame, wrap="word", width=1, height=1, font=font, background=background,
            foreground=PLAIN_COLOR, selectbackground=SELECTION_BACKGROUND,
            inactiveselectbackground=THEME["editor.inactiveSelection"], padx=pad * 2,
            pady=pad, highlightthickness=1, highlightbackground=background,
            highlightcolor=FOCUS_BORDER, borderwidth=0, takefocus=1, cursor="arrow")
        bold = tkfont.Font(root=parent, **{**font.actual(), "weight": "bold"})
        self._bold = bold
        text = self.text
        text.tag_configure("title", font=bold)
        text.tag_configure("syntax", font=code_font)
        text.tag_configure("example", font=code_font, lmargin1=pad * 2, lmargin2=pad * 2)
        text.tag_configure("docs", foreground=MUTED)
        text.tag_configure("none", foreground=MUTED)
        text.tag_configure("gap", spacing1=6)
        text.tag_configure("sel", foreground=PLAIN_COLOR)   # every color stays readable
        text.tag_raise("sel")
        text.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=text.yview)
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
        for index, (part, body) in enumerate(help_sections(doc)):  # type: ignore[arg-type]
            start = text.index("end-1c")
            text.insert("end", ("\n" if index else "") + body)
            tags = (part,) if index == 0 else (part, "gap")
            for tag in tags:
                text.tag_add(tag, start if index == 0 else f"{start}+1c", "end-1c")
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


# --- Story map (PR-F45-18, PR-F45-19, design §6.2) ----------------------------------------

MAP_MARGIN = 16
MAP_ZOOM_MIN = 50
MAP_ZOOM_MAX = 200
MAP_ZOOM_STEP = 25
MAP_NAME_PX = 13
MAP_DETAIL_PX = 11
BOX_FILL = THEME["map.box"]
BOX_OUTLINE = THEME["map.boxBorder"]
RING_COLOR = THEME["map.ring"]
RING_GAP = 3
LINK_COLOR = THEME["map.link"]
ENDING_COLOR = THEME["map.ending"]
CHAPTER_COLOR = THEME["map.chapter"]
MINIGAME_COLOR = THEME["map.minigame"]
LEGEND_STEP = 96
LEGEND_EXTRA = ("ending", "chapter", "minigame")      # after the link kinds (2026-11-02)
EDGE_STYLES: dict[str, tuple[tuple[int, ...], str]] = {   # told apart by line style
    "jump": ((), LINK_COLOR),           # solid
    "call": ((6, 4), LINK_COLOR),       # dashed
    "menu": ((2, 4), LINK_COLOR),       # dotted
}
ALL_FILES = "All files"
MAP_EMPTY = "No story map yet. It is drawn from the last check that loaded the script."
MAP_OUT_OF_DATE = "out of date: the last check didn't load the script"
TAG_BOX = "box"
TAG_EDGE = "edge"
TAG_RING = "ring"


class StoryMapView:
    """The Story map tab: a legend and a file filter above a scrolling canvas of label boxes
    and link arrows. Arrows move the focus ring (``storymap.neighbour``), Tab follows the
    focused box's links from where Tab started (``cycle_target``), and a click or Enter
    calls ``on_open(box)``; with Ctrl it calls ``on_open_tab(box)`` (2026-11-02). Zoom is
    50–200 %."""

    def __init__(self, parent: tk.Misc, *, background: str, family: str, mod: str,
                 on_open: Callable[[Box], None],
                 on_open_tab: Callable[[Box], None] | None = None) -> None:
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.on_open = on_open
        self.on_open_tab = on_open_tab or on_open
        bar = ttk.Frame(self.frame)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.name_font = tkfont.Font(root=parent, family=family, size=-MAP_NAME_PX)
        self.detail_font = tkfont.Font(root=parent, family=family, size=-MAP_DETAIL_PX)
        self.legend = tk.Canvas(bar, height=20,
                                width=(len(LINK_KINDS) + len(LEGEND_EXTRA)) * LEGEND_STEP,
                                background=background,
                                highlightthickness=0, borderwidth=0, takefocus=0)
        self.legend.pack(side="left")
        self._draw_legend()
        ttk.Label(bar, text="File:").pack(side="left", padx=(12, 4))
        self.file_choice = ttk.Combobox(bar, state="readonly", width=24, values=(ALL_FILES,))
        self.file_choice.set(ALL_FILES)
        self.file_choice.pack(side="left")
        self.file_choice.bind("<<ComboboxSelected>>", self._on_file, add="+")
        self.note = ttk.Label(bar, text="", foreground=MUTED)
        self.note.pack(side="left", padx=(12, 0))

        self.canvas = tk.Canvas(self.frame, background=background, highlightthickness=1,
                                borderwidth=0, takefocus=1, highlightcolor=RING_COLOR,
                                highlightbackground=background)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        vbar.grid(row=1, column=1, sticky="ns")
        hbar = ttk.Scrollbar(self.frame, orient="horizontal", command=self.canvas.xview)
        hbar.grid(row=2, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.labels: tuple[object, ...] = ()
        self.links: tuple[object, ...] = ()
        self.notes: dict[str, Notes] = {}
        self.stale = False
        self.file: str | None = None
        self.layout: MapLayout | None = None
        self.zoom = 100
        self.focused: int | None = None
        self.anchor: int | None = None   # where a run of Tab presses started
        self.edge_items: list[tuple[int, str]] = []    # (canvas item, link kind)
        self.ring: int | None = None

        canvas = self.canvas
        for key, way in (("<Left>", "left"), ("<Right>", "right"), ("<Up>", "up"),
                         ("<Down>", "down")):
            canvas.bind(key, lambda _e, w=way: self._arrow(w))
        canvas.bind("<Tab>", self._tab)
        for key in ("<Return>", "<KP_Enter>"):
            canvas.bind(key, lambda _e: self._open_focused())
            canvas.bind(f"<{mod}-{key[1:]}", lambda _e: self._open_focused(tab=True))
        canvas.bind("<Button-1>", self._click)
        canvas.bind(f"<{mod}-Button-1>", lambda e: self._click(e, tab=True))
        canvas.bind("<MouseWheel>", self._wheel)
        canvas.bind("<Shift-MouseWheel>", self._wheel_x)
        canvas.bind(f"<{mod}-MouseWheel>", self._wheel_zoom)
        canvas.bind("<FocusIn>", lambda _e: self._ensure_focus(), add="+")

    # --- Data -------------------------------------------------------------------------------

    def set_data(self, labels: Iterable[object], links: Iterable[object] | None,
                 stale: bool, notes: dict[str, Notes] | None = None) -> None:
        """New labels and links (the last good check's) and each label's ``Notes``; keeps
        the file filter while its file still holds labels, and the focus on the same label
        name."""
        self.labels = tuple(labels)
        self.links = tuple(links or ())
        self.notes = dict(notes or {})
        self.stale = stale
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
        self.layout = layout(self.links, self.labels, file=self.file, notes=self.notes)
        self.anchor = None
        self.focused = None
        if name is not None:
            self.focused = self.layout.index_of(name)
        if self.focused is None:
            self.focused = self._first_box()
        parts = [hidden_text(self.layout)]
        if self.stale:
            parts.append(MAP_OUT_OF_DATE)
        self.note.configure(text=" · ".join(p for p in parts if p))
        self.draw()

    def _first_box(self) -> int | None:
        if self.layout is None or not self.layout.boxes:
            return None
        found = self.layout.index_of("start")
        return 0 if found is None else found

    def focused_name(self) -> str | None:
        if self.layout is None or self.focused is None:
            return None
        return self.layout.boxes[self.focused].name

    # --- Drawing ----------------------------------------------------------------------------

    def _draw_legend(self) -> None:
        legend = self.legend
        for index, kind in enumerate(LINK_KINDS):
            dash, color = EDGE_STYLES[kind]
            x = 4 + index * 96
            options: dict = {"fill": color, "arrow": "last", "width": 1}
            if dash:
                options["dash"] = dash
            legend.create_line(x, 10, x + 36, 10, tags=("legend", f"legend-{kind}"), **options)
            legend.create_text(x + 42, 10, anchor="w", text=kind, fill=PLAIN_COLOR,
                               font=self.detail_font, tags=("legend", "legend-word"))
        x = 4 + len(LINK_KINDS) * LEGEND_STEP
        legend.create_rectangle(x, 3, x + 30, 17, outline=ENDING_COLOR, fill=BOX_FILL,
                                tags=("legend", "legend-ending"))
        legend.create_rectangle(x + 3, 6, x + 27, 14, outline=ENDING_COLOR,
                                tags=("legend",))
        legend.create_text(x + 36, 10, anchor="w", text="ending", fill=PLAIN_COLOR,
                           font=self.detail_font, tags=("legend", "legend-word"))
        x += LEGEND_STEP
        legend.create_text(x, 10, anchor="w", text="Aa", fill=CHAPTER_COLOR,
                           font=self.detail_font, tags=("legend", "legend-chapter"))
        legend.create_text(x + 24, 10, anchor="w", text="chapter", fill=PLAIN_COLOR,
                           font=self.detail_font, tags=("legend", "legend-word"))
        x += LEGEND_STEP
        legend.create_rectangle(x, 4, x + 18, 16, outline=MINIGAME_COLOR,
                                tags=("legend", "legend-minigame"))
        legend.create_text(x + 24, 10, anchor="w", text="minigame", fill=PLAIN_COLOR,
                           font=self.detail_font, tags=("legend", "legend-word"))

    def legend_words(self) -> list[str]:
        return [str(self.legend.itemcget(i, "text"))
                for i in self.legend.find_withtag("legend-word")]

    def _scale(self) -> float:
        return self.zoom / 100

    def box_rect(self, index: int) -> tuple[float, float, float, float]:
        """Box ``index``'s rectangle on the canvas at the current zoom."""
        assert self.layout is not None
        box = self.layout.boxes[index]
        s = self._scale()
        x0, y0 = MAP_MARGIN + box.x * s, MAP_MARGIN + box.y * s
        return x0, y0, x0 + BOX_WIDTH * s, y0 + BOX_HEIGHT * s

    def draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self.edge_items = []
        self.ring = None
        s = self._scale()
        self.name_font.configure(size=-max(6, round(MAP_NAME_PX * s)))
        self.detail_font.configure(size=-max(5, round(MAP_DETAIL_PX * s)))
        found = self.layout
        if found is None or not found.boxes:
            canvas.create_text(MAP_MARGIN, MAP_MARGIN, anchor="nw", text=MAP_EMPTY,
                               fill=MUTED, font=self.detail_font)
            canvas.configure(scrollregion=(0, 0, 1, 1))
            return
        for edge in found.edges:
            points = self._edge_points(edge.src, edge.dst)
            dash, color = EDGE_STYLES.get(edge.kind, ((), LINK_COLOR))
            options: dict = {"fill": color, "arrow": "last", "width": 1}
            if dash:
                options["dash"] = dash
            item = canvas.create_line(*points, tags=(TAG_EDGE, f"edge-{edge.kind}"), **options)
            self.edge_items.append((item, edge.kind))
        pad = 6 * s
        for index, box in enumerate(found.boxes):
            x0, y0, x1, y1 = self.box_rect(index)
            tags = (TAG_BOX, f"box{index}")
            start = MARK_START in box.marks
            ending = MARK_ENDING in box.marks
            canvas.create_rectangle(x0, y0, x1, y1, outline=ENDING_COLOR if ending
                                    else BOX_OUTLINE, fill=BOX_FILL,
                                    width=2 if start else 1, tags=(*tags, f"rect{index}"))
            if ending:                   # an end box: a second border inside the first
                inset = 3 * s
                canvas.create_rectangle(x0 + inset, y0 + inset, x1 - inset, y1 - inset,
                                        outline=ENDING_COLOR, tags=(*tags, f"inner{index}"))
            tag_x = x0
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
                marks = self.detail_font.measure(", ".join(box.marks)) + pad if box.marks else 0
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
            if box.marks:
                canvas.create_text(x1 - pad, y0 + 4 * s, anchor="ne", text=", ".join(box.marks),
                                   font=self.detail_font, fill=MUTED,
                                   tags=(*tags, f"marks{index}"))
        width = 2 * MAP_MARGIN + found.width * s
        height = 2 * MAP_MARGIN + found.height * s
        canvas.configure(scrollregion=(0, 0, width, height))
        self._draw_ring()

    def _edge_points(self, src: int, dst: int) -> list[float]:
        s = self._scale()
        ax0, ay0, ax1, ay1 = self.box_rect(src)
        bx0, by0, bx1, by1 = self.box_rect(dst)
        amid, bmid = (ay0 + ay1) / 2, (by0 + by1) / 2
        bend = 20 * s
        if src == dst:                   # a self-jump: a loop over the top right corner
            return [ax1 - 2 * bend, ay0, ax1 - 2 * bend, ay0 - 0.6 * bend,
                    ax1 + 0.6 * bend, ay0 - 0.6 * bend, ax1 + 0.6 * bend, amid, ax1, amid]
        if bx0 >= ax1:
            return [ax1, amid, bx0, bmid]
        if bx1 <= ax0:
            return [ax0, amid, bx1, bmid]
        return [ax1, amid, ax1 + bend, amid, bx1 + bend, bmid, bx1, bmid]   # same column

    def _draw_ring(self) -> None:
        canvas = self.canvas
        if self.ring is not None:
            canvas.delete(self.ring)
            self.ring = None
        if self.layout is None or self.focused is None:
            return
        x0, y0, x1, y1 = self.box_rect(self.focused)
        self.ring = canvas.create_rectangle(x0 - RING_GAP, y0 - RING_GAP, x1 + RING_GAP,
                                            y1 + RING_GAP, outline=RING_COLOR, width=2,
                                            tags=(TAG_RING,))

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
        if x0 - RING_GAP < left or x1 + RING_GAP > left + width:
            canvas.xview_moveto(max(0.0, (x0 - MAP_MARGIN) / total_w))
        if y0 - RING_GAP < top or y1 + RING_GAP > top + height:
            canvas.yview_moveto(max(0.0, (y0 - MAP_MARGIN) / total_h))

    # --- Keys, clicks, zoom -----------------------------------------------------------------

    def focus_box(self, index: int | None, *, from_tab: bool = False) -> None:
        if not from_tab:
            self.anchor = None
        self.focused = index
        self._draw_ring()
        if index is not None:
            self.see(index)

    def _ensure_focus(self) -> None:
        if self.focused is None:
            self.focus_box(self._first_box())

    def _arrow(self, way: str) -> str:
        if self.layout is not None and self.focused is not None:
            found = neighbour(self.layout, self.focused, way)
            if found is not None:
                self.focus_box(found)
        return "break"

    def _tab(self, _event: tk.Event | None = None) -> str:
        if self.layout is not None and self.focused is not None:
            anchor = self.anchor if self.anchor is not None else self.focused
            found = cycle_target(self.layout, anchor, self.focused)
            if found is not None:
                self.focus_box(found, from_tab=True)
                self.anchor = anchor
        return "break"

    def _open_focused(self, tab: bool = False) -> str:
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
        self.canvas.focus_set()
        found = self.box_at(event.x, event.y)
        if found is not None and self.layout is not None:
            self.focus_box(found)
            (self.on_open_tab if tab else self.on_open)(self.layout.boxes[found])

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


# --- Status bar (F45 01 §6.5, amended 2026-11-02, user: VS Code dark) ----------------------

ELLIPSIS = "…"
STATUS_ITEM_PAD = 7                     # px either side of an item's text, at 100 %


# --- Outline (2026-11-02, AC-F45-54) ---------------------------------------------------------

class OutlineView:
    """The Outline tab: a read-only tree of ``outline.Row`` rows. Enter or a double-click on
    a row with a place calls ``on_open(file, line)``. Sections start open."""

    def __init__(self, parent: tk.Misc, *,
                 on_open: Callable[[str, int], None]) -> None:
        self.frame = ttk.Frame(parent, padding=8)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.note = ttk.Label(self.frame, text=NO_OUTLINE, foreground=MUTED)
        self.note.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.tree = ttk.Treeview(self.frame, show="tree", selectmode="browse", height=1)
        self.tree.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.tag_configure("section", foreground=THEME["syntax.keyword"])
        self.tree.tag_configure("place", foreground=PLAIN_COLOR)
        self.tree.tag_configure("plain", foreground=MUTED)
        self.on_open = on_open
        self.places: dict[str, tuple[str, int]] = {}
        self.rows: tuple[OutlineRow, ...] = ()
        for key in ("<Return>", "<KP_Enter>", "<Double-Button-1>"):
            self.tree.bind(key, self._open, add="+")

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
    left and on the right, white on blue, one line high. Long texts are cut with ``…``
    (never wrapped): when the items don't fit, the one with the highest ``shrink`` gives up
    width first. Items take no keyboard focus; what they show is reachable elsewhere."""

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


__all__ = ["ALL_FILES", "AssetInfo", "AssetPane", "COPY_NAME", "CompletionPopup",
           "OutlineView",
           "DIRTY_MARK", "EDGE_STYLES", "ELLIPSIS", "HelpPane", "MAP_EMPTY", "MAP_OUT_OF_DATE",
           "MAP_ZOOM_MAX", "MAP_ZOOM_MIN", "NO_PREVIEW", "PREVIEW_MAX_BYTES",
           "PREVIEW_MAX_PIXELS", "ProjectView", "RING_COLOR", "StatusBar", "StatusItem",
           "StoryMapView", "autohide", "elide", "node_text", "panel_header", "read_asset",
           "thumbnail_step"]
