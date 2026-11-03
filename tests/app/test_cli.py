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


@pytest.fixture
def built(monkeypatch, tmp_path):
    """A built game as its exe sees it (F42): ``sys.frozen``, ``_MEIPASS`` =
    ``<exe folder>/_internal``, ``sys.executable`` = ``<exe folder>/Lanterns.exe``, a
    ``game`` folder beside it, and a ``sys.path`` holding outside entries too. ``sys.path``,
    ``dont_write_bytecode``, the streams and the SDL variables are restored afterwards."""
    import pygame  # noqa: F401  (loaded before sys.path is narrowed, as in the exe)

    from engine.app import bootstrap  # noqa: F401

    folder = tmp_path / "Lanterns 0.1.0 Windows"
    (folder / "_internal").mkdir(parents=True)
    (folder / "game").mkdir()
    (folder / "Lanterns.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(folder / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / "Lanterns.exe"))
    monkeypatch.setattr(sys, "path", [str(folder / "_internal" / "base_library.zip"),
                                      str(folder / "_internal"), "", ".", str(folder),
                                      str(folder / "game"), str(tmp_path / "elsewhere")])
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    for name in ("PYGAME_HIDE_SUPPORT_PROMPT", "SDL_WINDOWS_DPI_AWARENESS"):
        monkeypatch.delenv(name, raising=False)
    return folder


def test_ac_f42_04_frozen_launcher_runs_the_exe_folder_game(built, launched, monkeypatch,
                                                           tmp_path):
    """AC-F42-04 (PR-F42-03, SEC-F42-01, decision 8): the built exe runs
    ``<exe folder>/game`` from any CWD (never the CWD's or ``_internal``'s ``game``), keeps
    only ``_internal`` on ``sys.path``, writes no bytecode, and is always a release run; a
    positional argument exits 2, silently when the windowed exe has no streams."""
    cwd = tmp_path / "somewhere"
    (cwd / "game").mkdir(parents=True)
    (built / "_internal" / "game").mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", [str(cwd / "fake.exe")])     # never argv[0]
    assert cli.launcher_main(["--bench", "1"]) == 0
    assert launched[0]["game_dir"] == built / "game"
    assert launched[0]["release"] is True and launched[0]["bench_seconds"] == 1.0
    assert paths.launcher_game_dir() == built / "game" and paths.exe_dir() == built
    assert sys.path == [str(built / "_internal" / "base_library.zip"), str(built / "_internal")]
    assert sys.dont_write_bytecode is True
    # SEC-F42-09: the exe folder is the <app> root; <game> and <engine> still win below it.
    from engine.core import logsetup
    from engine.core.redact import Redactor

    roots = logsetup.redaction_roots(game_root=built / "game", game_dir_as_given=None,
                                     engine_root=built / "_internal")
    assert ("<app>", str(built)) in [(root.token, root.path) for root in roots]
    redact = Redactor(roots, home_name=None, case_insensitive=True)
    assert redact(str(built / "Lanterns.exe")).replace("\\", "/") == "<app>/Lanterns.exe"
    assert redact(str(built / "game" / "a.png")).replace("\\", "/") == "<game>/a.png"
    assert redact(str(built / "_internal" / "x")).replace("\\", "/") == "<engine>/x"
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    with pytest.raises(SystemExit) as exit_info:
        cli.launcher_main([str(cwd / "game")])
    assert exit_info.value.code == 2 and len(launched) == 1
    assert sys.stderr is not None and sys.stderr.name == os.devnull
    for bad in (["--start", "x"], ["--report-to-editor"], ["--seed", "1"], ["build"]):
        with pytest.raises(SystemExit):
            cli.launcher_main(bad)
    assert len(launched) == 1


def test_ac_f42_05_missing_game_folder(built, launched, monkeypatch):
    """AC-F42-05 (PR-F42-03): with no ``game`` folder beside the exe (the player moved only
    the exe), the native error box shows ``GAME_FOLDER_MISSING`` naming the exe, and the
    exe exits 1 without starting."""
    from engine.app import bootstrap
    from engine.tools.build import texts

    shown = []
    monkeypatch.setattr(bootstrap, "show_native_error", lambda *a: shown.append(a))
    (built / "game").rmdir()
    (built / "game").write_bytes(b"not a folder")
    assert cli.launcher_main([]) == 1
    assert shown == [("Lanterns", "The game folder is missing. Keep Lanterns.exe, _internal "
                                  "and game together in one folder.")]
    assert cli.GAME_FOLDER_MISSING == texts.GAME_FOLDER_MISSING
    assert launched == []


@pytest.mark.parametrize("argv", [[], ["--bench", "1"], ["--log-level", "debug"]])
def test_frozen_build_is_always_release(argv, built, monkeypatch, launched):
    """SEC-F01-20: a frozen build is a release run whatever the arguments or environment."""
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


def test_ac_f42_01_build_command(launched, tmp_path, monkeypatch, capsys):
    """AC-F42-01 (PR-F42-01, I-6): ``build`` parses ``GAME_DIR``, ``--out``, ``--zip``,
    ``--replace`` (and the hidden ``--report-to-editor``); defaults are ``<repo>/game`` and
    ``builds`` beside it; relative folders resolve against the CWD. ``--release`` is
    ``build is only available in dev runs``, exit 2. ``python -m engine``'s handler imports
    ``tools.build.command`` only when called. A frozen parser has no ``build``."""
    import types

    from engine import __main__ as entry

    calls = []

    def builder(game_dir, **kwargs):
        calls.append((game_dir, kwargs))
        return 0

    monkeypatch.chdir(tmp_path)
    assert cli.main(["build", "mygame", "--out", "out", "--zip", "--replace"],
                    builder=builder) == 0
    assert calls.pop() == (tmp_path / "mygame", {"out": tmp_path / "out", "zip": True,
                                                 "replace": True, "report": False})
    assert cli.main(["build", "--report-to-editor"], builder=builder) == 0
    assert calls.pop() == (REPO / "game", {"out": REPO / "builds", "zip": False,
                                           "replace": False, "report": True})
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["build", "--release"], builder=builder)
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.rstrip().endswith("error: build is only available in "
                                                     "dev runs")
    stub = types.ModuleType("engine.tools.build.command")
    stub.build_command = lambda game_dir, **kw: calls.append((game_dir, kw)) or 7
    monkeypatch.setitem(sys.modules, "engine.tools.build.command", stub)
    assert entry._build(tmp_path, out=tmp_path / "b", zip=False, replace=False,
                        report=False) == 7
    assert calls.pop()[1]["out"] == tmp_path / "b"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO), raising=False)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["build"], builder=builder)
    assert exit_info.value.code == 2
    assert "invalid choice: 'build'" in capsys.readouterr().err
    assert calls == [] and launched == []


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
