"""The core statements and how a line is read (F02 checklist step 5; 04-technical.md §6).

AC-F02-21 (the core statements build the expected nodes), AC-F02-22 (how a line is read),
AC-F02-25 (statement words that can't be used here), and AC-F02-30 (reserved words and the
statement registry), through a single-file parse. Reading order across files, the
``Program``, and the speaker/target checks are steps 6–8.
"""

import pytest

from engine.script.lexer import NAME, TAIL_SCRIPT
from engine.script.nodes import (
    Call,
    Define,
    If,
    Include,
    Jump,
    Label,
    Node,
    PythonLine,
    Return,
    Say,
    Statement,
)
from engine.script.statements import (
    StatementSpec,
    get_spec,
    register,
    registered_words,
    scoped_registry,
)
from engine.script.words import STATEMENT_WORDS, STATEMENT_WORDS_F02
from tests.script.helpers import FIXTURES, dumps, message_at, parse_text, template


def _lanterns(name: str, order: int):
    path = FIXTURES / "lanterns" / name
    return parse_text(path.read_text(encoding="utf-8"), f"script/{name}", order=order)


# --- AC-F02-21 ---------------------------------------------------------------------------

def _where(node: Node) -> tuple[int, int, int]:
    return node.line, node.end_line, node.column


def test_chapter1_nodes():
    parsed = _lanterns("chapter1.vns", 1)
    assert parsed.errors == []
    labels = [node for node in parsed.nodes]
    assert [type(n).__name__ for n in labels] == ["Label", "Label"]
    riverbank, stall = labels
    assert (riverbank.name, stall.name) == ("riverbank", "lantern_stall")
    block = riverbank.block
    assert [type(s) for s in block] == [Say, Say, Call, If, Jump]
    say1, say2, call, chain, jump = block
    assert _where(say1) == (2, 3, 5)
    assert (say1.speaker, say1.attributes, say1.text) == (
        None, (), "Paper lanterns drifted past us one by one, each carrying somebody's wish "
                  "downstream.")
    assert _where(say2) == (4, 4, 5)
    assert (say2.speaker, say2.attributes, say2.text) == (
        "hana", (), "Did you write one? Everybody writes one.")
    assert _where(call) == (5, 5, 5) and call.target == "lantern_stall"
    assert chain.line == 7
    first, second, third = chain.branches
    assert (first.keyword, first.condition.source, first.line, first.condition.column) == (
        "if", "bought_lantern and trust >= 2", 7, 8)
    happy, plus = first.block
    assert (happy.line, happy.speaker, happy.attributes, happy.text) == (
        8, "hana", ("happy",), "You actually bought one! Here, the pen's still wet.")
    assert isinstance(plus, PythonLine)
    assert (plus.line, plus.py.source, plus.py.column) == (9, "trust += 1", 11)
    assert (second.keyword, second.line, second.condition.source) == ("elif", 10,
                                                                      "bought_lantern")
    assert [s.line for s in second.block] == [11]
    assert (third.keyword, third.line, third.condition) == ("else", 12, None)
    sad, quote = third.block
    assert (sad.line, sad.speaker, sad.attributes) == (13, "hana", ("sad",))
    assert (quote.line, quote.speaker, quote.text) == (
        14, "daichi", 'She\'s been saying "just one more" since six o\'clock.')
    assert _where(jump) == (17, 17, 5) and jump.target == "bridge"
    assert stall.line == 19
    narration, small_if, ret = stall.block
    assert (narration.line, narration.text) == (
        20, '"Three hundred yen," the stall keeper said. "Wishes are extra."')
    assert (small_if.line, small_if.branches[0].condition.source) == (21, "trust > 0")
    inner = small_if.branches[0].block[0]
    assert (inner.line, inner.py.source) == (22, "bought_lantern = True")
    assert isinstance(ret, Return) and ret.line == 23


def test_main_nodes():
    parsed = _lanterns("main.vns", 0)
    assert parsed.errors == []
    includes = [n for n in parsed.nodes if isinstance(n, Include)]
    assert [(n.line, n.path) for n in includes] == [(1, "chapter1.vns"),
                                                    (2, "routes/daichi.vns")]
    defines = [n for n in parsed.nodes if isinstance(n, Define)]
    assert (defines[0].name, defines[0].line, defines[0].value.source) == (
        "hana", 4, 'Character("Hana", color="#e8a0b4")')
    assert defines[0].value.mode == "eval" and defines[0].value.names == {"Character"}
    start = parsed.labels["start"]
    first = start.block[0]
    assert isinstance(first, PythonLine)
    assert (first.line, first.py.source, first.py.mode, first.py.column) == (
        8, "trust = 1", "exec", 7)
    for node in _walk(parsed.nodes):
        assert node.file.ref == "script/main.vns"


def _walk(nodes):
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, Label):
            stack.extend(node.block)
        elif isinstance(node, If):
            for branch in node.branches:
                stack.extend(branch.block)


def test_code_objects_are_named_after_the_file():
    parsed = _lanterns("chapter1.vns", 1)
    chain = parsed.labels["riverbank"].block[3]
    assert chain.branches[0].condition.code.co_filename == "<script/chapter1.vns>"


def test_identity_keys_follow_adr_0006():
    parsed = parse_text(template(S='hana happy "Hi   there"⏎[4]$ x = 1  # note⏎[4]call bridge'))
    block = parsed.labels["start"].block
    assert block[1].identity_key() == ("say", "hana", "Hi there")
    assert block[2].identity_key() == ("py", "x = 1")
    assert block[3].identity_key() == ("call", "bridge")
    assert block[4].identity_key() == ("jump", "bridge")
    assert Return(file=block[0].file, line=1, end_line=1, column=1).identity_key() == (
        "return",)


# --- AC-F02-22 ---------------------------------------------------------------------------

EXTRA = 'define returned = Character("R")⏎define jumpy = Character("J")'


@pytest.mark.parametrize("row,expected", [
    ('returned "Back."', ("say", "returned")),
    ('jumpy "Hi"', ("say", "jumpy")),
    ("Jump bridge", "E31"), ("Jump “x”", "E31"),
    ("hana “Hi”", "E50"), ("hana 'Hi'", "E51"), ('1. "Hi"', "E30d"),
    ('"Hi"', ("say", None)),
    ("hana Hello there.", "E71"), ("jmup bridge", "E30a"), ("The lanterns were lit.", "E30b"),
    ('hana (sad) "Hi"', "E72"), ('hana a b c d e "Hi"', "E73"),
    ('kaito "Hi"', "E70"), ("$ x = 1", "python"),
])
def test_how_a_line_is_read(row, expected):
    parsed = parse_text(template(S=row, T=EXTRA))
    if isinstance(expected, str) and expected.startswith("E") and expected != "E70":
        assert parsed.codes == [expected]
        return
    assert parsed.errors == []
    node = parsed.labels["start"].block[1]
    if expected == "python":
        assert isinstance(node, PythonLine)
    elif expected == "E70":
        # Speaker checks are whole-game (step 7): the line is dialogue whose speaker is
        # not defined.
        assert isinstance(node, Say) and node.speaker == "kaito"
        assert "kaito" in parsed.ctx.collected.speakers
        assert "kaito" not in parsed.ctx.collected.define_defs
    else:
        assert isinstance(node, Say) and node.speaker == expected[1]


# --- AC-F02-25 ---------------------------------------------------------------------------

# AC-F02-25's 25 unbuilt words, less those a later feature has built since (F03: default;
# F04: scene, show, hide, image; F08: play, stop, queue, voice; F07: menu; F09: pause, shake,
# flash, and with, which now starts no line: E32b; F18: chapter; F22: points; F17: nvl; F19:
# ending, lock, unlock; F23: minigame).
UNBUILT = "window".split()                  # F28 s3 built effect; F32 s4 ui; F31 s3 file;
                                            # F34 freed cg (lock gallery)


@pytest.mark.parametrize("row,where,message", [
    ("jmup bridge", "5", '"jmup" is not a statement. Did you mean "jump"?'),
    ("The lanterns were lit.", "5",
     '"The" is not a statement, and this line has no text in quotes. If it is narration or '
     'dialogue, put the text in straight quotes: "The lanterns were lit."'),
    ('1. "Hi"', "5:5", 'this line starts with "1.", which isn\'t a statement, a name, or a '
                       "quote. Put narration or dialogue in straight quotes."),
    ("Jump bridge", "5", '"Jump" is not a statement. Statement words are lower case: jump.'),
    ("python:⏎[8]x = 1", "5",
     "python: blocks aren't supported. Write each line of Python as its own $ line."),
    ("jump", "5", "jump needs the name of a label, e.g. jump bridge."),
    ('jump "bridge"', "5", "label names aren't written in quotes. Write jump bridge."),
    ("jump bridge and run", "5", 'jump takes one label name, but this line has more after '
                                 'it. Remove "and run", or join the words with _.'),
    ("jump bridge:", "5", "jump doesn't start a block. Remove the :."),
    ("return home", "5", 'return doesn\'t take anything after it. Remove "home".'),
])
def test_statement_word_errors(row, where, message):
    parsed = parse_text(template(S=row))
    assert [message_at(e) for e in parsed.errors] == [(where, message)]


@pytest.mark.parametrize("word", UNBUILT)
def test_unbuilt_words_are_e32(word):
    assert len(UNBUILT) == 1
    parsed = parse_text(template(S=f"{word} hana"))
    assert [message_at(e) for e in parsed.errors] == [(
        "5", f'"{word}" is not available yet in this engine version. Remove the line or '
             "comment it out with # for now.")]


@pytest.mark.parametrize("edit,line", [
    ({"T": "window show"}, 9),     # F07 removed the menu row (menu:⏎… parses, its 07 I-10);
                                   # F09 built pause, so the row was nvl's; F17 built nvl
])
def test_e32_only(edit, line):
    parsed = parse_text(template(**edit))
    assert parsed.codes == ["E32"] and parsed.errors[0].line == line


@pytest.mark.parametrize("word,example", [("at", "show hana at left"),
                                          ("as", "show hana as hana2"),
                                          ("behind", "show hana behind daichi"),
                                          ("with", "scene bg river with fade")])     # F09
def test_modifier_words_are_e32b(word, example):
    parsed = parse_text(template(S=f"{word} x"))
    assert [message_at(e) for e in parsed.errors] == [(
        "5", f'"{word}" can\'t start a line. It goes after a statement, e.g. {example}.')]


E40 = ("this line is outside any label, so the story can never reach it. Add label <name>: "
       "above it and indent it.")


def test_e40_once_per_run():
    parsed = parse_text(template(T='"Hello."⏎hana "Hi."⏎⏎# c⏎"Again."'))
    assert [message_at(e) for e in parsed.errors] == [("9", E40)]


def test_e40_again_after_a_label():
    parsed = parse_text(template(T='"Hello."⏎label x:⏎[4]return⏎"Again."'))
    assert [message_at(e) for e in parsed.errors] == [("9", E40), ("12", E40)]


def test_call_without_a_name():
    parsed = parse_text(template(S="call"))
    assert parsed.messages[0].startswith("script/main.vns, line 5: call needs the name of a "
                                         "label")


@pytest.mark.parametrize("row,code", [
    ("label inner:⏎[8]return", "E24"), ("define x = 1", "E46"), ('include "a.vns"', "E90"),
])
def test_top_level_statements_in_a_block(row, code):
    parsed = parse_text(template(S=row))
    assert parsed.codes == [code]


def test_e90_text():
    parsed = parse_text(template(S='include "a.vns"'))
    assert message_at(parsed.errors[0]) == (
        "5", "include can't be inside a label or block, because a file belongs to the game "
             "from the start. Move it to the top level.")


@pytest.mark.parametrize("row,code,where", [
    ("include chapter2.vns", "E95", "9"), ('include "a.vns" "b.vns"', "E96", "9:17"),
])
def test_include_shape_errors(row, code, where):
    parsed = parse_text(template(T=row))
    assert [(e.code, message_at(e)[0]) for e in parsed.errors] == [(code, where)]


def test_e95_text():
    parsed = parse_text(template(T="include chapter2.vns"))
    assert parsed.errors[0].message == ('the file name goes in quotes. Write include '
                                        '"chapter2.vns".')


# --- AC-F02-30 ---------------------------------------------------------------------------

SR_F02_38 = ("label jump call return if elif else define include default scene show hide at "
             "behind as image window pause menu play stop queue voice with shake flash nvl "
             "chapter ending lock unlock points minigame effect file python").split()


def test_statement_words_are_exactly_the_37():
    """F02's 38, frozen (F14 07 I-1), F14's ``rollback`` as the 39th (04 §18 A1), F20's
    ``flowchart`` as the 40th (F20 07 A1), and F32's ``ui`` as the 41st (F32 C1); F34 freed
    ``cg`` (F34 07 I-1), so 37 and 40."""
    assert len(SR_F02_38) == 37
    assert STATEMENT_WORDS_F02 == frozenset(SR_F02_38)
    assert STATEMENT_WORDS == frozenset(SR_F02_38) | {"rollback", "flowchart", "ui"}


def _spec(word: str) -> StatementSpec:
    return StatementSpec(word, "story", False, TAIL_SCRIPT, lambda raw, ctx: None)


def test_register_rejects_unreserved_and_duplicate_words():
    with scoped_registry():
        with pytest.raises(ValueError):
            register(_spec("music"))
        with pytest.raises(ValueError):
            register(_spec("label"))


def test_f02_registry():
    # F02's nine, plus default (F03 step 4), scene, show, hide, image (F04 step 2), and play,
    # queue, stop, voice (F08 step 1), menu (F07 step 1), shake, flash, pause (F09 step 1), and
    # chapter (F18 step 1), points (F22 step 1), rollback (F14 step 1), nvl (F17 step 1), and
    # ending, lock, unlock (F19 step 3), minigame (F23 s2), flowchart (F20 s1), effect
    # (F28 s3), ui (F32 s4), and file (F31 s3).
    assert registered_words() == frozenset(
        "label define include jump call return if elif else default scene show hide image "
        "play queue stop voice menu shake flash pause chapter points rollback nvl ending lock "
        "unlock minigame flowchart effect ui file".split())


class Window(Statement):            # an unbuilt word (nvl until F17 built it)
    __slots__ = ("mode",)

    def identity_key(self) -> tuple[str, ...]:
        return ("window", self.mode)


def _parse_window(raw, ctx):
    tokens = raw.tokens[1:]
    if len(tokens) != 1 or tokens[0].kind != NAME:
        ctx.error("E32", "window")
        return None
    node = Window(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column)
    node.mode = tokens[0].text
    return node


def test_scoped_registration_parses_with_the_new_spec_and_is_undone():
    lanterns = (FIXTURES / "lanterns" / "chapter1.vns").read_text(encoding="utf-8")
    before = dumps(parse_text(lanterns, "script/chapter1.vns").nodes)
    with scoped_registry():
        register(StatementSpec("window", "story", False, TAIL_SCRIPT, _parse_window))
        parsed = parse_text(template(S="window show"))
        assert parsed.errors == []
        node = parsed.labels["start"].block[1]
        assert isinstance(node, Window) and node.mode == "show"
        assert dumps(parse_text(lanterns, "script/chapter1.vns").nodes) == before
    assert get_spec("window") is None
    assert parse_text(template(S="window show")).codes == ["E32"]
