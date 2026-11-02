"""F23 s4 — the host and screen in Host U (``06`` §0.3): AC-F23-18, 23, 24, 26, 27, 29, 31
(Host U rows), 32 (on the unit canvas), 33, 34, 35, 36 (Host U rows), 37 (anchor rows), 38,
44, 45, 51, 52, 55, 63 (host rows). One test per AC, its rows inside. App rows are in
``tests/app/test_minigame_app.py``."""

import dataclasses
import gc
import logging
import threading

import pygame
import pytest

from engine.app.story import Watchdog
from engine.core.config_schema import ThemeConfig
from engine.core.logsetup import RedactingFormatter
from engine.core.minigame_types import CodexChange, MeterChange
from engine.core.redact import Redactor, RedactRoot, install
from engine.minigames.api import CodexFilter, MinigameThreadError, PickAction
from engine.minigames.host import SNAPSHOT_KEY, Phase
from engine.minigames.screen import MinigameScreen
from engine.render.thumbnail import make_thumbnail
from engine.runtime import limits
from engine.runtime.commands import MinigameUsed
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.nav import InputKind, Nav
from tests.fakes.ui_shell import ColumnMenu, UiHarness
from tests.minigames.conftest import write
from tests.minigames.host_u import WHERE, HostU, load_plugins

H = UiHarness
E275_88 = ("minigame probe stopped with an error in minigames/probe.py, line 88: division by "
           "zero. Fix the plugin; the log has the details.")


def _sounds() -> ThemeConfig:
    cfg = ThemeConfig()
    return dataclasses.replace(cfg, button=dataclasses.replace(
        cfg.button, focus_sound="sfx/focus.ogg", activate_sound="sfx/activate.ogg"))


SOUNDS = _sounds()


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture
def world(game):
    return HostU(game)


def running(w: HostU, **kwargs) -> HostU:
    """A Probe session, started as a cut (restored) and settled for one frame."""
    w.start(**kwargs)
    w.frame()
    assert w.session is not None and w.session.phase is Phase.RUNNING, w.fatal
    return w


def fatal_text(w: HostU) -> str:
    assert len(w.fatal) == 1, w.fatal
    return w.fatal[0].format()


def handle_events(w: HostU) -> list:
    return [arg for name, arg in w.behavior.calls if name == "handle_event"]


# --- AC-F23-18 — abandoning applies nothing ----------------------------------------------------

@pytest.mark.parametrize("action", ["back_step", "new_start", "say", "error_screen", "reset",
                                    "screen_removed"])
def test_ac18_abandoning_applies_nothing(world, action):
    w = world
    w.behavior.requests = [("points", "add", ("hana", 3)), ("codex", "give", ("paper_lantern",))]
    w.start(restored=False)
    w.frames(20)
    w.session.music = w.audio.take_music("minigame")
    old = w.session
    assert old.ledger.changes == (MeterChange("hana", "+=", 3),
                                  CodexChange("give", "paper_lantern"))
    if action == "back_step":
        w.host.on_landing()
    elif action == "new_start":
        w.start(run=2)
    elif action == "say":
        w.host.on_say(object())
    elif action in ("error_screen", "reset"):
        w.host.abandon()                  # App.add_fatal_hook's / the shell's in-game reset
    else:
        w.shell.stack.remove(old.screen)  # a load's replace_all: on_exit
    w.frames(20)
    assert w.done() == []
    assert old.phase is Phase.CLOSED and old.screen not in list(w.shell.stack)
    assert ("release",) in w.audio.calls
    assert ("stop_ui", 0.1, "minigame") in w.audio.calls
    if action == "new_start":
        assert w.session is not old and w.session.cmd.run == 2
    else:
        assert w.session is None and w.shell.source is None and w.cue.fn is None


# --- AC-F23-23 — reads and the plugin's only handle -------------------------------------------

def test_ac23_reads_and_the_only_handle(world):
    w = world
    seen = {}

    def on_start(ctx):
        seen["get"] = ctx.points.get("hana")
        seen["names"] = ctx.points.names()
        seen["items"] = ctx.codex.items()
        seen["moon"] = ctx.codex.has("moon")
        ctx.args["words"].append("x")
        seen["ctx"] = ctx

    w.behavior.on_start = on_start
    cmd = w.start(args={"pairs": 6, "hints": False, "label": "", "words": ["a"]},
                  meters=(("hana", 3, 0, 10),), items=("coin",), tips=("moon",))
    assert seen["get"] == 3 and seen["names"] == ("hana",)
    assert seen["items"] == ("coin",) and seen["moon"] is True
    assert list(cmd.args["words"]) == ["a"]                       # a deep copy
    ctx = seen["ctx"]
    public = {n for n in dir(type(ctx)) if not n.startswith("_")}
    assert public == {"args", "random", "points", "codex", "settings", "area", "scope",
                      "painter", "theme", "words", "dev", "log", "image", "gui_image", "font",
                      "play_sound", "music", "play_ui", "heading", "hint", "cue_point",
                      "confirm", "codex_view", "finish", "story"}
    from engine.app.app import App
    from engine.runtime.interpreter import Interpreter
    from engine.runtime.state import GameState
    banned = (Interpreter, GameState, App)
    frontier, seen_ids = [ctx], {id(ctx)}
    for _ in range(8):
        nxt = []
        for obj in frontier:
            assert not isinstance(obj, banned), type(obj)
            for ref in gc.get_referents(obj):
                if id(ref) not in seen_ids and not isinstance(ref, (type, type(gc))):
                    seen_ids.add(id(ref))
                    nxt.append(ref)
        frontier = nxt


# --- AC-F23-24 — requested changes -------------------------------------------------------------

@pytest.mark.parametrize("requests, expected", [
    ([("points", "add", ("hana", 2)), ("codex", "give", ("paper_lantern",)),
      ("codex", "unlock_tip", ("lanterns",))], None),
    ([("points", "add", ("hanna", 1))], 'there is no meter named "hanna". Did you mean "hana"?'),
    ([("codex", "give", ("lantren",))], 'there is no item "lantren"'),
    ([("codex", "give", ("lanterns",))], "lanterns is a tip, not an item"),
    ([("points", "add", ("hana", 1.5))], "must be a whole number"),
    ([("points", "add", ("hana", True))], "must be a whole number"),
    ([("points", "add", ("hana", 1))] * 1001, "more than 1,000 changes"),
], ids=["three", "meter", "item", "kind", "float", "bool", "many"])
def test_ac24_requested_changes(world, requests, expected):
    w = world
    w.behavior.requests = requests
    w.behavior.on_event = lambda ctx, ev: ctx.finish(9) or True
    w.start()
    if expected is not None:
        text = fatal_text(w)
        assert expected in text
        assert text.startswith("minigames/probe.py, line ")       # the P prefix
        assert w.session is None and w.done() == []
        return
    w.frame(H.key(pygame.K_SPACE))
    w.frames(25)
    done = w.done()
    assert len(done) == 1 and done[0].result == 9
    assert done[0].changes == (MeterChange("hana", "+=", 2),
                               CodexChange("give", "paper_lantern"),
                               CodexChange("unlock_tip", "lanterns"))


# --- AC-F23-26 — assets ------------------------------------------------------------------------

def test_ac26_assets(game, caplog):
    from engine.core.paths import GamePaths
    from tests.fixtures.F04 import gen_images as gen
    from tests.render.conftest import make_assets
    gen.write(game, {"images/hana/happy.png": gen.block(32, 48, (250, 10, 10)),
                     "gui/lantern_back.png": gen.block(16, 16, (10, 10, 250))})
    registry = load_plugins(game)
    w = HostU(game, registry=registry)
    w.shell.assets = make_assets(GamePaths.for_game(game))
    w.ports.image = lambda name: w.shell.assets.image(
        {"hana happy": "images/hana/happy.png"}.get(name, name))
    seen = {}

    def on_start(ctx):
        seen["image"] = ctx.image("hana happy")
        seen["gui"] = ctx.gui_image("gui/lantern_back.png")
        seen["font"] = ctx.font(None, 28)
        seen["missing"] = ctx.image("hana nope")
        ctx.play_sound("sfx/flip.ogg")
        ctx.play_sound("sfx/flip.ogg", volume=50)

    w.behavior.on_start = on_start
    w.start()
    assert w.fatal == []
    assert seen["image"].ref == "images/hana/happy.png"
    assert seen["image"].size == (32, 48) and not seen["image"].is_placeholder
    assert seen["gui"].size == (16, 16)
    assert seen["font"] == w.shell.theme.font(28)
    assert seen["missing"].is_placeholder
    assert ("play_ui", "sfx/flip.ogg", 100, "minigame") in w.audio.calls
    assert ("play_ui", "sfx/flip.ogg", 50, "minigame") in w.audio.calls
    # s5b: [theme.minigame] background_image missing → the gradient plus one W64; a real
    # one covers the canvas.
    cfg = ThemeConfig()
    for ref, color in (("gui/nope.png", None), ("gui/lantern_back.png", (10, 10, 250))):
        theme = dataclasses.replace(cfg, minigame=dataclasses.replace(cfg.minigame,
                                                                      background_image=ref))
        w = HostU(game, registry=registry, cfg=theme)
        w.shell.assets = make_assets(GamePaths.for_game(game))
        w.ui = UiHarness(w.shell)                         # its canvas draws with these assets
        w.behavior.reset()
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        w.start()
        w.frames(3)
        w64 = [r for r in caplog.records if getattr(r, "code", None) == "W64"]
        if color is None:
            assert len(w64) == 1 and "[theme.minigame] background_image" in w64[0].getMessage()
            assert "so the gradient is used." in w64[0].getMessage()
            top = w.ui.px(640, 2)
            assert max(abs(a - b) for a, b in zip(top, cfg.title.fill_top_color)) <= 8
        else:
            assert w64 == [] and w.ui.px(20, 700) == color


# --- AC-F23-27 — audio -------------------------------------------------------------------------

@pytest.mark.parametrize("end", ["finish", "abandon"])
def test_ac27_audio(world, end):
    w = world

    def on_start(ctx):
        ctx.music().play("bgm/game.ogg")
        for _ in range(4):
            ctx.play_sound("sfx/flip.ogg")

    w.behavior.on_start = on_start
    w.behavior.on_event = lambda ctx, ev: ctx.finish(1) or True
    w.start()
    assert w.audio.calls[:2] == [("take_music", "minigame"), ("play", "bgm/game.ogg")]
    assert [c for c in w.audio.calls if c[0] == "play_ui"] == \
        [("play_ui", "sfx/flip.ogg", 100, "minigame")] * 4      # the pool caps at 3 (F08)
    if end == "finish":
        w.frame(H.key(pygame.K_SPACE))
    else:
        w.host.abandon()
    assert w.audio.calls[-2:] == [("release",), ("stop_ui", 0.1, "minigame")]


# --- AC-F23-29 — the engine's widgets, theme, and keys ----------------------------------------

@pytest.mark.parametrize("row", ["keys", "pad", "click", "back", "theme", "codex"])
def test_ac29_widgets_theme_and_keys(game, row):
    w = HostU(game, cfg=SOUNDS)
    b = w.behavior
    if row in ("keys", "pad", "click"):
        b.grid = True
        running(w)
        if row == "keys":
            w.frame(H.key(pygame.K_DOWN))
            w.frame(H.key(pygame.K_RIGHT))
            w.frame(H.key(pygame.K_RETURN))
            assert w.shell.sounds.count("sfx/activate.ogg") == 1
            assert "sfx/focus.ogg" in w.shell.sounds
        elif row == "pad":
            for button in (pygame.CONTROLLER_BUTTON_DPAD_DOWN,
                           pygame.CONTROLLER_BUTTON_DPAD_RIGHT, pygame.CONTROLLER_BUTTON_A):
                w.frame(H.pad(button))
        else:
            center = b.buttons[2].box.center
            w.frame(H.motion(center))
            w.frame(H.down(center), H.up(center))
        w.frames(25)
        assert [d.result for d in w.done()] == [2 if row == "click" else 3]
    elif row == "back":
        running(w)
        w.frame(H.key(pygame.K_BACKSPACE), H.key(pygame.K_ESCAPE))
        assert [ev.nav for ev in handle_events(w)] == [Nav.BACK]   # Esc never reaches it
    elif row == "theme":
        seen = {}

        def on_start(ctx):
            seen["color"] = ctx.theme.get("panel.text_color")
            seen["yes"] = ctx.words.get("yes")
            seen["mine"] = (ctx.theme.mine("card.back_color"), ctx.words.mine("hint"))
            ctx.play_ui("button.activate_sound")

        b.on_start = on_start
        w.start()
        assert seen["color"] == w.shell.theme.cfg.panel.text_color
        assert seen["yes"] == "Yes" and seen["mine"] == ((0x20, 0x30, 0x40), "Find the pairs")
        assert ("play_ui", "sfx/activate.ogg", 100, "minigame") in w.audio.calls
    else:
        seen = {}

        def on_start(ctx):
            view = ctx.codex_view(filter=CodexFilter(frozenset({"item"})),
                                  pick=PickAction("Show", lambda name: ctx.finish(name)))
            groups = view.build(ctx.area, 1.0)
            ctx.scope.set_groups(groups)
            ctx.scope.set_default(view.default_widget())
            seen["view"] = view
            seen["area"] = ctx.area

        b.on_start = on_start
        running(w, items=("coin",))
        assert seen["area"].w >= 640 and seen["area"].h >= 400
        assert seen["view"].default_widget() is not None
        for key in (pygame.K_DOWN, pygame.K_RETURN, pygame.K_RETURN):
            w.frame(H.key(key))
        w.frames(25)
        assert w.fatal == [] and [d.result for d in w.done()] == ["coin"]


# --- AC-F23-31 — backdrop and what is hidden (Host U rows) -------------------------------------

def test_ac31_backdrop(game):
    write(game, "minigames/stagey.py",
          "from engine.minigames.api import Minigame, register\n"
          "@register\nclass Stagey(Minigame):\n    name = 'stagey'\n    over_stage = True\n")
    registry = load_plugins(game)
    w = HostU(game, registry=registry)
    cfg = w.shell.theme.cfg
    running(w)
    top, bottom = w.ui.px(640, 2), w.ui.px(640, 717)
    assert max(abs(a - b) for a, b in zip(top, cfg.title.fill_top_color)) <= 8
    assert max(abs(a - b) for a, b in zip(bottom, cfg.title.fill_bottom_color)) <= 8
    w.host.abandon()
    w.start("stagey", {})
    w.frame()
    expected = tuple(round(200 * 0.7 + c * 0.3) for c in cfg.menu.dim_color)
    assert max(abs(a - b) for a, b in zip(w.ui.px(640, 600), expected)) <= 8
    draws = w.scene.draws
    w.frames(3)
    assert w.scene.draws == draws                # opaque: the in-game screen isn't drawn


# --- AC-F23-32 — dissolves (unit canvas) ------------------------------------------------------

@pytest.mark.parametrize("row", ["dissolve_in", "cut", "restored", "end", "inputs", "esc",
                                 "f5_out", "resize"])
def test_ac32_dissolves(game, row):
    w = HostU(game, reduce_motion=row == "cut")

    def on_event(ctx, ev):
        if ev.ui.type == pygame.KEYDOWN and ev.ui.raw.key == pygame.K_f:
            ctx.finish(4)
            return True
        return False

    w.behavior.on_event = on_event
    P = (640, 600)
    if row == "restored":
        w.start(restored=True)
        w.frame()
        assert w.session.phase is Phase.RUNNING
        return
    w.start(restored=False)
    if row == "cut":
        w.frame()
        assert w.session.phase is Phase.RUNNING                  # no in-between frame
        w.frame(H.key(pygame.K_f))
        assert len(w.done()) == 1                                 # the end is a cut too
        return
    if row == "dissolve_in":
        w.frames(9)                                               # 150 ms
        mid = w.ui.px(*P)
        w.frames(9)
        assert w.session.phase is Phase.RUNNING
        end = w.ui.px(*P)
        expected = tuple((200 + e) / 2 for e in end)
        assert max(abs(a - b) for a, b in zip(mid, expected)) <= 10
        assert [n for n, _ in w.behavior.calls if n in ("update", "handle_event")] == []
        return
    if row == "inputs":
        w.frame(H.down((640, 360)), H.up((640, 360)), H.key(pygame.K_RETURN),
                H.wheel((640, 360), 1))
        assert handle_events(w) == [] and w.used() == []
        assert w.scene.received == []
        return
    if row == "esc":
        w.frame(H.key(pygame.K_ESCAPE))
        assert w.session.phase is Phase.RUNNING                   # snapped, then it acts
        assert [e.raw.key for e in w.scene.received] == [pygame.K_ESCAPE]
        return
    if row == "resize":
        w.frames(2)
        w.ui.resize((1600, 900))
        w.frame()
        assert w.session.phase is Phase.RUNNING
        return
    w.frames(20)
    assert w.session.phase is Phase.RUNNING
    w.frame(H.key(pygame.K_f))
    assert w.session.phase is Phase.CLOSING and w.done() == []
    if row == "f5_out":
        w.frame(H.key(pygame.K_F5))
        assert len(w.done()) == 1
        assert [e.raw.key for e in w.scene.received] == [pygame.K_F5]
        return
    calls = len(w.behavior.calls)
    for _ in range(16):
        w.frame()
        assert w.done() == []
    w.frames(2)
    assert len(w.done()) == 1 and w.session is None
    assert all(n == "draw" for n, _ in w.behavior.calls[calls:])   # no update, no input


# --- AC-F23-33 — input routing -----------------------------------------------------------------

ROUTES = [
    # (id, event, the plugin gets it, falls to the in-game screens when unused)
    ("esc", H.key(pygame.K_ESCAPE), False, True),
    ("start", H.pad(pygame.CONTROLLER_BUTTON_START), False, True),
    ("right", H.down((640, 360), 3), True, True),
    ("east", H.pad(pygame.CONTROLLER_BUTTON_B), True, True),
    ("backspace", H.key(pygame.K_BACKSPACE), True, False),
    ("wheel_up", H.wheel((640, 360), 1), True, True),
    ("pageup", H.key(pygame.K_PAGEUP), True, True),
    ("lb", H.pad(pygame.CONTROLLER_BUTTON_LEFTSHOULDER), True, True),
    ("wheel_down", H.wheel((640, 360), -1), True, True),
    ("pagedown", H.key(pygame.K_PAGEDOWN), True, True),
    ("rb", H.pad(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER), True, True),
    ("f5", H.key(pygame.K_F5), False, True),
    ("f9", H.key(pygame.K_F9), False, True),
    ("h", H.key(pygame.K_h), True, False),
    ("a", H.key(pygame.K_a), True, False),
    ("ctrl", H.key(pygame.K_LCTRL, pygame.KMOD_LCTRL), True, False),
    ("tab", H.key(pygame.K_TAB), True, False),
    ("space", H.key(pygame.K_SPACE), True, False),
    ("enter", H.key(pygame.K_RETURN), True, False),
    ("click", H.down((640, 360)), True, False),
    ("arrow", H.key(pygame.K_LEFT), True, False),
    ("dpad", H.pad(pygame.CONTROLLER_BUTTON_DPAD_UP), True, False),
    ("middle", H.down((640, 360), 2), True, False),
    ("north", H.pad(pygame.CONTROLLER_BUTTON_Y), True, False),
    ("west", H.pad(pygame.CONTROLLER_BUTTON_X), True, False),
    ("letterbox", H.down((10, 10), in_canvas=False), False, False),
]


@pytest.mark.parametrize("use", [False, True], ids=["unused", "used"])
def test_ac33_input_routing(world, use):
    w = running(world)
    w.behavior.use_all = use
    for name, event, gets, falls in ROUTES:
        w.scene.received.clear()
        before = len(handle_events(w))
        w.frame(event)
        got = handle_events(w)[before:]
        assert (len(got) == 1) is gets, name
        if gets:
            assert got[0].ui is event, name
            if name in ("right", "east", "backspace"):
                assert got[0].nav is Nav.BACK, name
            if name in ("pageup", "lb"):
                assert got[0].nav is Nav.PAGE_UP, name
        assert (len(w.scene.received) == 1) is (falls and not (use and gets)), name


# --- AC-F23-34 — used inputs -------------------------------------------------------------------

def test_ac34_used_inputs(world):
    w = world
    w.behavior.use = {pygame.KEYDOWN, pygame.MOUSEWHEEL}
    w.start(restored=False)
    w.frame(H.key(pygame.K_SPACE))                          # during the fade: never counts
    w.frames(20)
    w.behavior.use = {pygame.MOUSEMOTION, pygame.KEYUP}
    w.frame(H.motion((10, 10)), H.key(pygame.K_SPACE, up=True), H.down((5, 5)))
    assert w.used() == []                                   # motion, release, unused press
    w.behavior.use = set()
    w.behavior.on_event = lambda ctx, ev: "yes" if ev.ui.type == pygame.MOUSEWHEEL else 0
    w.frame(H.wheel((640, 360), -1))                        # a truthy non-bool counts
    w.frame(H.key(pygame.K_SPACE), H.wheel((640, 360), -1))
    assert w.used() == [MinigameUsed(w.session.cmd.sid, w.session.cmd.run)]
    w.behavior.on_event = None                              # a widget taking a press counts
    w.behavior.grid = True
    w.start(run=2)
    w.frame(H.down(w.behavior.buttons[0].box.center))
    assert len(w.used()) == 2 and w.used()[-1].run == 2


# --- AC-F23-35 — pause under menus and confirms; focus -----------------------------------------

@pytest.mark.parametrize("row", ["menu", "confirm_esc", "confirm_yes", "unfocused",
                                 "keys_focus", "mouse_focus"])
def test_ac35_pause_and_focus(world, row):
    w = world
    b = w.behavior
    b.grid = True
    if row == "mouse_focus":
        w.shell.stack.last_input = InputKind.MOUSE
        running(w)
        assert w.session.scope.focused is None
        w.frame(H.key(pygame.K_RIGHT))
        assert w.session.scope.focused is b.buttons[0]
        return
    w.shell.stack.last_input = InputKind.KEYS
    if row == "keys_focus":                  # once the fade-in ends: no marker before it
        w.start(restored=False)
        scope = w.session.scope
        assert w.session.phase is Phase.OPENING and scope.focused is None
        w.frames(30)
        assert scope.focused is b.buttons[0] and scope.visible
        return
    running(w)
    scope = w.session.scope
    w.frame(H.key(pygame.K_RIGHT))
    focused = scope.focused
    if row == "menu":
        menu = ColumnMenu(w.shell, by=InputKind.KEYS, fade=False)
        w.shell.stack.push(menu)
        dt = b.dt
        updates = len([c for c in b.calls if c[0] == "update"])
        w.frames(600)
        assert b.dt == dt and len([c for c in b.calls if c[0] == "update"]) == updates
        w.shell.stack.remove(menu)
        before = pygame.image.tobytes(w.frame(), "RGB")
        assert scope.focused is focused and w.session.phase is Phase.RUNNING
        assert pygame.image.tobytes(w.frame(), "RGB") == before
        return
    if row == "unfocused":
        w.focused = False
        dt = b.dt
        w.frames(60)
        assert b.dt == dt
        return
    answers = []
    b.on_event = lambda ctx, ev: ctx.confirm("hint", lambda: answers.append("yes"),
                                             lambda: answers.append("no")) or True
    w.frame(H.key(pygame.K_SPACE))
    assert isinstance(w.shell.stack.top, ConfirmScreen)
    b.on_event = None
    if row == "confirm_esc":
        w.frame(H.key(pygame.K_ESCAPE))
        w.frames(20)
        assert answers == ["no"] and w.scene.received == []      # no game menu
    else:
        w.frame(H.key(pygame.K_LEFT))
        w.frame(H.key(pygame.K_RETURN))
        w.frames(20)
        assert answers == ["yes"]
    assert w.shell.stack.top is w.screen and w.session.phase is Phase.RUNNING


# --- AC-F23-36 — skip and auto (Host U rows) ---------------------------------------------------

def test_ac36_skip_stops_at_open(world):
    w = world
    stops = []
    w.ports.stop_skip = lambda: stops.append(1)
    running(w)
    assert stops == [1]
    w.frame(H.key(pygame.K_LCTRL, pygame.KMOD_LCTRL), H.key(pygame.K_TAB))
    assert [ev.ui.raw.key for ev in handle_events(w)] == [pygame.K_LCTRL, pygame.K_TAB]
    assert w.scene.received == [] and stops == [1]


# --- AC-F23-37 — the limit cue's anchor ---------------------------------------------------------

def test_ac37_cue_anchor(world):
    w = world
    w.behavior.hint = "Find the pairs"
    running(w)
    hint = w.session.frame.hint
    assert w.cue.fn() == (hint.right - 52, hint.y)
    w.host.abandon()
    assert w.cue.fn is None
    w.behavior.hint = None
    running(w)
    assert w.cue.fn() == (1088, 668)
    w.host.abandon()
    w.behavior.cue = (300, 200)
    running(w)
    assert w.cue.fn() == (300, 200)
    w.behavior.on_event = lambda ctx, ev: ctx.finish(1) or True
    w.frame(H.key(pygame.K_SPACE))
    assert w.cue.fn is None                                       # reset for F14's textbox


# --- AC-F23-38 — opening picture and save thumbnail --------------------------------------------

def test_ac38_opening_picture_and_thumbnail(world, tmp_path):
    w = world
    w.behavior.use = {pygame.KEYDOWN}
    w.start(restored=False)
    w.frame()
    assert w.shell.source() is None                               # during the fade-in
    opening = w.session.opening.copy()
    w.frames(20)
    for _ in range(3):
        w.frame(H.key(pygame.K_SPACE))
    assert w.behavior.counter == 3
    pictures = [w.shell.source() for _ in range(3)]
    assert pictures[0] is pictures[1] is pictures[2] and w.host.smoothscales == 1
    assert pygame.image.tobytes(pictures[0], "RGB") == \
        pygame.image.tobytes(make_thumbnail(opening), "RGB")      # shows 0, not 3
    menu = ColumnMenu(w.shell, by=InputKind.KEYS, fade=False)
    w.shell.stack.push(menu)
    assert w.shell.source() is pictures[0]                        # paused: the same
    w.shell.stack.remove(menu)
    w.host.abandon()
    assert w.shell.source is None
    # The shell side (I-8): the source is asked first; None leaves F11's capture.
    from tests.ui.test_game_menu import game
    g = game(tmp_path / "rig")
    got: list = []
    thumb = pictures[0]
    g.shell.set_thumbnail_source(lambda: thumb)
    g.shell.capture_scene(got.append)
    assert got == [thumb]
    g.shell.set_thumbnail_source(lambda: None)
    g.shell.capture_scene(got.append)
    assert got == [thumb]                                         # waits for draw_layer


# --- AC-F23-44 — a plugin error ends on the error screen ---------------------------------------

@pytest.mark.parametrize("where", ["start", "layout", "handle_event", "update", "draw",
                                   "settings_changed", "confirm", "system_exit",
                                   "keyboard_interrupt", "thread_error", "no_text"])
def test_ac44_plugin_error_screen(world, caplog, where):
    w = world
    b = w.behavior
    caplog.set_level(logging.DEBUG, logger="vn.plugin")
    raising = {"system_exit": SystemExit(3), "keyboard_interrupt": KeyboardInterrupt(),
               "thread_error": MinigameThreadError("x"), "no_text": TypeError("'int' x")}
    if where in raising:
        exc = raising[where]

        def on_event(ctx, ev):
            raise exc

        b.on_event = on_event
        running(w)
        w.frame(H.key(pygame.K_SPACE))
        text = fatal_text(w)
        assert text.startswith("script/main.vns, line 9: minigame probe stopped with an "
                               "error in minigames/probe.py, line ")
        assert text.endswith(". Fix the plugin; the log has the details.")
        assert w.fatal[0].code == "E275" and w.session is None
        return
    if where in ("start", "layout", "draw"):
        b.raise_in = where
        w.start()
    elif where == "confirm":
        b.on_event = lambda ctx, ev: ctx.confirm("hint", lambda: (1 / 0)) or True
        running(w)
        w.frame(H.key(pygame.K_SPACE))
        b.on_event = None
        w.frame(H.key(pygame.K_LEFT))
        w.frame(H.key(pygame.K_RETURN))
        w.frames(20)
        assert w.fatal[0].code == "E275"
        assert "stopped with an error in minigames/probe.py" in fatal_text(w)
        return
    else:
        running(w)
        b.raise_in = where
        if where == "settings_changed":
            w.shell.painter.set_text_scale(lambda: 1.5)
        w.frame(H.key(pygame.K_SPACE))
    assert fatal_text(w) == f"{WHERE[0]}, line {WHERE[1]}: {E275_88}"
    assert w.session is None and w.done() == []
    records = [r for r in caplog.records if r.levelno == logging.ERROR
               and r.name == "vn.plugin"]
    assert len(records) == 1 and "<minigames/probe.py>" in records[0].exc_text
    assert "return 1 / 0" in records[0].exc_text                  # from linecache


# --- AC-F23-45 — a stuck plugin ------------------------------------------------------------------

@pytest.mark.parametrize("where", ["update", "handle_event", "draw"])
def test_ac45_stuck_plugin(game, monkeypatch, where):
    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.1)
    watchdog = Watchdog(tick=0.02)
    watchdog.start()
    try:
        w = HostU(game, guard=watchdog)
        assert w.host.ports.guard is watchdog
        if where == "draw":
            w.behavior.loop_in = "draw"
            w.start()
        else:
            running(w)
            w.behavior.loop_in = where
            w.frame(H.key(pygame.K_SPACE))
    finally:
        watchdog.stop()
    assert w.fatal[0].code == "E277"
    assert fatal_text(w) == (
        "script/main.vns, line 9: minigame probe ran for 0.1 seconds in minigames/probe.py, "
        "line 120, without finishing, so it is probably stuck in a loop. Check any while "
        "loop there.")


# --- AC-F23-51 — group F: plugin values become exact built-ins ---------------------------------

class Name(str):
    pass


class Loop:
    def __bool__(self):
        while True:
            pass


@pytest.mark.parametrize("row", ["set", "tuple", "subclass_result", "nan", "deep",
                                 "bool_amount", "float_amount", "big_amount", "subclass_name",
                                 "many", "texts"])
def test_ac51_plugin_values(world, row):
    w = world
    b = w.behavior
    results = {"set": {1}, "tuple": (1, 2), "subclass_result": Name("x"),
               "nan": float("nan"), "deep": None}
    if row in results:
        value = results[row]
        if row == "deep":
            value = []
            for _ in range(105):
                value = [value]
        b.on_event = lambda ctx, ev: ctx.finish(value) or True
        running(w)
        w.frame(H.key(pygame.K_SPACE))
        assert w.fatal[0].code == "E276" and w.done() == []
        return
    requests = {"bool_amount": [("points", "add", ("hana", True))],
                "float_amount": [("points", "add", ("hana", 1.5))],
                "big_amount": [("points", "add", ("hana", 10 ** 10))],
                "subclass_name": [("points", "add", (Name("hana"), 1))],
                "many": [("codex", "give", ("coin",))] * 1001}
    if row in requests:
        b.requests = requests[row]
        w.start()
        assert w.fatal[0].code == ("E275" if row in ("subclass_name", "many") else "E236")
        assert fatal_text(w).startswith("minigames/probe.py, line ")
        return
    b.heading = "\ud800" + "\u202e" + "\u2028" + "x" * 1_000_000
    b.hint = "a\nb" * 1000
    running(w)
    s = w.session
    assert s.heading_text.startswith("\ufffd") and len(s.heading_text) == 200
    assert "\u202e" not in s.heading_text and "\u2028" not in s.heading_text
    assert "\n" not in s.hint_text and len(s.hint_text) <= 1000
    assert w.fatal == []


def test_ac51_a_looping_bool_is_stopped(game, monkeypatch):
    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.1)
    watchdog = Watchdog(tick=0.02)
    watchdog.start()
    try:
        w = HostU(game, guard=watchdog)
        w.behavior.on_event = lambda ctx, ev: Loop()
        running(w)
        w.frame(H.key(pygame.K_SPACE))
    finally:
        watchdog.stop()
    assert w.fatal[0].code == "E277"


# --- AC-F23-52 — group G: asset calls stay in the sandbox --------------------------------------

def test_ac52_hostile_asset_refs(world):
    w = world
    refs = ["../../secret.png", "C:/Windows/win.ini", "\\\\server\\share\\x.png", "CON",
            "audio/../config.toml", "gui/../../x.png", "x" * 2000, "\x00"]
    seen = []

    def on_start(ctx):
        for ref in refs:
            seen.append(ctx.image(ref).is_placeholder)
            seen.append(ctx.gui_image(ref) is None)            # F24 07 I-5 (Q-c)
            ctx.font(ref, 28)
            ctx.play_sound(ref)

    w.behavior.on_start = on_start
    w.start()
    assert w.fatal == [] and seen == [True] * (2 * len(refs))


# --- AC-F23-55 — group J: failure text can't hang, leak, or bloat ------------------------------

class BadStr(Exception):
    def __str__(self):
        raise ValueError("no")


class LoopStr(Exception):
    def __str__(self):
        while True:
            pass


@pytest.mark.parametrize("row", ["home", "str_raises", "str_loops", "huge", "forged"])
def test_ac55_failure_text(game, monkeypatch, caplog, row):
    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.1)
    install(Redactor([RedactRoot("<game>", str(game))], home_name="aiko",
                     case_insensitive=True))
    caplog.set_level(logging.DEBUG, logger="vn.plugin")
    exc = {"home": FileNotFoundError(f"cannot open C:\\Users\\aiko\\x and {game}"),
           "str_raises": BadStr(), "str_loops": LoopStr(),
           "huge": ValueError("v" * 10_000_000),
           "forged": ValueError("bad\n2026-11-02 00:00:00.000 ERROR   runtime  fake")}[row]
    watchdog = Watchdog(tick=0.02)
    watchdog.start()
    try:
        w = HostU(game, guard=watchdog)

        def on_event(ctx, ev):
            raise exc

        w.behavior.on_event = on_event
        running(w)
        w.frame(H.key(pygame.K_SPACE))
    finally:
        watchdog.stop()
    text = fatal_text(w)
    assert w.fatal[0].code == "E275" and "aiko" not in text and str(game) not in text
    if row in ("str_raises", "str_loops"):
        import re                                    # no Python text: the line, then "."
        assert re.search(r"minigames/probe\.py, line \d+\. Fix the plugin; the log has the "
                         r"details\.$", text), text
    if row == "huge":
        assert len(text) < 400
    formatted = [RedactingFormatter().format(r) for r in caplog.records
                 if r.name == "vn.plugin" and r.levelno == logging.ERROR]
    assert len(formatted) == 1
    assert "aiko" not in formatted[0]
    assert not any(line.startswith("2026-11-02 00:00:00.000")
                   for line in formatted[0].splitlines()[1:])


# --- AC-F23-63 — CI guard: costs (host rows) --------------------------------------------------

def test_ac63_costs(world):
    w = world
    w.behavior.heading = True
    w.behavior.hint = "Find the pairs"
    cache = w.shell.assets.cache

    def held():
        return [k for k in cache.keys() if k and k[0] == SNAPSHOT_KEY]

    w.start(restored=False)
    assert w.host.offscreen_draws == 2                     # the in-game draw and the opening
    assert len(held()) == 2
    w.frames(20)
    assert w.session.phase is Phase.RUNNING and held() == [] and w.host.smoothscales == 1
    w.frames(10)
    keys = len(cache.keys())
    w.frames(600)
    assert len(cache.keys()) == keys                       # nothing new per frame
    assert w.host.offscreen_draws == 2


# --- AC-F23-53's host half: a thread error or a refused title inside a call is E275 -------------

def test_ac53_thread_error_inside_a_call_is_e275(world):
    w = world
    errors = []

    def on_start(ctx):
        def worker():
            try:
                ctx.points.get("hana")
            except MinigameThreadError as e:
                errors.append(e)
        t = threading.Thread(target=worker)
        t.start()
        t.join(5)
        ctx.codex.title("nope")

    w.behavior.on_start = on_start
    w.start()
    assert len(errors) == 1
    assert w.fatal[0].code == "E275" and 'there is no item "nope"' in fatal_text(w)
    assert w.screen is None or isinstance(w.screen, MinigameScreen)
