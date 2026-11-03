"""F35 step 1 — the Music Room page (``ui/builtin/music_room_page.py``): AC-F35-06 (layout at
100 % and 150 % text), AC-F35-07 (controls on F08's Service S: FakeMixer, fake clock) and
AC-F35-10 (keys, mouse, wheel, shoulders).

Port R is a fake ``MusicRoomPort`` over five tracks (two closed); its ``handle()`` takes the
music of a Service S (or None: no audio). Logic rows use F05's M20 metrics
(``FixedFontAssets``) and a bare ``FocusScope``; drawing rows use a ``TestShell`` (real
assets, default theme) on a 1280×720 canvas."""

from dataclasses import dataclass
from types import SimpleNamespace

import pygame
import pytest

from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.ui.builtin.music_room_page import (MusicRoomPage, music_room_layout, time_text)
from engine.ui.focus import Box, FocusScope
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import Painter
from engine.ui.theme import Words, plain_theme
from tests.audio.conftest import make_service
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fixed_font import FixedFontAssets
from tests.fakes.ui_shell import TestShell

SLOT = Box(416, 112, 808, 552)
FESTIVAL, OMEN, SHRINE = "bgm/festival.ogg", "bgm/omen.ogg", "bgm/shrine_steps.ogg"  # 12, 3, 4 s
M20 = SimpleNamespace(theme=plain_theme(), words=Words(), assets=FixedFontAssets())


@dataclass(frozen=True)
class Track:
    name: str
    title: str
    file: str


TRACKS = (Track("main_theme", "Main Theme", SHRINE),
          Track("festival", "Festival Night", FESTIVAL),
          Track("secret", "Secret", "bgm/missing.ogg"),
          Track("omen", "Omen", OMEN),
          Track("rain", "Rain", "sfx/rain.ogg"))
OPEN = {"main_theme", "festival", "omen"}


class PortR:
    def __init__(self, s=None, open_names=OPEN, tracks=TRACKS) -> None:
        self.s = s
        self.open = set(open_names)
        self._tracks = tuple(tracks)
        self.taken = None
        self.left = 0

    def tracks(self):
        return self._tracks

    def is_open(self, name):
        return name in self.open

    def handle(self):
        if self.s is None:
            return None
        if self.taken is None:
            self.taken = self.s.service.take_music("music_room")
        return self.taken

    def leave(self):
        self.left += 1


class Host:
    """The page in a bare ``FocusScope`` (as the Extras screen hosts it)."""

    def __init__(self, port: PortR, *, ui=M20, scale: float = 1.0) -> None:
        self.scope = FocusScope()
        self.page = MusicRoomPage(port, ui=ui)
        self.page.scope = lambda: self.scope
        self.scope.set_groups(self.page.lay_out(SLOT, scale))

    def click(self, w, pos) -> None:
        self.scope.focus(w, InputKind.MOUSE)
        w.on_mouse("down", pos)
        w.on_mouse("up", pos)
        if w.accepts_click(pos):
            w.activate()


def frames(s, page: MusicRoomPage, seconds: float, step: float = 0.01) -> None:
    """``seconds`` of App frames: the service's events and update, then the page's."""
    end = s.clock.now + seconds
    while s.clock.now < end - 1e-9:
        dt = min(step, end - s.clock.now)
        s.advance(dt)
        page.update(dt)


def starts(s) -> list[tuple]:
    """``(name, loops, start)`` of every ``music_start``."""
    return [args[:3] for _t, name, args in s.mixer.calls if name == "music_start"]


def draw(page: MusicRoomPage, shell: TestShell, scope: FocusScope) -> Canvas:
    canvas = Canvas(shell.assets)
    canvas.bind(pygame.Surface((1280, 720)), Viewport.compute((1280, 720), (1280, 720)),
                RenderQuality.FINAL)
    p = shell.painter
    p.bind(canvas)
    page.draw(canvas, p)
    for w in (page.list, *page.buttons):
        w.draw(p, w.look(focused=scope.focused is w))
    return canvas


# --- AC-F35-06 ------------------------------------------------------------------------------

def test_ac06_layout_at_100_and_150(monkeypatch):
    at100 = music_room_layout(SLOT, 1.0)
    assert at100.list == Box(416, 112, 808, 360) and at100.row_height == 48
    assert (at100.now_playing.y, at100.now_size) == (504, 24)
    assert at100.bar == Box(416, 548, 640, 8)
    assert (at100.time_right, at100.time_size) == (1224, 20)
    assert at100.buttons == tuple(Box(x, 584, 188, 56) for x in (416, 620, 824, 1028))
    at150 = music_room_layout(SLOT, 1.5)
    assert at150.row_height == 67 and (at150.now_size, at150.time_size) == (36, 30)
    assert at150.buttons == tuple(Box(x, 565, 188, 75) for x in (416, 620, 824, 1028))
    assert at150.bar.y == 529 and at150.now_playing.y == 469
    assert at150.list == Box(416, 112, 808, 325)
    for layout in (at100, at150):
        assert layout.list.bottom < layout.now_playing.y < layout.bar.y < layout.buttons[0].y
        assert layout.buttons[-1].bottom <= SLOT.bottom and layout.buttons[-1].right <= 1224

    # Rows: numbers for all, ??? for closed ones (never focused), long titles cut with "…".
    long = Track("long", "A Very Long Festival Night Under Paper Lanterns By The River", OMEN)
    host = Host(PortR(tracks=(*TRACKS, long), open_names=OPEN | {"long"}))
    page = host.page
    assert page.buttons[1].box == at100.buttons[1] and page.list.box == at100.list
    assert [page.row_texts(i) for i in range(5)] == [
        ("1", "Main Theme"), ("2", "Festival Night"), ("3", "???"), ("4", "Omen"),
        ("5", "???")]
    cut = page.row_texts(5)[1]
    assert cut.endswith("…") and len(cut) == (808 - 72 - 16) // 20      # M20: 20 per grapheme
    assert [r.enabled for r in page.rows] == [True, True, False, True, False, True]
    host.scope.focus(page.list, InputKind.KEYS)
    page.list.focus_index(1)
    assert host.scope.press(Nav.DOWN) and page.list.focus_row == 3      # skips "???"
    page.list.on_mouse("hover", page.list.row_box(2).center)
    assert page.list.focus_row == 3
    big = Host(PortR(), scale=1.5).page
    assert big.list.row_height == 67 and big.buttons[0].box == at150.buttons[0]

    # Time formats.
    assert time_text(5.2, 221.9) == "0:05 / 3:41" and time_text(72.4, None) == "1:12"
    assert time_text(0.0, None) == "0:00" and time_text(3725.0, 3725.9) == "62:05 / 62:05"

    # Drawn: the playing row's 6-wide marker and bold title, ??? in the disabled color, the
    # now-playing line, the bar's two shapes and the time right-aligned at x 1224.
    shell = TestShell()
    cfg = shell.theme.cfg
    host = Host(PortR(), ui=shell)
    page = host.page
    page.player.pick(1)
    page.player.shown, page.player.shown_length = 5.2, 221.9
    rects, shapes = [], []
    real_rect, real_shape = Painter.rect, Painter.shape
    monkeypatch.setattr(Painter, "rect", lambda self, box, color: (
        rects.append((box, tuple(color))), real_rect(self, box, color))[1])
    monkeypatch.setattr(Painter, "shape", lambda self, box, spec, **kw: (
        shapes.append((box, spec)), real_shape(self, box, spec, **kw))[1])
    with spy_draw_text(monkeypatch) as calls:
        draw(page, shell, host.scope)
    row = page.list.row_box(1)
    assert (Box(row.x, row.y, 6, row.h - 1), tuple(cfg.button.marker.fill_color)) in rects
    texts = {c.text: c for c in calls}
    assert texts["Festival Night"].font == shell.theme.font(28, bold=True)
    assert texts["Main Theme"].font == shell.theme.font(28)
    assert texts["???"].color == tuple(cfg.button.disabled.text_color)
    assert texts["Festival Night"].pos == (row.x + 72, row.y + row.h / 2)
    assert texts["2"].pos == (row.x + 16, row.y + row.h / 2)
    assert texts["0:05 / 3:41"].pos == (1224, 552) and \
        texts["0:05 / 3:41"].options["anchor"] == "midright"
    assert [s for s in shapes if s[0].y == 548] == [
        (Box(416, 548, 640, 8), shapes[0][1]),
        (Box(416, 548, round(640 * 5.2 / 221.9), 8), shapes[1][1])]
    assert shapes[0][1].fill_color == tuple(cfg.slider.track_color)
    assert shapes[1][1].fill_color == tuple(cfg.slider.fill_color)
    page.player.shown_length = None
    page.player.shown = 72.4
    with spy_draw_text(monkeypatch) as calls:
        draw(page, shell, host.scope)
    assert "1:12" in [c.text for c in calls]
    nobody = Host(PortR(), ui=shell).page
    with spy_draw_text(monkeypatch) as calls:
        draw(nobody, shell, FocusScope())
    shown = [c.text for c in calls]
    assert "Pick a track to play." in shown and not any(":" in t and t[0].isdigit()
                                                       for t in shown)


# --- AC-F35-07 ------------------------------------------------------------------------------

def test_ac07_controls_on_the_music_handle(tmp_path):
    s = make_service(tmp_path)
    port = PortR(s)
    host = Host(port)
    page, player = host.page, host.page.player
    handle = port.handle()

    # A pick plays from 0 (Play all: once); picking it again starts it again.
    assert player.pick(1)
    frames(s, page, 2.0)
    assert starts(s)[-1] == (FESTIVAL, 0, 0.0) and player.shown == pytest.approx(2.0, abs=0.02)
    assert page.time().endswith(" / 0:12") and page.bar_fill() == pytest.approx(2 / 12, abs=0.01)
    assert not player.pick(2) and player.current == 1                   # closed: refused
    player.pick(1)
    frames(s, page, 0.5)
    assert starts(s)[-1] == (FESTIVAL, 0, 0.0) and len(starts(s)) == 2
    frames(s, page, 1.0)

    # Pause keeps the position and fades out; resume plays on from it (±0.1 s).
    at = handle.position()
    player.toggle()
    assert player.paused and player.shown == pytest.approx(at, abs=1e-6)
    frames(s, page, 1.0)
    assert s.mixer.music_name() is None and page.time().startswith("0:01")
    player.toggle()
    assert starts(s)[-1][0] == FESTIVAL and starts(s)[-1][2] == pytest.approx(at, abs=0.1)
    frames(s, page, 0.5)
    assert handle.position() == pytest.approx(at + 0.5, abs=0.1)

    # Next / Previous skip closed tracks and wrap.
    order = []
    for step in (player.next, player.next, player.previous, player.previous):
        step()
        order.append(player.current)
    assert order == [3, 0, 3, 1]

    # Play all: an ended track gives the next open one (omen → main_theme, wrapping).
    player.pick(3)
    frames(s, page, 3.6)
    assert player.current == 0 and s.mixer.music_name() == SHRINE
    assert starts(s)[-1] == (SHRINE, 0, 0.0)

    # Repeat track loops (natively); back to Play all, its next pass end moves on.
    player.toggle_mode()
    player.pick(3)
    frames(s, page, 7.0)
    assert player.current == 3 and starts(s)[-1] == (OMEN, -1, 0.0)
    assert s.mixer.music_name() == OMEN and player.shown < 3.0
    player.toggle_mode()
    frames(s, page, 3.1)
    assert player.current == 0

    # One open track, Play all: it plays again from the start.
    port.open = {"omen"}
    count = starts(s).count((OMEN, 0, 0.0))
    player.pick(3)
    frames(s, page, 3.6)
    assert player.current == 3 and starts(s).count((OMEN, 0, 0.0)) == count + 2

    # A missing file: silence, 0:00, one more try, then quiet (no spinning); Next works.
    port.open = {"secret"}
    player.pick(2)
    frames(s, page, 3.0)
    assert player.current == 2 and player.quiet and page.bar_fill() == 0.0
    assert page.time() == "0:00" and page.play_button.label() == "Play"
    port.open = {"secret", "omen"}
    player.next()
    assert player.current == 3 and not player.quiet

    # Leaving fades the room's track over [audio] music_fadeout; a released handle is fine.
    fades = [args for _t, name, args in s.mixer.calls if name == "music_fadeout"]
    page.closed()
    after = [args for _t, name, args in s.mixer.calls if name == "music_fadeout"]
    assert after[len(fades):] == [(round(s.service.cfg.music_fadeout * 1000),)]
    assert port.left == 1 and player.current is None
    handle.release()
    player.pick(3)
    page.update(0.5)
    page.closed()
    assert port.left == 2


# --- AC-F35-10 ------------------------------------------------------------------------------

def test_ac10_keys_mouse_wheel_and_shoulders():
    port = PortR()                                         # no audio: the player still runs
    host = Host(port)
    page, scope, lst = host.page, host.scope, host.page.list
    assert page.nav_extras == frozenset({"shoulders"})
    assert page.default_widget() is lst

    # Keys: Up/Down in the list, Down from the last open row to Play/Pause, Left/Right
    # among the buttons, Up back to the list; Enter plays the focused row.
    scope.focus(lst, InputKind.KEYS)
    lst.focus_index(0)
    assert scope.press(Nav.DOWN) and lst.focus_row == 1
    assert scope.press(Nav.ACTIVATE) and page.player.current == 1
    assert scope.press(Nav.DOWN) and lst.focus_row == 3
    assert scope.press(Nav.DOWN) and scope.focused is page.play_button
    assert scope.press(Nav.RIGHT) and scope.focused is page.next_button
    assert scope.press(Nav.RIGHT) and scope.focused is page.mode_button
    assert scope.press(Nav.ACTIVATE) and page.player.repeat
    assert page.mode_button.label() == "Repeat track"
    assert scope.press(Nav.LEFT) and scope.press(Nav.LEFT) and scope.focused is page.play_button
    assert page.play_button.label() == "Pause"
    assert scope.press(Nav.ACTIVATE) and page.player.paused
    assert page.play_button.label() == "Play"
    assert scope.press(Nav.UP) and scope.focused is lst

    # Page Up / Page Down (and the bumpers, the "shoulders" extra) are Previous / Next:
    # the list leaves them to the page.
    page.player.pick(1)
    assert not scope.press(Nav.PAGE_DOWN)
    assert page.on_nav(Nav.PAGE_DOWN) and page.player.current == 3
    assert page.on_nav(Nav.PAGE_UP) and page.player.current == 1
    assert not page.on_nav(Nav.DOWN)

    # Mouse: a click on an open row plays it; on a ??? row nothing; buttons click.
    host.click(lst, lst.row_box(0).center)
    assert page.player.current == 0
    host.click(lst, lst.row_box(2).center)
    assert page.player.current == 0
    host.click(page.next_button, page.next_button.box.center)
    assert page.player.current == 1
    host.click(page.previous_button, page.previous_button.box.center)
    assert page.player.current == 0

    # The wheel scrolls a long list.
    many = tuple(Track(f"t{i}", f"Track {i}", f"bgm/t{i}.ogg") for i in range(12))
    long = Host(PortR(tracks=many, open_names={t.name for t in many})).page.list
    assert long.overflows()
    assert long.on_mouse("wheel", long.box.center, notches=-1) and long.scroll > 0

    # Every track closed: no row and no button can be focused; Play does nothing.
    closed = Host(PortR(open_names=())).page
    assert not closed.list.enabled() and not any(b.enabled() for b in closed.buttons)
    assert closed.default_widget() is None
    closed.player.toggle()
    assert closed.player.current is None
