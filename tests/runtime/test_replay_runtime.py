"""F36 W2: scene replays in the interpreter (``runtime/replay.py``, ``Interpreter.new_game(seed,
replay=)``, the end rules in ``_enter``/``_return``, ``_end``, ``_fail``, ``stop_replay``),
F31/F32's skipped lines (W229), F20 and F34 switched off, and ``run_headless(replay=)``:
AC-F36-07, 08, 09, 16, 17, 18, 22, 23, 25.

Story P (``MAIN``) is a small *Paper Lanterns*: ``festival`` calls ``helper`` (which jumps on
to ``helper_two`` and returns), then jumps to ``stall``; a choice there jumps to ``river``,
which jumps to ``walk``, which jumps (or, with more than 5 coins, calls) ``fireworks``.
"Unchanged" for the store is its whole file form (``encode_bytes``) plus not in the sandbox."""

import logging

import pytest

from engine.core.startvalues import StartOptions
from engine.persist.fileformat import decode, encode_bytes, parse
from engine.persist.sync import MEMORY, READ_ONLY
from engine.runtime import replay as replay_mod
from engine.runtime.commands import (DeleteSaves, MetaDelete, MetaWrite, Say, ShowStage,
                                     StoryEnded, StoryFailed)
from engine.runtime.flowchart import FlowStates
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.metafiles import MetaFiles, attach
from engine.runtime.persistent import PersistentStore
from engine.runtime.replay import REPLAY_KIND, ReplayRun
from engine.script.messages import format_message
from tests.persist.sync_support import Harness
from tests.persist.writer_support import base, game  # noqa: F401  (Harness Y's fixtures)
from tests.runtime import metafiles_story
from tests.runtime.endings_story import drive, launched
from tests.runtime.flow_story import load_l
from tests.runtime.rollback_story import back, forward, shown_text, step
from tests.runtime.story import load_files
from tests.script.message_cases import load_cases

MAIN = '''define hana = Character("Hana")
default coins = 0
default name = "nobody"
lock replay start "Start"
lock replay festival "The Festival"
lock replay helper "Helper"
lock replay river "By the River" to fireworks:
    coins = 3
    name = "Aiko"
lock replay loop "Loop"
label start:
    "Start."
    jump festival
label festival:
    "Festival one."
    call helper
    "Festival two."
    jump stall
label helper:
    "Helper one."
    jump helper_two
label helper_two:
    "Helper two."
    return
label stall:
    "Stall."
    menu:
        "To the river":
            jump river
        "Stay":
            "Stayed."
    "After."
label river:
    "River {var=coins} {var=name}."
    jump walk
label walk:
    "Walk."
    if coins > 5:
        call fireworks
    jump fireworks
label fireworks:
    "Fireworks."
label loop:
    "Loop {var=coins}."
    $ coins += 1
    if coins < 3:
        jump loop
    "Loop done."
label boom:
    $ persistent.hits = 1
    "Boom."
    $ coins = 1 / 0
label keys:
    unlock replay loop
    lock replay festival
    "Keys."
'''

FULL = ["Start.", "Festival one.", "Helper one.", "Helper two.", "Festival two.", "Stall.",
        "River 0 nobody.", "Walk.", "Fireworks."]


@pytest.fixture
def program(tmp_path):
    return load_files(tmp_path, {"main.vns": MAIN})


def texts(commands) -> list[str]:
    """The lines shown, as shown (``{var=}`` filled in)."""
    return ["".join(p.text for p in c.body.pieces) for c in commands if type(c) is Say]


def _store(program, **kinds) -> PersistentStore:
    store = PersistentStore(identity_scheme=program.identity_scheme)
    if kinds:
        store = PersistentStore.with_data(unlocks={k: list(v) for k, v in kinds.items()})
    return store


def _image(store: PersistentStore) -> dict:
    """The store's whole content, as the file would hold it."""
    return parse(decode(encode_bytes(store)))


def _ready(program, store: PersistentStore) -> PersistentStore:
    """``store`` as a launch leaves it (kinds registered, built-in values set), so its image
    is the one a replay starts from."""
    launched(program, store)
    return store


def _seeded(program) -> PersistentStore:
    """A launched store with progress: a value, a seen line, two unlocked replays."""
    store = _store(program, replay=["festival", "loop"])
    store.set("x", 1)
    store.mark_seen(program.labels["start"].block[0].sid)
    return _ready(program, store)


def _replay(program, store, label, *, inputs=(), dev=False, **kw):
    return run_headless(program, seed=42, persistent=store, replay=label, inputs=inputs,
                        dev=dev, **kw)


def _started(program, store, run: ReplayRun, **kw):
    interp = launched(program, store, **kw)
    interp.new_game(42, replay=run)
    interp.run(10_000)
    return interp


# --- AC-F36-07 — unlock on arrival ------------------------------------------------------------

def test_ac07_arrival_unlocks_by_jump_call_choice_and_new_game_only(program):
    expected = ("start", "festival", "helper", "river")      # new game, jump, call, choice
    store = _store(program)
    commands = run_headless(program, seed=42, persistent=store, inputs=["advance"] * 6 +
                            ["choose 1"])
    assert texts(commands) == FULL and type(commands[-1]) is StoryEnded
    assert store.unlocked(REPLAY_KIND) == expected           # walk and loop: not reached
    window = _store(program)
    drive(program, window, choices=(1,))                     # the window's driver: the same
    assert window.unlocked(REPLAY_KIND) == expected

    # A load (restore in a fresh interpreter on an empty store), a flowchart jump (restore
    # with fresh_menu), and a rollback landing (back, then forward across ``jump festival``)
    # unlock nothing.
    interp = launched(program, _store(program))
    interp.new_game(42)
    interp.run(10_000)
    step(interp)
    at_festival = interp.checkpoint()
    assert shown_text(interp) == "Festival one."
    for fresh in (False, True):
        other = launched(program, _store(program))
        assert other.restore(at_festival, fresh_menu=fresh).result is RestoreResult.OK
        assert other.persistent.unlocked(REPLAY_KIND) == ()
    assert interp.persistent.relock(REPLAY_KIND, "festival")
    back(interp)
    assert shown_text(interp) == "Start."
    forward(interp)
    assert shown_text(interp) == "Festival one."
    assert interp.persistent.unlocked(REPLAY_KIND) == ("start",)
    step(interp)                                             # a live call still unlocks
    assert interp.persistent.unlocked(REPLAY_KIND) == ("start", "helper")
    # A replay unlocks nothing it reaches (and is put back anyway).
    store = _store(program)
    _replay(program, store, ReplayRun("start", "loop"), inputs=["advance"] * 6 + ["choose 1"])
    assert store.unlocked(REPLAY_KIND) == () and not store.in_sandbox


# --- AC-F36-08 — unlock replay / lock replay lines ----------------------------------------------

def test_ac08_unlock_and_lock_replay_lines(program):
    store = _store(program, replay=["festival", "start"])
    commands = run_headless(program, seed=42, persistent=store,
                            start=StartOptions("keys"))
    assert texts(commands) == ["Keys."] and type(commands[-1]) is StoryEnded
    assert store.unlocked(REPLAY_KIND) == ("start", "loop")   # festival taken back
    run_headless(program, seed=42, persistent=store, start=StartOptions("keys"))
    assert store.unlocked(REPLAY_KIND) == ("start", "loop")   # again: nothing changes


# --- AC-F36-09 — the kind ---------------------------------------------------------------------

def test_ac09_kind_is_revocable_lasts_and_delete_progress_clears_it(program, game):  # noqa: F811
    store = _store(program)
    interp = launched(program, store)
    assert store.is_revocable(REPLAY_KIND)
    assert interp.replays.has("river") and not interp.replays.has("walk")
    assert replay_mod.run_for(program, "river") == ReplayRun("river", "fireworks",
                                                             (("coins", 3), ("name", "Aiko")))
    assert replay_mod.run_for(program, "walk") == ReplayRun("walk")
    interp.new_game(42)
    interp.run(10_000)
    step(interp)
    state = interp.checkpoint()
    assert store.unlocked(REPLAY_KIND) == ("start", "festival")
    interp.new_game(43)                                      # New Game keeps them
    interp.run(10_000)
    assert store.unlocked(REPLAY_KIND) == ("start", "festival")
    assert interp.restore(state).result is RestoreResult.OK  # so does a load
    assert store.unlocked(REPLAY_KIND) == ("start", "festival")
    store.reset()                                            # F16 Delete progress
    assert store.unlocked(REPLAY_KIND) == ()
    launched(program, store)                                 # registering again is safe
    # MEMORY and READ_ONLY stores unlock in memory and write nothing.
    memory = Harness(game / "memory", game=game, mode=MEMORY)
    folder = game / "readonly"
    folder.mkdir()
    readonly = Harness(folder, game=game, mode=READ_ONLY)
    for h in (memory, readonly):
        run_headless(program, seed=42, persistent=h.store)
        h.ticks(10.0)
        assert h.store.unlocked(REPLAY_KIND) == ("start", "festival", "helper")
    assert not (game / "memory").exists() and list(folder.iterdir()) == []


# --- AC-F36-16 — the end without ``to`` ----------------------------------------------------------

@pytest.mark.parametrize("label, lines", [
    # call and return, a jump inside the call go on; a jump elsewhere at its own depth ends
    ("festival", ["Festival one.", "Helper one.", "Helper two.", "Festival two."]),
    ("helper_two", ["Helper two."]),                         # ``return`` ends
    ("fireworks", ["Fireworks."]),                           # the lines end (story end)
    ("loop", ["Loop 0.", "Loop 1.", "Loop 2.", "Loop done."]),   # a jump to itself goes on
])
def test_ac16_a_replay_without_to_ends_when_the_story_leaves_the_scene(program, label, lines):
    store = _seeded(program)
    before = _image(store)
    commands = _replay(program, store, label)
    assert texts(commands) == lines and type(commands[-1]) is StoryEnded
    assert sum(type(c) is StoryEnded for c in commands) == 1
    assert not store.in_sandbox and _image(store) == before


def test_ac16_quit_error_and_end_replay_mid_replay_put_the_store_back(program):
    # Quit mid-replay: the run stops at the menu (inputs out); the store is put back.
    store = _seeded(program)
    before = _image(store)
    commands = _replay(program, store, ReplayRun("start", "loop"), inputs=["advance"] * 5)
    assert texts(commands)[-1] == "Stall." and type(commands[-1]) is not StoryEnded
    assert not store.in_sandbox and _image(store) == before
    # An error mid-replay: F10's error path (StoryFailed alone), the store put back before.
    store = _seeded(program)
    commands = _replay(program, store, "boom")
    assert texts(commands) == ["Boom."] and type(commands[-1]) is StoryFailed
    assert not store.in_sandbox and _image(store) == before
    # End Replay: ``stop_replay`` mid-scene; nothing released, ENDED, the store put back.
    store = _seeded(program)
    interp = _started(program, store, replay_mod.run_for(program, "festival"))
    store.set("x", 99)
    store.unlock(REPLAY_KIND, "walk")
    assert store.in_sandbox and interp.replay is not None
    interp.stop_replay()
    assert interp.status is Status.ENDED and interp.current is None and interp.released == 0
    assert interp.replay is None and not store.in_sandbox and _image(store) == before
    # 07 I-10: ``leave``/``stop_replay`` close a sandbox even with no replay running.
    store.begin_sandbox()
    store.set("x", 5)
    interp.stop_replay()
    assert not store.in_sandbox and store.get("x") == 1
    # A new game after a replay plays normally (and a new replay starts clean).
    interp.new_game(42)
    interp.run(10_000)
    assert interp.replay is None and shown_text(interp) == "Start."
    assert "start" in store.unlocked(REPLAY_KIND)


# --- AC-F36-17 — the end with ``to`` and the starting values -------------------------------------

def test_ac17_a_replay_with_to_ends_on_reaching_it_by_jump_or_call(program):
    store = _seeded(program)
    before = _image(store)
    # river's declared replay: starting values after the defaults, jumps to walk go on, the
    # jump to fireworks ends it before "Fireworks.".
    commands = _replay(program, store, "river")
    assert texts(commands) == ["River 3 Aiko.", "Walk."] and type(commands[-1]) is StoryEnded
    assert not store.in_sandbox and _image(store) == before
    # Reached by a call (more than 5 coins): ends there too.
    commands = _replay(program, store, ReplayRun("river", "fireworks", (("coins", 9),)))
    assert texts(commands) == ["River 9 nobody.", "Walk."] and type(commands[-1]) is StoryEnded
    # A ``to`` never reached: the replay ends at the story's end.
    commands = _replay(program, store, ReplayRun("festival", "loop"),
                       inputs=["advance"] * 5 + ["choose 1"])
    assert texts(commands) == FULL[1:] and type(commands[-1]) is StoryEnded
    assert not store.in_sandbox and _image(store) == before


# --- AC-F36-18 — an ending in a replay -------------------------------------------------------------

def test_ac18_an_ending_in_a_replay_shows_its_card_records_nothing_then_ends(tmp_path):
    program = load_l(tmp_path, _template_l('lock replay river "By the River"'))
    store = _ready(program, _store(program, ending=["good"]))
    before = _image(store)
    commands = _replay(program, store, "river")
    cards = [(c.card.kind, c.card.name) for c in commands
             if type(c) is ShowStage and c.card is not None]
    assert cards == [("chapter", "river"), ("ending", "sad")]
    assert texts(commands) == ["The water is dark."] and type(commands[-1]) is StoryEnded
    assert store.unlocked("ending") == ("good",) and not store.in_sandbox
    assert _image(store) == before
    # The same scene in a normal game records the ending.
    plain = _store(program)
    run_headless(program, seed=42, persistent=plain, start=StartOptions("river"))
    assert plain.unlocked("ending") == ("sad",)


# --- AC-F36-22 — file write/delete and ui delete saves skipped (W229) ----------------------------

def _w229(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W229"]


def test_ac22_meta_writes_deletes_and_save_wipes_are_skipped_with_w229(tmp_path, caplog):
    rows = {c.id.removeprefix("F36-22-"): c for c in load_cases() if c.code == "W229"}
    assert set(rows) == {"W229-write", "W229-delete", "W229-saves"}
    for form in ("write", "delete", "saves"):
        args = (form,) if form == "saves" else (form, "hana.chr")
        assert format_message("W229", args) == rows[f"W229-{form}"].expect["exact"]

    walk = metafiles_story.fixture("walk")
    folder = metafiles_story.spy(entries={"hana.chr": b"x", "read_me.txt": b"hello"},
                                 originals={"hana.chr": metafiles_story.HANA})
    entries = dict(folder.entries)
    interp = launched(walk, dev=True)
    attach(interp, MetaFiles(folder))
    caplog.set_level(logging.INFO)
    for _ in range(2):                                       # two replays, one session
        interp.new_game(42, replay=ReplayRun("start"))
        interp.run(10_000)
        while interp.status is Status.WAITING:
            step(interp)
        assert interp.status is Status.ENDED and not interp.persistent.in_sandbox
    commands = interp.take_commands(1 << 30)
    assert not [c for c in commands if type(c) in (MetaWrite, MetaDelete)]
    assert folder.entries == entries and interp.files.changes == 0
    assert {verb for verb, _ in folder.calls} == {"exists", "read"}    # read and exists work
    shown = texts(commands)
    assert "W2 hello" in shown and "W5 back" in shown and len(shown) == 12
    ref = "script/main.vns"
    assert _w229(caplog) == [
        f"{ref}, line {n}: " + format_message("W229", (verb, name))
        for n, verb, name in ((6, "write", "hana.chr"), (7, "write", "read_me.txt"),
                              (13, "delete", "hana.chr"), (14, "delete", "gone.chr"))]
    assert not interp.timeline.block_pending

    # ``ui delete saves``: nothing held in a replay (W229 once), held in a normal game; a
    # release run skips it without a word.
    wipe = load_files(tmp_path / "wipe", {"main.vns": (
        'lock replay start "Start"\nlabel start:\n    "One."\n    ui delete saves\n'
        '    "Two."\n')})
    caplog.clear()
    for dev in (True, False):
        commands = _replay(wipe, _store(wipe), "start", dev=dev)
        assert texts(commands) == ["One.", "Two."] and DeleteSaves() not in commands
    assert _w229(caplog) == [f"{ref}, line 4: " + format_message("W229", ("saves",))]
    assert DeleteSaves() in run_headless(wipe, seed=42)


# --- AC-F36-23 — F20 records nothing in a replay ---------------------------------------------------

def test_ac23_a_replay_records_no_arrival_node_state_or_edge(tmp_path):
    program = load_l(tmp_path, _template_l('lock replay stall "The Stall"\n'
                                           'label forgetful:\n'
                                           '    flowchart forget\n'
                                           '    "Forgot."'))
    store = _store(program)
    holder = FlowStates()
    run_headless(program, seed=42, persistent=store, flow=holder,
                 inputs=["advance"] * 3 + ["choose 1", "advance", "choose 1"])
    reached, taken, states = list(holder.reached), list(holder.taken), dict(holder)
    assert reached and states                                # a normal game records
    before = _image(store)
    for label, inputs in (("stall", ["advance", "choose 1", "advance", "choose 1"]),
                          ("forgetful", [])):
        commands = _replay(program, store, label, inputs=inputs, flow=holder)
        assert type(commands[-1]) is StoryEnded
        assert holder.reached == reached and holder.taken == taken and dict(holder) == states
        assert _image(store) == before
    # Run in the interpreter too: nothing pending at any step of a replay.
    interp = launched(program, store)
    interp.new_game(42, replay=ReplayRun("stall"))
    interp.run(10_000)
    while interp.status is Status.WAITING:
        assert interp.flow_pending == [] and interp.flow.path == ()
        step(interp)
    assert not store.in_sandbox and _image(store) == before


def _template_l(extra: str) -> str:
    from tests.script.helpers import F20_TEMPLATE_DIR
    main = (F20_TEMPLATE_DIR / "script" / "main.vns").read_text(encoding="utf-8")
    return main.rstrip("\n") + "\n" + extra + "\n"


# --- AC-F36-25 — rollback, skip, auto and history in a replay -------------------------------------

def test_ac25_rollback_works_inside_a_replay_and_stops_at_its_first_line(program):
    store = _seeded(program)
    before = _image(store)
    interp = _started(program, store, replay_mod.run_for(program, "festival"))
    shown = [shown_text(interp)]
    for _ in range(2):                                       # skip and auto post Advance too
        step(interp)
        shown.append(shown_text(interp))
    assert shown == ["Festival one.", "Helper one.", "Helper two."]
    back(interp, 9)                                          # stops at the replay's first line
    assert shown_text(interp) == "Festival one." and interp.replay is not None
    assert store.in_sandbox
    back(interp)
    assert shown_text(interp) == "Festival one."
    forward(interp, 2)                                       # a quiet re-run inside the call
    assert shown_text(interp) == "Helper two." and interp.replay is not None
    assert [e.text for e in interp.history.entries] == shown   # history: the replay's only
    back(interp)
    assert shown_text(interp) == "Helper one." and interp.call_stack
    step(interp)
    step(interp)                                             # Festival two.
    assert shown_text(interp) == "Festival two."
    step(interp)                                             # jump stall: the end
    assert interp.status is Status.ENDED and interp.replay is None
    assert not store.in_sandbox and _image(store) == before
    # Headless back/forward inputs in a replay.
    commands = _replay(program, store, "festival",
                       inputs=["advance", "back 5", "advance", "advance", "forward"])
    assert texts(commands)[:3] == ["Festival one.", "Helper one.", "Festival one."]
    assert type(commands[-1]) is StoryEnded and _image(store) == before


# --- PR-F36-07 / SR-F36-02 — a replay's missing picture is F04's launch warning ----------------

def test_a_replay_image_with_no_picture_gives_w12_at_its_declaration(tmp_path):
    from engine.runtime.images import ImageSource
    from engine.runtime.launch import run_launch

    story = MAIN.replace('lock replay loop "Loop"', 'lock replay loop "Loop" image cg lops')
    program = load_files(tmp_path, {"main.vns": story})
    files = ("images/cg/loops.png",)
    launch = run_launch(program, dev=True, images=ImageSource.from_files(files))
    w12 = [w for w in launch.warnings if w.code == "W12"]
    assert [(w.file, w.line) for w in w12] == [("script/main.vns", 10)]
    assert "cg lops" in w12[0].message and "cg loops" in w12[0].message   # did you mean
    clean = load_files(tmp_path / "ok", {"main.vns": story.replace("cg lops", "cg loops")})
    launch = run_launch(clean, dev=True, images=ImageSource.from_files(files))
    assert not [w for w in launch.warnings if w.code == "W12"]


# --- PR-F36-13 — F34: a picture shown in a replay unlocks nothing, even before the put-back ---

def test_a_gallery_picture_shown_in_a_replay_unlocks_nothing(tmp_path):
    from engine.runtime import gallery

    program = load_files(tmp_path, {"main.vns": (
        'lock gallery bg lanterns "Lanterns"\nlabel start:\n    scene bg lanterns\n'
        '    "One."\n')})
    store = _store(program)
    interp = _started(program, store, ReplayRun("start"))
    assert store.in_sandbox and gallery.unlocked(program, store) == ()
    interp.new_game(42)                                      # ends the replay; a normal game
    interp.run(10_000)
    assert not store.in_sandbox and gallery.unlocked(program, store) == ("bg lanterns",)
