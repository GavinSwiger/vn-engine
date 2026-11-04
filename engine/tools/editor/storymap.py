"""The story map's layout and keyboard navigation (F45 ``04-technical.md`` §5, §7.7;
PR-F45-18, PR-F45-19, UI-F45-06, design §6.2).

Pure Python, no Tk: ``layout`` turns the last good check's label links and label names into
boxes and edges at canvas positions, and the window draws them. Deterministic and iterative
(TR-F45-08): equal inputs give equal layouts, and depth costs no recursion.

- **Columns** are the breadth-first distance from ``start`` over every link kind. Labels it
  doesn't reach share one last column. **Rows** follow program order (the order of
  ``labels``) within each column. A box sits at ``(COLUMN_STEP·column, ROW_STEP·row)``.
- At most ``max_boxes`` boxes are kept, the first by (column, row); ``hidden`` counts the
  rest and no edge touches a dropped box.
- **Marks** (PR-F45-19): ``start``; ``not reached``; ``ends``, a label with no outgoing
  ``jump`` or ``menu`` link, unless only ``call`` links reach it (it returns to its caller,
  ``07`` I-9).
- ``file=`` shows one file's labels. Columns and marks still come from the whole story;
  rows are counted among the shown labels.
- **Notes** (2026-11-02, AC-F45-51): ``label_notes`` places the check child's ``chapter``,
  ``ending`` and ``minigame_use`` rows in the label that holds their line (the nearest
  label line above, same file). A box shows its chapter and minigames; a label with an
  ``ending`` line is marked ``ending`` and drawn as an end box. F20 s2 (2026-11-02,
  AC-F45-61): a ``flowchart_scene`` row (the scene mark, the label's first line) gives the
  box its Flowchart scene title. F32 (AC-F32-25): a ``ui_delete`` row (a ``ui delete
  saves`` line) marks its label ``deletes saves``.
- F41 P4 (04 §7.4, PR-F41-07): a ``replay_scene`` row (a ``lock replay`` scene's label, read
  by name) is a starting point besides ``start``: it and what it leads to aren't marked
  ``not reached``, and its box is marked ``replay``. Columns stay the distance from ``start``.
- ``neighbour`` is the arrow keys (the nearest box in a 90° cone); ``targets`` and
  ``cycle_target`` are Tab (the focused box's outgoing edges, in link order).
- F46 (``04`` §3.4, §6.1.7, §6.4): an edge carries its first link's ``choice`` text and
  ``conditional`` flag, which the map draws as a chip (``chip_text``: 24 characters, then
  "…") and an "if" mark. ``stale=`` names the scenes whose text doesn't parse now (Studio
  keeps their last links); their boxes are marked ``out of date``.
- F46 places (``04`` §6.8, AC-F46-24): ``places=`` keeps author-placed corners; with any
  places, each other shown box (label order) goes to ``place_free`` near a spot 220 px right
  of the first placed box linking to it, else near its F45 cell. Placed boxes never move,
  and box order (and so box indexes) doesn't depend on places.
- F46 routing: ``out_edges`` are a box's edges by target y; each leaves at
  ``y0 + h·(k+1)/(n+1)`` (``edge_line``). A choice edge's ``slot`` is its chip's t along
  the drawn curve (``curve_points``, ``curve_at``: the window draws the same curve), the
  first of ``CHIP_SLOTS`` whose chip overlaps no box or earlier chip, else 0.5; the chip's
  size is estimated from its characters (``chip_size``), so no text is measured. ``chip_slot``
  and ``RectHash`` re-slot a chip when the window drags a box.
- F46 map undo (``04`` §6.9, TR-F46-05): ``MapStep`` / ``MapHistory`` (100 steps plus a redo
  list); ``map_undo`` checks each step file's edit token, then runs the records'
  ``edit_undo``/``edit_redo``.
- F58 live map (``04`` §7.6, §7.7; ``07`` I-8, I-9): ``relayout`` is the incremental layout
  (``layout`` is ``relayout`` with nothing to reuse, so they agree by construction): pins
  (automatically placed boxes, kept by the window) count as places; only boxes with neither
  are placed; chips are re-slotted only where a changed area meets their tried spots
  (``ChipSlots``); it returns a ``LayoutDiff`` by label name and ``EdgeKey``. Each curve's
  length table is built once (``curve_at`` bisects it). Ports, end heights and ``out_edges``
  are computed once per layout, and the chip's row-gap fallback is here (``Edge.lift``,
  ``chip_center``), so the view never measures or queries the canvas to place a chip.
  ``MapStep.pins`` carries Tidy up's pins.

``links`` are ``LabelLink`` objects or ``(src, dst, kind, file, line[, choice, cond])``
rows; ``labels`` are ``NameEntry`` objects, ``(name, file, line)`` rows, or plain names.
"""

import bisect
import heapq
import math
import unicodedata
from collections import deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, Protocol

from engine.script.labelgraph import LabelLink
from engine.script.messages import show

BOX_WIDTH: Final = 160
BOX_HEIGHT: Final = 40
COLUMN_STEP: Final = 220
ROW_STEP: Final = 60
MAX_BOXES: Final = 1_500
START_LABEL: Final = "start"
MARK_START: Final = "start"
MARK_NOT_REACHED: Final = "not reached"
MARK_ENDS: Final = "ends"
MARK_ENDING: Final = "ending"                   # the label holds an ``ending`` line (F19)
MARK_OUT_OF_DATE: Final = "out of date"         # F46: the scene's text doesn't parse now
MARK_DELETES_SAVES: Final = "deletes saves"     # F32: the label holds ``ui delete saves``
MARK_REPLAY: Final = "replay"                   # F41: a scene replay starts here
CHIP_CHARS: Final = 24                          # F46: a choice chip's characters before "…"
LINK_KINDS: Final = ("jump", "call", "menu")
_ENDING_LINKS = frozenset({"jump", "menu"})     # a label with none of these ends the story
DIRECTIONS: Final = ("left", "right", "up", "down")
PLACE_MARGIN: Final = 20                        # F46: free space kept around a placed box
PLACE_STEP: Final = 20                          # F46: place_free's ring step (and the snap)
PLACE_TRIES: Final = 2_000                      # F46: spots place_free tries before the row
CHIP_SLOTS: Final = (0.5, 0.35, 0.65, 0.2, 0.8)  # F46: a chip's t along its arrow, in order
CHIP_CHAR_PX: Final = 6                         # F46: estimated chip width per character
CHIP_PAD: Final = 8                             # F46: chip padding, each side
CHIP_HEIGHT: Final = 18
MAP_UNDO_STEPS: Final = 100                     # F46: map history steps kept
UNDO_BLOCKED: Final = "`{file}` was changed after this. Undo it in the text (Ctrl+Z there)."

Places = Mapping[str, tuple[int, int]]          # label → corner at 100% zoom, logical px
PinSets = Mapping[str | None, Places]           # F58: file-filter choice → its pins
Rect = tuple[float, float, float, float]        # x0, y0, x1, y1


@dataclass(frozen=True, slots=True)
class Box:
    """One label: its name, ``file:line``, grid place, canvas corner, and marks."""

    name: str
    file: str | None
    line: int | None
    column: int
    row: int
    x: int
    y: int
    marks: tuple[str, ...] = ()
    chapter: str | None = None                  # the first chapter line's name in the label
    minigames: tuple[str, ...] = ()             # minigame names, in line order
    scene: str | None = None                    # F20: the label's Flowchart scene title


@dataclass(frozen=True, slots=True)
class Notes:
    """What a label holds besides links: its first chapter, endings, minigames, and (F20)
    its Flowchart scene title."""

    chapter: str | None = None
    endings: tuple[str, ...] = ()
    minigames: tuple[str, ...] = ()
    scene: str | None = None
    deletes_saves: bool = False                 # F32: a ``ui delete saves`` line
    replay: bool = False                        # F41: a scene replay (F36) starts here


@dataclass(frozen=True, slots=True)
class Edge:
    """An arrow from box ``src`` to box ``dst`` (indexes into ``MapLayout.boxes``), with
    its first link's choice text and condition flag, and its chip's t along ``edge_curve``
    (F46). ``lift`` (F58, the row-gap fallback moved here from the view, ``07`` I-8): the
    chip's centre y at 100 % when no slot along the curve is free and it sits in the row gap
    below or above the boxes instead; None otherwise."""

    src: int
    dst: int
    kind: str
    choice: str | None = None
    conditional: bool = False
    slot: float = 0.5
    lift: float | None = None


EdgeKey = tuple[str, str, str]                  # F58: (source label, target label, kind)


@dataclass(frozen=True, slots=True)
class MapLayout:
    """``boxes`` sorted by (column, row); ``edges`` in link order, one per (src, dst, kind);
    ``hidden`` labels past the box cap; ``width``/``height`` the drawing's extent at 100%.

    F58 (``04`` §7.6), not compared: ``by_name`` (label → box index, so ``index_of`` is
    O(1)); ``outs`` (box → its ``out_edges``, the ports top to bottom); ``ports`` (edge →
    ``(k, n)``: the k-th of n out edges); ``ends`` (edge → its end height when several
    arrows join the same two boxes); ``chips``, the chip cache ``relayout`` reuses."""

    boxes: tuple[Box, ...]
    edges: tuple[Edge, ...]
    hidden: int
    width: int
    height: int
    by_name: Mapping[str, int] = field(default_factory=dict, compare=False, repr=False)
    outs: Mapping[int, tuple[int, ...]] | None = field(default=None, compare=False,
                                                         repr=False)
    ports: tuple[tuple[int, int], ...] = field(default=(), compare=False, repr=False)
    ends: Mapping[int, float] | None = field(default=None, compare=False, repr=False)
    chips: "ChipSlots | None" = field(default=None, compare=False, repr=False)
    chip_version: int = field(default=-1, compare=False, repr=False)
    edge_keys: Mapping[EdgeKey, int] | None = field(default=None, compare=False, repr=False)
    sigs: tuple[tuple, ...] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.by_name and self.boxes:
            object.__setattr__(self, "by_name",
                               {box.name: i for i, box in enumerate(self.boxes)})
        ends_of = [(e.src, e.dst) for e in self.edges]
        if self.outs is None or len(self.ports) != len(self.edges):
            outs, ports = _ports(self.boxes, ends_of)
            object.__setattr__(self, "outs", outs)
            object.__setattr__(self, "ports", ports)
        if self.ends is None:
            object.__setattr__(self, "ends", _ends(ends_of))
        if self.edge_keys is None:
            names = [box.name for box in self.boxes]
            object.__setattr__(self, "edge_keys", {
                (names[e.src], names[e.dst], e.kind): i for i, e in enumerate(self.edges)})
        if self.sigs is None:
            object.__setattr__(self, "sigs", tuple(
                _sig(self.boxes, e.src, e.dst, self.ports[i], self.ends.get(i))
                for i, e in enumerate(self.edges)))

    def index_of(self, name: str) -> int | None:
        """The box for label ``name``, or None when it isn't shown."""
        found = self.by_name.get(name)
        if found is None and not self.by_name and self.boxes:   # pragma: no cover
            return next((i for i, b in enumerate(self.boxes) if b.name == name), None)
        return found

    def edge_key(self, index: int) -> EdgeKey:
        """Edge ``index`` by label names: ``(source, target, kind)`` (F58's registry key)."""
        edge = self.edges[index]
        return self.boxes[edge.src].name, self.boxes[edge.dst].name, edge.kind


def _label_row(entry: object) -> tuple[str, str | None, int | None]:
    if isinstance(entry, str):
        return entry, None, None
    name = getattr(entry, "name", None)
    if name is not None:
        return name, getattr(entry, "file", None), getattr(entry, "line", None)
    name, file, line = entry  # type: ignore[misc]
    return name, file, line


def _link_row(link: object) -> tuple[str, str, str, str | None, bool]:
    src = getattr(link, "src", None)
    if src is not None:
        return (src, link.dst, link.kind,  # type: ignore[attr-defined]
                getattr(link, "choice", None), getattr(link, "conditional", False))
    row = tuple(link)  # type: ignore[call-overload]
    choice, cond = row[5:7] if len(row) >= 7 else (None, False)
    return row[0], row[1], row[2], choice, cond


def chip_text(choice: str | None) -> str:
    """A choice arrow's chip: the first ``CHIP_CHARS`` characters, then "…" when cut;
    ``""`` for an arrow that isn't from a choice."""
    if not choice:
        return ""
    return choice if len(choice) <= CHIP_CHARS else choice[:CHIP_CHARS] + "…"


def label_notes(labels: Iterable[object],
                names: Mapping[str, Iterable[object]]) -> dict[str, Notes]:
    """Label name → ``Notes`` from the name index's ``chapter``, ``ending``,
    ``minigame_use``, and ``flowchart_scene`` rows (each in the label whose line is the
    nearest above it in the same file). Rows without a place, or above every label of their
    file, are left out. F41: ``replay_scene`` rows name their label (the declaration is top
    level, so its line says nothing); a name that isn't a label is left out."""
    starts: dict[str, list[tuple[int, str]]] = {}
    found: dict[str, dict[str, list[str]]] = {}
    known: set[str] = set()
    for entry in labels:
        name, where, line = _label_row(entry)
        known.add(name)
        if where is not None and line is not None:
            starts.setdefault(where, []).append((line, name))
    for rows in starts.values():
        rows.sort()
    for entry in names.get("replay_scene", ()):
        name = _label_row(entry)[0]
        if name in known:
            found.setdefault(name, {}).setdefault("replay_scene", []).append(name)
    for kind in ("chapter", "ending", "minigame_use", "flowchart_scene", "ui_delete"):
        for entry in names.get(kind, ()):
            what, where, line = _label_row(entry)
            rows = starts.get(where) if where is not None else None
            if not rows or line is None:
                continue
            at = bisect.bisect_right(rows, (line, "􏿿")) - 1
            if at < 0:
                continue
            found.setdefault(rows[at][1], {}).setdefault(kind, []).append(what)
    return {label: Notes(next(iter(kinds.get("chapter", ())), None),
                         tuple(kinds.get("ending", ())), tuple(kinds.get("minigame_use", ())),
                         next(iter(kinds.get("flowchart_scene", ())), None),
                         bool(kinds.get("ui_delete")), bool(kinds.get("replay_scene")))
            for label, kinds in found.items()}


def layout(links: Iterable[object], labels: Iterable[object], *,
           max_boxes: int = MAX_BOXES, file: str | None = None,
           notes: Mapping[str, Notes] | None = None,
           stale: Collection[str] = (), places: Places | None = None) -> MapLayout:
    """The story map for ``labels`` (program order) and ``links`` (see the module doc):
    ``relayout`` with nothing to reuse."""
    return relayout(None, links, labels, max_boxes=max_boxes, file=file, notes=notes,
                    stale=stale, places=places)[0]


@dataclass(frozen=True, slots=True)
class LayoutDiff:
    """What ``relayout`` changed against the previous layout, by label name and
    ``EdgeKey`` (F58 ``04`` §7.6 step 5). ``full``: there was no previous layout (draw it
    all). Boxes: ``added``, ``removed``, ``moved`` (corner), ``restyled`` (file, marks,
    chapter, minigames or scene title), ``lines`` (``line`` only: the ``file:line`` text).
    Edges: ``edges_added``, ``edges_removed``, ``edges_restyled`` (choice text or
    condition), ``edges_rerouted`` (an end box moved, or its port or end height changed),
    ``chips_moved`` (an existing chip's place changed). ``placed``: the boxes placed
    automatically this time (no pin or place), the spots the caller pins (PR-F58-07)."""

    full: bool = False
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    moved: tuple[str, ...] = ()
    restyled: tuple[str, ...] = ()
    lines: tuple[str, ...] = ()
    edges_added: tuple[EdgeKey, ...] = ()
    edges_removed: tuple[EdgeKey, ...] = ()
    edges_restyled: tuple[EdgeKey, ...] = ()
    edges_rerouted: tuple[EdgeKey, ...] = ()
    chips_moved: tuple[EdgeKey, ...] = ()
    placed: Mapping[str, tuple[int, int]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.full or self.added or self.removed or self.moved or self.restyled
                    or self.lines or self.edges_added or self.edges_removed
                    or self.edges_restyled or self.edges_rerouted or self.chips_moved)

    @property
    def size(self) -> int:
        """Boxes and edges changed (F58: over 200 is a full redraw, PR-F58-06)."""
        return (len(self.added) + len(self.removed) + len(self.moved) + len(self.restyled)
                + len(self.edges_added) + len(self.edges_removed) + len(self.edges_restyled)
                + len(self.edges_rerouted))


def relayout(prev: MapLayout | None, links: Iterable[object], labels: Iterable[object], *,
             max_boxes: int = MAX_BOXES, file: str | None = None,
             notes: Mapping[str, Notes] | None = None, stale: Collection[str] = (),
             places: Places | None = None, pins: Places | None = None,
             keep: bool = False) -> tuple[MapLayout, LayoutDiff]:
    """The map for ``labels`` and ``links`` with ``pins`` (F58: automatically placed boxes,
    kept in memory) and ``places`` (the author's) both treated as places, ``places``
    winning: equal to ``layout(..., places={**pins, **places})``, and a ``LayoutDiff``
    against ``prev`` (F58 ``04`` §7.6).

    Columns, marks and rows are O(n + e); a box or edge equal to ``prev``'s is the same
    object. Only boxes without a pin or place are placed (``place_free`` on the cached
    box hash). Chips are re-slotted only where needed: a new edge, one whose curve or text
    changed, or one whose tried spots meet a changed area (a box added, removed or moved, a
    chip removed or moved by an earlier edge). ``prev``'s chip cache moves to the result;
    ``keep=True`` copies it instead (a dry run, ``prev`` stays usable). A ``prev`` whose
    cache moved on, or edges that changed their link order, slot every chip again."""
    notes = notes or {}
    rows: dict[str, tuple[str | None, int | None]] = {}
    for entry in labels:
        if type(entry) is str:
            name, where, line = entry, None, None
        else:
            try:
                name, where, line = entry.name, entry.file, entry.line
            except AttributeError:
                name, where, line = _label_row(entry)
        if name not in rows:
            rows[name] = (where, line)
    known: list[tuple[str, str, str, str | None, bool]] = []
    outgoing: dict[str, list[str]] = {}
    ending_out: set[str] = set()                # labels with a jump or menu link out
    reached_by: dict[str, set[str]] = {}        # label → the link kinds that reach it
    for link in links:
        if type(link) is LabelLink:
            src, dst, kind, choice, cond = (link.src, link.dst, link.kind, link.choice,
                                            link.conditional)
        else:
            src, dst, kind, choice, cond = _link_row(link)
        if src in rows and kind in _ENDING_LINKS:
            ending_out.add(src)
        if src not in rows or dst not in rows:
            continue
        known.append((src, dst, kind, choice, cond))
        outgoing.setdefault(src, []).append(dst)
        reached_by.setdefault(dst, set()).add(kind)

    distance: dict[str, int] = {}
    if START_LABEL in rows:
        distance[START_LABEL] = 0
        queue = deque([START_LABEL])
        while queue:
            here = queue.popleft()
            for there in outgoing.get(here, ()):
                if there not in distance:
                    distance[there] = distance[here] + 1
                    queue.append(there)
    last = max(distance.values()) + 1 if distance else 0
    # F41 P4: "not reached" counts scene replays as starting points too (columns don't).
    reached = set(distance)
    queue = deque(name for name in rows if name not in reached
                  and notes.get(name, _NO_NOTES).replay)
    reached.update(queue)
    while queue:
        for there in outgoing.get(queue.popleft(), ()):
            if there not in reached:
                reached.add(there)
                queue.append(there)

    specs: list[tuple[int, int, str, str | None, int | None, tuple[str, ...], Notes]] = []
    next_row: dict[int, int] = {}
    for name, (where, line) in rows.items():
        if file is not None and where != file:
            continue
        column = distance.get(name, last)
        row = next_row.get(column, 0)
        next_row[column] = row + 1
        marks = []
        if name == START_LABEL:
            marks.append(MARK_START)
        if name not in reached:
            marks.append(MARK_NOT_REACHED)
        note = notes.get(name, _NO_NOTES)
        if note.replay:
            marks.append(MARK_REPLAY)
        if name not in ending_out and reached_by.get(name) != {"call"}:
            marks.append(MARK_ENDS)
        if note.endings:
            marks.append(MARK_ENDING)
        if note.deletes_saves:
            marks.append(MARK_DELETES_SAVES)
        if name in stale:
            marks.append(MARK_OUT_OF_DATE)
        specs.append((column, row, name, where, line, tuple(marks), note))
    specs.sort(key=lambda s: (s[0], s[1]))
    hidden = len(specs) - max(0, min(len(specs), max_boxes))
    del specs[max(0, max_boxes):]

    valid = (prev is not None and prev.chips is not None
             and prev.chips.version == prev.chip_version)
    cache = (prev.chips.copy() if keep else prev.chips) if valid else ChipSlots()
    assert cache is not None
    before = dict(cache.box_at) if valid else {}
    spots, placed = _positions(cache, specs, rows, known,
                               {**(pins or {}), **(places or {})})

    old_boxes = prev.boxes if prev is not None else ()
    old_at = prev.by_name if prev is not None else {}
    boxes_list: list[Box] = []
    for column, row, name, where, line, marks, note in specs:
        x, y = spots[name]
        j = old_at.get(name)
        old = old_boxes[j] if j is not None else None
        if (old is not None and old.x == x and old.y == y and old.line == line
                and old.column == column and old.row == row and old.file == where
                and old.marks == marks and old.chapter == note.chapter
                and old.minigames == note.minigames and old.scene == note.scene):
            boxes_list.append(old)
        else:
            boxes_list.append(Box(name, where, line, column, row, x, y, marks, note.chapter,
                                  note.minigames, note.scene))
    boxes = tuple(boxes_list)
    index = {box.name: i for i, box in enumerate(boxes)}

    pairs: list[tuple[int, int, str, str | None, bool]] = []
    seen: set[tuple[int, int, str]] = set()
    for src, dst, kind, choice, cond in known:
        a, b = index.get(src), index.get(dst)
        if a is None or b is None or (a, b, kind) in seen:
            continue
        seen.add((a, b, kind))
        pairs.append((a, b, kind, choice, cond))
    ends_of = [(p[0], p[1]) for p in pairs]
    outs, ports = _ports(boxes, ends_of)
    ends = _ends(ends_of)
    corners = [spots[box.name] for box in boxes]
    end_of = ends.get
    sigs = [(corners[a], corners[b], port, end_of(i))
            for i, ((a, b), port) in enumerate(zip(ends_of, ports))]
    names = [box.name for box in boxes]
    keys = {(names[p[0]], names[p[1]], p[2]): i for i, p in enumerate(pairs)}

    regions: list[Rect] = []
    if valid and before != spots:
        for name in before.keys() | spots.keys():
            was, now = before.get(name), spots.get(name)
            if was != now:
                if was is not None:
                    regions.append(box_rect(*was))
                if now is not None:
                    regions.append(box_rect(*now))
    chips, moved_chips = _place_chips(cache, not valid, boxes, pairs, ports, ends, sigs,
                                      list(keys), regions)

    old_keys = prev.edge_keys if prev is not None else {}
    old_edges = prev.edges if prev is not None else ()
    edges_list: list[Edge] = []
    no_chip = (0.5, None)
    for key, (a, b, kind, choice, cond) in zip(keys, pairs):
        i = len(edges_list)
        slot, lift = chips.get(i, no_chip)
        j = old_keys.get(key)
        if j is not None:
            old_edge = old_edges[j]
            if (old_edge.src == a and old_edge.dst == b and old_edge.choice == choice
                    and old_edge.conditional == cond and old_edge.slot == slot
                    and old_edge.lift == lift):
                edges_list.append(old_edge)
                continue
        edges_list.append(Edge(a, b, kind, choice, cond, slot, lift))
    cache.version += 1
    width = max((b.x for b in boxes), default=-BOX_WIDTH) + BOX_WIDTH
    height = max((b.y for b in boxes), default=-BOX_HEIGHT) + BOX_HEIGHT
    found = MapLayout(boxes, tuple(edges_list), hidden, width, height, index, outs,
                      ports, ends, cache, cache.version, keys, tuple(sigs))
    return found, _diff(prev, found, placed, moved_chips)


_NO_NOTES = Notes()


def _sig(boxes: Sequence[Box], a: int, b: int, port: tuple[int, int],
         end: float | None) -> tuple:
    """What an edge's drawn curve depends on: both corners, its port and its end height
    (a self-link is the one whose two corners are the same box's)."""
    one, two = boxes[a], boxes[b]
    return ((one.x, one.y), (two.x, two.y), port, end)


def _diff(prev: MapLayout | None, now: MapLayout, placed: Mapping[str, tuple[int, int]],
          moved_chips: Collection[EdgeKey]) -> LayoutDiff:
    if prev is None:
        return LayoutDiff(True, tuple(b.name for b in now.boxes),
                          edges_added=tuple(now.edge_keys), placed=placed)
    added, moved, restyled, lines = [], [], [], []
    old_boxes, old_at = prev.boxes, prev.by_name
    for box in now.boxes:
        j = old_at.get(box.name)
        if j is None:
            added.append(box.name)
            continue
        old = old_boxes[j]
        if old is box:
            continue
        if old.x != box.x or old.y != box.y:
            moved.append(box.name)
        if (old.file != box.file or old.marks != box.marks or old.chapter != box.chapter
                or old.minigames != box.minigames or old.scene != box.scene):
            restyled.append(box.name)
        if old.line != box.line:
            lines.append(box.name)
    removed = tuple(b.name for b in prev.boxes if b.name not in now.by_name)
    e_added, e_restyled, e_rerouted = [], [], []
    old_keys, old_edges, old_sigs = prev.edge_keys, prev.edges, prev.sigs
    for key, i in now.edge_keys.items():
        j = old_keys.get(key)
        if j is None:
            e_added.append(key)
            continue
        old, edge = old_edges[j], now.edges[i]
        if old.choice != edge.choice or old.conditional != edge.conditional:
            e_restyled.append(key)
        if old_sigs[j] != now.sigs[i]:
            e_rerouted.append(key)
    e_removed = tuple(key for key in old_keys if key not in now.edge_keys)
    chips = tuple(key for key in moved_chips if key in now.edge_keys)
    return LayoutDiff(False, tuple(added), removed, tuple(moved), tuple(restyled),
                      tuple(lines), tuple(e_added), e_removed, tuple(e_restyled),
                      tuple(e_rerouted), chips, placed)


def _positions(cache: "ChipSlots", specs: Sequence[tuple], order: Iterable[str],
               known: Sequence[tuple[str, str, str, str | None, bool]],
               places: Places) -> tuple[dict[str, tuple[int, int]],
                                         dict[str, tuple[int, int]]]:
    """Every shown box's corner, and those placed automatically now. With no places: the
    F45 cells. Otherwise placed boxes keep their places and the rest (label order) go to
    ``place_free`` near a spot ``COLUMN_STEP`` right of the first placed box linking to
    them, else near their F45 cell. ``cache.boxes`` ends up holding every shown box."""
    if not places:
        spots = {s[2]: (COLUMN_STEP * s[0], ROW_STEP * s[1]) for s in specs}
        cache.sync_boxes(spots)
        return spots, dict(spots)
    shown = {s[2]: s for s in specs}
    spots: dict[str, tuple[int, int]] = {}
    for name in shown:
        spot = places.get(name)
        if spot is not None:
            spots[name] = (max(0, int(spot[0])), max(0, int(spot[1])))
    cache.sync_boxes(spots)
    if len(spots) == len(shown):
        return spots, {}
    lowest = max((y for _, y in spots.values()), default=None)
    into: dict[str, list[str]] | None = None
    placed: dict[str, tuple[int, int]] = {}
    for name in order:
        spec = shown.get(name)
        if spec is None or name in spots:
            continue
        if into is None:
            into = {}
            for src, dst, _kind, _choice, _cond in known:
                if src != dst:
                    into.setdefault(dst, []).append(src)
        near = (COLUMN_STEP * spec[0], ROW_STEP * spec[1])
        for src in into.get(name, ()):
            if src in spots:
                near = (spots[src][0] + COLUMN_STEP, spots[src][1])
                break
        x, y = spots[name] = placed[name] = _free_spot(cache.boxes, lowest, near)
        cache.add_box(name, x, y)
        lowest = y if lowest is None else max(lowest, y)
    return spots, placed


class RectHash:
    """Rectangles ``(x0, y0, x1, y1)`` bucketed into ``COLUMN_STEP`` × ``ROW_STEP`` cells:
    ``add`` one (F58: with an optional ``owner``), ``hits`` tells whether a rectangle
    overlaps any (touching doesn't count). F58: ``discard`` removes one, ``owners`` names
    the owners a rectangle overlaps, ``hits_before`` counts only owners ranked below a
    limit (a chip meets only earlier chips)."""

    __slots__ = ("_cells",)

    def __init__(self, rects: Iterable[Rect] = ()) -> None:
        self._cells: dict[tuple[int, int], list[tuple]] = {}
        for rect in rects:
            self.add(rect)

    @staticmethod
    def _span(rect: Rect) -> tuple[range, range]:
        x0, y0, x1, y1 = rect
        return (range(int(x0 // COLUMN_STEP), int(x1 // COLUMN_STEP) + 1),
                range(int(y0 // ROW_STEP), int(y1 // ROW_STEP) + 1))

    def add(self, rect: Rect, owner: object = None) -> None:
        entry = (*rect, owner)
        columns, rows = self._span(rect)
        cells = self._cells
        for c in columns:
            for r in rows:
                found = cells.get((c, r))
                if found is None:
                    cells[(c, r)] = [entry]
                else:
                    found.append(entry)

    def discard(self, rect: Rect, owner: object = None) -> None:
        """Removes one ``rect`` added with ``owner`` (nothing when there is none)."""
        entry = (*rect, owner)
        columns, rows = self._span(rect)
        for c in columns:
            for r in rows:
                found = self._cells.get((c, r))
                if found is not None and entry in found:
                    found.remove(entry)
                    if not found:
                        del self._cells[(c, r)]

    def hits(self, rect: Rect) -> bool:
        x0, y0, x1, y1 = rect
        columns, rows = self._span(rect)
        cells = self._cells
        for c in columns:
            for r in rows:
                for a0, b0, a1, b1, _owner in cells.get((c, r), ()):
                    if a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1:
                        return True
        return False

    def hits_before(self, rect: Rect, rank: Mapping[object, int], limit: int) -> bool:
        """Whether ``rect`` overlaps an entry whose owner ranks below ``limit``."""
        x0, y0, x1, y1 = rect
        columns, rows = self._span(rect)
        cells = self._cells
        for c in columns:
            for r in rows:
                for a0, b0, a1, b1, owner in cells.get((c, r), ()):
                    if a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1:
                        k = rank.get(owner)
                        if k is not None and k < limit:
                            return True
        return False

    def owners(self, rect: Rect) -> set:
        """The owners of the entries ``rect`` overlaps."""
        x0, y0, x1, y1 = rect
        columns, rows = self._span(rect)
        found: set = set()
        cells = self._cells
        for c in columns:
            for r in rows:
                for a0, b0, a1, b1, owner in cells.get((c, r), ()):
                    if a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1:
                        found.add(owner)
        return found

    def copy(self) -> "RectHash":
        other = RectHash()
        other._cells = {cell: list(entries) for cell, entries in self._cells.items()}
        return other


def box_rect(x: float, y: float) -> Rect:
    """The ``BOX_WIDTH`` × ``BOX_HEIGHT`` rectangle with its corner at (x, y)."""
    return (x, y, x + BOX_WIDTH, y + BOX_HEIGHT)


_RINGS: list[tuple[tuple[int, int], ...]] = [((0, 0),)]


def _ring(k: int) -> tuple[tuple[int, int], ...]:
    """Ring ``k``'s offsets (in ``PLACE_STEP`` units), nearest first, then by y, then x."""
    while len(_RINGS) <= k:
        n = len(_RINGS)
        spots = {(dx, dy) for dx in range(-n, n + 1) for dy in (-n, n)}
        spots |= {(dx, dy) for dx in (-n, n) for dy in range(-n, n + 1)}
        _RINGS.append(tuple(sorted(spots, key=lambda p: (p[0] * p[0] + p[1] * p[1],
                                                         p[1], p[0]))))
    return _RINGS[k]


def _free_spot(taken: RectHash, lowest: int | None, near: tuple[int, int]) -> tuple[int, int]:
    x, y = max(0, round(near[0])), max(0, round(near[1]))
    m = PLACE_MARGIN
    tries, k = 0, 0
    while tries < PLACE_TRIES:
        for dx, dy in _ring(k):
            sx, sy = x + dx * PLACE_STEP, y + dy * PLACE_STEP
            if sx < 0 or sy < 0:
                continue
            if not taken.hits((sx - m, sy - m, sx + BOX_WIDTH + m, sy + BOX_HEIGHT + m)):
                return sx, sy
            tries += 1
            if tries >= PLACE_TRIES:
                break
        k += 1
    return x, (0 if lowest is None else lowest + ROW_STEP)


def place_free(occupied: Iterable[tuple[int, int]], near: tuple[int, int]) -> tuple[int, int]:
    """A corner for a new box near ``near`` that keeps ``PLACE_MARGIN`` px clear of every box
    cornered at ``occupied``: the spot itself, else rings in ``PLACE_STEP`` px steps (nearest
    first; never below 0), ``PLACE_TRIES`` tries in all, else the row below the lowest box.
    Deterministic; never raises."""
    corners = [(round(x), round(y)) for x, y in occupied]
    taken = RectHash(box_rect(x, y) for x, y in corners)
    return _free_spot(taken, max((y for _, y in corners), default=None), near)


def layout_places(layout_: MapLayout) -> dict[str, tuple[int, int]]:
    """Every shown box's corner, by label: what the first move records (``04`` §6.8)."""
    return {box.name: (box.x, box.y) for box in layout_.boxes}


def _ports(boxes: Sequence[Box], ends_of: Sequence[tuple[int, int]]
           ) -> tuple[dict[int, tuple[int, ...]], tuple[tuple[int, int], ...]]:
    """Each source box's ``out_edges`` and each edge's port ``(k, n)``, for every box at
    once (O(e log e); F58 drops the per-box scan). ``ends_of``: each edge's ``(src, dst)``.
    A self-link has port (0, 1)."""
    found: dict[int, list[tuple[int, int, int]]] = {}
    for i, (src, dst) in enumerate(ends_of):
        if src != dst:
            box = boxes[dst]
            row = (box.y, box.x, i)
            group = found.get(src)
            if group is None:
                found[src] = [row]
            else:
                group.append(row)
    ports = [(0, 1)] * len(ends_of)
    outs: dict[int, tuple[int, ...]] = {}
    for src, group in found.items():
        group.sort()
        n = len(group)
        order = tuple(i for _y, _x, i in group)
        for k, i in enumerate(order):
            ports[i] = (k, n)
        outs[src] = order
    return outs, tuple(ports)


def _ends(ends_of: Sequence[tuple[int, int]]) -> dict[int, float]:
    """Edge → its end height (a share of the box) when several arrows join the same two
    boxes, so they never lie on top of each other (F46 step 5, now ``storymap``'s)."""
    pairs: dict[tuple[int, int], list[int]] = {}
    shared = False
    for i, pair in enumerate(ends_of):
        if pair[0] != pair[1]:
            group = pairs.get(pair)
            if group is None:
                pairs[pair] = [i]
            else:
                group.append(i)
                shared = True
    if not shared:
        return {}
    return {i: (k + 1) / (len(group) + 1) for group in pairs.values() if len(group) > 1
            for k, i in enumerate(group)}


def out_edges(layout_: MapLayout, box: int) -> tuple[int, ...]:
    """The indexes of the edges leaving ``box`` (self-links left out), by target y, then
    target x, then link order: the ports top to bottom, and Tab's order on a box."""
    assert layout_.outs is not None
    return layout_.outs.get(box, ())


def edge_port(layout_: MapLayout, index: int) -> float:
    """Edge ``index``'s port on its source as a share of the height: (k+1)/(n+1)."""
    k, n = layout_.ports[index]
    return (k + 1) / (n + 1)


def _line(boxes: Sequence[Box], edge: Edge, k: int, n: int) -> Rect:
    a, b = boxes[edge.src], boxes[edge.dst]
    bend = 20
    if edge.src == edge.dst:                            # F45's loop: its right-hand side
        x = a.x + BOX_WIDTH + 0.6 * bend
        return (x, a.y - 0.6 * bend, x, a.y + BOX_HEIGHT / 2)
    port = a.y + BOX_HEIGHT * (k + 1) / (n + 1)
    end = b.y + BOX_HEIGHT / 2
    if b.x >= a.x + BOX_WIDTH:
        return (a.x + BOX_WIDTH, port, b.x, end)
    if b.x + BOX_WIDTH <= a.x:
        return (a.x, port, b.x + BOX_WIDTH, end)
    x = max(a.x, b.x) + BOX_WIDTH + bend               # same column: F45's bend, its run
    return (x, a.y + BOX_HEIGHT / 2, x, end)


def edge_line(layout_: MapLayout, index: int) -> Rect:
    """Edge ``index``'s straight run ``(x0, y0, x1, y1)`` at 100%: from its port on the
    source (``y0 + h·(k+1)/(n+1)`` for the k-th of ``n`` out edges; the right side, or the
    left for a target to the left) to the target's facing side's middle. Same-column and
    self edges keep F45's shapes; this is their vertical run. A chip sits along it."""
    k, n = layout_.ports[index]
    return _line(layout_.boxes, layout_.edges[index], k, n)


def curve_points(a: Rect, b: Rect, port: float = 0.5, *, bend: float = 20,
                 loop: bool = False, end: float | None = None) -> list[float]:
    """The control points of the arrow from rectangle ``a`` to ``b`` that the map draws
    with ``smooth`` (one source for the window and for chip slots, step 4): it leaves and
    enters horizontally; a forward or backward arrow leaves at ``port`` of ``a``'s height;
    same-column arrows bend round the right; ``loop`` is a self-jump over the top right.
    ``end`` (F46 step 5, several arrows between the same two boxes): where it enters ``b``
    (and, same column, leaves ``a``) as a share of the height, so they stay apart."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    amid, bmid = (ay0 + ay1) / 2, (by0 + by1) / 2
    if bx0 >= ax1 or bx1 <= ax0:
        amid = ay0 + (ay1 - ay0) * port
    elif end is not None:
        amid = ay0 + (ay1 - ay0) * end
    if end is not None:
        bmid = by0 + (by1 - by0) * end
    if loop:
        return [ax1 - 2 * bend, ay0, ax1 - 2 * bend, ay0 - 0.6 * bend,
                ax1 + 0.6 * bend, ay0 - 0.6 * bend, ax1 + 0.6 * bend, amid, ax1, amid]
    if bx0 >= ax1:                      # forward: an S from the right edge to the left
        half = max(bend, (bx0 - ax1) / 2)
        return [ax1, amid, ax1 + half, amid, bx0 - half, bmid, bx0, bmid]
    if bx1 <= ax0:                      # backward: from the left edge to the right
        half = max(bend, (ax0 - bx1) / 2)
        return [ax0, amid, ax0 - half, amid, bx1 + half, bmid, bx1, bmid]
    return [ax1, amid, ax1 + bend, amid, bx1 + bend, bmid, bx1, bmid]   # same column


CURVE_STEPS: Final = 16                         # samples per spline segment (``curve_at``)
CURVE_CACHE: Final = 20_000                     # F58: curves whose length tables are kept
_TABLES: dict[tuple[float, ...], tuple[list[tuple[float, float]], list[float]]] = {}


def _table(points: Sequence[float]) -> tuple[list[tuple[float, float]], list[float]]:
    """The samples of the curve Tk draws through ``points`` and their cumulative lengths,
    built once per control-point tuple (F58: a slot probe is then a bisect)."""
    key = tuple(points)
    found = _TABLES.get(key)
    if found is not None:
        return found
    pts = list(zip(points[0::2], points[1::2]))
    knots = [pts[0], *(((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
                       for i in range(1, len(pts) - 2)), pts[-1]]
    samples = [pts[0]]
    for j in range(len(knots) - 1):
        (ax, ay), (cx, cy), (bx, by) = knots[j], pts[j + 1], knots[j + 1]
        for step in range(1, CURVE_STEPS + 1):
            u = step / CURVE_STEPS
            v = 1 - u
            samples.append((v * v * ax + 2 * v * u * cx + u * u * bx,
                            v * v * ay + 2 * v * u * cy + u * u * by))
    lengths = [0.0]
    for (ax, ay), (bx, by) in zip(samples, samples[1:]):
        lengths.append(lengths[-1] + math.hypot(bx - ax, by - ay))
    if len(_TABLES) >= CURVE_CACHE:
        _TABLES.clear()
    found = _TABLES[key] = (samples, lengths)
    return found


def curve_at(points: Sequence[float], t: float) -> tuple[float, float]:
    """The point a fraction ``t`` of the way, by length, along the curve Tk draws through
    ``points`` with ``smooth`` (quadratic pieces from the first point through the middles of
    the inner control points to the last). Two points: the straight line."""
    if len(points) < 6:
        ax, ay, bx, by = points[0], points[1], points[-2], points[-1]
        return ax + (bx - ax) * t, ay + (by - ay) * t
    samples, lengths = _table(points)
    goal = lengths[-1] * min(1.0, max(0.0, t))
    i = bisect.bisect_left(lengths, goal, 1)
    if i >= len(samples):
        return samples[-1]
    run = lengths[i] - lengths[i - 1]
    f = (goal - lengths[i - 1]) / run if run else 0.0
    (ax, ay), (bx, by) = samples[i - 1], samples[i]
    return ax + (bx - ax) * f, ay + (by - ay) * f


def edge_curve(layout_: MapLayout, index: int) -> list[float]:
    """Edge ``index``'s drawn curve at 100% (``curve_points`` from its port, and its end
    height when it shares its two boxes with another arrow): where its chip sits (``slot``
    is a t along it)."""
    edge = layout_.edges[index]
    k, n = layout_.ports[index]
    assert layout_.ends is not None
    return _curve(layout_.boxes, edge.src, edge.dst, k, n, layout_.ends.get(index))


def _curve(boxes: Sequence[Box], src: int, dst: int, k: int, n: int,
           end: float | None = None) -> list[float]:
    a, b = boxes[src], boxes[dst]
    return curve_points(box_rect(a.x, a.y), box_rect(b.x, b.y), (k + 1) / (n + 1),
                        loop=src == dst, end=end)


def chip_size(text: str) -> tuple[int, int]:
    """A chip's estimated size at 100% for ``text`` (``chip_text``'s result); F58 ``07``
    I-8: East Asian wide and full-width characters count twice."""
    wide = sum(1 for ch in text if ord(ch) > 0x10FF
               and unicodedata.east_asian_width(ch) in ("W", "F"))
    return CHIP_CHAR_PX * (len(text) + wide) + 2 * CHIP_PAD, CHIP_HEIGHT


def chip_rect(line: Sequence[float], t: float, size: tuple[float, float]) -> Rect:
    """The chip of ``size`` centred at ``t`` along ``line``: a straight run ``(x0, y0, x1,
    y1)`` or a curve's control points (``curve_at``)."""
    cx, cy = curve_at(line, t)
    w, h = size
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def chip_slot(line: Sequence[float], size: tuple[float, float], taken: RectHash) -> float:
    """The first of ``CHIP_SLOTS`` where the chip overlaps nothing in ``taken`` (boxes and
    earlier chips), else 0.5."""
    for t in CHIP_SLOTS:
        if not taken.hits(chip_rect(line, t, size)):
            return t
    return 0.5


def chip_center(layout_: MapLayout, index: int) -> tuple[float, float] | None:
    """Edge ``index``'s chip centre at 100% (its ``slot`` along ``edge_curve``, or the row
    gap at ``lift``), or None when it has no chip. The view draws the measured chip there
    and never re-slots by measurement (F58 ``07`` I-8; R3: a few px of overlap at
    extreme fonts)."""
    edge = layout_.edges[index]
    if not chip_text(edge.choice):
        return None
    cx, cy = curve_at(edge_curve(layout_, index), 0.5 if edge.lift is not None
                      else edge.slot)
    return (cx, edge.lift) if edge.lift is not None else (cx, cy)


@dataclass(slots=True)
class _Chip:
    sig: tuple                                  # the curve's inputs and the chip text
    curve: list[float]
    slot: float
    lift: float | None
    rect: Rect
    probes: tuple[Rect, ...]                    # every spot tried, up to the one taken


class ChipSlots:
    """``relayout``'s cache (F58 ``04`` §7.6 step 4): the shown boxes (``boxes``, owner the
    label; ``box_at`` their corners), the chips (owner the ``EdgeKey``), every chip's tried
    spots (``probes``) and its record, the chips' link order, and a version that says
    which layout owns it."""

    __slots__ = ("boxes", "box_at", "chips", "probes", "recs", "order", "sigs", "version")

    def __init__(self) -> None:
        self.boxes = RectHash()
        self.box_at: dict[str, tuple[int, int]] = {}
        self.chips = RectHash()
        self.probes = RectHash()
        self.recs: dict[EdgeKey, _Chip] = {}
        self.order: list[EdgeKey] = []
        self.sigs: list[tuple] = []             # each chip's ``_Chip.sig``, in ``order``
        self.version = 0

    def copy(self) -> "ChipSlots":
        other = ChipSlots()
        other.boxes, other.chips, other.probes = (self.boxes.copy(), self.chips.copy(),
                                                  self.probes.copy())
        other.box_at, other.recs, other.order = (dict(self.box_at), dict(self.recs),
                                                 list(self.order))
        other.sigs = list(self.sigs)
        other.version = self.version
        return other

    def add_box(self, name: str, x: int, y: int) -> None:
        self.box_at[name] = (x, y)
        self.boxes.add(box_rect(x, y), name)

    def sync_boxes(self, spots: Mapping[str, tuple[int, int]]) -> None:
        """``boxes`` holds exactly ``spots``."""
        at = self.box_at
        for name in [n for n, p in at.items() if spots.get(n) != p]:
            self.boxes.discard(box_rect(*at.pop(name)), name)
        for name, (x, y) in spots.items():
            if name not in at:
                self.add_box(name, x, y)


class _Taken:
    """``chip_slot``'s ``taken`` for chip ``limit``: the boxes and the earlier chips; it
    keeps every spot tried."""

    __slots__ = ("boxes", "chips", "rank", "limit", "probes", "blocked")

    def __init__(self, cache: ChipSlots, rank: Mapping[EdgeKey, int], limit: int) -> None:
        self.boxes, self.chips, self.rank, self.limit = cache.boxes, cache.chips, rank, limit
        self.probes: list[Rect] = []
        self.blocked = 0

    def hits(self, rect: Rect) -> bool:
        self.probes.append(rect)
        hit = self.boxes.hits(rect) or self.chips.hits_before(rect, self.rank, self.limit)
        self.blocked += hit
        return hit


def _place_chips(cache: ChipSlots, rebuild: bool, boxes: Sequence[Box],
                 pairs: Sequence[tuple[int, int, str, str | None, bool]],
                 ports: Sequence[tuple[int, int]], ends: Mapping[int, float],
                 sigs: Sequence[tuple], keys: Sequence[EdgeKey], regions: list[Rect]
                 ) -> tuple[dict[int, tuple[float, float | None]],
                                               set[EdgeKey]]:
    """Each choice edge's ``(slot, lift)`` by edge index, and the keys of chips that moved.
    Chips are taken in edge order: the first of ``CHIP_SLOTS`` whose estimated chip meets no
    box and no earlier chip, else 0.5; when all are taken, the row gap below the boxes, else
    above them (``lift``), else 0.5 anyway."""
    info = [(i, keys[i], pair[3], (sigs[i], pair[3])) for i, pair in enumerate(pairs)
            if pair[3]]
    rank = {key: j for j, (_i, key, _t, _s) in enumerate(info)}
    order = [key for _i, key, _t, _s in info]
    new_sigs = [sig for _i, _key, _t, sig in info]
    recs = cache.recs
    same = not rebuild and cache.order == order
    if not rebuild and not same:
        were = [key for key in cache.order if key in rank]
        if were != [key for _i, key, _t, _s in info if key in recs]:
            rebuild = True                      # a link-order swap: slot them all again
    dirty: set[int]
    if rebuild:
        cache.chips, cache.probes = RectHash(), RectHash()
        recs.clear()
        dirty = set(range(len(info)))
    elif same:                                  # the same chips in the same order
        dirty = {j for j, (was, now) in enumerate(zip(cache.sigs, new_sigs)) if was != now}
        for region in regions:
            for owner in cache.probes.owners(region):
                j = rank.get(owner)
                if j is not None:
                    dirty.add(j)
    else:
        for key in [key for key in recs if key not in rank]:
            rec = recs.pop(key)
            cache.chips.discard(rec.rect, key)
            for probe in rec.probes:
                cache.probes.discard(probe, key)
            regions.append(rec.rect)
        dirty = set()
        for j, (_i, key, _text, sig) in enumerate(info):
            rec = recs.get(key)
            if rec is None or rec.sig != sig:
                dirty.add(j)
        for region in regions:
            for owner in cache.probes.owners(region):
                j = rank.get(owner)
                if j is not None:
                    dirty.add(j)
    heap = sorted(dirty)
    moved: set[EdgeKey] = set()
    gap = (ROW_STEP - BOX_HEIGHT) / 2
    while heap:
        j = heapq.heappop(heap)
        i, key, choice, sig = info[j]
        a, b = pairs[i][0], pairs[i][1]
        rec = recs.get(key)
        k, n = ports[i]
        curve = rec.curve if rec is not None and rec.sig[0] == sig[0] \
            else _curve(boxes, a, b, k, n, ends.get(i))
        size = chip_size(chip_text(choice))
        taken = _Taken(cache, rank, j)
        t = chip_slot(curve, size, taken)
        rect = chip_rect(curve, t, size)
        lift = None
        if taken.blocked >= len(CHIP_SLOTS):    # 07 I-8: the row gap, below then above
            one, two = boxes[a], boxes[b]
            cx = (rect[0] + rect[2]) / 2
            w, h = size
            for y in (max(one.y, two.y) + BOX_HEIGHT + gap, min(one.y, two.y) - gap):
                if y - h / 2 >= 0:
                    spot = (cx - w / 2, y - h / 2, cx + w / 2, y + h / 2)
                    if not taken.hits(spot):
                        rect, lift = spot, y
                        break
        new = _Chip(sig, curve, t, lift, rect, tuple(taken.probes))
        if rec is not None:
            cache.chips.discard(rec.rect, key)
            for probe in rec.probes:
                cache.probes.discard(probe, key)
        cache.chips.add(rect, key)
        for probe in new.probes:
            cache.probes.add(probe, key)
        recs[key] = new
        if rec is not None and rec.rect == rect:
            continue
        if rec is not None:
            moved.add(key)
        for area in ((rec.rect, rect) if rec is not None else (rect,)):
            for owner in cache.probes.owners(area):
                later = rank.get(owner)
                if later is not None and later > j and later not in dirty:
                    dirty.add(later)
                    heapq.heappush(heap, later)
    cache.order, cache.sigs = order, new_sigs
    return {i: (recs[key].slot, recs[key].lift) for i, key, _t, _s in info}, moved


# -- F46 map history (04 §3.4, §6.9) -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MapStep:
    """One map action: box places before and after (None: automatic), each touched
    file's edit token ``(ref, OpenFile.changes right after)``, and (F58) Tidy up's pins."""

    title: str
    before: Mapping[str, tuple[int, int] | None]
    after: Mapping[str, tuple[int, int] | None]
    files: tuple[tuple[str, int], ...] = ()
    # F58 (07 I-9): Tidy up's pins, ``(before, after)``, each file-filter choice (None: all
    # files) → label → corner, for every choice Tidy up changed; None for other steps.
    pins: "tuple[PinSets, PinSets] | None" = None


class MapHistory:
    """The map's undo list (``limit`` steps, oldest dropped) and redo list. Pure: the window
    checks tokens and runs the text undo (or ``map_undo`` does both)."""

    __slots__ = ("limit", "_redo", "_undo")

    def __init__(self, limit: int = MAP_UNDO_STEPS) -> None:
        self.limit = limit
        self._undo: list[MapStep] = []
        self._redo: list[MapStep] = []

    def __len__(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)

    def push(self, step: MapStep) -> None:
        """Adds a new step; clears the redo list."""
        self._undo.append(step)
        del self._undo[:max(0, len(self._undo) - self.limit)]
        self._redo.clear()

    def undo_step(self) -> MapStep | None:
        """The step Ctrl+Z would undo (left in place), or None."""
        return self._undo[-1] if self._undo else None

    def redo_step(self) -> MapStep | None:
        """The step Ctrl+Y would redo (left in place), or None."""
        return self._redo[-1] if self._redo else None

    def drop(self, *, redo: bool = False) -> MapStep | None:
        """Removes the newest undo (or redo) step without doing it: a blocked step."""
        stack = self._redo if redo else self._undo
        return stack.pop() if stack else None

    def undone(self, files: tuple[tuple[str, int], ...]) -> MapStep | None:
        """The newest step was undone: it moves to the redo list with ``files`` as tokens."""
        if not self._undo:
            return None
        step = replace(self._undo.pop(), files=files)
        self._redo.append(step)
        return step

    def redone(self, files: tuple[tuple[str, int], ...]) -> MapStep | None:
        """The newest redo step was redone: back to the undo list with ``files`` as tokens."""
        if not self._redo:
            return None
        step = replace(self._redo.pop(), files=files)
        self._undo.append(step)
        del self._undo[:max(0, len(self._undo) - self.limit)]
        return step

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


class UndoRecord(Protocol):
    """What ``map_undo`` needs of an open file: its change counter and its text undo."""

    changes: int

    def edit_undo(self) -> object: ...

    def edit_redo(self) -> object: ...


@dataclass(frozen=True, slots=True)
class MapUndo:
    """``map_undo``'s outcome: the step (None: nothing to do), the places to restore (None
    when blocked), and the refs that blocked it (closed or changed since)."""

    step: MapStep | None
    places: Mapping[str, tuple[int, int] | None] | None = None
    blocked: tuple[str, ...] = ()


def undo_blocked_text(refs: Sequence[str]) -> str:
    """Design §17's "Undo blocked" line (``UNDO_BLOCKED``), naming the first blocked file
    (``script/`` left off)."""
    ref = refs[0] if refs else ""
    return UNDO_BLOCKED.format(file=show(ref.removeprefix("script/")))


def stale_files(step: MapStep, records: Mapping[str, UndoRecord | None]) -> tuple[str, ...]:
    """The step's files that are closed (no record) or whose ``changes`` differ from the
    token (typing, a reload, a text Ctrl+Z), in step order."""
    found = []
    for ref, token in step.files:
        record = records.get(ref)
        if record is None or record.changes != token:
            found.append(ref)
    return tuple(found)


def map_undo(history: MapHistory, records: Mapping[str, UndoRecord | None], *,
             redo: bool = False) -> MapUndo:
    """Map Ctrl+Z (Ctrl+Y with ``redo``), ``04`` §6.9: when a step file is stale, the step
    is dropped and nothing runs; otherwise each record's ``edit_undo`` (``edit_redo``) runs
    once, the new counters become the step's tokens, and ``before`` (``after``) is returned
    to restore."""
    step = history.redo_step() if redo else history.undo_step()
    if step is None:
        return MapUndo(None)
    blocked = stale_files(step, records)
    if blocked:
        history.drop(redo=redo)
        return MapUndo(step, None, blocked)
    tokens = []
    for ref, _token in step.files:
        record = records[ref]
        assert record is not None
        if redo:
            record.edit_redo()
        else:
            record.edit_undo()
        tokens.append((ref, record.changes))
    if redo:
        history.redone(tuple(tokens))
        return MapUndo(step, step.after)
    history.undone(tuple(tokens))
    return MapUndo(step, step.before)


def hidden_text(layout_: MapLayout) -> str:
    """``"N labels not shown"`` (``"1 label not shown"``), or ``""`` when all are shown."""
    n = layout_.hidden
    if n <= 0:
        return ""
    return f"{n} label not shown" if n == 1 else f"{n} labels not shown"


def label_files(labels: Iterable[object]) -> tuple[str, ...]:
    """The files that hold labels, sorted: the file filter's choices."""
    return tuple(sorted({f for f in (_label_row(e)[1] for e in labels) if f is not None}))


def neighbour(layout_: MapLayout, box: int, direction: str) -> int | None:
    """The nearest box from ``box`` toward ``direction`` (``left``, ``right``, ``up``,
    ``down``; any case), within 45° either side; None past the edge. Ties go to the box
    nearer the axis, then the lower index."""
    boxes = layout_.boxes
    if not 0 <= box < len(boxes):
        return None
    way = direction.lower()
    if way not in DIRECTIONS:
        raise ValueError(f"direction {direction!r} is not one of {DIRECTIONS}")
    here = boxes[box]
    best: tuple[int, int, int] | None = None
    for i, other in enumerate(boxes):
        if i == box:
            continue
        dx, dy = other.x - here.x, other.y - here.y
        along, across = {"right": (dx, dy), "left": (-dx, dy),
                         "down": (dy, dx), "up": (-dy, dx)}[way]
        if along <= 0 or abs(across) > along:
            continue
        key = (along * along + across * across, abs(across), i)
        if best is None or key < best:
            best = key
    return None if best is None else best[2]


def targets(layout_: MapLayout, box: int) -> tuple[int, ...]:
    """The boxes ``box`` has edges to, in link order, each once (self-links left out)."""
    found: list[int] = []
    for edge in layout_.edges:
        if edge.src == box and edge.dst != box and edge.dst not in found:
            found.append(edge.dst)
    return tuple(found)


def cycle_target(layout_: MapLayout, anchor: int, current: int | None) -> int | None:
    """Tab: the target of ``anchor`` after ``current`` (wrapping), the first when
    ``current`` isn't one of them, or None when ``anchor`` has none."""
    found = targets(layout_, anchor)
    if not found:
        return None
    if current in found:
        return found[(found.index(current) + 1) % len(found)]
    return found[0]


__all__ = ["BOX_HEIGHT", "BOX_WIDTH", "Box", "CHIP_CHARS", "CHIP_CHAR_PX", "CHIP_HEIGHT",
           "CHIP_PAD", "CHIP_SLOTS", "COLUMN_STEP", "DIRECTIONS", "Edge", "LINK_KINDS",
           "MAP_UNDO_STEPS", "MARK_ENDING", "MARK_ENDS", "MARK_NOT_REACHED", "MARK_OUT_OF_DATE",
           "MARK_REPLAY", "MARK_START", "MAX_BOXES", "ChipSlots", "EdgeKey", "LayoutDiff",
           "MapHistory", "MapLayout", "MapStep", "MapUndo", "Notes", "PinSets",
           "PLACE_MARGIN", "PLACE_STEP", "PLACE_TRIES", "Places", "ROW_STEP", "RectHash",
           "START_LABEL", "UNDO_BLOCKED", "UndoRecord", "box_rect", "chip_rect", "chip_size",
           "chip_center", "chip_slot", "chip_text", "curve_at", "curve_points", "cycle_target",
           "edge_curve", "edge_line", "edge_port", "undo_blocked_text", "hidden_text", "label_files", "label_notes",
           "layout", "layout_places", "map_undo", "neighbour", "out_edges", "place_free",
           "relayout", "stale_files", "targets"]
