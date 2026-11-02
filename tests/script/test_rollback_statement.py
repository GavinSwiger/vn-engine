"""F14 step 1 — the ``rollback`` statement at load (``script/rollback.py``, ``checks.py``):
AC-F14-16's node rows (the four words, ``Menu.fixed`` from ``attach_fixed``, the menu's sid,
``VOICE_TRANSPARENT``). Its message rows (E200–E204, E60, E31, the clean forms) are in
``tests/fixtures/F02/messages/cases.toml``."""

from engine.core.paths import GamePaths
from engine.script.loader import load_story
from engine.script.menu import Menu
from engine.script.rollback import Rollback
from tests.script.helpers import first_say, parse_text, template


def load(tmp_path, S: str):
    script = tmp_path / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_text(template(S=S), encoding="utf-8")
    result = load_story(GamePaths(tmp_path.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    assert not result.warnings, result.warnings                     # no W20
    return result.program


def test_ac16_rollback_statement_nodes(tmp_path):
    """AC-F14-16 node rows: the four words, ``fixed`` on the next menu only, the voice."""
    for word in ("block", "off", "on", "fixed"):
        parsed = parse_text(template(S=f"rollback {word}  # comment"))
        node = first_say(parsed)
        assert type(node) is Rollback and node.word == word, parsed.messages
        assert node.identity_key() == ("rollback", word)
    # ``rollback fixed`` marks only the menu right below it.
    outer = 'menu:⏎[8]"Go":⏎[12]rollback fixed⏎[12]menu:⏎[16]"Stay":⏎[20]"Stayed."'
    program = load(tmp_path / "a", outer)
    menu = program.at("start", (1,))
    inner = menu.choices[0].block[1]
    assert type(menu) is Menu and type(inner) is Menu
    assert (menu.fixed, inner.fixed) == (False, True)
    fixed = load(tmp_path / "b", 'rollback fixed⏎[4]menu:⏎[8]"Go":⏎[12]"Gone."')
    plain = load(tmp_path / "c", 'menu:⏎[8]"Go":⏎[12]"Gone."')
    assert fixed.at("start", (2,)).fixed and not plain.at("start", (1,)).fixed
    assert fixed.at("start", (2,)).sid == plain.at("start", (1,)).sid
    # A voice looks past ``rollback``.
    program = load(tmp_path / "d", 'voice "voice/x.ogg"⏎[4]rollback block⏎[4]hana "Hi."')
    line = program.at("start", (3,))
    assert line.voice == "voice/x.ogg"
