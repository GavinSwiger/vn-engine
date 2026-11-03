"""F47 P1-C: the check's usage rows (``variable``, ``character_use``, ``image_use``,
``audio_use``, ``variable_use``) and the Database's "Used in N lines" and Delete refusal
(``dbmodel``; AC-F47-15). The check runs in process, through the wire, without launch."""

from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from tests.tools.f45_games import check, studio

MAIN = """\
include "ch2.vns"
define hana = Character("Hana", blip="bgm/theme.ogg")
define rin = Character(name_from="rin_name")
define kai = Character("Kai")
image bg dusk = "#203040"
default trust = 0
default rin_name = "???"
default unused = False
label start:
    scene bg dusk
    show hana happy
    hana "Hi, {var=rin_name}."
    hana happy "Again."  # one line, two uses: counted once
    $ trust += 1
    if trust > 0 and hana:
        rin "Trust is {var=trust}."
    menu:
        "Play" if trust > 1:
            play music "bgm/theme.ogg"
        "Stop":
            scene bg room
    call club
    jump bridge
"""


def test_ac15_used_in_counts_and_delete_refusal(tmp_path):
    """AC-F47-15: Used-in counts match the check's references (distinct lines); Delete is
    refused with §6.4's text while used, and allowed when unused."""
    game = studio(tmp_path)
    (game / "script" / "main.vns").write_text(MAIN, encoding="utf-8")
    result = check(game, launch=False)
    names = result.names
    assert result.loaded and not [p for p in result.problems if p.severity == "error"]
    assert [(e.name, e.file, e.line) for e in names["variable"]] == [
        ("trust", "script/main.vns", 6), ("rin_name", "script/main.vns", 7),
        ("unused", "script/main.vns", 8)]
    assert db.use_places(names, dec.CHARACTER, "hana") == (
        ("script/main.vns", 12), ("script/main.vns", 13), ("script/main.vns", 15))
    assert db.use_places(names, dec.VARIABLE, "trust") == (
        ("script/main.vns", 14), ("script/main.vns", 15), ("script/main.vns", 16),
        ("script/main.vns", 18))
    assert db.use_places(names, dec.VARIABLE, "rin_name") == (
        ("script/main.vns", 3), ("script/main.vns", 12))
    assert db.use_places(names, db.SOUND, "bgm/theme.ogg") == (
        ("script/main.vns", 2), ("script/main.vns", 19))
    assert db.uses_of(names, db.BACKGROUND, "BG Room") == 1                # any case
    texts = {"script/main.vns": MAIN}
    decls = dec.scan(texts)
    chars = {e.name: e for e in db.character_entries(decls, names)}
    assert {n: e.uses for n, e in chars.items()} == {"hana": 3, "rin": 1, "kai": 0}
    assert [e.shown for e in db.character_entries(decls, names)] == ["Hana", "Kai", "rin"]
    assert chars["hana"].used_text == "Used in 3 lines"
    assert chars["rin"].used_text == "Used in 1 line"
    assert chars["kai"].used_text == "Not used yet" and chars["kai"].name_editable
    assert db.delete_refusal(chars["hana"]) == (
        "Hana is used in 3 lines, so it can't be deleted yet.")
    assert db.delete_refusal(chars["kai"]) is None
    variables = {e.name: e.uses for e in db.variable_entries(decls, names)}
    assert variables == {"rin_name": 2, "trust": 4, "unused": 0}
    backgrounds = {e.name: (e.kind, e.uses) for e in db.background_entries(decls, names)}
    assert backgrounds["bg dusk"] == (dec.COLOR, 1)
    assert backgrounds["bg room"] == (db.BACKGROUND, 1)
    assert db.looks_of("hana", names) == ("happy",)
    assert [e.name for e in db.sound_entries(names)[db.OTHER_SOUNDS]] == ["bgm/theme.ogg"]
