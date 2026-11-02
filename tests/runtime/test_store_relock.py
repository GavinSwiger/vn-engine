"""F19 revocable unlock kinds in the store (F19 ``06-acceptance.md`` AC-F19-26; checklist
step 2; ``04`` §5, §7.5; TR-F19-02, 03)."""

import random

import pytest

from engine.persist.fileformat import PieceEncoder
from engine.runtime.persistent import PersistentStore


def store_with_kinds() -> PersistentStore:
    store = PersistentStore(identity_scheme=1)
    store.register_kind("ending", revocable=True)
    store.register_kind("cg")
    return store


def _random_ops(seed: int, ops: int) -> None:
    """TR-F19-02: unlock, relock, merge_kind, and writes in random order; after each write
    the kept encoder's output equals a fresh encoder's."""
    rng = random.Random(f"tr-f19-02:{seed}")
    store = store_with_kinds()
    store.register_kind("route", revocable=True)
    encoder = PieceEncoder()
    names = [f"n{i}" for i in range(12)]
    for _ in range(ops):
        roll = rng.random()
        kind = rng.choice(("ending", "route"))
        if roll < 0.35:
            store.unlock(rng.choice((kind, "cg")), rng.choice(names),
                         quiet=rng.random() < 0.2)
        elif roll < 0.6:
            store.relock(kind, rng.choice(names))
        elif roll < 0.75:
            disk = rng.sample(names, rng.randrange(len(names)))
            store.merge_kind(kind, disk)
        else:
            assert encoder.encode(store) == PieceEncoder().encode(store), seed
            store.mark_synced(store.version)


@pytest.mark.parametrize("seeds, ops", [
    (5, 200), pytest.param(50, 10_000, marks=pytest.mark.slow)], ids=["default", "slow"])
def test_ac26_relock_and_revocable_kinds(seeds, ops):
    store = store_with_kinds()
    assert store.unlock("ending", "a") is True
    assert store._unlock_changed[("ending", "a")] == store.version
    assert store.relock("ending", "a") is True
    assert store._unlock_changed[("ending", "a")] == store.version
    assert store.relock("ending", "a") is False
    store.unlock("ending", "b")
    store.unlock("ending", "a")                               # re-unlocked: last
    assert store.unlocked("ending") == ("b", "a")

    version = store.version                                   # TR-F19-03
    for kind in ("cg", "nope"):
        with pytest.raises(ValueError):
            store.relock(kind, "x")
    assert store.version == version

    store.take_new_unlocks()
    assert store.unlock("ending", "q", quiet=True) is True
    assert store.is_unlocked("ending", "q") and store.take_new_unlocks() == ()
    assert store._unlock_changed[("ending", "q")] == store.version
    store.unlock("cg", "x")
    assert ("cg", "x") not in store._unlock_changed

    synced = store._unlock_changed[("ending", "b")]           # mark_synced keeps later ones
    store.mark_synced(synced)
    assert all(v > synced for v in store._unlock_changed.values())
    assert set(store._unlock_changed) == {("ending", "a"), ("ending", "q")}
    store.reset()
    assert store._unlock_changed == {}

    for seed in range(seeds):
        _random_ops(seed, ops)
