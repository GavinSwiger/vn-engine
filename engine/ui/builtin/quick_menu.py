"""``QuickMenu``: the pill of small text buttons in the strip under the textbox (F10 ``04``
§7.8 with I-3, I-4; ``03-ui`` "Quick menu"; UI-F10-10; PR-F10-32 to 35).

Why this module exists: the quick menu must show exactly with the say window, take clicks
that never advance the text or pick a choice, and let every other click in the strip act on
the scene. It is not a screen (it never holds the story): it is an ``InGameOverlay`` hosted
by F05's ``TextboxScreen`` (C5), which offers it each event before its own advance logic,
also while hidden, and draws it after the box. F07's ``ChoiceScreen`` sits above the
textbox and lets presses outside its buttons, releases, and motion fall through (C7), so
the pill works over choices too; the choice floor (C6) keeps the buttons above the pill.

- **Visible** exactly when ``[quick_menu] enabled``, at least one entry is shown
  (``MenuRegistry.shown("quick")``: author order, overrides, ``visible()``), and the host
  passes ``box_shown=True``: not before the first line, not hidden, not after ``clear()``.
- **Layout** ``UiTheme.quick_menu_layout`` (the pill inside the strip under the box, I-4),
  recomputed when the labels or the text scale change. The scale is the say window's text
  size over ``textbox.text_size`` (F16's one source, ``TextboxScreen.settings``); the
  quick-menu text stops scaling at 24. F32 (04 §6.5, D2): the scale is
  ``textbox.text_scale()`` and the key gains ``shell.looks.revision``, so a style switch
  changes the pill's colors and layout in the switch frame.
- **Input** (only while visible, except to finish a capture): button-1 down on an item
  captures it (an enabled one shows the pressed chip; a disabled one does nothing) and is
  consumed; a release with a capture is consumed and acts only over the same enabled item
  (``entry.action``, then ``quick_menu.activate_sound`` or else ``button.activate_sound``).
  Any other event goes on to F05, so a click in the strip off the pill advances. No key or
  gamepad input is handled (PR-F10-34): every F10 quick action also has a key path.
- **Look** (03 "States"): hover (accent text and an underline 3 below the baseline) comes
  from ``stack.pointer`` in ``draw``, only while an in-game screen is top; the pressed chip
  while the pointer holds a press over its item; the on chip (``entry.on()``) with its
  border; disabled items in the muted italic.
- **Choice floor** (C6, I-3): ``floor()`` is ``pill_top() − 4`` while the quick menu can show
  over a box that has something to draw (hidden mode aside), else 704. ``install_ui``
  hands it to F07 through ``ChoiceController.set_floor``.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pygame

from engine.render.frames import FrameSpec
from engine.ui.focus import Box
from engine.ui.input import UiEvent
from engine.ui.layouts import QuickItem, QuickMenuLayout
from engine.ui.menus import EntryContext, MenuEntry
from engine.ui.nav import InputKind
from engine.ui.theme import measure_with

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.shell import GameShell

FLOOR_GAP: Final = 4                   # choices end 4 above the pill (C6)
NO_PILL_FLOOR: Final = 704             # F07's step-3 area without the quick menu
CHIP_INSET: Final = 2
CHIP_RADIUS: Final = 10
UNDERLINE_GAP: Final = 3               # the hover underline sits 3 below the baseline


@dataclass(frozen=True)
class _Shown:
    """One frame's pill: the entries and their laid-out items, in the same order."""
    entries: tuple[MenuEntry, ...]
    layout: QuickMenuLayout


class QuickMenu:
    """The quick-menu overlay of one launch (``install_ui`` adds it after ``GameMenuKeys``).
    ``textbox`` is F05's ``TextboxScreen`` (its ``settings`` give the text scale; ``has_box``
    the floor's box state)."""

    def __init__(self, shell: "GameShell", textbox: object) -> None:
        self.shell = shell
        self.textbox = textbox
        self._measure = self._measure_for(shell.theme)
        self._layout_key: tuple | None = None
        self._layout: QuickMenuLayout | None = None
        self.captured: str | None = None       # the entry id a button-1 press holds

    # -- what shows --

    @property
    def enabled(self) -> bool:
        return bool(self.shell.config.quick_menu.enabled)

    def entries(self) -> list[MenuEntry]:
        """The entries shown now (empty while ``[quick_menu] enabled = false``)."""
        if not self.enabled:
            return []
        return self.shell.menus.shown("quick")

    def label(self, entry: MenuEntry) -> str:
        """The entry's word (overrides, then ``[words]``). An id whose feature hasn't added its
        ``WordsConfig`` field yet shows the id capitalized."""
        try:
            return self.shell.words.get(entry.id)
        except KeyError:
            return entry.id.replace("_", " ").capitalize()

    def _measure_for(self, theme) -> object:
        return measure_with(self.shell.assets, theme.font(theme.cfg.quick_menu.text_size))

    def _revision(self) -> int:
        looks = getattr(self.shell, "looks", None)
        return 0 if looks is None else looks.revision

    def text_scale(self) -> float:
        """F16's text scale: the textbox's own (F32: measured on its layout look), else the
        say window's text size over ``textbox.text_size``."""
        scale_of = getattr(self.textbox, "text_scale", None)
        if scale_of is not None:
            return scale_of()
        base = self.shell.config.theme.textbox.text_size
        size_of = getattr(self.textbox, "text_size", None)
        if size_of is None or not base:
            return 1.0
        return size_of() / base

    def shown(self) -> _Shown | None:
        """The pill as it would draw now, box state aside; None when there is none."""
        entries = tuple(self.entries())
        if not entries:
            return None
        labels = tuple(self.label(e) for e in entries)
        scale = self.text_scale()
        revision = self._revision()
        key = (labels, scale, revision)
        if key != self._layout_key or self._layout is None:
            if self._layout_key is not None and self._layout_key[2] != revision:
                self._measure = self._measure_for(self.shell.theme)     # F32: a new look
            self._layout = self.shell.theme.quick_menu_layout(list(labels), self._measure,
                                                              scale=scale)
            self._layout_key = key
        return _Shown(entries, self._layout)

    def pill_top(self) -> int | None:
        """The pill's top y; None when the quick menu is off or has no entry (C6)."""
        found = self.shown()
        return None if found is None else round(found.layout.pill_top())

    def floor(self) -> int:
        """F07's last-resort fit ends here (C6): the pill top − 4 while the quick menu can
        show over the box (686 by default; 684 at 150 %), else 704."""
        top = self.pill_top()
        if top is None or not bool(getattr(self.textbox, "has_box", False)):
            return NO_PILL_FLOOR
        return top - FLOOR_GAP

    @staticmethod
    def _hit(found: _Shown, pos: tuple[float, float]) -> int | None:
        for index, item in enumerate(found.layout.items):
            if item.box.contains(pos):
                return index
        return None

    # -- InGameOverlay --

    def handle_event(self, event: UiEvent, *, box_shown: bool) -> bool:
        kind = event.type
        if kind == pygame.MOUSEBUTTONUP and getattr(event.raw, "button", 0) == 1 \
                and self.captured is not None:
            captured, self.captured = self.captured, None
            found = self.shown() if box_shown else None
            if found is not None and event.in_canvas and event.canvas_pos is not None:
                index = self._hit(found, event.canvas_pos)
                if index is not None:
                    entry = found.entries[index]
                    if entry.id == captured and entry.enabled():
                        self._activate(entry)
            return True
        if kind != pygame.MOUSEBUTTONDOWN or getattr(event.raw, "button", 0) != 1:
            return False
        if not box_shown or not event.in_canvas or event.canvas_pos is None:
            return False
        found = self.shown()
        if found is None:
            return False
        index = self._hit(found, event.canvas_pos)
        if index is None:
            return False                       # the strip off the pill: F05's scene click
        entry = found.entries[index]
        self.captured = entry.id if entry.enabled() else None
        return True                            # a quick-menu button never advances

    def _activate(self, entry: MenuEntry) -> None:
        cfg = self.shell.theme.cfg
        if entry.action is not None:
            entry.action(EntryContext(self.shell, InputKind.MOUSE))
        sound = cfg.quick_menu.activate_sound
        self.shell.play_ui(sound if sound is not None else cfg.button.activate_sound)

    def update(self, dt: float, *, frozen: bool) -> None:
        # ``frozen`` is also True under F07's choices, so it can't end a capture; a menu or
        # fade on top (the story held) can.
        if self.captured is not None and not self.shell.stack.story_may_run():
            self.captured = None

    def draw(self, canvas: "Canvas", *, box_shown: bool) -> None:
        if not box_shown:
            return
        found = self.shown()
        if found is None:
            return
        shell = self.shell
        q = shell.theme.cfg.quick_menu
        painter = shell.painter
        painter.bind(canvas)
        layout = found.layout
        painter.shape(layout.pill, FrameSpec(q.fill_color, q.fill_opacity,
                                             corner_radius=q.corner_radius,
                                             slice_width=q.frame_slice_width),
                      image=shell.theme.frames.get("quick_menu"))
        pointer = shell.stack.pointer if shell.stack.story_may_run() else None
        hovered = self._hit(found, pointer) if pointer is not None else None
        for index, (entry, item) in enumerate(zip(found.entries, layout.items, strict=True)):
            enabled = entry.enabled()
            over = enabled and hovered == index
            if self.captured is not None:
                pressed = over and self.captured == entry.id
                over = pressed
            else:
                pressed = False
            on = enabled and entry.on is not None and bool(entry.on())
            self._draw_item(canvas, item, layout.text_size, enabled=enabled, hover=over,
                            pressed=pressed, on=on)

    def _draw_item(self, canvas: "Canvas", item: QuickItem, size: int, *, enabled: bool,
                   hover: bool, pressed: bool, on: bool) -> None:
        theme = self.shell.theme
        q = theme.cfg.quick_menu
        painter = self.shell.painter
        b = item.box
        chip = Box(b.x + CHIP_INSET, b.y + CHIP_INSET, b.w - 2 * CHIP_INSET,
                   b.h - 2 * CHIP_INSET)
        if pressed:
            painter.shape(chip, FrameSpec(q.pressed.fill_color, corner_radius=CHIP_RADIUS))
        elif on:
            painter.shape(chip, FrameSpec(q.on.fill_color, border_color=q.on.border_color,
                                          border_width=q.on.border_width,
                                          corner_radius=CHIP_RADIUS))
        font = theme.font(size, italic=not enabled)
        if not enabled:
            color = q.disabled.text_color
        elif hover:
            color = q.focused.text_color
        else:
            color = q.text_color
        if not item.label:
            return
        cx, cy = item.label_box.center
        left, top, width, _height = canvas.draw_text(item.label, font, color, (cx, cy),
                                                     anchor="center")
        if hover and not pressed:
            ascent = canvas.font_handle(font, size).font.get_ascent()
            painter.rect(Box(left, top + ascent + UNDERLINE_GAP, width,
                             q.focused.underline_width), q.focused.text_color)


__all__ = ["FLOOR_GAP", "NO_PILL_FLOOR", "QuickMenu"]
