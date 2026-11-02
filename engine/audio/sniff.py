"""Content sniffing before any decode (F08 ``04-technical.md`` §7.4 steps 3–4, §8 items 3, 5;
TR-F08-04; AC-F08-35, 36, 37).

The code lives in ``engine/core/audiosniff.py`` (F45 ``04`` Q5: Studio, which may not import
``audio``, checks added files with it). This module re-exports the same objects, so
``Sniffed`` is one class and ``MixerBackend.decode``'s type barrier holds.
"""

from engine.core.audiosniff import (FORMAT_NAMES, Sniffed, declared_seconds, matches,
                                    ogg_last_granule, refused_signature, sniff)

__all__ = ["FORMAT_NAMES", "Sniffed", "declared_seconds", "matches", "ogg_last_granule",
           "refused_signature", "sniff"]
