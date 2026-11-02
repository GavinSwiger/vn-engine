"""F19 step 3 — the ending and route indexes (``runtime/endings.py``): AC-F19-13 (when a route
is open) and AC-F19-25 (the seams for F20 and F36, F39's second ``register``)."""

from engine.runtime import endings
from engine.runtime.endings import EndingIndex, RouteIndex
from engine.runtime.persistent import PersistentStore
from tests.runtime.endings_story import F19, launched, load_e, store_with
from tests.runtime.story import load_files

INCLUDES = F19 / "includes" / "script"


def test_ac13_when_a_route_is_open(tmp_path):
    program = load_e(tmp_path / "r")
    rows = [  # (e, r, then relock good, promise open, festival_night open, routes view)
        ((), (), False, False, False, []),
        (("sad",), (), False, False, False, []),
        (("good", "sad"), (), False, True, False, ["promise"]),
        (("sad", "good"), ("festival_night",), False, True, True, ["promise", "festival_night"]),
        (("sad", "good"), (), True, False, False, []),
        (("sad",), ("promise",), False, True, False, ["promise"]),
        (("old",), ("gone",), False, False, False, []),
    ]
    for e, r, relock, promise, festival, view in rows:
        store = store_with(e, r)
        interp = launched(program, store)
        if relock:
            assert store.relock("ending", "good")
        index = interp.routes
        row = (e, r, relock)
        assert index.is_open("promise") is promise, row
        assert index.is_open("festival_night") is festival, row
        assert store.get("routes") == view, row
        assert not index.is_open("gone") and not index.is_open("nope") and not index.is_open(3)

    # A patch adds ``until good`` to line 3: the route opens at once, nothing is written.
    patched = load_e(tmp_path / "p",
                     replace={3: 'lock route festival_night "Festival Night" until good'})
    store = store_with(("good",))
    version = store.version
    assert RouteIndex.build(patched, store).is_open("festival_night")
    assert store.version == version


def test_ac25_seams_for_f20_and_f36(tmp_path):
    files = {p.name: p.read_text(encoding="utf-8") for p in INCLUDES.iterdir()}
    program = load_files(tmp_path / "inc", files)
    store = PersistentStore.with_data(unlocks={"ending": ["b1", "zz", "a1"]})
    interp = launched(program, store)

    index = interp.endings
    rows = [(i.name, i.heading, i.title, i.label) for i in index]
    assert rows == [("a1", None, "A One", "a_path"), ("a2", "A Heading", "A Two", "a_menu"),
                    ("b1", None, "B One", "b_path"), ("b2", None, "B Two", "b_menu")]
    by_name = {s.name: s for s in program.endings}
    assert [i.sid for i in index] == [by_name[i.name].sid for i in index]
    assert all(i.sid for i in index)
    assert len(index) == 4 and all(index.has(i.name) and index.get(i.name) == i for i in index)
    assert not index.has("zz") and index.get("zz") is None and not index.has(None)
    assert [i.name for i in index.reached(store)] == ["b1", "a1"]

    assert [(r.name, r.sid, r.label, r.until, r.title) for r in interp.routes] == [
        ("b_path", "route:b_path", "b_path", ("a1", "a2"), "The B Path"),
        ("a_path", "route:a_path", "a_path", (), "The A Path")]
    assert len(interp.routes) == 2 and interp.routes.has("a_path")
    assert not interp.routes.has("start")

    for kind, recognizer in (("ending", index.has), ("route", interp.routes.has)):
        assert store.is_revocable(kind)
        entry = dict(store.kind_items())[kind]
        assert entry.known.__self__ is recognizer.__self__        # the index's ``has``

    # F39: ``register`` again with a program that drops an ending; no ValueError.
    store.unlock("ending", "a2")
    assert store.get("endings") == ["b1", "a1", "a2"]
    files["a.vns"] = files["a.vns"].replace('ending a2 "A Heading" "A Two"', '"No end."')
    files["main.vns"] = files["main.vns"].replace("until a1, a2", "until a1")
    interp.program = load_files(tmp_path / "f39", files)
    endings.register(interp)
    assert not interp.endings.has("a2") and store.get("endings") == ["b1", "a1"]
    assert isinstance(interp.endings, EndingIndex)
