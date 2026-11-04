# ADR-0003 — File locations, `app_id`, and engine I/O boundaries

Status: **accepted** — 2026-11-01 (with modifications)
Proposed by: vn-feature-architect (F01 `04-technical.md` §17). Reviewed by:
vn-security-reviewer (F01 `05-security.md` §6.4, OQ-S1, OQ-S2). Decided by:
vn-system-architect (F01 `07-architecture-review.md`).

## Context

In development, logs belong at `<game>/logs/` (PR-F01-36). A packaged game installed in a
read-only location (e.g. Program Files) cannot write there, and saves (F11), persistent
data (F12), and settings (F16) face the same problem. Several games built on the engine
can be installed for the same user, so their per-user folders must not collide. The seed
invariant 9 said all filesystem access goes through `engine/meta/` and only inside the game
folder, which contradicts any per-user write location and predates engine infrastructure
I/O (config, assets, logs, DPI queries) that exists before F31.

## Options

- Locations: (1) always the game folder; (2) always a per-user folder; (3) game folder in
  dev builds, per-user folder in release builds.
- Per-user folder identity: (a) game folder name; (b) game title; (c) an explicit author-set
  id; (d) a fallback with a hash of something stable.

## Decision

1. **Build modes.** A run is a *release* run when frozen (F42) or started with `--release`.
   Otherwise it is a *dev* run.
2. **Write roots.** The engine creates, modifies, renames, or deletes files only in these
   roots, and never follows a link out of them:

   | Data | Dev run | Release run |
   |---|---|---|
   | Logs (F01) | `<game>/logs/` | `user_log_dir(app_id)` |
   | Saves (F11) | `<game>/saves/` (a real directory) | `user_data_dir(app_id)/saves/` |
   | Persistent data (F12) | `<game>/persistent/` | `user_data_dir(app_id)/persistent/` |

   Save files (F11): `<slot>.vnsave`, where the whole name matches `SLOT_NAME_RE`
   (`(auto|quick|page(?:[1-9][0-9]?|100))-[1-6]\.vnsave`, case-exact), and the writer's temp
   files `.<slot>.vnsave.<8 hex>.tmp`. Flowchart node states (F20) share this root:
   `node-<16 hex>.vnnode` (the whole name matching `NODE_NAME_RE`, `node-[0-9a-f]{16}\.vnnode`,
   which no slot, persistent, or settings name or temp matches) and their temps
   `.node-<16 hex>.vnnode.<8 hex>.tmp`. They are written by writer owner `flow` and removed by
   F20's eviction, `flowchart forget`, and Delete progress, all through one name-checking helper
   (`persist/nodestates.py` `NodeFolder`), and only while the root passes the real-folder check
   (else F20 makes no file call there for the session). Nothing else in the folder is read,
   written, or deleted; a delete removes only the entry at a slot or node name (never a link's
   target, never recursively).

   Persistent-data files (F12): `persistent.json`, `persistent.bad.json` (one quarantined
   copy, never read), and the writer's temp files `.persistent.json.<8 hex>.tmp`. Nothing else.
   | Meta files (F31): only the script's literal names (≤ 32, `META_NAME_RE`) and their temps `.<name>.<8 hex>.tmp` | a real `<game>/characters/`, through `engine/meta/` and writer owner `meta` (the dev real-folder rule in every run; no fallback; W197 when unwritable) | same |
   | Dev tool: F44 editor / F45 Studio (ADR-0008, Amendment 1) | the `.vns` files under the real `<game>/script` that the editor listed and the author opened; from F45, files created, replaced, renamed, or deleted in the real group folders (`script`, `images`, `audio`, `gui`, `fonts`, `minigames`, and F31's `files`) and their real subfolders, a missing group folder, `config.toml`, and an author-chosen new game folder; `<game>/.studio/storymap.json` (F46, ADR-0008 Am. 2); plus its own temp file beside each; never from the game process or the check child | not available |
   | Studio per-user files (F48, ADR-0008 Am. 5): `assistant.json` in `studio_user_dir()`; `key-<16 hex>.txt` in `studio_user_dir(local=True)`, only when no OS keychain exists (mode 0600); each with its `write_atomic` temp | the folders in §3, a real directory created 0700; never from the game process or the check child | not available |
   | Settings (F16) | `<game>/settings/` (a real directory) | `user_data_dir(app_id)/settings/` |

   Settings files (F16): `settings.json`, `settings.bad.json` (one quarantined copy, never
   read), and the writer's temp files `.settings.json.<8 hex>.tmp`. Nothing else.

   A feature that needs another write location amends this table through its own
   architecture review (F16 did so for settings).
3. **Per-user folders.**
   - `user_data_dir(app_id)`: Windows `%APPDATA%\vn-engine\<app_id>\`, macOS
     `~/Library/Application Support/vn-engine/<app_id>/`, other
     `$XDG_DATA_HOME/vn-engine/<app_id>/` (or `~/.local/share/…`).
   - `user_log_dir(app_id)`: Windows **`%LOCALAPPDATA%\vn-engine\<app_id>\logs\`** (logs
     must not roam with the profile; security R3). macOS and other:
     `user_data_dir(app_id)/logs/`.
   - `studio_user_dir(*, local=False)` (F48, dev tools only): Windows
     `%APPDATA%\vn-engine\_studio\` (roaming: settings, consent) or, with `local=True`,
     `%LOCALAPPDATA%\vn-engine\_studio\` (a fallback key file must not roam); macOS
     `~/Library/Application Support/vn-engine/_studio/` and other
     `$XDG_DATA_HOME/vn-engine/_studio/` (or `~/.local/share/…`) for both. `_studio` fails
     `APP_ID_RE`, so no game's folder can be it. It returns None when the folder can't be
     made real; Studio then saves no setting. Files are read with `read_regular` (64 KiB for
     `assistant.json`, 4 KiB for a key file) and parsed with strict types.
   - Environment-derived bases are used only when they are absolute paths
     (`XDG_DATA_HOME` per the XDG spec; `APPDATA`/`LOCALAPPDATA` as absolute drive or UNC
     paths). Otherwise the documented default is used, or the folder counts as not
     writable. These functions never return a relative path. (SEC-F01-17)
4. **`app_id` (answers OQ-S1).**
   - Format: `^[a-z0-9][a-z0-9-]{0,39}$`, and not a Windows reserved name (`con`, `prn`,
     `aux`, `nul`, `com0`–`com9`, `lpt0`–`lpt9`). `user_data_dir` and `user_log_dir` raise
     `ValueError` for anything else. (SEC-F01-16)
   - Source: the `[game] id` key in `config.toml`, **introduced by F01** (optional). An
     invalid value is a normal config error (PR-F01-11).
   - Fallback when `[game] id` is unset: `slugify(game folder name)`, where reserved
     results get a `-game` suffix. The fallback may be used **for logs only**. Logs are
     the only data whose collision is harmless (retention touches only engine log names).
   - **Rule:** no feature may write anything other than logs under `user_data_dir` or
     `user_log_dir` using a fallback id. In a release run without `[game] id`, such a
     feature refuses to write and tells the author which key to set (F11/F12/F16 choose
     the UX). F42 refuses to package a game without `[game] id`. F12's UX: W53 at launch,
     and the session runs on in-memory data with no read or write under `user_data_dir`.
     F16's UX: W74 once per session; settings apply for that session only, with no read or
     write under `user_data_dir`. F11's UX: W80 once; the Save, Load, and quick save/load
     entries are hidden and F5/F9 do nothing, with no file call.
   - The example game ships with `id` commented out, with a comment telling authors to set
     a unique id before release. So a copied template never shares an id by default.
   - Because `[game] id` lives in `config.toml`, a release run chooses its log folder
     after config is loaded. Log records emitted before that are buffered and written to
     the file once it opens. None are lost. **Dev runs use the same startup path**
     (amended in F01 review round 2, C-7): they also buffer early records and open the
     log after config is loaded. Only the location rule differs by mode. The buffer is
     memory-only, redacted on entry, and bounded (SEC-F01-23) in every run.
5. **Log folder safety.** `<game>/logs` is used only if it is a real directory (not a
   symlink, junction, or other reparse point) whose real path is `<game>/logs`. Rotation
   and retention act only on regular files with engine log names, and new logs are created
   with exclusive create. (SEC-F01-13, SEC-F01-14)
   A link at or above a per-user root (for example, the player moved `vn-engine` to
   another drive) only locates that root and is followed. Links inside any root are never
   followed. This is what invariant 9(b)'s "never follows a link out of them" means.
   The same rules apply to F12's dev root `<game>/persistent`, F16's dev root
   `<game>/settings`, and F11's dev root `<game>/saves` (each a real directory whose real path is itself, checked at launch and
   before each write; a linked dev root is neither read nor written). Stale-temp cleanup removes only regular
   files with the engine's temp name that are over 60 s old: at most 16 per launch, after
   examining at most 1,000 entries (6,000 for F11's saves root, which also holds up to 4,000
   F20 node files). F20 finds its own stale node temps in its bounded launch listing (≤ 20,000
   entries, regular files only) and removes them with its other removals, ≤ 64 per frame.
6. **Fallback chain.** If the chosen log folder is not writable, use the other mode's
   location, then console-only. The error screen always shows the location actually used,
   in environment-style form (`%LOCALAPPDATA%\…`, `~/Library/…`, `$XDG_DATA_HOME/…`), so the
   OS username never appears.
7. **Invariant 9 scope.** Invariant 9 is reworded (see `docs/architecture.md`) to cover any
   file or OS access whose target comes from content or saved data, whichever package does
   it, to list the write roots by reference to this ADR, to confine OS queries outside
   `meta/` to the read-only allow-list in `engine/app/platform.py`, and to state that author
   code is trusted and not sandboxed.
8. **Home and environment lookups (security C-S5).** Reading the home folder and the
   environment variables that locate the folders in §3 (`APPDATA`, `LOCALAPPDATA`,
   `XDG_DATA_HOME`) and the redactor's roots (also `TEMP`, `TMP`, `sys` prefixes) is not an
   OS query under invariant 9(c). These reads stay in `engine/core/paths.py` and
   `engine/core/logsetup.py` (enforced by an AST test), and their values are never output
   unredacted. They are not moved to `engine/app/platform.py`, because `user_data_dir` must
   stay usable from the pygame-free `persist` package (F11, F12), which cannot import `app`.
9. **One routine for files in write roots (F12, F44 I-17).** `engine/core/safefile.py` (stdlib
   only) is the one implementation of the real-directory check, the regular-file read (`lstat`
   regular, no-follow open, `fstat` equal to `lstat`, size cap), the atomic write (exclusive
   random temp file, fsync, `os.replace`), stale-temp cleanup, and file stamps. F44's editor save
   and F12 use it, and F11 and F16 reuse it. File names in a write root are engine constants or
   engine-generated, never taken from content or saved data.

Modifications to the draft: logs under `%LOCALAPPDATA%` on Windows (`user_log_dir`);
`[game] id` introduced by F01 instead of F42; the `app_id` format and the logs-only
fallback rule; the write-roots table; log folder safety; environment hardening; the
buffered early log records; invariant 9 wording.

## Consequences

- F11, F12, F16, and F42 inherit one location rule and one identity rule.
- Release players can always find logs; the error screen says where.
- Two games never share save or persistent folders by default.
- Authors must set `[game] id` before release; F42 enforces it.
- Startup is slightly more involved (buffered early log records). Dev and release runs
  share that one path, so every dev and CI run tests it.
- A game copied to another folder keeps its saves in release runs (the id is in config,
  not derived from the path).

## Status history

- 2026-11-01: proposed (F01 04-technical §17).
- 2026-11-01: accepted with modifications (F01 07-architecture-review), incorporating
  security review §6.4 R1–R3 and OQ-S1.
- 2026-11-01: amended at F01 approval (review round 2): dev runs share the buffered
  startup path (§4, feature architect C-7); links at or above per-user roots (§5); home
  and environment lookups are not OS queries and stay in `core/paths.py` and
  `core/logsetup.py` (§8, security C-S5). Status remains accepted.
- 2026-11-01: amended at F44 approval: §2 gains the dev-tool row for the scene editor's
  `.vns` saves (ADR-0008). Status remains accepted.
- 2026-11-01: amended at F12 approval (F12 `07`): §2 names the persistent files; §4 gives F12's
  W53 UX; §5 applies the real-directory and temp-cleanup rules to `<game>/persistent`; new §9
  makes `core/safefile.py` the one routine for files in write roots. Status remains accepted.
- 2026-11-02: amended at F16 approval (F16 `07`): §2 gains the Settings row and names its three
  files; §4 gives F16's W74 UX; §5 covers `<game>/settings`. `SAVE_DIRNAMES` gains `settings`
  (SEC-F02-11), and F42 excludes the folder from packages. Status remains accepted.
- 2026-11-02: amended at F11 approval (F11 `07`): §2 fixes the dev saves folder at
  `<game>/saves/` and names the save files (`*.vnsave` slot names and their temps only); §4
  gives F11's W80 UX; §5 covers `<game>/saves`. F42 excludes the folder from packages. Status
  remains accepted.
- 2026-11-02: amended at F20 approval (F20 `07`, SEC-F20-01, -05, -15): §2's saves root also
  holds F20's node-state files and their temps (owner `flow`, one name helper, engine-generated
  names only, deletes by eviction, forget, and Delete progress); §5 raises F11's saves-root temp
  scan to 6,000 entries and records F20's own temp scan. No new folder. Status remains accepted.
- 2026-11-02: amended at F45 approval (F45 `07`): §2's dev-tool row widens to Studio's file
  operations in the game's group folders, `config.toml`, and a new game folder (ADR-0008
  Amendment 1). No write root changes. Status remains accepted.
- 2026-11-02: amended at F31 approval (F31 `07` §5): §2's meta files row replaces "F31 decides
  behavior in read-only installs" with F31's rule: only the script's literal names (≤ 32,
  `META_NAME_RE`) and their temps, in a real `<game>/characters/` under the dev real-folder rule
  in every run, with no fallback (W197 when unwritable). Changes run as writer jobs of owner
  `meta` (ADR-0007). The dev-tool row's group folders add `files` (ADR-0008 Amendment 1);
  `characters` is never a group folder. Status remains accepted.
- 2026-11-02: amended at F46 (F46 `07` §5, I-11): §2's dev-tool row adds
  `<game>/.studio/storymap.json` (ADR-0008 Amendment 2). `.studio/` is not a write root; packaged builds exclude it (F42). Status
  remains accepted.
- 2026-11-03: amended at F43 approval (`specs/F43-localization/07` I-11): §7's allow-list
  gains the **system UI language**. `engine/app/platform.py`'s `system_ui_language()` returns
  a validated language tag or None, and the value is never logged (only the chosen game
  language is). On Windows it may load `kernel32` (System32 only, as `user32`/`shcore`) for
  exactly one function, `GetUserPreferredUILanguages`, with `argtypes`/`restype` declared;
  any other `kernel32` name stays forbidden (SEC-F01-18). Elsewhere it reads `LC_ALL`, then
  `LC_MESSAGES`, then `LANG`. §8's environment rule now names three modules: `core/paths.py`
  and `core/logsetup.py` (folder and redaction-root variables, not OS queries) and
  `app/platform.py` (the three locale variables only, an OS query under 9(c)). The privacy
  AST and supply-chain tests enforce both. `translations/` is a read-only game folder (read
  through `GamePaths`), not a write root. Status remains accepted.
- 2026-11-04: amended at F48 approval (F48 `07`): §2 gains the Studio per-user files row
  (`assistant.json`, `key-<16 hex>.txt`; dev tools only) and §3 gains `studio_user_dir`
  (roaming, and non-roaming with `local=True`, under `vn-engine/_studio`). §8 is unchanged:
  the folder variables are still read only in `core/paths.py`. The provider key variables and
  proxy settings F48 reads are ADR-0008 Amendment 5 §7, not §8. Status remains accepted.
