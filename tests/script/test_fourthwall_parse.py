"""F30 step 2: ``effect window_title`` and ``effect crash`` at load, and where ``{username}`` may
go (``06-acceptance.md`` AC-F30-08's node rows, AC-F30-10's unit rows). AC-F30-08, 09, and 10's
messages are rows of ``tests/fixtures/F02/messages/cases.toml`` (``test_messages.py``).

``effect`` has no executor until F28 s3, so it is registered only inside ``scoped_registry()``
here (F19 07 I-5; F30 07 I-15)."""

import pytest

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.core.paths import GamePaths
from engine.runtime.character import CharacterFactory, CharacterOptionError
from engine.runtime.commands import Say, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import CHECKPOINT_TYPES
from engine.script import glitch
from engine.script.audio_checks import VOICE_TRANSPARENT
from engine.script.fourthwall import CrashEffect, TitleEffect
from engine.script.glitch import EFFECT_STATEMENT_KINDS, Effect
from engine.script.loader import load_story
from engine.script.statements import scoped_registry
from engine.script.texttags import NameMark, Span, VarMark, parse
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)
from tests.script.helpers import parse_text, template_f30

IMAGES = ("images/bg/room.png",)


@pytest.fixture
def effect_word():
    with scoped_registry():
        glitch.register_words()
        yield


def _node(S: str):
    parsed = parse_text(template_f30(S=S))
    assert parsed.codes == [], (S, parsed.messages)
    return parsed.nodes[2].block[2]


def test_ac_f30_08_effect_window_title_and_crash_parse(effect_word, tmp_path):
    rows = [
        ('effect window_title "Night"', TitleEffect, "Night"),
        ('effect window_title ""', TitleEffect, ""),
        ("effect window_title off", TitleEffect, None),
        ('effect window_title "a {{b"', TitleEffect, "a {b"),
        ('effect window_title "' + "é" * 100 + '"', TitleEffect, "é" * 100),
        ("effect crash", CrashEffect, None),
    ]
    for S, kind, value in rows:
        node = _node(S)
        assert type(node) is kind, S
        assert (node.text if kind is TitleEffect else node.body) == value, S
        assert node.identity_key() == ("effect",)
    pieces = _node('effect crash "Hi {username}, {var=v}, {{x"').body.pieces
    assert [type(p) for p in pieces] == [Span, NameMark, Span, VarMark, Span]
    assert pieces[1].var is None and pieces[3].name == "v" and pieces[4].text == ", {x"
    assert type(_node('effect crash "' + "a" * 2000 + '"')) is CrashEffect
    assert _node("effect off").kind is None                              # F28's, unchanged
    assert tuple(EFFECT_STATEMENT_KINDS) == ("tear", "colorshift", "static", "jitter",
                                             "window_title", "crash")
    for node_type in (TitleEffect, CrashEffect):
        assert node_type not in CHECKPOINT_TYPES and node_type in VOICE_TRANSPARENT
    assert Effect in VOICE_TRANSPARENT

    # The kind words stay free as story names; window_titles holds the script's titles (I-7).
    script = tmp_path / "script"
    script.mkdir()
    (script / "main.vns").write_text(template_f30(
        S='$ crash += 1⏎effect window_title "Night"⏎effect window_title off',
        T='default crash = 1⏎default window_title = "x"⏎default username = "x"'),
        encoding="utf-8")
    program = load_story(GamePaths(tmp_path.resolve())).program
    assert program.window_titles == frozenset({"Night"})
    # No executor until F30 s3, so the run leaves the effect lines out.
    (script / "main.vns").write_text(template_f30(
        S="$ crash += 1", T='default crash = 1⏎default window_title = "x"⏎'
                            'default username = "x"'), encoding="utf-8")
    program = load_story(GamePaths(tmp_path.resolve())).program
    commands = run_headless(program, seed=42, image_files=IMAGES)
    assert not any(type(c) is StoryFailed for c in commands)
    assert sum(type(c) is Say for c in commands) == 4


def test_ac_f30_10_username_places():
    # Dialogue, narration, and a menu question take it; E175, E252, E302's title card and the
    # tag errors are cases.toml rows. A character name is refused at the define (launch).
    with pytest.raises(CharacterOptionError) as refused:
        CharacterFactory(frozenset())("Hi {username}")
    assert refused.value.code == "E302"
    assert refused.value.message.endswith("not in a character name.")
    seen = []
    body = parse("Hi {username=v}.", lambda at: (7, at + 1), seen.append,
                 on_var=lambda *use: seen.append(use))
    assert seen == [("v", 7, 4)]                                         # no W42 for v
    assert body.pieces[1] == NameMark("v", body.pieces[0].style)
