"""Volume levels (F08 ``04-technical.md`` §7.8; ``07`` I-10; PR-F08-08, 09).

Why this module exists: every sound's level is one formula, so the music, effects, voice,
and UI sounds all agree and a settings change applies the same way everywhere. A level is
``amp(master, channel, relative) = c(master) · c(channel) · c(relative)`` with
``c(v) = (v / 100)²``, which sounds even to the ear (PR-F08-09). SDL_mixer keeps a volume in
1/128 steps (``int(v × 128)``), so ``quantize`` rounds to the nearest step and never turns a
non-zero level into silence (I-10: master 20 with sound 40 is 0.0064, under one step).

Pure: no pygame, clock, or state.
"""

from dataclasses import dataclass
from typing import Final

VOLUME_STEPS: Final = 128                 # SDL_mixer's MIX_MAX_VOLUME


def curve(volume: int) -> float:
    """``(volume / 100)²`` for a 0–100 percentage, computed exactly for whole numbers
    (``curve(70) == 0.49``)."""
    return (volume * volume) / 10_000


def amp(master: int, channel: int, relative: int) -> float:
    """The amplitude of a sound: the master volume, its channel's volume (music, sound,
    or voice), and the volume written in the script (or a seam's ``volume``)."""
    return curve(master) * curve(channel) * curve(relative)


def quantize(level: float) -> float:
    """``level`` rounded to SDL's nearest 1/128 step, in 0.0–1.0; any level above 0 gives
    at least 1/128 (I-10)."""
    if level <= 0.0:
        return 0.0
    steps = min(VOLUME_STEPS, max(1, round(level * VOLUME_STEPS)))
    return steps / VOLUME_STEPS


@dataclass(frozen=True, slots=True)
class Volumes:
    """The four volume settings, 0–100 (``[audio]`` defaults; F16's settings win)."""

    master: int = 100
    music: int = 70
    sound: int = 80
    voice: int = 100

    def sound_gain(self) -> float:
        """``c(master) · c(sound)``: an effect's level before its own volume and ramp."""
        return curve(self.master) * curve(self.sound)

    def voice_gain(self) -> float:
        """``c(master) · c(voice)``: a voice line's level (a voice has no relative volume,
        so it is ``amp(master, voice, 100)``)."""
        return curve(self.master) * curve(self.voice)


__all__ = ["VOLUME_STEPS", "Volumes", "amp", "curve", "quantize"]
