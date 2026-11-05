"""F49 W1: Studio's Color scheme page (SPEC §4; AC-F49-11, 12).

One test per AC, on copies of the F47 sample game in ``tmp_path`` (its config.toml has no
``[theme]``). The helper child is a fake that records each still it is asked for."""

import time
from pathlib import Path

import pytest

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import files, helperhub
from engine.core.schemes import SCHEMES
from engine.tools.editor import schememodel as scm

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import settingsview  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


class FakeHelper:
    """Stands in for the helper child: records each still (kind, config bytes)."""

    def __init__(self, game_dir) -> None:
        self.stills: list[tuple[str, bytes]] = []
        self.serial = 0

    def still(self, kind, width, config):
        self.stills.append((kind, config))
        self.serial += 1
        return self.serial

    def thumb(self, ref, size, stamp=None):
        return None

    def play(self, ref):
        self.serial += 1
        return self.serial

    def stop_sound(self):
        return None

    def poll(self):
        return []

    def stop(self):
        pass


@pytest.fixture
def helper(monkeypatch):
    made: list[FakeHelper] = []

    def make(game_dir):
        made.append(FakeHelper(game_dir))
        return made[-1]

    monkeypatch.setattr(helperhub, "make_runner", make)
    return made


def sample_game(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    return game


def config_text(ed) -> str:
    return ed.win.files[CONFIG_REF].widget.get("1.0", "end-1c")


def edit_editor(ed, text: str) -> None:
    widget = ed.win.files[CONFIG_REF].widget
    widget.delete("1.0", "end-1c")
    widget.insert("1.0", text)
    ed.root.update()


def open_schemes(ed):
    ed.root.update()
    ed.win.show_tab(ed.win.tab_index("settings"))
    pane = ed.win.settings
    pane.select_page("schemes")
    ed.root.update()
    return pane


def drawn(cards, tag: str) -> list[tuple[str, str]]:
    """(card id, text) of the canvas texts tagged ``tag``."""
    canvas = cards.widget
    out = []
    for item in canvas.find_withtag(tag):
        card = next(t for t in canvas.gettags(item) if t.startswith("card:"))[5:]
        out.append((card, canvas.itemcget(item, "text")))
    return out


def press(ed, cards, key: str) -> None:
    cards.widget.focus_force()
    ed.root.update()
    cards.widget.event_generate(key)
    ed.root.update()


def wait(ed, pred, seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while not pred() and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.01)
    return pred()


def test_ac_f49_11_cards_select_preview_and_apply_one_undo_step(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    pane = open_schemes(ed)
    tree = pane.page_tree
    assert [tree.item(k, "text") for k in tree.get_children()][:2] == ["Game", "Color scheme"]
    assert pane.title_label.cget("text") == "Color scheme"
    cards = pane.scheme_cards
    assert [name for _id, name in drawn(cards, "name")] == [
        s.name for s in SCHEMES.values()]                       # 2026-11-05: 28 schemes
    assert drawn(cards, "in_use") == [("sakura", "In use")]          # no preset: Sakura
    assert str(pane.scheme_apply.cget("state")) == "disabled"        # Sakura is in use
    assert pane.scheme_note.winfo_manager() == "" and pane.scheme_unknown.winfo_manager() == ""
    original = config_text(ed)
    record = win.files[CONFIG_REF]

    # A click selects and asks for the preview_text still 0.5 s later; nothing is written.
    x0, y0, x1, y1 = cards.card_box(1)
    cards.widget.event_generate("<Button-1>", x=(x0 + x1) // 2, y=(y0 + y1) // 2)
    ed.root.update()
    assert pane.scheme_pick == "pocket" and cards.selected == "pocket"
    assert pane.scheme_apply.cget("text") == "Apply Pocket LCD"
    assert str(pane.scheme_apply.cget("state")) == "normal"
    assert wait(ed, lambda: helper and any(b'preset = "pocket"' in c
                                           for _k, c in helper[0].stills))
    fake = helper[0]
    kind, data = fake.stills[-1]
    assert kind == "textbox"
    shown = scm.preview_text(original, "pocket")
    assert data.decode("utf-8").rstrip() == shown.rstrip()
    assert config_text(ed) == original and not record.dirty

    # The arrow keys move the selection.
    press(ed, cards, "<Right>")
    assert pane.scheme_pick == "amber"
    press(ed, cards, "<Left>")
    assert pane.scheme_pick == "pocket"
    assert config_text(ed) == original

    # Enter applies: one preset line under a new [theme]; Ctrl+Z gives the text back exactly.
    press(ed, cards, "<Return>")
    applied = config_text(ed)
    assert applied.endswith('[theme]\npreset = "pocket"') and applied.startswith(original)
    assert drawn(pane.scheme_cards, "in_use") == [("pocket", "In use")]
    assert str(pane.scheme_apply.cget("state")) == "disabled"
    record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == original

    # Apply (the button) writes the picked one; a second Apply changes that one line.
    pane = open_schemes(ed)
    pane.scheme_cards.select("amber")
    pane.scheme_apply.invoke()
    ed.root.update()
    amber = config_text(ed)
    assert amber == scm.preview_text(original, "amber")              # what the still showed
    pane.scheme_cards.select("synthwave")
    pane.scheme_apply.invoke()
    ed.root.update()
    assert config_text(ed) == amber.replace('"amber"', '"synthwave"')
    assert config_text(ed).count("[theme]") == 1
    record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == amber
    assert "preset" not in (game / "config.toml").read_text(encoding="utf-8")  # unsaved


def test_ac_f49_12_custom_colors_note_clear_and_unknown_id(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    pane = open_schemes(ed)
    record = ed.win.files[CONFIG_REF]
    assert pane.scheme_note.winfo_manager() == ""                    # none set: no note

    custom = ('\n[theme.textbox]\nfill_color = "#FFFFFF"\n[theme.nvl]\ntext_color = "#101010"\n'
              '[theme.menu]\ndim_color = "#000000"\n')
    edit_editor(ed, config_text(ed) + custom)
    before = config_text(ed)
    pane = open_schemes(ed)
    assert pane.scheme_note.winfo_manager() == "pack"
    assert pane.scheme_note_body.cget("text") == (
        "2 colors you set yourself still show over the scheme.")
    assert pane.scheme_clear.cget("text") == "Clear my colors"

    # Cancel changes nothing.
    ed.answers.append(1)
    pane.scheme_clear.invoke()
    ed.root.update()
    assert ed.dialogs[-1] == ("ask", (
        "Remove the 2 colors you set yourself, so the scheme shows everywhere? Ctrl+Z in "
        "config.toml brings them back."), ("Remove", "Cancel"), 1, 0)
    assert config_text(ed) == before

    # Remove deletes both in one undo step; the neutral dim color stays.
    ed.answers.append(0)
    pane.scheme_clear.invoke()
    ed.root.update()
    cleared = config_text(ed)
    assert "#FFFFFF" not in cleared and "#101010" not in cleared
    assert 'dim_color = "#000000"' in cleared
    assert pane.scheme_note.winfo_manager() == ""
    record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == before

    # An id this version doesn't have: its text, and no card is in use.
    edit_editor(ed, config_text(ed) + '\n[theme]\npreset = "neon"\n')
    pane = open_schemes(ed)
    assert pane.scheme_unknown.winfo_manager() == "pack"
    assert pane.scheme_unknown_label.cget("text") == (
        "config.toml asks for a color scheme this version doesn't have (\"neon\"), so the "
        "default colors show. Pick one and press Apply.")
    assert drawn(pane.scheme_cards, "in_use") == []
    assert str(pane.scheme_apply.cget("state")) == "normal"          # Apply Sakura fixes it
    assert settingsview.INTRO["schemes"] == scm.INTRO


def test_import_palette_writes_your_palette_and_a_built_in_replaces_it(studio, tmp_path,
                                                                       helper, monkeypatch):
    """2026-11-05: Import palette… reads a pasted palette or a file, shows it on a sample,
    and writes ``[theme.scheme]`` as one undo step; a built-in card then removes it."""
    from engine.core.palette import derive_roles
    from engine.tools.editor import paletteimport as pi
    from tests.tools.editor.conftest import patch_studio
    patch_studio(monkeypatch, "PALETTE_MODAL", False)
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    pane = open_schemes(ed)
    record = ed.win.files[CONFIG_REF]
    original = config_text(ed)
    assert pane.scheme_import.cget("text") == "Import palette…"

    dialog = pi.open_palette_import(ed.root, pane.write_palette)
    assert dialog.status.cget("text") == pi.EMPTY and dialog.import_() is False
    dialog.set_text("nothing here")
    assert "No colors found" in dialog.status.cget("text")
    assert dialog.buttons[0].instate(["disabled"])
    # A file: its colors fill the box and its name the Name field.
    gpl = tmp_path / "dusk-harbor.gpl"
    gpl.write_text("GIMP Palette\nName: Dusk Harbor\n38 70 83\n42 157 143\n233 196 106\n"
                   "244 162 97\n231 111 81\n", encoding="utf-8")
    monkeypatch.setattr(pi, "ask_palette_file", lambda _parent: gpl)
    dialog.open_file()
    five = ("#264653", "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51")
    assert dialog.colors == five and dialog.name.get() == "Dusk Harbor"
    assert dialog.status.cget("text") == pi.FOUND.format(n=5)
    assert dialog.canvas.find_all()                                   # the sample is drawn
    dialog.way.set("Light")
    dialog.update()
    assert dialog.roles == derive_roles(five, False).roles
    assert dialog.import_() is True and not dialog.window.winfo_exists()
    ed.root.update()

    mine = config_text(ed)
    assert mine.startswith(original) and '[theme.scheme]\nname = "Dusk Harbor"\n' in mine
    assert f'accent = "{derive_roles(five, False).roles["accent"]}"' in mine
    cards = pane.scheme_cards
    assert cards.cards[0].id == scm.CUSTOM and cards.cards[0].name == "Dusk Harbor"
    assert drawn(cards, "in_use") == [(scm.CUSTOM, "In use")]
    assert str(pane.scheme_apply.cget("state")) == "disabled"
    # A built-in removes the palette (it would hide the scheme), as one undo step.
    pane.scheme_cards.select("gothic")
    pane.scheme_apply.invoke()
    ed.root.update()
    gothic = config_text(ed)
    assert 'preset = "gothic"' in gothic and "accent =" not in gothic
    assert pane.scheme_cards.cards[0].id == "sakura"
    record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == mine
    record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == original
