"""The stage at any line of a scene (Studio UX 2.5 "Stage preview at any line", 2026-11-06).

Why this module exists: the side pane's preview shows the stage at the selected Events row
or the Script cursor: the background, each character where the lines above put them in
their look, and the text box with that line in the speaker's colour. Studio draws it from
the script text alone, at once, with no game running, so these are pure functions of text:

- ``path_to(lines, at)``: the lines above line ``at`` that ran to get there. Branches are
  read **on the most likely path**: a choice or ``if`` that holds ``at`` takes the branch
  holding it; one wholly above takes its first branch that falls through to ``at`` (a
  branch that ends with ``jump`` or ``return`` doesn't). ``branched`` says another branch
  above would set a different stage (a ``scene``, ``show`` or ``hide``, or a face change on
  a line of dialogue), so the preview says what it assumed in one quiet line. A ``call``
  above follows the scene it calls (``scene_lines``), so a stage it sets carries back.
- ``stage_after(lines)``: the stage those lines leave, by the engine's rules (``runtime/
  stage.shown``): ``scene`` clears, a ``show`` of a tag on stage keeps its place and zoom
  (one word keeps its look), ``hide`` removes, and ``hana sad "..."`` changes Hana's look
  if she is on stage.
- ``say_at(lines, at, speakers)``: the line of text at ``at`` (narration or a defined
  character's), its words joined across the lines it spans.
- ``moment(lines, at, ...)``: all three as a ``scenepreview.Stage`` with ``say`` and
  ``note``.

Imports the standard library and its own package.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from engine.tools.editor.scenepreview import Sprite, Stage

BRANCH_NOTE: Final = "Assumes the first way through each choice and if above."
CALL_DEPTH: Final = 3                       # scenes followed through ``call``
_WORD = re.compile(r"[A-Za-z_]\w*$")
_SAY = re.compile(r'^(?:([A-Za-z_]\w*)((?:[ \t]+[A-Za-z_][\w]*){0,4})[ \t]+)?"')
_TAGS = re.compile(r"\{[^{}]*\}")
_STOP: Final = frozenset(("at", "behind", "onlayer", "zorder", "as", "with", "layer",
                          "zoom", "flip"))
_BRANCH_HEADS: Final = ("if", "elif", "else")
_LEAVES: Final = ("jump", "return")


@dataclass(frozen=True, slots=True)
class Say:
    """The text box's line: ``who`` the shown name (None: narration or no name plate),
    ``color`` the name's colour, ``text`` the words as written (tags kept for the game)."""

    who: str | None
    color: str | None
    text: str

    @property
    def plain(self) -> str:
        """``text`` without its tags, for the sketch."""
        return _TAGS.sub("", self.text).replace('\\"', '"')


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _head(line: str) -> str:
    code = line.strip()
    if not code or code.startswith("#"):
        return ""
    word = re.match(r"[A-Za-z_]\w*", code)
    return word.group(0) if word else code[0]


def _block_end(lines: Sequence[str], i: int, hi: int) -> int:
    """The index after line ``i``'s block (its deeper-indented lines)."""
    base = _indent(lines[i])
    j = i + 1
    while j < hi:
        if _head(lines[j]) and _indent(lines[j]) <= base:
            break
        j += 1
    return j


_OPTION = re.compile(r'^"(?:[^"\\]|\\.)*"[^#]*:\s*(?:#.*)?$')


def _option(line: str) -> bool:
    """A choice's line: its quoted text, maybe a condition, then ``:``."""
    return _OPTION.match(line.strip()) is not None


def _leaves(lines: Sequence[str], lo: int, hi: int, main: bool) -> bool:
    """The block ``lines[lo:hi]`` ends with ``jump`` (or ``return`` in the scene shown)."""
    last = None
    for j in range(lo, hi):
        if _head(lines[j]):
            if last is None or _indent(lines[j]) <= _indent(lines[last]):
                last = j
    if last is None:
        return False
    head = _head(lines[last])
    return head == "jump" or (head == "return" and main)


def _sets_stage(lines: Sequence[str], lo: int, hi: int) -> bool:
    for j in range(lo, hi):
        head = _head(lines[j])
        if head in ("scene", "show", "hide"):
            return True
        found = _SAY.match(lines[j].strip())
        if found and found.group(2):
            return True
    return False


def _branches(lines: Sequence[str], i: int, hi: int) -> tuple[list[tuple[int, int]], int]:
    """A branch group at line ``i`` (an ``if`` chain or a ``menu``): each branch's (header,
    end), and the index after the group."""
    if _head(lines[i]) == "menu":
        end = _block_end(lines, i, hi)
        out, j = [], i + 1
        while j < end:
            if _head(lines[j]) and _option(lines[j]):
                stop = _block_end(lines, j, end)
                out.append((j, stop))
                j = stop
            else:
                j += 1
        return out, end
    base, out, j = _indent(lines[i]), [], i
    while j < hi and _head(lines[j]) in (("if",) if j == i else ("elif", "else")) \
            and _indent(lines[j]) == base:
        stop = _block_end(lines, j, hi)
        out.append((j, stop))
        j = stop
        while j < hi and not _head(lines[j]):
            j += 1
    return out, j


def path_to(lines: Sequence[str], at: int, *,
            scene_lines: Callable[[str], Sequence[str] | None] | None = None,
            main: bool = True, depth: int = 0) -> tuple[list[str], bool]:
    """The lines run before ``lines[at]`` on the most likely path (module docstring), and
    whether the stage there depends on a branch above (one that can run sets the stage,
    and no ``scene`` line after it clears it). ``lines[0]`` is the label line (skipped);
    ``scene_lines(name)`` gives a called scene's lines (label first)."""
    out: list[str] = []
    branched = [False]
    _walk(lines, 1, len(lines), at, out, branched, scene_lines, main, depth)
    return out, branched[0]


def _walk(lines: Sequence[str], lo: int, hi: int, at: int, out: list[str],
          branched: list[bool], scene_lines: Callable[[str], Sequence[str] | None] | None,
          main: bool, depth: int) -> None:
    i = lo
    while i < hi and i < at:
        head = _head(lines[i])
        if not head:
            i += 1
            continue
        if head in ("if", "menu") and lines[i].rstrip().endswith(":"):
            group, end = _branches(lines, i, hi)
            if at < end:                                    # the cursor is in this group
                for start, stop in group:
                    if start < at < stop:
                        _walk(lines, start + 1, stop, at, out, branched, scene_lines, main,
                              depth)
                return
            ways = [(a, b) for a, b in group if not _leaves(lines, a + 1, b, main)]
            if head == "if" and group and _head(lines[group[-1][0]]) != "else":
                ways.append((end, end))                     # no branch ran
            chosen = ways[0] if ways else (group[0] if group else (end, end))
            _walk(lines, chosen[0] + 1, chosen[1], at, out, branched, scene_lines, main,
                  depth)
            if len(ways) > 1 and any(_sets_stage(lines, a + 1, b) for a, b in ways):
                branched[0] = True
            i = end
            continue
        out.append(lines[i])
        if head == "scene":
            branched[0] = False                             # a new stage: nothing carries
        elif head == "call" and scene_lines is not None and depth < CALL_DEPTH:
            words = lines[i].split()
            name = words[1].split("(", 1)[0] if len(words) > 1 else ""
            called = scene_lines(name) if _WORD.match(name) else None
            if called:
                inner, more = path_to(called, len(called), scene_lines=scene_lines,
                                      main=False, depth=depth + 1)
                out.extend(inner)
                if any(_head(line) == "scene" for line in inner):
                    branched[0] = more
                else:
                    branched[0] |= more
        i += 1


def _picture(words: Sequence[str]) -> str:
    out = []
    for word in words:
        if word in _STOP:
            break
        out.append(word)
    return " ".join(out)


def _show(line: str) -> tuple[str, str, str | None, float | None, float | None] | None:
    """A ``show`` line → (tag, picture, at, x, zoom), None when it names nothing."""
    words = line.split("#", 1)[0].split()
    name = _picture(words[1:])
    if not name:
        return None
    tag, at, x, zoom = name.split()[0], None, None, None
    for k, word in enumerate(words[:-1]):
        following = words[k + 1].strip("(),")
        if word == "as":
            tag = following
        elif word == "at":
            try:
                x = float(following)
            except ValueError:
                at = following
        elif word == "zoom":
            try:
                zoom = float(following)
            except ValueError:
                pass
    return tag, name, at, x, zoom


def stage_after(lines: Sequence[str], tag_of: Callable[[str], str] = lambda who: who,
                speakers: Mapping[str, object] | None = None) -> Stage:
    """The stage ``lines`` leave (module docstring). ``carried``: no ``scene`` line ran."""
    background, carried = None, True
    sprites: dict[str, Sprite] = {}             # by tag, in draw order
    for line in lines:
        code = line.strip()
        head = _head(line)
        if head == "scene":
            words = code.split("#", 1)[0].split()
            background, carried, sprites = _picture(words[1:]) or None, False, {}
        elif head == "show":
            found = _show(code)
            if found is None:
                continue
            tag, name, at, x, zoom = found
            old = sprites.get(tag)
            if old is None:
                sprites[tag] = Sprite(name, at, x, 1.0 if zoom is None else zoom)
            else:
                sprites[tag] = Sprite(old.image if name == tag else name,
                                      at if at is not None or x is not None else old.at,
                                      x if x is not None else (None if at else old.x),
                                      old.zoom if zoom is None else zoom)
        elif head == "hide":
            words = code.split()
            if len(words) > 1:
                sprites.pop(words[1], None)
        else:
            found = _SAY.match(code)
            if found and found.group(1) and found.group(2) and \
                    (speakers is None or found.group(1) in speakers):
                tag = tag_of(found.group(1))
                old = sprites.get(tag)
                if old is not None:
                    sprites[tag] = replace(old, image=f"{tag} {' '.join(found.group(2).split())}")
    return Stage(background, carried, tuple(sprites.values()))


def say_at(lines: Sequence[str], at: int, speakers: Mapping[str, tuple[str | None, str | None]]
           ) -> tuple[Say, str | None, str] | None:
    """The line of text at ``lines[at]``: (``Say``, its speaker's define name or None, its
    look words), else None. ``speakers``: define name → (shown name, colour)."""
    if not 0 <= at < len(lines):
        return None
    code = lines[at].strip()
    found = _SAY.match(code)
    if found is None:
        return None
    who = found.group(1)
    if who is not None and who not in speakers:
        return None                             # ``chapter x "..."`` and such
    text, j, rest = [], at, code[found.end():]
    while True:
        part, closed = _quoted(rest)
        text.append(part.strip())
        if closed or j + 1 >= len(lines) or j - at >= 20:
            break
        j += 1
        rest = lines[j]
    shown, color = speakers.get(who, (None, None)) if who is not None else (None, None)
    return Say(shown, color, " ".join(t for t in text if t)), who, " ".join(
        (found.group(2) or "").split())


def _quoted(rest: str) -> tuple[str, bool]:
    """``rest`` up to its closing quote (``\\"`` doesn't close), and whether it closed."""
    k = 0
    while k < len(rest):
        if rest[k] == "\\":
            k += 2
            continue
        if rest[k] == '"':
            return rest[:k], True
        k += 1
    return rest, False


def moment(lines: Sequence[str], at: int, *,
           speakers: Mapping[str, tuple[str | None, str | None]],
           tag_of: Callable[[str], str] = lambda who: who,
           scene_lines: Callable[[str], Sequence[str] | None] | None = None,
           lead: Sequence[str] = (), came_from: str | None = None) -> Stage:
    """The stage at ``lines[at]`` (``lines[0]``: the label line) as a ``Stage`` with
    ``say`` (the text box, or None) and ``note`` (``BRANCH_NOTE`` when the path above was
    assumed). A ``scene``, ``show`` or ``hide`` at ``at`` counts: the stage after it. With
    no ``scene`` line on the path, ``lead`` (``scenepreview.lead_in``) comes first."""
    taken, branched = path_to(lines, at, scene_lines=scene_lines)
    if 0 <= at < len(lines) and _head(lines[at]) in ("scene", "show", "hide"):
        taken.append(lines[at])
    said = say_at(lines, at, speakers)
    if said is not None and said[1] is not None and said[2]:
        taken.append(f"{said[1]} {said[2]} \"\"")    # the face this line asks for
    stage = stage_after(taken, tag_of, speakers)
    if stage.carried and lead:
        stage = stage_after([*lead, *taken], tag_of, speakers)
        stage = replace(stage, came_from=came_from if not stage.carried else None)
    return replace(stage, say=said[0] if said is not None else None,
                   note=BRANCH_NOTE if branched else None)


__all__ = ["BRANCH_NOTE", "Say", "moment", "path_to", "say_at", "stage_after"]
