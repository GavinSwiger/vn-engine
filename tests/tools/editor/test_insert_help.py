"""Insert…: hovering an entry (or its muted reason) shows what it does and how it is
written; a group heading shows nothing."""

import pytest

from engine.tools.editor import formdialogs as fd
import engine.tools.editor.window  # noqa: F401  (registers every statement doc)
from engine.tools.editor.assist import insert_menu

tk = pytest.importorskip("tkinter")


@pytest.mark.tk
def test_every_entry_has_hover_help():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        picker = fd.InsertPicker(root, insert_menu())
        tree = picker.tree
        groups = tree.get_children("")
        assert picker.help_of(groups[0]) == ""
        for item, entry in picker.docs.items():
            assert picker.help_of(item), tree.item(item, "text")
        for reason, item in picker.reasons.items():
            assert picker.help_of(reason) == picker.help_of(item)
        first = next(iter(picker.docs))
        picker.tips.row = first
        picker.tips.show()
        assert picker.tips.window is not None
        picker.tips.hide()
        assert picker.tips.window is None
        picker.dialog.destroy()
    finally:
        root.destroy()
