# Studio, the scene editor

Studio edits, checks, and previews your game, and maps your story.

## Open a game

```
python -m engine edit game
```

Leave out `game` to open the game next to `main.py`. The window holds the **Project**
panel, **Start values**, four tabs, **Problems**, and **Help**.

## Your files

The **Project** panel lists Script, Images, Audio, GUI, Fonts, Minigames, and
`config.toml`. Click a file to open it: scripts and `config.toml` in the editor (Ctrl+S
saves), pictures on the **Asset** tab with **Copy name**.

**Add files…** copies files into the selected folder, checking each one as the game would. If a name is taken,
choose **Keep both** (the copy gets `_2`), **Replace**, or **Skip**. Refused files are
listed with the reason.

Minigames are Python code that the game runs. Only add code you trust.

**New script file** makes a `.vns` file and, unless you untick it, its `include` line in
`main.vns`. **Rename** doesn't change lines that use the old
name; the next check lists them. **Delete** is permanent: the file doesn't go to the trash.
`main.vns`, `config.toml`, and folders can't be renamed or deleted.

**File ▸ New game…** copies the starter game into an empty or new folder and opens it.

## Checks

Studio checks your script, unsaved text included, when a game opens, 1.5 seconds after you
stop typing, when you save, and on F7 (**Check now**). The status bar counts errors (⊗)
and warnings (⚠) and says "Out of date" until a newer check finishes.

The **Problems** panel lists each problem (Error, Warning, or Info) with its code, place,
and message. Click a row, or select it and press Enter, to jump to its line, marked `E` or
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
  It also opens after a word such as `jump` and a space.
- The **Insert** menu adds any statement's example on a new line and selects the part to
  change.
- The **Help** pane explains the statement on the cursor's line, with an example and its
  section of [the script language](script-language.md).

## The story map

The **Story map** tab (Ctrl+2) draws each label as a box: arrows solid for `jump`, dashed
for `call`, dotted for a `menu` choice. Boxes are marked `start`, `not reached`, or `ends`;
`ending` labels have a double border; boxes show chapters and minigames.

The **Outline** tab (Ctrl+4) lists chapters, endings, routes, codex entries, meters,
minigames, and flowchart boxes; Enter opens one.

Click a box, or select it and press Enter, to open its label in a side editor sharing the
Editor tab's text; F6 reaches it and Esc closes it. Ctrl+Enter or Ctrl+click uses the Editor
tab. Ctrl+= and Ctrl+- zoom.

If a change stops the script loading, the map keeps its last drawing, marked "out of date".
**Go to label** (Ctrl+G) jumps to a label by name.

## Preview a scene

Click inside a scene. "Preview starts at:" names the label above the cursor. Press F5 or
**Preview**. Studio saves your files and opens the game at that label. Shift+F5 starts at
`label start` instead.

A scene that is only reached by `call` ends the preview at its `return`.

## Start values

In *Paper Lanterns*, the example game, `label bridge` checks `bought_lantern`. Hana's
name is "???" until `label start` sets it. Type start values in the **Start values** box,
one per line, written like a `default`:

```
bought_lantern = True
hana_name = "Hana"
```

The story's defaults are set first. Then your values replace them. A default that uses
another default, like `default bonus = trust + 1`, uses the original `trust`.

Previews are normal dev runs. They use the saves and persistent data in your game folder.

## When a preview can't start

Two errors come from the start options, so they have no line:

- **E26b, no such label:** no label has the start name. The message suggests a close
  name, or names the file that no `include` adds.
- **E26c, no such default:** a start value's name has no `default` (a `define` can't have
  a start value). Fix the spelling, or add a `default`.

## Without Studio

This line runs the same preview in cmd, PowerShell, or bash:

```
python -m engine run game --start bridge --set "bought_lantern=True" --set "hana_name='Hana'"
```

`--start` picks the label; each `--set` gives one start value. Put text in single quotes
inside the double quotes.

## Keys

- Ctrl+S: save. Ctrl+Shift+S: save all.
- Ctrl+N: new script file. Ctrl+Shift+O: Add files…
- F2, Delete: rename or delete the file selected in the **Project** panel.
- Ctrl+Space: completion. Ctrl+G: Go to label.
- Ctrl+1, Ctrl+2, Ctrl+3, Ctrl+4: Editor, Story map, Asset, Outline.
- Ctrl+=, Ctrl+-, Ctrl+0: zoom the text, or the map.
- F5: preview from the cursor. Shift+F5: from the start. F7: Check now.
- F6, Shift+F6: next or previous area.

## Good to know

- The editor shows right-to-left text in typing order. Check how it looks in the preview.
- On macOS, F5 and F6 may need Fn (so may F7), and Ctrl is Cmd.
- Tk (Studio's toolkit) has limited screen-reader support.

## For engine builders

A statement appears in Insert, Help, and completion when its feature calls
`register_doc(StatementDoc(…))` beside its `register(StatementSpec(…))`.
`tests/script/test_statement_docs.py` fails for a word without one.
