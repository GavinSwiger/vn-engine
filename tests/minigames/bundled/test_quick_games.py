"""F53 step W1: the three quick minigames together (Lock, Stay still, Hand game): AC-F53-01
(registration and imports), 02 (every refusal), 03 (test and skipped outcomes), 04 (Skip
Game), 05 (keyboard only, gamepad only, mouse only), 06 (Reduce motion), 07 (no color
literal; six schemes), 08 (layouts at 100 % and 150 % text) and 33 (docs)."""

import ast
import re
import sys
from pathlib import Path

import pygame
import pytest

from engine.core.minigame_types import Outcome
from engine.minigames import api
from engine.minigames.bundled import BUNDLED, PuzzleRoom
from engine.minigames.bundled import hand_rules, lock_rules, still_rules
from engine.minigames.bundled.code_lock import CodeLock
from engine.minigames.bundled.hand_game import HandGame
from engine.minigames.bundled.stay_still import StayStill
from engine.ui.focus import Box
from engine.ui.nav import InputKind
from tests.minigames.bundled.quick_host import H, done_after, open_game, pad, tap, typed
from tests.minigames.host_u import NAMES, HostU

REPO = Path(__file__).resolve().parents[3]
BUNDLED_DIR = REPO / "engine" / "minigames" / "bundled"
GAMES = {"code_lock": CodeLock, "stay_still": StayStill, "hand_game": HandGame}
BASE = {"code_lock": {**lock_rules.DEFAULTS, "code": "0417"},
        "stay_still": dict(still_rules.DEFAULTS),
        "hand_game": {**hand_rules.DEFAULTS, "opponent": "Hana"}}
T = "is 1 to {n} characters on one line."

# (game, changed arguments, reason) in each game's check order (01 §3.4).
REASONS = [
    ("code_lock", {"kind": "dail"}, 'kind must be "keypad" or "dial", but it is "dail". Did you '
     'mean "dial"?'),
    ("code_lock", {"code": 417}, 'code must be text in quotes, such as code="0417", but it is '
     "a whole number."),
    ("code_lock", {"code": "12a4"}, 'a keypad code is 1 to 12 digits from 0 to 9, but code is '
     '"12a4".'),
    ("code_lock", {"kind": "dial", "code": "12"}, 'a dial code is 3 to 6 digits, or 3 to 6 '
     'letters from A to Z, but code is "12".'),
    ("code_lock", {"tries": 100}, "tries must be a whole number from 0 (no limit) to 99, but it "
     "is 100."),
    ("code_lock", {"hint": 5}, "hint must be text in quotes, or None, but it is a whole number."),
    ("code_lock", {"hint": ""}, "hint is empty; it is 1 to 120 characters on one line."),
    ("code_lock", {"hint": "x" * 130}, "hint is 130 characters long; it is 1 to 120 characters "
     "on one line."),
    ("code_lock", {"hint": "a\nb"}, "hint has a line break or hidden character; it is 1 to 120 "
     "characters on one line."),
    ("code_lock", {"hint": " a"}, "hint starts or ends with a space. Remove the space."),
    ("code_lock", {"hint_after": -1}, "hint_after must be a whole number from 0 to 99, but it is "
     "-1."),
    ("code_lock", {"leave": "yes"}, 'leave must be True or False, but it is "yes".'),
    ("stay_still", {"seconds": 2}, "seconds must be a whole number from 3 to 120, but it is 2."),
    ("stay_still", {"line": 5}, "line must be text in quotes, or None, but it is a whole "
     "number."),
    ("stay_still", {"speaker": "x" * 30}, "speaker is 30 characters long; it is 1 to 24 "
     "characters on one line."),
    ("stay_still", {"flinch_line": ""}, "flinch_line is empty; it is 1 to 160 characters on one "
     "line."),
    ("stay_still", {"strict": 1}, "strict must be True or False, but it is 1."),
    ("stay_still", {"mouse": "yes"}, 'mouse must be True or False, but it is "yes".'),
    ("stay_still", {"ready": None}, "ready must be True or False, but it is None."),
    ("hand_game", {"opponent": None}, "opponent must be text in quotes, but it is None."),
    ("hand_game", {"rounds": 10}, "rounds must be a whole number from 1 to 9, but it is 10."),
    ("hand_game", {"mode": "cheet"}, 'mode must be "fair", "kind", "cheat", or "sly", but it '
     'is "cheet". Did you mean "cheat"?'),
]


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def start(w: HostU, name: str, **args):
    g = open_game(w, name, {**BASE[name], **args})
    w.frame()
    return g


# --- AC-F53-01 ---------------------------------------------------------------------------------

def test_ac_f53_01_registration_and_imports():
    at = BUNDLED.index(PuzzleRoom)
    assert BUNDLED[-3:] == (CodeLock, StayStill, HandGame) and BUNDLED.index(CodeLock) > at
    for name, cls in GAMES.items():
        entry = api.declarations(cls, "engine")
        assert (entry.name, entry.api, entry.over_stage) == (name, "1.1", True)
    allowed = {"engine.minigames.api", "engine.minigames.bundled.rule_text"}
    for module in ("lock_rules", "still_rules", "hand_rules"):
        tree = ast.parse((BUNDLED_DIR / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) else []
            for found in names:
                assert found in allowed or found.split(".")[0] in sys.stdlib_module_names, \
                    (module, found)


# --- AC-F53-02 ---------------------------------------------------------------------------------

def test_ac_f53_02_every_refusal_in_order():
    for name, changed, reason in REASONS:
        args = {**BASE[name], **changed}
        before = repr(args)
        assert GAMES[name]().check_args(args) == reason, (name, changed)
        assert repr(args) == before
    for name, base in BASE.items():
        assert GAMES[name]().check_args(dict(base)) is None, name
    # The first problem only, in table order.
    assert CodeLock().check_args({**BASE["code_lock"], "kind": 1, "code": 5, "tries": -1}) \
        .startswith("kind must be")
    assert CodeLock().check_args({**BASE["code_lock"], "code": "x", "tries": -1}) \
        .startswith("a keypad code")
    assert CodeLock().check_args({**BASE["code_lock"], "tries": True, "leave": 0}) \
        .startswith("tries must be")
    assert StayStill().check_args({**BASE["stay_still"], "speaker": "", "ready": 0}) \
        .startswith("speaker is empty")
    assert HandGame().check_args({**BASE["hand_game"], "rounds": 0, "mode": "x"}) \
        .startswith("rounds must be")
    # Codes are ASCII: superscripts and accented letters are refused.
    assert CodeLock().check_args({**BASE["code_lock"], "code": "12²"}).startswith("a keypad")
    assert CodeLock().check_args({**BASE["code_lock"], "kind": "dial", "code": "café"}) \
        .startswith("a dial code")


# --- AC-F53-03 ---------------------------------------------------------------------------------

def test_ac_f53_03_test_and_skipped_outcomes():
    expected = {"code_lock": (True, True), "stay_still": (0, 0)}
    for name, (test, skipped) in expected.items():
        sig = api.declarations(GAMES[name], "engine").sig
        assert (sig.test, sig.skipped) == (Outcome(test), Outcome(skipped))
    sig = api.declarations(HandGame, "engine").sig
    for mode, test in (("fair", "won"), ("kind", "won"), ("cheat", "lost"), ("sly", "lost")):
        args = {**BASE["hand_game"], "mode": mode}
        assert sig.outcome("test", args, NAMES) == Outcome(test)
        assert sig.outcome("skipped", args, NAMES) == Outcome("draw")


# --- AC-F53-04 ---------------------------------------------------------------------------------

def test_ac_f53_04_skip_game(game):
    w = HostU(game)
    for name, result in (("code_lock", True), ("stay_still", 0), ("hand_game", "draw")):
        g = open_game(w, name, {**BASE[name], **({"mode": "cheat"} if name == "hand_game"
                                                  else {})}, skippable=True)
        w.frames(3)
        assert w.host.can_skip()
        w.host.skip(w.session)
        done = done_after(w)
        assert (done.result, done.changes) == (result, ()) and g.finishes == [], name


# --- AC-F53-05 ---------------------------------------------------------------------------------

KEYS = {"up": pygame.K_UP, "down": pygame.K_DOWN, "left": pygame.K_LEFT,
        "right": pygame.K_RIGHT}
DPAD = {"up": pygame.CONTROLLER_BUTTON_DPAD_UP, "down": pygame.CONTROLLER_BUTTON_DPAD_DOWN,
        "left": pygame.CONTROLLER_BUTTON_DPAD_LEFT,
        "right": pygame.CONTROLLER_BUTTON_DPAD_RIGHT}


def step(w, how: str, direction: str) -> None:
    w.frame(*(tap(KEYS[direction]) if how == "keys" else pad(DPAD[direction])))


def activate(w, how: str, target) -> None:
    """Reach ``target`` and activate it with one input kind only."""
    if how == "mouse":
        w.ui.click(target.box.center)
        return
    scope = w.session.scope
    for _ in range(40):
        f = scope.focused
        if f is target and scope.visible:
            break
        if f is None or not scope.visible:
            step(w, how, "down")                    # the first press focuses the default
            continue
        (fx, fy), (tx, ty) = f.box.center, target.box.center
        if abs(tx - fx) > abs(ty - fy):
            step(w, how, "right" if tx > fx else "left")
        else:
            step(w, how, "down" if ty > fy else "up")
    assert scope.focused is target, (how, target)
    w.frame(*(tap(pygame.K_RETURN) if how == "keys" else pad(pygame.CONTROLLER_BUTTON_A)))


def any_press(w, how: str) -> None:
    if how == "keys":
        w.frame(*tap(pygame.K_z))
    elif how == "pad":
        w.frame(*pad(pygame.CONTROLLER_BUTTON_X))
    else:
        w.ui.click((640, 700))


@pytest.mark.parametrize("how", ["keys", "pad", "mouse"])
def test_ac_f53_05_one_input_kind_only(game, how):
    w = HostU(game)
    # Lock: opened (True), stepped back (False).
    g = start(w, "code_lock")
    for d in "0417":
        activate(w, how, g.keys[10 if d == "0" else int(d) - 1])   # 1–9, Clear, 0, Enter
    if g.full and w.session.scope.focused is not g.enter:
        assert how == "mouse"                                    # keys moved focus to Enter
    activate(w, how, g.enter)
    assert done_after(w).result is True
    g = start(w, "code_lock")
    activate(w, how, g.leave_button)
    assert done_after(w).result is False
    # The dial too.
    g = start(w, "code_lock", kind="dial", code="101")
    if how == "mouse":
        w.ui.click((g.wheel_widgets[0].box.center[0], g.wheel_widgets[0].box.y + 8))
        w.ui.click((g.wheel_widgets[2].box.center[0], g.wheel_widgets[2].box.y + 8))
    else:
        activate_wheel = g.wheel_widgets[0]
        while w.session.scope.focused is not activate_wheel or not w.session.scope.visible:
            step(w, how, "left")
        step(w, how, "up")
        step(w, how, "right")
        step(w, how, "right")
        step(w, how, "up")
    assert g.wheels == ["1", "0", "1"]
    activate(w, how, g.open_button)
    assert done_after(w).result is True
    # Stay still: 0, and a flinch.
    for touches in (0, 1):
        g = start(w, "stay_still", seconds=3)
        activate(w, how, g.ready_button)
        w.frames(60)
        for _ in range(touches):
            any_press(w, how)
        assert done_after(w).result == touches, (how, touches)
    # Hand game: won, lost, draw.
    for choose, word in ((hand_rules.beats, "won"), (hand_rules.loses_to, "lost"),
                         (lambda f: f, "draw")):
        g = start(w, "hand_game")
        while g.continue_button not in w.session.scope.widgets():
            hand = choose(g.fair_hands[-1])
            activate(w, how, g.hand_buttons[hand_rules.HANDS.index(hand)])
            if g.next_button in w.session.scope.widgets():
                activate(w, how, g.next_button)
        activate(w, how, g.continue_button)
        assert done_after(w).result == word, (how, word)


# --- AC-F53-06 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("reduce", [False, True])
def test_ac_f53_06_reduce_motion(game, reduce):
    w = HostU(game, reduce_motion=reduce)
    g = start(w, "code_lock", kind="dial", code="123")
    w.frame(*tap(pygame.K_UP))
    assert (g.slide(0) == 0) is reduce                       # the turn: a cut
    w.frame(*tap(pygame.K_RETURN))
    w.frame()
    assert (g.shake() == 0) is reduce                        # the wrong-code shake
    g = start(w, "code_lock")
    for ch in "0417":
        w.frame(*typed(ch))
    w.frame(*tap(pygame.K_RETURN))
    frames = 0
    while not g.finishes:
        w.frame()
        frames += 1
    assert frames == pytest.approx(42, abs=2)                # the 700 ms hold is unchanged
    g = start(w, "stay_still", ready=False, seconds=10)
    w.frames(60 + 30)                                        # 0.5 s into the countdown
    assert (g.bar() == pytest.approx(1.0)) is reduce         # steps once a second
    g = start(w, "hand_game", mode="cheat")
    fair = g.fair_hands[-1]
    w.ui.click(g.hand_buttons[hand_rules.HANDS.index(hand_rules.beats(fair))].box.center)
    w.frames(34)
    assert g.shown == fair                                   # the 600 ms hold is unchanged
    w.frames(2)
    assert g.shown != fair and g.captions[0].startswith("Hana switched hands!")
    assert (g.shake() == 0) is reduce


# --- AC-F53-07 ---------------------------------------------------------------------------------

_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b|\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)")


def test_ac_f53_07_engine_colors_only(game, tmp_path):
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.core.schemes import SCHEMES
    from engine.minigames.tables import PluginTables
    for module in ("code_lock", "stay_still", "hand_game"):
        text = (BUNDLED_DIR / f"{module}.py").read_text(encoding="utf-8")
        assert not _COLOR.findall(text), module
    assert len(SCHEMES) == 6
    for scheme in SCHEMES:
        root = tmp_path / scheme
        root.mkdir()
        (root / "config.toml").write_text(f'[theme]\npreset = "{scheme}"\n', encoding="utf-8")
        config = load_config(GamePaths.for_game(root)).config
        tables = PluginTables(config.theme.plugin, config.words.plugin, config.theme, dev=True)
        w = HostU(game, config=config, tables=tables, cfg=config.theme)
        for name in GAMES:
            start(w, name)
            w.session.last_kind = InputKind.KEYS
            scope = w.session.scope
            if scope.focused is None:
                w.frame(*tap(pygame.K_DOWN))
            assert scope.focused is not None and scope.visible, (scheme, name)
            w.frames(2)
            assert not w.fatal, (scheme, name)


# --- AC-F53-08 ---------------------------------------------------------------------------------

def _rects(lay) -> list[tuple]:
    out = []
    for value in vars(lay).values() if hasattr(lay, "__dict__") else \
            (getattr(lay, f) for f in lay.__slots__):
        if isinstance(value, tuple) and value and isinstance(value[0], tuple):
            out.extend(value)
        elif isinstance(value, tuple) and len(value) == 4:
            out.append(value)
    return out


def _inside(area: Box, rect) -> bool:
    x, y, w, h = rect
    return area.x - 1e-6 <= x and area.y - 1e-6 <= y and x + w <= area.right + 1e-6 \
        and y + h <= area.bottom + 1e-6


@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_ac_f53_08_layouts_fit(game, scale):
    w = HostU(game)
    w.shell.painter.set_text_scale(lambda: scale)
    long_hint = "A long hint that wraps onto a second line of the hint bar, " * 3
    cases = [("code_lock", {"code": "0" * 12, "hint": long_hint[:120].strip(), "hint_after": 0}),
             ("code_lock", {"code": "0417", "leave": False}),
             ("code_lock", {"kind": "dial", "code": "ABCDEF"}),
             ("stay_still", {"speaker": "X" * 24, "line": ("Don't touch anything. " * 8)[:160]
                             .strip()}),
             ("stay_still", {"ready": False}),
             ("hand_game", {"opponent": "W" * 24})]
    for name, args in cases:
        g = start(w, name, **args)
        w.frames(2)
        area = w.session.area
        lay = g.lay
        for rect in _rects(lay):
            assert _inside(area, rect), (name, args, scale, rect, area)


# --- AC-F53-33 ---------------------------------------------------------------------------------

def test_ac_f53_33_docs():
    text = (REPO / "docs" / "minigames.md").read_text(encoding="utf-8")
    sections = {}
    for heading, name in (("Lock", "code_lock"), ("Stay still", "stay_still"),
                          ("Hand game", "hand_game")):
        sections[name] = text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
        assert f"(`{name}`)" in sections[name]
        for sub in ("### Arguments", "### Playing", "### When the arguments are refused",
                    "### Changing the look and the words"):
            assert sub in sections[name], (name, sub)
    quick = "".join(sections.values())
    for name, changed, reason in REASONS:
        assert f"`{reason}`" in quick, reason
    w280 = lock_rules.w280_text(lock_rules.parse({"code": "1", "leave": False}))
    assert " ".join(w280.split()) in " ".join(sections["code_lock"].split())
    for name, cls in GAMES.items():
        for key, value in cls.words.items():
            assert f'{key} = "{value}"' in sections[name], (name, key)
        for key in cls.tokens:
            assert f"| `{key}` |" in sections[name], (name, key)
