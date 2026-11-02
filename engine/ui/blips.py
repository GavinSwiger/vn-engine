"""``BlipPlayer``: a character's text blips as F05 types its line (F06 ``SPEC.md`` §5, ``07``
I-2; PR-F06-01 to 06).

Why this module exists: a ``Character(blip=…)`` line plays a short sound on every
``blip_every``-th letter or digit as it appears, so players can tell speakers apart by ear.
The textbox's typing listener seam (``TextboxScreen.add_listener``) reports each grapheme the
moment it shows, so blips follow the typewriter exactly: none during a timed pause, at a
click-wait, while hidden or frozen, or after a completing press, because no grapheme shows
then (F05 §7.10). ``install_textbox`` (``app/text_check.py``) registers one player per launch
when ``App.audio`` exists; it also listens to every ``Say`` (``add_say_listener``) to learn
the speaker's ``BlipSpec`` and restart the count.

- A grapheme blips only when its first code point's Unicode category starts with ``L`` or
  ``N`` (letters and digits, kana and CJK included); spaces, punctuation, symbols, emoji,
  and ``\\n`` are silent (PR-F06-01).
- Every ``every``-th eligible grapheme blips, starting with the line's first; the count
  restarts on each ``Say``, not at a page or click-wait (PR-F06-02).
- At most one blip starts per ``BLIP_MIN_GAP_S``; an eligible grapheme inside the gap is
  silent but still counts (PR-F06-05), so instant text gives one blip.
- A restored line (rollback, load) and a voiced line (``Say.voice``) never blip; narration
  and characters without ``blip`` have no ``BlipSpec`` (PR-F06-04, 06).
- With ``spread`` > 0 each blip is one of ``BLIP_STEPS``' variants, picked by the player's
  own ``random.Random`` (presentation randomness: invariant 7 doesn't apply).

Skipping, a file that is still decoding (the 50 ms limit), a broken file (W26), volume, and
"one blip at a time" are ``AudioService.play_blip``'s (F06 step 2). F16 turns blips off and on
with ``set_enabled``; on, the next eligible grapheme blips.

Cost: under 1 µs per grapheme with no blip; a cached blip is the service's call.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Protocol
from unicodedata import category

from engine.audio.pitch import BLIP_STEPS

if TYPE_CHECKING:
    from random import Random

    from engine.render.typewriter import WaitKind
    from engine.runtime.character import BlipSpec
    from engine.runtime.commands import Say

BLIP_MIN_GAP_S: Final = 0.04          # PR-F06-05: at most one blip starts per 40 ms (I-2)


class BlipAudio(Protocol):
    """What the player needs of the ``AudioService`` (F06 step 2)."""

    def play_blip(self, file: str, *, volume: int = 100, spread: float = 0.0,
                  step: int = 0) -> None: ...


def blips_on(grapheme: str) -> bool:
    """Whether ``grapheme`` is a letter or digit (its first code point's category is
    ``L*`` or ``N*``; PR-F06-01)."""
    return bool(grapheme) and category(grapheme[0])[0] in "LN"


class BlipPlayer:
    """One launch's blips: an F05 ``TypingListener`` (``glyph_shown``) and say listener
    (``on_say``) on the textbox. ``clock`` is the App's monotonic clock (seconds)."""

    def __init__(self, audio: BlipAudio, clock: Callable[[], float], rng: "Random") -> None:
        self.audio = audio
        self.clock = clock
        self.rng = rng
        self.enabled = True
        self._spec: "BlipSpec | None" = None       # the line's blip; None: a silent line
        self._count = 0                             # eligible graphemes of the line so far
        self._last = float("-inf")                  # when the last blip started

    def set_enabled(self, on: bool) -> None:
        """F16's switch. Turned on again, the next eligible grapheme blips (the gap
        allowing)."""
        on = bool(on)
        if on and not self.enabled:
            self._count = 0
        self.enabled = on

    # -- say listener --

    def on_say(self, cmd: "Say") -> None:
        """Every ``Say``, before the textbox lays it out: the line's ``BlipSpec``, or none
        for a restored or voiced line."""
        spec = cmd.blip
        self._spec = None if spec is None or cmd.restored or cmd.voice is not None else spec
        self._count = 0

    # -- TypingListener --

    def glyph_shown(self, index: int, grapheme: str) -> None:
        spec = self._spec
        if spec is None or not self.enabled or not blips_on(grapheme):
            return
        count = self._count
        self._count = count + 1
        if count % spec.every:
            return
        now = self.clock()
        if now - self._last < BLIP_MIN_GAP_S:
            return
        self._last = now
        spread = spec.spread
        step = self.rng.choice(BLIP_STEPS) if spread else 0
        self.audio.play_blip(spec.file, volume=spec.volume, spread=spread, step=step)

    def pause_started(self, seconds: float) -> None:
        pass

    def waiting(self, kind: "WaitKind") -> None:
        pass

    def completed(self, by_press: bool) -> None:
        pass


__all__ = ["BLIP_MIN_GAP_S", "BlipAudio", "BlipPlayer", "blips_on"]
