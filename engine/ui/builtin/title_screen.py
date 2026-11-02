"""``TitleScreen``: the first screen of a game (F10 ``03`` "Title screen", UI-F10-07; ``04``
§7.5, §7.9).

Why this module exists: the title is where every session starts and where every story ends
(PR-F10-20 to 27). It is a ``MenuScreen`` (one focus for mouse, keys, and gamepad) that
paints the whole canvas itself:

- **Background**: ``[theme.title] background_image`` (or F32's override) scaled to cover
  1280×720 keeping its aspect, centred; else a vertical gradient from ``fill_top_color`` to
  ``fill_bottom_color`` (one viewport-sized surface in ``SizedLru``).
- **Logo box** (80, 48, 560×200, smaller by ``title_layout``'s fit): ``logo_image`` scaled
  down to fit, never up, its left edge at x 80 and centred on the box; else ``[game] title``
  in the bold face at ``title.logo.text_size``, at most 2 lines (smaller by 4 down to 40,
  then "…"), with a panel backing 24 larger on each side only over a background image.
- **Buttons**: ``shell.menus.shown("title")`` read each time the title opens, in a column at
  (80, 288) (``layouts.title_layout``). Nothing is focused until the first navigation input,
  which focuses the first entry. Back and Start do nothing here; Shift+F3 opens the widget
  sampler in dev runs.
- **Version** pill at the bottom right (1264, 708) when ``[title] show_version``.
- **Motion**: the whole title fades in from black over ``title.fade_in_ms`` (500 ms) at launch
  and on every return; any input finishes it. New Game fades it to black over ``ui.fade_ms``
  taking no input, then the shell cuts to the game. Both are cuts under reduced motion.
- **Music**: ``on_enter`` asks the shell to take the music stream (``title_entered``);
  ``on_exit`` lets it go.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.core.logsetup import get_logger
from engine.core.redact import escape_controls
from engine.render.canvas import Canvas
from engine.render.frames import FrameSpec, surface_cost, to_black, vertical_gradient
from engine.render.text import FontSpec, text_width
from engine.ui.focus import Box, FocusGroup
from engine.ui.input import UiEvent
from engine.ui.layouts import TitleLayout, title_layout
from engine.ui.menu_screen import MenuScreen
from engine.ui.menus import EntryContext, MenuEntry
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import Painter
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.core.config_schema import TitleTheme
    from engine.render.assets import ImageRef
    from engine.ui.shell import GameShell

_log = get_logger("ui")

CANVAS_W, CANVAS_H = CANVAS_SIZE
GRADIENT_KEY: Final = "ui-gradient"
TEXT_STEP: Final = 4               # title text steps down by 4 ...
TEXT_MIN: Final = 40               # ... not below 40, then ends in "…"
TEXT_MAX_LINES: Final = 2
BACKING: Final = 24                # the title text's panel is 24 larger on each side
VERSION_RIGHT, VERSION_BOTTOM = 1264, 708
VERSION_HEIGHT: Final = 28
VERSION_RADIUS: Final = 14
VERSION_PAD: Final = 8
_EPSILON: Final = 1e-9
# Inputs that finish the fade-in (motion does not).
_INPUT_EVENTS = frozenset({pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                           pygame.MOUSEWHEEL, pygame.CONTROLLERBUTTONDOWN})


class TitleScreen(MenuScreen):
    """The title. Opaque; never ``in_game``, so the story holds while it shows."""

    solid = True

    def __init__(self, shell: "GameShell", *, fade_in: bool = True) -> None:
        self._buttons: dict[str, Button] = {}
        self.buttons: list[Button] = []
        self.layout: TitleLayout | None = None
        self._text_fit: tuple[tuple, FontSpec, list[str]] | None = None
        cfg = shell.theme.cfg
        ms = 0 if (not fade_in or shell.reduce_motion) else cfg.title.fade_in_ms
        self.fade_in_s = ms / 1000.0
        self.in_t = 0.0 if self.fade_in_s > 0 else 1.0
        self.leaving = False
        self.out_s = 0.0
        self.out_t = 0.0
        self._out_fresh = False
        self._leave_then: Callable[[], None] | None = None
        self._seen_revision = shell.overrides.revision
        # No focus until the first navigation input (AC-F10-33): opened "by" the mouse.
        super().__init__(shell, by=InputKind.MOUSE, fade=False)

    @property
    def holds_notices(self) -> bool:                         # type: ignore[override]
        """F11 C7: new notices wait while the title fades in from black or out to it."""
        return self.in_t < 1.0 or self.leaving

    @property
    def game_shell(self) -> "GameShell":
        return self.shell                                    # type: ignore[return-value]

    # -- layout --

    def build(self) -> None:
        shell = self.game_shell
        cfg = shell.theme.cfg
        entries = shell.menus.shown("title")
        self.layout = title_layout(len(entries), scale=self.painter.text_scale(),
                                   text_size=cfg.button.text_size, height=cfg.button.height,
                                   width=cfg.title.button_width, gap=cfg.button.gap)
        buttons = []
        for entry, box in zip(entries, self.layout.buttons, strict=True):
            button = self._buttons.get(entry.id)
            if button is None:
                button = self._buttons[entry.id] = self._button(entry)
            button.box = box
            buttons.append(button)
        self.buttons = buttons
        self.scope.set_groups([FocusGroup(buttons, column=True)])
        self.scope.default_widget = buttons[0] if buttons else None
        self.revision += 1

    def _button(self, entry: MenuEntry) -> Button:
        words = self.shell.words
        return Button(lambda: words.get(entry.id), lambda: self._activate(entry),
                      enabled=entry.enabled, on=entry.on)

    def _activate(self, entry: MenuEntry) -> None:
        if entry.action is not None:
            entry.action(EntryContext(self.game_shell, self.input_kind))
        elif entry.page is not None:
            # F11 Load, F16 Settings: the page in the game menu's layout over the title.
            self.game_shell.open_title_page(entry.id, self.input_kind)
        else:
            _log.debug("Title entry %s has neither an action nor a page", entry.id)

    # -- lifecycle --

    def on_enter(self) -> None:
        self.game_shell.title_entered()

    def on_exit(self) -> None:
        super().on_exit()
        self.game_shell.title_exited()

    def leave(self, seconds: float, then: Callable[[], None]) -> None:
        """New Game: fade to black over ``seconds`` taking no input, then ``then()`` (which
        replaces the stack). ``seconds`` 0 cuts at once."""
        if self.leaving:
            return
        self.leaving = True
        self.repeat.stop()
        self.pressed = None
        self._leave_then = then
        self.out_s = max(0.0, seconds)
        self._out_fresh = True
        if self.out_s <= 0:
            self._finish_leave()

    def _finish_leave(self) -> None:
        self.out_t = 1.0
        then, self._leave_then = self._leave_then, None
        if then is not None:
            then()

    # -- input --

    def handle_event(self, event: UiEvent) -> bool:
        if self.leaving:
            return True                              # no input while it fades out
        if self.in_t < 1.0 and event.type in _INPUT_EVENTS:
            self.in_t = 1.0                          # any input finishes the fade-in
        return super().handle_event(event)

    def _on_nav(self, nav: Nav) -> None:
        if nav in (Nav.BACK, Nav.START):
            return                                   # nothing on the title (03 Interaction)
        super()._on_nav(nav)

    def back(self) -> None:
        """Back does nothing on the title (it never quits)."""

    def on_sampler(self) -> None:
        if self.shell.dev:
            from engine.ui.builtin.sampler import SamplerScreen

            self.push_child(SamplerScreen(self.shell, by=InputKind.KEYS))

    # -- frame --

    def update(self, dt: float, *, is_top: bool) -> None:
        if self.leaving:
            fresh, self._out_fresh = self._out_fresh, False
            if not fresh and self._leave_then is not None:
                self.out_t = min(1.0, self.out_t + dt / self.out_s)
                if self.out_t >= 1.0 - _EPSILON:
                    self._finish_leave()
            return
        if self.in_t < 1.0:
            self.in_t = min(1.0, self.in_t + dt / self.fade_in_s)
            if self.in_t >= 1.0 - _EPSILON:
                self.in_t = 1.0
        super().update(dt, is_top=is_top)

    def on_update(self, dt: float) -> None:
        overrides = self.game_shell.overrides
        if overrides.revision != self._seen_revision:
            self._seen_revision = overrides.revision
            self.build()                               # hidden entries, labels
            self._text_fit = None
            self.game_shell.title_look_changed()       # music; art is read every draw

    @property
    def darkness(self) -> float:
        """How far the title is toward black this frame (fade-in, then New Game)."""
        return max(1.0 - self.in_t, self.out_t)

    def draw(self, canvas: Canvas) -> None:
        assert self.built and self.layout is not None
        p = self.painter
        p.bind(canvas)
        background = self.game_shell.title_image("background")
        if background is not None:
            _draw_cover(canvas, background)
        else:
            self._draw_gradient(canvas)
        self._draw_logo(canvas, p, backing=background is not None)
        self.draw_widgets(p)
        if self.game_shell.config.title.show_version:
            self._draw_version(canvas, p)
        dark = self.darkness
        if dark > 0:
            surface = canvas.surface
            assert surface is not None
            to_black(surface, dark)

    def _draw_gradient(self, canvas: Canvas) -> None:
        draw_title_gradient(canvas, self.shell.theme.cfg.title)

    def _draw_logo(self, canvas: Canvas, p: Painter, *, backing: bool) -> None:
        assert self.layout is not None
        box = self.layout.logo
        cy = box.y + box.h / 2
        logo = self.game_shell.title_image("logo")
        if logo is not None:
            w, h = logo.size
            k = min(1.0, box.w / w, box.h / h)
            _blit_scaled(canvas, logo, k, (box.x, cy - h * k / 2))
            return
        font, lines = self._fit_title_text(canvas, box)
        if not lines:
            return
        handle = canvas.font_handle(font, font.size).font
        width = max(text_width(handle, line) for line in lines)
        height = handle.get_linesize() * len(lines)
        if backing:
            p.panel(Box(box.x - BACKING, cy - height / 2 - BACKING, width + 2 * BACKING,
                        height + 2 * BACKING))
        canvas.draw_text("\n".join(lines), font, self.shell.theme.cfg.title.logo.text_color,
                         (box.x, cy), anchor="midleft")

    def _fit_title_text(self, canvas: Canvas, box: Box) -> tuple[FontSpec, list[str]]:
        """``[game] title`` in at most 2 lines of ``box.w``: the size steps down by 4 (not
        below 40), then the second line ends in "…"."""
        theme = self.shell.theme
        text = escape_controls(self.game_shell.config.game.title)
        size = self.painter.scaled_size(theme.cfg.title.logo.text_size)
        key = (text, size, box.w)
        if self._text_fit is not None and self._text_fit[0] == key:
            return self._text_fit[1], self._text_fit[2]
        floor = min(TEXT_MIN, size)
        font = theme.font(size, bold=True)
        while True:
            lines = canvas.layout_lines(text, font, box.w, None)
            if len(lines) <= TEXT_MAX_LINES or font.size - TEXT_STEP < floor:
                break
            font = theme.font(font.size - TEXT_STEP, bold=True)
        lines = canvas.layout_lines(text, font, box.w, TEXT_MAX_LINES)
        self._text_fit = (key, font, lines)
        return font, lines

    def _draw_version(self, canvas: Canvas, p: Painter) -> None:
        theme = self.shell.theme
        cfg = theme.cfg
        version = escape_controls(self.game_shell.config.game.version)
        if not version:
            return
        scale = p.text_scale()
        font = theme.font(p.scaled_size(cfg.title.version.text_size))
        width = text_width(canvas.font_handle(font, font.size).font, version)
        h = round(VERSION_HEIGHT * scale)
        w = width + 2 * VERSION_PAD
        box = Box(VERSION_RIGHT - w, VERSION_BOTTOM - h, w, h)
        p.shape(box, FrameSpec(cfg.panel.fill_color, cfg.title.version.fill_opacity,
                               corner_radius=round(VERSION_RADIUS * scale)))
        canvas.draw_text(version, font, cfg.title.version.text_color,
                         (box.x + w / 2, box.y + h / 2), anchor="center")


def draw_title_gradient(canvas: Canvas, cfg: "TitleTheme") -> None:
    """The plain title backdrop: a vertical gradient from ``fill_top_color`` to
    ``fill_bottom_color`` over the whole viewport, one surface in ``SizedLru`` (also F33's
    content warning backdrop)."""
    surface = canvas.surface
    assert surface is not None
    size = surface.get_size()
    key = (GRADIENT_KEY, tuple(cfg.fill_top_color), tuple(cfg.fill_bottom_color), size)
    cache = canvas.assets.cache
    frame = canvas.assets.time.frame
    gradient = cache.get(key, frame)
    if gradient is None:
        gradient = vertical_gradient(size, cfg.fill_top_color, cfg.fill_bottom_color)
        cache.put(key, gradient, surface_cost(gradient), frame)
    surface.blit(gradient, (0, 0))


def _blit_scaled(canvas: Canvas, image: "ImageRef", k: float,
                 topleft: tuple[float, float]) -> None:
    """``image`` at ``k`` times its canvas size, its top-left at ``topleft`` (canvas units),
    through the cached device-size variant."""
    surface = canvas.surface
    assert surface is not None
    variant = canvas.assets.scaled(image, canvas.scale_x * k, canvas.scale_y * k,
                                   canvas.quality)
    surface.blit(variant, canvas.px(*topleft))


def _draw_cover(canvas: Canvas, image: "ImageRef") -> None:
    """``image`` scaled to cover the canvas keeping its aspect, centred."""
    w, h = image.size
    k = max(CANVAS_W / w, CANVAS_H / h)
    _blit_scaled(canvas, image, k, ((CANVAS_W - w * k) / 2, (CANVAS_H - h * k) / 2))


__all__ = ["TitleScreen", "draw_title_gradient"]
