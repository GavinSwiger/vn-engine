# Minigames

A minigame is a small game that runs inside the story: the story stops at a `minigame` line,
the player plays, and the story goes on with the result. Some minigames come with the engine;
you can also write your own in Python.

> **This guide is being written in parts.** It starts with three minigames that come with the
> engine: the poem game (F24), the cross-examination (F25), and the phone chat (F26). The
> `minigame` line itself, the Skip Game and Shift+F8 rules, and how to write your own
> minigame plugin are added with F23's last steps.

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
moves between replies, picks one, or scrolls; after that, the chat holds its place. The chat
adds no lines to History.

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
