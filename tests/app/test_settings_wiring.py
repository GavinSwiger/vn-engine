"""F16 story wiring (checklist step 3; ``04`` §5.5, §7.2, §7.3; ``07`` G8, G9, I-5, I-11):
AC-F16-09 (each change reaches its target), AC-F16-10 (reduce motion: one effective switch),
AC-F16-11 (reset settings), AC-F16-16 (settings are not story state), AC-F16-17 (values in
place before the first frame and sound).

Service S (06 §0.2): ``SettingsService`` on a ``FakeWindow`` and a fake clock, with
recording stand-ins for ``App.audio``, the textbox, the stage, the blips, and
``App.skip_auto``; every call and attribute set goes to one shared log, so order is
checked too. App F and Launch L are in-process ``bootstrap.launch`` runs (``scripted_app``).
"""

import json
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app.settings import SettingsService
from engine.audio.backend import NullMixer
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig, Config, EffectsConfig
from engine.core.lru import SizedLru
from engine.core.settings_schema import KEYS
from engine.persist.settings_file import FILE_NAME, encode_settings
from engine.render.effects import EffectSettings
from engine.ui.builtin.skip_auto import SkipAutoSettings
from engine.ui.builtin.textbox_screen import TextSettings
from engine.ui.shell import Mode
from tests.app.test_settings_service import Clock, FakeWriter, loaded
from tests.app.test_story_load_screen import make_game
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fake_window import FakeWindow
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display          # FakeWindow builds pygame Surfaces

A = AudioConfig()
MU, S, V, MI = A.music_volume, A.sound_volume, A.voice_volume, A.play_minimized
TWO_LINES = 'label start:\n    "Start."\n    "End."\n    return\n'


class Target:
    """A stand-in target: method calls and attribute sets are logged as ``(name, value)``."""

    def __init__(self, log: list, name: str) -> None:
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_name", name)

    def __setattr__(self, attr: str, value) -> None:
        self._log.append((f"{self._name}.{attr}", value))
        object.__setattr__(self, attr, value)

    def __getattr__(self, attr: str):
        if attr.startswith("_"):
            raise AttributeError(attr)
        return lambda *args: self._log.append((f"{self._name}.{attr}", args))


def rig(tmp_path, values=None, *, config=None, writer=None, window=None):
    """Service S after ``attach_audio`` and ``attach_story``; returns it, the shared log
    (cleared after the attach), and the attach's own log."""
    log: list = []
    window = window if window is not None else FakeWindow()
    service = SettingsService(loaded(tmp_path / "game" / "settings", values),
                              config or Config(), window=window, writer=writer,
                              clock=Clock(), game_root=tmp_path / "game")
    service.attach_audio(Target(log, "audio"))
    service.attach_story(textbox=Target(log, "textbox"), stage=Target(log, "stage"),
                         blips=Target(log, "blips"), skip_auto=Target(log, "skip_auto"))
    attached = list(log)
    log.clear()
    window.calls.clear()
    service.add_listener(lambda keys: log.append(("listener", keys)))
    return service, log, attached, window


def text(cps=None, instant=False, size=28, reduce=False) -> TextSettings:
    return TextSettings(cps=cps, instant=instant, text_size=size, reduce_motion=reduce)


# --- AC-F16-09 — each change reaches its target ---------------------------------------------------

AC09_ROWS = [
    ("master_volume", 50, [("audio.set_volumes", (50, MU, S, V))], []),
    ("audio_unfocused", False, [("audio.set_background", (False, MI))], []),
    ("voice_sustain", True, [("audio.set_voice_sustain", (True,))], []),
    ("mono", True, [("audio.set_mono", (True,))], []),
    ("text_cps", 80, [("textbox.settings", text(cps=80))], []),
    ("text_cps", 0, [("textbox.settings", text(instant=True))], []),     # G8: cps None
    ("text_size_pct", 130, [("textbox.settings", text(size=36))], []),
    ("text_blips", False, [("blips.set_enabled", (False,))], []),
    ("skip_all", True, [("skip_auto.settings", SkipAutoSettings(skip_all=True))], []),
    ("auto_scale_pct", 25, [("skip_auto.settings", SkipAutoSettings(auto_scale=0.25))], []),
    ("auto_scale_pct", 150, [("skip_auto.settings", SkipAutoSettings(auto_scale=1.5))], []),
    ("auto_scale_pct", 400, [("skip_auto.settings", SkipAutoSettings(auto_scale=4.0))], []),
    ("auto_wait_voice", False,
     [("skip_auto.settings", SkipAutoSettings(auto_wait_voice=False))], []),
    ("fullscreen", True, [], ["set_fullscreen"]),
    ("window_size", (1600, 900), [], []),
]


def test_ac09_each_change_reaches_its_target(tmp_path):
    # The attach pushes each group once; set_mono only when mono is on.
    _, _, attached, _ = rig(tmp_path)
    assert [name for name, _ in attached] == [
        "audio.set_volumes", "audio.set_background", "audio.set_voice_sustain",
        "textbox.settings", "stage.settings", "blips.set_enabled", "skip_auto.settings"]
    assert attached[0] == ("audio.set_volumes", (A.master_volume, MU, S, V))
    assert attached[3:] == [("textbox.settings", text()),
                            ("stage.settings", EffectSettings(reduce=False)),
                            ("blips.set_enabled", (True,)),
                            ("skip_auto.settings", SkipAutoSettings())]
    _, _, attached, _ = rig(tmp_path, {"mono": True, "music_volume": 40})
    assert [name for name, _ in attached][:4] == [
        "audio.set_volumes", "audio.set_background", "audio.set_voice_sustain",
        "audio.set_mono"]
    assert attached[0][1] == (A.master_volume, 40, S, V)

    # Each row: exactly its calls, once, then the listener once.
    for key, value, calls, window_calls in AC09_ROWS:
        service, log, _, window = rig(tmp_path)
        service.set(key, value)
        assert log == calls + [("listener", frozenset({key}))], key
        assert window.calls == window_calls, key
        assert service.value(key) == value, key

    # No audio device, no blips, no skip/auto, no story objects: stored still changes.
    service = SettingsService(loaded(tmp_path / "game" / "settings"), Config(),
                              window=FakeWindow(), clock=Clock(), game_root=tmp_path / "game")
    audio = AudioService(None, SizedLru(1 << 20), AudioConfig(), backend=NullMixer())
    service.attach_audio(audio)
    service.attach_story(blips=None, skip_auto=None)
    for key, value, _, _ in AC09_ROWS:
        service.set(key, value)
        assert service.stored[key] == value, key
    assert audio.volumes.master == 50 and audio.mono is True


# --- AC-F16-10 — reduce motion: one effective switch ---------------------------------------------

def test_ac10_reduce_motion_is_one_effective_switch(tmp_path):
    service, log, _, _ = rig(tmp_path)
    for value in (True, False, True):
        service.set("reduce_motion", value)
    stage = [(n, v) for n, v in log if n.startswith("stage.")]
    assert stage == [("stage.settings", EffectSettings(reduce=True)), ("stage.drop_effects", ()),
                     ("stage.settings", EffectSettings(reduce=False)),
                     ("stage.settings", EffectSettings(reduce=True)), ("stage.drop_effects", ())]
    assert [v.reduce_motion for n, v in log if n == "textbox.settings"] == [True, False, True]

    # G9: attached with the flag already on, no drop_effects().
    _, _, attached, _ = rig(tmp_path, {"reduce_motion": True})
    assert ("stage.settings", EffectSettings(reduce=True)) in attached
    assert not [n for n, _ in attached if n == "stage.drop_effects"]

    # [effects] reduce = true: locked on; the player value changes nothing on the stage.
    config = Config(effects=EffectsConfig(reduce=True))
    service, log, attached, _ = rig(tmp_path, config=config)
    assert ("stage.settings", EffectSettings(reduce=True)) in attached
    assert service.value("reduce_motion") is False and service.effective_reduce() is True
    assert service.locked("reduce_motion") is True
    for value in (True, False, True, False):
        service.set("reduce_motion", value)
    assert not [n for n, _ in log if n.startswith("stage.")]
    assert all(v.reduce_motion is True for n, v in log if n == "textbox.settings")


# --- AC-F16-11 — reset settings -------------------------------------------------------------------

def test_ac11_reset_settings(tmp_path):
    writer, window = FakeWriter(), FakeWindow()
    window.set_fullscreen(True)
    values = {"music_volume": 40, "reduce_motion": True, "text_size_pct": 130,
              "fullscreen": True}
    service, log, _, window = rig(tmp_path, values, writer=writer, window=window)
    service.reset()
    assert service.stored == {}
    assert all(service.value(key) == service.defaults[key] for key in KEYS)
    names = [n for n, _ in log if n != "listener"]
    assert sorted(names) == ["audio.set_volumes", "stage.settings", "textbox.settings"]
    assert ("audio.set_volumes", (A.master_volume, MU, S, V)) in log
    assert ("textbox.settings", text()) in log
    assert ("stage.settings", EffectSettings(reduce=False)) in log
    # FakeWindow logs set_fullscreen(False) as "set_windowed".
    assert window.calls == ["set_windowed"] and window.fullscreen is False
    service.update(1.0)
    [(_, job)] = writer.fake.submitted
    assert json.loads(job.pieces[0]) == {"format": 2, "values": {}}


# --- AC-F16-16 — settings are not story state -----------------------------------------------------

STORED = {"music_volume": 40, "text_size_pct": 130}


def settings_game(tmp_path: Path, extra: str = "") -> Path:
    game = make_game(tmp_path, {"main.vns": TWO_LINES}, title=True)
    with (game / "config.toml").open("a", encoding="utf-8") as f:
        f.write("[textbox]\ncps = 0\n" + extra)
    (game / "settings").mkdir()
    (game / "settings" / FILE_NAME).write_bytes(encode_settings(STORED))
    return game


def launch(game: Path) -> int:
    return bootstrap.launch(game, release=False, bench_seconds=None,
                            log_level_override=None, pygame_warning=None)


def on_title(app) -> bool:
    shell = app.shell
    return (not app.loading and shell is not None and shell.mode is Mode.TITLE
            and app.story is not None)


def test_ac16_settings_are_not_story_state(tmp_path, user_roots, scripted_app, monkeypatch):
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", False)
    game = settings_game(tmp_path)
    file = game / "settings" / FILE_NAME
    before = file.read_bytes()
    seen: dict = {"phase": 0, "checks": []}
    names = [f'"{key}"' for key in KEYS]

    def check(app, label):
        values = {key: app.settings.value(key) for key in KEYS}
        seen["checks"].append((label, dict(app.settings.stored), values, file.read_bytes()))

    def step(app):
        phase = seen["phase"]
        if phase == 0 and on_title(app):
            seen["values"] = {key: app.settings.value(key) for key in KEYS}
            app.shell.start_new_game()                                   # New Game
            check(app, "new game")
            seen["phase"] = 1
        elif phase == 1 and app.textbox.line is not None:
            seen["first"] = app.story.checkpoint()
            seen["line"] = app.textbox.line
            post_key(pygame.K_SPACE)
            seen["phase"] = 2
        elif phase == 2 and app.textbox.line is not seen["line"]:
            state = seen["first"]
            seen["json"] = json.dumps(app.story.checkpoint().to_json())
            assert app.story.restore(state).result.name == "OK"         # a GameState restore
            check(app, "restore")
            assert app.story.restore(state).result.name == "OK"         # rollback stand-in
            check(app, "rollback")
            app.shell.return_to_title()                                  # Main Menu
            check(app, "main menu")
            app.persist.store.reset()                                    # App.persist reset()
            app.persist.update(app.clock())
            check(app, "persist reset")
            seen["phase"] = 3

    for frame in range(2, 300):
        scripted_app.at(frame, step)
    scripted_app.quit_frame = 300
    assert launch(game) == 0
    assert seen["phase"] == 3, seen["phase"]
    for label, stored, values, data in seen["checks"]:
        assert stored == STORED and values == seen["values"] and data == before, label
    assert file.read_bytes() == before
    assert not [n for n in names if n in seen["json"]]
    persistent = game / "persistent" / "persistent.json"
    if persistent.exists():
        assert not [n for n in names if n in persistent.read_text(encoding="utf-8")]


# --- AC-F16-17 — values in place before the first frame and sound ---------------------------------

def test_ac17_values_in_place_before_the_first_frame_and_sound(tmp_path, user_roots,
                                                              scripted_app, monkeypatch):
    game = settings_game(tmp_path, '[theme.title]\nmusic = "title.ogg"\n')
    (game / "settings" / FILE_NAME).write_bytes(encode_settings(
        {"music_volume": 40, "mono": True, "text_size_pct": 130, "reduce_motion": True}))
    order: list[tuple] = []
    for name in ("set_volumes", "set_mono", "take_music"):
        real = getattr(AudioService, name)
        monkeypatch.setattr(AudioService, name,
                            lambda self, *a, _real=real, _name=name:
                            order.append((_name, a)) or _real(self, *a))
    state: dict = {}
    with spy_draw_text(monkeypatch) as draws:
        def mark(app):
            if "title" in state:
                state.setdefault("end", len(draws))
            elif on_title(app):
                state["title"] = len(draws)
                state["stage"] = app.stage_screen.settings
                state["text"] = app.textbox.settings

        for frame in range(2, 200):
            scripted_app.at(frame, mark)
        scripted_app.quit_frame = 200
        assert launch(game) == 0
        first_title = draws[state["title"]:state["end"]]

    names = [n for n, _ in order]
    assert "take_music" in names
    first_take = names.index("take_music")
    assert ("set_volumes", (A.master_volume, 40, S, V)) in order[:first_take]
    assert ("set_mono", (True,)) in order[:first_take]
    assert all(a[1] == 40 for n, a in order if n == "set_volumes")   # never config music
    assert state["stage"] == EffectSettings(reduce=True)
    assert state["text"].text_size == 36 and state["text"].reduce_motion is True
    labels = [call.font.size for call in first_title if call.text == "New Game"]
    assert labels and all(size == 36 for size in labels)            # 28 at 130%
