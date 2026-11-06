# The Database

The **Database** tab in Studio (Ctrl+3) is where you make the game's characters, pictures,
sounds, variables, meters, codex entries, routes, transitions and stage positions without
typing script lines. Pick a category on the left, then an entry in the list; its form is on
the right. A field is applied when you press Enter or leave it, and Ctrl+Z in the script
file takes it back. Studio saves each file a change touches right away; a file with your own
unsaved typing in it stays unsaved until Ctrl+S or Play, so half-written text is never saved
for you. **+ New** adds an entry: new declarations go into
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
  (`default persistent.name`): every line that uses it changes to `persistent.name` too
  (Studio says how many and asks first), and unticking changes them back. A line that only
  a story variable fits (`{var=name}`, `minigame … into name`) stops the change until you
  edit it.
- **Meters**: a name, an optional lowest and highest, the start and its ranks (`points`).
  **+ New** offers ready-made meters first: your kit's (Horror's Sanity, 0 to 100, starting
  full, with four ranks), or Affection, Trust, Courage and Coins without a kit (Game
  settings ▸ Kit tailors the list). **Blank meter…** goes from 0 to 100. Under **On
  screen**, pick the meter's **Look** (bar, number, hearts, pips, dial), its **Corner**
  (click one of the four) and the **Label** beside it; the small picture next to them shows
  the meter in your colors at a sample value, with its rank. A field you leave alone uses
  the kit's default, and the line under them says which ("Kit default: hearts, top
  right"); **Use default** clears one. These go in `[meter.<name>]` in config.toml, one undo
  step each. The story shows the meter with `show meter <name>` (Insert ▸ Show meter).
- **Codex**: tips (kept in every playthrough) and items (this playthrough only), each with a
  title, a category, a picture and its text, one paragraph per line (`lock tip`/`lock item`).
  The Kind field switches an entry between tip and item. An item also has Count, Most held
  and Money, and **Price**: what a shop asks for one when its stock names no price (empty:
  none; written as `price 5`).
- **Contacts**: the people who write to the player, each with the messages they send and
  a preview of the newest one. See [Contacts](#contacts).
- **Minigame data**: the data the bundled minigames take, such as word lists, gift tables
  and **shops** (each row: an item, its price, how many are for sale; an empty price uses
  the item's own). See [minigames.md](minigames.md), "Setting up a minigame in Studio".
- **Endings & routes**: routes, with their title and the endings the player must reach to
  open them (`lock route … until …`); **+ New** asks which scene the route starts at. The
  endings are listed from your story's Ending lines, read-only, with **Go to**.
- **Chapters**: the story's Chapter lines in story order, with **Go to** and **▶ Play its
  scene**.
- **Transitions**: your own Dissolve, Fade or Mask with its length, colour, mask picture,
  soft edge and direction (`define … = Dissolve(…)`). **Try it** comes in a later update;
  until then, use the transition in a scene and choose Run ▸ Play this scene.
- **Positions**: the stage, drawn small, with a marker where each position stands. Drag a
  marker (or use the arrow keys, or type x and y) and `[stage.positions]` in `config.toml`
  changes. A drop near the bottom edge lands on it. **Use default** puts a moved left,
  center or right back; your own positions can be deleted while unused.
- **Achievements**: the rewards players keep across playthroughs, in the order the
  Achievements page shows them. See [Achievements](#achievements).
- **Clean up** (last): scenes nothing leads to and things the story never uses, found
  by each check. See [Clean up](#clean-up).

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

In Events, Insert… ▸ **Unlock a gallery picture** adds a picture to the player's gallery
without showing it (`unlock gallery cg festival`), and **Forget a gallery picture** makes the
game forget one. Game
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
- Players unlock a replay the first time they reach its scene. An **Unlock a scene
  replay** or **Forget a scene replay** event (Events ▸ Insert…) opens or locks one from the
  story; while
  one names a replay, its scene can't change and **Delete** is refused, with **Show uses**.
- **◀ Move earlier** and **Move later ▶** (or Alt+Up / Alt+Down in the list) change the
  order. Both replays must be in the same script file.
- **▶ Play replay** plays the scene as players see it from Extras;
  **▶ Preview Extras** opens Extras ▸ Scenes with every scene open. Nothing is saved.

In Endings & routes, each ending has **▶ Play replay** too (it plays the ending's scene)
while Game settings ▸ **Extras** ▸ "Let players replay endings they've reached" is on. The
same page has "Show an Endings page in Extras" and the Endings and Scenes words. A replay's
scene name keeps players' records, so Studio doesn't rename it.

## Achievements

Achievements reward players for what they do, with a notice ("Achievement unlocked: First
Steps") and a list under the title screen's Extras ▸ Achievements, kept across
playthroughs. Studio writes one line per achievement into `database.vns`, in the page's
order:

```
lock achievement first_steps "First Steps" "Finish the prologue." image achievements first_steps
lock achievement garden "Secret Garden" "Find the hidden garden." hidden
lock achievement completionist "Completionist" "See every ending." when "lantern" in persistent.endings and "next_year" in persistent.endings
```

- **+ New achievement** asks for the **Name shown**; the script name is made from it
  (`First Steps` → `first_steps`) and the achievement goes at the end.
- Click one to see its form: the **Name shown**, a **Description**, an **Icon** (a picture;
  a square one, 64 × 64 or larger, looks best) and **Hidden** (players see "Hidden
  achievement" until they unlock it).
- **Unlocked**: **By an Unlock achievement line in the story** (add Events ▸ Insert… ▸
  **Unlock achievement** where the player earns it; the form says so while no line gives it), or
  **Automatically, when:** — the same checks as an If (an ending was seen, a variable, a
  meter, a codex tip or item, a route, the playthrough), All of or Any of them. The game
  checks them at every line and choice, and when the story ends. A condition the checks
  can't show stays as you typed it ("Written as script"). Picking By a line again removes
  the condition. A story has up to 200 achievements, 64 of them automatic.
- **▲ Move up** and **▼ Move down** (or Alt+Up / Alt+Down in the list) change the order.
  Both must be in the same script file.
- **▶ Preview achievements** opens Extras ▸ Achievements with every
  achievement unlocked. Nothing is saved.
- **Delete** is refused while an Unlock achievement line names it, with **Show uses**.
  Players' unlocked achievements are kept under the script name, so Studio doesn't rename
  it.

Game settings ▸ **Extras** ▸ Achievement words (and Button words ▸ Achievements) change the
page's heading, the notice's start, the "Unlocked" count and a hidden achievement's words.
Sending achievements to a store such as Steam needs a platform hook written in Python: see
[minigames.md](minigames.md), "Achievement hook". Achievements always work without one.

## Contacts

Contacts are the people who write to the player: a pen pal's letters, a friend's texts, a
voice on the radio. Their messages arrive in the Inbox while the story goes on. Studio
writes one line per contact into `database.vns`, and one `define` per message:

```
lock contact hana "Hana" on pigeon image hana portrait
define hana_letter_1 = [
    "Meet me at the bridge when the lanterns are lit.",
    {"me": "I'll be there."},
    ]
```

A pen pal in a minute:

1. **+ New** asks the **Name** players see; the script name is made from it (`Hana` →
   `hana`).
2. Pick the **Device look**: how the messages come. The first choice is the game's own
   device, the one the game uses for a contact with no look of its own, named as the game
   shows it and with where it comes from ("Game default (Pigeon post, from the Fantasy
   kit)"; without a kit, "Game default (Phone, with no kit)"); the others are
   Phone, Letters, Pigeon post, Radio, Terminal and Mind. The line under it shows the
   arrival notice ("A pigeon lands on the sill with a note from Hana.").
3. Pick a **Picture** (shown with the notice and in the Inbox).
4. Under **Messages**, click **+ New message**, name it, and write its lines in the
   phone-chat step editor: lines from the contact, the player's own (Me) and time
   dividers. Close it, and the message is saved.
5. In a scene, add Events ▸ Insert… ▸ Messages ▸ **Send** (or paste the line the message
   offers with **Copy**: `send hana_letter_1 from hana`).

Each message lists where it is sent from (scene and line; click one to go there) and has
**Write lines…** to change it. The messages listed are the ones the contact's Send lines
name, then any lists of lines not sent yet whose name starts with the contact's
(`hana_…`). The picture
beside the fields shows the newest message in its device look and your colours, drawn as
Game settings ▸ Devices draws that device: the arrival notice over a pigeon's note, a
signed letter, a green terminal, chat bubbles. A Send line's own look (`send … on phone`)
wins for that message.

Renaming a contact (its script name) changes its Send lines too, after asking; messages in
older saves stay in the thread with the same name shown. Renaming a message changes its
Send lines and the replies that wait for it (`inbox.reply("hana_letter_1")`) too. **Delete** is refused while a Send
line uses the contact, and says which scenes and lines; its messages stay when it goes.

## Clean up

**Clean up** is the last category. Each time the game is checked (as you type, on Play, or
with Check now), it lists what the story doesn't use, so you can tidy up before you build:

- **Scenes not reached**: no jump, call or choice leads there from `start` (a scene replay
  counts as a way in).
- **Characters**, **Pictures**, **Sounds** and **Variables** that no line uses.
- **Other**: transitions, positions, meters and other `define` lines nothing uses.

The count next to Clean up is how many there are. Each row shows the name and where it is
(file and line). Click one to see its kind, where it is, the picture or a ▶ to hear the
sound, why it is listed, and two buttons:

- **Open in Pictures** (or Characters, Sounds, …) shows it in its own category. A scene has
  **Show on map**, which selects its box on the Story map; a plain `define` has **Open in
  Editor**.
- **Delete…** is that category's own Delete, with its own question first: a file is
  deleted from the game folder ("This can't be undone"), a line is removed (Edit ▸ Undo
  brings it back), and a scene is deleted from the Story map as **Delete scene** does.
  A deleted row leaves the list.

Type in the search box to find a row by name. Before the first check the list says
**Not checked yet** with **Check now**. If the story has errors, Clean up asks you to fix them in
Problems first, because it needs a story that loads. Characters are listed only after your
first Play or Check now; until then a line above the list says so. With nothing unused,
it says **Nothing to clean up**. The same list, as warnings W237–W242, is what
`python -m engine lint` prints: see [script-language.md](script-language.md#unused-and-unreached-tidy-up-warnings).
