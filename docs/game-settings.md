# Game settings

The **Game settings** tab in Studio (Ctrl+4) changes how your game looks and behaves without
editing `config.toml` by hand. Pick a page on the left; its fields are on the right.

- **Game**: the game's title and version, and the window's size, fullscreen and icon.
- **Color scheme**: built-in colors for every box, menu and button, picked with one click
  (see below).
- **Title screen**: whether it shows, its buttons, background, logo, music and colours.
- **Text box**: text speed, fonts, colours, size and padding, the name tab and the
  click-to-continue mark.
- **Choices**: whether locked choices show, and how choices look.
- **Saves & going back**: save pages, auto-saves, chapter save names, the Save and Load
  pages' look, and how far players can go back.
- **Sound volumes**: starting volumes, fades, playing in the background, music loop points.
- **Effects & comfort**: reduce motion and flashing, default effect lengths and sizes,
  effect colours, auto-advance and skipping.
- **Chapters & codex**: the chapter title card, and the Codex page and its notices.
- **Flowchart**: the players' Flowchart page: whether it shows, which choices get a box,
  jumping, and every box's look.
- **Content warning**: when it shows, its text and how long players wait.
- **Fourth wall**: showing the player's computer user name, and the fake crash screen.
- **Button words**: every word the game shows, grouped by where it appears, to rename or
  translate them.
- **All settings**: every setting the engine has, by section. Type in the search box to
  find one.

Styles and playthrough looks are still edited in the Editor.

A field is applied when you press Enter or leave it (a long text: when you leave it, or
Ctrl+Enter). The change goes into `config.toml` in the Editor, unsaved, so Ctrl+S saves it
and Ctrl+Z in `config.toml` takes it back. Changes you type in the Editor show here too.

Each field says what it does, the values it takes, and its default. A blue bar at its left
means you changed it; **Use default** removes your line so the engine's default applies.
Beside each group's heading, "In config.toml: [textbox]" says where its settings are written,
in case you also open the file.

On **Text box** and **Title screen**, the preview shows a still of the game's real drawing
with your unsaved changes, half a second after you stop typing. If it can't be drawn, it
says why, for example a value the game refuses.

## Color scheme

The **Color scheme** page shows the six built-in schemes as cards: Sakura (the engine's
own colors), Pocket LCD, Amber Terminal, Synthwave Sunset, Vaporwave Dream and Groovy
'70s. Each card shows four of its colors (fill, border, accent and text), and the scheme
your game uses says "In use"; with no scheme set, that is Sakura. A scheme changes colors
only: fonts, pictures and sounds stay as they are.

- **Click a card** (or move to it with the arrow keys) to see it. Half a second later the
  preview shows the text box in that scheme, with your other unsaved changes. Nothing is
  written yet; leaving the page without applying changes nothing.
- **Apply** (it names the card, such as **Apply Pocket LCD**; or Enter, or a
  double-click) writes one line, `preset = "pocket"`
  under `[theme]`, as one step that Ctrl+Z in `config.toml` takes back.
- **Custom colors kept.** Colors you set yourself under `[theme]` still show over the
  scheme. When you have some, a note says how many, and **Clear my colors** removes them
  (after asking) so the scheme shows everywhere. Ctrl+Z brings them back.
- If `config.toml` names a scheme this version doesn't have, the page says so and no card
  is in use; the default colors show until you apply one.

A style can have its own scheme while the story has it on: on **Styles & playthrough
looks**, each style's first field is **Color scheme** ("not set" keeps the main look's
scheme). All settings lists the same key as `[theme] preset`.

If `config.toml` has a mistake, the tab shows only the line to fix and **Open in Editor**.
A setting written in a way the form can't change, such as `textbox = { … }` on one line,
says so and offers **Edit as script**. Lists of your own entries, such as stage positions,
are edited in the Editor (**Open in Editor**).

Back to [Studio](scene-editor.md).
