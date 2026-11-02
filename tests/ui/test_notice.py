"""F11 step 5 (with step 7's notice hooks): ``ui/notice.NoticeLayer``, ``GameShell.notify`` /
``update_layer`` / ``draw_layer`` / ``clear_notices``, ``Screen.holds_notices`` (C7), and
``App``'s frame order (C9).

**Notice N** (``06`` §0.2): the layer with a fake clock (``update(dt, focused=…)``) and a
fake pointer. Geometry rows use F05's M20 metrics (17 units per character at 24), as
AC-F11-50 does; pixel probes draw with the bundled font on the 1280×720 unit canvas under
the dummy driver. AC-F11-50 and 51 are proved here (their App S rows wait for step 8).
"""

import math

import pygame
import pytest

from engine.core.config_schema import Config, NoticeTheme, ThemeConfig
from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.focus import Box
from engine.ui.notice import (
    NoticeLayer,
    NoticeStyle,
    clean_text,
    ease_in_out,
    notice_panel,
    notice_style,
    shown_ms,
)
from engine.ui.paint import Painter
from engine.ui.screen import Screen, ScreenStack
from engine.ui.shell import GameShell, ShellPorts
from engine.ui.theme import Words, measure_with, plain_theme
from tests.fakes.audio_spy import AudioSpy
from tests.fakes.fixed_font import FixedFont
from tests.render.conftest import make_assets

FRAME = 1 / 60
PINK_WHITE = (0xFF, 0xF4, 0xF8)
BERRY = (0xA0, 0x28, 0x60)
STAGE = (40, 90, 160)


def m20(text: str, size: int) -> float:
    return FixedFont(size).size(text)[0]


def layer(style: NoticeStyle | None = None, *, reduce: bool = False, scale: float = 1.0,
          play=None) -> NoticeLayer:
    return NoticeLayer(style or NoticeStyle(), m20, text_scale=lambda: scale,
                       reduce_motion=lambda: reduce, play=play)


def run(notices: NoticeLayer, seconds: float, dt: float = 0.01, **kwargs) -> None:
    for _ in range(round(seconds / dt)):
        notices.update(dt, **kwargs)


def only(notices: NoticeLayer):
    (view,) = notices.views()
    return view


def close(a, b, tol=2) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def over(fg, a, bg) -> tuple[int, int, int]:
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg, bg))


# --- AC-F11-50: look (M20) -------------------------------------------------------------------

def test_quick_saved_panel_and_text_position():
    notices = layer()
    notices.notify("Quick saved.")
    run(notices, 0.2)
    view = only(notices)
    assert view.phase == "shown" and view.opacity == 1.0
    assert view.box == Box(1012, 24, 244, 58)
    panel = notice_panel("Quick saved.", "info", m20, size=24)
    assert (view.box.x + panel.text_x, view.box.y + 12) == (1032, 36)
    assert panel.bar is None and view.lines == ("Quick saved.",)


def test_problem_notice_has_its_bar_and_wider_inset():
    notices = layer()
    notices.notify("This save is too large.", kind="problem")
    run(notices, 0.2)
    view = only(notices)
    assert view.box == Box(807, 24, 449, 58)
    panel = notice_panel("This save is too large.", "problem", m20, size=24)
    assert panel.bar is not None
    bar = panel.bar.moved(view.box.x, view.box.y)
    assert bar == Box(819, 36, 6, 34)
    assert view.box.x + panel.text_x == 845


def test_second_notice_is_8_below_the_first():
    notices = layer()
    notices.notify("Quick saved.")
    notices.notify("No quick save yet.")
    run(notices, 0.2)
    first, second = notices.views()
    assert first.box.bottom == 82 and second.box.y == 90
    assert second.box.right == 1256


def test_long_text_is_560_wide_with_4_lines_ending_in_an_ellipsis():
    text = " ".join(["word"] * 60)[:300]
    panel = notice_panel(text, "info", m20, size=24)
    assert (panel.width, panel.height) == (560, 160)
    assert len(panel.lines) == 4 and panel.lines[-1].endswith("…") and panel.truncated
    assert all(m20(line, 24) <= 520 for line in panel.lines)


def test_short_text_is_at_least_160_wide():
    assert notice_panel("OK", "info", m20, size=24).width == 160


def test_three_tall_notices_the_third_waits_above_y_400():
    notices = layer()
    texts = [f"{n} " + " ".join(["word"] * 60)[:300] for n in range(3)]
    for text in texts:
        notices.notify(text)
    shown = notices.views()
    assert [v.box.h for v in shown] == [160, 160]
    assert [v.box.y for v in shown] == [24, 192]
    assert notices.waiting() == (texts[2],)
    run(notices, 2.0)
    assert all(v.box.bottom <= 400 for v in notices.views())


def test_text_at_150_percent_is_size_36():
    notices = layer(scale=1.5)
    notices.notify("Quick saved.")
    run(notices, 0.2)
    view = only(notices)
    assert view.size == 36
    assert view.box.h == 50 + 24                       # pitch(36) = 50


def test_four_lines_at_150_percent_still_end_above_400():
    notices = layer(scale=1.5)
    notices.notify("x " * 400)
    run(notices, 0.2)
    view = only(notices)
    assert len(view.lines) == 4 and view.box.bottom == 24 + 4 * 50 + 24 <= 400


def test_missing_notice_frame_is_w64_and_the_drawn_notice_is_used(tmp_path, caplog):
    import dataclasses

    from engine.core.paths import GamePaths
    from engine.ui.theme import resolve_theme
    from tests.render.conftest import copy_game

    game = GamePaths.for_game(copy_game("assets", tmp_path / "game"))
    theme_cfg = dataclasses.replace(ThemeConfig(), notice=NoticeTheme(frame_image="gui/n.png"))
    theme = resolve_theme(dataclasses.replace(Config(), theme=theme_cfg), make_assets(game))
    (message,) = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W64"]
    assert message == ('config.toml: [theme.notice] frame_image "gui/n.png" doesn\'t exist, so '
                       "the drawn notice is used.")
    assert theme.frames["notice"] is None and notice_style(theme).image is None


def test_style_follows_panel_tokens_unless_set():
    theme = plain_theme()
    style = notice_style(theme)
    panel = theme.cfg.panel
    assert style.frame.fill_color == panel.fill_color == PINK_WHITE
    assert style.frame.fill_opacity == 0.94
    assert style.frame.border_color == panel.border_color
    assert (style.frame.border_width, style.frame.corner_radius) == (2, 12)
    assert style.text_color == panel.text_color and style.marker_color == BERRY
    assert (style.font.size, style.max_width, style.duration_ms, style.fade_ms) == (
        24, 560, 1500, 200)
    own = plain_theme(ThemeConfig(notice=NoticeTheme(
        fill_color=(1, 2, 3), fill_opacity=0.5, border_color=(4, 5, 6), text_color=(7, 8, 9),
        max_width=320)))
    style = notice_style(own)
    assert (style.frame.fill_color, style.frame.fill_opacity, style.frame.border_color) == (
        (1, 2, 3), 0.5, (4, 5, 6))
    assert style.text_color == (7, 8, 9) and style.max_width == 320


# --- AC-F11-51: timing and stack (fake clock) ------------------------------------------------

def test_quick_saved_fades_in_shows_fades_out_and_is_gone_at_1900_ms():
    notices = layer()
    notices.notify("Quick saved.")
    phases = []
    for _ in range(114):                                 # 1.9 s of 1/60 s frames
        assert notices.views(), "gone too early"
        notices.update(FRAME)
        phases.append(notices.views()[0].phase if notices.views() else "gone")
    assert phases.count("in") == 11 and phases[11] == "shown"     # 200 ms (12th frame ends it)
    assert phases.count("shown") == 90                             # 1,500 ms
    assert phases.count("out") == 12 and phases[-1] == "gone"      # 200 ms; gone at 1,900


@pytest.mark.parametrize("chars, ms", [(12, 1500), (20, 1500), (21, 1550), (60, 3500),
                                       (150, 8000), (200, 8000)])
def test_shown_time(chars, ms):
    assert shown_ms(chars) == ms
    notices = layer()
    notices.notify("x" * chars)
    assert only(notices).shown_s == pytest.approx(ms / 1000)


def test_duration_token_sets_the_base_time():
    assert shown_ms(12, 3000) == 3000
    notices = layer(NoticeStyle(duration_ms=3000))
    notices.notify("Quick saved.")
    run(notices, 0.2)
    run(notices, 2.99)
    assert only(notices).phase == "shown"
    run(notices, 0.01)
    assert only(notices).phase == "out"


def test_same_text_while_shown_restarts_its_time_with_no_second_panel():
    spy = AudioSpy()
    notices = layer(NoticeStyle(sound="sfx/notice.ogg"), play=spy.play_ui)
    notices.notify("Quick saved.")
    run(notices, 0.2 + 1.0)
    assert only(notices).elapsed_s == pytest.approx(1.0)
    notices.notify("Quick saved.")
    assert only(notices).elapsed_s == 0.0
    run(notices, 1.49)
    assert only(notices).phase == "shown"
    assert spy.calls == [("play_ui", "sfx/notice.ogg")]          # not on the restart


def test_same_text_during_fade_out_fades_back_in_without_a_slide():
    notices = layer()
    notices.notify("Quick saved.")
    run(notices, 0.2 + 1.5 + 0.1)
    before = only(notices)
    assert before.phase == "out" and before.opacity == pytest.approx(0.5)
    notices.notify("Quick saved.")
    after = only(notices)
    assert after.phase == "in" and after.opacity == pytest.approx(0.5)
    assert after.box == before.box                                # no jump, no slide
    run(notices, 0.1)
    assert only(notices).phase == "shown"
    run(notices, 1.49)
    assert only(notices).phase == "shown"


def test_same_text_while_waiting_adds_nothing():
    notices = layer()
    for text in ("a", "b", "c", "d"):
        notices.notify(text)
    notices.notify("d")
    notices.notify("a")
    assert [v.text for v in notices.views()] == ["a", "b", "c"]
    assert notices.waiting() == ("d",)


def test_four_then_twelve_more_three_shown_ten_waiting_oldest_dropped():
    notices = layer()
    for n in range(4):
        notices.notify(f"notice {n}")
    assert len(notices.views()) == 3 and notices.waiting() == ("notice 3",)
    for n in range(4, 16):
        notices.notify(f"notice {n}")
    assert [v.text for v in notices.views()] == ["notice 0", "notice 1", "notice 2"]
    assert notices.waiting() == tuple(f"notice {n}" for n in range(6, 16))
    assert notices.dropped == 3


def test_a_waiting_notice_shows_when_one_leaves():
    notices = layer()
    for n in range(4):
        notices.notify(f"notice {n}")
    run(notices, 1.9)
    assert [v.text for v in notices.views()] == ["notice 3"]
    assert notices.waiting() == ()
    assert only(notices).box.y == 24


def test_unfocused_window_pauses_the_shown_time_then_it_resumes():
    notices = layer()
    notices.notify("Quick saved.")
    run(notices, 0.2 + 0.5)
    run(notices, 5.0, focused=False)
    assert only(notices).elapsed_s == pytest.approx(0.5)
    run(notices, 0.99)
    assert only(notices).phase == "shown"
    run(notices, 0.02)
    assert only(notices).phase == "out"


def test_pointer_over_a_notice_pauses_only_that_one():
    notices = layer()
    notices.notify("Quick saved.")
    notices.notify("No quick save yet.")
    run(notices, 0.2)
    first, second = notices.views()
    pointer = first.box.center
    assert notices.contains(pointer) and not notices.contains((100, 100))
    run(notices, 1.0, pointer=pointer)
    first, second = notices.views()
    assert first.elapsed_s == 0.0 and second.elapsed_s == pytest.approx(1.0)
    run(notices, 0.5, pointer=(100, 100))
    first, second = notices.views()
    assert first.elapsed_s == pytest.approx(0.5)
    assert second.phase == "out"


def test_hold_makes_new_notices_wait_and_shown_ones_keep_counting():
    notices = layer()
    notices.notify("first")
    run(notices, 0.5)
    notices.notify("second", hold=True)
    assert [v.text for v in notices.views()] == ["first"]
    assert notices.waiting() == ("second",)
    run(notices, 1.0, hold=True)
    assert notices.waiting() == ("second",)
    assert only(notices).elapsed_s == pytest.approx(1.3)
    notices.update(FRAME, hold=False)
    assert [v.text for v in notices.views()] == ["first", "second"]


def test_text_is_cleaned_and_cut_to_1000_code_points():
    notices = layer()
    notices.notify("Saved\x07!" + "y" * 1200)
    text = only(notices).text
    assert "\x07" not in text and text.startswith("Saved!y")
    assert len(text) == 1000


@pytest.mark.parametrize("raw, clean", [
    ("a\x00b\nc\td\x7f\x85e", "abcde"),                 # Cc
    ("a​b‮c﻿d", "abcd"),                 # Cf
    ("a‍b", "a‍b"),                           # ZWJ kept
    ("a b c", "abc"),                         # Zl, Zp
    ("a\ud800b", "a�b"),                           # a lone surrogate
    ("Quick saved.", "Quick saved."),
], ids=repr)
def test_clean_text(raw, clean):
    assert clean_text(raw) == clean


def test_reduce_motion_cuts_appear_leave_and_restack():
    notices = layer(reduce=True)
    notices.notify("Quick saved.")
    notices.notify("No quick save yet.")
    notices.update(FRAME)
    first, second = notices.views()
    assert first.opacity == second.opacity == 1.0
    assert first.box == Box(1012, 24, 244, 58)                     # no slide
    assert second.box.y == 90
    notices.update(1.5 - 2 * FRAME)
    notices.notify("No quick save yet.")      # restart the second: the first leaves first
    notices.update(FRAME)
    (view,) = notices.views()                  # gone in one frame, and the second is
    assert view.text == "No quick save yet."   # restacked to the top in the same frame
    assert view.box.y == 24 and view.opacity == 1.0


def test_fade_in_slides_24_units_leftward_with_ease_in_out():
    notices = layer()
    notices.notify("Quick saved.")
    notices.update(0.1)
    view = only(notices)
    assert view.opacity == pytest.approx(ease_in_out(0.5)) == pytest.approx(0.5)
    assert view.box.x == pytest.approx(1012 + 24 * 0.5)
    notices.update(0.05)
    assert only(notices).box.x == pytest.approx(1012 + 24 * (1 - ease_in_out(0.75)))


def test_fade_out_is_linear():
    notices = layer()
    notices.notify("Quick saved.")
    run(notices, 1.7)
    notices.update(0.05)
    assert only(notices).opacity == pytest.approx(0.75)


def test_restack_moves_up_over_fade_ms_with_ease_in_out():
    notices = layer()
    notices.notify("first")
    run(notices, 0.5)
    notices.notify("second")
    run(notices, 1.4)                          # "first" is gone; "second" starts moving up
    view = only(notices)
    assert view.text == "second" and view.box.y == 90
    notices.update(0.1)
    assert only(notices).box.y == pytest.approx(90 + (24 - 90) * ease_in_out(0.5))
    notices.update(0.1)
    assert only(notices).box.y == pytest.approx(24)


def test_sound_plays_once_per_new_notice():
    spy = AudioSpy()
    notices = layer(NoticeStyle(sound="sfx/n.ogg"), play=spy.play_ui)
    for text in ("a", "b", "c", "d"):
        notices.notify(text)
    assert spy.calls == [("play_ui", "sfx/n.ogg")] * 3
    run(notices, 1.9)
    assert spy.calls == [("play_ui", "sfx/n.ogg")] * 4             # "d" shows later
    silent = layer(play=spy.play_ui)
    silent.notify("x")
    assert len(spy.calls) == 4


def test_bad_kind_is_refused():
    with pytest.raises(ValueError):
        layer().notify("x", kind="warning")          # type: ignore[arg-type]


def test_clear_drops_everything():
    notices = layer()
    for n in range(5):
        notices.notify(str(n))
    notices.clear()
    assert notices.views() == () and notices.waiting() == ()


def test_ease_in_out_curve():
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert ease_in_out(t) == pytest.approx((1 - math.cos(math.pi * t)) / 2)


# --- Pixels: the drawn notice (unit canvas, bundled font) ------------------------------------

class Board:
    """A 1280×720 canvas with a solid stage, a notice layer in the default theme, and a
    painter."""

    def __init__(self, *, theme=None) -> None:
        self.assets = make_assets(None)
        self.theme = theme or plain_theme()
        style = notice_style(self.theme)
        self.notices = NoticeLayer(style, measure_with(self.assets, style.font))
        self.painter = Painter(self.theme)
        self.canvas = Canvas(self.assets)
        self.framebuffer = pygame.Surface((1280, 720))
        self.viewport = Viewport.compute((1280, 720), (1280, 720))

    def draw(self) -> None:
        self.assets.time.advance(FRAME if self.assets.time.frame else None)
        self.framebuffer.fill(STAGE)
        self.canvas.bind(self.framebuffer, self.viewport, RenderQuality.FINAL)
        self.notices.draw(self.canvas, self.painter)

    def px(self, x, y) -> tuple[int, int, int]:
        return tuple(self.framebuffer.get_at(self.canvas.px(x, y)))[:3]


def test_probe_under_quick_saved_is_the_notice_fill_over_the_stage():
    board = Board()
    board.notices.notify("Quick saved.")
    run(board.notices, 0.2)
    board.draw()
    assert close(board.px(1250, 53), over(PINK_WHITE, 0.94, STAGE))
    assert board.px(1270, 53) == STAGE                      # right of the panel
    assert board.px(1250, 90) == STAGE                      # below it
    box = only(board.notices).box
    text = [board.px(x, y) for x in range(int(box.x) + 20, int(box.right) - 20)
            for y in range(36, 70)]
    assert any(sum(c) < 300 for c in text)                  # plum text drawn


def test_problem_bar_pixels_and_half_faded_fill():
    board = Board()
    board.notices.notify("This save is too large.", kind="problem")
    run(board.notices, 0.2)
    board.draw()
    box = only(board.notices).box
    assert close(board.px(box.x + 15, box.y + box.h / 2), BERRY)
    halfway = Board()
    halfway.notices.notify("Quick saved.")
    halfway.notices.update(0.1)                              # opacity 0.5
    halfway.draw()
    assert close(halfway.px(1250, 53), over(PINK_WHITE, 0.94 * 0.5, STAGE), tol=3)


def test_nothing_is_drawn_without_notices():
    board = Board()
    board.draw()
    assert board.px(1250, 53) == STAGE


# --- GameShell seam (C2) and holds_notices (C7) -----------------------------------------------

def make_shell(*, reduce: bool = False, audio=None) -> GameShell:
    config = Config()
    ports = ShellPorts(stack=ScreenStack(), assets=make_assets(None), dev=True, config=config,
                       new_game=lambda: None, in_game_screens=lambda: [],
                       reset_in_game=lambda: None, request_quit=lambda: None, audio=audio)
    shell = GameShell(ports, theme=plain_theme(config.theme), words=Words(config.words))
    shell.reduce_motion = reduce
    return shell


class Stage(Screen):
    def draw(self, canvas) -> None:
        canvas.fill(STAGE)


def test_shell_notify_update_and_draw_layer():
    shell = make_shell()
    shell.stack.push(Stage())
    shell.notify("Quick saved.")
    shell.notify("Couldn't save: the disk is full.", kind="problem")
    shell.update_layer(0.2, focused=True)
    views = shell.notices.views()
    assert [v.kind for v in views] == ["info", "problem"]
    assert views[0].box.y == 24 and views[0].box.right == 1256
    canvas = Canvas(shell.assets)
    framebuffer = pygame.Surface((1280, 720))
    canvas.bind(framebuffer, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
    shell.stack.draw(canvas)
    shell.draw_layer(canvas)
    assert close(tuple(framebuffer.get_at((1250, 53)))[:3], over(PINK_WHITE, 0.94, STAGE))
    shell.clear_notices()
    assert shell.notices.views() == ()


def test_shell_pauses_under_the_stack_pointer_and_when_unfocused():
    shell = make_shell()
    shell.stack.push(Stage())
    shell.notify("Quick saved.")
    shell.update_layer(0.2, focused=True)
    shell.update_layer(1.0, focused=False)
    assert only(shell.notices).elapsed_s == 0.0
    shell.stack.pointer = (1250, 53)
    shell.update_layer(1.0, focused=True)
    assert only(shell.notices).elapsed_s == 0.0
    shell.stack.pointer = None
    shell.update_layer(1.0, focused=True)
    assert only(shell.notices).elapsed_s == pytest.approx(1.0)


def test_shell_notice_sound_and_reduce_motion_follow_the_shell():
    audio = AudioSpy()
    shell = make_shell(reduce=True, audio=audio)
    shell.notify("x")
    shell.update_layer(FRAME, focused=True)
    assert only(shell.notices).opacity == 1.0
    assert audio.calls == []                                 # notice.sound is none


def test_black_fade_holds_new_notices_until_another_screen_is_top():
    shell = make_shell()
    stage = Stage()
    shell.stack.push(stage)
    fade = BlackFadeScreen(1.0, lambda: None)
    shell.stack.push(fade)
    assert fade.holds_notices and not stage.holds_notices and not Screen.holds_notices
    shell.notify("Quick saved.")
    shell.update_layer(0.5, focused=True)
    assert shell.notices.views() == () and shell.notices.waiting() == ("Quick saved.",)
    shell.stack.remove(fade)
    shell.update_layer(FRAME, focused=True)
    assert [v.text for v in shell.notices.views()] == ["Quick saved."]


def test_title_holds_notices_while_it_fades_in():
    shell = make_shell()
    title = TitleScreen(shell, fade_in=True)
    shell.stack.push(title)
    assert title.holds_notices
    shell.notify("Saved settings.")
    for _ in range(30):                                      # title.fade_in_ms 500
        shell.stack.update(FRAME)
        shell.update_layer(FRAME, focused=True)
    assert not title.holds_notices
    assert [v.text for v in shell.notices.views()] == ["Saved settings."]
    assert not TitleScreen(shell, fade_in=False).holds_notices


def test_story_load_screen_holds_notices():
    from engine.app.loading import StoryLoadScreen

    assert StoryLoadScreen.holds_notices is True


# --- App frame order (C9): update and draw slots, dev overlay on top, error mode ---------------

class LayerSpy:
    """A shell's notice slots, recorded in ``order``."""

    def __init__(self, order: list) -> None:
        self.order = order
        self.focus: list[bool] = []

    def update_layer(self, dt, *, focused) -> None:
        self.order.append("update_layer")
        self.focus.append(focused)

    def draw_layer(self, canvas) -> None:
        self.order.append("draw_layer")

    def clear_notices(self) -> None:
        self.order.append("clear_notices")


class OrderScreen(Screen):
    def __init__(self, order: list) -> None:
        self.order = order

    def update(self, dt, *, is_top) -> None:
        self.order.append("update")

    def draw(self, canvas) -> None:
        self.order.append("draw")


@pytest.mark.display
def test_app_runs_the_notice_layer_after_screens_and_under_the_overlay(monkeypatch):
    from engine.render import overlay
    from tests.fakes.fake_window import FakeWindow
    from tests.fakes.harness import make_app

    window = FakeWindow()
    app, limiter = make_app(window)
    order: list = []
    spy = LayerSpy(order)
    app.shell = spy                                           # type: ignore[assignment]
    app.screens.push(OrderScreen(order))
    app.overlay_on = True
    monkeypatch.setattr(overlay, "draw", lambda canvas, recent, lines=(): order.append("overlay"))
    limiter.at(3, lambda: pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST)))
    limiter.at(5, lambda: pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSGAINED)))
    limiter.quit_at(6)
    app.run()
    per_frame = ["update", "update_layer", "draw", "draw_layer", "overlay"]
    assert order == per_frame * 6
    assert spy.focus == [True, True, False, False, True, True]


@pytest.mark.display
def test_app_error_mode_clears_notices_and_skips_the_layer():
    from tests.fakes.fake_window import FakeWindow
    from tests.fakes.harness import make_app

    window = FakeWindow()
    app, limiter = make_app(window)
    order: list = []
    app.shell = LayerSpy(order)                               # type: ignore[assignment]
    app.screens.push(OrderScreen(order))
    limiter.at(2, lambda: app.show_fatal_error(RuntimeError("boom")))
    limiter.quit_at(4)
    app.run()
    assert order.count("clear_notices") == 1
    after = order[order.index("clear_notices") + 1:]
    assert "update_layer" not in after and "draw_layer" not in after
