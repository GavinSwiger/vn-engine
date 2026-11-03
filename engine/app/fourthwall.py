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

- **The name** (step 5, ``04`` §6.3, §6.4, §6.7; SEC-F30-01, 03, 04, 07): a real
  ``UsernameSource`` exists only when the author offers the name (``[meta] username``) and
  the launch has no F44 start options; otherwise ``name_source`` gives None and every
  ``{username}`` span draws its fallback word. The source reads (``read_login_name``, looked
  up here at install time so tests swap in a fake reader) only while ``username_use`` is 2,
  at most once per opt-in, at the first draw of a line holding the name. An unreadable name
  logs W188 once per session (it names only the fallback word). The first name read (3
  graphemes or more) becomes ``redact``'s session term, so a leaked exception text shows
  ``<user>``; ``forget()`` clears it. The textbox and the NVL page get ``name`` as their
  source and ``names_changed`` as the ``username_use`` listener. The Settings rows follow
  ``row_rules``: the name row iff ``[meta] username``, the label row iff the story has an
  ``effect crash``. ``UsernameGate`` answers the first-launch question (``due``/``answer``)
  for the shell's pre-title slot (``ShellPorts.username_question``, set here), and a quit
  guard stores "Don't allow" when the window closes while the question is open.

Only this module may import ``engine.meta.username``. Nothing here logs or stores the name.
"""

import unicodedata
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from engine.core import redact
from engine.core.constants import WINDOW_TITLE_MAX
from engine.core.graphemes import graphemes
from engine.core.logsetup import get_logger
from engine.meta.username import UsernameSource, read_login_name
from engine.runtime.commands import FakeCrash, WaitDone, WindowTitle
from engine.runtime.errors import format_message
from engine.runtime.fourthwall import uses_crash
from engine.ui.builtin.fake_crash import FakeCrashScreen, crash_text
from engine.ui.builtin.username_question import UsernameQuestion
from engine.ui.theme import Words

if TYPE_CHECKING:
    from engine.app.app import App

_log = get_logger("app")

_REPLACED: Final = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_REPLACEMENT: Final = "�"
TERM_MIN_GRAPHEMES: Final = 3          # SEC-F30-04: shorter names add no redaction term


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
        # F30 s5: the player's name for ``{username}`` (``name``); None: the fallback word.
        self.name_source: Callable[[], str | None] = lambda: None
        self.source: UsernameSource | None = None
        self.gate: UsernameGate | None = None
        self._term = False                      # the session redaction term is set

    # -- the name (04 §6.3, §6.4) --

    def wire_name(self, read: Callable[[], str | None]) -> None:
        """A real source (module docstring): only with ``[meta] username`` on, settings,
        and no start options."""
        app = self.app
        settings = getattr(app, "settings", None)
        if not app.config.meta.username or settings is None \
                or getattr(app, "start", None) is not None:
            return
        self.source = UsernameSource(allowed=lambda: settings.value("username_use") == 2,
                                     read=read, on_failure=self._w188)
        self.name_source = self.name

    def name(self) -> str | None:
        """The name to draw, or None; the first name read becomes the redaction term."""
        source = self.source
        if source is None:
            return None
        name = source.name()
        if name is not None and not self._term and len(graphemes(name)) >= TERM_MIN_GRAPHEMES:
            redact.set_session_term(name)
            self._term = True
        return name

    def settings_changed(self, keys: frozenset[str]) -> None:
        """The ``username_use`` listener: off forgets the name and its term; the textbox
        and NVL page show the line again with the name or the fallback."""
        if "username_use" not in keys:
            return
        settings = getattr(self.app, "settings", None)
        if self.source is not None and (settings is None
                                        or settings.value("username_use") != 2):
            self.source.forget()
            redact.set_session_term(None)
            self._term = False
        textbox = getattr(self.app, "textbox", None)
        if textbox is not None:
            textbox.names_changed()

    def _w188(self) -> None:
        fallback = self.app.config.meta.username_fallback
        _log.warning("%s", format_message("W188", (fallback,)), extra={"code": "W188"})

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
            message=crash_text(cmd.body, self.name_source() if _holds_name(cmd.body) else None,
                               words.get("fake_crash_message")),
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
        settings = getattr(self.app, "settings", None)
        if settings is None or "crash_label" not in settings.defaults:
            return False
        return bool(settings.value("crash_label"))

    def _reduce(self) -> bool:
        """Reduced effects: ``[effects] reduce`` OR the player's setting (F16)."""
        settings = getattr(self.app, "settings", None)
        if settings is not None:
            return settings.effective_reduce()
        stage = self.app.stage_screen
        return bool(stage.settings.reduce) if stage is not None \
            else bool(self.app.config.effects.reduce)


class UsernameGate:
    """F30's first-launch question for the shell's pre-title slot (04 §6.7; 07 I-2):
    ``due()`` is True at most once per session, when the author offers the name, settings
    exist, ``username_use`` is 0 (never answered), and there are no start options.
    ``answer(allow)`` stores 2 or 1 (the only writer besides the Settings row and Reset)."""

    def __init__(self, app: "App") -> None:
        self.app = app
        self._asked = False

    def due(self) -> bool:
        app = self.app
        settings = getattr(app, "settings", None)
        due = (not self._asked and bool(app.config.meta.username) and settings is not None
               and settings.value("username_use") == 0
               and getattr(app, "start", None) is None)
        if due:
            self._asked = True
        return due

    def answer(self, allow: bool) -> None:
        settings = getattr(self.app, "settings", None)
        if settings is not None:
            settings.set("username_use", 2 if allow else 1)


def _holds_name(body: object) -> bool:
    """``body`` (a resolved crash message, or None) holds a ``{username}`` span."""
    pieces = getattr(body, "pieces", ())
    return any(getattr(getattr(p, "style", None), "username", False) for p in pieces)


def install_fourthwall(app: "App", *, read: Callable[[], str | None] | None = None
                       ) -> FourthWall:
    """Once per launch, after ``install_ui`` (``install_story``): register ``WindowTitle`` →
    ``apply_title`` and ``FakeCrash`` → ``open_crash`` (always: the router picks the most
    specific type, so ``StageScreen``'s ``StoryWait`` handler never sees a crash), and the
    title reset as a shell in-game reset. Step 5: the name's source (``read``: default this
    module's ``read_login_name``), the textbox and NVL seams, the ``username_use`` listener,
    the Settings row rules, the question's gate (``app.fourthwall``, the shell's
    ``username_question`` port), and its quit guard."""
    fourthwall = FourthWall(app)
    fourthwall.wire_name(read if read is not None else read_login_name)
    fourthwall.gate = UsernameGate(app)
    textbox = getattr(app, "textbox", None)
    if textbox is not None:
        textbox.set_name_source(fourthwall.name_source)
        clean = getattr(app.shell, "clean_capture", None)      # the shell's (04 §6.6)
        if clean is not None:
            textbox.set_clean_capture(clean)
    settings = getattr(app, "settings", None)
    if settings is not None:
        settings.add_listener(fourthwall.settings_changed)
        offered = bool(app.config.meta.username)
        program = getattr(getattr(app.story, "interp", None), "program", None)
        crash = program is not None and uses_crash(program)
        settings.row_rules["settings_username"] = lambda: offered
        settings.row_rules["settings_crash_label"] = lambda: crash
    app.fourthwall = fourthwall                                 # type: ignore[attr-defined]
    router = app.router
    router.unregister(WindowTitle)              # nothing else applies a title
    router.register(WindowTitle, fourthwall.apply_title)
    router.register(FakeCrash, fourthwall.open_crash)
    shell = app.shell
    if shell is not None:
        shell.add_in_game_reset(fourthwall.reset_title)
        # The first-launch question (04 §6.7): the shell's pre-title slot after F33's
        # warning; closing the window while it is open stores "Don't allow" (Q6), before
        # F16's settings are written at exit.
        shell.ports = replace(shell.ports, username_question=fourthwall.gate)
        app.add_quit_guard(lambda: _quit_answers(app))
    return fourthwall


def _quit_answers(app: "App") -> bool:
    """The question's quit guard: an open question answers "Don't allow"; never vetoes."""
    for screen in list(app.screens):
        if isinstance(screen, UsernameQuestion):
            screen.answer_on_quit()
    return True


__all__ = ["FourthWall", "TERM_MIN_GRAPHEMES", "UsernameGate", "display_title",
           "install_fourthwall"]
