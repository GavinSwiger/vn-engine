"""The Guide's model: five chapters of steps that tick themselves from the project, following
the beginner's guide ``docs/first-game.md`` part by part (F47 ``01-design.md`` PR-F47-26,
§6.4; ``04-technical.md`` §3.1, §7.4; the walkthrough plan of 2026-11).

Why this module exists: the Guide pane (``guidepane.py``) must show the same ticks on every
refresh without reading files or Tk state of its own. So the facts the steps need are
gathered once per good check into a ``GuideFacts``, and ``chapters`` turns them into
``GuideChapter`` rows of ``GuideStep``s, each with its **Show me** target and its **Read
more** heading in the guide as data. Pure Python, no Tk.

The chapters are the guide's five parts: 1 Your first game, 2 Make it yours, 3 Choices that
matter, 4 Bigger games (optional: the author may skip it) and 5 Test and share. Each step's
tick rule is in ``_DONE``; a step ticks only from the project (the check's names, the
scripts' scene reads and declarations, ``config.toml``) or from what Studio saw happen and
keeps in ``studio.json`` (a Play reached the game window, an ending a Play reached, a
problem fixed; ``marks``), never from a Guide button.

A game made from the sample story already has characters, pictures, music, a choice, a
variable and two endings, so for it (``sample=True``) the steps count only what isn't in
``SAMPLE_BASELINE``: the author's own. Nothing is ticked in a new sample game.

``facts_from`` builds the facts from a ``CheckResult``, the scripts' texts and
``config.toml``'s text; it returns None for a check that didn't load, so the pane keeps the
last good check's ticks. ``note_check`` turns each check (loaded or not) into the marks
"a problem was seen, then fixed".

Imports only ``engine.core``, ``engine.script``, its own package and the standard library
(ADR-0008).
"""

import functools
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.script.nodes import Say
from engine.tools.editor import declarations as dec
from engine.tools.editor.checker import CheckResult, NameEntry
from engine.tools.editor.scenes import SceneRead, chunks, parse_chunk

START_LABEL: Final = "start"
SCENE_MIN_ROWS: Final = 3
BACKGROUND_TAG: Final = "bg"
GUIDE_TITLE: Final = "Guide checklist"          # Help ▸ Guide checklist shows the pane
GUIDE_DOC: Final = "first-game.md"              # Help ▸ Guides ▸ Beginner's guide
DOC_TITLE: Final = "Beginner's guide"
DONE_TEXT: Final = "Your game runs from start to an ending. Well done!"

# Show me places (the pane maps each to a tab, page or button, with its New button focused).
SETTINGS: Final = "settings"            # Game settings tab; item = the page
DATABASE: Final = "database"            # Database tab; item = the category, target = a row
STORY_MAP: Final = "story_map"          # Story map; item = the scene to open beside it
INSERT: Final = "insert"                # Insert form on the start scene; item = its title
PLAY: Final = "play"                    # the Play button
MENU: Final = "menu"                    # a File menu entry; item = its label
PROBLEMS: Final = "problems"            # the Problems panel
UPDATE: Final = "update"                # the ⟳ Update button (▶ Play when no game runs)

# Marks Studio keeps in studio.json's ``guide`` list: what it saw happen.
STAGE_VIEWED: Final = "stage_viewed"    # an Events row showed the stage AT LINE
PLAYED_SCENE: Final = "played_scene"    # a Play started at a scene other than start
HOT_UPDATED: Final = "hot_updated"      # a running game took a change ("Updated at")
BUILT: Final = "built"                  # a build finished
ERROR_SEEN: Final = "error_seen"
ERROR_FIXED: Final = "error_fixed"      # a check with errors, then one without
UNREACHABLE_SEEN: Final = "unreachable_seen"
UNREACHABLE_FIXED: Final = "unreachable_fixed"
LEFTOVERS_SEEN: Final = "leftovers_seen"
LEFTOVERS_CLEARED: Final = "leftovers_cleared"   # Clean up listed something, then nothing
SKIP_PREFIX: Final = "skip_"            # skip_bigger: the author skipped that chapter
MARKS: Final = (STAGE_VIEWED, PLAYED_SCENE, HOT_UPDATED, BUILT, ERROR_SEEN, ERROR_FIXED,
                UNREACHABLE_SEEN, UNREACHABLE_FIXED, LEFTOVERS_SEEN, LEFTOVERS_CLEARED)

# The Clean up list's kinds (``cleanup.KINDS``: the check's linter rows).
LEFTOVER_KINDS: Final = ("unreached", "unused_character", "unused_picture", "unused_sound",
                         "unused_variable", "unused_define", "unused_transition",
                         "unused_position", "unused_meter")


@dataclass(frozen=True, slots=True)
class ShowMe:
    """Where **Show me** goes: a ``place`` constant, the item there (or None) and, for the
    Database, the row to select (``target``: a name; None: none)."""

    place: str
    item: str | None = None
    target: str | None = None


@dataclass(frozen=True, slots=True)
class StepSpec:
    """One step: ``text`` (what to do, short), ``hint`` (one sentence of how), ``section``
    (the guide's heading **Read more** opens) and Show me."""

    key: str
    text: str
    hint: str
    section: str
    show_me: ShowMe
    sample_only: bool = False


@dataclass(frozen=True, slots=True)
class ChapterSpec:
    key: str
    title: str
    section: str                        # the guide's part heading
    done_text: str
    steps: tuple[StepSpec, ...]
    optional: bool = False


def _s(key: str, text: str, hint: str, section: str, show_me: ShowMe, *,
       sample_only: bool = False) -> StepSpec:
    return StepSpec(key, text, hint, section, show_me, sample_only)


PART1, PART2, PART3 = ("Part 1: Your first game", "Part 2: Make it yours",
                       "Part 3: Choices that matter")
PART4, PART5 = "Part 4: Bigger games", "Part 5: Test and share"

CHAPTERS: Final = (
    ChapterSpec("first", "Your first game", PART1, DONE_TEXT, (
        _s("play_sample", "Play the sample",
           "Click the arrow next to ▶ Play, pick Play from the start, and click through.",
           "Step 3: Play the sample", ShowMe(PLAY, START_LABEL), sample_only=True),
        _s("name", "Name your game", "Type a title of your own in Game settings ▸ Game title.",
           "Step 5: Name your game", ShowMe(SETTINGS, "game")),
        _s("character", "Add a character",
           "In the Database, click Characters, then + New, and give them a name.",
           "Step 6: Add a character with pictures", ShowMe(DATABASE, "character")),
        _s("looks", "Give them pictures",
           "Open your character in the Database and click + Add looks… to add their faces.",
           "Step 6: Add a character with pictures", ShowMe(DATABASE, "character")),
        _s("background", "Add a background",
           "In the Database, click Pictures, then + New ▸ Add backgrounds….",
           "Step 7: Add backgrounds", ShowMe(DATABASE, "picture")),
        _s("scene", "Write your first scene",
           "Give the first scene a few lines, with your character saying one of them.",
           "Step 8: Write your first scene", ShowMe(STORY_MAP, START_LABEL)),
        _s("choice", "Add a choice",
           "Give the player two buttons that lead to different scenes.",
           "Step 10: Add a choice with two branches", ShowMe(INSERT, "Choice")),
        _s("ending", "Add an ending", "Finish a scene with an ending card.",
           "Step 11: Add endings", ShowMe(INSERT, "Ending")),
        _s("play", "Play to an ending",
           "Play from the start and pick choices until an ending card shows.",
           "Step 12: Play to the end", ShowMe(PLAY, START_LABEL)),
    )),
    ChapterSpec("yours", "Make it yours", PART2, "Your game looks and sounds like yours now.", (
        _s("kit", "Pick a kit", "In Game settings ▸ Kit, click a card, then Apply.",
           "Pick a kit and a color scheme", ShowMe(SETTINGS, "kits")),
        _s("scheme", "Pick a color scheme",
           "Apply a kit with its colors, or a card in Game settings ▸ Color scheme.",
           "Pick a kit and a color scheme", ShowMe(SETTINGS, "schemes")),
        _s("title_screen", "Dress the title screen",
           "In Game settings ▸ Title screen, pick a background picture or music.",
           "The title screen", ShowMe(SETTINGS, "title")),
        _s("music", "Add music", "Start a song in a scene with Insert ▸ Audio ▸ Music.",
           "Music and sounds", ShowMe(INSERT, "Music")),
        _s("sound", "Add a sound effect", "Play a short sound once, like a door bell.",
           "Music and sounds", ShowMe(INSERT, "Sound")),
        _s("effect", "Add a transition or effect",
           "Fade a background in with dissolve, or shake the screen for a moment.",
           "Transitions and effects", ShowMe(INSERT, "Shake screen")),
        _s("colors", "Style a character's lines",
           "Give your character a Text colour, or make their lines Italic.",
           "Name colors and the text box", ShowMe(DATABASE, "character")),
        _s("stage", "See the stage at a line",
           "Open a scene on the Story map and click a row in Events.",
           "See the stage at any line", ShowMe(STORY_MAP, START_LABEL)),
    )),
    ChapterSpec("choices", "Choices that matter", PART3,
                "Your game remembers what the player chose.", (
        _s("variable", "Add a variable",
           "In the Database, click Variables, then + New. A Yes-No one is a good start.",
           "Variables", ShowMe(DATABASE, "variable")),
        _s("set_in_choice", "Change it in a choice",
           "Under one of a choice's buttons, add a Set variable line.",
           "Variables", ShowMe(STORY_MAP, START_LABEL)),
        _s("meter", "Add a meter", "In the Database, click Meters, then + New.",
           "Meters", ShowMe(DATABASE, "meter")),
        _s("meter_use", "Show and change the meter",
           "Show the meter in a scene, then add or take points after a choice.",
           "Meters", ShowMe(INSERT, "Change meter")),
        _s("condition", "Hide a button behind a test",
           "Fill in a button's Only show when, such as points.mood >= 8.",
           "Choices that need something", ShowMe(STORY_MAP, START_LABEL)),
        _s("roll", "Roll the dice",
           "Add a check to a button, so a meter and luck decide what happens.",
           "Checks: rolling the dice", ShowMe(STORY_MAP, START_LABEL)),
        _s("three_endings", "Have three endings",
           "Add endings until your story has three of its own.",
           "Many endings", ShowMe(INSERT, "Ending")),
        _s("unreachable", "Fix a scene nobody can reach",
           "When the Story map marks a scene \"can't be reached\", change what leads there.",
           "Scenes nobody can reach", ShowMe(STORY_MAP)),
        _s("remembered", "Remember across playthroughs",
           "Tick Remembered across playthroughs on a variable, then fix any problem it shows.",
           "Remembering across playthroughs", ShowMe(DATABASE, "variable")),
        _s("two_endings", "Reach two endings",
           "Play twice and pick differently. The title screen's Extras ▸ Endings lists them.",
           "The Endings page", ShowMe(PLAY, START_LABEL)),
    )),
    ChapterSpec("bigger", "Bigger games", PART4,
                "You've tried the tools for bigger games.", (
        _s("second_part", "Split the story in two",
           "Choose File ▸ New script file, type a name such as night2, and click Create.",
           PART4, ShowMe(MENU, "New script file")),
        _s("clock", "Move the story clock", "Add a Go to a day line to start a new day.",
           "Story time: the clock and the calendar", ShowMe(INSERT, "Go to a day")),
        _s("items", "Give an item and money",
           "Make an item in Database ▸ Codex, then give it to the player in a scene.",
           "Items, money and a shop", ShowMe(DATABASE, "codex")),
        _s("shop", "Open a shop", "Add a Minigame line that opens the shop.",
           "Items, money and a shop", ShowMe(INSERT, "Minigame")),
        _s("letter", "Send a letter",
           "Add a contact in Database ▸ Contacts, then send the player a message.",
           "The Inbox: letters and messages", ShowMe(DATABASE, "contact")),
        _s("reply", "Read a reply",
           "Add an If that tests inbox.reply, to react to the player's answer.",
           "The Inbox: letters and messages", ShowMe(INSERT, "If")),
        _s("tip", "Add a codex tip",
           "Make a tip in Database ▸ Codex and give it to the player in a scene.",
           "The codex: tips and items", ShowMe(DATABASE, "codex")),
        _s("ask_name", "Ask the player's name",
           "Add a Minigame line with ask_text, keeping the answer in a variable.",
           "Minigames", ShowMe(INSERT, "Minigame")),
        _s("chapter", "Start a chapter", "Add a Chapter line under a scene's background.",
           "Chapters", ShowMe(INSERT, "Chapter")),
    ), optional=True),
    ChapterSpec("share", "Test and share", PART5,
                "Your game is ready to share. Send people the zip.", (
        _s("fix_problem", "Fix a problem",
           "Click a row in Problems to go to its line, then fix it.",
           "The game check and Problems", ShowMe(PROBLEMS)),
        _s("play_scene", "Play from a scene",
           "Put the cursor in a scene other than the first, then press ▶ Play.",
           "Play from any scene", ShowMe(PLAY)),
        _s("hot_update", "Update the running game",
           "While the game runs, change a line and save. The game picks it up.",
           "Update while the game runs", ShowMe(UPDATE)),
        _s("cleanup", "Tidy up with Clean up",
           "Delete what Database ▸ Clean up lists until it says nothing is left.",
           "Clean up", ShowMe(DATABASE, "cleanup")),
        _s("build", "Build the game", "Choose File ▸ Build game… and click Build.",
           "Build the Windows game", ShowMe(MENU, "Build game…")),
    )),
)
CHAPTER_KEYS: Final = tuple(chapter.key for chapter in CHAPTERS)
STEPS: Final = CHAPTERS[0].steps                # the first game's steps (celebrations)


@dataclass(frozen=True, slots=True)
class MenuFacts:
    """One ``menu``: its scene, its buttons' texts, and whether a button has an ``if`` test
    or a ``check``."""

    scene: str
    options: frozenset[str]
    tested: bool = False
    rolled: bool = False


@dataclass(frozen=True, slots=True)
class GuideFacts:
    """What the steps read. ``title`` is None when ``config.toml`` has none (or is broken).
    ``uses`` maps a kind of line (``USE_KINDS``) to the lines of that kind, as written (one
    space between words), so the sample's own lines can be told apart. ``marks``: what
    Studio saw happen (studio.json); ``reached``: endings a Play from Studio reached."""

    folder_name: str
    title: str | None = None
    characters: frozenset[str] = frozenset()
    backgrounds: frozenset[str] = frozenset()
    endings: frozenset[str] = frozenset()
    start_rows: int = 0
    choices: int = 0
    played: bool = False
    images: frozenset[str] = frozenset()
    start_speakers: frozenset[str] = frozenset()
    menus: tuple[MenuFacts, ...] = ()
    uses: Mapping[str, frozenset[str]] = field(default_factory=dict)
    variables: frozenset[str] = frozenset()
    remembered: frozenset[str] = frozenset()
    meters: frozenset[str] = frozenset()
    items: frozenset[str] = frozenset()
    tips: frozenset[str] = frozenset()
    contacts: frozenset[str] = frozenset()
    styled: frozenset[str] = frozenset()        # characters with a text colour or italic
    theme: Mapping[str, object] = field(default_factory=dict)   # config.toml's [theme]
    script_refs: frozenset[str] = frozenset()
    errors: int = 0
    unreachable: tuple[str, ...] = ()           # scenes marked can't be reached / not reached
    marks: frozenset[str] = frozenset()
    reached: frozenset[str] = frozenset()


# Kinds of line ``uses`` keeps (``_use_kinds``).
USE_KINDS: Final = ("music", "sound", "effect", "set_in_choice", "meter_show", "points",
                    "clock", "unlock_item", "unlock_tip", "shop", "ask_text", "send", "reply",
                    "chapter")


@dataclass(frozen=True, slots=True)
class Baseline:
    """What a template game starts with, which the Guide doesn't count as the author's."""

    characters: frozenset[str] = frozenset()
    backgrounds: frozenset[str] = frozenset()
    endings: frozenset[str] = frozenset()
    variables: frozenset[str] = frozenset()
    menus: frozenset[frozenset[str]] = frozenset()      # each menu's button texts
    lines: frozenset[str] = frozenset()                 # lines ``uses`` would count
    script_refs: frozenset[str] = frozenset()


# What engine/data/sample/ has (test_guide checks this against a new sample game).
SAMPLE_BASELINE: Final = Baseline(
    characters=frozenset({"hana", "daichi"}),
    backgrounds=frozenset({"bg river_dusk", "bg bridge_night"}),
    endings=frozenset({"lantern", "next_year"}),
    variables=frozenset({"sent_lantern"}),
    menus=frozenset({frozenset({"Write a wish and send one", "Just watch this year"})}),
    lines=frozenset({
        "scene bg river_dusk with dissolve",
        'play music "music/lantern_walk.wav" fadein 1.0',
        "show hana happy at left with dissolve",
        "show daichi smile at right with dissolve",
        "$ sent_lantern = True",
        "scene bg bridge_night with dissolve",
        'play sound "sound/chime.wav"',
        "show hana happy with dissolve",
    }),
    script_refs=frozenset({"script/main.vns", "script/database.vns"}),
)
EMPTY_BASELINE: Final = Baseline(script_refs=frozenset({"script/main.vns"}))


@dataclass(frozen=True, slots=True)
class GuideStep:
    """One row of the Guide: its 1-based ``number`` in its chapter, text, tick, Show me
    target, hint and the guide's heading for **Read more**."""

    number: int
    key: str
    text: str
    done: bool
    show_me: ShowMe
    hint: str = ""
    section: str = ""


@dataclass(frozen=True, slots=True)
class GuideChapter:
    """One chapter: its 1-based ``number``, rows, and whether it is done, skipped (an
    optional chapter the author skipped) or ``current`` (the first neither done nor
    skipped)."""

    number: int
    key: str
    title: str
    section: str
    done_text: str
    rows: tuple[GuideStep, ...]
    optional: bool = False
    skipped: bool = False
    current: bool = False

    @property
    def done(self) -> bool:
        return all_done(self.rows)

    @property
    def ticked(self) -> int:
        return sum(1 for row in self.rows if row.done)


def skip_mark(chapter: str) -> str:
    return SKIP_PREFIX + chapter


def _own(found: Iterable[str], base: Iterable[str]) -> frozenset[str]:
    return frozenset(found) - frozenset(base)


def _done(facts: GuideFacts, base: Baseline) -> dict[str, bool]:
    """Every step's tick rule, by key."""
    title = (facts.title or "").strip()
    marks = facts.marks
    characters = _own(facts.characters, base.characters)
    own_menus = [m for m in facts.menus if m.options not in base.menus]
    endings = _own(facts.endings, base.endings)
    reached = _own(facts.reached, base.endings)

    def used(kind: str) -> bool:
        return bool(facts.uses.get(kind, frozenset()) - base.lines)

    theme = facts.theme
    title_screen = theme.get("title")
    return {
        # Chapter 1
        "play_sample": facts.played,
        "name": bool(title) and title != facts.folder_name.strip(),
        "character": bool(characters),
        "looks": any(len(name.split(" ")) > 1 and name.split(" ", 1)[0] in characters
                     for name in facts.images),
        "background": bool(facts.backgrounds - base.backgrounds),
        "scene": facts.start_rows >= SCENE_MIN_ROWS and bool(facts.start_speakers & characters),
        "choice": bool(own_menus),
        "ending": bool(endings),
        "play": bool(reached),
        # Chapter 2
        "kit": isinstance(theme.get("kit"), str) and bool(theme.get("kit")),
        "scheme": bool(theme.get("preset")) or bool(theme.get("scheme")),
        "title_screen": isinstance(title_screen, dict) and bool(title_screen),
        "music": used("music"),
        "sound": used("sound"),
        "effect": used("effect"),
        "colors": bool(facts.styled & characters),
        "stage": STAGE_VIEWED in marks,
        # Chapter 3
        "variable": bool(_own(facts.variables, base.variables)),
        "set_in_choice": used("set_in_choice"),
        "meter": bool(facts.meters),
        "meter_use": used("meter_show") and used("points"),
        "condition": any(m.tested for m in own_menus),
        "roll": any(m.rolled for m in own_menus),
        "three_endings": len(endings) >= 3,
        "unreachable": UNREACHABLE_FIXED in marks,
        "remembered": bool(facts.remembered) and facts.errors == 0,
        "two_endings": len(reached) >= 2,
        # Chapter 4
        "second_part": bool(facts.script_refs - base.script_refs),
        "clock": used("clock"),
        "items": bool(facts.items) and used("unlock_item"),
        "shop": used("shop"),
        "letter": bool(facts.contacts) and used("send"),
        "reply": used("reply"),
        "tip": bool(facts.tips) and used("unlock_tip"),
        "ask_name": used("ask_text"),
        "chapter": used("chapter"),
        # Chapter 5
        "fix_problem": ERROR_FIXED in marks,
        "play_scene": PLAYED_SCENE in marks,
        "hot_update": HOT_UPDATED in marks,
        "cleanup": LEFTOVERS_CLEARED in marks,
        "build": BUILT in marks,
    }


def _show_me(spec: StepSpec, facts: GuideFacts, base: Baseline) -> ShowMe:
    """The step's Show me, aimed at the author's own character or choice when there is one."""
    target = spec.show_me
    if target.place == DATABASE and spec.key in ("looks", "colors"):
        own = sorted(_own(facts.characters, base.characters))
        return ShowMe(DATABASE, target.item, own[-1] if own else None)
    if spec.key in ("set_in_choice", "condition", "roll"):
        own = [m for m in facts.menus if m.options not in base.menus]
        return ShowMe(STORY_MAP, own[-1].scene if own else START_LABEL)
    if spec.key == "unreachable":
        return ShowMe(STORY_MAP, facts.unreachable[0] if facts.unreachable else None)
    return target


def steps(facts: GuideFacts, *, sample: bool = False,
          chapter: str = CHAPTER_KEYS[0]) -> tuple[GuideStep, ...]:
    """The steps of ``chapter`` for ``facts``; ``sample``: the game came from the sample
    story (its things don't count, and it has the "Play the sample" step)."""
    base = SAMPLE_BASELINE if sample else EMPTY_BASELINE
    done = _done(facts, base)
    spec = next(c for c in CHAPTERS if c.key == chapter)
    shown = [step for step in spec.steps if sample or not step.sample_only]
    return tuple(GuideStep(number, step.key, step.text, done[step.key],
                           _show_me(step, facts, base), step.hint, step.section)
                 for number, step in enumerate(shown, start=1))


def chapters(facts: GuideFacts, *, sample: bool = False) -> tuple[GuideChapter, ...]:
    """Every chapter for ``facts``; the first neither done nor skipped is ``current``."""
    found: list[GuideChapter] = []
    current_given = False
    for number, spec in enumerate(CHAPTERS, start=1):
        rows = steps(facts, sample=sample, chapter=spec.key)
        skipped = spec.optional and skip_mark(spec.key) in facts.marks and not all_done(rows)
        current = not current_given and not skipped and not all_done(rows)
        current_given = current_given or current
        found.append(GuideChapter(number, spec.key, spec.title, spec.section, spec.done_text,
                                  rows, spec.optional, skipped, current))
    return tuple(found)


def all_done(rows: Sequence[GuideStep]) -> bool:
    """Every step ticked: the chapter shows its done text."""
    return bool(rows) and all(row.done for row in rows)


def note_check(marks: Iterable[str], *, errors: int, unreachable: bool | None,
               leftovers: bool | None) -> frozenset[str]:
    """``marks`` after one check: a problem seen, then gone, is a problem fixed. ``errors``
    counts the check's errors; ``unreachable`` and ``leftovers`` (Clean up's list isn't
    empty) are None when the check couldn't tell (it didn't load, or the linter didn't run)."""
    found = set(marks)
    for now, seen, fixed in ((errors > 0, ERROR_SEEN, ERROR_FIXED),
                             (unreachable, UNREACHABLE_SEEN, UNREACHABLE_FIXED),
                             (leftovers, LEFTOVERS_SEEN, LEFTOVERS_CLEARED)):
        if now:
            found.add(seen)
        elif now is not None and seen in found:
            found.add(fixed)
    return frozenset(found)


# --- Facts -----------------------------------------------------------------------------------
#
# Studio checks after every typing pause, so the facts must be cheap on a long story: each
# script is read line by line with a few patterns (cached per text, so an unchanged file
# costs a lookup), and only the ``start`` scene is parsed (its rows and speakers).

_LABEL = re.compile(r"label[ \t]+([^\W\d]\w*)[ \t]*(?:\(|:)")
_MENU = re.compile(r"menu\b[^\"]*:[ \t]*(?:#.*)?$")
_CHOICE = re.compile(r'"((?:[^"\\]|\\.)*)"(.*):[ \t]*(?:#.*)?$')
_SET = re.compile(r"\$[ \t]*(?:persistent[ \t]*\.[ \t]*)?[^\W\d]\w*[ \t]*[-+*/]?=(?!=)")
_USES: Final = (
    ("music", re.compile(r"(?:play|queue)[ \t]+music\b")),
    ("sound", re.compile(r"play[ \t]+sound\b")),
    ("effect", re.compile(r"(?:(?:scene|show|hide)\b.*[ \t]with[ \t]+\w|with[ \t]+\w|"
                          r"shake\b|flash\b)")),
    ("meter_show", re.compile(r"show[ \t]+meter\b")),
    ("points", re.compile(r"points[ \t]+\w+[ \t]*[-+]=")),
    ("clock", re.compile(r"clock[ \t]+(?:next|go[ \t]+to)\b")),
    ("unlock_item", re.compile(r"unlock[ \t]+item\b")),
    ("unlock_tip", re.compile(r"unlock[ \t]+tip\b")),
    ("shop", re.compile(r"minigame[ \t]+shop\b")),
    ("ask_text", re.compile(r"minigame[ \t]+ask_text\b")),
    ("send", re.compile(r"send[ \t]+\w+[ \t]+from\b")),
    ("reply", re.compile(r"(?:el)?if\b.*inbox\.reply[ \t]*\(")),
    ("chapter", re.compile(r"chapter[ \t]+\w")),
)
TEXT_CACHE: Final = 256                 # scripts whose scan is kept


@dataclass(frozen=True, slots=True)
class TextScan:
    """One script's facts: its menus, its lines by ``USE_KINDS`` (``(kind, line)`` pairs),
    whether it has the ``start`` scene, and its declarations."""

    menus: tuple[MenuFacts, ...]
    uses: tuple[tuple[str, str], ...]
    has_start: bool
    declared: tuple[dec.Decl, ...]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


@functools.lru_cache(maxsize=TEXT_CACHE)
def scan_text(ref: str, text: str) -> TextScan:
    """``text``'s menus and uses, read line by line inside its scenes (no parsing)."""
    menus: list[MenuFacts] = []
    uses: list[tuple[str, str]] = []
    scene: str | None = None
    has_start = False
    menu: tuple[int, list[str], list[bool], list[bool]] | None = None
    choice_indent: int | None = None

    def close_menu() -> None:
        nonlocal menu, choice_indent
        if menu is not None and scene is not None:
            _at, options, tested, rolled = menu
            menus.append(MenuFacts(scene, frozenset(options), any(tested), any(rolled)))
        menu, choice_indent = None, None

    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        depth = _indent(raw)
        if depth == 0:
            close_menu()
            label = _LABEL.match(line)
            scene = label.group(1) if label else None
            has_start = has_start or scene == START_LABEL
            continue
        if scene is None:
            continue
        if menu is not None and depth <= menu[0]:
            close_menu()
        if choice_indent is not None and depth <= choice_indent:
            choice_indent = None
        if menu is not None and choice_indent is None:
            button = _CHOICE.match(line)
            if button is not None:              # a button: "Text" [if …] [check …]:
                tail = button.group(2)
                menu[1].append(button.group(1))
                menu[2].append(re.search(r"(?:^|[ \t])if\b", tail) is not None)
                menu[3].append(re.search(r"(?:^|[ \t])check\b", tail) is not None)
                choice_indent = depth
                continue
        words = " ".join(line.split())
        if _MENU.match(line):
            close_menu()
            menu = (depth, [], [], [])
            continue
        if choice_indent is not None and _SET.match(line):
            uses.append(("set_in_choice", words))
        for kind, pattern in _USES:
            if pattern.match(line):
                uses.append((kind, words))
    close_menu()
    return TextScan(tuple(menus), tuple(uses), has_start, dec.scan({ref: text}))


@functools.lru_cache(maxsize=8)
def start_read(ref: str, text: str) -> SceneRead | None:
    """The ``start`` scene of ``text`` parsed (the one scene the facts parse)."""
    lines = text.split("\n")
    for name, first, last in chunks(text):
        if name == START_LABEL:
            read = parse_chunk(ref, "\n".join(lines[first - 1:last]) + "\n")
            return read if read is not None and read.error is None else None
    return None


def scan_scenes(texts: Mapping[str, str]) -> tuple[int, int, frozenset[str],
                                                   tuple[MenuFacts, ...],
                                                   dict[str, frozenset[str]],
                                                   tuple[dec.Decl, ...]]:
    """(start's row count, the number of menus, start's speakers, each menu, ``uses``, the
    declarations) from the scripts (ref → text)."""
    start_rows = 0
    speakers: set[str] = set()
    menus: list[MenuFacts] = []
    uses: dict[str, set[str]] = {}
    declared: list[dec.Decl] = []
    for ref in sorted(texts):
        found = scan_text(ref, texts[ref])
        menus += found.menus
        declared += found.declared
        for kind, line in found.uses:
            uses.setdefault(kind, set()).add(line)
        read = start_read(ref, texts[ref]) if found.has_start else None
        if read is not None:
            start_rows = max(start_rows, len(read.statements))
            speakers |= {stmt.node.speaker for stmt in read.statements
                         if isinstance(stmt.node, Say) and stmt.node.speaker}
    return (start_rows, len(menus), frozenset(speakers), tuple(menus),
            {kind: frozenset(lines) for kind, lines in uses.items()}, tuple(declared))


def theme_of(config_text: str | None) -> dict:
    """``config.toml``'s text read as TOML; {} when missing or broken."""
    if not config_text:
        return {}
    try:
        return tomllib.loads(config_text)
    except (tomllib.TOMLDecodeError, RecursionError):
        return {}


def title_of(config_text: str | None) -> str | None:
    """``[game] title`` from ``config.toml``'s text, or None (missing, not text, broken)."""
    game = theme_of(config_text).get("game")
    title = game.get("title") if isinstance(game, dict) else None
    return title if isinstance(title, str) else None


def _names(names: Mapping[str, Sequence[NameEntry]], kind: str) -> frozenset[str]:
    return frozenset(entry.name for entry in names.get(kind, ()))


def errors_in(result: CheckResult) -> int:
    return sum(1 for item in result.problems if item.severity == "error")


def unreachable_in(result: CheckResult) -> tuple[str, ...]:
    """Scenes the check marks "can't be reached" or "not reached", in name order."""
    blocked = {scene for scene, rows in result.reach.items()
               if any(row.kind == "blocked" for row in rows)}
    return tuple(sorted(blocked | _names(result.names, "unreached")))


def leftovers_in(result: CheckResult) -> bool | None:
    """Clean up's list isn't empty; None when the linter didn't run."""
    if not result.loaded or "unused_character" not in result.name_totals:
        return None
    return any(result.name_totals.get(kind, 0) for kind in LEFTOVER_KINDS)


def facts_from(result: CheckResult | None, texts: Mapping[str, str], *,
               folder_name: str, config_text: str | None, played: bool,
               marks: Iterable[str] = (), reached: Iterable[str] = ()) -> GuideFacts | None:
    """The facts for one check: None when there is no result or the story didn't load
    (the pane keeps the last good facts). ``texts`` are the scripts (ref → text, open
    documents' unsaved edits included); ``config_text`` is ``config.toml``'s text;
    ``played``, ``marks`` and ``reached`` are ``studiostate``'s."""
    if result is None or not result.loaded:
        return None
    names = result.names
    start_rows, choices, speakers, menus, uses, declared = scan_scenes(texts)
    images = _names(names, "image")
    backgrounds = frozenset(name for name in images
                            if name.split(" ", 1)[0] == BACKGROUND_TAG and " " in name)

    def kind(*kinds: str) -> frozenset[str]:
        return frozenset(d.name for d in declared if d.kind in kinds)

    styled = frozenset(d.name for d in declared if d.kind == dec.CHARACTER and d.values
                       and (d.values.get("text_color") or d.values.get("text_italic")))
    doc = theme_of(config_text)
    theme = doc.get("theme")
    game = doc.get("game")
    if isinstance(game, dict) and "kit" in game:          # [game] kit ([theme] before v1)
        theme = {**(theme if isinstance(theme, dict) else {}), "kit": game["kit"]}
    return GuideFacts(
        folder_name=folder_name, title=title_of(config_text),
        characters=_names(names, "character") | kind(dec.CHARACTER), backgrounds=backgrounds,
        endings=_names(names, "ending"), start_rows=start_rows, choices=choices,
        played=played, images=images, start_speakers=speakers, menus=menus, uses=uses,
        variables=kind(dec.VARIABLE), remembered=kind(dec.PERSISTENT),
        meters=kind(dec.METER) | _names(names, "meter"), items=kind(dec.ITEM),
        tips=kind(dec.TIP), contacts=kind(dec.CONTACT) | _names(names, "contact"),
        styled=styled, theme=theme if isinstance(theme, dict) else {},
        script_refs=frozenset(ref for ref in texts if ref.endswith(".vns")),
        errors=errors_in(result), unreachable=unreachable_in(result),
        marks=frozenset(marks), reached=frozenset(reached))


__all__ = ["BACKGROUND_TAG", "BUILT", "Baseline", "CHAPTERS", "CHAPTER_KEYS", "ChapterSpec",
           "DATABASE", "DOC_TITLE", "DONE_TEXT", "EMPTY_BASELINE", "ERROR_FIXED", "ERROR_SEEN",
           "GUIDE_DOC", "GUIDE_TITLE", "GuideChapter", "GuideFacts", "GuideStep", "HOT_UPDATED",
           "INSERT", "LEFTOVERS_CLEARED", "LEFTOVERS_SEEN", "MARKS", "MENU", "MenuFacts", "PLAY",
           "PLAYED_SCENE", "PROBLEMS", "SAMPLE_BASELINE", "SCENE_MIN_ROWS", "SETTINGS",
           "STAGE_VIEWED", "START_LABEL", "STEPS", "STORY_MAP", "ShowMe", "StepSpec", "TextScan",
           "UNREACHABLE_FIXED", "UNREACHABLE_SEEN", "UPDATE", "USE_KINDS", "all_done", "chapters",
           "errors_in", "facts_from", "leftovers_in", "note_check", "scan_scenes", "scan_text",
           "skip_mark", "start_read", "steps", "theme_of", "title_of", "unreachable_in"]
