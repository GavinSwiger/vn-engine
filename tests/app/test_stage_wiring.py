"""F04 step 5 — the stage in the App: ``install_stage`` (F09 C6), ``in_game_screens``, the
bootstrap ``LoadOptions``, and the stage under F05's textbox (``06-acceptance.md`` §0.2:
App-level cases with a ``FakeWindow``, a fake frame clock, and the dummy video driver).

AC-F04-12 (App part), 17, 29 (App part), 34; F09 C6 and AC-F09-40 (the wiring), F10 I-8 (the
stage is emptied before a new game).
"""

import logging
import os
import sys
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app.app import App
from engine.app.loading import story_load_screen
from engine.app.menus import reset_in_game
from engine.app.story import install_stage, install_story
from engine.core.config import load_config
from engine.core.constants import MB
from engine.core.paths import GamePaths
from engine.core.timing import GameTime
from engine.render.assets import AssetManager
from engine.runtime.commands import Flash, PrefetchImages, Shake, ShowStage, StoryWait
from engine.runtime.images import ImageIndex
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.runtime.stage import EMPTY_STAGE, StageState
from engine.ui.builtin.stage_screen import StageScreen
from engine.ui.screen import Screen
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fake_window import FakeWindow
from tests.fakes.loop import FakeClock, ScriptedLimiter, post_key
from tests.fixtures.F04 import gen_images as gen
from tests.runtime.story import load_r

pytestmark = pytest.mark.display

NO_TITLE = '[game]\ntitle = "Stage"\n\n[title]\nenabled = false\n'


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def make_game(root: Path, script: str, images: dict | None = None, config: str = "") -> Path:
    (root / "script").mkdir(parents=True)
    (root / "config.toml").write_text(NO_TITLE + config, encoding="utf-8")
    (root / "script" / "main.vns").write_text(script, encoding="utf-8")
    gen.write(root, images or {})
    return root


class Played:
    """One in-process session of a game folder: each presented frame's (frame number, the
    textbox's line, probe pixels)."""

    def __init__(self, root: Path, *, probes=(), dev: bool = True, last: int = 120,
                 on_frame=None) -> None:
        paths = GamePaths.for_game(root)
        config = load_config(paths).config
        self.frames: list[tuple[int, str | None, dict]] = []
        self.window = FakeWindow((1280, 720), probe_points=probes, on_flip=self._flipped)
        clock = FakeClock()
        self.limiter = ScriptedLimiter(clock)
        assets = AssetManager(paths, budget_bytes=256 * MB, scale_filter="smooth",
                              time=GameTime(), format_source=self.window.framebuffer)
        self.app = App(config=config, paths=paths, window=self.window, assets=assets, log=None,
                       dev=dev, bench_seconds=None, clock=clock, limiter=self.limiter)
        self.app.screens.replace_all([story_load_screen(
            self.app, paths, on_ready=bootstrap.build_initial_screens)])
        for frame in range(1, last):
            self.limiter.at(frame, lambda: on_frame(self) if on_frame else None)
        self.limiter.quit_at(last)
        self.code = self.app.run()

    def _flipped(self, window: FakeWindow) -> None:
        textbox = self.app.textbox
        line = textbox.line.text if textbox is not None and textbox.line is not None else None
        self.frames.append((self.limiter.frame, line, dict(window.flips[-1].probes)))

    @property
    def line(self) -> str | None:
        textbox = self.app.textbox
        return None if textbox is None or textbox.line is None else textbox.line.text


# --- install_stage, in_game_screens, LoadOptions -------------------------------------------------

def test_install_stage_builds_one_stage_screen_per_launch(tmp_path):
    root = make_game(tmp_path / "g", 'label start:\n    "One."\n')
    played = Played(root, last=8)
    app = played.app
    stage_screen = app.stage_screen
    assert isinstance(stage_screen, StageScreen) and stage_screen.in_game and stage_screen.opaque
    assert app.router._handlers[ShowStage] == stage_screen.show_stage          # F09 C6
    assert app.router._handlers[PrefetchImages] == stage_screen.view.prefetch
    # AC-F09-40: F09's handlers, the idle advance, and in_game.
    assert app.router._handlers[StoryWait] == stage_screen.start_wait
    assert app.router._handlers[Shake] == stage_screen.shake
    assert app.router._handlers[Flash] == stage_screen.flash
    assert app.textbox.on_idle_advance == stage_screen.press
    assert not Screen().in_game and app.textbox.in_game
    screens = bootstrap.in_game_screens(app)
    assert screens == [stage_screen, app.textbox]                     # layer 1, then the line
    assert bootstrap.in_game_screens(app)[0] is stage_screen          # one per launch
    assert stage_screen.view.art_height == app.config.stage.art_height
    # F10 I-8: emptied before a new game and on the way to the title.
    stage_screen.show_stage(ShowStage(StageState("bg x")))
    reset_in_game(app)
    assert stage_screen.view.stage == EMPTY_STAGE


def test_install_story_registers_the_stage_once(tmp_path):
    class FakeApp:
        def __init__(self):
            from engine.app.dispatch import CommandRouter
            from engine.core.config_schema import Config
            from engine.ui.screen import ScreenStack
            from tests.render.conftest import make_assets

            self.router = CommandRouter()
            self.config = Config()
            self.assets = make_assets(None)
            self.screens = ScreenStack()
            self.story = None
            self.shell = None
            self.dev = True
            self.start = None

        def add_quit_guard(self, guard):
            pass

        def request_quit(self):
            pass

    app = FakeApp()
    program = load_r(tmp_path)
    install_story(app, Interpreter(program, run_launch(program).namespace), fixed_seed=1)
    assert isinstance(app.stage_screen, StageScreen)
    assert app.stage_screen.view.index.get("black") is not None       # built-in black only
    with pytest.raises(ValueError):
        install_stage(app, ImageIndex({}))                             # one handler per type


def test_author_positions_reach_the_load(tmp_path):
    """Bootstrap's ``LoadOptions(position_names=...)``: ``at`` may name a
    ``[stage.positions]`` entry (no E120), and it draws there."""
    color = (0x30, 0xE0, 0x30)
    root = make_game(tmp_path / "g", 'label start:\n    show g at spot\n    "One."\n',
                     {"images/g.png": gen.block(100, 200, color)},
                     "\n[stage.positions]\nspot = [200, 300]\n")
    played = Played(root, probes=[(200, 200)], last=20)
    assert not played.app.error_mode
    seen = [p for _, line, p in played.frames if line == "One."]
    assert seen and seen[0][(200, 200)] == color


# --- AC-F04-17 — the frame changes all at once ----------------------------------------------

def test_ac_f04_17_the_frame_changes_all_at_once(tmp_path):
    """Fixture ``cut/``. The green block is 100×400 (top at y 320), probed at (320, 400)
    above F05's textbox (box top y 504)."""
    root = make_game(tmp_path / "cut", 'label start:\n    "One."\n    scene bg red\n'
                     '    show block_green at left\n    "Two."\n',
                     {"images/bg/red.png": gen.block(1280, 720, gen.RED),
                      "images/block_green.png": gen.block(100, 400, gen.GREEN)})
    posted = {}

    def on_frame(p: Played) -> None:
        if p.line == "One." and "frame" not in posted and p.limiter.frame >= 10:
            posted["frame"] = p.limiter.frame
            post_key(pygame.K_SPACE)

    played = Played(root, probes=[(100, 100), (320, 400)], on_frame=on_frame, last=40)
    n = posted["frame"]
    by_frame = {frame: (line, probes) for frame, line, probes in played.frames}
    assert by_frame[n][0] == "Two."
    assert by_frame[n][1] == {(100, 100): gen.RED, (320, 400): gen.GREEN}
    before = [(line, probes) for frame, line, probes in played.frames if frame < n and line]
    assert before and all(line == "One." and probes[(100, 100)] == (0, 0, 0)
                          for line, probes in before)
    for _, _, probes in played.frames:
        assert not (probes[(100, 100)] == gen.RED and probes[(320, 400)] != gen.GREEN)


# --- AC-F04-29 (App part) — the textbox over the stage ----------------------------------------
# F05 step 6 retired this AC's stand-in band clause (C2 f); the line screen above layer 100 is
# now F05's textbox.

def test_ac_f04_29_the_textbox_draws_over_layer_100(tmp_path):
    # F11's Q.Save and Q.Load widen the pill past x 460: keep F10's and F13's buttons only.
    root = make_game(tmp_path / "g", 'label start:\n    show b at 640 layer 100\n'
                     '    "Over the stage."\n',
                     {"images/b.png": gen.block(400, 600, gen.GREEN)},
                     '[quick_menu]\nentries = ["history", "hide", "menu"]\n')
    played = Played(root, probes=[(640, 300), (460, 700), (1000, 600), (640, 504)], last=20)
    shown = [p for _, line, p in played.frames if line == "Over the stage."]
    assert shown
    probes = shown[0]
    assert probes[(640, 300)] == gen.GREEN                     # the stage above the box
    # Below the box: the sprite (x 460, left of F10's quick-menu pill at x 640).
    assert probes[(460, 700)] == gen.GREEN
    assert probes[(640, 504)] == (0xF0, 0xA0, 0xC0)            # the box border over it
    fill = (0xFF, 0xF4, 0xF8)                                  # the box fill at 0.80 over it
    assert all(abs(p - round(f * 0.8 + g * 0.2)) <= 1
               for p, f, g in zip(probes[(1000, 600)], fill, (0, 0, 0)))


# --- AC-F04-12 (App part) — words that changed nothing, in dev runs only ----------------------

@pytest.mark.parametrize("dev", [True, False], ids=["dev", "release"])
def test_ac_f04_12_dev_runs_only(tmp_path, caplog, dev):
    root = make_game(tmp_path / "g", 'define hana = Character("Hana")\nlabel start:\n'
                     '    hana pout "Hi."\n    hana pout "Hi."\n')

    def on_frame(p: Played) -> None:
        if p.line and p.limiter.frame % 4 == 0:
            post_key(pygame.K_SPACE)

    with caplog.at_level(logging.DEBUG, logger="vn"):
        Played(root, dev=dev, on_frame=on_frame, last=60)
    # INFO only: step 6's launch check also logs its W13 for these lines (area ``stage``).
    infos = [r.getMessage() for r in caplog.records
             if r.name == "vn.stage" and r.levelno == logging.INFO]
    text = "hana's words \"pout\" changed nothing, because hana isn't on stage."
    assert infos == ([f"script/main.vns, line 3: {text}", f"script/main.vns, line 4: {text}"]
                     if dev else [])


# --- AC-F04-34 — bad art never stops the game ---------------------------------------------------

BAD_ART = {
    # row: (image name, extra top lines, files, expected label, F01 log fragment or None)
    "unknown": ("hana hapy", "", {}, "no image: hana hapy", None),
    "empty_file": ("hana hapy", "", {"images/hana/hapy.png": b""}, "images/hana/hapy.png",
                   "could not read image images/hana/hapy.png"),
    "too_large": ("hana big", 'image hana big = "art/big.png"\n',
                  {"art/big.png": gen.header_only(60000, 60000)}, "art/big.png",
                  "image too large: art/big.png"),
    "folder": ("hana dir", "", {}, "no image: hana dir", None),
    "locked": ("hana locked", "", {"images/hana/locked.png": gen.block(64, 64, (200, 80, 80))},
               "images/hana/locked.png", "could not read images/hana/locked.png"),
}
# The mode-000 row is POSIX only (as test_assets.py's test_unreadable_image).
BAD_ART_ROWS = [pytest.param(row, marks=pytest.mark.skipif(
    sys.platform == "win32", reason="mode 000 does not block reads on Windows"))
    if row == "locked" else row for row in sorted(BAD_ART)]


@pytest.mark.parametrize("dev", [True, False], ids=["dev", "release"])
@pytest.mark.parametrize("use", ["sprite", "background"])
@pytest.mark.parametrize("row", BAD_ART_ROWS)
def test_ac_f04_34_bad_art_never_stops_the_game(tmp_path, monkeypatch, caplog, row, use, dev):
    name, top, files, label, log = BAD_ART[row]
    statement = f"show {name}" if use == "sprite" else f"scene {name}"
    root = make_game(tmp_path / "g", f'{top}label start:\n    {statement}\n    "Line."\n'
                     '    "End."\n', files)
    if row == "folder":
        (root / "images" / "hana" / "dir.png").mkdir(parents=True)
    if row == "locked":
        locked = root / "images" / "hana" / "locked.png"
        locked.chmod(0)
        if os.access(locked, os.R_OK):
            locked.chmod(0o644)
            pytest.skip("running with permission to read mode-000 files")
    loads = []
    real_load = pygame.image.load
    monkeypatch.setattr(pygame.image, "load", lambda *a, **k: loads.append(a) or real_load(*a, **k))
    seen = {}

    def on_frame(p: Played) -> None:
        if p.line == "Line.":
            seen["line"] = seen.get("line", 0) + 1
            if seen["line"] == 12:
                post_key(pygame.K_SPACE)
        elif p.line == "End." and "end" not in seen:
            seen["end"] = p.limiter.frame
            post_key(pygame.K_SPACE)

    with caplog.at_level(logging.DEBUG, logger="vn"), spy_draw_text(monkeypatch) as calls:
        played = Played(root, dev=dev, on_frame=on_frame, last=200)
    assert played.code == 0 and not played.app.error_mode
    assert seen["line"] >= 12 and "end" in seen                 # ≥ 10 frames after the line
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert not any("Traceback" in r.getMessage() for r in caplog.records)
    assert label in [c.text for c in calls]                    # the placeholder showed
    asset_lines = [r.getMessage() for r in caplog.records if r.name == "vn.assets"
                   and r.levelno >= logging.WARNING]
    if log is None:
        assert asset_lines == []
    else:
        assert len(asset_lines) == 1 and log in asset_lines[0], asset_lines
    if row == "too_large":
        assert loads == []                                     # never decoded


# --- The step 5 milestone: the stage demo plays to the end ---------------------------------

def test_stage_demo_plays_to_the_end(tmp_path, caplog):
    from tests.fixtures.F04.make_stage_demo import write_demo

    root = tmp_path / "demo"
    write_demo(root)
    pygame.init()                                   # write_demo quits pygame when done
    with (root / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[title]\nenabled = false\n")
    lines: list[str] = []

    def on_frame(p: Played) -> None:
        if p.line and (not lines or lines[-1] != p.line):
            lines.append(p.line)
        if p.line and p.limiter.frame % 3 == 0:
            post_key(pygame.K_SPACE)

    with caplog.at_level(logging.WARNING, logger="vn"):
        played = Played(root, on_frame=on_frame, last=200, probes=[(640, 100)])
    assert played.code == 0 and not played.app.error_mode
    # The demo's ghost has no art on purpose; step 6's launch check says so, once.
    assert [r.getMessage() for r in caplog.records] == [
        'script/main.vns, line 22: there is no image "ghost", so a placeholder will show. '
        "Add images/ghost.png, or check the spelling."]
    assert len(lines) == 9 and lines[-1].startswith("That's the stage.")
    colors = {probes[(640, 100)] for _, line, probes in played.frames if line}
    assert len(colors) >= 3                         # river, a sprite's face, dusk


# --- AC-F04-46 — stage output carries no identity (F04 step 6: the launch warnings) ------------

LONG_WORDS = ["w" + c * 59 for c in "abcde"]                  # 5 words of 60 characters
LONG_NAME = " ".join(LONG_WORDS)
AC46_SCRIPT = (
    'define hana = Character("Hana")\n'
    'define kaito = Character("Kaito")\n'
    'image bg festival = "art/festival_final.png"\n'
    "label start:\n"
    "    scene bg nowhere\n"
    f"    show {LONG_NAME} at left\n"
    "    show hana hapy at right\n"
    "    show stall\n"
    "    show hana behind stal\n"
    '    kaito pout "Hi."\n'
    '    "End."\n')
AC46_FILES = {
    "images/stall.png": gen.block(100, 200, (0x30, 0xE0, 0x30)),
    "images/hana/happy.png": b"", "images/hana/happy.webp": b"",          # W11
    "images/bg/bridge-day.png": b"", "images/hana/happy\u202e.png": b"",  # W10
    "art/festival-final.png": b"",                                        # W12b's suggestion
}


def test_ac_f04_46_stage_output_carries_no_identity(tmp_path, user_roots, scripted_app,
                                                    monkeypatch, capfd):
    """The launch warnings W10, W11, W12, W12b, W13, W16 and the placeholder labels of a
    missing sprite and background, from a game under ``qauser7/vn/game`` in a dev run, pass
    privacy check P on every channel and show game-relative refs. (The W15 restore of the
    AC is step 5's run-time text and is not played here.)"""
    from engine.core.redact import echo
    from tests.fakes.privacy import capture_channels, check_p

    root = make_game(user_roots.home / "vn" / "game", AC46_SCRIPT, AC46_FILES)
    scripted_app.quit_frame = 40
    with capture_channels(monkeypatch) as channels:
        code = bootstrap.launch(root, release=False, bench_seconds=None,
                                log_level_override=None, pygame_warning=None)
    assert code == 0
    log = (root / "logs" / "latest.log").read_text(encoding="utf-8")
    stage_lines = [line for line in log.splitlines() if " stage " in line[:48]]
    joined = "\n".join(stage_lines) + "\n" + log
    for part in ("Some image files have names a script can't use:",
                 "images/bg/bridge-day.png: rename it bridge_day.png",
                 "images/hana/happy\\u202e.png: rename it",
                 'images/hana/happy.png and images/hana/happy.webp both give the image',
                 'script/main.vns, line 3: image bg festival uses "art/festival_final.png"',
                 'Did you mean "art/festival-final.png"?',
                 'script/main.vns, line 7: there is no image "hana hapy"',
                 "script/main.vns, line 9: behind stal:",
                 "script/main.vns, line 10: kaito's line has the word \"pout\""):
        assert part in joined, part
    assert "\u202e" not in log
    shown = echo(LONG_NAME)
    assert len(shown) == 120 and shown.endswith("…")
    assert f'there is no image "{shown}"' in log
    labels = [c.text for c in channels.draws]
    assert f"no image: {shown}" in labels and "no image: bg nowhere" in labels
    texts = channels.texts() + [capfd.readouterr().err]
    texts += [p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*.log")]
    check_p(texts, home=user_roots.home, game=root)
