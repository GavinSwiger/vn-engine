# ADR-0007 — Stage composite and background image decoding

Status: **accepted** — 2026-11-01 (the decode thread conditional per OS on AC-F04-45;
synchronous fallback pre-approved)
Proposed by: vn-feature-architect (F04 `04-technical.md` §7.4, §7.7, §17.1). Reviewed by:
vn-qa-engineer (F04 `06-acceptance.md` AC-F04-36, 37, 43–45, 48). Decided by:
vn-system-architect (F04 `07-architecture-review.md`).

## Context

Spike S0 (`tests/perf/S0-results.md`) found frames memory-bound. Six large alpha sprites
blitted every frame would cost about 20–27 ms on the ADR-0005 reference machine, which is over
the 16 ms budget (invariant 10). PR-F04-20 requires a background plus 6 sprites of
1,200×2,000 source pixels at 60 fps. Decoding one such PNG takes about 36 ms, so loading it
in the frame loop gives a long frame (PR-F04-21). The engine already runs one worker thread
(F03's watchdog). F08 plans another (its audio decoder). Before this ADR, there was no
general rule for worker threads beyond the threads note in architecture.md.

## Options

1. Draw the background and every sprite each frame: too slow (S0).
2. **Compose once per stage change into one buffer, then blit it each frame.**
3. Dirty rectangles: complex, and every change is a whole-picture cut anyway (PR-F04-19).
4. Load images synchronously ahead of time: still a 36 ms frame per image.
5. **Decode on a worker thread, from bytes the main thread read and checked.**
6. A worker that also reads files: `GamePaths`' listing cache is single-threaded, and
   invariant 9 keeps file access in one place.

## Decision

Options 2 and 5.

- **Composite.** `StageView` composes the stage once per `ShowStage`, and again whenever the
  viewport size or render quality changes, into one opaque buffer the size of
  `canvas.surface`, in the framebuffer format. It blits that buffer each frame. The buffer is
  never a subsurface. It sits outside `SizedLru` and is recreated on resize. A view keeps one
  composite; F09 may keep a second one for a transition. During F01's FAST resize settle,
  the last composite is scaled uncached. Scaled source variants stay in `SizedLru`. A
  variant larger than 2 viewports is cropped to the visible part.
- **Decode worker.** One daemon thread in `engine/render/prefetch.py` decodes, and optionally
  pre-scales, images named by `PrefetchImages`. The main thread reads the bytes through
  `GamePaths.read_file` and checks the header (`image_dimensions`) before handing them over.
  The main thread converts each result and adopts it into `AssetManager`, at most one result
  per frame. `PREFETCH_THREADED = False` runs the same steps on the main thread. If
  AC-F04-45 fails on an OS, that OS uses the fallback, and AC-F04-44 (c) proves the pixels
  are identical.
- **Worker-thread rule (all features).** Story state and author code run only on the main
  thread. A worker thread never reads or writes `GameState`, the namespace, or the
  interpreter, and never touches `AssetManager`, `SizedLru`, `GamePaths`, or any other
  engine object it didn't create. It gets immutable input (bytes, sizes) through a queue and
  returns objects it created. The main thread adopts them. Every worker is a daemon with a
  stop added to shutdown. Each worker's module has a flag to run its work synchronously on
  the main thread. Current workers: the F03 watchdog, which only interrupts the main thread;
  the F04 image decoder; the F08 audio decoder; and the F12 persistent writer (below).
- **File-writer worker (F12 amendment).** A worker may make file-system calls on condition
  that all of these hold:
  - It acts on one ADR-0003 write-root folder, given as a `Path` in a frozen request, and only
    through `core/safefile.py`.
  - It writes only bytes prepared on the main thread.
  - It reads only its own target file. It does so when the target's stamp changed, and the
    main thread validates those bytes before using them.
  - It unlinks only its own temp file and, for owner `meta` only (F31 amendment), the entry at
    a registered name (`FileRemove` → `remove_file`: never a link's target, never recursive,
    never a real folder).
  - It never logs. It returns a reason word and redacted detail, and the main thread logs them.

  `persist/writer.py` runs **one** such daemon thread per process, with
  `WRITER_THREADED = False` as the synchronous fallback. Writes never overlap. At quit the
  thread gets `CLOSE_WAIT_S` (2 s) and is then abandoned; it can leave only a temp file, never a
  partial target. No feature starts a second writer.
- **One writer, several owners (F16 amendment, merging F16 `04` §18 and F11 `04` C14).**
  - The one `Writer` is `App.writer`, built with the App; its thread starts on the first submit.
  - Each owner registers once: `writer.client(owner, *, root, names) -> WriterClient` (a second
    registration of an owner raises). `names` is a fixed set of file names, or a full-match
    pattern for engine-generated names only. Owners: `persist` (F12, `persistent.json`),
    `settings` (F16, `settings.json`), `save` (F11, the `SLOT_NAME_RE` pattern), and `flow`
    (F20, the `NODE_NAME_RE` pattern in the same root as `save`, under SEC-F20-03: `FileWrite`
    only; at most one `flow` job queued or in flight, and none submitted while `save` or
    `persist` has one pending; at quit its final submit comes after F11's and F12's and uses
    only what is left of the shared deadline), and `meta` (F31, the `META_NAME_RE` pattern in
    `<game>/characters`; `FileWrite` and `FileRemove`). New owners come only through review.
  - Before any file-system call, a job's folder must equal its owner's root and its name must
    be registered; otherwise the result is `Failed("couldn't write")` and nothing is touched.
    The only folder the writer may create is an owner's root (`ensure_real_dir`). The
    conditions above apply to each job within its owner's root.
  - Three job kinds: F12's stamped `WriteRequest` (the only job that may read, and only its own
    target), `FileWrite(folder, name, pieces, release, token)`, a plain last-writer-wins
    atomic write (F16, F11), and `FileRemove(folder, name, release, token)` (F31): owner `meta`
    only (any other owner's fails), `safefile.remove_file` on a registered name, and the root
    check never creates the root (`ensure_real_dir(root, release=False, create=False)`). New
    kinds come only through review.
  - `WriterClient.drop_queued()` (F31) ends that client's unstarted jobs, under the lock. Only
    `meta` calls it, first at quit.
  - Jobs run one at a time, FIFO across owners. Results go only to the submitting owner's
    client (`take()`, `pending`, `wait(until)`); "in flight" counts that owner's jobs only.
  - At quit, every owner shares one deadline, `CLOSE_WAIT_S` from the start of `App.run()`'s
    `finally`; the thread is then abandoned.

## Consequences

- A static stage costs one opaque blit per frame (about 1–1.5 ms at 1080p on the reference
  machine). A change costs one compose (about 10–15 ms), which is at most one long frame per
  change (PR-F04-21).
- Memory outside the budget: one composite, 3.5 MB at 1280×720 and 33 MB at 3840×2160 (two
  with F09). This is accepted.
- **F09** transitions blend two complete pictures (`StageView.picture()`). **F28** stage
  effects act on the composite. **F38** animating a sprite every frame would recompose every
  frame, so F38 must split the composite into "below", "the animated sprite", and "above"
  layers, or bring a new ADR.
- **F28 glitch buffers (F28 amendment).** While a glitch kind is in effect, the stage may
  hold, outside the budget:
  - two colorshift outputs `X` (viewport-sized, display format, swapped like composite and
    spare);
  - one band temp `T` (viewport width × 270 rows);
  - a noise field `N8` (8-bit) and its display-format copy `N32`;
  - one tear strip.

  These buffers:
  - are allocated only while their kind is in effect, and released at the first tick after it
    ends;
  - are recreated only on resize, never during F01's FAST settle;
  - fail soft: W183 turns the kind off.

  The worst case, colorshift and static both on, is about 29 MB at 1920×1080 and 116 MB at
  3840×2160. This is accepted. Nothing recomposes per frame. The colorshift output is built
  once per composite, one band per frame. A picture with no output yet (a load, or
  colorshift's first frame) is built whole in its first frame, which is at most one long frame
  per change (F28 `07` I-1, I-8).
- **F15** fast skip may compose on many consecutive frames. F15 owns pacing.
- **F08** follows the worker-thread rule for its decoder.
- This ADR replaces F03's "nothing runs off the frame loop except the watchdog" note
  (F03 review §3.3). TR-F03-05 still bans threads in `engine/runtime/`.

## Status history

- 2026-11-01: proposed (F04 `04-technical.md` §17.1).
- 2026-11-01: accepted with the general worker-thread rule and the per-OS fallback (F04
  `07-architecture-review.md`).
- 2026-11-01: clarified in the F08 review (I-5): a worker never starts, stops, or changes
  playback or display. F08's audio worker only decodes; the main thread plays the result.
- 2026-11-01: clarified in the F06 review: the audio worker may also build pitch variants
  (pure resampling, then `Sound(buffer=…)`) from a Sound it decoded itself, under the
  loader lock. These are objects it created, and it still never plays them.
- 2026-11-01: clarified in the F09 review: besides the second composite, `StageView` keeps one
  alpha scratch `S` and, after the first `Mask` transition, one mask byte buffer `B`. Both are
  viewport-sized and recreated only on resize, so they fall under the general rule for buffers
  outside the memory budget and are listed in `docs/architecture.md`. F09 adds no thread.
- 2026-11-01: amended in the F12 review (F12 `04` §18.1, `07`). The rule gains the file-writer
  clause, and the F12 persistent writer is listed. Modifications to the draft: the writer
  doesn't log, and it reads only its own target. Option 6's objection (a worker sharing
  `GamePaths`) doesn't apply, because the writer never uses `GamePaths`. Status remains
  accepted.
- 2026-11-02: amended in the F16 review (F16 `07` §3): the one writer serves several owners.
  Each registers a fixed root and fixed file names; results route per owner; quit uses one
  shared 2 s deadline. This merges F16's client proposal with F11's owner-tagged jobs (C14);
  F11's "in flight means any owner" is rejected. F12 checklist step 4 builds this form. Status
  remains accepted.
- 2026-11-02: F11 approved (F11 `07`): owner `save` registers the saves root and
  `SLOT_NAME_RE` and submits only `FileWrite` jobs; encoding stays on the main thread in slices
  (a worker can't read `GameState`). No rule change. Status remains accepted.
- 2026-11-02: amended at F20 approval (F20 `07`, SEC-F20-03): owner `flow` registered for F20's
  node-state files in the saves root, with the fairness conditions above; a read-only
  `pending_of(owner)` count lets it wait behind `save` and `persist`. Status remains accepted.
- 2026-11-02: amended at F28 approval (F28 `04` §6.7, §17; `07` I-1).
  - F28's glitch buffers are listed under Consequences: two `X`, `T`, `N8`/`N32`, and a strip.
    They are held only while their kind is in effect, at most about 116 MB at 4K.
  - The proposed fallback (one `X`, with an unfiltered first frame in transitions) is not
    adopted.
  - No thread is added. Status remains accepted.
- 2026-11-02: amended at F31 approval (F31 `07` §2 item 3(a), §5, I-1, I-2).
  - Owner `meta` is registered for `<game>/characters` with the `META_NAME_RE` pattern (a name
    pattern, not a predicate).
  - The file-writer clause gains `FileRemove`, for owner `meta` only: it removes the entry at a
    registered name (never a link's target, never recursive, never a real folder) and never
    creates the root. This breaks the earlier "unlinks only its own temp file", so the clause is
    amended. Job kinds become three.
  - `WriterClient.drop_queued()` is added; only `meta` calls it, first at quit.
  - No thread is added. Status remains accepted.
