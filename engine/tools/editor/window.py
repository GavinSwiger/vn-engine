"""The Studio window: every Tk call of the editor (F44 ``04-technical.md`` §7.6,
``03-ui.md`` §1-§4; ``07`` I-3, I-6, I-13, I-14; F45 ``01`` §6.1, ``04`` §7.4, §7.5, ``07``
I-1, I-2).

``EditorWindow(root, paths)`` builds the window on an existing ``tk.Tk`` and opens the
game's files; ``run_editor`` (``engine/tools/editor/__init__.py``) creates the root and runs
the main loop. The left column holds the project panel (``views.ProjectView`` over
``files.project_tree``); the right area is a notebook whose pages come from ``TABS`` (one
row per tab: its strip entry, View menu row and Ctrl+digit key), with Problems and Help
below it. Each opened file keeps its own ``tk.Text`` for the session, so switching files
keeps the text and its undo history. Each editor ``Text``'s Tcl command is wrapped by a Tcl
proc (the ``rename`` proxy pattern IDLE uses): content commands mark the document dirty, and
every change or cursor move schedules one coalesced ``refresh`` that colors the visible
lines, redraws the line-number gutter, moves the current-line highlight, and updates the
start label and the status bar's cursor items. Word wrap is off (``04`` C3), so every row on
screen is one F02 line. The Insert menu, completion (Ctrl+Space, ``views.CompletionPopup``)
and the Help pane come from the statement doc registry (``assist``) and the last good
check's names. Colors and fonts come from ``theme`` through ``studiolook`` (VS Code Dark
Modern, F45 ``08``); every size is px at 100 % times ``scale`` (``theme.scale_of``).

This module keeps construction, the open files (``OpenFile`` records), the editor text,
refresh, save and close, and the document API other parts write through:
``record_for(ref)`` opens a document without showing it, and ``apply_plan(plan, verify)``
applies a ``scriptedit.Plan`` (F46's story edits, F47's Database and Game settings, F42's
``config.toml`` changes) with one undo step per file. ``EditorWindow`` mixes in the rest:

- ``studiomenus.StudioMenus``: the menus, from a table.
- ``editorkeys.EditorKeys``: key bindings from a table, focus order and F6.
- ``fileactions.FileActions``: Add files…, New script file, Rename, Delete, New game.
- ``checkwiring.CheckWiring``: checks, markers, the name index, the Problems panel, and
  ``on_check_done``.
- ``runwiring.RunWiring``: the Play bar (``playbar``), Play and Stop, and the poll loop
  (``join_runner``).
- ``mapwiring.MapWiring``: the Story map tab, its side pane, the layout file, map undo.
- ``guidepane.GuideWiring``: the Guide column at the right edge (F47 "Your first game").
- ``assistwiring.AssistWiring``: F48's Assistant pane, sharing the Guide's column (one at a
  time), its chat runs and their 50 ms poll.

Imports only ``engine.core``, ``engine.script`` (through ``document`` and ``syntax``), and
the standard library; never pygame (TR-F44-01).
"""

import math
import os
import queue
import subprocess  # noqa: F401  (kept: tests patch window.subprocess.Popen)
import time
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from tkinter import font as tkfont
from tkinter import messagebox, ttk  # noqa: F401  (kept: older tests patch it here)
from typing import Any

from engine.core.paths import GamePaths
from engine.script.assetgroups import CONFIG_REF
from engine.script.diagnostics import ScriptError
from engine.script.messages import show
from engine.script.statement_docs import StatementDoc
from engine.tools.editor import files, livemap, scenes, wheel
from engine.tools.editor import mapwatch as watchmod
from engine.tools.editor.mapwatch import FileNews, ScriptWatch, scan as scan_scripts
from engine.tools.editor.assist import (
    Context,
    auto_open,
    candidates,
    completion_context,
    help_for,
    insert_text,
    tag_help,
)
from engine.tools.editor.checker import CheckItem, CheckResult
from engine.tools.editor.config_help import (
    CONFIG_KINDS,
    auto_open_config,
    config_candidates,
    config_context,
    config_help,
    section_at,
)
from engine.tools.build import texts as build_texts
from engine.tools.editor.builddialog import build_running
from engine.tools.editor.dialogs import ask, show_error
from engine.tools.editor.document import (
    SaveError,
    ScriptDocument,
    open_config,
    open_document,
    save,
)
from engine.tools.editor.preview import POLL_INTERVAL_MS, PreviewRunner, PreviewState
from engine.tools.editor.scriptedit import Plan
from engine.tools.editor.syntax import (
    PLAIN_COLOR,
    SYNTAX_TAGS,
    TAG_COLORS,
    TAG_COMMENT,
    color_spans,
    indent_unit,
)
from engine.tools.editor.outline import outline
from engine.tools.editor.storyeditor import StoryEditor, apply_edits
from engine.tools.editor.storymap import MapHistory
from engine.tools.editor.appicon import set_app_icon
from engine.tools.editor.theme import (
    PANE_DRAG,
    STATUS_BAR_PX,
    THEME,
    dark_title_bar,
    make_fonts,
    scale_of,
    style_ttk,
)
from engine.tools.editor.views import (
    DIRTY_MARK,
    AssetPane,
    CompletionPopup,
    EmptyState,
    HelpPane,
    OutlineView,
    ProjectView,
    StatusBar,
    TabStrip,
    autohide,
    entry_enabled,
    panel_header,
    read_asset,
)
from engine.tools.editor.checkwiring import (  # re-exported: tests read window.<NAME>
    PROBLEMS_HEADING,
    PROBLEMS_HINT,
    CheckWiring,
    Paragraph,
    _marker_severity,
    check_row,
    check_summary,
)
from engine.tools.editor.editorkeys import EditorKeys
from engine.tools.editor.editormenu import EditorMenu
from engine.tools.editor.fileactions import (  # re-exported: tests read window.<NAME>
    ADD_BUTTON,
    CLASH_BUTTONS,
    FileActions,
    launch_studio,
)
from engine.tools.editor.mapwiring import GO_TO_LABEL_ASK, MapWiring
from engine.tools.editor.guidepane import GuideWiring
from engine.tools.editor.assistwiring import AssistWiring
from engine.tools.editor.docking import DockWiring
from engine.tools.editor.tabchoice import TabChoice
from engine.tools.editor import uiprefs
from engine.tools.editor.runwiring import (  # re-exported: tests read window.<NAME>
    START_VALUES_HEADING,
    STATUS_NOT_RUNNING,
    RunWiring,
    status_text,
)
from engine.tools.editor.studiolook import (  # re-exported: tests read window.<NAME>
    BACKGROUND,
    BOTTOM_MIN_WIDTH,
    CHOSEN_BACKGROUND,
    COMPLETION_PAGE,
    CURSOR_COLOR,
    CURSOR_WIDTH,
    EDITOR_MIN_HEIGHT,
    FOCUS_BORDER,
    FONT_MAX_PX,
    FONT_MIN_PX,
    FONT_PX,
    GUTTER_BACKGROUND,
    GUTTER_CURRENT,
    GUTTER_FOREGROUND,
    INACTIVE_SELECTION,
    JUMP_BACKGROUND,
    LEFT_MIN_WIDTH,
    LEFT_WIDTH,
    LINE_BACKGROUND,
    LINK_FOREGROUND,
    MARKER_CHARS,
    MARKER_COLORS,
    MARKER_LETTERS,
    MESSAGE_FOREGROUND,
    PANEL_BACKGROUND,
    PANEL_INSET,
    PROBLEMS_HEIGHT,
    PROBLEMS_MIN_HEIGHT,
    PROBLEMS_SHARE,
    SASH_WIDTH,
    SELECTION_BACKGROUND,
    START_VALUES_PX,
    TAB_SPACES,
    TAG_CHOSEN,
    TAG_GAP,
    TAG_JUMP,
    TAG_LINE,
    TAG_LINK,
    TAG_MARKER,
    TEXT_PAD,
    WINDOW_MIN_SIZE,
    WINDOW_SIZE,
    line_of,
    plural,
)
from engine.tools.editor.studiomenus import SHOW_WARNINGS, StudioMenus

# --- Text (03 §1.1, §2, §4; I-6, I-14; F45 01 §6) -------------------------------------------

TITLE_SUFFIX = " — vn-engine Studio"
PROJECT_HEADING = "Project"
TAB_EDITOR = "Editor"
TAB_MAP = "Story map"
TAB_ASSET = "File preview"                # was "Asset" (2026-11-04)
TAB_DATABASE = "Database"               # F47 W2
TAB_SETTINGS = "Game settings"          # F47 W4
TAB_OUTLINE = "Outline"                 # 2026-11-02, AC-F45-54
EDITOR_EMPTY_TITLE = "No story files yet"                       # 08 §9
EDITOR_EMPTY_HINT = "Your story is written in script files."
CLOSE_BUTTONS = ("Save all", "Don't save", "Cancel")
CLOSE_ESCAPE = 2                        # Cancel (I-6)
CHANGED_BUTTONS = ("Keep mine", "Use the file on disk")
CHANGED_ESCAPE = 0                      # Keep mine, never "Use the file on disk" (I-6)
PREVIEW_GLYPH = "▶ "               # ▶ before the preview state
EOL_NAMES = {"\n": "LF", "\r\n": "CRLF", "\r": "CR"}

HELP_LINE_CHARS = 4_096                 # Help and completion read this much of a line
OUTSIDE_CHECK_INTERVAL = 1.0            # seconds between disk checks on <FocusIn> (§7.2)
WATCH_POLL_MS = 50                      # F58 04 §7.2: the watch's mailbox, polled on Tk
WATCH_THREAD = True                     # tests turn the thread off and tick by hand
ASK_PAUSE_MS = 1_000                    # F58 PR-02, I-5: the question after a typing pause
CLOSED_DOCS_CHARS = 16 * 1024 * 1024    # F58 R2: closed files' watch documents kept
_MIN_COLORED_LINES = 60                 # lines colored per refresh when the view is unknown


# --- Tabs (F45 01 §6.1; F47 04 §3.4) --------------------------------------------------------

@dataclass(frozen=True)
class Tab:
    """One page of the right area's notebook. Its place in ``TABS`` is its strip position
    and its key (Ctrl+1 for the first); the View menu lists it there too. ``build``,
    ``focus``, ``empty`` and ``on_show`` name ``EditorWindow`` attributes (dotted paths are
    followed), read when used, so tests may patch them."""

    name: str                   # what the code calls the page: ``select_tab("map")``
    title: str                  # the strip and View menu text
    icon: str                   # ``icons`` name on the strip
    build: str                  # method: () -> the page widget, made on ``self.notebook``
    focus: str                  # the widget Ctrl+digit and F6 land on
    empty: str                  # its ``views.EmptyState`` (its button is the stop instead)
    on_show: str | None = None  # method run when the page is shown, and when the name
    #                             index changes while it shows


# The user's order (F47 04 §19): Editor · Story map · Database · Game settings · Asset ·
# Outline. Database and Game settings join here in F47 W2/W4 (one row each).
TABS: tuple[Tab, ...] = (
    Tab("editor", TAB_EDITOR, "editor", "_build_editor_tab", "text", "editor_empty"),
    Tab("map", TAB_MAP, "storymap", "_build_map_tab", "map_canvas", "story_map.empty",
        on_show="refresh_story_map"),
    Tab("database", TAB_DATABASE, "database", "_build_database_tab", "database.focus_widget",
        "database.empty", on_show="refresh_database"),
    Tab("settings", TAB_SETTINGS, "settings", "_build_settings_tab", "settings.focus_widget",
        "settings.empty", on_show="refresh_settings"),
    Tab("asset", TAB_ASSET, "image", "_build_asset_tab", "asset_pane.frame",
        "asset_pane.empty"),
    Tab("outline", TAB_OUTLINE, "outline", "_build_outline_tab", "outline_view.tree",
        "outline_view.empty", on_show="refresh_outline"),
)

# The Tcl side of the change hook: forward to the renamed widget command (errors propagate
# unchanged, so Tk's own ``catch`` in its bindings works), then notify Python.
_PROXY_PROC = r"""
proc %(widget)s {command args} {
    set result [%(original)s $command {*}$args]
    switch -exact -- $command {
        insert - delete - replace { %(notify)s 1 }
        mark {
            if {[lindex $args 0] eq "set" && [lindex $args 1] eq "insert"} { %(notify)s 0 }
        }
    }
    return $result
}
"""


def window_title(game_name: str, dirty: bool) -> str:
    """``<folder name> — vn-engine editor``, with ``* `` in front while any file is unsaved
    (UI-F44-02). Never a path."""
    return (DIRTY_MARK if dirty else "") + game_name + TITLE_SUFFIX


def close_message(refs: Sequence[str]) -> str:
    """The close dialog's text (03 §2.2, I-14)."""
    head = f"Save changes to {plural(len(refs), 'file')} before closing?"
    return head + "\n\n" + "\n".join(show(ref) for ref in refs)


def changed_message(ref: str) -> str:
    """The outside-change dialog's text (03 §2.2, PR-F44-08)."""
    return f"`{show(ref)}` changed on disk while you were editing it. Keep which version?"


def indent_text(unit: str) -> str:
    """The status bar's indent item: ``Spaces: 4``, or ``Tab Size: 4`` for a tab."""
    return f"Tab Size: {TAB_SPACES}" if unit == "\t" else f"Spaces: {len(unit)}"


def probe_astral_columns(root: tk.Misc) -> int:
    """I-3: how many index columns this Tk counts for one character outside the BMP
    (2 on Tk 8.6, 1 where Tk stores full code points)."""
    scratch = tk.Text(root)
    try:
        scratch.insert("1.0", "\U0001F600")
        return int(scratch.index("end-1c").split(".")[1])
    finally:
        scratch.destroy()


@dataclass
class OpenFile:
    """One file in the editor: an editable document, or a read-only message."""

    ref: str
    widget: tk.Text
    doc: ScriptDocument | None = None
    error: ScriptError | None = None
    stamp: tuple[int, int] | None = None    # disk stamp of a read-only file
    marks: dict[str, CheckItem] = field(default_factory=dict)   # Tk mark -> its check item
    changes: int = 0                        # F46: content changes, counted as they happen
    outside_stamp: tuple[int, int] | None = None    # F58: changed on disk, not yet asked

    @property
    def editable(self) -> bool:
        return self.doc is not None

    @property
    def dirty(self) -> bool:
        return self.doc is not None and self.doc.dirty


class EditorWindow(StudioMenus, EditorKeys, EditorMenu, FileActions, CheckWiring, RunWiring,
                   MapWiring, AssistWiring, GuideWiring, DockWiring, TabChoice):
    """Studio on ``root`` for the game at ``paths`` (``03`` §1.1, F45 ``01`` §6.1).
    ``runner`` is the preview runner and ``check_runner`` the check runner; tests pass
    fakes (F45 ``07`` I-2)."""

    tabs: tuple[Tab, ...] = TABS

    def __init__(self, root: tk.Tk, paths: GamePaths, *,
                 runner: PreviewRunner | None = None,
                 check_runner: object | None = None) -> None:
        self.root = root
        self.paths = paths
        self.game_name = paths.root.name
        self.mod = "Command" if root.tk.call("tk", "windowingsystem") == "aqua" else "Control"
        self.astral_columns = probe_astral_columns(root)
        self.refs: list[str] = []           # the Script group's files, in panel order
        self.project: files.ProjectTree | None = None
        self.game_missing = False
        self.files: dict[str, OpenFile] = {}
        self.current: OpenFile | None = None
        self.closed = False
        self._empty_widget: tk.Text | None = None
        self._shown: tk.Text | None = None  # the editor widget gridded on screen
        # The Story map's side editor (2026-11-02): a Tk peer of the current file's widget.
        self.side_text: tk.Text | None = None
        self._side_source: tk.Text | None = None
        self._side_open = False
        self._side_width: int | None = None     # the author's width, kept for the session
        self.side_tab = "script"            # F46 C1: the tab a box opens on, per window (G12)
        self.story: StoryEditor | None = None
        self._context_at: tuple[int, int] | None = None   # New scene here's map point
        self.last_context: tk.Menu | None = None
        # F46 step 4 (04 §6.8–6.10): the map history, and the layout file (read at the first
        # draw; written LAYOUT_SAVE_MS after the last place change and on close; a link
        # found reading or writing stops writes for this window).
        self.map_history = MapHistory()
        self._layout_read = False
        self._layout_writable = True
        self._layout_dirty = False
        self._layout_save_id: str | None = None
        self._suppress = False              # loading text: not an author edit
        self._refresh_id: str | None = None
        self._label_line: int | None = None
        self._jump_line: int | None = None
        self._last_outside_check = -math.inf
        self._checking_outside = False
        self.runner = runner if runner is not None else PreviewRunner()
        self.preview_state = PreviewState.NOT_RUNNING
        self.paragraphs: list[Paragraph] = []
        self._chosen: int | None = None
        self._poll_id: str | None = None
        # Checks (F45 07 I-1, I-2): load-only until the author's first Preview, Save or
        # Check now in this window; ``edit_serial`` goes up on every content change.
        if check_runner is None:
            from engine.tools.editor.checker import CheckRunner
            check_runner = CheckRunner(paths.root)
        self.check_runner = check_runner
        self.armed = False
        self.edit_serial = 0
        self.check_result: CheckResult | None = None    # the newest finished check
        self.check_running = False          # asked for and not finished, timed out or crashed
        self._check_failure: str | None = None          # the timeout or crash line
        self._check_serial = -1             # edit_serial of the newest request
        self._check_unsaved = False         # the newest request couldn't carry unsaved text
        self._debounce_id: str | None = None
        self._check_status_shown: str | None = None
        # Run with each applied check's result, after the panel and markers (F47 04 §3.4).
        self.on_check_done: list[Callable[[CheckResult], object]] = []
        # Runners polled with the preview's and the check's, and stopped on close.
        self.runners: list[tuple[object, Callable[[list], object]]] = []
        self._panel_view: tuple[str, object] = ("hint", PROBLEMS_HINT)   # preview's part
        # View menu toggle, the author's choice in every game (``uiprefs``).
        self.show_warnings = tk.BooleanVar(
            master=root, value=bool(uiprefs.value("show_warnings", True)))
        # Add files… runs its copies on a worker thread (04 §7.5 Add).
        self.adding = False
        self._add_queue: "queue.Queue[files.AddOutcome | None]" = queue.Queue()
        self._add_outcomes: list[files.AddOutcome] = []
        self._add_id: str | None = None
        # The last good check's name index (kind -> NameEntry rows) and label links (F45
        # 04 §4.2): step 4 sets them as results arrive, and completion and the story map
        # read them. ``check_stale`` marks the map "out of date" (a check that didn't load).
        self._check_names: dict = {}
        self._check_links: tuple = ()
        self._check_stale = False
        self._map_dirty = True
        # F46 (04 §6.1): each open script's scene index, the label digests each one counts
        # as checked, and the digests sent with the newest check request (its serial).
        self.scene_indexes: dict[str, scenes.SceneIndex] = {}
        self._checked: dict[str, dict[scenes.Key, bytes]] = {}
        self._check_snapshot: tuple[int, dict[str, dict[scenes.Key, bytes]], dict] | None = None
        # F58 (04 §7.4): the follow clock (80 ms debounce, 250 ms max wait), what asked for
        # the update in hand, and the map's live status line (S1-S8).
        self.follow_clock = self._make_follow_clock()
        self._follow_source = "typing"
        self._now_source: str | None = None
        self._follow_throttle = False
        self._after_throttle = False
        self.map_line = self._make_map_line()
        # F58 W4 (04 §7.1-7.3, §7.11): the watch, its update batch, the decoded documents
        # of open clean files waiting to reload, the stamps of the closed files indexed
        # from disk, what the next map update brings from disk (S1), the capped files
        # (S6), S4's pending check, Q2's pending adoption, and the dirty-file question.
        self.watch: ScriptWatch | None = None
        self._watch_id: str | None = None
        self._batch_id: str | None = None
        self._ask_id: str | None = None
        self._batch = livemap.UpdateBatch()
        self._news_docs: dict[str, ScriptDocument] = {}
        self._closed_docs: dict[str, ScriptDocument] = {}   # R2: opened without a read
        self._closed_stamps: dict[str, tuple[int, int]] = {}
        self._disk_refs: dict[str, None] = {}
        self._capped: set[str] = set()
        self._big = False
        self._adopt: tuple[int, dict, dict] | None = None
        self._map_shown: tuple | None = None    # the data the map last drew
        self._help_key: tuple | None = None
        self._help_sash_placed = False
        self._line_shown: tuple[str, int] | None = None     # (widget, line) highlighted
        self._indent_key: tuple | None = None
        self._indent_shown = ""

        self._make_fonts()
        self._build_layout()
        self._build_hot_reload()            # F39: before the Run menu's toggle row
        self._build_menus()
        self._build_tab_choice()            # which tabs the strip shows (``tabchoice``)
        self._bind_keys()
        self.refresh_project()
        if self.refs:
            self.open_file(self.refs[0])
        else:
            self._show_empty()
        self._update_title()
        self._start_watch()
        root.bind("<Map>", self._on_map_event, add="+")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.mod == "Command":
            root.createcommand("tk::mac::Quit", self.on_close)
        root.bind("<FocusIn>", self._on_focus_in, add="+")
        self.text.focus_set()
        self._poll_id = root.after(POLL_INTERVAL_MS, self._poll_preview)
        self.request_check()
        self._icons = set_app_icon(root)
        dark_title_bar(root)

    # --- Building ---------------------------------------------------------------------------

    def _make_fonts(self) -> None:
        """08 §4: the type scale in px times ``scale``; the editor's code font zooms."""
        self.scale = scale_of(self.root)
        self.fonts = make_fonts(self.root, self.scale)
        self.font_px = FONT_PX
        self.font = self.fonts["code"]
        self.font.configure(size=-self._px(FONT_PX))
        self.start_values_font = self.fonts["codeSmall"]
        self.start_values_font.configure(size=-self._px(START_VALUES_PX))
        self.ui_font = tkfont.nametofont("TkDefaultFont", root=self.root)

    def _px(self, value: float) -> int:
        """``value`` px at 100 % in screen pixels."""
        return round(value * self.scale)

    def _build_layout(self) -> None:
        root = self.root
        px = self._px
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(px(WINDOW_SIZE[0]), screen_w)
        height = min(px(WINDOW_SIZE[1]), max(px(WINDOW_MIN_SIZE[1]), screen_h - px(48)))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(*(px(size) for size in WINDOW_MIN_SIZE))
        root.configure(background=BACKGROUND)
        self._theme_fonts = style_ttk(root, self.fonts, self.scale)
        wheel.install(root)                 # the wheel scrolls whatever is under the pointer

        # The status bar is packed first, so it keeps its line at the minimum size.
        self._build_status_bar()
        self._build_play_bar()             # F47: under the menu bar, across the window
        sash, sash_width = THEME["sash"], px(SASH_WIDTH)
        self.hpane = tk.PanedWindow(root, **PANE_DRAG, orient="horizontal", sashwidth=sash_width,
                                    borderwidth=0, sashrelief="flat", background=sash)
        self.hpane.pack(fill="both", expand=True)
        # Every pane is a child of ``root``, so any dock can hold it (``docking``).
        self.left = ttk.Frame(root, width=px(LEFT_WIDTH), style="Side.TFrame")
        self.vpane = tk.PanedWindow(self.hpane, **PANE_DRAG, orient="vertical", sashwidth=sash_width,
                                    borderwidth=0, sashrelief="flat", background=sash)
        self.hpane.add(self.vpane, minsize=px(LEFT_MIN_WIDTH), stretch="always")
        self.hpane.bind("<Configure>", self._limit_left_column, add="+")
        self.hpane.bind("<ButtonRelease-1>", self._limit_left_column, add="+")
        self.hpane.bind("<B1-Motion>", self._limit_left_column, add="+")

        self._build_left_column()
        # F45 01 §6.1: the right area is a notebook with fixed tabs (no Ctrl+Tab traversal:
        # Ctrl+digit switches them). 08 §7: its own tabs are hidden under the tab strip.
        self.tab_area = ttk.Frame(self.vpane)
        self.notebook = ttk.Notebook(self.tab_area, takefocus=0, style="Tabless.TNotebook")
        for tab in self.tabs:
            self.notebook.add(getattr(self, tab.build)(), text=tab.title)
        self.tab_strip = TabStrip(self.tab_area, self.notebook, tuple(
            (tab.title, tab.icon) for tab in self.tabs), font=self.fonts["body"],
            scale=self.scale)
        self.tab_strip.frame.pack(side="top", fill="x")
        self.notebook.pack(side="top", fill="both", expand=True)
        self.vpane.add(self.tab_area, minsize=px(EDITOR_MIN_HEIGHT), stretch="always")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")
        # Below the notebook: Problems (60 %) and Help (40 %) with a draggable divider (both
        # on the chrome tone, so their sash is the divider color).
        self.bottom = tk.PanedWindow(self.vpane, **PANE_DRAG, orient="horizontal", sashwidth=sash_width,
                                     borderwidth=0, sashrelief="flat",
                                     background=THEME["divider"])
        self.problems_frame = ttk.Frame(root, style="Side.TFrame")
        self.help_pane = HelpPane(root, font=self.ui_font,
                                  code_font=self.start_values_font,
                                  title_font=self.fonts["bodyStrong"],
                                  background=PANEL_BACKGROUND, scale=self.scale)
        self.help_text = self.help_pane.text
        self.bottom.bind("<Configure>", self._place_help_sash, add="+")
        self.help_pane.show(None)
        self.popup = CompletionPopup(self.root, font=self.font)
        self.popup.on_pick = lambda index: self.accept_completion(index)
        self._build_editor_area()
        self._build_side_pane()
        self._build_problems_panel()
        self._build_guide()                 # F47: the Guide column, right of the tabs
        self._build_assistant()             # F48: the Assistant pane shares that column
        self._build_docks()                 # every pane in its dock (``docking``)

    def _build_left_column(self) -> None:
        """The chrome-toned left column (08 §7): PROJECT's header with "+ Add files…" as a
        ghost button, and the tree below it (F47: the Play bar replaced F44's start values
        and Preview button here)."""
        left, px = self.left, self._px
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.grid_propagate(False)
        head = panel_header(left, PROJECT_HEADING, self.scale)
        head.grid(row=0, column=0, sticky="ew")
        self.add_button = ttk.Button(head, text=f"+ {ADD_BUTTON}", command=self.add_files,
                                     takefocus=0, style="Chrome.Ghost.TButton")
        self.add_button.pack(side="right", padx=(0, px(4)))
        self.project_view = ProjectView(left, font=self.ui_font, background=BACKGROUND,
                                        on_select=self._on_tree_select, scale=self.scale)
        self.project_view.frame.grid(row=1, column=0, sticky="nsew")
        self.tree = self.project_view.tree
        for key in ("<Return>", "<KP_Enter>"):
            self.tree.bind(key, self._focus_editor)
        self.tree.bind("<F2>", lambda _e: self._break(self.rename_selected))
        self.tree.bind("<Delete>", lambda _e: self._break(self.delete_selected))
        self._bind_project_menu()

    def _build_status_bar(self) -> None:
        """F45 01 §6.5 (amended 2026-11-02): the game folder, the check's counts and message,
        and the preview state on the left; the cursor's line and column, the indent, the
        encoding and the line ending on the right. The check items focus Problems when
        clicked; the folder name focuses the project panel."""
        font = self.fonts["small"]
        height = max(self._px(STATUS_BAR_PX), font.metrics("linespace") + 4)
        bar = self.status_bar = StatusBar(self.root, font=font, height=height,
                                          scale=self.scale)
        self.game_item = bar.add(text=self.game_name, shrink=2,
                                 on_click=lambda: self.tree.focus_set())
        self.check_counts = bar.add(on_click=self.focus_problems)
        self.check_status = bar.add(shrink=3, on_click=self.focus_problems)
        self.status_label = bar.add(prefix=PREVIEW_GLYPH, shrink=1, text=STATUS_NOT_RUNNING)
        self.story_status = bar.add(shrink=4)  # F46: a selected choice arrow's full text
        self.cursor_item = bar.add(side="right")
        self.indent_item = bar.add(side="right")
        self.encoding_item = bar.add(side="right")
        self.eol_item = bar.add(side="right")
        bar.frame.pack(side="bottom", fill="x")
        bar.divider.pack(side="bottom", fill="x")

    def _build_editor_tab(self) -> tk.Widget:
        """The Editor tab's page; its gutter and scrollbars come in ``_build_editor_area``
        once the fonts and the bottom panes exist."""
        self.editor_frame = ttk.Frame(self.notebook)
        return self.editor_frame

    def _build_database_tab(self) -> tk.Widget:
        """F47 W2/W3: the Database (``database.DatabasePane``)."""
        from engine.tools.editor.database import DatabasePane
        self.database = DatabasePane(self, self.notebook)
        from engine.tools.editor.minigameview import attach    # F47 W8: Minigame data
        attach(self.database)
        return self.database.frame

    def refresh_database(self) -> None:
        if not self.closed:
            self.database.refresh()

    def _build_settings_tab(self) -> tk.Widget:
        """F47 W4: Game settings (``settingsview.SettingsPane``)."""
        from engine.tools.editor.settingsview import SettingsPane
        self.settings = SettingsPane(self, self.notebook)
        return self.settings.frame

    def refresh_settings(self) -> None:
        if not self.closed:
            self.settings.refresh()

    def _build_asset_tab(self) -> tk.Widget:
        self.asset_pane = AssetPane(self.notebook, scale=self.scale, on_add=self.add_files,
                                    add_label=ADD_BUTTON)
        return self.asset_pane.frame

    def _build_outline_tab(self) -> tk.Widget:
        self.outline_view = OutlineView(self.notebook, on_open=self.jump_to, scale=self.scale,
                                        on_check=self.check_now)
        return self.outline_view.frame

    def _build_editor_area(self) -> None:
        frame = self.editor_frame
        key = "Cmd" if self.mod == "Command" else "Ctrl"
        self.editor_empty = EmptyState(frame, icon="script", title=EDITOR_EMPTY_TITLE,
                                       hint=EDITOR_EMPTY_HINT,
                                       button=f"New script file ({key}+N)",
                                       command=self.new_script_file, scale=self.scale)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)
        self.gutter = tk.Canvas(frame, width=self._gutter_width(1), background=GUTTER_BACKGROUND,
                                highlightthickness=0, borderwidth=0, takefocus=0)
        self.gutter.grid(row=0, column=0, sticky="ns")
        wheel.register(self.gutter, lambda units: self.text.yview_scroll(units, "units")
                       if getattr(self, "text", None) is not None else False)
        self.vbar = ttk.Scrollbar(frame, orient="vertical")
        self._vbar_set = autohide(self.vbar, row=0, column=2, sticky="ns")
        self.hbar = ttk.Scrollbar(frame, orient="horizontal")
        self._hbar_set = autohide(self.hbar, row=1, column=1, sticky="ew")

    # --- Tabs ---------------------------------------------------------------------------------

    def tab_index(self, name: str) -> int:
        """The notebook index of the tab called ``name`` in ``tabs``."""
        return next(i for i, tab in enumerate(self.tabs) if tab.name == name)

    def current_tab(self) -> str:
        """The name of the tab on screen."""
        return self.tabs[self.notebook.index("current")].name

    def select_tab(self, name: str) -> None:
        """Put the tab called ``name`` on screen (the focus stays where it is); a hidden tab
        comes back."""
        if hasattr(self, "tabs_hidden"):
            self.reveal_tab(name)
        self.notebook.select(self.tab_index(name))

    def _attr(self, path: str) -> Any:
        """``self.a.b`` for the path ``"a.b"`` (a ``Tab`` field)."""
        value: Any = self
        for part in path.split("."):
            value = getattr(value, part)
        return value

    def show_tab(self, index: int) -> None:
        """Ctrl+1, Ctrl+2, …: the tab at ``index``, with the keyboard focus in it."""
        tab = self.tabs[index]
        if tab.name == "editor" and self._side_has_focus():
            self.side_to_editor()           # the Editor tab at the side editor's cursor
            return
        if hasattr(self, "tabs_hidden"):
            self.reveal_tab(tab.name)
        self.notebook.select(index)
        if tab.on_show is not None:
            getattr(self, tab.on_show)()
        self._tab_widget().focus_set()

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        self.close_completion()
        self._schedule_refresh()            # the gutter of the editor now on screen
        if not self.closed:
            on_show = self.tabs[self.notebook.index("current")].on_show
            if on_show is not None:
                getattr(self, on_show)()

    def _place_help_sash(self, event: tk.Event) -> None:
        """Problems 60 %, Help 40 % at first; the author's drag is kept after that."""
        if self._help_sash_placed or event.width <= 1 or not hasattr(self, "dock_of"):
            return
        self._even_docks()

    def zoom_view(self, step: int) -> None:
        """Ctrl+= / Ctrl+- / Ctrl+0: the story map's zoom on the Story map tab, else the
        editor text's."""
        if self.current_tab() == "map" and not self._side_has_focus():
            self.story_map.zoom_by(step)
        else:
            self.zoom(step)

    def _limit_left_column(self, _event: tk.Event | None = None) -> None:
        """The left column stays between 160 px and half the window (03 §1.1)."""
        total = self.hpane.winfo_width()
        dock = getattr(self, "left_dock", None)
        if total <= 1 or dock is None or not self.hpane.panes() or \
                str(self.hpane.panes()[0]) != str(dock):
            return
        x, y = self.hpane.sash_coord(0)
        limit = max(self._px(LEFT_MIN_WIDTH), total // 2)
        if x > limit:
            self.hpane.sash_place(0, limit, y)

    # --- Editor widgets ---------------------------------------------------------------------

    def _text_options(self, *, editable: bool) -> dict[str, object]:
        return dict(
            wrap="none", undo=editable, maxundo=-1, autoseparators=True,
            width=1, height=1, font=self.font, padx=self._px(TEXT_PAD),
            pady=self._px(TEXT_PAD), background=BACKGROUND, foreground=PLAIN_COLOR,
            insertbackground=CURSOR_COLOR, insertwidth=self._px(CURSOR_WIDTH),
            selectbackground=SELECTION_BACKGROUND,
            inactiveselectbackground=INACTIVE_SELECTION, highlightthickness=1,
            highlightbackground=BACKGROUND, highlightcolor=FOCUS_BORDER, borderwidth=0,
            tabs=(self._tab_width(),))

    def _make_text(self, *, editable: bool) -> tk.Text:
        widget = tk.Text(self.editor_frame, **self._text_options(editable=editable))
        # Made first, so the jump highlight and the selection lie over it.
        widget.tag_configure(TAG_LINE, background=LINE_BACKGROUND)
        for tag in SYNTAX_TAGS:
            widget.tag_configure(tag, foreground=TAG_COLORS[tag])
        widget.tag_configure(TAG_JUMP, background=JUMP_BACKGROUND)
        # Selected text is plain: no Dark+ syntax color reaches 4.5:1 on the selection.
        widget.tag_configure("sel", foreground=PLAIN_COLOR)
        widget.tag_raise("sel")
        widget.configure(yscrollcommand=lambda first, last, w=widget: self._on_yscroll(
            w, first, last), xscrollcommand=lambda first, last, w=widget: self._on_xscroll(
            w, first, last))
        widget.bind("<Configure>", lambda _e: self._schedule_refresh(), add="+")
        tags = list(widget.bindtags())
        tags.insert(1, self._editor_bindtag)
        widget.bindtags(tuple(tags))
        return widget

    def _install_change_hook(self, widget: tk.Text, owner: tk.Text | None = None) -> None:
        """Wrap the widget's Tcl command (§7.6 "Change hook"). The record is found by its
        widget, so a renamed file keeps its hook (F45 ``04`` §7.5 Rename step 3); a peer
        reports as its ``owner``."""
        name = str(widget)
        original = name + "_vn_original"
        notify = widget.register(lambda content, w=owner or widget: self._on_change(
            w, content == "1"))
        widget.tk.call("rename", name, original)
        widget.tk.eval(_PROXY_PROC % {"widget": name, "original": original, "notify": notify})

    def _open_any(self, ref: str) -> ScriptDocument | ScriptError:
        """``open_config`` for ``config.toml``, else ``open_document``."""
        if ref == CONFIG_REF:
            return open_config(self.paths)
        return open_document(self.paths, ref)

    def _new_record(self, ref: str) -> OpenFile:
        # F58 R2: a closed file the watch has just decoded opens from that document while
        # its stamp still holds (Apply over large closed files reads nothing on Tk).
        kept = self._closed_docs.pop(ref, None)
        result = kept if kept is not None and self._stat(kept.real_path) == kept.stamp \
            else self._open_any(ref)
        if isinstance(result, ScriptDocument):
            widget = self._make_text(editable=True)
            record = OpenFile(ref, widget, doc=result)
            self._install_change_hook(widget)
            self._set_text(record, result.text)
            result.text = ""
            widget.mark_set("insert", "1.0")
            self._place_marks(record)
            self._baseline(record)
            return record
        widget = self._make_text(editable=False)
        widget.configure(wrap="word", foreground=MESSAGE_FOREGROUND)
        widget.insert("1.0", result.format())
        widget.configure(state="disabled")
        return OpenFile(ref, widget, error=result, stamp=self._stat(self.paths.root / ref))

    def _set_text(self, record: OpenFile, text: str) -> None:
        """Replace a document's whole text as loaded from disk: not an edit, no undo."""
        widget = record.widget
        self._suppress = True
        try:
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        finally:
            self._suppress = False
        widget.edit_reset()
        widget.edit_modified(False)

    @property
    def text(self) -> tk.Text:
        """The editor widget on screen: the side editor's peer on the Story map tab."""
        side = self._side_active()
        if side is not None:
            return side
        if self.current is not None:
            return self.current.widget
        assert self._empty_widget is not None
        return self._empty_widget

    def _editor_widgets(self) -> list[tk.Text]:
        widgets = [record.widget for record in self.files.values()]
        if self._empty_widget is not None:
            widgets.append(self._empty_widget)
        return widgets

    def _show(self, widget: tk.Text) -> None:
        if widget is not self._shown:
            self.close_completion()
            shown = self._shown
            had_focus = shown is not None and self.root.focus_get() is shown
            if shown is not None:
                shown.grid_remove()
            widget.grid(row=0, column=1, sticky="nsew")
            self._shown = widget
            # No scripts at all: the empty state over the Editor tab (08 §9).
            if widget is self._empty_widget and not self.refs:
                self.editor_empty.show(self.editor_frame)
            else:
                self.editor_empty.hide()
            self.vbar.configure(command=widget.yview)
            self.hbar.configure(command=widget.xview)
            self._vbar_set(*widget.yview())
            self._hbar_set(*widget.xview())
            if had_focus:
                widget.focus_set()
        if self._side_open and self._side_source is not widget:
            if self.current is not None and self.current.editable \
                    and widget is self.current.widget:
                self._make_side_peer(widget)    # the side editor follows the file
                if self.side_tab == "events":
                    self.root.after_idle(self._follow_events)
            else:
                self.close_side(focus_map=False)
        self._label_line = None
        self._schedule_refresh()

    def _show_empty(self) -> None:
        if self._empty_widget is None:
            self._empty_widget = self._make_text(editable=False)
            self._empty_widget.configure(state="disabled")
        self.current = None
        self._show(self._empty_widget)

    # --- Project panel (F45 PR-F45-01, 04 §7.4) ---------------------------------------------

    def refresh_project(self) -> None:
        """List the game folder again into the project panel. ``self.refs`` becomes the
        Script group's files in panel order. A missing game folder shows one gray row and
        turns the file operations off (design edge cases, AC-F45-26)."""
        self.paths.invalidate_listings()
        project = files.project_tree(self.paths)
        self.game_missing = isinstance(project, files.Refusal)
        self.project = None if isinstance(project, files.Refusal) else project
        self.refs = self.project.file_refs("script") if self.project is not None else []
        self.project_view.fill(project, self._is_dirty)
        self._set_file_ops(not self.game_missing)
        if self.project_view.selected() is None:    # keep the author's own selection
            self._select_current_row()

    def _is_dirty(self, ref: str) -> bool:
        record = self.files.get(ref)
        return record is not None and record.dirty

    def _openable(self, ref: str | None) -> bool:
        """A file the Editor tab shows: a listed script, or ``config.toml``."""
        return ref is not None and (ref in self.refs or ref == CONFIG_REF)

    def _select_current_row(self) -> None:
        if self.current is not None:
            self.project_view.select(self.current.ref)

    def _on_tree_select(self, ref: str) -> None:
        """A row was selected: a script or ``config.toml`` opens in the Editor tab, any
        other file shows its facts in the Asset tab; groups and folders do nothing."""
        node = self.project_view.node(ref)
        if node is None or self.closed:
            return
        if self._openable(ref):
            if self.current is None or self.current.ref != ref:
                self.open_file(ref)
            self.select_tab("editor")
        elif node.kind == "file":
            self.show_asset(node)

    def show_asset(self, node: files.TreeNode | str,
                   box: tuple[int, int] | None = None) -> None:
        """The File preview tab for a non-script file (a tree node or a ref): its facts, and a
        thumbnail for a PNG or GIF within the caps (PR-F45-20, 04 §7.7)."""
        ref = node if isinstance(node, str) else node.ref
        self.asset_pane.show(read_asset(self.paths, ref), box=box)
        self.select_tab("asset")

    def _focus_editor(self, _event: tk.Event | None = None) -> str:
        if self._openable(self.project_view.selected()) or _event is None:
            self.select_tab("editor")
            self.text.focus_set()
        return "break"

    def open_file(self, ref: str) -> OpenFile:
        """Show ``ref`` in the editor, opening it on first use (switching keeps unsaved
        edits, PR-F44-04)."""
        record = self._record(ref)
        self.current = record
        self._show(record.widget)
        self.select_tab("editor")
        self._select_current_row()
        return record

    def _record(self, ref: str) -> OpenFile:
        record = self.files.get(ref)
        if record is None:
            record = self.files[ref] = self._new_record(ref)
            self._closed_stamps.pop(ref, None)
            self._watch_open()
        return record

    # --- The document API (F47 04 §3.4; F46's StoryEditor.act, F47 Database and Settings,
    # F42's config.toml writes) ------------------------------------------------------------

    def record_for(self, ref: str) -> OpenFile:
        """``ref``'s open document, opening it (not shown, no tab change) on first use. A
        file that can't be edited gives a read-only record (``editable`` False)."""
        return self._record(ref)

    def apply_plan(self, plan: Plan,
                   verify: Callable[[Mapping[str, str]], bool]) -> bool:
        """Apply ``plan`` to the editor's texts: each ``FilePlan``'s edits as one undo step
        of its file (opened with ``record_for`` when needed). ``verify(texts)`` gets every
        touched file's live text (ref → text) first; when a file can't be edited or
        ``verify`` says no, nothing is written and the answer is False. The change hook then
        marks the files unsaved and schedules the follow and the check, as typing does."""
        records = {fp.ref: self.record_for(fp.ref) for fp in plan.files}
        if any(not record.editable for record in records.values()):
            return False
        texts = {ref: record.widget.get("1.0", "end-1c") for ref, record in records.items()}
        if not verify(texts):
            return False
        for file_plan in plan.files:
            widget = records[file_plan.ref].widget
            self._as_one_step(widget, lambda w=widget, e=file_plan.edits: apply_edits(w, e))
        return True

    def _update_marks(self) -> None:
        """``* `` in front of unsaved rows and the title (UI-F44-02)."""
        for ref in self.files:
            self.project_view.set_dirty(ref, self._is_dirty(ref))
        self._update_title()

    def _update_title(self) -> None:
        dirty = any(record.dirty for record in self.files.values())
        self.root.title(window_title(self.game_name, dirty))

    def dirty_files(self) -> list[OpenFile]:
        """Unsaved files in panel order, then ``config.toml``, then any that left the
        panel."""
        order = [*self.refs, CONFIG_REF]
        dirty = [self.files[ref] for ref in order if ref in self.files and self.files[ref].dirty]
        dirty += [record for ref, record in self.files.items()
                  if ref not in order and record.dirty]
        return dirty

    def _drop_record(self, ref: str) -> None:
        """Forget an open file (deleted): its widget goes, and the editor shows the first
        script, or nothing."""
        record = self.files.pop(ref, None)
        if record is None:
            return
        index = self.scene_indexes.get(ref)
        if index is not None and record.doc is not None and not record.doc.dirty \
                and self._stat(record.doc.real_path) == record.doc.stamp:
            # F58: still on disk as loaded: its index stays, as a closed file's (PR-03).
            self.scene_indexes[ref] = scenes.slim(index)
            self._closed_stamps[ref] = record.doc.stamp
            self._map_dirty = True
        else:
            self._forget_index(ref)
        self._watch_open()
        if self.current is record:
            self.current = None
            others = [r for r in self.refs if r != ref]
            if others:
                self.open_file(others[0])
            else:
                self._show_empty()
        record.widget.destroy()
        self._update_marks()

    def _index_changed(self) -> None:
        """The name index or the scene index changed: the map redraws when next shown, the
        Events page follows, and the tab on screen refreshes (its ``on_show``)."""
        self._map_dirty = True
        if not self.closed and self._side_open and self.side_tab == "events":
            self.root.after_idle(self._follow_events)
        if not self.closed:
            on_show = self.tabs[self.notebook.index("current")].on_show
            if on_show is not None:
                self.root.after_idle(getattr(self, on_show))

    def refresh_outline(self) -> None:
        """The Outline tab from the name index (AC-F45-54); unchanged rows redraw nothing."""
        if not self.closed:
            self.outline_view.set_rows(outline(self._check_names))

    # --- Help pane (PR-F45-16) --------------------------------------------------------------

    def focus_help(self) -> None:
        self.help_text.focus_set()

    def _line_head(self, widget: tk.Text) -> str:
        """The first ``HELP_LINE_CHARS`` characters of the cursor's line."""
        head = widget.get("insert linestart", f"insert linestart +{HELP_LINE_CHARS}c")
        return _join_surrogates(head.split("\n", 1)[0])

    def _update_help(self, widget: tk.Text) -> None:
        if self.current is None or not self.current.editable:
            self._help_key = None
            self.help_pane.show(None)
            return
        head = self._line_head(widget)
        if self._editing_config():
            section = self._config_section(widget)
            key = (str(widget), head, section)
            if key != self._help_key:
                self._help_key = key
                self.help_pane.show(config_help(head, section))
            return
        before = _join_surrogates(widget.get("insert linestart", "insert"))
        tag = tag_help(head, len(before)) if len(before) <= HELP_LINE_CHARS else None
        key = (str(widget), head, tag)
        if key == self._help_key:
            return
        self._help_key = key
        self.help_pane.show(tag if tag is not None else help_for(head))

    def _editing_config(self) -> bool:
        """True while the Editor tab shows ``config.toml`` (2026-11-02, AC-F45-63..66)."""
        return self.current is not None and self.current.ref == CONFIG_REF

    def _config_section(self, widget: tk.Text) -> str | None:
        """The ``[section]`` the cursor's line of ``config.toml`` is in."""
        return section_at(widget.get("1.0", "insert linestart"))

    def _rows(self, ctx: Context) -> list:
        """The completion rows for ``ctx``: config names, or the check's name index."""
        if ctx.kinds and ctx.kinds[0] in CONFIG_KINDS:
            return config_candidates(ctx)
        return candidates(ctx, self._check_names)

    # --- Insert (PR-F45-15, UI-F45-05) ------------------------------------------------------

    def insert_doc(self, doc: StatementDoc) -> None:
        """Insert ▸ …: the doc's example on a new line below the cursor (or in place of a
        blank cursor line), indented like the cursor line (one unit more after a ``:``),
        nested lines in the file's indent unit; the first field is selected. One undo
        step."""
        if self.closed or self.current is None or not self.current.editable:
            return
        self.close_completion()
        self.select_tab("editor")
        widget = self.current.widget
        line = line_of(widget.index("insert"))
        current = widget.get(f"{line}.0", f"{line}.end")
        lead = current[:len(current) - len(current.lstrip(" \t"))]
        unit = indent_unit(widget.get("1.0", "end-1c"))
        blank = not current.strip()
        if not blank and _without_comment(current).rstrip().endswith(":"):
            lead += unit
        text, span = insert_text(doc, lead, unit)
        base = f"{line}.0" if blank else f"{line + 1}.0"

        def act() -> None:
            if blank:
                widget.delete(f"{line}.0", f"{line}.end")
                widget.insert(f"{line}.0", text)
            else:
                widget.insert(f"{line}.end", "\n" + text)

        self._as_one_step(widget, act)
        widget.tag_remove("sel", "1.0", "end")
        if span is not None:
            first = widget.index(f"{base} +{self._tk_length(text[:span[0]])}c")
            last = widget.index(f"{base} +{self._tk_length(text[:span[1]])}c")
            widget.tag_add("sel", first, last)
            widget.mark_set("insert", last)
        else:
            widget.mark_set("insert", f"{base} +{self._tk_length(text)}c")
        widget.see("insert")
        widget.focus_set()

    # --- Completion (PR-F45-13, 14; UI-F45-04) ----------------------------------------------

    def _completion_here(self, widget: tk.Text) -> tuple[Context, str] | None:
        """(context, text before the cursor) at the cursor, or None."""
        before = widget.get("insert linestart", "insert")
        if len(before) > HELP_LINE_CHARS:
            return None
        before = _join_surrogates(before)
        if self._editing_config():
            ctx = config_context(before, len(before), self._config_section(widget))
        else:
            # The rest of the line too: ``"…" in codex.tips`` narrows a string's names.
            after = widget.get("insert", f"insert +{HELP_LINE_CHARS}c").split("\n", 1)[0]
            ctx = completion_context(before + _join_surrogates(after), len(before))
        return None if ctx is None else (ctx, before)

    def complete(self) -> None:
        """Ctrl+Space: open the completion list for the word at the cursor."""
        if self.closed or self.current is None or not self.current.editable:
            return
        self._open_completion(self.text)

    def _open_completion(self, widget: tk.Text) -> bool:
        found = self._completion_here(widget)
        if found is None:
            self.close_completion()
            return False
        ctx, before = found
        rows = self._rows(ctx)
        if not rows:
            self.close_completion()
            return False
        back = self._tk_length(before[ctx.start:])
        widget.see("insert")
        widget.update_idletasks()
        box = widget.bbox(f"insert -{back}c") or widget.bbox("insert")
        x, y = (box[0], box[1] + box[3]) if box else (0, 0)
        self.popup.open(widget, line_of(widget.index("insert")), ctx, rows,
                        widget.winfo_rootx() + x, widget.winfo_rooty() + y)
        # Esc is bound only while the list is open: otherwise no key binding in the main
        # window reacts to Escape (F44 I-6).
        self.root.bind_class(self._editor_bindtag, "<Escape>",
                             lambda _e: self._completion_key("close"))
        return True

    def close_completion(self) -> None:
        popup = getattr(self, "popup", None)
        if popup is not None and popup.is_open:
            popup.close()
            try:
                self.root.unbind_class(self._editor_bindtag, "<Escape>")
            except tk.TclError:
                pass

    def _update_completion(self) -> None:
        """After a change or a cursor move while the list is open: refilter, or close it
        when the cursor left the word or its line."""
        popup = self.popup
        widget = popup.widget
        if not popup.is_open or widget is None:
            return
        if widget is not self.text or line_of(widget.index("insert")) != popup.line:
            self.close_completion()
            return
        found = self._completion_here(widget)
        old = popup.ctx
        if found is None or old is None or found[0].start != old.start \
                or found[0].kinds != old.kinds:
            self.close_completion()
            return
        ctx = found[0]
        if ctx == old:
            return
        rows = self._rows(ctx)
        if not rows:
            self.close_completion()
            return
        popup.fill(ctx, rows)

    def accept_completion(self, index: int | None = None) -> bool:
        """Enter, Tab, or a click: put the chosen name in place of the typed word."""
        popup = self.popup
        widget = popup.widget
        if not popup.is_open or widget is None:
            return False
        if index is not None:
            popup.select(index)
        chosen = popup.chosen()
        found = self._completion_here(widget)
        self.close_completion()
        if chosen is None or found is None:
            return False
        ctx, before = found
        back = self._tk_length(before[ctx.start:])

        def act() -> None:
            if back:
                widget.delete(f"insert -{back}c", "insert")
            widget.insert("insert", chosen.text)

        self._as_one_step(widget, act)
        widget.see("insert")
        widget.focus_set()
        return True

    def _completion_key(self, action: str) -> str | None:
        """Up, Down, Prior, Next, Escape, Return and Tab while the list is open."""
        if not self.popup.is_open:
            return None
        if action == "accept":
            self.accept_completion()
        elif action == "close":
            self.close_completion()
        else:
            self.popup.move({"up": -1, "down": 1, "prior": -COMPLETION_PAGE,
                             "next": COMPLETION_PAGE}[action])
        return "break"

    def _after_key(self, event: tk.Event) -> None:
        """PR-F45-14: a typed space after a word whose doc lists names opens the list; so
        does a ``{`` or ``{/`` in a text string (text tags, AC-F45-57)."""
        if (event.char == " " and not self.popup.is_open) or event.char in ("{", "/", "[", "."):
            self.root.after_idle(self._auto_complete, event.widget)

    def _auto_complete(self, widget: tk.Text) -> None:
        if self.closed or self.current is None or widget is not self.text:
            return
        if self.popup.is_open:
            self._update_completion()       # "{" then "/": the tag list gives way
            if self.popup.is_open:
                return
        before = _join_surrogates(widget.get("insert linestart", "insert"))
        if len(before) > HELP_LINE_CHARS:
            return
        if self._editing_config():
            if auto_open_config(before, len(before), self._config_section(widget)):
                self._open_completion(widget)
        elif auto_open(before, len(before)):
            self._open_completion(widget)

    def _on_editor_focus_out(self, _event: tk.Event) -> None:
        if self.popup.is_open:
            self.root.after_idle(self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        """Focus left the editor (not for the list itself): close the list."""
        if not self.popup.is_open or self.closed:
            return
        try:
            focus = self.root.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus is self.popup.widget or (focus is not None and self.popup.owns(focus)):
            return
        self.close_completion()

    # --- Change hook and refresh (§7.6) -----------------------------------------------------

    def _on_change(self, widget: tk.Text, content: bool) -> None:
        if self.closed:
            return
        record = next((r for r in self.files.values() if r.widget is widget), None)
        if content and record is not None:
            record.changes += 1                 # now, not at <<Modified>> (F46 map undo)
            if not self._suppress and record.ref in self.scene_indexes:
                self._schedule_follow()
            if self._ask_id is not None and not self._suppress:
                self._arm_ask()                 # F58 I-5: the question waits for a pause
        if content and not self._suppress:
            self.edit_serial += 1
            self._schedule_auto_check()
        if content and not self._suppress and record is not None and record.doc is not None:
            if not record.doc.dirty:
                record.doc.dirty = True
                self._update_marks()
        if content:
            self._label_line = None
        self._schedule_refresh()

    def _on_yscroll(self, widget: tk.Text, first: str, last: str) -> None:
        if widget is self._shown:
            self._vbar_set(first, last)
            self._schedule_refresh()

    def _on_xscroll(self, widget: tk.Text, first: str, last: str) -> None:
        if widget is self._shown:
            self._hbar_set(first, last)

    def _schedule_refresh(self) -> None:
        if self._refresh_id is None and not self.closed:
            self._refresh_id = self.root.after_idle(self.refresh)

    def refresh(self) -> None:
        """Color the visible lines, redraw the gutter, update the start label, and clear
        the jump highlight once the cursor leaves its line."""
        self._refresh_id = None
        if self.closed:
            return
        widget = self.text
        first, last = self._visible_lines(widget)
        if self.current is not None and self.current.editable:
            self._color_lines(widget, first, last)
        self._update_current_line(widget)
        self._draw_gutter(widget, first, last)
        self._update_start_label(widget)
        self._update_help(widget)
        self._update_check_status()
        self._update_cursor_items(widget)
        self._update_side_name()
        if self.popup.is_open:
            self._update_completion()

    def _update_current_line(self, widget: tk.Text) -> None:
        """The cursor line's background (an editable file only; the selection and the jump
        highlight lie over it)."""
        editable = self.current is not None and self.current.editable
        key = (str(widget), line_of(widget.index("insert"))) if editable else None
        if key == self._line_shown:
            return
        for other in self._editor_widgets():
            other.tag_remove(TAG_LINE, "1.0", "end")
        if key is not None:
            widget.tag_add(TAG_LINE, f"{key[1]}.0", f"{key[1] + 1}.0")
        self._line_shown = key

    def _update_cursor_items(self, widget: tk.Text) -> None:
        """The status bar's right side for the file on screen: ``Ln N, Col M`` (columns
        count characters, from 1), the indent, the encoding and the line ending. Empty (so
        hidden) without an editable file."""
        record = self.current
        if record is None or record.doc is None:
            for item in (self.cursor_item, self.indent_item, self.encoding_item,
                         self.eol_item):
                item.configure(text="")
            return
        doc = record.doc
        line = line_of(widget.index("insert"))
        before = widget.get("insert linestart", "insert")
        column = len(_join_surrogates(before)) if self.astral_columns > 1 else len(before)
        self.cursor_item.configure(text=f"Ln {line}, Col {column + 1}")
        key = (str(widget), self.edit_serial, id(doc))
        if key != self._indent_key:         # the whole text is read once per edit
            self._indent_key = key
            self._indent_shown = indent_text(indent_unit(widget.get("1.0", "end-1c")))
        self.indent_item.configure(text=self._indent_shown)
        self.encoding_item.configure(text="UTF-8 with BOM" if doc.bom else "UTF-8")
        self.eol_item.configure(text=EOL_NAMES.get(doc.newline, "LF"))

    def _visible_lines(self, widget: tk.Text) -> tuple[int, int]:
        first = line_of(widget.index("@0,0"))
        height = widget.winfo_height()
        last = line_of(widget.index(f"@0,{height}"))
        rows = height // max(1, self.font.metrics("linespace")) + 1
        last = max(last, first + max(rows, _MIN_COLORED_LINES))
        return first, min(last, line_of(widget.index("end-1c")))

    def _color_lines(self, widget: tk.Text, first: int, last: int) -> None:
        start, stop = f"{first}.0", f"{last}.end"
        for tag in SYNTAX_TAGS:
            widget.tag_remove(tag, start, stop)
        ranges: dict[str, list[str]] = {}
        wide = self.astral_columns > 1
        for number, line in enumerate(widget.get(start, stop).split("\n"), start=first):
            spans = color_spans(line)
            if not spans:
                continue
            columns = _column_map(line) if wide and _has_astral(line) else None
            for begin, end, tag in spans:
                if columns is not None:
                    begin, end = columns[begin], columns[end]
                ranges.setdefault(tag, []).extend((f"{number}.{begin}", f"{number}.{end}"))
        for tag, indexes in ranges.items():
            widget.tag_add(tag, *indexes)

    # --- Gutter (§7.6 "Gutter", UI-F44-03 as changed by C3) ---------------------------------

    def _gutter_width(self, lines: int) -> int:
        return (MARKER_CHARS + len(str(lines)) + 2) * self.font.measure("0")

    def _draw_gutter(self, widget: tk.Text, first: int, last: int) -> None:
        gutter = self.side_gutter if widget is self.side_text else self.gutter
        gutter.delete("all")
        total = line_of(widget.index("end-1c"))
        width = self._gutter_width(total)
        if int(gutter.cget("width")) != width:
            gutter.configure(width=width)
        if self.current is None or not self.current.editable:
            return
        zero = self.font.measure("0")
        right = width - zero
        marked = self._line_items(self.current, first, last)
        cursor_line = line_of(widget.index("insert"))
        drawn = False
        for number in range(first, last + 1):
            info = widget.dlineinfo(f"{number}.0")
            if info is None:
                if drawn:
                    break
                continue
            drawn = True
            gutter.create_text(right, info[1], anchor="ne", text=str(number), font=self.font,
                               fill=GUTTER_CURRENT if number == cursor_line
                               else GUTTER_FOREGROUND)
            severity = _marker_severity(marked.get(number, ()))
            if severity is not None:
                gutter.create_text(zero // 2, info[1], anchor="nw", font=self.font,
                                   text=MARKER_LETTERS[severity],
                                   fill=MARKER_COLORS[severity], tags=TAG_MARKER)

    # --- Indent (PR-F44-07, §7.6 "Indent") --------------------------------------------------

    def _editable(self, widget: tk.Text) -> bool:
        return str(widget.cget("state")) == "normal"

    def _as_one_step(self, widget: tk.Text, action: Callable[[], None]) -> None:
        """One undo step for the whole action."""
        widget.configure(autoseparators=False)
        widget.edit_separator()
        try:
            action()
        finally:
            widget.edit_separator()
            widget.configure(autoseparators=True)

    def _newline(self, widget: tk.Text) -> str:
        """Enter keeps the line's indent, plus one unit after a line ending with ``:``."""
        if not self._editable(widget):
            return "break"

        def act() -> None:
            if widget.tag_ranges("sel"):
                widget.delete("sel.first", "sel.last")
            before = widget.get("insert linestart", "insert")
            lead = before[:len(before) - len(before.lstrip(" \t"))]
            if _without_comment(before).rstrip().endswith(":"):
                lead += indent_unit(widget.get("1.0", "end-1c"))
            widget.insert("insert", "\n" + lead)
            widget.see("insert")

        self._as_one_step(widget, act)
        return "break"

    def _indent(self, widget: tk.Text, *, dedent: bool) -> str:
        """Tab and Shift+Tab: indent or dedent the selected lines, or insert one unit at the
        cursor (dedent the cursor's line). Never moves focus."""
        if not self._editable(widget):
            return "break"
        unit = indent_unit(widget.get("1.0", "end-1c"))
        selection = widget.tag_ranges("sel")

        def act() -> None:
            if not selection and not dedent:
                widget.insert("insert", unit)
                widget.see("insert")
                return
            if selection:
                first = line_of(widget.index("sel.first"))
                end = widget.index("sel.last")
                last = line_of(end)
                if last > first and end.endswith(".0"):
                    last -= 1
            else:
                first = last = line_of(widget.index("insert"))
            for number in range(first, last + 1):
                if dedent:
                    line = widget.get(f"{number}.0", f"{number}.end")
                    count = _dedent_count(line, unit)
                    if count:
                        widget.delete(f"{number}.0", f"{number}.{count}")
                elif widget.get(f"{number}.0", f"{number}.end"):
                    widget.insert(f"{number}.0", unit)
            if selection:
                widget.tag_remove("sel", "1.0", "end")
                widget.tag_add("sel", f"{first}.0", f"{last}.end")

        self._as_one_step(widget, act)
        return "break"

    # --- Zoom (03 §4, §7) -------------------------------------------------------------------

    def zoom(self, step: int) -> None:
        """Ctrl+= / Ctrl+- change the editor text by 2 px within 10-32 px; Ctrl+0 (step 0)
        returns to 14 px. The gutter shares the font."""
        size = FONT_PX if step == 0 else min(FONT_MAX_PX, max(FONT_MIN_PX,
                                                               self.font_px + step))
        if size == self.font_px:
            return
        self.font_px = size
        self.font.configure(size=-self._px(size))
        tab = self._tab_width()
        for widget in self._editor_widgets() + ([self.side_text] if self.side_text else []):
            widget.configure(tabs=(tab,))
        self._schedule_refresh()

    def _tab_width(self) -> int:
        return TAB_SPACES * self.font.measure(" ")

    # --- Save and close (PR-F44-04, §7.2 Save, §7.6 "Dialogs") ------------------------------

    def save_record(self, record: OpenFile) -> bool:
        """Save one unsaved file. A failure shows its dialog and keeps the text and its
        ``* ``. A clean or read-only file writes nothing."""
        if record.doc is None or not record.doc.dirty:
            return True
        try:
            save(record.doc, record.widget.get("1.0", "end-1c"))
        except SaveError as error:
            show_error(self.root, error.message)
            return False
        self._update_marks()
        self._saved_refs.append(record.ref)     # F39: ``after_saves`` updates the game
        return True

    def save_current(self) -> bool:
        """Ctrl+S: save the file on screen. Arms the window and asks for a check, then
        updates a running game (F39)."""
        self.armed = True
        saved = self.current is None or self.save_record(self.current)
        if saved:
            self.request_check()
            self.after_saves()
        return saved

    def save_all(self) -> bool:
        """Ctrl+Shift+S: save every unsaved file, stopping at the first failure. Arms the
        window and asks for a check."""
        self.armed = True
        for record in self.dirty_files():
            if not self.save_record(record):
                return False
        self.request_check()
        self.after_saves()
        return True

    def on_close(self) -> None:
        """The close box, Alt+F4, and Cmd+Q: ask about unsaved files, then close."""
        if self.closed:
            return
        if build_running(self):                 # F42 PR-F42-23: CLOSE_WHILE_BUILDING
            if ask(self.root, build_texts.CLOSE_WHILE_BUILDING,
                   (build_texts.STOP_AND_CLOSE, build_texts.KEEP_BUILDING),
                   escape=1, default=1) != 0:
                return
            self.build_runner.stop()            # the tree is killed and staging removed
        dirty = self.dirty_files()
        if dirty:
            choice = ask(self.root, close_message([record.ref for record in dirty]),
                         CLOSE_BUTTONS, escape=CLOSE_ESCAPE)
            if choice == CLOSE_ESCAPE:
                return
            if choice == 0:
                for record in dirty:
                    if not self.save_record(record):
                        return
        self.close()

    def close(self) -> None:
        """Close the window now, ending a running preview first (PR-F44-14)."""
        if self.closed:
            return
        self.closed = True
        for after_id in (self._refresh_id, self._poll_id, self._add_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._refresh_id = self._poll_id = self._add_id = None
        self._cancel_debounce()
        self._cancel_follow()
        self._stop_watch()                      # F58 AC-36: never waits for the thread
        self._stop_live_map()
        self._cancel_layout_save()
        self.save_layout()                      # F46: whatever happens to the scripts
        self.runner.stop()
        self.check_runner.stop()
        self.close_assistant()                  # F48 07 I-7: the pane's run and check child
        for runner, _on_events in self.runners:     # joined runners (runwiring)
            runner.stop()
        self.root.destroy()

    # --- Changes made outside the editor (PR-F44-08, §7.2) ----------------------------------

    def _on_focus_in(self, event: tk.Event) -> None:
        if event.widget is self.root and not self.closed:
            # The window itself may end up with the focus (at launch, or when Tk forgot the
            # widget): hand it to the editor (03 §4 "Starting focus").
            self.root.after_idle(self._focus_editor_if_lost)
        now = time.monotonic()
        if self.closed or self._checking_outside or \
                now - self._last_outside_check < OUTSIDE_CHECK_INTERVAL:
            return
        self._last_outside_check = now
        self.check_outside_changes()

    def _focus_editor_if_lost(self) -> None:
        if self.closed:
            return
        try:
            focus = self.root.focus_get()
        except (KeyError, tk.TclError):
            return
        if focus is self.root:
            self.text.focus_set()

    def check_outside_changes(self) -> None:
        """List the project again, reload clean files that changed on disk, and ask about
        changed files with unsaved edits."""
        self._checking_outside = True
        try:
            self.refresh_project()
            for record in list(self.files.values()):
                self._check_record(record)
        finally:
            self._checking_outside = False
        self._update_marks()

    def _check_record(self, record: OpenFile) -> None:
        if record.doc is not None:
            stamp = self._stat(record.doc.real_path)
            if stamp is None or stamp == record.doc.stamp:
                return
            if record.doc.dirty:
                self._answered(record)          # F58 I-5: one question per stamp
                choice = ask(self.root, changed_message(record.ref), CHANGED_BUTTONS,
                             escape=CHANGED_ESCAPE)
                if choice == 0:
                    record.doc.stamp = stamp    # keep mine; ask again only on a new change
                    return
        else:
            stamp = self._stat(self.paths.root / record.ref)
            if stamp is None or stamp == record.stamp:
                return
        self.reload(record)

    def reload(self, record: OpenFile) -> OpenFile:
        """Read ``record``'s file again, keeping the cursor line."""
        result = self._open_any(record.ref)
        if isinstance(result, ScriptDocument) and record.doc is not None:
            self._reload_from(record, result)   # F58 contract 3: changed scenes parse
            record.widget.see("insert")
            self._map_dirty = True
            fresh = record
        else:
            fresh = self._new_record(record.ref)
            self.files[record.ref] = fresh
            if self.current is record:
                had_focus = self.root.focus_get() is record.widget
                self.current = fresh
                self._show(fresh.widget)
                if had_focus:
                    fresh.widget.focus_set()
            record.widget.destroy()
        if fresh is self.current:
            self._label_line = None
            self._schedule_refresh()
        self._update_marks()
        return fresh

    # --- The live map's watch of script/** (F58 04 §7.1-7.3, §7.11; 07 I-2 to I-7) ----------

    def _start_watch(self) -> None:
        """The watch thread over ``script/**`` (``mapwatch``), baselined with Studio's own
        listing so nothing is read until it changes; its mailbox is polled here every
        ``WATCH_POLL_MS``. ``WATCH_THREAD`` False (tests): no thread, ``watch.tick()`` by
        hand."""
        self.watch = ScriptWatch(self.paths.root)
        self.watch.baseline(scan_scripts(self.paths.root))
        self._watch_open()
        if WATCH_THREAD:
            self.watch.start()
        self._watch_id = self.root.after(WATCH_POLL_MS, self._poll_watch)

    def _stop_watch(self) -> None:
        """Window close (AC-F58-36): the thread is asked to stop, never waited for."""
        if self.watch is not None:
            self.watch.stop()
        for after_id in (self._watch_id, self._batch_id, self._ask_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._watch_id = self._batch_id = self._ask_id = None

    def _watch_open(self) -> None:
        """The open scripts (their news carries the decoded document)."""
        if self.watch is not None:
            self.watch.set_open(ref for ref, record in self.files.items()
                                if record.doc is not None)

    def _poll_watch(self) -> None:
        """The mailbox, every ``WATCH_POLL_MS``: news applied, then Q2's adoption. A failed
        watch stops here; the focus listing (``check_outside_changes``) covers it."""
        self._watch_id = None
        watch = self.watch
        if self.closed or watch is None or watch.failed is not None:
            return
        news = watch.mailbox.take()
        if news:
            self.take_news(news)
        self._maybe_adopt()
        self._watch_id = self.root.after(WATCH_POLL_MS, self._poll_watch)

    def take_news(self, news: Mapping[str, FileNews]) -> None:
        """The watch's news (one entry per file): own writes are quiet (the stamp after the
        read equals Studio's own, I-2), news older than Studio's last save or reload of
        that file is dropped (the file's ``os.stat`` moved on, I-4), a file with unsaved
        edits keeps them and gets one question (I-5); the rest joins the update batch."""
        listed = False
        for ref, item in news.items():
            kind = item.kind
            if kind == watchmod.REMOVED:
                listed = True
                self._capped.discard(ref)
                self._closed_docs.pop(ref, None)
                if ref not in self.files and ref in self.scene_indexes:
                    self._drop_closed(ref)
                    self._disk_refs[ref] = None
                continue
            if kind == watchmod.CAPPED:
                self._capped.add(ref)
                self.map_line.say("S6", livemap.S6)
                continue
            if kind in (watchmod.CHECK_ONLY, watchmod.UNREADABLE):
                if ref not in self.files:       # the check covers it (and the map with it)
                    self._drop_closed(ref)
                self._outside_check()
                continue
            if kind != watchmod.CHANGED:
                continue                        # LISTED: S4's check covers it
            if ref not in self.refs:
                listed = True                   # a new file: the project panel lists it
            record = self.files.get(ref)
            if record is not None:
                self._news_for_record(record, item)
            elif self._closed_stamps.get(ref) != item.stamp \
                    and self._stat(self.paths.root / ref) == item.stamp:
                self._closed_stamps[ref] = item.stamp
                self._batch.add(ref, item.text)
                if item.doc is not None:
                    self._keep_doc(item.doc)
        if listed:
            self.refresh_project()
        if not self._capped:
            self.map_line.clear("S6")
        if self._batch_id is None:              # else a slice is already on its way
            self._run_batch()

    def _news_for_record(self, record: OpenFile, item: FileNews) -> None:
        doc = record.doc
        if doc is None:                         # read-only: reload as F44 does
            if item.stamp != record.stamp:
                self.reload(record)
            return
        if item.stamp == doc.stamp or self._stat(doc.real_path) != item.stamp:
            return                              # own write (PR-20), or older news (I-4)
        if doc.dirty:
            self._outside_dirty(record, item.stamp)
            return
        if item.doc is not None:
            self._news_docs[record.ref] = item.doc
            self._batch.add(record.ref, None)

    def _run_batch(self) -> None:
        """The pending files, parsed in 30 ms slices (PR-10); over 50,000 changed lines the
        map waits for a check instead (S4)."""
        self._batch_id = None
        batch = self._batch
        if self.closed or self._big:
            return
        if not batch.pending:
            self._disk_updated()                # removals only (or nothing)
            return
        if batch.big(self._changed_lines):
            self._big_batch()
            return
        if batch.step(self._index_news, lambda: time.perf_counter() * 1000):
            self._disk_updated()
        else:
            self._batch_id = self.root.after(1, self._run_batch)

    def _changed_lines(self, ref: str, text: str | None) -> int:
        if text is None:
            doc = self._news_docs.get(ref)
            text = doc.text if doc is not None else ""
        return scenes.changed_lines(text, self._checked.get(ref))

    def _index_news(self, ref: str, text: str | None) -> None:
        """One file of the batch: an open clean file reloads from the watch's document (no
        second read, I-3); a closed file's index is brought up to date, parsing only the
        scenes whose digest differs from the last check's (contract 3)."""
        record = self.files.get(ref)
        if text is None:
            doc = self._news_docs.pop(ref, None)
            if doc is not None and record is not None and record.doc is not None \
                    and not record.doc.dirty:
                self._reload_from(record, doc)
                self._disk_refs[ref] = None
            return
        if record is not None:
            return                              # opened meanwhile: its own text rules
        index = scenes.reindex(self.scene_indexes.get(ref), ref, text, 0,
                               checked=self._checked.get(ref, {}),
                               positions=self._positions())
        self.scene_indexes[ref] = scenes.slim(index)
        self._checked.setdefault(ref, index.checked)
        self._disk_refs[ref] = None

    def _disk_updated(self) -> None:
        """A batch landed: one map update (S1 with it), and the usual check after
        ``CHECK_DEBOUNCE_MS`` (PR-03; never an armed one, I-6)."""
        if not self._disk_refs:
            return
        self.edit_serial += 1
        self._schedule_auto_check()
        self._map_dirty = True
        self._follow_source = "disk"
        if self._side_open and self.side_tab == "events":
            self.root.after_idle(self._follow_events)
        if self.current_tab() == "map" and not self._iconic():
            self.refresh_story_map()
            self.follow_scroll()
        else:
            on_show = self.tabs[self.notebook.index("current")].on_show
            if on_show is not None and on_show != "refresh_story_map":
                self.root.after_idle(getattr(self, on_show))
        self.assist_texts_changed()             # F58 W5: cards on these files

    def _big_batch(self) -> None:
        """PR-10: too much changed to parse here. Boxes stay, S4 shows, the watch only
        lists, open clean files reload without parsing and closed files leave the map to
        the check, which runs now."""
        refs = list(self._batch.take())
        self._big = True
        if self.watch is not None:
            self.watch.lists_only = True
        for ref in refs:
            doc = self._news_docs.pop(ref, None)
            record = self.files.get(ref)
            if doc is not None and record is not None and record.doc is not None \
                    and not record.doc.dirty:
                self._reload_from(record, doc, parse=False)
            elif record is None:
                self._drop_closed(ref)
        self.map_line.say("S4", livemap.s4(len(refs)))
        self._show_map_line()
        self.request_check()

    def big_batch_done(self) -> None:
        """S4's check result arrived: the watch reads again, S4 goes."""
        if not self._big:
            return
        self._big = False
        if self.watch is not None:
            self.watch.lists_only = False
        self.map_line.clear("S4")
        self._show_map_line()

    def _outside_check(self) -> None:
        self.edit_serial += 1
        self._schedule_auto_check()

    def _keep_doc(self, doc: ScriptDocument) -> None:
        """R2: the newest watch documents of closed files, ``CLOSED_DOCS_CHARS`` at most."""
        docs = self._closed_docs
        docs.pop(doc.ref, None)
        docs[doc.ref] = doc
        total = sum(len(kept.text) for kept in docs.values())
        while total > CLOSED_DOCS_CHARS and len(docs) > 1:
            total -= len(docs.pop(next(iter(docs))).text)

    def _drop_closed(self, ref: str) -> None:
        self._closed_docs.pop(ref, None)
        self.scene_indexes.pop(ref, None)
        self._checked.pop(ref, None)
        self._closed_stamps.pop(ref, None)
        self._map_dirty = True

    def _reload_from(self, record: OpenFile, doc: ScriptDocument, *, parse: bool = True
                     ) -> None:
        """Replace an open clean file's text with ``doc`` (as read from disk), keeping the
        cursor line; its index follows the previous check's digests, so a changed scene
        parses at once (contract 3; ``parse`` False: baseline, the check follows)."""
        widget = record.widget
        line = line_of(widget.index("insert"))
        self._set_text(record, doc.text)
        doc.text = ""
        record.doc = doc
        widget.mark_set("insert", f"{min(line, line_of(widget.index('end-1c')))}.0")
        self._place_marks(record)
        if self._is_script(record):
            text = widget.get("1.0", "end-1c")
            self.scene_indexes[record.ref] = scenes.reindex(
                self.scene_indexes.get(record.ref), record.ref, text, record.changes,
                checked=self._checked.get(record.ref) if parse else None,
                positions=self._positions())
            self._checked.setdefault(record.ref, self.scene_indexes[record.ref].checked)
        if record is self.current:
            self._label_line = None
            self._schedule_refresh()
        self._update_marks()

    def _iconic(self) -> bool:
        try:
            return str(self.root.state()) == "iconic"
        except tk.TclError:
            return True

    def _on_map_event(self, event: tk.Event) -> None:
        """The window shows again (PR-21): one catch-up update, glowing what changed."""
        if event.widget is self.root and not self.closed and self.current_tab() == "map":
            self.root.after_idle(self.refresh_story_map)

    # --- A changed file with unsaved edits (PR-F58-02; 07 I-5) ---------------------------------

    def _outside_dirty(self, record: OpenFile, stamp: tuple[int, int]) -> None:
        """Changed on disk, unsaved here: the text stays, S2 shows, and F44's question
        waits for focus: asked at <FocusIn>, or after a 1 s typing pause while Studio has
        the focus, whichever comes first, once per outside stamp."""
        if record.outside_stamp == stamp:
            return
        record.outside_stamp = stamp
        self.map_line.say("S2", livemap.s2(record.ref))
        self._show_map_line()
        self._arm_ask()

    def _arm_ask(self) -> None:
        if self._ask_id is not None:
            try:
                self.root.after_cancel(self._ask_id)
            except tk.TclError:
                pass
            self._ask_id = None
        if not self.closed and any(r.outside_stamp is not None for r in self.files.values()):
            self._ask_id = self.root.after(ASK_PAUSE_MS, self._ask_after_pause)

    def _ask_after_pause(self) -> None:
        self._ask_id = None
        if self.closed or self._checking_outside or not self._focused():
            return                              # <FocusIn> asks instead
        self._checking_outside = True
        try:
            for record in list(self.files.values()):
                if record.outside_stamp is not None and record.doc is not None:
                    self._check_record(record)
        finally:
            self._checking_outside = False
        self._update_marks()

    def _focused(self) -> bool:
        try:
            return self.root.focus_get() is not None
        except (KeyError, tk.TclError):
            return False

    def _answered(self, record: OpenFile) -> None:
        """The question for ``record`` was asked (or its file reloaded): S2 goes when no
        other file waits."""
        record.outside_stamp = None
        if not any(r.outside_stamp is not None for r in self.files.values()):
            self.map_line.clear("S2")
            self._show_map_line()

    # --- Q2: the checked digests (04 §7.11; 07 I-7) -------------------------------------------

    def _maybe_adopt(self) -> None:
        """A check result's digests are adopted for files without unsaved edits only after
        a listing that started after the result has finished, and only where the stamp is
        still the snapshot's (a file that moved keeps its old ``checked``)."""
        pending = self._adopt
        watch = self.watch
        if pending is None or (watch is not None and watch.alive
                               and watch.finished <= pending[0]):
            return
        self._adopt = None
        self._adopt_digests(pending[1], pending[2])

    def _adopt_digests(self, digests: Mapping[str, dict], stamps: Mapping[str, object]
                       ) -> None:
        for ref, checked in digests.items():
            index = self.scene_indexes.get(ref)
            if index is None or self._stamp_of(ref) != stamps.get(ref):
                continue
            self._checked[ref] = checked
            if ref not in self.files:           # closed: the check's links take over
                self.scene_indexes[ref] = scenes.drop_checked_reads(index, checked)
        self._map_dirty = True

    def _stamp_of(self, ref: str) -> object:
        record = self.files.get(ref)
        if record is not None:
            return record.doc.stamp if record.doc is not None else None
        return self._closed_stamps.get(ref)

    @staticmethod
    def _stat(path: os.PathLike | str) -> tuple[int, int] | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    # --- Jump (UI-F44-08, §7.6 "Jump", I-3) -------------------------------------------------

    def jump_to(self, ref: str, line: int, column: int | None = None) -> None:
        """Open ``ref``, put the cursor on ``line`` and ``column`` (F02's, 1-based; column 1
        when there is none), scroll the line into the middle third, highlight it until the
        cursor leaves it, and focus the editor."""
        record = self.open_file(ref)
        widget = record.widget
        if not record.editable:
            widget.focus_set()
            return
        line = max(1, min(line, line_of(widget.index("end-1c"))))
        text = widget.get(f"{line}.0", f"{line}.end")
        self._place_jump(widget, line, self._tk_column(text, column))

    def _place_jump(self, widget: tk.Text, line: int, tk_column: int = 0) -> None:
        """The cursor to ``line.tk_column``, the line in the middle third, highlighted
        until the cursor leaves it, and the focus in ``widget``."""
        widget.mark_set("insert", f"{line}.{tk_column}")
        for other in self._editor_widgets():
            other.tag_remove(TAG_JUMP, "1.0", "end")
        self._jump_line = line
        widget.update_idletasks()                   # a file just shown has no height yet
        rows = max(1, widget.winfo_height() // max(1, self.font.metrics("linespace")))
        widget.yview(f"{max(1, line - rows // 3)}.0")
        widget.tag_add(TAG_JUMP, f"{line}.0", f"{line + 1}.0")
        widget.focus_set()
        self._schedule_refresh()

    def _tk_column(self, line_text: str, column: int | None) -> int:
        """F02's column C → Tk's index column: the first C-1 characters, counted the way
        this Tk counts them (I-3: two columns for a character outside the BMP on Tk 8.6)."""
        if not column:
            return 0
        text = _join_surrogates(line_text)
        count = min(column - 1, len(text))
        if self.astral_columns > 1:
            return _column_map(text)[count]
        return count

    def _tk_length(self, text: str) -> int:
        """``len(text)`` in Tk index characters (for ``+Nc``)."""
        return self._tk_column(text, len(text) + 1)


def _without_comment(line: str) -> str:
    """``line`` without its ``#`` comment (as the coloring finds it)."""
    for begin, _end, tag in color_spans(line):
        if tag == TAG_COMMENT:
            return line[:begin]
    return line


def _dedent_count(line: str, unit: str) -> int:
    """How many leading characters Shift+Tab removes: one unit, never more than the line
    has (a tab, or up to the unit's width in spaces)."""
    if line.startswith("\t"):
        return 1
    width = len(unit) if unit != "\t" else TAB_SPACES
    spaces = len(line) - len(line.lstrip(" "))
    return min(spaces, width)


def _join_surrogates(text: str) -> str:
    """Join surrogate pairs that Tk 8.6 may return for a character outside the BMP."""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _has_astral(line: str) -> bool:
    return any(ord(char) > 0xFFFF for char in line)


def _column_map(line: str) -> list[int]:
    """Tk index column for each string offset 0..len(line) when Tk counts a character
    outside the BMP as two columns (I-3)."""
    columns = [0]
    for char in line:
        columns.append(columns[-1] + (2 if ord(char) > 0xFFFF else 1))
    return columns
