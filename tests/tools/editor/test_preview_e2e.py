"""End-to-end preview (F44 step 6; ``04`` §5.1–5.3, §7.4, §14 "Integration"; ``06`` §0.3):
the real game as the editor's child, and the same code paths in process.

- In process (default tier): the start options in a headless new game (AC-F44-01, 02), the
  load checks with ``LoadOptions(start=, start_names=)`` (AC-F44-05, 06), the report of a
  launch equal to its error screen (AC-F44-09), and the panel and jump fed with reports
  built exactly as the child builds them (AC-F44-28, 29 with the ten ``seeded`` games).
- Real children (``CHILD`` of ``06`` §0.3: ``python -m engine run <game> --report-to-editor``
  under the SDL dummy drivers, per-user roots under ``tmp_path``): one smoke path in the
  default tier, F5 in the editor on game R whose child's E26c lands in the panel. Every
  other real launch is over 1 s and marked ``slow`` (I-16).

Every child is killed in teardown (``Runners.close``, ``subprocess.run(timeout=)``), and
every Tk root is destroyed in a ``finally``. Tk tests skip without Tk or a display.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.app import bootstrap, cli
from engine.app.app import engine_error_message
from engine.app.editor_link import build_report, encode_line
from engine.core.config import load_config
from engine.core.errors import ConfigErrorGroup
from engine.core.paths import GamePaths
from engine.core.redact import redact
from engine.core.startvalues import StartOptions, parse_set
from engine.runtime.commands import Say
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.script import ScriptErrorGroup
from engine.script.loader import LoadOptions, LoadResult, load_story
from engine.script.messages import format_message
from engine.tools.editor.preview import (
    REPORT_MARKER,
    STARTED,
    PreviewEvent,
    PreviewState,
    Report,
    decode_report,
    preview_argv,
)
from tests.app.test_editor_link import (  # noqa: F401  (fixtures used by name)
    decoded,
    error_screens,
    launch,
    lines_of,
    make_game,
    session,
    stdout,
)
from tests.app.test_smoke_launch import roots_env
from tests.fakes.banned_words import BANNED_ANY, BANNED_CASED
from tests.fixtures.F44.seeded import SEEDED, seeded_scripts
from tests.tools.editor.conftest import R_SCRIPTS
from tests.tools.editor.test_preview import Runners, run_until, states

S = PreviewState
REPO = Path(__file__).resolve().parents[3]
STARTING, RUNNING, CLOSED = "Starting…", "Running. F5 restarts it.", "Closed."
STOPPED_ERROR = "Stopped with an error, listed in Problems."


# --- Game R and its variants -----------------------------------------------------------------

def r_with(**changes: str) -> dict[str, str]:
    """R's scripts with whole files replaced or added: ``r_with(chapter2="...")``; a key's
    ``__`` stands for ``/`` (``routes__hana``) and ``.vns`` is added."""
    scripts = dict(R_SCRIPTS)
    for name, text in changes.items():
        scripts[name.replace("__", "/") + ".vns"] = text
    return scripts


def r_line(ref: str, line: int, text: str, scripts: dict[str, str] | None = None) -> dict:
    """R's scripts (or ``scripts``) with line ``line`` of ``ref`` replaced by ``text``."""
    scripts = dict(R_SCRIPTS if scripts is None else scripts)
    lines = scripts[ref].split("\n")
    lines[line - 1] = text
    scripts[ref] = "\n".join(lines)
    return scripts


ROW1 = r_line("main.vns", 7, "    jump club_poen",
              r_line("chapter2.vns", 11, '        sayori "It\'s {b}nice{/b}.'))
SIXTY = r_line("main.vns", 2, 'include "routes/hana.vns"\ninclude "extra.vns"',
               {**R_SCRIPTS, "extra.vns": "label extra:\n" + "    jmup x\n" * 60})
CJK = r_line("chapter2.vns", 11, '        sayori "日本語のせりふ {b}です')
BAD_CONFIG = b"[window]\nwidth = 'wide'\n"


def load(game: Path, start: str | None = None, names: tuple[str, ...] = (),
         paths: GamePaths | None = None) -> LoadResult:
    return load_story(paths or GamePaths.for_game(game),
                      LoadOptions(start=start, start_names=names))


def expected_report(game: Path, *, start: str | None = None,
                    names: tuple[str, ...] = ()) -> Report:
    """The report the child builds for ``game``'s load or config errors, built in process
    the same way (``loading.py`` → ``show_fatal_error`` → ``EditorLink.fatal``)."""
    paths = GamePaths.for_game(game)
    config = load_config(paths)
    if config.errors:
        error = ConfigErrorGroup(config.errors)
    else:
        error = ScriptErrorGroup.from_result(load(game, start, names, paths))
    return decoded(encode_line(build_report(error, phase="start")))


# --- AC-F44-01, 02: the start options in a new game (headless) --------------------------------

def interpreter(tmp_path: Path, start: StartOptions | None, scripts=None) -> Interpreter:
    game = make_game(tmp_path / "my_game", scripts)
    result = load(game)
    assert result.program is not None, [e.format() for e in result.errors]
    launched = run_launch(result.program)
    assert launched.namespace is not None
    return Interpreter(result.program, launched.namespace, start=start)


def where(interp: Interpreter) -> tuple[str, int]:
    stmt = interp.current
    return stmt.file.ref, stmt.line


def to_first_say(interp: Interpreter) -> Say:
    interp.run(10_000)
    assert interp.status is Status.WAITING
    (say,) = [c for c in interp.take_commands(1 << 20) if type(c) is Say]
    return say


def test_ac01_every_new_game_begins_at_the_start_label(tmp_path):
    interp = interpreter(tmp_path, StartOptions(label="club_poem"))
    interp.new_game(1)
    assert where(interp) == ("script/chapter2.vns", 7)            # the first statement run
    say = to_first_say(interp)
    assert say.text == "It's {b}nice{/b}." and where(interp) == ("script/chapter2.vns", 11)
    interp.new_game(2)                                             # a second new game
    assert where(interp) == ("script/chapter2.vns", 7)


def test_ac01_first_lines(tmp_path):
    for i, (start, first) in enumerate([(StartOptions(label="hana_route"), "Hana's route."),
                                        (None, "Opening line."),
                                        (StartOptions(), "Opening line.")]):
        interp = interpreter(tmp_path / str(i), start)
        interp.new_game(1)
        assert to_first_say(interp).text == first, start


AC02_ROWS = [
    ("sayo_points=1", lambda G, say: say.text == "You wrote a poem? Let me see!"
     and G["max_pts"] == 3),
    ("seen=['x']", lambda G, say: G["seen"] == ["x", "poem"]),
    ("trust='high'", lambda G, say: G["trust"] == "high"),
    (None, lambda G, say: G["seen"] == ["poem"] and say.text == "It's {b}nice{/b}."),
]


def test_ac02_set_values_replace_defaults_after_defaults_run(tmp_path):
    for i, (arg, check) in enumerate(AC02_ROWS):
        values = (parse_set(arg),) if arg is not None else ()
        interp = interpreter(tmp_path / str(i), StartOptions(label="club_poem", values=values))
        for seed in (1, 2):                                        # not shared between games
            interp.new_game(seed)
            say = to_first_say(interp)
            assert check(interp.G, say), (arg, dict(interp.G))
            state = interp.checkpoint().to_json()
            assert json.loads(json.dumps(state)) == state          # plain JSON types
        if arg is not None:
            name, value = values[0]
            assert state["variables"][name] == (["x", "poem"] if name == "seen" else value)


# --- AC-F44-05, 06: unknown labels and names are load errors ----------------------------------

AC05_ROWS = {
    "near_label": (R_SCRIPTS, "club_poen", (), ["E26b"], ["club_poen", "club_poem"], []),
    "label_case": (R_SCRIPTS, "Club_Poem", (), ["E26b"], ["club_poem"], []),
    "no_label": (R_SCRIPTS, "zzz", (), ["E26b"], ["zzz"], ["Did you mean"]),
    "near_name": (R_SCRIPTS, None, ("sayo_point",), ["E26c"],
                  ["sayo_point", "default", "sayo_points"], []),
    "a_define": (R_SCRIPTS, None, ("wish_cost",), ["E26c"], ["wish_cost", "define", "default"],
                 []),
    "a_character": (R_SCRIPTS, None, ("sayori",), ["E26c"], ["sayori", "define", "default"], []),
    "no_name": (R_SCRIPTS, None, ("nobody",), ["E26c"], ["nobody"], ["Did you mean"]),
    "three_errors": (r_line("main.vns", 7, "    jump nowhere"), "zzz", ("sayo_point",),
                     ["E43", "E26b", "E26c"], [], []),
}


def test_ac05_start_options_are_checked_at_load(tmp_path):
    for row in sorted(AC05_ROWS):
        scripts, label, names, codes, has, lacks = AC05_ROWS[row]
        game = make_game(tmp_path / row / "my_game", scripts)
        errors = load(game, label, names).errors
        assert [e.code for e in errors] == codes, row
        for error in errors:
            if error.code.startswith("E26"):
                assert error.file is None and error.line is None and error.column is None
                text = error.format()                              # AC-F02-38
                assert not BANNED_CASED.search(text) and not BANNED_ANY.search(text), row
        text = errors[-1].format()
        assert all(part in text for part in has), (row, text)
        assert not any(part in text for part in lacks), (row, text)


def test_ac05_the_start_checks_are_skipped_exactly_when_e43_is(tmp_path):
    """AC-F44-05's last row says an invalid-UTF-8 ``chapter2.vns`` skips E26b "like E43".
    F02 doesn't skip E43 there (it salvages the file's names, §7.6.2), so E26b follows E43
    and stays; a file that can't be read at all skips both."""
    game = make_game(tmp_path / "my_game", r_line("main.vns", 7, "    jump nowhere"))
    path = game / "script" / "chapter2.vns"
    path.write_bytes(path.read_bytes().replace(b"Chapter 2", b"Chapter \xff"))
    assert [e.code for e in load(game, "zzz").errors] == ["E43", "E01a", "E26b"]
    game = make_game(tmp_path / "unread", r_line("main.vns", 2, 'include "missing.vns"'))
    result = load(game, "zzz", ("nobody",))
    assert [e.code for e in result.errors] == ["E91"] and result.checks_skipped


def test_ac06_a_label_in_a_file_no_file_includes(tmp_path):
    game = make_game(tmp_path / "my_game")
    reads: list[str] = []

    class Spy(GamePaths):
        def read_file(self, ref, *, max_bytes):
            reads.append(ref)
            return super().read_file(ref, max_bytes=max_bytes)

    spy = Spy(game.resolve())
    (error,) = load(game, "late_scene", paths=spy).errors
    assert error.code == "E26b"
    assert "script/chapter3.vns" in error.format()
    assert 'include "chapter3.vns"' in error.format()
    assert reads.count("script/chapter3.vns") == 1
    reads.clear()
    assert not load(game, "club_poem", paths=spy).errors
    assert "script/chapter3.vns" not in reads


# --- The wiring: run --set reaches the load (E26c), with and without the editor ---------------

@pytest.mark.display
def test_set_names_reach_the_load_through_the_cli(tmp_path, user_roots, session, stdout,
                                                  error_screens):
    game = make_game(tmp_path / "my_game")
    argv = ["run", str(game), "--start", "club_poem", "--set", "sayo_point=1"]
    assert cli.main([*argv, "--report-to-editor"]) == 1
    (line,) = lines_of(stdout)
    report = decoded(line)
    assert report.phase == "start" and error_screens == []
    assert report == expected_report(game, start="club_poem", names=("sayo_point",))
    (item,) = report.items
    assert item.text == format_message("E26c", ("sayo_point", False, "sayo_points"))
    assert cli.main(argv) == 1                                     # the error screen instead
    (screen,) = error_screens
    assert screen.message == "\n\n".join(report.paragraphs())


# --- AC-F44-09: the error report equals the error screen (in process) -------------------------

HOOK_ERROR = RuntimeError("a test hook failed before the story started")


def _raise_on_ready(app):
    raise HOOK_ERROR


AC09_ROWS = {
    "two_errors": (ROW1, b'[game]\ntitle = "My Game"\n', None, None),
    "sixty_errors": (SIXTY, b'[game]\ntitle = "My Game"\n', None, None),
    "start_zzz": (R_SCRIPTS, b'[game]\ntitle = "My Game"\n', "zzz", None),
    "bad_config": (R_SCRIPTS, BAD_CONFIG, None, None),
    "hook_raises": (R_SCRIPTS, b'[game]\ntitle = "My Game"\n', None, _raise_on_ready),
    "cjk_line": (CJK, b'[game]\ntitle = "My Game"\n', None, None),
}


@pytest.mark.display
@pytest.mark.parametrize("row", sorted(AC09_ROWS))
def test_ac09_the_report_equals_the_error_screen(tmp_path, user_roots, session, stdout,
                                                 error_screens, monkeypatch, row):
    scripts, config, label, hook = AC09_ROWS[row]
    game = make_game(tmp_path / "my_game", scripts, config=config)
    if hook is not None:
        monkeypatch.setattr(bootstrap, "build_initial_screens", hook)
    start = StartOptions(label=label) if label else None
    assert launch(game, start=start) == 1
    (line,) = lines_of(stdout)
    assert line.isascii()
    report = decoded(line)
    assert report.phase == "start" and error_screens == []        # never pushed
    assert launch(game, start=start, editor_report=False) == 1
    (screen,) = error_screens
    # These games name no path to redact. The screen cuts a very long text (60 errors) with
    # "…"; the panel keeps all of it.
    shown = "\n\n".join(report.paragraphs())
    assert shown == screen.message or (screen.message.endswith("…")
                                       and shown.startswith(screen.message[:-1]))
    if hook is not None:
        (item,) = report.items
        assert item.text == redact(engine_error_message(HOOK_ERROR))
        assert item.file is None
        return
    assert report == expected_report(game, start=label)
    if row == "two_errors":
        first, second = report.items                   # F02's reading order (AC-F02-39)
        assert (first.file, first.line, first.column) == ("script/main.vns", 7, None)
        assert (second.file, second.line, second.column) == ("script/chapter2.vns", 11, 16)
    elif row == "sixty_errors":
        assert len(report.items) == 50 and report.problem_count == 60
        assert report.tail[0].startswith("…and 10 more problems.")
    elif row == "start_zzz":
        (item,) = report.items
        assert (item.file, item.line, item.column) == (None, None, None)
    elif row == "bad_config":
        (item,) = report.items
        assert item.file == "config.toml"
    elif row == "cjk_line":
        assert "日本語のせりふ" in report.items[0].text


@pytest.mark.display
def test_ac09_no_report_names_the_users_home(tmp_path, user_roots, session, stdout,
                                             monkeypatch):
    home = tmp_path / "vn_user_7f3a"
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    game = make_game(home / "my_game", ROW1)
    assert launch(game) == 1
    (line,) = lines_of(stdout)
    assert b"vn_user_7f3a" not in line
    assert len(decoded(line).items) == 2


# --- Real children (CHILD of 06 §0.3) --------------------------------------------------------

def child_env(base: Path) -> dict[str, str]:
    """The per-user roots under ``base`` and the SDL dummy drivers."""
    env = roots_env(base)
    env["SDL_AUDIODRIVER"] = "dummy"
    return env


class RealPopen:
    """The runner's ``popen`` for real children: its own argv, cwd, and environment, plus
    the test's per-user roots and dummy drivers."""

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env

    def __call__(self, argv, **kwargs):
        env = dict(kwargs.pop("env"))
        env.update(self.env)
        return subprocess.Popen(argv, env=env, **kwargs)


def run_child(game: Path, *args: str, env: dict[str, str], report: bool = True,
              timeout: float = 30.0) -> tuple[int, list, bytes, str]:
    """CHILD(args): (exit code, decoded report lines, stdout, stderr). The child is killed
    if it outlives ``timeout``."""
    argv = [sys.executable, "-m", "engine", "run", str(game),
            *(["--report-to-editor"] if report else []), "--log-level", "debug", *args]
    done = subprocess.run(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    lines = [line for line in done.stdout.splitlines() if line.startswith(REPORT_MARKER)]
    return (done.returncode, [decode_report(line) for line in lines], done.stdout,
            done.stderr.decode("utf-8", "replace"))


def digests(folder: Path) -> dict[str, str]:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


def log_text(game: Path) -> str:
    path = game / "logs" / "latest.log"
    return path.read_text("utf-8", "replace") if path.exists() else ""


@pytest.mark.slow
@pytest.mark.parametrize("row", sorted(AC05_ROWS))
def test_ac05_the_child_reports_the_load_error(tmp_path, row):
    scripts, label, names, codes, _, _ = AC05_ROWS[row]
    game = make_game(tmp_path / "my_game", scripts)
    args = [*(["--start", label] if label else []),
            *(arg for name in names for arg in ("--set", f"{name}=1"))]
    code, reports, _, _ = run_child(game, *args, env=child_env(tmp_path))
    assert code == 1
    (report,) = reports
    assert report == expected_report(game, start=label, names=names)
    assert len(report.items) == len(codes)


@pytest.mark.slow
def test_ac05_without_the_editor_the_error_screen_shows_and_exits_1(tmp_path):
    game = make_game(tmp_path / "my_game")
    env = child_env(tmp_path)
    proc = subprocess.Popen([sys.executable, "-m", "engine", "run", str(game), "--set",
                             "sayo_point=1", "--bench", "1"], cwd=REPO, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        out, _ = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 1 and REPORT_MARKER not in out
    assert '"sayo_point" has no default' in log_text(game)


@pytest.mark.slow
@pytest.mark.parametrize("row", ["two_errors", "sixty_errors", "start_zzz", "bad_config",
                                 "cjk_line"])
def test_ac09_the_childs_report(tmp_path, row):
    scripts, config, label, _ = AC09_ROWS[row]
    game = make_game(tmp_path / "my_game", scripts, config=config)
    began = time.monotonic()
    code, reports, out, _ = run_child(game, *(["--start", label] if label else []),
                                      env=child_env(tmp_path))
    assert code == 1 and time.monotonic() - began < 10
    assert out.isascii()
    (report,) = reports
    assert report.phase == "start"
    assert report == expected_report(game, start=label)


@pytest.mark.slow
def test_ac09_the_childs_report_never_names_the_users_home(tmp_path):
    home = tmp_path / "vn_user_7f3a"
    env = child_env(tmp_path)
    env.update(HOME=str(home), USERPROFILE=str(home))
    game = make_game(home / "my_game", ROW1)
    code, reports, out, _ = run_child(game, env=env)
    assert code == 1 and len(reports) == 1
    assert b"vn_user_7f3a" not in out


def _shells() -> list[tuple[str, list[str]]]:
    """The installed shells of AC-F44-02's quoting rows, each with the command prefix that
    runs one command line. WSL's ``bash.exe`` (System32) can't run Windows paths."""
    found = []
    if sys.platform == "win32":
        found.append(("cmd", ["cmd", "/s", "/c"]))
        if shutil.which("powershell"):
            found.append(("powershell", ["powershell", "-NoProfile", "-Command"]))
    bash = shutil.which("bash")
    if bash and "system32" not in bash.lower():
        found.append(("bash", [bash, "-c"]))
    return found


@pytest.mark.slow
def test_ac02_the_documented_set_form_survives_each_shell(tmp_path):
    """``--set "hana_name='Hana'"`` typed in cmd, PowerShell, and bash reaches the game
    as the text ``Hana`` (a ``print`` probe at ``start`` logs it)."""
    env = child_env(tmp_path)
    scripts = r_line("main.vns", 6, '    $ print("name", hana_name)\n    "Opening line."')
    scripts = r_line("main.vns", 4, 'default trust = 0\ndefault hana_name = "???"', scripts)
    procs = {}
    try:
        for name, prefix in _shells():
            game = make_game(tmp_path / name, scripts)
            python, folder = (Path(sys.executable).as_posix(), game.as_posix()) \
                if name == "bash" else (sys.executable, str(game))
            if name == "powershell":
                line = (f"& '{python}' -m engine run '{folder}' --bench 1 "
                        "--set \"hana_name='Hana'\"")
            else:
                line = (f'"{python}" -m engine run "{folder}" --bench 1 '
                        "--set \"hana_name='Hana'\"")
            command = (" ".join(prefix) + f' "{line}"') if name == "cmd" else [*prefix, line]
            procs[name] = (game, subprocess.Popen(command, cwd=REPO, env=env,
                                                  stdin=subprocess.DEVNULL,
                                                  stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.PIPE))
        for name, (game, proc) in procs.items():
            _, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, (name, err.decode("utf-8", "replace")[-2000:])
            assert "print: name Hana" in log_text(game), name
    finally:
        for _, proc in procs.values():
            if proc.poll() is None:
                proc.kill()
                proc.wait()


@pytest.mark.slow
def test_ac01_the_new_game_log_line_names_the_start_label(tmp_path):
    game = make_game(tmp_path / "my_game")
    code, reports, _, _ = run_child(game, "--start", "club_poem", "--set", "sayo_points=1",
                                    "--bench", "1", env=child_env(tmp_path))
    assert code == 0 and reports == [STARTED]
    assert 'starting at "club_poem", 1 start value.' in log_text(game)


@pytest.mark.slow
def test_ac08_the_started_report_and_a_closed_pipe(tmp_path):
    game = make_game(tmp_path / "my_game")
    env = child_env(tmp_path)
    base = [sys.executable, "-m", "engine", "run", str(game), "--bench", "1"]
    procs = {
        "report": subprocess.Popen([*base, "--report-to-editor"], cwd=REPO, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE),
        "plain": subprocess.Popen(base, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE),
        "closed": subprocess.Popen([*base, "--report-to-editor"], cwd=REPO, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE),
    }
    procs["closed"].stdout.close()                     # before the child starts the story
    results = {}
    try:
        for name, proc in procs.items():
            if name == "closed":
                err = proc.stderr.read()
                proc.wait(30)
                results[name] = (proc.returncode, b"", err)
            else:
                out, err = proc.communicate(timeout=30)
                results[name] = (proc.returncode, out, err)
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    code, out, _ = results["report"]
    assert code == 0
    lines = [line for line in out.splitlines() if line.startswith(REPORT_MARKER)]
    assert len(lines) == 1 and lines[0].isascii()
    assert json.loads(lines[0][len(REPORT_MARKER):]) == {"v": 1, "event": "started"}
    code, out, _ = results["plain"]
    assert code == 0 and REPORT_MARKER not in out
    code, _, err = results["closed"]
    assert code == 0
    assert b"Traceback" not in err and b"BrokenPipeError" not in err
    assert b"Exception ignored" not in err


@pytest.mark.slow
def test_ac10_real_children_and_ac17_nothing_is_written(tmp_path):
    good = make_game(tmp_path / "my_game")
    bad = make_game(tmp_path / "bad_game", r_line("main.vns", 7, "    jump club_poen"))
    before = digests(good / "script")
    runners = Runners()
    try:
        runner = runners.make(popen=RealPopen(child_env(tmp_path)))
        runner.start(preview_argv(good, "club_poem", ["--set", "sayo_points=1"]))
        assert states(run_until(runner, S.RUNNING)) == [S.STARTING, S.RUNNING]
        proc = runner.process
        began = time.monotonic()
        runner.stop()
        assert proc.poll() is not None and time.monotonic() - began < 2.5
        assert digests(good / "script") == before                 # AC-F44-17's last row
        runner = runners.make(popen=RealPopen(child_env(tmp_path)))
        runner.start(preview_argv(bad, None, []))
        events = run_until(runner, S.DIDNT_START)
        assert states(events) == [S.STARTING, S.DIDNT_START]
        assert events[-1].report == expected_report(bad)
        assert runners.procs[-1].returncode == 1
    finally:
        runners.close()


# --- The editor with real children ------------------------------------------------------------

def tk_kit():
    """The Tk helpers of ``test_window_preview`` (skips without Tk)."""
    pytest.importorskip("tkinter")
    from tests.tools.editor import test_window_preview as kit
    return kit


@pytest.fixture
def editors(tmp_path, monkeypatch):
    """``editors(game) -> Editor`` (mapped at ``+-3000+-3000``) whose runner starts real
    children with the test's per-user roots; ``.statuses`` records every status shown."""
    kit = tk_kit()
    window = kit.window
    roots: list = []
    runners = Runners()
    callback_errors: list = []
    errors_shown: list[str] = []
    monkeypatch.setattr(window.messagebox, "showerror",
                        lambda title, message, **kwargs: errors_shown.append(message))
    env = child_env(tmp_path)

    def build(game: Path):
        root = kit.new_root()
        roots.append(root)
        root.report_callback_exception = lambda *info: callback_errors.append(info)
        root.withdraw()
        runner = runners.make(popen=RealPopen(env))
        ed = kit.Editor(window.EditorWindow(root, GamePaths.for_game(game), runner=runner,
                                            check_runner=kit.NoChecks()), errors_shown)
        ed.runners = runners
        ed.statuses = []
        show_event = ed.win.show_event

        def recording(event):
            show_event(event)
            ed.statuses.append(ed.status_label.cget("text"))

        ed.win.show_event = recording
        root.geometry("+-3000+-3000")
        root.deiconify()
        root.update()
        return ed

    try:
        yield build
    finally:
        runners.close()
        for root in roots:
            try:
                root.destroy()
            except kit.tk.TclError:
                pass
    assert not callback_errors, callback_errors


@pytest.mark.tk
def test_smoke_f5_shows_the_childs_e26c_in_the_panel(editors, route_game):
    """The default tier's one real launch: F5 in ``club_poem`` with a misspelled start
    value; the child's load error (E26c, AC-F44-05) is the panel (AC-F44-27's last clause,
    AC-F44-28), and nothing is clickable."""
    kit = tk_kit()
    ed = editors(route_game)
    ed.open_file("script/chapter2.vns")
    ed.text.mark_set("insert", "9.0")
    kit.set_box(ed, "sayo_point = 1")
    ed.idle()
    ed.press(ed.text, "<F5>")
    kit.pump(ed, lambda: kit.status(ed).startswith("Didn't start"))
    (argv, _), = ed.runners.calls
    assert argv[-4:] == ["--start", "club_poem", "--set", "sayo_point = 1"]
    assert ed.statuses == [STARTING, "Didn't start: 1 problem, listed in Problems."]
    expected = expected_report(route_game, start="club_poem", names=("sayo_point",))
    assert ed.panel_paragraphs() == expected.paragraphs() == [
        "The script has 1 problem:",
        format_message("E26c", ("sayo_point", False, "sayo_points"))]
    assert not any(p.clickable for p in ed.paragraphs)
    assert ed.runners.procs[0].wait(5) == 1
    assert ed.focus() is ed.text


@pytest.mark.tk
@pytest.mark.slow
def test_ac26_f5_plays_the_real_game_from_the_cursor(editors, route_game):
    """AC-F44-26 with the real child, AC-F44-31 (b), AC-F44-17's full-session row. A
    ``print`` probe in the branch shows where the game started and with which values (the
    stand-in logs no ``Say``)."""
    kit = tk_kit()
    script = route_game / "script"
    before = digests(script)
    ed = editors(route_game)
    ed.text.insert("1.0", "# edited\n")                           # main.vns
    ed.open_file("script/chapter2.vns")
    ed.text.insert("9.0", '        $ print("probe", sayo_points, max_pts, seen)\n')
    ed.text.mark_set("insert", "10.0")                            # sayori's line
    kit.set_box(ed, "sayo_points = 1\n# comment\n\nseen = ['x']")
    ed.idle()
    ed.press(ed.text, "<F5>")
    kit.pump(ed, lambda: kit.status(ed) == RUNNING)
    assert ed.statuses == [STARTING, RUNNING]
    assert kit.panel_text(ed) == "No problems."
    (argv, kwargs), = ed.runners.calls
    assert argv[3:8] == ["run", str(ed.paths.root), "--report-to-editor", "--start",
                         "club_poem"]
    assert [parse_set(arg) for arg in argv[9::2]] == [("sayo_points", 1), ("seen", ["x"])]
    assert kwargs["stdin"] is subprocess.DEVNULL
    end = time.monotonic() + 10
    while "print: probe" not in log_text(route_game) and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.05)
    assert "print: probe 1 3 ['x', 'poem']" in log_text(route_game)
    proc = ed.runners.procs[0]
    began = time.monotonic()
    ed.win.on_close()                                             # AC-F44-31 (b)
    assert proc.poll() is not None and time.monotonic() - began < 2.5
    after = digests(script)
    assert set(after) == set(before)
    assert {ref for ref in after if after[ref] != before[ref]} == {"main.vns", "chapter2.vns"}


@pytest.mark.tk
@pytest.mark.slow
def test_ac31c_a_run_time_error_is_listed_and_the_game_stays_open(editors, tmp_path):
    kit = tk_kit()
    game = make_game(tmp_path / "my_game", r_line("chapter2.vns", 7, "    $ seen.append(1/0)"))
    ed = editors(game)
    ed.open_file("script/chapter2.vns")
    ed.text.mark_set("insert", "9.0")
    ed.idle()
    ed.press(ed.text, "<F5>")
    kit.pump(ed, lambda: kit.status(ed) == STOPPED_ERROR)
    assert ed.statuses == [STARTING, RUNNING, STOPPED_ERROR]
    proc = ed.runners.procs[0]
    end = time.monotonic() + 2
    while time.monotonic() < end:
        ed.root.update()
        time.sleep(0.05)
    assert proc.poll() is None                         # the child's error screen shows
    assert kit.status(ed) == STOPPED_ERROR
    (paragraph,) = [p for p in ed.paragraphs if p.clickable]
    assert (paragraph.item.file, paragraph.item.line) == ("script/chapter2.vns", 7)
    kit.click_paragraph(ed, ed.paragraphs.index(paragraph))
    assert ed.current.ref == "script/chapter2.vns"
    assert ed.text.index("insert").split(".")[0] == "7"


# --- AC-F44-28, 29: the panel and the jump, with reports built as the child builds them -------

@pytest.fixture
def report_editor(editors, tmp_path):
    """``report_editor(scripts, config=…, start=…) -> (Editor, Report)``: game R's variant
    in an editor whose panel shows the load's report, as F5 would (no child)."""

    def build(scripts, *, config: bytes = b'[game]\ntitle = "My Game"\n',
              start: str | None = None, name: str = "my_game"):
        game = make_game(tmp_path / name, scripts, config=config)
        report = expected_report(game, start=start)
        ed = editors(game)
        ed.show_event(PreviewEvent(S.DIDNT_START, report))
        return ed, report

    return build


@pytest.mark.tk
@pytest.mark.parametrize("row, clickable", [
    # AC-F44-28's first row (ROW1, both clickable) is
    # test_window_preview::test_a_load_error_report_fills_the_panel_with_links, and
    # test_ac09_the_report_equals_the_error_screen[two_errors] shows the real report is that.
    ("bad_config", [False]),
    ("late_scene", [False, False]),
    ("sixty_errors", [False] + [True] * 50 + [False]),
])
def test_ac28_the_panel_shows_the_report_and_links_only_line_errors(report_editor, row,
                                                                    clickable):
    kit = tk_kit()
    scripts, config, start = {
        "bad_config": (R_SCRIPTS, BAD_CONFIG, None),
        "late_scene": (R_SCRIPTS, b'[game]\ntitle = "My Game"\n', "late_scene"),
        "sixty_errors": (SIXTY, b'[game]\ntitle = "My Game"\n', None),
    }[row]
    ed, report = report_editor(scripts, config=config, start=start)
    count = report.problem_count
    assert kit.status(ed) == (f"Didn't start: {count} problem{'s' * (count != 1)}, "
                              "listed in Problems.")
    assert ed.panel_paragraphs() == report.paragraphs()
    assert [p.clickable for p in ed.paragraphs] == clickable
    if not any(clickable):
        insert = ed.text.index("insert")
        kit.click_paragraph(ed, len(ed.paragraphs) - 1)
        assert str(ed.problems.cget("cursor")) == "arrow"
        assert ed.current.ref == "script/main.vns" and ed.text.index("insert") == insert
        assert ed.problems.tag_ranges(kit.window.TAG_LINK) == ()


@pytest.mark.tk
@pytest.mark.parametrize("name", sorted(SEEDED))
def test_ac29_one_click_lands_on_each_seeded_mistake(report_editor, name):
    kit = tk_kit()
    ed, report = report_editor(seeded_scripts(name), name=name)
    ref, line = SEEDED[name][3]
    (index,) = [i for i, p in enumerate(ed.paragraphs) if p.clickable]
    item = ed.paragraphs[index].item
    assert (item.file, item.line) == (ref, line)
    kit.click_paragraph(ed, index)
    assert ed.current.ref == ref and ed.focus() is ed.text
    column = (item.column or 1) - 1
    assert ed.text.index("insert") == f"{line}.{column}"
    assert [str(i) for i in ed.text.tag_ranges(kit.window.TAG_JUMP)] == [f"{line}.0",
                                                                          f"{line + 1}.0"]
