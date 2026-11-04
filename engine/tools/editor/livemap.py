"""The live story map's pure model (F58 ``04-technical.md`` §7.4, §7.5, §7.7, §7.9, §7.10;
``01-design.md`` PR-F58-04, 07, 09–11, 14, 17, 18, 22, 23; ``07`` I-9, I-13).

No Tk, no clock of its own: every timer takes ``now``/``after``/``cancel`` callables, so the
unit tests run on ``tests/tools/editor/live_fakes.FakeClock``. ``storymap`` lays the map out;
``mapcanvas`` draws it; the window wires these together (F58 W1–W5).

- ``FollowClock`` (PR-04, 05, 22): a change follows ``FOLLOW_MS`` after the last change, and
  at least every ``FOLLOW_MAX_MS`` from the previous update's *start* while changes keep
  coming (C1). ``fire(throttle)`` says which: a throttle tick adds no "out of date" and
  doesn't refresh the Events list; the pause update after it does. ``now()`` follows at once
  (actions, Q5).
- ``MapModel`` (§7.5): each file's label rows ``(name, line)`` and edge rows ``(src, dst,
  kind, choice, conditional)``, from the check child's lists and the scene indexes. Edges
  carry no lines, so a line shift changes only label lines. ``delta(shown)`` compares the
  changed files with a snapshot: boxes added, removed, renamed (PR-23: one name gone and one
  new at the same chunk position of one file) and line-only; edges added, removed, changed.
- ``Pins`` (§7.7, C4, I-9): the automatically placed corners per file-filter choice, never
  saved, at most ``PIN_CAP`` in all (the oldest pins of removed boxes go first).
- ``glow_items`` and ``GlowSet`` (PR-11, 12): what glows after an update, and the 2 s glow
  with its 4-step fade (one step on, one off under Reduce motion), at most ``GLOW_CAP`` per
  update, no item restarted within ``REGLOW_MS``. The "out of date" mark never glows (C5).
- ``MapLine`` and the ``s1``–``s8`` texts (§6.3; PR-17): one status line, S2 first, else the
  newest; S1 and S5 clear after ``LINE_CLEAR_MS`` or at the next update.
- ``UpdateBatch`` (PR-09, 10): the pending files of the next update (newest text per file
  wins, so a held or hidden map collects one update, never a queue), the 50,000-line big
  batch rule and the 30 ms parse slices.
- ``IndexBudget`` (PR-18): the 16 MiB / 64 MiB / 2,000-file caps (S6).
- ``preview_rows`` (PR-14, SEC-F48-09): what a card's plans add and remove, at most
  ``PREVIEW_CAP`` items, names and choice texts escaped for display (never the card's
  title or summary: they aren't inputs).
- ``stale_by_index`` (§7.10): Apply's Stale test against the editor's ``SceneIndex`` in
  O(touched); None when only ``rebase`` can tell (an edit above the first label).
"""

import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.core.redact import echo
from engine.script.messages import show
from engine.tools.editor.scenes import Key, SceneIndex
from engine.tools.editor.storymap import (
    MARK_OUT_OF_DATE, EdgeKey, LayoutDiff, MapLayout, PinSets, Places, chip_text)
from engine.tools.editor.studiolook import plural

FOLLOW_MS: Final = 80                   # C1: the debounce after the last change
FOLLOW_MAX_MS: Final = 250              # C1: the longest wait while changes keep coming
GLOW_MS: Final = 2_000                  # PR-11: how long a glow (or ghost) lasts
FADE_AT: Final = (1_400, 1_550, 1_700, 1_850)    # its four fade steps (the last 600 ms)
FADE_LEVELS: Final = (0.8, 0.6, 0.4, 0.2)        # the glow colour's share at each step
REGLOW_MS: Final = 1_000                # an item re-glows at most once a second
GLOW_CAP: Final = 50                    # over this many changes: S5 and no glow
LINE_CLEAR_MS: Final = 5_000            # S1 and S5 clear after this
PIN_CAP: Final = 10_000                 # PR-18, I-9: pins over every filter choice
PREVIEW_CAP: Final = 200                # PR-18: preview items
BIG_BATCH_LINES: Final = 50_000         # PR-10: over this, the check updates the map
PARSE_SLICE_MS: Final = 30              # PR-10: in-process parsing per idle tick
FILE_CAP_BYTES: Final = 16 * 1024 * 1024        # SCRIPT_FILE_MAX_BYTES
TOTAL_CAP_BYTES: Final = 64 * 1024 * 1024
FILE_COUNT_CAP: Final = 2_000

# §6.3's texts (verbatim; {file} through ``show``, counts through ``plural``).
S1_ONE: Final = "Updated from disk: `{file}`."
S1_MANY: Final = "Updated from disk: {n} files."
S2: Final = ("`{file}` changed on disk, and you have unsaved changes in it. Studio will ask "
             "which to keep.")
S3: Final = "The map will update when you finish."
S4: Final = "Many changes on disk ({n} files). The map updates after the check."
S5: Final = "{n} changes on the map."
S6: Final = "Some script files are too large to follow live. They update after each check."
S7: Final = ("Preview of the Assistant's change: {parts}. Apply or Discard it in the "
             "Assistant pane.")
S7_MORE: Final = ", and {n} more"
S8: Final = "The Assistant's change doesn't change the map."
FOLLOW_CHANGES: Final = "Follow changes"
REDUCE_MOTION: Final = "Reduce motion"
MARK_PROPOSED: Final = "proposed"
MARK_REMOVED: Final = "removed"

LabelRow = tuple[str, int | None]                       # (name, line)
EdgeRow = tuple[str, str, str, str | None, bool]        # (src, dst, kind, choice, conditional)


# --- The follow clock (§7.4) -------------------------------------------------------------------

class FollowClock:
    """When the map follows the text. ``changed()`` on every text change; ``now()`` for an
    action (it follows at once); ``cancel()`` on close. ``fire(throttle)`` runs the update:
    ``throttle`` is True for a tick the max wait forced while changes keep coming.

    Due time: ``min(last change + debounce, max(first change of the burst, previous update's
    start) + max_wait)``. After a throttle tick a pause tick still follows the last change,
    so the pause's own work (the "out of date" marks, the Events list) runs once typing
    stops."""

    __slots__ = ("_fire", "_after", "_cancel", "_now", "debounce", "max_wait", "_timer",
                 "_due", "_last_change", "_burst", "_last_start", "_pending", "_throttle")

    def __init__(self, fire: Callable[[bool], object], *, after: Callable[[float, Callable],
                                                                           object],
                 cancel: Callable[[object], object], now: Callable[[], float],
                 debounce: float = FOLLOW_MS, max_wait: float = FOLLOW_MAX_MS) -> None:
        self._fire, self._after, self._cancel, self._now = fire, after, cancel, now
        self.debounce, self.max_wait = debounce, max_wait
        self._timer: object | None = None
        self._due: float | None = None
        self._last_change: float | None = None
        self._burst: float | None = None        # first change not yet followed by a pause
        self._last_start: float | None = None   # the previous update's start
        self._pending = False                   # changes the last update didn't see
        self._throttle = False

    @property
    def pending(self) -> bool:
        return self._timer is not None

    def changed(self) -> None:
        t = self._now()
        self._last_change = t
        self._pending = True
        if self._burst is None:
            self._burst = t
        self._arm()

    def _arm(self) -> None:
        assert self._last_change is not None
        pause = self._last_change + self.debounce
        due, throttle = pause, False
        if self._pending and self._burst is not None:
            anchor = self._burst if self._last_start is None else max(self._burst,
                                                                       self._last_start)
            cap = anchor + self.max_wait
            if cap < pause:
                due, throttle = cap, True
        if self._timer is not None and due == self._due and throttle == self._throttle:
            return
        self._drop_timer()
        self._due, self._throttle = due, throttle
        self._timer = self._after(max(0.0, due - self._now()), self._tick)

    def _drop_timer(self) -> None:
        if self._timer is not None:
            self._cancel(self._timer)
            self._timer = None

    def _tick(self) -> None:
        self._timer = None
        throttle = self._throttle
        self._run(throttle)
        if throttle and self._last_change is not None:
            self._arm()                         # the pause tick still comes

    def _run(self, throttle: bool) -> None:
        self._last_start = self._now()
        self._pending = False
        if not throttle:
            self._burst = None
        self._fire(throttle)

    def now(self) -> None:
        """Follow at once (an action, Q5): any wait is dropped."""
        self._drop_timer()
        self._burst = None
        self._last_change = None
        self._run(False)

    def cancel(self) -> None:
        self._drop_timer()
        self._burst = self._last_change = None
        self._pending = False


# --- The model and its delta (§7.5) ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FileRows:
    """One file's labels (first chunk of each name, file order) and edges (link order)."""

    labels: tuple[LabelRow, ...] = ()
    edges: tuple[EdgeRow, ...] = ()


def _edge_row(link: object) -> tuple[str, EdgeRow]:
    """``(file, row)`` of a ``LabelLink`` or a ``(src, dst, kind, file, line[, choice,
    cond])`` row."""
    src = getattr(link, "src", None)
    if src is not None:
        return link.file, (src, link.dst, link.kind,  # type: ignore[attr-defined]
                           getattr(link, "choice", None), getattr(link, "conditional", False))
    row = tuple(link)  # type: ignore[call-overload]
    choice, cond = row[5:7] if len(row) >= 7 else (None, False)
    return row[3], (row[0], row[1], row[2], choice, bool(cond))


def _label_entry(entry: object) -> tuple[str, str | None, int | None]:
    name = getattr(entry, "name", None)
    if name is not None:
        return name, getattr(entry, "file", None), getattr(entry, "line", None)
    name, file, line = entry  # type: ignore[misc]
    return name, file, line


def rows_from_index(index: SceneIndex, check: Mapping[str, Sequence[EdgeRow]] | None = None
                    ) -> FileRows:
    """An indexed file's rows (as ``scenes.map_data`` merges them): each chunk's parsed
    links, else its last good read's, else (first chunks only) the check child's links of
    that label (``check``: label → rows)."""
    labels: list[LabelRow] = []
    edges: list[EdgeRow] = []
    check = check or {}
    reads, good = index.reads, index.good
    for key, start in index.starts.items():
        name, n = key
        if n == 0:
            labels.append((name, start))
        read = reads.get(key)
        if read is not None and read.error is not None:
            read = good.get(key)
        if read is not None:
            edges.extend((ln.src, ln.dst, ln.kind, ln.choice, ln.conditional)
                         for ln in read.links)
        elif n == 0:
            edges.extend(check.get(name, ()))
    return FileRows(tuple(labels), tuple(edges))


@dataclass(frozen=True, slots=True)
class MapDelta:
    """What changed between a snapshot and the model (by label name and ``EdgeKey``)."""

    files: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    renamed: tuple[tuple[str, str], ...] = ()            # (old, new), PR-23
    lines: tuple[str, ...] = ()
    edges_added: tuple[EdgeKey, ...] = ()
    edges_removed: tuple[EdgeKey, ...] = ()
    edges_changed: tuple[EdgeKey, ...] = ()              # choice text or "if"

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.renamed or self.lines
                    or self.edges_added or self.edges_removed or self.edges_changed)

    @property
    def map_changed(self) -> bool:
        """Anything but line numbers (S1 and the glow care about this)."""
        return bool(self.added or self.removed or self.renamed or self.edges_added
                    or self.edges_removed or self.edges_changed)


class MapModel:
    """The map's current data, file by file (§7.5). ``labels()``/``links()`` give
    ``storymap.relayout``'s inputs (links as 7-tuples with line 0: edges carry no lines);
    ``snapshot()`` is what the canvas shows; ``delta(shown)`` the difference."""

    __slots__ = ("files", "order")

    def __init__(self) -> None:
        self.files: dict[str, FileRows] = {}
        self.order: list[str] = []              # file order: the check's, new files last

    @classmethod
    def from_check(cls, labels: Iterable[object], links: Iterable[object]) -> "MapModel":
        """The check child's labels and links, grouped by file (a link by its own file)."""
        model = cls()
        by_file: dict[str, list[LabelRow]] = {}
        for entry in labels:
            name, file, line = _label_entry(entry)
            if file is None:
                continue
            if file not in by_file:
                by_file[file] = []
                model.order.append(file)
            by_file[file].append((name, line))
        edges: dict[str, list[EdgeRow]] = {}
        for link in links:
            file, row = _edge_row(link)
            edges.setdefault(file, []).append(row)
            if file not in by_file:
                by_file[file] = []
                model.order.append(file)
        for file in model.order:
            model.files[file] = FileRows(tuple(by_file[file]), tuple(edges.get(file, ())))
        return model

    def copy(self) -> "MapModel":
        other = MapModel()
        other.files, other.order = dict(self.files), list(self.order)
        return other

    def check_links(self, ref: str) -> dict[str, list[EdgeRow]]:
        """``ref``'s edges by source label (``rows_from_index``'s fallback)."""
        found: dict[str, list[EdgeRow]] = {}
        rows = self.files.get(ref)
        for edge in rows.edges if rows is not None else ():
            found.setdefault(edge[0], []).append(edge)
        return found

    def set_file(self, ref: str, rows: FileRows) -> None:
        if ref not in self.files:
            self.order.append(ref)
        self.files[ref] = rows

    def drop_file(self, ref: str) -> None:
        if self.files.pop(ref, None) is not None:
            self.order.remove(ref)

    def labels(self) -> list[tuple[str, str, int | None]]:
        return [(name, ref, line) for ref in self.order for name, line in self.files[ref].labels]

    def links(self) -> list[tuple]:
        return [(src, dst, kind, ref, 0, choice, cond) for ref in self.order
                for src, dst, kind, choice, cond in self.files[ref].edges]

    def snapshot(self) -> dict[str, FileRows]:
        return dict(self.files)

    def delta(self, shown: Mapping[str, FileRows], refs: Iterable[str] | None = None
              ) -> MapDelta:
        """Compare the files ``refs`` (default: every file in either) with ``shown``."""
        if refs is None:
            refs = list(dict.fromkeys([*shown, *self.files]))
        refs = [ref for ref in refs if shown.get(ref) != self.files.get(ref)]
        if not refs:
            return MapDelta()
        old_names: dict[str, LabelRow] = {}
        new_names: dict[str, LabelRow] = {}
        old_edges: dict[EdgeKey, tuple] = {}
        new_edges: dict[EdgeKey, tuple] = {}
        renamed: list[tuple[str, str]] = []
        for ref in refs:
            was, now = shown.get(ref, FileRows()), self.files.get(ref, FileRows())
            for row in was.labels:
                old_names.setdefault(row[0], row)
            for row in now.labels:
                new_names.setdefault(row[0], row)
            for src, dst, kind, choice, cond in was.edges:
                old_edges.setdefault((src, dst, kind), (choice, cond))
            for src, dst, kind, choice, cond in now.edges:
                new_edges.setdefault((src, dst, kind), (choice, cond))
            was_names = {r[0] for r in was.labels}
            now_names = {r[0] for r in now.labels}
            gone = [i for i, row in enumerate(was.labels) if row[0] not in now_names]
            came = [i for i, row in enumerate(now.labels) if row[0] not in was_names]
            if len(gone) == 1 and len(came) == 1 and gone[0] == came[0] \
                    and len(was.labels) == len(now.labels):
                renamed.append((was.labels[gone[0]][0], now.labels[came[0]][0]))
        old_set = {old for old, _new in renamed}
        new_set = {new for _old, new in renamed}
        added = tuple(n for n in new_names if n not in old_names and n not in new_set)
        removed = tuple(n for n in old_names if n not in new_names and n not in old_set)
        lines = tuple(n for n, row in new_names.items()
                      if n in old_names and old_names[n][1] != row[1])
        return MapDelta(
            tuple(refs), added, removed, tuple(renamed), lines,
            tuple(k for k in new_edges if k not in old_edges),
            tuple(k for k in old_edges if k not in new_edges),
            tuple(k for k, v in new_edges.items() if k in old_edges and old_edges[k] != v))


# --- Pins (§7.7) -------------------------------------------------------------------------------

class Pins:
    """Automatically placed corners per file-filter choice (None: all files), in memory
    only. ``of(choice)`` is ``relayout``'s ``pins``; ``add`` records ``LayoutDiff.placed``;
    ``removed`` notes boxes gone from the map (their pins go first past the cap);
    ``rename`` moves a pin to a new name in every choice (PR-23). ``snapshot``/``restore``
    are Tidy up's ``MapStep.pins`` halves (I-9)."""

    __slots__ = ("cap", "_sets", "_gone")

    def __init__(self, cap: int = PIN_CAP) -> None:
        self.cap = cap
        self._sets: dict[str | None, dict[str, tuple[int, int]]] = {}
        self._gone: dict[tuple[str | None, str], None] = {}    # oldest removal first

    def __len__(self) -> int:
        return sum(len(found) for found in self._sets.values())

    def of(self, choice: str | None) -> dict[str, tuple[int, int]]:
        return self._sets.setdefault(choice, {})

    def add(self, choice: str | None, placed: Places) -> None:
        found = self.of(choice)
        for name, spot in placed.items():
            found[name] = (int(spot[0]), int(spot[1]))
            self._gone.pop((choice, name), None)
        self._trim()

    def removed(self, names: Iterable[str], choice: str | None = None) -> None:
        for name in names:
            for key in ([choice] if choice is not None else list(self._sets)):
                if name in self._sets.get(key, {}):
                    self._gone[(key, name)] = None

    def rename(self, old: str, new: str) -> None:
        for key, found in self._sets.items():
            if old in found:
                found[new] = found.pop(old)
                self._gone.pop((key, old), None)

    def clear(self, choice: str | None = None) -> None:
        if choice is None:
            self._sets.clear()
            self._gone.clear()
        else:
            self._sets.pop(choice, None)
            self._gone = {k: None for k in self._gone if k[0] != choice}

    def snapshot(self) -> PinSets:
        return {key: dict(found) for key, found in self._sets.items()}

    def restore(self, sets: PinSets) -> None:
        self._sets = {key: dict(found) for key, found in sets.items()}
        self._gone = {k: None for k in self._gone if k[1] in self._sets.get(k[0], {})}

    def _trim(self) -> None:
        over = len(self) - self.cap
        if over <= 0:
            return
        for key in list(self._gone):            # the oldest removed boxes first
            if over <= 0:
                break
            self._sets.get(key[0], {}).pop(key[1], None)
            del self._gone[key]
            over -= 1
        for found in self._sets.values():       # then the oldest pins at all
            while over > 0 and found:
                del found[next(iter(found))]
                over -= 1


# --- Glow (§7.9) -------------------------------------------------------------------------------

def glow_items(delta: MapDelta, before: MapLayout | None, after: MapLayout,
               diff: LayoutDiff | None = None
               ) -> tuple[tuple[str, ...], tuple[EdgeKey, ...], tuple[str, ...],
                          tuple[EdgeKey, ...]]:
    """``(boxes, edges, ghost boxes, ghost edges)`` an update makes glow (PR-11): new and
    renamed boxes; boxes whose arrows, marks (but "out of date", C5), chapter or scene title
    changed; new arrows and arrows whose choice text or "if" changed. Removed boxes and
    arrows leave ghosts. A line shift alone glows nothing. Only what ``after`` shows."""
    shown = after.by_name
    boxes: dict[str, None] = {}
    for name in delta.added:
        boxes[name] = None
    for _old, new in delta.renamed:
        boxes[new] = None
    for src, _dst, _kind in (*delta.edges_added, *delta.edges_removed, *delta.edges_changed):
        boxes[src] = None
    if before is not None:
        names = diff.restyled if diff is not None else tuple(shown)
        for name in names:
            i, j = before.by_name.get(name), shown.get(name)
            if i is None or j is None:
                continue
            was, now = before.boxes[i], after.boxes[j]
            if ({m for m in was.marks if m != MARK_OUT_OF_DATE}
                    != {m for m in now.marks if m != MARK_OUT_OF_DATE}
                    or was.chapter != now.chapter or was.scene != now.scene):
                boxes[name] = None
    keys = after.edge_keys or {}
    edges = tuple(k for k in (*delta.edges_added, *delta.edges_changed) if k in keys)
    renamed_old = {old for old, _new in delta.renamed}
    ghosts = tuple(name for name in delta.removed if name not in renamed_old
                   and before is not None and name in before.by_name)
    old_keys = before.edge_keys if before is not None else {}
    ghost_edges = tuple(k for k in delta.edges_removed if k in (old_keys or {})
                        and k not in keys)
    return (tuple(n for n in boxes if n in shown), edges, ghosts, ghost_edges)


GlowKey = tuple[str, object]                     # ("box" | "edge" | "ghost" | "ghost_edge", key)


@dataclass(frozen=True, slots=True)
class GlowStart:
    """``start``'s outcome: the changes to draw now (level 1.0), or ``over`` > 0: that many
    changes, none glowing (S5)."""

    changes: tuple[tuple[GlowKey, float | None], ...] = ()
    over: int = 0


class GlowSet:
    """Every glow and ghost on one timer (§7.9). ``start`` begins glows (``reduce``: on and
    off in one step each); ``tick()`` returns ``(key, level)`` changes since the last tick:
    a level is the glow colour's share (1.0, then ``FADE_LEVELS``), None when it's gone;
    ``due()`` is when the next change falls due (ms on the injected clock), or None."""

    __slots__ = ("_now", "_on", "_level")

    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self._on: dict[GlowKey, tuple[float, bool]] = {}        # key → (start, reduce)
        self._level: dict[GlowKey, float] = {}

    def __len__(self) -> int:
        return len(self._on)

    def __contains__(self, key: GlowKey) -> bool:
        return key in self._on

    def start(self, boxes: Iterable[str] = (), edges: Iterable[EdgeKey] = (),
              ghosts: Iterable[str] = (), ghost_edges: Iterable[EdgeKey] = (), *,
              reduce: bool = False, cap: int = GLOW_CAP) -> GlowStart:
        keys = [*(("box", b) for b in boxes), *(("edge", e) for e in edges),
                *(("ghost", g) for g in ghosts), *(("ghost_edge", g) for g in ghost_edges)]
        if len(keys) > cap:
            return GlowStart((), len(keys))
        t = self._now()
        changes = []
        for key in keys:
            was = self._on.get(key)
            if was is not None and t - was[0] < REGLOW_MS:
                continue                        # a glowing item isn't restarted within 1 s
            self._on[key] = (t, reduce)
            if self._level.get(key) != 1.0:
                self._level[key] = 1.0
                changes.append((key, 1.0))
        return GlowStart(tuple(changes))

    @staticmethod
    def level_at(elapsed: float, reduce: bool) -> float | None:
        if elapsed >= GLOW_MS:
            return None
        if reduce:
            return 1.0
        level = 1.0
        for at, share in zip(FADE_AT, FADE_LEVELS):
            if elapsed >= at:
                level = share
        return level

    def tick(self) -> list[tuple[GlowKey, float | None]]:
        t = self._now()
        changes: list[tuple[GlowKey, float | None]] = []
        for key, (start, reduce) in list(self._on.items()):
            level = self.level_at(t - start, reduce)
            if level is None:
                del self._on[key]
                self._level.pop(key, None)
                changes.append((key, None))
            elif self._level.get(key) != level:
                self._level[key] = level
                changes.append((key, level))
        return changes

    def due(self) -> float | None:
        best: float | None = None
        for start, reduce in self._on.values():
            steps = (GLOW_MS,) if reduce else (*FADE_AT, GLOW_MS)
            elapsed = self._now() - start
            for at in steps:
                if at > elapsed:
                    due = start + at
                    best = due if best is None else min(best, due)
                    break
        return best

    def clear(self) -> list[tuple[GlowKey, float | None]]:
        gone = [(key, None) for key in self._on]
        self._on.clear()
        self._level.clear()
        return gone


# --- The status line (§6.3) --------------------------------------------------------------------

def s1(refs: Sequence[str]) -> str:
    if len(refs) == 1:
        return S1_ONE.format(file=show(refs[0]))
    return S1_MANY.format(n=len(refs))


def s2(ref: str) -> str:
    return S2.format(file=show(ref))


def s4(files: int) -> str:
    return S4.format(n=files)


def s5(changes: int) -> str:
    return S5.format(n=changes)


def s7(new_scenes: int, removed_scenes: int, new_arrows: int, removed_arrows: int,
       more: int = 0) -> str:
    """S7 with its parts (zeros left out) and ", and {n} more" past ``PREVIEW_CAP``; S8
    when there are no parts."""
    parts = [plural(n, word) for n, word in ((new_scenes, "new scene"),
                                             (removed_scenes, "removed scene"),
                                             (new_arrows, "new arrow"),
                                             (removed_arrows, "removed arrow")) if n]
    if not parts and not more:
        return S8
    text = ", ".join(parts) + (S7_MORE.format(n=more) if more else "")
    return S7.format(parts=text)


LINE_KINDS: Final = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
_TRANSIENT: Final = frozenset({"S1", "S5"})


class MapLine:
    """The map's one status line (PR-17): ``say(kind, text)`` and ``clear(kind)``;
    ``text()`` is S2 while it holds, else the newest; ``update_started()`` clears S1 and S5,
    which also clear ``LINE_CLEAR_MS`` after they were said (``expire()``)."""

    __slots__ = ("_now", "_lines", "_serial")

    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self._lines: dict[str, tuple[int, float, str]] = {}    # kind → (serial, said, text)
        self._serial = 0

    def say(self, kind: str, text: str) -> None:
        assert kind in LINE_KINDS, kind
        self._serial += 1
        self._lines[kind] = (self._serial, self._now(), text)

    def clear(self, kind: str) -> None:
        self._lines.pop(kind, None)

    def update_started(self) -> None:
        for kind in _TRANSIENT:
            self._lines.pop(kind, None)

    def expire(self) -> bool:
        """Drop S1/S5 older than ``LINE_CLEAR_MS``; True when the text changed."""
        t = self._now()
        old = [k for k, (_s, said, _t) in self._lines.items()
               if k in _TRANSIENT and t - said >= LINE_CLEAR_MS]
        for kind in old:
            del self._lines[kind]
        return bool(old)

    def due(self) -> float | None:
        times = [said + LINE_CLEAR_MS for k, (_s, said, _t) in self._lines.items()
                 if k in _TRANSIENT]
        return min(times) if times else None

    def kind(self) -> str | None:
        if "S2" in self._lines:
            return "S2"
        if not self._lines:
            return None
        return max(self._lines.items(), key=lambda item: item[1][0])[0]

    def text(self) -> str:
        kind = self.kind()
        return "" if kind is None else self._lines[kind][2]


# --- The pending update (PR-09, PR-10) ----------------------------------------------------------

class UpdateBatch:
    """The files the next map update covers: ``add(ref, text)`` keeps the newest text per
    file (None: the open editor's text), so any number of changes while the map is held,
    hidden or minimised is one update (``holds``: why it waits). ``ready()`` when there is
    something and nothing holds it. ``big(lines_of)``: over ``BIG_BATCH_LINES`` changed
    lines (S4, the check instead). ``step(work, now)`` runs ``work(ref, text)`` file by file
    for ``PARSE_SLICE_MS`` (at least one file) and says whether the batch is done."""

    __slots__ = ("pending", "holds")

    def __init__(self) -> None:
        self.pending: dict[str, str | None] = {}
        self.holds: set[str] = set()

    def __len__(self) -> int:
        return len(self.pending)

    def add(self, ref: str, text: str | None = None) -> None:
        self.pending.pop(ref, None)
        self.pending[ref] = text

    def hold(self, why: str) -> None:
        self.holds.add(why)

    def release(self, why: str) -> bool:
        """Drop one hold; True when the batch is now ready."""
        self.holds.discard(why)
        return self.ready()

    def ready(self) -> bool:
        return bool(self.pending) and not self.holds

    def big(self, lines_of: Callable[[str, str | None], int],
            limit: int = BIG_BATCH_LINES) -> bool:
        total = 0
        for ref, text in self.pending.items():
            total += lines_of(ref, text)
            if total > limit:
                return True
        return False

    def take(self) -> dict[str, str | None]:
        found, self.pending = self.pending, {}
        return found

    def step(self, work: Callable[[str, str | None], object], now: Callable[[], float],
             budget: float = PARSE_SLICE_MS) -> bool:
        start = now()
        while self.pending:
            ref = next(iter(self.pending))
            text = self.pending.pop(ref)
            work(ref, text)
            if now() - start >= budget:
                break
        return not self.pending


class IndexBudget:
    """PR-18's caps on what is indexed from disk: no file over ``FILE_CAP_BYTES``, and
    nothing past ``FILE_COUNT_CAP`` files or ``TOTAL_CAP_BYTES`` in all. ``admit(ref,
    size)`` in listing order; ``capped`` names what was refused (S6 while any)."""

    __slots__ = ("files", "total", "capped")

    def __init__(self) -> None:
        self.files = 0
        self.total = 0
        self.capped: list[str] = []

    def admit(self, ref: str, size: int) -> bool:
        if (size > FILE_CAP_BYTES or self.files >= FILE_COUNT_CAP
                or self.total + size > TOTAL_CAP_BYTES):
            self.capped.append(ref)
            return False
        self.files += 1
        self.total += size
        return True

    @property
    def line(self) -> str:
        return S6 if self.capped else ""


# --- The card preview (§7.10) ------------------------------------------------------------------

def display(text: str, limit: int | None = None) -> str:
    """A name or choice text as the map may show it (SEC-F48-09 (b)): ``echo``'s escapes,
    plus format and zero-width characters (which ``echo`` keeps) as ``\\uXXXX``."""
    shown = echo(text) if limit is None else echo(text, limit)
    return "".join(f"\\u{ord(ch):04x}" if unicodedata.category(ch) in ("Cf", "Zl", "Zp")
                   else ch for ch in shown)


@dataclass(frozen=True, slots=True)
class Preview:
    """A card's map preview (PR-14): the label names and ``EdgeKey``s added and removed
    (at most ``PREVIEW_CAP`` items in all, in that order), ``more`` past the cap, each
    item's display text (``texts``: name → shown name; edge → its chip), and the after-rows
    of the touched files (for the dry-run layout)."""

    boxes_added: tuple[str, ...] = ()
    boxes_removed: tuple[str, ...] = ()
    edges_added: tuple[EdgeKey, ...] = ()
    edges_removed: tuple[EdgeKey, ...] = ()
    more: int = 0
    texts: Mapping[object, str] = field(default_factory=dict)
    files: Mapping[str, FileRows] = field(default_factory=dict)

    @property
    def line(self) -> str:
        return s7(len(self.boxes_added), len(self.boxes_removed), len(self.edges_added),
                  len(self.edges_removed), self.more)

    def __bool__(self) -> bool:
        return bool(self.boxes_added or self.boxes_removed or self.edges_added
                    or self.edges_removed or self.more)


def preview_rows(model: MapModel, after: Mapping[str, FileRows]) -> Preview:
    """What applying a card would change on the map: ``after`` holds each touched file's
    rows parsed from the card's plans applied in memory (nothing runs or is written)."""
    trial = model.copy()
    for ref, rows in after.items():
        trial.set_file(ref, rows)
    delta = trial.delta(model.files, after.keys())
    renamed_new = tuple(new for _old, new in delta.renamed)
    renamed_old = tuple(old for old, _new in delta.renamed)
    groups = [list((*delta.added, *renamed_new)), list((*delta.removed, *renamed_old)),
              list(delta.edges_added), list(delta.edges_removed)]
    room = PREVIEW_CAP
    kept: list[list] = []
    for group in groups:
        kept.append(group[:room])
        room -= len(kept[-1])
    more = sum(len(g) for g in groups) - sum(len(k) for k in kept)
    choices: dict[EdgeKey, str | None] = {}
    for rows in (*after.values(), *(model.files[r] for r in after if r in model.files)):
        for src, dst, kind, choice, _cond in rows.edges:
            choices.setdefault((src, dst, kind), choice)
    texts: dict[object, str] = {}
    for name in (*kept[0], *kept[1]):
        texts[name] = display(name)
    for key in (*kept[2], *kept[3]):
        texts[key] = chip_text(display(choices.get(key) or ""))
    return Preview(tuple(kept[0]), tuple(kept[1]), tuple(kept[2]), tuple(kept[3]), more,
                   texts, dict(after))


def stale_by_index(touched: Sequence[Sequence[Key | None]],
                   marks: Iterable[tuple[Key, int, bytes]],
                   index: SceneIndex) -> bool | None:
    """Apply's Stale test (``edits.rebase``) for a card file against the editor's index of
    its live text, in O(touched): True (stale) when a touched chunk is gone or changed, or
    one edit's chunks moved by different amounts; False when every edit still applies;
    None when an edit touches the lines above the first label (ask ``rebase``)."""
    then = {key: (first, chunk_digest) for key, first, chunk_digest in marks}
    for keys in touched:
        shift: int | None = None
        for key in keys:
            if key is None:
                return None
            was = then.get(key)
            first = index.starts.get(key)
            if was is None or first is None or index.digests.get(key) != was[1]:
                return True
            step = first - was[0]
            if shift is not None and step != shift:
                return True
            shift = step
    return False


__all__ = ["BIG_BATCH_LINES", "EdgeRow", "FADE_AT", "FADE_LEVELS", "FILE_CAP_BYTES",
           "FILE_COUNT_CAP", "FOLLOW_CHANGES", "FOLLOW_MAX_MS", "FOLLOW_MS", "FileRows",
           "FollowClock", "GLOW_CAP", "GLOW_MS", "GlowKey", "GlowSet", "GlowStart",
           "IndexBudget", "LINE_CLEAR_MS", "LINE_KINDS", "LabelRow", "MARK_PROPOSED",
           "MARK_REMOVED", "MapDelta", "MapLine", "MapModel", "PARSE_SLICE_MS", "PIN_CAP",
           "PREVIEW_CAP", "Pins", "Preview", "REDUCE_MOTION", "REGLOW_MS", "S1_MANY", "S1_ONE",
           "S2", "S3", "S4", "S5", "S6", "S7", "S7_MORE", "S8", "TOTAL_CAP_BYTES",
           "UpdateBatch", "display", "glow_items", "preview_rows", "rows_from_index", "s1",
           "s2", "s4", "s5", "s7", "stale_by_index"]
