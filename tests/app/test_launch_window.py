"""In-process ``launch()`` with the window, assets, and the App (§7.1 steps 11–17).

AC-F01-06 (non-ASCII paths and title), 18 (config read once), 19 (title from config), 22
(custom icon), 23 / 139 (icon fallbacks at launch), 29 / 54 (creation order, start in
fullscreen, F11 back to the initial size), 31 (display scale feeds the window size), 68 (log
header), 162 (video driver line and the Wayland note), 166 (header line 5 echo limits).

``pygame.Window`` is a ``SpyWindow`` here (``tests/app/conftest.py``), so no window is ever
shown, and each App quits after a few scripted frames.
"""

import ast
import builtins
import io
import os
import re
import shutil
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap, cli
from engine.app import platform as osinfo
from engine.core.geometry import initial_window_size
from engine.core.paths import GamePaths, engine_data_dir
from engine.render.window import GameWindow
from tests.fakes.spy_window import SpyWindow

pytestmark = pytest.mark.display

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "F01"
REPO = Path(__file__).resolve().parent.parent.parent
SLASH = "paths must stay inside the game folder and use forward slashes, e.g. images/bg/club.png"

HEADER = [
    re.compile(r"^vn-engine 0\.1\.0 \| Python \d+\.\d+\.\d+ \| pygame-ce \d+\.\d+\.\d+ "
               r"\(SDL \d+\.\d+\.\d+\) \| .+ \| build (dev|release)$"),
    re.compile(r"^Log: .+$"),
    re.compile(r"^Displays \(video driver [a-z0-9_]+\): \d+: \d+x\d+ @ (\d+%|n/a)"
               r"(, \d+: \d+x\d+ @ (\d+%|n/a))*$"),
    re.compile(r"^Window: \d+x\d+ (windowed|fullscreen) \| framebuffer \d+x\d+ px \| "
               r"requested \d+x\d+ \| display scale \d+(\.\d+)? \| usable area \d+x\d+ "
               r"\((work area|estimated)\)$"),
    re.compile(r"^Game: \".*\" .* \| canvas 1280x720 \| render: device resolution \| "
               r"cache \d+ MB \| fps cap \d+$"),
]
LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) (\w+)\s+(\w+)\s+(.*)$")


@pytest.fixture(autouse=True)
def _quit_after_a_few_frames(scripted_app):
    return scripted_app


def launch(game_dir: Path, *, release: bool = False, log_level: str | None = None) -> int:
    return bootstrap.launch(game_dir, release=release, bench_seconds=None,
                            log_level_override=log_level, pygame_warning=None)


def make_game(parent: Path, config: str = "", name: str = "game") -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / "config.toml").write_text(config, encoding="utf-8")
    return root


# F02 adds one WARNING to every launch of a game folder without a story (PR-F02-06). These
# F01 games have none, so the F01 checks leave that one record out (F02 07 §6 (a)).
W01 = ("WARNING", "script", "No story found: script/main.vns doesn't exist.")


def records(log_file: Path) -> list[tuple[str, str, str]]:
    """(level, area, message) of each timestamped line, except F02's W01."""
    out = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        match = LINE.match(line)
        if match and (match.group(2), match.group(3), match.group(4)) != W01:
            out.append((match.group(2), match.group(3), match.group(4)))
    return out


def header_lines(log_file: Path) -> list[str]:
    found = []
    for level, area, message in records(log_file):
        for index, pattern in enumerate(HEADER):
            if level == "INFO" and area == "app" and pattern.match(message):
                found.append((index, message))
    return found


# --- AC-F01-68: the log header -------------------------------------------------------------------

def test_header_lines_in_order(tmp_path, user_roots):
    game = make_game(tmp_path, '[game]\ntitle = "Paper Lanterns"\nversion = "0.1.0"\n')
    assert launch(game) == 0
    log_file = game / "logs" / "latest.log"
    lines = records(log_file)
    assert HEADER[0].match(lines[0][2])
    found = header_lines(log_file)
    assert [index for index, _ in found] == [0, 1, 2, 3, 4]
    assert pygame.version.ver in found[0][1]
    assert found[4][1] == ('Game: "Paper Lanterns" 0.1.0 | canvas 1280x720 | '
                           'render: device resolution | cache 512 MB | fps cap 60')
    assert lines[-1] == ("INFO", "app", "Clean shutdown (exit code 0)")
    assert not [line for line in lines if line[0] in ("WARNING", "ERROR")]


def test_window_line_reports_size_framebuffer_scale_and_usable_area(tmp_path, user_roots,
                                                                    monkeypatch):
    monkeypatch.setattr(osinfo, "system_display_scale", lambda: 1.25)
    monkeypatch.setattr(osinfo, "primary_work_area", lambda: (1366, 728))
    game = make_game(tmp_path)
    assert launch(game) == 0
    window_line = header_lines(game / "logs" / "latest.log")[3][1]
    assert window_line == ("Window: 1164x655 windowed | framebuffer 1164x655 px | requested "
                           "1280x720 | display scale 1.25 | usable area 1366x728 (work area)")


def test_estimated_usable_area_without_a_work_area(tmp_path, user_roots, monkeypatch):
    monkeypatch.setattr(osinfo, "primary_work_area", lambda: None)
    monkeypatch.setattr(pygame.display, "get_desktop_sizes", lambda: [(1366, 768)])
    game = make_game(tmp_path)
    assert launch(game) == 0
    window_line = header_lines(game / "logs" / "latest.log")[3][1]
    assert window_line.endswith("usable area 1366x688 (estimated)")


# --- AC-F01-31 (scale part): the display scale feeds the window size ----------------------------

def test_display_scale_is_applied_to_the_requested_size(tmp_path, user_roots, monkeypatch):
    seen = []
    monkeypatch.setattr(osinfo, "system_display_scale", lambda: 144 / 96)
    monkeypatch.setattr(osinfo, "primary_work_area", lambda: (2560, 1392))
    monkeypatch.setattr(bootstrap, "initial_window_size",
                        lambda *a, **k: seen.append(a) or initial_window_size(*a, **k))
    game = make_game(tmp_path)
    assert launch(game) == 0
    assert seen == [((1280, 720), 1.5, (2560, 1392))]
    assert SpyWindow.log[0][1]["size"] == (1920, 1080)


# --- AC-F01-162: the video driver line and the Wayland note -----------------------------------------

def test_engine_never_sets_the_video_driver():
    for path in (REPO / "engine").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "SDL_VIDEODRIVER":
                pytest.fail(f"{path} mentions SDL_VIDEODRIVER")


def test_environment_setup_leaves_the_driver_unset(monkeypatch):
    monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    cli.prepare_environment()
    assert "SDL_VIDEODRIVER" not in os.environ


# The engine checks ``driver == "wayland"``, so x11 stands for every other named driver
# (windows and cocoa took the same path); dummy is the real driver in test_real_driver_is_named.
@pytest.mark.parametrize("driver, notes", [("wayland", 1), ("x11", 0)])
def test_wayland_note(tmp_path, user_roots, monkeypatch, driver, notes):
    monkeypatch.setattr(pygame.display, "get_driver", lambda: driver)
    game = make_game(tmp_path)
    assert launch(game) == 0
    lines = records(game / "logs" / "latest.log")
    note = ("INFO", "app", bootstrap.NATIVE_WAYLAND_NOTE)
    assert lines.count(note) == notes
    assert any(message.startswith(f"Displays (video driver {driver}): ")
               for _, _, message in lines)


def test_real_driver_is_named(tmp_path, user_roots):
    game = make_game(tmp_path)
    assert launch(game) == 0
    displays = header_lines(game / "logs" / "latest.log")[2][1]
    expected = os.environ.get("SDL_VIDEODRIVER", "")
    assert displays.startswith(f"Displays (video driver {expected or ''}")
    if expected != "wayland":
        assert ("INFO", "app", bootstrap.NATIVE_WAYLAND_NOTE) not in records(
            game / "logs" / "latest.log")


# --- AC-F01-18 / 19: the title comes from config, read once -------------------------------------

def test_config_is_read_once(tmp_path, user_roots, scripted_app, monkeypatch):
    game = make_game(tmp_path, '[game]\ntitle = "Before"\n')
    loads = []
    real_load = bootstrap.load_config
    monkeypatch.setattr(bootstrap, "load_config", lambda p: loads.append(p) or real_load(p))
    titles = []
    scripted_app.at(6, lambda app: (game / "config.toml").write_text(
        '[game]\ntitle = "After"\n', encoding="utf-8"))
    scripted_app.at(65, lambda app: titles.append(app.window.title))
    scripted_app.quit_frame = 65
    assert launch(game) == 0
    assert titles == ["Before"] and len(loads) == 1
    scripted_app.at(1, lambda app: titles.append(app.window.title))
    assert launch(game) == 0
    assert titles[-1] == "After"


@pytest.mark.parametrize("title", ["Paper Lanterns", "📖 مرحبا 文芸部",
                                   ("Long title " * 46)[:500]])
def test_window_title_from_config(tmp_path, user_roots, scripted_app, title):
    game = make_game(tmp_path, f'[game]\ntitle = "{title}"\n')
    seen = []
    scripted_app.at(1, lambda app: seen.append(app.window.title))
    assert launch(game) == 0
    assert seen == [title]


def test_header_line_5_echoes_to_120_characters(tmp_path, user_roots):
    title = ("Long title " * 46)[:500]
    version = "9" * 200
    game = make_game(tmp_path, f'[game]\ntitle = "{title}"\nversion = "{version}"\n')
    assert launch(game) == 0
    game_line = header_lines(game / "logs" / "latest.log")[4][1]
    assert game_line.startswith(f'Game: "{title[:119]}…" {version[:119]}… | ')


# --- AC-F01-29 / 54: creation order and starting in fullscreen ---------------------------------

def test_window_is_created_hidden_and_shown_after_the_first_frame(tmp_path, user_roots):
    game = make_game(tmp_path, '[window]\nletterbox_color = "#123456"\n')
    assert launch(game) == 0
    names = [entry[0] for entry in SpyWindow.log if entry[0] in
             ("create", "set_fullscreen", "flip", "show")]
    assert names[:3] == ["create", "flip", "show"]
    assert SpyWindow.log[0][1]["hidden"] is True
    assert next(entry for entry in SpyWindow.log if entry[0] == "flip")[1] == (0x12, 0x34, 0x56)


def test_starting_in_fullscreen(tmp_path, user_roots, scripted_app, monkeypatch):
    monkeypatch.setattr(osinfo, "system_display_scale", lambda: 1.0)
    monkeypatch.setattr(osinfo, "primary_work_area", lambda: (1366, 728))
    game = make_game(tmp_path, '[window]\nfullscreen = true\n')
    scripted_app.at(2, lambda app: app.handle_raw(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_F11, mod=0)))
    assert launch(game) == 0
    names = [entry[0] for entry in SpyWindow.log if entry[0] in
             ("create", "set_fullscreen", "flip", "show", "set_windowed")]
    assert names[:4] == ["create", "set_fullscreen", "flip", "show"]
    assert "set_windowed" in names
    expected = initial_window_size((1280, 720), 1.0, (1366, 728))
    assert ("set size", expected) in SpyWindow.log
    assert ("set position", pygame.WINDOWPOS_CENTERED) in SpyWindow.log
    window_line = header_lines(game / "logs" / "latest.log")[3][1]
    assert window_line.startswith("Window: ") and " fullscreen | " in window_line


# --- AC-F01-22 / 23 / 139: the window icon at launch --------------------------------------------

@pytest.fixture
def icon_spy(monkeypatch):
    icons = []
    real = GameWindow.set_icon
    monkeypatch.setattr(GameWindow, "set_icon",
                        lambda self, surface: icons.append(surface) or real(self, surface))
    return icons


@pytest.mark.parametrize("ref", ["gui/lantern.png", "gui/UPPER.PNG"])
def test_custom_icon_at_launch(tmp_path, user_roots, icon_spy, ref):
    game = tmp_path / "game"
    shutil.copytree(FIXTURES / "games" / "assets", game)
    (game / "config.toml").write_text(f'[window]\nicon = "{ref}"\n', encoding="utf-8")
    assert launch(game) == 0
    assert len(icon_spy) == 1
    expected = (255, 0, 0) if ref == "gui/lantern.png" else (0, 255, 0)
    assert icon_spy[0].get_at((32, 32))[:3] == expected
    assert not [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]


@pytest.mark.parametrize("ref, level, text", [
    ("../x.png", "ERROR", f'Asset path "../x.png" is not allowed: {SLASH} — using the engine icon'),
    ("/etc/passwd", "WARNING", 'Window icon "/etc/passwd" must be a PNG file — using the engine icon'),
    ("C:/Windows/win.ini", "WARNING",
     'Window icon "C:/Windows/win.ini" must be a PNG file — using the engine icon'),
])
def test_blocked_or_non_png_icon_is_never_read(tmp_path, user_roots, icon_spy, ref, level, text):
    game = make_game(tmp_path, f'[window]\nicon = "{ref}"\n')
    outside = tmp_path / "x.png"
    outside.write_bytes((FIXTURES / "games" / "assets" / "gui" / "lantern.png").read_bytes())
    touched = []
    reads = []
    real_read = GamePaths.read_file
    # A context of its own: only the file spies are undone afterwards, not user_roots,
    # scripted_app, or the message_box recorder.
    with pytest.MonkeyPatch.context() as spies:
        for owner, name in ((builtins, "open"), (io, "open"), (os, "open"), (Path, "read_bytes")):
            real = getattr(owner, name)

            def spy(*args, _real=real, **kwargs):
                touched.append(str(args[0]))
                return _real(*args, **kwargs)

            spies.setattr(owner, name, spy)
        spies.setattr(GamePaths, "read_file",
                      lambda self, r, *, max_bytes: reads.append(r) or real_read(
                          self, r, max_bytes=max_bytes))
        assert launch(game) == 0
    assert reads == ["config.toml"]
    # The game, the engine's own data, the log folders, and pygame's default window icon.
    allowed = (game.resolve(), engine_data_dir().resolve(), user_roots.home.resolve(),
               Path(pygame.__file__).resolve().parent)
    for path in touched:
        resolved = Path(path).resolve()
        assert any(resolved.is_relative_to(root) for root in allowed), path
        assert resolved != outside.resolve()
    engine_icon = pygame.image.tobytes(pygame.image.load(str(engine_data_dir() / "icon.png")),
                                       "RGBA")
    pygame.init()
    assert pygame.image.tobytes(icon_spy[0], "RGBA") == engine_icon
    pygame.quit()
    icon_lines = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert icon_lines == [(level, "assets", text)]


# --- AC-F01-06: spaces and non-ASCII characters in paths and the title ------------------------------

def test_unicode_game_folder(tmp_path, user_roots, scripted_app, monkeypatch):
    game = tmp_path / "My Games" / "José" / "マイゲーム"
    shutil.copytree(FIXTURES / "games" / "unicode", game)
    reads = []
    real_read = GamePaths.read_file
    monkeypatch.setattr(GamePaths, "read_file",
                        lambda self, r, *, max_bytes: reads.append(r) or real_read(
                            self, r, max_bytes=max_bytes))
    seen = {}

    def probe(app):
        seen["title"] = app.window.title
        image = app.assets.image("images/背景/é.png")
        seen["image"] = (image.is_placeholder, image.size)
        font = app.assets.font("fonts/フォント.ttf", 20)
        seen["font_key"] = font.key
        seen["widths"] = (font.font.size("Hello")[0],
                          app.assets.font(None, 20).font.size("Hello")[0])

    scripted_app.at(2, probe)
    assert launch(game) == 0
    assert seen["title"] == "文芸部 Café Литература"
    assert seen["image"] == (False, (64, 32))
    assert seen["font_key"] == ("font", "fonts/フォント.ttf", 20)
    assert seen["widths"][0] != seen["widths"][1]
    assert "fonts/フォント.ttf" in reads
    log_file = game / "logs" / "latest.log"
    text = log_file.read_text(encoding="utf-8")
    assert '"文芸部 Café Литература"' in header_lines(log_file)[4][1]
    assert "Clean shutdown (exit code 0)" in text
