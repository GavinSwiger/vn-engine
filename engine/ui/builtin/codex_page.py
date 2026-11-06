"""``CodexView`` and ``CodexPage``: the codex list, reusable, and its game-menu page (F21
``01-design.md`` §6 UI-F21-01 to 05; ``04-technical.md`` §5, §7.7, §7.9, §7.10 with its
amendment; ``07-architecture-review.md`` I-1, I-9, I-10, I-12).

Why this module exists: the player rereads the tips and items found so far, F25 presents an
item from the same list, and F27 picks one, so the list is one widget set (``CodexView``)
that any host puts in a box of at least 640×400. F21's own host is ``CodexPage`` in the game
menu's body slot (and, opened from the title, tips only). The view reads the story only
through a ``CodexPort`` (``app/codex.py``'s ``AppCodexPort``, F23's ``LedgerCodexPort``), so
``ui`` never imports ``engine.script`` or ``persist``.

- **Model** (§7.10), made again by ``build`` and when the port's tips or items change: the
  entries passing the ``CodexFilter`` (from the title only tips); per category, unlocked tips
  in declaration order (plus locked ones as disabled ``???`` rows under ``show_locked``) or
  held items in the order obtained; tabs are the categories, in first-declaration order,
  that have a row. No tab: ``codex_empty`` centred in the box (``list.empty`` color).
- **Layout** is ``layouts.codex_layout`` (pure): a tab row (``PageRow`` placed top-left,
  only with two or more tabs; labels cut with "…" so one tab and ◀ ▶ fit, I-12), the list
  (rows max(``list.row_height``, pitch + 16), the title at x + 16 cut with "…" to lw − 64, an
  unread dot 24 from the row's right edge), and the detail panel: the picture box (only for
  an entry declared with a picture, 07 I-9), the title in ``panel.heading`` (2 lines, then
  "…"), the body (an F13 variable-row ``ScrollList`` of paragraphs laid out with F05's
  ``LineLayout``, 12 apart, cached per (entry, width, text size)), and the pick button.
- **Lazy body** (04 §11 amendment, TR-F21-05): showing an entry lays out only the
  paragraphs in the body's view; the others have an estimated height (one font measure of
  the plain text: max(pitch, ceil(1.1 × width / body width) × pitch), + 12 between
  paragraphs). Each ``update`` lays out at most one more: a row now in view first, else the
  first one not laid out. A row above the view that gets its real height moves ``scroll`` by
  the difference, so the text in view stays put. The partial layout stays in the cache, so
  a revisit continues where it left off.
- **Selection.** ``build`` keeps ``selected`` while it is still listed, else the first
  unlocked row of the first tab; a tab switch selects that tab's first unlocked row. Keys:
  the detail follows the focused row; the mouse: a press on a row selects it (hover only
  moves the focus look). Showing an entry marks it read through the port (§7.7), once.
- **Keys** (UI-F21-03), in the widgets and in ``on_nav`` (for a host that calls it before
  F10's move): Up from the list's first row goes to the current tab's button; Right from the
  list to the body (else the pick button), Left from the body back; Activate on a row moves
  focus to the body (browse) or the pick button (pick); Activate on the pick button calls
  ``on_pick(selected)``, synchronously (F25 I-4, F23 A6). The rest is F10's.
- **Drawing** (amendment): ``draw`` draws only what isn't a scope widget: the detail panel,
  the picture, the title, and ``codex_empty``. The owner draws the widgets (``MenuScreen``
  for ``CodexPage``, F23's host for a plugin).
- **Pictures** (§7.9): ``port.picture(image)`` gives a file ref (loaded with
  ``assets.image``, scaled down to fit and never up, centred, through the FINAL variant
  cache; a placeholder draws nothing, F01 logged it once), an RGB (a filled 16:9 box fitted
  to the picture box), or None (nothing).

F64 (specs/F64-items/SPEC.md): a counted item's row title ends with "×n" (the port's
``count``); the items' default tab is named by the port's ``bag_word`` (the kit's, or
``[codex] bag_word``) when it has one; and with ``purse`` (the game menu's page, not the
title's or a picker's) the money item's word and count ("Coins ×30", the port's ``purse``)
are drawn at the right of the top row, also when the bag is empty. Ports without these
methods (F23's) show the page as before.

F64 round 2 (Use): with a ``UseAction`` (the game menu's page only), an item that has a Use
scene shows a Use button where the pick button goes, enabled only while the item can be used
now (``app/hotbar.ItemUser``); its ``hint`` ("Belt: 2", the item's hotbar slot) is drawn at
the left of that row and the button takes the right half. The button is a focus group of its
own, shown and hidden as the selection moves (``groups_changed``).

F65 (codex kinds): which kinds a view lists, in what order, and with which fields comes from
``core/codexkinds``: ``KINDS`` are the kinds on the ``codex`` page, a kind's ``order`` picks
how ``codex_tabs`` makes its rows (``declared``: tips, with locked ones under
``show_locked``; ``obtained`` and ``newest``: the port's own order), ``on_title`` which ones
the title's page lists, and ``"count"`` in ``shows`` which rows end with "×n". A port lists
a kind other than tips and items with ``listed(kind)`` (optional, ``port_listed``);
``ui/builtin/kind_page.KindPage`` is the page of any other kind (the Inbox).

Theme (01 §6): ``codex.new.fill_color`` (None: ``button.marker.fill_color``),
``codex.locked.text_color`` (None: ``button.disabled.text_color``), ``codex.image_height``.
Words: ``codex`` (the heading), ``codex_tips``, ``codex_items``, ``codex_locked``,
``codex_empty``; the pick word is the host's.
"""

import dataclasses
import math
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol

from engine.core.codexkinds import ORDER_DECLARED, codex_kind, codex_kinds, page_kinds
from engine.render.text import FontSpec
from engine.render.textlayout import LayoutContext, LineLayout, Page
from engine.runtime.codex import CodexCategory, CodexEntry
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import (
    CODEX_DOT,
    CODEX_DOT_INSET,
    CODEX_GAP,
    CODEX_MIN_BOX,
    CODEX_TITLE_LINES,
    CODEX_TITLE_X,
    PAGE_ROW_LABEL_PAD,
    CodexLayout,
    RowPlacement,
    codex_layout,
    cut_to_width,
    pitch,
    scaled,
    wrap_text,
)
from engine.ui.menus import MenuPageBase
from engine.ui.nav import InputKind, Nav
from engine.ui.page_row import PageRow
from engine.ui.theme import font_spec, measure_with
from engine.ui.widgets import (
    SCROLL_RADIUS,
    SCROLL_TRACK,
    Button,
    ListRow,
    Look,
    MouseKind,
    ScrollList,
    clipped,
)

if TYPE_CHECKING:
    from engine.core.config_schema import ThemeConfig
    from engine.render.canvas import Canvas
    from engine.ui.focus import FocusScope
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme, Words
    from engine.ui.widgets import Widget

RGB = tuple[int, int, int]
HEADING: Final = "codex"              # the [words] key of the heading and both entries
KINDS: Final = frozenset(k.name for k in page_kinds(HEADING))      # F65: tips and items
SOLID_ASPECT: Final = (16, 9)         # a SolidColor picture is a 16:9 box
BODY_LAYOUT_CACHE: Final = 8          # entries whose body layouts are kept
LAZY_ESTIMATE: Final = 1.1            # an unlaid paragraph's lines: 1.1 × its width / the body's


# --- Seams ---------------------------------------------------------------------------------------

class CodexPort(Protocol):
    """What the view reads (04 §5): every declared entry (declaration order), the categories
    (first-declaration order), the unlocked tips, the held items (order obtained), the read
    marks, and pictures. ``mark_read`` is the one write (§7.7)."""

    show_locked: bool

    def entries(self) -> Sequence[CodexEntry]: ...

    def categories(self) -> Sequence[CodexCategory]: ...

    def tips(self) -> Collection[str]: ...

    def items(self) -> Sequence[str]: ...

    def is_read(self, name: str) -> bool: ...

    def mark_read(self, name: str) -> None: ...

    def picture(self, image: str) -> "str | RGB | None": ...

    # F64, optional (``getattr``): ``count(name)`` (held count), ``bag_word()`` ("" for
    # none), ``purse()`` (the money's shown word and count, or None). F65, optional:
    # ``listed(kind)``, the names of another codex kind in its order (``port_listed``).


def port_listed(port: object, kind: str) -> Sequence[str]:
    """F65: the names the port lists for ``kind``: ``tips()``, ``items()``, else the port's
    ``listed(kind)`` (() for a port without it)."""
    if kind == "tip":
        return port.tips()                                      # type: ignore[attr-defined]
    if kind == "item":
        return port.items()                                     # type: ignore[attr-defined]
    listed = getattr(port, "listed", None)
    return listed(kind) if listed is not None else ()


def port_count(port: object, name: str) -> int:
    """F64: the port's held count of ``name`` (1 for a port without counts)."""
    count = getattr(port, "count", None)
    return count(name) if count is not None else 1


def port_purse(port: object) -> tuple[str, int] | None:
    """F64: the port's purse, or None (no money item, or a port without one)."""
    purse = getattr(port, "purse", None)
    return purse() if purse is not None else None


def purse_text(word: str, count: int) -> str:
    """F64: the purse as shown, "Coins ×30"."""
    return f"{word} ×{count:,}"


def row_title(port: object, entry: CodexEntry) -> str:
    """F64: a row's title: a counted item's ends with "×n" (F65: a kind that shows a
    count)."""
    kind = codex_kind(entry.kind)
    if kind is not None and "count" in kind.shows and getattr(entry, "counted", False):
        return f"{entry.title} ×{port_count(port, entry.name):,}"
    return entry.title


class CodexUi(Protocol):
    """What the view draws with: the resolved theme, the words, and the asset manager
    (``GameShell`` has all three; F23's host passes its own)."""

    theme: "UiTheme"
    words: "Words"
    assets: Any


@dataclass(frozen=True)
class CodexFilter:
    """Which entries a view lists. ``categories``: author texts, or ``"codex_tips"`` /
    ``"codex_items"`` for a kind's default category; None: all."""

    kinds: frozenset[str] = KINDS
    categories: frozenset[str] | None = None


@dataclass(frozen=True)
class PickAction:
    """The pick button: its text (from the host's words) and what a pick calls."""

    word: str
    on_pick: Callable[[str], None]


@dataclass(frozen=True)
class UseAction:
    """F64 round 2: the bag's Use button: its word, which items have one (``has``), which
    can be used now (``can``), the call, and the hint beside it ("" for none)."""

    word: str
    has: Callable[[str], bool]
    can: Callable[[str], bool]
    on_use: Callable[[str], None]
    hint: Callable[[str], str] = lambda _name: ""


@dataclass(frozen=True)
class CodexRow:
    entry: CodexEntry
    locked: bool = False              # a locked tip (``show_locked``): ``???``, disabled


@dataclass(frozen=True)
class CodexTab:
    key: str                          # the author's category text, or the default's word key
    label: str                        # as written, or the word (``Tips``, ``Items``)
    rows: tuple[CodexRow, ...]


def category_key(category: CodexCategory) -> str:
    """The key ``CodexFilter.categories`` takes for ``category``."""
    return category.text if category.text is not None else (category.word or "")


def codex_tabs(port: CodexPort, flt: CodexFilter, word: Callable[[str], str], *,
               title: bool = False) -> tuple[CodexTab, ...]:
    """04 §7.10 "Model": the tabs and their rows (module docstring). F65: each kind in
    ``codexkinds`` order, its rows made by its ``order``."""
    kinds = flt.kinds & {k.name for k in codex_kinds() if k.on_title} if title else flt.kinds
    wanted = flt.categories

    def passes(entry: CodexEntry) -> bool:
        return entry.kind in kinds and (wanted is None
                                        or category_key(entry.category) in wanted)

    entries = tuple(port.entries())
    rows: dict[CodexCategory, list[CodexRow]] = {}
    for kind in codex_kinds():
        if kind.name not in kinds:
            continue
        names = port_listed(port, kind.name)
        if kind.order == ORDER_DECLARED:                # tips: declaration order
            unlocked = set(names)
            locked = bool(port.show_locked)
            for entry in entries:
                if entry.kind != kind.name or not passes(entry):
                    continue
                if entry.name in unlocked:
                    rows.setdefault(entry.category, []).append(CodexRow(entry))
                elif locked:
                    rows.setdefault(entry.category, []).append(CodexRow(entry, True))
        else:                                           # the port's order
            by_name = {e.name: e for e in entries if e.kind == kind.name}
            for name in names:
                entry = by_name.get(name)
                if entry is not None and passes(entry):
                    rows.setdefault(entry.category, []).append(CodexRow(entry))
    tabs = []
    for category in port.categories():
        found = rows.get(category)
        if found:
            label = category.text if category.text is not None else word(category.word or "")
            tabs.append(CodexTab(category_key(category), label, tuple(found)))
    return tuple(tabs)


def new_dot_color(cfg: "ThemeConfig") -> RGB:
    """``codex.new.fill_color``, else the resolved ``button.marker.fill_color``."""
    color = cfg.codex.new.fill_color
    return tuple(color if color is not None else cfg.button.marker.fill_color)  # type: ignore


def locked_color(cfg: "ThemeConfig") -> RGB:
    """``codex.locked.text_color``, else the resolved ``button.disabled.text_color``."""
    color = cfg.codex.locked.text_color
    return tuple(color if color is not None else cfg.button.disabled.text_color)  # type: ignore


def fit_picture(size: tuple[float, float], box: Box, *, upscale: bool = False) -> Box:
    """``size`` scaled to fit ``box`` keeping its shape (never up unless ``upscale``),
    centred, in whole canvas units."""
    w, h = size
    if w <= 0 or h <= 0:
        return Box(box.x + box.w / 2, box.y + box.h / 2, 0, 0)
    s = min(box.w / w, box.h / h)
    if not upscale:
        s = min(1.0, s)
    tw, th = round(w * s), round(h * s)
    return Box(box.x + (box.w - tw) / 2, box.y + (box.h - th) / 2, tw, th)


def _hex(color: Sequence[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color[:3])


def _rgb(color: str) -> RGB:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


# --- Widgets -------------------------------------------------------------------------------------

class _CodexList(ScrollList):
    """The entry list: the view's routes first (Up to the tabs, Right to the body,
    Activate); a key move shows the newly focused entry; a press on a row selects it."""

    def __init__(self, view: "CodexView") -> None:
        self.view = view
        self.clicked = False
        super().__init__(lambda: view.list_rows, view._row_activated,
                         draw_row=view._draw_row, enabled=lambda: bool(view.list_rows))

    def on_nav(self, d: Nav) -> bool:
        if self.view._route(self, d):
            return True
        used = super().on_nav(d)
        if used:
            self.clicked = False
            self.view._follow_focus()
        return used

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        used = super().on_mouse(kind, pos, notches=notches)
        if kind == "down":
            self.clicked = self.pressed_row is not None
            if self.clicked:
                self.view._select_row(self.focus_row)
        return used


class _CodexBody(ScrollList):
    """The detail body: paragraphs as F13 variable rows (Up/Down/Page keys scroll it), Left
    back to the list. Drawn as text only, with the focus frame round the whole box."""

    def __init__(self, view: "CodexView") -> None:
        self.view = view
        super().__init__(lambda: view.body_rows, lambda _index: None,
                         heights=lambda i: view.body_heights[i],
                         pitch=lambda: view.body_pitch, enabled=lambda: bool(view.body_rows))

    def on_nav(self, d: Nav) -> bool:
        if self.view._route(self, d):
            return True
        return super().on_nav(d)

    def draw(self, p: "Painter", look: Look) -> None:
        rows = self._sync()
        if not rows:
            return
        if look.state in ("focused", "pressed"):
            p.widget_frame(self.box, "list", Look("focused"), marker=False)
        with clipped(p, self.box):
            for index in self.visible_range():
                self.view._draw_paragraph(p, index, self.row_box(index))
            lane, thumb = self.lane_box(), self.thumb_box()
            if lane is not None and thumb is not None:
                from engine.render.frames import FrameSpec

                style = p.style("list", "normal")
                x = lane.x + (lane.w - SCROLL_TRACK) / 2
                p.shape(Box(x, lane.y, SCROLL_TRACK, lane.h),
                        FrameSpec(style.color("scrollbar_track"), 1.0,
                                  corner_radius=SCROLL_RADIUS))
                p.shape(Box(x, thumb.y, SCROLL_TRACK, thumb.h),
                        FrameSpec(style.color("scrollbar"), 1.0, corner_radius=SCROLL_RADIUS))


@dataclass
class _Body:
    """One entry's body at one (width, text size): each paragraph's page (None: not laid
    out yet) and row height (estimated until laid out), shared with the cache so a revisit
    continues where it left off (04 §11 amendment)."""

    paragraphs: tuple = ()
    ctx: Any = None
    pages: "list[Page | None]" = field(default_factory=list)
    heights: list[float] = field(default_factory=list)
    pitch: int = 1

    def gap(self, index: int) -> int:
        return CODEX_GAP if index < len(self.pages) - 1 else 0

    def unlaid(self) -> int | None:
        """The first paragraph not laid out yet, or None."""
        return next((i for i, page in enumerate(self.pages) if page is None), None)


@dataclass
class _Detail:
    """The shown entry's detail: the title lines (≤ 2, the last may end "…") and its
    body (``_Body``; empty with no entry)."""

    title: tuple[str, ...] = ()
    body: _Body = field(default_factory=_Body)

    @property
    def pages(self) -> list:
        return self.body.pages


@dataclass
class _Cache:
    layouts: dict[tuple, _Body] = field(default_factory=dict)
    titles: dict[tuple, str] = field(default_factory=dict)


# --- The view ------------------------------------------------------------------------------------

class CodexView:
    """The reusable codex list (module docstring). ``ui`` gives the theme, words, and
    assets; ``scope`` the host's ``FocusScope`` (the view focuses its own widgets in it);
    ``title`` lists tips only (the title screen's page)."""

    def __init__(self, port: CodexPort, *, ui: CodexUi, filter: CodexFilter = CodexFilter(),
                 pick: PickAction | None = None, title: bool = False,
                 scope: "Callable[[], FocusScope | None] | None" = None,
                 purse: bool = False, use: UseAction | None = None) -> None:
        self.port = port
        self.use = use if not title and pick is None else None
        self.show_purse = purse and not title
        self.ui = ui
        self.filter = filter
        self.pick = pick
        self.title_mode = title
        self._scope: "Callable[[], FocusScope | None]" = \
            scope if scope is not None else (lambda: None)
        cfg = ui.theme.cfg
        self.cfg = cfg
        self.box = Box(0, 0, *CODEX_MIN_BOX)
        self.scale = 1.0
        self.layout: CodexLayout | None = None
        self.tabs: tuple[CodexTab, ...] = ()
        self.tab = 0
        self.selected: str | None = None
        self.list_rows: list[ListRow] = []
        self.body_rows: list[ListRow] = []
        self.body_heights: list[float] = []
        self.body_pitch = 1
        self.groups_changed = False       # the shown widgets changed: the host builds again
        self.layouts_made = 0             # paragraphs laid out (cache misses)
        self._detail = _Detail()
        self._cache = _Cache()
        self._signature: tuple | None = None
        self._shown: tuple[bool, bool, bool] | None = None    # (tab row, list, pick)
        button = cfg.button
        self._label_font = ui.theme.font(button.text_size)
        self._measure = measure_with(ui.assets, self._label_font)
        self._heading_measure = measure_with(ui.assets, ui.theme.font(
            cfg.panel.heading.text_size, bold=True))
        self.tab_row = PageRow(lambda: self._tab_labels, lambda: self.tab, self._select_tab,
                               measure=self._measure, scale=lambda: self.scale,
                               text_size=button.text_size, height=button.height)
        self._tab_labels: tuple[str, ...] = ()
        self.list = _CodexList(self)
        self.body = _CodexBody(self)
        self.pick_button = Button(lambda: pick.word if pick is not None else "", self._pick,
                                  enabled=lambda: self.selected is not None) \
            if pick is not None else None
        self.use_button = Button(lambda: self.use.word if self.use is not None else "",
                                 self._use, enabled=self._can_use) \
            if self.use is not None else None

    # -- building --

    def build(self, box: Box, text_scale: float) -> list[FocusGroup]:
        """Lay out in ``box`` (≥ 640×400) at ``text_scale`` and return the focus groups of
        the widgets shown now (the tab row only with two or more tabs; none with no tab)."""
        assert box.w >= CODEX_MIN_BOX[0] and box.h >= CODEX_MIN_BOX[1], \
            f"a CodexView needs at least 640×400, not {box.w}×{box.h}"
        self.box = box
        self.scale = text_scale
        self._refresh()
        self.groups_changed = False
        return self._groups()

    def _groups(self) -> list[FocusGroup]:
        if not self.tabs:
            self._shown = (False, False, False)
            return []
        groups = []
        if len(self.tabs) > 1:
            groups.append(FocusGroup([self.tab_row]))
        groups.append(FocusGroup([self.list], column=True))
        groups.append(FocusGroup([self.body]))
        if self.pick_button is not None:
            groups.append(FocusGroup([self.pick_button]))
        if self.use_button is not None and self._use_shown():          # F64: Use
            groups.append(FocusGroup([self.use_button]))
        self._shown = (len(self.tabs) > 1, True, self.pick_button is not None,
                       self._use_shown())
        return groups

    # -- F64 round 2: Use --

    def _use_shown(self) -> bool:
        """The selected entry is an item with a Use scene (and this view has Use)."""
        name = self.selected
        if self.use is None or name is None:
            return False
        entry = next((r.entry for r in self.rows() if r.entry.name == name), None)
        return entry is not None and entry.kind == "item" and self.use.has(name)

    def _can_use(self) -> bool:
        return (self._use_shown() and self.use is not None
                and self.use.can(self.selected))           # type: ignore[arg-type]

    def _use(self) -> None:
        if self.use is not None and self.selected is not None and self._can_use():
            self.use.on_use(self.selected)

    def use_hint(self) -> str:
        """The hint beside Use for the selected item ("" for none)."""
        if not self._use_shown():
            return ""
        return self.use.hint(self.selected)                # type: ignore[union-attr,arg-type]

    def _refresh(self) -> None:
        """The model again, keeping ``selected`` while it is still listed (else the
        current tab's first unlocked row; the first tab's when that tab is gone)."""
        port = self.port
        self._signature = self._sign()
        self.tabs = codex_tabs(port, self.filter, self._word, title=self.title_mode)
        previous, previous_tab = self.selected, self.tab
        self.selected = None
        tab, row = self._find(previous)
        if tab is None:
            tab = previous_tab if previous is None and previous_tab < len(self.tabs) else 0
            row = None
        self._open_tab(tab, row)

    def _sign(self) -> tuple:
        """What the model is made from: the tips, the items, and (F64) their counts; F65: the
        names of the view's other kinds."""
        port = self.port
        items = tuple(port.items())
        counts = tuple(port_count(port, n) for n in items) \
            if getattr(port, "count", None) is not None else ()
        others = tuple(tuple(port_listed(port, k)) for k in sorted(self.filter.kinds - KINDS))
        return (tuple(port.tips()), items, counts, port_purse(port) if self.show_purse
                else None, others)

    def _word(self, key: str) -> str:
        """``[words]``, but the items' default tab is the port's bag word when it has one
        (F64)."""
        if key == "codex_items":
            bag = getattr(self.port, "bag_word", None)
            word = bag() if bag is not None else ""
            if word:
                return word
        return self.ui.words.get(key)

    def _find(self, name: str | None) -> tuple[int | None, int | None]:
        if name is None:
            return None, None
        for t, tab in enumerate(self.tabs):
            for r, row in enumerate(tab.rows):
                if row.entry.name == name and not row.locked:
                    return t, r
        return None, None

    def _open_tab(self, tab: int, row: int | None) -> None:
        """Show ``tab`` with ``row`` selected (None: its first unlocked row, if any)."""
        self.tab = max(0, min(tab, len(self.tabs) - 1)) if self.tabs else 0
        rows = self.rows()
        self.list_rows = [ListRow(r.entry.title, not r.locked) for r in rows]
        if row is None:
            row = next((i for i, r in enumerate(rows) if not r.locked), None)
        self._fit_tab_labels()
        lst = self.list
        lst.scroll = 0.0
        lst.focus_row = row if row is not None else 0
        self._show(rows[row].entry if row is not None else None)
        if row is not None:
            lst.focus_index(row)

    def _fit_tab_labels(self) -> None:
        """I-12: each label cut with "…" so that its button and ◀ ▶ fit the row."""
        layout = self._layout_for(None)
        size = scaled(self.cfg.button.text_size, self.scale)
        room = max(1.0, layout.tab_label_width - PAGE_ROW_LABEL_PAD)
        self._tab_labels = tuple(self._fit(tab.label, room, size, self._measure)
                                 for tab in self.tabs)

    def rows(self) -> tuple[CodexRow, ...]:
        """The current tab's rows."""
        return self.tabs[self.tab].rows if self.tabs else ()

    # -- the detail --

    def _layout_for(self, entry: CodexEntry | None, title_lines: int = CODEX_TITLE_LINES
                    ) -> CodexLayout:
        cfg = self.cfg
        use = (self.use is not None and entry is not None and entry.kind == "item"
               and self.use.has(entry.name))                       # F64: Use's row
        return codex_layout(self.box, self.scale, tabs=len(self.tabs),
                            pick=self.pick is not None or use,
                            picture=entry is not None and entry.image is not None,
                            purse=self.show_purse and port_purse(self.port) is not None,
                            title_lines=title_lines, image_height=cfg.codex.image_height,
                            button_text_size=cfg.button.text_size,
                            button_min_height=cfg.button.height,
                            heading_size=cfg.panel.heading.text_size,
                            text_size=cfg.panel.text_size, list_row_min=cfg.list.row_height)

    def _show(self, entry: CodexEntry | None) -> None:
        """Make ``entry`` (None: nothing) the shown one: lay the detail out, place the
        widgets, and mark it read (§7.7)."""
        self.selected = entry.name if entry is not None else None
        detail = _Detail()
        lines = 1
        if entry is not None:
            base = self._layout_for(entry)
            detail.title = self._title_lines(entry.title, base.title.w)
            lines = len(detail.title)
        layout = self.layout = self._layout_for(entry, max(1, lines))
        self._place(layout)
        if entry is not None:
            detail.body = self._paragraphs(entry, layout.body.w)
        self._detail = detail
        self.body_heights = detail.body.heights
        self.body_pitch = detail.body.pitch
        self.body_rows = [ListRow("")] * len(detail.pages)
        body = self.body
        body.heights_changed()
        body.scroll = 0.0
        body.focus_row = 0
        while (index := self._unlaid_in_view()) is not None:   # only what is in view
            self._ensure(index)
        if entry is not None and not self.port.is_read(entry.name):
            self.port.mark_read(entry.name)

    def _place(self, layout: CodexLayout) -> None:
        row = self.tab_row
        row.placement = RowPlacement("topleft", (layout.box.x, layout.box.y))
        row.width = layout.tab_row.w if layout.tab_row is not None else layout.box.w
        lst = self.list
        lst.box = layout.list
        lst.row_height = layout.row_height
        self.body.box = layout.body
        if self.pick_button is not None and layout.pick is not None:
            self.pick_button.box = layout.pick
        if self.use_button is not None and layout.pick is not None:    # F64: Use
            pick = layout.pick
            half = round(pick.w / 2)
            self.use_button.box = (Box(pick.right - half, pick.y, half, pick.h)
                                   if self.use_hint() else pick)

    def _fit(self, text: str, width: float, size: int, measure) -> str:
        key = (text, width, size, measure is self._heading_measure)
        found = self._cache.titles.get(key)
        if found is None:
            found = self._cache.titles[key] = cut_to_width(text, width, size, measure)
            if len(self._cache.titles) > 4096:
                self._cache.titles.clear()
        return found

    def _title_lines(self, title: str, width: float) -> tuple[str, ...]:
        """The detail title: wrapped at ``width`` in ``panel.heading``, at most 2 lines,
        the second cut with "…"."""
        size = scaled(self.cfg.panel.heading.text_size, self.scale)
        lines = wrap_text(title, width, size, self._heading_measure) or [title]
        if len(lines) <= CODEX_TITLE_LINES:
            return tuple(lines)
        rest = " ".join(lines[CODEX_TITLE_LINES - 1:])
        last = cut_to_width(rest, width, size, self._heading_measure)
        return (*lines[:CODEX_TITLE_LINES - 1], last)

    def _paragraphs(self, entry: CodexEntry, width: float) -> _Body:
        """The entry's body at ``width`` and the text size, from the cache (per (entry,
        width, text size)) or new: no paragraph laid out yet, each row at its estimated
        height (04 §11 amendment: max(pitch, ceil(1.1 × plain width / width) × pitch), plus
        12 before the next one). ``_ensure`` lays the paragraphs out."""
        cfg = self.cfg
        size = scaled(cfg.panel.text_size, self.scale)
        p = pitch(size)
        key = (entry.name, entry.paragraphs, round(width, 3), size)
        layouts = self._cache.layouts
        found = layouts.get(key)
        if found is None:
            ctx = LayoutContext(self.ui.assets, self.ui.theme.faces, size,
                                _hex(cfg.panel.text_color), width, 1.0e9)
            n = len(entry.paragraphs)
            found = _Body(entry.paragraphs, ctx, [None] * n, [], p)
            for i, paragraph in enumerate(entry.paragraphs):
                plain = "".join(span.text for span in paragraph.plain())
                lines = math.ceil(LAZY_ESTIMATE * self._measure(plain, size) / max(1.0, width))
                found.heights.append(max(p, lines * p) + found.gap(i))
            layouts[key] = found
            while len(layouts) > BODY_LAYOUT_CACHE:
                del layouts[next(iter(layouts))]
        return found

    def _unlaid_in_view(self) -> int | None:
        """The first body row in view that isn't laid out yet, or None."""
        pages = self._detail.pages
        return next((i for i in self.body.visible_range() if i < len(pages)
                     and pages[i] is None), None)

    def _ensure(self, index: int) -> bool:
        """Lay out paragraph ``index`` of the shown body if it isn't yet (True): its real
        height replaces the estimate, and a row above the first visible one moves ``scroll``
        by the difference, so the view doesn't jump."""
        detail = self._detail.body
        if not 0 <= index < len(detail.pages) or detail.pages[index] is not None:
            return False
        page = LineLayout(detail.paragraphs[index], detail.ctx).page(0)
        self.layouts_made += 1
        body = self.body
        first = body.visible_range().start if self.body_rows else 0
        before = detail.heights[index]
        detail.pages[index] = page
        detail.heights[index] = (max(detail.pitch, sum(line.pitch for line in page.lines))
                                 + detail.gap(index))
        body.heights_changed()
        if index < first:
            body.scroll += detail.heights[index] - before
            body._clamp_scroll()
        return True

    def _fill_step(self) -> bool:
        """One ``update``'s share of the lazy body: a row in view first, else the first row
        not laid out; at most one paragraph."""
        index = self._unlaid_in_view()
        if index is None:
            index = self._detail.body.unlaid()
        return index is not None and self._ensure(index)

    # -- selection and focus --

    def _select_row(self, index: int) -> None:
        rows = self.rows()
        if 0 <= index < len(rows) and not rows[index].locked:
            if rows[index].entry.name != self.selected:
                self._show(rows[index].entry)

    def _follow_focus(self) -> None:
        """Keys: the detail follows the list's focused row."""
        self._select_row(self.list.focus_row)

    def _select_tab(self, index: int) -> None:
        if 0 <= index < len(self.tabs) and index != self.tab:
            self._open_tab(index, None)

    def _focus(self, w: "Widget | None") -> bool:
        scope = self._scope()
        return w is not None and scope is not None and scope.focus(w, InputKind.KEYS)

    def _can_focus(self, w: "Widget | None") -> bool:
        scope = self._scope()
        return scope is not None and scope.can_focus(w)

    def _row_activated(self, index: int) -> None:
        """Activate on a row: by a click, the row is already selected; by keys, it is shown
        and focus moves to the body (browse) or the pick button (pick)."""
        if self.list.clicked:
            self.list.clicked = False
            return
        self._select_row(index)
        target = self.pick_button if self.pick is not None else self.body
        self._focus(target)

    def _pick(self) -> None:
        if self.pick is not None and self.selected is not None:
            self.pick.on_pick(self.selected)

    def _route(self, w: "Widget | None", nav: Nav) -> bool:
        """UI-F21-03's moves that aren't F10's directional move. True: used."""
        if w is self.list:
            if nav is Nav.UP and len(self.tabs) > 1:
                enabled = [i for i, row in enumerate(self.list_rows) if row.enabled]
                if not enabled or self.list.focus_row <= enabled[0]:
                    self.tab_row.focus_button(("page", self.tab))
                    return self._focus(self.tab_row)
            elif nav is Nav.RIGHT:
                for target in (self.body, self.pick_button):
                    if target is not None and self._can_focus(target):
                        return self._focus(target)
            elif nav is Nav.ACTIVATE:
                self.list.clicked = False
                self.list.activate()
                return True
        elif w is self.body and nav is Nav.LEFT:
            return self._focus(self.list)
        elif w is not None and w is self.pick_button and nav is Nav.ACTIVATE:
            self.pick_button.activate()
            return True
        elif w is not None and w is self.use_button and nav is Nav.ACTIVATE:
            self.use_button.activate()
            return True
        return False

    # -- the host's calls --

    def update(self, dt: float) -> None:
        """A change of the port's tips or items (F23's ledger) lists it at once; when that
        changes which widgets are shown, ``groups_changed`` asks the host to build again.
        Before that, at most one more body paragraph is laid out (``_fill_step``)."""
        self._fill_step()
        signature = self._sign()
        if signature != self._signature:
            self._refresh()
        elif self.use is None:
            return
        shown = (len(self.tabs) > 1, bool(self.tabs), self.pick_button is not None
                 and bool(self.tabs), self._use_shown())
        if self._shown is not None and shown != self._shown:
            self.groups_changed = True

    def on_nav(self, nav: Nav) -> bool:
        """For a host that calls it before F10's move (F23): the routes of the focused
        widget. The game menu reaches the same routes through the widgets themselves."""
        scope = self._scope()
        return self._route(scope.focused if scope is not None else None, nav)

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """Mouse input no widget took: nothing (rows, tabs, and the wheel are the
        widgets')."""
        return False

    def default_widget(self) -> "Widget | None":
        """The list (its focused row is the selected one); None with no rows."""
        return self.list if self.list_rows else None

    # -- drawing --

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        """What isn't a scope widget: ``codex_empty`` with no tab; else the detail panel,
        the picture, and the title. F64: the purse first, when shown."""
        layout = self.layout
        self._draw_purse(p, layout)
        if not self.tabs or layout is None:
            p.text(self.ui.words.get("codex_empty"), self.box.center, area="list.empty",
                   anchor="center")
            return
        p.panel(layout.panel)
        name = self.selected
        if name is None:
            return
        entry = next((r.entry for r in self.rows() if r.entry.name == name), None)
        if entry is None:
            return
        if layout.picture is not None and entry.image is not None:
            self._draw_picture(canvas, entry.image, layout.picture)
        hint = self.use_hint()                                   # F64: "Belt: 2"
        if hint and layout.pick is not None:
            pick = layout.pick
            room = pick.w - round(pick.w / 2) - CODEX_GAP
            p.text(hint, (pick.x, pick.y + pick.h / 2), area="panel", anchor="midleft",
                   max_width=room)
        style = p.style("panel.heading")
        size = scaled(self.cfg.panel.heading.text_size, self.scale)
        font = dataclasses.replace(style.font, size=size)
        pt = pitch(size)
        for i, line in enumerate(self._detail.title):
            canvas.draw_text(line, font, style.text_color,
                             (layout.title.x, layout.title.y + i * pt + pt / 2),
                             anchor="midleft")

    def _draw_purse(self, p: "Painter", layout: CodexLayout | None) -> None:
        """F64: "Coins ×30" right-aligned in the purse strip (the layout's, else one made
        for the empty page)."""
        if not self.show_purse:
            return
        found = port_purse(self.port)
        if found is None:
            return
        box = layout.purse if layout is not None else None
        if box is None:
            box = self._layout_for(None).purse
        if box is None:
            return
        p.text(purse_text(*found), (box.right, box.y + box.h / 2), area="button",
               anchor="midright", max_width=box.w)

    def _draw_picture(self, canvas: "Canvas", image: str, box: Box) -> None:
        found = self.port.picture(image)
        if found is None:
            return
        if isinstance(found, str):
            assets = self.ui.assets
            ref = assets.image(found)
            if ref.is_placeholder:
                return                                  # F01 logged it once
            target = fit_picture(ref.size, box)
            rect = canvas.rect_to_px((target.x, target.y, target.w, target.h))
            if rect.width <= 0 or rect.height <= 0:
                return
            surface, _offset = assets.variant(ref, rect.size, canvas.quality)
            canvas.surface.blit(surface, rect.topleft)
            return
        target = fit_picture(SOLID_ASPECT, box, upscale=True)
        canvas.fill(tuple(found)[:3], (target.x, target.y, target.w, target.h))

    def _draw_row(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        rows = self.rows()
        if not 0 <= index < len(rows):
            return
        row = rows[index]
        cfg = self.cfg
        canvas = p.canvas
        cy = box.y + box.h / 2
        size = scaled(cfg.button.text_size, self.scale)
        font = dataclasses.replace(self._label_font, size=size)
        if row.locked:
            canvas.draw_text(self.ui.words.get("codex_locked"), font, locked_color(cfg),
                             (box.x + CODEX_TITLE_X, cy), anchor="midleft")
            return
        name = row.entry.name
        if name == self.selected:
            p.widget_frame(box, "list", Look(look.state, None, True), marker=False)
        assert self.layout is not None
        title = self._fit(row_title(self.port, row.entry), self.layout.title_width, size,
                          self._measure)
        canvas.draw_text(title, font, cfg.button.text_color, (box.x + CODEX_TITLE_X, cy),
                         anchor="midleft")
        if not self.port.is_read(name):
            r = CODEX_DOT / 2
            p.ellipse(Box(box.right - CODEX_DOT_INSET - r, cy - r, CODEX_DOT, CODEX_DOT),
                      new_dot_color(cfg))

    def _draw_paragraph(self, p: "Painter", index: int, box: Box) -> None:
        """Paragraph ``index``'s lines from ``box``'s top, a run of glyphs of one face,
        size, and color per ``draw_text`` (baselines from the layout)."""
        pages = self._detail.pages
        if not 0 <= index < len(pages) or pages[index] is None:
            return                                      # not laid out yet: drawn next frame
        canvas = p.canvas
        for line in pages[index].lines:
            baseline = box.y + line.baseline
            run: list[str] = []
            run_key: tuple | None = None
            run_x = 0.0
            for glyph in line.glyphs:
                if glyph.hangs:
                    continue
                key = (glyph.face, glyph.size, glyph.color)
                if key != run_key:
                    if run and run_key is not None:
                        self._draw_run(canvas, "".join(run), run_key, box.x + run_x, baseline)
                    run, run_key, run_x = [], key, glyph.x
                run.append(glyph.text)
            if run and run_key is not None:
                self._draw_run(canvas, "".join(run), run_key, box.x + run_x, baseline)

    @staticmethod
    def _draw_run(canvas: "Canvas", text: str, key: tuple, x: float, baseline: float) -> None:
        face, size, color = key
        if not text.strip():
            return
        font: FontSpec = font_spec(face, size)
        ascent = canvas.font_handle(font, size).font.get_ascent()
        canvas.draw_text(text, font, _rgb(color), (x, baseline - ascent))


# --- The page ------------------------------------------------------------------------------------

class CodexPage(MenuPageBase):
    """The ``codex`` page (``MenuPage``): one ``CodexView`` over the whole body slot. From
    the title (``from_title``) it lists tips only."""

    heading = HEADING

    def __init__(self, port: CodexPort, *, from_title: bool,
                 use: UseAction | None = None) -> None:
        self.port = port
        self.from_title = from_title
        self.use = use                                  # F64 round 2: the game menu's
        self.host: "PageHost | None" = None
        self.view: CodexView | None = None

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        if self.view is None:
            self.view = CodexView(self.port, ui=host.shell, title=self.from_title,
                                  scope=lambda: host.scope, purse=not self.from_title,
                                  use=self.use)
        return self.view.build(body, host.painter.text_scale())

    def update(self, dt: float) -> None:
        view = self.view
        if view is not None:
            view.update(dt)
            if view.groups_changed and self.host is not None:
                self.host.rebuild()

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        if self.view is not None:
            self.view.draw(canvas, p)

    def on_nav(self, d: Nav) -> bool:
        return self.view.on_nav(d) if self.view is not None else False

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        return self.view.on_mouse(kind, pos, notches=notches) if self.view is not None \
            else False

    def default_widget(self) -> "Widget | None":
        return self.view.default_widget() if self.view is not None else None


__all__ = ["CodexFilter", "CodexPage", "CodexPort", "CodexRow", "CodexTab", "CodexUi",
           "CodexView", "PickAction", "UseAction", "category_key", "codex_tabs", "fit_picture",
           "locked_color", "new_dot_color", "port_count", "port_listed", "port_purse", "purse_text",
           "row_title"]
