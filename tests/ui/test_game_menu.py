"""F10 step 7 — the game menu, the confirm flows, and quitting on a real ``GameShell`` built by
``install_ui`` over test_title's small fake App (no frame loop): AC-F10-07, 09 (game-menu
rows), 42 to 46, 48, 55 to 63 in unit form, 67 (counts), and ``open_title_page``. App F runs
of the same flows (the real loop, story, and textbox) are in ``tests/app/test_ui_flow.py``.

The game runs on F05's ``TextboxScreen``, which hosts ``GameMenuKeys`` (C5). Its box (the
default fill at 0.80 over black, #CCC3C6) is the scene probe here: Template F's stage probe D
at (1000, 100) needs F04 and is pending (I-20). One frame is ``UiHarness.frame``: events,
``update(1/60)``, draw on a 1280×720 canvas.
"""

import pygame
import pytest

from engine.core.startvalues import StartOptions
from engine.runtime.commands import BASE_STYLE, Advance, Say, Span, StoryEnded, TaggedText
from engine.ui.backdrop import BACKDROP_KEY
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.sampler import SamplerScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.focus import Box, FocusGroup
from engine.ui.input import UiEvent
from engine.ui.menu_screen import CursorKeeper, Phase
from engine.ui.menus import MenuEntry, MenuPageBase
from engine.ui.nav import InputKind
from engine.ui.shell import Mode
from engine.ui.widgets import Button
from tests.fakes.audio_spy import AudioSpy
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import UiHarness
from tests.ui.test_title import Rig, close, over

H = UiHarness
BAND = (1000, 600)                    # inside the textbox, right of the text
SKY = (1000, 100)                     # above the box (black: no stage in this rig)
GREY = (0xCC, 0xC3, 0xC6)             # the box fill #FFF4F8 at 0.80 over black
DIM = (0x2A, 0x1E, 0x26)
RETURN, MAIN_MENU, QUIT = (48, 264, 288, 56), (48, 332, 288, 56), (48, 400, 288, 56)
CONFIRM_PANEL, YES, NO = (320, 237, 640, 246), (424, 387, 200, 56), (656, 387, 200, 56)
FADE = 9                              # ui.fade_ms 150 at 60 fps
MAIN_MENU_TEXT = "Return to the title screen? Unsaved progress will be lost."
QUIT_TEXT = "Quit the game? Unsaved progress will be lost."
# Shown complete at once (restored), so one advance input posts its Advance.
LINE = Say("s5", None, None, None, (), "Hello there.",
          body=TaggedText((Span("Hello there.", BASE_STYLE),)), restored=True)


def centre(box) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2, y + h / 2


def as_tuple(box: Box) -> tuple:
    return box.x, box.y, box.w, box.h


class Game:
    """A game in progress on the textbox (start options skip the title), one line shown."""

    def __init__(self, tmp_path, config: str = "", **kwargs) -> None:
        self.rig = Rig(tmp_path, config, start=StartOptions("start"), **kwargs)
        self.app = self.rig.app
        self.shell = self.rig.shell
        self.h = self.rig.h
        self.textbox = self.app.textbox
        assert [type(s) for s in self.stack] == [TextboxScreen]
        self.textbox.show(LINE)
        self.frames(2)

    @property
    def stack(self) -> list:
        return list(self.app.screens)

    @property
    def top(self):
        return self.app.screens.top

    @property
    def menu(self) -> GameMenuScreen:
        menu = self.shell.game_menu()
        assert menu is not None
        return menu

    def frame(self, *events):
        return self.h.frame(*events)

    def frames(self, n: int):
        return self.h.frames(n)

    def px(self, point):
        return self.h.px(*point)

    def open(self, event=None, *, settle: bool = True) -> GameMenuScreen:
        self.frame(event if event is not None else H.key(pygame.K_ESCAPE))
        menu = self.menu
        if settle:
            self.frames(FADE + 1)
            assert menu.phase is Phase.OPEN
        return menu

    def button(self, entry_id: str) -> Button:
        found = self.menu.button(entry_id)
        assert found is not None
        return found

    def labels(self) -> list[str]:
        return [b.label() for b in self.menu.buttons]


def game(tmp_path, config: str = "", **kwargs) -> Game:
    return Game(tmp_path, config, **kwargs)


# --- AC-F10-42 — opening the game menu -----------------------------------------------------

@pytest.mark.parametrize("event, by", [
    (H.key(pygame.K_ESCAPE), InputKind.KEYS),
    (H.key(pygame.K_ESCAPE, pygame.KMOD_LSHIFT), InputKind.KEYS),
    (H.pad(pygame.CONTROLLER_BUTTON_B), InputKind.KEYS),
    (H.pad(pygame.CONTROLLER_BUTTON_START), InputKind.KEYS),
    (H.down((640, 360), 3), InputKind.MOUSE),
], ids=["esc", "shift-esc", "east", "start", "right-click"])
def test_ac42_inputs_open_the_menu_in_their_frame(tmp_path, event, by):
    g = game(tmp_path)
    g.frame(event)
    menu = g.top
    assert isinstance(menu, GameMenuScreen) and menu.opened_by is by
    assert [type(s) for s in g.stack] == [TextboxScreen, GameMenuScreen]
    if by is InputKind.KEYS:
        assert menu.scope.focused is g.button("return") and menu.scope.visible
    else:
        assert menu.scope.focused is None
    assert g.app.story.posted == []                     # the textbox never saw it
    assert g.textbox.line is LINE


@pytest.mark.parametrize("event", [
    H.key(pygame.K_ESCAPE, pygame.KMOD_LCTRL), H.key(pygame.K_ESCAPE, pygame.KMOD_LALT),
    H.key(pygame.K_ESCAPE, pygame.KMOD_LGUI), H.down((640, 360), 3, in_canvas=False),
    H.key(pygame.K_F3, pygame.KMOD_LSHIFT), H.wheel((640, 360), -1),
], ids=["ctrl-esc", "alt-esc", "meta-esc", "letterbox-right-click", "shift-f3", "wheel"])
def test_ac42_other_inputs_do_not_open_it(tmp_path, event):
    g = game(tmp_path)
    g.frame(event)
    assert [type(s) for s in g.stack] == [TextboxScreen]


def test_ac42_not_on_the_title_or_during_a_black_fade(tmp_path):
    rig = Rig(tmp_path)
    rig.frame(H.key(pygame.K_ESCAPE))
    assert [type(s) for s in rig.stack] == [TitleScreen]
    rig.shell.open_game_menu(InputKind.KEYS)            # mode TITLE: refused
    assert [type(s) for s in rig.stack] == [TitleScreen]
    g = game(tmp_path / "b")
    g.shell.story_ended(StoryEnded())
    g.frame(H.key(pygame.K_ESCAPE), H.down((640, 360), 3))
    assert [type(s) for s in g.stack] == [TextboxScreen, BlackFadeScreen]
    g.shell.open_game_menu(InputKind.KEYS)              # mode ENDING: refused
    assert g.shell.game_menu() is None


def test_ac42_the_opening_input_never_acts_inside_it(tmp_path):
    g = game(tmp_path)
    menu = g.open(H.down((192, 292), 3), settle=False)  # right click over Return's place
    g.frame(H.up((192, 292), 3))
    g.frames(FADE + 2)
    assert g.top is menu and menu.phase is Phase.OPEN
    g.frame(H.key(pygame.K_ESCAPE, up=True))
    g.frames(2)
    assert g.top is menu and menu.phase is Phase.OPEN
    g.frame(H.key(pygame.K_ESCAPE))                     # a second Esc closes it
    assert menu.phase is Phase.CLOSING


def test_ac42_a_second_menu_never_stacks(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    g.shell.open_game_menu(InputKind.KEYS)
    assert g.stack == [g.textbox, menu]


# --- AC-F10-43 — look and first frame --------------------------------------------------------

def test_ac43_look_and_first_frames(tmp_path):
    g = game(tmp_path)
    before = g.px(BAND)
    assert before == GREY
    g.frame(H.key(pygame.K_ESCAPE))                      # frame N
    assert g.px(BAND) == GREY                            # the fade starts after the input
    g.frame()                                            # N + 1
    assert g.px(BAND) != GREY and sum(g.px(BAND)) < sum(GREY)       # darker: the fade began
    g.frames(FADE - 1)                                   # N + 9
    menu = g.menu
    dimmed = over(DIM, 0.55, GREY)
    assert close(g.px(BAND), dimmed)
    sky = g.px(SKY)
    assert close(sky, over(DIM, 0.55, (0, 0, 0)))
    assert g.px((800, 360)) == sky                       # no content panel
    panel = g.shell.theme.cfg.panel
    assert close(g.px((30, 600)), over(panel.fill_color, panel.fill_opacity, sky), 3)  # left of the box
    assert g.labels() == ["Return", "Main Menu", "Quit"]
    assert [as_tuple(b.box) for b in menu.buttons] == [RETURN, MAIN_MENU, QUIT]
    assert menu.look_for(g.button("return")).state == "focused"
    frame = pygame.image.tobytes(g.frame(), "RGB")       # steady: byte-identical
    for _ in range(3):
        assert pygame.image.tobytes(g.frame(), "RGB") == frame


def test_ac43_opened_by_right_click_shows_no_focus(tmp_path):
    g = game(tmp_path)
    menu = g.open(H.down((900, 200), 3))
    assert all(menu.look_for(b).state == "normal" for b in menu.buttons)


# --- AC-F10-44 — closing ----------------------------------------------------------------------

@pytest.mark.parametrize("events", [
    [H.key(pygame.K_ESCAPE)], [H.pad(pygame.CONTROLLER_BUTTON_B)], [H.down((900, 200), 3)],
    [H.pad(pygame.CONTROLLER_BUTTON_START)], [H.key(pygame.K_RETURN)],
    [H.down(centre(RETURN)), H.up(centre(RETURN))],
], ids=["esc", "east", "right-click", "start", "enter-on-return", "click-return"])
def test_ac44_inputs_close_the_menu_over_nine_frames(tmp_path, events):
    g = game(tmp_path)
    menu = g.open()
    g.frame(*events)                                     # frame N
    assert menu.phase is Phase.CLOSING
    g.frames(FADE - 1)
    assert g.top is menu
    g.frame()                                            # N + 9
    assert g.stack == [g.textbox] and g.app.story.posted == []
    g.frame(H.key(pygame.K_SPACE))                       # the game takes input again
    assert g.app.story.posted == [Advance(LINE.sid)]


@pytest.mark.parametrize("events", [
    [H.down((800, 200)), H.up((800, 200))], [H.down((700, 500)), H.up((700, 500))],
    [H.wheel((800, 200), -1)], [H.wheel(centre(RETURN), 1)],
], ids=["click-dim", "click-content-area", "wheel-dim", "wheel-sidebar"])
def test_ac44_clicks_off_the_buttons_and_the_wheel_do_nothing(tmp_path, events):
    g = game(tmp_path)
    menu = g.open()
    g.frame(*events)
    g.frames(FADE + 1)
    assert g.stack == [g.textbox, menu] and menu.phase is Phase.OPEN
    assert g.app.story.posted == []


def test_ac44_start_with_a_confirm_on_top_does_nothing(tmp_path):
    g = game(tmp_path)
    g.open()
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_RETURN))                      # Main Menu → the question
    confirm = g.top
    assert isinstance(confirm, ConfirmScreen)
    g.frames(FADE + 1)
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_START))
    g.frames(FADE + 1)
    assert g.top is confirm and confirm.phase is Phase.OPEN


# --- AC-F10-45 — Main Menu ---------------------------------------------------------------------

def _main_menu_question(g: Game, *, by_mouse: bool = False) -> ConfirmScreen:
    if by_mouse:
        g.frame(H.motion(centre(MAIN_MENU)))
        g.h.click(centre(MAIN_MENU))
    else:
        g.frame(H.key(pygame.K_DOWN))
        g.frame(H.key(pygame.K_RETURN))
    confirm = g.top
    assert isinstance(confirm, ConfirmScreen)
    g.frames(FADE + 1)
    return confirm


def test_ac45_the_question_and_its_text(tmp_path, monkeypatch):
    g = game(tmp_path)
    g.open()
    with spy_draw_text(monkeypatch) as calls:
        confirm = _main_menu_question(g)
    assert confirm.message == MAIN_MENU_TEXT
    assert [b.label() for b in (confirm.yes_button, confirm.no_button)] == ["Yes", "No"]
    assert " ".join(confirm.fit.lines) == MAIN_MENU_TEXT
    drawn = {c.text for c in calls}
    assert all(line in drawn for line in confirm.fit.lines)


@pytest.mark.parametrize("answer, visible", [
    ([H.key(pygame.K_RETURN)], True), ([H.key(pygame.K_ESCAPE)], True),
    ([H.pad(pygame.CONTROLLER_BUTTON_B)], True), ([H.down(centre(NO)), H.up(centre(NO))], False),
    ([H.down((900, 100), 3)], False),
], ids=["enter-on-no", "esc", "east", "click-no", "right-click"])
def test_ac45_no_keeps_the_menu_with_main_menu_focused(tmp_path, answer, visible):
    g = game(tmp_path)
    menu = g.open()
    _main_menu_question(g)
    g.frame(*answer)
    g.frames(FADE + 1)
    assert g.stack == [g.textbox, menu] and g.shell.mode is Mode.GAME
    assert menu.scope.focused is g.button("main_menu")
    assert menu.scope.visible is visible                 # drawn focused only for keys/pad
    assert g.app.quits == 0


def test_ac45_yes_fades_to_black_then_shows_the_title(tmp_path):
    audio = AudioSpy()
    g = game(tmp_path, '[theme.title]\nmusic = "title.ogg"', audio=audio)
    g.open()
    _main_menu_question(g)
    before = g.px(BAND)
    g.frame(H.key(pygame.K_LEFT))                        # Yes
    audio.calls.clear()
    g.frame(H.key(pygame.K_RETURN))                      # frame N
    assert audio.calls == [("stop_story_audio", 0.5)]
    assert g.shell.mode is Mode.ENDING
    assert [type(s) for s in g.stack] == [TextboxScreen, GameMenuScreen, BlackFadeScreen]
    shades = []
    for _ in range(FADE - 1):                            # N + 1 .. N + 8: no input acts
        g.frame(H.key(pygame.K_RETURN), H.key(pygame.K_ESCAPE), H.down(centre(RETURN)),
                H.up(centre(RETURN)))
        shades.append(g.px(BAND))
    # The confirm's own dim goes in frame N + 1 (visible over the light box since F05),
    # then the fade only darkens.
    assert sum(shades[0]) < sum(GREY) and sum(before) < sum(GREY)
    assert all(sum(a) >= sum(b) for a, b in zip(shades, shades[1:]))
    assert shades[-1] != (0, 0, 0)
    g.frame()                                            # N + 9: the title
    assert [type(s) for s in g.stack] == [TitleScreen] and g.shell.mode is Mode.TITLE
    title = g.top
    assert title.in_t == 0.0 and title.fade_in_s == 0.5
    assert g.textbox.line is None                        # the textbox is cleared
    assert audio.calls[-2:] == [("take_music", "title"), ("play", "title.ogg", True, 0.0)]
    assert g.app.story.posted == [] and g.app.quits == 0


def test_ac45_yes_under_reduced_motion_cuts(tmp_path):
    g = game(tmp_path, reduce=True)
    g.open()
    _main_menu_question(g)
    g.frame(H.key(pygame.K_LEFT))
    g.frame(H.key(pygame.K_RETURN))
    assert [type(s) for s in g.stack] == [TitleScreen]
    assert g.top.darkness == 0.0                          # no black frame


def test_ac41_no_title_main_menu_asks_to_quit_and_yes_quits(tmp_path):
    g = Game.__new__(Game)
    g.rig = Rig(tmp_path, "[title]\nenabled = false")
    g.app, g.shell, g.h = g.rig.app, g.rig.shell, g.rig.h
    g.textbox = g.app.textbox
    g.textbox.show(LINE)
    g.open()
    confirm = _main_menu_question(g)
    assert confirm.message == QUIT_TEXT
    g.frame(H.key(pygame.K_LEFT))
    g.frame(H.key(pygame.K_RETURN))
    assert g.app.quits == 1


# --- AC-F10-46 — pages inside the game menu ---------------------------------------------------

class FakePage(MenuPageBase):
    """06 §0.4's fake page: heading ``save``, one column of three buttons; records calls."""

    heading = "save"

    def __init__(self, host, *, back_result: bool = False) -> None:
        self.host = host
        self.back_result = back_result
        self.calls: list = []
        self.buttons = [Button(lambda i=i: f"P{i + 1}", lambda: None) for i in range(3)]

    def build(self, host, body):
        self.calls.append(("build", as_tuple(body)))
        for i, button in enumerate(self.buttons):
            button.box = Box(body.x + 32, body.y + 32 + 68 * i, 320, 56)
        return [FocusGroup(self.buttons, column=True)]

    def update(self, dt: float) -> None:
        pass

    def draw(self, canvas, p) -> None:
        pass

    def back(self) -> bool:
        self.calls.append(("back",))
        return self.back_result

    def closed(self) -> None:
        self.calls.append(("closed",))


def _with_save_page(g: Game, *, back_result: bool = False) -> list:
    pages: list[FakePage] = []

    def make(host):
        pages.append(FakePage(host, back_result=back_result))
        return pages[-1]

    g.shell.menus.add("game", MenuEntry("save", page=make))
    return pages


def test_ac46_pages(tmp_path, monkeypatch):
    g = game(tmp_path)
    pages = _with_save_page(g)
    menu = g.open()
    assert g.labels() == ["Return", "Save", "Main Menu", "Quit"]
    sky = g.px((800, 360))
    save = g.button("save")
    with spy_draw_text(monkeypatch) as calls:
        g.frame(H.motion(save.box.center))
        g.h.click(save.box.center)                       # the page shows in this frame
    page = pages[0]
    assert page.calls == [("build", (416, 112, 808, 552))]
    assert menu.page is page and save.is_selected()
    assert any(c.text == "Save" and c.pos == (416, 56) for c in calls)
    assert g.px((800, 360)) != sky                       # the content panel
    marker = g.shell.theme.cfg.button.marker.fill_color
    g.frame(H.motion((800, 650)))                        # pointer off: Save not focused
    assert menu.look_for(save).selected and menu.look_for(save).state == "normal"
    assert close(g.px((save.box.x + 7, save.box.center[1])), marker, 3)
    g.frame(H.key(pygame.K_DOWN))                        # keys: focus shows again (Save)
    menu.scope.focus(save, InputKind.KEYS)
    g.frame(H.key(pygame.K_RIGHT))
    assert menu.scope.focused is page.buttons[0]
    g.frame(H.key(pygame.K_DOWN))
    assert menu.scope.focused is page.buttons[1]
    g.frame(H.key(pygame.K_LEFT))
    assert menu.scope.focused is save
    g.frame(H.key(pygame.K_RIGHT))
    assert menu.scope.focused is page.buttons[1]
    g.frame(H.key(pygame.K_ESCAPE))                      # back() False: the page closes
    assert page.calls[-2:] == [("back",), ("closed",)]
    assert menu.page is None and menu.scope.focused is save and not save.is_selected()
    g.frame()
    assert g.px((800, 360)) == sky
    g.frame(H.key(pygame.K_ESCAPE))                      # again: the menu closes
    assert menu.phase is Phase.CLOSING
    assert page.calls.count(("closed",)) == 1


def test_ac46_a_page_that_handles_back_stays(tmp_path):
    g = game(tmp_path)
    pages = _with_save_page(g, back_result=True)
    menu = g.open()
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_RETURN))
    g.frame(H.key(pygame.K_ESCAPE))
    assert menu.page is pages[0] and menu.phase is Phase.OPEN
    assert pages[0].calls[-1] == ("back",)


def test_ac46_closing_the_menu_closes_its_page(tmp_path):
    g = game(tmp_path)
    pages = _with_save_page(g)
    menu = g.open()
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_RETURN))
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_START))
    g.frames(FADE + 1)
    assert g.shell.game_menu() is None and menu.page is None
    assert pages[0].calls.count(("closed",)) == 1


def test_title_pages_open_in_the_menu_layout_over_the_title(tmp_path):
    rig = Rig(tmp_path)
    pages: list[FakePage] = []
    rig.shell.menus.add("title", MenuEntry("load", page=lambda host: pages.append(
        FakePage(host)) or pages[-1]))
    rig.app.screens.replace_all(rig.shell.initial_screens())
    rig.frames(31)
    title = rig.title
    assert [b.label() for b in title.buttons] == ["New Game", "Load", "Quit"]
    rig.frame(H.key(pygame.K_DOWN))
    rig.frame(H.key(pygame.K_DOWN))
    rig.frame(H.key(pygame.K_RETURN))                    # Load
    screen = rig.app.screens.top
    assert isinstance(screen, GameMenuScreen) and screen.from_title
    assert [b.label() for b in screen.buttons] == ["Return", "Load"]
    assert screen.page is pages[0] and screen.scene_picture() is None
    rig.frames(FADE + 1)
    rig.frame(H.key(pygame.K_ESCAPE))
    rig.frames(FADE + 1)
    assert rig.stack == [title] and pages[0].calls[-1] == ("closed",)
    assert title.scope.focused is title.buttons[1]       # back on Load


# --- AC-F10-48 — the scene picture -------------------------------------------------------------

@pytest.mark.parametrize("window", [(1280, 720), (1920, 1080)])
def test_ac48_scene_picture_is_the_last_frame_before_the_menu(tmp_path, window):
    g = game(tmp_path)
    g.h.resize(window)
    g.frames(2)
    vp = g.h.viewport
    before = g.h.framebuffer.subsurface((vp.x, vp.y, vp.w, vp.h)).copy()
    menu = g.open()
    picture = menu.scene_picture()
    assert picture is not None and picture.get_size() == (vp.w, vp.h) == window
    assert pygame.image.tobytes(picture, "RGB") == pygame.image.tobytes(before, "RGB")


# --- AC-F10-07 — Back returns focus to the opener (game menu → its question) ----------------

@pytest.mark.parametrize("back, visible", [
    (H.key(pygame.K_ESCAPE), True), (H.pad(pygame.CONTROLLER_BUTTON_B), True),
    (H.down((900, 100), 3), False),
], ids=["esc", "east", "right-click"])
def test_ac07_back_from_a_question_returns_to_its_button(tmp_path, back, visible):
    g = game(tmp_path)
    menu = g.open()
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_DOWN))                        # Quit
    g.frame(H.key(pygame.K_RETURN))
    g.frames(FADE + 1)
    g.frame(back)
    g.frames(FADE + 1)
    assert g.stack == [g.textbox, menu]
    assert menu.scope.focused is g.button("quit") and menu.scope.visible is visible
    assert g.app.quits == 0 and g.app.story.new_games == 1


# --- AC-F10-55, 56 — the Main Menu question --------------------------------------------------

def test_ac55_focus_rows(tmp_path):
    g = game(tmp_path)
    g.open()
    confirm = _main_menu_question(g)
    scope = confirm.scope
    assert scope.focused is confirm.no_button and scope.visible
    for key, want in ((pygame.K_LEFT, "yes"), (pygame.K_LEFT, "yes"), (pygame.K_RIGHT, "no"),
                      (pygame.K_RIGHT, "no"), (pygame.K_UP, "no"), (pygame.K_DOWN, "no"),
                      (pygame.K_TAB, "yes"), (pygame.K_TAB, "no")):
        g.frame(H.key(key))
        assert scope.focused is getattr(confirm, f"{want}_button"), key


def test_ac55_opened_by_mouse_focuses_nothing_until_a_key(tmp_path):
    g = game(tmp_path)
    g.open(H.down((900, 100), 3))
    confirm = _main_menu_question(g, by_mouse=True)
    g.frame(H.motion((100, 100)))
    assert confirm.scope.focused is None
    g.frame(H.key(pygame.K_DOWN))
    assert confirm.scope.focused is confirm.no_button and g.top is confirm


@pytest.mark.parametrize("events", [
    [H.pad(pygame.CONTROLLER_BUTTON_START)], [H.wheel((640, 360), -1)],
    [H.down((100, 100)), H.up((100, 100))], [H.down((900, 650)), H.up((900, 650))],
], ids=["start", "wheel", "click-100-100", "click-dim"])
def test_ac55_inputs_that_leave_the_question_open(tmp_path, events):
    g = game(tmp_path)
    g.open()
    confirm = _main_menu_question(g)
    g.frame(*events)
    g.frames(FADE + 1)
    assert g.top is confirm and confirm.phase is Phase.OPEN and g.shell.mode is Mode.GAME


def test_ac55_the_question_waits_forever(tmp_path):
    g = game(tmp_path)
    g.open()
    confirm = _main_menu_question(g)
    for _ in range(36_000):
        g.app.screens.update(1 / 60)
    assert g.top is confirm and confirm.phase is Phase.OPEN


def test_ac56_look(tmp_path, monkeypatch):
    g = game(tmp_path)
    g.open()
    band_before, sidebar_before = g.px(BAND), g.px((30, 600))
    with spy_draw_text(monkeypatch) as calls:
        confirm = _main_menu_question(g)
    assert close(g.px(BAND), over(DIM, 0.35, band_before), 3)
    assert close(g.px((30, 600)), over(DIM, 0.35, sidebar_before), 3)
    assert confirm.layout is not None and len(confirm.fit.lines) == 2
    assert as_tuple(confirm.layout.panel) == CONFIRM_PANEL
    assert as_tuple(confirm.yes_button.box) == YES and as_tuple(confirm.no_button.box) == NO
    lines = [c for c in calls if c.text in confirm.fit.lines]
    assert lines and all(c.pos[0] == 640 and c.bounds[2] <= 544 for c in lines)


# --- AC-F10-57 — quitting (unit form; App F rows in tests/app/test_ui_flow.py) ---------------

def test_ac57_quit_in_game_asks_and_a_second_request_quits(tmp_path):
    g = game(tmp_path)
    g.app.request_quit()
    confirm = g.top
    assert isinstance(confirm, ConfirmScreen) and confirm.message == QUIT_TEXT
    assert g.app.quits == 0
    g.frames(10)
    assert g.top is confirm
    g.app.request_quit()                                 # the quit question is open
    assert g.app.quits == 1


def test_ac57_quit_yes_runs_later_guards_once(tmp_path):
    g = game(tmp_path)
    later = []
    g.app.add_quit_guard(lambda: later.append(1) or True)
    g.open()
    g.frame(H.key(pygame.K_UP))                          # wraps to Quit
    g.frame(H.key(pygame.K_RETURN))
    g.frames(FADE + 1)
    g.frame(H.key(pygame.K_LEFT))
    g.frame(H.key(pygame.K_RETURN))                      # Yes
    assert g.app.quits == 1 and later == [1]


def test_ac57_quit_no_keeps_the_menu(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    g.frame(H.key(pygame.K_UP))
    g.frame(H.key(pygame.K_RETURN))
    g.frames(FADE + 1)
    g.frame(H.key(pygame.K_RETURN))                      # No
    g.frames(FADE + 1)
    assert g.stack == [g.textbox, menu] and g.app.quits == 0


def test_ac57_a_quit_replaces_the_main_menu_question(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    asked = _main_menu_question(g)
    calls = []
    asked.on_yes = lambda: calls.append("yes")
    asked.on_no = lambda: calls.append("no")
    g.app.request_quit()
    top = g.top
    assert isinstance(top, ConfirmScreen) and top.message == QUIT_TEXT
    assert asked not in g.stack and calls == []
    assert g.stack == [g.textbox, menu, top]
    g.frames(FADE + 2)
    assert calls == [] and g.shell.mode is Mode.GAME


def test_ac57_title_and_fades_quit_at_once(tmp_path):
    rig = Rig(tmp_path)
    rig.app.request_quit()
    assert rig.app.quits == 1 and [type(s) for s in rig.stack] == [TitleScreen]
    g = game(tmp_path / "b")
    g.shell.story_ended(StoryEnded())
    g.app.request_quit()
    assert g.app.quits == 1
    assert not any(isinstance(s, ConfirmScreen) for s in g.stack)


def test_ac57_a_forced_quit_never_asks(tmp_path):
    g = game(tmp_path)
    g.app.request_quit(force=True)
    assert g.app.quits == 1 and g.stack == [g.textbox]


@pytest.mark.parametrize("mouse_last", [False, True], ids=["key-last", "mouse-last"])
def test_ac57_the_quit_question_focus_follows_the_last_input(tmp_path, mouse_last):
    g = game(tmp_path)
    g.frame(H.key(pygame.K_LSHIFT))
    if mouse_last:
        g.frame(H.motion((500, 500)))
    g.app.request_quit()
    confirm = g.top
    assert isinstance(confirm, ConfirmScreen)
    if mouse_last:
        assert confirm.scope.focused is None
    else:
        assert confirm.scope.focused is confirm.no_button and confirm.scope.visible


# --- AC-F10-58 — input order and input during fades ------------------------------------------

def test_ac58_one_esc_closes_only_the_question(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    confirm = _main_menu_question(g)
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(FADE + 1)
    assert confirm not in g.stack and g.stack == [g.textbox, menu]


def test_ac58_esc_and_esc_in_one_frame(tmp_path):
    g = game(tmp_path)
    g.frame(H.key(pygame.K_ESCAPE), H.key(pygame.K_ESCAPE))
    assert g.menu.phase is Phase.CLOSING


def test_ac58_input_during_the_opening_fade(tmp_path):
    g = game(tmp_path)
    menu = g.open(settle=False)
    g.frames(3)
    assert menu.phase is Phase.OPENING
    g.frame(H.key(pygame.K_DOWN))
    assert menu.phase is Phase.OPEN and menu.scope.focused is g.button("main_menu")


def test_ac58_click_during_the_closing_fade_reaches_the_game_once(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(3)
    g.frame(H.down((900, 200)), H.up((900, 200)))
    assert menu not in g.stack
    assert g.app.story.posted == [Advance(LINE.sid)]


def test_ac58_esc_during_the_closing_fade_opens_it_again(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(3)
    g.frame(H.key(pygame.K_ESCAPE))
    again = g.shell.game_menu()
    assert again is not None and again is not menu and menu not in g.stack
    assert g.app.story.posted == []


# --- AC-F10-59, 60 — fades ---------------------------------------------------------------------

def _shades(g: Game, n: int, point=BAND) -> list:
    out = []
    for _ in range(n):
        g.frame()
        out.append(g.px(point))
    return out


def test_ac59_open_and_close_take_nine_frames_linearly(tmp_path):
    g = game(tmp_path)
    g.frame(H.key(pygame.K_ESCAPE))
    shades = _shades(g, FADE + 1)
    end = over(DIM, 0.55, GREY)
    for k, shade in enumerate(shades[:FADE], start=1):
        assert close(shade, over(DIM, 0.55 * k / FADE, GREY), 3), (k, shade)
    assert close(shades[FADE], end)
    g.frame(H.key(pygame.K_ESCAPE))
    shades = _shades(g, FADE)
    for k, shade in enumerate(shades[:-1], start=1):
        assert close(shade, over(DIM, 0.55 * (1 - k / FADE), GREY), 3), (k, shade)
    assert shades[-1] == GREY


def test_ac60_reduced_motion_cuts_the_menu(tmp_path):
    g = game(tmp_path, reduce=True)
    g.frame(H.key(pygame.K_ESCAPE))
    assert close(g.px(BAND), over(DIM, 0.55, GREY))
    g.frame(H.key(pygame.K_ESCAPE))
    assert g.stack == [g.textbox] and g.px(BAND) == GREY


def test_fade_ms_zero_cuts_menus(tmp_path):
    g = game(tmp_path, "[theme.ui]\nfade_ms = 0")
    g.frame(H.key(pygame.K_ESCAPE))
    assert close(g.px(BAND), over(DIM, 0.55, GREY)) and g.menu.phase is Phase.OPEN
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_RETURN))                       # Main Menu
    assert isinstance(g.top, ConfirmScreen) and g.top.phase is Phase.OPEN
    g.frame(H.key(pygame.K_LEFT))
    g.frame(H.key(pygame.K_RETURN))                       # Yes: no black fade at 0 ms
    assert [type(s) for s in g.stack] == [TitleScreen]


# --- AC-F10-09 — the sampler from the game menu ------------------------------------------------

def test_ac09_shift_f3_on_the_game_menu_opens_the_sampler(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    g.frame(H.key(pygame.K_F3, pygame.KMOD_LSHIFT))
    assert isinstance(g.top, SamplerScreen)
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(FADE + 1)
    assert g.top is menu and menu.scope.focused is g.button("return")


def test_ac09_no_sampler_without_dev(tmp_path, monkeypatch):
    g = game(tmp_path, dev=False)
    made = []
    monkeypatch.setattr(SamplerScreen, "__init__", lambda *a, **k: made.append(1))
    g.open()
    g.frame(H.key(pygame.K_F3, pygame.KMOD_LSHIFT))
    assert isinstance(g.top, GameMenuScreen) and made == []


# --- AC-F10-61 — a controller ------------------------------------------------------------------

def test_ac61_controller_start_dpad_a_b_and_removal(tmp_path):
    g = game(tmp_path)
    added = UiEvent(pygame.event.Event(pygame.CONTROLLERDEVICEADDED, device_index=0,
                                       instance_id=0), None, False)
    removed = UiEvent(pygame.event.Event(pygame.CONTROLLERDEVICEREMOVED, instance_id=0),
                      None, False)
    g.frame(added)
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_START))
    menu = g.menu
    g.frames(FADE + 1)
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN))
    assert menu.scope.focused is g.button("main_menu")
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_A))
    confirm = g.top
    assert isinstance(confirm, ConfirmScreen)
    g.frames(FADE + 1)
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_B))
    g.frames(FADE + 1)
    assert g.top is menu and menu.scope.focused is g.button("main_menu")
    g.frame(removed)
    assert g.stack == [g.textbox, menu] and menu.scope.focused is g.button("main_menu")
    g.frame(H.key(pygame.K_DOWN))
    assert menu.scope.focused is g.button("quit")
    g.frame(H.motion(centre(RETURN)))
    assert menu.scope.focused is g.button("return")


def test_ac61_two_controllers_move_one_focus(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    down0 = H.pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN)
    down1 = UiEvent(pygame.event.Event(pygame.CONTROLLERBUTTONDOWN,
                                       button=pygame.CONTROLLER_BUTTON_DPAD_DOWN,
                                       instance_id=1), None, False)
    g.frame(down0, down1)
    assert menu.scope.focused is g.button("quit")


# --- AC-F10-62 — resize inside the menu --------------------------------------------------------

def test_ac62_resize_keeps_screens_focus_and_boxes_and_recaptures_once(tmp_path):
    g = game(tmp_path)
    menu = g.open()
    g.frame(H.key(pygame.K_DOWN))
    boxes = [as_tuple(b.box) for b in menu.buttons]
    captures = menu.backdrop.captures
    stack = g.stack
    g.h.resize((1600, 900))
    g.frame()                                            # the old backdrop, scaled
    assert g.px(BAND) != (0, 0, 0)
    g.frames(3)
    assert menu.backdrop.captures == captures + 1
    assert g.stack == stack and menu.scope.focused is g.button("main_menu")
    assert [as_tuple(b.box) for b in menu.buttons] == boxes
    g.frame(UiEvent(pygame.event.Event(pygame.WINDOWFOCUSLOST), None, False))
    g.frame(UiEvent(pygame.event.Event(pygame.WINDOWFOCUSGAINED), None, False))
    assert g.stack == stack and menu.scope.focused is g.button("main_menu")


# --- AC-F10-63 — cursor hiding -----------------------------------------------------------------

def test_ac63_cursor_hides_on_keys_and_comes_back(tmp_path):
    g = game(tmp_path)
    calls: list[bool] = []
    g.shell.cursor = CursorKeeper(calls.append)
    g.frame(H.key(pygame.K_SPACE))                       # keys in game: nothing
    assert calls == []
    g.open()
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_UP))
    assert calls == [False]
    g.frame(H.motion((900, 300)))
    assert calls == [False, True]
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(FADE + 1)
    assert calls == [False, True, False, True]           # shown when the last menu went


# --- AC-F10-67 — caches and draw calls (counts; the timing row runs in tests/perf) -------------

def test_ac67_steady_menu_frames_build_and_capture_nothing(tmp_path):
    g = game(tmp_path)
    g.h.resize((1920, 1080))
    menu = g.open()
    assert menu.backdrop.captures == 1
    builds = g.shell.painter.builds
    for _ in range(60):
        g.frame()
    assert menu.backdrop.captures == 1 and g.shell.painter.builds == builds
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(FADE + 1)
    cache = g.shell.assets.cache
    assert not [key for key in cache.keys() if key and key[0] == BACKDROP_KEY]


def test_ac67_the_fade_layer_is_the_sidebar(tmp_path):
    g = game(tmp_path)
    menu = g.open(settle=False)
    g.frame()
    assert menu._layer is not None
    assert menu._layer.get_size() == (336, 672)
