"""window.py's split (F47 ``04-technical.md`` §3.4): the extension points F47 and F42 wire
into. ``TABS`` makes the pages, the strip, the View menu rows and the Ctrl+digit keys;
``on_check_done`` runs after each applied check; ``join_runner`` adds a runner to the one
poll loop; ``record_for`` and ``apply_plan`` are the document API."""

from types import SimpleNamespace

import pytest

from engine.core.paths import GamePaths
from engine.tools.editor import tomlpatch
from engine.tools.editor.checker import CheckEvent, CheckResult, CheckState
from engine.tools.editor.scriptedit import FilePlan, LineEdit, Plan

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_window import FakeChecks, studio  # noqa: E402,F401
from tests.tools.editor.test_window import new_root  # noqa: E402

pytestmark = pytest.mark.tk


def menu_rows(menu: tk.Menu) -> list[tuple[str, str]]:
    return [(str(menu.entrycget(i, "label")), str(menu.entrycget(i, "accelerator")))
            for i in range(menu.index("end") + 1) if menu.type(i) == "command"]


def test_tabs_make_the_pages_the_strip_the_view_rows_and_the_keys(studio, studio_game):
    ed = studio(studio_game)
    win = ed.win
    titles = ["Editor", "Story map", "Database", "Game settings", "File preview",     # F47 W2, W4
              "Outline"]
    assert [tab.title for tab in window.TABS] == titles
    assert [win.notebook.tab(i, "text") for i in range(win.notebook.index("end"))] == titles
    assert len(win.tab_strip.cells) == 6
    assert menu_rows(win.view_menu)[:6] == [(t, f"Ctrl+{i}") for i, t in
                                            enumerate(titles, 1)]
    for digit in "123456":
        assert win.root.bind_all(f"<Control-Key-{digit}>")
    assert not win.root.bind_all("<Control-Key-7>")
    win.select_tab("asset")
    assert win.current_tab() == "asset" and win.notebook.index("current") == 4


def test_one_tabs_row_adds_a_tab(studio_game):
    class Extra(window.EditorWindow):
        tabs = window.TABS + (window.Tab("extra", "Extra", "outline", "_build_extra",
                                         "extra_frame", "extra_empty"),)

        def _build_extra(self):
            self.extra_frame = tk.Frame(self.notebook)
            self.extra_empty = SimpleNamespace(focus_widget=lambda: None)
            return self.extra_frame

    root = new_root()
    try:
        root.withdraw()
        win = Extra(root, GamePaths.for_game(studio_game), check_runner=FakeChecks())
        extra = len(window.TABS)
        assert win.notebook.tab(extra, "text") == "Extra"
        assert len(win.tab_strip.cells) == extra + 1
        assert ("Extra", f"Ctrl+{extra + 1}") in menu_rows(win.view_menu)
        assert root.bind_all(f"<Control-Key-{extra + 1}>")
        win.show_tab(extra)
        assert win.current_tab() == "extra" and win._tab_widget() is win.extra_frame
        win.close()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_on_check_done_runs_after_each_applied_check(studio, studio_game):
    ed = studio(studio_game)
    win = ed.win
    seen = []
    win.on_check_done.append(lambda result: seen.append((result, win.panel_paragraphs()[0])))
    result = CheckResult(problems=(), problem_total=0, names={}, links=None, loaded=False,
                         serial=win.edit_serial, seconds=0.1)
    win.apply_check_events([CheckEvent(CheckState.STARTED, result.serial)])
    assert seen == []
    win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    assert seen == [(result, "Checked: no problems.")]          # after the panel


def test_a_joined_runner_is_polled_and_stopped(studio, studio_game):
    ed = studio(studio_game)
    win = ed.win

    class Runner:
        stopped = False

        def poll(self):
            return ["event"]

        def stop(self):
            self.stopped = True

    runner, got = Runner(), []
    win.join_runner(runner, got.append)
    win._poll_preview()
    assert got == [["event"]]
    win.close()
    assert runner.stopped


def test_record_for_and_apply_plan(studio, studio_game):
    ed = studio(studio_game)
    win = ed.win
    shown, tab = win.current, win.current_tab()
    record = win.record_for("config.toml")
    assert win.current is shown and win.current_tab() == tab        # opened, not shown
    assert record.editable and not record.dirty
    before = record.widget.get("1.0", "end-1c")
    toml = tomlpatch.plan_set(before, "game", "title", "Lantern Night")
    assert isinstance(toml, tomlpatch.TomlPlan)
    texts = []
    assert not win.apply_plan(toml.as_plan(), lambda now: texts.append(now) or False)
    assert texts == [{"config.toml": before}]
    assert record.widget.get("1.0", "end-1c") == before             # refused: unchanged
    assert win.apply_plan(toml.as_plan(),
                          lambda now: tomlpatch.verify(toml, now["config.toml"]))
    assert 'title = "Lantern Night"' in record.widget.get("1.0", "end-1c")
    assert record.dirty
    record.widget.edit_undo()                                       # one undo step
    assert record.widget.get("1.0", "end-1c") == before
    two = Plan("two", (FilePlan("script/main.vns", (), (LineEdit(1, 0, ("# a",)),)),
                       FilePlan("config.toml", (), (LineEdit(1, 0, ("# b",)),))))
    assert win.apply_plan(two, lambda now: set(now) == {"script/main.vns", "config.toml"})
    assert win.files["script/main.vns"].widget.get("1.0", "1.end") == "# a"
    assert record.widget.get("1.0", "1.end") == "# b"
