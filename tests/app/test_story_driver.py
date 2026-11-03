"""F03 step 6 — the story in the window: ``RuntimeStoryDriver``, ``install_story``, the
launch phase in ``app/loading.py``, and ``build_initial_screens`` (``04-technical.md``
§5.3, §7.3, §7.6). AC-F03-02, 07, 31, 43, 70, 71, and F44 C1's step 6 part (``--start`` and
``--set`` reach the new game). F03 step 13: ``run --seed`` (AC-F03-44), the new-game line in
the window (AC-F03-74), and AC-F44-02's ``--seed`` row.

Driver rows run on a fake clock with no window. App rows (marker ``display``) launch
in-process (``scripted_app``, fake frame clock; the launch phase keeps its real clock),
except AC-F03-31 (b)'s frame timing, which needs the real frame limiter.
"""

import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap, cli, story
from engine.app.app import App
from engine.app.dispatch import CommandRouter
from engine.app.loading import StoryLoadScreen, story_load_screen
from engine.app.story import INBOX_MAX, RuntimeStoryDriver, install_story
from engine.core.config_schema import Config
from engine.core.constants import MB
from engine.core.paths import GamePaths
from engine.core.startvalues import StartOptions
from engine.core.timing import BenchRecorder, GameTime
from engine.render.assets import AssetManager
from engine.runtime import interpreter as interpreter_module
from engine.runtime.commands import (Advance, AudioRestore, Command, Flash, Glitch,
                                     PrefetchImages, Say,
                                     Shake, ShowMenu, ShowStage, StoryEnded, StoryFailed,
                                     StoryWait, ChapterStarted, NvlPage, CodexAdded,
                                     StartMinigame, WindowTitle, FakeCrash,
                                     UiStyle, UiBlocks, DeleteSaves, MetaWrite, MetaDelete)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, RestoreResult, Status, story_variables
from engine.runtime.launch import LaunchJob, run_launch
from engine.script import nodes
from engine.ui.builtin.placeholder import PlaceholderScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from tests.app.test_story_load_screen import copy_example, launch, make_game, records
from tests.fakes.fake_window import FakeWindow
from tests.fakes.loop import post_key, post_quit
from tests.runtime.story import load_files, load_r
from tests.script.helpers import template_a, template_r

REPO = Path(__file__).resolve().parents[2]
SEED_42_DICE = "977afd8015414a94"


class TickClock:
    """A fake clock that moves ``step`` seconds every time it is read."""

    def __init__(self, step: float = 2e-6) -> None:
        self.now = 0.0
        self.step = step
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        self.now += self.step
        return self.now


def make_driver(program, **kwargs) -> RuntimeStoryDriver:
    launched = run_launch(program)
    assert launched.namespace is not None, [e.format() for e in launched.errors]
    kwargs.setdefault("clock", TickClock())
    return RuntimeStoryDriver(Interpreter(program, launched.namespace), **kwargs)


def play_to_end(driver: RuntimeStoryDriver, *, max_frames: int = 1000) -> list[Command]:
    """Pump frame after frame, answering every line with ``Advance``; the commands in
    order."""
    out: list[Command] = []
    for _ in range(max_frames):
        cmds = driver.pump()
        out.extend(cmds)
        for cmd in cmds:
            if type(cmd) is Say:
                driver.post(Advance(cmd.sid))
        if driver.status in (Status.ENDED, Status.FAILED) and not cmds:
            return out
    raise AssertionError("the story did not end")


def first_line_state(driver: RuntimeStoryDriver):
    driver.new_game()
    cmds = driver.pump()
    assert [type(c) for c in cmds] == [AudioRestore, ShowStage, Say]   # F08, F04, the line
    return driver.checkpoint()


# --- AC-F03-02 — a second new game leaves nothing behind ------------------------------------

GOLDEN_R_SEED_42 = 798552        # dice.roll(1, 1000000) as the first draw after seed 42
GOLDEN_R_SEED_7 = 310905
AC02_S = ('$ extra = 1⏎[4]$ trust = 5⏎[4]$ r = dice.roll(1, 1000000)⏎'
          '[4]$ fortunes.append("lost")')


def test_ac_f03_02_three_new_games(tmp_path):
    seeds = iter([42, 42, 7])
    driver = make_driver(load_r(tmp_path, S=AC02_S), seed_source=lambda: next(seeds))
    interp = driver.interp
    rolls = []
    for _ in range(3):
        driver.new_game()
        first = driver.pump()
        assert [type(c) for c in first] == [AudioRestore, ShowStage, Say]   # F08, F04 first
        assert first[2].text == "Start."
        state = driver.checkpoint()
        assert dict(state.variables) == {"trust": 0, "hana_name": "???"}
        assert "extra" not in interp.G and "r" not in interp.G
        assert state.call_stack == () and interp.call_stack == []
        driver.post(Advance(first[2].sid))
        rest = play_to_end(driver)
        assert [type(c) for c in rest] == [Say, StoryEnded]
        rolls.append(interp.G["r"])
    assert rolls[0] == rolls[1] != rolls[2]
    assert rolls == [GOLDEN_R_SEED_42, GOLDEN_R_SEED_42, GOLDEN_R_SEED_7]
    # Define values are not re-evaluated (documented behaviour).
    assert interp.G["fortunes"].count("lost") == 3


# --- AC-F03-07 — nothing runs until the player advances -------------------------------------

def test_ac_f03_07_nothing_runs_without_advance(tmp_path):
    program = load_r(tmp_path, S="$ ran = True")
    driver = make_driver(program)
    driver.new_game()
    returned = []
    for _ in range(100):
        returned.extend(driver.pump())
    assert [type(c) for c in returned] == [AudioRestore, ShowStage, Say]   # F08, F04 first
    assert returned[2].text == "Start."
    assert driver.status is Status.WAITING
    assert "ran" not in driver.checkpoint().variables
    line_7 = returned[2].sid
    driver.post(Advance(line_7))
    driver.post(Advance(line_7))
    frame = driver.pump()
    assert [(type(c), c.text) for c in frame] == [(Say, "End.")]
    assert driver.checkpoint().variables["ran"] is True


def test_ac_f03_07_advance_for_another_line_is_ignored(tmp_path):
    program = load_r(tmp_path, S="$ ran = True")
    driver = make_driver(program)
    driver.new_game()
    _, _, line = driver.pump()                    # F08 AudioRestore, F04 ShowStage, the line
    interp = driver.interp
    before = _fingerprint(interp)
    driver.post(Advance(program.at("start", (3,)).sid))            # line 10
    assert driver.pump() == []
    assert _fingerprint(interp) == before
    assert line.sid == interp.current.sid


def _fingerprint(interp: Interpreter) -> tuple:
    variables = story_variables(interp.G, interp.reserved)
    return (id(interp.G), frozenset(interp.G), tuple((k, repr(v), id(v))
                                                     for k, v in variables.items()),
            interp.current.sid, [c.sid for c in interp.call_stack], interp.core.state,
            interp.core.ready, interp.status, interp.steps, list(interp.entered),
            list(interp._held), interp.released, interp.last_checkpoint)


# --- AC-F03-43 — each new game gets its own seed --------------------------------------------

def test_ac_f03_43_fifty_new_games_fifty_seeds(tmp_path, monkeypatch):
    calls = []
    real = story.secrets.randbits

    def randbits(k):
        calls.append(k)
        return real(k)

    monkeypatch.setattr(story.secrets, "randbits", randbits)
    driver = make_driver(load_r(tmp_path))
    values = [first_line_state(driver).to_json()["dice"] for _ in range(50)]
    assert len(set(values)) == 50
    assert calls == [64] * 50


def test_ac_f03_43_fixed_seed(tmp_path):
    called = []
    driver = make_driver(load_r(tmp_path), fixed_seed=42,
                         seed_source=lambda: called.append(1) or 1)
    values = {first_line_state(driver).to_json()["dice"] for _ in range(50)}
    assert values == {SEED_42_DICE}
    assert called == []


SEED_IN_A_PROCESS = r"""
import sys
from pathlib import Path
from engine.app.story import RuntimeStoryDriver
from engine.core.paths import GamePaths
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.script import load_story

program = load_story(GamePaths(Path(sys.argv[1]))).program
driver = RuntimeStoryDriver(Interpreter(program, run_launch(program).namespace))
driver.new_game()
driver.pump()
print(driver.checkpoint().to_json()["dice"])
"""


def test_ac_f03_43_two_processes_differ(tmp_path):
    driver = make_driver(load_r(tmp_path))
    here = first_line_state(driver).to_json()["dice"]
    out = subprocess.run([sys.executable, "-c", SEED_IN_A_PROCESS, str(tmp_path.resolve())],
                         cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    there = out.stdout.strip().splitlines()[-1]            # after pygame's banner
    assert len(there) == 16 and there != here


# --- AC-F03-71 — driver inbox, command cap, and frame order ---------------------------------

def test_ac_f03_71_a_thousand_statements_in_the_advance_frame(tmp_path):
    program = load_r(tmp_path, S="$ a += 1⏎[4]" * 999 + "$ a += 1", T="default a = 0")
    clock = TickClock(2e-6)
    driver = make_driver(program, clock=clock)
    driver.new_game()
    _, _, start = driver.pump()                   # F08 AudioRestore, F04 ShowStage, the line
    driver.post(Advance(start.sid))                   # frame N's event phase
    frame_n = driver.pump()
    assert [(type(c), c.text) for c in frame_n] == [(Say, "End.")]
    assert driver.checkpoint().variables["a"] == 1000


@pytest.mark.display
def test_ac_f03_71_frame_order_in_the_app(tmp_path, user_roots, scripted_app):
    """In the App: the line that follows an Advance posted in frame N's event phase is on
    the textbox when frame N draws (F05: at ``cps = 0`` "Start." is complete when the Space
    comes, so the Space advances)."""
    body = "    $ a += 1\n" * 1000
    game = make_game(tmp_path, {"main.vns": 'default a = 0\nlabel start:\n    "Start."\n'
                                            + body + '    "End."\n'})
    with (game / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[textbox]\ncps = 0\n")
    drawn = []
    real_draw = TextboxScreen.draw

    def draw(self, canvas):
        drawn.append((scripted_app.limiters[-1].frame, self.line.text if self.line else None))
        real_draw(self, canvas)

    real_install = story.install_story

    def install(app, interp, **kwargs):
        driver = real_install(app, interp, **kwargs)
        driver._clock = TickClock(2e-6)               # the AC's fake clock
        return driver

    scripted_app.at(10, lambda app: post_key(pygame.K_SPACE))
    scripted_app.quit_frame = 12
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(TextboxScreen, "draw", draw)
        mp.setattr("engine.app.loading.install_story", install)
        assert launch(game) == 0
    by_frame = dict(drawn)
    assert by_frame[9] == "Start." and by_frame[10] == "End."


def test_ac_f03_71_inbox_keeps_64(tmp_path, caplog):
    driver = make_driver(load_r(tmp_path))
    driver.new_game()
    driver.pump()
    with caplog.at_level(logging.DEBUG, logger="vn.runtime"):
        for _ in range(70):
            driver.post(Advance("nope"))
    assert len(driver._inbox) == INBOX_MAX == 64
    dropped = [r for r in caplog.records if r.levelno == logging.DEBUG
               and r.name == "vn.runtime" and "dropped" in r.getMessage()]
    assert len(dropped) == 6
    assert driver.pump() == [] and len(driver._inbox) == 0


@pytest.mark.parametrize("check_only, kept", [(True, 1), (False, 0)])
def test_restore_check_only_leaves_the_inbox(tmp_path, check_only, kept):
    """F11 C10: a ``check_only`` restore changes nothing, the queued events included; a real
    OK restore drops them."""
    driver = make_driver(load_r(tmp_path))
    driver.new_game()
    driver.pump()
    state = driver.checkpoint()
    assert state is not None
    driver.post(Advance("queued"))
    outcome = driver.restore(state, check_only=check_only)
    assert outcome.result is RestoreResult.OK
    assert len(driver._inbox) == kept


@dataclass(frozen=True, slots=True)
class Marker(Command):
    n: int


def test_ac_f03_71_a_burst_over_the_cap_spills_in_order(tmp_path, monkeypatch):
    def say_after_markers(interp, stmt):
        for n in range(299):
            interp._hold(Marker(n))
        interp.take_checkpoint(stmt, interpreter_module.say_command(interp, stmt))
        return interpreter_module.Step.WAIT

    monkeypatch.setitem(interpreter_module.EXECUTORS, nodes.Say, say_after_markers)
    driver = make_driver(load_r(tmp_path))
    driver.new_game()
    first = driver.pump()
    second = driver.pump()
    # The new game's AudioRestore (F08), the held commands, then F04's ShowStage and the line
    # (architecture.md "Bursts").
    assert (len(first), len(second)) == (256, 46)
    assert type(first[0]) is AudioRestore
    assert [c.n for c in first[1:] + second[:-2]] == list(range(299))
    assert type(second[-2]) is ShowStage
    assert type(second[-1]) is Say and second[-1].text == "Start."
    assert driver.pump() == []


def test_a_real_ctrl_c_in_the_pump_is_not_swallowed(tmp_path, monkeypatch):
    driver = make_driver(load_r(tmp_path, S="$ boom()",
                                T="define boom = lambda: (_ for _ in ()).throw(KeyboardInterrupt)"))
    driver.new_game()
    _, _, line = driver.pump()                    # F08 AudioRestore, F04 ShowStage, the line
    driver.post(Advance(line.sid))
    with pytest.raises(KeyboardInterrupt):
        driver.pump()


# --- install_story -----------------------------------------------------------------------

class _FakeApp:
    """What ``install_story`` (and F10's ``install_ui``) use of the ``App``."""

    def __init__(self) -> None:
        from engine.ui.screen import ScreenStack
        from tests.render.conftest import make_assets

        self.router = CommandRouter()
        self.story = None
        self.shell = None
        self.errors: list[BaseException] = []
        self.quits = 0
        self.config = Config()
        self.assets = make_assets(None)
        self.dev = True
        self.start = None
        self.screens = ScreenStack()

    def show_fatal_error(self, error):
        self.errors.append(error)

    def request_quit(self):
        self.quits += 1

    def add_quit_guard(self, guard) -> None:     # F10 step 7: the shell's quit guard
        pass


@pytest.mark.display
def test_install_story_registers_one_handler_per_command(tmp_path):
    from engine.ui.builtin.black_fade import BlackFadeScreen
    from engine.ui.shell import GameShell, Mode

    pygame.init()
    try:
        app = _FakeApp()
        program = load_r(tmp_path)
        driver = install_story(app, Interpreter(program, run_launch(program).namespace),
                               fixed_seed=42)
        assert app.story is driver and driver.fixed_seed == 42
        assert isinstance(app.shell, GameShell)                  # F10 C9: install_ui
        for command in (Say, StoryEnded, StoryFailed):
            with pytest.raises(ValueError):
                app.router.register(command, lambda cmd: None)
        assert set(app.router._handlers) == {Say, StoryEnded, StoryFailed, ShowStage,
                                             PrefetchImages,          # F04, F05
                                             ShowMenu,                # F07 step 2
                                             StoryWait, Shake, Flash,  # F09 step 2
                                             ChapterStarted,          # F18 step 3
                                             NvlPage,                 # F17 step 2
                                             CodexAdded,              # F21 step 2
                                             StartMinigame,           # F23 s4
                                             Glitch,                  # F28 s3
                                             WindowTitle, FakeCrash,  # F30 s3, s4
                                             UiStyle, UiBlocks, DeleteSaves,  # F32 s4
                                             *story.AUDIO_COMMANDS}   # F08 step 3
        textbox = app.textbox                                    # F05: install_textbox
        assert isinstance(textbox, TextboxScreen) and app.router._handlers[Say] == textbox.show
        assert app.router._handlers[NvlPage] == textbox.show_nvl     # F17: no stand-in
        app.screens.push(textbox)
        app.shell.mode = Mode.GAME
        driver.new_game()
        for cmd in driver.pump():
            app.router.dispatch(cmd)
        assert textbox.line.text == "Start."
        app.router.dispatch(StoryEnded())                        # F10: the shell's story end
        assert [type(s) for s in app.screens] == [TextboxScreen, BlackFadeScreen]
        assert app.shell.mode is Mode.ENDING
        error = RuntimeError("x")
        app.router.dispatch(StoryFailed(error))
        assert app.errors == [error]
    finally:
        pygame.quit()


def test_story_ended_without_a_shell_shows_the_placeholder():
    app = _FakeApp()
    story._story_ended(app, StoryEnded())
    assert [type(s) for s in app.screens] == [PlaceholderScreen]


def test_story_ended_flushes_persistent_data_first():
    """F12 I-1: with ``App.persist`` set, ``flush_soon()`` runs before the shell's story
    end; without it (before F12) nothing is asked."""
    calls = []

    class Persist:
        def flush_soon(self):
            calls.append("flush")

    class Shell:
        def story_ended(self, cmd):
            calls.append("shell")

    app = _FakeApp()
    app.shell = Shell()
    story._story_ended(app, StoryEnded())
    assert calls == ["shell"]
    app.persist = Persist()
    story._story_ended(app, StoryEnded())
    assert calls == ["shell", "flush", "shell"]


# --- AC-F03-70 — launch, end, and failure in the app ----------------------------------------

def _press_until_the_end(app) -> None:
    """Space, unless the story has ended: on F10's title the first Space focuses New Game
    and the next starts it; in the game it advances. After the end the title stays. F25-4:
    a minigame gets Shift+F8 instead, the dev test outcome, which is what the headless run
    plays: at the bridge's cross-examination Space would press Hana again and again (Press
    has the focus), and the poem's pages depend on its run's seed, which the cross-examination
    before it moved, so Space no longer picks the headless run's words."""
    from engine.minigames.screen import MinigameScreen

    if isinstance(app.screens.top, MinigameScreen):
        post_key(pygame.K_F8, pygame.KMOD_SHIFT)
    elif app.story is None or app.story.status is not Status.ENDED:
        post_key(pygame.K_SPACE)


# Frames _play_example runs: Space every third frame reads the lines and menus, finishes
# the F09 transitions and pauses and the F18 cards it lands on, and the end fades to the
# title; the minigames end with Shift+F8 (F25-4; ``_press_until_the_end``). F26-4's walk
# home (a dissolve, two lines, and the phone chat's fades) needs more frames; so do F31 s5's
# six bonus lines, and F30 s6's two more and its fake crash (0.5 s before a press counts).
EXAMPLE_FRAMES = 840


def _play_example(session, game: Path, *, start: StartOptions | None = None,
                  argv: list[str] | None = None):
    """Launch ``game``, press Space every third frame from frame 6 until the story ends
    (on the title too: New Game), and record what the textbox shows; returns (exit code,
    lines, first seen)."""
    shown, first = [], {}
    real_show = TextboxScreen.show

    def show(self, cmd):
        shown.append((cmd.name, cmd.text))
        real_show(self, cmd)

    def look(app):
        top = app.screens.top
        if "screen" not in first and isinstance(top, TextboxScreen) and top.line:
            first.update(screen=type(top), line=top.line.text, loading=app.loading,
                         frame=session.limiters[-1].frame)

    for frame in range(2, EXAMPLE_FRAMES):
        session.at(frame, look)
        if frame >= 6 and frame % 3 == 0:
            session.at(frame, _press_until_the_end)
    session.quit_frame = EXAMPLE_FRAMES
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(TextboxScreen, "show", show)
        if argv is not None:
            code = cli.main(argv)
        else:
            code = bootstrap.launch(game, release=False, bench_seconds=None,
                                    log_level_override=None, pygame_warning=None, start=start)
    return code, shown, first


@pytest.mark.display
def test_ac_f03_70_the_example_game_plays_to_the_end(tmp_path, user_roots, scripted_app):
    """As amended by F10 (G13): launch shows the title, New Game plays the story in the
    textbox, and the end shows F10's title (AC-F10-40), not F01's placeholder."""
    from engine.ui.builtin.title_screen import TitleScreen
    from engine.ui.shell import Mode

    game = copy_example(tmp_path / "game")
    # F03 step 14: the example rolls dice, so the window and the headless run share a seed.
    code, shown, first = _play_example(scripted_app, game,
                                       argv=["run", str(game), "--seed", "1"])
    assert code == 0
    app = scripted_app.apps[-1]
    assert first["screen"] is TextboxScreen and first["loading"] is False
    assert first["line"] == "The festival comes once a year, on the night the river runs slowest."
    from tests.runtime.stage_story import example_minigames, load_game
    program = load_game(game)                   # with config.toml's [stage.positions]
    # F07 step 5: Space at a menu focuses its first choice, and the next Space picks it.
    from tests.runtime.corpus import play
    inputs = play(program, 1).inputs
    expected = [(c.name, c.text) for c in run_headless(program, seed=1, inputs=inputs,
                                                       minigames=example_minigames())
                if type(c) is Say]
    # F07 step 5: 33 lines, 5 menus; F08 step 12 adds the firework's line; F17 step 5
    # the prologue's 7 full-screen lines; F19 step 6 the night's last menu and the sad
    # ending's 3 lines; F24-4 the wish line before the poem and its reaction after it;
    # F25-4 Hana's map line and, on the bridge, one line before the cross-examination and
    # the four of its won branch; F26-4 the walk home's line before Hana's phone chat and
    # the thought after it; F27-4 the stall keeper's line before the shed's puzzle room;
    # F23 s6 the stall keeper's line before the lantern game and her reaction after it;
    # F31 s5 the bonus scene's six lines; F30 s6 its name line and the one after its
    # fake crash.
    assert shown == expected and len(shown) == 66
    assert [type(s) for s in app.screens] == [TitleScreen]
    assert app.shell.mode is Mode.TITLE
    assert app.story.status is Status.ENDED
    assert set(app.router._handlers) == {Say, StoryEnded, StoryFailed, ShowStage,
                                         PrefetchImages, ShowMenu,                # F07
                                         StoryWait, Shake, Flash,                 # F09
                                         ChapterStarted,                          # F18
                                         NvlPage,                                 # F17
                                         CodexAdded,                              # F21
                                         StartMinigame,                           # F23
                                         Glitch,                                  # F28 s3
                                         WindowTitle, FakeCrash,                  # F30 s3, s4
                                         UiStyle, UiBlocks, DeleteSaves,          # F32 s4
                                         MetaWrite, MetaDelete,                   # F31 s4
                                         *story.AUDIO_COMMANDS}                   # F08
    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert problems == []


@pytest.mark.display
def test_ac_f03_70_no_story_creates_no_interpreter(tmp_path, user_roots, scripted_app,
                                                   monkeypatch):
    created = []
    real_init = Interpreter.__init__
    monkeypatch.setattr(Interpreter, "__init__",
                        lambda self, *a, **k: created.append(1) or real_init(self, *a, **k))
    game = make_game(tmp_path, None)
    assert launch(game) == 0
    app = scripted_app.apps[-1]
    assert [type(s) for s in app.screens] == [PlaceholderScreen]
    assert app.story is None and created == []


@pytest.mark.display
def test_ac_f03_70_loading_ends_after_the_launch_phase(tmp_path, user_roots, scripted_app,
                                                       monkeypatch):
    seen = []
    real_install = story.install_story

    def install(app, interp, **kwargs):
        seen.append(("install", app.loading))
        return real_install(app, interp, **kwargs)

    real_step = LaunchJob.step

    def step(self):
        seen.append(("step", scripted_app.apps[-1].loading))
        return real_step(self)

    monkeypatch.setattr("engine.app.loading.install_story", install)
    monkeypatch.setattr(LaunchJob, "step", step)
    game = make_game(tmp_path, {"main.vns": template_r()})
    scripted_app.quit_frame = 6
    assert launch(game) == 0
    assert seen and all(loading for _, loading in seen)
    assert seen[-1] == ("install", True)
    assert scripted_app.apps[-1].loading is False


@pytest.mark.display
def test_ac_f03_70_a_run_time_failure_shows_the_error_screen(tmp_path, user_roots,
                                                              scripted_app):
    from engine.ui.builtin.error import ErrorScreen

    game = instant(make_game(tmp_path, {"main.vns": template_r(S="$ x = 1 / 0")}))
    scripted_app.at(5, lambda app: post_key(pygame.K_SPACE))
    scripted_app.quit_frame = 8
    assert launch(game) == 1
    app = scripted_app.apps[-1]
    assert isinstance(app.screens.top, ErrorScreen) and len(app.screens) == 1
    assert app.story is None


@pytest.mark.display
def test_launch_errors_show_one_error_group(tmp_path, user_roots, scripted_app):
    from engine.ui.builtin.error import ErrorScreen

    game = make_game(tmp_path, {"main.vns": template_r(
        T="⏎".join(f"define d{k} = 1 / 0" for k in range(60)))})
    scripted_app.quit_frame = 6
    assert launch(game) == 1
    app = scripted_app.apps[-1]
    assert isinstance(app.screens.top, ErrorScreen)
    assert app.screens.top.message.startswith("The script has 60 problems:")
    assert app.story is None and app.loading is False
    errors = [r for r in records(game / "logs" / "latest.log")
              if r[0] == "ERROR" and r[1] == "runtime"]
    assert errors[0][2].startswith("script/main.vns, line 11: define d0 couldn't be set")
    assert errors[-1][2].startswith("…and 10 more problems")
    # AC-F03-29 (step 8): the error group's text ends with F02's E100 line (the screen then
    # applies F01's 4,000-character cut, F02 §7.10.2); each error shows its source line.
    message = app._fatal_message
    assert message.split("\n\n")[-1] == "…and 10 more problems. Fix these and launch again."
    assert "\n    define d0 = 1 / 0\n" in message
    assert message.startswith(app.screens.top.message.rstrip("…"))
    assert errors[1][2] == "    define d0 = 1 / 0"


@pytest.mark.display
def test_ac_f03_29_a_load_error_comes_first_and_no_define_runs(tmp_path, user_roots,
                                                               scripted_app, monkeypatch):
    from engine.ui.builtin.error import ErrorScreen

    jobs = []
    real_init = LaunchJob.__init__
    monkeypatch.setattr(LaunchJob, "__init__",
                        lambda self, *a, **k: jobs.append(1) or real_init(self, *a, **k))
    game = make_game(tmp_path, {"main.vns": template_r(S="jmup start",
                                                       T="define e = 1 / 0")})
    scripted_app.quit_frame = 6
    assert launch(game) == 1
    top = scripted_app.apps[-1].screens.top
    assert isinstance(top, ErrorScreen) and jobs == []
    assert top.message.startswith("The script has 1 problem:")
    assert 'line 8: "jmup" is not a statement' in top.message and "define e" not in top.message


@pytest.mark.display
def test_ac_f03_38_the_app_answers_game_has(tmp_path, user_roots, scripted_app):
    """E89c's game-folder form in the app: ``module()`` asks the game folder through the
    ``game_has`` that ``StoryLoadScreen`` passes to the launch job."""
    from engine.ui.builtin.error import ErrorScreen

    game = make_game(tmp_path, {"main.vns": template_r(T='define helpers = module("helpers")')})
    (game / "helpers.py").write_text("raise SystemExit\n", encoding="utf-8")
    scripted_app.quit_frame = 6
    assert launch(game) == 1
    top = scripted_app.apps[-1].screens.top
    assert isinstance(top, ErrorScreen)
    assert ('script/main.vns, line 11: define helpers couldn\'t be set: "helpers" is a file in '
            "the game folder") in top.message


# --- F44 C1 (step 6 part): --start and --set reach the new game ------------------------------

@pytest.mark.display
def test_c1_start_and_set_reach_the_new_game(tmp_path, user_roots, scripted_app):
    game = copy_example(tmp_path / "game")
    # --set names a default (E26c otherwise); the example game declares bought_lantern.
    code, shown, first = _play_example(
        scripted_app, game,
        argv=["run", str(game), "--start", "bridge", "--set", "bought_lantern=False"])
    assert code == 0
    assert first["line"].startswith("The old footbridge creaked")
    assert ("Daichi", "Shame. The stall closes at eight, and it's eight.") in shown
    assert scripted_app.apps[-1].start == StartOptions("bridge", (("bought_lantern", False),))


# --- AC-F03-31 — define evaluation is sliced and the window responds -------------------------

SLEEPY = "define t = module(\"time\")⏎" + "⏎".join(f"define w{k} = t.sleep(0.03)"
                                                   for k in range(20))


def test_ac_f03_31_a_one_define_per_step(tmp_path, monkeypatch):
    program = load_r(tmp_path, T=SLEEPY.replace("0.03", "0"))
    job = LaunchJob(program)
    evaluated = []
    real = job._set_define
    monkeypatch.setattr(job, "_set_define", lambda d: evaluated.append(d.name) or real(d))
    with pytest.raises(AssertionError):
        job.result
    counts = []
    while not job.step():
        counts.append(len(evaluated))
    names = [d.name for d in program.defines]
    assert evaluated == names
    # Each step evaluates at most one define (the namespace step evaluates none).
    assert all(b - a <= 1 for a, b in zip([0, *counts], counts))


@pytest.mark.display
def test_ac_f03_31_b_the_window_responds_during_the_launch(tmp_path):
    game = make_game(tmp_path, {"main.vns": template_r(T=SLEEPY)})
    pygame.init()
    pygame.event.clear()
    try:
        window = FakeWindow()
        paths = GamePaths.for_game(game)
        assets = AssetManager(paths, budget_bytes=64 * MB, scale_filter="smooth",
                              time=GameTime(), format_source=window.framebuffer)
        app = App(config=Config(), paths=paths, window=window, assets=assets, log=None,
                  dev=True, bench_seconds=0.05)
        app.screens.replace_all([story_load_screen(
            app, paths, on_ready=bootstrap.build_initial_screens)])
        frames: list[tuple[float, bool, bool]] = []      # (start, loading, launching)
        updates: list[float] = []
        benches: list[float] = []
        loader_screen = app.screens.top
        real_update = StoryLoadScreen.update
        real_wait = app._limiter.wait
        real_bench = BenchRecorder.__init__

        def update(self, dt, *, is_top):
            t = time.perf_counter()
            real_update(self, dt, is_top=is_top)
            updates.append(time.perf_counter() - t)

        def wait():
            start = real_wait()
            launching = loader_screen.job is not None and not loader_screen.finished
            frames.append((start, app.loading, launching))
            if launching and not window.calls.count("set_fullscreen"):
                post_key(pygame.K_F11)                 # handled between two slices
            if not app.loading and app.story is not None and len(frames) > 5:
                post_quit()
            return start

        def bench_init(self, **kwargs):
            benches.append((app.loading, app.story is not None))
            real_bench(self, **kwargs)

        app._limiter.wait = wait
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(StoryLoadScreen, "update", update)
            mp.setattr(BenchRecorder, "__init__", bench_init)
            assert app.run() == 0
    finally:
        pygame.quit()
    launching = [f for f in frames if f[2]]
    assert len(launching) >= 5                          # 20 × 30 ms over several frames
    assert all(loading for _, loading, _ in launching)
    assert max(updates) <= 0.1, max(updates)
    assert window.calls.count("set_fullscreen") == 1
    assert benches and benches[0] == (False, True)      # the bench starts after the launch
    from engine.ui.builtin.title_screen import TitleScreen
    assert isinstance(app.screens.top, TitleScreen)     # F10: launch shows the title


@pytest.mark.display
def test_ac_f03_31_b_quit_during_the_launch(tmp_path, user_roots, scripted_app, monkeypatch):
    game = make_game(tmp_path, {"main.vns": template_r(T=SLEEPY)})
    started, posted = [], []
    real_init = LaunchJob.__init__

    def init(self, *args, **kwargs):
        started.append(time.perf_counter())
        real_init(self, *args, **kwargs)

    def maybe_quit(app):
        if started and not posted and time.perf_counter() - started[0] >= 0.2:
            posted.append((time.perf_counter(), app.loading))
            post_quit()

    monkeypatch.setattr(LaunchJob, "__init__", init)
    for frame in range(1, 500):
        scripted_app.at(frame, maybe_quit)
    scripted_app.quit_frame = 10_000
    assert launch(game) == 0
    ended = time.perf_counter()
    assert posted and posted[0][1] is True              # still launching
    assert ended - posted[0][0] < 1.0
    assert scripted_app.apps[-1].story is None


# --- F03 step 7: AC-F03-48, 50 — a run-time error in the app --------------------------------

def instant(game: Path) -> Path:
    """``[textbox] cps = 0``: each line shows complete in its first frame, so one Space
    advances it (F05: a press while a line types only completes it)."""
    with (game / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[textbox]\ncps = 0\n")
    return game


ESC_FRAME = 14


def _fail_in_app(session, tmp_path: Path, S: str, *, release: bool = False):
    """Launch R with S, press Space at frame 5 (``Start.`` is shown by then) and Esc at
    ``ESC_FRAME``; returns (exit code, top screen type per frame, lines shown, the driver,
    every drawn text)."""
    from tests.app.test_story_load_screen import launch as launch_game
    from tests.fakes.draw_spy import spy_draw_text

    game = instant(make_game(tmp_path, {"main.vns": template_r(S=S)}))
    tops, shown, drivers = {}, [], []
    real_show = TextboxScreen.show
    real_install = story.install_story

    def show(self, cmd):
        shown.append(cmd.text)
        real_show(self, cmd)

    def install(app, interp, **kwargs):
        drivers.append(real_install(app, interp, **kwargs))
        return drivers[-1]

    for frame in range(1, 40):
        session.at(frame, lambda app, frame=frame: tops.__setitem__(frame, type(app.screens.top)))
    session.at(5, lambda app: post_key(pygame.K_SPACE))
    session.at(ESC_FRAME, lambda app: post_key(pygame.K_ESCAPE))
    session.quit_frame = 60
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(TextboxScreen, "show", show)
        mp.setattr("engine.app.loading.install_story", install)
        with spy_draw_text(mp) as calls:
            code = launch_game(game, release=release)
    return code, tops, shown, drivers[-1], [c.text for c in calls]


@pytest.mark.display
@pytest.mark.parametrize("release", [False, True], ids=["dev", "release"])
def test_ac_f03_48_the_error_screen_and_exit_code(tmp_path, user_roots, scripted_app, release):
    from engine.ui.builtin.error import ErrorScreen

    code, tops, shown, driver, drawn = _fail_in_app(scripted_app, tmp_path, "$ x = trsut",
                                                    release=release)
    assert code == 1 and scripted_app.limiters[-1].frame == ESC_FRAME     # Esc ended it
    app = scripted_app.apps[-1]
    assert isinstance(app.screens.top, ErrorScreen)
    assert app.screens.top.message == ('script/main.vns, line 8: there is no variable named '
                                       '"trsut". Did you mean "trust"?')
    first_error = min(f for f, t in tops.items() if t is ErrorScreen)
    assert first_error == 6                                  # the frame after the Space
    assert shown == ["Start."]                               # no further Say dispatched
    assert not [t for t in drawn if "Traceback" in t or 'File "' in t or ".py" in t]
    assert any(t.startswith("script/main.vns, line 8: there is no variable") for t in drawn)


@pytest.mark.display
@pytest.mark.parametrize("S", ["$ exit()", "$ raise MemoryError", '$ raise BaseException("x")',
                               "$ raise GeneratorExit", "$ x = 1 / 0"])
def test_ac_f03_50_no_crash_no_hang_nothing_more(tmp_path, user_roots, scripted_app, capsys, S):
    from engine.ui.builtin.error import ErrorScreen

    code, tops, shown, driver, _ = _fail_in_app(scripted_app, tmp_path, S)
    assert code == 1 and scripted_app.limiters[-1].frame == ESC_FRAME     # open until Esc
    top = scripted_app.apps[-1].screens.top
    assert isinstance(top, ErrorScreen) and top.message.startswith("script/main.vns, line 8: ")
    assert all(t is ErrorScreen for f, t in tops.items() if 6 <= f <= ESC_FRAME)
    err = capsys.readouterr().err
    assert "Traceback (most recent call last)" not in err and 'File "' not in err
    assert driver.status is Status.FAILED and driver.checkpoint() is None
    sid = driver.interp.current.sid
    driver.post(Advance(sid))
    assert [driver.pump() for _ in range(10)] == [[]] * 10
    assert driver.checkpoint() is None and shown == ["Start."]


@pytest.mark.display
def test_ac_f03_50_a_keyboard_interrupt_is_f01s(tmp_path, user_roots, scripted_app):
    code, tops, shown, driver, _ = _fail_in_app(scripted_app, tmp_path,
                                                "$ raise KeyboardInterrupt")
    assert code == 0 and scripted_app.limiters[-1].frame == 5
    game = tmp_path / "game"
    lines = [m for _, _, m in records(game / "logs" / "latest.log")]
    assert lines[-2:] == ["Interrupted from the terminal (Ctrl+C)", "Clean shutdown (exit code 0)"]


@pytest.mark.display
def test_a_run_time_error_is_logged_once_with_its_frames(tmp_path, user_roots, scripted_app):
    _fail_in_app(scripted_app, tmp_path, "$ x = 1 / 0")
    log = (tmp_path / "game" / "logs" / "latest.log").read_text(encoding="utf-8")
    errors = [r for r in records(tmp_path / "game" / "logs" / "latest.log") if r[0] == "ERROR"]
    assert [(level, area) for level, area, _ in errors] == [("ERROR", "runtime")]
    assert errors[0][2].startswith("script/main.vns, line 8: this divides by zero.")
    # SEC-F23-09: every traceback line carries the two-space prefix (F23 07 I-14).
    assert "\n      $ x = 1 / 0\n  Traceback (script frames):\n    script/main.vns, line 8 " \
           "(label start)\n  ZeroDivisionError\n" in log


# --- F03 step 13 — AC-F03-44 (--seed in dev runs), AC-F03-74 in the window -----------------

@pytest.fixture
def launch_args(monkeypatch):
    """``bootstrap.launch`` replaced by a recorder of its keyword arguments."""
    calls: list[dict] = []
    monkeypatch.setattr(bootstrap, "launch",
                        lambda game_dir, **kwargs: calls.append(kwargs) or 0)
    return calls


def seed_usage_error(argv: list[str], capsys) -> str:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 2
    return capsys.readouterr().err


@pytest.mark.parametrize("text, seed", [("42", 42), ("0", 0), ("007", 7),
                                        ("18446744073709551615", (1 << 64) - 1)])
def test_ac_f03_44_seed_values_are_accepted(tmp_path, launch_args, text, seed):
    assert cli.main(["run", str(tmp_path), "--seed", text]) == 0
    assert launch_args[0]["seed"] == seed and launch_args[0]["release"] is False


def test_ac_f03_44_no_seed_means_none(tmp_path, launch_args):
    assert cli.main(["run", str(tmp_path)]) == 0
    assert launch_args[0]["seed"] is None


@pytest.mark.parametrize("text", ["-1", "18446744073709551616", "abc", "1.5", "+1", " 1",
                                  "1e3", "", "\u0664\u0662"])
def test_ac_f03_44_bad_seeds_are_usage_errors(tmp_path, launch_args, capsys, text):
    err = seed_usage_error(["run", str(tmp_path), f"--seed={text}"], capsys)
    assert err.startswith("usage: python -m engine run ")
    assert "--seed needs a whole number from 0 to 18446744073709551615" in err
    assert launch_args == []


def test_ac_f03_44_release_refuses_seed(tmp_path, launch_args, capsys):
    err = seed_usage_error(["run", str(tmp_path), "--release", "--seed", "1"], capsys)
    assert err.startswith("usage: python -m engine run ")
    assert err.rstrip().endswith("--seed is only available in dev runs")
    assert launch_args == []


def test_ac_f03_44_frozen_parser_has_no_seed(tmp_path, launch_args, capsys, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(REPO), raising=False)
    err = seed_usage_error(["run", str(tmp_path), "--seed", "1"], capsys)
    assert "unrecognized arguments: --seed 1" in err
    assert launch_args == []


def test_main_py_has_no_seed(capsys, monkeypatch):
    """F44 I-10: the dev-run options are ``run``'s; ``main.py``'s usage line is unchanged
    (AC-F01-159)."""
    from tests.app.test_cli import USAGE

    monkeypatch.setattr(cli, "_launch", lambda *a, **k: pytest.fail("launched"))
    with pytest.raises(SystemExit) as exit_info:
        cli.launcher_main(["--seed", "42"])
    assert exit_info.value.code == 2
    assert capsys.readouterr().err.startswith(USAGE + "\n")


def test_run_help_lists_seed(capsys):
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    usage = capsys.readouterr().out.split("\n\n")[0]
    assert "[--seed N]" in usage


def test_f44_ac02_seed_combines_with_start_and_set(tmp_path, launch_args):
    """AC-F44-02's last CLI row: ``--start``, ``--set``, and ``--seed`` combine freely, and
    the start options draw no numbers, so the first checkpoint's ``dice`` is that of
    ``--seed 42`` alone."""
    from tests.tools.editor.conftest import R_SCRIPTS

    assert cli.main(["run", str(tmp_path), "--start", "club_poem", "--set", "sayo_points=1",
                     "--seed", "42"]) == 0
    (call,) = launch_args
    assert call["seed"] == 42
    assert call["start"] == StartOptions("club_poem", (("sayo_points", 1),))
    from tests.runtime.story import load_files

    program = load_files(tmp_path / "r", R_SCRIPTS)
    dice = []
    for start in (call["start"], None):
        launched = run_launch(program)
        driver = RuntimeStoryDriver(Interpreter(program, launched.namespace, start=start),
                                    clock=TickClock(), fixed_seed=call["seed"])
        driver.new_game()
        says = [c for c in driver.pump() if type(c) is Say]
        dice.append((says[0].text, driver.checkpoint().to_json()["dice"]))
    assert dice == [("You wrote a poem? Let me see!", SEED_42_DICE),
                    ("Opening line.", SEED_42_DICE)]


@pytest.mark.display
def test_ac_f03_44_and_74_seed_in_the_window(tmp_path, user_roots, scripted_app):
    """``python -m engine run <R> --seed 42`` (dev): every new game's first checkpoint has
    the seed-42 dice, and each new game logs ``New game: seed 42, 2 defaults.``."""
    game = make_game(tmp_path, {"main.vns": template_r()})
    states = []

    def first_checkpoint(app):
        states.append(app.story.checkpoint())
        app.story.new_game()                         # a second game in the same session

    scripted_app.at(12, first_checkpoint)
    scripted_app.at(20, lambda app: states.append(app.story.checkpoint()))
    scripted_app.quit_frame = 22
    assert cli.main(["run", str(game), "--seed", "42"]) == 0
    app = scripted_app.apps[-1]
    assert app.seed == 42 and app.story.fixed_seed == 42
    assert [s.to_json()["dice"] for s in states] == [SEED_42_DICE, SEED_42_DICE]
    lines = [r for r in records(game / "logs" / "latest.log") if r[2].startswith("New game")]
    assert lines == [("INFO", "runtime", "New game: seed 42, 2 defaults.")] * 2


@pytest.mark.display
def test_ac_f03_74_release_window_logs_no_seed(tmp_path, user_roots, scripted_app):
    game = make_game(tmp_path, {"main.vns": template_r()})
    scripted_app.quit_frame = 12
    assert launch(game, release=True) == 0
    app = scripted_app.apps[-1]
    assert app.seed is None and app.story.fixed_seed is None
    (log,) = user_roots.home.rglob("latest.log")           # release: the per-user folder
    lines = [r for r in records(log) if r[2].startswith("New game")]
    assert lines == [("INFO", "runtime", "New game: 2 defaults.")]


# --- F08 step 3 — the audio commands have a handler until the audio service exists ----------

def test_f08_audio_commands_reach_a_handler_that_does_nothing(tmp_path):
    """An App-level run of a story with audio never meets ``UnhandledCommandError``: each of
    the nine commands is dispatched to ``install_no_audio``'s stand-in (F08 step 4/5: the
    audio service replaces these)."""

    class _App:
        router = CommandRouter()

    app = _App()
    story.install_no_audio(app)
    assert set(app.router._handlers) == set(story.AUDIO_COMMANDS)
    assert len(story.AUDIO_COMMANDS) == 9
    program = load_files(tmp_path, {"main.vns": template_a(
        S='play music "bgm/omen.ogg"⏎queue music "bgm/a.ogg"⏎play sound "sfx/r.ogg" loop⏎'
          'play sound "sfx/d.ogg"⏎stop sound⏎stop voice⏎voice "voice/v.ogg"⏎"Hi."⏎stop music')})
    commands = run_headless(program, seed=42)
    kinds = {type(c) for c in commands}
    assert set(story.AUDIO_COMMANDS) <= kinds             # the story sends all nine
    for cmd in commands:
        if type(cmd) in story.AUDIO_COMMANDS:
            app.router.dispatch(cmd)
