"""``install_minigames``: F23's host wired into one windowed launch (F23 ``04`` §2, §7.4,
§7.8; ``07`` I-8, I-11).

Why this module exists: ``minigames`` never imports ``app`` (ADR-0002), so the host gets the
App's pieces as ``HostPorts`` built here, once per launch, from ``install_story`` (after
``install_codex``, before ``install_settings_ui``):

- the router's ``StartMinigame`` handler (``MinigameHost.start``); plugin classes are looked
  up in the launch's registry (``app.minigames.get(name)``);
- ``post`` (the story driver), ``where`` (a statement's script file and line), ``fatal``
  (``App.show_fatal_error``), the guard (the launch's watchdog);
- the ledger's checks: F22's ``Points.spec`` and F21's ``CodexIndex`` (``entry_check``),
  read through the driver each call; F21's read marks and pictures for ``ctx.codex_view``;
- the shell (theme, words, assets, painter, notices, the confirm, ``set_thumbnail_source``),
  F08's audio, F14's limit cue, F15's ``stop_skip``, F05's textbox, F04's stage screen, F16's
  settings, ``App.focused``, and the viewport size;
- listeners: F14's landing listener, the textbox's say listener, the shell's in-game reset,
  the App's fatal hook (07 I-11), and F11's ``set_minigame_title_provider`` (the live
  registry's cleaned title; an unregistered name gives None);
- the plugin tables (04 §7.9): ``[theme.plugin]`` and ``[words.plugin]``, stored raw by
  ``config.py``, checked here against every registered minigame (``PluginTables.check``:
  bad values keep the default with config's text; unknown keys and names warn in dev);
- the game menu's ``skip_minigame`` entry (UI-F23-12), listed only over a running skippable
  minigame (``MinigameHost.can_skip``).

``engine.script`` is imported only for type checking (F23 ``04`` §2).
"""

import threading
from typing import TYPE_CHECKING

from engine.app.codex import AppCodexPort
from engine.minigames.context import PlayerSettings
from engine.minigames.host import HostPorts, MinigameHost
from engine.minigames.tables import PluginTables
from engine.runtime.commands import StartMinigame
from engine.runtime.images import ImageFile
from engine.runtime.minigame import entry_check
from engine.ui.menus import EntryContext, MenuEntry

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.images import ImageIndex
    from engine.runtime.interpreter import Interpreter


def _live(app: "App", interp: "Interpreter") -> "Interpreter":
    found = getattr(getattr(app, "story", None), "interp", None)
    return found if found is not None else interp


def statement_place(app: "App", interp: "Interpreter", sid: str) -> tuple[str | None, int | None]:
    """The script file and line of statement ``sid`` (E275–E277's prefix), or (None, None)."""
    program = getattr(_live(app, interp), "program", None)
    stmt = program.get(sid) if program is not None else None
    if stmt is None:
        return None, None
    return stmt.file.ref, stmt.line


def player_settings(app: "App") -> PlayerSettings:
    """What a plugin learns of F16's settings (PR-F23-19)."""
    shell = app.shell
    scale = shell.painter.text_scale() if shell is not None else 1.0
    reduce = bool(getattr(shell, "reduce_motion", False))
    settings = getattr(app, "settings", None)
    volumes = [100, 100, 100, 100]
    if settings is not None:
        for i, key in enumerate(("master_volume", "music_volume", "sound_volume",
                                 "voice_volume")):
            try:
                value = settings.value(key)
            except (KeyError, ValueError):
                continue
            if type(value) is int:
                volumes[i] = value
    return PlayerSettings(scale, reduce, *volumes)


def install_minigames(app: "App", interp: "Interpreter",
                      images: "ImageIndex | None" = None) -> MinigameHost | None:
    """Build the launch's ``MinigameHost`` and wire it (module docstring). None (nothing
    registered) without a shell (an App wired by hand)."""
    shell = app.shell
    if shell is None:
        return None
    registry = getattr(app, "minigames", None)
    pictures = AppCodexPort(lambda: _live(app, interp).codex, images,
                            show_locked=app.config.codex.show_locked)

    def lookup(name: str):
        return registry.get(name) if registry is not None else None

    def post(event: object) -> None:
        story = app.story
        if story is not None:
            story.post(event)

    def fatal(error: BaseException) -> None:
        app.show_fatal_error(error, already_logged=getattr(error, "logged", False) is True)

    def image(name: str):
        entry = images.get(name) if images is not None else None
        if isinstance(entry, ImageFile):
            return app.assets.image(entry.ref)
        return app.assets.image(name)

    def viewport() -> tuple[int, int] | None:
        view = app.viewport
        return None if view is None else (view.w, view.h)

    config = app.config
    tables = PluginTables(config.theme.plugin, config.words.plugin, shell.theme.cfg,
                          dev=bool(app.dev))
    if registry is not None:
        tables.check(registry.entries())

    rollback = getattr(app, "rollback_keys", None)
    skip_auto = getattr(app, "skip_auto", None)
    ports = HostPorts(
        shell=shell, lookup=lookup, post=post,
        where=lambda sid: statement_place(app, interp, sid), fatal=fatal,
        check_meter=lambda name: _live(app, interp).points.spec(name),
        check_entry=lambda name, kind: entry_check(_live(app, interp).codex.index)(name,
                                                                                    kind),
        index=lambda: _live(app, interp).codex.index, guard=interp.guard, image=image,
        is_read=lambda name: _live(app, interp).codex.is_read(name),
        mark_read=lambda name: _live(app, interp).codex.mark_read(name),
        picture=pictures.picture, show_locked=app.config.codex.show_locked,
        audio=getattr(app, "audio", None),
        cue=getattr(rollback, "cue", None),
        stop_skip=skip_auto.stop_skip if skip_auto is not None else None,
        textbox=app.textbox, stage=app.stage_screen,
        settings=lambda: player_settings(app), focused=lambda: bool(app.focused),
        viewport=viewport, tables=tables,
        main_thread=registry.main_thread if registry is not None else threading.get_ident())
    host = MinigameHost(ports)
    app.minigame_host = host
    app.router.register(StartMinigame, host.start)
    story = app.story
    add_landing = getattr(story, "add_landing_listener", None)
    if add_landing is not None:
        add_landing(host.on_landing)                      # F14: a back step abandons
    textbox = app.textbox
    if textbox is not None:
        textbox.add_say_listener(host.on_say)             # a Say while open abandons
    shell.add_in_game_reset(host.abandon)                 # load, New Game, the title
    shell.menus.add("game", MenuEntry("skip_minigame", action=lambda ctx: _ask_skip(host, ctx),
                                      visible=host.can_skip))
    add_fatal = getattr(app, "add_fatal_hook", None)
    if add_fatal is not None:
        add_fatal(host.abandon)                           # 07 I-11: before the error screen
    saves = getattr(app, "saves", None)
    if saves is not None and hasattr(saves, "set_minigame_title_provider"):
        def title(name: str) -> str | None:
            entry = lookup(name)
            return tables.look(entry).title if entry is not None else None
        saves.set_minigame_title_provider(title)
    return host


def _ask_skip(host: MinigameHost, ctx: EntryContext) -> None:
    host.ask_skip(ctx.by)


__all__ = ["install_minigames", "player_settings", "statement_place"]
