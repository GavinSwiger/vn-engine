# The Database

The **Database** tab in Studio (Ctrl+3) is where you make the game's characters, pictures,
sounds and variables without typing script lines. Pick a category on the left, then an
entry in the list; its form is on the right. A field is applied when you press Enter or
leave it, and Ctrl+Z in the script file takes it back. **+ New** adds an entry: new
characters and variables go into `script/database.vns`, which Studio makes (and includes
from `main.vns`) the first time.

- **Characters**: the name shown, its colour, the text colour and italics, the character's
  **Looks** (the pictures in `images/<name>/`; **+ Add looks…** copies more in), and the
  **Voice blip** (a sound with ▶, how often it plays, its pitch and volume).
- **Pictures**: backgrounds, each character's looks, and colour backgrounds
  (`image bg night = "#102040"`), as thumbnails.
- **Sounds**: by folder (music, sound effects, voices, blips); ▶ plays one, ■ stops it.
- **Variables**: a name, a kind (Number, Text, Yes-No) and a starting value (`default`).

Each entry says where it is used ("Used in 3 lines"); **Show uses** lists those lines in
Problems, where a click opens one. Something that is used can't be deleted until those
lines change. A script name can change only while nothing uses it.

A declaration written in a way the form can't read, such as `Character(name)` with a
variable, is listed but shown read-only, with **Edit as script**.

Back to [Studio](scene-editor.md).
