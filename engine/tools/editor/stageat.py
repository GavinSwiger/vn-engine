"""The lines a **Try it** run plays (F47 ``01-design.md`` PR-F47-20, ``04-technical.md`` §7.5
P2-F; AC-F47-30).

Why this module exists: Try it plays one line in a small game window "over the scene's
background and characters at that row (else black), then holds for 2 s". The game child
(``run --try-stdin``) takes a few script lines; this module builds them, as pure functions
of text, so they are tested without Tk or a game:

- ``stage_at``: the stage a scene has set up above a row, as ``scene``/``show`` lines
  replayed in order (each without its ``with``), from the scene's lines above the row. A
  ``scene`` line starts again, ``hide`` drops that tag's lines. It reads lines as written
  (branches included), which is close enough for a preview.
- ``form_try_lines``: a form's line over that stage: the stage, a short beat so it shows
  first, the line, then the 2-second hold.
- ``transition_entry_lines``: a Database transition over a background
  (``declarations.transition_try_lines``), and ``first_background`` picks that background.

Imports only the standard library and ``declarations``.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from engine.tools.editor import declarations as dec

STAGE_BEAT: Final = "pause 0.5"         # the stage shows before the line plays
HOLD: Final = dec.TRY_PAUSE             # PR-F47-20's 2-second hold
STAGE_MAX_SHOWS: Final = 40             # at most this many ``show`` lines are replayed
BACKGROUND_TAG: Final = dec.BACKGROUND_TAG
_WITH = re.compile(r"[ \t]+with[ \t]+.*$")
_TAG = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def _code(line: str) -> str:
    """``line`` without its comment and outer blanks (stage lines hold no quotes)."""
    return line.split("#", 1)[0].strip()


def _show_tag(words: Sequence[str]) -> str | None:
    """The tag a ``show`` line's sprite goes by: its ``as`` name, else its first word."""
    if len(words) < 2:
        return None
    for at, word in enumerate(words[:-1]):
        if word == "as":
            return words[at + 1]
    return words[1]


def stage_at(lines: Iterable[str]) -> tuple[str, ...]:
    """The ``scene`` and ``show`` lines that set up the stage after ``lines`` (a scene's
    lines above a row), each without its ``with``; empty when none does (black)."""
    scene: str | None = None
    shows: list[tuple[str, str]] = []
    for line in lines:
        code = _code(line)
        words = code.split()
        if not words:
            continue
        head = words[0]
        if head == "scene":
            scene = _WITH.sub("", code)
            shows = []
        elif head == "show":
            tag = _show_tag(words)
            if tag is not None and _TAG.match(tag):
                shows.append((tag, _WITH.sub("", code)))
        elif head == "hide" and len(words) >= 2:
            shows = [(tag, text) for tag, text in shows if tag != words[1]]
    kept = [text for _tag, text in shows[-STAGE_MAX_SHOWS:]]
    return tuple(([scene] if scene is not None else []) + kept)


def form_try_lines(stage: Sequence[str], line: str) -> tuple[str, ...]:
    """A form's ``line`` (one or more lines) played over ``stage`` (``stage_at``), then
    held for 2 s. With no stage it plays on an empty black stage."""
    played = tuple(part for part in line.split("\n") if part.strip())
    if not played:
        raise ValueError("no line to try")
    return (*(stage or ("scene",)), STAGE_BEAT, *played, HOLD)


def first_background(names: Iterable[str]) -> str | None:
    """The first ``bg …`` picture name (sorted), else None."""
    found = sorted(name for name in names
                   if name.split()[:1] and name.split()[0].casefold() == BACKGROUND_TAG
                   and len(name.split()) > 1)
    return found[0] if found else None


def transition_entry_lines(name: str, values: Mapping[str, object],
                           background: str | None) -> tuple[str, ...]:
    """A Database transition's Try it lines: the empty stage, then ``background`` (else
    the built-in ``black``) through the transition, then the hold. Raises ValueError for
    values the transition can't play."""
    return dec.transition_try_lines(name, values, background or "black")
