"""F47 W4: Studio's Game settings tab (``01-design.md`` §4.4, §6.3; ``04-technical.md`` §3.2,
§7.2, §7.3; AC-F47-19, 20).

One test per AC, on copies of the F47 sample game (``engine/data/sample/`` via
``files.new_game``) in ``tmp_path``. AC-F47-19 is Tk only (no helper); AC-F47-20 runs the
real helper child (the look child), which Studio starts as its own process."""

import time
from pathlib import Path

import pytest

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import files, helperhub, settingsmodel, tomlpatch
from engine.tools.editor.dbmodel import EDIT_AS_SCRIPT

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import settingsview  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


def sample_game(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    return game


def open_settings(ed, page: str = "game"):
    ed.root.update()
    ed.win.show_tab(ed.win.tab_index("settings"))
    pane = ed.win.settings
    pane.select_page(page)
    ed.root.update()
    return pane


def config_text(ed) -> str:
    return ed.win.files[CONFIG_REF].widget.get("1.0", "end-1c")


def type_into(field, text: str) -> None:
    """Type ``text`` into an entry, spinbox or colour field and press Enter."""
    field.var.set(text)
    (field._typed if isinstance(field, settingsview.ColorField) else field._done)()


def edit_editor(ed, text: str) -> None:
    """Replace config.toml's whole text in the Editor, as typing would (one edit)."""
    widget = ed.win.files[CONFIG_REF].widget
    widget.delete("1.0", "end-1c")
    widget.insert("1.0", text)
    ed.root.update()


def test_ac_f47_19_broken_config_message_and_one_document_one_undo_history(
        studio, tmp_path):
    game = sample_game(tmp_path)
    on_disk = (game / "config.toml").read_bytes()
    ed = studio(game, mapped=True)
    win = ed.win
    pane = open_settings(ed)
    assert win.current_tab() == "settings" and win.notebook.tab(
        win.tab_index("settings"), "text") == "Game settings"
    title = pane.shown_fields["game.title"]
    assert title.widget.value == "my_game" and title.row.label.cget("text") == "Game title"
    assert "Default: Untitled Visual Novel" in title.row.hint.cget("text")

    # A field change edits the open config.toml: unsaved, one undo step, file untouched.
    type_into(title.widget, "Lantern Night")
    ed.root.update()
    record = win.files[CONFIG_REF]
    assert 'title = "Lantern Night"' in config_text(ed)
    assert record.dirty and (game / "config.toml").read_bytes() == on_disk
    assert str(title.row.default.cget("state")) == "normal"
    width = pane.shown_fields["window.width"]
    assert str(width.row.default.cget("state")) == "disabled"       # not set: the default
    type_into(width.widget, "1600")
    assert "[window]\nwidth = 1600" in config_text(ed)

    # The Editor shows the same text, and its undo takes back one change at a time.
    win.jump_to(CONFIG_REF, 1)
    assert win.current_tab() == "editor" and win.current is record
    record.widget.edit_undo()
    assert "width = 1600" not in config_text(ed)
    assert 'title = "Lantern Night"' in config_text(ed)
    record.widget.edit_undo()
    assert 'title = "my_game"' in config_text(ed)
    pane = open_settings(ed)
    assert pane.shown_fields["game.title"].widget.value == "my_game"
    assert str(pane.shown_fields["game.title"].row.default.cget("state")) == "normal"

    # Typing in the Editor (unsaved) shows in Settings; Use default removes the line.
    edit_editor(ed, config_text(ed) + "\n[textbox]\ncps = 90\n")
    pane = open_settings(ed, "textbox")
    cps = pane.shown_fields["textbox.cps"]
    assert cps.widget.value == 90
    assert cps.row.bar.cget("background") == settingsview.ROLES["accent"]   # changed bar
    pane.use_default(cps.field)
    ed.root.update()
    assert "cps = 90" not in config_text(ed) and "[textbox]" in config_text(ed)
    assert pane.shown_fields["textbox.cps"].widget.value == 40      # the default again
    record.widget.edit_undo()
    assert "cps = 90" in config_text(ed)

    # A key in an inline table is refused: the field says so and offers Edit as script.
    edit_editor(ed, config_text(ed) + '\n[theme]\ntextbox = { fill_color = "#000000" }\n')
    pane = open_settings(ed, "textbox")
    fill = pane.shown_fields["theme.textbox.fill_color"]
    assert fill.complex and fill.row.hint.cget("text") == tomlpatch.COMPLEX
    assert fill.row.default.cget("text") == EDIT_AS_SCRIPT
    fill.row.default.invoke()
    inline = config_text(ed).split("\n").index('textbox = { fill_color = "#000000" }') + 1
    assert win.current_tab() == "editor"
    assert record.widget.index("insert").split(".")[0] == str(inline)

    # A config.toml that doesn't parse: only the message and Open in Editor.
    edit_editor(ed, config_text(ed) + "\noops = \n")
    bad_line = config_text(ed).split("\n").index("oops = ") + 1
    pane = open_settings(ed)
    assert pane.state == "broken" and pane.empty.shown
    assert pane.empty.hint.cget("text") == settingsmodel.broken_message(bad_line) == (
        f"config.toml has a mistake on line {bad_line}, so these settings can't be shown. "
        "Fix it in the Editor.")
    assert pane.empty.button.cget("text") == "Open in Editor"
    assert win._tab_widget() is pane.empty.button                    # Ctrl+4 lands on it
    pane.empty.button.invoke()
    ed.root.update()
    assert win.current_tab() == "editor" and win.current is record
    assert record.widget.index("insert").split(".")[0] == str(bad_line)

    # Fixed in the Editor: the form is back.
    edit_editor(ed, config_text(ed).replace("\noops = \n", "\n"))
    pane = open_settings(ed)
    assert pane.state == "form" and not pane.empty.shown
    assert (game / "config.toml").read_bytes() == on_disk           # nothing was saved


def wait(ed, pred, seconds: float = 30.0) -> bool:
    end = time.monotonic() + seconds
    while not pred() and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.01)
    return pred()


def test_ac_f47_20_previews_come_from_the_look_child_with_unsaved_text(studio, tmp_path,
                                                                      request):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    hub = helperhub.hub_for(win)                     # the real helper child
    request.addfinalizer(hub.runner.stop)            # the fixture only destroys the root
    sent: list[tuple[float, str, bytes]] = []
    real_still = hub.runner.still

    def spy(kind, width, config):
        sent.append((time.monotonic(), kind, config))
        return real_still(kind, width, config)

    hub.runner.still = spy
    pane = open_settings(ed, "textbox")
    assert pane.status == settingsview.UPDATING
    assert wait(ed, lambda: pane.preview_image() is not None), pane.status
    assert pane.status == "" and [kind for _t, kind, _c in sent] == ["textbox"]
    first = pane.preview_image()
    first_data = first.cget("data") if first is not None else None

    # A change: "Updating preview…" at once, one still 0.5 s after it, from unsaved text.
    fill = pane.shown_fields["theme.textbox.fill_color"]
    changed_at = time.monotonic()
    type_into(fill.widget, "#203040")
    ed.root.update()
    assert pane.status == settingsview.UPDATING
    assert wait(ed, lambda: len(sent) == 2)
    at, kind, config = sent[1]
    assert kind == "textbox"
    assert settingsview.PREVIEW_DELAY_MS / 1000 - 0.02 <= at - changed_at \
        <= settingsview.PREVIEW_DELAY_MS / 1000 + 0.4
    assert b'fill_color = "#203040"' in config
    assert b"#203040" not in (game / "config.toml").read_bytes()    # unsaved
    assert wait(ed, lambda: pane.status == "" and pane.preview_image() is not first)
    assert pane.preview_image().cget("data") != first_data

    # Typing again before the 0.5 s are up sends one still, for the newest text.
    type_into(pane.shown_fields["theme.textbox.text_size"].widget, "40")
    ed.root.update()
    type_into(pane.shown_fields["theme.textbox.text_size"].widget, "44")
    assert wait(ed, lambda: len(sent) == 3)
    end = time.monotonic() + settingsview.PREVIEW_DELAY_MS / 1000 * 1.5
    while time.monotonic() < end:
        ed.root.update()
    assert len(sent) == 3 and b"text_size = 44" in sent[2][2]

    # Title screen: its own still.
    pane = open_settings(ed, "title")
    assert wait(ed, lambda: pane.preview_image() is not None and pane.status == "")
    assert sent[-1][1] == "title"

    # A failure shows the reason (here a value the game refuses, typed in the Editor).
    text = config_text(ed).replace('version = "0.1.0"', "version = 5")
    widget = win.files[CONFIG_REF].widget
    widget.delete("1.0", "end-1c")
    widget.insert("1.0", text)
    pane = open_settings(ed, "title")
    assert wait(ed, lambda: pane.status.startswith("Preview not available: "))
    assert "[game] version" in pane.status and pane.preview_image() is None
