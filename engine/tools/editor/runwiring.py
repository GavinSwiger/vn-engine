"""Studio's Play bar wiring (F47 ``01`` PR-F47-07..09, ``04`` §7.4; F44 ``03`` §2.2, ``04``
§7.6 "Preview (F5)"), as the ``RunWiring`` mixin of ``window.EditorWindow``.

``playbar.PlayBar`` sits under the menu bar (on Windows and Linux, in its row). Its split
button (▶ Play "from <scene>", ■ Stop "playing <scene>" and ⟳ Update while the game runs,
and a ▾ menu) and the Run menu start, update and stop the game. A click on ▶ Play and Play
this scene (F5) play from the selected story-map box while the Story map shows, else from
the label above the editor's cursor; Play from the start (Shift+F5, in the ▾) plays from
the game's ``start``; Play from this scene (a box's or an Events row's context menu) plays
from that scene; Stop (Ctrl+F2) ends the game child; ⟳ Update is Ctrl+R (below). While the
game runs, the name beside ■ Stop follows the scene it is in (its ``at`` line reports).
Every game Play starts opens beside Studio when there is room. **Docked** (the status bar's
pin, or **Dock the game beside Studio** in the Run menu and the ▾; one setting, remembered
per person) makes room when Studio fills the screen, opens the game without a title bar,
and moves it along when Studio moves or is resized (``gamebeside``: ``--window-at``,
``--window-size``, ``--window-borderless`` and the ``window`` message; Studio goes back as
it was when the game ends). **Floating** is the free window. Every Play saves every unsaved
file, checks the start values (kept for the session in
Play options, with "Play as a new player"), and hands argv to ``preview.PreviewRunner``. The
first Play that reaches the game window marks ``played`` in ``studiostate`` (the Guide's
step 7). One poll loop (every ``POLL_INTERVAL_MS``) polls the game runner, the check runner,
then every runner joined with ``join_runner`` (``win.runners``: F47's ``HelperRunner``,
F42's ``BuildRunner``, F39's hot reload), each in its own handler.

F39 (``specs/F39-hot-reload/SPEC.md`` §4.2, W2): ``win.hot`` (``hotreload.HotReload``)
updates the running game when a ``.vns`` file or ``config.toml`` is saved (Run ▸ "Update the
game on save", on by default) or on Ctrl+R (Run ▸ "Update the running game"), after a check
of the saved files; its texts (S1-S4) replace F44's in the status bar while an update is
under way, and the Problems summary gets its suffix while an update is held. Play and Stop
forget any update, so a restart is never reported as "Updated".

F40 (developer console, ``01`` §4.3, §6.4; ``04`` §7.5, W2): **Run ▸ Open console in the
game** (F12) sends ``open`` to the running game, or plays from the start and sends it once
the game runs; **Run ▸ Jump the game to this scene** and the map box's **Jump the game
here** send ``jump`` (dimmed, with "no game running" beside them, while no game runs);
Database's **In the game now** asks for ``values`` and **Change…** sends ``set``. Answers
come through ``consoleclient.ConsoleTracker`` (one outstanding request per kind, 2 s) and
show in the status bar's preview item for 5 s as ``Console: {text}``, escaped and cut to
200 characters; Studio never acts on an answer's text.

Line reports (what the running game is doing; ``core/editorreport.py``): subscribe with
``win.on_game_event(callback)``, which returns a function that unsubscribes. Each poll tick
(every ``POLL_INTERVAL_MS``) calls ``callback(kind, data)`` for every report the game sent
since the last tick, oldest first, on the Tk main thread:

- ``kind == "ending"``, ``data == {"id": "true_end", "title": "Together"}`` each time the
  game runs an ``ending`` line (the ending's name and its title as shown);
- ``kind == "at"``, ``data == {"file": "script/bridge.vns", "line": 14, "scene": "bridge"}``
  when the story moves to another line, at most about 10 a second (the newest place wins).

Only dev runs Studio starts send them (every Play is one). ``data`` is a fresh dict per
call; its strings are the game's (redacted, at most 1,024 characters, untrusted): show them
escaped. A callback that raises is logged and skipped; the others still run.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Any

from engine.tools.editor import consoleclient, gamebeside, studiostate
from engine.tools.editor import uiprefs
from engine.tools.editor.dialogs import ask, ask_text, show_info
from engine.tools.editor.hotreload import HotReload, HotReloadEvent
from engine.tools.editor.playbar import (  # noqa: F401  (re-exported: tests read them here)
    BEGINNING,
    START_VALUES_HEADING,
    PlayBar,
    Tooltip,
    ask_play_options,
)
from engine.tools.editor.preview import (
    POLL_INTERVAL_MS,
    PreviewEvent,
    PreviewState,
    editor_report,
    preview_argv,
    start_value_args,
    start_values_report,
)
from engine.tools.editor.syntax import LABEL_LINE
from engine.tools.editor.checkwiring import NO_PROBLEMS
from engine.tools.editor.studiolook import TAG_JUMP, line_of, plural
from engine.tools.editor.views import set_entry_enabled

_log = logging.getLogger(__name__)

STATUS_NOT_RUNNING = "Not running."
STATUS_TEXTS = {                        # 03 §2.2; DIDNT_START is didnt_start_text(n)
    PreviewState.NOT_RUNNING: STATUS_NOT_RUNNING,
    PreviewState.STARTING: "Starting…",
    PreviewState.RUNNING: "Running. F5 restarts it.",
    PreviewState.UPDATING: "Updating…",            # F39 S1 (HotReload's text wins)
    PreviewState.CLOSED: "Closed.",
    PreviewState.STOPPED_ERROR: "Stopped with an error, listed in Problems.",
    PreviewState.STOPPED_UNEXPECTED: "Stopped unexpectedly.",
}
# F32 (04 §6.8): Run ▸ "Preview title as playthrough…".
PLAYTHROUGH_MENU = "Preview title as playthrough…"
PLAYTHROUGH_ASK = "Preview the title as which playthrough?"
NO_PLAYTHROUGHS = "This game has no [playthrough] tables."
PLAYTHROUGH_CONFIG_HEAD = "config.toml has a problem, so the preview didn't start."
LIVE = (PreviewState.STARTING, PreviewState.RUNNING, PreviewState.UPDATING)
# F39: the game can be updated in these states (the error screen too, while it is open).
UPDATABLE = (*LIVE, PreviewState.STOPPED_ERROR)
# The game's window is open (and reads Studio's messages): ⟳ Update works, a docked game follows.
FOLLOWS = (PreviewState.RUNNING, PreviewState.STOPPED_ERROR)
UPDATE_MENU = "Update the running game"         # Run menu, Ctrl+R (F39 §4.2)
UPDATE_ON_SAVE_MENU = "Update the game on save"     # Run menu check, on by default (D2)
PREVIEW_GLYPH = "▶ "                    # the status item's prefix; F39's texts start with it
# F40 (01 §6.4): the Run menu's console items and the map box's.
CONSOLE_MENU = "Open console in the game"
JUMP_MENU = "Jump the game to this scene"
JUMP_HERE = "Jump the game here"
NO_GAME = "no game running"             # beside a dimmed console item (the accelerator column)
JUMP_NEEDS_GAME = "Console: play the game first (Shift+F5), then jump it to a scene."
JUMP_NEEDS_SCENE = ("Console: pick a scene first: a box on the Story map, or put the cursor "
                    "in a scene in the editor.")
# The spec's text, then what to do: the game doesn't answer while it loads or shows a
# screen that must finish first (the name question, a warning, a fade, the error screen).
DIDNT_ANSWER = (consoleclient.DIDNT_ANSWER + " It may be loading or showing a screen that "
                "has to finish first. Try again in a moment.")
CHANGE_ASK = "Change {name} in the game"
CHANGE_HINT = 'Like a start value: 3, True, "Hana" or [1, 2]'
CHANGE_OK = "Change"


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

    @property
    def runner(self) -> Any:
        """The game runner (``preview.PreviewRunner``; tests put a fake here). Setting it
        also points the hot reload at it."""
        return self._runner

    @runner.setter
    def runner(self, value: Any) -> None:
        self._runner = value
        hot = self.__dict__.get("hot")
        if hot is not None:
            hot.runner = value

    def _build_play_bar(self) -> None:
        """The Play bar under the menu bar, across the window (PR-F47-07). Packed before
        the panes; ``studiomenus`` packs the in-window menu bar above it."""
        key = "Cmd" if getattr(self, "mod", "Control") == "Command" else "Ctrl"
        self.play_bar = PlayBar(self.root, scale=self.scale, font=self.ui_font,
                                tip_font=self.fonts["small"], on_play=self.play_from_start,
                                on_scene=self.play_scene, on_stop=self.stop_game,
                                on_options=self.play_options, on_guide=self.toggle_guide,
                                on_assistant=getattr(self, "toggle_assistant", None),
                                on_update=self.update_game, update_key=f"{key}+R")
        self.play_bar.frame.pack(side="top", fill="x")
        self.play_bar.divider.pack(side="top", fill="x")
        self.play_button = self.play_bar.play_button       # ▶ Play, ■ Stop while running
        self.bar_focus = self.play_bar.buttons[0]         # the bar's Tab and F6 stop
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
        # Proposal 2.3: docked or floating (one setting, remembered for this person).
        # Docked unless this person chose Floating (the card's default, 2026-11-06).
        self.game_beside = tk.BooleanVar(master=self.root,
                                         value=uiprefs.value("game_beside") is not False)
        self.play_bar.add_check(gamebeside.MENU, self.game_beside, self.toggle_game_beside)
        self._room_before: tuple[str, str] | None = None
        self._follow_after: str | None = None
        self._followed: gamebeside.Rect | None = None
        bar = getattr(self, "status_bar", None)
        self.dock_pin = None
        if bar is not None:                 # the pin: Docked / Floating, at the far right
            self.dock_pin = bar.add(side="right", on_click=self.toggle_dock)
            self.dock_pin.tooltip = Tooltip(self.dock_pin.label, "", self.fonts["small"])
        self._show_dock_pin()
        self.root.bind("<Configure>", self._studio_moved, add="+")
        self.on_game_event(self._game_at)   # "playing <scene>" beside ■ Stop

    def _game_at(self, kind: str, data: dict) -> None:
        if kind == "at" and data.get("scene"):
            self.play_bar.set_playing(str(data["scene"]))

    def toggle_dock(self) -> None:
        """The status bar's pin: Docked ↔ Floating."""
        self.game_beside.set(not self.game_beside.get())
        self.toggle_game_beside()

    def toggle_game_beside(self) -> None:
        """Run ▸ Dock the game beside Studio (the ▾ menu's and the pin): kept for every
        game. Docking while the game runs moves it beside Studio now."""
        self.save_studio_state(game_beside=bool(self.game_beside.get()))
        self._show_dock_pin()
        if self.game_beside.get():
            self._followed = None
            self._follow_now()

    def _show_dock_pin(self) -> None:
        pin = self.__dict__.get("dock_pin")
        if pin is None:
            return
        docked = bool(self.game_beside.get())
        pin.configure(text=gamebeside.PIN_DOCKED if docked else gamebeside.PIN_FLOATING)
        pin.tooltip.text = gamebeside.TIP_DOCKED if docked else gamebeside.TIP_FLOATING

    def _studio_moved(self, event: tk.Event) -> None:
        """Studio moved or was resized: while docked with a game running, the game follows
        ``FOLLOW_MS`` after the last move."""
        if event.widget is not self.root or not self.game_beside.get() or \
                self.preview_state not in FOLLOWS:
            return
        if self._follow_after is not None:
            self.root.after_cancel(self._follow_after)
        self._follow_after = self.root.after(gamebeside.FOLLOW_MS, self._follow_now)

    def _follow_now(self) -> None:
        """Send the docked game its spot beside Studio, when it changed."""
        self._follow_after = None
        root = self.root
        if self.closed or not gamebeside.PLACES or not self.game_beside.get() or \
                self.preview_state not in FOLLOWS:
            return
        try:
            if not root.winfo_viewable() or str(root.state()) == "iconic":
                return
            caption = gamebeside.caption_of(root, self.scale)
            spot = gamebeside.place_game(
                gamebeside.studio_rect(root, caption), gamebeside.work_area(root),
                self._game_size(), caption=caption, gap=round(gamebeside.GAP * self.scale),
                share=False)
        except tk.TclError:
            return
        if spot is None or spot.game == self._followed:
            return                          # no room beside Studio: the game stays
        send = getattr(self.runner, "send", None)
        if callable(send) and send(gamebeside.window_line(spot.game)):
            self._followed = spot.game

    def _game_spot(self) -> list[str]:
        """``--window-at`` and ``--window-size`` beside Studio, or nothing (``gamebeside``).
        Studio makes room here when it must and may; a hidden or minimized Studio places
        nothing."""
        root = self.root
        if not gamebeside.PLACES:
            return []
        try:
            if not root.winfo_viewable() or str(root.state()) == "iconic":
                return []
            caption = gamebeside.caption_of(root, self.scale)
            spot = gamebeside.place_game(
                gamebeside.studio_rect(root, caption), gamebeside.work_area(root),
                self._game_size(), caption=caption, gap=round(gamebeside.GAP * self.scale),
                share=bool(self.game_beside.get()))
            if spot is None:
                return []
            if spot.studio is not None:
                before = gamebeside.make_room(root, spot.studio)
                root.update_idletasks()
                if self._room_before is None:
                    self._room_before = (before, str(root.geometry()))
        except tk.TclError:
            return []
        self._followed = spot.game
        docked = bool(self.game_beside.get())
        return [*spot.argv(), *((gamebeside.BORDERLESS,) if docked else ())]

    def _game_size(self) -> tuple[int, int]:
        """The game's own window size in screen pixels (``config.toml``'s ``[window]``)."""
        from engine.core.config import load_config
        from engine.core.config_schema import WindowConfig
        from engine.core.paths import GamePaths

        window = WindowConfig()
        try:
            loaded = load_config(GamePaths.for_game(self.paths.root))
            if loaded.config is not None:
                window = loaded.config.window
        except Exception:  # noqa: BLE001  (a config that can't load: the default size)
            pass
        return round(window.width * self.scale), round(window.height * self.scale)

    def _give_back_room(self) -> None:
        """The game ended: Studio as it was before it made room, unless it was moved or
        resized since."""
        saved, self._room_before = self.__dict__.get("_room_before"), None
        if saved is None:
            return
        before, made = saved
        try:
            if str(self.root.geometry()) == made:
                gamebeside.give_back(self.root, before)
        except tk.TclError:
            pass

    def _start_game(self, argv: list[str]) -> None:
        """Start the game child with ``argv`` placed beside Studio (``_game_spot``)."""
        spot = self._game_spot()
        if spot and "--report-to-editor" in argv:
            at = argv.index("--report-to-editor") + 1
            argv = [*argv[:at], *spot, *argv[at:]]
        self.runner.start(argv)
        self.apply_events(self.runner.poll())

    def save_studio_state(self, **changes: object) -> None:
        """Change ``.studio/studio.json``; after a link is found, nothing more is written
        for this window. How Studio looks (``uiprefs.LOOK_KEYS``: tabs, panes, Show
        warnings, Reduce motion) goes to the per-user file instead, for every game."""
        look = {key: changes.pop(key) for key in list(changes) if key in uiprefs.LOOK_KEYS}
        if look:
            uiprefs.save(**look)
        if not changes or not self._state_writable:
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

    # --- Hot reload (F39 §4.2, W2) ----------------------------------------------------------

    def _build_hot_reload(self) -> None:
        """``self.hot`` on the game runner, joined to the poll loop, and the Run menu's
        "Update the game on save" variable (on, per window, not remembered: D2). Built
        before the menus."""
        self.update_on_save = tk.BooleanVar(master=self.root, value=True)
        self._saved_refs: list[str] = []
        self._hot_suffix_shown = ""
        self.hot = HotReload(self.runner, start_check=self.request_saved_check,
                             check_running=self._check_under_way)
        self.join_runner(self.hot, self._on_hot_events)

    def _check_under_way(self) -> bool:
        """A check is asked for or running (its event will come)."""
        running = getattr(self.check_runner, "running", None)
        return bool(self.check_running if running is None else running)

    def update_game(self) -> None:
        """Run ▸ Update the running game (Ctrl+R): check the saved files, then restart
        the game at the same place. Nothing happens without a running game."""
        if self.closed or self.preview_state not in UPDATABLE:
            return
        self.hot.request()
        self._on_hot_events(self.hot.poll())        # ▶ Updating… now, not at the next tick

    def toggle_update_on_save(self) -> None:
        self.hot.update_on_save = bool(self.update_on_save.get())

    def after_saves(self) -> None:
        """After a save and its own check request: each saved ``.vns`` file or
        ``config.toml`` updates the running game (when the toggle is on)."""
        refs, self._saved_refs = self._saved_refs, []
        if self.closed or self.preview_state not in UPDATABLE:
            return
        for ref in refs:
            if self.hot.saved(ref):
                break                       # one update covers every file saved
        self._on_hot_events(self.hot.poll())

    def _on_hot_events(self, events: Sequence[HotReloadEvent]) -> None:
        for event in events:
            if self.closed:
                return
            self.status_label.configure(text=event.status.removeprefix(PREVIEW_GLYPH))
        self._sync_hot_suffix()

    def _sync_hot_suffix(self) -> None:
        """Redraw Problems when its summary's suffix (an update held) changes."""
        if not self.closed and self.hot.problems_suffix() != self._hot_suffix_shown:
            self.render_panel()

    def hot_suffix(self) -> str:
        """The Problems summary's F39 suffix now; remembered as shown."""
        hot = self.__dict__.get("hot")
        self._hot_suffix_shown = hot.problems_suffix() if hot is not None else ""
        return self._hot_suffix_shown

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

    def _save_before_play(self) -> bool:
        """Save every unsaved file (the first failure shows its dialog: False) and ask for
        the first full check (07 I-1)."""
        was_armed, dirty = self.armed, self.dirty_files()
        self.armed = True
        for record in dirty:
            if not self.save_record(record):
                return False
        if dirty or not was_armed:          # after saves, and the first full check (07 I-1)
            self.request_check()
        return True

    def play(self, label: str | None) -> None:
        """Play from ``label`` (None: the start). Saves every unsaved file first: the first
        failure shows its dialog and nothing starts. Start-value problems go to the panel,
        and nothing starts (I-5). Focus stays where it was (03 §4)."""
        if self.closed or not self._save_before_play():
            return
        args, problems = start_value_args(self.start_values_text)
        if problems:
            self.show_event(PreviewEvent(PreviewState.DIDNT_START,
                                         start_values_report(problems)))
            return
        self._saved_refs = []               # a restart, not an update
        self.hot.stop()
        self._start_game(preview_argv(self.paths.root, label, args, fresh=self.play_fresh))

    def stop_game(self) -> None:
        """■ Stop and Ctrl+F2: end the game child (only while it runs)."""
        if self.closed or self.preview_state not in LIVE:
            return
        self.hot.stop()
        self.runner.stop()
        self.show_event(PreviewEvent(PreviewState.CLOSED))

    def preview_playthrough(self) -> None:
        """Run ▸ Preview title as playthrough… (F32 04 §6.8): ``config.toml``'s
        ``[playthrough.N]`` keys in a small chooser, then the game's title as that
        playthrough (``run --playthrough N``: persistent data read, kept in memory). No
        tables: an info box. A config that fails to load: its errors in the panel, no
        chooser, no preview (07 G8). Start values and "Play as a new player" don't apply."""
        if self.closed:
            return
        from engine.core.config import load_config
        from engine.core.paths import GamePaths

        loaded = load_config(GamePaths.for_game(self.paths.root))
        if loaded.errors:
            self.show_event(PreviewEvent(PreviewState.DIDNT_START, editor_report(
                *(error.format() for error in loaded.errors), head=PLAYTHROUGH_CONFIG_HEAD)))
            return
        numbers = sorted(loaded.config.playthrough)
        if not numbers:
            show_info(self.root, NO_PLAYTHROUGHS)
            return
        picked = ask(self.root, PLAYTHROUGH_ASK, [*(str(n) for n in numbers), "Cancel"],
                     escape=len(numbers))
        if picked >= len(numbers) or not self._save_before_play():
            return
        self._saved_refs = []               # a restart, not an update
        self.hot.stop()
        self._start_game(preview_argv(self.paths.root, None, [],
                                      extra=("--playthrough", str(numbers[picked]))))

    def play_extras(self, page: str = "gallery") -> None:
        """F34 Database ▸ Gallery's ▶ Preview the gallery: saves like ▶ Play, then runs the
        game's dev ``run --extras <page>`` through the Play bar (Extras opens on ``page``
        with everything in it unlocked in memory; nothing is saved). Start values and "Play
        as a new player" don't apply."""
        if self.closed or not self._save_before_play():
            return
        self._saved_refs = []               # a restart, not an update
        self.hot.stop()
        self._start_game(preview_argv(self.paths.root, None, [], extra=("--extras", page)))

    def play_replay(self, label: str) -> None:
        """F36 Database ▸ Scene replays' and ending rows' ▶ Play replay: saves like ▶ Play,
        then runs the game's dev ``run --replay <label>`` through the Play bar (the scene
        plays as a replay; nothing is saved). Start values and "Play as a new player" don't
        apply."""
        if self.closed or not self._save_before_play():
            return
        self._saved_refs = []               # a restart, not an update
        self.hot.stop()
        self._start_game(preview_argv(self.paths.root, None, [], replay=label))

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
            self._poll_console()
            self._poll_game_events()
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

    def on_game_event(self, callback: Callable[[str, dict], object]) -> Callable[[], None]:
        """Call ``callback(kind, data)`` for each line report from the running game (see
        the module docstring); returns the function that unsubscribes it."""
        listeners = self.__dict__.setdefault("_game_listeners", [])
        listeners.append(callback)

        def unsubscribe() -> None:
            if callback in listeners:
                listeners.remove(callback)
        return unsubscribe

    def _poll_game_events(self) -> None:
        """The line reports read this tick, to every ``on_game_event`` listener."""
        read = getattr(self.runner, "game_events", None)
        events = read() if callable(read) else []
        listeners = self.__dict__.get("_game_listeners") or []
        for event in events:
            for callback in list(listeners):
                try:
                    callback(event.kind, dict(event.data))
                except Exception:  # noqa: BLE001  (one listener never stops the others)
                    _log.exception("A game event listener failed")

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
        text = self.hot.preview_event(event)        # F39: S1/S2 while an update runs
        self.status_label.configure(text=status_text(event) if text is None
                                    else text.removeprefix(PREVIEW_GLYPH))
        self.play_bar.set_running(event.state in LIVE)
        self.play_bar.set_updatable(event.state in UPDATABLE, enabled=event.state in FOLLOWS)
        if event.state not in UPDATABLE:        # the game is gone: Studio as it was
            self._give_back_room()
        elif event.state is PreviewState.RUNNING:   # docked: where Studio is now (an update
            self._followed = None                   # reopens the game at its old spot)
            self._follow_now()
        set_entry_enabled(self.run_menu, UPDATE_MENU, event.state in UPDATABLE)
        self._sync_hot_suffix()
        self._console_state_changed()
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

    # --- The developer console (F40 W2) -----------------------------------------------------

    game_values: tuple[bool, dict[str, str]] | None = None     # (story running, name → text)

    @property
    def console(self) -> consoleclient.ConsoleTracker:
        """The console requests waiting on an answer (made on first use)."""
        tracker = self.__dict__.get("_console_tracker")
        if tracker is None:
            tracker = self.__dict__["_console_tracker"] = consoleclient.ConsoleTracker()
        return tracker

    @property
    def game_running(self) -> bool:
        """Whether a game is running that can take console requests."""
        return self.preview_state is PreviewState.RUNNING

    def open_console(self) -> None:
        """Run ▸ Open console in the game (F12): ``open`` to the running game; with none,
        Play from the start, then ``open`` once it runs (PR-F40-18)."""
        if self.closed:
            return
        if self.game_running:
            self.console_send("open", consoleclient.open_line())
            return
        self._console_open_pending = True
        if self.preview_state not in LIVE:      # a game already starting just gets it later
            self.play_from_start()
            if self.preview_state not in LIVE:  # didn't start (a save or a start value)
                self._console_open_pending = False

    def jump_game_to_scene(self) -> None:
        """Run ▸ Jump the game to this scene: the selected box while the Story map shows,
        else the scene at the editor's cursor."""
        if not self.game_running:
            self.console_status(JUMP_NEEDS_GAME)
            return
        label = self.scene_to_play()
        if label is None:
            self.console_status(JUMP_NEEDS_SCENE)
            return
        self.jump_game_to(label)

    def jump_game_to(self, label: str) -> None:
        """Jump the running game to scene ``label`` (PR-F40-19)."""
        if not self.game_running:
            self.console_status(JUMP_NEEDS_GAME)
            return
        self.console_send("jump", consoleclient.jump_line(label))

    def change_in_game(self, name: str, shown: str) -> None:
        """Database's **Change…**: a one-field dialog, then ``set`` (PR-F40-20)."""
        if not self.game_running:
            return
        answer = ask_text(self.root, CHANGE_ASK.format(name=name), shown, ok=CHANGE_OK,
                          hint=lambda _text: CHANGE_HINT, select_stem=False)
        if answer is None or not answer[0].strip():
            return
        self.console_send("set", consoleclient.set_line(name, answer[0].strip()))

    def ask_game_values(self) -> None:
        """Ask the running game for every variable's value (Database's In the game now)."""
        if self.game_running and not self.console.waiting("values"):
            self.console_send("values", consoleclient.values_line(), quiet=True)

    def console_send(self, do: str, line: bytes | None, *, quiet: bool = False) -> bool:
        """Send one console message line and wait (2 s) for its answer. None (a value
        too long to send) shows the bad-value text."""
        if line is None:
            self.console_status(consoleclient.STATUS.format(text=consoleclient.BAD_VALUE))
            return False
        send = getattr(self.runner, "send", None)
        if send is None or not send(line):
            if not quiet:
                self.console_status(DIDNT_ANSWER)
            return False
        self.console.sent(do)
        return True

    def console_status(self, text: str) -> None:
        """``text`` in the status bar's preview item for 5 s, then the preview state."""
        label = self.status_label
        if self.__dict__.get("_console_shown") is None:
            self._console_before = str(label.cget("text"))
        label.configure(text=text)
        self._console_shown = text
        after = self.__dict__.get("_console_after")
        if after is not None:
            self.root.after_cancel(after)
        self._console_after = self.root.after(
            round(consoleclient.STATUS_SHOW_S * 1000), self._console_status_done)

    def _console_status_done(self) -> None:
        self._console_after = None
        shown, self._console_shown = self.__dict__.get("_console_shown"), None
        if not self.closed and shown is not None and \
                str(self.status_label.cget("text")) == shown:
            self.status_label.configure(text=self._console_before)

    def _console_state_changed(self) -> None:
        """A preview state: the console items on or off, a pending ``open`` sent, the
        waiting requests forgotten when the game ends, and Database told."""
        running = self.game_running
        self._console_shown = None              # the new state's text is the one to keep
        menu = getattr(self, "run_menu", None)
        if menu is not None:
            set_entry_enabled(menu, JUMP_MENU, running)
            menu.entryconfigure(JUMP_MENU, accelerator="" if running else NO_GAME)
        if running and self.__dict__.get("_console_open_pending"):
            self._console_open_pending = False
            self.console_send("open", consoleclient.open_line())
        if self.preview_state not in LIVE:
            self._console_open_pending = False
            self.console.clear()
            self.game_values = None
        database = getattr(self, "database", None)
        if database is not None:
            database.game_running_changed(running)

    def _poll_console(self) -> None:
        """The game's console answers (untrusted text: shown escaped, never acted on), and
        the requests that went unanswered for 2 s."""
        read = getattr(self.runner, "console_events", None)
        events = read() if callable(read) else []
        for event in events:
            answer = self.console.receive(event, self._console_names())
            if answer is None:
                continue
            if answer.do == "values":
                self.game_values = (bool(answer.story), answer.values)
                self._values_arrived()
                continue
            if answer.status is not None:
                self.console_status(answer.status)
            if answer.do == "set":
                self.ask_game_values()          # the value refreshes after each Change
        for do in self.console.overdue():
            if do == "values":
                self.game_values = None
                self._values_arrived()
            else:
                self.console_status(DIDNT_ANSWER)

    def _console_names(self) -> frozenset[str]:
        database = getattr(self, "database", None)
        return frozenset(database.game_value_names()) if database is not None else frozenset()

    def _values_arrived(self) -> None:
        database = getattr(self, "database", None)
        if database is not None:
            database.game_values_changed()

