"""F19 step 1 — ``ending``, ``lock``, ``unlock`` at parse (``script/routes.py``): AC-F19-01's
and AC-F19-02's nodes. Their message rows (E240, E242–E244) are in
``tests/fixtures/F02/messages/cases.toml``.

Since F19 step 3 the words are registered at import (07 I-5); the ``words`` fixture, from
step 1, calls ``register_words()`` again, which changes nothing.
"""

import pytest

from engine.core.paths import GamePaths
from engine.runtime.commands import StoryEnded
from engine.runtime.headless import run_headless
from engine.script.loader import load_story
from engine.script.routes import LOCK_TARGETS, Ending, Lock, RouteDecl, register_words
from engine.script.statements import get_spec, scoped_registry
from tests.script.helpers import first_say, parse_text, template_e


@pytest.fixture
def words():
    with scoped_registry():
        register_words()
        yield


def _load(tmp_path, text: str):
    script = tmp_path / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_text(text, encoding="utf-8")
    return load_story(GamePaths(tmp_path.resolve()))


AC01 = [
    ('ending sad "Paper Ashes"', ("sad", None, "Paper Ashes", None, None)),
    ('ending sad "Sad End" "Paper Ashes"', ("sad", "Sad End", "Paper Ashes", None, None)),
    ('ending sad "Sad End" "Paper Ashes" 5 with dissolve 1.5',
     ("sad", "Sad End", "Paper Ashes", 5.0, ("dissolve", 1.5))),
    ('ending quiet "Quiet" 0', ("quiet", None, "Quiet", 0.0, None)),
    ('ending quiet "Quiet" 30', ("quiet", None, "Quiet", 30.0, None)),
    ('ending quiet "Quiet" 0.5', ("quiet", None, "Quiet", 0.5, None)),
    ('ending sad "A {{b}"', ("sad", None, "A {b}", None, None)),
    ('ending sad "終わり" "紙の灰 🏮"', ("sad", "終わり", "紙の灰 🏮", None, None)),
    ('ending sad "نهاية الطريق"', ("sad", None, "نهاية الطريق", None, None)),
    (f'ending {"e" * 64} "{"a" * 60}" "{"紙" * 120}"', ("e" * 64, "a" * 60, "紙" * 120, None, None)),
]


def test_ac01_ending_parses(words, tmp_path):
    for row, expected in AC01:
        parsed = parse_text(template_e(S=row))
        assert parsed.errors == [], (row, parsed.messages)
        node = first_say(parsed)
        assert type(node) is Ending, row
        clause = node.with_clause
        shown = None if clause is None else (clause.name, clause.seconds)
        assert (node.name, node.heading, node.title, node.seconds, shown) == expected, row
    # The identity is the name only: texts, seconds, and with don't change it.
    keys = {first_say(parse_text(template_e(S=row))).identity_key() for row in (
        'ending sad "Paper Ashes"', 'ending sad "Other" "Title" 7 with fade 2')}
    assert keys == {("ending", "sad")}
    # A label, a chapter, and an ending named sad load together.
    result = _load(tmp_path / "names", template_e(T='label sad:⏎[4]chapter sad "Sad"⏎[4]return'))
    assert result.errors == ()
    assert [e.name for e in result.program.endings] == ["sad", "good", "true"]
    # voice above an ending is W20; above lock/unlock it reaches the next line (VOICE_TRANSPARENT).
    voiced = _load(tmp_path / "voice", template_e(S='voice "v.ogg"⏎[4]ending early "E"'))
    assert [w.code for w in voiced.warnings if w.code == "W20"] == ["W20"]
    for line in ("unlock route promise", "lock route festival_night", "lock ending good"):
        clear = _load(tmp_path / line.replace(" ", "_"), template_e(S=f'voice "v.ogg"⏎[4]{line}'))
        assert clear.errors == () and clear.warnings == (), line


def test_ac02_routes_lock_unlock_parse(words, tmp_path):
    result = _load(tmp_path / "decl", template_e())
    assert result.errors == ()
    promise, festival = result.program.routes
    assert (type(promise), promise.name, promise.title, promise.until, promise.sid) == (
        RouteDecl, "promise", "Hana's Promise", ("sad", "good"), "route:promise")
    assert (festival.name, festival.until, festival.sid) == (
        "festival_night", (), "route:festival_night")
    for written in ("sad,good", "sad ,good", "sad , good"):
        nodes = parse_text(f'lock route promise "P" until {written}\n').nodes
        assert [n.until for n in nodes] == [("sad", "good")], written
    many = ", ".join(f"e{i}" for i in range(1, 33))
    parsed = parse_text(f'lock route promise "P" until {many}\n')
    assert parsed.errors == [] and len(parsed.nodes[0].until) == 32
    for row, expected in [
            ("unlock route festival_night", (True, "route", "festival_night")),
            ("lock route festival_night", (False, "route", "festival_night")),
            ("lock ending good", (False, "ending", "good"))]:
        parsed = parse_text(template_e(S=row))
        assert parsed.errors == [], row
        node = first_say(parsed)
        assert type(node) is Lock and (node.unlock, node.kind, node.name) == expected
        assert node.identity_key() == ("unlock" if expected[0] else "lock",) + expected[1:]
    # route and until stay usable as names, and the story runs.
    story = _load(tmp_path / "names", 'default route = 1\nlabel start:\n    $ until = route + 1\n'
                  '    if route > until:\n        "A."\n    "B."\n')
    assert story.errors == ()
    commands = run_headless(story.program, seed=42)
    assert isinstance(commands[-1], StoryEnded)


def test_i5_words_are_registered_at_import():
    """07 I-5, since step 3: importing ``engine.script`` registers the words and F19's
    ``LOCK_TARGETS`` rows once; ``register_words()`` again (the step-1 tests' ``words``
    fixture) changes nothing, and ``scoped_registry()`` keeps them."""
    specs = {w: get_spec(w) for w in ("ending", "lock", "unlock")}
    assert all(spec is not None and spec.placement == "either" for spec in specs.values())
    rows = ["route", "ending", "tip", "item"]           # F21's rows since F21 step 2 (07 I-4)
    assert list(LOCK_TARGETS) == rows
    with scoped_registry():
        register_words()
        assert list(LOCK_TARGETS) == rows
        assert {w: get_spec(w) for w in specs} == specs
    assert list(LOCK_TARGETS) == rows and get_spec("ending") is specs["ending"]
    parsed = parse_text(template_e(S="unlock route promise"))
    assert parsed.errors == []
