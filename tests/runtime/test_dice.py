"""PCG32 and the ``dice`` front object (F03 04 §7.8).

ACs: AC-F03-39 (all), AC-F03-41 (all), TR-F03-13 / AC-F03-40's unit part, AC-F03-40's
E85j/E85c/E85k fields (the message texts are phase 2). TR-F03-06 (same results under any
``PYTHONHASHSEED``): ``test_determinism.py``'s AC-F03-67 runs this call script
(``golden_document``) under hash seeds 0, 1, and ``random`` and compares it with the golden.
"""

import json

import pytest

from engine.runtime.dice import (DICE_CALLS, DiceArgumentError, DiceFacade, DiceNotReady, Pcg32,
                                 make_dice)
from tests.runtime.conftest import FIXTURES

GOLDEN = FIXTURES / "dice_golden.json"
GOLDEN_SEEDS = (0, 1, 42, 2**64 - 1)
PICK_ITEMS = list("abcdefg")
REPS = 1000

CHI_DF2 = 13.82
CHI_DF5 = 20.52


def seeded(seed: int = 42):
    core = Pcg32()
    core.seed(seed)
    return core, make_dice(core)


def chi_square(counts, expected):
    return sum((c - expected) ** 2 / expected for c in counts)


def call_script(seed: int) -> dict:
    """06-acceptance §5.6: per repetition, ``roll(1, 6)``, ``pick`` of 7 items,
    ``decimal()``, ``shuffle`` of 10 items, ``roll(0, 2**40)``; 1,000 repetitions."""
    _, dice = seeded(seed)
    out = {"roll_1_6": [], "pick_7": [], "decimal": [], "shuffle_10": [], "roll_0_2p40": []}
    for _ in range(REPS):
        out["roll_1_6"].append(dice.roll(1, 6))
        out["pick_7"].append(dice.pick(PICK_ITEMS))
        out["decimal"].append(dice.decimal())
        out["shuffle_10"].append("".join(map(str, dice.shuffle(list(range(10))))))
        out["roll_0_2p40"].append(dice.roll(0, 2**40))
    out["pick_7"] = "".join(out["pick_7"])
    return out


def golden_document() -> dict:
    return {"seeds": {str(seed): call_script(seed) for seed in GOLDEN_SEEDS}}


# --- AC-F03-41 ----------------------------------------------------------------------------

def test_pcg32_reference_vectors_ac_41():
    core = Pcg32()
    core.seed(42)
    assert core.state == 0x977AFD8015414A94
    assert core.ready
    assert [core.next32() for _ in range(6)] == [
        0xC2F57BD6, 0x6B07C4A9, 0x72B7B29B, 0x44215383, 0xF5AF5EAD, 0x68BEB632]
    core.seed(0)
    assert [core.next32() for _ in range(3)] == [0xE823A24E, 0x7A7ECBD9, 0x89FD6C06]


def test_pcg32_published_pcg_c_basic_stream():
    """The (42, 54) vector of pcg-c-basic, through the same step with increment 109."""
    import engine.runtime.dice as dice_module
    core = Pcg32()
    saved = dice_module.PCG_INCREMENT
    dice_module.PCG_INCREMENT = (54 << 1) | 1
    try:
        core.seed(42)
        assert [core.next32() for _ in range(6)] == [
            0xA15C02B7, 0x7B47F409, 0xBA1D3330, 0x83D2F293, 0xBFA4784B, 0xCBED606E]
    finally:
        dice_module.PCG_INCREMENT = saved


@pytest.mark.parametrize("bad", [-1, 2**64, 1.0, True, "1"])
def test_seed_range(bad):
    with pytest.raises(ValueError):
        Pcg32().seed(bad)


def test_golden_ac_41():
    assert GOLDEN.is_file(), "commit tests/fixtures/F03/dice_golden.json (§5.6)"
    assert json.loads(GOLDEN.read_text(encoding="utf-8")) == golden_document()


# --- AC-F03-39 ----------------------------------------------------------------------------

def test_roll_ac_39():
    _, dice = seeded()
    counts = [0] * 6
    for _ in range(60_000):
        v = dice.roll(1, 6)
        assert 1 <= v <= 6
        counts[v - 1] += 1
    assert chi_square(counts, 10_000) <= CHI_DF5
    assert dice.roll(5, 5) == 5
    assert all(-3 <= dice.roll(-3, -1) <= -1 for _ in range(100))
    assert all(0 <= dice.roll(0, 2**64) <= 2**64 for _ in range(1000))


def test_pick_ac_39():
    _, dice = seeded()
    assert dice.pick(["a"]) == "a"
    items = ["a", "b", "c"]
    counts = dict.fromkeys(items, 0)
    for _ in range(30_000):
        counts[dice.pick(items)] += 1
    assert chi_square(counts.values(), 10_000) <= CHI_DF2


def test_decimal_ac_39():
    core, dice = seeded()
    total = 0.0
    for _ in range(100_000):
        d = dice.decimal()
        assert type(d) is float and 0.0 <= d < 1.0
        assert (d * 2**53).is_integer()
        total += d
    assert abs(total / 100_000 - 0.5) <= 0.01
    probe = Pcg32(core.state, ready=True)
    a, b = probe.next32(), probe.next32()
    assert dice.decimal() == ((a >> 5) * 2**26 + (b >> 6)) / 2**53


def test_shuffle_ac_39():
    _, dice = seeded()
    items = [1, 2, 3]
    counts: dict[tuple, int] = {}
    for _ in range(60_000):
        out = dice.shuffle(items)
        assert out is not items and sorted(out) == [1, 2, 3]
        counts[tuple(out)] = counts.get(tuple(out), 0) + 1
    assert items == [1, 2, 3]
    assert len(counts) == 6
    assert chi_square(counts.values(), 10_000) <= CHI_DF5
    assert dice.shuffle([]) == []


def test_below_is_in_range_for_any_n():
    core, _ = seeded()
    for n in (1, 2, 3, 2**32 - 1, 2**32, 2**32 + 1, 2**64, 10**30):
        for _ in range(50):
            assert 0 <= core.below(n) < n


def test_state_replays():
    core, dice = seeded(7)
    saved = core.state
    first = [dice.roll(1, 100) for _ in range(20)]
    core.state = saved
    assert [dice.roll(1, 100) for _ in range(20)] == first


# --- TR-F03-13 and the E85c / E85j / E85k data --------------------------------------------

def test_only_four_calls_tr_13():
    _, dice = seeded()
    assert [a for a in dir(dice) if not a.startswith("__")] == ["decimal", "pick", "roll",
                                                                 "shuffle"]
    assert list(DICE_CALLS) == ["decimal", "pick", "roll", "shuffle"]
    assert not hasattr(dice, "__dict__")
    assert isinstance(dice, DiceFacade)


@pytest.mark.parametrize("name", ["seed", "state", "_below", "rol", "core", "extra"])
def test_unknown_attribute_read_e85c(name):
    _, dice = seeded()
    with pytest.raises(AttributeError) as caught:
        getattr(dice, name)
    assert caught.value.name == name and caught.value.obj is dice


@pytest.mark.parametrize("name", ["state", "extra", "roll", "seed"])
def test_setting_or_deleting_any_attribute_e85c(name):
    core, dice = seeded()
    state = core.state
    with pytest.raises(AttributeError) as caught:
        setattr(dice, name, 0)
    assert caught.value.name == name and caught.value.obj is dice
    with pytest.raises(AttributeError) as caught:
        delattr(dice, name)
    assert caught.value.name == name
    assert core.state == state
    assert dice.roll(1, 6) in range(1, 7)


@pytest.mark.parametrize("call, args, form, value, got", [
    ("roll", (6, 1), "order", (6, 1), 0),
    ("roll", (1.5, 6), "whole", 1.5, 0),
    ("roll", (True, 6), "whole", True, 0),
    ("roll", (1, "6"), "whole", "6", 0),
    ("roll", (1,), "count", None, 1),
    ("roll", (), "count", None, 0),
    ("pick", ([],), "empty", [], 0),
    ("pick", ("abc",), "list", "abc", 0),
    ("pick", ((1, 2),), "list", (1, 2), 0),
    ("pick", (), "count", None, 0),
    ("shuffle", ("abc",), "list", "abc", 0),
    ("shuffle", ([1], [2]), "count", None, 2),
    ("decimal", (1,), "count", None, 1),
])
def test_wrong_values_e85j(call, args, form, value, got):
    core, dice = seeded()
    state = core.state
    with pytest.raises(DiceArgumentError) as caught:
        getattr(dice, call)(*args)
    error = caught.value
    assert (error.call, error.form, error.got) == (call, form, got)
    assert error.value == value
    assert core.state == state


def test_kind_words_on_argument_errors():
    _, dice = seeded()
    with pytest.raises(DiceArgumentError) as caught:
        dice.shuffle("abc")
    assert caught.value.kind == "text"
    with pytest.raises(DiceArgumentError) as caught:
        dice.roll(1.5, 6)
    assert caught.value.kind == "a decimal number"


@pytest.mark.parametrize("call, args", [("roll", (1, 6)), ("pick", ([1],)), ("decimal", ()),
                                        ("shuffle", ([1],)), ("roll", (6, 1))])
def test_not_ready_e85k(call, args):
    core = Pcg32()
    dice = make_dice(core)
    with pytest.raises(DiceNotReady) as caught:
        getattr(dice, call)(*args)
    assert caught.value.call == call
    assert core.state == 0
