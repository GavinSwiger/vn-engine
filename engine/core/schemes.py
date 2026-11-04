"""The built-in color schemes (F49 SPEC §3.1, §3.2): one registry that config and Studio read.

Why this module exists: an author picks a whole look with one ``[theme] preset = "<id>"``
line (or a ``[style.<name>.theme] preset``). A scheme is a few role colors (fill, text,
border, accent, …); ``ROLE_TOKENS`` says which theme color tokens each role sets. Config
lays a scheme's colors *under* the author's own keys (``config._with_scheme``), Studio's
Color scheme page draws its cards from ``SCHEMES``, and W67 names a scheme its colors came
from (``app/ui_contrast``). A seventh scheme is one more row in ``SCHEMES`` (PR-F49-01).

Every color token of ``ThemeConfig`` is in exactly one group (AC-F49-02):

- **mapped** (``ROLE_TOKENS``): set by every scheme;
- **following** (``FOLLOWING_TOKENS``): left unset, so they keep following another token
  (``nvl.*`` the text box, ``notice.*`` the panel, …);
- **neutral** (``NEUTRAL_TOKENS``): never set (a dim stays dark, a flash stays white).

Sakura's ``extra`` colors keep today's engine defaults exactly, so ``preset = "sakura"`` is
the same as no preset (PR-F49-05). The registry is read-only (07 I-7). Pure data, stdlib
only.
"""

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

# The role names, in the §3.1 column order.
ROLES: Final[tuple[str, ...]] = ("fill", "text", "border", "accent", "accent2", "soft",
                                 "focus", "pressed", "muted", "track", "toggle")


@dataclass(frozen=True)
class Scheme:
    """One built-in scheme: ``id`` (the ``preset`` value), its shown ``name``, ``colors``
    (role → ``"#RRGGBB"``, every role of ``ROLES``), and ``extra`` (dotted token path →
    ``"#RRGGBB"``, single tokens that win over the role map). Both mappings are read-only."""
    id: str
    name: str
    colors: Mapping[str, str]
    extra: Mapping[str, str]


def _scheme(id_: str, name: str, values: str, extra: Mapping[str, str] | None = None
            ) -> Scheme:
    colors = values.split()
    assert len(colors) == len(ROLES), id_
    return Scheme(id_, name, MappingProxyType(dict(zip(ROLES, colors))),
                  MappingProxyType(dict(extra or {})))


# §3.1, the user's exact values (D1), in the order Studio shows them. Columns as ``ROLES``:
#        fill    text    border  accent  accent2 soft    focus   pressed muted   track   toggle
SCHEMES: Final[Mapping[str, Scheme]] = MappingProxyType({s.id: s for s in (
    _scheme("sakura", "Sakura",
            "#FFF4F8 #3D2B36 #F0A0C0 #A02860 #A02860 #FFE6F0 #FFD6E8 #FFC2DC #6E5E68 #C8B8C2 "
            "#7E5C74", {
                "toggle.on.knob_color": "#FFFFFF",
                "save.newest.text_color": "#FFFFFF",
                "flowchart.fill_color": "#FFFAFC",
                "chapter.fill_color": "#2A1E26",
                "chapter.heading.text_color": "#F0A0C0",
                "chapter.title.text_color": "#FFF4F8",
                "save.placeholder.fill_color": "#F0D0DE",
                "list.scrollbar_track_color": "#F0D0DE",
            }),
    _scheme("pocket", "Pocket LCD",
            "#9BBC0F #0F380F #306230 #0F380F #0F380F #8BAC0F #C4D96A #8BAC0F #244A24 #8BAC0F "
            "#306230"),
    _scheme("amber", "Amber Terminal",
            "#140C02 #FFB000 #9A6800 #FFCC00 #FFCC00 #2A1A04 #3A2604 #4A3006 #B07A14 #3A2604 "
            "#9A6800"),
    _scheme("synthwave", "Synthwave Sunset",
            "#262335 #F2E9FF #CA7CD8 #FF68A8 #64CFF7 #34294F #3D2E5C #4A3570 #9A90B4 #4A3F66 "
            "#5A4A7A"),
    _scheme("vaporwave", "Vaporwave Dream",
            "#FBE6F8 #3A2B5C #9F63C4 #674AB3 #137566 #C6F5F2 #C6F5F2 #A8EDE6 #6E5E82 #D8C8E8 "
            "#9F63C4"),
    _scheme("groovy", "Groovy '70s",
            "#F3E6C8 #3B2416 #D08A1E #9E3A12 #2F6F6A #F2D49B #F2D49B #E8C07A #6E5848 #D9C9A8 "
            "#8A6A4A"),
)})

DEFAULT_SCHEME: Final = "sakura"           # the look with no preset (Studio's "In use")

# §3.2: role → the theme color tokens it sets (dotted paths under ``[theme]``).
ROLE_TOKENS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    "fill": ("textbox.fill_color", "panel.fill_color", "button.fill_color",
             "choice.fill_color", "quick_menu.fill_color", "save.badge.fill_color",
             "slider.thumb_border_color", "title.fill_top_color", "toggle.on.knob_color",
             "save.newest.text_color", "flowchart.fill_color", "chapter.fill_color"),
    "text": ("textbox.text_color", "panel.text_color", "button.text_color",
             "choice.text_color", "quick_menu.text_color", "save.badge.text_color",
             "save.placeholder.text_color", "chapter.title.text_color"),
    "border": ("textbox.border_color", "panel.border_color", "button.border_color",
               "choice.border_color", "list.divider_color", "rollback.mark.border_color"),
    "accent": ("textbox.name_tab.text_color", "textbox.indicator.fill_color",
               "choice.marker.fill_color", "button.marker.fill_color",
               "panel.heading.text_color", "toggle.on.track_color", "slider.fill_color",
               "slider.thumb_color", "list.scrollbar_color", "title.logo.text_color",
               "quick_menu.focused.text_color", "quick_menu.on.border_color",
               "save.newest.fill_color", "rollback.mark.glyph_color",
               "chapter.heading.text_color"),
    "accent2": ("button.focused.border_color", "choice.focused.border_color"),
    "soft": ("textbox.name_tab.fill_color", "rollback.mark.fill_color",
             "flowchart.node.fill_color", "save.placeholder.fill_color"),
    "focus": ("button.focused.fill_color", "choice.focused.fill_color",
              "title.fill_bottom_color", "quick_menu.pressed.fill_color",
              "quick_menu.on.fill_color"),
    "pressed": ("button.pressed.fill_color",),
    "muted": ("choice.locked.text_color", "button.disabled.text_color",
              "list.empty.text_color", "title.version.text_color",
              "quick_menu.disabled.text_color"),
    "track": ("button.disabled.track_color", "list.scrollbar_track_color"),
    "toggle": ("toggle.track_color", "slider.track_color", "flowchart.node.border_color",
               "flowchart.edge.line_color"),
})

# Tokens left unset so they keep following another token (their default is None).
FOLLOWING_TOKENS: Final[tuple[str, ...]] = (
    "nvl.fill_color", "nvl.text_color", "nvl.name.text_color", "nvl.indicator.fill_color",
    "notice.fill_color", "notice.border_color", "notice.text_color",
    "notice.marker.fill_color", "codex.new.fill_color", "codex.locked.text_color",
    "flowchart.node.text_color", "flowchart.gate.fill_color",
    "flowchart.unknown.text_color", "flowchart.path.line_color",
    "flowchart.here.fill_color", "flowchart.here.text_color",
    "minigame.fill_top_color", "minigame.fill_bottom_color",
    "choice.timer.fill_color", "choice.timer.track_color",          # F51 (C1)
    "text_entry.fill_color", "text_entry.border_color", "text_entry.text_color",   # F52
    "text_entry.placeholder_color", "text_entry.caret_color")

# Tokens no scheme sets.
NEUTRAL_TOKENS: Final[tuple[str, ...]] = (
    "stage.empty_color", "effects.flash_color", "effects.fade_color",
    "gallery.viewer.fill_color", "menu.dim_color", "title.loading.text_color")


def scheme_ids() -> tuple[str, ...]:
    """The scheme ids in registry order (``SchemeName``'s options)."""
    return tuple(SCHEMES)


def scheme(id_: str) -> Scheme | None:
    """The scheme with id ``id_`` (case-sensitive), or None."""
    return SCHEMES.get(id_)


@functools.cache
def scheme_colors(id_: str) -> Mapping[str, str]:
    """Dotted token path → ``"#RRGGBB"`` for every token scheme ``id_`` sets: the role map
    first, then its extras over it (read-only). An unknown id is a ``KeyError``."""
    found = SCHEMES[id_]
    colors = {path: found.colors[role] for role, paths in ROLE_TOKENS.items()
              for path in paths}
    colors.update(found.extra)
    return MappingProxyType(colors)


__all__ = ["DEFAULT_SCHEME", "FOLLOWING_TOKENS", "NEUTRAL_TOKENS", "ROLES", "ROLE_TOKENS",
           "SCHEMES", "Scheme", "scheme", "scheme_colors", "scheme_ids"]
