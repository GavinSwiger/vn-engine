"""F57 step 2: Heartbeat played on Host U (F23's ``MinigameHost`` on F10's unit canvas, fake
clock 1/60 s, an Audio spy): AC-F57-04 (a full run), 06 (Skip Game and the test outcome), 07
(tokens, schemes, the beat sound), 09 (input and the paused clock) and 10 (docs)."""

import dataclasses
from pathlib import Path

import pygame
import pytest

from engine.core.minigame_types import MeterChange, Outcome
from engine.minigames import api
from engine.minigames.bundled import BUNDLED
from engine.minigames.bundled.heartbeat import TOKENS, WORDS, Heartbeat
from engine.minigames.bundled.heartbeat_rules import DEFAULTS
from engine.minigames.context import PlayerSettings
from engine.minigames.tables import engine_token
from engine.ui.focus import Box
from tests.fakes.ui_shell import SolidScreen, UiHarness
from tests.minigames.host_u import NAMES, HostU

H = UiHarness
REPO = Path(__file__).resolve().parents[3]
SOUND = "sfx/heartbeat.ogg"


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture
def world(game):
    return HostU(game)


def tap(key: int) -> tuple:
    return H.key(key), H.key(key, up=True)


SPACE, ENTER = tap(pygame.K_SPACE), tap(pygame.K_RETURN)


def open_hb(w: HostU, *, level: str = "normal", skippable: bool = False, **args) -> Heartbeat:
    """A fresh session (a cut) with ``args`` over the defaults, under Timing assist
    ``level``; ``g.finishes`` records ``ctx.finish``."""
    w.posted.clear()
    w.audio.calls.clear()
    w.ports.settings = lambda: PlayerSettings(timing_assist=level)
    cmd = dataclasses.replace(w.command("heartbeat", {**DEFAULTS, **args}),
                              skippable=skippable)
    w.host.start(cmd)
    assert not w.fatal, [f.format() for f in w.fatal]
    g = w.session.plugin
    port = w.session.ctx._port
    real = port.finish
    g.finishes = []

    def finish(result):
        g.finishes.append(result)
        return real(result)

    port.finish = finish
    return g


def until(w: HostU, g: Heartbeat, t: float, limit: int = 2000) -> None:
    """Frames until the game clock reaches ``t``."""
    for _ in range(limit):
        if g.t >= t - 1e-9:
            return
        w.frame()
    raise AssertionError(f"the clock stayed at {g.t}")


def sounds(w: HostU) -> list[str]:
    return [c[1] for c in w.audio.calls if c[0] == "play_ui" and c[1] == SOUND]


# --- AC-F57-04 ---------------------------------------------------------------------------------

def test_ac_f57_04_a_full_run(world):
    w = world
    g = open_hb(w, meter="hana")
    w.frame()
    assert g.circle_text() == "Ready…" and w.session.hint_text == WORDS["hint"]
    for k in range(1, 7):                         # beats at 1 + k s: hit the first six
        until(w, g, 1 + k - 0.05)
        w.frame(*SPACE)
        assert g.beats.marks[-1] is True and len(g.beats.marks) == k
    assert g.circle_text() in ("Steady", "")
    until(w, g, 9.3)                              # beats 7 and 8 pass with no press
    assert g.beats.marks == [True] * 6 + [False] * 2
    assert g.circle_text() == "6 of 8" and g.finishes == []
    start = g.t
    while not g.finishes:
        w.frame()
    assert g.t - start == pytest.approx(1.5, abs=0.04)
    assert g.finishes == [6]
    assert w.session.ledger.changes == (MeterChange("hana", "+=", -2),)

    # Cost 0, or no meter: no change. A press ends the result early.
    for more in (dict(meter="hana", cost=0), dict()):
        g = open_hb(w, **more)
        until(w, g, 9.3)
        assert g.beats.misses == 8 and g.finishes == []
        w.frame(*ENTER)
        assert g.finishes == [0] and w.session.ledger.changes == ()


# --- AC-F57-06 ---------------------------------------------------------------------------------

def test_ac_f57_06_skip_and_test_outcome(world):
    w = world
    entry = api.declarations(Heartbeat, "engine")
    assert entry.sig.skipped is not None and entry.sig.test is not None   # skippable is fine
    for kind in ("test", "skipped"):
        assert entry.sig.outcome(kind, {**DEFAULTS, "beats": 12, "meter": "hana"},
                                 NAMES) == Outcome(12)
    g = open_hb(w, skippable=True, beats=10, meter="hana")
    until(w, g, 2.5)                              # beat 1 missed: a pending miss
    assert w.host.can_skip()
    w.host.skip(w.session)
    w.frames(120)
    done = w.done()
    assert len(done) == 1 and done[0].result == 10 and done[0].changes == ()
    assert g.finishes == []
    g = open_hb(w, beats=5, meter="hana")
    until(w, g, 2.5)
    w.frame(H.key(pygame.K_F8, pygame.KMOD_SHIFT))
    w.frames(120)
    done = w.done()
    assert len(done) == 1 and done[0].result == 5 and done[0].changes == ()


# --- AC-F57-07 ---------------------------------------------------------------------------------

def _tables(tmp_path: Path, text: str):
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.minigames.tables import PluginTables
    root = tmp_path / f"cfg{len(list(tmp_path.iterdir()))}"
    root.mkdir()
    (root / "config.toml").write_text(text, encoding="utf-8")
    result = load_config(GamePaths.for_game(root))
    assert result.errors == [] and result.warnings == [], text
    config = result.config
    return config, PluginTables(config.theme.plugin, config.words.plugin, config.theme,
                                dev=True)


def test_ac_f57_07_tokens_schemes_and_sound(game, tmp_path):
    from engine.core.schemes import SCHEMES
    assert TOKENS == {
        "target.fill_color": "button.fill_color", "target.border_color": "button.border_color",
        "target.text_color": "button.text_color", "ring.line_color": "slider.fill_color",
        "hit_color": "button.focused.border_color",
        "miss_color": "button.disabled.text_color", "dot.empty_color": "button.border_color"}
    assert {"sakura", "pocket", "amber", "synthwave", "vaporwave", "groovy"} <= set(SCHEMES)
    for scheme in SCHEMES:
        config, tables = _tables(tmp_path, f'[theme]\npreset = "{scheme}"\n')
        w = HostU(game, config=config, tables=tables, cfg=config.theme)
        g = open_hb(w)
        for key, token in TOKENS.items():
            assert g.colors[key] == engine_token(config.theme, token), (scheme, key)
        w.frame()
    config, tables = _tables(tmp_path, '[theme.plugin.heartbeat]\nhit_color = "#123456"\n'
                                       '[theme.plugin.heartbeat.ring]\nline_color = "#ABCDEF"\n'
                                       '[words.plugin.heartbeat]\nhit = "Calm"\n')
    w = HostU(game, config=config, tables=tables, cfg=config.theme)
    g = open_hb(w)
    assert g.colors["hit_color"] == (0x12, 0x34, 0x56)
    assert g.colors["ring.line_color"] == (0xAB, 0xCD, 0xEF)
    assert g.word_text["hit"] == "Calm"

    # The sound: once per beat (Normal), once per ring's arrival (No time limits).
    w = HostU(game)
    g = open_hb(w, beats=4, sound=SOUND)
    until(w, g, 1.95)
    assert sounds(w) == []
    until(w, g, 2.05)
    assert sounds(w) == [SOUND]
    w.frame(*SPACE)                                # a hit: the sound is never the only cue
    until(w, g, 5.3)
    assert sounds(w) == [SOUND] * 4
    g = open_hb(w, level="off", beats=4, sound=SOUND)
    assert w.session.hint_text == WORDS["hint_wait"]
    until(w, g, 4.0)                               # ring 1 arrived at 2.0 and waits
    assert sounds(w) == [SOUND] and g.beats.marks == []
    w.frame(*SPACE)
    assert g.beats.marks == [True]
    until(w, g, g.beats.current.time + 0.05)
    assert sounds(w) == [SOUND] * 2


# --- AC-F57-09 ---------------------------------------------------------------------------------

def test_ac_f57_09_input_and_the_paused_clock(world):
    w = world
    g = open_hb(w)
    area = Box(*g._area())
    presses = {
        "click": (H.down(area.center), H.up(area.center)),
        "enter": ENTER, "space": SPACE,
        "a": (H.pad(pygame.CONTROLLER_BUTTON_A), H.pad(pygame.CONTROLLER_BUTTON_A, up=True)),
    }
    for k, (name, events) in enumerate(presses.items(), start=1):
        until(w, g, 1 + k)
        w.frame(*events)
        assert g.beats.marks[-1:] == [True] and len(g.beats.marks) == k, name
    # Right click, Esc, and a held key's repeat don't judge.
    g = open_hb(w)
    until(w, g, 1.9)
    w.frame(H.down(area.center, 3), H.up(area.center, 3))
    assert g.beats.marks == []
    w.frame(H.key(pygame.K_SPACE))                # held down: the first press judges ...
    assert g.beats.marks == [True]
    until(w, g, 2.9)
    w.frame(H.key(pygame.K_SPACE))                # ... a second KEYDOWN without a KEYUP is a repeat
    assert g.beats.marks == [True]
    w.frame(H.key(pygame.K_SPACE, up=True))
    w.frame(*SPACE)
    assert g.beats.marks == [True, True]
    used = g.handle_event(api.PluginEvent(H.key(pygame.K_ESCAPE), None))
    assert used is False and g.beats.marks == [True, True]
    # A covering screen (the game menu) stops the clock: no window passes under it.
    t = g.t
    cover = SolidScreen((10, 10, 10))
    w.shell.stack.push(cover)
    w.frames(300)
    assert g.t == t and len(g.beats.marks) == 2
    w.shell.stack.pop()
    w.frames(2)
    assert g.t == pytest.approx(t + 2 / 60)
    # A frame stall counts at most 0.1 s.
    w.host.call(g.update, 5.0)
    assert g.t == pytest.approx(t + 2 / 60 + 0.1)


# --- AC-F57-10 ---------------------------------------------------------------------------------

def test_ac_f57_10_docs_and_registration():
    assert BUNDLED.count(Heartbeat) == 1               # later games follow it
    text = (REPO / "docs" / "minigames.md").read_text(encoding="utf-8")
    names = text.split("names come with the engine:", 1)[1].split("Any others", 1)[0]
    assert "`heartbeat`" in names                     # F53 and later add their names here
    section = text.split("\n## Heartbeat\n", 1)[1].split("\n## ", 1)[0]
    for heading in ("### Arguments", "### Playing", "### When the arguments are refused",
                    "### Testing Heartbeat", "### Changing the look and the words"):
        assert heading in section, heading
    for word in ("Timing assist", "No time limits", "Reduce motion", "Skip Game"):
        assert word in section, word
    for key, value in WORDS.items():
        assert f'{key} = "{value}"' in section, key
    for key, token in TOKENS.items():
        assert f"| `{key}` | `{token}` |" in section, key
