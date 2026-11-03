"""The music room's tracks at run time (F35 ``SPEC.md`` §2 PR-F35-01, 02, §5.1; ``F36/07`` I-6).

Why this module exists: a ``lock track`` declaration lists a music file in the title's Music
Room, and the room shows it once it is open. Which tracks are open is decided here, once, for
the page (``ui/builtin/music_room_page.py``, through ``app``'s port) and for F34's Extras
entry (shown once a track is open):

- **Default rule**: the track opens the first time the story starts its file (F08's
  ``AudioService.on_track_started``: ``play music``, ``queue music``, a restored save's
  music; never a ``take_music`` holder's track) and stays open across playthroughs. The
  record is F12's unlock kind ``"track"`` keyed by the track's **name** (so its file can
  change without losing it), non-revocable, ``known`` = the declared names, and kept by
  F36's replay sandbox (``replay_keeps``, I-6).
- ``open``: always open; nothing is recorded.
- ``until e1, e2``: open while every named ending is reached (F19's ``"ending"`` kind, read
  at each call, so ``lock ending`` closes it again); nothing is recorded.

``TrackIndex`` keeps the declarations in declaration order (the page's order). Files compare
as F08 compares them: the ref ``"audio/" + file`` as written (``script.audio.audio_ref``;
the same-track rule and the reader use the written spelling, no second rule here).

The declaration node is F35 step 2's (``script/musicroom.py``'s ``TrackDecl``, in
``Program.tracks``); this module reads only the fields ``TrackDeclLike`` names. Pure
(TR-F03-05): no file, clock, randomness, or thread; nothing read from the persistent file is
logged or shown (records are lookup keys, SEC-F12-10).
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from engine.runtime.endings import ENDING_KIND
from engine.runtime.persistent import PersistentStore
from engine.script.audio import audio_ref

TRACK_KIND: Final = "track"            # F12 unlock kind (non-revocable, replay_keeps)

Rule = Literal["heard", "open", "until"]


class TrackDeclLike(Protocol):
    """What the index reads of a ``lock track`` declaration (F35 step 2's ``TrackDecl``):
    ``open`` True for ``open``; ``until`` the ending names as written (empty: none)."""

    @property
    def name(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def file(self) -> str: ...

    @property
    def open(self) -> bool: ...

    @property
    def until(self) -> Sequence[str]: ...


class TrackSource(Protocol):
    """A program with tracks in declaration order (``Program.tracks``, step 2)."""

    @property
    def tracks(self) -> Sequence[TrackDeclLike]: ...


@dataclass(frozen=True, slots=True)
class TrackInfo:
    """One declared track: its name (the record key), title and file as written, and its
    rule's data (``open``; ``until`` endings, () when none)."""

    name: str
    title: str
    file: str
    open: bool = False
    until: tuple[str, ...] = ()

    @property
    def rule(self) -> Rule:
        if self.open:
            return "open"
        return "until" if self.until else "heard"


class TrackIndex:
    """Every declared track in declaration order (immutable). Lookups take any value and
    give None/False/() for anything that isn't a track's name or file."""

    __slots__ = ("_items", "_by_name", "_by_file")

    def __init__(self, items: Sequence[TrackInfo]) -> None:
        self._items = tuple(items)
        self._by_name = {info.name: info for info in self._items}
        by_file: dict[str, list[TrackInfo]] = {}
        for info in self._items:
            by_file.setdefault(audio_ref(info.file), []).append(info)
        self._by_file = {key: tuple(found) for key, found in by_file.items()}

    @classmethod
    def build(cls, program: TrackSource) -> "TrackIndex":
        return cls(tuple(TrackInfo(d.name, d.title, d.file, bool(d.open), tuple(d.until))
                         for d in program.tracks))

    def __iter__(self) -> Iterator[TrackInfo]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, name: object) -> TrackInfo | None:
        return self._by_name.get(name) if type(name) is str else None

    def has(self, name: object) -> bool:
        """The ``"track"`` kind's ``known`` recognizer."""
        return type(name) is str and name in self._by_name

    def by_file(self, file: object) -> tuple[TrackInfo, ...]:
        """The tracks of ``file`` (as ``play music`` writes it), in declaration order: one
        after the whole-game checks (E337), () for a file no track lists."""
        return self._by_file.get(audio_ref(file), ()) if type(file) is str else ()

    def is_open(self, store: PersistentStore, track: "TrackInfo | str") -> bool:
        """PR-F35-02 (module docstring). False for anything that isn't a declared track."""
        info = self.get(track) if type(track) is str else track
        if not isinstance(info, TrackInfo) or self._by_name.get(info.name) is not info:
            return False
        if info.open:
            return True
        if info.until:
            return all(store.is_unlocked(ENDING_KIND, e) for e in info.until)
        return store.is_unlocked(TRACK_KIND, info.name)

    def open_tracks(self, store: PersistentStore) -> tuple[TrackInfo, ...]:
        """The open tracks in declaration order (F34's Extras entry shows when not empty),
        each kind read once."""
        heard = set(store.unlocked(TRACK_KIND))
        reached = set(store.unlocked(ENDING_KIND))
        return tuple(info for info in self._items
                     if info.open or (set(info.until) <= reached if info.until
                                      else info.name in heard))


def register(store: PersistentStore, program: TrackSource) -> TrackIndex:
    """The program's ``TrackIndex``, and the ``"track"`` kind on ``store`` (``known`` = the
    declared names; non-revocable; kept by F36's replay sandbox, I-6). Safe to repeat (F39
    with a new program: registering again replaces ``known``)."""
    index = TrackIndex.build(program)
    store.register_kind(TRACK_KIND, known=index.has, replay_keeps=True)
    return index


def heard(store: PersistentStore, index: TrackIndex, file: str) -> bool:
    """The story started ``file`` (``on_track_started``): each default-rule track of that
    file is recorded. True if any record is new. ``open``/``until`` tracks and files no
    track lists record nothing."""
    new = False
    for info in index.by_file(file):
        if info.rule == "heard" and store.unlock(TRACK_KIND, info.name):
            new = True
    return new


__all__ = ["Rule", "TRACK_KIND", "TrackDeclLike", "TrackIndex", "TrackInfo", "TrackSource",
           "heard", "register"]
