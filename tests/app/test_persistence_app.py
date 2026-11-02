"""Persistent data in the App (F12 checklist step 6; ``04`` §7.4, §7.5, §7.7; ``07`` I-1):
the launch read in ``StoryLoadScreen``, ``App.persist``'s frame slot, the flushes, the quit
close, ``--no-persistent``, and W53. AC-F12-31, AC-F12-32, AC-F12-35, the App row of
AC-F12-36, and the milestone: values survive a restart.

App A (06 §0.2): in-process launches (``scripted_app``: F01's fake frame clock, hidden
window), the game started through ``bootstrap``. The writer is synchronous
(``WRITER_THREADED = False``) unless a test says "threaded". Where an AC row has a ``$``
line, the story plays it (F12 step 3a); a few timing rows still change
``App.persist.store`` from a scripted action, at a known frame.
"""

import json
import threading
import time
from pathlib import Path

import pygame
import pytest

from engine.app import cli
from engine.app.app import App
from engine.app.loading import StoryLoadScreen
from engine.audio.service import AudioService
from engine.core.config_schema import WordsConfig
from engine.core.paths import GamePaths
from engine.persist import limits
from engine.persist.fileformat import ReadJob
from engine.persist.location import FILE_NAME
from engine.persist.sync import MEMORY, WRITABLE, PersistentSync
from engine.persist.texts import NO_ID_TEXT, OFF_TEXT, final_write_skipped_text
from engine.runtime.commands import Say
from engine.runtime.headless import run_headless
from engine.runtime.launch import LaunchJob
from engine.runtime.persistent import Missing
from engine.script import StoryLoader, load_story
from engine.ui.builtin.error import ErrorScreen
from engine.ui.shell import GameShell
from tests.app.test_story_load_screen import launch, make_game, records
from tests.fakes.loop import post_key
from tests.persist.writer_support import tree

pytestmark = pytest.mark.display

FILE = "<game>/persistent/persistent.json"
INSTANT = "\n[textbox]\ncps = 0\n"
TWO_LINES = 'default trust = 0\nlabel start:\n    "Start."\n    "End."\n    return\n'


@pytest.fixture(autouse=True)
def sync_writer(monkeypatch):
    """Synchronous writes, unless a test patches this back."""
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", False)


def game_of(tmp_path: Path, script: str = TWO_LINES, *, config: str = INSTANT) -> Path:
    game = make_game(tmp_path, {"main.vns": script})
    with (game / "config.toml").open("a", encoding="utf-8") as f:
        f.write(config)
    return game


def ready(app: App) -> bool:
    """The launch is over and the first line is on the text box."""
    textbox = app.textbox
    return (app.persist is not None and not app.loading and textbox is not None
            and textbox.line is not None)


def once_ready(session, action, *, first: int = 2, last: int = 200) -> list:
    """Run ``action(app)`` at the start of the first frame where ``ready``; returns a list
    that holds that frame's number."""
    done: list[int] = []

    def maybe(app):
        if not done and ready(app):
            done.append(session.limiters[-1].frame)
            action(app)

    for frame in range(first, last):
        session.at(frame, maybe)
    return done


def disk(game: Path) -> dict:
    return json.loads((game / "persistent" / FILE_NAME).read_bytes())


def log_of(game: Path) -> list[tuple[str, str, str]]:
    return records(game / "logs" / "latest.log")


# --- The milestone: values survive a restart --------------------------------------------------

def test_milestone_values_and_seen_lines_survive_a_restart(tmp_path, user_roots, scripted_app):
    """Run 1 changes the store (step 3a's ``$ persistent.festivals += 1`` and the runtime's
    seen mark stand-ins) and quits; run 2 launches the same game and finds them."""
    game = game_of(tmp_path)
    marked = []

    def change(app):
        store = app.persist.store
        store.set("festivals", 1)
        store.set("flowers", ["sad"])          # F19 made persistent.endings a read-only view
        sid = app.textbox.line.sid               # the runtime marks it on Advance (step 3)
        store.mark_seen(sid)
        marked.append(sid)

    once_ready(scripted_app, change)
    scripted_app.quit_frame = 60
    assert launch(game) == 0
    assert disk(game)["values"] == {"festivals": 1, "flowers": ["sad"], "playthrough": 0}

    found = {}
    scripted_app.actions.clear()
    once_ready(scripted_app, lambda app: found.update(
        festivals=app.persist.store.get("festivals"),
        flowers=app.persist.store.get("flowers"),
        seen=app.persist.store.is_seen(marked[0]), mode=app.persist.mode))
    assert launch(game) == 0
    assert found == {"festivals": 1, "flowers": ["sad"], "seen": True, "mode": WRITABLE}
    problems = [r for r in log_of(game) if r[0] in ("WARNING", "ERROR")]
    assert problems == []


# --- AC-F12-31 — launch order and slicing -----------------------------------------------------

def test_ac31_launch_order_and_the_frame_slot(tmp_path, user_roots, scripted_app, monkeypatch):
    game = game_of(tmp_path)
    program = load_story(GamePaths.for_game(game)).program
    first = next(c for c in run_headless(program, seed=1) if type(c) is Say)
    label, _, key = first.sid.rpartition("/")
    (game / "persistent").mkdir()
    (game / "persistent" / FILE_NAME).write_bytes(json.dumps(
        {"format": 1, "identity_scheme": 1, "values": {}, "seen": {label: key},
         "chosen": {}, "unlocks": {}}).encode("ascii"))

    events: list[tuple[int, str]] = []

    def frame() -> int:
        return scripted_app.limiters[-1].frame if scripted_app.limiters else 0

    def spy(cls, name, tag):
        real = getattr(cls, name)

        def wrapper(self, *args, **kwargs):
            result = real(self, *args, **kwargs)
            if tag != "loaded" or result:
                events.append((frame(), tag))
            return result
        monkeypatch.setattr(cls, name, wrapper)

    import engine.app.persistence as persistence
    real_read = persistence.safefile.read_regular
    monkeypatch.setattr(persistence.safefile, "read_regular",
                        lambda *a: events.append((frame(), "read")) or real_read(*a))
    spy(StoryLoader, "step", "loaded")
    spy(ReadJob, "step", "read-step")
    spy(LaunchJob, "__init__", "launch-job")
    spy(PersistentSync, "update", "persist")
    spy(AudioService, "update", "audio")
    seen_at_say = []
    from engine.app.dispatch import CommandRouter
    real_dispatch = CommandRouter.dispatch

    def dispatch(self, command):
        events.append((frame(), "dispatch"))
        if type(command) is Say:
            app = scripted_app.apps[-1]
            seen_at_say.append((command.sid, app.persist.store.is_seen(command.sid)))
        return real_dispatch(self, command)

    monkeypatch.setattr(CommandRouter, "dispatch", dispatch)
    scripted_app.quit_frame = 20
    assert launch(game) == 0
    tags = [tag for _, tag in events]
    loaded = tags.index("loaded")
    assert tags.index("read") > loaded
    assert tags.index("launch-job") > max(i for i, t in enumerate(tags) if t == "read-step")
    assert seen_at_say[0] == (first.sid, True)
    # Each frame after install: one persist.update, after every dispatch, before audio.
    by_frame: dict[int, list[str]] = {}
    for f, tag in events:
        by_frame.setdefault(f, []).append(tag)
    installed = [f for f, tags_ in by_frame.items() if "persist" in tags_]
    assert installed and installed == list(range(installed[0], installed[0] + len(installed)))
    for f in installed:
        tags_ = [t for t in by_frame[f] if t in ("dispatch", "persist", "audio")]
        assert tags_.count("persist") == 1
        p = tags_.index("persist")
        assert all(t == "dispatch" for t in tags_[:p]) and tags_[p + 1:] == ["audio"]
    app = scripted_app.apps[-1]
    assert isinstance(app.persist, PersistentSync) and app.persist.mode is WRITABLE


# --- AC-F12-32 — runs without a file ---------------------------------------------------------

FESTIVALS = ('default trust = 0\ndefault persistent.festivals = 0\nlabel start:\n'
             '    $ persistent.x = 1\n    "Start."\n    "End."\n    return\n')


def _festivals_file(game: Path) -> bytes:
    data = json.dumps({"format": 1, "identity_scheme": 1, "values": {"festivals": 2},
                       "seen": {}, "chosen": {}, "unlocks": {}}).encode("ascii")
    (game / "persistent").mkdir()
    (game / "persistent" / FILE_NAME).write_bytes(data)
    return data


@pytest.mark.parametrize("extra", [[], ["--seed", "7", "--start", "start", "--set", "trust=2"]],
                         ids=["plain", "with-start-options"])
def test_ac32_no_persistent_reads_and_writes_nothing(tmp_path, user_roots, scripted_app, extra):
    """The file holds ``festivals`` 2; the run reads its ``default`` 0 and plays a
    ``$ persistent`` line, and the folder is left as it was."""
    game = game_of(tmp_path, FESTIVALS)
    _festivals_file(game)
    before = tree(game / "persistent")
    found = {}
    once_ready(scripted_app, lambda app: found.update(
        mode=app.persist.mode, festivals=app.persist.store.peek("festivals"),
        x=app.persist.store.peek("x")))
    scripted_app.quit_frame = 40
    assert cli.main(["run", str(game), "--no-persistent", *extra]) == 0
    assert found == {"mode": MEMORY, "festivals": 0, "x": 1}
    assert tree(game / "persistent") == before
    infos = [r for r in log_of(game) if r[2] == OFF_TEXT]
    assert [r[0] for r in infos] == ["INFO"]


def test_ac32_no_persistent_creates_no_folder(tmp_path, user_roots, scripted_app):
    game = game_of(tmp_path, FESTIVALS)
    once_ready(scripted_app, lambda app: None)
    scripted_app.quit_frame = 40
    assert cli.main(["run", str(game), "--no-persistent"]) == 0
    assert not (game / "persistent").exists()


def test_ac32_release_refuses_no_persistent(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", str(tmp_path), "--release", "--no-persistent"])
    assert exit_info.value.code == 2
    assert "--no-persistent is only available in dev runs" in capsys.readouterr().err


def test_ac32_a_frozen_build_has_no_such_option(tmp_path, capsys, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", str(tmp_path), "--no-persistent"])
    assert exit_info.value.code == 2
    assert "unrecognized arguments: --no-persistent" in capsys.readouterr().err


def test_ac32_release_without_an_id_gives_w53_and_plays(tmp_path, user_roots, scripted_app):
    game = game_of(tmp_path)
    found = {}
    once_ready(scripted_app, lambda app: found.update(mode=app.persist.mode))
    scripted_app.quit_frame = 40
    assert launch(game, release=True) == 0
    assert found == {"mode": MEMORY}
    assert not (game / "persistent").exists()
    assert not any(user_roots.appdata.rglob("persistent"))
    logged = [r for r in records(next(user_roots.home.rglob("latest.log")))
              if r[2] == NO_ID_TEXT]
    assert [r[0] for r in logged] == ["WARNING"]


def test_the_cli_passes_no_persistent_to_the_app(tmp_path, user_roots, scripted_app):
    game = game_of(tmp_path)
    scripted_app.quit_frame = 4
    assert cli.main(["run", str(game), "--no-persistent"]) == 0
    assert scripted_app.apps[-1].no_persistent is True
    assert cli.main(["run", str(game)]) == 0
    assert scripted_app.apps[-1].no_persistent is False


# --- AC-F12-35 — orderly ends and one writer -------------------------------------------------

def test_ac35_story_end_writes_at_the_next_frame(tmp_path, user_roots, scripted_app):
    """A change just before ``StoryEnded`` (well inside the 1 s interval) is written by the
    frame after the end, not at quit (``flush_soon``)."""
    game = game_of(tmp_path, 'label start:\n    "Start."\n    return\n')
    seen = {}

    def change_and_end(app):
        app.persist.last_start = app.clock()      # the 1 s interval isn't due
        app.persist.store.set("x", 1)
        post_key(pygame.K_SPACE)

    frames = once_ready(scripted_app, change_and_end)

    def look(app):
        if frames and "frame" not in seen and app.story.status.name == "ENDED":
            path = game / "persistent" / FILE_NAME
            seen.update(frame=scripted_app.limiters[-1].frame,
                        values=json.loads(path.read_bytes())["values"] if path.exists() else None)

    for f in range(2, 120):
        scripted_app.at(f, look)
    scripted_app.quit_frame = 120
    assert launch(game) == 0
    assert seen["values"] == {"x": 1, "playthrough": 0} and seen["frame"] == frames[0] + 1


def test_ac35_an_error_screen_shows_after_the_write(tmp_path, user_roots, scripted_app,
                                                    monkeypatch):
    """``$ persistent.x = 1`` then an author error in the same burst."""
    game = game_of(tmp_path, 'label start:\n    "Start."\n    $ persistent.x = 1\n'
                             '    $ y = 1 / 0\n    return\n')
    order = []
    real_draw = ErrorScreen.draw

    def draw(self, canvas):
        if not order:
            path = game / "persistent" / FILE_NAME
            order.append(json.loads(path.read_bytes())["values"] if path.exists() else None)
        real_draw(self, canvas)

    monkeypatch.setattr(ErrorScreen, "draw", draw)

    def change_and_fail(app):
        app.persist.last_start = app.clock()      # the 1 s interval isn't due
        post_key(pygame.K_SPACE)

    once_ready(scripted_app, change_and_fail)
    scripted_app.quit_frame = 60
    assert launch(game) == 1
    assert order == [{"x": 1, "playthrough": 0}]


def test_ac35_a_failing_flush_never_keeps_the_error_screen_away(tmp_path, user_roots,
                                                               scripted_app, monkeypatch):
    game = game_of(tmp_path, 'label start:\n    "Start."\n    $ y = 1 / 0\n    return\n')

    def broken(self, until=None):
        raise RuntimeError("flush broke")

    monkeypatch.setattr(PersistentSync, "flush_now", broken)
    once_ready(scripted_app, lambda app: post_key(pygame.K_SPACE))
    scripted_app.quit_frame = 60
    assert launch(game) == 1
    app = scripted_app.apps[-1]
    assert isinstance(app.screens.top, ErrorScreen) and app.error_mode


def _quit_by(session, how: str):
    def action(app):
        app.persist.last_start = app.clock()      # unwritten when the quit comes
        app.persist.store.set("x", 1)
        if how == "request_quit":
            app.request_quit(force=True)
        elif how == "ctrl-c":
            raise KeyboardInterrupt
        else:                                     # closed now (and again: F10 asks first)
            limiter = session.limiters[-1]
            limiter.quit_at(limiter.frame)
    return action


@pytest.mark.parametrize("how", ["window-close", "request_quit", "ctrl-c"])
def test_ac35_quit_closes_before_audio_and_leaves_no_thread(tmp_path, user_roots, scripted_app,
                                                           monkeypatch, how):
    """Threaded writer."""
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", True)
    game = game_of(tmp_path)
    order = []
    real_close = PersistentSync.close
    real_shutdown = AudioService.shutdown
    monkeypatch.setattr(PersistentSync, "close",
                        lambda self, until=None: order.append("close") or real_close(self, until))
    monkeypatch.setattr(AudioService, "shutdown",
                        lambda self: order.append("audio") or real_shutdown(self))
    frames = once_ready(scripted_app, _quit_by(scripted_app, how))
    scripted_app.quit_frame = 200
    before = set(threading.enumerate())          # another test's leftovers are not ours
    assert launch(game) == 0
    app = scripted_app.apps[-1]
    assert frames and order == ["close", "audio"]
    assert disk(game)["values"] == {"x": 1, "playthrough": 0}   # F32 built-in
    assert app.writer.started and not app.writer.alive
    assert not [t for t in threading.enumerate()
                if t.name.startswith("vn-writer") and t not in before]


def test_ac35_a_final_write_past_the_deadline_is_skipped(tmp_path, user_roots, scripted_app,
                                                        monkeypatch):
    """Threaded writer, ``CLOSE_WAIT_S`` patched to 0.2 s, fsync sleeping 0.5 s off the main
    thread: quit returns within 0.7 s, the file is whole (old or new), W52 says so."""
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", True)
    monkeypatch.setattr(limits, "CLOSE_WAIT_S", 0.2)
    from engine.core import safefile
    real_fsync = safefile.os.fsync

    def slow_fsync(fd):
        if threading.current_thread() is not threading.main_thread():
            time.sleep(0.5)
        real_fsync(fd)

    game = game_of(tmp_path)
    (game / "persistent").mkdir()
    old = json.dumps({"format": 1, "identity_scheme": 1, "values": {"x": 0}, "seen": {},
                      "chosen": {}, "unlocks": {}}, separators=(",", ":")).encode("ascii")
    (game / "persistent" / FILE_NAME).write_bytes(old)
    timing = {}
    real_close_writers = App._close_writers

    def close_writers(self):
        start = time.monotonic()
        real_close_writers(self)
        timing["close"] = time.monotonic() - start

    monkeypatch.setattr(App, "_close_writers", close_writers)

    def change(app):
        monkeypatch.setattr(safefile.os, "fsync", slow_fsync)
        app.persist.store.set("x", 1)             # written now: the fsync sleeps
        app.persist.update(app.clock())
        assert app.persist.in_flight
        app.persist.store.set("x", 2)
        app.request_quit(force=True)

    once_ready(scripted_app, change)
    scripted_app.quit_frame = 200
    try:
        assert launch(game) == 0
    finally:
        thread = scripted_app.apps[-1].writer._thread
        if thread is not None:
            thread.join(5)
    assert timing["close"] <= 0.2 + 0.5
    data = (game / "persistent" / FILE_NAME).read_bytes()
    assert json.loads(data)["values"] in ({"x": 0}, {"x": 0, "playthrough": 0},
                                         {"x": 1, "playthrough": 0})
    skipped = [r for r in log_of(game) if r[2] == final_write_skipped_text(FILE)]
    assert [r[0] for r in skipped] == ["WARNING"]


def test_no_persist_update_in_error_mode(tmp_path, user_roots, scripted_app, monkeypatch):
    game = game_of(tmp_path, 'label start:\n    "Start."\n    $ y = 1 / 0\n    return\n')
    calls = []
    real_update = PersistentSync.update
    monkeypatch.setattr(PersistentSync, "update", lambda self, now: calls.append(
        scripted_app.apps[-1].error_mode) or real_update(self, now))
    once_ready(scripted_app, lambda app: post_key(pygame.K_SPACE))
    scripted_app.quit_frame = 30
    assert launch(game) == 1
    assert calls and not any(calls)
    assert scripted_app.apps[-1].error_mode


# --- AC-F12-36 (App row) — a full session leaves only the file -------------------------------

def test_ac36_a_full_session_in_the_app_leaves_only_the_file(tmp_path, user_roots, scripted_app):
    game = game_of(tmp_path)
    count = [0]

    def change(app):
        if app.persist is not None and not app.loading and count[0] < 20:
            app.persist.store.set(f"n{count[0]}", count[0])
            count[0] += 1

    for f in range(2, 120, 3):
        scripted_app.at(f, change)
    scripted_app.quit_frame = 120
    assert launch(game) == 0
    assert count[0] == 20
    assert [p.name for p in (game / "persistent").iterdir()] == [FILE_NAME]
    assert disk(game)["values"] == {**{f"n{i}": i for i in range(20)}, "playthrough": 0}


def test_a_launch_error_installs_no_persistence(tmp_path, user_roots, scripted_app):
    """A launch failure comes before ``install_persistence``: no sync, nothing written."""
    game = game_of(tmp_path, 'define a = 1 / 0\nlabel start:\n    "Start."\n')
    scripted_app.quit_frame = 20
    assert launch(game) == 1
    app = scripted_app.apps[-1]
    assert app.persist is None and isinstance(app.screens.top, ErrorScreen)
    assert list((game / "persistent").iterdir()) == []


def test_the_load_screen_warms_the_encoder_before_the_hand_over(tmp_path, user_roots,
                                                                scripted_app):
    """A big store (60,000 seen lines) is warm when the game starts (F12 step 5's hand-off:
    otherwise its first write waits thousands of frames)."""
    game = game_of(tmp_path)
    seen = {f"l{i}": " ".join(f"{i * 1000 + k:012x}" for k in range(1000)) for i in range(60)}
    (game / "persistent").mkdir()
    (game / "persistent" / FILE_NAME).write_bytes(json.dumps(
        {"format": 1, "identity_scheme": 1, "values": {}, "seen": seen, "chosen": {},
         "unlocks": {}}).encode("ascii"))
    found = {}
    once_ready(scripted_app, lambda app: found.update(warm=app.persist.encoder.is_warm,
                                                      screen=type(app.screens.top)))
    scripted_app.quit_frame = 40
    assert launch(game) == 0
    assert found["warm"] is True and found["screen"] is not StoryLoadScreen


def test_sec12_launch_warnings_reach_the_notice_layer(tmp_path, user_roots, scripted_app,
                                                      monkeypatch):
    """SEC-F12-12 through F11's ``forward_launch_notices``: the launch's W50 shows once as
    the ``notice_persistent`` word, a problem notice (the log has the full text)."""
    game = game_of(tmp_path)
    (game / "persistent").mkdir()
    (game / "persistent" / FILE_NAME).write_bytes(b"{")
    shown = []
    real_notify = GameShell.notify

    def notify(self, text, *, kind="info"):
        shown.append((text, kind))
        real_notify(self, text, kind=kind)

    monkeypatch.setattr(GameShell, "notify", notify)
    found = once_ready(scripted_app, lambda app: None)
    scripted_app.quit_frame = 40
    assert launch(game) == 0
    assert found and shown == [(WordsConfig().notice_persistent, "problem")]
    assert [r[0] for r in log_of(game) if "couldn't be used" in r[2]] == ["WARNING"]


def test_the_writer_thread_starts_before_the_first_frame_of_the_game(tmp_path, user_roots,
                                                                    scripted_app, monkeypatch):
    """AC-F12-45: ``install_persistence`` starts the writer in the load screen's slice, so
    the first write only queues its job."""
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", True)
    game = game_of(tmp_path)
    found = {}
    once_ready(scripted_app, lambda app: found.update(started=app.writer.alive,
                                                      writes=app.persist.requests))
    scripted_app.quit_frame = 40
    assert launch(game) == 0
    assert found == {"started": True, "writes": 0}


def test_ac29_a_newer_file_is_never_changed_by_a_story(tmp_path, user_roots, scripted_app):
    """AC-F12-29 with the story's own lines (``tests/persist/test_launch.py`` has the sync's
    rows): ``$ persistent.x = 1``, ``$ persistent._clear()``, the story's end
    (``flush_soon``), and quit (``close``) leave a ``format`` 2 file as it was."""
    game = game_of(tmp_path, 'label start:\n    $ persistent.x = 1\n    $ persistent._clear()\n'
                             '    $ persistent.x = 1\n    "Start."\n    return\n')
    (game / "persistent").mkdir()
    data = json.dumps({"format": 2, "identity_scheme": 1, "values": {"festivals": 2},
                       "seen": {}, "chosen": {}, "unlocks": {}}).encode("ascii")
    (game / "persistent" / FILE_NAME).write_bytes(data)
    found = {}

    def look_and_end(app):
        found.update(x=app.persist.store.peek("x"), festivals=app.persist.store.peek("festivals"))
        post_key(pygame.K_SPACE)

    once_ready(scripted_app, look_and_end)
    scripted_app.quit_frame = 60
    assert launch(game) == 0
    assert found == {"x": 1, "festivals": Missing}
    assert tree(game / "persistent") == {FILE_NAME: data}
    assert [r[0] for r in log_of(game) if "newer engine version" in r[2]] == ["WARNING"]
