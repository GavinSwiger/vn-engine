"""The mouse wheel scrolls whatever is under the pointer (``wheel``): a scrolled form over its
fields, a gutter's text, a text box holding an embedded card, and never a dropdown's value
inside a form."""

import pytest

from engine.tools.editor import wheel
from engine.tools.editor.fieldwidgets import ScrollFrame

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402


class Turn:
    """A wheel event at ``widget``'s middle (Windows: 120 per notch; down is negative)."""

    def __init__(self, widget, notches=-1):
        widget.update_idletasks()
        self.widget = widget
        self.x_root = widget.winfo_rootx() + max(1, widget.winfo_width() // 2)
        self.y_root = widget.winfo_rooty() + max(1, widget.winfo_height() // 2)
        self.delta = 120 * notches
        self.num = "??"


def test_units():
    event = type("E", (), {"delta": -120, "num": "??"})()
    assert wheel.units_of(event) == wheel.LINES_PER_NOTCH
    event.delta = 240
    assert wheel.units_of(event) == -2 * wheel.LINES_PER_NOTCH
    event.delta = 3                                       # macOS: small steps
    assert wheel.units_of(event) == -1
    assert wheel.units_of(type("E", (), {"num": 5, "delta": 0})()) == wheel.LINES_PER_NOTCH


@pytest.fixture()
def root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.geometry("400x300+40+40")
    wheel.install(root)
    yield root
    root.destroy()


@pytest.mark.tk
def test_a_form_scrolls_over_its_fields_and_dropdowns_keep_their_value(root):
    form = ScrollFrame(root)
    form.frame.pack(fill="both", expand=True)
    entries = [ttk.Entry(form.inner) for _ in range(40)]
    for entry in entries:
        entry.pack(fill="x", pady=4)
    combo = ttk.Combobox(form.inner, values=("a", "b", "c"), state="readonly")
    combo.current(0)
    combo.pack(before=entries[0])
    root.update()
    assert form.canvas.yview()[0] == 0.0
    assert wheel.route(Turn(entries[1])) == "break"
    root.update()
    assert form.canvas.yview()[0] > 0.0                  # over a field, the form moved
    before = form.canvas.yview()[0]
    form.canvas.yview_moveto(0)
    root.update()
    combo.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    root.update()
    assert combo.get() == "a"                            # the setting didn't change
    assert form.canvas.yview()[0] > 0.0                  # the form scrolled instead
    # Up at the top: nothing to do, and the turn isn't taken.
    form.canvas.yview_moveto(0)
    root.update()
    assert wheel.route(Turn(entries[1], notches=1)) is None
    assert before > 0


@pytest.mark.tk
def test_a_dropdown_outside_a_form_still_steps(root):
    combo = ttk.Combobox(root, values=("a", "b", "c"), state="readonly")
    combo.current(0)
    combo.pack()
    root.update()
    combo.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    assert combo.get() == "b"


@pytest.mark.tk
def test_text_with_an_embedded_card_and_a_gutter(root):
    text = tk.Text(root, height=5)
    text.pack(side="right", fill="both", expand=True)
    gutter = tk.Canvas(root, width=30)
    gutter.pack(side="left", fill="y")
    wheel.register(gutter, lambda units: text.yview_scroll(units, "units"))
    text.insert("1.0", "\n".join(f"line {n}" for n in range(200)))
    card = tk.Frame(text, width=100, height=40, background="red")
    text.window_create("1.0", window=card)
    root.update()
    assert wheel.route(Turn(card)) == "break"            # the card's text box scrolls
    root.update()
    first = text.yview()[0]
    assert first > 0
    assert wheel.route(Turn(gutter)) == "break"
    root.update()
    assert text.yview()[0] > first
    # A text box with room to scroll uses Tk's own binding (the route leaves it alone).
    assert wheel.route(Turn(text)) is None
