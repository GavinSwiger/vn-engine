"""F20 step 6 in the real app (06 §0.5: one App F session, module-scoped by design): Template L
launched in process (``scripted_app``: fake clock, hidden window, dev, unthreaded writer), the
title off, ``[saves] autosave_quit = true``. Until the page exists (s8) the jump is called
through ``App.flow.jump`` as the page will call it, after its confirm.

Rows: the launch listing and the frame slot write ``scene:stall``'s file (AC-F20-39, 37 in the
app); AC-F20-28's (F15) and (F18) rows (skip and auto off, the pending chapter auto-save
dropped) and the jump's Auto save before the commit (AC-F20-30's first row, service side);
AC-F20-29's windowed row (the jump releases what the headless jump releases); AC-F20-31's end
to end row (a damaged file: a notice, no error screen).
"""

import shutil
from pathlib import Path

import pygame
import pytest

from engine.persist.nodestates import NodeFolder, NodeStatus, node_file, read_node
from engine.persist.saves import SlotId, read_slot_full
from engine.runtime.commands import Say
from engine.runtime.flowchart import FlowStates
from engine.runtime.headless import run_headless
from engine.ui.nav import InputKind
from engine.ui.theme import Words
from tests.app.test_endings_app import spy_commands
from tests.app.test_saves_service import launch, line_text, play, unthreaded, wait
from tests.fakes.loop import post_key
from tests.runtime.corpus import canon
from tests.runtime.flow_story import load_l

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                        # the fixture, re-exported for pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "fixtures" / "F20" / "template"
CONFIG = """[game]
id = "f20-template"

[title]
enabled = false

[textbox]
cps = 0

[saves]
autosave_quit = true

[theme.ui]
fade_ms = 0

[theme.save]
load_fade_ms = 0
"""
LINE12 = "Daichi waves from the stall."
STALL = "scene:stall"


def autos(game: Path) -> int:
    """Auto slots holding a save."""
    return sum(read_slot_full(game / "saves", SlotId("auto", n),
                              game_id="f20-template").status.value == "ok" for n in range(1, 7))


def _released(commands: list) -> list:
    """Canonical JSON of ``commands`` up to and with the first ``Say``, without wait ids."""
    end = next(i for i, c in enumerate(commands) if type(c) is Say)
    out = []
    for item in canon(commands[:end + 1]):
        item.pop("wait_id", None)
        out.append(item)
    return out


def test_jump_in_the_app(tmp_path, scripted_app, unthreaded):
    game = tmp_path / "game"
    shutil.copytree(TEMPLATE, game)
    (game / "config.toml").write_text(CONFIG, encoding="utf-8")
    saves = game / "saves"
    saves.mkdir()
    (saves / node_file("chapter:river")).write_bytes(b"damaged\n")     # AC-31's file

    def script(app, out):
        yield from wait(lambda: line_text(app) is not None)
        words = Words(app.config.words)
        out["mode"] = app.flow.mode
        yield from wait(lambda: app.flow.listed)
        out["listed"] = set(app.flow.files)
        commands = spy_commands(app)
        while line_text(app) != LINE12:                 # Space until line 12 shows
            post_key(pygame.K_SPACE)
            for _ in range(3):
                yield
        yield from wait(lambda: node_file(STALL) in app.flow.files)
        out["file"] = read_node(NodeFolder(saves, release=False), STALL,
                                game_id="f20-template").status
        state = read_node(NodeFolder(saves, release=False), STALL,
                          game_id="f20-template").state
        out["state"] = state
        # Skip and auto on, a pending chapter auto-save; then the jump (in game).
        app.skip_auto.set_auto(True)
        app.skip_auto.skip = "toggled"
        app.saves.request_autosave()
        autos_before = autos(game)
        del commands[:]
        app.flow.jump(STALL, origin="game", by=InputKind.KEYS)
        out["auto_saved"] = autos(game) - autos_before
        out["off"] = (app.skip_auto.skipping, app.skip_auto.auto, app.saves.autosave_pending)
        yield from wait(lambda: any(type(c) is Say for c in commands))
        out["released"] = _released(list(commands))
        # AC-31 end to end: the damaged file → a notice, no error screen.
        app.flow.jump("chapter:river", origin="game", by=InputKind.KEYS)
        for _ in range(3):
            yield
        out["notice"] = ([v.text for v in app.shell.notices.views()],
                         words.get("notice_load_damaged"), app.error_mode,
                         app.flow.reason("chapter:river"))

    out = play(scripted_app, script, last=900)
    assert launch(game) == 0
    assert out["mode"] == "disk" and out["listed"] == {node_file("chapter:river")}
    assert out["file"] is NodeStatus.OK
    assert out["auto_saved"] == 1                   # the pre-jump Auto save, written
    assert out["off"] == (False, False, False)
    texts, damaged, error_mode, reason = out["notice"]
    assert damaged in texts and error_mode is False and reason == "flowchart_no_state"
    # AC-29's windowed row: the headless jump of the same state releases the same commands.
    program = load_l(tmp_path / "headless")
    holder = FlowStates()
    holder[STALL] = out["state"]
    headless = run_headless(program, seed=42, flow=holder, inputs=[f"jump {STALL}"])
    first = next(i for i, c in enumerate(headless) if type(c) is Say)
    assert _released(headless[first + 1:]) == out["released"]
