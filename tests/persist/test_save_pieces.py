"""``iter_pieces`` and the sliced encoder (F11 ``04`` §7.3, §11): AC-F11-03 (pieces equal one
dump; TR-F11-02) and AC-F11-04's encoder half (every step returns at the first clock read
past its deadline; at least two steps for a 2.2 MiB state; the result equals the one-shot
bytes). The App S half of AC-F11-04 (pieces reused across F5 presses, the writer's pending
count, the 5 ms CI guard) comes with ``SaveService`` (step 8)."""

import json
import random

import pytest

from engine.persist import saves
from engine.persist.saves import SaveEncoder, TooLarge, iter_pieces
from tests.persist import save_support as ss
from tests.persist.test_save_format import random_fields, random_state

DUMP = {"ensure_ascii": True, "separators": (",", ":"), "allow_nan": False}


def one_shot(obj) -> bytes:
    return json.dumps(obj, **DUMP).encode()


SHAPES = [
    {}, [], "x", 0, None, 1.5, [[]], {"a": {}}, {"a": [1, [2, [3, [4]]]]},
    {"\ud800": [" ", {"\"": "\\"}]}, [{"k": i, "花": [i] * 3} for i in range(300)],
    {f"v{i}": "x" * (i % 7) for i in range(5_000)}, [0] * 20_000, [[0] * 70] * 300,
    {"big": "y" * 200_000, "after": [1, 2]}, (1, (2, 3)), {"t": (4, [5])},
    {1: 2, "a": 3}, [{"a": 1, None: 2}], {"a": True, "b": False, "c": -0.0},
]


def test_pieces_equal_one_dump():
    for i, obj in enumerate(SHAPES):
        expected = one_shot(obj)
        for depth in range(5):
            assert b"".join(iter_pieces(obj, depth)) == expected, (i, depth)


@pytest.mark.parametrize("bad", [[float("nan")], {"a": [float("inf")]}, [{1, 2}], {"a": object()}])
def test_pieces_raise_what_the_dump_raises(bad):
    with pytest.raises((ValueError, TypeError)) as one:
        one_shot(bad)
    with pytest.raises(type(one.value)):
        b"".join(iter_pieces(bad))


def _encode(encoder: SaveEncoder, deadline_ms: float, clock: ss.FakeClock) -> list[int]:
    """Steps the encoder to the end; returns the clock reads of each step."""
    per_step = []
    while True:
        start = len(clock.reads)
        deadline = clock() + deadline_ms / 1000
        done = encoder.step(deadline, clock)
        reads = clock.reads[start + 1:]
        per_step.append(len(reads))
        if done:
            return per_step
        # AC-F11-04: the step returned at the first clock read past its deadline.
        assert reads and reads[-1] > deadline and all(r <= deadline for r in reads[:-1])


def _check_encoder(seed: int) -> None:
    """AC-F11-03 with Encoder E at each deadline (0, 1, 4 and 1,000 ms)."""
    for deadline_ms in (0, 1, 4, 1_000):
        rng = random.Random(seed)
        state = random_state(rng)
        encoder = SaveEncoder(state, jpeg=None, **random_fields(rng))
        _encode(encoder, deadline_ms, ss.FakeClock())
        result = encoder.result
        assert not isinstance(result, TooLarge), (seed, deadline_ms)
        line3 = b"".join(result[2:])
        expected = one_shot(state.to_json())
        assert line3 == expected + b"\n", (seed, deadline_ms)
        assert encoder.structure == saves.count_structure(line3), (seed, deadline_ms)
        assert b"".join(iter_pieces(state.to_json())) == expected, (seed, deadline_ms)


def test_encoder_result_equals_the_one_shot_bytes():
    for seed in range(50):
        _check_encoder(seed)


@pytest.mark.slow
def test_encoder_result_equals_the_one_shot_bytes_200():
    for seed in range(50, 200):
        _check_encoder(seed)


def _state_mib(mib: float):
    rng = random.Random(7)
    words = ["lantern", "花火", "wind", "\U0001f338", "poem", "\"q\"", "a\\b"]
    picks = [{"q": rng.choice(words) * 3, "a": [rng.randint(0, 9) for _ in range(5)]}
             for _ in range(int(mib * 23_000))]
    return ss.p8_state(picks=picks, names={f"n{i}": rng.choice(words) for i in range(2_000)})


def test_a_2_2_mib_state_is_sliced():
    """AC-F11-04 (encoder): deadline = clock() + 4 ms on a 1 ms clock."""
    state = _state_mib(2.2)
    expected = one_shot(state.to_json())
    assert 2.0 * (1 << 20) < len(expected) < 2.6 * (1 << 20)
    encoder = SaveEncoder(state, **ss.save_fields())
    steps = _encode(encoder, 4, ss.FakeClock())
    assert len(steps) >= 2 and encoder.steps == len(steps)
    assert b"".join(encoder.result[2:]) == expected + b"\n"
    pieces = list(iter_pieces(state.to_json()))
    assert max(len(p) for p in pieces) <= 128 * 1024        # no unit is the whole state


def test_a_finished_encoder_stays_finished():
    encoder = SaveEncoder(ss.p8_state(), **ss.save_fields())
    result = encoder.run()
    assert encoder.step(0.0, ss.FakeClock()) is True and encoder.result is result
