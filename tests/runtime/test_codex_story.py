"""F21 step 2 — tips and items in the story, headless (Run H on Template C, the *Paper
Lanterns* walkthrough, Harness Y): AC-F21-07's "Run H ends" rows (07 I-5), AC-F21-08 to 13,
AC-F21-17 to 20, and AC-F21-36 (rollback, moved into step 2 by 07 §2.2)."""

import dataclasses
import logging

import pytest

from engine.persist import fileformat
from engine.persist.location import FILE_NAME
from engine.persist.sync import MEMORY, READ_ONLY
from engine.runtime.codex import Codex
from engine.runtime.commands import (CodexAdded, ShowMenu, StepBack, StepForward, StoryEnded,
                                     StoryFailed)
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.persistent import UNLOCK_NAMES_MAX, PersistentStore
from engine.runtime.state import EMPTY_ITEMS, GameState, ItemsState
from tests.persist.sync_support import Harness, disk_unlocks, store_unlocks
from tests.persist.writer_support import base, game  # noqa: F401  (Harness Y's fixtures)
from tests.runtime.codex_story import (ALL, CA, WALK_INPUTS, added, launched, load_c,
                                       load_result, run_c, said, started, step, store_with,
                                       text_of, to_text, walk)

ZZ = "ZZMARK"


def _spy(monkeypatch, name: str) -> list:
    """Record each result of ``Codex.<name>``."""
    results: list = []
    real = getattr(Codex, name)

    def spy(self, *args):
        result = real(self, *args)
        results.append(result)
        return result

    monkeypatch.setattr(Codex, name, spy)
    return results


def _at_before(program, store=None, **kwargs):
    interp = started(program, store, **kwargs)
    out = to_text(interp, "Before.")
    return interp, out


# --- AC-F21-07 — reads of codex at run time (07 I-5) ----------------------------------------

@pytest.mark.parametrize("S, T", [
    ('if "brass_key" in codex.items:⏎[8]"A."', None),
    ("$ seen = codex.items", None),
    ("$ n = len(codex.tips)", None),
    ('$ s = list(codex.items)⏎[4]$ s.append("x")', None),
    ("$ k = f()", "define f = lambda: len(codex.items)"),
    (None, 'default had = "brass_key" in codex.items'),
], ids=["if", "seen", "len", "copy", "lambda", "default"])
def test_ac07_reading_codex_runs(tmp_path, S, T):
    result = load_result(tmp_path / "c", S=S, T=T)
    assert not result.errors and not result.warnings
    commands = run_c(result.program)
    assert type(commands[-1]) is StoryEnded and not any(type(c) is StoryFailed
                                                         for c in commands)


# --- AC-F21-08 — unlock tip at run time ------------------------------------------------------

def test_ac08_unlock_tip(tmp_path, monkeypatch):
    program = load_c(tmp_path / "known", S='unlock tip lanterns⏎[4]if "lanterns" in codex.tips:'
                                           '⏎[8]"Known."')
    store = store_with()
    commands = run_c(program, store)
    lines = [i for i, c in enumerate(commands) if type(c).__name__ == "Say"]
    known = next(i for i in lines if commands[i].text == "Known.")
    burst = commands[lines[lines.index(known) - 1] + 1:known + 1]
    assert added(burst) == [CA("tip", "lanterns")] and added(commands) == added(burst)
    assert store.unlocked("tip") == ("lanterns",)
    assert ("tip", "lanterns") in store.take_new_unlocks()

    results = _spy(monkeypatch, "unlock_tip")
    base_program = load_c(tmp_path / "base")
    twice = load_c(tmp_path / "twice", S="unlock tip lanterns⏎[4]unlock tip lanterns")
    commands = run_c(twice)
    assert added(commands) == [CA("tip", "lanterns")] and results == [True, False]
    # These lines wait for nothing, show nothing, and take no checkpoint.
    assert [c for c in commands if type(c) is not CodexAdded] == run_c(base_program)

    once = load_c(tmp_path / "once", S="unlock tip lanterns")
    known_store, plain_store = store_with(t=("lanterns",)), store_with(t=("lanterns",))
    assert added(run_c(once, known_store)) == []
    run_c(base_program, plain_store)
    assert known_store.version == plain_store.version            # the line changed nothing
    store = store_with()
    assert added(run_c(once, store)) == [CA("tip", "lanterns")]
    assert added(run_c(once, store)) == []                      # the second run


# --- AC-F21-09 — lock tip forgets a tip -------------------------------------------------------

def test_ac09_lock_tip(tmp_path, monkeypatch, caplog):
    results = _spy(monkeypatch, "relock_tip")
    program = load_c(tmp_path / "k", S="lock tip lanterns⏎[4]$ k = codex.tips")
    interp, out = _at_before(program, store_with(t=("lanterns", "river_god")))
    assert results == [True] and interp.G["k"] == ["river_god"] and added(out) == []

    results.clear()
    lock = load_c(tmp_path / "lock", S="lock tip lanterns")
    store, plain = store_with(), store_with()
    with caplog.at_level(logging.WARNING):
        commands = run_c(lock, store, dev=True)
    run_c(load_c(tmp_path / "base"), plain, dev=True)
    assert results == [False] and store.version == plain.version and added(commands) == []
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    again = load_c(tmp_path / "again", S="lock tip lanterns⏎[4]unlock tip lanterns")
    store = store_with(t=("lanterns",))
    assert added(run_c(again, store)) == [CA("tip", "lanterns")]
    assert store.unlocked("tip")[-1] == "lanterns"


# --- AC-F21-10 — unlock item and lock item at run time ----------------------------------------

@pytest.mark.parametrize("S, items, cas", [
    ("unlock item red_lantern", ["red_lantern"], ["red_lantern"]),
    ("unlock item brass_key⏎[4]unlock item red_lantern", ["brass_key", "red_lantern"],
     ["brass_key", "red_lantern"]),
    ("unlock item red_lantern⏎[4]unlock item brass_key⏎[4]unlock item red_lantern",
     ["red_lantern", "brass_key"], ["red_lantern", "brass_key"]),
    ("unlock item red_lantern⏎[4]lock item red_lantern", [], ["red_lantern"]),
    ("unlock item red_lantern⏎[4]lock item red_lantern⏎[4]unlock item red_lantern",
     ["red_lantern"], ["red_lantern", "red_lantern"]),
    ("lock item brass_key", [], []),
    ('unlock item brass_key⏎[4]if "brass_key" in codex.items:⏎[8]"Key."', None, ["brass_key"]),
], ids=range(7))
def test_ac10_unlock_and_lock_item(tmp_path, S, items, cas):
    program = load_c(tmp_path / "c", S=S)
    if items is None:                                       # the "Key." row
        commands = run_c(program)
        assert "Key." in said(commands)
        assert added(commands) == [CA("item", n) for n in cas]
        return
    interp = started(program)
    start = interp.checkpoint()
    out = to_text(interp, "Before.")
    assert interp.G["codex"].items == items
    assert added(out) == [CA("item", n) for n in cas]
    if S == "unlock item red_lantern":
        assert start.items is EMPTY_ITEMS
        assert interp.checkpoint().items.held == ("red_lantern",)
        base = load_c(tmp_path / "base")
        assert len(said(run_c(program))) == len(said(run_c(base)))   # same checkpoints


# --- AC-F21-11 — reading codex.tips and codex.items -------------------------------------------

def test_ac11_reading_codex(tmp_path):
    interp, _ = _at_before(load_c(tmp_path / "a", S="$ k = codex.tips"),
                           store_with(t=("river_god", "lanterns")))
    assert interp.G["k"] == ["lanterns", "river_god"] and type(interp.G["k"]) is list

    interp, _ = _at_before(load_c(tmp_path / "b", S=(
        'unlock item brass_key⏎[4]unlock item red_lantern⏎[4]$ seen = codex.items'
        '⏎[4]$ seen.append("x")⏎[4]$ again = codex.items')))
    assert interp.G["again"] == ["brass_key", "red_lantern"]
    state = interp.checkpoint()
    assert state.variables["seen"] == ["brass_key", "red_lantern", "x"]
    assert GameState.from_json(state.to_json()) == state

    interp, _ = _at_before(load_c(tmp_path / "c", S="$ a = codex.tips⏎[4]$ b = codex.tips"),
                           store_with(t=("lanterns",)))
    assert interp.G["a"] == interp.G["b"] and interp.G["a"] is not interp.G["b"]

    interp, _ = _at_before(load_c(tmp_path / "d", S="$ n = len(codex.tips)"),
                           store_with(t=("lanterns", "old_tip")))
    assert interp.G["n"] == 1

    interp = started(load_c(tmp_path / "e", S="$ i = codex.items"))
    state = dataclasses.replace(interp.checkpoint(), items=ItemsState(("gone", "brass_key")))
    assert interp.restore(state).result is RestoreResult.OK
    to_text(interp, "Before.")
    assert interp.G["i"] == ["brass_key"]

    program = load_c(tmp_path / "f", S='$ getattr(codex, "items").append("x")⏎[4]$ i = codex.items')
    interp, _ = _at_before(program)
    assert interp.G["i"] == [] and interp.status is Status.WAITING


# --- AC-F21-12 — run-time errors E256 ---------------------------------------------------------

def _failure(commands):
    failed = [c for c in commands if type(c) is StoryFailed]
    assert len(failed) == 1, commands[-3:]
    return failed[0].error


def test_ac12_e256(tmp_path):
    error = _failure(run_c(load_c(tmp_path / "a", T="define hint = codex.items")))
    (e,) = error.errors
    assert (e.code, e.line, e.message) == ("E256", 12, (
        "define hint couldn't be set: it reads codex, which holds items only once a game has "
        "started. Use a lambda or a default."))
    (e,) = _failure(run_c(load_c(tmp_path / "b", T="define hint = codex.tips"))).errors
    assert (e.code, e.line, e.message) == ("E256", 12, (
        "define hint couldn't be set: it reads codex, which holds tips only once a game has "
        "started. Use a lambda or a default."))

    program = load_c(tmp_path / "c", S='$ n = "items"⏎[4]$ setattr(codex, n, [])')
    interp = started(program)
    interp.codex.give("brass_key")
    step(interp)
    e = _failure(interp.take_commands(ALL))
    assert (e.code, e.line) == ("E256", 11)
    assert e.message.startswith("Python can't change codex.")
    assert interp.codex.items() == ("brass_key",)
    e = _failure(run_c(load_c(tmp_path / "d", S='$ n = "tips"⏎[4]$ delattr(codex, n)')))
    assert (e.code, e.line, e.message) == ("E256", 11, "Python can't change codex.tips. Use "
                                                       "unlock tip.")
    e = _failure(run_c(load_c(tmp_path / "e", S='$ x = getattr(codex, "itmes")')))
    assert (e.code, e.line, e.message) == ("E256", 10, 'there is no codex.itmes. Did you mean '
                                                       '"items"? codex has tips, items, and count.')
    e = _failure(run_c(load_c(tmp_path / "f", S='$ n = "zzz"⏎[4]$ x = getattr(codex, n)')))
    assert (e.code, e.line, e.message) == ("E256", 11, "there is no codex.zzz. codex has tips, "
                                                       "items, and count.")


# --- AC-F21-13 — W141 -----------------------------------------------------------------------

def test_ac13_w141(tmp_path, caplog):
    def w141(program, dev):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="vn.story"):
            run_c(program, dev=dev)
        return [r.getMessage() for r in caplog.records
                if r.name == "vn.story" and getattr(r, "code", None) == "W141"]

    twice = load_c(tmp_path / "a", S="lock item brass_key⏎[4]lock item brass_key")
    text = "lock item brass_key does nothing here, because the player doesn't have it."
    assert w141(twice, True) == [f"script/main.vns, line {n}: {text}" for n in (10, 11)]
    called = load_c(tmp_path / "b", S="call again⏎[4]call again",
                    T="label again:⏎[4]lock item brass_key⏎[4]return")
    assert w141(called, True) == [f"script/main.vns, line 14: {text}"]
    assert w141(twice, False) == []


# --- AC-F21-17 — what lasts, and how long ------------------------------------------------------

def test_ac17_what_lasts(tmp_path):
    S = "unlock tip lanterns⏎[4]unlock item red_lantern"

    def reads(interp):
        reader = interp.G["codex"]
        return reader.tips, reader.items

    for clear in ("$ persistent._clear()", "$ persistent._clear(progress=True)"):
        interp, _ = _at_before(load_c(tmp_path / clear[-6:-1], S=f"{S}⏎[4]{clear}"))
        assert reads(interp) == (["lanterns"], ["red_lantern"])

    program = load_c(tmp_path / "c", S=S)
    interp = started(program)
    k_s = interp.checkpoint()
    to_text(interp, "Before.")
    k_b = interp.checkpoint()
    for state, expected in ((k_s, (["lanterns"], [])), (k_b, (["lanterns"], ["red_lantern"]))):
        assert interp.restore(state).result is RestoreResult.OK
        assert reads(interp) == expected and added(interp.take_commands(ALL)) == []
    interp.new_game(42)
    interp.run(10_000)
    assert reads(interp) == (["lanterns"], []) and added(interp.take_commands(ALL)) == []
    interp.restore(k_b)
    interp.take_commands(ALL)
    interp.codex.mark_read("lanterns")
    interp.persistent.reset()                                    # F16's delete
    assert reads(interp) == ([], ["red_lantern"])
    assert interp.persistent.unlocked("codex_read") == ()

    program = load_c(tmp_path / "mid", S='lock tip lanterns⏎[4]"Mid."')
    interp = started(program, store_with(t=("lanterns",)))
    k_s = interp.checkpoint()
    to_text(interp, "Mid.")
    assert interp.restore(k_s).result is RestoreResult.OK
    assert reads(interp) == ([], []) and added(interp.take_commands(ALL)) == []


# --- AC-F21-18 — tips in the persistent file (Harness Y) ---------------------------------------

def _plant(folder, store):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE_NAME).write_bytes(fileformat.encode_bytes(store))


def _write(h):
    assert h.sync.flush_now(), h.sync.mode


def test_ac18_tips_in_the_persistent_file(tmp_path, game, caplog):  # noqa: F811
    program = load_c(tmp_path / "c")
    folder = game / "persistent"
    _plant(folder, PersistentStore.with_data(unlocks={"tip": ["old_tip", "lanterns", ZZ],
                                                      "codex_read": ["gone", "lanterns"]}))
    caplog.set_level(logging.DEBUG)
    h = Harness(folder, game=game)
    interp = launched(program, h.store)
    assert interp.G["codex"].tips == ["lanterns"] and interp.codex.is_read("lanterns")
    interp.codex.mark_read("river_god")
    _write(h)
    assert {("tip", "old_tip"), ("tip", ZZ), ("codex_read", "gone")} <= disk_unlocks(h.disk())
    for record in caplog.records:
        assert not any(s in record.getMessage() for s in ("old_tip", "gone", ZZ)), record
    # A full kind: an undeclared name gives way (UNLOCK_NAMES_MAX, real), no W57.
    full = PersistentStore.with_data(unlocks={"tip": [f"x{i}" for i in range(UNLOCK_NAMES_MAX)]})
    interp = launched(program, full)
    caplog.clear()
    assert interp.codex.unlock_tip("lanterns") and interp.codex.tips() == ("lanterns",)
    assert not any(getattr(r, "code", None) == "W57" for r in caplog.records)

    # Two copies, one folder, each writing after its change.
    for row, launch_tips in (("both", []), ("relock", ["lanterns"])):
        folder = game / row
        _plant(folder, PersistentStore.with_data(unlocks={"tip": launch_tips}))
        a, b = Harness(folder, game=game), Harness(folder, game=game)
        ia, ib = launched(program, a.store), launched(program, b.store)
        if row == "both":
            ia.codex.unlock_tip("lanterns")
            _write(a)
            ib.codex.unlock_tip("river_god")
            _write(b)
            expected = {("tip", "lanterns"), ("tip", "river_god")}
        else:
            ia.codex.relock_tip("lanterns")
            _write(a)
            b.store.set("n", 1)
            _write(b)
            expected = set()
        for h in (a, b, a):                                      # the next merge
            h.store.version += 1
            _write(h)
        tips = [{u for u in found if u[0] == "tip"} for found in
                (disk_unlocks(a.disk()), store_unlocks(a.store), store_unlocks(b.store))]
        assert tips == [expected] * 3, row


# --- AC-F21-19 and AC-F21-20 — the walkthrough, and without a persistent file ------------------

def _walk_run(store):
    """One walkthrough run: (items at "The bridge.", the bridge menu's choices, said, CAs,
    tips at the end, items and tips at the first line)."""
    interp = started(walk(), store)
    first = (interp.G["codex"].items, interp.G["codex"].tips)
    out = to_text(interp, "The bridge.")
    at_bridge = interp.G["codex"].items
    while interp.status is Status.WAITING:
        step(interp)
        out += interp.take_commands(ALL)
    assert type(out[-1]) is StoryEnded
    menu = next(c for c in out if type(c) is ShowMenu)
    choices = ["".join(s.text for s in c.body.plain()) for c in menu.choices if not c.locked]
    return at_bridge, choices, said(out), added(out), interp.G["codex"].tips, first


def _walkthrough(store) -> None:
    """AC-F21-20's two runs on ``store``."""
    at_bridge, choices, lines, cas, tips, _ = _walk_run(store)
    assert at_bridge == ["red_lantern"] and choices == ["Say nothing"]
    assert cas == [CA("item", "red_lantern"), CA("tip", "lanterns"), CA("tip", "river_god")]
    assert tips == ["lanterns", "river_god"]
    at_bridge, choices, lines, cas, tips, first = _walk_run(store)
    assert first == ([], ["lanterns", "river_god"])
    assert choices == ["Ask about the river god", "Say nothing"]
    assert "He grants one wish a year." in lines and at_bridge == ["red_lantern"]
    assert cas == [CA("item", "red_lantern")] and tips == ["lanterns", "river_god"]


def test_ac20_the_walkthrough(tmp_path):
    _walkthrough(PersistentStore(identity_scheme=walk().identity_scheme))
    commands = run_c(walk(), inputs=WALK_INPUTS)
    assert type(commands[-1]) is StoryEnded
    bad = (tmp_path / "bad" / "script")
    bad.mkdir(parents=True)
    from tests.runtime.codex_story import F21
    text = (F21 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")
    (bad / "main.vns").write_text(text.replace("unlock tip lanterns", "unlock tip lantern"),
                                  encoding="utf-8")
    from engine.core.paths import GamePaths
    from engine.script import load_story
    result = load_story(GamePaths((tmp_path / "bad").resolve()))
    assert [(e.code, 'Did you mean "lanterns"?' in e.message) for e in result.errors] == [
        ("E253", True)]


def test_ac19_without_a_persistent_file(game):  # noqa: F811
    memory = Harness(game / "memory", game=game, mode=MEMORY)
    folder = game / "readonly"
    folder.mkdir()
    newer = b'{"format":2}'
    (folder / FILE_NAME).write_bytes(newer)
    readonly = Harness(folder, game=game, mode=READ_ONLY)
    headless = PersistentStore(identity_scheme=walk().identity_scheme)
    for store, h in ((memory.store, memory), (readonly.store, readonly), (headless, None)):
        _walkthrough(store)
        if h is not None:
            h.ticks(10.0)
        codex = launched(walk(), store).codex
        assert codex.mark_read("lanterns") and codex.is_read("lanterns")
    assert not (game / "memory").exists()
    assert (folder / FILE_NAME).read_bytes() == newer and sorted(folder.iterdir()) == [
        folder / FILE_NAME]


# --- AC-F21-36 — rolling back over unlock and lock (Driver D's events) --------------------------

def _back(interp, n=1):
    interp.post(StepBack(n))
    interp.run(10_000)
    return interp.take_commands(ALL)


def _forward(interp, n=1):
    interp.post(StepForward(n))
    while interp.busy:
        interp.run(10_000)
    return interp.take_commands(ALL)


def test_ac36_rolling_back(tmp_path, monkeypatch):
    gives, tips = _spy(monkeypatch, "give"), _spy(monkeypatch, "unlock_tip")
    program = load_c(tmp_path / "a", S='"A."⏎[4]unlock item red_lantern⏎[4]unlock tip lanterns'
                                       '⏎[4]"B."')
    interp = started(program, rollback_steps=100)
    to_text(interp, "B.")
    version = interp.persistent.version
    out = _back(interp)
    reader = interp.G["codex"]
    assert text_of(interp) == "A." and reader.items == [] and reader.tips == ["lanterns"]
    assert interp.persistent.version == version and added(out) == []
    gives.clear(), tips.clear()
    out = _forward(interp)
    assert text_of(interp) == "B." and reader.items == ["red_lantern"] and added(out) == []
    assert gives == [True] and tips == [False]
    _back(interp)
    step(interp)                                                # a click forward: live
    assert text_of(interp) == "B."
    assert added(interp.take_commands(ALL)) == [CA("item", "red_lantern")]

    program = load_c(tmp_path / "b", S='unlock item red_lantern⏎[4]"A."⏎[4]lock item '
                                       'red_lantern⏎[4]"B."')
    interp = started(program, rollback_steps=100)
    to_text(interp, "B.")
    _back(interp)
    assert text_of(interp) == "A." and interp.G["codex"].items == ["red_lantern"]
    matches = interp.timeline.matches
    _forward(interp)
    assert text_of(interp) == "B." and interp.G["codex"].items == []
    assert interp.timeline.matches == matches + 1                # the future was kept

    program = load_c(tmp_path / "c", S='"A."⏎[4]if "lanterns" in codex.tips:⏎[8]"Known."'
                                       '⏎[4]lock tip lanterns⏎[4]"B."')
    interp = started(program, store_with(t=("lanterns",)), rollback_steps=100)
    to_text(interp, "B.")
    _back(interp, 2)
    assert text_of(interp) == "A."
    _forward(interp)
    t = interp.timeline
    assert text_of(interp) == "B." and t.cursor == len(t.states) - 1   # the future dropped
