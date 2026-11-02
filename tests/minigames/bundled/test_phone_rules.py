"""F26-1: the phone chat's rules and declarations (F26 ``06``: AC-F26-01, 02, 04, 05, 17, and
AC-F26-07's unit row).

Direct calls into ``phone_rules`` (harness "Rules") with Template C's ``late_chat``,
``contact="Sayori"``, ``time="11:42 PM"``. The refusal texts are F26 ``01`` §5.3's drafts and
this module's forms for the rows the drafts leave open (``07`` I-1's edge forms, I-9): a
narrative-designer rewording updates these tables, not the ACs.
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
from engine.minigames.bundled import phone_rules
from engine.minigames.bundled.phone_chat import PhoneChat
from engine.minigames.bundled.phone_rules import (
    Message,
    Placed,
    TimeMark,
    Typing,
    fixed_outcome,
    parse,
    phone_layout,
    problem,
    result_of,
    thread_layout,
    typing_s,
)
from engine.minigames.bundled.poem_game import PoemGame
from engine.minigames.bundled.present_evidence import PresentEvidence
from tests.minigames.conftest import plugin, write

REPO = Path(__file__).resolve().parents[3]
BUNDLED_DIR = Path(bundled.__file__).parent
SIG = api.declarations(PhoneChat, "engine").sig
S = StoryNames((), (), ())
ZWJ_EMOJI = "\U0001F469‍\U0001F4BB"
LATE = ["you awake?",
        "i can't sleep...",
        {"ask": "awake",
         "yes": ["Yeah, what's up?", "nothing really"],
         "sleep": ["Go to sleep, Sayori.", "ok ok... one more thing!!"],
         "ignore": True},
        {"time": "11:51 PM"},
        "can we walk to school together tomorrow?",
        {"ask": "walk", "sure": "Sure. Same corner as always?", "busy": "I have to go early."},
        "yay!! see you then"]


def base(**changes) -> dict:
    args = {"chat": copy.deepcopy(LATE), "contact": "Sayori", "time": "11:42 PM"}
    args.update(changes)
    return args


def at(k: int, step: object) -> dict:
    """The base args with top-level step ``k`` (from 1) replaced."""
    chat = copy.deepcopy(LATE)
    chat[k - 1] = step
    return base(chat=chat)


def awake(**changes) -> dict:
    """The base args with ask ``awake`` changed; a value of ``...`` removes the key."""
    step = copy.deepcopy(LATE[2])
    for key, value in changes.items():
        if value is ...:
            step.pop(key)
        else:
            step[key] = value
    return at(3, step)


def _ordered(v: object) -> object:
    if type(v) is dict:
        return [(k, _ordered(x)) for k, x in v.items()]
    if type(v) is list:
        return [_ordered(x) for x in v]
    return v


# --- AC-F26-01: declarations, imports, and codes ---------------------------------------------

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


def test_ac_f26_01_declarations_imports_and_codes(game, load):
    # BUNDLED: PhoneChat once, in feature order, from one import line (07 G6, I-7).
    tree = ast.parse((BUNDLED_DIR / "__init__.py").read_text(encoding="utf-8"))
    modules = [n.module for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert modules.count("engine.minigames.bundled.phone_chat") == 1
    assert bundled.BUNDLED.count(PhoneChat) == 1
    assert bundled.BUNDLED.index(PoemGame) < bundled.BUNDLED.index(PresentEvidence) \
        < bundled.BUNDLED.index(PhoneChat)
    # The signature.
    entry = api.declarations(PhoneChat, "engine")
    assert (SIG.name, SIG.title, entry.api, entry.over_stage) == ("phone_chat", "Phone", "1.1",
                                                                  True)
    assert SIG.args == (ArgSpec("chat", REQUIRED), ArgSpec("contact", REQUIRED),
                        ArgSpec("time", None))
    assert SIG.test == SIG.skipped == Outcome(None)
    assert PhoneChat.test_outcome == PhoneChat.skipped_outcome == Outcome(None)
    assert entry.words == {"title": "Phone", "ignore": "Don't reply",
                           "close": "Put the phone away", "placeholder": "Message"}
    assert entry.tokens == {
        "phone.body_color": "#1E1E24", "phone.screen_color": "#F7F4F6",
        "phone.body_width": 420, "bar.fill_color": "#FFFFFF", "bar.text_color": "#3A2E39",
        "bar.line_color": "#E3D9DF", "header.text_font": "ui.text_font",
        "header.text_size": 28, "message.text_font": "ui.text_font", "message.text_size": 24,
        "them.fill_color": "#ECE6EA", "them.text_color": "#2A2128",
        "me.fill_color": "#A02860", "me.text_color": "#FFFFFF", "name.text_color": "#A02860",
        "note.text_color": "#6E5E68", "typing.dot_color": "#6E5E68"}
    assert SIG.check is not None and SIG.outcome is not None
    assert "check_story" not in PhoneChat.__dict__
    assert SIG.check(base(contact=3), S) == problem(base(contact=3)) is not None
    assert SIG.check(base(), S) is None
    # The ast scan (PR-F26-01, C1, A7, A8).
    stdlib = set(sys.stdlib_module_names) - {"random", "time"}
    rules_ok = {"engine.minigames.api", "engine.minigames.bundled.rule_text",
                "engine.ui.layouts"}
    kit = {"engine.minigames.bundled", "engine.minigames.bundled.phone_rules",
           "engine.ui.focus", "engine.ui.widgets", "engine.ui.paint", "engine.ui.nav",
           "engine.ui.layouts", "pygame", "engine.render.frames", "engine.render.text"}
    banned = re.compile(r"(random|time)$|engine\.(runtime|script|persist|app)\b|"
                        r"engine\.minigames\.(host|loader|registry|context)\b")
    for name, allowed in (("phone_rules", rules_ok), ("phone_chat", rules_ok | kit)):
        found = _imports(BUNDLED_DIR / f"{name}.py")
        assert {m for m in found if m.split(".")[0] not in stdlib} <= allowed, name
        assert not [m for m in found if banned.match(m)], name
    # Codes: W176's text (01 §5.4, with the real token name); the spares unused.
    assert phone_rules.w176_text("\U0001F60A", "step 4") == (
        "The phone chat's message font can't draw \"\U0001F60A\" (U+1F60A), used in step 4, "
        "so it shows as a box. Set plugin.phone_chat.message.text_font to a font that has it, "
        "or remove the character.")
    assert '"中" (U+4E2D), used in step 2 after reply "yes" of ask "awake",' in \
        phone_rules.w176_text("中", 'step 2 after reply "yes" of ask "awake"')
    for name in ("phone_rules", "phone_chat"):
        text = (BUNDLED_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"E28[89]|E290|W17[78]", text), name
    codes_file = REPO / "specs" / "CODES.md"   # specs/ is kept out of the repository
    if codes_file.exists():
        codes = codes_file.read_text(encoding="utf-8")
        assert re.search(r"F26 Phone / messages \| E288–E290 \| W176–W178", codes)
    # AC-F23-21's replacement row against the real BUNDLED.
    write(game, "minigames/my_phone.py", plugin("phone_chat"))
    loaded = load(game)
    assert loaded.result.ok and loaded.names.count("phone_chat") == 1
    assert loaded.result.registry.get("phone_chat").unit == "minigames/my_phone.py"
    assert loaded.warnings("W160") == [messages.w160_replaces("minigames/my_phone.py",
                                                              "phone_chat")]
    assert load(game, dev=False).warnings() == []


# --- AC-F26-02: R1–R14 ---------------------------------------------------------------------

def _random_text(rng: random.Random) -> str:
    alphabet = "ab Z_9\n\t​‍‮ 中\U0001F60A\xa0"
    return "".join(rng.choice(alphabet) for _ in range(rng.choice([0, 1, 3, 20, 41, 81, 301])))


def _random_value(rng: random.Random, depth: int = 0) -> object:
    roll = rng.randrange(10 if depth < 3 else 5)
    if roll == 0:
        return rng.choice([0, 1, -1, 3, 10**30, True, False, None, 1.5, 1e300])
    if roll in (1, 2, 3):
        return rng.choice([_random_text(rng), "hi", "me", "time", "ask", "ignore", "awake"])
    if roll == 4:
        return rng.choice(["11:42 PM", "Sayori", "", "  ", "x" * 41])
    if roll in (5, 6):
        sizes = [0, 1, 3, 25, 201] if depth == 0 else [0, 1, 3, 22]
        return [_random_value(rng, depth + 1) for _ in range(rng.choice(sizes))]
    if roll == 7:
        return {rng.choice(["me", "time", "Natsuki", "", "a b"]): _random_value(rng, depth + 1)
                for _ in range(rng.randrange(0, 3))}
    keys = ["yes", "sleep", "say yes", "9a", "ignore", "x", "y"]
    step: dict = {"ask": rng.choice(["awake", "walk", 5, "a b", "x" * 65])}
    for key in rng.sample(keys, rng.randrange(0, 6)):
        step[key] = _random_value(rng, depth + 1)
    return step


def test_ac_f26_02_the_argument_checks():
    r1 = 'chat must be a list of messages and asks, e.g. ["hi!", {"me": "hey"}], but it is '
    r3 = ('step 4 must be a message (text), a one-key dictionary such as {"me": "hi"}, or an '
          "ask, but it is ")
    msg = "a message is 1 to 300 characters with up to 4 line breaks."
    r5 = ", but a sender's name is 1 to 40 characters on one line."
    r6 = ', but a time is 1 to 20 characters on one line, such as "11:51 PM".'
    r7 = ", but an ask's name is letters, digits, and _."
    r8 = '; an ask has 1 to 4, plus "ignore".'
    r8n = "; a reply's name is letters, digits, and _."
    r9 = ('reply "yes" of ask "awake" must be its text, or a list of its text and what '
          "follows, but it is ")
    reply = 'reply "yes" of ask "awake"'
    rule9 = "a reply is 1 to 80 characters on one line."
    r11 = ('ignore in ask "awake" must be True, False, or a button label of 1 to 40 characters, '
           "but it is ")
    r13 = "contact must be a name of 1 to 40 characters on one line, but it is "
    r14 = ('time must be text such as "11:42 PM" (1 to 20 characters on one line), or None, '
           "but it is ")
    edge = "starts or ends with a space. Remove the space."
    x30 = "x" * 30 + "…"

    def total_chat(extra: bool) -> list:
        asks = [{"ask": f"a{j}", **{f"o{k}": ["R", *["f"] * 20] for k in range(4)}}
                for j in range(10)]                         # 10 × 4 × 20 = 800 follow-ups
        plain: list = ["m"] * 190
        if extra:
            plain[0] = {"ask": "b", "x": ["R", "f"]}
        return asks + plain

    asks21 = [{"ask": f"a{j}", "x": "X"} for j in range(21)]
    hidden = ("\x00", "\t", "​", "‏", " ", " ", "", "\ud800")
    rows = [
        # R1
        *[(base(chat=v), r1 + end) for v, end in (
            ({"a": 1}, "a dictionary."), ("hi", "text."), (3, "a whole number."),
            (None, "None."))],
        # R2
        (base(chat=[]), "chat must have 1 to 200 steps, but it has 0."),
        (base(chat=["x"] * 201), "chat must have 1 to 200 steps, but it has 201."),
        (base(chat=["x"] * 200), None),
        (base(chat=total_chat(True)), "chat has 1,001 steps counting replies; the most is "
                                      "1,000."),
        (base(chat=total_chat(False)), None),
        # R3
        *[(at(4, v), r3 + end) for v, end in (
            (["x"], "a list."), (3, "a whole number."), ({}, "a dictionary with 0 keys."),
            ({"me": "a", "time": "b"}, "a dictionary with 2 keys."))],
        # R4
        (at(1, "x" * 300), None),
        (at(1, "x" * 301), f"step 1 is 301 characters long; {msg}"),
        (at(1, ""), f"step 1 is empty; {msg}"),
        (at(1, "   "), f"step 1 is empty; {msg}"),
        (at(1, "a\nb\nc\nd\ne"), None),
        (at(1, "a\nb\nc\nd\ne\nf"), f"step 1 has 5 line breaks; {msg}"),
        (at(1, {"me": 3}), "the message in step 1 isn't text; it is a whole number."),
        *[(at(1, f"a{ch}b"), f"step 1 has a hidden or control character; {msg}")
          for ch in hidden],
        *[(at(1, t), None) for t in (ZWJ_EMOJI, "中", "שלום",
                                     "\U0001F60A", {"me": "שלום"})],
        *[(at(1, t), "step 1 starts or ends with a space or line break. Remove it.")
          for t in (" hi", "hi ", "hi\n", {"me": "hi "})],
        # R5
        (at(1, {"": "hi"}), 'step 1 is from ""' + r5),
        (at(1, {"N" * 41: "hi"}), f'step 1 is from "{"N" * 30}…"' + r5),
        (at(1, {"Nat\nsuki": "hi"}), 'step 1 is from "Nat suki"' + r5),
        (at(1, {"N" * 40: "hi"}), None),
        (at(1, {" Natsuki": "hi"}), f'step 1 is from " Natsuki", which {edge}'),
        # R6
        (at(7, {"time": ""}), 'the time in step 7 is ""' + r6),
        (at(7, {"time": "1" * 21}), f'the time in step 7 is "{"1" * 21}"' + r6),
        (at(7, {"time": "1\n2"}), 'the time in step 7 is "1 2"' + r6),
        (at(7, {"time": "1" * 20}), None),
        (at(7, {"time": " 1 AM"}), f'the time in step 7 is " 1 AM", which {edge}'),
        # R7
        (awake(ask="stay up?"), 'step 3 asks "stay up?"' + r7),
        (awake(ask=5), "step 3 asks 5" + r7),
        (awake(ask="a" * 65), f'step 3 asks "{"a" * 30}…"' + r7),
        (awake(ask="a" * 64), None),
        (at(6, {**LATE[5], "ask": "awake"}),
         'step 6 asks "awake" again; each ask needs its own name.'),
        # R8
        (awake(yes=..., sleep=...), 'ask "awake" has 0 replies' + r8),
        (awake(a="A", b="B", c="C"), 'ask "awake" has 5 replies' + r8),
        (awake(a="A", b="B"), None),
        (awake(**{"say yes": "Y"}), 'ask "awake" has a reply named "say yes"' + r8n),
        (awake(**{"9a": "Y"}), 'ask "awake" has a reply named "9a"' + r8n),
        # R9
        (awake(yes=3), r9 + "a whole number."),
        (awake(yes=[]), r9 + "an empty list."),
        (awake(yes=[3]), r9 + "a list that starts with a whole number."),
        (awake(yes=""), f"{reply} is empty; {rule9}"),
        (awake(yes="x" * 81), f"{reply} is 81 characters long; {rule9}"),
        (awake(yes="x" * 80), None),
        (awake(yes="a\nb"), f"{reply} has a line break or hidden character; {rule9}"),
        (awake(yes=["Sure ", "ok"]), f"{reply} {edge}"),
        # R10
        (awake(yes=["R", *["f"] * 21]), f"{reply} is followed by 21 steps; the most is 20."),
        (awake(yes=["R", *["f"] * 20]), None),
        (awake(yes=["R", {"ask": "more", "a": "A"}]),
         f"{reply} is followed by an ask; put the next ask after this one in chat."),
        (awake(yes=["R", "ok", ""]), f"step 2 after {reply} is empty; {msg}"),
        (awake(yes=["R", {"time": "3 AM"}, ["x"]]),
         f"step 2 after {reply} must be a message (text), a one-key dictionary such as "
         '{"me": "hi"}, or an ask, but it is a list.'),
        # R11
        (awake(ignore=""), r11 + '"".'),
        (awake(ignore=1), r11 + "1."),
        (awake(ignore=0), r11 + "0."),
        (awake(ignore=None), r11 + "None."),
        (awake(ignore="x" * 41), r11 + f'"{x30}".'),
        (awake(ignore=" Not now"), f'ignore in ask "awake" is " Not now", which {edge}'),
        *[(awake(ignore=v), None) for v in (True, False, "Not now", ...)],
        # R12
        (base(chat=asks21), "chat has 21 asks; a chat can have up to 20."),
        (base(chat=asks21[:20]), None),
        # R13
        (base(contact=3), r13 + "3."),
        (base(contact=""), r13 + '"".'),
        (base(contact="S" * 41), r13 + f'"{"S" * 30}…".'),
        (base(contact="Sa\nyori"), r13 + '"Sa yori".'),
        (base(contact="S" * 40), None),
        (base(contact=" Sayori"), f'contact " Sayori" {edge}'),
        # R14
        (base(time=2342), r14 + "2342."),
        (base(time=""), r14 + '"".'),
        (base(time="1" * 21), r14 + f'"{"1" * 21}".'),
        (base(time="1\n2"), r14 + '"1 2".'),
        (base(time=None), None),
        (base(time="1" * 20), None),
        (base(time="11:42 PM "), f'time "11:42 PM " {edge}'),
        # Order
        (base(chat={"a": 1}, contact=3), r1 + "a dictionary."),
        (base(chat=[""] * 201), "chat must have 1 to 200 steps, but it has 201."),
        (base(chat=[LATE[0], "", LATE[2], LATE[3], {"ask": "a b", "x": "X"}]),
         f"step 2 is empty; {msg}"),
        (awake(ask="a b", a="A", b="B", c="C"), 'step 3 asks "a b"' + r7),
        (awake(a="A", b="B", c="C", yes=3), 'ask "awake" has 5 replies' + r8),
        (awake(yes=3, ignore=1), r9 + "a whole number."),
        (base(chat=asks21 + ["x"] * 8 + [3]),
         r3.replace("step 4", "step 30") + "a whole number."),
        (base(chat=asks21, contact=3), "chat has 21 asks; a chat can have up to 20."),
        (base(contact=3, time=3), r13 + "3."),
        # Echo cuts
        (at(1, {"Nat\n" + "x" * 36: "hi"}), f'step 1 is from "Nat {"x" * 26}…"' + r5),
        (awake(ask="a" * 40, a="A", b="B", c="C"), f'ask "{"a" * 30}…" has 5 replies' + r8),
        (base(time="x" * 40), r14 + f'"{x30}".'),
    ]
    for i, (args, expected) in enumerate(rows):
        assert problem(args) == expected, i
    # Hostile values: a str or None, never raises, args unchanged, the same answer twice.
    rng = random.Random(26)
    for name in ("chat", "contact", "time"):
        for _ in range(300):
            value = (_random_value(rng) if name != "chat" or rng.random() < 0.3 else
                     [_random_value(rng, 1) for _ in range(rng.randrange(1, 12))])
            args = base(**{name: value})
            before = _ordered(copy.deepcopy(args))
            answers = [problem(args), problem(args)]
            assert answers[0] == answers[1]
            assert answers[0] is None or type(answers[0]) is str
            assert _ordered(args) == before


# --- AC-F26-04: parsing and results ---------------------------------------------------------

def test_ac_f26_04_parsing_and_results():
    chat = parse(base())
    assert len(chat.steps) == 7 and chat.asks == ("awake", "walk")
    assert chat.contact == "Sayori" and chat.time == "11:42 PM" and chat.group is False
    assert chat.steps[0] == Message("Sayori", "you awake?")
    assert chat.steps[3] == TimeMark("11:51 PM")
    ask = chat.steps[2]
    assert [o.key for o in ask.options] == ["yes", "sleep"]
    assert (ask.ignore, ask.ignore_label) == (True, None)
    assert ask.options[0].text == "Yeah, what's up?"
    assert ask.options[0].after == (Message("Sayori", "nothing really"),)
    walk = chat.steps[5]
    assert (walk.ignore, walk.ignore_label) == (False, None)
    assert [(o.key, o.after) for o in walk.options] == [("sure", ()), ("busy", ())]
    assert parse(awake(ignore="Leave it")).steps[2].ignore_label == "Leave it"
    assert parse(awake(ignore=False)).steps[2].ignore is False
    me = parse(base(chat=[{"me": "On my way."}, {"Natsuki": "hi"}])).steps
    assert me == (Message(None, "On my way."), Message("Natsuki", "hi"))
    assert parse(base(time=None)).time is None
    # group (PR-F26-14).
    for steps, group in (
            (["hi", {"Natsuki": "yo"}], True),
            (["hi", {"me": "yo"}], False),
            (["hi", {"ask": "a", "x": ["X", {"Natsuki": "yo"}]}], True),
            ([{"Natsuki": "yo"}], False),
            ([{"Sayori": "yo"}, "hi"], False)):
        assert parse(base(chat=steps)).group is group, steps
    # result_of, key order asserted.
    abc = parse(base(chat=[{"ask": k, "x": "X", "ignore": True} for k in "abc"]))
    ab = parse(base(chat=[{"ask": k, "x": "X"} for k in "ab"]))
    for chat, picks, expected in (
            (parse(base(chat=["hi"])), {}, {}),
            (abc, {}, {"a": None, "b": None, "c": None}),
            (abc, {"a": "ignore"}, {"a": "ignore", "b": None, "c": None}),
            (ab, {"b": "y", "a": "x"}, {"a": "x", "b": "y"})):
        result = result_of(chat, picks)
        assert result == expected and list(result) == list(expected)
    with pytest.raises(AssertionError):
        parse(base(contact=3))


# --- AC-F26-05: fixed outcomes -------------------------------------------------------------

def _valid_chat(rng: random.Random) -> list:
    chat: list = []
    for j in range(rng.randrange(0, 5)):
        chat.append(rng.choice(["hi", {"me": "ok"}, {"time": "1 AM"}, {"Natsuki": "yo"}]))
        keys = rng.sample(["x", "y", "z", "w"], rng.randint(1, 4))
        ask = {"ask": f"q{j}", **{k: rng.choice([k.upper(), [k.upper(), "f"]]) for k in keys}}
        if rng.random() < 0.5:
            ask["ignore"] = rng.choice([True, False, "Leave it"])
        chat.append(ask)
    return chat or ["hi"]


def test_ac_f26_05_fixed_outcomes():
    first = {"awake": "yes", "walk": "sure"}
    every_ignore = [{"ask": k, "y": "Y", "x": "X", "ignore": True} for k in "ab"]
    for args, expected in ((base(), Outcome(first, ())),
                           (base(chat=["hi", {"me": "yo"}]), Outcome({}, ())),
                           (base(chat=every_ignore), Outcome({"a": "y", "b": "y"}, ()))):
        assert SIG.outcome("test", args, S) == SIG.outcome("skipped", args, S) == expected
        assert fixed_outcome("test", parse(args)) == expected
    with pytest.raises(ValueError):
        fixed_outcome("other", parse(base()))
    with pytest.raises(ValueError):
        PhoneChat().outcome_for("other", base(), S)
    assert PhoneChat.test_outcome == PhoneChat.skipped_outcome == Outcome(None)
    rng = random.Random(5)
    for _ in range(50):
        args = base(chat=_valid_chat(rng))
        assert problem(args) is None
        out = SIG.outcome("test", args, S)
        assert out is not None and out == SIG.outcome("skipped", args, S)
        assert out.changes == () and type(out.result) is dict
        assert list(out.result) == list(parse(args).asks)
        assert "ignore" not in out.result.values()


# --- AC-F26-07 (unit row): typing times ----------------------------------------------------

def test_ac_f26_07_typing_times():
    for n, seconds in ((1, 0.6), (8, 0.6), (9, 0.625), (40, 1.4), (63, 1.975), (64, 2.0),
                       (300, 2.0)):
        assert typing_s("x" * n) == pytest.approx(seconds), n
    assert typing_s(ZWJ_EMOJI) == typing_s("abc")
    assert (phone_rules.GAP_S, phone_rules.GUARD_S, phone_rules.GUARD_EPSILON) == (0.5, 0.25,
                                                                                   1e-6)


# --- AC-F26-17: layout numbers -------------------------------------------------------------

AREA = (24, 24, 1232, 672)


def _fake(text: str, size: int) -> float:
    return 10 * len(text)


def _geometry(placed: tuple[Placed, ...]) -> list[tuple]:
    return [(q.y, q.x, q.w, q.h) for q in placed]


def test_ac_f26_17_layout_numbers():
    lay = phone_layout(AREA, s=24, bar_size=24, header_size=28, body_width=420, reply_h=None)
    assert (lay.body, lay.screen) == ((430, 24, 420, 672), (442, 36, 396, 648))
    assert lay.bar[3] == 42 and lay.header == (442, 78, 396, 63)
    assert (lay.thread, lay.reply, lay.reply_cap) == ((458, 157, 364, 439), (458, 612, 364, 56),
                                                      423)
    big = phone_layout(AREA, s=36, bar_size=36, header_size=42, body_width=420, reply_h=None)
    assert (big.body, big.screen) == ((382, 24, 516, 672), (394, 36, 492, 648))
    assert big.bar[3] == 58 and big.header == (394, 94, 492, 83)
    assert (big.thread, big.reply[3], big.reply_cap) == ((410, 193, 460, 393), 66, 387)
    capped = phone_layout(AREA, s=36, bar_size=36, header_size=42, body_width=420, reply_h=900)
    assert (capped.body, capped.screen, capped.bar, capped.header) == (
        big.body, big.screen, big.bar, big.header)
    assert (capped.thread[3], capped.reply[3]) == (72, 387)
    narrow = phone_layout((24, 24, 300, 672), s=24, bar_size=24, header_size=28,
                          body_width=420, reply_h=None)
    assert narrow.body[2] == 300
    # The thread.
    items = [Message("Sayori", "you awake?"), Message("Sayori", "i can't sleep..."),
             Message(None, "Yeah, what's up?"), TimeMark("11:51 PM"),
             Message("Sayori", "can we walk to school together tomorrow?"), Typing("Sayori")]
    one = dict(width=364, s=24, small=24, measure=_fake)
    placed = thread_layout(items, group=False, **one)
    assert _geometry(placed) == [(0, 0, 124, 50), (58, 0, 184, 50), (124, 180, 184, 50),
                                 (190, 142, 80, 34), (240, 0, 234, 84), (332, 0, 72, 50)]
    assert [q.kind for q in placed] == ["them", "them", "me", "time", "them", "typing"]
    assert placed[4].lines == ("can we walk to school", "together tomorrow?")
    assert all(q.name is None for q in placed)                       # not a group
    # Appending in two calls equals one full call; a bubble replacing the typing item.
    assert thread_layout(items[3:], group=False, start=thread_layout(items[:3], group=False,
                                                                     **one), **one) == placed
    group = [Message("Sayori", "a"), Message("Natsuki", "b"), Message("Natsuki", "c"),
             Message("Sayori", "d")]
    named = thread_layout(group, group=True, **one)
    assert [q.y for q in named] == [38, 142, 200, 304]
    assert [q.name for q in named] == ["Sayori", "Natsuki", None, "Sayori"]
    for chat_items, is_group in ((items, False), (group[:3] + [Typing("Sayori")], True),
                                 (group[:2] + [Typing("Natsuki")], True)):
        laid = thread_layout(chat_items, group=is_group, **one)
        bubble = thread_layout([Message(chat_items[-1].sender, "hello there")],
                               group=is_group, start=laid[:-1], **one)[-1]
        assert (bubble.y, bubble.name) == (laid[-1].y, laid[-1].name)
    long = thread_layout([Message("Sayori", "x" * 40)], group=False, **one)[0]
    assert len(long.lines) == 2 and all(_fake(line, 24) <= 249 for line in long.lines)
    assert "".join(long.lines) == "x" * 40
