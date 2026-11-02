"""F28 step 5 — the colorshift filter and ``with glitch`` in Screen L
(``tests/render/glitch_screen.py``; ``06-acceptance.md`` §1.5), and the CI cost guard.

The default tier runs at 640×360 (scale 0.5, colorshift ``large`` = 6 px). A filtered
picture is checked against ``test_glitch_math.reference`` (the whole-frame channel shift) of
the view's plain composite (``picture()``).

Deviations (lean, F28 tests over 06's 5 s budget): AC-F28-23's transition row plays a
dissolve (fade and mask take the same filtered pictures through ``KindFrame``); AC-F28-26's
stream is 300 commands at 640×360 (the 10,000-command run is ``slow``), and its 1080p
timing loop runs 30 steady frames per case, not 120.

AC-F28-23, AC-F28-24, AC-F28-26.
"""

import logging
import random
import statistics
import time

import pygame
import pytest

from engine.render import glitch as glitch_module
from engine.render import stage as stage_module
from engine.render import transitions as transitions_module
from engine.render.canvas import RenderQuality
from engine.render.effects import EffectSettings
from engine.render.glitch import C, ColorShift, GlitchKind, colorshift_px
from engine.runtime.commands import Glitch, GlitchBurst, ShowStage, TransitionSpec
from engine.runtime.glitch import GlitchEntry, GlitchState
from tests.render.glitch_screen import DAICHI, HANA, L, burst, lasting, on, stage
from tests.render.test_glitch_math import reference

pytestmark = pytest.mark.display

D = colorshift_px(C["large"], 640)                       # 6 px at 640×360
SEA = stage(HANA, background="bg sea")


def raw(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


def codes(caplog, code: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "code", None) == code]


def spec(kind: str, seconds: float | None = 1.0, sid: str = "sid-1") -> TransitionSpec:
    calm, flashes = (False, True) if kind == "glitch" else (True, False)
    return TransitionSpec(kind, kind, sid, seconds, None, None, 0.1, False, None,
                          calm=calm, flashes=flashes)


def shifted(rig: L, d: int = D) -> bytes:
    """The filtered copy of the view's plain composite."""
    return reference(rig.view.picture(), d)


def ready(name, tmp_path, *, reduce: bool = False, glitch: Glitch | None = None) -> L:
    rig = L(tmp_path / name, reduce=reduce)
    rig.show(stage(HANA))
    rig.frame()
    if glitch is not None:
        rig.screen.glitch(glitch)
    return rig


def play(rig: L) -> list[tuple[bool, float | None, pygame.Surface]]:
    """Frames until the transition is over: whether it was RUNNING, the clock it was drawn
    at (None: the last frame, p = 1), the frame."""
    out = []
    for _ in range(300):
        run = rig.view._run
        if run is None:
            return out
        running = run.running
        frame = rig.frame()
        out.append((running, run.clock if rig.view._run is run else None, frame))
    raise AssertionError("the transition did not end")


def close(a: bytes, b: bytes, tol: int, step: int = 31) -> bool:
    return all(abs(a[i] - b[i]) <= tol for i in range(0, len(a), step))


# --- AC-F28-23 — colorshift on screen and through transitions ------------------------------------

def test_ac_f28_23_colorshift_on_screen_and_through_transitions(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    # Lasting, still: the channel shift of the composite in every frame (built in the first,
    # 07 I-8); picture() stays plain.
    rig = ready("still", tmp_path, glitch=on(("colorshift", "large")))
    plain = raw(rig.view.picture())
    frames = [raw(f) for f in rig.frames(3)]
    assert frames[0] == frames[1] == frames[2] == shifted(rig) != plain
    assert raw(rig.view.picture()) == plain

    # A dissolve: each RUNNING frame lies between the filtered old and new pictures (± 2),
    # and the last frame is the filtered new composite exactly.
    old = shifted(rig)
    rig.show(SEA, transition=spec("dissolve"))
    played = play(rig)
    new = shifted(rig)
    for running, clock, frame in played:
        if running and clock is not None:
            a = round(255 * clock) / 255
            mix = bytes(round(o * (1 - a) + n * a) for o, n in zip(old[::31], new[::31]))
            assert close(raw(frame)[::31], mix, 2, 1), clock
    assert raw(played[-1][2]) == new and len(played) > 60

    # finish() at p ≈ 0.3: the next frame is the filtered new composite.
    rig.show(stage(HANA), transition=spec("dissolve"))
    while not (rig.view._run.running and rig.view._run.clock >= 0.3):
        rig.frame()
    rig.view.finish()
    assert raw(rig.frame()) == shifted(rig) and rig.view._run is None

    # A colorshift burst ending at p ≈ 0.4: set_filter re-prepares and resumes at that p;
    # the last frame is the plain new composite.
    rig = ready("burst-end", tmp_path)
    rig.screen.glitch(burst("colorshift", "large", 0.5))
    rig.frames(3)
    rig.show(SEA, transition=spec("dissolve"))
    clocks = []
    while rig.view._run is not None:
        run = rig.view._run
        clocks.append((run.clock, run.running, run.shift is not None))
        last = rig.frame()
    # The frame the filter goes re-prepares only the kind (07 I-2): its clock stands still.
    off = [i for i in range(1, len(clocks)) if clocks[i - 1][2] and not clocks[i][2]]
    assert len(off) == 1 and 0.3 < clocks[off[0]][0] == clocks[off[0] - 1][0] < 0.5
    assert raw(last) == raw(rig.view.picture())

    # A cut under colorshift: the previous filtered picture until the new one is built
    # (2 bands at 360 rows), never an unfiltered frame; then the new one.
    rig = ready("cut", tmp_path, glitch=on(("colorshift", "large")))
    before = raw(rig.frame())
    rig.show(SEA)
    cut = [raw(f) for f in rig.frames(4)]
    assert cut[0] == cut[1] == before and cut[2] == cut[3] == shifted(rig)

    # `effect colorshift 0.5`: 30 filtered frames, then the composite exactly.
    rig = ready("burst", tmp_path, glitch=burst("colorshift", "large", 0.5))
    frames = [raw(f) for f in rig.frames(31)]
    assert frames[:30] == [shifted(rig)] * 30 and frames[30] == raw(rig.view.picture())

    # Reduced: the composite under the filtered copy at alpha round(255·w): 50 % at
    # t = 0.15, filtered only from t = 0.3; the same fall after `off`.
    rig = ready("reduced", tmp_path, reduce=True, glitch=on(("colorshift", "large")))
    frames = [raw(f) for f in rig.frames(20)]
    comp, filt = raw(rig.view.picture()), shifted(rig)
    half = bytes(round(c + (f - c) * 128 / 255) for c, f in zip(comp[::31], filt[::31]))
    assert frames[0] == comp and close(frames[9][::31], half, 2, 1)
    assert frames[18] == frames[19] == filt
    rig.frames(60)                                     # reduced: one change a second
    rig.screen.glitch(on())
    frames = [raw(f) for f in rig.frames(20)]
    assert close(frames[8][::31], half, 2, 1) and frames[18] == comp

    # A load landing with colorshift lasting: filtered from the first frame (07 I-8).
    rig = L(tmp_path / "load")
    rig.show(stage(HANA), restored=True)
    rig.screen.glitch(Glitch(lasting(("colorshift", "large")), restored=True))
    assert raw(rig.frame()) == shifted(rig)

    # FAST settle frames: plain (the control's frames).
    ctl = ready("fast-c", tmp_path)
    for r in (rig, ctl):
        r.window.resize(800, 450)
    assert raw(rig.frame()) == raw(ctl.frame())
    assert rig.app.canvas.quality is RenderQuality.FAST

    # The build raises pygame.error: the stage draws plain; one W183 naming colorshift.
    def broken(self, picture, out):
        raise pygame.error("no memory")

    monkeypatch.setattr(ColorShift, "_build_band", broken)
    rig = ready("broken", tmp_path, glitch=on(("colorshift", "large")))
    frames = [raw(f) for f in rig.frames(3)]
    assert frames == [raw(rig.view.picture())] * 3
    records = codes(caplog, "W183")
    assert len(records) == 1 and '"colorshift"' in records[0].getMessage()


# --- AC-F28-24 — `with glitch` -------------------------------------------------------------------

def test_ac_f28_24_with_glitch(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    # Default 0.5 s: 30 RUNNING frames; the old picture's rows before p = 0.5, the new
    # one's from it, torn (each row a roll of the plain one); the last frame is the new
    # composite exactly.
    rig = ready("default", tmp_path)
    old = raw(rig.view.picture())
    rig.show(stage(DAICHI, background="bg sea"), transition=spec("glitch", None))
    assert rig.view._run.kind_name == "glitch"
    played = play(rig)
    new = raw(rig.view.picture())
    assert sum(running for running, _, _ in played) == 30
    pitch, torn = 640 * 3, 0
    for clock, frame in ((c, raw(f)) for r, c, f in played if r and c is not None):
        plain = old if clock / 0.5 < 0.5 else new
        for y in range(0, 360, 3):
            row, want = frame[y * pitch:(y + 1) * pitch], plain[y * pitch:(y + 1) * pitch]
            if row != want:
                torn += 1
                assert sorted(row[i:i + 3] for i in range(0, pitch, 3)) == \
                    sorted(want[i:i + 3] for i in range(0, pitch, 3))
    assert torn > 0 and raw(played[-1][2]) == new

    # `with glitch 0.8`: 48 frames; a click at p ≈ 0.25: the new composite, untorn.
    rig.show(stage(HANA), transition=spec("glitch", 0.8))
    assert sum(running for running, _, _ in play(rig)) == 48
    rig.show(SEA, transition=spec("glitch", 0.5))
    while not (rig.view._run.running and rig.view._run.clock >= 0.125):
        rig.frame()
    rig.view.finish()
    assert raw(rig.frame()) == raw(rig.view.picture()) and rig.view._run is None

    # Three flashes, then `with glitch` within 1 s: a dissolve, one W182 (not W61).
    rig = ready("refused", tmp_path)
    for _ in range(3):
        assert rig.screen.limiter.admit(rig.screen.now, reduced=False)
    rig.screen.show_stage(ShowStage(SEA, transition=spec("glitch", 0.5, sid="g1")))
    assert rig.view._run.kind_name == "dissolve"
    assert len(codes(caplog, "W182")) == 1 and not codes(caplog, "W61")
    assert "glitch transition" in codes(caplog, "W182")[0].getMessage()

    # Four `with glitch 1.0`, and four 0.5 s ones under reduce: never counted; reduced, a
    # dissolve.
    for name, seconds, reduce in (("long", 1.0, False), ("calm", 0.5, True)):
        rig = ready(name, tmp_path, reduce=reduce)
        calls = []
        rig.screen.limiter.admit = lambda now, *, reduced: calls.append(now) or True
        for i in range(4):
            rig.screen.show_stage(ShowStage(SEA if i % 2 else stage(HANA),
                                            transition=spec("glitch", seconds, sid=f"{i}")))
            assert rig.view._run.kind_name == ("dissolve" if reduce else "glitch")
            rig.frames(8)
        assert calls == [], name

    # GlitchKind.draw raises pygame.error: F09's W62 cut.
    def broken(self, target, p, offset):
        raise pygame.error("boom")

    monkeypatch.setattr(GlitchKind, "draw", broken)
    rig = ready("w62", tmp_path)
    rig.show(SEA, transition=spec("glitch", 0.5))
    played = play(rig)
    assert raw(played[-1][2]) == raw(rig.view.picture()) and len(codes(caplog, "W62")) == 1


# --- AC-F28-26 — CI cost guard: bounded buffers, one heavy step -------------------------------------

class Heavy:
    """Counts the heavy steps of each frame: a compose or old-picture paint, a filter band,
    a kind's prepare step."""

    def __init__(self, monkeypatch) -> None:
        self.n = self.composes = self.depth = 0
        for owner, name in ((stage_module.StageView, "_paint"),
                            (ColorShift, "_build_band"),
                            (transitions_module.Dissolve, "prepare_step"),
                            (transitions_module.Mask, "prepare_step"),
                            (GlitchKind, "prepare_step")):
            monkeypatch.setattr(owner, name, self._wrap(getattr(owner, name), name))

    def _wrap(self, real, name):
        def counted(*args, **kwargs):
            self.n += self.depth == 0             # a mask's fallback dissolve: one step
            self.composes += name == "_paint"
            self.depth += 1
            try:
                return real(*args, **kwargs)
            finally:
                self.depth -= 1
        return counted


def live(rig: L) -> dict[str, int]:
    """The view's and the layer's buffers alive now."""
    view, layer = rig.view, rig.layer
    run = view._run
    composites = {id(s) for s in (view._composite, view._spare, run.old if run else None)
                  if s is not None}
    shifts = {id(f): f for f in (layer._shift, view._filter) if f is not None}
    return {"composites": len(composites), "S": int(view._scratch is not None),
            "B": int(view._masks.buffer is not None),
            "X": sum(len(f._outputs) for f in shifts.values()),
            "T": sum(f._band is not None for f in shifts.values()),
            "N8": int(layer.noise.n8 is not None), "N32": int(layer.noise.n32 is not None)}


LIMITS = {"composites": 2, "S": 1, "B": 1, "X": 2, "T": 1, "N8": 1, "N32": 1}
KINDS = ("tear", "colorshift", "static", "jitter")
SIZES = (None, "small", "medium", "large")


def command(r: random.Random, i: int) -> object:
    """One random stage or glitch command (or a view action)."""
    roll = r.random()
    if roll < 0.45:
        bursts = tuple(GlitchBurst(k, "hana" if k == "jitter" else None, r.choice(SIZES),
                                   r.choice((None, 0.2, 0.5, 1.2)), f"b{i}{k}")
                       for k in r.sample(KINDS, r.randint(0, 2)))
        on_ = GlitchState()
        for k in r.sample(KINDS, r.randint(0, 3)):
            on_ = on_.with_entry(GlitchEntry(k, r.choice(SIZES), "hana" if k == "jitter"
                                             else None))
        stops = tuple((k, None) for k in r.sample(KINDS, r.randint(0, 1)))
        return Glitch(on_, stops=stops, bursts=bursts, restored=r.random() < 0.05)
    if roll < 0.75:
        kind = r.choice(("dissolve", "fade", "glitch", "mask", None))
        tr = None if kind is None else spec(kind, r.choice((0.3, 0.6)), f"t{i}")
        sprites = (HANA,) if r.random() < 0.7 else (HANA, DAICHI)
        bg = r.choice(("bg grain", "bg sea"))
        return ShowStage(stage(*sprites, background=bg), transition=tr,
                         restored=r.random() < 0.05)
    return r.choice(("finish", "cancel", "resize", "reduce"))


def fuzz(rig: L, heavy: Heavy, n: int, seed: int) -> None:
    r = random.Random(seed)
    sizes = ((640, 360), (800, 450), (480, 270))
    for i in range(n):
        cmd = command(r, i)
        if cmd == "finish":
            rig.view.finish()
        elif cmd == "cancel":
            rig.view.cancel()
        elif cmd == "resize":
            rig.window.resize(*r.choice(sizes))
        elif cmd == "reduce":                               # F16 replaces the settings
            reduce = not rig.screen.settings.reduce
            rig.screen.settings = EffectSettings(reduce=reduce)
            if reduce:
                rig.screen.drop_effects()
        elif isinstance(cmd, ShowStage):
            rig.screen.show_stage(cmd)
        else:
            rig.screen.glitch(cmd)
        for _ in range(r.randint(1, 4)):
            rig.limiter.clock.now += 1.0                    # F01's settles end at once
            had = rig.view._filter is not None and rig.view._filter.buffers > 0
            heavy.n = 0
            rig.frame()
            counts = live(rig)
            assert all(counts[k] <= LIMITS[k] for k in LIMITS), (i, counts)
            # One heavy step a frame once the filter has an output (07 I-8's first build
            # and a finish() frame's own compose are ADR-0007's allowed long frames).
            if had and rig.view._run is not None:
                assert heavy.n <= 1, (i, heavy.n)


@pytest.mark.parametrize("tier", ["ci", pytest.param("slow", marks=pytest.mark.slow)])
def test_ac_f28_26_bounded_buffers_one_heavy_step(tmp_path, monkeypatch, tier):
    heavy = Heavy(monkeypatch)
    rig = ready("fuzz", tmp_path)
    fuzz(rig, heavy, 300 if tier == "ci" else 10_000, seed=7)
    # After `effect off` and one tick, the glitch buffers are released.
    rig.screen.glitch(Glitch(GlitchState(), stops=(("tear", None), ("colorshift", None),
                                                   ("static", None), ("jitter", None))))
    rig.screen.settings = EffectSettings()
    rig.frames(2)
    counts = live(rig)
    assert counts["X"] == counts["T"] == counts["N8"] == counts["N32"] == 0

    # Colorshift on, a transition, and a resize at FINAL quality: one heavy step a frame.
    rig = ready("steps", tmp_path, glitch=on(("colorshift", "large")))
    rig.frames(2)
    rig.show(SEA, transition=spec("dissolve", 1.0))
    seen = []
    for f in range(40):
        if f == 10:
            rig.window.resize(800, 450)
        rig.limiter.clock.now += 0.5                         # the settle ends at f = 12
        heavy.n = 0
        rig.frame()
        seen.append(heavy.n)
    # before: compose, 2 bands, the kind; after: compose both, 2 + 2 bands, the kind
    assert max(seen) == 1 and sum(seen) == 4 + 7, seen

    # 120 steady frames of each kind compose nothing; the stage layer's median at 1080p,
    # each kind alone and with a dissolve, is ≤ 10 ms on the CI runner.
    big = L(tmp_path / "big", size=(1920, 1080))
    big.show(stage(HANA, DAICHI))
    big.frames(2)
    canvas = big.app.canvas
    for kind in KINDS:
        entry = (kind, "large", "hana") if kind == "jitter" else (kind, "large")
        big.screen.glitch(on(entry))
        big.frames(6)
        heavy.composes = 0
        for with_dissolve in (False, True):
            if with_dissolve:
                big.show(stage(HANA, DAICHI, background="bg sea") if kind != "jitter"
                         else stage(HANA), transition=spec("dissolve", 3.0))
                big.frames(8)
            times = []
            for _ in range(30):
                big.screen.update(1 / 60, is_top=True)
                t = time.perf_counter()
                big.screen.draw(canvas)
                times.append(time.perf_counter() - t)
            assert statistics.median(times) <= 0.010, (kind, with_dissolve)
            if not with_dissolve:
                assert heavy.composes == 0, kind
        big.view.finish()
        big.frame()
        big.screen.glitch(on())
        big.frames(2)
