"""F64 round 1: the story map's reach reads item counts like variables
(``items.count("coin")`` starts at 0, ``unlock|lock item`` change it)."""

import textwrap

from engine.core.paths import GamePaths
from engine.script.loader import load_story
from engine.script.reach import analyze, count_key
from engine.tools.lint import starts_of

TOP = 'lock item coin "Coins" count 0 to 50 money\nlock item key "Key"\n'


def _program(tmp_path, text):
    script = tmp_path / "script"
    script.mkdir(parents=True, exist_ok=True)
    (script / "main.vns").write_text(TOP + textwrap.dedent(text), encoding="utf-8")
    result = load_story(GamePaths(tmp_path.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def test_counts_are_watched_and_set(tmp_path):
    program = _program(tmp_path, """\
        label start:
            unlock item coin 30
            lock item coin 5
            if items.count("coin") >= 30:
                jump rich
            if codex.count("coin") >= 20:
                jump comfy
            return

        label rich:
            return

        label comfy:
            return
        """)
    found = analyze(program, starts_of(program))
    rich, comfy = found["rich"], found["comfy"]
    assert rich.blocked is not None
    assert 'items.count("coin") is always 25 there' in rich.blocked
    assert comfy.blocked is None and comfy.ways[0].possible
    assert [s.text for s in rich.setters] == ["unlock item coin 30", "lock item coin 5"]
    assert {s.var for s in rich.setters} == {count_key("coin")}


def test_counts_stop_at_the_most_and_at_none(tmp_path):
    program = _program(tmp_path, """\
        label start:
            unlock item coin 80
            lock item key
            if items.count("coin") > 50 or codex.count("key") > 0:
                jump never
            return

        label never:
            return
        """)
    assert analyze(program, starts_of(program))["never"].blocked is not None


def test_a_new_game_holds_none(tmp_path):
    program = _program(tmp_path, """\
        label start:
            if items.count("coin") > 3:
                jump later
            return

        label later:
            return
        """)
    assert analyze(program, starts_of(program))["later"].blocked is not None
