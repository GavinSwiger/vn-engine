"""``ThumbCache``: the launch's thumbnails for picture tiles (F34 ``04-technical.md`` §7.4,
PR-F34-14; ``07-architecture-review.md`` I-2, I-3).

Why this module exists: a gallery page shows up to 12 pictures, each usually a 1920×1080 PNG
that takes about 36 ms to decode, so opening or turning a page must not decode them in the
frame loop (ADR-0005). The launch's ``ImagePrefetcher`` decodes them off the main thread
(ADR-0007); this cache turns each decoded picture into a small tile-sized thumbnail and
keeps it, so a page opened again shows at once. F34's Gallery page and F36's Scenes page
share one cache per launch (``app/extras.py`` makes it and hands it to the pages' ports).

- ``want(refs)`` (a page is built or turned): these picture files are the ones to make,
  in order. Nothing is made in the frame of a ``want`` (the opening or turning frame).
- ``pump()`` (once per frame, from the page's ``update``): pumps the prefetcher (through
  ``can_pump``, so W3 can pump it only on the title, I-3), then makes **at most one**
  thumbnail: the first wanted picture whose source is already in the asset cache, scaled to
  cover the box with a centre crop. The prefetcher is asked for one picture at a time, so
  when it is idle and the picture still isn't cached, the prefetcher refused it (bigger than
  ``PREFETCH_ONE_MAX``) or the file failed; only then is it loaded on the main thread
  (``assets.image``: a missing file gives F04's placeholder and its one warning), at most
  once per picture per launch, one per frame (I-2). Without a prefetcher every picture is
  loaded that way, one per frame.
- ``get(ref, size)`` (drawing): the thumbnail at ``size`` device pixels, or None while it
  isn't ready (the tile draws its empty look). A miss at a new size (the window changed)
  wants it again.
- ``ask(refs)`` (F34's viewer): prefetch these pictures next (the viewer's next picture);
  ``pump_prefetcher()`` pumps without making a thumbnail (the viewer covers the page).

Thumbnails live in their own ``SizedLru`` of ``THUMB_BUDGET`` (16 MiB), keyed by
``(ref, size)``; a thumbnail made by the main-thread fallback is held for the launch, so the
fallback never runs twice for one picture. Imports: ``core``, ``render`` (the prefetch
request), ``pygame``.
"""

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Final, Protocol

import pygame

from engine.core.constants import ENTRY_OVERHEAD, MB
from engine.core.lru import SizedLru
from engine.render.prefetch import PrefetchRequest

if TYPE_CHECKING:
    from engine.render.assets import ImageRef

THUMB_BUDGET: Final = 16 * MB
THUMB_BOX: Final = (188, 106)          # the tile's picture box in canvas units (UI-F34-01)

Size = tuple[int, int]


class ThumbAssets(Protocol):
    """What the cache uses of ``AssetManager`` (main thread only)."""

    scale_filter: str
    time: Any                          # ``GameTime``: ``frame``

    def image(self, ref: str) -> "ImageRef": ...

    def surface(self, image: "ImageRef") -> pygame.Surface: ...

    def is_cached(self, ref: str) -> bool: ...


class ThumbPrefetcher(Protocol):
    """What the cache uses of ``ImagePrefetcher``."""

    @property
    def pending(self) -> bool: ...

    def request(self, wanted: Iterable[PrefetchRequest]) -> None: ...

    def pump(self) -> None: ...


def cover_crop(source_size: Size, size: Size) -> tuple[int, int, int, int]:
    """The centred part ``(x, y, w, h)`` of a ``source_size`` picture that, scaled, covers
    ``size`` exactly (D8: tiles crop, the viewer fits)."""
    sw, sh = max(1, source_size[0]), max(1, source_size[1])
    tw, th = max(1, size[0]), max(1, size[1])
    scale = max(tw / sw, th / sh)
    cw = max(1, min(sw, round(tw / scale)))
    ch = max(1, min(sh, round(th / scale)))
    return (sw - cw) // 2, (sh - ch) // 2, cw, ch


class ThumbCache:
    """The per-launch thumbnail cache (module docstring)."""

    def __init__(self, assets: ThumbAssets, prefetcher: ThumbPrefetcher | None = None, *,
                 budget_bytes: int = THUMB_BUDGET,
                 can_pump: Callable[[], bool] | None = None) -> None:
        self.assets = assets
        self.prefetcher = prefetcher
        self.can_pump: Callable[[], bool] = can_pump if can_pump is not None else (lambda: True)
        self._lru: SizedLru[tuple[str, Size], pygame.Surface] = SizedLru(budget_bytes)
        self.size: Size = THUMB_BOX                 # the device size of the last draw
        self._wanted: list[str] = []
        self._fresh = False                         # a want this frame: make nothing
        self._asked: str | None = None              # the one picture the prefetcher has
        self._refused: set[str] = set()             # asked, idle, still not cached
        self._fallen: set[str] = set()              # loaded on the main thread (once each)
        self.made = 0                               # thumbnails made (tests, the overlay)
        self.main_loads = 0                         # main-thread fallback loads

    # -- the page's calls --

    def want(self, refs: Iterable[str]) -> None:
        """The pictures of the page now shown, in order (file refs). Replaces the previous
        page's; nothing is made until the next frame's ``pump``."""
        seen: set[str] = set()
        self._wanted = [r for r in refs if isinstance(r, str) and not (r in seen or seen.add(r))]
        self._fresh = True
        self._asked = None
        self._ask_next()

    def get(self, ref: str, size: Size) -> pygame.Surface | None:
        """The thumbnail of ``ref`` at ``size`` device pixels, or None (not ready yet). A
        miss wants it at that size."""
        size = (max(1, int(size[0])), max(1, int(size[1])))
        found = self._lru.get((ref, size), self.assets.time.frame)
        if found is not None:
            return found
        if size != self.size:
            self.size = size
        if ref not in self._wanted:
            self._wanted.append(ref)
        return None

    def ready(self, ref: str, size: Size | None = None) -> bool:
        """Whether ``ref``'s thumbnail is made (at ``size``; default the last drawn size)."""
        return (ref, size or self.size) in self._lru

    def pump(self) -> str | None:
        """Once per frame (module docstring). Returns the ref whose thumbnail was made, or
        None."""
        if self._fresh:
            self._fresh = False                     # the opening or turning frame
            return None
        self.pump_prefetcher()
        missing = [r for r in self._wanted if (r, self.size) not in self._lru]
        if not missing:
            return None
        assets = self.assets
        pf = self.prefetcher
        if pf is not None:
            asked = self._asked
            if asked is not None and not pf.pending:
                if not assets.is_cached(asked) and (asked, self.size) not in self._lru:
                    self._refused.add(asked)        # idle and still not cached: refused
                self._asked = None
            if self._asked is None:
                self._ask_next()                    # keep the worker busy
        for ref in missing:                         # 1. a source already decoded
            if assets.is_cached(ref):
                self._make(ref, hold=False)
                return ref
        if pf is None:                              # 2. no prefetch: main thread, one per frame
            return self._fallback(missing[0])
        for ref in missing:                         # 3. a refused one, once per launch
            if ref in self._refused and ref not in self._fallen:
                return self._fallback(ref)
        return None

    def pump_prefetcher(self) -> None:
        """Pump the prefetcher (only when ``can_pump()``)."""
        if self.prefetcher is not None and self.can_pump():
            self.prefetcher.pump()

    def ask(self, refs: Iterable[str]) -> None:
        """Prefetch ``refs`` next (the viewer's next picture); the page's own request is
        made again by its next ``want``."""
        if self.prefetcher is None:
            return
        self._asked = None
        self.prefetcher.request([PrefetchRequest(ref) for ref in refs])

    # -- internals --

    def _ask_next(self) -> None:
        """Ask the prefetcher for the first wanted picture not cached, made, or refused."""
        pf = self.prefetcher
        if pf is None:
            return
        for ref in self._wanted:
            if ((ref, self.size) in self._lru or ref in self._refused or ref in self._fallen
                    or self.assets.is_cached(ref)):
                continue
            pf.request([PrefetchRequest(ref)])
            self._asked = ref
            return

    def _fallback(self, ref: str) -> str:
        self._fallen.add(ref)
        self.main_loads += 1
        self._make(ref, hold=True)
        return ref

    def _make(self, ref: str, *, hold: bool) -> None:
        """Scale ``ref`` to cover ``self.size`` with a centre crop, into the cache."""
        assets = self.assets
        source = assets.surface(assets.image(ref))
        size = self.size
        x, y, w, h = cover_crop(source.get_size(), size)
        piece = source.subsurface(pygame.Rect(x, y, w, h))
        if piece.get_size() == size:
            thumb = piece.copy()
        elif assets.scale_filter == "pixel" or piece.get_bitsize() not in (24, 32):
            thumb = pygame.transform.scale(piece, size)
        else:
            thumb = pygame.transform.smoothscale(piece, size)
        key = (ref, size)
        cost = size[0] * size[1] * thumb.get_bytesize() + ENTRY_OVERHEAD
        self._lru.put(key, thumb, cost, assets.time.frame)
        if hold:
            self._lru.hold(key)
        self.made += 1


__all__ = ["THUMB_BOX", "THUMB_BUDGET", "ThumbAssets", "ThumbCache", "ThumbPrefetcher",
           "cover_crop"]
