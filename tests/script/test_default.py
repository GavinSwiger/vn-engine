"""F03 step 4: the ``default`` statement and the ``Program`` additions (F03
``04-technical.md`` §3.2 except ``bindings.py``, §6.1, §6.3; SR-F03-01–03, SR-F03-08).

AC-F03-17's message rows live in ``tests/fixtures/F02/messages/cases.toml`` (``feature =
"F03"``; one catalogue) and also feed the golden file; here they run once more as the AC,
next to the edge cases: where E46b, E47b, E47c, and the default order are raised, what an
erroneous line still registers, ``StatementSpec.misplaced``, ``Program.defaults``,
``define_names``, ``default_names``, and ``speakers``, and the start-option names (E26c).
"""

from types import MappingProxyType

import pytest

from engine.script.checks import CheckInput, iter_checks
from engine.script.diagnostics import DiagnosticSink
from engine.script.lexer import TAIL_AFTER_EQUALS, TAIL_SCRIPT
from engine.script.loader import LoadResult, load_story
from engine.script.nodes import Default, PyCode, Say, ScriptFile
from engine.script.program import LoadStats, Program
from engine.script.statements import (
    StatementSpec,
    get_spec,
    register,
    registered_words,
    scoped_registry,
)
from tests.script import message_cases
from tests.script.helpers import parse_text, template_r

MAIN = "script/main.vns"


def load(game, files: dict[str, str]) -> LoadResult:
    return load_story(game(files))


def report(result: LoadResult) -> list[tuple[str, str, int | None, str]]:
    return [(e.code, e.file, e.line, e.message) for e in result.errors]


def clean(result: LoadResult) -> Program:
    assert result.program is not None, [e.format() for e in result.errors]
    assert result.errors == () and result.warnings == ()
    return result.program


def run(code: PyCode, names: dict | None = None) -> object:
    """Evaluate a value the way the runtime will (here with no built-ins)."""
    return eval(code.code, {"__builtins__": {}, **(names or {})})  # noqa: S307


# --- AC-F03-17 ------------------------------------------------------------------------------

AC17 = [case for case in message_cases.load_cases() if case.ac == "AC-F03-17"]


def test_ac17_has_every_row():
    # E46b, E47b, E47c ×2, E48, E48b, E49 ×2, E60, E62 ×3, E63, and the clean load.
    assert [c.code for c in AC17] == ["E46b", "E47b", "E47c", "E47c", "E48", "E48b", "E49",
                                      "E49", "E60", "E62", "E62", "E62", "E63", "-"]
    assert all(c.feature == "F03" and c.time == "load" and c.needs == "load" for c in AC17)


@pytest.mark.parametrize("case", AC17, ids=lambda case: case.id)
def test_ac17_default_load_errors(case):
    message_cases.check_case(case, message_cases.run_case(case))


def test_ac17_multi_line_default_loads_clean_and_gives_its_value(game):
    program = clean(load(game, {"main.vns": template_r(T="default deck = [1,⏎[4]2]")}))
    deck = program.defaults[-1]
    assert (deck.name, deck.line, deck.end_line) == ("deck", 11, 12)
    assert run(deck.value) == [1, 2]


# --- The statement ----------------------------------------------------------------------------

def test_default_is_registered_as_a_top_level_statement_with_e46b():
    spec = get_spec("default")
    assert spec is not None and "default" in registered_words()
    assert (spec.placement, spec.takes_block, spec.tail, spec.misplaced) == (
        "top", False, TAIL_AFTER_EQUALS, "E46b")


def test_f02_top_level_statements_carry_their_misplaced_codes():
    codes = {word: get_spec(word).misplaced for word in ("label", "define", "include", "jump",
                                                          "if", "return")}
    assert codes == {"label": "E24", "define": "E46", "include": "E90", "jump": None,
                     "if": None, "return": None}


def test_misplaced_is_a_keyword_field_after_parse_and_required_for_top_statements():
    def parse(raw, ctx):
        return None

    spec = StatementSpec(word="nvl", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                         parse=parse)
    assert spec.misplaced is None
    with scoped_registry():
        with pytest.raises(ValueError, match="misplaced"):
            register(StatementSpec(word="cg", placement="top", takes_block=False,
                                   tail=TAIL_SCRIPT, parse=parse))
        register(StatementSpec(word="cg", placement="top", takes_block=False,
                               tail=TAIL_SCRIPT, parse=parse, misplaced="E46"))
        assert get_spec("cg").misplaced == "E46"
    assert get_spec("cg") is None


def test_the_node_has_the_define_shape():
    parsed = parse_text(template_r(T="default bonus = lambda: trust * len(fortunes)  # x"))
    assert parsed.errors == []
    node = parsed.nodes[-1]
    assert isinstance(node, Default)
    assert (node.name, node.line, node.column) == ("bonus", 11, 1)
    assert node.value.mode == "eval" and node.value.source.startswith("lambda: trust")
    assert node.value.names == {"trust", "len", "fortunes"}     # names inside lambda count
    assert parsed.ctx.collected.default_defs == {
        "trust": [(node.file, 4)], "hana_name": [(node.file, 5)], "bonus": [(node.file, 11)]}


# E46b: the line's own name and value, on one line, without its comment (SR-F03-01).
@pytest.mark.parametrize("edit,where,shown", [
    ("default trust = 0", 8, "trust = 0"),
    ("default deck = [1,⏎[8]2]  # two lines", 8, "deck = [1, 2]"),
    ("default trust = 0  # a comment", 8, "trust = 0"),
    ("if True:⏎[8]default met = False", 9, "met = False"),
    ("default persistent.seen = True", 8, "persistent.seen = True"),
    ("default", 8, "name = value"),
    ("default luck", 8, "name = value"),
    ("default luck =", 8, "name = value"),
])
def test_e46b_shows_the_lines_own_assignment(game, edit, where, shown):
    result = load(game, {"main.vns": template_r(S=edit)})
    assert report(result) == [(
        "E46b", MAIN, where,
        "default sets a variable's starting value before the story begins, so it must be at "
        f"the top level. To change the value during the story, use $ {shown}.")]


@pytest.mark.parametrize("edit", ["default fortunes = 0", "default trust = 1",
                                  "default fresh = 1"])
def test_a_misplaced_default_declares_nothing(edit):
    # No E47b/E47c follow-on, and nothing for the whole-game checks.
    parsed = parse_text(template_r(S=edit))
    assert parsed.codes == ["E46b"]
    assert set(parsed.ctx.collected.default_defs) == {"trust", "hana_name"}
    assert not any(isinstance(n, Default) and n.line == 8 for n in parsed.nodes)


# Malformed lines and bad names at the top level (E49, E60–E64, E82), one error each.
@pytest.mark.parametrize("edit,code,column", [
    ("default x =", "E49", None),
    ("default = 1", "E49", None),
    ("default x y = 1", "E49", None),
    ("default x == 1", "E82", 12),
    ("default a.b.c = 1", "E49", None),
    ("default x = (1", "E82", 13),
    ("default x = 1:", "E82", 14),
    ("default class = 1", "E61", None),
    ("default 2x = 1", "E64", None),
    ("default Default = 1", "E60", None),
    ("default Character = 1", "E62", None),
    ("default narrator = 1", "E62", None),
    ("default module = 1", "E62", None),
    ("default __x = 1", "E63", None),
])
def test_bad_default_lines(game, edit, code, column):
    result = load(game, {"main.vns": template_r(T=edit)})
    assert [(e.code, e.line, e.column) for e in result.errors] == [(code, 11, column)]


@pytest.mark.parametrize("edit,registered", [
    ("default luck", True),                  # E49 with a valid name still registers it
    ("default luck = (1", True),             # E82 too (SR-F03-02, as SR-F02-60)
    ("default menu = 1", False),             # an invalid name never does
    ("default _seen = 1", False),
    ("default a.b = 1", False),
])
def test_an_erroneous_default_still_registers_a_valid_name(edit, registered):
    parsed = parse_text(template_r(T=edit))
    assert len(parsed.errors) == 1
    names = set(parsed.ctx.collected.default_defs) - {"trust", "hana_name"}
    assert names == ({edit.split()[1]} if registered else set())


def test_e49_uses_the_default_word_and_define_keeps_its_own():
    assert parse_text(template_r(T="define luck")).messages == [
        'script/main.vns, line 11: define needs a name, =, and a value, e.g. '
        'define hana = Character("Hana").']
    assert parse_text(template_r(T="define a.b = 1")).messages == [
        'script/main.vns, line 11: define sets one plain name, and "a.b" has a dot. Use a '
        "name without dots."]


# --- E47b and E47c ------------------------------------------------------------------------------

def test_e47b_once_per_name_at_the_second_place(game):
    result = load(game, {"main.vns": template_r(T='default trust = 1⏎include "b.vns"'),
                         "b.vns": "default trust = 2\ndefault luck = 1\ndefault luck = 2\n"})
    assert report(result) == [
        ("E47b", MAIN, 11, '"trust" already has a default in script/main.vns, line 4. '
                           "Remove one of them."),
        ("E47b", "script/b.vns", 3, '"luck" already has a default in script/b.vns, line 2. '
                                    "Remove one of them."),
    ]


@pytest.mark.parametrize("main_t,other,where,message", [
    # The default comes first (main.vns line 4); b.vns comes later in reading order even
    # though its line number is smaller.
    ('include "b.vns"', "define trust = 5", ("script/b.vns", 1),
     '"trust" has a default in script/main.vns, line 4, and is set by define here.'),
    ('include "b.vns"', "default fortunes = []", ("script/b.vns", 1),
     '"fortunes" is set by define in script/main.vns, line 3, and by default here.'),
    ('define hana_name = "Hana"⏎define hana_name = "H"', None, (MAIN, 11),
     '"hana_name" has a default in script/main.vns, line 5, and is set by define here.'),
])
def test_e47c_at_whichever_comes_second(game, main_t, other, where, message):
    files = {"main.vns": template_r(T=main_t)}
    if other is not None:
        files["b.vns"] = other + "\n"
    result = load(game, files)
    found = [e for e in result.errors if e.code == "E47c"]
    assert len(found) == 1
    assert (found[0].file, found[0].line) == where
    assert found[0].message == message + (
        " Use define for values that never change and default for values the story "
        "changes, and remove the other.")


# --- Default order (SR-F03-03) ----------------------------------------------------------------

@pytest.mark.parametrize("edit,order", [
    # A default comes after the defaults its value names; ties in reading order.
    ("default b = a + 1⏎default a = len(fortunes)⏎default c = 1",
     ["trust", "hana_name", "a", "b", "c"]),
    # Names inside lambda and comprehensions count.
    ("default f = lambda: g⏎default g = [k for k in h]⏎default h = []",
     ["trust", "hana_name", "h", "g", "f"]),
    # Defines are all set first, so they never order defaults; a default may use any define.
    ("default early = later_define⏎define later_define = trust_bonus⏎define trust_bonus = 2",
     ["trust", "hana_name", "early"]),
    ("default z = trust + hana_name.count('?')", ["trust", "hana_name", "z"]),
])
def test_default_order(game, edit, order):
    program = clean(load(game, {"main.vns": template_r(T=edit)}))
    assert [d.name for d in program.defaults] == order


def test_default_cycles_name_default(game):
    result = load(game, {"main.vns": template_r(
        T="default a = b⏎default b = c⏎default c = a⏎default s = [s]")})
    assert report(result) == [
        ("E48", MAIN, 11, "default a uses b, b uses c, and c uses a (script/main.vns, line 12, "
                          "and script/main.vns, line 13), so none of them can be set first. "
                          "Change one so it doesn't use the others."),
        ("E48b", MAIN, 14, "default s uses itself, so it can't be set. Write its value without "
                           "using s."),
    ]


def test_define_and_default_cycles_are_separate(game):
    # A define named like a default is E47c, not a cycle between the two kinds.
    result = load(game, {"main.vns": template_r(
        T="define d1 = d2⏎define d2 = d1⏎default x = y⏎default y = x")})
    assert [(e.code, e.message.split(" uses")[0]) for e in result.errors] == [
        ("E48", "define d1"), ("E48", "default x")]


def test_no_default_order_when_a_default_has_its_own_error(game):
    result = load(game, {"main.vns": template_r(T="default a = b⏎default b = a⏎default c = (1")})
    assert [e.code for e in result.errors] == ["E82"]


def test_a_long_default_cycle_gives_one_short_message(game):
    count = 2_000
    lines = "⏎".join(f"default d{i} = d{(i + 1) % count}" for i in range(count))
    result = load(game, {"main.vns": template_r(T=lines)})
    assert [e.code for e in result.errors] == ["E48"]
    message = result.errors[0].message
    assert len(message) <= 1000 and message.startswith("default d0 uses d1, d1 uses d2")


# --- Program ------------------------------------------------------------------------------------

def test_program_fields(game):
    program = clean(load(game, {
        "main.vns": template_r(T='default b = a⏎default a = 1⏎include "b.vns"'),
        "b.vns": 'label side:\n    daichi "Hi."\n    "Narration."\n    hana "Again."\n'
                 "    return\n"}))
    assert [d.name for d in program.defaults] == ["trust", "hana_name", "a", "b"]
    assert program.define_names == frozenset({"hana", "daichi", "fortunes"})
    assert program.default_names == frozenset({"trust", "hana_name", "a", "b"})
    assert isinstance(program.speakers, MappingProxyType)
    assert {name: (say.file.ref, say.line) for name, say in program.speakers.items()} == {
        "hana": (MAIN, 7), "daichi": ("script/b.vns", 2)}
    assert list(program.speakers) == ["hana", "daichi"]          # reading order
    assert all(isinstance(say, Say) and say.sid for say in program.speakers.values())


def test_defaults_are_declarations_not_positions(game):
    program = clean(load(game, {"main.vns": template_r()}))
    trust = program.defaults[0]
    assert trust.sid == "default:trust"
    assert program.get("default:trust") is None and program.get(trust.sid) is None
    assert all(not isinstance(stmt, Default) for stmt in program.iter_statements())


def test_program_built_directly_derives_its_f03_fields():
    file = ScriptFile(MAIN, "main.vns", 0)
    stats = LoadStats(files=1, labels=0, statements=0, words=0, seconds=0.0)
    empty = Program(files=(file,), labels={}, defines=(), stats=stats)
    assert empty.defaults == () and empty.define_names == frozenset()
    assert empty.default_names == frozenset() and dict(empty.speakers) == {}
    parsed = parse_text(template_r(T="default luck = 3"))
    defaults = [n for n in parsed.nodes if isinstance(n, Default)]
    program = Program(files=(file,), labels=parsed.labels, defines=(), stats=stats,
                      defaults=defaults)
    assert type(program.defaults) is tuple and program.default_names == {
        "trust", "hana_name", "luck"}
    assert list(program.speakers) == ["hana"]
    with pytest.raises(TypeError):
        Program(files=(), labels={}, defines=(), stats=stats,  # type: ignore[call-arg]
                define_names=frozenset({"x"}))


# --- Start options (E26c, F44 C2): --set accepts default names ----------------------------------

def test_set_names_are_checked_against_the_defaults():
    parsed = parse_text(template_r(T="default sayo_points = 0"))
    sink = DiagnosticSink()
    job = iter_checks(CheckInput(
        paths=None, sink=sink, collected=parsed.ctx.collected,  # type: ignore[arg-type]
        files=(parsed.nodes[0].file,), nodes=tuple(parsed.nodes), checks_skipped=False,
        limit_hit=False, unincluded=(), start_names=("trust", "sayo_point", "fortunes")))
    while True:
        try:
            next(job)
        except StopIteration as stop:
            out = stop.value
            break
    texts = [error.message for error in sink.errors()]
    assert texts == [
        '"sayo_point" has no default, so --set can\'t give it a start value. Did you mean '
        '"sayo_points"?',
        '"fortunes" is a define, which can\'t be changed, so --set can\'t give it a start '
        "value. Use default for values the story changes."]
    assert [d.name for d in out.defaults] == ["trust", "hana_name", "sayo_points"]
