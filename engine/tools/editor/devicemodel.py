"""Game settings ▸ Devices, the pure half (F65 round 3, "Studio contacts and devices").

Why this module exists: a message comes by one of six devices (phone, letter, pigeon,
radio, terminal, mind), and ``[device.<look>]`` in config.toml sets how each words and
sounds one: its name, the arrival notice, the arrival sound, the line above each message
and how the sender's lines read. The Devices page shows one card per device with a live
preview in the game's colors; this module reads the open text's values
(``settingsmodel.values``) into what the cards show and turns an edit into ``tomlpatch``
changes; ``devicepage`` holds the widgets.

- ``own(found, look)``: each key the file sets for ``look``, validated as the game reads it
  (None: not set, or a value the game would refuse).
- ``words(found, look)``: what the game will use (``[device.<look>]`` over the engine's
  words, ``kits.device_words``); ``default_look(found)``: the game's own device (the kit's,
  else a phone) and ``default_note(found)`` the words that mark it.
- ``palette(found, look)``: the look's colors (``core/devicelooks``) from the scheme in use,
  an imported palette's roles and the author's own ``[theme]`` colors, as the game reads
  them.
- ``preview(found, look)``: what a card's preview draws (``DevicePreview``); Database ▸
  Contacts passes a contact's own message.
- ``changes(look, key, value)``: the ``tomlpatch`` change for one key (None or blank:
  remove it).

Pure Python: ``core`` and its own package; no Tk (ADR-0008).
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields as dc_fields
from types import SimpleNamespace
from typing import Final

from engine.core.config_schema import (
    DEVICE_SECTION,
    DeviceTable,
    ThemeConfig,
    ValueProblem,
    config_fields,
)
from engine.core.devicelooks import DevicePalette, device_palette
from engine.core.kits import DEVICE_LOOKS, KITS, DeviceWords, arrive_text, device_look, \
    device_words
from engine.core.schemes import DEFAULT_SCHEME, SCHEMES, custom_colors, scheme_colors
from engine.tools.editor import kitmodel as km
from engine.tools.editor import schememodel as scm

KEYS: Final = ("name", "arrive_text", "arrive_sound", "header_text", "reading")
INTRO: Final = ("How each device words and sounds a message: a phone buzzes, a pigeon lands "
                "on the sill. A message comes by its contact's device unless the send line "
                "says another (send invite from hana on pigeon).")
LABELS: Final = {"name": "Name", "arrive_text": "Arrival notice",
                 "arrive_sound": "Arrival sound", "header_text": "Line above each message",
                 "reading": "Reads as"}
HINTS: Final = {
    "name": "Shown on the Inbox button and page when this is the game's device.",
    "arrive_text": "Shown when a message arrives. {name} is who sent it.",
    "arrive_sound": "Plays once when a message arrives, at the sound volume.",
    "header_text": "Above each message in the Inbox, before its day.",
    "reading": "A letter shows the sender's lines as one signed letter.",
}
ENGINE: Final = "Not set: {text}"
READING_DEFAULT: Final = "Its own: {label}"
READINGS: Final = {"letter": "A signed letter", "chat": "Chat lines"}
GAME_DEVICE: Final = "The game's device"
GAME_DEVICE_KIT: Final = "The game's device (from the {kit} kit)"
GAME_DEVICE_NOTE: Final = "Messages and contacts with no device of their own come by this."
SAMPLE_FROM: Final = "Hana"
SAMPLE_DAY: Final = "Day 3"
SAMPLE_LETTER: Final = ("Meet me at the bridge when the lanterns are lit.",
                        "Bring the red one.")
SAMPLE_REPLY: Final = "I'll be there."
SAMPLE_ME: Final = "You"
LOOK_NAMES: Final = {look: device_words(look).name for look in DEVICE_LOOKS}


def section(look: str) -> str:
    return f"{DEVICE_SECTION}.{look}"


def own(found: Mapping[str, object], look: str) -> dict[str, object | None]:
    """Each key the file sets for ``look``, as the game reads it (None: not set or
    refused)."""
    out: dict[str, object | None] = {}
    for key, field_ in config_fields(DeviceTable).items():
        if key not in KEYS:
            continue
        value = found.get(f"{section(look)}.{key}")
        try:
            out[key] = None if value is None else field_.metadata["validator"].check(value)
        except ValueProblem:
            out[key] = None
    return out


def _config(found: Mapping[str, object]) -> SimpleNamespace:
    kit = found.get(km.PATH)
    tables = {look: DeviceTable(**{k: v for k, v in own(found, look).items()})
              for look in DEVICE_LOOKS}
    return SimpleNamespace(theme=SimpleNamespace(kit=kit if isinstance(kit, str) else None),
                           device=tables)


def words(found: Mapping[str, object], look: str) -> DeviceWords:
    """What the game will use for ``look`` with the text ``found`` was read from."""
    return device_words(look, _config(found))


def default_look(found: Mapping[str, object]) -> str:
    """The game's own device: the kit's, else a phone."""
    return device_look(_config(found))


def default_note(found: Mapping[str, object]) -> str:
    """The words that mark the game's device ("The game's device (from the Fantasy kit)")."""
    kit = found.get(km.PATH)
    if isinstance(kit, str) and kit in KITS:
        return GAME_DEVICE_KIT.format(kit=KITS[kit].name)
    return GAME_DEVICE


def engine_text(look: str, key: str) -> str:
    """The engine's own value of ``key`` for ``look``, as a field's hint shows it."""
    plain = device_words(look)
    if key == "reading":
        return READING_DEFAULT.format(label=reading_label(plain.letter))
    text = {"name": plain.name, "arrive_text": plain.arrive, "header_text": plain.via,
            "arrive_sound": "no sound"}[key]
    return ENGINE.format(text=text if key == "arrive_sound" else f"“{text}”")


def reading_label(letter: bool) -> str:
    return READINGS["letter" if letter else "chat"]


def reading_choices(look: str) -> list[tuple[object, str]]:
    """The Reads as choices: the device's own first (None), then each reading."""
    return [(None, READING_DEFAULT.format(label=reading_label(device_words(look).letter))),
            *READINGS.items()]


def changes(look: str, key: str, value: object) -> tuple[tuple[str, str, object], ...]:
    """The change that sets ``[device.<look>] key`` (None or blank: removes it)."""
    if isinstance(value, str):
        value = value.strip() or None
    return ((section(look), key, value),)


# --- Colors and the preview --------------------------------------------------------------------

def _theme_defaults() -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(path: str, node: object) -> None:
        for f in dc_fields(node):                                      # type: ignore[arg-type]
            value = getattr(node, f.name)
            key = f"{path}.{f.name}" if path else f.name
            if hasattr(value, "__dataclass_fields__"):
                walk(key, value)
            elif isinstance(value, tuple) and len(value) == 3 and all(
                    isinstance(c, int) for c in value):
                out[key] = "#{:02X}{:02X}{:02X}".format(*value)
    walk("", ThemeConfig())
    return out


_DEFAULTS: Final = _theme_defaults()


def token_of(found: Mapping[str, object]):
    """A ``core/devicelooks.Token`` as the game would read ``[theme]``: the author's own
    color, else the scheme's (an imported palette's roles over it), else the engine's."""
    value = found.get(scm.PATH)
    base = value if isinstance(value, str) and value in SCHEMES else DEFAULT_SCHEME
    roles = scm.custom_roles(found)
    colors = custom_colors(base, roles) if roles else scheme_colors(base)

    def token(path: str) -> str:
        mine = found.get(f"theme.{path}")
        if isinstance(mine, str) and len(mine) == 7 and mine.startswith("#"):
            return mine.upper()
        return colors.get(path) or _DEFAULTS[path]
    return token


def palette(found: Mapping[str, object], look: str) -> DevicePalette:
    return device_palette(look, token_of(found))


@dataclass(frozen=True, slots=True)
class DevicePreview:
    """What a card's preview draws: the ``notice`` text, the ``header`` line above the
    message, the ``lines`` ((name, text): name "" for a letter's plain lines), the
    ``signature`` ("" for chat lines), the ``colors``, and whether a ``sound`` is set."""

    look: str
    notice: str
    header: str
    lines: tuple[tuple[str, str], ...]
    signature: str
    colors: DevicePalette
    sound: str | None


def preview(found: Mapping[str, object], look: str, sender: str = SAMPLE_FROM,
            lines: tuple[tuple[str, str], ...] | None = None, day: str = SAMPLE_DAY
            ) -> DevicePreview:
    """What ``look`` draws: a sample message from Hana, or (Database ▸ Contacts) the
    ``lines`` of a message from ``sender``, each ``(name, text)``: name ``SAMPLE_ME`` for
    the player's own, "" for a letter's plain lines."""
    said = words(found, look)
    header = f"{said.via} · {day}" if day else said.via
    if lines is None:
        lines = tuple(("", text) for text in SAMPLE_LETTER) if said.letter else (
            (SAMPLE_FROM, SAMPLE_LETTER[0]), (SAMPLE_ME, SAMPLE_REPLY))
    signature = f"— {sender}" if said.letter and lines else ""
    return DevicePreview(look, arrive_text(said, sender), header, lines, signature,
                         palette(found, look), said.sound)


__all__ = ["DevicePreview", "ENGINE", "GAME_DEVICE", "GAME_DEVICE_NOTE", "HINTS", "INTRO",
           "KEYS", "LABELS", "LOOK_NAMES", "SAMPLE_ME", "changes", "default_look", "default_note",
           "engine_text", "own", "palette", "preview", "reading_choices", "reading_label",
           "section", "token_of", "words"]
