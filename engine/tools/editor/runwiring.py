"""Studio's Play bar wiring (F47 ``01`` PR-F47-07..09, ``04`` §7.4; F44 ``03`` §2.2, ``04``
§7.6 "Preview (F5)"), as the ``RunWiring`` mixin of ``window.EditorWindow``.

``playbar.PlayBar`` sits under the menu bar. Play (Shift+F5, the primary button) plays from
the game's ``start``; Play this scene (F5) plays from the selected story-map box while the
Story map shows, else from the label above the editor's cursor; Play from this scene (a
box's or an Events row's context menu) plays from that scene; Stop (Ctrl+F2) ends the game
child. Every Play saves every unsaved file, checks the start values (kept for the session in
Play options, with "Play as a new player"), and hands argv to ``preview.PreviewRunner``. The
first Play that reaches the game window marks ``played`` in ``studiostate`` (the Guide's
step 7). One poll loop (every ``POLL_INTERVAL_MS``) polls the game runner, the check runner,
then every runner joined with ``join_runner`` (``win.runners``: F47's ``HelperRunner``,
F42's ``BuildRunner``, F39's hot reload), each in its own handler.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Any

from engine.tools.editor import studiostate
from engine.tools.editor.playbar import (  # noqa: F401  (re-exported: tests read them here)
    BEGINNING,
    START_VALUES_HEADING,
    PlayBar,
    ask_play_options,
)
from engine.tools.editor.preview import (
    POLL_INTERVAL_MS,
    PreviewEvent,
    PreviewState,
    preview_argv,
    start_value_args,
    start_values_report,
)
from engine.tools.editor.syntax import LABEL_LINE
from engine.tools.editor.checkwiring import NO_PROBLEMS
from engine.tools.editor.studiolook import TAG_JUMP, line_of, plural

STATUS_NOT_RUNNING = "Not running."
STATUS_TEXTS = {                        # 03 §2.2; DIDNT_START is didnt_start_text(n)
    PreviewState.NOT_RUNNING: STATUS_NOT_RUNNING,
    PreviewState.STARTING: "Starting…",
    PreviewState.RUNNING: "Running. F5 restarts it.",
    PreviewState.CLOSED: "Closed.",
    PreviewState.STOPPED_ERROR: "Stopped with an error, listed in Problems.",
    PreviewState.STOPPED_UNEXPECTED: "Stopped unexpectedly.",
}
LIVE = (PreviewState.STARTING, PreviewState.RUNNING)


def didnt_start_text(count: int) -> str:
    """``Didn't start: 1 problem, listed in Problems.`` (03 §2.2, I-14)."""
    return f"Didn't start: {plural(count, 'problem')}, listed in Problems."


def status_text(event: PreviewEvent) -> str:
    """The status line for a preview state (UI-F44-06)."""
    if event.state is PreviewState.DIDNT_START:
        return didnt_start_text(event.report.problem_count if event.report else 1)
    return STATUS_TEXTS[event.state]


class RunWiring:
    """The Play bar, playing and stopping the game, and the one poll loop."""

    start_values_text = ""              # Play options' start values (session only)
    play_fresh = False                  # Play options' "Play as a new player"
    guide_shown = False
    _scene_tab = ""

    def _build_play_bar(self) -> None:
        """The Play bar under the menu bar, across the window (PR-F47-07). Packed before
        the panes; ``studiomenus`` packs the in-window menu bar above it."""
        self.play_bar = PlayBar(self.root, scale=self.scale, font=self.ui_font,
                                tip_font=self.fonts["small"], on_play=self.play_from_start,
                                on_scene=self.play_scene, on_stop=self.stop_game,
                                on_options=self.play_options, on_guide=self.toggle_guide)
        self.play_bar.frame.pack(side="top", fill="x")
        self.play_bar.divider.pack(side="top", fill="x")
        self.play_button = self.play_bar.play_button
        self.stop_button = self.play_bar.stop_button
        self.start_label = self.play_bar.scene_label
        self._played_marked = False
        self._state_writable = True
        state = studiostate.read_state(self.paths.root)
        if isinstance(state, studiostate.StudioState):
            self.guide_shown = state.guide_open
            self._played_marked = state.played
        elif state.link:                    # a link: never write there (studiostate)
            self._state_writable = False
        self.play_bar.set_guide(self.guide_shown)

    def save_studio_state(self, **changes: bool) -> None:
        """Change ``.studio/studio.json``; after a link is found, nothing more is written
        for this window."""
        if not self._state_writable:
            return
        problem = studiostate.with_change(self.paths.root, **changes)
        if problem is not None and problem.link:
            self._state_writable = False

    # --- Start label (PR-F44-09, UI-F44-05) -------------------------------------------------

    def start_label_name(self) -> str | None:
        """The label above the editor's cursor (Play this scene's fallback), or None for the beginning."""
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
        self._update_scene_name()

    def scene_to_play(self) -> str | None:
        """Play this scene's label (§7.4): the selected box while the Story map shows,
        else the label above the editor's cursor; None plays from the start."""
        if self.current_tab() == "map":
            name = self.story_map.focused_name()
            if name is not None:
                return name
        return self.start_label_name()

    def _update_scene_name(self) -> None:
        """The muted name after Play this scene: what F5 would play now."""
        self.play_bar.set_scene(self.scene_to_play())

    # --- Play (PR-F47-07..09, §7.4; F44 PR-F44-09-14) --------------------------------------

    def play_from_start(self) -> None:
        """▶ Play and Shift+F5: from the game's ``start``."""
        self.play(None)

    def play_scene(self) -> None:
        """▶ Play this scene and F5."""
        self.play(self.scene_to_play())

    def play(self, label: str | None) -> None:
        """Play from ``label`` (None: the start). Saves every unsaved file first: the first
        failure shows its dialog and nothing starts. Start-value problems go to the panel,
        and nothing starts (I-5). Focus stays where it was (03 §4)."""
        if self.closed:
            return
        was_armed, dirty = self.armed, self.dirty_files()
        self.armed = True
        for record in dirty:
            if not self.save_record(record):
                return
        if dirty or not was_armed:          # after saves, and the first full check (07 I-1)
            self.request_check()
        args, problems = start_value_args(self.start_values_text)
        if problems:
            self.show_event(PreviewEvent(PreviewState.DIDNT_START,
                                         start_values_report(problems)))
            return
        self.runner.start(preview_argv(self.paths.root, label, args, fresh=self.play_fresh))
        self.apply_events(self.runner.poll())

    def stop_game(self) -> None:
        """■ Stop and Ctrl+F2: end the game child (only while it runs)."""
        if self.closed or self.preview_state not in LIVE:
            return
        self.runner.stop()
        self.show_event(PreviewEvent(PreviewState.CLOSED))

    def play_options(self) -> None:
        """Play options…: the start values and "Play as a new player", for this session."""
        answer = ask_play_options(self.root, self.start_values_text, self.play_fresh,
                                  font=self.start_values_font)
        if answer is not None:
            self.start_values_text, self.play_fresh = answer

    def toggle_guide(self) -> None:
        """? Guide: show or hide the Guide (remembered per game in ``studiostate``). The
        pane itself (W6) listens through ``show_guide`` when the window has one."""
        self.guide_shown = not self.guide_shown
        self.play_bar.set_guide(self.guide_shown)
        self.save_studio_state(guide_open=self.guide_shown)
        show = getattr(self, "show_guide", None)
        if callable(show):
            show(self.guide_shown)

    def _poll_preview(self) -> None:
        """The one poll loop: the preview runner, the check runner, then each joined
        runner, every ``POLL_INTERVAL_MS`` until the window closes."""
        self._poll_id = None
        if self.closed:
            return
        try:
            self.apply_events(self.runner.poll())
            tab = self.current_tab()
            if tab == "map" or tab != self._scene_tab:      # a box chosen, or the tab left
                self._scene_tab = tab
                self._update_scene_name()
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
        self.play_bar.set_running(event.state in LIVE)
        if event.state is PreviewState.RUNNING:
            self.show_hint(NO_PROBLEMS)
            if not self._played_marked:     # Guide step 7: a Play reached the game window
                self._played_marked = True
                self.save_studio_state(played=True)
                played = getattr(self, "guide_played", None)
                if callable(played):
                    played()
        elif event.report is not None and event.state in (PreviewState.DIDNT_START,
                                                          PreviewState.STOPPED_ERROR):
            self.show_report(event.report)
