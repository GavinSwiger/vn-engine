"""F30 step 5b — the first-launch question about the player's name: AC-F30-30 (the launch
slot after F33's warning, the answers, the quit guard, who is asked) and AC-F30-31 ("Allow"
can't be clicked through) (``01`` PR-F30-06, UI-F30-05; ``04`` §6.7; ``05`` SEC-F30-08, Q6).

The launch is a real ``GameShell`` from ``install_ui`` with ``install_fourthwall`` over the
small fake App of ``test_title.py`` (no frame loop), F16's real ``SettingsService`` (no
writer), and Reader Z. Frames run as ``App`` runs them: events, ``update``, draw on a
1280×720 canvas.
"""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from engine.app.fourthwall import install_fourthwall
from engine.app.menus import install_ui
from engine.app.settings import SettingsService
from engine.app.text_check import install_textbox
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.persist.settings_file import LoadedSettings, Outcome
from engine.ui.builtin.content_warning import ContentWarningScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.builtin.username_question import GroundScreen, UsernameQuestion
from engine.ui.input import UiEvent
from engine.ui.menu_screen import CursorKeeper, MenuScreen
from engine.ui.shell import Mode
from tests.fakes.ui_shell import UiHarness
from tests.fakes.username import Z, no_real_username, reader  # noqa: F401  (name guard)
from tests.ui.test_content_warning import warning_config
from tests.ui.test_title import FakeApp

pytestmark = pytest.mark.display

H = UiHarness
REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "tests" / "fixtures" / "F10" / "template_min"
ASK = ("This game can show your computer's user name in the story. It is never saved or "
       "sent anywhere. Allow it?")
OFFER = "[meta]\nusername = true\n"


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


class Launch:
    """One launch: the fake App with settings (``username_use`` = ``use``), the shell, F30's
    install, and the first screens on the stack."""

    count = 0

    def __init__(self, tmp_path: Path, config: str = OFFER, *, use: int = 0,
                 outcome: Outcome = Outcome.OK, start=None) -> None:
        Launch.count += 1
        root = Path(shutil.copytree(TEMPLATE, tmp_path / f"game{Launch.count}"))
        with (root / "config.toml").open("a", encoding="utf-8") as f:
            f.write("\n" + config + "\n")
        loaded = load_config(GamePaths.for_game(root))
        assert not loaded.errors, [e.format() for e in loaded.errors]
        from tests.render.conftest import make_assets

        self.app = FakeApp(loaded.config, make_assets(GamePaths.for_game(root)), start=start)
        self.app.settings = SettingsService(
            LoadedSettings({"username_use": use} if use else {}, outcome), loaded.config)
        install_textbox(self.app)
        self.shell = install_ui(self.app)
        self.shell.cursor = CursorKeeper(lambda visible: None)
        self.read = reader(Z)
        self.wall = install_fourthwall(self.app, read=self.read)
        self.h = UiHarness(self.shell)
        self.app.screens.replace_all(self.shell.initial_screens())

    @property
    def types(self) -> list[type]:
        return [type(s) for s in self.app.screens]

    @property
    def use(self) -> int:
        return self.app.settings.value("username_use")

    @property
    def question(self) -> UsernameQuestion:
        top = self.app.screens.top
        assert isinstance(top, UsernameQuestion), self.types
        return top

    def frame(self, *events, dt: float = 1 / 60) -> None:
        for event in events:
            self.app.screens.handle_event(event)
        self.app.screens.update(dt)
        h = self.h
        h.framebuffer.fill((0, 0, 0))
        h.canvas.bind(h.framebuffer, h.viewport, h.quality)
        self.app.screens.draw(h.canvas)

    def run(self, seconds: float, *events) -> None:
        """Frames of 50 ms for ``seconds``; ``events`` go in the first."""
        for i in range(round(seconds / 0.05)):
            self.frame(*(events if i == 0 else ()), dt=0.05)

    def through_warning(self) -> None:
        """F33's warning: in, wait, Continue (Enter), fade out: the question is pushed."""
        self.run(2.4)
        self.frame(H.key(pygame.K_RETURN), H.key(pygame.K_RETURN, up=True))
        self.run(0.3)

    def to_allow(self) -> None:
        self.frame(H.key(pygame.K_LEFT), H.key(pygame.K_LEFT, up=True))
        assert self.question.scope.focused is self.question.yes_button

    def enter(self) -> None:
        self.frame(H.key(pygame.K_RETURN), H.key(pygame.K_RETURN, up=True))


# --- AC-F30-30 — the first-launch question ---------------------------------------------------

def test_ac_f30_30_first_launch_question(tmp_path):
    # Launch: warning → Continue → ground + question (exact text, focus "Don't allow") →
    # an answer → the title.
    run = Launch(tmp_path, OFFER + warning_config())
    assert run.types == [ContentWarningScreen] and run.shell.mode is Mode.TITLE
    run.through_warning()
    assert run.types == [GroundScreen, UsernameQuestion] and run.shell.mode is Mode.TITLE
    q = run.question
    assert q.message == ASK
    assert (run.shell.words.get(q.yes_key), run.shell.words.get(q.no_key)) == \
        ("Allow", "Don't allow")
    assert q.scope.focused is q.no_button
    assert run.app.story.new_games == 0 and run.read.calls == 0
    run.enter()                                          # Enter at frame 1: "Don't allow"
    assert run.use == 1
    run.run(0.5)
    assert run.types == [TitleScreen] and run.read.calls == 0

    # Esc stores 1.
    run = Launch(tmp_path)
    run.frame()
    run.frame(H.key(pygame.K_ESCAPE), H.key(pygame.K_ESCAPE, up=True))
    assert run.use == 1

    # QUIT during the question: stored by the quit guard; the process quits.
    run = Launch(tmp_path)
    run.frame()
    run.app.request_quit()
    assert run.use == 1 and run.app.quits == 1

    # Focus to "Allow", Enter after 0.5 s: stores 2; the name source now gives the name.
    run = Launch(tmp_path)
    run.frame()
    run.to_allow()
    run.run(0.55)
    run.enter()
    assert run.use == 2
    run.run(0.5)
    assert run.types == [TitleScreen]
    assert run.wall.name_source() == Z and run.read.calls == 1

    # No warning configured: the question first, then the title.
    run = Launch(tmp_path)
    assert run.types == [GroundScreen, UsernameQuestion]

    # Already answered (1 or 2), the offer off, start options: no question.
    for launch in (Launch(tmp_path, use=1), Launch(tmp_path, use=2), Launch(tmp_path, ""),
                   Launch(tmp_path, start=SimpleNamespace(label="act2", values={}))):
        assert UsernameQuestion not in launch.types and GroundScreen not in launch.types
    assert Launch(tmp_path).wall.gate.due() is False     # once per session

    # A session-only settings file (W74/W75; W70's unreadable file likewise): asked at
    # every launch.
    for _ in range(2):
        run = Launch(tmp_path, outcome=Outcome.NO_FILE)
        assert UsernameQuestion in run.types
        run.frame()
        run.enter()
        assert run.use == 1


# --- AC-F30-31 — "Allow" can't be clicked through ----------------------------------------------

def test_ac_f30_31_allow_cannot_be_clicked_through(tmp_path, monkeypatch):
    # Enter held from the warning's last frame into the question: no answer.
    run = Launch(tmp_path, OFFER + warning_config())
    run.run(2.4)
    run.frame(H.key(pygame.K_RETURN))                    # held: no KEYUP yet
    run.run(0.3)
    q = run.question
    run.run(1.0, H.key(pygame.K_RETURN, up=True))
    assert q.answered is None and run.use == 0 and run.question is q

    # Mouse down on Continue, up over "Allow" in the question's first frame: no answer.
    run = Launch(tmp_path, OFFER + warning_config())
    run.run(2.4)
    warning = run.app.screens.top
    run.frame(H.motion(warning.continue_button.box.center),
              H.down(warning.continue_button.box.center))
    run.frame(H.key(pygame.K_RETURN), H.key(pygame.K_RETURN, up=True))
    run.run(0.3)
    q = run.question
    allow = q.yes_button.box.center
    run.frame(H.motion(allow), H.up(allow))
    run.run(1.0)
    assert q.answered is None and run.use == 0

    # A double click whose second click lands on "Allow" in the question's first frame
    # (before its first draw, and in the frame after it): no answer.
    run = Launch(tmp_path)
    q = run.question
    allow = q.yes_button.box.center
    for event in (H.motion(allow), H.down(allow), H.up(allow)):
        run.app.screens.handle_event(event)              # not drawn yet
    run.frame()
    run.frame(H.motion(allow), H.down(allow), H.up(allow))
    run.run(1.0)
    assert q.answered is None and run.use == 0

    # Focus on "Allow": Enter at 0.4 s of drawn time is ignored (and plays no click sound,
    # F30 s6); at 0.5 s stores 2 with the click.
    monkeypatch.setattr(MenuScreen, "activation_sound", lambda self: "click.ogg")
    run = Launch(tmp_path)
    sounds: list = []
    monkeypatch.setattr(run.shell, "play_ui", sounds.append)
    run.frame()
    run.to_allow()
    q = run.question
    run.frame(dt=0.4 - q.drawn_s)
    assert q.drawn_s == pytest.approx(0.4)
    run.frame(H.key(pygame.K_RETURN), dt=0.0)
    assert q.answered is None and run.use == 0 and run.app.screens.top is q
    assert "click.ogg" not in sounds
    run.frame(dt=0.1)
    assert q.drawn_s == pytest.approx(0.5)
    run.frame(H.key(pygame.K_RETURN), dt=0.0)
    assert run.use == 2 and sounds.count("click.ogg") == 1

    # "Don't allow", Esc, or QUIT in the first frame (before any draw): 1 at once.
    for answer in ("no", "esc", "quit"):
        run = Launch(tmp_path)
        q = run.question
        if answer == "no":
            no = q.no_button.box.center
            for event in (H.motion(no), H.down(no), H.up(no)):
                run.app.screens.handle_event(event)
        elif answer == "esc":
            run.app.screens.handle_event(H.key(pygame.K_ESCAPE))
        else:
            run.app.request_quit()
        assert run.use == 1 and q.answered is False, answer

    # Unfocused for 2 s: only drawn, focused time counts toward the 0.5 s.
    run = Launch(tmp_path)
    run.frame()
    run.to_allow()
    q = run.question
    lost = UiEvent(pygame.event.Event(pygame.WINDOWFOCUSLOST), None, False)
    gained = UiEvent(pygame.event.Event(pygame.WINDOWFOCUSGAINED), None, False)
    run.frame(lost)
    run.run(2.0)
    run.frame(gained)
    run.enter()
    assert q.answered is None and q.drawn_s < 0.1
    run.run(0.5)
    run.enter()
    assert run.use == 2
