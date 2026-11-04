"""F52 steps P7 and W5: ``ask_text`` on Host U and headless: AC-F52-28 (the answer), 14 (typed
text stays private), 31 (saves and rollback), 32 (``{var=…}`` shows braces), and the E272 /
E271 halves of AC-F52-29 and 30 through the runtime."""

import dataclasses
import functools
import logging
from pathlib import Path

import pygame
import pytest

from engine.core.paths import GamePaths
from engine.minigames.bundled import BUNDLED
from engine.minigames.bundled.ask_text import WORDS, AskText
from engine.minigames.loader import load_plugins
from engine.runtime import headless
from engine.runtime.commands import MinigameDone, StoryFailed
from engine.script import load_story
from engine.script.loader import LoadOptions
from engine.ui.input import UiEvent
from tests.fakes.ui_shell import UiHarness
from tests.minigames.host_u import HostU
from tests.runtime.minigame_story import said

H = UiHarness
REPO = Path(__file__).resolve().parents[3]
SECRET = "Hunter2Moon"


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


def ask(w: HostU, *, restored: bool = True, **args):
    """A new session (a cut when ``restored``), run until RUNNING."""
    from engine.minigames.host import Phase

    w.posted.clear()
    cmd = dataclasses.replace(w.command("ask_text", args), restored=restored)
    w.host.start(cmd)
    assert not w.fatal, [f.format() for f in w.fatal]
    w.frame()
    while w.session.phase is not Phase.RUNNING:
        w.frame()
    return w.session, w.session.plugin, cmd


def result(w: HostU):
    done = w.done()
    return done[-1].result if done else None


def run_out(w: HostU, frames: int = 60) -> None:
    for _ in range(frames):
        if w.done():
            return
        w.frame()


# --- AC-F52-28: the answer -------------------------------------------------------------------------

def test_ac_f52_28_answer(world):
    w = world
    assert AskText in BUNDLED
    s, g, _ = ask(w, prompt="What's your name?", max_length=12, allowed="name")
    assert s.scope.focused is g.field and s.hint_text == WORDS["hint"] and not s.heading_on
    assert g.lines == ["What's your name?"] and g.field.placeholder == "Type here"
    w.frame(H.key(pygame.K_RETURN))                            # empty: refused with a note
    assert not s.finished and g.field.plan(w.shell.painter, s.screen.look_for(g.field)) \
        .note == "Type something first."
    w.frame(typed("  Sayo! "))                                 # "!" isn't a name character
    assert g.field.text == "  Sayo " and g.field.note is not None
    w.frame(H.key(pygame.K_RETURN))
    run_out(w)
    assert result(w) == "Sayo"                                 # trimmed
    s, g, _ = ask(w, default="Ren")                            # default prefills
    assert g.field.text == "Ren" and g.field.model.caret == 3
    w.frame(H.key(pygame.K_DOWN), H.key(pygame.K_RETURN))      # OK by keys
    run_out(w)
    assert result(w) == "Ren"
    s, g, _ = ask(w, can_be_empty=True)
    w.frame(H.key(pygame.K_RETURN))
    run_out(w)
    assert result(w) == ""
    s, g, _ = ask(w, hide=True)
    w.frame(typed("pw"))
    assert g.field.plan(w.shell.painter, s.screen.look_for(g.field)).text == "••"


# --- AC-F52-14: typed text never reaches the log, notices, or messages ---------------------------

def test_ac_f52_14_typed_text_stays_private(world, caplog):
    w = world
    caplog.set_level(logging.DEBUG)
    s, g, _ = ask(w, max_length=40)
    w.frame(typed(SECRET))
    w.frame(H.key(pygame.K_LEFT), H.key(pygame.K_BACKSPACE), typed("n"))
    w.frame(H.key(pygame.K_v, pygame.KMOD_LCTRL))              # paste: nothing to paste here
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_A))                 # the keyboard
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_B))
    w.frame(H.key(pygame.K_RETURN))
    run_out(w)
    assert result(w) == "Hunter2Monn"
    texts = [r.getMessage() for r in caplog.records] + [t for _, t in w.shell.notices]
    texts += [repr(e) for e in w.posted if not isinstance(e, MinigameDone)]
    assert texts and not [t for t in texts if "Hunter" in t or "Moon" in t or "Mon" in t]
    # The only place the answer goes is the story's result (MinigameDone).
    assert [e.result for e in w.posted if isinstance(e, MinigameDone)] == ["Hunter2Monn"]


# --- AC-F52-31: a save while typing loads back with default; rollback asks again ----------------

def test_ac_f52_31_saves_and_rollback(world):
    w = world
    s, g, cmd = ask(w, default="Ren", restored=False)
    w.frame(typed("ji"))
    assert g.field.text == "Renji" and w.used()               # typing is a used input
    # A load restores the line's checkpoint: the same command, restored, starts it again.
    w.posted.clear()
    w.host.start(dataclasses.replace(cmd, restored=True))
    w.frame()
    assert w.session is not s and w.session.plugin.field.text == "Ren"   # the draft is gone
    # Rollback before the line: the session is abandoned (nothing posted); it asks again.
    w.host.on_landing()
    assert w.session is None and not w.done()
    s, g, _ = ask(w, default="Ren")
    assert g.field.text == "Ren" and not s.finished


# --- AC-F52-32 (and E272, E271): headless, through the runtime -----------------------------------

@functools.cache
def sigs(root: str):
    result = load_plugins(GamePaths(Path(root)), dev=False)
    assert result.ok and "ask_text" in result.signatures()
    return result.signatures()


def story(tmp_path: Path, line: str):
    (tmp_path / "script").mkdir(parents=True, exist_ok=True)
    (tmp_path / "script" / "main.vns").write_text(
        'default player_name = ""\n\nlabel start:\n    "Before."\n'
        f"    {line}\n"
        '    "{var=player_name}! That\'s a nice name."\n', encoding="utf-8")
    return load_story(GamePaths(tmp_path.resolve()), LoadOptions(dev=False,
                                                               minigames=sigs(str(tmp_path))))


def test_ac_f52_32_var_shows_braces(tmp_path):
    loaded = story(tmp_path, 'minigame ask_text default="{b}x" into player_name')
    assert loaded.program is not None, [e.format() for e in loaded.errors]
    commands = headless.run_headless(loaded.program, seed=1, minigames=sigs(str(tmp_path)),
                                     inputs=["advance", "advance", "advance"])
    assert said(commands) == ["Before.", "{b}x! That's a nice name."]
    # The E272 half of AC-F52-29: a refused argument stops the story at the line.
    bad = story(tmp_path / "bad", 'minigame ask_text allowed="letter" into player_name')
    commands = headless.run_headless(bad.program, seed=1, minigames=sigs(str(tmp_path / "bad")),
                                     inputs=["advance"])
    failed = commands[-1]
    assert type(failed) is StoryFailed and failed.error.code == "E272"
    assert failed.error.message.endswith(
        'allowed must be "any", "name", "letters", "digits" or "letters_digits", not '
        '"letter". Did you mean "letters"?')
    # The E271 half of AC-F52-30: ask_text can't be skippable.
    refused = story(tmp_path / "skip", "minigame ask_text skippable into player_name")
    assert [e.code for e in refused.errors] == ["E271"]
