"""F09 step 1 — ``with`` clauses, ``shake``, ``flash``, and ``pause`` at load
(``engine/script/effects.py``; F09 ``04-technical.md`` §5.1): AC-F09-01 and AC-F09-02. The
load errors E192–E198 are ``cases.toml`` rows (AC-F09-03), run by ``test_messages.py``."""

from engine.script.effects import Flash, Pause, Shake, WithClause
from engine.script.stage import Hide, Scene, Show
from tests.script.helpers import parse_text


def statement(line: str):
    parsed = parse_text(f"label start:\n    {line}\n")
    assert parsed.errors == [], parsed.messages
    (label,) = parsed.nodes
    (stmt,) = label.block
    return stmt


def clause(line: str) -> tuple:
    c = statement(line).with_clause
    assert isinstance(c, WithClause) and (c.line, c.column) == (2, line.index(" with ") + 6)
    return c.name, c.seconds, c.color


# --- AC-F09-01 — with clauses parse -------------------------------------------------------------

WITH_ROWS = [
    ("scene bg sea with fade", ("fade", None, None)),
    ("show hana sad with dissolve 0.3", ("dissolve", 0.3, None)),
    ("hide hana with dissolve", ("dissolve", None, None)),
    ("scene bg sea with fade 2.0 white", ("fade", 2.0, "#FFFFFF")),
    ("scene bg sea with fade white 2.0", ("fade", 2.0, "#FFFFFF")),
    ('scene bg sea with fade 0.4 "#ffe08a"', ("fade", 0.4, "#FFE08A")),
    ('scene bg sea with fade "#FFE08A" 0.4', ("fade", 0.4, "#FFE08A")),
    ("scene bg sea with fade red", ("fade", None, "#FF0000")),           # G1, 07 I-9
    ("scene bg sea with fade black", ("fade", None, "#000000")),
    ("show hana at left with cut", ("cut", None, None)),
    ("show hana with dissolve 0", ("dissolve", 0, None)),
    ("show hana with dissolve 30", ("dissolve", 30, None)),
    ("show hana with lantern 0.8", ("lantern", 0.8, None)),
    ("show hana with lantern white", ("lantern", None, "#FFFFFF")),      # a define: launch decides
    ("show hana with 灯", ("灯", None, None)),
]


def test_ac01_with_clauses():
    for line, expected in WITH_ROWS:
        assert clause(line) == expected, line
    assert type(statement("scene bg sea with fade")) is Scene
    assert type(statement("show hana with fade")) is Show
    assert type(statement("hide hana with fade")) is Hide
    assert statement("show hana").with_clause is None
    # identity keys leave out the with clause (2.6 of 07: F04-era sids are unchanged)
    assert statement("show hana sad with dissolve 0.3").identity_key() == (
        statement("show hana sad").identity_key())
    assert statement("scene bg sea with fade").identity_key() == ("scene", "bg sea")


# --- AC-F09-02 — shake, flash, pause parse ----------------------------------------------------

SHAKE_ROWS = [
    ("shake", (None, None, None)),
    ("shake large", ("large", None, None)),
    ("shake small horizontal 2.0", ("small", "horizontal", 2.0)),
    ("shake 2.0 vertical medium", ("medium", "vertical", 2.0)),
    ("shake 0.1", (None, None, 0.1)),
    ("shake 10", (None, None, 10)),
]
FLASH_ROWS = [
    ("flash", (None, None)),
    ("flash red", ("#FF0000", None)),
    ('flash "#ffe08a" 0.6', ("#FFE08A", 0.6)),
    ("flash 0.6 white", ("#FFFFFF", 0.6)),
    ("flash 0.1", (None, 0.1)),
    ("flash 2", (None, 2)),
]
PAUSE_ROWS = [("pause", None), ("pause 1.5", 1.5), ("pause 0.1", 0.1), ("pause 30", 30)]


def test_ac02_shake_flash_pause():
    for line, expected in SHAKE_ROWS:
        node = statement(line)
        assert type(node) is Shake and (node.size, node.direction, node.seconds) == expected, line
        assert node.identity_key() == ("shake",), line
    for line, expected in FLASH_ROWS:
        node = statement(line)
        assert type(node) is Flash and (node.color, node.seconds) == expected, line
        assert node.identity_key() == ("flash",), line
    for line, seconds in PAUSE_ROWS:
        node = statement(line)
        assert type(node) is Pause and node.seconds == seconds, line
        assert node.identity_key() == ("pause",), line


OTHER_FORMS = [
    ("shake:", "E110"), ("flash:", "E110"), ("pause:", "E110"),
    ("shake 2s", "E195"), ("pause soon", "E197"), ("pause 1 2", "E197"),
    ("flash 0.5 0.6", "E196"), ("shake small horizontal vertical", "E195"),
    ("show hana with", "E113"), ("show hana with dissolve at left", "E115"),
]


def test_other_forms():
    for line, code in OTHER_FORMS:
        parsed = parse_text(f"label start:\n    {line}\n")
        assert parsed.codes == [code], (line, parsed.messages)
