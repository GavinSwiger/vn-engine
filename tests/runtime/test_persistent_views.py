"""F19's engine views on the persistent store (F19 ``06-acceptance.md`` AC-F19-16; checklist
step 2; ``04`` §5 ``register_view``, §7.4; ``07`` I-1, I-4), and with step 3's real getters
(``runtime/endings.py``): AC-F19-08 (the names in suggestions), 17 (hidden names), and 29
(old stored values, W131, TR-F19-08).

AC-F19-16 uses a counting spy: the store caches whatever a getter gives per
``unlocks_gen``, so the real getters make the same passes."""

import logging

import pytest

from engine.persist import fileformat
from engine.persist.location import FILE_NAME
from engine.runtime.commands import StoryEnded, StoryFailed
from engine.runtime.errors import persistent_error
from engine.runtime.launch import run_launch
from engine.runtime.persistent import (PersistentInDefine, PersistentNamespace,
                                       PersistentStore, PersistentViewName)
from engine.script.messages import format_message
from engine.script.routes import PERSISTENT_VIEWS
from tests.persist.sync_support import Harness, plant
from tests.persist.writer_support import base, game  # noqa: F401
from tests.runtime.endings_story import drive, launched, load_e, run_e
from tests.runtime.story import load_files
from tests.script.helpers import template_p


def write(h: Harness) -> None:
    assert h.sync.flush_now(), h.sync.mode


def test_ac16_the_stores_views(tmp_path):
    store = PersistentStore(identity_scheme=1)
    store.register_kind("ending", revocable=True)
    passes = []

    def g() -> list[str]:
        passes.append(1)
        return ["sad"]

    store.register_view("endings", g)
    first = store.get("endings")
    assert first == ["sad"] and store.peek("endings") == ["sad"]
    first.append("x")                                         # a fresh list each read (C1)
    assert store.get("endings") == ["sad"] and type(store.get("endings")) is list

    version = store.version
    with pytest.raises(PersistentViewName) as set_error:
        store.set("endings", [])
    with pytest.raises(PersistentViewName) as delete_error:
        store.delete("endings")
    with pytest.raises(PersistentViewName):
        setattr(PersistentNamespace(store), "endings", [])   # a computed setattr reaches it
    assert (set_error.value.form, delete_error.value.form) == ("set", "delete")
    assert store.version == version
    code, message = persistent_error(set_error.value, None)  # type: ignore[arg-type]
    assert (code, message) == ("E245", format_message("E245", ("change", "endings")))

    assert "endings" in store.names() and "endings" in dir(PersistentNamespace(store))

    with pytest.raises(ValueError):
        store.register_view("_x", g)
    store.register_view("endings", lambda: ["good"])          # again: replaces (07 I-1)
    assert store.get("endings") == ["good"]
    store.register_view("endings", g)

    store.begin_defines()                                     # the access check comes first
    with pytest.raises(PersistentInDefine):
        store.get("endings")
    store.end_defines()

    # CI count (07 I-4): one pass per change to unlock names, none for other changes.
    passes.clear()
    for _ in range(10):
        store.get("endings")
    assert len(passes) == 1
    store.set("flowers", ["rose"])
    store.mark_seen("start/000000000001")
    store.get("endings")
    assert len(passes) == 1
    for change in (lambda: store.unlock("ending", "sad"),
                   lambda: store.relock("ending", "sad")):
        change()
        store.get("endings")
        store.get("endings")
    assert len(passes) == 3

    # A stored value under a view's name goes to migrate and isn't kept (04 §7.4).
    migrated = []
    old = PersistentStore.with_data(values={"endings": ["sad"], "routes": ["r"]})
    old.register_view("endings", g, migrate=migrated.append)
    old.register_view("routes", g)
    assert migrated == [["sad"]] and not old.has_value("endings") and not old.has_value("routes")
    assert old.merge_value("endings", ["good"], b'["good"]') is True
    assert old.load_value("endings", ["true"], b'["true"]') is True
    assert migrated == [["sad"], ["good"], ["true"]] and not old.has_value("endings")

    # W56 leaves the views out: they are registered after the launch (04 §7.4).
    for view in sorted(PERSISTENT_VIEWS):
        program = load_files(tmp_path / view, {"main.vns": template_p(
            S=f"$ z = len(persistent.{view})")})
        launch = run_launch(program, dev=True, persistent=PersistentStore(identity_scheme=1))
        assert [w for w in launch.warnings if w.code == "W56"] == []


# --- Step 3: the real views (AC-F19-08, 17, 29) ------------------------------------------------

def test_ac08_the_engine_names_in_suggestions(tmp_path):
    rows = [("$ x = persistent.ending", "ending", "endings"),
            ('if persistent.routs:⏎[8]"A."', "routs", "routes")]
    for n, (S, name, suggestion) in enumerate(rows):
        program = load_e(tmp_path / str(n), S=S)
        failed = run_e(program)[-1]
        assert type(failed) is StoryFailed
        error = failed.error
        assert (error.code, error.line) == ("E180", 7)
        if name == "ending":
            assert error.message == ('persistent.ending has no value yet. Did you mean '
                                     '"endings"?')
        assert f'"{suggestion}"' in error.message
        launch = run_launch(program, dev=True, persistent=PersistentStore(identity_scheme=1))
        w56 = [w for w in launch.warnings if w.code == "W56"]
        assert [(w.line, w.message) for w in w56] == [
            (7, format_message("W56", (name, suggestion)))]
    program = load_e(tmp_path / "ok", S="$ x = persistent.endings⏎[4]$ y = persistent.routes")
    launch = run_launch(program, dev=True, persistent=PersistentStore(identity_scheme=1))
    assert [w for w in launch.warnings if w.code == "W56"] == []
    assert type(run_e(program)[-1]) is StoryEnded
    interp = launched(program)
    assert {"endings", "routes"} <= set(dir(interp.G["persistent"]))


def test_ac17_undeclared_and_hostile_names_stay_hidden(tmp_path, game, caplog):
    program = load_e(tmp_path / "r")
    folder = game / "persistent"
    folder.mkdir()
    (folder / FILE_NAME).write_bytes(fileformat.encode_bytes(PersistentStore.with_data(
        unlocks={"ending": ["old", "sad", "ZZMARK"], "route": ["gone", "festival_night"]})))
    with caplog.at_level(logging.DEBUG):
        h = Harness(folder, game=game, program=program)
        interp = launched(program, h.store)
        store = h.store
        assert store.get("endings") == ["sad"] and store.get("routes") == ["festival_night"]
        assert [i.name for i in interp.endings.reached(store)] == ["sad"]
        assert not interp.routes.is_open("gone")
        store.set("flowers", ["rose"])
        write(h)
    assert not [r for r in caplog.records
                if any(w in r.getMessage() for w in ("old", "gone", "ZZMARK"))]
    unlocks = h.disk()["unlocks"]
    assert (unlocks["ending"], unlocks["route"]) == (["old", "sad", "ZZMARK"],
                                                     ["gone", "festival_night"])

    # UNLOCK_NAMES_MAX (10,000, real) undeclared names: sad pushes one out; no W57.
    full = PersistentStore.with_data(unlocks={"ending": [f"u{i}" for i in range(10_000)]})
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        interp, commands = drive(program, full)
    assert type(commands[-1]) is StoryEnded and full.is_unlocked("ending", "sad")
    assert len(full.unlocked("ending")) == 10_000 and full.get("endings") == ["sad"]
    assert not [r for r in caplog.records if getattr(r, "code", None) == "W57"]


def _w131(form: str, count: int = 0) -> str:
    return format_message("W131", (form, count) if form == "endings" else (form,))


def _w131_records(caplog) -> list[str]:
    found = [r for r in caplog.records if getattr(r, "code", None) == "W131"]
    assert all(r.name == "vn.persist" for r in found)
    return [r.getMessage() for r in found]


def test_ac29_old_stored_endings_and_routes_values(tmp_path, game, caplog):
    program = load_e(tmp_path / "r")
    big = [f"x{i}" for i in range(999)] + ["good"]               # 1,000 items (default tier)
    rows = [
        ({"endings": ["sad", "good", "sad"]}, ("sad", "good"), [_w131("endings", 2)]),
        ({"endings": ["good", "nope", 3, None, ["sad"], "ZZMARK"]}, ("good",),
         [_w131("endings", 1)]),
        ({"endings": "sad"}, (), [_w131("endings", 0)]),
        ({"endings": {}}, (), [_w131("endings", 0)]),
        ({"endings": 7}, (), [_w131("endings", 0)]),
        ({"endings": []}, (), [_w131("endings", 0)]),
        ({"routes": ["promise"]}, (), [_w131("routes")]),
        ({"endings": ["sad"], "routes": ["promise"]}, ("sad",),
         [_w131("endings", 1), _w131("routes")]),
        ({"endings": big}, ("good",), [_w131("endings", 1)]),
    ]
    for n, (values, reached, warnings) in enumerate(rows):
        folder = game / f"p{n}"
        folder.mkdir()
        (folder / FILE_NAME).write_bytes(fileformat.encode_bytes(
            PersistentStore.with_data(values=values)))
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            h = Harness(folder, game=game, program=program)
            store = h.store
            launched(program, store)
            launched(program, store)                            # W131 once per store (I-1)
            assert store.unlocked("ending") == reached, values
            assert store.unlocked("route") == () and store.take_new_unlocks() == ()
            assert _w131_records(caplog) == warnings, values
            write(h)
            assert not {"endings", "routes"} & set(h.disk().get("values", {}))
            if n == 0:
                # TR-F19-08: copy B (an older engine) writes values.endings again; A merges.
                plant(h.path, fileformat.encode_bytes(PersistentStore.with_data(
                    values={"endings": ["sad", "good"]},
                    unlocks={"ending": ["sad", "good"]})))
                store.set("flowers", ["rose"])
                write(h)
                assert store.unlocked("ending") == ("sad", "good")
                assert store.take_new_unlocks() == () and len(_w131_records(caplog)) == 1
                assert "endings" not in h.disk().get("values", {})
        assert not [r for r in caplog.records if "ZZMARK" in r.getMessage()], values
