# The Database

The **Database** tab in Studio (Ctrl+3) is where you make the game's characters, pictures,
sounds, variables, meters, codex entries, routes, transitions and stage positions without
typing script lines. Pick a category on the left, then an entry in the list; its form is on
the right. A field is applied when you press Enter or leave it, and Ctrl+Z in the script
file takes it back. **+ New** adds an entry: new declarations go into
`script/database.vns`, which Studio makes (and includes from `main.vns`) the first time;
positions go into `config.toml`.

- **Characters**: the name shown, its colour, the text colour and italics, the character's
  **Looks** (the pictures in `images/<name>/`; **+ Add looks…** copies more in; a click on
  one sets up its [blinking and talking](#blinking-and-talking)), and the
  **Voice blip** (a sound with ▶, how often it plays, its pitch and volume).
- **Pictures**: backgrounds, each character's looks, and colour backgrounds
  (`image bg night = "#102040"`), as thumbnails. Turn on **In the gallery** to put a
  picture in the [gallery](#gallery) (`lock gallery cg festival "Festival"`); its
  **Gallery title** is made from the picture's name and you can change it.
- **Gallery**: the gallery pictures, in the order players see them. See [Gallery](#gallery).
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

## Blinking and talking

A character can blink and move her mouth while her lines type, with no script lines. In
**Characters**, click one of her looks: the **Blinking and talking** panel under the Looks
shows that look at 192 px with two rows of small pictures.

- **Blink frames**: copies of the look with the eyes closed (or half closed, then closed).
  The character blinks every few seconds.
- **Talking frames**: copies of the look with the mouth open. The mouth moves while her
  lines type and closes when the text stops.

**+ Add blink frame…** and **+ Add talking frame…** copy one picture in and name it for
you: `happy_blink1.png`, `happy_blink2.png`, … next to `happy.png` (`happy_talk1.png` for
talking). Click a small picture and **Remove frame** (or Delete) removes the file; the other
frames keep their names. A look holds up to 9 of each. **▶ Blink** plays one blink and
**▶ Talk** two seconds of talking in the panel; **■ Stop** stops it.

A frame must be the same size as its look, with only the eyes or mouth changed. The panel
says when a frame is another size, because the game won't use it. Files you copy in
yourself with these names are found too. Frames are not looks: the Looks gallery and the
Events forms don't offer them, and a look that has frames is labelled `happy (moves)`.

How fast it moves is in **Game settings ▸ Effects & comfort ▸ Sprite animation**: blinking
and talking on or off, about how often a blink comes, and the seconds per blink and talking
frame. ▶ Blink and ▶ Talk use these. With **Reduce motion** on, sprites hold still.

Each entry says where it is used ("Used in 3 lines"); **Show uses** lists those lines in
Problems, where a click opens one. Something that is used can't be deleted until those
lines change. A script name can change only while nothing uses it.

A declaration written in a way the form can't read, such as `Character(name)` with a
variable, is listed but shown read-only, with **Edit as script**.

Back to [Studio](scene-editor.md).

## Gallery

The gallery is the Extras page where players look again at the special pictures they've
seen. A gallery picture unlocks by itself the first time it shows in the story (a Scene,
Show or a line that changes a look), so there is nothing else to set up.

- **+ Add pictures…** opens your pictures as thumbnails; click the ones you want (a tick
  shows), then **Add**. They go at the end of the gallery, each with a title made from its
  name. Only pictures not in the gallery yet are offered.
- Click a picture to see its form: the **Picture**, the **Title** under its square, and
  **More versions**: up to 8 more pictures in the same square (a close-up, a smile).
  Players step through a square's versions in the viewer. **+ Add a version…** picks one;
  **Remove** takes one out.
- **◀ Move earlier** and **Move later ▶** change the order. Both pictures must be in the
  same script file; when they aren't, the buttons say so and you move their lines in the
  Editor.
- A picture no line shows (and no Unlock gallery picture event names) is marked: players
  can't get it yet. "Shown in N lines" lists where it shows.
- **Remove from gallery** takes it out (Ctrl+Z in `database.vns` brings it back). It is
  refused while a Lock or Unlock gallery picture event names it.
- **▶ Preview the gallery** plays the game straight into Extras ▸ Gallery with every
  picture unlocked. Nothing is saved.

In Events, **Unlock** with **What: gallery** adds a picture to the player's gallery without
showing it (`unlock gallery cg festival`), and **Lock** makes the game forget one. Game
settings ▸ **Extras** has "Show locked pictures as ???" and the gallery's look.

## Music room

The music room is the Extras page where players listen again to the songs of your game.
Each song is a **track**: a music file from Sounds ▸ Music with a title. Studio writes one
line per track into `database.vns`, in the room's order:

```
lock track main_theme "Main Theme" file "music/main_theme.ogg" open
lock track festival_night "Festival Night" file "music/festival_night.ogg"
lock track paper_lanterns "Paper Lanterns" file "music/paper_lanterns.ogg" until lantern
```

- **+ Add track…** lists your music files that aren't in the room yet; pick one (Ctrl+click
  for several), press **▶ Play** to listen first, then **Add**. Each goes at the end, its
  title made from the file's name (`festival_night.ogg` → "Festival Night").
- Click a track to see its form: the **Title** players see, the **File** (with ▶ Play), and
  **When players get it**:
  - **When the story first plays it** (the usual): the track opens the first time a Play
    music line plays its file, and stays open in every later playthrough.
  - **From the start**: always open.
  - **After these endings**: tick endings; the track opens once players have reached all
    of them.
- A track whose file no Play music line plays is marked, since players would never get it.
  "Played by N lines" lists where it plays.
- **▲ Move up** and **▼ Move down** (or Alt+Up / Alt+Down in the list) change the order.
  Both tracks must be in the same script file; when they aren't, the list says so and you
  move their lines in the Editor.
- **Delete** asks first; the music file stays (Ctrl+Z in `database.vns` brings the track
  back). Nothing else in the story names a track, so Delete is never refused.
- **▶ Preview the music room** plays the game straight into Extras ▸ Music Room with every
  track open. Nothing is saved.

In Sounds, a music file's form has **In the music room**: switch it on to add the file as a
track (off removes it), change its **Music room title**, or **Open in Music room**. The
room's words (Play, Pause, Next…) are on Game settings ▸ **Extras** and **Button words**.
A track's script name keeps players' records, so Studio doesn't rename it; to rename one,
edit its line (players who had it lose it).

## Scene replays

Scene replays let players watch a scene again from Extras ▸ Scenes once they've reached it.
A replay never changes their saves or progress. Studio writes one line per replay into
`database.vns`, in the Scenes page's order, with any starting values indented under it:

```
lock replay festival "The Festival"
lock replay bridge "On the Footbridge" image cg lanterns to fireworks:
    sent_lantern = True
    player = "Hana"
```

- **+ New replay…** lists the scenes that don't have a replay yet; pick one and it goes at
  the end, its title taken from the scene's Flowchart title, else its name
  (`river_walk` → "River Walk").
- Click a replay to see its form: the **Scene** it plays (with **Go to**), the **Title**
  players see, the **Picture** on its tile (the first choice, "scene's first
  background", uses the first background the scene shows) and where it **Ends**: **When
  the scene ends**, or **At scene** — the replay stops when the story reaches that scene.
- **Starting values**: in a replay, variables start at their starting values. Set any the
  scene needs, such as the player's name: **+ Add a starting value**, pick the variable,
  then its value (Yes or No, a number or a text, as the variable's kind). **Remove** takes
  one away. Up to 32.
- Players unlock a replay the first time they reach its scene. An **Unlock** or **Forget**
  event (Events ▸ Lock / Unlock ▸ Scene replay) opens or locks one from the story; while
  one names a replay, its scene can't change and **Delete** is refused, with **Show uses**.
- **◀ Move earlier** and **Move later ▶** (or Alt+Up / Alt+Down in the list) change the
  order. Both replays must be in the same script file.
- **▶ Play replay** plays the scene as players see it from Extras, through the Play bar;
  **▶ Preview Extras** opens Extras ▸ Scenes with every scene open. Nothing is saved.

In Endings & routes, each ending has **▶ Play replay** too (it plays the ending's scene)
while Game settings ▸ **Extras** ▸ "Let players replay endings they've reached" is on. The
same page has "Show an Endings page in Extras" and the Endings and Scenes words. A replay's
scene name keeps players' records, so Studio doesn't rename it.
