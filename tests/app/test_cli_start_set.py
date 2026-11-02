"""F44 step 5: ``run --start``/``--set``/``--report-to-editor`` and ``edit`` on the command
line (``04`` §5.4; ``07`` I-1, I-9, I-10, I-15).

AC-F44-04 (value and option errors are usage errors), AC-F44-07 (dev runs only), the CLI
rows of AC-F44-13 (``edit`` start-up), and AC-F44-33 (b) (``run`` loads no editor code).
In-process through ``cli.main`` with ``bootstrap.launch`` patched to record its calls (as
AC-F01-159 (b)); one subprocess per code path (I-16).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import engine.__main__ as engine_main
from engine.app import bootstrap, cli
from engine.core.paths import engine_root
from engine.core.startvalues import StartOptions
from engine.script.messages import format_message
from engine.tools import editor as editor_package
from tests.app.test_cli import USAGE
from tests.tools.editor.conftest import R_SCRIPTS

REPO = Path(__file__).resolve().parent.parent.parent
RUN_USAGE = "usage: python -m engine run "
NOT_A_VALUE = ("the value must be a number, True, False, None, quoted text, a list, "
               "or a dictionary")


@pytest.fixture
def game(tmp_path) -> Path:
    """Game R (F44 ``06`` §0.3) at ``<tmp>/my_game``."""
    root = tmp_path / "my_game"
    for ref, text in R_SCRIPTS.items():
        path = root / "script" / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    (root / "config.toml").write_bytes(b'[game]\ntitle = "My Game"\n')
    return root


@pytest.fixture
def launched(monkeypatch):
    """``bootstrap.launch`` replaced by a recorder of its arguments."""
    calls: list[dict] = []

    def fake_launch(game_dir, **kwargs):
        calls.append({"game_dir": game_dir, **kwargs})
        return 0

    monkeypatch.setattr(bootstrap, "launch", fake_launch)
    return calls


@pytest.fixture
def edited(monkeypatch):
    """An ``edit`` handler that records the folder it gets."""
    calls: list[Path] = []

    def handler(game_dir: Path) -> int:
        calls.append(game_dir)
        return 0

    return calls, handler


def usage_error(argv: list[str], capsys, *, editor=None) -> str:
    """Runs ``cli.main(argv)``, expects exit 2, and returns stderr."""
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv, editor=editor)
    assert exit_info.value.code == 2
    return capsys.readouterr().err


@pytest.fixture
def frozen(monkeypatch):
    """The CLI as a frozen build sees it (AC-F01-155)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO), raising=False)


# --- AC-F44-04: value and option errors -----------------------------------------------------

LONG_TEXT = '"' + "x" * 10_001 + '"'


@pytest.mark.parametrize("args, expected", [
    (["--set", "sayo_points=Hana"], '--set "sayo_points=Hana": put text in quotes.'),
    (["--set", "sayo_points=1+1"], f'--set "sayo_points=1+1": {NOT_A_VALUE}.'),
    (["--set", "sayo_points= "], "the value must be a number"),
    (["--set", "sayo_points=1", "--set", "sayo_points = 2"], "`sayo_points` is set twice"),
    ([arg for i in range(101) for arg in ("--set", f"v{i}=1")], "100"),
    (["--set", "sayo_points"], '--set "sayo_points"'),
    (["--set", "1x=1"], '--set "1x=1"'),
    (["--set", "class=1"], '--set "class=1"'),
    (["--start", "club poem"], "--start needs a label name, like club_poem"),
    (["--start", "3rd"], "--start needs a label name, like club_poem"),
    (["--set", f"s={LONG_TEXT}"], "the value must be a number"),
], ids=["unquoted", "sum", "empty", "twice", "101", "no-equals", "bad-name", "keyword",
        "start-space", "start-digit", "too-long"])
def test_ac04_value_and_option_errors_are_usage_errors(args, expected, game, launched,
                                                       capsys):
    err = usage_error(["run", str(game), *args], capsys)
    assert err.startswith(RUN_USAGE)
    assert expected in err
    assert launched == []


def test_ac04_every_bad_value_is_listed_with_its_argument(game, launched, capsys):
    err = usage_error(["run", str(game), "--set", "a=Hana", "--set", "b=1+1",
                       "--set", "a=2"], capsys)
    assert '--set "a=Hana": put text in quotes.' in err
    assert f'--set "b=1+1": {NOT_A_VALUE}.' in err
    assert '--set "a=2": `a` is set twice.' in err
    assert launched == []


def test_ac04_a_long_argument_is_cut_when_echoed(game, launched, capsys):
    err = usage_error(["run", str(game), "--set", f"s={LONG_TEXT}"], capsys)
    assert "x" * 10_001 not in err
    assert "…" in err


def test_ac04_good_values_reach_launch_in_argv_order(game, launched):
    assert cli.main(["run", str(game), "--set", "sayo_points = 1",
                     "--set", "hana_name='Hana'", "--set", "seen=[1, {'a': None}]"]) == 0
    (call,) = launched
    assert call["start"] == StartOptions(label=None, values=(
        ("sayo_points", 1), ("hana_name", "Hana"), ("seen", [1, {"a": None}])))
    assert call["editor_report"] is False


def test_ac04_start_and_report_reach_launch(game, launched):
    assert cli.main(["run", str(game), "--start", "club_poem", "--report-to-editor",
                     "--bench", "1"]) == 0
    (call,) = launched
    assert call["start"] == StartOptions(label="club_poem")
    assert call["editor_report"] is True
    assert call["bench_seconds"] == 1.0


def test_no_start_options_means_none(game, launched):
    assert cli.main(["run", str(game)]) == 0
    assert launched[0]["start"] is None
    assert launched[0]["editor_report"] is False


def test_ac04_a_bad_value_exits_2_in_a_real_process(game):
    """The subprocess row of AC-F44-04 (one per code path, I-16)."""
    result = subprocess.run([sys.executable, "-m", "engine", "run", str(game), "--set",
                             "sayo_points=Hana"], cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8", timeout=60)
    assert result.returncode == 2
    assert result.stderr.startswith(RUN_USAGE)
    assert '--set "sayo_points=Hana": put text in quotes.' in result.stderr
    assert "Traceback" not in result.stderr
    assert not (game / "logs").exists()                   # found before anything loaded


# --- AC-F44-07: dev runs only ---------------------------------------------------------------

def test_ac07a_edit_release_is_refused(game, edited, capsys):
    calls, handler = edited
    err = usage_error(["edit", "--release", str(game)], capsys, editor=handler)
    assert err.startswith("usage: python -m engine edit ")
    assert "the editor is only available in dev runs" in err
    assert calls == []


@pytest.mark.parametrize("args, option", [
    (["--start", "club_poem"], "--start"),
    (["--set", "x=1"], "--set"),
    (["--report-to-editor"], "--report-to-editor"),
])
def test_ac07b_run_release_refuses_each_option(args, option, game, launched, capsys):
    err = usage_error(["run", str(game), "--release", *args], capsys)
    assert err.startswith(RUN_USAGE)
    assert f"{option} is only available in dev runs" in err          # I-9: names it
    assert launched == []


def test_ac07c_frozen_edit_is_not_a_command(frozen, game, edited, capsys):
    calls, handler = edited
    err = usage_error(["edit", str(game)], capsys, editor=handler)
    assert "invalid choice: 'edit'" in err
    assert calls == []


@pytest.mark.parametrize("args", [["--start", "x"], ["--set", "x=1"],
                                  ["--report-to-editor"]])
def test_ac07c_frozen_run_has_no_start_options(args, frozen, game, launched, capsys):
    err = usage_error(["run", str(game), *args], capsys)
    assert "unrecognized arguments" in err
    assert launched == []


def test_ac07c_frozen_run_still_runs(frozen, game, launched):
    assert cli.main(["run", str(game)]) == 0
    assert launched[0]["release"] is True
    assert launched[0]["start"] is None and launched[0]["editor_report"] is False


def test_ac07d_main_without_editor_has_no_edit(game, capsys):
    err = usage_error(["edit", str(game)], capsys)
    assert "invalid choice: 'edit'" in err


@pytest.mark.parametrize("args", [["--start", "x"], ["--set", "x=1"],
                                  ["--report-to-editor"]])
def test_ac07d_main_py_has_none_of_the_options(args, capsys, monkeypatch):
    """I-10: the options belong to ``run`` only; ``main.py``'s usage line is unchanged."""
    monkeypatch.setattr(cli, "_launch", lambda *a, **k: pytest.fail("launched"))
    with pytest.raises(SystemExit) as exit_info:
        cli.launcher_main(args)
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.startswith(USAGE + "\n")


def test_ac07e_run_help_lists_both_options(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", "--help"], editor=engine_main._edit)
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith(RUN_USAGE)
    usage = out.split("\n\n")[0]
    assert "[--start LABEL]" in usage and "[--set NAME=VALUE]" in usage
    assert "--start LABEL" in out and "--set NAME=VALUE" in out
    assert "report" not in out


def test_engine_help_lists_edit_only_with_a_handler(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"], editor=engine_main._edit)
    assert "edit" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "edit" not in capsys.readouterr().out


# --- AC-F44-13: edit start-up (CLI rows) ----------------------------------------------------

def test_ac13_edit_without_folder_gets_the_folder_run_uses(edited, launched):
    calls, handler = edited
    assert cli.main(["edit"], editor=handler) == 0
    assert cli.main(["run"]) == 0
    assert calls == [engine_root() / "game"] == [launched[0]["game_dir"]]


def test_ac13_edit_resolves_a_relative_folder_like_run(edited, launched, tmp_path,
                                                       monkeypatch):
    calls, handler = edited
    monkeypatch.chdir(tmp_path)
    assert cli.main(["edit", "my_game"], editor=handler) == 0
    assert cli.main(["run", "my_game"]) == 0
    assert calls == [tmp_path / "my_game"] == [launched[0]["game_dir"]]


def test_ac13_edit_skips_the_environment_and_the_pygame_check(edited, monkeypatch, game):
    calls, handler = edited

    def forbidden(*args, **kwargs):
        raise AssertionError("edit must not prepare pygame")

    monkeypatch.setattr(cli, "prepare_environment", forbidden)
    monkeypatch.setattr(cli._bootcheck, "check_pygame", forbidden)
    assert cli.main(["edit", str(game)], editor=handler) == 0
    assert calls == [game]


def test_ac13_edit_on_an_empty_folder_prints_runs_message(tmp_path, monkeypatch, capsys):
    """AC-F44-13 wins over ``03``'s empty-list state: a folder with no ``script/`` gets the
    W01 line ``run`` logs for it, exit 1, and the editor never opens."""
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    monkeypatch.setattr(editor_package, "run_editor",
                        lambda game_dir: pytest.fail("the editor opened"))
    assert cli.main(["edit", str(empty)], editor=engine_main._edit) == 1
    assert capsys.readouterr().err == format_message("W01") + "\n"


def test_ac13_edit_on_a_missing_folder_prints_runs_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(editor_package, "run_editor",
                        lambda game_dir: pytest.fail("the editor opened"))
    assert cli.main(["edit", str(tmp_path / "nowhere")], editor=engine_main._edit) == 1
    err = capsys.readouterr().err
    assert err.startswith("Can't find the game folder") and err.count("\n") == 1


def test_ac15_a_script_folder_without_vns_files_still_opens(tmp_path, monkeypatch):
    """The other side of the AC-13 decision: ``script/`` exists but is empty → the editor
    opens on it and shows "No .vns files in script/" (AC-F44-15)."""
    game = tmp_path / "g"
    (game / "script").mkdir(parents=True)
    opened: list[Path] = []
    monkeypatch.setattr(editor_package, "run_editor", lambda d: opened.append(d) or 0)
    assert cli.main(["edit", str(game)], editor=engine_main._edit) == 0
    assert opened == [game]


def test_ac13_edit_without_tkinter_or_pygame_prints_one_line(game):
    """The ``python -m engine edit`` subprocess row: with ``tkinter`` and ``pygame`` both
    blocked, the handler is still reached (no pygame check) and prints this OS's line."""
    wrapper = ("import runpy, sys; sys.modules['tkinter'] = None; sys.modules['pygame'] = None; "
               "sys.argv = ['engine', 'edit', sys.argv[1]]; "
               "runpy.run_module('engine', run_name='__main__', alter_sys=True)")
    result = subprocess.run([sys.executable, "-c", wrapper, str(game)], cwd=REPO,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 1
    assert result.stderr == editor_package.no_tkinter_message() + "\n"
    assert result.stdout == ""


# --- AC-F44-33 (b): run loads no editor code ------------------------------------------------

def test_ac33b_run_never_imports_the_editor_or_tkinter(game):
    """``cli.main(["run", …])`` with every F44 option, in a fresh process whose startup
    imports the whole of ``engine.app`` (the real window launch is F44 step 6's e2e test)."""
    code = (
        "import sys\n"
        "from engine.app import cli\n"
        "def fake_launch(game_dir, **kwargs):\n"
        "    import engine.app.app, engine.app.bootstrap, engine.app.editor_link\n"
        "    import engine.app.loading\n"
        "    return 0\n"
        "cli._launch = fake_launch\n"
        "assert cli.main(['run', sys.argv[1], '--start', 'club_poem', '--set', 'x=1',\n"
        "                 '--report-to-editor']) == 0\n"
        "bad = sorted(m for m in sys.modules if m == 'tkinter' or m.startswith('engine.tools'))\n"
        "print(bad)\n")
    result = subprocess.run([sys.executable, "-c", code, str(game)], cwd=REPO,
                            capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, SDL_VIDEODRIVER="dummy"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
