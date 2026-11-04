# Developer console

The developer console lets you look inside a running game and change it while you test:
see every variable, jump to any scene, or run one line of Python. It is for you, the game
maker. Players never get it: built games don't contain it, and `--release` turns it off.

## In the game

Press **F12** while the game runs from Studio (or from `python -m engine run`). The
console opens over the game and the story waits. **F12** or **Esc** closes it. It has three
tabs:

- **Variables**: every story variable (`default`) and meter, with its value now. Type to
  filter. Pick one, type a new value and press Enter. Values are typed like Play options'
  start values: `3`, `True`, `"Hana"`, `[1, 2]`. A Yes-No value has **Switch**, a whole
  number **-1** and **+1**. A meter needs a whole number and stays within its range.
- **Jump**: every scene. Pick one and press Enter: the story goes there and keeps its
  variables, pictures and music. On the title screen, Jump starts a new game at that scene.
- **Code**: one line of Python, like a `$` line. Enter runs it. An expression shows its
  value; Up and Down bring back earlier lines.

A change becomes part of the current step: saving now keeps it, and Back can't go to a step
before it. During a minigame or a scene replay the console only shows values.

## From Studio

You don't have to type anything in the game:

- **Run ▸ Open console in the game** (F12 in Studio) opens the console in the running game.
  If no game runs, Studio plays from the start and opens it.
- **Run ▸ Jump the game to this scene** jumps the running game to the selected box on the
  Story map, or to the scene at the editor's cursor. On the map, right-click a box and
  pick **Jump the game here**. Both are dimmed, with "no game running" beside them, until
  you choose Run ▸ Play.
- **Database ▸ Variables** and **▸ Meters** show **In the game now:** with the value in the
  running game, and **Change…** to set it. "not started" means the game is on its title
  screen.

The result shows in the status bar for 5 seconds, such as "Console: Jumped to river." If it
says "Console: the game didn't answer.", the game was loading or showing a screen that has
to finish first (a fade, a question, a warning or the error screen). Try again in a moment.

## Be careful with Code

- The Code tab runs real Python with your permissions, like the game's own `$` lines.
- The `$` rules catch mistakes, but they aren't a sandbox.
- Changes to persistent data and to files aren't undone.
- Never paste code you don't understand.

Back to [Studio](scene-editor.md).
