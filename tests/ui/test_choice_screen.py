"""F07 steps 2–4 — menus on screen: ``ChoiceController``, ``ChoiceScreen``, the textbox's
``wait_for_menu``, and the button looks. AC-F07-20, 22, 24, 25, 26, 27, 28 (F07 ``06`` §1.4),
with F10's amendments (AC-F07-24's off-button rows return ``False``; C7, C8) and 07 I-3 (the
locked fill is the normal one at 0.90); AC-F07-34 (step 3); and step 4's AC-F07-29 (the fade,
with 07 I-7's one-frame lead: alpha ``min(1, (k + 1) / 7.2)``, full from k = 7), 30, 31, 32,
33, 36, and 38. AC-F07-38 uses generated WAVs (``focus.wav``, ``pick.wav``; the repo has no
Ogg encoder): the AC checks the ``play_ui`` calls, which don't depend on the format.

Two rigs:

- **Unit**: a ``ChoiceController`` on a bare ``ScreenStack`` with a textbox stand-in
  (``tab_top`` 460, so B = 444 and the buttons sit at the AC's tops 130, 201, 272) and a view
  that draws nothing; input as ``UiEvent``s; ``draw`` marks the first draw.
- **App A** (``tests/fakes/text_app.py``): the real ``App`` loop on a 1280×720
  ``FakeWindow``, 1/60 s frames, Template M in ``tmp_path``. F05's built ``tab_top`` is 462,
  so B is 446 and the live tops are 131, 202, 273; every probe of the AC still lands where
  it says (button 1's top-left corner is (240, 131)).
"""

import pygame
import pytest

from engine.core.config_schema import ChoiceFocusedTheme, ChoiceMarkerTheme, ChoiceTheme
from engine.render.choices import ChoiceStackView
from engine.render.typewriter import TypeState
from engine.runtime.commands import Advance, Choose, Say, ShowMenu, ShownChoice
from engine.render.textlayout import BUNDLED_FACES
from engine.ui.builtin.choice_screen import GUARD_S, ChoiceController, ChoiceScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.input import UiEvent
from engine.ui.screen import Screen, ScreenStack
from tests.fakes.fixed_font import FixedFontAssets, tagged
from tests.fakes.text_app import Session, make_text_game
from tests.runtime.menu_story import K
from tests.script.helpers import template_m

FILL = (0xE6, 0xDC, 0xDF)                 # #FFF4F8 at 0.90 over black
FOCUSED_FILL = (0xE6, 0xC1, 0xD1)         # #FFD6E8 at 0.90 over black
BORDER = (0xF0, 0xA0, 0xC0)
BERRY = (0xA0, 0x28, 0x60)
PLUM = (0x3D, 0x2B, 0x36)
MAUVE = (0x6E, 0x5E, 0x68)
BLACK = (0, 0, 0)
B1, B2, B3 = (640, 160), (640, 231), (640, 301)
NO_QUESTION = ('menu:⏎[8]"The red one":⏎[12]$ lantern = "red"⏎'
               '[8]"Not this year":⏎[12]jump walk_home')


# --- Unit rig ------------------------------------------------------------------------------------

class FakeTextbox(Screen):
    """F05's seams as F07 uses them; on the stack under the choices."""

    opaque = False
    in_game = True

    def __init__(self) -> None:
        self.hidden = False
        self.has_box = True
        self.nvl_on = False                    # ADV (F17's NVL rows: test_nvl_choices)
        self.size = 28
        self.cleared = 0
        self.on_shown = None
        self.reduced = False

    def text_size(self) -> int:
        return self.size

    def tab_top(self) -> float:
        return 460.0                           # 04's figure: B = 444, the AC's tops

    def clear(self, *, hide: bool = True) -> None:
        self.cleared += 1

    def wait_for_menu(self, on_shown) -> None:
        self.on_shown = on_shown

    def set_hidden(self, hidden: bool) -> None:
        self.hidden = hidden

    def reduce_motion(self) -> bool:
        return self.reduced


class NoDraw:
    def __init__(self) -> None:
        self.draws = 0
        self.alphas: list[float] = []

    def draw(self, canvas, layout, states, *, alpha=1.0) -> None:
        self.draws += 1
        self.alphas.append(alpha)


class Rig:
    def __init__(self, locked: tuple[bool, ...] = (False, False, False), line="question", *,
                 theme: ChoiceTheme | None = None, restored: bool = False, **sounds):
        self.stack = ScreenStack()
        self.textbox = FakeTextbox()
        self.stack.push(self.textbox)
        self.posted: list[object] = []
        self.played: list[str] = []
        self.controller = ChoiceController(
            self.stack, self.textbox, theme=theme or ChoiceTheme(), assets=FixedFontAssets(),
            faces=BUNDLED_FACES, base_text_size=28, post=self.posted.append, view=NoDraw(),
            play=self.played.append, **sounds)
        self.cmd = ShowMenu("menu/1", tuple(
            ShownChoice(f"c{i + 1}", tagged(f"Choice {i + 1}"), flag)
            for i, flag in enumerate(locked)), line, restored)
        self.controller.show(self.cmd)

    def open(self, *, drawn: bool = True) -> ChoiceScreen:
        self.textbox.on_shown()
        screen = self.stack.top
        assert isinstance(screen, ChoiceScreen)
        if drawn:
            screen.draw(None)                  # NoDraw: the first draw starts the guard
        return screen

    def past_guard(self) -> ChoiceScreen:
        screen = self.open()
        screen.update(GUARD_S, is_top=True)
        return screen

    def send(self, raw) -> bool:
        pos = getattr(raw, "pos", None)
        return self.stack.handle_event(UiEvent(raw, pos, pos is not None))

    def chosen(self) -> list[str]:
        return [e.choice for e in self.posted if isinstance(e, Choose)]


def down(pos, button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)


def up(pos, button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button)


def motion(pos):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0))


def key(k, **kw):
    return pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, **kw)


def letterbox_click():
    return UiEvent(down((50, 160)), (-110, 160), False)


# --- the controller ------------------------------------------------------------------------------

def test_show_waits_for_the_line_then_pushes_directly_above_the_textbox():
    rig = Rig()
    assert rig.stack.top is rig.textbox and rig.textbox.on_shown is not None
    screen = rig.open(drawn=False)
    assert list(rig.stack) == [rig.textbox, screen]
    assert rig.controller.screen is screen and screen.in_game and not screen.opaque
    assert rig.textbox.cleared == 0


def test_a_none_menu_clears_the_textbox_first():
    rig = Rig(line="none")
    assert rig.textbox.cleared == 1


def test_close_removes_the_screen_anywhere_and_drops_a_waiting_menu():
    rig = Rig()
    screen = rig.open()
    above = Screen()
    rig.stack.push(above)
    rig.controller.close()
    assert list(rig.stack) == [rig.textbox, above] and rig.controller.screen is None
    rig.controller.show(rig.cmd)
    rig.controller.close()
    rig.textbox.on_shown()                     # the stale callback opens nothing
    assert not any(isinstance(s, ChoiceScreen) for s in rig.stack)
    assert screen.cmd is rig.cmd


def test_a_new_show_and_a_say_close_the_open_menu():
    rig = Rig()
    rig.open()
    rig.controller.show(rig.cmd)
    assert not any(isinstance(s, ChoiceScreen) for s in rig.stack)
    rig.open()
    rig.controller.on_say(Say("s", None, None, None, (), "x"))
    assert not any(isinstance(s, ChoiceScreen) for s in rig.stack)


def test_a_menu_with_nothing_pickable_is_a_programmer_error():
    with pytest.raises(AssertionError):
        Rig(locked=(True, True))


# --- AC-F07-24 — mouse ---------------------------------------------------------------------------

def test_ac24_ac26_motion_focuses_during_and_after_the_guard():
    rig = Rig()
    screen = rig.open()
    assert screen.focus is None
    assert rig.send(motion(B3)) is False                # in the guard: hover focuses
    assert screen.focus == 2
    screen.update(GUARD_S, is_top=True)
    assert rig.send(motion(B2)) is False
    assert screen.focus == 1 and rig.posted == []


def test_ac24_a_click_on_button_2_posts_one_choose_and_closes():
    rig = Rig()
    rig.past_guard()
    assert rig.send(down(B2)) is True
    assert rig.posted == [Choose("menu/1", "c2")]
    assert not any(isinstance(s, ChoiceScreen) for s in rig.stack)


def test_ac24_clicks_off_the_buttons_and_other_inputs_do_nothing_and_go_on():
    """The gap, above, beside, the textbox, the letterbox; then button 3, the wheel,
    Escape, and a button-1 up on a button."""
    rig = Rig()
    screen = rig.past_guard()
    for pos in [(640, 196), (640, 100), (200, 160), (640, 600)]:
        assert screen.handle_event(UiEvent(down(pos), pos, True)) is False, pos
    assert screen.handle_event(letterbox_click()) is False
    assert rig.posted == [] and screen.focus is None
    for raw in (down(B1, 3), pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1),
                key(pygame.K_ESCAPE), up(B1)):
        pos = getattr(raw, "pos", None)
        assert screen.handle_event(UiEvent(raw, pos, pos is not None)) is False, raw
    assert rig.posted == []


def test_ac24_locked_buttons_are_never_hit():
    rig = Rig(locked=(False, True, False))
    screen = rig.past_guard()
    rig.send(motion(B1))
    assert screen.handle_event(UiEvent(down(B2), B2, True)) is False
    rig.send(motion(B2))
    assert screen.focus == 0 and rig.posted == []


def test_f14_i10_rollback_inputs_fall_through():
    """F14 07 I-10: Page Up/Down, the wheel, and the shoulder buttons are rollback's; the
    choices never consume them, before or past the guard, focused or not."""
    for raw in [
        key(pygame.K_PAGEUP), key(pygame.K_PAGEDOWN),
        pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1),
        pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1),
        pygame.event.Event(pygame.CONTROLLERBUTTONDOWN,
                           button=pygame.CONTROLLER_BUTTON_LEFTSHOULDER),
        pygame.event.Event(pygame.CONTROLLERBUTTONDOWN,
                           button=pygame.CONTROLLER_BUTTON_RIGHTSHOULDER),
    ]:
        rig = Rig()
        screen = rig.open()
        for _ in range(2):
            assert screen.handle_event(UiEvent(raw, None, False)) is False, raw
            rig.send(key(pygame.K_DOWN))
            screen.update(GUARD_S, is_top=True)
        assert rig.posted == [], raw


# --- AC-F07-25 — keyboard ------------------------------------------------------------------------

LOCKED_4 = (False, True, False, False)        # c1, c2 (locked), c3, c4


def test_ac25_focus_moves_and_down_down_return_picks_c3():
    """The AC's table, each row on a fresh menu: (keys from open, focus after)."""
    for keys, focus in [
        ((), None),
        ((pygame.K_DOWN,), "c1"),
        ((pygame.K_UP,), "c4"),
        ((pygame.K_DOWN,) * 2, "c3"),
        ((pygame.K_DOWN,) * 3, "c4"),
        ((pygame.K_DOWN,) * 4, "c1"),
        ((pygame.K_UP,) * 2, "c3"),
        ((pygame.K_RETURN,), "c1"),
        ((pygame.K_SPACE,), "c1"),
        ((pygame.K_KP_ENTER,), "c1"),
    ]:
        rig = Rig(locked=LOCKED_4)
        screen = rig.past_guard()
        for k in keys:
            assert rig.send(key(k)) is True, keys
        shown = None if screen.focus is None else rig.cmd.choices[screen.focus].key
        assert shown == focus and rig.posted == [], keys
    rig = Rig(locked=LOCKED_4)
    rig.past_guard()
    for k in (pygame.K_DOWN, pygame.K_DOWN, pygame.K_RETURN):
        rig.send(key(k))
    assert rig.chosen() == ["c3"]


def test_ac25_mouse_and_keys_share_one_focus_that_is_never_cleared():
    rig = Rig(locked=LOCKED_4)
    screen = rig.past_guard()
    rig.send(key(pygame.K_DOWN))
    rig.send(motion((640, 343)))               # c4 (the AC's tops: 130, 201, 272, 343)
    assert screen.focus == 3
    rig.send(key(pygame.K_DOWN))
    assert screen.focus == 0
    rig.send(motion((640, 600)))               # off every button
    assert screen.focus == 0


def test_ac25_key_ups_and_repeats_do_nothing():
    rig = Rig(locked=LOCKED_4)
    screen = rig.past_guard()
    for k in (pygame.K_DOWN, pygame.K_RETURN, pygame.K_SPACE):
        assert rig.send(pygame.event.Event(pygame.KEYUP, key=k, mod=0)) is False
    assert rig.send(key(pygame.K_DOWN, repeat=True)) is False
    assert screen.focus is None and rig.posted == []


# --- AC-F07-26 — the 250 ms guard ----------------------------------------------------------------

def run_ms(screen: ChoiceScreen, ms: int) -> None:
    for _ in range(ms):
        screen.update(0.001, is_top=True)


def test_ac26_a_click_at_249_ms_does_nothing_and_at_250_picks():
    rig = Rig()
    screen = rig.open()
    run_ms(screen, 249)
    rig.send(down(B1))
    assert rig.posted == [] and screen.focus == 0       # hover and presses still focus
    run_ms(screen, 1)
    assert rig.posted == []                             # an ignored press is not kept
    rig.send(down(B1))
    assert rig.chosen() == ["c1"]


def test_ac26_return_waits_for_the_guard_too():
    rig = Rig()
    screen = rig.open()
    rig.send(key(pygame.K_RETURN))
    assert screen.focus == 0
    run_ms(screen, 249)
    rig.send(key(pygame.K_RETURN))
    assert rig.posted == []
    run_ms(screen, 1)
    rig.send(key(pygame.K_RETURN))
    assert rig.chosen() == ["c1"]


def test_ac26_the_guard_runs_only_from_the_first_draw_while_top_and_shown():
    rig = Rig()
    screen = rig.open(drawn=False)
    screen.update(1.0, is_top=True)            # not drawn yet
    assert screen.elapsed == 0.0
    screen.draw(None)
    screen.update(1.0, is_top=False)           # a menu on top (F10)
    rig.textbox.hidden = True
    screen.update(1.0, is_top=True)            # hidden (C8)
    assert screen.elapsed == 0.0
    rig.textbox.hidden = False
    screen.update(0.1, is_top=True)
    assert screen.elapsed == pytest.approx(0.1)


def test_c8_while_hidden_every_input_goes_on_to_the_textbox():
    rig = Rig()
    screen = rig.past_guard()
    rig.textbox.hidden = True
    for raw in (down(B1), key(pygame.K_RETURN), key(pygame.K_DOWN), motion(B2)):
        assert screen.handle_event(UiEvent(raw, getattr(raw, "pos", None), True)) is False
    assert rig.posted == [] and screen.focus is None
    canvas_free = NoDraw()
    rig.controller.view = canvas_free
    screen.draw(None)
    assert canvas_free.draws == 0


# --- AC-F07-22 (shape rule) — focus never depends on color alone ---------------------------------

def test_ac22_focus_shows_by_shape_with_the_colors_made_equal():
    pygame.init()
    try:
        theme = ChoiceTheme(focused=ChoiceFocusedTheme(fill_color=(0xFF, 0xF4, 0xF8),
                                                       border_color=(0xF0, 0xA0, 0xC0)),
                            marker=ChoiceMarkerTheme(fill_color=(0xFF, 0xF4, 0xF8)))
        view = ChoiceStackView(None, theme)
        normal = view.build_shape("normal", (800, 59), 1.0)
        focused = view.build_shape("focused", (800, 59), 1.0)
        assert normal.get_at((2, 29)) != focused.get_at((2, 29))     # border width 4 vs 2
        assert normal.get_at((3, 29)) != focused.get_at((3, 29))
        assert any(normal.get_at((x, 29)) != focused.get_at((x, 29))  # the marker's place
                   for x in range(16, 28))
    finally:
        pygame.quit()


# --- App A ---------------------------------------------------------------------------------------

def m_session(tmp_path, *, cps: int = 0, config: str = "", **edit) -> Session:
    root = make_text_game(tmp_path / "game", script=template_m(**edit),
                          config=f"[textbox]\ncps = {cps}\n" + config)
    return Session(root)


def choice_screen(s: Session) -> ChoiceScreen | None:
    return next((x for x in s.app.screens if isinstance(x, ChoiceScreen)), None)


def watch(s: Session, events: list) -> object:
    """Generator step: wait for the story and record every event it is posted."""
    yield from s.until(lambda: s.app.story is not None and s.app.textbox is not None)
    real = s.app.story.post

    def post(event):
        events.append((s.frame, event))
        real(event)

    s.app.story.post = post


def darkest(s: Session, x0: int, y0: int, w: int, h: int) -> tuple[int, int, int]:
    best = None
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            color = s.px(x, y)
            if best is None or sum(color) < sum(best):
                best = color
    return best


def near(a, b, tol=2) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def menu_sid(s: Session) -> str:
    return choice_screen(s).cmd.sid



@pytest.mark.display
def test_ac20_choices_appear_in_the_frame_the_question_completes(tmp_path, monkeypatch):
    """40 cps: nothing while the question types; pushed directly above the textbox and drawn
    in the frame F05's ``completed`` fires; the indicator place shows the box fill."""
    s = m_session(tmp_path, cps=40)
    completed: list[int] = []
    drawn: list[int] = []
    real_draw = ChoiceStackView.draw

    def draw(self, canvas, layout, states, **kw):
        drawn.append(s.frame)
        real_draw(self, canvas, layout, states, **kw)

    monkeypatch.setattr(ChoiceStackView, "draw", draw)
    seen = {}

    class Done:
        def glyph_shown(self, index, grapheme): pass
        def pause_started(self, seconds): pass
        def waiting(self, kind): pass
        def completed(self, by_press): completed.append(s.frame)

    def script(s):
        yield from s.until(lambda: s.textbox is not None)
        s.textbox.add_listener(Done())
        yield from s.until_line("Before.")
        yield from s.until(lambda: s.textbox.typer.state is TypeState.COMPLETE)
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: s.line_text() == "Will you buy a lantern?")
        while s.textbox.typer.state is not TypeState.COMPLETE:
            assert choice_screen(s) is None
            yield
        seen["stack"] = [type(x) for x in s.app.screens]
        yield
        seen["indicator"] = s.textbox.indicator_kind()
        x, y = s.textbox.view.indicator_anchor(
            s.textbox.layout.page(0), s.textbox._line_id, s.textbox.typer.shown,
            s.textbox.geometry)
        seen["probe"] = s.px(round(x) + 8, round(y) - 6)
        for _ in range(30):
            yield
            assert s.textbox.indicator_kind() is None

    s.play(script)
    assert seen["stack"][-2:] == [TextboxScreen, ChoiceScreen]
    assert drawn and drawn[0] == completed[-1]
    assert seen["indicator"] is None
    assert near(seen["probe"], (0xCC, 0xC3, 0xC6), 3)     # #FFF4F8 at 0.80 over black


@pytest.mark.display
def test_ac20_a_click_completes_the_question_and_opens_in_that_frame(tmp_path):
    s = m_session(tmp_path, cps=40)
    events: list = []
    seen = {}

    def script(s):
        yield from watch(s, events)
        yield from s.until_line("Before.")
        yield from s.until(lambda: s.textbox.typer.state is TypeState.COMPLETE)
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: s.line_text() == "Will you buy a lantern?")
        for _ in range(6):                     # 100 ms of typing
            yield
        seen["typing"] = s.textbox.typer.state is TypeState.TYPING
        s.mouse(B1)
        seen["click"] = s.frame
        yield
        seen["open"] = choice_screen(s) is not None
        for _ in range(6):                     # a second click 100 ms later: the guard
            yield
        s.mouse(B1)
        yield
        yield
        seen["still"] = choice_screen(s) is not None

    s.play(script)
    assert seen["typing"] and seen["open"] and seen["still"]
    assert [e for _, e in events if isinstance(e, Choose)] == []
    assert [type(e) for _, e in events] == [Advance]       # "Before." only


@pytest.mark.display
@pytest.mark.parametrize("edit, line", [
    ({"M": NO_QUESTION}, "Before."),
    ({"S": "$ pass", "M": NO_QUESTION}, None),
])
def test_ac20_question_less_menus(tmp_path, edit, line):
    """Kept: ``Before.`` stays complete with no indicator; first statement: no box, the
    area 16–704."""
    s = m_session(tmp_path, **edit)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.textbox is not None and s.app.story is not None)
        if line is not None:
            yield from s.until_line(line)
            s.key(pygame.K_SPACE)
        yield from s.until(lambda: choice_screen(s) is not None)
        screen = choice_screen(s)
        seen["frame_text"] = s.line_text()
        seen["indicator"] = s.textbox.indicator_kind()
        seen["area"] = (screen.layout.area.top, screen.layout.area.bottom)
        yield
        seen["box"] = s.px(640, 600)

    s.play(script)
    if line is None:
        assert seen["frame_text"] is None and seen["box"] == BLACK
        assert seen["area"] == (16, 704)
    else:
        assert seen["frame_text"] == "Before." and seen["indicator"] is None
        assert seen["area"] == (16, 446)


@pytest.mark.display
def test_ac20_a_next_question_opens_the_choices_and_posts_nothing(tmp_path):
    s = m_session(tmp_path, cps=40,
                  M='menu:⏎[8]hana "Pick one.{next}"⏎' + NO_QUESTION[len("menu:⏎"):])
    events: list = []

    def script(s):
        yield from watch(s, events)
        yield from s.until_line("Before.")
        yield from s.until(lambda: s.textbox.typer.state is TypeState.COMPLETE)
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: choice_screen(s) is not None, limit=300)
        for _ in range(10):
            yield

    s.play(script)
    assert [type(e) for _, e in events] == [Advance]


@pytest.mark.display
def test_ac22_button_looks_over_black(tmp_path):
    s = m_session(tmp_path, S="scene black")
    seen = {}

    def script(s):
        yield from s.until(lambda: choice_screen(s) is not None)
        for _ in range(8):                     # past the fade (AC-F07-29)
            yield
        seen["normal"] = [s.px(300, 160), s.px(300, 231)]
        seen["border"] = [s.px(240, 160), s.px(241, 160), s.px(242, 160)]
        seen["background"] = [s.px(240, 131), s.px(640, 120), s.px(640, 335), s.px(239, 160)]
        seen["marker_place"] = s.px(262, 160)
        seen["ink"] = darkest(s, 280, 140, 720, 40)
        s.key(pygame.K_DOWN)
        yield
        yield
        seen["focused"] = [s.px(300, 160), s.px(244, 160), s.px(262, 160)]
        seen["focused_border"] = [s.px(x, 160) for x in range(240, 244)]
        seen["focused_ink"] = darkest(s, 280, 140, 720, 40)

    s.play(script)
    assert all(near(c, FILL, 1) for c in seen["normal"])
    assert near(seen["border"][0], BORDER, 1) and near(seen["border"][1], BORDER, 1)
    assert near(seen["border"][2], FILL, 1)
    assert all(c == BLACK for c in seen["background"])
    assert near(seen["marker_place"], FILL, 1)
    assert near(seen["ink"], PLUM)
    assert near(seen["focused"][0], FOCUSED_FILL, 1)
    assert near(seen["focused"][1], FOCUSED_FILL, 1)
    assert near(seen["focused"][2], BERRY, 1)
    assert all(near(c, BERRY, 1) for c in seen["focused_border"])
    assert near(seen["focused_ink"], PLUM)


@pytest.mark.display
def test_ac22_a_locked_choice(tmp_path):
    """R2 ``coins = 1`` with ``show_locked``: the normal fill at 0.90 (07 I-3), the lock
    mark in ``#6E5E68`` at the marker's place, never a marker."""
    s = m_session(tmp_path, S="scene black", replace={2: "default coins = 1"},
                  config="[choice]\nshow_locked = true\n")
    seen = {}

    def script(s):
        yield from s.until(lambda: choice_screen(s) is not None)
        for _ in range(8):                     # past the fade
            yield
        seen["fill"] = s.px(300, 231)
        seen["lock"] = darkest(s, 256, 220, 15, 22)
        seen["text"] = darkest(s, 280, 211, 720, 40)
        for k in (pygame.K_DOWN, pygame.K_DOWN, pygame.K_UP):
            s.key(k)
            yield
            yield
            seen.setdefault("marker", []).append(s.px(262, 231))

    s.play(script)
    assert near(seen["fill"], FILL, 1)
    assert near(seen["lock"], MAUVE) and near(seen["text"], MAUVE)
    assert all(c != BERRY for c in seen["marker"])


@pytest.mark.display
def test_ac24_ac27_a_click_on_button_2_picks_and_closes_at_once(tmp_path):
    s = m_session(tmp_path, S="scene black")
    events: list = []
    seen = {}

    def script(s):
        yield from watch(s, events)
        yield from s.until(lambda: choice_screen(s) is not None)
        seen["sid"] = menu_sid(s)
        for _ in range(20):                    # past the guard
            yield
        s.event(pygame.MOUSEMOTION, pos=B2, rel=(0, 0), buttons=(0, 0, 0))
        yield
        s.mouse(B2)
        seen["click"] = s.frame
        yield
        seen["stack"] = [type(x) for x in s.app.screens]
        seen["probes"] = [s.px(300, 160), s.px(300, 231), s.px(262, 231)]

    s.play(script)
    chooses = [(f, e) for f, e in events if isinstance(e, Choose)]
    assert chooses == [(seen["click"], Choose(seen["sid"], K("The paper crane (2 coins)")))]
    assert ChoiceScreen not in seen["stack"]
    assert all(c == BLACK for c in seen["probes"])
    said = [(f, c.text) for f, c in s.said if c.text.startswith("After")]
    assert said and said[0][0] == seen["click"]      # dispatched in the pick's frame


@pytest.mark.display
def test_ac28_advance_inputs_never_pass_a_menu(tmp_path):
    s = m_session(tmp_path, cps=40)
    events: list = []
    seen = {}

    def presses(s):
        for _ in range(10):
            s.mouse((640, 600))
            yield
        # AC-F07-28 amended: the wheel is a rollback input since F14 (AC-F14-20: wheel up
        # over choices steps back), so it is left out here.
        s.key(pygame.K_LCTRL, pygame.KMOD_CTRL)
        yield

    def script(s):
        yield from watch(s, events)
        yield from s.until_line("Before.")
        yield from s.until(lambda: s.textbox.typer.state is TypeState.COMPLETE)
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: s.line_text() == "Will you buy a lantern?")
        yield
        s.key(pygame.K_SPACE)                  # completes the question, posts nothing
        yield
        yield from s.until(lambda: choice_screen(s) is not None)
        yield from presses(s)                  # within the guard
        s.key(pygame.K_SPACE)
        yield
        seen["focus"] = choice_screen(s).focus
        for _ in range(20):
            yield
        yield from presses(s)                  # past it
        seen["open"] = choice_screen(s) is not None
        seen["auto"] = s.textbox.menu_waiting

    s.play(script)
    assert [type(e) for _, e in events] == [Advance]       # "Before." only
    assert seen["focus"] == 0 and seen["open"] and seen["auto"]


@pytest.mark.display
def test_ac28_the_textbox_never_posts_while_a_menu_waits(tmp_path):
    """``wait_for_menu`` direct: press, idle advance, and ``{next}`` post nothing."""
    s = m_session(tmp_path)
    seen = {}

    def script(s):
        yield from s.until_line("Before.")
        tb = s.textbox
        idle: list = []
        tb.on_idle_advance = lambda: idle.append(1)
        opened: list = []
        tb.wait_for_menu(lambda: opened.append(s.frame))
        yield
        tb.press()
        tb.press()
        seen["posted"] = [e for _, e in s.posted]
        seen["opened"] = list(opened)          # once, in the update after the call
        tb.clear()
        tb.wait_for_menu(lambda: opened.append(-1))
        tb.press()
        seen["idle"] = idle
        yield
        seen["after_clear"] = list(opened)
        tb.on_idle_advance = None

    s.play(script)
    assert seen["posted"] == [] and seen["idle"] == []
    assert len(seen["opened"]) == 1 and seen["after_clear"][1:] == [-1]


# --- AC-F07-34 — a restored menu on screen (F07 step 3) ------------------------------------------

class Cover(Screen):
    """An opaque test screen standing in for F11's load screen. ``in_game`` False (as F11's):
    the story isn't pumped under it, so the restore burst arrives at the pop; True: the burst
    arrives while it covers the textbox, so the controller's wait is what holds the menu."""

    def __init__(self, in_game: bool) -> None:
        self.in_game = in_game

    def handle_event(self, event: UiEvent) -> bool:
        return True


def saved_menu(s: Session):
    """Generator step: play to Template M's menu; returns Bm (through its JSON)."""
    import json

    from engine.runtime.state import GameState

    yield from s.until(lambda: s.app.story is not None and s.app.textbox is not None)
    yield from s.until_line("Before.")
    yield from s.until(lambda: s.textbox.typer.state is TypeState.COMPLETE)
    s.key(pygame.K_SPACE)
    yield from s.until(lambda: choice_screen(s) is not None)
    return GameState.from_json(json.loads(json.dumps(s.app.story.checkpoint().to_json())))


def count_choice_screens(s: Session) -> int:
    return sum(isinstance(x, ChoiceScreen) for x in s.app.screens)


@pytest.mark.display
@pytest.mark.parametrize("in_game", [False, True], ids=["f11-like", "in-game"])
def test_ac34_a_restored_menu_opens_once_the_cover_goes(tmp_path, in_game):
    from engine.runtime.interpreter import RestoreResult

    s = m_session(tmp_path, cps=40)
    seen: dict = {}

    def script(s):
        bm = yield from saved_menu(s)
        for _ in range(20):
            yield
        s.mouse(B1)                                      # pick: "After: red."
        yield from s.until(lambda: (s.line_text() or "").startswith("After"))
        cover = Cover(in_game)
        s.app.screens.push(cover)
        seen["outcome"] = s.app.story.restore(bm).result
        covered = []
        for _ in range(60):                              # 1 s under the cover
            yield
            covered.append(count_choice_screens(s))
        seen["covered"] = covered
        seen["line under cover"] = s.line_text()
        s.app.screens.remove(cover)
        seen["pop"] = s.frame
        yield                                            # the first frame after the pop
        screen = choice_screen(s)
        seen["stack"] = [type(x) for x in s.app.screens][-2:]
        seen["line"] = s.line_text()
        seen["restored"] = s.textbox.line.restored
        seen["complete"] = s.textbox.typer.state is TypeState.COMPLETE
        seen["indicator"] = s.textbox.indicator_kind()
        seen["focus"] = screen.focus
        seen["first"] = (screen.started, screen.elapsed)
        yield
        seen["next"] = screen.elapsed
        # Restored again while that menu is open, from a test screen above.
        cover = Cover(in_game)
        s.app.screens.push(cover)
        seen["again"] = s.app.story.restore(bm).result
        for _ in range(3):
            yield
        seen["old gone"] = screen not in list(s.app.screens) if in_game else None
        s.app.screens.remove(cover)
        yield
        yield
        seen["one"] = count_choice_screens(s)
        seen["new"] = choice_screen(s) is not screen

    s.play(script)
    assert seen["outcome"] is RestoreResult.OK and seen["again"] is RestoreResult.OK
    assert seen["covered"] == [0] * 60
    if in_game:                                          # the burst came under the cover
        assert seen["line under cover"] == "Will you buy a lantern?"
        assert seen["old gone"] is True                  # ScreenStack.remove under it
    assert seen["stack"] == [TextboxScreen, ChoiceScreen]
    assert seen["line"] == "Will you buy a lantern?" and seen["restored"]
    assert seen["complete"] and seen["indicator"] is None
    assert seen["focus"] is None
    assert seen["first"] == (True, 0.0)                  # drawn in that frame; guard from it
    assert seen["next"] == pytest.approx(1 / 60)
    assert seen["one"] == 1 and seen["new"]


@pytest.mark.display
def test_ac34_a_new_game_while_a_menu_is_open_removes_it(tmp_path):
    s = m_session(tmp_path)
    seen: dict = {}

    def script(s):
        yield from saved_menu(s)
        s.app.story.new_game()
        yield
        yield
        seen["count"] = count_choice_screens(s)
        seen["line"] = s.line_text()
        seen["controller"] = s.app.choices.screen

    s.play(script)
    assert seen["count"] == 0 and seen["controller"] is None
    assert seen["line"] == "Before."


# --- F07 step 4 — AC-F07-29 — fade-in and motion (unit) -------------------------------------------

def draws(screen: ChoiceScreen, frames: int) -> None:
    for _ in range(frames):
        screen.update(1 / 60, is_top=True)
        screen.draw(None)


def test_ac29_the_fade_ramps_from_the_open_frame():
    """07 I-7: frame k after the first draw has alpha ``min(1, (k + 1) / 7.2)``."""
    rig = Rig()
    screen = rig.open()
    draws(screen, 9)
    expected = [min(1.0, (k + 1) / 7.2) for k in range(10)]
    assert rig.controller.view.alphas == pytest.approx(expected)
    assert rig.controller.view.alphas[7] == 1.0


def test_ac29_no_fade():
    for how in ("fade_in_ms 0", "reduce motion", "restored", "F14 sets 0"):
        rig = Rig(theme=ChoiceTheme(fade_in_ms=0) if how == "fade_in_ms 0" else None,
                  restored=how == "restored")
        rig.textbox.reduced = how == "reduce motion"
        rig.textbox.on_shown()
        screen = rig.stack.top
        if how == "F14 sets 0":
            screen.fade = 0                    # F14 07 A5: a per-screen value
        screen.draw(None)
        assert rig.controller.view.alphas == [1.0], how


def test_ac29_reduce_motion_turned_on_mid_fade_ends_it():
    rig = Rig()
    screen = rig.open()
    rig.textbox.reduced = True
    draws(screen, 1)
    assert rig.controller.view.alphas == [pytest.approx(1 / 7.2), 1.0]


def test_ac29_the_guard_doesnt_wait_for_a_long_fade():
    rig = Rig(theme=ChoiceTheme(fade_in_ms=1000))
    screen = rig.open()
    run_ms(screen, 250)
    assert screen.alpha() < 0.3
    rig.send(down(B1))
    assert rig.chosen() == ["c1"]


# --- AC-F07-30 — hide (unit: the inputs that hide) ------------------------------------------------

def test_ac30_hide_inputs_and_a_letterbox_middle_click():
    """H (Shift allowed), button 2, and pad Y hide; Ctrl/Alt/Meta+H is App A's
    ``test_ac30_hide_and_show``. A middle click in the letterbox doesn't hide."""
    for raw in (key(pygame.K_h),
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h, mod=pygame.KMOD_LSHIFT),
                down(B1, 2),
                pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=0,
                                   button=pygame.CONTROLLER_BUTTON_Y)):
        rig = Rig()
        screen = rig.past_guard()
        pos = getattr(raw, "pos", None)
        assert screen.handle_event(UiEvent(raw, pos, True)) is True, raw
        assert rig.textbox.hidden and rig.posted == [], raw
    rig = Rig()
    screen = rig.past_guard()
    assert screen.handle_event(UiEvent(down((50, 160), 2), (-110, 160), False)) is False
    assert not rig.textbox.hidden


# --- AC-F07-31 — gamepad (unit: B and the other buttons go on) ------------------------------------

def pad(button):
    return pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=0, button=button)


def stick(value, axis=pygame.CONTROLLER_AXIS_LEFTY):
    return pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=0, axis=axis,
                              value=value)


def test_ac31_other_pad_inputs_go_on():
    """B, X, Start, D-pad left, the left stick's x, the right stick, and A's release.
    (The stick's one-step-per-push rows are App A's ``test_ac31_gamepad``.)"""
    rig = Rig()
    screen = rig.past_guard()
    for raw in (pad(pygame.CONTROLLER_BUTTON_B), pad(pygame.CONTROLLER_BUTTON_X),
                pad(pygame.CONTROLLER_BUTTON_START), pad(pygame.CONTROLLER_BUTTON_DPAD_LEFT),
                stick(30000, pygame.CONTROLLER_AXIS_LEFTX),
                stick(30000, pygame.CONTROLLER_AXIS_RIGHTY),
                pygame.event.Event(pygame.CONTROLLERBUTTONUP, instance_id=0,
                                   button=pygame.CONTROLLER_BUTTON_A)):
        assert screen.handle_event(UiEvent(raw, None, False)) is False, raw
    assert rig.posted == [] and screen.focus is None


# --- AC-F07-32 — number keys ----------------------------------------------------------------------

def test_ac32_a_number_picks_the_nth_pickable():
    for k in (pygame.K_2, pygame.K_KP2):
        rig = Rig(locked=LOCKED_4)
        rig.past_guard()
        assert rig.send(key(k)) is True
        assert rig.chosen() == ["c3"]


def test_ac32_out_of_range_and_during_the_guard_do_nothing():
    rig = Rig(locked=LOCKED_4)
    screen = rig.open()
    assert rig.send(key(pygame.K_1)) is True and rig.posted == []     # in the guard
    run_ms(screen, 250)
    assert rig.send(key(pygame.K_4)) is False and rig.send(key(pygame.K_7)) is False
    assert rig.send(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1,
                                       mod=pygame.KMOD_LCTRL)) is False
    assert rig.posted == [] and screen.focus is None
    rig.send(key(pygame.K_3))
    assert rig.chosen() == ["c4"]


# --- AC-F07-36, 38 (unit): listeners and sounds ---------------------------------------------------

class Listener:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def menu_shown(self, cmd):
        self.calls.append(("shown", cmd))

    def focus_changed(self, key):
        self.calls.append(("focus", key))

    def picked(self, key):
        self.calls.append(("picked", key))


def test_ac36_ac38_listeners_and_sounds_in_order():
    rig = Rig(focus_sound="focus.wav", pick_sound="pick.wav")
    heard = Listener()
    rig.controller.add_listener(heard)
    order: list = []
    rig.controller.play = lambda f: order.append(("play", f))
    rig.controller.post = lambda e: order.append(("post", e))
    heard.calls = order
    screen = rig.open()
    screen.draw(None)                                  # a second draw: no second menu_shown
    rig.send(motion(B1))
    rig.send(motion(B1))                               # already focused: nothing
    rig.send(key(pygame.K_DOWN))
    screen.update(GUARD_S, is_top=True)
    rig.send(key(pygame.K_RETURN))
    assert order == [("shown", rig.cmd), ("focus", "c1"), ("play", "focus.wav"),
                     ("focus", "c2"), ("play", "focus.wav"), ("picked", "c2"),
                     ("play", "pick.wav"), ("post", Choose("menu/1", "c2"))]


def test_ac38_no_tokens_no_sound():
    rig = Rig()
    rig.past_guard()
    rig.send(key(pygame.K_DOWN))
    rig.send(key(pygame.K_RETURN))
    assert rig.chosen() == ["c1"] and rig.played == []


# --- App A: AC-F07-29 -----------------------------------------------------------------------------

def scaled(color, alpha):
    return tuple(c * alpha for c in color)


@pytest.mark.display
def test_ac29_the_fade_on_screen(tmp_path):
    """Over ``scene black``: frame k's fill probe is the fill × ``min(1, (k + 1) / 7.2)``;
    full from k = 7; frames 8–120 with no input are pixel-identical."""
    s = m_session(tmp_path, S="scene black")
    seen = {"probe": [], "changed": []}

    def raw() -> bytes:
        return s.fb.get_buffer().raw              # a plain copy: compared with memcmp

    def script(s):
        yield from s.until(lambda: choice_screen(s) is not None)  # frame k = 0 is presented
        for k in range(121):
            if k <= 8:
                seen["probe"].append(s.px(300, 160))
            if k == 8:
                first = raw()
                seen["composite"] = s.app.choices.view.fade_surface
            elif k > 8 and raw() != first:
                seen["changed"].append(k)
            yield

    s.play(script)
    for k, color in enumerate(seen["probe"]):
        assert near(color, scaled(FILL, min(1.0, (k + 1) / 7.2))), (k, color)
    assert seen["probe"][7] == seen["probe"][8] == FILL
    assert seen["changed"] == []
    assert seen["composite"] is None                  # freed once alpha reached 1 (I-13)


@pytest.mark.display
def test_ac29_reduce_motion_on_screen(tmp_path):
    """The real textbox's ``reduce_motion`` reaches the choices. ``fade_in_ms = 0`` is the
    unit ``test_ac29_no_fade`` (the token's parse is ``tests/core/test_config_choice.py``)."""
    s = m_session(tmp_path, S="scene black")
    seen = {}

    def script(s):
        yield from s.until(lambda: s.textbox is not None)
        s.textbox.settings.reduce_motion = True
        yield from s.until(lambda: choice_screen(s) is not None)
        seen["first"] = s.px(300, 160)

    s.play(script)
    assert near(seen["first"], FILL, 1)


@pytest.mark.display
def test_ac29_a_down_during_the_fade_shows_focus_in_the_next_frame(tmp_path):
    s = m_session(tmp_path, S="scene black")
    seen = {}

    def script(s):
        yield from s.until(lambda: choice_screen(s) is not None)  # k = 0
        yield
        yield                                                       # k = 2
        s.key(pygame.K_DOWN)
        yield                                                       # k = 3: focused
        seen["fill"] = s.px(300, 160)
        seen["marker"] = s.px(262, 160)

    s.play(script)
    alpha = 4 / 7.2
    assert near(seen["fill"], scaled(FOCUSED_FILL, alpha))
    assert near(seen["marker"], scaled(BERRY, alpha))


# --- App A: AC-F07-30 — hide and show -------------------------------------------------------------

def pad_event(s: Session, button: int) -> None:
    s.event(pygame.CONTROLLERBUTTONDOWN, instance_id=0, button=button)


SHOW_INPUTS = [
    ("button 1", lambda s: s.mouse(B1)),
    ("Return", lambda s: s.key(pygame.K_RETURN)),
    ("Space", lambda s: s.key(pygame.K_SPACE)),
    ("H", lambda s: s.key(pygame.K_h)),
    ("button 2", lambda s: s.mouse(B1, 2)),
    ("gamepad Y", lambda s: pad_event(s, pygame.CONTROLLER_BUTTON_Y)),
]
HIDE_INPUTS = [
    ("H", lambda s: s.key(pygame.K_h)),
    ("button 2", lambda s: s.mouse(B2, 2)),
    ("gamepad Y", lambda s: pad_event(s, pygame.CONTROLLER_BUTTON_Y)),
]


@pytest.mark.display
def test_ac30_hide_and_show(tmp_path):
    """Each input hides and shows with c2 kept, nothing posted; the guard counts only the
    shown frames (hidden time doesn't count; the 249/250 ms edge is the unit AC-26 test)."""
    s = m_session(tmp_path, S="scene black")
    events: list = []
    seen: dict = {"hides": [], "shows": [], "mods": []}

    def script(s):
        yield from watch(s, events)
        yield from s.until(lambda: choice_screen(s) is not None)
        screen = choice_screen(s)
        s.key(pygame.K_DOWN)
        s.key(pygame.K_DOWN)                       # c2 focused
        for _ in range(6):
            yield                                  # elapsed 100 ms
        for mod in (pygame.KMOD_LCTRL, pygame.KMOD_LALT, pygame.KMOD_LMETA):
            s.key(pygame.K_h, mod)
            yield
            seen["mods"].append(s.textbox.hidden)
        start = screen.elapsed
        shown = 0
        for index, (name, show) in enumerate(SHOW_INPUTS):
            hide_name, hide = HIDE_INPUTS[index % len(HIDE_INPUTS)]
            hide(s)
            yield
            seen["hides"].append((hide_name, s.textbox.hidden, s.px(300, 160), s.px(300, 231),
                                  s.px(640, 600)))
            for _ in range(5):
                yield                              # hidden: no guard time
            show(s)
            yield
            shown += 1
            seen["shows"].append((name, s.textbox.hidden, screen.focus,
                                  choice_screen(s) is screen))
        seen["elapsed"] = (start, shown, screen.elapsed)

    s.play(script)
    assert seen["mods"] == [False, False, False]
    for name, hidden, *probes in seen["hides"]:
        assert hidden and all(c == BLACK for c in probes), name
    for name, hidden, focus, same in seen["shows"]:
        assert not hidden and focus == 1 and same, name
    assert events == []                            # no Choose, no Advance
    start, shown, elapsed = seen["elapsed"]
    assert elapsed == pytest.approx(start + shown / 60)


# --- App A: AC-F07-31 — gamepad -------------------------------------------------------------------

@pytest.mark.display
def test_ac31_gamepad(tmp_path):
    s = m_session(tmp_path)
    events: list = []
    seen = {"focus": []}
    steps = [
        ("added", lambda s: s.event(pygame.CONTROLLERDEVICEADDED, device_index=0, which=0)),
        ("A", lambda s: pad_event(s, pygame.CONTROLLER_BUTTON_A)),
        ("down", lambda s: pad_event(s, pygame.CONTROLLER_BUTTON_DPAD_DOWN)),
        ("up", lambda s: pad_event(s, pygame.CONTROLLER_BUTTON_DPAD_UP)),
        ("up", lambda s: pad_event(s, pygame.CONTROLLER_BUTTON_DPAD_UP)),
    ] + [(f"stick {v}", lambda s, v=v: s.event(
        pygame.CONTROLLERAXISMOTION, instance_id=0, axis=pygame.CONTROLLER_AXIS_LEFTY, value=v))
        for v in (20000, 32767, 9000, 8000, 20000, 0, -20000)]

    def script(s):
        yield from watch(s, events)
        yield from s.until_line("Before.")
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: choice_screen(s) is not None)
        screen = choice_screen(s)
        for _ in range(20):
            yield                                  # past the guard
        for name, step in steps:
            step(s)
            yield
            seen["focus"].append((name, screen.focus))
        pad_event(s, pygame.CONTROLLER_BUTTON_A)   # picks the focused one
        yield
        yield

    s.play(script)
    assert [f for _, f in seen["focus"]] == [None, 0, 1, 0, 2, 0, 0, 0, 0, 1, 1, 0]
    chooses = [e for _, e in events if isinstance(e, Choose)]
    assert [c.choice for c in chooses] == [K("The red one")]


# --- App A: AC-F07-33 — covered, resized, fullscreen ----------------------------------------------

@pytest.mark.display
def test_ac33_a_screen_on_top_pauses_focus_and_the_guard(tmp_path):
    s = m_session(tmp_path, S="scene black")
    events: list = []
    seen = {}

    def script(s):
        yield from watch(s, events)
        yield from s.until(lambda: choice_screen(s) is not None)
        screen = choice_screen(s)
        s.key(pygame.K_DOWN)
        s.key(pygame.K_DOWN)                       # c2 focused
        for _ in range(6):
            yield                                  # elapsed 100 ms
        cover = Cover(False)
        cover.opaque = True
        s.app.screens.push(cover)
        for frame in range(120):                   # 2 s
            if frame % 10 == 0:
                s.key(pygame.K_DOWN)
                s.mouse(B1)
            yield
        seen["covered"] = (screen.focus, screen.elapsed)
        s.app.screens.remove(cover)
        for _ in range(8):
            yield
        s.mouse(B2)                                # 8 frames after the pop: 233 ms
        yield
        yield
        seen["early"] = [e for _, e in events]
        s.mouse(B2)                                # 10 frames after: 267 ms
        yield

    s.play(script)
    assert seen["covered"] == (1, pytest.approx(0.1))
    assert seen["early"] == []
    assert [e.choice for _, e in events] == [K("The paper crane (2 coins)")]


@pytest.mark.display
def test_ac33_resize_and_fullscreen_keep_focus_and_guard(tmp_path):
    s = m_session(tmp_path, S="scene black")
    seen = {}

    def script(s):
        yield from s.until(lambda: choice_screen(s) is not None)
        screen = choice_screen(s)
        layout = screen.layout
        s.key(pygame.K_DOWN)
        s.key(pygame.K_DOWN)                       # c2 focused
        for _ in range(6):
            yield
        before = screen.elapsed
        s.window.resize(1600, 900)
        s.window.desktop = (1600, 900)
        yield
        s.key(pygame.K_F11)                        # fullscreen at the desktop size
        for _ in range(20):                        # past the resize settle
            yield
        seen["state"] = (choice_screen(s) is screen, screen.focus, screen.layout is layout,
                         s.window.fullscreen)
        seen["elapsed"] = (before, screen.elapsed)
        seen["border"] = [s.px(x, 200) for x in (299, 300)]   # canvas (240, 160) × 1.25

    s.play(script)
    assert seen["state"] == (True, 1, True, True)
    before, after = seen["elapsed"]
    assert after == pytest.approx(before + 21 / 60)
    assert seen["border"][0] == BLACK and near(seen["border"][1], BORDER, 2)


# --- App A: AC-F07-36 and 38 — listeners, and sounds through App.audio.play_ui -------------------

@pytest.mark.display
def test_ac36_ac38_listeners_and_sounds(tmp_path, monkeypatch):
    """One run with both sound tokens: motion focuses c1, motion over it again does
    nothing, Down focuses c2, Return picks. ``menu_shown`` once in the first drawn frame;
    focus K(red) then K(crane); one pick; the say listener gets the question; ``play_ui``
    plays focus twice and pick once, each after its change. (No tokens, no sound: the unit
    ``test_ac38_no_tokens_no_sound``.)"""
    from engine.audio.service import AudioService
    from engine.core.config_schema import AudioConfig
    from engine.core.lru import SizedLru
    from tests.fakes.fake_mixer import FakeMixer
    from tests.fixtures.F08.make_audio import tone_wav

    config = '[theme.choice]\nfocus_sound = "focus.wav"\npick_sound = "pick.wav"\n'
    root = make_text_game(tmp_path / "game", script=template_m(),
                          config="[textbox]\ncps = 0\n" + config)
    (root / "audio").mkdir()
    for name in ("focus.wav", "pick.wav"):
        (root / "audio" / name).write_bytes(tone_wav(0.1))
    s = Session(root)
    order: list = []
    says: list = []
    drawn: list[int] = []
    frames: dict = {}
    real_draw = ChoiceStackView.draw

    def draw(self, canvas, layout, states, **kw):
        drawn.append(s.frame)
        real_draw(self, canvas, layout, states, **kw)

    monkeypatch.setattr(ChoiceStackView, "draw", draw)

    class Recording(AudioService):
        def play_ui(self, file, **kw):
            order.append(("play_ui", file))
            super().play_ui(file, **kw)

    class Heard(Listener):
        def menu_shown(self, cmd):
            frames["shown"] = s.frame
            super().menu_shown(cmd)

    def script(s):
        yield from s.until(lambda: s.app.story is not None and s.textbox is not None)
        s.app.audio = Recording(s.paths, SizedLru(1 << 22), AudioConfig(), backend=FakeMixer())
        heard = Heard()
        heard.calls = order
        s.app.choices.add_listener(heard)
        s.textbox.add_say_listener(says.append)
        yield from s.until_line("Before.")
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: choice_screen(s) is not None)
        for _ in range(20):
            yield
        s.event(pygame.MOUSEMOTION, pos=B1, rel=(0, 0), buttons=(0, 0, 0))
        yield
        s.event(pygame.MOUSEMOTION, pos=(B1[0] + 50, B1[1]), rel=(0, 0), buttons=(0, 0, 0))
        yield                                      # over the focused button: nothing
        s.key(pygame.K_DOWN)
        yield
        s.key(pygame.K_RETURN)
        yield
        yield
        s.app.audio = None

    s.play(script)
    assert [c[0] for c in order] == ["shown", "focus", "play_ui", "focus", "play_ui",
                                     "picked", "play_ui"]
    assert isinstance(order[0][1], ShowMenu) and frames["shown"] == drawn[0]
    assert [c for c in order if c[0] != "play_ui"][1:] == [
        ("focus", K("The red one")), ("focus", K("The paper crane (2 coins)")),
        ("picked", K("The paper crane (2 coins)"))]
    assert [c for c in order if c[0] == "play_ui"] == [("play_ui", "focus.wav")] * 2 + [
        ("play_ui", "pick.wav")]
    assert [c.text for c in says][:2] == ["Before.", "Will you buy a lantern?"]


# --- App A: AC-F07-42 — drawing cost stays bounded (the CI guard, F07 step 5) ----------------

# AC-F07-21 row F's six two-line choices: row F's 60 "a"s are two lines in M20, but one
# line in the real font once the fit rule steps down, so App A uses 60 "m"s, which stay two
# lines at 20 and so reach row F's step 3.
M60 = "m" * 60


@pytest.mark.display
def test_ac42_drawing_cost_stays_bounded(tmp_path, monkeypatch):
    """1920×1080, row F's six two-line choices under a question; after the fade, Down every
    frame for 120 frames. After the first focus cycle (six Downs) the choices' drawing makes
    no ``AssetManager.text_line`` call (other screens, such as F10's quick menu, have their
    own) and builds no shape; the shape cache holds ≤ 6; no glyph
    surface from ``text_line`` gets an alpha; the fade composite is unreachable once alpha is
    1; the open frame's work is ≤ 50 ms (the frame's real time, with the test's spies)."""
    import gc
    import time
    import weakref

    from engine.render.assets import AssetManager

    menu = 'menu:⏎[8]hana "Will you buy a lantern?"⏎' + "⏎".join(
        f'[8]"{M60}":⏎[12]$ pass' for _ in range(6))
    root = make_text_game(tmp_path / "game", script=template_m(M=menu),
                          config="[textbox]\ncps = 0\n")
    s = Session(root, size=(1920, 1080))
    counts = {"text_line": 0, "shape": 0}
    glyphs: list[tuple[pygame.Surface, int | None]] = []
    real_text_line = AssetManager.text_line
    real_glyphs = ChoiceStackView._build_glyphs
    real_build = ChoiceStackView.build_shape
    inside = [False]           # the choices' text_line calls (the quick menu has its own)

    def build_glyphs(self, *args, **kwargs):
        inside[0] = True
        try:
            return real_glyphs(self, *args, **kwargs)
        finally:
            inside[0] = False

    def text_line(self, *args, **kwargs):
        surface = real_text_line(self, *args, **kwargs)
        if inside[0]:
            counts["text_line"] += 1
            glyphs.append((surface, surface.get_alpha()))
        return surface

    def build_shape(self, *args, **kwargs):
        counts["shape"] += 1
        return real_build(self, *args, **kwargs)

    monkeypatch.setattr(AssetManager, "text_line", text_line)
    monkeypatch.setattr(ChoiceStackView, "_build_glyphs", build_glyphs)
    monkeypatch.setattr(ChoiceStackView, "build_shape", build_shape)
    seen: dict = {"cache": []}

    def script(s):
        yield from s.until_line("Before.")
        s.key(pygame.K_SPACE)
        started = time.perf_counter()
        while choice_screen(s) is None:                 # the open frame is the last one
            started = time.perf_counter()
            yield
        seen["open_ms"] = (time.perf_counter() - started) * 1000.0
        view = s.app.choices.view
        seen["layout"] = (choice_screen(s).layout.step, len(choice_screen(s).layout.buttons),
                          [len(b.lines) for b in choice_screen(s).layout.buttons])
        fade = view.fade_surface
        seen["fading"] = fade is not None
        ref = weakref.ref(fade) if fade is not None else None
        del fade
        for _ in range(10):                             # past the fade (7.2 frames)
            yield
        for frame in range(120):
            s.key(pygame.K_DOWN)
            yield
            if frame == 5:                              # the first focus cycle is done
                seen["after_cycle"] = dict(counts)
            seen["cache"].append(view.shape_count)
        seen["end"] = dict(counts)
        seen["focus"] = choice_screen(s).focus
        gc.collect()
        seen["composite_dead"] = ref is None or ref() is None
        seen["composite_kept"] = view.fade_surface

    s.play(script)
    assert seen["layout"] == (3, 6, [2] * 6)                       # row F: step 3, two lines
    assert seen["fading"] and seen["composite_dead"] and seen["composite_kept"] is None
    assert seen["end"] == seen["after_cycle"]                      # nothing after the cycle
    assert seen["after_cycle"]["text_line"] > 0 and seen["after_cycle"]["shape"] > 0
    assert max(seen["cache"]) <= 6
    assert seen["focus"] is not None
    assert all(surface.get_alpha() == alpha for surface, alpha in glyphs)
    assert seen["open_ms"] <= 50.0, seen["open_ms"]
