"""Shared names for the "one mechanic, many skins" systems (F60 kits, F61 status corner,
F62 visible meters; plan: specs/skins-contract.md, 2026-11-06).

Why this module exists: kits (data), the status corner (engine UI) and meter looks (runtime
and Studio) are built by different hands but must agree on a few words. They live here,
in core, so every layer can import them without importing each other.

- ``CORNER_PLACES``: where a status corner item can sit, in Studio's order.
- ``DEFAULT_CORNER_PLACE``: the place used when neither the author nor the kit names one.
- ``METER_LOOKS``: how a shown meter can be drawn; ``DEFAULT_METER_LOOK`` when unset.
"""

from __future__ import annotations

from typing import Final

CORNER_PLACES: Final = ("top_left", "top_right", "bottom_left", "bottom_right")
DEFAULT_CORNER_PLACE: Final = "top_left"

METER_LOOKS: Final = ("bar", "number", "hearts", "pips", "dial")
DEFAULT_METER_LOOK: Final = "bar"

__all__ = ["CORNER_PLACES", "DEFAULT_CORNER_PLACE", "DEFAULT_METER_LOOK", "METER_LOOKS"]
