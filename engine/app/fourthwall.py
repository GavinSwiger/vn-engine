"""F30 fourth-wall tricks in the window: the title bar and the fake crash (F30
``04-technical.md`` §6.1, §6.2; ``05`` SEC-F30-05, -09, -10; ``07`` I-6, I-11).

Why this module exists: the runtime only says what the window should show (``WindowTitle``,
``FakeCrash``); ``app`` owns the window and the screens, so the two handlers live here, wired
once per launch by ``install_fourthwall`` (from ``install_story``):

- **The title** (``apply_title``): ``[game] title`` when the command's title is None, else
  the script's text, cleaned by ``display_title`` (Cc, Cf, Cs, Zl, and Zp become U+FFFD; at
  most ``WINDOW_TITLE_MAX`` code points), so applying a title never raises. Every way out of
  the story puts the game's title back: the shell's in-game reset (New Game, a load, the
  return to the title, the story's end), ``show_fatal_error`` (C6), and the ending card's
  ``WindowTitle(None)`` (the runtime's ``clear_title``). Nothing here writes or logs a title.
- **The fake crash** (``open_crash``): the stage owns the wait first (F15 sees a click wait;
  a restore or New Game ends it). While skip runs nothing shows: skip's next update passes
  the wait (PR-F30-16). Otherwise F12's persistent data is written now (``flush_now``; a
  failure is one DEBUG line and the page still shows), then ``FakeCrashScreen`` is pushed
  with the message (``crash_text``: never redacted, never logged, never in history) and the
  ``[words]`` hint, the label only when the player turned it on, and a fade only under
  reduced effects.

Step 5 adds the player's name (``name_source``, the ``UsernameSource`` wiring, W188, and the
redaction term); until then ``name_source`` gives None and a ``{username}`` span shows its
fallback word. Only this module may import ``engine.meta.username``.
"""

import unicodedata
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from engine.core.constants import WINDOW_TITLE_MAX
from engine.core.logsetup import get_logger
from engine.runtime.commands import FakeCrash, WaitDone, WindowTitle
from engine.ui.builtin.fake_crash import FakeCrashScreen, crash_text
from engine.ui.theme import Words

if TYPE_CHECKING:
    from engine.app.app import App

_log = get_logger("app")

_REPLACED: Final = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_REPLACEMENT: Final = "�"


def display_title(text: str) -> str:
    """``text`` as the window's title bar shows it (04 §6.1 step 1, SEC-F30-09(b)): at most
    ``WINDOW_TITLE_MAX`` code points, each control, format, lone surrogate, line separator, and
    paragraph separator replaced with U+FFFD."""
    return "".join(_REPLACEMENT if unicodedata.category(ch) in _REPLACED else ch
                   for ch in text[:WINDOW_TITLE_MAX])


class FourthWall:
    """The launch's ``WindowTitle`` and ``FakeCrash`` handlers and the title reset."""

    def __init__(self, app: "App") -> None:
        self.app = app
        # F30 s5: the player's name for ``{username}`` (``UsernameSource.name``); None: the
        # fallback word.
        self.name_source: Callable[[], str | None] = lambda: None

    # -- the title (04 §6.1) --

    def apply_title(self, cmd: WindowTitle) -> None:
        """The ``WindowTitle`` handler: the script's title, or ``[game] title`` for None."""
        title = cmd.title if cmd.title is not None else self.app.config.game.title
        self.app.set_title(display_title(title))

    def reset_title(self) -> None:
        """The shell's in-game reset: the game's own title (new game, load, title, end)."""
        self.app.set_title(display_title(self.app.config.game.title))

    # -- the fake crash (04 §6.2) --

    def open_crash(self, cmd: FakeCrash) -> None:
        """The ``FakeCrash`` handler: the stage's wait, then (unless skipping) a flush of
        persistent data and the page."""
        app = self.app
        stage = app.stage_screen
        if stage is None:                       # an App wired by hand: nothing to show on
            if app.story is not None:
                app.story.post(WaitDone(cmd.wait_id))
            return
        stage.start_wait(cmd)
        skip = getattr(app, "skip_auto", None)
        if skip is not None and skip.skipping:
            return                              # skip's next update passes it (PR-F30-16)
        persist = getattr(app, "persist", None)
        if persist is not None:
            try:
                persist.flush_now()
            except Exception:
                _log.debug("Persistent data couldn't be written before the fake crash",
                           exc_info=True)
        words = self._words()
        config = app.config
        screen = FakeCrashScreen(
            message=crash_text(cmd.body, self.name_source(), words.get("fake_crash_message")),
            game_title=config.game.title, game_version=config.game.version,
            hint=words.get("fake_crash_hint"),
            label=words.get("fake_crash_label") if self._label_on() else None,
            fade=self._reduce(), on_continue=stage.press,
            waiting=lambda: stage.wait_id == cmd.wait_id, stack=app.screens,
            focused=lambda: bool(getattr(app, "focused", True)))
        app.screens.push(screen)

    def _words(self) -> Words:
        shell = self.app.shell
        return shell.words if shell is not None else Words(self.app.config.words)

    def _label_on(self) -> bool:
        """The player's ``crash_label`` setting (F30 s5 adds the key; off until then)."""
        settings = self.app.settings
        if settings is None or "crash_label" not in settings.defaults:
            return False
        return bool(settings.value("crash_label"))

    def _reduce(self) -> bool:
        """Reduced effects: ``[effects] reduce`` OR the player's setting (F16)."""
        settings = self.app.settings
        if settings is not None:
            return settings.effective_reduce()
        stage = self.app.stage_screen
        return bool(stage.settings.reduce) if stage is not None \
            else bool(self.app.config.effects.reduce)


def install_fourthwall(app: "App") -> FourthWall:
    """Once per launch, after ``install_ui`` (``install_story``): register ``WindowTitle`` →
    ``apply_title`` and ``FakeCrash`` → ``open_crash`` (always: the router picks the most
    specific type, so ``StageScreen``'s ``StoryWait`` handler never sees a crash), and the
    title reset as a shell in-game reset."""
    fourthwall = FourthWall(app)
    router = app.router
    router.unregister(WindowTitle)              # nothing else applies a title
    router.register(WindowTitle, fourthwall.apply_title)
    router.register(FakeCrash, fourthwall.open_crash)
    shell = app.shell
    if shell is not None:
        shell.add_in_game_reset(fourthwall.reset_title)
    return fourthwall


__all__ = ["FourthWall", "display_title", "install_fourthwall"]
