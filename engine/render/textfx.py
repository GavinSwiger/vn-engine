"""Text-effect poses: the pure numbers behind ``{shake}``, ``{wave}``, and ``{glitch}`` (F29
``04-technical.md`` §4, §7.1, §7.3; ``07-architecture-review.md`` I-2, I-3, I-4).

Why this module exists: a pose must be a fixed function of (grapheme index, effect time, the
line's seed), the same on every run, process, and platform, so a reloaded or rolled-back line
replays the same frames and the story RNG is never read (invariant 7). Every number here is a
32-bit integer hash of Python ints (``mix32``) plus ``math.sin``; never ``random`` and never
``hash()``, which is salted for strings.

- ``mix32``, ``h``, ``u``, ``v``: the hash (04 §7.1). Salts: shake 1, glitch phase 2, glitch
  pick 3; ``salt << 20 | seed``, so a seed is at most 20 bits. ``index_key(i)`` is ``h``'s
  first round, kept per glyph by the draw lists.
- ``line_seed(sid)``: a line's seed (07 I-3), ``mix32`` folded over the sid's UTF-8 bytes from
  ``SEED_START``, masked to 20 bits. ADV uses it as is; an NVL row uses ``line_seed(sid) ^
  row``. Computed once per ``show``, never per frame.
- ``amplitude``, ``shake_unit``, ``wave_unit``, ``glitch_pick``: the pose parts (04 §7.3).
- ``still_minimum``: reduce motion's floor for one glitch run (07 I-4): if no glyph of the run
  shows a symbol at step 0, the one closest to switching shows one.

The draw lists (``render/textbox.py``, ``render/nvl.py``) hold the rasters; this module holds
no state. No pygame; ``TextEffect`` comes from ``runtime.commands`` for annotations only, and
only its ``kind`` and ``strength`` are read (07 I-2).
"""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Iterable    # only math, dataclasses, typing (AC-F29-08)

if TYPE_CHECKING:                                    # annotations only (07 I-2)
    from engine.runtime.commands import TextEffect

REFERENCE_SIZE: Final = 28                   # amplitudes are given at this text size
SHAKE_STEP_S: Final = 0.05                   # a new shake pose 20 times a second
WAVE_PERIOD_S: Final = 1.0
WAVE_PHASE: Final = 0.6                      # radians per grapheme index
GLITCH_STEP_S: Final = 0.12                  # a glyph changes at most once per step
AMPLITUDE: Final = {"shake": {"small": 1.0, "medium": 2.0, "large": 4.0},
                    "wave": {"small": 2.0, "medium": 3.5, "large": 6.0}}
GLITCH_P: Final = {"small": 0.10, "medium": 0.25, "large": 0.50}
SUBSTITUTES: Final = "!#$%&*+/<=>?@\\^_|~[]"   # 20, PR-F29-06 order

SHAKE: Final = 0                             # FxGlyph.kind (04 §4)
WAVE: Final = 1
GLITCH: Final = 2
KINDS: Final = {"shake": SHAKE, "wave": WAVE, "glitch": GLITCH}

SALT_SHAKE: Final = 1
SALT_GLITCH_PHASE: Final = 2
SALT_GLITCH_PICK: Final = 3
SEED_BITS: Final = 20
SEED_MASK: Final = (1 << SEED_BITS) - 1
SEED_START: Final = 0x811C9DC5               # line_seed's fold start (07 I-3)
_M: Final = 0xFFFFFFFF
_I_KEY: Final = 0x5BD1E995


@dataclass(frozen=True, slots=True)
class FxTime:
    """The effect clock as the draw pass sees it: ``t`` seconds of line time (ADV) or page
    time (NVL), and ``still`` (F16's effective reduce-motion flag, read every draw)."""

    t: float
    still: bool = False


# --- The hash (04 §7.1) ------------------------------------------------------------------------

def mix32(x: int) -> int:
    """A 32-bit integer finalizer (a bijection on 0 .. 2³² − 1); ``x`` is masked first."""
    x &= _M
    x ^= x >> 16
    x = (x * 0x7FEB352D) & _M
    x ^= x >> 15
    x = (x * 0x846CA68B) & _M
    x ^= x >> 16
    return x


def index_key(i: int) -> int:
    """``h``'s first round, ``mix32(i ^ 0x5BD1E995)``: fixed per grapheme, so a draw list
    keeps it (``render/textbox.py``'s per-frame pass inlines the other two rounds)."""
    return mix32(i ^ _I_KEY)


def h(i: int, step: int, salt: int, seed: int) -> int:
    """``mix32(mix32(mix32(i ^ 0x5BD1E995) + step) + (salt << 20 | seed))``."""
    return mix32(mix32(mix32(i ^ _I_KEY) + step) + (salt << SEED_BITS | seed))


def u(hashed: int) -> float:
    """The low 16 bits as a fraction in [0, 1)."""
    return (hashed & 0xFFFF) / 65536


def v(hashed: int) -> float:
    """The high 16 bits as a fraction in [0, 1)."""
    return (hashed >> 16) / 65536


def line_seed(sid: str) -> int:
    """A line's pose seed from its sid alone (07 I-3): ``mix32`` folded over the sid's UTF-8
    bytes (a lone surrogate passes through) from ``SEED_START``, masked to ``SEED_BITS``.
    Any string gives a value; NVL rows add ``^ row``."""
    x = SEED_START
    for byte in sid.encode("utf-8", "surrogatepass"):
        x = mix32(x ^ byte)
    return x & SEED_MASK


# --- Poses (04 §7.3) ---------------------------------------------------------------------------

def amplitude(effect: "TextEffect", size: int) -> float:
    """Shake/wave: ``AMPLITUDE[kind][strength] × size / 28`` canvas units (``size`` the
    glyph's, ``{size}`` and F16's text size included; PR-F29-07). Glitch: ``GLITCH_P``, the
    share of glyphs showing a symbol. ``KeyError`` on a value outside the fixed sets."""
    if effect.kind == "glitch":
        return GLITCH_P[effect.strength]
    return AMPLITUDE[effect.kind][effect.strength] * size / REFERENCE_SIZE


def shake_unit(index: int, t: float, seed: int) -> tuple[float, float]:
    """Grapheme ``index``'s shake offset as fractions of the amplitude, each in [−1, 1),
    constant for each ``SHAKE_STEP_S`` step."""
    hashed = h(index, math.floor(t / SHAKE_STEP_S), SALT_SHAKE, seed)
    return 2 * u(hashed) - 1, 2 * v(hashed) - 1


def wave_unit(index: int, t: float) -> float:
    """Grapheme ``index``'s lift as a fraction of the amplitude: ``sin(2π t / 1.0 + 0.6 i)``
    (unseeded, so a wave ripples along the line)."""
    return math.sin(2 * math.pi * t / WAVE_PERIOD_S + WAVE_PHASE * index)


def glitch_pick(index: int, t: float, seed: int, p: float, still: bool) -> int:
    """−1 for the real glyph, else an index into ``SUBSTITUTES``. Each glyph's steps are
    offset by its own phase, so neighbours don't change together; ``still`` freezes step 0
    (the picture at t = 0)."""
    if still:
        step = 0
    else:
        phase = GLITCH_STEP_S * u(h(index, 0, SALT_GLITCH_PHASE, seed))
        step = math.floor((t + phase) / GLITCH_STEP_S)
    hashed = h(index, step, SALT_GLITCH_PICK, seed)
    return int(v(hashed) * len(SUBSTITUTES)) if u(hashed) < p else -1


def still_minimum(run: Iterable[tuple[int, float]], seed: int) -> tuple[int, int] | None:
    """Reduce motion's floor for one glitch run (07 I-4). ``run`` is the run's drawn glyphs as
    ``(grapheme index, p)`` in draw order (a strength change inside a run doesn't break it).
    None when the run is empty or a glyph already shows a symbol at step 0; else ``(index,
    substitute)`` for the glyph with the smallest step-0 ``u`` (the one closest to switching;
    ties to the earlier glyph), which then shows ``SUBSTITUTES[substitute]``. Computed once
    per draw list, never per frame."""
    best: tuple[float, int, int] | None = None
    for index, p in run:
        hashed = h(index, 0, SALT_GLITCH_PICK, seed)
        chance = u(hashed)
        if chance < p:
            return None
        if best is None or chance < best[0]:
            best = (chance, index, int(v(hashed) * len(SUBSTITUTES)))
    return None if best is None else (best[1], best[2])


__all__ = ["AMPLITUDE", "FxTime", "GLITCH", "GLITCH_P", "GLITCH_STEP_S", "KINDS",
           "REFERENCE_SIZE", "SALT_GLITCH_PHASE", "SALT_GLITCH_PICK", "SALT_SHAKE", "SEED_BITS",
           "SEED_MASK", "SEED_START", "SHAKE", "SHAKE_STEP_S", "SUBSTITUTES", "WAVE",
           "WAVE_PERIOD_S", "WAVE_PHASE", "amplitude", "glitch_pick", "h", "index_key",
           "line_seed", "mix32", "shake_unit", "still_minimum", "u", "v", "wave_unit"]
