"""F46's visual story editor in the Studio window (``06-acceptance.md`` AC-F46-04, step 1b).

Studio L: the Studio window on a copy of ``tests/fixtures/F46/games/lanterns/`` with the fake
check runner of ``test_studio_window.py`` (it records requests and never answers them), after
one fake ``DONE`` holding L's labels and links. ``livemap.FOLLOW_MS`` is patched to 20 ms;
the real values (F58 C1: 80 ms, 250 ms max wait) are asserted first. The pure halves are ``test_scenes.py`` and ``test_storymap*.py``."""

import shutil
import time
from pathlib import Path

import pytest

from engine.script.labelgraph import LabelLink
from engine.tools.editor import (
    assist, document, formdialogs, forms, layoutfile, livemap, scenes, scriptedit, storymap,
    views)
from engine.tools.editor.checker import CheckEvent, CheckResult, CheckState, NameEntry
from engine.tools.editor.theme import THEME

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.conftest import patch_studio  # noqa: E402
from tests.tools.editor.test_studio_window import studio, tab  # noqa: E402,F401
from tests.tools.editor.test_window import take_focus  # noqa: E402

pytestmark = pytest.mark.tk

LANTERNS = Path(__file__).resolve().parents[2] / "fixtures" / "F46" / "games" / "lanterns"
MAIN, CH2 = "script/main.vns", "script/ch2.vns"
# L's labels and links, as the check child sends them (06 §5; AC-F46-03's choice fields).
L_LABELS = (NameEntry("start", MAIN, 6), NameEntry("festival", MAIN, 12),
            NameEntry("stall", CH2, 1), NameEntry("river", CH2, 11))
L_LINKS = (LabelLink("start", "festival", "jump", MAIN, 10),
           LabelLink("festival", "stall", "call", MAIN, 14),
           LabelLink("stall", "river", "menu", CH2, 5, "Buy the red one", True),
           LabelLink("stall", "river", "jump", CH2, 9))


@pytest.fixture
def lanterns(tmp_path) -> Path:
    game = tmp_path / "lanterns"
    shutil.copytree(LANTERNS, game)
    return game


def studio_l(studio, game: Path):
    ed = studio(game, mapped=True)
    result = CheckResult(problems=(), problem_total=0, names={"label": L_LABELS},
                         links=L_LINKS, loaded=True, serial=ed.win.edit_serial, seconds=0.1)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    ed.press(ed.text, "<Control-Key-2>")
    assert tab(ed) == "Story map"
    return ed


def edges(view) -> set[tuple[str, str, str]]:
    boxes = view.layout.boxes
    return {(boxes[e.src].name, boxes[e.dst].name, e.kind) for e in view.layout.edges}


def boxes(view) -> dict[str, tuple]:
    return {b.name: (b.file, b.line, b.x, b.y, b.marks) for b in view.layout.boxes}


def rect_item(view, name: str) -> int:
    """Box ``name``'s rectangle item (F58: the painter's registry, I-10)."""
    return view.painter.boxes[name].rect


def chip_parts(view, index: int) -> dict[str, int]:
    """Edge ``index``'s chip items by role: ``box``, ``text`` and (a condition) ``if``."""
    items = view.chip_items(index)
    parts = {"box": items[0], "text": items[-1]} if items else {}
    if len(items) == 3:
        parts["if"] = items[1]
    return parts


def wait_follow(ed, calls: list) -> None:
    """Run Tk's timers until ``follow`` ran, then let the map redraw."""
    end = time.monotonic() + 5
    while not calls and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.002)
    ed.root.update()


def test_ac_f46_04_the_map_follows_typing_and_choice_arrows_show_their_text(
        studio, lanterns, monkeypatch):
    assert (livemap.FOLLOW_MS, livemap.FOLLOW_MAX_MS) == (80, 250)     # F58 C1
    monkeypatch.setattr(livemap, "FOLLOW_MS", 20)
    on_disk = {ref: (lanterns / ref).read_bytes() for ref in (MAIN, CH2)}
    ed = studio_l(studio, lanterns)
    view = ed.story_map
    win = ed.win
    result, requests = win.check_result, len(ed.checks.requests)
    assert ("festival", "river", "jump") not in edges(view)

    calls: list[int] = []
    follow = win.follow
    monkeypatch.setattr(win, "follow", lambda: (calls.append(1), follow())[1])
    parsed: list[str] = []
    parse = scenes.parse_chunk
    monkeypatch.setattr(scenes, "parse_chunk", lambda ref, chunk, **kw: (
        parsed.append(chunk.split(":", 1)[0].split()[1]), parse(ref, chunk, **kw))[1])

    # Type `    jump river` as a new main 15: five keys 5 ms apart, the timer not yet run.
    main = win.files[MAIN]
    main.widget.mark_set("insert", "15.0")
    before = main.changes
    for piece in ("    ", "jump", " ", "river", "\n"):
        main.widget.insert("insert", piece)
        ed.root.update_idletasks()
        time.sleep(0.005)
    assert main.changes == before + 5                    # counted at once, per change
    assert main.widget.get("15.0", "15.end") == "    jump river"
    assert ("festival", "river", "jump") not in edges(view) and not calls
    wait_follow(ed, calls)
    assert ("festival", "river", "jump") in edges(view)
    assert calls == [1] and parsed == ["festival"]
    assert win.check_result is result                    # no new DONE: the map followed

    # ch2 9 becomes `    jump`: stall keeps its last links and reads "out of date".
    win.open_file(CH2)
    ed.press(ed.text, "<Control-Key-2>")
    shown = boxes(view)
    ch2 = win.files[CH2]
    ch2.widget.delete("9.4", "9.end")
    ch2.widget.insert("9.4", "jump")
    calls.clear()
    wait_follow(ed, calls)
    m = view.layout
    stall = m.index_of("stall")
    assert "out of date" in m.boxes[stall].marks
    assert "out of date" in ed.map_canvas.itemcget(view.painter.boxes["stall"].marks, "text")
    assert {("stall", "river", "menu"), ("stall", "river", "jump")} <= edges(view)
    after = boxes(view)
    assert {k: v for k, v in after.items() if k != "stall"} == {
        k: v for k, v in shown.items() if k != "stall"}

    # stall → river (menu): dotted, its chip reads the choice, with an `if` mark.
    canvas = ed.map_canvas
    menu = next(i for i, e in enumerate(m.edges)
                if (m.boxes[e.src].name, e.kind) == ("stall", "menu"))
    item, kind = view.edge_item(menu), m.edges[menu].kind
    assert kind == "menu" and canvas.itemcget(item, "dash") == "2 4"
    chip = chip_parts(view, menu)
    assert canvas.itemcget(chip["text"], "text") == "Buy the red one"
    assert canvas.itemcget(chip["if"], "text") == "if"
    assert canvas.itemcget(chip["box"], "fill") == THEME["map.chip"]
    assert canvas.itemcget(chip["text"], "fill") == THEME["map.chipText"]
    jump = next(i for i, e in enumerate(m.edges)
                if (m.boxes[e.src].name, e.kind) == ("stall", "jump"))
    assert not view.chip_items(jump)                     # only choice arrows have chips

    # A 30-character choice: the chip shows its first 24 characters, then "…".
    long = "Buy the red one for 2 coins!!"
    long += "!" * (30 - len(long))
    assert len(long) == 30
    ch2.widget.delete("9.4", "9.end")
    ch2.widget.insert("9.4", "jump river")
    ch2.widget.delete("3.8", "3.25")
    ch2.widget.insert("3.8", f'"{long}"')
    assert ch2.widget.get("3.0", "3.end") == f'        "{long}" if coins > 0:'
    calls.clear()
    wait_follow(ed, calls)
    m = view.layout
    stall = m.index_of("stall")
    assert "out of date" not in m.boxes[stall].marks
    menu = next(i for i, e in enumerate(m.edges)
                if (m.boxes[e.src].name, e.kind) == ("stall", "menu"))
    assert canvas.itemcget(chip_parts(view, menu)["text"], "text") == long[:24] + "…"

    assert len(ed.checks.requests) >= requests          # the fake runner answered nothing
    assert win.check_result is result
    assert {ref: (lanterns / ref).read_bytes() for ref in (MAIN, CH2)} == on_disk


# --- Step 2: side pane tabs and the read-only Events list (AC-F46-05, 09) ----------------------

def side_page(ed) -> str:
    return ed.side_book.tab(ed.side_book.select(), "text")


def click_box(ed, name: str) -> None:
    """A real click on box ``name`` (scrolled into view first)."""
    view, canvas = ed.story_map, ed.map_canvas
    i = view.layout.index_of(name)
    view.see(i)
    ed.root.update()
    x0, y0, x1, y1 = canvas.coords(rect_item(view, name))
    x, y = int((x0 + x1) / 2 - canvas.canvasx(0)), int((y0 + y1) / 2 - canvas.canvasy(0))
    canvas.event_generate("<Button-1>", x=x, y=y)
    canvas.event_generate("<ButtonRelease-1>", x=x, y=y)     # F46: the release opens it
    ed.root.update()


def click_row(ed, index: int) -> None:
    tree = ed.events_view.tree
    tree.see(f"{index + 1}.0")
    ed.root.update()
    _x, y, _w, h, _base = tree.dlineinfo(f"{index + 1}.0")
    tree.event_generate("<Button-1>", x=40, y=y + h // 2)
    ed.root.update()


def test_ac_f46_05_side_pane_tabs(studio, lanterns):
    ed = studio_l(studio, lanterns)
    win, canvas, events = ed.win, ed.map_canvas, ed.events_view
    assert win.side_tab == "script"
    click_box(ed, "river")                               # a click opens on Script
    assert win.side_tabs.words() == ["Events", "Script"]
    assert side_page(ed) == "Script" and ed.current.ref == CH2
    assert ed.text is ed.side_text and ed.side_text.index("insert") == "11.0"
    ed.press(canvas, "<Control-e>")                      # Ctrl+E on the map: Events
    assert side_page(ed) == "Events" and ed.focus() is canvas
    assert events.title.cget("text") == "river"
    assert events.texts()[:2] == ["Show character  hana happy · left", "Say  hana: You came!"]
    click_box(ed, "festival")                            # remembered: Events
    assert side_page(ed) == "Events" and ed.current.ref == MAIN
    assert events.title.cget("text") == "festival"
    assert events.texts() == ["Narration  The lanterns were lit.", "Visit scene  stall",
                              "Return", "◆"]
    ed.press(events.tree, "<Control-e>")                 # Ctrl+E in the Events list
    assert side_page(ed) == "Script" and ed.focus() is ed.side_text
    ed.press(ed.side_text, "<Escape>")                   # Esc closes the pane
    assert not win._side_open and ed.focus() is canvas
    ed.story_map.focus_box(ed.story_map.layout.index_of("start"))
    ed.press(canvas, "<Return>")                         # Enter on start: Script
    assert win._side_open and side_page(ed) == "Script"
    assert ed.side_text.index("insert") == "6.0"
    side = ed.side_text
    side.mark_set("insert", "9.4")
    ed.press(side, "<Control-e>")                        # G8: from the Script text too
    assert side_page(ed) == "Events" and ed.focus() is events.tree
    assert side.index("insert") == "9.4" and events.selected() == 1
    ed.press(events.tree, "<Escape>")
    ed.press(canvas, "<Control-Return>")                 # Ctrl+Enter: the Editor tab
    assert tab(ed) == "Editor" and ed.text.index("insert") == "6.0"
    body = ed.text.get("1.0", "end-1c")
    ed.text.mark_set("insert", "9.0")
    ed.press(ed.text, "<Control-e>")                     # the Editor tab's Ctrl+E: Tk's own
    assert not ed.text.bind("<Control-e>") and win.side_tab == "events"
    assert ed.text.get("1.0", "end-1c") == body

    fresh = studio_l(studio, lanterns)                   # a new window starts on Script
    assert fresh.win.side_tab == "script"
    click_box(fresh, "river")
    assert side_page(fresh) == "Script" and win.side_tab == "events"


def test_ac_f46_09_rows_and_text_stay_in_step_and_f6(studio, lanterns, monkeypatch):
    monkeypatch.setattr(livemap, "FOLLOW_MS", 20)
    ed = studio_l(studio, lanterns)
    canvas, events = ed.map_canvas, ed.events_view
    click_box(ed, "start")
    ed.press(canvas, "<Control-e>")
    assert side_page(ed) == "Events" and events.texts() == [
        "Background  bg room · dissolve", "Say  hana (happy): Welcome to the festival!",
        "Go to scene  festival", "◆"]
    side = ed.side_text
    click_row(ed, 1)                                     # a row → the Script cursor
    assert events.selected() == 1 and side.index("insert") == "9.0"
    assert ed.focus() is events.tree
    ed.press(events.tree, "<Control-e>")
    side.mark_set("insert", "10.4")                      # the cursor → the row
    ed.press(side, "<Control-e>")
    assert events.texts()[events.selected()] == "Go to scene  festival"

    click_box(ed, "river")                               # opens on Events now
    assert events.title.cget("text") == "river" and events.selected() == 0
    row = events.texts().index("Script  $ notes = [stall]")
    for _ in range(row):
        ed.press(events.tree, "<Down>")
    assert events.selected() == row and ed.side_text.index("insert") == "15.0"
    ed.press(events.tree, "<Return>")                    # Enter on a Script row: Script
    assert side_page(ed) == "Script" and ed.focus() is ed.side_text
    assert ed.side_text.index("insert") == "15.0"

    ed.press(ed.side_text, "<Control-e>")                # typing: the rows follow
    calls: list[int] = []
    follow = ed.win.follow
    monkeypatch.setattr(ed.win, "follow", lambda: (calls.append(1), follow())[1])
    ed.side_text.insert("17.0", "    pause 1\n")
    wait_follow(ed, calls)
    assert events.texts()[-3:] == ["Wait  1 s", "Return", "◆"]
    assert events.selected() == row                      # the cursor's row, still
    # F6 with Events shown
    order = [ed.tree, canvas, events.tree, ed.play_button, ed.problems, ed.help_text]
    seen = [ed.tree]
    ed.press(ed.tree, "<F6>")
    for _ in range(len(order)):
        seen.append(ed.focus())
        ed.press(seen[-1], "<F6>")
    assert seen == order + [ed.tree]
    back = [ed.tree]
    for _ in range(len(order)):
        ed.press(back[-1], "<Shift-F6>")
        back.append(ed.focus())
    assert back == [ed.tree] + order[::-1]


# --- Step 3: editing from the Events list (AC-F46-12 act half, 13, 16, 18, 20) -----------------
# The planners are test_scriptedit.py's and the forms test_forms.py's; these rows drive the
# window. The real picker and form dialogs are built (not run modally) and answered in place.

def events_on(ed, name: str) -> None:
    """Box ``name`` in the side pane, on the Events page."""
    click_box(ed, name)
    if side_page(ed) != "Events":
        ed.press(ed.map_canvas, "<Control-e>")
    assert ed.events_view.title.cget("text") == name


def row_of(ed, text: str) -> int:
    return ed.events_view.texts().index(text)


def line(ed, ref: str, number: int) -> str:
    return ed.win.files[ref].widget.get(f"{number}.0", f"{number}.end")


def answer_dialogs(monkeypatch, picks: list, values: list, seen: dict) -> None:
    """``formdialogs.pick_insert`` and ``edit_form`` answered from the queues with the real
    dialogs: a pick is (group, entry) or None (Esc); values are the fields to type (the line
    preview is checked as each is typed) or None (Cancel), or a callable run first (it may
    edit the text) that returns them."""
    def pick(parent, menu):
        picker = formdialogs.InsertPicker(parent, menu)
        seen["picker"] = picker.entries()
        answer = picks.pop(0)
        if answer is None:
            assert picker.dialog.bind("<Escape>")
            picker._pick(1)
        else:
            picker.choose(*answer)
            picker._pick(0)
        return picker.result

    def edit(parent, form, start, *, names, ok="OK", assets=None):
        dialog = formdialogs.FormDialog(parent, form, start, names=names, ok=ok, assets=assets)
        answer = values.pop(0)
        if callable(answer):
            answer = answer()
        if answer is None:
            dialog._pick(1)
            return dialog.result
        previews = []
        for key, value in answer.items():
            dialog.vars[key].set(value)
            previews.append((dialog.card.get("1.0", "end-1c"), form.write(dialog.values())))
        seen["previews"] = previews
        seen["hints"] = dialog.hints()
        dialog._pick(0)
        return dialog.result

    monkeypatch.setattr(formdialogs, "pick_insert", pick)
    monkeypatch.setattr(formdialogs, "edit_form", edit)


def test_ac_f46_16_insert(studio, lanterns, monkeypatch):
    picks, values, seen = [], [], {}
    answer_dialogs(monkeypatch, picks, values, seen)
    ed = studio_l(studio, lanterns)
    events, tree = ed.events_view, ed.events_view.tree
    events_on(ed, "festival")
    click_row(ed, row_of(ed, "Visit scene  stall"))
    picks.append(("Stage", "Background"))
    values.append({"image": "bg room", "transition": "fade"})
    ed.press(tree, "<Insert>")
    assert [(g, d) for g, docs in assist.insert_menu() for d in docs] == [
        (g, d) for g, d in seen["picker"] if not isinstance(d, forms.CommandForm)]  # F47 P2
    assert line(ed, MAIN, 14) == "    scene bg room with fade"
    assert line(ed, MAIN, 15) == "    call stall"
    assert seen["previews"] == [("scene bg room", "scene bg room"),
                                ("scene bg room with fade", "scene bg room with fade")]
    assert events.texts()[events.selected()] == "Background  bg room · fade"

    # Enter on the last ◆ row, then Text ▸ Say: after the `return` line.
    events.select(len(events.rows) - 1)
    picks.append(("Text", "Say"))
    values.append({"speaker": "hana", "text": "Hi there."})
    ed.press(tree, "<Return>")
    assert (line(ed, MAIN, 16), line(ed, MAIN, 17)) == ("    return", '    hana "Hi there."')

    # A text-only doc: its example above the row, then Script with fields[0] selected.
    # (``at`` stays text only for good: F47 gave ``shake`` a form.)
    position = next(d for _g, docs in assist.insert_menu() for d in docs if d.key == "at")
    click_row(ed, 0)
    picks.append(("Stage", "Position"))
    events.buttons["insert"].invoke()                    # the button does what the key does
    ed.root.update()
    text, _sel = assist.insert_text(position, "    ", "    ")
    assert line(ed, MAIN, 13) == text == "    show hana sad at right"
    assert side_page(ed) == "Script" and ed.focus() is ed.side_text
    assert ed.side_text.get("sel.first", "sel.last") == position.fields[0]

    # A name not in the index: the hint, and OK writes it.
    ed.press(ed.side_text, "<Control-e>")
    click_row(ed, 0)
    picks.append(("Stage", "Background"))
    values.append({"image": "bg nowhere"})
    ed.press(tree, "<Insert>")
    assert seen["hints"]["image"] == formdialogs.NOT_FOUND == \
        "Not found yet; the check will tell you."
    assert line(ed, MAIN, 13) == "    scene bg nowhere"

    # Cancel on a form and Esc on the picker write nothing.
    body = ed.win.files[MAIN].widget.get("1.0", "end-1c")
    picks.extend([("Stage", "Background"), None])
    values.append(None)
    ed.press(tree, "<Insert>")
    ed.press(tree, "<Insert>")
    assert ed.win.files[MAIN].widget.get("1.0", "end-1c") == body and not picks

    # stall: Insert on Just look's ◆ (a `$ pass` block) replaces the `$ pass` (G2).
    events_on(ed, "stall")
    ends = [i for i, row in enumerate(events.rows) if row.kind == "end"]
    click_row(ed, ends[1])
    picks.append(("Story flow", "Go to scene"))
    values.append({"scene": "festival"})
    ed.press(tree, "<Insert>")
    assert line(ed, CH2, 7) == "            jump festival"
    assert line(ed, CH2, 8) == '    "You walk past the stall."'


def test_ac_f46_13_refusals_stale_broken_locked(studio, lanterns, monkeypatch, tmp_path):
    monkeypatch.setattr(livemap, "FOLLOW_MS", 60_000)    # no follow unless an action asks
    monkeypatch.setattr(livemap, "FOLLOW_MAX_MS", 60_000)
    picks, values, seen = [], [], {}
    answer_dialogs(monkeypatch, picks, values, seen)
    ed = studio_l(studio, lanterns)
    story, events, tree = ed.story, ed.events_view, ed.events_view.tree
    said: list[str] = []
    say = story.say
    monkeypatch.setattr(story, "say", lambda text, place=None: (said.append(text),
                                                                 say(text, place))[1])
    main = ed.win.files[MAIN].widget

    # Stale: a line typed above the row, no follow yet.
    events_on(ed, "festival")
    click_row(ed, row_of(ed, "Visit scene  stall"))
    before = main.get("1.0", "end-1c")
    main.insert("13.0", '    "x"\n')
    ed.press(tree, "<Delete>")
    assert main.get("1.0", "end-1c") == before.replace(
        "label festival:\n", 'label festival:\n    "x"\n')
    assert story.status == scriptedit.STALE == \
        "This scene changed in the text, so nothing was changed. Try again."
    assert events.texts()[:2] == ["Narration  x", "Narration  The lanterns were lit."]

    # Stale: the Say form open on main 9 while main 9 changes in the text.
    events_on(ed, "start")
    click_row(ed, row_of(ed, "Say  hana (happy): Welcome to the festival!"))

    def typed_meanwhile():
        main.insert("9.4", "hana ")
        return {"text": "Changed"}
    values.append(typed_meanwhile)
    body = main.get("1.0", "end-1c").replace("    hana happy", "    hana hana happy", 1)
    ed.press(tree, "<F2>")
    assert main.get("1.0", "end-1c") == body and story.status == scriptedit.STALE

    # Broken: ch2 9 is `    jump`; a stall action says where to fix it, with a link.
    events_on(ed, "stall")
    ch2 = ed.win.files[CH2].widget
    ch2.delete("9.4", "9.end")
    ch2.insert("9.4", "jump")
    ed.win.follow()
    ed.root.update()
    shown = ch2.get("1.0", "end-1c")
    click_row(ed, row_of(ed, "Narration  You walk past the stall."))
    ed.press(tree, "<Delete>")
    assert ch2.get("1.0", "end-1c") == shown
    assert story.status == "Fix the problem in `ch2.vns`, line 9 first."
    assert events.on_link is not None
    events.message.event_generate("<Button-1>")
    ed.root.update()
    assert side_page(ed) == "Script" and ed.side_text.index("insert") == "9.0"
    events_on(ed, "festival")                            # other scenes stay editable
    click_row(ed, row_of(ed, "Narration  x"))
    ed.press(tree, "<Alt-Down>")
    assert (line(ed, MAIN, 13), line(ed, MAIN, 14)) == (
        '    "The lanterns were lit."', '    "x"')

    # Locked: main.vns opened read-only by F44 (its size cap below the file's size).
    monkeypatch.setattr(document, "SCRIPT_FILE_MAX_BYTES",
                        (lanterns / MAIN).stat().st_size - 1)
    on_disk = (lanterns / MAIN).read_bytes()
    locked = studio_l(studio, lanterns)
    record = locked.win._record(MAIN)
    assert not record.editable
    shown_text = record.widget.get("1.0", "end-1c")
    locked.story.show(MAIN, "start")
    locked.events_view.buttons["insert"].invoke()
    assert locked.story.status == record.error.format() and locked.story.status
    assert record.widget.get("1.0", "end-1c") == shown_text
    assert (lanterns / MAIN).read_bytes() == on_disk and not picks
    for text in said + [locked.story.status]:
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text


def test_ac_f46_18_one_action_one_undo_step(studio, lanterns, monkeypatch):
    patch_studio(monkeypatch, "CHECK_DEBOUNCE_MS", 20)
    picks, values, seen = [], [], {}
    answer_dialogs(monkeypatch, picks, values, seen)
    on_disk = (lanterns / MAIN).read_bytes()
    ed = studio_l(studio, lanterns)
    story, events, tree = ed.story, ed.events_view, ed.events_view.tree
    events_on(ed, "festival")
    main = ed.win.files[MAIN].widget
    old = main.get("1.0", "end-1c")

    # AC-F46-12's act half: a plan that fails verify writes nothing.
    row = story.rows[0]
    assert story.act(lambda read, lines, start: scriptedit.plan_form(
        read, lines, start, row, '"The lanterns glowed.')) is None
    assert main.get("1.0", "end-1c") == old and story.status == scriptedit.UNSAFE == \
        "Studio couldn't make this change safely. Change it in the text."

    requests = len(ed.checks.requests)
    click_row(ed, 0)
    values.append({"text": "The lanterns glowed."})
    ed.press(tree, "<Return>")
    new = old.replace('"The lanterns were lit."', '"The lanterns glowed."')
    assert ed.side_text.get("1.0", "end-1c") == new
    assert ed.side_text.get("13.0", "13.end") == '    "The lanterns glowed."'
    assert ed.row(MAIN).startswith("* ")
    assert (lanterns / MAIN).read_bytes() == on_disk
    end = time.monotonic() + 5
    while len(ed.checks.requests) == requests and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.005)
    assert len(ed.checks.requests) > requests
    assert events.texts()[0] == "Narration  The lanterns glowed."

    history = ed.win.map_history                         # the form edit: one map step
    assert len(history) == 1 and history.undo_step().files == (
        (MAIN, ed.win.files[MAIN].changes),)
    side = ed.side_text
    ed.press(tree, "<Control-e>")                        # the Script page
    assert ed.focus() is side
    ed.press(side, "<Control-z>")                        # one Ctrl+Z: the exact old text
    assert main.get("1.0", "end-1c") == old
    # 07 I-6, real Tk: the text's own Ctrl+Z raised the counter, so map undo is blocked.
    assert storymap.stale_files(history.undo_step(), ed.win.files) == (MAIN,)
    ed.press(side, "<Control-y>")
    assert main.get("1.0", "end-1c") == new
    ed.press(side, "<Control-e>")                        # in Events, the same
    ed.press(tree, "<Control-z>")
    assert main.get("1.0", "end-1c") == old
    assert events.texts()[0] == "Narration  The lanterns were lit."
    ed.press(tree, "<Control-y>")
    assert main.get("1.0", "end-1c") == new

    main.insert("1.0", "#")                              # a typed key, then map Ctrl+Z
    ed.press(ed.map_canvas, "<Control-z>")
    assert ed.story_map.message == (
        "`main.vns` was changed after this. Undo it in the text (Ctrl+Z there).")
    assert ed.story_map.note.cget("text") == ed.story_map.message
    assert main.get("1.0", "end-1c") == "#" + new and len(history) == 0


def test_ac_f46_20_drag_rows_copy_and_paste(studio, lanterns):
    ed = studio_l(studio, lanterns)
    events, tree = ed.events_view, ed.events_view.tree
    main = ed.win.files[MAIN].widget
    events_on(ed, "start")
    old = main.get("1.0", "end-1c")

    def y_of(index: int) -> int:
        tree.see(f"{index + 1}.0")
        ed.root.update()
        _x, y, _w, h, _b = tree.dlineinfo(f"{index + 1}.0")
        return y + h // 2

    say, background = y_of(1), y_of(0)                   # drag Say onto Background
    tree.event_generate("<Button-1>", x=40, y=say)
    tree.event_generate("<B1-Motion>", x=40, y=say - 3)
    tree.event_generate("<B1-Motion>", x=40, y=background)
    tree.event_generate("<ButtonRelease-1>", x=40, y=background)
    ed.root.update()
    assert [line(ed, MAIN, n) for n in (7, 8, 9)] == [
        '    hana happy "Welcome to the festival!"  # first line', "    # Mia arrives",
        "    scene bg room with dissolve"]                # what AC-F46-17 row 1 writes
    ed.press(tree, "<Control-z>")
    assert main.get("1.0", "end-1c") == old

    click_row(ed, row_of(ed, "Background  bg room · dissolve"))
    ed.press(tree, "<Control-c>")
    assert ed.root.clipboard_get() == "# Mia arrives\nscene bg room with dissolve"
    events_on(ed, "festival")
    click_row(ed, row_of(ed, "Visit scene  stall"))
    ed.press(tree, "<Control-v>")
    assert [line(ed, MAIN, n) for n in (14, 15, 16)] == [
        "    # Mia arrives", "    scene bg room with dissolve", "    call stall"]

    pasted = main.get("1.0", "end-1c")
    click_row(ed, row_of(ed, "Narration  The lanterns were lit."))
    ed.press(tree, "<Control-x>")                        # copies and deletes
    assert ed.root.clipboard_get() == '"The lanterns were lit."'
    assert line(ed, MAIN, 13) == "    # Mia arrives"
    ed.press(tree, "<Control-z>")                        # one undo step
    assert main.get("1.0", "end-1c") == pasted


# --- Step 4: places, moving boxes, the layout file, Tidy up (AC-F46-22, 25, 27) -------------

def places(view) -> dict[str, tuple[int, int]]:
    return {b.name: (b.x, b.y) for b in view.layout.boxes}


def centre(ed, name: str) -> tuple[int, int]:
    """Box ``name``'s middle in window coordinates (scrolled into view first)."""
    view, canvas = ed.story_map, ed.map_canvas
    i = view.layout.index_of(name)
    view.see(i)
    ed.root.update()
    x0, y0, x1, y1 = canvas.coords(rect_item(view, name))
    return int((x0 + x1) / 2 - canvas.canvasx(0)), int((y0 + y1) / 2 - canvas.canvasy(0))


def drag(ed, name: str, by: tuple[float, float], *, shift: bool = False,
         release: bool = True) -> None:
    """A real drag of box ``name`` by ``by`` (100 % px) in three motions."""
    canvas, s = ed.map_canvas, ed.story_map._scale()
    x, y = centre(ed, name)
    dx, dy = round(by[0] * s), round(by[1] * s)
    take_focus(canvas)
    canvas.event_generate("<Button-1>", x=x, y=y)
    for f in (0.25, 0.6, 1.0):
        canvas.event_generate("<B1-Motion>", x=x + round(dx * f), y=y + round(dy * f))
        ed.root.update()
    if release:
        canvas.event_generate("<ButtonRelease-1>", x=x + dx, y=y + dy, state=1 if shift else 0)
        ed.root.update()


def test_ac_f46_25_moving_boxes(studio, lanterns, monkeypatch):
    ed = studio_l(studio, lanterns)
    view, canvas, history = ed.story_map, ed.map_canvas, ed.win.map_history
    cells = places(view)
    river = view.layout.index_of("river")
    x0, y0 = cells["river"]

    # During a drag only river's items, its edges and their chips change (spy).
    edges_in = {i for i, e in enumerate(view.layout.edges) if river in (e.src, e.dst)}
    items = {view.edge_item(i) for i in edges_in}
    chips = {c for i in edges_in for c in view.chip_items(i)}
    own = set(view.items_of("river"))
    touched: list[object] = []
    methods = ("move", "coords", "create_polygon", "create_text")
    for method in methods:
        real = getattr(canvas, method)

        def spy(*args, _real=real, _method=method, **kw):
            if _method.startswith("create"):
                touched.append("created")       # F58 I-8: chips ride along, never re-made
            elif _method == "move" or len(args) > 1:
                touched.append(args[0])
            return _real(*args, **kw)
        monkeypatch.setattr(canvas, method, spy)
    drag(ed, "river", (47, 13), release=False)
    allowed = {*own, view.ring, view._handle, *items, *chips}
    assert touched and set(touched) <= allowed
    assert {*own, *items} <= set(touched)
    for method in methods:
        monkeypatch.delattr(canvas, method)
    x, y = centre(ed, "river")
    canvas.event_generate("<ButtonRelease-1>", x=x, y=y)  # where the pointer now is
    ed.root.update()
    assert view.places["river"] == (x0 + 40, y0 + 20)    # snapped to 20 px
    assert len(history) == 1                             # one map step, and the first
    assert view.places == {**cells, "river": (x0 + 40, y0 + 20)}   # stores every box

    drag(ed, "river", (47, 13), shift=True)              # Shift: no snap
    assert view.places["river"] == (x0 + 87, y0 + 33) and len(history) == 2
    drag(ed, "river", (-(x0 + 300), 0))                  # past the left edge: x = 0
    assert view.places["river"][0] == 0 and len(history) == 3
    at = view.places["river"]
    assert view.focused == river
    ed.press(canvas, "<Alt-Right>")
    assert view.places["river"] == (at[0] + 20, at[1]) and len(history) == 4
    ed.press(canvas, "<Shift-Alt-Down>")
    at = (at[0] + 20, at[1] + 100)
    assert view.places["river"] == at and len(history) == 5

    rect = canvas.coords(rect_item(view, "river"))
    drag(ed, "river", (100, 60), release=False)          # Esc mid-drag: back, no step
    assert canvas.coords(rect_item(view, "river")) != rect
    ed.press(canvas, "<Escape>")
    assert canvas.coords(rect_item(view, "river")) == rect and view.drag is None
    assert view.places["river"] == at and len(history) == 5
    drag(ed, "river", (100, 60), release=False)          # focus lost mid-drag (G9): same
    take_focus(ed.tree)
    assert canvas.coords(rect_item(view, "river")) == rect and view.drag is None
    canvas.event_generate("<ButtonRelease-1>", x=5, y=5)
    ed.root.update()
    assert view.places["river"] == at and len(history) == 5

    view.focus_box(river)                                # Move box (G3)
    take_focus(canvas)
    view.start_move()
    for key in ("<Right>", "<Right>", "<Return>"):
        ed.press(canvas, key)
    assert view.places["river"] == (at[0] + 40, at[1]) and len(history) == 6
    at = view.places["river"]
    view.start_move()
    rect = canvas.coords(rect_item(view, "river"))
    ed.press(canvas, "<Right>")
    assert canvas.coords(rect_item(view, "river")) != rect and view.places["river"] == at
    ed.press(canvas, "<Escape>")                         # Esc in that mode restores it
    assert view.places["river"] == at and len(history) == 6 and view.moving is None
    assert places(view)["river"] == at and canvas.coords(rect_item(view, "river")) == rect
    assert not ed.win._side_open                         # no drag opened the side pane


def test_ac_f46_22_the_layout_file_in_studio(studio, lanterns, monkeypatch):
    assert layoutfile.LAYOUT_SAVE_MS == 1_000
    monkeypatch.setattr(layoutfile, "LAYOUT_SAVE_MS", 20)
    monkeypatch.setattr(livemap, "FOLLOW_MS", 20)
    path = lanterns / ".studio" / "storymap.json"
    assert not path.parent.exists()
    writes: list[bytes] = []
    write = layoutfile.write_layout
    monkeypatch.setattr(layoutfile, "write_layout",
                        lambda root, data: (writes.append(data), write(root, data))[1])
    ed = studio_l(studio, lanterns)
    view, canvas = ed.story_map, ed.map_canvas
    cells = places(view)

    view.focus_box(view.layout.index_of("river"))        # two moves within the delay
    ed.press(canvas, "<Alt-Right>")
    ed.press(canvas, "<Alt-Down>")
    assert not writes
    end = time.monotonic() + 5
    while not writes and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.005)
    end = time.monotonic() + 0.1
    while time.monotonic() < end:
        ed.root.update()
    river = (cells["river"][0] + 20, cells["river"][1] + 20)
    assert len(writes) == 1                              # one write, every shown box
    assert layoutfile.read_layout(lanterns) == {**cells, "river": river}
    assert not ed.root.title().startswith("* ") and not ed.win.dirty_files()
    assert not any(row.startswith("* ") for row in ed.rows())
    assert not any(ed.notebook.tab(t, "text").startswith("* ") for t in ed.notebook.tabs())

    ed.press(canvas, "<Alt-Right>")                      # move again, close: written
    ed.win.close()
    river = (river[0] + 20, river[1])
    assert len(writes) == 2
    stored = layoutfile.read_layout(lanterns)
    assert stored == {**cells, "river": river}

    fresh = studio_l(studio, lanterns)                   # a new window: the stored places
    assert places(fresh.story_map) == stored and fresh.story_map.message == ""
    fresh.win.close()
    assert len(writes) == 2                              # nothing moved: nothing written

    good = path.read_bytes()
    path.write_bytes(good.replace(b'"studio_map": 1', b'"studio_map": 2'))
    third = studio_l(studio, lanterns)                   # unreadable: automatic, one line
    assert places(third.story_map) == cells
    text = "The map layout file couldn't be read, so boxes were placed automatically."
    assert third.story_map.message == text and third.story_map.note.cget("text") == text
    third.win.close()

    path.write_bytes(good)
    fourth = studio_l(studio, lanterns)                  # `label river:` retyped as creek
    fourth.win.open_file(CH2)
    fourth.press(fourth.text, "<Control-Key-2>")
    widget = fourth.win.files[CH2].widget
    assert widget.get("11.0", "11.end") == "label river:"
    widget.delete("11.6", "11.11")
    widget.insert("11.6", "creek")
    end = time.monotonic() + 5
    while "creek" not in places(fourth.story_map) and time.monotonic() < end:
        fourth.root.update()
        time.sleep(0.005)
    shown = places(fourth.story_map)
    creek = shown.pop("creek")
    assert "creek" not in fourth.story_map.places and "river" not in shown
    assert storymap.place_free(shown.values(), creek) == creek   # a free spot (place_free)
    fourth.story_map.focus_box(fourth.story_map.layout.index_of("start"))
    fourth.press(fourth.map_canvas, "<Alt-Right>")       # the next write: creek, no river
    fourth.win.close()
    final = layoutfile.read_layout(lanterns)
    assert "creek" in final and "river" not in final


def test_ac_f46_27_tidy_up(studio, lanterns, monkeypatch):
    monkeypatch.setattr(layoutfile, "LAYOUT_SAVE_MS", 20)
    ed = studio_l(studio, lanterns)
    view, canvas, history = ed.story_map, ed.map_canvas, ed.win.map_history
    cells = places(view)
    view.focus_box(view.layout.index_of("river"))        # two moves
    ed.press(canvas, "<Alt-Right>")
    view.focus_box(view.layout.index_of("festival"))
    ed.press(canvas, "<Alt-Down>")
    moved = dict(view.places)
    assert moved["river"] != cells["river"] and moved["festival"] != cells["festival"]
    assert view.tidy_button.cget("text") == "Tidy up"
    view.tidy_button.invoke()                            # F45's column cells, one step
    assert places(view) == cells and view.places == {} and len(history) == 3
    ed.press(canvas, "<Control-z>")                      # one map Ctrl+Z restores both
    assert view.places == moved and places(view) == moved
    ed.press(canvas, "<Control-y>")
    assert places(view) == cells


# --- Step 5: arrows, choices and new scenes on the map; keys, menus, empty states ------------
# (AC-F46-32, 33, 36, 37). The planners are test_scriptedit.py's (AC-28-31, 34, 35).

BLANK = Path(__file__).resolve().parents[2] / "fixtures" / "F46" / "games" / "blank"


@pytest.fixture
def blank(tmp_path) -> Path:
    game = tmp_path / "blank"
    shutil.copytree(BLANK, game, ignore=shutil.ignore_patterns("expected_main.vns"))
    return game


def studio_n(studio, game: Path):
    ed = studio(game, mapped=True)
    result = CheckResult(problems=(), problem_total=0,
                         names={"label": (NameEntry("start", MAIN, 3),)}, links=(),
                         loaded=True, serial=ed.win.edit_serial, seconds=0.1)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    ed.press(ed.text, "<Control-Key-2>")
    return ed


def answer_new_scene(monkeypatch, names: list, seen: dict) -> None:
    """``formdialogs.ask_new_scene`` answered with the real dialog: each queued answer is
    (typed name, file shown) or None (Cancel)."""
    def ask(parent, files, default, *, taken=(), problem=None, new_file=None):
        dialog = formdialogs.NewSceneDialog(parent, files, default, taken=taken,
                                            problem=problem, new_file=new_file)
        seen.setdefault("defaults", []).append(dialog.file.get())
        answer = names.pop(0)
        if answer is None:
            dialog._pick(1)
            return dialog.result
        dialog.name.set(answer[0])
        seen.setdefault("hints", []).append(str(dialog.hint.cget("text")))
        dialog.file.set(answer[1])
        dialog._pick(0)
        return dialog.result
    monkeypatch.setattr(formdialogs, "ask_new_scene", ask)


def point(ed, name: str, *, handle: bool = False) -> tuple[int, int]:
    """Box ``name``'s middle (or its handle's) in window coordinates."""
    view, canvas = ed.story_map, ed.map_canvas
    i = view.layout.index_of(name)
    view.see(i)
    ed.root.update()
    x0, y0, x1, y1 = canvas.coords(rect_item(view, name))
    x = x1 - view.handle_px() / 2 if handle else (x0 + x1) / 2
    return int(x - canvas.canvasx(0)), int((y0 + y1) / 2 - canvas.canvasy(0))


def draw_arrow(ed, src: str, dst: str, *, release: bool = True) -> None:
    """A real drag from ``src``'s handle onto ``dst``."""
    canvas = ed.map_canvas
    take_focus(canvas)
    x, y = point(ed, src, handle=True)
    canvas.event_generate("<Motion>", x=x, y=y)
    canvas.event_generate("<Button-1>", x=x, y=y)
    tx, ty = point(ed, dst)
    for f in (0.3, 0.7, 1.0):
        canvas.event_generate("<B1-Motion>", x=x + round((tx - x) * f),
                              y=y + round((ty - y) * f))
        ed.root.update()
    if release:
        canvas.event_generate("<ButtonRelease-1>", x=tx, y=ty)
        ed.root.update()


def type_field(ed, text: str, key: str = "<Return>") -> None:
    field = ed.story_map.field
    assert field is not None
    field.entry.delete(0, "end")
    field.entry.insert(0, text)
    ed.press(field.entry, key)


def test_ac_f46_32_the_walkthrough(studio, blank, monkeypatch):
    picks, values, seen = [], [], {}
    answer_dialogs(monkeypatch, picks, values, seen)
    names: list = []
    answer_new_scene(monkeypatch, names, seen)
    ed = studio_n(studio, blank)
    view, canvas, events = ed.story_map, ed.map_canvas, ed.events_view
    assert [b.name for b in view.layout.boxes] == ["start"]

    # Double-click empty space: New scene "At the river" in main.vns, placed there.
    take_focus(canvas)
    x, y = 420, 260
    names.append(("At the river", "main.vns"))
    want = scriptedit.snap(view.map_point(x, y))
    for _ in range(2):
        canvas.event_generate("<Button-1>", x=x, y=y)
        canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
    ed.root.update()
    assert seen["hints"] == ["Its name in the script: at_the_river"]
    assert seen["defaults"] == ["main.vns"]
    river = view.layout.index_of("at_the_river")
    assert view.places["at_the_river"] == want
    assert ed.win._side_open and ed.current.ref == MAIN and ed.win.files[MAIN].dirty
    assert ed.side_text.get("sel.first", "sel.last") == scriptedit.PLACEHOLDER
    assert view.selected == river

    draw_arrow(ed, "start", "at_the_river")              # the handle: a "go to"
    assert line(ed, MAIN, 5) == "    jump at_the_river"
    assert edges(view) == {("start", "at_the_river", "jump")}

    names.append(("shrine", "main.vns"))                 # Ctrl+Shift+N: beside the selection
    ed.press(canvas, "<Control-Shift-N>")
    assert "shrine" in view.places and not ed.dialogs

    ed.answers.append(0)                                 # Make a choice
    draw_arrow(ed, "start", "shrine")
    assert ed.dialogs[-1][1:] == (
        "`start` already goes to `at_the_river`. Turn this into a choice?",
        ("Make a choice", "Cancel"), 1, 0)
    assert view.field is not None                        # the new arrow's text field
    assert view.selected_edge()[:3] == ("start", "shrine", "menu")
    type_field(ed, "Climb to the shrine")
    view.focus_box(view.layout.index_of("start"))
    take_focus(canvas)
    while view.selected_edge() is None or view.selected_edge()[1] != "at_the_river":
        ed.press(canvas, "<Tab>")
    ed.press(canvas, "<F2>")                             # F2 the other chip
    type_field(ed, "Walk to the river")

    click_box(ed, "at_the_river")
    ed.press(canvas, "<Control-e>")
    assert events.texts() == ["Narration  (Write what happens in this scene.)", "◆"]
    events.select(1)
    picks.append(("Stage", "Background"))
    values.append({"image": "bg river", "transition": "dissolve"})
    ed.press(events.tree, "<Return>")
    events.select(len(events.rows) - 1)
    picks.append(("Text", "Say"))
    values.append({"speaker": "hana", "look": "happy", "text": "You came!"})
    ed.press(events.tree, "<Return>")
    events.select(row_of(ed, "Background  bg river · dissolve"))
    ed.press(events.tree, "<Alt-Up>")
    assert events.texts()[0] == "Background  bg river · dissolve"
    ed.press(events.tree, "<Control-z>")
    assert events.texts()[1] == "Background  bg river · dissolve"
    ed.press(events.tree, "<Control-s>")
    assert (blank / MAIN).read_bytes() == (BLANK / "expected_main.vns").read_bytes()
    from tests.tools.f45_games import check
    assert check(blank).problem_total == 0


STORY_MENU = ["New scene", "Go to scene…", "Rename scene", "Delete scene", "Move box",
              "Delete arrow", "Edit choice text", "Change target…", "Tidy up",
              "Insert command…", "Edit command", "Move up", "Move down"]


def menu_entries(menu) -> list[tuple[str, str]]:
    """(label, state) of each command entry."""
    return [(str(menu.entrycget(i, "label")), str(menu.entrycget(i, "state")))
            for i in range(menu.index("end") + 1) if menu.type(i) == "command"]


def test_ac_f46_33_keys_and_menus(studio, lanterns, monkeypatch):
    patch_studio(monkeypatch, "CONTEXT_MENUS_POST", False)
    ed = studio_l(studio, lanterns)
    win, view, canvas, events = ed.win, ed.story_map, ed.map_canvas, ed.events_view
    menu = win.story_menu
    bar = win.menubar
    assert [bar.entrycget(i, "label") for i in range(bar.index("end") + 1)] == [
        "File", "Edit", "Insert", "Story", "View", "Run", "Help"]
    assert [label for label, _state in menu_entries(menu)] == STORY_MENU
    assert menu.entrycget("New scene", "accelerator") == "Ctrl+Shift+N"
    assert menu.entrycget("Go to scene…", "accelerator") == "Ctrl+J"

    # Each entry fires the handler its key fires (recorded).
    calls: list[tuple] = []
    with monkeypatch.context() as patch:
        for name in ("new_scene", "go_to_scene", "rename_scene", "delete_scene",
                     "move_box", "delete_arrow", "edit_choice_text", "change_target",
                     "tidy_up"):
            patch.setattr(window.EditorWindow, name,
                          lambda self, *a, n=name: calls.append((n, *a)))
        for name in ("insert", "edit", "move"):
            patch.setattr(window.StoryEditor, name,
                          lambda self, *a, n=name: calls.append((n, *a)))
        view.focus_box(view.layout.index_of("stall"))
        for entry, key, call in (("New scene", "<Control-Shift-N>", ("new_scene",)),
                                 ("Go to scene…", "<Control-j>", ("go_to_scene",)),
                                 ("Rename scene", "<F2>", ("rename_scene",)),
                                 ("Delete scene", "<Delete>", ("delete_scene",))):
            calls.clear()
            ed.press(canvas, key)
            assert calls == [call], key
            win._update_story_menu()
            calls.clear()
            menu.invoke(entry)
            assert calls == [call], entry
        calls.clear()
        win._update_story_menu()
        menu.invoke("Move box")
        assert calls == [("move_box",)]
        view.select_edge(view.edge_index("stall", "river", "menu"))
        for entry, key, call in (("Delete arrow", "<Delete>", ("delete_arrow",)),
                                 ("Edit choice text", "<F2>", ("edit_choice_text",))):
            calls.clear()
            ed.press(canvas, key)
            win._update_story_menu()
            menu.invoke(entry)
            assert calls == [call, call], entry
        calls.clear()
        win._update_story_menu()
        menu.invoke("Change target…")
        assert calls == [("change_target",)]
        view.select_edge(None)
        win._update_story_menu()                 # off: drawn dim, and does nothing
        assert not views.entry_enabled(menu, "Change target…")
        menu.invoke("Change target…")
        assert calls == [("change_target",)]
        view.places = {"stall": (0, 0)}
        calls.clear()
        win._update_story_menu()
        menu.invoke("Tidy up")
        assert calls == [("tidy_up",)]
        view.places = {}
        events_on(ed, "stall")
        click_row(ed, 1)
        for entry, key, call in (("Insert command…", "<Insert>", ("insert", 1)),
                                 ("Edit command", "<Return>", ("edit", 1)),
                                 ("Move up", "<Alt-Up>", ("move", 1, -1)),
                                 ("Move down", "<Alt-Down>", ("move", 1, 1))):
            calls.clear()
            ed.press(events.tree, key)
            win._update_story_menu()
            menu.invoke(entry)
            assert calls == [call, call], entry

    # Context menus: Button-3, Shift+F10 and the Menu key on a box, an arrow and a row.
    def shown() -> list[tuple[str, str]]:
        return menu_entries(win.last_context)
    x, y = point(ed, "festival")
    take_focus(canvas)
    canvas.event_generate("<Button-3>", x=x, y=y)
    ed.root.update()
    assert view.focused_name() == "festival"
    assert shown() == [("New scene", "normal"), ("Go to scene…", "normal"),
                       ("Rename scene", "normal"), ("Delete scene", "normal"),
                       ("Move box", "normal"), ("Play from this scene", "normal"),
                       ("Jump the game here",                  # F40: dimmed, no game
                        "normal" if views.MENU_DIM_ENTRIES else "disabled")]
    win.last_context = None
    ed.press(canvas, "<Shift-F10>")
    assert [label for label, _ in shown()][:2] == ["New scene", "Go to scene…"]
    view.select_edge(view.edge_index("stall", "river", "menu"))
    win.last_context = None
    ed.press(canvas, "<App>")
    assert shown() == [("Delete arrow", "normal"), ("Edit choice text", "normal"),
                       ("Change target…", "normal")]
    view.select_edge(view.edge_index("stall", "river", "jump"))
    ed.press(canvas, "<Shift-F10>")
    assert shown() == [("Delete arrow", "normal"),
                       ("Change target…", "normal")]           # no text on a "go to"
    win.last_context = None
    canvas.event_generate("<Button-3>", x=4, y=canvas.winfo_height() - 4)
    ed.root.update()
    assert [label for label, _ in shown()] == ["New scene here"]
    _x, ry, _w, rh, _b = events.tree.dlineinfo("1.0")
    events.tree.event_generate("<Button-3>", x=40, y=ry + rh // 2)
    ed.root.update()
    assert events.selected() == 0
    assert [label for label, _ in shown()] == [
        "Insert command…", "Edit command", "Move up", "Move down", "Delete command",
        "Play from this scene"]                          # F47 PR-F47-08

    # Tab on stall: its arrows in out_edges order; Enter: the target; Esc: back to stall.
    view.focus_box(view.layout.index_of("stall"))
    take_focus(canvas)
    order = storymap.out_edges(view.layout, view.layout.index_of("stall"))
    picked = []
    for _ in range(len(order) + 1):
        ed.press(canvas, "<Tab>")
        picked.append(view.edge)
    assert picked == [*order, order[0]] and view.focused_name() == "stall"
    ed.press(canvas, "<Return>")
    assert view.focused_name() == "river" and view.edge is None
    ed.press(canvas, "<Escape>")
    assert view.focused_name() == "stall"

    # Esc closes the inline field writing nothing.
    body = {ref: record.widget.get("1.0", "end-1c") for ref, record in win.files.items()}
    view.select_edge(view.edge_index("stall", "river", "menu"))
    ed.press(canvas, "<F2>")
    assert view.field is not None and view.field.entry.get() == "Buy the red one"
    type_field(ed, "Something else", "<Escape>")
    assert view.field is None and ed.focus() is canvas
    assert {ref: r.widget.get("1.0", "end-1c") for ref, r in win.files.items()} == body

    # Ctrl+J picking river writes what the drag writes.
    monkeypatch.setattr(formdialogs, "pick_scene", lambda parent, names, **kw: "river")
    view.focus_box(view.layout.index_of("festival"))
    ed.press(canvas, "<Control-j>")
    by_key = win.files[MAIN].widget.get("1.0", "end-1c")
    assert line(ed, MAIN, 15) == "    jump river"
    ed.press(canvas, "<Control-z>")
    assert line(ed, MAIN, 15) == "    return"
    draw_arrow(ed, "festival", "river")
    assert win.files[MAIN].widget.get("1.0", "end-1c") == by_key

    # In the Script text, Delete and Insert keep F44's behaviour (AC-F45-46).
    click_box(ed, "start")
    win.show_side_tab("script")
    side = ed.side_text
    side.mark_set("insert", "7.4")
    win.show_side_tab("script")
    ed.press(side, "<Delete>")
    assert side.get("7.0", "7.end") == "     Mia arrives"
    ed.press(side, "<Insert>")
    assert side.get("7.0", "7.end") == "     Mia arrives" and ed.focus() is side


def test_ac_f46_36_visual_roles_and_cues(studio, lanterns, monkeypatch):
    from engine.tools.editor import theme
    roles, pairs = theme.ROLES, {(fg, bg): low for fg, bg, low in theme.CONTRAST_PAIRS}
    assert THEME["map.selected"] == roles["accent"] and THEME["map.chip"] == roles["raised"]
    assert THEME["map.chipText"] == roles["muted"] == THEME["muted"]
    assert pairs[("map.selected", "editor.background")] >= 3      # accent on surface
    assert pairs[("map.selected", "map.box")] >= 3                # accent on raised
    assert pairs[("muted", "map.box")] >= 4.5                     # muted on raised
    for fg, bg, low in theme.CONTRAST_PAIRS:
        assert theme.contrast(THEME[fg], THEME[bg]) >= low, (fg, bg)
    ed = studio_l(studio, lanterns)
    view, canvas, events = ed.story_map, ed.map_canvas, ed.events_view
    accent = THEME["map.selected"]

    click_box(ed, "stall")                               # selected: 2 px accent
    assert canvas.itemcget(rect_item(view, "stall"), "outline") == accent
    assert float(canvas.itemcget(rect_item(view, "stall"), "width")) == 2
    draw_arrow(ed, "festival", "river", release=False)   # dashed accent line, accent target
    (dragline,) = canvas.find_withtag("linkline")
    assert canvas.itemcget(dragline, "fill") == accent and canvas.itemcget(dragline, "dash")
    assert canvas.itemcget(rect_item(view, "river"), "outline") == accent
    assert float(canvas.itemcget(rect_item(view, "river"), "width")) == 2
    ed.press(canvas, "<Escape>")
    assert not canvas.find_withtag("linkline") and view.link is None
    assert canvas.itemcget(rect_item(view, "river"), "outline") != accent

    menu = view.edge_index("stall", "river", "menu")     # a selected arrow: 2 px accent
    view.select_edge(menu)
    item = view.edge_item(menu)
    assert canvas.itemcget(item, "fill") == accent and float(canvas.itemcget(item, "width")) == 2
    assert ed.win.story_status.text == "Choice: Buy the red one"
    chip = chip_parts(view, menu)                        # chip: raised, small muted text
    assert canvas.itemcget(chip["box"], "fill") == THEME["map.chip"]
    assert canvas.itemcget(chip["text"], "fill") == THEME["muted"]
    assert view.chip_font.cget("size") == -12
    view.select_edge(view.edge_index("stall", "river", "jump"))
    assert canvas.itemcget(item, "fill") != accent and ed.win.story_status.text == ""

    events_on(ed, "stall")                               # Events: word muted, then text
    tree = events.tree
    assert tree.tag_cget("word", "foreground") == THEME["muted"]
    click_row(ed, 0)
    assert "chosenword" in tree.tag_names("1.0")
    assert tree.tag_cget("chosenword", "foreground") == THEME["foreground"]
    assert "chosenword" not in tree.tag_names("4.0")

    patch_studio(monkeypatch, "scale_of", lambda root: 1.5)   # 150 %
    big = studio_l(studio, lanterns)
    view, canvas = big.story_map, big.map_canvas
    assert view.dpi == 1.5 and view.handle_px() == 12
    i = view.layout.index_of("river")
    x, y = point(big, "river")
    canvas.event_generate("<Motion>", x=x, y=y)
    (handle,) = canvas.find_withtag("handle")
    x0, _y0, x1, _y1 = canvas.coords(handle)
    rect = canvas.coords(rect_item(view, "river"))
    assert round(rect[2] - x0) == 12
    place = (view.layout.boxes[i].x, view.layout.boxes[i].y)
    view.focus_box(i)
    big.press(canvas, "<Alt-Right>")
    assert view.places["river"] == (place[0] + 20, place[1])
    assert round(canvas.coords(rect_item(view, "river"))[0] - rect[0]) == 30


def test_ac_f46_37_empty_states(studio, blank, lanterns):
    ed = studio_n(studio, blank)
    view = ed.story_map
    assert view.start_only.shown and view.start_only.frame.winfo_ismapped()
    hint = view.start_only.hint.cget("text")
    assert hint == ("Double-click empty space to add a scene. Drag from one scene to another "
                    "to connect them.")
    assert view.start_only.title.cget("text") and view.start_only.button is not None
    assert not view.empty.shown                          # the start box stays usable
    events = ed.events_view
    ed.win.side_tab = "events"
    ed.win._show_side_pane()
    ed.win.show_side_tab("events")
    ed.root.update()
    assert events.empty.shown and events.empty.frame.winfo_ismapped()
    assert events.empty.hint.cget("text") == "Select a scene to see what happens in it."
    assert events.empty.title.cget("text")

    other = studio_l(studio, lanterns)                   # more than start: no note
    assert not other.story_map.start_only.shown
    events_on(other, "river")
    assert not other.events_view.empty.shown


# --- Step 6: rename, delete scene, change target, New file…, Preview from this scene --------

RENAME_TEXT = ("Rename `stall` to `lantern_stall`? 2 lines that go to it change too. Python "
               "code that names it doesn't. (2 places, first `ch2.vns`, line 14) Saves made "
               "inside this scene will start it from the beginning.")


def test_ac_f46_39_rename_in_studio(studio, lanterns, monkeypatch):
    seen: list = []

    def ask_text(parent, message, initial, *, ok, hint=None, **_kw):
        seen.append((message, initial, ok, hint("Lantern Stall")))
        return "Lantern Stall", True
    patch_studio(monkeypatch, "ask_text", ask_text)
    ed = studio_l(studio, lanterns)
    win, view, canvas = ed.win, ed.story_map, ed.map_canvas
    for ref in [ref for ref in win.files if ref != MAIN]:
        win.files.pop(ref)
    assert set(win.files) == {MAIN}
    original = {ref: (lanterns / ref).read_text(encoding="utf-8").rstrip()
                for ref in (MAIN, CH2)}
    before = places(view)
    view.focus_box(view.layout.index_of("stall"))
    ed.answers.append(0)                                         # Rename
    ed.press(canvas, "<F2>")
    assert seen == [("Rename the scene `stall`. Type its new name:", "stall", "Continue",
                     "Its name in the script: lantern_stall")]
    assert ed.dialogs == [("ask", RENAME_TEXT, ("Rename", "Cancel"), 1, 1)]
    assert CH2 in win.files and win.files[CH2].dirty and win.files[MAIN].dirty
    assert ed.row(MAIN).startswith("* ") and ed.row(CH2).startswith("* ")
    assert line(ed, MAIN, 14) == "    call lantern_stall"
    assert line(ed, CH2, 1) == "label lantern_stall:"
    assert line(ed, CH2, 16) == "    flowchart forget lantern_stall"
    assert line(ed, CH2, 14) == '    $ stall = "visited"'
    assert places(view)["lantern_stall"] == before["stall"]
    assert view.focused_name() == "lantern_stall"

    def texts() -> dict[str, str]:
        return {ref: win.files[ref].widget.get("1.0", "end-1c") for ref in (MAIN, CH2)}
    renamed = texts()
    ed.press(canvas, "<Control-z>")                              # one map undo: both
    assert texts() == original
    assert places(view)["stall"] == before["stall"] and "lantern_stall" not in places(view)

    view.focus_box(view.layout.index_of("stall"))                # again; text undo per file
    ed.answers.append(0)
    ed.press(canvas, "<F2>")
    assert texts() == renamed
    for ref in (MAIN, CH2):
        win.files[ref].widget.edit_undo()
        assert win.files[ref].widget.get("1.0", "end-1c") == original[ref], ref

    ed.dialogs.clear()                                           # start keeps its name
    view.focus_box(view.layout.index_of("start"))
    ed.press(canvas, "<F2>")
    assert ed.dialogs == [("error", "The story starts at `start`, so it keeps its name.")]


def test_ac_f46_41_change_target_in_studio(studio, lanterns, monkeypatch):
    offered: list = []
    monkeypatch.setattr(formdialogs, "pick_scene", lambda parent, names, **kw: (
        offered.append((list(names), kw)), "festival")[1])
    patch_studio(monkeypatch, "CONTEXT_MENUS_POST", False)
    ed = studio_l(studio, lanterns)
    win, view = ed.win, ed.story_map
    view.select_edge(view.edge_index("stall", "river", "jump"))
    win.context_menu("edge").invoke("Change target…")
    assert offered == [(["festival", "stall", "start"],
                        {"title": "Change target", "ok": "Change"})]
    assert line(ed, CH2, 9) == "    jump festival"
    assert view.selected_edge()[:3] == ("stall", "festival", "jump")
    ed.press(ed.map_canvas, "<Control-z>")
    assert line(ed, CH2, 9) == "    jump river"

    # Dragging the selected arrow's head onto another box does the same.
    view.select_edge(view.edge_index("stall", "river", "jump"))
    ed.root.update()
    canvas = ed.map_canvas
    item = view.edge_item(view.edge)
    hx, hy = canvas.coords(item)[-2:]
    x, y = int(hx - canvas.canvasx(0)), int(hy - canvas.canvasy(0))
    take_focus(canvas)
    canvas.event_generate("<Button-1>", x=x, y=y)
    tx, ty = point(ed, "festival")
    for f in (0.5, 1.0):
        canvas.event_generate("<B1-Motion>", x=x + round((tx - x) * f),
                              y=y + round((ty - y) * f))
        ed.root.update()
    canvas.event_generate("<ButtonRelease-1>", x=tx, y=ty)
    ed.root.update()
    assert line(ed, CH2, 9) == "    jump festival"


def test_ac_f46_42_new_file(studio, lanterns, monkeypatch):
    seen: dict = {}
    made: list = []

    def ask(parent, files, default, *, taken=(), problem=None, new_file=None):
        dialog = formdialogs.NewSceneDialog(parent, files, default, taken=taken,
                                            problem=problem, new_file=new_file)
        seen.setdefault("defaults", []).append(dialog.file.get())
        seen.setdefault("lists", []).append(list(dialog.files.cget("values")))
        if made:
            assert dialog.new_button is not None
            made.append(dialog.add_file())
            seen["chosen"] = dialog.file.get()
        dialog.name.set("shop front" if made else "lantern shop")
        dialog._pick(0)
        return dialog.result
    monkeypatch.setattr(formdialogs, "ask_new_scene", ask)
    ed = studio_l(studio, lanterns)
    win, view = ed.win, ed.story_map
    view.focus_box(view.layout.index_of("stall"))
    view.select_box(view.layout.index_of("stall"))
    win.new_scene()
    assert seen["defaults"] == ["ch2.vns"] and seen["lists"] == [["main.vns", "ch2.vns"]]
    assert line(ed, CH2, 19) == "label lantern_shop:"
    ed.press(ed.map_canvas, "<Control-z>")
    view.focus_box(None)
    view.select_box(None)
    made.append("go")
    ed.answers.append(("shop.vns", True))                       # F45's new script flow
    win.new_scene()
    assert seen["defaults"][-1] == "main.vns"
    assert made[-1] == "script/shop.vns" and seen["chosen"] == "shop.vns", ed.dialogs
    assert (lanterns / "script" / "shop.vns").exists()
    record = win.files["script/shop.vns"]
    assert "label shop_front:" in record.widget.get("1.0", "end-1c"), (ed.dialogs, seen)
    assert 'include "shop.vns"' in win.files[MAIN].widget.get("1.0", "end-1c")
    assert view.layout.index_of("shop_front") is not None


def test_ac_f46_43_play_from_this_scene(studio, lanterns, monkeypatch):
    patch_studio(monkeypatch, "CONTEXT_MENUS_POST", False)
    ed = studio_l(studio, lanterns)
    win, view = ed.win, ed.story_map
    started: list = []
    monkeypatch.setattr(win.runner, "start", lambda argv: started.append(list(argv)))
    monkeypatch.setattr(win.runner, "poll", lambda: [])
    view.focus_box(view.layout.index_of("river"))
    win.context_menu("box").invoke("Play from this scene")       # F47 PR-F47-08
    assert len(started) == 1
    argv = started[0]
    assert argv[argv.index("--start") + 1] == "river"


def test_arrows_and_wasd_scroll_the_map(studio, lanterns):
    """User feedback 2026-11-03: arrows and W A S D scroll the map (Shift: further);
    Ctrl+arrows go from box to box; Ctrl+S still saves with the map focused."""
    ed = studio_l(studio, lanterns)
    view, canvas = ed.story_map, ed.map_canvas
    canvas.configure(width=120, height=80)
    for _ in range(4):
        view.zoom_by(1)
    ed.root.update()
    take_focus(canvas)
    x0, y0 = canvas.xview()[0], canvas.yview()[0]
    ed.press(canvas, "<Right>")
    x1 = canvas.xview()[0]
    assert x1 > x0
    ed.press(canvas, "<Key-a>")
    assert canvas.xview()[0] < x1
    region = canvas.cget("scrollregion").split()
    canvas.configure(scrollregion=(0, 0, region[2], 4000))   # L is one row: make it tall
    ed.root.update()
    ed.press(canvas, "<Key-s>")
    y1 = canvas.yview()[0]
    assert y1 > y0
    ed.press(canvas, "<Key-S>")                          # Shift: five steps
    assert canvas.yview()[0] - y1 > 4 * (y1 - y0) - 1e-6
    ed.press(canvas, "<Key-w>")
    assert canvas.yview()[0] < canvas.yview()[1] and canvas.yview()[0] > y1

    saved: list[str] = []
    ed.win.save_current = lambda: saved.append("save")
    y2 = canvas.yview()[0]
    ed.press(canvas, "<Control-s>")
    assert saved == ["save"] and canvas.yview()[0] == y2

    view.focus_box(None)
    ed.press(canvas, "<Control-Right>")                  # the first box gets the focus
    first = view.focused
    assert first is not None
    ed.press(canvas, "<Control-Right>")
    assert view.focused is not None and view.focused != first
