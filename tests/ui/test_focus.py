"""``move_target`` and ``FocusScope`` (F10 ``04`` §7.3): AC-F10-03 (TR-F10-03) and AC-F10-04.
Pure Python: boxes in canvas units, no display. Tables are loops (test-review-F10.md)."""

from engine.ui.focus import Box, FocusGroup, FocusScope, move_target
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button


def at(cx: float, cy: float, w: float = 20, h: float = 20) -> Box:
    """A box centred on (cx, cy)."""
    return Box(cx - w / 2, cy - h / 2, w, h)


class Counted(Button):
    """A button that counts activations and can be disabled from the test."""

    def __init__(self, name: str, box: Box) -> None:
        self.name = name
        self.count = 0
        self.live = True
        super().__init__(lambda: name, self._act, enabled=lambda: self.live, box=box)

    def _act(self) -> None:
        self.count += 1

    def __repr__(self) -> str:
        return self.name


A, B, C = Box(0, 0, 320, 56), Box(0, 68, 320, 56), Box(0, 136, 320, 56)
YES, NO = at(524, 415, 200, 56), at(756, 415, 200, 56)


# AC-F10-03 rows 1–6: move_target over plain boxes.
MOVES = [
    (A, [B, C], Nav.DOWN, 0),                                   # 1: A DOWN → B
    (C, [A, B], Nav.DOWN, None),                                # 1: C DOWN → None
    (B, [A, C], Nav.LEFT, None),                                # 1: B LEFT → None
    (at(100, 100), [at(400, 100), at(180, 140)], Nav.RIGHT, 1),  # 2: Q (160 < 300)
    (at(100, 100), [at(300, 100), at(200, 160)], Nav.RIGHT, 0),  # 3: R (200 < 220)
    (at(100, 100), [at(200, 150), at(200, 50)], Nav.RIGHT, 1),   # 4: T, tie → reading order
    (at(100, 100), [at(100, 300)], Nav.RIGHT, None),            # 5: not strictly beyond
    (at(100, 100), [at(100, 300)], Nav.DOWN, 0),                # 5: V
    (NO, [YES], Nav.LEFT, 0),                                   # 6: No LEFT → Yes
    (YES, [NO], Nav.LEFT, None),                                # 6: Yes LEFT → None
    (NO, [YES], Nav.UP, None),                                  # 6: No UP → None
]


def test_ac03_move_target():
    for i, (cur, cands, d, expected) in enumerate(MOVES):
        assert move_target(cur, cands, d) == expected, i
    for d in (Nav.NEXT, Nav.ACTIVATE, Nav.HOME, Nav.BACK):
        assert move_target(A, [B, C], d) is None, d


def column_abc(*, column: bool = True):
    a, b, c = Counted("A", A), Counted("B", B), Counted("C", C)
    scope = FocusScope([FocusGroup([a, b, c], column=column)])
    return scope, a, b, c


def test_ac03_rows_1_7_8_9_scope_moves():
    scope, a, b, c = column_abc()
    scope.focus(c, InputKind.KEYS)
    assert scope.move(Nav.DOWN) and scope.focused is a
    assert scope.move(Nav.UP) and scope.focused is c
    scope, a, b, c = column_abc(column=False)
    scope.focus(a, InputKind.KEYS)
    assert scope.move(Nav.DOWN) and scope.focused is b
    scope.focus(c, InputKind.KEYS)
    assert not scope.move(Nav.DOWN) and scope.focused is c
    # Row 8: a row group (not a column) stays at its ends.
    yes, no = Counted("Yes", YES), Counted("No", NO)
    scope = FocusScope([FocusGroup([yes, no])])
    scope.focus(no, InputKind.KEYS)
    assert not scope.move(Nav.RIGHT) and scope.focused is no
    assert not scope.move(Nav.DOWN) and scope.focused is no
    assert scope.move(Nav.LEFT) and scope.focused is yes
    # Row 9: a disabled widget is skipped by move and Tab.
    scope, a, b, c = column_abc()
    b.live = False
    scope.focus(a, InputKind.KEYS)
    assert scope.move(Nav.DOWN) and scope.focused is c
    scope.focus(a, InputKind.KEYS)
    assert scope.tab(True) and scope.focused is c


def test_ac03_row10_tab_reading_order_across_groups():
    r, m, q = (Counted(n, Box(48, y, 288, 56)) for n, y in (("R", 264), ("M", 332),
                                                             ("Q", 400)))
    w2, w1 = Counted("w2", at(500, 300)), Counted("w1", at(500, 200))
    scope = FocusScope([FocusGroup([r, m, q], column=True), FocusGroup([w2, w1])])
    assert scope.tab_order() == [r, m, q, w1, w2]
    scope.focus(q, InputKind.KEYS)
    assert scope.tab(True) and scope.focused is w1
    scope.focus(w2, InputKind.KEYS)
    assert scope.tab(True) and scope.focused is r
    assert scope.tab(False) and scope.focused is w2


# AC-F10-04: focus rules.

def test_ac04_first_input_focuses_default_without_acting():
    for d in (Nav.UP, Nav.DOWN, Nav.LEFT, Nav.RIGHT, Nav.NEXT, Nav.PREV, Nav.ACTIVATE):
        scope, b1, b2, b3 = column_abc()
        scope.default_widget = b1
        assert scope.focused is None
        assert scope.press(d), d
        assert scope.focused is b1 and scope.visible and scope.source is InputKind.KEYS, d
        assert (b1.count, b2.count, b3.count) == (0, 0, 0), d
    for d in (Nav.BACK, Nav.START, Nav.SAMPLER, Nav.HOME, Nav.PAGE_DOWN):
        scope, b1, _, _ = column_abc()
        scope.default_widget = b1
        assert not scope.press(d), d
        assert scope.focused is None, d


def test_ac04_press_moves_and_activates_once_focused():
    scope, b1, b2, _ = column_abc()
    scope.press(Nav.DOWN)                      # focuses B1
    assert scope.press(Nav.DOWN) and scope.focused is b2
    assert scope.press(Nav.ACTIVATE) and b2.count == 1
    assert scope.press(Nav.PREV) and scope.focused is b1
    assert not scope.press(Nav.BACK)


def test_ac04_disabled_focused_passes_focus_on_in_reading_order():
    scope, b1, b2, b3 = column_abc()
    scope.focus(b2, InputKind.KEYS)
    b2.live = False
    scope.refresh()
    assert scope.focused is b3
    b2.live = True
    b3.live = False
    scope.refresh()
    assert scope.focused is b1
    b1.live = b2.live = b3.live = False         # every widget disabled clears focus
    scope.refresh()
    assert scope.focused is None


def test_ac04_disabled_never_focused_by_any_path():
    scope, b1, b2, b3 = column_abc()
    b1.live = False
    scope.default_widget = b1
    assert scope.default() is b2               # the default is skipped while disabled
    assert not scope.focus(b1, InputKind.MOUSE)    # hover or click
    assert not scope.focus(b1, InputKind.KEYS)
    scope.focus(b2, InputKind.KEYS)
    assert scope.move(Nav.UP) and scope.focused is b3    # wraps past B1
    for _ in range(6):
        scope.tab(True)
        assert scope.focused is not b1
        scope.move(Nav.DOWN)
        assert scope.focused is not b1


def test_ac04_set_groups_keeps_the_focused_widget():
    scope, b1, b2, b3 = column_abc()
    scope.focus(b2, InputKind.KEYS)
    extra = Counted("X", Box(0, 204, 320, 56))
    scope.set_groups([FocusGroup([b1, b2, b3, extra], column=True)])
    assert scope.focused is b2
    scope.set_groups([FocusGroup([b1, b3], column=True)])
    assert scope.focused is None
    # The focus-sound hook fires on a change only.
    changes = []
    scope, b1, b2, _ = column_abc()
    scope.on_change = changes.append
    scope.focus(b1, InputKind.KEYS, sound=False)        # first focus at open
    scope.focus(b1, InputKind.MOUSE)                    # no change
    scope.move(Nav.DOWN)
    scope.clear()
    assert changes == [b2]


def test_hidden_focus_is_revealed_before_it_moves():
    scope, b1, b2, _ = column_abc()
    scope.focus(b2, InputKind.MOUSE, sound=False, visible=False)   # Back by right click
    assert scope.press(Nav.DOWN)
    assert scope.focused is b2 and scope.visible and scope.source is InputKind.KEYS
    assert b2.count == 0
    assert scope.press(Nav.DOWN) and scope.focused is not b2


def test_edge_rule_then_other_groups():
    side = Counted("S", Box(48, 300, 288, 56))
    page = Counted("P", Box(500, 300, 200, 56))
    calls = []

    def edge(d, group):
        calls.append((d, group.widgets[0]))
        return False

    scope = FocusScope([FocusGroup([side], column=True), FocusGroup([page])], on_edge=edge)
    scope.focus(side, InputKind.KEYS)
    assert scope.move(Nav.RIGHT) and scope.focused is page        # other groups
    assert calls == [(Nav.RIGHT, side)]
    taken = FocusScope([FocusGroup([side], column=True), FocusGroup([page])],
                       on_edge=lambda d, g: True)
    taken.focus(side, InputKind.KEYS)
    assert taken.move(Nav.RIGHT) and taken.focused is side       # the edge rule took it


def test_widget_at_and_clear():
    scope, b1, b2, _ = column_abc()
    assert scope.widget_at((10, 70)) is b2
    assert scope.widget_at((10, 130)) is None                     # the gap between B2 and C
    b2.live = False
    assert scope.widget_at((10, 70)) is b2 and not scope.can_focus(b2)
    scope.focus(b1, InputKind.MOUSE)
    scope.clear()
    assert scope.focused is None and not scope.visible
    box = Box(10, 20, 30, 40)
    assert (box.right, box.bottom, box.center) == (40, 60, (25, 40))
    assert box.contains((10, 20)) and not box.contains((40, 20))
    assert box.moved(5, -5) == Box(15, 15, 30, 40)


# AC-F25-20 (F25 A7; F23 SPEC I-20): the focus default, unit rows. The Host U row is F25-3's.

def test_ac_f25_20_set_default():
    import threading

    from engine.minigames.context import bind

    scope, b1, b2, b3 = column_abc()
    assert scope.default() is b1                                  # the first in Tab order
    scope.set_default(b3)
    assert scope.default_widget is b3 and scope.default() is b3
    assert scope.set_default(None) is None
    assert scope.default_widget is None and scope.default() is b1
    bound = bind(scope, threading.get_ident())
    bound.set_default(b2)
    assert scope.default() is b2 and bound.default() is b2
    assert not hasattr(bound, "default_widget")
    assert "default_widget" not in dir(type(bound))
