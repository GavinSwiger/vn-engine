"""F38's frame naming rule (PR-F38-01): which image names are a look's blink and talking
frames, and the order they play in.

Why this module exists: a character blinks and moves her mouth with no code. Next to
``images/hana/happy.png`` the author drops ``happy_blink1.png`` (eyes closed) and
``happy_talk1.png`` (mouth open); the names alone are the setup. The game (``app`` builds the
``render/spriteanim.py`` animator from ``frames_of``) and Studio (Database ▸ Characters,
which may import only ``core`` and ``script``) read the rule here, like ``imagenames.py``.

The rule, case-exact, for a look (an image name such as ``hana happy`` or ``hana``):

- Its frames are ``<look>_blink``, ``<look>_blink1`` … ``<look>_blink9`` and ``<look>_talk``,
  ``<look>_talk1`` … ``<look>_talk9`` (``hana happy_blink1`` is
  ``images/hana/happy_blink1.png``; ``hana_talk1`` is a frame of the one-word look ``hana``).
- They play with no number first, then by number; a missing number is skipped.
  ``_blink0``, ``_blink10`` and ``_blink01`` are not frames (they stay ordinary looks).
- Both the look and the frame must be picture files: names from files under ``images/``
  and from ``image name = "file"`` declarations count, solid colors (``image x = "#…"``)
  don't. A frame name whose look doesn't exist is an ordinary look.

Pure: no I/O, no pygame. ``names`` is a container of picture names (``picture_names``
builds one from ``ImageIndex.items()``; Studio passes its own list of image names).
"""

from collections.abc import Container, Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

FrameKind = Literal["blink", "talk"]
FRAME_KINDS: Final[tuple[FrameKind, ...]] = ("blink", "talk")
FRAMES_MAX: Final = 9                # numbers 1–9 (plus the unnumbered one)
_DIGITS: Final = frozenset("123456789")


@dataclass(frozen=True, slots=True)
class LookFrames:
    """A look's frame names, each kind in number order (unnumbered first)."""
    blink: tuple[str, ...] = ()
    talk: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.blink or self.talk)

    def of(self, kind: FrameKind) -> tuple[str, ...]:
        return self.blink if kind == "blink" else self.talk


NO_FRAMES: Final = LookFrames()


@dataclass(frozen=True, slots=True)
class Frame:
    """What ``frame_of`` found: the look it belongs to, its kind, and its number (0 when the
    name has none)."""
    look: str
    kind: FrameKind
    number: int


def _check(kind: str, number: int) -> None:
    if kind not in FRAME_KINDS:
        raise ValueError(f"frame kind must be one of {FRAME_KINDS}, not {kind!r}")
    if type(number) is not int or not 0 <= number <= FRAMES_MAX:
        raise ValueError(f"frame number must be 0 to {FRAMES_MAX}, not {number!r}")


def frame_name(look: str, kind: FrameKind, number: int = 0) -> str:
    """The frame's image name: ``frame_name("hana happy", "blink", 1)`` is
    ``"hana happy_blink1"``; number 0 gives the unnumbered ``"hana happy_blink"``."""
    _check(kind, number)
    return f"{look}_{kind}{number or ''}"


def _numbers(look: str, kind: FrameKind, names: Container[str]) -> list[int]:
    return [n for n in range(FRAMES_MAX + 1) if frame_name(look, kind, n) in names]


def frames_of(look: str, names: Container[str]) -> LookFrames:
    """``look``'s frames among ``names`` (picture names), in play order per kind;
    ``NO_FRAMES`` when ``look`` isn't one of ``names`` or has none."""
    if look not in names:
        return NO_FRAMES
    found = {kind: tuple(frame_name(look, kind, n) for n in _numbers(look, kind, names))
             for kind in FRAME_KINDS}
    return LookFrames(found["blink"], found["talk"]) if any(found.values()) else NO_FRAMES


def frame_of(name: str, names: Container[str]) -> Frame | None:
    """The ``Frame`` that ``name`` is, or None: not named like a frame, or its look isn't
    one of ``names``, or ``name`` itself isn't. (Studio hides frames from its look lists
    with this.)"""
    if name not in names:
        return None
    for kind in FRAME_KINDS:
        tail = "_" + kind
        at = name.rfind(tail)
        if at <= 0:
            continue
        rest = name[at + len(tail):]
        if rest and (len(rest) != 1 or rest not in _DIGITS):
            continue
        look = name[:at]
        if look not in names:
            continue
        return Frame(look, kind, int(rest or 0))
    return None


def cycle(frames: Sequence[str]) -> tuple[str, ...]:
    """The play order of one kind's frames: 1…N, then back down to 1 (``(a, b, c)`` →
    ``(a, b, c, b, a)``). The look shows after it."""
    frames = tuple(frames)
    return frames + frames[-2::-1] if frames else ()


def next_number(look: str, kind: FrameKind, names: Container[str]) -> int | None:
    """The number Studio gives a new frame: 1 + the highest used (an unnumbered frame
    counts as 0), or None when 9 is used (a look holds at most frames 1–9)."""
    _check(kind, 0)
    top = max(_numbers(look, kind, names), default=0)
    return None if top >= FRAMES_MAX else top + 1


def picture_names(images: Iterable[tuple[str, object]]) -> frozenset[str]:
    """The names that are picture files, from ``(name, image)`` pairs such as
    ``ImageIndex.items()``: an image with a ``ref`` (an ``ImageFile``) counts, a solid color
    (``SolidColor``, which has none) doesn't."""
    return frozenset(name for name, image in images
                     if isinstance(getattr(image, "ref", None), str))
