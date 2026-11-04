"""Every Insert entry has its own name (no two "Lock"s), the Insert menu uses the same names
as Events ▸ Insert…, and an entry that shares a form opens it on its own kind."""

from collections import Counter

import pytest

from engine.tools.editor import formdialogs as fd
from engine.tools.editor import storyeditor
import engine.tools.editor.window  # noqa: F401  (registers every statement doc)
from engine.tools.editor.assist import insert_menu
from engine.tools.editor.forms import form_for_doc

tk = pytest.importorskip("tkinter")


def _entries():
    return [(group, entry) for group, entries in fd._with_form_entries(insert_menu())
            for entry in entries]


def test_no_two_entries_share_a_name():
    names = [fd._title(entry) for _group, entry in _entries()]
    assert [n for n, k in Counter(names).items() if k > 1] == []
    assert {"Forget a gallery picture", "Unlock a gallery picture", "Delete all saves",
            "Read a meta file", "Poem game"} <= set(names)
    # Forms only one entry opens keep their short names.
    assert {"Say", "Narration", "Music", "Stop music", "Stop sound", "Background",
            "Ask for a name…"} <= set(names)


def test_a_shared_form_opens_on_the_entrys_kind():
    docs = {fd.entry_title(e): e for _g, e in _entries() if not isinstance(e, fd.CommandForm)}
    for title, what in (("Unlock a gallery picture", "gallery"), ("Forget a scene replay", "replay"),
                        ("Give a tip or an item", "tip"), ("Unlock achievement", "achievement")):
        doc = docs[title]
        assert fd.new_values(form_for_doc(doc), doc)["what"] == what, title
    assert storyeditor._game_of(docs["Poem game"]) == "poem_game"
    assert storyeditor._game_of(docs["Minigame"]) is None


@pytest.mark.tk
def test_the_dialog_title_follows_the_pick():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        docs = {fd.entry_title(e): e for _g, e in _entries()
                if not isinstance(e, fd.CommandForm)}
        doc = docs["Unlock a gallery picture"]
        form = form_for_doc(doc)
        dialog = fd.FormDialog(root, form, fd.new_values(form, doc), names={})
        assert dialog.dialog.title() == "Unlock gallery picture"
        dialog.vars["what"].set("route")
        dialog.dialog.update()
        assert dialog.dialog.title() == "Unlock route"
        dialog.dialog.destroy()
    finally:
        root.destroy()
