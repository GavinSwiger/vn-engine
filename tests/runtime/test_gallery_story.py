"""F34 W2 — gallery pictures unlock when shown (``runtime/stage.py``'s three executors call
``gallery.seen``; ``Interpreter.__init__`` registers the kind): AC-F34-07 to 11.

Run R is ``run_headless(program, seed=42, persistent=store)``; Driver D is F19's ``drive``
(``RuntimeStoryDriver``, a fake clock). Skip mode has no runtime flag: it advances each line
and ends each wait at once, which is Driver D with ``wait_pumps=0``."""

import json

from engine.runtime import gallery
from engine.runtime.commands import ShowStage, StoryFailed
from engine.runtime.flowchart import FlowStates
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult
from engine.runtime.persistent import PersistentStore
from tests.runtime.conftest import round_trip
from tests.runtime.endings_story import drive, launched
from tests.runtime.flow_story import load_l
from tests.runtime.story import load_files

HEAD = ('define h = Character("Hana", image_tag="hana")\n'
        'lock gallery cg river "By the River":\n'
        '    cg river_smile\n'
        'lock gallery bg lanterns "Lanterns"\n'
        'lock gallery hana festive "Hana at the Festival"\n'
        'lock gallery cg storm "Storm"\n')

SHOWS = ('label start:\n'
         '    scene bg lanterns\n'
         '    "One."\n'
         '    show hana\n'
         '    h festive "Two."\n'
         '    h festive "Again."\n'
         '    show cg river_smile\n'
         '    "Three."\n')


def _load(root, body: str):
    return load_files(root, {"main.vns": HEAD + body})


def _store(program, *held: str) -> PersistentStore:
    if held:
        return PersistentStore.with_data(unlocks={"gallery": list(held)})
    return PersistentStore(identity_scheme=program.identity_scheme)


def _spy(store: PersistentStore, log: list) -> PersistentStore:
    """Log ``(op, name, result)`` for every ``"gallery"`` unlock and relock."""
    for op in ("unlock", "relock"):
        real = getattr(store, op)

        def call(kind, name, _real=real, _op=op, **kw):
            result = _real(kind, name, **kw)
            if kind == gallery.GALLERY_KIND:
                log.append((_op, name, result))
            return result
        setattr(store, op, call)
    return store


def _at(text: str, out: dict):
    """Driver D's ``on_line``: keep the checkpoint at the line ``text``."""
    def on_line(interp):
        if getattr(interp.current, "text", None) == text:
            out[text] = interp.checkpoint()
    return on_line


# --- AC-F34-07 — unlock on show ---------------------------------------------------------------

def test_ac07_scene_show_dialogue_look_and_version_unlock_the_same_everywhere(tmp_path):
    program = _load(tmp_path, SHOWS)
    expected = ("cg river_smile", "bg lanterns", "hana festive")       # gallery order
    log: list = []
    store = _spy(_store(program), log)
    drive(program, store, wait_pumps=0)                                 # skip mode
    assert gallery.unlocked(program, store) == expected
    # One call per stage change that names a gallery picture: the repeated look changes
    # nothing and calls nothing; ``show hana`` and the entry ``cg river`` stay out.
    assert log == [("unlock", "bg lanterns", True), ("unlock", "hana festive", True),
                   ("unlock", "cg river_smile", True)]
    clicked = _store(program)
    drive(program, clicked, wait_pumps=1)                               # clicking
    headless = _store(program)
    commands = run_headless(program, seed=42, persistent=headless)
    assert not any(type(c) is StoryFailed for c in commands)
    assert gallery.unlocked(program, clicked) == gallery.unlocked(program, headless) == expected


# --- AC-F34-08 — load, rollback landing, flowchart jump unlock nothing ------------------------

def test_ac08_load_rollback_and_flowchart_jump_unlock_nothing(tmp_path):
    program = load_l(tmp_path, HEAD + 'label start:\n'
                                      '    "Zero."\n'
                                      '    jump river\n'
                                      'label river:\n'
                                      '    flowchart scene "River"\n'
                                      '    show cg river_smile\n'
                                      '    "Three."\n'
                                      '    lock gallery cg river_smile\n'
                                      '    "Four."\n')
    # A load onto the CG (Template L's config.toml: the flowchart is on).
    saved: dict = {}
    drive(program, _store(program), on_line=_at("Three.", saved))
    state = round_trip(saved["Three."])
    assert any(s.image == "cg river_smile" for s in state.stage.sprites)
    log: list = []
    fresh = launched(program, _spy(_store(program), log))
    assert fresh.restore(state).result is RestoreResult.OK
    assert log == [] and fresh.persistent.unlocked("gallery") == ()

    # Rollback: back onto the CG (after ``lock gallery`` forgot it), then back before the
    # ``show`` and forward over it (F14's quiet re-run). Only the first live show unlocks.
    log.clear()
    store = _spy(_store(program), log)
    run_headless(program, seed=42, persistent=store, inputs=[
        "advance", "advance", "back 1", "advance", "back 2", "forward 1"])
    assert [entry for entry in log if entry[0] == "unlock"] == [
        ("unlock", "cg river_smile", True)]

    # A flowchart jump onto the CG (run 1's node state).
    holder = FlowStates()
    run_headless(program, seed=42, persistent=_store(program), flow=holder)
    log.clear()
    store = _spy(_store(program), log)
    commands = run_headless(program, seed=42, persistent=store, flow=holder,
                            inputs=["jump scene:river"])
    assert any(type(c) is ShowStage and any(s.image == "cg river_smile"
                                            for s in c.stage.sprites) for c in commands)
    assert [entry for entry in log if entry[0] == "unlock"] == []


# --- AC-F34-09 — unlocks outlive New Game and load; not in GameState --------------------------

def test_ac09_unlocks_survive_new_game_and_load_and_stay_out_of_game_state(tmp_path):
    program = _load(tmp_path, SHOWS)
    saved: dict = {}
    store = _store(program)
    interp, _ = drive(program, store, on_line=_at("One.", saved))
    held = gallery.unlocked(program, store)
    assert held == ("cg river_smile", "bg lanterns", "hana festive")
    interp.new_game(42)                                                 # New Game
    assert gallery.unlocked(program, store) == held
    assert interp.restore(round_trip(saved["One."])).result is RestoreResult.OK   # load
    assert gallery.unlocked(program, store) == held

    # The GameState JSON is the same whatever the store holds.
    other: dict = {}
    drive(program, _store(program, *held), on_line=_at("Three.", other))
    empty: dict = {}
    drive(program, _store(program), on_line=_at("Three.", empty))
    text = json.dumps(empty["Three."].to_json(), sort_keys=True)
    assert json.dumps(other["Three."].to_json(), sort_keys=True) == text

    # Showing again changes nothing.
    version = store.version
    store.take_new_unlocks()
    drive(program, store)
    assert store.version == version and store.take_new_unlocks() == ()


# --- AC-F34-10 — unlock gallery ----------------------------------------------------------------

def test_ac10_unlock_gallery_unlocks_without_showing(tmp_path):
    program = _load(tmp_path, 'label start:\n'
                              '    "One."\n'
                              '    unlock gallery cg storm\n'
                              '    "Two."\n')
    store = _store(program)
    commands = run_headless(program, seed=42, persistent=store)
    assert gallery.unlocked(program, store) == ("cg storm",)
    assert not any(type(c) is StoryFailed for c in commands)
    assert not any(type(c) is ShowStage and (c.stage.background == "cg storm" or any(
        s.image == "cg storm" for s in c.stage.sprites)) for c in commands)


# --- AC-F34-11 — lock gallery -----------------------------------------------------------------

def test_ac11_lock_gallery_forgets_and_a_locked_picture_is_left_alone(tmp_path):
    program = _load(tmp_path, 'label start:\n'
                              '    "One."\n'
                              '    lock gallery cg river\n'
                              '    lock gallery cg storm\n'
                              '    "Two."\n')
    log: list = []
    store = _spy(_store(program, "cg river", "bg lanterns"), log)
    commands = run_headless(program, seed=42, persistent=store)
    assert not any(type(c) is StoryFailed for c in commands)
    assert log == [("relock", "cg river", True), ("relock", "cg storm", False)]
    assert gallery.unlocked(program, store) == ("bg lanterns",)
