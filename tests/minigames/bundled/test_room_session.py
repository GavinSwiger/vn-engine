"""F27-3 — the puzzle room on screen (``06-acceptance.md`` AC-F27-08 to 15, 18 to 21, 25).
One test per AC, its rows inside; AC-F27-26 (``perf``) is ``tests/perf/test_room_perf.py``.

**Host R** is ``room_host.HostR`` (F23's Host U pieces with the bundled ``PuzzleRoom``, a real
F21 ``CodexView`` over ``LedgerCodexPort`` on Template R's codex, the fixture images, dev
on). Each row opens a fresh session, a cut (``restored``) reached by keys unless it says
otherwise. ``_WARNED`` is cleared around every test.

**Paths.** "Go to X" by keys or D-pad is a shortest arrow sequence from the current focus,
found by breadth-first search over the real scope's ``move`` (focus restored after each
probe); by mouse it is pointer motion to X's center. "Pick X" is F21's pick of X's row with
the row's device.

**Overlap (deviation, reported).** Hooks lie inside the door's rect in the attic, and the
door is later in room order, so the later hotspot gets the click (``07`` I-notes): at S0 a
click at hook's center activates the door. The mouse row of the S0 take therefore takes
``string`` (the only other take shown at S0); the keyboard and gamepad rows take hook.

Driver D (``tests/runtime/minigame_story``) accepts the posted results on Template R or L.
"""

import dataclasses
import logging
from collections import deque

import pygame
import pytest

from engine.app.codex import notice_text
from engine.core.config import load_config
from engine.core.minigame_types import CodexChange, Outcome
from engine.core.paths import GamePaths
from engine.minigames.bundled import puzzle_room, room_rules
from engine.minigames.bundled.puzzle_room import PICKER, ROOM, Hotspot
from engine.minigames.screen import MinigameScreen
from engine.minigames.tables import PluginTables
from engine.runtime.commands import CodexAdded, StartMinigame, StepBack
from engine.runtime.state import GameState
from engine.ui.focus import Box, FocusGroup, FocusScope
from engine.ui.nav import InputKind, Nav
from engine.ui.theme import Words
from engine.ui.widgets import Widget
from tests.fixtures.F27 import rooms
from tests.minigames.bundled.room_host import (BACKSPACE, D_DOWN, D_LEFT, D_RIGHT, D_UP, DOWN,
                                               EAST, ENTER, ENTRY, LB, LEFT, PAGE_DOWN,
                                               PAGE_UP, RB, RIGHT, SOUNDS, SOUTH, TAB, UP, H,
                                               HostR, click)

TAKE_HOOK = {"action": "take", "hotspot": "hook", "item": "rusty_key", "gone": ["hook"]}
USE_DRAWER = {"action": "use", "hotspot": "drawer", "item": "rusty_key",
              "gone": ["hook", "drawer"]}
COMBINE = {"action": "combine", "hotspot": None, "item": "magnet_string",
           "gone": list(rooms.S3_G)}
EXIT_S5 = {"action": "exit", "hotspot": "out", "item": None, "gone": list(rooms.S5_G)}
LOOK_AROUND = "Look around. Pick an item in Items to use it."
KEYS, MOUSE = InputKind.KEYS, InputKind.MOUSE
ARROWS = {"keys": {Nav.UP: UP, Nav.DOWN: DOWN, Nav.LEFT: LEFT, Nav.RIGHT: RIGHT},
          "pad": {Nav.UP: D_UP, Nav.DOWN: D_DOWN, Nav.LEFT: D_LEFT, Nav.RIGHT: D_RIGHT}}
ACT = {"keys": ENTER, "pad": SOUTH}
BACK = {"keys": BACKSPACE, "pad": EAST, "mouse": click((640, 360), 3)}


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture(autouse=True)
def warned():
    """``puzzle_room._WARNED`` is empty before and after each test (W179/W180 per process)."""
    puzzle_room._WARNED.clear()
    yield puzzle_room._WARNED
    puzzle_room._WARNED.clear()


@pytest.fixture
def world():
    return HostR()


# --- Helpers ----------------------------------------------------------------------------------

def spot(g, key: str) -> Hotspot:
    return next(s for s in g.spots if s.spot.key == key)


def name_of(g, w) -> str | None:
    """A scope widget's name: a hotspot's key, ``items``, ``put_away``, ``back``, or the
    view's part (``list``, ``body``, ``pick``)."""
    if w is None:
        return None
    if isinstance(w, Hotspot):
        return w.spot.key
    for name in ("items", "put_away", "back"):
        if w is getattr(g, name):
            return name
    view = g.view._target if g.view is not None else None
    if view is not None:
        for name, part in (("list", view.list), ("body", view.body),
                           ("pick", view.pick_button)):
            if w is part:
                return name
    return type(w).__name__


def focus(w: HostR):
    g = w.session.plugin
    return name_of(g, w.scope.focused) if w.scope.visible else None


def widget(g, name: str) -> Widget:
    if name in ("items", "put_away", "back"):
        return getattr(g, name)
    return spot(g, name)


def path_to(w: HostR, target: Widget) -> list[Nav]:
    """The shortest arrow sequence from the focus to ``target`` (BFS over the real scope's
    ``move``; focus restored after each probe)."""
    scope = w.scope
    start, visible = scope.focused, scope.visible
    seen, queue = {id(start): []}, deque([start])
    found = None
    while queue:
        cur = queue.popleft()
        if cur is target:
            found = seen[id(cur)]
            break
        for d in (Nav.UP, Nav.DOWN, Nav.LEFT, Nav.RIGHT):
            scope.focus(cur, KEYS, sound=False)
            scope.move(d)
            nxt = scope.focused
            if id(nxt) not in seen:
                seen[id(nxt)] = seen[id(cur)] + [d]
                queue.append(nxt)
    scope.focus(start, KEYS, sound=False, visible=visible)
    assert found is not None, f"no arrow path to {name_of(w.session.plugin, target)}"
    return found


def go(w: HostR, name: str, device: str) -> None:
    """Go to a hotspot or button: arrows (keys, D-pad) or pointer motion (mouse)."""
    g = w.session.plugin
    target = widget(g, name)
    if device == "mouse":
        w.frame(H.motion(target.box.center))
        return
    for d in path_to(w, target):
        w.frame(*ARROWS[device][d])
    assert w.scope.focused is target


def act(w: HostR, name: str, device: str) -> None:
    """Go to ``name`` and activate it with the device."""
    go(w, name, device)
    if device == "mouse":
        w.frame(*click(widget(w.session.plugin, name).box.center))
    else:
        w.frame(*ACT[device])


def pick(w: HostR, item: str, device: str) -> None:
    """In the picker, pick ``item``'s row with the device (AC-F21-26)."""
    g = w.session.plugin
    view = g.view._target
    index = [r.entry.name for r in view.rows()].index(item)
    if device == "mouse":
        w.frame(*click(view.list.row_box(index).center))
        w.frame(*click(view.pick_button.box.center))
        return
    if w.scope.focused is not view.list:
        for d in path_to(w, view.list):
            w.frame(*ARROWS[device][d])
    while view.list.focus_row != index:
        w.frame(*ARROWS[device][Nav.DOWN if view.list.focus_row < index else Nav.UP])
    w.frame(*ACT[device])                     # the row: focus moves to the pick button
    assert w.scope.focused is view.pick_button
    w.frame(*ACT[device])


def items(w: HostR, device: str) -> None:
    act(w, "items", device)
    assert w.session.plugin.mode == PICKER


def settle(w: HostR) -> None:
    """Frames until the finished session has posted its result (the dissolve out)."""
    for _ in range(60):
        if w.done():
            return
        w.frame()
    raise AssertionError("never posted")


def back(w: HostR, device: str) -> None:
    w.frame(*BACK[device])


# --- AC-F27-08 — The new-item notice (Q4) ------------------------------------------------------

def test_ac_f27_08_the_new_item_notice(world, tmp_path):
    from tests.minigames.bundled.test_room_headless import _game
    from tests.runtime.minigame_story import ALL, finish, launched, start_of, step
    from engine.runtime.interpreter import Status
    w = world
    program, sigs = _game(tmp_path / "l", loop=True)
    interp = launched(program, sigs=sigs)
    interp.new_game(42)
    interp.run(10_000)
    cmd = start_of(interp.take_commands(ALL))
    words = Words()

    def play(cmd: StartMinigame, actions) -> object:
        g = w.open(None, cmd=cmd)
        for a in actions:
            a(g)
        settle(w)
        (done,) = w.done()
        return done

    def accept_run(done) -> tuple[list, StartMinigame | None]:
        """Driver D accepts; Says are advanced until the loop's next StartMinigame."""
        out = finish(interp, done.result, done.changes)
        while not any(type(c) is StartMinigame for c in out) and interp.status is Status.WAITING:
            step(interp)
            out += interp.take_commands(ALL)
        starts = [c for c in out if type(c) is StartMinigame]
        return out, (starts[0] if starts else None)

    def notices(out) -> list[str]:
        return [notice_text(words, c) for c in out if type(c) is CodexAdded]

    # S0: activate hook; before acceptance the ledger holds give rusty_key and nothing is
    # released by the story.
    def take(key):
        def run(g):
            w.host.call(spot(g, key).activate)
            assert w.changes == (CodexChange("give", g.room.spot(key).take),)
            assert interp.take_commands(ALL) == []
        return run

    done = play(cmd, [take("hook")])
    out, cmd = accept_run(done)
    added = [c for c in out if type(c) is CodexAdded]
    assert added == [CodexAdded("item", "rusty_key", "Rusty Key")]
    assert out.index(added[0]) < out.index(cmd)                 # before the next run
    assert notices(out) == ["New item: Rusty Key"]
    # S1: the right use on drawer: no request, no notice.

    def use(g):
        w.host.call(g._open_picker)
        w.host.call(g.view._target._pick)                       # Rusty Key, the only row
        w.host.call(spot(g, "drawer").activate)
        assert w.changes == ()

    out, cmd = accept_run(play(cmd, [use]))
    assert notices(out) == [] and "The key turns. Inside, a magnet." in [
        "".join(s.text for s in c.body.plain()) for c in out if type(c).__name__ == "Say"]
    out, cmd = accept_run(play(cmd, [take("magnet")]))
    out, cmd = accept_run(play(cmd, [take("string")]))
    assert set(cmd.base.items) == {"magnet", "string"}          # S3

    # S3: combine (magnet_string not held): take, take, give; one notice after acceptance.
    def combine(g):
        w.host.call(g._open_picker)
        w.host.call(g._picked, "magnet")
        w.host.call(g._open_picker)
        w.host.call(g._picked, "string")
        assert w.changes == (CodexChange("take", "magnet"), CodexChange("take", "string"),
                             CodexChange("give", "magnet_string"))

    checkpoint = interp.checkpoint()
    combined = play(cmd, [combine])
    out, _ = accept_run(combined)
    assert notices(out) == ["New item: Magnet on a String"]
    # The same with magnet_string already held: the same ledger; no CodexAdded, held once.
    data = checkpoint.to_json()
    data["items"]["held"].append("magnet_string")
    assert interp.restore(GameState.from_json(data)).result.value == "ok"
    held_cmd = start_of(interp.take_commands(ALL))
    assert set(held_cmd.base.items) == {"magnet", "string", "magnet_string"}
    again = play(held_cmd, [combine])
    assert again.changes == combined.changes
    out, _ = accept_run(again)
    assert notices(out) == []
    assert list(interp.codex.items()).count("magnet_string") == 1
    assert not {"magnet", "string"} & set(interp.codex.items())
    assert MinigameScreen.holds_notices is False


# --- AC-F27-09 — Every result by each input device ---------------------------------------------

def reachable(w: HostR, target: Widget) -> bool:
    try:
        path_to(w, target)
    except AssertionError:
        return False
    return True


def test_ac_f27_09_every_result_by_each_device(tmp_path):
    from tests.minigames.bundled.test_room_headless import LINE_P, _game
    from tests.runtime.minigame_story import at_a, finish, to_line
    w = HostR(reduce_motion=True)                        # the endings are cuts
    program, sigs = _game(tmp_path / "r")
    take_string = {"action": "take", "hotspot": "string", "item": "string", "gone": ["string"]}

    def s0(device):
        act(w, "window", device)
        assert w.hint() == "Snow, as far as you can see."
        return "string" if device == "mouse" else "hook"         # module docstring

    def s1(device):
        items(w, device)
        pick(w, "rusty_key", device)
        act(w, "door", device)
        assert w.hint() == "That doesn't work."
        return "drawer"

    def s3(device):
        items(w, device)
        pick(w, "magnet", device)
        items(w, device)
        return None                                              # the last pick finishes

    def room_w(device):
        act(w, "box", device)
        assert w.hint() == "You need something for this."
        items(w, device)
        pick(w, "door_key", device)
        act(w, "box", device)
        assert w.hint() == "That doesn't work."
        items(w, device)
        pick(w, "string", device)
        g = w.session.plugin
        assert (w.hint(), g.mode) == ("Those don't go together.", PICKER)
        back(w, device)
        assert (g.mode, g.selected) == (ROOM, "door_key")
        back(w, device)
        assert (g.selected, w.hint()) == (None, LOOK_AROUND)
        return "gate"

    scenarios = {
        "S0 take": (rooms.stage("S0"), s0, TAKE_HOOK, [CodexChange("give", "rusty_key")]),
        "S1 use": (rooms.stage("S1"), s1, USE_DRAWER, []),
        "S3 combine": (rooms.stage("S3"), s3, COMBINE,
                       [CodexChange("take", "magnet"), CodexChange("take", "string"),
                        CodexChange("give", "magnet_string")]),
        "S5 exit": (rooms.stage("S5"), lambda device: "out", EXIT_S5, []),
        "Room W words": (({"room": rooms.room("room_w"), "state": None},
                          ("string", "door_key")), room_w,
                         {"action": "exit", "hotspot": "gate", "item": None, "gone": []}, []),
    }
    for name, ((args, held), steps, want, ledger) in scenarios.items():
        for device in ("keys", "mouse", "pad"):
            g = w.open(args, held, by=MOUSE if device == "mouse" else KEYS)
            last = steps(device)
            assert g.finishes == [] and w.changes == (), (name, device)
            if last is None:
                pick(w, "string", device)                        # S3: the combine
            else:
                act(w, last, device)
            result = take_string if (name, device) == ("S0 take", "mouse") else want
            changes = [CodexChange("give", "string")] if result is take_string else ledger
            assert g.finishes == [result], (name, device)        # in the finishing frame
            settle(w)
            assert [(d.result, list(d.changes)) for d in w.done()] == [(result, changes)]
            if device == "keys" and name != "Room W words":
                interp = at_a(program, sigs=sigs)
                to_line(interp, LINE_P)
                finish(interp, result)
                assert interp.checkpoint().variables["attic_state"] == result
    # Room U, gamepad only: key isn't reachable by arrows from the first focus; RB is.
    g = w.open({"room": rooms.room("room_u"), "state": None})
    assert focus(w) == "cover" and not reachable(w, spot(g, "key"))
    for _ in range(5):
        if focus(w) == "key":
            break
        w.frame(*RB)
    assert focus(w) == "key"
    w.frame(*SOUTH)
    assert g.finishes == [{"action": "take", "hotspot": "key", "item": "string",
                           "gone": ["key"]}]
    assert [d.changes for d in w.done()] == [(CodexChange("give", "string"),)]


# --- AC-F27-10 — Hotspots as widgets -----------------------------------------------------------

def rings(w: HostR, g) -> list[list[str]]:
    """Per frame from now on: the hotspots whose ring and tag were drawn."""
    frames: list[list[str]] = []
    real = g._draw_focus
    real_frame = w.frame

    def draw_focus(hotspot, p):
        frames[-1].append(hotspot.spot.key)
        return real(hotspot, p)

    def frame(*events):
        frames.append([])
        return real_frame(*events)

    g._draw_focus = draw_focus
    w.frame = frame
    return frames


WHITE = (255, 255, 255)


def test_ac_f27_10_hotspots_as_widgets(world):
    w = world
    drawer, bare = (620, 465), (700, 200)
    # Reached by Enter (the fade-in): window focused when it ends; its ring and tag only.
    g = w.stage("S0", restored=False, frame=False)
    drawn = rings(w, g)
    for _ in range(60):
        w.frame()
        if w.running() and g.opened:
            break
    assert focus(w) == "window" and drawn[-1] == ["window"]
    assert w.px(874, 200) == WHITE                       # window's ring (x 880 − 7 + 1)
    assert all(len(f) <= 1 for f in drawn)
    # Reached by click: nothing focused; no ring.
    g = w.stage("S0", by=MOUSE)
    drawn = rings(w, g)
    w.frame()
    assert w.scope.focused is None and drawn == [[]]
    # Pointer over drawer: focused by the mouse, ring and tag, not a used input; then bare
    # background: cleared.
    w.frame(H.motion(drawer))
    assert (focus(w), w.scope.source, drawn[-1], w.used()) == ("drawer", MOUSE, ["drawer"], [])
    assert w.px(514, 465) == WHITE
    w.frame(H.motion(bare))
    assert w.scope.focused is None and drawn[-1] == []
    # Window focused by keys, then the pointer over drawer: drawer's ring only.
    g = w.stage("S0")
    drawn = rings(w, g)
    w.frame()
    assert drawn[-1] == ["window"]
    w.frame(H.motion(drawer))
    assert drawn[-1] == ["drawer"] and w.px(874, 200) != WHITE
    # Resting on drawer, then Right: F10's move from drawer; only the new spot's ring.
    scope = w.scope
    before = scope.focused
    scope.move(Nav.RIGHT)
    want = scope.focused
    scope.focus(before, MOUSE, sound=False)
    w.frame(*RIGHT)
    assert scope.focused is want is not spot(g, "drawer") and drawn[-1] == [want.spot.key]
    assert all(len(f) <= 1 for f in drawn)
    # Room U: a click at the shared center activates key (later in room order).
    g = w.open({"room": rooms.room("room_u"), "state": None}, by=MOUSE)
    w.frame(*click((600, 350)))
    assert g.finishes == [{"action": "take", "hotspot": "key", "item": "string",
                           "gone": ["key"]}]
    # Hidden spots are not in the scope; at S1 a click at hook's center activates door.
    keys = lambda: [name_of(g, x) for x in w.scope.widgets()]          # noqa: E731
    g = w.stage("S0")
    assert not {"magnet", "glint", "out"} & set(keys())
    g = w.stage("S1", by=MOUSE)
    assert "hook" not in keys()
    w.frame(*click((172, 348)))
    assert w.hint() == "Locked tight."
    g = w.open({"room": rooms.room(), "state": None}, ("rusty_key",))
    assert "hook" not in keys()


# --- AC-F27-11 — Reach by Page keys and shoulders (C2) -----------------------------------------

def answers(g) -> list[bool]:
    """``handle_event``'s answers to navigation presses from now on."""
    found: list[bool] = []
    real = g.handle_event

    def spy(ev):
        answer = real(ev)
        if ev.nav is not None:
            found.append(answer)
        return answer

    g.handle_event = spy
    return found


def screen_answers(w: HostR) -> list[bool]:
    """``MinigameScreen.handle_event``'s answers (False: on to F14's ``RollbackKeys``)."""
    found: list[bool] = []
    screen = w.session.screen
    real = screen.handle_event

    def spy(ev):
        answer = real(ev)
        if ev.raw.type in (pygame.KEYDOWN, pygame.CONTROLLERBUTTONDOWN, pygame.MOUSEBUTTONDOWN):
            found.append(answer)
        return answer

    screen.handle_event = spy
    return found


def test_ac_f27_11_reach_by_page_keys_and_shoulders(world):
    w = world
    for stage, selected in (("S0", None), ("S1", "rusty_key")):
        g = w.stage(stage)
        if selected is not None:
            w.host.call(g._open_picker)
            w.host.call(g._picked, selected)
        order = w.scope.tab_order()
        want = [*sorted(g.spots, key=lambda s: (s.box.y, s.box.x)), g.items] \
            if False else order                              # F10's reading order
        assert order[:len(g.spots)] == [s for s in order if isinstance(s, Hotspot)]
        assert order[len(g.spots):] == [g.items] + ([g.put_away] if selected else [])
        n = len(order)
        for start in order:
            w.scope.focus(start, KEYS, sound=False)
            seen = []
            for _ in range(n):
                w.frame(*PAGE_DOWN)
                seen.append(w.scope.focused)
            assert seen == order[order.index(start) + 1:] + order[:order.index(start) + 1]
        for keys, step in ((PAGE_UP, -1), (LB, -1), (RB, 1)):
            w.scope.focus(order[0], KEYS, sound=False)
            w.frame(*keys)
            assert w.scope.focused is order[step % n]
    # Each step is used: True, MinigameUsed at the first, never on to RollbackKeys.
    g = w.stage("S0")
    said, passed = answers(g), screen_answers(w)
    for keys in (PAGE_DOWN, RB, PAGE_UP, LB):
        w.frame(*keys)
    assert said == passed == [True] * 4 and len(w.used()) == 1
    # Nothing focused (reached by click): Page Down focuses the first in Tab order.
    g = w.stage("S0", by=MOUSE)
    w.frame(*PAGE_DOWN)
    assert w.scope.focused is w.scope.tab_order()[0]
    # Room U: Page Down reaches key, which no arrow sequence reaches.
    g = w.open({"room": rooms.room("room_u"), "state": None})
    for _ in range(3):
        w.frame(*PAGE_DOWN)
        if focus(w) == "key":
            break
    assert focus(w) == "key"
    # Picker mode: the view's, not a focus step.
    g = w.stage("S1")
    w.host.call(g._open_picker)
    assert focus(w) == "list"
    for keys in (PAGE_DOWN, RB):
        w.frame(*keys)
        assert focus(w) == "list" and g.mode == PICKER
    # G4: with one focusable, tab() is False, so the key falls through to F23's fallback.
    # (Every valid room shows a hotspot under 07 G6, so the scope is cut to Items here.)
    g = w.stage("S0")
    w.host.call(w.scope.set_groups, [FocusGroup([g.items])])
    w.scope.focus(g.items, KEYS)
    said, passed = answers(g), screen_answers(w)
    for keys in (PAGE_DOWN, PAGE_UP):
        w.frame(*keys)
    assert said == passed == [False, False]
    # 200 seeded rooms of 2–12 spots (layout only): n Page Downs visit all n and wrap.
    import random
    rng = random.Random(27)
    for _ in range(200):
        room = room_rules.parse(rooms.random_room(rng, rng.randint(2, 12)))
        spots = [Widget(box=Box(*s.rect)) for s in room.spots]
        scope = FocusScope([FocusGroup(spots), FocusGroup([Widget(box=Box(24, 24, 200, 56))])])
        order = scope.tab_order()
        for start in order:
            scope.focus(start, KEYS, sound=False)
            seen = []
            for _ in order:
                assert scope.tab(True)
                seen.append(scope.focused)
            assert set(map(id, seen)) == set(map(id, order)) and seen[-1] is start


# --- AC-F27-12 — Items, the selection, and the picker ------------------------------------------

def view_of(g):
    return g.view._target


def scope_names(w: HostR) -> list[str]:
    g = w.session.plugin
    return [name_of(g, x) for x in w.scope.widgets()]


def test_ac_f27_12_items_selection_and_picker(world):
    w = world
    using = "Choose where to use Rusty Key, or combine it in Items."
    for by, device in ((KEYS, "keys"), (MOUSE, "mouse")):
        # Items: the picker over held items only, its first row selected; Use.
        g = w.stage("S1", by=by)
        items(w, device)
        view = view_of(g)
        assert [r.entry.name for r in view.rows()] == ["rusty_key"]       # no tip row
        assert (view.selected, view.pick.word, w.hint()) == ("rusty_key", "Use",
                                                             "Choose an item to use.")
        assert not {"items", "put_away"} & set(scope_names(w)) and "back" in scope_names(w)
        assert focus(w) == ("list" if by is KEYS else None)
        assert g.picker.backing == (220, 24, 840, 598)
        # Pick Rusty Key: room mode; Put away at (240, 24); Items focused or nothing.
        pick(w, "rusty_key", device)
        assert (g.mode, g.selected, w.hint()) == (ROOM, "rusty_key", using)
        assert focus(w) == ("items" if by is KEYS else None)
        w.frame()
        assert g.put_away_text == "Put away Rusty Key"
        assert (g.put_away.box.x, g.put_away.box.y) == (240, 24)
        # Put away by the button: the selection goes, Put away leaves the scope.
        act(w, "put_away", device)
        assert (g.selected, w.hint()) == (None, LOOK_AROUND)
        assert "put_away" not in scope_names(w)
        assert focus(w) == ("items" if by is KEYS else None)
    # Put away by Backspace, right click, and east: used, never the game menu.
    for device in ("keys", "mouse", "pad"):
        g = w.stage("S1", by=MOUSE if device == "mouse" else KEYS)
        w.host.call(g._open_picker)
        w.host.call(g._picked, "rusty_key")
        said, passed = answers(g), screen_answers(w)
        back(w, device)
        assert (g.selected, w.hint(), said, passed) == (None, LOOK_AROUND, [True], [True])
        assert focus(w) == (None if device == "mouse" else "items")
        assert w.changes == ()
    # Picker Back: the button, Backspace, right click, east: room mode, selection kept.
    for device, how in (("keys", "button"), ("mouse", "button"), ("keys", "nav"),
                        ("mouse", "nav"), ("pad", "nav")):
        g = w.stage("S1", by=MOUSE if device == "mouse" else KEYS)
        w.host.call(g._open_picker)
        w.host.call(g._picked, "rusty_key")
        items(w, device)
        if how == "button":
            act(w, "back", device)
        else:
            back(w, device)
        assert (g.mode, g.selected, w.hint()) == (ROOM, "rusty_key", using)
        assert focus(w) == (None if device == "mouse" else "items")
        assert w.changes == ()
    # Room W's no-combine twin: hint_using_only; the word stays Use; String replaces it.
    g = w.open({"room": rooms.room("room_w_only"), "state": None}, ("string", "door_key"))
    items(w, "keys")
    pick(w, "door_key", "keys")
    assert w.hint() == "Choose where to use Door Key."
    items(w, "keys")
    assert view_of(g).pick.word == "Use"
    pick(w, "string", "keys")
    assert (g.selected, w.hint()) == ("string", "Choose where to use String.")
    # S3, Magnet selected: Combine; picking Magnet again keeps it, with no request.
    g = w.stage("S3")
    items(w, "keys")
    pick(w, "magnet", "keys")
    items(w, "keys")
    assert (view_of(g).pick.word, w.hint()) == ("Combine",
                                                "Choose an item to combine with Magnet.")
    pick(w, "magnet", "keys")
    assert (g.mode, g.selected, w.changes, g.finishes) == (ROOM, "magnet", (), [])
    # Left from a row, Down from the last row: Back, at 100% and at 150% with two hint lines.
    for scale in (1.0, 1.5):
        for keys in (LEFT, DOWN):
            w.shell.painter.set_text_scale(lambda: scale)
            g = w.stage("S3")
            if scale == 1.5:
                w.host.call(g.ctx.hint, "A hint long enough to need two lines at this text "
                                        "size, so the area is as short as it gets here.")
                assert len(w.session.frame.hint_lines) == 2
            items(w, "keys")
            w.frame()
            view = view_of(g)
            if keys is DOWN:
                while view.list.focus_row < len(view.list_rows) - 1:
                    w.frame(*DOWN)
            w.frame(*keys)
            assert focus(w) == "back", (scale, keys)
    w.shell.painter.set_text_scale(lambda: 1.0)
    # S0, nothing held: codex_empty, no pick button; Back closes.
    g = w.stage("S0")
    items(w, "keys")
    assert view_of(g).tabs == () and scope_names(w) == ["back"] and focus(w) == "back"
    w.frame(*ENTER)
    assert g.mode == ROOM
    # Captions: kept over motion and arrows; cleared by a selection change, Put away, or
    # Items; replaced by another activation.
    g = w.stage("S1")
    act(w, "door", "keys")
    w.frame(H.motion((700, 200)), *UP, *DOWN)
    assert w.hint() == "Locked tight." == g.caption
    act(w, "window", "keys")
    assert w.hint() == "Snow, as far as you can see."
    items(w, "keys")
    assert (g.caption, w.hint()) == (None, "Choose an item to use.")
    pick(w, "rusty_key", "keys")
    assert w.hint() == using
    act(w, "door", "keys")
    assert w.hint() == "That doesn't work."
    w.frame(*BACKSPACE)
    assert (g.caption, w.hint()) == (None, LOOK_AROUND)


# --- AC-F27-13 — Back and used inputs (C1) -----------------------------------------------------

def wheel_up(w: HostR, pos=(620, 465)) -> bool:
    """The wheel turned up over drawer: the screen's answer (False: F14's StepBack(1),
    refused with F23's cue once ``MinigameUsed`` was posted, AC-F23-16)."""
    screen = w.session.screen
    return screen.handle_event(H.wheel(pos, 1))


def test_ac_f27_13_back_and_used_inputs(world, tmp_path):
    w = world
    centers = [s.box.center for s in w.stage("S0").spots]
    # Nothing, or pointer motion over every spot: unused, so the wheel goes back.
    for moves in ((), centers):
        g = w.stage("S0")
        for pos in moves:
            w.frame(H.motion(pos))
        assert w.used() == [] and wheel_up(w) is False
    # One arrow, Tab, Page Down, RB, a look, Items then picker Back: used.
    cases = {"arrow": [RIGHT], "tab": [TAB], "page": [PAGE_DOWN], "rb": [RB],
             "page_up": [PAGE_UP], "lb": [LB], "look": [ENTER],
             "picker": ["items", BACKSPACE]}
    for name, steps in cases.items():
        g = w.stage("S0")
        passed = screen_answers(w)
        for s in steps:
            if s == "items":
                w.host.call(w.scope.focus, g.items, KEYS)
                w.frame(*ENTER)
            else:
                w.frame(*s)
        assert len(w.used()) == 1 and all(passed), name
        if name in ("page_up", "lb"):
            assert passed == [True]                     # a focus step, not StepBack
        assert wheel_up(w) is False and len(w.used()) == 1
    # Backspace, right click, east with no selection: unused; Backspace does nothing, right
    # click and east reach the game menu (F23's fallback).
    for keys, menu in ((BACKSPACE, False), (click((700, 200), 3), True), (EAST, True)):
        g = w.stage("S0")
        passed = screen_answers(w)
        w.frame(*keys)
        assert w.used() == [] and passed == [not menu]
    # Template L, the second run (after the take was accepted), nothing used: back lands on
    # the first run's P: rusty_key not held, attic_state None, hook shown.
    from tests.minigames.bundled.test_room_headless import _game
    from tests.runtime.minigame_story import ALL, finish, launched, start_of
    program, sigs = _game(tmp_path / "l", loop=True)
    interp = launched(program, sigs=sigs)
    interp.new_game(42)
    interp.run(10_000)
    start_of(interp.take_commands(ALL))
    second = start_of(finish(interp, TAKE_HOOK, (CodexChange("give", "rusty_key"),)))
    g = w.open(None, cmd=second)
    while not w.running():
        w.frame()                                       # the fade in
    assert "hook" not in g.keys and w.used() == []
    assert wheel_up(w) is False
    interp.post(StepBack(1))
    interp.run(10_000)
    landed = start_of(interp.take_commands(ALL))
    assert landed.base.items == () and landed.args["state"] is None
    assert interp.checkpoint().variables["attic_state"] is None
    g = w.open(None, cmd=landed)
    assert "hook" in g.keys


# --- AC-F27-14 — Same room on replay; host endings ---------------------------------------------

def loop_runs(tmp, n: int):
    """Driver D on Template L: the interpreter after ``n`` accepted runs (take hook, then use
    drawer), and the StartMinigame of the waiting run."""
    from tests.minigames.bundled.test_room_headless import _game
    from tests.runtime.minigame_story import ALL, finish, launched, start_of, step
    program, sigs = _game(tmp, loop=True)
    interp = launched(program, sigs=sigs)
    interp.new_game(42)
    interp.run(10_000)
    cmd = start_of(interp.take_commands(ALL))
    runs = [(TAKE_HOOK, (CodexChange("give", "rusty_key"),)), (USE_DRAWER, ())]
    for result, changes in runs[:n]:
        out = finish(interp, result, changes)
        while not [c for c in out if type(c) is StartMinigame]:
            step(interp)                                # "The key turns. Inside, a magnet."
            out += interp.take_commands(ALL)
        cmd = start_of(out)
    return program, sigs, interp, cmd


def opening(w: HostR) -> bytes:
    """The opening picture of a session started with ``frame=False`` (before any update; on
    a cut the host's opening surface is already the thumbnail's and released)."""
    return pygame.image.tobytes(w.host._offscreen((1280, 720), w.session.screen.draw_running),
                                "RGB")


def test_ac_f27_14_same_room_on_replay_and_host_endings(world, tmp_path, monkeypatch):
    from engine.minigames.context import DiceHandle
    from tests.runtime.minigame_story import ALL, at_a, finish, start_of
    w = world
    calls = []
    for method in ("roll", "pick", "decimal", "shuffle"):
        monkeypatch.setattr(DiceHandle, method, lambda self, *a, _m=method, **k: calls.append(_m))
    # No ctx.random call while playing; equal args and held items, equal opening pictures.
    g = w.stage("S1")
    act(w, "window", "keys")
    items(w, "keys")
    pick(w, "rusty_key", "keys")
    act(w, "drawer", "keys")
    assert g.finishes == [USE_DRAWER] and calls == []
    pictures = []
    for seed in (1, 2, 1):
        w.stage("S1", seed=seed, frame=False)
        pictures.append(opening(w))
    assert pictures[0] == pictures[1] == pictures[2]
    # A look, a selection, and an open picker, then a save restored and a back landing on P:
    # each opens S1's opening picture, and drawer with Rusty Key gives the use result.
    program, sigs, interp, s1 = loop_runs(tmp_path / "l", 1)
    g = w.open(None, cmd=s1)
    w.host.call(spot(g, "window").activate)
    w.host.call(g._open_picker)
    w.host.call(g._picked, "rusty_key")
    w.host.call(g._open_picker)
    saved = interp.checkpoint().to_json()
    fresh = at_a(program, sigs=sigs)
    assert fresh.restore(GameState.from_json(saved)).result.value == "ok"
    restored = start_of(fresh.take_commands(ALL))
    out = finish(interp, USE_DRAWER)
    interp.take_commands(ALL)
    interp.post(StepBack(1))
    interp.run(10_000)
    landed = start_of(out + interp.take_commands(ALL))
    assert landed.restored and landed.base.items == ("rusty_key",)
    for cmd in (restored, landed):
        g = w.open(None, cmd=cmd, frame=False)
        assert (g.mode, g.selected, g.caption, w.hint()) == (ROOM, None, None, LOOK_AROUND)
        assert opening(w) == pictures[0]
        w.host.call(g._open_picker)
        w.host.call(g._picked, "rusty_key")
        w.host.call(spot(g, "drawer").activate)
        assert g.finishes == [USE_DRAWER]
    # Two clicks in one frame, then input and update after the finish: one finish, one give.
    g = w.stage("S0", by=MOUSE)
    w.frame(*click((340, 550)), *click((340, 550)))
    g.update(1.0)
    g._activate("window")
    g._open_picker()
    g._picked("rusty_key")
    assert len(g.finishes) == 1 and w.changes == (CodexChange("give", "string"),)
    # Shift+F8 and Skip Game at S1 with a selection and the picker open: the first exit, no
    # requests; Driver D accepts it: attic_state equals it, held items unchanged.
    first_exit = Outcome({"action": "exit", "hotspot": "out", "item": None, "gone": ["hook"]},
                         ())
    for how in ("shift_f8", "skip"):
        g = w.open(None, cmd=dataclasses.replace(s1, skippable=True, restored=True))
        w.host.call(g._open_picker)
        w.host.call(g._picked, "rusty_key")
        w.host.call(g._open_picker)
        if how == "shift_f8":
            w.frame(H.key(pygame.K_F8, pygame.KMOD_SHIFT))
        else:
            assert w.host.can_skip()
            w.host.skip(w.session)
        settle(w)
        assert [(d.result, d.changes) for d in w.done()] == [(first_exit.result, ())]
    _, _, interp, _ = loop_runs(tmp_path / "m", 1)
    finish(interp, first_exit.result)
    assert interp.checkpoint().variables["attic_state"] == first_exit.result
    assert interp.codex.items() == ("rusty_key",)
    # Room S (stuck) with skippable: Skip Game leaves by its first exit.
    g = w.open({"room": rooms.room("room_s"), "state": None}, skippable=True)
    w.host.skip(w.session)
    settle(w)
    assert [d.result["hotspot"] for d in w.done()] == ["out"]


# --- AC-F27-15 — Settings changed mid-run ------------------------------------------------------

def test_ac_f27_15_settings_changed_mid_run(world):
    from engine.ui.layouts import button_height
    w = world
    g = w.stage("S1")
    items(w, "keys")
    pick(w, "rusty_key", "keys")
    act(w, "door", "keys")
    go(w, "drawer", "keys")
    w.frame()
    caption, boxes = w.hint(), [s.box for s in g.spots]
    before = pygame.image.tobytes(w.frame(), "RGB")
    w.shell.painter.set_text_scale(lambda: 1.5)
    w.frame()
    area = w.session.area
    lay = room_rules.room_layout(area, button_h=button_height(scale=1.5),
                                 put_away_w=g.put_away.box.w)
    assert (g.items.box, g.put_away.box) == (Box(*lay.items), Box(*lay.put_away))
    assert g.items.box.h == button_height(scale=1.5) > button_height()
    assert [s.box for s in g.spots] == boxes and focus(w) == "drawer"
    assert (g.selected, g.caption, w.hint()) == ("rusty_key", caption, caption)
    w.shell.painter.set_text_scale(lambda: 1.0)
    w.frame()
    assert pygame.image.tobytes(w.frame(), "RGB") == before
    # The picker by keys at 150%: kept, and the view built again once, at the next draw.
    items(w, "keys")
    view = view_of(g)
    builds = []
    real = view.build
    view.build = lambda box, scale: builds.append((box, scale)) or real(box, scale)
    w.shell.painter.set_text_scale(lambda: 1.5)
    w.frame()
    picker = room_rules.picker_layout(w.session.area, button_h=button_height(scale=1.5))
    assert g.mode == PICKER and builds == [(Box(*picker.view), 1.5)]
    w.frame()
    assert len(builds) == 1
    # layout(area) alone: recomputed once, at the next draw, never before.
    w.shell.painter.set_text_scale(lambda: 1.0)
    g = w.stage("S1")
    w.frame()
    count = g.recomputes
    w.host.call(g.layout, w.session.area)
    assert g.recomputes == count
    w.frame()
    w.frame()
    assert g.recomputes == count + 1
    # Reduced motion on: the next frame is pixel-equal.
    before = pygame.image.tobytes(w.frame(), "RGB")
    w.shell.reduce_motion = True
    assert pygame.image.tobytes(w.frame(), "RGB") == before


# --- AC-F27-18 — The room on screen ------------------------------------------------------------

GREY, KEY_BROWN, SHADOW = (0x80, 0x80, 0x80), (0xC0, 0x80, 0x40), (0x1A, 0x1A, 0x1A)


def near(a, b, tol: int = 8) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def count(surface: pygame.Surface, color) -> int:
    return pygame.mask.from_threshold(surface, (*color, 255), (9, 9, 9, 255)).count()


def spy_canvas(w: HostR) -> tuple[list, list]:
    """(draw_text calls, panel boxes) from now on."""
    texts, panels = [], []
    canvas, painter = w.ui.canvas, w.shell.painter
    real_text, real_panel = canvas.draw_text, painter.panel

    def draw_text(text, font, color, pos, **kw):
        texts.append((text, font, tuple(pos)))
        return real_text(text, font, color, pos, **kw)

    def panel(box, area="panel", **kw):
        panels.append(((box.x, box.y, box.w, box.h), area))
        return real_panel(box, area, **kw)

    canvas.draw_text, painter.panel = draw_text, panel
    return texts, panels


def test_ac_f27_18_the_room_on_screen(world, caplog):
    from engine.ui.layouts import pitch
    w = world
    g = w.stage("S0", by=MOUSE, frame=False)
    picture = pygame.image.frombytes(opening(w), (1280, 720), "RGB")
    # The opening picture: no ring, no tag; Items; the base hint; no heading.
    assert near(picture.get_at((514, 465))[:3], GREY) and near(picture.get_at((874, 200))[:3],
                                                                GREY)
    frame = w.session.frame
    assert frame.heading is None and frame.hint_lines == (LOOK_AROUND,)
    assert "items" in scope_names(w)
    w.frame()
    # The background and hook's image, fitted (64×32 in 64×96), not stretched.
    assert near(w.px(640, 360), GREY)
    assert near(w.px(172, 348), KEY_BROWN) and near(w.px(172, 310), GREY)
    # Nothing focused: pixel-equal to a render with no hotspot widgets.
    plain = pygame.image.tobytes(w.frame(), "RGB")
    groups = list(w.scope.groups)
    w.host.call(w.scope.set_groups, groups[1:])
    assert pygame.image.tobytes(w.frame(), "RGB") == plain
    w.host.call(w.scope.set_groups, groups)
    # Drawer focused: the ring's color and shadow bands, then the picture; the tag.
    texts, panels = spy_canvas(w)
    w.frame(H.motion((620, 465)))
    assert near(w.px(514, 465), (255, 255, 255)) and near(w.px(517, 465), SHADOW)
    assert near(w.px(521, 465), GREY)
    lines, tw, th = g._tags[("Desk drawer", 24)]
    assert lines == ("Desk drawer",) and th == pitch(24) + 12
    row = g.lay.row
    x, y, _, _ = box = room_rules.tag_box((520, 420, 200, 90), tw, th,
                                          row_bottom=row[1] + row[3], area=w.session.area)
    assert (box, "panel") in panels
    (label,) = [t for t in texts if t[0] == "Desk drawer"]
    assert label[2] == (x + 12, y + 6) and label[1].size == 24
    assert label[1].ref is None                          # ui.text_font
    # S1: hook hidden, so no pixel of its image.
    w.stage("S1")
    assert count(w.frame(), KEY_BROWN) == 0
    # Picker mode: the backing panel at x 220–1060; Items and Put away not drawn.
    g = w.stage("S1")
    w.host.call(g._open_picker)
    texts, panels = spy_canvas(w)
    w.frame()
    assert ((220, 24, 840, 598), "panel") in panels
    assert not [t for t in texts if t[0] in ("Items", "Put away Rusty Key")]
    # A missing hotspot image: F04's placeholder centered in hook's rect, clipped to it, and
    # F04's dev warning once.
    caplog.set_level(logging.WARNING)
    room = rooms.room()
    room["hotspots"]["hook"]["image"] = "attic nope"
    room["hotspots"]["door"]["rect"] = [40, 120, 90, 420]                # off hook
    room["hotspots"]["out"]["rect"] = [40, 120, 90, 420]
    for _ in range(2):
        g = w.open({"room": room, "state": None}, by=MOUSE)
        shot = w.frame()
    assert not near(shot.get_at((172, 348))[:3], GREY)                   # inside hook
    assert near(shot.get_at((138, 348))[:3], GREY) and near(shot.get_at((206, 348))[:3], GREY)
    warned = [r for r in caplog.records if r.name == "vn.assets" and "attic nope" in
              r.getMessage()]
    assert len(warned) == 1


# --- AC-F27-19 — Tokens, words, and long text --------------------------------------------------

def configured(tmp_path, text: str) -> HostR:
    """Host R with ``config.toml`` (``text``): F23 s5b's ``PluginTables`` checks
    ``[theme.plugin]`` and ``[words.plugin]`` against the declarations."""
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(text, encoding="utf-8")
    result = load_config(GamePaths.for_game(root))
    assert result.errors == [], [e.format() for e in result.errors]
    tables = PluginTables(result.config.theme.plugin, result.config.words.plugin, SOUNDS,
                          dev=True)
    tables.check([ENTRY])
    return HostR(config=result.config, tables=tables)


def _luminance(rgb) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


OVERRIDES = {"hint": "Regarde.", "hint_using_only": "Où utiliser {item} ?",
             "hint_picker": "Choisis.", "hint_combine": "Avec {item} ?", "items": "Objets",
             "back": "Retour", "use": "Utiliser", "combine": "Combiner",
             "put_away": "Ranger {item}", "need_item": "Il te faut un objet.",
             "no_use": "Rien.", "no_combine": "Non."}


def test_ac_f27_19_tokens_words_and_long_text(tmp_path):
    from tests.minigames.host_u import entry
    from tests.minigames.host_u import ITEMS as ITEM_CATEGORY, TIPS
    from engine.runtime.codex import CodexIndex
    # Unit rows: the tokens' contrast with each other, and the ring on any 12-bit color.
    white, shadow = (255, 255, 255), (0x1A, 0x1A, 0x1A)
    assert contrast(white, shadow) >= 4.5
    assert min(max(contrast(c, white), contrast(c, shadow))
               for c in ((r * 17, g * 17, b * 17) for r in range(16) for g in range(16)
                         for b in range(16))) >= 3
    # The title (the save description's) and hint_using with braces.
    w = configured(tmp_path / "a", '[words.plugin.puzzle_room]\ntitle = "Salle"\n'
                                    'hint_using = "Utilise {item} {0} {}"\n')
    g = w.stage("S1")
    assert w.session.title == "Salle"
    w.host.call(g._open_picker)
    w.host.call(g._picked, "rusty_key")
    assert w.hint() == "Utilise Rusty Key {0} {}" and not w.fatal
    # Every other word in its place.
    body = "".join(f'{k} = "{v}"\n' for k, v in OVERRIDES.items())
    w = configured(tmp_path / "b", "[words.plugin.puzzle_room]\n" + body)
    g = w.open({"room": rooms.room("room_w_only"), "state": None}, ("string", "door_key"))
    assert w.hint() == "Regarde." and g.items.label() == "Objets"
    w.host.call(spot(g, "box").activate)
    assert w.hint() == "Il te faut un objet."
    w.host.call(g._open_picker)
    assert (w.hint(), view_of(g).pick.word, g.back.label()) == ("Choisis.", "Utiliser",
                                                                "Retour")
    w.host.call(g._picked, "door_key")
    w.frame()
    assert (w.hint(), g.put_away_text) == ("Où utiliser Door Key ?", "Ranger Door Key")
    w.host.call(spot(g, "box").activate)
    assert w.hint() == "Rien."
    g = w.open({"room": rooms.room("room_w"), "state": None}, ("string", "door_key"))
    w.host.call(g._open_picker)
    w.host.call(g._picked, "door_key")
    w.host.call(g._open_picker)
    assert (w.hint(), view_of(g).pick.word) == ("Avec Door Key ?", "Combiner")
    w.host.call(g._picked, "string")
    assert w.hint() == "Non."
    # The ring color token.
    w = configured(tmp_path / "c", '[theme.plugin.puzzle_room.spot]\nring_color = "#FF0000"\n')
    w.stage("S0", by=MOUSE)
    w.frame(H.motion((620, 465)))
    assert near(w.px(514, 465), (255, 0, 0))
    # A 40-code-point title at 150%: Put away is 480 wide; only the title is cut.
    long = "Lantern " * 4 + "Glowing!"
    assert len(long) == 40
    index = CodexIndex((entry("rusty_key", "item", long), entry("string", "item", "String")),
                       (ITEM_CATEGORY, TIPS))
    w = HostR(index=index)
    w.shell.painter.set_text_scale(lambda: 1.5)
    g = w.stage("S1")
    w.host.call(g._open_picker)
    w.host.call(g._picked, "rusty_key")
    w.frame()
    assert g.put_away.box.w == 480
    assert g.put_away_text.startswith("Put away ") and g.put_away_text.endswith("…")
    assert long.startswith(g.put_away_text[len("Put away "):-1])
    # Long labels at 150%: each tag inside the area, the whole label drawn (wrapped, G5).
    labels = ["a" * 40, "中" * 20, "😀", "שלום", "W" * 40]
    room = rooms.room("room_u")
    for n, label in enumerate(labels):
        room["hotspots"][f"x{n}"] = {"rect": [100 + 200 * n, 560, 64, 64], "label": label}
    g = w.open({"room": room, "state": None}, by=MOUSE)
    area = w.session.area
    for n, label in enumerate(labels):
        texts, _ = spy_canvas(w)
        w.frame(H.motion((132 + 200 * n, 592)))
        assert focus(w) == f"x{n}"
        lines, tw, th = g._tags[(label, g._sizes[2])]
        assert "".join(lines) == label and [t[0] for t in texts if t[0] in lines] == list(lines)
        row = g.lay.row
        x, y, bw, bh = room_rules.tag_box(spot(g, f"x{n}").spot.rect, tw, th,
                                          row_bottom=row[1] + row[3], area=area)
        assert area.x <= x and x + bw <= area.right and area.y <= y and y + bh <= area.bottom
    assert len(g._tags[("W" * 40, g._sizes[2])][0]) == 2                 # two lines


# --- AC-F27-20 — W179, a room that can't be left -----------------------------------------------

def coded(caplog, code: str) -> list[logging.LogRecord]:
    found = [r for r in caplog.records if getattr(r, "code", None) == code]
    caplog.clear()
    return found


def test_ac_f27_20_w179_host_rows(world, caplog, warned, monkeypatch):
    w = world
    caplog.set_level(logging.DEBUG, logger="vn.plugin")
    stuck = {"room": rooms.room("room_s"), "state": None}
    want = room_rules.w179_text(room_rules.parse(stuck["room"]), (), ())
    assert want.startswith('puzzle_room in "bg attic" can\'t be left')
    g = w.open(stuck)
    (record,) = coded(caplog, "W179")
    assert (record.getMessage(), record.name, record.levelno) == (want, "vn.plugin",
                                                                  logging.WARNING)
    w.open(stuck)
    assert coded(caplog, "W179") == []                   # once per text
    w.open({"room": rooms.stuck_room(0), "state": None})
    assert len(coded(caplog, "W179")) == 1               # another background
    # Room S stays playable: a look, then Skip Game's first exit is covered by AC-F27-14.
    g = w.open(stuck)
    w.host.call(spot(g, "window").activate)
    assert w.hint() == "Snow, as far as you can see."
    # 101 distinct texts: exactly 100 records. The first 97 stand for earlier rooms (texts
    # already in _WARNED), so only the last four rooms start a session here.
    warned.clear()
    warned.update(f"an earlier room's text {n}" for n in range(97))
    for n in range(4):
        w.open({"room": rooms.stuck_room(n), "state": None}, frame=False)
    assert len(coded(caplog, "W179")) == 3 and len(warned) == 100
    # Release: none, and reach isn't called.
    warned.clear()
    reached = []
    real = room_rules.reach
    monkeypatch.setattr(room_rules, "reach", lambda *a: reached.append(a) or real(*a))
    HostR(dev=False).open(stuck)
    assert coded(caplog, "W179") == [] and reached == []


# --- AC-F27-21 — W180, a hotspot under the buttons or hint -------------------------------------

def test_ac_f27_21_w180_host_rows(world, caplog, warned):
    w = world
    caplog.set_level(logging.DEBUG, logger="vn.plugin")
    room = {"background": "bg attic", "hotspots": {
        "low": {"rect": [300, 560, 200, 100], "label": "Low"},
        "out": {"rect": [1000, 300, 100, 100], "label": "Door", "exit": True}}}
    two_lines = "A hint long enough to need two lines at this text size, so the area " \
                "is as short as it gets here."

    def at(scale: float, w: HostR) -> None:
        w.shell.painter.set_text_scale(lambda: scale)
        g = w.session.plugin
        w.host.call(g.ctx.hint, two_lines)
        w.frame()

    g = w.open({"room": room, "state": None})
    assert coded(caplog, "W180") == []                   # 100%, one-line hint
    at(1.5, w)
    assert len(w.session.frame.hint_lines) == 2
    (record,) = coded(caplog, "W180")
    assert record.getMessage() == room_rules.w180_texts(
        g.room, g.keys, row=g.lay.row, area=w.session.area)[0]
    at(1.0, w)
    at(1.5, w)
    assert coded(caplog, "W180") == []
    warned.clear()
    release = HostR(dev=False)
    release.open({"room": room, "state": None})
    at(1.5, release)
    assert coded(caplog, "W180") == []


# --- AC-F27-25 — CI guard: costs ---------------------------------------------------------------

def test_ac_f27_25_costs(world):
    import time
    w = world
    # ctx.image: once for the background and once per shown spot with an image, at start.
    w.stage("S2", by=MOUSE)                              # magnet (an image) shown
    assert w.images == ["bg attic", "attic magnet"]
    w.stage("S1", by=MOUSE)                              # hook hidden
    assert w.images == ["bg attic"]
    g = w.stage("S0", by=MOUSE)
    assert w.images == ["bg attic", "attic key"]
    w.frame(H.motion((620, 465)))
    w.frames(2)
    assert focus(w) == "drawer"
    # 600 frames with drawer focused: nothing new cached (text, rescales, shapes), at most
    # 8 ring fills and one tag panel per frame, no recompute, no ctx.image.
    puts, fills, tags = [], [], []
    cache = w.assets.cache
    real_put, real_fill, real_panel = cache.put, w.ui.canvas.fill, w.shell.painter.panel
    ring = {g.ring_color, g.shadow_color}
    cache.put = lambda key, *a, **k: puts.append(key) or real_put(key, *a, **k)
    w.ui.canvas.fill = lambda color, rect=None: (
        fills.append(1) if tuple(color) in ring else None, real_fill(color, rect))[1]
    tag = g._tags[("Desk drawer", 24)]
    w.shell.painter.panel = lambda box, *a, **k: (
        tags.append(1) if (box.w, box.h) == tag[1:] else None, real_panel(box, *a, **k))[1]
    recomputes = g.recomputes
    for _ in range(600):
        w.frame()
    assert puts == [] and g.recomputes == recomputes and w.images == ["bg attic",
                                                                      "attic key"]
    assert len(fills) == 8 * 600 and len(tags) == 600
    # The checks on the bound room: under 5 ms (a loose CI limit).
    args = {"room": rooms.bound_room(),
            "state": {"gone": [f"s{i}" for i in range(39)] + ["zzz"]}}
    names = rooms.bound_names()
    assert room_rules.problem(args) is None and room_rules.story_problem(args, names) is None
    began = time.perf_counter()
    room_rules.problem(args)
    room_rules.story_problem(args, names)
    assert time.perf_counter() - began < 0.005
