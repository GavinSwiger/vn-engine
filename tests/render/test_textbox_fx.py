"""F29 step 3 — effect glyphs in the ADV say window (``04-technical.md`` §7.2, §7.3, §7.5;
``06-acceptance.md`` AC-F29-10, AC-F29-16; ``07-architecture-review.md`` I-3, I-4, I-8).

``TextboxView`` draws straight onto a canvas (no App): bodies are hand-built
(``tests/fakes/fx_text.py``) until F29 step 2's tags exist, and each is compared with the same
text without effect tags (T′). Effect time is ``FxTime(f / 60)``; the seed is the line's
``line_seed(sid)`` (07 I-3). At 1280×720 one canvas unit is one pixel.
"""

import statistics
import time

import pygame
import pytest

from engine.core.config_schema import TextboxTheme
from engine.render.canvas import Canvas, RenderQuality
from engine.render.textbox import TextboxView, _PageDraw, _TypedLayer, box_geometry, fx_blits, \
    rgb_hex
from engine.render.textfx import SUBSTITUTES, FxTime, glitch_pick, line_seed, shake_unit, \
    wave_unit
from engine.render.textlayout import BUNDLED_FACES, LayoutContext, LineLayout
from tests.fakes.fx_text import FxSpy, SurfaceLog, TextLineSpy, bind, fx_body, plain, \
    real_assets

pytestmark = pytest.mark.display

FRAMES = range(61)
L4 = "I'm {wave}so{/wave} happy you came today!"
L5 = "{shake=small}I just... {pause=0.6}{speed=0.2}don't{/speed} want you to leave.{/shake}"
L6 = "{glitch=large}You're not going anywhere.{/glitch}"
L14 = "{speed=0.2}It was... {/speed}{speed=instant}{shake=large}GONE.{/shake}{/speed}"
WORDS = ("it is still a little early and the lights in the old mill flicker in the cold wind; "
         "i will tell it if it fits: a little lit lily, a still rill, a frill in the mill; ") * 4


class Adv:
    """One view, canvas, and geometry; ``layout(body)`` lays a body out in the box."""

    def __init__(self, size=(1280, 720), text_size=28, quality=RenderQuality.FINAL):
        self.assets = real_assets()
        self.canvas = Canvas(self.assets)
        self.fb = bind(self.canvas, size, quality)
        self.theme = TextboxTheme()
        self.view = TextboxView(self.assets, self.theme, BUNDLED_FACES.for_style(True, False))
        self.geometry = box_geometry(self.theme, text_size)

    def page(self, body, k=0):
        g = self.geometry
        ctx = LayoutContext(self.assets, BUNDLED_FACES, g.text_size,
                            rgb_hex(self.theme.text_color), g.area[2], g.area[3])
        return LineLayout(body, ctx).page(k)

    def rest(self, text):
        """T′'s draw list as {grapheme index: (surface, dest)}."""
        draw = self.view.build_glyphs(self.canvas, self.page(plain(text)), self.geometry,
                                      self.canvas.scale)
        return dict(zip(draw.indices, draw.entries))


def page_a(text_size=28, effect="glitch=large"):
    """06 §5's page A: one line that fills the first page of the box (199 glyphs at size 28;
    06 says ≈ 204)."""
    kind = effect.split("=")[0]
    return "{" + effect + "}" + WORDS + "{/" + kind + "}"


def _glitch_ok(blits, rest, fx_by_index, t, seed, p, still=False):
    """Each glitch blit is the real glyph or the substitute ``glitch_pick`` names, centred."""
    shown = []
    for g in fx_by_index.values():
        k = glitch_pick(g.index, t, seed, p, still)
        if k < 0 and still:
            k = g.still_sub
        expected = (g.surface, g.dest) if k < 0 else g.subs[k]
        assert expected in blits, (g.index, t)
        if k >= 0:
            surface, (x, y) = g.subs[k]
            assert y == rest[g.index][1][1]
            shown.append(k)
    return shown


# --- AC-F29-10 — effect glyphs on screen ----------------------------------------------------------

AC10_ROWS = ["L4", "L5", "L6", "bold_color", "cjk_emoji", "L14_size42", "size2_wave48",
             "fx_none", "typed_layer"]


@pytest.mark.parametrize("row", AC10_ROWS)
def test_ac_f29_10_effect_glyphs_on_screen(row, monkeypatch):
    texts = {"L4": L4, "L5": L5, "L6": L6, "fx_none": L6, "typed_layer": L4,
             "bold_color": "{color=#e05050}{b}{glitch=large}Run{/glitch}{/b}{/color}",
             "cjk_emoji": "{glitch=large}紙👩‍👩‍👧 a{/glitch}", "L14_size42": L14,
             "size2_wave48": "{size=2}{wave=large}Hi{/wave}{/size}"}
    text = texts[row]
    adv = Adv(text_size={"L14_size42": 42, "size2_wave48": 48}.get(row, 28))
    spy = FxSpy(monkeypatch)
    lines = TextLineSpy(monkeypatch, adv.assets)
    seed = line_seed("main/6")
    page = adv.page(fx_body(text))
    rest = adv.rest(text)
    view, canvas, geometry = adv.view, adv.canvas, adv.geometry
    end = page.end_glyph
    draw = view._glyphs(canvas, page, 1, geometry)
    fx = {g.index: g for g in draw.fx}
    static = dict(zip(draw.indices, draw.entries))
    assert set(fx) | set(static) == set(rest) and not set(fx) & set(static)
    for i, g in fx.items():                                      # rest place = T′'s
        assert (g.surface, g.dest) == rest[i]
        assert static.get(i) is None
    for i, entry in static.items():
        assert entry == rest[i]
    if row == "fx_none":
        view.draw_typed(canvas, page, 1, end, geometry, fx=None, seed=seed)
        drawn = set(view._layer.draw.entries[:view._layer.count]) | set(spy.take())
        assert drawn == set(rest.values())                       # real rasters at rest
        return
    if row == "typed_layer":                                     # TR-F29-04
        log = SurfaceLog(canvas.surface)
        canvas.surface = log
        view.draw_typed(canvas, page, 1, end, geometry, fx=FxTime(0.3), seed=seed)
        assert log.log[-1] == ("blits", 2)                       # the effect pass is last
        assert all(kind == "blit" for kind, _ in log.log[:-1])   # the layer (no spills)
        kept = [(i, e) for i, e in sorted(rest.items()) if i not in (4, 5)]
        bare = _TypedLayer(_PageDraw([e for _, e in kept], [i for i, _ in kept]),
                           view._layer.rect)
        bare.add(len(kept))
        assert pygame.image.tobytes(view._layer.surface, "RGBA") == \
            pygame.image.tobytes(bare.surface, "RGBA")
        anchor = view.indicator_anchor(page, 1, end, geometry)
        assert anchor == TextboxView(adv.assets, adv.theme, BUNDLED_FACES).indicator_anchor(
            adv.page(plain(text)), 2, end, geometry)
        return
    lifts, symbols = [], set()
    lines.take()
    for f in FRAMES:
        t = f / 60
        view.draw_typed(canvas, page, 1, end, geometry, fx=FxTime(t), seed=seed)
        blits = spy.take()
        assert len(blits) == len(fx)
        if row in ("L4", "size2_wave48"):
            amp = {"L4": 3.5, "size2_wave48": 6.0 * 96 / 28}[row]
            for i, g in fx.items():
                assert g.amp == pytest.approx(amp)
                x, y = rest[i][1]
                dy = round(-amp * wave_unit(i, t))
                assert (g.surface, (x, y + dy)) in blits
                lifts.append((-dy, y + dy))
        elif row in ("L5", "L14_size42"):
            amp = {"L5": 1.0, "L14_size42": 6.0}[row]
            for i, g in fx.items():
                ux, uy = shake_unit(i, t, seed)
                x, y = rest[i][1]
                dx, dy = round(amp * ux), round(amp * uy)
                assert abs(dx) <= amp and abs(dy) <= amp
                assert (g.surface, (x + dx, y + dy)) in blits
        else:
            symbols.update(_glitch_ok(blits, rest, fx, t, seed, 0.5))
        assert lines.take() == []                                # nothing rendered per frame
    if row == "L4":
        assert sorted(fx) == [4, 5]
    if row == "L5":
        assert len(fx) == len([g for line in page.lines for g in line.glyphs
                               if not g.text.isspace() and not g.hangs])
    if row == "L6":
        assert len(fx) == 23 and len(symbols) > 5
    if row == "size2_wave48":
        assert 20 <= max(lift for lift, _ in lifts) <= 22
        # Unclamped (Q3): the top glyph rises its full 21 px, nothing holds it at the area's
        # top. (06's "ink above the box top" needs ink within 21 px of the box top at rest;
        # the bundled font's "H" ink sits 61 px below it here, so it stays inside the box.)
        top = min(y for _, y in lifts)
        assert top == rest[0][1][1] - max(lift for lift, _ in lifts)
        assert top < canvas.px(0, geometry.area[1])[1]           # above the text area's top
    if row in ("L6", "bold_color", "cjk_emoji"):
        built = TextLineSpy(monkeypatch, adv.assets)
        view.forget_line()
        draw = view._glyphs(canvas, page, 1, geometry)
        calls = built.take()
        subs = [c for c in calls if c[1] in SUBSTITUTES]
        real_font = {c[1]: c[0] for c in calls}
        assert len(subs) == 20                                   # once per (face, size, color)
        for g in draw.fx:
            for (surface, (x, y)), ch in zip(g.subs, SUBSTITUTES):
                glyph = next(p for line in page.lines for p in line.glyphs if p.index == g.index)
                centre = geometry.area[0] + glyph.x + glyph.advance / 2
                assert abs(x + surface.get_width() / 2 - centre) <= 1, (g.index, ch)
                assert y == g.dest[1]
        if row == "bold_color":                                  # bold face, 28, #e05050
            font = real_font["R"]
            assert all(c[0] is font and c[2] == (0xE0, 0x50, 0x50) for c in subs)
            regular = BUNDLED_FACES.for_style(False, False)
            assert font.size_px == 28 and font.key != adv.assets.font(
                regular.ref, 28, bundled=regular.bundled, synth=regular.synth).key
        if row == "cjk_emoji":
            space = next(g.index for line in page.lines for g in line.glyphs if g.text == " ")
            assert space not in fx and space not in static


# --- AC-F29-16 — CI cost guard --------------------------------------------------------------------

def _steady(adv, page, frames, seed, *, fx=True):
    """Counts over ``frames`` steady frames after the first: blits calls per frame."""
    canvas, view, geometry = adv.canvas, adv.view, adv.geometry
    real = canvas.surface
    view.draw_typed(canvas, page, 1, page.end_glyph, geometry, fx=FxTime(0.0), seed=seed)
    per_frame = []
    for f in range(1, frames + 1):
        log = SurfaceLog(real)
        canvas.surface = log
        view.draw_typed(canvas, page, 1, page.end_glyph, geometry,
                        fx=FxTime(f / 60) if fx else None, seed=seed)
        per_frame.append(sum(1 for kind, _ in log.log if kind == "blits"))
    canvas.surface = real
    return per_frame


@pytest.mark.parametrize("row", ["a_plain", "b_glitch", "c_shake", "d_fast", "e_median"])
def test_ac_f29_16_ci_cost_guard(row, monkeypatch):
    adv = Adv(size=(1920, 1080))
    seed = line_seed("main/a")
    builds = []
    real_build = TextboxView.build_glyphs

    def build(self, *args):
        builds.append(args)
        return real_build(self, *args)

    monkeypatch.setattr(TextboxView, "build_glyphs", build)
    effect = {"c_shake": "shake=large"}.get(row, "glitch=large")
    text = page_a(effect=effect)
    page = adv.page(plain(text) if row == "a_plain" else fx_body(text))
    assert page.end_glyph >= 180
    lines = TextLineSpy(monkeypatch, adv.assets)
    if row == "d_fast":                                          # a live resize over (b)
        spy = FxSpy(monkeypatch)
        bind(adv.canvas, (1920, 1080))
        adv.view.draw_typed(adv.canvas, page, 1, page.end_glyph, adv.geometry,
                            fx=FxTime(0.0), seed=seed)
        assert spy.take() is not None
        lines.take()
        bind(adv.canvas, (1500, 844), RenderQuality.FAST)
        for f in range(1, 6):
            adv.view.draw_typed(adv.canvas, page, 1, page.end_glyph, adv.geometry,
                                fx=FxTime(f / 60), seed=seed)
            assert spy.take() is None                            # no effect pass: at rest
        fast = adv.view._glyphs(adv.canvas, page, 1, adv.geometry)
        assert fast.fx == [] and len(fast.entries) == len(adv.rest(text))
        assert not any(c[1] in SUBSTITUTES for c in lines.take())
        bind(adv.canvas, (1500, 844))                            # the drag ends: FINAL
        adv.view.draw_typed(adv.canvas, page, 1, page.end_glyph, adv.geometry,
                            fx=FxTime(0.2), seed=seed)
        assert spy.take()                                        # posing resumes
        return
    if row == "e_median":
        draw = adv.view._glyphs(adv.canvas, page, 1, adv.geometry)
        surface = adv.canvas.surface
        times = []
        for f in range(200):
            start = time.perf_counter()
            out = []
            fx_blits(draw.fx, FxTime(f / 60), seed, out)
            surface.blits(out, doreturn=False)
            times.append(time.perf_counter() - start)
        assert statistics.median(times) <= 0.002
        return
    adv.view.draw_typed(adv.canvas, page, 1, 0, adv.geometry, fx=FxTime(0.0), seed=seed)
    arrival = lines.take()
    subs = [c for c in arrival if c[1] in SUBSTITUTES]
    builds.clear()
    counts = _steady(adv, page, 30, seed)
    assert builds == [] and lines.take() == []                   # nothing built or rendered
    draw = adv.view._glyphs(adv.canvas, page, 1, adv.geometry)
    spills = 1 if adv.view._layer.spills else 0
    if row == "a_plain":
        assert draw.fx == [] and draw.runs == []
        assert counts == [spills] * 30                           # AC-F05-46's calls
    elif row == "b_glitch":
        assert len(subs) == 20 and len({c[0] for c in subs}) == 1   # once, one style
        assert counts == [spills + 1] * 30                       # exactly one blits more
    else:
        assert subs == [] and counts == [spills + 1] * 30
