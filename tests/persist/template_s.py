"""Template S in full (F11 ``06`` §0.4) and the golden saves made from it (AC-F11-37).

``tests/fixtures/F11/template/`` holds Template S's ``config.toml`` and ``script/main.vns``;
``make_game`` copies them into a test folder and adds its art and music, generated at run
time (``bg room`` solid (200, 200, 200), ``bg street`` solid (0, 80, 240), ``bgm/theme.ogg``
2 s of silence), so no binary asset is committed. F04, F07, F08, and F09 are built, so the
template no longer needs the reduced form (I-14 A8) for the rows that use it.

``tests/fixtures/F11/golden/`` holds three format-1 saves (P6, P-menu, P18) as this build
writes them: Template S played headless with seed 42 (choice 1 at the menu), encoded by
``SaveEncoder`` with ``seq`` 1–3, ``saved_at`` 1,793,567,040, game ``f11-template``,
version ``1.0``, and a flat ``bg room`` thumbnail. ``tests/persist/test_golden_saves.py``
checks they are this build's and that each loads at its line. Regenerate them (when a
feature adds or changes a ``GameState`` key, e.g. F14 ``rollback``, F18 ``chapter``, F22
``points``) with the one command::

    .venv/Scripts/python -m tests.persist.template_s
"""

import shutil
from pathlib import Path

import pygame

from engine.persist import saves
from engine.render.thumbnail import encode_jpeg
from engine.runtime.commands import Advance, Choose, WaitDone
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from engine.script.menu import Menu
from engine.script.program import Program
from tests.persist import save_support as ss
from tests.runtime.menu_story import load_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F11"
TEMPLATE = FIXTURES / "template"
GOLDEN = FIXTURES / "golden"
SEED = 42
ROOM = (200, 200, 200)
STREET = (0, 80, 240)
IMAGES = {"images/bg/room.png": ROOM, "images/bg/street.png": STREET}
MUSIC = "audio/bgm/theme.ogg"

LINE6 = "Hey, have you ever written a poem? I wrote one about paper lanterns last night."
LINE8 = "The wind picks up."
LINE18 = "End of the day."
# name → (the line it waits at, seq)
GOLDEN_SAVES = {"p6.vnsave": (6, 1), "menu.vnsave": (9, 2), "p18.vnsave": (18, 3)}


def script_text() -> str:
    return (TEMPLATE / "script" / "main.vns").read_text(encoding="utf-8")


def make_game(root: Path, config: str = "", *, title: bool = True,
              script: str | None = None) -> Path:
    """Template S in ``root`` (created): its config plus ``config`` (``autosave_quit`` is
    false unless ``config`` sets it, as in ``test_saves_service.make_game``), ``[title]
    enabled = false`` unless ``title``, the script (or ``script``: a patched copy), the
    two backgrounds, and the music."""
    from tests.fakes.fake_mixer import ogg_bytes
    from tests.fixtures.F04 import gen_images as gen

    (root / "script").mkdir(parents=True)
    text = (TEMPLATE / "config.toml").read_text(encoding="utf-8")
    if not title:
        text += "\n[title]\nenabled = false\n"
    text += config
    if "autosave_quit" not in text:
        text = (text.replace("[saves]\n", "[saves]\nautosave_quit = false\n", 1)
                if "[saves]\n" in text else text + "\n[saves]\nautosave_quit = false\n")
    (root / "config.toml").write_text(text, encoding="utf-8")
    if script is None:
        shutil.copyfile(TEMPLATE / "script" / "main.vns", root / "script" / "main.vns")
    else:
        (root / "script" / "main.vns").write_text(script, encoding="utf-8")
    gen.write(root, {ref: gen.block(1280, 720, color) for ref, color in IMAGES.items()})
    music = root / MUSIC
    music.parent.mkdir(parents=True)
    music.write_bytes(ogg_bytes(2.0, salt=b"theme"))
    return root


def load_program(root: Path, text: str | None = None) -> Program:
    """Template S (or ``text``) loaded headless from a folder under ``root``."""
    result = load_text(root, script_text() if text is None else text)
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def launched(program: Program) -> Interpreter:
    launch = run_launch(program, images=ImageSource.from_files(IMAGES))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace)


def checkpoints(program: Program, *, choice: int = 1) -> dict[int, GameState]:
    """Template S played headless (seed 42): the checkpoint at each line or menu it waits
    at, by line. Waits that aren't checkpoints (the fade) end at once."""
    interp = launched(program)
    interp.new_game(SEED)
    out: dict[int, GameState] = {}
    while True:
        if interp.status is Status.RUNNING:
            interp.run(10_000)
        interp.take_commands(1 << 30)
        if interp.status is not Status.WAITING:
            return out
        if interp.waiting_for is not None:
            interp.post(WaitDone(interp.waiting_for))
            continue
        current = interp.current
        state = interp.checkpoint()
        assert current is not None and state is not None
        out[current.line] = state
        if type(current) is Menu:
            interp.post(Choose(current.sid, interp.choices.waiting.pickable[choice - 1]))
        else:
            interp.post(Advance(current.sid))


def thumbnail_jpeg() -> bytes:
    """A flat ``bg room`` 320×180 picture, through the engine's encoder."""
    surface = pygame.Surface((320, 180))
    surface.fill(ROOM)
    jpeg = encode_jpeg(surface)
    assert jpeg is not None
    return jpeg


def save_bytes(state: GameState, seq: int, jpeg: bytes | None) -> bytes:
    """A save file of ``state`` as this build writes it (the golden saves' fields)."""
    result = saves.encode_save(state, seq=seq, saved_at=ss.SAVED_AT,
                               description=saves.describe(state, None), chapter=None,
                               game=ss.GAME_ID, game_version="1.0", jpeg=jpeg)
    assert not isinstance(result, saves.TooLarge), result
    return b"".join(result)


def golden_bytes(root: Path) -> dict[str, bytes]:
    """The golden saves as this build makes them (``root``: a scratch folder)."""
    states = checkpoints(load_program(root))
    jpeg = thumbnail_jpeg()
    return {name: save_bytes(states[line], seq, jpeg)
            for name, (line, seq) in GOLDEN_SAVES.items()}


def write_golden() -> None:
    """Regenerate ``tests/fixtures/F11/golden/`` (the module docstring's command)."""
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        made = golden_bytes(Path(scratch) / "game")
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, data in made.items():
        (GOLDEN / name).write_bytes(data)
        print(f"wrote {GOLDEN / name} ({len(data):,} bytes)")


if __name__ == "__main__":
    write_golden()
