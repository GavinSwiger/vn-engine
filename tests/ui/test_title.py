"""F10 step 6 — the shell and the title on a real ``GameShell`` built by ``install_ui`` over a
small fake App (no frame loop): AC-F10-23, 24, 26 (the title row), 33, 34, 35, the sampler
rows of AC-F10-08, the title rows of AC-F10-47, and the shell's story-end and New Game rules
(``04`` §7.7). App F runs of the same flows (the real loop, story, and textbox) are in
``tests/app/test_ui_flow.py``.

Frames run as ``App`` runs them (``UiHarness``: events, ``update(1/60)``, draw on a 1280×720
canvas), so one unit is one pixel. Template F's ``template_min/`` config (I-20) gives the
game title "Example Visual Novel" and version "0.1.0"; art comes from
``tests/fixtures/F10/gen_ui_images.py`` in a temporary copy.
"""

import logging
import shutil
from pathlib import Path

import pygame
import pytest

from engine.app.dispatch import CommandRouter
from engine.app.menus import install_ui
from engine.app.text_check import install_textbox
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime.commands import StoryEnded
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.sampler import SamplerScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.input import UiEvent
from engine.ui.menu_screen import CursorKeeper
from engine.ui.nav import InputKind
from engine.ui.screen import ScreenStack
from engine.ui.shell import Mode
from tests.fakes.audio_spy import AudioSpy
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import UiHarness
from tests.fixtures.F10.gen_ui_images import generate
from tests.render.conftest import make_assets

H = UiHarness
REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "tests" / "fixtures" / "F10" / "template_min"
NEW_GAME = (80, 288, 320, 56)
QUIT = (80, 356, 320, 56)
FADE_IN_FRAMES = 30
CHECKER = {(0xFF, 0x00, 0xFF), (0x00, 0x00, 0x00), (0x20, 0x20, 0x20)}


class FakeStory:
    def __init__(self) -> None:
        self.new_games = 0
        self.posted: list = []

    def new_game(self) -> None:
        self.new_games += 1

    def post(self, event) -> None:
        self.posted.append(event)


class FakeApp:
    """What ``install_ui`` reads of the ``App``."""

    def __init__(self, config, assets, *, dev: bool = True, start=None, audio=None) -> None:
        self.config = config
        self.assets = assets
        self.dev = dev
        self.start = start
        self.screens = ScreenStack()
        self.router = CommandRouter()
        self.story = FakeStory()
        self.shell = None
        self.quits = 0
        self.guards: list = []
        if audio is not None:
            self.audio = audio

    def add_quit_guard(self, guard) -> None:
        self.guards.append(guard)

    def request_quit(self, *, force: bool = False) -> None:
        """As ``App.request_quit``: each guard may veto (step 7's quit guard asks first in
        game); ``quits`` counts the quits that went through."""
        if not force and not all(guard() for guard in list(self.guards)):
            return
        self.quits += 1


def make_game(tmp_path: Path, config: str = "", *, art: bool = False) -> Path:
    root = Path(shutil.copytree(TEMPLATE, tmp_path / "game"))
    if config:
        with (root / "config.toml").open("a", encoding="utf-8") as f:
            f.write("\n" + config + "\n")
    if art:
        generate(root)
    return root


class Rig:
    """A launched title: the fake App, its shell, and a harness over the shell's stack."""

    def __init__(self, tmp_path: Path, config: str = "", *, art: bool = False,
                 dev: bool = True, audio=None, reduce: bool = False, start=None) -> None:
        root = make_game(tmp_path, config, art=art)
        paths = GamePaths.for_game(root)
        loaded = load_config(paths)
        assert not loaded.errors, [e.format() for e in loaded.errors]
        self.assets = make_assets(paths)
        self.app = FakeApp(loaded.config, self.assets, dev=dev, start=start, audio=audio)
        install_textbox(self.app)                          # F05: the overlay host (C5)
        self.shell = install_ui(self.app)
        self.shell.cursor = CursorKeeper(lambda visible: None)
        self.shell.reduce_motion = reduce
        self.shell.check_entries()
        self.h = UiHarness(self.shell)
        self.app.screens.replace_all(self.shell.initial_screens())

    @property
    def stack(self) -> list:
        return list(self.app.screens)

    @property
    def title(self) -> TitleScreen:
        top = self.app.screens.top
        assert isinstance(top, TitleScreen)
        return top

    def frame(self, *events):
        return self.h.frame(*events)

    def frames(self, n: int):
        return self.h.frames(n)

    def px(self, x, y):
        return self.h.px(x, y)


def close(a, b, tol=2) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def over(fg, a, bg) -> tuple[int, int, int]:
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg, bg))


# Tables are loops in one test (several rigs where the config differs), not ``parametrize``:
# every ``tests/ui`` test pays for ``pygame.init()``/``quit()`` (test-review-F10.md).

# --- AC-F10-33 — launch to the title ------------------------------------------------------

def test_ac33_launch_back_start_wheel_and_quit(tmp_path):
    rig = Rig(tmp_path)
    assert [type(s) for s in rig.stack] == [TitleScreen]
    assert rig.shell.mode is Mode.TITLE and rig.app.story.new_games == 0
    rig.frame()
    title = rig.title
    assert [b.label() for b in title.buttons] == ["New Game", "Quit"]
    assert [(b.box.x, b.box.y, b.box.w, b.box.h) for b in title.buttons] == [NEW_GAME, QUIT]
    assert title.scope.focused is None                    # nothing focused yet
    rig.frame(H.key(pygame.K_DOWN))                       # first navigation: focus, no move
    assert title.scope.focused is title.buttons[0] and title.scope.visible
    for name, event in (
        ("esc", H.key(pygame.K_ESCAPE)), ("right-down", H.down((640, 360), 3)),
        ("right-up", H.up((640, 360), 3)), ("east", H.pad(pygame.CONTROLLER_BUTTON_B)),
        ("start", H.pad(pygame.CONTROLLER_BUTTON_START)),
        ("wheel-down", H.wheel((240, 316), -1)), ("wheel-up", H.wheel((240, 316), 1)),
    ):
        rig.frame(event)
        rig.frames(2)
        assert rig.stack == [title] and rig.shell.mode is Mode.TITLE, name
        assert title.scope.focused is title.buttons[0] and rig.app.quits == 0, name
        assert rig.app.story.new_games == 0, name
    rig.h.click((240, 384))                               # Quit
    assert rig.app.quits == 1


# --- New Game (04 §7.7.2): fade, no input, then the cut -----------------------------------------

def test_new_game_fades_without_input_then_cuts_to_the_game(tmp_path):
    rig = Rig(tmp_path)
    rig.frames(FADE_IN_FRAMES + 1)
    before = rig.px(1000, 100)
    rig.frame(H.key(pygame.K_RETURN))                     # focuses New Game
    rig.frame(H.key(pygame.K_RETURN))                     # frame N: activates it
    assert rig.shell.mode is Mode.ENDING and rig.title.leaving
    shades = [rig.px(1000, 100)]
    for k in range(1, 9):
        rig.frame(H.key(pygame.K_ESCAPE), H.down((240, 316)), H.up((240, 316)),
                  H.key(pygame.K_RETURN))
        shades.append(rig.px(1000, 100))
        assert rig.app.story.new_games == 0, k
    assert shades[0] == before
    for k, shade in enumerate(shades):                    # falls linearly over 9 frames
        expected = tuple(round(c * (1 - k / 9)) for c in before)
        assert close(shade, expected, 3), (k, shade, expected)
    rig.frame()                                           # frame N + 9: the cut
    assert rig.app.story.new_games == 1
    assert [type(s) for s in rig.stack] == [TextboxScreen]
    assert rig.shell.mode is Mode.GAME and rig.app.quits == 0


def test_reduced_motion_new_game_and_story_end_cut_at_once(tmp_path, caplog):
    """New Game and the story end are cuts under reduced motion; in-game resets run before
    ``new_game``; a ``StoryEnded`` in title mode is ignored with a DEBUG line."""
    rig = Rig(tmp_path, reduce=True)
    order = []
    rig.shell.add_in_game_reset(lambda: order.append("f15"))
    real = rig.shell.ports.new_game
    object.__setattr__(rig.shell.ports, "new_game", lambda: (order.append("new"), real()))
    rig.frame()
    assert rig.title.darkness == 0                        # no fade-in either
    rig.frame(H.key(pygame.K_RETURN))
    rig.frame(H.key(pygame.K_RETURN))
    assert rig.app.story.new_games == 1 and [type(s) for s in rig.stack] == [TextboxScreen]
    assert order == ["f15", "new"]
    rig.shell.story_ended(StoryEnded())
    assert [type(s) for s in rig.stack] == [TitleScreen] and rig.title.darkness == 0
    with caplog.at_level(logging.DEBUG, logger="vn.ui"):
        rig.shell.story_ended(StoryEnded())
    assert [type(s) for s in rig.stack] == [TitleScreen] and rig.shell.mode is Mode.TITLE
    assert any(r.levelno == logging.DEBUG and "StoryEnded ignored" in r.getMessage()
               for r in caplog.records)


# --- AC-F10-34 — title without art; AC-F10-36's version pill ------------------------------------

def test_ac34_title_without_art_and_ac36_version_pill(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    with spy_draw_text(monkeypatch) as calls:
        rig.frames(FADE_IN_FRAMES + 1)
        calls.clear()
        rig.frame()
    assert close(rig.px(1000, 0), (0xFF, 0xF4, 0xF8))
    assert close(rig.px(1000, 719), (0xFF, 0xD6, 0xE8))
    assert close(rig.px(1000, 360), (255, 229, 240))
    titles = [c for c in calls if c.text.replace("\n", " ") == "Example Visual Novel"]
    assert len(titles) == 1
    call = titles[0]
    assert call.font.size == 64 and call.color == (0xA0, 0x28, 0x60)
    assert call.font.bundled.name == "BOLD"
    left, top, _, height = call.bounds
    assert left == 80 and abs(top + height / 2 - 148) <= 1
    assert call.text.count("\n") <= 1
    assert rig.px(70, 148) == rig.px(1000, 148)            # no backing panel
    for i in range(8):
        for j in range(8):
            pixel = rig.px(40 + i * 160, 20 + j * 90)
            assert pixel not in CHECKER, (i, j, pixel)
    (call,) = [c for c in calls if c.text == "0.1.0"]      # the version pill
    assert call.font.size == 20 and call.color == (0x6E, 0x5E, 0x68)
    left, top, width, height = call.bounds
    assert abs(left + width + 8 - 1264) <= 1 and abs(top + height / 2 - (708 - 14)) <= 1
    rig2 = Rig(tmp_path / "b", "[title]\nshow_version = false")
    with spy_draw_text(monkeypatch) as calls:
        rig2.frames(2)
    assert not [c for c in calls if c.text == "0.1.0"]


# --- AC-F10-35 — title art and logo -------------------------------------------------------------

def test_ac35_title_art_and_logo(tmp_path, monkeypatch):
    art, logo = (40, 120, 200), (250, 200, 0)
    # A full-size background, no logo: it covers the canvas and the title text gets a backing.
    rig = Rig(tmp_path / "bg", '[theme.title]\nbackground_image = "gui/title_bg.png"', art=True)
    with spy_draw_text(monkeypatch) as calls:
        rig.frames(FADE_IN_FRAMES + 1)
    assert rig.px(1000, 600) == art
    call = [c for c in calls if c.text.replace("\n", " ") == "Example Visual Novel"][-1]
    left, top, width, height = call.bounds
    assert rig.px(left - 30, top + height / 2) == art             # outside the backing
    inside = rig.px(left - 12, top + height / 2)                   # backing, beside the text
    assert close(inside, over((0xFF, 0xF4, 0xF8), 0.94, art), 3)
    assert rig.px(left + width + 30, top + height / 2) == art
    assert rig.px(left + width + 12, top + height / 2) != art
    # A wide background is cropped, not stretched; the logo is scaled down to its box.
    rig = Rig(tmp_path / "wide", '[theme.title]\nbackground_image = "gui/title_wide.png"\n'
              'logo_image = "gui/logo.png"', art=True)
    rig.frames(FADE_IN_FRAMES + 1)
    assert close(rig.px(5, 5), art) and close(rig.px(1275, 715), art)
    # 560×140 at x 80–640, y 78–218 (smoothscale's downscale rounds a uniform fill down by
    # up to 3 per channel: pygame-ce 2.5.8 gives (247, 198, 0)).
    assert close(rig.px(360, 148), logo, 4)
    assert close(rig.px(84, 82), logo, 4) and close(rig.px(636, 214), logo, 4)
    assert not close(rig.px(360, 74), logo, 20) and not close(rig.px(650, 148), logo, 20)
    assert not close(rig.px(360, 222), logo, 20)
    # A small logo is never scaled up.
    rig = Rig(tmp_path / "small", '[theme.title]\nlogo_image = "gui/logo_small.png"', art=True)
    rig.frames(FADE_IN_FRAMES + 1)
    assert close(rig.px(84, 102), logo, 4) and close(rig.px(276, 194), logo, 4)
    assert not close(rig.px(290, 148), logo, 20) and not close(rig.px(180, 95), logo, 20)
    assert not close(rig.px(180, 201), logo, 20)


# --- AC-F10-23 — images and fonts fall back ----------------------------------------------------

def test_ac23_button_frame_images(tmp_path):
    rig = Rig(tmp_path / "all", '[theme.button]\nframe_image = "gui/button.png"', art=True)
    rig.frames(FADE_IN_FRAMES + 1)
    x, y, w, h = NEW_GAME
    for (px, py), color in (((x + 2, y + 2), (255, 0, 0)), ((x + 160, y + 2), (0, 255, 0)),
                            ((x + 160, y + 28), (0, 0, 255))):
        backdrop = rig.px(1000, py)                                # the gradient at that row
        assert close(rig.px(px, py), over(color, 0.9, backdrop), 3), (px, py)
    rig = Rig(tmp_path / "focused", '[theme.button.focused]\nframe_image = "gui/button.png"',
              art=True)
    rig.frames(FADE_IN_FRAMES + 1)
    rig.frame(H.key(pygame.K_DOWN))                                # New Game focused
    backdrop = rig.px(1000, 290)
    assert close(rig.px(240, 290), over((0, 255, 0), 0.9, backdrop), 3)
    normal = rig.px(240, 360)                                      # Quit: the drawn look
    assert not close(normal, over((0, 255, 0), 0.9, rig.px(1000, 360)), 20)


def test_ac23_missing_or_bad_images_fall_back(tmp_path, caplog, monkeypatch):
    x, y, w, h = NEW_GAME
    for ref in ("gui/buton.png", "gui/bad.png"):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="vn.ui"):
            rig = Rig(tmp_path / ref[4:7], f'[theme.button]\nframe_image = "{ref}"', art=True)
            rig.frames(FADE_IN_FRAMES + 1)
        w64 = [r for r in caplog.records if r.name == "vn.ui" and getattr(r, "code", "") == "W64"]
        assert len(w64) == 1, ref
        for i in range(0, 320, 8):
            for j in range(0, 56, 4):
                assert rig.px(x + i, y + j) not in CHECKER, ref
        # The drawn look: the default fill #FFF4F8 at 0.90 over the gradient.
        assert close(rig.px(x + 160, y + 28),
                     over((0xFF, 0xF4, 0xF8), 0.9, rig.px(1000, y + 28)), 3), ref
    # A missing logo and background: the title text and the gradient; AC-F10-24's background
    # row (the W64 text starts with its fixed part, G1).
    caplog.clear()
    config = ('[theme.title]\nlogo_image = "gui/nologo.png"\n'
              'background_image = "gui/title_bg.png"')
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        rig = Rig(tmp_path / "title", config)
    with spy_draw_text(monkeypatch) as calls:
        rig.frames(FADE_IN_FRAMES + 1)
    assert any(c.text.replace("\n", " ") == "Example Visual Novel" for c in calls)
    assert close(rig.px(1000, 0), (0xFF, 0xF4, 0xF8))              # the gradient
    messages = [r.getMessage() for r in caplog.records if getattr(r, "code", "") == "W64"]
    assert [m for m in messages if m.startswith(
        'config.toml: [theme.title] background_image "gui/title_bg.png" doesn\'t exist')]


# --- AC-F10-24 — W64 texts at install_ui, once ----------------------------------------------

FRAME_W64 = ('config.toml: [theme.button] frame_image "gui/buton.png" doesn\'t exist, so the '
             'drawn button is used. Did you mean "gui/button.png"?')
FONT_W64 = ('config.toml: [theme.ui] text_font "fonts/Lora.ttf" couldn\'t be read as a font, so '
            'the text box font is used.')
LOGO_W64 = ('config.toml: [theme.title] logo_image "gui/logo.png" doesn\'t exist, so the game\'s '
            'title is shown as text.')
W64_ROWS = [
    # The frame and font rows share one config (both need the generated art).
    ('[theme.button]\nframe_image = "gui/buton.png"\n[theme.ui]\ntext_font = "fonts/Lora.ttf"',
     True, [FRAME_W64, FONT_W64]),
    ('[theme.title]\nlogo_image = "gui/logo.png"', False, [LOGO_W64]),
]


def test_ac24_w64_texts_once_in_dev_and_release(tmp_path, caplog, monkeypatch):
    for n, (config, art, texts) in enumerate(W64_ROWS):
        for dev in (True, False):
            caplog.clear()
            with caplog.at_level(logging.DEBUG, logger="vn.ui"):
                rig = Rig(tmp_path / f"{n}-{dev}", config, art=art, dev=dev)
                with spy_draw_text(monkeypatch) as calls:
                    rig.frames(3)
                rig.frame(H.key(pygame.K_RETURN))
                rig.frame(H.key(pygame.K_RETURN))
                rig.frames(12)                             # in the game
                rig.shell.story_ended(StoryEnded())
                rig.frames(100)                            # back on the title
                assert isinstance(rig.app.screens.top, TitleScreen)
            w64 = [(r.name, r.levelname, r.getMessage()) for r in caplog.records
                   if getattr(r, "code", "") == "W64"]
            assert sorted(w64) == sorted(("vn.ui", "WARNING", t) for t in texts), (n, dev)
            if art:                                        # AC-F10-23: the textbox face
                labels = [c for c in calls if c.text in ("New Game", "Quit")]
                assert labels and all(c.font.ref is None for c in labels)


# --- AC-F10-26 (title row) and AC-F10-27's W66 at install -------------------------------------

def test_ac26_ac27_title_entries_and_w66(tmp_path, caplog):
    from engine.ui.menus import MenuEntry

    rig = Rig(tmp_path / "order", '[title]\nentries = ["quit", "new_game"]')
    rig.frame()
    assert [b.label() for b in rig.title.buttons] == ["Quit", "New Game"]
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        rig = Rig(tmp_path / "typo", '[title]\nentries = ["new_gam", "quit"]')
    rig.frame()
    (record,) = [r for r in caplog.records if getattr(r, "code", "") == "W66"]
    assert record.getMessage().startswith('config.toml: [title] entries has "new_gam"')
    assert 'Did you mean "new_game"?' in record.getMessage()
    assert [b.label() for b in rig.title.buttons] == ["Quit"]
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        rig = Rig(tmp_path / "empty", "[title]\nentries = []")
    rig.frame()
    assert [getattr(r, "code", "") for r in caplog.records].count("W66") == 1
    assert [b.label() for b in rig.title.buttons] == ["New Game", "Quit"]
    # I-2: entries registered by installs that run after install_ui and before check_entries
    # count (AC-F10-27's late-registration row, title form).
    caplog.clear()
    root = make_game(tmp_path / "late", '[title]\nentries = ["new_game", "load", "quit"]')
    paths = GamePaths.for_game(root)
    app = FakeApp(load_config(paths).config, make_assets(paths))
    install_textbox(app)
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        shell = install_ui(app)
        shell.menus.add("title", MenuEntry("load", action=lambda ctx: None))   # F11's install
        shell.check_entries()
    assert "W66" not in [getattr(r, "code", "") for r in caplog.records]
    assert [e.id for e in shell.menus.shown("title")] == ["new_game", "load", "quit"]


# --- AC-F10-47 — overrides while the title shows ----------------------------------------------
# F32 removed ``UiOverrides.set_title_look``; the title-look row moved to
# ``tests/ui/test_title_playthrough.py`` (AC-F32-14) as a ``[playthrough.0]`` table.

def test_ac47_word_and_hidden_overrides_while_the_title_shows(tmp_path):
    rig = Rig(tmp_path)
    rig.frames(FADE_IN_FRAMES + 1)
    rig.shell.overrides.set_hidden("title", "quit", True)
    rig.shell.overrides.set_word("new_game", "Begin")
    rig.frame()
    assert [b.label() for b in rig.title.buttons] == ["Begin"]
    rig.shell.overrides.clear()
    rig.frame()
    assert [b.label() for b in rig.title.buttons] == ["New Game", "Quit"]


def test_title_music_leaves_with_new_game_and_comes_back(tmp_path):
    audio = AudioSpy()
    rig = Rig(tmp_path, '[theme.title]\nmusic = "title.ogg"', audio=audio)
    rig.frames(3)
    rig.frame(H.key(pygame.K_RETURN))
    rig.frame(H.key(pygame.K_RETURN))
    assert audio.calls[-1] == ("stop", 0.5)
    rig.frames(8)
    assert audio.calls[-1] == ("stop", 0.5)
    rig.frame()                                            # the cut
    assert audio.calls[-1] == ("release",)
    rig.shell.story_ended(StoryEnded())
    assert audio.calls[-1] == ("stop_story_audio", 0.5)
    rig.frames(61)
    assert audio.calls[-2:] == [("take_music", "title"), ("play", "title.ogg", True, 0.0)]


# --- The story's end (04 §7.7.5) on the shell ------------------------------------------------

def test_story_end_fades_then_shows_the_title(tmp_path):
    rig = Rig(tmp_path, reduce=False)
    rig.frame(H.key(pygame.K_RETURN))
    rig.frame(H.key(pygame.K_RETURN))
    rig.frames(10)
    assert rig.shell.mode is Mode.GAME
    rig.shell.story_ended(StoryEnded())
    assert rig.shell.mode is Mode.ENDING
    assert [type(s) for s in rig.stack] == [TextboxScreen, BlackFadeScreen]
    for _ in range(60):                                    # frame N (the push) to N + 59
        rig.frame(H.key(pygame.K_SPACE))
    assert isinstance(rig.app.screens.top, BlackFadeScreen)
    rig.frame(H.key(pygame.K_SPACE))                       # N + 60: the title cuts in
    assert rig.app.story.posted == []                      # no input reached the textbox
    assert [type(s) for s in rig.stack] == [TitleScreen]
    assert rig.shell.mode is Mode.TITLE and rig.title.in_t == 0.0


def test_no_title_and_start_options_skip_the_title(tmp_path):
    from engine.core.startvalues import StartOptions

    rig = Rig(tmp_path / "none", "[title]\nenabled = false")
    assert [type(s) for s in rig.stack] == [TextboxScreen] and rig.shell.mode is Mode.GAME
    assert rig.app.story.new_games == 1
    rig.shell.story_ended(StoryEnded())
    rig.frames(61)
    assert rig.app.quits == 1                              # AC-F10-41: the end quits
    rig = Rig(tmp_path / "start", start=StartOptions("late"))
    assert [type(s) for s in rig.stack] == [TextboxScreen] and rig.app.story.new_games == 1
    rig.shell.story_ended(StoryEnded())
    rig.frames(61)
    assert [type(s) for s in rig.stack] == [TitleScreen]   # AC-F10-39


# --- AC-F10-08 — hold to repeat in the sampler (opened from the title) -----------------------

def open_sampler(tmp_path) -> tuple[Rig, SamplerScreen]:
    rig = Rig(tmp_path)
    rig.frames(2)
    rig.frame(H.key(pygame.K_F3, pygame.KMOD_LSHIFT))
    sampler = rig.app.screens.top
    assert isinstance(sampler, SamplerScreen)
    return rig, sampler


def hold(rig: Rig, down: UiEvent, frames: int, up: UiEvent | None = None) -> None:
    rig.frame(down)
    rig.frames(frames - 1)
    if up is not None:
        rig.frame(up)


def test_ac08_slider_button_and_toggle_and_ac09_dev_only(tmp_path):
    """The list row (hold Down 1.30 s → Row 13) is the App F test in
    ``tests/app/test_ui_flow.py::test_ac08_sampler_from_the_title_and_hold_down``."""
    rig, sampler = open_sampler(tmp_path / "dev")
    sampler.scope.focus(sampler.slider, InputKind.KEYS)
    sampler.value = 0
    hold(rig, H.key(pygame.K_RIGHT), 79, H.key(pygame.K_RIGHT, up=True))   # 1.30 s
    assert sampler.value == 60
    sampler.scope.focus(sampler.live_button, InputKind.KEYS)
    hold(rig, H.key(pygame.K_DOWN), 120, H.key(pygame.K_DOWN, up=True))
    assert sampler.scope.focused is sampler.open_confirm                 # moved once
    calls = []
    real_set = sampler.black_toggle.set
    sampler.black_toggle.set = lambda on: (calls.append(on), real_set(on))
    sampler.scope.focus(sampler.black_toggle, InputKind.KEYS)
    hold(rig, H.key(pygame.K_RIGHT), 120, H.key(pygame.K_RIGHT, up=True))
    assert calls == [True]
    rig.frame(H.key(pygame.K_ESCAPE))
    rig.frames(10)
    assert isinstance(rig.app.screens.top, TitleScreen)
    release = Rig(tmp_path / "r", dev=False)               # AC-F10-09: no sampler without --dev
    release.frame(H.key(pygame.K_F3, pygame.KMOD_LSHIFT))
    assert isinstance(release.app.screens.top, TitleScreen)


def _axis(value: int) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=0,
                                      axis=pygame.CONTROLLER_AXIS_LEFTY, value=value), None,
                   False)


STOPS = {
    "keyup": (H.key(pygame.K_DOWN), H.key(pygame.K_DOWN, up=True)),
    "pad-up": (H.pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN),
               H.pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN, up=True)),
    "stick": (_axis(20_000), _axis(0)),
    "focus-lost": (H.key(pygame.K_DOWN),
                   UiEvent(pygame.event.Event(pygame.WINDOWFOCUSLOST), None, False)),
    "hover-button": (H.key(pygame.K_DOWN), H.motion((200, 500))),
}


def test_ac08_repeat_stops(tmp_path):
    """The AC waits 60 frames after each stop; a repeat that kept running would step every
    5 frames (0.08 s), so the later rows wait 15 (test-review-F10.md)."""
    rig, sampler = open_sampler(tmp_path)
    for n, (name, (press, stop)) in enumerate(STOPS.items()):
        sampler.scope.focus(sampler.list, InputKind.KEYS)
        sampler.list.focus_row = 0
        hold(rig, press, 40, stop)                  # 1 step + 2 or 3 repeats, then the stop
        row = sampler.list.focus_row
        assert row in (3, 4), name
        rig.frames(60 if n == 0 else 15)
        assert sampler.list.focus_row == row, name
    # A confirm pushed on top stops it too.
    sampler.scope.focus(sampler.list, InputKind.KEYS)
    sampler.list.focus_row = 0
    hold(rig, H.key(pygame.K_DOWN), 40)
    sampler.show_confirm()
    row = sampler.list.focus_row
    rig.frames(60)
    assert sampler.list.focus_row == row
