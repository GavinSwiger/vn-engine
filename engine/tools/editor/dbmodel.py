"""The Database's lists (F47 ``04-technical.md`` §3.1, §7.1; design §4.3, §6.2, §6.4,
PR-F47-02, PR-F47-05, PR-F47-10; AC-F47-08, 14, 15).

Why this module exists: each Database category is a list of entries with "Used in N lines"
and a Delete that is refused while the entry is used. The lists merge what
``declarations.scan`` reads from the texts (so a new author's characters show without a
launch check) with the last good check's name index (``CheckResult.names``: ``character``,
``image``, ``audio``, ``variable`` and the ``*_use`` rows of ``tools/check.py``). Pure: no Tk;
``names`` is any mapping of kind → rows with ``name``, ``file`` and ``line`` (``NameEntry``).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

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

# Entry kinds beyond declarations' (pictures and sounds are files, not declarations).
BACKGROUND: Final = "background"   # an image named bg …: a file, or a colour (dec.COLOR)
SOUND: Final = "sound"

# Which check rows count an entry's uses.
USE_KINDS: Final[Mapping[str, str]] = {
    dec.CHARACTER: "character_use", dec.COLOR: "image_use", BACKGROUND: "image_use",
    dec.VARIABLE: "variable_use", SOUND: "audio_use"}
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
        shown = decl.name
        if kind == dec.CHARACTER and decl.values is not None \
                and isinstance(decl.values.get(dec.NAME), str) and decl.values[dec.NAME]:
            shown = str(decl.values[dec.NAME])
        out.append(Entry(kind, decl.name, shown, decl.place, decl.values is not None,
                         uses_of(names, kind, decl.name), decl))
    return out


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


def looks_of(tag: str, names: Names) -> tuple[str, ...]:
    """The looks of sprite ``tag``: the rest of each image name that starts with it
    (``hana smile`` → ``smile``), sorted."""
    folded = tag.casefold()
    looks = {row.name.split(maxsplit=1)[1] for row in names.get("image", ())
             if len(row.name.split()) > 1 and row.name.split()[0].casefold() == folded}
    return tuple(sorted(looks, key=str.casefold))


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


def search(entries: Iterable[Entry], text: str) -> list[Entry]:
    """The entries whose shown or script name holds ``text`` (any case)."""
    needle = text.strip().casefold()
    return [e for e in entries
            if not needle or needle in e.shown.casefold() or needle in e.name.casefold()]


__all__ = ["BACKGROUND", "CATEGORIES", "CATEGORY_CHARACTER", "CATEGORY_PICTURE",
           "CATEGORY_SOUND", "CATEGORY_VARIABLE", "DELETE_REFUSED", "EDIT_AS_SCRIPT",
           "EMPTY_HINT", "EMPTY_TITLE", "Entry", "NOT_USED", "NameRow", "Names",
           "OTHER_SOUNDS", "SCRIPT_NAME", "SHOW_USES", "SOUND", "SOUND_FOLDERS",
           "SOUND_TITLES", "USED_IN", "USE_KINDS", "background_entries", "character_entries",
           "delete_refusal", "looks_of", "search", "sound_entries", "sound_folder",
           "use_places", "used_text", "uses_of", "variable_entries", "variable_names"]
