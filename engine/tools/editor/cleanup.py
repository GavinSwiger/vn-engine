"""Database ▸ Clean up's model (F41 ``04-technical.md`` §7.5; design §4.4, §6.1, §6.2; P5).

Why this module exists: Clean up lists what the linter (``tools/lint.py``) found: scenes
nothing reaches and things nothing uses. The check child sends those findings as names rows
(``unreached``, ``unused_character|picture|sound|variable|define|transition|position|meter``;
decision 1), never as Problems items. This module turns **one run's** ``CheckResult`` into
what the pane shows: its state, the header and waiting lines, the groups and their rows, and
each row's kind line, place, warning text and actions. W2's ``dbcleanup.py`` (Tk) shows it
as given.

- **States** (PR-F41-15, AC-F41-20): no result → ``Not checked yet``; an error in the run, or
  no lint kinds (lint didn't run) → the errors text; no ``unused_character`` (a
  ``--no-launch`` run) → the waiting line above the list; no rows → the empty text.
- **Groups** in §6.1's order; rows sorted by name within a group (Other: by kind, then
  name); at most ``CLEANUP_MAX_ROWS`` rows across groups, then ``Showing 1,000 of {n}.``.
  Counts are the run's true totals (``name_totals``), so the category count is n.
- **Targets** (decision 2): a row finds its Database entry **by name** within its category
  (pictures without case, sounds by their name under ``audio/``), so a picture with no
  ``image`` line (a file only) needs nothing new. A scene targets the story map, a plain
  ``define`` the editor at its line (decision 5).
- **Actions** are data: ``Open in {category}`` / ``Show on map`` / ``Open in Editor``, then
  ``Delete…`` through the category's own Delete (decision 4; a scene through F46's Delete
  scene, a define through the declaration delete). W2 offers Delete only where the category
  does.

Pure: no Tk. Imports ``core``, ``script`` (``format_message``) and this package, never
``tools.check``, ``tools.lint`` or ``runtime``; the kind table matches ``lint.LINT_KINDS``
(a test compares them).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from engine.script.messages import format_message
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec

# --- Texts (design §6.2, final) ------------------------------------------------------------------

TITLE: Final = db.CATEGORY_TITLES[db.CATEGORY_CLEANUP]
HEADER: Final = "These aren't used in your story. Delete what you don't need before you build."
EMPTY: Final = "Nothing to clean up. Everything in your game is used."
ERRORS: Final = "Fix the errors in Problems first. Clean up needs a story that loads."
WAITING: Final = "Characters are listed after your first Play or Check now."
OVER_CAP: Final = "Showing {shown} of {total}."
NOT_CHECKED: Final = "Not checked yet"
OPEN_IN: Final = "Open in {category}"
SHOW_ON_MAP: Final = "Show on map"
OPEN_IN_EDITOR: Final = "Open in Editor"
DELETE: Final = "Delete…"

CLEANUP_MAX_ROWS: Final = 1_000          # rows shown across groups (the check child's cap)

# --- States -------------------------------------------------------------------------------------

STATE_NOT_CHECKED: Final = "not_checked"
STATE_ERRORS: Final = "errors"
STATE_EMPTY: Final = "empty"
STATE_LIST: Final = "list"

# --- Groups (§6.1 order) and kinds --------------------------------------------------------------

# Group keys are the singular category keys ("characters" as a literal belongs only to
# core/constants.py, the meta-files write root; tests/core/test_paths_meta.py).
GROUP_SCENES: Final = "scene"
GROUP_CHARACTERS: Final = db.CATEGORY_CHARACTER
GROUP_PICTURES: Final = db.CATEGORY_PICTURE
GROUP_SOUNDS: Final = db.CATEGORY_SOUND
GROUP_VARIABLES: Final = db.CATEGORY_VARIABLE
GROUP_OTHER: Final = "other"
GROUPS: Final[tuple[tuple[str, str], ...]] = (
    (GROUP_SCENES, "SCENES NOT REACHED"), (GROUP_CHARACTERS, "CHARACTERS"),
    (GROUP_PICTURES, "PICTURES"), (GROUP_SOUNDS, "SOUNDS"), (GROUP_VARIABLES, "VARIABLES"),
    (GROUP_OTHER, "OTHER"))

# Where a row's actions lead.
TO_CATEGORY: Final = "category"          # a Database category's entry
TO_MAP: Final = "map"                    # the story map's scene box (F46)
TO_EDITOR: Final = "editor"              # the line in the editor (a plain define)

UNUSED_CHARACTER: Final = "unused_character"


@dataclass(frozen=True, slots=True)
class CleanupKind:
    """One names row kind: its code, W242's kind word (None for W237–W241), group, form kind
    line, where it leads, the Database category (None: the map or the editor) and the
    entry kind its Delete removes (a ``declarations`` or ``dbmodel`` kind; None: a scene)."""

    code: str
    word: str | None
    group: str
    kind_line: str
    to: str
    category: str | None
    entry_kind: str | None


KINDS: Final[Mapping[str, CleanupKind]] = {
    "unreached": CleanupKind("W237", None, GROUP_SCENES, "Scene", TO_MAP, None, None),
    UNUSED_CHARACTER: CleanupKind("W238", None, GROUP_CHARACTERS, "Character", TO_CATEGORY,
                                  db.CATEGORY_CHARACTER, dec.CHARACTER),
    "unused_picture": CleanupKind("W239", None, GROUP_PICTURES, "Picture", TO_CATEGORY,
                                  db.CATEGORY_PICTURE, db.BACKGROUND),
    "unused_sound": CleanupKind("W240", None, GROUP_SOUNDS, "Sound", TO_CATEGORY,
                                db.CATEGORY_SOUND, db.SOUND),
    "unused_variable": CleanupKind("W241", None, GROUP_VARIABLES, "Variable", TO_CATEGORY,
                                   db.CATEGORY_VARIABLE, dec.VARIABLE),
    "unused_define": CleanupKind("W242", "define", GROUP_OTHER, "Define", TO_EDITOR, None,
                                 dec.DEFINE),
    "unused_transition": CleanupKind("W242", "transition", GROUP_OTHER, "Transition",
                                     TO_CATEGORY, db.CATEGORY_TRANSITION, dec.TRANSITION),
    "unused_position": CleanupKind("W242", "position", GROUP_OTHER, "Position", TO_CATEGORY,
                                   db.CATEGORY_POSITION, dec.POSITION),
    "unused_meter": CleanupKind("W242", "meter", GROUP_OTHER, "Meter", TO_CATEGORY,
                                db.CATEGORY_METER, dec.METER),
}
_KIND_ORDER: Final = {kind: n for n, kind in enumerate(KINDS)}

# Actions (data; W2 wires each).
ACTION_OPEN: Final = "open"              # Open in {category}
ACTION_MAP: Final = "map"                # Show on map
ACTION_EDITOR: Final = "editor"          # Open in Editor
ACTION_DELETE: Final = "delete"          # Delete… through the target's own Delete


@dataclass(frozen=True, slots=True)
class Action:
    """One button: what it does (``ACTION_*``) and its text."""

    action: str
    text: str


@dataclass(frozen=True, slots=True)
class CleanupItem:
    """One Clean up row. ``iid`` is ``u:{kind}:{name}``; ``place`` is ``{file name}:{line}``
    (the file name alone without a line, "" without a file); ``text`` the warning."""

    kind: str
    name: str
    file: str | None
    line: int | None
    info: CleanupKind

    @property
    def iid(self) -> str:
        return f"u:{self.kind}:{self.name}"

    @property
    def code(self) -> str:
        return self.info.code

    @property
    def group(self) -> str:
        return self.info.group

    @property
    def kind_line(self) -> str:
        return self.info.kind_line

    @property
    def place(self) -> str:
        if not self.file:
            return ""
        name = self.file.rsplit("/", 1)[-1]
        return name if self.line is None else f"{name}:{self.line}"

    @property
    def text(self) -> str:
        args = (self.name,) if self.info.word is None else (self.info.word, self.name)
        return format_message(self.info.code, args)

    @property
    def target(self) -> str:
        """Where Open leads: ``TO_CATEGORY``, ``TO_MAP`` or ``TO_EDITOR``."""
        return self.info.to

    @property
    def category(self) -> str | None:
        """The Database category whose entry this row is (None: a scene or a define)."""
        return self.info.category

    @property
    def actions(self) -> tuple[Action, ...]:
        """Open in {category} (Show on map for a scene, Open in Editor for a define), then
        Delete…."""
        if self.info.to == TO_MAP:
            first = Action(ACTION_MAP, SHOW_ON_MAP)
        elif self.info.to == TO_EDITOR:
            first = Action(ACTION_EDITOR, OPEN_IN_EDITOR)
        else:
            title = db.CATEGORY_TITLES[self.info.category or ""]
            first = Action(ACTION_OPEN, OPEN_IN.format(category=title))
        return (first, Action(ACTION_DELETE, DELETE))

    def matches(self, entry_name: str) -> bool:
        """Whether a Database entry named ``entry_name`` is this row's (by name; pictures
        without case; sounds by their name under ``audio/``)."""
        if self.kind == "unused_picture":
            return entry_name.casefold() == self.name.casefold()
        if self.kind == "unused_sound":
            return entry_name.removeprefix("audio/") == self.name
        return entry_name == self.name


@dataclass(frozen=True, slots=True)
class CleanupGroup:
    key: str
    heading: str
    count: int                      # the group's true total
    items: tuple[CleanupItem, ...]  # shown rows


@dataclass(frozen=True, slots=True)
class CleanupView:
    """What the pane shows: ``state``; ``message`` (the state's text: not checked, errors,
    empty; None for a list); the ``header``; the ``waiting`` line (None after a full
    check); ``over_cap`` (None under the cap); the groups with rows; ``count`` (the
    category's count, every row of the run)."""

    state: str
    message: str | None
    header: str | None = None
    waiting: str | None = None
    over_cap: str | None = None
    groups: tuple[CleanupGroup, ...] = ()
    count: int = 0

    @property
    def items(self) -> tuple[CleanupItem, ...]:
        return tuple(item for group in self.groups for item in group.items)

    def item(self, iid: str) -> CleanupItem | None:
        return next((item for item in self.items if item.iid == iid), None)


def _row_parts(row: Any) -> tuple[str, str | None, int | None]:
    if isinstance(row, tuple):
        return row[0], row[1], row[2]
    return row.name, row.file, row.line


def _has_errors(result: Any) -> bool:
    return any(getattr(problem, "severity", None) == "error"
               for problem in getattr(result, "problems", ()))


def cleanup_view(result: Any | None) -> CleanupView:
    """Clean up for **this run's** ``CheckResult`` (its ``names`` and ``name_totals``, not
    the window's merged names, which keep kinds a run didn't send)."""
    if result is None:
        return CleanupView(STATE_NOT_CHECKED, NOT_CHECKED)
    names: Mapping[str, Sequence[Any]] = getattr(result, "names", {}) or {}
    totals: Mapping[str, int] = getattr(result, "name_totals", {}) or {}
    sent = [kind for kind in KINDS if kind in names]
    if _has_errors(result) or not sent:
        return CleanupView(STATE_ERRORS, ERRORS)
    waiting = WAITING if UNUSED_CHARACTER not in names else None
    grouped: dict[str, list[CleanupItem]] = {key: [] for key, _heading in GROUPS}
    counts: dict[str, int] = dict.fromkeys(grouped, 0)
    for kind in sent:
        info = KINDS[kind]
        rows = names[kind]
        counts[info.group] += max(totals.get(kind, 0), len(rows))
        grouped[info.group].extend(CleanupItem(kind, *_row_parts(row), info) for row in rows)
    total = sum(counts.values())
    if total == 0:
        return CleanupView(STATE_EMPTY, EMPTY, waiting=waiting)
    groups: list[CleanupGroup] = []
    room = CLEANUP_MAX_ROWS
    for key, heading in GROUPS:
        items = sorted(grouped[key], key=lambda i: (_KIND_ORDER[i.kind], i.name.casefold(),
                                                    i.name))
        shown = tuple(items[:max(room, 0)])
        room -= len(shown)
        if counts[key]:
            groups.append(CleanupGroup(key, heading, counts[key], shown))
    shown_count = sum(len(group.items) for group in groups)
    over = OVER_CAP.format(shown=f"{shown_count:,}", total=f"{total:,}") \
        if shown_count < total else None
    return CleanupView(STATE_LIST, None, HEADER, waiting, over, tuple(groups), total)


def search(view: CleanupView, text: str) -> tuple[CleanupItem, ...]:
    """The shown rows whose name holds ``text`` (any case; PR-F41-16)."""
    folded = text.strip().casefold()
    return tuple(item for item in view.items if folded in item.name.casefold())


def target_entry(item: CleanupItem, entries: Iterable[Any]) -> Any | None:
    """The first of ``entries`` (Database ``Entry``s, or rows with an ``entry``) that is
    ``item``'s, by name within its category; None when there is none (or for a scene)."""
    if item.target != TO_CATEGORY and item.kind != "unused_define":
        return None
    for candidate in entries:
        entry = getattr(candidate, "entry", candidate)
        name = getattr(entry, "name", None)
        if isinstance(name, str) and item.matches(name):
            return candidate
    return None


__all__ = ["ACTION_DELETE", "ACTION_EDITOR", "ACTION_MAP", "ACTION_OPEN", "Action",
           "CLEANUP_MAX_ROWS", "CleanupGroup", "CleanupItem", "CleanupKind", "CleanupView",
           "DELETE", "EMPTY", "ERRORS", "GROUPS", "HEADER", "KINDS", "NOT_CHECKED",
           "OPEN_IN", "OPEN_IN_EDITOR", "OVER_CAP", "SHOW_ON_MAP", "STATE_EMPTY",
           "STATE_ERRORS", "STATE_LIST", "STATE_NOT_CHECKED", "TITLE", "TO_CATEGORY",
           "TO_EDITOR", "TO_MAP", "WAITING", "cleanup_view", "search", "target_entry"]
