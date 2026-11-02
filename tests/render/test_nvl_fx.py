"""F29 step 4 — text effects in NVL (``04-technical.md`` §7.4, §7.6, TR-F29-05, TR-F29-07;
``06-acceptance.md`` AC-F29-15; ``07-architecture-review.md`` I-3, I-7, I-13).

``TextboxScreen`` runs by hand in NVL, one frame at a time (``show`` when a line arrives, then
``update(1/60)`` and ``draw``), on the bundled fonts at 1280×720, with the stand-in app of
``tests/ui/test_textbox_screen_fx.py``. Bodies are hand-built until F29 step 2's tags exist
(``tests/fakes/fx_text.py``); T′ is the same text without effect tags.

Each frame records every row's effect blits by its seed: each settled row's
``_RowFx.pose`` (``render/nvl.py``, R2's cache) and the current line's ``fx_blits`` call
(``render/textbox.py``). A row's seed is ``line_seed(sid) ^ row`` (I-3);
expected poses are rebuilt from ``textfx``'s pose functions on each effect glyph's rest
(``Pose(i, p, seed)``, 06 §0.3). Page time p counts the frames that add time: a line's
arrival frame adds none (04 §7.4), which is what keeps a settling line's pose (TR-F29-05).
"""

import math
from collections import Counter
from types import SimpleNamespace

import pytest

from engine.core.config_schema import Config
from engine.render import nvl as nvl_mod
from engine.render import textbox as textbox_mod
from engine.render.canvas import Canvas
from engine.render.textbox import TextboxView, fx_blits
from engine.render.textfx import GLITCH, SHAKE, SHAKE_STEP_S, FxTime, glitch_pick, line_seed, \
    shake_unit, wave_unit
from engine.render.textlayout import BUNDLED_FACES
from engine.render.typewriter import TypeState
from engine.runtime.commands import NvlPage
from engine.runtime.nvl import line_of
from engine.ui.builtin.textbox_screen import TextboxScreen, TextSettings
from tests.fakes.fx_text import SurfaceLog, TextLineSpy, bind, real_assets, say

pytestmark = pytest.mark.display

DT = 1 / 60
L9 = ("{wave=large}The river{/wave} was quiet.", "main/9", None)
L10 = ("{shake}Did you hear that?{/shake}", "main/10", "Hana")
L11 = ("{shake}Did you hear that?{/shake}", "main/11", "Hana")
L12 = ("{glitch}It was... {/glitch}{speed=instant}GONE.{/speed}", "main/12", None)
T = (L9, L10, L11, L12)


def seed_of(line, row: int) -> int:
    return line_seed(line[1]) ^ row


def pose(g, t: float, seed: int, still: bool = False):
    """``Pose(i, t, seed)`` of one effect glyph from its rest (06 §0.3)."""
    x, y = g.dest
    if g.kind == GLITCH:
        k = glitch_pick(g.index, t, seed, g.amp, still)
        if k >= 0:
            return g.subs[k]
        if still and g.still_sub >= 0:                       # 07 I-4's minimum
            return g.subs[g.still_sub]
        return g.surface, g.dest
    if still:
        return g.surface, g.dest
    if g.kind == SHAKE:
        ux, uy = shake_unit(g.index, t, seed)
        return g.surface, (x + round(g.amp * ux), y + round(g.amp * uy))
    return g.surface, (x, y - round(g.amp * wave_unit(g.index, t)))


class Page:
    """One ``TextboxScreen`` in NVL driven frame by frame; ``run`` returns the frame's effect
    blits as {seed: blits}."""

    def __init__(self, monkeypatch, *, cps=0, config: Config | None = None) -> None:
        self.assets = real_assets()
        self.canvas = Canvas(self.assets)
        bind(self.canvas, (1280, 720))
        config = config if config is not None else Config()
        view = TextboxView(self.assets, config.theme.textbox, BUNDLED_FACES.for_style(True, False))
        screens = SimpleNamespace(story_may_run=lambda: True)
        story = SimpleNamespace(post=lambda event: None)
        self.app = SimpleNamespace(story=story, focused=True, screens=screens)
        self.tb = TextboxScreen(self.app, config, view, BUNDLED_FACES)
        self.tb.settings = TextSettings(cps=cps)
        self.calls: list[tuple[int, list]] = []
        real = textbox_mod.fx_blits

        def spy(glyphs, fx, seed, out):
            start = len(out)
            real(glyphs, fx, seed, out)
            self.calls.append((seed, list(out[start:])))

        real_pose = nvl_mod._RowFx.pose

        def pose(row, fx, out):
            start = len(out)
            real_pose(row, fx, out)
            self.calls.append((row.seed, list(out[start:])))

        monkeypatch.setattr(textbox_mod, "fx_blits", spy)
        monkeypatch.setattr(nvl_mod._RowFx, "pose", pose)
        self.tb.show_nvl(NvlPage(True))

    def show(self, line, *, effects=True, restored=False) -> dict[int, list]:
        text, sid, name = line
        self.tb.show(say(text, sid, effects=effects, name=name, restored=restored))
        return self.run()

    def run(self) -> dict[int, list]:
        self.tb.update(DT, is_top=True)
        self.tb.draw(self.canvas)
        calls, self.calls = self.calls, []
        frame = dict(calls)
        assert len(frame) == len(calls), "two rows share a seed"
        return frame

    def frames(self, n: int) -> list[dict[int, list]]:
        return [self.run() for _ in range(n)]

    @property
    def t(self) -> float:
        return self.tb._fx_t

    def draws(self) -> dict:
        """{seed: draw list} of every row with effect glyphs, as last drawn."""
        nv, nvl = self.tb.nvl_view, self.tb.nvl
        out = {r.seed: r.draw for r in nv._settled_fx}
        if nvl.current is not None and self.tb.typer is not None:
            row = next(k for k, r in enumerate(nvl.rows()) if r.entry == nvl.current)
            draw = nv.line_view._page_draw
            if draw is not None and draw.fx:
                out[line_seed(nvl.entries[nvl.current].sid) ^ row] = draw
        return out

    def expected(self, seed: int, t: float, *, still: bool = False) -> list:
        return [pose(g, t, seed, still) for g in self.draws()[seed].fx]

    def rest(self) -> Counter:
        """Every drawn glyph and name at rest: static lists plus effect glyphs' rests."""
        nv = self.tb.nvl_view
        blits = list(nv._settled) + list(nv.line_view._page_draw.entries)
        blits += [(g.surface, g.dest) for draw in self.draws().values() for g in draw.fx]
        return Counter((id(s), d) for s, d in blits)


def _offsets(page: Page, seed: int, blits: list) -> list:
    return [(x - gx, y - gy) for (_, (x, y)), (gx, gy) in
            zip(blits, (g.dest for g in page.draws()[seed].fx))]


def _restore(page: Page, *, effects=True) -> dict[int, list]:
    lines = tuple(line_of(say(text, sid, effects=effects, name=name))
                  for text, sid, name in T)
    page.tb.show_nvl(NvlPage(True, lines))
    return page.show(L12, effects=effects, restored=True)


AC15_ROWS = ["L10_under_L9", "settle_same_pose", "row_seeds", "waiting", "nvl_clear",
             "page_fold", "G9_long_line", "rollback", "load", "reduce_motion", "layout",
             "steady_glitch_page", "R2_cache"]


@pytest.mark.parametrize("row", AC15_ROWS)
def test_ac_f29_15_effects_in_nvl(row, monkeypatch):
    page = Page(monkeypatch)
    tb = page.tb
    s9, s10, s11, s12 = (seed_of(line, k) for k, line in enumerate(T))
    if row in ("L10_under_L9", "settle_same_pose"):
        first = page.show(L9)
        assert page.t == 0.0 and first[s9] == page.expected(s9, 0.0)
        before = page.frames(20)[-1]
        p = page.t
        assert p == pytest.approx(20 / 60)
        arrival = page.show(L10)                               # L9 settles
        assert page.t == p > 0                                  # no restart, no time added
        assert s9 in {r.seed for r in tb.nvl_view._settled_fx}  # L9's effects are settled
        assert arrival[s9] == page.expected(s9, p) and len(arrival[s9]) == 8
        if row == "settle_same_pose":                          # TR-F29-05
            assert arrival[s9] == before[s9]
            page.show(L11)
            before = page.frames(17)[-1]
            arrival = page.show(L12)                            # L11 settles under L12
            assert arrival[s11] == before[s11] and arrival[s10] == before[s10]
            assert arrival[s9] == before[s9]
        else:
            assert page.run()[s9] == page.expected(s9, page.t)  # moving on: page time
            assert page.t == pytest.approx(21 / 60)
        return
    if row in ("row_seeds", "waiting"):
        for line in T:
            page.show(line)
            page.frames(7)
        assert tb.typer.state is TypeState.COMPLETE             # L12 waits for a press
        assert [r.entry for r in tb.nvl.rows()] == [0, 1, 2, 3]
        frames, times = [], []
        for _ in range(30):
            frames.append(page.run())
            times.append(page.t)
        for frame in frames:
            assert set(frame) == {s9, s10, s11, s12}
        frame = frames[-1]
        for seed in (s9, s10, s11, s12):
            assert frame[seed] == page.expected(seed, page.t)
        if row == "row_seeds":                                  # same text, rows 1 and 2
            assert s10 != s11
            a, b = _offsets(page, s10, frame[s10]), _offsets(page, s11, frame[s11])
            assert len(a) == len(b) == 15
            assert sum(1 for x, y in zip(a, b) if x != y) >= 10
            return
        steps = 0
        for (f0, t_a), (f1, t_b) in zip(zip(frames, times), zip(frames[1:], times[1:])):
            if math.floor(t_b / SHAKE_STEP_S) != math.floor(t_a / SHAKE_STEP_S):
                steps += 1
                assert f0[s10] != f1[s10] and f0[s11] != f1[s11]   # settled rows move
        assert steps >= 9
        return
    if row == "nvl_clear":
        page.show(L9)
        page.show(L10)
        page.frames(30)
        assert page.t > 0.4
        tb.show_nvl(NvlPage(True))                              # `nvl clear`
        assert page.t == 0.0
        frame = page.show(L11)                                  # the page's first frame
        assert page.t == 0.0 and frame[seed_of(L11, 0)] == page.expected(seed_of(L11, 0), 0.0)
        page.run()
        assert page.t == pytest.approx(1 / 60)
        return
    if row == "page_fold":
        long = "{shake}" + " ".join(["the lanterns drift past the bridge rail"] * 3) + "{/shake}"
        for n in range(20):
            frame = page.show((long, f"main/f{n}", None))
            rows = tb.nvl.plan.rows
            if n and rows[0].entry == tb.nvl.current:          # the line starts a new page
                assert page.t == 0.0
                seed = line_seed(f"main/f{n}")
                assert frame[seed] == page.expected(seed, 0.0)
                assert len(frame) == 1                          # the old rows are gone
                return
            assert n == 0 or page.t > 0
            page.frames(5)
        raise AssertionError("no fold")
    if row == "G9_long_line":                                   # 07 I-7: no restart
        words = "".join(f"w{n % 10}xy " for n in range(300))   # 1,500 graphemes: 2+ pages
        line = ("{wave}" + words + "{/wave}", "main/450", None)
        page.show(L9)
        page.frames(10)
        page.show(line)                                         # starts a page: t = 0
        assert page.t == 0.0 and tb.typer.state is TypeState.WAIT_PAGE
        page.frames(10)
        tb.press()
        frame = page.run()
        assert tb.typer.page >= 1 and page.t == pytest.approx(11 / 60)
        seed = line_seed("main/450")                            # row 0, its own later page
        assert frame[seed] == page.expected(seed, page.t)
        first = tb.layout.page(tb.typer.page).first_glyph
        assert first > 0 and all(g.index >= first for g in page.draws()[seed].fx)
        return
    if row in ("rollback", "load"):
        if row == "rollback":
            for line in T:
                page.show(line)
                page.frames(10)
        first = _restore(page)
        assert page.t == 0.0 and tb.typer.state is TypeState.COMPLETE
        assert set(first) == {s9, s10, s11, s12}
        for seed in (s9, s10, s11, s12):                        # complete, p = 0, row seeds
            draw = page.draws()[seed]
            assert len(first[seed]) == len(draw.fx) > 0
            assert first[seed] == page.expected(seed, 0.0)
        restored = page.rest()
        _restore(page, effects=False)                           # T′'s restored page
        assert page.rest() == restored and page.draws() == {}
        frames = page.frames(3)
        assert page.t == pytest.approx(3 / 60) and frames == [{}, {}, {}]
        return
    if row == "reduce_motion":
        tb.settings.reduce_motion = True
        for line in T:
            page.show(line)
            page.frames(5)
        frames = page.frames(60)
        assert all(f == frames[0] for f in frames)
        for seed in (s9, s10, s11):                             # wave and shake at rest
            assert frames[0][seed] == [(g.surface, g.dest) for g in page.draws()[seed].fx]
        assert frames[0][s12] == page.expected(s12, 0.0, still=True)
        assert frames[0][s12] == page.expected(s12, 5.0, still=True)
        return
    if row == "layout":
        plans = []
        for effects in (True, False):
            page = Page(monkeypatch)
            trace = []
            for line in T:
                page.show(line, effects=effects)
                page.frames(5)
                nvl = page.tb.nvl
                trace.append([(r.entry, r.page, r.y) for r in nvl.rows()])
            plans.append((trace, page.tb.nvl.plan))
        assert plans[0] == plans[1]
        return
    if row == "R2_cache":                     # AC-F29-18's fallback: blits equal uncached
        mixed = ("{shake=large}Wait a{/shake} {wave}moment, {/wave}{glitch=large}what was"
                 "{/glitch} {shake}that{/shake} {glitch=small}noise?{/glitch}", "main/m", None)
        for line in (*T, mixed, L9):
            page.show(line)
        rows = list(tb.nvl_view._settled_fx)
        assert len(rows) == 5 and any(len({g.kind for g in r.draw.fx}) == 3 for r in rows)
        times, t = [], 0.0
        for dt in [DT] * 40 + [0.37, 0.002, 0.049, 0.051, 0.1, 0.0, 0.031, 0.119, 0.121]:
            t += dt
            times.append(FxTime(t))
        times += [FxTime(0.0), FxTime(0.0), None, FxTime(2.0, True), FxTime(2.0, True),
                  FxTime(7.5), FxTime(7.5 + DT), None, FxTime(3.0)]
        times += [FxTime(3.0 + k * DT) for k in range(1, 30)]
        for fx in times:
            for r in rows:
                got: list = []
                r.pose(fx, got)
                want: list = []
                if fx is not None and fx.still and r.draw.runs:
                    r.draw.prepare_still(r.seed)
                fx_blits(r.draw.fx, fx, r.seed, want)  # uncached
                assert got == want, (fx, r.seed)
        return
    # steady frame of a full page of {glitch=large} lines: no rendering, ≤ 2 more blits
    sentence = "the lanterns drift past the bridge rail while the river runs slow tonight"
    counts = []
    for effects in (True, False):
        page = Page(monkeypatch)
        for n in range(3):
            text = "{glitch=large}" + " ".join([sentence] * 4) + "{/glitch}"
            page.show((text, f"main/g{n}", "Hana" if n == 1 else None), effects=effects)
            page.frames(3)
        nvl = page.tb.nvl
        assert len(nvl.rows()) == 3 and nvl.plan.rows[0].entry == 0
        assert sum(len(layout.page(0).lines) for layout in
                   (nvl._layouts[0][2], nvl._layouts[1][2])) >= 8
        lines = TextLineSpy(monkeypatch, page.assets)
        fits, builds = [], []
        real_fit, real_build = nvl_mod.fit_line, TextboxView.build_glyphs
        monkeypatch.setattr(nvl_mod, "fit_line", lambda *a: fits.append(a) or real_fit(*a))
        monkeypatch.setattr(TextboxView, "build_glyphs",
                            lambda self, *a: builds.append(a) or real_build(self, *a))
        real = page.canvas.surface
        per_frame = []
        for _ in range(10):
            log = SurfaceLog(real)
            page.canvas.surface = log
            frame = page.run()
            page.canvas.surface = real
            per_frame.append(sum(1 for kind, _ in log.log if kind == "blits"))
            if effects:
                assert len(frame) == 3
        assert lines.take() == [] and fits == [] and builds == []
        counts.append(per_frame)
        monkeypatch.setattr(nvl_mod, "fit_line", real_fit)
        monkeypatch.setattr(TextboxView, "build_glyphs", real_build)
    assert len(set(counts[1])) == 1 and all(c <= counts[1][0] + 2 for c in counts[0])
    # T′: settled + current static (2). Effects: settled static, all settled rows' effects in
    # one, the current line's effects (its static list is empty: no call) (3).
    assert counts == [[3] * 10, [2] * 10]

