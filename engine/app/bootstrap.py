"""The startup sequence (§7.1): logging, game folder, config, log folder, then the App.

Why this module exists: startup order matters for privacy and for the author's first
experience. Logging begins in memory before anything else, the log folder is chosen only
after ``config.toml`` has named the game's ``[game] id`` (ADR-0003 §4), and every exit path
ends with the log opened and ``Clean shutdown (exit code N)`` as its last line. One code
path serves dev and release runs; only the log location rule differs.

A session whose startup failed (missing game folder, config errors) still opens the window
and runs the loop on the ``ErrorScreen``; only a window that cannot be created ends with
the system dialog (``show_native_error``, the only ``message_box`` caller).
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from engine import __version__
from engine.app.app import App
from engine.app.settings import (SettingsLaunch, install_settings, launch_settings,
                                 launch_value)
from engine.core import logsetup
from engine.core.config import load_config
from engine.core.config_schema import Config
from engine.core.constants import CANVAS_SIZE, ERROR_MESSAGE_MAX_CHARS, LOGS_DIRNAME, MB
from engine.core.errors import ConfigErrorGroup, UserFacingError
from engine.core.geometry import initial_window_size
from engine.core.logsetup import LogDirCandidate, LogSetup, get_logger, lifecycle
from engine.core.paths import GamePaths, engine_root, slugify, user_log_dir
from engine.core.redact import echo, escape_controls, redact, truncate
from engine.core.timing import GameTime

if TYPE_CHECKING:
    from engine.core.startvalues import StartOptions


def launch(game_dir: Path, *, release: bool, bench_seconds: float | None,
           log_level_override: str | None, pygame_warning: str | None,
           start: "StartOptions | None" = None, editor_report: bool = False,
           seed: int | None = None, no_persistent: bool = False, resume: bool = False,
           window_at: tuple[int, int] | None = None,
           try_lines: Sequence[str] | None = None) -> int:
    """Run one session of the game in ``game_dir``; return the process exit code.

    F44: ``start`` holds ``run --start``/``--set`` (``App.start``); ``editor_report``
    (``--report-to-editor``) gives the App an ``EditorLink`` on this process's stdout.
    F03 step 13: ``seed`` is ``run --seed`` (``App.seed``), the seed of every new game.
    F12: ``no_persistent`` is ``run --no-persistent`` (``App.no_persistent``).
    F39 (dev runs only): with ``editor_report`` the link also reads Studio's messages on
    stdin; ``resume`` (``--resume-from-editor``) makes the first screen after the load F39's
    ``ResumeScreen``; ``window_at`` (``--window-at=X,Y``) opens the window there.
    F47 P2-F: ``try_lines`` (``--try-stdin``) makes it Studio's Try it run
    (``app/trystory.py``): no log file, no settings read, a small window, the label's
    lines played from the start, persistent data in memory, and nothing written."""
    log = logsetup.begin(level=log_level_override or "info", engine_root=engine_root())
    app_log = get_logger("app")
    state = _Startup(game_dir, release=release)
    state.try_lines = tuple(try_lines) if try_lines is not None else None
    code = 0
    interrupted = False
    try:
        try:
            # Step 6: header line 1 and the pygame-ce >= 2.6 warning (memory only).
            lifecycle(app_log, _header_build_line(release))
            if pygame_warning is not None:
                app_log.warning(pygame_warning)
            # Step 7: the game folder.
            try:
                state.paths = GamePaths.for_game(game_dir)
                log.add_game_root(state.paths.root, as_given=game_dir)
            except UserFacingError as error:
                state.fatal = error
                app_log.error("%s", error.format())
            # Step 8: config.
            config = Config()
            if state.paths is not None:
                result = load_config(state.paths)
                config = result.config
                state.config_loaded = result.loaded
                config_log = get_logger("config")
                for warning in result.warnings:
                    config_log.warning("%s", warning)
                for error in result.errors:
                    config_log.error("%s", error.format())
                if result.errors:
                    state.fatal = ConfigErrorGroup(result.errors)
                if log_level_override is None:
                    log.set_level(config.engine.log_level)
            state.config = config
            # Steps 9–10: app id and the log file.
            _open_log(log, state)
            # Step 10b (F16): the player's settings, before the window size is chosen.
            state.settings = _read_settings(state)
            # Steps 11–17: pygame, the window, assets, the App.
            code = _run_session(state, log, release=release, bench_seconds=bench_seconds,
                                start=start, editor_report=editor_report, seed=seed,
                                no_persistent=no_persistent, resume=resume,
                                window_at=window_at)
        except KeyboardInterrupt:
            interrupted = True
            code = 0
        except Exception:
            app_log.exception("Startup failed because of an error inside the engine")
            code = 1
    finally:
        _close_window(state)
        # Step 18: the log always opens, so a release log receives buffered errors too.
        try:
            if log.session is None:
                _open_log(log, state)
        except Exception:
            app_log.debug("Could not open the log file during cleanup", exc_info=True)
        if interrupted:
            # Logged after the cleanup opened the log, so the last two lines are always
            # the interruption and the shutdown (PR-F01-35).
            lifecycle(app_log, "Interrupted from the terminal (Ctrl+C)")
        lifecycle(app_log, "Clean shutdown (exit code %d)", code)
        log.close()
    return code


class _Startup:
    """What the startup sequence has learned so far (for the cleanup path)."""

    def __init__(self, game_dir: Path, *, release: bool) -> None:
        self.game_dir = game_dir
        self.release = release
        self.paths: GamePaths | None = None
        self.config: Config = Config()
        self.config_loaded = False
        self.fatal: BaseException | None = None
        self.window = None                 # GameWindow once created (step 13)
        self.pygame_started = False
        self.settings: SettingsLaunch | None = None     # F16 step 10b
        self.try_lines: tuple[str, ...] | None = None   # F47 P2-F: --try-stdin's lines


def _read_settings(state: _Startup) -> SettingsLaunch:
    """F16 step 10b (``04`` §7.1): skipped after a fatal startup error or without a game
    folder; a release run with a fallback id is W74 with no file call."""
    app_id, fallback = choose_app_id(state)
    return launch_settings(game_root=state.paths.root if state.paths is not None else None,
                           release=state.release, app_id=app_id, id_is_fallback=fallback,
                           skip=state.fatal is not None or state.paths is None
                           or state.try_lines is not None)      # F47 P2-F: defaults


def choose_app_id(state: "_Startup") -> tuple[str, bool]:
    """§7.1 step 9: ``[game] id`` if the config loaded and set it, else the slug of the
    game folder's name. Returns ``(app_id, id_is_fallback)``. A fallback id is only ever
    passed to ``user_log_dir`` (SEC-F01-16 (d), SEC-F01-23 (d))."""
    configured = state.config.game.id
    if state.config_loaded and configured is not None:
        return configured, False
    name = state.paths.root.name if state.paths is not None else state.game_dir.name
    return slugify(name), True


def log_candidates(paths: GamePaths | None, app_id: str, *,
                   release: bool) -> list[LogDirCandidate]:
    """§7.1 step 10: dev runs try ``<game>/logs`` first, release runs the per-user folder
    first; each falls back to the other (ADR-0003 §6)."""
    user = [LogDirCandidate(user_log_dir(app_id), "user")]
    game = [] if paths is None else [LogDirCandidate(paths.root / LOGS_DIRNAME, "game")]
    return user + game if release else game + user


def _open_log(log: LogSetup, state: _Startup) -> None:
    app_id, fallback = choose_app_id(state)
    # F47 P2-F: a Try it run opens no log file (console only), so it writes nothing.
    candidates = ([] if state.try_lines is not None else
                  log_candidates(state.paths, app_id, release=state.release))
    session = log.open_file(candidates)
    lifecycle(get_logger("app"), logsetup.header_log_line(session, fallback_id=fallback))


def _header_build_line(release: bool) -> str:
    pygame_version, sdl_version = _pygame_versions()
    return logsetup.header_build_line(
        engine_version=__version__, pygame_version=pygame_version, sdl_version=sdl_version,
        os_description=_os_description(), release=release)


def _pygame_versions() -> tuple[str, str]:
    """pygame-ce and SDL versions as ``x.y.z`` (``unknown`` if pygame cannot tell)."""
    pygame = sys.modules.get("pygame")
    if pygame is None:
        try:
            import pygame                                   # noqa: F811
        except ImportError:
            return "unknown", "unknown"
    try:
        version = str(pygame.version.ver)
    except AttributeError:
        version = ".".join(str(part) for part in getattr(pygame, "vernum", ())[:3]) \
            or "unknown"
    try:
        sdl = ".".join(str(part) for part in pygame.get_sdl_version())
    except (AttributeError, TypeError):
        sdl = "unknown"
    return version, sdl


def _os_description() -> str:
    from engine.app import platform as osinfo
    return osinfo.os_description()


# --- Steps 11–17: pygame, the window, assets, the App ------------------------------------

NATIVE_WAYLAND_NOTE = ("Native Wayland session: window centering and position restore are "
                       "not supported (PR-F01-63)")


def approx_usable(desktop: tuple[int, int]) -> tuple[int, int]:
    """Estimated usable area where the OS cannot report a work area (§7.1 step 12)."""
    return desktop[0], max(1, desktop[1] - 80)


def _run_session(state: _Startup, log: LogSetup, *, release: bool,
                 bench_seconds: float | None, start: "StartOptions | None" = None,
                 editor_report: bool = False, seed: int | None = None,
                 no_persistent: bool = False, resume: bool = False,
                 window_at: tuple[int, int] | None = None) -> int:
    import pygame

    from engine.app import platform as osinfo
    from engine.render.assets import DEFAULT, AssetManager
    from engine.render.window import GameWindow, WindowCreationError

    app_log = get_logger("app")
    config = state.config
    # Step 11: pygame and header line 3.
    pygame.init()
    state.pygame_started = True
    driver = pygame.display.get_driver()
    lifecycle(app_log, _displays_line(driver, osinfo.displays_info()))
    if driver == "wayland":
        app_log.info(NATIVE_WAYLAND_NOTE)
    # Step 12: window size (F16: the player's stored size, else the config size).
    settings = state.settings if state.settings is not None else SettingsLaunch.skipped()
    requested = launch_value(settings.loaded, config, "window_size")
    scale = osinfo.system_display_scale()
    work = osinfo.primary_work_area()
    if work is not None:
        usable, source = work, "work area"
    else:
        usable, source = approx_usable(tuple(pygame.display.get_desktop_sizes()[0])), "estimated"
    trying = state.try_lines is not None
    if trying:                                  # F47 P2-F: a small window, never fullscreen
        from engine.app.trystory import try_size

        requested = try_size(requested)
    size = initial_window_size(requested, scale, usable)
    # Step 13: the window, in the player's stored mode (F16), else the config's.
    try:
        window = GameWindow(title=_window_title(config.game.title, trying), size=size,
                            resizable=config.window.resizable,
                            start_fullscreen=not trying and bool(
                                launch_value(settings.loaded, config, "fullscreen")),
                            letterbox_color=config.window.letterbox_color,
                            initial_size_for_restore=size,
                            position=window_at)              # F39: the old preview's spot
    except WindowCreationError as error:
        get_logger("window").exception("The game window could not be created")
        message = str(error)
        if sys.stderr is not None:
            try:
                print(redact(message), file=sys.stderr)
            except Exception:
                pass
        show_native_error(f"{config.game.title} could not start", message)
        return 1
    state.window = window
    # Step 14: assets; the default font file is pinned for the whole session.
    game_time = GameTime()
    assets = AssetManager(state.paths, budget_bytes=config.engine.cache_mb * MB,
                          scale_filter=config.window.scale_filter, time=game_time,
                          format_source=window.framebuffer)
    assets.font(None, 28)
    assets.cache.hold(("fontfile", DEFAULT))
    # Step 15: the icon (unconverted; no display format needed).
    window.set_icon(assets.icon_surface(config.window.icon))
    # Step 16: header lines 4 and 5.
    framebuffer = window.framebuffer()
    fb_size = framebuffer.get_size() if framebuffer is not None else (0, 0)
    lifecycle(app_log, window_header_line(window.size, window.fullscreen, fb_size, requested,
                                          scale, usable, source))
    lifecycle(app_log, game_header_line(config))
    # Step 17: the App. The story loads inside the frame loop (F02 §7.9); the load screen
    # shows build_initial_screens(app) when it is done (I-2: this module never imports
    # engine.script).
    link = _editor_link() if editor_report else None
    app = App(config=config, paths=state.paths, window=window, assets=assets, log=log,
              dev=not release, bench_seconds=bench_seconds, start=start, seed=seed,
              no_persistent=no_persistent or trying, editor_link=link)
    app.try_run = trying
    if link is not None:                      # F39: Studio's messages; the failed place
        if not trying:                        # a try run's stdin held its lines
            link.listen(_editor_input(), resume=resume)
        app.add_fatal_hook(lambda: link.fatal_hook(app))
    # F16: ``App.settings`` (the window size is stored at quit in requested units).
    install_settings(app, settings, display_scale=scale,
                     game_root=state.paths.root if state.paths is not None else None,
                     release=release)
    if state.fatal is None:
        open_audio(app, state.paths)
        if app.settings is not None:          # F16: the player's volumes before any sound
            app.settings.attach_audio(app.audio)
    if state.fatal is not None:
        app.show_fatal_error(state.fatal, already_logged=True)
    elif state.paths is None:
        app.screens.replace_all(build_initial_screens(app))
    else:
        from engine.app.loading import story_load_screen

        ready = resume_screens if resume and link is not None else build_initial_screens
        paths = state.paths
        if state.try_lines is not None:       # F47 P2-F: the label rides on main.vns
            from engine.app.trystory import TryPaths, try_screens

            paths, ready = TryPaths.over(paths, state.try_lines), try_screens
        app.screens.replace_all([story_load_screen(app, paths, on_ready=ready)])
    return app.run()


def _window_title(title: str, trying: bool) -> str:
    """The game's title; a Try it run's says so (F47 P2-F)."""
    if not trying:
        return title
    from engine.app.trystory import WINDOW_TITLE

    return WINDOW_TITLE.format(title=title)


def open_audio(app: App, paths: GamePaths | None) -> None:
    """F08 (§7.10, I-4, I-8): ``App.audio``, built once before any story (F10's title
    music), on the shared asset cache, the App's clock, and ``GameTime.frame``. The device
    is opened here (``open_backend``: ``NullMixer`` and one W30 without one); the service
    closes it in a shutdown hook. Imported here, so startup never imports ``engine.script``
    before the story load (I-2)."""
    from engine.audio import backend as audio_backend
    from engine.audio.service import AudioService

    game_time = app.time
    audio = AudioService(paths, app.assets.cache, app.config.audio,
                         backend=audio_backend.open_backend(), clock=app.clock,
                         frame=lambda: game_time.frame)
    app.audio = audio
    app.add_shutdown(audio.shutdown)


def _editor_link():
    """F44: the report channel on this process's stdout (None when there is no stdout)."""
    from engine.app.editor_link import EditorLink

    return EditorLink(getattr(sys.stdout, "buffer", None))


def _editor_input():
    """F39: Studio's messages arrive on this process's stdin (None when there is none).

    Read through an unbuffered file object of its own that never closes the descriptor,
    not ``sys.stdin.buffer``: the reader thread waits inside a read, and a daemon thread
    holding ``sys.stdin.buffer``'s lock makes the interpreter abort at exit ("could not
    acquire lock ... at interpreter shutdown"), which would turn a clean quit into a
    crash."""
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):      # no stdin, or not a real file
        return None
    try:
        return open(fd, "rb", buffering=0, closefd=False)   # noqa: SIM115
    except OSError:
        return None


def resume_screens(app: App) -> list:
    """F39 (§5.1 step 5): ``--resume-from-editor``'s ``on_ready``. With a story, F39's
    ``ResumeScreen`` waits for Studio's frame and resumes the carried place through
    ``GameShell.enter_game`` (no title, no F33 warning), else starts normally
    (``build_initial_screens``) with N1, N3 or N4. Without a story: ``build_initial_screens``.
    F44's ``started`` follows as usual."""
    link = app.editor_link
    shell = app.shell
    if app.story is None or shell is None or link is None:
        return build_initial_screens(app)
    from engine.app.hot_reload import ResumePorts, ResumeScreen

    ports = ResumePorts(
        take_frame=link.take_frame,
        driver=lambda: app.story,
        enter_game=shell.enter_game,
        start_normally=lambda: app.screens.replace_all(build_initial_screens(app)),
        notify=lambda text, kind: shell.notify(text, kind=kind),       # type: ignore[arg-type]
        show_fatal_error=app.show_fatal_error,
        keep=link.keep)
    return [ResumeScreen(ports)]


def in_game_screens(app: App) -> list:
    """The in-game screens of one game, bottom first (F10 I-2: the one list, used by
    ``build_initial_screens`` through the shell and by ``ShellPorts.in_game_screens`` on
    every New Game): ``[StageScreen, TextboxScreen]`` (F05 C2 e), the launch's one of each,
    built by ``install_stage`` and ``install_textbox`` (absent when no story was installed).
    The textbox hosts F10's overlays (C5), so they stay with it across New Games. F17
    changes this list too."""
    stage = getattr(app, "stage_screen", None)
    textbox = getattr(app, "textbox", None)
    return [screen for screen in (stage, textbox) if screen is not None]


def build_initial_screens(app: App) -> list:
    """What shows once the story is ready. With a story (``app.story``, set by
    ``install_story``), F10's shell decides (``initial_screens``: the title, or the first
    game at once with start options or ``[title] enabled = false``); without F10's shell
    the first game starts on ``in_game_screens``. No story (W01) or no game folder: F01's
    placeholder. F33 inserts its content warning through the shell."""
    if app.story is not None:
        if app.shell is not None:
            return app.shell.initial_screens()
        app.story.new_game()                    # type: ignore[attr-defined]
        return in_game_screens(app)
    from engine.ui.builtin.placeholder import PlaceholderScreen

    return [PlaceholderScreen(title=app.config.game.title, engine_version=__version__)]


def show_native_error(title: str, text: str) -> None:
    """The only pygame.display.message_box call. Redacts and escapes both strings, cuts
    text to ERROR_MESSAGE_MAX_CHARS, swallows every exception. Never exposed to screens
    or scripts (security §9)."""
    try:
        import pygame

        safe_title = echo(title)
        safe_text = truncate(escape_controls(redact(text), allow_newline=True),
                             ERROR_MESSAGE_MAX_CHARS)
        pygame.display.message_box(safe_title, safe_text, message_type="error")
    except Exception:
        get_logger("app").debug("The system error dialog could not be shown", exc_info=True)


def _displays_line(driver: str, displays: list[str]) -> str:
    listed = ", ".join(f"{index}: {entry}" for index, entry in enumerate(displays, 1))
    return f"Displays (video driver {driver}): {listed or 'none'}"


def window_header_line(window_size: tuple[int, int], fullscreen: bool,
                       framebuffer: tuple[int, int], requested: tuple[int, int],
                       scale: float, usable: tuple[int, int], source: str) -> str:
    """Header line 4 (§7.10.8)."""
    mode = "fullscreen" if fullscreen else "windowed"
    return (f"Window: {window_size[0]}x{window_size[1]} {mode} | "
            f"framebuffer {framebuffer[0]}x{framebuffer[1]} px | "
            f"requested {requested[0]}x{requested[1]} | display scale {round(scale, 4)} | "
            f"usable area {usable[0]}x{usable[1]} ({source})")


def game_header_line(config: Config) -> str:
    """Header line 5 (§7.10.8); title and version are echoed (≤ 120 characters)."""
    return (f'Game: "{echo(config.game.title)}" {echo(config.game.version)} | '
            f"canvas {CANVAS_SIZE[0]}x{CANVAS_SIZE[1]} | render: device resolution | "
            f"cache {config.engine.cache_mb} MB | fps cap {config.engine.fps}")


def _close_window(state: _Startup) -> None:
    """Step 18: destroy the window and stop pygame, whatever happened."""
    try:
        if state.window is not None:
            state.window.destroy()
        if state.pygame_started:
            import pygame
            pygame.quit()
    except Exception:
        get_logger("app").debug("Could not close the window cleanly", exc_info=True)
    state.window = None
    state.pygame_started = False
