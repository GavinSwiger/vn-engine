"""The Guide's model: seven "Your first game" steps that tick themselves from the project
(F47 ``01-design.md`` PR-F47-26, §6.4; ``04-technical.md`` §3.1, §7.4).

Why this module exists: the Guide pane (W6, ``guidepane.py``) must show the same ticks on
every refresh without reading files or Tk state of its own. So the facts it needs are
gathered once per good check into a ``GuideFacts``, and ``steps`` turns them into seven
``GuideStep`` rows, each with its **Show me** target as data. Pure Python, no Tk.

The steps, in order (texts from §6.4):

1. Name your game: ``[game] title`` is set and isn't the folder's name (New game sets the
   title to the folder name).
2. Add a character: a ``character`` name from the check.
3. Add a background: an image name whose first word is ``bg`` (``bg river_dusk``).
4. Write your first scene: the ``start`` label has ``SCENE_MIN_ROWS`` or more rows (the
   Events list's rows: every statement, nested ones included).
5. Add a choice: a ``menu`` anywhere in the story.
6. Add an ending: an ``ending`` name from the check.
7. Play it: a Play reached the game window (``studiostate.StudioState.played``).

A game made from the sample story already has characters, backgrounds and endings, so
for it (``sample=True``) steps 2, 3 and 6 count only names that aren't in
``SAMPLE_BASELINE``: the author's own. Its ``start`` and its choice tick steps 4 and 5
("two are already ticked by the sample", 01 §2).

``facts_from`` builds the facts from a ``CheckResult``, the scripts' scene reads and
``config.toml``'s text; it returns None for a check that didn't load, so the pane keeps
showing the last good check's ticks. Characters come from the launch phase, so a load-only
check (before Studio is armed) has none yet.

Imports only ``engine.core``, ``engine.script``, its own package and the standard library
(ADR-0008).
"""

import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from engine.script.menu import Menu
from engine.tools.editor.checker import CheckResult, NameEntry
from engine.tools.editor.scenes import SceneRead, chunks, parse_chunk

START_LABEL: Final = "start"
SCENE_MIN_ROWS: Final = 3
BACKGROUND_TAG: Final = "bg"
GUIDE_TITLE: Final = "Your first game"
DONE_TEXT: Final = "Your game runs from start to an ending. Well done!"

# Show me places (W6 maps each to a tab, page or button, with its New button focused).
SETTINGS: Final = "settings"            # Game settings tab; item = the page
DATABASE: Final = "database"            # Database tab; item = the category
STORY_MAP: Final = "story_map"          # Story map; item = the label to select
INSERT: Final = "insert"                # Insert picker on the start scene; item = form key
PLAY: Final = "play"                    # the Play button


@dataclass(frozen=True, slots=True)
class ShowMe:
    """Where **Show me** goes: a ``place`` constant and the item there (or None)."""

    place: str
    item: str | None = None


@dataclass(frozen=True, slots=True)
class StepSpec:
    key: str
    text: str
    show_me: ShowMe


STEPS: Final = (
    StepSpec("name", "Name your game", ShowMe(SETTINGS, "game")),
    StepSpec("character", "Add a character", ShowMe(DATABASE, "characters")),
    StepSpec("background", "Add a background", ShowMe(DATABASE, "pictures")),
    StepSpec("scene", "Write your first scene", ShowMe(STORY_MAP, START_LABEL)),
    StepSpec("choice", "Add a choice", ShowMe(INSERT, "choice")),
    StepSpec("ending", "Add an ending", ShowMe(INSERT, "ending")),
    StepSpec("play", "Play it", ShowMe(PLAY)),
)


@dataclass(frozen=True, slots=True)
class GuideFacts:
    """What the steps read. ``title`` is None when ``config.toml`` has none (or is broken)."""

    folder_name: str
    title: str | None = None
    characters: frozenset[str] = frozenset()
    backgrounds: frozenset[str] = frozenset()
    endings: frozenset[str] = frozenset()
    start_rows: int = 0
    choices: int = 0
    played: bool = False


@dataclass(frozen=True, slots=True)
class Baseline:
    """Names a template game starts with, which the Guide doesn't count as the author's."""

    characters: frozenset[str] = frozenset()
    backgrounds: frozenset[str] = frozenset()
    endings: frozenset[str] = frozenset()


# What engine/data/sample/ declares (test_guide checks this against a new sample game).
SAMPLE_BASELINE: Final = Baseline(
    characters=frozenset({"hana", "daichi"}),
    backgrounds=frozenset({"bg river_dusk", "bg bridge_night"}),
    endings=frozenset({"lantern", "next_year"}),
)


@dataclass(frozen=True, slots=True)
class GuideStep:
    """One row of the Guide: its 1-based ``number``, text, tick and Show me target."""

    number: int
    key: str
    text: str
    done: bool
    show_me: ShowMe


def steps(facts: GuideFacts, *, sample: bool = False) -> tuple[GuideStep, ...]:
    """The seven steps for ``facts``; ``sample``: the game came from the sample story."""
    base = SAMPLE_BASELINE if sample else Baseline()
    title = (facts.title or "").strip()
    done = {
        "name": bool(title) and title != facts.folder_name.strip(),
        "character": bool(facts.characters - base.characters),
        "background": bool(facts.backgrounds - base.backgrounds),
        "scene": facts.start_rows >= SCENE_MIN_ROWS,
        "choice": facts.choices > 0,
        "ending": bool(facts.endings - base.endings),
        "play": facts.played,
    }
    return tuple(GuideStep(number, spec.key, spec.text, done[spec.key], spec.show_me)
                 for number, spec in enumerate(STEPS, start=1))


def all_done(rows: Sequence[GuideStep]) -> bool:
    """Every step ticked: the pane shows ``DONE_TEXT``."""
    return bool(rows) and all(row.done for row in rows)


# --- Facts -----------------------------------------------------------------------------------

def read_scenes(texts: Mapping[str, str]) -> list[SceneRead]:
    """Every label chunk of ``texts`` (script ref → LF text) parsed as the story map does;
    chunks that don't parse are skipped."""
    found: list[SceneRead] = []
    for ref, text in texts.items():
        lines = text.split("\n")
        for _name, first, last in chunks(text):
            read = parse_chunk(ref, "\n".join(lines[first - 1:last]) + "\n")
            if read is not None and read.error is None:
                found.append(read)
    return found


def title_of(config_text: str | None) -> str | None:
    """``[game] title`` from ``config.toml``'s text, or None (missing, not text, broken)."""
    if not config_text:
        return None
    try:
        game = tomllib.loads(config_text).get("game")
    except (tomllib.TOMLDecodeError, RecursionError):
        return None
    title = game.get("title") if isinstance(game, dict) else None
    return title if isinstance(title, str) else None


def _names(names: Mapping[str, Sequence[NameEntry]], kind: str) -> frozenset[str]:
    return frozenset(entry.name for entry in names.get(kind, ()))


def facts_from(result: CheckResult | None, scenes: Iterable[SceneRead], *,
               folder_name: str, config_text: str | None, played: bool) -> GuideFacts | None:
    """The facts for one check: None when there is no result or the story didn't load
    (the pane keeps the last good facts). ``scenes`` are the scripts' reads (``read_scenes``
    over the open-or-saved texts, or the story map's index); ``config_text`` is
    ``config.toml``'s text (its open document, unsaved edits included); ``played`` is
    ``studiostate``'s."""
    if result is None or not result.loaded:
        return None
    names = result.names
    start_rows = 0
    choices = 0
    for read in scenes:
        if read.name == START_LABEL:
            start_rows = max(start_rows, len(read.statements))
        choices += sum(1 for stmt in read.statements if isinstance(stmt.node, Menu))
    backgrounds = frozenset(name for name in _names(names, "image")
                            if name.split(" ", 1)[0] == BACKGROUND_TAG and " " in name)
    return GuideFacts(folder_name=folder_name, title=title_of(config_text),
                      characters=_names(names, "character"), backgrounds=backgrounds,
                      endings=_names(names, "ending"), start_rows=start_rows,
                      choices=choices, played=played)


__all__ = ["BACKGROUND_TAG", "Baseline", "DATABASE", "DONE_TEXT", "GUIDE_TITLE",
           "GuideFacts", "GuideStep", "INSERT", "PLAY", "SAMPLE_BASELINE", "SCENE_MIN_ROWS",
           "SETTINGS", "STEPS", "STORY_MAP", "START_LABEL", "ShowMe", "StepSpec", "all_done",
           "facts_from", "read_scenes", "steps", "title_of"]
