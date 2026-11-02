"""Helpers for the runtime tests (F03).

Phase 1 builds states by hand. ``state_b_json`` mirrors 06-acceptance §0.5's state B (the
``End.`` checkpoint of run R, seed 42); phase 2 replaces it with the real checkpoint of R.
"""

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from engine.runtime.dice import Pcg32
from engine.runtime.state import GameState

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F03"

SID_LINE_9 = "start/3fa9c2d81b07"
CALL_SID = "start/9c1d04e2aa31"


def seed_state(seed: int) -> int:
    core = Pcg32()
    core.seed(seed)
    return core.state


def make_state(variables=None, *, position=SID_LINE_9, at=("start", (2,)), call_stack=(),
               dice=None, identity_scheme=1) -> GameState:
    """A hand-built state, as take_checkpoint would build it."""
    return GameState(position=position, position_at=at, call_stack=tuple(call_stack),
                     variables=MappingProxyType(dict(variables or {})),
                     dice=seed_state(42) if dice is None else dice,
                     identity_scheme=identity_scheme)


def state_b_json() -> dict:
    """A fresh copy of state B's JSON object."""
    return make_state({"trust": 0, "hana_name": "???"}).to_json()


def round_trip(state: GameState) -> GameState:
    return GameState.from_json(json.loads(json.dumps(state.to_json(), ensure_ascii=True)))


@pytest.fixture
def state_b() -> dict:
    return state_b_json()


# --- The corpus (06 §0.5), built once per session -----------------------------------------------

@pytest.fixture(scope="session")
def small_parts(tmp_path_factory) -> dict:
    """The corpus's ``flow/``, ``vars/``, and ``lanterns/`` parts as loaded programs: the
    default tier's slice. With the example game they use every statement kind the realistic
    part does (test-review-F03.md), so the whole-corpus runs are ``slow``."""
    from tests.runtime import corpus
    root = tmp_path_factory.mktemp("corpus-small")
    return {name: corpus.load_part(folder)
            for name, folder in corpus.make_corpus(root, realistic=False).items()}


@pytest.fixture(scope="session")
def small_played(small_parts) -> dict:
    """``corpus.play(program, 1)`` of each small part (read-only: tests must not post to
    its interpreter)."""
    from tests.runtime import corpus
    return {name: corpus.play(program, 1) for name, program in small_parts.items()}


@pytest.fixture(scope="session")
def realistic_part(tmp_path_factory):
    """F02's realistic corpus (50,000 words, seed 1, ``--defaults``) as a loaded program;
    only ``slow`` tests use it."""
    from tests.runtime import corpus
    root = tmp_path_factory.mktemp("corpus-realistic")
    return corpus.load_part(corpus.make_corpus(root)["realistic"])
