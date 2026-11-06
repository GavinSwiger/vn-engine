"""F64 present at a menu on screen (specs/F64-items/SPEC-present.md): the menu's Show an
item… button opens the item picker, a pick posts ``Choose(sid, key, item)``, Back leaves
the menu waiting; the picker lists held items only."""

from engine.runtime.commands import Choose, ShowMenu, ShownChoice, TaggedText
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.present_picker import PANEL, PresentScreen, heading_text
from engine.ui.nav import InputKind
from tests.fakes.fixed_font import tagged
from tests.fakes.ui_shell import TestShell, UiHarness
from tests.ui.test_choice_screen import Rig
from tests.ui.test_codex_view import PortP

PRESENT = "c0ffee000000"


def _rig() -> tuple[Rig, list]:
    rig = Rig()
    opened: list = []
    rig.controller.set_presenter(lambda on_pick, by: opened.append((on_pick, by)),
                                 lambda: "Show something…")
    cmd = ShowMenu("menu/1", (ShownChoice("c1", tagged("Choice 1"), False),
                              ShownChoice(PRESENT, TaggedText((), False), False,
                                          present=True)), "question")
    rig.cmd = cmd
    rig.controller.show(cmd)
    return rig, opened


def test_the_present_button_opens_the_picker_and_its_pick_is_posted():
    rig, opened = _rig()
    screen = rig.past_guard()
    texts = ["".join(s.text for s in body.plain()) for body in screen.layout.bodies] \
        if hasattr(screen.layout, "bodies") else None
    rig.controller.pick(screen, PRESENT, by=InputKind.MOUSE)
    assert rig.posted == [] and rig.stack.top is screen          # still waiting
    on_pick, by = opened[0]
    assert by is InputKind.MOUSE
    on_pick("red_lantern")
    assert rig.posted == [Choose("menu/1", PRESENT, "red_lantern")]
    assert not any(isinstance(s, ChoiceScreen) for s in rig.stack)


def test_back_from_the_picker_leaves_the_menu_and_a_pick_after_it_closed_is_ignored():
    rig, opened = _rig()
    screen = rig.past_guard()
    rig.controller.pick(screen, PRESENT)
    rig.controller.close()                                        # a load, a new game
    opened[0][0]("red_lantern")
    assert rig.posted == []


def test_without_a_picker_nothing_happens():
    rig = Rig()
    cmd = ShowMenu("menu/1", (ShownChoice("c1", tagged("Choice 1"), False),
                              ShownChoice(PRESENT, TaggedText((), False), False,
                                          present=True)), "question")
    rig.controller.show(cmd)
    screen = rig.past_guard()
    rig.controller.pick(screen, PRESENT)
    assert rig.posted == [] and rig.stack.top is screen


def test_the_picker_lists_held_items_and_shows_the_pick():
    shell = TestShell(reduce_motion=True)
    picked: list[str] = []
    port = PortP(t=("lanterns",), i=("red_lantern", "coin"))
    screen = PresentScreen(shell, port, picked.append, by=InputKind.KEYS)
    shell.stack.push(screen)
    harness = UiHarness(shell)
    harness.frame()
    view = screen.view
    assert [r.entry.name for t in view.tabs for r in t.rows] == ["red_lantern", "coin"]
    assert view.pick_button is not None and view.pick_button.label() == "Show"
    assert PANEL.contains(screen.back_button.box.center)
    assert screen.view_box.w >= 640 and screen.view_box.h >= 400
    view.pick_button.activate()
    harness.frame()
    assert picked == ["red_lantern"] and screen not in list(shell.stack)


def test_back_closes_the_picker_without_a_pick():
    shell = TestShell(reduce_motion=True)
    picked: list[str] = []
    screen = PresentScreen(shell, PortP(i=("coin",)), picked.append, by=InputKind.MOUSE)
    shell.stack.push(screen)
    harness = UiHarness(shell)
    harness.frame()
    screen.back()
    harness.frame()
    assert picked == [] and screen not in list(shell.stack)


def test_the_heading_drops_the_ellipsis():
    assert heading_text("Show an item…") == "Show an item"
    assert heading_text("Present...") == "Present"
    assert heading_text("…") == "…"


def test_large_text_still_fits():
    shell = TestShell(reduce_motion=True)
    shell.painter.text_scale = lambda: 1.5                         # type: ignore[method-assign]
    screen = PresentScreen(shell, PortP(i=("coin",)), lambda name: None, by=InputKind.KEYS)
    assert screen.view_box.h >= 400 and screen.back_button.box.bottom <= PANEL.bottom
