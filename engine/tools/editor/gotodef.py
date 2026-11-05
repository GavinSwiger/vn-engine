"""Go to definition (2026-11-04): what the name under the cursor is, and where it is made.

Why this module exists: an author reading ``jump market`` or ``amara "Hi"`` wants to see that
scene or that character, the way VS Code's Go to definition works. The script editor's
right-click menu (and Ctrl+click) asks ``target_at`` and says in words what it found ("Go to
scene market", "Show picture amara happy"), so nobody needs to know what a declaration is.

- ``target_at(line, column, names, image_refs, here=)``: the ``Target`` for the text at
  ``column`` of ``line``, or None. ``names`` is the check's name index (kind → ``NameEntry``
  or ``(name, file, line)`` rows); ``image_refs`` maps a folded picture name to its
  ``images/…`` file. A name with a place in a script goes to that line; a picture without
  an ``image`` line, and a sound, open in the File preview (``line`` None).
- ``amara sad "Hi"``: on ``sad``, the picture ``amara sad``; on ``amara``, the character.
- The words of ``show``/``scene``/``hide`` up to ``at``/``with``/``as``/``behind`` are one
  picture name; after ``at`` a position, after ``with`` a transition; after ``jump`` and
  ``call`` a scene comes first. A quoted sound path names that sound.

Pure: no Tk, so the menu's words and targets are tested without a window.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

GO: Final = "Go to {kind} {name}"
SHOW: Final = "Show {kind} {name}"
NOTHING: Final = "Go to definition"        # the menu's entry, greyed, when nothing is found

# Kind → the word the menu says, in the order a bare name is looked up.
KIND_WORDS: Final = {
    "label": "scene", "character": "character", "variable": "variable", "image": "picture",
    "transition": "transition", "position": "position", "meter": "meter",
    "ending": "ending", "route": "route", "chapter": "chapter", "style": "style",
    "ui": "screen", "glitch": "glitch", "minigame": "minigame", "tip": "tip",
    "item": "item", "category": "category"}
SOUND: Final = "sound"

_WORD: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_STAGE: Final = frozenset({"show", "scene", "hide"})
_STOPS: Final = frozenset({"at", "as", "with", "behind", "zorder", "onlayer"})
_AFTER: Final = {"at": "position", "with": "transition", "as": "image", "behind": "image"}


@dataclass(frozen=True, slots=True)
class Target:
    """Where a name is made: ``ref`` at ``line``, or ``ref`` in the File preview (None)."""

    text: str                   # the menu entry: "Go to scene market"
    ref: str
    line: int | None = None


def _rows(names: Mapping[str, Iterable[object]], kind: str) -> Iterable[tuple]:
    for row in names.get(kind, ()) or ():
        if isinstance(row, tuple):
            yield (tuple(row) + (None, None))[:3]
        else:
            yield (getattr(row, "name", None), getattr(row, "file", None),
                   getattr(row, "line", None))


def _placed(names: Mapping[str, Iterable[object]], kind: str, name: str) -> Target | None:
    for found, file, line in _rows(names, kind):
        if found == name and isinstance(file, str) and isinstance(line, int):
            return Target(GO.format(kind=KIND_WORDS[kind], name=name), file, line)
    return None


def _picture(name: str, names: Mapping[str, Iterable[object]],
             image_refs: Mapping[str, str]) -> Target | None:
    """A picture by name: its ``image`` line, else its file, else (a tag such as ``hana``)
    the first picture of that tag."""
    name = " ".join(name.split())
    placed = _placed(names, "image", name)
    if placed is not None:
        return placed
    folded = name.casefold()
    ref = image_refs.get(folded)
    if ref is None:
        found = sorted(r for n, r in image_refs.items() if n.startswith(folded + " "))
        ref = found[0] if found else None
    return Target(SHOW.format(kind="picture", name=name), ref) if ref is not None else None


def _quoted(line: str, column: int) -> str | None:
    """The text of the double-quoted string around ``column``, if any."""
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', line):
        if match.start() < column < match.end():
            return match.group(1)
    return None


def _sound(text: str, names: Mapping[str, Iterable[object]]) -> Target | None:
    wanted = text.strip().replace("\\", "/").removeprefix("audio/")
    for found, _file, _line in _rows(names, "audio"):
        if found == wanted:
            return Target(SHOW.format(kind=SOUND, name=wanted), "audio/" + wanted)
    return None


def target_at(line: str, column: int, names: Mapping[str, Iterable[object]],
              image_refs: Mapping[str, str], *,
              here: tuple[str, int] | None = None) -> Target | None:
    """What the text at ``column`` (0-based, in characters) of ``line`` names, and where it
    is made; None for nothing, or when that place is ``here`` (the same file and line)."""
    found = _target(line, column, names, image_refs)
    if found is not None and here is not None and (found.ref, found.line) == here:
        return None
    return found


def _target(line: str, column: int, names: Mapping[str, Iterable[object]],
            image_refs: Mapping[str, str]) -> Target | None:
    quoted = _quoted(line, column)
    if quoted is not None:
        return _sound(quoted, names)
    words = [(m.start(), m.end(), m.group()) for m in _WORD.finditer(line)]
    at = next((i for i, (start, end, _w) in enumerate(words) if start <= column <= end), None)
    if at is None or line.lstrip().startswith("#"):
        return None
    word = words[at][2]
    first = words[0][2] if words and words[0][0] == len(line) - len(line.lstrip()) else ""
    if first in _STAGE and at > 0:
        # show/scene/hide: the picture's words, then modifiers each taking one name.
        span = []
        for start, end, text in words[1:]:
            if text in _STOPS:
                break
            span.append((start, end, text))
        if any(start <= column <= end for start, end, _t in span):
            return _picture(" ".join(text for *_se, text in span), names, image_refs)
        before = words[at - 1][2]
        kind = _AFTER.get(before)
        if kind == "image":
            return _picture(word, names, image_refs)
        if kind is not None:
            return _placed(names, kind, word)
        return None
    quote = line.find('"')
    if at > 0 and (quote < 0 or words[at][0] < quote) and             _placed(names, "character", first) is not None:
        # ``amara sad "Hi"``: the words before the line are the picture she shows.
        said = [text for start, _e, text in words if quote < 0 or start < quote]
        return _picture(" ".join(said), names, image_refs)
    if first in ("jump", "call") and at == 1:
        placed = _placed(names, "label", word)
        if placed is not None:
            return placed
    if word.startswith("persistent."):
        return _placed(names, "variable", word) or _placed(
            names, "variable", word.removeprefix("persistent."))
    for kind in KIND_WORDS:
        if kind == "image":
            continue
        placed = _placed(names, kind, word)
        if placed is not None:
            return placed
    return None


__all__ = ["GO", "KIND_WORDS", "NOTHING", "SHOW", "SOUND", "Target", "target_at"]
