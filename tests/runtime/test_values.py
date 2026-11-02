"""``freeze``, ``kind_words``, and the saveable-value rules (F03 04 §7.4, SR-F03-10/33).

ACs: AC-F03-18 (the values that save, unit half), AC-F03-19 (the unit rows: kinds, paths,
exact-type subclasses), TR-F03-12, TR-F03-03 (the snapshot shares nothing; unit half).
"""

import collections
import enum
import math
import types

import pytest

from engine.runtime import limits
from engine.runtime.values import (BIG_INT, INF, KEY, KIND, NAN, TOO_DEEP, Unsaveable, freeze,
                                   kind_words, plain_copy, same_value)


def nested(levels: int) -> list:
    """``[]`` wrapped ``levels - 1`` times: a list nested exactly ``levels`` levels."""
    v: list = []
    for _ in range(levels - 1):
        v = [v]
    return v


def type_tree(v):
    if type(v) is list:
        return ["list", [type_tree(x) for x in v]]
    if type(v) is dict:
        return ["dict", [[k, type_tree(x)] for k, x in v.items()]]
    if type(v) is float:
        return ["float", math.copysign(1.0, v)]
    return type(v).__name__


SAVEABLE = [
    None, True, False, 0, -7, 1.5, -0.0, 1e308, 5e-324,
    10**4300 - 1, -(10**4300 - 1),
    "", "日本語 😀 עברית", "\ud800",
    [], {}, {"": 1}, {"a": [1, {"b": None}]}, {f"k{i}": i for i in range(1000)},
    nested(100),
    [2**62, -(2**62), 2**62 - 1, 2**200, True, 1.0, None, "x"],
]


@pytest.mark.parametrize("value", SAVEABLE, ids=range(len(SAVEABLE)))
def test_freeze_accepts_and_copies_saveable_values(value):
    frozen = freeze(value)
    assert same_value(frozen, value)
    assert type_tree(frozen) == type_tree(value)
    if type(value) in (list, dict):
        assert frozen is not value


def test_freeze_shares_no_container():
    inner = [2]
    value = {"deck": [1, inner], "map": {"k": inner}}
    frozen = freeze(value)
    inner.append(3)
    value["deck"].append(4)
    assert frozen == {"deck": [1, [2]], "map": {"k": [2]}}
    assert frozen["deck"][1] is not frozen["map"]["k"]


def test_int_limit_tr_f03_12():
    assert limits.INT_LIMIT == 10**4300
    assert freeze(10**4300 - 1) == 10**4300 - 1
    assert freeze(-(10**4300 - 1)) == -(10**4300 - 1)
    for big in (10**4300, -(10**4300), 10**5000):
        with pytest.raises(Unsaveable) as caught:
            freeze(big)
        assert caught.value.reason == BIG_INT
    with pytest.raises(Unsaveable):
        freeze([1, 10**4300])


def test_depth_limit():
    freeze(nested(100))
    with pytest.raises(Unsaveable) as caught:
        freeze(nested(101))
    assert caught.value.reason == TOO_DEEP
    assert caught.value.path == ()


def test_self_containing_list_is_too_deep():
    party: list = []
    party.append(party)
    with pytest.raises(Unsaveable) as caught:
        freeze(party)
    assert caught.value.reason == TOO_DEEP
    assert caught.value.path_text("party") == "party"
    d: dict = {}
    d["self"] = d
    with pytest.raises(Unsaveable) as caught:
        freeze(d)
    assert caught.value.reason == TOO_DEEP


class Lantern:
    pass


def plain_function():
    return 1


@pytest.mark.parametrize("value, reason, kind", [
    (set(), KIND, "a set"),
    (frozenset(), KIND, "a set"),
    (lambda: 1, KIND, "a function"),
    (plain_function, KIND, "a function"),
    (len, KIND, "a function"),
    ("abc".upper, KIND, "a function"),
    (Lantern().__init__, KIND, "a function"),
    (math, KIND, "a module"),
    (range(3), KIND, "a Python object (range)"),
    (Lantern(), KIND, "a Python object (Lantern)"),
    ((1, 2), KIND, "a tuple"),
    (float("nan"), NAN, "a decimal number"),
    (float("inf"), INF, "a decimal number"),
    (float("-inf"), INF, "a decimal number"),
    (collections.OrderedDict(), KIND, "a Python object (OrderedDict)"),
    (collections.defaultdict(list), KIND, "a Python object (defaultdict)"),
    (enum.IntEnum("Mood", "HAPPY").HAPPY, KIND, "a Python object (Mood)"),
    (type("Name", (str,), {})("x"), KIND, "a Python object (Name)"),
    (type("Big", (int,), {})(3), KIND, "a Python object (Big)"),
    (type("Seq", (list,), {})(), KIND, "a Python object (Seq)"),
])
def test_freeze_refuses(value, reason, kind):
    with pytest.raises(Unsaveable) as caught:
        freeze(value)
    assert caught.value.reason == reason
    assert caught.value.value is value
    assert caught.value.kind == kind
    assert caught.value.path == ()


def test_key_that_isnt_text():
    with pytest.raises(Unsaveable) as caught:
        freeze({"a": 1, 3: "a"})
    error = caught.value
    assert error.reason == KEY
    assert error.value == 3
    assert error.path_text("scores") == "scores"


@pytest.mark.parametrize("value, path, text", [
    ({"bag": [1, 2, {3}]}, ("bag", 2), 'inventory["bag"][2]'),
    ([0, [1, [2, (3,)]]], (1, 1, 1), "inventory[1][1][1]"),
    ({"a": {"b": {1: 2}}}, ("a", "b"), 'inventory["a"]["b"]'),
    ({'q"\\': [float("nan")]}, ('q"\\', 0), 'inventory["q\\"\\\\"][0]'),
    ([1, 2**63, 10**4300], (2,), "inventory[2]"),
])
def test_paths(value, path, text):
    with pytest.raises(Unsaveable) as caught:
        freeze(value)
    assert caught.value.path == path
    assert caught.value.path_text("inventory") == text


def test_path_names_first_failing_occurrence():
    shared = [set()]
    with pytest.raises(Unsaveable) as caught:
        freeze({"x": 1, "first": shared, "second": shared})
    assert caught.value.path == ("first", 0)


def test_unsaveable_text_never_contains_the_value():
    with pytest.raises(Unsaveable) as caught:
        freeze({"ZZMARK": {"ZZMARK"}})
    assert "ZZMARK" not in str(caught.value)


@pytest.mark.parametrize("value, words", [
    (None, "nothing (None)"), (True, "True or False"), (0, "a whole number"),
    (1.5, "a decimal number"), ("x", "text"), ([], "a list"), ({}, "a dictionary"),
    ((), "a tuple"), (set(), "a set"), (frozenset(), "a set"), (len, "a function"),
    (lambda: 0, "a function"), ("x".upper, "a function"), (types, "a module"),
    (Lantern(), "a Python object (Lantern)"),
])
def test_kind_words_sr_f03_33(value, words):
    assert kind_words(value) == words


def test_kind_words_for_the_dice():
    from engine.runtime.dice import Pcg32, make_dice
    dice = make_dice(Pcg32())
    assert kind_words(dice) == "the dice"
    with pytest.raises(Unsaveable) as caught:
        freeze({"d": dice})
    assert caught.value.kind == "the dice"
    assert caught.value.path == ("d",)


def test_plain_copy_is_deep():
    value = {"a": [1, {"b": [2]}], "c": "x"}
    copy = plain_copy(value)
    assert copy == value
    copy["a"][1]["b"].append(3)
    assert value == {"a": [1, {"b": [2]}], "c": "x"}


@pytest.mark.parametrize("a, b, same", [
    (1, True, False), (1, 1.0, False), (0.0, -0.0, False), (-0.0, -0.0, True),
    ([1, [2]], [1, [2]], True), ([1], [True], False), ({"a": 1}, {"a": 1.0}, False),
    ({"a": 1, "b": 2}, {"b": 2, "a": 1}, True), ({"a": 1}, {"b": 1}, False),
])
def test_same_value(a, b, same):
    assert same_value(a, b) is same
