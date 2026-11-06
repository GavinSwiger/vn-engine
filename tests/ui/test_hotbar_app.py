"""F64 round 2 in the real App loop: the hotbar in the corner (number keys, a click, the
gamepad), the "Not now" refusal while a line types, and the bag's Use button
(specs/F64-items/SPEC.md "Round 2")."""

import pygame

from engine.app.hotbar import KEY
from engine.runtime.commands import Say
from engine.ui.nav import InputKind
from tests.fakes.text_app import Session, make_text_game

SCRIPT = '''define hana = Character("Hana")
lock item tea "Jasmine Tea" count 0 to 5 use drink_tea
lock item map "Old Map" use read_map
lock item key "Brass Key"
default warm = 0
label start:
    unlock item tea 3
    unlock item key
    unlock item map
    show hotbar
    hana "One."
    hana "Two."
    hana "Three."
    hana "Four."
label drink_tea:
    lock item tea
    $ warm += 1
    hana "Warm."
    return
label read_map:
    hana "North."
    return
'''


def _text(cmd: Say) -> str:
    return "".join(span.text for span in cmd.body.plain())


def _hotbar(s: Session):
    return s.app.shell.corner.item(KEY)


def _ready(s: Session, text: str):
    yield from s.until_line(text)
    yield from s.until(lambda: s.textbox.indicator_kind() == "line")
    for _ in range(5):
        yield


def test_hotbar_keys_click_and_pad(tmp_path):
    session = Session(make_text_game(tmp_path / "game", script=SCRIPT))
    seen: dict[str, object] = {}

    def script(s: Session):
        yield from _ready(s, "One.")
        hotbar = _hotbar(s)
        assert hotbar is not None
        seen["slots"] = [(slot.key, slot.name, slot.count) for slot in hotbar.slots()]
        s.key(pygame.K_1)                                # tea: slot 1
        yield from _ready(s, "Warm.")
        seen["count"] = s.app.story.interp.codex.count("tea")
        s.key(pygame.K_SPACE)
        yield from _ready(s, "Two.")
        box = _hotbar(s).boxes[1]                        # map: a click on slot 2
        s.mouse((int(box.x + box.w / 2), int(box.y + box.h / 2)))
        yield from _ready(s, "North.")
        s.key(pygame.K_SPACE)
        yield from _ready(s, "Three.")
        s.key(pygame.K_4)                                # an empty slot: nothing
        for _ in range(10):
            yield
        assert s.line_text() == "Three."
        s.event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_X, instance_id=0)
        yield
        s.event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_A, instance_id=0)
        yield from _ready(s, "Warm.")
        seen["said"] = [_text(cmd) for _, cmd in s.said]

    session.play(script)
    assert seen["slots"] == [("1", "tea", 3), ("2", "map", None), ("3", None, None),
                             ("4", None, None)]
    assert seen["count"] == 2
    assert seen["said"] == ["One.", "Warm.", "Two.", "North.", "Three.", "Warm."]


def test_not_now_while_typing_and_the_bag_use(tmp_path):
    session = Session(make_text_game(tmp_path / "game", script=SCRIPT,
                                     config="[textbox]\ncps = 5\n"))
    seen: dict[str, object] = {"notices": []}

    def script(s: Session):
        yield from s.until_line("One.")
        shell = s.app.shell
        real = shell.notify
        shell.notify = lambda text, **kw: (seen["notices"].append(text), real(text, **kw))
        yield
        s.key(pygame.K_1)                                # still typing: refused
        for _ in range(3):
            yield
        seen["after_refusal"] = s.line_text()
        s.key(pygame.K_SPACE)                            # finish the line
        yield from s.until(lambda: s.textbox.indicator_kind() == "line")
        shell.open_game_menu(InputKind.KEYS)
        for _ in range(20):
            yield
        menu = shell.game_menu()
        menu.open_page("codex")
        for _ in range(10):
            yield
        view = menu.page.view
        seen["use_shown"] = view._use_shown()
        seen["hint"] = view.use_hint()
        seen["enabled"] = view.use_button.enabled()
        view.use_button.activate()
        yield from _ready(s, "Warm.")
        seen["said"] = [_text(cmd) for _, cmd in s.said]

    session.play(script)
    assert seen["after_refusal"] == "One." and seen["notices"] == ["Not now"]
    assert seen["use_shown"] is True and seen["enabled"] is True
    assert seen["hint"] == "Hotbar: 1"
    assert seen["said"] == ["One.", "Warm."]
