"""``PageRow``: a row of page buttons with ◀ ▶ (F11 ``03-ui`` "Page row contents", States;
F21 ``07`` I-1, the shared page row).

Why this module exists: F11's Save and Load pages pick one of up to 102 pages, and F21's
codex picks one of its tab categories, with the same row: buttons in F11's look, arrows when
the row doesn't fit, and the same keys. It is one ``Widget``, so a page drops it into a
``FocusGroup`` and the focus scope moves to it and away from it like any other widget; the
buttons inside it are its parts:

- **Layout** is ``layouts.page_row_layout`` (pure, AC-F11-39): H_b tall, max(H_b, label + 32)
  wide, 4 apart, placed by its ``RowPlacement`` (F11: midbottom at (820, 664)); ◀ and ▶ only
  when every button doesn't fit, with the ``fixed`` pages always shown and a window of the
  rest around the current page. ``box`` is the row's bounds, re-laid out whenever the labels,
  the current page, or the text scale change.
- **Look** (F11 States): F10's ``button`` frames without the focus marker; the current page
  is *selected* (F10's bar), so a focused current page shows bar, fill, and border. Arrows
  are drawn 12×16 triangles in the button's text color; a disabled arrow (◀ on the first
  page, ▶ on the last) has F10's disabled look and is skipped by focus.
- **Keys.** Left / Right (and Tab / Shift+Tab, through ``FocusScope``'s parts rule) move
  between the enabled buttons and return False at the ends, so focus can leave the row.
  Activate on a page shows it and moves focus to the new current page's button; ◀ / ▶ show
  the adjacent page and keep focus while they stay enabled (never wrapping).
- **Mouse.** Hover focuses a button; a click acts on the button the press began on.

``on_select(index)`` gets the page index chosen; the owner changes ``current()``. A page key
or bumper handled elsewhere calls ``current_changed()`` so a focused page button follows.
"""

import dataclasses
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Final

from engine.ui.focus import Box
from engine.ui.layouts import (
    BUTTON_HEIGHT,
    BUTTON_TEXT_SIZE,
    PAGE_BODY,
    PAGE_ROW_PLACEMENT,
    Measure,
    PageButton,
    PageRowLayout,
    RowPlacement,
    page_row_layout,
    scaled,
)
from engine.ui.nav import Nav
from engine.ui.paint import frame_state
from engine.ui.widgets import Look, LookState, MouseKind, Widget

if TYPE_CHECKING:
    from engine.ui.paint import Painter

ARROW_SIZE: Final = (12, 16)          # the drawn ◀ ▶ triangles
Key = tuple[str, int | None]          # ("page", index) | ("prev", None) | ("next", None)


def _key(button: PageButton) -> Key:
    return (button.kind, button.page)


class PageRow(Widget):
    """The page row. ``labels()`` are every page in order, ``current()`` the shown page's
    index; ``fixed`` leading pages are always shown (F11's Load: Auto and Quick)."""

    repeatable = True

    def __init__(self, labels: Callable[[], Sequence[str]], current: Callable[[], int],
                 on_select: Callable[[int], None], *, fixed: int = 0,
                 measure: Measure, scale: Callable[[], float] = lambda: 1.0,
                 text_size: int = BUTTON_TEXT_SIZE, height: int = BUTTON_HEIGHT,
                 width: float = PAGE_BODY.w, placement: RowPlacement = PAGE_ROW_PLACEMENT,
                 enabled: Callable[[], bool] | None = None, focusable: bool = True) -> None:
        self._layout: PageRowLayout | None = None
        self._layout_key: tuple | None = None
        super().__init__(enabled=enabled, focusable=focusable)
        self.labels = labels
        self.current = current
        self.on_select = on_select
        self.fixed = fixed
        self.measure = measure
        self.scale = scale
        self.text_size = text_size
        self.height = height
        self.width = width
        self.placement = placement
        self._focus: Key | None = None
        self._pressed: Key | None = None

    # -- geometry --

    @property                                                 # type: ignore[override]
    def box(self) -> Box:
        """The row's bounds (from the layout; a page never sets it)."""
        if not hasattr(self, "labels"):
            return Box(0, 0, 0, 0)
        return self.layout().bounds

    @box.setter
    def box(self, value: Box) -> None:
        pass                                                  # placed by ``placement``

    def layout(self) -> PageRowLayout:
        """``page_row_layout`` for the labels, current page, and text scale now (cached)."""
        labels = tuple(self.labels())
        key = (labels, self.current(), self.scale(), self.text_size, self.height,
               self.width, self.placement, self.fixed)
        if key != self._layout_key or self._layout is None:
            self._layout = page_row_layout(labels, key[1], self.measure, fixed=self.fixed,
                                           scale=key[2], text_size=self.text_size,
                                           height=self.height, width=self.width,
                                           placement=self.placement)
            self._layout_key = key
        return self._layout

    def button_enabled(self, button: PageButton, layout: PageRowLayout | None = None) -> bool:
        layout = layout if layout is not None else self.layout()
        if button.kind == "prev":
            return layout.prev_enabled
        if button.kind == "next":
            return layout.next_enabled
        return True

    def _enabled_buttons(self) -> list[PageButton]:
        layout = self.layout()
        return [b for b in layout.buttons if self.button_enabled(b, layout)]

    def button_at(self, pos: tuple[float, float]) -> PageButton | None:
        for button in self.layout().buttons:
            if button.box.contains(pos):
                return button
        return None

    def _current_index(self) -> int:
        n = len(tuple(self.labels()))
        return max(0, min(self.current(), n - 1)) if n else 0

    # -- focus among the buttons --

    def focused_button(self) -> PageButton | None:
        """The button focus is on inside the row: the last one focused while it is shown
        and enabled, else the current page's."""
        usable = self._enabled_buttons()
        for button in usable:
            if _key(button) == self._focus:
                return button
        current = ("page", self._current_index())
        for button in usable:
            if _key(button) == current:
                return button
        return usable[0] if usable else None

    def focus_button(self, key: Key) -> None:
        self._focus = key

    def current_changed(self) -> None:
        """The shown page changed (a page key): a focused page button moves to the new
        current page's; a focused arrow stays while it is enabled."""
        focused = self.focused_button()
        if focused is None or focused.kind == "page" or not self.button_enabled(focused):
            self._focus = ("page", self._current_index())

    # -- Widget --

    def on_nav(self, d: Nav) -> bool:
        if d not in (Nav.LEFT, Nav.RIGHT, Nav.NEXT, Nav.PREV):
            return False
        usable = self._enabled_buttons()
        focused = self.focused_button()
        if focused is None:
            return False
        index = usable.index(focused) + (1 if d in (Nav.RIGHT, Nav.NEXT) else -1)
        if not 0 <= index < len(usable):
            return False
        self._focus = _key(usable[index])
        return True

    def tab_entered(self, forward: bool) -> None:
        usable = self._enabled_buttons()
        if usable:
            self._focus = _key(usable[0] if forward else usable[-1])

    def activate(self) -> None:
        if not self.enabled():
            return
        button = self.focused_button()
        if button is not None:
            self._act(button)

    def _act(self, button: PageButton) -> None:
        current = self._current_index()
        if button.kind == "page":
            assert button.page is not None
            self.on_select(button.page)
            self._focus = ("page", self._current_index())
            return
        target = current - 1 if button.kind == "prev" else current + 1
        if self.button_enabled(button):
            self.on_select(target)
        self.current_changed()

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if not self.enabled():
            return False
        if kind == "hover":
            button = self.button_at(pos)
            if button is None or not self.button_enabled(button) or _key(button) == self._focus:
                return False
            self._focus = _key(button)
            return True
        if kind == "down":
            button = self.button_at(pos)
            usable = button is not None and self.button_enabled(button)
            self._pressed = _key(button) if usable and button is not None else None
            if self._pressed is not None:
                self._focus = self._pressed
            return usable
        return False

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        pressed, self._pressed = self._pressed, None
        button = self.button_at(pos)
        return (pressed is not None and self.enabled() and button is not None
                and _key(button) == pressed and self.button_enabled(button))

    # -- drawing --

    def button_state(self, button: PageButton, look: Look) -> LookState:
        """A button's look: disabled arrows (or a disabled row); the focused button pressed
        or focused while the row is; else normal."""
        if look.state == "disabled" or not self.button_enabled(button):
            return "disabled"
        focused = self.focused_button()
        if focused is not None and _key(button) == _key(focused):
            if look.state == "pressed":
                return "pressed"
            if look.state == "focused":
                return "focused"
        return "normal"

    def draw(self, p: "Painter", look: Look) -> None:
        """Each button: F10's ``button`` frame without the marker, the current page with
        the bar; the label centered (the layout made it fit), or the arrow."""
        layout = self.layout()
        current = self._current_index()
        size = scaled(self.text_size, self.scale())
        for button in layout.buttons:
            selected = button.kind == "page" and button.page == current
            blook = Look(self.button_state(button, look), None, selected)
            p.widget_frame(button.box, "button", blook, marker=False)
            style = p.style("button", frame_state(blook))
            cx, cy = button.box.center
            if button.kind == "page":
                font = dataclasses.replace(style.font, size=size)
                p.canvas.draw_text(button.label, font, style.text_color, (cx, cy),
                                   anchor="center")
            else:
                w, h = ARROW_SIZE
                p.triangle(Box(cx - w / 2, cy - h / 2, w, h), style.text_color,
                           direction="left" if button.kind == "prev" else "right")


__all__ = ["ARROW_SIZE", "PageRow"]
