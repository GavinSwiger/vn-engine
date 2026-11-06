# Minigames

A minigame is a small game that runs inside the story: the story stops at a `minigame` line,
the player plays, and the story goes on with the result. Some minigames come with the engine;
you can also write your own in Python.

This guide has three parts:

1. **Using a minigame** (next section): the `minigame` line, what the player sees, and how
   to test a story that has one. Then one section for each minigame that comes with the
   engine: the poem game, the cross-examination, the phone chat, and the puzzle room.
2. **Writing a minigame**: your own minigame, step by step, using the example game's
   lantern memory game as the worked example. You need to know a little Python: what a
   class, a method, and a list are.
3. **Plugin reference**: everything a plugin can declare and call, and the error messages.

## Using a minigame

A minigame is played from one line of the script. This is the lantern stall in the example
game (`game/script/chapter1.vns`):

```
default turns = 0

label lantern_stall:
    "\"Unless you can find the pairs,\" she added, and turned a row of paper lanterns face down."
    minigame lantern_memory pairs=6 into turns
    if turns <= 10:
        "\"Only {var=turns} turns? Sharp eyes,\" the stall keeper said."
```

When the story reaches the `minigame` line, the scene fades into the game. The player plays
until the game ends, the game fades back to the story, and the story goes on with the next
line.

- **The name** comes first: `lantern_memory`. It is the name the minigame's plugin gives
  itself. Nine names come with the engine: `poem_game`, `present_evidence`, `phone_chat`,
  `puzzle_room`, `heartbeat`, `code_lock`, `stay_still`, `hand_game`, and `gift_giving`;
  `ask_text`, `cipher_note`, `terminal` and `shop` come with it too. Any others are plugins
  in your game's `game/minigames/` folder.
- **Arguments** come next, written `name=value`: `pairs=6`. Each minigame has its own; its
  section below (or its plugin) lists them. A value is worked out when the line runs, like
  a condition, so `hints=points.hana >= 3` works. Misspelled or missing arguments are
  caught when the game starts, with the line number.
- **`into turns`** keeps the minigame's result in a story variable, which needs a
  `default`. Each minigame says what its result is: a number of turns, a word, a
  dictionary. Without `into`, the result is dropped.
- **`skippable`**, right after the name, adds **Skip Game** to the game menu while this
  minigame runs, for players who would rather read on. Only minigames that say what happens
  when skipped allow it.

A minigame can also change meters (`points`) and the codex: clearing the lantern board
adds 1 to Hana's meter. Those changes happen together with the result, just before the next
line, so a save or a rollback never sees half of them.

**What the player can do.** The minigame is played with the mouse, the keyboard (arrow
keys, Enter, Backspace for Back), or a gamepad. Esc opens the game menu as usual, and the
game waits while the menu is open. Saving during a minigame saves its start: loading starts
the game again from the beginning, with the same random layout. Rolling back to a minigame
lets the player play it again, like a choice. Once the player has done something in a
minigame, the mouse wheel can't step back out of it.

**Testing.** A headless run (an automated test that plays the story with no window) uses
each minigame's test outcome: a result the plugin declares for tests. You can give your own in the inputs instead: `finish 9`, or
`finish 9; points hana += 1` to make the meter change too. In a dev run, **Shift+F8** ends
the running minigame with its test outcome, so you can test the story around it quickly.

The script language reference has the full form of the line and its error messages:
[script-language.md](script-language.md), "minigame".

## Setting up a minigame in Studio

You don't have to type the data or the line. In Studio, open **Database ▸ Minigame data**.
The list shows the story's word lists, evidence, phone chats, puzzle rooms, gift tables and shops. **+ New**
makes one in `script/database.vns`, ready to change. Each change is saved into the script
straight away, and **Edit ▸ Undo** takes it back. If the game wouldn't accept a change yet,
for example a room with no way out, the panel shows "Not saved yet" and the reason, and
saves once you fix it.

- **Poem words**: one row per word and one column per meter, each with a 0 to 3 spinner.
  **+ Add word** adds a row, and ✕ removes it.
- **Evidence**: the witness's statements in order. For each statement, type what the
  witness says and tick the items that contradict it. The items come from **Codex ▸ Items**.
  Studio writes the testimony and its answer for you.
- **Phone chat**: the steps in order. **+ Add ▾** adds a message from the contact, from
  you, or from someone else, a time, or a reply point. A reply point holds up to four
  buttons, and each button can have its own follow-up steps. Tick "Don't reply" to add
  that button too.
- **Puzzle room**: pick the background, then drag on the picture to draw a hotspot. Drag
  a hotspot to move it, or drag a corner to resize it. The arrow keys move the selected
  hotspot, and Shift with the arrow keys resizes it. The panel beside the picture sets the
  hotspot's name tag and what a click does: show its text, give an item, need an item
  (the items that work, plus the text for a wrong one), or leave the room. It also sets
  which hotspot it appears after, and its picture. The recipes below the picture combine
  two items into a third.
- **Gift table**: pick a character at the top (**+ Add character** takes a meter's name).
  One row per gift: the item, the reaction (Loved, Liked, Neutral or Disliked), the points
  (-10 to 10) and what the character says. The "Any other gift" row is for every item not
  listed. **+ Add gift** adds a row, and ✕ removes it. The items come from **Codex ▸ Items**.
- **Shop**: one row per item for sale: the item, its price, and how many are for sale. An
  empty Price uses the item's own **Price** (Codex ▸ Items); an empty How many means any
  number. **+ Add item** adds a row, ▲ and ▼ move it, and ✕ removes it.

Then, in a scene's **Events**, use **Insert ▸ Minigame**. Pick the game. The form shows
that game's arguments. A data argument lists that game's data, with **Set up…** to edit
the data and **New…** to make more. **Result goes to** picks the variable that gets the
result. Your own minigames (`minigames/*.py`) are listed too, with the arguments they
declare. A data set written in a way the panel can't show, such as one built with Python,
offers **Edit as script**. If a data set has comments, Studio asks before saving it, because
saving rewrites it without them.

## Poem game

The poem game (`poem_game`) comes with the engine. It shows a notebook page with two columns
of words. The player picks one word, the page changes to new words, and so on until the poem
has `rounds` words. Each word you write in the list scores toward the story's meters
(`points`), so the player's choice of words says which character the poem is for. When the
poem is done, the scores are added to the meters, and the story can branch on who liked it
best.

### The word list

Write the words as a `define` dictionary. Each key is a word as the player sees it. Its value
says which meters it raises:

- `{"sayori": 3, "natsuki": 1}`: 3 points for `sayori` and 1 for `natsuki`.
- `"yuri"`: a meter's name on its own means 1 point for that meter.
- `{}`: no points for anyone. A few of these make the choice less obvious.

Each name must be a meter the story declares with `points`. Then call the game with
`minigame poem_game words=<list>` and branch on the result:

```
points sayori natsuki yuri
default poem_for = None

define day1_words = {
    "sunshine": {"sayori": 3, "natsuki": 1},
    "candy": {"natsuki": 3},
    "melancholy": {"yuri": 3, "sayori": 1},
    "whisper": "yuri",
    "puppy": {"natsuki": 2, "sayori": 1},
    "eternity": {"yuri": 3},
    "ribbon": {"sayori": 2},
    "bounce": {"natsuki": 2},
    "crimson": {"yuri": 2},
    "lantern": {"yuri": 1, "natsuki": 1},
    "pencil": {},
    "window": {},
    }

label day1_poem:
    "I opened my notebook and started on a poem."
    minigame poem_game words=day1_words rounds=4 page_words=8 into poem_for
    if poem_for == "sayori":
        "Sayori clapped before I had finished reading it out."
    elif poem_for == "natsuki":
        "Natsuki pretended not to like it. She read it twice."
    elif poem_for == "yuri":
        "Yuri asked if she could keep a copy."
    else:
        "Nobody said anything. Maybe it needed more work."
```

The closing `}` of a `define` that runs over several lines is indented, like the lines inside
it. Keep lists under about 200 words: the game takes up to 2,000, but long lists make saves
bigger.

A second poem can use two lists together. `day1_words | day2_words` is one list with the
words of both. Here the result is every meter's total, the meters don't change by themselves
(`to_points=False`), and the story uses a quarter of Yuri's total:

```
define day2_words = {
    "silence": {"yuri": 2},
    "cupcake": {"natsuki": 3},
    "morning": {"sayori": 2},
    "storm": {"yuri": 1, "natsuki": 1},
    "pillow": {},
    }
default scores = {}

label day2_poem:
    minigame poem_game skippable words=day1_words | day2_words rounds=8 to_points=False result="totals" into scores
    points yuri += scores["yuri"] // 4
```

`skippable` lets the player skip the game from the game menu (Skip Game). A skipped poem
scores nothing: `into` gets `None` for `"winner"`, every meter at 0 for `"totals"`, and an
empty list for `"words"`, and no meter changes.

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `words` | none (you must give it) | a dictionary of words and their scores | The word list |
| `rounds` | `20` | a whole number from 1 to 50 | How many words the player picks |
| `page_words` | `10` | a whole number from 2 to 12 | How many words each page shows |
| `to_points` | `True` | `True` or `False` | Add each meter's total to that meter when the poem is done |
| `result` | `"winner"` | `"winner"`, `"totals"`, or `"words"` | What goes into the `into` variable |

The list needs at least `rounds + page_words - 1` words, so that every page is full: 29 words
for the defaults (20 rounds of 10 words). A word is never shown again once it is picked.

What `result` puts into the `into` variable:

- `"winner"`: the name of the meter with the highest total, such as `"sayori"`. On a tie, the
  meter declared first in `points` wins. If every total is 0, the result is `None`.
- `"totals"`: a dictionary of every meter the list names and its total, zeros included, in
  the order the meters are declared, such as `{"sayori": 3, "natsuki": 4, "yuri": 0}`.
- `"words"`: the picked words in the order the player picked them, such as
  `["sunshine", "candy"]`.

Only meters named somewhere in the list take part. A meter the list never names isn't in
`"totals"` and can't win. With `to_points=True`, each total above 0 is added to its meter
before the `into` variable is set. A meter never goes past its range.

### Playing

The page shows its words in two columns, and the counter in its top right corner shows how
many words are picked so far (`3 / 20`). The player picks a word with a click, Enter, Space,
or the gamepad's A button, and moves between words with the arrow keys, Tab, the D-pad, or
the left stick. After a pick with the keys or a gamepad, the focus stays on the same place
on the new page. A pick in the first 0.2 seconds after the page changes is ignored, so a
double click never picks a word the player hasn't seen. Esc, right click, and the gamepad's
B button open the game menu, as in every minigame.

Saving during a poem saves the start of the poem. Loading that save starts the poem again at
`0 / 20`, with the same first page. Rolling back (the mouse wheel or Page Up) during a poem
goes back to the line before it, but only until the player picks a word or moves between
words; after that, the poem holds its place.

### When a word list is refused

The game checks the arguments when the story reaches the `minigame` line, before it shows
anything. A problem stops the story with E272, which names the argument you wrote and the
reason. With one argument written, it looks like this:

`poem_game can't use words=day1_words: "sunshine" gives sayori 1.5; a score is a whole number from 0 to 99.`

With no argument or several written, the engine can't tell which one the reason is about, so
it says `poem_game can't use these arguments:` before the reason. Every reason names the
argument or word it is about. Only the first problem is reported, so fix it and run again.

| # | Reason | Fix |
|---|---|---|
| R1 | `words must be a dictionary of words and their scores, e.g. {"sunshine": {"sayori": 3}}, but it is a list.` | Write the words as a dictionary in `{ }`, each word followed by `:` and its scores. A list in `[ ]` has no scores. |
| R2 | `words has 2,400 words; the poem game takes up to 2,000.` | Use fewer words. Split a long list in two and use one per poem. |
| R3 | `"cherry blossoms in spring" is 25 characters long; a word is 1 to 24 characters on one line.` | Shorten the word or phrase to 24 characters at most. |
| R3 | `the word "" is empty; a word is 1 to 24 characters on one line.` | Remove the empty word, or write it. |
| R3 | `the word "a b" has a line break or hidden character; a word is 1 to 24 characters on one line.` | Retype the word: a line break or an invisible character from a copy and paste is in it. |
| R3 | `the word "rain " starts or ends with a space. Remove the space.` | Remove the space inside the quotes. |
| R4 | `"Rain" and "rain" are the same word. Keep one.` | Remove one of them. Capitals don't make a word different. |
| R5 | `the scores for "sunshine" must be a dictionary such as {"sayori": 3}, or one meter's name, but they are a list.` | Write the word's scores as `{"sayori": 3}`, or as one meter's name in quotes. |
| R6 | `"sunshine" scores toward "Sayori!", which can't be a meter name.` | Use a meter's name exactly as `points` declares it: letters, digits, and `_`. |
| R6 | `"sunshine" scores toward 20 meters; a word can score toward up to 16.` | Give the word fewer meters. |
| R7 | `"sunshine" gives sayori 1.5; a score is a whole number from 0 to 99.` | Use a whole number from 0 to 99, such as `2`. `True` isn't a score. |
| R8 | `rounds must be a whole number from 1 to 50, but it is 0.` | Set `rounds` from 1 to 50. |
| R9 | `page_words must be a whole number from 2 to 12, but it is 20.` | Set `page_words` from 2 to 12. |
| R10 | `20 rounds of 10 words need at least 29 words, but words has 12. Add words, or lower rounds or page_words.` | Add words, or lower `rounds` or `page_words`, as it says. |
| R11 | `to_points must be True or False, but it is "yes".` | Write `True` or `False`, without quotes. |
| R12 | `result must be "winner", "totals", or "words", but it is "winer". Did you mean "winner"?` | Use one of the three, in quotes. |
| R13 | `"sunshine" scores toward "sayory", but there is no meter named "sayory". Did you mean "sayori"?` | Fix the name, or declare the meter with `points`. |

Problems with the words (R1 to R7, in the list's order) come first, then `rounds`,
`page_words`, the list's length, `to_points`, and `result` (R8 to R12), then unknown meters
(R13).

### Testing the poem

A headless run (an automated test that plays the story with no window) never shows the
page. Unless its inputs have a `finish` for the poem, a headless run picks the first
`rounds` words of the list, in the order you wrote them, and scores them as if the player
had picked them. Shift+F8 in a test run (while you test, not in a release) does the same. So
put the words you want a test to pick first. With `day1_words` and
`rounds=4` above, a headless run picks sunshine, candy, melancholy, and whisper: Sayori 4,
Natsuki 4, Yuri 4, and the result is `"sayori"` (a tie goes to the meter declared first).
To test another result, give it with `finish`, such as
`finish "yuri"; points yuri += 20`.

Two things about the list's order:

- `a | b` puts the words of `a` first, then the words of `b` that aren't in `a`. A word in
  both keeps its place from `a` but takes its scores from `b`.
- If you write the same word twice in one dictionary, Python keeps only the second one, and
  no warning tells you. Search the list for the word if a score seems wrong.

### Saves and changing the list

A save made at a poem keeps its own copy of the word list. If you change the `define` in an
update, an old save still plays the poem with the words it was saved with. If the update
removes a meter the saved list names, or a saved list no longer passes the checks, the save
loads at the nearest point before the poem instead.

### Changing the look and the words

The page, the words, and the counter take their colors, fonts, and sizes from
`[theme.plugin.poem_game]` in `config.toml`. The tokens are listed in
[ui-system.md](ui-system.md), §3, "Poem game". The title in the save list ("Poem") and the
hint under the page ("Pick a word for your poem.") can be changed in
`[words.plugin.poem_game]`:

```toml
[words.plugin.poem_game]
title = "Poem"
hint = "Pick a word for your poem."
```

### API 1.1 notes (for minigame plugin authors)

The poem game is a minigame plugin like any you write, and it uses two hooks that minigame
API 1.1 added. A plugin that declares `api = "1.1"` can define them; a plugin that declares
`api = "1.0"` never has them called, even if it defines methods with these names.

- `check_story(self, args, story)` refuses arguments that don't fit the story. It runs right
  after `check_args` returns `None`, on the same fresh instance that is never started.
  `story` is a `StoryNames` with the declared `meters`, `items`, and `tips` (and
  `item_categories`), each in declaration order: declared, not held, so an item nobody has
  yet is listed. Return a reason text to refuse, or `None`. The engine shows a refusal as
  E272, as it does for `check_args`, and on a load it goes to the nearest point. The poem
  game checks its meter names here (R13).
- `outcome_for(self, kind, args, story)` gives the outcome for `kind` `"test"` (a headless
  run with no `finish`, and Shift+F8) or `"skipped"` (Skip Game), worked out from the
  arguments. Return an `Outcome`, or `None` to use the declared `test_outcome` or
  `skipped_outcome`. The declared ones still decide whether `skippable` is allowed. The poem
  game's test outcome scores the first `rounds` words; its skipped outcome has zero totals
  and no meter changes.
- `closest(written, names)` from `engine.minigames.api` gives the engine's did-you-mean
  suggestion (the same one the script checks use), or `None`, for a reason such as
  `Did you mean "sayori"?`.

Both hooks must have no side effects: don't change `args`, and give the same answer each
time. The engine runs them under the same time limit as `check_args`; an error, a loop, or a
value it can't use stops the story with E275 at the `minigame` line.

## Present evidence

The cross-examination (`present_evidence`) comes with the engine. A witness's testimony
shows one statement at a time over the dimmed stage, with the witness's name above it. On
any statement, the player either **presses** the witness (asks for more) or **presents** an
item from the codex that contradicts it. A wrong item can cost the player a point of a meter,
shown as a bar at the top left.

Every press or present ends the minigame at once, and the story answers it with ordinary
dialogue: the witness's reply, the judge's grumble, or the breakthrough. Then the story
starts the cross-examination again at the same statement. So all the talking stays in your
script, with its voices, sprites, history, and rollback.

### The testimony, the answer, and the loop

Write the testimony as a `define` dictionary. Each key names a statement (letters, digits,
and `_`), and its text is what the witness says. The player reads the statements in the
order you write them. A second dictionary, the answer, says which item contradicts which
statement. The items are the codex's items (`lock item`), and the player can present only
the ones they hold, so unlock the right one before the cross-examination.

This is the whole loop. Copy it, then change the names and the texts:

```
points credibility 0 to 5 start 5
default stmt = None
default shown = {}
define daichi = Character("Daichi")
define judge = Character("Judge")
lock item brass_key "Brass Key" in "Evidence":
    "Found in the grass outside the shrine gate."
lock item festival_map "Festival Map" in "Evidence"

define daichi_says = {
    "after_dark": "Nobody went near the shrine after dark.",
    "gate": "The gate was locked all night. I checked it myself.",
    "priest": "Only the priest has a key to that gate.",
    }
define daichi_answer = {"gate": "brass_key"}

label trial:
    unlock item brass_key
    unlock item festival_map
    judge "The witness may begin."
    jump cross_exam

label cross_exam:
    minigame present_evidence skippable testimony=daichi_says answer=daichi_answer speaker="Daichi" penalty="credibility" at=stmt into shown
    $ stmt = shown["statement"]
    if shown["correct"]:
        jump gate_breakthrough
    if shown["action"] == "press":
        daichi "I said what I said!"
        jump cross_exam
    judge "And how does that prove anything?"
    if points.credibility == 0:
        jump guilty_verdict
    jump cross_exam

label gate_breakthrough:
    "Objection! The key was outside the gate all along."
    return

label guilty_verdict:
    judge "That's enough. The court has heard all it needs to."
    return
```

What `into` gets is always a dictionary with four keys:

- `"action"`: `"press"` or `"present"`.
- `"statement"`: the key of the statement the player was on, such as `"gate"`.
- `"evidence"`: the item presented, such as `"festival_map"`, or `None` for a press.
- `"correct"`: `True` only when the item is in the answer for that statement.

`$ stmt = shown["statement"]` and `at=stmt` together reopen the cross-examination on the
statement the player was on, instead of the first one. A wrong item takes `cost` (1) from
the `penalty` meter once, when the story goes on after the minigame, so `points.credibility`
already shows the loss on the next line. The meter never goes below its range, so check for
0 to end the loop, as above. `skippable` lets the player skip the cross-examination from the
game menu (Skip Game); a skipped one counts as the right item presented, with no loss.

An answer can list several items, any of which is right:
`{"gate": ["brass_key", "shrine_photo"]}`. It can answer several statements too, and one
item may answer more than one statement.

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `testimony` | none (you must give it) | a dictionary of 1 to 12 statements: each key a name of up to 32 letters, digits, and `_`, each text 1 to 120 characters on one line | The statements, in the order the player reads them |
| `answer` | none (you must give it) | a dictionary of 1 to 12 of `testimony`'s keys, each with an item name or a list of 1 to 8 | Which items contradict which statements |
| `at` | `None` | `None` or a key of `testimony` | The statement shown first (`None`: the first) |
| `speaker` | `None` | `None`, or a name of 1 to 24 characters on one line | The name over the statements |
| `press` | `True` | `True` or `False` | Show the Press button. With `False`, every run ends with a present |
| `evidence` | `None` | `None`, or a list of 1 to 24 codex category names | Which of the codex's item categories the player can present from (`None`: all). Items declared without `in` are in `"codex_items"` |
| `penalty` | `None` | `None` or a meter's name | The meter shown as the bar, which a wrong item lowers. `None`: no bar and no loss |
| `penalty_max` | `5` | a whole number from 1 to 20 | The value at which the bar is full |
| `cost` | `1` | a whole number from 0 to `penalty_max` | What a wrong item takes from the meter |

**Set `penalty_max` to the meter's top**, as the `5` of `points credibility 0 to 5` above, so
the full bar is the full meter. The bar shows the meter's value, clamped to 0 to
`penalty_max`, with the number beside it (`4 / 5`).

### Playing

The box at the bottom shows the speaker, the statement, and how far into the testimony the
player is (`2 / 3`). Its buttons are **‹ Previous**, **Press**, **Present**, and **Next ›**.
Previous and Next step through the statements and wrap around at both ends; Page Up, Page
Down, and the gamepad's shoulder buttons do the same. With one statement, there is no
Previous, Next, or count.

**Present** replaces the box with the codex's item list, the same list and detail page as
the Codex page of the game menu, and the hint quotes the statement. The player reads an
item's details, then presents it with the button under them. **Back** (the button, right
click, Backspace, or the gamepad's B button) returns to the same statement and changes
nothing. Left from the list, or Down from its last row, reaches Back.

Everything works by mouse, keyboard (arrows, Tab, Enter, Space), or gamepad (D-pad, left
stick, A). There is no timer. A wrong item shows the lost part of the bar crossed out for
half a second, then shrinks it away; with reduced motion on, the bar changes at once. Esc
and the gamepad's Start button open the game menu, as in every minigame.

Saving during a cross-examination saves its start: loading starts it again at `at`, with
the meter as it was before. A loss the story hasn't taken yet is never saved.

### When the arguments are refused

The game checks the arguments when the story reaches the `minigame` line, before it shows
anything. A problem stops the story with E272. The line always writes at least two
arguments (`testimony` and `answer`), so the engine can't tell which one the reason is
about, and the message starts with `present_evidence can't use these arguments:`. A whole
message looks like this:

`present_evidence can't use these arguments: the answer for "gate" is "brass_kye", but there is no item named "brass_kye". Did you mean "brass_key"?`

Only the first problem is reported, so fix it and run again.

| # | Reason | Fix |
|---|---|---|
| R1 | `testimony must be a dictionary of statements, e.g. {"gate": "The gate was locked."}, but it is a list.` | Write the testimony as a dictionary in `{ }`, each statement's key followed by `:` and its text. A list in `[ ]` has no keys. |
| R1 | `testimony has 15 statements; a testimony has 1 to 12.` | Use at most 12 statements. Split a long testimony in two cross-examinations. |
| R2 | `"the gate" can't be a statement key; use letters, digits, and _, starting with a letter.` | Write the key as one word, such as `"the_gate"` or `"gate"`. The player never sees it. |
| R3 | `the statement "gate" is 140 characters long; a statement is 1 to 120 characters on one line.` | Shorten the statement, or split it in two statements. |
| R3 | `the statement "gate" is empty; a statement is 1 to 120 characters on one line.` | Write the statement's text, or remove the statement. |
| R3 | `the statement "gate" has a line break or hidden character; a statement is 1 to 120 characters on one line.` | Retype the text: a line break or an invisible character from a copy and paste is in it. |
| R3 | `the statement "gate" starts or ends with a space. Remove the space.` | Remove the space inside the quotes. |
| R4 | `answer must be a dictionary of statements and items, e.g. {"gate": "brass_key"}, but it is text.` | Write the answer as a dictionary: each statement's key, `:`, and its item. |
| R5 | `answer names the statement "gat", which isn't in testimony. Did you mean "gate"?` | Use a key exactly as `testimony` writes it. |
| R6 | `the answer for "gate" must be an item name or a list of 1 to 8 item names, but it is 3.` | Write one item's name in quotes, or a list of up to 8 in `[ ]`. |
| R7 | `at must be None or a statement in testimony, but it is "gat". Did you mean "gate"?` | Use a key of `testimony`, or `None` for the first statement. |
| R8 | `speaker must be None or a name of 1 to 24 characters on one line, but it is 7.` | Write the name in quotes, at most 24 characters, or leave `speaker` out. |
| R9 | `press must be True or False, but it is "yes".` | Write `True` or `False`, without quotes. |
| R10 | `evidence must be None or a list of 1 to 24 category names, e.g. ["Evidence"], but it is "Evidence".` | Put the category names in a list, even one: `evidence=["Evidence"]`. |
| R11 | `penalty must be None or a meter's name, but it is 3.` | Write the meter's name in quotes, such as `penalty="credibility"`. |
| R11 | `penalty_max must be a whole number from 1 to 20, but it is 0.` | Set `penalty_max` to the meter's top, from 1 to 20. |
| R11 | `cost must be a whole number from 0 to penalty_max (5), but it is 6.` | Lower `cost`, or raise `penalty_max`. |
| R12 | `the answer for "gate" is "brass_kye", but there is no item named "brass_kye". Did you mean "brass_key"?` | Fix the name, or declare the item with `lock item`. |
| R12 | `the answer for "gate" is "lanterns", which is a tip; only items can be presented.` | Use an item. To make a tip the answer, declare it as an item instead. |
| R13 | `penalty is "credibilty", but there is no meter named "credibilty". Did you mean "credibility"?` | Fix the name, or declare the meter with `points`. |
| R14 | `evidence names the category "Evidnce", but no item is in a category by that name. Did you mean "Evidence"?` | Use a category exactly as a `lock item … in` line writes it. |
| R14 | `the answer for "gate" is "shrine_photo", which is in "Photos", not in evidence, so it can never be presented.` | Add the item's category to `evidence`, or change the answer. |

Problems with the testimony (R1 to R3) come first, then the answer (R4 to R6), `at`,
`speaker`, `press`, `evidence`, and the penalty (R7 to R11), then names the story doesn't
declare (R12 to R14).

In a test run, the cross-examination also warns (W173) when the player can't win it: they
hold none of the answer's items, or no item at all in `evidence`'s categories. The story
still plays; unlock an item before the line, or change the answer.

### Testing the cross-examination

A headless run (an automated test that plays the story with no window) never shows the
testimony. Unless its inputs have a `finish` for it, a headless run presents the right item
on the first statement that has an answer: the first item of that statement's answer, with
no loss. Shift+F8 in a test run, and Skip Game, do the same. With the loop above, a
headless run presents the Brass Key against `"gate"` and goes on to `gate_breakthrough`. To
test another result, give it with `finish`, and the loss with it, such as
`finish {"action": "present", "statement": "gate", "evidence": "festival_map", "correct": False}; points credibility -= 1`.

### Changing the look, the sounds, and the words

The statement, the speaker's name, and the bar take their colors and size from
`[theme.plugin.present_evidence]` in `config.toml`; the box, the buttons, and the list use
the game's own panel, button, and list looks. The tokens are listed in
[ui-system.md](ui-system.md), §3, "Present evidence". Two sounds can play too, from the
game's `audio` folder: `press_sound` when the player presses, and `present_sound` when they
present an item (right or wrong). Neither plays unless you set it:

```toml
[theme.plugin.present_evidence]
press_sound = "sfx/press.ogg"
present_sound = "sfx/present.ogg"
```

Every text the cross-examination shows can be changed in `[words.plugin.present_evidence]`.
`title` is also the save description, and `{statement}` in `hint_picker` is replaced by the
statement, cut after 30 characters with "…":

```toml
[words.plugin.present_evidence]
title = "Cross-Examination"
hint = "Press the witness, or present evidence."
hint_no_press = "Present evidence that contradicts the statement."
hint_picker = "Present evidence against: “{statement}”"
previous = "‹ Previous"
next = "Next ›"
press = "Press"
present = "Present"
back = "Back"
bar_label = "Credibility"
```

## Phone chat

The phone chat (`phone_chat`) comes with the engine. A phone appears over the dimmed stage
and shows a text conversation: the contact's name at the top, the time as a divider, and
their messages arriving one at a time, each after a moment of "typing" dots. At each reply
point, buttons take the place of the message field, and the player picks one of up to four
replies, or ignores the message. The story gets a dictionary of the picks and branches on
it.

### The chat, the replies, and the result

Write the chat as a `define` list. Each item of the list is one step, played in order:

| Step | Meaning |
|---|---|
| `"you awake?"` | A message from the contact (the `contact` argument) |
| `{"me": "On my way."}` | A message from the player, without a choice |
| `{"Natsuki": "Who added me?"}` | A message from someone else, for a group chat |
| `{"time": "11:51 PM"}` | A divider with the time; the clock at the top changes to it |
| `{"ask": "walk", "sure": "Sure!", "busy": "Can't, sorry."}` | A reply point: the buttons, in the order you write them |

An ask's first key, `"ask"`, names it, and the result uses that name. Each other key names a
reply (letters, digits, and `_`) and gives its text, shown on the player's button and then
as the player's message. A reply can also be a list: its text, then up to 20 steps that
follow it, such as the contact's answer. `"ignore": True` adds a last button, "Don't reply",
set apart in italics; `"ignore": "Leave it"` gives that button your own words. Messages are
plain text; text tags like `{b}` don't work here. Build a text with Python if you need a
name in it: `"hi " + player_name`.

This is the whole scene. Copy it, then change the names and the texts:

```
default night = {}

define late_chat = [
    "you awake?",
    "i can't sleep...",
    {"ask": "awake",
        "yes": ["Yeah, what's up?", "nothing really", "just thinking about the festival"],
        "sleep": ["Go to sleep, Sayori.", "ok ok... one more thing!!"],
        "ignore": True},
    {"time": "11:51 PM"},
    "can we walk to school together tomorrow?",
    {"ask": "walk",
        "sure": "Sure. Same corner as always?",
        "busy": ["I have to go early.", "oh... ok"]},
    "night night!!",
    ]

label night_texts:
    "My phone buzzed on the desk."
    minigame phone_chat chat=late_chat contact="Sayori" time="11:42 PM" into night
    if night["awake"] == "ignore":
        "I turned the phone face down. She would be fine. Probably."
    elif night["walk"] == "sure":
        "I set my alarm ten minutes early."
    else:
        "I lay awake for a while, wondering if I should have said yes."
```

What `into` gets is a dictionary with every ask's name, in the chat's order. Each holds the
key of the reply the player picked, `"ignore"`, or `None` if the chat never got there: here
`{"awake": "yes", "walk": "sure"}`, or `{"awake": "ignore", "walk": None}`, because ignoring
closes the phone at once. A chat with no asks gives `{}`. The phone chat changes no meter
and no codex entry; write `points` lines after it for that.

**Deeper branches.** A reply's follow-ups can't hold another ask. When a reply should lead to
a different conversation, end the chat at that ask, and start a second chat inside the `if`:

```
default walk = {}
default early = {}

define walk_chat = [
    "so... can we walk to school together tomorrow?",
    {"ask": "walk", "sure": "Sure. Same corner as always?", "busy": "I have to go early."},
    ]
define early_chat = [
    "how early??",
    {"ask": "when", "seven": "Seven.", "six": "Six. Sorry."},
    "ok i'll set two alarms",
    ]

label walk_texts:
    minigame phone_chat chat=walk_chat contact="Sayori" into walk
    if walk["walk"] == "busy":
        minigame phone_chat chat=early_chat contact="Sayori" into early
```

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `chat` | none (you must give it) | a list of 1 to 200 steps, at most 1,000 counting every reply's follow-ups, with at most 20 asks | The conversation |
| `contact` | none (you must give it) | a name of 1 to 40 characters on one line | The name at the top, and who sends the plain-text messages |
| `time` | `None` | `None`, or a time of 1 to 20 characters on one line, such as `"11:42 PM"` | The first time: the clock at the top and the first divider. `None`: no clock until a time step |

The texts have limits too. A message is 1 to 300 characters with up to 4 line breaks; a
reply is 1 to 80 characters on one line; a sender's name or an ignore label is 1 to 40; a
time is 1 to 20. An ask has 1 to 4 replies, plus `"ignore"`. No text may start or end with a
space.

### Playing

Each message waits half a second, then the contact's typing dots show for 0.6 to 2 seconds
(longer for a longer message), then the message appears on the left. The player's own
messages appear on the right, in another color, after the half second only. A time step
shows its divider at once. Enter, Space, the gamepad's A button, or a left click
ends one wait, so a player who reads fast can hurry the chat along, one message per press.

At an ask, the replies show as buttons under the messages, and the chat waits as long as the
player needs. There is no timer. The player picks a reply with a click, Enter, Space, or A,
and moves between them with the arrow keys, Tab, the D-pad, or the left stick. A pick in the
first quarter of a second after the buttons appear is ignored, so a player hurrying the
messages never picks a reply by accident. The reply appears as the player's message, its
follow-ups play, and the chat goes on. "Don't reply" closes the phone at once. After the
last step, one button, "Put the phone away", ends the chat.

The mouse wheel over the messages, Page Up and Page Down, and the gamepad's shoulder buttons
scroll back through the chat; a new message scrolls to the bottom again. With two or more
senders besides the player, each sender's name shows above the first of their messages in a
row. With reduced motion on, the dots stay still and the chat scrolls without easing. Esc
and the gamepad's Start button open the game menu, as in every minigame.

Saving during a chat saves its start: loading starts it again at the first message, with
every reply open. Rolling back (the mouse wheel or Page Up, when the chat has nothing to
scroll) goes back to the line before the chat, but only until the player hurries a message,
moves between replies, picks one, or scrolls; after that, the chat holds its place.

### Reading a chat again

When the chat closes, it stays readable:

- **History.** The messages the player saw join the history log in order, right after the
  line before the chat: each of the contact's messages under the sender's name, and each
  of the player's messages and picked replies as a choice row. Time dividers are left out.
- **The Inbox.** The whole chat is kept on the **Inbox** page of the game menu, after
  Codex. The button appears once the first chat has finished. The page lists one row per
  contact, the most recent first; a chat joins the row of its contact (the declared
  contact whose shown name it uses, see "Messages" in
  [script-language.md](script-language.md)), so every chat with Sayori is one thread. A dot
  marks a row with something the player hasn't opened on the page yet. The right side shows
  the contact's chats and messages, newest first, each under its opening time, as it
  played: "Sayori: you awake?", the player's own messages as "You: …" (`[words] inbox_me`),
  and later time dividers in italics. Playing the same chat again adds it to the thread
  again.
- **Saves and going back.** The Inbox is part of the story, like the items a player holds:
  a save keeps it, loading puts it back, and rolling back to before the chat takes the row
  away again. Whether a row has been opened is remembered across saves and playthroughs.
  A save from before this version loads with an empty Inbox.

A chat the player skips (Skip Game) is kept with the replies a skip picks, so the player can
still read it there. The page's name is `[words] inbox` ("Inbox"); with a genre kit and that
word left as is, the kit names it: Messages (Romance, Cozy), Whispers (Horror), Dispatches
(Mystery), Pigeon post (Fantasy), Comms (Sci-fi), Letters (Letters). A minigame of your own
that replaces `phone_chat` adds nothing to History or the Inbox.

### When the arguments are refused

The game checks the arguments when the story reaches the `minigame` line, before it shows
anything. A problem stops the story with E272. The line always writes at least two
arguments (`chat` and `contact`), so the engine can't tell which one the reason is about,
and the message starts with `phone_chat can't use these arguments:`. A whole message looks
like this:

`phone_chat can't use these arguments: reply "yes" of ask "awake" is 95 characters long; a reply is 1 to 80 characters on one line.`

"Step 4" counts the chat's steps from 1. A step among a reply's follow-ups is named after
the reply, such as `step 2 after reply "yes" of ask "awake"`. Only the first problem is
reported, so fix it and run again.

| # | Reason | Fix |
|---|---|---|
| R1 | `chat must be a list of messages and asks, e.g. ["hi!", {"me": "hey"}], but it is a dictionary.` | Write the chat as a list in `[ ]`, one step after another. |
| R2 | `chat must have 1 to 200 steps, but it has 240.` | Split a long chat in two, with a line of story between them. |
| R2 | `chat has 1,050 steps counting replies; the most is 1,000.` | Shorten the replies' follow-ups, or split the chat in two. |
| R3 | `step 4 must be a message (text), a one-key dictionary such as {"me": "hi"}, or an ask, but it is a list.` | Write the step as text in quotes, or as a dictionary with one key such as `{"me": "hi"}`. |
| R3 | `step 4 must be a message (text), a one-key dictionary such as {"me": "hi"}, or an ask, but it is a dictionary with 2 keys.` | Give each message its own step: `{"time": "11:51 PM"}`, then `{"me": "hi"}`. |
| R4 | `step 1 is 320 characters long; a message is 1 to 300 characters with up to 4 line breaks.` | Shorten the message, or split it in two steps. |
| R4 | `step 1 is empty; a message is 1 to 300 characters with up to 4 line breaks.` | Write the message, or remove the step. |
| R4 | `step 1 has 5 line breaks; a message is 1 to 300 characters with up to 4 line breaks.` | Use fewer `\n`, or split the message in two steps. |
| R4 | `step 1 has a hidden or control character; a message is 1 to 300 characters with up to 4 line breaks.` | Retype the message: a tab or an invisible character from a copy and paste is in it. |
| R4 | `step 1 starts or ends with a space or line break. Remove it.` | Remove the space or `\n` inside the quotes. |
| R4 | `the message in step 1 isn't text; it is a whole number.` | Put the message in quotes. |
| R5 | `step 1 is from "", but a sender's name is 1 to 40 characters on one line.` | Write the sender's name before the `:`, such as `{"Natsuki": "hi"}`. |
| R5 | `step 1 is from "Natsuki ", which starts or ends with a space. Remove the space.` | Remove the space inside the quotes. With it, the name would be another sender. |
| R6 | `the time in step 4 is "", but a time is 1 to 20 characters on one line, such as "11:51 PM".` | Write the time, such as `{"time": "11:51 PM"}`. |
| R7 | `step 3 asks "stay up?", but an ask's name is letters, digits, and _.` | Name the ask with one word, such as `"stay_up"`. The player never sees it. |
| R7 | `step 8 asks "awake" again; each ask needs its own name.` | Give the second ask another name, such as `"awake2"`. |
| R8 | `ask "awake" has 5 replies; an ask has 1 to 4, plus "ignore".` | Keep four replies at most. |
| R8 | `ask "awake" has a reply named "say yes"; a reply's name is letters, digits, and _.` | Name the reply with one word, such as `"yes"`, and put the words in its text. |
| R9 | `reply "yes" of ask "awake" must be its text, or a list of its text and what follows, but it is a whole number.` | Write the reply's text in quotes, or a list that starts with it. |
| R9 | `reply "yes" of ask "awake" is 95 characters long; a reply is 1 to 80 characters on one line.` | Shorten the reply. Put the rest in a follow-up: `["Yeah.", {"me": "What's up?"}]`. |
| R9 | `reply "yes" of ask "awake" has a line break or hidden character; a reply is 1 to 80 characters on one line.` | Retype the reply on one line, without `\n`. |
| R10 | `reply "yes" of ask "awake" is followed by an ask; put the next ask after this one in chat.` | Move the ask out of the reply, after this ask in the chat, or start a second chat (Deeper branches, above). |
| R10 | `reply "yes" of ask "awake" is followed by 25 steps; the most is 20.` | Move the steps that every reply shares after the ask in the chat. |
| R11 | `ignore in ask "awake" must be True, False, or a button label of 1 to 40 characters, but it is "".` | Write `True`, `False`, or the button's words in quotes. |
| R12 | `chat has 25 asks; a chat can have up to 20.` | Split the chat in two. |
| R13 | `contact must be a name of 1 to 40 characters on one line, but it is 3.` | Write the name in quotes, such as `contact="Sayori"`. |
| R13 | `contact " Sayori" starts or ends with a space. Remove the space.` | Remove the space inside the quotes. |
| R14 | `time must be text such as "11:42 PM" (1 to 20 characters on one line), or None, but it is 2342.` | Write the time in quotes, `time="11:42 PM"`, or leave `time` out. |

Problems with the list (R1 and R2) come first, then each step in order (R3 to R11, a
reply's follow-ups with their reply), then the number of asks, `contact`, and `time` (R12 to
R14).

### Testing the chat

A headless run (an automated test that plays the story with no window) never shows the
phone. Unless its inputs have a `finish` for it, a headless run picks the first reply of
every ask, as if the player had picked each in turn. Shift+F8 in a test run, and Skip Game
(with `skippable`), do the same. So **list the neutral reply first**: it is the one a test,
or a player who skips, gets. With the chat above, a headless run gives
`{"awake": "yes", "walk": "sure"}`. To test another result, give it with `finish`, such as
`finish {"awake": "ignore", "walk": None}`.

### Saves and changing the chat

A save made at a chat keeps its own copy of the chat. If you change the `define` in an
update, an old save still plays the chat it was saved with. If a saved chat no longer passes
the checks, the save loads at the nearest point before the chat instead.

### Changing the look and the words

The phone, the messages, and the dividers take their colors, fonts, and sizes from
`[theme.plugin.phone_chat]` in `config.toml`; the reply buttons use the game's own button
look. The tokens are listed in [ui-system.md](ui-system.md), §3, "Phone chat". This makes
the phone wider and the player's messages blue:

```toml
[theme.plugin.phone_chat.phone]
body_width = 480

[theme.plugin.phone_chat.me]
fill_color = "#3A6AA8"
```

Every word the phone shows can be changed in `[words.plugin.phone_chat]`. `title` is also
the save description, and an ask's own `"ignore"` label wins over `ignore`:

```toml
[words.plugin.phone_chat]
title = "Phone"
ignore = "Don't reply"
close = "Put the phone away"
placeholder = "Message"
```

In a test run, the phone chat warns (W176) when the message font can't draw a character of
the chat, such as an emoji or a letter of another alphabet: it would show as a box. Set
`message.text_font` to a font that has it, or remove the character. The story still plays.

## Puzzle room

The puzzle room (`puzzle_room`) comes with the engine. A picture fills the screen, and the
player explores it: hotspots on the picture can be looked at, picked up, used with an item,
or clicked to leave. Two items can be combined into a third. The minigame ends each time the
story's state would change, so the story reacts at once: to a pick-up, a right use, a
combine, or the way out. The story gets a dictionary that says what happened, and passes it
back in to play the room again from where the player left it.

### The room, the state loop, and the result

Write the room as a `define` dictionary. `"background"` is an image name, as `scene` takes
it; `"hotspots"` names each hotspot and gives its fields; `"combine"` (optional) lists the
recipes. Then play the room in a loop, passing its last result back as `state`. This is the
whole scene. Copy it, then change the names, the places, and the texts:

```
lock item rusty_key "Rusty Key"
lock item string "String"
lock item magnet "Magnet"
lock item magnet_string "Magnet on a String"
lock item door_key "Door Key"

define attic = {
    "background": "bg attic",
    "hotspots": {
        "window": {"rect": [880, 90, 220, 260], "label": "Window", "look": "Snow, as far as you can see."},
        "hook":   {"rect": [300, 260, 64, 96], "label": "Coat hook", "take": "rusty_key", "image": "attic key"},
        "drawer": {"rect": [520, 420, 200, 90], "label": "Desk drawer", "use": "rusty_key", "look": "Locked.", "nope": "It doesn't fit."},
        "magnet": {"rect": [590, 440, 60, 50], "label": "Magnet", "after": "drawer", "take": "magnet", "image": "attic magnet"},
        "string": {"rect": [300, 470, 80, 60], "label": "Ball of string", "take": "string"},
        "vent":   {"rect": [1000, 440, 160, 100], "label": "Vent", "use": "magnet_string", "look": "Something glints down there."},
        "glint":  {"rect": [1040, 460, 80, 60], "label": "Key", "after": "vent", "take": "door_key"},
        "door":   {"rect": [40, 120, 180, 420], "label": "Door", "use": "door_key", "look": "Locked tight."},
        "out":    {"rect": [40, 120, 180, 420], "label": "Door", "after": "door", "exit": True},
    },
    "combine": {"magnet_string": ["magnet", "string"]},
    }
default attic_state = None

label attic_room:
    minigame puzzle_room skippable room=attic state=attic_state into attic_state
    if attic_state["hotspot"] == "drawer":
        "The key turns. Inside, a magnet."
        lock item rusty_key
    if attic_state["hotspot"] == "door":
        lock item door_key
    if attic_state["action"] == "exit":
        jump hallway
    jump attic_room

label hallway:
    "The hallway was even colder than the attic."
    return
```

Each hotspot does one thing. A hotspot with only a `"look"` shows its caption in the hint
bar. A `"take"` hotspot gives the player its item and disappears. A `"use"` hotspot waits for
one of its items (pick it in Items, then click the hotspot); until then a click shows its
`"look"`, and a wrong item shows its `"nope"`. An `"exit"` hotspot leaves. A hotspot with
`"after"` appears only once that other hotspot is spent (taken from, or used), like the
magnet in the drawer, and the open door that takes the locked door's place.

What `into` gets is a dictionary with four keys:

| Key | Holds |
|---|---|
| `"action"` | `"take"`, `"use"`, `"combine"`, `"exit"`, or `"click"` (a hotspot with no look, take, use, or exit) |
| `"hotspot"` | The hotspot's name, or `None` for a combine |
| `"item"` | The item taken, used, or made, or `None` |
| `"gone"` | Every hotspot spent so far, in room order |

The room gives the items: a take or a combine adds its item to the player's codex, with the
usual "New item" notice, and a combine also takes the two items away. **The room never takes
an item for a use**, because only your story knows whether the key is still needed. Write
`lock item` after a use, as the loop above does for the rusty key and the door key.

**Pass `state` back.** `state=attic_state` with the last result is what keeps the room as the
player left it. Without it, every spent `use` hotspot comes back: the drawer is locked again
and the magnet is gone. Taken things stay taken either way, because the player still holds
their items, but pass `state` anyway. Start the variable at `None` with `default`.

Each result ends the room, so the story can say something or change a meter before the loop
plays it again. Only `"exit"` leaves for good here; a plain `"click"` hotspot also ends the
room, so the story can react, then `jump` back.

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `room` | none (you must give it) | a dictionary with `"background"`, 1 to 40 `"hotspots"`, and up to 40 `"combine"` recipes | The picture, the hotspots, and the recipes |
| `state` | `None` | `None`, or the room's last result (its `"gone"` is a list of up to 40 hotspot names) | Where the player left the room |

A hotspot has a `"rect"` and a `"label"`, and some of these fields:

| Field | Allowed | Meaning |
|---|---|---|
| `"rect"` | `[x, y, width, height]` in whole numbers, at least 32 × 32 and inside 1280 × 720 | Where it is, in screen units, whatever the window's size |
| `"label"` | 1 to 40 characters on one line | Its name tag, shown on focus or hover |
| `"look"` | 1 to 80 characters on one line | A caption shown in the hint bar on a click (not on a take or exit) |
| `"take"` | an item name | The item the player picks up |
| `"use"` | an item name, or a list of 1 to 8 | The items that work here |
| `"nope"` | 1 to 80 characters on one line | The caption for a wrong item (needs `"use"`) |
| `"exit"` | `True` or `False` | Leaves the room |
| `"after"` | another hotspot with `"take"` or `"use"` | Shown only once that one is spent |
| `"image"` | an image name of 1 to 64 characters | A picture drawn in the rect, fitted and centered, while the hotspot shows |

A hotspot does one of take, use, or exit. The hotspot names are letters, digits, and `_`,
starting with a letter; the player never sees them. Every room needs at least one hotspot
with `"exit": True`.

### Playing

The picture fills the screen. Hotspots are invisible but for their `image`. Pointing at one,
or reaching it with the arrow keys, Tab, the D-pad, or the left stick, shows a white ring
around it and its label. A click, Enter, Space, or the gamepad's A button activates it.

**Items** (top left) opens the player's items over the room. Picking one selects it: the
hint says "Choose where to use Rusty Key", a **Put away** button appears, and the next
hotspot the player activates gets the item. With an item selected, Items picks a second
one to combine with it. Right click, Backspace, or B puts the item away (or closes Items).
Esc and the gamepad's Start button open the game menu, as in every minigame.

**Leave room between hotspots.** The arrow keys go to the nearest hotspot in that direction,
so a small hotspot tucked between big ones can be hard to reach by arrows. Tab, Page Down,
and the gamepad's RB step through every hotspot in room order (Shift+Tab, Page Up, and LB go
back), so none is ever out of reach, but a room the arrows cover is easier to play. Where
two hotspots overlap, the later one in room order gets the click, so keep a small hotspot out
of a big one's rect, or the player can't click it. Keep hotspots out of the top left, where
the buttons are, and above y 540, where the hint bar grows at larger text sizes.

Saving in a room saves its start: loading plays the room again from its arguments, with the
items the player holds. Looks, wrong tries, and the selected item aren't saved. Rolling back
(the mouse wheel) goes back to the line before the room until the player activates anything;
after that, the room holds its place.

### When the arguments are refused

The game checks the arguments when the story reaches the `minigame` line, before it shows
anything. A problem stops the story with E272. The line in the loop writes two arguments
(`room` and `state`), so the engine can't tell which one the reason is about, and the
message starts with `puzzle_room can't use these arguments:`. A whole message looks like
this:

`puzzle_room can't use these arguments: hotspot "hook" has "takes", which isn't a hotspot field. Did you mean "take"?`

Only the first problem is reported, so fix it and run again.

| # | Reason | Fix |
|---|---|---|
| R1 | `room has "hotspot", which isn't background, hotspots, or combine. Did you mean "hotspots"?` | Spell the key as the example above does. |
| R1 | `room must be a dictionary with "background" and "hotspots", but it is a list.` | Write the room in `{ }`, with `"background"` and `"hotspots"` keys. |
| R2 | `background must be an image name such as "bg attic", but it is 3.` | Write the picture's name in quotes, as for `scene`. |
| R3 | `hotspots must be a dictionary of 1 to 40 hotspots, but it has 45.` | Split the room in two rooms, joined by an exit. |
| R3 | `"coat hook" can't be a hotspot name; use letters, digits, and _, starting with a letter.` | Name the hotspot with one word, such as `"coat_hook"`, and put the words in its label. |
| R4 | `hotspot "hook" has "takes", which isn't a hotspot field. Did you mean "take"?` | Spell the field as the hotspot table above does. |
| R5 | `the rect of "hook" must be [x, y, width, height] in whole numbers, at least 32 × 32 and inside 1280 × 720, but it is [300, 260].` | Give all four numbers, and keep the box on the 1280 × 720 screen. |
| R6 | `the look of "window" is 95 characters long; a caption is 1 to 80 characters on one line.` | Shorten the caption, and say the rest in the story. |
| R6 | `the label of "hook" is empty; a label is 1 to 40 characters on one line.` | Write the name the player sees, such as `"Coat hook"`. |
| R7 | `hotspot "drawer" has both take and use; a hotspot does one of take, use, or exit.` | Split it in two hotspots, the second with `"after"` the first, like the magnet. |
| R7 | `hotspot "hook" has both look and take; a hotspot that takes or leaves ends the run at once, so it has no look.` | Remove the look, and say it in the story after the take. |
| R7 | `hotspot "window" has nope but no use; nope is the caption for a wrong item, so it needs use.` | Remove the nope, or give the hotspot a `"use"`. |
| R8 | `the use of "drawer" must be an item name or a list of 1 to 8 item names, but it is 3.` | Write the item's name in quotes, or a list of names in `[ ]`. |
| R9 | `hotspot "magnet" comes after "drawr", which isn't in hotspots. Did you mean "drawer"?` | Name a hotspot of this room. |
| R9 | `hotspot "magnet" comes after "window", which has no take or use, so it is never spent.` | Point `"after"` at a hotspot the player takes from or uses something on. |
| R10 | `the image of "hook" must be an image name such as "attic key", but it is True.` | Write the picture's name in quotes, or leave `"image"` out. |
| R11 | `the exit of "out" must be True or False, but it is "yes".` | Write `True` (no quotes), or leave `"exit"` out. |
| R11 | `room has no hotspot with "exit": True, so it can't be left.` | Add a way out, such as a door with `"exit": True`. |
| R12 | `combine must map each made item to two different items, e.g. {"magnet_string": ["magnet", "string"]}, with at most 40 recipes.` | Write each recipe as the made item, then a list of the two items. |
| R12 | `combine lists "magnet" and "string" twice.` | Keep one recipe for each pair of items. |
| R13 | `state must be None or the room's last result, but it is a list.` | Pass `None`, or the variable the room's `into` filled. |
| R13 | `state must be None or the room's last result, whose "gone" is a list of up to 40 hotspot names, but its "gone" is "hook".` | Don't build the state by hand; pass the room's last result. |
| R14 | `the take of "hook" is "rusty_kye", but there is no item named "rusty_kye". Did you mean "rusty_key"?` | Spell the item as its `lock item` line does, or declare it. |
| R14 | `the take of "hook" is "lanterns", which is a tip; only items can be held.` | Declare an item with `lock item`, and use its name. |

Problems with the room itself come first (R1 to R3), then each hotspot in room order (R4 to
R11), then the recipes, `state`, and the item names (R12 to R14).

### Testing the room

A headless run (an automated test that plays the story with no window) never shows the
room. Unless its inputs have a `finish` for it, a headless run leaves by the first exit in
room order, as if the player had walked out at once: with the room above,
`{"action": "exit", "hotspot": "out", "item": None, "gone": []}`. Shift+F8 in a test run, and
Skip Game (with `skippable`), do the same. So a loop like the one above always ends in a
test. To test a pick-up, give it with `finish`, with the item the room would give, such as
`finish {"action": "take", "hotspot": "hook", "item": "rusty_key", "gone": ["hook"]}; unlock item rusty_key`.

While you test, the room checks itself as it opens, and warns once for each problem:

- **W179**, when the player can't leave: no exit is shown, and nothing the player holds or
  can find in the room works on the hotspots in the way. The check knows only this room:
  **an item your script gives the player later is invisible to it**, so it can warn about a
  room that waits for one. Give the item before the room, or ignore the warning there.
- **W180**, when a hotspot is mostly under the Items row or the hint bar at the current text
  size. The check uses the widest hint the screen can show, so a hotspot beside a short hint
  can still warn. Move the hotspot up, or make it bigger.

Neither warning stops the story, and neither shows in a release.

### Changing the look and the words

The ring around the focused hotspot takes its colors from `[theme.plugin.puzzle_room]` in
`config.toml`; the buttons, the name tag, and the item picker use the game's own look. The
tokens are listed in [ui-system.md](ui-system.md), §3, "Puzzle room". This makes the ring
gold:

```toml
[theme.plugin.puzzle_room.spot]
ring_color = "#FFD27A"
ring_shadow_color = "#3A2400"
```

Every word the room shows can be changed in `[words.plugin.puzzle_room]`. `title` is also
the save description, `{item}` is the selected item's title, and `hint_using_only` replaces
`hint_using` in a room without `"combine"`:

```toml
[words.plugin.puzzle_room]
title = "Puzzle Room"
hint = "Look around. Pick an item in Items to use it."
hint_using = "Choose where to use {item}, or combine it in Items."
hint_using_only = "Choose where to use {item}."
hint_picker = "Choose an item to use."
hint_combine = "Choose an item to combine with {item}."
items = "Items"
back = "Back"
use = "Use"
combine = "Combine"
put_away = "Put away {item}"
need_item = "You need something for this."
no_use = "That doesn't work."
no_combine = "Those don't go together."
```

## Heartbeat

Heartbeat (`heartbeat`) comes with the engine. A ring closes toward a circle on a steady
beat, and the player presses as it meets the circle, to keep their composure. The result is
the number of beats hit. Each miss can lower a meter.

```
points composure 0 to 10 start 5
default calm = 0

label confession:
    minigame heartbeat skippable beats=8 meter="composure" sound="sfx/heartbeat.ogg" into calm
    if calm >= 6:
        hana "I... I like you. I have for a long time."
    else:
        hana "I... never mind. It's nothing."
```

A pulse can be a sensitive image (panic, anxiety). If your game uses Heartbeat in a hard
scene, consider a content warning (`[content_warning]`, see
[script-language.md](script-language.md)).

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `beats` | `8` | a whole number from 4 to 20 | How many beats the player presses on |
| `bpm` | `60` | a whole number from 40 to 120 | Beats a minute: 60 is one beat a second |
| `window` | `"normal"` | `"tight"` (±0.15 s), `"normal"` (±0.25 s), `"wide"` (±0.40 s) | How close to the beat a press must be; never more than 40 % of the time between beats |
| `meter` | `None` | `None`, or a meter's name | The meter a miss lowers |
| `cost` | `1` | a whole number from 0 to 20 | How much each miss lowers `meter` |
| `sound` | `None` | `None`, or a sound file in quotes (up to 260 characters) | Plays on each beat, with the ring |

### Playing

"Ready…" shows in the circle for 1 second. Then a ring closes in over one beat and meets the
circle on the beat; the next ring starts as it lands. The player presses as the ring meets
the circle: a click anywhere in the game, Space, Enter, or the gamepad's A button. A press
within the window is a hit ("Steady", and the circle's border turns the hit color). A press
up to half a beat early, or no press before the window ends, is a miss ("Missed"). Each beat
is judged once, and other presses do nothing. The dots under the circle fill in: a filled
dot for a hit, a dash for a miss, a ring for a beat to come.

At the end, "6 of 8" shows for 1.5 seconds (a press ends it early), and the game fades back
to the story. With `meter`, the meter goes down by `cost` for each miss, once, at the end.

- **Timing assist** (the player's setting, Settings ▸ Display): **Slower** doubles the
  lead-in, the time between beats, and the window. **No time limits** closes each ring at
  the normal pace, then waits on the circle until the player presses; every press then
  counts, so the result is always `beats` and the meter is unchanged. A change during the
  game applies from the next beat.
- **Reduce motion**: the ring doesn't move; it shows at three sizes (far, halfway, on the
  circle). Nothing ever flashes: only the circle's border changes color, at most twice a
  second.
- **Sound** is never the only cue: the ring always shows the beat. Under No time limits,
  the sound plays as each ring reaches the circle.
- The game menu (Esc, Start) and leaving the window pause the beat.
- **Skip Game** (with `skippable`) gives a full score, `beats`, and leaves the meter as it
  was. Saving during the game saves its start: loading plays it again from the lead-in.

### When the arguments are refused

A problem stops the story with E272, `heartbeat can't use these arguments:` and the reason.
Only the first problem is reported.

| Reason | Fix |
|---|---|
| `beats must be a whole number from 4 to 20, but it is 3.` | Use 4 to 20 beats, written without a decimal point. |
| `bpm must be a whole number from 40 to 120, but it is 150.` | Use 40 to 120 beats a minute. |
| `window must be "tight", "normal" or "wide", but it is "loose".` | Pick one of the three, in quotes. |
| `meter must be None or a meter's name, but it is 3.` | Write the meter's name in quotes, or leave `meter` out. |
| `meter names "composre", which no points line declares. Did you mean "composure"?` | Spell the meter as its `points` line does, or declare it. |
| `cost must be a whole number from 0 to 20, but it is 25.` | Use 0 to 20. |
| `sound must be None or a sound file in quotes, such as "sfx/heartbeat.ogg", but it is 5.` | Write the file in quotes, on one line, up to 260 characters. |

### Testing Heartbeat

A headless run, Shift+F8 in a test run, and Skip Game end Heartbeat with a full score
(`beats`) and no meter change. To test a low score, give it with `finish`, such as
`finish 3; points composure -= 5`.

### Changing the look and the words

Heartbeat's colors come from `[theme.plugin.heartbeat]`. Each one follows a token of the
game's own look by default, so every color scheme applies:

| Token | Default |
|---|---|
| `target.fill_color` | `button.fill_color` |
| `target.border_color` | `button.border_color` |
| `target.text_color` | `button.text_color` |
| `ring.line_color` | `slider.fill_color` |
| `hit_color` | `button.focused.border_color` |
| `miss_color` | `button.disabled.text_color` |
| `dot.empty_color` | `button.border_color` |

Every word can be changed in `[words.plugin.heartbeat]`. `title` is also the save
description; `hint_wait` replaces `hint` under No time limits; `{hits}` and `{beats}` are the
score:

```toml
[words.plugin.heartbeat]
title = "Heartbeat"
hint = "Press when the ring meets the circle: click, Space, Enter, or A."
hint_wait = "Press when the ring reaches the circle. Take your time."
ready = "Ready…"
hit = "Steady"
miss = "Missed"
result = "{hits} of {beats}"
```

## Code lock

The Code lock (`code_lock`) comes with the engine. It shows a keypad, or a combination dial, over
the dimmed scene. The player opens it with a code the story gave them, such as the date in a
diary. The result is `True` when it opened, else `False`. No data is needed: in Studio, the
Minigame form is the whole setup.

```
default safe_open = False

label study:
    minigame code_lock skippable code="0417" tries=3 hint="The date on the diary." into safe_open
    if safe_open:
        "The safe clicked open."
```

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `code` | required | text in quotes. Keypad: 1 to 12 digits. Dial: 3 to 6 digits, or 3 to 6 letters A to Z | The code that opens it. Write it in quotes, so a leading 0 stays |
| `kind` | `"keypad"` | `"keypad"`, `"dial"` | Number buttons, or wheels the player turns |
| `tries` | `0` | a whole number from 0 (no limit) to 99 | Wrong codes allowed before the lock stays shut |
| `hint` | `None` | text, 1 to 120 characters on one line, or `None` | Shown in the hint bar after some wrong tries |
| `hint_after` | `3` | a whole number from 0 to 99 | Wrong tries before the hint shows; 0 shows it from the start |
| `leave` | `True` | `True` or `False` | `True` shows a Step back button, which gives `False` |

A dial with a letter code ignores capitals: `code="love"` opens with LOVE.

### Playing

- **Keypad.** The player types digits with the number keys (top row or number pad), or
  presses the buttons by mouse, arrow keys and Enter, or the gamepad. Backspace deletes a
  digit, and Clear deletes them all. Enter works once every slot is filled; typing past
  the last slot does nothing. When the keyboard or gamepad fills the last slot, Enter gets
  the focus.
- **Dial.** One wheel per character. Up and Down (keys, D-pad, stick, a click on ▲ or ▼,
  or the mouse wheel over a wheel) turn it, and 9 turns to 0, Z to A. Left and Right move
  between wheels and then to Open. Typing a digit or letter sets the wheel and moves on.
  Enter or A on a wheel is Open. Wheels start at 0, or at A for a letter code.
- **A wrong code** says so in words, with the tries left: "Wrong code. 2 tries left." The
  keypad clears; the wheels stay where they are. After the last allowed wrong try, the lock
  says "No tries left. The lock stays shut." with one Continue button, and the result is
  `False`.
- **The right code** shows "Open!" and the story goes on a moment later with `True`.
- **The hint** replaces the hint bar's words after `hint_after` wrong tries: "Hint: The date
  on the diary."
- **Reduce motion**: a wheel's turn and the wrong-code shake are cuts. Nothing is ever shown
  by color alone. **Skip Game** (with `skippable`) counts as opened.

A lock that can't be left (`leave=False`), with no try limit and no hint, leaves a player who
missed the code only Skip Game or a load. A dev run says so once, with W280:
`code_lock can't be left: leave=False, tries=0 and no hint, so a player who missed the code
can only skip or load. Add a hint, a try limit, or leave=True.`

### When the arguments are refused

A problem stops the story with E272, `code_lock can't use these arguments:` and the reason.
Only the first problem is reported, in this order:

| Reason | Fix |
|---|---|
| `kind must be "keypad" or "dial", but it is "dail". Did you mean "dial"?` | Write one of the two, in quotes. |
| `code must be text in quotes, such as code="0417", but it is a whole number.` | Put the code in quotes, so a leading 0 isn't lost. |
| `a keypad code is 1 to 12 digits from 0 to 9, but code is "12a4".` | Use digits only, or `kind="dial"` for letters. |
| `a dial code is 3 to 6 digits, or 3 to 6 letters from A to Z, but code is "12".` | Use 3 to 6 digits, or 3 to 6 letters, not both. |
| `tries must be a whole number from 0 (no limit) to 99, but it is 100.` | Use 0 to 99. |
| `hint must be text in quotes, or None, but it is a whole number.` (and the text rules below) | Write the hint in quotes, on one line, up to 120 characters. |
| `hint_after must be a whole number from 0 to 99, but it is -1.` | Use 0 to 99. |
| `leave must be True or False, but it is "yes".` | Write `True` or `False`, without quotes. |

### Testing the Lock

A headless run, Shift+F8 in a test run, and Skip Game open the lock: the result is `True`.
To test a lock that stays shut, give `finish False`.

### Changing the look and the words

The Lock draws with the game's own `panel` and `button` colors, so every color scheme
applies. `[theme.plugin.code_lock]` has a size and three sounds (none by default):

| Token | Default |
|---|---|
| `display.text_size` | `48` (32 to 64) |
| `turn_sound` | none |
| `wrong_sound` | none |
| `open_sound` | none |

Every word can be changed in `[words.plugin.code_lock]`; `{n}` is the tries left:

```toml
[words.plugin.code_lock]
title = "Lock"
hint_keypad = "Enter the code."
hint_dial = "Turn the wheels to the code, then choose Open."
hint_prefix = "Hint: "
clear = "Clear"
enter = "Enter"
open = "Open"
leave = "Step back"
wrong = "Wrong code."
tries_left = "{n} tries left."
try_left = "1 try left."
opened = "Open!"
locked_out = "No tries left. The lock stays shut."
continue = "Continue"
```

## Stay still

Stay still (`stay_still`) comes with the engine. A character tells the player not to touch
anything, and a countdown runs. Each key press, click, wheel notch or gamepad button is a
flinch. The result is the number of flinches.

```
default flinches = 0

label hands_off:
    effect window_title "Don't move."
    minigame stay_still seconds=15 speaker="Monika" line="Don't touch anything. I'll know." into flinches
    effect window_title off
    if flinches == 0:
        monika "Good. You can listen."
```

The game itself never reads the player's name, the window title or any file. Keep that kind
of effect in the story around it, as above: a window title, `{username}` in a line after it,
or a `file write` when the player flinched.

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `seconds` | `10` | a whole number from 3 to 120 | How long the player must not touch anything |
| `line` | `None` ("Don't touch anything.") | text, 1 to 160 characters on one line | The line shown while the player waits |
| `speaker` | `None` (no name) | text, 1 to 24 characters | The name above the line |
| `flinch_line` | `None` ("Don't move.") | text, 1 to 160 characters on one line | Shown for 2 seconds after each flinch |
| `strict` | `False` | `True` or `False` | `True`: the first flinch ends the game, with the result 1 |
| `mouse` | `False` | `True` or `False` | `True`: moving the mouse counts as a flinch |
| `ready` | `True` | `True` or `False` | `True` shows an "I'm ready" button first |

### Playing

- With `ready`, the player presses **I'm ready** (click, Enter, or A); the countdown starts
  half a second later. With `ready=False` it starts a second after the game appears. Nothing
  counts before that.
- **A flinch** is any key press (a key held down counts once), a left, middle or extra
  mouse button, a wheel notch, any gamepad button, a D-pad or stick step, and, with
  `mouse=True`, moving the pointer 24 units. Presses within a quarter of a second of a
  flinch are the same flinch. Each flinch shows `flinch_line` for 2 seconds.
- **Never a flinch:** Esc, the gamepad's Start and B buttons and the right mouse button
  (they open the game menu, and the countdown waits while it is open), F5 and F9,
  releasing a key or button, Shift, Ctrl, Alt or the Windows key pressed on their own, and
  leaving the window: the countdown waits until the window has focus again, and the click
  that brings it back doesn't count.
- At 0 the story goes on with the count. With `strict=True`, the first flinch ends it with
  1.
- **Timing assist** doesn't apply: the game asks the player to do nothing. A player who
  can't keep still can use **Skip Game** (with `skippable`), which gives 0.
- **Reduce motion**: the bar under the countdown steps once a second instead of draining.

### When the arguments are refused

A problem stops the story with E272, `stay_still can't use these arguments:` and the reason.
Only the first problem is reported, in this order:

| Reason | Fix |
|---|---|
| `seconds must be a whole number from 3 to 120, but it is 2.` | Use 3 to 120 seconds. |
| `line must be text in quotes, or None, but it is a whole number.` (and the text rules below) | Write the line in quotes, on one line, up to 160 characters. |
| `speaker is 30 characters long; it is 1 to 24 characters on one line.` | Use a name of 1 to 24 characters. |
| `flinch_line is empty; it is 1 to 160 characters on one line.` | Write the line, or leave `flinch_line` out. |
| `strict must be True or False, but it is 1.` | Write `True` or `False`. |
| `mouse must be True or False, but it is "yes".` | Write `True` or `False`. |
| `ready must be True or False, but it is None.` | Write `True` or `False`. |

### Testing Stay still

A headless run, Shift+F8 in a test run, and Skip Game give 0 flinches. To test the other
branch, give `finish 2`.

### Changing the look and the words

Stay still draws with the game's `panel` and `slider` colors. `[theme.plugin.stay_still]`:

| Token | Default |
|---|---|
| `line.text_size` | `32` (24 to 40) |
| `flinch_sound` | none |

```toml
[words.plugin.stay_still]
title = "Stay Still"
hint_ready = "Press I'm ready, then don't touch anything."
hint = "Don't press anything until the time is up."
ready = "I'm ready"
line = "Don't touch anything."
flinch_line = "Don't move."
```

## Hand game

The hand game (`hand_game`) comes with the engine: rock, paper, scissors against a
character, who may play fair or cheat. The result is `"won"`, `"lost"` or `"draw"`.

```
default rps = None

label recess:
    minigame hand_game opponent="Hana" rounds=3 mode="cheat" into rps
    if rps == "lost":
        hana "Did you see that? ...No, you didn't."
```

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `opponent` | required | text, 1 to 24 characters | Who the player plays against, as shown |
| `rounds` | `3` | a whole number from 1 to 9 | How many rounds at most; draws count as rounds |
| `mode` | `"fair"` | `"fair"`, `"kind"`, `"cheat"`, `"sly"` | How they play |

- **fair**: her hand is random.
- **kind**: she lets the player win, without showing it. The result is always `"won"`.
- **cheat**: when her hand would lose, it switches to the winning one after a moment, and
  the player sees it: "Hana switched hands!"
- **sly**: when her hand would lose, she shows the winning one at once. No switch shows.

Her hand is picked at the start of each round, before the player picks, so a load replays
the same hands. The match ends early when one side can't be caught.

### Playing

The player picks Rock, Paper or Scissors (click, arrow keys and Enter, or the gamepad).
Both cards show, and a caption says who won the round. **Next round** goes on; at the end, a
second caption says "You won!", "You lost." or "It's a draw.", and **Continue** returns to
the story. **Reduce motion** makes the cheating switch a cut (the caption still says it).
**Skip Game** (with `skippable`) gives `"draw"`.

### When the arguments are refused

A problem stops the story with E272, `hand_game can't use these arguments:` and the reason.
Only the first problem is reported, in this order:

| Reason | Fix |
|---|---|
| `opponent must be text in quotes, but it is None.` (and the text rules below) | Write a name of 1 to 24 characters, in quotes. |
| `rounds must be a whole number from 1 to 9, but it is 10.` | Use 1 to 9. |
| `mode must be "fair", "kind", "cheat", or "sly", but it is "cheet". Did you mean "cheat"?` | Use one of the four, in quotes. |

**The text rules** (Lock's `hint`, Stay still's `line`, `speaker` and `flinch_line`, and
`opponent`) have these reasons, with the argument's name and its most characters:

| Reason | Fix |
|---|---|
| `hint is empty; it is 1 to 120 characters on one line.` | Write some text, or leave the argument out. |
| `hint is 130 characters long; it is 1 to 120 characters on one line.` | Shorten it. |
| `hint has a line break or hidden character; it is 1 to 120 characters on one line.` | Keep it on one line, with no hidden characters. |
| `hint starts or ends with a space. Remove the space.` | Remove the space. |

### Testing the hand game

A headless run and Shift+F8 in a test run give `"won"` for `fair` and `kind`, and `"lost"`
for `cheat` and `sly`. Skip Game gives `"draw"`. Give another result with `finish "draw"`.

### Changing the look and the words

The hand game draws with the game's `panel` and `button` colors. `[theme.plugin.hand_game]`
has a size, a sound, and a picture for each hand (none by default: the word shows). A
picture is shrunk to fit the card, never stretched; a missing one shows the word.

| Token | Default |
|---|---|
| `hand.text_size` | `48` (32 to 64) |
| `hand.rock_image` | none |
| `hand.paper_image` | none |
| `hand.scissors_image` | none |
| `reveal_sound` | none |

`{name}` is the opponent, `{n}` and `{total}` the round, `{you}` and `{them}` the score:

```toml
[words.plugin.hand_game]
title = "Rock, Paper, Scissors"
hint = "Pick a hand."
rock = "Rock"
paper = "Paper"
scissors = "Scissors"
you = "You"
round = "Round {n} of {total}"
score = "You {you} – {them} {name}"
win_round = "You win this round."
lose_round = "{name} wins this round."
draw_round = "A draw."
switched = "{name} switched hands!"
next = "Next round"
won = "You won!"
lost = "You lost."
draw = "It's a draw."
continue = "Continue"
```

## Gift giving

Gift giving (`gift_giving`) comes with the engine. The player picks an item they hold and
gives it to a character. A **gift table** says how the character takes each item: a
reaction, points for their meter, and a line they say. Any other item uses the character's
"any other gift" row (`"*"`). The result is the reaction (`"loved"`, `"liked"`, `"neutral"`
or `"disliked"`), or `None` when nothing was given.

```
points hana daichi 0 to 10
lock item red_lantern "Red Lantern" in "Gifts"
lock item umbrella "Umbrella" in "Gifts"
default reaction = None

define birthday_gifts = {
    "hana": {
        "*": ["neutral", 0, "Oh. Thank you."],
        "red_lantern": ["loved", 3, "You kept it all this time?"],
        "umbrella": ["liked", 1],
        },
    "daichi": {
        "umbrella": ["disliked", -1, "I have three of these."],
        },
    }

label birthday:
    minigame gift_giving skippable gifts=birthday_gifts to="hana" categories=["Gifts"] into reaction
    if reaction == "loved":
        hana happy "Best birthday ever."
```

### The gift table

- Each key is a character, named like a meter: letters, digits and `_` (up to 32
  characters in a table).
- Each character maps item names (declared with `lock item` or `item`; up to 200) and
  `"*"` (any other gift) to a list: the reaction (`"loved"`, `"liked"`, `"neutral"` or
  `"disliked"`), the points (a whole number from -10 to 10), and, if you like, the line the
  character says (1 to 160 characters on one line).
- An item that isn't listed uses the `"*"` row; with no `"*"` row it is neutral, 0 points
  and no line.
- Points change the meter named like the character, so a character whose gifts give points
  needs a `points` line. A character whose points are all 0 doesn't.

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `gifts` | required | a gift table | Who likes what |
| `to` | required | a character in the table | Whose reactions to use; their meter changes |
| `speaker` | `None` (`to` with a capital first letter) | text, 1 to 24 characters | The name on the reaction card |
| `categories` | `None` (every item) | a list of 1 to 24 item category names | Only items in these categories can be given |
| `use_up` | `True` | `True` or `False` | `True`: the given item leaves the inventory |
| `leave` | `True` | `True` or `False` | `True` shows a Not now button |
| `result` | `"reaction"` | `"reaction"` or `"item"` | The result: the reaction word, or the given item's name |

### Playing

The codex item list opens over the dimmed scene, showing only the items the player holds
(in `categories`). The player reads an item, then chooses **Give**. A card shows the
character's name, their line and how they took it ("Hana loved it."), with **Continue**.
Then the item is taken (with `use_up`), the meter changes by the points (if they aren't 0;
it stays inside the meter's range), and the story goes on with the result. Nothing changes
before Continue.

- **Not now** (with `leave`), Backspace, the right mouse button or the gamepad's B button
  give `None` and change nothing.
- When the player holds nothing the list could show, a panel says "You have nothing to
  give." with Continue, and the result is `None`. A dev run warns once, with W285:
  `gift_giving to "hana": the player holds no item the picker can show, so the game says "You
  have nothing to give." and the result is None.`
- Mouse, keyboard and gamepad all work; nothing is timed or moves. **Skip Game** (with
  `skippable`) gives `"neutral"` (or `None` with `result="item"`), and nothing is given or
  taken.

### When the arguments are refused

A problem stops the story with E272, `gift_giving can't use these arguments:` and the
reason. Only the first problem is reported, characters and items in the order written:

| Reason | Fix |
|---|---|
| `gifts must be a dictionary of characters and their gifts, such as {"hana": {"red_lantern": ["loved", 3]}}, but it is a list.` | Write the table in `{ }`, as above. |
| `gifts has 0 characters; it can have 1 to 32.` | Give 1 to 32 characters. |
| `"Hana Li" can't be a character in gifts; write it as points names a meter: letters, digits, and _.` | Use the character's meter name. |
| `the gifts for "hana" must be a dictionary of items and reactions, but they are a list.` | Write the character's gifts in `{ }`. |
| `"hana" has 201 gifts; a character can have up to 200.` | List fewer items; use `"*"` for the rest. |
| `"red lantern" in the gifts for "hana" can't be an item name; write an item's name, or "*" for any other gift.` | Write the item's name as declared. |
| `the gift "coin" for "hana" must be a list such as ["loved", 3, "Thank you!"], but it is text.` (or `…, but it has 1 parts.`) | Write a list of the reaction, the points and, if you like, a line. |
| `the gift "coin" for "hana" has the reaction "lovd"; a reaction is "loved", "liked", "neutral", or "disliked". Did you mean "loved"?` | Use one of the four. |
| `the gift "coin" for "hana" gives 11 points; points are a whole number from -10 to 10.` | Use -10 to 10. |
| `the line for "coin" (hana) is empty; it is 1 to 160 characters on one line.` (and the text rules of the hand game) | Write the line in quotes, on one line, or leave it out. |
| `to must be one of the characters in gifts ("hana", "daichi"), but it is "hanna". Did you mean "hana"?` | Use a character from the table. |
| `speaker is empty; it is 1 to 24 characters on one line.` | Write a name, or leave `speaker` out. |
| `categories must be a list of 1 to 24 item category names, such as ["Gifts"], or None, but it is text.` | Write a list in `[ ]`. |
| `category 2 in categories starts or ends with a space. Remove the space.` | Write each category's name as declared. |
| `use_up must be True or False, but it is 1.` (and `leave`) | Write `True` or `False`. |
| `result must be "reaction" or "item", but it is "items". Did you mean "item"?` | Use one of the two. |
| `the gifts for "hana" name the item "paper_lanter", but there is no item named "paper_lanter". Did you mean "paper_lantern"?` | Spell the item as its `item` line does, or declare it. |
| `the gifts for "daichi" give points, but there is no meter named "daichi". Declare it with points daichi, or set its points to 0.` | Add `daichi` to a `points` line, or use 0 points. |
| `there is no item category "codex_item". Did you mean "codex_items"?` | Spell the category as its `item` lines do. |

### Testing gift giving

A headless run, Shift+F8 in a test run, and Skip Game give `"neutral"` (or `None` with
`result="item"`) and change nothing. To test a gift, give its result and changes with
`finish`, such as `finish "loved"; points hana += 3`.

### Changing the look and the words

Gift giving draws with the game's `panel` and `button` colors and the codex's look.
`[theme.plugin.gift_giving]`:

| Token | Default |
|---|---|
| `line.text_size` | `28` (24 to 40) |
| `give_sound` | none |

`{name}` is the speaker:

```toml
[words.plugin.gift_giving]
title = "Gift"
hint = "Choose a gift for {name}."
give = "Give"
not_now = "Not now"
nothing = "You have nothing to give."
continue = "Continue"
loved = "{name} loved it."
liked = "{name} liked it."
neutral = "{name} accepted it."
disliked = "{name} didn't like it."
```

## Ask for text

Ask for text (`ask_text`) comes with the engine. A question and a text field appear over the
dimmed scene; the player types an answer (a name, a password, a word) and presses Enter or
OK. The answer, trimmed at both ends, goes into the `into` variable.

```
default player_name = ""

label start:
    hana "Wait, I never asked. What's your name?"
    minigame ask_text prompt="What's your name?" max_length=12 allowed="name" into player_name
    hana "{var=player_name}! That's a nice name."
```

`{var=player_name}` shows the answer exactly as typed: braces in it stay braces, so a player
can't add text tags.

In Studio: **Events ▸ Insert ▸ Ask for a name…** fills in the line above (and offers to add
`default player_name = ""`), or **Insert ▸ Minigame ▸ Ask for text** for any question.

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `prompt` | the word `prompt` | text of 1 to 300 characters | The question |
| `default` | `None` | `None`, or text | The starting text (also the test answer) |
| `max_length` | `20` | a whole number from 1 to 200 | The longest answer, in characters |
| `allowed` | `"any"` | `"any"`, `"name"` (letters, marks, space, `-`, `'`, `’`, `.`), `"letters"`, `"digits"` (0 to 9), `"letters_digits"` | What the player can type |
| `hide` | `False` | `True` or `False` | Dots instead of letters (a password) |
| `can_be_empty` | `False` | `True` or `False` | Whether OK takes an empty answer |

### Playing

- **Keyboard:** type, fix mistakes with Backspace, Delete, Left, Right, Home and End, and
  press Enter. Japanese and other input methods work, and Ctrl+V pastes the first line of
  the clipboard. A character `allowed` refuses isn't added ("That character can't be used
  here."), and typing stops at `max_length` ("That's as long as it can be.").
- **Controller:** press A on the field for the on-screen keyboard: the D-pad moves, A types,
  X deletes, Y adds a space, the bumpers change the page, and Done finishes. B closes it and
  keeps the text. Its pages follow the game's language and fonts.
- **Mouse:** click in the field to place the cursor, and the small keyboard picture at its
  right end for the on-screen keyboard.
- Esc opens the game menu; the typed text is still there afterwards. Saving while typing
  and loading that save asks the question again, starting from `default`.

### When the arguments are refused

The story stops at the line (E272) with one of these:

- `prompt must be text of 1 to 300 characters, but it has 412.`
- `max_length must be a whole number from 1 to 200, not 0.`
- `allowed must be "any", "name", "letters", "digits" or "letters_digits", not "letter". Did you mean "letters"?`
- `default can hold at most 12 characters (max_length), but it has 31.`
- `default has characters allowed="digits" doesn't let the player type: "a", "b".`
- `hide must be True or False, not "yes".`

### Testing the question

Headless runs and Shift+F8 answer with `default`, or `"Test"` when there is none. The
question can't be `skippable` (the story needs the answer; E271).

### Changing the look and the words

The field uses `[theme.text_entry]` (its colors follow `[theme.button]` when not set) and the
panel `[theme.panel]`. The words are in `[words.plugin.ask_text]`:

```
[words.plugin.ask_text]
title = "Your answer"           # the save's description while asking
prompt = "Type your answer."    # the question when the line gives none
placeholder = "Type here"       # in the empty field
ok = "OK"
empty = "Type something first." # OK with an empty answer
hint = "Type, then press Enter. With a controller, press A for the keyboard."
```

The on-screen keyboard's keys and the field's notes are in `[words]`: `text_entry_space`,
`text_entry_delete`, `text_entry_done`, `text_entry_full`, `text_entry_refused`.

## Coded note

Coded note (`cipher_note`) comes with the engine. A letter is written in a code: under each
coded sign is a letter square, and the player types (or turns) the letter they think it
stands for. Every copy of that sign changes together. When the whole note reads right, it is
solved. Hints are tips the player learned in the story.

```
lock tip hana_code "Hana's notebook" in "Hana's code":
    "She always swapped letters, never shifted them. 'E is the commonest,' she wrote."
lock tip hana_letter "Hana's last letter"
default letter_read = False

label attic:
    minigame cipher_note message="MEET ME AT THE OLD LANTERN STALL." hints="Hana's code" tip="hana_letter" into letter_read
```

The result is `True` when the player solves the note and presses Done, `False` when they put
it away.

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `message` | (required) | text of 1 to 300 characters | The note, in plain words; `\n` starts a line |
| `kind` | `"letters"` | `"letters"`, `"shift"`, `"symbols"` | Letter swap, shift along the alphabet, or one symbol per letter |
| `alphabet` | `"ABCDEFGHIJKLMNOPQRSTUVWXYZ"` | 2 to 60 different characters, no spaces | The letters that are coded; anything else shows as written |
| `shift` | `3` | 1 to the alphabet's length − 1 | Shift: how many places each letter moves |
| `key` | `None` | the alphabet in another order | Letter swap: the coded letter for each alphabet letter. `None`: made from the message (the same every time) |
| `symbols` | Greek and Cyrillic letters | at least one per alphabet letter | Symbols: the sign for each alphabet letter, in order |
| `revealed` | `""` | letters of the alphabet | Letters that start solved (letter swap and symbols) |
| `hints` | `None` | a tip category | The Hints button shows the tips of this category the player holds |
| `tip` | `None` | a tip | Unlocked when the note is solved |

### Playing

- **Type** the letter under a sign, or **turn** it with Up and Down. Typing moves to the next
  sign with no letter. Backspace or Delete clears a sign. A letter can be on one sign only:
  typing it elsewhere takes it off the first.
- **Left and Right** move through the squares in reading order (past the last, to the
  buttons); **Page Up and Page Down** (or the bumpers) jump a line. Long notes scroll.
- **Shift:** the squares show the decoded note; turn the one square at the side ("A is
  written as …") until the note makes sense.
- **Hints** opens the codex with the tips of `hints`; with none held it reads "No hints yet".
- **Done** appears once the note is solved. **Put away** asks first, then ends with `False`.

### When the arguments are refused

The story stops at the line (E272), for example:

- `message has no letter of the alphabet, so there is nothing to decode.`
- `kind must be "letters", "shift" or "symbols", not "shfit". Did you mean "shift"?`
- `key must use each letter of the alphabet once, but Q is missing.`
- `hints names the tip category "Hanas code", but no tip is in it. Did you mean "Hana's code"?`
- `tip "hana_leter" isn't a declared tip. Did you mean "hana_letter"?`

In dev runs, W270 warns once when the game's fonts can't draw a character of the note.

### Testing the note

Headless runs, Shift+F8 and Skip Game solve it: `True`, with `tip` unlocked.

### Changing the look and the words

`[theme.plugin.cipher_note]`: `code.text_color` (the signs; default the panel text color),
`code.text_size`, `code_font`, `guess.text_color` (the typed letters; default the panel
heading color). The squares use `[theme.text_entry]`. `[words.plugin.cipher_note]`:
`title`, `hint`, `hint_shift`, `shift_label`, `hints`, `no_hints`, `put_away`, `confirm`,
`solved`, `done`.

## Computer terminal

Computer terminal (`terminal`) comes with the engine. The player types commands into an old
computer. You write the commands and their replies as a table; commands can wait for another
command, sit behind a password, unlock a tip, or end the session. `help` lists the commands
the player knows, and a **Commands** button lists them too, so a player with a controller
can finish without typing. Passwords learned from tips are offered at the password prompt.

```
lock tip hana_password "Hana's notebook" in "Hana":
    "On the last page, underlined twice: lantern."
lock tip hana_diary "Hana's diary"
default hacked = False

define library_pc = {
    "welcome": "KUROSAWA HIGH LIBRARY TERMINAL\nType help to see what you can do.",
    "prompt": "A:\\>",
    "unknown": "Bad command or file name.",
    "not_yet": "Access denied. Log in first.",
    "commands": [
        {"command": "dir", "reply": "DIARY.TXT    GRADES.DAT    README.TXT"},
        {"command": "type readme.txt", "also": ["read readme.txt"], "help": False,
         "reply": "Library hours: 8:00 to 17:00."},
        {"command": "login", "password": "lantern", "known_from": "hana_password",
         "reply": "Welcome back, H. Sato."},
        {"command": "type diary.txt", "after": "login", "unlock": "hana_diary", "help": "hana_password",
         "reply": "June 3. They'll find out about the grades. I have to delete them."},
        {"command": "del grades.dat", "after": "login", "help": False, "ends": "goal",
         "reply": "1 file deleted."},
    ],
    }

label start:
    minigame terminal data=library_pc screen="dark" into hacked
    if hacked:
        "The grades are gone."
```

In Studio: **Database ▸ Minigame data ▸ Terminals ▸ + New** makes a terminal to fill in, and
**Insert ▸ Minigame ▸ Computer terminal** puts it in the story.

### The table

| Key | Default | Meaning |
|---|---|---|
| `welcome` | `""` | Shown when the session starts (up to 2,000 characters; `\n` for new lines) |
| `prompt` | `">"` | Before each command (1 to 12 characters) |
| `unknown`, `not_yet` | the words `unknown`, `not_yet` | The reply to a line that isn't a command, and to a command whose `after` hasn't run |
| `commands` | (required) | 1 to 100 commands |

Each command:

| Key | Default | Meaning |
|---|---|---|
| `command` | (required) | What to type (1 to 40 characters). Capitals and extra spaces don't matter |
| `also` | `[]` | Up to 8 other ways to type it |
| `reply` | `""` | What it prints (up to 2,000 characters) |
| `help` | `True` | `True`: `help` lists it; `False`: secret; a tip's name: listed once the player has that tip |
| `after` | `None` | Another command that must run first |
| `password` | `None` | Asked first; capitals don't matter |
| `known_from` | `None` | The tip that teaches the password: Commands offers it at the password prompt |
| `unlock` | `None` | A tip unlocked when it runs |
| `ends` | `None` | `"goal"` or `"out"`: the session ends after the reply (Continue) |

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `data` | (required) | a table like the one above | The terminal |
| `result` | `"reached"` | `"reached"`, `"details"` | `True`/`False` (reached a `goal` command), or `{"reached": …, "ended_by": the command as written or None, "tried": the lines typed}` |
| `screen` | `"game"` | `"game"`, `"dark"` | The game's colors, or an amber monitor in any color scheme |
| `hide_passwords` | `True` | `True` or `False` | Dots instead of a typed password |

### Playing

- Type a command and press Enter. `help` lists what you know, `clear` empties the screen,
  `exit` (or Leave) asks before stepping away. A mistyped command gets "Did you mean: …"
  (never for a secret command). Up and Down bring back earlier commands.
- **Commands** lists what `help` lists; at a password prompt it offers "Password from: <tip>"
  when the player has the tip. A pick goes into the field; Enter runs it.
- The wheel, Page Up and Page Down, and the bumpers scroll the output.
- Passwords are never kept in `tried`, the history or the log.

### When the arguments are refused

The story stops at the line (E272), for example:

- `the terminal needs 1 to 100 commands, but it has 0.`
- `"open diary" is used twice (command 2, and command 5's also). Each command needs its own words.`
- `"help" is built into the terminal, so command 4 can't use it. Pick other words.`
- `"type diary.txt" works only after "logn", which isn't a command. Did you mean "login"?`
- `"a" works only after "b", and "b" only after "a", so neither can ever run.`
- `"login" names the tip "hana_pasword", which isn't a declared tip. Did you mean "hana_password"?`

In dev runs: W273 when the screen's font can't draw a character, W274 when `help` lists no
command at the start, W275 when a command uses the words of a renamed `help`, `clear` or
`exit` (the built-in wins).

### Testing the terminal

Headless runs, Shift+F8 and Skip Game run the first `"goal"` command: reached, with its tip.
With no goal command, not reached.

### Changing the look and the words

`[theme.plugin.terminal]`: `screen.fill_color`, `screen.fill_opacity`, `screen.border_color`,
`text_color`, `prompt_color`, `dim_color` (system lines), `text_font`, `text_size` (24),
`dark.fill_color`, `dark.text_color`, `dark.prompt_color`, `dark.dim_color`,
`dark.border_color` (the dark screen's amber colors), `key_sound`, `error_sound`.
`[words.plugin.terminal]` holds every word the terminal shows, including the built-ins'
`help`, `clear` and `exit`.

## Shop

The shop (`shop`) comes with the engine. The player buys items with the story's money: the
item marked `money` (see "Item counts and money" in [script-language.md](script-language.md)).
The panel shows the money the player holds at the top right ("Coins ×30", in the bag's own
word for money), then one row per item for sale: its name ("×2" when the player has some),
"3 left" or "Sold out" when only a few are for sale, and the price ("5 Coins", or "Free").

```
lock item coin "Coins" in "Purse" money
lock item tea "Jasmine Tea" count 0 to 9 price 5
lock item matches "Matches" count 0 to 99
lock item lantern "Red Lantern"
default bought = {}

define stall_stock = {
    "tea": None,
    "matches": [1, 10],
    "lantern": 20,
    }

label stall:
    unlock item coin 30
    minigame shop skippable stock=stall_stock name="Daichi's Stall" into bought
    if "lantern" in bought:
        daichi happy "Take good care of it."
```

### The stock

- Each key is an item's name (declared with `lock item`), in the order the shop lists them
  (1 to 40 items).
- Each value is the price, or a list of the price and how many are for sale:
  - `20`: 20 each, as many as the player likes.
  - `[1, 10]`: 1 each, 10 for sale on this visit (1 to 999).
  - `None` or `[None, 10]`: the item's own price, from `price 5` on its `lock item` line
    (Studio's **Price** field). An item with no price there needs one in the stock.
- A price is a whole number from 0 (free) to 999,999.
- The stock is counted again on each visit. To sell out for good, keep the table in a
  `default` and lower it from the result, or show a different table later.
- An item without `count` can be held once, so the shop sells one; a counted item stops at
  its most ("You can't carry more Jasmine Tea.").

### Arguments

| Argument | Default | Allowed | Meaning |
|---|---|---|---|
| `stock` | required | a stock table | What is for sale, and at what price |
| `money` | `None` (the item marked `money`) | an item's name | What the player pays with |
| `name` | `None` (the `title` word, "Shop") | text, 1 to 40 characters | The heading |

### Playing

The shop opens over the dimmed scene. The player picks a row and presses **Buy**: the price
is taken from the money and one item goes into the bag, and the panel shows the new money
and count at once. **Buy** can be pressed again to buy more. When a row can't be bought, its
price is dimmed and Buy says why: "Matches is sold out.", "Not enough Coins." or "You can't
carry more Jasmine Tea.". **Put back** undoes the last Buy (the item goes back and the money
comes back), so a slip costs nothing.

**Leave** (or Backspace, the right mouse button, or the gamepad's B button) ends the visit.
The result is what was bought, such as `{"tea": 2, "matches": 1}`, or `{}` for nothing. The
money and items change only then, together with the result, so a save or a rollback never
sees half a purchase. Going back to the shop's line opens the shop again as it was.

- Mouse: click a row to pick it, then **Buy**. Keyboard and gamepad: Up and Down pick a row,
  Enter (or A) goes to **Buy**.
- Nothing is timed or moves. **Skip Game** (with `skippable`) buys nothing: `{}`.

### When the arguments are refused

A problem stops the story with E272, `shop can't use these arguments:` and the reason:

| Reason | Fix |
|---|---|
| `stock must be a dictionary of items and prices, such as {"tea": 5, "matches": [1, 10]}, but it is a list.` | Write the stock in `{ }`, as above. |
| `stock has 0 items; a shop sells 1 to 40.` | Sell 1 to 40 items. |
| `"jasmine tea" in stock can't be an item name; write an item's name.` | Write the item's name as declared. |
| `"tea" in stock must be a price, such as 5, or a list of the price and how many, such as [5, 3], but it is text.` | Write a number, or `[price, how many]`. |
| `"tea" in stock costs -1; a price is a whole number from 0 to 999,999, or None for the item's own price.` | Use 0 to 999,999. |
| `"tea" in stock has 0 for sale; how many is a whole number from 1 to 999, or None for any number.` | Use 1 to 999, or `None`. |
| `stock names the item "tee", but there is no item named "tee". Did you mean "tea"?` | Spell the item as its `lock item` line does. |
| `the shop needs money, but no item is the money. …` | Add `money` to an item's line, or write `money="coin"`. |
| `"coin" is the money, so the shop can't sell it.` | Take the money out of the stock. |
| `"matches" has no price: write one in stock, e.g. "matches": 5, or add price 5 to its lock item line.` | Give it a price. |

### Testing the shop

A headless run, Shift+F8 in a test run, and Skip Game buy nothing (`{}`). To test a
purchase, give the result and the changes with `finish`.

### Changing the look and the words

The shop draws with the game's `panel`, `list` and `button` colors, so it fits every color
scheme. `[theme.plugin.shop]` has `buy_sound` (none). `{item}` is an item's name, `{money}`
the money word and `{n}` a number. A price of 1 drops the money word's plural ending ("1 Coin",
"1 Ruby"; "Gold" stays "Gold"):

```toml
[words.plugin.shop]
title = "Shop"
hint = "Choose something, then Buy."
buy = "Buy"
put_back = "Put back"
leave = "Leave"
price = "{n} {money}"
free = "Free"
left = "{n} left"
sold_out = "Sold out"
gone = "{item} is sold out."
bought = "Bought {item}."
returned = "Put {item} back."
short = "Not enough {money}."
full = "You can't carry more {item}."
enough = "That's all for this visit."
```

## Writing a minigame

A minigame of your own is a **plugin**: a Python file in your game's `game/minigames/`
folder. When the game starts, the engine loads every plugin there, and each one adds a
minigame name that `minigame` lines can use. This section builds the example game's lantern
memory game, a board of face-down lanterns where the player turns over two at a time and
tries to find the pairs. It is about 80 lines long, and you can copy it as the start of
your own.

### What a minigame does

Every minigame follows the same simple life:

1. The story reaches the `minigame` line. The engine checks the arguments, then makes a
   new copy of your minigame class and calls its `start` method.
2. While the player plays, the engine calls your methods: `handle_event` for each key,
   click, or button press; `update` once a frame; `draw` once a frame. Buttons you put on
   the screen are drawn and pressed for you, so a simple game needs few of these.
3. When the game is over, your code calls `ctx.finish(result)`. The engine fades back to
   the story, puts `result` into the `into` variable, and makes any meter or codex changes
   you asked for.

`ctx` is the **context**: the one object your minigame uses to talk to the engine. It holds
the arguments, the story's random numbers, the meters and codex, and calls for the heading,
the hint bar, sounds, and pictures. The reference below lists all of it.

### The complete plugin

This is `game/minigames/lantern_memory.py`, the whole file:

```python
"""Lantern memory: turn over two lanterns at a time and find the pairs.

The example game's minigame plugin, and the one docs/minigames.md walks through
("Writing a minigame"). In the script:

    minigame lantern_memory pairs=6 into turns

The result is the number of turns the player took. Clearing the board also gives Hana
one point.
"""

from engine.minigames.api import Arg, Minigame, Outcome, add_points, register
from engine.ui.focus import Box, FocusGroup
from engine.ui.widgets import Button

PICTURES = ["Moon", "Crane", "Fish", "Star", "Bell", "Kite", "Fan", "Drum"]
COLUMNS = 4
CARD_W, CARD_H, GAP = 200, 110, 24


@register
class LanternMemory(Minigame):
    name = "lantern_memory"
    title = "Lantern Memory"
    args = {"pairs": Arg(), "hints": Arg(default=False)}
    test_outcome = Outcome(9, (add_points("hana", 1),))
    words = {"hint": "Find the matching lanterns."}

    def check_args(self, args):
        pairs = args["pairs"]
        if type(pairs) is not int or not 2 <= pairs <= len(PICTURES):
            return f"pairs must be a whole number from 2 to {len(PICTURES)}"
        if type(args["hints"]) is not bool:
            return "hints must be True or False"
        return None

    def start(self, ctx):
        self.ctx = ctx
        self.cards = ctx.random.shuffle(PICTURES[:ctx.args["pairs"]] * 2)
        self.up = []                  # the one or two cards turned face up this turn
        self.found = set()            # the cards already matched
        self.turns = 0
        self.buttons = [Button(lambda i=i: self.face(i), lambda i=i: self.pick(i))
                        for i in range(len(self.cards))]
        self.layout(ctx.area)
        ctx.scope.set_groups([FocusGroup(self.buttons)])
        ctx.scope.set_default(self.buttons[0])
        ctx.heading(True)
        self.show_hint()

    def layout(self, area):
        rows = (len(self.cards) + COLUMNS - 1) // COLUMNS
        left = area.x + (area.w - (COLUMNS * CARD_W + (COLUMNS - 1) * GAP)) / 2
        top = area.y + (area.h - (rows * CARD_H + (rows - 1) * GAP)) / 2
        for i, button in enumerate(self.buttons):
            row, column = divmod(i, COLUMNS)
            button.box = Box(left + column * (CARD_W + GAP), top + row * (CARD_H + GAP),
                             CARD_W, CARD_H)

    def face(self, i):
        return self.cards[i] if i in self.found or i in self.up else "?"

    def pick(self, i):
        if i in self.found or i in self.up:
            return
        if len(self.up) == 2:         # the last two didn't match: turn them back down
            self.up = []
        self.up.append(i)
        if len(self.up) == 2:
            self.turns += 1
            first, second = self.up
            if self.cards[first] == self.cards[second]:
                self.found.update(self.up)
                self.up = []
        if len(self.found) == len(self.cards):
            self.ctx.points.add("hana", 1)
            self.ctx.finish(self.turns)
            return
        self.show_hint()

    def show_hint(self):
        hint = self.ctx.words.mine("hint")
        if self.ctx.args["hints"]:
            left = (len(self.cards) - len(self.found)) // 2
            hint += f" Pairs left: {left}. Turns: {self.turns}."
        self.ctx.hint(hint)
```

The rest of this section goes through it a piece at a time.

### Step 1: the file and the imports

Make the folder `game/minigames/` (lower case) next to `game/script/`, and save the plugin
there as a `.py` file. The file's name doesn't matter to the story; the name inside it does.

The first lines bring in what the plugin uses: from `engine.minigames.api`, the `Minigame`
class to build on, `Arg` and `Outcome` for the declarations, `add_points` for the test
outcome, and `register`; from F10's widget kit, `Button`, `Box` (a rectangle: x, y, width,
height), and `FocusGroup` (buttons the arrow keys move between). `PICTURES`, `COLUMNS`, and
the card sizes are plain Python values the game uses.

### Step 2: the declarations

```python
@register
class LanternMemory(Minigame):
    name = "lantern_memory"
    title = "Lantern Memory"
    args = {"pairs": Arg(), "hints": Arg(default=False)}
    test_outcome = Outcome(9, (add_points("hana", 1),))
    words = {"hint": "Find the matching lanterns."}
```

`@register` on the line above the class adds the minigame to the game. Then the class says
what it is:

- **`name`** is what `minigame` lines write: lower-case letters, digits, and `_`.
- **`title`** is shown as the heading and as a save's description.
- **`args`** lists the arguments. `Arg()` is required: a line without `pairs=` gets an
  error when the game starts. `Arg(default=False)` is optional, with that default.
- **`test_outcome`** is the result a headless run and Shift+F8 use: 9 turns, and 1 point
  for Hana. Without one, every headless run must give a `finish` input.
- **`words`** are the texts the game shows, so an author can change them in
  `config.toml` without touching the plugin (see "Words and look" below).

A `skipped_outcome` (not used here) is what Skip Game gives; a minigame without one can't be
`skippable`.

### Step 3: checking the arguments

```python
    def check_args(self, args):
        pairs = args["pairs"]
        if type(pairs) is not int or not 2 <= pairs <= len(PICTURES):
            return f"pairs must be a whole number from 2 to {len(PICTURES)}"
        if type(args["hints"]) is not bool:
            return "hints must be True or False"
        return None
```

`check_args` runs before the game starts, with every argument (defaults filled in). Return
`None` when they are fine, or a short reason when they aren't: the story stops with the
reason at the `minigame` line, `lantern_memory can't use pairs=40: …`. Check every argument
here, because **`ctx.args` can come from a save** (see "Rules every plugin follows").
`check_args` must have **no side effects**: it only looks at `args` and returns. Don't
change `args`, write files, play sounds, or keep anything for later; the engine may call it
more than once, and on a copy of your class that never starts.

### Step 4: starting

```python
    def start(self, ctx):
        self.ctx = ctx
        self.cards = ctx.random.shuffle(PICTURES[:ctx.args["pairs"]] * 2)
```

`start` runs once, when the game opens. It keeps `ctx` for later and deals the cards: two of
each of the first `pairs` pictures, shuffled. Use **`ctx.random`** for anything random. It
is the story's own random source (the same as `dice` in the script), so a save, a rollback,
and a test run all deal the same board. Python's `random` module would deal a new one each
time.

Then it makes one F10 `Button` per card. A button takes two functions: one that gives its
label (here `face(i)`: the picture, or `?` while the card is face down), and one that runs
when it is pressed (`pick(i)`). The `lambda i=i:` form makes each button remember its own
card number. `ctx.scope.set_groups` puts the buttons in the game's focus scope: the engine
draws them, moves the focus between them with the arrow keys or a gamepad, and presses them
with Enter, the gamepad's A button, or a click. `set_default` picks the card focused first.
Last, `ctx.heading(True)` shows the title above the board, and `show_hint` fills the hint
bar under it.

### Step 5: laying out the board

```python
    def layout(self, area):
        rows = (len(self.cards) + COLUMNS - 1) // COLUMNS
        left = area.x + (area.w - (COLUMNS * CARD_W + (COLUMNS - 1) * GAP)) / 2
        top = area.y + (area.h - (rows * CARD_H + (rows - 1) * GAP)) / 2
```

`area` is the part of the screen the game may use (a `Box` on the 1280 × 720 screen,
already leaving room for the heading and hint bar). `layout` places each button's `box` in a
grid, centred in the area. `start` calls it once, and the engine calls it again whenever
the area changes, for example when the player picks a bigger text size.

### Step 6: playing and finishing

`pick(i)` is the whole game. It ignores a card that is already up or found. When two cards
are up and didn't match, the next pick turns them back down first. When the second card of
a turn goes up, the turn counts, and a matching pair goes into `found`. When every card is
found, the game asks for 1 point for Hana with `ctx.points.add("hana", 1)` and ends with
**`ctx.finish(self.turns)`**: the number of turns is the result.

`ctx.points.add` doesn't change the meter at once: the change waits and happens together
with the result, as the story goes on. If the player leaves the game (loads a save, goes
back to the title), nothing happens at all.

The plugin never draws the cards itself: buttons draw themselves with the game's button look.
A plugin that wants its own pictures defines `draw(self, canvas)` (see the reference).

### Step 7: using it in the story

```
default turns = 0

label lantern_stall:
    minigame lantern_memory pairs=6 into turns
    if turns <= 10:
        "\"Only {var=turns} turns? Sharp eyes,\" the stall keeper said."
```

Run the game in dev mode and play it. To check the arguments, try `pairs=40`: the game stops
at that line with the reason from `check_args`. A mistake in the plugin's Python stops the
game at launch with the plugin's file and line, `minigames/lantern_memory.py, line 30: …`,
and the log (`game/logs/`) has the details.

### Step 8: testing it

- **Shift+F8** (dev runs) ends the game at once with its test outcome, so you can test the
  story after it without playing.
- A **headless run** uses the test outcome too, or a `finish` input:
  `finish 12` for a slow player, `finish 6; points hana += 1` for a perfect one.
- Play it once with only the keyboard and once with only a gamepad: every button should be
  reachable, and the focus always visible.

### Words and look

Every text a player sees should come from `words`, read with `ctx.words.mine("hint")`. An
author can then change it in `config.toml`, including the title:

```toml
[words.plugin.lantern_memory]
title = "Lantern Pairs"
hint = "Find the two lanterns that match."
```

A plugin can also declare **tokens**, look values an author can change, such as
`tokens = {"card.back_color": "#203040"}`. Read one with `ctx.theme.mine("card.back_color")`;
an author sets it as:

```toml
[theme.plugin.lantern_memory.card]
back_color = "#402030"
```

`ctx.theme.get("button.fill_color")` reads the game's own theme, so a plugin can match it.

### Rules every plugin follows

Plugins are powerful, so a few rules keep players and their saves safe:

- **A plugin is a program.** It runs with the same rights as the game itself and can do
  anything Python can. Only put plugins you wrote, or whose author you trust, in
  `game/minigames/`, and treat a plugin from someone else like any program you download.
- **`ctx.args` can come from a save.** Save files can be edited, so a player (or a damaged
  save) can start your minigame with any arguments its declaration allows. Check them all
  in `check_args`, which has no side effects, and never trust them anywhere else.
- **Never build file paths or `eval` from arguments.** Don't turn an argument into a file
  name, a folder, a module to import, or code to run. Use arguments to choose between
  values your plugin already has, like `PICTURES[:pairs]` above. For pictures and sounds, use
  `ctx.image`, `ctx.gui_image`, and `ctx.play_sound`, which only read files in the game
  folder.
- **Use `ctx.log`** for messages to yourself: `ctx.log.info("dealt %d cards", n)`. It goes
  to the game's log under the area `plugin`, with private paths hidden. Don't `print` or
  write your own log files.
- **Keep the player's computer out of results, titles, and logs.** Never put the player's
  user name, computer name, folders, or anything else about their computer in a result, a
  title, a word, or a log message. Results are saved with the game, and logs are often
  shared when someone reports a bug.
- **Make no API calls from your own threads.** Everything on `ctx`, and every object it gives
  you, works only on the game's main thread; a call from a thread of your own stops the
  game with an error. Do your work in `start`, `handle_event`, `update`, and `draw`.
- **Honour `reduce_motion`.** If your game moves, shakes, or flashes, check
  `ctx.settings.reduce_motion` in `start` and again in `settings_changed`: when it is
  `True`, cut instead of animating.
- **Honour Timing assist.** If your game has a time limit or a beat, get every limit from
  `ctx.settings.timed(seconds)` and never pick your own factor: it gives `seconds`, twice
  that, or `None` when the player chose No time limits. Under `None`, wait for the player
  and never fail on time. Declare `api = "1.3"` (see "API 1.3 notes").
- **Use relative imports in packages.** A bigger plugin can be a folder with an
  `__init__.py` (a package), such as `game/minigames/night_sky/`. Its files import each other
  with relative imports (`from . import rules`, `from .board import Board`), never as
  `import rules`, which would look outside your plugin.

Two more habits keep the game smooth: do slow work (loading pictures, building big lists) in
`start`, not in `draw`; and keep `update` and `draw` short. In dev runs the engine warns
when one frame takes over 8 ms.

### API 1.3 notes (Timing assist)

Minigame API 1.3 adds the player's **Timing assist** setting (Settings ▸ Display) to
`ctx.settings`:

- **Declare `api = "1.3"`** to use `ctx.settings.timing_assist` and `ctx.settings.timed`. An
  older engine has neither, and refuses a 1.3 plugin with E278 instead of failing later.
- `ctx.settings.timing_assist` is `"normal"`, `"slower"`, or `"off"` (No time limits).
  `ctx.settings.timed(seconds)` turns a time limit into the player's: `timed(2.0)` is `2.0`,
  `4.0`, or `None`.
- **Under "off", wait for the player and never auto-fail.** Heartbeat is the example: its
  ring closes at the normal pace, then waits on the circle until the player presses.
- **A change arrives through `settings_changed`.** Your game decides when it applies, for
  example from the next beat or the next round, so a running countdown never jumps.

### API 1.4 notes (text fields)

Minigame API 1.4 adds **`api.TextField`**, the engine's one-line text field (the one
`ask_text` uses), so your game can ask the player to type: a name, a password, a letter.

- **Declare `api = "1.4"`** to use it. An older engine refuses a 1.4 plugin with E278.
- **Put it in `ctx.scope`** like a button: `ctx.scope.set_groups([FocusGroup([field, ok])])`,
  give it a `box` in `layout`, and `ctx.scope.set_default(field)` to start with it focused.
- **Arguments** (all optional): `text` (the starting text), `max_length` (1 to 200
  characters, default 40), `allowed` (`"any"`, `"name"`, `"letters"`, `"digits"`,
  `"letters_digits"`, or your own string of characters, such as `"ABCDEF"`), `case`
  (`"upper"` or `"lower"`), `mask` (dots instead of letters), `placeholder` (shown while
  it is empty), `cell=True` (one letter in a square: typing replaces it, Up and Down turn it
  through `allowed`; needs your own `allowed` string), `bare=True` (no box: a prompt line),
  `keep_keyboard=True` (the on-screen keyboard stays open after Enter), `on_change(text)`
  and `on_submit(text)` (Enter, or the keyboard's Done), `enabled`, and, for a bare field,
  `font`, `text_size`, `text_color`, `caret_color`.
- **Read and set it** with `field.text` and `field.set_text("…")`. `field.last_edit` says
  what the player did last (`"type"`, `"paste"`, `"delete"`, `"turn"`, `"move"`).
- **The engine does the typing.** Under API 1.4 the engine owns the keyboard's text: text
  input is on only while a `TextField` is focused, and your `handle_event` never sees
  `TEXTINPUT` or the field's editing keys (Backspace, Delete, Left, Right, Home, End,
  Enter). Japanese and other input methods, paste (Ctrl+V), length and character limits
  all work. Up, Down, Tab and the mouse still reach your game, so Up and Down can move
  between fields or recall history.
- **Gamepads.** A on a focused field opens the engine's on-screen keyboard. It is the
  engine's, drawn over your game; it never joins `ctx.scope`, and your game keeps running
  under it. B closes it and keeps the text.
- **Esc still opens the game menu**, and the typed text is still there afterwards.
  Backspace on a focused field never opens the menu or goes back.
- **Typed text counts as playing**, so the player can't step back past the minigame after
  typing (as with any used input).
- **An older plugin** (API 1.3 or below) is unchanged: text input stays on while it runs,
  and it reads `TEXTINPUT` in `handle_event` as before.
- **Never log typed text** or show it anywhere but your own screen; finish with it as the
  result (`ctx.finish(field.text)`) if the story needs it.

### API 1.5 notes (item counts)

Minigame API 1.5 lets a game read and change **how many** of an item the player holds (items
declared with `count`; see "Item counts and money" in the script language). The shop uses it.

- **Declare `api = "1.5"`.** An older engine refuses a 1.5 plugin with E278.
- **Read:** `ctx.codex.count("coin")` is how many the player holds now, this game's own
  changes included (0 for none). `ctx.codex.most("coin")` is the most they can hold (1 for an
  item without `count`). `ctx.codex.money_word()` is the bag's word for the money ("Coins").
  `ctx.story.money` names the item marked `money` (or `None`), and `ctx.story.prices` lists
  each item's `price` as `(name, price)` pairs.
- **Change:** `ctx.codex.give("coin", 5)` and `ctx.codex.take("coin", 5)`, and in an outcome
  `api.give("coin", 5)` and `api.take("coin", 5)`. The number is a whole number from 1 to
  999,999; leaving it out means 1, so older code is unchanged. Giving stops at the item's
  most and taking stops at none, exactly as `unlock item coin 5` and `lock item coin 5` do.
- **The usual rules hold.** The name must be a declared item (E253), the number must be in
  range (E275), a game makes at most 1,000 changes, and nothing reaches the story until the
  game finishes. Then the changes are made in order through the story's own rules, so a
  save, a load, a rollback and Skip Game stay exact.

### Achievement hook

Achievements (docs/script-language.md, section 7, "lock achievement") are kept on the
player's computer and need no code. A game sold on a store such as Steam may also want each
achievement told to the store. That is the **achievement hook**: a small plugin, written by
the game's programmer, that the engine calls when achievements change. The engine itself
never uses the network; your hook talks to the store's own library, if you add one.

Put the hook in a file in `game/minigames/`, like a minigame plugin (a file that only
registers a hook is fine):

```python
from engine.minigames import api


class StoreHook:
    def started(self, unlocked):
        # Once per launch, after the player's progress is read: the names already earned,
        # in the order of their lock achievement lines. Optional.
        for name in unlocked:
            store_library.set_achievement(name)

    def unlocked(self, name):
        # Each new achievement, right after its notice shows.
        store_library.set_achievement(name)


api.register_achievement_hook(StoreHook())
```

- **`api.register_achievement_hook(hook)`** (minigame API 1.2) takes an object, not a
  class, with an **`unlocked(name)`** method and, if you like, **`started(unlocked)`**. A game
  has one hook.
- `name` is the achievement's script name (`first_steps`), never its title.
- The engine calls the hook only in a game window, never in headless runs, on the game's
  main thread, between frames.
- **Keep each call short** (well under 0.1 s): the game waits while it runs. A slower call
  is logged once (W225). If a call raises an error, or runs so long that the engine stops
  it, the hook is turned off until the game restarts (W225); achievements still work and are
  still kept on the player's computer.
- Achievements earned while players watch a scene again (scene replays) are kept, and the
  hook is told about them like any other.
- Settings' "delete persistent data" locks every achievement again; the hook isn't told
  (stores keep what they recorded).
- The hook is trusted code, like any plugin: the rules in "Rules every plugin follows" apply.

### Saves

A save made during a minigame holds the minigame's name, its arguments, and its random seed,
not the board itself. Loading it starts the game again from the beginning, with the same
cards. Because players can edit save files, a save can restart any minigame with any
arguments its plugin accepts. That is why `check_args` must check everything, and why
changing a plugin's arguments later needs care: if a new version refuses arguments an old
save holds, that save goes back to the nearest point it can.

## Plugin reference

### Declarations

| Class attribute | Meaning |
|---|---|
| `name` | The minigame's name in scripts: lower-case letters, digits, `_`. Required. |
| `title` | The heading and save description; `[words.plugin.<name>] title` wins. Default: the name. |
| `api` | The minigame API version the plugin was written for: `"1.0"` (default) up to `"1.5"`. |
| `args` | `{"name": Arg(), "other": Arg(default=value)}`. Names start with a letter. |
| `test_outcome` | `Outcome(result, changes)` for headless runs and Shift+F8, or `None`. |
| `skipped_outcome` | `Outcome(…)` for Skip Game, or `None` (then the game can't be `skippable`). |
| `over_stage` | `True` draws the game over the dimmed story scene instead of its own backdrop. |
| `tokens` | `{"element.property": default}`: look values authors set in `[theme.plugin.<name>]`. |
| `words` | `{"key": "text"}`: texts authors set in `[words.plugin.<name>]`. |

`Outcome(result, changes)`: `result` is a plain value (text, a number, `True`, `False`,
`None`, a list, or a dictionary with text keys); `changes` is a tuple of `add_points(name,
n)`, `set_points(name, n)`, `give(item)`, `take(item)` (API 1.5: `give(item, n)`,
`take(item, n)`), and `unlock_tip(tip)`.

### Methods the engine calls

| Method | When |
|---|---|
| `check_args(self, args)` | Before the game starts and when a save loads. Return `None` or a reason. No side effects. |
| `check_story(self, args, story)` | API 1.1: after `check_args`; refuse names the story doesn't declare. |
| `outcome_for(self, kind, args, story)` | API 1.1: a test or skipped outcome worked out from the arguments. |
| `start(self, ctx)` | Once, when the game opens. |
| `handle_event(self, ev)` | For each input, before the buttons get it. `ev.nav` is the move (`Nav.UP`, `Nav.ACTIVATE`, `Nav.BACK`, …) or `None`; `ev.ui` is the raw event. Return `True` if you used it (the buttons then don't see it), `False` to pass it on. |
| `update(self, dt)` | Once a frame; `dt` is the seconds since the last one. Not called while the game menu is open. |
| `draw(self, canvas)` | Once a frame, before the buttons. `canvas.fill(color, (x, y, w, h))`, `canvas.draw_text(text, font, color, (x, y), anchor="center")`, `canvas.draw_image(image, (x, y))`. |
| `layout(self, area)` | When the play area changes. |
| `settings_changed(self, s)` | When the player changes a setting; `s` is the new `ctx.settings`. |

### The context (`ctx`)

| Member | What it is |
|---|---|
| `ctx.args` | The checked arguments, a dictionary (yours to read; a copy). |
| `ctx.random` | The story's random source: `roll(a, b)`, `pick(list)`, `decimal()`, `shuffle(list)` (returns a new list). |
| `ctx.points` | Meters: `get(name)`, `names()`, `highest()`, and `add(name, n)`, `set(name, n)` (made when the game finishes). |
| `ctx.codex` | `items()`, `tips()`, `has(kind, name)`, `title(name)`, API 1.5's `count(item)`, `most(item)`, `money_word()`, and `give(item, n=1)`, `take(item, n=1)`, `unlock_tip(tip)` (made when the game finishes). |
| `ctx.story` | The story's declared names: `meters`, `items`, `tips`, `item_categories`, `tip_categories`, and (API 1.5) `money` and `prices`. |
| `ctx.settings` | `text_scale`, `reduce_motion`, the volumes, and (API 1.3) `timing_assist` (`"normal"`, `"slower"`, `"off"`) with `timed(seconds)`: the player's time limit, or `None` for no limit. |
| `ctx.area` | The play area, a `Box`. |
| `ctx.scope` | The focus scope: `set_groups([FocusGroup(buttons)])`, `set_default(button)`, `focused`. |
| `ctx.painter` | F10's painter, for drawing frames in the game's look. |
| `ctx.theme`, `ctx.words` | `mine(key)` reads your own token or word; `get(key)` the game's. |
| `ctx.dev`, `ctx.log` | `True` in dev runs; the plugin's logger. |
| `ctx.image(name)`, `ctx.gui_image(file)` | A story image (`"hana happy"`) or a picture file in the game folder. |
| `ctx.font(file, size)` | A font; `None` as the file is the game's UI font. |
| `ctx.play_sound(file, volume=100)`, `ctx.play_ui(token)`, `ctx.music()` | Sounds and the game's music while it runs. |
| `ctx.heading(on, text=None)`, `ctx.hint(text)` | The heading above the game and the hint bar under it. |
| `ctx.cue_point((x, y))` | Where the rollback cue shows. |
| `ctx.confirm(word, on_yes, on_no=None)` | A Yes/No question, its text from your `words`. |
| `ctx.codex_view(filter=…, pick=…)` | The codex's item list inside the game (as the cross-examination uses it). |
| `ctx.finish(result)` | Ends the game with `result`. |

### Errors and warnings

| Code | When | What to do |
|---|---|---|
| E270 | A `minigame` line names no minigame, or one that isn't loaded, or a bad `into`. | Fix the name, or the `into` variable (it needs a `default`). |
| E271 | An argument the minigame doesn't have, one missing, or written without `=`. | Use the plugin's argument names, `name=value`. |
| E272 | `check_args` refused the arguments, or a value can't be saved. | Fix the line, or the plugin's check. |
| E273 | A plugin has a Python mistake, stopped while loading, or declares something wrong; for the achievement hook: `register_achievement_hook needs an object with an unlocked(name) method.` / `register_achievement_hook was called twice; a game has one achievement hook.` | Fix the file and line the message names; register one hook object. |
| E274 | Two plugins use the same name. | Rename one. |
| E275 | The plugin stopped with an error while running. | Fix the file and line; the log has the details. |
| E276 | `ctx.finish` gave a result that can't be saved. | Finish with text, a number, a list, or a dictionary. |
| E277 | The plugin ran 5 seconds without returning: probably a loop. | Check any `while` loop at that line. |
| E278 | The plugin needs a newer minigame API than this engine has. | Update the engine, or use an older plugin. |
| E279 | A headless run reached a minigame with no test outcome and no `finish`. | Add `finish …` to the inputs, or a `test_outcome`. |
| W160 | A plugin replaces a minigame that comes with the engine (dev). | Rename yours to keep both. |
| W161 | A file in `game/minigames/` registers nothing (dev). | Register a minigame, or move the file into a plugin's folder. |
| W162 | One frame of a minigame took over 8 ms (dev). | Draw less each frame. |
| W163 | A plugin file is a link, not a real file (dev). | Put the file itself in `game/minigames/`. |
| W164 | The folder is named `Minigames`, not `minigames` (dev). | Rename it in lower case. |
| W165 | A plugin line has hidden text-direction characters (dev). | Delete them. |
| W225 | The achievement hook failed (`the achievement platform hook failed in unlocked (RuntimeError), so it is off until the game restarts. Achievements are still kept on this computer.`), or a call took over 0.1 s (`the achievement platform hook took 0.4 s in unlocked; keep hook calls under 0.1 s so the game doesn't stall.`, once). | Fix the hook, or make its calls shorter. |
