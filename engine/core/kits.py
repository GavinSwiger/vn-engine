"""The built-in genre kits (F60; plan: specs/skins-contract.md, "F60 Genre kits").

Why this module exists: the engine's shared systems (meters now; messages, the clock,
items and checks later) are one mechanic each, dressed per genre. A **kit** is that
dressing in one bundle, so an author picks "Fantasy" once with ``[theme] kit = "fantasy"``
and the wording, the look and the defaults match. A kit never changes what a game does on
its own: it only fills in what the author left unset.

- ``Kit``: ``id`` (the ``kit`` value), ``name``, a one-line ``blurb``, ``scheme`` (the F49
  scheme it suggests; Studio offers to apply it with the kit, config never does),
  ``meters`` (``MeterDress``: the default ``look`` and ``place`` of a shown meter and the
  "+ Meter" ``suggestions``), ``clock`` (``ClockDress``, F63: the parts of the day and how a
  day is worded), ``items`` (F64) and ``messages`` (F65), filled below, and ``checks``:
  reserved, empty until that system lands.
- ``KITS`` / ``kit(id)`` / ``kit_ids()``: the registry, in Studio's order.
- ``kit_of(config)``: the kit ``[theme] kit`` names, or None (no kit: today's behavior).
- ``meter_look(config, meter)``: how meter ``meter`` is shown, as ``(look, place, label)``,
  with the precedence ``[meter.<name>]`` > kit > ``skins`` defaults.
- F64: each kit's ``items`` holds ``ITEMS_BAG`` (the bag's name: Satchel, Evidence, Cargo)
  and ``ITEMS_MONEY`` (the money word: Gold, Credits; "" for none), from ``ITEM_WORDS``.
  ``bag_words(config)`` gives ``(bag, money)``: ``[codex] bag_word`` / ``money_word`` when
  set, else the kit's, else "" (the page's own "Items", the money item's own title).
  Round 2: ``ITEMS_HOTBAR``, the hotbar's name (Belt, Pockets; ``hotbar_word``).
- F65: each kit's ``messages`` holds ``MESSAGES_TITLE`` (the Inbox page's name: Messages,
  Letters, Comms) and ``MESSAGES_DEVICE`` (the default device look: one of
  ``DEVICE_LOOKS``), from ``MESSAGE_WORDS``. ``kit_words(config)`` gives the ``[words]``
  a kit fills in, by key (the pages of ``codexkinds`` kinds with a ``kit_title``), for
  ``ui/theme.Words`` to use where the author left the word at its default.
- F65 round 2: ``DEVICE_WORDS`` / ``device_words(look)``: how each device look words a
  message (``DeviceWords``: the arrival notice, the line above each message in the Inbox,
  and whether the sender's lines read as a letter or as chat lines), so a pigeon lands on
  the sill while a phone buzzes. Round 3: ``device_words(look, config)`` lays
  ``[device.<look>]`` over these key by key (``DeviceWords`` gains the device's ``name``
  and arrival ``sound``), ``arrive_text`` fills in ``{name}``, and the game's device's
  name names the Inbox (``kit_words``).

Pure data, read-only; imports only ``core``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Final

from engine.core.codexkinds import CHAT, codex_kinds
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
class ClockDress:
    """A kit's story clock (F63): the ``parts`` of the day, ``day_text`` (how a date is
    worded, with fields such as ``{day}``; see ``storyclock.TEXT_FIELDS``), and, when the
    genre counts time that way, ``seasons`` or ``months`` (True: the twelve months). Each
    gives way to ``[calendar]`` (``storyclock.calendar_of``). F63 round 2: ``place``, the
    status corner ``show clock`` puts the clock in (the corner the kit's meters don't use)."""
    parts: tuple[str, ...]
    day_text: str
    seasons: tuple[str, ...] = ()
    months: bool = False
    place: str = "top_right"


@dataclass(frozen=True)
class Kit:
    """One built-in kit (see the module docstring). The reserved sections are empty
    mappings until their system lands; every built-in kit has a ``clock``."""
    id: str
    name: str
    blurb: str
    scheme: str
    meters: MeterDress
    clock: ClockDress | None = None
    messages: Mapping[str, Any] = field(default=_EMPTY)
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
        )), clock=ClockDress(("Morning", "Lunch", "After school", "Evening"),
                             "{weekday}, day {day}", place="top_left")),
    Kit("horror", "Horror",
        "Blood-dark colors, and a sanity bar that drains as the night goes on.",
        "blood_moon", MeterDress("bar", "top_left", (
            _m("sanity", "Sanity", 0, 100, 100,
               ("Breaking", 0), ("Shaken", 25), ("Uneasy", 50), ("Steady", 75)),
            _m("composure", "Composure", 0, 10, 5,
               ("Panicked", 0), ("Rattled", 4), ("Calm", 7)),
        )), clock=ClockDress(("Dusk", "Midnight", "Witching hour", "Dawn"), "Night {day}")),
    Kit("mystery", "Mystery",
        "Black and white, with suspicion and credibility to keep an eye on.",
        "noir", MeterDress("number", "top_right", (
            _m("suspicion", "Suspicion", 0, 10, 0,
               ("Unnoticed", 0), ("Watched", 4), ("Accused", 8)),
            _m("credibility", "Credibility", 0, 10, 5,
               ("Doubted", 0), ("Heard", 4), ("Trusted", 8)),
            _m("clues", "Clues", 0, 20, 0),
        )), clock=ClockDress(("Morning", "Afternoon", "Evening", "Small hours"),
                             "Day {day} of the case", place="top_left")),
    Kit("fantasy", "Fantasy",
        "Parchment and gold, with renown to earn and stamina to spend.",
        "high_fantasy", MeterDress("pips", "top_left", (
            _m("renown", "Renown", 0, 100, 0,
               ("Unknown", 0), ("Known", 20), ("Famed", 50), ("Legend", 85)),
            _m("stamina", "Stamina", 0, 10, 10,
               ("Spent", 0), ("Tired", 3), ("Fresh", 7)),
            _m("gold", "Gold", 0, 999, 20),
        )), clock=ClockDress(("Dawn", "Midday", "Dusk", "Night"),
                             "Day {day} of the journey")),
    Kit("cozy", "Cozy",
        "Warm café colors, a good mood and a pocket of coins.",
        "cozy_cafe", MeterDress("number", "top_left", (
            _m("mood", "Mood", 0, 10, 6,
               ("Gloomy", 0), ("Content", 4), ("Cheerful", 8)),
            _m("coins", "Coins", 0, 999, 50),
        )), clock=ClockDress(("Morning", "Afternoon", "Evening", "Night"),
                             "{season}, day {season_day}",
                             seasons=("Spring", "Summer", "Autumn", "Winter"))),
    Kit("scifi", "Sci-fi",
        "A starship console, with hull and oxygen gauges to watch.",
        "starship", MeterDress("dial", "top_left", (
            _m("hull", "Hull", 0, 100, 100,
               ("Breached", 0), ("Damaged", 30), ("Holding", 70)),
            _m("oxygen", "Oxygen", 0, 100, 100,
               ("Gasping", 0), ("Thin", 30), ("Clear", 60)),
        )), clock=ClockDress(("Alpha watch", "Beta watch", "Gamma watch"), "Shift {day}")),
    Kit("letters", "Letters",
        "Old paper and ink, and the slow trust of letters between two people.",
        "sepia", MeterDress("pips", "top_right", (
            _m("trust", "Trust", 0, 10, 2,
               ("Strangers", 0), ("Pen pals", 3), ("Confidants", 7)),
            _m("hope", "Hope", 0, 10, 5,
               ("Despairing", 0), ("Waiting", 4), ("Hopeful", 8)),
        )), clock=ClockDress(("Morning post", "Evening post"), "{month_day} {month}",
                             months=True, place="top_left")),
)})

# F64: the kits' ``items`` sections (bag name, money word), filled in after the rows above so
# each system's kit section stays in one place.
ITEMS_BAG: Final = "bag"
ITEMS_MONEY: Final = "money"
ITEM_WORDS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType({
    "romance": ("Keepsakes", "Coins"),
    "horror": ("Supplies", ""),
    "mystery": ("Evidence", ""),
    "fantasy": ("Satchel", "Gold"),
    "cozy": ("Basket", "Coins"),
    "scifi": ("Cargo", "Credits"),
    "letters": ("Keepsakes", "Stamps"),
})
# F64 round 2: the hotbar's name per kit (``ITEMS_HOTBAR``), shown in the bag beside Use.
ITEMS_HOTBAR: Final = "hotbar"
HOTBAR_WORDS: Final[Mapping[str, str]] = MappingProxyType({
    "romance": "Pocket", "horror": "Pockets", "mystery": "Pockets", "fantasy": "Belt",
    "cozy": "Apron", "scifi": "Quick slots", "letters": "Desk",
})
# F65: the kits' ``messages`` sections (the Inbox page's name, the default device look).
MESSAGES_TITLE: Final = "title"
MESSAGES_DEVICE: Final = "device"
DEVICE_LOOKS: Final = ("phone", "letters", "pigeon", "radio", "terminal", "mind")
MESSAGE_WORDS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType({
    "romance": ("Messages", "phone"),
    "horror": ("Whispers", "mind"),
    "mystery": ("Dispatches", "radio"),
    "fantasy": ("Pigeon post", "pigeon"),
    "cozy": ("Messages", "phone"),
    "scifi": ("Comms", "terminal"),
    "letters": ("Letters", "letters"),
})


@dataclass(frozen=True, slots=True)
class DeviceWords:
    """F65 round 2: how a device look words a message. ``arrive``: the arrival notice
    (``{name}``: the sender's display name); ``via``: the line above each message in the
    Inbox ("Arrived by pigeon"); ``letter``: the sender's lines read as one letter (plain
    paragraphs, signed "— Hana") rather than as chat lines ("Hana: …"). Round 3: ``name``,
    the device's shown name, and ``sound``, the arrival sound (None: silence)."""

    arrive: str
    via: str
    letter: bool
    name: str = ""
    sound: str | None = None


DEVICE_WORDS: Final[Mapping[str, DeviceWords]] = MappingProxyType({
    "phone": DeviceWords("New message from {name}.", "Message", False, "Phone"),
    "letters": DeviceWords("A letter from {name} has arrived.", "Letter", True, "Letters"),
    "pigeon": DeviceWords("A pigeon lands on the sill with a note from {name}.",
                          "Arrived by pigeon", True, "Pigeon post"),
    "radio": DeviceWords("The radio crackles. It's {name}.", "Over the radio", False,
                         "Radio"),
    "terminal": DeviceWords("Incoming transmission from {name}.", "Transmission", False,
                            "Terminal"),
    "mind": DeviceWords("{name}'s voice, inside your head.", "A thought", True, "Mind"),
})


def device_words(look: str, config: Any = None) -> DeviceWords:
    """F65 round 2: ``look``'s wording (a phone's for a look this engine doesn't know).
    Round 3: each key ``config``'s ``[device.<look>]`` sets wins over the engine's word."""
    words = DEVICE_WORDS.get(look) or DEVICE_WORDS[DEVICE_LOOKS[0]]
    table = getattr(config, "device", _EMPTY).get(look)
    if table is None:
        return words
    reading = getattr(table, "reading", None)
    return DeviceWords(table.arrive_text or words.arrive, table.header_text or words.via,
                       words.letter if reading is None else reading == "letter",
                       table.name or words.name, table.arrive_sound or words.sound)


def arrive_text(words: DeviceWords, name: str) -> str:
    """F65 round 3: the arrival notice with ``{name}`` filled in (only that field, so an
    author's other braces show as written)."""
    return words.arrive.replace("{name}", name)


KITS = MappingProxyType({  # type: ignore[misc]
    id_: replace(k, items=MappingProxyType({ITEMS_BAG: ITEM_WORDS[id_][0],
                                            ITEMS_MONEY: ITEM_WORDS[id_][1],
                                            ITEMS_HOTBAR: HOTBAR_WORDS[id_]}),
                 messages=MappingProxyType({MESSAGES_TITLE: MESSAGE_WORDS[id_][0],
                                            MESSAGES_DEVICE: MESSAGE_WORDS[id_][1]}))
    for id_, k in KITS.items()})


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


def bag_words(config: Any) -> tuple[str, str]:
    """F64: ``(bag, money)`` for the bag page (module docstring)."""
    found = kit_of(config)
    own = getattr(config, "codex", None)
    out = []
    for key, attr in ((ITEMS_BAG, "bag_word"), (ITEMS_MONEY, "money_word")):
        mine = getattr(own, attr, "")
        if isinstance(mine, str) and mine.strip():
            out.append(mine.strip())
        else:
            word = found.items.get(key, "") if found is not None else ""
            out.append(word if isinstance(word, str) else "")
    return out[0], out[1]


def hotbar_word(config: Any) -> str:
    """F64 round 2: the hotbar's name: ``[hotbar] word``, else the kit's, else ""."""
    own = getattr(getattr(config, "hotbar", None), "word", "")
    if isinstance(own, str) and own.strip():
        return own.strip()
    found = kit_of(config)
    word = found.items.get(ITEMS_HOTBAR, "") if found is not None else ""
    return word if isinstance(word, str) else ""


def kit_words(config: Any) -> dict[str, str]:
    """F65: the ``[words]`` the kit fills in, by key: each codex kind's page with a
    ``kit_title`` (``("messages", "title")`` names the ``inbox`` page). ``{}`` with no kit.
    ``ui/theme.Words`` uses one only where the author left that word at its default.
    Round 3: the game's device's ``[device.<look>] name`` wins over the kit's title."""
    found = kit_of(config)
    if found is None:
        return device_name_words(config)
    out: dict[str, str] = {}
    for kind in codex_kinds():
        if kind.kit_title is None:
            continue
        section, key = kind.kit_title
        word = getattr(found, section, _EMPTY).get(key, "")
        if isinstance(word, str) and word.strip():
            out.setdefault(kind.page, word.strip())
    return {**out, **device_name_words(config)}


def device_name_words(config: Any) -> dict[str, str]:
    """F65 round 3: ``{"inbox": name}`` when ``[device.<the game's device>] name`` is set
    (it then wins over the kit's title), else ``{}``."""
    table = getattr(config, "device", _EMPTY).get(device_look(config))
    name = getattr(table, "name", None)
    return {CHAT.page: name.strip()} if isinstance(name, str) and name.strip() else {}


def device_look(config: Any) -> str:
    """F65: the kit's default device look ("phone" with no kit)."""
    found = kit_of(config)
    look = found.messages.get(MESSAGES_DEVICE, "") if found is not None else ""
    return look if look in DEVICE_LOOKS else DEVICE_LOOKS[0]


__all__ = ["DEVICE_LOOKS", "DEVICE_WORDS", "DeviceWords", "arrive_text", "device_name_words",
           "device_words", "HOTBAR_WORDS", "ITEMS_BAG", "ITEMS_HOTBAR", "ITEMS_MONEY",
           "ITEM_WORDS", "MESSAGES_DEVICE", "MESSAGES_TITLE", "MESSAGE_WORDS",
           "bag_words", "device_look", "hotbar_word", "kit_words",
           "ClockDress", "KITS", "Kit", "MeterDress", "MeterSuggestion", "kit", "kit_ids", "kit_of",
           "meter_label", "meter_look"]
