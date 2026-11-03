"""``GalleryViewer``: one gallery picture at a time, full screen (F34 ``01-design.md`` §6.3,
PR-F34-13, UI-F34-04 and 05; ``04-technical.md`` §7.5).

Why this module exists: the gallery's tiles are small; the player looks at a picture whole.
The viewer is an F10 ``MenuScreen`` pushed over the Extras screen (``push_child``), so it
fades in and out and takes mouse, keys, and gamepad the F10 way, but it has no widgets.

- **Look.** ``gallery.viewer.fill_color`` (black until the config has it) fills 1280×720;
  the picture is scaled to fit, aspect kept (up or down), and centred
  (``assets.variant``, cached). A solid-colour picture fills the canvas; a missing file is
  F04's placeholder. Nothing else is drawn.
- **Order** (§7.5): the pictures given are every unlocked picture in gallery order.
  Next: +1; past the last it closes. Previous: −1, nothing at the first. Back closes.
  ``on_close(key, by)`` gets the key of the last picture shown and the closing input kind.
- **Input** (UI-F34-04). Next: a click, Enter, Space, gamepad A, Right, Page Down, the
  wheel down. Previous: Left, Page Up, the wheel up. Back: Esc, right click, gamepad B.
- **Motion** (UI-F34-05). F10's fade in and out (``ui.fade_ms``), drawn as a dim of the
  screens below towards the fill colour plus the picture at the fade's alpha (no
  canvas-sized layer). A change crossfades over 200 ms of game time; any input first
  finishes a crossfade, then acts. Reduced motion: cuts.
- **Cost** (PR-F34-14). A change loads one picture (``assets.image``: usually cached by the
  prefetch) and asks the ``ThumbCache``'s prefetcher for the next one; ``update`` pumps it,
  since the page under the viewer doesn't update while covered.
"""

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.constants import CANVAS_SIZE
from engine.render.canvas import Canvas
from engine.render.frames import dim
from engine.ui.focus import Box
from engine.ui.menu_screen import MenuScreen, MenuShell, Phase
from engine.ui.nav import InputKind, Nav

if TYPE_CHECKING:
    import pygame

    from engine.render.assets import ImageRef
    from engine.ui.paint import Painter
    from engine.ui.thumbs import ThumbCache

RGB = tuple[int, int, int]
CROSSFADE_S: Final = 0.2
FILL_DEFAULT: Final = (0, 0, 0)       # gallery.viewer.fill_color default
CANVAS_BOX: Final = Box(0, 0, *CANVAS_SIZE)
_EPSILON: Final = 1e-9


@dataclass(frozen=True)
class ViewerPicture:
    """One picture: the key of its tile and its source (a file ref, a colour, or None)."""

    key: Hashable
    source: "str | RGB | None"


def fill_color(cfg) -> RGB:
    """``gallery.viewer.fill_color`` (black before the config has the ``gallery`` area)."""
    viewer = getattr(getattr(cfg, "gallery", None), "viewer", None)
    color = getattr(viewer, "fill_color", None)
    return tuple(color)[:3] if color is not None else FILL_DEFAULT       # type: ignore


def fit_box(size: tuple[float, float], box: Box = CANVAS_BOX) -> Box:
    """``size`` scaled to fit ``box`` (up or down), aspect kept, centred."""
    w, h = size
    if w <= 0 or h <= 0:
        return Box(box.x + box.w / 2, box.y + box.h / 2, 0, 0)
    s = min(box.w / w, box.h / h)
    tw, th = w * s, h * s
    return Box(box.x + (box.w - tw) / 2, box.y + (box.h - th) / 2, tw, th)


class GalleryViewer(MenuScreen):
    """The full-canvas viewer (module docstring)."""

    def __init__(self, shell: MenuShell, *, by: InputKind, pictures: Sequence[ViewerPicture],
                 start: int = 0,
                 on_close: Callable[[Hashable, InputKind], None] | None = None,
                 thumbs: "ThumbCache | None" = None) -> None:
        assert pictures, "the viewer needs at least one picture"
        self.pictures = tuple(pictures)
        self.index = max(0, min(start, len(self.pictures) - 1))
        self.on_close = on_close
        self.thumbs = thumbs
        self.fill = fill_color(shell.theme.cfg)
        self.loads = 0                                  # pictures loaded (tests)
        self._current = None
        self._old = None
        self.cross = 1.0                                # crossfade progress (1: done)
        self._cross_fresh = False
        super().__init__(shell, by=by)
        self._current = self._load(self.index)
        self._prefetch_next()

    # -- state --

    @property
    def current(self) -> ViewerPicture:
        return self.pictures[self.index]

    @property
    def crossfading(self) -> bool:
        return self.cross < 1.0

    @property
    def opaque(self) -> bool:                           # type: ignore[override]
        """Open, the viewer covers the whole canvas: nothing below needs drawing."""
        return self.phase is Phase.OPEN

    def layer_box(self) -> Box:
        return CANVAS_BOX

    # -- moves --

    def step(self, delta: int) -> None:
        """Next (+1) or Previous (−1); past the last, close; nothing before the first."""
        self.finish_crossfade()
        target = self.index + delta
        if target < 0:
            return
        if target >= len(self.pictures):
            self.close()
            return
        old = self._current
        self.index = target
        self._current = self._load(target)
        if self.shell.reduce_motion:
            self._old, self.cross = None, 1.0
        else:
            self._old, self.cross, self._cross_fresh = old, 0.0, True
        self._prefetch_next()
        self.revision += 1

    def finish_crossfade(self) -> None:
        self._old, self.cross = None, 1.0

    def back(self) -> None:
        self.finish_crossfade()
        self.close()

    def _load(self, index: int):
        """The picture's ``ImageRef`` (loaded now; usually prefetched) or its colour."""
        source = self.pictures[index].source
        if isinstance(source, str):
            self.loads += 1
            return self.shell.assets.image(source)
        return source

    def _prefetch_next(self) -> None:
        thumbs = self.thumbs
        nxt = self.index + 1
        if thumbs is None or nxt >= len(self.pictures):
            return
        source = self.pictures[nxt].source
        if isinstance(source, str):
            thumbs.ask([source])

    # -- MenuScreen --

    def unused_nav(self, nav: Nav) -> bool:
        if nav in (Nav.ACTIVATE, Nav.RIGHT, Nav.PAGE_DOWN):
            self.step(1)
            return True
        if nav in (Nav.LEFT, Nav.PAGE_UP):
            self.step(-1)
            return True
        if self.crossfading and nav is not None:
            self.finish_crossfade()
            return True
        return False

    def unused_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if kind == "down":
            self.finish_crossfade()
            return True                                  # its release is the click
        if kind == "up":
            if pos[0] > -1.0e8:                          # released inside the canvas
                self.step(1)
            return True
        if kind == "wheel" and notches:
            self.step(-1 if notches > 0 else 1)
            return True
        return False

    def on_update(self, dt: float) -> None:
        if self.crossfading:
            if self._cross_fresh:
                self._cross_fresh = False                # from the frame after the change
            else:
                self.cross = min(1.0, self.cross + dt / CROSSFADE_S)
                if self.cross >= 1.0 - _EPSILON:
                    self.finish_crossfade()
        if self.thumbs is not None:
            self.thumbs.pump_prefetcher()

    def on_exit(self) -> None:
        super().on_exit()
        if self.on_close is not None:
            self.on_close(self.current.key, self._closed_by or self.input_kind)

    # -- drawing --

    def draw(self, canvas: Canvas) -> None:
        surface = canvas.surface
        assert surface is not None
        a = self.alpha
        if a >= 1.0:
            surface.fill(self.fill)
        else:
            dim(surface, self.fill, a)
        if self._old is not None and self.crossfading:
            self._draw_picture(canvas, self._old, a * (1.0 - self.cross))
            self._draw_picture(canvas, self._current, a * self.cross)
        else:
            self._draw_picture(canvas, self._current, a)

    def draw_content(self, p: "Painter") -> None:
        pass                                              # ``draw`` does it all

    def _draw_picture(self, canvas: Canvas, picture, alpha: float) -> None:
        if picture is None or alpha <= 0.0:
            return
        surface = canvas.surface
        assert surface is not None
        if not hasattr(picture, "size"):                  # a solid colour: the whole canvas
            color = tuple(picture)[:3]
            if alpha >= 1.0:
                surface.fill(color)
            else:
                dim(surface, color, alpha)
            return
        image: "ImageRef" = picture
        box = fit_box(image.size)
        rect = canvas.rect_to_px((box.x, box.y, box.w, box.h))
        if rect.width <= 0 or rect.height <= 0:
            return
        scaled, _offset = canvas.assets.variant(image, rect.size, canvas.quality)
        _blit_alpha(surface, scaled, rect.topleft, alpha)


def _blit_alpha(surface: "pygame.Surface", source: "pygame.Surface", pos: tuple[int, int],
                alpha: float) -> None:
    """Blit ``source`` at ``alpha`` (0–1), leaving its own alpha setting as it was (it is
    a shared cached variant)."""
    if alpha >= 1.0:
        surface.blit(source, pos)
        return
    previous = source.get_alpha()
    source.set_alpha(max(0, round(255 * alpha)))
    try:
        surface.blit(source, pos)
    finally:
        source.set_alpha(previous)


__all__ = ["CROSSFADE_S", "GalleryViewer", "ViewerPicture", "fill_color", "fit_box"]
