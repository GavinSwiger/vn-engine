"""Studio's preview: start values, the Preview button, start, poll and status (F44 ``03``
§2.2, ``04`` §7.6 "Preview (F5)"), as the ``RunWiring`` mixin of ``window.EditorWindow``.

Preview (F5, Shift+F5, the button) saves every unsaved file, checks the start values, and
hands argv to ``preview.PreviewRunner``. One poll loop (every ``POLL_INTERVAL_MS``) polls the
preview runner, the check runner, then every runner joined with ``join_runner`` (``win.runners``:
F47's ``HelperRunner``, F42's ``BuildRunner``, F39's hot reload), each in its own handler.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from engine.tools.editor.preview import (
    POLL_INTERVAL_MS,
    PreviewEvent,
    PreviewState,
    preview_argv,
    start_value_args,
    start_values_report,
)
from engine.tools.editor.syntax import LABEL_LINE, PLAIN_COLOR
from engine.tools.editor.views import autohide, panel_header
from engine.tools.editor.checkwiring import NO_PROBLEMS
from engine.tools.editor.studiolook import (
    COLUMN_PAD,
    CURSOR_COLOR,
    CURSOR_WIDTH,
    FOCUS_BORDER,
    INACTIVE_SELECTION,
    INPUT_BACKGROUND,
    INPUT_BORDER,
    LEFT_WIDTH,
    PANEL_INSET,
    SELECTION_BACKGROUND,
    START_VALUES_ROWS,
    TAG_JUMP,
    TEXT_PAD,
    line_of,
    plural,
)

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


def didnt_start_text(count: int) -> str:
    """``Didn't start: 1 problem, listed in Problems.`` (03 §2.2, I-14)."""
    return f"Didn't start: {plural(count, 'problem')}, listed in Problems."


def status_text(event: PreviewEvent) -> str:
    """The status line for a preview state (UI-F44-06)."""
    if event.state is PreviewState.DIDNT_START:
        return didnt_start_text(event.report.problem_count if event.report else 1)
    return STATUS_TEXTS[event.state]


class RunWiring:
    """The left column's preview part, starting a preview, and the one poll loop."""

    def _build_run_column(self, left: ttk.Frame, row: int) -> None:
        """The left column from grid ``row`` down (08 §7): START VALUES, the Preview button
        and where it starts."""
        px = self._px
        inset = px(PANEL_INSET)
        panel_header(left, START_VALUES_HEADING, self.scale).grid(
            row=row, column=0, sticky="ew", pady=(px(COLUMN_PAD), 0))
        self.start_values_hint = ttk.Label(left, text=START_VALUES_HINT,
                                           style="Side.Hint.TLabel",
                                           wraplength=px(LEFT_WIDTH) - 2 * inset)
        self.start_values_hint.grid(row=row + 1, column=0, sticky="w", padx=inset)
        box = ttk.Frame(left, style="Side.TFrame")
        box.grid(row=row + 2, column=0, sticky="ew", padx=inset, pady=(px(4), 0))
        box.columnconfigure(0, weight=1)
        # An input: the input fill in a 1 px border that turns the focus color (08 §7).
        self.start_values = tk.Text(
            box, height=START_VALUES_ROWS, width=1, wrap="none", undo=True, maxundo=-1,
            font=self.start_values_font, background=INPUT_BACKGROUND, foreground=PLAIN_COLOR,
            insertbackground=CURSOR_COLOR, insertwidth=px(CURSOR_WIDTH),
            selectbackground=SELECTION_BACKGROUND, inactiveselectbackground=INACTIVE_SELECTION,
            padx=px(8), pady=px(TEXT_PAD), highlightthickness=1,
            highlightbackground=INPUT_BORDER, highlightcolor=FOCUS_BORDER, borderwidth=0,
            relief="flat")
        self.start_values.tag_configure("sel", foreground=PLAIN_COLOR)
        self.start_values.grid(row=0, column=0, sticky="ew")
        values_bar = ttk.Scrollbar(box, orient="vertical", command=self.start_values.yview,
                                   style="Side.Vertical.TScrollbar")
        self.start_values.configure(yscrollcommand=autohide(values_bar, row=0, column=1,
                                                            sticky="ns"))

        self.preview_button = ttk.Button(left, text=PREVIEW_BUTTON, command=self.preview,
                                         style="Large.TButton")
        for key in ("<Return>", "<KP_Enter>"):          # Space works by itself
            self.preview_button.bind(key, lambda _e: self._break(self.preview))
        self.preview_button.grid(row=row + 3, column=0, sticky="ew", padx=inset,
                                 pady=(inset, 0))
        wrap = px(LEFT_WIDTH) - 2 * inset
        ttk.Label(left, text=STARTS_AT, style="Side.Hint.TLabel").grid(
            row=row + 4, column=0, sticky="w", padx=inset, pady=(px(COLUMN_PAD), 0))
        self.start_label = ttk.Label(left, text=BEGINNING, wraplength=wrap, justify="left",
                                     style="Side.TLabel")
        self.start_label.grid(row=row + 5, column=0, sticky="w", padx=inset, pady=(0, inset))
        self._wrapped_labels = (self.start_values_hint, self.start_label)

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
        line = line_of(widget.index("insert"))
        if self._jump_line is not None and line != self._jump_line:
            widget.tag_remove(TAG_JUMP, "1.0", "end")
            self._jump_line = None
        if line == self._label_line:
            return
        self._label_line = line
        name = self.start_label_name()
        self.start_label.configure(text=name if name is not None else BEGINNING)

    # --- Preview (PR-F44-09-14, §7.6 "Preview (F5)") ---------------------------------------

    def preview(self, from_cursor: bool = True, *, at: str | None = None) -> None:
        """F5, the Preview button (``from_cursor``: start at the label above the cursor),
        Shift+F5 (start at ``start``) and Preview from this scene (``at``: that label). Saves every unsaved file first: the first failure
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
        label = at if at is not None else self.start_label_name() if from_cursor else None
        self.runner.start(preview_argv(self.paths.root, label, args))
        self.apply_events(self.runner.poll())

    def _poll_preview(self) -> None:
        """The one poll loop: the preview runner, the check runner, then each joined
        runner, every ``POLL_INTERVAL_MS`` until the window closes."""
        self._poll_id = None
        if self.closed:
            return
        try:
            self.apply_events(self.runner.poll())
            self.apply_check_events(self.check_runner.poll())
            for runner, on_events in list(self.runners):
                if self.closed:
                    break
                on_events(runner.poll())
        finally:
            if not self.closed:
                self._poll_id = self.root.after(POLL_INTERVAL_MS, self._poll_preview)

    def join_runner(self, runner: Any, on_events: Callable[[list], object]) -> None:
        """Poll ``runner`` (anything with ``poll() -> list`` and ``stop()``: F47's
        ``HelperRunner``, F42's ``BuildRunner``) in the poll loop, handing each tick's
        events to ``on_events``; it is stopped when the window closes."""
        self.runners.append((runner, on_events))

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
