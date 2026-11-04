"""F55 step 2: the coded note played on Host U and headless: AC-F55-04, 05, 06, 07, 08, 09, 13,
15; the runtime halves of AC-F55-01 (E272, check_story), 11 (headless, Skip Game) and 12
(W270 once, dev only)."""

import dataclasses
import functools
import logging
from pathlib import Path

import pygame
import pytest

from engine.core.minigame_types import CodexChange, Outcome, StoryNames
from engine.core.paths import GamePaths
from engine.minigames import api
from engine.minigames.bundled import BUNDLED, cipher_note as module
from engine.minigames.bundled.cipher_note import TOKENS, WORDS, CipherNote
from engine.minigames.loader import load_plugins
from engine.runtime import headless
from engine.runtime.commands import StepBack, StoryFailed
from engine.script import load_story
from engine.script.loader import LoadOptions
from engine.ui.input import UiEvent
from engine.ui.nav import InputKind
from engine.ui.widgets import Look
from tests.fakes.ui_shell import UiHarness
from tests.minigames.host_u import HostU
from tests.runtime.minigame_story import ALL, finish, launched, said, start_of, step

H = UiHarness
ABC_KEY = "BCDEFGHIJKLMNOPQRSTUVWXYZA"           # A→B, B→C, C→D, …
NAMES = StoryNames(("hana",), ("paper_lantern", "coin"), ("lanterns", "moon"),
                   tip_categories=(("codex_tips", ("lanterns", "moon")),))


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


def open_note(w: HostU, *, tips=(), **args) -> CipherNote:
    w.posted.clear()
    cmd = dataclasses.replace(w.command("cipher_note", args, tips=tips), names=NAMES)
    w.host.start(cmd)
    assert not w.fatal, [f.format() for f in w.fatal]
    w.frame()
    return w.session.plugin


def focused(w: HostU):
    return w.session.scope.focused


def texts(g: CipherNote) -> str:
    return "".join(c.text or "_" for c in g.cells)


def run_out(w: HostU, frames: int = 60):
    for _ in range(frames):
        if w.done():
            return w.done()[-1]
        w.frame()
    return None


# --- AC-F55-04: typing, turning, clearing -------------------------------------------------------

def test_ac_f55_04_guessing(world):
    w = world
    g = open_note(w, message="ABA C", key=ABC_KEY)       # signs B, C, B, D
    assert [g.cell_sign[id(c)] for c in g.cells] == ["B", "C", "B", "D"]
    assert focused(w) is g.cells[0]
    w.frame(typed("a"))                                  # every copy of the sign
    assert texts(g) == "A_A_" and focused(w) is g.cells[1]   # next sign with no letter
    w.frame(typed("a"))                                  # A moves to sign C
    assert texts(g) == "_A__" and focused(w) is g.cells[2]
    w.frame(typed("b"))
    assert texts(g) == "BAB_" and focused(w) is g.cells[3]
    w.frame(typed("c"))                                  # every sign set: focus stays
    assert texts(g) == "BABC" and focused(w) is g.cells[3]
    w.session.scope.focus(g.cells[1], InputKind.KEYS)
    w.frame(H.key(pygame.K_DOWN))                        # turning: A → B (taken off sign B)
    assert texts(g) == "_B_C" and focused(w) is g.cells[1]   # and focus doesn't move
    w.frame(H.key(pygame.K_BACKSPACE))                   # Backspace clears the sign
    assert texts(g) == "___C"
    w.frame(typed("z"), H.key(pygame.K_LEFT))            # wraps to the first empty sign
    assert texts(g) == "_Z_C"


# --- AC-F55-05: Left/Right reading order, the side column, lines, scrolling ----------------------

def test_ac_f55_05_moving(world):
    w = world
    message = "\n".join(["ABCD"] * 8)                    # 8 lines; 5 show at 100 %
    g = open_note(w, message=message, key=ABC_KEY)
    assert g.lines == 8 and g.lines_shown == 5 and g.top_line == 0
    w.frame(H.key(pygame.K_RIGHT))
    assert focused(w) is g.cells[1]
    w.frame(H.key(pygame.K_LEFT))
    assert focused(w) is g.cells[0]
    w.frame(H.key(pygame.K_LEFT))                         # before the first: stays
    assert focused(w) is g.cells[0]
    w.frame(H.key(pygame.K_PAGEDOWN))                     # the next line's first cell
    assert focused(w) is g.cells[4]
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER))   # RB: the same
    assert focused(w) is g.cells[8]
    for _ in range(4):
        w.frame(H.key(pygame.K_PAGEDOWN))
    assert focused(w) is g.cells[24] and g.top_line == 2  # scrolled into view
    w.frame(H.key(pygame.K_PAGEUP))
    assert focused(w) is g.cells[20]
    g._focus(g.cells[-1])
    w.frame(H.key(pygame.K_RIGHT))                        # past the last: the side column
    assert focused(w) is g.put_away
    w.frame(H.key(pygame.K_LEFT))                         # Left from there: the last cell
    assert focused(w) is g.cells[-1]
    w.frame(H.wheel((500, 300), 1))
    assert g.top_line == 2                                # the wheel scrolls the note


# --- AC-F55-06: solving, Done, Put away ---------------------------------------------------------

def test_ac_f55_06_solving_and_leaving(world):
    w = world
    g = open_note(w, message="AB", key=ABC_KEY, tip="moon")
    w.frame(typed("a"))
    w.frame(typed("b"))
    assert g.solved and w.session.hint_text == WORDS["solved"]
    assert focused(w) is g.done_button and not any(c.enabled() for c in g.cells)
    w.frame(H.key(pygame.K_RETURN))
    done = run_out(w)
    assert done.result is True and done.changes == (CodexChange("unlock_tip", "moon"),)
    g = open_note(w, message="AB", key=ABC_KEY, tip="moon")
    g._focus(g.put_away)
    w.frame(H.key(pygame.K_RETURN))                       # the confirm (No focused)
    assert w.shell.stack.top is not w.screen
    w.frame(H.key(pygame.K_LEFT), H.key(pygame.K_RETURN))  # Yes
    done = run_out(w)
    assert done.result is False and done.changes == ()


# --- AC-F55-07: the shift kind ---------------------------------------------------------------

def test_ac_f55_07_shift(world):
    w = world
    g = open_note(w, message="ABC", kind="shift", shift=3)      # written DEF
    assert [g.cell_sign[id(c)] for c in g.cells] == ["D", "E", "F"]
    assert not any(c.focusable for c in g.cells) and focused(w) is g.dial
    assert w.session.hint_text == WORDS["hint_shift"]
    w.frame(typed("c"))                                   # "A is written as C": shift 2
    assert texts(g) == "BCD" and not g.solved
    w.frame(H.key(pygame.K_DOWN))                         # turned to D: shift 3
    assert texts(g) == "ABC" and g.solved and focused(w) is g.done_button


# --- AC-F55-08: hints --------------------------------------------------------------------------

def test_ac_f55_08_hints(world):
    w = world
    g = open_note(w, message="AB", key=ABC_KEY, hints="codex_tips")
    assert g.hints_button.label() == WORDS["no_hints"] and not g.hints_button.enabled()
    g = open_note(w, message="AB", key=ABC_KEY, hints="codex_tips", tips=("lanterns",))
    assert g.hints_button.label() == WORDS["hints"] and g.hints_button.enabled()
    g._focus(g.hints_button)
    w.frame(H.key(pygame.K_RETURN))
    assert g.mode == "hints"
    names = [r.entry.name for r in g.view.rows()]
    assert names == ["lanterns"]                          # only that category's held tips
    w.frame(H.key(pygame.K_BACKSPACE))                    # Back closes it
    assert g.mode == "note" and focused(w) is g.hints_button
    g = open_note(w, message="AB", key=ABC_KEY)
    assert g.hints_button not in w.session.scope.widgets()   # no hints: no button


# --- AC-F55-09: revealed letters ------------------------------------------------------------------

def test_ac_f55_09_revealed(world):
    w = world
    g = open_note(w, message="ABA", key=ABC_KEY, revealed="a")
    first = g.cells[0]
    assert first.text == "A" and not first.enabled() and not first.focusable
    p = w.shell.painter
    plan = first.plan(p, Look("disabled"))
    assert plan.bold and plan.underline is None           # bold, no underline
    assert focused(w) is g.cells[1]                       # skipped by focus
    w.frame(typed("a"))                                   # A on another sign: revealed stays
    assert g.cells[0].text == "A" and g.board.guess("B") == "A"
    w.frame(H.key(pygame.K_BACKSPACE))
    assert g.cells[0].text == "A"                         # never cleared
    g = open_note(w, message="AB", key=ABC_KEY, revealed="AB")
    assert g.solved and focused(w) is g.done_button       # all revealed: solved at once


# --- AC-F55-13: the same-sign bar, words, tokens ---------------------------------------------

def test_ac_f55_13_bar_words_tokens(world, monkeypatch):
    w = world
    entry = api.declarations(CipherNote, "engine")
    assert entry.words == WORDS and entry.tokens == TOKENS and entry.api == "1.4"
    assert CipherNote in BUNDLED
    g = open_note(w, message="ABA", key=ABC_KEY)
    bars = []
    real = type(w.shell.painter).rect
    monkeypatch.setattr(type(w.shell.painter), "rect",
                        lambda self, box, color: (bars.append((box, color)), real(self, box,
                                                                                  color))[1])
    w.frame()
    under = [b for b, c in bars if c == g.colors["guess.text_color"] and b.h == 4]
    assert sorted(b.x for b in under) == sorted([g.cells[0].box.x, g.cells[2].box.x])
    assert g.colors["guess.text_color"] == w.shell.theme.cfg.panel.heading.text_color
    assert g.colors["code.text_color"] == w.shell.theme.cfg.panel.text_color
    # Nothing by color alone: the bar is a shape, a revealed letter is bold, a sign is text.


# --- AC-F55-15: saves and rollback ---------------------------------------------------------------

STORY = '''lock tip hana_code "Hana's notebook" in "Hana's code":
    "She always swapped letters, never shifted them."
lock tip hana_letter "Hana's last letter"
default letter_read = False

label start:
    "Before."
    minigame cipher_note {args} into letter_read
    "After."
'''
GOOD = 'message="MEET ME" hints="Hana\'s code" tip="hana_letter"'


@functools.cache
def sigs(root: str):
    result = load_plugins(GamePaths(Path(root)), dev=False)
    assert result.ok and "cipher_note" in result.signatures()
    return result.signatures()


def program(root: Path, args: str = GOOD):
    (root / "script").mkdir(parents=True, exist_ok=True)
    (root / "script" / "main.vns").write_text(STORY.format(args=args), encoding="utf-8")
    return load_story(GamePaths(root.resolve()), LoadOptions(dev=False, minigames=sigs(str(root))))


def test_ac_f55_15_saves_and_rollback(world, tmp_path):
    w = world
    g = open_note(w, message="AB", key=ABC_KEY)
    w.frame(typed("a"))
    cmd = dataclasses.replace(w.session.cmd, restored=True)
    w.host.start(cmd)                                     # a load: the same line again
    w.frame()
    assert texts(w.session.plugin) == "__" and not w.session.plugin.solved
    loaded = program(tmp_path / "g")
    interp = launched(loaded.program, sigs=sigs(str(tmp_path / "g")))
    interp.new_game(42)
    interp.run(10_000)
    step(interp)                                          # past "Before."
    start_of(interp.take_commands(ALL))
    finish(interp, True, (CodexChange("unlock_tip", "hana_letter"),))
    assert "hana_letter" in interp.codex.tips()
    interp.post(StepBack(1))
    interp.run(10_000)
    interp.take_commands(ALL)
    assert "hana_letter" in interp.codex.tips()           # rollback after Done keeps it


# --- AC-F55-01/11/12, the runtime halves -----------------------------------------------------

def test_ac_f55_01_11_12_runtime(world, tmp_path, caplog):
    ok = program(tmp_path / "ok")
    assert ok.program is not None, [e.format() for e in ok.errors]
    commands = headless.run_headless(ok.program, seed=1, minigames=sigs(str(tmp_path / "ok")),
                                     inputs=["advance", "advance"])
    assert said(commands) == ["Before.", "After."]          # the test outcome: True
    assert CipherNote().outcome_for("skipped", {"message": "x", "tip": "t"}, NAMES) == \
        Outcome(True, (api.unlock_tip("t"),))
    for args, text in (('message="MEET ME" kind="shfit"',
                        'kind must be "letters", "shift" or "symbols", not "shfit". Did you '
                        'mean "shift"?'),
                       ('message="MEET ME" hints="Hanas code"',
                        'hints names the tip category "Hanas code", but no tip is in it. Did '
                        'you mean "Hana\'s code"?')):
        bad = program(tmp_path / str(len(text)), args)
        commands = headless.run_headless(bad.program, seed=1,
                                         minigames=sigs(str(tmp_path / str(len(text)))),
                                         inputs=["advance"])
        failed = commands[-1]
        assert type(failed) is StoryFailed and failed.error.code == "E272"
        assert failed.error.message.endswith(text)
    # W270: once per note, dev only.
    w = world
    module.WARNED.clear()
    caplog.set_level(logging.WARNING)
    for _ in range(2):
        open_note(w, message="AB", kind="symbols",                  # private-use signs
                  symbols="".join(chr(0xE000 + i) for i in range(26)))
        w.frame()
    found = [r for r in caplog.records if getattr(r, "code", None) == "W270"]
    assert len(found) == 1 and found[0].getMessage().startswith(
        "cipher_note: the game's fonts can't draw 2 characters of this note")
    module.WARNED.clear()
    w.ports.shell.dev = False
    caplog.clear()
    open_note(w, message="AB", kind="symbols",
              symbols="".join(chr(0xE000 + i) for i in range(26)))
    w.frame()
    assert not [r for r in caplog.records if getattr(r, "code", None) == "W270"]
