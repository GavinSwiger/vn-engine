"""The preview half of the editor window on game R (F44 ``04`` §7.6 "Preview (F5)",
"Problems panel", "Jump"; ``03`` §2.2, §3, §4; ``07`` I-3, I-5): F5 and Shift+F5, the status
line, the problems panel, and the jump. Tk rows of AC-F44-16 (F5 after a failed save),
AC-F44-21, AC-F44-26-31 that need no real game child (step 6 runs those with the real one),
and AC-F44-30.

The runner's ``popen`` records the real argv and launches a fake child from
``tests/fixtures/F44/children/`` instead of the game. Every child is killed and every root
destroyed in the fixture's teardown. Skipped when Tk or a display is missing.
"""

import errno
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.core.startvalues import parse_set
from engine.tools.editor import document
from engine.tools.editor.preview import (
    PreviewEvent,
    PreviewState,
    Report,
    ReportItem,
)
from tests.tools.editor.test_preview import Runners, StubbornPopen, child

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_window import (  # noqa: E402  (after the Tk skip)
    Editor,
    NoChecks,
    new_root,
    r_bytes,
    read_only,
    take_focus,
)

pytestmark = pytest.mark.tk

S = PreviewState
STARTING, RUNNING, CLOSED = "Starting…", "Running. F5 restarts it.", "Closed."
UNEXPECTED = "Stopped unexpectedly."
STOPPED_ERROR = "Stopped with an error, listed in Problems."


class Launcher:
    """The runner's ``popen``: records the argv it was given and the files' bytes at that
    moment, then starts the next fake child instead (the last one repeats)."""

    def __init__(self, names: tuple[str, ...], popen=subprocess.Popen,
                 watch: tuple[Path, ...] = ()) -> None:
        self.names = list(names)
        self.popen = popen
        self.watch = watch
        self.argvs: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.bytes_at_call: list[dict[Path, bytes]] = []

    def __call__(self, argv, **kwargs):
        self.argvs.append(list(argv))
        self.kwargs.append(kwargs)
        self.bytes_at_call.append({path: path.read_bytes() for path in self.watch})
        name = self.names.pop(0) if len(self.names) > 1 else self.names[0]
        return self.popen(child(*name.split()), **kwargs)


@pytest.fixture
def make_editor(monkeypatch):
    """``make_editor(game, children=("started_exit0",), mapped=False, ...) -> Editor`` with
    ``.launcher`` and ``.statuses`` (every status text shown, in order)."""
    roots: list = []
    runners = Runners()
    callback_errors: list = []
    errors_shown: list[str] = []
    monkeypatch.setattr(window.messagebox, "showerror",
                        lambda title, message, **kwargs: errors_shown.append(message))

    def build(game: Path, *, children: tuple[str, ...] = ("started_exit0",),
              mapped: bool = False, stubborn: bool = False, kill_after_s: float = 2.0,
              watch: tuple[Path, ...] = ()) -> Editor:
        root = new_root()
        roots.append(root)
        root.report_callback_exception = lambda *info: callback_errors.append(info)
        root.withdraw()
        launcher = Launcher(children, StubbornPopen if stubborn else subprocess.Popen, watch)
        runner = runners.make(popen=launcher, kill_after_s=kill_after_s)
        ed = Editor(window.EditorWindow(root, GamePaths.for_game(game), runner=runner,
                                        check_runner=NoChecks()), errors_shown)
        ed.launcher = launcher
        ed.runners = runners
        ed.statuses = []
        show_event = ed.win.show_event

        def recording(event):
            show_event(event)
            ed.statuses.append(ed.status_label.cget("text"))

        ed.win.show_event = recording
        if mapped:
            root.geometry("+-3000+-3000")
            root.deiconify()
            root.update()
        else:
            root.update_idletasks()
        return ed

    try:
        yield build
    finally:
        runners.close()
        for root in roots:
            try:
                root.destroy()
            except tk.TclError:
                pass
    assert not callback_errors, callback_errors


def pump(ed: Editor, until, timeout: float = 10.0) -> None:
    """Run the Tk loop until ``until()`` is true."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ed.root.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out; statuses: {ed.statuses}")


def status(ed: Editor) -> str:
    return ed.status_label.cget("text")


def panel_text(ed: Editor) -> str:
    return ed.problems.get("1.0", "end-1c")


def set_box(ed: Editor, text: str) -> None:
    ed.start_values.delete("1.0", "end")
    ed.start_values.insert("1.0", text)


def paragraph_point(ed: Editor, index: int) -> tuple[int, int]:
    """Window coordinates inside paragraph ``index``'s first character."""
    panel = ed.problems
    panel.update_idletasks()
    first = panel.tag_ranges(ed.paragraphs[index].tag)[0]
    panel.see(first)
    panel.update_idletasks()
    x, y, width, height = panel.bbox(first)
    return x + width // 2, y + height // 2


def click_paragraph(ed: Editor, index: int) -> None:
    x, y = paragraph_point(ed, index)
    panel = ed.problems
    take_focus(panel)                           # a real click gives the window the keyboard
    panel.event_generate("<Motion>", x=x, y=y)
    panel.event_generate("<Button-1>", x=x, y=y)
    panel.event_generate("<ButtonRelease-1>", x=x, y=y)
    ed.root.update()


LOAD_ERRORS = Report("start", "The script has 3 problems:", (
    ReportItem("script/chapter2.vns, line 11, column 16: this text has no closing quote.\n"
               "    sayori \"It's {b}nice{/b}.", "script/chapter2.vns", 11, 16),
    ReportItem("script/main.vns, line 7: there is no label called `club_poen`.",
               "script/main.vns", 7, None),
    ReportItem("config.toml has a problem: `volume` must be a number.", "config.toml",
               None, None),
), ("…and 2 more problems. Fix these and launch again.",))


# --- Status texts (03 §2.2, UI-F44-06) -------------------------------------------------------

def test_the_status_text_of_every_state():
    one = Report("start", None, (ReportItem("x"),))
    assert window.status_text(PreviewEvent(S.NOT_RUNNING)) == "Not running."
    assert window.status_text(PreviewEvent(S.STARTING)) == STARTING
    assert window.status_text(PreviewEvent(S.RUNNING)) == RUNNING
    assert window.status_text(PreviewEvent(S.DIDNT_START, one)) == \
        "Didn't start: 1 problem, listed in Problems."
    assert window.status_text(PreviewEvent(S.DIDNT_START, LOAD_ERRORS)) == \
        "Didn't start: 5 problems, listed in Problems."
    assert window.status_text(PreviewEvent(S.CLOSED)) == CLOSED
    assert window.status_text(PreviewEvent(S.STOPPED_ERROR, one)) == STOPPED_ERROR
    assert window.status_text(PreviewEvent(S.STOPPED_UNEXPECTED)) == UNEXPECTED


# --- AC-F44-26: F5 saves, then previews from the cursor --------------------------------------

def test_f5_saves_then_starts_at_the_cursors_label(make_editor, route_game):
    main, chapter2 = route_game / "script/main.vns", route_game / "script/chapter2.vns"
    ed = make_editor(route_game, mapped=True, watch=(main, chapter2))
    ed.text.insert("1.0", "# edited\n")                         # main.vns
    ed.open_file("script/chapter2.vns")
    ed.text.insert("1.0", "# edited\n")                         # club_poem is now line 7
    ed.text.mark_set("insert", "10.0")
    box = "sayo_points = 1\n# comment\n\nseen = ['x']"
    set_box(ed, box)
    ed.idle()
    ed.press(ed.text, "<F5>")
    assert ed.launcher.bytes_at_call == [{
        main: b"# edited\n" + r_bytes("main.vns"),
        chapter2: b"# edited\n" + r_bytes("chapter2.vns")}]
    (argv,) = ed.launcher.argvs
    assert argv[:8] == [sys.executable, "-m", "engine", "run", str(ed.paths.root),
                        "--report-to-editor", "--start", "club_poem"]
    assert argv[8] == argv[10] == "--set" and len(argv) == 12
    assert parse_set(argv[9]) == ("sayo_points", 1)
    assert parse_set(argv[11]) == ("seen", ["x"])
    assert ed.statuses[0] == STARTING
    pump(ed, lambda: status(ed) == CLOSED)
    assert ed.statuses == [STARTING, RUNNING, CLOSED]
    assert panel_text(ed) == "No problems."
    assert ed.rows()[:2] == ["main.vns", "chapter2.vns"]
    assert ed.start_values.get("1.0", "end-1c") == box
    assert ed.focus() is ed.text                                 # focus stays (03 §4)


def test_shift_f5_and_a_cursor_above_every_label_pass_no_start(make_editor, route_game):
    ed = make_editor(route_game, mapped=True, children=("exit3",))
    ed.open_file("script/chapter2.vns")
    ed.text.mark_set("insert", "9.0")
    set_box(ed, "sayo_points = 1")
    ed.idle()
    ed.press(ed.text, "<Shift-F5>")                             # AC-F44-31 (a)
    assert "--start" not in ed.launcher.argvs[0]
    assert ed.launcher.argvs[0][-2:] == ["--set", "sayo_points = 1"]
    pump(ed, lambda: status(ed) == UNEXPECTED)
    ed.text.mark_set("insert", "2.0")                           # above club_poem
    ed.idle()
    ed.press(ed.text, "<F5>")
    assert "--start" not in ed.launcher.argvs[1]


def test_the_preview_button_enter_and_space_do_what_f5_does(make_editor, route_game):
    ed = make_editor(route_game, mapped=True, children=("exit3",))
    ed.press(ed.preview_button, "<Return>")
    pump(ed, lambda: status(ed) == UNEXPECTED)
    ed.press(ed.preview_button, "<space>")
    pump(ed, lambda: len(ed.launcher.argvs) == 2 and status(ed) == UNEXPECTED)
    assert ed.launcher.argvs[0] == ed.launcher.argvs[1]
    assert "--start" not in ed.launcher.argvs[0]                # main.vns line 1


# --- AC-F44-16 (F5 rows): a failed save starts nothing ---------------------------------------

def _fail(code: int):
    def raiser(*_args, **_kwargs):
        raise OSError(code, os.strerror(code))
    return raiser


SAVE_FAILURES = [
    ("read-only", "the file is read-only."),
    ("_write_all", "the disk is full."),
    ("replace", "the file is read-only or locked."),
    ("fsync", "the system reported an error."),
]


def test_a_failed_save_on_f5_keeps_everything_and_starts_nothing(
        make_editor, route_game, monkeypatch):
    """Each failure row of AC-F44-16 through F5, in one editor (a failed save leaves it
    dirty, so the next row starts from the same state)."""
    path = route_game / "script/chapter2.vns"
    ed = make_editor(route_game, mapped=True)
    ed.open_file("script/chapter2.vns")
    ed.text.insert("1.0", "x")
    ed.idle()
    for failure, reason in SAVE_FAILURES:
        ed.errors_shown.clear()
        if failure == "read-only":
            with read_only(path):
                ed.press(ed.text, "<F5>")
        else:
            with monkeypatch.context() as patch:
                target = document if failure == "_write_all" else document.os
                patch.setattr(target, failure, _fail({"_write_all": errno.ENOSPC,
                                                      "replace": errno.EACCES,
                                                      "fsync": errno.EIO}[failure]))
                ed.press(ed.text, "<F5>")
        assert ed.errors_shown == [f"Couldn't save `script/chapter2.vns`: {reason}"]
        assert str(route_game) not in ed.errors_shown[0]
        assert ed.launcher.argvs == [], failure
        assert path.read_bytes() == r_bytes("chapter2.vns"), failure
        assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []
        assert ed.body().startswith("xdefault")
        assert ed.rows()[1] == "* chapter2.vns"
        assert status(ed) == "Not running." and ed.statuses == []


# --- AC-F44-27: start-value problems show before launch (I-5) --------------------------------

def test_start_value_problems_show_in_the_panel_and_nothing_starts(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    set_box(ed, "sayo_points = Hana\n# ok\nseen = 1+1\nsayo_points = 2")
    ed.press(ed.text, "<F5>")
    assert ed.launcher.argvs == []
    assert status(ed) == "Didn't start: 3 problems, listed in Problems."
    assert ed.panel_paragraphs() == [
        "The start values have 3 problems:",
        "Start values, line 1: put text in quotes.",
        "Start values, line 3: the value must be a number, True, False, None, quoted text, "
        "a list, or a dictionary.",
        "Start values, line 4: `sayo_points` is set twice.",
    ]
    assert not any(p.clickable for p in ed.paragraphs)
    assert ed.problems.tag_ranges(window.TAG_LINK) == ()
    assert ed.focus() is ed.text
    set_box(ed, "\n".join(f"v{i} = {i}" for i in range(101)))
    ed.press(ed.text, "<F5>")
    assert ed.launcher.argvs == []
    assert status(ed) == "Didn't start: 1 problem, listed in Problems."
    assert len(ed.paragraphs) == 2 and "100" in ed.panel_paragraphs()[1]
    assert UNEXPECTED not in ed.statuses


# --- AC-F44-28: the problems panel -----------------------------------------------------------

def test_a_load_error_report_fills_the_panel_with_links(make_editor, route_game):
    ed = make_editor(route_game, mapped=True, children=("starterror_exit1", "started_exit0"))
    assert panel_text(ed) == window.PROBLEMS_HINT
    ed.press(ed.text, "<F5>")
    pump(ed, lambda: status(ed).startswith("Didn't start"))
    assert status(ed) == "Didn't start: 2 problems, listed in Problems."
    paragraphs = ed.panel_paragraphs()
    assert paragraphs[0] == "The script has 2 problems:"
    assert paragraphs[1].startswith("script/chapter2.vns, line 11, column 16: this text")
    assert paragraphs[1].endswith("\n    sayori \"It's {b}nice{/b}.")
    assert paragraphs[2].startswith("script/main.vns, line 7: there is no label")
    assert [p.clickable for p in ed.paragraphs] == [False, True, True]
    panel = ed.problems
    links = panel.tag_ranges(window.TAG_LINK)
    assert [panel.get(a, b) for a, b in zip(links[0::2], links[1::2])] == [
        "script/chapter2.vns, line 11, column 16", "script/main.vns, line 7"]
    assert panel.tag_cget(window.TAG_LINK, "foreground") == "#4DAAFC"
    assert str(panel.tag_cget(window.TAG_LINK, "underline")) in ("1", "true")
    x, y = paragraph_point(ed, 2)
    panel.event_generate("<Motion>", x=x, y=y)
    ed.root.update()
    assert str(panel.cget("cursor")) == "hand2"
    x, y = paragraph_point(ed, 0)
    panel.event_generate("<Motion>", x=x, y=y)
    ed.root.update()
    assert str(panel.cget("cursor")) == "arrow"
    assert ed.focus() is ed.text                                 # focus stays (03 §4)
    ed.press(ed.text, "<F5>")                                    # a successful preview
    pump(ed, lambda: status(ed) == CLOSED)
    assert panel_text(ed) == "No problems."
    assert panel.tag_ranges(window.TAG_LINK) == ()


def test_errors_you_cant_click(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    report = Report("start", "The script has 2 problems:", (
        ReportItem("config.toml has a problem.", "config.toml", None, None),
        ReportItem("script/elsewhere.vns, line 3: not in the list.", "script/elsewhere.vns",
                   3, 1),
        ReportItem("script/main.vns: a whole-file problem.", "script/main.vns", None, None),
    ), ("…and 1 more problems.",))
    ed.show_event(PreviewEvent(S.DIDNT_START, report))
    assert status(ed) == "Didn't start: 4 problems, listed in Problems."
    assert ed.panel_paragraphs() == report.paragraphs()
    assert not any(p.clickable for p in ed.paragraphs)
    assert ed.problems.tag_ranges(window.TAG_LINK) == ()
    insert = ed.text.index("insert")
    for index in range(len(ed.paragraphs)):
        click_paragraph(ed, index)
        assert str(ed.problems.cget("cursor")) == "arrow"
    assert ed.current.ref == "script/main.vns" and ed.text.index("insert") == insert
    assert ed.text.tag_ranges(window.TAG_JUMP) == ()


def test_paragraphs_are_6_px_apart(make_editor, route_game):
    ed = make_editor(route_game)
    ed.show_report(LOAD_ERRORS)
    panel = ed.problems
    assert int(panel.tag_cget(window.TAG_GAP, "spacing1")) == 6
    starts = [panel.tag_ranges(p.tag)[0] for p in ed.paragraphs]
    assert window.TAG_GAP not in panel.tag_names(starts[0])
    assert all(window.TAG_GAP in panel.tag_names(start) for start in starts[1:])


def test_f6_selects_the_first_clickable_error_and_up_down_move_it(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.show_report(LOAD_ERRORS)
    ed.press(ed.text, "<F6>")
    ed.press(ed.start_values, "<F6>")
    assert ed.focus() is ed.problems
    panel = ed.problems

    def chosen() -> str:
        first, last = panel.tag_ranges(window.TAG_CHOSEN)
        return panel.get(first, last)

    assert chosen().startswith("script/chapter2.vns, line 11")
    assert panel.tag_cget(window.TAG_CHOSEN, "background") == "#04395E"
    ed.press(panel, "<Down>")
    assert chosen().startswith("script/main.vns, line 7")
    ed.press(panel, "<Up>")
    ed.press(panel, "<Up>")
    assert chosen() == "The script has 3 problems:\n"
    ed.press(panel, "<Return>")                                  # not clickable
    assert ed.focus() is panel and ed.current.ref == "script/main.vns"
    ed.press(panel, "<Down>")
    ed.press(panel, "<Down>")
    ed.press(panel, "<Return>")                                  # main.vns, line 7, no column
    assert ed.focus() is ed.text
    assert ed.current.ref == "script/main.vns" and ed.text.index("insert") == "7.0"
    assert panel.tag_ranges(window.TAG_CHOSEN) == ()             # only while focused


def test_ctrl_c_copies_selected_panel_text(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.show_report(LOAD_ERRORS)
    panel = ed.problems
    panel.tag_add("sel", "1.4", "1.10")
    ed.press(panel, "<Control-c>")
    assert ed.root.clipboard_get() == "script"


# --- AC-F44-29 (fake-child rows): clicking an error jumps to its line ------------------------

def test_a_click_jumps_to_the_line_and_column(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.show_report(LOAD_ERRORS)
    click_paragraph(ed, 1)
    assert ed.current.ref == "script/chapter2.vns"
    assert ed.selected() == "script/chapter2.vns"
    assert ed.text.index("insert") == "11.15"
    assert [str(i) for i in ed.text.tag_ranges(window.TAG_JUMP)] == ["11.0", "12.0"]
    assert ed.text.tag_cget(window.TAG_JUMP, "background") == "#322E16"
    assert ed.focus() is ed.text
    ed.idle()
    ed.text.mark_set("insert", "12.0")
    ed.idle()
    assert ed.text.tag_ranges(window.TAG_JUMP) == ()


def test_a_jump_puts_the_line_in_the_middle_third(make_editor, route_game):
    lines = [f'    "Line {n}."' for n in range(1, 401)]
    lines[0] = "label club_poem:"
    lines[249] = '    "no closing quote'
    (route_game / "script/chapter2.vns").write_text("\n".join(lines) + "\n", "utf-8")
    ed = make_editor(route_game, mapped=True)
    ed.jump_to("script/chapter2.vns", 250, 5)
    ed.root.update()
    widget = ed.text
    height = widget.winfo_height()
    linespace = ed.font.metrics("linespace")
    y = widget.dlineinfo("250.0")[1]
    assert height / 3 - linespace <= y <= 2 * height / 3, (y, height)
    assert widget.index("insert") == "250.4"


def test_a_jump_counts_characters_outside_the_bmp(make_editor, route_game):
    """I-3: F02's column counts characters; Tk 8.6 counts an emoji as two columns."""
    (route_game / "script/routes/hana.vns").write_text(
        'label hana_route:\n    "😀😀 Hana\'s route."\n', "utf-8")
    ed = make_editor(route_game, mapped=True)
    ed.jump_to("script/routes/hana.vns", 2, 9)                   # the "H"
    assert ed.text.get("2.0", "insert").encode("utf-16", "surrogatepass").decode(
        "utf-16") == '    "😀😀 '
    assert ed.text.get("insert", "insert +1c") == "H"


def test_a_jump_past_the_end_lands_on_the_last_line(make_editor, route_game):
    ed = make_editor(route_game)
    ed.jump_to("script/routes/hana.vns", 99, 50)
    assert ed.text.index("insert") == "2.19"


# --- AC-F44-30: a preview never freezes the editor or touches its text ------------------------

def run_with_heartbeat(ed: Editor, seconds: float, until=None) -> float:
    """Run the Tk loop with an ``after(50)`` heartbeat for ``seconds``, or until ``until()``
    is true once the typing (at 150 ms) is done; returns the largest gap between beats."""
    beats: list[float] = []
    began = time.monotonic()

    def beat():
        beats.append(time.monotonic())
        ed.root.after(50, beat)

    ed.root.after(50, beat)
    while time.monotonic() - began < seconds:
        ed.root.update()
        if until is not None and until() and time.monotonic() - began > 0.25:
            break
        time.sleep(0.005)
    ed.root.update()
    beats.append(time.monotonic())
    return max(b - a for a, b in zip(beats, beats[1:]))


def check_untouched_while_running(ed: Editor, seconds: float, until=None) -> None:
    before = ed.body()
    ed.press(ed.text, "<F5>")
    ed.root.after(150, lambda: ed.text.insert("1.0", "typed "))
    assert run_with_heartbeat(ed, seconds, until) <= 0.2
    assert ed.body() == "typed " + before


def test_a_crashing_preview_leaves_the_editor_responsive(make_editor, route_game):
    ed = make_editor(route_game, mapped=True, children=("started_exit3",))
    check_untouched_while_running(ed, 5.0, until=lambda: status(ed) == UNEXPECTED)
    assert ed.statuses == [STARTING, RUNNING, UNEXPECTED]


@pytest.mark.slow
@pytest.mark.parametrize("name, final", [
    ("hang", RUNNING), ("flood50mb", RUNNING), ("started_exit0", CLOSED),
    ("started_exit3", UNEXPECTED)])
def test_the_editor_stays_responsive_for_5_s(make_editor, route_game, name, final):
    ed = make_editor(route_game, mapped=True, children=(name,))
    ed.runners.runners[-1]._forward = lambda line: None          # the flood isn't printed
    check_untouched_while_running(ed, 5.0)
    assert status(ed) == final


def test_f5_during_a_hang_keeps_one_child_alive(make_editor, route_game):
    ed = make_editor(route_game, mapped=True, children=("hang", "started_exit0"),
                     stubborn=True, kill_after_s=0.2)
    ed.press(ed.text, "<F5>")
    pump(ed, lambda: status(ed) == RUNNING)
    old = ed.runners.procs[0]
    ed.press(ed.text, "<F5>")
    began = time.monotonic()
    while status(ed) != CLOSED:
        assert ed.runners.alive() <= 1
        assert time.monotonic() - began < 2.5, ed.statuses
        ed.root.update()
        time.sleep(0.05)
    assert old.poll() is not None
    assert ed.statuses == [STARTING, RUNNING, STARTING, RUNNING, CLOSED]


# --- AC-F44-31 (fake-child rows): closing, run-time errors -----------------------------------

def test_closing_the_editor_ends_the_preview(make_editor, route_game):
    ed = make_editor(route_game, mapped=True, children=("hang",))
    ed.press(ed.text, "<F5>")
    pump(ed, lambda: status(ed) == RUNNING)
    proc = ed.runners.procs[0]
    began = time.monotonic()
    ed.win.on_close()
    assert proc.poll() is not None and time.monotonic() - began < 2.5
    assert ed.closed


def test_a_run_time_error_is_listed_and_clickable(make_editor, route_game):
    ed = make_editor(route_game, mapped=True, children=("started_runerror_exit1",))
    ed.press(ed.text, "<F5>")
    pump(ed, lambda: status(ed) == STOPPED_ERROR)
    pump(ed, lambda: ed.runners.procs[0].poll() is not None)
    time.sleep(0.15)
    ed.root.update()
    assert ed.statuses == [STARTING, RUNNING, STOPPED_ERROR]       # stays after the exit
    assert [p.clickable for p in ed.paragraphs] == [True]
    click_paragraph(ed, 0)
    assert ed.current.ref == "script/chapter2.vns" and ed.text.index("insert") == "7.4"


# --- AC-F44-21: readable and keyboard-reachable ----------------------------------------------

def _luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_window_text_colors_are_readable_on_every_background():
    """AC-F44-21 as amended 2026-11-02 (VS Code Dark+): every text color on each background
    it is drawn on is at least 4.5:1, focus rings and link lines at least 3:1
    (``theme.CONTRAST_PAIRS``); the window's colors are the theme's."""
    from engine.tools.editor import theme

    t = theme.THEME
    backgrounds = [window.BACKGROUND, window.LINE_BACKGROUND, window.JUMP_BACKGROUND,
                   window.SELECTION_BACKGROUND, window.GUTTER_BACKGROUND]
    assert backgrounds == ["#1E1E1E", "#2A2D2E", "#322E16", "#264F78", "#1E1E1E"]
    assert window.LINK_FOREGROUND == "#4DAAFC" and window.MESSAGE_FOREGROUND == "#9D9D9D"
    assert (window.GUTTER_FOREGROUND, window.GUTTER_CURRENT) == ("#858585", "#C6C6C6")
    assert window.CHOSEN_BACKGROUND == "#04395E" and window.PLAIN_COLOR == "#D4D4D4"
    for color in (window.PLAIN_COLOR, window.LINK_FOREGROUND, window.MESSAGE_FOREGROUND):
        assert _contrast(color, window.BACKGROUND) >= 4.5, color
    assert _contrast(window.PLAIN_COLOR, window.SELECTION_BACKGROUND) >= 4.5
    for fg, bg, need in theme.CONTRAST_PAIRS:
        assert _contrast(t[fg], t[bg]) >= need, (fg, t[fg], bg, t[bg])
        assert need in (4.5, 3.0)
    assert ("statusBar.foreground", "statusBar.background", 4.5) in theme.CONTRAST_PAIRS


def test_studio_marker_and_map_colors_are_readable():
    """AC-F44-21 as amended by F45 and 2026-11-02: the gutter markers on the gutter (4.5:1),
    the story map's label text on its boxes (4.5:1), and its link lines and focus ring on the
    canvas (3:1)."""
    views = pytest.importorskip("engine.tools.editor.views")
    markers = [window.MARKER_COLORS["error"], window.MARKER_COLORS["warning"]]
    assert markers == ["#F14C4C", "#CCA700"]
    assert min(_contrast(c, window.GUTTER_BACKGROUND) for c in markers) >= 4.5
    assert (views.BOX_FILL, views.BOX_OUTLINE, views.RING_COLOR) == (
        "#252526", "#3C3C3C", "#007FD4")
    assert {color for _dash, color in views.EDGE_STYLES.values()} == {"#808080"}
    assert min(_contrast(c, views.BOX_FILL) for c in (views.PLAIN_COLOR, views.MUTED)) >= 4.5
    assert min(_contrast(c, window.BACKGROUND)
               for c in (views.RING_COLOR, views.LINK_COLOR, views.PLAIN_COLOR)) >= 3.0


def test_every_key_action_is_bound_and_the_font_is_14_px(make_editor, route_game):
    ed = make_editor(route_game)
    mod = ed.mod
    for sequence in ("<F5>", "<Shift-F5>", f"<{mod}-s>", "<F6>", "<Shift-F6>",
                     f"<{mod}-equal>", f"<{mod}-minus>", f"<{mod}-0>"):
        assert ed.root.bind_all(sequence), sequence
    assert window.FONT_PX == 14 and ed.font.cget("size") == -14
