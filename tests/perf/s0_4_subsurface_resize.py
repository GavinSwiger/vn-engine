"""S0-4 (AC-F01-119): draw into a framebuffer subsurface, then 100 resizes.

    .venv/Scripts/python tests/perf/s0_4_subsurface_resize.py          # the AC check
    .venv/Scripts/python tests/perf/s0_4_subsurface_resize.py --stale  # informational probe

Tries the full 2560x1080 window first. If the OS does not give that size (the display is
narrower), it uses the AC's 1280x540 variant with the rectangle halved:
subsurface (160, 0, 960, 540); probes (159,270) & (1120,270) black, (160,270) & (1119,270) red.
Resizes alternate between the test size and 1024x768; after every resize get_surface() is
re-fetched, the subsurface re-created (viewport per 04-technical §7.3), filled, and flipped.
Every time the window is back at the test size the four probe pixels are re-checked.

--stale: informational only. Keeps a subsurface from before a resize and touches it after,
to show what a Canvas that missed a re-bind would see. Run in its own process (could crash).
"""

from __future__ import annotations

import math
import os
import sys
import time

os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")

import pygame  # noqa: E402

import s0_common  # noqa: E402

RED = (255, 0, 0)
BLACK = (0, 0, 0)


def viewport(W: int, H: int, cw: int = 1280, ch: int = 720) -> pygame.Rect:
    s = min(W / cw, H / ch)
    w = min(W, max(1, math.floor(cw * s + 0.5)))
    h = min(H, max(1, math.floor(ch * s + 0.5)))
    return pygame.Rect((W - w) // 2, (H - h) // 2, w, h)


def settle(win: pygame.Window, want: tuple[int, int], timeout: float = 1.0) -> None:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        pygame.event.pump()
        if tuple(win.size) == want and win.get_surface().get_size() == want:
            return
        time.sleep(0.005)


def draw(win: pygame.Window) -> tuple[pygame.Surface, pygame.Rect]:
    fb = win.get_surface()
    vp = viewport(*fb.get_size())
    fb.fill(BLACK)
    sub = fb.subsurface(vp)
    sub.fill(RED)
    win.flip()
    return fb, vp


def probes(fb: pygame.Surface, vp: pygame.Rect) -> dict:
    y = vp.y + vp.h // 2
    pts = {
        (vp.x - 1, y): BLACK,
        (vp.right, y): BLACK,
        (vp.x, y): RED,
        (vp.right - 1, y): RED,
    }
    res = {}
    for p, want in pts.items():
        if 0 <= p[0] < fb.get_width():
            got = tuple(fb.get_at(p))[:3]
            res[str(p)] = (got, got == want)
    return res


def main() -> int:
    s0_common.print_json("versions", s0_common.versions())
    pygame.init()
    win = pygame.Window("vn-engine S0-4", size=(2560, 1080), allow_high_dpi=True, resizable=True,
                        position=(0, 0))
    settle(win, (2560, 1080))
    full = tuple(win.size) == (2560, 1080) and win.get_surface().get_size() == (2560, 1080)
    print(f"2560x1080 requested -> window.size={tuple(win.size)} fb={win.get_surface().get_size()}")
    if full:
        test_size = (2560, 1080)
    else:
        test_size = (1280, 540)
        win.size = test_size
        settle(win, test_size)
        print(f"display too small for 2560x1080; using the AC's 1280x540 variant -> "
              f"window.size={tuple(win.size)} fb={win.get_surface().get_size()}")
    other = (1024, 768)

    fb, vp = draw(win)
    first = probes(fb, vp)
    s0_common.print_json("viewport", tuple(vp))
    s0_common.print_json("initial probes", first)
    ok_initial = tuple(vp) == ((320, 0, 1920, 1080) if full else (160, 0, 960, 540)) and all(
        v[1] for v in first.values()) and len(first) == 4

    errors: list[str] = []
    mismatches = 0
    size_misses = 0
    fb_ids = set()
    t0 = time.perf_counter()
    for i in range(100):
        want = other if i % 2 == 0 else test_size
        try:
            win.size = want
            settle(win, want)
            if win.get_surface().get_size() != want:
                size_misses += 1
            fb, vp = draw(win)
            fb_ids.add(id(fb))
            if want == test_size:
                pr = probes(fb, vp)
                if not all(v[1] for v in pr.values()):
                    mismatches += 1
                    print(f"resize {i}: probe mismatch {pr}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"resize {i}: {exc!r}")
    dt = time.perf_counter() - t0
    final_size = tuple(win.size)
    print(f"100 resizes in {dt:.2f} s; exceptions={len(errors)}; probe mismatches={mismatches}; "
          f"framebuffer size misses after settle={size_misses}; distinct fb Surface objects seen={len(fb_ids)}; "
          f"final window.size={final_size}")
    for e in errors[:5]:
        print("  ", e)
    ok = ok_initial and not errors and mismatches == 0
    print(f"S0-4 RESULT: {'PASS' if ok else 'FAIL'} (variant {'2560x1080' if full else '1280x540 halved'})")
    win.destroy()
    pygame.quit()
    return 0 if ok else 1


def stale_probe() -> int:
    """Informational: is a subsurface taken before a resize still usable afterwards?"""
    pygame.init()
    win = pygame.Window("vn-engine S0-4 stale", size=(1280, 720), allow_high_dpi=True, resizable=True)
    settle(win, (1280, 720))
    fb_old = win.get_surface()
    sub_old = fb_old.subsurface((0, 0, 1280, 720))
    win.size = (1024, 576)
    settle(win, (1024, 576))
    fb_new = win.get_surface()
    print(f"same Surface object after resize: {fb_new is fb_old}; old fb size now {fb_old.get_size()}; "
          f"new fb size {fb_new.get_size()}")
    try:
        print(f"old subsurface size: {sub_old.get_size()}", flush=True)
        sub_old.fill(RED)
        print("filling the old subsurface: no exception", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"filling the old subsurface raised: {exc!r}", flush=True)
    win.flip()
    win.destroy()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(stale_probe() if "--stale" in sys.argv else main())
