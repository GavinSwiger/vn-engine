# ADR-0001 — Canvas units, rasterized at device resolution

Status: **accepted (conditional on spike S0, AC-F01-121)** — 2026-11-01
Proposed by: vn-feature-architect (F01 `04-technical.md` §17). Decided by: vn-system-architect
(F01 `07-architecture-review.md`).

## Context

The product fixes a 1280×720 virtual canvas, letterboxed into any window (PR-F01-21/22),
and wants text and art as sharp as native at 1440p and 4K (F01 product Q1). The renderer is
CPU-side pygame-ce `Surface`s. Scaling a finished frame costs a full-frame resample every
frame, and that cost grows with window size. Every later rendering feature (F04, F05, F09,
F17, F28, F29, F38, F43) inherits this choice, so it must be made once.

## Options

- **A.** Compose at 1280×720, then scale the whole frame to the viewport every frame.
- **B.** Lay out in canvas units; rasterize at the viewport's device resolution. Assets are
  pre-scaled and cached per scale; fonts are rendered at `size × scale`.
- **C.** GPU textures through `pygame._sdl2.video` (private, experimental API).
- **D.** B, with the render scale capped (render at most 1920×1080, then `smoothscale` the rest).

## Decision

**B**, with **D** as the pre-approved fallback.

1. All game drawing goes through `engine.render.canvas.Canvas`, whose coordinates are
   canvas units (1280×720). Code outside `Canvas`, `App`, and pixel-level effects must not
   assume the drawing surface is 1280×720. The canvas size is defined once
   (`engine/core/constants.py`, `CANVAS_SIZE`).
2. The device-resolution drawing surface is a subsurface of the window framebuffer, so
   presenting needs no extra copy or scale. Only `App` fills the letterbox bars.
3. Text is laid out with reference metrics in canvas units and rasterized at device size.
   Line breaks never depend on window size. **Every text feature (F05, F13, F17, F29, F43)
   keeps this rule.**
4. **S0 gate.** Option B stands if spike S0's performance check (AC-F01-121: typical VN
   frame, frame-work p99 ≤ 12.0 ms at 1920×1080 fullscreen on the ADR-0005 reference
   machine) is GO. If it is NO-GO, option D becomes the decision **without another review**.
   Switching changes only `Canvas.bind` and `App.present`. S0 results are written to
   `tests/perf/S0-results.md`; the system architect then records the outcome below and
   drops "(conditional)" from the status.

## Consequences

- + Text and art are crisp at every size, up to the resolution of the source art. No
  per-frame full-frame scale.
- + The canvas size is a coordinate system only, so a future configurable canvas is cheap.
- + A later GPU path (option C, if pygame-ce makes it public) stays local to `Canvas`/`App`.
- − Scaled asset variants, rasterized text lines, and font objects use extra memory. **All
  of them count toward `[engine] cache_mb`** (see F01 review, required change on text caching).
- − The first frame after a resize re-scales the visible assets (FAST variants while the
  size is settling).
- − **Animated scale or rotation** (F04 zoom, F09 transitions, F28 effects) must not create
  one cached variant per frame. Those features draw through an uncached path, or pre-scale
  at a small number of key sizes. The variant cache is for sizes reused across frames.
- − **Whole-frame effects** (F09 dissolves, F28 glitches) use offscreen buffers of
  `canvas.surface.get_size()`, never `CANVAS_SIZE`. Their cost grows with device
  resolution. The performance budget (invariant 10, ADR-0005) is defined at 1920×1080;
  higher resolutions are best-effort.
- − **Screen-space effects** (shake, flash) stay inside the viewport. They never draw into
  the letterbox bars.
- − Pixel-art games using `scale_filter = "pixel"` at non-integer scales may see one-pixel
  differences between sprites, because each asset is scaled and positioned separately.
  `integer_scale = true` avoids this.

## S0 outcome

Run 2026-11-01; AC-F01-121 is **pending** (details in `tests/perf/S0-results.md`).

- The run machine was not a reference machine (ADR-0005) and was busy, so AC-F01-114
  conditions were not met. Option B fullscreen at 1920×1080 gave frame-work p99 12.91 ms
  and 19.19 ms on the two compliant runs (NO-GO if read literally).
- Fallback D does not help: at 1080p it equals B, and above 1080p it is slower (whole-frame
  `smoothscale`). Option A was slower than B at every size. Option B stays.
- Next: re-run `s0_6_typical_frame.py --option B --mode fullscreen --seconds 65` under
  AC-F01-114 conditions. If it fails, the cost is in full-screen alpha blits, and the fix
  is a new architecture decision, not a switch to D.

## Status history

- 2026-11-01: proposed (F01 04-technical §17).
- 2026-11-01: accepted, conditional on S0 (F01 07-architecture-review). Added the cache,
  animated-transform, whole-frame-effect, and screen-space consequences.
- 2026-11-01: confirmed at F01 approval (review round 2). Still conditional: S0 runs first
  in F01 implementation (AC-F01-121); the system architect records the outcome above and
  then drops "(conditional)".
