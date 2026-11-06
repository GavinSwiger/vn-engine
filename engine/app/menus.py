"""``install_ui``: F10's menus wired into one launch (F10 ``04`` §3.1, §7.10, §7.11; C9).

Why this module exists: ``ui`` never imports ``engine.app``, so the ``GameShell`` gets every
App-side thing it needs as injected ports (``ShellPorts``): the stack, the assets, the story
driver's ``new_game``, the in-game screens (``bootstrap.in_game_screens``, I-2's one list),
how to reset them, the App's quit, and F12's flush. This module builds those ports, resolves
the theme once (W64; W67 in dev runs, ``ui_contrast``; W65 for empty words), creates the
shell, registers F10's own entries (title: New Game, Quit; game menu: Return, Main Menu,
Quit; quick menu: Hide, Menu), adds the ``GameMenuKeys`` and ``QuickMenu`` overlays to the
in-game line screen (in that order), hands F07 the choice floor, registers the shell's quit
guard, sets ``app.shell``, and forwards the services' launch notices to it
(``forward_launch_notices``, F11 I-10). F33: the shell's ``content_warning`` port is a
``WarningGate`` over ``App.settings`` (read when asked) that start options skip, and W193
(dev) is checked here (``app/content_warning.py``).

``install_story`` calls it once per launch, after the presentation installs (F04's stage,
F05's textbox, F07's choices) and before the installs that register menu entries (F11, F13,
F15, F16); ``shell.check_entries()`` (W66, W68) is ``install_story``'s last line. A reload
(F39) keeps the shell.

The overlay host is F05's ``TextboxScreen`` (``_overlay_host``; ``install_textbox`` runs
first), and ``reset_in_game`` clears it.

F07 seams (C6–C8; whichever of F10 step 8 and the F07 build lands second wires them here):
``install_choices`` runs before ``install_ui`` and keeps its ``ChoiceController`` on
``app.choices``. ``install_ui`` then calls ``app.choices.set_floor(quick_menu.floor)`` (I-3:
the pill top − 4 while the quick menu can show, else 704), and ``reset_in_game`` calls
``app.choices.close()`` (I-8). ``ChoiceScreen`` reads ``textbox.hidden`` every frame (C8), so
the quick menu's Hide (``textbox.set_hidden(True)``) hides the choices too, and returns False
for unhandled presses, releases, and motion (C7), so they bubble to the textbox's overlays.
"""

from typing import TYPE_CHECKING

from engine.app.content_warning import WarningGate, check_fit
from engine.app.ui_contrast import warn_contrast
from engine.ui.builtin.game_menu import GameMenuKeys
from engine.ui.builtin.quick_menu import QuickMenu
from engine.ui.menus import EntryContext, MenuEntry
from engine.core.logsetup import get_logger
from engine.ui.shell import GameShell, ShellPorts
from engine.ui.textrouting import TextServices
from engine.core.kits import kit_words
from engine.ui.theme import resolve_theme, resolve_words

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.ui.builtin.textbox_screen import TextboxScreen
    from engine.ui.screen import Screen


def current_language(app: "App") -> str:
    """F52 (04 §4.4): the language the keyboard's pages follow: the player's chosen language
    (F43's setting), else ``"en"`` until F43's ``[language] source`` lands (the seam)."""
    settings = getattr(app, "settings", None)
    try:
        chosen = settings.value("language") if settings is not None else ""
    except (KeyError, AttributeError):
        chosen = ""
    return chosen if isinstance(chosen, str) and chosen else "en"


def text_services(app: "App") -> TextServices:
    """F52: the shell's ``TextServices``: the text input owner's clipboard read (none
    headless), the language, and dev warnings (W267) to log area ``ui``."""
    log = get_logger("ui")

    def read_clipboard() -> str:
        owner = getattr(app, "text_input", None)
        return owner.read_clipboard() if owner is not None else ""

    def warn(code: str, text: str) -> None:
        log.warning("%s", text, extra={"code": code})

    return TextServices(read_clipboard=read_clipboard, language=lambda: current_language(app),
                        warn=warn if app.dev else None)


def install_ui(app: "App") -> GameShell:
    """Build the shell for ``app`` (which must have a story), register F10's entries, the
    game-menu keys, and the quit guard, and set ``app.shell``."""
    story = app.story
    assert story is not None, "install_ui needs the story (install_story sets it first)"
    config = app.config
    assets = app.assets
    textbox = _overlay_host(app)
    theme = resolve_theme(config, assets, textbox_faces=textbox.faces)
    warn_contrast(theme, dev=app.dev)                # W67 (dev), after W64 resolved the frames
    words = resolve_words(config.words, kit=kit_words(config))     # F65: the kit's words
    start = app.start
    skip_title = start is not None and (start.label is not None or bool(start.values))
    check_fit(config, theme, words, assets, dev=app.dev)          # W193 (F33, dev)
    ports = ShellPorts(
        stack=app.screens, assets=assets, dev=app.dev, config=config,
        new_game=story.new_game,                                   # type: ignore[attr-defined]
        in_game_screens=lambda: _in_game_screens(app),
        reset_in_game=lambda: reset_in_game(app),
        request_quit=app.request_quit,
        audio=getattr(app, "audio", None),                         # F08's AudioService
        textbox=textbox,                                           # F05's TextboxScreen
        skip_title=skip_title,
        flush_persist=lambda: _flush_persist(app),
        content_warning=WarningGate(config.content_warning,         # F33 (I-1)
                                    lambda: getattr(app, "settings", None), skip=skip_title))
    shell = GameShell(ports, theme=theme, words=words)
    shell.text = text_services(app)                                 # F52
    shell.menus.add("title", MenuEntry("new_game", action=_new_game))
    shell.menus.add("title", MenuEntry("quit", action=_quit))
    shell.menus.add("game", MenuEntry("return", action=_return))
    shell.menus.add("game", MenuEntry("main_menu", action=_main_menu))
    shell.menus.add("game", MenuEntry("quit", action=_ask_quit))
    shell.menus.add("quick", MenuEntry("hide", action=_hide))
    shell.menus.add("quick", MenuEntry("menu", action=_open_menu))
    textbox.add_overlay(GameMenuKeys(shell))
    quick = QuickMenu(shell, textbox)
    textbox.add_overlay(quick)                       # after GameMenuKeys (04 §7.1)
    shell.quick_menu = quick
    _pass_floor(app, quick)
    app.add_quit_guard(shell.quit_guard)             # first: F11's guard is added after it
    app.shell = shell
    forward_launch_notices(app, shell)
    return shell


# F11 I-10: the services whose launch notices go to the notice layer, as (App attribute,
# ``[words]`` key of the one notice shown). F16's settings (I-13: W70, a settings file that
# couldn't be read); F12's persistent data (SEC-F12-12: W50–W52 from ``App.persist``).
NOTICE_SOURCES = (("settings", "notice_settings_default"),
                  ("persist", "notice_persistent"))


def forward_launch_notices(app: "App", shell: GameShell) -> None:
    """Drain each built service's ``take_notices()`` into ``shell.notify`` (F11 I-10). A
    service or word that doesn't exist yet is skipped, so F16's ``install_settings_ui`` may
    call this again (it drains once)."""
    for name, key in NOTICE_SOURCES:
        take = getattr(getattr(app, name, None), "take_notices", None)
        if take is not None:
            shell.forward_notices(take, key)


def _overlay_host(app: "App") -> "TextboxScreen":
    """The in-game screen that hosts F10's overlays (C5): F05's ``TextboxScreen``, one per
    launch (``install_textbox`` runs before ``install_ui``)."""
    textbox = getattr(app, "textbox", None)
    assert textbox is not None, "install_ui needs the textbox (install_textbox runs first)"
    return textbox


def _pass_floor(app: "App", quick: QuickMenu) -> None:
    """C6, I-3: F07's ``ChoiceController`` (``app.choices``, installed first) lays out its
    last-resort fit down to ``quick.floor()``. Nothing to do before F07 is built."""
    set_floor = getattr(getattr(app, "choices", None), "set_floor", None)
    if set_floor is not None:
        set_floor(quick.floor)


def _in_game_screens(app: "App") -> "list[Screen]":
    from engine.app import bootstrap          # lazily: loading.py never imports bootstrap

    return bootstrap.in_game_screens(app)


def reset_in_game(app: "App") -> None:
    """Before a new game and on the way back to the title (I-8): nothing of the last game
    may show: ``textbox.clear(hide=True)`` (F05); F07 closes its ``ChoiceScreen`` here
    (``ScreenStack.remove``); then ``textbox.set_hidden(False)``, so the next game never
    starts hidden (I-8). F15's resets run after this (``GameShell.add_in_game_reset``).
    F04: the stage shows the empty stage until the next game's first ``ShowStage``."""
    textbox = getattr(app, "textbox", None)
    if textbox is not None:
        textbox.clear(hide=True)
    close_choices = getattr(getattr(app, "choices", None), "close", None)
    if close_choices is not None:
        close_choices()                              # F07: ScreenStack.remove(ChoiceScreen)
    if textbox is not None:
        textbox.set_hidden(False)
    stage = getattr(app, "stage_screen", None)
    if stage is not None:
        stage.clear()


def _flush_persist(app: "App") -> None:
    """F12 I-1: persistent data is written soon before the title or a quit (no
    ``App.persist`` before F12)."""
    persist = getattr(app, "persist", None)
    if persist is not None:
        persist.flush_soon()


def _new_game(ctx: EntryContext) -> None:
    ctx.shell.start_new_game()


def _quit(ctx: EntryContext) -> None:
    ctx.shell.ports.request_quit()                  # the title: the guard lets it through


def _return(ctx: EntryContext) -> None:
    ctx.shell.close_game_menu()


def _main_menu(ctx: EntryContext) -> None:
    ctx.shell.ask_main_menu(ctx.by)


def _ask_quit(ctx: EntryContext) -> None:
    ctx.shell.ask_quit(ctx.by)


def _hide(ctx: EntryContext) -> None:
    """The quick menu's Hide: hidden mode, as H (C8: F07's choices hide with the box)."""
    textbox = ctx.shell.ports.textbox
    if textbox is not None:
        textbox.set_hidden(True)                     # type: ignore[attr-defined]


def _open_menu(ctx: EntryContext) -> None:
    ctx.shell.open_game_menu(ctx.by)


__all__ = ["NOTICE_SOURCES", "forward_launch_notices", "install_ui", "reset_in_game"]
