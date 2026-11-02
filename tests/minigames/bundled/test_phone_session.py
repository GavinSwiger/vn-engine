"""F26-3 — the phone chat on screen (``06-acceptance.md`` AC-F26-07 to 16, 18 to 21, 24).

**Host C**: F23's Host U (``tests/minigames/host_u.py``) with the bundled ``PhoneChat`` from
``BUNDLED``: SDL dummy, offscreen 1280×720, default theme with F10's button sounds, 100% text,
1/60 s frames, the Audio spy and post sink, the ``fatal`` recorder, dev on, ``vn.plugin``
captured. Args are Template C's ``late_chat`` (``tests/fixtures/F26/chats.py``) unless a row
says otherwise; sessions start as a cut (``restored``), "reached by Enter" unless a row says
otherwise. One world per test (one AC); each row opens a fresh session. ``_WARNED`` is cleared
around every test.

**t0** is the first RUNNING frame (the first ``update``). Timing rows count frames: an input
handled in a frame comes before that frame's ``update``, so a wait it starts has had one
update when the frame ends. Rows whose subject isn't timing skip waits with ``skip_waits``
(the plugin's hurry, through ``host.call`` so F23's first-focus rule applies).

Back rows (AC-F26-13) assert the screen's answer: an unused wheel, Page key, or LB returns
False from ``MinigameScreen.handle_event``, so it reaches F14's ``RollbackKeys`` (StepBack(1);
AC-F23-16 covers what F14 does with it), and ``MinigameUsed`` is posted only after a used
press.
"""

import dataclasses
import logging

import pygame
import pytest

from engine.core.config_schema import ThemeConfig
from engine.minigames.api import PluginEvent
from engine.minigames.bundled import phone_chat, phone_rules, rule_text
from engine.minigames.bundled.phone_chat import Phase, PhoneChat
from engine.minigames.bundled.phone_rules import Message, TimeMark
from engine.minigames.bundled.phone_rules import p as pitch_of_size
from engine.minigames.host import Phase as HostPhase
from engine.ui.focus import Box
from engine.ui.nav import InputKind, Nav
from tests.fakes.ui_shell import UiHarness
from tests.fixtures.F26 import chats
from tests.minigames.host_u import HostU

H = UiHarness
DT = 1 / 60
ACTIVATE = "sfx/activate.ogg"


def _sounds() -> ThemeConfig:
    cfg = ThemeConfig()
    return dataclasses.replace(cfg, button=dataclasses.replace(
        cfg.button, focus_sound="sfx/focus.ogg", activate_sound=ACTIVATE))


SOUNDS = _sounds()


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture(autouse=True)
def warned():
    """``phone_chat._WARNED`` is empty before and after each test (W176 is per process)."""
    phone_chat._WARNED.clear()
    yield phone_chat._WARNED
    phone_chat._WARNED.clear()


@pytest.fixture
def world(game):
    return HostU(game, cfg=SOUNDS)


# --- Driving --------------------------------------------------------------------------------

def tap(key: int, mod: int = 0) -> tuple:
    return H.key(key, mod), H.key(key, mod, up=True)


def pad(button: int) -> tuple:
    return H.pad(button), H.pad(button, up=True)


ENTER, SPACE, DOWN = tap(pygame.K_RETURN), tap(pygame.K_SPACE), tap(pygame.K_DOWN)
PAGE_UP, PAGE_DOWN = tap(pygame.K_PAGEUP), tap(pygame.K_PAGEDOWN)
SOUTH, DPAD_DOWN = pad(pygame.CONTROLLER_BUTTON_A), pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN)
LB = pad(pygame.CONTROLLER_BUTTON_LEFTSHOULDER)


def click(pos, button: int = 1) -> tuple:
    return H.down(pos, button), H.up(pos, button)


def open_chat(w: HostU, args=chats.LATE, *, by: InputKind = InputKind.KEYS, cmd=None,
              **changes) -> PhoneChat:
    """A fresh session (a cut), reached by ``by``; ``g.finishes`` records ``ctx.finish``."""
    w.posted.clear()
    w.shell.stack.last_input = by
    if cmd is None:
        cmd = w.command("phone_chat", args)
    if changes:
        cmd = dataclasses.replace(cmd, **changes)
    w.host.start(cmd)
    assert not w.fatal, [f.format() for f in w.fatal]
    s = w.session
    g = s.plugin
    port = s.ctx._port
    real = port.finish
    g.finishes = []

    def finish(result):
        g.finishes.append(result)
        return real(result)

    port.finish = finish
    return g


def skip_waits(w: HostU, g: PhoneChat) -> None:
    """Hurry every wait until rows show (no update runs: ``since_buttons`` is 0)."""
    while g.phase in (Phase.BEGIN, Phase.GAP, Phase.TYPING):
        if g.phase is Phase.BEGIN:
            w.host.call(g.update, 0.0)
        else:
            w.host.call(g._hurry)


def frames_until(w: HostU, cond, limit: int = 400, each=None) -> int:
    """Run frames until ``cond()`` holds after one; the number run."""
    for n in range(1, limit + 1):
        w.frame()
        if each is not None:
            each()
        if cond():
            return n
    raise AssertionError("never happened")


def texts(g: PhoneChat) -> list[str]:
    return [i.text for i in g.items if isinstance(i, Message)]


def record_events(g: PhoneChat) -> list[bool]:
    """``handle_event``'s answers from now on."""
    answers: list[bool] = []
    real = g.handle_event

    def spy(ev):
        answer = real(ev)
        answers.append(answer)
        return answer

    g.handle_event = spy
    return answers


def thread_center(g: PhoneChat) -> tuple[float, float]:
    return Box(*g.layout_now.thread).center


def pill_center(g: PhoneChat, i: int) -> tuple[float, float]:
    return g.replies.pill(i).center


def scope(w: HostU):
    return w.session.scope


# --- AC-F26-07 — Flow and timing --------------------------------------------------------------

def test_ac_f26_07_flow_and_timing(world):
    w = world
    g = open_chat(w, chats.args(chats.FLOW, time=None))
    w.frame()                                                       # t0
    assert (g.phase, g.items, g.clock, g.labels) == (Phase.GAP, [], None, ())
    assert scope(w).groups == [] and g.layout_now.reply[3] == 56    # the placeholder field
    never_typing = []
    assert frames_until(w, lambda: g.typing is not None) == 30      # 500 ms
    typing = g.view[-1]
    assert (typing.kind, typing.x, typing.sender) == ("typing", 0, "Sayori")   # left side
    assert frames_until(w, lambda: texts(g) == ["hi"]) == 36        # +600 ms
    assert g.typing is None and g.view[-1].y == typing.y and g.view[-1].kind == "them"
    assert frames_until(w, lambda: len(texts(g)) == 2,
                        each=lambda: never_typing.append(g.typing)) == 30   # +500 ms, me
    assert never_typing == [None] * 30
    me = [i for i in g.view if i.kind == "me"][0]
    assert me.x + me.w == pytest.approx(g.layout_now.thread[2])     # right side
    assert [i.text for i in g.items if isinstance(i, TimeMark)] == ["1 AM", "2 AM"]
    assert g.clock == "2 AM"                                        # the same frame
    assert frames_until(w, lambda: g.typing is not None) == 30      # +500 ms
    assert frames_until(w, lambda: len(texts(g)) == 3) == 120       # +2,000 ms
    assert g.labels == ("A",) and g.phase is Phase.ASK              # the same frame
    before = (list(g.items), g.labels, g.phase, g.view)
    for _ in range(600):                                            # updates only (F26-4)
        w.host.call(g.update, DT)
    w.frame()
    assert (list(g.items), g.labels, g.phase, g.view) == before     # an ask waits


# --- AC-F26-08 — Hurry --------------------------------------------------------------------------

def test_ac_f26_08_hurry(world):
    w = world
    flow = chats.args(chats.FLOW, time=None)
    # Enter, Space, south at 200 ms (gap): hi in that frame, no indicator, used once.
    for keys in (ENTER, SPACE, SOUTH):
        g = open_chat(w, flow)
        w.frame()
        w.frames(12)
        answers = record_events(g)
        seen = []
        w.frame(keys[0])
        seen.append(g.typing)
        w.frame(keys[1])
        assert texts(g) == ["hi"] and seen == [None] and answers[0] is True
        assert len(w.used()) == 1
    # A left click on the thread at 800 ms (typing): hi in that frame, the indicator removed.
    g = open_chat(w, flow)
    w.frame()
    w.frames(48)
    assert g.phase is Phase.TYPING
    w.frame(*click(thread_center(g)))
    assert texts(g) == ["hi"] and g.typing is None and g.view[-1].kind == "them"
    # Enter on 2 consecutive frames from 200 ms: hi, then On my way. with both dividers; the
    # 64-cp message's gap restarts from that frame.
    g = open_chat(w, flow)
    w.frame()
    w.frames(12)
    w.frame(*ENTER)
    w.frame(*ENTER)
    assert texts(g) == ["hi", "On my way."] and g.clock == "2 AM"
    assert g.phase is Phase.GAP and g.t == pytest.approx(DT)
    assert frames_until(w, lambda: g.typing is not None) == 29
    # Right click, middle click, a letterbox click: no hurry, not taken.
    g = open_chat(w, flow)
    w.frame()
    answers = record_events(g)
    for event in (*click(thread_center(g), 3), *click(thread_center(g), 2)):
        w.frame(event)
    w.frame(H.down((5, 5), in_canvas=False), H.up((5, 5), in_canvas=False))
    assert texts(g) == [] and answers == [False] * 4 and w.used() == []
    # Enter or a thread click while A shows: no hurry; Enter goes to the button.
    g = open_chat(w, flow)
    skip_waits(w, g)
    assert g.labels == ("A",)
    answers = record_events(g)
    shown = list(g.items)
    w.frame(*click(thread_center(g)))
    assert g.items == shown and answers[0] is False
    w.frames(15)
    w.frame(*ENTER)
    assert answers[-2] is False and g.picks == {"q": "a"}
    # After finish: handle_event False.
    w.frames(15)
    w.frame(*ENTER)
    assert g.done and g.finishes == [{"q": "a"}]
    assert g.handle_event(PluginEvent(ENTER[0], Nav.ACTIVATE)) is False


# --- AC-F26-09 — The 250 ms guard --------------------------------------------------------------

def test_ac_f26_09_the_guard(world):
    w = world

    def at_awake(by=InputKind.KEYS) -> PhoneChat:
        g = open_chat(w, by=by)
        skip_waits(w, g)
        assert g.ask.id == "awake"
        assert scope(w).focused is (g.replies if by is InputKind.KEYS else None)
        return g

    # Enter after 14 updates: ignored; after 15 (the float sum): picks yes.
    for n, picked in ((14, {}), (15, {"awake": "yes"})):
        g = at_awake()
        w.frames(n)
        w.frame(*ENTER)
        assert g.picks == picked, n
        assert (g.labels != ()) is (n == 14)
    # Odd frame times, then Enter: the inclusive boundary within GUARD_EPSILON.
    for last, picked in ((0.049998, {}), (0.0499995, {"awake": "yes"})):
        g = at_awake()
        for dt in (0.1, 0.1, last):
            w.host.call(g.update, dt)
        w.frame(*ENTER)
        assert g.picks == picked, last
    # Down after 2 updates moves focus at once; Enter after 15 picks sleep.
    g = at_awake()
    w.frames(2)
    w.frame(*DOWN)
    assert g.replies.focus_row == 1 and g.picks == {}
    w.frames(12)
    w.frame(*ENTER)
    assert g.picks == {"awake": "sleep"}
    # The ignore row after 14 / 15 updates.
    for n, done in ((14, False), (15, True)):
        g = at_awake()
        w.host.call(g.replies.on_nav, Nav.DOWN)
        w.host.call(g.replies.on_nav, Nav.DOWN)
        assert g.replies.focus_row == 2
        w.frames(n)
        w.frame(*ENTER)
        assert g.done is done and g.finishes == ([{"awake": "ignore", "walk": None}]
                                                 if done else []), n
    # The close button after 14 / 15 updates (C3).
    for n, done in ((14, False), (15, True)):
        g = open_chat(w, chats.args(chats.QUIET))
        skip_waits(w, g)
        assert g.phase is Phase.END and g.labels == ("Put the phone away",)
        w.frames(n)
        w.frame(*ENTER)
        assert g.done is done and g.finishes == ([{}] if done else []), n
    # Enter on every frame through the last message's typing: no finish until 250 ms after
    # close appeared.
    g = open_chat(w, chats.args(chats.QUIET))
    appeared = None
    for frame in range(200):
        w.frame(*ENTER)
        if appeared is None and g.labels:
            appeared = frame
        if g.done:
            break
    assert appeared is not None and g.done and g.finishes == [{}]
    assert frame - appeared == 15
    # Two clicks 3 frames apart on one reply, after 15 updates: one pick.
    g = at_awake(InputKind.MOUSE)
    w.frames(15)
    spot = pill_center(g, 0)
    w.frame(*click(spot))
    w.frames(2)
    w.frame(*click(spot))
    assert g.picks == {"awake": "yes"} and g.finishes == []


# --- AC-F26-10 — Picks, ignore, and the end -----------------------------------------------------

def test_ac_f26_10_picks_ignore_and_the_end(world, tmp_path):
    w = world
    # Pick yes: no groups, the me bubble in that frame; nothing really 500 + 750 ms later with
    # the 11:51 PM divider and clock in its frame.
    g = open_chat(w)
    skip_waits(w, g)
    w.frames(15)
    w.frame(*ENTER)
    assert scope(w).groups == [] and g.items[-1] == Message(None, "Yeah, what's up?")
    assert frames_until(w, lambda: g.typing is not None) + 1 == 30       # the pick frame's too
    assert frames_until(w, lambda: texts(g)[-1] == "nothing really") == 45
    assert g.items[-1] == TimeMark("11:51 PM") and g.clock == "11:51 PM"
    # A reply ["R", {"time": "3 AM"}, "f"]: R, the divider, and the clock in one frame; f
    # 1,100 ms later; then the next top-level step.
    g = open_chat(w, chats.args([{"ask": "q", "r": ["R", {"time": "3 AM"}, "f"]}, "next"]))
    skip_waits(w, g)
    w.frames(15)
    w.frame(*ENTER)
    assert g.items[-2:] == [Message(None, "R"), TimeMark("3 AM")] and g.clock == "3 AM"
    assert frames_until(w, lambda: texts(g)[-1] == "f") + 1 == 66
    assert g.items[-1] == Message("Sayori", "f")
    assert g.queue[0] == Message("Sayori", "next") and g.phase is Phase.GAP
    # Ignore at awake: no bubble; finish once, that frame.
    g = open_chat(w)
    skip_waits(w, g)
    shown = list(g.items)
    w.host.call(g.replies.focus_index, 2)
    w.frames(15)
    w.frame(*ENTER)
    assert g.items == shown and g.finishes == [{"awake": "ignore", "walk": None}]
    # Ignore rows: True / "Leave it" / False / absent.
    for ignore, last in ((True, "Don't reply"), ("Leave it", "Leave it"), (False, None),
                         (None, None)):
        ask = {"ask": "q", "a": "A"}
        if ignore is not None:
            ask["ignore"] = ignore
        g = open_chat(w, chats.args([ask]))
        skip_waits(w, g)
        assert g.labels == (("A", last) if last else ("A",)), ignore
        assert g.ignore_row == (1 if last else None)
    # After "yay!! see you then": the close button in the same frame; picking it finishes once.
    g = open_chat(w)
    for _ in range(2):
        skip_waits(w, g)
        w.frames(15)
        w.frame(*ENTER)
    w.frames(15)                     # the bubble for "Sure. …" ran; the last message waits
    frames_until(w, lambda: bool(g.labels))
    assert texts(g)[-1] == "yay!! see you then" and g.labels == ("Put the phone away",)
    w.frames(15)
    w.frame(*ENTER)
    assert g.finishes == [{"awake": "yes", "walk": "sure"}]
    # No asks: plays to close, finish {}.
    g = open_chat(w, chats.args(chats.QUIET))
    skip_waits(w, g)
    w.frames(15)
    w.frame(*ENTER)
    assert g.finishes == [{}]
    # three, ignore at the first ask.
    g = open_chat(w, chats.args(chats.THREE))
    skip_waits(w, g)
    w.host.call(g.replies.focus_index, 1)
    w.frames(15)
    w.frame(*ENTER)
    assert g.finishes == [{"a": "ignore", "b": None, "c": None}]
    # After finish: update and input change nothing; finish isn't called again.
    state = (list(g.items), g.phase, dict(g.picks), g.anim)
    g.update(1.0)
    g._pick(0)
    assert (list(g.items), g.phase, dict(g.picks), g.anim) == state and len(g.finishes) == 1
    # Dev Shift+F8 and Skip Game: the posted fixed outcome (A3).
    firsts = {"awake": "yes", "walk": "sure"}
    g = open_chat(w)
    w.frame()
    w.frame(*tap(pygame.K_F8, pygame.KMOD_SHIFT))
    w.frames(30)
    done = w.done()
    assert [(d.result, d.changes) for d in done] == [(firsts, ())]
    if not hasattr(w.host, "skip"):
        pytest.skip("F23 s5b: Skip Game")       # pragma: no cover
    g = open_chat(w, skippable=True)
    w.frame()
    w.host.skip(w.session)
    w.frames(30)
    assert [(d.result, d.changes) for d in w.done()] == [(firsts, ())]
    # Driver D accepts the posted dict: night at B equals it.
    from tests.minigames.bundled.test_phone_headless import LINE_P, _game
    from tests.runtime.minigame_story import at_a, finish, to_line
    program, sigs = _game(tmp_path / "d")
    interp = at_a(program, sigs=sigs)
    to_line(interp, LINE_P)
    finish(interp, done[0].result)
    assert interp.checkpoint().variables["night"] == firsts


# --- AC-F26-11 — First RUNNING frame and focus -------------------------------------------------

def test_ac_f26_11_first_running_frame_and_focus(world):
    w = world
    first = chats.args(chats.FIRST)
    # The opening picture: placeholder, the 11:42 PM divider, no rows.
    g = open_chat(w, first)
    s = w.session
    assert g.phase is Phase.BEGIN and g.labels == () and g.items == [TimeMark("11:42 PM")]
    assert s.thumb is not None and s.phase is HostPhase.RUNNING
    # t0: the three buttons in that frame over an empty thread; reached by Enter, row 0
    # focused and nothing used yet.
    w.frame()
    assert g.labels == ("X", "Y", "Don't reply") and texts(g) == []
    assert scope(w).focused is g.replies and g.replies.focus_row == 0 and w.used() == []
    # Enter at t0: ignored (guard).
    w.frame(*ENTER)
    assert g.picks == {} and g.labels
    # Reached by click: nothing focused; the first Down focuses row 0 and is used.
    g = open_chat(w, first, by=InputKind.MOUSE)
    w.frame()
    assert g.labels and scope(w).focused is None
    w.frame(*DOWN)
    assert scope(w).focused is g.replies and g.replies.focus_row == 0
    assert len(w.used()) == 1
    # late_chat: an Enter pick at awake → walk's rows with row 0 focused (Q-a).
    g = open_chat(w)
    skip_waits(w, g)
    w.frames(15)
    w.frame(*ENTER)
    assert scope(w).focused is None
    frames_until(w, lambda: g.ask is not None and g.ask.id == "walk")
    assert scope(w).focused is g.replies and g.replies.focus_row == 0
    # A click pick at awake → walk's rows with nothing focused.
    g = open_chat(w, by=InputKind.MOUSE)
    skip_waits(w, g)
    w.frames(15)
    w.frame(*click(pill_center(g, 0)))
    assert g.picks == {"awake": "yes"}
    frames_until(w, lambda: g.ask is not None and g.ask.id == "walk")
    assert scope(w).focused is None


# --- AC-F26-12 — A chat by each input device ---------------------------------------------------

def _play(w: HostU, g: PhoneChat, hurry, choices: dict[str, tuple]) -> list[int]:
    """Hurry each wait with ``hurry``; at each ask (or the end, key ``None``) wait 15 updates
    and send ``choices[id]``. Returns the thread length after every frame."""
    lengths = []
    w.frame()
    while not g.done:
        assert len(lengths) < 2000
        if g.phase in (Phase.GAP, Phase.TYPING):
            w.frame(*hurry(g))
        else:
            w.frames(15)
            key = g.ask.id if g.ask is not None else None
            for events in choices[key](g):
                w.frame(*events)
        lengths.append(len(g.items))
    return lengths


def test_ac_f26_12_a_chat_by_each_device(world):
    w = world
    rows = (
        ("keyboard", InputKind.KEYS, lambda g: ENTER,
         {"awake": lambda g: (DOWN, ENTER), "walk": lambda g: (ENTER,), None: lambda g: (ENTER,)},
         {"awake": "sleep", "walk": "sure"}, 3),
        ("mouse", InputKind.MOUSE, lambda g: click(thread_center(g)),
         {"awake": lambda g: (click(pill_center(g, 0)),),
          "walk": lambda g: (click(pill_center(g, 1)),),
          None: lambda g: (click(pill_center(g, 0)),)},
         {"awake": "yes", "walk": "busy"}, 3),
        ("gamepad", InputKind.KEYS, lambda g: SOUTH,
         {"awake": lambda g: (DPAD_DOWN, DPAD_DOWN, SOUTH)},
         {"awake": "ignore", "walk": None}, 1),
    )
    lengths = {}
    for name, by, hurry, choices, result, picks in rows:
        w.shell.sounds.clear()
        g = open_chat(w, by=by)
        lengths[name] = _play(w, g, hurry, choices)
        assert g.finishes == [result], name
        assert w.shell.sounds.count(ACTIVATE) == picks, name
    # Keyboard with reduced motion: as row 1, with the same thread items and timings.
    w.shell.reduce_motion = True
    keyboard = rows[0]
    g = open_chat(w)
    assert g.reduce is True
    assert _play(w, g, keyboard[2], keyboard[3]) == lengths["keyboard"]
    assert g.finishes == [keyboard[4]]


# --- AC-F26-13 — Back and used inputs (Q1) -----------------------------------------------------

def test_ac_f26_13_back_and_used_inputs(world):
    w = world

    def back_rows(g: PhoneChat, used: int) -> None:
        """The wheel, Page Up, and LB in turn: each unused (the screen returns False, so F14
        gets it); MinigameUsed exactly ``used`` times."""
        screen = w.session.screen
        for event in (H.wheel(thread_center(g), 1), PAGE_UP[0], LB[0]):
            assert screen.handle_event(event) is False, event
        assert len(w.used()) == used

    # Nothing yet; mouse motion only; a click in the letterbox.
    g = open_chat(w)
    w.frame()
    back_rows(g, 0)
    w.frame(H.motion(thread_center(g)))
    w.frame(H.down((5, 5), in_canvas=False), H.up((5, 5), in_canvas=False))
    back_rows(g, 0)
    # A left click on the thread during ask awake: ends no wait, not used.
    skip_waits(w, g)
    w.frame(*click(thread_center(g)))
    back_rows(g, 0)
    # A hurry (Enter in the first gap): used.
    g = open_chat(w)
    w.frame()
    w.frame(*ENTER)
    back_rows(g, 1)
    # Down during ask awake; a pick: used.
    g = open_chat(w)
    skip_waits(w, g)
    w.frame(*DOWN)
    back_rows(g, 1)
    g = open_chat(w)
    skip_waits(w, g)
    w.frames(15)
    w.frame(*ENTER)
    assert g.picks == {"awake": "yes"}
    back_rows(g, 1)


# --- AC-F26-14 — Scrolling the thread ------------------------------------------------------------

def test_ac_f26_14_scrolling_the_thread(world):
    w = world
    g = open_chat(w, chats.args(chats.LONG))
    w.frame()
    for _ in range(30):
        w.host.call(g._hurry)
    w.frame()
    assert len(texts(g)) == 30 and g.labels == () and g.phase is Phase.GAP
    answers = record_events(g)
    # One wheel notch up over the thread: 126 (3 × (34 + 8)); used.
    w.frame(H.wheel(thread_center(g), 1))
    assert g.scroll_back == 126 and answers == [True] and len(w.used()) == 1
    # Page Up, LB: 405 each (439 − 34), clamped to the top.
    w.frame(*PAGE_UP)
    w.frame(*LB)
    assert g.scroll_back == 126 + 2 * 405
    most = g.content_h - g.layout_now.thread[3]
    while g.scroll_back < most:
        w.frame(*PAGE_UP)
    assert g.scroll_back == most
    # The wheel up at the top; Page Down at the bottom: not taken (F23's fallback acts).
    screen = w.session.screen
    assert screen.handle_event(H.wheel(thread_center(g), 1)) is False
    g.scroll_back = 0.0
    assert screen.handle_event(PAGE_DOWN[0]) is False
    # A new bubble while scrolled up: back to the bottom.
    w.frame(H.wheel(thread_center(g), 2))
    assert g.scroll_back > 0
    w.frame(*ENTER)
    assert len(texts(g)) == 31 and g.scroll_back == 0
    # The wheel over the reply list (AC-F26-18's 150% case): the list scrolls, not the thread.
    w.shell.painter.set_text_scale(lambda: 1.5)
    g = open_chat(w, chats.args(chats.overflow(4, 3, True)))
    w.frame()
    w.frame()
    assert g.replies.max_scroll() == 28 and g.scroll_back == 0
    w.frame(H.wheel(pill_center(g, 2), -1))
    assert g.replies.scroll == 28 and g.scroll_back == 0


# --- AC-F26-15 — Same chat on replay ------------------------------------------------------------

def test_ac_f26_15_same_chat_on_replay(world, tmp_path, monkeypatch):
    w = world
    from engine.minigames.context import DiceHandle
    calls = []
    for method in ("roll", "pick", "decimal", "shuffle"):
        monkeypatch.setattr(DiceHandle, method, lambda self, *a, _m=method, **k: calls.append(_m))
    # A full late_chat session makes no ctx.random call.
    g = open_chat(w)
    _play(w, g, lambda g: ENTER, {"awake": lambda g: (ENTER,), "walk": lambda g: (ENTER,),
                                  None: lambda g: (ENTER,)})
    assert g.done and calls == []

    # Two sessions with the same dt list and inputs (seeds 1 and 2): equal thread, picks,
    # results, and frames.
    def replay(seed: int):
        g = open_chat(w, seed=seed)
        pictures = []
        w.frame()
        for n in range(900):
            events = ()
            if g.phase in (Phase.GAP, Phase.TYPING) and n % 4 == 2:
                events = ENTER                                      # a hurry (F26-4: fewer frames)
            elif g.phase is Phase.ASK and g.since_buttons > 0.3:
                events = (*DOWN, *ENTER) if g.ask.id == "awake" else ENTER   # sleep, sure
            elif g.phase is Phase.END and g.since_buttons > 0.3:
                events = ENTER                                      # close
            w.frame(*events)
            if n % 5 == 0:
                pictures.append(pygame.image.tobytes(w.ui.framebuffer, "RGB"))
            if g.done:
                break
        return list(g.items), dict(g.picks), g.finishes, pictures

    one, two = replay(1), replay(2)
    assert one == two and one[2] == [{"awake": "sleep", "walk": "sure"}]
    # From AC-F26-03's restored StartMinigame, and from a Driver D landing on P: the opening
    # picture's state, AC-F26-07's timings from t0, and a pick of sleep.
    from engine.runtime.commands import StepBack
    from engine.runtime.state import GameState
    from tests.minigames.bundled.test_phone_headless import LINE_P, _game
    from tests.runtime.minigame_story import ALL, at_a, finish, start_of, to_line
    program, sigs = _game(tmp_path / "c")
    live = at_a(program, sigs=sigs)
    to_line(live, LINE_P)
    saved = live.checkpoint().to_json()
    fresh = at_a(program, sigs=sigs)
    assert fresh.restore(GameState.from_json(saved)).result.value == "ok"
    restored = start_of(fresh.take_commands(ALL))
    later = at_a(program, sigs=sigs)
    to_line(later, LINE_P)
    finish(later, {"awake": "yes", "walk": "sure"})
    later.post(StepBack(1))
    landed = start_of(later.take_commands(ALL))
    for cmd in (restored, landed):
        assert cmd.restored
        g = open_chat(w, cmd=cmd)
        assert (g.clock, g.items, g.picks, g.labels) == ("11:42 PM", [TimeMark("11:42 PM")],
                                                         {}, ())
        w.frame()
        assert frames_until(w, lambda: g.typing is not None) == 30
        assert frames_until(w, lambda: texts(g) == ["you awake?"]) == 39    # typing_s 0.65
        skip_waits(w, g)
        w.host.call(g.replies.focus_index, 1)
        w.frames(15)
        w.frame(*ENTER)
        assert g.picks == {"awake": "sleep"}


# --- AC-F26-16 — Settings changed mid-chat -----------------------------------------------------

def test_ac_f26_16_settings_changed_mid_chat(world):
    w = world
    g = open_chat(w)
    skip_waits(w, g)
    w.frames(15)
    w.frame(*ENTER)
    skip_waits(w, g)
    assert g.ask.id == "walk"
    w.frame(*DOWN)
    w.frames(20)                                  # the press look and any ease are over
    before = pygame.image.tobytes(w.ui.framebuffer, "RGB")
    replies, state = g.replies, (dict(g.picks), g.phase, g.t, list(g.items))
    since = g.since_buttons
    # 150%: re-placed at s 36, at the bottom, the same list and focus; nothing else changes.
    w.shell.painter.set_text_scale(lambda: 1.5)
    g.scroll_back = 10.0
    w.frame()
    assert g._sizes[0] == 36 and g.scroll_back == 0
    assert all(i.h == len(i.lines) * 50 + 16 for i in g.view if i.kind in ("them", "me"))
    assert g.view == phone_rules.thread_layout(
        g.items, g.layout_now.thread[2], s=36, small=36, group=False, measure=g._mmeasure)
    assert g.replies is replies and g.replies.focus_row == 1 and scope(w).focused is replies
    assert (dict(g.picks), g.phase, g.t, list(g.items)) == state
    assert g.since_buttons == pytest.approx(since + DT)
    # Back to 100%: pixel-equal to the frame before.
    w.shell.painter.set_text_scale(lambda: 1.0)
    w.frame()
    assert pygame.image.tobytes(w.ui.framebuffer, "RGB") == before
    # layout(area) alone: recomputed once, at the next draw.
    count = g.relayouts
    g.layout(w.session.area)
    assert g.relayouts == count
    w.frames(2)
    assert g.relayouts == count + 1
    # Reduced motion on during typing: the dots rest from the next frame; the next scroll cuts.
    g = open_chat(w)
    w.frame()
    frames_until(w, lambda: g.typing is not None)
    w.frames(20)
    assert any(g.dot_lift(k) > 0 for k in range(3))
    w.shell.reduce_motion = True
    w.frame()
    assert g.reduce and [g.dot_lift(k) for k in range(3)] == [0, 0, 0]
    frames_until(w, lambda: g.typing is None)
    assert g.ease_offset == 0
    w.shell.reduce_motion = False
    w.frame()
    assert g.reduce is False
    w.shell.reduce_motion = True
    assert open_chat(w).reduce is True                       # read from ctx.settings at start
    w.shell.reduce_motion = False
    # No update for 600 frames during typing (paused): the bubble comes the same remaining
    # time later (± 1 frame).
    g = open_chat(w)
    w.frame()
    frames_until(w, lambda: g.typing is not None)
    w.frames(10)
    w.focused = False
    w.frames(600)
    assert g.typing is not None and texts(g) == []
    w.focused = True
    left = round(phone_rules.typing_s("you awake?") * 60) - 10
    assert frames_until(w, lambda: texts(g) == ["you awake?"]) in (left - 1, left, left + 1)


# --- AC-F26-18 — Fit from 100% to 150%, and overflow -------------------------------------------

def test_ac_f26_18_fit_and_overflow(world):
    w = world
    for scale in (1.0, 1.25, 1.5):
        w.shell.painter.set_text_scale(lambda scale=scale: scale)
        for n in range(1, 5):
            for ignore in (True, False):
                for cp in (3, 80):
                    g = open_chat(w, chats.args(chats.overflow(n, cp, ignore)))
                    w.host.call(g.update, 0.0)
                    assert g._ensure()
                    case = (scale, n, ignore, cp)
                    r = g.replies
                    reply = g.layout_now.reply
                    bs = g._sizes[3]
                    content = sum(g._heights)
                    assert reply[3] == min(g.layout_now.reply_cap, content), case
                    assert g.layout_now.thread[3] >= pitch_of_size(g._sizes[0]) + 16, case
                    bottoms = []
                    for i, label in enumerate(g.labels):
                        r.focus_index(i)
                        row = r.row_box(i)
                        assert r.box.y - 1e-6 <= row.y and row.bottom <= r.box.bottom + 1e-6
                        pill = r.pill(i)
                        assert reply[0] <= pill.x and pill.right <= reply[0] + reply[2], case
                        lines = g._wraps[i]
                        assert pill.h == max(56, len(lines) * pitch_of_size(bs) + 16), case
                        assert " ".join(lines) == label and "…" not in label, case
                        bottoms.append((pill.y + r.scroll, pill.bottom + r.scroll))
                    assert all(a[1] <= b[0] for a, b in zip(bottoms, bottoms[1:])), case
    # The designer's 150% rows (G1).
    g = open_chat(w, chats.args(chats.overflow(4, 3, True)))
    w.host.call(g.update, 0.0)
    g._ensure()
    assert [g.replies.pill(i).h for i in range(5)] == [75] * 5
    assert sum(g._heights) == 415 and g.replies.max_scroll() == 28
    g = open_chat(w, chats.args(chats.overflow(4, 80, True)))
    w.host.call(g.update, 0.0)
    g._ensure()
    assert g.layout_now.reply[3] == 387 and g.layout_now.thread[3] == 72
    for _ in range(4):
        g.replies.on_nav(Nav.DOWN)
    last = g.replies.row_box(4)
    assert g.replies.focus_row == 4 and g.labels[4] == "Don't reply"
    assert g.replies.box.y <= last.y and last.bottom <= g.replies.box.bottom + 1e-6
    # Content rows at 150%: wrapped within 321 with every code point kept; the contact cut.
    breaks = "\n".join(["x" * 58] * 4 + ["y" * 64])                # 300 cp, 4 breaks
    messages = (*chats.UNICODE_MESSAGES, breaks)
    g = open_chat(w, chats.args(list(messages), contact="S" * 40))
    while g.phase is not Phase.END:
        w.host.call(g.update if g.phase is Phase.BEGIN else g._hurry, *(
            (0.0,) if g.phase is Phase.BEGIN else ()))
    g._ensure()
    bubbles = [i for i in g.view if i.kind == "them"]
    assert len(bubbles) == len(messages)
    for item, text in zip(bubbles, messages):
        assert all(g._mmeasure(line, 36) <= 321 for line in item.lines)
        assert "".join(item.lines).replace(" ", "") == text.replace(" ", "").replace("\n", "")
    header = g._base.header
    assert g._header_text.endswith("…") and len(g._header_text) < 40
    assert g._measure(g.header_font)(g._header_text, g._sizes[2]) <= header[2] - 32


# --- AC-F26-19 — The phone on screen -----------------------------------------------------------

def _hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(rgb)


def _near(got, want: str, tol: int = 8) -> bool:
    want_rgb = tuple(int(want[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= tol for a, b in zip(got, want_rgb))


def test_ac_f26_19_the_phone_on_screen(world, monkeypatch):
    w = world
    g = open_chat(w)
    shell = w.shell
    texts_drawn, shapes, ellipses, frames = [], [], [], []
    real_text = w.ui.canvas.draw_text

    def draw_text(text, font, color, pos, **kw):
        texts_drawn.append((text, font, tuple(color), pos, kw.get("anchor")))
        return real_text(text, font, color, pos, **kw)

    monkeypatch.setattr(w.ui.canvas, "draw_text", draw_text, raising=False)
    painter = shell.painter
    real_shape, real_ellipse, real_frame = painter.shape, painter.ellipse, painter.widget_frame
    monkeypatch.setattr(painter, "shape", lambda box, spec, **kw: (
        shapes.append((box, spec)), real_shape(box, spec, **kw))[1], raising=False)
    monkeypatch.setattr(painter, "ellipse", lambda box, color, **kw: (
        ellipses.append((box, tuple(color))), real_ellipse(box, color, **kw))[1], raising=False)
    monkeypatch.setattr(painter, "widget_frame", lambda box, area, look, **kw: (
        frames.append((box, area, look)), real_frame(box, area, look, **kw))[1], raising=False)
    s = w.session
    # The opening picture: phone, the 11:42 PM clock and divider, an empty thread, the
    # placeholder; no indicator; no heading or hint bar.
    assert g.clock == "11:42 PM" and texts(g) == [] and g.typing is None and s.thumb is not None
    assert s.frame.heading is None and s.frame.hint is None and not s.heading_on
    # The placeholder with no rows; the scope has no groups.
    w.frame()
    texts_drawn.clear()
    w.frame()
    reply = g.layout_now.reply
    assert scope(w).groups == [] and g.labels == ()
    assert _near(w.ui.px(reply[0] + 1, reply[1] + reply[3] / 2), "#6E5E68", 24)
    placeholder = [t for t in texts_drawn if t[0] == "Message"]
    assert placeholder and placeholder[0][2] == (0x6E, 0x5E, 0x68)
    # After a pick of yes and "nothing really".
    skip_waits(w, g)
    w.frames(15)
    w.frame(*ENTER)
    skip_waits(w, g)
    w.frames(20)
    texts_drawn.clear()
    shapes.clear()
    frames.clear()
    w.frame()
    px = w.ui.px
    assert _near(px(436, 360), "#1E1E24") and _near(px(450, 360), "#F7F4F6")
    assert _near(px(520, 40), "#FFFFFF")
    clock = [t for t in texts_drawn if t[0] == "11:51 PM" and t[4] == "center"]
    bar = g.layout_now.bar
    assert clock[0][1].size == 24 and clock[0][2] == (0x3A, 0x2E, 0x39)
    assert clock[0][3] == (bar[0] + bar[2] / 2, bar[1] + bar[3] / 2)
    header = [t for t in texts_drawn if t[0] == "Sayori"]
    assert header[0][1].size == 28 and header[0][3][0] == 640
    assert _near(px(600, 141), "#E3D9DF")
    top = g.thread_top()
    thread = Box(*g.layout_now.thread)
    shown = [i for i in g.view if i.kind in ("them", "me") and top + i.y >= thread.y
             and top + i.y + i.h <= thread.bottom]
    assert {i.kind for i in shown} == {"them", "me"}
    for item in shown:
        y = top + item.y
        line = [t for t in texts_drawn if t[0] == item.lines[0]][0]
        if item.kind == "them":
            assert 458 + item.x == 458 and _near(px(459, y + item.h / 2), "#ECE6EA")
            assert line[2] == (0x2A, 0x21, 0x28) and line[3][0] == 458 + 12
        else:
            assert 458 + item.x + item.w == pytest.approx(822)
            assert _near(px(820, y + item.h / 2), "#A02860") and line[2] == (255, 255, 255)
        assert any(spec.corner_radius == 18 and box.y == y for box, spec in shapes)
    # The reply rows: F10's button frames; labels at 32; the ignore row is italic.
    buttons = [f for f in frames if f[1] == "button"]
    assert len(buttons) == 2 and buttons[0][2].state == "focused"
    for f in buttons:
        label = [t for t in texts_drawn if t[3][0] == f[0].x + 32]
        assert label, f
    g = open_chat(w)
    skip_waits(w, g)
    texts_drawn.clear()
    frames.clear()
    w.frame()
    pills = [g.replies.pill(i) for i in range(3)]
    assert pills[2].y - pills[1].bottom == 16 and pills[1].y - pills[0].bottom == 8
    italic = [t for t in texts_drawn if t[0] == "Don't reply"][0][1]
    from engine.render.text import Face, Synth
    assert (italic.bundled, italic.synth) == (Face.ITALIC, Synth.ITALIC)
    # The focused row: F10's look (fill, border, marker) differs from a normal row's.
    focused, normal = pills[0], pills[1]
    assert px(focused.x + 1, focused.y + focused.h / 2) != px(normal.x + 1,
                                                               normal.y + normal.h / 2)
    assert px(focused.x + 16, focused.y + focused.h / 2) != px(normal.x + 16,
                                                               normal.y + normal.h / 2)
    # The typing indicator 600 ms after "nothing really"'s turn: 72 × 50, three 10-unit dots
    # 8 apart in the dot color.
    g = open_chat(w)
    w.frame()
    frames_until(w, lambda: g.typing is not None)
    ellipses.clear()
    w.frame()
    item = g.view[-1]
    assert (item.kind, item.w, item.h) == ("typing", 72, 50)
    assert [round(b.w) for b, _ in ellipses] == [10, 10, 10]
    assert [round(b.x - ellipses[0][0].x) for b, _ in ellipses] == [0, 18, 36]
    assert {c for _, c in ellipses} == {(0x6E, 0x5E, 0x68)}
    # Dot k's lift (motion on): 2 at anim − 0.15k = 0.3, 4 at 0.6; reduced motion: 0.
    for k in range(3):
        g.anim = 0.3 + 0.15 * k
        assert g.dot_lift(k) == pytest.approx(2, abs=0.5)
        g.anim = 0.6 + 0.15 * k
        assert g.dot_lift(k) == pytest.approx(4, abs=0.5)
    g.reduce = True
    assert [g.dot_lift(k) for k in range(3)] == [0, 0, 0]
    # A new bubble: the offset is the added height at once, half at 75 ms, 0 at 150 ms;
    # reduced motion: 0 at once.
    for reduce in (False, True):
        w.shell.reduce_motion = reduce
        g = open_chat(w)
        w.frame()
        before = g.content_h
        w.host.call(g._hurry)
        w.host.call(g._hurry)
        g._ensure()
        added = g.content_h - before
        assert added > 0
        if reduce:
            assert g.ease_offset == 0
            continue
        assert g.ease_offset == added
        g.update(0.075)
        assert g.ease_offset == pytest.approx(added / 2)
        g.update(0.075)
        assert g.ease_offset == 0
    w.shell.reduce_motion = False


# --- AC-F26-20 — Tokens and words --------------------------------------------------------------

def _configured(game, tmp_path, text: str) -> HostU:
    """Host C over a ``config.toml`` holding ``text`` ([theme.plugin] / [words.plugin],
    checked at install by s5b's ``PluginTables``)."""
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.minigames.tables import PluginTables
    from tests.minigames.host_u import load_plugins
    root = tmp_path / f"cfg{len(list(tmp_path.iterdir()))}"
    root.mkdir()
    (root / "config.toml").write_text(text, encoding="utf-8")
    result = load_config(GamePaths.for_game(root))
    assert result.errors == [] and result.warnings == [], text
    registry = load_plugins(game)
    tables = PluginTables(result.config.theme.plugin, result.config.words.plugin,
                          result.config.theme, dev=True)
    tables.check(registry.entries())
    return HostU(game, registry=registry, config=result.config, tables=tables, cfg=SOUNDS)


def test_ac_f26_20_tokens_and_words(game, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    # Words: the save description (the session's title) and the labels; a chat's own ignore
    # label still wins.
    w = _configured(game, tmp_path, '[words.plugin.phone_chat]\ntitle = "Téléphone"\n'
                                    'ignore = "Laisser"\nclose = "Ranger"\n'
                                    'placeholder = "Texto"\n')
    g = open_chat(w)
    assert w.session.title == "Téléphone" and g.word["placeholder"] == "Texto"
    skip_waits(w, g)
    assert g.labels[-1] == "Laisser"
    g = open_chat(w, chats.args(chats.QUIET))
    skip_waits(w, g)
    assert g.labels == ("Ranger",)
    g = open_chat(w, chats.args([{"ask": "q", "a": "A", "ignore": "Leave it"}]))
    skip_waits(w, g)
    assert g.labels == ("A", "Leave it")
    # body_width 1000 / 100: 600 / 360 wide at 100%, no config warning.
    for width, body in ((1000, 600), (100, 360)):
        caplog.clear()
        w = _configured(game, tmp_path,
                        f"[theme.plugin.phone_chat.phone]\nbody_width = {width}\n")
        g = open_chat(w)
        assert g.layout_now.body[2] == body
        assert [r for r in caplog.records if r.name == "vn.config"
                and r.levelno >= logging.WARNING] == []
    # message.text_size 60 → s 36; header.text_size 10 → 24.
    w = _configured(game, tmp_path, "[theme.plugin.phone_chat.message]\ntext_size = 60\n"
                                    "[theme.plugin.phone_chat.header]\ntext_size = 10\n")
    g = open_chat(w)
    assert g._sizes[0] == 36 and g._sizes[2] == 24 and g.header_font.size == 24
    # me.fill_color: the me bubble probe reads #102030.
    w = _configured(game, tmp_path, '[theme.plugin.phone_chat.me]\nfill_color = "#102030"\n')
    g = open_chat(w, chats.args([{"me": "hello there"}]))
    w.frame()
    w.host.call(g._hurry)
    w.frames(12)
    me = g.view[-1]
    top = g.thread_top()
    assert me.kind == "me"
    assert _near(w.ui.px(458 + me.x + me.w - 4, top + me.y + me.h / 2), "#102030")
    # A missing message font: F23's font fallback (the theme's), its one log line in dev.
    caplog.clear()
    w = _configured(game, tmp_path,
                    '[theme.plugin.phone_chat.message]\ntext_font = "fonts/nope.ttf"\n')
    g = open_chat(w)
    w.frames(3)
    assert g.message_ref == "fonts/nope.ttf" and g.message_font.ref is None
    named = [r for r in caplog.records if "nope.ttf" in r.getMessage()
             and r.levelno >= logging.WARNING]
    assert len(named) <= 1


# --- AC-F26-21 — Missing glyphs (W176) ---------------------------------------------------------

def test_ac_f26_21_missing_glyphs(world, game, caplog, monkeypatch, warned):
    w = world
    caplog.set_level(logging.DEBUG, logger="vn.plugin")

    def records() -> list[logging.LogRecord]:
        found = [r for r in caplog.records if getattr(r, "code", None) == "W176"]
        caplog.clear()
        return found

    # Unit (TR-F26-03): the bundled default font at 24.
    font = w.shell.assets.font(None, 24).font
    found = phone_rules.glyph_missing(font, "aé\"\U0001F60A中")
    assert found == ["\U0001F60A", "中"]
    # Step 4 "hi 😊": one record at the opening picture.
    caplog.clear()
    open_chat(w, chats.args(chats.w176_chat(4, "hi \U0001F60A")))
    got = records()
    assert [r.getMessage() for r in got] == [phone_rules.w176_text("\U0001F60A", "step 4")]
    assert got[0].name == "vn.plugin" and got[0].levelno == logging.WARNING
    # A second session of that chat: none.
    open_chat(w, chats.args(chats.w176_chat(4, "hi \U0001F60A")))
    assert records() == []
    # The same character at step 6 of another chat: one more (another text).
    open_chat(w, chats.args(chats.w176_chat(6, "\U0001F60A")))
    assert [r.getMessage() for r in records()] == [
        phone_rules.w176_text("\U0001F60A", "step 6")]
    # 中 in a follow-up of reply yes: that follow-up's locator.
    open_chat(w, chats.args(chats.w176_follow_up()))
    assert [r.getMessage() for r in records()] == [
        phone_rules.w176_text("中", 'step 2 after reply "yes" of ask "awake"')]
    # White space, \n, ZWJ, U+0301 are never passed to glyph_missing.
    seen: list[str] = []
    real = phone_rules.glyph_missing
    monkeypatch.setattr(phone_rules, "glyph_missing",
                        lambda f, chars: (seen.append(chars), real(f, chars))[1])
    open_chat(w, chats.args(["a b\nc", "d‍e", "é"]))
    assert seen == ["abcde"]
    # 101 distinct missing texts across sessions: exactly 100.
    warned.clear()
    caplog.clear()
    for chat in chats.many_missing(101):
        open_chat(w, chats.args(chat))
    assert len(records()) == 100 and len(warned) == 100
    # 2,001 distinct characters: glyph_missing gets the first 2,000.
    pairs = phone_rules.glyph_chars(phone_rules.parse(chats.args(chats.distinct_chars(2001))))
    assert len(pairs) == 2000 and pairs[-1][0] == chr(0x4E00 + 1999)
    # Release (ctx.dev False): none, and glyph_missing is never called.
    seen.clear()
    warned.clear()
    release = HostU(game, dev=False, cfg=SOUNDS)
    open_chat(release, chats.args(chats.w176_chat(4, "hi \U0001F60A")))
    assert records() == [] and seen == []


# --- AC-F26-24 — CI guard: costs ----------------------------------------------------------------

def test_ac_f26_24_costs(world, monkeypatch):
    w = world
    wraps: list[str] = []
    real_wrap = phone_rules.wrap_text
    monkeypatch.setattr(phone_rules, "wrap_text",
                        lambda text, *a, **k: (wraps.append(text), real_wrap(text, *a, **k))[1])
    # Each new bubble: one wrap; each ask: one per row.
    g = open_chat(w)
    w.frame()
    wraps.clear()
    w.host.call(g._hurry)
    g._ensure()
    assert wraps == ["you awake?"]
    wraps.clear()
    w.host.call(g._hurry)
    g._ensure()
    assert sorted(wraps) == sorted(["i can't sleep...", "Yeah, what's up?",
                                    "Go to sleep, Sayori.", "Don't reply"])
    # 600 frames during an ask: no wrap, no new text render, no shape built once the new
    # bubble's 150 ms ease (which brings it into view) is over.
    w.frames(10)
    assets = w.shell.assets
    lines = {k for k in assets.cache.keys() if k[0] == "text"}
    builds = w.shell.painter.builds
    wraps.clear()
    w.frames(600)
    assert wraps == [] and {k for k in assets.cache.keys() if k[0] == "text"} == lines
    assert w.shell.painter.builds == builds
    # 200 bubbles: shapes only for items intersecting the thread.
    g = open_chat(w, chats.args([f"m{n}" for n in range(200)]))
    w.frame()
    for _ in range(199):
        w.host.call(g._hurry)
    w.frame()
    shapes = []
    real_shape = w.shell.painter.shape
    monkeypatch.setattr(w.shell.painter, "shape", lambda box, spec, **kw: (
        shapes.append(box), real_shape(box, spec, **kw))[1], raising=False)
    w.frame()
    thread = Box(*g.layout_now.thread)
    bubbles = [b for b in shapes if b.w < thread.w and b.x >= thread.x]
    visible = [i for i in g.view if g.thread_top() + i.y < thread.bottom
               and g.thread_top() + i.y + i.h > thread.y]
    assert 0 < len(bubbles) <= len(visible) + 1 < 20
    # problem() on a printable chat never calls rule_text.hidden (the fast path).
    hidden = []
    monkeypatch.setattr(rule_text, "hidden", lambda ch: hidden.append(ch) or False)
    assert phone_rules.problem(chats.LATE) is None and hidden == []

