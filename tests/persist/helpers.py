"""Shared helpers for the F12 persist tests: a fake ``Program``, store snapshots, random
stores within the caps (TR-F12-01), and a one-call read. Stdlib only."""

import random

from engine.persist.fileformat import ReadJob, ReadOutcome, valid_label
from engine.runtime.persistent import (CHOSEN, SEEN, PersistentStore, valid_name)
from engine.runtime.values import same_value


class FakeProgram:
    """``get(sid)`` and ``label(name)`` as F02's ``Program`` answers them, for a fixed set of
    sids. Labels default to the sids' labels."""

    def __init__(self, sids=(), labels=None, persistent=()):
        self.sids = set(sids)
        self.labels = (set(labels) if labels is not None
                       else {s.rpartition("/")[0] for s in self.sids})
        self.persistent_default_names = frozenset(persistent)
        self.lookups = 0

    def get(self, sid):
        self.lookups += 1
        return sid if sid in self.sids else None

    def label(self, name):
        return name if name in self.labels else None


def snapshot(store: PersistentStore):
    """Values (frozen copies), records, and unlocks, in order."""
    return (store.values_snapshot(),
            {form: [(g, list(r.order)) for g, r in store.records(form).items()]
             for form in (SEEN, CHOSEN)},
            [(k, list(e.names)) for k, e in store.kind_items()])


def same_store(a: PersistentStore, b: PersistentStore) -> bool:
    va, ra, ua = snapshot(a)
    vb, rb, ub = snapshot(b)
    return (va.keys() == vb.keys() and all(same_value(va[k], vb[k]) for k in va)
            and ra == rb and ua == ub)


def read(data: bytes, program=None, *, scheme: int = 1) -> tuple[ReadOutcome, PersistentStore,
                                                                  ReadJob]:
    store = PersistentStore(identity_scheme=scheme)
    job = ReadJob(data, store, program)
    return job.run(), store, job


# --- Random stores (AC-F12-21) ----------------------------------------------------------------

STRING_PARTS = ['"', "\\", "\u2028", "\u00e9", "\u82b1", "\ud800", "\udfff", "\U0001f600", "{", "[", ",", ":",
                "a", " ", "\x00", "/", "~", "\n", "Z"]
NAME_START = ["a", "b", "\u00e9", "\u82b1", "x_", "\u03a9", "z"]
NAME_MORE = ["a", "1", "_", "\u00e9", "\u82b1", "\u00df", "9", "q"]


def random_text(rng: random.Random, low: int = 0, high: int = 8) -> str:
    """Never a lone high surrogate right before a lone low one: JSON reads ``\\ud800\\udfff``
    as one astral character, so that pair can't round-trip through any JSON file."""
    text = "".join(rng.choice(STRING_PARTS) for _ in range(rng.randint(low, high)))
    return text.replace("\ud800\udfff", "\ud800a\udfff")


def random_name(rng: random.Random) -> str:
    while True:
        name = rng.choice(NAME_START) + "".join(rng.choice(NAME_MORE)
                                                for _ in range(rng.randint(0, 6)))
        if valid_name(name):
            return name


def random_label(rng: random.Random) -> str:
    while True:
        label = random_name(rng)
        if valid_label(label):
            return label


def random_key(rng: random.Random) -> str:
    key = "".join(rng.choice("0123456789abcdef") for _ in range(12))
    return key if rng.random() < 0.8 else f"{key}~{rng.randint(2, 9_999_999)}"


def random_value(rng: random.Random, depth: int = 0):
    roll = rng.random()
    if depth < 3 and roll < 0.15:
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    if depth < 3 and roll < 0.3:
        return {random_text(rng): random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))}
    return rng.choice([None, True, False, 0, -1, 2**62, -(2**70), 10**200, 0.5, -0.0, 1e308,
                       5e-324, random_text(rng), random_text(rng, 1, 20)])


def random_store(rng: random.Random) -> PersistentStore:
    store = PersistentStore(identity_scheme=1)
    for _ in range(rng.randint(0, 12)):
        store.set(random_name(rng), random_value(rng))
    for _ in range(rng.randint(0, 6)):
        label = random_label(rng)
        for _ in range(rng.randint(1, 40)):
            store.mark_seen(f"{label}/{random_key(rng)}")
    for _ in range(rng.randint(0, 4)):
        menu = f"{random_label(rng)}/{random_key(rng)}"
        for _ in range(rng.randint(1, 3)):
            store.mark_chosen(menu, random_key(rng))
    for _ in range(rng.randint(0, 4)):
        kind = random_text(rng, 1, 10)
        store.register_kind(kind)
        for _ in range(rng.randint(0, 5)):
            store.unlock(kind, random_text(rng, 1, 12))
    store.take_new_unlocks()
    return store
