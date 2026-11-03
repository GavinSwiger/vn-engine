"""The sprite animator: which blink or talking frame each sprite on stage shows now (F38
``SPEC.md`` §2, §5; PR-F38-02, 03, 04, 06).

Why this module exists: blinking and mouths moving with the text are pure timing, so they
live apart from drawing and are tested with a fake clock, like ``typewriter.py``. The stage
screen (F38 step 2) calls ``tick(dt, still=…)`` each frame and hands ``wanted()`` to
``StageView.show_frames``; the textbox screen reports lines (``on_say``) and typing (the
``TypingListener`` methods) to it, like F06's blips.

Rules:

- **Frames.** ``frames_of(look)`` gives a look's frames (``script/spriteframes.py``'s
  ``LookFrames``: ``blink`` and ``talk`` names in number order; ``app`` passes
  ``lambda look: frames_of(look, names)``). Each kind plays 1…N, then back down to 1, then
  the look (``spriteframes.cycle``; repeated here because ``render`` doesn't import
  ``script``).
- **Blinks.** A sprite whose look has blink frames blinks after a gap of
  ``uniform(0.5, 1.5) × blink_every`` seconds, drawn from the animator's own
  ``random.Random`` (never the story's dice), each frame ``blink_frame`` seconds, then
  draws the next gap. A new sprite, or a sprite whose look changed, starts with a gap.
- **Talking.** The ``Say``'s ``speaker_tag``, when it is on stage with talk frames, plays
  them while its line types, each ``talk_frame`` seconds, repeating 1…N…1 then the look,
  from frame 1 at the first letter or digit (a grapheme whose first code point is ``L*`` or
  ``N*``, F06's rule: spaces and "……" don't move the mouth). The mouth closes (the look
  shows) at a timed pause, a ``{pause}`` or page wait, the line's end (typed or by a
  press), a new line, a stage change, or ``TALK_IDLE_S`` with no new letter (hidden box,
  frozen typing); the next letter starts again at frame 1. Restored lines and narration
  never talk.
- **No blink while talking.** Talking cuts a blink in progress (the sprite draws a new gap);
  a blink that comes due while the mouth moves waits until it stops.
- **Holds.** ``tick(still=True)`` (reduce motion, ``[animation] enabled = false``, a
  transition, a title card, a resize: the caller decides) or a tag in ``held`` (a sprite
  too big to repaint) shows plain looks: a blink in progress ends, the mouth closes, and a
  due blink waits. ``settings.enabled`` false holds everything too.

Presentation only (PR-F38-04): nothing here reaches ``GameState``, saves, or rollback;
``reset()`` (restore, load, new game, the way to the title) drops every sprite and line.

Pure Python: no pygame, no clock of its own.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from random import Random
from typing import TYPE_CHECKING, Final, Protocol
from unicodedata import category

if TYPE_CHECKING:
    from engine.core.config_schema import AnimationConfig
    from engine.render.typewriter import WaitKind
    from engine.runtime.commands import Say
    from engine.runtime.stage import StageState

TALK_IDLE_S: Final = 0.25           # no new letter for this long closes the mouth
BLINK_GAP: Final = (0.5, 1.5)        # a gap is uniform(*BLINK_GAP) × blink_every
_EPS: Final = 1e-9                   # slack when comparing summed frame times


@dataclass(frozen=True, slots=True)
class AnimSettings:
    """``[animation]``'s four values (F38 §3), seconds as floats."""
    enabled: bool = True
    blink_every: float = 4.0
    blink_frame: float = 0.08
    talk_frame: float = 0.1

    @classmethod
    def from_config(cls, config: "AnimationConfig") -> "AnimSettings":
        return cls(config.enabled, config.blink_every, config.blink_frame, config.talk_frame)


class Frames(Protocol):
    """What ``frames_of`` returns (``spriteframes.LookFrames``)."""
    blink: Sequence[str]
    talk: Sequence[str]


FramesOf = Callable[[str], Frames]


def _cycle(frames: Sequence[str]) -> tuple[str, ...]:
    frames = tuple(frames)
    return frames + frames[-2::-1] if frames else ()


def _is_letter(grapheme: str) -> bool:
    return bool(grapheme) and category(grapheme[0])[0] in "LN"


def _step(t: float, length: float) -> int:
    return int((t + _EPS) // length)


@dataclass(slots=True)
class _Sprite:
    look: str
    blink: tuple[str, ...]           # play order, without the look
    talk: tuple[str, ...]            # play order, without the look
    wait: float = 0.0                # seconds until the next blink is due
    blink_t: float | None = None     # seconds into the blink shown, or None


class SpriteAnimator:
    """Blink timers per tag and the speaker's mouth (module docstring). ``settings`` may be
    replaced whole; it is read each ``tick``."""

    def __init__(self, frames_of: FramesOf, rng: Random,
                 settings: AnimSettings = AnimSettings()) -> None:
        self.frames_of = frames_of
        self.rng = rng
        self.settings = settings
        self._sprites: dict[str, _Sprite] = {}
        self._held: Collection[str] = frozenset()
        self._speaker: str | None = None
        self._talk_t: float | None = None    # seconds into the mouth's cycle, or None
        self._idle = 0.0                     # seconds since the last letter

    # -- read only --

    @property
    def speaker(self) -> str | None:
        """The tag of the line's speaker (None: narration, a restored line, or no line)."""
        return self._speaker

    @property
    def talking(self) -> bool:
        """Whether the speaker's mouth is moving."""
        return self._talk_t is not None

    # -- the stage and lines --

    def set_stage(self, stage: "StageState") -> None:
        """The stage shown (every ``ShowStage``). A sprite keeps its blink timer while its
        tag and look stay; a new tag or look starts with a gap. The mouth closes."""
        old = self._sprites
        sprites: dict[str, _Sprite] = {}
        for sprite in stage.sprites:
            kept = old.get(sprite.tag)
            if kept is not None and kept.look == sprite.image:
                sprites[sprite.tag] = kept
                continue
            frames = self.frames_of(sprite.image)
            fresh = _Sprite(sprite.image, _cycle(frames.blink), _cycle(frames.talk))
            if fresh.blink:
                fresh.wait = self._gap()
            sprites[sprite.tag] = fresh
        self._sprites = sprites
        self._stop_talk()

    def on_say(self, cmd: "Say") -> None:
        """Every ``Say`` shown (``TextboxScreen.add_say_listener``): its speaker may talk,
        unless the line is restored."""
        self._stop_talk()
        self._speaker = None if cmd.restored else cmd.speaker_tag

    def reset(self) -> None:
        """Plain looks, no line: a restore, a load, a new game, the way to the title. The
        next ``set_stage`` starts the sprites again."""
        self._sprites = {}
        self._speaker = None
        self._held = frozenset()
        self._stop_talk()

    # -- TypingListener --

    def glyph_shown(self, index: int, grapheme: str) -> None:
        if not _is_letter(grapheme):
            return
        tag = self._speaker
        sprite = self._sprites.get(tag) if tag is not None else None
        if sprite is None or not sprite.talk or tag in self._held:
            return
        if self._talk_t is None:
            self._talk_t = 0.0
            if sprite.blink_t is not None:           # talking cuts a blink in progress
                self._end_blink(sprite)
        self._idle = 0.0

    def pause_started(self, seconds: float) -> None:
        self._stop_talk()

    def waiting(self, kind: "WaitKind") -> None:
        self._stop_talk()

    def completed(self, by_press: bool) -> None:
        self._stop_talk()

    # -- the frame --

    def tick(self, dt: float, *, still: bool = False, held: Collection[str] = ()) -> None:
        """Add ``dt`` seconds. ``still``: every sprite holds its plain look this frame;
        ``held``: these tags do (a sprite too big to repaint)."""
        settings = self.settings
        holding = still or not settings.enabled
        self._held = frozenset(self._sprites if holding else held)
        if self._talk_t is not None:
            self._idle += dt
            if self._speaker in self._held or self._idle >= TALK_IDLE_S - _EPS:
                self._stop_talk()
            else:
                self._talk_t += dt
        talker = self._speaker if self._talk_t is not None else None
        for tag, sprite in self._sprites.items():
            if not sprite.blink:
                continue
            if sprite.blink_t is not None:
                sprite.blink_t += dt
                if tag in self._held or sprite.blink_t >= (
                        len(sprite.blink) * settings.blink_frame - _EPS):
                    self._end_blink(sprite)
                continue
            sprite.wait -= dt
            if sprite.wait <= _EPS and tag != talker and tag not in self._held:
                sprite.blink_t = 0.0

    def wanted(self) -> Mapping[str, str]:
        """Tag → the frame name it shows now, for each sprite not at its plain look."""
        settings = self.settings
        out: dict[str, str] = {}
        for tag, sprite in self._sprites.items():
            if tag in self._held:
                continue
            if tag == self._speaker and self._talk_t is not None:
                step = _step(self._talk_t, settings.talk_frame) % (len(sprite.talk) + 1)
                if step < len(sprite.talk):
                    out[tag] = sprite.talk[step]
            elif sprite.blink_t is not None:
                step = _step(sprite.blink_t, settings.blink_frame)
                if step < len(sprite.blink):
                    out[tag] = sprite.blink[step]
        return out

    # -- internals --

    def _gap(self) -> float:
        return self.rng.uniform(*BLINK_GAP) * self.settings.blink_every

    def _end_blink(self, sprite: _Sprite) -> None:
        sprite.blink_t = None
        sprite.wait = self._gap()

    def _stop_talk(self) -> None:
        self._talk_t = None
        self._idle = 0.0
