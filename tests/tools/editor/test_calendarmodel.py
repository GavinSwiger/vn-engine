"""F63 round 2: ``calendarmodel``, the pure half of Game settings ▸ Calendar."""

from engine.tools.editor import calendarmodel as cm
from engine.tools.editor import settingsmodel as sm


def found(text: str):
    return sm.values(text)


def test_own_values_are_read_as_the_game_reads_them():
    own = cm.own(found('[calendar]\nparts = ["Day", "Night"]\nlast_day = "soon"\n'))
    assert own["parts"] == ("Day", "Night") and own["last_day"] is None    # refused: unset
    assert set(own) == set(cm.KEYS) and {"day_card", "place"} <= set(own)


def test_sources_wording_and_names():
    horror = found('[theme]\nkit = "horror"\n')
    assert cm.source(horror, "parts") == "From the Horror kit"
    assert cm.source(horror, "seasons") == cm.FROM_ENGINE                 # horror has none
    assert cm.source(found('[theme]\nkit = "cozy"\n'), "seasons") == "From the Cozy kit"
    assert cm.source(found(""), "parts") == cm.FROM_ENGINE
    assert cm.names_of(" Dusk ,, Small   hours, ") == ["Dusk", "Small hours"]
    assert cm.names_text(("Dusk", "Dawn")) == "Dusk, Dawn" and cm.names_text(None) == ""
    assert cm.check_names("parts", ["A", "B"]) and not cm.check_names("parts", ["A", "a"])
    assert cm.start_value(" 3 ") == 3 and cm.start_value("Monday  1 April") == "Monday 1 April"
    assert cm.start_value("") is None
    assert cm.fields_hint(cm.calendar(found(""))) == "Use {day}, {weekday} in curly brackets."


def test_preview_in_the_games_colors():
    seen = cm.preview(found('[theme]\nkit = "horror"\npreset = "amber"\n'))
    assert (seen.card, seen.date, seen.part, seen.place) == ("Night 2", "Night 1", "Dusk",
                                                             "top_right")
    assert (seen.card_fill, seen.card_text) == ("#140C02", "#FFB000")      # amber's roles
    assert seen.card_on and seen.colors[0] == "#140C02"
    plain = cm.preview(found('[calendar]\nday_card = false\nplace = "bottom_left"\n'
                             '[theme.chapter]\nfill_color = "#102030"\n'))
    assert not plain.card_on and plain.card_caption == cm.CARD_OFF
    assert plain.card_fill == "#102030" and plain.place == "bottom_left"
    assert "bottom left" in plain.corner_caption
    assert cm.problems(found('[calendar]\nstart = "Fooday 9"\n'))[0].startswith(
        'The start "Fooday 9"')
