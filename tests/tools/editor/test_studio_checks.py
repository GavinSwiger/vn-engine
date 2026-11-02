"""Checks in the Studio window (F45 step 4; ``06`` AC-F45-27's Tk row, AC-F45-30..36, as
adjusted by ``07`` I-1), and the status bar that shows them (AC-F45-50, amended 2026-11-02).

Every test but AC-F45-36 builds Studio W (game S with the fake check runner of
``test_studio_window.py``, which records ``request(overlay, serial, launch)``) and hands the
window runner events through ``apply_check_events``, as the 100 ms poll does. AC-F45-36 is the
one real check child: ``CheckRunner`` on a copy of S."""

import json
import time
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script.labelgraph import LabelLink
from engine.tools.editor.checker import (
    CheckEvent,
    CheckItem,
    CheckResult,
    CheckRunner,
    CheckState,
    NameEntry,
)
from engine.tools.editor.document import encode
from engine.tools.editor.preview import PreviewEvent, PreviewState, Report, ReportItem
from engine.tools.editor.views import MAP_OUT_OF_DATE

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools import f45_games  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401
from tests.tools.editor.test_window import Editor, new_root  # noqa: E402
from tests.tools.editor.test_window_preview import click_paragraph  # noqa: E402

pytestmark = pytest.mark.tk

E43 = CheckItem("error", "E43", "load", 'there is no label named "bridg". Did you mean "bridge"?',
                "script/ch2.vns", 9, None)
CONFIG_NO_LINE = CheckItem("error", "", "config", "config.toml has a problem.", "config.toml",
                           None, None)
LINT = CheckItem("warning", "L101", "lint", "a lint rule.", "script/main.vns", 3, None)


def result(*items: CheckItem, serial: int = 0, loaded: bool = True, seconds: float = 1.0,
           names: dict | None = None, links: tuple | None = ()) -> CheckResult:
    return CheckResult(problems=tuple(items), problem_total=len(items), names=names or {},
                       links=links if loaded else None, loaded=loaded, serial=serial,
                       seconds=seconds)


def done(ed: Editor, *items: CheckItem, **kwargs) -> CheckResult:
    """Hand the window a ``DONE`` for the newest request (serial: the current
    ``edit_serial`` unless given)."""
    kwargs.setdefault("serial", ed.win.edit_serial)
    res = result(*items, **kwargs)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, res.serial, res)])
    ed.root.update_idletasks()
    return res


def status(ed: Editor) -> str:
    """The status bar's check message (F45 01 §6.5, amended 2026-11-02)."""
    return ed.check_status.cget("text")


def counts(ed: Editor) -> str:
    """The status bar's error and warning counts."""
    return ed.check_counts.cget("text")


def markers(ed: Editor) -> dict[int, tuple[str, str]]:
    """Line -> (letter, color) of every marker drawn in the gutter."""
    found = {}
    for item in ed.gutter.find_withtag(window.TAG_MARKER):
        y = ed.gutter.coords(item)[1]
        line = int(ed.text.index(f"@0,{int(y) + 2}").split(".")[0])
        found[line] = (ed.gutter.itemcget(item, "text"), ed.gutter.itemcget(item, "fill"))
    return found


def overlay_files(overlay: bytes) -> dict[str, bytes]:
    header, _, body = overlay.partition(b"\n")
    files, offset = {}, 0
    for entry in json.loads(header)["files"]:
        files[entry["ref"]] = body[offset:offset + entry["size"]]
        offset += entry["size"]
    return files


# --- AC-F45-30: row and summary text ---------------------------------------------------------

def test_ac30_row_and_summary_text():
    t = "the text."
    rows = [
        (CheckItem("error", "E43", "load", t, "script/ch2.vns", 9, None),
         "Error E43 script/ch2.vns, line 9: "),
        (CheckItem("warning", "W12", "launch", t, "script/main.vns", 5, None), "Warning W12 "),
        (CheckItem("info", "TODO", "load", t, "script/main.vns", 1, None), "Info TODO "),
        (CheckItem("error", "", "config", t, "config.toml", 2, None),
         "Error config.toml, line 2: "),
        (CheckItem("error", "E26b", "load", t), "Error E26b: "),
        (CheckItem("error", "L101", "lint", t, "script/ch2.vns", 9, None),
         "Error L101 script/ch2.vns, line 9: "),
        (CheckItem("warning", "X1", "future", t, "script/ch2.vns", 9, 4),
         "Warning X1 script/ch2.vns, line 9, column 4: "),
    ]
    for item, start in rows:
        row = window.check_row(item)
        assert row.startswith(start), (item, row)
        assert row.endswith(" " + t)
    assert window.check_row(rows[3][0]) == "Error config.toml, line 2: the text."
    assert window.check_row(rows[4][0]) == "Error E26b: the text."
    err, warn, info = rows[0][0], rows[1][0], rows[2][0]
    assert window.check_summary(result()) == "Checked: no problems."
    assert window.check_summary(result(err)) == "Checked: 1 error."
    assert window.check_summary(result(err, err, warn)) == "Checked: 2 errors, 1 warning."
    assert window.check_summary(result(warn)) == "Checked: 1 warning."
    assert window.check_summary(result(info)) == "Checked: no problems."     # Gap G7


# --- AC-F45-31: the problems panel -----------------------------------------------------------

def test_ac31_the_problems_panel(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    done(ed, E43, CONFIG_NO_LINE, LINT)
    report = Report("start", "The script has 1 problem:", (
        ReportItem("script/main.vns, line 7: there is no label named `club`.",
                   "script/main.vns", 7, None),), ())
    ed.win.show_event(PreviewEvent(PreviewState.DIDNT_START, report))
    assert ed.panel_paragraphs() == [
        "Checked: 2 errors, 1 warning.",
        'Error E43 script/ch2.vns, line 9: there is no label named "bridg". Did you mean '
        '"bridge"?',
        "Error config.toml: config.toml has a problem.",
        "Warning L101 script/main.vns, line 3: a lint rule.",
        *report.paragraphs()]
    assert [p.clickable for p in ed.paragraphs] == [False, True, False, True, False, True]
    panel = ed.problems
    links = panel.tag_ranges(window.TAG_LINK)
    assert [panel.get(a, b) for a, b in zip(links[0::2], links[1::2])] == [
        "Error E43 script/ch2.vns, line 9", "Warning L101 script/main.vns, line 3",
        "script/main.vns, line 7"]
    click_paragraph(ed, 1)
    assert ed.current.ref == "script/ch2.vns" and ed.text.index("insert") == "9.0"
    click_paragraph(ed, 3)
    assert ed.current.ref == "script/main.vns" and ed.text.index("insert") == "3.0"
    click_paragraph(ed, 2)                                   # plain: nothing moves
    assert ed.current.ref == "script/main.vns" and ed.text.index("insert") == "3.0"
    many = [CheckItem("error", "E43", "load", f"problem {n}.", "script/main.vns", 1 + n % 8,
                      None) for n in range(1000)]
    done(ed, *many)
    assert len(ed.paragraphs) == 1 + 1000 + len(report.paragraphs())
    assert ed.panel_paragraphs()[1000] == "Error E43 script/main.vns, line 8: problem 999."


# --- AC-F45-27 (Tk): config.toml rows ---------------------------------------------------------

def test_ac27_a_config_row_with_a_line_is_a_link(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    at_line = CheckItem("error", "", "config", "`title` must be text.", "config.toml", 2, None)
    done(ed, at_line, CONFIG_NO_LINE)
    assert [p.clickable for p in ed.paragraphs] == [False, True, False]
    click_paragraph(ed, 1)
    assert ed.current.ref == "config.toml" and ed.text.index("insert") == "2.0"
    assert ed.body() == '[game]\ntitle = "My Game"'


# --- AC-F45-32: gutter markers ----------------------------------------------------------------

def test_ac32_gutter_markers(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    ed.open_file("script/ch2.vns")
    ch2 = "script/ch2.vns"
    items = [CheckItem("error", "E1", "load", "error on 3.", ch2, 3, None),
             CheckItem("warning", "W1", "launch", "warning on 5.", ch2, 5, None),
             CheckItem("info", "TODO", "load", "info on 7.", ch2, 7, None),
             CheckItem("warning", "W2", "launch", "warning on 9.", ch2, 9, None),
             CheckItem("error", "E2", "load", "error on 9.", ch2, 9, None),
             CheckItem("error", "E3", "load", "in main.", "script/main.vns", 4, None)]
    done(ed, *items)
    ed.root.update()
    red, amber = "#F14C4C", "#CCA700"
    assert markers(ed) == {3: ("E", red), 5: ("W", amber), 9: ("E", red)}
    assert ed.win.check_markers() == {3: "E", 5: "W", 9: "E"}
    ed.text.insert("3.0", "    \"one\"\n    \"two\"\n")             # 2 lines above line 3
    ed.root.update()
    assert markers(ed) == {5: ("E", red), 7: ("W", amber), 11: ("E", red)}
    ed.text.mark_set("insert", "5.4")
    ed.root.update()
    assert status(ed) == "error on 3."
    ed.text.mark_set("insert", "11.0")
    ed.root.update()
    assert status(ed) == "warning on 9."                    # the line's first item
    ed.text.mark_set("insert", "1.0")
    ed.root.update()
    assert status(ed) == "Out of date" and counts(ed) == "\u2297 3  \u26a0 2"   # 2 lines in
    done(ed)
    ed.root.update()
    assert markers(ed) == {} and ed.win.check_markers() == {}


# --- AC-F45-33: when checks run, and what the status says ------------------------------------

def test_ac33_when_checks_run_and_the_status(studio, studio_game, monkeypatch):
    monkeypatch.setattr(window, "CHECK_DEBOUNCE_MS", 60_000)
    ed = studio(studio_game)
    requests = ed.checks.requests
    assert requests == [(None, 0, False)] and status(ed) == "Checking…"   # load-only (I-1)
    assert counts(ed) == ""                                 # no result yet
    labels = (NameEntry("start", "script/main.vns", 4), NameEntry("club", "script/ch2.vns", 1))
    images = (NameEntry("hana happy"),)
    links = (LabelLink("start", "club", "call", "script/main.vns", 7),)
    done(ed, names={"label": labels, "image": images}, links=links)
    assert status(ed) == "" and counts(ed) == "\u2297 0  \u26a0 0"
    done(ed, E43, names={"label": labels, "image": images}, links=links)
    rows = ed.panel_paragraphs()

    ed.text.insert("end", "\n# x")
    ed.root.update_idletasks()
    ed.win.save_current()                                   # Ctrl+S on a dirty file
    assert requests[1:] == [(None, ed.win.edit_serial, True)]
    ed.win.check_now()                                      # F7
    assert requests[2:] == [(None, ed.win.edit_serial, True)]
    done(ed, E43, names={"label": labels, "image": images}, links=links)
    assert status(ed) == "" and counts(ed) == "\u2297 1  \u26a0 0"

    ed.text.insert("1.0", "x")                              # typing x
    ed.root.update_idletasks()
    assert status(ed) == "Out of date" and ed.panel_paragraphs() == rows
    started = time.perf_counter()
    ed.win.request_check()                                  # a request while running
    assert time.perf_counter() - started < 0.010
    assert requests[-1][1:] == (ed.win.edit_serial, True)   # armed: launch stays on
    assert status(ed) == "Checking…" and ed.panel_paragraphs() == rows
    assert counts(ed) == "\u2297 1  \u26a0 0"                # the newest result's, kept
    ed.text.insert("1.0", "y")                              # typing while Checking…
    assert ed.text.get("1.0", "1.2") == "yx"

    serial = ed.win.edit_serial
    ed.win.apply_check_events([CheckEvent(CheckState.STARTED, serial),
                               CheckEvent(CheckState.TIMEOUT, serial)])
    assert status(ed) == ("The check took longer than 30 seconds and was stopped. "
                          "Press F7 to try again.")
    assert ed.panel_paragraphs() == rows
    ed.win.check_now()
    ed.win.apply_check_events([CheckEvent(CheckState.CRASHED, serial, exit_code=1)])
    assert status(ed) == "The check stopped unexpectedly. Press F7 to try again."
    assert ed.panel_paragraphs() == rows and ed.dialogs == []

    ed.win.check_now()
    done(ed, E43, loaded=False, names={"position": (NameEntry("left"),)})
    assert ed.win.check_names["label"] == labels and ed.win.check_names["image"] == images
    assert ed.win.check_names["position"] == (NameEntry("left"),)
    assert ed.win.check_links == links and ed.win.check_stale
    ed.win.show_tab(1)
    ed.root.update_idletasks()
    assert [box.name for box in ed.story_map.layout.boxes] == ["start", "club"]
    assert MAP_OUT_OF_DATE in ed.story_map.note.cget("text")


# --- AC-F45-34: check as you type -------------------------------------------------------------

def test_ac34_check_as_you_type(studio, studio_game, monkeypatch):
    monkeypatch.setattr(window, "CHECK_DEBOUNCE_MS", 50)
    ed = studio(studio_game)
    requests = ed.checks.requests
    path = studio_game / "script" / "main.vns"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    ed.text.insert("end", "\n# one")
    ed.root.update()
    time.sleep(0.02)
    ed.text.insert("end", " two")
    # perf_counter, not monotonic: on Windows monotonic ticks in ~16 ms steps, so a 50 ms
    # wait could read as 47 ms. The debounce is scheduled just before ``second``, and Tk's
    # timer clock isn't Python's, hence a few ms of slack below 50.
    second = time.perf_counter()
    end = second + 2
    while len(requests) < 2 and time.perf_counter() < end:
        ed.root.update()
        time.sleep(0.002)
    waited = time.perf_counter() - second
    for _ in range(10):                                      # no second debounced request
        ed.root.update()
        time.sleep(0.01)
    assert len(requests) == 2 and waited >= 0.045
    overlay, serial, launch = requests[1]
    record = ed.current
    assert overlay_files(overlay) == {"script/main.vns": encode(record.doc, ed.body())}
    assert (serial, launch) == (ed.win.edit_serial, False)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before

    done(ed, seconds=6)                                       # a slow check: auto pauses
    ed.text.insert("end", " three")
    for _ in range(15):
        ed.root.update()
        time.sleep(0.01)
    assert len(requests) == 2
    ed.win.check_now()
    ed.win.save_current()
    assert len(requests) == 4

    done(ed)
    monkeypatch.setattr(window, "encode_overlay", lambda files: None)
    ed.text.insert("end", "\n# four")
    ed.win.check_now()
    assert requests[-1][0] is None
    assert status(ed) == "Checking… (unsaved changes not checked)"


# --- AC-F45-35: the warnings toggle -----------------------------------------------------------

def test_ac35_the_warnings_toggle(studio, studio_game):
    ed = studio(studio_game)
    ch2 = "script/ch2.vns"
    done(ed, CheckItem("error", "E1", "load", "error on 3.", ch2, 3, None),
         CheckItem("warning", "W1", "launch", "warning on 5.", ch2, 5, None),
         CheckItem("info", "TODO", "load", "info on 7.", ch2, 7, None))
    everything = ed.panel_paragraphs()
    assert len(everything) == 4
    ed.view_menu.invoke(window.SHOW_WARNINGS)
    assert not ed.win.show_warnings.get()
    assert ed.panel_paragraphs() == [everything[0], everything[1]]
    assert everything[0] == "Checked: 1 error, 1 warning."
    ed.view_menu.invoke(window.SHOW_WARNINGS)
    assert ed.panel_paragraphs() == everything


# --- AC-F45-36: the walkthrough with a real check ---------------------------------------------

def pump(ed: Editor, until, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ed.root.update()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out; status: {status(ed)!r}")


def test_ac36_the_walkthrough_with_a_real_check(tmp_path, monkeypatch):
    game = f45_games.studio(tmp_path)
    monkeypatch.setattr(window, "CHECK_DEBOUNCE_MS", 60_000)
    root = new_root()
    errors: list = []
    root.report_callback_exception = lambda *info: errors.append(info)
    runner = CheckRunner(game)
    try:
        ed = Editor(window.EditorWindow(root, GamePaths.for_game(game), check_runner=runner),
                    [])
        root.geometry("+-3000+-3000")
        root.update()
        pump(ed, lambda: counts(ed) == "\u2297 0  \u26a0 0" and not ed.win.check_running)
        assert ed.win.check_names.get("label")                  # load-only still names
        ed.open_file("script/ch2.vns")
        ed.text.insert("9.0", "    jump bridg\n")
        ed.press(ed.text, "<Control-s>")
        pump(ed, lambda: not ed.win.check_running)
        assert counts(ed) == "\u2297 1  \u26a0 0", ed.panel_paragraphs()
        assert ed.panel_paragraphs()[0] == "Checked: 1 error."
        row = ed.panel_paragraphs()[1]
        assert row.startswith("Error E43 script/ch2.vns, line 9: ")
        assert 'Did you mean "bridge"' in row
        ed.text.mark_set("insert", "9.0")
        root.update()
        assert ed.win.check_markers() == {9: "E"}
        assert markers(ed)[9][0] == "E"
        assert status(ed) == ed.win.check_result.problems[0].text
        proc = runner.process
        ed.win.close()
        if proc is not None:
            end = time.monotonic() + 2.5
            while proc.poll() is None and time.monotonic() < end:
                time.sleep(0.05)
            assert proc.poll() is not None
    finally:
        runner.stop()
        try:
            root.destroy()
        except tk.TclError:
            pass
    assert not errors, errors


# --- AC-F45-50: the status bar (F45 01 §6.5, amended 2026-11-02, user: VS Code dark) --------

def test_ac50_the_status_bar(studio, studio_game):
    """A blue strip along the whole bottom edge: the game folder, the check's counts and
    message, and the preview state on the left; Ln/Col, the indent, the encoding and the line
    ending on the right. It follows the cursor, the check, and the preview; the check items
    focus Problems; long texts are cut with "…", never wrapped."""
    (studio_game / "script" / "crlf.vns").write_bytes(
        b"\xef\xbb\xbflabel side2:\r\n\t\"Tabbed.\"\r\n")
    ed = studio(studio_game, mapped=True)
    root, bar = ed.root, ed.status_bar
    frame = bar.frame
    assert frame.cget("background") == "#007ACC"
    assert {item.label.cget("foreground") for item in bar.items} == {"#FFFFFF"}
    assert frame.winfo_width() == root.winfo_width()
    assert frame.winfo_y() + frame.winfo_height() == root.winfo_height()
    assert frame.winfo_height() >= 22
    texts = [str(w.cget("text")) for w in ed.left.winfo_children() if w.winfo_class() == "TLabel"]
    assert window.STARTS_AT in texts and "Not running." not in texts      # moved to the bar

    def shown():
        return [item.shown() for item in bar.items if item.shown()]

    assert shown() == ["my_game", "Checking…", "▶ Not running.", "Ln 1, Col 1",
                       "Spaces: 4", "UTF-8", "LF"]
    ed.text.mark_set("insert", "6.4")                       # a cursor move
    root.update()
    assert ed.cursor_item.cget("text") == "Ln 6, Col 5"
    done(ed, E43, CheckItem("warning", "W1", "launch", "w.", "script/main.vns", 2, None))
    assert shown()[:3] == ["my_game", "⊗ 1  ⚠ 1", "▶ Not running."]
    ed.text.mark_set("insert", "2.0")                       # the line's item is the message
    root.update()
    assert ed.check_status.cget("text") == "w."
    ed.win.show_event(PreviewEvent(PreviewState.RUNNING))
    assert ed.status_label.shown() == "▶ Running. F5 restarts it."

    ed.open_file("script/crlf.vns")                         # the file's own facts
    ed.text.mark_set("insert", "2.1")
    root.update()
    assert shown()[-4:] == ["Ln 2, Col 2", "Tab Size: 4", "UTF-8 with BOM", "CRLF"]
    ed.check_counts.label.event_generate("<Button-1>")      # a click: Problems gets the keys
    assert ed.focus() is ed.problems

    root.geometry("760x480")                                # the minimum size, a long message
    long = "a long message " * 40
    ed.check_status.configure(text=long)
    root.update()
    label = ed.check_status.label
    assert ed.check_status.cget("text") == long and label.cget("text").endswith("…")
    assert frame.winfo_height() == frame.winfo_reqheight()  # still one line
    right = max(item.label.winfo_x() + item.label.winfo_width() for item in bar.items
                if item.side == "left" and item.shown())
    assert right <= min(item.label.winfo_x() for item in bar.items
                        if item.side == "right" and item.shown())
    assert "\n" not in label.cget("text")
