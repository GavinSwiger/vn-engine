"""AC-F11-37 — the golden saves (F11 SPEC step 11; ``06`` §5 ``golden/``).

``tests/fixtures/F11/golden/`` holds Template S's saves at P6, P-menu, and P18 as this build
writes them (``tests/persist/template_s.py`` says how they are made). The test proves
they are this build's: each committed file reads OK, and its meta (but the two line
lengths) and its state equal what this build makes now; line 2 is a JPEG the engine's
reader accepts (its bytes may differ by platform). Then each is loaded into a fresh
Template S interpreter: the real reader, ``restore(check_only=True)``, then the restore,
which shows its line (or menu) again.

When a feature adds or changes a ``GameState`` key (F14 ``rollback``, F18 ``chapter``,
F22 ``points``), the test fails; regenerate the saves with one command:

    .venv/Scripts/python -m tests.persist.template_s

A save format change (``vnsave`` or ``state_format`` above 1) must instead keep these files
and load them through a migration (``06`` §7). ``vnsave`` 2 (version 1's ``state_rev``) did:
these files stay ``vnsave`` 1 and load as revision 0, so their meta is compared without
``vnsave`` and ``state_rev``. The frozen version 1 saves are ``test_v1_golden_saves.py``'s.
"""

import json

from engine.persist import saves
from engine.persist.saves import SlotId, SlotStatus
from engine.runtime.commands import Say, ShowMenu
from engine.runtime.interpreter import RestoreResult
from tests.persist import save_support as ss
from tests.persist import template_s as ts

SHOWN = {"p6.vnsave": (Say, ts.LINE6), "menu.vnsave": (ShowMenu, None),
         "p18.vnsave": (Say, ts.LINE18)}
LENGTHS = ("thumb", "state", "vnsave", "state_rev")   # not compared (docstring)


def test_ac37_golden_saves_are_this_builds_and_load_at_their_lines(tmp_path):
    made = ts.golden_bytes(tmp_path / "game")
    assert sorted(p.name for p in ts.GOLDEN.iterdir()) == sorted(ts.GOLDEN_SAVES)
    for name, data in made.items():
        committed = (ts.GOLDEN / name).read_bytes()
        read = saves.parse_full(committed, game_id=ss.GAME_ID)
        ours = saves.parse_full(data, game_id=ss.GAME_ID)
        assert read.status is SlotStatus.OK, (name, read.reason)
        assert ss.meta(committed)["vnsave"] == 1 and read.meta.state_rev == 0, name
        meta = {k: v for k, v in ss.meta(committed).items() if k not in LENGTHS}
        assert meta == {k: v for k, v in ss.meta(data).items() if k not in LENGTHS}, name
        assert json.loads(ss.lines(committed)[2]) == json.loads(ss.lines(data)[2]), name
        assert read.state == ours.state, name
        head = saves.classify_head(committed, len(committed), SlotId("auto", 1),
                                   game_id=ss.GAME_ID, thumb=True)
        assert head.status is SlotStatus.OK and head.jpeg is not None, name
    program = ts.load_program(tmp_path / "story")
    for name, (kind, text) in SHOWN.items():
        slot = SlotId(1, 1)
        folder = tmp_path / "saves"
        folder.mkdir(exist_ok=True)
        (folder / slot.file_name()).write_bytes((ts.GOLDEN / name).read_bytes())
        read = saves.read_slot_full(folder, slot, game_id=ss.GAME_ID)
        assert read.status is SlotStatus.OK and read.state is not None, (name, read.reason)
        interp = ts.launched(program)
        interp.new_game(7)
        interp.run(10_000)
        interp.take_commands(1 << 30)
        assert interp.restore(read.state, check_only=True).result is RestoreResult.OK, name
        assert interp.restore(read.state).result is RestoreResult.OK, name
        interp.run(10_000)
        shown = [c for c in interp.take_commands(1 << 30) if type(c) in (Say, ShowMenu)]
        last = shown[-1]                       # a menu's question line comes before it
        assert type(last) is kind and last.sid == read.state.position and last.restored, name
        assert kind is ShowMenu or (len(shown) == 1 and last.text == text), name
        assert interp.checkpoint().to_json() == read.state.to_json(), name
