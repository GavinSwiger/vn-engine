"""Studio's Kit page, the pure half (F60; specs/F60-genre-kits/SPEC.md).

Why this module exists: an author dresses the whole game for a genre with one click instead
of writing ``[theme] kit``. This module reads the open ``config.toml``'s values
(``settingsmodel.values``) and says what the page shows and writes; the card grid is
``kitcards``, the page's widgets ``kitpage``.

- ``cards(found)``: "No kit" first, then one ``KitCard`` per kit with what its small
  preview draws (its scheme's colors, its meter look and corner, its first meter's label).
- ``in_use(found)`` / ``unknown_text(found)``: the kit the game uses (``NONE`` without one;
  None for an id this version doesn't have, whose note is ``unknown_text``).
- ``details(id)``: the picked card's blurb and what it sets, as lines.
- ``scheme_offer(id, found)``: the "Also use its color scheme" option's text, and whether
  it starts ticked and can be changed.
- ``apply_changes(id, with_scheme, found)``: the ``tomlpatch.plan_changes`` changes that
  pick a kit (``[theme] kit``) and, when asked, its scheme (``schememodel.apply_changes``),
  one undo step.

Pure Python: ``core`` and this package's pure modules only; no Tk, no pygame (ADR-0008).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from engine.core.kits import KITS
from engine.core.redact import echo
from engine.core.schemes import DEFAULT_SCHEME, SCHEMES
from engine.core.skins import DEFAULT_CORNER_PLACE, DEFAULT_METER_LOOK
from engine.tools.editor import schememodel as scm

# --- Texts ------------------------------------------------------------------------------------

TITLE: Final = "Kit"
INTRO: Final = ("Dress your game for its genre in one go: how meters look and where they "
                "sit, the meters it suggests, and a color scheme to match. Anything you set "
                "yourself still wins.")
NONE: Final = ""                              # the "No kit" card's id
NONE_NAME: Final = "No kit"
NONE_BLURB: Final = "The engine's plain defaults, for any genre."
NONE_SETS: Final = "Meters you show appear as bars in the top-left corner."
IN_USE: Final = scm.IN_USE
APPLY: Final = "Apply {name}"
REMOVE: Final = "Use no kit"
ALSO_SCHEME: Final = "Also use its color scheme ({name})"
SCHEME_IN_USE: Final = "Its color scheme ({name}) is already in use"
SETS: Final = "Meters you show appear as {look} in the {place} corner."
SUGGESTS: Final = "Suggested meters: {meters}."
UNKNOWN: Final = ("config.toml asks for a kit this version doesn't have (\"{id}\"), so the "
                  "game uses no kit. Pick one and press Apply.")

LOOK_WORDS: Final[Mapping[str, str]] = {
    "bar": "bars", "number": "numbers", "hearts": "hearts", "pips": "pips", "dial": "dials"}
PLACE_WORDS: Final[Mapping[str, str]] = {
    "top_left": "top-left", "top_right": "top-right", "bottom_left": "bottom-left",
    "bottom_right": "bottom-right"}

SECTION: Final = "theme"
KEY: Final = "kit"
PATH: Final = f"{SECTION}.{KEY}"


@dataclass(frozen=True, slots=True)
class KitCard:
    """One card: ``id`` (the ``kit`` value; ``NONE`` for "No kit"), ``name``, ``colors``
    (fill, text, border, accent, soft, track as ``"#RRGGBB"``), and the preview's meter:
    ``look``, ``place`` and ``label`` ("" draws no label)."""

    id: str
    name: str
    colors: tuple[str, str, str, str, str, str]
    look: str
    place: str
    label: str


def _colors(roles: Mapping[str, str]) -> tuple[str, str, str, str, str, str]:
    return (roles["fill"], roles["text"], roles["border"], roles["accent"], roles["soft"],
            roles["track"])


def _scheme_now(found: Mapping[str, object]) -> Mapping[str, str]:
    """The role colors the game uses now (its preset over Sakura, an imported palette's
    roles over that): "No kit" keeps them, so its card shows them."""
    value = found.get(scm.PATH)
    base = SCHEMES.get(value if isinstance(value, str) else DEFAULT_SCHEME,
                       SCHEMES[DEFAULT_SCHEME])
    return {**base.colors, **scm.custom_roles(found)}


def cards(found: Mapping[str, object] | None = None) -> tuple[KitCard, ...]:
    """"No kit", then every kit in registry order."""
    plain = KitCard(NONE, NONE_NAME, _colors(_scheme_now(found or {})), DEFAULT_METER_LOOK,
                    DEFAULT_CORNER_PLACE, "")
    return (plain, *(KitCard(k.id, k.name, _colors(SCHEMES[k.scheme].colors), k.meters.look,
                             k.meters.place, k.meters.suggestions[0].label)
                     for k in KITS.values()))


def in_use(found: Mapping[str, object]) -> str | None:
    """The kit ``found`` uses: its ``[theme] kit``, ``NONE`` without one, None when the value
    names no kit."""
    value = found.get(PATH)
    if value is None:
        return NONE
    return value if isinstance(value, str) and value in KITS else None


def unknown_text(found: Mapping[str, object]) -> str | None:
    """The unknown-id note when ``[theme] kit`` names no kit, else None (the author's value
    through ``echo()``)."""
    if in_use(found) is not None:
        return None
    value = found.get(PATH)
    return UNKNOWN.format(id=echo(value if isinstance(value, str) else str(value)))


def name_of(id_: str) -> str:
    return NONE_NAME if id_ == NONE else KITS[id_].name


def details(id_: str) -> tuple[str, ...]:
    """The picked card's blurb, then what it sets, one line each."""
    if id_ == NONE:
        return NONE_BLURB, NONE_SETS
    found = KITS[id_]
    meters = ", ".join(
        f"{s.label} {s.low}–{s.high}"
        + (f" ({', '.join(label for label, _ in s.ranks)})" if s.ranks else "")
        for s in found.meters.suggestions)
    return (found.blurb,
            SETS.format(look=LOOK_WORDS[found.meters.look],
                        place=PLACE_WORDS[found.meters.place]),
            SUGGESTS.format(meters=meters))


@dataclass(frozen=True, slots=True)
class SchemeOffer:
    """The "Also use its color scheme" option: ``text``, whether it starts ``ticked``, and
    whether the author can change it (``enabled``)."""

    text: str
    ticked: bool
    enabled: bool


def scheme_offer(id_: str, found: Mapping[str, object]) -> SchemeOffer | None:
    """The option for kit ``id_``; None for "No kit" (it has no scheme). It starts ticked,
    except over an imported palette (applying a scheme replaces it); a scheme already in use
    shows ticked and fixed."""
    if id_ == NONE:
        return None
    scheme = SCHEMES[KITS[id_].scheme]
    if scm.in_use(found) == scheme.id:
        return SchemeOffer(SCHEME_IN_USE.format(name=scheme.name), True, False)
    return SchemeOffer(ALSO_SCHEME.format(name=scheme.name),
                       scm.in_use(found) != scm.CUSTOM, True)


def apply_changes(id_: str, with_scheme: bool, found: Mapping[str, object]
                  ) -> tuple[tuple[str, str, str | None], ...]:
    """The changes that pick kit ``id_`` (``NONE`` removes the line) and, with
    ``with_scheme``, its color scheme; only what differs from ``found``."""
    out: list[tuple[str, str, str | None]] = []
    if in_use(found) != id_:
        out.append((SECTION, KEY, id_ or None))
    if with_scheme and id_ != NONE:
        scheme = KITS[id_].scheme
        if scm.in_use(found) != scheme:
            out.extend(scm.apply_changes(scheme, found))
    return tuple(out)


def apply_text(id_: str) -> str:
    """The Apply button's text."""
    if id_ == NONE:
        return REMOVE
    return APPLY.format(name=name_of(id_))


__all__ = ["ALSO_SCHEME", "APPLY", "INTRO", "IN_USE", "KEY", "KitCard", "NONE", "NONE_NAME",
           "PATH", "REMOVE", "SECTION", "SchemeOffer", "TITLE", "UNKNOWN", "apply_changes",
           "apply_text", "cards", "details", "in_use", "name_of", "scheme_offer",
           "unknown_text"]
