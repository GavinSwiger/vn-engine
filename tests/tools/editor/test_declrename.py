"""F47 P3-B: rename everywhere (``declrename``; ``04-technical.md`` P3-B; AC-F47-52).

One table: each Database kind renamed in a two-file story changes exactly its uses (one
``FilePlan``, so one undo step, per file), the Ask counts them and says what happens to
saves, and clashes, read-only files and broken files refuse the whole rename."""

import pytest

from engine.tools.editor import declarations as dec
from engine.tools.editor import declrename as dr
from engine.tools.editor.scriptedit import Ask, Refuse, apply_lines

DB = "script/database.vns"
MAIN = "script/main.vns"
DATABASE = '''define e = Character("Eileen")  # the hero
define hana = Character("Hana", image_tag="hana")
default score = 0
default who = "x"
define n = Character(name_from="who")
default persistent.seen = False
points trust 0 to 10
lock tip lanterns "Lanterns"
define fadeslow = Dissolve(1.0)
define room1 = ["a", "b"]
'''
STORY = '''label start:
    e "Hi {var=score}. score and e stay in the text."
    $ score += 1; e.name = "E"
    if score > 2 and points.trust > 1 and "lanterns" in codex.tips:
        hana "Fine."
    show hana smile at farleft with fadeslow
    points trust += score
    unlock tip lanterns
    menu:
        "Go" if persistent.seen and points["trust"]:
            pass
    minigame poem words=room1 into score
    # score e trust: comments stay
'''
CONFIG = '''[stage.positions]
farleft = 100
'''
TEXTS = {DB: DATABASE, MAIN: STORY}
P = {"farleft"}


def renamed(kind, old, new, texts=TEXTS, **kw):
    """The Ask's text, and each file's changed lines after the plan (ref → {line: text})."""
    question = dr.plan_rename(kind, old, new, texts, **kw)
    plan = dr.plan_rename(kind, old, new, texts, confirm=True, **kw)
    assert isinstance(question, Ask) and isinstance(plan, dr.RenamePlan), (question, plan)
    assert question.buttons == ("Rename", "Cancel") and question.escape == 1
    refs = [fp.ref for fp in plan.plan.files]
    assert len(refs) == len(set(refs))                  # one FilePlan (undo step) per file
    after = {**texts, CONFIG_REF: kw.get("config_text", "")}
    changed: dict[str, dict[int, str]] = {}
    for fp in plan.plan.files:
        old_lines = after[fp.ref].split("\n")
        new_lines = apply_lines(old_lines, fp.edits)
        assert len(new_lines) == len(old_lines) or fp.ref == CONFIG_REF
        changed[fp.ref] = {i + 1: line for i, (line, was) in
                           enumerate(zip(new_lines, old_lines)) if line != was}
    assert dr.verify_rename(plan, {**texts, CONFIG_REF: kw.get("config_text", "")},
                            kw.get("positions", ()))
    return question.text, changed


CONFIG_REF = dr.CONFIG_REF
SAVES = ("Saves made before this keep the old name, so in those saves `{}` starts again "
         "from its starting value.")

CASES = [
    (dec.VARIABLE, "score", "courage",
     "Rename `score` to `courage`? 6 places in 2 files will change. " + SAVES.format("courage"),
     {DB: {3: "default courage = 0"},
      MAIN: {2: '    e "Hi {var=courage}. score and e stay in the text."',
             3: '    $ courage += 1; e.name = "E"',
             4: '    if courage > 2 and points.trust > 1 and "lanterns" in codex.tips:',
             7: "    points trust += courage",
             12: "    minigame poem words=room1 into courage"}}),
    (dec.CHARACTER, "e", "eileen",
     "Rename `e` to `eileen`? 3 places in 2 files will change. Its pictures stay in images/e/.",
     {DB: {1: 'define eileen = Character("Eileen", image_tag="e")  # the hero'},
      MAIN: {2: '    eileen "Hi {var=score}. score and e stay in the text."',
             3: '    $ score += 1; eileen.name = "E"'}}),
    (dec.CHARACTER, "hana", "hanako",
     "Rename `hana` to `hanako`? 2 places in 2 files will change.",
     {DB: {2: 'define hanako = Character("Hana", image_tag="hana")'},
      MAIN: {5: '        hanako "Fine."'}}),          # show hana smile: the picture stays
    (dec.VARIABLE, "who", "player",
     "Rename `who` to `player`? 2 places in 1 file will change. " + SAVES.format("player"),
     {DB: {4: 'default player = "x"', 5: 'define n = Character(name_from="player")'}}),
    (dec.METER, "trust", "courage",
     "Rename `trust` to `courage`? 4 places in 2 files will change. " + SAVES.format("courage"),
     {DB: {7: "points courage 0 to 10"},
      MAIN: {4: '    if score > 2 and points.courage > 1 and "lanterns" in codex.tips:',
             7: "    points courage += score",
             10: '        "Go" if persistent.seen and points["courage"]:'}}),
    (dec.PERSISTENT, "seen", "met",
     "Rename `seen` to `met`? 2 places in 2 files will change. What the game remembered from "
     "earlier playthroughs keeps the old name, so `met` starts again from its starting value.",
     {DB: {6: "default persistent.met = False"},
      MAIN: {10: '        "Go" if persistent.met and points["trust"]:'}}),
    (dec.TIP, "lanterns", "lamps",
     "Rename `lanterns` to `lamps`? 3 places in 2 files will change. " + dr.CODEX_NOTE,
     {DB: {8: 'lock tip lamps "Lanterns"'},
      MAIN: {4: '    if score > 2 and points.trust > 1 and "lamps" in codex.tips:',
             8: "    unlock tip lamps"}}),
    (dec.TRANSITION, "fadeslow", "slow",
     "Rename `fadeslow` to `slow`? 2 places in 2 files will change.",
     {DB: {9: "define slow = Dissolve(1.0)"},
      MAIN: {6: "    show hana smile at farleft with slow"}}),
    (dr.DATA, "room1", "hall",
     "Rename `room1` to `hall`? 2 places in 2 files will change.",
     {DB: {10: 'define hall = ["a", "b"]'},
      MAIN: {12: "    minigame poem words=hall into score"}}),
]


@pytest.mark.parametrize(("kind", "old", "new", "text", "changes"), CASES,
                         ids=[f"{c[0]}-{c[1]}" for c in CASES])
def test_ac_f47_52_rename_everywhere_table(kind, old, new, text, changes):
    asked, changed = renamed(kind, old, new, positions={"farleft"})
    assert asked == text
    assert changed == changes


def test_ac_f47_52_positions_refusals_and_locks():
    # A position: the show line and config.toml's key, one undo step each.
    asked, changed = renamed(dec.POSITION, "farleft", "edge", positions={"farleft"},
                             config_text=CONFIG, taken={"farleft", "left"})
    assert asked == "Rename `farleft` to `edge`? 2 places in 2 files will change."
    assert changed[MAIN] == {6: "    show hana smile at edge with fadeslow"}
    assert "edge = 100" in changed[CONFIG_REF].values()
    assert dr.plan_rename(dec.POSITION, "left", "west", TEXTS, config_text=CONFIG) == \
        Refuse("`left` is a built-in position, so it keeps its name.")

    # Clashes: a declared name, an undeclared Python name, a bad name.
    clash = "There's already something called {}. Pick another name."
    assert dr.plan_rename(dec.VARIABLE, "score", "hana", TEXTS) == Refuse(clash.format("hana"))
    undeclared = {**TEXTS, MAIN: STORY.replace("pass", "$ gold = 1")}
    assert dr.plan_rename(dec.VARIABLE, "score", "gold", undeclared) == \
        Refuse(clash.format("gold"))
    assert dr.plan_rename(dec.VARIABLE, "score", "if", TEXTS).text.startswith("if can't")

    # A read-only file that uses it refuses the whole rename; one that doesn't is fine.
    assert dr.plan_rename(dec.VARIABLE, "score", "courage", TEXTS, positions=P,
                          locked={MAIN: "main.vns is read-only."}) == \
        Refuse("main.vns is read-only.", (MAIN, 1))
    assert isinstance(dr.plan_rename(dec.METER, "trust", "c", {**TEXTS, "script/x.vns": ""},
                                     locked={"script/x.vns": "x"}, positions=P), Ask)
    # A file with a problem that names it: fix it first.
    broken = {**TEXTS, "script/ch2.vns": "label two:\n    $ score = (\n"}
    found = dr.plan_rename(dec.VARIABLE, "score", "courage", broken, positions=P)
    assert isinstance(found, Refuse) and found.text.startswith("Fix the problem in `ch2.vns`")

    # Routes are their scenes' names; the same name is nothing to do.
    assert dr.plan_rename(dec.ROUTE, "bridge", "river", TEXTS) == Refuse(dr.ROUTE_REFUSED)
    assert dr.plan_rename(dec.VARIABLE, "score", "score", TEXTS) is None

    # The plan goes stale when a planned line changes.
    plan = dr.plan_rename(dec.VARIABLE, "score", "courage", TEXTS, confirm=True, positions=P)
    assert not dr.verify_rename(plan, {**TEXTS, MAIN: STORY.replace("score += 1", "x = 1")})


# --- Remembered across playthroughs (first-game fix, 2026-11-06) ---------------------------

REMEMBER_DB = "default knows_recipe = False  # learned at the bakery\ndefault coins = 0\n"
REMEMBER_STORY = '''label start:
    menu:
        "Ask about the recipe" if knows_recipe and coins:
            pass
    $ knows_recipe = True; e.knows_recipe = 1
    "knows_recipe stays in dialogue."
'''


def _swapped(name, remember, texts):
    question = dr.plan_remember(name, remember, texts)
    plan = dr.plan_remember(name, remember, texts, confirm=True)
    assert isinstance(question, Ask) and isinstance(plan, dr.RenamePlan), (question, plan)
    out = dict(texts)
    for fp in plan.plan.files:
        out[fp.ref] = "\n".join(apply_lines(texts[fp.ref].split("\n"), fp.edits))
    assert dr.verify_rename(plan, texts)
    return question, out


def test_remembering_a_variable_changes_its_default_and_every_use():
    texts = {DB: REMEMBER_DB, MAIN: REMEMBER_STORY}
    question, after = _swapped("knows_recipe", True, texts)
    assert question.text == ("Make `knows_recipe` remembered across playthroughs? 3 places in "
                             "2 files will change to `persistent.knows_recipe`. It starts from "
                             "its starting value in every game until the story sets it.")
    assert question.buttons == ("Change", "Cancel") and question.escape == 1
    assert after[DB].split("\n")[0] == ("default persistent.knows_recipe = False  "
                                        "# learned at the bakery")
    assert after[MAIN].split("\n")[2] == ('        "Ask about the recipe" if '
                                          "persistent.knows_recipe and coins:")
    assert after[MAIN].split("\n")[4] == ("    $ persistent.knows_recipe = True; "
                                          "e.knows_recipe = 1")
    assert after[MAIN].split("\n")[5] == '    "knows_recipe stays in dialogue."'

    question, back = _swapped("knows_recipe", False, after)        # and back again
    assert question.text.startswith("Make `knows_recipe` an ordinary story variable again? "
                                    "3 places in 2 files will change to `knows_recipe`.")
    assert back == texts


def test_forgetting_fixes_plain_uses_left_by_a_hand_edit():
    """W320's broken state: unticking makes the plain uses right again."""
    texts = {DB: "default persistent.knows_recipe = False\n", MAIN: REMEMBER_STORY}
    _question, after = _swapped("knows_recipe", False, texts)
    assert after[DB] == "default knows_recipe = False\n" and after[MAIN] == REMEMBER_STORY


def test_remembering_refuses_places_only_a_story_variable_fits():
    texts = {DB: REMEMBER_DB, MAIN: 'label start:\n    "You have {var=knows_recipe}."\n'}
    refused = dr.plan_remember("knows_recipe", True, texts, confirm=True)
    assert isinstance(refused, Refuse) and refused.place == (MAIN, 2)
    assert refused.text == ("`main.vns`, line 2 uses `knows_recipe` where only a story "
                            "variable fits ({var=…}, minigame … into, or name_from). Change "
                            "that line first.")
    clash = {DB: REMEMBER_DB + "default persistent.knows_recipe = True\n", MAIN: ""}
    assert isinstance(dr.plan_remember("knows_recipe", True, clash, confirm=True), Refuse)
