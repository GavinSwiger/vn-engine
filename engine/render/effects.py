"""Screen effects: the shake offset, the flash fill, and the flash limit (F09 ``04-technical.md``
§4.3, §6.7, §6.8; PR-F09-10 to 15, UI-F09-04 to 06; TR-F09-04).

Why this module exists: ``shake`` and ``flash`` are presentation timing, not story state, so
the runtime only sends ``Shake``/``Flash`` commands and ``StageScreen`` plays them here on its
effect clock. Reduced effects and the flash limit act only here, so the command sequence never
depends on them (TR-F09-01).

- **Shake** (§6.7): amplitude ``A(t) = size·(1 − t/T)``, phase ``k = floor(t/0.05)``, and a
  fixed cycle of unit vectors (``SHAKE_VECTORS``); the offset is ``round(A·u)`` canvas units,
  (0, 0) from ``t ≥ T`` and always under reduced effects. No randomness.
- **Flash** (§6.7): full strength in its first frame, then ``w = 1 − t/T``; drawn over the
  whole stage viewport as a multiply by ``1 − w`` and an add of ``c·w``. Reduced: ``w``
  rises to 0.5 over ``max(0.3, T)`` s (``ease_in_out``) and falls the same way. A new flash
  replaces the one fading (07 I-7); a refused one replaces nothing.
- **Flash limit** (§6.8): ``FlashLimiter.admit`` counts start times on the effect clock: at
  most 3 in any half-open second, 1 under reduced effects (WCAG 2.3.1). Every ``flash`` and
  every ``fade`` under 1 s is counted (F28's ``flashes`` kinds too); a click-through gives
  its fade back (``withdraw``: a player-caused cut, ui-system §5).
- **W61** (``RefusalLog``): once per statement, for at most ``W61_SIDS_MAX`` statements;
  a refusal by reduced mode's one-per-second rule logs nothing.

Pure math (``shake_offset``, ``flash_weight``), the limiter, and the log need no window.
"""

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pygame

from engine.core.constants import SHAKE_SIZES
from engine.core.logsetup import get_logger
from engine.runtime.transitions import flash_refused_text

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.runtime.commands import Flash, Shake

RGB = tuple[int, int, int]

SHAKE_STEP_S: Final = 0.05               # the shake's phase changes every 50 ms
SHAKE_VECTORS: Final = {
    None: ((0.8, 0.6), (-0.8, -0.6), (-0.6, 0.8), (0.6, -0.8)),      # both
    "horizontal": ((1.0, 0.0), (-1.0, 0.0)),
    "vertical": ((0.0, 1.0), (0.0, -1.0)),
}
FLASH_LIMIT: Final = 3                   # flashes in any half-open second (PR-F09-14)
FLASH_LIMIT_REDUCED: Final = 1           # ...under reduced effects (PR-F09-15)
FLASH_WINDOW_S: Final = 1.0
FADE_COUNTS_UNDER_S: Final = 1.0         # a fade shorter than this counts as a flash
REDUCED_FLASH_PEAK: Final = 0.5          # the reduced flash's highest weight
REDUCED_FLASH_MIN_S: Final = 0.3         # ...reached after max(this, T) seconds
W61_SIDS_MAX: Final = 1000               # statements W61 is remembered for (§7 item 3)
_EPSILON: Final = 1e-9

_log = get_logger("stage")


@dataclass(frozen=True, slots=True)
class EffectSettings:
    """``StageScreen.settings`` (F16 replaces the whole object): ``reduce`` is the effective
    "reduce motion and flashing" switch, ``[effects] reduce`` OR the player's setting
    (07 I-6). F16 calls ``StageScreen.drop_effects()`` when it turns on."""

    reduce: bool = False


def ease_in_out(t: float) -> float:
    """ui-system §5: ``(1 − cos(πt)) / 2``, clamped to 0–1."""
    t = 0.0 if t <= 0.0 else 1.0 if t >= 1.0 else t
    return (1.0 - math.cos(math.pi * t)) / 2.0


def shake_offset(size: float, direction: str | None, seconds: float,
                 t: float) -> tuple[int, int]:
    """The shake's offset in canvas units at ``t`` seconds since it started (§6.7)."""
    if t < 0.0 or t >= seconds - _EPSILON:
        return 0, 0
    amplitude = size * (1.0 - t / seconds)
    vectors = SHAKE_VECTORS.get(direction, SHAKE_VECTORS[None])
    ux, uy = vectors[math.floor(t / SHAKE_STEP_S + _EPSILON) % len(vectors)]
    return round(amplitude * ux) + 0, round(amplitude * uy) + 0     # + 0: no -0


def flash_weight(t: float, seconds: float, *, reduced: bool) -> float:
    """The flash color's weight ``w`` (0–1) at ``t`` seconds since it started (§6.7)."""
    if t < 0.0:
        return 0.0
    if not reduced:
        return 0.0 if t >= seconds - _EPSILON else 1.0 - t / seconds
    rise = max(REDUCED_FLASH_MIN_S, seconds)
    if t >= 2.0 * rise - _EPSILON:
        return 0.0
    x = t / rise if t <= rise else 2.0 - t / rise
    return REDUCED_FLASH_PEAK * ease_in_out(x)


def flash_end(seconds: float, *, reduced: bool) -> float:
    """When a flash of ``seconds`` is over."""
    return 2.0 * max(REDUCED_FLASH_MIN_S, seconds) if reduced else seconds


class FlashLimiter:
    """§6.8: the start times admitted in the last second, on the effect clock. One per
    ``StageScreen``; it keeps its history when reduce is switched (07 I-6)."""

    def __init__(self) -> None:
        self._times: deque[float] = deque()

    def admit(self, now: float, *, reduced: bool) -> bool:
        """Drop the start times ``≤ now − 1``; refuse when 3 remain (1 when ``reduced``);
        otherwise record ``now`` and admit."""
        times = self._times
        while times and times[0] <= now - FLASH_WINDOW_S:
            times.popleft()
        if len(times) >= (FLASH_LIMIT_REDUCED if reduced else FLASH_LIMIT):
            return False
        times.append(now)
        return True

    def withdraw(self, at: float) -> None:
        """Forget one admission at ``at`` (a fade the player clicked through, §6.8)."""
        try:
            self._times.remove(at)
        except ValueError:
            pass


class RefusalLog:
    """W61, once per statement (``sid``), for at most ``W61_SIDS_MAX`` statements (§6.8).
    ``locate(sid)`` is ``install_stage``'s location formatter (``ui`` and ``render`` import
    no ``script``). F28 (04 §17 item 2, 07 §2.2): ``code`` names the record's code (W182 for
    a refused glitch); W61 and W182 share the one sid set and its cap."""

    def __init__(self, locate: Callable[[str], str] | None = None) -> None:
        self.locate = locate
        self.logged: set[str] = set()

    def refused(self, sid: str, text: str, code: str = "W61") -> None:
        if sid in self.logged or len(self.logged) >= W61_SIDS_MAX:
            return
        self.logged.add(sid)
        where = self.locate(sid) if self.locate is not None else ""
        _log.warning("%s%s", where, text, extra={"code": code})


class _ShakeState:
    __slots__ = ("size", "direction", "seconds", "start")

    def __init__(self, size: float, direction: str | None, seconds: float,
                 start: float | None) -> None:
        self.size = size
        self.direction = direction
        self.seconds = seconds
        self.start = start                   # None: starts at the next tick


class _FlashState:
    __slots__ = ("color", "seconds", "reduced", "start")

    def __init__(self, color: RGB, seconds: float, reduced: bool,
                 start: float | None) -> None:
        self.color = color
        self.seconds = seconds
        self.reduced = reduced
        self.start = start


class EffectLayer:
    """The one shake and the one flash in play (each replaced by the next), with the
    ``[effects]``/``[theme.effects]`` defaults a command leaves out. Times are on
    ``StageScreen``'s effect clock; a ``pending`` effect starts at the next ``tick`` (the
    frame it arrives in shows it at t = 0)."""

    def __init__(self, *, shake_seconds: float = 0.5, shake_size: str = "medium",
                 flash_seconds: float = 0.3, flash_color: RGB = (255, 255, 255),
                 empty_color: RGB = (0, 0, 0), refusals: RefusalLog | None = None) -> None:
        self.shake_seconds = shake_seconds
        self.shake_size = shake_size
        self.flash_seconds = flash_seconds
        self.flash_color = tuple(flash_color)
        self.empty_color = tuple(empty_color)
        self.refusals = refusals if refusals is not None else RefusalLog()
        self._shake: _ShakeState | None = None
        self._flash: _FlashState | None = None

    # -- commands --

    def shake(self, cmd: "Shake", now: float, *, pending: bool = False) -> None:
        """Start ``cmd`` at ``now`` (``pending``: at the next ``tick``), replacing any shake
        in play (it restarts from its own t = 0)."""
        size = SHAKE_SIZES.get(cmd.size or self.shake_size, SHAKE_SIZES["medium"])
        seconds = cmd.seconds if cmd.seconds is not None else self.shake_seconds
        self._shake = _ShakeState(float(size), cmd.direction, float(seconds),
                                  None if pending else now)

    def flash(self, cmd: "Flash", now: float, *, reduce: bool, limiter: FlashLimiter,
              pending: bool = False) -> bool:
        """Admit ``cmd`` at ``now`` (§6.8) and, if admitted, start it then (``pending``: at
        the next ``tick``) in place of any flash in play (07 I-7). Refused: nothing is drawn
        or replaced, and W61 is logged unless reduced mode's rule refused it."""
        if not limiter.admit(now, reduced=reduce):
            if not reduce:
                self.refusals.refused(cmd.sid, flash_refused_text())
            return False
        color = _rgb(cmd.color) if cmd.color is not None else self.flash_color
        seconds = cmd.seconds if cmd.seconds is not None else self.flash_seconds
        self._flash = _FlashState(color, float(seconds), reduce, None if pending else now)
        return True

    def tick(self, now: float) -> None:
        """Effects that arrived since the last tick start now; finished ones are dropped."""
        shake, flash = self._shake, self._flash
        if shake is not None:
            if shake.start is None:
                shake.start = now
            elif now - shake.start >= shake.seconds - _EPSILON:
                self._shake = None
        if flash is not None:
            if flash.start is None:
                flash.start = now
            elif now - flash.start >= flash_end(flash.seconds,
                                                reduced=flash.reduced) - _EPSILON:
                self._flash = None

    def clear(self) -> None:
        """No shake and no flash from the next frame (restore, ``on_enter``,
        ``drop_effects``)."""
        self._shake = None
        self._flash = None

    @property
    def active(self) -> bool:
        return self._shake is not None or self._flash is not None

    # -- values --

    def offset_units(self, now: float, *, reduce: bool) -> tuple[int, int]:
        """The shake offset in canvas units; (0, 0) with none, at its end, or reduced."""
        shake = self._shake
        if shake is None or reduce:
            return 0, 0
        t = 0.0 if shake.start is None else now - shake.start
        return shake_offset(shake.size, shake.direction, shake.seconds, t)

    def flash_weight(self, now: float) -> float:
        flash = self._flash
        if flash is None:
            return 0.0
        t = 0.0 if flash.start is None else now - flash.start
        return flash_weight(t, flash.seconds, reduced=flash.reduced)

    # -- drawing --

    def draw_band(self, surface: pygame.Surface, offset_px: tuple[int, int]) -> None:
        """The strips a shaken stage uncovers, in ``stage.empty_color`` (§6.7)."""
        dx, dy = offset_px
        w, h = surface.get_size()
        if dx > 0:
            surface.fill(self.empty_color, (0, 0, dx, h))
        elif dx < 0:
            surface.fill(self.empty_color, (w + dx, 0, -dx, h))
        if dy > 0:
            surface.fill(self.empty_color, (0, 0, w, dy))
        elif dy < 0:
            surface.fill(self.empty_color, (0, h + dy, w, -dy))

    def draw_flash(self, canvas: "Canvas", now: float) -> None:
        """The flash over the whole stage viewport: multiply by ``1 − w``, add ``c·w``."""
        flash = self._flash
        if flash is None:
            return
        w = self.flash_weight(now)
        if w <= 0.0:
            return
        surface = canvas.surface
        assert surface is not None, "Canvas.bind() has not been called"
        keep = int(255 * (1.0 - w) + 0.5)
        surface.fill((keep, keep, keep), special_flags=pygame.BLEND_RGB_MULT)
        surface.fill(tuple(int(c * w + 0.5) for c in flash.color),
                     special_flags=pygame.BLEND_RGB_ADD)


def _rgb(color: str) -> RGB:
    """``#RRGGBB`` → RGB (a command's color is always this form, 04 §5.1)."""
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


__all__ = ["EffectLayer", "EffectSettings", "FADE_COUNTS_UNDER_S", "FLASH_LIMIT",
           "FLASH_LIMIT_REDUCED", "FlashLimiter", "RefusalLog", "SHAKE_VECTORS",
           "W61_SIDS_MAX", "ease_in_out", "flash_end", "flash_weight", "shake_offset"]
