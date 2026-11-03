"""The loaded story: ``Program`` and its lookups (F02 ``04-technical.md`` §4.2).

A ``Program`` is static content, like an image: rebuilt from the script files at every
launch, immutable once built, never saved, and not part of ``GameState``. Saved data reaches
it only through ``get``, ``location``, ``label``, ``at``, and ``statements_in``
(SEC-F02-10): they accept any JSON value, check its type before any dict access, do one
whole-string lookup (``~n`` is never parsed), and return ``None`` or nothing instead of
raising.

Later features add fields to ``Program`` (F04 ``images``, ...) as keyword fields with
defaults, filled in by ``iter_build_program``'s caller or by this builder. F03 added
``defaults`` (evaluation order), ``define_names`` and ``default_names`` (derived from
``defines`` and ``defaults``), and ``speakers`` (the first dialogue line of each speaker).
F04 added ``images``: the ``image`` declarations by name, in reading order. F12 added
``persistent_defaults`` (reading order, which is their evaluation order), the derived
``persistent_default_names``, and from the bindings pass ``persistent_reads`` (each read
name's first use, ``(file ref, line)``) and ``persistent_writes`` (names set or deleted).
F22 added ``meters``: every declared meter's ``MeterSpec``, include order, then line.
F19 added ``endings`` (every ``Ending`` statement, include order, then line) and ``routes``
(every ``RouteDecl``, reading order). F21 added ``codex`` (every declared tip and item as a
``CodexEntry``, include order, then line) and ``codex_categories`` (first-declaration order).
F20 added ``flow_marks`` (each ``flowchart`` mark by its target's sid: the marked ``menu:``,
``chapter``, or ``ending``, or for a scene mark its label's first statement, the mark itself)
and ``flowgraph`` (the graph of load phase 6, None when ``[flowchart]`` is off or not asked
for; ``script/flowgraph.py``). F30 added ``username_fallback`` (``[meta] username_fallback``
through ``LoadOptions``: what ``{username}`` holds in the story) and ``window_titles`` (every
``effect window_title`` text, the titles a save may restore, ``07`` I-7). F32 added
``style_names`` (``LoadOptions.style_names``: the config's ``[style.<name>]`` names, which a
restored ``ui style`` must be one of, W205; None when the load had no config). F31 added
``meta_files`` (every ``file`` line's name; the runtime's executor asserts its name is one).
F34 added ``gallery`` (every ``lock gallery`` declaration as a ``GalleryEntry``, include order,
then line) and ``gallery_pictures`` (every entry picture and version → its entry's picture).
F35 added ``tracks`` (every ``lock track`` declaration as a ``Track``, reading order).
F36 added ``replays`` (every ``lock replay`` declaration as a ``ReplayEntry``, reading order).
F37 added ``achievements`` (every ``lock achievement`` declaration, reading order).
"""

import time
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from engine.script.achievements import AchievementDecl
from engine.script.codex import CodexCategory, CodexEntry, CodexEntryDecl, build_entries
from engine.script.fourthwall import TitleEffect
from engine.script.gallery import GalleryDecl, GalleryEntry, build_gallery
from engine.script.identity import IDENTITY_SCHEME, IDENTITY_YIELD_ITEMS, iter_assign, walk_block
from engine.script.metafiles import MetaFile
from engine.script.musicroom import Track, TrackDecl, build_tracks
from engine.script.nodes import (Default, Define, Label, Node, PersistentDefault, Say,
                                 ScriptFile, Statement)
from engine.script.points import MeterSpec, PointsDecl
from engine.script.replay import ReplayDecl, ReplayEntry, build_replays
from engine.script.routes import Ending, RouteDecl
from engine.script.stage import ImageDecl

if TYPE_CHECKING:
    from engine.script.flowchart import FlowMark
    from engine.script.flowgraph import FlowGraph


@dataclass(slots=True, frozen=True)
class StmtLocation:
    """Where a statement sits: ``path`` ``(i,)`` is ``label.block[i]``; ``(i, b, j)`` is
    ``block[i].blocks()[b][j]`` (an ``If`` branch; F07, a menu choice); and so on."""

    label: str
    path: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class LoadStats:
    """PR-F02-40's numbers. ``statements`` counts ``Statement``s inside labels; ``words`` is
    ``len(text.split())`` summed over ``Say``; ``seconds`` is the load's wall time."""

    files: int
    labels: int
    statements: int
    words: int
    seconds: float


def _no_statements() -> Iterator[Statement]:
    return iter(())


@dataclass(slots=True, frozen=True, kw_only=True, eq=False)
class Program:
    """An immutable, pygame-free story (docs/architecture.md "Script program").

    F03: ``defaults`` in evaluation order (SR-F03-03); ``define_names`` and
    ``default_names`` are always derived from ``defines`` and ``defaults``; ``speakers``
    maps each speaker to its first dialogue line in reading order (read-only; built from
    the labels when not given).

    F04: ``images`` maps each declared image name to its ``ImageDecl`` (``name``, ``ref``,
    ``color``), in reading order (read-only; names are unique, E133). The image index reads
    it at launch; ``Program.get`` never returns a declaration.

    F12: ``persistent_defaults`` in reading order (phase 2b's order); ``persistent_reads``
    maps each ``persistent.<name>`` read to its first use ``(file ref, line)`` in reading
    order; ``persistent_writes`` holds the names set or deleted anywhere (both read-only;
    defines, defaults, choice conditions, and nested code count).

    F22: ``meters`` holds every declared meter's ``MeterSpec`` in include order, then line
    (names unique, E231; at most 200, E235).

    F19: ``endings`` holds every ``Ending`` statement in include order, then line (names
    unique, E241; at most 1,000, E246); ``routes`` every ``RouteDecl`` in reading order
    (names unique labels, E241, E243; at most 1,000, E246).

    F21: ``codex`` holds every declared tip and item in include order, then line (names
    unique across both kinds, E251; at most 1,000 of each, E254); ``codex_categories`` the
    categories in first-declaration order (at most 24, E254).

    F20: ``flow_marks`` maps each mark's target sid to its ``FlowMark`` (read-only);
    ``flowgraph`` is load phase 6's ``FlowGraph``, or None.

    F30: ``username_fallback`` is the word ``{username}`` resolves to in the story (history,
    saves, goldens; the real name is only drawn); ``window_titles`` holds the shown text of
    every ``effect window_title "…"``, so a restore uses a saved title only if this script
    writes it (SEC-F30-09, ``07`` I-7).

    F31: ``meta_files`` holds the name of every ``file`` line (at most 32, E314).

    F34: ``gallery`` holds every gallery entry in include order, then line (at most 500,
    E343); ``gallery_pictures`` maps every entry picture and version to its entry's picture
    (read-only; a picture is in the gallery once, E343).

    F35: ``tracks`` holds every music-room track in reading order (names and files unique,
    E337; at most 200, E337).

    F36: ``replays`` holds every scene replay in reading order (one per scene, at most 500,
    E349), each with its tile picture (PR-F36-07).

    F37: ``achievements`` holds every ``lock achievement`` declaration in reading order (names
    unique, at most 200, E340), each with its ``when`` compiled once (``when_code``)."""

    files: tuple[ScriptFile, ...]                 # reading order
    labels: Mapping[str, Label]                   # read-only, reading order
    defines: tuple[Define, ...]                   # evaluation order (§7.6.4)
    stats: LoadStats
    identity_scheme: int = IDENTITY_SCHEME
    defaults: tuple[Default, ...] = ()            # F03: evaluation order (SR-F03-03)
    speakers: Mapping[str, Say] = None            # type: ignore[assignment]  # F03, see above
    images: Mapping[str, ImageDecl] = field(       # F04, see above
        default_factory=lambda: MappingProxyType({}))
    persistent_defaults: tuple[PersistentDefault, ...] = ()   # F12, see above
    persistent_reads: Mapping[str, tuple[str, int]] = field(   # F12, see above
        default_factory=lambda: MappingProxyType({}))
    persistent_writes: frozenset[str] = frozenset()            # F12, see above
    meters: tuple[MeterSpec, ...] = ()                         # F22, see above
    endings: tuple[Ending, ...] = ()                           # F19, see above
    routes: tuple[RouteDecl, ...] = ()                         # F19, see above
    codex: tuple[CodexEntry, ...] = ()                         # F21, see above
    codex_categories: tuple[CodexCategory, ...] = ()           # F21, see above
    flow_marks: "Mapping[str, FlowMark]" = field(              # F20, see above
        default_factory=lambda: MappingProxyType({}))
    flowgraph: "FlowGraph | None" = None                       # F20, see above
    username_fallback: str = "friend"                          # F30, see above
    window_titles: frozenset[str] = frozenset()                # F30, see above
    style_names: frozenset[str] | None = None                  # F32, see the module
    meta_files: frozenset[str] = frozenset()                   # F31, see above
    gallery: tuple[GalleryEntry, ...] = ()                     # F34, see above
    gallery_pictures: Mapping[str, str] = field(               # F34, see above
        default_factory=lambda: MappingProxyType({}))
    tracks: tuple[Track, ...] = ()                             # F35, see above
    replays: tuple[ReplayEntry, ...] = ()                      # F36, see above
    achievements: tuple[AchievementDecl, ...] = ()             # F37, see above
    define_names: frozenset[str] = field(default=frozenset(), init=False)
    default_names: frozenset[str] = field(default=frozenset(), init=False)
    persistent_default_names: frozenset[str] = field(default=frozenset(), init=False)
    _index: Mapping[str, Statement] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        labels = self.labels
        if not isinstance(labels, MappingProxyType):
            object.__setattr__(self, "labels", MappingProxyType(dict(labels)))
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "defines", tuple(self.defines))
        object.__setattr__(self, "defaults", tuple(self.defaults))
        if not isinstance(self.images, MappingProxyType):
            object.__setattr__(self, "images", MappingProxyType(dict(self.images)))
        object.__setattr__(self, "define_names", frozenset(d.name for d in self.defines))
        object.__setattr__(self, "default_names", frozenset(d.name for d in self.defaults))
        object.__setattr__(self, "persistent_defaults", tuple(self.persistent_defaults))
        object.__setattr__(self, "persistent_default_names",
                           frozenset(d.name for d in self.persistent_defaults))
        if not isinstance(self.persistent_reads, MappingProxyType):
            object.__setattr__(self, "persistent_reads",
                               MappingProxyType(dict(self.persistent_reads)))
        object.__setattr__(self, "persistent_writes", frozenset(self.persistent_writes))
        object.__setattr__(self, "meta_files", frozenset(self.meta_files))
        object.__setattr__(self, "meters", tuple(self.meters))
        object.__setattr__(self, "endings", tuple(self.endings))
        object.__setattr__(self, "routes", tuple(self.routes))
        object.__setattr__(self, "codex", tuple(self.codex))
        object.__setattr__(self, "codex_categories", tuple(self.codex_categories))
        object.__setattr__(self, "gallery", tuple(self.gallery))
        object.__setattr__(self, "tracks", tuple(self.tracks))
        object.__setattr__(self, "replays", tuple(self.replays))
        object.__setattr__(self, "achievements", tuple(self.achievements))
        if not isinstance(self.gallery_pictures, MappingProxyType):
            object.__setattr__(self, "gallery_pictures",
                               MappingProxyType(dict(self.gallery_pictures)))
        if not isinstance(self.flow_marks, MappingProxyType):
            object.__setattr__(self, "flow_marks", MappingProxyType(dict(self.flow_marks)))
        speakers = self.speakers
        if self._index is None or speakers is None:
            index: dict[str, Statement] = {}
            found: dict[str, Say] = {}
            for node in self.labels.values():
                for stmt, _ in walk_block(node.block):
                    index[stmt.sid] = stmt
                    if isinstance(stmt, Say) and stmt.speaker is not None:
                        found.setdefault(stmt.speaker, stmt)
            if self._index is None:
                object.__setattr__(self, "_index", index)
            if speakers is None:
                speakers = found
        if not isinstance(speakers, MappingProxyType):
            object.__setattr__(self, "speakers", MappingProxyType(dict(speakers)))

    # Lookups for saved data (SEC-F02-10) --------------------------------------------------

    def get(self, sid: object) -> Statement | None:
        """The statement with exactly this identity. Never a label, define, or include."""
        if type(sid) is not str:
            return None
        return self._index.get(sid)  # type: ignore[union-attr]

    def location(self, sid: object) -> StmtLocation | None:
        stmt = self.get(sid)
        return None if stmt is None else StmtLocation(stmt.label, stmt.path)

    def label(self, name: object) -> Label | None:
        if type(name) is not str:
            return None
        return self.labels.get(name)

    def at(self, label: object, path: object) -> Statement | None:
        """The statement at ``path`` in ``label`` (a ``StmtLocation`` from saved data).
        Walks only ``Label.block`` and each statement's ``blocks()`` (``If`` branches, F07
        ``Menu`` choices); every index must be an ``int`` (not ``bool``) in range, checked
        before it is used."""
        if type(label) is not str or (type(path) is not tuple and type(path) is not list):
            return None
        node = self.labels.get(label)
        size = len(path)  # type: ignore[arg-type]
        if node is None or size == 0:
            return None
        block = node.block
        k = 0
        while True:
            i = path[k]  # type: ignore[index]
            if type(i) is not int or not 0 <= i < len(block):
                return None
            stmt = block[i]
            k += 1
            if k == size:
                return stmt
            if k + 1 >= size:
                return None
            blocks = stmt.blocks()
            b = path[k]  # type: ignore[index]
            if type(b) is not int or not 0 <= b < len(blocks):
                return None
            block = blocks[b]
            k += 1

    def statements_in(self, label: object) -> Iterator[Statement]:
        """The label's statements in pre-order; empty for anything but a label name."""
        node = self.label(label)
        if node is None:
            return _no_statements()
        return (stmt for stmt, _ in walk_block(node.block))

    def iter_statements(self) -> Iterator[Statement]:
        """Every statement: labels in reading order, each in pre-order."""
        for node in self.labels.values():
            for stmt, _ in walk_block(node.block):
                yield stmt


def iter_build_program(files: Sequence[ScriptFile], nodes: Iterable[Node], *,
                       defines: Sequence[Define] | None = None,
                       defaults: Sequence[Default] | None = None,
                       started: float | None = None,
                       clock: Callable[[], float] = time.perf_counter,
                       persistent_reads: Mapping[str, tuple[str, int]] | None = None,
                       persistent_writes: Iterable[str] = (),
                       flow_marks: Iterable[tuple[Node, "FlowMark"]] = (),
                       username_fallback: str = "friend",
                       style_names: frozenset[str] | None = None,
                       ) -> Generator[None, None, Program]:
    """The last phase of a load (§7.8, step 4 of §1's pipeline): assign identities, index
    the statements, and build the ``Program``. Yields every ``IDENTITY_YIELD_ITEMS``
    statements; the loader uses ``program = yield from iter_build_program(...)``.

    ``files`` and ``nodes`` (every file's top-level nodes) are in reading order and come
    from a load whose whole-game checks passed (label names unique). ``defines`` is the
    evaluation order from the define-order check (default: reading order); ``defaults``
    the same for F03's defaults. ``started`` is the clock value at the first script read,
    for ``LoadStats.seconds``. F12: the persistent defaults come from ``nodes`` in reading
    order; ``persistent_reads`` and ``persistent_writes`` from the bindings pass. F20:
    ``flow_marks`` are the checks' ``(target, FlowMark)`` pairs, keyed here by sid. F30:
    ``username_fallback`` from ``LoadOptions``; ``window_titles`` from the statements. F32:
    ``style_names`` from ``LoadOptions``. F31: ``meta_files`` from the statements.
    """
    nodes = list(nodes)
    labels: dict[str, Label] = {}
    images: dict[str, ImageDecl] = {}
    persistent_defaults: list[PersistentDefault] = []
    meters: list[MeterSpec] = []
    routes: list[RouteDecl] = []
    endings: list[Ending] = []
    decls: list[CodexEntryDecl] = []
    gallery_decls: list[GalleryDecl] = []
    track_decls: list[TrackDecl] = []
    replay_decls: list[ReplayDecl] = []
    achievement_decls: list[AchievementDecl] = []
    for node in nodes:
        if isinstance(node, Label):
            labels.setdefault(node.name, node)
        elif isinstance(node, ImageDecl):
            images.setdefault(node.name, node)
        elif isinstance(node, PersistentDefault):
            persistent_defaults.append(node)
        elif isinstance(node, PointsDecl):                  # F22: reading order
            meters.extend(node.specs())
        elif isinstance(node, RouteDecl):                   # F19: reading order
            routes.append(node)
        elif isinstance(node, CodexEntryDecl):              # F21: reading order
            decls.append(node)
        elif isinstance(node, GalleryDecl):                 # F34: reading order
            gallery_decls.append(node)
        elif isinstance(node, TrackDecl):                   # F35: reading order
            track_decls.append(node)
        elif isinstance(node, ReplayDecl):                  # F36: reading order
            replay_decls.append(node)
        elif isinstance(node, AchievementDecl):             # F37: reading order
            achievement_decls.append(node)
    if defines is None:
        defines = [node for node in nodes if isinstance(node, Define)]
    if defaults is None:
        defaults = [node for node in nodes if isinstance(node, Default)]
    yield from iter_assign(nodes)
    index: dict[str, Statement] = {}
    speakers: dict[str, Say] = {}
    titles: set[str] = set()
    meta_files: set[str] = set()
    statements = words = 0
    for node in labels.values():
        for stmt, _ in walk_block(node.block):
            index[stmt.sid] = stmt
            statements += 1
            if isinstance(stmt, Say):
                words += len(stmt.text.split())
                if stmt.speaker is not None and stmt.speaker not in speakers:
                    speakers[stmt.speaker] = stmt
            elif isinstance(stmt, Ending):                  # F19: include order, then line
                endings.append(stmt)
            elif isinstance(stmt, TitleEffect) and stmt.text is not None:       # F30
                titles.add(stmt.text)
            elif isinstance(stmt, MetaFile):                # F31
                meta_files.add(stmt.name)
            if statements % IDENTITY_YIELD_ITEMS == 0:
                yield
    codex, codex_categories = build_entries(decls)        # F21: after the sids
    gallery, gallery_pictures = build_gallery(gallery_decls)    # F34: after the sids
    tracks = build_tracks(track_decls)                          # F35: after the sids
    replays = build_replays(replay_decls, labels)               # F36: after the sids
    marks = {_mark_sid(target): mark for target, mark in flow_marks}    # F20: after the sids
    seconds = 0.0 if started is None else max(0.0, clock() - started)
    stats = LoadStats(files=len(files), labels=len(labels), statements=statements,
                      words=words, seconds=seconds)
    return Program(files=tuple(files), labels=MappingProxyType(labels),
                   defines=tuple(defines), stats=stats, defaults=tuple(defaults),
                   speakers=MappingProxyType(speakers), images=MappingProxyType(images),
                   persistent_defaults=tuple(persistent_defaults),
                   persistent_reads=MappingProxyType(dict(persistent_reads or {})),
                   persistent_writes=frozenset(persistent_writes), meters=tuple(meters),
                   endings=tuple(endings), routes=tuple(routes), codex=codex,
                   codex_categories=codex_categories, flow_marks=MappingProxyType(marks),
                   username_fallback=username_fallback, window_titles=frozenset(titles),
                   style_names=style_names, meta_files=frozenset(meta_files),
                   gallery=gallery, gallery_pictures=gallery_pictures, tracks=tracks,
                   replays=replays, achievements=tuple(achievement_decls),
                   _index=index)


def _mark_sid(target: Node) -> str:
    """F20: a mark's key. A scene mark's target is its ``Label``: the key is the label's first
    statement (the scene mark itself, the node's anchor)."""
    if isinstance(target, Label):
        return target.block[0].sid
    return target.sid


def build_program(files: Sequence[ScriptFile], nodes: Iterable[Node], *,
                  defines: Sequence[Define] | None = None,
                  defaults: Sequence[Default] | None = None, started: float | None = None,
                  clock: Callable[[], float] = time.perf_counter,
                  persistent_reads: Mapping[str, tuple[str, int]] | None = None,
                  persistent_writes: Iterable[str] = (),
                  flow_marks: Iterable[tuple[Node, "FlowMark"]] = (),
                  username_fallback: str = "friend") -> Program:
    """``iter_build_program`` run to the end in one go."""
    job = iter_build_program(files, nodes, defines=defines, defaults=defaults,
                             started=started, clock=clock, persistent_reads=persistent_reads,
                             persistent_writes=persistent_writes, flow_marks=flow_marks,
                             username_fallback=username_fallback)
    while True:
        try:
            next(job)
        except StopIteration as stop:
            return stop.value


__all__ = ["LoadStats", "Program", "StmtLocation", "build_program", "iter_build_program"]
