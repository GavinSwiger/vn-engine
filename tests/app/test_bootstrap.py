"""The startup sequence up to the log file (§7.1 steps 6–10, 18), run in-process.

AC-F01-63 (log in the game folder), 66 (locked log), 75 (release runs log per user), 126
(integration part), 127 (early records reach the file), 128 (early records redacted), 130
(nothing written before the folder is chosen), 131 (console-only release runs discard the
buffer), 146 (planted links in the per-user folder); the parts of AC-F01-74 and 129 that
exist before the error screen (Step 8). Steps 6–7 launch tests are in
``test_launch_window.py``.
"""

import hashlib
import inspect
import logging
import os
import re
import sys
from pathlib import Path

import pytest

from engine.app import bootstrap
from engine.core import logsetup, paths
from engine.core.logsetup import LogSetup
from engine.core.paths import user_log_dir

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def _quit_after_a_few_frames(scripted_app):
    """Every launch() here runs a few frames and quits (see tests/app/conftest.py)."""
    return scripted_app

HEADER_1 = re.compile(
    r"^vn-engine 0\.1\.0 \| Python \d+\.\d+\.\d+ \| pygame-ce \d+\.\d+\.\d+ "
    r"\(SDL \d+\.\d+\.\d+\) \| .+ \| build (dev|release)$")
NOT_FOUND = "config.toml not found — using default settings"
FALLBACK = " (fallback folder: [game] id is not set)"
NOT_REGULAR = "logs/latest.log is not a regular file — rotation skipped"
ROTATE_FAILED = "Could not rotate latest.log (it may be open in another copy of the game)"
NOT_AVAILABLE = "not available (the log folder could not be written)"


def launch(game_dir: Path, *, release: bool = False, log_level: str | None = None) -> int:
    return bootstrap.launch(game_dir, release=release, bench_seconds=None,
                            log_level_override=log_level, pygame_warning=None)


def make_game(parent: Path, name: str = "game", config: str | None = "") -> Path:
    root = parent / name
    root.mkdir(parents=True)
    if config is not None:
        (root / "config.toml").write_text(config, encoding="utf-8")
    return root


def messages(log_file: Path) -> list[str]:
    """The message part of each timestamped line (traceback lines are skipped)."""
    out = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ", line):
            out.append(line[40:])
    return out


def snapshot(*folders: Path) -> dict[str, tuple[int, int, str]]:
    found = {}
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            st = os.lstat(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest() \
                if path.is_file() and not path.is_symlink() else ""
            found[str(path)] = (st.st_size if path.is_file() else 0, st.st_mtime_ns, digest)
    return found


def vn_engine_dir() -> Path:
    """The per-user ``vn-engine`` folder for this platform (under the test roots)."""
    log_dir = user_log_dir("probe")
    return next(p for p in log_dir.parents if p.name == "vn-engine")


# --- AC-F01-63: the log is written in the game folder ----------------------------------------

def test_dev_run_logs_in_the_game_folder(tmp_path, user_roots):
    game = make_game(tmp_path)
    assert launch(game) == 0
    log_file = game / "logs" / "latest.log"
    lines = messages(log_file)
    assert HEADER_1.match(lines[0]) and lines[0].endswith("build dev")
    assert "Log: <game>/logs/latest.log" in lines
    assert lines[-1] == "Clean shutdown (exit code 0)"
    assert not (user_roots.localappdata / "vn-engine").exists()


def test_log_level_from_config_and_override(tmp_path, user_roots):
    game = make_game(tmp_path, config='[engine]\nlog_level = "error"\nunknown_key = 1\n')
    assert launch(game) == 0
    text = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    # The unknown-key WARNING was buffered before the configured level applied.
    assert "unknown key" in text
    assert text.rstrip().endswith("Clean shutdown (exit code 0)")


# --- AC-F01-127: early records reach the file ------------------------------------------------

@pytest.mark.parametrize("release", [False, True])
def test_records_before_config_reach_the_log(tmp_path, user_roots, capsys, release):
    game = make_game(tmp_path, "my game", config=None)
    assert launch(game, release=release) == 0
    log_file = (user_log_dir("my-game") if release else game / "logs") / "latest.log"
    lines = messages(log_file)
    assert lines.count(NOT_FOUND) == 1
    header_2 = next(i for i, line in enumerate(lines) if line.startswith("Log: "))
    assert HEADER_1.match(lines[0])
    assert 0 < lines.index(NOT_FOUND) < header_2
    assert NOT_FOUND in capsys.readouterr().err
    if release:
        assert lines[header_2].endswith(FALLBACK)
        assert not (game / "logs").exists()


# --- AC-F01-66: a locked log does not stop the game -------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="only Windows locks open files")
def test_locked_latest_log(tmp_path, user_roots):
    game = make_game(tmp_path)
    logs = game / "logs"
    logs.mkdir()
    (logs / "latest.log").write_text("2026-10-30 09:15:02.120 INFO    app     other copy\n")
    with open(logs / "latest.log", "a"):
        assert launch(game) == 0
    pid_log = logs / f"latest-{os.getpid()}.log"
    lines = messages(pid_log)
    assert lines.count(ROTATE_FAILED) == 1
    assert f"Log: <game>/logs/latest-{os.getpid()}.log" in lines


# --- AC-F01-74 (part): no usable log folder in a dev run -------------------------------------
# (the per-user fallback with its exact display path is in test_error_mode.py)

def test_dev_run_with_no_usable_folder_still_starts(tmp_path, user_roots):
    game = make_game(tmp_path, "vn test")
    (game / "logs").write_text("not a folder")
    vn_engine_dir().parent.mkdir(parents=True, exist_ok=True)
    vn_engine_dir().write_text("a file")
    before = snapshot(tmp_path)
    captured = {}
    real_open = LogSetup.open_file

    def spy(self, candidates):
        session = real_open(self, candidates)
        captured["session"] = session
        return session

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(LogSetup, "open_file", spy)
        assert launch(game) == 0
    assert captured["session"].display_path == NOT_AVAILABLE
    assert snapshot(tmp_path) == before


# --- AC-F01-75: release runs log to the per-user folder ------------------------------------------

@pytest.fixture
def data_dir_calls(monkeypatch):
    """Every call of ``user_data_dir``, with the name of the calling function."""
    calls = []
    real = paths.user_data_dir

    def spy(app_id):
        calls.append((app_id, inspect.stack()[1].function))
        return real(app_id)

    monkeypatch.setattr(paths, "user_data_dir", spy)
    return calls


def _assert_only_log_dirs(calls):
    if sys.platform == "win32":
        assert calls == []
    else:
        assert all(caller == "user_log_dir" for _, caller in calls)


@pytest.mark.parametrize("folder, app_id", [
    ("My Game!", "my-game"),
    ("マイゲーム", "game"),
    pytest.param("CON", "con-game", marks=pytest.mark.skipif(
        sys.platform == "win32", reason="CON cannot be a folder name on Windows")),
])
def test_release_run_with_fallback_id(tmp_path, user_roots, data_dir_calls, folder, app_id):
    game = make_game(tmp_path, folder)
    before = snapshot(game)
    assert launch(game, release=True) == 0
    lines = messages(user_log_dir(app_id) / "latest.log")
    assert lines[0].endswith("build release")
    header_2 = next(line for line in lines if line.startswith("Log: "))
    assert header_2.endswith(FALLBACK)
    assert not (game / "logs").exists()
    assert snapshot(game) == before
    _assert_only_log_dirs(data_dir_calls)
    for name in ("saves", "persistent"):
        assert not list(tmp_path.rglob(name))


def test_release_run_with_configured_id(tmp_path, user_roots, data_dir_calls):
    game = make_game(tmp_path, "My Game!", config='[game]\nid = "my-vn"\n')
    before = snapshot(game)
    assert launch(game, release=True) == 0
    lines = messages(user_log_dir("my-vn") / "latest.log")
    header_2 = next(line for line in lines if line.startswith("Log: "))
    assert not header_2.endswith(FALLBACK)
    if sys.platform == "win32":
        assert header_2 == "Log: %LOCALAPPDATA%\\vn-engine\\my-vn\\logs\\latest.log"
    assert not list(user_roots.home.rglob("my-game"))
    assert snapshot(game) == before
    _assert_only_log_dirs(data_dir_calls)


# --- AC-F01-126 (integration part) -----------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="LOCALAPPDATA is a Windows variable")
def test_release_run_without_localappdata_logs_in_the_game_folder(tmp_path, user_roots,
                                                                  monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA")
    game = make_game(tmp_path)
    assert launch(game, release=True) == 0
    assert "Log: <game>/logs/latest.log" in messages(game / "logs" / "latest.log")


# --- AC-F01-128: early records are redacted when buffered ------------------------------------------

def test_early_records_are_redacted(tmp_path, user_roots, monkeypatch, capsys):
    game = make_game(tmp_path, "my game", config=None)
    home = user_roots.home
    real_load = bootstrap.load_config
    stored = []

    def wrapped(game_paths):
        result = real_load(game_paths)
        log = logging.getLogger("vn.config")
        log.warning("x %s", str(home / "a"))
        try:
            raise OSError(f"cannot open {home / 'secret' / 'file.txt'}")
        except OSError:
            log.error("load failed", exc_info=True)
        buffer = logsetup._active.early_buffer
        stored.extend(buffer.items)
        return result

    tail = []
    real_close = LogSetup.close

    def close_spy(self):
        tail.extend(self.tail)
        real_close(self)

    monkeypatch.setattr(bootstrap, "load_config", wrapped)
    monkeypatch.setattr(LogSetup, "close", close_spy)
    assert launch(game, release=True) == 0
    log_file = user_log_dir("my-game") / "latest.log"
    text = log_file.read_text(encoding="utf-8")
    lines = messages(log_file)
    header_2 = next(i for i, line in enumerate(lines) if line.startswith("Log: "))
    x_line = next(i for i, line in enumerate(lines) if line.startswith("x "))
    error_line = lines.index("load failed")
    assert lines[x_line] in ("x ~/a", "x ~\\a")
    assert x_line < error_line < header_2
    assert lines.index(NOT_FOUND) < header_2
    assert "Traceback" in text
    # Only text was stored, already redacted.
    assert stored and all(isinstance(flag, bool) and isinstance(item, str)
                          for flag, item in stored)
    assert all("qauser7" not in item.lower() for _, item in stored)
    assert any("load failed" in line for line in tail)
    for channel in (text, capsys.readouterr().err, "\n".join(tail)):
        _privacy_check(channel, home, game)


def _privacy_check(text: str, home: Path, game: Path) -> None:
    lowered = text.lower()
    assert "qauser7" not in lowered
    for root in (home, game.resolve()):
        for form in (str(root), root.as_posix(), str(root).replace("\\", "\\\\")):
            assert form.lower() not in lowered


# --- AC-F01-129 (part): the early buffer is bounded ------------------------------------------------

@pytest.mark.parametrize("key_count", [3_000, pytest.param(60_000, marks=pytest.mark.slow)])
def test_early_buffer_is_bounded(tmp_path, user_roots, monkeypatch, key_count):
    """3,000 unknown keys already overflow the 1,000-record bound; the AC's 60,000 (about
    4 s) runs in the ``slow`` tier."""
    keys = "".join(f"k{i:05d} = 1\n" for i in range(1, key_count + 1))
    game = make_game(tmp_path, config="[game]\n" + keys)
    assert len((game / "config.toml").read_bytes()) < 1_048_576
    counts = {"early": 0, "open": False}
    bounds = {}

    class Counter(logging.Handler):
        def emit(self, record):
            if not counts["open"] and not getattr(record, "lifecycle", False):
                counts["early"] += 1

    real_open = LogSetup.open_file

    def spy(self, candidates):
        buffer = self.early_buffer
        bounds.update(records=buffer.records, bytes=buffer.bytes, dropped=buffer.dropped)
        session = real_open(self, candidates)
        counts["open"] = True
        return session

    counter = Counter()
    logging.getLogger("vn").addHandler(counter)
    monkeypatch.setattr(LogSetup, "open_file", spy)
    monkeypatch.setattr(sys, "stderr", None)                 # keep 60,000 lines off stderr
    try:
        assert launch(game, release=True) == 0
    finally:
        logging.getLogger("vn").removeHandler(counter)
    assert bounds["records"] <= 1000 and bounds["bytes"] <= 262_144
    lines = messages(user_log_dir("game") / "latest.log")
    early_in_file = [line for line in lines if line.startswith("config.toml, line")]
    dropped = [line for line in lines if line.endswith("early log records were dropped")]
    assert len(dropped) == 1
    n = int(dropped[0].split()[0])
    assert n == counts["early"] - len(early_in_file)
    assert lines.index(early_in_file[-1]) + 1 == lines.index(dropped[0])
    assert lines.index(dropped[0]) < next(i for i, line in enumerate(lines)
                                          if line.startswith("Log: "))
    assert lines[-1] == "Clean shutdown (exit code 0)"
    for prefix in ("vn-engine ", "Log: ", "Displays (video driver ", "Window: ", "Game: "):
        assert any(line.startswith(prefix) for line in lines), prefix


# --- AC-F01-130: nothing is written before the log folder is chosen ---------------------------------

def test_nothing_is_written_before_the_folder_is_chosen(tmp_path, user_roots, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    game = make_game(tmp_path, config='[game]\nid = "my-vn"\nbogus = 1\n')
    before = snapshot(tmp_path)
    at_open = {}
    real_open = LogSetup.open_file

    def spy(self, candidates):
        at_open["snapshot"] = snapshot(tmp_path)
        return real_open(self, candidates)

    monkeypatch.setattr(LogSetup, "open_file", spy)
    assert launch(game, release=True) == 0
    assert at_open["snapshot"] == before
    assert (user_log_dir("my-vn") / "latest.log").is_file()


# --- AC-F01-131: console-only release runs discard the buffer ---------------------------------------

def test_console_only_release_run_discards_the_buffer(tmp_path, user_roots, monkeypatch):
    game = make_game(tmp_path, config="[game]\nbogus = 1\n")
    (game / "logs").write_text("a file")
    vn_engine_dir().parent.mkdir(parents=True, exist_ok=True)
    vn_engine_dir().write_text("a file")
    before = snapshot(tmp_path)
    seen = {}
    real_open = LogSetup.open_file

    def spy(self, candidates):
        buffer = self.early_buffer
        seen["had_items"] = bool(buffer.items)
        session = real_open(self, candidates)
        seen["attached"] = buffer in logging.getLogger("vn").handlers
        seen["items"] = len(buffer.items)
        seen["session"] = session
        return session

    monkeypatch.setattr(LogSetup, "open_file", spy)
    assert launch(game, release=True) == 0
    assert seen["had_items"] is True
    assert seen["attached"] is False and seen["items"] == 0
    assert seen["session"].file_path is None
    assert snapshot(tmp_path) == before


def test_console_only_release_run_with_a_config_error(tmp_path, user_roots):
    game = make_game(tmp_path, config="[window]\nwidth = 1\n")
    (game / "logs").write_text("a file")
    vn_engine_dir().parent.mkdir(parents=True, exist_ok=True)
    vn_engine_dir().write_text("a file")
    before = snapshot(tmp_path)
    assert launch(game, release=True) == 1
    assert snapshot(tmp_path) == before


# --- AC-F01-146: planted links in the per-user log folder -------------------------------------------

def test_planted_links_in_the_per_user_folder(tmp_path, user_roots):
    game = make_game(tmp_path, config='[game]\nid = "my-vn"\n')
    log_dir = user_log_dir("my-vn")
    log_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.txt").write_text("victim")
    (outside / "keep.txt").write_text("keep")
    try:
        os.symlink(outside / "victim.txt", log_dir / "latest.log")
        os.symlink(outside / "keep.txt", log_dir / "session-2020-01-01_00-00-00.log")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this system does not allow creating symlinks ({exc.__class__.__name__})")
    before = snapshot(outside)
    assert launch(game, release=True) == 0
    assert snapshot(outside) == before
    assert os.path.islink(log_dir / "latest.log")
    assert os.path.islink(log_dir / "session-2020-01-01_00-00-00.log")
    pid_log = log_dir / f"latest-{os.getpid()}.log"
    assert pid_log.is_file() and not pid_log.is_symlink()
    assert messages(pid_log).count(NOT_REGULAR) == 1


# --- Missing game folder, interrupt, and the cleanup path -----------------------------------------------

def test_missing_game_folder_logs_to_the_fallback_folder(tmp_path, user_roots, capsys):
    missing = user_roots.home / "Desktop" / "nope"
    assert launch(missing) == 1
    lines = messages(user_log_dir("nope") / "latest.log")
    assert any(line.startswith('Can\'t find the game folder "~/Desktop/nope".')
               for line in lines)
    assert lines[-1] == "Clean shutdown (exit code 1)"
    assert "qauser7" not in capsys.readouterr().err.lower()


def test_ctrl_c_during_startup(tmp_path, user_roots, monkeypatch):
    game = make_game(tmp_path)

    def interrupted(_paths):
        raise KeyboardInterrupt

    monkeypatch.setattr(bootstrap, "load_config", interrupted)
    assert launch(game, log_level="error") == 0
    lines = messages(game / "logs" / "latest.log")
    assert lines[-2:] == ["Interrupted from the terminal (Ctrl+C)",
                          "Clean shutdown (exit code 0)"]
    assert HEADER_1.match(lines[0])


def test_engine_bug_during_startup_is_logged_with_a_traceback(tmp_path, user_roots,
                                                              monkeypatch):
    game = make_game(tmp_path)

    def broken(_paths):
        raise RuntimeError("boom")

    monkeypatch.setattr(bootstrap, "load_config", broken)
    assert launch(game) == 1
    text = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    assert "RuntimeError: boom" in text and "Traceback" in text
    assert text.rstrip().endswith("Clean shutdown (exit code 1)")


def test_logging_is_detached_after_launch(tmp_path, user_roots):
    game = make_game(tmp_path)
    before = list(logging.getLogger("vn").handlers)
    launch(game)
    assert logging.getLogger("vn").handlers == before
    assert logsetup._active is None
