"""F62 round 2 in Studio: Database ▸ Meters' ready-made meters (+ New), the On screen
fields that write ``[meter.<name>]`` in config.toml, and the live preview
(specs/F62-visible-meters/SPEC.md §7)."""

from pathlib import Path

import pytest

from engine.core.kits import KITS
from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, files, tomlpatch
from engine.tools.editor import metermodel as mm
from engine.tools.editor.scriptedit import Refuse, apply_lines

DB_REF = declplan.DATABASE_REF


def test_offers_come_from_the_kit_or_a_short_general_list():
    general, kit = mm.offers({})
    assert kit is None and [o.label for o in general] == ["Affection", "Trust", "Courage",
                                                          "Coins"]
    horror, kit = mm.offers({"theme.kit": "horror"})
    assert kit is KITS["horror"] and horror[0].label == "Sanity"
    assert mm.offers({"theme.kit": "nope"})[1] is None
    sanity = horror[0]
    line = dec.meter_line((sanity.name,), mm.offer_values(sanity))
    assert line == ('points sanity 0 to 100 start 100 ranks "Breaking" 0 "Shaken" 25 '
                    '"Uneasy" 50 "Steady" 75')
    assert dec.meter_read(line)[1] is not None
    for offer in (*general, *(o for k in KITS.values() for o in k.meters.suggestions)):
        dec.meter_line((offer.name,), mm.offer_values(offer))        # every preset writes
    assert mm.offer_text(sanity).startswith("Sanity  ·  0 to 100, starts at 100  ·  Breaking")
    assert mm.offer_text(sanity, taken=True) == "Sanity (already in your game)"


def test_defaults_own_values_and_preview():
    romance = {"theme.kit": "romance"}
    assert mm.default_text(romance, "affection") == "Kit default: hearts, top right"
    assert mm.default_text({}, "hana_love") == "Default: bar, top left"
    assert mm.label_text(romance, "affection") == "Empty: shows “Affection”."
    own = {**romance, "meter.affection.look": "dial", "meter.affection.place": "nowhere",
           "meter.affection.label": "Love"}
    assert mm.own(own, "affection") == {"look": "dial", "place": None, "label": "Love"}
    assert mm.shown(own, "affection") == ("dial", "top_right", "Love")
    values = {"low": 0, "high": 10, "start": None,
              "ranks": (("Stranger", 0), ("Friend", 4), ("Close", 8))}
    seen = mm.preview(own, "affection", values)
    assert (seen.look, seen.place, seen.label) == ("dial", "top_right", "Love")
    assert (seen.number, seen.of, seen.rank) == ("6", "/ 10", "Friend")
    assert seen.caption == "Shown at 6 of 10 · Friend"
    assert mm.preview({}, "x", {"low": None, "high": None}).caption == "Shown at 6"
    assert mm.look_changes("hana", "label", "  ") == (("meter.hana", "label", None),)


def _apply(text: str, changes) -> str:
    plan = tomlpatch.plan_changes(text, changes, drop_empty=True)
    assert isinstance(plan, tomlpatch.TomlPlan) and tomlpatch.verify(plan, text)
    return "\n".join(apply_lines(text.split("\n"), plan.edits))


def test_clearing_the_last_key_takes_its_table():
    text = '[game]\ntitle = "x"\n\n[meter.sanity]\nlook = "hearts"'
    added = _apply(text, mm.look_changes("sanity", "place", "top_right"))
    assert added == text + '\nplace = "top_right"'
    assert _apply(added, mm.look_changes("sanity", "look", None)) == (
        '[game]\ntitle = "x"\n\n[meter.sanity]\nplace = "top_right"')
    assert _apply(text, mm.look_changes("sanity", "look", None)) == '[game]\ntitle = "x"'
    first = '[meter.hana]\nlabel = "Hana"\n\n[game]\ntitle = "x"'
    assert _apply(first, mm.look_changes("hana", "label", "")) == '[game]\ntitle = "x"'
    kept = '[meter.hana]\n# my note\nlabel = "Hana"'
    assert _apply(kept, mm.look_changes("hana", "label", None)) == "[meter.hana]\n# my note"
    plain = tomlpatch.plan_remove(text, "meter.sanity", "look")      # without drop_empty
    assert isinstance(plain, tomlpatch.TomlPlan) and plain.edits[0].first == 5
    assert isinstance(tomlpatch.plan_set(text, "meter.sanity", "look", "spiral"), Refuse)


tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import open_database, text_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401


def _labels(menu) -> list[tuple[str, str]]:
    return [(menu.entrycget(i, "label"), menu.entrycget(i, "state"))
            for i in range(menu.index("end") + 1) if menu.type(i) == "command"]


def _tags(canvas) -> set[str]:
    return {t for item in canvas.find_all() for t in canvas.gettags(item)}


@pytest.mark.tk
def test_new_meter_menu_offers_ready_made_meters(studio, tmp_path):
    game = files.new_game(tmp_path / "plain")
    assert isinstance(game, Path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "meter")
    menu = db.meter_menu()
    labels = _labels(menu)
    assert [label.split("  ")[0] for label, _ in labels] == [
        "Affection", "Trust", "Courage", "Coins", "Blank meter…", mm.KIT_HINT + " ›"]
    menu.invoke(0)                                                    # Affection
    ed.root.update()
    assert text_of(ed, DB_REF).endswith(
        'points affection 0 to 10 ranks "Stranger" 0 "Friend" 4 "Close" 8')
    assert db.selected_row().iid == "m:affection"
    assert _labels(db.meter_menu())[0] == ("Affection (already in your game)", "disabled")
    db.meter_menu().invoke(7)                                         # the Kit page
    ed.root.update()
    assert ed.win.settings.title_label.cget("text") == "Kit"


@pytest.mark.tk
def test_on_screen_fields_write_config_and_redraw_the_preview(studio, tmp_path):
    game = files.new_game(tmp_path / "scary")
    assert isinstance(game, Path)
    config = game / CONFIG_REF
    config.write_text(config.read_text("utf-8").rstrip("\n") + '\n\n[theme]\nkit = "horror"\n',
                      "utf-8")
    ed = studio(game, mapped=True)
    db = open_database(ed, "meter")
    menu = db.meter_menu()
    assert _labels(menu)[0] == ("Suggested by the Horror kit", "disabled")
    menu.invoke(1)                                                    # Sanity
    ed.root.update()
    f = db.form.fields
    assert f["look"].box.get() == "Bar (default)" and f["corner"].value is None
    assert {"look:bar", "place:top_left", "rank"} <= _tags(f["preview"])
    assert f["preview_caption"].cget("text") == "Shown at 60 of 100 · Uneasy"
    original = ed.win.record_for(CONFIG_REF).widget.get("1.0", "end-1c")

    f["look"].pick("hearts")
    ed.root.update()
    f = db.form.fields
    assert text_of(ed, CONFIG_REF) == original + '\n\n[meter.sanity]\nlook = "hearts"'
    assert "look:hearts" in _tags(f["preview"])
    f["corner"].pick("bottom_right")
    f["label"].var.set("Mind")
    f["label"]._done()
    ed.root.update()
    f = db.form.fields
    assert text_of(ed, CONFIG_REF).endswith(
        '[meter.sanity]\nlook = "hearts"\nplace = "bottom_right"\nlabel = "Mind"')
    assert {"place:bottom_right", "look:hearts"} <= _tags(f["preview"])
    assert "Mind" in {f["preview"].itemcget(i, "text") for i in
                      f["preview"].find_withtag("label")}
    # One undo step per change.
    ed.win.files[CONFIG_REF].widget.edit_undo()
    assert text_of(ed, CONFIG_REF).endswith('place = "bottom_right"')
    db.refresh(select="m:sanity")
    ed.root.update()
    f = db.form.fields
    assert f["label"].var.get() == ""
    # Clearing every key takes the table with it.
    f["look"].pick(None)
    db.form.fields["corner"].pick(None)
    ed.root.update()
    assert text_of(ed, CONFIG_REF) == original
    assert db.form.fields["corner"].value is None
