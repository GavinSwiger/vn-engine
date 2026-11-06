"""F47 W7: the Database's P2 categories and the Positions canvas (``01-design.md`` §4.3,
§6.4; ``04-technical.md`` W7; AC-F47-38, 40).

One test per AC, on copies of the F47 sample game (``files.new_game``) in ``tmp_path``. The
writers themselves are P2-D's (``test_declarations_p2.py``); these tests drive the tab the
way an author does: + New, ticking endings, Go to, dragging a marker."""

from pathlib import Path

import pytest

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import declplan, files

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import apply_check, open_database, text_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

DB_REF = declplan.DATABASE_REF
MAIN_REF = "script/main.vns"


def sample_game(tmp_path: Path) -> Path:
    """The sample story with a chapter line in each of its two scenes."""
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    main = game / "script" / "main.vns"
    text = main.read_text("utf-8").replace(
        "label start:\n", 'label start:\n    chapter one "Chapter 1" "Lanterns"\n', 1).replace(
        "label bridge:\n", 'label bridge:\n    chapter two "Chapter 2" "The Bridge"\n', 1)
    main.write_text(text, "utf-8")
    return game


def line_of(ed, ref: str, needle: str) -> int:
    return next(n for n, line in enumerate(text_of(ed, ref).split("\n"), start=1)
                if needle in line)


def button(frame, text: str):
    """The button labelled ``text`` anywhere under ``frame``."""
    stack = [frame]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if widget.winfo_class() == "TButton" and widget.cget("text") == text:
            return widget
    raise AssertionError(f"no {text!r} button")


def test_ac_f47_38_routes_edit_lock_route_until_and_endings_chapters_go_to(
        studio, tmp_path, monkeypatch):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    db = open_database(ed, "ending")
    assert [(r.iid, r.text) for r in db.visible_rows()] == [
        ("g:routes", "Routes"), ("g:endings", "Endings"),
        ("e:next_year", "Next Year, Maybe"), ("e:lantern", "Wishes on the Water")]

    # + New route: the scene it starts at, then its title (into database.vns).
    from engine.tools.editor import dbmore
    picked: list[list[str]] = []
    monkeypatch.setattr(dbmore, "pick_scene",
                        lambda parent, names, **kw: (picked.append(list(names)), "bridge")[1])
    ed.answers.append("The Bridge Route")
    assert db.new_route()
    assert "bridge" in picked[0] and "start" in picked[0]
    assert ed.dialogs[-1][:3] == ("text", "Title of the route, as players will see it:",
                                  "Bridge")
    assert 'lock route bridge "The Bridge Route"\n' in text_of(ed, DB_REF) + "\n"
    assert db.selected_row().iid == "r:bridge"

    # The multi-pick of endings writes until, in the order ticked; unticking removes one.
    until = db.form.fields["until"]
    assert list(until) == ["lantern", "next_year"]
    until["lantern"].check.invoke()
    assert 'lock route bridge "The Bridge Route" until lantern' in text_of(ed, DB_REF)
    db.form.fields["until"]["next_year"].check.invoke()
    assert 'until lantern, next_year' in text_of(ed, DB_REF)
    db.form.fields["until"]["lantern"].check.invoke()
    assert 'lock route bridge "The Bridge Route" until next_year' in text_of(ed, DB_REF)
    title = db.form.fields["title"]
    title.var.set("True Route")
    title._done()
    assert 'lock route bridge "True Route" until next_year' in text_of(ed, DB_REF)
    assert ed.win.files[DB_REF].widget.edit("canundo")

    # Endings: read-only, each with Go to its ending line; "used" by the waiting route.
    assert ed.win.save_record(ed.win.files[DB_REF])
    apply_check(ed, game)
    db.select("e:next_year")
    assert db.selected_row().detail == "1 route"
    assert db.form.fields == {}                                 # nothing to edit
    button(db.body, "Go to").invoke()
    ed.root.update()
    assert ed.win.current_tab() == "editor"
    widget = ed.win.files[MAIN_REF].widget
    assert widget.index("insert").split(".")[0] == str(line_of(ed, MAIN_REF,
                                                                "ending next_year"))

    # Chapters: read-only, in story order, with Go to and ▶ Play its scene; no + New.
    db = open_database(ed, "chapter")
    assert [(r.iid, r.text) for r in db.visible_rows()] == [("h:one", "Lanterns"),
                                                             ("h:two", "The Bridge")]
    assert db.counts()["chapter"] == 2
    assert not db.new_button.winfo_ismapped()
    db.select("h:two")
    played: list = []
    monkeypatch.setattr(ed.win, "play", lambda label: played.append(label))
    button(db.body, "▶ Play its scene").invoke()
    assert played == ["bridge"]
    button(db.body, "Go to").invoke()
    ed.root.update()
    assert widget.index("insert").split(".")[0] == str(line_of(ed, MAIN_REF, "chapter two"))

    # W7's Variables field: "Remembered across playthroughs" swaps default ↔ persistent.
    db = open_database(ed, "variable")
    db.select("v:sent_lantern")
    db.form.fields["remembered"].check.invoke()
    assert "default persistent.sent_lantern = False" in text_of(ed, DB_REF)
    assert db.selected_row().iid == "pv:sent_lantern"
    assert db.selected_row().detail == "Remembered"
    db.form.fields["remembered"].check.invoke()
    assert "default sent_lantern = False" in text_of(ed, DB_REF)


def test_ac_f47_40_positions_canvas_drags_markers_and_writes_stage_positions(
        studio, tmp_path):
    game = files.new_game(tmp_path / "my_game")
    ed = studio(game, mapped=True)
    db = open_database(ed, "position")
    assert [r.text for r in db.visible_rows()] == ["left", "center", "right"]
    assert [r.detail for r in db.visible_rows()] == ["Built-in"] * 3
    db.select("o:left")
    ed.root.update()
    stage = db.stage
    assert stage.points == {"left": (320.0, 720.0), "center": (640.0, 720.0),
                            "right": (960.0, 720.0)}

    def drag(name: str, to: tuple[float, float]) -> tuple[float, float]:
        """Press on ``name``'s marker, move, and drop at stage point ``to``."""
        start = stage.to_canvas(*stage.points[name])
        end = stage.to_canvas(*to)
        canvas = stage.canvas
        before = config()
        canvas.event_generate("<ButtonPress-1>", x=round(start[0]), y=round(start[1]))
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        canvas.event_generate("<B1-Motion>", x=round(mid[0]), y=round(mid[1]))
        assert db.stage.dragging == name                        # mid-drag: nothing written
        assert config() == before
        canvas.event_generate("<B1-Motion>", x=round(end[0]), y=round(end[1]))
        canvas.event_generate("<ButtonRelease-1>", x=round(end[0]), y=round(end[1]))
        ed.root.update()
        return stage.to_stage(round(end[0]), round(end[1]))

    def config() -> str:
        return ed.win.record_for(CONFIG_REF).widget.get("1.0", "end-1c")

    # A drop in the middle writes [x, y]; the row says "Moved" and Use default is enabled.
    x, y = drag("left", (400, 360))
    assert y < 700
    assert f"[stage.positions]\nleft = [{int(x)}, {int(y)}]" in config()
    assert db.selected_row().detail == "Moved"
    assert db.stage.points["left"] == (x, y)
    assert db.form.fields["x"].value == x and db.form.fields["y"].value == y
    assert not ed.win.files[CONFIG_REF].dirty                   # saved at once (first-game fix)
    assert (game / CONFIG_REF).read_text("utf-8").rstrip("\n") == config().rstrip("\n")

    # A drop on the floor writes x alone (y 720 is the bottom edge).
    x, y = drag("left", (300, 715))
    assert y == 720
    assert f"left = {int(x)}\n" in config() + "\n"

    # Typing a number moves it too; Use default takes the line out again.
    db.form.fields["x"].var.set("250")
    db.form.fields["x"]._done()
    assert "left = 250\n" in config() + "\n"
    button(db.body, "Use default").invoke()
    assert "left =" not in config()
    assert db.selected_row().detail == "Built-in"

    # + New position (at the middle of the floor), drag it, then Delete it.
    ed.answers.append("Far left")
    db.new_entry()
    assert "far_left = 640" in config()
    assert db.selected_row().iid == "o:far_left"
    x, y = drag("far_left", (120, 720))
    assert f"far_left = {int(x)}" in config()
    ed.answers.append(0)                                        # Delete
    button(db.body, "Delete").invoke()
    assert "far_left" not in config()
    assert [r.text for r in db.visible_rows()] == ["left", "center", "right"]
