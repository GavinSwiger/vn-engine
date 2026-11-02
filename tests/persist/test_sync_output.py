"""AC-F12-44 — output doesn't depend on the writer (TR-F12-07; invariant 7), F12 checklist
step 5.

Step 3a (the ``persistent`` namespace in the story, ``run_headless(persistent=)``, and the
interpreter's marks) isn't built yet, so this runs against the store API directly: the
example game plays headless through the interpreter while the driver does what step 3 will
do at each accepted line (reads the store, marks the line seen, changes a value now and
then), and the sync runs between lines as the App's frame slot will. Then:

- the command sequence is identical with no sync, with Harness Y unthreaded, and threaded,
  and equal to ``run_headless``'s;
- what the story would read from the store at each line is identical in all three, and
  identical for a store read from a file and the same store built with ``with_data``.

When step 3a lands, this test should switch to ``run_headless(program, seed=42,
persistent=store)`` and the ``tests/fixtures/F12/`` scripts."""

import pytest

from engine.persist.fileformat import Outcome, ReadJob, encode_bytes
from engine.persist.sync import MEMORY
from engine.runtime.commands import Advance, Choose, StoryEnded
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.script.menu import Menu
from tests.persist.sync_support import Harness
from tests.persist.writer_support import base, game, writers  # noqa: F401
from tests.runtime import corpus


SEED = 42


@pytest.fixture(scope="module")
def example():
    return corpus.example_program(), corpus.example_images()


def play(program, images, store: PersistentStore | None, harness: Harness | None):
    """The headless loop of ``run_headless`` plus step 3's store use at each line."""
    launch = run_launch(program, images=ImageSource.from_files(images))
    assert launch.namespace is not None
    interp = Interpreter(program, launch.namespace, minigames=corpus.example_minigames())
    interp.new_game(SEED)
    commands, reads = [], []
    now = 0.0
    lines = 0
    while True:
        if interp.status is Status.RUNNING:
            interp.run(10_000)
        commands.extend(interp.take_commands(1 << 62))
        if interp.status is Status.WAITING:
            if corpus.settle(interp):                   # F09/F18 waits, F24-4's poem: at once
                continue
            sid = interp.current.sid
            lines += 1
            if store is not None:
                reads.append((sid, store.is_seen(sid), store.peek("festivals"),
                              store.peek("endings"), store.unlocked("cg")))
                store.mark_seen(sid)                       # the Advance mark (step 3)
                if lines % 5 == 0:
                    store.set("festivals", lines)
                if lines % 9 == 0:
                    store.unlock("cg", f"line{lines}")
            if harness is not None:
                now += 0.4
                harness.tick(now)
            if type(interp.current) is Menu:                # F07: a menu, first choice
                interp.post(Choose(sid, interp.choices.waiting.pickable[0]))
            else:
                interp.post(Advance(sid))
        elif interp.status is not Status.RUNNING:
            break
    if harness is not None:
        harness.sync.close()
    return commands, reads


def _with_data() -> PersistentStore:
    return PersistentStore.with_data(values={"festivals": 2, "endings": ["sad"]},
                                     unlocks={"cg": ["river_night"]})


def _from_file() -> PersistentStore:
    data = encode_bytes(_with_data())
    store = PersistentStore(identity_scheme=1)
    assert ReadJob(data, store, None).run().kind is Outcome.OK
    store.register_kind("cg")
    return store


def test_ac44_commands_do_not_depend_on_the_writer(example, game, writers):
    program, images = example
    plain = run_headless(program, seed=SEED, image_files=images,
                         inputs=corpus.play(program, SEED, images).inputs,     # F07: menus
                         minigames=corpus.example_minigames())
    assert plain[-1] == StoryEnded()
    runs = {}
    runs["no sync"] = play(program, images, _with_data(), None)
    runs["memory sync"] = play(program, images, (s := _with_data()),
                               Harness(game / "m", game=game, store=s, mode=MEMORY))
    runs["unthreaded"] = play(program, images, (s := _with_data()),
                              Harness(game / "u" / "persistent", game=game, store=s))
    runs["threaded"] = play(program, images, (s := _with_data()),
                            Harness(game / "t" / "persistent", game=game, store=s,
                                    writer=writers(threaded=True)))
    for name, (commands, reads) in runs.items():
        assert commands == plain, name
        assert reads == runs["no sync"][1], name
    assert len(runs["no sync"][1]) > 20
    for folder in ("u", "t"):
        data = (game / folder / "persistent" / "persistent.json").read_bytes()
        again = PersistentStore(identity_scheme=1)
        assert ReadJob(data, again, None).run().kind is Outcome.OK
        assert again.is_seen(runs["no sync"][1][-1][0])


def test_ac44_a_store_read_from_a_file_reads_the_same_as_with_data(example):
    program, images = example
    built = play(program, images, _with_data(), None)
    read = play(program, images, _from_file(), None)
    assert read == built
