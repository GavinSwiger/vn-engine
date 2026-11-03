"""F36 P1: the replay sandbox of F12's store and sync (F36 ``04`` §7.1, §7.2): AC-F36-21 on
the store and the sync (Harness Y, a real folder, a synchronous writer, a fake clock).

Each row of the table is what a replay's script line does to the store (``persistent.x =``,
``unlock tip``, a gallery picture shown, ``lock ending``, ``ending``, a chapter, choices,
seen lines, a ``ui`` look, ``_clear``, Delete progress, a kept track or achievement); each
row runs with each way out of a replay: its end (``end_sandbox``), a quit (``close``), and
a crash (F30's ``flush_now``, then nothing)."""

import pytest

from engine.persist.fileformat import decode, encode_bytes, parse
from engine.runtime.persistent import CHOSEN, SEEN
from tests.persist.sync_support import Harness, records, sid
from tests.persist.writer_support import base, game  # noqa: F401

MENU = "a/" + "c" * 12


def _seed(store) -> None:
    store.register_kind("tip")
    store.register_kind("gallery")
    store.register_kind("chapter")
    store.register_kind("ending", revocable=True)
    store.register_kind("track", replay_keeps=True)          # F35
    store.register_kind("achievement", replay_keeps=True)    # F37
    store.set("x", 1)
    store.set("v", [1, 2])
    store.set("playthrough", 0)
    for n in range(12):                                       # past SMALL_RUN: a set
        store.mark_seen(sid("a", n))
    store.mark_seen(sid("b", 1))
    store.mark_chosen(MENU, "d" * 12)
    for kind, name in (("tip", "t"), ("gallery", "g1"), ("chapter", "c1"),
                       ("ending", "good"), ("track", "t1"), ("achievement", "a1")):
        store.unlock(kind, name)


def _all(s) -> None:
    for row in ROWS.values():
        if row[0] is not _all:
            row[0](s)


# id: (what the replay does, the names kept afterwards)
ROWS = {
    "persistent.x =": (lambda s: (s.set("x", 2), s.set("new", 5)), []),
    "in place": (lambda s: (s.get("v").append(3), s.check_in_place()), []),
    "delete": (lambda s: s.delete("x"), []),
    "unlock tip": (lambda s: s.unlock("tip", "t2"), []),
    "gallery shown": (lambda s: s.unlock("gallery", "g2"), []),
    "lock ending": (lambda s: s.relock("ending", "good"), []),
    "ending": (lambda s: s.unlock("ending", "sad"), []),
    "chapter": (lambda s: s.unlock("chapter", "c2"), []),
    "choices": (lambda s: s.mark_chosen(MENU, "e" * 12), []),
    "seen lines": (lambda s: [s.mark_seen(sid(g, n)) for g in "ac" for n in range(20, 30)], []),
    "ui look": (lambda s: s.set("playthrough", 3), []),
    "clear progress": (lambda s: s.clear(progress=True), []),
    "delete progress": (lambda s: s.reset(), []),
    "kept track": (lambda s: (s.unlock("track", "t2"), s.unlock("track", "t1")),
                   [("track", "t2")]),
    "kept achievement": (lambda s: (s.unlock("achievement", "a2"),
                                    s.unlock("achievement", "a3")),
                         [("achievement", "a2"), ("achievement", "a3")]),
    "re-registered (F39)": (lambda s: (s.register_kind("tip", replay_keeps=True),
                                       s.unlock("tip", "t3")), [("tip", "t3")]),
    "everything": (_all, [("track", "t2"), ("achievement", "a2"), ("achievement", "a3"),
                          ("tip", "t3")]),
}


@pytest.mark.parametrize("way", ["end", "quit", "crash"])
@pytest.mark.parametrize("row", list(ROWS))
def test_ac_f36_21_a_replay_changes_no_progress(row, way, game):
    act, kept = ROWS[row]
    h = Harness(game / "persistent", game=game)
    _seed(h.store)
    notices = []
    h.sync.add_unlock_listener(lambda kind, name: notices.append((kind, name)))
    h.ticks(2.0)                                     # written; the encoder follows the store
    assert h.path.read_bytes() == h.encoded()
    h.store.set("y", 7)                              # a change not yet written at the start
    s = h.store
    file_before = h.path.read_bytes()
    expected = parse(decode(encode_bytes(s)))        # the store as the replay starts
    for kind, name in kept:
        expected["unlocks"][kind].append(name)
    changed, resets, requests = dict(s.changed), s.reset_count, h.sync.requests
    notices.clear()

    s.begin_sandbox()
    with pytest.raises(RuntimeError):
        s.begin_sandbox()
    act(s)
    h.sync.encoder.warm(s)                           # worst case: its caches saw the replay
    h.ticks(3.0)
    assert h.sync.flush_now() is False               # F30's fake crash: nothing written
    assert s.in_sandbox
    assert h.path.read_bytes() == file_before and h.sync.requests == requests
    assert ("track", "t2") not in kept or notices.count(("track", "t2")) == 1
    during = s.version
    notices.clear()

    if way == "crash":                               # the process dies here
        assert h.path.read_bytes() == file_before
        return
    if way == "quit":
        h.sync.close()
        assert not s.in_sandbox
    else:
        s.end_sandbox()
        s.end_sandbox()                              # closed: a no-op
        assert not s.in_sandbox and s.version > during
        assert dict(s.changed) == changed and s.reset_count == resets
        h.ticks(3.0)
        assert h.sync.requests == requests + 1       # one write afterwards
    assert h.disk() == expected                      # old content plus the kept names
    assert h.path.read_bytes() == h.encoded()        # the encoder's caches started over
    assert s.values_snapshot() == expected["values"]
    assert {r for r in records(s, SEEN)} == {f"{g}/{k}" for g, t in expected["seen"].items()
                                              for k in t.split(" ")}
    assert len(records(s, CHOSEN)) == sum(len(t.split(" ")) for t in expected["chosen"].values())
    assert {k: list(s.unlocked(k)) for k in expected["unlocks"]} == expected["unlocks"]
    assert s.is_seen(sid("a", 11)) and not s.is_seen(sid("a", 25))
    h.ticks(1.0)
    assert notices == []                             # kept names are unlocked again quietly
