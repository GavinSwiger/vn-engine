"""The Studio window: every Tk call of the editor (F44 ``04-technical.md`` §7.6,
``03-ui.md`` §1-§4; ``07`` I-3, I-6, I-13, I-14; F45 ``01`` §6.1, ``04`` §7.4, §7.5, ``07``
I-1, I-2).

``EditorWindow(root, paths)`` builds the window on an existing ``tk.Tk`` and opens the
game's files; ``run_editor`` (``engine/tools/editor/__init__.py``) creates the root and runs
the main loop. The left column holds the project panel (``views.ProjectView`` over
``files.project_tree``) in place of F44's file list; the right area is a notebook with the
Editor, Story map and Asset tabs. File operations (Add files…, New script file, Rename,
Delete, New game) are ``files`` functions; their dialogs are in ``dialogs``. A check runner
(``check_runner=``, F45 ``07`` I-2; ``checker.CheckRunner`` by default) is asked for a check
at open, after saves, on F7, and ``CHECK_DEBOUNCE_MS`` after typing stops (F45 ``04`` §7.2):
load-only until the author's first Preview, Save or Check now (``07`` I-1). Each finished
check heads the problems panel (a summary, then one row per item), sets gutter markers
(``E``/``W``) on Tk marks that move with edits, and drives the check items of the status bar
(``views.StatusBar``, F45 ``01`` §6.5: the error and warning counts and one message). The
last good check's name index and label links live in ``check_names``, ``check_links`` and
``check_stale``:
completion (Ctrl+Space, ``views.CompletionPopup``) and the story map
(``views.StoryMapView``) read them. The Insert menu and the Help pane come from the
statement doc registry (``assist``). Each opened file keeps its own ``tk.Text`` for the
session, so switching files keeps the text and its undo history. Each editor ``Text``'s Tcl command is wrapped by
a Tcl proc (the ``rename`` proxy pattern IDLE uses): content commands mark the document
dirty, and every change or cursor move schedules one coalesced ``refresh`` that colors the
visible lines, redraws the line-number gutter, moves the current-line highlight, and updates
the start label and the status bar's cursor items. Word wrap is off (``04`` C3), so every row
on screen is one F02 line. Colors come from ``theme.THEME`` (VS Code Dark+, amended
2026-11-02); ``theme.style_ttk`` styles the ttk widgets.

Preview (F5, Shift+F5, the button) saves every unsaved file, checks the start values, and
hands argv to ``preview.PreviewRunner``, which the window polls every 100 ms. The status
bar's preview item shows the runner's state (``03`` §2.2), and the problems panel shows a
report's paragraphs;
a paragraph that names a listed file and a line is a link that jumps there (``03`` §3).

Imports only ``engine.core``, ``engine.script`` (through ``document`` and ``syntax``), and
the standard library; never pygame (TR-F44-01).
"""

import math
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk  # noqa: F401  (tests patch messagebox through here)

from engine.core.editorreport import CHECK_DEBOUNCE_MS, CHECK_SLOW_S, CHECK_TIMEOUT_S
from engine.core.errors import UserFacingError
from engine.core.paths import GamePaths, engine_root
from engine.script.assetgroups import CONFIG_REF
from engine.script.diagnostics import ScriptError
from engine.script.messages import show
from engine.script.statement_docs import StatementDoc
from engine.tools.editor import files
from engine.tools.editor.assist import (
    Context,
    auto_open,
    candidates,
    completion_context,
    help_for,
    insert_menu,
    insert_text,
    tag_help,
)
from engine.tools.editor.checker import CheckItem, CheckResult, CheckState, encode_overlay
from engine.tools.editor.config_help import (
    CONFIG_KINDS,
    auto_open_config,
    config_candidates,
    config_context,
    config_help,
    section_at,
)
from engine.tools.editor.dialogs import (
    APP_NAME,
    ask,
    ask_directory,
    ask_open_files,
    ask_text,
    show_error,
    show_info,
)
from engine.tools.editor.document import (
    SaveError,
    ScriptDocument,
    encode,
    open_config,
    open_document,
    retarget,
    save,
)
from engine.tools.editor.preview import (
    POLL_INTERVAL_MS,
    PreviewEvent,
    PreviewRunner,
    PreviewState,
    Report,
    ReportItem,
    preview_argv,
    start_value_args,
    start_values_report,
)
from engine.tools.editor.syntax import (
    LABEL_LINE,
    PLAIN_COLOR,
    SYNTAX_TAGS,
    TAG_COLORS,
    TAG_COMMENT,
    color_spans,
    indent_unit,
)
from engine.tools.editor.outline import outline
from engine.tools.editor.storymap import Box, label_notes
from engine.tools.editor.theme import THEME, STATUS_BAR_PX, dark_title_bar, scale_of, style_ttk
from engine.tools.editor.views import (
    DIRTY_MARK,
    AssetPane,
    CompletionPopup,
    HelpPane,
    OutlineView,
    ProjectView,
    StatusBar,
    StoryMapView,
    autohide,
    panel_header,
    read_asset,
)

# --- Text (03 §1.1, §2, §4; I-6, I-14; F45 01 §6) -------------------------------------------

TITLE_SUFFIX = " — vn-engine Studio"
PROJECT_HEADING = "Project"
ADD_BUTTON = "Add files…"
TAB_EDITOR = "Editor"
TAB_MAP = "Story map"
TAB_ASSET = "Asset"
TAB_OUTLINE = "Outline"                 # 2026-11-02, AC-F45-54
TAB_OUTLINE_INDEX = 3
SIDE_OPEN_TAB = "Open in Editor tab"     # the Story map's side editor (2026-11-02)
SIDE_CLOSE = "\u2715"
GO_TO_LABEL_ASK = "Go to label:"
GO_TO_LABEL_OK = "Go"
NO_SUCH_LABEL = "There is no label named `{name}` in the last check."
NO_LABELS_YET = "Labels are listed after the first check."
PICK_FOLDER = "Select a group or folder in the project panel first."
NEW_SCRIPT_ASK = "New script file in `{folder}/`:"
NEW_SCRIPT_OPTION = "Add an include line to main.vns"
RENAME_ASK = "New name for `{ref}`:"
ADD_NAME_OK = "Add"
CLASH_BUTTONS = ("Keep both", "Replace", "Skip")
CLASH_CHOICES = ("keep_both", "replace", "skip")
CLASH_ESCAPE = 2                        # Skip
RENAME_BUTTONS = ("Rename", "Cancel")
DELETE_BUTTONS = ("Delete", "Cancel")
DELETE_DEFAULT = 1                      # a destructive button is never the default (UI-F45-06)
ADD_POLL_MS = 50
START_VALUES_HEADING = "Start values"
START_VALUES_HINT = "One per line, e.g. sayo_points = 1"
PREVIEW_BUTTON = "Preview (F5)"
STARTS_AT = "Preview starts at:"
BEGINNING = "the beginning"
STATUS_NOT_RUNNING = "Not running."
STATUS_TEXTS = {                        # 03 §2.2; DIDNT_START is didnt_start_text(n)
    PreviewState.NOT_RUNNING: STATUS_NOT_RUNNING,
    PreviewState.STARTING: "Starting…",
    PreviewState.RUNNING: "Running. F5 restarts it.",
    PreviewState.CLOSED: "Closed.",
    PreviewState.STOPPED_ERROR: "Stopped with an error, listed in Problems.",
    PreviewState.STOPPED_UNEXPECTED: "Stopped unexpectedly.",
}
PROBLEMS_HEADING = "Problems"
PROBLEMS_HINT = "Problems that stop a preview appear here."
NO_PROBLEMS = "No problems."
CLOSE_BUTTONS = ("Save all", "Don't save", "Cancel")
CLOSE_ESCAPE = 2                        # Cancel (I-6)
CHANGED_BUTTONS = ("Keep mine", "Use the file on disk")
CHANGED_ESCAPE = 0                      # Keep mine, never "Use the file on disk" (I-6)
# Checks (F45 01 §6.3, §6.5, 04 §7.2 steps 6-8, C-4; amended 2026-11-02: the status bar).
CHECKING = "Checking…"
CHECK_OUT_OF_DATE = "Out of date"
CHECK_UNSAVED_NOT_CHECKED = "unsaved changes not checked"
ERROR_GLYPH = "\u2297"                  # ⊗, VS Code's error count
WARNING_GLYPH = "\u26a0"                # ⚠, its warning count
PREVIEW_GLYPH = "\u25b6 "               # ▶ before the preview state
EOL_NAMES = {"\n": "LF", "\r\n": "CRLF", "\r": "CR"}
CHECK_TIMEOUT_TEXT = (f"The check took longer than {CHECK_TIMEOUT_S} seconds and was stopped. "
                      "Press F7 to try again.")
CHECK_CRASHED_TEXT = "The check stopped unexpectedly. Press F7 to try again."
SEVERITY_WORDS = {"error": "Error", "warning": "Warning", "info": "Info"}
SHOW_WARNINGS = "Show warnings"         # View menu toggle (PR-F45-12)

# --- Sizes in pixels at 100 % scaling (03 §1.1, UI-F44-01) --------------------------------

# The editor window's own default size as a Tk geometry string. It is not the game canvas
# (AC-F01-48 keeps the canvas size in core/constants.py; its test looks for int literals).
WINDOW_GEOMETRY = "1100x720"
WINDOW_SIZE = tuple(int(part) for part in WINDOW_GEOMETRY.split("x"))
WINDOW_MIN_SIZE = (760, 480)
LEFT_WIDTH = 240
LEFT_MIN_WIDTH = 160
COLUMN_PAD = 8
EDITOR_MIN_HEIGHT = 160
PROBLEMS_HEIGHT = 160
PROBLEMS_SHARE = 0.6                    # Problems 60 %, Help 40 % (F45 01 §6.1)
BOTTOM_MIN_WIDTH = 120
PROBLEMS_MIN_HEIGHT = 80
TEXT_PAD = 4
SASH_WIDTH = 6
SIDE_SHARE = 0.45                       # the Story map's side editor at first (2026-11-02)
SIDE_MIN_WIDTH = 240
MAP_MIN_WIDTH = 200
CURSOR_WIDTH = 2
FONT_PX = 14                            # editor text, zoomable (03 §4, §7)
FONT_MIN_PX = 10
FONT_MAX_PX = 32
FONT_STEP_PX = 2
START_VALUES_PX = 12
START_VALUES_ROWS = 6
TAB_SPACES = 4
COMPLETION_PAGE = 10                    # rows Page Up / Page Down move in the list

# --- Colors (03 §1.2, §2.1, amended 2026-11-02: VS Code Dark+, all from theme.THEME) -------

BACKGROUND = THEME["editor.background"]
SIDE_BACKGROUND = THEME["sideBar.background"]
INPUT_BACKGROUND = THEME["input.background"]
GUTTER_BACKGROUND = THEME["gutter.background"]
GUTTER_FOREGROUND = THEME["gutter.foreground"]
GUTTER_CURRENT = THEME["gutter.activeForeground"]   # the cursor line's number
MESSAGE_FOREGROUND = THEME["muted"]     # read-only messages, the empty row, hints
JUMP_BACKGROUND = THEME["editor.jumpHighlight"]
LINE_BACKGROUND = THEME["editor.lineHighlight"]     # the cursor's line
CURSOR_COLOR = THEME["editor.cursor"]
FOCUS_BORDER = THEME["focusBorder"]
MARKER_COLORS = {"error": THEME["marker.error"],    # on GUTTER_BACKGROUND (UI-F45-03)
                 "warning": THEME["marker.warning"]}
MARKER_LETTERS = {"error": "E", "warning": "W"}             # info has no marker
MARKER_CHARS = 2                        # the gutter's marker column, in characters
MARK_PREFIX = "chk"                     # Tk marks chk0, chk1, … on each checked line
TAG_MARKER = "marker"                   # gutter canvas items that are markers
SELECTION_BACKGROUND = THEME["editor.selection"]
INACTIVE_SELECTION = THEME["editor.inactiveSelection"]
CHOSEN_BACKGROUND = THEME["list.activeSelection"]   # the problems panel's chosen row
LINK_FOREGROUND = THEME["link"]         # problems panel links (03 §3)
TAG_LINE = "current_line"               # the cursor's line, under jump and sel
TAG_JUMP = "jump"
TAG_HINT = "hint"
TAG_LINK = "link"                       # the location before the first ":" of a link
TAG_GAP = "gap"                         # 6 px above every paragraph but the first
TAG_CHOSEN = "chosen"                   # the selected paragraph while the panel has focus
TAG_CLICK = "clickable"                 # every clickable paragraph: the pointer is a hand
PARAGRAPH_PREFIX = "para"               # one tag per paragraph: para0, para1, …
PARAGRAPH_GAP = 6

HELP_LINE_CHARS = 4_096                 # Help and completion read this much of a line
OUTSIDE_CHECK_INTERVAL = 1.0            # seconds between disk checks on <FocusIn> (§7.2)
_MIN_COLORED_LINES = 60                 # lines colored per refresh when the view is unknown

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


def plural(count: int, word: str) -> str:
    """``1 file``, ``2 files`` (I-14)."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


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


def didnt_start_text(count: int) -> str:
    """``Didn't start: 1 problem, listed in Problems.`` (03 §2.2, I-14)."""
    return f"Didn't start: {plural(count, 'problem')}, listed in Problems."


def status_text(event: PreviewEvent) -> str:
    """The status line for a preview state (UI-F44-06)."""
    if event.state is PreviewState.DIDNT_START:
        return didnt_start_text(event.report.problem_count if event.report else 1)
    return STATUS_TEXTS[event.state]


def check_location(item: CheckItem) -> str:
    """F02's location form (``script/ch2.vns, line 9[, column 5]``, ``config.toml, line 2``),
    the file alone without a line, or ``""`` without a file."""
    if item.file is None:
        return ""
    where = show(item.file)
    if item.line is None:
        return where
    where += f", line {item.line}"
    return where + (f", column {item.column}" if item.column is not None else "")


def check_row_head(item: CheckItem) -> str:
    """``Error E43 script/ch2.vns, line 9``: the severity word, the code, the location."""
    word = SEVERITY_WORDS.get(item.severity, item.severity.capitalize())
    return " ".join(part for part in (word, item.code, check_location(item)) if part)


def check_row(item: CheckItem) -> str:
    """One problems-panel row: ``<Severity> <code> <location>: <text>`` (04 §7.2 step 7).
    Any ``source`` and code read the same way (PR-F45-08)."""
    return f"{check_row_head(item)}: {item.text}"


def check_counts(result: CheckResult) -> tuple[int, int]:
    """(errors, warnings) of a result. Info rows aren't counted (Gap G7)."""
    errors = sum(1 for item in result.problems if item.severity == "error")
    warnings = sum(1 for item in result.problems if item.severity == "warning")
    return errors, warnings


def check_summary(result: CheckResult) -> str:
    """``Checked: no problems.``, ``Checked: 2 errors, 1 warning.`` (01 §6.3): the problems
    panel's first row."""
    errors, warnings = check_counts(result)
    parts = [plural(count, word) for count, word in ((errors, "error"), (warnings, "warning"))
             if count]
    return "Checked: " + (", ".join(parts) if parts else "no problems") + "."


def counts_text(result: CheckResult) -> str:
    """The status bar's check counts, as VS Code shows them: ``⊗ 2  ⚠ 1`` (01 §6.5)."""
    errors, warnings = check_counts(result)
    return f"{ERROR_GLYPH} {errors}  {WARNING_GLYPH} {warnings}"


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


def _line_of(index: str) -> int:
    return int(str(index).split(".")[0])


@dataclass
class Paragraph:
    """One paragraph in the problems panel."""

    tag: str
    item: ReportItem | CheckItem | None     # None for a head, tail or summary line
    clickable: bool


@dataclass
class OpenFile:
    """One file in the editor: an editable document, or a read-only message."""

    ref: str
    widget: tk.Text
    doc: ScriptDocument | None = None
    error: ScriptError | None = None
    stamp: tuple[int, int] | None = None    # disk stamp of a read-only file
    marks: dict[str, CheckItem] = field(default_factory=dict)   # Tk mark -> its check item

    @property
    def editable(self) -> bool:
        return self.doc is not None

    @property
    def dirty(self) -> bool:
        return self.doc is not None and self.doc.dirty


def launch_studio(folder: Path) -> None:
    """Open Studio on a new game in its own process; this window stays open (a seam)."""
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(files.studio_argv(folder), cwd=engine_root(), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


class EditorWindow:
    """Studio on ``root`` for the game at ``paths`` (``03`` §1.1, F45 ``01`` §6.1).
    ``runner`` is the preview runner and ``check_runner`` the check runner; tests pass
    fakes (F45 ``07`` I-2)."""

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
        self._panel_view: tuple[str, object] = ("hint", PROBLEMS_HINT)   # preview's part
        self.show_warnings = tk.BooleanVar(master=root, value=True)     # View menu toggle
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
        self._help_key: tuple | None = None
        self._help_sash_placed = False
        self._line_shown: tuple[str, int] | None = None     # (widget, line) highlighted
        self._indent_key: tuple | None = None
        self._indent_shown = ""

        self._make_fonts()
        self._build_layout()
        self._build_menus()
        self._bind_keys()
        self.refresh_project()
        if self.refs:
            self.open_file(self.refs[0])
        else:
            self._show_empty()
        self._update_title()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.mod == "Command":
            root.createcommand("tk::mac::Quit", self.on_close)
        root.bind("<FocusIn>", self._on_focus_in, add="+")
        self.text.focus_set()
        self._poll_id = root.after(POLL_INTERVAL_MS, self._poll_preview)
        self.request_check()
        dark_title_bar(root)

    # --- Building ---------------------------------------------------------------------------

    def _make_fonts(self) -> None:
        family = tkfont.nametofont("TkFixedFont", root=self.root).actual("family")
        self.font_px = FONT_PX
        self.font = tkfont.Font(root=self.root, family=family, size=-FONT_PX)
        self.start_values_font = tkfont.Font(root=self.root, family=family,
                                             size=-START_VALUES_PX)
        self.ui_font = tkfont.nametofont("TkDefaultFont", root=self.root)

    def _build_layout(self) -> None:
        root = self.root
        width, height = WINDOW_SIZE
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(*WINDOW_MIN_SIZE)
        root.configure(background=BACKGROUND)
        self._theme_fonts = style_ttk(root)
        self.scale = scale_of(root)

        # The status bar is packed first, so it keeps its line at the minimum size.
        self._build_status_bar()
        sash = THEME["sash"]
        self.hpane = tk.PanedWindow(root, orient="horizontal", sashwidth=SASH_WIDTH,
                                    borderwidth=0, sashrelief="flat", background=sash)
        self.hpane.pack(fill="both", expand=True)
        self.left = ttk.Frame(self.hpane, padding=COLUMN_PAD, width=LEFT_WIDTH,
                              style="Side.TFrame")
        self.hpane.add(self.left, width=LEFT_WIDTH, minsize=LEFT_MIN_WIDTH, stretch="never")
        self.vpane = tk.PanedWindow(self.hpane, orient="vertical", sashwidth=SASH_WIDTH,
                                    borderwidth=0, sashrelief="flat", background=sash)
        self.hpane.add(self.vpane, minsize=LEFT_MIN_WIDTH, stretch="always")
        self.hpane.bind("<Configure>", self._limit_left_column, add="+")
        self.hpane.bind("<ButtonRelease-1>", self._limit_left_column, add="+")
        self.hpane.bind("<B1-Motion>", self._limit_left_column, add="+")

        self._build_left_column()
        # F45 01 §6.1: the right area is a notebook with fixed tabs (no Ctrl+Tab traversal:
        # Ctrl+1/2/3 switch them).
        self.notebook = ttk.Notebook(self.vpane, takefocus=0)
        self.editor_frame = ttk.Frame(self.notebook)
        # The Story map tab: the map, and beside it (after a click) the side editor.
        self.map_frame = ttk.Frame(self.notebook)
        self.map_split = tk.PanedWindow(self.map_frame, orient="horizontal",
                                        sashwidth=SASH_WIDTH, borderwidth=0,
                                        sashrelief="flat", background=sash)
        self.map_split.pack(fill="both", expand=True)
        map_box = ttk.Frame(self.map_split, padding=8)
        self.map_split.add(map_box, minsize=MAP_MIN_WIDTH, stretch="always")
        self.story_map = StoryMapView(map_box, background=BACKGROUND,
                                      family=self.ui_font.actual("family"), mod=self.mod,
                                      on_open=self.open_label_beside,
                                      on_open_tab=self.open_label_box)
        self.story_map.frame.pack(fill="both", expand=True)
        self.map_canvas = self.story_map.canvas
        self.asset_pane = AssetPane(self.notebook)
        self.notebook.add(self.editor_frame, text=TAB_EDITOR)
        self.notebook.add(self.map_frame, text=TAB_MAP)
        self.notebook.add(self.asset_pane.frame, text=TAB_ASSET)
        self.outline_view = OutlineView(self.notebook, on_open=self.jump_to)
        self.notebook.add(self.outline_view.frame, text=TAB_OUTLINE)
        self.vpane.add(self.notebook, minsize=EDITOR_MIN_HEIGHT, stretch="always")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")
        # Below the notebook: Problems (60 %) and Help (40 %) with a draggable divider.
        self.bottom = tk.PanedWindow(self.vpane, orient="horizontal", sashwidth=SASH_WIDTH,
                                     borderwidth=0, sashrelief="flat", background=sash)
        self.vpane.add(self.bottom, height=PROBLEMS_HEIGHT, minsize=PROBLEMS_MIN_HEIGHT,
                       stretch="never")
        self.problems_frame = ttk.Frame(self.bottom)
        self.bottom.add(self.problems_frame, minsize=BOTTOM_MIN_WIDTH, stretch="always")
        self.help_pane = HelpPane(self.bottom, font=self.ui_font, code_font=self.font,
                                  background=BACKGROUND, pad=TEXT_PAD)
        self.help_text = self.help_pane.text
        self.bottom.add(self.help_pane.frame, minsize=BOTTOM_MIN_WIDTH, stretch="always")
        self.bottom.bind("<Configure>", self._place_help_sash, add="+")
        self.help_pane.show(None)
        self.popup = CompletionPopup(self.root, font=self.font)
        self.popup.on_pick = lambda index: self.accept_completion(index)
        self._build_editor_area()
        self._build_side_pane()
        self._build_problems_panel()

    def _build_left_column(self) -> None:
        left = self.left
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.grid_propagate(False)
        head = ttk.Frame(left, style="Side.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text=PROJECT_HEADING.upper(), style="SideTitle.TLabel").grid(
            row=0, column=0, sticky="w")
        self.add_button = ttk.Button(head, text=ADD_BUTTON, command=self.add_files,
                                     takefocus=0, style="Secondary.TButton")
        self.add_button.grid(row=0, column=1, sticky="e")
        self.project_view = ProjectView(left, font=self.ui_font, background=BACKGROUND,
                                        on_select=self._on_tree_select)
        self.project_view.frame.grid(row=1, column=0, sticky="nsew", pady=(2, 0))
        self.tree = self.project_view.tree
        for key in ("<Return>", "<KP_Enter>"):
            self.tree.bind(key, self._focus_editor)
        self.tree.bind("<F2>", lambda _e: self._break(self.rename_selected))
        self.tree.bind("<Delete>", lambda _e: self._break(self.delete_selected))

        ttk.Label(left, text=START_VALUES_HEADING.upper(), style="SideTitle.TLabel").grid(
            row=2, column=0, sticky="w", pady=(COLUMN_PAD, 0))
        self.start_values_hint = ttk.Label(left, text=START_VALUES_HINT,
                                           foreground=MESSAGE_FOREGROUND, style="Side.TLabel",
                                           wraplength=LEFT_WIDTH - 2 * COLUMN_PAD)
        self.start_values_hint.grid(row=3, column=0, sticky="w")
        box = ttk.Frame(left, style="Side.TFrame")
        box.grid(row=4, column=0, sticky="ew", pady=(2, 0))
        box.columnconfigure(0, weight=1)
        self.start_values = tk.Text(
            box, height=START_VALUES_ROWS, width=1, wrap="none", undo=True, maxundo=-1,
            font=self.start_values_font, background=INPUT_BACKGROUND, foreground=PLAIN_COLOR,
            insertbackground=CURSOR_COLOR, insertwidth=CURSOR_WIDTH,
            selectbackground=SELECTION_BACKGROUND, inactiveselectbackground=INACTIVE_SELECTION,
            padx=TEXT_PAD, pady=TEXT_PAD, highlightthickness=1,
            highlightbackground=INPUT_BACKGROUND, highlightcolor=FOCUS_BORDER, borderwidth=0,
            relief="flat")
        self.start_values.tag_configure("sel", foreground=PLAIN_COLOR)
        self.start_values.grid(row=0, column=0, sticky="ew")
        values_bar = ttk.Scrollbar(box, orient="vertical", command=self.start_values.yview,
                                   style="Side.Vertical.TScrollbar")
        self.start_values.configure(yscrollcommand=_autohide(values_bar, row=0, column=1,
                                                             sticky="ns"))

        self.preview_button = ttk.Button(left, text=PREVIEW_BUTTON, command=self.preview)
        for key in ("<Return>", "<KP_Enter>"):          # Space works by itself
            self.preview_button.bind(key, lambda _e: self._break(self.preview))
        self.preview_button.grid(row=5, column=0, sticky="ew", pady=(COLUMN_PAD, 0))
        wrap = LEFT_WIDTH - 2 * COLUMN_PAD
        ttk.Label(left, text=STARTS_AT, style="Side.TLabel").grid(row=6, column=0, sticky="w",
                                                                  pady=(COLUMN_PAD, 0))
        self.start_label = ttk.Label(left, text=BEGINNING, wraplength=wrap, justify="left",
                                     style="Side.TLabel")
        self.start_label.grid(row=7, column=0, sticky="w")
        self._wrapped_labels = (self.start_values_hint, self.start_label)
        left.bind("<Configure>", self._rewrap_left, add="+")

    def _build_status_bar(self) -> None:
        """F45 01 §6.5 (amended 2026-11-02): the game folder, the check's counts and message,
        and the preview state on the left; the cursor's line and column, the indent, the
        encoding and the line ending on the right. The check items focus Problems when
        clicked; the folder name focuses the project panel."""
        linespace = self.ui_font.metrics("linespace")
        height = max(round(STATUS_BAR_PX * self.scale), linespace + 4)
        bar = self.status_bar = StatusBar(self.root, font=self.ui_font, height=height,
                                          scale=self.scale)
        self.game_item = bar.add(text=self.game_name, shrink=2,
                                 on_click=lambda: self.tree.focus_set())
        self.check_counts = bar.add(on_click=self.focus_problems)
        self.check_status = bar.add(shrink=3, on_click=self.focus_problems)
        self.status_label = bar.add(prefix=PREVIEW_GLYPH, shrink=1, text=STATUS_NOT_RUNNING)
        self.cursor_item = bar.add(side="right")
        self.indent_item = bar.add(side="right")
        self.encoding_item = bar.add(side="right")
        self.eol_item = bar.add(side="right")
        bar.frame.pack(side="bottom", fill="x")

    def focus_problems(self) -> None:
        """A click on the status bar's check items: the keyboard focus to Problems."""
        if not self.closed:
            self.problems.focus_set()

    def _build_editor_area(self) -> None:
        frame = self.editor_frame
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)
        self.gutter = tk.Canvas(frame, width=self._gutter_width(1), background=GUTTER_BACKGROUND,
                                highlightthickness=0, borderwidth=0, takefocus=0)
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.vbar = ttk.Scrollbar(frame, orient="vertical")
        self.vbar.grid(row=0, column=2, sticky="ns")
        self.hbar = ttk.Scrollbar(frame, orient="horizontal")
        self._hbar_set = _autohide(self.hbar, row=1, column=1, sticky="ew")

    def _build_side_pane(self) -> None:
        """The Story map's side editor: a header (the file, Open in Editor tab, ✕) over a
        gutter and the peer text. Added to ``map_split`` only while open."""
        side = self.side_frame = ttk.Frame(self.map_split)
        side.columnconfigure(1, weight=1)
        side.rowconfigure(1, weight=1)
        head = ttk.Frame(side, style="Header.TFrame")
        head.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.side_name = ttk.Label(head, text="", style="Header.TLabel")
        self.side_name.pack(side="left", padx=TEXT_PAD * 2)
        self.side_close_button = ttk.Button(head, text=SIDE_CLOSE, width=3, takefocus=0,
                                            style="Secondary.TButton",
                                            command=self.close_side)
        self.side_close_button.pack(side="right", padx=(TEXT_PAD, TEXT_PAD), pady=TEXT_PAD)
        self.side_open_button = ttk.Button(head, text=SIDE_OPEN_TAB, takefocus=0,
                                           style="Secondary.TButton",
                                           command=self.side_to_editor)
        self.side_open_button.pack(side="right", pady=TEXT_PAD)
        self.side_gutter = tk.Canvas(side, width=self._gutter_width(1),
                                     background=GUTTER_BACKGROUND, highlightthickness=0,
                                     borderwidth=0, takefocus=0)
        self.side_gutter.grid(row=1, column=0, sticky="ns")
        self.side_vbar = ttk.Scrollbar(side, orient="vertical")
        self.side_vbar.grid(row=1, column=2, sticky="ns")
        self.side_hbar = ttk.Scrollbar(side, orient="horizontal")
        self._side_hbar_set = _autohide(self.side_hbar, row=2, column=1, sticky="ew")

    def _build_problems_panel(self) -> None:
        frame = self.problems_frame
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        panel_header(frame, PROBLEMS_HEADING, TEXT_PAD).grid(row=0, column=0, columnspan=2,
                                                             sticky="ew")
        self.problems = tk.Text(
            frame, wrap="word", width=1, height=1, font=self.ui_font, background=BACKGROUND,
            foreground=PLAIN_COLOR, selectbackground=SELECTION_BACKGROUND,
            inactiveselectbackground=INACTIVE_SELECTION, padx=2 * TEXT_PAD, pady=TEXT_PAD,
            highlightthickness=1, highlightbackground=BACKGROUND, highlightcolor=FOCUS_BORDER,
            borderwidth=0, takefocus=1, cursor="arrow")
        panel = self.problems
        panel.tag_configure(TAG_HINT, foreground=MESSAGE_FOREGROUND)
        panel.tag_configure(TAG_LINK, foreground=LINK_FOREGROUND, underline=True)
        panel.tag_configure(TAG_GAP, spacing1=PARAGRAPH_GAP)
        panel.tag_configure(TAG_CHOSEN, background=CHOSEN_BACKGROUND)
        panel.tag_configure("sel", foreground=PLAIN_COLOR)
        panel.tag_bind(TAG_CLICK, "<Enter>", lambda _e: panel.configure(cursor="hand2"))
        panel.tag_bind(TAG_CLICK, "<Leave>", lambda _e: panel.configure(cursor="arrow"))
        panel.tag_raise("sel")
        panel.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(frame, orient="vertical", command=panel.yview)
        panel.configure(yscrollcommand=autohide(bar, row=1, column=1, sticky="ns"))
        self.show_hint(PROBLEMS_HINT)
        # A click focuses the panel even though its text is read-only. A click on a link
        # (not a drag that selects text) jumps.
        panel.bind("<Button-1>", lambda _e: panel.focus_set(), add="+")
        panel.bind("<ButtonRelease-1>", self._on_panel_click, add="+")
        panel.bind("<FocusIn>", self._on_panel_focus_in, add="+")
        panel.bind("<FocusOut>", lambda _e: panel.tag_remove(TAG_CHOSEN, "1.0", "end"),
                   add="+")
        panel.bind("<Up>", lambda _e: self._break(self.choose_paragraph, -1))
        panel.bind("<Down>", lambda _e: self._break(self.choose_paragraph, 1))
        for key in ("<Return>", "<KP_Enter>"):
            panel.bind(key, lambda _e: self._break(self.activate_chosen))

    def _build_menus(self) -> None:
        """F45 01 §6.1's menus: File, Edit, Insert (the doc registry's groups), View, Run,
        Help. File's operations are disabled while the game folder can't be found
        (AC-F45-26)."""
        key = "Cmd" if self.mod == "Command" else "Ctrl"
        bar = tk.Menu(self.root, tearoff=0)
        self.file_menu = menu = tk.Menu(bar, tearoff=0)
        menu.add_command(label="New game…", command=self.new_game)
        menu.add_command(label="New script file", accelerator=f"{key}+N",
                         command=self.new_script_file)
        menu.add_command(label=ADD_BUTTON, accelerator=f"{key}+Shift+O",
                         command=self.add_files)
        menu.add_command(label="Rename", accelerator="F2", command=self.rename_selected)
        menu.add_command(label="Delete", accelerator="Delete", command=self.delete_selected)
        menu.add_separator()
        menu.add_command(label="Save", accelerator=f"{key}+S", command=self.save_current)
        menu.add_command(label="Save all", accelerator=f"{key}+Shift+S", command=self.save_all)
        menu.add_separator()
        menu.add_command(label="Close", command=self.on_close)
        bar.add_cascade(label="File", menu=menu)
        self.file_ops = ("New script file", ADD_BUTTON, "Rename", "Delete")

        edit = tk.Menu(bar, tearoff=0)
        for label, accel, action in (
                ("Undo", f"{key}+Z", lambda: self._undo(self.text)),
                ("Redo", f"{key}+Y", lambda: self._redo(self.text)),
                ("Cut", f"{key}+X", lambda: self._clipboard(self.text, "<<Cut>>")),
                ("Copy", f"{key}+C", lambda: self._clipboard(self.text, "<<Copy>>")),
                ("Paste", f"{key}+V", lambda: self._clipboard(self.text, "<<Paste>>"))):
            edit.add_command(label=label, accelerator=accel, command=action)
        edit.add_separator()
        edit.add_command(label="Complete", accelerator=f"{key}+Space", command=self.complete)
        edit.add_command(label="Go to label…", accelerator=f"{key}+G",
                         command=self.go_to_label)
        bar.add_cascade(label="Edit", menu=edit)

        # Insert: one submenu per GROUPS entry with docs, built once from the registry.
        self.insert_menu = tk.Menu(bar, tearoff=0)
        self.insert_submenus: dict[str, tk.Menu] = {}
        for group, docs in insert_menu():
            sub = tk.Menu(self.insert_menu, tearoff=0)
            for doc in docs:
                sub.add_command(label=doc.title, command=lambda d=doc: self.insert_doc(d))
            self.insert_menu.add_cascade(label=group, menu=sub)
            self.insert_submenus[group] = sub
        bar.add_cascade(label="Insert", menu=self.insert_menu)

        view = tk.Menu(bar, tearoff=0)
        for index, label in enumerate((TAB_EDITOR, TAB_MAP, TAB_ASSET, TAB_OUTLINE)):
            view.add_command(label=label, accelerator=f"{key}+{index + 1}",
                             command=lambda i=index: self.show_tab(i))
        view.add_separator()
        view.add_command(label="Zoom in", accelerator=f"{key}+=",
                         command=lambda: self.zoom_view(FONT_STEP_PX))
        view.add_command(label="Zoom out", accelerator=f"{key}+-",
                         command=lambda: self.zoom_view(-FONT_STEP_PX))
        view.add_command(label="Actual size", accelerator=f"{key}+0",
                         command=lambda: self.zoom_view(0))
        view.add_separator()
        view.add_checkbutton(label=SHOW_WARNINGS, variable=self.show_warnings,
                             command=self.render_panel)
        bar.add_cascade(label="View", menu=view)

        run = tk.Menu(bar, tearoff=0)
        run.add_command(label="Preview", accelerator="F5", command=self.preview)
        run.add_command(label="Preview from start", accelerator="Shift+F5",
                        command=lambda: self.preview(False))
        run.add_command(label="Check now", accelerator="F7", command=self.check_now)
        bar.add_cascade(label="Run", menu=run)

        help_menu = tk.Menu(bar, tearoff=0)
        help_menu.add_command(label="Help for this line", command=self.focus_help)
        bar.add_cascade(label="Help", menu=help_menu)
        self.edit_menu, self.view_menu, self.run_menu = edit, view, run
        self.help_menu = help_menu
        self.menubar = bar
        self.root.configure(menu=bar)

    def _set_file_ops(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for label in self.file_ops:
            self.file_menu.entryconfigure(label, state=state)
        self.add_button.configure(state=state)

    def file_ops_enabled(self) -> bool:
        return str(self.file_menu.entrycget(ADD_BUTTON, "state")) == "normal"

    def show_tab(self, index: int) -> None:
        """Ctrl+1 / Ctrl+2 / Ctrl+3: the Editor, Story map, or Asset tab, with the keyboard
        focus in it."""
        if index == 0 and self._side_has_focus():
            self.side_to_editor()           # the Editor tab at the side editor's cursor
            return
        self.notebook.select(index)
        if index == 1:
            self.refresh_story_map()
        if index == TAB_OUTLINE_INDEX:
            self.refresh_outline()
        self._tab_widget().focus_set()

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        self.close_completion()
        self._schedule_refresh()            # the gutter of the editor now on screen
        if not self.closed and self.notebook.index("current") == 1:
            self.refresh_story_map()
        if not self.closed and self.notebook.index("current") == TAB_OUTLINE_INDEX:
            self.refresh_outline()

    def _place_help_sash(self, event: tk.Event) -> None:
        """Problems 60 %, Help 40 % at first; the author's drag is kept after that."""
        if self._help_sash_placed or event.width <= 1:
            return
        self._help_sash_placed = True
        self.bottom.sash_place(0, int(event.width * PROBLEMS_SHARE), 0)

    def zoom_view(self, step: int) -> None:
        """Ctrl+= / Ctrl+- / Ctrl+0: the story map's zoom on the Story map tab, else the
        editor text's."""
        if self.notebook.index("current") == 1 and not self._side_has_focus():
            self.story_map.zoom_by(step)
        else:
            self.zoom(step)

    def _limit_left_column(self, _event: tk.Event | None = None) -> None:
        """The left column stays between 160 px and half the window (03 §1.1)."""
        total = self.hpane.winfo_width()
        if total <= 1:
            return
        x, y = self.hpane.sash_coord(0)
        limit = max(LEFT_MIN_WIDTH, total // 2)
        if x > limit:
            self.hpane.sash_place(0, limit, y)

    def _rewrap_left(self, event: tk.Event) -> None:
        wrap = max(40, event.width - 2 * COLUMN_PAD)
        for label in self._wrapped_labels:
            label.configure(wraplength=wrap)

    # --- Editor widgets ---------------------------------------------------------------------

    def _text_options(self, *, editable: bool) -> dict[str, object]:
        return dict(
            wrap="none", undo=editable, maxundo=-1, autoseparators=True,
            width=1, height=1, font=self.font, padx=TEXT_PAD, pady=TEXT_PAD,
            background=BACKGROUND, foreground=PLAIN_COLOR, insertbackground=CURSOR_COLOR,
            insertwidth=CURSOR_WIDTH, selectbackground=SELECTION_BACKGROUND,
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
        result = self._open_any(ref)
        if isinstance(result, ScriptDocument):
            widget = self._make_text(editable=True)
            record = OpenFile(ref, widget, doc=result)
            self._install_change_hook(widget)
            self._set_text(record, result.text)
            result.text = ""
            widget.mark_set("insert", "1.0")
            self._place_marks(record)
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
            self.vbar.configure(command=widget.yview)
            self.hbar.configure(command=widget.xview)
            self.vbar.set(*widget.yview())
            self._hbar_set(*widget.xview())
            if had_focus:
                widget.focus_set()
        if self._side_open and self._side_source is not widget:
            if self.current is not None and self.current.editable \
                    and widget is self.current.widget:
                self._make_side_peer(widget)    # the side editor follows the file
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
            self.notebook.select(0)
        elif node.kind == "file":
            self.show_asset(node)

    def show_asset(self, node: files.TreeNode | str,
                   box: tuple[int, int] | None = None) -> None:
        """The Asset tab for a non-script file (a tree node or a ref): its facts, and a
        thumbnail for a PNG or GIF within the caps (PR-F45-20, 04 §7.7)."""
        ref = node if isinstance(node, str) else node.ref
        self.asset_pane.show(read_asset(self.paths, ref), box=box)
        self.notebook.select(2)

    def _focus_editor(self, _event: tk.Event | None = None) -> str:
        if self._openable(self.project_view.selected()) or _event is None:
            self.notebook.select(0)
            self.text.focus_set()
        return "break"

    def open_file(self, ref: str) -> OpenFile:
        """Show ``ref`` in the editor, opening it on first use (switching keeps unsaved
        edits, PR-F44-04)."""
        record = self._record(ref)
        self.current = record
        self._show(record.widget)
        self.notebook.select(0)
        self._select_current_row()
        return record

    def _record(self, ref: str) -> OpenFile:
        record = self.files.get(ref)
        if record is None:
            record = self.files[ref] = self._new_record(ref)
        return record

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
        if self.current is record:
            self.current = None
            others = [r for r in self.refs if r != ref]
            if others:
                self.open_file(others[0])
            else:
                self._show_empty()
        record.widget.destroy()
        self._update_marks()

    # --- File operations (F45 PR-F45-02..06, 04 §7.5) ---------------------------------------

    def _target_folder(self) -> tuple[str, str] | None:
        """(group key, folder ref) for the selected row: a group or folder itself, or a
        file's folder. None for ``config.toml`` or no selection."""
        node = self.project_view.node(self.project_view.selected())
        if node is None or node.kind == "config":
            return None
        if node.kind == "file":
            return node.group, node.ref.rsplit("/", 1)[0]
        return node.group, node.ref

    def add_files(self, sources: Sequence[Path] | None = None) -> None:
        """Add files…: pick files, plan them, settle names and clashes in dialogs, then copy
        them on a worker thread; the summary shows when the last one is done."""
        if self.closed or self.adding or not self.file_ops_enabled():
            return
        target = self._target_folder()
        if target is None:
            show_error(self.root, PICK_FOLDER)
            return
        key, folder_ref = target
        if sources is None:
            sources = ask_open_files(self.root)
        if not sources:
            return
        plans = files.plan_add(self.paths, key, folder_ref, sources)
        jobs: list[tuple[files.AddPlan, str]] = []
        refused: list[files.AddOutcome] = []
        for plan in plans:
            settled = self._settle_name(plan)
            if settled is None:
                continue
            if settled.refusal is not None:
                refused.append(files.AddOutcome(settled.label, reason=settled.refusal))
                continue
            choice = "new"
            if settled.clash is not None:
                answer = ask(self.root, files.clash_message(f"{folder_ref}/{settled.clash}"),
                             CLASH_BUTTONS, escape=CLASH_ESCAPE)
                choice = CLASH_CHOICES[answer]
                if choice == "skip":
                    continue
            jobs.append((settled, choice))
        self._start_adding(jobs, refused)

    def _settle_name(self, plan: files.AddPlan) -> files.AddPlan | None:
        """Ask for a better name while the plan has an image-name problem; None to skip."""
        while plan.refusal is None and plan.problem is not None:
            answer = ask_text(self.root, plan.problem, plan.offer or plan.name,
                              ok=ADD_NAME_OK,
                              hint=lambda name, f=plan.folder_ref: files.show_hint(f, name))
            if answer is None:
                return None
            plan = files.rename_plan(self.paths, plan, answer[0])
        return plan

    def _start_adding(self, jobs: list[tuple[files.AddPlan, str]],
                      refused: list[files.AddOutcome]) -> None:
        self._add_outcomes = list(refused)
        if not jobs:
            if refused:
                show_info(self.root, files.add_summary(self._add_outcomes))
            return
        self.adding = True
        worker_paths = GamePaths(self.paths.root)      # its own listing cache
        out = self._add_queue

        def work() -> None:
            try:
                for plan, choice in jobs:
                    out.put(files.run_add(worker_paths, plan, choice))  # type: ignore[arg-type]
            finally:
                out.put(None)

        threading.Thread(target=work, name="studio-add", daemon=True).start()
        self._add_id = self.root.after(ADD_POLL_MS, self._poll_adding)

    def _poll_adding(self) -> None:
        self._add_id = None
        if self.closed:
            return
        done = False
        while True:
            try:
                item = self._add_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                done = True
                break
            self._add_outcomes.append(item)
        if not done:
            self._add_id = self.root.after(ADD_POLL_MS, self._poll_adding)
            return
        self.adding = False
        added = [o.ref for o in self._add_outcomes if o.ref is not None]
        self.refresh_project()
        if added:
            self.project_view.select(added[-1])
        show_info(self.root, files.add_summary(self._add_outcomes))

    def new_script_file(self) -> None:
        """Ctrl+N: a new ``.vns`` file in ``script/`` (or the selected script subfolder),
        with an ``include`` line added to ``main.vns``'s text when the option is ticked."""
        if self.closed or not self.file_ops_enabled():
            return
        target = self._target_folder()
        folder = target[1] if target is not None and target[0] == "script" else "script"
        answer = ask_text(self.root, NEW_SCRIPT_ASK.format(folder=show(folder)), "new.vns",
                          ok="Create", option=NEW_SCRIPT_OPTION, option_value=True)
        if answer is None:
            return
        name, include = answer
        result = files.new_script(self.paths, folder, name)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return
        self.refresh_project()
        if include and result != files.MAIN_REF:
            self._add_include(result)
        self.open_file(result)
        self.notebook.select(0)

    def _add_include(self, new_ref: str) -> None:
        """Put ``include "<path>"`` into ``main.vns``'s text as one undo step; it stays
        unsaved until the author saves."""
        if files.MAIN_REF not in self.refs:
            return
        record = self._record(files.MAIN_REF)
        if not record.editable:
            return
        widget = record.widget
        line = files.include_position(widget.get("1.0", "end-1c"))
        last = _line_of(widget.index("end-1c"))
        text = files.include_line(new_ref)

        def act() -> None:
            if line > last:
                widget.insert("end-1c", "\n" + text)
            else:
                widget.insert(f"{line}.0", text + "\n")

        self._as_one_step(widget, act)

    def rename_selected(self) -> None:
        """F2: rename the selected file in its folder after a confirmation."""
        ref = self.project_view.selected()
        if self.closed or ref is None or not self.file_ops_enabled():
            return
        problem = self._fixed(ref)
        if problem is not None:
            show_error(self.root, problem)
            return
        old_name = ref.rsplit("/", 1)[1]
        answer = ask_text(self.root, RENAME_ASK.format(ref=show(ref)), old_name, ok="Rename",
                          hint=lambda name, f=ref.rsplit("/", 1)[0]: files.show_hint(f, name))
        if answer is None or answer[0] == old_name:
            return
        new_name = answer[0]
        record = self.files.get(ref)
        message = files.rename_message(ref, new_name, unsaved=record is not None
                                       and record.dirty)
        if ask(self.root, message, RENAME_BUTTONS, escape=1) != 0:
            return
        result = files.rename_file(self.paths, ref, new_name)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return
        if record is not None:
            self.files.pop(ref)
            if record.doc is not None:
                try:
                    retarget(record.doc, self.paths, result)
                except UserFacingError:
                    record.widget.destroy()
                    record = None
            if record is not None:
                record.ref = result
                self.files[result] = record
            elif self.current is not None and self.current.ref == ref:
                self.current = None
        self.refresh_project()
        if self.current is None:
            self._show_empty()
        self.project_view.select(result)
        self._update_marks()

    def delete_selected(self) -> None:
        """Delete: remove the selected file from the disk after a confirmation whose
        default and Esc are Cancel. An open copy closes; its unsaved text is dropped."""
        ref = self.project_view.selected()
        if self.closed or ref is None or not self.file_ops_enabled():
            return
        problem = self._fixed(ref)
        if problem is not None:
            show_error(self.root, problem)
            return
        record = self.files.get(ref)
        message = files.delete_message(ref, unsaved=record is not None and record.dirty)
        if ask(self.root, message, DELETE_BUTTONS, escape=1, default=DELETE_DEFAULT) != 0:
            return
        result = files.delete_file(self.paths, ref)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return
        self.refresh_project()
        self._drop_record(ref)

    def _fixed(self, ref: str) -> str | None:
        """Why the row ``ref`` can't be renamed or deleted, or None."""
        fixed = files.fixed_reason(ref)
        if fixed is not None:
            return fixed
        node = self.project_view.node(ref)
        if node is None or node.kind != "file":
            return files.FOLDER_FIXED
        return None

    def new_game(self) -> None:
        """File ▸ New game…: create a game from the starter in a new or empty folder and
        open it in its own Studio; this window stays open."""
        if self.closed:
            return
        folder = ask_directory(self.root)
        if folder is None:
            return
        result = files.new_game(folder)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return
        launch_studio(result)

    # --- Checks (F45 04 §7.2, 07 I-1, I-2) --------------------------------------------------

    def request_check(self) -> None:
        """Ask the check runner for a check of the saved files plus the unsaved text of every
        dirty document (the overlay; C-4: past its caps, the saved files only, and the
        status says so). Load-only until the window is armed (F45 ``07`` I-1). Never
        blocks."""
        if self.closed:
            return
        self._cancel_debounce()
        overlay, unsaved = self._overlay()
        self._check_unsaved = unsaved
        self._check_serial = self.edit_serial
        self.check_running = True
        self._check_failure = None
        self.check_runner.request(overlay, self.edit_serial, launch=self.armed)
        self._update_check_status()

    def _overlay(self) -> tuple[bytes | None, bool]:
        """(overlay, whether unsaved text is left out): ``encode(doc, text)`` of each dirty
        document, or None when there is none or ``encode_overlay`` refuses."""
        dirty = self.dirty_files()
        if not dirty:
            return None, False
        entries: list[tuple[str, bytes]] = []
        for record in dirty:
            assert record.doc is not None
            try:
                entries.append((record.ref, encode(record.doc,
                                                   record.widget.get("1.0", "end-1c"))))
            except SaveError:                   # a lone surrogate: saved files only
                return None, True
        overlay = encode_overlay(entries)
        return overlay, overlay is None

    def check_now(self) -> None:
        """F7: check now; arms the window."""
        self.armed = True
        self.request_check()

    def _schedule_auto_check(self) -> None:
        """Check ``CHECK_DEBOUNCE_MS`` after the last content change (PR-F45-11)."""
        self._cancel_debounce()
        if not self.closed:
            self._debounce_id = self.root.after(CHECK_DEBOUNCE_MS, self._auto_check)

    def _cancel_debounce(self) -> None:
        if self._debounce_id is not None:
            try:
                self.root.after_cancel(self._debounce_id)
            except tk.TclError:
                pass
            self._debounce_id = None

    def _auto_check(self) -> None:
        """The debounced check; paused while the last check took over ``CHECK_SLOW_S``
        (saves and F7 still check)."""
        self._debounce_id = None
        if self.closed or (self.check_result is not None
                           and self.check_result.seconds > CHECK_SLOW_S):
            return
        self.request_check()

    def apply_check_events(self, events: Sequence[object]) -> None:
        """The runner's events (polled every 100 ms): ``DONE`` replaces the result, the
        rows, the markers and the name index in one step; ``TIMEOUT`` and ``CRASHED`` keep
        them and show one status line."""
        changed = False
        for event in events:
            state = getattr(event, "state", None)
            if state not in (CheckState.DONE, CheckState.TIMEOUT, CheckState.CRASHED):
                continue                        # STARTED: still Checking…
            if getattr(event, "serial", -1) >= self._check_serial:
                self.check_running = False
            if state is CheckState.DONE:
                result = getattr(event, "result", None)
                if result is not None:
                    self._apply_result(result)
                    self._check_failure = None
            else:
                self._check_failure = (CHECK_TIMEOUT_TEXT if state is CheckState.TIMEOUT
                                       else CHECK_CRASHED_TEXT)
            changed = True
        if changed and not self.closed:
            self._update_check_status()

    def _apply_result(self, result: CheckResult) -> None:
        self.check_result = result
        # The name index keeps every kind this run didn't send, and the links of the last
        # check that loaded the script (04 §4.2).
        names = dict(self._check_names)
        names.update({kind: tuple(entries) for kind, entries in result.names.items()})
        if result.loaded:            # a kind this run counted 0 of is now empty (2026-11-02)
            names.update({kind: () for kind, total in result.name_totals.items()
                          if total == 0})
        self._check_names = names
        if result.links is not None:
            self._check_links = tuple(result.links)
        self._check_stale = result.links is None
        self._index_changed()
        for record in self.files.values():
            self._place_marks(record)
        self.render_panel()
        self._schedule_refresh()

    def check_status_text(self) -> str:
        """The status bar's check message without the cursor's item (04 §7.2 step 6, 01
        §6.5): the timeout or crash line; ``Checking…`` while a check runs; ``Out of date``
        after an edit the newest result hasn't seen; ``""`` otherwise. ``unsaved changes not
        checked`` is added while the overlay was left out (C-4)."""
        result = self.check_result
        if self._check_failure is not None and not self.check_running:
            return self._check_failure
        if self.check_running:
            text = CHECKING
        elif result is not None and result.serial < self.edit_serial:
            text = CHECK_OUT_OF_DATE
        else:
            text = ""
        if self._check_unsaved:
            unsaved = CHECK_UNSAVED_NOT_CHECKED
            text = f"{text} ({unsaved})" if text else unsaved[0].upper() + unsaved[1:]
        return text

    def _update_check_status(self) -> None:
        """The status bar's check items: the newest result's counts, and the cursor line's
        first check item when it has one, else ``check_status_text``."""
        if self.closed:
            return
        result = self.check_result
        self.check_counts.configure(text=counts_text(result) if result is not None else "")
        text = self.check_status_text()
        record = self.current
        if record is not None and record.marks:
            line = _line_of(record.widget.index("insert"))
            items = self._line_items(record, line, line).get(line)
            if items:
                text = items[0].text
        if text != self._check_status_shown:
            self._check_status_shown = text
            self.check_status.configure(text=text)

    # --- Markers (04 §7.2 step 8) -----------------------------------------------------------

    def _place_marks(self, record: OpenFile) -> None:
        """Replace ``record``'s check marks: one Tk mark at ``line.0`` for each item of the
        newest result in its file. Right gravity, so lines inserted at the start of a marked
        line push the mark down with its text."""
        widget = record.widget
        for name in record.marks:
            widget.mark_unset(name)
        record.marks = {}
        result = self.check_result
        if result is None or not record.editable:
            return
        number = 0
        for item in result.problems:
            if item.file != record.ref or item.line is None:
                continue
            name = f"{MARK_PREFIX}{number}"
            number += 1
            widget.mark_set(name, f"{item.line}.0")
            widget.mark_gravity(name, "right")
            record.marks[name] = item

    def _line_items(self, record: OpenFile, first: int,
                    last: int) -> dict[int, list[CheckItem]]:
        """Line -> its check items in result order, for lines ``first``..``last`` only (the
        marks are walked from ``first.0``)."""
        if not record.marks:
            return {}
        found: dict[int, list[tuple[int, CheckItem]]] = {}
        widget = record.widget
        name = widget.mark_next(f"{first}.0")
        while name:
            line = _line_of(widget.index(name))
            if line > last:
                break
            item = record.marks.get(name)
            if item is not None:
                found.setdefault(line, []).append((int(name[len(MARK_PREFIX):]), item))
            name = widget.mark_next(name)
        return {line: [item for _n, item in sorted(pairs, key=lambda pair: pair[0])]
                for line, pairs in found.items()}

    def check_markers(self) -> dict[int, str]:
        """Line -> ``E`` or ``W`` for every marked line of the file on screen."""
        record = self.current
        if record is None or not record.marks:
            return {}
        last = _line_of(record.widget.index("end-1c"))
        markers = {}
        for line, items in self._line_items(record, 1, last).items():
            letter = _marker_severity(items)
            if letter is not None:
                markers[line] = MARKER_LETTERS[letter]
        return markers

    # --- The last good check's names and links (F45 04 §4.2; step 4 sets them) --------------

    @property
    def check_names(self) -> dict:
        """kind -> name entries (``NameEntry`` or ``(name, file, line)`` rows): what
        completion offers, and the story map's labels with their places."""
        return self._check_names

    @check_names.setter
    def check_names(self, value: dict | None) -> None:
        self._check_names = dict(value or {})
        self._index_changed()

    @property
    def check_links(self) -> tuple:
        """The label links (``LabelLink`` or ``(src, dst, kind, file, line)`` rows)."""
        return self._check_links

    @check_links.setter
    def check_links(self, value: Sequence[object] | None) -> None:
        self._check_links = tuple(value or ())
        self._index_changed()

    @property
    def check_stale(self) -> bool:
        """True while the newest check didn't load the script: the map is "out of date"."""
        return self._check_stale

    @check_stale.setter
    def check_stale(self, value: bool) -> None:
        self._check_stale = bool(value)
        self._index_changed()

    def _index_changed(self) -> None:
        self._map_dirty = True
        if not self.closed and self.notebook.index("current") == 1:
            self.root.after_idle(self.refresh_story_map)
        if not self.closed and self.notebook.index("current") == TAB_OUTLINE_INDEX:
            self.root.after_idle(self.refresh_outline)

    def refresh_outline(self) -> None:
        """The Outline tab from the name index (AC-F45-54); unchanged rows redraw nothing."""
        if not self.closed:
            self.outline_view.set_rows(outline(self._check_names))

    # --- Story map (PR-F45-18, 19; design §6.2) ---------------------------------------------

    def refresh_story_map(self) -> None:
        """Draw the map from ``check_names["label"]`` and ``check_links`` if they changed."""
        if self.closed or not self._map_dirty:
            return
        self._map_dirty = False
        labels = self._check_names.get("label", ())
        self.story_map.set_data(labels, self._check_links, self._check_stale,
                                label_notes(labels, self._check_names))

    def open_label_box(self, box: Box) -> None:
        """A click or Enter on a box: its label line in the Editor tab."""
        if box.file is not None and box.line is not None:
            self.jump_to(box.file, box.line)

    # --- The side editor (2026-11-02, user: map opens editor to the side) ------------------

    def open_label_beside(self, box: Box) -> None:
        """A click or Enter on a box: its label line in the side editor beside the map (a
        file that didn't load opens in the Editor tab)."""
        if box.file is None or box.line is None:
            return
        record = self._record(box.file)
        if not record.editable:
            self.jump_to(box.file, box.line)
            return
        self.current = record
        self._show(record.widget)           # retargets an open side editor
        if self._side_source is not record.widget:
            self._make_side_peer(record.widget)
        self._show_side_pane()
        peer = self.side_text
        assert peer is not None
        self._place_jump(peer, max(1, min(box.line, _line_of(peer.index("end-1c")))))
        if self.story_map.focused is not None:
            self.story_map.see(self.story_map.focused)    # the map just got narrower
        # Last: the row's quiet <<TreeviewSelect>> must not meet update_idletasks above.
        self._select_current_row()

    def _make_side_peer(self, source: tk.Text) -> None:
        """A Tk text peer of ``source``: the same text, tags, marks, undo and modified flag;
        its own cursor, selection and view."""
        self._drop_side_peer()
        peer = tk.Text.__new__(tk.Text)
        tk.BaseWidget._setup(peer, self.side_frame, {})
        peer.widgetName = "text"
        source.peer_create(peer._w, **self._text_options(editable=True))
        peer.tag_configure("sel", foreground=PLAIN_COLOR)
        peer.tag_raise("sel")
        peer.configure(yscrollcommand=self._on_side_yscroll, xscrollcommand=self._side_hbar_set)
        peer.bind("<Configure>", lambda _e: self._schedule_refresh(), add="+")
        # Esc closes the side editor (an open completion list takes it first).
        peer.bind("<Escape>", lambda _e: None if self.popup.is_open
                  else self._break(self.close_side))
        tags = list(peer.bindtags())
        tags.insert(1, self._editor_bindtag)
        peer.bindtags(tuple(tags))
        self._install_change_hook(peer, owner=source)
        peer.grid(row=1, column=1, sticky="nsew")
        self.side_vbar.configure(command=peer.yview)
        self.side_hbar.configure(command=peer.xview)
        self.side_text, self._side_source = peer, source
        self._update_side_name()

    def _drop_side_peer(self) -> None:
        peer = self.side_text
        if peer is None:
            return
        if self.popup.widget is peer:
            self.close_completion()
        self.side_text = self._side_source = None
        name = str(peer)
        peer.destroy()
        try:
            peer.tk.call("rename", name, "")    # the change hook's proc outlives the widget
        except tk.TclError:
            pass

    def _show_side_pane(self) -> None:
        """Add the side editor to the Story map tab: 45 % of it at first, then the width
        the author left it at."""
        if self._side_open:
            return
        split = self.map_split
        split.update_idletasks()
        total = split.winfo_width()
        width = self._side_width or int(total * SIDE_SHARE)
        split.add(self.side_frame, minsize=SIDE_MIN_WIDTH, stretch="always")
        self._side_open = True
        if total > 1:
            split.update_idletasks()
            split.sash_place(0, max(MAP_MIN_WIDTH, total - width), 0)

    def close_side(self, focus_map: bool = True) -> None:
        """✕ or Esc: hide the side editor; the focus goes back to the map."""
        if not self._side_open:
            return
        width = self.side_frame.winfo_width()
        if width > 1:
            self._side_width = width
        self.map_split.forget(self.side_frame)
        self._side_open = False
        self._drop_side_peer()
        if focus_map and not self.closed:
            self.map_canvas.focus_set()
        self._schedule_refresh()

    def side_to_editor(self) -> None:
        """Open in Editor tab (and Ctrl+1 in the side editor): the Editor tab at the side
        editor's cursor."""
        peer, record = self.side_text, self.current
        if peer is None or record is None:
            return
        line, column = (int(part) for part in peer.index("insert").split("."))
        self.notebook.select(0)
        self._place_jump(record.widget, line, column)

    def _side_active(self) -> tk.Text | None:
        """The side editor's peer while it is on screen, else None."""
        side = self.side_text
        if side is None or self.closed or self.current is None \
                or self._side_source is not self.current.widget:
            return None
        return side if self.notebook.index("current") == 1 else None

    def _side_has_focus(self) -> bool:
        try:
            return self.side_text is not None and self.root.focus_get() is self.side_text
        except (KeyError, tk.TclError):
            return False

    def _on_side_yscroll(self, first: str, last: str) -> None:
        self.side_vbar.set(first, last)
        self._schedule_refresh()

    def _update_side_name(self) -> None:
        """The side editor's header: the file's ref, ``* `` in front while unsaved."""
        record = self.current
        if self.side_text is not None and record is not None:
            text = (DIRTY_MARK if record.dirty else "") + show(record.ref)
            if self.side_name.cget("text") != text:
                self.side_name.configure(text=text)

    def label_places(self) -> dict[str, tuple[str | None, int | None]]:
        """Label name -> (file, line), from the last good check, in program order."""
        places: dict[str, tuple[str | None, int | None]] = {}
        for entry in self._check_names.get("label", ()):
            if isinstance(entry, str):
                name, where, line = entry, None, None
            elif hasattr(entry, "name"):
                name = entry.name
                where, line = getattr(entry, "file", None), getattr(entry, "line", None)
            else:
                name, where, line = tuple(entry)[:3]
            places.setdefault(name, (where, line))
        return places

    def go_to_label(self) -> None:
        """Ctrl+G: the story map's text alternative. Asks for a label name and jumps to its
        line."""
        if self.closed:
            return
        places = self.label_places()

        def hint(text: str) -> str:
            if not places:
                return NO_LABELS_YET
            name = text.strip()
            where = places.get(name)
            if where is None or where[0] is None:
                return ", ".join([n for n in places if n.startswith(name)][:6])
            return f"{show(where[0])}, line {where[1]}"

        answer = ask_text(self.root, GO_TO_LABEL_ASK, "", ok=GO_TO_LABEL_OK, hint=hint,
                          select_stem=False)
        if answer is None:
            return
        name = answer[0].strip()
        where = places.get(name)
        if where is None or where[0] is None or where[1] is None:
            show_error(self.root, NO_SUCH_LABEL.format(name=name))
            return
        self.jump_to(where[0], where[1])

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
        self.notebook.select(0)
        widget = self.current.widget
        line = _line_of(widget.index("insert"))
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
        self.popup.open(widget, _line_of(widget.index("insert")), ctx, rows,
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
        if widget is not self.text or _line_of(widget.index("insert")) != popup.line:
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
            self.vbar.set(first, last)
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
        key = (str(widget), _line_of(widget.index("insert"))) if editable else None
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
        line = _line_of(widget.index("insert"))
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
        first = _line_of(widget.index("@0,0"))
        height = widget.winfo_height()
        last = _line_of(widget.index(f"@0,{height}"))
        rows = height // max(1, self.font.metrics("linespace")) + 1
        last = max(last, first + max(rows, _MIN_COLORED_LINES))
        return first, min(last, _line_of(widget.index("end-1c")))

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
        total = _line_of(widget.index("end-1c"))
        width = self._gutter_width(total)
        if int(gutter.cget("width")) != width:
            gutter.configure(width=width)
        if self.current is None or not self.current.editable:
            return
        zero = self.font.measure("0")
        right = width - zero
        marked = self._line_items(self.current, first, last)
        cursor_line = _line_of(widget.index("insert"))
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

    # --- Start label (PR-F44-09, UI-F44-05) -------------------------------------------------

    def start_label_name(self) -> str | None:
        """The label Preview would start at, or None for the beginning."""
        if self.current is None or not self.current.editable:
            return None
        widget = self.text
        found = widget.search(r"^label[ \t]", "insert lineend", backwards=True, regexp=True,
                              stopindex="1.0")
        if not found:
            return None
        match = LABEL_LINE.match(widget.get(f"{found} linestart", f"{found} lineend"))
        return match.group(1) if match is not None else None

    def _update_start_label(self, widget: tk.Text) -> None:
        line = _line_of(widget.index("insert"))
        if self._jump_line is not None and line != self._jump_line:
            widget.tag_remove(TAG_JUMP, "1.0", "end")
            self._jump_line = None
        if line == self._label_line:
            return
        self._label_line = line
        name = self.start_label_name()
        self.start_label.configure(text=name if name is not None else BEGINNING)

    # --- Keys (03 §4, §7.6 "Keys") ----------------------------------------------------------

    _editor_bindtag = "VnEditorText"

    def _bind_keys(self) -> None:
        root, mod = self.root, self.mod
        tag = self._editor_bindtag

        def on_tag(sequence: str, handler: Callable[[tk.Event], str | None]) -> None:
            root.bind_class(tag, sequence, handler)

        for key in ("<Tab>",):
            on_tag(key, lambda e: self._completion_key("accept")
                   or self._indent(e.widget, dedent=False))
        for key in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            try:
                on_tag(key, lambda e: self._indent(e.widget, dedent=True))
            except tk.TclError:
                pass                        # a keysym this Tk doesn't know
        for key in ("<Return>", "<KP_Enter>"):
            on_tag(key, lambda e: self._completion_key("accept") or self._newline(e.widget))
        # The completion list (UI-F45-04): the editor keeps the focus, so its keys go here
        # and fall through to the Text bindings while no list is open.
        for key, action in (("<Up>", "up"), ("<Down>", "down"), ("<Prior>", "prior"),
                            ("<Next>", "next")):
            on_tag(key, lambda _e, a=action: self._completion_key(a))
        on_tag(f"<{mod}-space>", lambda _e: self._break(self.complete))
        on_tag("<KeyPress>", self._after_key)
        on_tag("<FocusOut>", self._on_editor_focus_out)
        for letter in "zZ":
            on_tag(f"<{mod}-{letter}>", lambda e: self._undo_or_redo(e))
        for key in (f"<{mod}-y>", f"<{mod}-Y>"):
            on_tag(key, lambda e: self._redo(e.widget))
        for key in (f"<{mod}-a>", f"<{mod}-A>"):
            on_tag(key, lambda e: self._select_all(e.widget))
        for letter, event in (("x", "<<Cut>>"), ("c", "<<Copy>>"), ("v", "<<Paste>>")):
            for key in (f"<{mod}-{letter}>", f"<{mod}-{letter.upper()}>"):
                on_tag(key, lambda e, ev=event: self._clipboard(e.widget, ev))

        def on_all(sequence: str, handler: Callable[[tk.Event], str | None]) -> None:
            root.bind_all(sequence, lambda e: handler(e) if self._in_main(e) else None)

        for key in (f"<{mod}-s>", f"<{mod}-S>"):
            on_all(key, lambda _e: self._break(self.save_current))
        on_all(f"<{mod}-Shift-S>", lambda _e: self._break(self.save_all))
        for key in (f"<{mod}-n>", f"<{mod}-N>"):
            on_all(key, lambda _e: self._break(self.new_script_file))
        on_all(f"<{mod}-Shift-O>", lambda _e: self._break(self.add_files))
        for key in (f"<{mod}-g>", f"<{mod}-G>"):
            on_all(key, lambda _e: self._break(self.go_to_label))
        on_all("<F7>", lambda _e: self._break(self.check_now))
        for index in range(4):
            on_all(f"<{mod}-Key-{index + 1}>", lambda _e, i=index: self._break(self.show_tab, i))
        for key in (f"<{mod}-equal>", f"<{mod}-plus>", f"<{mod}-KP_Add>"):
            on_all(key, lambda _e: self._break(self.zoom_view, FONT_STEP_PX))
        for key in (f"<{mod}-minus>", f"<{mod}-KP_Subtract>"):
            on_all(key, lambda _e: self._break(self.zoom_view, -FONT_STEP_PX))
        for key in (f"<{mod}-0>", f"<{mod}-KP_0>"):
            on_all(key, lambda _e: self._break(self.zoom_view, 0))
        on_all("<F5>", lambda _e: self._break(self.preview))
        on_all("<Shift-F5>", lambda _e: self._break(self.preview, False))
        on_all("<F6>", lambda _e: self._break(self.cycle_focus, 1))
        on_all("<Shift-F6>", lambda _e: self._break(self.cycle_focus, -1))

        # Tab order outside the editor (03 §4): project → editor → start values → Preview →
        # problems → project. Tab in the editor indents instead.
        order: list[Callable[[], tk.Widget]] = [
            lambda: self.tree, lambda: self.text, lambda: self.start_values,
            lambda: self.preview_button, lambda: self.problems]
        for index, get in enumerate(order):
            if index == 1:
                continue
            widget = get()
            forward, back = order[(index + 1) % len(order)], order[index - 1]
            widget.bind("<Tab>", lambda _e, f=forward: self._move_focus(f()))
            for key in ("<Shift-Tab>", "<ISO_Left_Tab>"):
                try:
                    widget.bind(key, lambda _e, b=back: self._move_focus(b()))
                except tk.TclError:
                    pass
        # The Help pane is reached by F6; Tab from it goes on to the project panel.
        self.help_text.bind("<Tab>", lambda _e: self._move_focus(self.tree))
        for key in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            try:
                self.help_text.bind(key, lambda _e: self._move_focus(self.problems))
            except tk.TclError:
                pass

    def _in_main(self, event: tk.Event) -> bool:
        """Global keys act only in the editor's own window, not in a dialog."""
        widget = event.widget
        try:
            return not self.closed and isinstance(widget, tk.Misc) and \
                widget.winfo_toplevel() is self.root
        except (KeyError, tk.TclError):
            return False

    @staticmethod
    def _break(action: Callable[..., object], *args: object) -> str:
        action(*args)
        return "break"

    @staticmethod
    def _move_focus(widget: tk.Widget) -> str:
        widget.focus_set()
        return "break"

    def cycle_focus(self, step: int) -> None:
        """F6 / Shift+F6: Project → Editor area → Start values → Problems → Help →
        Project (UI-F45-02, amended AC-F44-32; the editor area is the current tab's
        widget, then the Story map's side editor while it is open)."""
        areas: list[tk.Widget] = [self.tree, self._tab_widget()]
        side = self._side_active()
        if side is not None:
            areas.append(side)
        areas += [self.start_values, self.problems, self.help_text]
        try:
            focus = self.root.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus is self.preview_button:
            target = self.problems if step > 0 else self.start_values
        else:
            if focus in self._editor_widgets() or focus in (self.map_canvas,
                                                             self.asset_pane.frame):
                position = 1
            elif focus in areas:
                position = areas.index(focus)
            else:
                position = 0 if step > 0 else 2     # unknown focus: land in the editor
            target = areas[(position + step) % len(areas)]
        target.focus_set()

    def _tab_widget(self) -> tk.Widget:
        """The widget F6 lands on in the notebook: the current tab's."""
        index = self.notebook.index("current")
        if index == 1:
            return self.map_canvas
        if index == 2:
            return self.asset_pane.frame
        if index == TAB_OUTLINE_INDEX:
            return self.outline_view.tree
        return self.text

    def _undo_or_redo(self, event: tk.Event) -> str:
        """Ctrl+Z is undo, also with Caps Lock (keysym ``Z``); with Shift it is redo."""
        if int(event.state) & 0x1:
            return self._redo(event.widget)
        return self._undo(event.widget)

    def _undo(self, widget: tk.Text) -> str:
        try:
            widget.edit_undo()
        except tk.TclError:
            pass                            # nothing to undo
        return "break"

    def _redo(self, widget: tk.Text) -> str:
        try:
            widget.edit_redo()
        except tk.TclError:
            pass
        return "break"

    @staticmethod
    def _select_all(widget: tk.Text) -> str:
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", "1.0", "end-1c")
        return "break"

    @staticmethod
    def _clipboard(widget: tk.Text, virtual: str) -> str:
        widget.event_generate(virtual)
        return "break"

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
                first = _line_of(widget.index("sel.first"))
                end = widget.index("sel.last")
                last = _line_of(end)
                if last > first and end.endswith(".0"):
                    last -= 1
            else:
                first = last = _line_of(widget.index("insert"))
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
        self.font.configure(size=-size)
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
        return True

    def save_current(self) -> bool:
        """Ctrl+S: save the file on screen. Arms the window and asks for a check."""
        self.armed = True
        saved = self.current is None or self.save_record(self.current)
        if saved:
            self.request_check()
        return saved

    def save_all(self) -> bool:
        """Ctrl+Shift+S: save every unsaved file, stopping at the first failure. Arms the
        window and asks for a check."""
        self.armed = True
        for record in self.dirty_files():
            if not self.save_record(record):
                return False
        self.request_check()
        return True

    def on_close(self) -> None:
        """The close box, Alt+F4, and Cmd+Q: ask about unsaved files, then close."""
        if self.closed:
            return
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
        self.runner.stop()
        self.check_runner.stop()
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
        line = _line_of(record.widget.index("insert"))
        result = self._open_any(record.ref)
        if isinstance(result, ScriptDocument) and record.doc is not None:
            self._set_text(record, result.text)
            result.text = ""
            record.doc = result
            widget = record.widget
            widget.mark_set("insert", f"{min(line, _line_of(widget.index('end-1c')))}.0")
            widget.see("insert")
            self._place_marks(record)
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

    @staticmethod
    def _stat(path: os.PathLike | str) -> tuple[int, int] | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    # --- Preview (PR-F44-09-14, §7.6 "Preview (F5)") ---------------------------------------

    def preview(self, from_cursor: bool = True) -> None:
        """F5, the Preview button (``from_cursor``: start at the label above the cursor),
        and Shift+F5 (start at ``start``). Saves every unsaved file first: the first failure
        shows its dialog and nothing starts. Start-value problems go to the panel, and
        nothing starts (I-5). Focus stays where it was (03 §4)."""
        if self.closed:
            return
        was_armed, dirty = self.armed, self.dirty_files()
        self.armed = True
        for record in dirty:
            if not self.save_record(record):
                return
        if dirty or not was_armed:          # after saves, and the first full check (07 I-1)
            self.request_check()
        args, problems = start_value_args(self.start_values.get("1.0", "end-1c"))
        if problems:
            self.show_event(PreviewEvent(PreviewState.DIDNT_START,
                                         start_values_report(problems)))
            return
        label = self.start_label_name() if from_cursor else None
        self.runner.start(preview_argv(self.paths.root, label, args))
        self.apply_events(self.runner.poll())

    def _poll_preview(self) -> None:
        self._poll_id = None
        if self.closed:
            return
        try:
            self.apply_events(self.runner.poll())
            self.apply_check_events(self.check_runner.poll())
        finally:
            if not self.closed:
                self._poll_id = self.root.after(POLL_INTERVAL_MS, self._poll_preview)

    def apply_events(self, events: Sequence[PreviewEvent]) -> None:
        for event in events:
            self.show_event(event)

    def show_event(self, event: PreviewEvent) -> None:
        """The status bar's preview item and the panel for a preview state (03 §2.2, F45 01
        §6.5): Running clears the
        panel, Didn't start and Stopped with an error show the report, and the others leave
        it as it is."""
        self.preview_state = event.state
        self.status_label.configure(text=status_text(event))
        if event.state is PreviewState.RUNNING:
            self.show_hint(NO_PROBLEMS)
        elif event.report is not None and event.state in (PreviewState.DIDNT_START,
                                                          PreviewState.STOPPED_ERROR):
            self.show_report(event.report)

    # --- Problems panel (03 §3, §7.6 "Problems panel") -------------------------------------

    def _clear_panel(self) -> tk.Text:
        panel = self.problems
        panel.configure(state="normal")
        panel.delete("1.0", "end")
        for tag in panel.tag_names():
            if tag.startswith(PARAGRAPH_PREFIX):
                panel.tag_delete(tag)
        panel.configure(cursor="arrow")
        self.paragraphs = []
        self._chosen = None
        return panel

    def show_hint(self, text: str) -> None:
        """A gray line instead of preview problems (below the check rows)."""
        self._panel_view = ("hint", text)
        self.render_panel()

    def show_report(self, report: Report) -> None:
        """The report's paragraphs, in the error screen's order and wording, below the check
        rows (PR-F45-08)."""
        self._panel_view = ("report", report)
        self.render_panel()

    def _check_entries(self) -> list[tuple[str, object, bool, int]]:
        """The check part of the panel: (text, item, clickable, link length)."""
        result = self.check_result
        if result is None:
            return []
        entries: list[tuple[str, object, bool, int]] = [(check_summary(result), None, False, 0)]
        everything = self.show_warnings.get()
        for item in result.problems:
            if everything or item.severity == "error":
                clickable = item.line is not None and self._openable(item.file)
                entries.append((check_row(item), item, clickable,
                                len(check_row_head(item)) if clickable else 0))
        return entries

    def render_panel(self) -> None:
        """The problems panel: the newest check's summary and rows (warning and info rows
        hidden by the View toggle), then the newest preview or start-value report in F44's
        text, or its gray hint. A paragraph with a line in a file the editor shows is a
        link: its location is underlined in ``#0A4FBF``, the pointer is a hand over it, and
        a click or Enter jumps."""
        if self.closed:
            return
        panel = self._clear_panel()
        entries = self._check_entries()
        kind, value = self._panel_view
        hint: str | None = None
        if kind == "report":
            assert isinstance(value, Report)
            if value.head is not None:
                entries.append((value.head, None, False, 0))
            for item in value.items:
                clickable = (item.line is not None
                             and item.file in self.refs)    # the Script group (amended A-28)
                colon = item.text.find(":") if clickable else -1
                entries.append((item.text, item, clickable, max(colon, 0)))
            entries += [(line, None, False, 0) for line in value.tail]
        else:
            hint = str(value)
        for index, (text, item, clickable, link) in enumerate(entries):
            tag = f"{PARAGRAPH_PREFIX}{index}"
            start = panel.index("end-1c")
            panel.insert("end", text + ("\n" if index < len(entries) - 1 else ""))
            panel.tag_add(tag, start, "end-1c")
            if index:
                panel.tag_add(TAG_GAP, start, f"{start} lineend")
            if clickable:
                if link > 0:
                    panel.tag_add(TAG_LINK, start, f"{start}+{self._tk_length(text[:link])}c")
                panel.tag_add(TAG_CLICK, start, "end-1c")
            self.paragraphs.append(Paragraph(tag, item, clickable))   # type: ignore[arg-type]
        if hint is not None:
            if entries:
                start = panel.index("end-1c")
                panel.insert("end", "\n" + hint, TAG_HINT)
                panel.tag_add(TAG_GAP, f"{start}+1c", "end-1c")
            else:
                panel.insert("1.0", hint, TAG_HINT)
        panel.tag_raise("sel")
        panel.configure(state="disabled")
        panel.yview_moveto(0)

    def panel_paragraphs(self) -> list[str]:
        """The panel's paragraphs as shown (for tests and the docs)."""
        panel = self.problems
        texts = []
        for paragraph in self.paragraphs:
            ranges = panel.tag_ranges(paragraph.tag)
            texts.append(panel.get(ranges[0], ranges[1]).removesuffix("\n") if ranges else "")
        return texts

    def _paragraph_at(self, index: str) -> int | None:
        panel = self.problems
        for where in (index, f"{index} -1c"):
            for tag in panel.tag_names(where):
                if tag.startswith(PARAGRAPH_PREFIX) and tag[len(PARAGRAPH_PREFIX):].isdigit():
                    return int(tag[len(PARAGRAPH_PREFIX):])
        return None

    def _on_panel_click(self, event: tk.Event) -> None:
        if self.problems.tag_ranges("sel"):
            return                              # a drag that selected text, not a click
        index = self._paragraph_at(self.problems.index(f"@{event.x},{event.y}"))
        if index is not None:
            self._choose(index)
            self.activate_paragraph(index)

    def _on_panel_focus_in(self, _event: tk.Event) -> None:
        """The first clickable error is selected when the panel gets focus (03 §3)."""
        if not self.paragraphs:
            return
        if self._chosen is None:
            clickable = [i for i, p in enumerate(self.paragraphs) if p.clickable]
            self._chosen = clickable[0] if clickable else 0
        self._choose(self._chosen)

    def choose_paragraph(self, step: int) -> None:
        """Up and Down move the selected paragraph."""
        if not self.paragraphs:
            return
        current = self._chosen if self._chosen is not None else -step
        self._choose(min(len(self.paragraphs) - 1, max(0, current + step)))

    def _choose(self, index: int) -> None:
        panel = self.problems
        self._chosen = index
        panel.tag_remove(TAG_CHOSEN, "1.0", "end")
        ranges = panel.tag_ranges(self.paragraphs[index].tag)
        if ranges:
            panel.tag_add(TAG_CHOSEN, ranges[0], ranges[1])
            panel.see(ranges[0])

    def activate_chosen(self) -> None:
        """Enter in the panel: jump to the selected error if it is clickable."""
        if self._chosen is not None:
            self.activate_paragraph(self._chosen)

    def activate_paragraph(self, index: int) -> None:
        """Jump to paragraph ``index``'s error. Nothing happens for one that can't be
        clicked."""
        paragraph = self.paragraphs[index]
        item = paragraph.item
        if paragraph.clickable and item is not None and item.file is not None and \
                item.line is not None:
            self.jump_to(item.file, item.line, item.column)

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
        line = max(1, min(line, _line_of(widget.index("end-1c"))))
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


# --- Helpers --------------------------------------------------------------------------------

def _marker_severity(items: Sequence[CheckItem]) -> str | None:
    """``error`` if any item on the line is an error, else ``warning`` for a warning, else
    None (info has no marker)."""
    severities = {item.severity for item in items}
    if "error" in severities:
        return "error"
    return "warning" if "warning" in severities else None


_autohide = autohide


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
