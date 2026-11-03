"""``GameShell``: the flow between the title and the game (F10 ``04`` §5.4, §7.7).

Why this module exists: launching, New Game, the story's end, and the return to the title
each change the whole stack, the title music, and what may run, and they must agree with
each other (a new game leaves nothing of the last one; the story never runs under the
title). One object owns that flow, so screens and features never replace the stack on their
own. ``app/menus.py: install_ui`` builds it once per launch with injected ports
(``ShellPorts``); ``ui`` never imports ``engine.app``.

Flows (§7.7):
- **Launch** (``initial_screens``): first the pre-title steps that are due, in a fixed
  order (F33's content warning, then F30's name question), each in mode TITLE and none
  with start options; then (``pre_title_done``), with start options (F44
  ``--start``/``--set``) or ``[title] enabled = false``, a new game starts at once;
  otherwise the title, fading in.
- **New Game** (``start_new_game``): title music out, the title fades to black over
  ``ui.fade_ms`` taking no input, then: music released, in-game screens reset (F15's hooks
  after), ``new_game()``, and the stack becomes ``in_game_screens()``.
- **Story end** (``story_ended``, the ``StoryEnded`` handler): story audio stops, the game
  fades to black over 1 s (``BlackFadeScreen``), then the title fades in (or, with no title,
  the game quits).
- **Game menu** (``open_game_menu``, from ``GameMenuKeys`` and the quick menu's Menu): pushed
  over the in-game screens only in mode GAME with no menu open. Its Main Menu and Quit ask
  first (``ask_main_menu``, ``ask_quit``: No is focused when opened by keys).
- **Return to title** (``return_to_title``, Main Menu → Yes): the question goes at once,
  story audio stops, everything fades to black over ``ui.fade_ms`` (no input), then the
  title.
- **Quit** (``quit_guard``, registered once by ``install_ui``): on the title and during a
  fade the game quits at once; in game the quit question is asked, and a second window close
  while it is open quits at once. Yes (``quit_confirmed``) asks ``App.request_quit`` again,
  so later guards (F11's save on quit) still run. A top screen that ``quits_at_once`` (F30's
  fake crash) quits at once, after F12's flush.
Under reduced motion every fade is a cut in the frame it would start.

The shell is also the ``MenuShell`` every ``MenuScreen`` uses (stack, assets, theme, words,
painter, cursor, ``play_ui``) and holds the entry registry and F10's overrides
(``ui/menus.py``).

F32 looks (``04`` §4.3, §6.3, §6.4): ``theme`` is a property, the current look's ``UiTheme``
once ``app/looks.py: install_looks`` gave the shell its ``Looks`` (``set_looks``), else the
launch's base theme. The playthrough look is chosen (``_choose``) only at four moments: the
launch (``set_looks``), a title opening, a new game (before ``new_game()``), and a load
(before the in-game screens), so ``$ persistent.playthrough = 2`` mid-story changes nothing
until then. The title's pictures and music are the current look's; a picture a new look
names is never read in the frame that chose it (the title draws its fill colors there,
under the fade-in's black, 07 G3), and the launch look's pictures are read in ``set_looks``,
during the load screen. Notices (F11 C2): ``notify`` hands a message to the one ``NoticeLayer``
(``ui/notice.py``); ``App`` calls ``update_layer`` after the screens' update and
``draw_layer`` after the screens are drawn and before the dev overlay, and
``show_fatal_error`` calls ``clear_notices``. ``forward_notices`` drains a service's
``take_notices()`` into one notice (F11 I-10, F16 I-13; F12's once its words exist).

Scene capture for save thumbnails (F11 C3, ``04`` §7.3): ``capture_scene(then)`` hands
``then`` a 320×180 picture (``render/thumbnail.make_thumbnail``) or None. In game with no
menu up, the request waits for ``draw_layer``, which shrinks this frame's canvas once for
every request of the frame, after the screens and before the notices and the dev overlay.
Under a menu or confirm it gets the **kept thumbnail** at once: the shell makes it whenever
a menu's ``CapturedBackdrop`` copies the scene directly over an in-game screen (once per open
and per resize recapture; a confirm over the game menu keeps the game menu's). The scene is
frozen while a menu is up, so the kept thumbnail stays valid until the frame in which the
last menu has gone (``update_layer`` drops it; so Quit → Yes, which removes the question
before it quits, still saves it), and a new game, the title, or a load drops it too
(``_reset_in_game``). On the title and during a fade between title and game: None.
F30 (``07`` I-5, I-6): while a ``private_picture`` screen (the fake crash) is anywhere on the
stack no picture is taken or kept (None), and ``picture_private()`` tells F11's ``can_save``.
F30's clean thumbnail (``04`` §6.6, SEC-F30-03): a textbox that shows the player's name calls
``clean_capture(canvas)`` before it draws its box; when this frame captures (``scene_wanted``:
a pending request, or a menu's backdrop not yet captured) the stage alone is shrunk into the
frame's ``_clean``, which ``_serve_captures`` and ``_scene_captured`` use instead of the full
canvas; ``draw_layer`` clears it. The name never reaches a save picture.

A load (F11 C8, ``show_loaded_game``) restores first, under the menus, and closes them only
when the restore succeeded: no closing fade, the in-game screens reset with F11's
``LoadFadeScreen`` on top (the scene fades in from black), mode GAME.

Seams kept free for later features: F11's
``set_confirm_key`` (it feeds ``confirm_key``) and ``add_before_title`` (run first in
``return_to_title``); F12 I-1's flush of persistent data before the title or a quit is the
``flush_persist`` port. F14's limit cue is the one cue layer (``set_cue_layer``, A3,
ui-system layer 6): updated after the notices with ``covered`` (a screen that isn't in-game on
top, or mode not GAME), drawn after the scene captures and before the notices while not
covered.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final, Protocol

from engine.core.config import did_you_mean
from engine.core.config_schema import Config
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.render.thumbnail import make_thumbnail
from engine.runtime.commands import StoryEnded
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.load_fade import LoadFadeScreen
from engine.ui.menu_screen import CursorKeeper, MenuScreen
from engine.ui.menus import DEFAULT_ORDER, MENU_NOUNS, MenuRegistry, UiOverrides, join_names
from engine.ui.nav import InputKind
from engine.ui.notice import Kind, NoticeLayer, notice_style
from engine.ui.paint import Painter
from engine.ui.screen import Screen, ScreenStack
from engine.ui.theme import F10_ENTRY_WORDS, UiTheme, Words, measure_with, warn_label_cuts

if TYPE_CHECKING:
    import pygame

    from engine.render.assets import AssetManager, ImageRef
    from engine.render.canvas import Canvas
    from engine.ui.builtin.quick_menu import QuickMenu
    from engine.ui.builtin.title_screen import TitleScreen
    from engine.ui.looks import Looks

_log = get_logger("ui")

CaptureThen = Callable[["pygame.Surface | None"], None]

STORY_END_FADE_S: Final = 1.0          # 03 Motion: the story end's fade to black
STORY_AUDIO_FADE_S: Final = 0.5        # stop_story_audio on a story end or Main Menu → Yes
TITLE_MUSIC_OWNER: Final = "title"
# The [words] key of each question the game menu asks (F11's set_confirm_key may change them).
CONFIRM_KEYS: Final = {"main_menu": "confirm_main_menu", "quit": "confirm_quit"}
# The config section of each menu's author list (W66).
ENTRY_SECTIONS: Final = {"title": "title", "quick": "quick_menu"}


class Mode(Enum):
    TITLE = "title"
    GAME = "game"
    ENDING = "ending"            # a fade to black, to the title, or from the title runs


class MusicHandle(Protocol):
    """F08's music handle (``AudioService.take_music``)."""

    def play(self, file: str, *, loop: bool, fadein: float) -> None: ...

    def stop(self, *, fadeout: float) -> None: ...

    def release(self) -> None: ...


class AudioPort(Protocol):
    """What the shell uses of F08's ``AudioService``."""

    def take_music(self, owner: str) -> MusicHandle: ...

    def stop_story_audio(self, seconds: float) -> None: ...

    def play_ui(self, file: str) -> None: ...


class WarningPort(Protocol):
    """F33 (I-1): ``app/content_warning.py``'s ``WarningGate``. ``due()`` is True at most
    once per session; ``acknowledge()`` records Continue."""

    def due(self) -> bool: ...

    def acknowledge(self) -> None: ...


class QuestionPort(Protocol):
    """F30 (04 §6.7): ``app/fourthwall.py``'s ``UsernameGate``. ``due()`` is True at most
    once per session; ``answer(allow)`` stores the player's choice."""

    def due(self) -> bool: ...

    def answer(self, allow: bool) -> None: ...


class CueLayer(Protocol):
    """F14 A3: the shell's one in-game cue layer (F14's ``LimitCue``)."""

    def update(self, dt: float, *, covered: bool, reduce_motion: bool) -> None: ...

    def draw(self, canvas: "Canvas") -> None: ...


@dataclass(frozen=True)
class ShellPorts:
    """Injected by ``app/menus.py``. ``in_game_screens`` is ``bootstrap.in_game_screens``
    (I-2: the one list, ``[StageScreen, TextboxScreen]``). ``reset_in_game`` clears the
    in-game screens before a new game or the title (I-8). ``request_quit`` is
    ``App.request_quit()`` (not forced). ``skip_title``: ``App.start`` has a label or values.
    ``flush_persist``: F12's ``persist.flush_soon()`` (I-1), before the title or a quit.
    ``content_warning``: F33's ``WarningGate`` (a pre-title step, ``initial_screens``).
    ``username_question``: F30's ``UsernameGate`` (the next pre-title step;
    ``install_fourthwall`` sets it after ``install_ui``)."""

    stack: ScreenStack
    assets: "AssetManager"
    dev: bool
    config: Config
    new_game: Callable[[], None]
    in_game_screens: Callable[[], list[Screen]]
    reset_in_game: Callable[[], None]
    request_quit: Callable[[], None]
    audio: AudioPort | None = None
    textbox: object | None = None          # F05's TextboxScreen (settings, hidden)
    skip_title: bool = False
    flush_persist: Callable[[], None] | None = None
    content_warning: WarningPort | None = None
    username_question: "QuestionPort | None" = None


def reduce_motion_of(config: Config) -> bool:
    """``[effects] reduce`` once F09 adds it (F16 later); False until then."""
    effects = getattr(config, "effects", None)
    return bool(getattr(effects, "reduce", False))


class GameShell:
    """Owns the title ↔ game flow; the ``MenuShell`` of every F10 screen."""

    def __init__(self, ports: ShellPorts, *, theme: UiTheme, words: Words,
                 cursor: CursorKeeper | None = None) -> None:
        self.ports = ports
        self.config = ports.config
        self.base_theme = theme                     # the launch's [theme] (F32: no layers)
        self.looks: "Looks | None" = None           # F32 (set_looks)
        self._playthrough: Callable[[], int] | None = None
        self._defer_pictures = False                # F32 07 G3: the frame that chose a look
        self.overrides = UiOverrides()
        self.words = words
        words.override = self.overrides.word
        self.menus = MenuRegistry(entries={"title": self.config.title.entries,
                                           "quick": self.config.quick_menu.entries},
                                  overrides=self.overrides)
        self.painter = Painter(theme)
        self.cursor = cursor if cursor is not None else CursorKeeper()
        self.reduce_motion = reduce_motion_of(self.config)
        self.mode = Mode.TITLE
        self.entries_checked = False
        # Step 8: the launch's ``QuickMenu`` overlay (``install_ui`` sets it; F07's choice
        # floor and tests read it).
        self.quick_menu: "QuickMenu | None" = None
        self._resets: list[Callable[[], None]] = []
        self._before_title: list[Callable[[], None]] = []          # F11 C5
        self._confirm_fns: dict[str, Callable[[], str]] = {}       # F11 C6
        self._quit_confirm: ConfirmScreen | None = None
        self._quit_confirmed = False
        self._music: MusicHandle | None = None
        self._music_file: str | None = None
        self._music_stopping = False
        self._images: dict[str, "ImageRef | None"] = {}
        # F11 C3: the 320×180 thumbnail of the scene under the open menus, and the capture
        # requests waiting for this frame's ``draw_layer``.
        self.kept_thumbnail: "pygame.Surface | None" = None
        self._captures: list[CaptureThen] = []
        # F30 (04 §6.6): this frame's thumbnail of the stage drawn before a textbox showing
        # the player's name (``clean_capture``); ``draw_layer`` clears it.
        self._clean: "pygame.Surface | None" = None
        self._cue: CueLayer | None = None                          # F14 A3: layer 6
        # F23 I-8: the one thumbnail source (a running minigame's opening picture).
        self._thumbnail_source: "Callable[[], pygame.Surface | None] | None" = None
        style = notice_style(theme)
        self.notices = NoticeLayer(
            style, measure_with(ports.assets, style.font),
            text_scale=self.painter.text_scale, reduce_motion=lambda: self.reduce_motion,
            play=self.play_ui)

    # -- MenuShell --

    @property
    def theme(self) -> UiTheme:
        """The current look's ``UiTheme`` (F32), else the launch's base theme."""
        looks = self.looks
        return looks.current().theme if looks is not None else self.base_theme

    @property
    def stack(self) -> ScreenStack:
        return self.ports.stack

    @property
    def assets(self) -> "AssetManager":
        return self.ports.assets

    @property
    def dev(self) -> bool:
        return self.ports.dev

    def play_ui(self, token: str | None) -> None:
        """A UI sound through F08 (``play_ui``); nothing without audio or a token."""
        audio = self.ports.audio
        if token is not None and audio is not None:
            audio.play_ui(token)

    # -- notices (F11 C2, 04 §7.9) --

    def notify(self, text: str, *, kind: Kind = "info") -> None:
        """Show a notice (``"info"``, or ``"problem"`` with its bar) over whatever is on
        top. It waits while the top screen ``holds_notices`` (C7). F11, F12 (SEC-F12-12),
        F16 (W70), and F37 call this with their words."""
        self.notices.notify(text, kind=kind, hold=self._holds_notices())

    def update_layer(self, dt: float, *, focused: bool) -> None:
        """``App``, after ``ScreenStack.update``: notice times run while ``focused`` and the
        pointer is not over the notice; waiting ones show once the top screen lets them.
        Then the cue layer (F14 A3) with ``covered`` and ``reduce_motion``."""
        self.notices.update(dt, focused=focused, pointer=self.stack.pointer,
                            hold=self._holds_notices())
        if self.kept_thumbnail is not None and not self._menu_open():
            self.kept_thumbnail = None              # the game runs again: no longer frozen
        cue = self._cue
        if cue is not None:
            cue.update(dt, covered=self._game_covered(), reduce_motion=self.reduce_motion)

    def draw_layer(self, canvas: "Canvas") -> None:
        """``App.present``, after the screens and before the dev overlay: this frame's scene
        captures first (C3), then the cue layer while the game isn't covered (F14 A3,
        ui-system layer 6), then the notices (so neither is ever part of a thumbnail, scene
        picture, or backdrop). A look chosen this frame may read its title pictures from the
        next frame on (F32 07 G3)."""
        self._defer_pictures = False
        if self._captures:
            self._serve_captures(canvas)
        self._clean = None                          # F30: this frame's only
        cue = self._cue
        if cue is not None and not self._game_covered():
            cue.draw(canvas)
        self.notices.draw(canvas, self.painter)

    def set_cue_layer(self, layer: "CueLayer | None") -> None:
        """F14 A3 (``07`` §3.3): the one in-game cue layer (ui-system layer 6, above the
        choices, under the notices), F14's ``LimitCue``. One slot: a second user goes
        through architecture review. ``App`` skips the layer calls in error mode."""
        self._cue = layer

    def _game_covered(self) -> bool:
        """F14 A3: the game is covered (a screen that isn't in-game on top, or mode not
        GAME): the cue ends and isn't drawn."""
        top = self.stack.top
        return self.mode is not Mode.GAME or top is None or not top.in_game

    def clear_notices(self) -> None:
        """``show_fatal_error``: the error screen shows no notice."""
        self.notices.clear()

    def forward_notices(self, take: Callable[[], Sequence[object]], key: str, *,
                        kind: Kind = "problem") -> bool:
        """F11 I-10 (F16 I-13; F12 SEC-F12-12 once its words exist): drain a service's
        ``take_notices()`` into one notice, the ``[words]`` value of ``key``. Nothing is
        drained while ``key`` is not a known word, so a later call still finds them. True
        when a notice was given."""
        if key not in self.words.keys():
            return False
        if not list(take()):
            return False
        self.notify(self.words.get(key), kind=kind)
        return True

    def _holds_notices(self) -> bool:
        top = self.stack.top
        return bool(getattr(top, "holds_notices", False)) if top is not None else False

    # -- scene capture for save thumbnails (F11 C3, 04 §7.3) --

    def capture_scene(self, then: CaptureThen) -> None:
        """Hand ``then`` this scene's 320×180 thumbnail, or None. On the title and during a
        fade between title and game (mode TITLE or ENDING): None at once. With the kept
        thumbnail (a menu or confirm is up over the game, or the last one left in this
        frame): that, at once. Otherwise in this frame's ``draw_layer``: one shrink of the
        canvas as the screens drew it serves every request of the frame (or the kept
        thumbnail, if a menu opened in between)."""
        if self.mode is not Mode.GAME or self.picture_private():
            then(None)
            return
        picture = self._source_picture()
        if picture is not None:
            then(picture)
        elif self.kept_thumbnail is not None:
            then(self.kept_thumbnail)
        else:
            self._captures.append(then)

    def set_thumbnail_source(self, fn: "Callable[[], pygame.Surface | None] | None") -> None:
        """F23 (``04`` §7.8, ``07`` I-8; one slot): ``fn()`` is asked first by
        ``capture_scene`` and again when this frame's captures are served; a 320×180
        surface it returns is the thumbnail (a running minigame's opening picture), None
        leaves F11's normal capture. None clears the slot."""
        self._thumbnail_source = fn

    def picture_private(self) -> bool:
        """F30 (07 I-6): a ``private_picture`` screen (the fake crash) is on the stack, so no
        save picture is taken and F11's ``can_save()`` is False unless quitting."""
        return any(getattr(screen, "private_picture", False) for screen in self.stack)

    def scene_wanted(self) -> bool:
        """F30 (04 §6.6 step 1): this frame takes a picture of the scene: a capture request
        waits for ``draw_layer``, or a menu on the stack has a backdrop not yet captured."""
        if self._captures:
            return True
        return any(isinstance(s, MenuScreen) and s.backdrop is not None
                   and not s.backdrop.ready for s in self.stack)

    def clean_capture(self, canvas: "Canvas") -> None:
        """F30 (04 §6.6 step 2; SEC-F30-03): the textbox, before drawing a box that shows the
        player's name. When this frame captures, the canvas as drawn so far (the stage and
        its effects; no say window, choices, or quick menu) becomes this frame's ``_clean``
        thumbnail; otherwise nothing (no shrink on frames that take no picture)."""
        surface = canvas.surface
        if surface is None or self.mode is not Mode.GAME or self.picture_private() \
                or not self.scene_wanted():
            return
        self._clean = make_thumbnail(surface)

    def _source_picture(self) -> "pygame.Surface | None":
        source = self._thumbnail_source
        return source() if source is not None else None

    def _serve_captures(self, canvas: "Canvas") -> None:
        pending, self._captures = self._captures, []
        surface = canvas.surface
        if self.mode is Mode.TITLE or surface is None or self.picture_private():
            picture = None
        elif (source := self._source_picture()) is not None:
            picture = source                        # F23 I-8: a minigame's opening picture
        elif self._menu_open():
            picture = self.kept_thumbnail           # the menu itself is never in it
        elif self._clean is not None:
            picture = self._clean                   # F30: the stage without the name
        else:
            picture = make_thumbnail(surface)
        for then in pending:
            then(picture)

    def _menu_open(self) -> bool:
        return any(isinstance(s, MenuScreen) for s in self.stack)

    def _watch_backdrop(self, screen: Screen) -> None:
        """Keep the thumbnail of what ``screen``'s backdrop captures (C3)."""
        backdrop = getattr(screen, "backdrop", None)
        if backdrop is not None:
            backdrop.on_scene = lambda scene: self._scene_captured(screen, scene)

    def _scene_captured(self, screen: Screen, scene: "pygame.Surface") -> None:
        """A backdrop copied the screens below ``screen``: in game, directly over an in-game
        screen, that scene becomes the kept thumbnail (a confirm over the game menu, or a
        menu over the title, keeps nothing; nor does anything while a ``private_picture``
        screen is on the stack, F30)."""
        if self.mode is not Mode.GAME or self.picture_private():
            return
        screens = list(self.stack)
        index = next((i for i, s in enumerate(screens) if s is screen), 0)
        if index > 0 and screens[index - 1].in_game:
            clean = self._clean                     # F30: the stage without the name
            self.kept_thumbnail = clean if clean is not None else make_thumbnail(scene)

    # -- F32 looks (04 §4.3, §6.3) --

    def set_looks(self, looks: "Looks", playthrough: Callable[[], int]) -> None:
        """``install_looks``: the session's ``Looks`` and how to read the playthrough number.
        Words ask the look after F10's overrides, the title's buttons come from the look,
        and the launch's playthrough look is chosen now (before ``initial_screens``, so F33's
        warning has it) with its title pictures read here, during the load screen."""
        self.looks = looks
        self._playthrough = playthrough
        self.words.override = looks.word
        self.menus.title_entries = looks.title_entries
        self._choose()
        self._defer_pictures = False
        for part in ("background", "logo"):
            self.title_image(part)

    def _choose(self) -> None:
        """Choose the playthrough look from persistent data (one of the four moments)."""
        looks, read = self.looks, self._playthrough
        if looks is None or read is None:
            return
        before = looks.revision
        looks.choose(read())
        if looks.revision != before:
            self._defer_pictures = True

    # -- seams --

    def add_in_game_reset(self, fn: Callable[[], None]) -> None:
        """F15 I-4: ``fn()`` runs after ``reset_in_game`` on New Game and on the way back to
        the title (skip and auto end there), in the order added."""
        self._resets.append(fn)

    def confirm(self, message: str, on_yes: Callable[[], None], *,
                on_no: Callable[[], None] | None = None, yes: str = "yes", no: str = "no",
                by: InputKind) -> ConfirmScreen:
        """Push the one Yes/No dialog over the top screen; focus returns to the opener."""
        screen = ConfirmScreen(self, message, on_yes, on_no, yes=yes, no=no, by=by)
        self._push_over_top(screen)
        return screen

    def _push_over_top(self, screen: MenuScreen) -> None:
        self._watch_backdrop(screen)
        top = self.stack.top
        if isinstance(top, MenuScreen):
            top.push_child(screen)                  # focus returns to its opener after
        else:
            self.stack.push(screen)

    # -- launch (§7.7.1) --

    def initial_screens(self) -> list[Screen]:
        """What shows once the story is installed: the first pre-title step that is due
        (F33's content warning), else ``_first_screens()``."""
        step = self._next_pre_title()
        return step if step is not None else self._first_screens()

    def _first_screens(self) -> list[Screen]:
        """The game at once with start options or no title, else the title fading in from
        black."""
        if self.ports.skip_title or not self.config.title.enabled:
            self._choose()                          # F32: before new_game()
            self.ports.new_game()
            self.mode = Mode.GAME
            return list(self.ports.in_game_screens())
        self.mode = Mode.TITLE
        return [self._title_screen()]

    # -- pre-title steps (F33 07 I-2) --

    def _next_pre_title(self) -> list[Screen] | None:
        """The pre-title steps in their fixed order, the screens of the first that is due:
        F33's content warning, then F30's name question (``GroundScreen`` under
        ``UsernameQuestion``, 04 §6.7). Each runs in mode TITLE (quit with no question, no
        game menu, no saves), holds notices, is skipped with start options, and never calls
        ``new_game()``. No registry: a new step is a new line here."""
        if self.ports.skip_title:
            return None
        warning = self.ports.content_warning
        if warning is not None and warning.due():
            from engine.ui.builtin.content_warning import ContentWarningScreen

            cw = self.config.content_warning
            self.mode = Mode.TITLE
            return [ContentWarningScreen(self, text=cw.text, min_seconds=cw.min_seconds,
                                         on_continue=warning.acknowledge,
                                         on_quit=self.ports.request_quit,
                                         then=self.pre_title_done)]
        question = self.ports.username_question
        if question is not None and question.due():
            from engine.ui.builtin.username_question import GroundScreen, UsernameQuestion

            self.mode = Mode.TITLE
            return [GroundScreen(self), UsernameQuestion(self, on_answer=question.answer,
                                                         then=self.pre_title_done)]
        return None

    def pre_title_done(self) -> None:
        """A pre-title step finished (F33: Continue, after its fade to black; F30: an
        answer, once the question has closed): the next due step, else the title or the
        game (``new_game()`` runs only now)."""
        step = self._next_pre_title()
        self.stack.replace_all(step if step is not None else self._first_screens())

    def _title_screen(self) -> "TitleScreen":
        from engine.ui.builtin.title_screen import TitleScreen

        self._choose()                              # F32: every title opening
        return TitleScreen(self, fade_in=True)

    # -- New Game (§7.7.2) --

    def start_new_game(self) -> None:
        """The title's New Game: music out, the title fades to black (no input), then the
        game cuts in. Ignored unless the title is showing."""
        if self.mode is not Mode.TITLE:
            return
        from engine.ui.builtin.title_screen import TitleScreen

        title = next((s for s in reversed(list(self.stack)) if isinstance(s, TitleScreen)),
                     None)
        self.leave_title()
        self.mode = Mode.ENDING
        if title is None:
            self._new_game_cut()
            return
        seconds = 0.0 if self.reduce_motion else self.theme.cfg.ui.fade_ms / 1000.0
        title.leave(seconds, then=self._new_game_cut)

    def _new_game_cut(self) -> None:
        self._release_title_music()
        self._reset_in_game()
        self._choose()                              # F32: before new_game()
        self.ports.new_game()
        self.mode = Mode.GAME
        self.stack.replace_all(self.ports.in_game_screens())

    # -- a loaded game (F11 C8, 04 §7.6 step 5) --

    def show_loaded_game(self) -> None:
        """F11 C8: a load's restore succeeded (it ran first, under the menus, so the story
        hold kept its burst): every menu and confirm goes at once with no fade; from the
        title its music fades out (``leave_title``, PR-F10-24); the in-game screens are reset
        (F15's hooks after) and become the stack, with ``LoadFadeScreen`` on top (PR-F11-34;
        none under reduce motion or with ``[theme.save] load_fade_ms = 0``); mode GAME; the
        kept thumbnail goes. The restored line shows at the next pump, under the fade."""
        if self.mode is Mode.TITLE:
            self.leave_title()
        self._choose()                              # F32: before the in-game screens
        self._reset_in_game()
        self.mode = Mode.GAME
        screens = list(self.ports.in_game_screens())
        fade_ms = self.theme.cfg.save.load_fade_ms
        if not self.reduce_motion and fade_ms > 0:
            screens.append(LoadFadeScreen(fade_ms / 1000.0, self.stack))
        self.stack.replace_all(screens)

    def _reset_in_game(self) -> None:
        self.kept_thumbnail = None                  # nothing of the last scene (C3)
        self.ports.reset_in_game()
        for fn in list(self._resets):
            fn()

    # -- the game menu (§7.7.3) --

    def open_game_menu(self, by: InputKind) -> None:
        """Push the game menu over the in-game screens: only in mode GAME and while no
        menu is open (Esc or right click under a menu never stacks a second one)."""
        if self.mode is not Mode.GAME:
            return
        if any(isinstance(s, MenuScreen) for s in self.stack):
            return
        menu = GameMenuScreen(self, by=by)
        self._watch_backdrop(menu)
        self.stack.push(menu)

    def game_menu(self) -> GameMenuScreen | None:
        """The open game menu (F11's ``scene_picture``, F16's ``refresh_backdrop``)."""
        for screen in reversed(list(self.stack)):
            if isinstance(screen, GameMenuScreen):
                return screen
        return None

    def close_game_menu(self) -> None:
        """The game menu's Return."""
        menu = self.game_menu()
        if menu is not None:
            menu.close()

    def open_title_page(self, entry_id: str, by: InputKind) -> None:
        """A title entry's page (F11 Load, F16 Settings) in the game menu's layout over the
        title, with Return first; Back closes it."""
        if self.mode is not Mode.TITLE:
            return
        entry = self.menus.entry("title", entry_id)
        assert entry is not None and entry.page is not None, \
            f"{entry_id!r} is not a page entry of the title"
        self._push_over_top(GameMenuScreen(self, by=by, title_page=entry_id))

    def confirm_key(self, action: str) -> str:
        """The ``[words]`` key of the Main Menu (``"main_menu"``) or Quit (``"quit"``)
        question. With no title, Main Menu asks and acts as Quit (PR-F10-27). F11's
        ``set_confirm_key`` (C6) supplies its own function per action here."""
        if action == "main_menu" and not self.config.title.enabled:
            action = "quit"
        fn = self._confirm_fns.get(action)
        return fn() if fn is not None else CONFIRM_KEYS[action]

    def set_confirm_key(self, action: str, key: Callable[[], str]) -> None:
        """F11 C6: ``key()`` names the ``[words]`` key of the ``"main_menu"`` or ``"quit"``
        question each time it is asked (F11: the auto-save wording while saving can)."""
        if action not in CONFIRM_KEYS:
            raise ValueError(f"set_confirm_key: unknown action {action!r}")
        self._confirm_fns[action] = key

    def add_before_title(self, fn: Callable[[], None]) -> None:
        """F11 C5: ``fn()`` runs first in ``return_to_title`` (Main Menu → Yes), while the
        mode is still GAME and the kept thumbnail is there, in the order added."""
        self._before_title.append(fn)

    def ask_main_menu(self, by: InputKind) -> None:
        """The game menu's Main Menu: ask, and on Yes return to the title (with no title:
        the quit question, and Yes quits)."""
        if not self.config.title.enabled:
            self.ask_quit(by)
            return
        self._ask(self.words.get(self.confirm_key("main_menu")), self.return_to_title, by)

    def ask_quit(self, by: InputKind) -> None:
        """The game menu's Quit and the quit guard's question; Yes quits."""
        self._quit_confirm = self._ask(self.words.get(self.confirm_key("quit")),
                                       self.quit_confirmed, by)

    def _ask(self, message: str, on_yes: Callable[[], None], by: InputKind) -> ConfirmScreen:
        # Yes takes the picture away in its own frame (a fade to black, or the exit), so the
        # dialog goes without a closing fade (04 §7.7.4 step 2).
        screen = ConfirmScreen(self, message, on_yes, by=by, yes_cuts=True)
        self._push_over_top(screen)
        return screen

    # -- quitting (§7.7.6) --

    def quit_guard(self) -> bool:
        """``App``'s quit guard. True (quit now) on the title, during a fade, after Yes, or
        when the quit question is already open (a second window close), and, after F12's
        flush, when the top screen ``quits_at_once`` (F30's fake crash: nothing more is
        asked; F11's quit save still runs). Otherwise any other question goes (as No,
        without its callback), the quit question opens (No focused unless the mouse moved
        since the last key), and the quit waits: False."""
        if self.mode is not Mode.GAME or self._quit_confirmed:
            return True
        top = self.stack.top
        if top is not None and getattr(top, "quits_at_once", False):
            self._flush_persist()
            return True
        if self._quit_confirm is not None and self._quit_confirm in list(self.stack):
            return True
        for screen in list(self.stack):
            if isinstance(screen, ConfirmScreen):
                self.stack.remove(screen)
        by = InputKind.MOUSE if self.stack.last_input is InputKind.MOUSE else InputKind.KEYS
        self.ask_quit(by)
        return False

    def quit_confirmed(self) -> None:
        """Quit → Yes: quit through ``App.request_quit``; this guard now allows it and later
        guards (F11) still run."""
        self._quit_confirmed = True
        self._flush_persist()
        self.ports.request_quit()

    def _flush_persist(self) -> None:
        flush = self.ports.flush_persist
        if flush is not None:
            flush()

    # -- the story's end and the return to the title (§7.7.4, §7.7.5) --

    def story_ended(self, cmd: StoryEnded) -> None:
        """The ``StoryEnded`` handler. It arrives only while an in-game screen is top (the
        story hold); in any other mode it is ignored with a DEBUG line."""
        if self.mode is not Mode.GAME:
            _log.debug("StoryEnded ignored: the shell is in mode %s", self.mode.name)
            return
        self._stop_story_audio()
        self.mode = Mode.ENDING
        self._fade_then(STORY_END_FADE_S, self._after_story_end)

    def return_to_title(self) -> None:
        """Main Menu → Yes: story audio stops in this frame, the question goes, everything
        (scene and game menu) fades to black over ``ui.fade_ms`` taking no input, then the
        title fades in with its music. F11's ``add_before_title`` hooks run first here."""
        if self.mode is not Mode.GAME:
            return
        for fn in list(self._before_title):         # F11 C5: the Main Menu auto-save
            fn()
        self._flush_persist()                       # F12 I-1
        self._stop_story_audio()
        self.mode = Mode.ENDING
        for screen in list(self.stack):
            if isinstance(screen, ConfirmScreen):
                self.stack.remove(screen)
        self._fade_then(self.theme.cfg.ui.fade_ms / 1000.0, self._show_title)

    def _after_story_end(self) -> None:
        if self.config.title.enabled:
            self._show_title()
        else:
            self.ports.request_quit()              # mode ENDING: nothing asks first

    def _show_title(self) -> None:
        self._reset_in_game()
        self.mode = Mode.TITLE
        self.stack.replace_all([self._title_screen()])

    def _fade_then(self, seconds: float, then: Callable[[], None]) -> None:
        if self.reduce_motion or seconds <= 0:
            then()                                  # a cut: no black frame
        else:
            self.stack.push(BlackFadeScreen(seconds, then))

    def _stop_story_audio(self) -> None:
        audio = self.ports.audio
        if audio is not None:
            audio.stop_story_audio(STORY_AUDIO_FADE_S)

    # -- title look and music (§7.9) --

    def title_image(self, part: str) -> "ImageRef | None":
        """The title's ``"background"`` or ``"logo"`` of the current look (F32): the base
        ref gives the image ``resolve_theme`` checked (W64); another ref (a playthrough
        table's, checked at launch, W207) is read once on first draw, never in the frame
        that chose the look (None there: the fill colors show, 07 G3)."""
        base = self.base_theme
        ref = getattr(self.theme.cfg.title, f"{part}_image")
        if ref == getattr(base.cfg.title, f"{part}_image"):
            return base.background if part == "background" else base.logo
        if ref is None:
            return None
        if ref not in self._images:
            if self._defer_pictures:
                return None
            image = self.assets.image(ref)
            self._images[ref] = None if image.is_placeholder else image
        return self._images[ref]

    def title_music_file(self) -> str | None:
        """The current look's ``[theme.title] music`` (F32)."""
        return self.theme.cfg.title.music

    def title_entered(self) -> None:
        """``TitleScreen.on_enter``: the title takes the music stream and plays its music
        looped (a missing file is F08's log line and silence, PR-F10-24)."""
        self._music_stopping = False
        file = self.title_music_file()
        audio = self.ports.audio
        if file is None or audio is None:
            return
        if self._music is None:
            self._music = audio.take_music(TITLE_MUSIC_OWNER)
        self._music.play(file, loop=True, fadein=self.config.audio.music_fadein)
        self._music_file = file

    def title_look_changed(self) -> None:
        """The title look changed while the title shows: restart the music if it changed
        (the art is re-read on the next draw). F32 calls it nowhere (a new look shows when a
        title opens, 04 §6.4)."""
        if self.mode is not Mode.TITLE or self._music_stopping:
            return
        file = self.title_music_file()
        if file == self._music_file:
            return
        if self._music is not None:
            self._music.stop(fadeout=self.config.audio.music_fadeout)
            if file is None:
                self._release_title_music()
                return
        self.title_entered()

    def leave_title(self) -> None:
        """The title music fades out (``[audio] music_fadeout``). New Game calls it; F11
        calls it before a load from the title. The handle is released when the title
        goes."""
        if self._music is not None and not self._music_stopping:
            self._music.stop(fadeout=self.config.audio.music_fadeout)
        self._music_stopping = True

    def title_exited(self) -> None:
        """``TitleScreen.on_exit``: whatever replaced the title, its music is let go."""
        if self._music is not None:
            if not self._music_stopping:
                self._music.stop(fadeout=self.config.audio.music_fadeout)
            self._release_title_music()

    def _release_title_music(self) -> None:
        music, self._music = self._music, None
        self._music_file = None
        if music is not None:
            music.release()

    # -- W66 and W68, once every feature has registered (I-2) --

    def check_entries(self) -> None:
        """The last line of ``install_story``: W66 for each name in ``[title] entries`` and
        ``[quick_menu] entries`` that no feature registered for that menu (with
        ``config.py``'s did-you-mean, I-10) and for an empty list, then W68 (dev) for the
        words the menus show. A menu with nothing registered (an App wired by hand) is not
        checked."""
        if self.entries_checked:
            return
        self.entries_checked = True
        lists = [(menu, section, "entries", self.menus.config_list(menu))
                 for menu, section in ENTRY_SECTIONS.items()]
        lists += [("title", f"playthrough.{n}", "title_entries", table.title_entries)
                  for n, table in sorted(self.config.playthrough.items())]     # F32
        for menu, section, key, author in lists:
            registered = self.menus.registered(menu)
            if author is None or not registered:
                continue
            if not any(name in registered for name in author):
                # Empty, or naming no button of this menu: the defaults show (AC-F10-27).
                _log.warning("%s", w66_empty_text(section, registered, author, menu=menu,
                                                  key=key), extra={"code": "W66"})
                continue
            for name in author:
                if name not in registered:
                    _log.warning("%s", w66_text(section, menu, name, registered, key=key),
                                 extra={"code": "W66"})
        known = set(self.words.keys())                # a later id brings its word (I-10)
        shown = {menu: [e.id for e in self.menus.shown(menu) if e.id in known]
                 or list(F10_ENTRY_WORDS[menu]) for menu in DEFAULT_ORDER}
        warn_label_cuts(self.theme, self.words, self.assets, dev=self.dev, menus=shown)


def w66_text(section: str, menu: str, name: str, registered: list[str], *,
             key: str = "entries") -> str:
    """W66: a name in ``entries`` that isn't a button of that menu (G7 drafts the
    ``[title]`` form and the list join). F32: ``[playthrough.N] title_entries`` too."""
    text = (f'config.toml: [{section}] {key} has "{echo(name)}", which isn\'t a '
            f"{MENU_NOUNS[menu]}.")
    close = did_you_mean(name, registered)
    if close is not None:
        text += f' Did you mean "{close}"?'
    return text + f" The buttons are {join_names(registered)}."


def w66_empty_text(section: str, registered: list[str], names: "Sequence[str]" = (), *,
                   menu: str = "title", key: str = "entries") -> str:
    """W66's empty-list form (G1 draft): an empty list, or one naming no button of the menu
    (``names``, as written), shows the defaults."""
    example = ", ".join(f'"{name}"' for name in registered)
    if names:
        listed = ", ".join(f'"{echo(name)}"' for name in names[:3])
        more = ", …" if len(names) > 3 else ""
        what = f"has no {MENU_NOUNS[menu]} ({listed}{more})"
    else:
        what = "is empty"
    return (f"config.toml: [{section}] {key} {what}, so the default buttons are shown: "
            f"{join_names(registered)}. List the buttons to show, e.g. "
            f"{key} = [{example}].")


__all__ = ["CONFIRM_KEYS", "STORY_AUDIO_FADE_S", "STORY_END_FADE_S", "AudioPort", "CueLayer",
           "GameShell", "Mode",
           "MusicHandle", "QuestionPort", "ShellPorts", "WarningPort", "reduce_motion_of", "w66_empty_text",
           "w66_text"]
