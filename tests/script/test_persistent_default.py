"""AC-F12-01: ``default persistent.<name>`` and the ``Program`` (F12 ``06-acceptance.md``
§1.1; ``04-technical.md`` §6), plus the root-generic ``<root>.<attr>`` walk of
``bindings.py`` that F22 will extend with ``points`` (F22 ``07`` question 2).

Template P (06 §0.4): S is line 7, T is line 10. E184's messages are rows of
``tests/fixtures/F02/messages/cases.toml`` (``test_messages.py`` runs them).
"""

import ast

import pytest

from engine.core.paths import GamePaths
from engine.script import load_story
from engine.script import bindings
from engine.script.nodes import Default, PersistentDefault, PyCode
from tests.script.helpers import template_p


def load(root, *, S=None, T=None):
    script = root / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_text(template_p(S=S, T=T), encoding="utf-8")
    return load_story(GamePaths(root.resolve()))


def program_of(root, **edit):
    result = load(root, **edit)
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def test_ac01_persistent_defaults_in_the_program(tmp_path):
    program = program_of(tmp_path)
    nodes = program.persistent_defaults
    assert [type(n) for n in nodes] == [PersistentDefault, PersistentDefault]
    assert [n.name for n in nodes] == ["festivals", "hana_remembers"]
    assert [n.sid for n in nodes] == ["default:persistent.festivals",
                                      "default:persistent.hana_remembers"]
    assert [d.name for d in program.defaults] == ["trust"]
    assert all(type(d) is Default for d in program.defaults)
    assert program.persistent_default_names == {"festivals", "hana_remembers"}
    assert program.get("default:persistent.festivals") is None    # a declaration


@pytest.mark.parametrize("S, T, reads, writes", [
    ('if persistent.a:⏎[8]"A."', None, {"a": 7}, set()),
    ("$ persistent.j.append(1)", None, {"j": 7}, set()),
    ("$ persistent.b += 1", None, {}, {"b"}),
    ("$ del persistent.c", None, {}, {"c"}),
    ('$ setattr(persistent, "d", 1)', None, {}, {"d"}),
    ('$ delattr(persistent, "e")', None, {}, {"e"}),
    (None, "define greet = lambda: persistent.g", {"g": 10}, set()),
    (None, "default persistent.h = persistent.festivals + 1", {"festivals": 10}, set()),
    ('menu:⏎[8]"Go" if persistent.i:⏎[12]"A."', None, {"i": 8}, set()),
    ("$ f = lambda: persistent.n", None, {"n": 7}, set()),
    ("$ persistent._clear()", None, {}, set()),                 # engine names: not uses
    ("$ x = [persistent.q for _ in range(2)]", None, {"q": 7}, set()),
], ids=["if", "append", "augmented", "del", "setattr", "delattr", "define-lambda",
        "persistent-default", "choice", "dollar-lambda", "engine", "comprehension"])
def test_ac01_bindings_collect_reads_and_writes(tmp_path, S, T, reads, writes):
    program = program_of(tmp_path, S=S, T=T)
    assert dict(program.persistent_reads) == {n: ("script/main.vns", line)
                                               for n, line in reads.items()}
    assert program.persistent_writes == writes
    if T is not None and T.startswith("default persistent.h"):
        assert "h" in program.persistent_default_names


def test_ac01_first_use_wins(tmp_path):
    program = program_of(tmp_path, S="$ x = persistent.a⏎[4]$ y = persistent.a",
                         T="define f = lambda: persistent.a")
    assert dict(program.persistent_reads) == {"a": ("script/main.vns", 7)}


def test_ac01_other_defaults_keep_their_codes(tmp_path):
    result = load(tmp_path / "a", T="default persistent = 1")
    assert [e.code for e in result.errors] == ["E62"]
    result = load(tmp_path / "b", T="default seen.intro = False")
    assert [e.code for e in result.errors] == ["E49"]
    assert result.errors[0].message == ('default sets one plain name, and "seen.intro" has a '
                                        "dot. Use a name without dots.")


@pytest.mark.parametrize("T, code", [
    ("default persistent.for = 1", "E61"),
    ("default persistent.label = 1", None),            # statement words are fine here
    ("default persistent.dice = 1", None),             # so are the story's engine names
    ("default persistent.x", "E49"),
    ("label later:⏎[4]default persistent.x = 1", "E46b"),
], ids=["keyword", "statement-word", "engine-name", "no-value", "in-a-block"])
def test_ac01_persistent_default_names(tmp_path, T, code):
    result = load(tmp_path, T=T)
    assert [e.code for e in result.errors] == ([code] if code else [])


# --- The walk over any root (F22 07 question 2) ---------------------------------------------

def uses(source: str, roots=("persistent", "points"), mode="exec"):
    tree = ast.parse(source, mode=mode)
    return [(u.root, u.name, u.kind) for u in sorted(bindings.scan(tree, roots).uses)]


def test_scan_collects_every_root_given():
    assert uses("points.trust += 1\nx = persistent.a\nsetattr(points, 'b', 2)") == [
        ("points", "trust", "write"), ("persistent", "a", "read"), ("points", "b", "write")]
    assert uses("x = persistent.a", roots=()) == []
    assert uses("other.a = 1\ngetattr(persistent, 'z')\npersistent.__class__") == []


def test_mentions_looks_into_nested_code():
    piece = PyCode(source="lambda: persistent.x", line=1, column=1, mode="eval",
                   code=compile("lambda: persistent.x", "<script/main.vns>", "eval"))
    assert bindings.mentions(piece, ("persistent",))
    assert not bindings.mentions(piece, ("points",))
