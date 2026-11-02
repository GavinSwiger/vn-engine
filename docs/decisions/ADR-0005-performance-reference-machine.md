# ADR-0005 — Performance reference machine and measurement

Status: **accepted** — 2026-11-01
Proposed by: vn-feature-architect (F01 `04-technical.md` §17, amendment to invariant 10;
answer to product Q5). Reviewed by: vn-qa-engineer (F01 `06-acceptance.md` §0.1, gaps G5,
G6, G7). Decided by: vn-system-architect (F01 `07-architecture-review.md`).

## Context

Invariant 10 said "60 fps at 1280×720 on integrated graphics; frame work under 16 ms". That
can't be tested: "integrated graphics" covers a tenfold performance range, and "60 fps" has
no measurement. QA pointed out (G6) that the proposed pass rule, "frame-interval p99
≤ 16.7 ms", leaves 0.033 ms over the 16.667 ms frame period, so it would mostly measure OS
timer jitter and fail on healthy machines. Every rendering feature (F04, F05, F09, F17, F28,
F29, F38) is held to this budget, so the measurement must be defined once.

## Options

1. Keep "integrated graphics" undefined.
2. A named reference machine, with frame-interval p99 ≤ 16.7 ms as the pass rule.
3. A named reference machine, with the budget expressed as frame-work time plus a
   long-frame rate.

## Decision

Option 3.

**Reference machine.** Intel Core i5-8250U with Intel UHD Graphics 620, 8 GB RAM, Windows 11,
internal 1920×1080 display at 100% scaling, mains power, "Balanced" power plan, CPython 3.12
(python.org build), pygame-ce 2.5.x wheel. If the team owns no such machine, a stand-in with
integrated graphics and a PassMark single-thread score ≤ 2,000 is acceptable. Its CPU model
and score are recorded in the test report.

**Metrics** (logged by `--bench SECONDS`; definitions are binding on every feature):
- *Frame interval*: unclamped wall-clock time between consecutive frame starts (consecutive
  returns of the frame limiter's wait).
- *Frame work*: wall-clock time from a frame's start to the return of that frame's
  `flip()`. It excludes the limiter's wait.
- *Long frame*: a frame interval longer than 1.5 × the frame period (25.0 ms at 60 fps).
- Values are reported in ms with 2 decimal places. A run starts on the first frame after
  the start-up phases of invariant 10 (story loading, F02) end. Its first 5 s are warm-up
  and are excluded.

**Pass rule (invariant 10).** In a 600 s `--bench` run on the reference machine, at the
default 1280×720 window and in 1920×1080 fullscreen:
- frame-work p99 ≤ **16.0 ms**;
- long frames ≤ **0.5%** of all frame intervals;
- frame count ≤ `fps × measured seconds + 1` (the cap holds, PR-F01-46).

**Scope.** F01 measures the placeholder screen. Each later rendering feature re-runs the
bench with its own content and states its scene in its acceptance document. Resolutions
above 1920×1080 are measured for information only and do not gate. Spike S0's typical-frame
check (ADR-0001, AC-F01-121) uses frame-work time, as QA assumed (G7 a).

**Player-chosen loads (F11).** Reading a save file for a load is one step on the main thread
(≤ about 6 ms typical, ≤ about 1.2 s on the reference machine for a hostile file at F11's bounds,
≤ 2 s gated by SEC-F11-06). It happens only when the player chooses a load, like a start-up phase,
so bench scenes don't include loads; F11's own perf ACs measure it.

**Player-chosen jumps and page opens (F20).** A flowchart jump is a load in this class: its
node-file read, the Auto save encoded at once before it (`autosave_now("jump")`), and the restore
that re-checks a menu's conditions are one step under the same limits. Opening the Flowchart page
may finish its layout in one step (≤ 250 ms at 1,000 nodes on the reference machine, TR-F20-07);
the layout is prewarmed in ≤ 2 ms slices while a menu is on top, so the remainder is usually 0.
Bench scenes include neither; F20's perf ACs measure them.

## Consequences

- The budget is testable and does not fail on timer jitter.
- "Steady 60 fps" means few long frames, not perfect frame pacing.
- PR-F01-49 and the F01 success measure must be reworded to these metrics, and the F01
  bench output must report them.
- A machine slower than the reference is not supported for the 60 fps promise.

## Status history

- 2026-11-01: accepted (F01 07-architecture-review). Pass rule changed from the proposed
  "interval p99 ≤ 16.7 ms" to frame-work p99 plus long-frame rate, per QA G6.
- 2026-11-01: F01 approved (review round 2). Final.
- 2026-11-01: amended at F02 approval: a bench run starts after start-up phases (story
  loading) end. Status remains accepted.
- 2026-11-02: amended at F11 approval: a player-chosen load's file read is one step outside the
  bench (invariant 10's exception list). Status remains accepted.
- 2026-11-02: amended at F20 approval: a flowchart jump is in the player-chosen load class, and a
  page open's layout remainder is one step at a player-chosen open. Status remains accepted.
