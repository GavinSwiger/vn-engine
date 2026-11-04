# Story map editing

Studio's **Story map** tab (Ctrl+2) is more than a picture: you can build your story on it.
Every change is written into your `.vns` files as ordinary script lines, so the script stays
the one true copy. Nothing on the map is stored anywhere else except where the boxes sit.
The basics of the map (box marks, arrow styles, the Outline) are in
[the scene editor page](scene-editor.md).

## Boxes

- **Scroll the map:** the arrow keys or W A S D (Shift: further), the mouse wheel, or the
  scroll bars. Ctrl+arrows go from box to box.
- **Move a box:** drag it. It snaps to a 20 px grid; hold Shift for no snap. With a box
  chosen, Alt+arrows move it (Shift+Alt: five steps). **Move box** in the **Story** menu moves
  it with the arrow keys; Enter keeps the place and Esc puts it back.
- **Tidy up** lays every box out again in columns.
- **New scene:** double-click empty space, press Ctrl+Shift+N, or use **+ New scene**. Type a
  name (its script name shows as you type) and pick the file. **New file…** in that dialog
  makes a new script file first. Studio adds `label <name>:` and a placeholder line.
- **Rename scene:** F2, or double-click the box's name. Studio changes the `label` line and
  every `jump`, `call` and `flowchart forget` line that names the scene, in every script file,
  opening closed files as unsaved. Python code that names the scene (a `$` line, a condition,
  a `define` or `default` value) is never changed: the question counts those places so you
  can fix them yourself. Saves made inside this scene will start it from the beginning. The
  `start` scene keeps its name.
- **Delete scene:** press Delete on the box. The question says how many arrows lead there;
  those lines show an error until you change them. `start` can't be deleted.
- **Play from this scene:** right-click the box, or a row in **Events**.

## Arrows and choices

- **Connect two scenes:** drag from the handle on a box's right edge onto another box, or
  press Ctrl+J (**Go to scene…**) and pick one. Studio writes a `jump`.
- If the scene already goes somewhere, Studio asks: **Make a choice** turns the two arrows
  into a `menu` with one option each, and opens the new option's text.
- **Choice text:** select a choice arrow and press F2 (or double-click its label). Enter
  saves, Esc cancels.
- **Change target…:** right-click an arrow and pick another scene, or select the arrow and
  drag its head onto another box.
- Tab on a box walks its arrows; Delete removes the selected arrow's line.

## The Events tab

Click a box to open the scene beside the map. The side pane has two tabs, **Events** and
**Script** (the text itself); Ctrl+E switches between them. Events lists what happens in the
scene, one row per line: *Say*, *Show character*, *Background*, *Choice* and so on. A line
Studio has no form for shows as a **Script** row with its text; `$ pass` shows as `(nothing)`.

- **Insert…** (or the Insert key) adds a command after the chosen row.
- Enter or a double-click opens the row's form.
- Alt+Up and Alt+Down move a row; Delete removes it (asking first when lines are inside it).
- Ctrl+Z in the Events tab undoes the scene file's last change.

**The Choice form** holds a menu: the **Question** (speaker, look, text) and up to six
**Options**, each with its text, **Only show when** (a condition, or Always) and **Goes to**
(a scene, or "continues here"). **Add**, **Remove**, **Up** and **Down** act on the chosen
option. Under **Time limit**, tick **Give the player [5] seconds** (1 to 60, in steps of
0.5) to add a countdown, and pick under **When time runs out, pick** the option chosen for
the player when it runs out; ticking the box first picks the last option with no condition.
That option is always shown, so it can't have an "Only show when" condition. Players who
turned on Timing assist get twice as long, or no limit. The **Lines** preview shows
`menu time 5:` and `"..." timeout:`, and OK waits while a problem line shows. In Events, the
Choice row ends with ` · 5 seconds`, and the timed option's row says `when time runs out`.

## Undo on the map

Ctrl+Z on the map undoes the last map action, in every file it touched, and puts the boxes
back. If you changed one of those files in the text since, the undo is blocked and Studio
says which file: "Undo blocked". Undo that file in the text instead (Ctrl+Z there).

## Where the box places live

Box places are saved in `.studio/storymap.json` inside your game folder, a moment after you
move a box. The game never reads it. A missing or broken
file only means the boxes are placed automatically. Whether you keep it in version control is
your choice.

## Good to know

- Studio changes only the lines an action needs; your comments and spacing stay.
- If a scene's text has a mistake, its map actions wait until you fix it.
- Tk (Studio's toolkit) has limited screen-reader support; the text itself (Ctrl+1) and
  **Go to label** (Ctrl+G) are the keyboard path through the story.
