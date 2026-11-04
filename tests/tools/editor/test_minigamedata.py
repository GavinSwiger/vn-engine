"""F47 P2-E: minigame setup data (``minigamedata``; AC-F47-42, 43, 44, 46). Pure: no Tk.

The data shapes come from ``docs/minigames.md`` itself, so a docs change that Studio can't
read back fails here. The rules modules (``engine/minigames/bundled/*_rules.py``) and the
bundled plugin classes are imported here only: Studio may not import them (ADR-0008), so
``minigamedata`` mirrors their data checks and argument tables, and these tests compare
them case by case. The room's model is tested too (for W8's room canvas, AC-F47-45).
"""

import dataclasses
import inspect
from pathlib import Path

import pytest

from engine.minigames.api import REQUIRED
from engine.minigames.bundled import (ask_text, code_lock, gift_giving, gift_rules,
                                      hand_game,
                                      heartbeat, lock_rules,
                                      phone_chat, phone_rules, poem_game, poem_rules,
                                      present_evidence, present_rules, puzzle_room, room_rules,
                                      stay_still)
from engine.tools.editor import declplan
from engine.tools.editor import minigamedata as md
from engine.tools.editor.scriptedit import Refuse, apply_lines

REPO = Path(__file__).resolve().parents[3]
REF = "script/story.vns"


def _docs_blocks() -> list[str]:
    """Every fenced block of docs/minigames.md, as a script text."""
    blocks, cur = [], None
    for line in (REPO / "docs" / "minigames.md").read_text("utf-8").split("\n"):
        if line.startswith("```"):
            if cur is None:
                cur = []
            else:
                blocks.append("\n".join(cur) + "\n")
                cur = None
        elif cur is not None:
            cur.append(line)
    return blocks


def _docs_text(*names: str) -> str:
    """The docs block that defines all of ``names``."""
    for block in _docs_blocks():
        if all(f"define {n} = " in block for n in names):
            return block
    raise AssertionError(f"docs/minigames.md has no block defining {names}")


def _sets(text: str) -> dict[str, md.DataSet]:
    return {ds.name: ds for ds in md.scan({REF: text})}


def _apply(plan: md.DataPlan, texts: dict[str, str]) -> dict[str, str]:
    """What the window does: verify against the live texts, then apply each file plan."""
    assert md.verify(plan, texts)
    out = dict(texts)
    for file_plan in plan.plan.files:
        out[file_plan.ref] = "\n".join(apply_lines(out[file_plan.ref].split("\n"),
                                                   file_plan.edits))
    return out


def _outside(text: str, ds: md.DataSet) -> list[str]:
    lines = text.split("\n")
    return lines[:ds.first - 1] + lines[ds.last:]


# --- AC-F47-42 ---------------------------------------------------------------------------------

def test_poem_words_table_round_trips_the_docs_define():
    """AC-F47-42: each poem ``define`` in docs/minigames.md reads into a table (one row per
    word, one column per meter) and writes back byte-identical; unchanged, nothing is
    written; an edited table is written as the docs lay it out, read back the same, kept
    where the shorthand rows weren't touched, and accepted by the poem rules."""
    for name in ("day1_words", "day2_words"):
        text = _docs_text(name)
        ds = _sets(text)[name]
        assert (ds.kind, ds.used, ds.guessed) == (md.POEM, (("poem_game", "words"),), False)
        assert tuple(md.define_lines(md.POEM, name, ds.model)) == ds.lines
        assert md.plan_edit(ds, ds.model, {REF: text}) is None

    text = _docs_text("day1_words")
    ds = _sets(text)["day1_words"]
    model = ds.model
    meters = md.poem_meters(model, ("sayori", "natsuki", "yuri"))
    assert meters == ("sayori", "natsuki", "yuri")
    rows = {row.word: row for row in model.words}
    table = {row.word: tuple(md.poem_points(row, m) for m in meters) for row in model.words}
    cases = [  # (word, cells read as) — shorthand, dict, empty
        ("whisper", (0, 0, 1)), ("sunshine", (3, 1, 0)), ("pencil", (0, 0, 0))]
    for word, cells in cases:
        assert table[word] == cells
    assert rows["whisper"].short and md.poem_set(rows["whisper"], "yuri", 1) is rows["whisper"]

    edited = [md.poem_set(row, "natsuki", 2) if row.word == "candy" else row
              for row in model.words]
    edited = [md.poem_set(row, "sayori", 1) if row.word == "pencil" else row for row in edited]
    edited.append(md.poem_set(md.PoemWord("thunder"), "yuri", 3))
    new = md.PoemWords(tuple(edited))
    plan = md.plan_edit(ds, new, {REF: text})
    assert isinstance(plan, md.DataPlan) and plan.plan.title == "Change poem words day1_words"
    after = _apply(plan, {REF: text})[REF]
    again = _sets(after)["day1_words"]
    assert again.model == new
    assert '    "whisper": "yuri",' in again.lines and '    "candy": {"natsuki": 2},' in again.lines
    assert again.lines[-2:] == ('    "thunder": {"yuri": 3},', "    }")
    assert _outside(after, again) == _outside(text, ds)
    assert poem_rules.problem({"words": md.value_of(md.POEM, new), "rounds": 4,
                               "page_words": 8}) is None      # the docs line's arguments

    bad = md.PoemWords(new.words + (md.poem_set(md.PoemWord("Candy"), "yuri", 1),))
    assert md.plan_edit(ds, bad, {REF: text}) == Refuse(md.SAME_TWICE.format(
        what='The word "Candy"'))
    stale = text.replace('"candy": {"natsuki": 3}', '"candy": {"natsuki": 1}')
    assert not md.verify(plan, {REF: stale})


# --- AC-F47-43 ---------------------------------------------------------------------------------

def test_evidence_editor_round_trips_testimony_and_answer():
    """AC-F47-43: the docs' testimony and answer read as one evidence list (statement,
    "contradicted by"), write back byte-identical, and an edit rewrites only the define
    whose values changed; a testimony with no answer yet gets one after it."""
    text = _docs_text("daichi_says", "daichi_answer")
    texts = {REF: text}
    sets = _sets(text)
    says, answer = sets["daichi_says"], sets["daichi_answer"]
    assert (says.kind, answer.kind) == (md.TESTIMONY, md.ANSWER)
    assert md.answer_name("daichi_says", texts) == "daichi_answer"
    for ds in (says, answer):
        assert tuple(md.define_lines(ds.kind, ds.name, ds.model)) == ds.lines
    evidence = md.evidence_of(says.model, answer.model)
    assert [(s.key, s.items) for s in evidence.statements] == [
        ("after_dark", ()), ("gate", ("brass_key",)), ("priest", ())]
    assert md.plan_evidence(says, answer, evidence, texts) is None

    cases = [  # (edit, defines rewritten)
        ("text", ("daichi_says",)),
        ("items", ("daichi_answer",)),
        ("both", ("daichi_says", "daichi_answer"))]
    for edit, rewritten in cases:
        statements = list(evidence.statements)
        if edit in ("text", "both"):
            statements[2] = md.Statement("priest", "Only the priest has a key.", ())
            statements.append(md.Statement(md.slug("I heard nothing.", ["gate"]),
                                           "I heard nothing."))
        if edit in ("items", "both"):
            statements[1] = md.Statement("gate", statements[1].text,
                                         ("brass_key", "shrine_photo"))
        new = md.Evidence(tuple(statements))
        plan = md.plan_evidence(says, answer, new, texts)
        assert isinstance(plan, md.DataPlan), edit
        assert tuple(name for _, name, _ in plan.writes) == rewritten
        after = _apply(plan, texts)[REF]
        again = _sets(after)
        assert md.evidence_of(again["daichi_says"].model, again["daichi_answer"].model) == new
        t_value, a_value = md.evidence_values(new)
        assert present_rules.problem({"testimony": t_value, "answer": a_value}) is None
        for name in ("daichi_says", "daichi_answer"):
            if name not in rewritten:
                assert again[name].lines == sets[name].lines
    assert again["daichi_answer"].lines == (
        'define daichi_answer = {"gate": ["brass_key", "shrine_photo"]}',)

    alone = text.replace('define daichi_answer = {"gate": "brass_key"}\n', "")
    lone = _sets(alone)["daichi_says"]
    new = md.Evidence(tuple(md.Statement(s.key, s.text, s.items) for s in evidence.statements))
    plan = md.plan_evidence(lone, None, new, {REF: alone})
    after = _apply(plan, {REF: alone})[REF]
    assert after == text.replace("define daichi_answer", "define daichi_says_answer")
    assert md.plan_evidence(lone, None, md.Evidence(evidence.statements[:1]),
                            {REF: alone}) == Refuse(md.NO_ANSWER)


# --- AC-F47-44 ---------------------------------------------------------------------------------

EVERY_STEP = (
    md.Step(md.TIME, "7:02 AM"),
    md.Step(md.FROM_CONTACT, "morning!!\nare you up"),
    md.Step(md.FROM_ME, "Barely."),
    md.Step(md.FROM_OTHER, "Who added me?", "Natsuki"),
    md.AskStep("plan", (
        md.Reply("walk", "Walk with me?", (
            md.Step(md.FROM_CONTACT, "yes!!"), md.Step(md.FROM_ME, "Corner, ten minutes."),
            md.Step(md.FROM_OTHER, "Ugh.", "Natsuki"), md.Step(md.TIME, "7:05 AM"))),
        md.Reply("bus", "I'll take the bus.")), True),
    md.AskStep("snack", (md.Reply("yes", "Sure."), md.Reply("no", "No thanks.")), "Leave it"),
    md.AskStep("quiet", (md.Reply("ok", "Ok."),), False),
    md.AskStep("last", (md.Reply("bye", "Bye!"), md.Reply("later", "Later."))),
)


def test_phone_chat_steps_round_trip_every_kind():
    """AC-F47-44: every step kind (from contact, me, someone else, time, reply point) with
    nested follow-ups and each "Don't reply" form (True, own words, False, none) writes
    and reads back the same; the docs' chats come back byte-identical; edits keep the
    rest of the file; the phone rules accept what is written."""
    text = _docs_text("late_chat")
    for name, block in (("late_chat", text), ("walk_chat", _docs_text("walk_chat"))):
        ds = _sets(block)[name]
        assert ds.kind == md.CHAT and md.plan_edit(ds, ds.model, {REF: block}) is None
        assert tuple(md.define_lines(md.CHAT, name, ds.model)) == ds.lines
    late = _sets(text)["late_chat"]
    awake = late.model[2]
    assert isinstance(awake, md.AskStep) and awake.ignore is True
    assert [(r.key, len(r.follow)) for r in awake.replies] == [("yes", 2), ("sleep", 1)]

    cases = [  # (title, chat)
        ("every kind", EVERY_STEP),
        ("ignore words", late.model[:2] + (md.AskStep(awake.name, awake.replies, "Leave it"),)
         + late.model[3:]),
        ("follow-up added", late.model[:5] + (md.AskStep("walk", (
            md.Reply("sure", "Sure.", (md.Step(md.FROM_CONTACT, "yay"),)),
            md.Reply("busy", "Can't.")), None),) + late.model[6:]),
    ]
    for title, chat in cases:
        assert md.problem(md.CHAT, chat) is None, title
        assert phone_rules.problem({"chat": md.value_of(md.CHAT, chat),
                                    "contact": "Sayori"}) is None, title
        assert md.read_value(md.CHAT, md.value_of(md.CHAT, chat)) == chat, title
        plan = md.plan_edit(late, chat, {REF: text})
        after = _apply(plan, {REF: text})[REF]
        again = _sets(after)["late_chat"]
        assert again.model == chat and _outside(after, again) == _outside(text, late), title

    texts = {"script/main.vns": "label start:\n    return\n"}
    plan = md.plan_new(md.CHAT, "morning_chat", EVERY_STEP, texts)
    assert plan.create == declplan.DATABASE_REF
    texts[declplan.DATABASE_REF] = declplan.DATABASE_HEADER
    after = _apply(plan, texts)
    assert after["script/main.vns"].startswith('include "database.vns"')
    made = _sets(after[declplan.DATABASE_REF])
    assert made["morning_chat"].model == EVERY_STEP and made["morning_chat"].guessed
    nested = md.AskStep("x", (md.Reply("a", "A.", (md.Step(md.FROM_ME, " hi"),)),))
    assert isinstance(md.plan_edit(late, (nested,), {REF: text}), Refuse)


# --- AC-F47-46 ---------------------------------------------------------------------------------

def test_minigame_form_fields_come_from_plugin_args():
    """AC-F47-46: the Minigame form lists installed games; its fields are the plugin's
    declared args (a bundled one's table, or a game plugin read from its source: the
    example game's lantern_memory); required args pick a data set of that game, optional
    ones show their default; "into" picks a variable. The line reads and writes back."""
    plugin = (REPO / "game" / "minigames" / "lantern_memory.py").read_text("utf-8")
    plugins = {"minigames/lantern_memory.py": plugin}
    assert md.games(plugins) == md.BUNDLED + ("lantern_memory",)
    poem = _docs_text("day1_words")
    room = _docs_text("attic")
    sets = md.scan({REF: poem, "script/room.vns": room})

    cases = [  # (game, [(arg, required, widget, default text)], data choices of arg 0)
        ("poem_game", [("words", True, md.DATA, ""), ("rounds", False, md.NUMBER, "20"),
                       ("page_words", False, md.NUMBER, "10"),
                       ("to_points", False, md.TOGGLE, "True"),
                       ("result", False, md.CHOICE, '"winner"')], ("day1_words",)),
        ("phone_chat", [("chat", True, md.DATA, ""), ("contact", True, md.TEXT, ""),
                        ("time", False, md.TEXT, "None")], ()),
        ("puzzle_room", [("room", True, md.DATA, ""), ("state", False, md.VARIABLE, "None")],
         ("attic",)),
        ("lantern_memory", [("pairs", True, md.DATA, ""), ("hints", False, md.TOGGLE, "False")],
         ("day1_words", "attic")),
    ]
    for game, fields, choices in cases:
        form = md.form_fields(game, plugins)
        assert [(f.name, f.required, f.widget, f.default_text) for f in form.fields] == fields
        assert md.data_choices(form.fields[0], sets) == choices, game
        assert (form.into.name, form.into.widget, form.into.label) == (
            "into", md.VARIABLE, md.INTO_LABEL)
    assert md.form_fields("no_such_game", plugins) is None

    line = "    minigame lantern_memory pairs=6 into turns"
    call = md.read_call(line)
    form = md.form_fields("lantern_memory", plugins)
    values = md.form_values(form, call)
    assert values == {"pairs": "6", "hints": "False", "into": "turns"}
    assert md.call_line(md.call_from_form(form, values, old=call)) == line
    assert md.call_line(md.call_from_form(form, {**values, "hints": "True"}, old=call)) == \
        "    minigame lantern_memory pairs=6 hints=True into turns"
    assert md.call_from_form(form, {**values, "pairs": ""}) == Refuse(
        md.NEEDED.format(label="Pairs"))
    story = (REPO / "game" / "script" / "chapter1.vns").read_text("utf-8")
    assert line in story.split("\n")

    poem_form = md.form_fields("poem_game")
    made = md.call_from_form(poem_form, {"words": "day1_words", "rounds": "4",
                                         "page_words": "10", "into": "poem_for"},
                             skippable=True)
    assert md.call_line(made) == ("    minigame poem_game skippable words=day1_words rounds=4 "
                                  "into poem_for")
    for block in _docs_blocks():
        for number, text in enumerate(block.split("\n")):
            if text.lstrip().startswith("minigame "):
                assert md.call_line(md.read_call(text)) == text


# --- The checks and tables Studio mirrors ------------------------------------------------------

def _attic() -> dict:
    return md.value_of(md.ROOM, _sets(_docs_text("attic"))["attic"].model)


def _with_spot(name: str, **fields: object) -> dict:
    room = _attic()
    spot = dict(room["hotspots"].get(name, {"rect": [400, 300, 64, 64], "label": "X"}))
    spot.update(fields)
    for key in [k for k, v in fields.items() if v is None]:
        del spot[key]
    room["hotspots"] = {**room["hotspots"], name: spot}
    return room


def _circle() -> dict:
    room = _with_spot("hook", after="magnet")
    room["hotspots"]["magnet"] = {**room["hotspots"]["magnet"], "after": "hook"}
    return room


POEMS = [
    {"sun": {"sayori": 3}, "rain": "yuri"},
    {"sun": {"sayori": 3}},
    {"": {}, "rain": {}},
    {" sun": {}, "rain": {}},
    {"sun\nny": {}, "rain": {}},
    {"x" * 25: {}, "rain": {}},
    {"Sun": {}, "sun": {}},
    {"sun": {"1bad": 1}, "rain": {}},
    {"sun": "two words", "rain": {}},
    {"sun": {"sayori": 100}, "rain": {}},
    {"sun": {"sayori": -1}, "rain": {}},
    {"sun": {"sayori": 1.5}, "rain": {}},
    {"sun": {f"m{k}": 1 for k in range(17)}, "rain": {}},
]
STATEMENTS = {"gate": "The gate was locked.", "priest": "Only the priest has a key."}
EVIDENCE = [
    (STATEMENTS, {"gate": "brass_key"}),
    (STATEMENTS, {"gate": ["brass_key", "photo"], "priest": "key"}),
    (STATEMENTS, {}),
    (STATEMENTS, {"gate": []}),
    (STATEMENTS, {"gone": "brass_key"}),
    (STATEMENTS, {"gate": [f"i{k}" for k in range(9)]}),
    ({}, {"gate": "brass_key"}),
    ({f"s{k}": "Text." for k in range(13)}, {"s1": "key"}),
    ({"1gate": "Text."}, {"1gate": "key"}),
    ({"gate": "x" * 121}, {"gate": "key"}),
    ({"gate": "Locked. "}, {"gate": "key"}),
]
CHATS = [
    ["hi", {"me": "hey"}, {"time": "9:00"}, {"Natsuki": "yo"},
     {"ask": "a", "x": ["X.", "ok", {"me": "k"}], "ignore": "Leave it"}],
    [],
    ["x" * 301],
    ["a\nb\nc\nd\ne\nf"],
    [{"me": " hi"}],
    [{"time": "x" * 21}],
    [{"N" * 41: "hi"}],
    ["   "],
    [{"ask": "a", "x": "X."}, {"ask": "a", "y": "Y."}],
    [{"ask": "a"}],
    [{"ask": "a", **{f"r{k}": "R." for k in range(5)}}],
    [{"ask": "a", "bad key": "X."}],
    [{"ask": "a", "x": "x" * 81}],
    [{"ask": "a", "x": ["X.", *(["ok"] * 21)]}],
    [{"ask": "a", "x": ["X.", {"ask": "b", "y": "Y."}]}],
    [{"ask": "a", "x": "X.", "ignore": "x" * 41}],
    [{"ask": "a", "x": "X.", "ignore": 1}],
    [{"ask": f"a{k}", "x": "X."} for k in range(21)],
    [{"me": "hi", "time": "9:00"}],
]
ROOMS = [
    _attic(),
    _with_spot("window", rect=[0, 0, 31, 100]),
    _with_spot("window", rect=[1200, 0, 100, 100]),
    _with_spot("window", label="x" * 41),
    _with_spot("hook", use="string"),
    _with_spot("hook", look="A hook."),
    _with_spot("window", nope="No."),
    _with_spot("glint", after="nowhere"),
    _with_spot("glint", after="window"),
    _with_spot("hook", after="magnet"),
    _circle(),
    _with_spot("out", exit=None, after=None, look="A door."),
    _with_spot("x1", image="i" * 65),
    _with_spot("1x"),
    _with_spot("window", colour="red"),
    {**_attic(), "background": ""},
    {**_attic(), "hotspots": {}},
    {**_attic(), "combine": {"magnet_string": ["magnet", "magnet"]}},
    {**_attic(), "combine": {"magnet": ["magnet", "string"]}},
    {**_attic(), "combine": {"a": ["magnet", "string"], "b": ["string", "magnet"]}},
]


@pytest.mark.parametrize("kind, value, rules", [
    *((md.POEM, v, lambda v: poem_rules.problem({"words": v, "rounds": 1, "page_words": 2}))
      for v in POEMS),
    *((md.TESTIMONY, v, lambda v: present_rules.problem({"testimony": v[0], "answer": v[1]}))
      for v in EVIDENCE),
    *((md.CHAT, v, lambda v: phone_rules.problem({"chat": v, "contact": "Sayori"}))
      for v in CHATS),
    *((md.ROOM, v, lambda v: room_rules.problem({"room": v})) for v in ROOMS),
])
def test_checks_agree_with_the_rules_modules(kind, value, rules):
    """``problem`` refuses exactly what the bundled rules refuse; a shape the panel can't
    hold (read as None) is one the rules refuse too. Good cases written back pass."""
    if kind == md.TESTIMONY:
        t, a = md.read_value(md.TESTIMONY, value[0]), md.read_value(md.ANSWER, value[1])
        model = None if t is None or a is None else md.evidence_of(t, a)
    else:
        model = md.read_value(kind, value)
    real = rules(value)
    if model is None:
        assert real is not None
        return
    assert (md.problem(kind, model) is None) == (real is None), (md.problem(kind, model), real)
    if real is None:
        written = (md.evidence_values(model) if kind == md.TESTIMONY
                   else md.value_of(kind, model))
        assert rules(written) is None


def test_builtin_fields_match_the_plugins():
    """``BUILTIN_FIELDS`` is the bundled plugins' ``args`` (names, order, required,
    defaults); the mirrored limits are the rules modules'."""
    plugins = {}
    for module in (poem_game, present_evidence, phone_chat, puzzle_room, heartbeat, code_lock,
                   stay_still, hand_game, gift_giving, ask_text):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if isinstance(getattr(cls, "args", None), dict) and getattr(cls, "name", None):
                plugins[cls.name] = cls.args
    assert set(plugins) == set(md.BUILTIN_FIELDS) == set(md.BUNDLED)
    for game, fields in md.BUILTIN_FIELDS.items():
        real = [(k, a.default is REQUIRED, None if a.default is REQUIRED else a.default)
                for k, a in plugins[game].items()]
        mine = [(f.name, f.required, None if f.default is md.NO_DEFAULT else f.default)
                for f in fields]
        assert mine == real, game
    assert (md.WORDS_MAX, md.WORD_MAX, md.NAMES_MAX, md.SCORE_MAX) == (
        poem_rules.WORDS_MAX, poem_rules.WORD_MAX, poem_rules.NAMES_MAX, poem_rules.SCORE_MAX)
    assert (md.STEPS_MAX, md.TOTAL_MAX, md.ASKS_MAX, md.REPLIES_MAX, md.AFTER_MAX,
            md.MESSAGE_MAX, md.BREAKS_MAX, md.REPLY_MAX, md.SENDER_MAX, md.TIME_MAX) == (
        phone_rules.STEPS_MAX, phone_rules.TOTAL_MAX, phone_rules.ASKS_MAX,
        phone_rules.OPTIONS_MAX, phone_rules.AFTER_MAX, phone_rules.MESSAGE_MAX,
        phone_rules.BREAKS_MAX, phone_rules.REPLY_MAX, phone_rules.NAME_MAX,
        phone_rules.TIME_MAX)
    assert (md.STATEMENTS_MAX, md.STATEMENT_MAX, md.ANSWER_ITEMS_MAX) == (
        present_rules.STATEMENTS[-1], present_rules.TEXT_MAX, present_rules.ANSWER_ITEMS[-1])
    assert (md.HOTSPOTS_MAX, md.RECIPES_MAX, md.USE_MAX, md.RECT_MIN, md.IMAGE_MAX,
            md.LABEL_MAX, md.CAPTION_MAX, md.FIELDS, md.CANVAS) == (
        room_rules.HOTSPOTS[-1], room_rules.RECIPES_MAX, room_rules.USE_MAX,
        room_rules.RECT_MIN, room_rules.NAME_MAX, room_rules.LABEL_MAX,
        room_rules.CAPTION_MAX, room_rules.FIELDS, room_rules.CANVAS)


def test_puzzle_room_round_trips_for_the_room_canvas():
    """For W8's room canvas (AC-F47-45): the docs' attic writes back byte-identical (its
    aligned names and each hotspot's field order kept); a hotspot redrawn on the canvas
    (``clamp_rect``) and a new one write, read back, and pass the room rules."""
    text = _docs_text("attic")
    ds = _sets(text)["attic"]
    assert tuple(md.define_lines(md.ROOM, "attic", ds.model)) == ds.lines
    assert md.plan_edit(ds, ds.model, {REF: text}) is None
    room = ds.model
    assert md.clamp_rect((1270, -5, -20, 10)) == (1248, 0, 32, 32)
    moved = tuple(dataclasses.replace(s, rect=md.clamp_rect((900, 100, 200, 240)))
                  if s.name == "window" else s for s in room.hotspots)
    added = md.Hotspot(md.slug("Old chest", [s.name for s in moved], "spot"),
                       (600, 560, 120, 80), "Old chest", look="Empty.")
    new = md.Room(room.background, moved + (added,), room.combine)
    plan = md.plan_edit(ds, new, {REF: text})
    after = _apply(plan, {REF: text})[REF]
    again = _sets(after)["attic"]
    assert again.model == new and again.lines[4].startswith('        "hook":      {')
    assert room_rules.problem({"room": md.value_of(md.ROOM, new)}) is None


# --- F53 W2: the quick games in the Minigame form ------------------------------------------------

def test_ac_f53_28_quick_games_fields():
    """The three games' fields (§5's labels and widgets) are their plugins' args; BUNDLED and
    GAME_TITLES list them."""
    quick = ("code_lock", "stay_still", "hand_game")
    at = md.BUNDLED.index("code_lock")
    assert md.BUNDLED[at:at + 3] == quick and at > md.BUNDLED.index("heartbeat")
    assert [md.game_title(g) for g in quick] == ["Lock", "Stay still", "Hand game"]
    shape = {g: [(f.name, f.label, f.widget, f.required, f.default_text, f.lo, f.hi, f.choices)
                 for f in md.BUILTIN_FIELDS[g]] for g in quick}
    assert shape["code_lock"] == [
        ("kind", "Kind", md.CHOICE, False, '"keypad"', None, None, ("keypad", "dial")),
        ("code", "Code", md.TEXT, True, "", None, None, ()),
        ("tries", "Tries allowed", md.NUMBER, False, "0", 0, 99, ()),
        ("hint", "Hint", md.TEXT, False, "None", None, None, ()),
        ("hint_after", "Show the hint after", md.NUMBER, False, "3", 0, 99, ()),
        ("leave", "Player can step back", md.TOGGLE, False, "True", None, None, ())]
    assert shape["stay_still"] == [
        ("seconds", "Seconds", md.NUMBER, False, "10", 3, 120, ()),
        ("line", "What they say", md.TEXT, False, "None", None, None, ()),
        ("speaker", "Who says it", md.TEXT, False, "None", None, None, ()),
        ("flinch_line", "What they say when you move", md.TEXT, False, "None", None, None, ()),
        ("strict", "The first touch ends it", md.TOGGLE, False, "False", None, None, ()),
        ("mouse", "Moving the mouse counts", md.TOGGLE, False, "False", None, None, ()),
        ("ready", "Show an \"I'm ready\" button", md.TOGGLE, False, "True", None, None, ())]
    assert shape["hand_game"] == [
        ("opponent", "Opponent's name", md.TEXT, True, "", None, None, ()),
        ("rounds", "Rounds", md.NUMBER, False, "3", 1, 9, ()),
        ("mode", "How they play", md.CHOICE, False, '"fair"', None, None,
         ("fair", "kind", "cheat", "sly"))]
    # The limits are the rules modules'.
    assert (shape["code_lock"][2][5:7], shape["stay_still"][0][5:7]) == ((0, 99), (3, 120))
    form = md.form_fields("code_lock")
    values = {**md.form_values(form, None), "code": '"0417"', "tries": "3",
              "hint": '"The date on the diary."', "into": "safe_open"}
    call = md.call_from_form(form, values)
    assert md.call_line(dataclasses.replace(call, indent="")) == (
        'minigame code_lock code="0417" tries=3 hint="The date on the diary." into safe_open')


def test_ac_f53_30_every_field_has_a_hint():
    """``fieldhints.MINIGAME_HINTS`` (F57's one table, F53's ARG_HINTS) has a sentence for
    every bundled field, and §5's texts for the quick games."""
    from engine.tools.editor import fieldhints
    for game, fields in md.BUILTIN_FIELDS.items():
        for f in fields:
            hint = fieldhints.minigame_hint(game, f.name)
            assert hint and hint.endswith(".") and len(hint) <= 140, (game, f.name)
        assert set(fieldhints.MINIGAME_HINTS[game]) == {f.name for f in fields}, game
    assert fieldhints.minigame_hint("code_lock", "tries") == (
        "Wrong codes allowed before the lock stays shut. 0: no limit.")
    assert fieldhints.minigame_hint("stay_still", "flinch_line") == (
        "Shown for 2 seconds each time the player touches something.")
    assert fieldhints.minigame_hint("hand_game", "mode") == (
        "fair: random. kind: lets the player win. cheat: switches hands to win, and it shows. "
        "sly: always wins, without showing it.")


def test_ac_f53_31_row_summaries():
    summary = md.FORM.summary
    assert summary({"line": 'minigame code_lock code="0417" tries=3 into safe_open'}) == (
        "Lock · 0417 → safe_open")
    assert summary({"line": "minigame stay_still seconds=15 into flinches"}) == (
        "Stay still · 15 s → flinches")
    assert summary({"line": "minigame stay_still"}) == "Stay still · 10 s"
    assert summary({"line": 'minigame hand_game opponent="Hana" rounds=3 mode="cheat" '
                            "into rps"}) == "Hand game · Hana, cheat → rps"
    assert summary({"line": 'minigame hand_game opponent="Hana"'}) == "Hand game · Hana, fair"
    assert summary({"line": "minigame code_lock code=secret_code"}) == "Lock · secret_code"


@pytest.mark.parametrize("kind,code", [
    ("keypad", "0417"), ("keypad", "0" * 12), ("keypad", "0" * 13), ("keypad", ""),
    ("keypad", "12a4"), ("keypad", "12²"), ("dial", "123"), ("dial", "12"), ("dial", "love"),
    ("dial", "LoVe"), ("dial", "ab12"), ("dial", "café"), ("dial", "abcdefg"),
    ("dial", "x" * 40)])
def test_ac_f53_32_code_check_mirrors_lock_rules(kind, code):
    """The form's L3/L4 is ``lock_rules``' with a capital first letter; OK is refused."""
    real = lock_rules.problem({**lock_rules.DEFAULTS, "kind": kind, "code": code})
    mine = md.code_problem(kind, code)
    assert (mine is None) == (real is None)
    if real is not None:
        assert mine == real[0].upper() + real[1:]
    form = md.form_fields("code_lock")
    values = {**md.form_values(form, None), "kind": md.literal(kind), "code": md.literal(code)}
    call = md.call_from_form(form, values)
    assert isinstance(call, Refuse) == (real is not None)
    if real is not None:
        assert call.text == mine
    # An expression is left to the game.
    assert md.form_problem("code_lock", {"kind": '"keypad"', "code": "secret"}) is None


# --- F54 S2: the gift table --------------------------------------------------------------------

def _gifts(**more) -> dict:
    return md.value_of(md.GIFTS, _sets(_docs_text("birthday_gifts"))["birthday_gifts"].model) | more


GIFT_TABLES = [
    _gifts(),
    {},
    {f"c{k}": {} for k in range(33)},
    {"Hana Li": {}},
    {"1hana": {"coin": ["liked", 1]}},
    {"hana": {f"i{k}": ["liked", 1] for k in range(201)}},
    {"hana": {"*": ["neutral", 0], **{f"i{k}": ["liked", 1] for k in range(200)}}},
    {"hana": {"red lantern": ["liked", 1]}},
    {"hana": {"coin": ["lovd", 1]}},
    {"hana": {"coin": ["liked", 11]}},
    {"hana": {"coin": ["liked", -10, "Fine."]}},
    {"hana": {"coin": ["liked", 1, ""]}},
    {"hana": {"coin": ["liked", 1, "x" * 161]}},
    {"hana": {"coin": ["liked", 1, "a\nb"]}},
    {"hana": {"coin": ["liked", 1, " a"]}},
    {"hana": {"coin": "liked"}},
    {"hana": {"coin": ["liked"]}},
    {"hana": {"coin": ["liked", 1, 5]}},
    {"hana": ["liked"]},
]


@pytest.mark.parametrize("value", GIFT_TABLES)
def test_ac_f54_08_gift_tables(value):
    """The docs' table round-trips byte-identical and is found by its minigame line and by
    its shape; ``problem`` refuses exactly what ``gift_rules`` refuses."""
    text = _docs_text("birthday_gifts")
    ds = _sets(text)["birthday_gifts"]
    assert ds.kind == md.GIFTS and not ds.guessed and ("gift_giving", "gifts") in ds.used
    assert tuple(md.define_lines(md.GIFTS, "birthday_gifts", ds.model)) == ds.lines
    assert md.plan_edit(ds, ds.model, {REF: text}) is None
    alone = "\n".join(ds.lines) + "\n"
    found = _sets(alone)["birthday_gifts"]
    assert found.kind == md.GIFTS and found.guessed and found.model == ds.model
    # The mirror, case by case.
    model = md.read_value(md.GIFTS, value)
    to = next(iter(value), "hana") if isinstance(value, dict) else "hana"
    real = gift_rules.problem({**gift_rules.DEFAULTS, "gifts": value, "to": to})
    if model is None:
        assert real is not None
        return
    mine = md.problem(md.GIFTS, model)
    assert (mine is None) == (real is None), (mine, real)
    if real is not None and "Did you mean" not in real:
        assert mine == real
    if real is None:
        assert gift_rules.problem({**gift_rules.DEFAULTS, "to": to,
                                   "gifts": md.value_of(md.GIFTS, model)}) is None


def test_ac_f54_08_new_table_and_any_row():
    """A new table writes the docs' layout; the "Any other gift" row is written only when it
    differs from Neutral, 0 and no line."""
    section = md.GiftSection("hana", (md.GiftRow("red_lantern", "loved", 3, "Kept it?"),))
    plain = md.gift_set_any(section, "neutral", 0, "")
    assert plain == section
    said = md.gift_set_any(section, "neutral", 0, "Oh. Thank you.")
    assert said.rows[0] == md.GiftRow("*", "neutral", 0, "Oh. Thank you.") and said.any_row
    assert md.gift_set_any(said, "neutral", 0, None) == section
    plan = md.plan_new(md.GIFTS, "birthday_gifts", md.GiftTable((said,)),
                       {md.MAIN_REF: 'label start:\n    "Hi."\n'})
    written = list(plan.plan.files[0].edits[0].lines)
    written = written[written.index("define birthday_gifts = {"):]
    assert written == [
        "define birthday_gifts = {",
        '    "hana": {',
        '        "*": ["neutral", 0, "Oh. Thank you."],',
        '        "red_lantern": ["loved", 3, "Kept it?"],',
        "        },",
        "    }"]
    refused = md.plan_new(md.GIFTS, "x", md.GiftTable(), {md.MAIN_REF: ""})
    assert isinstance(refused, Refuse) and "gifts has 0 characters" in refused.text


def test_ac_f54_11_hints_and_row_summary():
    from engine.tools.editor import fieldhints
    assert [(f.name, f.label, f.widget, f.required) for f in md.BUILTIN_FIELDS["gift_giving"]]         == [("gifts", "Gift table", md.DATA, True), ("to", "Gift for", md.METER, True),
            ("speaker", "Name shown", md.TEXT, False),
            ("categories", "Item categories", md.VALUE, False),
            ("use_up", "The gift is used up", md.TOGGLE, False),
            ("leave", "Player can say Not now", md.TOGGLE, False),
            ("result", "Result", md.CHOICE, False)]
    assert md.game_title("gift_giving") == "Gift giving" and "gift_giving" in md.BUNDLED
    hints = {"gifts": "The gift table: who likes what.",
             "to": "Whose reactions to use. Their meter changes by the gift's points.",
             "speaker": "The name on the reaction card. Empty: the Gift for name.",
             "categories": "Only items in these categories can be given. Empty: every item.",
             "use_up": "On: the given item leaves the inventory.",
             "leave": "On: shows a Not now button (the result is then None).",
             "result": "reaction: loved, liked, neutral or disliked. item: the given item's "
                       "name."}
    for name, hint in hints.items():
        assert fieldhints.minigame_hint("gift_giving", name) == hint
    line = ('minigame gift_giving skippable gifts=birthday_gifts to="hana" '
            'categories=["Gifts"] into reaction')
    assert md.FORM.summary({"line": line}) == "Gift giving · birthday_gifts → reaction"
