"""Glitch looks: the pure math, the static noise, and the colorshift filter's build (F28
``04-technical.md`` §6.5, §6.6, §6.7; ``07`` I-4, I-6; PR-F28-05 to 08, UI-F28-02, 05).

Why this module exists: glitches are presentation timing, not story state. The runtime only
sends ``Glitch`` commands, and ``StageScreen`` plays them on F09's effect clock. Everything
random here is derived from a presentation seed with ``mix64``, never from ``random``'s
shared state or the story's dice (PR-F28-13), so a test that fixes the seed fixes every
frame.

- **Sizes** (01 §6.2), in canvas units: ``T`` tear shift, ``C`` colorshift offset, ``S``
  static strength (a fraction), ``J`` jitter reach.
- **Rates** (07 I-4, I-6): a look's step index is ``look_index(t, rate)`` with ``t`` the
  seconds since the look started; tear and static re-pick 10 times a second, jitter 12.
  Every index change happens at a multiple of ``1/rate``, so no half-open second holds more
  than ``rate`` changes.
- **Tear** (§6.6): ``tear_bands`` picks 2–6 bands, 8–80 units tall, together at most 40% of
  the canvas height, never overlapping, each sliding by ``±(¼…1)·shift``. ``draw_tear``
  rolls each band's device rows in place with wrap (``Surface.scroll`` with
  ``SCROLL_REPEAT``), so every row keeps its pixel multiset and nothing outside the bands
  is written.
- **Static** (§6.6): ``Noise`` holds one 640×360-cell byte field (2-unit grain) scaled
  (nearest) to the viewport, and a display-format copy at strength ``s``. A frame multiplies
  the stage by ``round(255(1 − s))`` and adds the copy at a wrap offset, so every frame adds
  the same pixel multiset and the stage's mean brightness never pulses (PR-F28-07).
- **Jitter** (§6.6): ``jitter_offset`` is an integer offset in ``[−a, a]²``, never (0, 0).
- **Colorshift** (§6.5): ``ColorShift`` builds the filtered copy of a picture in bands of at
  most 270 rows (8 ``BLEND_RGB_*`` operations each): red taken from ``d`` px to the right
  (drawn shifted left), blue from ``d`` px to the left, green in place, the missing edge
  columns black. It keeps at most two outputs. ``StageView`` filters its pictures through it.

The pure functions need no window; ``draw_tear``, ``Noise``, and ``ColorShift`` use plain
``Surface``s. Callers (``GlitchLayer``) run every allocation and draw inside the per-kind
``try`` of 07 I-17 (W183).

**``GlitchLayer``** (§6.4; 07 I-5 to I-7; F28 step 4) plays ``Glitch`` commands on
``StageScreen``'s effect clock. It keeps one *look* per ``(kind, jitter tag)``: the lasting
size (from ``cmd.lasting``), the running burst, the time ``t0`` and seed of what shows now
(a new seed at every start and hand-off, ``mix64(layer seed, start counter)``), and the
reduced envelope's ``shown_at``/``gone_at``. Photosensitivity, all in the presentation:

- **Flash limit** (PR-F28-10, D8, 07 I-5): one ``FlashLimiter.admit`` per command when it
  starts a counted burst (not jitter, under 1 s, drawn after reduction) or starts, ends, or
  resizes a lasting static or colorshift. Refused: the counted bursts are dropped (W182 once
  per statement, none under reduce) and the lasting set waits as the *target*, retried once a
  tick (a newer command replaces it; one equal to what shows cancels it). Tear and jitter
  toggles, bursts of 1 s or more, restores, and ``clear()`` never count.
- **Reduced effects** (PR-F28-11): no tear, no jitter (their bursts are dropped); static is
  one still ``small`` frame faded in and out over 0.3 s (``ease_in_out``). The flag is read
  every frame, so switching it changes the look at once.
- **Pattern rate**: each look re-picks at most 10 times a second (12 for jitter), and static
  keeps the stage's mean brightness (``Noise``).

Drawing (D1): jitter copies (``StageView.draw_sprite_copy``) → tear → static, over the stage
viewport only, never on FAST settle frames (07 I-7). Each kind draws in its own ``try``: a
``pygame.error`` or ``MemoryError`` turns that kind off for the run with one W183. Buffers
(the noise, the colorshift outputs) are released at the first tick with no look of their
kind. Colorshift is not drawn here: ``filter`` gives ``StageScreen`` the ``ColorShift`` for
``StageView.set_filter`` (F28 step 5), which filters the stage picture itself.

**``GlitchKind``** is ``with glitch`` (``render/transitions.KINDS["glitch"]``): the old
picture, then the new one from p = 0.5, torn hardest at the midpoint.
"""

import math
import zlib
from collections.abc import Callable
from random import Random
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, NamedTuple

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.core.logsetup import get_logger
from engine.render.canvas import RenderQuality
from engine.render.effects import FADE_COUNTS_UNDER_S, FlashLimiter, RefusalLog, ease_in_out
from engine.runtime.glitch import EMPTY_GLITCH, GlitchState, glitch_failed_text, \
    glitch_refused_text

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.render.stage import StageView
    from engine.render.transitions import KindFrame
    from engine.runtime.commands import Glitch, GlitchBurst
    from engine.runtime.stage import StageState

# --- Sizes (01 §6.2; 04 §6.6), canvas units or a strength fraction --------------------------
T: Final = MappingProxyType({"small": 16, "medium": 40, "large": 96})          # tear shift
C: Final = MappingProxyType({"small": 2, "medium": 6, "large": 12})            # colorshift
S: Final = MappingProxyType({"small": 0.15, "medium": 0.30, "large": 0.50})    # static
J: Final = MappingProxyType({"small": 4, "medium": 10, "large": 24})           # jitter

# --- Rates: re-picks per second (PR-F28-05, 07, 08; 07 I-4) --------------------------------
TEAR_RATE: Final = 10
STATIC_RATE: Final = 10
JITTER_RATE: Final = 12

# --- Tear bands (04 §6.6) -----------------------------------------------------------------
TEAR_BANDS: Final = (2, 6)                       # bands per pick
TEAR_BAND_HEIGHT: Final = (8, 80)                # units
TEAR_MAX_TOTAL: Final = CANVAS_SIZE[1] * 2 // 5  # 40% of the canvas height (288 units)

# --- Static noise (04 §6.6) ---------------------------------------------------------------
NOISE_GRAIN: Final = 2                           # units per noise cell
NOISE_CELLS: Final = (CANVAS_SIZE[0] // NOISE_GRAIN, CANVAS_SIZE[1] // NOISE_GRAIN)

# --- Colorshift (04 §6.5) -----------------------------------------------------------------
COLORSHIFT_BAND_ROWS: Final = 270                # rows built per step
COLORSHIFT_OUTPUTS: Final = 2                    # filtered pictures kept

_MASK64: Final = (1 << 64) - 1
_GOLDEN64: Final = 0x9E3779B97F4A7C15
_INDEX_EPSILON: Final = 1e-9                     # f/600 · 12 lands just under an integer


def _finalize(z: int) -> int:
    """splitmix64's output function: a bijection on 64-bit integers."""
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return z ^ (z >> 31)


def mix64(seed: int, n: int) -> int:
    """A 64-bit hash of ``(seed, n)`` (04 §4.3): each look's seed is ``mix64(layer seed,
    start counter)``, and each look index ``k`` starts a stream at ``mix64(seed, k)``.
    Deterministic; Python ints of any size or sign are folded to 64 bits."""
    return _finalize((_finalize(seed & _MASK64) + ((n & _MASK64) + 1) * _GOLDEN64) & _MASK64)


class _Stream:
    """A splitmix64 stream started at ``mix64(seed, k)``."""

    __slots__ = ("state",)

    def __init__(self, seed: int, k: int) -> None:
        self.state = mix64(seed, k)

    def next(self) -> int:
        self.state = (self.state + _GOLDEN64) & _MASK64
        return _finalize(self.state)

    def below(self, n: int) -> int:
        """An integer in ``[0, n)`` (``n ≥ 1``)."""
        return (self.next() * n) >> 64

    def between(self, lo: int, hi: int) -> int:
        """An integer in ``[lo, hi]``."""
        return lo + self.below(hi - lo + 1)

    def unit(self) -> float:
        """A float in ``[0, 1]``."""
        return (self.next() >> 11) / ((1 << 53) - 1)


def look_index(elapsed: float, rate: int) -> int:
    """A look's step index ``floor(elapsed · rate)`` (``k`` in 04 §6.4; 07 I-4 for jitter's
    12). The small epsilon keeps a sample taken exactly at a step boundary on its new step
    despite float error, so the changes stay on the multiples of ``1/rate``."""
    return math.floor(elapsed * rate + _INDEX_EPSILON)


# --- Tear ---------------------------------------------------------------------------------

class TearBand(NamedTuple):
    """One sliding band in canvas units: rows ``[y, y + h)``, shifted ``dx`` (sign = way)."""

    y: int
    h: int
    dx: float


def _free_starts(placed: list[tuple[int, int]], h: int, height: int) -> list[tuple[int, int]]:
    """The ranges ``[a, b]`` of tops ``y`` where a band of ``h`` rows overlaps none of
    ``placed`` (sorted ``(y, h)``) inside ``[0, height)``."""
    ranges: list[tuple[int, int]] = []
    start = 0
    for y, bh in placed + [(height, 0)]:
        last = y - h
        if last >= start:
            ranges.append((start, last))
        start = max(start, y + bh)
    return ranges


def tear_bands(seed: int, k: int, shift: float) -> tuple[TearBand, ...]:
    """The bands of tear look step ``k`` (04 §6.6, PR-F28-05), sorted by ``y``.

    ``n`` in [2, 6] bands are drawn, each ``h`` in [8, 80] units; drawing stops before the
    total passes 40% of the canvas height. Each band's top is drawn uniformly among the tops
    in ``[0, height − h]`` that overlap no band already placed (no position: skipped; the
    first two always fit). ``dx`` is ``±(¼ + ¾u)·shift``, never 0. ``shift ≤ 0`` gives no
    bands (``with glitch`` at p = 0 and 1)."""
    if shift <= 0:
        return ()
    height = CANVAS_SIZE[1]
    r = _Stream(seed, k)
    placed: list[tuple[int, int]] = []
    bands: list[TearBand] = []
    total = 0
    for _ in range(r.between(*TEAR_BANDS)):
        h = r.between(*TEAR_BAND_HEIGHT)
        if total + h > TEAR_MAX_TOTAL:
            break
        ranges = _free_starts(placed, h, height)
        count = sum(b - a + 1 for a, b in ranges)
        if count == 0:
            continue
        pick = r.below(count)
        for a, b in ranges:
            if pick <= b - a:
                y = a + pick
                break
            pick -= b - a + 1
        size = shift * (0.25 + 0.75 * r.unit())
        dx = size if r.below(2) else -size
        total += h
        placed.append((y, h))
        placed.sort()
        bands.append(TearBand(y, h, dx))
    return tuple(sorted(bands))


def tear_px(dx: float, scale_x: float) -> int:
    """A band's shift in device pixels: ``±floor(|dx|·sx + 0.5)`` (the same on both sides)."""
    px = math.floor(abs(dx) * scale_x + 0.5)
    return px if dx >= 0 else -px


def band_rows(band: TearBand, scale_y: float, rows: int) -> tuple[int, int]:
    """A band's device rows ``[top, bottom)`` as ``Canvas.rect_to_px`` rounds them, clipped
    to ``rows``."""
    top = min(rows, math.floor(band.y * scale_y + 0.5))
    bottom = min(rows, math.floor((band.y + band.h) * scale_y + 0.5))
    return top, bottom


def draw_tear(surface: pygame.Surface, bands: tuple[TearBand, ...], scale_x: float,
              scale_y: float) -> None:
    """Roll each band's device rows of ``surface`` (the stage viewport) right by
    ``tear_px(dx)`` with wrap, in place (04 §6.6). Each row keeps its pixel multiset; rows
    outside the bands and pixels outside ``surface`` are never written (UI-F28-02)."""
    width, rows = surface.get_size()
    if width == 0:
        return
    for band in bands:
        top, bottom = band_rows(band, scale_y, rows)
        shift = tear_px(band.dx, scale_x) % width
        if bottom <= top or shift == 0:
            continue
        surface.subsurface((0, top, width, bottom - top)).scroll(shift, 0,
                                                                  pygame.SCROLL_REPEAT)


# --- Jitter -------------------------------------------------------------------------------

def jitter_offset(seed: int, k: int, a: int) -> tuple[int, int]:
    """Jitter step ``k``'s offset in canvas units: ``dx``, ``dy`` uniform integers in
    ``[−a, a]``, never both 0 (04 §6.6, PR-F28-08). ``a ≥ 1``."""
    r = _Stream(seed, k)
    for _ in range(64):
        dx, dy = r.between(-a, a), r.between(-a, a)
        if dx or dy:
            return dx, dy
    return a, 0                                  # unreachable in practice (p < 10⁻⁷⁰)


# --- Static -------------------------------------------------------------------------------

def noise_offset(seed: int, k: int) -> tuple[int, int]:
    """Static step ``k``'s wrap offset into the noise field, in cells (``[0, 640) ×
    [0, 360)``)."""
    r = _Stream(seed, k)
    return r.below(NOISE_CELLS[0]), r.below(NOISE_CELLS[1])


def _half_up(value: float) -> int:
    return math.floor(value + 0.5)


def static_multiplier(strength: float) -> int:
    """The MULT gray of a static frame: ``round(255·(1 − s))``."""
    return _half_up(255 * (1.0 - strength))


def static_add(value: int, strength: float) -> int:
    """The ADD gray of a field byte at strength ``s``: ``round(value · s)``."""
    return _half_up(value * strength)


class Noise:
    """The static's noise (04 §6.6, §6.7): ``field()`` is ``NOISE_CELLS`` bytes from
    ``Random(seed).randbytes``; ``n8`` is it scaled (nearest) to the viewport as an 8-bit
    palette surface; ``n32`` is ``n8`` in the target's format at the last strength, rebuilt
    only when the strength or the size changes. ``release()`` frees both buffers."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._field: bytes | None = None
        self.n8: pygame.Surface | None = None
        self.n32: pygame.Surface | None = None
        self._strength: float | None = None

    def field(self) -> bytes:
        if self._field is None:
            self._field = Random(self.seed).randbytes(NOISE_CELLS[0] * NOISE_CELLS[1])
        return self._field

    def prepare(self, target: pygame.Surface) -> None:
        """Build ``n8`` and ``n32`` for ``target``'s size and format (a no-op when built)."""
        size = target.get_size()
        if self.n8 is not None and self.n8.get_size() == size and self.n32 is not None:
            return
        self.release()
        small = pygame.image.frombytes(self.field(), NOISE_CELLS, "P")
        self.n8 = pygame.transform.scale(small, size)
        self.n32 = pygame.Surface(size, 0, target)

    def _paint(self, strength: float) -> None:
        assert self.n8 is not None and self.n32 is not None
        self.n8.set_palette([(g, g, g) for g in (static_add(i, strength) for i in range(256))])
        self.n32.blit(self.n8, (0, 0))
        self._strength = strength

    def draw(self, surface: pygame.Surface, strength: float, offset: tuple[int, int]) -> None:
        """Multiply ``surface`` by ``static_multiplier(s)``, then add ``n32`` wrapped at
        ``offset`` (cells), in at most 4 pieces. Nothing at ``s ≤ 0``."""
        if strength <= 0:
            return
        self.prepare(surface)
        assert self.n32 is not None
        if strength != self._strength:
            self._paint(strength)
        width, height = surface.get_size()
        gray = static_multiplier(strength)
        surface.fill((gray, gray, gray), special_flags=pygame.BLEND_RGB_MULT)
        ox = (offset[0] % NOISE_CELLS[0]) * width // NOISE_CELLS[0]
        oy = (offset[1] % NOISE_CELLS[1]) * height // NOISE_CELLS[1]
        for x in ((-ox, width - ox) if ox else (0,)):
            for y in ((-oy, height - oy) if oy else (0,)):
                surface.blit(self.n32, (x, y), special_flags=pygame.BLEND_RGB_ADD)

    def release(self) -> None:
        self.n8 = self.n32 = None
        self._strength = None


# --- Colorshift ---------------------------------------------------------------------------

def colorshift_px(units: float, width: int) -> int:
    """The channel offset ``d`` in device px for a picture ``width`` px wide (the stage
    viewport): ``max(1, round(units · width / canvas width))`` (04 §6.5)."""
    return max(1, _half_up(units * width / CANVAS_SIZE[0]))


class _Output:
    __slots__ = ("key", "surface", "row")

    def __init__(self, key: tuple, surface: pygame.Surface) -> None:
        self.key = key
        self.surface = surface
        self.row = 0                             # rows built so far


class ColorShift:
    """The colorshift picture filter (04 §4.3 ``PictureFilter``, §6.5, PR-F28-06).

    ``units`` is ``C[size]``; ``weight`` is 0–1 (the reduced fade; 1 = filtered only) and
    ``target`` the weight that fade heads to (0 or 1), which a transition uses (04 §6.5).
    ``filtered(picture, key, step=…)`` returns the filtered copy of ``picture`` for the
    composite ``key`` when it is complete. While it is building it returns the newest complete
    output of the same size (stale, 07 I-8), or None; ``step`` builds one band first.
    ``ready`` is the complete output of ``key`` only (no step); ``newest`` the newest complete
    output of any size. ``complete`` builds the whole output now (a load or colorshift's
    first frame, 07 I-8). At most ``COLORSHIFT_OUTPUTS`` outputs and one band buffer are
    held; ``release()`` frees them. ``picture`` is an opaque surface (a stage composite).

    A build that raises ``pygame.error`` or ``MemoryError`` (07 I-17) marks the filter
    ``broken``, frees its buffers, and calls ``on_failed`` (``GlitchLayer``'s W183); a broken
    filter returns None from then on, so the stage draws unfiltered."""

    def __init__(self, units: float, *, weight: float = 1.0, target: float = 1.0,
                 on_failed: "Callable[[BaseException], None] | None" = None) -> None:
        self.units = units
        self.weight = weight
        self.target = target
        self.on_failed = on_failed
        self.broken = False
        self._outputs: list[_Output] = []
        self._done: _Output | None = None        # the newest complete output
        self._band: pygame.Surface | None = None  # T: width × 270 rows

    @property
    def buffers(self) -> int:
        """Surfaces held (outputs and the band buffer), for the allocation counter."""
        return len(self._outputs) + (self._band is not None)

    def _full_key(self, picture: pygame.Surface, key: tuple) -> tuple:
        return (key, colorshift_px(self.units, picture.get_width()), picture.get_size())

    def _output(self, picture: pygame.Surface, key: tuple) -> _Output:
        full = self._full_key(picture, key)
        for out in self._outputs:
            if out.key == full:
                return out
        size = picture.get_size()
        if len(self._outputs) < COLORSHIFT_OUTPUTS:
            out = _Output(full, pygame.Surface(size, 0, picture))
            self._outputs.append(out)
        else:
            out = next(o for o in self._outputs if o is not self._done)
            if out.surface.get_size() != size:
                out.surface = pygame.Surface(size, 0, picture)
            out.key, out.row = full, 0
        return out

    def _build_band(self, picture: pygame.Surface, out: _Output) -> None:
        """Rows ``[row, row + 270)`` of ``out``: 8 ``BLEND_RGB_*`` operations (04 §6.5)."""
        width, height = picture.get_size()
        band = self._band
        if band is None or band.get_width() != width:
            band = self._band = pygame.Surface((width, COLORSHIFT_BAND_ROWS), 0, picture)
        y = out.row
        rows = min(COLORSHIFT_BAND_ROWS, height - y)
        d = out.key[1]
        area = pygame.Rect(0, y, width, rows)
        whole = pygame.Rect(0, 0, width, rows)
        x = out.surface
        x.blit(picture, (0, y), area)                                   # green in place
        x.fill((0, 255, 0), area, pygame.BLEND_RGB_MULT)
        band.fill((255, 0, 0), whole)                                   # red from x + d
        band.blit(picture, (-d, 0), area, pygame.BLEND_RGB_MULT)
        band.fill((0, 0, 0), (max(0, width - d), 0, min(d, width), rows))
        x.blit(band, (0, y), whole, pygame.BLEND_RGB_ADD)
        band.fill((0, 0, 255), whole)                                   # blue from x − d
        band.blit(picture, (d, 0), area, pygame.BLEND_RGB_MULT)
        band.fill((0, 0, 0), (0, 0, min(d, width), rows))
        x.blit(band, (0, y), whole, pygame.BLEND_RGB_ADD)
        out.row = y + rows

    def filtered(self, picture: pygame.Surface, key: tuple, *,
                 step: bool) -> pygame.Surface | None:
        if self.broken:
            return None
        try:
            out = self._output(picture, key)
            height = picture.get_height()
            if step and out.row < height:
                self._build_band(picture, out)
        except (pygame.error, MemoryError) as exc:
            self._fail(exc)
            return None
        if out.row >= height:
            self._done = out
            return out.surface
        done = self._done
        if done is not None and done is not out and done.surface.get_size() == picture.get_size():
            return done.surface
        return None

    def ready(self, picture: pygame.Surface, key: tuple) -> pygame.Surface | None:
        """The complete output of ``key`` for ``picture``, or None (nothing is built)."""
        full = self._full_key(picture, key)
        for out in self._outputs:
            if out.key == full and out.row >= picture.get_height():
                return out.surface
        return None

    def newest(self) -> pygame.Surface | None:
        """The newest complete output, of any size (a resize's stand-in, 07 I-8)."""
        done = self._done
        return None if done is None else done.surface

    def complete(self, picture: pygame.Surface, key: tuple) -> pygame.Surface | None:
        if self.broken:
            return None
        try:
            out = self._output(picture, key)
            while out.row < picture.get_height():
                self._build_band(picture, out)
        except (pygame.error, MemoryError) as exc:
            self._fail(exc)
            return None
        self._done = out
        return out.surface

    def _fail(self, exc: BaseException) -> None:
        self.broken = True
        self.release()
        if self.on_failed is not None:
            self.on_failed(exc)

    def release(self) -> None:
        self._outputs.clear()
        self._done = None
        self._band = None


# --- The layer (04 §6.4; 07 I-5 to I-7) ------------------------------------------------------

TEAR, COLORSHIFT, STATIC, JITTER = "tear", "colorshift", "static", "jitter"
MOTION_KINDS: Final = frozenset((TEAR, JITTER))         # not drawn under reduced effects
COUNTED_LASTING: Final = (STATIC, COLORSHIFT)           # lasting changes the limit counts
REDUCED_FADE_S: Final = 0.3                             # the reduced envelope, in and out
REDUCED_STATIC_SIZE: Final = "small"
_TEAR_KEY: Final = (TEAR, None)
_COLORSHIFT_KEY: Final = (COLORSHIFT, None)
_STATIC_KEY: Final = (STATIC, None)
_EPSILON: Final = 1e-9

_log = get_logger("stage")


class _Burst:
    __slots__ = ("size", "seconds", "start", "sid")

    def __init__(self, size: str, seconds: float, sid: str) -> None:
        self.size = size
        self.seconds = seconds
        self.start: float | None = None          # None: starts at the next tick
        self.sid = sid


class _Look:
    """One ``(kind, tag)``'s glitch: ``lasting`` (a size or None) and ``burst`` (or None);
    ``t0`` and ``seed`` belong to what shows now (``t0`` None: it starts at the next tick,
    so the frame it arrives in shows t = 0); ``shown_at``/``gone_at`` drive the reduced
    envelope (``shown_at`` None: set at that tick). ``_k``/``_pick`` memoize the last step's
    bands or offset."""

    __slots__ = ("kind", "tag", "lasting", "burst", "t0", "seed", "shown_at", "gone_at",
                 "_k", "_pick")

    def __init__(self, kind: str, tag: str | None, seed: int) -> None:
        self.kind = kind
        self.tag = tag
        self.lasting: str | None = None
        self.burst: _Burst | None = None
        self.t0: float | None = None
        self.seed = seed
        self.shown_at: float | None = None
        self.gone_at: float | None = None
        self._k = -1
        self._pick: object = None

    @property
    def visible(self) -> bool:
        return self.lasting is not None or self.burst is not None

    @property
    def size(self) -> str:
        burst = self.burst
        if burst is not None:
            return burst.size
        assert self.lasting is not None
        return self.lasting

    def restart(self, seed: int, now: float | None) -> None:
        """A new look from ``now`` (a start or a burst-to-lasting hand-off, 07 I-6)."""
        self.seed = seed
        self.t0 = now
        self._k = -1

    def elapsed(self, now: float) -> float:
        burst, t0 = self.burst, self.t0
        if t0 is None or (burst is not None and burst.start is None):
            return 0.0                           # arrived, not ticked yet: t = 0
        return max(0.0, now - t0)


class GlitchLayer:
    """Tear, static, and jitter on screen, and the glitch looks' clocks (module docstring).
    ``seconds`` and ``size`` are ``[effects] glitch`` and ``glitch_size`` (a command's
    None); ``refusals`` is the ``EffectLayer``'s (W61 and W182 share its statements);
    ``seed`` is presentation entropy (``install_stage``: ``time.monotonic_ns()``)."""

    def __init__(self, *, seconds: float = 0.5, size: str = "medium",
                 refusals: RefusalLog | None = None, seed: int = 0) -> None:
        self.seconds = float(seconds)
        self.size = size if size in T else "medium"
        self.refusals = refusals if refusals is not None else RefusalLog()
        self.seed = seed
        self.noise = Noise(seed & _MASK64)
        self._shift: ColorShift | None = None    # the filter while colorshift is in effect
        self.broken: set[str] = set()            # kinds that failed to draw (W183)
        self._looks: dict[tuple[str, str | None], _Look] = {}
        self._shown: GlitchState = EMPTY_GLITCH  # the lasting set the looks show
        self._target: "tuple[GlitchState, FlashLimiter] | None" = None   # refused, waiting
        self._starts = 0
        self._now = 0.0

    # -- commands --

    def apply(self, cmd: "Glitch", now: float, *, reduce: bool,
              limiter: FlashLimiter) -> None:
        """The ``Glitch`` handler's work (04 §6.4 ``apply``; 07 I-5): stops, then the bursts
        and the lasting set, counted once for the whole command."""
        self._now = now
        if cmd.restored:                         # a load or landing: at once, no envelope
            self._target = None
            self._set_lasting(cmd.lasting, now, restored=True)
            return
        for kind, tag in cmd.stops:              # ("jitter", None): every jitter
            for look in self._looks.values():
                if look.burst is not None and look.kind == kind \
                        and (tag is None or look.tag == tag):
                    self._end_burst(look, now)
        counted = False
        starts: list[tuple["GlitchBurst", bool]] = []
        for burst in cmd.bursts:
            if burst.kind in self.broken or (reduce and burst.kind in MOTION_KINDS):
                continue                         # never drawn: never counted
            seconds = burst.seconds if burst.seconds is not None else self.seconds
            count = burst.kind != JITTER and seconds < FADE_COUNTS_UNDER_S - _EPSILON
            counted = counted or count
            starts.append((burst, count))
        lasting_counts = self._counts(cmd.lasting)
        admitted = True
        if counted or lasting_counts:
            admitted = limiter.admit(now, reduced=reduce)
        for burst, count in starts:
            if count and not admitted:
                if not reduce:                   # reduced mode's own rule logs nothing
                    self.refusals.refused(burst.sid, glitch_refused_text(), code="W182")
                continue
            self._start_burst(burst)
        if admitted or not lasting_counts:
            self._target = None
            self._set_lasting(cmd.lasting, now)
        else:
            self._target = (cmd.lasting, limiter)

    def stage_shown(self, stage: "StageState") -> None:
        """A ``ShowStage``: the jitter of a sprite that left goes (its burst too)."""
        if not any(look.kind == JITTER for look in self._looks.values()):
            return
        tags = {sprite.tag for sprite in stage.sprites}
        gone = [key for key, look in self._looks.items()
                if look.kind == JITTER and look.tag not in tags]
        for key in gone:
            del self._looks[key]

    def tick(self, now: float, *, reduce: bool) -> None:
        """Once per running frame, after the effects: a waiting lasting set is tried again;
        bursts that arrived start now, finished ones end (a lasting look under one starts
        again); looks gone (and faded, when reduced) are dropped and unused buffers freed."""
        # A waiting lasting set is admitted at the time a handler would have run (the last
        # tick's), so it shows in this frame as a command's change shows in the next one:
        # the limit then holds for shown frames too (07 I-13, AC-F28-17).
        before, self._now = self._now, now
        target = self._target
        if target is not None:
            lasting, limiter = target
            if not self._counts(lasting) or limiter.admit(before, reduced=reduce):
                self._target = None
                self._set_lasting(lasting, now)
        looks = self._looks
        dropped = False
        for look in looks.values():
            burst = look.burst
            if burst is not None:
                if burst.start is None:
                    burst.start = now
                    look.restart(self._next_seed(), now)
                elif now - burst.start >= burst.seconds - _EPSILON:
                    self._end_burst(look, now)
            if look.t0 is None:
                look.t0 = now                    # a lasting look that arrived: t = 0 now
            if look.shown_at is None and look.visible:
                look.shown_at = now              # a new look: the reduced fade starts here
            dropped = dropped or not self._keeps(look, now, reduce)
        if dropped:
            for key in [key for key, look in looks.items()
                        if not self._keeps(look, now, reduce)]:
                del looks[key]
        if _STATIC_KEY not in looks and self.noise.n8 is not None:
            self.noise.release()
        if _COLORSHIFT_KEY not in looks and self._shift is not None:
            self._shift.release()                # only here: clear() + restored keeps it (I-8)
            self._shift = None

    @staticmethod
    def _keeps(look: _Look, now: float, reduce: bool) -> bool:
        """Shown, or (reduced) a static or colorshift still fading out."""
        if look.visible:
            return True
        gone = look.gone_at
        return (reduce and look.kind in COUNTED_LASTING and gone is not None
                and now - gone < REDUCED_FADE_S - _EPSILON)

    def drop_bursts(self) -> None:
        """No burst from the next frame (F15 skip; F16 when reduce turns on); lasting looks
        stay, and one under a dropped burst starts again."""
        now = self._now
        dropped = False
        for look in self._looks.values():
            if look.burst is not None:
                look.burst = None
                if look.lasting is not None:
                    look.restart(self._next_seed(), now)
                else:
                    dropped = True
        if dropped:
            for key in [key for key, look in self._looks.items() if not look.visible]:
                del self._looks[key]

    def clear(self) -> None:
        """No glitch at all (a restored stage, ``on_enter``, ``StageScreen.clear``); a
        waiting lasting set is dropped. Buffers go at the next tick."""
        self._looks.clear()
        self._shown = EMPTY_GLITCH
        self._target = None

    @property
    def active(self) -> bool:
        return bool(self._looks)

    def filter(self, reduce: bool) -> "ColorShift | None":
        """The colorshift picture filter while colorshift is in effect (04 §6.5), else None:
        one ``ColorShift`` (kept with its outputs until ``tick`` finds no colorshift look),
        offset ``C[size]``; weight 1, or under reduce the 0.3 s envelope (a look fading out
        has target 0). ``StageScreen`` hands it to ``StageView.set_filter``."""
        look = self._looks.get(_COLORSHIFT_KEY)
        if look is None or COLORSHIFT in self.broken or not (look.visible or reduce):
            return None
        shift = self._shift
        if shift is None:
            shift = self._shift = ColorShift(C[look.size] if look.visible else C[self.size],
                                             on_failed=self._filter_failed)
        if look.visible:
            shift.units = C[look.size]
        shift.target = 1.0 if look.visible else 0.0
        shift.weight = self._weight(look, self._now) if reduce else 1.0
        return shift

    def _filter_failed(self, exc: BaseException) -> None:
        self._failed(COLORSHIFT, exc)

    # -- drawing --

    def draw(self, canvas: "Canvas", view: "StageView", now: float,
             offset_px: tuple[int, int], *, reduce: bool) -> None:
        """Jitter copies, then tear, then static, over ``canvas.surface`` (the stage
        viewport, already holding the stage at the shake's ``offset_px``). Nothing on a FAST
        settle frame (07 I-7)."""
        looks = self._looks
        if not looks or canvas.quality is RenderQuality.FAST:
            return
        surface = canvas.surface
        assert surface is not None, "Canvas.bind() has not been called"
        broken = self.broken
        if not reduce and JITTER not in broken:
            try:
                for look in looks.values():
                    if look.kind == JITTER and look.visible:
                        dx, dy = self._jitter(look, now)
                        ox, oy = canvas.px(dx, dy)
                        view.draw_sprite_copy(surface, look.tag,      # type: ignore[arg-type]
                                              (offset_px[0] + ox, offset_px[1] + oy))
            except (pygame.error, MemoryError) as exc:
                self._failed(JITTER, exc)
        tear = looks.get(_TEAR_KEY)
        if tear is not None and tear.visible and not reduce and TEAR not in broken:
            try:
                draw_tear(surface, self._bands(tear, now), canvas.scale_x, canvas.scale_y)
            except (pygame.error, MemoryError) as exc:
                self._failed(TEAR, exc)
        static = looks.get(_STATIC_KEY)
        if static is not None and STATIC not in broken:
            if reduce:
                strength = S[REDUCED_STATIC_SIZE] * self._weight(static, now)
                k = 0                            # one still frame
            elif static.visible:
                strength = S[static.size]
                k = look_index(static.elapsed(now), STATIC_RATE)
            else:
                return
            try:
                self.noise.draw(surface, strength, self._noise_offset(static, k))
            except (pygame.error, MemoryError) as exc:
                self._failed(STATIC, exc)

    # -- inside --

    def _next_seed(self) -> int:
        self._starts += 1
        return mix64(self.seed, self._starts)

    def _resolve(self, size: str | None) -> str:
        return size if size is not None and size in T else self.size

    def _counts(self, lasting: GlitchState) -> bool:
        """Whether showing ``lasting`` starts, ends, or resizes a lasting static or
        colorshift (07 I-5); a kind that is off for the run (W183) never counts."""
        if lasting == self._shown:
            return False
        for kind in COUNTED_LASTING:
            if kind in self.broken:
                continue
            if self._lasting_size(lasting, kind) != self._lasting_size(self._shown, kind):
                return True
        return False

    def _lasting_size(self, lasting: GlitchState, kind: str) -> str | None:
        for entry in lasting.on:
            if entry.kind == kind:
                return self._resolve(entry.size)
        return None

    def _start_burst(self, burst: "GlitchBurst") -> None:
        key = (burst.kind, burst.tag)
        look = self._looks.get(key)
        if look is None:
            look = self._looks[key] = _Look(burst.kind, burst.tag, 0)
        elif not look.visible:                   # fading out: a new look at the tick
            look.shown_at = look.gone_at = None
        seconds = burst.seconds if burst.seconds is not None else self.seconds
        look.burst = _Burst(self._resolve(burst.size), float(seconds), burst.sid)

    def _end_burst(self, look: _Look, now: float) -> None:
        look.burst = None
        if look.lasting is not None:
            look.restart(self._next_seed(), now)     # back to the lasting look (07 I-6)
        else:
            look.gone_at = now

    def _set_lasting(self, lasting: GlitchState, now: float, *, restored: bool = False) -> None:
        """The looks' lasting sizes become ``lasting``'s: a new one starts at the next tick
        (restored: with no envelope), one that went off fades (reduced) or goes."""
        want = {(entry.kind, entry.tag): self._resolve(entry.size) for entry in lasting.on}
        for key, look in self._looks.items():
            if look.lasting is not None and key not in want:
                look.lasting = None
                if look.burst is None:
                    look.gone_at = now
        for key, size in want.items():
            look = self._looks.get(key)
            if look is None:
                look = self._looks[key] = _Look(key[0], key[1], self._next_seed())
            elif not look.visible:               # fading out: on again from the next tick
                look.restart(self._next_seed(), None)
                look.gone_at = look.shown_at = None
            look.lasting = size
            if restored:
                look.shown_at = -math.inf
        self._shown = lasting

    def _weight(self, look: _Look, now: float) -> float:
        """The reduced envelope (04 §6.4): in over 0.3 s from ``shown_at``, out over 0.3 s
        from ``gone_at``."""
        if not look.visible:
            gone = look.gone_at if look.gone_at is not None else now
            return ease_in_out(1.0 - (now - gone) / REDUCED_FADE_S)
        shown = look.shown_at
        return 0.0 if shown is None else ease_in_out((now - shown) / REDUCED_FADE_S)

    @staticmethod
    def _jitter(look: _Look, now: float) -> tuple[int, int]:
        k = look_index(look.elapsed(now), JITTER_RATE)
        if k != look._k:
            look._k, look._pick = k, jitter_offset(look.seed, k, J[look.size])
        return look._pick                                       # type: ignore[return-value]

    @staticmethod
    def _bands(look: _Look, now: float) -> tuple[TearBand, ...]:
        k = look_index(look.elapsed(now), TEAR_RATE)
        if k != look._k:
            look._k, look._pick = k, tear_bands(look.seed, k, T[look.size])
        return look._pick                                       # type: ignore[return-value]

    @staticmethod
    def _noise_offset(look: _Look, k: int) -> tuple[int, int]:
        if k != look._k:
            look._k, look._pick = k, noise_offset(look.seed, k)
        return look._pick                                       # type: ignore[return-value]

    def _failed(self, kind: str, exc: BaseException) -> None:
        """W183 (PR-F28-16): ``kind`` is off for the rest of the run; logged once."""
        if kind in self.broken:
            return
        self.broken.add(kind)
        if kind == STATIC:
            self.noise.release()
        elif kind == COLORSHIFT and self._shift is not None:
            self._shift.release()
            self._shift = None
        _log.warning("%s", glitch_failed_text(kind, type(exc).__name__),
                     extra={"code": "W183"})


# --- ``with glitch`` (04 §6.6 ``GlitchKind``; PR-F28-18) -------------------------------------

GLITCH_TRANSITION_SHIFT: Final = T["large"]      # the tear's peak shift, units (at p = 0.5)


class GlitchKind:
    """``KINDS["glitch"]``: the old picture for p < 0.5, the new one from p = 0.5, torn with
    a shift ``96·(1 − |1 − 2p|)`` units by the bands of ``tear_bands(crc32(sid), k, …)``,
    ``k = floor(p·seconds·10)`` (new bands every 100 ms of the run, ``KindFrame.seconds``).
    The view draws p = 0 and p = 1 (the plain, or filtered, new picture); reduced effects play
    it as a dissolve (``calm=False``). Nothing to prepare: the tear rolls rows in place."""

    def __init__(self, frame: "KindFrame") -> None:
        self.frame = frame
        sid = frame.spec.sid if frame.spec is not None else ""
        self.seed = zlib.crc32(sid.encode("utf-8"))

    def prepare_step(self) -> bool:
        return True

    def draw(self, target: pygame.Surface, p: float, offset: tuple[int, int]) -> None:
        frame = self.frame
        target.blit(frame.old if p < 0.5 else frame.new, offset)
        shift = GLITCH_TRANSITION_SHIFT * (1.0 - abs(1.0 - 2.0 * p))
        bands = tear_bands(self.seed, look_index(p * frame.seconds, TEAR_RATE), shift)
        width, height = target.get_size()
        draw_tear(target, bands, width / CANVAS_SIZE[0], height / CANVAS_SIZE[1])


__all__ = ["C", "COLORSHIFT_BAND_ROWS", "COLORSHIFT_OUTPUTS", "ColorShift",
           "GLITCH_TRANSITION_SHIFT", "GlitchKind", "GlitchLayer", "J", "JITTER_RATE",
           "NOISE_CELLS", "NOISE_GRAIN", "Noise", "S", "STATIC_RATE", "T", "TEAR_BANDS",
           "TEAR_BAND_HEIGHT", "TEAR_MAX_TOTAL", "TEAR_RATE", "TearBand", "band_rows",
           "colorshift_px", "draw_tear", "jitter_offset", "look_index", "mix64", "noise_offset",
           "static_add", "static_multiplier", "tear_bands", "tear_px"]
