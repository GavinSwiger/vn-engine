"""Real launches as subprocesses under the dummy video driver (04-technical §14.2).

AC-F01-01 (``python main.py --bench 1`` from the repo root), 03 (another game folder), 05
(the shipped example game, log part), 17 (unknown key warning, subprocess part), 71 (console
output), 113 (``--bench 3``), 147 (two games sharing a fallback id), 159 (c) (a release run
of ``main.py``).

Every subprocess gets ``SDL_VIDEODRIVER=dummy`` (so no window ever appears, even when the
test run itself uses a real driver) and per-user roots under the test's temp folder.
Launches that write different folders run in parallel; the ones that write
``<repo>/game/logs`` run one after another. Other pytest runs on the same checkout (parallel
builders) launch the shipped game too, so both groups hold ``repo_logs_lock()``, an OS file
lock, while they launch, read, or compare ``<repo>/game/logs`` (test-review-F02.md).

Every ``--bench N`` launch takes N + 5 s (the warm-up), so only the AC-F01-01 launch runs in
the default tier; the rest are ``slow`` (in-process launches in ``test_session_logs.py``,
``test_bootstrap.py`` and ``test_error_mode.py`` cover the same code on a fake clock).
"""

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "F01"
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")
BENCH_LINES = [
    re.compile(r"^Bench result: window \d+x\d+ (windowed|fullscreen) \| framebuffer \d+x\d+ px "
               r"\| fps cap \d+ \| measured \d+\.\d{2} s \| warm-up 5\.00 s excluded \| "
               r"frames \d+$"),
    re.compile(r"^Bench frame interval ms: p50 \d+\.\d{2} \| p95 \d+\.\d{2} \| p99 \d+\.\d{2} "
               r"\| max \d+\.\d{2}$"),
    re.compile(r"^Bench frame work ms: p50 \d+\.\d{2} \| p95 \d+\.\d{2} \| p99 \d+\.\d{2} \| "
               r"max \d+\.\d{2}$"),
    re.compile(r"^Bench long frames \(> \d+\.\d{2} ms\): \d+ of \d+ \(\d+\.\d{2}%\) \| cap: "
               r"\d+ <= \d+ (holds|FAILS)$"),
    re.compile(r"^Bench rule \(ADR-0005\): (PASS|FAIL) \(.+\)$"),
]
HEADER = [r"^vn-engine 0\.1\.0 \| ", r"^Log: ", r"^Displays \(video driver ", r"^Window: ",
          r"^Game: "]
# Computed at import, before any test points TEMP at its own folder.
LOCK_PATH = Path(tempfile.gettempdir()) / (
    f"vn-engine-game-logs-{hashlib.sha256(str(REPO).encode()).hexdigest()[:12]}.lock")


@contextlib.contextmanager
def repo_logs_lock(timeout: float = 600):
    """Hold a lock shared by every pytest run on this checkout while ``<repo>/game/logs``
    is written or compared. The OS drops it if the run dies."""
    with open(LOCK_PATH, "a+b") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail(f"{LOCK_PATH} stayed locked for {timeout} s")
                time.sleep(0.2)
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass
class Run:
    returncode: int
    stdout: str
    stderr: str
    seconds: float


def roots_env(base: Path) -> dict[str, str]:
    """The per-user roots of 06-acceptance §0.5 under ``base``, and the dummy driver."""
    home = base / "qauser7"
    env = dict(os.environ)
    env.update(SDL_VIDEODRIVER="dummy", HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home / "AppData" / "Roaming"),
               LOCALAPPDATA=str(home / "AppData" / "Local"),
               TEMP=str(base / "temp"), TMP=str(base / "temp"))
    env.pop("XDG_DATA_HOME", None)
    for name in ("HOME", "APPDATA", "LOCALAPPDATA", "TEMP"):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    return env


def user_log_dir_in(env: dict[str, str], app_id: str) -> Path:
    if sys.platform == "win32":
        return Path(env["LOCALAPPDATA"]) / "vn-engine" / app_id / "logs"
    if sys.platform == "darwin":
        return Path(env["HOME"]) / "Library" / "Application Support" / "vn-engine" / app_id / "logs"
    return Path(env["HOME"]) / ".local" / "share" / "vn-engine" / app_id / "logs"


def start(args: list[str], *, cwd: Path, env: dict[str, str]):
    started = time.perf_counter()
    process = subprocess.Popen([sys.executable, *args], cwd=cwd, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process, started


def finish(handle, timeout: float = 60) -> Run:
    process, started = handle
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
        pytest.fail(f"launch did not finish within {timeout} s:\n{err[-2000:]}")
    return Run(process.returncode, out, err, time.perf_counter() - started)


def records(log_file: Path) -> list[tuple[str, str, str]]:
    return [(line[24:31].strip(), line[32:39].strip(), line[40:])
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if TIMESTAMP.match(line)]


def assert_header(messages: list[str]) -> None:
    """Header lines 1-5 appear in order (DEBUG records may sit between them)."""
    position = 0
    for pattern in HEADER:
        while not re.match(pattern, messages[position]):
            position += 1
        position += 1


def bench_lines(recs) -> list[tuple[str, str, str]]:
    return [r for r in recs if r[2].startswith("Bench ")]


def assert_bench_lines(recs) -> list[str]:
    lines = bench_lines(recs)
    assert len(lines) == 5
    for (level, area, message), pattern in zip(lines, BENCH_LINES):
        assert (level, area) == ("INFO", "loop")
        assert pattern.match(message), message
    return [message for _, _, message in lines]


def snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    if not folder.exists():
        return {}
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*")}


# --- the parallel group -------------------------------------------------------------------

@pytest.fixture(scope="module")
def parallel(tmp_path_factory):
    """Launch every independent session at once; return their results and folders."""
    base = tmp_path_factory.mktemp("smoke")
    with repo_logs_lock():
        return _launch_parallel(base)


def _launch_parallel(base: Path):
    repo_logs_before = snapshot(REPO / "game" / "logs")
    runs: dict[str, object] = {}
    info: dict[str, object] = {"base": base}

    # AC-F01-159 (c): a release run of main.py logs per user, never in <repo>/game/logs.
    env_release = roots_env(base / "release")
    info["release_env"] = env_release
    runs["release"] = start([str(REPO / "main.py"), "--release", "--bench", "1",
                             "--log-level", "debug"], cwd=REPO, env=env_release)

    # AC-F01-03: another game folder.
    minimal = base / "minimal"
    shutil.copytree(FIXTURES / "games" / "minimal", minimal,
                    ignore=shutil.ignore_patterns("logs"))
    info["minimal"] = minimal
    runs["other_folder"] = start(["-m", "engine", "run", str(minimal), "--bench", "1"],
                                 cwd=REPO, env=roots_env(base / "other"))

    # AC-F01-17 / 71: warnings and errors reach the console; INFO lines do not.
    console_game = base / "console" / "game"
    console_game.mkdir(parents=True)
    (console_game / "config.toml").write_bytes(
        (FIXTURES / "config" / "walkthrough_step2.toml").read_bytes()
        .replace(b'icon = "gui/lantern.png"', b'icon = "../x.png"'))
    info["console_game"] = console_game
    runs["console"] = start(["-m", "engine", "run", str(console_game), "--bench", "1"],
                            cwd=REPO, env=roots_env(base / "console"))

    # AC-F01-147: two games named "game", no [game] id, both release, 0.5 s apart.
    shared_env = roots_env(base / "shared")
    info["shared_env"] = shared_env
    for name in ("first", "second"):
        game = base / name / "game"
        game.mkdir(parents=True)
        (game / "config.toml").write_text(f'[game]\ntitle = "{name}"\n', encoding="utf-8")
        runs[name] = start(["-m", "engine", "run", str(game), "--release", "--bench", "2"],
                           cwd=REPO, env=shared_env)
        if name == "first":
            time.sleep(0.5)

    results = {name: finish(handle) for name, handle in runs.items()}
    info["repo_logs_unchanged"] = snapshot(REPO / "game" / "logs") == repo_logs_before
    return results, info


@pytest.mark.slow
def test_release_run_of_main_py(parallel):
    results, info = parallel
    run = results["release"]
    assert run.returncode == 0, run.stderr
    assert info["repo_logs_unchanged"]
    log_file = user_log_dir_in(info["release_env"], "game") / "latest.log"
    recs = records(log_file)
    assert recs[0][2].endswith("build release")
    assert any(level == "DEBUG" for level, _, _ in recs)
    assert recs[-1] == ("INFO", "app", "Clean shutdown (exit code 0)")


@pytest.mark.slow
def test_run_another_game_folder(parallel):
    results, info = parallel
    run = results["other_folder"]
    assert run.returncode == 0, run.stderr
    recs = records(info["minimal"] / "logs" / "latest.log")
    assert '"Fixture Game" 9.9.9' in recs[4][2]
    assert info["repo_logs_unchanged"]


@pytest.mark.slow
def test_console_shows_warnings_and_errors_only(parallel):
    results, info = parallel
    run = results["console"]
    assert run.returncode == 0, run.stderr
    warning = 'config.toml, line 6: unknown key [window] fulscreen — did you mean "fullscreen"?'
    assert warning in run.stderr
    assert "Asset path \"../x.png\" is not allowed" in run.stderr
    assert "vn-engine 0.1.0 |" not in run.stderr
    assert "Clean shutdown" not in run.stderr
    assert "Bench result" not in run.stderr
    recs = records(info["console_game"] / "logs" / "latest.log")
    assert ("WARNING", "config", warning) in recs
    assert recs[-1][2] == "Clean shutdown (exit code 0)"


@pytest.mark.slow
def test_two_games_sharing_a_fallback_id(parallel):
    results, info = parallel
    for name in ("first", "second"):
        assert results[name].returncode == 0, results[name].stderr
    log_dir = user_log_dir_in(info["shared_env"], "game")
    sessions = {}
    for path in log_dir.iterdir():
        assert path.is_file() and re.fullmatch(r"(latest(-\d+)?|session-[\d_-]+)\.log",
                                               path.name), path.name
        text = path.read_text(encoding="utf-8")
        title = re.search(r'Game: "(first|second)"', text)
        if title:
            sessions[title.group(1)] = text
    assert set(sessions) == {"first", "second"}
    for text in sessions.values():
        assert "vn-engine 0.1.0 |" in text.splitlines()[0]
        assert text.rstrip().endswith("Clean shutdown (exit code 0)")
    # Nothing else under the per-user roots changed: only the shared log folder exists.
    vn_root = log_dir.parent.parent
    assert [p.name for p in vn_root.iterdir()] == ["game"]


# --- the sequential group (writes <repo>/game/logs) -------------------------------------------

def test_launch_from_the_project_root_and_the_shipped_game(tmp_path):
    """AC-F01-01 and the log part of AC-F01-05."""
    with repo_logs_lock():
        run = finish(start([str(REPO / "main.py"), "--bench", "1"], cwd=REPO,
                           env=roots_env(tmp_path)))
        recs = records(REPO / "game" / "logs" / "latest.log")
    assert run.returncode == 0, run.stderr
    assert run.seconds < 30
    assert_header([m for _, _, m in recs])
    assert_bench_lines(recs)
    assert recs[-1] == ("INFO", "app", "Clean shutdown (exit code 0)")
    assert not [r for r in recs if r[0] in ("WARNING", "ERROR")]
    assert '"Example Visual Novel" 0.1.0' in recs[4][2]
    # F02 (04 §14): the example story loaded before the bench started.
    loaded = [i for i, r in enumerate(recs)
              if r[1] == "script" and r[2].startswith("Loaded story:")]
    assert len(loaded) == 1 and loaded[0] < recs.index(bench_lines(recs)[0])


@pytest.mark.slow
def test_bench_mode(tmp_path):
    """AC-F01-113."""
    with repo_logs_lock():
        run = finish(start([str(REPO / "main.py"), "--bench", "3"], cwd=REPO,
                           env=roots_env(tmp_path)))
        recs = records(REPO / "game" / "logs" / "latest.log")
    assert run.returncode == 0, run.stderr
    assert 8.0 <= run.seconds < 30
    lines = assert_bench_lines(recs)
    bench_index = recs.index(bench_lines(recs)[-1])
    assert recs[-1] == ("INFO", "app", "Clean shutdown (exit code 0)")
    assert bench_index < len(recs) - 1
    first = lines[0]
    assert "fps cap 60" in first and "warm-up 5.00 s excluded" in first
    measured = float(re.search(r"measured (\d+\.\d{2}) s", first).group(1))
    assert 2.95 <= measured <= 3.05
    assert int(re.search(r"frames (\d+)$", first).group(1)) <= 181
    assert "(> 25.00 ms)" in lines[3] and lines[3].endswith("holds")
