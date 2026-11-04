# Studio, the scene editor

Studio edits, checks, plays, and maps your game.

## Open a game

```
python -m engine edit game
```

Leave out `game` to open the one next to `main.py`. **File ▸ Open game…**
opens another game in its own window. Drag pane titles to an
edge. **View ▸ Tabs and panes…** (or right-click the tabs) hides, locks and
resets them, for every game; going to a hidden tab brings it back.

## Your files

The **Project** panel lists Script, Images, Audio, GUI, Fonts, Minigames, and
`config.toml`. Click a file to open it: scripts and `config.toml` in the editor,
pictures and sounds on the **File preview** tab with **Copy name**.

**Add files…** copies files into the selected folder, checking each one as the game would. If a name is taken,
choose **Keep both** (the copy gets `_2`), **Replace**, or **Skip**. Refused files are
listed with the reason.

Minigames are Python code that the game runs. Only add code you trust.

**New script file** makes a `.vns` file and, unless you untick it, its `include` line in
`main.vns`. **Rename** doesn't change lines that use the old
name; the next check lists them. **Delete** is permanent.
`main.vns`, `config.toml`, and folders can't be renamed or deleted.

**File ▸ New game…** copies the starter game into an empty or new folder and opens it.

## Checks

Studio checks your script, unsaved text included, when a game opens, 1.5 seconds after you
stop typing, when you save, and on F7 (**Check now**). The status bar counts errors (⊗)
and warnings (⚠) and says "Out of date" until a newer check finishes.

The **Problems** panel lists each problem (Error, Warning, or Info) with its code, place,
and message. Click a row (or Enter) to jump to its line, marked `E` or
`W` beside its number. **View ▸ Show warnings** hides or shows warnings and info.

**Your game's code waits for you.** Until your first Preview, Save, or Check now in a
window, checks only read your files, so opening a downloaded game runs none of its code.
After that, checks also run your `define` and `default` lines, as the game does, and
warnings such as a missing picture (W12) appear.

Some checks need the game window, so they are shown on Preview only: text warnings (a line
too long for its box, a hard-to-read color), chapter card colors (W111), and loading
minigames.

## Writing help

- **Ctrl+Space** lists the words and names that fit at the cursor: statements, labels,
  images, audio, characters, endings, routes, tips, meters, minigames and their arguments.
  It also opens after `jump` and a space.
- **Insert** adds any statement's example on a new line, selecting the part to change.
- The **Help** pane explains the statement on the cursor's line, with an example and its
  section of [the script language](script-language.md).

## The story map

The **Story map** tab (Ctrl+2) draws each label as a box: arrows solid for `jump`, dashed
for `call`, dotted for a `menu` choice. Boxes are marked `start`, `not reached`, or `ends`;
`ending` labels have a double border.

The **Outline** tab (Ctrl+6) lists chapters, endings, routes, codex entries, meters,
minigames, and flowchart boxes; Enter opens one.

Click a box (or Enter) to open its scene beside the map; F6 reaches it, Esc closes
it. Map editing: [Story map editing](story-map.md). Ctrl+Enter or
Ctrl+click uses the Editor tab. Ctrl+= and Ctrl+- zoom.

If a change stops the script loading, the map keeps its last drawing, marked "out of date".
**Find scene…** (Ctrl+G) jumps to a scene by name.

## Play a scene

**Run ▸ Play this scene** (F5) saves and plays from the label above the cursor or the
selected map box. **Run ▸ Play** (Shift+F5) starts at
`label start`. **Run ▸ Stop** (Ctrl+F2) closes it.

A scene that is only reached by `call` ends the preview at its `return`.

## Start values

In *Paper Lanterns*, the example game, `label bridge` checks `bought_lantern`. Hana's
name is "???" until `label start` sets it. In **Run ▸ Play options…**, type them in the
**Start values** box, one per line, written like a `default`:

```
bought_lantern = True
hana_name = "Hana"
```

Your values replace the defaults. A default that uses another default, like
`default bonus = trust + 1`, uses the original `trust`.

Previews are normal dev runs, using your game folder's saves and persistent data unless
you tick **Play as a new player**.

## When a preview can't start

Two errors come from the start options:

- **E26b, no such label:** no label has the start name. The message suggests a close
  name or the file no `include` adds.
- **E26c, no such default:** a start value's name has no `default` (a `define` can't have
  a start value). Fix the spelling, or add a `default`.

## Without Studio

The same preview from a terminal:

```
python -m engine run game --start bridge --set "bought_lantern=True" --set "hana_name='Hana'"
```

`--start` picks the label; each `--set` gives one start value. Put text in single quotes
inside the double quotes.

## Keys

- Ctrl+S: [save](hot-reload.md). Ctrl+Shift+S: save all. Ctrl+Shift+B: [Build game](build-game.md).
- Ctrl+O: Open game… Ctrl+N: new script file. Ctrl+Shift+O: Add files…
- F2, Delete: rename or delete the selected **Project** file.
- Ctrl+Space: completion. Ctrl+G: Find scene.
- Ctrl+1, Ctrl+2, Ctrl+3, Ctrl+4, Ctrl+5, Ctrl+6: Editor, Story map,
  [Database](database.md), [Game settings](game-settings.md) (or **File ▸ Game settings**),
  File preview, Outline.
- Ctrl+=, Ctrl+-, Ctrl+0: zoom the text, or the map.
- F5: play this scene. Shift+F5: from the start. Ctrl+F2: stop. F7: Check now.
  F12: the [console](dev-console.md).
- F6, Shift+F6: next or previous area.

## Good to know

- The editor shows right-to-left text in typing order. Check how it looks in the preview.
- On macOS, F5 and F6 may need Fn, and Ctrl is Cmd.
- Tk (Studio's toolkit) has limited screen-reader support.

## For engine builders

A statement appears in Insert, Help, and completion when its feature calls
`register_doc(StatementDoc(…))` beside its `register(StatementSpec(…))`.
`tests/script/test_statement_docs.py` fails for a word without one.
