"""F32 step 2: the ``ui`` statement at load (``06-acceptance.md`` AC-F32-05; AC-F32-06's
``vn check`` sentence and its W204–W207 rows). AC-F32-06's load messages are rows of
``tests/fixtures/F02/messages/cases.toml`` (``test_messages.py``).

``ui`` is registered at import since F32 s4; the ``ui_word`` fixture still registers it
inside ``scoped_registry()`` (a no-op when it is registered, F19 07 I-5)."""

import shutil

import pytest

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.core.paths import GamePaths
from engine.runtime.commands import Say, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import CHECKPOINT_TYPES
from engine.runtime.state import reserved_since_save
from engine.script import ui
from engine.script.audio_checks import VOICE_TRANSPARENT
from engine.script.loader import LoadOptions, load_story
from engine.script.messages import format_message
from engine.script.statements import scoped_registry
from engine.script.ui import UiStatement
from engine.script.words import STATEMENT_WORDS, STATEMENT_WORDS_F02
from tests.script import message_cases
from tests.script.helpers import F32_TEMPLATE_DIR, template_f32
from tests.tools.f45_games import check as run_check

IMAGES = ("images/bg/room.png",)
STYLES = frozenset(("ashes", "calm"))


@pytest.fixture
def ui_word():
    with scoped_registry():
        ui.register_words()
        yield


def _load(tmp_path, text: str):
    script = tmp_path / "script"
    script.mkdir(exist_ok=True)
    (script / "main.vns").write_text(text, encoding="utf-8")
    return load_story(GamePaths(tmp_path.resolve()), LoadOptions(style_names=STYLES))


def _node(tmp_path, S: str) -> UiStatement:
    result = _load(tmp_path, template_f32(S=S))
    assert result.errors == (), (S, [e.format() for e in result.errors])
    return result.program.labels["start"].block[2]


def test_ac_f32_05_ui_parses(ui_word, tmp_path):
    rows = [
        ("ui style ashes", dict(form="style", style="ashes")),
        ("ui style off", dict(form="style", style=None)),
        ('ui saving off "There\'s nothing left to keep."',
         dict(form="saving", on=False, reason="There's nothing left to keep.")),
        ("ui saving off", dict(form="saving", on=False, reason=None)),
        ('ui loading off "a {{b"', dict(form="loading", on=False, reason="a {b")),
        ("ui loading on", dict(form="loading", on=True, reason=None)),
        ('ui saving off "' + "é" * 200 + '"', dict(form="saving", reason="é" * 200)),
        ("ui delete saves", dict(form="delete")),
    ]
    for S, fields in rows:
        node = _node(tmp_path, S)
        assert type(node) is UiStatement, S
        assert {k: getattr(node, k) for k in fields} == fields, S
        assert node.identity_key() == ("ui", node.form)
    assert UiStatement not in CHECKPOINT_TYPES and UiStatement not in VOICE_TRANSPARENT
    assert ui.reason_ok("é" * 200) and not ui.reason_ok("") and not ui.reason_ok("a" * 201)

    # The 41st reserved word (07 I-7: membership and count, not order); F14's older-saves rule.
    assert "ui" in STATEMENT_WORDS - STATEMENT_WORDS_F02 and len(STATEMENT_WORDS) == 40
    assert reserved_since_save("ui") and reserved_since_save("UI")
    reserved = _load(tmp_path, template_f32(T="default ui = 1"))
    assert [e.code for e in reserved.errors] == ["E60"]

    # The words after ui stay free as names; a ui line in a choice block loads.
    choice = 'menu:⏎        "Go":⏎            ui style calm'
    text = template_f32(S='$ style += 1⏎$ delete = "x"⏎' + choice,
                        T="default style = 1⏎default saves = 0")
    result = _load(tmp_path, text)
    assert result.errors == (), [e.format() for e in result.errors]
    # The run leaves the ui line out (a headless run of it is F32 s3's golden).
    result = _load(tmp_path, template_f32(S='$ style += 1⏎$ delete = "x"',
                                          T="default style = 1⏎default saves = 0"))
    commands = run_headless(result.program, seed=42, image_files=IMAGES)
    assert not any(type(c) is StoryFailed for c in commands)
    assert sum(type(c) is Say for c in commands) == 3
    assert result.program.style_names == STYLES                 # for the restore's W205 (s3)


def test_ac_f32_06_vn_check_and_the_warning_rows(ui_word, tmp_path):
    game = tmp_path / "game"
    shutil.copytree(F32_TEMPLATE_DIR, game)
    (game / "script" / "main.vns").write_text(template_f32(S="ui style ashs"), "utf-8")
    problems = run_check(game).problems
    assert [(p.code, p.line) for p in problems if p.severity == "error"] == [("E320", 5)]
    assert format_message("E320", ("ashs", "ashes")) in problems[0].text

    args = {"W204": ("text",), "W205": ("ashes",), "W206": ("ashes",),
            "W207": ("style.ashes.theme.textbox", "frame_image", "gui/x.png", "missing")}
    rows = {c.code: c for c in message_cases.load_cases() if c.code in args}
    assert set(rows) == set(args)
    for code, row in rows.items():
        assert format_message(code, args[code]) == row.expect["exact"], code
