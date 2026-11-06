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
- **New images or sounds?** Press **⟳ Update** beside **■ Stop** (Ctrl+R, or **Update the
  running game** in the **Run** menu). It updates without a save.

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
then left, at its own size or smaller.

The pin at the right of the status bar switches between two ways (also **Dock the game
beside Studio** in the **▾** next to **▶ Play** and in the **Run** menu; Studio remembers it
for every game):

- **📌 Docked** (the default): the game opens without a title bar, and when you move or resize Studio, the
  game moves with it. If Studio fills the screen, Studio leaves maximized and takes the
  left part; the game gets the right. When the game closes, Studio goes back as it was,
  unless you moved or resized it.
- **Floating**: the game opens in its own window, which stays where you put it.

Click the game to give it the keys; click Studio to take them back.

Limits: on Windows, Studio uses the monitor it is on, less the taskbar. On macOS and Linux
it sees one screen and no dock, and the game follows only where the system lets programs
move windows (not on Wayland). If there is no room beside Studio, the docked game stays
where it is. A game you made fullscreen (F11) or maximized stays so and doesn't follow.

Back to [Studio](scene-editor.md).
