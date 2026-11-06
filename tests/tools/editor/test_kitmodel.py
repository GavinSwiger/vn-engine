"""F60: the Kit page's model (``kitmodel``) and its Game settings field
(specs/F60-genre-kits/SPEC.md)."""

from engine.core.kits import KITS
from engine.core.schemes import SCHEMES
from engine.tools.editor import kitmodel as km
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor import tomlpatch
from engine.tools.editor.scriptedit import apply_lines


def plan(text: str, changes) -> str:
    found = tomlpatch.plan_changes(text, changes)
    return "\n".join(apply_lines(text.split("\n"), found.edits))


def test_cards_no_kit_first_then_each_kit_with_its_preview():
    shown = km.cards({})
    assert [c.id for c in shown] == ["", *KITS]
    assert [c.name for c in shown][:2] == ["No kit", "Romance"]
    plain = shown[0]
    assert (plain.look, plain.place, plain.label) == ("bar", "top_left", "")
    assert plain.colors[0] == SCHEMES["sakura"].colors["fill"]
    # "No kit" keeps the game's own colors: its preset, an imported palette over that.
    assert km.cards({"theme.preset": "noir"})[0].colors[0] == "#000000"
    assert km.cards({"theme.scheme.fill": "#123456"})[0].colors[0] == "#123456"
    horror = shown[2]
    assert (horror.look, horror.place, horror.label) == ("bar", "top_left", "Sanity")
    assert horror.colors[3] == SCHEMES["blood_moon"].colors["accent"]


def test_in_use_and_the_unknown_note():
    assert km.in_use({}) == km.NONE and km.unknown_text({}) is None
    assert km.in_use({"theme.kit": "cozy"}) == "cozy"
    assert km.in_use({"theme.kit": "western"}) is None
    assert "\x1b" not in km.unknown_text({"theme.kit": "a\x1bb"})    # through echo()
    assert km.unknown_text({"theme.kit": "western"}) == (
        'config.toml asks for a kit this version doesn\'t have ("western"), so the game '
        "uses no kit. Pick one and press Apply.")


def test_details_say_what_a_kit_sets():
    blurb, sets, suggests = km.details("romance")
    assert blurb == KITS["romance"].blurb
    assert sets == "Meters you show appear as hearts in the top-right corner."
    assert suggests.startswith("Suggested meters: Affection 0–10 (Stranger, Friend, Close)")
    assert km.details(km.NONE) == (km.NONE_BLURB, km.NONE_SETS)
    assert "Clues 0–20." in km.details("mystery")[2]          # no ranks: no brackets


def test_scheme_offer():
    assert km.scheme_offer(km.NONE, {}) is None
    offer = km.scheme_offer("fantasy", {})
    assert offer == km.SchemeOffer("Also use its color scheme (High Fantasy)", True, True)
    # Over an imported palette it starts unticked (a scheme would replace the palette).
    assert not km.scheme_offer("fantasy", {"theme.scheme.fill": "#123456"}).ticked
    used = km.scheme_offer("fantasy", {"theme.preset": "high_fantasy"})
    assert used == km.SchemeOffer("Its color scheme (High Fantasy) is already in use", True,
                                  False)


def test_apply_changes_one_plan():
    text = '[game]\ntitle = "x"\n'
    both = km.apply_changes("horror", True, {})
    assert both == (("theme", "kit", "horror"), ("theme", "preset", "blood_moon"))
    assert plan(text, both).endswith('[theme]\nkit = "horror"\npreset = "blood_moon"')
    assert km.apply_changes("horror", False, {}) == (("theme", "kit", "horror"),)
    # Only what differs; the kit in use with its scheme writes nothing.
    found = {"theme.kit": "horror", "theme.preset": "blood_moon"}
    assert km.apply_changes("horror", True, found) == ()
    assert km.apply_changes("horror", True, {"theme.kit": "horror"}) == (
        ("theme", "preset", "blood_moon"),)
    # No kit removes the line; an unknown id is replaced.
    assert km.apply_changes(km.NONE, True, {"theme.kit": "horror"}) == (
        ("theme", "kit", None),)
    assert km.apply_changes(km.NONE, True, {}) == ()
    assert km.apply_changes(km.NONE, True, {"theme.kit": "nope"}) == (("theme", "kit", None),)
    # Applying a scheme clears an imported palette, as the Color scheme page does.
    assert ("theme.scheme", "fill", None) in km.apply_changes(
        "cozy", True, {"theme.scheme.fill": "#123456"})
    assert km.apply_text("cozy") == "Apply Cozy" and km.apply_text(km.NONE) == "Use no kit"


def test_the_page_and_the_field():
    assert [p.key for p in sm.pages()][:3] == ["game", sm.SCHEMES, sm.KITS]
    assert sm.page(sm.KITS).title == "Kit" and sm.page(sm.KITS).preview == ""
    field = sm.fields_by_path()["theme.kit"]
    assert field.kind == "choice" and field.label == "Genre kit"
    assert field.widget.options == tuple(KITS)
    assert dict(field.widget.labels)["scifi"] == "Sci-fi"
    # Searching Game settings finds it.
    assert [f.path for s in sm.search("kit") for f in s.fields] == ["theme.kit"]
    assert "theme.kit" in [f.path for s in sm.search("genre") for f in s.fields]
