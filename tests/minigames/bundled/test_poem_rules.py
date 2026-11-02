"""F24-1: the poem game's rules and declarations (F24 ``06``: AC-F24-01, 02, 04, 05, 12, and
the unit rows of AC-F24-09 (I-6's inclusive guard) and AC-F24-10 (``new_page``)).

Direct calls into ``poem_rules`` (harness "Rules"); declared meters are plain tuples. The
refusal texts are F24 ``01`` §5.3's drafts: a narrative-designer rewording updates this
table, not the ACs. AC-F24-13 (fit against ``minigame_frame``) was added at F24-3 (``07``
I-9), at the end.
"""

import ast
import copy
import random
from pathlib import Path

from engine.core.minigame_types import REQUIRED, ArgSpec, MeterChange, Outcome
from engine.minigames import api, bundled, messages
from engine.minigames.bundled import poem_game, poem_rules
from engine.minigames.bundled.poem_game import PoemGame
from engine.minigames.bundled.poem_rules import (
    changes_of,
    fixed_outcome,
    meter_problem,
    named_meters,
    new_page,
    page_layout,
    parse,
    pick_ignored,
    problem,
    result_of,
    score,
)
from engine.script.suggest import suggest
from tests.minigames.conftest import plugin, write

BUNDLED_DIR = Path(bundled.__file__).parent
D = ("sayori", "natsuki", "yuri", "monika")
M3 = ("sayori", "natsuki", "yuri")
W8 = {"sunshine": {"sayori": 3, "natsuki": 1}, "candy": {"natsuki": 3},
      "melancholy": {"yuri": 3, "sayori": 1}, "whisper": "yuri", "blank": {},
      "zero": {"monika": 0}, "ribbon": {"sayori": 2}, "lantern": {"yuri": 1, "natsuki": 1}}
W29 = {f"w{i:02}": "yuri" for i in range(29)}
SIG = api.declarations(PoemGame, "engine").sig
RULE = "a word is 1 to 24 characters on one line."


def base(**changes) -> dict:
    args = {"words": W29, "rounds": 20, "page_words": 10, "to_points": True, "result": "winner"}
    args.update(changes)
    return args


def first(scores, extra: dict | None = None) -> dict:
    """W29 with word w00's scores replaced (and ``extra`` words after it)."""
    return {"w00": scores, **{k: v for k, v in W29.items() if k != "w00"}, **(extra or {})}


def with_word(word: str) -> dict:
    return {word: "yuri", **W29}


def check(args: dict, meters=M3) -> str | None:
    return problem(args) or meter_problem(args, meters)


# --- AC-F24-01: declarations and imports ----------------------------------------------------

def test_bundled_declarations():
    tree = ast.parse((BUNDLED_DIR / "__init__.py").read_text(encoding="utf-8"))
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    # F25 07 I-8: later bundled features add their own lines and classes after F24's.
    assert [n.module for n in imports].count("engine.minigames.bundled.poem_game") == 1
    assert bundled.BUNDLED[0] is PoemGame and bundled.BUNDLED.count(PoemGame) == 1
    entry = api.declarations(PoemGame, "engine")
    assert (SIG.name, SIG.title, entry.api, entry.over_stage) == ("poem_game", "Poem", "1.1",
                                                                  False)
    assert SIG.args == (ArgSpec("words", REQUIRED), ArgSpec("rounds", 20),
                        ArgSpec("page_words", 10), ArgSpec("to_points", True),
                        ArgSpec("result", "winner"))
    assert SIG.test == SIG.skipped == Outcome(None)
    assert PoemGame.test_outcome == PoemGame.skipped_outcome == Outcome(None)
    assert entry.words == {"title": "Poem", "hint": "Pick a word for your poem."}
    assert entry.tokens == {
        "page.paper_image": "", "page.fill_color": "#FFFDF6", "page.rule_color": "#C9D8EE",
        "page.margin_color": "#E8A0A0", "page.max_width": 800,
        "word.text_font": "ui.text_font", "word.text_size": 32, "word.text_color": "#3A2E39",
        "counter.text_size": 28, "counter.text_color": "plugin.poem_game.word.text_color"}
    assert SIG.check is not None and SIG.outcome is not None


def _top_imports(path: Path) -> set[str]:
    """Imports outside ``if TYPE_CHECKING:`` (07 I-9 allows type-only ones)."""
    found = set()

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


def test_imports():
    rules_ok = {"engine.minigames.api", "engine.minigames.bundled.rule_text", "unicodedata",
                "re", "dataclasses", "math", "typing", "collections.abc"}   # F25 07 I-5
    game_ok = rules_ok | {"engine.minigames.bundled", "engine.minigames.bundled.poem_rules",
                          "engine.ui.focus", "engine.ui.widgets", "engine.ui.paint"}
    assert _top_imports(BUNDLED_DIR / "poem_rules.py") <= rules_ok
    assert _top_imports(BUNDLED_DIR / "poem_game.py") <= game_ok


def test_a_game_plugin_replaces_the_real_bundled_poem_game(game, load):
    write(game, "minigames/my_poems.py", plugin("poem_game"))
    loaded = load(game)
    assert loaded.result.ok and loaded.names.count("poem_game") == 1     # + later bundled
    assert loaded.result.registry.get("poem_game").unit == "minigames/my_poems.py"
    assert loaded.warnings("W160") == [messages.w160_replaces("minigames/my_poems.py",
                                                              "poem_game")]
    assert load(game, dev=False).warnings() == []


# --- AC-F24-02: R1–R13 ---------------------------------------------------------------------

def test_argument_checks():
    r1 = ('words must be a dictionary of words and their scores, e.g. {"sunshine": '
          '{"sayori": 3}}, but it is ')
    hidden = f'the word "a b" has a line break or hidden character; {RULE}'
    r5 = ('the scores for "w00" must be a dictionary such as {"sayori": 3}, or one meter\'s '
          "name, but they are ")
    sixteen = tuple(f"m{i}" for i in range(16))
    r8 = "rounds must be a whole number from 1 to 50, but it is "
    r9 = "page_words must be a whole number from 2 to 12, but it is "
    r12 = 'result must be "winner", "totals", or "words", but it is '
    x30 = "x" * 30 + "…"
    rows = [  # (args, meters, expected)
        *[(base(words=v), M3, r1 + end) for v, end in (
            (["a"], "a list."), ("x", "text."), (3, "a whole number."),
            (1.5, "a decimal number."), (True, "True."), (None, "None."))],
        (base(words={f"w{i}": "yuri" for i in range(2001)}), M3,
         "words has 2,001 words; the poem game takes up to 2,000."),
        (base(words={f"w{i}": "yuri" for i in range(2000)}), M3, None),
        (base(words=with_word("")), M3, f'the word "" is empty; {RULE}'),
        (base(words=with_word("cherry blossoms in spring")), M3,
         f'"cherry blossoms in spring" is 25 characters long; {RULE}'),
        (base(words=with_word("w" * 24)), M3, None),
        *[(base(words=with_word(f"a{ch}b")), M3, hidden)
          for ch in ("\n", "\x00", "​", " ", "", "\ud800", "‏")],
        (base(words=with_word("\U0001F469‍\U0001F4BB")), M3, None),     # I-8: ZWJ
        (base(words=with_word(" rain")), M3,
         'the word " rain" starts or ends with a space. Remove the space.'),
        (base(words=with_word("rain ")), M3,
         'the word "rain " starts or ends with a space. Remove the space.'),
        (base(words={"Rain": "yuri", "rain": "yuri", **W29}), M3,
         '"Rain" and "rain" are the same word. Keep one.'),
        (base(words={"Straße": "yuri", "STRASSE": "yuri", **W29}), M3,
         '"Straße" and "STRASSE" are the same word. Keep one.'),
        (base(words=first(["sayori"])), M3, r5 + "a list."),
        (base(words=first(3)), M3, r5 + "a whole number."),
        (base(words=first(None)), M3, r5 + "None."),
        (base(words=first("yuri")), M3, None),
        (base(words=first("Sayori!")), M3,
         '"w00" scores toward "Sayori!", which can\'t be a meter name.'),
        (base(words=first({"Sayori!": 3})), M3,
         '"w00" scores toward "Sayori!", which can\'t be a meter name.'),
        (base(words=first({"a" * 65: 3})), M3,
         f'"w00" scores toward "{"a" * 30}…", which can\'t be a meter name.'),
        (base(words=first(dict.fromkeys((f"m{i}" for i in range(17)), 1))), M3,
         '"w00" scores toward 17 meters; a word can score toward up to 16.'),
        (base(words=first(dict.fromkeys(sixteen, 1))), sixteen + M3, None),
        *[(base(words=first({"sayori": v})), M3,
           f'"w00" gives sayori {shown}; a score is a whole number from 0 to 99.')
          for v, shown in ((1.5, "1.5"), (True, "True"), (-1, "-1"), (100, "100"))],
        (base(words=first({"sayori": 0, "yuri": 99})), M3, None),
        *[(base(rounds=v), M3, r8 + shown) for v, shown in (
            (0, "0."), (51, "51."), (True, "True."), ("20", '"20".'))],
        (base(rounds=1), M3, None),
        (base(rounds=50, page_words=2, words={f"w{i}": "yuri" for i in range(51)}), M3, None),
        *[(base(page_words=v), M3, r9 + shown) for v, shown in (
            (1, "1."), (13, "13."), (True, "True."))],
        (base(words={f"w{i}": "yuri" for i in range(28)}), M3,
         "20 rounds of 10 words need at least 29 words, but words has 28. Add words, or "
         "lower rounds or page_words."),
        (base(to_points="yes"), M3, 'to_points must be True or False, but it is "yes".'),
        (base(to_points=1), M3, "to_points must be True or False, but it is 1."),
        (base(result="winer"), M3, r12 + '"winer". Did you mean "winner"?'),
        (base(result="xyz"), M3, r12 + '"xyz".'),
        (base(result=3), M3, r12 + "3."),
        *[(base(words=first(scores)), M3,
           f'"w00" scores toward "{name}", but there is no meter named "{name}".{hint}')
          for scores, name, hint in (
              ({"sayory": 3}, "sayory", ' Did you mean "sayori"?'),
              ("Yuri", "Yuri", ' Did you mean "yuri"?'),
              ({"zzz": 1}, "zzz", ""))],
        # Order
        (base(words={"": "yuri", **{f"w{i}": "yuri" for i in range(2001)}}), M3,
         "words has 2,002 words; the poem game takes up to 2,000."),
        (base(words=first({"sayori": 1.5}, {"": "yuri"})), M3,
         '"w00" gives sayori 1.5; a score is a whole number from 0 to 99.'),
        (base(words=with_word(""), rounds=0), M3, f'the word "" is empty; {RULE}'),
        (base(words={f"w{i}": "yuri" for i in range(5)}, rounds=0), M3, r8 + "0."),
        (base(words=first({"zzz": 1}), result="winer"), M3,
         r12 + '"winer". Did you mean "winner"?'),
        (base(words=first({"sayori": 1, "qqq": 1, "rrr": 1})), M3,
         '"w00" scores toward "qqq", but there is no meter named "qqq".'),
        # Echo cuts
        (base(words=with_word("x" * 40)), M3, f'"{x30}" is 40 characters long; {RULE}'),
        (base(words=first("!" * 40)), M3,
         f'"w00" scores toward "{"!" * 30}…", which can\'t be a meter name.'),
        (base(to_points="x" * 40), M3, f'to_points must be True or False, but it is "{x30}".'),
        (base(to_points=list(range(100))), M3,
         "to_points must be True or False, but it is [0, 1, 2, 3, 4, 5, 6, 7, 8, 9,…."),
    ]
    for i, (args, meters, expected) in enumerate(rows):
        assert check(args, meters) == expected, i
    # R13's suggestion is F22's (``Points`` suggests with the same ``suggest``).
    for name in ("sayory", "Yuri", "zzz"):
        assert api.closest(name, M3) == suggest(name, M3)


def _random_value(rng: random.Random, depth: int = 0) -> object:
    roll = rng.randrange(9 if depth < 3 else 6)
    if roll == 0:
        return rng.choice([0, 1, -1, 99, 100, 2000, 10**30, rng.randint(-10**6, 10**6)])
    if roll == 1:
        return rng.choice([0.0, 1.5, -2.25, 1e300])
    if roll == 2:
        return rng.choice([True, False, None])
    if roll in (3, 4, 5):
        alphabet = "aZ_ !\n​‍ß\U0001F338yurisayori"
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
    if roll == 6:
        return [_random_value(rng, depth + 1) for _ in range(rng.randrange(0, 6))]
    if roll == 7:                                    # text keys of any shape
        return {str(_random_value(rng, 3)): _random_value(rng, depth + 1)
                for _ in range(rng.randrange(0, 6))}
    return {f"w{i}": _random_value(rng, depth + 1) for i in range(rng.randrange(0, 40))}


def _ordered(v: object) -> object:
    if type(v) is dict:
        return [(k, _ordered(x)) for k, x in v.items()]
    if type(v) is list:
        return [_ordered(x) for x in v]
    return v


def test_hostile_values_never_raise_or_change_the_args():
    rng = random.Random(24)
    for name in ("words", "rounds", "page_words", "to_points", "result"):
        for _ in range(300):
            args = base(**{name: _random_value(rng)})
            before = _ordered(copy.deepcopy(args))
            answers = [(problem(args), meter_problem(args, M3)) for _ in range(2)]
            assert answers[0] == answers[1]
            assert all(a is None or type(a) is str for a in answers[0])
            assert _ordered(args) == before


# --- AC-F24-04: scores, results, and changes -----------------------------------------------

def _w8(**changes) -> poem_rules.Poem:
    return parse(base(words=W8, rounds=2, page_words=3, **changes))


def _picks(poem: poem_rules.Poem, *words: str) -> list[int]:
    order = [e.word for e in poem.entries]
    return [order.index(w) for w in words]


def test_scores_results_and_changes():
    poem = _w8()
    meters = named_meters(poem, D)
    assert meters == D
    rows = [  # (picks, totals in D order, winner, changes)
        (("sunshine", "candy"), (3, 4, 0, 0), "natsuki", (("sayori", 3), ("natsuki", 4))),
        (("sunshine", "candy", "melancholy"), (4, 4, 3, 0), "sayori",
         (("sayori", 4), ("natsuki", 4), ("yuri", 3))),
        (("blank", "zero"), (0, 0, 0, 0), None, ()),
        (("whisper",), (0, 0, 1, 0), "yuri", (("yuri", 1),)),
        (("lantern", "ribbon"), (2, 1, 1, 0), "sayori",
         (("sayori", 2), ("natsuki", 1), ("yuri", 1))),
    ]
    for words, totals, winner, changes in rows:
        picked = _picks(poem, *words)
        got = score(poem, picked, meters)
        assert list(got) == list(D) and tuple(got.values()) == totals, words
        assert result_of(poem, picked, got) == winner, words
        assert changes_of(poem, got) == tuple(MeterChange(m, "+=", n) for m, n in changes)
    picked = _picks(poem, "candy", "sunshine")
    totals = score(poem, picked, meters)
    as_totals = result_of(_w8(result="totals"), picked, totals)
    assert list(as_totals.items()) == [("sayori", 3), ("natsuki", 4), ("yuri", 0), ("monika", 0)]
    assert result_of(_w8(result="words"), picked, totals) == ["candy", "sunshine"]
    assert changes_of(_w8(to_points=False), totals) == ()

    small = parse(base(words={"a": {"sayori": 2, "yuri": 2}, "b": {}}, rounds=1, page_words=2))
    meters = named_meters(small, ("yuri", "sayori", "extra"))
    assert meters == ("yuri", "sayori")
    totals = score(small, [0], meters)
    assert result_of(small, [0], totals) == "yuri"
    assert [c.name for c in changes_of(small, totals)] == ["yuri", "sayori"]

    big = parse(base(words={f"w{i}": {"sayori": 99} for i in range(51)}, rounds=50,
                     page_words=2))
    assert score(big, range(50), ("sayori",)) == {"sayori": 4950}


# --- AC-F24-05: fixed outcomes --------------------------------------------------------------

def test_fixed_outcomes():
    changes = (MeterChange("sayori", "+=", 3), MeterChange("natsuki", "+=", 4))
    zeros = {"sayori": 0, "natsuki": 0, "yuri": 0, "monika": 0}
    rows = [  # (arg changes, test outcome, skipped outcome)
        ({}, Outcome("natsuki", changes), Outcome(None)),
        ({"result": "totals"}, Outcome({"sayori": 3, "natsuki": 4, "yuri": 0, "monika": 0},
                                       changes), Outcome(zeros)),
        ({"result": "words"}, Outcome(["sunshine", "candy"], changes), Outcome([])),
        ({"to_points": False}, Outcome("natsuki"), Outcome(None)),
        ({"page_words": 7}, Outcome("natsuki", changes), Outcome(None)),
    ]
    story = api.StoryNames(D, (), ())
    for change, test, skipped in rows:
        args = base(words=W8, rounds=2, **{"page_words": 3, **change})
        for kind, expected in (("test", test), ("skipped", skipped)):
            assert fixed_outcome(kind, parse(args), D) == expected, (change, kind)
            got = SIG.outcome(kind, args, story)
            assert got == expected and type(got.changes) is tuple, (change, kind)
            if type(expected.result) is dict:
                assert list(got.result) == list(expected.result)

    rng = random.Random(5)
    for _ in range(20):
        n = rng.randrange(3, 40)
        words = {f"w{i}": ({m: rng.randrange(0, 100) for m in rng.sample(D, rng.randrange(0, 4))}
                           if rng.random() < 0.8 else rng.choice(D)) for i in range(n)}
        page_words = rng.randrange(2, min(n, 12) + 1)
        args = base(words=words, rounds=rng.randrange(1, n - page_words + 2),
                    page_words=page_words, to_points=rng.random() < 0.5,
                    result=rng.choice(poem_rules.RESULTS))
        assert check(args, D) is None
        poem = parse(args)
        totals = score(poem, range(poem.rounds), named_meters(poem, D))
        expected = Outcome(result_of(poem, range(poem.rounds), totals), changes_of(poem, totals))
        assert SIG.outcome("test", args, api.StoryNames(D, (), ())) == expected


def test_hooks_are_the_rules():
    story = api.StoryNames(M3, (), ())
    assert SIG.check(base(), story) is None
    assert SIG.check(base(rounds=0), story) == check(base(rounds=0))
    assert SIG.check(base(words=first({"zzz": 1})), story) == check(base(words=first({"zzz": 1})))


# --- Playing: new_page (AC-F24-10 unit row) and the guard (I-6) -------------------------------

def test_new_page_and_the_pick_guard():
    calls = []

    def rec(items):
        calls.append(list(items))
        items.reverse()
        return items

    remaining = [0, 2, 3, 5]
    assert new_page(remaining, 2, rec) == [5, 3]
    assert calls == [[0, 2, 3, 5]] and remaining == [0, 2, 3, 5]
    frames, since = {}, 0.0
    for n in range(1, 14):                                    # as update(dt) sums them
        since += 1 / 60
        frames[n] = since
    assert frames[12] < 0.2                                   # why the boundary needs I-6
    for since, ignored in ((0.0, True), (frames[11], True), (frames[12], False),
                           (frames[13], False), (float("inf"), False)):
        assert pick_ignored(since) is ignored, since


# --- AC-F24-12: page layout numbers (+ 07 I-7's counter floor) -------------------------------

def test_page_layout_numbers():
    area = (24, 24, 1232, 598)
    lay = page_layout(area, max_width=800, n=10, pitch=45)
    assert lay.page == (240, 32, 800, 582) and lay.margin_x == 312
    assert [c[0] + c[2] / 2 for c in (lay.cells[0], lay.cells[5])] == [494, 858]
    assert (lay.cells[0], lay.cells[4], lay.cells[5]) == (
        (312, 218.5, 364, 53), (312, 430.5, 364, 53), (676, 218.5, 364, 53))
    assert lay.counter_at == (1008, 56) and lay.label_width == 300
    assert lay.rules == tuple(106.5 + 53 * k for k in range(10))

    lay = page_layout(area, max_width=800, n=5, pitch=45)
    assert [c[0] for c in lay.cells] == [312] * 3 + [676] * 2 and lay.cells[0][1] == 271.5
    lay = page_layout(area, max_width=800, n=2, pitch=45)
    assert lay.cells[0][1] == lay.cells[1][1] == 324.5 and lay.cells[1][0] == 676
    for width, page, margin, centers, label in (
            (1232, (24, 32, 1232, 582), 96, [386, 966], 516),
            (560, (360, 32, 560, 582), 432, None, 180)):
        lay = page_layout(area, max_width=width, n=10, pitch=45)
        assert (lay.page, lay.margin_x, lay.label_width) == (page, margin, label)
        if centers:
            assert [c[0] + c[2] / 2 for c in (lay.cells[0], lay.cells[5])] == centers

    # 150%, one-line hint: rows 75 tall from 118 to 568 (≤ 574); the counter floor
    # (page.y + 83) doesn't move them (I-7).
    for counter_h in (0, 59):
        lay = page_layout((24, 24, 1232, 582), max_width=800, n=12, pitch=67,
                          counter_h=counter_h)
        assert {c[3] for c in lay.cells} == {75}
        assert lay.cells[0][1] == 118 and lay.cells[5][1] + 75 == 568
    # A two-line hint at 150%: the rows start below the counter's line box (07 G3, I-7).
    lay = page_layout((24, 24, 1232, 540), max_width=800, n=12, pitch=67, counter_h=59)
    assert lay.cells[0][1] == 115 and lay.cells[0][3] == 69.5
    assert lay.cells[5][1] + 69.5 == lay.page[1] + lay.page[3] - 24


# --- AC-F24-13: fit from 100% to 150% (F24-3, 07 I-9; F23 s5a's minigame_frame) -------------

def test_fit_from_100_to_150_percent():
    from engine.ui.layouts import minigame_frame

    def m20(text: str, size: int) -> float:                       # M20: 20 per grapheme at 28
        return len(text) * round(20 * size / 28)

    hints = {"one": "Pick a word for your poem.",
             "two": "Pick one word for your poem from this page, then the next. " * 2}
    cases = 0
    for scale in (1.0, 1.25, 1.5):
        word, counter = poem_rules.scaled(32, scale), poem_rules.scaled(28, scale)
        pitch, counter_h = poem_rules.line_pitch(word), poem_rules.line_pitch(counter)
        for lines, hint in hints.items():
            frame = minigame_frame(scale, heading=None, hint=hint, measure=m20)
            assert len(frame.hint_lines) == (1 if lines == "one" else 2)
            a = frame.content
            for max_width in (560, 800, 1232):
                for n in range(2, 13):
                    cases += 1
                    lay = page_layout((a.x, a.y, a.w, a.h), max_width=max_width, n=n,
                                      pitch=pitch, counter_h=counter_h)
                    px, py, pw, ph = lay.page
                    for x, y, w, h in lay.cells:
                        assert px <= x and x + w <= px + pw + 1e-9
                        assert py + 80 - 1e-9 <= y and y + h <= py + ph - 24 + 1e-9
                    boxes = sorted(lay.cells)
                    for i, (x, y, w, h) in enumerate(boxes):
                        for x2, y2, w2, h2 in boxes[i + 1:]:
                            assert x + w <= x2 + 1e-9 or y + h <= y2 + 1e-9 \
                                or y2 + h2 <= y + 1e-9
                    row_h = lay.cells[0][3]
                    assert row_h >= pitch
                    if lines == "one":
                        assert row_h == max(48, pitch + 8)
                    cw = m20("50 / 50", counter)                  # the counter's box (G3)
                    cx, cy = lay.counter_at
                    assert px <= cx - cw and cx <= px + pw and cy + counter_h <= py + ph
                    assert cy + counter_h <= min(y for _, y, _, _ in lay.cells) + 1e-9
    assert cases == 198
