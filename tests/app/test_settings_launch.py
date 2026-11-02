"""F16 settings at launch and quit, in-process (checklist step 2; ``04`` §7.1, §7.6, §7.8;
``07`` §3, G10, I-14): the milestone (fullscreen and window size survive a relaunch),
AC-F16-07 (where the file lives; no file without an id; headless runs), AC-F16-15 (quit
order), AC-F16-18 (the window starts in the stored mode and size), AC-F16-19 (five
launch–quit cycles keep the size), and the frame slot.

Launch L (06 §0.2): ``bootstrap.launch`` under ``scripted_app`` (fake frame clock, hidden
``SpyWindow``), with the display scale and work area patched. The writer is synchronous
unless a test says "threaded".
"""

import json
import threading
import time
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app import platform as osinfo
from engine.app import settings as settings_mod
from engine.app.app import App
from engine.app.settings import NO_ID_TEXT, SettingsService, save_failed_text
from engine.core import constants, safefile
from engine.core.geometry import initial_window_size
from engine.core.paths import GamePaths, user_data_dir
from engine.persist import limits
from engine.persist.settings_file import FILE_NAME, encode_settings, settings_root
from engine.persist.sync import PersistentSync
from engine.runtime.headless import run_headless
from engine.script import load_story
from tests.app.test_persistence_app import game_of, ready
from tests.app.test_story_load_screen import records
from tests.fakes.loop import post_key
from tests.fakes.spy_window import SpyWindow

pytestmark = pytest.mark.display

WORK_AREA = (1920, 1040)
SETTINGS_FILE = "<game>/settings/settings.json"


@pytest.fixture(autouse=True)
def display(monkeypatch):
    monkeypatch.setattr(osinfo, "system_display_scale", lambda: 1.0)
    monkeypatch.setattr(osinfo, "primary_work_area", lambda: WORK_AREA)
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", False)


def make_game(parent: Path, config: str = "", *, values=None, name: str = "game") -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / "config.toml").write_text(config, encoding="utf-8")
    if values is not None:
        (root / "settings").mkdir()
        (root / "settings" / FILE_NAME).write_bytes(encode_settings(values))
    return root


def launch(game: Path, *, release: bool = False) -> int:
    return bootstrap.launch(game, release=release, bench_seconds=None,
                            log_level_override=None, pygame_warning=None)


def stored(game: Path) -> dict:
    return json.loads((game / "settings" / FILE_NAME).read_bytes())["values"]


def created() -> list[dict]:
    return [entry[1] for entry in SpyWindow.log if entry[0] == "create"]


def before_first_flip() -> list[str]:
    """The window calls before the first frame (attribute sets left out)."""
    names = []
    for entry in SpyWindow.log:
        if entry[0] == "flip":
            break
        if not entry[0].startswith("set "):
            names.append(entry[0])
    return names


# --- Milestone: fullscreen and window size survive a relaunch -------------------------------------

def test_milestone_fullscreen_and_size_survive_a_relaunch(tmp_path, user_roots, scripted_app):
    game = make_game(tmp_path)

    def resize(app):                     # the player drags the window to 1500x844
        app.window._window.size = (1500, 844)
        app.window.note_window_event(pygame.WINDOWSIZECHANGED)

    scripted_app.at(2, resize)
    scripted_app.at(3, lambda app: post_key(pygame.K_F11))
    scripted_app.quit_frame = 6
    assert launch(game) == 0
    assert stored(game) == {"fullscreen": True, "window_size": [1500, 844]}
    assert scripted_app.apps[-1].settings.stored == {"fullscreen": True,
                                                     "window_size": (1500, 844)}

    scripted_app.actions.clear()
    SpyWindow.log = []
    assert launch(game) == 0
    assert created()[0]["size"] == initial_window_size((1500, 844), 1.0, WORK_AREA)
    assert before_first_flip()[:2] == ["create", "set_fullscreen"]   # no windowed frame
    app = scripted_app.apps[-1]
    assert app.window.fullscreen and app.settings.value("fullscreen") is True
    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert [r for r in problems if r[1] == "setting"] == []


# --- AC-F16-18 — the window starts in the stored mode and size --------------------------------------

def test_ac18_stored_fullscreen_opens_fullscreen(tmp_path, user_roots, scripted_app):
    game = make_game(tmp_path, values={"fullscreen": True})
    assert launch(game) == 0
    assert before_first_flip()[:2] == ["create", "set_fullscreen"]
    assert scripted_app.apps[-1].window.fullscreen


@pytest.mark.parametrize("size, work", [((1600, 900), WORK_AREA), ((7680, 4320), (1920, 1080))])
def test_ac18_stored_size_is_fitted_like_the_config_size(tmp_path, user_roots, scripted_app,
                                                         monkeypatch, size, work):
    monkeypatch.setattr(osinfo, "primary_work_area", lambda: work)
    game = make_game(tmp_path, values={"window_size": size})
    assert launch(game) == 0
    assert created()[0]["size"] == initial_window_size(size, 1.0, work)
    assert "set_fullscreen" not in before_first_flip()


def test_ac18_no_file_uses_the_config(tmp_path, user_roots, scripted_app):
    game = make_game(tmp_path, "[window]\nwidth = 1600\nheight = 900\nfullscreen = true\n")
    assert launch(game) == 0
    assert created()[0]["size"] == (1600, 900)
    assert before_first_flip()[:2] == ["create", "set_fullscreen"]
    assert not (game / "settings").exists()       # nothing changed: nothing written


# --- AC-F16-19 — five launch-quit cycles keep the size ----------------------------------------------

def test_ac19_size_is_kept_across_launches(tmp_path, user_roots, scripted_app, monkeypatch):
    """AC-F16-19: five launch-quit cycles keep the stored size; each cycle runs at a
    different display scale (1.0, 1.25, 1.5, 2.0, 1.25), so the scale never leaks into
    the stored size."""
    monkeypatch.setattr(osinfo, "primary_work_area", lambda: (4000, 3000))
    game = make_game(tmp_path, values={"window_size": (1600, 900)})
    scripted_app.quit_frame = 2
    for scale in (1.0, 1.25, 1.5, 2.0, 1.25):
        monkeypatch.setattr(osinfo, "system_display_scale", lambda scale=scale: scale)
        SpyWindow.log = []
        assert launch(game) == 0
        assert created()[0]["size"] == (round(1600 * scale), round(900 * scale)), scale
        assert stored(game) == {"window_size": [1600, 900]}


# --- AC-F16-07 — where the file lives, and when there is none ---------------------------------------

def test_ac07_settings_root(tmp_path, user_roots):
    game = tmp_path / "game"
    assert settings_root(game_root=game, release=False, app_id=None) == game / "settings"
    assert settings_root(game_root=game, release=True, app_id="paper-lanterns") == \
        user_data_dir("paper-lanterns") / "settings"
    assert settings_root(game_root=game, release=True, app_id=None) is None
    assert "settings" in constants.SAVE_DIRNAMES


def test_ac07_release_without_an_id_reads_and_writes_nothing(tmp_path, user_roots,
                                                             scripted_app, monkeypatch):
    calls = []
    monkeypatch.setattr(settings_mod, "read_settings",
                        lambda *a, **k: calls.append(a))          # never called
    game = make_game(tmp_path, '[game]\ntitle = "No Id"\n')

    def change(app):
        for second in range(10):
            app.settings.set("music_volume", 40 + second)
            app.settings.set("fullscreen", second % 2 == 0)
            app.settings.update(app.clock() + second + 1.0)

    scripted_app.at(2, change)
    assert launch(game, release=True) == 0
    assert calls == []
    w74 = [r for r in records(user_logs(user_roots)) if r[2] == NO_ID_TEXT]
    assert [r[:2] for r in w74] == [("WARNING", "setting")]
    assert not list(Path(user_roots.home).rglob("settings")) and not (game / "settings").exists()


def user_logs(user_roots) -> Path:
    return next(Path(user_roots.home).rglob("latest.log"))


def test_ac07_headless_runs_have_no_settings(tmp_path, user_roots):
    game = game_of(tmp_path)
    (game / "settings").mkdir()
    target = game / "settings" / FILE_NAME
    target.write_bytes(encode_settings({"music_volume": 40}))
    before = (target.read_bytes(), target.stat().st_mtime_ns, sorted(p.name for p in
                                                                     (game / "settings").iterdir()))
    program = load_story(GamePaths.for_game(game)).program
    run_headless(program, seed=1)
    after = (target.read_bytes(), target.stat().st_mtime_ns, sorted(p.name for p in
                                                                    (game / "settings").iterdir()))
    assert after == before


def test_a_fatal_startup_reads_no_settings(tmp_path, user_roots, scripted_app, monkeypatch):
    calls = []
    monkeypatch.setattr(settings_mod, "read_settings", lambda *a, **k: calls.append(a))
    game = make_game(tmp_path, "[window]\nwidth = 1\n", values={"fullscreen": True})
    assert launch(game) == 1                         # the error screen; closing it is exit 1
    assert calls == [] and "set_fullscreen" not in before_first_flip()
    app = scripted_app.apps[-1]
    assert app.settings is not None and not app.settings.writable


# --- The frame slot (I-14) ------------------------------------------------------------------------

def test_the_frame_slot_runs_after_persist_and_before_audio(tmp_path, user_roots, scripted_app,
                                                            monkeypatch):
    order = []
    real_update = SettingsService.update
    monkeypatch.setattr(SettingsService, "update",
                        lambda self, now: order.append("settings") or real_update(self, now))
    monkeypatch.setattr(App, "_update_persist", lambda self: order.append("persist"))
    real_audio = App._update_audio
    monkeypatch.setattr(App, "_update_audio",
                        lambda self: order.append("audio") or real_audio(self))
    game = make_game(tmp_path)
    scripted_app.at(2, lambda app: app.show_fatal_error(RuntimeError("boom")))
    scripted_app.quit_frame = 4
    launch(game)
    assert order[:3] == ["persist", "settings", "audio"]
    assert order.count("settings") == order.count("audio") >= 3     # error mode too


# --- AC-F16-15 — quit order ------------------------------------------------------------------------

def test_ac15_quit_order_with_persistent_data(tmp_path, user_roots, scripted_app, monkeypatch):
    game = game_of(tmp_path)
    order: list[str] = []
    names: list[str] = []
    real_write = safefile.write_atomic

    def spy_write(target, pieces, **kwargs):
        names.append(Path(target).name)
        return real_write(target, pieces, **kwargs)

    monkeypatch.setattr(safefile, "write_atomic", spy_write)
    for name in ("submit_final", "wait_final"):
        real = getattr(SettingsService, name)
        monkeypatch.setattr(SettingsService, name,
                            lambda self, *a, _real=real, _name=name: order.append(_name)
                            or _real(self, *a))
    real_close = PersistentSync.close
    monkeypatch.setattr(PersistentSync, "close", lambda self, until=None: order.append(
        "close") or real_close(self, until))
    state = {}

    def step(app):
        frame = scripted_app.limiters[-1].frame
        if "start" not in state and ready(app):
            state["start"] = frame
            app.settings.set("music_volume", 40)
        elif state.get("start") is not None and frame == state["start"] + 6:   # 0.1 s later
            app.persist.store.set("x", 1)
            app.persist.update(app.clock())          # written now
            app.persist.store.set("x", 2)            # left for the final write
            names.clear()
            app.request_quit(force=True)

    for frame in range(2, 200):
        scripted_app.at(frame, step)
    scripted_app.quit_frame = 200
    assert launch(game) == 0
    assert order == ["submit_final", "close", "wait_final"]
    assert names == ["settings.json", "persistent.json"]
    assert stored(game) == {"music_volume": 40}


def test_ac15_a_stalled_write_ends_by_the_deadline(tmp_path, user_roots, scripted_app,
                                                   monkeypatch):
    """Threaded writer, ``CLOSE_WAIT_S`` patched to 0.2 s, fsync sleeping 0.5 s off the main
    thread: quit returns within 0.7 s, W75 ``couldn't write``, the file absent or whole."""
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", True)
    monkeypatch.setattr(limits, "CLOSE_WAIT_S", 0.2)
    real_fsync = safefile.os.fsync

    def slow_fsync(fd):
        if threading.current_thread() is not threading.main_thread():
            time.sleep(0.5)
        real_fsync(fd)

    timing = {}
    real_close_writers = App._close_writers

    def close_writers(self):
        start = time.monotonic()
        real_close_writers(self)
        timing["close"] = time.monotonic() - start

    monkeypatch.setattr(App, "_close_writers", close_writers)
    game = make_game(tmp_path)

    def change(app):
        monkeypatch.setattr(safefile.os, "fsync", slow_fsync)
        app.settings.set("music_volume", 40)

    scripted_app.at(2, change)
    scripted_app.quit_frame = 3
    try:
        assert launch(game) == 0
    finally:
        thread = scripted_app.apps[-1].writer._thread
        if thread is not None:
            thread.join(5)
    assert timing["close"] <= 0.2 + 0.5
    target = game / "settings" / FILE_NAME
    assert not target.exists() or stored(game) == {"music_volume": 40}
    w75 = [r for r in records(game / "logs" / "latest.log")
           if r[2] == save_failed_text(SETTINGS_FILE, "couldn't write")]
    assert [r[:2] for r in w75] == [("WARNING", "setting")]
