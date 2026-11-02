# ADR-0002 — `engine/core` and `engine/app` packages; import rules

Status: **accepted** — 2026-11-01 (with modifications)
Proposed by: vn-feature-architect (F01 `04-technical.md` §17). Decided by: vn-system-architect
(F01 `07-architecture-review.md`).

## Context

The seed `docs/architecture.md` has no home for config loading, logging, path containment,
viewport math, timing, the main loop, or the composition root. Some of these must be
usable by the pygame-free packages (`script`, `runtime`, `persist` need `UserFacingError`,
`GamePaths`, and logging). The seed rules also don't say whether `ui` may import `render`,
where `meta` and `minigames` sit, or what the entry points may import.

## Options

1. Put the shared code in `render/`. This breaks pygame-free use by `script`/`runtime`.
2. Put it in `runtime/`. This mixes concerns and makes `script → runtime` imports go upward.
3. Add a pure `core/` at the bottom and an `app/` composition root at the top.

## Decision

Option 3, with this complete import table. "May import" lists `engine.*` packages; stdlib
is always allowed.

| Package | May import | pygame |
|---|---|---|
| `core` | nothing | **never** |
| `script` | `core` | **never** |
| `runtime` | `core`, `script` | **never** |
| `persist` | `core`, `script`, `runtime` | **never**, except thumbnail encoding |
| `meta` | `core` | **never**. Which packages may import `meta` is settled in the F30/F31 reviews |
| `render` | `core`, `runtime` | yes |
| `audio` | `core`, `runtime` | yes |
| `ui` | `core`, `runtime`, `render`, `audio` | yes |
| `minigames` | `core`, `runtime`, `render`, `audio`, `ui` | yes (F23 may narrow this) |
| `app` | every package except `tools` | yes |
| `tools` | anything | yes |

- `engine/_bootcheck.py` is stdlib-only and parseable by Python 3.6.
- `engine/data/` holds engine-owned, non-code assets (default font, icon). It is not a package.
- Only the entry points (`main.py`, `engine/__main__.py`), `tools`, and modules inside
  `app` itself import `engine.app`.
- `core` modules have no side effects at import time and stay small. New `core` modules
  need a line in the owning feature's `04-technical.md` saying why they can't live higher up.
- The rules are enforced by `tests/test_import_rules.py` (AST scan).

Modifications to the draft: the full table above (the draft did not place `meta`,
`minigames`, `audio`, `persist`, or `engine/data/`), the intra-`app` import exception, and
the `core` creep rule.

## Consequences

- Story logic stays headless and testable.
- There is one obvious place for startup, the frame loop, and global input.
- `UserFacingError` and `GamePaths` are available to every package, so F02/F03/F11 errors
  and file access share one mechanism.
- `minigames` can build on `ui.Screen` instead of inventing a parallel loop (note for F23).

## Status history

- 2026-11-01: proposed (F01 04-technical §17).
- 2026-11-01: accepted with modifications (F01 07-architecture-review). The package layout
  in `docs/architecture.md` is updated when F01 is approved.
- 2026-11-01: F01 approved (review round 2). The package layout and the full import table
  are now in `docs/architecture.md`. Final.
