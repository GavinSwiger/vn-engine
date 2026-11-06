"""``install_meters``: shown meters in the status corner (F62 round 2).

Why this module exists: ``show meter`` changes ``GameState.points``'s shown list (saved,
rolled back, restored by a load), and F61's corner owns no game state. ``MeterCorner`` keeps
the corner in line with that list: a source of the corner (``StatusCorner.add_source``), so
once per frame it adds an item for a newly shown meter (fading in), removes one no longer
shown (fading out), and pulses an item whose rank changed. Values need nothing: each
``MeterItem`` reads its meter every frame.

**New game and load.** The corner keeps items across screens and the shell never clears it
(a load restores before the in-game reset runs). ``MeterCorner.reset`` is a shell in-game
reset (New Game, the way back to the title, and after a load): it drops this owner's items
at once, and the next frame refills them from the state as cuts, with no pulse, so a load
shows exactly what was saved.

How a meter looks comes from ``kits.meter_look`` (``[meter.<name>]`` > kit > defaults), read
when its item is made. While NVL is on, items take the narrow column form that fits
beside the text (``MeterItem``'s ``narrow``).
"""

from collections.abc import Hashable
from typing import TYPE_CHECKING

from engine.core.constants import CANVAS_SIZE
from engine.core.kits import meter_look
from engine.runtime.interpreter import Status
from engine.runtime.points import UnknownMeter
from engine.ui.meteritem import MeterItem, MeterReading

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.interpreter import Interpreter

CANVAS_W = CANVAS_SIZE[0]
KEY = "meter"                               # corner keys are ("meter", name)


def reading(interp: "Interpreter", name: str) -> MeterReading | None:
    """``name``'s value, range and rank now; None when it isn't a meter (a hot reload)."""
    points = interp.points
    try:
        spec = points.spec(name)
        value = points.get(name)
    except UnknownMeter:
        return None
    return MeterReading(value, spec.low if spec.ranged else None,
                        spec.high if spec.ranged else None,
                        spec.rank(value) if spec.ranks else None)


class MeterCorner:
    """The meters' side of the corner (module docstring)."""

    def __init__(self, app: "App", interp: "Interpreter") -> None:
        self.app = app
        self.interp = interp
        self._ranks: dict[str, str | None] = {}
        self._cut = True                    # the first fill and every refill are cuts

    @property
    def corner(self):
        return self.app.shell.corner

    def _narrow(self) -> float | None:
        """While NVL is on: the content width that fits beside its text column (the
        narrower side), else None."""
        nvl = getattr(getattr(self.app, "textbox", None), "nvl", None)
        if not getattr(nvl, "on", False):
            return None
        m = nvl.metrics
        style = self.corner.style
        space = min(m.left, CANVAS_W - (m.left + m.width))
        return max(0.0, space - style.margin - 2 * style.side_padding)

    def _mine(self) -> list[Hashable]:
        return [k for k in self.corner.keys()
                if isinstance(k, tuple) and len(k) == 2 and k[0] == KEY]

    def wanted(self) -> tuple[str, ...]:
        if self.interp.status is Status.IDLE:
            return ()
        return self.interp.points.shown()

    def sync(self) -> None:
        """Bring the corner in line with the shown list (module docstring)."""
        corner, cut = self.corner, self._cut
        self._cut = False
        wanted = self.wanted()
        for key in self._mine():
            if key[1] not in wanted:
                corner.remove_item(key, fade=not cut)
                self._ranks.pop(key[1], None)
        config = self.app.config
        for name in wanted:
            key = (KEY, name)
            now = reading(self.interp, name)
            rank = now.rank if now is not None else None
            if corner.item(key) is None or key not in corner.keys():
                look, place, label = meter_look(config, name)
                item = MeterItem(look, label, lambda name=name: reading(self.interp, name),
                                 narrow=self._narrow)
                corner.set_item(key, place, item, fade=not cut)
            elif not cut and name in self._ranks and self._ranks[name] != rank:
                corner.pulse(key)
            self._ranks[name] = rank

    def reset(self) -> None:
        """A shell in-game reset: drop the meters at once; the next frame refills them."""
        for key in self._mine():
            self.corner.remove_item(key, fade=False)
        self._ranks.clear()
        self._cut = True


def install_meters(app: "App", interp: "Interpreter") -> MeterCorner | None:
    """Every launch with a shell: the corner's meter source and the in-game reset."""
    shell = getattr(app, "shell", None)
    corner = getattr(shell, "corner", None)
    if corner is None:
        return None
    meters = MeterCorner(app, interp)
    corner.add_source(meters.sync)
    shell.add_in_game_reset(meters.reset)
    return meters


__all__ = ["KEY", "MeterCorner", "install_meters", "reading"]
