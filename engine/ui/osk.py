"""``OnScreenKeyboard``: the gamepad keyboard panel over a text field (F52 ``01`` §6.2, §6.3;
``04`` §3, §4.4; P5).

Why this module exists: a player with only a controller must still be able to type a name.
The keyboard is host-owned and modal (07 §3.4): a ``MenuScreen`` or the minigame host owns
one per screen, opens it over the focused ``TextField`` (south on the field, or a click on
the field's keyboard icon), and routes navigation and mouse input to it while it is open
(``ui.textrouting``). Its keys never join a ``FocusScope``, so a plugin replacing its groups
can't drop it.

- **Panel** (``textgeom.keyboard_layout``): ``panel.*`` look; the echo row repeats the field
  (text, caret, composition, counter, mask) so it doesn't matter what the panel covers; F21's
  ``PageRow`` picks the page; the 10 × 4 grid holds the page's keys (``button.*``; empty
  cells are blank and never focused); the bottom row is ◀ ▶ (caret), Space, Delete, Done.
- **Focus** is the keyboard's own: the first key at open; directions move by F10's
  ``move_target``; Home/End go to the first/last key; the page row keeps Left/Right for its
  buttons until its ends. Space is disabled when the field doesn't accept a space.
- **Pages** (``open_for``): ``kbpages.pages_for`` with the language and a glyph test over the
  UI font chain at key size (``ChainFont.covers``, else ``render.text.missing_glyphs``),
  cached per font and character. W267 is warned once per (field, left-out set), dev only.
- **Done** submits; the keyboard closes unless the field has ``keep_keyboard``.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import pygame

from engine.render.text import missing_glyphs
from engine.ui.focus import Box, move_target
from engine.ui.kbpages import Page, pages_for, undrawable, w267_text
from engine.ui.layouts import BUTTON_HEIGHT, BUTTON_TEXT_SIZE, RowPlacement
from engine.ui.nav import DIRECTIONS, Nav
from engine.ui.page_row import PageRow
from engine.ui.textgeom import KeyboardLayout, keyboard_layout
from engine.ui.widgets import Look

if TYPE_CHECKING:
    from engine.ui.paint import Painter
    from engine.ui.textfield import TextField

ARROW: Final = (12, 16)
BOTTOM_WORDS: Final = {"space": "text_entry_space", "delete": "text_entry_delete",
                       "done": "text_entry_done"}
DEFAULT_KEY_WORDS: Final = {"text_entry_space": "Space", "text_entry_delete": "Delete",
                            "text_entry_done": "Done"}
Item = tuple[str, object]           # ("row", None) | ("key", index) | (bottom name, None)


@dataclass
class KeyboardServices:
    """What the keyboard needs from its owner: the language code, a glyph test (None:
    everything draws), a text measure for the page row, the text scale, the words, and
    W267's sink (None outside dev runs)."""
    language: Callable[[], str] = lambda: "en"
    can_draw: Callable[[str], bool] | None = None
    measure: Callable[[str, int], float] = lambda text, size: len(text) * size * 0.6
    scale: Callable[[], float] = lambda: 1.0
    word: Callable[[str], str] = DEFAULT_KEY_WORDS.get        # type: ignore[assignment]
    warn: Callable[[str], None] | None = None
    text_size: int = BUTTON_TEXT_SIZE
    height: int = BUTTON_HEIGHT
    warned: set = field(default_factory=set)


def glyph_test(font: object) -> Callable[[str], bool]:
    """A ``can_draw`` over ``font`` (a ``ChainFont`` or a pygame font): the chain's coverage
    when known, else the ``.notdef`` pixel test; cached per character."""
    cache: dict[str, bool] = {}

    def can_draw(ch: str) -> bool:
        found = cache.get(ch)
        if found is None:
            covers = getattr(font, "covers", None)
            known = covers(ch) if callable(covers) else None
            if known is None:
                try:
                    known = not missing_glyphs(font, ch)       # type: ignore[arg-type]
                except pygame.error:
                    known = True
            found = cache[ch] = bool(known)
        return found
    return can_draw


class OnScreenKeyboard:
    """One screen's keyboard (module docstring)."""

    def __init__(self, services: KeyboardServices | None = None) -> None:
        self.services = services or KeyboardServices()
        self.field: "TextField | None" = None
        self.pages: list[Page] = []
        self.page = 0
        self.focus: Item = ("key", 0)
        self.pressed: Item | None = None
        self._row: PageRow | None = None
        self._layout: KeyboardLayout | None = None
        self._scale: float | None = None

    # -- open and close --

    @property
    def is_open(self) -> bool:
        return self.field is not None

    def open(self, field: "TextField", pages: list[Page]) -> None:
        self.field = field
        self.pages = list(pages)
        self.page = 0
        self.pressed = None
        services = self.services
        self._row = PageRow(lambda: [p.label for p in self.pages], lambda: self.page,
                            self._select, measure=services.measure, scale=services.scale,
                            text_size=services.text_size, height=services.height,
                            width=self.layout().page_row.w,
                            placement=RowPlacement("topleft", (self.layout().page_row.x,
                                                               self.layout().page_row.y)))
        self.focus = self._first()

    def open_for(self, field: "TextField") -> None:
        """Open over ``field`` with its pages (and W267 once, dev only)."""
        services = self.services
        can_draw = services.can_draw or (lambda _ch: True)
        language = services.language() or "en"
        pages = pages_for(language, field.allowed, field.case, can_draw)
        if services.warn is not None and services.can_draw is not None:
            missing = undrawable(language, field.allowed, field.case, can_draw)
            key = (id(field), tuple(missing))
            if missing and key not in services.warned:
                services.warned.add(key)
                services.warn(w267_text(missing))
        self.open(field, pages)

    def close(self) -> None:
        self.field = None
        self.pressed = None

    # -- layout --

    def layout(self) -> KeyboardLayout:
        scale = self.services.scale()
        if self._layout is None or scale != self._scale:
            self._scale = scale
            self._layout = keyboard_layout(scale, text_size=self.services.text_size,
                                           height=self.services.height)
            if self._row is not None:
                lay = self._layout
                self._row.placement = RowPlacement("topleft", (lay.page_row.x, lay.page_row.y))
        return self._layout

    def keys(self) -> tuple[str, ...]:
        return self.pages[self.page].keys if self.pages else ()

    def _enabled(self, item: Item) -> bool:
        name = item[0]
        if name == "row":
            return len(self.pages) > 1
        if name == "key":
            return int(item[1]) < len(self.keys())             # type: ignore[arg-type]
        if name == "space":
            return self.field is not None and self.field.allowed.accepts(" ")
        return True

    def items(self) -> list[tuple[Item, Box]]:
        """Every focusable part with its box, in reading order."""
        lay = self.layout()
        out: list[tuple[Item, Box]] = []
        if len(self.pages) > 1 and self._row is not None:
            out.append((("row", None), self._row.box))
        for index, box in enumerate(lay.keys):
            out.append((("key", index), box))
        for name, box in lay.bottom:
            out.append(((name, None), box))
        return [(item, box) for item, box in out if self._enabled(item)]

    def _first(self) -> Item:
        found = [item for item, _box in self.items() if item[0] != "row"]
        return found[0] if found else ("done", None)

    def _box(self, item: Item) -> Box | None:
        for it, box in self.items():
            if it == item:
                return box
        return None

    def _select(self, index: int) -> None:
        if 0 <= index < len(self.pages):
            self.page = index
            if self._row is not None:
                self._row.current_changed()

    def page_step(self, delta: int) -> bool:
        """LB / RB, Page Up / Page Down: the previous / next page (no wrap)."""
        target = self.page + delta
        if not 0 <= target < len(self.pages):
            return False
        self._select(target)
        if self.focus[0] == "key" and not self._enabled(self.focus):
            self.focus = self._first()
        return True

    # -- input --

    def on_nav(self, nav: Nav) -> bool:
        """A navigation press while open (always used)."""
        if not self.is_open:
            return False
        if self.focus[0] == "row" and self._row is not None and nav in (Nav.LEFT, Nav.RIGHT):
            if self._row.on_nav(nav):
                return True
        if nav is Nav.ACTIVATE:
            self.press()
            return True
        if nav in (Nav.HOME, Nav.END):
            found = [item for item, _box in self.items() if item[0] == "key"] or \
                [item for item, _box in self.items()]
            if found:
                self.focus = found[0] if nav is Nav.HOME else found[-1]
            return True
        if nav in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            self.page_step(-1 if nav is Nav.PAGE_UP else 1)
            return True
        if nav in DIRECTIONS:
            current = self._box(self.focus)
            items = [(item, box) for item, box in self.items() if item != self.focus]
            if current is None:
                self.focus = self._first()
                return True
            index = move_target(current, [box for _item, box in items], nav)
            if index is not None:
                self.focus = items[index][0]
                if self.focus[0] == "row" and self._row is not None:
                    self._row.current_changed()
            return True
        return True

    def press(self, item: Item | None = None) -> None:
        """Press a key (the focused one by default)."""
        f = self.field
        item = item if item is not None else self.focus
        if f is None or not self._enabled(item):
            return
        name = item[0]
        if name == "row":
            if self._row is not None:
                self._row.activate()
            return
        if name == "key":
            f.type_text(self.keys()[int(item[1])])               # type: ignore[arg-type]
        elif name == "left":
            f.move(-1)
        elif name == "right":
            f.move(1)
        elif name == "space":
            f.type_text(" ")
        elif name == "delete":
            f.backspace()
        elif name == "done":
            keep = f.keep_keyboard
            f.submit()
            if not keep:
                self.close()

    def item_at(self, pos: tuple[float, float]) -> Item | None:
        for item, box in self.items():
            if box.contains(pos):
                return item
        return None

    def on_mouse(self, kind: str, pos: tuple[float, float]) -> str | None:
        """``"down"``, ``"motion"``, ``"up"`` (button 1) while open: ``"outside"`` for a press
        outside the panel (the caller closes), else ``"used"``."""
        if not self.is_open:
            return None
        if kind == "down":
            if not self.layout().panel.contains(pos):
                return "outside"
            item = self.item_at(pos)
            self.pressed = item
            if item is not None:
                self.focus = item
                if item[0] == "row" and self._row is not None:
                    self._row.on_mouse("down", pos)
            return "used"
        if kind == "motion":
            item = self.item_at(pos)
            if self.pressed is None and item is not None:
                self.focus = item
                if item[0] == "row" and self._row is not None:
                    self._row.on_mouse("hover", pos)
            return "used"
        if kind == "up":
            item, self.pressed = self.pressed, None
            if item is not None and item == self.item_at(pos):
                if item[0] == "row" and self._row is not None:
                    self._row.on_mouse("up", pos)
                    if self._row.accepts_click(pos):
                        self._row.activate()
                else:
                    self.press(item)
            return "used"
        return "used"

    # -- drawing --

    def draw(self, p: "Painter") -> None:
        f = self.field
        if f is None:
            return
        lay = self.layout()
        p.panel(lay.panel)
        f.draw_echo(p, lay.echo)
        if self._row is not None and len(self.pages) > 1:
            focused = self.focus[0] == "row"
            self._row.draw(p, self._row.look(focused=focused))
        keys = self.keys()
        for index, box in enumerate(lay.keys):
            if index < len(keys):
                self._key(p, ("key", index), box, keys[index])
        word = self.services.word
        for name, box in lay.bottom:
            label = "" if name in ("left", "right") else word(BOTTOM_WORDS[name])
            self._key(p, (name, None), box, label)

    def _look(self, item: Item) -> Look:
        if not self._enabled(item):
            return Look("disabled")
        if item == self.pressed:
            return Look("pressed")
        return Look("focused") if item == self.focus else Look("normal")

    def _key(self, p: "Painter", item: Item, box: Box, label: str) -> None:
        look = self._look(item)
        p.widget_frame(box, "button", look, marker=False)
        if item[0] in ("left", "right"):
            style = p.style("button", "disabled" if look.state == "disabled" else "normal")
            w, h = ARROW
            p.triangle(Box(box.x + (box.w - w) / 2, box.y + (box.h - h) / 2, w, h),
                       style.text_color, direction="left" if item[0] == "left" else "right")
            return
        if label:
            style = p.style("button", look.state if look.state != "pressed" else "focused")
            fit = p.fit(label, "button", box.w - 8, look.state)
            if fit.text:
                p.canvas.draw_text(fit.text, dataclasses.replace(style.font, size=fit.size),
                                   style.text_color, box.center, anchor="center")


__all__ = ["DEFAULT_KEY_WORDS", "KeyboardServices", "OnScreenKeyboard", "glyph_test"]
