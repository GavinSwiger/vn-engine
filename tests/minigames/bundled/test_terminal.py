"""F56 steps P3 and W1: the terminal on Host U and headless: AC-F56-06, 07, 08, 13 (through
E272), 14, 15, 16, 17, 18, 19, 20, 21, 22, 24, 25, 26 (once, dev only), 33."""

import dataclasses
import functools
import logging
import re
from pathlib import Path

import pygame
import pytest

from engine.core.config import load_config
from engine.core.minigame_types import CodexChange
from engine.core.paths import GamePaths
from engine.minigames.bundled import BUNDLED, terminal as module
from engine.minigames.bundled.terminal import TOKENS, Terminal
from engine.minigames.loader import load_plugins
from engine.minigames.context import PlayerSettings
from engine.runtime import headless
from engine.runtime.commands import StepBack, StoryFailed
from engine.script import load_story
from engine.script.loader import LoadOptions
from engine.ui.input import UiEvent
from engine.ui.nav import InputKind
from engine.ui.theme import plain_theme
from tests.fakes.ui_shell import UiHarness
from tests.minigames.host_u import HostU
from tests.runtime.minigame_story import ALL, finish, launched, said, start_of, step

H = UiHarness
REPO = Path(__file__).resolve().parents[3]
PC = {
    "welcome": "LIBRARY TERMINAL",
    "prompt": "A:\\>",
    "commands": [
        {"command": "dir", "reply": "DIARY.TXT"},
        {"command": "login", "password": "lantern", "known_from": "lanterns",
         "reply": "Welcome back."},
        {"command": "type diary.txt", "after": "login", "unlock": "moon", "reply": "June 3."},
        {"command": "del grades.dat", "help": False, "ends": "goal", "reply": "1 file deleted."},
        {"command": "logout", "help": False, "ends": "out", "reply": "Bye."},
    ],
}


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture
def world(game):
    return HostU(game)


def typed(text: str) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.TEXTINPUT, text=text), None, False)


def enter(w: HostU, text: str) -> None:
    w.frame(typed(text), H.key(pygame.K_RETURN))
    w.frame()


def open_pc(w: HostU, *, tips=(), data=PC, **args) -> Terminal:
    w.posted.clear()
    w.audio.calls.clear()
    w.host.start(w.command("terminal", {"data": data, **args}, tips=tips))
    assert not w.fatal, [f.format() for f in w.fatal]
    w.frame()
    return w.session.plugin


def shown(g: Terminal) -> list[str]:
    return [line for line, _ in g.lines]


def focused(w: HostU):
    return w.session.scope.focused


def done(w: HostU, frames: int = 60):
    for _ in range(frames):
        if w.done():
            return w.done()[-1]
        w.frame()
    return None


# --- AC-F56-06: passwords: dots, never in tried, history, or the log ------------------------------

def test_ac_f56_06_passwords_private(world, caplog):
    w = world
    caplog.set_level(logging.DEBUG)
    g = open_pc(w, result="details")
    enter(w, "login")
    assert g.field.mask and g.session.mode == "password"
    w.frame(typed("secretword"))
    assert g.field.plan(w.shell.painter, w.screen.look_for(g.field)).text == "•" * 10
    w.frame(H.key(pygame.K_RETURN))
    w.frame()
    assert "Password: ••••••••••" in shown(g) and "secretword" not in " ".join(shown(g))
    assert "secretword" not in g.session.tried and "secretword" not in g.session.history
    assert not [r for r in caplog.records if "secretword" in r.getMessage()]
    enter(w, "")                                           # an empty answer cancels
    enter(w, "logout")
    w.frame(H.key(pygame.K_RETURN))
    out = done(w)
    assert out.result == {"reached": False, "ended_by": "logout", "tried": ["login", "logout"]}


# --- AC-F56-07: ends: Continue, by Enter, south or click ------------------------------------------

@pytest.mark.parametrize(("line", "how", "reached"), [
    ("del grades.dat", "enter", True), ("logout", "south", False), ("del grades.dat", "click",
                                                                     True)])
def test_ac_f56_07_ends(world, line, how, reached):
    w = world
    g = open_pc(w)
    enter(w, line)
    assert g.session.ended is not None and focused(w) is g.continue_button
    assert not g.commands_button.enabled() and not g.leave_button.enabled()
    assert g.field not in w.session.scope.widgets()
    if how == "enter":
        w.frame(H.key(pygame.K_RETURN))
    elif how == "south":
        w.frame(H.pad(pygame.CONTROLLER_BUTTON_A))
    else:
        w.ui.click(g.continue_button.box.center)
    assert done(w).result is reached


# --- AC-F56-08: help, clear, exit, renamed words --------------------------------------------------

def test_ac_f56_08_builtins(world):
    w = world
    g = open_pc(w)
    enter(w, "help")
    assert shown(g)[-5:] == ["Commands you know:", "  dir", "  login", "  type diary.txt",
                             "Also: help, clear, exit"]
    enter(w, "clear")
    assert shown(g) == []
    enter(w, "exit")
    assert w.shell.stack.top is not w.screen               # the confirm
    w.frame(H.key(pygame.K_RETURN))                         # No (focused)
    w.frames(20)                                            # the confirm fades out
    assert w.session is not None and not g.finished and "exit" in g.session.tried
    enter(w, "exit")
    w.frame(H.key(pygame.K_LEFT), H.key(pygame.K_RETURN))   # Yes
    assert done(w).result is False
    g = open_pc(w)                                          # renamed built-in words
    g.word["help"] = "aide"
    enter(w, "aide")
    assert shown(g)[-1] == "Also: aide, clear, exit"


# --- AC-F56-13: refusals through E272 and check_story ---------------------------------------------

STORY = '''lock tip hana_password "Hana's notebook"
lock tip hana_diary "Hana's diary"
default hacked = False
define pc = {data}

label start:
    "Before."
    minigame terminal data=pc{args} into hacked
    "After."
'''


@functools.cache
def sigs(root: str):
    result = load_plugins(GamePaths(Path(root)), dev=False)
    assert result.ok and "terminal" in result.signatures()
    return result.signatures()


def program(root: Path, data: str, args: str = ""):
    (root / "script").mkdir(parents=True, exist_ok=True)
    (root / "script" / "main.vns").write_text(STORY.format(data=data, args=args),
                                              encoding="utf-8")
    return load_story(GamePaths(root.resolve()), LoadOptions(dev=False, minigames=sigs(str(root))))


def test_ac_f56_13_refusals_at_the_line(tmp_path):
    for n, (data, args, reason) in enumerate((
            ('{"commands": []}', "", "the terminal needs 1 to 100 commands, but it has 0."),
            ('{"commands": [{"command": "dir"}]}', ' result="detail"',
             'result must be "reached" or "details", not "detail". Did you mean "details"?'),
            ('{"commands": [{"command": "login", "password": "x", "known_from": '
             '"hana_pasword"}]}', "",
             '"login" names the tip "hana_pasword", which isn\'t a declared tip. Did you mean '
             '"hana_password"?'))):
        loaded = program(tmp_path / str(n), data, args)
        assert loaded.program is not None, [e.format() for e in loaded.errors]
        commands = headless.run_headless(loaded.program, seed=1,
                                         minigames=sigs(str(tmp_path / str(n))),
                                         inputs=["advance"])
        failed = commands[-1]
        assert type(failed) is StoryFailed and failed.error.code == "E272"
        assert failed.error.message.endswith(reason)


# --- AC-F56-14: the prompt line ------------------------------------------------------------------

def test_ac_f56_14_prompt_line(world):
    w = world
    g = open_pc(w)
    f = g.field
    assert f.bare and f.max_length == 80 and f.keep_keyboard and focused(w) is f
    assert f.allowed.preset == "any"
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_A))
    kb = w.session.keyboard
    assert kb.is_open
    for ch in "dir":
        kb.focus = ("key", kb.keys().index(ch.upper())) if ch.upper() in kb.keys() else kb.focus
    kb.page = 1                                            # abc
    for ch in "dir":
        kb.focus = ("key", kb.keys().index(ch))
        w.frame(H.pad(pygame.CONTROLLER_BUTTON_A))
    kb.focus = ("done", None)
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_A))             # Done runs the line
    w.frame()
    assert "DIARY.TXT" in shown(g) and kb.is_open          # and the keyboard stays open
    assert f.text == ""


# --- AC-F56-15: the Commands list --------------------------------------------------------------

def test_ac_f56_15_commands_list(world):
    w = world
    g = open_pc(w)
    g.ctx.scope.focus(g.commands_button, InputKind.KEYS)
    w.frame(H.key(pygame.K_RETURN))
    assert g.panel == "commands"
    assert [r.label for r in g.list.rows()] == ["dir", "login", "type diary.txt", "Close"]
    w.frame(H.key(pygame.K_RETURN))                         # pick "dir"
    assert g.panel == "screen" and g.field.text == "dir" and focused(w) is g.field
    assert "DIARY.TXT" not in shown(g)                      # nothing ran
    g.field.set_text("")
    enter(w, "login")
    g._open_commands()
    w.frame()
    assert [(r.label, r.enabled) for r in g.list.rows()] == [
        ("You don't know a password for this.", False), ("Close", True)]
    w.frame(H.key(pygame.K_BACKSPACE))                       # Back closes it
    assert g.panel == "screen"
    g = open_pc(w, tips=("lanterns",))
    enter(w, "login")
    g._open_commands()
    w.frame()
    assert g.list.rows()[0].label == "Password from: Paper Lanterns"
    w.frame(H.key(pygame.K_RETURN))
    assert g.field.text == "lantern" and g.session.mode == "password"


# --- AC-F56-16: history recall -----------------------------------------------------------------

def test_ac_f56_16_history(world):
    w = world
    g = open_pc(w)
    for line in ("dir", "help", "zzz"):
        enter(w, line)
    w.frame(H.key(pygame.K_UP))
    assert g.field.text == "zzz"                            # newest first
    w.frame(H.key(pygame.K_UP))
    w.frame(H.key(pygame.K_UP))
    w.frame(H.key(pygame.K_UP))
    assert g.field.text == "dir"
    w.frame(H.key(pygame.K_DOWN))
    w.frame(H.key(pygame.K_DOWN))
    assert g.field.text == "zzz"
    w.frame(H.key(pygame.K_DOWN))                           # past the newest: empty
    assert g.field.text == "" and focused(w) is g.field
    w.frame(H.key(pygame.K_DOWN))                           # then Commands
    assert focused(w) is g.commands_button
    w.frame(H.key(pygame.K_UP))
    assert focused(w) is g.field


# --- AC-F56-17: output: 500 lines, scrolling, More below ------------------------------------------

def test_ac_f56_17_output(world, monkeypatch):
    w = world
    g = open_pc(w)
    for n in range(260):
        g._add([(f"line {n}", "plain"), (f"more {n}", "plain")])
    w.frame()
    assert len(g.lines) == 500 and g.lines[-1][0] == "more 259"
    calls = []
    real = type(w.shell.painter).shape
    monkeypatch.setattr(type(w.shell.painter), "shape",
                        lambda self, box, spec, **k: (calls.append(box), real(self, box, spec,
                                                                              **k))[1])
    w.frame(H.wheel((640, 300), 1))
    assert g.scroll == 3
    w.frame(H.key(pygame.K_PAGEUP))
    assert g.scroll == 3 + g.visible - 1
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER))
    assert g.scroll == 3
    w.frame()
    assert any(abs(b.right - g.inner.right) < 1 and b.h == g.pitch for b in calls)   # tag
    w.frame(typed("x"))                                     # typing returns to the bottom
    assert g.scroll == 0


# --- AC-F56-18: Leave is exit ------------------------------------------------------------------

def test_ac_f56_18_leave(world):
    w = world
    g = open_pc(w, result="details")
    enter(w, "dir")
    g.ctx.scope.focus(g.leave_button, InputKind.KEYS)
    w.frame(H.key(pygame.K_RETURN))
    w.frame(H.key(pygame.K_LEFT), H.key(pygame.K_RETURN))   # Yes
    assert done(w).result == {"reached": False, "ended_by": None, "tried": ["dir"]}


# --- AC-F56-19: tokens per scheme, the dark screen ---------------------------------------------

def load_theme(tmp_path, preset):
    root = tmp_path / preset
    root.mkdir()
    (root / "config.toml").write_text(f'[theme]\npreset = "{preset}"\n', encoding="utf-8")
    return load_config(GamePaths.for_game(root)).config


@pytest.mark.parametrize("preset", ["sakura", "amber"])
def test_ac_f56_19_tokens(game, tmp_path, preset):
    config = load_theme(tmp_path, preset)
    w = HostU(game, config=config)
    cfg = config.theme
    g = open_pc(w)
    assert g.colors["fill"] == cfg.panel.fill_color and g.colors["text_color"] == \
        cfg.panel.text_color and g.colors["prompt_color"] == cfg.panel.heading.text_color
    assert g.colors["dim_color"] == cfg.button.disabled.text_color
    assert g.opacity == cfg.panel.fill_opacity
    g = open_pc(w, screen="dark")
    assert g.colors == {"text_color": (0xFF, 0xB0, 0x00), "prompt_color": (0xFF, 0xCC, 0x00),
                        "dim_color": (0xB0, 0x7A, 0x14), "fill": (0x14, 0x0C, 0x02),
                        "border": (0x9A, 0x68, 0x00)} and g.opacity == 1.0
    from engine.app.text_check import contrast_ratio
    fill = g.colors["fill"]
    assert contrast_ratio(g.colors["text_color"], fill) >= 10.5
    assert contrast_ratio(g.colors["prompt_color"], fill) >= 12.8
    assert contrast_ratio(g.colors["dim_color"], fill) >= 5.2


# --- AC-F56-20: layout at 100 % and 150 % ----------------------------------------------------------

@pytest.mark.parametrize(("scale", "visible"), [(1.0, 13), (1.5, 8)])
def test_ac_f56_20_layout(world, scale, visible):
    w = world
    w.ports.settings = lambda: PlayerSettings(text_scale=scale)
    g = open_pc(w)
    assert g.visible == visible and g.pitch == round(1.4 * round(24 * scale))
    assert g.prompt_y + g.pitch == 550 - 24
    assert (g.commands_button.box.x, g.commands_button.box.y) == (24, 566)
    assert (g.leave_button.box.right, g.leave_button.box.y) == (1256, 566)
    assert g.leave_button.box.bottom <= 720 and g.field.box.right == 1256 - 24
    g._open_commands()
    p = g.list_panel
    assert (p.x + p.w / 2, p.bottom, p.w) == (640, 550, 640) and p.y >= 0


# --- AC-F56-21: no motion besides the caret -----------------------------------------------------

def test_ac_f56_21_still(world):
    w = world
    w.ports.settings = lambda: PlayerSettings(reduce_motion=True)
    g = open_pc(w)
    first = w.frame().copy()
    for _ in range(40):
        w.frame()
    assert w.frame().get_view("2").raw == first.get_view("2").raw   # steady caret, no motion


# --- AC-F56-22: Backspace is never Back; right click and east are the game menu ----------------------

def test_ac_f56_22_back_keys(world):
    w = world
    g = open_pc(w)
    for _ in range(3):
        assert w.screen.handle_event(H.key(pygame.K_BACKSPACE)) is True
    assert focused(w) is g.field and w.shell.stack.top is w.screen
    assert w.screen.handle_event(H.down((640, 300), 3)) is False      # to the game menu
    assert w.screen.handle_event(H.pad(pygame.CONTROLLER_BUTTON_B)) is False


# --- AC-F56-24: saves and rollback ------------------------------------------------------------

def test_ac_f56_24_saves_and_rollback(world, tmp_path):
    w = world
    g = open_pc(w)
    enter(w, "dir")
    w.host.start(dataclasses.replace(w.session.cmd, restored=True))   # a load
    w.frame()
    assert shown(w.session.plugin) == ["LIBRARY TERMINAL"]           # a fresh terminal
    data = '{"commands": [{"command": "x", "ends": "goal", "unlock": "hana_diary"}]}'
    loaded = program(tmp_path / "g", data)
    interp = launched(loaded.program, sigs=sigs(str(tmp_path / "g")))
    interp.new_game(42)
    interp.run(10_000)
    step(interp)
    start_of(interp.take_commands(ALL))
    finish(interp, True, (CodexChange("unlock_tip", "hana_diary"),))
    interp.post(StepBack(1))
    interp.run(10_000)
    interp.take_commands(ALL)
    assert "hana_diary" in interp.codex.tips()


# --- AC-F56-25: sounds -----------------------------------------------------------------------

def test_ac_f56_25_sounds(world):
    w = world
    g = open_pc(w)
    g.ctx.theme._port._declared = {**g.ctx.theme._port._declared,
                                   "key_sound": "sfx/key.ogg", "error_sound": "sfx/err.ogg"}
    w.audio.calls.clear()
    w.frame(typed("a"), typed("b"))
    plays = [c[1] for c in w.audio.calls if c[0] == "play_ui"]
    assert plays == ["sfx/key.ogg", "sfx/key.ogg"]
    w.audio.calls.clear()
    for line in ("zz", "type diary.txt"):
        g.field.set_text("")
        enter(w, line)
    enter(w, "login")
    enter(w, "wrong")
    plays = [c[1] for c in w.audio.calls if c[0] == "play_ui"]
    assert plays.count("sfx/err.ogg") == 3


# --- AC-F56-26: W274, W273 once, dev only -----------------------------------------------------

def test_ac_f56_26_warnings_once(world, caplog):
    w = world
    module.WARNED.clear()
    caplog.set_level(logging.WARNING)
    secret = {"commands": [{"command": "\ue000\ue001", "help": False}]}
    for _ in range(2):
        open_pc(w, data=secret)
        w.frame()
    codes = [getattr(r, "code", None) for r in caplog.records]
    assert codes.count("W274") == 1 and codes.count("W273") == 1
    module.WARNED.clear()
    caplog.clear()
    w.shell.dev = False
    open_pc(w, data=secret)
    w.frame()
    assert not [r for r in caplog.records if getattr(r, "code", None) in ("W273", "W274")]


# --- AC-F56-33: the docs example loads --------------------------------------------------------

def test_ac_f56_33_docs_example(tmp_path):
    text = (REPO / "docs" / "minigames.md").read_text(encoding="utf-8")
    section = text.split("## Computer terminal", 1)[1].split("\n## ", 1)[0]
    example = re.search(r"```\n(lock tip.*?)```", section, re.S).group(1)
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "main.vns").write_text(example, encoding="utf-8")
    loaded = load_story(GamePaths(tmp_path.resolve()),
                        LoadOptions(dev=False, minigames=sigs(str(tmp_path))))
    assert loaded.program is not None and not loaded.errors, [e.format() for e in loaded.errors]
    commands = headless.run_headless(loaded.program, seed=1, minigames=sigs(str(tmp_path)),
                                     inputs=["advance"] * 5)
    assert not [c for c in commands if type(c) is StoryFailed]
    assert Terminal in BUNDLED and TOKENS["dark.text_color"] == "#FFB000"
    assert plain_theme() is not None
