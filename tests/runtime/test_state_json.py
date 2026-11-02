"""``GameState``, its JSON form, and ``from_json``'s trust boundary (F03 04 §4.2, §9, §9.1).

Phase 1 uses hand-built states. ACs: AC-F03-18 and AC-F03-55 (round trip, unit half),
AC-F03-54 (shape, unit half), AC-F03-57 (frozen fields; I-9), AC-F03-62 (all rows,
``from_json`` half), AC-F03-64 (``from_json`` half), TR-F03-01/04 (``from_json`` part).
"""

import dataclasses
import json
import re
import time
from types import MappingProxyType

import pytest

from engine.runtime import limits
from engine.runtime.state import STATE_FORMAT, GameState, StateInvalid
from tests.runtime import fuzz_state
from tests.runtime.conftest import (CALL_SID, SID_LINE_9, make_state, round_trip,
                                    state_b_json)
from tests.runtime.test_values import SAVEABLE, nested, type_tree

REASON = re.compile(r"^[a-z_]{1,40}$")


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=True)


# --- Shape and round trip -----------------------------------------------------------------

def test_json_shape_ac_54():
    state = make_state({"trust": 0, "hana_name": "???"}, at=("start", (0,)))
    assert state.to_json() == {
        "format": 1, "identity_scheme": 1,
        "position": {"sid": SID_LINE_9, "at": ["start", [0]]},
        "call_stack": [], "variables": {"trust": 0, "hana_name": "???"},
        "dice": "977afd8015414a94",
        "stage": {"background": None, "sprites": []},           # F04: always written
        "audio": {"music": [], "sounds": []},                   # F08: always written
        "choices": {"picks": [], "waiting": None},    # F07: always written
        "history": {"entries": []},                             # F13: always written
        "chapter": {"current": None},                           # F18: always written
        "points": {"values": {}},                               # F22: always written
        "rollback": {"enabled": True},                          # F14: always written
        "nvl": {"on": False, "page": []},                       # F17: always written
        "items": {"held": []},                                  # F21: always written
        "minigame": {"waiting": None},                          # F23: always written
        "flow": {"path": []},                                   # F20: always written
        "glitch": {"on": []},                                   # F28: always written
    }
    assert dumps(state.to_json()).isascii()
    deep = make_state(call_stack=[(CALL_SID, ("b", (1,)))])
    assert deep.to_json()["call_stack"] == [{"sid": CALL_SID, "at": ["b", [1]]}]


@pytest.mark.parametrize("dice", [0, 1, 2**64 - 1, 0x8F3A5C0E12D4B7A9])
def test_dice_is_16_lowercase_hex(dice):
    text = make_state(dice=dice).to_json()["dice"]
    assert re.fullmatch(r"[0-9a-f]{16}", text)
    assert round_trip(make_state(dice=dice)).dice == dice


@pytest.mark.parametrize("value", SAVEABLE, ids=range(len(SAVEABLE)))
def test_round_trip_keeps_value_and_type_ac_18_55(value):
    state = make_state({"v": value, "after": 1})
    again = round_trip(state)
    assert again == state
    assert type_tree(again.variables["v"]) == type_tree(value)
    assert list(again.variables) == ["v", "after"]
    assert dumps(again.to_json()) == dumps(state.to_json())


def test_round_trip_full_state():
    state = make_state({"trust": 2, "deck": [3, 1, 2], "m": {"z": 1, "a": [None]}},
                       at=("riverbank", (3, 0, 1)),
                       call_stack=[(CALL_SID, ("start", (4,))), ("b/aaaaaaaaaaaa~2", ("b", ()))],
                       dice=2**64 - 1, identity_scheme=7)
    again = round_trip(state)
    assert again == state
    assert again.position_at == ("riverbank", (3, 0, 1))
    assert again.call_stack == ((CALL_SID, ("start", (4,))), ("b/aaaaaaaaaaaa~2", ("b", ())))
    assert list(again.variables["m"]) == ["z", "a"]


def test_identity_scheme_defaults_to_the_scripts_scheme():
    # F03 step 4: the default comes from F02's identity.py, never a copied constant (I-6).
    from engine.script.identity import IDENTITY_SCHEME
    state = GameState(position=SID_LINE_9, position_at=("start", (0,)), call_stack=(),
                      variables={}, dice=0)
    assert state.identity_scheme == IDENTITY_SCHEME
    assert round_trip(state).identity_scheme == IDENTITY_SCHEME


def test_equality_is_by_exact_type():
    assert make_state({"a": 1}) != make_state({"a": True})
    assert make_state({"a": 1}) != make_state({"a": 1.0})
    assert make_state({"a": 0.0}) != make_state({"a": -0.0})
    assert make_state({"a": [1]}) == make_state({"a": [1]})
    assert make_state({"a": 1}) != make_state({"a": 1, "b": 2})
    assert make_state(dice=1) != make_state(dice=2)


def test_state_is_frozen_ac_57():
    state = make_state({"deck": [1, [2]]})
    with pytest.raises(TypeError):
        state.variables["deck"] = 1          # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.dice = 1                       # type: ignore[misc]
    assert type(state.variables) is MappingProxyType
    with pytest.raises(TypeError):
        hash(state)


def test_to_json_hands_out_copies_i_9():
    state = make_state({"deck": [1, [2]], "m": {"k": [3]}})
    before = dumps(state.to_json())
    out = state.to_json()
    out["variables"]["deck"][1].append(9)
    out["variables"]["m"]["k"].clear()
    out["call_stack"].append("x")
    assert dumps(state.to_json()) == before


def test_from_json_shares_nothing_with_its_input():
    obj = make_state({"deck": [1, [2]]}).to_json()
    state = GameState.from_json(obj)
    obj["variables"]["deck"][1].append(3)
    obj["position"]["at"][1].append(5)
    assert state.variables["deck"] == [1, [2]]
    assert state.position_at == ("start", (2,))


# --- AC-F03-62: hostile state data --------------------------------------------------------

def edit(path, value=None, *, delete=False, add=None):
    """A function that applies one edit to a fresh copy of B."""
    def apply():
        obj = state_b_json()
        if path == ():
            return value
        target = obj
        for key in path[:-1]:
            target = target[key]
        if delete:
            del target[path[-1]]
        elif add is not None:
            target[path[-1]][add[0]] = add[1]
        else:
            target[path[-1]] = value
        return obj
    return apply


def var(name, value=0):
    def apply():
        obj = state_b_json()
        obj["variables"] = {name: value}
        return obj
    return apply


def many_names(n):
    def apply():
        obj = state_b_json()
        obj["variables"] = {f"v{i}": 0 for i in range(n)}
        return obj
    return apply


def items_total(n):
    """``n`` list members in total, spread over two variables."""
    def apply():
        obj = state_b_json()
        half = n // 2
        obj["variables"] = {"a": [0] * half, "b": [[1, 2]] * ((n - half) // 3) + [0] * ((n - half) % 3)}
        return obj
    return apply


SID = "start/3fa9c2d81b07"

REJECTED = {
    "whole list": edit((), []),
    "whole None": edit((), None),
    "whole str": edit((), "x"),
    "extra key": edit(("ZZMARK",), 1),
    "voice key (I-2)": edit(("voice",), None),
    "missing dice": edit(("dice",), delete=True),
    "missing variables": edit(("variables",), delete=True),
    "format True": edit(("format",), True),
    "format 1.0": edit(("format",), 1.0),
    "format '1'": edit(("format",), "1"),
    "format 2": edit(("format",), 2),
    "scheme True": edit(("identity_scheme",), True),
    "scheme 1.0": edit(("identity_scheme",), 1.0),
    "position not a dict": edit(("position",), "x"),
    "position sid 5": edit(("position",), {"sid": 5, "at": ["start", [0]]}),
    "position ['x']": edit(("position",), ["x"]),
    "position sid 1025": edit(("position", "sid"), "s" * 1025),
    "position sid 10 MB": edit(("position", "sid"), "ZZMARK" * 2_000_000),
    "position extra key": edit(("position",), {"sid": SID, "at": ["start", [0]], "x": 1}),
    "position missing at": edit(("position",), {"sid": SID}),
    "at 'x'": edit(("position", "at"), "x"),
    "at label 1025": edit(("position", "at"), ["l" * 1025, [0]]),
    "at path 129": edit(("position", "at"), ["start", [0] * 129]),
    "at path [true]": edit(("position", "at"), ["start", [True]]),
    "at path [1.0]": edit(("position", "at"), ["start", [1.0]]),
    "at tuple": edit(("position", "at"), ("start", [0])),
    "at three items": edit(("position", "at"), ["start", [0], 1]),
    "call_stack not a list": edit(("call_stack",), {"sid": SID}),
    "call_stack 1001": edit(("call_stack",), [{"sid": CALL_SID, "at": ["start", [4]]}] * 1001),
    "call_stack bad entry": edit(("call_stack",), [{"sid": 5, "at": ["start", [4]]}]),
    "variables not a dict": edit(("variables",), [["a", 1]]),
    "name __builtins__": var("__builtins__"),
    "name dice": var("dice"),
    "name Character": var("Character"),
    "name module": var("module"),
    "name persistent": var("persistent"),
    "name _x": var("_x"),
    "name a b": var("a b"),
    "name 1a": var("1a"),
    "name class": var("class"),
    "name ﬁx (not NFKC)": var("ﬁx"),
    "name 256 chars": var("n" * 256),
    "name ZZMARK x": var("ZZMARK x"),
    "name empty": var(""),
    "value nan": var("v", float("nan")),
    "value inf": var("v", float("inf")),
    "value -inf": var("v", float("-inf")),
    "value 10**4300": var("v", 10**4300),
    "value 101 levels": var("v", nested(101)),
    "value tuple": var("v", (1, 2)),
    "value {1: 2}": var("v", {1: 2}),
    "value set": var("v", {"ZZMARK"}),
    "dice upper": edit(("dice",), "8F3A5C0E12D4B7A9"),
    "dice 15": edit(("dice",), "8f3a5c0e12d4b7a"),
    "dice 17": edit(("dice",), "8f3a5c0e12d4b7a90"),
    "dice -1": edit(("dice",), "-1"),
    "dice int": edit(("dice",), 12345),
    "dice ZZMARK": edit(("dice",), "ZZMARK"),
    "dice newline": edit(("dice",), "8f3a5c0e12d4b7a\n"),
}

REJECTED_SLOW = {
    "100,001 names": many_names(limits.STATE_MAX_NAMES + 1),
    "2,000,001 items": items_total(limits.STATE_MAX_ITEMS + 1),
}

ACCEPTED = {
    "B": edit(("format",), 1),
    "scheme 999": edit(("identity_scheme",), 999),
    "sid 1024": edit(("position", "sid"), "s" * 1024),
    "path 128": edit(("position", "at"), ["start", [0] * 128]),
    "path negative": edit(("position", "at"), ["start", [-1]]),
    "call_stack 1000": edit(("call_stack",), [{"sid": CALL_SID, "at": ["start", [4]]}] * 1000),
    "name len": var("len"),
    "name 255": var("n" * 255),
    "name fortunes": var("fortunes"),
    "name non-ASCII NFKC": var("café"),
    "name soft keyword": var("match"),
    "value 100 levels": var("v", nested(100)),
    "value big int": var("v", 10**4300 - 1),
    "value lone surrogate": var("v", "\ud800ZZMARK"),
    "dice ffff": edit(("dice",), "ffffffffffffffff"),
    "dice 0000": edit(("dice",), "0000000000000000"),
}

ACCEPTED_SLOW = {
    "100,000 names": many_names(limits.STATE_MAX_NAMES),
    "2,000,000 items": items_total(limits.STATE_MAX_ITEMS),
}


def check_rejected(build):
    obj = build()
    start = time.perf_counter()
    with pytest.raises(StateInvalid) as caught:
        GameState.from_json(obj)
    assert time.perf_counter() - start < 1.0
    error = caught.value
    assert type(error) is StateInvalid
    assert REASON.match(error.reason)
    assert "ZZMARK" not in str(error) and "ZZMARK" not in repr(error)
    assert error.__cause__ is None and error.__suppress_context__ or error.__context__ is None


@pytest.mark.parametrize("build", REJECTED.values(), ids=REJECTED.keys())
def test_hostile_rows_rejected_ac_62(build):
    check_rejected(build)


@pytest.mark.slow
@pytest.mark.parametrize("build", REJECTED_SLOW.values(), ids=REJECTED_SLOW.keys())
def test_hostile_rows_rejected_slow_ac_62(build):
    check_rejected(build)


def check_accepted(build):
    obj = build()
    start = time.perf_counter()
    state = GameState.from_json(obj)
    assert time.perf_counter() - start < 1.0
    assert type(state) is GameState
    assert GameState.from_json(json.loads(dumps(state.to_json()))) == state


@pytest.mark.parametrize("build", ACCEPTED.values(), ids=ACCEPTED.keys())
def test_rows_accepted_ac_62(build):
    check_accepted(build)


@pytest.mark.slow
@pytest.mark.parametrize("build", ACCEPTED_SLOW.values(), ids=ACCEPTED_SLOW.keys())
def test_rows_accepted_slow_ac_62(build):
    check_accepted(build)


def test_missing_voice_is_the_normal_shape():
    assert "voice" not in state_b_json()
    assert GameState.from_json(state_b_json()).identity_scheme == 1


def test_specific_reasons():
    def reason(build):
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json(build())
        return caught.value.reason
    assert reason(REJECTED["extra key"]) == "unknown_key"
    assert reason(REJECTED["missing dice"]) == "missing_key"
    assert reason(REJECTED["format 2"]) == "format"
    assert reason(REJECTED["value nan"]) == "variable_value"
    assert reason(REJECTED["name dice"]) == "variable_name"
    # "too_many_items" (2,000,001 items, 0.6 s): test_save_problem.py's "one member over" row.


def test_format_constant():
    assert STATE_FORMAT == 1


# --- AC-F03-64: fuzzing (from_json half) --------------------------------------------------

def fuzz_bases() -> list[dict]:
    return [
        state_b_json(),
        make_state({"trust": 2, "deck": [3, 1, 2], "inv": {"bag": [1, {"k": None}]},
                    "name": "Hana", "luck": 0.5, "flag": True},
                   at=("riverbank", (3, 0, 1)),
                   call_stack=[(CALL_SID, ("start", (4,)))], dice=2**63).to_json(),
    ]


def run_fuzz(count: int, seed: int, inflate: bool = False) -> int:
    accepted = 0
    for obj in fuzz_state.mutations(fuzz_bases(), count, seed, inflate):
        try:
            state = GameState.from_json(obj)
        except StateInvalid as error:
            assert REASON.match(error.reason)
            assert "ZZMARK" not in str(error)
            continue
        accepted += 1
        assert round_trip(state) == state
    return accepted


def test_fuzz_ci_ac_64():
    accepted = run_fuzz(200, seed=64)
    assert 0 < accepted < 200


@pytest.mark.slow
def test_fuzz_full_ac_64():
    start = time.perf_counter()
    run_fuzz(10_000, seed=6400, inflate=True)
    assert time.perf_counter() - start < 600
