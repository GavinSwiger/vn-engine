"""S0-6 (AC-F01-121): typical VN frame bench, ADR-0001 option B vs option A (and D).

    .venv/Scripts/python tests/perf/s0_6_typical_frame.py --option B --mode fullscreen --seconds 65
    .venv/Scripts/python tests/perf/s0_6_typical_frame.py --option A --mode fullscreen --seconds 65

Scene (06-acceptance §5.7), generated procedurally (no third-party art), PNG round-tripped in
memory and loaded/converted like the asset loader (04-technical §7.11.1):
  bg 1280x720 opaque "photographic" (multi-octave noise + gradient + grain); three 480x720
  RGBA character silhouettes (~50% transparent, anti-aliased edges) at canvas x = 160, 400,
  640, y = 0; textbox 1240x200 at per-pixel alpha 200 at (20, 500); a 32 px name line and
  3 lines of 28 px dialogue (~190 chars) rendered once and cached (default pygame font; the
  engine's bundled Noto Sans is not available to a standalone spike).

Options:
  B  ADR-0001: canvas = framebuffer.subsurface(viewport); FINAL smoothscaled variants and
     text rasterized at round(size * scale), all cached; per frame only blits.
  A  compose at 1280x720 offscreen, then smoothscale the whole frame into the viewport.
  D  B capped at 1920x1080, then smoothscale to the viewport (only differs from B above 1080p).
Modes:
  fullscreen  borderless desktop fullscreen on the primary display (the AC measurement).
  windowed    a window of --size (may be larger than the display; informational).
  offscreen   compose into an offscreen Surface of --size, no flip (compose-only; informational).

Metrics (ADR-0005): frame start = return of the §7.9 limiter wait; frame work = start to the
return of flip(); 5 s warm-up excluded; nearest-rank percentiles; values in ms, 2 dp.
Also recorded: compose time (start -> just before flip) and flip time, intervals, long frames.
Appends one JSON line per run to tests/perf/s0_6_runs.jsonl.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import sys
import time

os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")

ap = argparse.ArgumentParser()
ap.add_argument("--option", choices=["A", "B", "D"], required=True)
ap.add_argument("--mode", choices=["fullscreen", "windowed", "offscreen"], default="fullscreen")
ap.add_argument("--size", default="1920x1080", help="windowed/offscreen size")
ap.add_argument("--seconds", type=float, default=65.0, help="measured seconds after warm-up")
ap.add_argument("--warmup", type=float, default=5.0)
ap.add_argument("--fps", type=int, default=60)
ap.add_argument("--a-filter", choices=["smooth", "fast"], default="smooth")
ap.add_argument("--env", action="append", default=[], help="extra SDL env KEY=VALUE (before import)")
ap.add_argument("--shot", default=None, help="save one presented frame as PNG to this path")
ap.add_argument("--label", default="")
ap.add_argument("--high-priority", action="store_true",
                help="diagnostic only: HIGH_PRIORITY_CLASS (not an AC condition; the engine never does this)")
ARGS = ap.parse_args()
for kv in ARGS.env:
    k, v = kv.split("=", 1)
    os.environ[k] = v
if ARGS.high_priority and sys.platform == "win32":
    import ctypes

    _k32 = ctypes.WinDLL("kernel32")  # throwaway spike only; engine code never loads kernel32
    _k32.GetCurrentProcess.restype = ctypes.c_void_p
    _k32.SetPriorityClass(ctypes.c_void_p(_k32.GetCurrentProcess()), 0x00000080)  # HIGH_PRIORITY_CLASS

import pygame  # noqa: E402

import s0_common  # noqa: E402

CANVAS = (1280, 720)
CAP_1080 = (1920, 1080)
HERE = os.path.dirname(os.path.abspath(__file__))
clock = time.perf_counter


# --------------------------------------------------------------------------- scene generation

def _png_roundtrip(surf: pygame.Surface) -> pygame.Surface:
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "x.png")
    buf.seek(0)
    return pygame.image.load(buf, "x.png")


def make_bg(rng: random.Random) -> pygame.Surface:
    W, H = CANVAS
    bg = pygame.Surface(CANVAS)
    # sky gradient
    for y in range(H):
        t = y / H
        bg.fill((int(40 + 120 * t), int(60 + 80 * t), int(120 + 60 * (1 - t))), (0, y, W, 1))
    # multi-octave value noise ("clouds"/foliage), smoothscaled up and added
    for cells, amp in ((8, 70), (24, 45), (80, 25), (240, 14)):
        n = pygame.Surface((cells, max(2, cells * 9 // 16)))
        for yy in range(n.get_height()):
            for xx in range(n.get_width()):
                v = rng.randint(0, amp)
                n.set_at((xx, yy), (v, int(v * 0.9), int(v * 0.7)))
        bg.blit(pygame.transform.smoothscale(n, CANVAS), (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    # "buildings" with lit windows
    x = 0
    while x < W:
        bw, bh = rng.randint(60, 160), rng.randint(180, 460)
        c = rng.randint(20, 60)
        pygame.draw.rect(bg, (c, c, c + 10), (x, H - bh, bw, bh))
        for wy in range(H - bh + 10, H - 10, 18):
            for wx in range(x + 6, x + bw - 10, 14):
                if rng.random() < 0.45:
                    pygame.draw.rect(bg, (rng.randint(180, 255), rng.randint(150, 220), 90), (wx, wy, 7, 9))
        x += bw + rng.randint(0, 20)
    # film grain
    grain = pygame.Surface((256, 256))
    for yy in range(256):
        for xx in range(256):
            v = rng.randint(0, 18)
            grain.set_at((xx, yy), (v, v, v))
    for gy in range(0, H, 256):
        for gx in range(0, W, 256):
            bg.blit(grain, (gx, gy), special_flags=pygame.BLEND_RGB_ADD)
    return bg


def make_sprite(rng: random.Random, hue: tuple[int, int, int]) -> pygame.Surface:
    """480x720 RGBA silhouette drawn at 2x then smoothscaled (soft edges)."""
    S = 2
    big = pygame.Surface((480 * S, 720 * S), pygame.SRCALPHA, 32)
    big.fill((0, 0, 0, 0))
    cx = 240 * S
    skin = (240, 210, 190, 255)
    r, g, b = hue
    # hair back
    pygame.draw.ellipse(big, (r // 3, g // 3, b // 3, 255), (cx - 110 * S, 30 * S, 220 * S, 290 * S))
    # body/dress: trapezoid from shoulders to the bottom
    pygame.draw.polygon(big, (r, g, b, 255), [(cx - 90 * S, 250 * S), (cx + 90 * S, 250 * S),
                                              (cx + 150 * S, 720 * S), (cx - 150 * S, 720 * S)])
    # arms
    pygame.draw.polygon(big, (r * 3 // 4, g * 3 // 4, b * 3 // 4, 255),
                        [(cx - 95 * S, 255 * S), (cx - 140 * S, 300 * S), (cx - 175 * S, 560 * S), (cx - 130 * S, 570 * S)])
    pygame.draw.polygon(big, (r * 3 // 4, g * 3 // 4, b * 3 // 4, 255),
                        [(cx + 95 * S, 255 * S), (cx + 140 * S, 300 * S), (cx + 175 * S, 560 * S), (cx + 130 * S, 570 * S)])
    # neck + head
    pygame.draw.rect(big, skin, (cx - 25 * S, 200 * S, 50 * S, 70 * S))
    pygame.draw.ellipse(big, skin, (cx - 85 * S, 60 * S, 170 * S, 190 * S))
    # fringe, eyes, mouth, collar detail
    pygame.draw.ellipse(big, (r // 3, g // 3, b // 3, 255), (cx - 95 * S, 40 * S, 190 * S, 90 * S))
    for ex in (-38, 38):
        pygame.draw.ellipse(big, (40, 50, 90, 255), (cx + (ex - 14) * S, 145 * S, 28 * S, 32 * S))
        pygame.draw.ellipse(big, (255, 255, 255, 255), (cx + (ex - 4) * S, 150 * S, 8 * S, 8 * S))
    pygame.draw.arc(big, (160, 80, 80, 255), (cx - 20 * S, 190 * S, 40 * S, 22 * S), math.pi, 2 * math.pi, 3 * S)
    pygame.draw.polygon(big, (250, 250, 250, 255), [(cx - 60 * S, 255 * S), (cx + 60 * S, 255 * S), (cx, 320 * S)])
    # cloth shading stripes (opaque; draw.* on SRCALPHA replaces pixels, it does not blend)
    for i in range(6):
        y = (330 + i * 60) * S
        half = (85 + i * 13) * S
        pygame.draw.line(big, (min(255, r + 40), min(255, g + 40), min(255, b + 40), 255),
                         (cx - half, y), (cx + half, y), 6 * S)
    _ = rng
    return pygame.transform.smoothscale(big, (480, 720))


def make_textbox() -> pygame.Surface:
    tb = pygame.Surface((1240, 200), pygame.SRCALPHA, 32)
    tb.fill((0, 0, 0, 0))
    pygame.draw.rect(tb, (18, 20, 38, 200), (0, 0, 1240, 200), border_radius=18)
    pygame.draw.rect(tb, (200, 190, 230, 200), (0, 0, 1240, 200), width=3, border_radius=18)
    pygame.draw.rect(tb, (60, 50, 110, 200), (24, -2, 260, 48), border_bottom_left_radius=10,
                     border_bottom_right_radius=10)
    return tb


NAME = ("Mika", 32)
DIALOGUE = [
    "The lanterns along the river flickered as the last train pulled away,",
    "and for a moment neither of us said anything. Then she laughed softly",
    "and asked whether I still remembered the promise we made that summer.",
]
TEXT_POS = [((50, 506), NAME[0], NAME[1], (255, 236, 200))] + [
    ((60, 556 + i * 40), line, 28, (240, 240, 245)) for i, line in enumerate(DIALOGUE)
]


def load_scene(fb_fmt: pygame.Surface) -> dict:
    """Generate, PNG round-trip, load, convert (alpha -> convert_alpha, opaque -> convert(fb))."""
    rng = random.Random(1234)
    raw = {
        "bg": make_bg(rng),
        "sprite_a": make_sprite(rng, (190, 70, 90)),
        "sprite_b": make_sprite(rng, (70, 110, 190)),
        "sprite_c": make_sprite(rng, (90, 160, 90)),
        "textbox": make_textbox(),
    }
    scene = {}
    for k, s in raw.items():
        loaded = _png_roundtrip(s)
        scene[k] = loaded.convert(fb_fmt) if k == "bg" else loaded.convert_alpha()
    m = pygame.mask.from_surface(scene["sprite_a"], 1)
    scene["_sprite_transparent_pct"] = round(100 * (1 - m.count() / (480 * 720)), 1)
    return scene


# --------------------------------------------------------------------------- geometry

def viewport(W: int, H: int) -> pygame.Rect:
    cw, ch = CANVAS
    s = min(W / cw, H / ch)
    w = min(W, max(1, math.floor(cw * s + 0.5)))
    h = min(H, max(1, math.floor(ch * s + 0.5)))
    return pygame.Rect((W - w) // 2, (H - h) // 2, w, h)


def bar_rects(W: int, H: int, vp: pygame.Rect) -> list[pygame.Rect]:
    rs = []
    if vp.x > 0:
        rs += [pygame.Rect(0, 0, vp.x, H), pygame.Rect(vp.right, 0, W - vp.right, H)]
    if vp.y > 0:
        rs += [pygame.Rect(0, 0, W, vp.y), pygame.Rect(0, vp.bottom, W, H - vp.bottom)]
    return rs


# --------------------------------------------------------------------------- renderers

class Prepared:
    """Per-scale cache (FINAL variants + rasterized text), built once outside the loop."""

    def __init__(self, scene: dict, scale: float) -> None:
        self.scale = scale

        def sz(w: int, h: int) -> tuple[int, int]:
            return max(1, math.floor(w * scale + 0.5)), max(1, math.floor(h * scale + 0.5))

        def scaled(s: pygame.Surface) -> pygame.Surface:
            if scale == 1.0:
                return s
            return pygame.transform.smoothscale(s, sz(*s.get_size()))

        def px(x: float, y: float) -> tuple[int, int]:
            return math.floor(x * scale + 0.5), math.floor(y * scale + 0.5)

        self.blits: list[tuple[pygame.Surface, tuple[int, int]]] = [
            (scaled(scene["bg"]), px(0, 0)),
            (scaled(scene["sprite_a"]), px(160, 0)),
            (scaled(scene["sprite_b"]), px(400, 0)),
            (scaled(scene["sprite_c"]), px(640, 0)),
            (scaled(scene["textbox"]), px(20, 500)),
        ]
        fonts: dict[int, pygame.font.Font] = {}
        for (x, y), text, size, color in TEXT_POS:
            rsize = max(1, round(size * scale))
            f = fonts.setdefault(rsize, pygame.font.Font(None, rsize))
            self.blits.append((f.render(text, True, color), px(x, y)))

    def draw(self, target: pygame.Surface) -> None:
        target.fblits(self.blits) if hasattr(target, "fblits") else target.blits(self.blits, doreturn=False)


def run() -> dict:
    s0_common.print_json("versions", s0_common.versions())
    pygame.init()
    W, H = (int(v) for v in ARGS.size.lower().split("x"))
    if ARGS.mode == "fullscreen":
        win = pygame.Window("vn-engine S0-6", size=(1280, 720), allow_high_dpi=True, position=(100, 100))
        win.set_fullscreen(desktop=True)
    elif ARGS.mode == "windowed":
        win = pygame.Window("vn-engine S0-6", size=(W, H), allow_high_dpi=True, position=(0, 0))
    else:
        win = pygame.Window("vn-engine S0-6 (offscreen)", size=(320, 180), allow_high_dpi=True)
    t_wait = clock()
    while clock() - t_wait < 1.0:
        pygame.event.pump()
        time.sleep(0.01)
    try:
        win.focus()
    except Exception:  # noqa: BLE001
        pass
    fb0 = win.get_surface()
    print(f"window.size={tuple(win.size)} framebuffer={fb0.get_size()} fullscreen_mode={ARGS.mode}", flush=True)

    scene = load_scene(fb0)
    print(f"sprite transparent pixels: {scene['_sprite_transparent_pct']}%", flush=True)

    offscreen = pygame.Surface((W, H)).convert(fb0) if ARGS.mode == "offscreen" else None

    def framebuffer() -> pygame.Surface:
        return offscreen if offscreen is not None else win.get_surface()

    fbw, fbh = framebuffer().get_size()
    vp = viewport(fbw, fbh)
    bars = bar_rects(fbw, fbh, vp)
    expected_fb = (fbw, fbh)

    # Build the per-option state (outside the measured loop: FINAL variants are cached).
    t_prep = clock()
    if ARGS.option == "B":
        prep = Prepared(scene, min(vp.w / CANVAS[0], vp.h / CANVAS[1]))
        mid = None
    elif ARGS.option == "A":
        prep = Prepared(scene, 1.0)
        mid = pygame.Surface(CANVAS).convert(fb0)
    else:  # D
        cap_vp = viewport(*CAP_1080) if (vp.w > CAP_1080[0]) else vp
        prep = Prepared(scene, min(cap_vp.w / CANVAS[0], cap_vp.h / CANVAS[1]))
        mid = pygame.Surface(cap_vp.size).convert(fb0) if cap_vp.size != vp.size else None
    prep_ms = (clock() - t_prep) * 1000
    scale_fn = pygame.transform.smoothscale if ARGS.a_filter == "smooth" else pygame.transform.scale

    def present() -> tuple[float, float]:
        fb = framebuffer()
        if fb.get_size() != expected_fb:
            raise RuntimeError(f"framebuffer size changed to {fb.get_size()}")
        for r in bars:
            fb.fill((0, 0, 0), r)
        canvas = fb.subsurface(vp)  # ADR-0001 decision 2; re-created per frame (~0.4 us)
        if mid is None:
            prep.draw(canvas)
        else:
            prep.draw(mid)
            scale_fn(mid, vp.size, canvas)
        t_c = clock()
        if offscreen is None:
            win.flip()
        return t_c, clock()

    # §7.9 limiter
    period = 1.0 / ARGS.fps
    next_deadline = clock()

    def wait() -> float:
        nonlocal next_deadline
        next_deadline += period
        remaining = next_deadline - clock()
        if remaining > 0.002:
            time.sleep(remaining - 0.002)
        while clock() < next_deadline:
            pass
        if clock() - next_deadline > period:
            next_deadline = clock()
        return clock()

    works, composes, flips, intervals = [], [], [], []
    frames = 0
    anomalies: list[str] = []
    t0 = None
    last = None
    while True:
        start = wait()
        if t0 is None:
            t0 = start
        if start >= t0 + ARGS.warmup + ARGS.seconds:
            break
        for ev in pygame.event.get():
            if ev.type in (pygame.WINDOWMINIMIZED, pygame.WINDOWHIDDEN, pygame.WINDOWFOCUSLOST,
                           pygame.WINDOWSIZECHANGED):
                phase = "measured" if start >= t0 + ARGS.warmup else "warm-up"
                anomalies.append(f"{start - t0:.2f}s ({phase}) {pygame.event.event_name(ev.type)}")
            if ev.type == pygame.QUIT:
                anomalies.append("QUIT")
        try:
            t_c, t_f = present()
        except RuntimeError as exc:
            anomalies.append(f"{start - t0:.2f}s {exc}")
            break
        if start >= t0 + ARGS.warmup:
            frames += 1
            works.append(t_f - start)
            composes.append(t_c - start)
            flips.append(t_f - t_c)
            if last is not None:
                intervals.append(start - last)
        last = start
    measured = (last - (t0 + ARGS.warmup)) if last else 0.0
    if ARGS.shot:  # after the loop, so the PNG encode never lands in a measured frame
        pygame.image.save(framebuffer(), ARGS.shot)

    long_thr = 1.5 / ARGS.fps
    longs = sum(1 for i in intervals if i > long_thr)
    result = {
        "label": ARGS.label,
        "option": ARGS.option + ("" if ARGS.option != "A" else f"/{ARGS.a_filter}"),
        "mode": ARGS.mode,
        "framebuffer": f"{fbw}x{fbh}",
        "viewport": list(vp),
        "fps_cap": ARGS.fps,
        "warmup_s": ARGS.warmup,
        "measured_s": round(measured, 2),
        "frames": frames,
        "work_ms": s0_common.summarize_ms(works),
        "compose_ms": s0_common.summarize_ms(composes),
        "flip_ms": s0_common.summarize_ms(flips),
        "interval_ms": s0_common.summarize_ms(intervals),
        "long_frames": f"{longs} of {len(intervals)} ({100 * longs / max(1, len(intervals)):.2f}%)",
        "cap": f"{frames} <= {math.floor(ARGS.fps * ARGS.seconds) + 1}",
        "prep_ms": round(prep_ms, 1),
        "sprite_transparent_pct": scene["_sprite_transparent_pct"],
        "env": ARGS.env,
        "anomalies": anomalies[:20],
        "versions": s0_common.versions(),
    }
    win.destroy()
    pygame.quit()
    return result


if __name__ == "__main__":
    res = run()
    w = res["work_ms"]
    print(json.dumps(res, indent=1))
    if res["mode"] == "fullscreen" and res["framebuffer"] == "1920x1080":
        verdict = "GO" if w["p99"] <= 12.00 else "NO-GO"
        print(f"S0-6 {res['option']} fullscreen 1920x1080: frame-work p99 {w['p99']:.2f} ms -> "
              f"{verdict if res['option'] == 'B' else 'informational'}")
    with open(os.path.join(HERE, "s0_6_runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(res) + "\n")
