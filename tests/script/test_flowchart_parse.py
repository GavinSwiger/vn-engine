"""F20 s1 — the ``flowchart`` line (F20 ``06-acceptance.md`` AC-F20-01, 02, 04; ``02-script.md``
§3; ``04-technical.md`` §6.1, §6.3, §6.4).

Message texts are checked by the F20 rows of ``tests/fixtures/F02/messages/cases.toml``
(``test_messages.py``, the golden ``expected.txt``); here each AC-F20-02 row is one problem
with its code, through the single-file parse."""

import logging

import engine.script  # noqa: F401  registers every statement
from engine.core.paths import GamePaths
from engine.runtime.commands import Say
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import GameState, reserved_since_save
from engine.script import LoadOptions, load_story
from engine.script.flowchart import Flowchart
from engine.script.words import STATEMENT_WORDS, STATEMENT_WORDS_F02
from tests.runtime.effects_story import started, story_game
from tests.script.helpers import parse_text, template, template_l
from tests.script.test_messages import CASES


def _node(line: str) -> Flowchart:
    parsed = parse_text(template(S=line))
    assert parsed.errors == [], [e.format() for e in parsed.errors]
    node = parsed.labels["start"].block[1]
    assert isinstance(node, Flowchart)
    return node


# --- AC-F20-01 — flowchart lines parse ---------------------------------------------------------

def test_ac_f20_01_flowchart_lines_parse(tmp_path):
    rows = [  # line, form, title, hidden, no_jump, target
        ('flowchart scene "Daichi\'s Stall"', "scene", "Daichi's Stall", False, False, None),
        ('flowchart scene "The Promise" hidden no jump', "scene", "The Promise", True, True,
         None),
        ('flowchart scene "A" no jump hidden', "scene", "A", True, True, None),
        ('flowchart "Where?"', "mark", "Where?", False, False, None),
        ("flowchart", "mark", None, False, False, None),
        ("flowchart hidden", "mark", None, True, False, None),
        ("flowchart no jump", "mark", None, False, True, None),
        ('flowchart "Say {{hi}"', "mark", "Say {hi}", False, False, None),
        ("flowchart omit", "omit", None, False, False, None),
        ("flowchart forget", "forget", None, False, False, None),
        ("flowchart forget river", "forget", None, False, False, "river"),
    ]
    for line, form, title, hidden, no_jump, target in rows:
        node = _node(line)
        assert (node.form, node.title, node.hidden, node.no_jump, node.target) == \
            (form, title, hidden, no_jump, target), line
        expected = (("flowchart", "forget", target or "") if form == "forget"
                    else ("flowchart", form))
        assert node.identity_key() == expected, line
    # A title or a flag never changes the identity.
    assert _node('flowchart "A" hidden').identity_key() == _node("flowchart").identity_key()
    # Each line runs as a step and releases nothing: the run equals the one without them.
    marked = ['flowchart scene "Opening" hidden', 'hana "1"', "flowchart omit", "menu:",
              '    "Go":', "        flowchart forget", "        flowchart forget start",
              '        hana "After."']
    plain = [line for line in marked if "flowchart" not in line]
    runs = []
    for name, lines in (("marked", marked), ("plain", plain)):
        commands = run_headless(story_game(tmp_path / name, lines), seed=42,
                                inputs=["advance", "choose 1", "advance"])
        runs.append([(type(c).__name__, c.text if type(c) is Say else None)
                     for c in commands])
    assert runs[0] == runs[1] and ("Say", "After.") in runs[0]
    # omit, forget, hidden, and no stay names.
    for edit in ({"T": "default hidden = 1⏎default no = 2⏎label forget:⏎[4]return"},
                 {"S": "$ omit = 3"}):
        parsed = parse_text(template(**edit))
        assert parsed.errors == [], edit
    # Not VOICE_TRANSPARENT: a voice above a flowchart line gets W20, as above any statement.
    game = tmp_path / "voice"
    (game / "script").mkdir(parents=True)
    (game / "script" / "main.vns").write_text(template_l(
        S='voice "voice/x.ogg"⏎[4]flowchart hidden'), encoding="utf-8")       # menu: below
    result = load_story(GamePaths(game.resolve()), LoadOptions(dev=True))
    assert result.errors == ()
    assert [w.code for w in result.warnings] == ["W20"]


# --- AC-F20-02 — parse messages E260 and E263 --------------------------------------------------

AC02_ROWS = [
    ("flowchart hiden", "E260"), ("flowchart nojump", "E260"), ("flowchart no_jump", "E260"),
    ("flowchart zzz", "E260"), ("flowchart scene", "E260"), ("flowchart scene hidden", "E260"),
    ('flowchart hidden "T"', "E260"), ('flowchart scene "A" hidden "B"', "E260"),
    ('flowchart "A" "B"', "E260"), ('flowchart "A" hidden hidden', "E260"),
    ("flowchart omit hidden", "E260"), ("flowchart forget river now", "E260"),
    ('flowchart "A":⏎[8]"Under it."', "E260"), ("flowchart no", "E260"),
    ("flowchart no hidden", "E260"), ('flowchart ""', "E263"),
    ('flowchart "' + "😀" * 121 + '"', "E263"), ('flowchart "Say {b}hi{/b}"', "E263"),
    ('flowchart "{var=x}"', "E263"), ('flowchart "a { b"', "E263"),
]


def test_ac_f20_02_parse_messages():
    for line, code in AC02_ROWS:
        parsed = parse_text(template(S=line))
        assert parsed.codes == [code] and parsed.errors[0].line == 5, (line, parsed.messages)
    # Exact texts: the F20 rows of cases.toml (E260 and E263, each form).
    assert {c.code for c in CASES if c.ac == "AC-F20-02" and c.code != "-"} == {"E260", "E263"}
    for title in ("😀" * 120, "灯" * 120, "א" * 120):
        assert _node(f'flowchart "{title}"').title == title


# --- AC-F20-04 — the reserved word ---------------------------------------------------------------

def test_ac_f20_04_the_reserved_word(tmp_path, caplog):
    assert len(STATEMENT_WORDS) == 41 and "flowchart" in STATEMENT_WORDS      # F32: ui
    assert "flowchart" not in STATEMENT_WORDS_F02 and len(STATEMENT_WORDS_F02) == 38
    for edit in ({"T": 'define flowchart = Character("F")'}, {"T": "label flowchart:⏎[4]return"},
                 {"T": "default flowchart = 1"}):
        parsed = parse_text(template(**edit))
        assert parsed.codes == ["E60"], (edit, parsed.messages)
    # "$ flowchart = 1" loads clean, like "$ rollback = 1" and "$ menu = 1": F03's $ bindings
    # never give E60 (F14's AC-F14-16 housekeeping; QA note for AC-F20-04's row).
    game = tmp_path / "dollar"
    (game / "script").mkdir(parents=True)
    (game / "script" / "main.vns").write_text(template(S="$ flowchart = 1"), encoding="utf-8")
    assert load_story(GamePaths(game.resolve()), LoadOptions()).errors == ()
    parsed = parse_text(template(S="flowchrt hidden"))
    assert [e.message for e in parsed.errors] == [
        '"flowchrt" is not a statement. Did you mean "flowchart"?']
    # A save from before F20 whose variables hold "flowchart" loads; restore drops it.
    assert [reserved_since_save(n) for n in ("flowchart", "Flowchart", "flowcharts")] == [
        True, True, False]
    program = story_game(tmp_path / "var", ['hana "1"'])
    interp, _ = started(program)
    data = interp.checkpoint().to_json()
    data["variables"].update({"flowchart": 3, "kept": 2})
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="vn"):
        assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert dict(interp.checkpoint().variables) == {"kept": 2}
    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert record.getMessage() == ('Restored state: "flowchart" is a reserved word in this '
                                   "version of the game, so the saved value was dropped.")
