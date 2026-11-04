"""F51 step P3, the Choice form's time limit and the Events rows (``01`` §7, ``04`` §7.5; 07
I-8): AC-F51-25 (``read_choice``; a form closed unchanged writes nothing), 26
(``choice_patches``), 28 (Insert writes a timed menu that loads), 29 (Events rows), 30
(field hints, syntax colouring). No Tk."""

from dataclasses import replace

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.script.parser import parse_file
from engine.tools.editor import forms
from engine.tools.editor.fieldhints import CHOICE_HINTS
from engine.tools.editor.forms import (ChoiceItem, ChoiceValues, choice_lines, choice_patches,
                                       choice_problems, default_timeout, read_choice, rows)
from engine.tools.editor.syntax import TAG_KEYWORD, color_spans
from tests.script.helpers import parse_text
from tests.tools.editor.test_forms import _apply, _inline, _scene

TIMED = ('menu time 5:  # silence counts',
         '    hana "Say something!"',
         '    "I love you too.":',
         '        $ pass',
         '    "I need to think.":',
         '        jump think',
         '    "..." timeout:  # the quiet one',
         '        $ pass')
PLAIN = ('menu:  # silence counts',
         '    hana "Say something!"',
         '    "I love you too.":',
         '        $ pass',
         '    "I need to think.":',
         '        jump think',
         '    "...":  # the quiet one',
         '        $ pass')


def _marked(values: ChoiceValues, index: int | None) -> tuple[ChoiceItem, ...]:
    return tuple(replace(item, timeout=n == index) for n, item in enumerate(values.choices))


# --- AC-F51-25 — reading, and a form closed unchanged ---------------------------------------------

def test_ac25_read_choice_gives_time_and_timeout_and_unchanged_writes_nothing():
    read, lines = _inline(*TIMED)
    values = read_choice(read, 0)
    assert values.time == "5"
    assert [item.timeout for item in values.choices] == [False, False, True]
    assert choice_patches(read, 0, lines, values) == []
    plain, plain_lines = _inline(*PLAIN)
    untimed = read_choice(plain, 0)
    assert untimed.time == "" and not any(item.timeout for item in untimed.choices)
    assert choice_patches(plain, 0, plain_lines, untimed) == []
    decimal, decimal_lines = _inline("menu time 2.50:", '    "Go":', "        $ pass",
                                     '    "..." timeout:', "        $ pass")
    kept = read_choice(decimal, 0)
    assert kept.time == "2.50" and choice_patches(decimal, 0, decimal_lines, kept) == []


# --- AC-F51-26 — choice_patches ------------------------------------------------------------------

def test_ac26_patches_touch_only_the_menu_line_and_the_changed_headers():
    plain, plain_lines = _inline(*PLAIN)
    old = read_choice(plain, 0)
    rows_out = {}
    # Tick on: menu time 5: and the marker, comments kept.
    on = replace(old, time="5", choices=_marked(old, 2))
    rows_out["tick on"] = _apply(plain_lines, choice_patches(plain, 0, plain_lines, on))
    timed, timed_lines = _inline(*TIMED)
    was = read_choice(timed, 0)
    rows_out["change N"] = _apply(timed_lines, choice_patches(
        timed, 0, timed_lines, replace(was, time="7.5")))
    rows_out["change pick"] = _apply(timed_lines, choice_patches(
        timed, 0, timed_lines, replace(was, choices=_marked(was, 0))))
    rows_out["tick off"] = _apply(timed_lines, choice_patches(
        timed, 0, timed_lines, replace(was, time="", choices=_marked(was, None))))
    head = ["label t:"]
    body = [f"    {line}" for line in TIMED]
    assert rows_out["tick on"][:9] == head + body
    assert rows_out["change N"][:9] == head + [body[0].replace("time 5:", "time 7.5:")] + body[1:]
    picked = list(body)
    picked[2] = '        "I love you too." timeout:'
    picked[6] = '        "...":  # the quiet one'
    assert rows_out["change pick"][:9] == head + picked
    assert rows_out["tick off"][:9] == head + [f"    {line}" for line in PLAIN]
    # Only the lines that change are patched.
    assert [(p.first, p.last) for p in choice_patches(
        timed, 0, timed_lines, replace(was, time="7.5"))] == [(2, 2)]
    assert sorted((p.first, p.last) for p in choice_patches(
        timed, 0, timed_lines, replace(was, choices=_marked(was, 0)))) == [(4, 4), (8, 8)]
    # A timeout mark without a time is never written.
    untouched = replace(old, choices=_marked(old, 2))
    assert choice_patches(plain, 0, plain_lines, untouched) == []


# --- AC-F51-28 — Insert a timed Choice ------------------------------------------------------------

def test_ac28_inserted_timed_choice_parses_with_no_error():
    values = ChoiceValues("hana", "", "Say something!", (
        ChoiceItem("I love you too."), ChoiceItem("I need to think.", goes="think"),
        ChoiceItem("...", timeout=True)), time="5")
    lines = choice_lines(values, "    ", "    ")
    assert lines[0] == "    menu time 5:" and lines[6] == '        "..." timeout:'
    text = "label t:\n" + "\n".join(lines) + "\n    return\nlabel think:\n    return\n"
    parsed = parse_text(text)
    assert parsed.errors == [], parsed.messages
    menu = parsed.labels["t"].block[0]
    assert menu.time == 5.0 and [c.timeout for c in menu.choices] == [False, False, True]
    assert choice_problems(values) is None
    assert default_timeout(replace(values, choices=values.choices[:2] + (
        ChoiceItem("Kiss", condition="love > 3"),))) == 1
    assert choice_problems(replace(values, choices=_marked(values, None))) == (
        "Pick the option to choose when time runs out.")
    assert choice_problems(replace(values, choices=(
        ChoiceItem("Go"), ChoiceItem("...", condition="x", timeout=True)))) == (
        'The option chosen when time runs out can\'t have an "Only show when" condition. '
        "Clear its condition, or pick another option.")
    for bad in ("0", "61", "0.5", "five"):
        assert choice_problems(replace(values, time=bad)) == (
            "The time limit is 1 to 60 seconds."), bad


# --- AC-F51-29 — Events rows ----------------------------------------------------------------------

@pytest.mark.parametrize("time,ending", [("5", " · 5 seconds"), ("1", " · 1 second"),
                                         ("2.5", " · 2.5 seconds")])
def test_ac29_events_rows_show_the_time_and_the_timeout_choice(time, ending):
    read, lines = _inline(f"menu time {time}:", *TIMED[1:])
    found = [(row.depth, row.word, row.summary) for row in rows(read, lines)]
    plain, plain_lines = _inline(*PLAIN)
    untimed = rows(plain, plain_lines)[0].summary
    assert found[0][2] == untimed + ending and "second" not in untimed
    headers = {word: summary for depth, word, summary in found if word.startswith('"')}
    assert headers == {'"I love you too."': "", '"I need to think."': "",
                       '"..."': "when time runs out"}


# --- AC-F51-30 — field hints and syntax colouring --------------------------------------------------

def _keywords(line: str) -> list[str]:
    return [line[a:b] for a, b, tag in color_spans(line) if tag == TAG_KEYWORD]


def test_ac30_field_hints_and_syntax_colouring():
    assert CHOICE_HINTS["time"] == (
        "Give the player this many seconds to choose; a bar counts down above the options. "
        "Players who turned on Timing assist get twice as long, or no limit.")
    assert CHOICE_HINTS["timeout"] == (
        "The option chosen for the player when time runs out. It's always shown, so players "
        "without a time limit can still pick it.")
    assert _keywords("    menu time 5:") == ["menu", "time"]
    assert _keywords('        "..." timeout:  # quiet') == ["timeout"]
    assert _keywords('        "..." timeout :') == ["timeout"]
    assert _keywords('        "time timeout":') == []                # inside the quotes
    assert _keywords("    $ time = timeout") == []
    assert _keywords('    hana "timeout:"') == []
    assert _keywords("    menu:") == ["menu"]
