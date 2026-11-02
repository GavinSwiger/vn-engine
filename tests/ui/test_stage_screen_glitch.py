"""F28 step 4 — glitches on ``StageScreen``: bursts with the story, the flash limit, reduced
effects, freezes and sizes, restores and skip, and drawing failures (``06-acceptance.md``
§1.4).

Two harnesses (06 §0.3): **App A** (``tests/fakes/text_app.Session``: the real ``App`` on a
``FakeWindow``, a fake clock of exactly 1/60 s per frame, ``install_story``) for the rows that
need the story, and **Screen L** (``tests/render/glitch_screen.L``) fed commands directly for
the rest. In App A the layer's drawing is spied on per frame (tear bands, static strength,
jittered tags); frame numbers are the presented frame's, so a line's arrival frame is the
frame its glyph 0 is drawn in.

Deviation (lean, 07 G10 closed): AC-F28-20's rows run in Screen L on the commands a load,
a rollback, skip, and New Game send (``ShowStage(restored)`` and ``Glitch(restored)``,
``drop_effects``, ``clear``); step 3's AC-F28-12 proves the runtime sends them.

AC-F28-15, 17, 18, 19, 20, 22.
"""

import logging
from collections import defaultdict
from pathlib import Path

import pygame
import pytest

from engine.render import glitch as glitch_module
from engine.render.canvas import RenderQuality
from engine.render.effects import EffectSettings, RefusalLog, W61_SIDS_MAX
from engine.render.glitch import band_rows, jitter_offset, tear_bands
from engine.runtime.commands import Flash, Glitch, ShowStage
from engine.runtime.glitch import ALL_STOPS
from engine.ui.screen import Screen
from tests.fakes.privacy import check_p
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen
from tests.render.glitch_screen import (GRAIN_REF, GREEN, HANA, YELLOW, L, burst, grain, lasting,
                                        on, stage)

pytestmark = pytest.mark.display

HEAD = ('define hana = Character("Hana")\nlabel start:\n    scene bg grain\n'
        '    show hana happy at center\n')
W182_TEXT = ("the glitch from this line wasn't shown, because the game shows at most 3 flashes "
             "a second to protect players who are sensitive to flashing.")


def codes(caplog, code: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "code", None) == code]


def raw(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


# --- App A with a spy on the layer's drawing ----------------------------------------------------

class GPlay:
    """One App A run of ``HEAD`` + ``body``. Each line is pressed ``hold`` frames after it
    arrives (``holds`` per line overrides it). ``drawn[frame]`` holds what the layer drew:
    ``tear`` (the bands), ``static`` (the strength), ``jitter`` (tag → device offset)."""

    def __init__(self, root: Path, body: str, config: str = "", *, hold: int = 40,
                 holds: dict[str, int] | None = None) -> None:
        self.root = make_text_game(root, script=HEAD + body, config=config)
        gen.write(self.root, {GRAIN_REF: grain(),
                              gen.ref_of("hana happy"): gen.block(300, 600, GREEN),
                              gen.ref_of("daichi grin"): gen.block(300, 600, YELLOW)})
        self.s = Session(self.root)
        self.hold, self.holds = hold, holds or {}
        self.drawn: dict[int, dict] = defaultdict(lambda: {"tear": None, "static": None,
                                                           "jitter": {}})
        self.arrival: dict[str, int] = {}
        self.admits: list[tuple[int, bool]] = []

    def run(self, monkeypatch) -> "GPlay":
        s = self.s

        def script(s: Session):
            yield from s.until(lambda: s.app.stage_screen is not None and s.textbox is not None)
            self._spy(monkeypatch)
            last, pressed = None, None
            for _ in range(3000):
                yield
                line, f = s.line_text(), s.frame - 1
                if line is not None and line != last:
                    self.arrival[line] = f
                    last = line
                if line == "End.":
                    return
                if line is not None and pressed != line \
                        and f - self.arrival[line] >= self.holds.get(line, self.hold) - 1:
                    s.key(pygame.K_SPACE)
                    pressed = line
            raise AssertionError("End. not reached")

        s.play(script)
        return self

    def _spy(self, monkeypatch) -> None:
        s, screen = self.s, self.s.app.stage_screen
        layer, view, limiter = screen.glitches, screen.view, screen.limiter
        real_tear, real_noise = glitch_module.draw_tear, layer.noise.draw
        real_copy, real_admit = view.draw_sprite_copy, limiter.admit

        def tear(surface, bands, sx, sy):
            self.drawn[s.frame]["tear"] = bands
            real_tear(surface, bands, sx, sy)

        def noise(surface, strength, offset):
            self.drawn[s.frame]["static"] = round(strength, 4)
            real_noise(surface, strength, offset)

        def copy(surface, tag, offset):
            result = real_copy(surface, tag, offset)
            if result:
                self.drawn[s.frame]["jitter"][tag] = offset
            return result

        def admit(now, *, reduced):
            result = real_admit(now, reduced=reduced)
            self.admits.append((s.frame, result))
            return result

        monkeypatch.setattr(glitch_module, "draw_tear", tear)
        layer.noise.draw = noise
        view.draw_sprite_copy = copy
        limiter.admit = admit

    def frames_of(self, line: str, count: int) -> list[dict]:
        start = self.arrival[line]
        return [self.drawn[f] for f in range(start, start + count)]


# --- AC-F28-15 — bursts start with the moment and outlive the line ------------------------------

WALK = """\
    effect tear 0.4
    hana "A."
    effect static on
    hana "B."
    effect static large 0.5
    hana "C."
    effect static off
    effect static large 2.0
    hana "D."
    effect static off
    hana "E."
    effect tear on
    effect static on
    effect jitter hana on
    hana "F."
    effect off
    hana "G."
    effect jitter hana 0.5
    show daichi grin at left
    effect jitter daichi on
    hana "H."
    "End."
"""


def test_ac_f28_15_bursts_start_with_the_moment_and_outlive_the_line(tmp_path, monkeypatch):
    cps = "[textbox]\ncps = 40\n"
    p = GPlay(tmp_path / "walk", WALK, cps).run(monkeypatch)
    a = p.arrival["A."]
    torn = sorted(f for f, d in p.drawn.items() if d["tear"] is not None and f < p.arrival["F."])
    assert torn == list(range(a, a + 24))                      # 0.4 s from glyph 0's frame
    assert all(d["static"] == 0.30 for d in p.frames_of("B.", 40))
    assert [d["static"] for d in p.frames_of("C.", 40)] == [0.50] * 30 + [0.30] * 10
    assert all(d["static"] == 0.50 for d in p.frames_of("D.", 40))
    assert all(d["static"] is None for d in p.frames_of("E.", 40))   # ends in E's arrival
    assert all(d["tear"] and d["static"] == 0.30 and set(d["jitter"]) == {"hana"}
               for d in p.frames_of("F.", 40))
    assert all(d["tear"] is None and d["static"] is None and not d["jitter"]
               for d in p.frames_of("G.", 40))
    both = [d["jitter"] for d in p.frames_of("H.", 30)]
    assert all(set(j) == {"hana", "daichi"} for j in both)
    hana_moves = [j["hana"] for j in both]
    daichi_moves = [j["daichi"] for j in both]
    assert len(set(hana_moves)) > 1 and len(set(daichi_moves)) > 1
    assert hana_moves != daichi_moves                          # each with its own offsets

    # "A." pressed at its frame 12: "B." arrives as in the control (the press is posted in
    # the same frame), and the tear runs on through frame 23.
    body = '    effect tear 0.4\n    hana "A."\n    hana "B."\n    "End."\n'
    p = GPlay(tmp_path / "press", body, cps, holds={"A.": 13}).run(monkeypatch)
    c = GPlay(tmp_path / "ctl", body.replace("    effect tear 0.4\n", ""), cps,
              holds={"A.": 13}).run(monkeypatch)
    assert p.arrival == c.arrival and [f for f, _ in p.s.posted] == [f for f, _ in c.s.posted]
    a = p.arrival["A."]
    assert sorted(f for f, d in p.drawn.items() if d["tear"]) == list(range(a, a + 24))
    assert p.arrival["B."] < a + 23

    # [effects] glitch = 1.2, glitch_size = "large": 72 frames, |dx| in [24, 96] units.
    config = cps + '[effects]\nglitch = 1.2\nglitch_size = "large"\n'
    p = GPlay(tmp_path / "config", '    effect tear\n    hana "A."\n    "End."\n', config,
              hold=90).run(monkeypatch)
    a = p.arrival["A."]
    torn = sorted(f for f, d in p.drawn.items() if d["tear"])
    assert torn == list(range(a, a + 72))
    assert all(24 <= abs(b.dx) <= 96 for f in torn for b in p.drawn[f]["tear"])


# --- AC-F28-17 — bursts and the flash limit (W182) ----------------------------------------------

class Admits:
    """Spies on ``StageScreen.limiter.admit``."""

    def __init__(self, rig: L) -> None:
        self.calls: list[bool] = []
        real = rig.screen.limiter.admit

        def admit(now, *, reduced):
            result = real(now, reduced=reduced)
            self.calls.append(result)
            return result

        rig.screen.limiter.admit = admit


def _static_strength(rig: L) -> list[float | None]:
    """Wrap the noise: each frame's static strength (None: none drawn)."""
    seen: list[float | None] = []
    real = rig.layer.noise.draw

    def draw(surface, strength, offset):
        seen[-1] = round(strength, 4)
        real(surface, strength, offset)

    rig.layer.noise.draw = draw
    real_frame = rig.frame

    def frame():
        seen.append(None)
        return real_frame()

    rig.frame = frame
    return seen


def test_ac_f28_17_bursts_and_the_flash_limit(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    # App A: six `effect tear 0.2` lines pressed every 18 frames; burst 4 is refused (W182
    # at its line, once), 1–3, 5, 6 are drawn.
    body = "".join(f'    effect tear 0.2\n    "N{i}."\n' for i in range(1, 7)) + '    "End."\n'
    p = GPlay(tmp_path / "strobe", body, "[textbox]\ncps = 0\n", hold=18).run(monkeypatch)
    torn = {line: sum(1 for d in p.frames_of(line, 18) if d["tear"])
            for line in (f"N{i}." for i in range(1, 7))}
    assert torn == {"N1.": 12, "N2.": 12, "N3.": 12, "N4.": 0, "N5.": 12, "N6.": 12}
    records = codes(caplog, "W182")
    assert [r.getMessage() for r in records] == [f"script/main.vns, line 11: {W182_TEXT}"]
    check_p([r.getMessage() for r in records], home=Path.home(), game=p.root)
    assert len(p.admits) == 6
    caplog.clear()

    def strobe(name: str, *, reduce: bool = False) -> tuple[L, Admits, list]:
        rig = L(tmp_path / name, reduce=reduce)
        rig.show(stage(HANA))
        rig.frame()
        return rig, Admits(rig), _static_strength(rig)

    # Three flashes, then `effect static 0.5`: one shared limit, refused, W182.
    rig, admits, strength = strobe("flash")
    for i in range(3):
        rig.screen.flash(Flash(None, 0.1, f"f{i}"))
        rig.frames(6)
    rig.screen.glitch(burst("static", None, 0.5, sid="st"))
    rig.frames(30)
    assert admits.calls == [True, True, True, False] and set(strength) == {None}
    assert len(codes(caplog, "W182")) == 1

    # tear 0.2 + static 0.3 + colorshift 0.5 in each of 4 moments: one admit per command.
    rig, admits, strength = strobe("three")
    for i in range(4):
        rig.screen.glitch(Glitch(lasting(), bursts=tuple(
            burst(kind, None, s, sid=f"m{i}{kind}").bursts[0]
            for kind, s in (("tear", 0.2), ("static", 0.3), ("colorshift", 0.5)))))
        rig.frames(18)
    assert admits.calls == [True, True, True, False]
    assert strength[54:72] == [None] * 18 and strength[36] == 0.30

    # Not counted: ten jitter bursts, six 1 s tears, and nothing drawn under reduce.
    for name, kind, seconds, reduce in (("jit", "jitter", 0.2, False),
                                        ("long", "tear", 1.0, False),
                                        ("calm", "tear", 0.2, True)):
        rig, admits, _ = strobe(name, reduce=reduce)
        for i in range(10):
            rig.screen.glitch(burst(kind, None, seconds, tag="hana" if kind == "jitter"
                                    else None, sid=f"{name}{i}"))
            rig.frames(18)
        assert admits.calls == [], name

    # Six `effect static on`/`off` pairs: at most 3 shown changes a second, the last target
    # reached, no W182 (07 I-5).
    caplog.clear()
    rig, admits, strength = strobe("pairs")
    for i in range(12):
        rig.screen.glitch(on(("static", None)) if i % 2 == 0 else on())
        rig.frames(18)
    rig.frames(60)
    shown = [s is not None for s in strength]
    changes = [f for f in range(1, len(shown)) if shown[f] != shown[f - 1]]
    assert all(sum(1 for c in changes if f <= c < f + 60) <= 3 for f in range(len(shown)))
    assert not shown[-1] and len(changes) >= 6 and not codes(caplog, "W182")

    # A refused `effect static large 0.3` over a lasting `static small`: the small static
    # goes on unchanged.
    rig, admits, strength = strobe("over")
    rig.screen.glitch(on(("static", "small")))
    rig.frames(6)
    for i in range(3):
        rig.screen.flash(Flash(None, 0.1, f"g{i}"))
        rig.frames(6)
    rig.screen.glitch(burst("static", "large", 0.3, sid="big", keep=lasting(("static", "small"))))
    rig.frames(30)
    assert admits.calls[-1] is False and set(strength) == {0.15}

    # Reduce on: two `effect static 0.5` 0.5 s apart; the second is refused, no W182.
    caplog.clear()
    rig, admits, strength = strobe("reduced", reduce=True)
    rig.screen.glitch(burst("static", None, 0.5, sid="r1"))
    rig.frames(30)
    rig.screen.glitch(burst("static", None, 0.5, sid="r2"))
    rig.frames(30)
    assert admits.calls == [True, False] and not codes(caplog, "W182")

    # W182 shares W61's statement set and its cap.
    log = RefusalLog()
    layer = glitch_module.GlitchLayer(refusals=log)
    refuse = type("Never", (), {"admit": lambda self, now, reduced: False})()
    for i in range(1500):
        layer.apply(burst("tear", None, 0.2, sid=f"s{i}"), 0.0, reduce=False, limiter=refuse)
    assert len(log.logged) == W61_SIDS_MAX


# --- AC-F28-18 — reduced effects ----------------------------------------------------------------

def test_ac_f28_18_reduced_effects(tmp_path):
    def pair(name: str, *, reduce: bool = True) -> tuple[L, L]:
        rig, ctl = L(tmp_path / name, reduce=reduce), L(tmp_path / f"{name}_c")
        for r in (rig, ctl):
            r.show(stage(HANA))
            r.frame()
        return rig, ctl

    # Tear, a tear burst, and jitter: every frame equals the control.
    rig, ctl = pair("motion")
    rig.screen.glitch(on(("tear", "large"), ("jitter", "large", "hana")))
    for _ in range(20):
        assert raw(rig.frame()) == raw(ctl.frame())
    rig.screen.glitch(burst("tear", None, 0.5, keep=lasting(("tear", "large"),
                                                             ("jitter", "large", "hana"))))
    for _ in range(40):
        assert raw(rig.frame()) == raw(ctl.frame())

    # `static large on`: one still frame at 0.15·w, w = ease_in_out(t/0.3); then off.
    rig, ctl = pair("static")
    strength = _static_strength(rig)
    rig.screen.glitch(on(("static", "large")))
    frames = rig.frames(60)                              # 1 s: the next change is admitted
    assert abs(strength[9] - 0.075) <= 0.005 and strength[18:] == [0.15] * 42
    assert len({raw(f) for f in frames[18:]}) == 1
    rig.screen.glitch(on())
    rig.frames(17)
    assert strength[-9] < 0.15 and strength[-1] > 0.0
    for _ in range(3):
        assert raw(rig.frame()) == raw(ctl.frame())

    # Switched on at frame 60 of `static medium on`: the still frame (k = 0) at 0.15; off at
    # frame 120: 0.30 with k = floor(121/6).
    rig, _ = pair("switch", reduce=False)
    strength = _static_strength(rig)
    offsets: list[tuple[int, int]] = []
    noise = rig.layer.noise.draw
    rig.layer.noise.draw = lambda s, st, off: (offsets.append(off), noise(s, st, off))
    rig.screen.glitch(on(("static", "medium")))
    rig.frames(61)
    seed = rig.layer._looks[("static", None)].seed
    rig.screen.settings = EffectSettings(reduce=True)
    rig.screen.drop_effects()                            # F16, when reduce turns on
    rig.frames(60)
    rig.screen.settings = EffectSettings(reduce=False)
    rig.frames(1)
    assert strength[60] == 0.30 and strength[61] == 0.15 and strength[121] == 0.30
    assert offsets[61] == glitch_module.noise_offset(seed, 0)
    assert offsets[121] == glitch_module.noise_offset(seed, 121 // 6)

    # Switched on during `effect tear 0.8`: gone the next frame, not back when it goes off.
    rig, ctl = pair("tear", reduce=False)
    rig.screen.glitch(burst("tear", None, 0.8))
    rig.frames(10)
    rig.screen.settings = EffectSettings(reduce=True)
    rig.screen.drop_effects()
    assert raw(rig.frame()) == raw(ctl.frame())
    rig.screen.settings = EffectSettings(reduce=False)
    for _ in range(10):
        assert raw(rig.frame()) == raw(ctl.frame())


# --- AC-F28-19 — freezes, window sizes, and fullscreen ------------------------------------------

class Menu(Screen):
    in_game = False                                # a menu: the stage's clock stops
    opaque = False                                 # ...drawn over the stage

    def draw(self, canvas) -> None:
        pass


ALL = on(("tear", "large"), ("static", "medium"), ("jitter", "large", "hana"))


def test_ac_f28_19_freezes_window_sizes_and_fullscreen(tmp_path):
    def run(name: str, **kwargs) -> L:
        rig = L(tmp_path / name, **kwargs)
        rig.show(stage(HANA))
        rig.frame()
        rig.screen.glitch(ALL)
        return rig

    reference = run("ref")
    ref = [raw(f) for f in reference.frames(40)]

    # A menu over the game at frame 30 for 120 frames, then focus lost for 60: every frame
    # equals frame 30's; the next is drawn at t = 31/60 (no catch-up).
    rig = run("frozen")
    rig.frames(31)
    menu = Menu()
    rig.app.screens.push(menu)
    assert all(raw(f) == ref[30] for f in rig.frames(120))
    rig.app.screens.remove(menu)
    rig.app.focused = False
    assert all(raw(f) == ref[30] for f in rig.frames(60))
    rig.app.focused = True
    assert raw(rig.frame()) == ref[31]

    # `effect tear 0.4` frozen at 0.2 s ends 0.2 s after resuming.
    rig = L(tmp_path / "burst")
    rig.show(stage(HANA))
    rig.frame()
    torn: list[bool] = []
    real = glitch_module.draw_tear
    glitch_module.draw_tear = lambda *a: (torn.append(True), real(*a))[1]
    try:
        rig.screen.glitch(burst("tear", None, 0.4))
        rig.frames(12)
        rig.app.screens.push(menu)
        rig.frames(60)
        rig.app.screens.remove(menu)
        count = len(torn)
        rig.frames(14)
    finally:
        glitch_module.draw_tear = real
    assert count == 72 and len(torn) == 84                  # 12 + 60 frozen + 12 more

    # 1600×900: tear bands at the same canvas rows scaled (± 1 px) with shifts of
    # round(dx·1.25) px, noise device-sized, jitter offsets scaled.
    big, ctl = run("big", size=(1600, 900)), L(tmp_path / "big_c", size=(1600, 900))
    big.screen.glitch(on(("tear", "large")))                # tear only, for the rows
    ctl.show(stage(HANA))
    control, frame = raw(ctl.frame()), raw(big.frame())
    look = big.layer._looks[("tear", None)]
    pitch = 1600 * 3
    for band in tear_bands(look.seed, 0, 96):
        top, bottom = band_rows(band, 1.25, 900)
        y = (top + bottom) // 2
        row, plain = frame[y * pitch:(y + 1) * pitch], control[y * pitch:(y + 1) * pitch]
        cut = (glitch_module.tear_px(band.dx, 1.25) % 1600) * 3
        assert row == plain[-cut:] + plain[:-cut], band
    big.screen.glitch(ALL)
    offsets = []
    real_copy = big.view.draw_sprite_copy
    big.view.draw_sprite_copy = lambda s, t, o: (offsets.append(o), real_copy(s, t, o))[1]
    big.frame()
    jit = big.layer._looks[("jitter", "hana")]
    dx, dy = jitter_offset(jit.seed, 0, 24)
    assert offsets == [big.app.canvas.px(dx, dy)]
    assert big.layer.noise.n8.get_size() == (1600, 900)

    # A resize (fullscreen toggle) at frame 30: F01's settle frames draw no glitch; after it
    # the looks go on from their clock's step (no reset).
    rig, ctl = run("resize"), L(tmp_path / "resize_c")
    ctl.show(stage(HANA))
    ctl.frame()
    rig.frames(30)
    t0 = rig.layer._looks[("tear", None)].t0
    for r in (rig, ctl):
        r.window.resize(960, 540)
    for _ in range(3):
        assert raw(rig.frame()) == raw(ctl.frame())
        assert rig.app.canvas.quality is RenderQuality.FAST
    for r in (rig, ctl):
        r.limiter.clock.now += 1.0                           # the settle is over
    assert raw(rig.frame()) != raw(ctl.frame())
    assert rig.app.canvas.quality is RenderQuality.FINAL
    assert rig.layer._looks[("tear", None)].t0 == t0 and rig.layer.noise.n8.get_size() == \
        (960, 540)


# --- AC-F28-20 — restore, skip, and new game on screen ------------------------------------------

def test_ac_f28_20_restore_skip_and_new_game_on_screen(tmp_path):
    w1, w2 = stage(background="bg sea"), stage(HANA)
    saved = lasting(("static", "small"))
    for reduce in (False, True):
        # A load: the saved set at once, at full strength in the first frame; no burst.
        rig = L(tmp_path / f"load{reduce}", reduce=reduce)
        strength = _static_strength(rig)
        rig.show(w1)
        rig.frame()
        rig.screen.glitch(burst("tear", "large", 2.0, keep=lasting(("jitter", "large", "hana"))))
        rig.frame()
        rig.screen.show_stage(ShowStage(w2, restored=True))
        rig.screen.glitch(Glitch(saved, restored=True))
        torn = []
        real = glitch_module.draw_tear
        glitch_module.draw_tear = lambda *a: (torn.append(True), real(*a))[1]
        try:
            rig.frames(3)
        finally:
            glitch_module.draw_tear = real
        assert strength[-3:] == [0.15] * 3 and not torn
        assert set(rig.layer._looks) == {("static", None)}

    # A rollback to W1 while W2's tear runs: the next frame is W1's plain picture.
    rig, ctl = L(tmp_path / "back"), L(tmp_path / "back_c")
    rig.show(w2)
    rig.frame()
    rig.screen.glitch(burst("tear", "large", 2.0))
    rig.frames(5)
    for r in (rig, ctl):
        r.screen.show_stage(ShowStage(w1, restored=True))
    assert raw(rig.frame()) == raw(ctl.frame())

    # Skip: `drop_effects` drops every burst; lasting static stays until `effect off`.
    rig = L(tmp_path / "skip")
    strength = _static_strength(rig)
    rig.show(w2)
    rig.frame()
    rig.screen.glitch(on(("static", "small")))
    rig.screen.glitch(burst("tear", "large", 2.0, keep=lasting(("static", "small"))))
    rig.frame()
    assert rig.layer._looks[("tear", None)].burst is not None
    for _ in range(10):
        rig.screen.drop_effects()                            # F15, every skipped frame
        rig.frame()
    assert ("tear", None) not in rig.layer._looks and strength[-10:] == [0.15] * 10
    rig.screen.glitch(Glitch(lasting(), stops=ALL_STOPS))                # effect off
    rig.frame()
    assert strength[-1] is None

    # Back to the title, then New Game: the first frame has no glitch.
    rig, ctl = L(tmp_path / "new"), L(tmp_path / "new_c")
    rig.show(w2)
    rig.screen.glitch(ALL)
    rig.frames(4)
    rig.screen.clear()
    rig.screen.on_enter()
    for r in (rig, ctl):
        r.show(w2)
    assert raw(rig.frame()) == raw(ctl.frame())


# --- AC-F28-22 — a drawing failure stops that kind (W183) ---------------------------------------

def test_ac_f28_22_a_drawing_failure_stops_that_kind(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    for kind, error in (("tear", pygame.error), ("static", MemoryError)):
        caplog.clear()
        rig = L(tmp_path / kind)
        rig.show(stage(HANA))
        rig.frame()
        rig.screen.glitch(ALL)
        drawn: dict[str, int] = defaultdict(int)
        real_tear, real_noise = glitch_module.draw_tear, rig.layer.noise.draw
        real_copy = rig.view.draw_sprite_copy
        failing = [False]

        def tear(*a):
            if failing[0] and kind == "tear":
                raise error("broken")
            drawn["tear"] += 1
            real_tear(*a)

        def noise(*a):
            if failing[0] and kind == "static":
                raise error("broken")
            drawn["static"] += 1
            real_noise(*a)

        def copy(*a):
            drawn["jitter"] += real_copy(*a)
            return True

        monkeypatch.setattr(glitch_module, "draw_tear", tear)
        rig.layer.noise.draw = noise
        rig.view.draw_sprite_copy = copy
        rig.frames(10)
        failing[0] = True
        rig.frames(10)
        rig.screen.glitch(burst(kind, "large", 0.5, keep=ALL.lasting))
        rig.frames(10)
        others = {"tear", "static", "jitter"} - {kind}
        assert drawn[kind] == 10 and all(drawn[k] == 30 for k in others), dict(drawn)
        records = codes(caplog, "W183")
        assert [r.getMessage() for r in records] == [
            f'the glitch effect "{kind}" couldn\'t be drawn ({error.__name__}), so it is off '
            "for the rest of this run."]
        check_p([r.getMessage() for r in records], home=Path.home(), game=tmp_path / kind)
        monkeypatch.undo()
