"""F11 C11: ``GameState.save_problem()`` (F11 ``04`` §7.3 step 2).

A reason word for anything ``take_checkpoint`` allows that wouldn't load back equal: what
``from_json`` refuses (§9.1 limits: variable count, names, sid and hint lengths, hint path,
member count) and, by the project's decision, any string holding a lone high
surrogate right before a lone low one (JSON reads the two back as one character); any other
lone surrogate round-trips as an escape and stays saveable. None means the state, written
with ``ensure_ascii=True`` and read back, is equal.
"""

import json
import random
import statistics
import time
from types import MappingProxyType

import pytest

from engine.runtime import limits
from engine.runtime.state import GameState, StateInvalid, _valid_name
from engine.runtime.values import freeze
from tests.runtime.conftest import make_state
from tests.runtime.test_values import nested


def read_back(state: GameState) -> GameState:
    return GameState.from_json(json.loads(json.dumps(state.to_json(), ensure_ascii=True)))


def loads_back_equal(state: GameState) -> bool:
    try:
        return read_back(state) == state
    except StateInvalid:
        return False


def problem(variables=None, **kwargs) -> str | None:
    return make_state(variables, **kwargs).save_problem()


# --- Each limit, at and over --------------------------------------------------------------------

CAP = limits.POSITION_MAX_CHARS
HINT = limits.HINT_MAX_PATH
ROWS = {
    "nothing": ({}, {}, None),
    "variables at the cap": ({f"v{i}": 0 for i in range(limits.STATE_MAX_NAMES)}, {}, None),
    "one variable over": ({f"v{i}": 0 for i in range(limits.STATE_MAX_NAMES + 1)}, {},
                          "too_many_names"),
    "sid at the cap": ({}, {"position": "s" * CAP}, None),
    "sid over": ({}, {"position": "s" * (CAP + 1)}, "position"),
    "hint label at the cap": ({}, {"at": ("l" * CAP, (2,))}, None),
    "hint label over": ({}, {"at": ("l" * (CAP + 1), (2,))}, "hint"),
    "hint path at the cap": ({}, {"at": ("start", (0,) * HINT)}, None),
    "hint path over": ({}, {"at": ("start", (0,) * (HINT + 1))}, "hint"),
    "call sid over": ({}, {"call_stack": [("c" * (CAP + 1), ("start", (1,)))]}, "call_stack"),
    "call hint over": ({}, {"call_stack": [("c", ("l" * (CAP + 1), (1,)))]}, "hint"),
    "call stack at the cap": ({}, {"call_stack": [("c", ("start", (1,)))]
                                   * limits.CALL_DEPTH_MAX}, None),
    "call stack over": ({}, {"call_stack": [("c", ("start", (1,)))]
                             * (limits.CALL_DEPTH_MAX + 1)}, "call_stack_too_deep"),
    "one member over": ({"a": [0] * (limits.STATE_MAX_ITEMS - 1), "b": {"k": [0]}}, {},
                        "too_many_items"),
    "name of 255": ({"a" * 255: 1}, {}, None),
    "name of 256": ({"a" * 256: 1}, {}, "variable_name"),
    "lone high surrogate": ({"s": "a\ud800"}, {}, None),
    "lone low surrogate deep": ({"s": [{"k": ["ok", ["\udfff"]]}]}, {}, None),
    "lone surrogate key": ({"s": {"\udc00": 1}}, {}, None),
    "low then high": ({"s": "\udfff\ud800"}, {}, None),
    "high, high": ({"s": "\ud800\ud800"}, {}, None),
    "pair across two strings": ({"s": ["\ud800", "\udfff"], "t": "\udfff"}, {},
                                None),
    "pair across two keys": ({"s": {"\ud800": 1, "\udfff": 2}}, {}, None),
    "lone surrogates in the sid and hint": ({}, {"position": "start/\ud800",
                                                 "at": ("\udfff", (2,))}, None),
    "surrogate pair": ({"s": "\ud800\udfff"}, {}, "lone_surrogate"),
    "pair after a lone one": ({"s": "\udfffx\ud800\udc00"}, {}, "lone_surrogate"),
    "pair deep": ({"s": [{"k": ["ok", ["a\ud800\udc00b"]]}]}, {}, "lone_surrogate"),
    "pair in a key": ({"s": {"k\ud800\udfff": 1}}, {}, "lone_surrogate"),
    "pair in the sid": ({}, {"position": "start/\ud800\udfff"}, "lone_surrogate"),
    "pair in a hint": ({}, {"at": ("\ud800\udfff", (2,))}, "lone_surrogate"),
    "astral and non-ASCII": ({"s": "\U0001f338 é 花", "d": {"\U0001f338": ["é"]}}, {}, None),
    "every kind": ({"a": None, "b": True, "c": -0.0, "d": 10**4299, "e": "x",
                    "f": [1, "y", [2.5, {"k": None}]], "g": {}}, {}, None),
    "depth 100": ({"n": nested(100)}, {}, None),
}


# Full-size rows (2,000,000 members, 0.6-0.9 s each; test-review-F03.md). "one member over"
# stays in the default run for the too_many_items branch; the 600,000-member guards below
# show that big states below the cap give None.
SLOW_ROWS = {
    "members at the cap": ({"a": [0] * (limits.STATE_MAX_ITEMS - 2), "b": {"k": [0]}}, {},
                           None),
    "members over, nested": ({"a": [[0] * 1000] * (limits.STATE_MAX_ITEMS // 1000)}, {},
                             "too_many_items"),
}


@pytest.mark.parametrize("variables, fields, word",
                         [*ROWS.values(), *(pytest.param(*row, marks=pytest.mark.slow)
                                            for row in SLOW_ROWS.values())],
                         ids=[*ROWS, *SLOW_ROWS])
def test_each_limit(variables, fields, word):
    state = make_state(variables, **fields)
    assert state.save_problem() == word
    if word is None:
        assert loads_back_equal(state)
    if word in ("too_many_names", "variable_name", "too_many_items", "hint", "position",
                "call_stack", "call_stack_too_deep"):
        with pytest.raises(StateInvalid) as refused:
            read_back(state)
        assert refused.value.reason == word


def test_a_word_is_a_reason_word():
    import re
    for _, _, word in [*ROWS.values(), *SLOW_ROWS.values()]:
        assert word is None or re.fullmatch(r"[a-z_]{1,40}", word)


# --- Names: exactly _valid_name -----------------------------------------------------------------

NAMES = ["a", "Z9", "trust", "len", "print", "x" * 255, "x" * 256, "", "_x", "__x", "9a",
         "a b", "a\nb", "a-b", "a\x00", "if", "True", "None", "class", "async", "dice",
         "Character", "persistent", "narrator", "module", "engine", "é", "名前", "ﬁx", "Ⅸ",
         "x́", "été", "a‍", "a" * 254 + "é", "é" * 256, "a\ud800"]


@pytest.mark.parametrize("name", NAMES, ids=[repr(n)[:20] for n in NAMES])
def test_names_match_valid_name(name):
    expected = None if _valid_name(name) else "variable_name"
    if expected is None and "\ud800" in name:
        expected = "lone_surrogate"
    assert problem({name: 1}) == expected
    assert problem({"ok": 1, name: 1, "zz": 2}) == expected


def test_one_bad_name_among_many():
    rng = random.Random(7)
    good = {f"v{i}": i for i in range(5000)}
    assert problem(good) is None
    for bad in ("_x", "if", "9a", "a\nb", "ﬁx", "x" * 256, "dice"):
        names = list(good)
        names.insert(rng.randrange(len(names)), bad)
        assert problem(dict.fromkeys(names, 0)) == "variable_name", bad
    assert problem({**good, "é": 1}) is None


def test_a_name_that_is_not_text():
    state = GameState(position="p", position_at=("start", (0,)), call_stack=(),
                      variables=MappingProxyType({1: 2}), dice=0)
    assert state.save_problem() == "variable_name"


# --- Hand-built states (never from take_checkpoint or from_json) --------------------------------

def test_hand_built_values():
    assert problem({"t": (1, 2)}) == "variable_value"
    assert problem({"t": [1, {2: 3}]}) == "variable_value"
    loop: list = []
    loop.append(loop)
    assert problem({"t": loop}) == "variable_value"
    assert problem({"t": nested(101)}) == "variable_value"
    assert problem({"t": [nested(100), [nested(99)], "x"]}) == "variable_value"
    assert problem({"t": [nested(99), [nested(98)], "x"]}) is None     # 100 levels


# --- None means it loads back equal; changes nothing --------------------------------------------

def _value(rng: random.Random, depth: int = 0):
    kind = rng.randrange(8 if depth < 5 else 5)
    if kind == 0:
        return rng.choice((None, True, False))
    if kind == 1:
        return rng.choice((0, -1, 2**63, 10**300, -0.0, 0.5, 1e300))
    if kind in (2, 3, 4):
        return "".join(rng.choice(("a", "é", "花", "\U0001f338", "\"", "\\", "\n", "\ud800",
                                   "\udfff")) for _ in range(rng.randint(0, 4)))
    if kind in (5, 6):
        return [_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {_value(rng, 9) if rng.random() < 0.9 else "k": _value(rng, depth + 1)
            for _ in range(rng.randint(0, 4))}


def test_none_means_it_loads_back_equal():
    """300 random states, in one loop (300 test items cost more than the checks)."""
    for seed in range(300):
        try:
            _check_random_state(seed)
        except AssertionError as error:
            raise AssertionError(f"seed {seed}") from error


def _check_random_state(seed: int) -> None:
    rng = random.Random(seed)
    variables = {}
    for i in range(rng.randint(0, 6)):
        value = _value(rng)
        try:
            variables[f"v{i}"] = freeze(value)
        except Exception:
            pass
    state = make_state(variables)
    snapshot = state.to_json()
    word = state.save_problem()
    assert state.to_json() == snapshot
    assert word in (None, "lone_surrogate")
    text = json.dumps(snapshot, ensure_ascii=False)        # quotes keep strings apart
    paired = any(0xD800 <= ord(a) <= 0xDBFF and 0xDC00 <= ord(b) <= 0xDFFF
                 for a, b in zip(text, text[1:]))
    assert (word == "lone_surrogate") is paired
    if word is None:
        assert loads_back_equal(state)


# --- Fast (F11 §7.3 runs it inside one encoder step) --------------------------------------------

SHAPES = {
    "600,000 ints": lambda: {"v": list(range(600_000))},
    "600,000 strings": lambda: {"v": [f"s{i}" for i in range(600_000)]},
    "150,000 dicts of 3": lambda: {"v": [{"a": i, "b": "x", "c": 1.5}
                                         for i in range(150_000)]},
    "100,000 variables of 5": lambda: {f"v{i}": [i, i, "t", None, True]
                                       for i in range(100_000)},
}


@pytest.mark.parametrize("shape", SHAPES.values(), ids=SHAPES.keys())
def test_600k_members_ci_guard(shape):
    """Records the median at about 600,000 members; fails only if it is far off (the
    development machine measured 6-40 ms; the stand-in it replaces 45-80 ms)."""
    state = make_state(shape())
    times = []
    for _ in range(3):
        start = time.perf_counter()
        assert state.save_problem() is None
        times.append(time.perf_counter() - start)
    median = statistics.median(times)
    print(f"save_problem median: {median * 1000:.2f} ms")
    assert median <= 0.25
