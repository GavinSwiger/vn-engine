"""F33 step 2 — the content warning on a real ``GameShell`` built by ``install_ui`` over the
small fake App of ``test_title.py`` (no frame loop): AC-F33-04 (launch order), 05 (the
"seen" record and Quit), 06 (Continue's wait and the inputs that do nothing), 07 (layout,
focus, scrolling), and 08 (reduced motion, notices) (F33 ``SPEC.md`` §2, §4, §5; ``07``
I-1, I-2, I-9).

Frames run as ``App`` runs them (events, ``update``, draw on a 1280×720 canvas). Timed rows
drive ``ScreenStack.update`` with 50 ms steps: the push frame (``update(0)``, which a fade
skips), the 150 ms fade in three steps, then the wait."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from engine.app import bootstrap
from engine.app.menus import install_ui
from engine.app.settings import SettingsService, launch_settings
from engine.app.text_check import install_textbox
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.persist.settings_file import FILE_NAME
from engine.persist.writer import Writer
from engine.ui import layouts
from engine.ui.builtin import content_warning as cw_module
from engine.ui.builtin.content_warning import (
    PANEL_MAX_H,
    PANEL_W,
    PANEL_X,
    WRAP_WIDTH,
    ContentWarningScreen,
)
from engine.ui.builtin.placeholder import PlaceholderScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.menu_screen import CursorKeeper, Phase
from engine.ui.screen import Screen
from engine.ui.shell import Mode
from tests.fakes.audio_spy import AudioSpy
from tests.fakes.ui_shell import DT, UiHarness
from tests.ui.test_title import FakeApp

H = UiHarness
REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "tests" / "fixtures" / "F10" / "template_min"
SHORT = ("This game is not suitable for children or those who are easily disturbed.\n\n"
         "It contains scenes of self-harm and psychological horror.")
LONG = "\n\n".join(" ".join(f"word{i:02d}" for i in range(n, n + 50)) for n in range(0, 250, 50))
MUSIC = "bgm/title.ogg"
CLICK = "ui/click.ogg"
BACK = "ui/back.ogg"
STEP = 0.05


def warning_config(show: str = "once", text: str = SHORT, *, min_seconds: float = 2,
                   extra: str = "") -> str:
    body = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return (f'[content_warning]\nshow = "{show}"\ntext = "{body}"\nmin_seconds = {min_seconds}\n'
            f'[theme.title]\nmusic = "{MUSIC}"\n[theme.button]\nactivate_sound = "{CLICK}"\n'
            f'[theme.ui]\nback_sound = "{BACK}"\n{extra}')


class Holder(Screen):
    """The story load screen's stand-in while ``install_ui`` runs: it holds notices."""

    holds_notices = True


class Rig:
    """A launched game: the fake App (with an Audio spy), its shell, and the first screens.
    ``settings`` becomes ``App.settings``; ``persist`` has one launch notice when asked."""

    count = 0

    def __init__(self, tmp_path: Path, config: str, *, start=None, reduce: bool = False,
                 settings=None, notice: bool = False, scale: float | None = None,
                 root: Path | None = None) -> None:
        Rig.count += 1
        if root is None:
            root = Path(shutil.copytree(TEMPLATE, tmp_path / f"game{Rig.count}"))
            with (root / "config.toml").open("a", encoding="utf-8") as f:
                f.write("\n" + config + "\n")
        self.root = root
        loaded = load_config(GamePaths.for_game(root))
        assert not loaded.errors, [e.format() for e in loaded.errors]
        from tests.render.conftest import make_assets

        self.audio = AudioSpy()
        self.app = FakeApp(loaded.config, make_assets(GamePaths.for_game(root)), start=start,
                           audio=self.audio)
        if settings is not None:
            self.app.settings = settings(loaded.config)
        if notice:
            self.app.persist = SimpleNamespace(take_notices=lambda: ["W50"],
                                               flush_soon=lambda: None)
            self.app.screens.push(Holder())
        install_textbox(self.app)
        self.shell = install_ui(self.app)
        self.shell.cursor = CursorKeeper(lambda visible: None)
        self.shell.reduce_motion = reduce
        if scale is not None:
            self.shell.painter.set_text_scale(lambda: scale)
        self.h = UiHarness(self.shell)
        self.app.screens.replace_all(self.shell.initial_screens())

    @property
    def types(self) -> list[type]:
        return [type(s) for s in self.app.screens]

    @property
    def warning(self) -> ContentWarningScreen:
        top = self.app.screens.top
        assert isinstance(top, ContentWarningScreen)
        return top

    def send(self, *events) -> None:
        for event in events:
            self.app.screens.handle_event(event)

    def step(self, seconds: float) -> None:
        """Update in 50 ms steps (the notice layer too)."""
        for _ in range(round(seconds / STEP)):
            self.app.screens.update(STEP)
            self.shell.update_layer(STEP, focused=True)

    def open(self) -> None:
        """The push frame, then the fade in: the panel is fully in."""
        self.app.screens.update(0.0)
        self.step(0.15)

    def ready(self, min_seconds: float = 2.0) -> None:
        self.open()
        self.step(min_seconds)
        assert self.warning.ready

    def press(self, key: int) -> None:
        self.send(H.key(key), H.key(key, up=True))

    def pad(self, button: int) -> None:
        self.send(H.pad(button), H.pad(button, up=True))

    def click(self, pos, button: int = 1) -> None:
        self.send(H.motion(pos), H.down(pos, button), H.up(pos, button))

    def sounds(self) -> list[str]:
        return [call[1] for call in self.audio.calls if call[0] == "play_ui"]


def continue_now(rig: Rig) -> None:
    rig.ready()
    rig.press(pygame.K_RETURN)
    rig.step(0.2)                               # the fade to black, then the next screens


# --- AC-F33-04 — launch order ---------------------------------------------------------------

def test_ac_f33_04_launch_order(tmp_path):
    rig = Rig(tmp_path, warning_config())
    assert rig.types == [ContentWarningScreen] and rig.shell.mode is Mode.TITLE
    assert rig.app.story.new_games == 0 and ("take_music", "title") not in rig.audio.calls
    rig.ready()
    rig.press(pygame.K_RETURN)
    assert rig.warning.leaving and rig.types == [ContentWarningScreen]     # fading out
    rig.step(0.2)
    assert rig.types == [TitleScreen] and rig.shell.mode is Mode.TITLE
    title = rig.app.screens.top
    assert title.in_t < 1.0 and ("take_music", "title") in rig.audio.calls  # fades in, music
    assert rig.app.story.new_games == 0
    # I-1: the Main Menu path back to the title, and a second initial_screens(): no warning.
    rig.step(1.0)
    rig.shell.start_new_game()
    rig.step(0.5)
    assert rig.shell.mode is Mode.GAME and rig.app.story.new_games == 1
    rig.shell.return_to_title()
    rig.step(0.5)
    assert rig.types == [TitleScreen]
    assert [type(s) for s in rig.shell.initial_screens()] == [TitleScreen]

    # [title] enabled = false: Continue → new_game() once, then the in-game screens.
    rig = Rig(tmp_path, warning_config(extra="[title]\nenabled = false\n"))
    assert rig.types == [ContentWarningScreen] and rig.app.story.new_games == 0
    continue_now(rig)
    assert rig.app.story.new_games == 1 and rig.shell.mode is Mode.GAME
    assert TextboxScreen in rig.types and ContentWarningScreen not in rig.types

    # Not due: F10's screens unchanged (the title; the game at once with no title).
    assert Rig(tmp_path, warning_config("never")).types == [TitleScreen]
    rig = Rig(tmp_path, warning_config("never", extra="[title]\nenabled = false\n"))
    assert rig.app.story.new_games == 1 and TextboxScreen in rig.types

    # Start options (F44): the game at once, no warning.
    for start in (SimpleNamespace(label="act2", values={}),
                  SimpleNamespace(label=None, values={"x": 1})):
        rig = Rig(tmp_path, warning_config("always"), start=start)
        assert rig.shell.mode is Mode.GAME and rig.app.story.new_games == 1
        assert ContentWarningScreen not in rig.types

    # No story: F01's placeholder.
    app = SimpleNamespace(story=None, shell=None, config=rig.app.config)
    assert [type(s) for s in bootstrap.build_initial_screens(app)] == [PlaceholderScreen]


# --- AC-F33-05 — the "seen" record; Quit ----------------------------------------------------

class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def real_settings(root: Path, clock: Clock):
    def build(config):
        launch = launch_settings(game_root=root, release=False, app_id=None,
                                 id_is_fallback=True)
        return SettingsService(launch.loaded, config, writer=Writer(threaded=False),
                               clock=clock, game_root=root, file=launch.file)
    return build


def test_ac_f33_05_seen_record_and_quit(tmp_path):
    clock = Clock()
    rig = Rig(tmp_path, warning_config("once"), settings=None)
    root = rig.root
    rig = Rig(tmp_path, "", root=root, settings=real_settings(root, clock))
    service = rig.app.settings
    assert rig.types == [ContentWarningScreen]
    continue_now(rig)
    assert service.value("warning_seen") == 1
    clock.now += 1.0
    service.update(clock.now)                       # debounce over: written
    service.update(clock.now)
    data = json.loads((root / "settings" / FILE_NAME).read_text(encoding="utf-8"))
    assert data == {"format": 3, "values": {"warning_seen": 1}}
    relaunch = Rig(tmp_path, "", root=root, settings=real_settings(root, clock))
    assert relaunch.types == [TitleScreen]          # seen: straight to the title

    # "always": shown again, and Continue writes nothing.
    rig = Rig(tmp_path, warning_config("always"), settings=real_settings(tmp_path / "x", clock))
    service = rig.app.settings
    continue_now(rig)
    assert service.stored == {} and not service.dirty

    # Quit: request_quit, quits at once (mode TITLE: the guard lets it through), nothing
    # stored; a window close likewise.
    rig = Rig(tmp_path, warning_config("once"), settings=real_settings(tmp_path / "y", clock))
    rig.open()
    rig.click(rig.warning.quit_button.box.center)
    assert rig.app.quits == 1 and rig.app.settings.stored == {}
    assert ContentWarningScreen in rig.types
    rig = Rig(tmp_path, warning_config("once"), settings=real_settings(tmp_path / "z", clock))
    rig.app.request_quit()                          # the window's close button
    assert rig.app.quits == 1 and rig.app.settings.stored == {}


# --- AC-F33-06 — Continue's wait; inputs that do nothing ------------------------------------

def test_ac_f33_06_wait_and_ignored_inputs(tmp_path):
    def at_2_10() -> Rig:
        rig = Rig(tmp_path, warning_config(min_seconds=2))
        rig.open()                                  # 0.15 s: the fade has ended
        rig.step(1.95)                              # 2.10 s
        return rig

    inputs = {
        "return": lambda rig: rig.press(pygame.K_RETURN),
        "click": lambda rig: rig.click(rig.warning.continue_button.box.center),
        "south": lambda rig: rig.pad(pygame.CONTROLLER_BUTTON_A),
    }
    for name, act in inputs.items():
        rig = at_2_10()
        assert not rig.warning.ready
        act(rig)
        assert not rig.warning.leaving and rig.sounds() == [], name
        rig.step(STEP)                              # 2.15 s
        assert rig.warning.ready, name
        act(rig)
        assert rig.warning.leaving and rig.sounds() == [CLICK], name
        rig.step(0.2)
        assert rig.types == [TitleScreen], name

    # min_seconds 0: ready as soon as the fade has ended.
    rig = Rig(tmp_path, warning_config(min_seconds=0))
    rig.app.screens.update(0.0)
    rig.step(0.1)
    assert rig.warning.phase is Phase.OPENING and not rig.warning.ready
    rig.step(STEP)
    assert rig.warning.ready

    # Esc, right click, gamepad east and Start: nothing (no Back sound); 600 s: still there.
    rig = Rig(tmp_path, warning_config(min_seconds=0))
    rig.ready(0)
    rig.press(pygame.K_ESCAPE)
    rig.click((40, 40), button=3)
    rig.pad(pygame.CONTROLLER_BUTTON_B)
    rig.pad(pygame.CONTROLLER_BUTTON_START)
    rig.press(pygame.K_F3)
    assert rig.sounds() == [] and not rig.warning.leaving
    rig.step(600)
    assert rig.types == [ContentWarningScreen] and rig.app.quits == 0


# --- AC-F33-07 — layout, focus, scrolling ---------------------------------------------------

def test_ac_f33_07_layout_focus_scrolling(tmp_path, monkeypatch):
    widths: list[float] = []
    real_wrap = cw_module.wrap_text

    def spy_wrap(text, width, size, measure):
        widths.append(width)
        return real_wrap(text, width, size, measure)

    monkeypatch.setattr(cw_module, "wrap_text", spy_wrap)
    for scale, text in ((1.0, SHORT), (1.5, SHORT), (1.0, LONG), (1.5, LONG)):
        rig = Rig(tmp_path, warning_config(text=text), scale=scale)
        screen = rig.warning
        lay = screen.layout
        cfg = rig.shell.theme.cfg
        size = layouts.scaled(cfg.panel.text_size, scale)
        p = layouts.pitch(size)
        heading_h = layouts.pitch(layouts.scaled(cfg.panel.heading.text_size, scale))
        h_b = layouts.button_height(cfg.button.text_size, scale=scale, minimum=cfg.button.height)
        panel = lay.panel
        assert (panel.x, panel.w) == (PANEL_X, PANEL_W) == (120, 1040)
        assert panel.y + panel.h / 2 == 360 and panel.h <= PANEL_MAX_H
        assert lay.heading_y == panel.y + 40 and lay.heading_size == layouts.scaled(32, scale)
        assert (lay.body.x, lay.body.w) == (168, 944)
        assert lay.body.y == lay.heading_y + heading_h + 24
        assert lay.body_size == size and lay.pitch == p and lay.gap == round(p / 2)
        assert list(lay.heights[:-1]) == [len(r) * p + lay.gap for r in lay.rows[:-1]]
        assert lay.heights[-1] == len(lay.rows[-1]) * p
        assert len(lay.rows) == len([t for t in text.split("\n\n")])
        row = (lay.continue_, lay.quit)
        assert all(b.y == lay.body.bottom + 32 and b.h == h_b and b.w >= 200 for b in row)
        assert lay.quit.x - lay.continue_.right == cfg.button.gap
        assert (lay.continue_.x + lay.quit.right) / 2 == 640
        assert panel.bottom == lay.continue_.bottom + 40
        for box in (lay.body, lay.continue_, lay.quit):     # nothing outside the panel
            assert panel.x <= box.x and box.right <= panel.right
            assert panel.y <= box.y and box.bottom <= panel.bottom
        overflow = text is LONG
        assert lay.overflow is overflow and screen.body.focusable is overflow
        assert (screen.body.lane_box() is not None) is overflow
        assert rig.shell.theme is not None and screen.scope.focused is (
            screen.body if overflow else screen.continue_button)
        rig.h.frame()                                       # it draws
    assert widths and set(widths) == {WRAP_WIDTH} == {924}

    # The long text: Down/Page/End scroll to the end, then Down goes to Continue; the wheel.
    rig = Rig(tmp_path, warning_config(text=LONG, min_seconds=0), scale=1.5)
    rig.ready(0)
    body = rig.warning.body
    rig.press(pygame.K_DOWN)
    assert body.scroll > 0 or body.focus_row == 1
    rig.press(pygame.K_PAGEDOWN)
    rig.press(pygame.K_END)
    assert body.scroll == body.max_scroll() > 0 and rig.warning.scope.focused is body
    rig.press(pygame.K_DOWN)
    assert rig.warning.scope.focused is rig.warning.continue_button
    rig.press(pygame.K_RIGHT)
    assert rig.warning.scope.focused is rig.warning.quit_button
    rig.press(pygame.K_HOME)                                # buttons: Home does nothing
    rig.press(pygame.K_UP)
    assert rig.warning.scope.focused is body
    before = body.scroll
    rig.send(H.wheel(body.box.center, 1))
    assert body.scroll < before


# --- AC-F33-08 — reduced motion; notices ----------------------------------------------------

def test_ac_f33_08_reduce_motion_and_notices(tmp_path):
    rig = Rig(tmp_path, warning_config(min_seconds=0), reduce=True, notice=True)
    screen = rig.warning
    assert screen.phase is Phase.OPEN and screen.alpha == 1.0       # no fade in
    shell = rig.shell
    assert shell.notices.waiting() == (shell.words.get("notice_persistent"),)
    rig.h.frame()
    rig.step(1.0)
    assert shell.notices.views() == () and len(shell.notices.waiting()) == 1
    rig.app.screens.update(0.0)
    rig.press(pygame.K_RETURN)                                      # a cut, in this frame
    assert rig.types == [TitleScreen] and rig.app.screens.top.in_t == 1.0
    frame = rig.h.frame()
    top = rig.shell.theme.cfg.title.fill_top_color
    assert tuple(frame.get_at((640, 2)))[:3] != (0, 0, 0)          # no black frame
    assert all(abs(a - b) <= 8 for a, b in zip(frame.get_at((640, 0))[:3], top))
    rig.step(STEP)
    assert len(shell.notices.views()) == 1 and shell.notices.waiting() == ()
