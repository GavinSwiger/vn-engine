"""F42 W2/W3, File ▸ Build game… (``01-design.md`` §6, PR-F42-09..17, -21, -23; ``04`` §3.2;
``07`` I-11, I-12): AC-F42-17, 18, 25, 26, 27, 28, 32, 34.

Studio's real ``BuildRunner`` drives a fake build child: ``Child`` is the process
(``popen`` hands it out; the test writes its report lines into a pipe) and ``kill`` stands in
for ``taskkill /T``. The OS calls (Open folder, Run the game), the tool check and the pip
child are faked through ``builddialog``'s module names."""

import json
import os
import string
import time
from pathlib import Path

import pytest

from engine.core.editorreport import REPORT_MARKER
from engine.tools.build import procs, texts, tree
from engine.tools.editor import buildmodel, buildprefs, builddialog, dialogs
from engine.tools.editor.buildrunner import BuildRunner, InstallEvent
from tests.tools.editor.test_studio_window import studio  # noqa: F401  (fixture)

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.tk

FOLDER = "My Game 0.0.0 Windows"
EXE = "My Game.exe"
ZIP = FOLDER + ".zip"
TOOL_OK = procs.ToolStatus(None, procs.PYINSTALLER_VERSION)
STAGING = f".{FOLDER}.building-0123abcd"


def report(event: str, **fields) -> bytes:
    data = {"v": 1, "event": event, **fields}
    return REPORT_MARKER + json.dumps(data, separators=(",", ":")).encode("ascii") + b"\n"


class Child:
    """A fake build child: stdout is a pipe the test writes report lines into."""

    pid = 4242

    def __init__(self, argv, **kwargs) -> None:
        r, self._w = os.pipe()
        self.stdout = os.fdopen(r, "rb")
        self.returncode = None
        self.argv = list(argv)
        self.kwargs = kwargs
        self.killed = False

    def send(self, event: str, **fields) -> None:
        os.write(self._w, report(event, **fields))

    def step(self, i: int, key: str, m: int = 6, **fields) -> None:
        self.send("build_step", i=i, m=m, key=key, files=fields.get("files"),
                  bytes=fields.get("bytes"), staging=fields.get("staging"))

    def end(self, code: int) -> None:
        if self.returncode is None:
            self.returncode = code
            os.close(self._w)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class Builds:
    """The build children started, the snapshots taken at each start, and the clock."""

    def __init__(self) -> None:
        self.children: list[Child] = []
        self.at_start: list[dict[str, str]] = []
        self.now = 100.0
        self.watch: list[Path] = []

    def popen(self, argv, **kwargs) -> Child:
        child = Child(argv, **kwargs)
        self.children.append(child)
        self.at_start.append({str(p): p.read_text(encoding="utf-8") for p in self.watch})
        return child

    def kill(self, proc: Child) -> None:
        proc.killed = True
        proc.end(-9)

    @property
    def child(self) -> Child:
        return self.children[-1]


@pytest.fixture
def builds(monkeypatch):
    found = Builds()
    monkeypatch.setattr(builddialog, "make_runner", lambda root: BuildRunner(
        root, popen=found.popen, kill_tree=found.kill, clock=lambda: found.now))
    monkeypatch.setattr(builddialog, "clock", lambda: found.now)
    monkeypatch.setattr(builddialog, "tool_status", lambda: TOOL_OK)
    monkeypatch.setattr(dialogs, "_center", lambda window, over: window.geometry(
        "+-3000+-3000"))
    return found


@pytest.fixture
def asked(monkeypatch):
    """``builddialog.ask``'s questions; answers are queued in ``asked.answers``."""
    log: list[tuple] = []
    log_answers: list[int] = []

    def fake(parent, message, buttons, *, escape, default=0, icon=None):
        log.append((message, tuple(buttons), escape, default))
        return log_answers.pop(0)

    monkeypatch.setattr(builddialog, "ask", fake)
    errors: list[str] = []
    monkeypatch.setattr(builddialog, "show_error", lambda parent, text: errors.append(text))

    class Asked(list):
        answers = log_answers
        shown_errors = errors

    result = Asked()
    result.log = log
    return result


def pump(ed, until, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ed.root.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def open_dialog(ed) -> builddialog.BuildDialog:
    dialog = builddialog.open_build_dialog(ed.win)
    assert dialog is not None
    ed.root.update()
    return dialog


def start_build(ed, dialog, *, app_id: str = "my-game") -> Child:
    dialog.id_var.set(app_id)
    dialog.build()
    assert dialog.view == builddialog.PROGRESS
    return ed.win.build_runner.process


def make_earlier_build(save_to: Path, folder: str = FOLDER) -> Path:
    target = save_to / folder
    (target / tree.MARKER_DIR).mkdir(parents=True)
    (target / tree.MARKER_DIR / tree.MARKER_NAME).write_bytes(tree.marker_bytes(
        engine="0.1", app_id="my-game", version="0.0.0", built="2026-11-02"))
    (target / EXE).write_bytes(b"MZ")
    return target


def done_fields(**changes) -> dict:
    fields = {"folder": FOLDER, "exe": EXE, "files": 1214, "bytes": 96 << 20, "zip": ZIP,
              "zip_bytes": 41 << 20, "warnings": 0, "left_out": [], "left_out_total": 0,
              "long_paths": 0, "long_path_example": None}
    fields.update(changes)
    return fields


def entry_off(menu, index: int) -> bool:
    """The entry is off (dimmed by ``views.set_entry_enabled`` on Windows, else disabled)."""
    label = str(menu.entrycget(index, "label"))
    return label in getattr(menu, "_studio_off", set()) \
        or menu.entrycget(index, "state") == "disabled"


def labels(widget) -> list[str]:
    """Every label's text under ``widget``, in creation order."""
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() in ("TLabel", "Label") and str(child.cget("text")):
            found.append(str(child.cget("text")))
        found += labels(child)
    return found


# --- AC-F42-17 --------------------------------------------------------------------------------

def test_ac_f42_17_check_errors_stop_the_build_and_fill_problems_warnings_build(
        studio, route_game, builds, asked):
    ed = studio(route_game)
    dialog = open_dialog(ed)
    child = start_build(ed, dialog)
    error = {"severity": "error", "code": "E101", "source": "load", "text": "Unknown label",
             "file": "script/main.vns", "line": 7, "column": None}
    child.step(1, "check")
    child.send("problems", items=[error])
    child.send("done", loaded=True, problems=1, seconds=0.2)
    child.send("build_failed", code="B_ERRORS", values={"n": 1}, details=[])
    child.end(1)
    pump(ed, lambda: dialog.view == builddialog.FAILED)
    assert dialog.failure[:2] == (texts.B_ERRORS_ONE, texts.FAILURES["B_ERRORS"][1])
    assert labels(dialog.page)[:2] == [texts.B_ERRORS_ONE, texts.FAILURES["B_ERRORS"][1]]
    result = ed.win.check_result                         # applied as a check run
    assert [item.text for item in result.problems] == ["Unknown label"]
    assert any("Unknown label" in p for p in ed.win.panel_paragraphs())
    assert not builddialog.build_running(ed.win)

    dialog.show_setup()                                  # Try again: values kept
    assert dialog.id_var.get() == "my-game"
    child = start_build(ed, dialog)
    warning = dict(error, severity="warning", code="W12", text="Unused image")
    child.step(1, "check")
    child.send("problems", items=[warning])
    child.send("done", loaded=True, problems=1, seconds=0.2)
    child.send("build_done", **done_fields(warnings=1))
    child.end(0)
    pump(ed, lambda: dialog.view == builddialog.FINISHED)
    assert texts.warnings_text(1) in dialog.finished_lines
    assert texts.warnings_text(1) == "Built with 1 warning. They're listed in Problems."
    assert [item.text for item in ed.win.check_result.problems] == ["Unused image"]


# --- AC-F42-18 --------------------------------------------------------------------------------

def test_ac_f42_18_studio_saves_open_files_and_writes_details_before_the_child(
        studio, route_game, builds, asked):
    ed = studio(route_game)
    win = ed.win
    win.open_file("script/main.vns")
    win.text.insert("end", '\n    "Added before the build."')
    assert win.dirty_files()
    builds.watch = [route_game / "script" / "main.vns", route_game / "config.toml"]
    dialog = open_dialog(ed)
    assert dialog.messages.get("id") == texts.FIELD_MESSAGES["NO_ID"]
    assert dialog.build_button.instate(["disabled"])    # no Game ID yet
    assert dialog.slug_button.winfo_manager() and \
        dialog.slug_button.cget("text") == "Use my-game"
    dialog.slug_button.invoke()                          # Use my-game
    assert dialog.id_var.get() == "my-game" and not dialog.slug_button.winfo_manager()
    dialog.build()

    on_disk = builds.at_start[0]                         # what the child would read
    assert '"Added before the build."' in on_disk[str(route_game / "script" / "main.vns")]
    config = on_disk[str(route_game / "config.toml")]
    assert 'id = "my-game"' in config and 'title = "My Game"' in config
    assert not win.dirty_files() and win.armed           # saved, full checks armed
    argv = builds.child.argv
    assert argv[argv.index("build") + 1] == str(route_game)
    assert argv[argv.index("--out") + 1] == str(route_game.parent / "builds")
    assert "--zip" in argv and "--replace" not in argv and "--report-to-editor" in argv
    builds.child.end(1)


# --- AC-F42-25 --------------------------------------------------------------------------------

def test_ac_f42_25_progress_rows_counter_elapsed_slow_and_cancel(
        studio, route_game, builds, asked):
    ed = studio(route_game)
    dialog = open_dialog(ed)
    save_to = route_game.parent / "builds"
    child = start_build(ed, dialog)
    assert labels(dialog.page)[0] == "Building My Game 0.0.0"
    child.step(1, "check")
    child.step(2, "copy", files=214, bytes=85 << 20, staging=STAGING)
    builds.now = 110.0
    child.step(3, "pack", staging=STAGING)
    pump(ed, lambda: dialog.counter.cget("text") == "Step 3 of 6")
    builds.now = 151.0                                   # 41 s into packing
    dialog.draw_progress()
    assert dialog.progress_rows() == [
        ("✓", "Checking your game"),
        ("✓", "Copying the game folder (214 files, 85 MB)"),
        ("›", "Packing the engine and Python… 0:41"),
        ("", "Adding licenses and the read-me file"),
        ("", "Making the zip file"),
        ("", "Finishing up")]
    assert dialog.slow_label.winfo_manager() and dialog.slow_label.cget("text") == texts.SLOW
    assert float(dialog.bar.cget("value")) == pytest.approx(1000 * 2 / 6, abs=1)

    staging = save_to / STAGING                          # what the child had made
    staging.mkdir(parents=True)
    (staging / tree.STAGING_MARKER).write_bytes(tree.STAGING_MARKER_BYTES)
    asked.answers += [1]                                 # Esc: Keep building
    dialog._on_escape()
    assert asked.log[-1] == (texts.CANCEL_ASK, (texts.STOP_BUILD, texts.KEEP_BUILDING), 1, 1)
    assert builddialog.build_running(ed.win) and not child.killed
    started = time.monotonic()
    dialog.cancel_build_button.invoke()                  # Cancel build
    assert dialog.counter.cget("text") == builddialog.STOPPING
    assert dialog.cancel_build_button.instate(["disabled"])
    pump(ed, lambda: dialog.view == builddialog.CANCELLED)
    assert time.monotonic() - started < 5 and child.killed
    assert not staging.exists() and list(save_to.iterdir()) == []
    assert dialog.cancelled_line == "Build stopped. Nothing in builds was changed."


# --- AC-F42-26 --------------------------------------------------------------------------------

def _values_for(code: str) -> dict:
    message, fix = texts.FAILURES[code]
    sample = {"n": 3, "x": "6.0", "y": "6.22.3", "slug": "my-game", "ref": "dice.py",
              "module": "numpy", "game": "my_game", "folder": FOLDER, "save_to": "builds",
              "need": "300 MB", "free": "12 MB", "reason": texts.TOO_BIG_BYTES, "dll": "x.dll"}
    keys = {name for text in (message, fix) for _l, name, _f, _c in
            string.Formatter().parse(text) if name}
    return {key: sample[key] for key in keys}


def test_ac_f42_26_each_failure_shows_its_message_and_fix_details_and_install(
        studio, route_game, builds, asked, monkeypatch):
    ed = studio(route_game)
    dialog = open_dialog(ed)
    tail = [f"packer line {i} in <save-to>" for i in range(200)]
    for code in texts.FAILURES:
        child = start_build(ed, dialog)
        details = tail if code == "B_PACK_FAILED" else []
        child.send("build_failed", code=code, values=_values_for(code), details=details)
        child.end(1)
        pump(ed, lambda: dialog.view == builddialog.FAILED)
        message, fix = texts.failure(code, **_values_for(code))
        assert labels(dialog.page)[:2] == [message, fix], code
        if code == "B_PACK_FAILED":                      # Show details: 200 lines, Copy
            dialog.details_button.invoke()
            assert dialog.details_box.winfo_manager()
            assert dialog.details_box.text.get("1.0", "end-1c").split("\n") == tail
            copied: list[str] = []                       # the shared clipboard can be busy
            monkeypatch.setattr(dialog.dialog, "clipboard_append", copied.append)
            dialog.details_box.copy.invoke()
            assert copied[0].split("\n") == tail
        else:
            assert dialog.details_button is None
        names = [b.cget("text") for b in dialog.page.winfo_children()[-1].winfo_children()]
        assert names == ([builddialog.INSTALL] if code in builddialog.TOOL_KEYS else []) + [
            builddialog.CLOSE, builddialog.TRY_AGAIN], code
        dialog.try_button.invoke()
        assert dialog.view == builddialog.SETUP

    child = start_build(ed, dialog)                      # a crash: B_CRASHED + its output
    os.write(child._w, b"Traceback (most recent call last):\n")
    child.end(3)
    pump(ed, lambda: dialog.view == builddialog.FAILED)
    assert dialog.failure[:2] == texts.FAILURES["B_CRASHED"]
    assert dialog.failure[2] == ("Traceback (most recent call last):",)

    # B_NO_TOOL's Install build tool (D2): pip's lines in Setup, then Build is on.
    status = [procs.ToolStatus("B_NO_TOOL")]
    monkeypatch.setattr(builddialog, "tool_status", lambda: status[0])

    class Installer:
        def __init__(self) -> None:
            self.events: list[InstallEvent] = []
            self.started = 0

        def start(self):
            self.started += 1
            return None

        def poll(self):
            events, self.events = self.events, []
            return events

        def cancel(self):
            pass

    installer = Installer()
    monkeypatch.setattr(builddialog, "make_installer", lambda root: installer)
    child = start_build(ed, dialog)
    child.send("build_failed", code="B_NO_TOOL", values={}, details=[])
    child.end(1)
    pump(ed, lambda: dialog.view == builddialog.FAILED)
    install = dialog.page.winfo_children()[-1].winfo_children()[0]
    install.invoke()                                     # back to Setup, installing
    assert dialog.view == builddialog.SETUP and installer.started == 1
    assert dialog.tool_label.cget("text") == builddialog.INSTALLING
    assert dialog.build_button.instate(["disabled"])
    installer.events = [InstallEvent(("Collecting pyinstaller==6.22.3",))]
    pump(ed, lambda: dialog.install_lines() == ["Collecting pyinstaller==6.22.3"])
    status[0] = TOOL_OK
    installer.events = [InstallEvent(("Successfully installed pyinstaller",)),
                        InstallEvent(finished=True, exit_code=0)]
    pump(ed, lambda: not dialog.installing)
    assert dialog.tool_label.cget("text") == builddialog.INSTALLED
    assert dialog.build_button.instate(["!disabled"])


def test_f66_studio_app_never_offers_install_build_tool(studio, route_game, builds, asked,
                                                       monkeypatch):
    monkeypatch.setattr(builddialog, "can_install", lambda: False)
    status = [procs.ToolStatus("B_NO_TOOL")]
    monkeypatch.setattr(builddialog, "tool_status", lambda: status[0])
    ed = studio(route_game)
    dialog = open_dialog(ed)
    assert not dialog.install_button.winfo_manager()       # the line says why; no button
    assert dialog.build_button.instate(["disabled"])
    dialog.install()                                       # a stray call does nothing
    assert not dialog.installing
    dialog.tool = TOOL_OK
    child = start_build(ed, dialog)
    child.send("build_failed", code="B_NO_TOOL", values={}, details=[])
    child.end(1)
    pump(ed, lambda: dialog.view == builddialog.FAILED)
    names = [b.cget("text") for b in dialog.page.winfo_children()[-1].winfo_children()]
    assert names == [builddialog.CLOSE, builddialog.TRY_AGAIN]


# --- AC-F42-27 --------------------------------------------------------------------------------

def test_ac_f42_27_finished_view_texts_and_the_open_and_run_targets(
        studio, route_game, builds, asked, monkeypatch):
    opened: list[Path] = []
    ran: list[tuple[Path, Path]] = []
    monkeypatch.setattr(builddialog, "open_folder", opened.append)
    monkeypatch.setattr(builddialog, "run_game", lambda exe, folder: ran.append((exe, folder)))
    ed = studio(route_game)
    dialog = open_dialog(ed)
    save_to = route_game.parent / "builds"
    child = start_build(ed, dialog)
    target = make_earlier_build(save_to)                 # what the child installed
    left = [["saves", texts.LEFT_OUT_REASONS["LEFT_OUT_TESTDATA"]],
            [".studio", texts.LEFT_OUT_STUDIO]]
    # The event's own names are never used to open anything (I-11).
    child.send("build_done", **done_fields(folder="..\\elsewhere", exe="evil.exe",
                                           left_out=left, left_out_total=3))
    child.end(0)
    pump(ed, lambda: dialog.view == builddialog.FINISHED)
    assert dialog.finished_lines == [
        "Your game is built.",
        "..\\elsewhere — 96 MB, 1,214 files",
        f"{ZIP} — 41 MB",
        "Send players the zip file. They unzip it and open evil.exe.",
        texts.SMARTSCREEN,
        "3 files were left out."]
    dialog.list_button.invoke()                          # Show list
    assert dialog.left_out_box.text.get("1.0", "end-1c").split("\n") == [
        "saves — test-run data from your PC; players get their own",
        ".studio — Studio's own files"]
    assert str(dialog.run_button.cget("style")) == "TButton"     # the primary
    dialog.open_button.invoke()
    assert opened == [target]
    ed.root.focus_force()
    dialog.run_button.focus_set()
    dialog._on_enter(type("E", (), {"widget": dialog.dialog})())  # Enter: Run the game
    assert ran == [(target / EXE, target)]
    prefs = buildprefs.read_prefs(route_game)
    assert prefs.last_id == "my-game"


# --- AC-F42-28 --------------------------------------------------------------------------------

def test_ac_f42_28_menu_key_off_while_building_and_the_dialog_keys(
        studio, route_game, builds, asked):
    ed = studio(route_game, mapped=True)
    win = ed.win
    menu = win.file_menu
    rows = [(menu.type(i), str(menu.entrycget(i, "label")) if menu.type(i) == "command"
             else "", str(menu.entrycget(i, "accelerator")) if menu.type(i) == "command"
             else "") for i in range(menu.index("end") + 1)]
    at = rows.index(("command", "Save all", "Ctrl+Shift+S"))
    assert rows[at + 1][0] == "separator"
    assert rows[at + 2] == ("command", "Build game…", "Ctrl+Shift+B")

    ed.press(win.text, "<Control-Shift-B>")              # Ctrl+Shift+B opens it
    dialog = win.build_dialog
    assert dialog is not None and dialog.view == builddialog.SETUP
    ed.root.update()
    assert dialog.dialog.focus_get() is dialog.id_entry   # the first invalid field
    assert str(dialog.build_button.cget("style")) == "TButton"
    dialog.dialog.event_generate("<Escape>")             # Esc = Cancel
    ed.root.update()
    assert win.build_dialog is None

    dialog = open_dialog(ed)
    dialog.id_var.set("my-game")
    dialog._focus_setup()
    ed.root.update()
    assert dialog.dialog.focus_get() is dialog.build_button      # all valid: Build
    dialog.name_entry.focus_force()
    dialog.name_entry.event_generate("<Return>")         # Enter = Build
    ed.root.update()
    assert dialog.view == builddialog.PROGRESS
    child = builds.child
    assert builddialog.build_running(win)
    assert builddialog.open_build_dialog(win) is dialog  # no second dialog
    assert entry_off(menu, at + 2)                       # off while building
    child.send("build_failed", code="B_NO_ID", values={"slug": "my-game"}, details=[])
    child.end(1)
    pump(ed, lambda: dialog.view == builddialog.FAILED)
    assert not entry_off(menu, at + 2)
    dialog.dialog.focus_force()
    dialog.dialog.event_generate("<Return>")             # Failed: Enter = Try again
    ed.root.update()
    assert dialog.view == builddialog.SETUP

    make_earlier_build(route_game.parent / "builds")     # REPLACE_ASK: Cancel is default
    asked.answers += [1]
    dialog.build()
    assert asked.log[-1] == (texts.replace_ask(FOLDER, False), (texts.REPLACE, "Cancel"), 1, 1)
    assert dialog.view == builddialog.SETUP
    asked.answers += [0]
    dialog.build()
    assert "--replace" in builds.child.argv
    builds.child.send("build_done", **done_fields(zip=None, zip_bytes=None))
    builds.child.end(0)
    pump(ed, lambda: dialog.view == builddialog.FINISHED)
    dialog.dialog.focus_force()
    dialog.dialog.event_generate("<Escape>")             # Finished: Esc = Close
    ed.root.update()
    assert win.build_dialog is None and not dialog.alive


# --- AC-F42-32 --------------------------------------------------------------------------------

def test_ac_f42_32_build_json_keeps_save_to_and_zip_and_id_changed_shows(
        studio, route_game, builds, asked):
    ed = studio(route_game)
    dialog = open_dialog(ed)
    assert dialog.save_var.get() == str(route_game.parent / "builds")   # D6 default
    out = route_game.parent / "out"
    dialog.save_var.set(str(out))
    dialog.zip_var.set(False)
    child = start_build(ed, dialog)
    stored = json.loads((route_game / ".studio" / "build.json").read_text(encoding="utf-8"))
    assert stored == {"save_to": "../out", "zip": False}
    assert "--zip" not in child.argv
    child.send("build_done", **done_fields(zip=None, zip_bytes=None))
    child.end(0)
    pump(ed, lambda: dialog.view == builddialog.FINISHED)
    stored = json.loads((route_game / ".studio" / "build.json").read_text(encoding="utf-8"))
    assert stored == {"save_to": "../out", "zip": False, "last_id": "my-game"}
    dialog.close()

    dialog = open_dialog(ed)                             # remembered
    assert dialog.save_var.get() == str(out) and dialog.zip_var.get() is False
    assert dialog.id_var.get() == "my-game"
    assert dialog.hints["id"].cget("text") == texts.ID_HINT
    dialog.id_var.set("lanterns")
    assert dialog.hints["id"].cget("text") == texts.ID_CHANGED.format(old="my-game",
                                                                      new="lanterns")
    assert str(dialog.hints["id"].cget("style")) == "BuildWarn.TLabel"
    assert dialog.build_button.instate(["!disabled"])   # a warning, not a stop


# --- AC-F42-34 --------------------------------------------------------------------------------

def test_ac_f42_34_closing_studio_during_a_build_asks_and_stops_it(
        studio, route_game, builds, asked):
    ed = studio(route_game)
    dialog = open_dialog(ed)
    child = start_build(ed, dialog)
    ed.answers.append(1)                                 # Keep building (the default)
    ed.win.on_close()
    assert ed.dialogs[-1] == ("ask", texts.CLOSE_WHILE_BUILDING,
                              (texts.STOP_AND_CLOSE, texts.KEEP_BUILDING), 1, 1)
    assert not ed.win.closed and builddialog.build_running(ed.win) and not child.killed
    ed.answers.append(0)                                 # Stop and close
    ed.win.on_close()
    assert ed.win.closed and child.killed


# --- AC-F48-59 (F48 S9): key-shaped text found by the build --------------------------------------

def test_ac_f48_59_the_finished_view_lists_each_key_place(studio, route_game, builds, asked):
    ed = studio(route_game)
    dialog = open_dialog(ed)
    child = start_build(ed, dialog)
    child.send("build_done", **done_fields(keys=[["script/main.vns", 4], ["config.toml", 2]]))
    child.end(0)
    pump(ed, lambda: dialog.view == builddialog.FINISHED)
    shown = [texts.key_found_text("script/main.vns", 4), texts.key_found_text("config.toml", 2)]
    assert shown[0] == ("script/main.vns, line 4: this looks like an API key. "
                        "Remove it before you share the game.")
    assert all(line in labels(dialog.page) for line in shown)
    assert dialog.finished_lines[-2:] == shown and dialog.keys_box is None
    dialog.close()

    dialog = open_dialog(ed)
    child = start_build(ed, dialog)
    many = [[f"script/s{i}.vns", i + 1] for i in range(5)]
    child.send("build_done", **done_fields(keys=many))
    child.end(0)
    pump(ed, lambda: dialog.view == builddialog.FINISHED)
    assert texts.key_found_text("script/s0.vns", 1) in labels(dialog.page)
    assert texts.key_found_text("script/s4.vns", 5) not in labels(dialog.page)
    assert dialog.keys_box.text.get("1.0", "end-1c").splitlines() == [
        texts.key_found_text(ref, line) for ref, line in many]
