"""F18 step 1 — the ``chapter`` statement at load (``script/chapter.py``, ``checks.py``):
AC-F18-01's node fields and E224. Its message rows (E220–E223, the ``with`` codes, the clean
forms, a label and a chapter sharing a name) are in ``tests/fixtures/F02/messages/cases.toml``;
the launch codes of ``with`` (E190, E191) are ``tests/runtime/test_chapters.py``'s."""

from engine.core.paths import GamePaths
from engine.script.loader import load_story
from engine.script.nodes import Chapter
from tests.script.helpers import first_say, parse_text, template

AC01 = [
    ('chapter festival "Chapter 2" "The Lantern Festival"',
     ("festival", "Chapter 2", "The Lantern Festival", None, None)),
    ('chapter prologue "Prologue"', ("prologue", None, "Prologue", None, None)),
    ('chapter river "Chapter 3" "By the River" 5 with lantern',
     ("river", "Chapter 3", "By the River", 5.0, ("lantern", None, None))),
    ('chapter epilogue "Epilogue" 0', ("epilogue", None, "Epilogue", 0.0, None)),
    ('chapter a "T" with dissolve 1.5', ("a", None, "T", None, ("dissolve", 1.5, None))),
    ('chapter a "T" with fade 2 white', ("a", None, "T", None, ("fade", 2.0, "#FFFFFF"))),
    ('chapter a "{{b} \\"x\\""', ("a", None, '{b} "x"', None, None)),
]


def test_ac01_node_fields_and_e224(tmp_path):
    for row, expected in AC01:
        parsed = parse_text(template(S=row))
        assert parsed.errors == [], row
        node = first_say(parsed)
        assert type(node) is Chapter and node.identity_key() == ("chapter", expected[0])
        clause = node.with_clause
        shown = None if clause is None else (clause.name, clause.seconds, clause.color)
        assert (node.name, node.heading, node.title, node.seconds, shown) == expected, row
    for count in (1000, 1001):
        root = tmp_path / str(count)
        lines = "".join(f'    chapter c{i} "T"\n' for i in range(count))
        (root / "script").mkdir(parents=True)
        (root / "script" / "main.vns").write_text(f"label start:\n{lines}", encoding="utf-8")
        result = load_story(GamePaths(root.resolve()))
        expected = [] if count == 1000 else [
            ("E224", None, "this story has 1,001 chapters; the engine allows 1,000.")]
        assert [(e.code, e.file, e.message) for e in result.errors] == expected
