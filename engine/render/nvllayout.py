"""NVL page layout without drawing: the look, the metrics, line heights, and the page fold
(F17 ``04-technical.md`` §5.3, §7.3; ``06`` AC-F17-11, 12).

Why this module exists: a live page (the presenter appends each ``Say`` it receives) and a
restored page (a restore sends the whole record) must group lines into the visible page the
same way, or a load would show another page than the player saw. Both fold the same
``plan_add`` over the same heights, so for the same lines and size the plans are equal
(TR-F17-03). Grouping is presentation-only: nothing here reaches the runtime (PR-F17-13).

- ``nvl_look`` resolves ``[theme.nvl]`` with its ``[theme.textbox]`` fallbacks.
- ``nvl_metrics`` is the text area at one effective size (F16's ``text_scale``): ``W`` wide
  and centered, from ``top_gap`` to ``720 − bottom_gap``; size clamped to 20–48; pitch
  ``round(1.4 × size)``.
- ``heights`` of a line: its page count and the heights of its first and last pages (each at
  least one pitch: an empty line takes one row), from ``LineLayout.page_height`` (breaks, no
  glyph positions), cached in an LRU of ``HEIGHTS_CACHE_MAX`` keyed by (line, width, height,
  size, faces). ``NvlLine`` compares by value, so live and restored lines share keys.
- ``plan_add`` places one line: a line of several pages starts a page alone and shows its
  last page (``Row.page`` −1); otherwise it goes ``gap`` below the last line if it fits, else
  it starts a new page. A name takes one pitch above the text. ``plan_from`` folds it.

Imports ``core``, ``runtime.commands`` and ``render.textlayout`` only; no pygame (AC-F17-33).
"""

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from engine.core.config_schema import RGB, ThemeConfig
from engine.core.constants import CANVAS_SIZE
from engine.render.textlayout import LINE_PITCH, FaceSet, LayoutContext, LineLayout
from engine.runtime.commands import NvlLine, TaggedText

NVL_SIZE_RANGE: Final = (20, 48)        # the effective size, clamped (UI-F17-05)
HEIGHTS_CACHE_MAX: Final = 1_024        # lines' heights kept (04 §7.3)


@dataclass(frozen=True)
class NvlLook:
    """``[theme.nvl]`` with its ``[theme.textbox]`` fallbacks resolved."""

    fill_color: RGB
    fill_opacity: float
    width: int
    top_gap: int
    bottom_gap: int
    line_gap: int
    text_size: int
    text_color: RGB
    name_color: RGB
    indicator_color: RGB


def nvl_look(theme: ThemeConfig) -> NvlLook:
    """The NVL look of ``theme``: each ``[theme.nvl]`` value, or the textbox's where it is
    None (fill and text colors, text size, the name tab's text color, the indicator's)."""
    nvl, box = theme.nvl, theme.textbox
    return NvlLook(
        fill_color=nvl.fill_color if nvl.fill_color is not None else box.fill_color,
        fill_opacity=nvl.fill_opacity,
        width=nvl.width,
        top_gap=nvl.top_gap,
        bottom_gap=nvl.bottom_gap,
        line_gap=nvl.line_gap,
        text_size=nvl.text_size if nvl.text_size is not None else box.text_size,
        text_color=nvl.text_color if nvl.text_color is not None else box.text_color,
        name_color=(nvl.name.text_color if nvl.name.text_color is not None
                    else box.name_tab.text_color),
        indicator_color=(nvl.indicator.fill_color if nvl.indicator.fill_color is not None
                         else box.indicator.fill_color))


@dataclass(frozen=True)
class NvlMetrics:
    """The text area at one effective size, in canvas units: ``left``/``top`` its corner,
    ``width``/``height`` (``H``) its size, ``pitch`` one row (and a name row), ``gap`` the
    space between two lines."""

    left: float
    top: float
    width: float
    height: float
    size: int
    pitch: int
    gap: int


def nvl_metrics(look: NvlLook, text_scale: float) -> NvlMetrics:
    """``size = clamp(round(text_size × text_scale), 20, 48)``, ``pitch = round(1.4 ×
    size)``; the area is ``width`` wide, centered, from ``top_gap`` to the canvas bottom less
    ``bottom_gap``."""
    low, high = NVL_SIZE_RANGE
    size = min(high, max(low, round(look.text_size * text_scale)))
    canvas_w, canvas_h = CANVAS_SIZE
    return NvlMetrics(left=canvas_w / 2 - look.width / 2, top=float(look.top_gap),
                      width=float(look.width),
                      height=float(canvas_h - look.top_gap - look.bottom_gap),
                      size=size, pitch=round(LINE_PITCH * size), gap=look.line_gap)


def hex_color(color: RGB) -> str:
    """``(r, g, b)`` as ``#rrggbb`` (``LayoutContext.base_color``)."""
    return "#{:02x}{:02x}{:02x}".format(*color)


def line_context(assets: object, faces: FaceSet, look: NvlLook, m: NvlMetrics,
                 named: bool) -> LayoutContext:
    """A line's layout context: the area's width, its height less a name row when the line
    is ``named`` (every page of a named line repeats the name, so one height serves all)."""
    name_h = m.pitch if named else 0
    return LayoutContext(assets, faces, m.size, hex_color(look.text_color), m.width,
                         m.height - name_h)


# --- Heights (04 §7.3) ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Heights:
    """A line's page count ``n`` and the heights of its first and last pages (each at least
    one pitch)."""

    n: int
    first: float
    last: float


_heights: "OrderedDict[tuple, Heights]" = OrderedDict()
_stats = [0, 0]                         # hits, misses


def heights(line: NvlLine, m: NvlMetrics, ctx: LayoutContext) -> Heights:
    """``line``'s heights in ``ctx`` (``line_context``), from the LRU when known. Computed
    from ``TaggedText(line.spans)`` by ``LineLayout``'s breaking, without glyph positions."""
    key = (line, ctx.width, ctx.height, ctx.text_size, tuple(ctx.faces.faces.items()))
    found = _heights.get(key)
    if found is not None:
        _heights.move_to_end(key)
        _stats[0] += 1
        return found
    _stats[1] += 1
    layout = LineLayout(TaggedText(line.spans), ctx)
    n = layout.all_pages()
    first = max(layout.page_height(0), m.pitch)
    last = first if n == 1 else max(layout.page_height(n - 1), m.pitch)
    found = _heights[key] = Heights(n, first, last)
    if len(_heights) > HEIGHTS_CACHE_MAX:
        _heights.popitem(last=False)
    return found


def heights_cache_info() -> tuple[int, int, int]:
    """(entries, hits, misses) of the heights LRU, for tests and the perf tier."""
    return len(_heights), _stats[0], _stats[1]


def clear_heights() -> None:
    """Empty the heights LRU and its counts (a cold load in tests)."""
    _heights.clear()
    _stats[0] = _stats[1] = 0


# --- The fold (04 §7.3) --------------------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    """One line on the visible page: ``entry`` its index among the presenter's entries,
    ``page`` which page of its layout (−1: its last), ``y`` the top of its name row (or of
    its text when unnamed), in canvas units."""

    entry: int
    page: int
    y: float


@dataclass(frozen=True)
class PagePlan:
    """The visible page: its rows in order, the height ``used`` from the area's top, and the
    effective size it was planned at."""

    rows: tuple[Row, ...]
    used: float
    size: int


def empty_plan(m: NvlMetrics) -> PagePlan:
    return PagePlan((), 0.0, m.size)


def plan_add(plan: PagePlan, i: int, h: Heights, named: bool, m: NvlMetrics) -> PagePlan:
    """``plan`` with entry ``i`` placed (module docstring)."""
    assert h.n >= 1, "a line has at least one page"
    name_h = m.pitch if named else 0
    need = name_h + h.first
    top = m.top
    if h.n > 1:
        return PagePlan((Row(i, -1, top),), name_h + h.last, m.size)
    if plan.rows and plan.used + m.gap + need <= m.height:
        return PagePlan(plan.rows + (Row(i, 0, top + plan.used + m.gap),),
                        plan.used + m.gap + need, m.size)
    return PagePlan((Row(i, 0, top),), need, m.size)


def plan_from(lines: Sequence[NvlLine], m: NvlMetrics,
              ctx_for: Callable[[NvlLine], LayoutContext]) -> PagePlan:
    """``plan_add`` folded over ``lines`` from the oldest (entries ``0..len − 1``);
    ``ctx_for(line)`` gives each line's context (``line_context``)."""
    plan = empty_plan(m)
    for i, line in enumerate(lines):
        plan = plan_add(plan, i, heights(line, m, ctx_for(line)), bool(line.name), m)
    return plan


__all__ = ["HEIGHTS_CACHE_MAX", "Heights", "NVL_SIZE_RANGE", "NvlLook", "NvlMetrics",
           "PagePlan", "Row", "clear_heights", "empty_plan", "heights", "heights_cache_info",
           "hex_color", "line_context", "nvl_look", "nvl_metrics", "plan_add", "plan_from"]
