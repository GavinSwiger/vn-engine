"""F17 step 3 — menus in NVL (``06-acceptance.md`` §1.5): the choice area (AC-F17-23, with
``07`` I-1's tall-question row) and menus on screen and after a pick (AC-F17-24, with I-1's
row in a script).

AC-F17-23 is a unit test: the real ``TextboxScreen`` (no window) with a page set through
``show_nvl``, and F07's real ``ChoiceController``/``ChoiceLayout`` on M20 (``FixedFontAssets``,
46 graphemes per 920-unit row at size 28). AC-F17-24 runs App A (``tests/fakes/text_app.py``)
on Template N, one row per run.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from engine.core.config_schema import ChoiceTheme, Config
from engine.render.choices import ChoiceArea, ChoiceStackView, half_up
from engine.render.textbox import TextboxView
from engine.render.textlayout import BUNDLED_FACES
from engine.render.typewriter import TypeState
from engine.runtime.commands import BASE_STYLE, NvlLine, NvlPage, ShowMenu, ShownChoice, Span
from engine.ui.builtin.choice_screen import ChoiceController
from engine.ui.builtin.nvl_page import NvlPresenter
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.screen import ScreenStack
from tests.fakes.fixed_font import FixedFontAssets, tagged
from tests.fakes.text_app import Session, make_text_game
from tests.script.helpers import template_n

# --- AC-F17-23 — the choice area (unit) ----------------------------------------------------------


def _line(text: str, name: str = "", key: int = 0) -> NvlLine:
    return NvlLine(f"main/{key}", name, None, (Span(text, BASE_STYLE),) if text else ())


def _unit(page: tuple[NvlLine, ...], *, nvl: bool = True):
    assets = FixedFontAssets()
    config = Config()
    view = TextboxView(assets, config.theme.textbox, BUNDLED_FACES.for_style(True, False))
    textbox = TextboxScreen(SimpleNamespace(story=None, focused=True), config, view,
                            BUNDLED_FACES)
    if nvl:
        textbox.show_nvl(NvlPage(True, page))
    controller = ChoiceController(ScreenStack(), textbox, theme=ChoiceTheme(), assets=assets,
                                  faces=BUNDLED_FACES, base_text_size=28, post=lambda e: None)
    return textbox, controller


def _menu(*texts: str, line: str = "question") -> ShowMenu:
    return ShowMenu("main/m", tuple(ShownChoice(f"k{i}", tagged(t), False)
                                    for i, t in enumerate(texts)), line)


A10 = "a" * 10
TEMPLATE_PAGE = (_line("Three days later, a lantern came.", key=12),
                 _line("It was a letter.", key=14),
                 _line("Will you open it?", "Hana", key=16))
EIGHT = tuple(_line(A10, key=k) for k in range(8))
ROWS13 = "\n".join("abcdefghijklm")


@pytest.mark.parametrize("name, page, choices, area, tops, step, view", [
    ("template N", TEMPLATE_PAGE, ("Open it", "Not yet"), (284, 648), (284, 355), 0, None),
    ("empty page", (), ("One", "Two"), (64, 648), (64, 135), 0, None),
    ("one a10", (_line(A10),), ("One", "Two"), (127, 648), (127, 198), 0, None),
    ("restart", EIGHT + (_line("Will you open it?", "Hana", key=8),), ("One", "Two"),
     (166, 648), (166, 237), 0, [8]),
    ("restart, six a60", EIGHT + (_line("Will you open it?", "Hana", key=8),),
     ("a" * 60,) * 6, (166, 648), (166, 246, 326, 406, 486, 566), 2, [8]),
    ("a690 question", (_line(A10), _line("a" * 690, key=1)), ("One", "Two"), (127, 648),
     (127, 198), 0, None),
    ("tall question (I-1)", TEMPLATE_PAGE[:2] + (_line(ROWS13, "Hana", key=16),),
     ("One", "Two"), (634, 648), None, 3, None),
    ("ADV", None, ("Open it", "Not yet"), None, None, 0, None),
])
def test_ac_f17_23_the_choice_area(name, page, choices, area, tops, step, view):
    if page is None:                       # ADV (Template N without line 7): F07's own rule
        textbox, controller = _unit((), nvl=False)
        out = controller.layout(_menu(*choices))
        assert textbox.choice_area(out.fits) is None
        assert out.area == ChoiceArea(16, textbox.tab_top() - 16, 704, "center")
        return
    textbox, controller = _unit(page)
    cmd = _menu(*choices, line="question" if page else "none")
    out = controller.layout(cmd)
    nvl = textbox.nvl
    assert textbox.choice_area(out.fits) == area, name
    assert out.step == step, name
    assert all(b.rect[0] == 240 and b.rect[0] + b.rect[2] == 1040 for b in out.buttons)
    if step < 3:                                       # D1: stack top = area top
        assert out.area == ChoiceArea(area[0], area[1], 704, "top") and out.tops == tops, name
    else:                                              # I-1: F07's own last resort, centered
        stack = out.bottom - out.top
        assert out.top == 16 + half_up((704 - 16 - stack) / 2), name
        assert all(b.rect[1] + b.rect[3] <= controller.floor() for b in out.buttons)
        assert [r.entry for r in nvl.rows()] == [len(page) - 1]     # the question stays
    if view is not None:                               # the view plan: the question only
        assert [(r.entry, r.y) for r in nvl.rows()] == [(view[0], 64)], name
        assert nvl.view is not None and len(nvl.plan.rows) == 9
    else:
        assert nvl.view is None, name
    if name == "a690 question":                        # its last page, alone on the page
        assert [(r.entry, r.page, r.y) for r in nvl.rows()] == [(1, -1, 64)]


# --- AC-F17-24 — menus on screen and after a pick (App A) -------------------------------------

RED = (255, 0, 0)
PANEL = (255, 207, 211)
P = (640, 30)
CPS0 = "[textbox]\ncps = 0\n"
ROWS13_SCRIPT = ROWS13.replace("\n", "\\n")        # Rows(13) as the script writes it
QUESTIONLESS = {"drop": (16,)}


def _game(tmp_path: Path, name: str, **edit) -> Path:
    root = make_text_game(tmp_path / name, script=template_n(**edit), config=CPS0)
    (root / "images").mkdir(exist_ok=True)
    red = pygame.Surface((1280, 720))
    red.fill(RED)
    pygame.image.save(red, str(root / "images" / "red.png"))
    return root


def _all_red(s: Session) -> bool:
    fb = s.fb
    mask = pygame.mask.from_threshold(fb, (*RED, 255), (1, 1, 1, 255))
    return mask.count() == fb.get_width() * fb.get_height()


def _above_pill(s: Session) -> bytes:
    """The frame above the quick menu's pill (the floor). The pill itself may differ after a
    restore: F14's Back entry follows the rollback history, which a restore resets."""
    floor = int(s.app.choices.floor())
    return pygame.image.tobytes(s.fb.subsurface((0, 0, 1280, floor)), "RGB")


def _pill_drawn(s: Session) -> bool:
    floor = int(s.app.choices.floor())
    band = s.fb.subsurface((0, floor, 1280, 720 - floor))
    mask = pygame.mask.from_threshold(band, (*RED, 255), (1, 1, 1, 255))
    return mask.count() < band.get_width() * band.get_height()


def _texts(s: Session) -> list[tuple[str, float]]:
    """(record text, y) of every row on screen."""
    nvl = s.textbox.nvl
    return [("".join(span.text for span in nvl.entries[r.entry].spans), r.y)
            for r in nvl.rows()]


ROWS_24 = {
    "template N": ({}, "question", [("Three days later, a lantern came.", 64),
                                     ("It was a letter.", 123),
                                     ("Will you open it?", 182)], (284, 355)),
    "question-less": (QUESTIONLESS, "kept", [("Three days later, a lantern came.", 64),
                                              ("It was a letter.", 123)], (186, 257)),
    "scene red first": ({"replace": {15: "    scene red⏎    menu:"}, **QUESTIONLESS}, "none",
                        [("Three days later, a lantern came.", 64),
                         ("It was a letter.", 123)], (186, 257)),
    "nvl clear first": ({"replace": {15: "    nvl clear⏎    menu:"}, **QUESTIONLESS}, "none",
                        [], (64, 135)),
    "nvl off first": ({"replace": {15: "    nvl off⏎    $ pass⏎    menu:"}, **QUESTIONLESS},
                      "none", None, None),
    "restart (AC-F17-23)": ({"replace": {12: "⏎".join(['    "aaaaaaaaaa"'] * 8)},
                             "drop": (13, 14)}, "question", [("Will you open it?", 64)],
                            (166, 237)),
    "tall question (I-1)": ({"replace": {16: f'        hana "{ROWS13_SCRIPT}"'}}, "question",
                            [(ROWS13, 64)], "step 3"),
}


@pytest.mark.display
@pytest.mark.parametrize("row", list(ROWS_24))
def test_ac_f17_24_menus_on_screen_and_after_a_pick(tmp_path, monkeypatch, row):
    edit, line, texts, tops = ROWS_24[row]
    clears: list[str] = []
    real_clear = TextboxScreen.clear

    def clear(self, *, hide=True):
        clears.append(inspect.currentframe().f_back.f_globals["__name__"])
        real_clear(self, hide=hide)

    monkeypatch.setattr(TextboxScreen, "clear", clear)
    choice_draws: list[int] = []
    real_draw = ChoiceStackView.draw

    def draw(self, canvas, layout, states, *, alpha=1.0):
        choice_draws.append(len(layout.buttons))
        real_draw(self, canvas, layout, states, alpha=alpha)

    monkeypatch.setattr(ChoiceStackView, "draw", draw)
    s = Session(_game(tmp_path, "g", **edit))
    seen: dict[str, object] = {}
    restarts: list[bool] = []                 # AC-F17-23: a view-plan restart is display only
    real_area = NvlPresenter.choice_area

    def choice_area(self, fits):
        before = self.view
        story = s.app.story.checkpoint().to_json()
        out = real_area(self, fits)
        if before is None and self.view is not None:
            restarts.append(story == s.app.story.checkpoint().to_json())
        return out

    monkeypatch.setattr(NvlPresenter, "choice_area", choice_area)

    def picture(s):
        choices = s.app.choices
        screen = choices.screen
        tb = s.textbox
        layout = screen.layout
        return {"nvl": tb.nvl_on, "line": screen.cmd.line,
                "texts": _texts(s) if tb.nvl_on else None,
                "tops": layout.tops, "step": layout.step, "area": layout.area,
                "bottoms": [b.rect[1] + b.rect[3] for b in layout.buttons],
                "floor": choices.floor(),
                "complete": tb.line is None or tb.typer.state is TypeState.COMPLETE,
                "indicator": tb.indicator_kind(), "panel": s.px(*P)}

    def script(s):
        yield from _to_menu(s)
        for _ in range(12):                               # past the 120 ms fade
            yield
        seen["live"] = picture(s)
        seen["live_fb"] = _above_pill(s)
        seen["drawn_line"] = [r.entry for r in s.textbox.nvl.rows()] if s.textbox.nvl_on \
            else None
        state = s.app.story.checkpoint()
        s.app.story.restore(state)                        # restored at the menu
        yield
        seen["restored"] = picture(s) if s.app.choices.screen is not None else None
        seen["restored_fb"] = _above_pill(s)
        seen["json"] = (state.to_json(), s.app.story.checkpoint().to_json())
        s.key(pygame.K_h)                                 # H at the menu
        yield
        yield
        seen["hidden"] = (_all_red(s), s.textbox.box_shown)
        count = len(choice_draws)
        yield
        seen["hidden_draws"] = len(choice_draws) - count
        s.key(pygame.K_h)
        for _ in range(30):                               # the quick menu fades back in
            yield
        seen["shown_again"] = (_above_pill(s) == seen["live_fb"], _pill_drawn(s))
        for _ in range(20):                               # past the guard
            yield
        count = len(s.said)
        s.key(pygame.K_1)                                 # pick "Open it"
        yield from s.until(lambda: len(s.said) > count)
        seen["after"] = _texts(s) if s.textbox.nvl_on else None

    s.play(script)
    live, restored = seen["live"], seen["restored"]
    assert live["line"] == line
    by_f07 = [name for name in clears if name.endswith("choice_screen")]
    if texts is None:                                     # ADV: F07's none area (and clear)
        assert not live["nvl"] and (live["area"].top, live["area"].bottom) == (16, 704)
        assert by_f07                                     # F07's ADV rule is unchanged
    else:
        assert by_f07 == []                               # C1: never in NVL
        assert live["nvl"] and live["texts"] == texts and live["panel"] == PANEL
        assert live["indicator"] is None and live["complete"]
        ids = seen["drawn_line"]
        assert len(ids) == len(set(ids))                  # each line drawn once
        if tops == "step 3":                              # I-1: F07's own last resort
            assert live["step"] == 3 and live["floor"] < 704
            assert all(b <= live["floor"] for b in live["bottoms"])   # the pill stays clear
        else:
            assert live["tops"] == tops and live["area"].align == "top"
        assert seen["hidden"] == (True, False) and seen["hidden_draws"] == 0
        assert seen["shown_again"] == (True, True)
        assert seen["after"] == [("After the pick.", 64)]
    assert restored == live                               # the same picture, first frame
    assert seen["restored_fb"] == seen["live_fb"]
    assert seen["json"][0] == seen["json"][1]
    assert restarts == ([True, True] if row.startswith("restart") else [])   # live, restored


def _to_menu(s: Session):
    """Advance (Space) until a menu's choices are on screen."""
    while True:
        choices = getattr(s.app, "choices", None)
        if choices is not None and choices.screen is not None and choices.screen.started:
            return
        tb = s.textbox
        if tb is not None and tb.line is not None and tb.typer is not None \
                and not tb.menu_waiting and tb.indicator_kind() is not None:
            s.key(pygame.K_SPACE)
        yield
