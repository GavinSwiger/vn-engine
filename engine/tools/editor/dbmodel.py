"""The Database's lists (F47 ``04-technical.md`` §3.1, §7.1; design §4.3, §6.2, §6.4,
PR-F47-02, PR-F47-05, PR-F47-10; AC-F47-08, 14, 15).

Why this module exists: each Database category is a list of entries with "Used in N lines"
and a Delete that is refused while the entry is used. The lists merge what
``declarations.scan`` reads from the texts (so a new author's characters show without a
launch check) with the last good check's name index (``CheckResult.names``: ``character``,
``image``, ``audio``, ``variable`` and the ``*_use`` rows of ``tools/check.py``). P2-D adds
the Meters, Codex, Endings & routes, Chapters, Transitions and Positions lists
(``P2_CATEGORIES``) and remembered variables; W7 adds them to the tab. F34-W4 adds
**Gallery** (``CATEGORY_GALLERY``, after Pictures): ``gallery_entries`` in gallery order
(``include_order``, then line), "used" by the ``lock|unlock gallery`` lines of the texts.
F35-S3 adds **Music room** (``CATEGORY_MUSIC_ROOM``, after Sounds): ``track_entries`` in
declaration order (the same order; nothing names a track, so a track is never "used"). Pure: no Tk;
``names`` is any mapping of kind → rows with ``name``, ``file`` and ``line`` (``NameEntry``).
"""

import re
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from engine.script.spriteframes import frame_of
from engine.tools.editor import declarations as dec

# --- Decision 4 and texts (design §6.4) --------------------------------------------------------

SOUND_FOLDERS: Final = ("music", "sound", "voice", "blips")
OTHER_SOUNDS: Final = "other"
SOUND_TITLES: Final[Mapping[str, str]] = {
    "music": "Music", "sound": "Sound effects", "voice": "Voices", "blips": "Blips",
    OTHER_SOUNDS: "Other"}

NOT_USED: Final = "Not used yet"
USED_IN: Final = "Used in {lines}"
DELETE_REFUSED: Final = "{name} is used in {lines}, so it can't be deleted yet."
SHOW_USES: Final = "Show uses"
EDIT_AS_SCRIPT: Final = "Edit as script"
EMPTY_TITLE: Final = "No {things} yet"
EMPTY_HINT: Final = "Add one with + New."
SCRIPT_NAME: Final = "Used in the script as {name}"

# The P1 Database category keys (singular: "characters" is the F31 write root's word, which
# only core/constants.py may spell; tests/core/test_paths_meta.py), in the design's order.
CATEGORY_CHARACTER: Final = "character"
CATEGORY_PICTURE: Final = "picture"
CATEGORY_SOUND: Final = "sound"
CATEGORY_VARIABLE: Final = "variable"
CATEGORIES: Final = (CATEGORY_CHARACTER, CATEGORY_PICTURE, CATEGORY_SOUND, CATEGORY_VARIABLE)
# P2 categories (design §4.3, P2-D), in the design's order; W7 adds them to the tab.
# "Endings & routes" is one category: its key is "ending".
CATEGORY_METER: Final = "meter"
CATEGORY_CODEX: Final = "codex"
CATEGORY_ENDING: Final = "ending"
CATEGORY_CHAPTER: Final = "chapter"
CATEGORY_TRANSITION: Final = "transition"
CATEGORY_POSITION: Final = "position"
CATEGORY_GALLERY: Final = "gallery"        # F34-W4: after Pictures (database.ALL_CATEGORIES)
CATEGORY_MUSIC_ROOM: Final = "music_room"  # F35-S3: after Sounds (database.ALL_CATEGORIES)
P2_CATEGORIES: Final = (CATEGORY_METER, CATEGORY_CODEX, CATEGORY_ENDING, CATEGORY_CHAPTER,
                        CATEGORY_TRANSITION, CATEGORY_POSITION)
CATEGORY_TITLES: Final[Mapping[str, str]] = {
    CATEGORY_CHARACTER: "Characters", CATEGORY_PICTURE: "Pictures", CATEGORY_SOUND: "Sounds",
    CATEGORY_VARIABLE: "Variables", CATEGORY_METER: "Meters", CATEGORY_CODEX: "Codex",
    CATEGORY_ENDING: "Endings & routes", CATEGORY_CHAPTER: "Chapters",
    CATEGORY_TRANSITION: "Transitions", CATEGORY_POSITION: "Positions",
    CATEGORY_GALLERY: "Gallery", CATEGORY_MUSIC_ROOM: "Music room"}
# The "{things}" of each P2 category's empty state (§6.4 "No {things} yet").
EMPTY_THINGS: Final[Mapping[str, str]] = {
    CATEGORY_METER: "meters", CATEGORY_CODEX: "tips or items", CATEGORY_ENDING: "routes",
    CATEGORY_CHAPTER: "chapters", CATEGORY_TRANSITION: "transitions",
    CATEGORY_POSITION: "positions", CATEGORY_GALLERY: "gallery pictures",
    CATEGORY_MUSIC_ROOM: "tracks"}
REMEMBERED: Final = "Remembered across playthroughs"
TIPS: Final = "Tips"
ITEMS: Final = "Items"
ENDINGS_HINT: Final = "Endings come from the Ending lines of your story."
CHAPTERS_HINT: Final = "Chapters come from the Chapter lines of your story."

# Entry kinds beyond declarations' (pictures and sounds are files, not declarations).
BACKGROUND: Final = "background"   # an image named bg …: a file, or a colour (dec.COLOR)
SOUND: Final = "sound"

# Which check rows count an entry's uses. An ending is "used" by the routes that wait for
# it (``route_until``); chapters and remembered variables have no rows.
USE_KINDS: Final[Mapping[str, str]] = {
    dec.CHARACTER: "character_use", dec.COLOR: "image_use", BACKGROUND: "image_use",
    dec.VARIABLE: "variable_use", SOUND: "audio_use", dec.METER: "meter_use",
    dec.TIP: "codex_use", dec.ITEM: "codex_use", dec.ROUTE: "route_use",
    dec.TRANSITION: "transition_use", dec.POSITION: "position_use",
    dec.ENDING: "route_until"}
_FOLDED: Final = frozenset((dec.COLOR, BACKGROUND))    # image names compare without case


class NameRow(Protocol):
    name: str
    file: str | None
    line: int | None


Names = Mapping[str, Sequence[NameRow]]


@dataclass(frozen=True, slots=True)
class Entry:
    """One list row: ``name`` (the script name, or a sound's ref under ``audio/``), ``shown``
    (the list text), ``place`` (declaring ``(ref, line)``, None for a file), ``editable``
    (the form can edit it; False: **Edit as script**, or a file), ``uses`` (distinct lines),
    and the ``decl`` read from the text, when there is one."""

    kind: str
    name: str
    shown: str
    place: tuple[str, int] | None
    editable: bool
    uses: int
    decl: dec.Decl | None = None
    folder: str | None = None                  # sounds: one of SOUND_FOLDERS or OTHER_SOUNDS
    values: Mapping[str, object] | None = None  # positions: x, y, builtin, written

    @property
    def name_editable(self) -> bool:
        """PR-F47-10: the script name can change while nothing uses it."""
        return self.editable and self.uses == 0

    @property
    def used_text(self) -> str:
        return used_text(self.uses)


# --- Uses (PR-F47-05, AC-F47-15) ---------------------------------------------------------------

def _lines(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def used_text(uses: int) -> str:
    """"Used in N lines" (one line: "Used in 1 line"), or "Not used yet"."""
    return NOT_USED if uses <= 0 else USED_IN.format(lines=_lines(uses))


def use_places(names: Names, kind: str, name: str) -> tuple[tuple[str | None, int | None], ...]:
    """The distinct ``(file, line)`` where entry ``kind`` ``name`` is used, in check order
    (for **Show uses**)."""
    rows = names.get(USE_KINDS.get(kind, ""), ())
    folded = kind in _FOLDED
    want = name.casefold() if folded else name
    seen: dict[tuple[str | None, int | None], None] = {}
    for row in rows:
        if (row.name.casefold() if folded else row.name) == want:
            seen[(row.file, row.line)] = None
    return tuple(seen)


def uses_of(names: Names, kind: str, name: str) -> int:
    """How many lines use entry ``kind`` ``name``, from the check's ``*_use`` rows."""
    return len(use_places(names, kind, name))


def delete_refusal(entry: Entry) -> str | None:
    """Design §6.4's refusal while ``entry`` is used, else None."""
    if entry.uses <= 0:
        return None
    return DELETE_REFUSED.format(name=entry.shown, lines=_lines(entry.uses))


# --- Lists -------------------------------------------------------------------------------------

def _first_place(rows: Iterable[NameRow], name: str) -> tuple[str, int] | None:
    for row in rows:
        if row.name == name and row.file is not None and row.line is not None:
            return row.file, row.line
    return None


def _decl_entries(kind: str, decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    out: list[Entry] = []
    seen: set[str] = set()
    for decl in decls:
        if decl.kind != kind or decl.name in seen:
            continue
        seen.add(decl.name)
        out.append(Entry(kind, decl.name, _shown(decl), decl.place,
                         decl.values is not None and kind in dec.EDITABLE_KINDS,
                         uses_of(names, kind, decl.name), decl))
    return out


def _shown(decl: dec.Decl) -> str:
    """The list text: a character's shown name, an entry's title, else the script name."""
    values = decl.values or {}
    key = dec.NAME if decl.kind == dec.CHARACTER else "title"
    shown = values.get(key)
    return shown if isinstance(shown, str) and shown else decl.name


def _merged(kind: str, decls: Iterable[dec.Decl], names: Names,
            row_kinds: Iterable[str]) -> list[Entry]:
    """``kind`` entries read from the texts (or marks), then the check's ``row_kinds``
    names the reader didn't find (read-only), sorted by shown name."""
    out = _decl_entries(kind, decls, names)
    known = {entry.name for entry in out}
    for row_kind in row_kinds:
        for row in names.get(row_kind, ()):
            if row.name not in known:
                known.add(row.name)
                out.append(Entry(kind, row.name, row.name, _first_place([row], row.name),
                                 False, uses_of(names, kind, row.name)))
    return sorted(out, key=lambda e: (e.shown.casefold(), e.name))


def meter_entries(decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Meters: ``points`` declarations (one entry per name), then the check's ``meter``
    names the reader didn't find."""
    return _merged(dec.METER, decls, names, ("meter",))


def codex_entries(decls: Iterable[dec.Decl], names: Names) -> dict[str, list[Entry]]:
    """Codex ▸ Tips and Items (``dec.TIP``, ``dec.ITEM``), each listed by title."""
    decls = list(decls)
    return {dec.TIP: _merged(dec.TIP, decls, names, ("tip",)),
            dec.ITEM: _merged(dec.ITEM, decls, names, ("item",))}


def codex_categories(decls: Iterable[dec.Decl], names: Names) -> tuple[str, ...]:
    """Every codex category the story names, for the Category field's choices."""
    found = {str(d.values["category"]) for d in decls if d.kind in (dec.TIP, dec.ITEM)
             and d.values is not None and d.values.get("category")}
    found.update(row.name for row in names.get("category", ()) if row.name)
    return tuple(sorted(found, key=str.casefold))


def route_entries(decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Endings & routes ▸ Routes: ``lock route`` declarations by title (editable), then the
    check's ``route`` names the reader didn't find."""
    return _merged(dec.ROUTE, decls, names, ("route",))


def ending_entries(marks: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Endings & routes ▸ Endings: every ``ending`` line (``declarations.marks``) with Go to,
    read-only; "used" by the routes waiting for it."""
    return _merged(dec.ENDING, marks, names, ("ending",))


def ending_names(marks: Iterable[dec.Decl], names: Names) -> tuple[str, ...]:
    """Every ending name, for a route's "locked until endings" multi-pick."""
    return tuple(sorted({e.name for e in ending_entries(marks, names)}, key=str.casefold))


def chapter_entries(marks: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Chapters: every ``chapter`` line (``declarations.marks``), read-only, in story order
    (ref, then line) with Go to and Play from here."""
    out = _merged(dec.CHAPTER, marks, names, ("chapter",))
    return sorted(out, key=lambda e: (e.place is None, e.place or ("", 0)))


def transition_entries(decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Transitions: ``define n = Dissolve/Fade/Mask(...)`` (editable when literal), then the
    check's defined transitions the reader didn't find; the built-ins (cut, dissolve,
    fade…) aren't entries."""
    defined = {"transition_defined": [row for row in names.get("transition", ())
                                      if row.file is not None]}
    return _merged(dec.TRANSITION, decls, {**names, **defined}, ("transition_defined",))


def remembered_entries(decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Variables remembered across playthroughs (``default persistent.<n>``), by name."""
    return _merged(dec.PERSISTENT, decls, names, ())


def position_entries(config_text: str, names: Names) -> list[Entry] | None:
    """Positions: the built-ins (left, center, right), then ``[stage.positions]`` in file
    order. ``values``: ``x``, ``y`` (None: Edit as script), ``builtin``, ``written``. None
    when config.toml isn't valid TOML."""
    rows = dec.position_rows(config_text)
    if rows is None:
        return None
    return [Entry(dec.POSITION, row.name, row.name, None, row.x is not None,
                  uses_of(names, dec.POSITION, row.name),
                  values={"x": row.x, "y": row.y, "builtin": row.builtin,
                          "written": row.written})
            for row in rows]


def character_entries(decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Characters read from the texts, then the check's ``character`` names the reader
    didn't find (shown read-only), sorted by shown name."""
    decls = list(decls)
    out = _decl_entries(dec.CHARACTER, decls, names)
    known = {entry.name for entry in out}
    for row in names.get("character", ()):
        if row.name not in known:
            known.add(row.name)
            out.append(Entry(dec.CHARACTER, row.name, row.name,
                             _first_place([row], row.name), False,
                             uses_of(names, dec.CHARACTER, row.name)))
    return sorted(out, key=lambda e: (e.shown.casefold(), e.name))


def variable_entries(decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Variables (``default``) read from the texts, then the check's ``variable`` names the
    reader didn't find, sorted by name."""
    decls = list(decls)
    out = _decl_entries(dec.VARIABLE, decls, names)
    known = {entry.name for entry in out}
    for row in names.get("variable", ()):
        if row.name not in known:
            known.add(row.name)
            out.append(Entry(dec.VARIABLE, row.name, row.name, _first_place([row], row.name),
                             False, uses_of(names, dec.VARIABLE, row.name)))
    return sorted(out, key=lambda e: e.name.casefold())


def variable_names(decls: Iterable[dec.Decl], names: Names) -> tuple[str, ...]:
    """Every story variable, for Set variable, If and Play options' pickers (AC-F47-14)."""
    return tuple(entry.name for entry in variable_entries(decls, names))


def background_entries(decls: Iterable[dec.Decl], names: Names) -> list[Entry]:
    """Pictures ▸ Backgrounds: colour backgrounds read from the texts (editable) and every
    other image named ``bg …`` in the check's ``image`` names (files), sorted by name."""
    decls = list(decls)
    out = _decl_entries(dec.COLOR, decls, names)
    known = {entry.name.casefold() for entry in out}
    for row in names.get("image", ()):
        words = row.name.split()
        if len(words) < 2 or words[0].casefold() != dec.BACKGROUND_TAG \
                or row.name.casefold() in known:
            continue
        known.add(row.name.casefold())
        out.append(Entry(BACKGROUND, row.name, row.name, _first_place([row], row.name),
                         False, uses_of(names, BACKGROUND, row.name)))
    return sorted(out, key=lambda e: e.name.casefold())


def looks_in(tag: str, image_names: Iterable[str],
             not_pictures: Container[str] = ()) -> tuple[str, ...]:
    """The looks of sprite ``tag`` among ``image_names``: the rest of each name that starts
    with it (``hana smile`` → ``smile``), sorted. F38's blink and talking frames
    (``hana smile_blink1``, ``spriteframes.frame_of``) are not looks and are left out;
    ``not_pictures`` are names known to be solid colours, which are never frames."""
    every = set(image_names)
    pictures = {name for name in every if name not in not_pictures}
    folded = tag.casefold()
    looks = {name.split(maxsplit=1)[1] for name in every
             if len(name.split()) > 1 and name.split()[0].casefold() == folded
             and frame_of(name, pictures) is None}
    return tuple(sorted(looks, key=str.casefold))


def looks_of(tag: str, names: Names) -> tuple[str, ...]:
    """The looks of sprite ``tag`` in the check's ``image`` names (``looks_in``: frames
    are left out, so the Events pickers don't offer them; F38 07 I-10)."""
    return looks_in(tag, (row.name for row in names.get("image", ())))


def sound_folder(ref: str) -> str:
    """Which Sounds group ``ref`` (relative to ``audio/``) is in."""
    head = ref.split("/", 1)[0].casefold() if "/" in ref else ""
    return head if head in SOUND_FOLDERS else OTHER_SOUNDS


def sound_entries(names: Names) -> dict[str, list[Entry]]:
    """Sounds by folder (``SOUND_FOLDERS``, then ``OTHER_SOUNDS``), each sorted."""
    groups: dict[str, list[Entry]] = {folder: [] for folder in (*SOUND_FOLDERS, OTHER_SOUNDS)}
    seen: set[str] = set()
    for row in names.get("audio", ()):
        if row.name in seen:
            continue
        seen.add(row.name)
        folder = sound_folder(row.name)
        groups[folder].append(Entry(SOUND, row.name, row.name.rsplit("/", 1)[-1], None,
                                    False, uses_of(names, SOUND, row.name), folder=folder))
    for entries in groups.values():
        entries.sort(key=lambda e: e.name.casefold())
    return groups


# --- Gallery (F34-W4) ----------------------------------------------------------------------------

_INCLUDE = re.compile(r'include[ \t]+"([^"\n]*)"')
MAIN_SCRIPT: Final = "script/main.vns"


def include_order(texts: Mapping[str, str]) -> tuple[str, ...]:
    """The script refs in the order the engine reads them: ``main.vns``, then each file's
    includes in line order, breadth first (``script/loader.py``); refs no include reaches
    come last, sorted."""
    order: list[str] = []
    queue = [MAIN_SCRIPT] if MAIN_SCRIPT in texts else []
    while queue:
        ref = queue.pop(0)
        if ref in order:
            continue
        order.append(ref)
        for line in texts.get(ref, "").split("\n"):
            match = _INCLUDE.match(line)
            if match is not None:
                found = f"script/{match.group(1).strip()}"
                if found in texts and found not in order:
                    queue.append(found)
    return (*order, *sorted(ref for ref in texts if ref not in order))


def gallery_entries(decls: Iterable[dec.Decl], texts: Mapping[str, str]) -> list[Entry]:
    """Gallery: every ``lock gallery`` declaration in gallery order (include order, then
    line; a picture declared twice is listed once). ``uses``: the ``lock|unlock gallery``
    lines naming its picture or a version (the lines a removal would break)."""
    rank = {ref: i for i, ref in enumerate(include_order(texts))}
    lines = dec.gallery_uses(texts)
    out: list[Entry] = []
    seen: set[str] = set()
    for decl in sorted((d for d in decls if d.kind == dec.GALLERY),
                       key=lambda d: (rank.get(d.ref, len(rank)), d.ref, d.first)):
        if decl.name in seen:
            continue
        seen.add(decl.name)
        pictures = {decl.name, *((decl.values or {}).get("versions") or ())}  # type: ignore[misc]
        uses = len({(ref, line) for name, ref, line, _u in lines if name in pictures})
        out.append(Entry(dec.GALLERY, decl.name, _shown(decl), decl.place,
                         decl.values is not None, uses, decl))
    return out


def track_entries(decls: Iterable[dec.Decl], texts: Mapping[str, str]) -> list[Entry]:
    """Music room: every ``lock track`` declaration in the room's order (include order, then
    line; a name declared twice is listed once). Nothing names a track in a label, so
    ``uses`` is 0 and Delete is never refused."""
    rank = {ref: i for i, ref in enumerate(include_order(texts))}
    out: list[Entry] = []
    seen: set[str] = set()
    for decl in sorted((d for d in decls if d.kind == dec.TRACK),
                       key=lambda d: (rank.get(d.ref, len(rank)), d.ref, d.first)):
        if decl.name in seen:
            continue
        seen.add(decl.name)
        out.append(Entry(dec.TRACK, decl.name, _shown(decl), decl.place,
                         decl.values is not None, 0, decl))
    return out


def gallery_pictures(decls: Iterable[dec.Decl]) -> dict[str, str]:
    """Every gallery picture (entry or version) → its entry's picture."""
    out: dict[str, str] = {}
    for decl in decls:
        if decl.kind == dec.GALLERY:
            out.setdefault(decl.name, decl.name)
            for version in (decl.values or {}).get("versions") or ():   # type: ignore[union-attr]
                out.setdefault(str(version), decl.name)
    return out


def search(entries: Iterable[Entry], text: str) -> list[Entry]:
    """The entries whose shown or script name holds ``text`` (any case)."""
    needle = text.strip().casefold()
    return [e for e in entries
            if not needle or needle in e.shown.casefold() or needle in e.name.casefold()]


__all__ = ["BACKGROUND", "CATEGORIES", "CATEGORY_CHAPTER", "CATEGORY_CHARACTER",
           "CATEGORY_CODEX", "CATEGORY_ENDING", "CATEGORY_GALLERY", "CATEGORY_METER", "CATEGORY_MUSIC_ROOM", "CATEGORY_PICTURE",
           "CATEGORY_POSITION", "CATEGORY_SOUND", "CATEGORY_TITLES", "CATEGORY_TRANSITION",
           "CATEGORY_VARIABLE", "CHAPTERS_HINT", "DELETE_REFUSED", "EDIT_AS_SCRIPT",
           "EMPTY_HINT", "EMPTY_THINGS", "EMPTY_TITLE", "ENDINGS_HINT", "Entry", "ITEMS",
           "NOT_USED", "NameRow", "Names", "OTHER_SOUNDS", "P2_CATEGORIES", "REMEMBERED",
           "SCRIPT_NAME", "SHOW_USES", "SOUND", "SOUND_FOLDERS", "SOUND_TITLES", "TIPS",
           "USED_IN", "USE_KINDS", "background_entries", "chapter_entries",
           "character_entries", "codex_categories", "codex_entries", "delete_refusal",
           "ending_entries", "ending_names", "gallery_entries",
           "gallery_pictures", "include_order", "looks_in", "looks_of", "meter_entries",
           "position_entries",
           "remembered_entries", "route_entries", "search", "sound_entries", "sound_folder",
           "track_entries", "transition_entries", "use_places", "used_text", "uses_of", "variable_entries",
           "variable_names"]
