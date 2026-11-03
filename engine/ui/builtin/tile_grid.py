"""``TileGrid``: pages of picture tiles in a body slot, reusable (F34 ``01-design.md`` §6.2
UI-F34-01 to 03; ``04-technical.md`` §3, §7.2, §7.4).

Why this module exists: F34's Gallery page and F36's Scenes page both show things the
player has unlocked as captioned pictures, 12 to a page, with ``???`` for the locked ones.
The grid is one view; each page only turns its own data into ``Tile`` values and says what
activating one does.

- **Layout** (``tile_grid_layout``, pure): 4 columns × 3 rows of 188×138 tiles (a 188×106
  picture box, its caption 8 below and 24 tall), 16 apart, centred in the body slot (the
  first tile at (420, 112) in F10's slot (416, 112, 808×552)); row pitch 154. F11's page
  row (midbottom at the slot's bottom centre) shows only with more than 12 tiles.
- **Tiles.** Unlocked: the thumbnail (``ThumbCache``, centre-cropped to cover the box) or a
  solid colour, framed in ``button.border_*`` (focused: ``button.focused.border_*``); the
  caption in ``gallery.caption.text_size`` and ``panel.text_color``, centred, cut with "…"
  to the tile width at the text size (F16 150 %: re-measured, cached per title and size).
  Locked: the box in ``panel.fill_color`` with ``button.border_*`` and the locked word
  centred in ``button.disabled.text_color``; no caption; never focused. A thumbnail not made
  yet: the locked look without the word. ``count`` ≥ 2: a 32×24 pill 6 inside the box's
  bottom right (``panel.fill_color``, the number in ``panel.text_color`` at 18).
- **Keys** (F10's ``Grid``): Right and Left go to the next and previous unlocked tile in
  reading order (Right after a row's last tile goes on to the next row), but Left from the
  first column leaves the grid for the host's edge rule (the sidebar); Up and Down use F10's
  ``move_target`` over the unlocked tiles, and Up with no unlocked tile above goes to the
  page row. Home / End, Tab through the tiles. Page Up / Page Down (and the bumpers, a
  page's ``nav_extras``) and the wheel turn pages through ``on_nav`` / ``on_mouse``, keeping
  the focused position or moving to the nearest unlocked tile. Activate or a click calls ``on_activate(tile)``.
- **Thumbnails.** Building or turning a page ``want``s that page's unlocked pictures;
  ``update`` pumps the cache (one thumbnail at most per frame); drawing never decodes.

Theme: ``gallery.caption.text_size`` (20 until the config has it: ``caption_size``).
"""

import dataclasses
import math
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from engine.render.frames import FrameSpec
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import PAGE_BODY, PAGE_ROW_PLACEMENT, RowPlacement, cut_to_width, scaled
from engine.ui.nav import PAGE_KEYS, InputKind, Nav
from engine.ui.page_row import PageRow
from engine.ui.theme import measure_with
from engine.ui.widgets import Grid, GridCell, Look, LookState, MouseKind

if TYPE_CHECKING:
    from engine.core.config_schema import ThemeConfig
    from engine.render.canvas import Canvas
    from engine.ui.focus import FocusScope
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme, Words
    from engine.ui.thumbs import ThumbCache
    from engine.ui.widgets import Widget

RGB = tuple[int, int, int]
Picture = str | RGB | None            # a file ref, a solid colour, or nothing (the empty look)

COLUMNS: Final = 4
ROWS: Final = 3
PER_PAGE: Final = COLUMNS * ROWS
TILE: Final = (188, 138)
PICTURE: Final = (188, 106)
CAPTION_GAP: Final = 8
CAPTION_HEIGHT: Final = 24
GAP: Final = 16
BADGE: Final = (32, 24)
BADGE_INSET: Final = 6
BADGE_TEXT: Final = 18                # not scaled by F16's text size: it must fit the pill
CAPTION_SIZE: Final = 20              # gallery.caption.text_size default (14–32)
CAPTION_CACHE: Final = 2048


@dataclass(frozen=True)
class Tile:
    """One tile. ``key`` names it to its page (F34: the entry's picture; F36: the label);
    ``count`` ≥ 2 shows the badge."""

    key: Hashable
    picture: Picture = None
    caption: str = ""
    locked: bool = False
    count: int = 0


@dataclass(frozen=True)
class TileGridLayout:
    grid: Box                          # the 3 rows of tiles
    tiles: tuple[Box, ...]             # PER_PAGE tile boxes, reading order
    pictures: tuple[Box, ...]
    captions: tuple[Box, ...]
    row: RowPlacement                  # where the page row sits


def tile_grid_layout(body: Box = PAGE_BODY) -> TileGridLayout:
    """UI-F34-01 in ``body`` (pure)."""
    tw, th = TILE
    width = COLUMNS * tw + (COLUMNS - 1) * GAP
    x0, y0 = body.x + (body.w - width) / 2, body.y
    tiles, pictures, captions = [], [], []
    for index in range(PER_PAGE):
        row, col = divmod(index, COLUMNS)
        x, y = x0 + col * (tw + GAP), y0 + row * (th + GAP)
        tiles.append(Box(x, y, tw, th))
        pictures.append(Box(x, y, *PICTURE))
        captions.append(Box(x, y + PICTURE[1] + CAPTION_GAP, tw, CAPTION_HEIGHT))
    grid = Box(x0, y0, width, ROWS * th + (ROWS - 1) * GAP)
    return TileGridLayout(grid, tuple(tiles), tuple(pictures), tuple(captions),
                          RowPlacement("midbottom", (body.x + body.w / 2, body.bottom)))


def caption_size(cfg: "ThemeConfig") -> int:
    """``gallery.caption.text_size`` (20 before the config has the ``gallery`` area)."""
    area = getattr(cfg, "gallery", None)
    caption = getattr(area, "caption", None)
    return int(getattr(caption, "text_size", CAPTION_SIZE))


def word_or(words: "Words", key: str, default: str) -> str:
    """``words.get(key)``, or ``default`` before the config has that word."""
    try:
        return words.get(key)
    except KeyError:
        return default


def nearest(enabled: Sequence[int], index: int) -> int | None:
    """The enabled index closest to ``index`` (the earlier one on a tie)."""
    return min(enabled, key=lambda i: (abs(i - index), i), default=None)


class TileUi(Protocol):
    """What the grid draws with (``GameShell`` has all three)."""

    theme: "UiTheme"
    words: "Words"
    assets: Any


# --- The widget ----------------------------------------------------------------------------

class TileCells(Grid):
    """The tiles of the shown page as one F10 ``Grid`` (one focus stop with parts): locked
    tiles are disabled cells; page keys and the wheel are the view's; Up with no unlocked
    tile above goes to the page row; drawn by the view's rules (module docstring)."""

    def __init__(self, view: "TileGrid") -> None:
        self.view = view
        self.pointer_off = False      # the pointer is over no unlocked tile
        super().__init__(lambda: view.cells, COLUMNS, TILE, GAP, view._activated,
                         tab_cells=True, enabled=lambda: any(c.enabled for c in view.cells))

    def _sync(self) -> list[GridCell]:
        cells = list(self.cells())
        enabled = [i for i, c in enumerate(cells) if c.enabled]
        if not (0 <= self.focus_cell < len(cells)) or not cells[self.focus_cell].enabled:
            found = nearest(enabled, self.focus_cell)
            self.focus_cell = found if found is not None else 0
        self.scroll = 0.0
        return cells

    def on_nav(self, d: Nav) -> bool:
        if d in PAGE_KEYS:
            return False                                       # the view turns pages
        self.pointer_off = False
        if d in (Nav.LEFT, Nav.RIGHT):
            return self._reading_step(d)
        if super().on_nav(d):
            return True
        if d is Nav.UP:
            return self.view.focus_row()
        return False

    def _reading_step(self, d: Nav) -> bool:
        """Right: the next unlocked tile in reading order (the next row after the last
        column). Left: the previous one, but never from the first column (the host's edge
        rule takes it to the sidebar). False: none, so focus may leave the grid."""
        cells = self._sync()
        cur = self.focus_cell
        enabled = [i for i, c in enumerate(cells) if c.enabled]
        if d is Nav.RIGHT:
            target = min((i for i in enabled if i > cur), default=None)
        elif cur % COLUMNS == 0:
            return False
        else:
            target = max((i for i in enabled if i < cur), default=None)
        if target is None:
            return False
        self.focus_index(target)
        return True

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if kind == "wheel":
            return self.view.wheel(notches)
        used = super().on_mouse(kind, pos, notches=notches)
        if kind == "hover":
            index = self.cell_at(pos)
            cells = self.view.cells
            self.pointer_off = index is None or not cells[index].enabled
            return used or self.pointer_off
        return used

    def cell_state(self, index: int, cell: GridCell, look: Look) -> LookState:
        state = super().cell_state(index, cell, look)
        if state in ("focused", "pressed") and self.pointer_off \
                and self.view.focus_source() is InputKind.MOUSE:
            return "normal"
        return state

    def draw(self, p: "Painter", look: Look) -> None:
        cells = self._sync()
        for index in range(len(cells)):
            self.view.draw_tile(p, index, Look(self.cell_state(index, cells[index], look)))


# --- The view ------------------------------------------------------------------------------

class TileGrid:
    """Pages of tiles in a body slot (module docstring). ``ui`` gives the theme, words, and
    assets; ``thumbs`` the launch's ``ThumbCache``; ``scope`` the host's ``FocusScope``;
    ``locked_word`` the locked tiles' text; ``on_activate(tile)`` opens a tile;
    ``changed()`` is called when what is drawn changes (a host's fade layer)."""

    def __init__(self, *, ui: TileUi, thumbs: "ThumbCache",
                 on_activate: Callable[[Tile], None],
                 scope: "Callable[[], FocusScope | None]" = lambda: None,
                 locked_word: Callable[[], str] = lambda: "???",
                 changed: Callable[[], None] | None = None) -> None:
        self.ui = ui
        self.thumbs = thumbs
        self.on_activate = on_activate
        self._scope = scope
        self.locked_word = locked_word
        self.changed = changed if changed is not None else (lambda: None)
        cfg = ui.theme.cfg
        self.cfg = cfg
        self.tiles: tuple[Tile, ...] = ()
        self.page = 0
        self.cells: list[GridCell] = []
        self.layout = tile_grid_layout()
        self.scale = 1.0
        self.groups_changed = False   # the page row came or went: the host builds again
        self._captions: dict[tuple, str] = {}
        self._caption_font = ui.theme.font(caption_size(cfg))
        self._measure = measure_with(ui.assets, self._caption_font)
        button = cfg.button
        self.cells_widget = TileCells(self)
        self.row = PageRow(lambda: [str(i + 1) for i in range(self.pages)], lambda: self.page,
                           self.turn_to,
                           measure=measure_with(ui.assets, ui.theme.font(button.text_size)),
                           scale=lambda: self.scale, text_size=button.text_size,
                           height=button.height, width=PAGE_BODY.w,
                           placement=PAGE_ROW_PLACEMENT)

    # -- model --

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.tiles) / PER_PAGE))

    def page_tiles(self) -> tuple[Tile, ...]:
        start = self.page * PER_PAGE
        return self.tiles[start:start + PER_PAGE]

    def set_tiles(self, tiles: Sequence[Tile]) -> None:
        """Show ``tiles``; the page and the focused tile stay where they can (by key)."""
        old = self.page_tiles()
        focused = old[self.cells_widget.focus_cell].key \
            if 0 <= self.cells_widget.focus_cell < len(old) else None
        had_row = self.pages > 1
        self.tiles = tuple(tiles)
        keys = [t.key for t in self.tiles]
        if focused in keys:
            index = keys.index(focused)
            self.page, self.cells_widget.focus_cell = divmod(index, PER_PAGE)
        self.page = min(self.page, self.pages - 1)
        self._show_page()
        if (self.pages > 1) != had_row:
            self.groups_changed = True

    def _show_page(self) -> None:
        tiles = self.page_tiles()
        self.cells = [GridCell(t.caption, not t.locked) for t in tiles]
        self.cells_widget._sync()
        self.thumbs.want(t.picture for t in tiles if not t.locked and isinstance(t.picture, str))
        self.changed()

    # -- the host's calls --

    def build(self, body: Box, text_scale: float) -> list[FocusGroup]:
        """Lay out in ``body`` at ``text_scale``; the focus groups (the page row only with
        more than one page)."""
        self.layout = tile_grid_layout(body)
        self.scale = text_scale
        self.cells_widget.box = self.layout.grid
        self.row.placement = self.layout.row
        self.row.width = body.w
        self.groups_changed = False
        widgets: list["Widget"] = [self.cells_widget]
        if self.pages > 1:
            widgets.append(self.row)
        return [FocusGroup(widgets)]

    def update(self, dt: float) -> None:
        """At most one thumbnail made (``ThumbCache.pump``)."""
        if self.thumbs.pump() is not None:
            self.changed()

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        """Nothing beyond the widgets (the host draws ``cells_widget`` and ``row``)."""

    def on_nav(self, nav: Nav) -> bool:
        """Page Up / Page Down (and the bumpers): the previous / next page."""
        if nav not in PAGE_KEYS:
            return False
        return self.turn(-1 if nav is Nav.PAGE_UP else 1)

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """The wheel anywhere in the slot turns pages."""
        return kind == "wheel" and self.wheel(notches)

    def wheel(self, notches: int) -> bool:
        if notches == 0:
            return False
        return self.turn(-1 if notches > 0 else 1)

    def default_widget(self) -> "Widget | None":
        """C1: the tiles (focused on the first unlocked one of the page); the page row when
        the page has none; None with neither."""
        if any(c.enabled for c in self.cells):
            return self.cells_widget
        return self.row if self.pages > 1 else None

    # -- pages and focus --

    def turn(self, delta: int) -> bool:
        return self.turn_to(self.page + delta)

    def turn_to(self, page: int) -> bool:
        """Show ``page`` (no wrap); the focused position stays, or the nearest unlocked."""
        if not 0 <= page < self.pages or page == self.page:
            return False
        self.page = page
        self._show_page()
        self.row.current_changed()
        return True

    def focus_key(self, key: Hashable, by: InputKind = InputKind.KEYS) -> bool:
        """Turn to ``key``'s page and focus its tile (drawn focused for keys). False: no
        such unlocked tile, or the host can't focus it now."""
        target = self.widget_for(key)
        scope = self._scope()
        if target is None or scope is None or not scope.can_focus(target):
            return False
        self.cells_widget.pointer_off = False
        return scope.focus(target, by, sound=False, visible=by is InputKind.KEYS)

    def widget_for(self, key: Hashable) -> "Widget | None":
        """Turn to ``key``'s page with its tile as the focused cell, and return the widget
        to focus (``MenuPageBase.widget_for``); None for a locked or unknown key."""
        index = next((i for i, t in enumerate(self.tiles) if t.key == key), None)
        if index is None or self.tiles[index].locked:
            return None
        page, cell = divmod(index, PER_PAGE)
        if page != self.page:
            self.page = page
            self._show_page()
            self.row.current_changed()
        else:
            self._show_page()          # want this page's thumbnails again (after a viewer)
        self.cells_widget.focus_cell = cell
        return self.cells_widget

    def focus_row(self) -> bool:
        scope = self._scope()
        if self.pages <= 1 or scope is None or not scope.can_focus(self.row):
            return False
        self.row.current_changed()
        return scope.focus(self.row, InputKind.KEYS)

    def focus_source(self) -> InputKind | None:
        scope = self._scope()
        return scope.source if scope is not None else None

    def _activated(self, index: int) -> None:
        tiles = self.page_tiles()
        if 0 <= index < len(tiles) and not tiles[index].locked:
            self.on_activate(tiles[index])

    # -- drawing --

    def caption(self, text: str) -> str:
        """``text`` cut with "…" to the tile width at the caption size now (cached)."""
        size = scaled(caption_size(self.cfg), self.scale)
        key = (text, size)
        found = self._captions.get(key)
        if found is None:
            if len(self._captions) >= CAPTION_CACHE:
                self._captions.clear()
            found = self._captions[key] = cut_to_width(text, TILE[0], size, self._measure)
        return found

    def draw_tile(self, p: "Painter", index: int, look: Look) -> None:
        tiles = self.page_tiles()
        if not 0 <= index < len(tiles):
            return
        tile = tiles[index]
        cfg = self.cfg
        canvas = p.canvas
        box = self.layout.pictures[index]
        drawn = False
        if not tile.locked:
            drawn = self._draw_picture(canvas, tile.picture, box)
        if not drawn:
            canvas.fill(tuple(cfg.panel.fill_color), (box.x, box.y, box.w, box.h))
        focused = look.state in ("focused", "pressed")
        border = cfg.button.focused if focused else cfg.button
        p.shape(box, FrameSpec(tuple(cfg.panel.fill_color), 0.0, tuple(border.border_color),
                               border.border_width))
        if tile.locked:
            style = p.style("button", "disabled")
            font = dataclasses.replace(style.font, size=scaled(cfg.button.text_size,
                                                               self.scale))
            canvas.draw_text(self.locked_word(), font, tuple(cfg.button.disabled.text_color),
                             box.center, anchor="center")
            return
        if tile.caption:
            cap = self.layout.captions[index]
            font = dataclasses.replace(self._caption_font,
                                       size=scaled(caption_size(cfg), self.scale))
            canvas.draw_text(self.caption(tile.caption), font, tuple(cfg.panel.text_color),
                             cap.center, anchor="center")
        if tile.count >= 2:
            bw, bh = BADGE
            pill = Box(box.right - BADGE_INSET - bw, box.bottom - BADGE_INSET - bh, bw, bh)
            p.shape(pill, FrameSpec(tuple(cfg.panel.fill_color), 1.0, corner_radius=bh // 2))
            font = dataclasses.replace(self._caption_font, size=BADGE_TEXT)
            canvas.draw_text(str(tile.count), font, tuple(cfg.panel.text_color), pill.center,
                             anchor="center")

    def _draw_picture(self, canvas: "Canvas", picture: Picture, box: Box) -> bool:
        """The thumbnail or colour covering ``box``; False when there is nothing to draw
        yet (no picture, or the thumbnail isn't made)."""
        if picture is None:
            return False
        if not isinstance(picture, str):
            canvas.fill(tuple(picture)[:3], (box.x, box.y, box.w, box.h))
            return True
        rect = canvas.rect_to_px((box.x, box.y, box.w, box.h))
        if rect.width <= 0 or rect.height <= 0:
            return True
        thumb = self.thumbs.get(picture, rect.size)
        if thumb is None:
            return False
        surface = canvas.surface
        assert surface is not None
        surface.blit(thumb, rect.topleft)
        return True


__all__ = ["BADGE", "CAPTION_SIZE", "COLUMNS", "GAP", "PER_PAGE", "PICTURE", "ROWS", "TILE",
           "Picture", "Tile", "TileCells", "TileGrid", "TileGridLayout", "TileUi", "caption_size",
           "nearest", "tile_grid_layout", "word_or"]
