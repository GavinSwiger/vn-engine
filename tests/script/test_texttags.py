"""Text tags (F05 step 2): ``texttags.parse``, STRING ``origins``, and ``Say.body``.

ACs: AC-F05-01 (tags become a styled body), AC-F05-03 (error positions and a parser that
never breaks). AC-F05-02's message rows are ``feature = "F05"`` rows of
``tests/fixtures/F02/messages/cases.toml`` (``test_messages.py``); the extra edge cases here
pin the forms 02 leaves open.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from engine.script.diagnostics import DiagnosticSink
from engine.script.lexer import STRING, StatementReader
from engine.script.limits import SCRIPT_MAX_ERRORS, SCRIPT_MAX_LINE_CHARS
from engine.script.nodes import Say, ScriptFile
from engine.script.statements import tail_for
from engine.script.texttags import (
    BASE_STYLE,
    EMPTY_TEXT,
    INSTANT,
    PauseMark,
    Span,
    Style,
    TaggedText,
    TagProblem,
    VarMark,
    WaitMark,
    origin_of,
    parse,
)
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)
from tests.script.helpers import message_at, parse_text, template_x

FUZZ = Path(__file__).resolve().parents[1] / "fixtures" / "F05" / "fuzz_texttags.py"


def load_fuzz():
    """``tests/fixtures/F05/fuzz_texttags.py`` as a module (it is not a package)."""
    spec = importlib.util.spec_from_file_location("fuzz_texttags", FUZZ)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fuzz_texttags"] = module
    spec.loader.exec_module(module)
    return module


def run(text: str) -> tuple[TaggedText | None, list[TagProblem]]:
    """Parse ``text`` as template X's line 7 (a ``{`` at offset k is column 6 + k)."""
    problems: list[TagProblem] = []
    body = parse(text, lambda k: (7, 6 + k), problems.append)
    return body, problems


def ok(text: str) -> TaggedText:
    body, problems = run(text)
    assert not problems, [p.message() for p in problems]
    assert body is not None
    return body


# --- 06 §0.5 body notation -------------------------------------------------------------------

def st(*marks: str) -> Style:
    """``b``, ``i``, ``#rrggbb``, ``s1.5``, ``v0.5``, ``vI`` → a ``Style``."""
    style = {}
    for mark in marks:
        if mark == "b":
            style["bold"] = True
        elif mark == "i":
            style["italic"] = True
        elif mark.startswith("#"):
            style["color"] = mark
        elif mark.startswith("s"):
            style["size"] = float(mark[1:])
        elif mark == "vI":
            style["speed"] = INSTANT
        elif mark.startswith("v"):
            style["speed"] = float(mark[1:])
    return Style(**style)


def sp(text: str, *marks: str) -> Span:
    return Span(text, st(*marks))


def body(*pieces, auto_next: bool = False) -> TaggedText:
    return TaggedText(tuple(pieces), auto_next)


# --- AC-F05-01 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("I saw it... {pause=0.6}the {b}{color=#E05050}lantern{/color}{/b} moved.",
     body(sp("I saw it... "), PauseMark(0.6), sp("the "), sp("lantern", "b", "#e05050"),
          sp(" moved."))),
    ("That's impossible. {pause}...Isn't it?",
     body(sp("That's impossible. "), WaitMark(), sp("...Isn't it?"))),
    ("{b}a{i}b{/i}c{/b}", body(sp("a", "b"), sp("b", "b", "i"), sp("c", "b"))),
    ("{color=#111111}a{color=#222222}b{/color}c{/color}",
     body(sp("a", "#111111"), sp("b", "#222222"), sp("c", "#111111"))),
    ("{speed=2}a{speed=0.5}b{/speed}{/speed}", body(sp("a", "v2"), sp("b", "v0.5"))),
    ("{speed=instant}LOOK!{/speed} It's", body(sp("LOOK!", "vI"), sp(" It's"))),
    ("{size=1.5}big{/size}", body(sp("big", "s1.5"))),
    ("{b}open to the end", body(sp("open to the end", "b"))),
    ("a{b}{/b}b", body(sp("ab"))),
    ("{b}a{/b}{b}b{/b}", body(sp("ab", "b"))),
    ("{{name}: {{wish}", body(sp("{name}: {wish}"))),
    ("{{b}", body(sp("{b}"))),
    ("} and }} stay", body(sp("} and }} stay"))),
    ("a\nb", body(sp("a\nb"))),
    ("[player_name]", body(sp("[player_name]"))),
    ("Hi {var=player_name}!", body(sp("Hi "), VarMark("player_name", BASE_STYLE), sp("!"))),
    ("{b}{var=player_name}{/b}", body(VarMark("player_name", st("b")))),
    ("in i—{next}", body(sp("in i—"), auto_next=True)),
    ("{b}a{next}{/b}", body(sp("a", "b"), auto_next=True)),
    ("", EMPTY_TEXT),
    ("{b}" * 50 + "x", body(sp("x", "b"))),
])
def test_ac01_tags_become_a_styled_body(text, expected):
    assert ok(text) == expected


@pytest.mark.parametrize("text,expected", [
    # Edge cases the AC table leaves out.
    ("{b}{/b}", EMPTY_TEXT),                                         # empty span: nothing
    ("{next}", body(auto_next=True)),
    ("{b}a{i}b{/i}{/b}{next}", body(sp("a", "b"), sp("b", "b", "i"), auto_next=True)),
    ("a{pause}{pause}b", body(sp("a"), WaitMark(), WaitMark(), sp("b"))),   # SR-F05-13 at run
    ("{pause=0.1}", body(PauseMark(0.1))),
    ("{pause=30}x", body(PauseMark(30.0), sp("x"))),
    ("{pause=007.50}", body(PauseMark(7.5))),
    ("{size=0.5}a{/size}{size=2}b", body(sp("a", "s0.5"), sp("b", "s2"))),
    ("{speed=0.1}a{speed=10}b", body(sp("a", "v0.1"), sp("b", "v10"))),
    ("{speed=instant}a{speed=2}b{/speed}c", body(sp("a", "vI"), sp("b", "v2"), sp("c", "vI"))),
    ("{color=#ABCdef}a", body(sp("a", "#abcdef"))),
    ("{i}{color=#111111}{b}x{/b}{/color}{/i}", body(sp("x", "b", "i", "#111111"))),
    ("{var=ｐｌａｙｅｒ}", body(VarMark("player", BASE_STYLE))),      # NFKC, as names are
    ("{var=名前}", body(VarMark("名前", BASE_STYLE))),
    ("a}b{{c}}", body(sp("a}b{c}}"))),
    ("{{}", body(sp("{}"))),
    ("é 😀 日本", body(sp("é 😀 日本"))),
    ("{b}a{/b}{pause}{b}b{/b}", body(sp("a", "b"), WaitMark(), sp("b", "b"))),
])
def test_ac01_edge_cases(text, expected):
    assert ok(text) == expected


def test_plain_drops_timing_and_merges_across_marks():
    parsed = ok("a{pause=1}b{b}c{pause}{/b}{b}d{var=x}{/b}")
    assert parsed.plain() == (sp("ab"), sp("cd", "b"))
    assert EMPTY_TEXT.plain() == ()


def test_ac01_tags_only_in_line_text():
    text = template_x(T='define motto = "{colour}"', D='$ s = "{bogus}"  # {blink}')
    parsed = parse_text(text)
    assert parsed.errors == [] and parsed.warnings == ()


def test_say_nodes_carry_the_body():
    parsed = parse_text(template_x(S="Hi {b}{var=player_name}{/b}."))
    say = parsed.labels["start"].block[0]
    assert isinstance(say, Say)
    assert say.text == "Hi {b}{var=player_name}{/b}."
    assert say.body == body(sp("Hi "), VarMark("player_name", st("b")), sp("."))
    # Dialogue too, and the identity key still uses the text as written (ADR-0006).
    parsed = parse_text(template_x(D='hana "{i}Oh.{/i}"'))
    say = parsed.labels["start"].block[0]
    assert say.body == body(sp("Oh.", "i"))
    assert say.identity_key() == ("say", "hana", "{i}Oh.{/i}")


# --- AC-F05-02 forms beyond the cases.toml rows -------------------------------------------------

@pytest.mark.parametrize("text,code,column,message", [
    ("{/}", "E160", 6, 'there is no tag "/". The tags are b, i, color, size, speed, shake, '
                       "wave, glitch, pause, var, next, and username."),   # F30: 12 tags
    ("{=5}", "E160", 6, None),
    ("{Bold}x", "E160", 6, 'there is no tag "Bold". For bold, write {b}…{/b}.'),
    ("{/B}", "E160", 6, "tags are lower case: write {/b}, not {/B}."),
    ("{Speed=Instant}", "E160", 6, "tags are lower case: write {speed=instant}, not "
                                   "{Speed=Instant}."),
    ("{b!}", "E160", 6, 'there is no tag "b!". Did you mean "b"?'),
    ("{b }x", "E162", 6, "tags have no spaces inside: write {b}."),
    ("{b x}", "E162", 6, "tags have no spaces inside: write {bx}."),
    ("{color=#e05050\n}x", "E162", 6, "tags have no spaces inside: write {color=#e05050}."),
    ("{color='#e05050'}x", "E162", 6, "tag values have no quotes: write {color=#e05050}."),
    ("{pause=}x", "E163", 6, "{pause=} needs a number of seconds, e.g. {pause=0.5}, or write "
                             "{pause} to wait for a click."),
    ("{color=}x", "E163", 6, "{color} needs a color, e.g. {color=#e05050}…{/color}."),
    ("{next=}", "E163", 6, None),
    ("{var=class}", "E164", 6, None),
    ("{var=1st}", "E164", 6, None),
    ("{pause=1.}", "E164", 6, None),
    ("{pause=1e3}", "E164", 6, None),
    ("{pause=" + "9" * 400 + "}", "E164", 6, None),
    ("{speed=Instant}", "E160", 6, None),
    ("{/var=x}", "E163", 6, "a closing tag takes no value. Write {/var}."),
    ("{b}{i}{color=#111111}a{/i}", "E166", 28,
     "{/i} closes italic, but {color} was opened inside it and is still open. Close {/color} "
     "first: {i}…{color}…{/color}{/i}."),
    ("a{next}}", "E167", 7, None),
    ("a{next} ", "E167", 7, None),
    ("a{next}{{", "E167", 7, None),
    ("a{next}{pause}", "E167", 7, None),
    ("a{next}{b}", "E167", 7, None),
    ("a{next}{/b}", "E165", 13, None),
    ("{b}a{next}{/b}{next}", "E167", 20, "this line has {next} twice. Keep the last one."),
    ("{{" * 3 + "{", "E161", 12, None),
    ("a{b{", "E161", 7, "this { never closes. End the tag with }, or write {{ to show a {."),
])
def test_ac02_more_forms(text, code, column, message):
    parsed, problems = run(text)
    assert parsed is None
    assert [(p.code, p.line, p.column) for p in problems] == [(code, 7, column)]
    if message is not None:
        assert problems[0].message() == message


def test_ac02_nesting_and_depth_limits():
    assert ok("{color=#111111}" * 50 + "x").pieces == (sp("x", "#111111"),)
    _, problems = run("{b}" * 25 + "{i}" * 25 + "{size=2}x")
    assert [(p.code, p.column) for p in problems] == [("E161", 6 + 150)]
    # Closing frees a level.
    assert ok(("{b}" * 50 + "x{/b}") + "{i}y").pieces[-1] == sp("y", "b", "i")


# --- AC-F05-03 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("S,where", [
    ('a\\"{colour}', "7:9"),
    ("a\\n{colour}", "7:9"),
    ("ab\\⏎[8]{colour}x", "8:9"),                     # a \ join; the closing quote on line 8
    ("ab⏎[8]{colour}x", "8:9"),                       # a plain join adds a space
    ("{colour}{blink}", "7:6"),
    ("a\\\\{colour}", "7:9"),
    ("日本{colour}", "7:8"),
    ("😀{colour}", "7:7"),                            # columns count code points
])
def test_ac03_error_positions(S, where):
    parsed = parse_text(template_x(S=S))
    assert len(parsed.errors) == 1, parsed.messages
    error = parsed.errors[0]
    assert error.code == "E160"
    assert message_at(error)[0] == where


def test_ac03_a_tag_may_span_a_backslash_join_but_not_a_plain_one():
    parsed = parse_text(template_x(S="{color=\\⏎[8]#e05050}a"))
    assert parsed.errors == []
    assert parsed.labels["start"].block[0].body == body(sp("a", "#e05050"))
    parsed = parse_text(template_x(S="{color=⏎[8]#e05050}a"))
    assert [(e.code, message_at(e)[0]) for e in parsed.errors] == [("E162", "7:6")]


def test_ac03_sixty_bad_lines_give_the_capped_report():
    lines = "⏎".join(['[4]"{colour}"'] * 60)
    parsed = parse_text(template_x(D='"x"⏎' + lines))
    assert parsed.ctx.sink.error_count == 60
    assert len(parsed.errors) == SCRIPT_MAX_ERRORS
    assert {e.code for e in parsed.errors} == {"E160"}
    assert [e.line for e in parsed.errors] == list(range(8, 8 + SCRIPT_MAX_ERRORS))


def test_ac03_line_limit_counts_tags_as_written():
    unit = "{b}a{/b}"
    room = SCRIPT_MAX_LINE_CHARS - len('    ""')
    text = (unit * (room // len(unit)) + "x" * (room % len(unit)))
    assert len('    "' + text + '"') == SCRIPT_MAX_LINE_CHARS
    parsed = parse_text(template_x(S=text))
    assert parsed.errors == [], parsed.messages[:1]
    parsed = parse_text(template_x(S=text + "x"))
    assert parsed.codes == ["E16"]


_TAG_OR_BRACES_RE = re.compile(r"\{\{|\{[^}]*\}")


def _strip_tags(text: str) -> str:
    """The input with every tag removed and ``{{`` turned into ``{`` (AC-F05-03)."""
    return _TAG_OR_BRACES_RE.sub(lambda m: "{" if m.group() == "{{" else "", text)


def _lexed(source: str) -> tuple[str, tuple] | None:
    """The STRING token of ``source`` read by the real reader (None past the line limit)."""
    if len(source) > SCRIPT_MAX_LINE_CHARS:
        return None
    file = ScriptFile("script/main.vns", "main.vns", 0)
    reader = StatementReader(file, "label start:\n" + source + "\n", DiagnosticSink(), tail_for)
    reader.next()
    raw = reader.next()
    assert raw is not None
    token = raw.tokens[0]
    assert token.kind == STRING
    return token.text, token.origins


def _check_fuzz(count: int, seed: int = 1) -> None:
    fuzz = load_fuzz()
    for number, case in enumerate(fuzz.cases(seed, count)):
        origins = case.origins
        lexed = _lexed(case.source) if number % 10 == 0 else None
        if lexed is not None:
            text, lexed_origins = lexed
            assert text == case.text
            # The lexer's slices sit on line 2 here; the generator's on template X's line 7.
            origins = tuple((o, 7, c) for o, _, c in lexed_origins)
        problems: list[TagProblem] = []
        parsed = parse(case.text, origin_of(origins, (7, 6)), problems.append)
        if parsed is not None:
            assert not problems
            shown = "".join(p.text for p in parsed.pieces if isinstance(p, Span))
            assert shown == _strip_tags(case.text), number
        else:
            assert len(problems) == 1, number
            problem = problems[0]
            assert problem.line == 7
            assert case.source[problem.column - 1] == "{", (number, problem)
            assert problem.message()


def test_ac03_fuzz_never_breaks():
    _check_fuzz(2_000)


@pytest.mark.slow
def test_ac03_fuzz_never_breaks_100k():
    _check_fuzz(100_000)


def test_fuzz_generator_is_deterministic_and_covers_its_shapes():
    fuzz = load_fuzz()
    first = list(fuzz.cases(1, 200))
    assert first == list(fuzz.cases(1, 200))
    assert max(len(c.text) for c in first) <= 10_000
    assert any(len(c.text) > 2_000 for c in first) and any(c.text == "" for c in first)
    results = [run(c.text)[0] is not None for c in first]
    assert any(results) and not all(results)


# --- STRING origins (04 §6.1) -------------------------------------------------------------------

@pytest.mark.parametrize("source,text,origins", [
    ('    "abc"', "abc", ((0, 2, 6),)),
    ('    "a\\"b"', 'a"b', ((0, 2, 6), (1, 2, 7), (2, 2, 9))),
    ('    "\\n\\\\x"', "\n\\x", ((0, 2, 6), (1, 2, 8), (2, 2, 10))),
    ('    "ab\\\n        cd"', "abcd", ((0, 2, 6), (2, 3, 9))),
    ('    "ab  \n        cd"', "ab cd", ((0, 2, 6), (2, 2, 8), (3, 3, 9))),
    ('    ""', "", ()),
    ('    "a\\qb"', "a\\qb", ((0, 2, 6), (1, 2, 7), (3, 2, 9))),       # E52, kept as written
])
def test_string_origins(source, text, origins):
    file = ScriptFile("script/main.vns", "main.vns", 0)
    reader = StatementReader(file, "label start:\n" + source + "\n", DiagnosticSink(), tail_for)
    reader.next()
    token = reader.next().tokens[0]
    assert (token.text, token.origins) == (text, origins)


def test_origin_of_maps_offsets_inside_slices():
    origin = origin_of(((0, 7, 6), (3, 8, 9)), (7, 5))
    assert [origin(k) for k in (0, 2, 3, 5)] == [(7, 6), (7, 8), (8, 9), (8, 11)]
    assert origin_of((), (7, 6))(0) == (7, 6)


def test_on_var_reports_each_use_with_its_place():
    seen = []
    parse("{var=a} {b}{var=b}{/b}", lambda k: (7, 6 + k), lambda p: None,
          on_var=lambda name, line, column: seen.append((name, line, column)))
    assert seen == [("a", 7, 6), ("b", 7, 17)]


def test_messages_show_hidden_characters_escaped():
    _, problems = run("{b‮}")
    assert "\\u202e" in problems[0].message() and "‮" not in problems[0].message()
    _, problems = run("{" + "x" * 5000 + "}")
    assert len(problems[0].message()) < 400
    assert re.search(r'there is no tag "x+…"', problems[0].message())
