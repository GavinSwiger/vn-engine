"""W67: the UI theme's contrast pairs, checked in dev runs (F10 ``04`` §7.10 step 5).

Why this module exists: an author's ``[theme.*]`` colors can make menu text or focus marks
hard to see. UI-F10-17 lists the pairs F10 draws; ``PAIRS`` holds them, and in dev runs
``install_ui`` logs one W67 (area ``ui``) for each pair under its minimum (4.5:1 text, 3:1
headings, title text, and graphics). A translucent fill is composited over pure black and
pure white with F05's contrast function (``app/text_check``; ``ui`` can't import ``app``, so
the check lives here) and the worse backdrop is named. A pair whose background is drawn from
a usable ``frame_image`` (or a logo or title picture) isn't checked. AC-F10-17 measures the
defaults with ``pair_ratios``.

The message forms are 03-ui's two W67 examples; the opaque and black-screen forms and every
"needs at least" noun are drafted here for the narrative designer's review.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from engine.app.text_check import BLACK, WHITE, composite, contrast_ratio, relative_luminance
from engine.core.config_schema import ThemeConfig
from engine.core.logsetup import get_logger
from engine.ui.builtin.flowchart_page import FOLLOWS, flow_color
from engine.ui.theme import UiTheme

_log = get_logger("ui")

RGB = tuple[int, int, int]
TEXT: Final = 4.5
LARGE: Final = 3.0                 # headings, title text, and graphics
LOADING_SCREEN: Final = ""         # ``Pair.bg`` of the loading text: the black launch canvas


def _always(theme: UiTheme) -> bool:
    return True


def _plain(*names: str) -> Callable[[UiTheme], bool]:
    """Drawn while any of these looks has no usable frame image."""
    return lambda theme: any(theme.frames.get(name) is None for name in names)


def _gradient(theme: UiTheme) -> bool:
    return theme.logo is None and theme.background is None


def _backing(theme: UiTheme) -> bool:
    return theme.logo is None and theme.background is not None and \
        theme.frames.get("panel") is None


@dataclass(frozen=True)
class Pair:
    """``fg`` drawn on ``bg`` (token paths under ``[theme]``), ``bg`` at the ``opacity``
    token (None: opaque). ``needs`` ends the message ("button text needs"); ``drawn`` says
    whether the pair is drawn without a picture under it."""
    fg: str
    bg: str
    opacity: str | None
    minimum: float
    needs: str
    drawn: Callable[[UiTheme], bool] = _always


_BUTTON = "button.fill_opacity"
_PANEL = "panel.fill_opacity"
_QUICK = "quick_menu.fill_opacity"
_FOCUSED = "button.focused.fill_color"

# UI-F10-17's pairs. Rows (toggle, slider, list) draw the button's focused fill and outline
# with no frame image, so the marker, outline, and track pairs on it are always checked.
PAIRS: Final[tuple[Pair, ...]] = (
    Pair("button.text_color", "button.fill_color", _BUTTON, TEXT, "button text needs",
         _plain("button")),
    Pair("button.text_color", _FOCUSED, _BUTTON, TEXT, "button text needs",
         _plain("button.focused", "button.selected")),
    Pair("button.text_color", "button.pressed.fill_color", _BUTTON, TEXT, "button text needs",
         _plain("button.pressed")),
    Pair("button.disabled.text_color", "button.fill_color", _BUTTON, TEXT,
         "button text needs", _plain("button.disabled")),
    Pair("button.marker.fill_color", _FOCUSED, _BUTTON, LARGE, "markers need"),
    Pair("button.marker.fill_color", "button.pressed.fill_color", _BUTTON, LARGE,
         "markers need"),
    Pair("button.focused.border_color", _FOCUSED, _BUTTON, LARGE, "focus outlines need"),
    Pair("button.focused.border_color", "button.pressed.fill_color", _BUTTON, LARGE,
         "focus outlines need"),
    Pair("panel.text_color", "panel.fill_color", _PANEL, TEXT, "panel text needs",
         _plain("panel")),
    Pair("panel.heading.text_color", "panel.fill_color", _PANEL, LARGE, "headings need",
         _plain("panel")),
    Pair("toggle.track_color", "panel.fill_color", _PANEL, LARGE, "tracks need",
         _plain("panel")),
    Pair("slider.track_color", "panel.fill_color", _PANEL, LARGE, "tracks need",
         _plain("panel")),
    Pair("toggle.track_color", _FOCUSED, _BUTTON, LARGE, "tracks need"),
    Pair("slider.track_color", _FOCUSED, _BUTTON, LARGE, "tracks need"),
    Pair("list.scrollbar_color", "panel.fill_color", _PANEL, LARGE, "scrollbars need",
         _plain("panel")),
    Pair("quick_menu.text_color", "quick_menu.fill_color", _QUICK, TEXT,
         "quick menu text needs", _plain("quick_menu")),
    Pair("quick_menu.focused.text_color", "quick_menu.fill_color", _QUICK, TEXT,
         "quick menu text needs", _plain("quick_menu")),
    Pair("quick_menu.text_color", "quick_menu.on.fill_color", _QUICK, TEXT,
         "quick menu text needs"),
    Pair("quick_menu.disabled.text_color", "quick_menu.fill_color", _QUICK, TEXT,
         "quick menu text needs", _plain("quick_menu")),
    Pair("title.version.text_color", "panel.fill_color", "title.version.fill_opacity", TEXT,
         "version text needs"),
    Pair("title.logo.text_color", "title.fill_top_color", None, LARGE, "title text needs",
         _gradient),
    Pair("title.logo.text_color", "title.fill_bottom_color", None, LARGE, "title text needs",
         _gradient),
    Pair("title.logo.text_color", "panel.fill_color", _PANEL, LARGE, "title text needs",
         _backing),
    Pair("toggle.on.knob_color", "toggle.on.track_color", None, LARGE, "toggle knobs need"),
    Pair("title.loading.text_color", LOADING_SCREEN, None, TEXT, "loading text needs"),
    # F14: the limit mark's glyph on its opaque pill (a graphic, 3:1; "marks need" drafted).
    Pair("rollback.mark.glyph_color", "rollback.mark.fill_color", None, LARGE, "marks need",
         _plain("rollback.mark")),
    # F20 (03-ui "Contrast"; chart surfaces are opaque). Drafted nouns.
    Pair("flowchart.node.text_color", "flowchart.node.fill_color", None, TEXT,
         "flowchart text needs"),
    Pair("flowchart.node.text_color", _FOCUSED, None, TEXT, "flowchart text needs"),
    Pair("flowchart.node.text_color", "flowchart.fill_color", None, TEXT,
         "flowchart text needs"),
    Pair("flowchart.unknown.text_color", "flowchart.fill_color", None, TEXT,
         "flowchart text needs"),
    Pair("flowchart.unknown.text_color", _FOCUSED, None, TEXT, "flowchart text needs"),
    Pair("flowchart.here.text_color", "flowchart.here.fill_color", None, TEXT,
         "flowchart text needs"),
    Pair("flowchart.edge.line_color", "flowchart.fill_color", None, LARGE,
         "flowchart lines need"),
    Pair("flowchart.node.border_color", "flowchart.node.fill_color", None, LARGE,
         "flowchart lines need"),
    Pair("flowchart.path.line_color", "flowchart.fill_color", None, LARGE,
         "flowchart lines need"),
)


def _token(cfg: ThemeConfig, path: str) -> object:
    """The token's value; F20's ``flowchart.*`` colors that follow another token (None) are
    resolved as the page resolves them (``flow_color``)."""
    node: object = cfg
    for part in path.split("."):
        node = getattr(node, part)
    if node is None and path in FOLLOWS:
        return flow_color(cfg, path)
    return node


def _bg_color(cfg: ThemeConfig, pair: Pair) -> RGB:
    return BLACK if pair.bg == LOADING_SCREEN else _token(cfg, pair.bg)   # type: ignore


def pair_ratios(cfg: ThemeConfig, pair: Pair) -> tuple[float, float]:
    """``pair``'s contrast over pure black and over pure white, composited as drawn."""
    fg: RGB = _token(cfg, pair.fg)                                       # type: ignore
    bg = _bg_color(cfg, pair)
    opacity = 1.0 if pair.opacity is None else float(_token(cfg, pair.opacity))  # type: ignore
    return (contrast_ratio(fg, composite(bg, opacity, BLACK)),
            contrast_ratio(fg, composite(bg, opacity, WHITE)))


def contrast_warnings(theme: UiTheme) -> list[str]:
    """W67's text for each drawn pair of ``theme`` under its minimum, in ``PAIRS`` order."""
    out = []
    for pair in PAIRS:
        if not pair.drawn(theme):
            continue
        over_black, over_white = pair_ratios(theme.cfg, pair)
        ratio, backdrop = (over_black, "black") if over_black <= over_white else \
            (over_white, "white")
        if ratio < pair.minimum:
            out.append(w67_text(theme.cfg, pair, ratio, backdrop))
    return out


def warn_contrast(theme: UiTheme, *, dev: bool, log=_log) -> None:
    """W67 (dev only) for each pair ``contrast_warnings`` finds; each pair is its own cause."""
    if dev:
        for text in contrast_warnings(theme):
            log.warning("%s", text, extra={"code": "W67"})


# --- The message (03-ui "Warnings") ------------------------------------------------------------

def _hex(color: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def _floored(ratio: float) -> str:
    """As F02's ratios (G1): floored to one decimal."""
    return f"{math.floor(ratio * 10 + 1e-9) / 10:.1f}"


def _shade(fg: RGB, bg: RGB, minimum: float) -> str:
    """W41's rule: move the color away from its background ("darker" when it is the darker
    one), unless even black or white that way can't reach ``minimum``; then, as for equal
    colors, the way with more room."""
    fg_l, bg_l = relative_luminance(fg), relative_luminance(bg)
    if fg_l != bg_l:
        shade = "darker" if fg_l < bg_l else "lighter"
        if contrast_ratio(BLACK if shade == "darker" else WHITE, bg) >= minimum:
            return shade
    return "darker" if contrast_ratio(BLACK, bg) >= contrast_ratio(WHITE, bg) else "lighter"


def w67_text(cfg: ThemeConfig, pair: Pair, ratio: float, backdrop: str) -> str:
    """W67 for ``pair`` at ``ratio`` (the worse one; ``backdrop`` ``"black"`` or ``"white"``).
    Keys are named under the table the two colors share, e.g. ``[theme.button]
    disabled.text_color … on fill_color``; a key outside it carries its own table."""
    fg_table, fg_key = pair.fg.rsplit(".", 1)
    bg_table = pair.bg.rsplit(".", 1)[0] if pair.bg else ""
    common: list[str] = []
    for a, b in zip(fg_table.split("."), bg_table.split(".")):
        if a != b:
            break
        common.append(a)
    head = ".".join(common) or fg_table

    def name(path: str) -> str:
        if path.startswith(head + "."):
            return path[len(head) + 1:]
        table, key = path.rsplit(".", 1)
        return f"[theme.{table}] {key}"

    fg: RGB = _token(cfg, pair.fg)                                       # type: ignore
    bg = _bg_color(cfg, pair)
    fg_name = name(pair.fg)
    start = f"config.toml: [theme.{head}] {fg_name} {_hex(fg)}"
    need = f"{pair.needs} at least {pair.minimum:g}:1"
    if pair.bg == LOADING_SCREEN:
        return (f"{start} on the black loading screen gives {_floored(ratio)}:1; {need}. "
                f"Pick a {_shade(fg, bg, pair.minimum)} {fg_name}.")
    on = f"{name(pair.bg)} {_hex(bg)}"
    if not pair.fg.endswith("text_color"):
        return (f"{start} is hard to see on {on} ({_floored(ratio)}:1; {need}). Pick a "
                f"{_shade(fg, bg, pair.minimum)} {fg_name}.")
    if pair.opacity is None:
        return f"{start} on {on} gives {_floored(ratio)}:1; {need}. Pick colors further apart."
    opacity = _token(cfg, pair.opacity)
    return (f"{start} on {on} at {name(pair.opacity)} {opacity:g} gives {_floored(ratio)}:1 "
            f"over a {backdrop} picture; {need}. Pick colors further apart.")


__all__ = ["PAIRS", "Pair", "contrast_warnings", "pair_ratios", "w67_text", "warn_contrast"]
