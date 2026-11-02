"""One focus point per screen, shared by mouse, keys, and gamepad (F10 ``04`` §7.3).

Why this module exists: every F10-based screen moves focus by the same rules (ui-system §9),
so they live here once, with no pygame and no drawing:

- ``move_target``: the directional move. Candidates are boxes whose centre lies strictly
  beyond the current centre in the direction; score = |Δ along| + 2 × |Δ sideways|; lowest
  wins; ties go to reading order (centre y, then x). ``Grid`` uses the same function over its
  cells (I-17).
- ``FocusScope``: the focused widget, how it was focused (``source``), whether it is drawn
  focused (``visible``), the groups it moves in, Tab order, the default widget, and the
  search order of a move: the widget itself, its group, the screen's edge rule, the other
  groups, then the wrap of a ``column`` group.

A widget is focusable when its ``focusable`` flag is set and ``enabled()`` is True. A
disabled widget is never focused by a move, Tab, ``default()``, hover, or click.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.ui.nav import DIRECTIONS, InputKind, Nav

if TYPE_CHECKING:
    from engine.ui.widgets import Widget


@dataclass(frozen=True)
class Box:
    """A rectangle in canvas units."""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def contains(self, pos: tuple[float, float]) -> bool:
        """Half-open: the right and bottom edges belong to the next box."""
        px, py = pos
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def moved(self, dx: float = 0.0, dy: float = 0.0) -> "Box":
        return Box(self.x + dx, self.y + dy, self.w, self.h)


def reading_key(box: Box) -> tuple[float, float]:
    """Reading order: top to bottom, then left to right (by centre)."""
    cx, cy = box.center
    return cy, cx


# Unit vector per direction: (along x, along y).
_AXES: dict[Nav, tuple[int, int]] = {
    Nav.UP: (0, -1),
    Nav.DOWN: (0, 1),
    Nav.LEFT: (-1, 0),
    Nav.RIGHT: (1, 0),
}


def move_target(cur: Box, cands: Sequence[Box], d: Nav) -> int | None:
    """Index into ``cands`` of the box a move in direction ``d`` reaches, or None."""
    axis = _AXES.get(d)
    if axis is None:
        return None
    ux, uy = axis
    cx, cy = cur.center
    best: tuple[float, tuple[float, float], int] | None = None
    for index, box in enumerate(cands):
        bx, by = box.center
        dx, dy = bx - cx, by - cy
        along = dx * ux + dy * uy
        if along <= 0:                         # not strictly beyond
            continue
        sideways = abs(dx * uy) + abs(dy * ux)
        key = (along + 2 * sideways, reading_key(box), index)
        if best is None or key < best:
            best = key
    return None if best is None else best[2]


def is_focusable(w: "Widget") -> bool:
    return bool(w.focusable) and bool(w.enabled())


def _reading_order(widgets: Iterable["Widget"]) -> list["Widget"]:
    return sorted(widgets, key=lambda w: reading_key(w.box))     # stable for equal centres


class FocusGroup:
    """Widgets that move among themselves first. ``column``: Up/Down wrap at the ends.
    ``clip`` (F16 conflict 4): the members show only inside this box (a scrolling column),
    so ``FocusScope.widget_at`` never finds a member outside it and ``MenuScreen`` draws
    them clipped to it."""

    def __init__(self, widgets: list["Widget"], *, column: bool = False,
                 clip: Box | None = None) -> None:
        self.widgets = list(widgets)
        self.column = column
        self.clip = clip

    def __contains__(self, w: object) -> bool:
        return any(member is w for member in self.widgets)

    def focusable(self) -> list["Widget"]:
        return [w for w in self.widgets if is_focusable(w)]


EdgeRule = Callable[[Nav, FocusGroup], bool]


class FocusScope:
    """The focus of one screen.

    ``focused`` is the widget with focus (or None); ``source`` the input kind that set it;
    ``visible`` whether it is drawn focused (False after a Back by mouse returns focus to the
    opener). ``on_edge(d, group)`` is the screen's edge rule (game menu: sidebar ↔ page);
    returning True means it moved focus. ``on_change(w)`` is called when focus moves to a new
    widget with ``sound`` True: the screen plays ``focus_sound`` there."""

    def __init__(self, groups: Sequence[FocusGroup] = (), *,
                 default: "Widget | None" = None,
                 on_edge: EdgeRule | None = None,
                 on_change: "Callable[[Widget], None] | None" = None) -> None:
        self.groups: list[FocusGroup] = list(groups)
        self.focused: Widget | None = None
        self.source: InputKind | None = None
        self.visible: bool = False
        self.default_widget: Widget | None = default
        self.on_edge: EdgeRule | None = on_edge
        self.on_change = on_change

    # -- membership and order --

    def widgets(self) -> list["Widget"]:
        """Every member widget, groups in order, each group in its given order."""
        return [w for group in self.groups for w in group.widgets]

    def contains(self, w: "Widget") -> bool:
        return any(w in group for group in self.groups)

    def can_focus(self, w: "Widget | None") -> bool:
        return w is not None and self.contains(w) and is_focusable(w)

    def group_of(self, w: "Widget") -> FocusGroup | None:
        for group in self.groups:
            if w in group:
                return group
        return None

    def tab_order(self, *, include: "Widget | None" = None) -> list["Widget"]:
        """Groups in order; within each, reading order. Only focusable widgets, plus
        ``include`` (to find the place of a widget that just became disabled)."""
        order: list[Widget] = []
        for group in self.groups:
            members = [w for w in group.widgets if w is include or is_focusable(w)]
            order.extend(_reading_order(members))
        return order

    def set_groups(self, groups: Sequence[FocusGroup]) -> None:
        """Replace the groups; focus stays on the same widget if it is still a member."""
        self.groups = list(groups)
        if self.focused is not None and not self.contains(self.focused):
            self.focused = None
        self.refresh()

    # -- focus changes --

    def focus(self, w: "Widget", by: InputKind, *, sound: bool = True,
              visible: bool = True) -> bool:
        """Focus ``w`` if it is a focusable member. Returns whether ``w`` is now focused."""
        if not self.can_focus(w):
            return False
        changed = w is not self.focused
        self.focused = w
        self.source = by
        self.visible = visible
        if changed and sound and self.on_change is not None:
            self.on_change(w)
        return True

    def clear(self) -> None:
        """No focus (the pointer left a mouse-focused widget). Plays no sound."""
        self.focused = None
        self.visible = False

    def set_default(self, w: "Widget | None") -> None:
        """Set the default widget (F25 A7; F23 SPEC I-20). A method, so F23's ``bind``
        exposes it to a minigame while the ``default_widget`` attribute stays hidden."""
        self.default_widget = w

    def default(self) -> "Widget | None":
        """The screen's default widget if focusable, else the first in Tab order."""
        if self.can_focus(self.default_widget):
            return self.default_widget
        order = self.tab_order()
        return order[0] if order else None

    def refresh(self) -> None:
        """A focused widget that became disabled passes focus to the next one in reading
        (Tab) order, wrapping; no sound. Screens call this every update."""
        w = self.focused
        if w is None or is_focusable(w):
            return
        order = self.tab_order(include=w)
        if w not in order:
            self.focused = None
            return
        start = order.index(w)
        for step in range(1, len(order)):
            candidate = order[(start + step) % len(order)]
            if is_focusable(candidate):
                self.focused = candidate
                return
        self.focused = None

    # -- navigation --

    def press(self, d: Nav) -> bool:
        """A navigation press (``04`` §7.3 step 5): focus becomes visible and key-driven.
        With nothing focused (or a hidden focus), UP/DOWN/LEFT/RIGHT/NEXT/PREV/ACTIVATE
        focus the default (or reveal the focus) without acting. Otherwise ACTIVATE activates
        the focused widget, NEXT/PREV tab, and the rest move. BACK, START, and SAMPLER are
        the screen's: False. Returns whether the press was used."""
        self.refresh()
        if d in (Nav.BACK, Nav.START, Nav.SAMPLER):
            return False
        first = d in DIRECTIONS or d in (Nav.NEXT, Nav.PREV, Nav.ACTIVATE)
        if self.focused is None:
            if not first:
                return False
            target = self.default()
            if target is None:
                return False
            self.focus(target, InputKind.KEYS)
            return True
        was_visible = self.visible
        self.visible = True
        self.source = InputKind.KEYS
        if not was_visible and first:
            return True
        if d is Nav.ACTIVATE:
            self.focused.activate()
            return True
        if d in (Nav.NEXT, Nav.PREV):
            if self.focused.on_nav(d):                     # a widget's own parts first
                return True
            return self.tab(d is Nav.NEXT)
        return self.move(d)

    def move(self, d: Nav) -> bool:
        """Move focus (or let the focused widget use ``d``). True when anything happened."""
        self.refresh()
        cur = self.focused
        if cur is None:
            return False
        if cur.on_nav(d):                                      # 1. the widget itself
            return True
        if d not in DIRECTIONS:
            return False
        group = self.group_of(cur)
        if group is not None:                                  # 2. its group
            if self._move_among(cur, [w for w in group.focusable() if w is not cur], d):
                return True
            if self.on_edge is not None and self.on_edge(d, group):   # 3. edge rule
                return True
        others = [w for g in self.groups if g is not group     # 4. other groups
                  for w in g.focusable() if w is not cur]
        if self._move_among(cur, others, d):
            return True
        if group is not None and group.column and d in (Nav.UP, Nav.DOWN):   # 5. wrap
            members = _reading_order(group.focusable())
            if members:
                target = members[0] if d is Nav.DOWN else members[-1]
                if target is not cur:
                    self.focus(target, InputKind.KEYS)
                    return True
        return False

    def tab(self, forward: bool) -> bool:
        """Next or previous widget in Tab order, wrapping. A widget with parts of its own
        in the Tab order (F11's slot grid and page row) gets ``tab_entered(forward)``, so
        Tab enters it at its first part and Shift+Tab at its last; NEXT/PREV then reach its
        ``on_nav`` first (``press``), and it returns False at its last part."""
        self.refresh()
        order = self.tab_order()
        if not order:
            return False
        cur = self.focused
        if cur is None or cur not in order:
            target = order[0] if forward else order[-1]
        else:
            index = order.index(cur) + (1 if forward else -1)
            target = order[index % len(order)]
        if target is cur:
            return False
        self.focus(target, InputKind.KEYS)
        target.tab_entered(forward)
        return True

    def widget_at(self, pos: tuple[float, float]) -> "Widget | None":
        """The member widget under ``pos`` (enabled or not; the last added wins on overlap).
        A member of a group whose ``clip`` doesn't contain ``pos`` is never found. Use
        ``can_focus`` before focusing it."""
        for group in reversed(self.groups):
            if group.clip is not None and not group.clip.contains(pos):
                continue
            for w in reversed(group.widgets):
                if w.box.contains(pos):
                    return w
        return None

    def _move_among(self, cur: "Widget", cands: list["Widget"], d: Nav) -> bool:
        index = move_target(cur.box, [w.box for w in cands], d)
        if index is None:
            return False
        self.focus(cands[index], InputKind.KEYS)
        return True
