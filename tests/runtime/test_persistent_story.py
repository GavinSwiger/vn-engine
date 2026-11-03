"""F12 persistent data in the story (F12 ``06-acceptance.md`` §1.1–1.3; checklist step 3).

Run P (06 §0.2): template P (``tests/fixtures/F12/template/``) with the row's edit, loaded
clean, then launched and played with an in-memory ``PersistentStore`` (``run_headless(...,
persistent=store)`` or ``run_launch`` + ``Interpreter`` when a test needs the interpreter).

Step 3a: AC-F12-02, 03, 04, 05 (launch and run rows; load rows are in
``tests/script/test_messages.py``), 07, 08, 09, 10, 30, and the milestone (the walkthrough
on an in-memory store). Step 3b (F07 has landed): AC-F12-06, 12, 13. AC-F12-01 is
``tests/script/test_persistent_default.py``; the facade's own rows of AC-F12-10 are
``test_persistent_namespace.py``.

Per F19's coming ownership of ``persistent.endings`` and ``persistent.routes``, these tests
use ``persistent.flowers`` where the ACs say ``persistent.endings``.
"""

import json
import logging
import tempfile
from pathlib import Path

import pytest

from engine.persist.fileformat import Outcome, ReadJob
from engine.runtime.commands import Advance, Choose, Say, ShowMenu, StoryEnded, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import (PersistentNoValue, PersistentStore, PERSIST_MAX_BYTES,
                                       PERSIST_MAX_NAMES)
from engine.runtime.values import same_value
from engine.script.diagnostics import ScriptErrorGroup
from engine.script.menu import Menu
from engine.script.messages import format_message
from engine.script.nodes import Say as SayNode
from tests.runtime.story import load_files
from tests.script import message_cases
from tests.script.helpers import template_p

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F12"


def empty() -> PersistentStore:
    return PersistentStore(identity_scheme=1)


def load_p(root: Path, *, S: str | None = None, T: str | None = None,
           replace: dict[int, str] | None = None):
    return load_files(root, {"main.vns": template_p(S=S, T=T, replace=replace)})


def run_p(root: Path, store: PersistentStore | None = None, *, S: str | None = None,
          T: str | None = None, replace: dict[int, str] | None = None, inputs=()):
    """Run P: the commands, and the store the run used."""
    store = empty() if store is None else store
    program = load_p(root, S=S, T=T, replace=replace)
    return run_headless(program, seed=42, persistent=store, inputs=inputs), store


def start_p(program, store: PersistentStore, **kwargs) -> Interpreter:
    launch = run_launch(program, persistent=store)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    interp = Interpreter(program, launch.namespace, persistent=store, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    return interp


def advance(interp: Interpreter) -> None:
    assert interp.status is Status.WAITING
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)


def play(interp: Interpreter) -> None:
    while interp.status is Status.WAITING:
        advance(interp)


def texts(commands) -> list[str]:
    return [c.text for c in commands if type(c) is Say]


def failure(commands):
    """The one ``StoryFailed`` error of a run (a launch failure's group unwrapped)."""
    failed = [c for c in commands if type(c) is StoryFailed]
    assert len(failed) == 1 and commands[-1] is failed[0], commands
    error = failed[0].error
    if isinstance(error, ScriptErrorGroup):
        assert len(commands) == 1
        (error,) = error.errors
    return error


def values(store: PersistentStore) -> dict:
    """The stored values, without F32's built-in ``playthrough`` at its launch value 0
    (``test_persistent_builtin.py`` covers it)."""
    found = store.values_snapshot()
    if found.get("playthrough") == 0:
        del found["playthrough"]
    return found


def say_sid(program, text: str) -> str:
    return next(s.sid for s in program.iter_statements()
                if isinstance(s, SayNode) and s.text == text)


def menu_of(program) -> Menu:
    return next(s for s in program.iter_statements() if type(s) is Menu)


# --- AC-F12-05 — the launch and run rows of cases.toml -----------------------------------

CASES = [c for c in message_cases.load_cases() if c.feature == "F12" and c.time != "load"]


def test_ac05_rows_cover_the_run_and_launch_codes():
    assert {c.code for c in CASES} == {"E180", "E181", "E182", "E183", "E185"}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_ac05_message(case):
    with tempfile.TemporaryDirectory() as tmp:
        text = message_cases.main_text(case)
        program = load_files(Path(tmp), {"main.vns": text})
        commands = run_headless(program, seed=42, persistent=empty())
    error = failure(commands)
    if case.time == "launch":
        assert type(commands[0].error) is ScriptErrorGroup
    message_cases.check_case(case, message_cases.Outcome([error], (), 1, False))
    assert error.code == case.code
    assert "\n" not in error.format() and "Traceback" not in error.format()


# --- AC-F12-02 — persistent defaults at launch ------------------------------------------------

@pytest.mark.parametrize("stored, edit, expected", [
    ({}, {}, {"festivals": 0, "hana_remembers": False}),
    ({"festivals": 2}, {}, {"festivals": 2, "hana_remembers": False}),
    ({"festivals": 0}, {"replace": {2: "default persistent.festivals = 5"}},
     {"festivals": 0, "hana_remembers": False}),
    ({}, {"replace": {2: "default persistent.festivals = 5"}},
     {"festivals": 5, "hana_remembers": False}),
    ({"festivals": 2}, {"T": "default persistent.next = persistent.festivals + 1"},
     {"festivals": 2, "hana_remembers": False, "next": 3}),
    ({}, {"T": "default persistent.next = persistent.festivals + 1"},
     {"festivals": 0, "hana_remembers": False, "next": 1}),
    ({}, {"T": "define base = 10⏎default persistent.score = base"},
     {"festivals": 0, "hana_remembers": False, "score": 10}),
    ({"old_flag": 1}, {"S": "$ x = persistent.old_flag"},
     {"old_flag": 1, "festivals": 0, "hana_remembers": False}),
], ids=["empty", "kept", "patch-kept", "patch-new", "next-3", "next-1", "define", "old"])
def test_ac02_persistent_defaults_at_launch(tmp_path, stored, edit, expected):
    store = PersistentStore.with_data(values=stored)
    commands, _ = run_p(tmp_path, store, **edit)
    assert texts(commands) == ["Start.", "End."] and type(commands[-1]) is StoryEnded
    assert values(store) == expected


def test_ac02_a_failing_default_has_the_prefix(tmp_path):
    error = failure(run_p(tmp_path / "a", T="default persistent.bad = 1 / 0")[0])
    assert (error.file, error.line) == ("script/main.vns", 10)
    assert error.message == ("default persistent.bad couldn't be set: "
                             + format_message("E85g", ("",)))
    error = failure(run_p(tmp_path / "b", T="default persistent.s = {1}")[0])
    assert error.code == "E181" and error.line == 10
    assert error.message.startswith("default persistent.s couldn't be set: persistent.s can't "
                                    "hold a set")


def test_ac02_a_default_of_a_failed_define_is_skipped(tmp_path):
    program = load_p(tmp_path, T="define base = 1 / 0⏎default persistent.score = base")
    launch = run_launch(program, persistent=(store := empty()))
    assert launch.namespace is None and [e.code for e in launch.errors] == ["E85g"]
    assert "score" not in values(store)


# --- AC-F12-03 — defines can't read persistent ---------------------------------------------------

@pytest.mark.parametrize("T, line", [
    ('define title = "Again?" if persistent.cleared else "Hello"', 10),
    ("define helper = lambda: persistent.festivals⏎define t2 = helper()", 11),
    ('define hp = hasattr(persistent, "x")', 10),
    ("define names = dir(persistent)", 10),
], ids=["read", "helper", "hasattr", "dir"])
def test_ac03_defines_fail_with_e185(tmp_path, T, line):
    error = failure(run_p(tmp_path, T=T)[0])
    assert (error.code, error.line) == ("E185", line)
    assert "but define values are set once at launch" in error.message


def test_ac03_the_store_is_unlocked_after_a_failing_define(tmp_path):
    store = empty()
    run_p(tmp_path, store, T='define hp = hasattr(persistent, "x")')
    store.set("x", 1)                               # no PersistentInDefine left behind


@pytest.mark.parametrize("stored, expected", [({}, "Hello"), ({"festivals": 1}, "Again?")])
def test_ac03_a_lambda_define_may_read_persistent(tmp_path, stored, expected):
    program = load_p(tmp_path, S="$ x = title()",
                     T='define title = lambda: "Again?" if persistent.festivals else "Hello"')
    interp = start_p(program, PersistentStore.with_data(values=stored))
    play(interp)
    assert interp.status is Status.ENDED and interp.G["x"] == expected


# --- AC-F12-04 — W56 ---------------------------------------------------------------------------

W56_TEXT = ("script/main.vns, line 7: persistent.hana_rememebrs is read here but never set or "
            'given a default. Did you mean "hana_remembers"?')
TYPO = 'if persistent.hana_rememebrs:⏎[8]"A."⏎[4]$ y = persistent.hana_rememebrs'


def w56(program, store=None, *, dev=True) -> list[str]:
    launch = run_launch(program, dev=dev, persistent=store or empty())
    return [w.format() for w in launch.warnings if w.code == "W56"]


def test_ac04_one_w56_at_the_first_use(tmp_path):
    program = load_p(tmp_path, S=TYPO)
    assert w56(program) == [W56_TEXT]
    assert w56(program, dev=False) == []                            # release: none


@pytest.mark.parametrize("S, T, stored", [
    ("$ z = persistent.festivals", None, {}),                       # defaulted
    ("$ z = persistent.k⏎[4]$ persistent.k = 1", None, {}),         # written
    ('$ z = persistent.k⏎[4]$ setattr(persistent, "k", 1)', None, {}),
    ("$ z = persistent.k⏎[4]$ del persistent.k", None, {}),         # deleted
    ("$ z = persistent.k", None, {"k": 1}),                         # stored
    ("$ z = persistent.k", "default persistent.k = 1", {}),
], ids=["default", "set", "setattr", "del", "stored", "default-later"])
def test_ac04_no_w56_for_known_names(tmp_path, S, T, stored):
    assert w56(load_p(tmp_path, S=S, T=T), PersistentStore.with_data(values=stored)) == []


def test_ac04_a_read_in_a_define_lambda_warns_at_its_line(tmp_path):
    program = load_p(tmp_path, T="define greet = lambda: persistent.gret")
    (text,) = w56(program)
    assert text.startswith("script/main.vns, line 10: persistent.gret is read here")


def test_ac04_w56_without_a_suggestion(tmp_path):
    (text,) = w56(load_p(tmp_path, S="$ z = persistent.zzzqqq"))
    assert text.endswith("Give it a starting value with default persistent.zzzqqq = False at "
                         "the top level of a file.")


# --- AC-F12-06 — read, set, and delete everywhere (3b) --------------------------------------------

def test_ac06_augmented_set(tmp_path):
    _, store = run_p(tmp_path, S="$ persistent.festivals += 1")
    assert values(store)["festivals"] == 1


def test_ac06_conditions(tmp_path):
    commands, _ = run_p(tmp_path, S='$ persistent.met = True⏎[4]if persistent.met:⏎[8]"Yes."'
                                    '⏎[4]elif persistent.festivals:⏎[8]"No."')
    assert texts(commands) == ["Start.", "Yes.", "End."]


@pytest.mark.parametrize("stored, offered", [({}, ["River"]),
                                             ({"hana_remembers": True}, ["Bridge", "River"])])
def test_ac06_choice_conditions(tmp_path, stored, offered):
    S = 'menu:⏎[8]"Bridge" if persistent.hana_remembers:⏎[12]"A."⏎[8]"River":⏎[12]"B."'
    commands, _ = run_p(tmp_path, PersistentStore.with_data(values=stored), S=S)
    (menu,) = [c for c in commands if type(c) is ShowMenu]
    assert [c.body.plain()[0].text for c in menu.choices] == offered


@pytest.mark.parametrize("S, expected", [
    ('$ setattr(persistent, "k", 2)⏎[4]$ v = getattr(persistent, "k")⏎[4]'
     '$ h = hasattr(persistent, "k")', {"v": 2, "h": True}),
    ('$ a = hasattr(persistent, "nope")⏎[4]$ b = hasattr(persistent, "festivals")',
     {"a": False, "b": True}),
    ('$ persistent.k = 1⏎[4]$ del persistent.k⏎[4]$ h = hasattr(persistent, "k")',
     {"h": False}),
    ("$ x = 5⏎[4]$ persistent.x = 1⏎[4]$ y = x", {"y": 5}),
], ids=["setattr", "hasattr", "del", "separate"])
def test_ac06_attribute_functions(tmp_path, S, expected):
    store = empty()
    interp = start_p(load_p(tmp_path, S=S), store)
    play(interp)
    assert interp.status is Status.ENDED
    for name, value in expected.items():
        assert interp.G[name] == value
    assert ("k" in values(store)) == (expected.get("h") is True)


def test_ac06_a_define_x_and_persistent_x_are_separate(tmp_path):
    store = empty()
    interp = start_p(load_p(tmp_path, S="$ persistent.x = 1⏎[4]$ y = x", T="define x = 5"),
                     store)
    play(interp)
    assert interp.G["y"] == 5 and values(store)["x"] == 1


def test_ac06_in_place_list_change_is_kept_and_encoded(tmp_path):
    _, store = run_p(tmp_path, S='$ persistent.flowers = ["iris"]⏎[4]'
                                 '$ persistent.flowers.append("lotus")')
    assert values(store)["flowers"] == ["iris", "lotus"]
    assert store.value_frag("flowers") == b'["iris","lotus"]'


@pytest.mark.parametrize("stored, expected", [({}, 0), ({"festivals": 2}, 4)])
def test_ac06_lambda_define_reads_at_call_time(tmp_path, stored, expected):
    program = load_p(tmp_path, S="$ g = greet()",
                     T="define greet = lambda: persistent.festivals * 2")
    interp = start_p(program, PersistentStore.with_data(values=stored))
    play(interp)
    assert interp.G["g"] == expected


def test_ac06_an_alias_is_e85e_at_the_next_checkpoint(tmp_path):
    commands, store = run_p(tmp_path, S="$ p = persistent⏎[4]$ p.y = 1")
    error = failure(commands)
    assert values(store)["y"] == 1
    assert error.code == "E85e" and error.line == 8          # the newest $ line naming p
    assert error.message.startswith('"p" holds persistent data, which can\'t be saved.')


# --- AC-F12-07 — outside saves, new games, and rollback -------------------------------------------

def test_ac07_checkpoints_hold_no_persistent_data(tmp_path):
    store = PersistentStore.with_data(values={"festivals": 2, "note": "ZZMARK"})
    program = load_p(tmp_path, S="$ persistent.n = persistent.festivals + 1")
    interp = start_p(program, store)
    first = interp.checkpoint()
    advance(interp)
    text = json.dumps(interp.checkpoint().to_json())
    assert "ZZMARK" not in text and "festivals" not in text
    assert set(interp.checkpoint().to_json()) == set(first.to_json())
    plain = start_p(load_files(tmp_path / "plain", {"main.vns": template_p()}), empty())
    assert set(plain.checkpoint().to_json()) == set(first.to_json())


def test_ac07_new_game_and_restores_leave_the_store(tmp_path):
    store = PersistentStore.with_data(values={"festivals": 2, "note": "ZZMARK"})
    program = load_p(tmp_path, S="$ persistent.n = persistent.festivals + 1")
    interp = start_p(program, store)
    snapshots = [interp.checkpoint()]
    advance(interp)
    snapshots.append(interp.checkpoint())
    version, before = store.version, values(store)
    for state in snapshots:
        assert interp.restore(state).result is RestoreResult.OK
        assert (store.version, values(store)) == (version, before)
    interp.new_game(7)
    assert (store.version, values(store)) == (version, before)   # before the first burst
    interp.run(10_000)
    assert interp.current.text == "Start." and store.version == version


def test_ac07_rolling_back_over_a_change_runs_it_again(tmp_path):
    store = PersistentStore.with_data(values={"n": 0})
    interp = start_p(load_p(tmp_path, S="$ persistent.n += 1"), store)
    before = interp.checkpoint()
    advance(interp)
    assert values(store)["n"] == 1
    assert interp.restore(before).result is RestoreResult.OK
    advance(interp)
    assert values(store)["n"] == 2


def test_ac07_a_load_keeps_a_later_value(tmp_path):
    store = empty()
    interp = start_p(load_p(tmp_path, S="$ persistent.hana_remembers = True"), store)
    before = interp.checkpoint()
    play(interp)
    assert interp.restore(before).result is RestoreResult.OK
    assert values(store)["hana_remembers"] is True


# --- AC-F12-08 — names with no value, del, and suggestions ---------------------------------------

def test_ac08_stored_names_are_suggested(tmp_path):
    store = PersistentStore.with_data(values={"festivals_seen": 1})
    error = failure(run_p(tmp_path, store, S="$ x = persistent.festivals_sen")[0])
    assert error.code == "E180" and 'Did you mean "festivals_seen"?' in error.message


def test_ac08_del_restores_a_copy_of_the_launch_value(tmp_path):
    S = ('$ persistent.flowers.append("a")⏎[4]$ del persistent.flowers⏎[4]'
         "$ e1 = list(persistent.flowers)⏎[4]$ persistent.flowers.append(\"b\")⏎[4]"
         "$ del persistent.flowers⏎[4]$ e2 = list(persistent.flowers)")
    interp = start_p(load_p(tmp_path, S=S, T="default persistent.flowers = []"), empty())
    play(interp)
    assert interp.status is Status.ENDED and interp.G["e1"] == interp.G["e2"] == []


def test_ac08_del_of_a_set_default(tmp_path):
    _, store = run_p(tmp_path, S="$ persistent.festivals = 3⏎[4]$ del persistent.festivals")
    assert values(store)["festivals"] == 0


# --- AC-F12-09 — plain values and in-place changes ----------------------------------------------

def test_ac09_a_set_keeps_a_copy(tmp_path):
    store = empty()
    interp = start_p(load_p(tmp_path, S="$ l = [1]⏎[4]$ persistent.l = l⏎[4]$ l.append(2)"),
                     store)
    play(interp)
    assert values(store)["l"] == [1] and interp.G["l"] == [1, 2]


@pytest.mark.parametrize("value", ["None", "True", "3", "2.5", '"花"', '[1, "a"]',
                                   '{"k": [1]}'])
def test_ac09_plain_values_round_trip(tmp_path, value):
    _, store = run_p(tmp_path, S=f"$ persistent.v = {value}")
    expected = eval(value)
    assert same_value(values(store)["v"], expected)
    assert same_value(json.loads(store.value_frag("v")), expected)


@pytest.mark.parametrize("value, words", [
    ("{1, 2}", "can't hold a set"), ('float("nan")', 'can\'t hold "not a number" (nan)'),
    ("(1, 2)", "can't hold a tuple"), ("len", "can't hold a function"),
    ("10**4300", "can't hold a whole number with more than 4,300 digits"),
])
def test_ac09_unsaveable_values_are_e181(tmp_path, value, words):
    store = empty()
    interp = start_p(load_p(tmp_path, S=f"$ persistent.v = {value}"), store)
    version, before = store.version, values(store)
    interp.post(Advance(interp.current.sid))
    version += 1                                        # the accepted Advance's mark
    interp.run(10_000)
    error = failure(interp.take_commands(100))
    assert error.code == "E181" and words in error.message and error.line == 7
    assert (store.version, values(store)) == (version, before)


def test_ac09_an_in_place_failure_keeps_the_last_good_fragment(tmp_path):
    commands, store = run_p(tmp_path, S="$ persistent.bag = []⏎[4]$ persistent.bag.append({1})")
    assert failure(commands).line == 8
    assert store.value_frag("bag") == b"[]"


def test_ac09_an_in_place_change_over_the_cap_is_e183(tmp_path):
    commands, _ = run_p(tmp_path, S='$ persistent.big = []⏎[4]'
                                    '$ persistent.big.extend(["x" * 1000] * 1100)')
    error = failure(commands)
    assert (error.code, error.line) == ("E183", 8)
    assert error.message.startswith("persistent data is now 1.1 MB, over the 1 MB limit")


def test_ac09_an_in_place_change_before_return_is_kept(tmp_path):
    """07 I-3: checked before the story ends."""
    commands, store = run_p(tmp_path, S='$ persistent.flowers.append("x")⏎[4]return',
                            T="default persistent.flowers = []")
    assert type(commands[-1]) is StoryEnded
    assert store.value_frag("flowers") == b'["x"]'


def test_ac09_an_in_place_failure_before_return_fails_the_story(tmp_path):
    commands, _ = run_p(tmp_path, S="$ persistent.flowers.append({1})⏎[4]return",
                        T="default persistent.flowers = []")
    error = failure(commands)
    assert (error.code, error.line) == ("E181", 7)


@pytest.mark.parametrize("S", [
    '$ persistent.flowers.append("x")',
    '$ persistent.flowers.pop()',
    '$ persistent.d["a"]["b"] = 2',
    '$ e = persistent.flowers⏎[4]"Mid."⏎[4]$ e.append("x")',
], ids=["append", "pop", "nested", "alias"])
def test_ac09_check_in_place_notices_changes(tmp_path, S):
    store = PersistentStore.with_data(values={"flowers": ["iris"], "d": {"a": {"b": 1}}})
    interp = start_p(load_p(tmp_path, S=S), store)
    while interp.current.text != "End.":
        before_frags = {n: store.value_frag(n) for n in ("flowers", "d")}
        interp.post(Advance(interp.current.sid))
        version = store.version
        interp.run(10_000)
    changed = {n for n in ("flowers", "d") if store.value_frag(n) != before_frags[n]}
    assert len(changed) == 1 and store.version == version + 1


def test_ac09_unchanged_values_cost_no_version(tmp_path):
    store = PersistentStore.with_data(values={"flowers": ["iris"]})
    interp = start_p(load_p(tmp_path, S="$ n = len(persistent.flowers)"), store)
    interp.post(Advance(interp.current.sid))
    version = store.version
    interp.run(10_000)
    assert interp.current.text == "End." and store.version == version


def test_ac09_check_in_place_runs_only_after_author_code(tmp_path):
    S = '$ n = len(persistent.flowers)⏎[4]"A."⏎[4]"B."⏎[4]"C."'
    store = PersistentStore.with_data(values={"flowers": ["iris"]})
    interp = start_p(load_p(tmp_path, S=S), store)
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        real = store.check_in_place
        mp.setattr(store, "check_in_place", lambda: calls.append(1) or real())
        advance(interp)                                  # the $ line ran: checked at "A."
        assert interp.current.text == "A." and calls == [1]
        for _ in range(3):                               # "B.", "C.", "End.": no author code
            advance(interp)
        assert calls == [1]


# --- AC-F12-10 — engine names and _clear in the story --------------------------------------------

def clear_store(program) -> PersistentStore:
    store = PersistentStore.with_data(
        values={"festivals": 3, "old_flag": 1, "flowers": ["sad"]},
        seen=("start/aaaaaaaaaaaa", "start/bbbbbbbbbbbb"),
        chosen=(("start/cccccccccccc", "dddddddddddd"),), unlocks={"cg": ["river_night"]})
    return store


def test_ac10_clear_restores_defaults_and_keeps_records(tmp_path):
    program = load_p(tmp_path, S="$ persistent._clear()", T="default persistent.flowers = []")
    store = clear_store(program)
    commands = run_headless(program, seed=42, persistent=store)
    assert type(commands[-1]) is StoryEnded
    assert values(store) == {"festivals": 0, "hana_remembers": False, "flowers": []}
    with pytest.raises(PersistentNoValue):
        store.get("old_flag")
    assert store.is_seen("start/aaaaaaaaaaaa") and store.is_seen("start/bbbbbbbbbbbb")
    assert store.was_chosen("start/cccccccccccc", "dddddddddddd")
    assert store.unlocked("cg") == ("river_night",)


def test_ac10_clear_with_progress_empties_records_but_not_unlocks(tmp_path):
    program = load_p(tmp_path, S="$ persistent._clear(progress=True)",
                     T="default persistent.flowers = []")
    store = clear_store(program)
    run_headless(program, seed=42, persistent=store)
    assert not store.is_seen("start/aaaaaaaaaaaa") and not store.is_seen("start/bbbbbbbbbbbb")
    assert not store.is_seen(say_sid(program, "Start."))     # cleared after it was marked
    assert not store.was_chosen("start/cccccccccccc", "dddddddddddd")
    assert store.unlocked("cg") == ("river_night",)


def test_ac10_dir_and_repr_in_the_story(tmp_path):
    store = PersistentStore.with_data(values={"note": "ZZMARK"})
    interp = start_p(load_p(tmp_path, S="$ d = dir(persistent)⏎[4]$ r = repr(persistent)"),
                     store)
    play(interp)
    assert interp.G["d"] == sorted(store.names())
    assert interp.G["r"] == "<persistent data>"


def test_ac10_the_stub_is_gone():
    engine = Path(__file__).resolve().parents[2] / "engine"
    for path in engine.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "PersistentStub" not in text and "PersistentUnavailable" not in text, path


# --- AC-F12-12 — seen lines (3b) -----------------------------------------------------------------

MENU_Q = 'menu:⏎[8]"Which way?"⏎[8]"Bridge":⏎[12]"A."⏎[8]"River":⏎[12]"B."'
MENU_NO_Q = 'menu:⏎[8]"Bridge":⏎[12]"A."⏎[8]"River":⏎[12]"B."'


def test_ac12_accepted_lines_and_questions_are_seen(tmp_path):
    program = load_p(tmp_path, S=MENU_Q)
    store = empty()
    commands = run_headless(program, seed=42, persistent=store,
                            inputs=("advance", "choose 1"))
    assert texts(commands) == ["Start.", "Which way?", "A.", "End."]
    menu = menu_of(program)
    for text in ("Start.", "A.", "End."):
        assert store.is_seen(say_sid(program, text)), text
    assert store.is_seen(menu.sid)                          # the question (its sid)
    assert not store.is_seen(say_sid(program, "B."))


def test_ac12_ignored_events_mark_nothing(tmp_path):
    program = load_p(tmp_path)
    store = empty()
    interp = start_p(program, store)
    version = store.version
    interp.post(Advance(say_sid(program, "End.")))          # another sid
    assert store.version == version
    play(interp)
    version = store.version
    interp.post(Advance(say_sid(program, "End.")))          # not WAITING
    assert store.version == version


def test_ac12_a_menu_without_a_question_marks_no_line(tmp_path):
    program = load_p(tmp_path, S=MENU_NO_Q)
    store = empty()
    run_headless(program, seed=42, persistent=store, inputs=("advance", "choose 2"))
    menu = menu_of(program)
    assert not store.is_seen(menu.sid)
    assert store.was_chosen(menu.sid, menu.choices[1].key)


def test_ac12_an_edited_line_is_unseen(tmp_path):
    store = empty()
    first = load_p(tmp_path / "a")
    run_headless(first, seed=42, persistent=store)
    old = say_sid(first, "Start.")
    edited = load_p(tmp_path / "b", replace={6: '    hana "Start!"'})
    new = say_sid(edited, "Start!")
    assert new != old and not store.is_seen(new) and store.is_seen(old)


def test_ac12_a_filled_store_and_skip_style_advances(tmp_path):
    program = load_p(tmp_path)
    sid = say_sid(program, "Start.")
    store = PersistentStore.with_data(seen=(sid,))
    assert store.is_seen(sid)
    fresh = empty()
    interp = start_p(program, fresh)
    before = interp.checkpoint()
    interp.post(Advance(sid))                               # as F15's skip will post it
    assert fresh.is_seen(sid)
    assert interp.checkpoint() is before                    # marking changes no state


# --- AC-F12-13 — choice marks (3b) ----------------------------------------------------------------

def test_ac13_choice_marks_across_runs(tmp_path):
    program = load_p(tmp_path, S=MENU_Q)
    menu = menu_of(program)
    bridge, river = (c.key for c in menu.choices)
    store = empty()
    run_headless(program, seed=42, persistent=store, inputs=("advance", "choose 2"))
    assert store.was_chosen(menu.sid, river) and not store.was_chosen(menu.sid, bridge)
    run_headless(program, seed=42, persistent=store, inputs=("advance", "choose 1"))
    assert store.was_chosen(menu.sid, river) and store.was_chosen(menu.sid, bridge)
    store.clear()
    assert store.was_chosen(menu.sid, river)
    store.clear(progress=True)
    assert not store.was_chosen(menu.sid, river) and not store.was_chosen(menu.sid, bridge)


def test_ac13_an_ignored_choose_marks_nothing(tmp_path):
    program = load_p(tmp_path, S=MENU_Q)
    store = empty()
    interp = start_p(program, store)
    menu = menu_of(program)
    version = store.version
    interp.post(Choose(menu.sid, menu.choices[0].key))     # no menu waits yet
    assert store.version == version and not store.was_chosen(menu.sid, menu.choices[0].key)


# --- AC-F12-30 — file contents can't stop the game ------------------------------------------------

def read_into(store: PersistentStore, program, document: dict) -> None:
    data = json.dumps(document, separators=(",", ":")).encode("ascii")
    assert ReadJob(data, store, program).run().kind is Outcome.OK


def document(values=None, unlocks=None) -> dict:
    return {"format": 1, "identity_scheme": 1, "values": values or {}, "seen": {},
            "chosen": {}, "unlocks": unlocks or {}}


def group_e_program(root: Path):
    return load_p(root, S="$ persistent.flag = True", T="default persistent.score = 0")


def test_ac30_junk_names_give_way(tmp_path, caplog):
    program = group_e_program(tmp_path)
    store = empty()
    read_into(store, program, document({f"j{i}": i for i in range(PERSIST_MAX_NAMES)}))
    caplog.set_level(logging.WARNING, logger="vn.persist")
    commands = run_headless(program, seed=42, persistent=store)
    assert type(commands[-1]) is StoryEnded
    stored = values(store)
    assert {"festivals", "hana_remembers", "score", "flag"} <= set(stored)
    assert len(stored) <= PERSIST_MAX_NAMES
    assert any(r.code == "W54" for r in caplog.records)


def test_ac30_junk_bytes_give_way(tmp_path, caplog):
    program = group_e_program(tmp_path)
    store = empty()
    filler = PERSIST_MAX_BYTES - 10 - len('{"junk":""}')
    read_into(store, program, document({"junk": "x" * filler}))
    assert store.values_bytes == PERSIST_MAX_BYTES - 10
    caplog.set_level(logging.WARNING, logger="vn.persist")
    commands = run_headless(program, seed=42, persistent=store)
    assert type(commands[-1]) is StoryEnded and values(store)["flag"] is True
    assert any(r.code == "W54" for r in caplog.records)


def test_ac30_junk_kinds_and_names(tmp_path, caplog):
    program = group_e_program(tmp_path)
    store = empty()
    read_into(store, program, document(unlocks={f"k{i}": ["a"] for i in range(32)}))
    store.register_kind("cg")
    assert store.unlock("cg", "river_night")
    for known, expected in ((lambda n: n == "river_night", True), (None, False)):
        store = empty()
        read_into(store, program, document(unlocks={"cg": [f"n{i}" for i in range(10_000)]}))
        store.register_kind("cg", known=known)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="vn.persist"):
            assert store.unlock("cg", "river_night") is expected
        assert any(r.code == ("W54" if expected else "W57") for r in caplog.records)


# --- Milestone: the walkthrough on an in-memory store ---------------------------------------------

LANTERNS = FIXTURES / "lanterns" / "script"


def lanterns(root: Path):
    files = {p.name: p.read_text(encoding="utf-8") for p in LANTERNS.glob("*.vns")}
    return load_files(root, files)


def test_milestone_the_walkthrough(tmp_path):
    """Design §2: the sad ending, then a new game remembers it; lines read once are seen;
    loading a save from before the ending keeps the memory."""
    program = lanterns(tmp_path)
    store = empty()
    first = run_headless(program, seed=42, persistent=store, inputs=(
        "advance", "advance", "advance", "choose 1"))
    assert type(first[-1]) is StoryEnded
    assert "Have we... done this before?" not in texts(first)
    assert values(store) == {"festivals": 1, "hana_remembers": True}
    new_line = next(s for s in program.iter_statements()
                    if isinstance(s, SayNode) and s.text == "Have we... done this before?")
    read = [say_sid(program, t) for t in texts(first)]
    assert all(store.is_seen(sid) for sid in read) and not store.is_seen(new_line.sid)

    interp = start_p(program, store)                         # run 2: a new game
    advance(interp)
    advance(interp)
    assert interp.current.text == "Have we... done this before?"
    assert not store.is_seen(interp.current.sid)
    j = interp.checkpoint()                                  # at the bridge
    advance(interp)
    assert store.is_seen(new_line.sid) and values(store)["festivals"] == 2
    assert interp.restore(j).result is RestoreResult.OK      # an old save
    assert values(store)["hana_remembers"] is True


def test_milestone_lanterns_is_deterministic_on_one_store(tmp_path):
    program = lanterns(tmp_path)
    inputs = ("advance", "advance", "advance", "choose 2")
    a, b = empty(), empty()
    assert run_headless(program, seed=42, persistent=a, inputs=inputs) == \
        run_headless(program, seed=42, persistent=b, inputs=inputs)
    assert values(a) == values(b) == {"festivals": 1, "hana_remembers": False}


def test_headless_without_a_store_uses_an_empty_one(tmp_path):
    commands = run_headless(load_p(tmp_path, S="$ persistent.festivals += 1"), seed=42)
    assert texts(commands) == ["Start.", "End."]


def test_an_interpreter_with_another_store_than_its_namespace_is_refused(tmp_path):
    program = load_p(tmp_path)
    launch = run_launch(program, persistent=empty())
    with pytest.raises(ValueError):
        Interpreter(program, launch.namespace, persistent=empty())


def test_no_stored_value_reaches_error_texts(tmp_path):
    store = PersistentStore.with_data(values={"note": "ZZMARK", "nested": {"k": ["ZZMARK"]}})
    for i, S in enumerate(("$ x = persistent.nte", "$ persistent.v = {1}",
                           "$ persistent._ZZ = 1", '$ persistent.nested["k"].append({1})')):
        error = failure(run_p(tmp_path / str(i), store, S=S)[0])
        assert "ZZMARK" not in error.format() and "ZZMARK" not in "".join(error.trace)


@pytest.mark.parametrize("S, subject", [
    ('$ persistent.bag = {"key": [{1}]}', 'persistent.bag["key"][0]'),
    ('$ persistent.bag["key"].append({1})', 'persistent.bag["key"][1]'),
    ('$ persistent.bag[next(iter(persistent.bag))].append({1})', "persistent.bag[…][0]"),
    ("$ persistent.bag = {k + \"!\": [{1}] for k in persistent.bag}", "persistent.bag[…][0]"),
], ids=["literal", "literal-in-place", "file-key", "built-key"])
def test_sec09_e181_paths_show_only_dict_keys_written_in_the_script(tmp_path, S, subject):
    """SEC-F12-09 (decided at step 6): a dict key in an E181 path shows only when it is a
    literal of the failing line; a key from the player's file (or built from one) is
    ``[…]``, so a name a player typed never reaches the error screen or the log."""
    store = PersistentStore.with_data(values={"bag": {"ZZMARK": [], "key": [0]}})
    error = failure(run_p(tmp_path, store, S=S)[0])
    assert error.code == "E181"
    assert error.message.startswith(f"{subject} can't hold a set"), error.message
    assert "ZZMARK" not in error.format()


def test_ac47_the_example_game_twice_on_one_store():
    """AC-F12-47, the example game: run 1 on a fresh store matches the committed golden
    (``commands_example.json``, seed 1) and counts one festival; run 2 on the same store is
    the same story plus Hana's line on the bridge, and counts two. F21: run 2 also has the
    thought on the riverbank that the river god's tip (kept from run 1) shows, and no
    ``CodexAdded`` for the tips it already has (its items are new again)."""
    from tests.runtime import corpus

    program, images = corpus.example_program(), corpus.example_images()
    golden = json.loads((corpus.GOLDENS / "commands_example.json").read_text(encoding="utf-8"))
    store = empty()
    # F07: the golden's menu answers; the bridge's extra line comes after the talk menu.
    inputs = corpus.play(program, 1, images, corpus.EXAMPLE_PICKS[1]).inputs
    first = corpus.canon(run_headless(program, seed=1, image_files=images, persistent=store,
                                      inputs=inputs, minigames=corpus.example_minigames()))
    assert first == golden["seeds"]["1"]["commands"]
    assert store.peek("festivals") == 1
    # F19: the night's last menu comes after Hana's extra line, so one more advance before it.
    # F21: the riverbank's extra thought follows the 14th line ("Paper lanterns drifted…";
    # F25-4's map line is one before it), and every line before it is advanced.
    assert inputs[:14] == ["advance"] * 14
    second = corpus.canon(run_headless(program, seed=1, image_files=images, persistent=store,
                                       inputs=[*inputs[:14], "advance", *inputs[14:-1],
                                               "advance", inputs[-1]],
                                       minigames=corpus.example_minigames()))
    # The extra lines shift the look-ahead, so prefetch requests may differ; compare the rest.
    first = [c for c in first if c["type"] != "PrefetchImages"]
    second = [c for c in second if c["type"] != "PrefetchImages"]
    # F25-4: the cross-examination starts before the bridge talk, so its StartMinigame's
    # held tips differ (run 2 holds the river god's from run 1); compare the rest. F26-4:
    # the walk home ends with Hana's phone chat. F27-4: the shed's puzzle room comes first.
    # F23 s6: the lantern stall's lantern game comes before it.
    starts = [[c["name"] for c in run if c["type"] == "StartMinigame"] for run in (first, second)]
    assert starts[0] == starts[1] == ["lantern_memory", "puzzle_room", "present_evidence",
                                      "poem_game", "phone_chat"]
    first = [c for c in first if c["type"] != "StartMinigame"]
    second = [c for c in second if c["type"] != "StartMinigame"]
    tips = [c for c in first if c["type"] == "CodexAdded" and c["kind"] == "tip"]
    assert [c["name"] for c in tips] == ["lanterns", "river_god"]
    added = [c for c in second if c not in first]
    assert [(c["type"], c["text"]) for c in added] == [
        ("Say", "Somewhere under the footbridge, the river god was already counting wishes."),
        ("Say", "Funny. I feel like we've stood on this bridge before.")]
    assert [c for c in second if c not in added] == [c for c in first if c not in tips]
    assert store.peek("festivals") == 2
