# ADR-0009 — Minigame plugins load Python from the game folder

Status: **accepted** — 2026-11-02 (with the security review's five amendments; amended at F24: API 1.1 hooks; amended at F25/F26: widget thread rule, API versioning; amended at F27: A9 joins 1.1)
Proposed by: vn-feature-architect (F23 `04-technical.md` §7.10, §17.3). Reviewed by:
vn-security-reviewer (F23 `05-security.md` §4, SEC-F23-01–04). Decided by:
vn-system-architect (F23 `07-architecture-review.md`).

## Context

Until F23, no Python file from the game folder runs: author code is `$` lines, conditions,
and `define`/`default` values compiled from `.vns` files (F03 `07`). F23 must load author
minigame plugins from `game/minigames/` in dev and release builds, and F24–F27 ship bundled
minigames through the same API. Invariant 9(d) already says author code is trusted and not
sandboxed. What needs deciding is how the code is found and imported, so that loading:
- reads only the real files of one real folder,
- writes nothing (no `__pycache__`),
- never shadows a stdlib or engine module (`game/minigames/json.py`), and
- can never be started or chosen by data (saves, config, persistent data).

## Options

1. **importlib with the folder on `sys.path`.** Rejected. It writes bytecode into the game
   folder, a plugin named `json.py` shadows the stdlib for the whole process, and Python's
   path finder follows links and loads `.pyc`, `.pyd`, and `.so` files that sit beside a
   source.
2. **A private finder that serves sources read through `GamePaths` and compiles them in
   memory.** Chosen.
3. **A subprocess host.** Rejected. It doesn't sandbox Python, and it costs a second
   interpreter, a protocol, and frame-time round trips for every input and draw.

## Decision

1. **One folder, read once.** At launch, before F02's load, `PluginLoadJob` (one unit per
   launch slice, main thread) loads the units in the real `<game>/minigames/`. Its only inputs
   are `GamePaths` and constants. No config key, save, persistent value, script text,
   environment variable, or start option names, adds, or skips a plugin file (SEC-F23-04(a)).
   Names in scripts and saves are registry keys only, never file names.
2. **No links followed, contained or not** (amendment 1). The folder `minigames` and every
   entry read under it must be a real directory or regular file whose real path equals its
   listed path (normcase). `resolve()`'s containment check is not enough, because it accepts
   contained links: a contained link can still point into a dev write root (`saves/`,
   `logs/`, `characters/`) that holds outside data. A linked or non-directory folder gives
   E273's G form and loads nothing. A linked, FIFO, or device entry is left out and named
   game-relative once in a dev warning (W163). A reparse point that resolves to its own path
   (a cloud placeholder or dedup file) counts as a real file or folder. Reads use the new
   `GamePaths` reads (`real_dir`, `list_real`, `read_file(…, regular=True)`). Each source is
   read once, and the bytes compiled are the bytes read.
3. **One ASCII name rule on every OS.** Unit stems and every name inside a package
   `fullmatch` `[a-z][a-z0-9_]{0,39}` (not a keyword, not a Windows reserved basename).
   `__init__.py` is the only `_` name read. Other names are refused or skipped unread.
4. **A private import system** (amendment 2). Before any plugin runs, the loader creates the
   package `_vn_minigames` (`__path__ = []`) and puts `PluginFinder` at **index 0** of
   `sys.meta_path`. It answers every `_vn_minigames.*` name from the pre-read sources and
   refuses unknown names under the prefix before any other finder runs. No `__path__` names
   a directory, so the path finder never searches the folder. Code filenames and specs are
   `<minigames/…>` (`cached=None`, `has_location=False`). `linecache` is seeded from the read
   text, so tracebacks show source lines with no file opened. Sources are strict UTF-8
   `str`, compiled with `dont_inherit=True`, so a coding cookie changes nothing.
   `sys.path`, `sys.path_hooks`, and `sys.path_importer_cache` are untouched. No `.pyc`,
   `.pyd`, `.so`, `.zip`, or `__pycache__` is ever loaded or written.
5. **Only the listing chooses code; tools run none** (amendment 3). Read-only tools (F41
   lint, F44's editor process, F42's packager) pass `LoadOptions.minigames=None` and never
   start `PluginLoadJob`. F39's reload, when designed, re-runs this loader and never
   `importlib.reload`. Headless runs do load plugins (their top levels run), then call only
   `check_args`, `check_story`, and `outcome_for` (API 1.1, F24), each on a fresh,
   never-started instance inside one guard entry.
6. **Bounded and reported.** At most 64 units, 1 MiB per file, 64 files and depth 3 per
   package, 8 MiB of source, and 256 registrations. Top levels and `register` run under the
   F03 guard and watchdog. Every run, release included, logs one INFO record per loaded unit
   (game-relative path, size, the first 12 hex digits of its SHA-256, API version), area
   `plugin`.
7. **Main thread only.** Every plugin call runs on the main thread inside the guard. Every
   object reachable from the plugin's `Context` checks the calling thread and raises
   `MinigameThreadError` otherwise (SEC-F23-11). *Amended at F25:* F10 widgets and focus
   groups are kit objects, not engine services. That covers the plugin's own and those
   `CodexView.build` returns, so they are not wrapped. Engine state behind a widget is reached
   only through a thread-checked object (`LedgerCodexPort` checks every public method), and the
   host calls widgets only through `_call` on the main thread.

## Consequences

- Plugins get no `.pyc` speed-up. Packages must use relative imports, and `__file__` is not a
  path. `docs/minigames.md` says so.
- Plugins stay trusted code under invariant 9(d). A plugin can import `os`, start threads,
  patch the engine, or catch the watchdog's interrupt. The guarantee covers how the engine
  handles data, not what a plugin chooses to do. Sharing a plugin is sharing a program, as
  with `$` lines (SEC-F23-15).
- **Saves can choose arguments** (amendment 4). A save restarts a minigame with the saved
  arguments, so restore runs the plugin's `check_args` and, from API 1.1 (F24), `check_story`
  (guarded, side-effect free, in one guard entry) before the commit. A refusal gives POSITION_NOT_FOUND, never a fatal error. This is the one place
  a restore position check runs author code (F03 contract change, F23 `07` C6). The guide
  tells authors to validate types and ranges there.
- **Thread checks** (amendment 5) cover every API object. A plugin's own threads are outside
  the guarantee (9(d)), and ADR-0007's rule is unchanged for engine code.
- The list-then-read window remains on Windows (an `lstat` before an `open` that follows
  links). A swap needs write access to the game folder, which could write a plugin
  directly, so the residual is accepted. Hard links load.
- F42 ships `minigames/*.py` and package folders only, and excludes `__pycache__`, `.pyc`,
  `.pyd`, and `.so` from that folder. F41 and F44 must keep `minigames=None` (F23 `05` group
  K is part of their ACs).
- No write location is added, so ADR-0003 is unchanged.
- **API versions** (added at F25/F26). An API minor version is frozen when the first engine
  release carries it. Until then, additive amendments join the unreleased minor (F25's
  `StoryNames.item_categories`, `ctx.story`, the `codex_view` types, and
  `FocusScope.set_default` joined 1.1, and so did F27's `ctx.codex.title`), so `api = "1.1"`
  means one surface. After a release,
  any addition bumps the minor, and removals or changes bump the major (E278).

## Status history

- 2026-11-02: proposed (F23 04-technical §17.3).
- 2026-11-02: reviewed, accepted with five amendments (F23 05-security §4).
- 2026-11-02: accepted with the amendments (F23 07-architecture-review).
- 2026-11-02: amended (F24 07-architecture-review): API 1.1 adds the hooks `check_story` and
  `outcome_for`; Decision 5 and the saves consequence name them. How code is found and
  loaded is unchanged.
- 2026-11-02: amended (F25 and F26 07-architecture-reviews). Decision 7 now says how widgets
  are treated under the thread rule. A consequence about API versioning is added, and
  A5–A7 join 1.1. How code is found and loaded is unchanged.
- 2026-11-02: amended (F27 07-architecture-review). A9, `ctx.codex.title(name)` (a declared
  item's or tip's title, held or not; read-only, thread-checked through `LedgerCodexPort`),
  joins 1.1 under the versioning consequence, since 1.1 is still unreleased. Nothing else
  changes.
