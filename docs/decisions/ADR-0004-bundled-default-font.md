# ADR-0004 — Bundle Noto Sans as the engine default font

Status: **accepted** — 2026-11-01 (with modifications); **amended** 2026-11-01 (F05: Bold,
Italic, and Bold Italic faces)
Proposed by: vn-feature-architect (F01 `04-technical.md` §17; amendment F05
`04-technical.md` §18.1). Decided by: vn-system-architect (F01 and F05
`07-architecture-review.md`).

## Context

PR-F01-61 requires a bundled default font covering at least Basic Latin, Latin-1, and Latin
Extended-A, for the placeholder screen, the error screen, and any text whose font is
missing. pygame's built-in `freesansbold` has unclear coverage and is bold only. The
architecture requires an ADR for new third-party inputs.

**F05 amendment.** Inline `{b}` and `{i}` tags (PR-F05-18, 22) need real faces with no
author setup. SDL's synthetic bold is about 14% wider and smeared at 28 units, synthetic
italic is a plain slant, and nested `{b}{i}` is common.

## Options

1. pygame's `freesansbold.ttf`.
2. A bundled open-license font: Noto Sans, DejaVu Sans, Source Sans 3.
3. A system font lookup (`pygame.font.SysFont`). Unpredictable across machines.

For the F05 amendment: synthesize every style; bundle Bold and Italic only; bundle Bold,
Italic, and Bold Italic.

## Decision

Ship the static `NotoSans-Regular.ttf` (SIL Open Font License 1.1) in
`engine/data/fonts/`, together with `OFL.txt`.

- Its source URL, release version, and SHA-256 are recorded in
  `engine/data/fonts/SOURCE.txt`, and a test checks the bundled file's hash (SEC-F01-22).
- It covers Latin, Greek, and Cyrillic. CJK and other scripts are F43's concern
  (font fallback chains).
- The error screen always uses this font, never a theme font, so it renders even when the
  game's own fonts or theme are broken.

Modifications to the draft: provenance record and hash test; the error-screen rule.

**F05 amendment.** Also ship `NotoSans-Bold.ttf`, `NotoSans-Italic.ttf`, and
`NotoSans-BoldItalic.ttf`, taken from the same release archive as Regular
(NotoSans-v2.015, `NotoSans/hinted/ttf/`), under the same `OFL.txt`.
- `SOURCE.txt` records a `File:` and `SHA-256:` pair for each of the four faces.
  `tests/test_supply_chain.py` checks every listed hash and fails if any font file in
  `engine/data/fonts/` has no entry.
- These are the default faces for bold, italic, and bold+italic text. The engine
  synthesizes a style only from an author's own font family (F05 W45), never mixing an
  author's regular face with a bundled style.
- The error-screen rule is unchanged: it uses Regular only.

Modification to the F05 draft: the "no unlisted font file" check.

## Consequences

- It is a third-party asset, not a code dependency. F42 builds must ship `OFL.txt` and
  `SOURCE.txt` next to the fonts.
- About 0.6 MB on disk for Regular, and about 1.9 MB more for the three F05 faces; no other
  runtime cost until a face is used (font files are charged to the shared memory budget once
  per file).
- F43 adds fallback fonts; it must not replace Regular as the error-screen font unless
  the replacement is also bundled with the engine.

## Status history

- 2026-11-01: proposed (F01 04-technical §17).
- 2026-11-01: accepted with modifications (F01 07-architecture-review).
- 2026-11-01: F01 approved (review round 2). Final.
- 2026-11-01: amendment proposed (F05 04-technical §18.1): bundle Bold, Italic, and Bold
  Italic.
- 2026-11-01: amendment accepted with one modification (the unlisted-file check) in the F05
  07-architecture-review.
