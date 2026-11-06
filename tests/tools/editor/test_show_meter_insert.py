"""F62 round 2: the engine's doc rows for ``show meter`` and ``hide meter`` put both in
Studio's Insert menu, each opening its form (``forms_meters``)."""

from engine.tools.editor.assist import help_for, insert_menu
from engine.tools.editor.forms import form_for_doc


def test_insert_menu_offers_show_and_hide_meter():
    docs = {doc.title: doc for _, entries in insert_menu() for doc in entries}
    show, hide = docs["Show a meter"], docs["Hide a meter"]
    assert show.syntax.startswith("show meter") and hide.syntax.startswith("hide meter")
    assert form_for_doc(show).key == "show_meter" and form_for_doc(hide).key == "hide_meter"
    # the sprite rows stay, with their own forms
    assert form_for_doc(docs["Show a sprite"]).key != "show_meter"
    assert help_for("    show meter hana") is show and help_for("hide meter a b") is hide
    assert help_for("show hana happy").title == "Show a sprite"
