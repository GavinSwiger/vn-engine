"""F44: the game side of the editor report protocol (``04`` §3, §5.3, §7.4; ``07`` I-4,
I-7, I-8) and the start options reaching the App and the story load.

TR-F44-05 (the report's texts are ``parts()``'s paragraphs, redacted), TR-F44-06 in process
(a load error writes one ``start`` report, exits 1, never shows the ErrorScreen), the
run-phase rule (after ``started`` the error screen still shows, PR-F44-13), I-4 trimming,
and ``--start`` reaching ``LoadOptions.start`` (E26b). Every report is decoded with the
editor's own ``decode_report``, so both sides keep to the same protocol. The real child
(``test_preview_e2e.py``) is F44 step 6.
"""

import io
import json
import os
from pathlib import Path

import pytest

from engine.app import app as app_module
from engine.app import bootstrap
from engine.app.app import engine_error_message
from engine.app.editor_link import EditorLink, build_report, encode_line
from engine.core.editorreport import (
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_MAX_ITEMS,
    REPORT_TEXT_MAX_CHARS,
)
from engine.core.errors import ConfigError, ConfigErrorGroup, UserFacingError
from engine.core.redact import redact
from engine.core.startvalues import StartOptions
from engine.script import ScriptErrorGroup
from engine.script.diagnostics import ScriptError
from engine.script.messages import format_message
from engine.tools.editor import game_folder_problem
from engine.tools.editor.preview import GAME, STARTED, Report, decode_report
from engine.ui.builtin.error import ErrorScreen
from tests.tools.editor.conftest import R_SCRIPTS

pytestmark = pytest.mark.display


def script_error(n: int, *, text: str = "something is wrong here") -> ScriptError:
    return ScriptError(f"{text} ({n})", code="E40", file="script/a.vns", line=n,
                       column=3, source_line=f"    jump nowhere_{n}")


def decoded(line: bytes) -> Report:
    report = decode_report(line)
    assert isinstance(report, Report), line[:200]
    return report


def lines_of(out) -> list[bytes]:
    return out.getvalue().splitlines()


# --- Report building (TR-F44-05, §7.4) ------------------------------------------------------

def test_tr05_a_script_error_group_reports_its_parts():
    group = ScriptErrorGroup([script_error(4), ScriptError("No label start.", code="E26")],
                             total=53, checks_skipped=True)
    head, pairs, tail = group.parts()
    report = decoded(encode_line(build_report(group, phase="start")))
    assert report.phase == "start"
    assert report.head == redact(head)
    assert [item.text for item in report.items] == [redact(text) for _, text in pairs]
    assert list(report.tail) == [redact(line) for line in tail]
    assert "\n\n".join(report.paragraphs()) == group.format()
    first, second = report.items
    assert (first.file, first.line, first.column) == ("script/a.vns", 4, 3)
    assert (second.file, second.line, second.column) == (None, None, None)
    assert report.problem_count == 53


def test_another_user_facing_error_is_one_item():
    error = UserFacingError("bad value", file="config.toml", line=4, column=9)
    report = decoded(encode_line(build_report(error, phase="start")))
    assert report.head is None and report.tail == ()
    (item,) = report.items
    assert (item.text, item.file, item.line, item.column) == (
        "config.toml, line 4, column 9: bad value", "config.toml", 4, 9)


def test_an_engine_error_is_the_screens_short_text():
    error = KeyError("boom")
    report = decoded(encode_line(build_report(error, phase="run")))
    assert report.phase == "run"
    assert [item.text for item in report.items] == [redact(engine_error_message(error))]
    assert report.items[0].file is None


def test_texts_are_cut_to_the_editor_limit():
    error = UserFacingError("x" * 20_000)
    (item,) = decoded(encode_line(build_report(error, phase="start"))).items
    assert len(item.text) == REPORT_TEXT_MAX_CHARS and item.text.endswith("…")


def test_the_line_is_ascii_json_after_the_marker():
    error = UserFacingError("Ünïcode “quotes” 😀")
    line = encode_line(build_report(error, phase="start"))
    assert line.startswith(REPORT_MARKER) and line.isascii() and b"\n" not in line
    assert json.loads(line[len(REPORT_MARKER):])["items"][0]["text"] == "Ünïcode “quotes” 😀"


# --- I-4: one line at most 1 MiB ------------------------------------------------------------

def test_i4_a_huge_report_drops_items_and_counts_them():
    errors = [script_error(n, text="😀" * 9_000) for n in range(1, 51)]   # ~54 KB each
    group = ScriptErrorGroup(errors, total=50)
    line = encode_line(build_report(group, phase="start"))
    assert len(line) <= REPORT_MAX_BYTES
    report = decoded(line)
    kept = len(report.items)
    assert 1 <= kept < 50
    assert report.tail[0] == f"…and {50 - kept} more problems."
    assert report.problem_count == 50


def test_i4_dropped_items_add_to_f02s_more_problems_line():
    errors = [script_error(n, text="😀" * 9_000) for n in range(1, 51)]
    group = ScriptErrorGroup(errors, total=1_250)               # F02's tail: "…and 1,200 more"
    report = decoded(encode_line(build_report(group, phase="start")))
    dropped = 50 - len(report.items)
    assert report.tail[0] == (f"…and {1_200 + dropped:,} more problems. "
                              "Fix these and launch again.")
    assert report.problem_count == 1_250


def test_i4_more_than_the_item_limit_is_counted_too():
    class Many(UserFacingError):
        def parts(self):
            return "head", tuple((script_error(n), f"p{n}") for n in range(70)), ()

    report = decoded(encode_line(build_report(Many("m"), phase="start")))
    assert len(report.items) == REPORT_MAX_ITEMS
    assert report.tail == ("…and 10 more problems.",)


# --- EditorLink ---------------------------------------------------------------------------

def test_started_is_written_once():
    out = io.BytesIO()
    link = EditorLink(out)
    link.story_started()
    link.story_started()
    assert [decode_report(line) for line in lines_of(out)] == [STARTED]
    assert out.getvalue().endswith(b"\n")


def test_fatal_before_started_reports_start_and_asks_to_exit():
    out = io.BytesIO()
    link = EditorLink(out)
    assert link.fatal(UserFacingError("x")) is True
    assert decoded(lines_of(out)[0]).phase == "start"


def test_fatal_after_started_reports_run_and_keeps_the_screen():
    out = io.BytesIO()
    link = EditorLink(out)
    link.story_started()
    assert link.fatal(UserFacingError("x")) is False
    assert decoded(lines_of(out)[1]).phase == "run"


class _BrokenPipe(io.RawIOBase):
    def writable(self):
        return True

    def write(self, data):
        raise BrokenPipeError(32, "Broken pipe")


@pytest.mark.parametrize("out", [None, _BrokenPipe()], ids=["no-stdout", "closed-pipe"])
def test_writing_never_raises(out):
    link = EditorLink(out)
    link.story_started()
    assert link.fatal(RuntimeError("x")) is False


def test_a_closed_pipe_sends_the_rest_of_stdout_to_the_null_device():
    """AC-F44-08: the editor closed the pipe. The buffered bytes must not fail the flush
    at exit (Python would print "Exception ignored" and exit with code 120)."""
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    out = open(write_fd, "wb", buffering=1 << 16)
    link = EditorLink(out)
    link.story_started()                                 # the write fails, quietly
    assert link.out is None
    out.write(b"x" * 100)
    out.close()                                          # flushes to the null device


def test_a_config_error_group_reports_one_item_per_error():
    errors = [ConfigError("bad width", file="config.toml", line=2, column=9),
              ConfigError("bad title", file="config.toml", line=5)]
    group = ConfigErrorGroup(errors)
    report = decoded(encode_line(build_report(group, phase="start")))
    assert [(i.file, i.line, i.column) for i in report.items] == [("config.toml", 2, 9),
                                                                  ("config.toml", 5, None)]
    assert "\n\n".join(report.paragraphs()) == group.format()


# --- In-process launches (TR-F44-06, I-7, I-8) ----------------------------------------------

@pytest.fixture
def session(scripted_app):
    scripted_app.quit_frame = 12
    return scripted_app


class _Stdout:
    """The process's stdout as bytes (what the editor's reader thread gets)."""

    def __init__(self, capture) -> None:
        self.capture = capture
        self.seen = b""

    def getvalue(self) -> bytes:
        self.seen += self.capture.readouterr().out
        return self.seen


@pytest.fixture
def stdout(capsysbinary) -> _Stdout:
    return _Stdout(capsysbinary)


@pytest.fixture
def error_screens(monkeypatch) -> list[ErrorScreen]:
    """Every ErrorScreen the App builds."""
    built: list[ErrorScreen] = []

    class Recorded(ErrorScreen):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            built.append(self)

    monkeypatch.setattr(app_module, "ErrorScreen", Recorded)
    return built


def make_game(root: Path, scripts: dict[str, str] | None = None, *,
              config: bytes = b'[game]\ntitle = "My Game"\n') -> Path:
    for ref, text in (R_SCRIPTS if scripts is None else scripts).items():
        path = root / "script" / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_bytes(config)
    return root


def launch(game: Path, *, start: StartOptions | None = None, editor_report: bool = True) -> int:
    return bootstrap.launch(game, release=False, bench_seconds=None, log_level_override=None,
                            pygame_warning=None, start=start, editor_report=editor_report)


def test_tr06_a_load_error_reports_start_and_exits_1(tmp_path, user_roots, session, stdout,
                                                     error_screens):
    game = make_game(tmp_path / "my_game", {"main.vns": "label start:\n    jmup x\n"})
    assert launch(game) == 1
    (line,) = lines_of(stdout)
    report = decoded(line)
    assert report.phase == "start"
    assert report.head == "The script has 1 problem:"
    (item,) = report.items
    assert (item.file, item.line) == ("script/main.vns", 2)
    assert item.text.startswith('script/main.vns, line 2: "jmup" is not a statement.')
    assert error_screens == []                           # never pushed (TR-F44-06)
    assert session.apps[0].exit_code == 1


def test_i8_a_clean_story_reports_started_after_the_initial_screens(tmp_path, user_roots,
                                                                    session, stdout,
                                                                    monkeypatch):
    game = make_game(tmp_path / "my_game")
    order: list[str] = []
    real = bootstrap.build_initial_screens

    def initial_screens(app):
        order.append(f"screens, {len(stdout.getvalue())} bytes out")
        return real(app)

    monkeypatch.setattr(bootstrap, "build_initial_screens", initial_screens)
    assert launch(game) == 0
    assert order == ["screens, 0 bytes out"]
    assert [decode_report(line) for line in lines_of(stdout)] == [STARTED]


def test_pr13_a_run_phase_error_reports_and_still_shows_the_screen(tmp_path, user_roots,
                                                                   session, stdout,
                                                                   error_screens):
    game = make_game(tmp_path / "my_game")
    session.at(8, lambda app: app.show_fatal_error(RuntimeError("late")))
    assert launch(game) == 1                    # the scripted quit closes the error screen
    started, error = lines_of(stdout)
    assert decode_report(started) == STARTED
    assert decoded(error).phase == "run"
    assert len(error_screens) == 1


def test_i7_a_startup_error_ends_before_the_first_frame(tmp_path, user_roots, session,
                                                        stdout, error_screens):
    game = make_game(tmp_path / "my_game", config=b"[window]\nwidth = 'wide'\n")
    assert launch(game) == 1
    (line,) = lines_of(stdout)
    report = decoded(line)
    assert report.phase == "start" and "config.toml" in report.items[0].text
    assert error_screens == []
    assert session.limiters[-1].frame == 0               # run() returned at once


def test_without_the_option_nothing_is_written(tmp_path, user_roots, session, stdout,
                                               error_screens):
    game = make_game(tmp_path / "my_game", {"main.vns": "label start:\n    jmup x\n"})
    assert launch(game, editor_report=False) == 1
    assert stdout.getvalue() == b""
    assert len(error_screens) == 1
    assert session.apps[0].editor_link is None


def test_start_reaches_the_app_and_the_load_checks_e26b(tmp_path, user_roots, session,
                                                        stdout):
    """``--start`` alone already reaches ``LoadOptions.start``: an unknown label is a load
    error with E26b's suggestion (AC-F44-05's first row, in process)."""
    game = make_game(tmp_path / "my_game")
    start = StartOptions(label="club_poen")
    assert launch(game, start=start) == 1
    assert session.apps[0].start is start
    (item,) = decoded(lines_of(stdout)[0]).items
    assert item.text == format_message("E26b", ("club_poen", "club_poem"))
    assert item.file is None and item.line is None


def test_a_good_start_label_loads(tmp_path, user_roots, session, stdout):
    game = make_game(tmp_path / "my_game")
    start = StartOptions(label="club_poem", values=(("sayo_points", 1),))
    assert launch(game, start=start) == 0
    assert session.apps[0].start is start
    reports = [decode_report(line) for line in lines_of(stdout)]
    # A dev run also reports the line it is on (line reports): the start label's scene.
    places = [r[1].data for r in reports if isinstance(r, tuple) and r[0] == GAME]
    assert [r for r in reports if not isinstance(r, tuple)] == [STARTED]
    assert places and places[0]["scene"] == "club_poem"


def test_ac13_edit_and_run_give_the_same_text_for_an_empty_folder(tmp_path, user_roots,
                                                                   session, capfd):
    """AC-F44-13's last row: ``edit``'s one line is the one ``run`` writes for the folder."""
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    assert launch(empty, editor_report=False) == 0
    err = capfd.readouterr().err
    problem = game_folder_problem(empty)
    assert problem == format_message("W01")
    assert problem in err
