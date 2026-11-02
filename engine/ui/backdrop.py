"""``CapturedBackdrop``: the frozen scene under a menu, captured once and dimmed once.

Why this module exists: a menu over the game shows the scene exactly as it was, dimmed
(PR-F10-01). Nothing below a menu changes while it is up: the story is held (F10 ``04`` §7.1),
in-game timers are frozen, and a non-top menu draws no pressed look or hover change. So the
screens below are drawn once more, copied, and dimmed once, and from then on the menu blits
that copy and is opaque. That keeps the game-menu frame at about 1 ms at 1080p instead of
redrawing the scene and the dim every frame (``04`` §11: 1.17 against 2.88 ms p99).

Lifecycle (``04`` §7.6):

1. Opened: ``ready`` is False, so the screen is not opaque and the stack draws the screens
   below this frame.
2. The screen's ``draw`` calls ``capture(canvas)`` first. If the viewport size or quality
   differs from the stored key: ``scene`` is a copy of what is below (the F3 overlay is drawn
   after the stack, so it is never in it) and ``dimmed`` a copy dimmed at full opacity. Both
   are held ``SizedLru`` entries ``("ui-backdrop", id(self), part)`` costing ``w·h·4``. Then
   ``ready`` is True and the screen is opaque from the next frame.
3. Later frames blit ``dimmed`` (or the scene and a partial dim while a fade runs).
4. A viewport size or quality change (resize, settle end) or ``invalidate()`` (F16 text size,
   F39 reload): this frame blits the old ``dimmed`` through ``transform.scale`` (uncached,
   F01's FAST rule) and ``ready`` turns False, so the next frame draws the screens below again
   and recaptures.
5. Without ``keep_scene`` the scene is dropped once the opening fade ends; ``release()`` on
   close lets both go.

``scene_picture()`` gives the scene (device pixels of the viewport) to F11's thumbnails.
``on_scene`` (F11 C3, set by ``GameShell``) is called with the undimmed scene at every capture
(step 2), so the shell keeps its 320×180 save thumbnail even when the scene is not kept.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

import pygame

from engine.render.frames import dim

if TYPE_CHECKING:
    from engine.render.assets import AssetManager
    from engine.render.canvas import Canvas

BACKDROP_KEY: Final = "ui-backdrop"
RGB = tuple[int, int, int]


class CapturedBackdrop:
    """The dimmed frozen scene for one open menu (``GameMenuScreen``, ``ConfirmScreen``)."""

    def __init__(self, assets: "AssetManager", color: RGB, opacity: float, *,
                 keep_scene: bool) -> None:
        self.assets = assets
        self.color = tuple(color)
        self.opacity = opacity
        self.keep_scene = keep_scene
        self.ready = False
        self.live = False          # draw over the live screens below (a close without scene)
        self.scene: pygame.Surface | None = None
        self.dimmed: pygame.Surface | None = None
        self.captures = 0          # how many times the screens below were copied (TR-F10-04)
        # F11 C3: called with the undimmed scene each time the screens below are copied.
        self.on_scene: Callable[[pygame.Surface], None] | None = None
        self._key: tuple | None = None

    # -- per frame --

    def capture(self, canvas: "Canvas", *, need_scene: bool = True) -> bool:
        """Call first in the screen's ``draw``. Returns True when ``dimmed`` (and ``scene``,
        if needed) match this frame's viewport; False when this frame shows the old
        ``dimmed`` scaled (already blitted) and the next frame recaptures."""
        surface = canvas.surface
        assert surface is not None
        key = (surface.get_size(), canvas.quality)
        if self.live:
            return False
        if key == self._key and self.dimmed is not None \
                and (self.scene is not None or not need_scene):
            return True
        if self.ready and self.dimmed is not None:
            # Opaque this frame: the screens below were not drawn, so show the old picture
            # scaled and capture next frame (they are frozen and unchanged).
            surface.blit(pygame.transform.scale(self.dimmed, surface.get_size()), (0, 0))
            self.ready = False
            return False
        self._store(surface, key, need_scene)
        self.ready = True
        return True

    def draw(self, canvas: "Canvas", a: float = 1.0) -> None:
        """Blit the backdrop at fade progress ``a``: the dimmed copy at 1, else the scene
        with a dim of ``opacity × a`` (two constant fills). In ``live`` mode the screens below
        were just drawn: only the dim is added."""
        surface = canvas.surface
        assert surface is not None
        if self.live:
            dim(surface, self.color, self.opacity * a)
            return
        if a >= 1.0 or self.scene is None:
            if self.dimmed is not None:
                surface.blit(self.dimmed, (0, 0))
            return
        surface.blit(self.scene, (0, 0))
        dim(surface, self.color, self.opacity * a)

    # -- changes --

    def go_live(self) -> None:
        """Stop using the copies: from the next frame the screens below are drawn again and
        only the dim is added (a closing fade after the scene was dropped)."""
        self.live = True
        self.ready = False

    def invalidate(self) -> None:
        """Recapture: this frame scales the old picture, the next one copies again."""
        self._key = None

    def drop_scene(self) -> None:
        """Let the undimmed scene go (screens that don't keep it, after their opening fade)."""
        if not self.keep_scene and self.scene is not None:
            self._forget("scene")
            self.scene = None

    def release(self) -> None:
        """Closing: release and discard both copies."""
        for part in ("scene", "dimmed"):
            if getattr(self, part) is not None:
                self._forget(part)
        self.scene = self.dimmed = None
        self.ready = False
        self._key = None

    def scene_picture(self) -> pygame.Surface | None:
        """The captured scene (device pixels of the viewport), or None (F11, PR-F10-31)."""
        return self.scene

    # -- internals --

    def _store(self, surface: pygame.Surface, key: tuple, need_scene: bool) -> None:
        self.release()
        scene = surface.copy()
        if self.on_scene is not None:
            self.on_scene(scene)
        dimmed = scene.copy()
        dim(dimmed, self.color, self.opacity)
        self.captures += 1
        self._key = key
        self.dimmed = dimmed
        self._remember("dimmed", dimmed)
        if need_scene or self.keep_scene:
            self.scene = scene
            self._remember("scene", scene)

    def _cache_key(self, part: str) -> tuple:
        return (BACKDROP_KEY, id(self), part)

    def _remember(self, part: str, surface: pygame.Surface) -> None:
        cache = self.assets.cache
        key = self._cache_key(part)
        cache.hold(key)
        width, height = surface.get_size()
        cache.put(key, surface, width * height * 4, self.assets.time.frame)

    def _forget(self, part: str) -> None:
        cache = self.assets.cache
        key = self._cache_key(part)
        cache.release(key)
        cache.discard(key)


__all__ = ["BACKDROP_KEY", "CapturedBackdrop"]
