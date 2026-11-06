"""The built-in color schemes (F49 SPEC §3.1, §3.2): one registry that config and Studio read.

Why this module exists: an author picks a whole look with one ``[theme] preset = "<id>"``
line (or a ``[style.<name>.theme] preset``). A scheme is a few role colors (fill, text,
border, accent, …); ``ROLE_TOKENS`` says which theme color tokens each role sets. Config
lays a scheme's colors *under* the author's own keys (``config._with_scheme``), Studio's
Color scheme page draws its cards from ``SCHEMES``, and W67 names a scheme its colors came
from (``app/ui_contrast``). A new scheme is one more row in ``SCHEMES`` (PR-F49-01).

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
    # 2026-11-05: themes across genres, each from five picked colors (fill, text, accent,
    # accent2, border) completed by ``palette.complete_roles``, so every one meets W67.
    _scheme("neon_vice", "Neon Vice",
            "#1A1033 #FFFFFF #7A3E9D #FF72B5 #2DE2E6 #351840 #511F4E #6C275B #AFABB8 #433B58 "
            "#FFA3CF"),
    _scheme("high_fantasy", "High Fantasy",
            "#F4E8CC #1A1108 #C9A86A #1F4E8C #785707 #EDDCB5 #E6D09E #DEC587 #615749 #CDC1A9 "
            "#1D395E"),
    _scheme("grimdark", "Grimdark",
            "#16130F #F9F8F6 #4A4036 #CC9384 #968C7C #271811 #381C13 #492115 #AAA8A5 #3F3C39 "
            "#DCB6AC"),
    _scheme("gothic", "Gothic Velvet",
            "#140A16 #F0E9F4 #4B2550 #D47F93 #997AB8 #270C1A #390D1F #4C0F23 #A39BA6 #3C323E "
            "#DEA4B5"),
    _scheme("noir", "Black and White",
            "#000000 #FFFFFF #6B6B6B #FFFFFF #BDBDBD #171717 #2E2E2E #454545 #A6A6A6 #2E2E2E "
            "#FFFFFF"),
    _scheme("paper", "Ink on Paper",
            "#FFFFFF #000000 #9E9E9E #111111 #484848 #E2E2E2 #C6C6C6 #A9A9A9 #505050 #D1D1D1 "
            "#0B0B0B"),
    _scheme("blood_moon", "Blood Moon",
            "#0E0505 #F8F0F0 #5C1515 #E9666D #FF8A3D #27090A #400C0F #5A1014 #A69E9E #382F2F "
            "#EE969B"),
    _scheme("cyberpunk", "Cyberpunk",
            "#0B0F1A #FFFFFF #1F4E5F #FCEE0A #00E5FF #0A2935 #084251 #075C6C #AAABAF #373A43 "
            "#FDF460"),
    _scheme("rose_garden", "Rose Garden",
            "#FFF7F3 #1D0F13 #E8B4BF #9C2148 #43683F #F8E4E4 #F0D1D6 #E9BDC7 #675B5C #D6CDCB "
            "#701B35"),
    _scheme("starship", "Starship Console",
            "#0D1B2A #FFFFFF #274C77 #4CC9F0 #FB9DC8 #153042 #1C455A #245A71 #AAAFB4 #394450 "
            "#8BDCF5"),
    _scheme("brass", "Brass and Steam",
            "#2A1E14 #FFFFFF #6B4E2E #DCB36E #9EC4C2 #3E2E1B #533E21 #674E28 #B4B0AD #50463E "
            "#E8CEA1"),
    _scheme("seaside", "Seaside",
            "#F1F8F7 #040E11 #9FD3D0 #0A5D64 #864939 #D6E9E9 #BBDADC #9FCBCE #535B5D #C6CECE "
            "#084147"),
    _scheme("enchanted_forest", "Enchanted Forest",
            "#0F1F17 #FFFFFF #2E5641 #DBB853 #85CBAD #1C3329 #2A483A #375C4C #ABB1AE #3A4741 "
            "#E8D18F"),
    _scheme("frost", "Frostbite",
            "#EEF5FB #040B13 #B9D3EA #265791 #6248A0 #D7E5F3 #C0D4EA #A9C4E2 #52585F #C4CBD1 "
            "#1A3C65"),
    _scheme("harvest", "Harvest Moon",
            "#FBF0DF #090503 #E2B77F #873E14 #505F20 #F2DDC7 #EACAB0 #E1B798 #5E5750 #CFC6B7 "
            "#5B2A0E"),
    _scheme("royal", "Royal Court",
            "#101833 #FFFFFF #3A4A80 #E3B341 #9AB1EA #1F2949 #2E3B5E #3E4C74 #ABAEB8 #3B4258 "
            "#EDCE84"),
    _scheme("sepia", "Old Photograph",
            "#EFE3CF #000000 #C4AE8C #684224 #475044 #E1D1BB #D3BFA7 #C5AD94 #544F48 #C4BAAA "
            "#442B17"),
    _scheme("cotton_candy", "Cotton Candy",
            "#FFF5FB #0C080F #F5B8D8 #9B2B65 #235F8A #F8DEEC #F0C7DD #E9B0CE #5C565D #D3CAD1 "
            "#691F47"),
    _scheme("eldritch", "Eldritch",
            "#0A1514 #FFFFFF #24413C #8BD450 #7BC6BE #192C1B #294322 #385A2A #A9ADAD #363F3E "
            "#B4E38D"),
    _scheme("witching_hour", "Witching Hour",
            "#1B1028 #FFFFFF #4A2E6B #FF8C1A #BA8DFF #2C1C42 #3D275C #4E3375 #AFABB4 #443B4F "
            "#FFB46A"),
    _scheme("wasteland", "Wasteland",
            "#26231A #FFFFFF #55503A #E4A86B #AEB881 #3B2E1C #513A1E #664520 #B3B2AF #4D4B43 "
            "#EDC69F"),
    _scheme("cozy_cafe", "Cozy Café",
            "#F7EFE5 #000000 #D8C0A8 #7E432A #445C50 #EADBCF #DDC7B9 #D0B4A3 #565450 #CBC4BC "
            "#522C1B"),
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
    "text_entry.placeholder_color", "text_entry.caret_color",
    "corner.fill_color", "corner.border_color", "corner.text_color",              # F61
    "corner.accent_color")

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


def custom_colors(base_id: str, roles: Mapping[str, str]) -> Mapping[str, str]:
    """2026-11-05 (``[theme.scheme]``): the token colors of scheme ``base_id`` with
    ``roles`` (role → ``"#RRGGBB"``) in place of its own. A scheme's ``extra`` colors are
    tuned to its roles, so they are left out once any role is replaced."""
    found = SCHEMES[base_id]
    if not roles:
        return scheme_colors(base_id)
    merged = {**found.colors, **{r: v for r, v in roles.items() if r in found.colors}}
    return MappingProxyType({path: merged[role] for role, paths in ROLE_TOKENS.items()
                             for path in paths})


__all__ = ["DEFAULT_SCHEME", "custom_colors", "FOLLOWING_TOKENS", "NEUTRAL_TOKENS", "ROLES", "ROLE_TOKENS",
           "SCHEMES", "Scheme", "scheme", "scheme_colors", "scheme_ids"]
