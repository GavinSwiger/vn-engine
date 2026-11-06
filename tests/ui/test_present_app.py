"""F64 present at a menu in the real App loop (specs/F64-items/SPEC-present.md): the menu's
Show an item… opens the bag over it, and showing an item runs its reaction."""

from engine.runtime.commands import Say
from engine.script.choicepresent import PRESENT_KEY
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.present_picker import PresentScreen
from engine.ui.nav import InputKind
from tests.fakes.text_app import Session, make_text_game

SCRIPT = '''define hana = Character("Hana")
lock item red_lantern "Red Lantern"
label start:
    unlock item red_lantern
    menu:
        hana "What's that in your hand?"
        "Nothing.":
            hana "Fine."
        present:
            red_lantern:
                hana "You kept it!"
            else:
                hana "Why?"
    hana "End."
'''


def _text(cmd: Say) -> str:
    return "".join(span.text for span in cmd.body.plain())


def test_showing_an_item_from_the_menu(tmp_path):
    session = Session(make_text_game(tmp_path / "game", script=SCRIPT))
    seen: dict[str, object] = {}

    def script(s: Session):
        while not isinstance(s.app.screens.top, ChoiceScreen):
            yield
        menu = s.app.screens.top
        assert [c.present for c in menu.cmd.choices] == [False, True]
        for _ in range(30):                                  # past the guard
            yield
        s.app.choices.pick(menu, PRESENT_KEY, by=InputKind.MOUSE)
        yield
        picker = s.app.screens.top
        assert isinstance(picker, PresentScreen)
        seen["rows"] = [r.entry.name for t in picker.view.tabs for r in t.rows]
        for _ in range(30):
            yield
        picker.view.pick_button.activate()
        for _ in range(60):
            yield
        seen["said"] = [_text(cmd) for _, cmd in s.said]

    session.play(script)
    assert seen["rows"] == ["red_lantern"]
    assert seen["said"][-1] == "You kept it!"
