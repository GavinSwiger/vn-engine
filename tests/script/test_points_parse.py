"""F22 step 1 — the ``points`` statement at load (``script/points.py``, ``checks.py``,
``bindings.py``): AC-F22-01's node fields and AC-F22-02's whole-game rows that the message
cases can't hold (two files, E235, ``Program.meters``, a menu condition, one error per piece).
The message rows (E230–E234, E62, the clean forms) are in
``tests/fixtures/F02/messages/cases.toml``."""

from engine.core.paths import GamePaths
from engine.script.bindings import check_all
from engine.script.identity import declaration_sid
from engine.script.loader import load_story
from engine.script.points import POINTS_LIMIT, MeterSpec, PointsChange, PointsDecl
from tests.script.helpers import first_say, parse_text, template

BIG = POINTS_LIMIT


def _load(root, files: dict[str, str]):
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (script / name).write_text(text, encoding="utf-8")
    return load_story(GamePaths(root.resolve()))


def _codes(text: str) -> list[str]:
    parsed = parse_text(text)
    assert parsed.errors == []
    return [e.code for e in check_all(parsed.nodes, parsed.ctx.collected.define_defs).errors]


def test_ac01_node_fields():
    # declarations
    rows = [("points a", (("a",), -BIG, BIG, 0, False)),
            ("points a b c", (("a", "b", "c"), -BIG, BIG, 0, False)),
            ("points a -5 to 5 start -2", (("a",), -5, 5, -2, True)),
            ("points a 1 to 9", (("a",), 1, 9, 1, True)),
            ("points a -9 to -1", (("a",), -9, -1, -9, True)),
            ("points a start 7", (("a",), -BIG, BIG, 7, False))]
    for row, expected in rows:
        parsed = parse_text(template(T=row))
        assert parsed.errors == [], row
        node = parsed.nodes[-1]
        assert type(node) is PointsDecl, row
        assert (node.names, node.low, node.high, node.start, node.ranged) == expected, row
    assert node.specs() == (MeterSpec("a", -BIG, BIG, 7, False),)
    assert declaration_sid(parsed.nodes[-1]) == "points:a"
    # changes and their identity
    rows = [("points a += 2", ("a", "+=", "2")), ("points a -= x * 2", ("a", "-=", "x * 2")),
            ("points a = 0", ("a", "=", "0")), ("points a+=1  # note", ("a", "+=", "1"))]
    for row, (name, op, amount) in rows:
        parsed = parse_text(template(S=row))
        assert parsed.errors == [], row
        node = first_say(parsed)
        assert type(node) is PointsChange and (node.name, node.op) == (name, op), row
        assert node.amount.mode == "eval" and node.identity_key() == ("points", name, op, amount)
    # names follow section 6
    assert parse_text(template(T="points menu")).codes == ["E60"]
    assert "can't be a meter name" in parse_text(template(T="points menu")).messages[0]
    assert parse_text(template(T="points _a")).codes == ["E63"]
    assert parse_text(template(T="points a:")).codes == ["E110"]


def test_ac02_whole_game_checks(tmp_path):
    # A declaration at depth 0 is a top-level statement: it ends a run of story lines, so a
    # story line after it gives E40 again (one per run).
    assert parse_text('label start:\n    return\n"A"\npoints a\n"B"\n').codes == ["E40", "E40"]
    # two files: Program.meters order; a meter beside a Character, label and default is fine
    result = _load(tmp_path / "two", {
        "main.vns": 'include "b.vns"\npoints sayori natsuki\npoints affection 0 to 100 '
                    'start 50\ndefine sayori = Character("Sayori")\ndefault sayori_x = 0\n'
                    'label start:\n    points sayori += 1\n    menu:\n'
                    '        "A" if points.yuri > 0:\n            return\n'
                    '    sayori "Hi."\n',
        "b.vns": "points yuri\nlabel sayori:\n    return\n"})
    assert result.errors == ()
    assert [m.name for m in result.program.meters] == ["sayori", "natsuki", "affection", "yuri"]
    assert result.program.meters[2] == MeterSpec("affection", 0, 100, 50, True)
    # E231 across files; E233 in a menu condition
    result = _load(tmp_path / "e231", {
        "main.vns": 'include "b.vns"\npoints sayori\nlabel start:\n    menu:\n'
                    '        "A" if points.sayory:\n            return\n',
        "b.vns": "points natsuki sayori\n"})
    assert [(e.code, e.file, e.line) for e in result.errors] == [
        ("E233", "script/main.vns", 5), ("E231", "script/b.vns", 1)]
    assert "here and at script/main.vns, line 2" in result.errors[1].message
    # E235 at 201 meters, none at 200
    for count, codes in ((200, []), (201, ["E235"])):
        names = " ".join(f"m{i}" for i in range(count))
        result = _load(tmp_path / str(count),
                       {"main.vns": f"points {names}\nlabel start:\n    return\n"})
        assert [e.code for e in result.errors] == codes
    assert result.errors[0].message == "this story has 201 meters; the engine allows 200."
    # one error per piece, in order: E87 before E234; E234 before E233; highest() isn't a read
    rows = [("$ trust = points.yuri = 1", "E87"), ("$ x = points.sayory; points.yuri = 1", "E234"),
            ("$ x = points.highest() + points.sayory", "E233")]
    for row, code in rows:
        assert _codes(f"points yuri\ndefine trust = 0\nlabel start:\n    {row}\n") == [code], row
    # no follow-on E233 for a meter whose line has a range error
    result = _load(tmp_path / "bad", {"main.vns": "points a 10 to 0\nlabel start:\n"
                                                  "    points a += 1\n    $ x = points.a\n"})
    assert [e.code for e in result.errors] == ["E232"]
