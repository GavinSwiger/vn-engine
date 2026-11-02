"""In-process ``launch()`` sessions that end on the error screen (§7.1 step 17, §7.12).

AC-F01-12, 13, 14, 15 (launch parts), 23 (icon fallbacks: never the error screen), 62
(Ctrl+C in a screen), 71 (in-process part), 72 (privacy on every channel), 74 (the error
screen part), 76, 77, 78, 80 (last log line), 81, 82, 110, 124, 132, 134 (launch parts),
137, 143, 148, 150, 151, 153 (the AC-F01-72 (b) copy).

``pygame.Window`` is a ``SpyWindow`` (never shown), each App runs scripted frames on a fake
clock, ``message_box`` is a recorder (``tests/conftest.py``), and every per-user folder is
under ``tmp_path`` (``user_roots``).
"""

import builtins
import hashlib
import io
import logging
import os
import re
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.core.config import load_config
from engine.core.errors import UserFacingError
from engine.core.paths import GamePaths, engine_data_dir, user_data_dir, user_log_dir
from engine.render.window import GameWindow, WindowCreationError
from engine.ui.builtin.error import ErrorScreen
from engine.ui.screen import Screen
from tests.fakes.loop import post_key
from tests.fakes.privacy import capture_channels, check_p
from tests.fakes.spy_window import SpyWindow
from tests.fixtures.F01 import config_fixtures

pytestmark = pytest.mark.display

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "F01"
CONFIG = FIXTURES / "config"
REPO = Path(__file__).resolve().parent.parent.parent
NOT_AVAILABLE = "not available (the log folder could not be written)"
UNUSABLE = ("The logs folder in the game folder is a link or not a folder — using another "
            "log location")
FALLBACK = " (fallback folder: [game] id is not set)"
LINE_FORMAT = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} (DEBUG|INFO|WARNING|ERROR)\s+[a-z]{1,7}\s+.+$")
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")
ENGINE_ERROR = ("Something went wrong inside the engine (RuntimeError: boom). "
                "The log file has the details.")


@pytest.fixture(autouse=True)
def session(scripted_app):
    scripted_app.quit_frame = 4
    return scripted_app


@pytest.fixture
def channels(monkeypatch):
    with capture_channels(monkeypatch) as found:
        yield found


def launch(game_dir: Path, *, release: bool = False, log_level: str | None = None) -> int:
    return bootstrap.launch(game_dir, release=release, bench_seconds=None,
                            log_level_override=log_level, pygame_warning=None)


def make_game(parent: Path, config: str | bytes | None = "", name: str = "game") -> Path:
    root = parent / name
    root.mkdir(parents=True)
    if config is not None:
        data = config.encode("utf-8") if isinstance(config, str) else config
        (root / "config.toml").write_bytes(data)
    return root


def copy_fixture_game(name: str, dest: Path) -> Path:
    shutil.copytree(FIXTURES / "games" / name, dest, ignore=shutil.ignore_patterns("logs"))
    return dest


# F02 adds one WARNING to every launch of a game folder without a story (PR-F02-06). These
# F01 games have none, so the F01 checks leave that one record out (F02 07 §6 (a)).
W01 = ("WARNING", "script", "No story found: script/main.vns doesn't exist.")


def records(log_file: Path) -> list[tuple[str, str, str]]:
    """(level, area, message) of each timestamped line, except F02's W01."""
    out = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if TIMESTAMP.match(line):
            record = (line[24:31].strip(), line[32:39].strip(), line[40:])
            if record != W01:
                out.append(record)
    return out


def messages(log_file: Path) -> list[str]:
    return [message for _, _, message in records(log_file)]


def error_screen(session) -> ErrorScreen:
    screen = session.apps[-1].screens.top
    assert isinstance(screen, ErrorScreen), screen
    return screen


class Raiser(Screen):
    """Raises ``error`` in ``update`` (or ``draw``) the first time it runs."""

    opaque = False

    def __init__(self, error: BaseException, where: str = "update") -> None:
        self.error = error
        self.where = where

    def update(self, dt, *, is_top):
        if self.where == "update":
            raise self.error

    def draw(self, canvas):
        if self.where == "draw":
            raise self.error


def raise_at(session, frame: int, error: BaseException, where: str = "update") -> None:
    session.at(frame, lambda app: app.screens.push(Raiser(error, where)))


def press_at(session, frame: int, key: int) -> None:
    session.at(frame, lambda app: post_key(key))


def screen_texts(channels) -> list[str]:
    return [c.text for c in channels.draws]


def vn_engine_dir() -> Path:
    log_dir = user_log_dir("probe")
    return next(p for p in log_dir.parents if p.name == "vn-engine")


def header_log_path(log_file: Path) -> str:
    line = next(m for m in messages(log_file) if m.startswith("Log: "))
    return line[len("Log: "):].removesuffix(FALLBACK)


# --- AC-F01-12, 13, 14, 15: config errors on the error screen ----------------------------------------

def test_bad_value_stops_on_the_error_screen(tmp_path, user_roots, session, channels, capsys):
    game = make_game(tmp_path, (CONFIG / "walkthrough_step3.toml").read_bytes())
    state = {}
    session.at(1, lambda app: state.update(error_mode=app.error_mode, title=app.window.title))
    press_at(session, 2, pygame.K_ESCAPE)
    session.quit_frame = 50
    assert launch(game) == 1
    assert session.limiters[-1].frame == 2
    expected = ('config.toml, line 8: [window] width must be a whole number from 640 to 7680, '
                'but found the text "1920". Remove the quotes.')
    assert state == {"error_mode": True, "title": "Paper Lanterns"}
    assert error_screen(session).message == expected
    log_file = game / "logs" / "latest.log"
    assert ("ERROR", "config", expected) in records(log_file)
    assert "Traceback" not in log_file.read_text(encoding="utf-8")
    assert "Traceback" not in capsys.readouterr().err
    # AC-F01-14: the valid part of the config is used.
    assert '"Paper Lanterns" version 0.1.0' in screen_texts(channels)
    assert messages(log_file)[-1] == "Clean shutdown (exit code 1)"


def test_all_config_errors_are_on_the_screen_and_logged_separately(tmp_path, user_roots,
                                                                   session):
    game = make_game(tmp_path, (CONFIG / "type_errors.toml").read_bytes())
    errors = load_config(GamePaths.for_game(game)).errors
    assert [e.line for e in errors] == [5, 6, 7, 8, 10]
    assert launch(game) == 1
    assert error_screen(session).message == "\n\n".join(e.format() for e in errors)
    logged = [r for r in records(game / "logs" / "latest.log") if r[0] == "ERROR"]
    assert [m for _, _, m in logged] == [e.format() for e in errors]
    text = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    for error in errors:
        assert error.format() + "\n" in text


def test_syntax_error_on_the_screen_without_a_traceback(tmp_path, user_roots, session, capsys):
    game = make_game(tmp_path, (CONFIG / "syntax_invalid_value.toml").read_bytes())
    assert launch(game) == 1
    assert error_screen(session).message == (
        'config.toml, line 4, column 9: expected a value after "=". '
        'Text values need quotes: title = "My Game"')
    assert "Traceback" not in capsys.readouterr().err
    assert "Traceback" not in (game / "logs" / "latest.log").read_text(encoding="utf-8")


# --- AC-F01-23: icon problems fall back to the engine icon ----------------------------------------------

# One row per path through the launch: not a PNG, a blocked ref, a file that cannot be used,
# a case miss. Every row of the AC-F01-23 table is checked without a launch in
# test_assets.py::test_icon_problems_use_the_engine_icon; ../x.png and the AC-F01-139 refs
# are launched in test_launch_window.py.
ICON_ROWS = [
    ("gui/icon.jpg", "WARNING", 'Window icon "gui/icon.jpg" must be a PNG file — using the engine icon'),
    ("gui/con.png", "ERROR", 'Asset path "gui/con.png" is not allowed: "con" is a reserved file '
                             "name on Windows — using the engine icon"),
    ("gui/corrupt.png", "WARNING", None),
    ("gui/Lantern.png", "WARNING", None),
]


@pytest.mark.parametrize("ref, level, text", ICON_ROWS)
def test_icon_fallbacks(tmp_path, user_roots, session, monkeypatch, ref, level, text):
    game = copy_fixture_game("assets", tmp_path / "game")
    (game / "config.toml").write_text(f'[window]\nicon = "{ref}"\n', encoding="utf-8")
    icons = []
    real = GameWindow.set_icon
    monkeypatch.setattr(GameWindow, "set_icon",
                        lambda self, surface: icons.append(pygame.image.tobytes(surface, "RGBA"))
                        or real(self, surface))
    reads = []
    real_read = GamePaths.read_file
    monkeypatch.setattr(GamePaths, "read_file", lambda self, r, *, max_bytes: reads.append(r)
                        or real_read(self, r, max_bytes=max_bytes))
    assert launch(game) == 0
    assert session.apps[-1].error_mode is False
    pygame.init()
    engine_icon = pygame.image.tobytes(pygame.image.load(str(engine_data_dir() / "icon.png")),
                                       "RGBA")
    pygame.quit()
    assert icons == [engine_icon]
    lines = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert len(lines) == 1 and lines[0][0] == level
    message = lines[0][2]
    if text is not None:
        assert message == text
        assert reads == ["config.toml"]
    else:
        assert message.startswith(f"Window icon {ref if ref != 'gui/Lantern.png' else ref} "
                                  "could not be used (")
        assert message.endswith(") — using the engine icon")
        if ref == "gui/Lantern.png":
            assert "gui/lantern.png" in message
        expected_reads = ["config.toml", "gui/corrupt.png"] if ref == "gui/corrupt.png" \
            else ["config.toml", ref]
        assert reads == expected_reads


@pytest.mark.parametrize("value", ["5", "true"])
def test_non_text_icon_is_a_config_error(tmp_path, user_roots, session, value):
    game = make_game(tmp_path, f"[window]\nicon = {value}\n")
    assert launch(game) == 1
    assert "[window] icon" in error_screen(session).message


# --- AC-F01-62 / 71: Ctrl+C in a screen; no stderr -------------------------------------------------------

def test_ctrl_c_in_a_screen_shuts_down_cleanly(tmp_path, user_roots, session, capsys):
    game = make_game(tmp_path)
    raise_at(session, 5, KeyboardInterrupt())
    session.quit_frame = 50
    assert launch(game, log_level="error") == 0
    lines = messages(game / "logs" / "latest.log")
    assert lines[-2:] == ["Interrupted from the terminal (Ctrl+C)", "Clean shutdown (exit code 0)"]
    assert "Traceback" not in capsys.readouterr().err


def test_no_stderr_means_no_console_handler(tmp_path, user_roots, session, monkeypatch):
    game = make_game(tmp_path, "[zzz]\n")
    monkeypatch.setattr(sys, "stderr", None)
    seen = {}
    session.at(2, lambda app: seen.update(
        handlers=[type(h) for h in logging.getLogger("vn").handlers]))
    raise_at(session, 2, RuntimeError("boom"))
    assert launch(game) == 1
    assert not [h for h in seen["handlers"] if issubclass(h, logging.StreamHandler)]


# --- AC-F01-72 / 153: privacy on every channel -------------------------------------------------------

def _privacy_session(tmp_path, user_roots, session, channels, capsys, error, *,
                     release=False, setup=None):
    game = make_game(user_roots.home, '[game]\ntitle = "My Game"\n', name="My Game")
    if setup is not None:
        setup(game)
    home = user_roots.home

    def content_problems(app):
        app.assets.image("images/missing.png")
        app.assets.font("fonts/missing.ttf", 20)

    session.at(2, content_problems)
    raise_at(session, 3, error)
    press_at(session, 5, pygame.K_c)
    session.quit_frame = 7
    assert launch(game, release=release) == 1
    assert len(channels.clipboard) == 1
    logs = [p for p in tmp_path.rglob("*.log")]
    texts = channels.texts() + [capsys.readouterr().err]
    texts += [p.read_text(encoding="utf-8", errors="replace") for p in logs]
    check_p(texts, home=home, game=game)
    return game, logs


def _absolute_traceback_error():
    def inner():
        raise RuntimeError("boom")
    try:
        inner()
    except RuntimeError as error:
        return error


@pytest.mark.parametrize("case", ["a", "b", "c", "d"])
def test_privacy_check_p_on_every_channel(tmp_path, user_roots, session, channels, capsys,
                                          monkeypatch, message_boxes, case):
    home = user_roots.home
    setup = None
    release = False
    if case == "a":
        error = _absolute_traceback_error()                  # the traceback has absolute paths
    elif case == "b":
        error = PermissionError(13, "Permission denied", str(home / "x.png"))
    elif case == "c":
        prefix = tmp_path / "qauser7" / "venv"
        monkeypatch.setattr(sys, "prefix", str(prefix))
        error = RuntimeError(f"failed in {prefix / 'lib' / 'x.py'}")
    else:
        profiles = tmp_path / "profiles" / "qauser7" / "AppData"
        monkeypatch.setenv("APPDATA", str(profiles / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(profiles / "Local"))
        error = RuntimeError("boom")
        local = profiles / "Local"
        real_mkdir = Path.mkdir

        def mkdir(self, *args, **kwargs):
            if str(self).startswith(str(local)):
                raise PermissionError(13, "Permission denied", str(self))
            return real_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mkdir)

        def setup(game):
            (game / "logs").write_text("not a folder", encoding="utf-8")
    game, logs = _privacy_session(tmp_path, user_roots, session, channels, capsys, error,
                                  release=release, setup=setup)
    if case != "d":
        assert logs, "a log file was written"
    # The same identity in a run whose window cannot be created.
    shutil.rmtree(game)
    game = make_game(home, '[game]\ntitle = "My Game"\n', name="My Game")

    def no_window(**kwargs):
        raise WindowCreationError(f"The game window could not be created: {home / 'dev'}")

    monkeypatch.setattr("engine.render.window.GameWindow", no_window)
    assert launch(game) == 1
    assert len(message_boxes) == 1
    title, text, _ = message_boxes[0]
    check_p([title, text, capsys.readouterr().err], home=home, game=game)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="XDG_DATA_HOME is Linux only")
def test_privacy_with_xdg_data_home(tmp_path, user_roots, session, channels, capsys,
                                    monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "qauser7" / "data"))
    game, logs = _privacy_session(tmp_path, user_roots, session, channels, capsys,
                                  RuntimeError("boom"), release=True)
    expected = "$XDG_DATA_HOME/vn-engine/my-game/logs/latest.log"
    assert any(expected in text for text in screen_texts(channels))
    assert header_log_path(user_log_dir("my-game") / "latest.log") == expected


# --- AC-F01-74, 143, 148: the error screen names the log actually used -------------------------------

def test_dev_run_with_logs_as_a_file_shows_the_per_user_log(tmp_path, user_roots, session,
                                                             channels):
    game = make_game(tmp_path, name="vn test")
    (game / "logs").write_text("x", encoding="utf-8")
    raise_at(session, 2, RuntimeError("boom"))
    assert launch(game) == 1
    log_file = user_log_dir("vn-test") / "latest.log"
    assert messages(log_file).count(UNUSABLE) == 1
    shown = header_log_path(log_file)
    assert f"Log: {shown}{FALLBACK}" in messages(log_file)
    assert f"Log file: {shown}" in screen_texts(channels)
    assert shown == {
        "win32": "%LOCALAPPDATA%\\vn-engine\\vn-test\\logs\\latest.log",
        "darwin": "~/Library/Application Support/vn-engine/vn-test/logs/latest.log",
    }.get(sys.platform, "~/.local/share/vn-engine/vn-test/logs/latest.log")


def test_no_writable_log_folder_is_shown_on_the_screen(tmp_path, user_roots, session, channels):
    game = make_game(tmp_path, name="vn test")
    (game / "logs").write_text("x", encoding="utf-8")
    vn_dir = vn_engine_dir()
    vn_dir.parent.mkdir(parents=True, exist_ok=True)
    vn_dir.write_text("x", encoding="utf-8")
    raise_at(session, 2, RuntimeError("boom"))
    assert launch(game) == 1
    assert f"Log file: {NOT_AVAILABLE}" in screen_texts(channels)
    assert not list(tmp_path.rglob("*.log"))


def _make_link(link: Path, target: Path, kind: str) -> None:
    if kind == "symlink":
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"this account cannot create symlinks ({error.__class__.__name__})")
    else:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


@pytest.mark.parametrize("kind", ["symlink", pytest.param("junction", marks=pytest.mark.skipif(
    sys.platform != "win32", reason="junctions exist only on Windows"))])
def test_logs_link_out_of_the_game_is_never_used(tmp_path, user_roots, session, channels, kind):
    game = make_game(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "latest.log").write_text("keep me\n", encoding="utf-8")
    (outside / "session-2020-01-01_00-00-00.log").write_text("old\n", encoding="utf-8")
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in outside.iterdir()}
    _make_link(game / "logs", outside, kind)
    raise_at(session, 2, RuntimeError("boom"))
    assert launch(game) == 1
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in outside.iterdir()}
    assert after == before
    log_file = user_log_dir("game") / "latest.log"
    assert messages(log_file).count(UNUSABLE) == 1
    assert f"Log file: {header_log_path(log_file)}" in screen_texts(channels)


def test_release_run_falls_back_to_the_game_folder_then_console(tmp_path, user_roots, session,
                                                                channels):
    game = make_game(tmp_path)
    vn_dir = vn_engine_dir()
    vn_dir.parent.mkdir(parents=True, exist_ok=True)
    vn_dir.write_text("x", encoding="utf-8")
    raise_at(session, 2, RuntimeError("boom"))
    assert launch(game, release=True) == 1
    log_file = game / "logs" / "latest.log"
    assert "Log: <game>/logs/latest.log" in messages(log_file)
    assert "Log file: <game>/logs/latest.log" in screen_texts(channels)

    other = make_game(tmp_path, name="other")
    (other / "logs").write_text("x", encoding="utf-8")
    channels.draws.clear()
    raise_at(session, 2, RuntimeError("boom"))
    assert launch(other, release=True) == 1
    assert f"Log file: {NOT_AVAILABLE}" in screen_texts(channels)
    assert (other / "logs").read_text(encoding="utf-8") == "x"


# --- AC-F01-76, 77, 80: engine exceptions -----------------------------------------------------------

@pytest.mark.parametrize("where", ["update", "draw"])
def test_engine_exception_in_the_example_game(tmp_path, user_roots, session, channels, where):
    game = tmp_path / "game"
    shutil.copytree(REPO / "game", game, ignore=shutil.ignore_patterns("logs", "characters"))
    # The load screen slices by wall-clock time (SCRIPT_LOAD_SLICE_S on time.perf_counter,
    # not the fake clock), so the hand-over to the title (``replace_all``, which drops any
    # screen pushed above the load screen) lands on frame 2 or 3 depending on machine speed.
    # Push the Raiser on the first frame from 3 that starts after the load handed over.
    pushed = []

    def push_after_load(app):
        if not pushed and not app.loading:
            pushed.append(True)
            app.screens.push(Raiser(RuntimeError("boom"), where))

    for frame in range(3, 9):
        session.at(frame, push_after_load)
    session.quit_frame = 10
    assert launch(game) == 1
    app = session.apps[-1]
    assert len(app.screens) == 1 and isinstance(app.screens.top, ErrorScreen)
    texts = screen_texts(channels)
    heading = next(c for c in channels.draws if c.text == "The game ran into a problem")
    assert heading.font.size == 40 and heading.pos == (80, 96)
    assert ENGINE_ERROR in texts
    assert '"Example Visual Novel" version 0.1.0' in texts
    assert "Log file: <game>/logs/latest.log" in texts
    assert any("Press Esc or Enter to quit" in t for t in texts)
    lines = (game / "logs" / "latest.log").read_text(encoding="utf-8").splitlines()
    error_index = next(i for i, line in enumerate(lines) if line[24:31].strip() == "ERROR")
    assert lines[error_index + 1].startswith("  Traceback")          # SEC-F23-09 prefix
    assert "RuntimeError: boom" in "\n".join(lines[error_index:error_index + 40])
    # One flip when the window is created, then frames 1–10 except the one that raised.
    assert len([entry for entry in SpyWindow.log if entry[0] == "flip"]) == 1 + 9


def test_engine_error_text_is_redacted_before_it_is_cut(tmp_path, user_roots, session,
                                                        channels, capsys):
    home = user_roots.home
    path = str(home / "a.png")
    end_of_name = path.index("qauser7") + len("qauser7")
    prefix = "x" * (119 - end_of_name + 3)
    raw = prefix + path + " "
    raw += "y" * (500 - len(raw))
    name_start = len(prefix) + path.index("qauser7")
    assert name_start < 119 < name_start + len("qauser7")   # a raw cut would split the name
    game = make_game(tmp_path)
    raise_at(session, 2, RuntimeError(raw))
    assert launch(game) == 1
    message = error_screen(session).message
    match = re.fullmatch(r"Something went wrong inside the engine \(RuntimeError: (.*)\)\. "
                         r"The log file has the details\.", message)
    assert match
    shown = match.group(1)
    assert len(shown) <= 120 and shown.endswith("…") and "~" in shown
    for start in range(len("qauser7") - 2):
        assert "qauser7"[start:start + 3] not in shown
    texts = channels.texts() + [capsys.readouterr().err,
                                (game / "logs" / "latest.log").read_text(encoding="utf-8")]
    check_p(texts, home=home, game=game)


def test_esc_on_the_error_screen_ends_the_log_with_exit_code_1(tmp_path, user_roots, session):
    game = make_game(tmp_path)
    raise_at(session, 2, RuntimeError("boom"))
    press_at(session, 4, pygame.K_ESCAPE)
    session.quit_frame = 50
    assert launch(game) == 1
    assert messages(game / "logs" / "latest.log")[-1] == "Clean shutdown (exit code 1)"


# --- AC-F01-78: missing game folder ----------------------------------------------------------------

def test_missing_game_folder_on_the_error_screen(tmp_path, user_roots, session, channels, capsys):
    home = user_roots.home
    press_at(session, 2, pygame.K_ESCAPE)
    session.quit_frame = 50
    assert launch(home / "Desktop" / "nope") == 1
    assert error_screen(session).message == (
        'Can\'t find the game folder "~/Desktop/nope". Check that the folder exists, or run: '
        "python -m engine run <folder>")
    assert '"Untitled Visual Novel" version 0.0.0' in screen_texts(channels)
    log_file = user_log_dir("nope") / "latest.log"
    assert log_file.is_file()
    check_p(channels.texts() + [capsys.readouterr().err, log_file.read_text(encoding="utf-8")],
            home=home)

    (home / "Desktop").mkdir(parents=True, exist_ok=True)
    (home / "Desktop" / "notes.txt").write_text("x", encoding="utf-8")
    press_at(session, 2, pygame.K_ESCAPE)
    assert launch(home / "Desktop" / "notes.txt") == 1
    assert error_screen(session).message == (
        '"~/Desktop/notes.txt" is a file, not a folder. Check that the folder exists, or run: '
        "python -m engine run <folder>")

    press_at(session, 2, pygame.K_ESCAPE)
    assert launch(tmp_path / "elsewhere" / "nope") == 1
    message = error_screen(session).message
    assert message.startswith('Can\'t find the game folder "')
    assert message.endswith('". Check that the folder exists, or run: python -m engine run '
                            "<folder>")
    check_p([message, capsys.readouterr().err], home=home)


# --- AC-F01-81, 82: the window or the error screen fails ------------------------------------------------

def test_window_creation_failure(tmp_path, user_roots, monkeypatch, message_boxes, capsys):
    game = make_game(tmp_path, '[game]\ntitle = "Paper Lanterns"\n')

    def no_window(**kwargs):
        raise WindowCreationError("No available video device")

    monkeypatch.setattr("engine.render.window.GameWindow", no_window)
    assert launch(game) == 1
    assert len(message_boxes) == 1
    title, text, kwargs = message_boxes[0]
    assert title == "Paper Lanterns could not start"
    assert kwargs.get("message_type") == "error"
    assert "No available video device" in text
    assert "No available video device" in capsys.readouterr().err
    log_text = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    assert "ERROR   window  The game window could not be created" in log_text
    assert "Traceback" in log_text

    message_boxes.error = pygame.error("no dialog")
    assert launch(game) == 1


def test_a_failing_error_screen_falls_back(tmp_path, user_roots, session, monkeypatch,
                                           message_boxes, capsys):
    game = make_game(tmp_path)

    def broken(self, canvas):
        raise ValueError("the error screen broke")

    monkeypatch.setattr(ErrorScreen, "draw", broken)
    raise_at(session, 2, RuntimeError("boom"))
    session.quit_frame = 50
    started = time.perf_counter()
    assert launch(game) == 1
    assert time.perf_counter() - started < 10
    assert session.limiters[-1].frame == 3
    assert len(message_boxes) == 1
    assert ENGINE_ERROR in capsys.readouterr().err
    log_text = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    assert log_text.count("Traceback") >= 2
    assert "RuntimeError: boom" in log_text and "ValueError: the error screen broke" in log_text


# --- AC-F01-110: the engine writes only into its chosen log folder -------------------------------------

def _png_bomb() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 100_000, 100_000, 8, 6, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk)))


def _tree(root: Path) -> dict[str, tuple]:
    found = {}
    for path in root.rglob("*"):
        st = os.lstat(path)
        if path.is_file() and not path.is_symlink():
            found[str(path)] = (st.st_size, st.st_mtime_ns,
                                hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            found[str(path)] = ("dir",)
    return found


@pytest.mark.parametrize("release", [False, True])
def test_writes_only_into_the_log_folder(tmp_path, user_roots, session, monkeypatch, release):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    game = copy_fixture_game("assets", tmp_path / "game")
    if release:
        (game / "config.toml").write_text('[game]\nid = "my-vn"\n', encoding="utf-8")
    (game / "images" / "bomb.png").write_bytes(_png_bomb())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.png").write_bytes((game / "gui" / "lantern.png").read_bytes())

    def load_everything(app):
        for ref in ("../outside/x.png", "images/../../x.png", "C:/x.png", "/etc/passwd",
                    "images\\bg.png", "images/a\n2026-11-01 forged.png", "images/con.png",
                    "images/bomb.png", "images/missing.png", "images/corrupt.png",
                    "images/rgba.png"):
            app.assets.image(ref)

    session.at(2, load_everything)
    press_at(session, 3, pygame.K_F11)
    raise_at(session, 4, RuntimeError("boom"))
    session.quit_frame = 6
    before = _tree(tmp_path)
    assert launch(game, release=release) == 1
    after = _tree(tmp_path)
    changed = {p for p in after if before.get(p) != after[p]} | (set(before) - set(after))
    # F16: F11 is the player's fullscreen choice, kept in the settings folder (ADR-0003
    # Settings row), the only other place the engine may write.
    if release:
        log_dir = user_log_dir("my-vn")
        settings_dir = user_data_dir("my-vn") / "settings"
        allowed_parents = {str(p) for p in (*log_dir.parents, *settings_dir.parents)}
        for path in changed:
            assert Path(path).is_relative_to(log_dir) or Path(path).is_relative_to(
                settings_dir) or (path in allowed_parents and path not in before), path
        assert not any(Path(p).is_relative_to(game) for p in changed)
    else:
        for path in changed:
            assert (Path(path).is_relative_to(game / "logs")
                    or Path(path).is_relative_to(game / "settings")), path
    assert changed


# --- AC-F01-124: [game] id names a folder only when valid and loaded --------------------------------------

@pytest.mark.parametrize("config", [
    '[game]\nid = "../escape"\n[window]\nwidth = 1280\n',
    '[game]\nid = "my-vn"\n[window]\nwidth = = 5\n',
    '[game]\nid = "CON"\n',
    '[game]\nid = "A"\n',
    '[game]\nid = "ｍｙ-ｖｎ"\n',
    "[game]\nid = 5\n",
])
def test_invalid_id_never_names_a_folder(tmp_path, user_roots, session, config):
    game = make_game(tmp_path, config, name="Lantern Game")
    touched = []
    with pytest.MonkeyPatch.context() as spies:
        def spy(owner, name):
            real = getattr(owner, name)

            def wrapper(*args, **kwargs):
                if args:
                    touched.append(str(args[0]))
                return real(*args, **kwargs)

            spies.setattr(owner, name, wrapper)

        spy(os, "mkdir")
        spy(os, "makedirs")
        spy(Path, "mkdir")
        spy(builtins, "open")
        spy(io, "open")
        assert launch(game, release=True) == 1
    log_file = user_log_dir("lantern-game") / "latest.log"
    lines = messages(log_file)
    assert any(line.startswith("Log: ") and line.endswith(FALLBACK) for line in lines)
    assert [r for r in records(log_file) if r[0] == "ERROR" and r[1] == "config"]
    forbidden = {"escape", "..", "my-vn", "CON", "con", "A", "ｍｙ-ｖｎ", "5"}
    for path in touched:
        segments = set(re.split(r"[\\/]", path))
        assert not segments & forbidden, path


# --- AC-F01-132, 134: config.toml read safely; parser failures --------------------------------------------

def test_config_link_out_of_the_game(tmp_path, user_roots, session):
    game = make_game(tmp_path, None)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config.toml").write_text('[game]\ntitle = "Leaked"\n', encoding="utf-8")
    try:
        os.symlink(outside / "config.toml", game / "config.toml")
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"this account cannot create symlinks ({error.__class__.__name__})")
    opened = []
    seen = {}
    session.at(2, lambda app: seen.update(title=app.window.title))
    real_open = builtins.open
    with pytest.MonkeyPatch.context() as spies:
        spies.setattr(builtins, "open", lambda f, *a, **k: opened.append(str(f))
                      or real_open(f, *a, **k))
        assert launch(game) == 1
    assert not [p for p in opened if "outside" in p]
    assert ("config.toml points to a place outside the game folder, which is not allowed. "
            "Replace it with a normal file.") in error_screen(session).message
    assert seen["title"] == "Untitled Visual Novel"
    assert str(outside) not in (game / "logs" / "latest.log").read_text(encoding="utf-8")


def test_config_folder_is_not_a_normal_file(tmp_path, user_roots, session):
    game = make_game(tmp_path, None)
    (game / "config.toml").mkdir()
    started = time.perf_counter()
    assert launch(game) == 1
    assert time.perf_counter() - started < 5
    assert "config.toml is not a normal file. Replace it with a text file." in \
        error_screen(session).message


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs are POSIX only")
def test_config_fifo_is_never_opened(tmp_path, user_roots, session):
    game = make_game(tmp_path, None)
    os.mkfifo(game / "config.toml")
    started = time.perf_counter()
    assert launch(game) == 1
    assert time.perf_counter() - started < 5
    assert "config.toml is not a normal file. Replace it with a text file." in \
        error_screen(session).message


PARSER_CASES = [
    (config_fixtures.generated_deep_arrays, 'config.toml is nested too deeply (too many "[" or '
                                            '"{" inside each other)'),
    (config_fixtures.generated_deep_tables, 'config.toml is nested too deeply (too many "[" or '
                                            '"{" inside each other)'),
    (config_fixtures.generated_bigint, "config.toml contains a value that is too large to read, "
                                      "such as a number with thousands of digits"),
    (lambda: (CONFIG / "nul_in_string.toml").read_bytes(), "config.toml, line 2, column 11:"),
    (lambda: (CONFIG / "utf16.toml").read_bytes(), "is not saved as UTF-8 text"),
]


@pytest.mark.parametrize("make, expected", PARSER_CASES)
def test_parser_failures_end_on_the_error_screen(tmp_path, user_roots, session, capsys,
                                                 make, expected):
    game = make_game(tmp_path, make())
    started = time.perf_counter()
    assert launch(game) == 1
    assert time.perf_counter() - started < 2
    assert expected in error_screen(session).message
    assert "Traceback" not in capsys.readouterr().err
    assert "Traceback" not in (game / "logs" / "latest.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("make", [c[0] for c in PARSER_CASES[:3]])
def test_parser_tracebacks_only_in_debug_records(tmp_path, user_roots, session, make):
    game = make_game(tmp_path, make())
    assert launch(game, log_level="debug") == 1
    last_level = None
    for line in (game / "logs" / "latest.log").read_text(encoding="utf-8").splitlines():
        if TIMESTAMP.match(line):
            last_level = line[24:31].strip()
        elif line.startswith("  Traceback"):                      # SEC-F23-09 prefix
            assert last_level == "DEBUG"
        else:
            assert not line.startswith("Traceback"), line


# --- AC-F01-137: content cannot forge or hide log lines -----------------------------------------------

def _assert_line_format(log_file: Path) -> None:
    in_traceback = False
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if TIMESTAMP.match(line):
            assert LINE_FORMAT.match(line), line
            in_traceback = line[24:31].strip() == "ERROR" or line[24:31].strip() == "DEBUG"
        else:
            assert in_traceback, line
            assert line.startswith("  "), line                      # SEC-F23-09 prefix


def test_forged_title(tmp_path, user_roots, session, channels):
    game = make_game(tmp_path, (CONFIG / "forged_title.toml").read_bytes())
    seen = {}
    session.at(2, lambda app: seen.update(title=app.window.title))
    raise_at(session, 2, RuntimeError("boom"))
    assert launch(game) == 1
    log_file = game / "logs" / "latest.log"
    game_line = next(m for m in messages(log_file) if m.startswith("Game: "))
    assert "Paper\\n2026-11-01" in game_line
    for line in log_file.read_text(encoding="utf-8").splitlines():
        assert not line.startswith("2026-11-01 00:00:00.000")
    assert "Paper\\n2026-11-01" in error_screen(session).game_title
    assert seen["title"].startswith("Paper\ufffd2026-11-01")
    _assert_line_format(log_file)


def test_bidi_title_and_long_unknown_key(tmp_path, user_roots, session):
    game = make_game(tmp_path, (CONFIG / "bidi_title.toml").read_bytes())
    assert launch(game) == 0
    log_file = game / "logs" / "latest.log"
    game_line = next(m for m in messages(log_file) if m.startswith("Game: "))
    assert "\\u202e" in game_line and "\u202e" not in game_line
    _assert_line_format(log_file)

    other = make_game(tmp_path, config_fixtures.generated_long_unknown_key(), name="other")
    assert launch(other) == 0
    log_file = other / "logs" / "latest.log"
    expected = "config.toml, line 2: unknown key [game] " + "k" * 119 + "…"
    assert ("WARNING", "config", expected) in records(log_file)
    _assert_line_format(log_file)


def test_control_character_refs_log_one_line_each(tmp_path, user_roots, session):
    game = make_game(tmp_path)
    refs = ["a.png\x00.txt", "images/a\x01.png", "images/a\tb.png",
            "images/a\n2026-11-01 00:00:00.000 ERROR app forged.png", "images/\x1b[31mred.png",
            "images/a\x7f.png"]
    session.at(2, lambda app: [app.assets.image(ref) for ref in refs])
    assert launch(game) == 0
    log_file = game / "logs" / "latest.log"
    # One line per ref (the ".txt" one is refused for its format before its characters).
    problems = [r for r in records(log_file) if r[0] in ("WARNING", "ERROR")]
    assert len(problems) == len(refs)
    _assert_line_format(log_file)


# --- AC-F01-150, 151: redaction on screen and the longest root ----------------------------------------

def test_user_facing_error_text_is_redacted_on_screen(tmp_path, user_roots, session, channels):
    game = make_game(tmp_path)
    root = game.resolve()
    raise_at(session, 2, UserFacingError("Bad file " + str(root / "script" / "a.vns")))
    assert launch(game) == 1
    assert error_screen(session).message in ("Bad file <game>/script/a.vns",
                                             "Bad file <game>\\script\\a.vns")
    check_p(channels.texts(), home=user_roots.home, game=game)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows environment roots")
def test_longest_root_wins_on_windows(tmp_path, user_roots, session, channels, capsys):
    game = make_game(tmp_path, '[game]\nid = "my-vn"\n[window]\nwidth = "big"\n')
    press_at(session, 2, pygame.K_c)
    assert launch(game, release=True) == 1
    # AC-F01-151 names my-vn, but §4.1 / §7.1 step 9 use [game] id only when the config
    # loaded without errors, so the second ConfigError makes this the fallback folder
    # (reported as a spec conflict). The longest-root rule is what this test checks.
    expected = "%LOCALAPPDATA%\\vn-engine\\game\\logs\\latest.log"
    log_file = user_log_dir("game") / "latest.log"
    assert header_log_path(log_file) == expected
    assert f"Log file: {expected}" in screen_texts(channels)
    assert len(channels.clipboard) == 1 and expected in channels.clipboard[0]
    for text in [log_file.read_text(encoding="utf-8")] + channels.texts():
        assert "~\\AppData\\Local" not in text
    check_p(channels.texts() + [capsys.readouterr().err, log_file.read_text(encoding="utf-8")],
            home=user_roots.home, game=game)
