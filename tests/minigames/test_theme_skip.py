"""F23 s5b — theme, words, the dev key, and the slow-frame warning in Host U (``06`` §0.3):
AC-F23-42, 43, 65. One test per AC, its rows inside. Skip Game and the App rows (AC-F23-28,
39, 40) are in ``tests/app/test_minigame_app.py``."""

import logging
from fractions import Fraction

import pygame
import pytest

from engine.core.config import load_config
from engine.core.minigame_types import MeterChange
from engine.core.paths import GamePaths
from engine.minigames import messages
from engine.minigames import screen as screen_module
from engine.minigames.host import Phase, minigame_look
from engine.minigames.tables import PluginTables
from engine.ui.nav import InputKind
from tests.fakes.ui_shell import ColumnMenu, UiHarness
from tests.minigames.host_u import HostU, load_plugins


H = UiHarness
SHIFT_F8 = H.key(pygame.K_F8, pygame.KMOD_LSHIFT)


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def handle_events(w: HostU) -> list:
    return [arg for name, arg in w.behavior.calls if name == "handle_event"]


def records(caplog, logger: str, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == logger and r.levelno == level]


# --- AC-F23-42 — Shift+F8 ------------------------------------------------------------------------

@pytest.mark.parametrize("row", ["running", "fade_in", "bare", "menu", "fade_out", "f8_alone",
                                 "ctrl_shift", "release"])
def test_ac42_shift_f8(game, caplog, row):
    caplog.set_level(logging.DEBUG)
    w = HostU(game, dev=row != "release")
    b = w.behavior
    b.reset()
    b.requests = [("points", "add", ("hana", 2))]           # pending: never posted (G2)
    if row == "bare":
        w.start("bare", {})
        w.frame()
        w.frame(SHIFT_F8)
        w.frames(30)
        assert w.done() == [] and w.session.phase is Phase.RUNNING
        assert w.shell.notices == [
            ("problem", 'Dev: "bare" has no test outcome, so Shift+F8 can\'t end it.')]
        return
    w.start(restored=row != "fade_in")
    if row == "fade_in":
        assert w.session.phase is Phase.OPENING
    else:
        w.frame()
    if row == "menu":
        w.shell.stack.push(ColumnMenu(w.shell, by=InputKind.KEYS, fade=False))
    if row == "fade_out":
        b.ctx.finish(4)
        w.host.call(lambda: None)                             # the pending finish closes
        assert w.session.phase is Phase.CLOSING
    before = len(handle_events(w))
    event = {"f8_alone": H.key(pygame.K_F8),
             "ctrl_shift": H.key(pygame.K_F8, pygame.KMOD_LSHIFT | pygame.KMOD_LCTRL)
             }.get(row, SHIFT_F8)
    w.frame(event)
    got = handle_events(w)[before:]
    w.frames(30)
    infos = records(caplog, "vn.plugin", logging.INFO)
    ends = [m for m in infos if "Shift+F8" in m]
    if row in ("running", "fade_in"):
        done = w.done()
        assert len(done) == 1 and done[0].result == 9
        assert done[0].changes == (MeterChange("hana", "+=", 1),)
        assert w.shell.notices == [("info", 'Dev: ended "Probe game" with its test outcome.')]
        assert len(ends) == 1 and "probe" in ends[0] and got == []
    elif row == "fade_out":
        assert [d.result for d in w.done()] == [4] and ends == [] and w.shell.notices == []
    elif row == "menu":
        assert w.done() == [] and ends == [] and got == [] and w.shell.notices == []
    elif row in ("f8_alone", "ctrl_shift"):
        assert len(got) == 1 and got[0].ui is event
        assert w.done() == [] and ends == [] and w.session.phase is Phase.RUNNING
    else:                                                     # release
        assert got == [] and w.done() == [] and w.shell.notices == [] and ends == []
        assert w.session.phase is Phase.RUNNING


# --- AC-F23-43 — theme and words configuration ---------------------------------------------------

def _config(tmp_path, text: str):
    root = tmp_path / "cfg"
    root.mkdir(exist_ok=True)
    (root / "config.toml").write_text(text, encoding="utf-8")
    return load_config(GamePaths.for_game(root))


def test_ac43_theme_and_words(game, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    # Row 1: [theme.minigame] values are used.
    result = _config(tmp_path, "[theme.minigame]\nfade_ms = 500\nstage_dim_opacity = 0.5\n"
                               "[theme.minigame.hint]\ntext_size = 30\n")
    assert result.errors == [] and result.warnings == []
    look = minigame_look(result.config.theme)
    assert (look.fade_ms, look.stage_dim_opacity, look.hint_text_size) == (500, 0.5, 30)
    registry = load_plugins(game)
    w = HostU(game, registry=registry, config=result.config)
    w.behavior.reset()
    w.behavior.hint = "Find the pairs"
    w.start(restored=False)
    assert w.session.fade_s == 0.5 and w.session.frame.hint_size == 30
    w.host.abandon()
    # Row 2: out of range → F01's usual config error.
    for text, error in [
        ("[theme.minigame]\nfade_ms = 1001\n", "[theme.minigame] fade_ms must be a whole "
                                               "number from 0 to 1000 (0 = cut), but found 1001"),
        ("[theme.minigame]\nfade_ms = -1\n", "but found -1"),
        ("[theme.minigame]\nstage_dim_opacity = 0.9\n",
         "[theme.minigame] stage_dim_opacity must be a number from 0.0 to 0.8"),
        ("[theme.minigame.hint]\ntext_size = 23\n",
         "[theme.minigame.hint] text_size must be a whole number from 24 to 36, but found 23"),
    ]:
        errors = [e.format() for e in _config(tmp_path, text).errors]
        assert len(errors) == 1 and error in errors[0], (text, errors)
    # Rows 3–6: the plugin's own tokens and words, checked at install.
    caplog.clear()
    result = _config(tmp_path,
                     "[theme.plugin.probe.card]\nback_color = \"#102030\"\nbackk_color = 1\n"
                     "[theme.plugin.prob]\nx = 1\n"
                     "[words.plugin.probe]\nhint = \"Trouve\"\n")
    assert result.errors == []
    tables = PluginTables(result.config.theme.plugin, result.config.words.plugin,
                          result.config.theme, dev=True)
    tables.check(registry.entries())
    seen = {}

    def on_start(ctx):
        seen["mine"] = (ctx.theme.mine("card.back_color"), ctx.words.mine("hint"),
                        ctx.words.mine("title"))

    w = HostU(game, registry=registry, config=result.config, tables=tables)
    w.behavior.reset()
    w.behavior.on_start = on_start
    w.start()
    assert seen["mine"] == ((0x10, 0x20, 0x30), "Trouve", "Probe game")
    warned = records(caplog, "vn.config", logging.WARNING)
    assert warned == [
        'config.toml, line 3: unknown key [theme.plugin.probe.card] backk_color — did you '
        'mean "back_color"?',
        "config.toml, line 4: unknown section [theme.plugin.prob] — did you mean "
        "[theme.plugin.probe]?"]
    caplog.clear()
    result = _config(tmp_path, "[theme.plugin.probe.card]\nback_color = \"red\"\n"
                               f"[words.plugin.probe]\nhint = \"{'x' * 201}\"\n")
    tables = PluginTables(result.config.theme.plugin, result.config.words.plugin,
                          result.config.theme, dev=False)
    tables.check(registry.entries())
    look = tables.look(registry.get("probe"))
    assert look.tokens["card.back_color"] == (0x20, 0x30, 0x40)
    assert look.words["hint"] == "Find the pairs"
    warned = records(caplog, "vn.config", logging.WARNING)
    assert warned[0] == ('config.toml, line 2: [theme.plugin.probe.card] back_color must be a '
                         'color like "#RRGGBB", but found the text "red", so the default is '
                         'used')
    assert warned[1].startswith("config.toml, line 4: [words.plugin.probe] hint must be text "
                                "of at most 200 characters") and len(warned) == 2
    # Row 7: the raw store's bounds are config errors.
    many = "".join(f"[theme.plugin.p{i}]\nx = 1\n" for i in range(257))
    keys = "[words.plugin.probe]\n" + "".join(f"k{i} = \"a\"\n" for i in range(201))
    for text, error in [
        (many, "[theme.plugin] must have at most 256 minigame tables, but found 257"),
        ("[theme.plugin.probe.a.b]\nc = 1\n", "[theme.plugin.probe.a.b] is nested too deeply"),
        (keys, "[words.plugin.probe] must have at most 200 keys, but found 201"),
        ("[theme.plugin.probe.card]\nback_color = [1]\n",
         "[theme.plugin.probe.card] back_color must be text, a number, or true or false, but "
         "found a list"),
    ]:
        errors = [e.format() for e in _config(tmp_path, text).errors]
        assert len(errors) == 1 and error in errors[0], (error, errors)
    # Row 8: the two words' defaults.
    words = _config(tmp_path, "").config.words
    assert words.skip_minigame == "Skip Game"
    assert words.confirm_skip_minigame == "Skip this game and go on with the story?"


# --- AC-F23-65 — slow-frame warning ------------------------------------------------------------

def _fake_clock(monkeypatch, step_ms: int) -> None:
    """Every ``perf_counter`` call in the screen moves ``step_ms`` on: update and draw each
    take ``step_ms`` (exact fractions, so 8 ms is 8 ms)."""
    ticks = [0]

    def perf_counter():
        ticks[0] += 1
        return Fraction(ticks[0] * step_ms, 1000)

    monkeypatch.setattr(screen_module, "perf_counter", perf_counter)


@pytest.mark.parametrize("row", ["slow", "at_budget", "release"])
def test_ac65_slow_frame(game, monkeypatch, caplog, row):
    caplog.set_level(logging.DEBUG)
    _fake_clock(monkeypatch, 4 if row == "at_budget" else 7)
    w = HostU(game, dev=row != "release")
    w.behavior.reset()
    w.start()
    w.frames(3)                                            # three slow frames
    w.host.abandon()
    w.start(run=2)                                         # a second run of the same game
    w.frames(3)
    warned = [r for r in caplog.records if getattr(r, "code", None) == "W162"]
    if row != "slow":
        assert warned == []
        return
    assert [r.getMessage() for r in warned] == [messages.w162_slow_frame("probe", 14)]
    assert warned[0].name == "vn.plugin" and warned[0].levelno == logging.WARNING
    assert warned[0].getMessage() == (
        "minigame probe took 14 ms to update and draw one frame, over 8 ms, so the game may "
        "stutter. Draw less each frame, or keep pictures that don't change instead of "
        "redrawing them.")
