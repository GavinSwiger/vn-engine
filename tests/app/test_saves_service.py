"""F11 step 8 in the real app (App S on the reduced Template S, I-14 A8): ``SaveService``,
the quick keys, the commit outcome table (I-1), the quit steps, and W80/W81/W83.

ACs: AC-F11-23, 24, 26 (default row), 50 (App S probe), 52, 55, plus the service rows of
AC-F11-04, 14, 15. AC-F11-04's encoder rows, 06, 25, and 53 are proved headless in
``tests/persist`` (``test_save_pieces``, ``test_save_format``, ``test_save_rotation``,
``test_writer_shared``). Every run is an in-process ``launch()`` (``scripted_app``: fake frame
clock, hidden window, 1280×720, dev) on a game folder under ``tmp_path``, scripted frame by
frame with a generator (``play``). The writer is unthreaded (App S, ``06`` §0.2) unless a
test says threaded. Pending until later steps: the Save/Load pages (step 9), auto-saves and
the quit words (step 10), W82, the nearest point, and the load fade (step 11: those are in
``test_load_polish_app``); P-menu, P-fade,
and music rows wait for F04/F07/F08/F09 on Template S (I-14 A8).
"""

import errno
import os
import threading
import time
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app.saves import SaveService
from engine.core import safefile
from engine.persist import limits, saves, writer as writer_mod
from engine.persist.saves import SlotId, SlotStatus
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from tests.app.test_story_load_screen import records
from tests.fakes.loop import post_key
from tests.persist import save_support as ss

pytestmark = pytest.mark.display

LINE6 = "Hey, have you ever written a poem? I wrote one about paper lanterns last night."
LINE8 = "The wind picks up."
CONFIG = """[game]
id = "f11-template"
title = "Save Test"
version = "1.0"

[title]
enabled = false
"""
PINK_WHITE = (0xFF, 0xF4, 0xF8)             # notice fill (panel.fill_color) at 0.94


def make_game(tmp_path: Path, config: str = "") -> Path:
    """The game folder. Unless ``config`` sets ``autosave_quit``, it is false (step 10): the
    scripted quit at the end of every run would otherwise add an Auto save."""
    root = tmp_path / "game"
    (root / "script").mkdir(parents=True)
    text = CONFIG + config
    if "autosave_quit" not in text:
        text = (text.replace("[saves]\n", "[saves]\nautosave_quit = false\n", 1)
                if "[saves]\n" in text else text + "\n[saves]\nautosave_quit = false\n")
    (root / "config.toml").write_text(text, encoding="utf-8")
    (root / "script" / "main.vns").write_text(ss.TEMPLATE_S_REDUCED, encoding="utf-8")
    return root


def launch(game: Path, *, release: bool = False) -> int:
    return bootstrap.launch(game, release=release, bench_seconds=None,
                            log_level_override=None, pygame_warning=None)


@pytest.fixture
def unthreaded(monkeypatch):
    """App S's writer: every job runs inside ``submit`` (``06`` §0.2 Writer W)."""
    monkeypatch.setattr(writer_mod, "WRITER_THREADED", False)


def play(session, script, *, last: int = 400) -> dict:
    """Run ``script(app, out)`` (a generator: each ``yield`` waits one frame) from frame 2,
    then quit. ``out`` collects what the script records; ``out["frame"]`` is the frame."""
    out: dict = {"done": False}
    state: dict = {}

    def step(app) -> None:
        if out["done"]:
            return
        out["frame"] = session.limiters[-1].frame
        if "gen" not in state:
            state["gen"] = script(app, out)
        try:
            next(state["gen"])
        except StopIteration:
            out["done"] = True
            session.limiters[-1].quit_at(out["frame"] + 1)

    for frame in range(2, last):
        session.at(frame, step)
    session.quit_frame = last
    return out


def textbox(app) -> TextboxScreen | None:
    return getattr(app, "textbox", None)


def line_text(app) -> str | None:
    box = textbox(app)
    return None if box is None or box.line is None else box.line.text


def at_line(app, text: str, shown: int = 0) -> bool:
    box = textbox(app)
    return (line_text(app) == text and app.screens.top is box
            and box.shown_count() >= shown)


def notices(app) -> list[str]:
    return [v.text for v in app.shell.notices.views()]


def wait(pred):
    while not pred():
        yield


def file_of(game: Path, name: str) -> Path:
    return game / "saves" / name


def full(game: Path, slot: SlotId):
    return saves.read_slot_full(game / "saves", slot, game_id=ss.GAME_ID)


def quick(n: int) -> SlotId:
    return SlotId("quick", n)


def save_log(game: Path) -> list[str]:
    return [m for _, area, m in records(game / "logs" / "latest.log") if area == "save"]


# --- Milestone, AC-F11-23 and 24: F5 shows "Quick saved." while typing; F9 → Yes loads -----

def _typing_run(tmp_path, scripted_app, *, press_f5: bool) -> dict:
    game = make_game(tmp_path / ("f5" if press_f5 else "control"))

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6, 10))
        out["f"] = out["frame"]
        out["cp"] = app.story.checkpoint()
        if press_f5:
            post_key(pygame.K_F5)
        counts = []
        for _ in range(6):
            yield
            counts.append(textbox(app).shown_count())
            out.setdefault("notice_frame", None)
            if out["notice_frame"] is None and "Quick saved." in notices(app):
                out["notice_frame"] = out["frame"]
                out["file_then"] = file_of(game, "quick-1.vnsave").is_file()
        out["counts"] = counts

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    out["game"] = game
    return out


def test_milestone_quick_save_while_typing_then_quick_load(tmp_path, scripted_app, unthreaded):
    """AC-F11-23 (file, notice within 3 frames and never before the file, typing unchanged)
    and AC-F11-24 (confirm text; Yes loads quick-1; line 6 types again from 0)."""
    control = _typing_run(tmp_path, scripted_app, press_f5=False)
    out = _typing_run(tmp_path, scripted_app, press_f5=True)
    game = out["game"]
    assert out["counts"] == control["counts"]                  # line 6 keeps typing
    assert out["counts"][-1] > out["counts"][0]
    assert out["notice_frame"] is not None and out["notice_frame"] - out["f"] <= 3
    assert out["file_then"]                                    # never before the file
    read = full(game, quick(1))
    assert read.status is SlotStatus.OK and read.state == out["cp"]
    assert read.meta.description == "Hana: " + LINE6[:50] + "…"
    assert read.meta.game == ss.GAME_ID and read.meta.seq == 1
    assert not file_of(game, "quick-2.vnsave").exists()


def test_quick_load_confirm_no_then_yes(tmp_path, scripted_app, unthreaded):
    """AC-F11-24: F9 at a later line asks; No changes nothing; Yes loads the save (line 6
    shown again); the restored checkpoint equals the saved one."""
    game = make_game(tmp_path)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6, 10))
        out["cp"] = app.story.checkpoint()
        post_key(pygame.K_F5)
        yield from wait(lambda: "Quick saved." in notices(app))
        post_key(pygame.K_SPACE)                               # complete line 6
        yield
        post_key(pygame.K_SPACE)                               # on to line 8
        yield from wait(lambda: at_line(app, LINE8))
        post_key(pygame.K_F9)
        yield
        top = app.screens.top
        out["question"] = top.message if isinstance(top, ConfirmScreen) else None
        post_key(pygame.K_ESCAPE)                              # No
        yield from wait(lambda: at_line(app, LINE8))
        out["after_no"] = line_text(app)
        post_key(pygame.K_F9)
        yield
        post_key(pygame.K_LEFT)                                # to Yes
        yield
        post_key(pygame.K_RETURN)
        yield from wait(lambda: at_line(app, LINE6))
        out["restored_line"] = textbox(app).line.restored
        out["restored"] = app.story.checkpoint()

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["question"] == "Load this save? Unsaved progress will be lost."
    assert out["after_no"] == LINE8
    # F05 shows a restored line complete (``Say.restored``); AC-F11-22's "types again from
    # 0 characters" row is step 11's and conflicts with that rule (reported).
    assert out["restored_line"] is True
    assert out["restored"].to_json() == out["cp"].to_json()


def test_quick_load_picks_the_highest_seq_without_confirm(tmp_path, scripted_app, unthreaded):
    """AC-F11-24: quick-1..3 with seq 3, 7, 5 and saved_at reversed → quick-2;
    ``confirm_quick_load = false`` loads at once; Q.Load is the same action."""
    game = make_game(tmp_path, "\n[saves]\nconfirm_quick_load = false\n")
    folder = game / "saves"
    folder.mkdir()
    for n, seq in ((1, 3), (2, 7), (3, 5)):
        state = ss.p8_state(marker=n)
        ss.write_slot(folder, ss.make_save(state, seq=seq, saved_at=ss.SAVED_AT - seq),
                      quick(n))

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_F9)
        yield
        yield
        out["marker"] = app.story.checkpoint().variables.get("marker")
        out["line"] = line_text(app)

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["marker"] == 2 and out["line"] == LINE8


def test_no_quick_save_and_modifiers(tmp_path, scripted_app, unthreaded):
    """AC-F11-24: no OK quick slot (empty, or only DAMAGED and NEWER) → the info notice
    ``No quick save yet.``; AC-F11-23: F5 with Ctrl, Alt, or Meta does nothing."""
    game = make_game(tmp_path)
    folder = game / "saves"
    folder.mkdir()
    ss.write_slot(folder, b"junk\n", quick(1))
    ss.write_slot(folder, ss.with_meta(ss.make_save(), vnsave=2), quick(2))

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_F9)
        yield
        yield
        out["views"] = [(v.text, v.kind) for v in app.shell.notices.views()]
        out["top"] = type(app.screens.top).__name__
        for mod in (pygame.KMOD_LCTRL, pygame.KMOD_LALT, pygame.KMOD_LMETA):
            post_key(pygame.K_F5, mod)
        for _ in range(4):
            yield

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["views"] == [("No quick save yet.", "info")]
    assert out["top"] == "TextboxScreen"
    assert sorted(p.name for p in folder.iterdir()) == ["quick-1.vnsave", "quick-2.vnsave"]


# --- AC-F11-23 rotation, AC-F11-04 reuse, AC-F11-50 probe, AC-F11-52 ---------------------------

def test_f5_seven_times_rotates_and_reuses_pieces(tmp_path, scripted_app, unthreaded,
                                                  monkeypatch):
    """AC-F11-23: six F5s fill quick-1..6; the 7th replaces the lowest ``seq`` (quick-1).
    AC-F11-04: F5 on one checkpoint encodes its state once and never has more than 2 of
    F11's writes pending. Q.Save does the same as F5."""
    game = make_game(tmp_path)
    calls = []
    real = saves.iter_pieces
    monkeypatch.setattr(saves, "iter_pieces", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    pending = []
    real_update = SaveService.update

    def update(self, dt):
        real_update(self, dt)
        pending.append(self.client.pending)

    monkeypatch.setattr(SaveService, "update", update)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        for i in range(7):
            if i == 6:
                entry = app.shell.menus.entry("quick", "q_save")
                from engine.ui.menus import EntryContext
                from engine.ui.nav import InputKind
                entry.action(EntryContext(app.shell, InputKind.MOUSE))
            else:
                post_key(pygame.K_F5)
            yield
            yield

    out = play(scripted_app, script)
    assert launch(game) == 0
    heads = {n: full(game, quick(n)) for n in range(1, 7)}
    assert all(h.status is SlotStatus.OK for h in heads.values())
    assert [heads[n].meta.seq for n in range(1, 7)] == [7, 2, 3, 4, 5, 6]
    assert len(calls) == 1
    assert max(pending) <= 2


def test_notice_probe_and_clicks_pass_through(tmp_path, scripted_app, unthreaded):
    """AC-F11-50 (App S probe: (1250, 53) is the notice fill over the stage) and AC-F11-52
    (a click on the notice advances line 6 as without it; the notice keeps counting)."""
    game = make_game(tmp_path)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        out["stage"] = tuple(app.window.framebuffer().get_at((1250, 53)))[:3]
        post_key(pygame.K_F5)
        yield from wait(lambda: any(v.text == "Quick saved." and v.opacity >= 1.0
                                    for v in app.shell.notices.views()))
        yield
        out["probe"] = tuple(app.window.framebuffer().get_at((1250, 53)))[:3]
        before = textbox(app).typer.shown
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(1100, 50)))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(1100, 50)))
        yield
        out["completed"] = textbox(app).shown_count() > before + 5
        out["still"] = "Quick saved." in notices(app)

    out = play(scripted_app, script)
    assert launch(game) == 0
    expected = tuple(round(f * 0.94 + s * 0.06) for f, s in zip(PINK_WHITE, out["stage"]))
    assert all(abs(a - b) <= 2 for a, b in zip(out["probe"], expected)), out
    assert out["completed"] and out["still"]


# --- I-1: the commit outcome table (a refused load changes nothing) -------------------------

@pytest.mark.parametrize("edit, notice", [
    pytest.param(lambda: b"junk\n", "This save is damaged and can't be loaded.", id="damaged"),
    pytest.param(lambda: ss.make_save(ss.state_with({"trust": 0}), seq=9).replace(
        ss.P8_SID.encode(), b"start/000000000000").replace(b'"at":["start",[2]]',
                                                           b'"at":["start",[9]]'),
        "This save no longer fits the story and can't be loaded.", id="position_not_found"),
])
def test_refused_quick_load_changes_nothing(tmp_path, scripted_app, unthreaded, edit, notice):
    """§7.6's table through I-1 (one row of each kind): the problem notice shows, the game
    goes on at its line, and nothing is restored."""
    game = make_game(tmp_path, "\n[saves]\nconfirm_quick_load = false\n")
    folder = game / "saves"
    folder.mkdir()
    data = edit()
    ss.write_slot(folder, data, quick(1))

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        if b"junk" in data:
            # A damaged slot is never Q.Load's target: load it the way a page does.
            app.saves._load(quick(1), "game")
        else:
            post_key(pygame.K_F9)
        yield
        yield
        out["views"] = [(v.text, v.kind) for v in app.shell.notices.views()]
        out["line"] = line_text(app)

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["views"] == [(notice, "problem")]
    assert out["line"] == LINE6


# --- W83 and the save notices (§7.3 Results; AC-F11-55 group G) ------------------------------

def test_write_failure_notice_w83_and_skip(tmp_path, scripted_app, unthreaded, monkeypatch):
    """``EIO`` once on quick-1's write: ``Couldn't save: the file couldn't be written.``,
    W83 ``couldn't save to Quick 1: couldn't write``, and the second save goes to another
    slot (AC-F11-55's last row); ``ENOSPC`` → the disk-full words."""
    game = make_game(tmp_path)
    faults = [errno.EIO, errno.ENOSPC]
    real = safefile.write_atomic

    def write_atomic(target, pieces, **kw):
        if faults and target.name.endswith(".vnsave"):
            raise OSError(faults.pop(0), "injected")
        return real(target, pieces, **kw)

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        texts = []
        for _ in range(3):
            post_key(pygame.K_F5)
            yield
            yield
            texts.append(notices(app)[-1] if notices(app) else None)
            app.shell.clear_notices()
        out["texts"] = texts

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["texts"] == ["Couldn't save: the file couldn't be written.",
                            "Couldn't save: the disk is full.", "Quick saved."]
    assert not file_of(game, "quick-1.vnsave").exists()
    assert not file_of(game, "quick-2.vnsave").exists()        # skipped after its failure
    assert full(game, quick(3)).status is SlotStatus.OK
    w83 = [m for m in save_log(game) if "couldn't save to" in m]
    assert w83 == ["couldn't save to Quick 1: couldn't write",
                   "couldn't save to Quick 2: disk full"]


def test_group_g_seq_clock_and_unusable_slots(tmp_path, scripted_app, unthreaded, monkeypatch):
    """AC-F11-55: quick-3 with ``seq`` 2⁵³ → three F5s each read OK on head and full and
    each shows ``Quick saved.``; ``saved_at`` is clamped (1969, 2100, year 10000); a folder
    at ``quick-1.vnsave`` is never chosen."""
    game = make_game(tmp_path)
    folder = game / "saves"
    folder.mkdir()
    ss.write_slot(folder, ss.make_save(seq=limits.SEQ_MAX), quick(3))
    (folder / "quick-1.vnsave").mkdir()
    clocks = iter([-1.0, 4_102_444_800.0, 253_402_300_800.0])
    now = {"t": None}
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: now["t"] if now["t"] is not None else real_time())

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        seen = []
        for _ in range(3):
            now["t"] = next(clocks)
            post_key(pygame.K_F5)
            yield
            now["t"] = None
            yield
            seen.append(notices(app)[-1] if notices(app) else None)
            app.shell.clear_notices()
        out["seen"] = seen

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["seen"] == ["Quick saved."] * 3
    assert (folder / "quick-1.vnsave").is_dir()
    written = [full(game, quick(n)) for n in (2, 4, 5)]
    assert all(r.status is SlotStatus.OK for r in written)
    assert [r.meta.saved_at for r in written] == [0, 4_102_444_800, 253_402_300_799]
    assert all(r.meta.seq == limits.SEQ_MAX for r in written)
    heads = [saves.read_slot_head(folder, quick(n), game_id=ss.GAME_ID, thumb=True)
             for n in (2, 4, 5)]
    assert all(h.status is SlotStatus.OK and h.jpeg is not None for h in heads)


def test_group_g_every_quick_slot_unreplaceable(tmp_path, scripted_app, unthreaded):
    """AC-F11-55 (G2): six quick slots NEWER or OTHER_GAME → ``Couldn't save: every slot on
    that page holds a save this version can't replace.``; no file changes."""
    game = make_game(tmp_path)
    folder = game / "saves"
    folder.mkdir()
    for n in range(1, 7):
        data = (ss.with_meta(ss.make_save(), vnsave=2) if n % 2
                else ss.make_save(game="other-game"))
        ss.write_slot(folder, data, quick(n))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_F5)
        yield
        yield
        out["views"] = [(v.text, v.kind) for v in app.shell.notices.views()]

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["views"] == [("Couldn't save: every slot on that page holds a save this "
                             "version can't replace.", "problem")]
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


# --- AC-F11-26: rapid saves on the threaded writer ----------------------------------------------

@pytest.mark.parametrize("presses, every, fsync_s, paced", [
    pytest.param(30, 2, 0.002, False, id="default"),
    # 10 a second for 10 s in real time (frames paced at 60 per second).
    pytest.param(100, 6, 0.020, True, id="full", marks=pytest.mark.slow),
])
def test_rapid_saves_threaded(tmp_path, scripted_app, monkeypatch, presses, every, fsync_s,
                              paced):
    """AC-F11-26: F5 at a steady rate on the threaded writer: one write at a time, results
    in submission order, every quick file whole and equal to the checkpoint, the six
    highest ``seq``s on disk, no temp left, one ``Quick saved.`` panel at a time."""
    game = make_game(tmp_path)
    active = {"now": 0, "max": 0}
    threads = set()
    lock = threading.Lock()
    real = safefile.write_atomic
    written: list[int] = []

    def write_atomic(target, pieces, **kw):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        threads.add(threading.get_ident())
        try:
            time.sleep(fsync_s)
            stamp = real(target, pieces, **kw)
            written.append(int(saves.meta_of(saves.strict_loads(pieces[0][:-1])).seq))
            return stamp
        finally:
            with lock:
                active["now"] -= 1

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6, 10))
        post_key(pygame.K_SPACE)                              # P6f: fully shown
        yield
        out["cp"] = app.story.checkpoint()
        panels = 0
        for i in range(presses * every):
            if i % every == 0:
                post_key(pygame.K_F5)
            if paced:
                time.sleep(1 / 60)
            yield
            panels = max(panels, notices(app).count("Quick saved."))
        app.saves.finish_index()
        for _ in range(200):
            if not app.saves._sent and not app.saves._jobs:
                break
            time.sleep(0.01)
            yield
        out["panels"] = panels

    out = play(scripted_app, script, last=presses * every + 600)
    assert launch(game) == 0
    assert active["max"] == 1 and threading.main_thread().ident not in threads
    assert written == sorted(written) and len(written) == presses
    reads = [full(game, quick(n)) for n in range(1, 7)]
    assert all(r.status is SlotStatus.OK and r.state == out["cp"] for r in reads)
    assert sorted(r.meta.seq for r in reads) == list(range(presses - 5, presses + 1))
    assert not [p for p in (game / "saves").iterdir() if p.name.endswith(".tmp")]
    assert out["panels"] == 1


# --- §7.1: W80, W81, stale temps (AC-F11-14), the index (AC-F11-15) --------------------------

def test_w81_link_folder_reads_nothing_and_saves_fail(tmp_path, scripted_app, unthreaded):
    """AC-F11-14: a dev ``saves/`` that is a junction (Windows) or symlink to
    ``outside/s/``: W81 once; F5 → ``Couldn't save: the save folder can't be written.``;
    nothing in ``outside/s/`` is read or created."""
    game = make_game(tmp_path)
    outside = tmp_path / "outside" / "s"
    outside.mkdir(parents=True)
    ss.write_slot(outside, ss.make_save(seq=5), quick(1))
    before = {p.name: p.read_bytes() for p in outside.iterdir()}
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), str(game / "saves"))
        else:
            os.symlink(outside, game / "saves", target_is_directory=True)
    except OSError:
        pytest.skip("links can't be made here")

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_F9)
        yield
        out["f9"] = notices(app)
        app.shell.clear_notices()
        post_key(pygame.K_F5)
        yield
        yield
        out["f5"] = notices(app)

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["f9"] == ["No quick save yet."]
    assert out["f5"] == ["Couldn't save: the save folder can't be written."]
    assert {p.name: p.read_bytes() for p in outside.iterdir()} == before
    w81 = [m for m in save_log(game) if m.startswith("saves can't be written")]
    assert w81 == ["saves can't be written this session: the save folder <game>/saves "
                   "is a link"]


def test_install_removes_only_old_slot_temps(tmp_path, scripted_app, unthreaded):
    """AC-F11-14: install removes regular slot temps over 60 s old only."""
    game = make_game(tmp_path)
    folder = game / "saves"
    folder.mkdir()
    old = time.time() - 61
    names = {".quick-1.vnsave.0123abcd.tmp": old, ".quick-2.vnsave.0123abcd.tmp": time.time() - 59,
             ".quick-1.vnsave.XYZ.tmp": old, ".persistent.json.0123abcd.tmp": old}
    for name, when in names.items():
        (folder / name).write_bytes(b"x")
        os.utime(folder / name, (when, when))
    (folder / ".auto-1.vnsave.0123abcd.tmp").mkdir()

    out = play(scripted_app, lambda app, out: wait(lambda: at_line(app, LINE6)))
    assert launch(game) == 0
    left = sorted(p.name for p in folder.iterdir())
    assert left == [".auto-1.vnsave.0123abcd.tmp", ".persistent.json.0123abcd.tmp",
                    ".quick-1.vnsave.XYZ.tmp", ".quick-2.vnsave.0123abcd.tmp"]


def test_w80_release_without_id(tmp_path, scripted_app, user_roots, unthreaded):
    """W80 once; ``q_save``/``q_load`` hidden; F5 and F9 do nothing; no saves folder."""
    game = make_game(tmp_path)
    (game / "config.toml").write_text(CONFIG.replace('id = "f11-template"\n', ""),
                                      encoding="utf-8")

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        out["shown"] = [e.id for e in app.shell.menus.shown("quick")]
        out["pages"] = [e.id for m in ("game", "title", "quick")
                        for e in app.shell.menus.shown(m) if e.id in ("save", "load")]
        post_key(pygame.K_F5)
        post_key(pygame.K_F9)
        yield
        yield
        out["notices"] = notices(app)
        out["available"] = app.saves.available

    out = play(scripted_app, script)
    assert launch(game, release=True) == 0
    assert "q_save" not in out["shown"] and "q_load" not in out["shown"]
    assert out["pages"] == []                     # step 9: Save and Load hidden everywhere
    assert out["notices"] == [] and out["available"] is False
    assert not (game / "saves").exists()
    logs = list(user_roots.home.rglob("latest.log"))
    w80 = [m for log in logs for _, area, m in records(log) if area == "save"]
    assert w80 == ["saving is off: a release run needs [game] id in config.toml"]


def test_save_before_the_index_ends_finishes_it(tmp_path, scripted_app, unthreaded,
                                                monkeypatch):
    """AC-F11-15: a save requested before the ``IndexJob`` ends finishes it first and takes
    ``max_seq + 1`` over every page (DAMAGED, NEWER, OTHER_GAME seqs don't count)."""
    game = make_game(tmp_path)
    folder = game / "saves"
    folder.mkdir()
    ss.write_slot(folder, ss.make_save(seq=40), SlotId(7, 3))
    ss.write_slot(folder, ss.with_meta(ss.make_save(seq=90), vnsave=2), SlotId(2, 1))
    ss.write_slot(folder, ss.make_save(seq=95, game="other-game"), SlotId(2, 2))
    real_step = saves.IndexJob.step
    # The frame slot never gets a step done; only ``finish()`` (deadline ∞) runs it.
    monkeypatch.setattr(saves.IndexJob, "step", lambda self, deadline, clock: (
        real_step(self, deadline, clock) if deadline == float("inf") else False))

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_F5)
        yield
        yield

    play(scripted_app, script)
    assert launch(game) == 0
    assert full(game, quick(1)).meta.seq == 41


# --- §7.8 step 5: the quit steps (C9, I-3) ------------------------------------------------------

def test_quit_submits_encoded_jobs_and_logs_the_rest(tmp_path, scripted_app, monkeypatch):
    """At quit, a job still waiting for the writer is abandoned at the shared deadline
    with W83 ``the quit didn't wait for it``; the slot keeps no partial file."""
    game = make_game(tmp_path)
    gate = threading.Event()
    real = safefile.write_atomic

    def write_atomic(target, pieces, **kw):
        if target.name.endswith(".vnsave"):
            gate.wait(5)
        return real(target, pieces, **kw)

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)
    monkeypatch.setattr(limits, "CLOSE_WAIT_S", 0.2)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_F5)
        yield
        yield from wait(lambda: app.saves._sent)    # encoding may take a few frames
        out["sent"] = len(app.saves._sent)

    out = play(scripted_app, script)
    try:
        assert launch(game) == 0
        assert out["sent"] == 1
        assert "couldn't save to Quick 1: the quit didn't wait for it" in save_log(game)
        # Checked while the abandoned write is still held, as when the process exits.
        assert not file_of(game, "quick-1.vnsave").exists()
    finally:
        gate.set()
        thread = scripted_app.apps[-1].writer._thread if scripted_app.apps else None
        if thread is not None:          # the abandoned writer ends inside this test
            thread.join(5)


def test_quit_writes_a_save_still_waiting_to_be_encoded(tmp_path, scripted_app, unthreaded,
                                                        monkeypatch):
    """A save requested but not yet encoded when the quit comes (the frame slot held back,
    as by the writer's backlog) is encoded and written at quit, not dropped with W83."""
    game = make_game(tmp_path)
    monkeypatch.setattr("engine.app.saves._PENDING_WRITES_MAX", 0)   # update never encodes

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_F5)
        yield
        yield
        out["waiting"] = len(app.saves._jobs)

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["waiting"] == 1
    assert full(game, quick(1)).status is SlotStatus.OK
    assert not any("didn't wait" in m for m in save_log(game)), save_log(game)


# --- AC-F11-04: the CI guard (real clock) ---------------------------------------------------------

def test_ci_guard_update_stays_under_5_ms(tmp_path, scripted_app, monkeypatch):
    """AC-F11-04 CI guard: a 1 MB state, the threaded writer with fsync sleeping 500 ms,
    a save every 10 frames for 120 frames: every ``SaveService.update`` takes ≤ 5 ms (real
    clock, ``gc`` off while timing) and ``write_atomic`` never runs on the main thread.
    The sleeps end when the frames do, so the quit doesn't wait them out."""
    import dataclasses
    import gc
    from types import MappingProxyType

    from engine.app.story import RuntimeStoryDriver

    game = make_game(tmp_path)
    release = threading.Event()
    threads = set()
    real_write = safefile.write_atomic

    def write_atomic(target, pieces, **kw):
        threads.add(threading.get_ident())
        release.wait(0.5)                                     # the 500 ms fsync
        return real_write(target, pieces, **kw)

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)
    from engine.runtime.values import freeze

    big = freeze([f"{i:06d} the lanterns drift over the river at dusk" for i in range(20_000)])
    real_cp = RuntimeStoryDriver.checkpoint

    def checkpoint(self):
        cp = real_cp(self)
        if cp is None:
            return None
        return dataclasses.replace(cp, variables=MappingProxyType({**cp.variables, "big": big}))

    monkeypatch.setattr(RuntimeStoryDriver, "checkpoint", checkpoint)
    times: list[float] = []
    real_update = SaveService.update

    def update(self, dt):
        enabled = gc.isenabled()
        gc.disable()
        start = time.perf_counter()
        try:
            real_update(self, dt)
        finally:
            times.append(time.perf_counter() - start)
            if enabled:
                gc.enable()

    monkeypatch.setattr(SaveService, "update", update)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        out["size"] = len(b"".join(saves.iter_pieces(app.story.checkpoint().to_json())))
        times.clear()
        for i in range(120):
            if i % 10 == 0:
                post_key(pygame.K_F5)
            yield
        out["notices"] = notices(app)
        release.set()

    out = play(scripted_app, script)
    try:
        assert launch(game) == 0
    finally:
        release.set()
    assert out["size"] >= 1_000_000, out
    assert len(times) >= 120 and max(times) <= 0.005, max(times)
    assert threads and threading.main_thread().ident not in threads, out["notices"]


# --- AC-F11-23: F5 at a choice menu (F07's ChoiceScreen passes it through) ---------------------

MENU_SCRIPT = '''define hana = Character("Hana")
label start:
    menu:
        hana "Where should we go?"
        "Help Hana with the posters":
            hana "Thanks!"
        "Go home":
            "Home."
    return
'''


def test_f5_at_a_choice_menu_saves_the_menu(tmp_path, scripted_app, unthreaded):
    """AC-F11-23's P-menu row (a menu of its own until Template S is whole, I-14 A8): F5
    while the choices show saves the menu checkpoint (``choices.waiting`` set) and the
    menu stays up; F9 → Yes brings the menu back."""
    from engine.ui.builtin.choice_screen import ChoiceScreen

    game = make_game(tmp_path)
    (game / "script" / "main.vns").write_text(MENU_SCRIPT, encoding="utf-8")

    def script(app, out):
        yield from wait(lambda: isinstance(app.screens.top, ChoiceScreen))
        out["cp"] = app.story.checkpoint()
        post_key(pygame.K_F5)
        yield
        yield
        out["notices"] = notices(app)
        out["top"] = type(app.screens.top)
        post_key(pygame.K_F9)
        yield
        post_key(pygame.K_LEFT)
        yield
        post_key(pygame.K_RETURN)
        yield from wait(lambda: isinstance(app.screens.top, ChoiceScreen))
        out["after"] = app.story.checkpoint()

    out = play(scripted_app, script)
    assert launch(game) == 0
    read = full(game, quick(1))
    assert read.status is SlotStatus.OK and read.state == out["cp"]
    assert read.state.choices.waiting is not None
    assert read.meta.description == "Hana: Where should we go?"
    assert out["notices"] == ["Quick saved."] and out["top"] is ChoiceScreen
    assert out["after"].to_json() == out["cp"].to_json()
