"""F29 — text-effect frame cost (``04-technical.md`` §11; ``06-acceptance.md`` AC-F29-17;
``07-architecture-review.md`` §2.3). Step 3 added the ADV rows; step 4 the NVL rows (the
default theme page, AC-F29-17 row 2, and the extreme theme, AC-F29-18).

**``perf``: the reference-machine run (owner).** ADR-0005: Intel Core i5-8250U, Windows 11,
mains power, "Balanced" plan; or a stand-in with integrated graphics and a PassMark
single-thread score of at most 2,000. Close other apps; the run takes a few seconds. From the
project root, in cmd::

    set VN_PERF=1
    set SDL_VIDEODRIVER=windows
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_textfx_perf.py

(In PowerShell: ``$env:VN_PERF = "1"; $env:SDL_VIDEODRIVER = "windows"``, then the same
command. The rows draw into a 1920×1080 surface of the display's format, so a dummy-driver
run measures the same CPU work; the printed line says which driver ran.) Attach the printed
``AC-F29-17`` lines and the machine's PassMark single-thread score to the test report.

Rows (600 frames each, 1920×1080, page A: one line filling the first ADV page at size 28):
- the effect pass (``fx_blits`` plus its ``blits``) on page A in ``{shake=large}`` and in
  ``{glitch=large}``: p99 ≤ 1.5 ms;
- the say window's whole draw (box, typed layer, effect pass) per frame: p99 ≤ 16.0 ms, and
  printed beside the same page without effects (T′, F05's path plus one empty-list check);
- a glitch page's arrival: the 20 substitutes of one (face, size, color), uncached: p99 ≤
  1.0 ms (04 §11 amended 2026-11-02: once per line, far inside the frame);
- NVL (``TextboxScreen`` in NVL at 1920×1080, ``fx`` page time, 600 frames): a full page of
  two lines (the first settled, the second current and complete) in ``{shake=large}`` and in
  ``{glitch=large}``, beside T′ (the three pages' frames interleaved on one framebuffer, so
  machine noise falls on all alike). ``NvlView.draw`` p99 ≤ T′'s p99 + 1.5 ms on the default theme
  (920 wide, size 28, 14 text rows, ≈ 700 effect glyphs) and + 5.0 ms on the extreme theme
  (AC-F29-18, a Should: 1200 wide, size 20, ``top_gap`` 24, ``bottom_gap`` 40, ``line_gap``
  0, 23 text rows, ≈ 2,400 effect glyphs); frame work (update + draw) p99 ≤ 16.0 ms.
"""

import os
import time
from dataclasses import replace
from types import SimpleNamespace

import pygame
import pytest

from engine.core.config_schema import Config
from engine.render.canvas import Canvas
from engine.render.textbox import TextboxView, fx_blits
from engine.render.textfx import SUBSTITUTES, FxTime, line_seed
from engine.render.textlayout import BUNDLED_FACES, LineLayout
from engine.runtime.commands import NvlPage
from engine.runtime.nvl import line_of
from engine.ui.builtin.textbox_screen import TextboxScreen, TextSettings
from tests.fakes.fx_text import bind, fx_body, plain, real_assets, say
from tests.perf.stage_bench_harness import machine_lines
from tests.render.test_textbox_fx import Adv, page_a
from tests.script.load_process import cpu_name

pytestmark = [pytest.mark.perf, pytest.mark.display]

FRAMES = 600
EFFECT_P99_MAX_MS = 1.5
FRAME_P99_MAX_MS = 16.0
ARRIVAL_P99_MAX_MS = 1.0               # 04 §11, amended 2026-11-02 (project decision)
NVL_DEFAULT_OVER_MS = 1.5
NVL_EXTREME_OVER_MS = 5.0
WORDS = ("the lanterns drift past the bridge rail while the river runs slow and the bells of "
         "the old mill answer from across the water ").split()


def p99(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]


def _line(name: str, ms: list[float]) -> str:
    ordered = sorted(ms)
    return (f"{name}: {len(ordered)} frames | ms p50 {ordered[len(ordered) // 2]:.3f} | "
            f"p99 {p99(ordered):.3f} | max {ordered[-1]:.3f}")


def _frames(adv: Adv, text: str, effects: bool) -> tuple[list[float], list[float], int]:
    """(effect pass ms, whole draw ms) per frame of page A shown complete, and its glyphs."""
    seed = line_seed("bench/a")
    page = adv.page(fx_body(text) if effects else plain(text))
    view, canvas, geometry = adv.view, adv.canvas, adv.geometry
    view.draw_typed(canvas, page, 1, page.end_glyph, geometry, fx=FxTime(0.0), seed=seed)
    draw = view._glyphs(canvas, page, 1, geometry)
    surface = canvas.surface
    effect_ms, frame_ms = [], []
    for f in range(1, FRAMES + 1):
        fx = FxTime(f / 60)
        start = time.perf_counter()
        out: list = []
        fx_blits(draw.fx, fx, seed, out)
        if out:
            surface.blits(out, doreturn=False)
        effect_ms.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        view.draw_box(canvas, geometry)
        view.draw_typed(canvas, page, 1, page.end_glyph, geometry, fx=fx, seed=seed)
        frame_ms.append((time.perf_counter() - start) * 1000)
    return effect_ms, frame_ms, len(draw.fx) + len(draw.entries)


def _arrival_ms(adv: Adv) -> list[float]:
    """The 20 substitutes of one style, each round in a new color (so uncached)."""
    face = BUNDLED_FACES.for_style(False, False)
    raster = adv.assets.font(face.ref, round(28 * adv.canvas.scale), bundled=face.bundled,
                             synth=face.synth)
    out = []
    for n in range(200):
        color = (n % 256, (n * 7) % 256, 200)
        start = time.perf_counter()
        for ch in SUBSTITUTES:
            adv.assets.text_line(raster, ch, color)
        out.append((time.perf_counter() - start) * 1000)
    return out


def test_ac_f29_17_adv_frame_cost():
    pygame.init()
    try:
        flags = pygame.display.get_driver()
    except pygame.error:
        flags = None
    print("\n== AC-F29-17 ADV page A, 1920x1080")
    for line in machine_lines(cpu_name(), os.environ.get("VN_PASSMARK_ST"), flags):
        print(line)
    failures = []
    for name, effect in (("plain (T')", None), ("shake=large", "shake=large"),
                         ("glitch=large", "glitch=large")):
        adv = Adv(size=(1920, 1080))
        text = page_a(effect=effect or "glitch=large")
        effect_ms, frame_ms, glyphs = _frames(adv, text, effect is not None)
        print(f"{name} ({glyphs} glyphs)")
        print("  " + _line("effect pass", effect_ms))
        print("  " + _line("say window draw", frame_ms))
        if effect is not None and p99(effect_ms) > EFFECT_P99_MAX_MS:
            failures.append(f"{name} effect pass p99 {p99(effect_ms):.3f} ms")
        if p99(frame_ms) > FRAME_P99_MAX_MS:
            failures.append(f"{name} draw p99 {p99(frame_ms):.3f} ms")
    arrival = _arrival_ms(Adv(size=(1920, 1080)))
    print(_line("glitch arrival, 20 substitutes of one style (uncached)", arrival))
    if p99(arrival) > ARRIVAL_P99_MAX_MS:
        failures.append(f"arrival p99 {p99(arrival):.3f} ms")
    assert not failures, failures


# --- NVL (AC-F29-17 row 2, AC-F29-18) -------------------------------------------------------------

def _nvl_screen(config: Config, canvas: Canvas) -> TextboxScreen:
    """A ``TextboxScreen`` in NVL drawing on ``canvas`` (its assets)."""
    assets = canvas.assets
    view = TextboxView(assets, config.theme.textbox, BUNDLED_FACES.for_style(True, False))
    app = SimpleNamespace(story=SimpleNamespace(post=lambda event: None), focused=True,
                          screens=SimpleNamespace(story_may_run=lambda: True))
    tb = TextboxScreen(app, config, view, BUNDLED_FACES)
    tb.settings = TextSettings(cps=0)
    tb.show_nvl(NvlPage(True))
    return tb


def _text(tb: TextboxScreen, rows: int) -> str:
    """The most words (cycling ``WORDS``) that lay out in exactly ``rows`` NVL rows."""
    probe = line_of(say("x", "bench/probe", effects=False))
    ctx = tb.nvl.ctx_for(probe, tb.nvl.metrics_at(tb.text_scale()))
    best, n = "", 1
    while True:
        text = " ".join(WORDS[k % len(WORDS)] for k in range(n))
        if len(LineLayout(plain(text), ctx).page(0).lines) > rows:
            return best
        best, n = text, n + 1


def _nvl_page(config: Config, canvas: Canvas, rows: tuple[int, int], effect: str | None
              ) -> tuple[TextboxScreen, Canvas, int]:
    """A page of two lines of ``rows`` text rows (the first settled, the second current and
    complete), in ``effect`` (None: T′), and its effect glyphs."""
    tb = _nvl_screen(config, canvas)
    for k, n in enumerate(rows):
        text = _text(tb, n)
        if effect is not None:
            text = "{" + effect + "}" + text + "{/" + effect.split("=")[0] + "}"
        tb.show(say(text, f"bench/nvl{k}", effects=effect is not None))
        for _ in range(3):
            tb.update(1 / 60, is_top=True)
            tb.draw(canvas)
    nvl = tb.nvl
    assert len(nvl.rows()) == 2 and nvl.plan.rows[0].entry == 0, "the page folded"
    view = tb.nvl_view
    glyphs = sum(len(r.draw.fx) for r in view._settled_fx) + len(view.line_view._page_draw.fx)
    return tb, canvas, glyphs


def _nvl_frames(pages: list[tuple[TextboxScreen, Canvas, int]]
                ) -> list[tuple[list[float], list[float]]]:
    """(``NvlView.draw`` ms, frame work ms) per frame of each page; the pages' frames are
    interleaved (on one framebuffer), so a busy moment of the machine falls on all of them
    alike."""
    out: list[tuple[list[float], list[float]]] = [([], []) for _ in pages]
    for _ in range(FRAMES):
        for (tb, canvas, _), (draw_ms, frame_ms) in zip(pages, out):
            start = time.perf_counter()
            tb.update(1 / 60, is_top=True)
            mid = time.perf_counter()
            tb.draw(canvas)
            end = time.perf_counter()
            draw_ms.append((end - mid) * 1000)
            frame_ms.append((end - start) * 1000)
    return out


def _extreme() -> Config:
    config = Config()
    nvl = replace(config.theme.nvl, width=1200, text_size=20, top_gap=24, bottom_gap=40,
                  line_gap=0)
    return replace(config, theme=replace(config.theme, nvl=nvl))


def test_ac_f29_17_18_nvl_frame_cost():
    pygame.init()
    try:
        driver = pygame.display.get_driver()
    except pygame.error:
        driver = None
    print("\n== AC-F29-17 / AC-F29-18 NVL page, 1920x1080")
    for line in machine_lines(cpu_name(), os.environ.get("VN_PASSMARK_ST"), driver):
        print(line)
    failures = []
    for theme, config, rows, over in (("default (AC-F29-17)", Config(), (7, 7),
                                       NVL_DEFAULT_OVER_MS),
                                      ("extreme (AC-F29-18)", _extreme(), (12, 11),
                                       NVL_EXTREME_OVER_MS)):
        effects = (None, "shake=large", "glitch=large")
        canvas = Canvas(real_assets())
        bind(canvas, (1920, 1080))
        pages = [_nvl_page(config, canvas, rows, effect) for effect in effects]
        (base, base_frame), *runs = _nvl_frames(pages)
        print(f"{theme}, {sum(rows)} text rows")
        print("  " + _line("plain (T') NvlView.draw", base))
        if p99(base_frame) > FRAME_P99_MAX_MS:
            failures.append(f"{theme} plain frame p99 {p99(base_frame):.3f} ms")
        for effect, (_, _, glyphs), (draw_ms, frame_ms) in zip(effects[1:], pages[1:], runs):
            print(f"  {effect} ({glyphs} effect glyphs)")
            print("    " + _line("NvlView.draw", draw_ms))
            print("    " + _line("frame work", frame_ms))
            print(f"    over T': p99 +{p99(draw_ms) - p99(base):.3f} ms (limit +{over}), "
                  f"p50 +{sorted(draw_ms)[FRAMES // 2] - sorted(base)[FRAMES // 2]:.3f} ms")
            if p99(draw_ms) > p99(base) + over:
                failures.append(f"{theme} {effect} draw p99 {p99(draw_ms):.3f} ms")
            if p99(frame_ms) > FRAME_P99_MAX_MS:
                failures.append(f"{theme} {effect} frame p99 {p99(frame_ms):.3f} ms")
    assert not failures, failures
