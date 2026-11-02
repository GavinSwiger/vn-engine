"""F10 step 6 in the real app (App F, ``06`` §0.4): AC-F10-33, 37, 39, 40, and the App F rows
of AC-F10-08, plus the step's milestone (title → New Game → the story plays in F05's textbox
→ story end → title). Later steps add their App F rows below; AC-F10-70 (step 9) launches a
copy of the shipped ``game/``.

Every run is an in-process ``launch()`` (``scripted_app``: fake frame clock, hidden window,
1280×720, dev) on a temporary copy of ``tests/fixtures/F10/template_min/`` (I-20: Template F's
``define`` and lines 5 and 13–17), so the fixture folder never gets a ``logs/``. The Audio spy
is put on ``App.audio`` in frame 1, before the story (and ``install_ui``) is installed: F08's
``AudioService`` doesn't exist yet. Pending until other features land (I-20): every row on
Template F's stage (F04), P-pause/P-fade (F09), music (F08), and real choices (F07).
"""

import shutil
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap, cli
from engine.app.app import App
from engine.app.story import RuntimeStoryDriver
from engine.runtime.interpreter import Status
from engine.script import StoryLoader
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.error import ErrorScreen
from engine.ui.builtin.sampler import SamplerScreen
from engine.ui.builtin.stage_screen import StageScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.nav import InputKind
from engine.ui.shell import GameShell, Mode
from tests.fakes.audio_spy import AudioSpy
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "tests" / "fixtures" / "F10" / "template_min"
BAND = (1000, 600)                 # inside F05's textbox while a line shows
BOX = (0xCC, 0xC3, 0xC6)           # its fill #FFF4F8 at 0.80 over the black stage


def make_game(tmp_path: Path, config: str = "", *, script: str | None = None) -> Path:
    root = Path(shutil.copytree(TEMPLATE, tmp_path / "game"))
    if config:
        with (root / "config.toml").open("a", encoding="utf-8") as f:
            f.write("\n" + config + "\n")
    if script is not None:
        (root / "script" / "main.vns").write_text(script, encoding="utf-8")
    return root


def launch(game: Path) -> int:
    return bootstrap.launch(game, release=False, bench_seconds=None, log_level_override=None,
                            pygame_warning=None)


def post(kind: int, **attrs) -> None:
    pygame.event.post(pygame.event.Event(kind, **attrs))


class Recorder:
    """Per presented frame: probe pixels, the stack's types, and the shell's mode."""

    def __init__(self, session, points=(BAND,)) -> None:
        self.session = session
        self.points = points
        self.frames: dict[int, tuple] = {}

    def install(self, mp) -> None:
        real = App.present
        recorder = self

        def present(app):
            result = real(app)
            fb = app.window.framebuffer()
            frame = recorder.session.limiters[-1].frame
            pixels = tuple(tuple(fb.get_at(p))[:3] for p in recorder.points)
            mode = app.shell.mode if app.shell is not None else None
            recorder.frames[frame] = (pixels, tuple(type(s) for s in app.screens), mode)
            return result

        mp.setattr(App, "present", present)

    def first(self, predicate) -> int:
        return min(f for f, row in self.frames.items() if predicate(row))


def with_audio(session, spy: AudioSpy) -> None:
    session.at(1, lambda app: setattr(app, "audio", spy))


class Player:
    """Each frame: on the title (fully faded in) press Return twice (focus, then New Game);
    in the game press Space every third frame while a line shows; stop once the story
    ended (``games`` new games at most)."""

    def __init__(self, session, *, games: int = 1, last: int = 600) -> None:
        self.session = session
        self.games = games
        self.started = 0
        self.returns = 0
        self.ended_frames: list[int] = []
        for frame in range(2, last):
            session.at(frame, self.step)
        session.quit_frame = last

    def step(self, app) -> None:
        frame = self.session.limiters[-1].frame
        top = app.screens.top
        if isinstance(top, TitleScreen) and top.in_t >= 1.0 and not top.leaving:
            if self.started < self.games:
                post_key(pygame.K_RETURN)
                self.returns += 1
                if self.returns % 2 == 0:
                    self.started += 1
        elif isinstance(top, TextboxScreen) and top.line is not None and frame % 3 == 0:
            if app.story is not None and app.story.status is not Status.ENDED:
                post_key(pygame.K_SPACE)


def said(mp) -> list[tuple[int, str]]:
    """Every line the textbox shows (filled in as the run goes)."""
    lines: list = []
    real = TextboxScreen.show

    def show(self, cmd):
        lines.append(cmd.text)
        real(self, cmd)

    mp.setattr(TextboxScreen, "show", show)
    return lines


# --- AC-F10-33 — launch to the title -----------------------------------------------------

def test_ac33_launch_to_the_title(tmp_path, user_roots, scripted_app, monkeypatch):
    game = make_game(tmp_path)
    pumps, games = [], []
    real_pump = RuntimeStoryDriver.pump
    real_new_game = RuntimeStoryDriver.new_game

    def pump(self, *args, **kwargs):
        released = real_pump(self, *args, **kwargs)
        pumps.append(released)
        return released

    monkeypatch.setattr(RuntimeStoryDriver, "pump", pump)
    monkeypatch.setattr(RuntimeStoryDriver, "new_game",
                        lambda self: games.append(1) or real_new_game(self))
    states = []
    for frame, action in ((10, lambda: post_key(pygame.K_ESCAPE)),
                          (12, lambda: post(pygame.MOUSEBUTTONDOWN, pos=(640, 360), button=3)),
                          (13, lambda: post(pygame.MOUSEBUTTONUP, pos=(640, 360), button=3)),
                          (14, lambda: post(pygame.CONTROLLERBUTTONDOWN, button=1,
                                            instance_id=0)),
                          (15, lambda: post(pygame.CONTROLLERBUTTONDOWN, button=6,
                                            instance_id=0)),
                          (16, lambda: post(pygame.MOUSEWHEEL, x=0, y=-1, flipped=False))):
        scripted_app.at(frame, lambda app, action=action: action())
    for frame in range(5, 30):
        scripted_app.at(frame, lambda app: states.append(
            (tuple(type(s) for s in app.screens), app.shell and app.shell.mode,
             app.screens.top.scope.focused if isinstance(app.screens.top, TitleScreen)
             else "-")))
    scripted_app.at(20, lambda app: post_key(pygame.K_DOWN))     # first navigation input
    scripted_app.quit_frame = 30
    assert launch(game) == 0
    app = scripted_app.apps[-1]
    assert isinstance(app.shell, GameShell)
    title = app.screens.top
    assert isinstance(title, TitleScreen) and app.shell.mode is Mode.TITLE
    assert [b.label() for b in title.buttons] == ["New Game", "Load", "Settings",
                                                    "Quit"]  # F11 step 9, F16 step 4
    assert games == [] and pumps == []                  # no new game, no pump, no command
    assert app.story.status is Status.IDLE
    before = [s for s in states[:15] if s[0] == (TitleScreen,)]
    assert before and all(s[1] is Mode.TITLE and s[2] is None for s in before)
    assert states[-1][2] is title.buttons[0]            # Down focused New Game


def test_ac33_no_story_still_shows_the_placeholder(tmp_path, user_roots, scripted_app):
    from engine.ui.builtin.placeholder import PlaceholderScreen

    game = make_game(tmp_path)
    shutil.rmtree(game / "script")
    assert launch(game) == 0
    app = scripted_app.apps[-1]
    assert [type(s) for s in app.screens] == [PlaceholderScreen] and app.shell is None


# --- The milestone and AC-F10-40 — New Game, play to the end, back to the title ---------------

def test_milestone_and_ac40_story_end(tmp_path, user_roots, scripted_app, monkeypatch):
    game = make_game(tmp_path, '[theme.title]\nmusic = "title.ogg"')
    spy = AudioSpy()
    with_audio(scripted_app, spy)
    player = Player(scripted_app, last=260)
    recorder = Recorder(scripted_app)
    ended = []
    real_end = GameShell.story_ended

    def story_ended(self, cmd):
        ended.append((scripted_app.limiters[-1].frame, len(spy.calls), self.mode))
        real_end(self, cmd)

    with pytest.MonkeyPatch.context() as mp:
        recorder.install(mp)
        lines = said(mp)
        mp.setattr(GameShell, "story_ended", story_ended)
        # Input in the fade frames is ignored: Esc and Space every frame after the end.
        for frame in range(2, 260):
            scripted_app.at(frame, lambda app: (isinstance(app.screens.top, BlackFadeScreen)
                                                and (post_key(pygame.K_ESCAPE),
                                                     post_key(pygame.K_SPACE))))
        assert launch(game) == 0
    app = scripted_app.apps[-1]
    assert lines == ["Hello there, this line types slowly.", "End."]
    assert len(ended) == 1
    n, calls_before, mode = ended[0]
    assert mode is Mode.GAME
    # stop_story_audio(0.5) in frame N.
    assert spy.calls[calls_before] == ("stop_story_audio", 0.5)
    # The box goes to black linearly over 60 frames, with the textbox under the fade.
    band = recorder.frames[n - 1][0][0]
    assert all(abs(c - b) <= 1 for c, b in zip(band, BOX)), band
    for k in range(60):
        pixels, types, _ = recorder.frames[n + k]
        assert types == (StageScreen, TextboxScreen, BlackFadeScreen), k   # F04: the stage
        expected = [round(b * (1 - k / 60)) for b in band]
        assert all(abs(c - e) <= 3 for c, e in zip(pixels[0], expected)), (k, pixels[0])
    # Then the title, fading in over 30 frames from black, mode TITLE, music taken again.
    pixels, types, mode = recorder.frames[n + 60]
    assert types == (TitleScreen,) and mode is Mode.TITLE and pixels[0] == (0, 0, 0)
    final = recorder.frames[n + 90][0][0]
    assert final != (0, 0, 0)
    for k in (10, 20):
        assert recorder.frames[n + 60 + k][0][0] != final
    assert recorder.frames[n + 95][0][0] == final
    assert spy.calls[calls_before + 1:] == [("take_music", "title"),
                                            ("play", "title.ogg", True, 0.0)]
    assert [type(s) for s in app.screens] == [TitleScreen] and app.shell.mode is Mode.TITLE
    # Over the whole run: the title took and played its music, New Game stopped it and
    # released it at the cut.
    assert spy.calls[:4] == [("take_music", "title"), ("play", "title.ogg", True, 0.0),
                             ("stop", 0.5), ("release",)]


def test_ac40_a_failing_last_line_shows_the_error_screen(tmp_path, user_roots, scripted_app):
    script = (TEMPLATE / "script" / "main.vns").read_text(encoding="utf-8")
    game = make_game(tmp_path, script=script.replace('    "End."\n', "    $ 1 / 0\n"))
    Player(scripted_app, last=120)
    constructed = []
    with pytest.MonkeyPatch.context() as mp:
        real_init = TitleScreen.__init__
        mp.setattr(TitleScreen, "__init__",
                   lambda self, *a, **k: constructed.append(1) or real_init(self, *a, **k))
        fades = []
        real_fade = BlackFadeScreen.__init__
        mp.setattr(BlackFadeScreen, "__init__",
                   lambda self, *a, **k: fades.append(1) or real_fade(self, *a, **k))
        assert launch(game) == 1                       # the error screen's exit code
    app = scripted_app.apps[-1]
    assert isinstance(app.screens.top, ErrorScreen) and len(app.screens) == 1
    assert len(constructed) == 1 and fades == []        # only the launch title; no fade


# --- AC-F10-39 — start options skip the title ---------------------------------------------------

def test_ac39_start_skips_the_title_and_new_game_starts_there_again(tmp_path, user_roots,
                                                                    scripted_app):
    game = make_game(tmp_path)
    constructed: list[int] = []
    Player(scripted_app, games=1, last=300)
    states = {}
    scripted_app.at(299, lambda app: states.update(types=[type(s) for s in app.screens],
                                                   mode=app.shell.mode))
    with pytest.MonkeyPatch.context() as mp:
        real_init = TitleScreen.__init__

        def init(self, *args, **kwargs):
            constructed.append(scripted_app.limiters[-1].frame)
            real_init(self, *args, **kwargs)

        mp.setattr(TitleScreen, "__init__", init)
        lines = said(mp)
        assert cli.main(["run", str(game), "--start", "late"]) == 0
    # The first game: "Late line." with no title; its end shows the title; New Game starts
    # at "Late line." again (the second "Late line.").
    assert lines[:2] == ["Late line.", "Late line."]
    assert len(constructed) == 2                    # after each end, never at launch
    assert states["types"] == [TitleScreen] and states["mode"] is Mode.TITLE


def test_ac39_set_only_skips_the_title_and_every_new_game_applies_it(tmp_path, user_roots,
                                                                     scripted_app):
    game = make_game(tmp_path, script='default n = 0\nlabel start:\n    "N line."\n'
                                      "    return\n")
    Player(scripted_app, games=1, last=300)
    seen = []
    real_show = TextboxScreen.show

    def show(self, cmd):
        seen.append(self.app.story.checkpoint().variables["n"])
        real_show(self, cmd)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(TextboxScreen, "show", show)
        assert cli.main(["run", str(game), "--set", "n=7"]) == 0
    assert seen == [7, 7]                           # the first game and the New Game


def test_ac39_without_options_the_title_comes_first(tmp_path, user_roots, scripted_app):
    game = make_game(tmp_path)
    tops = []
    for frame in range(2, 12):
        scripted_app.at(frame, lambda app: tops.append(type(app.screens.top).__name__))
    scripted_app.quit_frame = 12
    assert cli.main(["run", str(game)]) == 0
    assert "TitleScreen" in tops and "TextboxScreen" not in tops


# --- AC-F10-37 — the loading indicator ------------------------------------------------------

def _slow_load(session, game: Path, frames: int, mp, recorder: Recorder):
    """The loader returns "not done" for its first ``frames`` steps (one per frame), then
    loads for real. Returns (text calls per frame, the frame the load finished)."""
    real_step = StoryLoader.step
    steps = []

    def step(self, budget_s):
        steps.append(session.limiters[-1].frame)
        if len(steps) <= frames:
            return False
        return real_step(self, 1e9)

    mp.setattr(StoryLoader, "step", step)
    recorder.install(mp)
    per_frame: dict[int, list] = {}
    with spy_draw_text(mp) as calls:
        real_present = App.present

        def present(app):
            result = real_present(app)
            per_frame[session.limiters[-1].frame] = list(calls)
            calls.clear()
            return result

        mp.setattr(App, "present", present)
        assert launch(game) == 0
    return per_frame, steps[-1]


def _dot_points(y: float) -> tuple:
    return tuple((1264 - 30 + k * 12 + 3, round(y)) for k in range(3))


@pytest.mark.parametrize("seconds, frames", [(0.9, 54), (3.0, 180)], ids=["0.9s", "3s"])
def test_ac37_loading_indicator(tmp_path, user_roots, scripted_app, seconds, frames):
    shutil.copy(REPO / "engine" / "data" / "fonts" / "NotoSans-Regular.ttf",
                (tmp_path / "u.ttf"))
    game = make_game(tmp_path, '[theme.ui]\ntext_font = "fonts/u.ttf"')
    (game / "fonts").mkdir(exist_ok=True)
    shutil.copy(tmp_path / "u.ttf", game / "fonts" / "u.ttf")
    scripted_app.quit_frame = frames + 12
    recorder = Recorder(scripted_app, points=_dot_points(708 - 14))
    with pytest.MonkeyPatch.context() as mp:
        per_frame, done = _slow_load(scripted_app, game, frames, mp, recorder)
    loading = {f: [c for c in calls if c.text == "Loading"] for f, calls in per_frame.items()}
    shown = sorted(f for f, found in loading.items() if found)
    title_first = recorder.first(lambda row: row[1] == (TitleScreen,))
    assert title_first >= done
    assert not loading[title_first]                     # gone when the title starts fading in
    if seconds < 1.0:
        assert shown == []
        return
    assert shown[0] in (60, 61, 62) and shown[-1] == title_first - 1
    assert shown == list(range(shown[0], title_first))
    call = loading[shown[0]][0]
    assert call.color == (0xFF, 0xE6, 0xF0) and call.font.ref is None and call.font.size == 20
    assert call.font.bundled.name == "REGULAR"
    left, top, width, height = call.bounds
    assert abs(left + width - 1226) <= 1 and abs(top + height - 708) <= 1
    # Dot k is bright exactly when floor(t / 0.3) mod 3 == k (t since shown).
    first = shown[0]
    full, dim = (0xFF, 0xE6, 0xF0), tuple(round(c * 0.3) for c in (0xFF, 0xE6, 0xF0))
    dot_y = top + height / 2                            # the dots sit on the text's middle
    for offset in (5, 23, 41, 59, 77):                 # t = 0.083, 0.383, 0.683, 0.983, 1.283
        f = first + offset
        if f >= title_first:
            break
        bright = int(offset / 18) % 3
        pixels = recorder.frames[f][0]
        for k, pixel in enumerate(pixels):
            want = full if k == bright else dim
            assert all(abs(a - b) <= 6 for a, b in zip(pixel, want)), (offset, k, pixel)
    assert abs(dot_y - (708 - 14)) <= 2


def test_ac37_same_hand_over_delay_for_short_and_long_loads(tmp_path, user_roots,
                                                            scripted_app):
    delays = []
    for name, frames in (("short", 54), ("long", 180)):
        game = make_game(tmp_path / name)
        scripted_app.quit_frame = frames + 12
        recorder = Recorder(scripted_app)
        with pytest.MonkeyPatch.context() as mp:
            per_frame, done = _slow_load(scripted_app, game, frames, mp, recorder)
        delays.append(recorder.first(lambda row: row[1] == (TitleScreen,)) - done)
    assert delays[0] == delays[1]


# --- AC-F10-08 (App F rows) — Shift+F3 on the title opens the sampler; hold Down -------------

def test_ac08_sampler_from_the_title_and_hold_down(tmp_path, user_roots, scripted_app):
    game = make_game(tmp_path)
    seen = {}

    def focus_list(app):
        sampler = app.screens.top
        seen["sampler"] = sampler
        sampler.scope.focus(sampler.list, InputKind.KEYS)
        sampler.list.focus_row = 0

    scripted_app.at(10, lambda app: post_key(pygame.K_F3, pygame.KMOD_LSHIFT))
    scripted_app.at(12, focus_list)
    scripted_app.at(13, lambda app: post_key(pygame.K_DOWN))
    scripted_app.at(13 + 78, lambda app: post(pygame.KEYUP, key=pygame.K_DOWN, mod=0,
                                              unicode="", scancode=0))
    scripted_app.at(13 + 140, lambda app: seen.update(row=seen["sampler"].list.focus_row))
    scripted_app.at(13 + 141, lambda app: post_key(pygame.K_ESCAPE))
    scripted_app.quit_frame = 13 + 145
    assert launch(game) == 0
    assert isinstance(seen["sampler"], SamplerScreen)
    assert seen["row"] == 12                            # Row 13, and no step after the KEYUP
    assert isinstance(scripted_app.apps[-1].screens.top, TitleScreen)   # Esc: back


def test_ac37_reduced_motion_keeps_every_dot_full():
    from types import SimpleNamespace

    from engine.app.loading import StoryLoadScreen
    from engine.core.config_schema import Config

    screen = StoryLoadScreen(SimpleNamespace(config=Config()), None, on_ready=lambda app: [])
    screen.elapsed = 1.35                                # t = 0.35 since shown
    assert screen.bright_dot() == 1
    screen.reduce_motion = True                          # [effects] reduce (F09) / F16
    assert screen.bright_dot() is None


def test_ac47_overrides_leave_the_checkpoint_unchanged(tmp_path, user_roots, scripted_app):
    """AC-F10-47's last row: using every override changes no story state."""
    game = make_game(tmp_path)
    Player(scripted_app, games=1, last=80)
    seen = {}

    def use_every_override(app):
        story = app.story
        if "before" in seen or story is None or story.checkpoint() is None:
            return
        seen["before"] = story.checkpoint().to_json()
        overrides = app.shell.overrides
        overrides.set_word("quit", "Leave")
        overrides.set_hidden("title", "quit", True)
        overrides.set_title_look(background="gui/x.png", logo="gui/y.png", music="z.ogg")
        overrides.clear()
        seen["after"] = story.checkpoint().to_json()

    for frame in range(2, 80):
        scripted_app.at(frame, use_every_override)
    assert launch(game) == 0
    assert seen["before"] == seen["after"]


# --- F10 step 7 in the real app: the game menu, its questions, and quitting --------------------
#
# AC-F10-31, 41, 45, and 57's App F rows, and the step's milestone on the textbox (Esc opens
# the game menu over the line). Template F's stage, P-pause/P-fade (F09), music (F08), and
# real choices (F07) rows are pending (I-20). F04 (being built) already sends ``ShowStage``
# before its ``install_stage`` registers a handler; ``no_stage_yet`` drops it until then.

@pytest.fixture
def no_stage_yet(monkeypatch):
    from engine.app.dispatch import CommandRouter
    from engine.runtime import commands

    stage = getattr(commands, "ShowStage", None)
    real = CommandRouter.dispatch

    def dispatch(self, command):
        if stage is not None and isinstance(command, stage) and not any(
                klass in self._handlers for klass in type(command).__mro__):
            return
        real(self, command)

    monkeypatch.setattr(CommandRouter, "dispatch", dispatch)


class Steps:
    """Runs ``steps`` ((offset, action(app)), ...) counted from the first frame where the
    textbox is top showing a line."""

    def __init__(self, session, steps, *, last: int) -> None:
        self.session = session
        self.steps = list(steps)
        self.start: int | None = None
        for frame in range(2, last):
            session.at(frame, self.tick)
        session.quit_frame = last

    def tick(self, app) -> None:
        frame = self.session.limiters[-1].frame
        if self.start is None:
            top = app.screens.top
            if not (isinstance(top, TextboxScreen) and top.line is not None):
                return
            self.start = frame
        for offset, action in self.steps:
            if frame == self.start + offset:
                action(app)


def to_main_menu(app) -> None:
    """From Return (focused when the game menu opens by keys) to Main Menu: Up twice wraps
    to Quit, then Main Menu, whichever page entries (F11, F13, F16) sit between them."""
    post_key(pygame.K_UP)
    post_key(pygame.K_UP)


def run_from_start(game: Path) -> int:
    return cli.main(["run", str(game), "--start", "start"])


def test_step7_milestone_esc_opens_the_game_menu_over_the_line(tmp_path, user_roots,
                                                               scripted_app, no_stage_yet):
    from engine.ui.builtin.game_menu import GameMenuScreen

    game = make_game(tmp_path)
    seen = {}
    Steps(scripted_app, [
        (1, lambda app: post_key(pygame.K_ESCAPE)),
        (2, lambda app: seen.update(types=[type(s) for s in app.screens])),
        (12, lambda app: post_key(pygame.K_ESCAPE)),
        (23, lambda app: seen.update(after=[type(s) for s in app.screens])),
    ], last=40)
    assert run_from_start(game) == 0
    assert seen["types"] == [StageScreen, TextboxScreen, GameMenuScreen]   # F04: the stage
    assert seen["after"] == [StageScreen, TextboxScreen]


def test_ac31_the_story_waits_under_every_menu(tmp_path, user_roots, scripted_app,
                                               monkeypatch, no_stage_yet):
    from engine.ui.builtin.confirm import ConfirmScreen

    game = make_game(tmp_path)
    spy = AudioSpy()
    with_audio(scripted_app, spy)
    pumps: list[tuple[int, type]] = []
    real_pump = RuntimeStoryDriver.pump

    def pump(self, *args, **kwargs):
        app = scripted_app.apps[-1]
        pumps.append((scripted_app.limiters[-1].frame, type(app.screens.top)))
        return real_pump(self, *args, **kwargs)

    monkeypatch.setattr(RuntimeStoryDriver, "pump", pump)
    seen: dict = {}

    def snapshot(name):
        def take(app):
            seen[name] = (app.story.checkpoint().to_json(), len(spy.calls),
                          scripted_app.limiters[-1].frame)
        return take

    def check_asked(app):
        top = app.screens.top
        seen["quit_question"] = isinstance(top, ConfirmScreen) and top.message.startswith("Quit")

    with pytest.MonkeyPatch.context() as mp:
        lines = said(mp)
        Steps(scripted_app, [
            (1, snapshot("before")), (1, lambda app: post_key(pygame.K_ESCAPE)),   # open
            (12, to_main_menu),
            (13, lambda app: post_key(pygame.K_RETURN)),                         # Main Menu?
            (25, lambda app: post_key(pygame.K_ESCAPE)),                         # No
            (37, lambda app: post_key(pygame.K_F3, pygame.KMOD_LSHIFT)),         # sampler
            (40, lambda app: post_key(pygame.K_ESCAPE)),
            (52, lambda app: post(pygame.QUIT)), (54, check_asked),              # QUIT
            (64, lambda app: post_key(pygame.K_RETURN)),                         # No
            (76, lambda app: post_key(pygame.K_ESCAPE)),                         # close
            (88, snapshot("after")),
            (90, lambda app: post_key(pygame.K_SPACE)),          # completes the typing line
            (92, lambda app: post_key(pygame.K_SPACE)),                          # advance
        ], last=200)
        assert run_from_start(game) == 0
    start = seen["before"][2]
    end = seen["after"][2]
    assert seen["quit_question"] is True
    held = [p for p in pumps if start <= p[0] < end - 2]
    assert held == []                                   # no pump while a menu was up
    assert all(top is TextboxScreen for _, top in pumps)
    assert seen["before"][0] == seen["after"][0]        # byte-identical checkpoint
    calls = spy.calls[seen["before"][1]:seen["after"][1]]
    assert not [c for c in calls if c[0] in ("stop", "stop_story_audio", "release")]
    assert lines == ["Hello there, this line types slowly.", "End."]


def test_ac45_main_menu_yes_shows_the_title_and_never_pumps_under_it(
        tmp_path, user_roots, scripted_app, monkeypatch, no_stage_yet):
    game = make_game(tmp_path, '[theme.title]\nmusic = "title.ogg"')
    spy = AudioSpy()
    with_audio(scripted_app, spy)
    pumps: list[type] = []
    real_pump = RuntimeStoryDriver.pump

    def pump(self, *args, **kwargs):
        pumps.append(type(scripted_app.apps[-1].screens.top))
        return real_pump(self, *args, **kwargs)

    monkeypatch.setattr(RuntimeStoryDriver, "pump", pump)
    seen: dict = {}
    Steps(scripted_app, [
        (1, lambda app: post_key(pygame.K_ESCAPE)),
        (12, to_main_menu),
        (13, lambda app: post_key(pygame.K_RETURN)),
        (25, lambda app: post_key(pygame.K_LEFT)),
        (26, lambda app: post_key(pygame.K_RETURN)),                             # Yes
        (27, lambda app: seen.update(mode=app.shell.mode, calls=list(spy.calls))),
        (80, lambda app: seen.update(types=[type(s) for s in app.screens],
                                     mode_after=app.shell.mode,
                                     line=app.textbox.line)),
    ], last=90)
    assert run_from_start(game) == 0                     # the QUIT on the title quits at once
    assert seen["mode"] is Mode.ENDING
    assert ("stop_story_audio", 0.5) in seen["calls"]
    assert seen["types"] == [TitleScreen] and seen["mode_after"] is Mode.TITLE
    assert seen["line"] is None
    assert spy.calls[-2:] == [("take_music", "title"), ("play", "title.ogg", True, 0.0)]
    assert TitleScreen not in pumps


def test_ac57_quit_in_game_asks_then_a_second_close_quits(tmp_path, user_roots, scripted_app,
                                                         no_stage_yet):
    from engine.ui.builtin.confirm import ConfirmScreen

    game = make_game(tmp_path)
    seen: dict = {}

    def note(app):
        top = app.screens.top
        seen["asked"] = (app.running, type(top).__name__, getattr(top, "message", None),
                         isinstance(top, ConfirmScreen) and top.scope.focused is top.no_button)

    Steps(scripted_app, [
        (1, lambda app: post_key(pygame.K_LSHIFT)),               # last input: a key
        (2, lambda app: post(pygame.QUIT)),
        (12, note),                                               # still running
        (14, lambda app: post(pygame.QUIT)),                      # the second close
    ], last=10_000)
    assert run_from_start(game) == 0
    assert seen["asked"] == (True, "ConfirmScreen",
                             "Quit the game? Unsaved progress will be lost.", True)
    assert scripted_app.limiters[-1].frame < 100


def test_ac57_title_quit_exits_at_once(tmp_path, user_roots, scripted_app):
    game = make_game(tmp_path)
    posted: list[int] = []

    def close_on_the_title(app):
        if not posted and isinstance(app.screens.top, TitleScreen):
            posted.append(scripted_app.limiters[-1].frame)
            post(pygame.QUIT)

    for frame in range(2, 200):
        scripted_app.at(frame, close_on_the_title)
    scripted_app.quit_frame = 10_000
    assert launch(game) == 0
    assert posted and scripted_app.limiters[-1].frame == posted[0]    # no dialog


def test_ac57_a_forced_quit_never_asks(tmp_path, user_roots, scripted_app, no_stage_yet):
    game = make_game(tmp_path)
    Steps(scripted_app, [(2, lambda app: app.request_quit(force=True))], last=10_000)
    assert run_from_start(game) == 0
    assert scripted_app.limiters[-1].frame < 100


def test_ac57_the_error_screen_quits_with_1_without_the_guard(tmp_path, user_roots,
                                                              scripted_app, monkeypatch,
                                                              no_stage_yet):
    script = (TEMPLATE / "script" / "main.vns").read_text(encoding="utf-8")
    game = make_game(tmp_path, script=script.replace('    "End."\n', "    $ 1 / 0\n"))
    calls = []
    real_guard = GameShell.quit_guard
    monkeypatch.setattr(GameShell, "quit_guard",
                        lambda self: calls.append(1) or real_guard(self))
    Steps(scripted_app, [(2, lambda app: post_key(pygame.K_SPACE)),        # completes the line
                         (4, lambda app: post_key(pygame.K_SPACE))], last=60)  # advances
    assert run_from_start(game) == 1
    assert isinstance(scripted_app.apps[-1].screens.top, ErrorScreen) and calls == []


def test_ac41_no_title_main_menu_yes_exits_0(tmp_path, user_roots, scripted_app, no_stage_yet):
    game = make_game(tmp_path, "[title]\nenabled = false")
    seen = {}

    def note(app):
        seen["message"] = getattr(app.screens.top, "message", None)

    Steps(scripted_app, [
        (1, lambda app: post_key(pygame.K_ESCAPE)),
        (12, to_main_menu),
        (13, lambda app: post_key(pygame.K_RETURN)),
        (24, note),
        (25, lambda app: post_key(pygame.K_LEFT)),
        (26, lambda app: post_key(pygame.K_RETURN)),
    ], last=10_000)
    assert launch(game) == 0
    assert seen["message"] == "Quit the game? Unsaved progress will be lost."
    assert scripted_app.limiters[-1].frame < 200


# --- Step 8 — the quick menu in the real app (AC-F10-49, 50, 51 App rows) ---------------------

def _quick_item(app, entry_id: str):
    found = app.shell.quick_menu.shown()
    return dict(zip((e.id for e in found.entries), found.layout.items, strict=True))[entry_id]


def _click(app, entry_id: str | None = None, pos=None) -> None:
    if pos is None:
        x, y = _quick_item(app, entry_id).box.center
        pos = (round(x), round(y))
    post(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)
    post(pygame.MOUSEBUTTONUP, pos=pos, button=1)


def test_step8_quick_menu_hide_and_menu_in_the_real_app(tmp_path, user_roots, scripted_app,
                                                       monkeypatch, no_stage_yet):
    from engine.ui.builtin.game_menu import GameMenuScreen

    game = make_game(tmp_path)
    posted: list = []
    real_post = RuntimeStoryDriver.post

    def spy_post(self, event):
        posted.append(event)
        return real_post(self, event)

    monkeypatch.setattr(RuntimeStoryDriver, "post", spy_post)
    seen: dict = {}

    def note(name):
        def take(app):
            fb = app.window.framebuffer()
            pill = app.shell.quick_menu.shown().layout.pill
            seen[name] = dict(hidden=app.textbox.hidden, shown=app.textbox.shown_count(),
                              types=[type(s) for s in app.screens], posted=len(posted),
                              fill=tuple(fb.get_at((round(pill.x) + 3, 704)))[:3],
                              pill=(pill.y, pill.bottom, pill.center[0]),
                              floor=app.shell.quick_menu.floor())
        return take

    Steps(scripted_app, [
        (2, note("typing")),
        (3, lambda app: _click(app, "hide")),
        (5, note("hidden")),
        (6, lambda app: _click(app, pos=(640, 400))),          # F05: shows the box again
        (8, lambda app: _click(app, "menu")),
        (9, note("menu")),
        (20, lambda app: post_key(pygame.K_ESCAPE)),
        (32, lambda app: _click(app, pos=(100, 704))),         # the strip off the pill: F05
        (34, note("after")),
    ], last=60)
    assert run_from_start(game) == 0
    typing, hidden, menu, after = (seen[k] for k in ("typing", "hidden", "menu", "after"))
    assert typing["pill"] == (690, 718, 640) and typing["floor"] == 686
    assert typing["fill"] == tuple(round(c * 0.9) for c in (0xFF, 0xF4, 0xF8))   # over black
    assert hidden["hidden"] is True and hidden["posted"] == 0
    assert hidden["shown"] <= typing["shown"] + 1                 # typing stopped when hidden
    assert menu["types"][-1] is GameMenuScreen and menu["posted"] == 0
    assert after["types"] == [StageScreen, TextboxScreen] and not after["hidden"]
    assert after["shown"] == len("Hello there, this line types slowly.")   # the click completed it


# --- AC-F10-65 — imports, state, and headless runs ------------------------------------------

def _subprocess(code: str) -> str:
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_ac65_pure_ui_modules_never_start_the_display():
    out = _subprocess(
        "import pygame\n"
        "from engine.ui import nav, focus, layouts, menus\n"
        "nav.NavReader(); focus.Box(0, 0, 1, 1)\n"
        "layouts.quick_menu_layout(['Hide', 'Menu'], lambda t, s: len(t) * s * 0.6)\n"
        "r = menus.MenuRegistry(); r.add('quick', menus.MenuEntry('hide')); r.shown('quick')\n"
        "print(pygame.display.get_init())\n")
    assert out.splitlines()[-1] == "False"


def test_ac65_a_headless_run_never_imports_the_shell_or_the_title():
    out = _subprocess(
        "import sys\n"
        "from pathlib import Path\n"
        "from engine.core.paths import GamePaths\n"
        "from engine.runtime.headless import run_headless\n"
        "from engine.script import load_story\n"
        f"paths = GamePaths.for_game(Path({str(TEMPLATE)!r}))\n"
        "commands = run_headless(load_story(paths).program, seed=42)\n"
        "assert commands, 'no commands'\n"
        "print(sorted(m for m in ('engine.ui.shell', 'engine.ui.builtin.title_screen',\n"
        "                         'engine.ui.builtin.quick_menu') if m in sys.modules))\n")
    assert out.splitlines()[-1] == "[]"


def test_ac65_menu_code_reads_no_clock_and_no_randomness():
    import ast

    names = ["nav", "focus", "widgets", "menu_screen", "shell", "builtin/quick_menu"]
    for name in names:
        path = REPO / "engine" / "ui" / f"{name}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                module = getattr(node, "module", None) or ""
                imported = [a.name for a in node.names]
                assert module not in ("time", "random") and not {"time", "random"} & set(
                    imported), (name, ast.dump(node))
            if isinstance(node, ast.Attribute) and node.attr == "get_ticks":
                raise AssertionError(f"{name}: pygame.time.get_ticks")


def test_ac65_menus_write_nothing_but_logs(tmp_path, user_roots, scripted_app, no_stage_yet):
    """AC-F10-38's flow (New Game, Hide, Main Menu → Yes, New Game) leaves no file under the
    write roots (the user folders, the temp folder, the game folder) except logs."""
    game = make_game(tmp_path)
    seen: dict = {}
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    Steps(scripted_app, [
        (2, lambda app: _click(app, "hide")),
        (4, lambda app: post_key(pygame.K_ESCAPE)),
        (15, to_main_menu),
        (16, lambda app: post_key(pygame.K_RETURN)),
        (28, lambda app: post_key(pygame.K_LEFT)),
        (29, lambda app: post_key(pygame.K_RETURN)),                 # Main Menu → Yes
        (90, lambda app: post_key(pygame.K_DOWN)),
        (91, lambda app: post_key(pygame.K_RETURN)),                 # New Game
        (130, lambda app: seen.update(types=[type(s) for s in app.screens],
                                      hidden=app.textbox.hidden)),
    ], last=140)
    assert run_from_start(game) == 0
    assert seen == {"types": [StageScreen, TextboxScreen], "hidden": False}
    new = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    assert all("logs" in p.relative_to(tmp_path).parts for p in new), sorted(new)


# --- AC-F10-70 — the example game -------------------------------------------------------------

def test_ac70_the_example_game(tmp_path, user_roots, scripted_app, monkeypatch):
    """``game/`` launched with ``--dev`` (an in-process dev launch of a copy): no WARNING
    (W64–W68 included); the title shows the configured background (the probe at (1000, 600)
    is the picture's pixel, not the gradient) and the logo, and takes the music stream for the
    configured file; buttons are drawn from the configured ``frame_image``. Keys alone reach
    the first line, open and close the game menu, and return to the title (Main Menu → Yes)."""
    import tomllib

    from engine.audio.service import AudioService, MusicHandle
    from engine.ui import paint
    from engine.ui.builtin.confirm import ConfirmScreen
    from engine.ui.builtin.game_menu import GameMenuScreen
    from tests.app.test_story_load_screen import copy_example, records
    from tests.fixtures.F10.make_example_ui import UI

    example = REPO / "game"
    shipped = {p.relative_to(example).as_posix() for p in (example / "gui").iterdir()
               if p.name != ".gitkeep"}
    assert shipped == set(UI)                     # make_example_ui.py draws every file
    config = tomllib.loads((example / "config.toml").read_text(encoding="utf-8"))["theme"]
    title_cfg, button_cfg = config["title"], config["button"]
    game = copy_example(tmp_path / "game")
    picture = pygame.image.load(str(game / title_cfg["background_image"]))
    logo = pygame.image.load(str(game / title_cfg["logo_image"]))
    solid = next((x, y) for y in range(logo.get_height()) for x in range(logo.get_width())
                 if logo.get_at((x, y)).a == 255 and sum(logo.get_at((x, y))[:3]) > 600)

    music: list = []
    real_take, real_play = AudioService.take_music, MusicHandle.play
    monkeypatch.setattr(AudioService, "take_music",
                        lambda self, owner: music.append(("take_music", owner))
                        or real_take(self, owner))
    monkeypatch.setattr(MusicHandle, "play", lambda self, file, **kw: music.append(
        ("play", file)) or real_play(self, file, **kw))
    images: set[str] = set()
    monkeypatch.setattr(paint.Painter, "_image", _recording(paint.Painter._image, images))

    seen: dict = {}

    def on_title(app) -> None:
        top = app.screens.top
        if "title" in seen or not (isinstance(top, TitleScreen) and top.in_t >= 1.0):
            return
        fb = app.window.framebuffer()
        seen["title"] = dict(
            probe=tuple(fb.get_at((1000, 600)))[:3],
            logo=tuple(fb.get_at((80 + solid[0], 48 + solid[1])))[:3],
            focused=top.scope.focused)
        seen["title_frame"] = scripted_app.limiters[-1].frame
        post_key(pygame.K_DOWN)                              # the first input focuses New Game

    def keys(app) -> None:
        frame = scripted_app.limiters[-1].frame
        if seen.get("title_frame") == frame - 1:
            post_key(pygame.K_RETURN)                        # New Game

    for frame in range(2, 260):
        scripted_app.at(frame, on_title)
        scripted_app.at(frame, keys)
    Steps(scripted_app, [
        (0, lambda app: seen.update(line=app.textbox.line.text, mode=app.shell.mode)),
        (2, lambda app: post_key(pygame.K_ESCAPE)),
        (14, lambda app: seen.update(menu=[type(s) for s in app.screens])),
        (15, lambda app: post_key(pygame.K_ESCAPE)),
        (28, lambda app: seen.update(closed=[type(s) for s in app.screens])),
        (30, lambda app: post_key(pygame.K_ESCAPE)),
        (42, to_main_menu),
        (43, lambda app: post_key(pygame.K_RETURN)),                         # Main Menu
        (55, lambda app: seen.update(confirm=type(app.screens.top))),
        (56, lambda app: post_key(pygame.K_LEFT)),
        (57, lambda app: post_key(pygame.K_RETURN)),                         # Yes
        (140, lambda app: seen.update(back=[type(s) for s in app.screens],
                                      mode_after=app.shell.mode)),
    ], last=600)                                  # F18: the prologue card comes first (5 s)
    assert launch(game) == 0
    app = scripted_app.apps[-1]

    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert problems == []
    title = seen["title"]
    expected = tuple(picture.get_at((1000, 600)))[:3]
    assert all(abs(a - b) <= 2 for a, b in zip(title["probe"], expected)), title["probe"]
    gradient = tuple(round(top + (bottom - top) * 600 / 720)          # the plain title there
                     for top, bottom in zip((0xFF, 0xF4, 0xF8), (0xFF, 0xD6, 0xE8)))
    assert sum(abs(a - b) for a, b in zip(title["probe"], gradient)) > 60
    assert all(abs(a - b) <= 2 for a, b in zip(title["logo"], logo.get_at(solid)[:3]))
    assert title["focused"] is None
    assert app.shell.theme.background.ref == title_cfg["background_image"]
    assert app.shell.theme.logo.ref == title_cfg["logo_image"]
    assert music[:2] == [("take_music", "title"), ("play", title_cfg["music"])]
    assert app.shell.theme.style("button", "normal").image.ref == button_cfg["frame_image"]
    assert button_cfg["frame_image"] in images

    assert seen["line"] == "The festival comes once a year, on the night the river runs slowest."
    assert seen["mode"] is Mode.GAME
    assert seen["menu"][-1] is GameMenuScreen
    assert seen["closed"] == [StageScreen, TextboxScreen]
    assert seen["confirm"] is ConfirmScreen
    assert seen["back"] == [TitleScreen] and seen["mode_after"] is Mode.TITLE
    assert music[-2:] == [("take_music", "title"), ("play", title_cfg["music"])]


def _recording(real, refs: set):
    """``Painter._image`` that notes the ref of every frame image it hands out."""
    def image(self, ref_image):
        if ref_image is not None:
            refs.add(ref_image.ref)
        return real(self, ref_image)
    return image
