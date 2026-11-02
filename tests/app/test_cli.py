"""The launch commands: options, usage errors, environment setup, build mode.

AC-F01-160 (usage line reveals no home path); parts of AC-F01-31, 159, 162 that exist in
Step 1 (option parsing, exit codes, SDL environment defaults).
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.app import cli
from engine.core import paths

REPO = Path(__file__).resolve().parent.parent.parent
USAGE = "usage: python main.py [-h] [--release] [--bench SECONDS] [--log-level LEVEL]"


@pytest.fixture
def launched(monkeypatch):
    """Replace the startup sequence with a recorder of its arguments."""
    calls: list[dict] = []

    def fake_launch(game_dir, **kwargs):
        calls.append({"game_dir": game_dir, **kwargs})
        return 0

    monkeypatch.setattr(cli, "_launch", fake_launch)
    return calls


# --- main.py (launcher_main) --------------------------------------------------------------

def test_positional_argument_is_a_usage_error(launched, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.launcher_main(["extra"])
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(USAGE)
    assert "main.py always runs the game in <repo>/game" in err
    assert launched == []


@pytest.mark.parametrize("argv", [
    ["--bench", "0"], ["--bench", "3601"], ["--bench", "abc"], ["--bench", "nan"],
    ["--log-level", "verbose"], ["--log-level", "INFO"]])
def test_bad_option_values_are_usage_errors(argv, launched, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.launcher_main(argv)
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.startswith(USAGE)
    assert launched == []


@pytest.mark.parametrize("text, seconds", [("1", 1.0), ("3600", 3600.0), ("2.5", 2.5)])
def test_bench_range_is_accepted(text, seconds, launched):
    assert cli.launcher_main(["--bench", text]) == 0
    assert launched[0]["bench_seconds"] == seconds


def test_launcher_forwards_options_and_runs_repo_game(launched):
    assert cli.launcher_main(["--release", "--bench", "1", "--log-level", "debug"]) == 0
    call = launched[0]
    assert call["game_dir"] == paths.engine_root() / "game"
    assert call["game_dir"] == REPO / "game"
    assert call["release"] is True
    assert call["bench_seconds"] == 1.0
    assert call["log_level_override"] == "debug"
    assert call["pygame_warning"] is None


def test_defaults_are_dev_run_without_options(launched):
    assert cli.launcher_main([]) == 0
    call = launched[0]
    assert call["release"] is False
    assert call["bench_seconds"] is None
    assert call["log_level_override"] is None


@pytest.mark.parametrize("argv", [[], ["--bench", "1"], ["--log-level", "debug"]])
def test_frozen_build_is_always_release(argv, monkeypatch, launched):
    """SEC-F01-20: a frozen build is a release run whatever the arguments or environment."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO), raising=False)
    for name in ("VN_DEV", "DEBUG", "PYTHONDEVMODE"):
        monkeypatch.setenv(name, "1")
    assert cli.launcher_main(argv) == 0
    assert launched[0]["release"] is True


# --- python -m engine (main) --------------------------------------------------------------

def test_engine_without_subcommand_is_a_usage_error(launched, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.startswith("usage: python -m engine")
    assert launched == []


def test_engine_run_defaults_to_repo_game(launched):
    assert cli.main(["run", "--bench", "1"]) == 0
    assert launched[0]["game_dir"] == REPO / "game"
    assert launched[0]["bench_seconds"] == 1.0


def test_engine_run_resolves_relative_folder_against_cwd(launched, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "minimal"]) == 0
    assert launched[0]["game_dir"] == tmp_path / "minimal"
    assert launched[0]["game_dir"].is_absolute()


def test_engine_run_accepts_absolute_folder_and_options(launched, tmp_path):
    assert cli.main(["run", str(tmp_path), "--release", "--log-level", "warning"]) == 0
    call = launched[0]
    assert call["game_dir"] == tmp_path
    assert call["release"] is True
    assert call["log_level_override"] == "warning"


# --- Environment setup before pygame (§7.1 step 3) ----------------------------------------

def test_environment_defaults(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("SDL_WINDOWS_DPI_AWARENESS", raising=False)
    monkeypatch.delenv("PYGAME_HIDE_SUPPORT_PROMPT", raising=False)
    monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    cli.prepare_environment()
    assert os.environ["SDL_WINDOWS_DPI_AWARENESS"] == "permonitorv2"
    assert os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] == "1"
    assert "SDL_VIDEODRIVER" not in os.environ          # never set (PR-F01-63)


def test_environment_keeps_preset_dpi_awareness(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SDL_WINDOWS_DPI_AWARENESS", "system")
    cli.prepare_environment()
    assert os.environ["SDL_WINDOWS_DPI_AWARENESS"] == "system"


def test_environment_sets_no_dpi_awareness_elsewhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("SDL_WINDOWS_DPI_AWARENESS", raising=False)
    cli.prepare_environment()
    assert "SDL_WINDOWS_DPI_AWARENESS" not in os.environ


def test_cli_module_does_not_import_pygame():
    """pygame must not load before prepare_environment() runs (AC-F01-31)."""
    code = ("import sys; import engine.app.cli; "
            "sys.exit(1 if 'pygame' in sys.modules else 0)")
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO, timeout=60)
    assert result.returncode == 0


# --- Subprocess runs ----------------------------------------------------------------------

def _copy_engine_tree(dest: Path) -> None:
    dest.mkdir(parents=True)
    shutil.copy2(REPO / "main.py", dest / "main.py")
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(REPO / "engine", dest / "engine", ignore=ignore)
    if (REPO / "game").is_dir():
        shutil.copytree(REPO / "game", dest / "game",
                        ignore=shutil.ignore_patterns("__pycache__", "characters"))


def test_usage_line_reveals_no_home_path(tmp_path):
    """AC-F01-160."""
    home = tmp_path / "qauser7"
    root = home / "vn-engine"
    _copy_engine_tree(root)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    result = subprocess.run([sys.executable, str(root / "main.py"), "extra"],
                            cwd=tmp_path, env=env, capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 2
    assert "main.py always runs the game in" in result.stderr
    lowered = result.stderr.lower()
    assert "qauser7" not in lowered
    for form in (str(home), home.as_posix(), str(home).replace("\\", "\\\\")):
        assert form.lower() not in lowered


def test_python_m_engine_without_subcommand_exits_2():
    result = subprocess.run([sys.executable, "-m", "engine"], cwd=REPO,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert result.stderr.startswith("usage: python -m engine")


@pytest.mark.slow                 # a real --bench 1 launch: 6 s (5 s warm-up)
def test_main_py_runs_from_another_directory(tmp_path, user_roots):
    """AC-F01-02: main.py runs ``<repo>/game`` whatever the CWD, writes its log there, and
    writes nothing into the CWD. Always the dummy driver, so no window appears."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    launched_at = time.time()
    result = subprocess.run([sys.executable, str(REPO / "main.py"), "--bench", "1"],
                            cwd=cwd, env=dict(os.environ, SDL_VIDEODRIVER="dummy"),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert list(cwd.iterdir()) == []
    log_file = REPO / "game" / "logs" / "latest.log"
    assert log_file.stat().st_mtime >= launched_at - 1
