"""Game settings ▸ Calendar, the pure half (F63 round 2; specs/F63-story-clock/SPEC.md).

Why this module exists: story time (``clock next``, ``show clock``, the day card) reads its
names and wording from ``[calendar]`` in config.toml, then the kit, then the defaults
(``storyclock.calendar_of``). The Calendar page lets an author set them without TOML and see
the result at once. This module reads the open text's values (``settingsmodel.values``)
into what the page shows, and turns an edit into ``tomlpatch`` changes; ``calendarpage``
holds the widgets.

- ``own(found)``: each ``[calendar]`` key the file sets, validated as the game would read it
  (None: not set, or a value the game would refuse).
- ``calendar(found)``: the calendar the game will use (``[calendar]`` > kit > defaults), and
  ``problems(found)``: what the game warns about at load (W301), in words.
- ``source(found, key)``: where an unset key's value comes from ("the Horror kit").
- ``names_text`` / ``names_of``: a name list as one line ("Dusk, Midnight") and back.
- ``preview(found)``: what the live preview draws: the day card (the day after the start,
  in the chapter card's colors) and the corner readout (date over part, in the corner).

Pure Python: ``core``, ``script`` and its own package; no Tk (ADR-0008).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Final

from engine.core.config_schema import CalendarConfig, ValueProblem, config_fields
from engine.core.kits import KITS
from engine.core.schemes import DEFAULT_SCHEME, SCHEMES
from engine.core.storyclock import TEXT_FIELDS, Calendar, calendar_of
from engine.tools.editor import kitmodel as km
from engine.tools.editor import schememodel as scm

SECTION: Final = "calendar"
KEYS: Final = tuple(config_fields(CalendarConfig))
NAME_KEYS: Final = ("parts", "weekdays", "months", "seasons")
MORE_KEYS: Final = ("weekdays", "months", "seasons", "season_days")   # shown on demand
PLACE_NAMES: Final = {"top_left": "Top left", "top_right": "Top right",
                      "bottom_left": "Bottom left", "bottom_right": "Bottom right"}

INTRO: Final = ("Story time: what the parts of a day are called, the day the story starts "
                "on, and how dates read. Move time in the story with Insert ▸ Time.")
FROM_KIT: Final = "From the {kit} kit"
FROM_ENGINE: Final = "The engine's default"
FIELDS_HINT: Final = "Use {fields} in curly brackets."
READS: Final = "Reads: {text}"
CARD_CAPTION: Final = "At a new day the story shows this card."
CARD_OFF: Final = "No card at a new day (turned off)."
CORNER_CAPTION: Final = "show clock puts this in the {place} corner."
_PROBLEMS: Final = {
    "start": 'The start "{text}" isn\'t a date this calendar can read, so the story starts '
             "on day 1.",
    "month_days": "Days in a month needs one number for each month.",
    "field": "How a date reads uses {{{text}}}, which this calendar doesn't have.",
}


def own(found: Mapping[str, object]) -> dict[str, object | None]:
    """Each key the file sets, as the game reads it (None: not set or refused)."""
    out: dict[str, object | None] = {}
    for key, field_ in config_fields(CalendarConfig).items():
        value = found.get(f"{SECTION}.{key}")
        try:
            out[key] = None if value is None else field_.metadata["validator"].check(value)
        except ValueProblem:
            out[key] = None
    return out


def _config(found: Mapping[str, object]) -> SimpleNamespace:
    kit = found.get(km.PATH)
    return SimpleNamespace(calendar=SimpleNamespace(**own(found)),
                           theme=SimpleNamespace(kit=kit if isinstance(kit, str) else None))


def calendar(found: Mapping[str, object]) -> Calendar:
    """The calendar the game will use with the text ``found`` was read from."""
    return calendar_of(_config(found))[0]


def problems(found: Mapping[str, object]) -> tuple[str, ...]:
    """What the game would warn about at load (W301), in words."""
    return tuple(_PROBLEMS[p.form].format(text=p.text)
                 for p in calendar_of(_config(found))[1])


def kit_name(found: Mapping[str, object]) -> str | None:
    kit = found.get(km.PATH)
    return KITS[kit].name if isinstance(kit, str) and kit in KITS else None


def source(found: Mapping[str, object], key: str) -> str:
    """Where key ``key``'s value comes from while the file doesn't set it."""
    name = kit_name(found)
    from_kit = name is not None and key in ("parts", "day_text", "place", "seasons", "months")
    if from_kit and key in ("seasons", "months"):
        found_kit = KITS[str(found.get(km.PATH))].clock
        from_kit = found_kit is not None and bool(getattr(found_kit, key))
    return FROM_KIT.format(kit=name) if from_kit else FROM_ENGINE


def names_text(names: object) -> str:
    """A name list as one line: "Dusk, Midnight"."""
    if isinstance(names, (list, tuple)):
        return ", ".join(str(n) for n in names)
    return ""


def names_of(text: str) -> list[str]:
    """One line of names back into a list (commas between; blanks dropped)."""
    return [" ".join(part.split()) for part in text.split(",") if part.strip()]


def check_names(key: str, names: list[str]) -> bool:
    """Whether ``[calendar] key`` would take ``names``."""
    try:
        config_fields(CalendarConfig)[key].metadata["validator"].check(names)
    except ValueProblem:
        return False
    return True


def start_value(text: str) -> int | str | None:
    """The start field's text as written: a day number, else the date's text, None blank."""
    text = " ".join(text.split())
    if not text:
        return None
    return int(text) if text.isdigit() and len(text) <= 6 else text


def fields_hint(cal: Calendar) -> str:
    """The fields ``day_text`` may use with this calendar."""
    have = set(cal.fields(1))
    return FIELDS_HINT.format(fields=", ".join(f"{{{name}}}" for name in TEXT_FIELDS
                                               if name in have))


# --- The preview ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CalendarPreview:
    """What the preview draws: the day ``card`` text and whether the card is on, its
    ``card_fill`` and ``card_text`` colors; the corner's ``date`` and ``part`` at ``place``;
    ``colors`` (``kitmodel.KitCard``'s six: fill, text, border, accent, soft, track) for the
    stage and the corner's panel; the two captions."""

    card: str
    card_on: bool
    card_fill: str
    card_text: str
    date: str
    part: str
    place: str
    colors: tuple[str, str, str, str, str, str]
    card_caption: str
    corner_caption: str


def card_colors(found: Mapping[str, object]) -> tuple[str, str]:
    """The chapter card's fill and title colors (``[theme.chapter]`` > the scheme)."""
    value = found.get(scm.PATH)
    base = SCHEMES.get(value if isinstance(value, str) else DEFAULT_SCHEME,
                       SCHEMES[DEFAULT_SCHEME])
    roles = {**base.colors, **scm.custom_roles(found)}

    def token(path: str, role: str) -> str:
        mine = found.get(f"theme.{path}")
        if isinstance(mine, str) and mine.startswith("#"):
            return mine
        return base.extra.get(path, roles[role])
    return token("chapter.fill_color", "fill"), token("chapter.title.text_color", "text")


def preview(found: Mapping[str, object]) -> CalendarPreview:
    cal = calendar(found)
    fill, text = card_colors(found)
    day = cal.start_day
    return CalendarPreview(
        cal.date(day + 1), cal.day_card, fill, text, cal.date(day), cal.parts[0], cal.place,
        km.cards(found)[0].colors, CARD_CAPTION if cal.day_card else CARD_OFF,
        CORNER_CAPTION.format(place=PLACE_NAMES.get(cal.place, cal.place).lower()))


__all__ = ["CalendarPreview", "INTRO", "KEYS", "MORE_KEYS", "NAME_KEYS", "PLACE_NAMES",
           "SECTION", "calendar", "card_colors", "check_names", "fields_hint", "kit_name",
           "names_of", "names_text", "own", "preview", "problems", "source", "start_value"]
