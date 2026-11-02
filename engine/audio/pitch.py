"""Blip pitch variants by resampling (F06 ``SPEC.md`` §5; ``07`` I-3, I-5; AC-F06-07).

Why this module exists: a character's blip with ``blip_pitch = p`` plays at one of five
speeds, ``1 + p·s/2`` for ``s`` in ``BLIP_STEPS``, so it doesn't sound mechanical. SDL_mixer
can't change a sound's speed, so the loader's worker builds the five variants once per file
from the decoded samples: a faster one is shorter and higher (nearest-sample resampling,
which is enough for a sound this short).

Samples are the mixer's signed 16-bit frames: 4 bytes in stereo (one ``array('i')`` item per
frame) or 2 in mono after ``set_mono`` (``'h'``); the frame size is read on the main thread
with the mixer generation (I-3), so a frame's channels are never split.

Pure stdlib: no pygame, clock, or state.
"""

from array import array
from typing import Final

BLIP_PITCH_MAX_S: Final = 0.5                 # a longer file plays unpitched (W49)
BLIP_STEPS: Final = (-2, -1, 0, 1, 2)         # the variants, in this order
_TYPECODES: Final = {4: "i", 2: "h"}          # frame bytes -> one array item per frame


def speed(spread: float, step: int) -> float:
    """The playback speed of variant ``step`` for ``blip_pitch = spread`` (PR-F06-03)."""
    return 1.0 + spread * step / 2


def resample(raw: bytes, ratio: float, frame_bytes: int = 4) -> bytes:
    """``raw`` (whole frames of ``frame_bytes``: 4 stereo, 2 mono) played ``ratio`` times
    as fast: ``int(n / ratio)`` frames with ``out[k] = src[int(k · ratio)]``. ``ratio`` 1.0
    returns the same frames."""
    code = _TYPECODES[frame_bytes]
    src = array(code)
    assert src.itemsize == frame_bytes, "one array item must be one frame"
    assert len(raw) % frame_bytes == 0, "raw holds a partial frame"
    if ratio == 1.0:
        return bytes(raw)
    src.frombytes(raw)
    n = len(src)
    count = int(n / ratio)
    if count and int((count - 1) * ratio) >= n:        # float rounding at the very end
        last = n - 1
        picks = [src[min(int(k * ratio), last)] for k in range(count)]
    else:                                              # the index rises with k: all fit
        picks = [src[int(k * ratio)] for k in range(count)]
    return array(code, picks).tobytes()


__all__ = ["BLIP_PITCH_MAX_S", "BLIP_STEPS", "resample", "speed"]
