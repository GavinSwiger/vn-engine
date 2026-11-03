"""F31 s4 — quit never waits on meta jobs (F31 ``06-acceptance.md`` AC-F31-24; SEC-F31-08;
TR-F31-10; ``04`` §1.1 Q2): App M with a threaded writer on ``quit/`` (8 copies of a 64 KiB
original; the 4 MiB ``slow`` variant is not in the default tier). The first meta write waits
on an ``Event`` that is released 50 ms after ``drop_queued`` runs, so the other 7 are still
queued when the window closes."""

import threading
import time
from pathlib import Path

import pygame
import pytest

from engine.app.metafiles import DiskFolder
from engine.app.saves import SaveService
from engine.core import safefile
from engine.persist import limits
from engine.persist.writer import STOPPED_DETAIL, Failed
from engine.meta.files import MetaFolder
from tests.app.test_autosave_app import _quit_close_yes, autos
from tests.app.test_saves_service import launch, line_text, play, wait
from tests.fakes.loop import post_key
from tests.persist import save_support as ss

pytestmark = pytest.mark.display

ORIGINAL = bytes(range(256)) * 256                    # 64 KiB
SCRIPT = 'label start:\n    "Q0"\n' + '    file write "big.chr"\n' * 8 + '    "Q1"\n'


def test_ac_f31_24_quit_never_waits_on_meta_jobs(tmp_path, scripted_app, monkeypatch):
    game = tmp_path / "aiko" / "game"
    (game / "script").mkdir(parents=True)
    (game / "files").mkdir()
    (game / "files" / "big.chr").write_bytes(ORIGINAL)
    (game / "script" / "main.vns").write_text(SCRIPT, encoding="utf-8")
    (game / "config.toml").write_text(
        f'[game]\nid = "{ss.GAME_ID}"\ntitle = "Quit"\nversion = "1.0"\n\n'
        "[title]\nenabled = false\n\n[saves]\nautosave_quit = true\n", encoding="utf-8")

    order: list[str] = []
    gate = threading.Event()
    started: list[str] = []
    stopped: list[Failed] = []
    real_write, real_drop = safefile.write_atomic, DiskFolder.drop_queued
    real_submit_final, real_result = SaveService.submit_final, DiskFolder._result

    def write_atomic(target, pieces, **kw):
        if Path(target).name == "big.chr":
            started.append("big.chr")
            assert gate.wait(5)
        return real_write(target, pieces, **kw)

    def drop_queued(self):
        order.append("meta.drop_queued")
        threading.Timer(0.05, gate.set).start()
        real_drop(self)

    def submit_final(self):
        order.append("saves.submit_final")
        real_submit_final(self)

    def result(self, res):
        if isinstance(res, Failed) and res.detail == STOPPED_DETAIL:   # test-side read only
            stopped.append(res)
        real_result(self, res)

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)
    monkeypatch.setattr(DiskFolder, "drop_queued", drop_queued)
    monkeypatch.setattr(SaveService, "submit_final", submit_final)
    monkeypatch.setattr(DiskFolder, "_result", result)

    def script(app, out):
        yield from wait(lambda: line_text(app) == "Q0")
        while line_text(app) != "Q1":
            post_key(pygame.K_SPACE)
            yield
            yield
        out["in_flight"] = app.metafiles.client.in_flight
        out["threaded"] = app.writer.threaded
        yield from _quit_close_yes(app, out)

    out = play(scripted_app, script, last=300)
    began = time.monotonic()
    assert launch(game) == 0
    took = time.monotonic() - began
    gate.set()
    assert out["threaded"] and out["in_flight"] == 8
    assert order == ["meta.drop_queued", "saves.submit_final"]
    assert started == ["big.chr"] and len(stopped) == 7               # never started
    assert autos(game) == ["Q1"]                                      # the quit Auto save
    assert took < limits.CLOSE_WAIT_S + 5
    # The next launch's checks read the disk: the one write that ran is there, whole.
    root = game.resolve() / "characters"
    assert sorted(p.name for p in root.iterdir()) == ["big.chr"]
    assert MetaFolder(root, frozenset({"big.chr"})).exists("big.chr")
    assert (root / "big.chr").read_bytes() == ORIGINAL
