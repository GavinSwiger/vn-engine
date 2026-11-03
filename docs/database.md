# The Database

The **Database** tab in Studio (Ctrl+3) is where you make the game's characters, pictures,
sounds, variables, meters, codex entries, routes, transitions and stage positions without
typing script lines. Pick a category on the left, then an entry in the list; its form is on
the right. A field is applied when you press Enter or leave it, and Ctrl+Z in the script
file takes it back. **+ New** adds an entry: new declarations go into
`script/database.vns`, which Studio makes (and includes from `main.vns`) the first time;
positions go into `config.toml`.

- **Characters**: the name shown, its colour, the text colour and italics, the character's
  **Looks** (the pictures in `images/<name>/`; **+ Add looks…** copies more in), and the
  **Voice blip** (a sound with ▶, how often it plays, its pitch and volume).
- **Pictures**: backgrounds, each character's looks, and colour backgrounds
  (`image bg night = "#102040"`), as thumbnails.
- **Sounds**: by folder (music, sound effects, voices, blips); ▶ plays one, ■ stops it.
- **Variables**: a name, a kind (Number, Text, Yes-No) and a starting value (`default`).
  Tick **Remembered across playthroughs** to keep it after the game ends
  (`default persistent.name`).
- **Meters**: a name, an optional lowest and highest, and the start (`points`). A new meter
  goes from 0 to 100.
- **Codex**: tips (kept in every playthrough) and items (this playthrough only), each with a
  title, a category, a picture and its text, one paragraph per line (`lock tip`/`lock item`).
  The Kind field switches an entry between tip and item.
- **Endings & routes**: routes, with their title and the endings the player must reach to
  open them (`lock route … until …`); **+ New** asks which scene the route starts at. The
  endings are listed from your story's Ending lines, read-only, with **Go to**.
- **Chapters**: the story's Chapter lines in story order, with **Go to** and **▶ Play its
  scene**.
- **Transitions**: your own Dissolve, Fade or Mask with its length, colour, mask picture,
  soft edge and direction (`define … = Dissolve(…)`). **Try it** comes in a later update;
  until then, use the transition in a scene and press ▶ Play this scene.
- **Positions**: the stage, drawn small, with a marker where each position stands. Drag a
  marker (or use the arrow keys, or type x and y) and `[stage.positions]` in `config.toml`
  changes. A drop near the bottom edge lands on it. **Use default** puts a moved left,
  center or right back; your own positions can be deleted while unused.

Each entry says where it is used ("Used in 3 lines"); **Show uses** lists those lines in
Problems, where a click opens one. Something that is used can't be deleted until those
lines change. A script name can change only while nothing uses it.

A declaration written in a way the form can't read, such as `Character(name)` with a
variable, is listed but shown read-only, with **Edit as script**.

Back to [Studio](scene-editor.md).
