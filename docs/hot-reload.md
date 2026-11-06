# Update the running game

While the game runs from Studio's Play bar, you don't have to replay to see an edit. Save a
script file or `config.toml` (Ctrl+S) and the game updates: it closes, opens again in the
same spot on screen, and carries on from the same place with your new story. It says
"Story updated." Back (the mouse wheel) still reaches the lines you saw before.

Studio checks your saved files first. The status bar shows **▶ Updating…**, then
**▶ Running. Updated at 14:32.**

- **A mistake holds the update.** If the check finds an error, the game keeps running the
  old story and says "Story not updated". The status bar says "Running the old story: fix
  1 problem to update it.", and Problems lists the error. Fix it and save again.
- **Your line was removed?** The game goes back to the newest earlier line that still
  exists. If the whole scene is gone, it starts again.
- **Stopped with an error?** Fix the line and save: the game carries on from the line
  before the error.
- **New images or sounds?** Press Ctrl+R, or **Update the running game** in the **Run**
  menu. It updates without a save.

Turn off **Update the game on save** in the **Run** menu to update only with Ctrl+R. It is
on each time Studio opens.

Good to know:

- Only saves made in Studio count; edits from other programs need Ctrl+R.
- Unsaved text in other files is left out: the update uses your saved files.
- The music starts over, and an open menu closes.
- An update writes no save file.
- The first `file` line you add reaches the disk only after you start the game again
  (see [Meta files](meta-files.md)).
- **Run ▸ Play**, **Play this scene** and **Stop** work as before: they start the
  game again, or end it.

## Where the game opens

**▶ Play** opens the game beside Studio when the screen has room, right of Studio first,
then left, at its own size or smaller. If Studio fills the screen, tick **Game beside
Studio** (in the **▾** next to **▶ Play**, or the **Run** menu): Studio then leaves
maximized and takes the left part of the screen, and the game the right. When the game
closes, Studio goes back as it was, unless you moved or resized it. Studio remembers the
tick for every game.

Limits: on Windows, Studio uses the monitor it is on, less the taskbar. On macOS and Linux
it sees one screen and no dock. A game you made fullscreen (F11) stays fullscreen. Moving
Studio later doesn't move the game.

Back to [Studio](scene-editor.md).
