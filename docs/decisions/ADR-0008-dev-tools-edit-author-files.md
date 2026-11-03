# ADR-0008 — Dev tools that edit author files

Status: **accepted** — 2026-11-01 (with modifications); **amended** 2026-11-02 (F45, Amendment 1; F31, Amendment 1 §1; F46, Amendment 2; F42, Amendment 3); 2026-11-03 (F40, F41, F43, Amendment 4)
Proposed by: vn-feature-architect (F44 `04-technical.md` §17). Gaps raised by: vn-qa-engineer
(F44 `06-acceptance.md` §7, G1 and G11). Decided by: vn-system-architect (F44
`07-architecture-review.md`).

## Context

Invariant 9(b) and ADR-0003 §2 list every place the engine writes. `<game>/script/` is not on
that list, because the game never changes its own story. F44's scene editor must save the
author's `.vns` files. Its entry point, `python -m engine edit`, must also reach
`engine/tools/`, which the import table doesn't allow from `engine/__main__.py`. The editor
is a Tkinter window. It must stay free of pygame, so a hung or crashed game can never freeze
it.

## Options

1. **Treat dev tools as outside invariant 9.** This is the simplest option, but it leaves
   the editor's writes unbounded.
2. **Add a narrow, dev-only write location for one tool** with exact rules. Chosen.
3. **Have the game process save scripts** for the editor. This mixes story code with
   writing author files, and it needs a channel from the editor back to the game.

## Decision

1. **What the editor may write.** A dev tool started by `python -m engine edit` may replace
   **`.vns` files under the real `<game>/script` folder** that `GamePaths.walk_files` listed
   and that the author opened. During an atomic save, it may also create and remove its own
   temp file beside the target.
   - It never writes any other file, and it never creates a new `.vns` file. A New file
     action (PR-F44-22) would need an amendment to this ADR.
   - **Links are never followed out of `script/`.** The real path is checked when the file
     opens and checked again at every save: the target's folder must lie inside the real
     `<game>/script`, and the target must be a regular file, not a link or junction.
   - The temp file is `.<name>.<8 random hex>.tmp` in the same folder. It is created with
     `O_CREAT | O_EXCL`, which fails on any existing entry, so a link planted at that name
     is never followed. It is written, fsynced, and moved into place with `os.replace`. A
     failed save leaves the original bytes and no temp file. A race between the check and
     the replace is accepted, because this is a dev tool on the author's own machine.
   - **Dev runs only.** `edit` doesn't exist in frozen builds. Combined with `--release`, it
     is a usage error (exit 2).
   - **Never from the game process.** A game started with `--report-to-editor` writes only
     to its own stdout. It writes no new file.
2. **Imports.**
   - `engine/__main__.py` may import `engine.tools.editor`, but only inside the `edit`
     handler (a function-level import). `app` never imports `tools`.
   - The editor process imports `engine.app.cli` as its entry point and nothing else from
     `app`. `cli.py` must keep importing no pygame at module level.
   - `engine/tools/editor/` may import `core`, `script`, and stdlib (including `tkinter`).
     It never imports pygame, `app`, `render`, `ui`, `audio`, or `runtime`. It runs no
     author code. `tests/test_import_rules.py` enforces this with its own row.
   - `engine/tools/__init__.py` stays empty, so later tools (F41, F42) don't pull each other
     in.
3. **Threads in the editor.** The editor's reader thread runs in a process that holds no
   engine state, so ADR-0007's rule doesn't apply. It touches only the child's pipe and a
   queue. All Tk calls stay on the main thread.
4. **`core/startvalues.py`** joins `core`. It is stdlib-only (`ast`, `math`, `keyword`) with
   no import-time side effects. It holds `StartOptions` and the `--set` literal parser, which
   never evaluates its input. `cli`, `script`, `runtime`, and `tools` all need it, and `core`
   is the only package all four may import.
5. **Packaging.** F42 excludes `engine/tools/` from packaged builds, and the frozen command
   line defines none of `edit`, `--start`, `--set`, or `--report-to-editor`.

Modifications to the draft (F44 `04` §17): the save-time containment check and the exclusive
temp file (QA G1); the rule that the editor process imports only `cli` from `app`; a separate
import-table row for `tools/editor`; an empty `tools/__init__.py`; the thread note; the F42
exclusion stated as a decision (QA G11); and an amendment required for New file.

## Consequences

- ADR-0003 §2 gains a "Dev tool (F44 editor)" row that points here. Invariant 9(b) names
  this ADR.
- The `.vns` files and their temp file are the only new place written, only while the
  author edits in a dev checkout, and never by a game.
- The editor never imports pygame, so it can't be frozen by a preview, and its tests run
  without SDL.
- F42 has one more exclusion to enforce and test.
- F11 and F12 can reuse or lift the atomic-save routine instead of writing a second one
  (F44 `07` I-17).
- Any other tool that writes author files (for example a future F41 autofix) needs its own
  amendment to this ADR.

## Amendment 1 — Studio (F45)

Proposed by: vn-feature-architect (F45 `04-technical.md` §16). Decided by: vn-system-architect
(F45 `07-architecture-review.md`, accepted with modifications).

**Context.** F45 grows the editor into Studio: it adds, creates, renames and deletes files in
the game's asset folders, edits `config.toml`, creates a new game folder, and runs a
**check child** that loads and launches the game without a window. Decision 1 allowed only
replacing opened `.vns` files and required this amendment for New file.

**Decision.** Decision 1 is widened as follows; everything else in it still holds (dev runs
only, never from the game process, `write_atomic`'s exclusive temp, the accepted race).

1. **Where.** Studio (started by `python -m engine edit`) may act only under the real game
   folder, in the group folders `script/ASSET_GROUPS` names (`script`, `images`, `audio`,
   `gui`, `fonts`, `minigames`, and F31's `files`) and their real subfolders, plus
   `config.toml`. `characters` (F31's write root) is never a group folder. A write
   targets a `GamePaths.real_dir` path plus a validated name, never a path from content.
   Group folders are never an ADR-0003 write root.
2. **What.** Create a missing group folder (one `os.mkdir`; never a subfolder); create a file
   (`write_atomic(check=True, expected=None)`); replace a regular file (stamp-checked);
   rename a regular file within its folder, never replacing (POSIX link-then-unlink;
   Windows `os.rename`); delete a regular file (`safefile.remove_file`); replace
   `config.toml` when it is a regular file whose real path is its listed path. Each act
   re-runs F45 `04` §7.5's (F) folder, (N) name, (C) case-insensitive clash and (E) existing
   regular file checks at the moment it happens. A new file gets the mode `0o666 & ~umask`;
   a replaced file keeps its mode.
3. **New game folder.** An author-chosen folder that is missing (with a real parent) or an
   empty real folder that isn't a reparse point. Studio creates it, its group folders and
   the starter files (`engine/data/starter/`) by exclusive create, and nothing else.
4. **The check child** (`python -m engine check`, `engine/tools/check.py`) writes nothing:
   no bytecode (`-B`), no log handlers, no saves, settings or persistent data (an in-memory
   store), and author `print` output goes to the null device. It has its own import row
   (`core`, `script`, `runtime`; never pygame, `app`, `render`, `ui`, `audio`, `persist`,
   `meta`, `minigames`). `engine/__main__.py` imports `engine.tools.check` only inside its
   `check` handler; `check` doesn't exist in frozen builds and is a usage error with
   `--release`.
5. **When author code runs.** The check child runs the game's `define`/`default` code and
   `module()` helpers only after the author's first **Preview, Save or Check now** in that
   Studio window (not remembered between sessions). Until then Studio's checks run with
   `--no-launch` (config and story load only, which evaluate no author code). Opening a
   folder therefore never runs its code, as in F44. Studio's own process still runs none.
6. **Imports.** `tools/editor` keeps its row (`core`, `script`, stdlib, `tkinter`) and never
   imports `engine.tools.check` or `runtime`.

**Modifications to the draft:** the arming rule (5), `--no-launch`, the lazy `__main__`
import, `meta` in the child's banned list, file modes, and "never a subfolder" (2).

**Consequences.** ADR-0003 §2's dev-tool row and AC-F44-17 widen. Invariant 9(b) names the
amended exception. F42 still excludes `engine/tools/` (so a frozen build has neither `edit`
nor `check`) and may exclude `engine/data/starter/`. A future tool that writes author files
(e.g. an F41 autofix) still needs its own amendment.

## Amendment 2 — Studio layout folder (F46)

Proposed by: vn-feature-architect (F46 `04-technical.md` §16). Decided by: vn-system-architect
(F46 `07-architecture-review.md` §2.1, accepted with modifications; recorded here at the F42
review).

**Context.** F46 keeps story-map box places outside the script.

**Decision.** Dev runs only; never the game process or the check child.
1. Studio may create `<game>/.studio/` with one `os.mkdir` under the real game folder
   (`ensure_real_dir`'s dev rule), and create or replace regular files in it with
   `write_atomic`, never through a link. A new file gets `0o666 & ~umask`.
2. **Named files only.** `storymap.json` (F46), `build.json` (F42, Amendment 3) and
   `studio.json` (F47: Guide open and done state, "played", "sample"; main session 2026-11-02),
   each with its `write_atomic` temp. Studio never deletes, renames or makes subfolders there. Another file
   name needs a line here.
3. A read or write failure never blocks or dirties a script or a build.
4. The game, the loader and the check child never read the folder. It is not a group folder
   (`GamePaths` listings, `OverlayPaths` and the project panel never see it) and not an
   ADR-0003 write root.

**Consequences.** Invariant 9(b) names it. Packaged builds exclude `<game>/.studio/` (F42
PR-F42-05). It is not git-ignored; version control is the author's choice.

## Amendment 3 — Build output and the build tool (F42)

Proposed by: vn-feature-architect (F42 `04-technical.md` §18). Decided by: vn-system-architect
(F42 `07-architecture-review.md` §3, accepted with modifications).

**Context.** F42's `python -m engine build` and Studio's **Build game…** dialog create, rename
and delete outside the game folder, and Studio can run pip. Amendment 1 doesn't allow either.

**Decision.** Decision 1 and Amendment 1 still hold: dev runs only; never the game process or
the check child; `build` doesn't exist in frozen builds and is a usage error with `--release`.
1. **Where.** Only the author-chosen *Save to*: a real folder that is neither inside the real
   game folder nor contains it, and is not inside `<engine root>/engine` (real paths, normcase,
   both ways). Plus `.studio/build.json` under Amendment 2. The packer child's own per-user
   cache is a third-party write, accepted (SEC-F42-04).
2. **What.** Create *Save to* (one `os.mkdir`, real parent); one staging folder per run
   (`.<folder>.building-<8 hex>`, `os.mkdir`, staging marker first) with files by exclusive
   create; rename an earlier build aside (`.<folder>.old-<8 hex>`) and the new one in.
3. **Deletes.** Only this run's staging; the earlier build at exactly `<Save to>/<computed
   name>` (and its `.zip`) after the strict marker test and the author's confirmation
   (`REPLACE_ASK` or `--replace`); stale staging and aside entries older than 60 s that match
   their pattern and marker. One no-follow, real-path-contained, capped walker
   (`tools/build/tree.py`) over `safefile.remove_file`; never `shutil.rmtree`; never a name
   from `build.json`, a marker or a report event. After **Cancel build**, Studio deletes staging
   only after the process tree has exited, joining a bare `STAGING_RE` name to its own *Save to*.
4. **Reads.** The game folder only by no-follow real-entry walks with handle identity checks.
   The build child and the packer never import, `exec` or `compile` game-folder code, and no
   game-folder path reaches the packer. Engine-install files (Python's and the bundled
   libraries' licenses, `engine/data`) are read at fixed paths.
5. **Children.** Argument lists, no shell, `cwd = engine_root()`, `-E` with `PYTHON*` removed,
   never elevated; **Cancel build** kills the whole tree. Author code runs only in the check
   grandchild (Amendment 1 §4–5; a Build arms it; the CLI `build` equals `run`).
6. **pip.** Only `-E -m pip install --require-hashes --only-binary=:all: --no-input
   --disable-pip-version-check -r <engine root>/requirements-build.txt` (every package `==`
   with SHA-256, no index option), on the author's click, output redacted. Studio never imports
   PyInstaller; versions come from `importlib.metadata`.
7. **OS queries.** The build child reads free space on *Save to*'s volume
   (`shutil.disk_usage`) and installed package versions. Neither is personal data; this is a
   dev-tool exception to invariant 9(c)'s allow-list.
8. **Imports.** `tools/build`: `core`, `script`, stdlib; pygame only in `icon.py`; never
   PyInstaller (it runs as a child), `app`, `runtime`, `render`, `ui`, `audio`, `persist`,
   `meta`, `minigames` or another `tools` module. `tools/editor` may import only
   `tools.build.{names,texts,rules,tree,procs}`. `engine/__main__.py` imports
   `tools.build.command` only inside its `build` handler and passes it to `app.cli.main` as
   `builder=`, so `app` never imports `tools`.

**Modifications to the draft:** `build.json` named under Amendment 2; the `engine/` exclusion
for *Save to*; the packer cache; no event path in Cancel cleanup; OS queries (7); fixed
engine-install reads; the `builder=` injection.

**Consequences.** Invariant 9(b) and 9(c) and ADR-0003 §2's dev-tool row name Amendment 3.
*Save to* is written only on an explicit Build. AC-F42-37 and -39 test it. Any later tool that
writes outside the game folder needs its own amendment.

## Amendment 4 (M7 tools: F40, F41, F43)

**Context.** F40 puts a dev tool inside the running game. F41 adds a second check-child
command. F43's Translate tab writes `.po` files and exports a file wherever the author
chooses.

**Decision.**
1. **In-game dev tools (F40).** A dev tool that runs inside the game process lives under
   `engine/tools/` and reaches the game only through an **inert slot** on `App` (`console`,
   None unless filled), typed by a Protocol in `app/`. Only `engine/__main__.py` fills it,
   in dev runs and never in a Try-it or launcher run, through a function that imports
   the tool inside itself (as `builder=`). Every call site checks `App.dev` and a filled
   slot. `tools/console` may import `core`, `script`, `runtime`, `render`, `ui`, `app`, and
   never `meta`, `persist`, `audio`, `minigames` or another `tools` package. It writes no
   file. Author code typed into it is author code (invariant 9(d)), so its persistent
   writes behave as `$` lines'. Packaged builds exclude it with `engine/tools/`, and the
   leak scan holds its needle.
2. **`lint` (F41).** `python -m engine lint` is a dev-only command run through
   `tools/check.py` (lazy `linter=` import). It writes nothing and follows §4's rules.
   `tools/lint.py` has check.py's row and only check.py imports it.
3. **Translations (F43).** `ASSET_GROUPS` gains `translations`, so Amendment 1 §1's group
   folders include `<game>/translations/`. **Export…** may create or replace one regular
   file at the path the author picks in a Save-as dialog (`write_atomic`, exclusive temp
   beside it), and only on that explicit act. **Import…** reads one author-picked file of up
   to 16 MB and writes only through the Translate tab's normal `.po` save.

**Consequences.** Any later in-game dev tool reuses this slot pattern. Export is the second
tool that may write outside the game folder (after Amendment 3) and is limited to one
author-chosen file.

## Status history

- 2026-11-01: proposed (F44 04-technical §17).
- 2026-11-01: accepted with modifications (F44 07-architecture-review).
- 2026-11-02: Amendment 1 (Studio file operations, new game folder, check child) proposed in
  F45 `04` §16 and accepted with modifications (F45 `07`).
- 2026-11-02: Amendment 1 §1 widened at F31 approval (F31 `07` §5, I-9): the group folders add
  `files` (the `ASSET_GROUPS` row for meta-file originals, kind `meta`). `characters` is never a
  group. No other change. Status remains accepted.
- 2026-11-02: Amendment 2 (F46 `.studio/` layout folder), accepted in F46 `07` §2.1, recorded
  here at the F42 review; `build.json` added as its second named file.
- 2026-11-02: Amendment 3 (F42 build output, `build.json`, pip) proposed in F42 `04` §18 and
  accepted with modifications (F42 `07` §3).
- 2026-11-03: Amendment 4 (in-game dev tool slot, `lint`, `translations` group and Export)
  accepted in `specs/F43-localization/07` (joint M7 tools review).
