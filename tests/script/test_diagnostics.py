"""The diagnostics sink (F02 checklist step 1; 04-technical.md §7.11).

AC-F02-39's unit part (TR-F02-06): the sink keeps the 50 first diagnostics in reading order
while counting all of them, and file-less ones sort last as E06, E06b, E06c, E06d, E07,
E26, E26b, E26c, E05b (I-18, F44 C2). The 60-error file uses a single-file parse; the multi-file ``order/``
fixture is the loader's (step 6).

Step 9: ``ScriptErrorGroup`` (§7.10.2) — the AC-F02-43 screen text (with the walkthrough's
E70 built directly until the checks exist), the one-problem head, the E100/E99 tail
(AC-F02-41), and ``format()`` built from ``parts()`` (F44 C2, TR-F44-05).
"""

import random
import tracemalloc

import pytest

from engine.core.errors import UserFacingError
from engine.script.diagnostics import (
    FILELESS_ORDER,
    Diagnostic,
    DiagnosticSink,
    ScriptError,
    ScriptErrorGroup,
    WarningLog,
)
from engine.script.messages import format_message
from engine.script.nodes import ScriptFile
from engine.script.statements import ParseContext
from tests.script.helpers import parse_text, template

MAIN = ScriptFile("script/main.vns", "main.vns", 0)
B = ScriptFile("script/b.vns", "b.vns", 1)


def _feed(count: int, seed: int) -> tuple[DiagnosticSink, list[tuple[int, int, int]]]:
    files = [ScriptFile(f"script/f{i}.vns", f"f{i}.vns", i) for i in range(20)]
    rng = random.Random(seed)
    keys = []
    sink = DiagnosticSink()
    for _ in range(count):
        key = (rng.randrange(20), rng.randrange(1, 100_000), rng.randrange(1, 80))
        keys.append(key)
        sink.add(Diagnostic("E30d", files[key[0]], key[1], key[2], ("x",)))
    return sink, keys


# AC-F02-39's sizes run under ``slow``; the default tier checks the same property on a tenth
# of them or less (F02 Step 11 test review: each full-size case took 2-7 s).
@pytest.mark.parametrize("count", [100_000, pytest.param(2_000_000, marks=pytest.mark.slow)])
def test_two_million_diagnostics_keep_the_50_smallest(count):
    sink, keys = _feed(count, 7)
    assert sink.error_count == count
    kept = sink.kept()
    assert len(kept) == 50
    expected = sorted((o, line, c, seq) for seq, (o, line, c) in enumerate(keys, 1))[:50]
    assert [d.order for d in kept] == expected


@pytest.mark.parametrize("count", [20_000, pytest.param(200_000, marks=pytest.mark.slow)])
def test_sink_memory_stays_bounded(count):
    # tracemalloc makes every allocation slow, so the memory part runs on 200,000 (20,000 in
    # the default tier, where unbounded growth would already retain about 4 MiB).
    files = [ScriptFile(f"script/f{i}.vns", f"f{i}.vns", i) for i in range(20)]
    rng = random.Random(8)
    tracemalloc.start()
    try:
        sink = DiagnosticSink()
        before = tracemalloc.get_traced_memory()[0]
        for _ in range(count):
            sink.add(Diagnostic("E30d", files[rng.randrange(20)], rng.randrange(1, 100_000),
                                rng.randrange(1, 80), ("x",)))
        retained = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    assert sink.error_count == count and len(sink.kept()) == 50
    assert retained < 1024 * 1024


def test_fileless_diagnostics_sort_last_in_their_order():
    sink = DiagnosticSink()
    for code in ("E05b", "E26c", "E26b", "E26", "E07", "E06d", "E06c", "E06b", "E06"):
        sink.add(Diagnostic(code))
    sink.add(Diagnostic("E30a", B, 9, None, ("jmup", "jump")))
    sink.add(Diagnostic("E30a", MAIN, 3, None, ("jmup", "jump")))
    assert [d.code for d in sink.kept()] == ["E30a", "E30a", *FILELESS_ORDER]
    assert [d.file.ref for d in sink.kept()[:2]] == ["script/main.vns", "script/b.vns"]
    # F44 C2: the start-option errors E26b, E26c sort after E26.
    assert FILELESS_ORDER == ("E06", "E06b", "E06c", "E06d", "E07", "E26", "E26b", "E26c",
                              "E05b")


def test_nothing_more_for_a_file_after_a_file_ending_error():
    for code in ("E01a", "E01b", "E02", "E05"):
        sink = DiagnosticSink()
        file = ScriptFile("script/x.vns", "x.vns", 3)
        assert sink.add(Diagnostic(code, file, 1 if code == "E01a" else None, None,
                                   () if code == "E01a" else ("script/x.vns",)))
        assert not sink.add(Diagnostic("E30d", file, 9, 1, ("1.",)))
        assert sink.add(Diagnostic("E30d", MAIN, 9, 1, ("1.",)))
        assert sink.error_count == 2


def test_no_indentation_errors_after_the_first_kind_error():
    sink = DiagnosticSink()
    assert sink.add(Diagnostic("E10", MAIN, 5, None, ("\t",)))
    for code in ("E10", "E10c", "E11", "E12", "E13", "E14", "E15"):
        assert not sink.add(Diagnostic(code, MAIN, 20, None, ()))
    assert sink.add(Diagnostic("E30a", MAIN, 21, None, ("jmup", "jump")))
    assert sink.add(Diagnostic("E13", B, 3, None, ()))


def test_one_error_per_logical_line():
    sink = DiagnosticSink()
    assert sink.add(Diagnostic("E52", MAIN, 5, 7, ("\\q",), stmt=5))
    assert not sink.add(Diagnostic("E53", MAIN, 6, 3, ("x",), stmt=5))
    assert sink.add(Diagnostic("E53", MAIN, 6, 3, ("x",), stmt=6))
    assert sink.line_has_error(MAIN, 5)


def test_sixty_errors_in_one_file():
    rows = "⏎".join(["[4]jmup bridge"] * 60).removeprefix("[4]")
    parsed = parse_text(template(S=rows))
    sink = parsed.ctx.sink
    assert sink.error_count == 60
    assert [e.line for e in parsed.errors] == list(range(5, 55))
    extra = sink.error_count - len(parsed.errors)
    assert format_message("E100", (extra,)) == "…and 10 more problems. Fix these and launch again."


@pytest.mark.parametrize("count", [17_400, pytest.param(174_000, marks=pytest.mark.slow)])
def test_many_bad_lines_keep_memory_bounded(count):
    text = "label start:\n" + "    1.\n" * count
    parsed = parse_text(text)
    assert parsed.ctx.sink.error_count == count
    assert len(parsed.errors) == 50


def test_script_error_shapes():
    line_error = Diagnostic("E30d", MAIN, 5, 5, ("1.",), source_line='    1. "Hi"').to_error()
    assert isinstance(line_error, ScriptError)
    assert line_error.format().startswith("script/main.vns, line 5, column 5: this line starts")
    assert (line_error.code, line_error.caret, line_error.source_line) == ("E30d", 5,
                                                                           '    1. "Hi"')
    whole_file = Diagnostic("E02", MAIN, None, None, ("script/main.vns",),
                            whole_file=True).to_error()
    assert whole_file.format() == ("script/main.vns doesn't look like a text file. Script "
                                   "files must be plain text.")
    game = Diagnostic("E06").to_error()
    assert game.format().startswith("The story includes more than 1,000 .vns files")


CH1 = ScriptFile("script/chapter1.vns", "chapter1.vns", 1)


def _priya_step4() -> list[ScriptError]:
    """AC-F02-43's walkthrough errors: lines 3–4 from a parse of chapter1.vns; line 5's E70
    comes from the whole-game checks (step 7), so it is built directly."""
    text = 'label chapter1:\n    "Hi."\n    hana “You came!”\n    jmup bridge\n    hnaa "Hi."\n'
    ctx = ParseContext(sink=DiagnosticSink())
    ctx.collected.define_defs["hana"] = [(MAIN, 1)]
    parsed = parse_text(text, ref="script/chapter1.vns", ctx=ctx, order=1)
    e70 = Diagnostic("E70", CH1, 5, None, ("hnaa", "hana"), source_line='    hnaa "Hi."')
    return [*parsed.errors, e70.to_error()]


def test_ac43_error_screen_text():
    errors = _priya_step4()
    assert [e.code for e in errors] == ["E50", "E30a", "E70"]
    group = ScriptErrorGroup(errors, 3)
    assert group.format() == (
        "The script has 3 problems:\n"
        "\n"
        "script/chapter1.vns, line 3, column 10: this line uses curly quotes “ ” around the "
        'text. Put the text between straight quotes "like this". Curly quotes inside the text '
        "are fine.\n"
        "        hana “You came!”\n"
        "\n"
        'script/chapter1.vns, line 4: "jmup" is not a statement. Did you mean "jump"?\n'
        "        jmup bridge\n"
        "\n"
        'script/chapter1.vns, line 5: no character named "hnaa". Did you mean "hana"?\n'
        '        hnaa "Hi."')
    assert "^" not in group.format()
    assert group.message == group.format() and isinstance(group, UserFacingError)


def test_ac43_one_problem_and_the_tail():
    one = ScriptErrorGroup([Diagnostic("E30a", MAIN, 5, None, ("jmup", "jump")).to_error()], 1)
    assert one.format().startswith("The script has 1 problem:\n\n")
    sink = DiagnosticSink()
    for line in range(1, 61):
        sink.add(Diagnostic("E30a", MAIN, line, None, ("jmup", "jump")))
    many = ScriptErrorGroup(sink.errors(), sink.error_count)
    assert many.format().startswith("The script has 60 problems:")
    assert many.format().endswith("\n\n…and 10 more problems. Fix these and launch again.")
    skipped = ScriptErrorGroup(sink.errors(), sink.error_count, checks_skipped=True)
    assert skipped.format().endswith(
        "…and 10 more problems. Fix these and launch again.\n\nSome checks (labels, characters) "
        "were skipped because a file couldn't be read. Launch again after fixing it.")


def test_ac41_e99_is_not_counted():
    error = Diagnostic("E97", MAIN, 9, None, ("locked.vns", "script/locked.vns")).to_error()
    group = ScriptErrorGroup([error], 1, checks_skipped=True)
    head, items, tail = group.parts()
    assert head == "The script has 1 problem:"
    assert len(items) == 1 and tail == (format_message("E99"),)


def test_parts_build_format_tr_f44_05():
    sink = DiagnosticSink()
    for line in range(1, 61):
        sink.add(Diagnostic("E52", MAIN, line, 7, ("\\q",), source_line='    "a\\qb"'))
    sink.add(Diagnostic("E26"))
    for checks_skipped in (False, True):
        group = ScriptErrorGroup(sink.errors(), sink.error_count, checks_skipped=checks_skipped)
        head, items, tail = group.parts()
        assert "\n\n".join([head, *(text for _, text in items), *tail]) == group.format()
        assert [error for error, _ in items] == list(group.errors)
        assert items[0][1] == ('script/main.vns, line 1, column 7: "\\q" is not a special '
                               "sequence. Write \\\\ for a backslash, \\\" for a quote, or \\n "
                               'for a new line.\n        "a\\qb"')


def test_from_result_and_a_whole_game_error():
    class Result:
        errors = (Diagnostic("E26").to_error(),)
        error_count = 1
        checks_skipped = False

    group = ScriptErrorGroup.from_result(Result())
    assert group.total == 1 and group.checks_skipped is False
    assert group.format() == ('The script has 1 problem:\n\nThe story has no label named "start". '
                              "Add label start: to script/main.vns. The story begins there.")


def test_the_screen_shows_the_same_window_as_the_log():
    source = "x" * 150 + "!" + "x" * 100
    error = ScriptError("m.", code="E30d", file="script/main.vns", line=2, column=151,
                        source_line=source)
    _, items, _ = ScriptErrorGroup([error], 1).parts()
    shown = items[0][1].split("\n")[1]
    assert shown.startswith("    …") and "!" in shown and len(shown) <= 4 + 120


def test_warning_log_caps_w03():
    log = WarningLog()
    for line in range(1, 121):
        log.add_w03(MAIN, line, "invalid escape sequence \"\\d\"")
    result = log.finish()
    assert len(result) == 51
    assert result[0].format() == ('script/main.vns, line 1: Python warns: invalid escape '
                                  'sequence "\\d".')
    assert result[-1].format() == "…and 70 more Python warnings."
