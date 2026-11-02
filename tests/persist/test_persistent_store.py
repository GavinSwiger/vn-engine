"""The store's data half (F12 ``04`` §5.1, §7.1–7.3): AC-F12-11 (author-data limits),
AC-F12-14 (unlocks), AC-F12-15 (record limits at run time), plus the value API, records,
``with_data``, and ``mark_synced`` that later steps build on."""

import pytest

from engine.runtime import persistent as P
from engine.runtime.persistent import (Missing, PersistentEngineName, PersistentInDefine,
                                       PersistentNoValue, PersistentStore, PersistentTooBig,
                                       PersistentUnsaveable)
from engine.runtime.values import TOO_DEEP

SEEN_W57 = ("the seen-line record is full ({:,} lines), so the oldest lines from scenes no "
            "longer in the story were dropped.")


def new_store() -> PersistentStore:
    return PersistentStore(identity_scheme=1)


# --- AC-F12-11: author-data limits (real values) ------------------------------------------

def test_ac_f12_11_bytes_cap_exact():
    store = new_store()
    # {"a":"xxx…"} is k + 8 bytes
    store.set("a", "x" * (P.PERSIST_MAX_BYTES - 8))
    assert store.values_bytes == P.PERSIST_MAX_BYTES == 1_048_576
    version, before = store.version, store.values_snapshot()
    with pytest.raises(PersistentTooBig) as caught:
        store.set("a", "x" * (P.PERSIST_MAX_BYTES - 7))
    assert caught.value.form == "bytes" and caught.value.size == P.PERSIST_MAX_BYTES + 1
    assert store.version == version and store.values_snapshot() == before
    assert store.values_bytes == P.PERSIST_MAX_BYTES


def test_ac_f12_11_names_cap_and_reset_existing():
    store = new_store()
    for i in range(P.PERSIST_MAX_NAMES):
        store.set(f"n{i}", i)
    assert len(store.names()) == 10_000
    size, version = store.values_bytes, store.version
    with pytest.raises(PersistentTooBig) as caught:
        store.set("n10000", 1)
    assert caught.value.form == "names" and caught.value.size == 10_001
    assert store.values_bytes == size and store.version == version
    assert "n10000" not in store.names()
    store.set("n5", "again")                     # re-setting an existing name at the cap
    assert store.get("n5") == "again"


def test_ac_f12_11_name_length_and_delete_makes_room():
    store = new_store()
    store.set("a" * 255, 1)
    with pytest.raises(PersistentEngineName) as caught:
        store.set("a" * 256, 1)
    assert caught.value.form == "name"
    store.set("big", "x" * (P.PERSIST_MAX_BYTES - 300))
    with pytest.raises(PersistentTooBig):
        store.set("more", "y" * 400)
    before = store.values_bytes
    store.delete("big")
    assert store.values_bytes < before
    store.set("more", "y" * 400)


def test_too_big_size_is_the_written_object():
    """AC-F12-05's E183 row: the values object would be 1,363,196 bytes."""
    store = PersistentStore.with_data(values={"festivals": 0, "hana_remembers": False})
    assert store.values_bytes == len(b'{"festivals":0,"hana_remembers":false}')
    with pytest.raises(PersistentTooBig) as caught:
        store.set("log", "x" * 1_363_149)
    assert (caught.value.form, caught.value.size) == ("bytes", 1_363_196)


# --- Values API -------------------------------------------------------------------------------

def test_set_get_copy_and_errors():
    store = new_store()
    bag = [1, {"k": "v"}]
    store.set("bag", bag)
    bag.append(2)
    assert store.get("bag") == [1, {"k": "v"}]
    with pytest.raises(PersistentNoValue) as caught:
        store.get("nope")
    assert isinstance(caught.value, AttributeError) and caught.value.name == "nope"
    with pytest.raises(PersistentUnsaveable) as caught:
        store.set("visited", {1, 2})
    assert caught.value.error.reason == "kind"
    with pytest.raises(PersistentEngineName) as caught:
        store.set("_secret", 1)
    assert caught.value.form == "set"
    for bad in ("a b", "for", "\ufb01le", ""):
        with pytest.raises(PersistentEngineName):
            store.set(bad, 1)
    nested: list = []
    for _ in range(100):
        nested = [nested]
    with pytest.raises(PersistentUnsaveable) as caught:
        store.set("deep", nested)
    assert caught.value.error.reason == TOO_DEEP


def test_launch_values_delete_and_clear():
    store = new_store()
    store.set_known({"festivals", "endings"})
    store.set_default("festivals", 0)
    store.set_default("endings", [])
    store.set("festivals", 3)
    store.set("old_flag", 1)
    store.get("endings").append("sad")
    store.check_in_place()
    store.mark_seen("start/77aa01c2b3d4")
    store.register_kind("cg")
    store.unlock("cg", "river_night")
    store.delete("festivals")
    assert store.get("festivals") == 0
    with pytest.raises(PersistentNoValue):
        store.delete("never")
    store.clear()
    assert store.get("endings") == [] and store.get("festivals") == 0
    with pytest.raises(PersistentNoValue):
        store.get("old_flag")
    assert store.is_seen("start/77aa01c2b3d4") and store.unlocked("cg") == ("river_night",)
    store.clear(progress=True)
    assert not store.is_seen("start/77aa01c2b3d4") and store.is_unlocked("cg", "river_night")
    with pytest.raises(PersistentEngineName) as caught:
        store.clear(progress=1)
    assert caught.value.form == "progress" and caught.value.value == 1
    store.reset()
    assert store.unlocked("cg") == () and store.names() == {"festivals", "endings"}


def test_check_in_place_notices_append_alias_and_nested():
    store = new_store()
    store.set("bag", {"items": []})
    version = store.version
    store.check_in_place()                       # nothing read yet: nothing to check
    assert store.version == version
    alias = store.get("bag")["items"]
    alias.append("key")
    store.check_in_place()
    assert store.version == version + 1 and store.changed["bag"] == store.version
    assert store.peek("bag") == {"items": ["key"]}
    store.check_in_place()
    assert store.version == version + 1
    alias.append({1})
    with pytest.raises(PersistentUnsaveable):
        store.check_in_place()
    assert store.values_snapshot()["bag"] == {"items": ["key"]}   # last good fragment


def test_peek_is_a_copy_and_never_raises():
    store = PersistentStore.with_data(values={"festivals": [1]})
    copy = store.peek("festivals")
    copy.append(2)
    version = store.version
    assert store.peek("festivals") == [1] and store.version == version
    assert store.peek("nope") is Missing and not Missing and repr(Missing) == "Missing"


def test_defines_lock():
    store = new_store()
    store.begin_defines()
    for call in (lambda: store.get("x"), lambda: store.set("x", 1), lambda: store.clear()):
        with pytest.raises(PersistentInDefine):
            call()
    store.end_defines()
    store.set("x", 1)


def test_give_way_for_known_names(warnings):
    """SEC-F12-04c: a name the program mentions pushes out names it doesn't (W54)."""
    store = new_store()
    for i in range(P.PERSIST_MAX_NAMES):
        store.load_value(f"j{i}", i, str(i).encode())
    store.set_known({"flag", "score"})
    store.set("flag", True)
    assert store.get("flag") is True and "j0" not in store.names()
    assert warnings.of("W54") == ["persistent data in persistent.json had 1 entry that "
                                  "couldn't be used (a bad name or value). It was dropped and "
                                  "the rest was kept."]
    with pytest.raises(PersistentTooBig):
        store.set("unmentioned", 1)
    store.set_default("score", 0)
    assert store.get("score") == 0


def test_mark_synced_forgets_changes_up_to_version():
    store = new_store()
    store.set("a", 1)
    v1 = store.version
    store.set("b", 2)
    store.clear()
    assert store.cleared == P.VALUES
    store.mark_synced(v1)
    assert set(store.changed) == {"b"} and store.cleared == P.VALUES
    store.mark_synced(store.version)
    assert store.changed == {} and store.cleared == 0


# --- Records ----------------------------------------------------------------------------------

def test_seen_and_chosen_records():
    store = PersistentStore.with_data(seen=["start/77aa01c2b3d4"])
    assert store.is_seen("start/77aa01c2b3d4") and not store.is_seen("start/000000000000")
    assert not store.is_seen(None)
    version = store.version
    store.mark_seen("start/77aa01c2b3d4")
    assert store.version == version
    store.mark_chosen("bridge/5e0c11aa9b02", "a1b2c3d4e5f6")
    assert store.was_chosen("bridge/5e0c11aa9b02", "a1b2c3d4e5f6")
    assert not store.was_chosen("bridge/5e0c11aa9b02", "0f9e8d7c6b5a")
    with pytest.raises(ValueError):
        store.mark_seen("define:x")


# --- AC-F12-15: record limits at run time (patched caps) -----------------------------------

@pytest.mark.parametrize("form", ["seen", "chosen"])
def test_ac_f12_15_record_cap_drops_oldest_run(monkeypatch, warnings, form):
    cap = 1_000 if form == "seen" else 100
    monkeypatch.setattr(P, "SEEN_MAX" if form == "seen" else "CHOSEN_MAX", cap)
    store = new_store()

    def mark(group: str, i: int) -> None:
        key = f"{i:012x}"
        if form == "seen":
            store.mark_seen(f"{group}/{key}")
        else:
            store.mark_chosen(group, key)

    def has(group: str, i: int) -> bool:
        key = f"{i:012x}"
        return store.is_seen(f"{group}/{key}") if form == "seen" else store.was_chosen(group, key)

    groups = [f"l{g}/aaaaaaaaaaaa" if form == "chosen" else f"l{g}" for g in range(10)]
    per = cap // 10
    for group in groups:
        for i in range(per):
            mark(group, i)
    assert store.record_total(form) == cap and warnings.of("W57") == []
    mark("new" if form == "seen" else "new/aaaaaaaaaaaa", 0)
    assert not any(has(groups[0], i) for i in range(per))
    assert all(has(g, i) for g in groups[1:] for i in range(per))
    assert has("new" if form == "seen" else "new/aaaaaaaaaaaa", 0)
    expected = (SEEN_W57.format(cap) if form == "seen" else
                f"the choice record is full ({cap:,} choices), so the oldest choices from menus "
                "no longer in the story were dropped.")
    assert warnings.of("W57") == [expected]
    for i in range(per):                          # a second overflow: nothing more logged
        mark("newer" if form == "seen" else "newer/aaaaaaaaaaaa", i)
    assert not has(groups[1], 0)
    assert len(warnings.of("W57")) == 1


@pytest.mark.slow
def test_ac_f12_15_real_seen_cap(warnings):
    store = new_store()
    for g in range(10):
        for i in range(P.SEEN_MAX // 10):
            store.mark_seen(f"l{g}/{i:012x}")
    store.mark_seen("new/000000000000")
    assert not store.is_seen("l0/000000000000") and store.is_seen("l1/000000000000")
    assert warnings.of("W57") == [SEEN_W57.format(1_000_000)]


@pytest.mark.slow
def test_ac_f12_15_real_chosen_cap(warnings):
    store = new_store()
    for g in range(10):
        for i in range(P.CHOSEN_MAX // 10):
            store.mark_chosen(f"l{g}/aaaaaaaaaaaa", f"{i:012x}")
    store.mark_chosen("new/aaaaaaaaaaaa", "000000000000")
    assert not store.was_chosen("l0/aaaaaaaaaaaa", "000000000000")
    assert len(warnings.of("W57")) == 1


# --- AC-F12-14: unlocks -------------------------------------------------------------------------

def test_ac_f12_14_unlocks():
    store = new_store()
    store.register_kind("cg")
    assert store.unlock("cg", "river_night") is True
    assert store.unlock("cg", "river_night") is False
    assert store.unlock("cg", "bridge") is True
    assert store.unlocked("cg") == ("river_night", "bridge")
    assert store.is_unlocked("cg", "bridge") and not store.is_unlocked("cg", "x")
    assert store.take_new_unlocks() == (("cg", "river_night"), ("cg", "bridge"))
    assert store.take_new_unlocks() == ()
    with pytest.raises(ValueError):
        store.unlock("ending", "x")
    for bad in ("", "k" * 65, None):
        with pytest.raises(ValueError):
            store.register_kind(bad)
    store.register_kind("k" * 64)
    for i in range(30):
        store.register_kind(f"kind{i}")
    with pytest.raises(ValueError):
        store.register_kind("one_too_many")      # the 33rd registered kind
    store.clear()
    store.clear(progress=True)
    assert store.unlocked("cg") == ("river_night", "bridge")
    store.reset()
    assert store.unlocked("cg") == () and not store.is_unlocked("cg", "bridge")
    assert store.unlock("cg", "again") is True   # still registered after reset


def test_ac_f12_14_full_kind_real_cap(warnings):
    store = new_store()
    store.register_kind("cg")
    for i in range(P.UNLOCK_NAMES_MAX):
        store.unlock("cg", f"n{i}")
    assert store.unlock("cg", "river_night") is False
    assert not store.is_unlocked("cg", "river_night")
    assert store.unlock("cg", "other") is False
    assert warnings.of("W57") == ['unlock record "cg" is full (10,000), so new unlocks of this '
                                  "kind aren't recorded."]


def test_full_kind_recognized_name_pushes_out_junk(warnings):
    """SEC-F12-04d, 07 I-6 AC-F12-30 row 4 (seam shape)."""
    store = new_store()
    store.load_kind("cg", [f"junk{i}" for i in range(P.UNLOCK_NAMES_MAX)])
    store.register_kind("cg", known=lambda n: n == "river_night")
    assert store.unlock("cg", "river_night") is True
    assert "junk0" not in store.unlocked("cg") and len(store.unlocked("cg")) == 10_000
    assert warnings.codes() == ["W54"]
    assert store.unlock("cg", "junk_new") is False
    assert warnings.codes() == ["W54", "W57"]


def test_unregistered_kinds_give_way(warnings):
    """SEC-F12-04b: 32 kinds from a file never stop a feature's registration."""
    store = new_store()
    for i in range(P.UNLOCK_KINDS_MAX):
        assert store.load_kind(f"junk{i}", ["a"]) == 0
    assert store.load_kind("one_more", ["a"]) == -1
    store.register_kind("cg")
    assert store.unlock("cg", "river_night") is True
    assert "junk0" not in dict(store.kind_items()) and warnings.codes() == ["W54"]
    store.register_kind("junk5")                 # adopting a kind from the file
    assert store.unlocked("junk5") == ("a",)


def test_with_data_fills_without_new_unlocks_or_changes():
    store = PersistentStore.with_data(values=[("a", 1)], seen=["l/000000000000"],
                                      chosen=[("m/000000000000", "111111111111")],
                                      unlocks=[("cg", "x"), ("cg", "y")])
    assert store.take_new_unlocks() == () and store.changed == {}
    assert store.unlocked("cg") == ("x", "y") and store.identity_scheme == 1
