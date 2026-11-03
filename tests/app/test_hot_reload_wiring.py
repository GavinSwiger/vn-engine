"""F39 W1: the game side of hot reload wired into the CLI, the bootstrap, the App's frame and
the shell (``specs/F39-hot-reload/SPEC.md`` §5.1, §5.2, §5.4).

AC-F39-10 (the CLI's two hidden dev-run options, and no stdin reader without
``--report-to-editor``), AC-F39-11 (a ``reload`` at a line hands the place over and quits
cleanly; the resume launch shows the same line, N1, no title or F33 warning) and AC-F39-12
(the error loop: a run error, ``reload``, a ``default`` that fails at the resume, ``reload``
again). The launches are in process (``scripted_app``: fake frame clock, hidden window) with
stdin fed through ``Feed`` and stdout read back with Studio's own ``read_child_output``, so
both sides keep to one protocol. The real two-process run is W1's manual end-to-end check.
"""

import io
import queue
import sys
import time
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap, cli
from engine.app import hot_reload as hr
from engine.core.editorreport import RELOAD_MESSAGE
from engine.persist import limits
from engine.persist.saves import SLOT_NAME_RE
from engine.tools.editor import hotreload as studio
from engine.tools.editor.preview import EOF, STARTED, STATE, Report, read_child_output
from engine.ui.builtin.content_warning import ContentWarningScreen
from engine.ui.builtin.error import ErrorScreen
from engine.ui.builtin.title_screen import TitleScreen
from tests.app.test_saves_service import line_text, notices
from tests.fakes.loop import post_key
from tests.fakes.spy_window import SpyWindow

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]
CONFIG = """[game]
id = "f39-wiring"
title = "Reload Test"
version = "1.0"

[saves]
autosave_quit = true

[content_warning]
show = "always"
text = "This story has spiders."
"""
LINES = "".join(f'    "L{n}"\n' for n in range(1, 8))
SCRIPT = f"label start:\n    $ persistent.seen_start = True\n{LINES}    return\n"


class Feed(io.RawIOBase):
    """The child's stdin: bytes ``send`` hands over arrive in order; ``end`` is EOF."""

    def __init__(self) -> None:
        self._chunks: "queue.SimpleQueue[bytes | None]" = queue.SimpleQueue()
        self._buf = b""
        self._eof = False

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        while not self._buf and not self._eof:
            chunk = self._chunks.get()
            if chunk is None:
                self._eof = True
            else:
                self._buf = chunk
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n

    def send(self, data: bytes) -> None:
        self._chunks.put(data)

    def end(self) -> None:
        self._chunks.put(None)


class Child:
    """One in-process launch with ``--report-to-editor``: its stdin, stdout, App and every
    screen type it showed."""

    def __init__(self, session, monkeypatch, capsysbinary, game: Path, *,
                 frame: bytes | None = None, start: bool = False,
                 window_at: tuple[int, int] | None = None) -> None:
        self.session = session
        self.capture = capsysbinary
        self.game = game
        self.feed = Feed()
        self.stdin = io.BufferedReader(self.feed)
        self.resume = frame is not None
        if frame is not None:
            self.feed.send(frame)
        self.start = start
        self.window_at = window_at
        self.shown: set[type] = set()
        self.events: list[tuple[str, object]] = []
        self.code: int | None = None
        monkeypatch.setattr(bootstrap, "_editor_input", lambda: self.stdin)

    def run(self, script, *, last: int = 900) -> "Child":
        from engine.core.startvalues import StartOptions

        session = self.session
        session.actions = []
        state: dict = {}

        def step(app) -> None:
            self.shown.update(type(screen) for screen in app.screens)
            if state.get("done"):
                return
            if "gen" not in state:
                state["gen"] = script(app, self)
            try:
                next(state["gen"])
            except StopIteration:
                state["done"] = True

        for n in range(2, last):
            session.at(n, step)
        session.quit_frame = last
        self.capture.readouterr()
        try:
            self.code = bootstrap.launch(
                self.game, release=False, bench_seconds=None, log_level_override=None,
                pygame_warning=None, editor_report=True, resume=self.resume,
                window_at=self.window_at,
                start=StartOptions(label="start") if self.start else None)
        finally:
            self.feed.end()
        out = self.capture.readouterr().out
        read_child_output(io.BytesIO(out), self.events.append, lambda line: None)
        return self

    @property
    def app(self):
        return self.session.apps[-1]

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events if kind != EOF]

    def frame(self):
        (frame,) = [payload for kind, payload in self.events if kind == STATE]
        return frame


def make_game(tmp_path: Path, script: str = SCRIPT, name: str = "game") -> Path:
    root = tmp_path / name
    (root / "script").mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(CONFIG, encoding="utf-8")
    (root / "script" / "main.vns").write_text(script, encoding="utf-8")
    return root


def advance(app, text: str):
    """Space until ``text`` is the shown line."""
    for _ in range(400):
        if line_text(app) == text and app.screens.top is app.textbox:
            return
        post_key(pygame.K_SPACE)
        yield
        yield
    raise AssertionError(f"never reached {text!r}: at {line_text(app)!r}")


def reload(app, child: Child):
    """Studio's ``reload``; then frames (with a little real time for the reader thread)
    until the App quits."""
    child.feed.send(RELOAD_MESSAGE)
    for _ in range(400):
        time.sleep(0.005)
        yield


def wait_for(pred):
    for _ in range(600):
        if pred():
            return
        time.sleep(0.002)
        yield
    raise AssertionError("timed out")


def slot_files(game: Path) -> list[str]:
    folder = game / "saves"
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if SLOT_NAME_RE.fullmatch(p.name))


# --- AC-F39-10: the CLI --------------------------------------------------------------------

def test_ac_f39_10_cli_options_are_dev_only_and_checked(tmp_path, capsys, monkeypatch,
                                                        scripted_app):
    game = make_game(tmp_path)
    real_launch = bootstrap.launch
    launched: list[dict] = []
    monkeypatch.setattr(bootstrap, "launch",
                        lambda game_dir, **kwargs: launched.append(kwargs) or 0)

    def usage(*args: str) -> str:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["run", str(game), *args])
        assert exit_info.value.code == 2
        return capsys.readouterr().err.strip().splitlines()[-1]

    # Studio's argv reaches the launch: one-item --window-at, a negative X included.
    assert cli.main(["run", str(game), "--report-to-editor", "--resume-from-editor",
                     "--window-at=-120,80"]) == 0
    assert (launched[-1]["resume"], launched[-1]["window_at"]) == (True, (-120, 80))
    assert cli.main(["run", str(game), "--window-at", "100000,-100000"]) == 0
    assert (launched[-1]["resume"], launched[-1]["window_at"]) == (False, (100_000, -100_000))
    assert cli.main(["run", str(game)]) == 0
    assert (launched[-1]["resume"], launched[-1]["window_at"]) == (False, None)
    # --release with either one: exit 2 naming it.
    assert usage("--release", "--resume-from-editor").endswith(
        "error: --resume-from-editor is only available in dev runs")
    assert usage("--release", "--window-at=1,1").endswith(
        "error: --window-at is only available in dev runs")
    # The --window-at text, verbatim; past 100,000 is refused the same way.
    for bad in ("100001,0", "0,-100001", "1", "1,2,3", "a,b", "1.5,2", " 1,2", "+1,2", "١,٢",
                ""):
        assert usage(f"--window-at={bad}").endswith(
            "error: --window-at needs two whole numbers, like 120,80"), bad
    # The frame arrives on stdin, which is read only with --report-to-editor.
    assert usage("--resume-from-editor").endswith(
        "error: --resume-from-editor needs --report-to-editor")
    # Hidden from run --help.
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    help_text = capsys.readouterr().out
    assert "resume" not in help_text and "window-at" not in help_text
    # Never main.py's; a frozen build's run defines neither.
    for args in (["--resume-from-editor"], ["--window-at=1,1"]):
        with monkeypatch.context() as patch:
            patch.setattr(cli, "_launch", lambda *a, **k: pytest.fail("launched"))
            with pytest.raises(SystemExit) as exit_info:
                cli.launcher_main(args)
        assert exit_info.value.code == 2
        capsys.readouterr()
        with monkeypatch.context() as patch:
            patch.setattr(sys, "frozen", True, raising=False)
            patch.setattr(sys, "_MEIPASS", str(REPO), raising=False)
            assert "unrecognized arguments" in usage(*args)
    # Studio's and F11's state-line caps agree (Studio never parses a state).
    assert hr.STATE_LINE_MAX == limits.STATE_MAX_BYTES
    # No stdin reader without --report-to-editor (a real launch, in process).
    readers: list[object] = []
    monkeypatch.setattr(hr.StdinReader, "start", lambda self: readers.append(self) or self)
    monkeypatch.setattr(bootstrap, "_editor_input", lambda: pytest.fail("stdin read"))
    scripted_app.quit_frame = 5
    assert real_launch(game, release=False, bench_seconds=None, log_level_override=None,
                       pygame_warning=None) == 0
    assert scripted_app.apps[-1].editor_link is None and readers == []


# --- AC-F39-11: the game end to end --------------------------------------------------------

def test_ac_f39_11_reload_hands_the_place_over_and_the_resume_shows_it(
        tmp_path, user_roots, scripted_app, monkeypatch, capsysbinary):
    game = make_game(tmp_path, SCRIPT.replace('    "L3"', '    $ persistent.at_l3 = True\n'
                                                        '    "L3"'))
    old = Child(scripted_app, monkeypatch, capsysbinary, game, start=True)

    def at_l3_then_reload(app, child):
        yield from advance(app, "L3")
        app.settings.set("music_volume", 40)
        child.carried = app.story.checkpoint()
        yield from reload(app, child)

    old.run(at_l3_then_reload)
    # The state event, then a clean exit: no quit question, no quit Auto save, the writers
    # flushed (the setting changed just before, persistent data set on the way).
    assert old.code == 0
    assert old.kinds() == [STARTED, STATE]
    assert slot_files(game) == []
    assert '"music_volume": 40' in (game / "settings" / "settings.json").read_text(
        encoding="utf-8")
    assert "at_l3" in (game / "persistent" / "persistent.json").read_text(encoding="utf-8")
    frame = old.frame()
    assert frame.states == 3                                # L3, then L2 and L1 to go back to
    assert hr.parse_state(hr.split_frame(frame.body, 3)[0]) == old.carried

    # Studio's restart: F5's argv without --start, plus the two options; the body unchanged.
    argv, stdin = studio.restart(["python", "-m", "engine", "run", str(game),
                                  "--report-to-editor", "--start", "start"], frame)
    x, y = frame.window
    assert argv == ["python", "-m", "engine", "run", str(game), "--report-to-editor",
                    "--resume-from-editor", f"--window-at={x},{y}"]
    assert stdin.endswith(frame.body)
    new = Child(scripted_app, monkeypatch, capsysbinary, game, frame=stdin, window_at=(x, y))

    def resumed(app, child):
        yield from wait_for(lambda: line_text(app) == "L3")
        child.state = app.story.checkpoint()
        child.notes = notices(app)
        app.request_quit(force=True)
        yield

    new.run(resumed)
    assert new.code == 0
    assert new.kinds()[0] == STARTED
    assert new.state == old.carried
    assert new.notes == [hr.NOTE_UPDATED]
    assert TitleScreen not in new.shown and ContentWarningScreen not in new.shown
    assert hr.ResumeScreen in new.shown
    created = [entry[1] for entry in SpyWindow.log if entry[0] == "create"]
    assert created[-1]["position"] == (x, y)                # the old window's spot


# --- AC-F39-12: the error loop -------------------------------------------------------------

BROKEN = 'label start:\n    "L1"\n    "L2"\n    $ boom = 1 // 0\n    "L3"\n    return\n'
FIXED = 'label start:\n    "L1"\n    "L2"\n    "L3"\n    return\n'
BAD_DEFAULT = "default fresh = 1 // 0\n" + FIXED


def test_ac_f39_12_error_loop(tmp_path, user_roots, scripted_app, monkeypatch, capsysbinary):
    game = make_game(tmp_path, BROKEN)

    def error_then_reload(app, child):
        yield from advance(app, "L2")
        for _ in range(100):
            if app.error_mode:
                break
            post_key(pygame.K_SPACE)
            yield
            yield
        yield from reload(app, child)

    def resume_then_reload(app, child):
        yield from wait_for(lambda: app.error_mode or line_text(app) is not None)
        child.line = line_text(app)
        if app.error_mode:
            yield from reload(app, child)
            return
        child.notes = notices(app)
        app.request_quit(force=True)
        yield

    def errors(child: Child) -> list[str]:
        return [payload.phase for kind, payload in child.events
                if kind == "error" and isinstance(payload, Report)]

    # A run error, then reload: the error screen's place is the last line before the error.
    failed = Child(scripted_app, monkeypatch, capsysbinary, game, start=True).run(
        error_then_reload)
    assert failed.code == 1                                  # a quit from the error screen
    assert failed.kinds() == [STARTED, "error", STATE] and errors(failed) == ["run"]
    frame = failed.frame()
    assert frame.states == 2                                 # L2, then L1
    _, stdin = studio.restart([], frame)

    # A default that fails at the resume: the error screen (phase run); the next reload
    # carries the same states, byte for byte.
    (game / "script" / "main.vns").write_text(BAD_DEFAULT, encoding="utf-8")
    again = Child(scripted_app, monkeypatch, capsysbinary, game, frame=stdin).run(
        resume_then_reload)
    assert again.code == 1
    assert again.kinds() == [STARTED, "error", STATE] and errors(again) == ["run"]
    assert ErrorScreen in again.shown and TitleScreen not in again.shown
    assert (again.frame().body, again.frame().states) == (frame.body, frame.states)

    # Fixed: the update resumes at the line before the first error.
    (game / "script" / "main.vns").write_text(FIXED, encoding="utf-8")
    fixed = Child(scripted_app, monkeypatch, capsysbinary, game,
                  frame=studio.restart([], again.frame())[1]).run(resume_then_reload)
    assert fixed.code == 0 and fixed.kinds()[0] == STARTED
    assert fixed.line == "L2" and fixed.notes == [hr.NOTE_UPDATED]
