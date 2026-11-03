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

``links`` are ``LabelLink`` objects or ``(src, dst, kind, file, line[, choice, cond])``
rows; ``labels`` are ``NameEntry`` objects, ``(name, file, line)`` rows, or plain names.
"""

import bisect
import math
from collections import deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Protocol

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
    its first link's choice text and condition flag, and its chip's t along ``edge_line``
    (F46)."""

    src: int
    dst: int
    kind: str
    choice: str | None = None
    conditional: bool = False
    slot: float = 0.5


@dataclass(frozen=True, slots=True)
class MapLayout:
    """``boxes`` sorted by (column, row); ``edges`` in link order, one per (src, dst, kind);
    ``hidden`` labels past the box cap; ``width``/``height`` the drawing's extent at 100%."""

    boxes: tuple[Box, ...]
    edges: tuple[Edge, ...]
    hidden: int
    width: int
    height: int

    def index_of(self, name: str) -> int | None:
        """The box for label ``name``, or None when it isn't shown."""
        for i, box in enumerate(self.boxes):
            if box.name == name:
                return i
        return None


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
    """The story map for ``labels`` (program order) and ``links`` (see the module doc)."""
    notes = notes or {}
    rows: dict[str, tuple[str | None, int | None]] = {}
    for entry in labels:
        name, where, line = _label_row(entry)
        rows.setdefault(name, (where, line))
    known: list[tuple[str, str, str, str | None, bool]] = []
    outgoing: dict[str, list[str]] = {}
    ending_out: set[str] = set()                # labels with a jump or menu link out
    reached_by: dict[str, set[str]] = {}        # label → the link kinds that reach it
    for link in links:
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
                  and notes.get(name, Notes()).replay)
    reached.update(queue)
    while queue:
        for there in outgoing.get(queue.popleft(), ()):
            if there not in reached:
                reached.add(there)
                queue.append(there)

    placed: list[Box] = []
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
        note = notes.get(name, Notes())
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
        placed.append(Box(name, where, line, column, row, COLUMN_STEP * column,
                          ROW_STEP * row, tuple(marks), note.chapter, note.minigames,
                          note.scene))
    placed.sort(key=lambda b: (b.column, b.row))
    boxes = tuple(placed[:max(0, max_boxes)])
    if places:
        boxes = _place(boxes, rows, known, places)

    index = {box.name: i for i, box in enumerate(boxes)}
    edges: list[Edge] = []
    seen: set[tuple[int, int, str]] = set()
    for src, dst, kind, choice, cond in known:
        a, b = index.get(src), index.get(dst)
        if a is None or b is None or (a, b, kind) in seen:
            continue
        seen.add((a, b, kind))
        edges.append(Edge(a, b, kind, choice, cond))
    edges = _slot_chips(boxes, edges)
    width = max((b.x for b in boxes), default=-BOX_WIDTH) + BOX_WIDTH
    height = max((b.y for b in boxes), default=-BOX_HEIGHT) + BOX_HEIGHT
    return MapLayout(boxes, tuple(edges), len(placed) - len(boxes), width, height)


class RectHash:
    """Rectangles ``(x0, y0, x1, y1)`` bucketed into ``COLUMN_STEP`` × ``ROW_STEP`` cells:
    ``add`` one, ``hits`` tells whether a rectangle overlaps any (touching doesn't count)."""

    __slots__ = ("_cells",)

    def __init__(self, rects: Iterable[Rect] = ()) -> None:
        self._cells: dict[tuple[int, int], list[Rect]] = {}
        for rect in rects:
            self.add(rect)

    @staticmethod
    def _span(rect: Rect) -> tuple[range, range]:
        x0, y0, x1, y1 = rect
        return (range(int(x0 // COLUMN_STEP), int(x1 // COLUMN_STEP) + 1),
                range(int(y0 // ROW_STEP), int(y1 // ROW_STEP) + 1))

    def add(self, rect: Rect) -> None:
        columns, rows = self._span(rect)
        for c in columns:
            for r in rows:
                self._cells.setdefault((c, r), []).append(rect)

    def hits(self, rect: Rect) -> bool:
        x0, y0, x1, y1 = rect
        columns, rows = self._span(rect)
        for c in columns:
            for r in rows:
                for a0, b0, a1, b1 in self._cells.get((c, r), ()):
                    if a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1:
                        return True
        return False


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


def _place(boxes: tuple[Box, ...], order: Iterable[str],
           known: Iterable[tuple[str, str, str, str | None, bool]],
           places: Places) -> tuple[Box, ...]:
    """``boxes`` with placed ones at their places and the rest placed around them."""
    shown = {box.name: box for box in boxes}
    pos: dict[str, tuple[int, int]] = {}
    for name, box in shown.items():
        if name in places:
            x, y = places[name]
            pos[name] = (max(0, int(x)), max(0, int(y)))
    taken = RectHash(box_rect(x, y) for x, y in pos.values())
    lowest = max((y for _, y in pos.values()), default=None)
    into: dict[str, list[str]] = {}
    for src, dst, _kind, _choice, _cond in known:
        if src != dst:
            into.setdefault(dst, []).append(src)
    for name in order:
        box = shown.get(name)
        if box is None or name in pos:
            continue
        near = (box.x, box.y)
        for src in into.get(name, ()):
            if src in pos:
                near = (pos[src][0] + COLUMN_STEP, pos[src][1])
                break
        x, y = pos[name] = _free_spot(taken, lowest, near)
        taken.add(box_rect(x, y))
        lowest = y if lowest is None else max(lowest, y)
    return tuple(replace(box, x=pos[box.name][0], y=pos[box.name][1]) for box in boxes)


def layout_places(layout_: MapLayout) -> dict[str, tuple[int, int]]:
    """Every shown box's corner, by label: what the first move records (``04`` §6.8)."""
    return {box.name: (box.x, box.y) for box in layout_.boxes}


def _out_order(boxes: tuple[Box, ...], edges: list[Edge]) -> dict[int, list[int]]:
    """Each source box's ``out_edges``, for every box at once."""
    found: dict[int, list[int]] = {}
    for i, edge in enumerate(edges):
        if edge.src != edge.dst:
            found.setdefault(edge.src, []).append(i)
    for indexes in found.values():
        indexes.sort(key=lambda i: (boxes[edges[i].dst].y, boxes[edges[i].dst].x, i))
    return found


def out_edges(layout_: MapLayout, box: int) -> tuple[int, ...]:
    """The indexes of the edges leaving ``box`` (self-links left out), by target y, then
    target x, then link order: the ports top to bottom, and Tab's order on a box."""
    edges = layout_.edges
    found = [i for i, edge in enumerate(edges) if edge.src == box and edge.dst != box]
    found.sort(key=lambda i: (layout_.boxes[edges[i].dst].y, layout_.boxes[edges[i].dst].x, i))
    return tuple(found)


def _line(boxes: tuple[Box, ...], edge: Edge, k: int, n: int) -> Rect:
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
    edge = layout_.edges[index]
    order = out_edges(layout_, edge.src)
    k = order.index(index) if index in order else 0
    return _line(layout_.boxes, edge, k, max(1, len(order)))


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


def curve_at(points: Sequence[float], t: float) -> tuple[float, float]:
    """The point a fraction ``t`` of the way, by length, along the curve Tk draws through
    ``points`` with ``smooth`` (quadratic pieces from the first point through the middles of
    the inner control points to the last). Two points: the straight line."""
    pts = list(zip(points[0::2], points[1::2]))
    if len(pts) < 3:
        (ax, ay), (bx, by) = pts[0], pts[-1]
        return ax + (bx - ax) * t, ay + (by - ay) * t
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
    goal = lengths[-1] * min(1.0, max(0.0, t))
    for i in range(1, len(samples)):
        if lengths[i] >= goal:
            run = lengths[i] - lengths[i - 1]
            f = (goal - lengths[i - 1]) / run if run else 0.0
            (ax, ay), (bx, by) = samples[i - 1], samples[i]
            return ax + (bx - ax) * f, ay + (by - ay) * f
    return samples[-1]


def edge_curve(layout_: MapLayout, index: int) -> list[float]:
    """Edge ``index``'s drawn curve at 100% (``curve_points`` from its port): where its
    chip sits (``slot`` is a t along it)."""
    edge = layout_.edges[index]
    order = out_edges(layout_, edge.src)
    k = order.index(index) if index in order else 0
    return _curve(layout_.boxes, edge, k, max(1, len(order)))


def _curve(boxes: tuple[Box, ...], edge: Edge, k: int, n: int) -> list[float]:
    a, b = boxes[edge.src], boxes[edge.dst]
    return curve_points(box_rect(a.x, a.y), box_rect(b.x, b.y), (k + 1) / (n + 1),
                        loop=edge.src == edge.dst)


def chip_size(text: str) -> tuple[int, int]:
    """A chip's estimated size at 100% for ``text`` (``chip_text``'s result)."""
    return CHIP_CHAR_PX * len(text) + 2 * CHIP_PAD, CHIP_HEIGHT


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


def _slot_chips(boxes: tuple[Box, ...], edges: list[Edge]) -> list[Edge]:
    """``edges`` with each choice edge's chip slot along its drawn curve, chips taken in
    edge order."""
    if not any(edge.choice for edge in edges):
        return edges
    taken = RectHash(box_rect(box.x, box.y) for box in boxes)
    ports = _out_order(boxes, edges)
    rank = {i: (k, len(order)) for order in ports.values() for k, i in enumerate(order)}
    for i, edge in enumerate(edges):
        text = chip_text(edge.choice)
        if not text:
            continue
        line = _curve(boxes, edge, *rank.get(i, (0, 1)))
        size = chip_size(text)
        t = chip_slot(line, size, taken)
        taken.add(chip_rect(line, t, size))
        edges[i] = replace(edge, slot=t)
    return edges


# -- F46 map history (04 §3.4, §6.9) -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MapStep:
    """One map action: box places before and after (None: automatic), and each touched
    file's edit token ``(ref, OpenFile.changes right after)``."""

    title: str
    before: Mapping[str, tuple[int, int] | None]
    after: Mapping[str, tuple[int, int] | None]
    files: tuple[tuple[str, int], ...] = ()


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
           "MARK_REPLAY", "MARK_START", "MAX_BOXES", "MapHistory", "MapLayout", "MapStep", "MapUndo", "Notes",
           "PLACE_MARGIN", "PLACE_STEP", "PLACE_TRIES", "Places", "ROW_STEP", "RectHash",
           "START_LABEL", "UNDO_BLOCKED", "UndoRecord", "box_rect", "chip_rect", "chip_size",
           "chip_slot", "chip_text", "curve_at", "curve_points", "cycle_target", "edge_curve",
           "edge_line", "undo_blocked_text", "hidden_text", "label_files", "label_notes",
           "layout", "layout_places", "map_undo", "neighbour", "out_edges", "place_free",
           "stale_files", "targets"]
