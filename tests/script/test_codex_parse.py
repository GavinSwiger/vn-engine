"""F21 step 1 — ``lock tip|item`` and ``lock|unlock tip|item`` at parse (``script/codex.py``):
AC-F21-01's nodes. The message rows of AC-F21-02 and 03 (E250, E252, E244) are in
``tests/fixtures/F02/messages/cases.toml``.

F21's rows are registered at import since F21 step 2 (07 I-4); the ``words`` fixture's
``register_words()`` calls inside ``scoped_registry()`` now change nothing.
"""

import pytest

from engine.core.paths import GamePaths
from engine.runtime.commands import StoryEnded
from engine.runtime.headless import run_headless
from engine.script import codex, routes
from engine.script.codex import CodexEntryDecl, CodexLock
from engine.script.loader import LoadOptions, load_story
from engine.script.routes import LOCK_TARGETS
from engine.script.statements import scoped_registry
from engine.script.texttags import Span
from tests.script.helpers import expand, first_say, parse_text, template_c


@pytest.fixture
def words():
    with scoped_registry():
        routes.register_words()
        codex.register_words()
        yield


def _load(root, text: str, *, dev: bool = False):
    script = root / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_text(text, encoding="utf-8")
    return load_story(GamePaths(root.resolve()), LoadOptions(dev=dev))


def _decl(T: str, name: str) -> CodexEntryDecl:
    parsed = parse_text(template_c(T=T))
    assert parsed.errors == [], (T, parsed.messages)
    found = [n for n in parsed.nodes if isinstance(n, CodexEntryDecl) and n.name == name]
    assert len(found) == 1, T
    return found[0]


TOP = [
    ('lock tip moon "The Moon"', "moon", ("tip", "The Moon", None, None, 0)),
    ('lock item red2 "Red Lantern" in "Things" image items red_lantern', "red2",
     ("item", "Red Lantern", "Things", "items red_lantern", 0)),
    ('lock item r5 "R" image a b c d e', "r5", ("item", "R", None, "a b c d e", 0)),
    ('lock item k "A {{b} key" in "{{x}"', "k", ("item", "A {b} key", "{x}", None, 0)),
    ('lock tip t "終わり 🏮" in "伝説"', "t", ("tip", "終わり 🏮", "伝説", None, 0)),
    ('lock tip t "نهاية الطريق"', "t", ("tip", "نهاية الطريق", None, None, 0)),
    (f'lock tip {"t" * 64} "{"紙" * 60}" in "{"a" * 24}":' + '⏎[4]"p"' * 32, "t" * 64,
     ("tip", "紙" * 60, "a" * 24, None, 32)),
    (f'lock tip big "B":⏎[4]"{"紙" * 2000}"', "big", ("tip", "B", None, None, 1)),
    ('lock tip w "W":⏎[4]"Lanterns are folded⏎[8]from washi paper."', "w",
     ("tip", "W", None, None, 1)),
]


def test_ac01_declarations_and_lines_parse(words, tmp_path):
    # Template C's own lanterns: two paragraphs, sid codex:lanterns once loaded.
    story = _load(tmp_path / "c", template_c())
    assert story.errors == (), [e.format() for e in story.errors]
    lanterns = story.program.codex[0]
    assert (lanterns.name, lanterns.kind, lanterns.title, lanterns.category.text,
            lanterns.image, len(lanterns.paragraphs), lanterns.sid) == (
        "lanterns", "tip", "Paper Lanterns", "Festival", None, 2, "codex:lanterns")
    for T, name, expected in TOP:
        node = _decl(T, name)
        assert (node.kind, node.title, node.category, node.image,
                len(node.paragraphs)) == expected, T
    # 6 image words: F04's show-name code; the paragraph's text is one, joined.
    assert parse_text(template_c(T='lock item r6 "R" image a b c d e f')).codes == ["E126"]
    assert "Lanterns are folded" in _decl(
        'lock tip w "W":⏎[4]"Lanterns are folded⏎[8]from washi paper."', "w"
    ).paragraphs[0].pieces[0].text
    # Tags: Spans only, italic, bold, and color, size and speed 1.0.
    body = _decl('lock tip p "P":⏎[4]"One {i}wish{/i}, {b}one{/b}, {color=#a02860}red{/color}."',
                 "p").paragraphs[0]
    assert all(type(piece) is Span for piece in body.pieces) and not body.auto_next
    styles = {piece.text: piece.style for piece in body.pieces}
    assert styles["wish"].italic and styles["one"].bold and styles["red"].color == "#a02860"
    assert all(s.size == 1.0 and s.speed == 1.0 for s in styles.values())
    # In a label: CodexLock and its identity.
    for S, expected in (("unlock tip lanterns", (True, "tip", "lanterns")),
                        ("lock item brass_key", (False, "item", "brass_key"))):
        node = first_say(parse_text(template_c(S=S)))
        assert type(node) is CodexLock and (node.unlock, node.kind, node.name) == expected
        assert node.identity_key() == ("unlock" if expected[0] else "lock",) + expected[1:]
    # tip and item stay usable as names, and the story runs.
    names = _load(tmp_path / "names", expand(
        'default item = None⏎label start:⏎[4]$ tip = item⏎[4]if tip == item:⏎[8]"A."⏎[4]"B."')
        + "\n")
    assert names.errors == ()
    assert isinstance(run_headless(names.program, seed=42)[-1], StoryEnded)
    # A voice above unlock tip reaches the next line (VOICE_TRANSPARENT): no W20.
    voiced = _load(tmp_path / "voice", template_c(S='voice "v.ogg"⏎[4]unlock tip lanterns'),
                   dev=True)
    assert voiced.errors == () and "W20" not in {w.code for w in voiced.warnings}


def test_i4_rows_are_registered_at_import():
    """07 I-4, since step 2: importing ``engine.script`` registers F21's rows once, after F19's;
    ``register_words()`` again (the ``words`` fixture) changes nothing, and
    ``scoped_registry()`` keeps them."""
    assert list(LOCK_TARGETS) == ["route", "ending", "tip", "item"]
    rows = dict(LOCK_TARGETS)
    with scoped_registry():
        routes.register_words()
        codex.register_words()
        assert LOCK_TARGETS == rows
    assert LOCK_TARGETS == rows and LOCK_TARGETS["tip"] is codex.TIP_TARGET
