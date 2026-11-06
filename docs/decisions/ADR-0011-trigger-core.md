# ADR-0011 — One trigger core for blocks that wait for their moment

Status: **accepted** — 2026-11-06 (built with F65 round 3, `specs/skins-contract.md` "Phases 2-4")
Proposed by: the skins plan (docs/proposals/engine-features.html, "Trigger core"
foundation). First used by: the Inbox's `send` (F65 round 2, kind `message`: each `send`
line a trigger armed by its line and fired at once; round 3's `after 1 day` / `after 2
scenes` keep it armed until its timing comes, the first use of the relative timing and of
`check_triggers`' W316); Events (I-02), Places' "open when" (I-04) and Thoughts (I-06) will
sit on it.

## Context

Four planned systems each declare a block that waits: an event that plays when its `when`
fits at a place, a letter that arrives `after 1 day`, a place that is open only at some
times, a thought that settles `after 3 scenes`. Each needs a condition, once or repeat, a
saved set of what has already happened, story-time timing, and a deterministic order. Built
four times, they would disagree on when conditions run, how rollback treats them, and which
of two fitting blocks wins, and the check would have four ways of saying "this never fits".

Story time is already saved state (F63) and announces itself through one hook,
`ClockChanged`, with a documented rule for F14's quiet forward re-run.

## Options

1. **Each system keeps its own list.** Rejected: four copies of the same rules, and four
   save formats.
2. **One registry with kinds.** Chosen. The core owns declaration, timing, the saved state,
   the evaluation points and the pick order; each system only says what its blocks are and
   what firing one does.
3. **Evaluate every condition at every checkpoint, as F37's achievements do.** Rejected for
   story triggers: achievements are meta state outside rollback, while these change story
   state, so when they run must be part of the story's own steps (a clock line, a scene
   entered) to replay the same way.

## Decision

1. **Declarations are script data, never saved.** `script/triggers.Trigger`: `kind` (the
   owner's word, used in every message), `name` (`id` = `kind:name`, the saved key), the
   declaring line, a compiled `when`, `once`, `Timing` (`day` from, `part` in, and the
   relative `after_days` / `after_parts` / `after_scenes`), `where`, `live` (waits from the start) or
   armed, and a static `payload`. A kind registers once
   (`runtime/triggers.register_kind(word, collect, on_fire, pick)`); each interpreter builds
   its table from every kind's `collect(program)`.
2. **Saved state is small and additive.** `GameState.triggers` holds the armed instances
   (id, due day and, for `after N parts`, due part, scenes left, the owner's plain
   `data`) and the retired ids, written only
   when not empty. An older save has none. A saved id the script no longer declares is kept
   and ignored. A save never holds a condition: conditions always come from the script,
   so a save can't make code run.
3. **Relative timing counts from arming.** `after N days` / `after N parts` / `after N
   scenes` mean "from when the owner armed it" (the Inbox's `send`). Parts of the day are a
   position on the calendar (day × parts + part): arming saves the due day and part, and
   any clock change that reaches or passes it fits, so `clock next day` passes every part
   it skips and going back to an earlier day passes none. A block live from the start has nothing to
   count from, so the check refuses that pairing (E458).
4. **Evaluation points.** Pushed kinds (with `on_fire`) are evaluated at every
   `ClockChanged` and every scene entered, after counting armed scenes down. Picked kinds
   (Events) are evaluated only when the owner asks (`pick`). `$` lines are not evaluation
   points. A pass doesn't start a nested pass.
5. **The replay rule is clock.py's.** Load, restore, going back and New Game put state back
   and evaluate nothing. The quiet forward re-run runs the same clock lines and enters the
   same scenes, so it evaluates and fires again, ending where the first run did; `on_fire`
   shows things only when `not interp.timeline.replaying`.
6. **Conditions run as `if` conditions do**: under the watchdog, with the same E85 story
   errors, at the declaring line.
7. **Pick order is first fit in declaration order.** A kind may pass another `pick` policy.
   The planned second policy, saliency (most conditions, least recently seen), needs a "last
   seen" stamp per trigger; it will be one more optional field in the saved state.
8. **The check is pure.** It reads conditions as Python's tree (clock values, constants,
   comparisons, three-valued `and`/`or`/`not`) over enough days to be exact, and only then
   says "never" (W316) or "always" (feeding W315, for picked kinds). Codes come from F65's
   block from the top: E459, E458, E457 (run time: too many armed), W316, W315.

## Consequences

- Inbox delays, Events, Places and Thoughts each add a kind and their statements, not a
  saved structure or an ordering rule.
- A condition that reads only story variables is evaluated only at clock changes, scene
  entries and picks, never after every `$` line; authors who need "as soon as" put the
  change before a scene change or a clock line.
- Saves of games that use none of this are unchanged.
