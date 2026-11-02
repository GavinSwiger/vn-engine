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
  box its Flowchart scene title.
- ``neighbour`` is the arrow keys (the nearest box in a 90° cone); ``targets`` and
  ``cycle_target`` are Tab (the focused box's outgoing edges, in link order).

``links`` are ``LabelLink`` objects or ``(src, dst, kind, file, line)`` rows; ``labels`` are
``NameEntry`` objects, ``(name, file, line)`` rows, or plain names.
"""

import bisect
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

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
LINK_KINDS: Final = ("jump", "call", "menu")
_ENDING_LINKS = frozenset({"jump", "menu"})     # a label with none of these ends the story
DIRECTIONS: Final = ("left", "right", "up", "down")


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


@dataclass(frozen=True, slots=True)
class Edge:
    """An arrow from box ``src`` to box ``dst`` (indexes into ``MapLayout.boxes``)."""

    src: int
    dst: int
    kind: str


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


def _link_row(link: object) -> tuple[str, str, str]:
    src = getattr(link, "src", None)
    if src is not None:
        return src, link.dst, link.kind  # type: ignore[attr-defined]
    src, dst, kind = tuple(link)[:3]  # type: ignore[call-overload]
    return src, dst, kind


def label_notes(labels: Iterable[object],
                names: Mapping[str, Iterable[object]]) -> dict[str, Notes]:
    """Label name → ``Notes`` from the name index's ``chapter``, ``ending``,
    ``minigame_use``, and ``flowchart_scene`` rows (each in the label whose line is the
    nearest above it in the same file). Rows without a place, or above every label of their
    file, are left out."""
    starts: dict[str, list[tuple[int, str]]] = {}
    for entry in labels:
        name, where, line = _label_row(entry)
        if where is not None and line is not None:
            starts.setdefault(where, []).append((line, name))
    for rows in starts.values():
        rows.sort()
    found: dict[str, dict[str, list[str]]] = {}
    for kind in ("chapter", "ending", "minigame_use", "flowchart_scene"):
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
                         next(iter(kinds.get("flowchart_scene", ())), None))
            for label, kinds in found.items()}


def layout(links: Iterable[object], labels: Iterable[object], *,
           max_boxes: int = MAX_BOXES, file: str | None = None,
           notes: Mapping[str, Notes] | None = None) -> MapLayout:
    """The story map for ``labels`` (program order) and ``links`` (see the module doc)."""
    notes = notes or {}
    rows: dict[str, tuple[str | None, int | None]] = {}
    for entry in labels:
        name, where, line = _label_row(entry)
        rows.setdefault(name, (where, line))
    known: list[tuple[str, str, str]] = []
    outgoing: dict[str, list[str]] = {}
    ending_out: set[str] = set()                # labels with a jump or menu link out
    reached_by: dict[str, set[str]] = {}        # label → the link kinds that reach it
    for link in links:
        src, dst, kind = _link_row(link)
        if src in rows and kind in _ENDING_LINKS:
            ending_out.add(src)
        if src not in rows or dst not in rows:
            continue
        known.append((src, dst, kind))
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
        if name not in distance:
            marks.append(MARK_NOT_REACHED)
        if name not in ending_out and reached_by.get(name) != {"call"}:
            marks.append(MARK_ENDS)
        note = notes.get(name, Notes())
        if note.endings:
            marks.append(MARK_ENDING)
        placed.append(Box(name, where, line, column, row, COLUMN_STEP * column,
                          ROW_STEP * row, tuple(marks), note.chapter, note.minigames,
                          note.scene))
    placed.sort(key=lambda b: (b.column, b.row))
    boxes = tuple(placed[:max(0, max_boxes)])

    index = {box.name: i for i, box in enumerate(boxes)}
    edges: list[Edge] = []
    seen: set[tuple[int, int, str]] = set()
    for src, dst, kind in known:
        a, b = index.get(src), index.get(dst)
        if a is None or b is None or (a, b, kind) in seen:
            continue
        seen.add((a, b, kind))
        edges.append(Edge(a, b, kind))
    width = max((b.x for b in boxes), default=-BOX_WIDTH) + BOX_WIDTH
    height = max((b.y for b in boxes), default=-BOX_HEIGHT) + BOX_HEIGHT
    return MapLayout(boxes, tuple(edges), len(placed) - len(boxes), width, height)


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


__all__ = ["BOX_HEIGHT", "BOX_WIDTH", "Box", "COLUMN_STEP", "DIRECTIONS", "Edge",
           "LINK_KINDS", "MARK_ENDING", "MARK_ENDS", "MARK_NOT_REACHED", "MARK_START",
           "MAX_BOXES", "MapLayout", "Notes", "label_notes", "ROW_STEP", "START_LABEL", "cycle_target", "hidden_text",
           "label_files", "layout", "neighbour", "targets"]
