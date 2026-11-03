"""F34 P2: the F12 unlock kind ``"gallery"`` (``runtime/gallery.py``) against a stub program
and a real ``PersistentStore`` (AC-F34-12, 13), and F34 07 I-1: with ``cg`` no longer
reserved, a variable and a stage tag named ``cg`` save and load."""

from types import SimpleNamespace

from engine.persist.location import FILE_NAME
from engine.persist.sync import MEMORY, READ_ONLY
from engine.runtime import gallery
from engine.runtime.interpreter import RestoreResult
from engine.runtime.persistent import UNLOCK_NAMES_MAX, PersistentStore
from engine.script.gallery import GalleryEntry
from tests.persist.sync_support import Harness
from tests.persist.writer_support import base, game  # noqa: F401  (Harness Y's fixtures)
from tests.runtime.conftest import round_trip
from tests.runtime.endings_story import launched
from tests.runtime.menu_story import write_game

RIVER = GalleryEntry(picture="cg river", title="By the River", versions=("cg river_smile",),
                     sid="gallery:cg river", file="script/main.vns", line=1)
FESTIVAL = GalleryEntry(picture="cg festival", title="Festival Night", versions=(),
                        sid="gallery:cg festival", file="script/main.vns", line=3)
PROGRAM = SimpleNamespace(gallery=(RIVER, FESTIVAL), gallery_pictures={
    "cg river": "cg river", "cg river_smile": "cg river", "cg festival": "cg festival"})


def _interp(store: PersistentStore, *, replaying: bool = False) -> SimpleNamespace:
    """What ``runtime/gallery.py`` reads of an interpreter."""
    interp = SimpleNamespace(program=PROGRAM, persistent=store,
                             timeline=SimpleNamespace(replaying=replaying))
    gallery.register(interp)
    return interp


def test_ac12_unlocks_in_memory_and_hides_undeclared_names(game):  # noqa: F811
    memory = Harness(game / "memory", game=game, mode=MEMORY)
    folder = game / "readonly"
    folder.mkdir()
    newer = b'{"format":2}'
    (folder / FILE_NAME).write_bytes(newer)
    readonly = Harness(folder, game=game, mode=READ_ONLY)
    headless = PersistentStore(identity_scheme=1)
    for store, h in ((memory.store, memory), (readonly.store, readonly), (headless, None)):
        interp = _interp(store)
        assert gallery.seen(interp, "cg river_smile") is True
        assert gallery.seen(interp, "cg river_smile") is False          # shown again
        assert not gallery.seen(interp, "bg night") and not gallery.seen(interp, None)
        assert not gallery.seen(_interp(store, replaying=True), "cg festival")
        if h is not None:
            h.ticks(10.0)
        assert gallery.unlocked(PROGRAM, store) == ("cg river_smile",)
    assert not (game / "memory").exists()
    assert (folder / FILE_NAME).read_bytes() == newer and sorted(folder.iterdir()) == [
        folder / FILE_NAME]
    # A full kind read from file: names the script no longer declares stay hidden, and give
    # way to a declared picture.
    old = [f"cg old{i}" for i in range(UNLOCK_NAMES_MAX - 1)] + ["cg festival"]
    store = PersistentStore.with_data(unlocks={"gallery": old})
    interp = _interp(store)
    assert gallery.unlocked(PROGRAM, store) == ("cg festival",)
    assert gallery.seen(interp, "cg river") is True
    assert len(store.unlocked("gallery")) == UNLOCK_NAMES_MAX
    assert "cg old0" not in store.unlocked("gallery")
    assert gallery.unlocked(PROGRAM, store) == ("cg river", "cg festival")
    assert gallery.preview_names(PROGRAM) == ("cg river", "cg river_smile", "cg festival")


def test_ac13_delete_progress_clears_gallery_unlocks():
    store = PersistentStore(identity_scheme=1)
    interp = _interp(store)
    gallery.seen(interp, "cg river")
    gallery.seen(interp, "cg festival")
    assert store.relock("gallery", "cg festival")                        # lock gallery
    assert gallery.unlocked(PROGRAM, store) == ("cg river",)
    store.reset()                                                       # F16 Delete progress
    assert store.unlocked("gallery") == () and gallery.unlocked(PROGRAM, store) == ()
    assert gallery.seen(interp, "cg river") is True                     # still registered


def test_i1_a_variable_and_a_stage_tag_named_cg_save_and_load(tmp_path):
    from engine.script import load_story

    story = ("default cg = 1\nlabel start:\n    show cg festival\n    show hana as cg\n"
             '    $ cg += 1\n    "Here."\n    "There."\n')
    result = load_story(write_game(tmp_path / "g", story))
    assert result.errors == (), [e.format() for e in result.errors]
    interp = launched(result.program)
    interp.new_game(42)
    interp.run(10_000)
    state = interp.checkpoint()
    loaded = round_trip(state)
    assert loaded == state and loaded.variables["cg"] == 2
    assert "cg" in {sprite.tag for sprite in loaded.stage.sprites}
    fresh = launched(result.program)
    assert fresh.restore(loaded).result is RestoreResult.OK
    assert fresh.G["cg"] == 2
