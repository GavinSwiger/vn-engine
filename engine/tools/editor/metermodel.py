"""Database ▸ Meters' setup helpers, the pure half (F62 round 2;
specs/F62-visible-meters/SPEC.md §7).

Why this module exists: an author who has never coded should get a working meter in one
click and dress it without opening config.toml. This module says which ready-made meters
"+ Meter" offers (the kit's, or a short general list), how a meter is shown now (its own
``[meter.<name>]`` keys over the kit over the defaults, ``kits.meter_look``), what the
look fields write, and what the little preview draws. The widgets are in ``dbmore``; the
drawing is ``meterdraw``.

- ``offers(found)``: the "+ Meter" presets: the game's kit's suggestions, else
  ``GENERAL``; ``offer_text`` is a menu line, ``offer_values`` the ``meter_line`` values.
- ``own(found, name)``: the meter's own look, place and label (None when unset);
  ``default_text(found, name)`` says what an unset field falls back to.
- ``look_changes(name, key, value)``: the ``tomlpatch.plan_changes`` change for one field
  (an empty value removes the key, and ``drop_empty`` takes an emptied table with it).
- ``preview(found, name, values)``: what the preview draws, as a ``MeterPreview``.

Pure Python: ``core`` and this package's pure modules only; no Tk, no pygame (ADR-0008).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Final

from engine.core.kits import KITS, Kit, MeterSuggestion, meter_look
from engine.core.skins import CORNER_PLACES, METER_LOOKS
from engine.tools.editor import declarations as dec
from engine.tools.editor import kitmodel as km

# --- Texts ------------------------------------------------------------------------------------

BLANK: Final = "Blank meter…"
KIT_HINT: Final = "Game settings ▸ Kit suggests meters for your genre"
KIT_OFFERS: Final = "Suggested by the {kit} kit"
ALREADY: Final = "{label} (already in your game)"
OFFER: Final = "{label}  ·  {low} to {high}, starts at {start}{ranks}"
OFFER_RANKS: Final = "  ·  {labels}"
KIT_DEFAULT: Final = "Kit default: {look}, {place}"
PLAIN_DEFAULT: Final = "Default: {look}, {place}"
LABEL_DEFAULT: Final = "Empty: shows “{label}”."
SAMPLE: Final = "Shown at {value}{of}{rank}"
SAMPLE_OF: Final = " of {high}"
SAMPLE_RANK: Final = " · {rank}"

LOOK_NAMES: Final[Mapping[str, str]] = {
    "bar": "Bar", "number": "Number", "hearts": "Hearts", "pips": "Pips", "dial": "Dial"}
PLACE_NAMES: Final[Mapping[str, str]] = {
    "top_left": "Top left", "top_right": "Top right", "bottom_left": "Bottom left",
    "bottom_right": "Bottom right"}

SECTION: Final = "meter"
KEYS: Final = ("look", "place", "label")
SAMPLE_SHARE: Final = 0.6                 # the preview shows the meter this full

# No kit: a short list that fits most stories.
GENERAL: Final[tuple[MeterSuggestion, ...]] = (
    MeterSuggestion("affection", "Affection", 0, 10, 0,
                    (("Stranger", 0), ("Friend", 4), ("Close", 8))),
    MeterSuggestion("trust", "Trust", 0, 10, 5,
                    (("Wary", 0), ("Trusting", 4), ("Loyal", 8))),
    MeterSuggestion("courage", "Courage", 0, 10, 3,
                    (("Shy", 0), ("Brave", 5), ("Fearless", 9))),
    MeterSuggestion("coins", "Coins", 0, 999, 0),
)


def kit_in_use(found: Mapping[str, object]) -> Kit | None:
    """The kit config.toml's values ``found`` name, or None."""
    value = found.get(km.PATH)
    return KITS.get(value) if isinstance(value, str) else None


def offers(found: Mapping[str, object]) -> tuple[tuple[MeterSuggestion, ...], Kit | None]:
    """The "+ Meter" presets and the kit they come from (None: ``GENERAL``)."""
    kit = kit_in_use(found)
    return (kit.meters.suggestions if kit is not None else GENERAL), kit


def offer_text(offer: MeterSuggestion, taken: bool = False) -> str:
    """A preset's menu line: ``Sanity · 0 to 100, starts at 100 · Breaking, Shaken, …``."""
    if taken:
        return ALREADY.format(label=offer.label)
    ranks = OFFER_RANKS.format(labels=", ".join(label for label, _ in offer.ranks)) \
        if offer.ranks else ""
    return OFFER.format(label=offer.label, low=offer.low, high=offer.high, start=offer.start,
                        ranks=ranks)


def offer_values(offer: MeterSuggestion) -> dict[str, object]:
    """``declarations.meter_line`` values for a preset (``start`` only when it isn't the
    engine's own)."""
    values: dict[str, object] = {"low": offer.low, "high": offer.high, "start": None}
    if dec.meter_start(values) != offer.start:
        values["start"] = offer.start
    if offer.ranks:
        values["ranks"] = tuple(offer.ranks)
    return values


# --- The meter's look ---------------------------------------------------------------------------

def own(found: Mapping[str, object], name: str) -> dict[str, str | None]:
    """The meter's own ``[meter.<name>]`` keys (look, place, label), None when unset or not a
    value this version reads."""
    out: dict[str, str | None] = {}
    for key in KEYS:
        value = found.get(f"{SECTION}.{name}.{key}")
        ok = isinstance(value, str) and (
            value in METER_LOOKS if key == "look" else
            value in CORNER_PLACES if key == "place" else bool(value.strip()))
        out[key] = value if ok else None                          # type: ignore[assignment]
    return out


def _config(found: Mapping[str, object], tables: Mapping[str, object]) -> SimpleNamespace:
    """The shape ``kits.meter_look`` reads, from ``found``."""
    return SimpleNamespace(theme=SimpleNamespace(kit=found.get(km.PATH)), meter=tables)


def shown(found: Mapping[str, object], name: str) -> tuple[str, str, str]:
    """How the meter is shown now: ``(look, place, label)``."""
    return meter_look(_config(found, {name: SimpleNamespace(**own(found, name))}), name)


def fallback(found: Mapping[str, object], name: str) -> tuple[str, str, str]:
    """What the meter's look, place and label are when its own keys are unset."""
    return meter_look(_config(found, {}), name)


def default_text(found: Mapping[str, object], name: str) -> str:
    """"Kit default: hearts, top right" (without a kit: "Default: bar, top left")."""
    look, place, _label = fallback(found, name)
    words = KIT_DEFAULT if kit_in_use(found) is not None else PLAIN_DEFAULT
    return words.format(look=look, place=km.PLACE_WORDS[place].replace("-", " "))


def label_text(found: Mapping[str, object], name: str) -> str:
    """The label field's hint: what an empty label shows."""
    return LABEL_DEFAULT.format(label=fallback(found, name)[2])


def look_changes(name: str, key: str, value: str | None
                 ) -> tuple[tuple[str, str, str | None], ...]:
    """The change that sets ``[meter.<name>] key`` (None or blank: removes it)."""
    if isinstance(value, str):
        value = value.strip() or None
    return ((f"{SECTION}.{name}", key, value),)


# --- The preview --------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MeterPreview:
    """What the preview draws: ``colors`` (``kitmodel.KitCard``'s six), ``look``, ``place``,
    ``label``, the sample ``share`` (0 to 1), ``number``, ``of`` ("/ 10" or ""), ``rank``,
    and ``caption`` under it ("Shown at 6 of 10 · Friend")."""

    colors: tuple[str, str, str, str, str, str]
    look: str
    place: str
    label: str
    share: float
    number: str
    of: str
    rank: str
    caption: str


def sample(values: Mapping[str, object]) -> tuple[int, float]:
    """The sample value the preview shows and how full that is: 60 % of the range, or 6
    out of 10 without one."""
    low, high = values.get("low"), values.get("high")
    if type(low) is int and type(high) is int and high > low:
        value = low + round((high - low) * SAMPLE_SHARE)
        return value, (value - low) / (high - low)
    return 6, SAMPLE_SHARE


def rank_at(values: Mapping[str, object], value: int) -> str:
    """The rank label at ``value`` (the highest at or below it), "" for none."""
    label = ""
    for name, at in values.get("ranks") or ():                      # type: ignore[attr-defined]
        if value >= at:
            label = str(name)
    return label


def preview(found: Mapping[str, object], name: str, values: Mapping[str, object]
            ) -> MeterPreview:
    """The preview of meter ``name`` (declared with ``values``) as config ``found`` shows
    it, in the game's color scheme."""
    look, place, label = shown(found, name)
    value, share = sample(values)
    high = values.get("high")
    ranged = type(high) is int
    rank = rank_at(values, value)
    caption = SAMPLE.format(value=value, of=SAMPLE_OF.format(high=high) if ranged else "",
                            rank=SAMPLE_RANK.format(rank=rank) if rank else "")
    colors = km.cards(found)[0].colors                  # "No kit"'s card: the scheme in use
    return MeterPreview(colors, look, place, label, share, str(value),
                        f"/ {high}" if ranged else "", rank, caption)


__all__ = ["BLANK", "GENERAL", "KEYS", "KIT_HINT", "KIT_OFFERS", "LOOK_NAMES", "MeterPreview",
           "PLACE_NAMES", "SECTION", "default_text", "fallback", "kit_in_use", "label_text",
           "look_changes", "offer_text", "offer_values", "offers", "own", "preview",
           "rank_at", "sample", "shown"]
