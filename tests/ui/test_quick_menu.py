"""F10 step 8 — the quick menu (``QuickMenu``, an overlay of F05's ``TextboxScreen``) and the F07
seams C6–C8, on a real ``GameShell`` built by ``install_ui`` over test_title's small fake App
(no frame loop): AC-F10-49 to 54 in unit form, the quick rows of AC-F10-22, 25, 27, 29, 42, and
AC-F10-38's choice reset (I-8).

F07 isn't built: fake choices (``tests/fakes/fake_choices.py``, ``06`` §0.4) sit on
``app.choices`` before ``install_ui``, as F07's ``install_choices`` will (I-3). Item boxes come
from ``quick_menu_layout`` (the overlay's own layout). The rig has no stage, so the strip under
the box is black: the pill's fill probe is ``#FFF4F8`` at 0.90 over black. One frame is
``UiHarness.frame``: events, ``update(1/60)``, draw on a 1280×720 canvas.
"""

import logging

import pygame

from engine.app.menus import install_ui
from engine.app.text_check import install_textbox
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime.commands import BASE_STYLE, Advance, Say, Span, TaggedText
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.quick_menu import QuickMenu
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.menus import MenuEntry
from engine.ui.nav import InputKind
from engine.ui.shell import Mode
from tests.fakes.audio_spy import AudioSpy
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fake_choices import BUTTONS, FOCUSED, FakeChoiceController, FakeChoiceScreen
from tests.fakes.ui_shell import UiHarness
from tests.render.conftest import make_assets
from tests.ui.test_game_menu import FADE, LINE, Game
from tests.ui.test_title import FakeApp, Rig, close, make_game, over

H = UiHarness
PLUM = (0x3D, 0x2B, 0x36)
BERRY = (0xA0, 0x28, 0x60)
BLUSH = (0xFF, 0xD6, 0xE8)
MAUVE = (0x6E, 0x5E, 0x68)
PINK_WHITE = (0xFF, 0xF4, 0xF8)
TYPING = Say("s5", None, None, None, (), "Hello there, this line types slowly.",
             body=TaggedText((Span("Hello there, this line types slowly.", BASE_STYLE),)))


def quick(g) -> QuickMenu:
    menu = g.shell.quick_menu
    assert isinstance(menu, QuickMenu)
    return menu


def items(g) -> dict:
    """Entry id → its item (hit box, label box) as laid out now."""
    found = quick(g).shown()
    assert found is not None
    return {e.id: item for e, item in zip(found.entries, found.layout.items, strict=True)}


def pill(g):
    found = quick(g).shown()
    assert found is not None
    return found.layout.pill


def centre(item) -> tuple[float, float]:
    return item.box.center


def click(g, pos) -> None:
    g.frame(H.down(pos), H.up(pos))


def quick_labels(calls) -> list[str]:
    return [c.text for c in calls if c.text in ("Hide", "Menu", "Skip", "Auto")]


class ChoiceGame(Game):
    """A ``Game`` whose fake App has F07's controller (``app.choices``) before ``install_ui``,
    as ``install_story`` will order it (I-3)."""

    def __init__(self, tmp_path, config: str = "", **kwargs) -> None:
        real = install_textbox

        def with_choices(app):
            screen = real(app)
            app.choices = FakeChoiceController(app)
            return screen

        import tests.ui.test_title as title_module

        title_module.install_textbox = with_choices
        try:
            super().__init__(tmp_path, config, **kwargs)
        finally:
            title_module.install_textbox = real
        self.choices: FakeChoiceController = self.app.choices

    def show_choices(self) -> FakeChoiceScreen:
        screen = self.choices.show()
        self.frames(2)
        return screen


def typing_game(tmp_path, config: str = "") -> Game:
    g = Game(tmp_path, config)
    g.textbox.show(TYPING)
    g.frames(3)
    assert 0 < g.textbox.shown_count() < len(TYPING.text)
    return g


# Tables are loops in one test, each row on a fresh game, not ``parametrize``: every
# ``tests/ui`` test pays for ``pygame.init()``/``quit()`` (test-review-F10.md).

# --- install; AC-F10-49 — when the quick menu shows ---------------------------------------------

def test_install_and_ac49_shown_at_p_full_and_p_type(tmp_path, monkeypatch):
    with spy_draw_text(monkeypatch) as calls:
        g = Game(tmp_path)
        # install: Hide and Menu registered; the overlay comes after the menu keys.
        assert [e.id for e in g.shell.menus.shown("quick")] == ["hide", "menu"]
        assert [type(o).__name__ for o in g.textbox.overlays] == ["GameMenuKeys", "QuickMenu"]
        assert g.textbox.overlays[1] is g.shell.quick_menu
        calls.clear()
        g.frame()
        assert quick_labels(calls) == ["Hide", "Menu"]
        g.textbox.show(TYPING)
        g.frames(2)
        calls.clear()
        g.frame()
        assert quick_labels(calls) == ["Hide", "Menu"]


def test_ac49_not_before_the_first_line_on_the_title_or_after_main_menu_yes(tmp_path,
                                                                             monkeypatch):
    rig = Rig(tmp_path / "a")
    with spy_draw_text(monkeypatch) as calls:
        rig.frames(2)
    assert quick_labels(calls) == []                     # the title
    rig.frames(29)
    rig.frame(H.key(pygame.K_DOWN))
    rig.frame(H.key(pygame.K_RETURN))                    # New Game
    rig.frames(FADE + 2)
    assert [type(s) for s in rig.stack] == [TextboxScreen] and rig.shell.mode is Mode.GAME
    textbox = rig.app.textbox
    assert textbox.line is None
    with spy_draw_text(monkeypatch) as calls:
        rig.frame()
    assert quick_labels(calls) == []
    assert rig.app.screens.handle_event(H.down((640, 704))) is False     # F05's: nothing here
    g = Game(tmp_path / "b")
    g.shell.return_to_title()                            # Main Menu → Yes
    g.frames(FADE + 3)
    assert isinstance(g.top, TitleScreen)
    with spy_draw_text(monkeypatch) as calls:
        g.frames(2)
    assert quick_labels(calls) == []


def test_ac49_not_while_hidden_cleared_off_or_all_hidden_and_a_click_there_is_f05s(
        tmp_path, monkeypatch):
    for how in ("hidden", "cleared"):
        g = Game(tmp_path / how)
        hide = centre(items(g)["hide"])
        if how == "hidden":
            g.frame(H.key(pygame.K_h))                   # P-hidden
            assert g.textbox.hidden
        else:
            g.textbox.clear()
        with spy_draw_text(monkeypatch) as calls:
            g.frame()
        assert quick_labels(calls) == [], how
        click(g, hide)
        if how == "hidden":
            assert not g.textbox.hidden                  # F05: the click only shows the box
        assert g.app.story.posted == [] and g.shell.game_menu() is None, how
    for how, config in (("disabled", "[quick_menu]\nenabled = false"), ("every-hidden", "")):
        g = Game(tmp_path / how, config)
        if not config:
            g.shell.overrides.set_hidden("quick", "hide", True)
            g.shell.overrides.set_hidden("quick", "menu", True)
        with spy_draw_text(monkeypatch) as calls:
            g.frame()
        assert quick_labels(calls) == [], how
        assert quick(g).pill_top() is None, how
        click(g, (640, 704))                             # where the pill would be: advances
        assert g.app.story.posted == [Advance(LINE.sid)], how


# --- AC-F10-50 — look ---------------------------------------------------------------------------

def _underline_rows(g, item) -> list[int]:
    """Rows inside the pill where the label's full width is the accent color (the underline;
    glyph ink never spans a whole label)."""
    lb = item.label_box
    xs = [lb.x + 1 + (lb.w - 2) * i / 6 for i in range(7)]
    box = pill(g)
    return [y for y in range(int(box.y), int(box.bottom))
            if all(g.px((x, y)) == BERRY for x in xs)]


def test_ac50_pill_place_fill_labels_hover_underline_and_pressed_chip(tmp_path, monkeypatch):
    g = Game(tmp_path)
    box = pill(g)
    assert (box.y, box.bottom) == (690, 718) and box.center[0] == 640
    with spy_draw_text(monkeypatch) as calls:
        g.frame()
    assert close(g.px((box.x + 3, 704)), over(PINK_WHITE, 0.90, (0, 0, 0)))
    drawn = [c for c in calls if c.text in ("Hide", "Menu")]
    assert [c.text for c in drawn] == ["Hide", "Menu"]
    assert all(c.font.size == 20 and c.color == PLUM for c in drawn)
    assert drawn[0].bounds[0] < drawn[1].bounds[0]
    assert drawn[0].font == g.shell.theme.font(20)       # the UI face (AC-F10-22)
    found = items(g)
    menu, hide = found["menu"], found["hide"]
    with spy_draw_text(monkeypatch) as calls:
        g.frame(H.motion(centre(menu)))
    (label,) = [c for c in calls if c.text == "Menu"]
    assert label.color == BERRY
    assert [c.color for c in calls if c.text == "Hide"] == [PLUM]
    rows = _underline_rows(g, menu)
    font = g.shell.theme.font(20)
    ascent = g.h.canvas.font_handle(font, 20).font.get_ascent()
    baseline = label.bounds[1] + ascent
    assert len(rows) == 2 and abs(rows[0] - (baseline + 3)) <= 1
    assert _underline_rows(g, hide) == []
    # Holding a press on Hide: the pressed chip, inset 2.
    g.frame(H.down(centre(hide)))
    assert close(g.px((hide.box.x + 5, hide.box.center[1])), BLUSH)
    assert close(g.px((hide.box.x + 1, hide.box.center[1])), over(PINK_WHITE, 0.9, (0, 0, 0)), 3)
    g.frame(H.up((640, 400)))                            # released off the pill: nothing
    assert not g.textbox.hidden


def test_ac50_on_chip_and_disabled_entry(tmp_path, monkeypatch):
    g = Game(tmp_path)
    acted = []
    g.shell.menus.add("quick", MenuEntry("skip", action=lambda ctx: acted.append("skip"),
                                         on=lambda: True))
    g.shell.menus.add("quick", MenuEntry("auto", action=lambda ctx: acted.append("auto"),
                                         enabled=lambda: False))
    with spy_draw_text(monkeypatch) as calls:
        g.frame()
    found = items(g)
    assert list(found) == ["skip", "auto", "hide", "menu"]
    skip, auto = found["skip"], found["auto"]
    cy = skip.box.center[1]
    assert close(g.px((skip.box.x + 3, cy)), BERRY)             # the 2-unit border
    assert close(g.px((skip.box.x + 6, cy)), BLUSH)             # the on fill
    (drawn,) = [c for c in calls if c.text == "Auto"]
    assert drawn.color == MAUVE and drawn.font == g.shell.theme.font(20, italic=True)
    click(g, centre(auto))                               # takes no click, never advances
    g.frame(H.motion(centre(auto)))
    assert acted == [] and g.app.story.posted == [] and not g.textbox.hidden
    assert _underline_rows(g, auto) == []                # never hovered


# --- AC-F10-51 — clicks never leak --------------------------------------------------------------

def test_ac51_clicks_on_the_pill(tmp_path):
    g = typing_game(tmp_path / "hide")
    count = g.textbox.shown_count()
    click(g, centre(items(g)["hide"]))                   # down and up in one frame
    assert g.textbox.hidden and g.app.story.posted == []
    assert g.textbox.shown_count() == count
    g.frames(3)
    assert g.textbox.shown_count() == count              # hidden: typing frozen
    g = typing_game(tmp_path / "left-end")               # the pill's left end acts as Hide
    box = pill(g)
    click(g, (box.x + 1, box.center[1]))
    assert g.textbox.hidden and g.app.story.posted == []
    g = typing_game(tmp_path / "menu")
    click(g, centre(items(g)["menu"]))
    menu = g.top
    assert isinstance(menu, GameMenuScreen) and menu.opened_by is InputKind.MOUSE
    assert menu.scope.focused is None
    assert g.app.story.posted == []
    for up_at in ("off-pill", "menu"):                   # a press released elsewhere
        g = typing_game(tmp_path / f"up-{up_at}")
        found = items(g)
        line = g.textbox.line
        g.frame(H.down(centre(found["hide"])))
        g.frame(H.up((640, 400) if up_at == "off-pill" else centre(found["menu"])))
        assert not g.textbox.hidden and g.shell.game_menu() is None, up_at
        assert g.app.story.posted == [] and g.textbox.line is line, up_at
        assert g.textbox.typer.state.name == "TYPING", up_at
    # The capture ends when the game menu covers the game.
    g = Game(tmp_path / "capture")
    hide = centre(items(g)["hide"])
    g.frame(H.down(hide))
    assert quick(g).captured == "hide"
    g.frame(H.key(pygame.K_ESCAPE))
    g.frame()
    assert quick(g).captured is None
    g.frame(H.up(hide))
    assert not g.textbox.hidden


def test_ac51_strip_clicks_and_keys_over_hide_are_f05s(tmp_path):
    for name, pos in (("strip-left", (100, 704)), ("above-pill", (640, 689))):
        g = typing_game(tmp_path / name)
        click(g, pos)
        assert g.textbox.typer.state.name != "TYPING", name     # F05: the line completes
        assert not g.textbox.hidden, name
    for key in (pygame.K_SPACE, pygame.K_RETURN):
        g = typing_game(tmp_path / str(key))
        g.frame(H.motion(centre(items(g)["hide"])))
        g.frame(H.key(key))
        assert g.textbox.typer.state.name != "TYPING" and not g.textbox.hidden, key


# --- AC-F10-52 — over choices (fake choices; C6, C7, C8) --------------------------------------

def test_ac52_floor_follows_the_pill_and_a_click_on_a_choice_picks_it(tmp_path):
    g = ChoiceGame(tmp_path / "click")
    g.show_choices()
    click(g, BUTTONS[1].center)
    assert g.choices.chosen == ["c2"] and quick(g).captured is None
    assert not g.textbox.hidden and g.shell.game_menu() is None
    g = ChoiceGame(tmp_path / "floor")
    assert g.choices.floor_set == 1
    assert g.choices.floor() == 686                      # the quick menu shows over the box
    g.textbox.settings.text_size = 42                    # 150 %: pill y 688–720 (I-4)
    assert (pill(g).y, pill(g).bottom) == (688, 720) and g.choices.floor() == 684
    g.textbox.settings.text_size = None
    g.frame(H.key(pygame.K_h))
    assert g.choices.floor() == 686                      # hidden mode aside (laid out once)
    g.textbox.clear()
    assert g.choices.floor() == 704                      # no box: F07's step 3 to 704
    off = ChoiceGame(tmp_path / "off", "[quick_menu]\nenabled = false")
    assert off.choices.floor() == 704


def test_ac52_hide_and_show_over_choices_keep_focus_and_never_choose(tmp_path, monkeypatch):
    g = ChoiceGame(tmp_path)
    screen = g.show_choices()
    assert screen.floor_at_open == 686
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_DOWN))
    assert screen.focus == 1                             # c2
    click(g, centre(items(g)["hide"]))
    assert g.textbox.hidden and screen.hidden and g.choices.chosen == []
    with spy_draw_text(monkeypatch) as calls:
        g.frame()
    assert quick_labels(calls) == []
    assert g.px((640, 231)) == (0, 0, 0)                 # the choices hide with the box
    click(g, (640, 400))                                 # a left click shows both
    assert not g.textbox.hidden and g.choices.chosen == [] and screen.focus == 1
    g.frame()
    assert g.px((640, 231)) == FOCUSED


def test_ac52_menu_over_choices_and_back_and_a_strip_click_reaches_f05(tmp_path):
    g = ChoiceGame(tmp_path / "menu")
    screen = g.show_choices()
    g.frame(H.key(pygame.K_DOWN))
    click(g, centre(items(g)["menu"]))
    assert isinstance(g.top, GameMenuScreen) and g.choices.chosen == []
    g.frames(FADE + 1)
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(FADE + 1)
    assert g.stack == [g.textbox, screen] and screen.focus == 0
    assert g.choices.chosen == []
    g = ChoiceGame(tmp_path / "strip")
    g.textbox.show(TYPING)
    g.frames(2)
    g.show_choices()
    click(g, (100, 704))
    assert g.textbox.typer.state.name != "TYPING" and g.choices.chosen == []


# --- AC-F10-53 — not in the focus order ---------------------------------------------------------

def test_ac53_keys_and_gamepad_never_reach_the_quick_menu(tmp_path, monkeypatch):
    g = Game(tmp_path)
    keys = [H.key(pygame.K_TAB), H.key(pygame.K_LEFT), H.key(pygame.K_RIGHT),
            H.key(pygame.K_UP), H.key(pygame.K_DOWN),
            H.pad(pygame.CONTROLLER_BUTTON_DPAD_LEFT), H.pad(pygame.CONTROLLER_BUTTON_DPAD_RIGHT)]
    with spy_draw_text(monkeypatch) as calls:
        for event in keys:
            g.frame(event)
    assert all(c.color == PLUM for c in calls if c.text in ("Hide", "Menu"))
    assert not g.textbox.hidden and g.shell.game_menu() is None
    assert g.app.story.posted == []
    for advance in (H.key(pygame.K_SPACE), H.key(pygame.K_RETURN),
                    H.pad(pygame.CONTROLLER_BUTTON_A)):
        g.textbox.show(LINE)
        g.frame()
        g.frame(advance)
        assert g.app.story.posted[-1] == Advance(LINE.sid)
    assert not g.textbox.hidden and g.shell.game_menu() is None


# --- AC-F10-54 — author control -----------------------------------------------------------------

def test_ac54_entries_order_filter_and_a_fake_skip_entry(tmp_path, monkeypatch):
    for entries, shown in (('["menu", "hide"]', ["Menu", "Hide"]), ('["menu"]', ["Menu"])):
        g = Game(tmp_path / str(len(shown)), f"[quick_menu]\nentries = {entries}")
        with spy_draw_text(monkeypatch) as calls:
            g.frame()
        assert quick_labels(calls) == shown, entries
    g = Game(tmp_path / "skip")
    g.shell.menus.add("quick", MenuEntry("skip", action=lambda ctx: None, on=lambda: True))
    with spy_draw_text(monkeypatch) as calls:
        g.frame()
    assert quick_labels(calls) == ["Skip", "Hide", "Menu"]


# --- AC-F10-27 (quick rows) — W66 ---------------------------------------------------------------

def _w66(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if getattr(r, "code", "") == "W66"]


def test_ac27_w66_quick_rows(tmp_path, caplog, monkeypatch):
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        g = Game(tmp_path / "typo", '[quick_menu]\nentries = ["hied", "menu"]')
    assert _w66(caplog) == [
        'config.toml: [quick_menu] entries has "hied", which isn\'t a quick-menu button. '
        'Did you mean "hide"? The buttons are hide and menu.']
    with spy_draw_text(monkeypatch) as calls:
        g.frame()
    assert quick_labels(calls) == ["Menu"]
    for n, entries in enumerate(("[]", '["xyz"]')):     # the empty-list form shows the defaults
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="vn.ui"):
            g = Game(tmp_path / f"empty{n}", f"[quick_menu]\nentries = {entries}")
        (text,) = _w66(caplog)
        assert text.startswith("config.toml: [quick_menu] entries "), entries
        assert "so the default buttons are shown: hide and menu." in text, entries
        with spy_draw_text(monkeypatch) as calls:
            g.frame()
        assert quick_labels(calls) == ["Hide", "Menu"], entries
    # A late registration (after install_ui, before check_entries) gives no W66.
    caplog.clear()
    root = make_game(tmp_path / "late", '[quick_menu]\nentries = ["back", "menu"]')
    paths = GamePaths.for_game(root)
    app = FakeApp(load_config(paths).config, make_assets(paths))
    install_textbox(app)
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        shell = install_ui(app)
        shell.menus.add("quick", MenuEntry("back", action=lambda ctx: None))   # F14's install
        shell.check_entries()
    assert _w66(caplog) == []
    assert [e.id for e in shell.menus.shown("quick")] == ["back", "menu"]


# --- AC-F10-25 and AC-F10-22 (quick rows) -------------------------------------------------------

def test_ac25_ac22_quick_words_overrides_and_colors(tmp_path, monkeypatch):
    g = Game(tmp_path / "words", '[words]\nhide = "X-hide"\nmenu = "X-menu"')
    with spy_draw_text(monkeypatch) as calls:
        g.frame()
    assert [c.text for c in calls if c.text.startswith("X-")] == ["X-hide", "X-menu"]
    before = pill(g).w
    g.shell.overrides.set_word("menu", "A much longer menu word")
    with spy_draw_text(monkeypatch) as calls:
        g.frame()
    assert "A much longer menu word" in [c.text for c in calls]
    assert pill(g).w > before                            # laid out again on a label change
    g = Game(tmp_path / "theme", '[theme.quick_menu]\nfill_color = "#2A1E2E"\nfill_opacity = 1.0')
    box = pill(g)
    g.frame()
    assert close(g.px((box.x + 3, 704)), (0x2A, 0x1E, 0x2E))


# --- AC-F10-29 (quick row) — the quick menu's own sound ----------------------------------------

def test_ac29_click_hide_plays_the_quick_menu_sound(tmp_path):
    for name, config, sound in (
        ("quick", '[theme.button]\nactivate_sound = "a.ogg"\n'
                  '[theme.quick_menu]\nactivate_sound = "q.ogg"', "q.ogg"),
        ("button", '[theme.button]\nactivate_sound = "a.ogg"', "a.ogg"),
        ("none", "", None),
    ):
        spy = AudioSpy()
        g = Game(tmp_path / name, config, audio=spy)
        click(g, centre(items(g)["hide"]))
        assert g.textbox.hidden, name
        ui = [c for c in spy.calls if c[0] == "play_ui"]
        assert ui == ([("play_ui", sound)] if sound else []), name


# --- AC-F10-38 (the reset, I-8) — after Main Menu → Yes → New Game ----------------------------

def test_ac38_new_game_after_hiding_choices_leaves_nothing(tmp_path):
    spy = AudioSpy()
    g = ChoiceGame(tmp_path, audio=spy)
    g.show_choices()
    click(g, centre(items(g)["hide"]))
    assert g.textbox.hidden
    g.shell.return_to_title()                            # Main Menu → Yes
    g.frames(FADE + 3)
    assert isinstance(g.top, TitleScreen)
    assert ("stop_story_audio", 0.5) in spy.calls
    g.frames(31)
    g.frame(H.key(pygame.K_DOWN))
    g.frame(H.key(pygame.K_RETURN))                      # New Game
    g.frames(FADE + 2)
    assert g.stack == [g.textbox] and g.shell.mode is Mode.GAME
    assert g.choices.screen is None
    assert not any(isinstance(s, FakeChoiceScreen) for s in g.stack)
    assert not g.textbox.hidden
