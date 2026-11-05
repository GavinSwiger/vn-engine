"""Studio's Color scheme page, the pure half (F49 SPEC §4; PR-F49-06, 07; AC-F49-09).

Why this module exists: an author picks one of the built-in color schemes
(``engine.core.schemes``) with a click instead of writing ``[theme] preset``. This module
reads the open ``config.toml``'s values (``settingsmodel.values``) and says what the page
shows and writes; the Tk card grid is ``schemecards``, the page ``settingsview``.

- ``cards()``: one ``Card`` per scheme, in registry order, with its four swatches (fill,
  border, accent, text).
- ``in_use(found)``: the scheme the game uses (Sakura with no ``preset``; None for an id
  this version doesn't have, whose text is ``unknown_text``).
- ``custom_colors(found)`` / ``clear_changes(found)``: the ``[theme]`` colors the author
  set that a scheme would set (mapped or following tokens; not ``theme.plugin``, neutral
  tokens or a style's keys), and the changes that remove them (one ``tomlpatch`` plan).
- ``apply_changes(id, found)`` / ``preview_text(text, id, found)``: the ``preset`` line
  (and, 2026-11-05, the removal of an imported palette's ``[theme.scheme]`` keys, which
  would hide it), and the open text with them planned (the preview still's config; other
  unsaved edits stay).
- 2026-11-05, imported palettes: ``custom_card(found)`` is the "Your palette" card first
  in the grid while ``[theme.scheme]`` sets a role (``CUSTOM`` is its id, the one in use);
  ``import_changes(roles, name)`` writes the eleven roles and the palette's name.

Pure Python: ``core`` and this package's pure modules only; no Tk, no pygame (ADR-0008).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from engine.core.redact import echo
from engine.core.schemes import DEFAULT_SCHEME, FOLLOWING_TOKENS, ROLE_TOKENS, ROLES, SCHEMES
from engine.tools.editor import tomlpatch
from engine.tools.editor.scriptedit import Refuse, apply_lines

# --- Texts (SPEC §4, final; D3: "color") ------------------------------------------------------

TITLE: Final = "Color scheme"
INTRO: Final = ("Built-in colors for every box, menu and button in your game. Fonts, pictures "
                "and sounds stay as they are.")
IN_USE: Final = "In use"
APPLY: Final = "Apply {name}"
NOTE_HEADING: Final = "Custom colors kept"
NOTE_BODY: Final = "{n} colors you set yourself still show over the scheme."
NOTE_BODY_ONE: Final = "1 color you set yourself still shows over the scheme."
CLEAR: Final = "Clear my colors"
CONFIRM: Final = ("Remove the {n} colors you set yourself, so the scheme shows everywhere? "
                  "Ctrl+Z in config.toml brings them back.")
CONFIRM_ONE: Final = ("Remove the 1 color you set yourself, so the scheme shows everywhere? "
                      "Ctrl+Z in config.toml brings it back.")
CONFIRM_BUTTONS: Final = ("Remove", "Cancel")
UNKNOWN: Final = ("config.toml asks for a color scheme this version doesn't have (\"{id}\"), "
                  "so the default colors show. Pick one and press Apply.")
# 2026-11-05: Import palette (the dialog is ``paletteimport``).
CUSTOM: Final = "theme.scheme"            # the "Your palette" card's id
CUSTOM_NAME: Final = "Your palette"
IMPORT: Final = "Import palette…"
SCHEME_SECTION: Final = "theme.scheme"
PREVIEW_NOTE: Final = ("A still of the text box with the picked scheme and your other unsaved "
                       "changes.")

SECTION: Final = "theme"
KEY: Final = "preset"
PATH: Final = f"{SECTION}.{KEY}"

# The ``[theme]`` color tokens a scheme sets or that follow one (§3.2), as dotted paths
# under ``theme``; a key the author sets here hides the scheme's color.
_SCHEME_TOKENS: Final = frozenset(
    {f"{SECTION}.{path}" for paths in ROLE_TOKENS.values() for path in paths}
    | {f"{SECTION}.{path}" for path in FOLLOWING_TOKENS})


@dataclass(frozen=True, slots=True)
class Card:
    """One scheme's card: ``id`` (the ``preset`` value), ``name``, and ``swatches``, its
    fill, border, accent and text colors (``"#RRGGBB"``) in that order."""

    id: str
    name: str
    swatches: tuple[str, str, str, str]


def cards(found: Mapping[str, object] | None = None) -> tuple[Card, ...]:
    """Every scheme's card, in registry order (§3.1), after "Your palette" when ``found``
    has an imported one (``custom_card``)."""
    mine = custom_card(found) if found is not None else None
    return ((mine,) if mine is not None else ()) + tuple(
        Card(s.id, s.name, (s.colors["fill"], s.colors["border"], s.colors["accent"],
                            s.colors["text"])) for s in SCHEMES.values())


def custom_roles(found: Mapping[str, object]) -> dict[str, str]:
    """``[theme.scheme]``'s role colors that ``found`` sets (role → ``"#RRGGBB"``)."""
    out = {}
    for role in ROLES:
        value = found.get(f"{SCHEME_SECTION}.{role}")
        if isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            out[role] = value.upper()
    return out


def custom_card(found: Mapping[str, object]) -> Card | None:
    """The "Your palette" card (its ``name``, else ``CUSTOM_NAME``), with the preset's
    roles where the palette sets none; None without one."""
    roles = custom_roles(found)
    if not roles:
        return None
    base = found.get(PATH)
    scheme = SCHEMES.get(base if isinstance(base, str) else DEFAULT_SCHEME,
                         SCHEMES[DEFAULT_SCHEME])
    colors = {**scheme.colors, **roles}
    name = found.get(f"{SCHEME_SECTION}.name")
    return Card(CUSTOM, name if isinstance(name, str) and name.strip() else CUSTOM_NAME,
                (colors["fill"], colors["border"], colors["accent"], colors["text"]))


def in_use(found: Mapping[str, object]) -> str | None:
    """The id of the scheme ``found`` (``settingsmodel.values``) uses: its ``[theme] preset``,
    ``DEFAULT_SCHEME`` when it has none, None when the value isn't a scheme id."""
    if custom_roles(found):
        return CUSTOM
    value = found.get(PATH)
    if value is None:
        return DEFAULT_SCHEME
    return value if isinstance(value, str) and value in SCHEMES else None


def unknown_text(found: Mapping[str, object]) -> str | None:
    """The unknown-id text when ``[theme] preset`` names no scheme, else None. The author's
    value is shown through ``echo()`` (07 I-4)."""
    value = found.get(PATH)
    if value is None or isinstance(value, str) and value in SCHEMES:
        return None
    return UNKNOWN.format(id=echo(value if isinstance(value, str) else str(value)))


def custom_colors(found: Mapping[str, object]) -> tuple[str, ...]:
    """The dotted paths of the ``[theme]`` colors ``found`` sets that show over a scheme
    (mapped or following tokens), in file order."""
    return tuple(path for path in found if path in _SCHEME_TOKENS)


def note_body(count: int) -> str:
    """The Custom colors kept note's body for ``count`` colors."""
    return NOTE_BODY_ONE if count == 1 else NOTE_BODY.format(n=count)


def confirm_text(count: int) -> str:
    """Clear my colors' question for ``count`` colors."""
    return CONFIRM_ONE if count == 1 else CONFIRM.format(n=count)


def clear_changes(found: Mapping[str, object]) -> tuple[tuple[str, str, None], ...]:
    """The ``tomlpatch.plan_changes`` changes that remove every ``custom_colors`` key."""
    out = []
    for path in custom_colors(found):
        section, _, key = path.rpartition(".")
        out.append((section, key, None))
    return tuple(out)


def apply_change(id_: str) -> tuple[str, str, str]:
    """The one ``(section, key, value)`` that picks scheme ``id_``."""
    return SECTION, KEY, id_


def apply_changes(id_: str, found: Mapping[str, object]
                  ) -> tuple[tuple[str, str, str | None], ...]:
    """The changes that show built-in scheme ``id_``: its ``preset`` line, and every
    ``[theme.scheme]`` key removed (an imported palette would hide it). Nothing for
    ``CUSTOM``, which is already in use when its card shows."""
    if id_ == CUSTOM:
        return ()
    gone = tuple((SCHEME_SECTION, path.rsplit(".", 1)[1], None) for path in found
                 if path.startswith(SCHEME_SECTION + "."))
    return (apply_change(id_), *gone)


def import_changes(roles: Mapping[str, str], name: str | None
                   ) -> tuple[tuple[str, str, str | None], ...]:
    """The changes that write an imported palette: its name (or none), then each role."""
    clean = " ".join((name or "").split())[:60] or None
    return ((SCHEME_SECTION, "name", clean),
            *((SCHEME_SECTION, role, roles[role]) for role in ROLES))


def preview_text(text: str, id_: str, found: Mapping[str, object] | None = None) -> str:
    """``text`` with scheme ``id_``'s changes (``apply_changes``) planned but not applied
    (``text`` as it is when nothing changes, or when ``tomlpatch`` can't place them)."""
    return planned_text(text, apply_changes(id_, found or {}))


def planned_text(text: str, changes: tuple[tuple[str, str, str | None], ...]) -> str:
    """``text`` with ``changes`` planned but not applied (as it is when it can't be)."""
    plan = tomlpatch.plan_changes(text, changes) if changes else None
    if plan is None or isinstance(plan, Refuse):
        return text
    return "\n".join(apply_lines(text.split("\n"), plan.edits))


__all__ = ["APPLY", "CLEAR", "CONFIRM", "CONFIRM_BUTTONS", "CONFIRM_ONE", "CUSTOM",
           "CUSTOM_NAME", "Card", "IMPORT", "INTRO", "IN_USE", "SCHEME_SECTION",
           "apply_changes", "custom_card", "custom_roles", "import_changes", "planned_text", "KEY", "NOTE_BODY", "NOTE_BODY_ONE", "NOTE_HEADING", "PATH", "PREVIEW_NOTE",
           "SECTION", "TITLE", "UNKNOWN", "apply_change", "cards", "clear_changes",
           "confirm_text", "custom_colors", "in_use", "note_body", "preview_text",
           "unknown_text"]
