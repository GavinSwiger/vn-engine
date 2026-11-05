# Notes for AI agents

This folder is a visual novel made with **vn-engine**. The author is often not a
programmer: talk about scenes, characters, pictures, sounds and settings, and keep changes
small enough to review.

## Use the game's tools

vn-engine serves this game to AI apps over MCP (`python -m engine assist-mcp <game folder>`;
in Studio, **Help ▸ Connect an AI app…** sets it up). When those tools are connected, use
them rather than reading and writing files yourself. They know the language, check every
change, and show the author a diff before anything is written.

1. `project_summary`, then `story_map` or `scene` to see what's there.
2. `language_reference` before writing script; `language_docs` for one topic.
3. `propose_edit` for script changes (exact text, found once), then `apply_edit` with the id
   it returns. `undo_apply` takes the last one back.
4. Settings: `game_settings` (what this game sets), `settings_reference` (every setting,
   with search), `propose_settings` (change them by section and key).
5. `engine_docs` for the guides: game settings, screens and UI, minigames, meta files, the
   Database, the story map, building the game.
6. `run_check` after changes: problems with file and line.

## If you edit files directly

- `script/*.vns`: the story. `label name:` starts a scene; blocks nest by 4 spaces.
  `main.vns` holds `label start`. Characters, variables and other declarations sit at the
  top level of any script file; Studio's Database adds new ones to `script/database.vns`.
- `images/`, `audio/`: a picture's name is its path inside `images/` without the
  extension (`images/bg/river.png` is `bg river`). There is no list to keep.
- `config.toml`: the game's settings. Only keys the engine knows are allowed; run
  `python -m engine lint <game folder>` after changing it or any script.
- `minigames/` holds Python code the game runs. Change it only when asked.
- Leave `.studio/` alone: it is Studio's own state.

After any change, `python -m engine lint <game folder>` lists every problem. Fix what your
change caused before you finish.
