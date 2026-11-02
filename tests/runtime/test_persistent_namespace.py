"""The ``persistent`` facade (F12 ``04-technical.md`` §5.1; AC-F12-10's facade rows, E182's
forms, the define lock behind E185) and the namespace and limits it lives with."""

import pytest

from engine.runtime import limits
from engine.runtime import persistent as persistent_mod
from engine.runtime.namespace import build_namespace, persistent_store
from engine.runtime.persistent import (PersistentEngineName, PersistentInDefine,
                                       PersistentNamespace, PersistentNoValue,
                                       PersistentStore, PersistentTooBig, PersistentUnsaveable,
                                       store_of)
from engine.runtime.values import Unsaveable, freeze, kind_words
from engine.script.messages import format_message, megabytes


def facade(**values) -> tuple[PersistentNamespace, PersistentStore]:
    store = PersistentStore.with_data(values=values)
    return PersistentNamespace(store), store


def test_reads_sets_and_deletes_go_to_the_store():
    p, store = facade(festivals=1)
    assert p.festivals == 1
    p.festivals = 2
    assert store.get("festivals") == 2
    del p.festivals
    assert not hasattr(p, "festivals") and not hasattr(p, "nope")
    with pytest.raises(PersistentNoValue):
        p.nope


def test_engine_names():
    p, store = facade()
    with pytest.raises(PersistentEngineName) as caught:
        p._secret = 1
    assert caught.value.form == "set"
    with pytest.raises(PersistentEngineName) as caught:
        del p._secret
    assert caught.value.form == "set"
    with pytest.raises(PersistentEngineName) as caught:
        p._clera
    assert caught.value.form == "read"
    with pytest.raises(PersistentEngineName) as caught:
        p._clear(progress=1)
    assert (caught.value.form, caught.value.value) == ("progress", 1)
    for call in (lambda: p._clear(True), lambda: p._clear(full=True)):
        with pytest.raises(PersistentEngineName) as caught:
            call()
        assert caught.value.form == "call"
    for name in ("a b", "for", "x" * 256, "ﬁle"):
        with pytest.raises(PersistentEngineName) as caught:
            setattr(p, name, 1)
        assert caught.value.form == "name"
        with pytest.raises(PersistentNoValue):          # reading one is E180 (07 I-4 O1)
            getattr(p, name)
    setattr(p, "x" * 255, 1)                             # 255 characters is a name


def test_dunder_attributes_behave_as_on_any_object():
    p, store = facade()
    assert p.__class__ is PersistentNamespace and isinstance(p, PersistentNamespace)
    assert not isinstance(p, int)                        # isinstance reads __class__
    store.begin_defines()
    try:
        assert p.__class__ is PersistentNamespace        # no E185 for Python's own lookups
    finally:
        store.end_defines()


def test_the_define_lock():
    p, store = facade(festivals=1)
    store.begin_defines()
    try:
        for use in (lambda: p.festivals, lambda: setattr(p, "x", 1),
                    lambda: delattr(p, "festivals"), lambda: hasattr(p, "x"),
                    lambda: dir(p), lambda: p._clear()):
            with pytest.raises(PersistentInDefine):
                use()
    finally:
        store.end_defines()
    assert p.festivals == 1


def test_dir_repr_and_kind_words():
    p, store = facade(note="ZZMARK", b=1)
    assert dir(p) == sorted(store.names()) == ["b", "note"]
    assert repr(p) == "<persistent data>" and "ZZMARK" not in repr(p)
    assert kind_words(p) == "persistent data"
    with pytest.raises(Unsaveable):
        freeze(p)


def test_set_failures_change_nothing():
    p, store = facade(a=1)
    version, before = store.version, store.values_snapshot()
    with pytest.raises(PersistentUnsaveable):
        p.v = {1}
    with pytest.raises(PersistentTooBig) as caught:
        p.big = "x" * limits.PERSIST_MAX_BYTES
    assert caught.value.form == "bytes" and caught.value.limit == limits.PERSIST_MAX_BYTES
    assert (store.version, store.values_snapshot()) == (version, before)


def test_namespace_binds_the_given_store_or_a_fresh_one():
    from tests.runtime.story import load_files
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        program = load_files(Path(tmp), {"main.vns": 'label start:\n    "x"\n'})
    store = PersistentStore(identity_scheme=1)
    G = build_namespace(program, persistent=store)
    assert type(G["persistent"]) is PersistentNamespace and persistent_store(G) is store
    other = build_namespace(program)
    assert persistent_store(other) is not None and persistent_store(other) is not store
    assert store_of(object()) is None and persistent_store({}) is None


def test_limits_live_in_runtime_limits():
    for name in ("PERSIST_MAX_BYTES", "PERSIST_MAX_NAMES", "PERSIST_NAME_MAX_CHARS",
                 "SEEN_MAX", "CHOSEN_MAX", "UNLOCK_KINDS_MAX", "UNLOCK_NAMES_MAX"):
        assert getattr(persistent_mod, name) == getattr(limits, name)


@pytest.mark.parametrize("size, shown", [(1_048_577, "1.1"), (1_363_196, "1.3"),
                                         (1_100_000, "1.1"), (2_097_152, "2.0"),
                                         (1_415_577, "1.3"), (1_415_578, "1.4")])
def test_e183_megabytes(size, shown):
    """07 I-4 O3: MiB, one decimal, half up, never "1.0"."""
    assert megabytes(size) == shown


def test_e182_and_e185_drafted_forms():
    assert format_message("E182", ("read", "_secret")) == (
        'persistent has no "_secret". Names starting with _ belong to the engine, and _clear '
        "is the only one, e.g. persistent._clear().")
    assert format_message("E182", ("call",)) == (
        "persistent._clear takes only progress=True or progress=False, e.g. "
        "persistent._clear(progress=True).")
    assert format_message("E182", ("set", "_")).endswith('Use a name such as "flag".')
    assert format_message("E185", ("names", "", None)) == (
        "it reads persistent, but define values are set once at launch and would miss "
        "changes made during play. Use a lambda, so the value is worked out each time it is "
        "used.")
