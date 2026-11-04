"""F16 step 4 — the Settings page on a real ``GameShell`` with a dict-backed ``SettingsPort``
(no App, no frame loop): AC-F16-20 (entries), 21, 22, 23, 25 (rebuilds), 26 (row states),
27, 28, 29 (confirms), 30, and F10's hooks (``Slider(step=, value_text=)``,
``FocusGroup(clip=)``, ``MenuPage.on_mouse``). The service side and ``install_settings_ui``
are ``tests/app/test_settings_ui.py``.

Geometry at 100 % (text 28): H_b 56, slider row 91, body slot (416, 112, 808×552); the
game column is 1,629 tall (title 1,693), so the most it scrolls is 1,077 and a page key or
a lane press moves 552 − 56 = 496. Fades are off (reduced motion), so one frame acts.
Tables share one rig and run as loops (each pygame test costs ~0.04 s).
"""

import ast
from pathlib import Path

import pygame
import pytest

from engine.core.config_schema import Config, WordsConfig
from engine.core.settings_schema import effective_text_size
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.settings_page import SettingsColumn, SettingsPage, _Item, register_settings
from engine.ui.focus import Box, FocusGroup, FocusScope
from engine.ui.menu_screen import CursorKeeper
from engine.ui.menus import EntryContext
from engine.ui.nav import InputKind, Nav
from engine.ui.screen import ScreenStack
from engine.ui.shell import GameShell, Mode, ShellPorts
from engine.ui.theme import Words, plain_theme
from engine.ui.widgets import Button, Slider, Toggle
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import UiHarness
from tests.render.conftest import make_assets

H = UiHarness
REPO = Path(__file__).resolve().parents[2]
DEFAULTS = {"text_cps": 40, "text_size_pct": 100, "auto_scale_pct": 100,
            "auto_wait_voice": True, "skip_all": False, "master_volume": 100,
            "music_volume": 70, "sound_volume": 70, "voice_volume": 100, "text_blips": True,
            "voice_sustain": False, "audio_unfocused": False, "audio_minimized": False,
            "mono": False, "fullscreen": False, "reduce_motion": False,
            "window_size": (1280, 720), "timing_assist": 0}


class Port:
    """A dict-backed ``SettingsPort`` that records its calls."""

    def __init__(self, **values) -> None:
        self.values = dict(DEFAULTS, **values)
        self.calls: list[tuple] = []
        self.locks: set[str] = set()
        self.state = "enabled"

    def value(self, key):
        return self.values[key]

    def is_default(self, key):
        return self.values[key] == DEFAULTS[key]

    def set(self, key, value):
        self.calls.append(("set", key, value))
        self.values[key] = value

    def reset(self):
        self.calls.append(("reset",))
        self.values = dict(DEFAULTS)

    def locked(self, key):
        return key in self.locks

    def progress(self):
        return self.state

    def delete_progress(self):
        self.calls.append(("delete_progress",))


class Rig:
    """A shell with the Settings entries over ``Port``; ``open`` shows the page in game (or
    from the title). The painter's text scale follows ``text_size_pct`` as the App's."""

    def __init__(self, *, words: dict | None = None, **values) -> None:
        config = Config(words=WordsConfig(**(words or {})))
        ports = ShellPorts(stack=ScreenStack(), assets=make_assets(None), dev=True,
                           config=config, new_game=lambda: None, in_game_screens=lambda: [],
                           reset_in_game=lambda: None, request_quit=lambda: None)
        self.shell = GameShell(ports, theme=plain_theme(config.theme),
                               words=Words(config.words), cursor=CursorKeeper(lambda v: None))
        self.shell.reduce_motion = True
        self.port = Port(**values)
        self.shell.painter.set_text_scale(
            lambda: effective_text_size(28, self.port.values["text_size_pct"]) / 28)
        register_settings(self.shell, self.port)
        self.h = UiHarness(self.shell)

    def open(self, *, title: bool = False, by: InputKind = InputKind.KEYS) -> SettingsPage:
        shell = self.shell
        if title:
            shell.open_title_page("settings", by)
        else:
            shell.mode = Mode.GAME
            shell.open_game_menu(by)
            self.menu.open_page("settings")
            if by is InputKind.KEYS:
                self.frame(H.key(pygame.K_RIGHT))             # into the page: Fullscreen
        self.frame()
        page = self.menu.page
        assert isinstance(page, SettingsPage)
        return page

    @property
    def menu(self):
        menu = self.shell.game_menu()
        assert menu is not None
        return menu

    @property
    def page(self) -> SettingsPage:
        return self.menu.page

    @property
    def focused(self):
        return self.menu.scope.focused

    def row(self, word: str):
        return self.page.widgets[word]

    def scroll(self) -> float:
        return self.page.column.scroll

    def frame(self, *events):
        return self.h.frame(*events)

    def keys(self, *keys: int) -> None:
        for key in keys:
            self.frame(H.key(key))


def ys(page: SettingsPage) -> dict[str, float]:
    """Canvas y of every heading and row at the current scroll."""
    view = page.column.view
    return {item.word: view.y + item.y - page.column.scroll for item in page.column.items}


# --- F10 hooks: Slider(step=, value_text=), FocusGroup(clip=) (AC-F16-23, 28) -------------

def test_slider_step_snaps_presses_and_keeps_f10_defaults():
    value = {"v": 0}
    plain = Slider(lambda: "s", 0, 100, lambda: value["v"], lambda v: value.update(v=v),
                   box=Box(0, 0, 400, 91))
    assert plain.step == 5 and not plain.snap and plain.value_text is None
    assert plain.value_at(32 + 264 * 0.37) == 37                 # F10: the nearest whole value
    stepped = Slider(lambda: "s", 25, 400, lambda: value["v"], lambda v: value.update(v=v),
                     step=25, value_text=lambda v: f"{v}%", box=Box(0, 0, 400, 91))
    x0, x1 = stepped.bar_span()
    for t in [i / 50 for i in range(51)]:
        raw = 25 + t * 375
        got = stepped.value_at(x0 + t * (x1 - x0))
        assert (got - 25) % 25 == 0 and abs(got - raw) <= 25 and 25 <= got <= 400
    odd = Slider(lambda: "s", 0, 7, lambda: 0, lambda v: None, step=5, box=Box(0, 0, 400, 91))
    assert odd.value_at(10_000) == 7                             # lo + k·step clamped to hi
    with pytest.raises(ValueError):
        Slider(lambda: "s", 0, 10, lambda: 0, lambda v: None, step=0)


def test_focus_group_clip_hides_members_outside_it_from_the_pointer():
    inside = Button(lambda: "a", lambda: None, box=Box(416, 80, 400, 80))   # straddles 112
    other = Button(lambda: "b", lambda: None, box=Box(0, 0, 100, 100))
    scope = FocusScope([FocusGroup([other]), FocusGroup([inside], clip=Box(416, 112, 808, 552))])
    assert scope.widget_at((500, 100)) is None and scope.widget_at((500, 120)) is inside
    assert scope.widget_at((50, 50)) is other
    assert FocusGroup([]).clip is None


# --- AC-F16-20 — where Settings opens ------------------------------------------------------

def test_ac20_title_game_and_quick_entries():
    rig = Rig()
    page = rig.open(title=True)
    menu = rig.menu
    assert menu.from_title and [b.label() for b in menu.buttons] == ["Return", "Settings"]
    assert page.title and rig.focused is rig.row("fullscreen")         # C1: the page's default
    rig.frame(H.key(pygame.K_ESCAPE))
    assert rig.shell.game_menu() is None

    rig = Rig()
    rig.shell.mode = Mode.GAME
    rig.shell.open_game_menu(InputKind.KEYS)
    rig.menu.button("settings").activate()
    assert isinstance(rig.page, SettingsPage) and not rig.page.title
    rig.frame(H.key(pygame.K_ESCAPE))
    assert rig.shell.game_menu().page is None                         # Back: the sidebar
    rig.frame(H.key(pygame.K_ESCAPE))

    quick = rig.shell.menus.entry("quick", "settings")
    quick.action(EntryContext(rig.shell, InputKind.MOUSE))
    menu = rig.menu
    assert isinstance(menu.page, SettingsPage) and menu.scope.focused is None
    quick.action(EntryContext(rig.shell, InputKind.MOUSE))           # a menu is open: nothing
    assert len(list(rig.shell.stack)) == 1 and rig.menu is menu
    rig.frame(H.key(pygame.K_ESCAPE))
    assert rig.menu is menu and menu.page is None                     # back to the sidebar
    menu.close()
    quick.action(EntryContext(rig.shell, InputKind.KEYS))
    assert rig.focused is rig.row("fullscreen")


# --- AC-F16-21 — layout and words at 100 % --------------------------------------------------

def test_ac21_layout_at_100_percent(monkeypatch):
    rig = Rig(words={"music_volume": "Musique", "confirm_reset_settings": "Tout remettre ?"})
    page = rig.open()
    at = ys(page)
    assert (at["settings_display"], at["reduce_motion"], at["settings_text"], at["text_speed"],
            at["text_size"], at["auto_wait"]) == (112, 240, 419, 483, 582, 681)   # F50: +99
    box = rig.row("fullscreen").box
    assert (box.x, box.y, box.w, box.h) == (416, 176, 788, 56) and page.column.scroll == 0
    assert page.column.lane_box() == Box(1204, 112, 20, 552)
    reset = rig.row("reset_settings").box
    assert (reset.x, reset.w, reset.h) == (448, 400, 56)
    assert page.column.content == 1728 and "delete_progress" not in page.widgets
    focusable = rig.menu.scope.tab_order()
    assert len([w for w in focusable if w in page.widgets.values()]) == 18   # no heading
    assert rig.row("music_volume").label() == "Musique"
    page.on_mouse("wheel", (800, 400), notches=-10)                   # Musique into view
    with spy_draw_text(monkeypatch) as calls:
        rig.frame()
    assert "Musique" in [c.text for c in calls] and "Sound" in [c.text for c in calls]
    rig.menu.scope.focus(rig.row("reset_settings"), InputKind.KEYS)
    rig.frame(H.key(pygame.K_RETURN))
    assert rig.shell.stack.top.message == "Tout remettre ?"

    title = Rig().open(title=True)
    assert title.column.content == 1792
    assert title.column.items[-1].word == "delete_progress"
    items = [_Item("h", None), _Item("a", Toggle(lambda: "a", lambda: False, lambda v: None))]
    small = SettingsColumn(items, Box(0, 0, 0, 0))
    small.lay_out(Box(416, 112, 808, 552), 56, 91)
    assert small.lane_box() is None and items[1].widget.box.w == 808


# --- AC-F16-22 — everything fits at 150 % --------------------------------------------------

def test_ac22_everything_fits_at_150_percent(monkeypatch):
    rig = Rig(text_size_pct=150, auto_wait_voice=False)     # "Off": the wider state word
    page = rig.open()
    assert rig.shell.painter.text_scale() == 1.5
    heights = {item.word: item.h for item in page.column.items}
    assert heights["fullscreen"] == 75 and heights["text_speed"] == 111
    sizes: dict[str, int] = {}
    rows = [w for w in page.widgets.values()]
    with spy_draw_text(monkeypatch) as calls:
        for _ in rows:
            focused = rig.focused
            assert 112 <= focused.box.y and focused.box.bottom <= 664, focused.label()
            for call in calls:
                assert not call.text.endswith("…"), call.text
                sizes[call.text] = call.font.size
            calls.clear()
            rig.frame(H.key(pygame.K_DOWN))
    assert sizes["Auto-advance waits for voices"] == 40
    assert sizes["Fullscreen"] == 42


# --- AC-F16-23 — sliders: steps, Instant, value texts -------------------------------------

def test_ac23_slider_values_and_texts():
    rig = Rig()
    page = rig.open()
    port = rig.port
    speed = rig.row("text_speed")
    text = speed.value_text
    for cps, value, shown in ((40, 40, "40"), (0, 210, "Instant"), (5, 10, "10"),
                              (500, 200, "200")):
        port.values["text_cps"] = cps
        assert (speed.value, text(speed.value)) == (value, shown)
    assert port.calls == []                                           # shown, never set
    rig.menu.scope.focus(speed, InputKind.KEYS)
    for start, key, shown, stored in ((5, pygame.K_RIGHT, "20", 20),
                                      (200, pygame.K_RIGHT, "Instant", 0),
                                      (0, pygame.K_LEFT, "200", 200),
                                      (40, pygame.K_END, "Instant", 0),
                                      (40, pygame.K_HOME, "10", 10)):
        port.values["text_cps"] = start
        port.calls.clear()
        rig.frame(H.key(key))
        assert text(speed.value) == shown and port.calls == [("set", "text_cps", stored)]
    for word, key, start, shown in (("text_size", "text_size_pct", 100, "110%"),
                                    ("auto_wait", "auto_scale_pct", 100, "125%"),
                                    ("music_volume", "music_volume", 70, "75"),
                                    ("music_volume", "music_volume", 42, "47")):
        port.values[key] = start
        slider = rig.row(word)
        assert slider.on_nav(Nav.RIGHT)
        assert slider.value_text(slider.value) == shown
        port.values["text_size_pct"] = 100
    port.calls.clear()
    master = rig.row("master_volume")
    page.column.scroll_to(600)
    x0, x1 = master.bar_span()
    for t in (0.0, 0.13, 0.5, 0.88, 1.0):
        master.on_mouse("down", (x0 + t * (x1 - x0), master.box.y + 40))
        got = port.values["master_volume"]
        assert got % 5 == 0 and abs(got - 100 * t) <= 5


# --- AC-F16-25 — text size rebuilds once ---------------------------------------------------

def test_ac25_text_size_rebuilds_the_menu_once_and_keeps_focus():
    for title in (False, True):
        rig = Rig()
        rig.open(title=title)
        menu = rig.menu
        slider = rig.row("text_size")
        menu.scope.focus(slider, InputKind.KEYS)
        rig.frame()
        counts = {"rebuild": 0, "backdrop": 0}
        real_rebuild, real_refresh = menu.rebuild, menu.refresh_backdrop
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(menu, "rebuild", lambda: (counts.__setitem__(
                "rebuild", counts["rebuild"] + 1), real_rebuild()))
            mp.setattr(menu, "refresh_backdrop", lambda: (counts.__setitem__(
                "backdrop", counts["backdrop"] + 1), real_refresh()))
            rig.frame(H.key(pygame.K_RIGHT))
            rig.frame()
            assert counts == {"rebuild": 1, "backdrop": 0 if title else 1}
            assert rig.focused is slider and rig.page.column.items[1].h == 59   # H_b at 31
            if title:
                continue
            rig.port.values["text_size_pct"] = 100
            rig.frame()
            counts["rebuild"] = 0
            x0, x1 = slider.bar_span()
            y = slider.box.y + 40
            rig.frame(H.down((x0, y)))
            for i in range(1, 13):
                rig.frame(H.motion((x0 + (x1 - x0) * i / 12, y)))
            rig.frame(H.up((x1, y)))
            assert rig.port.values["text_size_pct"] == 150 and counts["rebuild"] <= 6


# --- AC-F16-26 — row states ------------------------------------------------------------------

def test_ac26_locked_reduce_progress_and_fullscreen_states():
    rig = Rig()
    rig.port.locks.add("reduce_motion")
    rig.open()
    reduce = rig.row("reduce_motion")
    assert reduce.on_state() is True and not reduce.enabled()
    assert reduce.look(focused=False).state == "disabled"
    rig.frame(H.key(pygame.K_DOWN))
    assert rig.focused is rig.row("timing_assist")                    # skipped by Down
    rig.page.column.scroll_to(0)
    rig.h.click(reduce.box.center)
    assert rig.port.calls == []
    rig.port.values["fullscreen"] = True                              # F11 outside the page
    assert rig.row("fullscreen").on_state() is True
    page_before, scroll_before = rig.page, rig.page.column.scroll
    rig.h.resize((1600, 900))
    rig.frame()
    assert rig.page is page_before and rig.page.column.scroll == scroll_before

    rig = Rig()
    rig.open(title=True)
    delete = rig.row("delete_progress")
    assert delete.enabled()
    rig.port.state = "disabled"
    assert not delete.enabled()


# --- AC-F16-27 — keys, gamepad, scrolling ----------------------------------------------------

def test_ac27_keys_scroll_the_focused_row_into_view():
    rig = Rig()
    rig.open()
    assert rig.focused is rig.row("fullscreen") and rig.scroll() == 0
    steps = [("reduce_motion", 0), ("timing_assist", 0), ("text_speed", 0), ("text_size", 9),
             ("auto_wait", 108), ("auto_voice", 172), ("skip_unread", 236),
             ("master_volume", 415)]                                   # F50: Timing assist
    for word, scroll in steps:
        rig.frame(H.key(pygame.K_DOWN))
        assert (rig.focused, rig.scroll()) == (rig.row(word), scroll), word
    # Up to Text speed shows its heading too (design §6.3: 307, 07 note in the report).
    rig.keys(*[pygame.K_UP] * 5)
    assert (rig.focused, rig.scroll()) == (rig.row("text_speed"), 307)
    rig.keys(pygame.K_UP, pygame.K_UP, pygame.K_UP)
    assert (rig.focused, rig.scroll()) == (rig.row("fullscreen"), 0)
    rig.frame(H.key(pygame.K_PAGEDOWN))
    assert (rig.focused, rig.scroll()) == (rig.row("auto_wait"), 496)
    rig.frame(H.key(pygame.K_PAGEUP))
    assert (rig.focused, rig.scroll()) == (rig.row("fullscreen"), 0)
    rig.menu.scope.focus(rig.row("auto_wait"), InputKind.KEYS)
    rig.frame()
    before = rig.scroll()
    rig.keys(pygame.K_END)
    assert rig.port.values["auto_scale_pct"] == 400 and rig.scroll() == before
    rig.keys(pygame.K_HOME)
    assert rig.port.values["auto_scale_pct"] == 25 and rig.scroll() == before
    rig.menu.scope.focus(rig.row("reset_settings"), InputKind.KEYS)
    rig.frame()
    assert rig.scroll() == 1176
    rig.frame(H.key(pygame.K_DOWN))
    assert rig.focused is rig.row("reset_settings")                   # the last row stays

    pad = Rig()
    pad.open()
    pad.frame(H.pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN))
    for _ in range(3):
        pad.frame(H.pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN))
    assert (pad.focused, pad.scroll()) == (pad.row("text_size"), 9)
    pad.page.column.scroll_to(0)
    auto = pad.row("text_size")                                       # partly below the slot
    pad.frame(H.motion((800, 600)))
    assert pad.focused is auto and pad.scroll() == 0                  # hover never scrolls


# --- AC-F16-28 — wheel, lane, clipping ------------------------------------------------------

def test_ac28_wheel_lane_and_clipping():
    rig = Rig()
    page = rig.open()
    column = page.column
    speed = rig.row("text_speed")
    rig.frame(H.wheel((800, speed.box.y + 60), -3))
    assert rig.scroll() == 180 and rig.port.calls == []
    column.scroll_to(0)
    rig.frame(H.wheel((800, 300), 1))
    assert rig.scroll() == 0
    column.scroll_to(5000)
    assert rig.scroll() == 1176
    rig.frame(H.wheel((800, 300), -1))
    assert rig.scroll() == 1176
    column.scroll_to(0)
    thumb = column.thumb_box()
    assert thumb.h == pytest.approx(max(32, 552 * 552 / 1728))
    rig.frame(H.down((1214, thumb.bottom + 50)), H.up((1214, thumb.bottom + 50)))
    assert rig.scroll() == 496
    column.scroll_to(0)
    rig.frame(H.down((1214, 150)))
    rig.frame(H.motion((1214, 200)))
    rig.frame(H.up((1214, 200)))
    assert rig.scroll() == pytest.approx(50 * 1728 / 552, abs=1)
    column.scroll_to(100)                       # Fullscreen at y 76–132, Auto wait 581–672
    rig.frame()
    for point in ((800, 100), (800, 670)):
        assert rig.menu.scope.widget_at(point) is None
        rig.h.click(point)
    assert rig.port.calls == []
    assert rig.row("auto_wait").box.contains((800, 670))

    big = Rig(text_size_pct=150)
    big.open()
    big.frame(H.wheel((800, 300), -3))
    assert big.scroll() == 270


# --- AC-F16-29 — Reset and Delete progress confirms -----------------------------------------

def test_ac29_confirms_return_focus_to_their_buttons():
    rig = Rig(music_volume=40)
    rig.open()
    reset = rig.row("reset_settings")
    for answer in (pygame.K_RETURN, pygame.K_ESCAPE):                 # No, then Back
        rig.menu.scope.focus(reset, InputKind.KEYS)
        rig.frame(H.key(pygame.K_RETURN))
        dialog = rig.shell.stack.top
        assert isinstance(dialog, ConfirmScreen)
        assert dialog.message == "Reset every setting to its default?"
        assert dialog.scope.focused is dialog.no_button
        rig.frame(H.key(answer))
        assert rig.focused is reset and rig.port.calls == []
    rig.frame(H.key(pygame.K_RETURN))
    rig.frame(H.key(pygame.K_LEFT))
    rig.frame(H.key(pygame.K_RETURN))                                 # Yes
    assert rig.port.calls == [("reset",)] and rig.focused is reset
    assert rig.row("music_volume").value == 70

    title = Rig()
    title.open(title=True)
    delete = title.row("delete_progress")
    title.menu.scope.focus(delete, InputKind.KEYS)
    title.frame(H.key(pygame.K_RETURN))
    assert title.shell.stack.top.message.startswith("Delete everything this game remembers")
    title.frame(H.key(pygame.K_LEFT))
    title.frame(H.key(pygame.K_RETURN))
    assert title.port.calls == [("delete_progress",)] and title.focused is delete


# --- AC-F16-30 — no motion of its own ------------------------------------------------------

def test_ac30_frames_settle_at_once(monkeypatch):
    rig = Rig()
    rig.open()
    with spy_draw_text(monkeypatch) as calls:
        for change in (lambda: rig.frame(H.key(pygame.K_RIGHT)),          # a value
                       lambda: rig.frame(H.wheel((800, 300), -2)),         # the column
                       lambda: rig.port.values.update(reduce_motion=True)):
            change()
            calls.clear()
            rig.frame()
            first = [(c.text, c.pos, c.font.size) for c in calls]
            calls.clear()
            for _ in range(3):
                rig.frame()
            again = [(c.text, c.pos, c.font.size) for c in calls]
            assert again == first * 3


# --- AC-F16-33 (page half) — the page imports no engine.persist or engine.app ---------------

def test_ac33_settings_page_imports_neither_persist_nor_app():
    source = (REPO / "engine" / "ui" / "builtin" / "settings_page.py").read_text("utf-8")
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    assert names and not [n for n in names if n.startswith(("engine.persist", "engine.app"))]
    assert not {"pickle", "marshal", "importlib", "threading", "queue"} & set(names)
