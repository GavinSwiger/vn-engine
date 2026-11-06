"""The built-in genre kits (F60; plan: specs/skins-contract.md, "F60 Genre kits").

Why this module exists: the engine's shared systems (meters now; messages, the clock,
items and checks later) are one mechanic each, dressed per genre. A **kit** is that
dressing in one bundle, so an author picks "Fantasy" once with ``[theme] kit = "fantasy"``
and the wording, the look and the defaults match. A kit never changes what a game does on
its own: it only fills in what the author left unset.

- ``Kit``: ``id`` (the ``kit`` value), ``name``, a one-line ``blurb``, ``scheme`` (the F49
  scheme it suggests; Studio offers to apply it with the kit, config never does),
  ``meters`` (``MeterDress``: the default ``look`` and ``place`` of a shown meter and the
  "+ Meter" ``suggestions``), and ``messages``, ``clock``, ``items``, ``checks``: reserved,
  empty until those systems land.
- ``KITS`` / ``kit(id)`` / ``kit_ids()``: the registry, in Studio's order.
- ``kit_of(config)``: the kit ``[theme] kit`` names, or None (no kit: today's behavior).
- ``meter_look(config, meter)``: how meter ``meter`` is shown, as ``(look, place, label)``,
  with the precedence ``[meter.<name>]`` > kit > ``skins`` defaults.

Pure data, read-only; imports only ``core``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from engine.core.skins import CORNER_PLACES, DEFAULT_CORNER_PLACE, DEFAULT_METER_LOOK, METER_LOOKS

_EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})


@dataclass(frozen=True)
class MeterSuggestion:
    """One "+ Meter" preset: the variable ``name``, the shown ``label``, its range ``low`` to
    ``high``, the ``start`` value, and ``ranks`` as ``(label, at)`` pairs, rising."""
    name: str
    label: str
    low: int
    high: int
    start: int
    ranks: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class MeterDress:
    """A kit's meters: ``look`` (one of ``skins.METER_LOOKS``) and ``place`` (one of
    ``skins.CORNER_PLACES``) for every shown meter, and the ``suggestions``."""
    look: str
    place: str
    suggestions: tuple[MeterSuggestion, ...]


@dataclass(frozen=True)
class Kit:
    """One built-in kit (see the module docstring). The reserved sections are empty
    mappings until their system lands."""
    id: str
    name: str
    blurb: str
    scheme: str
    meters: MeterDress
    messages: Mapping[str, Any] = field(default=_EMPTY)
    clock: Mapping[str, Any] = field(default=_EMPTY)
    items: Mapping[str, Any] = field(default=_EMPTY)
    checks: Mapping[str, Any] = field(default=_EMPTY)


def _m(name: str, label: str, low: int, high: int, start: int,
       *ranks: tuple[str, int]) -> MeterSuggestion:
    return MeterSuggestion(name, label, low, high, start, tuple(ranks))


# The kits, in the order Studio shows them (after "No kit"). Each row is the proposal's
# "One mechanic, many skins" column for its genre.
KITS: Final[Mapping[str, Kit]] = MappingProxyType({k.id: k for k in (
    Kit("romance", "Romance",
        "Rose colors, and hearts that fill as someone warms to you.",
        "rose_garden", MeterDress("hearts", "top_right", (
            _m("affection", "Affection", 0, 10, 0,
               ("Stranger", 0), ("Friend", 4), ("Close", 8)),
            _m("courage", "Courage", 0, 10, 3,
               ("Shy", 0), ("Brave", 5), ("Fearless", 9)),
        ))),
    Kit("horror", "Horror",
        "Blood-dark colors, and a sanity bar that drains as the night goes on.",
        "blood_moon", MeterDress("bar", "top_left", (
            _m("sanity", "Sanity", 0, 100, 100,
               ("Breaking", 0), ("Shaken", 25), ("Uneasy", 50), ("Steady", 75)),
            _m("composure", "Composure", 0, 10, 5,
               ("Panicked", 0), ("Rattled", 4), ("Calm", 7)),
        ))),
    Kit("mystery", "Mystery",
        "Black and white, with suspicion and credibility to keep an eye on.",
        "noir", MeterDress("number", "top_right", (
            _m("suspicion", "Suspicion", 0, 10, 0,
               ("Unnoticed", 0), ("Watched", 4), ("Accused", 8)),
            _m("credibility", "Credibility", 0, 10, 5,
               ("Doubted", 0), ("Heard", 4), ("Trusted", 8)),
            _m("clues", "Clues", 0, 20, 0),
        ))),
    Kit("fantasy", "Fantasy",
        "Parchment and gold, with renown to earn and stamina to spend.",
        "high_fantasy", MeterDress("pips", "top_left", (
            _m("renown", "Renown", 0, 100, 0,
               ("Unknown", 0), ("Known", 20), ("Famed", 50), ("Legend", 85)),
            _m("stamina", "Stamina", 0, 10, 10,
               ("Spent", 0), ("Tired", 3), ("Fresh", 7)),
            _m("gold", "Gold", 0, 999, 20),
        ))),
    Kit("cozy", "Cozy",
        "Warm café colors, a good mood and a pocket of coins.",
        "cozy_cafe", MeterDress("number", "top_left", (
            _m("mood", "Mood", 0, 10, 6,
               ("Gloomy", 0), ("Content", 4), ("Cheerful", 8)),
            _m("coins", "Coins", 0, 999, 50),
        ))),
    Kit("scifi", "Sci-fi",
        "A starship console, with hull and oxygen gauges to watch.",
        "starship", MeterDress("dial", "top_left", (
            _m("hull", "Hull", 0, 100, 100,
               ("Breached", 0), ("Damaged", 30), ("Holding", 70)),
            _m("oxygen", "Oxygen", 0, 100, 100,
               ("Gasping", 0), ("Thin", 30), ("Clear", 60)),
        ))),
    Kit("letters", "Letters",
        "Old paper and ink, and the slow trust of letters between two people.",
        "sepia", MeterDress("pips", "top_right", (
            _m("trust", "Trust", 0, 10, 2,
               ("Strangers", 0), ("Pen pals", 3), ("Confidants", 7)),
            _m("hope", "Hope", 0, 10, 5,
               ("Despairing", 0), ("Waiting", 4), ("Hopeful", 8)),
        ))),
)})


def kit_ids() -> tuple[str, ...]:
    """The kit ids in registry order (``KitName``'s options)."""
    return tuple(KITS)


def kit(id_: str) -> Kit | None:
    """The kit with id ``id_`` (case-sensitive), or None."""
    return KITS.get(id_)


def kit_of(config: Any) -> Kit | None:
    """The kit ``config``'s ``[theme] kit`` names, or None: no kit, or an id this version
    doesn't have (config warned and dropped it)."""
    theme = getattr(config, "theme", None)
    value = getattr(theme, "kit", None)
    return KITS.get(value) if isinstance(value, str) else None


def meter_label(meter: str) -> str:
    """A meter's shown name from its variable name: ``hana_love`` → "Hana love"."""
    words = meter.replace("_", " ").split()
    return " ".join(words)[:1].upper() + " ".join(words)[1:] if words else meter


def _own_meter(config: Any, meter: str) -> Any:
    """``[meter.<meter>]``'s table, or None. That table arrives with F62 round 2 (as
    ``config.meter``, a mapping of name → a table with ``look``, ``place``, ``label``, each
    None when unset); until then no config has one."""
    tables = getattr(config, "meter", None)
    if isinstance(tables, Mapping):
        return tables.get(meter)
    return None


def meter_look(config: Any, meter: str) -> tuple[str, str, str]:
    """How meter ``meter`` is shown: ``(look, place, label)``. Each comes from the first that
    sets it: the meter's own ``[meter.<name>]`` table, then the kit (its look and place, and
    the label of a suggestion with that name), then ``skins``' defaults (the label from the
    variable name)."""
    own = _own_meter(config, meter)
    found = kit_of(config)
    look, place, label = DEFAULT_METER_LOOK, DEFAULT_CORNER_PLACE, meter_label(meter)
    if found is not None:
        look, place = found.meters.look, found.meters.place
        label = next((s.label for s in found.meters.suggestions if s.name == meter), label)
    if own is not None:
        mine = getattr(own, "look", None)
        look = mine if mine in METER_LOOKS else look
        mine = getattr(own, "place", None)
        place = mine if mine in CORNER_PLACES else place
        mine = getattr(own, "label", None)
        label = mine if isinstance(mine, str) and mine.strip() else label
    return look, place, label


__all__ = ["KITS", "Kit", "MeterDress", "MeterSuggestion", "kit", "kit_ids", "kit_of",
           "meter_label", "meter_look"]
