"""Codex completion gaps (2026-11-02, user: keep Studio updated; ``06`` AC-F45-67..69):
picture names after ``image`` in a ``lock tip|item`` declaration, tip and item names in a
Python string, and ``codex.`` fields."""

import engine.script  # noqa: F401  (registers the statement docs)
from engine.tools.editor.assist import auto_open, candidates, completion_context

NAMES = {"image": [("hana happy", None, None), ("key brass", None, None)],
         "tip": [("river_god", None, None), ("lanterns", None, None)],
         "item": [("brass_key", None, None)]}


def offered(line, column=None):
    ctx = completion_context(line, len(line) if column is None else column)
    return None if ctx is None else [(c.text, c.kind) for c in candidates(ctx, NAMES)]


def test_ac67_picture_names_after_image_in_a_codex_declaration():
    assert offered('lock item brass_key "Brass Key" image ke') == [("key brass", "image")]
    assert offered('lock item brass_key "Brass Key" image key b') == [("key brass", "image")]
    assert offered('lock tip x "An image of" ') == [("lanterns", "tip"), ("river_god", "tip")]
    assert auto_open('lock item k "K" image ', 22)


def test_ac68_tip_and_item_names_in_python_strings():
    assert offered('$ seen = "ri" in codex.tips', 11) == [("river_god", "tip")]
    assert offered('if "b" in codex.items:', 5) == [("brass_key", "item")]
    assert offered('if "b" in items.held:', 5) == [("brass_key", "item")]
    assert offered('$ x = "l') == [("lanterns", "tip")]              # either kind
    assert offered('    "Take the boat" if "ri" in codex.tips:', 26) == [("river_god", "tip")]
    assert offered('    hana "ri') is None                          # dialogue: no names


def test_ac69_codex_dot_offers_its_fields():
    assert offered("$ n = len(codex.") == [("tips", "codex")]
    assert offered("if codex.ti") == [("tips", "codex")]
    assert auto_open("$ x = codex.", 12) and not auto_open("$ x = mycodex.", 14)
