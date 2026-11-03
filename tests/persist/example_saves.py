"""The example game's test saves and the fixture patch (F11 ``06`` §5, AC-F11-66).

``tests/fixtures/F11/example_saves/`` holds five saves of ``game/`` as this build writes them:
the example played headless with seed 1 and the walkthrough's choices
(``corpus.EXAMPLE_PICKS[1]``), saved at the checkpoints in ``CHECKPOINTS`` (lines, two
menus, and three with a call on the stack), with the game's own fields (no ``[game] id``,
version ``0.1.0``) and a thumbnail of ``bg river_dusk``. ``tests/fixtures/F11/example_patch/
patch.toml`` is a typical update (lines, a ``default``, and a label added); ``patched_copy``
applies it to a copy of ``game/``.

When an edit to ``game/`` moves a saved line (the test names the save), regenerate the saves
with the one command::

    .venv/Scripts/python -m tests.persist.example_saves
"""

import shutil
import tomllib
from pathlib import Path

import pygame

from engine.persist import saves
from engine.render.thumbnail import encode_jpeg
from engine.runtime.commands import Advance, Choose
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.state import GameState
from engine.script.menu import Menu
from engine.script.program import Program
from tests.runtime import corpus
from tests.runtime.stage_story import EXAMPLE, load_game

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F11"
SAVES = FIXTURES / "example_saves"
PATCH = FIXTURES / "example_patch" / "patch.toml"
SEED = 1
PICKS = corpus.EXAMPLE_PICKS[SEED]
SAVED_AT = 1_793_567_040
VERSION = "0.1.0"
# Each save → the k-th checkpoint of the seed-1 walkthrough it is made at (F17 step 5:
# +7 for the prologue's full-screen lines, so each save stays at its line; F24-4: +2 for the
# release's wish line and its reaction, after the poem, which has no checkpoint here;
# F25-4: +1 for Hana's map line in the prologue, and +5 on the bridge for the line before
# the cross-examination and the four of its won branch; F27-4: +1 after the stall for the
# line before the shed's puzzle room, which has no checkpoint here; F31 s5: +6 after the
# prologue for the six lines of the bonus scene, script/bonus.vns, and +2 from the stall on
# for F23's two lantern_memory lines around the stall's minigame).
CHECKPOINTS = {
    "prologue.vnsave": 10,      # main.vns: "He said you'd get lost at least twice."
    "fortune.vnsave": 22,       # chapter1.vns, in the called draw_fortune: the slip is read
    "stall_menu.vnsave": 28,    # chapter1.vns: the nested "Red or white?" menu (called)
    "talk_menu.vnsave": 43,     # daichi.vns: the "Talk" menu, the second time (called)
    "release.vnsave": 51,       # daichi.vns, in the called lantern_release: "Make a wish."
}
IGNORE = shutil.ignore_patterns("logs", "saves", "persistent", "settings", "characters",
                                "__pycache__")


def walkthrough(program: Program) -> list[tuple[object, GameState]]:
    """The example played headless (seed 1, the walkthrough's choices): each checkpoint
    with the statement it waits at. Story waits and the poem end at once (``corpus.settle``)."""
    interp = corpus.launched(program, corpus.example_images())
    interp.new_game(SEED)
    interp.run(10_000)
    picks = iter(PICKS)
    out: list[tuple[object, GameState]] = []
    while interp.status is Status.WAITING:
        if corpus.settle(interp):
            continue
        current = interp.current
        out.append((current, interp.checkpoint()))
        if type(current) is Menu:
            interp.post(Choose(current.sid, interp.choices.waiting.pickable[next(picks, 1) - 1]))
        else:
            interp.post(Advance(current.sid))
        interp.run(10_000)
        interp.take_commands(1 << 30)
    return out


def thumbnail_jpeg() -> bytes:
    """``bg river_dusk`` scaled to 320×180, through the engine's encoder."""
    picture = pygame.image.load(str(EXAMPLE / "images" / "bg" / "river_dusk.png"))
    jpeg = encode_jpeg(pygame.transform.smoothscale(picture, (320, 180)))
    assert jpeg is not None
    return jpeg


def save_bytes(state: GameState, seq: int, jpeg: bytes | None) -> bytes:
    result = saves.encode_save(state, seq=seq, saved_at=SAVED_AT,
                               description=saves.describe(state, None), chapter=None,
                               game=None, game_version=VERSION, jpeg=jpeg)
    assert not isinstance(result, saves.TooLarge), result
    return b"".join(result)


def example_bytes() -> dict[str, bytes]:
    """The five saves as this build makes them from ``game/``."""
    played = walkthrough(load_game(EXAMPLE))
    jpeg = thumbnail_jpeg()
    return {name: save_bytes(played[k][1], seq, jpeg)
            for seq, (name, k) in enumerate(CHECKPOINTS.items(), 1)}


def write_saves() -> None:
    """Regenerate ``tests/fixtures/F11/example_saves/`` (the module docstring's command)."""
    SAVES.mkdir(parents=True, exist_ok=True)
    for name, data in example_bytes().items():
        (SAVES / name).write_bytes(data)
        print(f"wrote {SAVES / name} ({len(data):,} bytes)")


def read_saves() -> dict[str, GameState]:
    """The committed saves, each read by the one parser (``parse_full``)."""
    out = {}
    for name in CHECKPOINTS:
        read = saves.parse_full((SAVES / name).read_bytes(), game_id=None)
        assert read.status is saves.SlotStatus.OK and read.state is not None, (name, read.reason)
        out[name] = read.state
    return out


def patched_copy(dest: Path) -> Path:
    """A copy of ``game/`` (without run folders) with ``patch.toml`` applied."""
    root = Path(shutil.copytree(EXAMPLE, dest, ignore=IGNORE))
    patch = tomllib.loads(PATCH.read_text(encoding="utf-8"))
    for edit in patch["insert"]:
        path = root / edit["file"]
        lines = path.read_text(encoding="utf-8").split("\n")
        at = [i for i, line in enumerate(lines) if line == edit["after"]]
        assert len(at) == 1, (edit["file"], edit["after"], len(at))
        lines[at[0] + 1:at[0] + 1] = edit["lines"]
        path.write_bytes("\n".join(lines).encode("utf-8"))
    for edit in patch["append"]:
        path = root / edit["file"]
        text = path.read_text(encoding="utf-8")
        path.write_bytes((text + "\n".join(edit["lines"]) + "\n").encode("utf-8"))
    return root


def fresh(program: Program) -> Interpreter:
    """A fresh launch of ``program`` in a new game, ready for ``restore``."""
    interp = corpus.launched(program, corpus.example_images())
    interp.new_game(SEED)
    interp.run(10_000)
    interp.take_commands(1 << 30)
    return interp


if __name__ == "__main__":
    write_saves()
