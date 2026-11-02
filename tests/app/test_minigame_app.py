"""F23 s4 in the real App (App M, ``06`` §0.3): Template M with the Probe in
``game/minigames/``, on F05's App A loop (fake window and clock, 1/60 s)."""

import shutil
import sys
from pathlib import Path

import pygame
import pytest

from engine.minigames.screen import MinigameScreen
from engine.runtime.commands import MinigameDone, MinigameUsed, StartMinigame
from tests.fakes.text_app import Session, make_text_game

REPO = Path(__file__).resolve().parents[2]
F23 = REPO / "tests" / "fixtures" / "F23"
TEMPLATE_M = (F23 / "template" / "script" / "main.vns").read_text(encoding="utf-8")


@pytest.fixture
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture(autouse=True)
def plugin_modules():
    """The launch's plugin phase leaves ``_vn_minigames`` modules and its finder behind."""
    meta = list(sys.meta_path)
    before = {k for k in sys.modules if k.startswith("_vn_minigames")}
    for k in before:
        sys.modules.pop(k)
    yield
    sys.meta_path[:] = meta
    for k in [k for k in sys.modules if k.startswith("_vn_minigames")]:
        sys.modules.pop(k)


def m_game(root: Path, config: str = "[textbox]\ncps = 0\n") -> Path:
    root = make_text_game(root, script=TEMPLATE_M, config=config)
    (root / "minigames").mkdir()
    shutil.copy(F23 / "plugins" / "probe.py", root / "minigames" / "probe.py")
    return root


def behavior(s: Session):
    cls = s.app.minigames.get("probe").cls
    return sys.modules[cls.__module__].behavior


def top(s: Session):
    return s.app.screens.top


def test_milestone_plays_saves_rolls_back(tmp_path, user_roots, pygame_ready):
    """The s4 milestone (SPEC §6) in one App session, with the App rows of AC-F23-14 (F5
    while RUNNING holds ``k_M``), 31 (no say window drawn under it), 36 (skip ends at
    open), 37 (the cue's anchor), and 38 (the thumbnail is the opening picture)."""
    s = Session(m_game(tmp_path / "g"))
    seen: dict = {}

    def script(s: Session):
        yield from s.until_line("Before.")
        app = s.app
        behavior(s).grid = True
        behavior(s).use = {pygame.KEYDOWN}
        app.skip_auto.start_skip()
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: isinstance(top(s), MinigameScreen))
        seen["skip"] = app.skip_auto.skipping
        k_m = app.story.checkpoint().to_json()
        seen["checkpoint"] = k_m["minigame"]
        yield from s.until(lambda: top(s).s.phase.value == "running")
        session = top(s).s
        seen["cue"] = app.rollback_keys.cue.anchor() == session.frame.cue
        draws = []
        real_draw = app.textbox.draw
        app.textbox.draw = lambda canvas: (draws.append(1), real_draw(canvas))
        captured, titles = [], []
        saves = app.saves
        real_captured, real_title = saves._captured, saves._minigame_title_of
        saves._captured = lambda kind, slot, picture: (
            captured.append((picture, app.story.checkpoint().to_json())),
            real_captured(kind, slot, picture))
        saves._minigame_title_of = lambda state: (titles.append(real_title(state)),
                                                  titles[-1])[1]
        s.key(pygame.K_a)                                    # used: the counter shows 1
        yield
        s.key(pygame.K_F5)
        for _ in range(3):
            yield
        seen["draws"] = len(draws)
        app.textbox.draw = real_draw
        seen["save"] = (captured[0][0] is session.thumb, captured[0][1] == k_m, titles[0])
        behavior(s).use = set()
        s.key(pygame.K_DOWN)
        yield
        s.key(pygame.K_RIGHT)
        yield
        s.key(pygame.K_RETURN)
        yield from s.until_line("After {var=turns}.")
        seen["turns"] = app.story.interp.G["turns"]
        seen["cue_after"] = app.rollback_keys.cue._anchor is None
        s.event(pygame.MOUSEWHEEL, x=0, y=1, flipped=False, precise_x=0.0, precise_y=1.0)
        yield from s.until(lambda: isinstance(top(s), MinigameScreen))
        seen["landed"] = top(s).s.cmd.restored
        yield from s.until(lambda: top(s).s.phase.value == "running")
        s.event(pygame.MOUSEWHEEL, x=0, y=1, flipped=False, precise_x=0.0, precise_y=1.0)
        yield from s.until_line("Before.")
        seen["back"] = app.story.interp.G["turns"]
        seen["closed"] = app.minigame_host.session is None
        yield

    s.play(script)
    assert seen["skip"] is False
    assert seen["checkpoint"]["waiting"]["name"] == "probe"
    assert seen["cue"] is True and seen["cue_after"] is True
    assert seen["draws"] == 0
    assert seen["save"] == (True, True, "Probe game")
    assert seen["turns"] == 3
    assert seen["landed"] is True
    assert seen["back"] == 0 and seen["closed"] is True


# --- F23 s5b: AC-F23-28, 39, 40 (App rows) ------------------------------------------------------

def running_probe(s: Session, before=None):
    """Advance past "Before." into the Probe and wait until it runs (the fade-in done);
    ``before(behavior)`` runs at "Before."."""
    yield from s.until_line("Before.")
    if before is not None:
        before(behavior(s))
    s.key(pygame.K_SPACE)
    yield from s.until(lambda: isinstance(top(s), MinigameScreen)
                       and top(s).s.phase.value == "running")


class AudioSpy:
    """F08's service as F16 and the host use it: ``set_volumes`` recorded; the rest
    accepted."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def set_volumes(self, *volumes) -> None:
        self.calls.append(("set_volumes", volumes))

    def play_ui(self, file, *, volume=100, owner=None) -> None:
        self.calls.append(("play_ui", file, volume, owner))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **kwargs: None


def test_ac28_settings_reach_the_plugin(tmp_path, user_roots, pygame_ready):
    from engine.app.settings import install_settings_ui
    from engine.core.config_schema import AudioConfig
    from engine.ui.builtin.game_menu import GameMenuScreen
    from tests.app.test_settings_service import make as make_settings
    s = Session(m_game(tmp_path / "g"))
    seen: dict = {}
    audio = AudioSpy()

    def script(s: Session):
        def look(b):
            b.heading, b.hint = True, "Find the pairs"
            service = make_settings(tmp_path)                 # F16's service, as a launch has
            service.attach_audio(audio)
            s.app.settings = service
            install_settings_ui(s.app)

        yield from running_probe(s, look)
        app = s.app
        b = behavior(s)
        first = b.ctx.settings
        seen["first"] = (first.text_scale, first.reduce_motion, first.sound_volume)
        area = top(s).s.area
        s.key(pygame.K_ESCAPE)
        yield from s.until(lambda: isinstance(top(s), GameMenuScreen))
        app.settings.set("text_size_pct", 150)
        mark = len(b.calls)
        s.key(pygame.K_ESCAPE)
        yield from s.until(lambda: isinstance(top(s), MinigameScreen))
        for _ in range(3):
            yield
        after = b.calls[mark:]
        upto = next(i for i, c in enumerate(after) if c[0] == "update")
        seen["changed"] = [c[1].text_scale for c in after[:upto] if c[0] == "settings_changed"]
        seen["changed_all"] = len([c for c in after if c[0] == "settings_changed"])
        layouts = [c[1] for c in after[:upto] if c[0] == "layout"]
        session = top(s).s
        seen["layout"] = (layouts[-1] == session.frame.content, layouts[-1] != area)
        app.minigame_host.ports.audio = audio
        b.ctx.play_sound("sfx/flip.ogg")
        audio.calls.clear()
        app.settings.set("sound_volume", 50)
        seen["volumes"] = list(audio.calls)                 # in the same call: at once
        yield
        seen["learns"] = b.ctx.settings.sound_volume

    s.play(script)
    a = AudioConfig()
    assert seen["first"] == (1.0, False, a.sound_volume)
    assert seen["changed"] == [1.5] and seen["changed_all"] == 1
    assert seen["layout"] == (True, True)
    assert seen["volumes"] == [("set_volumes", (a.master_volume, a.music_volume, 50,
                                                a.voice_volume))]
    assert seen["learns"] == 50


def test_ac39_save_description(tmp_path, user_roots, pygame_ready):
    """The provider F11 asks first while the state waits at the minigame: the live
    registry's cleaned display title (``[words.plugin.<name>] title``, else declared, else
    the name); asked only with the wait's name; None for an unregistered name."""
    from engine.core.minigame_types import MinigameSig
    from engine.minigames.registry import PluginClass
    config = '[textbox]\ncps = 0\n[words.plugin.probe]\ntitle = "Lantern game"\n'
    s = Session(m_game(tmp_path / "g", config))
    seen: dict = {}

    def script(s: Session):
        yield from s.until_line("Before.")
        saves = s.app.saves
        provider = saves._minigame_title
        seen["none"] = saves._minigame_title_of(s.app.story.checkpoint())   # waiting null
        asked = []
        saves._minigame_title = lambda name: (asked.append(name), provider(name))[1]
        yield from running_probe(s)
        seen["words"] = saves._minigame_title_of(s.app.story.checkpoint())
        seen["asked"] = list(asked)
        seen["unregistered"] = provider("nope")
        registry = s.app.minigames
        probe = registry.get("probe")
        odd = MinigameSig(name="odd", title=chr(0xD800) + "x" * 300,
                          source="minigames/odd.py", args=(), test=None, skipped=None,
                          check=None)
        bare = MinigameSig(name="bare", title="bare", source="minigames/bare.py", args=(),
                           test=None, skipped=None, check=None)
        for sig in (odd, bare):
            registry._entries[sig.name] = PluginClass(sig, probe.cls, sig.source, "1.0",
                                                      False, {}, {})
        seen["odd"] = provider("odd")
        seen["bare"] = provider("bare")
        yield

    s.play(script)
    assert seen["none"] is None and seen["words"] == "Lantern game"
    assert seen["asked"] == ["probe"] and seen["unregistered"] is None
    assert seen["bare"] == "bare"
    assert seen["odd"] == chr(0xFFFD) + "x" * 199


SKIP_M = TEMPLATE_M.replace("    minigame probe pairs=6 into turns\n",
                            "    minigame probe skippable pairs=6 into turns\n"
                            "    \"Middle {var=turns}.\"\n"
                            "    minigame probe pairs=6 into turns\n")


def test_ac40_skip_game(tmp_path, user_roots, pygame_ready):
    from engine.ui.builtin.confirm import ConfirmScreen
    from engine.ui.builtin.game_menu import GameMenuScreen
    from engine.ui.nav import InputKind
    root = make_text_game(tmp_path / "g", script=SKIP_M,
                          config='[textbox]\ncps = 0\n[words]\nskip_minigame = "Passer"\n')
    (root / "minigames").mkdir()
    shutil.copy(F23 / "plugins" / "probe.py", root / "minigames" / "probe.py")
    assert SKIP_M.splitlines()[8] == "    minigame probe skippable pairs=6 into turns"
    s = Session(root)
    seen: dict = {}

    def menu_ids():
        return [e.id for e in top(s).entries]

    def script(s: Session):
        app = s.app
        yield from s.until_line("Before.")
        s.key(pygame.K_ESCAPE)                               # over the story: absent
        yield from s.until(lambda: isinstance(top(s), GameMenuScreen))
        seen["story"] = menu_ids()
        s.key(pygame.K_ESCAPE)
        yield from s.until(lambda: not isinstance(top(s), GameMenuScreen))
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: isinstance(top(s), MinigameScreen))
        app.shell.open_game_menu(InputKind.KEYS)             # during the fade-in: absent
        seen["fade"] = menu_ids()
        top(s).close()
        yield from s.until(lambda: isinstance(top(s), MinigameScreen)
                           and top(s).s.phase.value == "running")
        s.key(pygame.K_ESCAPE)
        yield from s.until(lambda: isinstance(top(s), GameMenuScreen))
        menu = top(s)
        seen["running"] = menu_ids()
        seen["label"] = menu.buttons[1].label()
        s.key(pygame.K_DOWN)
        yield
        s.key(pygame.K_RETURN)
        yield from s.until(lambda: isinstance(top(s), ConfirmScreen))
        confirm = top(s)
        yield
        seen["confirm"] = (confirm.message, confirm.scope.focused is confirm.no_button)
        s.key(pygame.K_ESCAPE)                               # No: back to Skip Game
        yield from s.until(lambda: top(s) is menu)
        yield
        seen["refocus"] = menu.scope.focused is menu.buttons[1]
        s.key(pygame.K_RETURN)
        yield from s.until(lambda: isinstance(top(s), ConfirmScreen))
        yield
        b = behavior(s)
        done = []
        real_post = app.story.post

        def post(event):
            if isinstance(event, MinigameDone):
                done.append((any(isinstance(x, GameMenuScreen) for x in app.screens),
                             len([c for c in b.calls if c[0] == "update"])))
            real_post(event)

        app.story.post = post
        s.key(pygame.K_LEFT)
        yield
        s.key(pygame.K_RETURN)                               # Yes
        yield
        updates = len([c for c in b.calls if c[0] == "update"])
        yield from s.until_line("Middle {var=turns}.")
        seen["done"] = (done, updates)
        seen["turns"] = app.story.interp.G["turns"]
        app.story.post = real_post
        s.key(pygame.K_SPACE)                                # not skippable: absent
        yield from s.until(lambda: isinstance(top(s), MinigameScreen)
                           and top(s).s.phase.value == "running")
        s.key(pygame.K_ESCAPE)
        yield from s.until(lambda: isinstance(top(s), GameMenuScreen))
        seen["plain"] = menu_ids()
        yield

    s.play(script)
    assert "skip_minigame" not in seen["story"] and "skip_minigame" not in seen["fade"]
    assert "skip_minigame" not in seen["plain"]
    assert seen["running"][:2] == ["return", "skip_minigame"] and seen["label"] == "Passer"
    assert seen["confirm"] == ("Skip this game and go on with the story?", True)
    assert seen["refocus"] is True
    done, updates = seen["done"]
    assert done == [(False, updates)]                       # menu gone; no update since Yes
    assert seen["turns"] == "skipped"
