"""``SavePage``: the Save and Load pages of the game menu, also opened from the title (F11
``04-technical.md`` §5.3, §7.7; ``03-ui.md`` "Screens and elements" to "Interaction"; C1).

Why this module exists: the player picks a slot to save into or load from, sees what each
slot holds (picture, date, line), and deletes or overwrites with a question first. The page
only shows and asks; every slot fact comes from a ``SlotsPort`` that ``app/saves.py``
builds over ``SaveService`` (**ui never imports persist**: ``SlotView`` and ``SlotsPort``
are defined here and the app converts persist's heads into them). Every save string reaches
this page already cleaned by the app (``04`` §7.7 render-safe text) and is drawn as plain
text with ``Canvas.draw_text``: never ``TaggedText``, never a ``{var}`` lookup.

- **Layout** (``layouts.save_layout``, 03-ui Fit table): F10's ``Grid`` of 3 × 2 cells,
  256 × C at x 416, 692, 968 from y 112, rows g apart, drawn as buttons without the focus
  marker; the shared ``PageRow`` under it (Load: Auto, Quick, 1–N; Save: 1–N). A blocked
  page (F32) shows its reason instead of both; a Load page with no save anywhere shows "No
  saves yet." instead of the grid and keeps the row.
- **Cells by state** (03-ui "Cell contents by state"): filled (thumbnail, label tag,
  "Newest" on Auto and Quick, date, description; a missing or refused picture is the
  placeholder with "No picture" or ``save.no_picture_image``); empty, loading, damaged,
  newer, other game (the placeholder area with its words, wrapped); a load in progress adds
  a centered "Loading…" tag. The × shows on the focused, deletable cell; hovering it gives
  the pressed fill and a 2-unit ring. Tags, dates, and messages step down by 2 (not below
  24) and then end in "…".
- **Thumbnails** arrive as 320×180 surfaces (decoded lazily by the app for the shown page,
  ``("save-thumb", slot, stamp)`` in ``assets.cache``); the device-size variant is cached
  beside them under the same key plus its size.
- **Input** (03-ui Interaction): choose (click, Enter, Space, south), delete (×, Delete,
  Backspace, west: ``nav_extras``), Page Up / Page Down and the bumpers (previous / next
  page, no wrap, repeating while held), F10's moves over cells and the row (Left from the
  leftmost widget returns to the sidebar), Home / End (cells 1 and 6), Tab (cells 1–6, then
  the row). The wheel, F5, and F9 do nothing here. While a load is being checked the page
  takes no input; for a file over 1 MiB (``port.load_indicator()``, F11 G3) the badge frame
  also draws F10's loading indicator at (1264, 708), once (the read is one step).
- **Focus** (C1): the default widget is the grid, on the cell with the shown page's newest
  save (else cell 1); a page change keeps the cell position; a focused page button follows
  the new current page.
- **Back.** From the game menu Back closes the page (F10); opened from the quick menu's Save
  it closes the whole menu (``from_quick``, dropped by switching to another entry).
"""

import dataclasses
import math
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

import pygame

from engine.core.constants import ENTRY_OVERHEAD
from engine.render.frames import FrameSpec
from engine.render.text import FontSpec, text_width
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import (PAGE_BODY, PAGE_MESSAGE_WRAP, SAVE_TAG_PAD_X, SaveLayout,
                               cut_to_width, fit_message, pitch, save_layout)
from engine.ui.loading_indicator import draw_loading_indicator
from engine.ui.menus import EntryContext, MenuEntry, MenuPageBase
from engine.ui.nav import PAGE_KEYS, InputKind, Nav
from engine.ui.paint import fit_label, frame_state
from engine.ui.page_row import PageRow
from engine.ui.theme import measure_with
from engine.ui.widgets import Grid, GridCell, Look, LookState, MouseKind

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.shell import GameShell

Mode = Literal["save", "load"]
SlotPage = str | int                  # "auto", "quick", or 1 … pages (persist's, as plain data)
SlotState = Literal["empty", "loading", "filled", "damaged", "newer", "other_game"]

SLOTS: Final = 6
TAG_RADIUS: Final = 8
DELETE_STROKE: Final = (14, 3)        # the ×: two strokes 14 long, 3 wide
DELETE_RING: Final = 2
MESSAGE_PAD: Final = 8                # the placeholder message's side inset
THUMB_VARIANTS: Final = 24            # page-local scaled thumbnails without a cache key
FIT_MARGIN: Final = 0.5               # a fitted text is strictly narrower than its line

# A state's placeholder words ([words] keys).
STATE_WORDS: Final = {"empty": "save_empty", "loading": "save_loading",
                      "damaged": "save_damaged", "newer": "save_newer",
                      "other_game": "save_other_game"}
_CELLS: Final = tuple(GridCell() for _ in range(SLOTS))


@dataclass(frozen=True, eq=False)
class SlotView:
    """What a cell shows (``04`` §5.3). Texts are plain, render-safe, and cut by the app.
    ``thumb`` is the 320×180 picture (None: "No picture"); ``thumb_key`` its cache key
    (``("save-thumb", slot, stamp)``; None for a picture not from a file)."""

    label: str                        # "Slot 3", "Auto 2", "Quick 1"
    state: SlotState
    date: str = ""
    description: str = ""
    thumb: "pygame.Surface | None" = None
    newest: bool = False
    deletable: bool = False
    busy: bool = False                # a load of this slot is being checked
    version: str | None = None        # PR-F11-39's badge (Could; the app passes None)
    thumb_key: Hashable | None = None


class SlotsPort(Protocol):
    """What the page reads and calls (``app/saves.py``'s ``SaveSlots``)."""

    def pages(self, mode: Mode) -> list[SlotPage]: ...

    def page_label(self, page: SlotPage) -> str: ...

    def initial_page(self, mode: Mode) -> SlotPage: ...

    def views(self, page: SlotPage) -> list[SlotView]: ...  # 6; reading starts per open

    def default_cell(self, page: SlotPage) -> int: ...

    def blocked(self, mode: Mode) -> str | None: ...

    def no_saves(self) -> bool: ...

    def busy(self) -> bool: ...

    def load_indicator(self) -> bool: ...                   # busy with a file over 1 MiB

    def remember(self, mode: Mode, page: SlotPage) -> None: ...  # also: reading stops

    def choose(self, page: SlotPage, i: int, mode: Mode, by: InputKind) -> None: ...

    def delete(self, page: SlotPage, i: int, by: InputKind) -> None: ...


# --- The grid ------------------------------------------------------------------------------

class SlotGrid(Grid):
    """F10's ``Grid`` with the slot rules: Page Up / Page Down are the page's (not row
    moves); Delete / west deletes the focused cell; the × of the focused, deletable cell
    takes its own click; the wheel does nothing; everything is ignored while a load is
    being checked."""

    def __init__(self, page: "SavePage", layout: SaveLayout) -> None:
        self.page = page
        self.delete_hover = False
        self._delete_press: int | None = None
        self._click_delete: int | None = None
        super().__init__(lambda: _CELLS, 3, (0, 0), 0, page._choose, page._draw_cell,
                         tab_cells=True)
        self.fit(layout)

    def fit(self, layout: SaveLayout) -> None:
        first = layout.cells[0].box
        second = layout.cells[1].box
        self.cell = (int(first.w), int(first.h))
        self.gap = int(second.x - first.right)
        self.row_gap = layout.gap
        self.box = layout.grid

    def on_nav(self, d: Nav) -> bool:
        if self.page.busy():
            return True                                       # no input while checking
        self.delete_hover = False
        if d in PAGE_KEYS:
            return False                                      # the page changes page
        if d is Nav.DELETE:
            self.page._delete(self.focus_cell)
            return True
        return super().on_nav(d)

    def activate(self) -> None:
        index, self._click_delete = self._click_delete, None
        if index is not None:
            self.page._delete(index)
            return
        if not self.page.busy():
            super().activate()

    def delete_at(self, pos: tuple[float, float]) -> int | None:
        """The cell whose × is under ``pos`` (the focused, deletable cell only)."""
        index = self.cell_at(pos)
        if index is None or index != self.focus_cell or self.page.busy():
            return None
        view = self.page.view(index)
        if view is None or not view.deletable:
            return None
        hit = self.page.cell_part(index, self.cell_box(index)).delete_hit
        return index if hit.contains(pos) else None

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if kind == "wheel" or self.page.busy():
            return False
        if kind == "hover":
            changed = super().on_mouse(kind, pos)
            hover = self.delete_at(pos) is not None
            if hover != self.delete_hover:
                self.delete_hover = hover
                changed = True
            return changed
        if kind == "down":
            hit = self.delete_at(pos)
            self._delete_press = hit
            if hit is not None:
                self.pressed_cell = None
                return True
        return super().on_mouse(kind, pos, notches=notches)

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        press, self._delete_press = self._delete_press, None
        if press is not None:
            if self.delete_at(pos) == press:
                self._click_delete = press
                return True
            self.pressed_cell = None
            return False
        return super().accepts_click(pos)

    def cell_state(self, index: int, cell: GridCell, look: Look) -> LookState:
        state = super().cell_state(index, cell, look)
        if state == "pressed" and self._delete_press is not None:
            return "focused"                                  # pressing the ×, not the cell
        return state


# --- The page ------------------------------------------------------------------------------

class SavePage(MenuPageBase):
    """The ``save`` or ``load`` page (``mode``). ``from_quick``: opened by the quick menu's
    Save, so Back closes the whole menu."""

    nav_extras = frozenset({"shoulders", "delete"})

    def __init__(self, port: SlotsPort, mode: Mode, *, from_quick: bool = False) -> None:
        assert mode in ("save", "load"), mode
        self.port = port
        self.mode = mode
        self.heading = mode                                   # the [words] key
        self.from_quick = from_quick
        self.host: "PageHost | None" = None
        self.pages: list[SlotPage] = list(port.pages(mode))
        start = port.initial_page(mode)
        self.page: SlotPage = start if start in self.pages else self.pages[0]
        self.views: list[SlotView] = []
        self.layout: SaveLayout | None = None
        self.grid: SlotGrid | None = None
        self.row: PageRow | None = None
        self._shape: tuple | None = None
        self._signature: tuple | None = None
        self._fits: dict[tuple, tuple[str, int]] = {}
        self._scaled: dict[tuple, tuple["pygame.Surface", "pygame.Surface"]] = {}

    # -- reads --

    @property
    def shell(self) -> "GameShell":
        assert self.host is not None
        return self.host.shell

    def busy(self) -> bool:
        return self.port.busy()

    def view(self, index: int) -> SlotView | None:
        return self.views[index] if 0 <= index < len(self.views) else None

    def page_index(self) -> int:
        return self.pages.index(self.page)

    def _by(self) -> InputKind:
        """The input kind of the event being handled (the host's), keys if unknown."""
        kind = getattr(self.host, "input_kind", None)
        return kind if isinstance(kind, InputKind) else InputKind.KEYS

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        first = self.host is None
        self.host = host
        cfg = host.shell.theme.cfg
        self.layout = save_layout(host.painter.text_scale(), text_size=cfg.save.text_size,
                                  button_text_size=cfg.button.text_size,
                                  button_min_height=cfg.button.height)
        self._fits.clear()
        self._refresh()
        blocked = self.port.blocked(self.mode)
        no_saves = self.mode == "load" and self.port.no_saves()
        self._shape = (blocked, no_saves)
        if blocked is not None:
            return []
        if self.grid is None:
            self.grid = SlotGrid(self, self.layout)
        else:
            self.grid.fit(self.layout)
        if first:
            self.grid.focus_cell = self._default_cell()
        if self.row is None:
            fixed = sum(1 for page in self.pages if isinstance(page, str))
            self.row = PageRow(lambda: [self.port.page_label(pg) for pg in self.pages],
                               self.page_index, self._select, fixed=fixed,
                               measure=measure_with(host.shell.assets,
                                                    host.shell.theme.font(cfg.button.text_size)),
                               scale=host.painter.text_scale, text_size=cfg.button.text_size,
                               height=cfg.button.height, width=PAGE_BODY.w)
        widgets = [self.row] if no_saves else [self.grid, self.row]
        return [FocusGroup(list(widgets))]

    def update(self, dt: float) -> None:
        self._refresh()
        shape = (self.port.blocked(self.mode), self.mode == "load" and self.port.no_saves())
        if shape != self._shape and self.host is not None:
            self.host.rebuild()                               # the grid comes or goes

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        """The page message (F32's reason, or "No saves yet."), and F10's loading indicator
        while a load of a file over 1 MiB is being checked (G3); the grid and row are scope
        widgets, drawn by the host."""
        if self._shape is None or self.layout is None:
            return
        if self.busy() and self.port.load_indicator():
            shell = self.shell
            draw_loading_indicator(canvas, shell.words.get("loading"),
                                   shell.theme.cfg.title.loading.text_color,
                                   bright=None if getattr(shell, "reduce_motion", False) else 0)
        blocked, no_saves = self._shape
        text = blocked if blocked is not None else (
            self.shell.words.get("save_none") if no_saves else None)
        if not text:
            return
        style = p.style("list.empty")
        font = dataclasses.replace(style.font, size=p.scaled_size(style.font.size))
        grid = self.layout.grid
        canvas.draw_text(text, font, style.text_color, (PAGE_BODY.center[0], grid.center[1]),
                         anchor="center", max_width=PAGE_MESSAGE_WRAP, align="center")

    def back(self) -> bool:
        if self.busy():
            return True                                       # no input while checking
        if self.from_quick and self.host is not None:
            self.host.close_menu()
            return True
        return False

    def closed(self) -> None:
        self.port.remember(self.mode, self.page)

    def on_nav(self, d: Nav) -> bool:
        if d not in PAGE_KEYS:
            return False
        if self.busy():
            return True
        return self._go(self.page_index() + (1 if d is Nav.PAGE_DOWN else -1))

    def default_widget(self):
        """C1: the grid on the newest save's cell of the shown page (else cell 1); the
        page row when the grid isn't shown; None on a blocked page."""
        if self._shape is not None and self._shape[0] is not None:
            return None
        if self._shape is not None and self._shape[1]:
            return self.row
        return self.grid

    # -- pages --

    def _select(self, index: int) -> None:
        if not self.busy():
            self._go(index)

    def _go(self, index: int) -> bool:
        """Show page ``index`` (no wrap). The focused cell position stays; a focused page
        button follows the new current page."""
        if not 0 <= index < len(self.pages) or index == self.page_index():
            return False
        self.page = self.pages[index]
        self.port.remember(self.mode, self.page)
        self._scaled.clear()
        self._refresh()
        if self.row is not None:
            self.row.current_changed()
        return True

    def _refresh(self) -> None:
        self.views = list(self.port.views(self.page))
        signature = tuple((v.state, v.date, v.description, id(v.thumb), v.newest, v.busy,
                           v.deletable, v.label) for v in self.views) + (self.page,)
        if signature != self._signature:
            self._signature = signature
            host = self.host
            if host is not None and hasattr(host, "revision"):
                host.revision += 1                            # re-compose a fade layer

    def _default_cell(self) -> int:
        cell = self.port.default_cell(self.page)
        return cell if 0 <= cell < SLOTS else 0

    # -- choosing and deleting --

    def _choose(self, index: int) -> None:
        if self.busy():
            return
        self.port.choose(self.page, index, self.mode, self._by())

    def _delete(self, index: int) -> None:
        view = self.view(index)
        if self.busy() or view is None or not view.deletable:
            return
        self.port.delete(self.page, index, self._by())

    # -- cells --

    def cell_part(self, index: int, box: Box):
        """Cell ``index``'s parts (``layouts.SaveCell``) moved to ``box`` (the grid's cell
        on the canvas)."""
        assert self.layout is not None
        cell = self.layout.cells[index]
        dx, dy = box.x - cell.box.x, box.y - cell.box.y
        if dx == 0 and dy == 0:
            return cell
        return _moved_cell(cell, dx, dy)

    def _font(self, size: int) -> FontSpec:
        return self.shell.theme.font(size)

    def _fit(self, canvas: "Canvas", text: str, width: float, *, step: bool = True
             ) -> tuple[str, int]:
        """``text`` at ``save.text_size`` (scaled) narrower than ``width``: F10's step-down
        by 2, not below 24, then "…" (``step`` False: cut at the size). A text exactly as
        wide as its line counts as not fitting (03-ui: at 150% the date steps down to 28)."""
        assert self.layout is not None
        size = self.layout.text_size
        width -= FIT_MARGIN
        key = (text, round(width, 3), size, step)
        found = self._fits.get(key)
        if found is None:
            face = self._font(size)

            def font_at(s: int):
                return canvas.font_handle(face, s).font

            if step:
                fit = fit_label(text, font_at, size, width, min_size=min(24, size))
                found = (fit.text, fit.size)
            else:
                found = (cut_to_width(text, width, size,
                                     lambda part, s: text_width(font_at(s), part)), size)
            self._fits[key] = found
        return found

    def _draw_cell(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        view = self.view(index)
        layout = self.layout
        if view is None or layout is None:
            return
        canvas = p.canvas
        part = self.cell_part(index, box)
        save = self.shell.theme.cfg.save
        pic = part.picture
        if view.state == "filled":
            if view.thumb is not None:
                self._draw_thumb(canvas, view, pic)
            else:
                self._no_picture(canvas, p, pic)
            text_color = p.style("button", frame_state(look)).text_color
            if view.date:
                text, size = self._fit(canvas, view.date, layout.line_width)
                canvas.draw_text(text, self._font(size), text_color, part.date)
            if part.description is not None and view.description:
                text, size = self._fit(canvas, view.description, layout.line_width, step=False)
                canvas.draw_text(text, self._font(size), text_color, part.description)
            self._tag(p, view.label, part.label_tag, "topleft", save.badge.fill_color,
                      save.badge.fill_opacity, save.badge.text_color, layout.tag_max_width)
            if view.newest:
                self._tag(p, self.shell.words.get("save_newest"), part.newest_tag,
                          "bottomleft", save.newest.fill_color, 1.0, save.newest.text_color,
                          layout.tag_max_width)
            if view.version:
                self._tag(p, view.version, (pic.right - 4, pic.bottom - 4), "bottomright",
                          save.badge.fill_color, save.badge.fill_opacity,
                          save.badge.text_color, layout.tag_max_width)
            if view.busy:
                self._tag(p, self.shell.words.get("save_loading"), pic.center, "center",
                          save.badge.fill_color, save.badge.fill_opacity,
                          save.badge.text_color, pic.w - 8)
        else:
            area = part.placeholder
            p.rect(area, save.placeholder.fill_color)
            self._tag(p, view.label, part.label_tag, "topleft", save.badge.fill_color,
                      save.badge.fill_opacity, save.badge.text_color, layout.tag_max_width)
            top = part.label_tag[1] + layout.tag_height
            self._message(canvas, self.shell.words.get(STATE_WORDS[view.state]),
                          Box(area.x, top, area.w, area.bottom - top),
                          save.placeholder.text_color)
        if (look.state in ("focused", "pressed") and view.deletable and not view.busy
                and self.grid is not None and index == self.grid.focus_cell):
            self._delete_mark(p, part.delete_center, self.grid.delete_hover)

    def _draw_thumb(self, canvas: "Canvas", view: SlotView, pic: Box) -> None:
        surface = canvas.surface
        assert surface is not None and view.thumb is not None
        rect = canvas.rect_to_px((pic.x, pic.y, pic.w, pic.h))
        if rect.width <= 0 or rect.height <= 0:
            return
        size = rect.size
        scaled_thumb: pygame.Surface | None = None
        if view.thumb_key is not None:
            assets = canvas.assets
            key = (view.thumb_key, size)
            scaled_thumb = assets.cache.get(key, assets.time.frame)
            if scaled_thumb is None:
                scaled_thumb = pygame.transform.smoothscale(view.thumb, size)
                assets.cache.put(key, scaled_thumb, size[0] * size[1] * 4 + ENTRY_OVERHEAD,
                                 assets.time.frame)
        else:
            local = (id(view.thumb), size)
            found = self._scaled.get(local)
            if found is not None and found[0] is view.thumb:
                scaled_thumb = found[1]
            else:
                if len(self._scaled) >= THUMB_VARIANTS:
                    self._scaled.clear()
                scaled_thumb = pygame.transform.smoothscale(view.thumb, size)
                self._scaled[local] = (view.thumb, scaled_thumb)
        surface.blit(scaled_thumb, rect.topleft)

    def _no_picture(self, canvas: "Canvas", p: "Painter", pic: Box) -> None:
        """PR-F11-19: ``save.no_picture_image`` scaled to cover the box (no words), else the
        placeholder fill with "No picture"."""
        image = self.shell.theme.frames.get("save.no_picture")
        save = self.shell.theme.cfg.save
        surface = canvas.surface
        if image is not None and surface is not None:
            rect = canvas.rect_to_px((pic.x, pic.y, pic.w, pic.h))
            source = canvas.assets.surface(image)
            if source is not None and rect.width > 0 and rect.height > 0:
                key = ("save-no-picture", image.ref, rect.size)
                found = self._scaled.get(key)
                if found is None or found[0] is not source:
                    sw, sh = source.get_size()
                    cover = max(rect.width / max(1, sw), rect.height / max(1, sh))
                    big = pygame.transform.smoothscale(
                        source, (max(rect.width, math.ceil(sw * cover)),
                                 max(rect.height, math.ceil(sh * cover))))
                    crop = pygame.Rect(0, 0, *rect.size)
                    crop.center = big.get_rect().center
                    found = (source, big.subsurface(crop).copy())
                    self._scaled[key] = found
                surface.blit(found[1], rect.topleft)
                return
        p.rect(pic, save.placeholder.fill_color)
        self._message(canvas, self.shell.words.get("save_no_picture"), pic,
                      save.placeholder.text_color)

    def _message(self, canvas: "Canvas", text: str, area: Box,
                 color: tuple[int, int, int]) -> None:
        """Placeholder words centered in ``area``, wrapped, stepped down, then "…"."""
        assert self.layout is not None
        size = self.layout.text_size
        face = self._font(size)
        width = max(1.0, area.w - 2 * MESSAGE_PAD)
        key = ("message", text, round(width, 3), round(area.h, 3), size)
        found = self._fits.get(key)
        if found is None:
            lines = max(1, int(area.h // self.layout.pitch))

            def measure(part: str, s: int) -> float:
                return text_width(canvas.font_handle(face, s).font, part)

            fit = fit_message(text, width, size, measure, max_lines=lines,
                              min_size=min(24, size))
            found = ("\n".join(fit.lines), fit.size)
            self._fits[key] = found
        text_lines, fit_size = found
        lines = text_lines.split("\n")
        line_pitch = pitch(fit_size)
        cx, cy = area.center
        top = cy - len(lines) * line_pitch / 2
        font = self._font(fit_size)
        for i, line in enumerate(lines):
            if line:
                canvas.draw_text(line, font, color, (cx, top + i * line_pitch + line_pitch / 2),
                                 anchor="center")

    def _tag(self, p: "Painter", text: str, pos: tuple[float, float], anchor: str,
             fill: tuple[int, int, int], opacity: float, color: tuple[int, int, int],
             max_width: float) -> None:
        """A backed tag: ``save.text_size`` + 10 tall, text + 16 wide (at most
        ``max_width``, the text stepped down then cut), radius 8."""
        assert self.layout is not None
        canvas = p.canvas
        h = self.layout.tag_height
        shown, size = self._fit(canvas, text, max(1.0, max_width - SAVE_TAG_PAD_X))
        w = text_width(canvas.font_handle(self._font(size), size).font, shown) + SAVE_TAG_PAD_X
        x, y = pos
        if anchor == "bottomleft":
            y -= h
        elif anchor == "bottomright":
            x, y = x - w, y - h
        elif anchor == "center":
            x, y = x - w / 2, y - h / 2
        box = Box(x, y, w, h)
        p.shape(box, FrameSpec(fill, opacity, corner_radius=TAG_RADIUS))
        canvas.draw_text(shown, self._font(size), color, box.center, anchor="center")

    def _delete_mark(self, p: "Painter", center: tuple[float, float], hover: bool) -> None:
        """The ×: a 32-unit circle in ``save.badge`` (hovered: the pressed fill and a
        2-unit accent ring), two 3-wide strokes 14 long in ``button.marker.fill_color``."""
        cfg = self.shell.theme.cfg
        cx, cy = center
        d = 32
        circle = Box(cx - d / 2, cy - d / 2, d, d)
        if hover:
            spec = FrameSpec(cfg.button.pressed.fill_color, cfg.button.fill_opacity,
                             cfg.button.focused.border_color, DELETE_RING, d // 2)
        else:
            spec = FrameSpec(cfg.save.badge.fill_color, cfg.save.badge.fill_opacity,
                             corner_radius=d // 2)
        p.shape(circle, spec)
        canvas = p.canvas
        surface = canvas.surface
        assert surface is not None
        length, width = DELETE_STROKE
        half, side = length / 2 / math.sqrt(2), width / 2 / math.sqrt(2)
        color = cfg.button.marker.fill_color
        for sx in (1, -1):
            # A stroke from (cx − half·sx, cy − half) to (cx + half·sx, cy + half), 3 wide.
            ends = ((cx - half * sx, cy - half), (cx + half * sx, cy + half))
            nx, ny = side * sx, -side
            points = [(ends[0][0] + nx, ends[0][1] - ny), (ends[1][0] + nx, ends[1][1] - ny),
                      (ends[1][0] - nx, ends[1][1] + ny), (ends[0][0] - nx, ends[0][1] + ny)]
            pygame.draw.polygon(surface, color, [canvas.px(x, y) for x, y in points])


def _moved_cell(cell, dx: float, dy: float):
    def move(point: tuple[float, float] | None):
        return None if point is None else (point[0] + dx, point[1] + dy)

    return dataclasses.replace(
        cell, box=cell.box.moved(dx, dy), picture=cell.picture.moved(dx, dy),
        date=move(cell.date), description=move(cell.description),
        placeholder=cell.placeholder.moved(dx, dy), label_tag=move(cell.label_tag),
        newest_tag=move(cell.newest_tag), delete_center=move(cell.delete_center),
        delete_hit=cell.delete_hit.moved(dx, dy))


# --- Entries -------------------------------------------------------------------------------

def open_save_from_quick(shell: "GameShell", by: InputKind) -> None:
    """The quick menu's Save: the game menu opens on the Save page, and Back from it closes
    the whole menu. By keys the page's default widget is focused."""
    if shell.game_menu() is not None:
        return                                                # a menu is open: nothing more
    shell.open_game_menu(by)
    menu = shell.game_menu()
    if menu is None:
        return                                                # not in game
    if not any(e.id == "save" and e.page is not None for e in menu.entries):
        return                                                # hidden from the game menu
    menu.open_page("save")
    page = menu.page
    if isinstance(page, SavePage):
        page.from_quick = True
        target = page.default_widget()
        if by is InputKind.KEYS and target is not None and menu.scope.can_focus(target):
            menu.scope.focus(target, by, sound=False)


def register_save_pages(shell: "GameShell", port: SlotsPort, *, can_save: Callable[[], bool],
                        visible: Callable[[], bool]) -> None:
    """F11's page entries (``04`` §7.1 step 5): game ``save`` (``enabled=can_save``) and
    ``load``; title ``load`` (through ``open_title_page``); quick ``save`` (the game menu on
    the Save page, ``enabled=can_save``). ``visible`` False hides them all (W80)."""
    shell.menus.add("game", MenuEntry("save", page=lambda host: SavePage(port, "save"),
                                      enabled=can_save, visible=visible))
    shell.menus.add("game", MenuEntry("load", page=lambda host: SavePage(port, "load"),
                                      visible=visible))
    shell.menus.add("title", MenuEntry("load", page=lambda host: SavePage(port, "load"),
                                       visible=visible))
    shell.menus.add("quick", MenuEntry("save", action=lambda ctx: _quick_save_page(ctx),
                                       enabled=can_save, visible=visible))


def _quick_save_page(ctx: EntryContext) -> None:
    open_save_from_quick(ctx.shell, ctx.by)


__all__ = ["STATE_WORDS", "SavePage", "SlotGrid", "SlotView", "SlotsPort", "open_save_from_quick",
           "register_save_pages"]
