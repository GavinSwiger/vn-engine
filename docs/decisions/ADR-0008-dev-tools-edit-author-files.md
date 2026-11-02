# ADR-0008 — Dev tools that edit author files

Status: **accepted** — 2026-11-01 (with modifications); **amended** 2026-11-02 (F45, Amendment 1; F31, Amendment 1 §1)
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

## Status history

- 2026-11-01: proposed (F44 04-technical §17).
- 2026-11-01: accepted with modifications (F44 07-architecture-review).
- 2026-11-02: Amendment 1 (Studio file operations, new game folder, check child) proposed in
  F45 `04` §16 and accepted with modifications (F45 `07`).
- 2026-11-02: Amendment 1 §1 widened at F31 approval (F31 `07` §5, I-9): the group folders add
  `files` (the `ASSET_GROUPS` row for meta-file originals, kind `meta`). `characters` is never a
  group. No other change. Status remains accepted.
