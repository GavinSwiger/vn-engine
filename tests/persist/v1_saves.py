"""The frozen version 1 saves (v1 review M7): how ``tests/fixtures/F11/v1/*.vnsave`` were made.

``tests/fixtures/F11/v1/game/`` is a small story that puts every part of a version 1 state in
a save: the story clock (moved and shown), a message waiting to arrive (``send … after``,
an armed trigger), held items with counts and the purse, an Inbox delivery the player
answered, shown meters, the hotbar, a checked choice's roll, and a variable. Played headless
with seed ``SEED`` (the first choice at the menu, the reply ``yes`` at "Hana wrote."), it is
saved at "Evening." (everything, the message still waiting) and at "Next morning." (the
message arrived) with ``SaveEncoder``'s fields below and no picture.

**These files are frozen.** Unlike ``golden/`` they are never regenerated: version 1 must load
them, unchanged, forever (``test_v1_golden_saves.py``). ``write`` refuses to replace one; a
later revision adds its own set beside them. Made once with::

    .venv/Scripts/python -m tests.persist.v1_saves
"""

from pathlib import Path

from engine.persist import saves
from engine.runtime.commands import Advance, Choose, WaitDone
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.send import ReplyMessage
from engine.runtime.state import GameState
from engine.script.menu import Menu
from engine.script.program import Program
from tests.runtime.effects_story import load_game

V1 = Path(__file__).resolve().parents[1] / "fixtures" / "F11" / "v1"
GAME = V1 / "game"
GAME_ID = "f11-v1"
SEED = 7
SAVED_AT = 1_793_567_040
REPLY_AT = "Hana wrote."
# file → (the line it is saved at, seq)
SAVES = {"evening.vnsave": ("Evening.", 1), "next_morning.vnsave": ("Next morning.", 2)}


def load_program() -> Program:
    return load_game(GAME)


def launched(program: Program) -> Interpreter:
    launch = run_launch(program)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace)


def line_text(interp: Interpreter) -> str:
    body = getattr(interp.current, "body", None)
    plain = body.plain() if body is not None else ()
    return "".join(span.text for span in plain)


def play(program: Program) -> dict[str, GameState]:
    """The story played headless: the checkpoint at each line it waits at, by its text."""
    interp = launched(program)
    interp.new_game(SEED)
    out: dict[str, GameState] = {}
    replied = False
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
        if type(current) is Menu:
            interp.post(Choose(current.sid, interp.choices.waiting.pickable[0]))
            continue
        text = line_text(interp)
        if text == REPLY_AT and not replied:
            (delivery,) = interp.codex.deliveries()
            interp.post(ReplyMessage(delivery.key, "yes"))
            replied = True
            continue
        out[text] = interp.checkpoint()
        interp.post(Advance(current.sid))


def save_bytes(state: GameState, seq: int) -> bytes:
    result = saves.encode_save(state, seq=seq, saved_at=SAVED_AT,
                               description=saves.describe(state, None), chapter=None,
                               game=GAME_ID, game_version="1.0", jpeg=None)
    assert not isinstance(result, saves.TooLarge), result
    return b"".join(result)


def write() -> None:
    """Make the saves that don't exist yet (the module docstring); never replace one."""
    states = play(load_program())
    for name, (line, seq) in SAVES.items():
        path = V1 / name
        if path.exists():
            print(f"kept {path} (frozen)")
            continue
        data = save_bytes(states[line], seq)
        path.write_bytes(data)
        print(f"wrote {path} ({len(data):,} bytes)")


if __name__ == "__main__":
    write()
