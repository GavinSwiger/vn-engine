"""S0-3 (AC-F01-118): alpha conversion with only a pygame.Window (display.set_mode never called).

    .venv/Scripts/python tests/perf/s0_3_convert_alpha.py

Generates the fixture `images/rgba.png` as specified in 06-acceptance §5.1 (64x64, columns
0-31 alpha 0, columns 32-63 #3366CC alpha 255) into a temp folder, loads it from the file,
then tries convert_alpha() and, if that raises pygame.error, convert(32, pygame.SRCALPHA).
Pass: one path succeeds and (0,0) alpha == 0, (63,0) alpha == 255.
Also records (informational) what happens before any window exists, and convert(fmt) for
opaque images, which 04-technical §7.11.1 step 6 relies on.
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")

import pygame  # noqa: E402

import s0_common  # noqa: E402


def make_rgba_png(path: str) -> None:
    s = pygame.Surface((64, 64), pygame.SRCALPHA, 32)
    s.fill((0, 0, 0, 0))
    s.fill((0x33, 0x66, 0xCC, 255), pygame.Rect(32, 0, 32, 64))
    pygame.image.save(s, path)


def blit_on_red(c: pygame.Surface) -> tuple:
    """Does the converted surface actually alpha-blend? (0,0) must stay red if it does."""
    dst = pygame.Surface((64, 64))
    dst.fill((255, 0, 0))
    dst.blit(c, (0, 0))
    return tuple(dst.get_at((0, 0)))


def _set_alpha_255(c: pygame.Surface) -> pygame.Surface:
    c.set_alpha(255)
    return c


def try_paths(surf: pygame.Surface) -> dict:
    res: dict = {}
    for name, fn in (
        ("convert_alpha()", lambda: surf.convert_alpha()),
        ("convert(32, SRCALPHA)", lambda: surf.convert(32, pygame.SRCALPHA)),
        ("convert(32, SRCALPHA) + set_alpha(255)",
         lambda: _set_alpha_255(surf.convert(32, pygame.SRCALPHA))),
        ("convert(Surface((1,1), SRCALPHA, 32))",
         lambda: surf.convert(pygame.Surface((1, 1), pygame.SRCALPHA, 32))),
    ):
        try:
            c = fn()
            blit = blit_on_red(c)
            res[name] = {
                "ok": True,
                "a(0,0)": c.get_at((0, 0)).a,
                "a(63,0)": c.get_at((63, 0)).a,
                "rgba(63,0)": tuple(c.get_at((63, 0))),
                "flags_srcalpha": bool(c.get_flags() & pygame.SRCALPHA),
                "masks": c.get_masks(),
                "blit (0,0) onto red": blit,
                "blends": blit[:3] == (255, 0, 0),
            }
        except pygame.error as exc:
            res[name] = {"ok": False, "error": str(exc)}
    return res


def main() -> int:
    s0_common.print_json("versions", s0_common.versions())
    pygame.init()
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "images"))
        path = os.path.join(td, "images", "rgba.png")
        make_rgba_png(path)

        # Informational: before any window exists.
        pre = try_paths(pygame.image.load(path))
        s0_common.print_json("before any window (informational)", pre)

        win = pygame.Window("vn-engine S0-3", size=(640, 360), allow_high_dpi=True)
        pygame.event.pump()
        # Informational: Window exists but get_surface() not yet called.
        try:
            pygame.image.load(path).convert_alpha()
            print("convert_alpha() with Window but before get_surface(): OK")
        except pygame.error as exc:
            print(f"convert_alpha() with Window but before get_surface(): pygame.error: {exc}")
        fb = win.get_surface()
        assert pygame.display.get_surface() is None, "set_mode must never have been called"

        loaded = pygame.image.load(path)
        print(f"loaded: size={loaded.get_size()} bitsize={loaded.get_bitsize()} "
              f"srcalpha={bool(loaded.get_flags() & pygame.SRCALPHA)}")
        both = try_paths(loaded)
        s0_common.print_json("with pygame.Window, no set_mode", both)

        # The AC's procedure: convert_alpha first, fall back to convert(32, SRCALPHA).
        used = None
        try:
            conv = loaded.convert_alpha()
            used = "convert_alpha()"
        except pygame.error as exc:
            print(f"convert_alpha() raised: {exc}")
            conv = loaded.convert(32, pygame.SRCALPHA)
            used = "convert(32, SRCALPHA)"
        a0, a63 = conv.get_at((0, 0)).a, conv.get_at((63, 0)).a
        ok = a0 == 0 and a63 == 255
        blends = blit_on_red(conv)[:3] == (255, 0, 0)
        print(f"chosen path blends when blitted: {blends}")
        ok = ok and blends

        # Informational: opaque path (§7.11.1 step 6) — convert(fb) and convert(32, 0).
        opaque = pygame.Surface((8, 8))
        opaque.fill((10, 20, 30))
        info = {}
        for name, fn in (("convert(fb)", lambda: opaque.convert(fb)),
                         ("convert(32, 0)", lambda: opaque.convert(32, 0)),
                         ("convert() no args", lambda: opaque.convert())):
            try:
                c = fn()
                info[name] = {"ok": True, "masks": c.get_masks(), "same_format_as_fb": c.get_masks() == fb.get_masks()}
            except pygame.error as exc:
                info[name] = {"ok": False, "error": str(exc)}
        s0_common.print_json("opaque convert paths (informational)", info)
        s0_common.print_json("fb format", {"bitsize": fb.get_bitsize(), "masks": fb.get_masks()})

        print(f"S0-3 RESULT: {'PASS' if ok else 'FAIL'} via {used}: alpha(0,0)={a0} alpha(63,0)={a63}")
        win.destroy()
    pygame.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
