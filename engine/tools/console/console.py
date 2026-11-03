"""The console in the running game (F40 ``04`` §1, §7.1, §7.5, §7.6; W1).

Why this module exists: ``App`` has an inert ``console`` slot and calls it only in dev runs
(``App.dev``) for raw input, once per frame, and to draw. This class decides *when* the
model may act, so a change always lands while the story rests, and it answers Studio.

- **Where it may act** (``04`` §7.1): not while the story loads, in error mode, in the
  shell's ENDING mode, or while F30's fake crash, F30's name question, F33's warning, F11's
  load fade or F39's resume screen shows. There F12 is ignored, the console closes, and
  Studio's messages are dropped (not answered). Otherwise ``where_now`` sorts the moment.
- **Keys** (``key``): closed, F12 asks to open; the console opens on the first frame the
  story rests (F12 in a forward chain waits for its end). Open, every keyboard, text, mouse,
  wheel and controller event goes to the panel, so the screens below see none.
- **The hold** (``holds_story``): while open the App doesn't pump the story, except after a
  Jump, until the story rests at the label's first line (then the rows refresh).
- **Actions** (keys and Studio's ``jump``/``set``) wait in a queue and are applied in
  ``frame`` only while ``not interp.busy``. Each Studio request gets one ``console`` answer
  line; queued ``values`` requests coalesce to one answer per frame.
- **Jump**: in a game, ``Interpreter.console_jump`` and then the shell's
  ``enter_game(…, choose=False)`` (the in-game screens reset, the held scene preamble shows
  the stage again at the next pump; nothing is reset when the jump is refused). On the title,
  a new game at the label (``enter_game(new_game)``, ``start`` set to the label for that
  call only), as Studio's Play from scene.
- **Drawing**: only from ``App.present``, so the console is never in a thumbnail, a scene
  picture or a menu backdrop (those are drawn from the screen stack).

One ``ConsoleModel`` per story (a new one if ``app.program`` changes). Nothing here logs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from engine.app import input as app_input
from engine.app.hot_reload import ResumeScreen
from engine.app.loading import StoryLoadScreen
from engine.core.startvalues import StartOptions
from engine.tools.console import runner
from engine.tools.console.answer import console_event
from engine.tools.console.model import Action, Close, ConsoleModel, Where, where_now
from engine.tools.console.panel import ConsolePanel, start_typing, stop_typing
from engine.ui.builtin.content_warning import ContentWarningScreen
from engine.ui.builtin.fake_crash import FakeCrashScreen
from engine.ui.builtin.load_fade import LoadFadeScreen
from engine.ui.builtin.username_question import GroundScreen, UsernameQuestion
from engine.ui.shell import Mode

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.app.hot_reload import ConsoleRequest
    from engine.render.canvas import Canvas
    from engine.runtime.interpreter import Interpreter

# Screens on top of which the console never opens or acts (04 §7.1's last row).
BLOCKING_SCREENS = (FakeCrashScreen, UsernameQuestion, GroundScreen, ContentWarningScreen,
                    LoadFadeScreen, StoryLoadScreen, ResumeScreen)
# The input events an open console takes (04 §7.6); window, audio and other events pass.
INPUT_EVENTS = frozenset({
    pygame.KEYDOWN, pygame.KEYUP, pygame.TEXTINPUT, pygame.TEXTEDITING,
    pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.MOUSEWHEEL,
    pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION,
    pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP, pygame.CONTROLLERAXISMOTION,
    pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP, pygame.JOYAXISMOTION, pygame.JOYHATMOTION,
})


class DevConsole:
    """The ``App.console`` slot's object (module docstring)."""

    def __init__(self, app: App) -> None:
        self.app = app
        self.open = False
        self._want_open = False
        self._settling = False                 # after a Jump: the story runs to its line
        self._actions: list[Action] = []
        self._studio: list[ConsoleRequest] = []
        self._model: ConsoleModel | None = None
        self._panel: ConsolePanel | None = None

    # -- The App's calls ---------------------------------------------------------------------

    @property
    def holds_story(self) -> bool:
        """While open the story doesn't advance (PR-F40-06), except while a Jump settles."""
        return self.open and not self._settling

    def key(self, event: pygame.event.Event) -> bool:
        """One raw event (after the fullscreen and F3 keys). True when the console took it."""
        if not self.open:
            if event.type != pygame.KEYDOWN or event.key != pygame.K_F12:
                return False
            if self.where() is not None:
                self._want_open = True         # opens when the story rests (frame)
            return True
        if event.type not in INPUT_EVENTS:
            return False
        app = self.app
        action = self._panel.handle(app_input.translate(event, app.viewport, app.window))
        if isinstance(action, Close):
            self.close()
        elif action is not None:
            self._actions.append(action)
        return True

    def studio(self, request: ConsoleRequest) -> None:
        """Studio's ``console`` message (``EditorLink.update``): queued for ``frame``, or
        dropped (not answered) where the console can't act."""
        if self.where() is None:
            return
        self._studio.append(request)

    def frame(self) -> None:
        """Once per frame, after the story pump and Studio's messages (04 §7.1)."""
        where = self.where()
        if where is None:
            self._drop()
            return
        interp = self.app.story.interp
        if interp.busy:
            return
        model = self._ensure_model()
        if self._settling:
            self._settling = False
            model.refresh(where, interp)
        if self._want_open:
            self._want_open = False
            self._open(where, interp)
        while self._actions:
            self._apply(self._actions.pop(0))
            if not self._resting():
                self._actions.clear()          # a Jump: the rest would act on a moving story
                break
        self._answer_studio()

    def draw(self, canvas: Canvas) -> None:
        """``App.present``, above the screens and under notices and the F3 overlay."""
        if self.open and self._panel is not None:
            self._panel.draw(canvas)

    def close(self) -> None:
        if not self.open:
            return
        self.open = False
        if self._model is not None:
            self._model.closed()
        stop_typing()

    # -- Where the story is ------------------------------------------------------------------

    def where(self) -> Where | None:
        """``04`` §7.1: None where the console must not act, else ``where_now``."""
        app = self.app
        shell, story = app.shell, app.story
        if (app.loading or app.error_mode or shell is None or story is None
                or app.program is None):
            return None
        if any(isinstance(screen, BLOCKING_SCREENS) for screen in app.screens):
            return None
        if shell.mode is Mode.TITLE:
            return Where.NO_STORY
        if shell.mode is not Mode.GAME:
            return None
        host = app.minigame_host
        return where_now(story.interp,
                         minigame_host=getattr(host, "session", None) is not None)

    def _resting(self) -> bool:
        story = self.app.story
        return story is not None and not story.interp.busy and not self._settling

    # -- Inside ------------------------------------------------------------------------------

    def _ensure_model(self) -> ConsoleModel:
        program = self.app.program
        if self._model is None or self._model.program is not program:
            self._model = ConsoleModel(program, run_code=runner.run_code, jump=self._jump,
                                       guarded=runner.guarded)
            self._panel = ConsolePanel(self._model)
        return self._model

    def _open(self, where: Where, interp: Interpreter) -> None:
        if self.open:
            return
        skip_auto = self.app.skip_auto
        if skip_auto is not None:              # PR-F40-06
            skip_auto.stop_skip()
            skip_auto.set_auto(False)
        self.open = True
        self._model.opened(where, interp)
        start_typing()

    def _apply(self, action: Action) -> object:
        where = self.where()
        if where is None:
            return None
        return self._model.apply(action, where, self.app.story.interp)

    def _answer_studio(self) -> None:
        requests, self._studio = self._studio, []
        values_asked = False
        for request in requests:
            do = request.do
            if do == "values":
                values_asked = True
                continue
            if do == "open":
                where = self.where()
                if where is not None:
                    self._open(where, self.app.story.interp)
                self._send(console_event("open", True, ""))
                continue
            if not self._resting():            # a Jump settles: answer the rest next frame
                self._studio.append(request)
                continue
            action = ConsoleModel.studio_action(request)
            if action is None:
                continue
            result = self._apply(action)
            if result is not None:
                self._send(console_event(do, result.ok, result.text))
        if values_asked:
            where = self.where()
            if where is not None:
                story, pairs = self._model.values(where, self.app.story.interp)
                self._send(console_event("values", True, "", story=story, values=pairs))

    def _send(self, line: bytes) -> None:
        link = self.app.editor_link
        if link is not None:
            link.send_line(line)

    def _drop(self) -> None:
        self.close()
        self._want_open = False
        self._settling = False
        self._actions.clear()
        self._studio.clear()

    def _jump(self, label: str, new_game: bool) -> str | None:
        """The model's ``jump`` (module docstring). Returns the reason it was refused."""
        app = self.app
        story, shell = app.story, app.shell
        interp = story.interp
        if new_game:
            before = interp.start
            values = before.values if before is not None else ()
            interp.start = StartOptions(label=label, values=values)
            try:
                shell.enter_game(story.new_game)
            finally:
                interp.start = before
        else:
            reason = interp.console_jump(label)
            if reason:
                return reason
            shell.enter_game(lambda: None, choose=False)
        self._settling = True
        return None


__all__ = ["BLOCKING_SCREENS", "DevConsole", "INPUT_EVENTS"]
