"""Transition kinds: how a frame between two stage pictures is drawn (F09 ``04-technical.md``
§4.3, §6.4–6.6; 07 I-1).

Why this module exists: a transition is drawn from two whole pictures, the old composite
and the new one (``StageView`` keeps both, ADR-0007), with a few whole-buffer operations per
frame, so a dissolve, a fade, or a mask costs about what one or two more blits do (§10).
``KINDS`` is the one table of kinds: ``StageView`` builds a kind from a
``TransitionSpec.kind`` and F28 adds entries through review (C1).

A kind gets its pictures through ``KindFrame`` and does at most one heavy step per
``prepare_step`` call (True when it is ready to draw); the view starts its clock only then.
``draw(target, p, offset)`` draws progress ``p`` (0 < p < 1) into the stage's device
surface at ``offset`` (the shake); the view itself draws p = 0 (the old picture) and p = 1
(the new one, exactly). The alpha a kind derives from ``p`` must never fall as ``p`` grows:
the dissolve and the mask raise it with ``BLEND_RGBA_MAX`` (R3).

- **dissolve:** prepare copies the new picture into the view's SRCALPHA scratch ``S`` with
  alpha 0; each frame raises S's alpha to ``round(255p)``, then blits the old picture and S.
- **fade** (color ``c``): the old picture darkens toward ``c`` for the first half, the new
  one comes out of it for the second; weight ``w = |1 − 2p|`` (``fade_weight``), drawn as a
  blit, a multiply by ``255w``, and an add of ``c·(1 − w)``. Each half is linear.
- **glitch** (F28 ``04`` §6.6): ``render/glitch.GlitchKind``, the old picture then the new
  one from p = 0.5, torn hardest at the midpoint; reduced effects play it as a dissolve.
- **mask** (§6.6): the new picture shows where the mask's gray is below the progress, with a
  ``soft`` edge (``mask_alpha``). Prepare builds the index mask ``M8`` (an 8-bit ``P``
  surface the viewport's size, each index the exact gray; kept in the shared ``SizedLru``
  per (ref, size)): one step loads and scales the image, then one step per band of
  ≤ ``MASK_BAND_ROWS`` device rows reads the gray bytes (exact for a gray mask; pygame's
  ``grayscale`` for a colored one), then one step copies the new picture into ``S``. Each
  frame sets M8's palette to ``(255, 255, α(i, p))``, blits M8 into ``G`` (a view of the one
  byte buffer ``B``, byte order ARGB, so each pixel's bytes are ``255, 255, 255, α``), raises
  S's alpha to 255, multiplies S by ``A`` (a view of the same bytes in S's own pixel format:
  white with alpha α), then blits the old picture and S. A scratch in any other format, or a
  mask ``AssetManager.check`` finds unusable (missing, damaged, over F01's limits), plays as
  a dissolve; the ref is skipped for the rest of the run and the format fallback logs one
  INFO line (TR-F09-06).

``MaskStore`` is the view-owned part the mask kinds share: the unusable refs, the cache, and
``B`` (one ``MaskBuffer``, made when a mask first plays and remade only on resize, C7).
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import pygame

from engine.core.constants import ENTRY_OVERHEAD
from engine.core.logsetup import get_logger
from engine.render.effects import ease_in_out
from engine.render.glitch import GlitchKind

if TYPE_CHECKING:
    from engine.render.assets import AssetManager
    from engine.runtime.commands import TransitionSpec

RGB = tuple[int, int, int]

MASK_BAND_ROWS: Final = 270              # device rows of M8 built per frame (§6.6, §10)
# S's pixel formats the mask path supports (TR-F09-06), by channel masks (R, G, B, A).
SCRATCH_FORMATS: Final = {
    (0xFF0000, 0xFF00, 0xFF, 0xFF000000): "ARGB8888",
    (0xFF, 0xFF00, 0xFF0000, 0xFF000000): "ABGR8888",
}
_VIEW_ORDERS: Final = ("BGRA", "RGBA")   # byte orders whose view can match S's format
_MASK_CACHE_KEY: Final = "mask8"

_log = get_logger("stage")


# --- pure math (AC-F09-19) ---------------------------------------------------------------------

def progress(clock: float, seconds: float) -> float:
    """``clamp(clock / seconds)``; a clock within 1e-9 of the end counts as the end, so a
    whole number of 1/60 s frames reaches p = 1 exactly."""
    if seconds <= 0:
        return 1.0
    p = clock / seconds
    return 1.0 if p >= 1.0 - 1e-9 else max(0.0, p)


def linear(t: float) -> float:
    """The easing of dissolve, fade, and mask."""
    return t


def fade_weight(p: float) -> tuple[bool, float]:
    """``(new, w)``: which picture a fade shows at ``p`` (the new one from p = 0.5) and the
    weight it keeps against the color, ``w = |1 − 2p|``."""
    return (False, 1.0 - 2.0 * p) if p < 0.5 else (True, 2.0 * p - 1.0)


def mask_alpha(i: int, p: float, soft: float, reverse: bool) -> int:
    """The new picture's alpha (0–255) where the mask's gray is ``i`` (0–255), at progress
    ``p`` (07 I-1): with ``m′`` the gray (1 − gray when ``reverse``), 255 at p ≥ 1, the step
    ``m′ < p`` when ``soft`` is 0, else ``clamp((p·(1 + soft) − m′) / soft)``. It is 0 at
    p = 0 and never falls as ``p`` grows."""
    if p >= 1.0:
        return 255
    m = i / 255.0
    if reverse:
        m = 1.0 - m
    if soft <= 0.0:
        return 255 if m < p else 0
    a = (p * (1.0 + soft) - m) / soft
    return 0 if a <= 0.0 else 255 if a >= 1.0 else int(255.0 * a + 0.5)


def mask_palette(p: float, soft: float, reverse: bool) -> list[tuple[int, int, int]]:
    """M8's palette at ``p``: index ``i`` → ``(255, 255, α(i))``; blitted into ``G`` it
    becomes the bytes ``255, 255, 255, α`` (§6.6)."""
    return [(255, 255, mask_alpha(i, p, soft, reverse)) for i in range(256)]


def scratch_format(scratch: pygame.Surface) -> str | None:
    """``"ARGB8888"`` or ``"ABGR8888"``: S's pixel format, or None for any other."""
    return SCRATCH_FORMATS.get(tuple(scratch.get_masks()))


def view_order(scratch: pygame.Surface) -> str | None:
    """The byte order whose view of ``B`` has exactly S's pixel format (``"BGRA"`` for
    ARGB8888, ``"RGBA"`` for ABGR8888 on a little-endian machine), so the multiply in
    ``Mask.draw`` takes SDL's fast path; None when no view matches (the mask plays as a
    dissolve)."""
    masks = tuple(scratch.get_masks())
    if masks not in SCRATCH_FORMATS:
        return None
    for order in _VIEW_ORDERS:
        if tuple(pygame.image.frombuffer(bytearray(4), (1, 1), order).get_masks()) == masks:
            return order
    return None


# --- kinds -------------------------------------------------------------------------------------

class MaskBuffer:
    """``B``: one byte buffer of ``w·h·4`` and its two views, ``g`` (byte order ARGB, written
    by blitting M8) and ``a`` (S's own format, read by the multiply). One per ``MaskStore``."""

    __slots__ = ("size", "order", "data", "g", "a", "__weakref__")

    def __init__(self, size: tuple[int, int], order: str) -> None:
        self.size = size
        self.order = order
        self.data = bytearray(size[0] * size[1] * 4)
        self.g = pygame.image.frombuffer(self.data, size, "ARGB")
        self.a = pygame.image.frombuffer(self.data, size, order)


class MaskStore:
    """What the mask kinds of one ``StageView`` share across runs: the assets (whose
    ``SizedLru`` keeps M8 per (ref, size), charged ``w·h`` bytes), the refs found unusable
    (skipped for the rest of the run), whether the format fallback was logged, and ``B``."""

    def __init__(self, assets: "AssetManager") -> None:
        self.assets = assets
        self.unusable: set[str] = set()
        self.fallback_logged = False
        self.buffer: MaskBuffer | None = None

    def usable(self, ref: str) -> bool:
        """Whether ``ref`` can be a mask: ``AssetManager.check`` (no log: W60 was the launch
        warning) reads it through ``GamePaths.read_file`` into the cache, or remembers why
        not; an unusable ref is never asked about again."""
        if ref in self.unusable:
            return False
        if self.assets.check(ref, "image") is not None:
            self.unusable.add(ref)
            return False
        return True

    def index_mask(self, ref: str, size: tuple[int, int]) -> pygame.Surface | None:
        """M8 of ``ref`` at ``size``, if the cache still has it."""
        return self.assets.cache.get((_MASK_CACHE_KEY, ref, size), self.assets.time.frame)

    def keep(self, ref: str, size: tuple[int, int], m8: pygame.Surface) -> None:
        self.assets.cache.put((_MASK_CACHE_KEY, ref, size), m8,
                              size[0] * size[1] + ENTRY_OVERHEAD, self.assets.time.frame)

    def scaled(self, ref: str, size: tuple[int, int]) -> pygame.Surface | None:
        """The mask image smoothscaled to ``size`` (None if it can't be had after all)."""
        image = self.assets.image(ref)              # in the cache since ``usable``
        if image.is_placeholder:
            self.unusable.add(ref)
            return None
        source = self.assets.surface(image)
        if source.get_size() == size:
            return source
        return pygame.transform.smoothscale(source, size)

    def views(self, size: tuple[int, int], order: str) -> MaskBuffer:
        """``B`` at ``size``: made on first use, remade (the old one dropped first) only
        when the viewport size changes."""
        buffer = self.buffer
        if buffer is None or buffer.size != size or buffer.order != order:
            buffer = self.buffer = None
            buffer = self.buffer = MaskBuffer(size, order)
        return buffer


@dataclass(frozen=True, slots=True)
class KindFrame:
    """What a kind draws from: both pictures (device pixels, the viewport's size; the
    composites, or their colorshifted copies while F28's filter is on), the resolved color
    (``fade``), the view's one SRCALPHA scratch of that size, the spec (a mask's file,
    ``soft``, ``reverse``), the view's ``MaskStore``, and the resolved length in seconds
    (F28's ``glitch`` paces its tear by it)."""

    old: pygame.Surface
    new: pygame.Surface
    color: RGB
    scratch: Callable[[], pygame.Surface]
    spec: "TransitionSpec | None" = None
    masks: MaskStore | None = None
    seconds: float = 0.0


class TransitionKind(Protocol):
    """One kind of transition. The alpha drawn must never fall as ``p`` grows (§6.5)."""

    def __init__(self, frame: KindFrame) -> None: ...

    def prepare_step(self) -> bool:
        """One heavy step per call; True when ready to draw."""

    def draw(self, target: pygame.Surface, p: float, offset: tuple[int, int]) -> None:
        """The frame at progress ``0 < p < 1``."""


class Dissolve:
    """The new picture shows through the old one, evenly (§6.5)."""

    def __init__(self, frame: KindFrame) -> None:
        self.frame = frame
        self._s: pygame.Surface | None = None

    def prepare_step(self) -> bool:
        s = self.frame.scratch()
        s.blit(self.frame.new, (0, 0))
        s.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self._s = s
        return True

    def draw(self, target: pygame.Surface, p: float, offset: tuple[int, int]) -> None:
        s = self._s
        assert s is not None, "draw before prepare_step"
        s.fill((0, 0, 0, round(255 * p)), special_flags=pygame.BLEND_RGBA_MAX)
        target.blit(self.frame.old, offset)
        target.blit(s, offset)


class Fade:
    """Through a color: the old picture out, then the new one in (§6.5)."""

    def __init__(self, frame: KindFrame) -> None:
        self.frame = frame

    def prepare_step(self) -> bool:
        return True                                 # nothing to prepare

    def draw(self, target: pygame.Surface, p: float, offset: tuple[int, int]) -> None:
        frame = self.frame
        new, w = fade_weight(p)
        area = target.blit(frame.new if new else frame.old, offset)
        keep = int(255 * w + 0.5)
        target.fill((keep, keep, keep), area, special_flags=pygame.BLEND_RGB_MULT)
        add = tuple(int(c * (1.0 - w) + 0.5) for c in frame.color)
        target.fill(add, area, special_flags=pygame.BLEND_RGB_ADD)


class _Prepared:
    """What a ``Mask`` draws with once prepared (kept apart from the kind, so the prepare
    generator never refers back to it: no reference cycle keeps the pictures alive)."""

    __slots__ = ("dissolve", "m8", "b", "s")

    def __init__(self) -> None:
        self.dissolve: Dissolve | None = None
        self.m8: pygame.Surface | None = None
        self.b: MaskBuffer | None = None
        self.s: pygame.Surface | None = None


class Mask:
    """The new picture through a grayscale image (§6.6); a dissolve when the image or the
    scratch format can't be used."""

    def __init__(self, frame: KindFrame) -> None:
        self.frame = frame
        self.ready = _Prepared()
        self._steps: Iterator[bool] | None = _prepare_mask(frame, self.ready)

    def prepare_step(self) -> bool:
        assert self._steps is not None, "prepare_step after ready"
        done = next(self._steps)
        if done:
            self._steps = None
        return done

    def draw(self, target: pygame.Surface, p: float, offset: tuple[int, int]) -> None:
        ready = self.ready
        if ready.dissolve is not None:
            ready.dissolve.draw(target, p, offset)
            return
        m8, b, s, spec = ready.m8, ready.b, ready.s, self.frame.spec
        assert m8 is not None and b is not None and s is not None and spec is not None,             "draw before prepare_step"
        m8.set_palette(mask_palette(p, spec.soft, spec.reverse))
        b.g.blit(m8, (0, 0))
        s.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MAX)
        s.blit(b.a, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        target.blit(self.frame.old, offset)
        target.blit(s, offset)


def _prepare_mask(frame: KindFrame, ready: _Prepared) -> Iterator[bool]:
    """A ``Mask``'s preparation, yielding after each heavy step: the load and scale, each
    band, then the scratch copy (True). A dissolve's one step when the mask can't be used."""
    store, spec = frame.masks, frame.spec
    s = frame.scratch()
    size = s.get_size()
    order = view_order(s)
    if order is None and store is not None and not store.fallback_logged:
        store.fallback_logged = True
        _log.info("The stage's alpha buffer is not ARGB8888 or ABGR8888 here (masks %s), "
                  "so mask transitions play as dissolves.",
                  "/".join(f"{m:#x}" for m in s.get_masks()))
    ref = spec.mask if spec is not None else None
    m8 = None
    if order is not None and store is not None and ref is not None:
        m8 = store.index_mask(ref, size)
        if m8 is None:
            scaled = store.scaled(ref, size) if store.usable(ref) else None
            yield False                             # the load and scale (or the check)
            if scaled is not None:
                m8 = yield from _bands(scaled, size)
                store.keep(ref, size, m8)
    if m8 is None or order is None or store is None:
        ready.dissolve = Dissolve(frame)
        yield ready.dissolve.prepare_step()
        return
    ready.m8 = m8
    ready.b = store.views(size, order)
    s.blit(frame.new, (0, 0))
    ready.s = s
    yield True


def _bands(scaled: pygame.Surface, size: tuple[int, int]) -> Iterator[bool]:
    """M8's index bytes, one band of ≤ ``MASK_BAND_ROWS`` rows per step: a gray band's red
    bytes (exact), a colored band's ``grayscale``. Returns M8."""
    width, height = size
    rows = bytearray()
    for y in range(0, height, MASK_BAND_ROWS):
        band = scaled.subsurface((0, y, width, min(MASK_BAND_ROWS, height - y)))
        data = pygame.image.tobytes(band, "RGB")
        red = data[0::3]
        if not red == data[1::3] == data[2::3]:
            red = pygame.image.tobytes(pygame.transform.grayscale(band), "RGB")[0::3]
        rows += red
        if y + MASK_BAND_ROWS < height:
            yield False
    m8 = pygame.image.frombytes(bytes(rows), size, "P")
    yield False
    return m8


# The one table of kinds (C1): ``TransitionSpec.kind`` → its class. F28 adds ``glitch``
# (``render/glitch.GlitchKind``: torn halves, 04 §6.6).
KINDS: Final[dict[str, type[TransitionKind]]] = {"dissolve": Dissolve, "fade": Fade,
                                                  "mask": Mask, "glitch": GlitchKind}


__all__ = ["KINDS", "MASK_BAND_ROWS", "SCRATCH_FORMATS", "Dissolve", "Fade", "KindFrame",
           "Mask", "MaskBuffer", "MaskStore", "TransitionKind", "ease_in_out", "fade_weight",
           "linear", "mask_alpha", "mask_palette", "progress", "scratch_format", "view_order"]
