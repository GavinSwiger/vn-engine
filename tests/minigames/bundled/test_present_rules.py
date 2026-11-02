"""F25-1: the cross-examination's rules and declarations (F25 ``06``: AC-F25-01, 02, 04, 13).

Direct calls into ``present_rules`` (harness "Rules") with Story S and the base args
(Template E's line 19, defaults filled). The refusal texts are F25 ``01`` §5.3's drafts and
this module's forms for the rows the drafts leave open: a narrative-designer rewording
updates these tables, not the ACs. AC-F25-14 (fit against ``minigame_frame``) is F25-3's.
"""

import ast
import copy
import random
import re
import sys
from pathlib import Path

import pytest

from engine.core.minigame_types import REQUIRED, ArgSpec, Outcome, StoryNames
from engine.minigames import api, bundled, messages
from engine.minigames.bundled import present_evidence, present_rules, rule_text
from engine.minigames.bundled.poem_game import PoemGame
from engine.minigames.bundled.present_evidence import PresentEvidence
from engine.minigames.bundled.present_rules import (
    bar_geometry,
    ease_in_out,
    fixed_outcome,
    hatch_rects,
    judge,
    parse,
    picker_layout,
    problem,
    result_of,
    story_problem,
)
from engine.minigames.bundled.present_rules import testimony_layout as layout_of  # not a test
from tests.minigames.conftest import plugin, write

REPO = Path(__file__).resolve().parents[3]
BUNDLED_DIR = Path(bundled.__file__).parent
SIG = api.declarations(PresentEvidence, "engine").sig
S = StoryNames(meters=("credibility",), items=("brass_key", "festival_map", "shrine_photo"),
               tips=("lanterns",),
               item_categories=(("Evidence", ("brass_key", "festival_map")),
                                ("codex_items", ("shrine_photo",))))
SAYS = {"after_dark": "Nobody went near the shrine after dark.",
        "gate": "The gate was locked all night. I checked it myself.",
        "priest": "Only the priest has a key to that gate."}
WIN = {"action": "present", "statement": "gate", "evidence": "brass_key", "correct": True}


def base(**changes) -> dict:
    args = {"testimony": dict(SAYS), "answer": {"gate": "brass_key"}, "at": None,
            "speaker": "Daichi", "press": True, "evidence": None, "penalty": "credibility",
            "penalty_max": 5, "cost": 1}
    args.update(changes)
    return args


def check(args: dict, story: StoryNames = S) -> str | None:
    return problem(args) or story_problem(args, story)


def _ordered(v: object) -> object:
    if type(v) is dict:
        return [(k, _ordered(x)) for k, x in v.items()]
    if type(v) is list:
        return [_ordered(x) for x in v]
    return v


# --- AC-F25-01: declarations, imports, and codes ---------------------------------------------

def _imports(path: Path) -> set[str]:
    """Imports outside ``if TYPE_CHECKING:``."""
    found: set[str] = set()

    def visit(nodes):
        for node in nodes:
            if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
                continue
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.add(node.module)
            for field in ("body", "orelse", "handlers", "finalbody"):
                visit(getattr(node, field, []) or [])

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def test_ac_f25_01_declarations_imports_and_codes(game, load):
    # BUNDLED: PresentEvidence once, after PoemGame, from one import line (07 I-8).
    tree = ast.parse((BUNDLED_DIR / "__init__.py").read_text(encoding="utf-8"))
    modules = [n.module for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert modules.count("engine.minigames.bundled.present_evidence") == 1
    assert bundled.BUNDLED.count(PresentEvidence) == 1
    assert bundled.BUNDLED.index(PoemGame) < bundled.BUNDLED.index(PresentEvidence)
    # The signature.
    entry = api.declarations(PresentEvidence, "engine")
    assert (SIG.name, SIG.title, entry.api, entry.over_stage) == (
        "present_evidence", "Cross-Examination", "1.1", True)
    assert SIG.args == (ArgSpec("testimony", REQUIRED), ArgSpec("answer", REQUIRED),
                        ArgSpec("at", None), ArgSpec("speaker", None), ArgSpec("press", True),
                        ArgSpec("evidence", None), ArgSpec("penalty", None),
                        ArgSpec("penalty_max", 5), ArgSpec("cost", 1))
    assert SIG.test == SIG.skipped == Outcome(None)
    assert PresentEvidence.test_outcome == PresentEvidence.skipped_outcome == Outcome(None)
    assert SIG.check is not None and SIG.outcome is not None
    assert entry.tokens == {
        "statement.text_size": 28, "statement.text_color": "#1E6B34",
        "speaker.text_color": "panel.heading.text_color", "bar.fill_color": "#A02860",
        "bar.track_color": "#F0D0DE", "bar.loss_color": "#C62828", "press_sound": "",
        "present_sound": ""}
    assert entry.words == {
        "title": "Cross-Examination", "hint": "Press the witness, or present evidence.",
        "hint_no_press": "Present evidence that contradicts the statement.",
        "hint_picker": "Present evidence against: “{statement}”", "previous": "‹ Previous",
        "next": "Next ›", "press": "Press", "present": "Present", "back": "Back",
        "bar_label": "Credibility"}
    # The ast scan (PR-F25-01, C3).
    stdlib = set(sys.stdlib_module_names)
    rules_ok = {"engine.minigames.api", "engine.minigames.bundled.rule_text"}
    kit = {"engine.minigames.bundled", "engine.minigames.bundled.present_rules",
           "engine.ui.focus", "engine.ui.widgets", "engine.ui.paint", "engine.ui.nav",
           "engine.ui.layouts"}
    banned = re.compile(r"engine\.(runtime|script|app)\b|engine\.minigames\."
                        r"(host|loader|registry|context)\b")
    for name, allowed in (("rule_text", set()), ("present_rules", rules_ok),
                          ("present_evidence", rules_ok | kit)):
        found = _imports(BUNDLED_DIR / f"{name}.py")
        assert {m for m in found if m.split(".")[0] not in stdlib} <= allowed, name
        assert not [m for m in found if banned.match(m)], name
    # poem_rules imports the shared helpers instead of defining them (07 I-5).
    poem = ast.parse((BUNDLED_DIR / "poem_rules.py").read_text(encoding="utf-8"))
    defined = {n.name for n in poem.body if isinstance(n, ast.FunctionDef)} | {
        t.id for n in poem.body if isinstance(n, (ast.Assign, ast.AnnAssign))
        for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
        if isinstance(t, ast.Name)}
    shared = {"cut", "quoted", "value_echo", "kind_words", "line_problem"}
    assert not defined & shared
    assert "engine.minigames.bundled.rule_text" in _imports(BUNDLED_DIR / "poem_rules.py")
    # rule_text's text rule: form keys in order; breaks; edge; ZWJ; the printable fast path.
    rows = [((3, 1, 24), "not text"), (("", 1, 24), "empty"), (("x" * 25, 1, 24), "length"),
            (("a\nb", 1, 24), "breaks"), (("a‮b", 1, 24), "hidden"),
            ((" a", 1, 24), "edge"), (("a\n", 1, 24), "breaks"), (("   ", 1, 24), "edge"),
            (("a\nb\nc", 1, 300, 2), None), (("a\nb\nc", 1, 300, 1), "breaks"),
            (("hi\n", 1, 300, 4), "edge"), (("a\n\tb", 1, 300, 4), "hidden"),
            (("\U0001F469‍\U0001F4BB", 1, 24), None), (("中" * 24, 1, 24), None)]
    for i, (call, expected) in enumerate(rows):
        text, lo, hi, *breaks = call
        assert rule_text.line_problem(text, lo, hi, breaks=breaks[0] if breaks else 0) \
            == expected, i
    assert rule_text.LINE_FORMS == ("not text", "empty", "length", "breaks", "hidden", "edge")
    assert rule_text.hidden("​") and not rule_text.hidden("‍")
    # No F25 module uses the spare codes; CODES.md lists them.
    for name in ("rule_text", "present_rules", "present_evidence"):
        text = (BUNDLED_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"E28[5-7]|W17[45]", text), name
    codes_file = REPO / "specs" / "CODES.md"   # specs/ is kept out of the repository
    if codes_file.exists():
        codes = codes_file.read_text(encoding="utf-8")
        assert re.search(r"F25 Present evidence \| E285–E287 \| W173–W175", codes)
    # AC-F23-21's replacement row against the real BUNDLED.
    write(game, "minigames/my_trial.py", plugin("present_evidence"))
    loaded = load(game)
    assert loaded.result.ok and loaded.names.count("present_evidence") == 1
    assert loaded.result.registry.get("present_evidence").unit == "minigames/my_trial.py"
    assert loaded.warnings("W160") == [messages.w160_replaces("minigames/my_trial.py",
                                                              "present_evidence")]
    assert load(game, dev=False).warnings() == []


# --- AC-F25-02: R1–R14 ---------------------------------------------------------------------

def _random_value(rng: random.Random, depth: int = 0) -> object:
    roll = rng.randrange(9 if depth < 3 else 6)
    if roll == 0:
        return rng.choice([0, 1, -1, 5, 20, 21, 10**30, rng.randint(-10**6, 10**6)])
    if roll == 1:
        return rng.choice([0.0, 1.5, -2.25, 1e300])
    if roll == 2:
        return rng.choice([True, False, None])
    if roll in (3, 4, 5):
        alphabet = "aZ_ !\n​‍‮ßgatebrass_keyEvidence"
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
    if roll == 6:
        return [_random_value(rng, depth + 1) for _ in range(rng.randrange(0, 30))]
    if roll == 7:
        return {str(_random_value(rng, 3)): _random_value(rng, depth + 1)
                for _ in range(rng.randrange(0, 14))}
    return {k: _random_value(rng, depth + 1) for k in rng.sample(list(SAYS), 2)}


def test_ac_f25_02_the_checks():
    rule = "a statement is 1 to 120 characters on one line."
    r1 = ('testimony must be a dictionary of statements, e.g. {"gate": "The gate was '
          'locked."}, but it is ')
    r2 = "can't be a statement key; use letters, digits, and _, starting with a letter."
    r4 = ('answer must be a dictionary of statements and items, e.g. {"gate": "brass_key"}, '
          "but it is ")
    r6 = 'the answer for "gate" must be an item name or a list of 1 to 8 item names, but it is '
    r7 = "at must be None or a statement in testimony, but it is "
    r8 = "speaker must be None or a name of 1 to 24 characters on one line, but it is "
    r10 = 'evidence must be None or a list of 1 to 24 category names, e.g. ["Evidence"], but it is '
    cat = "; a category name is 1 to 24 characters on one line."
    pm = "penalty_max must be a whole number from 1 to 20, but it is "
    cost = "cost must be a whole number from 0 to penalty_max (5), but it is "
    hidden = f'the statement "gate" has a line break or hidden character; {rule}'
    x30 = "x" * 30 + "…"
    twelve = {f"s{i}": "x" for i in range(12)}
    rows = [
        # R1
        *[(base(testimony=v), r1 + end) for v, end in (
            (["a"], "a list."), ("x", "text."), (3, "a whole number."), (None, "None."))],
        (base(testimony={}), "testimony has 0 statements; a testimony has 1 to 12."),
        (base(testimony={f"s{i}": "x" for i in range(13)}),
         "testimony has 13 statements; a testimony has 1 to 12."),
        (base(testimony=twelve, answer={"s0": "brass_key"}), None),
        # R2
        *[(base(testimony={**SAYS, k: "x"}), f"{shown} {r2}") for k, shown in (
            ("the gate", '"the gate"'), ("1gate", '"1gate"'), ("a" * 33, f'"{"a" * 30}…"'),
            (3, "3"))],
        (base(testimony={**SAYS, "a" * 32: "x"}), None),
        # R3
        (base(testimony={**SAYS, "gate": ""}), f'the statement "gate" is empty; {rule}'),
        (base(testimony={**SAYS, "gate": "x" * 121}),
         f'the statement "gate" is 121 characters long; {rule}'),
        (base(testimony={**SAYS, "gate": 3}),
         f'the statement "gate" is a whole number, not text; {rule}'),
        *[(base(testimony={**SAYS, "gate": f"a{ch}b"}), hidden)
          for ch in ("\n", "\x00", "​", " ", "‮", "")],
        *[(base(testimony={**SAYS, "gate": t}),
           'the statement "gate" starts or ends with a space. Remove the space.')
          for t in (" gate", "gate ")],
        *[(base(testimony={**SAYS, "gate": t}), None)
          for t in ("x" * 120, "中" * 120, "\U0001F469‍\U0001F4BB")],
        # R4
        (base(answer="x"), r4 + "text."),
        (base(answer={}), "answer names 0 statements; an answer names 1 to 12."),
        (base(answer={f"s{i}": "brass_key" for i in range(13)}),
         "answer names 13 statements; an answer names 1 to 12."),
        # R5
        (base(answer={"gat": "brass_key"}),
         'answer names the statement "gat", which isn\'t in testimony. Did you mean "gate"?'),
        (base(answer={"zzz": "brass_key"}),
         'answer names the statement "zzz", which isn\'t in testimony.'),
        # R6
        (base(answer={"gate": 3}), r6 + "3."),
        (base(answer={"gate": []}), r6 + "[]."),
        (base(answer={"gate": ["brass_key"] * 9}), r6 + "['brass_key', 'brass_key', 'br…."),
        (base(answer={"gate": [3]}), r6 + "[3]."),
        (base(answer={"gate": ["brass_key"] * 8}), None),
        # R7
        (base(at="gat"), r7 + '"gat". Did you mean "gate"?'),
        (base(at="zzz"), r7 + '"zzz".'),
        (base(at=3), r7 + "3."),
        (base(at="priest"), None),
        # R8
        (base(speaker=""), r8 + '"".'),
        (base(speaker="W" * 25), r8 + f'"{"W" * 25}".'),
        (base(speaker=7), r8 + "7."),
        (base(speaker="Dai\nchi"), r8 + '"Dai chi".'),
        (base(speaker=" Daichi"), 'speaker " Daichi" starts or ends with a space. Remove the '
                                  "space."),
        (base(speaker="W" * 24), None),
        # R9
        (base(press="yes"), 'press must be True or False, but it is "yes".'),
        (base(press=1), "press must be True or False, but it is 1."),
        # R10
        (base(evidence="Evidence"), r10 + '"Evidence".'),
        (base(evidence=[]), "evidence lists 0 categories; it takes 1 to 24."),
        (base(evidence=["Evidence"] * 25), "evidence lists 25 categories; it takes 1 to 24."),
        (base(evidence=[""]), 'evidence names the category ""' + cat),
        (base(evidence=[3]), "evidence names the category 3" + cat),
        (base(evidence=["E" * 25]), f'evidence names the category "{"E" * 25}"' + cat),
        (base(evidence=["Evidence "]), 'evidence names the category "Evidence ", which starts '
                                       "or ends with a space. Remove the space."),
        (base(evidence=["Evidence"]), None),
        # R11
        (base(penalty=3), "penalty must be None or a meter's name, but it is 3."),
        *[(base(penalty_max=v), pm + shown) for v, shown in (
            (0, "0."), (21, "21."), (True, "True."), (5.0, "5.0."))],
        *[(base(cost=v), cost + shown) for v, shown in ((-1, "-1."), (6, "6."), (True, "True."))],
        (base(cost=5), None), (base(cost=0), None), (base(penalty_max=20), None),
        (base(penalty=None), None),
        # R12
        (base(answer={"gate": "brass_kye"}), 'the answer for "gate" is "brass_kye", but there '
                                             'is no item named "brass_kye". Did you mean '
                                             '"brass_key"?'),
        (base(answer={"gate": "lanterns"}), 'the answer for "gate" is "lanterns", which is a '
                                            "tip; only items can be presented."),
        (base(answer={"gate": ["brass_key", "zzz"]}), 'the answer for "gate" is "zzz", but '
                                                      'there is no item named "zzz".'),
        # R13
        (base(penalty="credibilty"), 'penalty is "credibilty", but there is no meter named '
                                     '"credibilty". Did you mean "credibility"?'),
        # R14: form 1; form 2 is unconditional (07 I-9). The `["codex_items"]` row answers
        # with an item in that category, since form 2 refuses brass_key there.
        (base(evidence=["Evidnce"]), 'evidence names the category "Evidnce", but no item is '
                                     'in a category by that name. Did you mean "Evidence"?'),
        (base(evidence=["codex_items"], answer={"gate": "shrine_photo"}), None),
        (base(evidence=["Evidence"], answer={"gate": "shrine_photo"}),
         'the answer for "gate" is "shrine_photo", which is in "codex_items", not in '
         "evidence, so it can never be presented."),
        (base(evidence=["Evidence", "codex_items"],
              answer={"gate": "shrine_photo", "priest": ["festival_map", "brass_key"]}), None),
        # Order
        (base(testimony={"a": "", "1b": "x"}), f'"1b" {r2}'),
        (base(answer={"zzz": "brass_key"}, cost=9),
         'answer names the statement "zzz", which isn\'t in testimony.'),
        (base(answer={"gate": "brass_kye"}, cost=9), cost + "9."),
        (base(answer={"gate": "brass_kye"}, penalty="credibilty"),
         'the answer for "gate" is "brass_kye", but there is no item named "brass_kye". '
         'Did you mean "brass_key"?'),
        (base(answer={"gate": ["yyy", "zzz"]}),
         'the answer for "gate" is "yyy", but there is no item named "yyy".'),
        # Echo cuts
        (base(testimony={**SAYS, "x" * 40: "x"}), f'"{x30}" {r2}'),
        (base(at="x" * 40), r7 + f'"{x30}".'),
    ]
    for i, (args, expected) in enumerate(rows):
        found = check(args)
        assert found == expected, i
        assert found is None or len(found) <= 200, i
    # Hostile values: a str or None, never raises, args unchanged, the same answer twice.
    rng = random.Random(25)
    for name in base():
        for _ in range(300):
            args = base(**{name: _random_value(rng)})
            before = _ordered(copy.deepcopy(args))
            answers = [(problem(args), story_problem(args, S)) for _ in range(2)]
            assert answers[0] == answers[1]
            assert all(a is None or type(a) is str for a in answers[0])
            assert _ordered(args) == before


# --- AC-F25-04: judging, results, and fixed outcomes ---------------------------------------

def _valid_args(rng: random.Random) -> dict:
    keys = rng.sample([f"s{i}" for i in range(20)], rng.randint(1, 12))
    answered = rng.sample(keys, rng.randint(1, len(keys)))
    names = list(S.items)
    answer = {k: (rng.choice(names) if rng.random() < 0.5
                  else rng.sample(names, rng.randint(1, 3))) for k in answered}
    return base(testimony={k: f"Statement {k}." for k in keys}, answer=answer,
                at=rng.choice([None, *keys]), press=rng.random() < 0.5,
                cost=rng.randint(0, 5))


def test_ac_f25_04_judging_results_and_fixed_outcomes():
    s0, s1, s2 = 0, 1, 2
    t = parse(base())
    assert (judge(t, s1, "brass_key"), result_of(t, s1, "brass_key")) == (True, WIN)
    assert list(result_of(t, s1, "brass_key")) == ["action", "statement", "evidence",
                                                    "correct"]
    assert judge(t, s1, "festival_map") is False
    assert result_of(t, s1, "festival_map") == {**WIN, "evidence": "festival_map",
                                                "correct": False}
    assert judge(t, s0, "brass_key") is False
    assert result_of(t, s0, "brass_key")["correct"] is False
    press = {"action": "press", "statement": "priest", "evidence": None, "correct": False}
    assert result_of(t, s2, None) == press and list(result_of(t, s2, None)) == list(press)
    both = parse(base(answer={"gate": "brass_key", "priest": ["festival_map", "brass_key"]}))
    assert judge(both, s1, "brass_key") and judge(both, s2, "brass_key")
    # fixed_outcome through sig.outcome, for both kinds.
    priest = {"action": "present", "statement": "priest", "evidence": "festival_map",
              "correct": True}
    for answer, expected in (
            ({"gate": "brass_key"}, Outcome(WIN, ())),
            ({"priest": ["festival_map", "brass_key"], "gate": "brass_key"}, Outcome(WIN, ())),
            ({"priest": ["festival_map", "brass_key"]}, Outcome(priest, ()))):
        args = base(answer=answer)
        assert SIG.outcome("test", args, S) == SIG.outcome("skipped", args, S) == expected
        assert fixed_outcome(parse(args)) == expected
    # Never None; exact built-ins, in key order.
    rng = random.Random(4)
    for _ in range(50):
        args = _valid_args(rng)
        assert problem(args) is None
        out = SIG.outcome("test", args, S)
        assert out is not None and out == SIG.outcome("skipped", args, S)
        assert type(out.result) is dict and out.changes == ()
        assert list(out.result) == ["action", "statement", "evidence", "correct"]
        assert [type(v) for v in out.result.values()] == [str, str, str, bool]
        assert out.result["correct"] is True and out.result["action"] == "present"


# --- AC-F25-13: layout and bar numbers ------------------------------------------------------

AREA_100 = (24, 24, 1232, 598)           # content (24, 24)–(1256, 622): one-line hint
AREA_150 = (24, 24, 1232, 532)           # content bottom 556: two-line hint at 150%
P100 = {"label_pitch": 34, "name_pitch": 45, "statement_pitch": 39, "button_h": 56}
P150 = {"label_pitch": 50, "name_pitch": 67, "statement_pitch": 59, "button_h": 75}


def test_ac_f25_13_layout_and_bar_numbers():
    from engine.ui import layouts               # the pitches are F10's (M20 numbers)
    for scale, pitches in ((1.0, P100), (1.5, P150)):
        assert pitches == {
            "label_pitch": layouts.pitch(layouts.scaled(24, scale)),
            "name_pitch": layouts.pitch(layouts.scaled(32, scale)),
            "statement_pitch": layouts.pitch(layouts.scaled(28, scale)),
            "button_h": layouts.button_height(scale=scale)}
    lay = layout_of(AREA_100, n_buttons=4, penalty=True, **P100)
    assert lay.panel == (24, 24, 432, 98) and lay.bar == (44, 82, 392, 24)
    assert lay.label_at == (44, 40) and lay.value_at == (436, 40)
    assert lay.box == (140, 332, 1000, 290)
    assert [b[0] for b in lay.buttons] == [164, 406, 648, 890]
    assert all(b[2:] == (226, 56) and b[1] + 28 == 598 - 28 for b in lay.buttons)
    assert lay.statement == (164, 332 + 24 + 45 + 8, 952, 117)
    assert lay.name_at == (164, 356) and lay.count_at == (1116, 356)
    for n, xs in ((3, [285, 527, 769]), (2, [406, 648]), (1, [527])):
        assert [b[0] for b in layout_of(AREA_100, n_buttons=n, penalty=True,
                                               **P100).buttons] == xs
    bare = layout_of(AREA_100, n_buttons=4, penalty=False, **P100)
    assert bare.panel is None and bare.box == lay.box
    big = layout_of(AREA_150, n_buttons=4, penalty=True, **P150)
    assert (big.box[1], big.box[1] + big.box[3]) == (165, 556)
    assert big.panel[1] + big.panel[3] == 138 <= big.box[1]
    # The picker.
    for area, bh, bottom, view_h in ((AREA_100, 56, 622, 566), (AREA_150, 75, 556, 500)):
        pick = picker_layout(area, button_h=bh)
        assert pick.backing == (220, 24, 840, bottom - 24)
        assert pick.view == (236, 40, 808, view_h)
        assert pick.back == (24, bottom - bh, 180, bh)
    # The bar.
    bar = (44, 82, 392, 24)
    for value, width in ((4, 313.6), (-3, 0), (9, 392)):
        fill, notches = bar_geometry(bar, value, 5)
        assert fill[:2] == (44, 82) and fill[3] == 24 and abs(fill[2] - width) < 1e-9
        assert len(notches) == 4
        for k, (x, y, w, h) in enumerate(notches, start=1):
            assert (w, y, h) == (2, 82, 24) and x <= 44 + 78.4 * k <= x + w
    assert len(bar_geometry(bar, 3, 10)[1]) == 9 and bar_geometry(bar, 3, 11)[1] == ()
    # The hatch.
    for seg in (bar, (44, 82, 78.4, 24), (357.6, 82, 78.4, 24)):
        x, y, w, h = seg
        rects = hatch_rects(seg)
        assert 0 < len(rects) <= 420
        assert all(r[2:] == (3, 3) and x <= r[0] and r[0] + 3 <= x + w and y <= r[1]
                   and r[1] + 3 <= y + h for r in rects)
    assert hatch_rects((44, 82, 0, 24)) == ()
    assert [ease_in_out(t) for t in (0, 0.5, 1)] == pytest.approx([0, 0.5, 1])
