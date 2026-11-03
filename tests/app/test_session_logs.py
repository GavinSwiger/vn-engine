"""Whole sessions in-process, on a fake clock: the example game, logs, bench, frozen builds.

AC-F01-04 (missing subfolders), 05 (the example game's files), 65 (five sessions kept), 67
(log line format), 70 (level filter and lifecycle lines), 155 (no dev mode in a frozen
build). ``--bench 1`` runs here take 6 s of *fake* time (about 360 frames), so they finish
in about a second each; the real-time bench is covered by ``test_smoke_launch.py``.
"""

import re
import shutil
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap, cli
from engine.core.logsetup import get_logger
from engine.core.paths import user_log_dir
from engine.ui.screen import Screen
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.first_launch import answer_name_question
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "F01"
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")
FORMAT = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} (DEBUG|INFO|WARNING|ERROR)\s+[a-z]{1,7}\s+.+$")
HEADER = [r"^vn-engine 0\.1\.0 \| ", r"^Log: ", r"^Displays \(video driver ", r"^Window: ",
          r"^Game: "]
NOT_FOUND = "config.toml not found — using default settings"
W01 = "No story found: script/main.vns doesn't exist."


@pytest.fixture(autouse=True)
def session(scripted_app):
    scripted_app.quit_frame = 10_000          # bench runs end themselves
    return scripted_app


def launch(game: Path, *, bench: float | None = None, log_level: str | None = None,
           release: bool = False) -> int:
    return bootstrap.launch(game, release=release, bench_seconds=bench,
                            log_level_override=log_level, pygame_warning=None)


def copy_example(dest: Path) -> Path:
    shutil.copytree(REPO / "game", dest, ignore=shutil.ignore_patterns("logs", "characters"))
    answer_name_question(dest)               # F30 s6: no first-launch name question
    return dest


def records(log_file: Path) -> list[tuple[str, str, str]]:
    return [(line[24:31].strip(), line[32:39].strip(), line[40:])
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if TIMESTAMP.match(line)]


def assert_header(messages: list[str]) -> None:
    """Header lines 1-5 appear in order (DEBUG records may sit between them)."""
    position = 0
    for pattern in HEADER:
        while not re.match(pattern, messages[position]):
            position += 1
        position += 1


class Raiser(Screen):
    opaque = False

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def update(self, dt, *, is_top):
        raise self.error


# --- AC-F01-05: the shipped example game ----------------------------------------------------------

def test_example_game_files():
    game = REPO / "game"
    for name in ("script", "images", "audio", "fonts", "gui"):
        assert (game / name).is_dir(), name
    text = (game / "config.toml").read_text(encoding="utf-8")
    parsed = tomllib.loads(text)
    assert parsed["game"]["title"] == "Example Visual Novel"
    assert parsed["game"]["version"] == "0.1.0"
    assert "id" not in parsed["game"]
    id_lines = [line for line in text.splitlines() if re.match(r"^#\s*id\s*=", line)]
    assert len(id_lines) == 1 and "set a unique id before you release" in id_lines[0]
    defaults = ["width = 1280", "height = 720", "fullscreen = false", "resizable = true",
                'letterbox_color = "#000000"', 'scale_filter = "smooth"',
                "integer_scale = false", "fps = 60", "cache_mb = 512", 'log_level = "info"']
    commented = [line.lstrip("# ").split("   #")[0].strip() for line in text.splitlines()
                 if line.startswith("#")]
    for default in defaults:
        assert default in commented, default
    assert any(line.startswith("icon = ") for line in commented)
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "game/logs/" in gitignore


def test_example_game_runs_without_warnings(tmp_path, user_roots):
    game = copy_example(tmp_path / "game")
    assert launch(game, bench=1.0) == 0
    recs = records(game / "logs" / "latest.log")
    assert not [r for r in recs if r[0] in ("WARNING", "ERROR")]
    assert '"Example Visual Novel" 0.1.0' in recs[4][2]


# --- AC-F01-04: missing subfolders are not errors (with F02's W01, F02 I-16) -----------------------

def test_empty_game_folder(tmp_path, user_roots):
    game = tmp_path / "empty"
    game.mkdir()
    assert launch(game, bench=1.0) == 0
    recs = records(game / "logs" / "latest.log")
    problems = [r for r in recs if r[0] in ("WARNING", "ERROR")]
    assert problems == [("WARNING", "config", NOT_FOUND), ("WARNING", "script", W01)]
    assert [p.name for p in game.iterdir()] == ["logs"]


@pytest.mark.parametrize("missing", ["script", "images", "audio", "fonts", "gui"])
def test_example_game_without_a_subfolder(tmp_path, user_roots, missing):
    game = copy_example(tmp_path / "game")
    shutil.rmtree(game / missing)
    assert launch(game, bench=1.0) == 0
    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    if missing == "images":
        # Without images/ the example's scene, show, and expression words name no picture,
        # so the launch check warns (W12, W13; area stage) and placeholders show. Expected
        # and permanent (project ruling, F04 step 8): only those warnings are allowed.
        assert {r[:2] for r in problems} == {("WARNING", "stage")}
        assert any("there are no images for hana" in r[2] for r in problems)
        problems = [r for r in problems if r[:2] != ("WARNING", "stage")]
    if missing == "audio":
        # Without audio/ the example's music and sound name no file, so each one played
        # logs W26 (area audio) and plays as silence; the title music plays within the run.
        # Only those records are allowed (F08 step 5, the example's audio).
        from tests.fixtures.F08.make_audio import EXAMPLE

        missing_audio = {("WARNING", "audio", f"audio/{name} is missing, so it plays as silence.")
                         for name in EXAMPLE}
        played = [r for r in problems if r in missing_audio]
        assert played and played[0][2].startswith("audio/bgm/lantern_walk.wav")
        # F35: the dev load names each music-room track's missing file first (W220, area
        # script, at its lock track line).
        tracks = [r for r in problems if r[:2] == ("WARNING", "script") and ": track " in r[2]]
        assert [r[2].split(": ", 1)[1] for r in tracks] == [
            f'track {name} plays "{file}", but there is no such file in audio/.'
            for name, file in (("lantern_walk", "bgm/lantern_walk.wav"),
                               ("bridge_night", "bgm/bridge_night.wav"),
                               ("river", "sfx/river.wav"))]
        problems = [r for r in problems if r not in tracks]
        # F08 step 8: the launch check names each music and sound file first, in order of
        # first use (W21, area script; the lines are wherever the example's statements
        # are), then the voice files in one W22 (step 12's voiced lines). F06: the blip
        # files come first, at their characters' defines.
        launch_check = [r for r in problems if r[:2] == ("WARNING", "script")]
        twice = " (also on 1 other line)"
        assert [r[2].split(": ", 1)[1] for r in launch_check[:-1]] == [
            f"there is no file audio/{name}, so it will be silent. Add the file, or check the "
            f"spelling.{more}" for name, more in (
                ("blips/hana.wav", ""), ("blips/daichi.wav", ""),
                ("bgm/lantern_walk.wav", twice), ("sfx/river.wav", ""), ("sfx/chime.wav", ""),
                ("bgm/bridge_night.wav", twice), ("sfx/firework.wav", ""))]
        w22 = launch_check[-1][2]
        assert w22.startswith("Some voice files don't exist, so those lines have no voice:")
        assert [line.split(" (")[0] for line in w22.split("\\n")[1:]] == [
            "audio/voice/hana_001.wav", "audio/voice/daichi_001.wav", "audio/voice/hana_002.wav"]
        problems = [r for r in problems if r not in missing_audio and r not in launch_check]
    if missing == "gui":
        # Without gui/ the title picture, logo, and button frame the example's config.toml
        # names don't exist: one W64 each (area ui), and the drawn looks are used (F10 step 9,
        # the example's menus).
        missing_gui = [r for r in problems if r[:2] == ("WARNING", "ui")
                       and r[2].startswith("config.toml: [theme.") and "doesn't exist" in r[2]]
        assert len(missing_gui) == 3
        problems = [r for r in problems if r not in missing_gui]
    assert problems == ([("WARNING", "script", W01)] if missing == "script" else [])


# --- AC-F01-65: five sessions are kept ----------------------------------------------------------------

def test_five_sessions_are_kept(tmp_path, user_roots):
    game = copy_example(tmp_path / "game")
    for _ in range(7):
        assert launch(game, bench=1.0) == 0
    names = sorted(p.name for p in (game / "logs").iterdir())
    assert "latest.log" in names
    assert len([n for n in names if re.fullmatch(r"session-.+\.log", n)]) == 4
    assert len(names) == 5


# --- AC-F01-67: log line format ---------------------------------------------------------------------

def check_format(log_file: Path) -> None:
    previous = None
    after_error = False
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if not TIMESTAMP.match(line):
            assert after_error, f"continuation line outside a traceback: {line!r}"
            assert line.startswith("  "), line              # AC-F01-67 prefix row (SEC-F23-09)
            continue
        assert FORMAT.match(line), line
        assert line[23] == " "
        assert line[24:31].rstrip() in ("DEBUG", "INFO", "WARNING", "ERROR")
        assert line[31] == " "
        assert re.fullmatch(r"[a-z]{1,7}", line[32:39].rstrip()), line
        assert line[39] == " "
        stamp = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S.%f")
        assert previous is None or stamp >= previous
        previous = stamp
        after_error = line[24:31].rstrip() in ("ERROR", "DEBUG")


def test_log_line_format(tmp_path, user_roots, session):
    game = shutil.copytree(FIXTURES / "games" / "assets", tmp_path / "game")
    (game / "config.toml").write_text("[windw]\nwidth = 1280\n", encoding="utf-8")

    def frame_2(app):
        app.assets.image("images/missing.png")
        get_logger("script").info("a script line")
        get_logger("runtime").warning("a runtime line")

    session.at(2, frame_2)
    session.at(3, lambda app: post_key(pygame.K_F11))
    session.at(4, lambda app: app.screens.push(Raiser(RuntimeError("boom"))))
    assert launch(game, bench=1.0) == 1                       # the bench ends on the error screen
    log_file = game / "logs" / "latest.log"
    areas = {area for _, area, _ in records(log_file)}
    assert {"app", "config", "assets", "window", "loop", "script", "runtime"} <= areas
    assert len([m for _, _, m in records(log_file) if m.startswith("Bench ")]) == 5
    check_format(log_file)


# --- AC-F01-70: the level filter; lifecycle lines are always written --------------------------------

def level_session(tmp_path, session, *, config_level: str | None = None,
                  cli_level: str | None = None) -> list[tuple[str, str, str]]:
    game = shutil.copytree(FIXTURES / "games" / "assets", tmp_path / "game")
    if config_level is not None:
        (game / "config.toml").write_text(f'[engine]\nlog_level = "{config_level}"\n',
                                          encoding="utf-8")
    else:
        (game / "config.toml").write_text('[game]\ntitle = "Levels"\n', encoding="utf-8")

    def frame_2(app):
        app.assets.image("images/rgba.png")
        app.assets.image("images/missing.png")

    session.quit_frame = 8
    session.at(2, frame_2)
    session.at(3, lambda app: post_key(pygame.K_F11))
    session.at(4, lambda app: app.screens.push(Raiser(RuntimeError("boom"))))
    assert launch(game, log_level=cli_level) == 1
    return records(game / "logs" / "latest.log")


def has(recs, level: str, start: str) -> bool:
    return any(r[0] == level and r[2].startswith(start) for r in recs)


@pytest.mark.parametrize("config_level, cli_level, expect", [
    (None, None, {"debug": False, "toggle": True, "warning": True, "error": True}),
    ("debug", None, {"debug": True, "toggle": True, "warning": True, "error": True}),
    ("warning", None, {"debug": False, "toggle": False, "warning": True, "error": True}),
    ("error", None, {"debug": False, "toggle": False, "warning": False, "error": True}),
    ("warning", "debug", {"debug": True, "toggle": True, "warning": True, "error": True}),
])
def test_level_filter(tmp_path, user_roots, session, config_level, cli_level, expect):
    recs = level_session(tmp_path, session, config_level=config_level, cli_level=cli_level)
    found = {
        "debug": has(recs, "DEBUG", "Loaded images/"),
        "toggle": has(recs, "INFO", "Fullscreen on"),
        "warning": any(r[0] == "WARNING" and "images/missing.png" in r[2] for r in recs),
        "error": has(recs, "ERROR", "The game stopped because of an error inside the engine"),
    }
    assert found == expect
    assert_header([m for _, _, m in recs])
    assert recs[-1][2] == "Clean shutdown (exit code 1)"


def example_at_level_error(dest: Path) -> Path:
    """The example game with ``log_level = "error"``. The rest of its config.toml stays: its
    story uses a ``[stage.positions]`` name (F04 step 8)."""
    game = copy_example(dest)
    config = game / "config.toml"
    text = config.read_text(encoding="utf-8")
    assert '# log_level = "info"' in text
    config.write_text(text.replace('# log_level = "info"', 'log_level = "error"'),
                      encoding="utf-8")
    return game


def test_bench_lines_at_level_error(tmp_path, user_roots):
    game = example_at_level_error(tmp_path / "game")
    assert launch(game, bench=1.0) == 0
    recs = records(game / "logs" / "latest.log")
    assert len([r for r in recs if r[2].startswith("Bench ")]) == 5
    assert recs[-1] == ("INFO", "app", "Clean shutdown (exit code 0)")


def test_ctrl_c_at_level_error(tmp_path, user_roots, session):
    game = example_at_level_error(tmp_path / "game")
    session.at(5, lambda app: app.screens.push(Raiser(KeyboardInterrupt())))
    assert launch(game) == 0
    recs = records(game / "logs" / "latest.log")
    assert [m for _, _, m in recs[-2:]] == ["Interrupted from the terminal (Ctrl+C)",
                                            "Clean shutdown (exit code 0)"]


# --- AC-F01-155: dev mode cannot be reached in a frozen build -------------------------------------

@pytest.mark.parametrize("argv", [[], ["--bench", "1"], ["--log-level", "debug"]])
def test_frozen_build_has_no_dev_mode(tmp_path, user_roots, session, monkeypatch, argv):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO), raising=False)
    for name in ("VN_DEV", "DEBUG", "PYTHONDEVMODE"):
        monkeypatch.setenv(name, "1")
    game = tmp_path / "game"
    game.mkdir()
    shutil.copy(FIXTURES / "config" / "dev_key.toml", game / "config.toml")
    session.at(2, lambda app: post_key(pygame.K_F3))
    session.quit_frame = 5 if not argv or argv[0] != "--bench" else 10_000
    with spy_draw_text(monkeypatch) as calls:
        cli.main(["run", str(game), *argv])
    app = session.apps[-1]
    assert app.dev is False
    assert not [c for c in calls if c.pos == (8, 8)]
    log_file = user_log_dir("game") / "latest.log"
    assert records(log_file)[0][2].endswith("build release")
