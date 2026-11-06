# The .vns script language

This is the reference for writing a story for vn-engine. You don't need to know how to
program. A story is plain text: mostly dialogue, plus a few English words that say where
scenes start and where the story goes next.
To write a scene and preview it in a window, see [The scene editor](scene-editor.md).

Owned by `vn-narrative-designer`. Sections marked **(proposed, …)** are planned, not yet
approved, and may change.
The full rules are in `specs/F02-script-parser/02-script.md`,
`specs/F03-interpreter-gamestate/02-script.md`, `specs/F04-stage-sprites/02-script.md`,
`specs/F05-adv-textbox/02-script.md`, `specs/F07-choice-menus/01-design.md` (menus),
`specs/F08-audio/02-script.md`, and `specs/F09-transitions/01-design.md` (transitions).

**Contents:** 1. A first story · 2. Files and includes · 3. Writing text · 4. Comments ·
5. Indentation · 6. Names · 7. Statements · 8. Characters · 9. Story variables ·
10. Random numbers · 11. Python modules · 12. Backgrounds and sprites · 13. Music and sound ·
14. Dialogue text · 15. Menus and theme · 16. Transitions and effects · 17. Saves ·
18. Rollback · 19. Reserved words · 20. Coming later · 21. Common errors ·
22. Run-time errors

---

## 1. A first story
**(proposed, F02)**

`game/script/main.vns`:
```
# The story always starts in main.vns, at label start.
define hana = Character("Hana")

label start:
    "The festival lanterns were already lit when I reached the river."
    hana "You came! I didn't think you would."
```

`define` creates a character: `hana` is what you type, `"Hana"` is what the player sees.
`label start:` is where the story begins; the indented lines under it are the scene. Text
in quotes alone is **narration**; a name before it makes it **dialogue**.

---

## 2. Files and includes
**(proposed, F02)**

Story files end in `.vns` and live in `game/script/` (subfolders are fine). The story
starts from `script/main.vns`. Only `main.vns` and the files it **includes** are part of
the game, so a backup like `chapter1 - Copy.vns` can't break it.

```
include "chapter1.vns"
include "routes/hana.vns"
```

- Paths start inside the `script` folder, use `/`, and must match capitals exactly.
- Includes go at the top level of a file (no indentation), usually at the top.
- Order doesn't matter, and files can include each other.
- Labels in any included file can be reached from every file.

---

## 3. Writing text
**(proposed, F02)**

Save files as **UTF-8** (the default in most editors). Any line endings work. Text can be
in any language, with any punctuation or emoji.

**Quotes.** Text goes between straight double quotes `"like this"`. Apostrophes and curly
quotes **inside** need nothing special. The quotes **around** the text must be straight;
word processors often turn them curly, and the engine will tell you.

```
    hana "I'm sure she said “tomorrow.”"
```

**Special characters.**

| To show | Write |
|---|---|
| `"` | `\"` |
| `\` | `\\` |
| a new line in the text box | `\n` |
| `{` | `{{` |

```
    daichi "She's been saying \"just one more\" since six o'clock."
```

Any other backslash is an error. `{ }` hold text tags such as `{b}` for bold; see
[Dialogue text](#14-dialogue-text). `[ ]` are always plain text.

**Long lines.** Leave the quote open and indent the next lines **more**. Line breaks
become single spaces. End a line with `\` to join with no space (for Japanese or Chinese).

```
    "Paper lanterns drifted past us one by one, each carrying
        somebody's wish downstream."
    hana "提灯が川を\
        流れていく。"
```

---

## 4. Comments
**(proposed, F02)**

`#` starts a comment that runs to the end of the line. Inside quotes, `#` is just text.

```
    hana "Ready?"   # a note
    # hana "A line I'm not sure about yet."
    # TODO: rewrite the bridge scene
```

Comment lines can be at any indentation. Comments starting with `TODO` are listed in the
log when you test the game.

---

## 5. Indentation
**(proposed, F02)**

Lines ending in `:` open a **block**; its lines are indented under it.

```
label riverbank:
    if bought_lantern:
        hana "You actually bought one!"
    else:
        hana "Not even a small one?"
    jump bridge
```

- Use spaces or tabs, but only one kind per file (continued lines too).
- Any width works; every line of a block lines up.
- Blank lines and comment lines never matter.
- A block needs at least one real line. For an unwritten scene, write `return`.

---

## 6. Names
**(proposed, F02)**

Label and `define` names use letters (any language), digits, and `_`, and can't start with
a digit: `hana`, `chapter_2`, `始まり`. Capitals matter. A name can't be a reserved word
(section 19) in any capitals, a Python word (`True`, `None`, `and`, `for`, `class`, …),
`Character`, `persistent`, `engine`, or `narrator`, and can't start with `_`.

The same rules apply to `default` names and to names a `$` line sets.
`dice`, `module`, `points`, and `codex` are engine names too.

---

## 7. Statements

### label
**(proposed, F02)**

```
label bridge:
    "The bridge was crowded with people waiting for the fireworks."
    jump fireworks
```

Names a scene. Top level only; each name once in the whole game. The game needs a label
`start`. When a label's lines run out, it acts like `return` (it never runs into the next
label), so end scenes with `jump`.

### jump
**(proposed, F02)**

```
    jump bridge
```

Continues at a label and doesn't come back. Every `jump` is checked when the game starts.

### call and return
**(proposed, F02)**

```
label riverbank:
    call lantern_stall
    hana "So? What did you wish for?"

label lantern_stall:
    "The stall keeper held up a lantern the size of my fist."
    return
```

`call` visits a label and comes back to the next line when it reaches `return` (or its
last line). A `return` with no `call` ends the story.

### Dialogue and narration
**(proposed, F02)**

```
    "The festival lanterns were already lit."
    hana "You came!"
    hana surprised "You came!"
```

Dialogue is a character's name, then text in quotes. The character must be created with
`define` somewhere in the game. Up to 4 words between the name and the text (like
`surprised`) change the character's expression on that line; see
[Expressions on dialogue lines](#expressions-on-dialogue-lines). Tags inside the quotes
style words and time pauses; see [Dialogue text](#14-dialogue-text).

### define
**(proposed, F02)**

```
define hana = Character("Hana", color="#e8a0b4")
define wish_cost = 300
```

Sets a name once for the whole game, before the story starts. Top level only; each name
once. A `define` can use other defined names (in any file) but not itself. The part after
`=` is Python. The story can't change a defined name; for a value the story changes, use
`default`.

### default

```
default trust = 0
default hana_name = "???"
default visited = []
```

Declares a **story variable** and its starting value. Top level only; each name once, and
not also a `define`. The value is set when a new game starts. It is also set when a player
loads a save made before you added the `default`, so adding variables in a patch never
breaks old saves. It never replaces a value the game already has. Defaults can use defined
names and other defaults, in any file. Then change the variable with `$`:

```
    $ trust += 1
```

**Use a `default` for every variable your story changes.** A variable created only by a
`$` line doesn't exist in saves made before that line ran.

> **Warning:** `default` values are Python too, like `$` lines and `define` values (see
> below), and run whenever a new game starts or a save is loaded.

### $ (one line of Python)
**(proposed, F02)**

> **Warning:** `$` lines, `if`/`elif` conditions, and `define` values all run real Python,
> with the same access to the player's computer as any program. `define` values run at
> **every launch, before the title screen**. A shared `.vns` file or mod is a program,
> even if it has no `$` lines. Players should only run scripts from people they trust.

```
    $ trust = 0
    $ trust += 1
```

Everything after `$` is one line of Python, with Python's own rules for quotes. A long line
can continue onto more-indented lines while a bracket `(` `[` `{` is open.

### if, elif, else
**(proposed, F02)**

```
    if bought_lantern and trust >= 2:
        hana happy "You actually bought one!"
    elif bought_lantern:
        hana "Oh. You bought one."
    else:
        hana sad "Not even a small one?"
```

`if` runs its lines when the condition is true; `elif` is checked only if everything above
was false; `else` runs when nothing above was true and comes last. They line up exactly.
Conditions are Python: `==`, `!=`, `<`, `<=`, `>`, `>=`, `and`, `or`, `not`.

### menu (choices)

```
    menu:
        hana "Will you buy a lantern?"
        "The red one":
            $ lantern = "red"
        "The paper crane (2 coins)" if coins >= 2:
            $ coins -= 2
            $ lantern = "crane"
        "Not this year":
            jump walk_home
    hana happy "Let's go to the river."
```

`menu:` stops the story and shows its choices as buttons over the scene, above the text box.
The player picks one with the mouse, the arrow keys and Enter or Space, the number keys 1–6,
or a gamepad (D-pad or left stick, then A). That choice's lines run, then the story goes on
after the menu, unless they `jump`, `call`, or `return` (which work as anywhere).

- **The question** is optional: one line of dialogue or narration, first in the menu. It
  stays in the text box, complete, while the player chooses. A `voice` line can go directly
  above it. Without a question, the last line stays on screen (right after a `scene`, the
  text box is hidden instead).
- **Choices**: 1 to 6 per menu, each quoted text ending in `:`, with its lines indented
  under it. To have a choice do nothing, write `$ pass` under it. Comments and blank lines
  can go anywhere in the menu.
- **Conditions**: `"text" if condition:` shows the choice only when the condition is true,
  checked once when the menu is reached (the same Python as `if`). At least one choice must
  show, so give every menu one choice without `if`, such as `"That's all":`.
- **Locked choices**: to show unavailable choices dimmed, with a lock, instead of hiding
  them, set `show_locked = true` under `[choice]` in `config.toml`. A locked choice can't
  be picked or focused.
- **Choice text** can use `{b}`, `{i}`, `{color=…}`, `{var=…}`, and `{{`, but not
  `{pause}`, `{speed}`, `{size}`, or `{next}`. A `{var=…}` shows its value as the menu is
  reached. Keep a choice to one line, about 50 characters: a choice shows at most two
  lines, and anything longer is cut with "…". Two choices may have the same text.
- **A menu inside a choice** asks a second question once that choice is picked.
- **A "Talk" loop** is a menu in a label of its own whose topics `jump` back to that label.
  Hide each topic once it's asked with `if not asked_…`, and keep one choice without `if`
  that leaves:

  ```
  default asked_fox = False
  default asked_bridge = False

  label talk:
      menu:
          daichi "What do you want to ask?"
          "The fox shrine" if not asked_fox:
              $ asked_fox = True
              daichi "The foxes guard the lanterns."
              jump talk
          "The old bridge" if not asked_bridge:
              $ asked_bridge = True
              daichi "Older than the town hall."
              jump talk
          "That's all":
              return
  ```

  Reach it with `call talk`, so `return` comes back to the line after the call.
- **Saving**: each menu is one save and rollback point. A save made at a menu loads with the
  same question and choices and nothing focused; going back to a menu lets the player choose
  again. Picks appear in the history log.
- A click or key press in the first quarter second after the choices appear doesn't pick,
  so a fast click through the question never picks by accident.

**Timed choices.** A menu can have a time limit. A bar and a number count down above the
choices; when they run out, the choice marked `timeout` is picked, exactly as if the player
had picked it:

```
    menu time 5:
        hana "Say something!"
        "I love you too.":
            $ answered = True
        "I need to think.":
            jump think_it_over
        "..." timeout:
            hana sad "...You won't even look at me."
```

- **`time N`** goes after `menu`, before the `:`. N is in seconds, from 1 to 60, like
  `pause 1.5` and `fadein 2.0` (a number as written, never a variable).
- **`timeout`** goes after one choice's text, before the `:`. A timed menu has exactly one
  such choice, and it can't have an `if`. It is an ordinary, visible choice, so a player
  with no time limit can still choose silence. Write the timeout branch as a real scene,
  not a game over.
- The timer starts when the choices appear, after the question has finished typing. It
  counts only while the player can use the menu: it waits while the game menu, Settings or
  the load page is open, while the text box is hidden, and while the window isn't focused.
- **Timing assist** (the player's setting): Normal gives N seconds, Slower 2N seconds, and
  No time limits shows the same menu with no bar and no timeout. Changing it mid-countdown
  keeps the fraction of time left (at 4 of 5 seconds, Slower leaves 2 of 10).
- **Saves and going back**: nothing new is saved. A save made at a timed menu loads with the
  full time. Going back to a menu the player already picked at shows it without a
  countdown; going back before a menu not yet picked and forward again restarts the full
  time. Skip stops at a timed menu as at any menu; auto never picks, but the timeout still
  does, and auto goes on after.
- History, the "chosen" marks and the story treat a timeout pick like any pick.
- `time` and `timeout` are words only in these two places; you can still use them as
  variable names.
- The bar's colors are `[theme.choice.timer] fill_color` and `track_color` (they follow
  the choice marker and the focused fill, so every color scheme styles them), and
  `tick_sound` plays at 3, 2 and 1 seconds left; see `docs/ui-system.md`.

**Checks on choices.** A choice can test one of your meters (see
[points](#points-character-stats)) with a roll of the dice, the way Disco Elysium does. The
button shows the odds before the player picks, and the roll decides which lines run:

```
points logic empathy 0 to 10 start 3
default met_daichi = True

label accuse:
    menu:
        daichi "You were at the shrine. Admit it."
        "The gate was locked from the inside." check logic hard:
            success:
                daichi surprised "...How did you know that?"
            failure:
                daichi "Nice story."
        "You're scared of something." check empathy 7 retry if met_daichi:
            success:
                daichi sad "...Of the river."
            failure:
                "He looks away."
        "Never mind.":
            $ pass
```

- **`check <meter> <difficulty>`** goes after the choice's text, before `if` and the `:`.
  The difficulty is a number from 1 to 99, or a word: `trivial` (6), `easy` (8), `medium`
  (10), `hard` (12), `heroic` (14), `legendary` (16), `impossible` (18).
- **The roll**: two six-sided dice plus the meter's value. Reaching the difficulty is a
  success. Double six always succeeds and double one always fails, so nothing is ever
  certain (3% to 97%).
- **Under the choice** go exactly two parts, `success:` first and then `failure:`, each with
  its own lines. Write the failure as a story, not a dead end: it is the scene most
  players remember.
- **The player sees** the odds before the text, in the choice marker's color:
  `[Logic · Hard · 28%] The gate was locked from the inside.` The name is the meter's,
  with `_` as a space; the word is the difficulty's (for a number, the word at or below
  it). The odds use the meter's value when the menu appears.
- **Then the dice roll.** Right after the pick a small card shows two dice tumbling and
  landing (about a second), then the sum against the difficulty and the result:
  `Dice 4 + Empathy 3 = 7 vs 7`, **Success** in the marker color or **Failure** in the
  choice text color. A click, Space or Enter skips the rest; skip mode passes it; with
  Reduce motion the dice show the result at once. Going back or forward never shows it
  again. History keeps one line for it: `Empathy check: 7 vs 7, success`.
- **One try** (a "red check"): once a check has been picked, it's hidden when its menu
  comes back (locked, with `show_locked = true`), whether it succeeded or not. Keep a
  choice without a check in every menu that comes back, so the player always has a way on.
- **`retry`** (a "white check"), after the difficulty: a failed check comes back once its
  meter has changed since the try, up or down. Until then it's hidden (locked, with
  `show_locked = true`, showing `[Empathy · Trivial · Retry once Empathy changes]`). A
  success is final. Give the player a way to change the meter, such as a scene where
  `points empathy += 1` runs; with no line that changes it, the check warns (below).
- **Loading and going back never reroll.** The roll uses the story's dice
  ([Random numbers](#10-random-numbers)), so going back to the menu and picking the same
  choice gives the same result. A retry check's try (the meter's value then, and the
  result) is saved with the pick, so after a load it comes back exactly when it would have.
- In dev runs, the log shows each roll: the dice, the meter, the total and the result.
- `check`, `success`, `failure` and `retry` are words only in these places; they stay free
  as variable names.
- In Studio, the Choice form's Check button opens a dialog with the meter, the difficulty,
  the odds, and **Can retry after the stat changes**.
- Not yet: bonuses on a check ("+1 from the key"), and words for the card and the badge in
  other languages.

**Showing an item.** A menu can let the player show any item they hold (see
[lock item](#lock-tip-lock-item-unlock-codex)) instead of picking a written choice, the way
Ace Attorney lets you present evidence to anyone:

```
lock item red_lantern "Red Lantern"
lock item brass_key "Brass Key"

label bridge:
    menu:
        hana "What's that in your hand?"
        "Nothing.":
            $ pass
        present:
            red_lantern:
                hana happy "You kept it!"
                jump lantern_memory
            else:
                hana "...Why are you showing me that?"
```

- **`present:`** goes in the menu with the choices. The player sees one more button,
  **Show an item…**, after the choices. It opens the bag (the Codex's item list, with each
  item's picture and text); the player picks an item and presses **Show**, or Back to
  return to the choices.
- **Under `present:`** goes one line per item that gets its own reaction, the item's name
  and a colon, each with its lines indented under it, and then **`else:`** last, for any
  other item. `else:` is required: the player can show anything they hold. To have a
  reaction do nothing, write `$ pass` under it.
- **`present if condition:`** shows the button only when the condition is true, like a
  choice's `if`. The button is also left out while the player holds no items (locked, with
  `show_locked = true`). It counts as one of the menu's six choices, so a menu has at most
  five written choices with it. Keep one choice without `if` so the player can always go on.
- **Timed menus**: the countdown waits while the bag is open, as under the game menu.
  `present` can't be the `timeout` choice.
- **Saving**: showing an item is a pick like any other. It's saved with the item, so loading,
  going back and going forward again show the same reaction. History shows the item's
  title as the pick, and the item stays in the bag (to take it, write `lock item <name>`
  in the reaction).
- **The check warns** when the scene gives the player an item (`unlock item`) before the
  menu and `present:` has no reaction for it, since the player has just got it. `else:`
  still answers it; add a reaction if it should matter there.
- `present` is a word only on this line in a menu; it stays free as a variable or
  character name. `present "Hi"` is still a line by a character called `present`.
- In Studio, the Choice form's **Accept an item** section adds the option: a row per item
  with where it goes, and a row for any other item. The Events list shows it under the
  choices, each reaction as **Shows red_lantern**. Headless runs show an item with
  `present red_lantern` at the menu.
- The button's words are `[words] present_choice` ("Show an item…", also the bag's
  heading) and `present_pick` ("Show").
- Not yet: showing tips (people, places), a hotbar, and using up the item shown.

**Settings in `config.toml`.** How menus behave is under `[choice]`; how they look is under
`[theme.choice]` (colors, text size, width, frame images, the focus marker, the locked
look, the fade-in, and focus and pick sounds). Every `choice.*` token, with its default and
range, is in `docs/ui-system.md` (Theme tokens, "Choices").

```
[choice]
show_locked = false     # true: a choice whose condition is false shows locked, not hidden

[theme.choice]
# text_size = 28        # 20-48; without it, the text box's size
# width = 800           # 400-1200
# frame_image = "gui/choice.png"          # a nine-slice picture for every button
# focused.frame_image = "gui/choice_focused.png"
# pick_sound = "sfx/pick.ogg"             # a file in the audio folder
# focus_sound = "sfx/focus.ogg"
```

`show_locked` takes only `true` or `false`; anything else stops the launch:
`config.toml, line 7: [choice] show_locked must be true or false, but found the text "yes"`.

**When a menu is wrong.** The game checks menus at launch and lists every mistake with its
file and line:

| Message | Fix |
|---|---|
| `menu needs : at the end of the line. Write menu:` | Add `:`. |
| `menu takes nothing else on its line. Put the question on the first line inside the menu, e.g. hana "Where to?"` | Move the question inside the menu. |
| `this menu has no lines under it. Indent its question and choices under it.` | Indent the question and choices under `menu:`. |
| `this choice has no lines under it. Indent what happens when it's picked; to just go on, write $ pass.` | Indent the choice's lines, or write `$ pass`. |
| `this menu has no choices. Under the question, add choices like "Go left": with that choice's lines indented under it.` | Add a choice. |
| `this menu has 7 choices, but a menu shows at most 6. Move the rarer ones into a second menu behind a choice such as "Something else...":.` | Split a big menu in two. |
| `the question goes on the first line of the menu, before the choices. Move this line up, or indent it inside a choice.` | Question first, choices after. |
| `this looks like a choice but has no : at the end. Write "Go left":.` | Add `:`. |
| `only choices can go directly in a menu, after one optional question line. Indent this line inside a choice, or move it above menu:.` | Everything but the question goes inside a choice. |
| `this choice has no text, so the player couldn't see it. Write its words between the quotes.` | Write the choice's words. |
| `{pause} can't be used in a choice, because choices appear all at once. Choices can use {b}, {i}, {color}, and {var}.` (`{speed}`, `{size}`, and `{next}` the same) | Remove the tag. |
| `{shake} can't be used in a choice, because choices are shown without text effects. Choices can use {b}, {i}, {color}, and {var}.` (`{wave}` and `{glitch}` the same) | Remove the effect. |
| `there is no tag "colour". Did you mean "color"?` (every tag mistake of [When a tag is wrong](#when-a-tag-is-wrong)) | Fix the tag. |
| `{var=met_daichi} shows a variable that no default or define sets, so the story stops if this line runs before a $ line sets it. Add default met_daichi = "" at the top level.` (warning) | Add the `default`. |
| `this line of text ends with :, which only menu choices do. Remove the :, or put the choice in a menu: block.` | A choice outside a menu: put it in one. |
| `voice goes directly above a line, not above a menu. Put a voice inside each branch.` (warning) | Put the `voice` above the question, or inside each choice. |
| `this choice needs 2 lines at text size 28. Choices are easiest to read on one line, about 50 characters.` (warning, dev runs) | Shorten the choice. |
| `this choice needs 3 lines at text size 28, but a choice shows at most 2, so the end is cut with "…". Shorten it.` (warning, dev runs) | Shorten the choice. |
| `config.toml: [theme.choice] pick_sound "pik.ogg" doesn't exist, so no sound plays. Did you mean "pick.ogg"?` (warning) | Fix the file name; sounds are in the `audio` folder. |
| `menu time needs a number of seconds after it, e.g. menu time 5:` | Write the seconds. |
| `menu time takes a number of seconds from 1 to 60, but found five. Write e.g. menu time 5:` | A number from 1 to 60, as digits. |
| `menu time 5 takes nothing else on its line. Put the question on the first line inside the menu, e.g. hana "Where to?"` | Move the question inside the menu. |
| `this choice is marked timeout, but its menu has no time limit. Write menu time 5: to give the player 5 seconds, or remove timeout.` | Add `time` to the menu, or remove `timeout`. |
| `this menu has a time limit but no choice marked timeout, so nothing could happen when time runs out. Write timeout after one choice's text, e.g. "Say nothing" timeout:` | Mark one choice `timeout`. |
| `this menu has 2 choices marked timeout, but time running out picks only one. Remove timeout from all but one.` | Keep one `timeout`. |
| `the timeout choice can't have an if: when time runs out, it must be there to pick. Remove the if, or mark a choice without one as timeout.` | Remove the `if`, or move `timeout`. |
| `this menu gives the player 3 seconds, but its choices are 112 characters long, about 8 seconds of reading. Raise the time, e.g. menu time 8:, or shorten the choices.` (warning, dev runs) | Raise the time or shorten the choices. |
| `check needs a meter and a difficulty, e.g. "Pick the lock" check logic medium:` | Write the meter and the difficulty. |
| `check logic needs a difficulty after the meter: a number from 1 to 99, or trivial, easy, medium, hard, heroic, legendary or impossible.` | Add the difficulty. |
| `check takes a difficulty from 1 to 99 or a word (trivial, easy, medium, hard, heroic, legendary or impossible), but found tough.` | Use a number or one of the words. |
| `check logic 9 takes nothing else before the : (an if may follow it), but found now.` | Remove the extra words. |
| `retry goes after the difficulty: write check logic medium retry, or check logic 9 retry.` | Move `retry` after the difficulty. |
| `this check can be retried once empathy changes, but no line changes empathy, so after a failure it never comes back. Add a line such as points empathy += 1 where the player earns it, or remove retry.` (warning) | Add a `points` line that changes the meter, or remove `retry`. |
| `there is no meter named "lgoic". Did you mean "logic"? Declare meters at the top level, e.g. points lgoic 0 to 10.` | Fix the name, or declare the meter. |
| `this choice has a check but no failure: under it. Add failure: with what happens then; to just go on, write $ pass under it.` | Add the missing part. |
| `a choice with a check holds only success: and failure:, each with its own lines. Indent this line under one of them.` | Move the line under `success:` or `failure:`. |
| `write success: first, then failure:, under a choice with a check.` | Swap the two parts. |
| `present: needs else: as its last line, for any other item the player shows (they can show anything they hold). Add else: with what happens then; to just go on, write $ pass under it.` | Add `else:` last under `present:`. |
| `this present: already has a reaction for red_lantern (line 7). Put all its lines under the first one.` | Join the two reactions into one. |
| `there is no item "red_lantren". Did you mean "red_lantern"? Declare items at the top level, e.g. lock item red_lantren "Title".` | Fix the item's name, or declare the item. |
| `lanterns is a tip; only items can be shown at present:. Use an item's name, or else: for everything else.` | Use an item, or let `else:` answer it. |
| `under present: each line is an item's name and a colon, e.g. red_lantern:, or else: for any other item. Indent what happens under each one.` | Put each item's name with a colon, and its lines under it. |
| `brass_key: comes after else:, but else: must be last under present:. Move it above else:.` | Move the reaction above `else:`. |
| `present: has no lines under it. Indent a line for each item, e.g. red_lantern:, then else: for any other item.` | Add the reactions under `present:`. |
| `present takes nothing before the : except an if, but found timeout. Write present: or present if <condition>:` | Remove the extra words; `present` can't be the timeout choice. |
| `this scene gives the player brass_key before this menu, but present: has no reaction for it, so else: answers. Add brass_key: under present: if it should matter here.` (warning) | Add `brass_key:` under `present:`, or leave it to `else:`. |

One mistake shows only while the story runs (see [Run-time errors](#22-run-time-errors)):
`every choice in this menu is hidden, because all their conditions are false, so the player can't pick anything. Add a choice without if, such as "That's all":.`
(with `show_locked = true`: `every choice in this menu is locked, …`). Give the menu a
choice without `if`.

### include
See [Files and includes](#2-files-and-includes).

### scene, show, hide, image
See [Backgrounds and sprites](#12-backgrounds-and-sprites).

### play, queue, stop, voice
See [Music and sound](#13-music-and-sound).

### with, shake, flash, pause
See [Transitions and effects](#16-transitions-and-effects).

### rollback
See [Rollback](#18-rollback): `rollback block`, `rollback off`, `rollback on`, and
`rollback fixed`.

### Meta files
See [section 23](#23-meta-files): `file write`, `file delete`, `file exists`, and
`file read`.

### Glitch effects
See [section 24](#24-glitch-effects): `effect tear`, `effect colorshift`, `effect static`,
`effect jitter`, `effect off`, and `with glitch`.

### Fourth-wall tricks
See [section 25](#25-fourth-wall-tricks): `effect window_title`, `effect crash`, and the
`{username}` tag.

### Dynamic UI
See [section 26](#26-dynamic-ui): `ui style`, `ui saving off`/`on`, `ui loading off`/`on`,
and `ui delete saves`.

### chapter
```
    scene bg festival
    chapter festival "Chapter 2" "The Lantern Festival"
    hana happy "The lanterns are already lit!"
```
Marks where a chapter starts. The screen goes to a title card, holds it 3 seconds, then
shows the stage, so set the next scene **above** the `chapter` line. A click finishes each
part. The first line after it is auto-saved, saves in the chapter are named after it
("Chapter 2: The Lantern Festival"), and chapters ever reached are remembered across
playthroughs.
- **Name**: like a label name, one per chapter; it may match a label.
- **Texts**: a title, or a heading and a title (`chapter prologue "Prologue"`); plain
  text, no `{b}` or `{var}` (write `{{` for a `{`). Heading up to 60 characters, title up
  to 120; a title that needs more than two lines on the card is cut with "…".
- **Card length**: seconds after the texts, e.g. `5`, from 0 to 30; `0` shows no card,
  but the chapter still starts, is auto-saved, and names saves.
- **with**: any [transition](#with), used going in and coming out; default `fade`.
  `chapter river "Chapter 3" "By the River" 5 with dissolve 1.5`
- Skip passes the card; auto mode waits out its length; menus pause it.

The example game has three: a prologue, and two chapters with headings (one with a card
length and `with`).

**Settings in `config.toml`**

| Setting | Default | What it changes |
|---|---|---|
| `[chapter] autosave` | true | An Auto save at the first line after each `chapter` |
| `[chapter] name_saves` | true | Saves named after their chapter; false: after their line |

**Looks** (`[theme.chapter]`, screen units; the card's text doesn't grow with the
player's text size)

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `chapter.fill_color` | `"#2A1E26"` | | The card |
| `chapter.fill_opacity` | 1.0 | 0.0–1.0 | Below 1.0 the scene shows through |
| `chapter.heading.text_font` | `ui.text_font` | | The heading |
| `chapter.heading.text_size` | 32 | 20–64 | |
| `chapter.heading.text_color` | `"#F0A0C0"` | | |
| `chapter.title.text_font` | `ui.bold_font` | | The title |
| `chapter.title.text_size` | 56 | 24–96 | |
| `chapter.title.text_color` | `"#FFF4F8"` | | |
| `chapter.gap` | 16 | 0–64 | Between heading and title |
| `chapter.max_width` | 1040 | 400–1240 | Where the title wraps |

| Message | Fix |
|---|---|
| `there are two chapters named "festival": here and at story.vns, line 12. Give each chapter its own name.` | Rename one. |
| `chapter needs a name and a title in quotes, e.g. chapter festival "The Lantern Festival".` / `chapter has three texts; …` / `this line has "slowly" left over after the chapter title. …` | Write `chapter name "Heading" "Title" 3 with fade` in that order. |
| `the chapter title has 140 characters; keep it to 120.` / `chapter text is shown as written, so it can't use text tags such as {b}. …` | Plain text up to 120 characters (heading 60, name 64). |
| `chapter takes a card length from 0 to 30 seconds (0 shows no card), but this has 45.` | Use seconds from 0 to 30. |
| `the title of chapter "festival" needs more than 2 lines on its card at size 56, so it is cut with "…". Shorten it to about 60 characters.` (warning) | Shorten the title. |
| `[theme.chapter] title.text_color "#60505A" has a contrast of 2.1:1 on the chapter card, under 4.5:1, so players may not read it.` (warning) | Pick colors further apart. |

### ending, lock route, unlock route
```
lock route promise "Hana's Promise" until sad, good

label river_end:
    hana "Maybe next year."
    ending sad "Sad End" "Paper Ashes"

label festival_end:
    hana "Look at the lanterns!"
    ending good "Good End" "The Lantern Festival"

label promise:
    hana "You came."
    lock ending sad
    lock ending good
    ending true "True End" "Hana's Promise"
```
```
label bridge:
    if "sad" in persistent.endings:
        hana "You look like you've lost someone before."
    if len(persistent.endings) >= 3:
        "Something about tonight feels familiar."
    menu:
        hana "The bridge, or home?"
        "Wait at the bridge" if "promise" in persistent.routes:
            jump promise
        "Go home":
            jump walk_home
```

**`ending name "Heading" "Title"`** ends the story. The game remembers the ending across
playthroughs, shows a card with its texts for 3 seconds, then fades to the title screen.
It works the same inside a `call` or a menu choice.
- **Name**: like a label name, one per ending; it may match a label or a chapter. Up to
  1,000 endings.
- **Texts**: a title, or a heading and a title, as for [chapter](#chapter): plain text, no
  `{b}` or `{var}` (write `{{` for a `{`), heading up to 60 characters and title up to 120.
- **Card length**: seconds after the texts, from 0 to 30; `0` shows no card and goes
  straight to the title screen. **with**: any [transition](#with), used for the card's way
  in; default `fade`. `ending good "Good End" "The Lantern Festival" 5 with dissolve`
- Nothing after an `ending` runs, so give the ending's lines **above** it. The card uses
  `[theme.chapter]`. A click ends the card early; skip passes it.
- The ending is remembered the moment the line runs, so quitting during the card keeps it.
  An ending makes no save, and the player can't roll back once it starts.

**`lock route label "Title"`** at the top level declares a **route** that starts locked, at
that label. Add `until sad, good` (1 to 32 ending names) to open it once the player has
reached all of those endings, in any playthroughs: a true route. Without `until`, only
`unlock route` opens it. Up to 1,000 routes.

Inside a label, **`unlock route name`** opens a route for good, **`lock route name`** closes
it again, and **`lock ending name`** makes the game forget an ending, which can close a route
that needs it (an ending that wasn't reached is left as it is). None of them waits or shows
anything. An ending is recorded only by reaching its `ending` line, so there is no
`unlock ending`.

The engine doesn't stop a `jump` into a locked route: check it in the choice's condition, as
above, and set `show_locked = true` under `[choice]` in `config.toml` to show the choice
dimmed, with a lock, until it opens (see [menu (choices)](#menu-choices)).

**`persistent.endings`** (the endings reached, first reached first) and
**`persistent.routes`** (the open routes, in the order they are declared) are lists you can
read anywhere, but not change or give a `default`: use `ending`, `lock ending`, and
`unlock route`/`lock route`. A copy (`$ seen = persistent.endings`) is an ordinary list.
Only names your script declares are listed.

Loading a save, rolling back, New Game, and `persistent._clear()` never change endings or
routes. Players reset them with "delete persistent data" in Settings.

The example game has three endings at the bridge, in `script/endings.vns`: the true ending
is the promise route, locked until both others are reached, and it forgets them again.

| Message | Fix |
|---|---|
| `ending needs a name and a title in quotes, e.g. ending good "The Lantern Festival".` / `ending has three texts; …` / `this line has "slowly" left over after the ending title. …` | Write `ending name "Heading" "Title" 3 with fade` in that order. |
| `ending goes inside a label, because it runs when the story reaches it.` | Move it into a label. |
| `there are two endings named "good": here and at script/story.vns, line 40. Give each ending its own name.` / `route "promise" is declared twice: …` | Rename one, or keep one `lock route` line. |
| `the ending title has 140 characters; keep it to 120.` / `ending text is shown as written, so it can't use text tags such as {b}. …` / `ending takes a card length from 0 to 30 seconds (0 shows no card), but this has 45.` | Plain text up to 120 characters (heading 60, name 64), seconds from 0 to 30. |
| `lock route promis names the label the route starts at, but there is no label "promis". Did you mean "promise"?` / `until names endings, but there is no ending "god". Did you mean "good"?` | Use a label name, and ending names from `ending` lines. |
| `until lists "good" twice.` / `until lists 40 endings; the most is 32.` | List each ending once, up to 32. |
| `there is no route "promis". Did you mean "promise"? …` / `there is no ending "god". Did you mean "good"?` | Fix the name, or declare the route with `lock route`. |
| `unlock ending can't be used: an ending is recorded when the story reaches its ending line.` | Reach the `ending` line instead. |
| `at the top level, lock only declares a route, …` / `lock route promise declares a route, so it goes at the top level. …` | Declare routes at the top level; put `unlock` and `lock` lines in a label. |
| `persistent.endings is kept by the engine, so this line can't change it. Endings are recorded by the ending statement and forgotten with lock ending.` / `persistent.endings is kept by the engine (the endings reached so far), so it can't have a default. Remove this line.` | Read it; change it with `ending` and `lock ending` (`persistent.routes`: `unlock route`, `lock route`). |
| `this story has 1,204 endings; the engine allows 1,000.` | Up to 1,000 endings and 1,000 routes. |
| `the lines after this ending never run, because ending ends the story. Move them above the ending or into another label.` (warning, dev runs) | Move them above the `ending`. |
| `lock route promise has no effect while its until endings (sad, good) are reached. Lock one of those endings too, or remove until.` (warning, dev runs) | Add `lock ending` for one of them, or remove `until`. |
| `persistent data had its own value named "endings" from an older version of the game. 2 ending names in it were recorded as reached, and the value was dropped.` (warning) | Nothing to do: an older version's own `persistent.endings` list was moved over. |

### lock tip, lock item, unlock (codex)
```
lock tip lanterns "Paper Lanterns" in "Festival":
    "Lanterns are folded from washi paper and set on the river on the last night."
    "Each carries one wish. Hana never says what hers is."
lock tip river_god "The River God" in "Legends"
lock item red_lantern "Red Lantern" in "Things" image items red_lantern:
    "Bought at Daichi's stall. The paper is {i}still warm{/i}."

label stall:
    daichi "One lantern, please."
    unlock item red_lantern
    hana "Let's go to the river."
    unlock tip lanterns
    jump bridge
```
```
label bridge:
    if "red_lantern" in codex.items:
        hana "Is that... the lantern from the stall?"
    menu:
        "Ask about the river god" if "river_god" in codex.tips:
            jump river_story
        "Say nothing":
            thought "Some things are better not asked."
    "The lanterns drifted on."

label river_story:
    hana "He grants one wish a year."
    unlock tip river_god
    lock item red_lantern
```

The **codex** is a page of the game menu that lists what the player knows and holds. It
has two kinds of entry:
- A **tip** is something the player learns: a custom, a legend, a word. **Tips are kept
  across playthroughs.** Loading a save, rolling back, and New Game never take one away.
- An **item** is something the player has right now: a key, a clue, a gift. **Items belong
  to this playthrough.** They are saved and rolled back like story variables, and a new
  game starts with none. Use items for clues that should reset, too.

**Declare** each entry once at the top level of any file: **`lock tip name "Title"`** or
**`lock item name "Title"`**. The entry starts locked: the player doesn't have it yet.
- **Name**: like a label name, one per entry across tips and items, up to 64 characters.
- **Title**: plain text up to 60 characters, shown in the list and above the entry. No
  `{b}` or `{var}` (write `{{` for a `{`).
- **`in "Category"`**: the tab the entry is listed under, up to 24 characters. Without it,
  tips go under "Tips" and items under "Items". A category holds tips or items, not both,
  and categories differ by their exact spelling. Up to 24 categories.
- **`image items red_lantern`**: a picture shown above the text, named as for `show` (here
  `images/items/red_lantern.png`). A large picture is made smaller to fit; a small one is
  never enlarged. A name with no picture gets the usual missing-picture warning when the
  game starts.
- **The text**: one quoted paragraph per indented line under the declaration, up to 32
  paragraphs of 2,000 characters. `{b}`, `{i}`, and `{color}` work; other tags don't.
- Up to 1,000 tips and 1,000 items.

**Inside a label**, **`unlock tip name`** adds a tip for good, and **`unlock item name`**
gives the player an item; each new one shows a notice ("New tip: Paper Lanterns").
**`lock item name`** takes an item away, and **`lock tip name`** makes the game forget a
tip. None of them waits or shows anything else, and the next line already sees the change.
Unlocking an entry the player already has does nothing.

**Read** them anywhere Python runs: **`codex.tips`** (the tips the player has, in the order
they are declared) and **`codex.items`** (the items the player holds, in the order they got
them) are lists of names: `"red_lantern" in codex.items`, `len(codex.tips)`. You can't
change them, give them a `default`, or read them in a `define` (use a `lambda`): use
`unlock` and `lock`. A copy (`$ seen = codex.items`) is an ordinary list. `tip` and `item`
are still free as variable names; `codex` is the engine's.

**Item counts and money.**

```
lock item coin "Coins" in "Purse" count 0 to 999 money
lock item match "Matches" count 3
default left = 0

label market:
    unlock item coin 30
    unlock item match 3
    if items.count("coin") >= 5:
        lock item coin 5
        unlock item red_lantern
        $ left = items.count("coin")
        daichi "Here you go. You have {var=left} coins left."
```

An item can be held **more than once** when its declaration has **`count`**: the bag shows it
as "Coins ×30".
- **`count`** alone lets the player hold up to 999,999; **`count 0 to 999`** (or **`count
  999`**) holds at most 999. A count always starts at 0.
- **`unlock item coin 30`** gives 30, and stops at the most the item holds. **`lock item coin
  5`** takes 5, and never goes below none: at 0 the item is gone from the bag. Without a
  number, `unlock item` gives one and `lock item` takes one, as before. An item without
  `count` is held once or not at all, so `unlock item key 3` still gives one key (with a
  warning).
- **`money`** marks the one item that is the player's money: the bag shows it at the top,
  "Coins ×30", even when the player has none. Money always counts, so `count` can be left out
  (`lock item coin "Coins" money`). `count` and `money` go anywhere after the title; both are
  words only there, so they stay free as names.
- **`price 5`** is what a shop asks for one of the item when its stock names no price
  (`lock item tea "Jasmine Tea" count 0 to 9 price 5`): a whole number from 0 to 999,999,
  anywhere after the title, items only. See "Shops" under `minigame`.
- **Read a count** with **`items.count("coin")`** anywhere Python runs: `if
  items.count("coin") >= 5:`, `$ left = items.count("coin")`. It is 0 when the player has none.
  To show it in a line, copy it to a variable first, as above. `codex.count("coin")` is the
  same thing; use it if your story has a variable of its own named `items` (then `items` stays
  yours, and `items.count` is that variable's).
- Counts are saved, loaded and rolled back with the items. A save made before counts loads
  with one of each item it held.
- The story map follows counts like variables: a scene behind `if items.count("coin") >= 30:`
  lists the `unlock item coin` and `lock item coin` lines that change it.

**The bag's words.** A genre kit names the items tab and the money: Fantasy's bag is the
"Satchel" and its money "Gold"; Mystery's is "Evidence"; Sci-fi's "Cargo" and "Credits".
`[codex] bag_word` and `money_word` in config.toml change them for your game. Without a kit
or a word, the tab is "Items" and the money shows its own title.

**Using items.**

```
lock item tea "Jasmine Tea" in "Things" count 0 to 5 use drink_tea

label drink_tea:
    lock item tea                 # using takes one only if the scene says so
    "Warmth spreads through your hands."
    return
```

- **`use drink_tea`** (anywhere after the title, items only) gives the item a **Use** button
  in the bag. Pressing it runs the scene `drink_tea` like a `call`: when the scene returns,
  the story goes on with the line after the one the player was reading. Using takes nothing
  by itself; a scene that uses an item up says `lock item tea`.
- **When an item can be used:** only while the story waits for a click at a line, with the
  whole line shown. Never at a menu, in a minigame, during a `pause` or a chapter card, or
  while another item's scene runs. Then the Use button is greyed out, and a hotbar key says
  "Not now". To make an item work only in some places, check in its scene: `if not
  in_cellar:` / `"Not here."` / `return`.
- **Saves and going back.** A use is a step of the story like any other: going back from the
  scene's first line returns to the line where the item was used, with the item back, and
  going forward again uses it again. Saves made inside the scene load there.
- `use` is a word only there, so it stays free as a name. The scene must be a label
  (did-you-mean on a typo).

**Rolling back** past `unlock item` takes the item away again, and scrolling forward gives
it back without a second notice. A tip stays, so a condition on `codex.tips` can turn out
differently when the player goes forward again; then the lines ahead are played afresh.
Players reset tips with "delete persistent data" in Settings; that keeps their items.

The codex page shows in the game menu, after History, once the story declares an entry.
Its tabs are the categories that have an entry to show; a dot marks an entry the player
hasn't opened yet. On the title screen it lists tips only, and only when `[title] entries`
names it (`entries = ["new_game", "load", "codex", "settings", "quit"]`) and the player has
a tip.

The example game has two tips ("Paper Lanterns" in Festival, "The River God" in Legends) and
two items: the paper lantern, with a picture, which the river takes when it is let go, and
the fortune slip, which stays tied to the rail on bad luck.

**Settings in `config.toml`**

| Setting | Default | What it changes |
|---|---|---|
| `[codex] notify` | true | A notice for each new tip or item; false: none |
| `[codex] show_locked` | false | true: tips the player doesn't have yet are listed as `???` |
| `[codex] bag_word` | "" | The items tab's name, such as "Satchel"; empty: the kit's, else "Items" |
| `[codex] money_word` | "" | The money's name at the top of the bag, such as "Gold"; empty: the kit's, else the item's title |

**Looks** (`[theme.codex]`, `[theme.codex.new]`, `[theme.codex.locked]`) and **words**

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `codex.new.fill_color` | `button.marker.fill_color` (`"#A02860"`) | | The dot on an entry not opened yet |
| `codex.locked.text_color` | `button.disabled.text_color` (`"#6E5E68"`) | | `???` rows |
| `codex.image_height` | 200 | 0–320 | The picture's height; 0 shows no pictures |

The list and the panel use the `button.*`, `list.*`, and `panel.*` settings. The words are
`codex` "Codex", `codex_tips` "Tips", `codex_items` "Items", `codex_new_tip` "New tip",
`codex_new_item` "New item", `codex_locked` "???", and `codex_empty` "Nothing here yet.",
each changed under `[words]`.

| Message | Fix |
|---|---|
| `lock tip needs a name and a title in quotes, e.g. lock tip lanterns "Paper Lanterns".` / `lock tip lanterns "Paper Lanterns" declares a tip, so it goes at the top level. …` / `unlock goes inside a label, because it runs when the story reaches it.` | Declare entries at the top level as `lock tip name "Title" in "Category" image …`, in that order; put `unlock` and `lock` lines in a label. |
| `there are two codex entries named "lanterns": here and at script/codex.vns, line 4. Give each tip and item its own name.` | Rename one. |
| `the tip title has 75 characters; keep it to 60.` / `a tip paragraph can use {b}, {i}, and {color}, but not {var}.` | Plain titles up to 60 characters; only `{b}`, `{i}`, `{color}` in the text. |
| `there is no tip "lantern". Did you mean "lanterns"? Declare tips at the top level, e.g. lock tip lantern "Title".` / `brass_key is an item, not a tip. Write unlock item brass_key.` | Fix the name, or declare the entry. |
| `this story has 1,204 tips; the engine allows 1,000.` | Up to 1,000 tips, 1,000 items, and 24 categories. |
| `there is no codex.itmes. Did you mean "items"? codex has tips, items, and count.` / `Python can't change codex.items. Use unlock item and lock item.` | Read `codex.tips` and `codex.items`; change them with `unlock` and `lock`. |
| `the amount in unlock item coin is a whole number from 1 to 999,999, but found "0". Write e.g. unlock item coin 3.` / `lock item coin takes a number after the name, but found "all". …` / `a tip is given or forgotten all at once, so unlock tip lanterns takes no number. …` | Write a whole number after an item's name, or none; to take some away, use `lock item`. |
| `tip lanterns can't have a count: a tip is known or not. …` / `tip lanterns can't be the money: …` | Only items have `count` and `money`. |
| `tip lanterns can't be used: only an item has a Use button, …` / `use needs the name of a label, e.g. use bridge.` / `there is no label named "drink_te". Did you mean "drink_tea"?` | Write `use` and a scene's label name on an item's declaration. |
| `a count always starts at 0, so write count 0 to 999 (or count 999) …` / `the most of coin a player can hold is a whole number from 1 to 999,999, but found "0". …` | Write `count`, `count 999` or `count 0 to 999`. |
| `gold and coin (script/items.vns, line 1) are both marked money, but the bag shows one purse. Remove money from one of them.` | Keep `money` on one item. |
| `there is no item named "coins". Did you mean "coin"? …` / `"lanterns" is a tip, not an item, so it has no count. …` / `items.count needs an item's name in quotes, e.g. items.count("coin"), not 3.` | Count a declared item by its name in quotes. (Also while playing, when the name is computed.) |
| `there is no items.total. items has one thing, count: …` / `Python can't change items. …` | Read `items.count("coin")`; change counts with `unlock item` and `lock item`. |
| `item brass_key has no count, so the player holds at most one and the 3 here acts as 1. …` (warning) | Add `count` to the item's declaration, or drop the number. |
| `this story has its own variable named items, so items.count("coin") reads that variable, not the bag. Write codex.count("coin") to count the item.` (warning) | Use `codex.count`, or rename your variable. |
| `coin holds at most 999, so unlock item coin 2,000 stops there. …` (warning) | Raise the item's most, or give less. |
| `define hint couldn't be set: it reads codex, which holds items only once a game has started. Use a lambda or a default.` (when the game starts) | Use `define hint = lambda: …` or a `default`. |
| `the category "festival" differs from "Festival" (script/codex.vns, line 1) only in capitals or spaces, so they show as two tabs. Use one spelling.` (warning, dev runs) | Spell the category one way. |
| `tip river_god is declared, but no unlock tip river_god line names it, so players get it only if code unlocks it.` (warning, dev runs) | Add an `unlock tip` line, or remove the tip. |
| `lock item brass_key does nothing here, because the player doesn't have it.` (warning, dev runs) | Check for the item first: `if "brass_key" in codex.items:`. |

### show hotbar, hide hotbar

`show hotbar` puts quick slots for usable items in a corner of the screen; `hide hotbar`
takes them away.

```
lock item match "Matches" count 0 to 3 use strike_match

label cellar:
    unlock item match 3
    show hotbar
    "It's pitch dark down here."
```

```toml
[hotbar]
slots = 4                       # 4 to 8 slots; the number keys 1 to 4 use them
items = ["match", "potion"]     # which item each slot holds; empty: automatic
place = "bottom_left"           # the corner
word = "Belt"                   # its name in the bag; empty: the kit's, else Hotbar
```

- Each slot shows the item's picture (else its first letters), its number key, and for a
  counted item how many the player holds. A slot whose item the player doesn't hold is empty.
- **Using a slot:** press its number key (1 to 8), click it, or on a gamepad press X, move
  with left and right and press A (B or X again leaves the slots). The rule is the Use
  button's: only while the story waits at a fully shown line; otherwise "Not now" shows.
- **Which items:** `[hotbar] items` names them slot by slot. Without it the slots fill with
  the held items that have a Use scene, in the order the player got them.
- It stays on screen, across scenes, until `hide hotbar`. Saves keep it, going back restores
  it, and New Game starts without it. Like shown meters it hides with the text box, under
  menus and during minigames, and fades in and out (cuts with Reduce motion).
- The corner is `[hotbar] place` (`top_left`, `top_right`, `bottom_left` or
  `bottom_right`), else the bottom left, above the text box. A genre kit names it in the bag
  ("Belt" in Fantasy, "Pockets" in Horror and Mystery); `[hotbar] word` changes the name.
- `show hotbar` and `hide hotbar` mean the hotbar only with nothing else on the line.
  `show hotbar at center` or `hide hotbar with dissolve` still show and hide a picture
  called hotbar; a game with such a picture gets a warning at each bare line.

| Message | Fix |
|---|---|
| `[hotbar] items names potoin, but no item has that name. Did you mean "potion"?` (warning) | Use an item's name from its `lock item` line. |
| `[hotbar] items names item key, which has no Use scene, so its slot could never be used. …` (warning) | Add `use` and a scene to the item, or take it off the list. |
| `show hotbar shows the hotbar now, not your picture hotbar. …` (warning, when the game starts) | Add where it goes (`show hotbar at center`), or rename the picture. |

### lock gallery, unlock gallery
```
lock gallery cg big_lantern "The Big Lantern"
lock gallery cg last_lantern "The Last Lantern":
    cg last_lantern_ashes

label festival_end:
    hana happy "Then come on! They light the big lantern at ten."
    scene cg big_lantern with dissolve
    "We ran down into the crowd. For one night, it felt like I had never left."
```
```
label letter:
    "Hana's letter said one lantern made it all the way to the sea."
    unlock gallery cg last_lantern
    "The burnt frame of the other one was still on her windowsill."
    unlock gallery cg last_lantern_ashes

label start_over:
    lock gallery cg big_lantern
```

The **gallery** is a page of **Extras**, on the title screen, where players look again at
the special pictures (CGs) they have seen: small squares, 12 to a page, and a click shows
the picture on the whole screen.

**Declare** each gallery picture once at the top level of any file: **`lock gallery
picture "Title"`**.
- **Picture**: named as for `show`; `cg big_lantern` is `images/cg/big_lantern.png`. Any
  picture works, a background or a sprite too. A name with no picture gets the usual
  missing-picture warning when the game starts.
- **Title**: plain text, 1–60 characters, shown under the square. No `{b}` or `{var}`
  (write `{{` for a `{`).
- **Versions**: picture names indented under the declaration, one per line, up to 8. They
  are more versions of the same picture (another face, another light) and share its
  square; the square shows how many of them the player has seen, and the whole-screen view
  steps through those.
- The gallery lists the pictures in the order of their lines (files in `include` order).
  A picture is in the gallery once. Up to 500.

**Gallery pictures unlock when they show.** Each one starts locked and unlocks the first
time it shows in the story: a `scene` or `show` line, or a dialogue line that changes a
sprite to it. There is nothing else to write. **Unlocks are kept across playthroughs**:
loading a save, rolling back, and New Game never take one away. Loading a save, rolling
back onto a picture, or jumping to it from the Flowchart page doesn't unlock it; playing to
it does. Players reset the gallery with "delete persistent data" in Settings.

**Inside a label**, **`unlock gallery picture`** unlocks a picture without showing it,
for one the story only tells of, and **`lock gallery picture`** (no title) makes the game
forget it, so its square is locked again. The name can be a version. Neither line waits or
shows anything.

The **Extras** button shows on the title screen once the player has unlocked a gallery
picture, and opens on the Gallery page. A picture not unlocked yet is a `???` square.
To see the gallery while you work, run `python -m engine run game --extras` (dev runs
only): every picture counts as unlocked, nothing is saved, and Extras opens at once.

`gallery` is still free as a name: it means something only right after `lock` or
`unlock`. `cg` is an ordinary name too, so `images/cg/` is a folder like any other.

The example game has two gallery pictures: "The Big Lantern" at the good ending, and "The
Last Lantern" at the true ending, with a version, the burnt frame, at the sad ending.

**Settings in `config.toml`**

| Setting | Default | What it changes |
|---|---|---|
| `[gallery] show_locked` | true | false: pictures not unlocked yet are left out instead of shown as `???` |

**Looks** (`[theme.gallery.caption]`, `[theme.gallery.viewer]`) and **words**

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `gallery.caption.text_size` | 20 | 14–32 | The titles under the squares |
| `gallery.viewer.fill_color` | `"#000000"` | | Around a picture shown on the whole screen |

The squares use the `button.*` and `panel.*` settings. The words are `extras` "Extras",
`gallery` "Gallery", and `gallery_locked` "???", each changed under `[words]`.

| Message | Fix |
|---|---|
| `lock gallery needs a picture name and a title in quotes, e.g. lock gallery cg festival "Festival Night".` / `this line has "slowly" left over after the title. lock gallery takes a picture name, then a title in quotes.` / `only picture names can go under a gallery picture, one per line, e.g. cg festival_smile.` | Write `lock gallery picture "Title"`, with only picture names indented under it. |
| `lock gallery cg festival "Festival Night" adds a picture to the gallery, so it goes at the top level. To make the game forget it during the story, write lock gallery cg festival with no title.` / `unlock gallery goes inside a label, because it runs when the story reaches it.` | Declare at the top level; put `unlock gallery` and `lock gallery` lines in a label. |
| `the picture "cg festival" is in the gallery twice: here and at script/gallery.vns, line 4. Give each picture one place in the gallery.` / `this story has 520 gallery pictures; the engine allows 500.` | Remove one of the lines; up to 500 gallery pictures. |
| `the gallery title is empty.` / `the gallery title has 75 characters; keep it to 60.` / `gallery titles are shown as written, so they can't use text tags such as {b}. Write {{ for a "{".` / `this gallery picture has 11 versions; keep it to 8.` | Plain titles of 1–60 characters; up to 8 versions. |
| `there is no gallery picture "cg festivl". Did you mean "cg festival"? Add pictures to the gallery at the top level, e.g. lock gallery cg festivl "Title".` | Fix the name, or add the picture to the gallery. |
| `the gallery picture "cg storm" never shows in the story and no unlock gallery line names it, so players can't get it.` (warning, dev runs) | Show the picture somewhere, add an `unlock gallery` line, or take it out of the gallery. |

### lock track (music room)
```
lock track main_theme "Main Theme" file "bgm/main_theme.ogg" open
lock track festival "Festival Night" file "bgm/festival.ogg"
lock track credits "Paper Lanterns" file "bgm/credits.ogg" until true
```

The **Music Room** is a page of **Extras**, on the title screen, where players listen to
the game's music again. It lists the tracks in the order of their lines; a track that isn't
open yet is a `???` row. Picking a row plays it from the start; the buttons are Previous,
Play/Pause, Next, and Play all / Repeat track (Play all plays each open track once, then the
next; Repeat track plays the same one again and again). Page Up and Page Down, and a
gamepad's shoulder buttons, are Previous and Next too.

**Declare** each track once at the top level of any file: **`lock track name "Title" file
"file"`**, then how it opens.
- **Name**: a name as in section 6, up to 64 characters. The game remembers a heard track
  by its name, so you can change its file later.
- **Title**: plain text, 1–60 characters, shown in the list. No `{b}` or `{var}` (write
  `{{` for a `{`).
- **File**: as `play music` writes it, inside `audio/`. Each file is in the Music Room
  once, and each name once. Up to 200 tracks.
- **How it opens**:
  - nothing more: the track opens the first time the story plays its file, with `play
    music` or `queue music` (loading a save that has it playing counts too), and **stays
    open across playthroughs**;
  - **`open`**: it is there from the start;
  - **`until ending, ending`**: it opens once the player has reached every one of those
    endings, and closes again if a `lock ending` line makes the game forget one.

There is no `unlock track` line, and `lock track` goes only at the top level.

The **Extras** button (and the Music Room in it) shows once at least one track is open.
While the Music Room is open, its track plays in place of the title music, at the
player's Music volume; leaving the page fades it out and the title music starts again.
To try the Music Room while you work, run `python -m engine run game --extras music_room`
(dev runs only): every track counts as open, and nothing is saved. Players close the heard
tracks again with "delete persistent data" in Settings.

The example game has three tracks: "Lantern Walk", the title music, `open`; "Bridge at
Night", which opens when the story first plays it on the bridge; and "The River at Night",
the river's sound, `until true`.

`track`, `open` and `until` are still free as names: they mean something only right after
`lock`. (`file` is a statement word of its own, section 23.)

**Words**: `music_room` "Music Room", `music_play` "Play", `music_pause` "Pause",
`music_previous` "Previous", `music_next` "Next", `music_play_all` "Play all",
`music_repeat_one` "Repeat track", `music_locked` "???", and `music_pick` "Pick a track to
play.", each changed under `[words]`. The page uses the `list.*`, `button.*`, `panel.*` and
`slider.*` settings.

| Message | Fix |
|---|---|
| `lock track needs a name, a title in quotes and a file, e.g. lock track main_theme "Main Theme" file "music/main_theme.ogg".` / `this line has "loud" left over. lock track takes a name, a title, file "…", then open or until and endings, in that order.` / `until needs 1 to 32 ending names, e.g. until good, true.` | Write the line in that order. |
| `lock track main_theme "Main Theme" declares a music-room track, so it goes at the top level.` / `there is no unlock track: a track opens when the story plays its music. Add open or until to its lock track line to open it another way.` | Declare tracks at the top level; use `open` or `until` instead of an unlock line. |
| `the track title is empty.` / `the track title has 75 characters; keep it to 60.` / `track titles are shown as written, so they can't use text tags such as {b}. Write {{ for a "{".` | Plain titles of 1–60 characters. |
| `there are two tracks named "festival": here and at database.vns, line 4. Give each track its own name.` / `tracks festival and night_walk both play "music/festival.ogg". Put each file in the music room once.` / `this story has 230 music-room tracks; the engine allows 200.` | One line per name and per file; up to 200 tracks. |
| `until names endings, but there is no ending "ture". Did you mean "true"?` | Use the name of an `ending` line. |
| `track festival plays "music/festval.ogg", but there is no such file in audio/. Did you mean "music/festival.ogg"?` (warning, dev runs) | Fix the file name, or add the file. |
| `track festival opens when the story plays "music/festival.ogg", but no play music or queue music line plays it, so players never get it. Add open or until, or play it in the story.` (warning, dev runs) | Play the file somewhere in the story, or add `open` or `until`. |

### lock replay (scene replays)
```
default coins = 0
default player_name = "Aiko"

lock replay festival "The Festival"
lock replay river "By the River" image cg river to fireworks:
    coins = 3
    player_name = "Aiko"
```
```
label letter:
    "Hana's letter said she still went to the river every summer."
    unlock replay river

label start_over:
    lock replay festival
```

**Scenes** is a page of **Extras**, on the title screen, where players watch a scene again.
A **replay** plays the scene as a throwaway game and then goes back to Extras: it never
changes the player's saves or progress. Nothing can be saved or loaded during it, and
endings, tips, gallery pictures, seen lines and `persistent` values reached in it are put
back afterwards.

**Declare** each replay once at the top level of any file: **`lock replay scene "Title"`**,
then optionally `image` and `to`, in that order.
- **Scene**: the label the replay starts at. Each scene has one replay; up to 500.
- **Title**: plain text, 1–60 characters, shown under the scene's square. No `{b}` or
  `{var}` (write `{{` for a `{`).
- **`image picture`**: the picture on the square, named as for `show`. Without it, the
  square shows the first picture a `scene` line shows in the label's own lines.
- **`to scene`**: where the replay stops. Without it, the replay ends when the story leaves
  the scene: a `jump` to another label, or the scene's own lines end or `return` (a `call`
  from it comes back and goes on). With it, the replay ends when the story reaches that
  scene. It always ends after an `ending`'s card or at the story's end.
- **Starting values**, indented under the declaration (end the line with `:`), one per line,
  up to 32: `name = value` for a variable made with `default` (not `persistent.`), with a
  number, text in quotes, `True`, `False`, or `None`. A replay starts with every variable at
  its `default` value, then sets these.

The Scenes page lists the replays in the order of their lines (files in `include` order).
**A replay unlocks when the player first reaches its scene** in a normal game, by a `jump`,
a `call`, a choice, or New Game; there is nothing else to write. Loading a save, rolling
back, and jumping from the Flowchart page unlock nothing. **Unlocks are kept across
playthroughs**; players reset them with "delete persistent data" in Settings.

**Inside a label**, **`unlock replay scene`** unlocks a replay without playing the scene,
and **`lock replay scene`** (no title) makes the game forget it, so its square is locked
again. Neither line waits.

**The Endings page.** Extras also has an **Endings** page: every `ending` of the story in the
order of its lines, the reached ones by heading and title, the rest `???`, under a count
("Endings reached: 2 / 5"). Picking a reached ending replays it: the label holding the
`ending` line plays from its first line, as a replay. If a `lock replay` line declares that
label, its `to` and starting values apply there too. Each page shows once it has something
to show (a reached ending, an unlocked replay), and the **Extras** button with it.

| Setting | Default | What it changes |
|---|---|---|
| `[endings] list` | true | false: no Endings page in Extras |
| `[endings] replay` | true | false: the Endings page lists endings but doesn't replay them |

**During a replay** the game menu works as usual, with these differences:
- **Nothing is saved or loaded.** Save and Load leave the game menu and the quick menu (so
  does the Flowchart), F5, F9 and the auto-saves do nothing, and `ui saving on` and `ui
  loading on` don't change that.
- **Main Menu reads End Replay** and goes straight back to Extras, with no question: nothing
  can be lost.
- **Progress is put back** when the replay ends, however it ends: endings, routes, tips,
  gallery pictures, seen lines and choices, the title's looks, and `persistent` values are as
  they were before it, and the persistent file isn't written meanwhile. Two things are kept:
  music-room tracks heard and achievements earned in a replay (their notices showed). Changes
  in Settings are kept too; Settings' "delete persistent data" is off.
- **The player's files and saves are safe.** `file write`, `file delete` (section 23) and `ui
  delete saves` (section 26) are skipped, with a warning in dev runs (below); `file read` and
  `file exists` work. Text on the screen is the story's as usual: `{var=…}` shows the
  starting values.
- Rollback, skip, auto and History work; rolling back stops at the replay's first line.

When the replay ends (by its own rules above, an ending's card, or End Replay), its sound
stops, the screen fades to black, and Extras comes back on the page it was started from.

To try a replay while you work, run **`python -m engine run game --replay scene`** (dev runs
only): the scene's replay starts at once, with no title (a `lock replay` of it gives its `to`
and starting values; any label works), and the game closes when it ends. It can't be used
with `--start`, `--extras` or `--try-stdin`. Studio's Database, "Scene replays", has a Play
replay button that does the same.

**Words**: `endings` "Endings", `endings_count` "Endings reached", `ending_locked` "???",
`ending_replay` "Replay", `replays` "Scenes", `replay_end` "End Replay", and
`replay_no_saving` "Saving and loading are off during a replay.", each changed under
`[words]`. The Endings page uses the `list.*`, `button.*` and `panel.*` settings; the Scenes
page uses the gallery's squares.

`replay` and `to` are still free as names: they mean something only right after `lock
replay` or `unlock replay`.

| Message | Fix |
|---|---|
| `lock replay needs a scene name and a title in quotes, e.g. lock replay festival "The Festival".` / `this line has "slowly" left over. lock replay takes a scene name, a title in quotes, then image and to, in that order.` / `to needs a scene name, e.g. to fireworks.` / `only starting values can go under a replay, one per line, e.g. coins = 3.` | Write the line in that order, with only starting values indented under it. |
| `lock replay festival "The Festival" declares a scene replay, so it goes at the top level. To make the game forget it during the story, write lock replay festival with no title.` / `unlock replay goes inside a label, because it runs when the story reaches it.` | Declare at the top level; put `unlock replay` and `lock replay` lines in a label. |
| `the scene "festival" has two replays: here and at extras.vns, line 4. Give each scene one replay.` / `this story has 520 replays; the engine allows 500.` | One replay per scene; up to 500. |
| `the replay title is empty.` / `the replay title has 75 characters; keep it to 60.` / `replay titles are shown as written, so they can't use text tags such as {b}. Write {{ for a "{".` / `this replay has 40 starting values; keep it to 32.` | Plain titles of 1–60 characters; up to 32 starting values. |
| `there is no scene "festivl". Did you mean "festival"?` / `to festival names the replay's own scene. Name the scene where the replay should stop, or leave out to.` / `there is no replay of "festivl". Did you mean "festival"? Declare it at the top level, e.g. lock replay festivl "Title".` | Use the name of a label, and a declared replay in `unlock replay` and `lock replay` lines. |
| `coins isn't a story variable. Starting values are for names made with default, e.g. default coins = 0.` / `a starting value is a number, text in quotes, True, False, or None, but this has "coins + 1".` / `coins has two starting values here; keep one.` | Give each `default` variable at most one plain value. |
| `file delete "hana.chr" doesn't run during a replay, so the player's files stay as they are.` (`file write` likewise) / `ui delete saves doesn't run during a replay, so the player's saves stay as they are.` (warning, dev runs, once per line) | Nothing to fix: the line runs as usual outside replays. |

### lock achievement (achievements)
```
lock achievement first_steps "First Steps" "Finish the prologue." image achievements first_steps
lock achievement garden "Secret Garden" "Find the hidden garden." hidden
lock achievement completionist "Completionist" "See every ending." when "good" in persistent.endings and "true" in persistent.endings
```
```
label prologue_end:
    "The lanterns go out one by one."
    unlock achievement first_steps
```

**Achievements** reward players across playthroughs. When the player earns one, a notice
shows at the top right, "Achievement unlocked: First Steps", with its picture; the
**Achievements** page of **Extras**, on the title screen, lists them all with a count
("Unlocked: 3 / 12").

**Declare** each achievement once at the top level of any file (Studio writes them into
`database.vns`): **`lock achievement name "Title"`**, then optionally a description,
`image`, `hidden` and `when`, in that order.
- **Name**: a name as in section 6. The game remembers an earned achievement by its name.
  Up to 200 achievements.
- **Title** and **description**: plain text in quotes, shown in the notice and the list: a
  title of 1–60 characters, a description of up to 200. No `{b}` or `{var}` (write `{{` for
  a `{`).
- **`image picture`**: the achievement's picture, named as for `show` (a square picture, 64 ×
  64 or larger, looks best). Without it, the list shows a plain square.
- **`hidden`**: until it is earned, the list shows "Hidden achievement" instead of its title
  and description. Once earned, it shows them as usual.
- **`when condition`**: the achievement unlocks by itself as soon as the condition is true.
  The condition is Python, written as for `if`, and runs to the end of the line. It is
  checked at every line and choice and once when the story ends, so it can test what the
  story did: `persistent` values (section 9), the endings reached (`"good" in
  persistent.endings`), variables. Up to 64 achievements can have `when`, each condition up
  to 500 characters. A condition that fails (a typo in a name, for example) gives a warning
  and isn't checked again until the game restarts; the story goes on.

**Inside a label**, **`unlock achievement name`** gives the achievement to the player. It
doesn't wait; the notice shows over the story. Giving one the player already has does
nothing. **Achievements are kept for good**: there is no `lock achievement` inside a label,
New Game keeps them, and only "delete persistent data" in Settings takes them away.

Two achievements earned at the same moment show two notices, in the order of their lines.
Achievements earned while players watch a scene again (scene replays, above) are kept, and
their notices show.

The **Extras** button (and the Achievements page in it) shows once at least one achievement
is earned. To try the page while you work, run `python -m engine run game --extras
achievements` (dev runs only): every achievement counts as earned, and nothing is saved.

The example game has four achievements: "Sharp Eyes" (an `unlock achievement` line when the
lantern game is won in 10 turns or fewer), "Set Adrift" (an `unlock achievement` line at the
lantern release, with the lantern's picture), "Two Ways Home" (`when "sad" in
persistent.endings and "good" in persistent.endings`), and "A Promise Kept", `hidden`, given
by the promise route.

A game sold on a store such as Steam can also tell the store about each achievement with a
**platform hook**, a small Python plugin: see docs/minigames.md, "Achievement hook".
Achievements always work without one, and the engine itself never uses the network.

**Words**: `achievements` "Achievements", `achievement_unlocked` "Achievement unlocked",
`achievements_progress` "Unlocked", `achievement_hidden` "Hidden achievement", and
`achievement_hidden_text` "Keep playing to unlock it.", each changed under `[words]`. The
page uses the `list.*` and `button.*` settings; the notice uses the notice's.

`achievement`, `hidden` and `when` are still free as names: they mean something only right
after `lock achievement` or `unlock achievement`.

| Message | Fix |
|---|---|
| `lock achievement needs a name and a title in quotes, e.g. lock achievement first_steps "First Steps" "Finish the prologue."` / `this line has "now" left over. lock achievement takes a name, a title, a description, image …, hidden, then when and a condition, in that order.` / `when needs a condition, e.g. when "good" in persistent.endings.` | Write the line in that order. |
| `lock achievement first_steps "First Steps" declares an achievement, so it goes at the top level. To give it to the player, write unlock achievement first_steps.` / `achievements can't be taken back, so lock achievement first_steps can't go in a label.` / `unlock achievement goes inside a label, because it runs when the story reaches it.` | Declare at the top level; put `unlock achievement` lines in a label. |
| `the achievement title is empty.` / `the achievement title has 75 characters; keep it to 60.` / `the achievement description has 230 characters; keep it to 200.` / `achievement titles and descriptions are shown as written, so they can't use text tags such as {b}. Write {{ for a "{".` | Plain titles of 1–60 characters, descriptions up to 200. |
| `the condition after when isn't valid Python: "(" was never closed.` / `the condition has 620 characters; keep it to 500.` | Fix the condition as for `if`; keep it under 500 characters. |
| `there are two achievements named "first_steps": here and at database.vns, line 9. Give each achievement its own name.` / `this story has 230 achievements; the engine allows 200.` / `this story has 70 achievements with when; the engine allows 64.` | One line per name; up to 200 achievements, 64 with `when`. |
| `there is no achievement "first_step". Did you mean "first_steps"? Declare achievements at the top level, e.g. lock achievement first_step "Title".` | Use the name of a declared achievement. |
| `achievement first_steps has no when condition and no unlock achievement line names it, so players never get it.` (warning, dev runs) | Add an `unlock achievement` line, or `when`. |
| `achievement completionist's when condition failed (NameError), so it isn't checked again until the game restarts.` (warning, once per achievement) | Fix the condition; the story goes on meanwhile. |

### flowchart (the story map)
```
lock route promise "Hana's Promise" until sad, good

label festival:
    chapter festival "Chapter 2" "The Lantern Festival"
    hana "You made it! They light the river lanterns at nine."
    jump stall

label stall:
    flowchart scene "Daichi's Stall"
    daichi "Red's the lucky colour this year. Or so I tell everyone."
    menu:
        "Buy the red one" if coins >= 2:
            $ coins -= 2
        "Just look":
            $ pass
    hana "Come on, the good spots are filling up."
    flowchart "Where should we watch the lanterns?"
    rollback fixed
    menu:
        "By the river":
            jump river
        "From the shrine steps":
            jump shrine
        "Wait at the bridge" if "promise" in persistent.routes:
            jump promise

label promise:
    flowchart scene "The Promise" hidden no jump
    hana "You remembered. Even after everything."
    flowchart hidden
    ending true "True End" "Lanterns on the Water"
```
```
label second_act:
    flowchart forget
    lock ending sad
    lock ending good
    "The festival grounds are empty. Were they ever full?"
```

The **Flowchart** page draws your story as a map, left to right. Players see where they have
been and `???` for what they haven't found yet, and they can **jump** back to any point they
have reached, with the story as it was then. They open it from the game menu (Esc), and from
the title screen once there is a point to jump to.

You get it with no extra lines. These are boxes on the chart:
- every `chapter` and every `ending`;
- a menu whose choices lead to different boxes. A small-talk menu whose choices join up
  again, like the stall's first menu above, isn't one;
- a padlocked gate for each route `lock route` keeps closed, ticking off its `until` endings;
- a Start box, when the story shows something before its first box.

A path out of a menu is labelled with its choice's text as plain text: a `{var=…}` in it
shows as `…`, never as a value, and its `if` condition never shows. Labels without a box are
passed through, so a path follows a `jump` or `call` to a plain label.

Every other choice about the chart is a line that starts with **`flowchart`**:
- **`flowchart scene "Title"`** as the first line of a label makes that label a box with
  this title. Use it for a scene players will want to find again.
- **`flowchart "Title"`** right above a `menu:` puts the menu on the chart with that title,
  whatever `[flowchart] menus` says. A plain `flowchart` uses the menu's question as the
  title. **`flowchart omit`** leaves a menu off the chart. A `rollback fixed` line may sit
  between the mark and its `menu:`.
- **`hidden`** after either line, or **`flowchart hidden`** right above a `chapter` or
  `ending`, keeps that box and its paths off the chart until the player reaches it. Use it
  for secret routes and the true ending. A locked route's boxes are hidden anyway until it
  opens; `hidden` keeps them hidden after that, until they are reached.
- **`no jump`** after a scene or menu line, or `flowchart no jump` right above a `chapter`,
  means players can't jump to that box (its panel says "You can't jump to this point."). Use
  it for scenes that must be played in order. Endings are never jump targets.
- **`flowchart forget`** makes the game forget the whole chart: each box goes back to `???`
  and its jump point is deleted. **`flowchart forget stall`** forgets only the boxes written
  in label `stall`: its scene, and the chapters and menus in it, not the labels it jumps to
  or calls. Endings follow their own records, so forget them with `lock ending`. Forgetting
  happens at once, and loading a save or rolling back doesn't undo it.

Titles are plain text of 1 to 120 characters, with no `{b}` or `{var}` (write `{{` for a
`{`). A `flowchart` line never changes what it marks, so adding, retitling, or removing one
keeps every player's chart and jump points.

**A jump** loads the story as it was when the player last reached that box: the scene, the
music, story variables, items, meters, and history, as loading a save does, and rollback
starts again from there. It keeps everything the game remembers across playthroughs:
endings, routes, tips, read lines, and the chart itself. A menu offers the choices allowed
*now*, so a route opened since then is offered: its conditions run again, on the story
variables of that moment and today's persistent data, as `default`s do when a save loads. In
the game a jump asks first and, with `[saves] autosave_quit`, makes an Auto save of where
the player was; from the title it asks nothing. Saves are never changed.

**Jump points are files.** Each box's jump point is a copy of the story state, kept in the
game's saves folder next to the saves (`node-….vnnode` files, up to 256 MiB in all).
**Delete progress** in Settings and `flowchart forget` delete them; deleting saves doesn't.
When a point couldn't be kept (no room, a folder that can't be written), its box says "Reach
this point again to jump here."; when the story has changed so much that the point no longer
fits, "This part of the story has changed.".

**Settings in `config.toml`**

| Setting | Default | What it changes |
|---|---|---|
| `[flowchart] enabled` | true | false: no Flowchart page (`flowchart` lines are still checked) |
| `[flowchart] menus` | `"branching"` | `"all"`: every menu is a box; `"marked"`: only menus with a `flowchart` line |
| `[flowchart] unvisited` | `"mystery"` | `"hidden"`: boxes not reached yet aren't drawn, so the chart grows as it's explored |
| `[flowchart] jump` | true | false: a map only, with no Jump button |

The page's colours and sizes are the `flowchart.*` tokens of the UI system, set in
`[theme.flowchart]`; its words (`flowchart`, `flowchart_jump`, `flowchart_no_jump`,
`flowchart_var`, and the rest) are changed under `[words]`.

The example game marks the lantern stall as a scene, titles the bridge's last menu "How
should the night end?", and hides the promise route's scene and the True End.

| Message | Fix |
|---|---|
| `"hiden" isn't a flowchart word. Did you mean "hidden"? A flowchart line takes a title in quotes, hidden, no jump, scene, omit, or forget.` / `flowchart scene needs the scene's title in quotes, e.g. flowchart scene "Daichi's Stall".` | Fix the spelling. The title comes right after `flowchart` (or `flowchart scene`), then `hidden` and `no jump`. |
| `flowchart scene must be the first line of label stall, so the flowchart knows where the scene starts. Move it above line 12.` / `flowchart lines go inside a label, next to the scene, menu, chapter, or ending they mark.` | Move it to the top of its label. |
| `a flowchart line marks the menu, chapter, or ending right below it, but the next line here is a line of dialogue (line 31). Move it right above the menu:.` / `a flowchart line above a chapter takes only hidden and no jump, because the chapter line gives the title. Remove "Festival Night".` | Put it right above the `menu:` (a `rollback fixed` may sit between). Above a chapter or ending, write only `hidden` or `no jump`. |
| `the flowchart title has 140 characters; keep it to 120.` / `flowchart titles are shown as written, so they can't use text tags such as {b} or {var}. Write {{ for a "{".` | Plain text, 1–120 characters. |
| `there is no label named "rivr". Did you mean "river"? flowchart forget takes a label name, or nothing to forget the whole flowchart.` | Name a label, or write `flowchart forget` alone. |
| `this story's flowchart has 3,204 boxes; the engine allows 3,000. Leave small menus off with flowchart omit, or set [flowchart] menus = "marked".` | Up to 3,000 boxes and 10,000 paths. |
| `scene "Old Ending" (label old_ending) can't be reached from the start of the story, so it stays ??? on the flowchart for every player. Add a jump or call that leads to it, or remove its flowchart line.` (warning, dev runs) | Jump to it, or remove the line. |
| `the flowchart can't tell where this line goes, so it draws no path from here. The story still plays; use jump or call with a label name to draw the path.` (warning, dev runs) | Use `jump` or `call` with a label name where the chart should follow. |
| `this choice's text is only {var=lantern_color}, so its path on the flowchart reads "…". Add a word or two, e.g. "Buy the {var=lantern_color} one".` (warning, dev runs) | Add words around the `{var}`. |
| `flowchart forget stall does nothing, because label stall has no flowchart boxes in it. Add flowchart scene "Title" as its first line, or name another label.` (warning, dev runs) | Mark a box in that label, or name another. |
| `the flowchart state for scene:stall is too large to keep, so this point can't be jumped to.` (warning, dev runs, while playing) | The story state there is over the save size limit (see "Saves"); the box keeps no jump point. |
| `couldn't jump to scene:stall: no state is kept for it` (warning, dev runs, while playing) | The point's file is missing or damaged, or the story changed; reaching the box again makes a new one. |

### points
See [points (character stats)](#points-character-stats) in section 9.

### nvl (full-screen text)
```
    scene bg river_dusk
    nvl on
    "The festival comes once a year, on the night the river runs slowest."
    "Every family folds a lantern. Mine never floated."
    hana "You're thinking about last year again."
    nvl clear
    "Three days later, the letter came."
    nvl off
    hana happy "Come on, the stalls are opening!"
```

`nvl on` switches to **full-screen text**: a panel covers the scene, and each line is
added below the one before it, like a page in a book. `nvl off` goes back to the text box.
`nvl clear` starts a new, empty page. Use it for long narration, a letter, or a diary
entry; the scene stays visible through the panel.

- **Pages fill up by themselves:** when the next line doesn't fit, the page empties and
  the line starts at the top. Use `nvl clear` for a deliberate break, such as a time skip.
  A line too long for a whole page shows in parts, with a click between them, like a
  long line in the text box.
- **Lines work as usual:** dialogue and narration, names (on their own row above the
  text, in the character's color), expressions, `voice`, and every
  [text tag](#text-tags). Each line types, pauses, and waits for a click as in the text
  box.
- **Menus:** the question goes on the page like any line (a menu with no question keeps
  the last line), and the choices sit just under it, lined up from the top. If they don't
  fit under the page, the page shows only the question with the choices under it; if
  they still don't fit, they are centered over the page as usual. After a pick, the next
  line starts a new page.
- **Where it goes:** `nvl on`, `nvl off`, and `nvl clear` go on a line of their own,
  anywhere a story line can: in a label, under `if`, or inside a choice's block (not
  directly under `menu:`). Nothing else goes on the line, except a `#` comment.
- **Transitions:** the panel appears and goes at once. Put a transition on the `scene`
  line before `nvl on` instead (`nvl on with dissolve` is an error). During a
  `scene … with dissolve` in full-screen text, the panel hides and comes back, with its
  page, at the next line. A `scene` never clears the page.
- **Chapters:** a `chapter` card doesn't end the page or change the mode. To start the
  new chapter on a fresh page, write `nvl clear` after the `chapter` line.
- Every game starts with the text box. `nvl off` empties the page, so a later `nvl on`
  starts on an empty one.
- Saves, history, skip, auto, and rollback work as with the text box. Loading a save or
  rolling back shows the page as it was, already typed out.
- A page keeps its last 32 lines for loading and rollback. Write `nvl clear` at least
  every 32 lines (a dev run warns otherwise).
- **Looks** come from `[theme.nvl]` in `config.toml`. By default the panel matches the
  text box (`#FFF4F8` at 0.85 over the scene, the same font, size, and colors), so
  character colors that read in the text box read here too.

```toml
[theme.nvl]
fill_color = "#3a2a3f"        # the panel; without it, the text box's fill_color
fill_opacity = 0.9            # 0.5 to 1.0
text_color = "#fff4f8"        # without it, the text box's text_color
name.text_color = "#f0a0c0"   # names of characters with no color
indicator.fill_color = "#f0a0c0"
```

| Key | Default | Allowed |
|---|---|---|
| `fill_color` | the text box's (`"#FFF4F8"`) | `"#RRGGBB"` |
| `fill_opacity` | `0.85` | 0.5–1.0 |
| `width` | `920` | 640–1200; the text column, centered |
| `top_gap` | `64` | 24–200; the screen's top to the first line |
| `bottom_gap` | `72` | 40–200; the last line to the screen's bottom (keeps the quick menu clear) |
| `line_gap` | `20` | 0–80; the space between two lines |
| `text_size` | the text box's (`28`) | 20–48; the player's text size scales it |
| `text_color` | the text box's (`"#3D2B36"`) | `"#RRGGBB"` |
| `name.text_color` | the name plate's (`"#A02860"`) | `"#RRGGBB"` |
| `indicator.fill_color` | the text box's indicator (`"#A02860"`) | `"#RRGGBB"` |

**Dev-run warnings.** A line in full-screen text that needs more than one page gets the
long-line warning below instead of the text box's. The game decides which lines are in
full-screen text by reading each label from the top: a line counts when the nearest
`nvl on` or `nvl off` above it in the same label is `nvl on` (jumps and calls aren't
followed, and every label starts with the text box). When the script uses `nvl on`, the
`[theme.nvl]` colors are checked on the panel over a black and a white picture, and so is
every character's name color.

| Message | Fix |
|---|---|
| `nvl needs on, off, or clear after it, e.g. nvl on.` / `nvl takes on, off, or clear, but this has "of". Did you mean "off"?` / `write nvl on in lower case.` | Write `nvl on`, `nvl off`, or `nvl clear`, in lower case. |
| `nvl on takes nothing else on its line, but this has "now".` / `full-screen text appears instantly, so nvl on can't take "with dissolve". Put the transition on the scene line before it.` / `nvl doesn't start a block, so it takes no ":". Write nvl on, then the lines under it at the same indentation.` | Put anything else on its own line; put transitions on the `scene` line before it. |
| `this full-screen line needs 2 pages at text size 28, so the player clicks once partway through. To choose where it breaks, split it into two lines.` (warning) | Split the line. |
| `33 lines have gone by in full-screen text since the last nvl clear, so the oldest isn't kept for loading and rollback, and a page restored here may start at a different line. Add nvl clear where a new page should begin.` (warning) | Add `nvl clear` at page breaks. |
| `config.toml: [theme.nvl] text_color #A0A0A0 on fill_color #FFF4F8 at fill_opacity 0.85 gives 1.7:1 over a black picture; full-screen text needs at least 4.5:1. Pick colors further apart.` (warning; also for `name.text_color` and `indicator.fill_color`, which need 3:1) | Pick colors further apart, or raise `fill_opacity`. |
| `rin's color #C060A0 gives 2.5:1 on the full-screen text panel ([theme.nvl]); names need at least 3:1. Pick a darker color, or change [theme.nvl] fill_color.` (warning) | Pick a darker color for her, or change the panel. |

The example game's prologue opens in full-screen text, with one `nvl clear` and one
`nvl off`.

### minigame
```
default turns = 0

label lantern_stall:
    hana "First to find all the pairs wins a lantern!"
    minigame lantern_memory pairs=6 into turns
    if turns <= 10:
        hana happy "Only {var=turns} turns? You're good at this!"
```

Starts a minigame (a small game such as a memory board or a poem builder) and waits until
the player finishes it, then goes on with the next line. Minigames come with the engine,
or from Python plugins in `game/minigames/`; [minigames.md](minigames.md) has the ones that
come with the engine and "Writing a minigame".

- **Name** first, exactly as the plugin names it.
- **Arguments** as `name=value`, e.g. `pairs=6` or `hints=points.hana >= 3`. Values are
  worked out when the line runs, like a condition, and must be values a variable could hold.
  Misspelled or missing arguments are caught when the game starts.
- **`into turns`** keeps the result in a variable, which needs a `default`. Without `into`
  the result is dropped. Meter and codex changes the minigame makes happen together with
  it, just before the next line.
- **`skippable`**, right after the name, lets players skip this minigame from the game menu
  (if the minigame supports it).

Esc opens the game menu as usual. A save made during a minigame starts it again from the
beginning, and rolling back to it lets the player play it again, like a choice. Random
layouts come out the same each time.

**Phone chats.** When a `minigame phone_chat` closes, the messages the player saw join the
history log (the contact's under the sender's name, the player's as choice rows), and the
whole chat stays on the game menu's **Inbox** page to read again, in the contact's thread,
with a dot until it is opened there. The Inbox is saved and rolled back with the story. See
"Reading a chat again" in [minigames.md](minigames.md), and "Messages" below for letters and
messages contacts send while the story goes on.

**Shops.** `minigame shop stock=stall_stock into bought` opens a shop where the player buys
items with the story's money (the item marked `money`). The stock is a `define` of items and
prices: `define stall_stock = {"tea": None, "matches": [1, 10], "lantern": 20}` sells tea at
its own `price`, matches at 1 each (10 for sale this visit) and the lantern at 20.
`bought` gets what was bought, such as `{"tea": 2}`. Money and items change when the player
leaves, together with the result. [minigames.md](minigames.md), "Shop", has the details and
Studio's Shop table.

**Testing.** A headless run uses each minigame's test outcome, or one you give in the
inputs: `finish 9`, or `finish 9; points hana += 1`. In a dev run, Shift+F8 ends a
minigame with its test outcome.

| Message | Fix |
|---|---|
| `there is no minigame named "lantern_memroy". Did you mean "lantern_memory"?` | Fix the spelling, or add the plugin. |
| `there is no default named "turn" for the result. …` | Add `default turns = 0`, or fix the name after `into`. |
| `lantern_memory has no argument "pair". …` / `minigame lantern_memory needs a value for pairs. …` | Use the plugin's argument names. |
| `write pairs=6, with = between the argument and its value.` | Write `name=value`. |
| `minigame is a statement, not Python, …` | Remove the `$` and write `minigame … into …`. |
| `minigames/stargazing.py, line 12: this minigame plugin has a Python mistake: …` (E273) | Fix the plugin. |
| `two minigame plugins use the name "stargazing": …` (E274) | Rename one of them. |
| `minigames/stargazing.py needs minigame API 1.4, but this engine has 1.1. …` (E278) | Update the engine, or use a version of the plugin made for this one. |
| `minigames/my_poems.py replaces the bundled minigame "poem_game", …` (warning, dev runs) | Rename yours to keep both. |

Errors while a minigame runs (E272 and E275–E279) are in section 22.

### Messages

Letters, texts and transmissions that arrive while the story goes on, and stay in the
**Inbox** to read again. Three lines do it: `lock contact` says who writes, `send` delivers a
message, and `open` stops the story at the Inbox.

```
lock contact hana "Hana" on pigeon image hana portrait
lock contact ren "Ren"

define invite = [
    "Meet me at the bridge when the lanterns are lit.",
    "Bring the red one. You'll see why.",
    ]
define late = "Running late, save me a seat!"

label morning:
    send invite from hana
    "I went down to breakfast."
    send late from ren
    open pigeon
    "I folded the note into my sleeve."
```

**Contacts.** `lock contact <name> "shown name" [on <look>] [image <picture>]` goes at the
top level of a file, like `lock tip`. The name is what the script uses (`from hana`); the
shown name (1 to 40 characters) is what the Inbox and the notices say. `on` picks the
device look their messages come by: `phone`, `letter`, `pigeon`, `radio`, `terminal` or
`mind` (`letters`, the spelling from before version 1, still works, with a warning).
Without it, the kit's look is used (`[theme] kit`: Fantasy sends pigeons, Letters sends
letters, Sci-fi a terminal, Horror a voice in your head), else a phone. `image` is a
picture name for the contact's thread and their notices. A contact has no thread until
they send something; there is no `unlock contact`.

**Messages.** A message is a `define` (or a `default`) of one text, or of a list of lines
in the phone chat's format:

- `"Meet me at the bridge."`: a line from the contact.
- `{"me": "I'll be there."}`: a line the player wrote (shown as "You: …").
- `{"time": "Day 3"}`: a divider.
- `{"Ren": "Hana told me too!"}`: a line from someone else.

A message has 1 to 200 lines of up to 2,000 characters. Its last line may ask for a reply
(see **Replies** below). The value is read when the message arrives, so a `default` the
story changed sends its new text.

**send.** `send <message> from <contact>` puts the message in the contact's thread. `send
invite from hana on letter` sends this one by another look, `after 1 day` holds it for a
while (see **Delays**), and `ask "Yes" "No"` lets the player answer (see **Replies**); they
can come in any order after the contact. The player sees:

- A notice, worded by the look: "A pigeon lands on the sill with a note from Hana.", "A
  letter from Hana has arrived.", "New message from Ren.", "The radio crackles. It's
  Ren.", "Incoming transmission from Ren." or "Hana's voice, inside your head." The
  contact's picture is its icon.
- An **Inbox** button in the quick menu (after History) in any game with a `send` line,
  and the Inbox in the game menu, both with the number not read yet: "Inbox (2)". With a
  kit, the button takes the kit's name for the page: "Pigeon post (2)", "Letters (1)".
- One row per contact on the Inbox page, the most recent first, with a dot until it is
  opened. The right side shows the contact's messages, newest first, each under a line
  saying how it came ("Arrived by pigeon · Day 3"; the date when the game uses the story
  clock). Letters, pigeons and voices read as a letter, signed "— Hana"; phones, radios
  and terminals as chat lines, "Ren: Running late". A finished phone chat joins the thread
  of the contact whose shown name it uses.

**Device looks.** Each look also draws its messages its own way, in the game's colors
(every color scheme keeps the text readable):

- **phone**: chat bubbles, the contact's on the left and the player's on the right.
- **letter**: a paper card, the line above it centred, signed at the bottom right; the
  line above and the signature are in a serif italic.
- **pigeon**: a smaller note tied with twine, with a wax seal, headed and signed like a
  letter.
- **radio**: a transcript with "[signal]" and a line of static under the heading.
- **terminal**: green text on a dark screen, in a monospaced font, with a block cursor.
- **mind**: no frame, the words in italics in a soft glow.

The arrival notice wears the same look (a phone's bubble, a letter's stamp, a pigeon's
seal, static, a green screen, a glow, a thought's words in italics). The serif and
monospaced fonts come with the engine (Noto Serif, Noto Sans Mono); a game that sets its
own `[theme.textbox] text_font` keeps that font in every look instead. With **Reduce motion** on, the static, the cursor
and the glow stay still.

`[device.<look>]` in config.toml changes how a look words and sounds a message. Every key
is optional; Game settings ▸ Devices writes them for you:

```toml
[device.pigeon]
name = "Pigeon Post"                        # names the Inbox when it is the game's device
arrive_text = "A grey bird lands on the sill."   # the notice; {name} is who sent it
arrive_sound = "sfx/wings.ogg"              # plays once when a message arrives
header_text = "By wing"                     # the line above each message
reading = "letter"                          # or "chat"
```

The sound plays once, at the player's sound volume, when the message arrives; not when
going back and forward again, not during a scene replay, and not while skipping. A
`[device.…]` name that isn't one of the six looks is a warning that suggests the closest.
An `arrive_sound` that names no file in `audio/` is a warning too (W317), listed by the check
and in Studio's Problems.

A `send` is a story step: a save keeps what arrived, going back before the line takes the
message out again, going forward brings it back (without a second notice), and New Game
empties the Inbox. Whether a thread was opened is remembered across saves and
playthroughs, like the codex's dots.

**Delays.** `send invite from hana after 1 day` holds the message until the story clock
reaches the next day (see [clock](#clock-story-time): `clock next day`, or `clock next`
past the last part of the day); `after 3 days` waits three. `after 2 scenes` holds it
until the story has entered two more scenes (a `jump`, a `call`, or a scene's start;
coming back from a `call` doesn't count). `after 2 parts` holds it for two parts of the day
(`[calendar] parts`), counted across days: sent in the evening of a day with Morning,
Afternoon and Evening, it arrives the next afternoon. Parts count as time passing, so a
`clock` line that skips parts passes them too: `clock next day` from the morning passes the
rest of that day, so `after 1 part` sent in the morning arrives with the next morning, and
`clock go to Night` arrives anything due by then. Going back to an earlier day with `clock
go to day 1` passes nothing; the message waits until the clock comes forward to its time
again. Then it arrives as if sent there: the arrival
notice shows, the date is the day it arrived, and the message's text is read then. While
it waits, a save keeps it on its way, going back before the `send` line takes it back,
and going forward brings it again without a second notice. Running the same `send` line
again before the message arrives starts its wait again. A save knows a message on its way
by its contact and message (and, for a second line sending the same, which one), not by
the line, so an update may change the line's `on`, `after` or `ask`, move it, or rename its
scene, and the message still arrives at its saved time. If the update removes every line
sending that message from that contact, the save keeps it waiting but it never arrives (a
dev run's log says so). In a dev run, F3 lists the
messages still on their way ("message invite from hana: day 3", "message late from ren: day
2, Afternoon").

```
label morning:
    send invite from hana after 1 day
    "I went down to breakfast."
    clock next day
    "Morning came, and with it a grey bird."
```

**Replies.** A message can end with a question the player answers in the Inbox, when they
like. Write the replies as its last line, in the phone chat's shapes:

```
define invite = [
    "Meet me at the bridge when the lanterns are lit.",
    {"ask": "come", "yes": "I'll be there.", "no": "Not this year."},
    ]
define tea = ["Tea at four?", {"ask": ["Yes please", "No thanks"]}]
```

With a name (`"come"`) each reply has an id (`yes`, `no`) and its text; with a list each
text is its own id. A message offers 1 to 4 replies of up to 80 characters on one line, all
different, and asks once, at its end. A phone chat's `"ignore"` is allowed and does nothing:
any message can stay unanswered. A reply is one text: to answer back, send another message
(`if inbox.reply("invite") == "yes":` / `send see_you from hana after 1 scene`). The `send`
line can also give the replies itself: `send late from ren ask "On my way." "Start without
me."` (each text its own id), for a message without an ask of its own.

On the Inbox page the replies are buttons under the message (each message that asks has
its own, so a thread can wait on two questions at once), and the thread has a ring beside
its dot until every one is answered. A long reply wraps to two lines in its button; past
that it is cut with "…", and the whole text shows while the button is focused. The
player's pick shows under the message as their line ("You: I'll be there.") and in
History as a choice. It counts like a choice: a reply
made while a line waits is a step of its own, so Back once takes the reply back on the
same line, and going forward gives it again; a reply made while `open` waits joins the next
step. A save keeps it. At a menu the buttons wait until the choice is made.

The story reads the answer with `inbox.reply("invite")`: the id of the reply picked (`"yes"`;
for a list, its text), or `""` before one. When the same message was sent more than once,
it is the newest answer.

```
label festival_eve:
    if inbox.reply("invite") == "yes":
        jump bridge
    elif inbox.reply("invite") == "":
        "Her letter still waits on my desk."
```

`inbox` can only be read. A game's own variable called `inbox` hides it. The story map
treats `inbox.reply("invite")` like a variable that each `send invite` may change.

**open.** `open inbox` opens the Inbox on the newest thread, and the story waits until the
player closes it; then the next line runs. `open pigeon` (or any look) opens it on the
newest thread that something came to by that look. While skipping, the story goes past
`open` without stopping; a headless run passes it too.

**Words.** `send` and `open` are statements only at the start of a line with a name after
them: `send "On my way."` and `open "Come in."` stay dialogue by characters called send and
open, and both stay free as variable names. `contact` is a word only after `lock`; `from`,
`on` and `inbox` only in these lines.

| Message | Fix |
|---|---|
| `send invite needs from and a contact after it. …` | Write `send invite from hana`. |
| `write the contact's name without quotes: send … from hana. …` | Use the contact's script name, not its shown name. |
| `there is no device look called "pigon". Did you mean "pigeon"? …` | Use phone, letter, pigeon, radio, terminal or mind. |
| `open opens the Inbox, but "door" is not inbox or a device look. …` | Write `open inbox` or `open pigeon`. |
| `on letters is a spelling from before version 1. It still works for now, but write on letter instead.` (warning W323) | Write `on letter` (and `open letter`). Studio writes the new spelling. |
| `lock contact needs the contact's name and the name to show in quotes, …` | Write `lock contact hana "Hana"`. |
| `lock contact declares a contact, so it goes at the top level of a file, …` | Move it above the labels. |
| `there is already a contact called hana (line 3). …` | Give each contact its own name. |
| `there is no contact called hnaa. Did you mean "hana"? …` | Fix the name, or declare the contact. |
| `there is no define called invte to send. Did you mean "invite"? …` | Fix the name, or write the message as a define. |
| `line 2 of message invite asks for a reply, but more lines follow it. …` | Put the ask on the message's last line. |
| `line 2 of message invite asks for a reply, but it has 5 replies; a message offers 1 to 4. …` | Give 1 to 4 short replies. |
| `send … after needs a number and days, parts or scenes, …` | Write `after 1 day`, `after 2 parts` or `after 2 scenes`. |
| `send … ask needs 1 to 4 replies in quotes, …` | Write `ask "Yes" "No"`. |
| `this send line has replies (ask …), but message invite (line 3) asks for a reply too. …` (E455) | Keep the replies in one place. |
| `send invite … after 1 day waits for the story clock, but no clock line in this game moves it, …` (warning W312; also for `after 2 parts`) | Add a `clock next day` (or `clock next`) line, or use `after 2 scenes`. |
| `message … can never happen: after 9 days is past [calendar] last_day (5), …` / `… after 24 parts of the day is past [calendar] last_day (5), …` (warning W316) | Use a shorter delay, or a later `last_day`. |
| `inbox.reply("invte") reads the reply to message invte, but no send line sends it with replies, …` (warning W313) | Fix the name, or give the message replies. |
| `inbox.reply("invite") is compared with "maybe", which isn't one of its replies ("no" or "yes"), …` (warning W314) | Compare with one of its reply ids. |
| `message invite must be text, or a list of lines like a phone chat's, …` | Make it text or a list. |
| `[device.pigeon] arrive_sound "sfx/wngs.ogg" names no such file in audio/, …` (warning W317) | Add the file to `audio/`, or check the spelling. |
| `open pigeon opens the Inbox at the newest message that came by pigeon, but nothing in this game comes by pigeon. …` (warning) | Send something by that look, or write `open inbox`. |

A message whose value goes wrong while the game runs (a `default` changed into something
that isn't a message) stops the story at the `send` line (E453, section 22), and so does
`inbox.reply` given something other than a message's name, or a change to `inbox` (E454).

---

## 8. Characters

```
define daichi = Character("Daichi", color="#3a6aa8")
define narrator_box = Character("")          # no name plate
```

| Option | What it does |
|---|---|
| `"Daichi"` (first) | The name the player sees. `""` shows no name plate. |
| `color="#3a6aa8"` | The name's color: `#` and six digits or letters a–f. |
| `name_from="hana_name"` | Take the shown name from a story variable instead (below). |
| `image_tag="daichi"` | Which sprite the character's lines change, when it isn't the define name. See [Expressions on dialogue lines](#expressions-on-dialogue-lines). |
| `text_color="#1e4a9c"` | The color of the character's lines. See [Text style for a character](#text-style-for-a-character). |
| `text_italic=True` | The character's lines are in italics. |
| `blip="blips/hana.ogg"` | A short sound played as the character's lines type (below). |
| `blip_every=2` | Blip on every 2nd letter or digit: a whole number from 1 to 10 (default 2). |
| `blip_pitch=0.1` | Vary each blip's pitch by up to ±10%: 0.0 to 0.5 (default 0.0, as recorded). |
| `blip_volume=70` | The blip's loudness, as a percentage of the sound volume: 0 to 100 (default 100). |

**A name that changes.** To show `???` until a character introduces herself, give the
character `name_from` with the name of a `default`, in quotes, and change that variable:

```
define hana = Character(name_from="hana_name", color="#b03070")
default hana_name = "???"

label start:
    hana "Oh, sorry. I'm Hana."
    $ hana_name = "Hana"
    hana "He said you'd get lost at least twice."    # the plate now reads Hana
```

The new name shows from the next line, is saved with the game, and goes back if the player
rolls back. The history keeps the name each line was shown with. Use either a name or
`name_from`, not both. Characters are checked when the game starts: every name that speaks
must be a `Character`, and every option must be spelled right.

**Blips.** A blip is a short sound played as a character's line types, so players can tell
speakers apart by ear:

```
define hana   = Character("Hana", color="#b03070", blip="blips/hana.ogg", blip_pitch=0.1)
define daichi = Character("Daichi", blip="blips/low.wav", blip_every=3, blip_volume=70)
```

The file is inside the `audio` folder, written as in `play` (`"blips/hana.ogg"`, not
`"audio/blips/hana.ogg"`), and is `.ogg`, `.opus`, `.flac`, `.mp3`, or `.wav`. Only letters
and digits blip, in any language; spaces, punctuation, symbols, and emoji stay silent.
`blip_every=2` blips on the line's first letter, then on every 2nd one; each new line counts
from its first letter again, and a `{pause}` or a page break doesn't restart the count. So
at `blip_every=2`, `"You're late!"` blips on Y, u, e, a, and e.

Blips follow the text as it appears: none while the text waits at a `{pause}`, while the
text box is hidden or a menu is open, or after the player clicks to show the rest of the
line. At most one blip starts every 0.04 seconds, and a new blip cuts off the one before,
so text that appears all at once (`{speed=instant}`, a speed of 0, or the player's instant
text setting) blips once. With `blip_pitch=0.1` each blip plays at one of five pitches
from 0.9 to 1.1 times its recorded pitch; a higher one is also a little shorter.

Voiced lines, narration, and skipped lines don't blip, and neither does a line shown again
by rollback or by loading a save. Keep a pitched blip to half a second or less: a longer one
plays at its recorded pitch, with a warning. `blip_every`, `blip_pitch`, and `blip_volume`
need `blip` in the same `Character(...)`. A missing file is a warning at the define, and a
file that can't be played is a warning the first time it is needed; either way the game
plays on without the blip. The example game gives Hana a bright blip with `blip_pitch=0.1`
and Daichi a lower, quieter one (`script/main.vns`, `game/audio/blips/`).

---

## 9. Story variables

A name set by a `$` line or a `default` is a **story variable**. Every later `$` line and
condition can use it, in every label and file. It is saved with the game and rolled back.
Labels and `call` don't make separate variables.

**What Python can see:** story variables, defined names, `Character`, `dice`, `module`,
`persistent` and `points` (below), `codex` (see [lock tip, lock item,
unlock](#lock-tip-lock-item-unlock-codex)), and Python's built-ins (`len`, `min`, `round`,
…).

**What a variable can hold:** `None`, `True`/`False`, whole and decimal numbers, text, lists,
and dictionaries with text keys, inside each other as deep as you like. Anything else
(a set, a function, a module, a character) can't be saved and stops the story with a
message saying what to use instead.

**What a `$` line can't set:** a defined name (use `default`), an engine name (`dice`,
`Character`, …), a name starting with `_`, or `import` (see section 11). Setting part of a
value is fine: `$ scores["hana"] = 2`.

Good to know:
- Two variables that share one list (`$ b = a`) get separate, equal lists after a load or
  rollback.
- A defined list changed by a `$` line isn't saved, and keeps the change in the next new
  game. Use `default` for anything that changes.
- A `define` value can't read story variables or roll `dice`, because defines are set at
  launch, before any game exists. A `lambda` in a define can, since it runs later:
  `define bonus = lambda: trust * 2`.
- In dev runs, `print()` output goes to the log.

### persistent (data across playthroughs)

```
default persistent.festivals = 0
default persistent.hana_remembers = False

label river_end:
    $ persistent.festivals += 1
    $ persistent.hana_remembers = True

label bridge:
    if persistent.hana_remembers:
        hana sad "Have we... done this before?"
```

`persistent.<name>` is remembered **across playthroughs**: quitting, starting a new game,
loading a save, and rolling back never change it. Use it for what the game should remember
about the player rather than the story ("finished once", "saw the sad ending").

- **`default persistent.<name> = value`** (top level, once per name) gives the starting value.
  It is used only when the name has no stored value, so adding one in a patch is safe and
  changing it later doesn't change what players already have.
- **Reading a name that has no value and no default** stops the story with a did-you-mean.
  Give every persistent name a `default`.
- **Values:** the same kinds as story variables (text, numbers, `True`/`False`, `None`, lists,
  dictionaries with text keys). `persistent.flowers.append("iris")` is kept. At most 1 MB in
  total and 10,000 names (E183).
- **Names** starting with `_` are the engine's. `$ persistent._clear()` forgets all your
  values (defaults apply again). `$ persistent._clear(progress=True)` also forgets which lines
  were read and which choices were picked. Unlocks (gallery, endings, achievements) stay;
  only the settings' "delete persistent data" button removes them.
- **`define` values can't read `persistent`**: they are set once at launch. Use a `lambda`.
- **Rollback re-runs lines**, so `$ persistent.festivals += 1` can count twice if the player
  rolls back over it and forward again. Prefer `= value`, or put a `rollback block` after
  it (see [Rollback](#18-rollback)).
- **Players can edit and share the file**, so treat what you read as untrusted: never pass a
  persistent value to `eval` or `exec`, and never build a file name or an image or sound
  name from one. Check a value's type before using it (`if persistent.festivals == 2:`
  rather than doing arithmetic on whatever is there), and never store anything personal.
- Saved automatically (within 2 seconds, at the story's end, and on quit) to
  `persistent/persistent.json` in the game folder during development, or the player's data
  folder in a release (set `[game] id`; without it the game runs but nothing is saved, with
  a warning). Players reset it by deleting that file. A damaged file is set aside as
  `persistent.bad.json` and the game starts fresh; a file from a newer engine version is
  left alone and nothing is saved that session. To test a first playthrough, run
  `python -m engine run --no-persistent` (dev runs only): nothing is read or saved.

| Message | Fix |
|---|---|
| `persistent.met_hana has no value yet. …` / `… Did you mean "hana_remembers"?` | Fix the spelling, or add `default persistent.met_hana = False`. |
| `hana_remembers is remembered across playthroughs (default persistent.hana_remembers, script/database.vns, line 2), so write persistent.hana_remembers here. …` (warning W320) | Write `persistent.hana_remembers` on that line. Plain `hana_remembers` is another variable that has no value. |
| `persistent.visited can't hold a set, …` / `persistent data is now 1.3 MB, over the 1 MB limit. …` | Store plain values; keep flags and counts, not long text. |
| `persistent.bag[…][0] can't hold a set, …` | `[…]` stands for a dictionary key that isn't written in your script (it may come from the player's file), so it is never shown. |
| `persistent names starting with _ belong to the engine, …` / `default persistent.a.b sets one name …` | Use a plain name such as `seen_intro`. |
| `define title couldn't be set: it reads persistent.cleared, …` | Use a `lambda` or a `default`. |
| `persistent.hana_rememebrs is read here but never set or given a default. …` (warning, dev runs) | Fix the spelling or add a `default`. |

### points (character stats)

```
points hana daichi 0 to 10
points courage 0 to 100 start 50
default bonus = 2

label bridge:
    points daichi += 1
    points courage -= bonus * 2
    if points.highest("hana", "daichi") == "hana":
        hana happy "Same time next year?"
```

A **meter** is a whole number the story keeps, such as how much each character likes the
player.

- **Declare** at the top level, once, in any file: `points hana daichi` starts each at 0.
  Add `0 to 10` to keep a meter in that range, and `start 5` to start elsewhere. Without a
  range a meter can go from -1,000,000,000 to 1,000,000,000; when 0 is outside the range, it
  starts at the low number. A story can have up to 200 meters.
- **Change** in a label: `points hana += 2`, `-= 1`, or `= 0`. The amount can be any Python
  that gives a whole number, e.g. `bonus * 2`. Adding past the top stops at the top, and
  taking away past the bottom stops at the bottom.
- **Read** wherever Python runs: `if points.hana >= 5:`, `points["hana"]`, and
  `points.highest("hana", "daichi")`, the name of the highest (the first listed wins a tie;
  with no names, every meter in the order they were declared). `$` lines can't change
  meters.
- **`define` values can't read `points`**: they are set at launch, before any game starts.
  Use a `lambda` or a `default`.
- A meter can share a character's name: `points.hana` is the meter, `hana` the character.
  Meters are saved and rolled back like variables. A save made before you added a meter
  starts it at its start, and a saved value outside a range you changed later moves into the
  range.
- In dev runs, **F3** shows every meter under the frame rate, such as `hana 2 (0-10)` (the
  range only when you declared one, and the rank when it has ranks). After 12 meters it
  shows how many more there are.

#### Ranks

```
points hana 0 to 10 ranks "Stranger" 0 "Friend" 4 "Close" 8

label bridge:
    if points.rank("hana") == "Close":
        hana happy "Same time next year?"
```

- **Ranks** name parts of a meter's range. After the range (and `start`), write `ranks`,
  then each rank's label in quotes and the number it starts at, lowest first. They apply to
  every meter on the line.
- `points.rank("hana")` gives the label of the highest rank the meter has reached, such as
  `"Friend"` at 4 to 7, or `""` while it is below the first rank. Use it wherever Python
  runs: conditions, `$` lines, choice conditions. To show it in text, copy it to a
  variable first: `$ hana_rank = points.rank("hana")`, then `{var=hana_rank}`.
- Labels are plain text, up to 40 characters, each used once. The numbers are whole, inside
  the range, and each higher than the one before. A story can give a meter up to 20 ranks.
- The rank comes from the meter's value, so it saves, loads, and goes back with it.
- `ranks` is a word only right before a quoted label, so a meter or variable can still be
  called `ranks`. `rank` can't be a meter name, because `points.rank` is taken.

#### Change notices

```
    points hana += 1 "Hana will remember that."
    points trust -= 2 "Daichi noticed."
```

- Text in quotes after the amount shows as a **notice** in the top-right corner when the
  line runs, the same notice as a new codex tip. It works with `+=`, `-=`, and `=`.
- The notice is plain text up to 200 characters (write `{{` for a `{`). It shows whether
  or not the meter changed, so write it for the moment, not the number.
- Skipping shows it too. Going back and forward again doesn't show it twice, and loading
  a save never shows it.

| Message | Fix |
|---|---|
| `points needs a meter name, e.g. points sayori 0 to 10 at the top level, or points sayori += 2 in a label.` | Name the meter: `points hana 0 to 10` at the top level, `points hana += 2` in a label. |
| `there are two meters named "sayori": here and at script/story.vns, line 3. Declare each meter once.` | Delete one of the two declarations. |
| `the range 10 to 0 is backwards; write the low number first.` | Write `0 to 10`. |
| `there is no meter named "sayory". Did you mean "sayori"? Declare meters at the top level, e.g. points sayory 0 to 10.` | Fix the spelling, or declare the meter. |
| `Python can't change points.sayori. Use the points statement, e.g. points sayori = 3.` | Change meters with a `points` line, not a `$` line. |
| `this story has 240 meters; the engine allows 200.` | Keep the rest in story variables. |
| `the amount for points sayori must be a whole number, but it is 1.5 (a decimal number).` | Round it: `points sayori += round(bonus)`. |
| `points sayori += 5 went past the top of its range, so sayori is 10, not 12.` (warning, dev runs, once per line) | Fine if you meant it; otherwise widen the range or change the meter by less. |
| `ranks needs at least one label and the number it starts at, e.g. ranks "Stranger" 0 "Friend" 4 "Close" 8` | Add the ranks, or remove `ranks`. |
| `the rank "Friend" needs the number it starts at after it, e.g. "Friend" 4` | Write the number after each label. |
| `two ranks are named "Friend"; give each rank its own label.` / `a rank label has 50 characters; keep it to 40.` | Rename or shorten the label. |
| `the rank "Close" starts at 12, outside the range 0 to 10.` | Lower the number, or widen the range. |
| `the rank "Friend" starts at 4, but it must start higher than "Stranger" (4). List ranks from lowest to highest.` | Put the ranks in order, each starting higher. |
| `"rank" can't be a meter name: points.rank("hana") gives a meter's rank. Pick another name, e.g. standing.` | Rename the meter. |
| `the notice is plain text, without {b} or {var}. Write {{ to show a {.` / `the notice is empty; write a few words between the quotes.` | Plain words only in a notice. |
| `points.rank needs a meter with ranks, but hana has none. Add ranks to its points line, e.g. points hana 0 to 10 ranks "Stranger" 0 "Friend" 4 "Close" 8` | Add ranks to that meter, or read `points.hana` instead. (Also while playing, when the name is computed.) |
| `hana has no rank named "Closee". Did you mean "Close"? Its ranks are "Stranger", "Friend", "Close".` (warning) | Fix the label in the condition. |

### show meter, hide meter

Meters are hidden from the player until the story shows them. `show meter` puts one or more
in a corner of the screen; `hide meter` takes them away.

```
points hana 0 to 10 ranks "Stranger" 0 "Friend" 4 "Close" 8
points sanity 0 to 100 start 100

label bridge:
    show meter hana sanity
    points hana += 1 "Hana will remember that."
    hide meter sanity
```

- Name one or more meters, separated by spaces. They stack in the order shown.
- A shown meter stays on screen, across scenes, until `hide meter`. Saves keep which meters
  are shown, going back restores it, and New Game starts with none.
- The value updates as `points` lines run. A meter with ranks shows its rank under it,
  and the panel gives a short pulse when the rank changes (none with Reduce motion).
- The corner hides with the text box, under menus, and during minigames. In full-screen
  text (`nvl on`) meters sit beside the text, one row each for the name, the meter and the
  rank, so keep names short.
- `meter` is a word here only right after `show` or `hide` with meter names after it.
  `show meter` alone, or with `at`, `as`, `with` or a number, still shows a picture tagged
  `meter`, and `meter` stays a valid name for anything.

#### How a shown meter looks: [meter.<name>]

Each meter can have its own table in `config.toml`. Every key is optional:

```toml
[meter.hana]
look = "hearts"        # bar, number, hearts, pips, or dial
place = "top_right"    # top_left, top_right, bottom_left, or bottom_right
label = "Hana"         # the name shown beside it, up to 30 characters

[meter.sanity]
look = "dial"
```

- What a table leaves out comes from the game's kit (`[theme] kit`), then the defaults: a
  bar at the top left, labelled with the meter's name (`hana_love` shows as "Hana love").
- **bar**: an outlined bar filled by the meter's share of its range. **number**: the
  value. **hearts** and **pips**: one mark per point when the range spans 10 or fewer,
  otherwise 5 to 10 marks that each stand for an equal part. **dial**: an arc with the
  value beside it.
- Every look but `number` needs a range on the `points` line; a meter without one is shown
  as a number.
- Colors come from `[theme.corner]`, so color schemes and kits style meters too: text in
  `text_color`, marks in `accent_color`.

| Message | Fix |
|---|---|
| `show meter takes meter names separated by spaces, but found "hana,". Write e.g. show meter hana sanity` | Remove commas and quotes: `show meter hana sanity`. |
| `hide meter takes only meter names, but found "with". A meter comes and goes on its own; write e.g. hide meter hana sanity` | Remove `with …`. |
| `show meter names hana twice; name each meter once.` / `show meter can name at most 8 meters on one line. Split it over two lines.` | Name each meter once, at most 8 per line. |
| `there is no meter named "hanna". Did you mean "hana"? …` | Fix the spelling, or declare the meter with a `points` line. |
| `[meter.hanna] is set up, but no points line declares a meter named hanna, so it is never used. Did you mean "hana"? …` (warning) | Rename the table to the meter's name, or delete it if the meter is gone (renaming or deleting a meter leaves its table behind). |
| `hana is shown as hearts, which needs a range, but its points line has none, so it is shown as a number. …` (warning) | Give the meter a range, e.g. `points hana 0 to 10`, or set `look = "number"`. |
| `this shows the picture "meter hana", not the meter. A meter takes no at, as or with: write show meter hana` (warning) | Remove `at`, `as` or `with`. |

### clock (story time)

Story time counts days and the parts of a day. It is saved with the game like a variable,
so loading, going back and New Game all put it exactly where it was. Three lines move it:

```
label after_class:
    clock next                     # Morning becomes After school
    if clock.day == 7:
        jump festival_eve
    if clock.part == "Night":
        jump sleep
    "It's {var=clock.date}, {var=clock.part}."
    clock next day                 # the first part of the next day
    clock go to day 12             # or 12; the first part of day 12
    clock go to "31 October" Night # a date, then (optional) a part of that day
    clock go to Evening            # later today, or tomorrow's if Evening has passed
```

- `clock next` moves to the next part of the day; after the last part it is the next day's
  first. `clock next day` skips to the next day's first part.
- `clock go to` takes a day (`day 12`), a date in quotes (`"31 October"`, `"Spring 4"`) or a
  part of the day, and a part after a day or date. A date that comes every year (or every
  season) means the next time it comes, today included. A day number may go back in time.
  Put a part with spaces in quotes: `clock go to "After school"`.
- Read it in conditions, `$` lines and text: `clock.day` (a number from 1), `clock.part`,
  `clock.weekday`, `clock.date` (the date in words, e.g. "Monday 1 April" or "Night 3"),
  `clock.month` and `clock.season` ("" without months or seasons), and
  `clock.days_left(...)`: days until a day number, a date in quotes, or, with nothing in
  the brackets, `last_day`; 0 once it has come. In text, write `{var=clock.date}` (any of
  the first six works).
- Comparisons must match the names exactly: `clock.part == "Night"`. A name the calendar
  doesn't have gets a warning, since the comparison could never match.
- `clock` is a word only at the start of a line with `next` or `go` after it. `clock "Tick."`
  is still dialogue by a character called clock, and `clock` stays free as a name. A game
  that has its own `clock` (a `define` or `default`) can't read story time in Python, and
  gets a warning.

#### The calendar: [calendar]

Without settings the day has Morning, Afternoon, Evening and Night, the week runs Monday to
Sunday, and dates read "Day 4". A kit (`[theme] kit`) brings its own parts and wording:
romance "Thursday, day 4", horror "Night 3", mystery "Day 4 of the case", fantasy "Day 4 of
the journey", cozy "Spring, day 4", sci-fi "Shift 2", letters "4 April". Your own keys
always win:

```toml
[calendar]
start = "Monday 1 April"       # or a day number: start = 3
parts = ["Morning", "After school", "Evening", "Night"]
last_day = 30                  # clock.days_left() counts down to it
# weekdays = ["Moonday", "Fireday", "Restday"]
# months = ["Thaw", "Bloom"]   # a start date naming a usual month turns on January-December
# month_days = 30              # or one number per month
# seasons = ["Spring", "Summer", "Autumn", "Winter"]
# season_days = 28
# day_text = "{weekday}, day {day}"   # also {month}, {month_day}, {season}, {season_day}
# day_card = false             # no date card at a new day
# place = "top_left"           # the corner show clock uses
```

The clock changing is also a hook other features build on (messages that arrive after a few
days, for example): each `clock` line that moves time tells them once.

#### The day card

When a `clock` line starts a new day, the date fills the screen for a moment, worded as
`clock.date` is ("Day 4", "Night 3", "Spring, day 4"), then the story goes on. It works like
a chapter card: it fades in and out in the chapter card's colors (`[theme.chapter]`, which
follow the color scheme), a click skips it, skipping passes it, and Reduce motion makes the
fades cuts. A new part of the same day shows no card. Turn it off with
`[calendar] day_card = false`.

Save slots of a game that uses the clock start with the story time: "Day 4, Evening ·
Hana: See you tomorrow."

### show clock, hide clock

`show clock` puts the date and the part of the day in a corner of the screen; `hide clock`
takes it away.

```
label monday:
    show clock
    "The bell rings."
    clock next                     # the corner changes to the next part at once
```

- It shows the date as `clock.date` words it, with the part of the day under it, and
  changes the moment a `clock` line moves time (with a short pulse, none with Reduce
  motion).
- It stays on screen, across scenes, until `hide clock`. Saves keep it, going back restores
  it, and New Game starts without it. Like shown meters, it hides with the text box, under
  menus and during minigames.
- The corner is `[calendar] place` (`top_left`, `top_right`, `bottom_left` or
  `bottom_right`), else the kit's (the corner its meters don't use), else the top right.
- `show clock` and `hide clock` mean the clock only with nothing else on the line.
  `show clock at left` or `hide clock with dissolve` still show and hide a picture called
  clock. A game with a picture called clock gets a warning at each bare `show clock`.

| Message | Fix |
|---|---|
| `clock moves story time and needs next or go after it, but found "nxt". Did you mean "next"? …` | Write `clock next`, `clock next day` or `clock go to …`. If the game has a character called clock, the message says so: put what they say in quotes. |
| `clock next takes nothing more, but found "days". …` | `clock next` or `clock next day`, nothing after. |
| `clock go to needs a day, a date or a part of the day, but found nothing. …` | Add where to go: `clock go to day 7`. |
| `clock go to takes a day or date and a part of the day at most, but found "late" after them. …` | Put a name with spaces in quotes. |
| `"31 Octobre" isn't a date this game's calendar can read. …` | Fix the date, or add the months or seasons it uses in `[calendar]`. |
| `no part of the day is called "Nite". Did you mean "Night"? …` | Fix the name, or add the part in `[calendar] parts`. |
| `clock.days_left() counts down to [calendar] last_day, which config.toml doesn't set. …` | Set `last_day`, or give the day: `clock.days_left(30)`. |
| `clock has no value called dya. Did you mean "day"? …` / `Python can't change clock.day. …` | Use one of the values above; move time with a `clock` line. |
| `clock.part is never "night": no part of the day is called that, …` (warning) | Match the name exactly: `"Night"`. |
| `[calendar] start "Fooday 9" isn't a date this calendar can read, …` (warning) | Use a day number or a date the calendar has. |
| `this goes to day 40, after [calendar] last_day (30), …` (warning) | Raise `last_day`, or go to an earlier day. |
| `show clock puts the story clock in the corner, not your picture "clock". …` (warning) | To show the picture, add where or how (`show clock at center`), or rename the picture. |

---

## 10. Random numbers

```
    $ wind = dice.roll(1, 6)            # 1, 2, 3, 4, 5, or 6
    $ fortune = dice.pick(fortunes)     # one item from a list
    if dice.decimal() < 0.25:           # a 25% chance
        "A gust took the lantern before I could write on it."
    $ deck = dice.shuffle(deck)         # a shuffled copy
```

| Call | Gives |
|---|---|
| `dice.roll(low, high)` | a whole number from `low` to `high`, both included |
| `dice.pick(items)` | one item from a non-empty list |
| `dice.decimal()` | a decimal number from 0 up to (not including) 1 |
| `dice.shuffle(items)` | a new, shuffled list; `items` stays as it was |

`dice` results are saved with the game: reloading or rolling back gives the **same**
results, so players can't reroll by reloading. Each new game rolls differently. `dice` can
be used once a game has started: in `$` lines, conditions, defaults, and `lambda` helpers,
but not directly in a `define` value.

**Use `dice`, not `random` or `time`.** Python's `random` module and the clock (`time`,
through `module`) work, but their results don't replay: after a load or a rollback they
give different numbers, so a player can reroll by reloading, and a scene that depends on
them can't be played back the same way.

> **Warning:** `$` lines, `if`/`elif` conditions, and `define` values run real Python, with
> the same access to the player's computer as any program, and `define` values run at
> every launch. Code that uses `dice` is no different. Players should only run scripts
> from people they trust.

---

## 11. Python modules

```
define math = module("math")

label shop:
    $ lanterns = math.floor(money / 300)
```

To use a Python module in the whole game, define it with `module("name")` at the top level.
That is the only way: `import` in a `$` line is an error, because a module can't be saved
with the game. Built-ins such as `len`, `min`, `max`, and `round` need no module.

---

## 12. Backgrounds and sprites

**Pictures come from files.** Put PNG, JPEG, or WebP files in `game/images/` (subfolders
are fine). A file's name in the script is its path inside `images/`, with the folders and
the file name as words and no extension. There is no list to keep.
```
game/images/bg/river_dusk.png         →  scene bg river_dusk
game/images/hana/happy.png            →  show hana happy
game/images/hana/yukata/happy.png     →  show hana yukata happy
game/images/stall.png                 →  show stall
```

The first word (`hana`) is the image's **tag**. Names match files exactly, capitals
included. In file and folder names use letters, digits, and `_`: no spaces, hyphens, or
extra dots, at most 5 words, and not a statement word or `layer`, `zoom`, `flip`. The log
lists any file that breaks these, with a name to rename it to. The example game's pictures
are in `game/images/`.

**Blinking and talking.** A character blinks, and moves her mouth while her lines type,
when her picture has frames next to it: copies of the same picture, the same size, with only
the eyes or the mouth changed. Name them after the look, with `_blink` or `_talk` and a
number from 1 to 9; no code is needed.
```
game/images/hana/happy.png            →  show hana happy
game/images/hana/happy_blink1.png     eyes half closed
game/images/hana/happy_blink2.png     eyes closed
game/images/hana/happy_talk1.png      mouth open
```
Frames play in number order, then back again (`1, 2, 1`), then the plain look; a missing
number is skipped, and a frame with no number plays first. Hana blinks every few seconds;
while `hana "…"` types, her mouth opens and closes, and it stops when the text stops (a
`{pause}`, the end of the line, or a click). A look with only blink frames only blinks. A
picture named in an `image` line works too: `image hana festival = "art/yukata.png"` takes
`image hana festival_blink1 = "art/yukata_blink.png"`. Timings are in `config.toml`, and
reduce motion holds every sprite still:
```toml
[animation]
enabled = true             # false: no blinking or talking
blink_every = 4.0          # about every 4 seconds (1 to 30), each gap random
blink_frame = 0.08         # seconds per blink frame (0.02 to 0.5)
talk_frame = 0.1           # seconds per talking frame (0.03 to 0.5)
```

**Art scale.** Sprites are drawn at their own size on a screen 720 high. If your art was
drawn for a 1920×1080 screen, say so once in `game/config.toml`. Backgrounds always fill
the screen, whatever their size.
```toml
[stage]
art_height = 1080          # 180 to 4320; 720 when left out
```

### scene
```
    scene bg river_dusk
    scene black
```
Removes every character and sets the background. `black` is built in. `scene` alone
clears to an empty black stage.

### show
```
    show hana happy
    show hana sad
    show hana at left
    show daichi grin at right
```
Shows a sprite. One sprite per tag: `show hana sad` replaces `hana happy` in the same
place, and `show hana at left` moves Hana without changing her face. A sprite shown for
the first time stands at `center`. After the image name you can add, in any order:

| Write | What it does |
|---|---|
| `at left`, `at center`, `at right` | Built-in positions. |
| `at by_the_rail` | A position you named in `config.toml` (below). |
| `at 400`, `at 400 680` | x (and y) on a 1280×720 screen, for the sprite's bottom center. −1280 to 2560, so a sprite can wait off-screen. |
| `behind hana` | Directly behind the sprite tagged `hana`. |
| `layer 10` | Higher layers are always in front. −100 to 100; normally 0. |
| `zoom 1.5` | Bigger or smaller, 0.25 to 4. `zoom 1` is normal size. |
| `flip on`, `flip off` | Mirror the sprite left to right, or undo it. |
| `as girl_b` | Use another tag, so the same picture can be shown twice. |

Each stays until you change it. On the same layer, the sprite shown most recently is in
front.

`at` takes a position name or numbers:
```
    show hana happy at left                  # left, center, or right
    show hana happy at by_the_rail           # a name from [stage.positions]
    show daichi at 760                       # x only: feet on the bottom edge
    show daichi at 760 680                   # x and y
```

`behind`, `layer`, `zoom`, `flip`, and `as`:
```
    show daichi at 760 behind hana           # just behind Hana
    show railing layer 10                    # always in front of the characters
    show hana happy zoom 1.3                 # a step closer
    show lantern_girl as girl_a at 900 flip on
    show lantern_girl as girl_b at -200      # waits off-screen
```

**Your own positions.** Name positions once in `config.toml` and use them like `left`:
```toml
[stage.positions]
by_the_rail = 560          # x only: stands on the bottom edge
hana_close = [560, 760]    # x and y
left = 240                 # the built-in ones can move too
```

### hide
```
    hide daichi
```
Removes the sprite with that tag. Write only the tag. Hiding someone who isn't shown does
nothing.

### Expressions on dialogue lines
```
    show hana happy
    hana pout "You're late!"
    hana "Fine. I forgive you."        # still pouting
```
Words between the name and the text change the speaker's sprite on that line, as if
`show hana pout` ran just before it, and the face stays. If the character isn't on stage,
the words do nothing. Only expression words go there; positions belong on a `show` line.
`hana sad` shows `hana sad`, not `hana yukata sad`: give the full name to keep an outfit.

If a character's images use another name, such as for a short speaker name, give the
`Character` an `image_tag`:
```
define d = Character("Daichi", color="#3a6aa8", image_tag="daichi")
```

### image
```
image bg dusk = "#2b2140"
image hana festival = "art/commissions/hana_yukata_v3.png"
```
Names a file outside `images/` (path from the game folder), or a solid color that fills
the screen (`#` and six digits or letters a–f). Top level only; each name once. Most games
need none.

**When pictures change.** Nothing changes on screen until the next line of text, choice,
`with`, or `pause`; then the whole picture changes together. `scene` followed by three
`show` lines is one picture, never a background without its characters.

### Transitions
```
    scene bg bridge_night with fade
    show hana happy with dissolve
    hide daichi with dissolve
```
`with` at the end of `scene`, `show`, or `hide` changes the picture through a transition
instead of at once. See [Transitions and effects](#16-transitions-and-effects).

### Missing pictures and positions
Missing pictures don't stop the game. You get a warning at launch, and a checkered
placeholder stands in while you play, so you can write before the art is done:

- `there is no image "hana hapy", so a placeholder will show. Did you mean "hana happy"?`
- `there is no image "hana blush", so a placeholder will show. Add images/hana/blush.png, or check the spelling.`
- `there is no image "hana happy", so a placeholder will show. Names match files exactly: rename images/hana/Happy.png to happy.png, or write hana Happy.`

A wrong position does stop the launch:

- `there is no position named "rigth". Did you mean "right"?`
- `there is no position named "stall". Use left, center, right, or a number such as at 400, or add stall to [stage.positions] in config.toml.`
- `1400 is too far right. Positions go from -1280 to 2560; the screen itself is 0 to 1280 across and 0 to 720 down.` (or `too far left`, `too high`, `too low`)
- `at takes a position name or one or two numbers, e.g. at left or at 400 680, but this has "400px". Numbers have no units.`
- `at takes at most two numbers, x and y, but this has 3.`

---

## 13. Music and sound

**Sounds come from files.** Put audio files in `game/audio/` (subfolders are fine, e.g.
`bgm/`, `sfx/`, `voice/`). In the script, write the file's path **inside** `audio/`, in
quotes, with its extension: `"bgm/festival.ogg"` plays `audio/bgm/festival.ogg`. Paths use
`/` and match capitals exactly.

**Formats.** Use **Ogg Vorbis (`.ogg`)**, especially for music: it is small and loops with
no gap. Opus, FLAC, WAV (16-bit), and MP3 play too. WAV loops with no gap as well, but its
files are about ten times larger. **Don't loop MP3 music:** an MP3 encoder adds a few
milliseconds of silence at the start and end of every file, so the track has a short gap
each time it loops (the game warns about it). Other files (`.m4a`, `.aac`, `.wma`, `.mid`)
don't play; convert them to `.ogg`.

**Loudness.** Aim for about the same loudness in every file: around −16 LUFS for music and
voice, effects and ambience a little quieter, and peaks under −1 dB, so players don't have
to keep changing the volume. Most audio editors can measure and set it (in Audacity:
Effect, Loudness Normalization).

There are three **channels**: `music` (one track at a time), `sound` (many effects at once),
and `voice` (one voice line at a time).

The example game, *Paper Lanterns*, uses each statement below: music that fades in and a
river that loops under it (`script/main.vns`), a chime over the river
(`script/chapter1.vns`), a change of music, a hard stop, a firework, and a queue
(`script/routes/daichi.vns`), three voiced lines, one of them a menu's question, and
Hana's and Daichi's text blips (section 8). Its files are in `game/audio/`; `game/audio/LICENSES.txt` records who made each one and its
license. Keep such a record for your own files too: where each came from, and its license.

### play
```
    play music "bgm/festival.ogg" fadein 2.0
    play sound "sfx/firework.ogg"
    play sound "sfx/rain.ogg" loop volume 40
```
Music loops and replaces the music playing (the old track fades out first). Playing the
track that's **already playing** leaves it alone, so music carries on when you jump to
another label. Effects play once and never stop anything else; with `loop`, an effect
repeats until `stop sound` (rain, a crowd, a river), and other effects play over it. After
the file you can add, in any order:

| Write | What it does |
|---|---|
| `fadein 2.0` | Fade in over 2 seconds (0 to 60). |
| `fadeout 1.0` | Music only: fade the old track out over 1 second. `fadeout 0` is a hard cut. |
| `volume 40` | Play at 40% of the channel's volume (0 to 100). |
| `loop`, `once` | Repeat until stopped, or play one time. |
| `restart` | Music only: start again even if this track is already playing. |
| `from 12.5`, `from current` | Music only: start 12.5 seconds in, or where the old track was (for swapping to a remix; add `fadeout 0` for a seamless swap). |

### queue
```
    play music "bgm/omen.ogg"
    queue music "bgm/shrine_steps.ogg"
```
Plays the track after the music before it ends. Only the **last** track in the queue loops,
so here `omen` plays once and `shrine_steps` loops. On a silent channel it plays at once.
Takes `fadein`, `volume`, `loop`, `once`. Only music can be queued.

### stop
```
    stop music fadeout 2.0
    stop music fadeout 0
    stop sound
    stop sound "sfx/crowd.ogg" fadeout 1.5
    stop voice
```
Stops the channel and clears the music queue. `stop sound` stops every effect playing;
with a file, it stops only that effect and leaves the rest (rain keeps falling).
`fadeout 0` is a hard cut, for a sudden silence; without `fadeout`, music fades over half
a second, and effects and the voice stop at once. Stopping a silent channel does nothing.

### voice
```
    voice "voice/hana_014.ogg"
    hana "You came! I didn't think you would."
```
Put `voice` **directly above** the line it voices: only comments and `scene`, `show`,
`hide`, `play`, `queue`, `stop`, and `$` lines may come between. The voice starts when the
line appears and stops when the player moves on, at the next voice, or at `stop voice`.
The line's text always shows too, so players who play without sound miss nothing.

A `voice` directly above a menu's question voices the question; it plays each time the
menu appears:

```
    menu:
        voice "voice/daichi_020.ogg"
        daichi "What do you want to ask?"
        "The fox shrine":
            jump fox_shrine
        "That's all":
            return
```

A voice with no line below it, above an `if`, or above `menu:` never plays, and a warning
says so when the game starts. In the History log a voiced line has a speaker icon: clicking
the line plays its voice again, and leaving History stops it.

### Settings in config.toml
```toml
[audio]
music_volume = 60          # starting volumes, 0 to 100; players change them in Settings
music_fadeout = 1.0        # default fade for changing or stopping music

[audio.loop_start]
"bgm/festival.ogg" = 8.0   # the intro plays once; every repeat starts at 8.0 seconds
```
Loop points work only in `.ogg` and `.opus` files; other files loop from the start, and the
log says so.
Other keys: `master_volume`, `sound_volume`, `voice_volume`, `music_fadein`,
`sound_fadein`, `sound_fadeout`, `restore_fadein`, `restore_fadeout`, and `play_unfocused`,
`play_minimized` (`false` pauses audio while the game is in the background). The example
game's `config.toml` lists each key with its default.

**Saving and loading.** A save remembers the music, its queue, and looping effects, not
where in the track the music was. After a load or rollback they come back from the start
of the track (`restore_fadeout` and `restore_fadein` fade between); one-shot effects don't
replay, but the voice of the line on screen does. Music that plays `once` isn't brought
back, so **loop the music under each scene**.

**Skipping.** While the player skips, one-shot effects and the voices of skipped lines
don't play, and fades are shortened, but music and looping effects follow the story, so
when skipping stops, what plays is what the line would have.

**Missing files are found at launch.** Before the title screen, the game looks up every
file named by `play`, `queue`, `stop sound`, and `voice` and lists the missing ones in the
log, with the file it thinks you meant. The game still starts; missing files play as
silence.

**Nothing about sound stops the game.** A missing or damaged file plays as silence, and the
log says which file and suggests a fix. With no sound device, or when it is unplugged, the
game runs silently and the log says so once; when a device is plugged in, the music and
looping effects of the current scene come back. Don't carry story-critical information in
sound alone.

---

## 14. Dialogue text

Lines appear in a text box at the bottom of the screen and type out letter by letter. The
speaker's name sits on a plate above the box, in the character's `color`. The player
clicks (or presses Space or Enter) once to finish a line that is still typing, and again
to go on.

### Text tags

Tags go inside the quotes, in `{ }`, and are never shown. Most come in pairs: `{b}` starts
bold and `{/b}` ends it.

```
    hana "I saw it... {pause=0.6}the {b}{color=#9a1c14}lantern{/color}{/b} moved."
    daichi "That's impossible. {pause}...Isn't it?"
    hana "{speed=0.5}Slowly,{/speed} it turned {i}upstream{/i}. {size=1.5}Look!{/size}"
```

| Tag | What it does |
|---|---|
| `{b}…{/b}` | bold |
| `{i}…{/i}` | italic |
| `{color=#9a1c14}…{/color}` | color: `#` and six digits or letters a–f |
| `{size=1.5}…{/size}` | bigger or smaller: 0.5 to 2 times the normal size |
| `{speed=0.5}…{/speed}` | type slower or faster: 0.1 to 10 times the player's speed (2 is twice as fast) |
| `{speed=instant}…{/speed}` | show these words all at once |
| `{shake}…{/shake}` | the letters tremble; see [Text effects](#text-effects) |
| `{wave}…{/wave}` | the letters ripple up and down |
| `{glitch}…{/glitch}` | some letters flicker into symbols such as `#` and `%` |
| `{pause=0.6}` | stop typing for 0.6 seconds (0.1 to 30) |
| `{pause}` | stop until the player clicks; the text so far stays |
| `{var=player_name}` | show a story variable's value |
| `{username}` | the player's computer user name, if the game offers it and they allow it; otherwise "friend" (see [Fourth-wall tricks](#25-fourth-wall-tricks)) |
| `{next}` | at the very end: go on to the next line without a click |
| `{{` | show a `{` |

- Tags are lower case with no spaces inside: `{color=#9a1c14}`, not `{Color = "#9a1c14"}`.
  Numbers have no units: `{pause=0.5}`, not `{pause=0.5s}`.
- Close tags in the reverse order you opened them: `{b}{i}…{/i}{/b}`. A tag still open
  at the end of the line closes there.
- A `}` on its own is just a `}`. To show a tag as text, write `{{b}`.
- Speeds are relative, so a player who reads fast still gets your slow line, only faster.
  Pauses always happen, even when the player shows text instantly.
- **If a color carries meaning (red for clues), make those words bold too**, for players
  who can't tell the colors apart: `{b}{color=#9a1c14}clue{/color}{/b}`. On the default
  box, red `#9a1c14` and blue `#1e4a9c` are easy to read.

**Showing a variable.** `{var=player_name}` shows the value of a `default` or `define`, text
or a number, as it was when the line started. Braces in the value show as they are, and
values over 200 letters are cut with "…". Anything else, such as a list or `True`, stops
the story with a message.

```
default player_name = "Ren"
default wishes = 3
    hana "{var=player_name}, we still have {var=wishes} wishes left."
```

**Interruptions.** A line that ends with `{next}` moves on by itself once it has typed out.
If the player clicked to finish it early, it waits for one more click, so nothing goes by
unread.

```
    daichi "Hana, it's a paper bag with a candle in i-{next}"
    hana "LOOK! It's turning around!"
```

**Long lines** are never cut off. A line too long for the box continues in a fresh box
after a click. In a dev run, the game warns about each such line so you can split it
where you like:

| Message | Fix |
|---|---|
| `this line needs 2 text boxes at text size 28, so the player clicks once partway through. To choose where it breaks, split it into two lines.` (warning, dev runs) | Split the line into two lines where you want the break, or leave it. |
| `…and 12 more lines need more than one text box.` (warning, dev runs) | After 20 such lines, the rest are counted. |

The check measures each `{var}` as its `default`'s value (or empty), at the `text_size` and
fonts in `config.toml`.

### Text effects

`{shake}`, `{wave}`, and `{glitch}` move or corrupt the letters between them while the line
is on screen: `shake` trembles, `wave` ripples up and down, and `glitch` flickers letters
into symbols such as `#` and `%`.

```
default player_name = "Ren"

label start:
    hana "I'm {wave}so{/wave} happy you came today!"
    hana "{shake=small}I just... {pause=0.6}{speed=0.2}don't{/speed} want you to leave.{/shake}"
    hana "{glitch=large}You're not going anywhere.{/glitch}"
    "My name is {glitch}{var=player_name}{/glitch}."
```

| Tag | What it does | `small` / `medium` / `large` |
|---|---|---|
| `{shake}…{/shake}` | each letter trembles on its own, 20 times a second | up to 1 / 2 / 4 units from its place (at text size 28) |
| `{wave}…{/wave}` | the letters ripple up and down, one wave a second along the words | 2 / 3.5 / 6 units high |
| `{glitch}…{/glitch}` | letters flicker into one of 20 symbols, each about 8 times a second | about 10% / 25% / 50% of the letters at any moment |

- **Strength.** Each takes `small`, `medium` (the default), or `large` after `=`:
  `{shake=large}…{/shake}`. Shake and wave grow with the text: `{size=2}` or a player's
  bigger text size moves them further.
- **One effect at a time.** Effects mix with every other tag (`{b}`, `{color}`, `{size}`,
  `{speed}`, `{pause}`, `{var}`), but a letter has one effect at a time, so close one before
  opening another: `{shake}…{/shake}{wave}…{/wave}`. The same effect inside itself is fine,
  and the inner strength wins: `{shake}a{shake=large}b{/shake}c{/shake}`.
- **Only for show.** Effects never change where a line breaks, how fast it types, its typing
  sound, or what is saved. **History** shows the real words, and a `{var}` inside `{glitch}`
  glitches only on screen.
- **Sudden speed changes** need no new tag: `{speed=0.2}` crawls, `{speed=instant}` slams the
  rest out at once, and `{pause=0.8}` holds a beat:

```
    "{speed=0.2}It was... {/speed}{pause=0.8}{speed=instant}{shake=large}GONE.{/shake}{/speed}"
```

- **Reduce motion.** When a player turns on **Reduce motion and flashing** in Settings (or
  `[effects] reduce = true` is set for everyone), shake and wave hold still and glitch stops
  flickering: each glitch span keeps one fixed scatter of symbols, at least one. So, as with
  `shake` and `flash`, don't let an effect carry the story on its own: let the words say
  what happens.
- **Where they work.** Dialogue and narration, in the text box and in full-screen text
  (`nvl`), where every line on the page keeps moving. A line shown again by a load or
  rollback appears complete, its effects moving. Choices, codex tips, and character names
  take no effects; the tag stops the launch with their own message.
- **Nothing is clipped.** A large shake or wave at a big size can reach a few units past
  the edge of the box. It is drawn there, and nothing is left behind when it moves back.
- **Fonts without the symbols.** Glitch draws its symbols in the span's own font:
  `! # $ % & * + / < = > ? @ \ ^ _ | ~ [ ]`. The built-in fonts have them all; a font that
  lacks one shows its missing-letter box instead.
- **Keep glitches short.** In a dev run, a `{glitch}` span of more than 40 letters at
  `medium` or `large` gives a warning (in the table below), because so many symbols make
  the line hard to read. Glitch a few words, or use `{glitch=small}`.

The example game's bonus scene, `game/script/bonus.vns`, uses each effect once.

### Text style for a character

```
define thought = Character("", text_color="#1e4a9c", text_italic=True)
    thought "Lanterns don't swim against the current. Do they?"
```

`text_color` and `text_italic=True` set how that character's lines look; tags inside still
apply, and `{color}` wins inside its span. `Character("")` has no name plate, which suits
thoughts. Names are plain text and never take tags.

### Settings in config.toml (text box)

```toml
[textbox]
cps = 35                                # letters per second; 0 shows text instantly

[theme.textbox]
text_size = 28                          # 20 to 48
fill_color = "#3a2a3f"                  # the box
fill_opacity = 0.85                     # 0.0 (clear) to 1.0 (solid)
text_color = "#fff4f8"
text_font = "fonts/Lora-Regular.ttf"    # inside the game folder
bold_font = "fonts/Lora-Bold.ttf"
italic_font = "fonts/Lora-Italic.ttf"
bold_italic_font = "fonts/Lora-BoldItalic.ttf"
frame_image = "gui/textbox.png"         # a box picture in gui/, instead of the drawn box

[theme.textbox.name_tab]
text_color = "#8a1f50"                  # names of characters with no color
```

| Key | Default | Allowed |
|---|---|---|
| `[textbox] cps` | `40` | 0 (instant) or 1–1000 |
| `[theme.textbox] text_font`, `bold_font`, `italic_font`, `bold_italic_font` | the built-in Noto Sans faces | a `.ttf` or `.otf` file in the game folder |
| `[theme.textbox] text_size` | `28` | 20–48 |
| `[theme.textbox] text_color`, `fill_color` | `"#3D2B36"`, `"#FFF4F8"` | `"#RRGGBB"` |
| `[theme.textbox] fill_opacity` | `0.80` | 0.0–1.0 |
| `[theme.textbox] frame_image` | none: the drawn box | an image in `gui/` |
| `[theme.textbox.name_tab] text_color` | `"#A02860"` | `"#RRGGBB"` |

The other look settings (sizes, borders, the name plate, the indicator) are listed in
[the UI system](ui-system.md), "Token list". Players can change the speed and size in
Settings. A missing font gives a warning and the built-in font is used; if you set
`text_font` without `bold_font` or `italic_font`, bold or italic is made from your font,
with a warning that suggests adding the real face.

**Readable colors.** In a dev run, the game warns when a character's name color is hard to
read on the name plate (under 3:1), or a `text_color` or the box's own colors are hard to
read over a black or a white picture (under 4.5:1). A dark box needs light text colors, and
the other way round.

### When a tag is wrong

The game checks every tag when it loads and stops with the file, line, and column of the
`{`. The messages:

| Message | Fix |
|---|---|
| `there is no tag "colour". Did you mean "color"?` | Fix the spelling. |
| `there is no tag "blink". The tags are b, i, color, size, speed, shake, wave, glitch, pause, var, next, and username.` | Use one of these tags. |
| `tags are lower case: write {b}, not {B}.` | Write the tag in lower case. |
| `there is no tag "bold". For bold, write {b}…{/b}.` | Tags from other engines get a hint like this. |
| `there is no tag "w". To wait for a click, write {pause}; to wait half a second, write {pause=0.5}.` | Use `{pause}`. |
| `there is no tag "cps". To change typing speed, write {speed=2}…{/speed} for twice as fast.` | Use `{speed=…}`. |
| `there is no tag "nw". To move on by itself, end the text with {next}.` | Use `{next}`. |
| `there is no tag "jitter". To shake text, write {shake}…{/shake}.` / `there is no tag "wavy". To make text ripple, write {wave}…{/wave}.` / `there is no tag "zalgo". To make text glitch, write {glitch}…{/glitch}.` | Use the [text effect](#text-effects) the hint names. |
| `there is no tag "font" in this engine version. The tags are b, i, color, size, speed, shake, wave, glitch, pause, var, next, and username.` | Remove it, or use one of these tags. |
| `this { never closes. End the tag with }, or write {{ to show a {.` | Close the tag, or write `{{`. |
| `{} is an empty tag. To show {}, write {{}.` | Write `{{}`. |
| `a { can't go inside a tag. To show a {, write {{.` | Close the tag first. |
| `this line has more than 50 style tags open at once. Close some with {/…}.` | Close tags you no longer need. |
| `tags have no spaces inside: write {color=#e05050}.` | Remove the spaces. |
| `write {pause=0.6}, with = between the tag and its value.` | Add `=`. |
| `tag values have no quotes: write {color=#e05050}.` | Remove the quotes. |
| `write {color=#e05050}, with = instead of :.` | Write `=`. |
| `{color} needs a color, e.g. {color=#e05050}…{/color}.` | Add the color. |
| `{size} needs a number, e.g. {size=1.5} for half again as big.` | Add the number. |
| `{speed} needs a number, e.g. {speed=0.5} for half speed, or {speed=instant}.` | Add the number or `instant`. |
| `{var} needs a variable's name, e.g. {var=player_name}.` | Add the name. |
| `{b} takes no value. Write {b}…{/b}.` | Remove the value (the same for `{i}` and `{next}`). |
| `a closing tag takes no value. Write {/color}.` | Remove the value. |
| `"#e0505" isn't a color. Write # and six digits or letters a to f, e.g. {color=#e05050}.` | Use `#` and six digits or letters a–f. |
| `write the color with #: {color=#e05050}.` | Add `#`. |
| `{pause=…} takes seconds from 0.1 to 30, but this has 45.` | Stay in range. |
| `numbers in tags have no units: write {pause=0.5}, not {pause=0.5s}.` | Remove the unit. |
| `{speed=…} takes a number from 0.1 to 10, or instant, but this has 40. Speeds are relative: 2 is twice as fast, 0.5 half as fast.` | Use a relative speed. |
| `{size=…} takes a number from 0.5 to 2, but this has 28. Sizes are relative: 1.5 is half again as big.` | Use a relative size. |
| `{shake=…} takes small, medium, or large, or no value, but this has "2". Write {shake=large} for a bigger shake.` (`{wave}` and `{glitch}` the same, ending "for a bigger wave" and "for more glitching") / `{wave=} takes small, medium, or large: write {wave} for medium, or {wave=large}.` | Write `small`, `medium`, or `large`, or no value for medium. |
| `{wave} can't go inside {shake}: a character has one effect at a time. Close {/shake} first, or pick one: {shake}…{/shake}{wave}…{/wave}.` | Close one effect before opening another. |
| `write 0.5, not .5.` | Start the number with 0. |
| `{var=…} takes one variable's name, such as {var=player_name}, but this has "hana.name". To show something else, store it in a variable first.` | `$ shown_name = hana.name`, then `{var=shown_name}`. |
| `{/b} closes bold, but no {b} is open here. Remove it, or add {b} where bold should start.` | Remove it, or add the `{b}`. |
| `{pause} doesn't open anything, so there is no {/pause}. Remove it.` | Remove the closing tag (the same for `{var}` and `{next}`). |
| `{/b} closes bold, but {i} was opened inside it and is still open. Close {/i} first: {b}…{i}…{/i}{/b}.` | Close the inner tag first. |
| `{next} goes at the very end of the text, because the line moves on as soon as it is shown. Move it to the end, or use {pause} to wait here.` | Move it to the end. |
| `this line has {next} twice. Keep the last one.` | Remove the first. |
| `this {glitch} has 41 characters glitching at medium or large, so about a quarter of them show as symbols at any moment and the line is hard to read. Use a shorter span or {glitch=small}; History always shows the real text.` / `this {glitch} has 64 characters glitching at medium or large, so about half of them show as symbols at any moment and the line is hard to read. Use a shorter span or {glitch=small}; History always shows the real text.` (warning, dev runs) | Glitch fewer words, or use `{glitch=small}`. |

---

## 15. Menus and theme

Every game comes with a title screen, a game menu, a quick menu under the text box, and
yes/no questions, all in the default pink theme. You change their pictures, colors, music,
and words in `config.toml`; no code is needed. The example game sets a title picture, a
logo, title music, and a button frame: look at its `config.toml` and `gui/` folder.

- **Title screen.** The picture, the logo (or the game's title as text), a column of
  buttons, and the version number in the bottom-right corner. Its music loops. The buttons
  include **New Game**, **Load** (see [Saves](#17-saves)), **Settings** (see
  [The Settings page](#the-settings-page)), and **Quit**; others join them as they are
  added to the engine.
- **Game menu.** Esc, a right click, gamepad B (east), or Start opens it during the story;
  so does **Menu** in the quick menu. It shows **Return**, **Save**, **Load**,
  **Settings**, **Main Menu**, and **Quit**, among others (**Codex**, after **History**,
  once the story declares a tip or an item: see
  [lock tip, lock item, unlock](#lock-tip-lock-item-unlock-codex)), over the dimmed scene.
  The story waits while it is open.
- **Quick menu.** Small buttons under the text box, such as **Hide**, **Menu**, **Save**,
  **Q.Save**, **Q.Load**, and **Settings**, shown whenever the text box is. Every one also has a key, so
  players never need the mouse.
- **Questions.** Main Menu and Quit ask "Yes" or "No" first. Esc means No. While
  leaving makes an auto-save, they don't say "Unsaved progress will be lost." (see
  [Saves](#17-saves)).
- **Widget sampler.** In a dev run, Shift+F3 on the title or in the game menu shows every
  kind of button, toggle, slider, and list in every state, with your colors. Use it to
  check a theme, including widgets your game's screens don't show yet.

### Title picture, logo, and music

Put your pictures in the `gui/` folder and your music in `audio/`, then name them:

```toml
[theme.title]
background_image = "gui/title_bg.png"   # 1280x720; other sizes are scaled to fill the screen
logo_image = "gui/logo.png"             # up to 560x200, at the top left
music = "bgm/title.ogg"                 # a file in audio/, played over and over
```

- **The picture** fills the whole screen, keeping its shape; the edges of a picture of
  another shape are cut off. Without one, the title is a plain background that goes from
  `title.fill_top_color` at the top to `title.fill_bottom_color` at the bottom.
- **The logo** sits in a box 560 wide and 200 tall at the top left, at its left edge and
  centered from top to bottom. A bigger logo is made smaller to fit; a smaller one is never
  enlarged. Without a logo, the title shows `[game] title` as large text (two lines at
  most). A logo with a see-through background (PNG) looks best.
- **The music** is a file inside `audio/`, written without `audio/` in front, like the
  files in `play music`. It starts on the title, fades out when a game starts, and starts
  again each time the player comes back to the title.
- If a picture is missing or can't be read, the game warns and uses the plain background,
  the title as text, or the drawn button instead; it never shows a broken picture. Missing
  music is silent, and the log names the file.

### Buttons

```toml
[theme.button]
frame_image = "gui/button.png"   # every button: title, game menu, and questions
frame_slice_width = 24           # the size of the picture's corners
text_color = "#3D2B36"           # the words on the buttons
```

A button frame is a **nine-slice** picture: its four corners (`frame_slice_width` square)
are drawn as they are, and its edges and middle stretch to fit each button, so one small
picture (72x72 is enough) fits every button. Keep the edges the same all along, so they
stretch without a seam. `fill_opacity` makes the whole frame see-through (0.90 by default).

The frame replaces the button's fill and border. A focused, pressed, selected, or disabled
button keeps its drawn look unless you give that state its own picture too, such as
`[theme.button.focused] frame_image`. Keep the words readable on every look: a dark frame
needs a light `text_color`, and then the drawn focused fill (`button.focused.fill_color`,
pink by default) needs a dark color too, or a frame of its own. Text needs at least 4.5:1
contrast with its button over a black and over a white picture.

Without any of these settings, buttons are drawn with the colors in the list below.

### Button words

Every word on a button or in a question can be changed under `[words]`:

```toml
[words]
new_game = "Begin"
confirm_quit = "Leave the festival? Unsaved progress will be lost."
```

| Key | Default |
|---|---|
| `new_game` | "New Game" |
| `load` | "Load" |
| `settings` | "Settings" |
| `extras` | "Extras" |
| `help` | "Help" |
| `quit` | "Quit" |
| `return` | "Return" |
| `history` | "History" |
| `save` | "Save" |
| `main_menu` | "Main Menu" |
| `yes` | "Yes" |
| `no` | "No" |
| `hide` | "Hide" |
| `menu` | "Menu" |
| `on` | "On" |
| `off` | "Off" |
| `loading` | "Loading" |
| `list_empty` | "Nothing here yet." |
| `confirm_main_menu` | "Return to the title screen? Unsaved progress will be lost." |
| `confirm_quit` | "Quit the game? Unsaved progress will be lost." |

A word is plain text, up to 200 characters (the two questions up to 1,000). An empty word
keeps its default, with a warning. A word too wide for its button is made smaller, down to
24, and then ends in "…"; a dev run warns, and tells you which width to raise. The
Saves and Settings pages add words of their own (see [Saves](#17-saves) and
[The Settings page](#the-settings-page)).

### Which buttons show

```toml
[title]
enabled = true                  # false: no title screen
show_version = true             # the version number in the corner
entries = ["new_game", "quit"]  # the title's buttons, in this order

[quick_menu]
enabled = true                  # false: no quick menu
entries = ["hide", "menu"]      # the quick menu's buttons, in this order
```

| Key | Default | Allowed |
|---|---|---|
| `[title] enabled` | `true` | `true` or `false` |
| `[title] show_version` | `true` | `true` or `false` |
| `[title] entries` | not set: every title button in the standard order | a list of button names |
| `[quick_menu] enabled` | `true` | `true` or `false` |
| `[quick_menu] entries` | not set: every quick-menu button in the standard order | a list of button names |

- **The names** are the `[words]` keys of the buttons: on the title `new_game` and `quit`,
  in the quick menu `hide` and `menu` (later screens add theirs: saving adds `load` on the
  title and `save`, `q_save`, and `q_load` in the quick menu), up to 16 names. `codex` is
  on the title only when the list names it (after `extras` in the standard order), and
  then only once the player has a tip. `flowchart` comes after `load` and shows once the
  player has reached a point they can jump to. A name
  that isn't a button of that menu gets a warning with the right spelling and the list of
  names; an empty list shows the standard buttons, with a warning.
- **No title.** With `enabled = false` the story starts as soon as the game opens. At the
  end of the story, or after Main Menu and Yes, the game closes.
- **Testing a late scene.** `--start` skips the title, and every New Game starts at that
  label again ([The scene editor](scene-editor.md)).

### The quick-menu strip

The quick menu sits in the strip between the text box and the bottom of the screen, which
is `[theme.textbox] bottom_gap` tall (32). The quick menu is 28 tall with its text at 20,
so it fits. If you make the strip shorter than 28, the quick menu overlaps the text box; at
a larger text size the quick menu grows to 32 and fills the strip. Turn it off with
`[quick_menu] enabled = false` if you want the text box lower.

### Every theme setting

Each setting goes under `[theme.<area>]` in `config.toml`, with the part before the last
dot as the table: `button.focused.fill_color` is `fill_color` under
`[theme.button.focused]`. Colors are `"#RRGGBB"`; opacity goes from 0.0 (invisible) to 1.0
(solid); sizes and lengths are whole numbers in screen units of the 1280x720 screen; times
(`_ms`) are in milliseconds. Pictures are files in `gui/` (frames are nine-slice), fonts
`.ttf` or `.otf` files in the game folder, and sounds files in `audio/`. Text sizes grow
with the player's text size setting. A wrong name or value gets the usual `config.toml`
warning or error, with a "did you mean".

**Fonts, fades, and panels** (the game menu, questions, and the version label)

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `ui.text_font` | `textbox.text_font` (the text box's font) | | All menu text |
| `ui.bold_font` | `textbox.bold_font` | | Headings and the title as text |
| `ui.fade_ms` | 150 | 0–1000 | Menus fading in and out |
| `ui.back_sound` | none | | Played on Back |
| `panel.fill_color` | `"#FFF4F8"` | | Menu panels and the question box |
| `panel.fill_opacity` | 0.94 | 0.0–1.0 | Their fill or frame |
| `panel.border_color` | `"#F0A0C0"` | | Their border |
| `panel.border_width` | 2 | 0–8 | |
| `panel.corner_radius` | 16 | 0–48 | |
| `panel.frame_image` | none | | A nine-slice picture instead of fill and border |
| `panel.frame_slice_width` | 24 | 0–96 | Its corner size |
| `panel.text_size` | 28 | 24–48 | Questions, list rows, values |
| `panel.text_color` | `"#3D2B36"` | | The same |
| `panel.heading.text_size` | 32 | 24–64 | Headings |
| `panel.heading.text_color` | `"#A02860"` | | Headings |

**Buttons** (every button; the focused look is shared by every widget)

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `button.text_size` | 28 | 24–48 | Button words |
| `button.text_color` | `"#3D2B36"` | | Button words |
| `button.fill_color` | `"#FFF4F8"` | | Fill (also when disabled) |
| `button.fill_opacity` | 0.90 | 0.0–1.0 | Fill or frame, every state |
| `button.border_color` | `"#F0A0C0"` | | Border |
| `button.border_width` | 2 | 0–8 | Border |
| `button.corner_radius` | 12 | 0–28 | Corners |
| `button.frame_image` | none | | Frame picture |
| `button.frame_slice_width` | 24 | 0–96 | Its corner size, every state |
| `button.height` | 56 | 40–120 | Smallest height |
| `button.side_padding` | 32 | 24–80 | Edge to words |
| `button.gap` | 12 | 0–48 | Space between buttons |
| `button.focused.fill_color` | `"#FFD6E8"` | | Focused (and selected) fill |
| `button.focused.border_color` | `"#A02860"` | | Focus outline |
| `button.focused.border_width` | 4 | 2–8 | Focus outline |
| `button.focused.frame_image` | none | | Focused frame picture |
| `button.pressed.fill_color` | `"#FFC2DC"` | | Pressed fill |
| `button.pressed.frame_image` | none | | Pressed frame picture |
| `button.selected.frame_image` | none | | Selected frame picture |
| `button.disabled.text_color` | `"#6E5E68"` | | Words of a button that can't be used |
| `button.disabled.border_width` | 0 | 0–8 | Its border |
| `button.disabled.track_color` | `"#C8B8C2"` | | Tracks of toggles and sliders that can't be used |
| `button.disabled.frame_image` | none | | Disabled frame picture |
| `button.marker.fill_color` | `"#A02860"` | | The focus arrow, on/off dot, and selected bar |
| `button.focus_sound` | none | | Played when the focus moves |
| `button.activate_sound` | none | | Played when a button is used |

**Toggles, sliders, and lists** (later screens, such as Settings; see them in the sampler)

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `toggle.track_color` | `"#7E5C74"` | | Off track and knob |
| `toggle.on.track_color` | `"#A02860"` | | On track |
| `toggle.on.knob_color` | `"#FFFFFF"` | | On knob |
| `slider.track_color` | `"#7E5C74"` | | Empty part of the bar |
| `slider.fill_color` | `"#A02860"` | | Filled part of the bar |
| `slider.thumb_color` | `"#A02860"` | | The handle |
| `slider.thumb_border_color` | `"#FFF4F8"` | | The handle's border |
| `list.row_height` | 48 | 32–120 | Smallest row height |
| `list.divider_color` | `"#F0A0C0"` | | Lines between rows |
| `list.scrollbar_color` | `"#A02860"` | | Scroll bar |
| `list.scrollbar_track_color` | `"#F0D0DE"` | | Scroll bar track |
| `list.empty.text_color` | `"#6E5E68"` | | "Nothing here yet." |

**Title screen**

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `title.background_image` | none | | The title picture |
| `title.logo_image` | none | | The logo |
| `title.music` | none | | Title music |
| `title.fill_top_color` | `"#FFF4F8"` | | Plain background, top |
| `title.fill_bottom_color` | `"#FFD6E8"` | | Plain background, bottom |
| `title.logo.text_size` | 64 | 40–96 | The title as text |
| `title.logo.text_color` | `"#A02860"` | | The title as text |
| `title.button_width` | 320 | 200–560 | Title buttons |
| `title.version.text_size` | 20 | 16–28 | Version number |
| `title.version.text_color` | `"#6E5E68"` | | Version number |
| `title.version.fill_opacity` | 0.90 | 0.0–1.0 | Its label |
| `title.loading.text_color` | `"#FFE6F0"` | | "Loading" on a slow start |
| `title.fade_in_ms` | 500 | 0–2000 | The title fading in from black |

**Game menu and questions**

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `menu.dim_color` | `"#2A1E26"` | | Darkens the scene under menus and questions |
| `menu.dim_opacity` | 0.55 | 0.0–1.0 | How dark, under the game menu |
| `menu.button_width` | 288 | 200–312 | Game-menu buttons |
| `confirm.dim_opacity` | 0.35 | 0.0–1.0 | Extra darkening under a question |
| `confirm.width` | 640 | 480–1000 | The question box |
| `confirm.button_width` | 200 | 160–280 | Yes and No, at least |

**Quick menu**

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `quick_menu.text_size` | 20 | 20–24 | Words (they grow with the text size up to 24) |
| `quick_menu.text_color` | `"#3D2B36"` | | Words |
| `quick_menu.fill_color` | `"#FFF4F8"` | | Background |
| `quick_menu.fill_opacity` | 0.90 | 0.0–1.0 | Background or frame |
| `quick_menu.corner_radius` | 14 | 0–16 | Corners |
| `quick_menu.frame_image` | none | | A nine-slice picture instead of the background |
| `quick_menu.frame_slice_width` | 12 | 0–16 | Its corner size |
| `quick_menu.side_padding` | 12 | 4–24 | Space around each word |
| `quick_menu.bottom_gap` | 2 | 0–32 | Bottom of the screen to the quick menu |
| `quick_menu.focused.text_color` | `"#A02860"` | | Word under the mouse |
| `quick_menu.focused.underline_width` | 2 | 1–4 | Its underline |
| `quick_menu.pressed.fill_color` | `"#FFD6E8"` | | A button being clicked |
| `quick_menu.on.fill_color` | `"#FFD6E8"` | | A button that is on |
| `quick_menu.on.border_color` | `"#A02860"` | | Its border |
| `quick_menu.on.border_width` | 2 | 1–4 | Its border |
| `quick_menu.disabled.text_color` | `"#6E5E68"` | | A button that can't be used |
| `quick_menu.activate_sound` | none | | Played on a click (instead of `button.activate_sound`) |

The text box's own settings are in section 14; every look setting's full description is in
[the UI system](ui-system.md), "Token list".

### The Settings page

Players open **Settings** from the title, the game menu, or the quick menu. Every change
applies at once, with no Apply button, and the game opens the same way next time.

| Group | Rows |
|---|---|
| Display | Fullscreen · Reduce motion and flashing · Timing assist (Normal, Slower, or No time limits) |
| Text | Text speed (10 to 200 letters a second, or Instant) · Text size (100% to 150%) · Auto-advance wait (25% to 400%) · Auto-advance waits for voices · Skip unread text |
| Sound | Master, Music, Sound, and Voice volume (0 to 100) · Text blips · Let voices finish · Play audio when unfocused · Play audio when minimized · Mono audio |
| Data | Use my computer's user name (only with `[meta] username = true`) · Label fake error screens (only when the story has an `effect crash`) · Reset settings · Delete progress (on the title only) |

- **Your `config.toml` gives the starting values**: `[textbox] cps`, `[auto]
  wait_for_voice`, `[skip] all`, the four `[audio]` volumes, `[audio] play_unfocused` and
  `play_minimized`, `[window] fullscreen`, `width`, and `height`, and `[effects]
  timing_assist`. Settings adds no key of its own, only the words below.
- **Only what a player changes is stored.** Every setting they never touched follows your
  `config.toml`, even after an update: raise `[audio] sound_volume` in a patch, and
  everyone who never moved that slider hears the new volume.
- **`[effects] reduce = true`** turns reduced motion on for every player: the toggle shows
  On and can't be turned off (see [Transitions and effects](#16-transitions-and-effects)).
- **Timing assist** sets every time limit in the game: **Normal**, **Slower** (twice the
  time for timed choices and minigames, and half the speed for beats), or **No time
  limits** (timed parts wait for the player). `[effects] timing_assist` (`"normal"`,
  `"slower"`, or `"off"`) is the Timing assist a new player starts with; players change it;
  it never locks the setting.
- **Settings aren't part of the story.** Saves, loading, rollback, and New Game never
  change them, and your script can't read or set them.
- **Reset settings** forgets every stored value after a question, so your `config.toml`
  applies again. **Delete progress**, on the title, asks first, then forgets what the game
  remembers across playthroughs: read text, picked choices, unlocks, and your `persistent`
  values (see [persistent](#persistent-data-across-playthroughs)). Saves and settings are
  kept.
- **Where settings live.** `settings.json` in the game folder's `settings/` during
  development, or the player's own data folder in a release, next to their saves. A
  release needs `[game] id` (see [Saves](#17-saves)); without one, settings last only until
  the game closes, with a warning. Delete `game/settings/` to test as a new player, and
  don't share it with the game.
- **The file belongs to the player**, so it is checked strictly. A value the game can't use
  goes back to its default, and a damaged file is set aside as `settings.bad.json` and every
  setting starts from its default. The game always starts.

Every word on the page can be changed under `[words]`, like the menu words above:

| Key | Default |
|---|---|
| `settings_display`, `settings_text`, `settings_sound`, `settings_data` | "Display", "Text", "Sound", "Data" (the group headings) |
| `fullscreen` | "Fullscreen" |
| `reduce_motion` | "Reduce motion and flashing" |
| `timing_assist`, `timing_normal`, `timing_slower`, `timing_off` | "Timing assist", "Normal", "Slower", "No time limits" |
| `text_speed`, `text_instant` | "Text speed", "Instant" |
| `text_size` | "Text size" |
| `auto_wait`, `auto_voice` | "Auto-advance wait", "Auto-advance waits for voices" |
| `skip_unread` | "Skip unread text" |
| `master_volume`, `music_volume`, `sound_volume`, `voice_volume` | "Master volume", "Music volume", "Sound volume", "Voice volume" |
| `text_blips` | "Text blips" |
| `voice_sustain` | "Let voices finish" |
| `audio_unfocused`, `audio_minimized` | "Play audio when unfocused", "Play audio when minimized" |
| `mono` | "Mono audio" |
| `reset_settings`, `confirm_reset_settings` | "Reset settings", "Reset every setting to its default?" |
| `delete_progress`, `confirm_delete_progress` | "Delete progress", "Delete everything this game remembers between playthroughs, such as read text and unlocked extras? Your saves are kept. This can't be undone." |
| `notice_settings_default` | "Your settings couldn't be read, so the defaults are used." (shown when the file was damaged) |

The page's name and its button are `settings` (above). The rules are those of every word: up
to 200 characters, the two questions up to 1,000; an empty word keeps its default, with a
warning.

These warnings are logged; the game uses the default settings and goes on. `…` stands for
the file, such as `<game>/settings/settings.json`.

| Message | Fix |
|---|---|
| `settings in … couldn't be used (not valid JSON), so the default settings are used. The old file was kept as settings.bad.json.` | Nothing in your game: the file was damaged or edited by hand. Look at `settings.bad.json`, then delete it. |
| `settings in …: text_size_pct must be a whole number from 100 to 150, but found 200, so the default is used.` | Nothing in your game: a value in the file was edited by hand. |
| `settings in … had 2 unknown entries; they were ignored.` | Nothing: they are dropped the next time a setting changes. |
| `settings in … were made by a newer engine version, so only the settings this version knows are used, and the file won't be changed this session.` | The player went back to an older version of the game; the file is kept for the newer one. |
| `settings won't be saved, because config.toml has no [game] id. Set a unique id under [game], e.g. id = "paper-lanterns", before releasing.` | Set `[game] id`. |
| `settings couldn't be saved to … (disk full). Changes apply this session and are tried again at the next change.` | Free some space, or check that the folder can be written. |

### Content warning

A content warning is a full screen shown after the game loads and before the title (or
before the story, with `[title] enabled = false`): your heading, your text, and two
buttons, **I understand** and **Quit**. Turn it on in `config.toml`:

```toml
[content_warning]
show = "once"          # "never" (the default), "once", or "always"
version = 1            # raise it after changing the text to show it once more
min_seconds = 2        # "I understand" can be pressed after this many seconds; 0 = at once
text = """
This game is not suitable for children or those who are easily disturbed.

It contains scenes of self-harm and psychological horror."""
```

| Key | Default | What it does |
|---|---|---|
| `[content_warning] show` | "never" | `"once"` shows it until the player presses I understand; `"always"` at every launch. |
| `[content_warning] text` | not set | Plain text, up to 2,000 characters. A line break stays a line break; a blank line starts a new paragraph. `{b}` and `[` show as written. Required unless `show` is `"never"`. |
| `[content_warning] version` | 1 | 1–1000. With `"once"`, raise it after changing the text and everyone sees the warning once more. |
| `[content_warning] min_seconds` | 2 | 0–10 seconds before I understand can be pressed. |
| `warning_heading` | "Content warning" | Under `[words]`: the heading. |
| `warning_continue` | "I understand" | Under `[words]`: the button that goes on. Quit uses `quit`. |

- **Only a button leaves it.** Esc and the gamepad's B do nothing, and it never closes by
  itself. Quit closes the game at once and remembers nothing.
- **"once" is remembered in the player's settings**, so **Reset settings** shows it again
  at the next launch (Delete progress doesn't). To test it as a new player, delete
  `game/settings/`.
- **Say what's coming.** If your story uses [fourth-wall tricks](#25-fourth-wall-tricks),
  list them: a fake error screen, and the player's user name if you offer it. With
  `[meta] username = true`, the name question comes right after the warning.
- **It isn't shown** when you start from a label (`--start`, `--set`, or Studio's "play
  from here"), and only once per launch: returning to the title doesn't show it again.
- **Keep it short.** About 220 characters fit without scrolling at the largest text size
  (about 600 at the default size); longer text scrolls. In a dev run the game warns when
  that happens:
  `config.toml: [content_warning] text needs 9 lines at 150% text size but 5 fit, so
  players with large text must scroll to read it. About 220 characters fit without
  scrolling.` Fix: shorten the text, or accept the scrolling.

### When something is wrong

These are warnings: the game still starts, and the default is used.

| Message | Fix |
|---|---|
| `config.toml: [theme.button] frame_image "gui/buton.png" doesn't exist, so the drawn button is used. Did you mean "gui/button.png"?` | Fix the file name. The same message names the logo, the title picture, and other frames. |
| `config.toml: [theme.title] logo_image "gui/logo.png" doesn't exist, so the game's title is shown as text.` | Add the picture, or remove the line. |
| `config.toml: [theme.ui] text_font "fonts/Lora.ttf" couldn't be read as a font, so the text box font is used.` | Use a `.ttf` or `.otf` font file. |
| `config.toml: [words] new_game is empty, so "New Game" is shown. Write the words to show, e.g. new_game = "Begin".` | Write the words, or remove the line. |
| `config.toml: [quick_menu] entries has "hied", which isn't a quick-menu button. Did you mean "hide"? The buttons are hide and menu.` | Use a name from the list. |
| `config.toml: [words] main_menu "Return to the main title screen" doesn't fit its button at text size 28, so it shows as "Return to the main…". Use fewer words, or widen the button with [theme.menu] button_width.` (dev runs) | Shorten the words, or widen the buttons. |

---

## 16. Transitions and effects

A **transition** changes the picture over time instead of all at once: `with dissolve`
blends, `with fade` goes through black. Two **effects** act on the picture for a moment:
`shake` and `flash`. `pause` holds the story for a beat. They only change what the player
sees: lines, choices, variables, and saves are the same whether they play in full, are
clicked through, or are turned down. The example game uses each one, with a comment above
its first use. Glitches (`effect`) have their own section: [Glitch effects](#24-glitch-effects).

### with
```
    scene bg bridge_night with fade
    show hana surprised with dissolve 0.3
    hide daichi with dissolve
    scene bg river_dusk with fade 2.0 white
    scene bg river_dusk with fade 0.4 "#ffe08a"
    show hana at left with cut
```
`with` and a transition's name go last on a `scene`, `show`, or `hide` line (and on a
[chapter](#chapter) line, for its card).

| Transition | What it does | Length when none is given |
|---|---|---|
| `cut` | The new picture at once, as with no `with` | 0 |
| `dissolve` | Blends the old picture into the new one | 0.5 seconds |
| `fade` | The old picture fades to black, then the new one fades in | 1.0 second, half each way |
| `glitch` | Tears the old picture, cuts to the new one, and calms; see [Glitch effects](#24-glitch-effects) | 0.5 seconds |
| a name you `define` | See [Your own transitions](#your-own-transitions) | its own |

After the name, in any order and each at most once:
- **a length** in seconds, 0 to 30, with no unit: `with dissolve 1.5`. 0 is a cut.
- **a color**, for `fade` only: `white`, `black`, `red`, or `"#RRGGBB"` in quotes (a `#`
  outside quotes starts a comment). Black when left out.

`cut` takes neither. Names are checked when the game starts, after every `define`, so a
misspelled one stops the launch with a "Did you mean".

**One moment, one transition.** A `with` plays every change since the picture was last
shown, all together:
```
    scene bg bridge_night
    show hana happy at left
    show daichi smile at right with fade
```
The bridge and both characters fade in at once; the empty bridge is never shown. Changes
after the last `with` appear with the next line, at once. Two `with` lines in a row play
one after the other. A word on a dialogue line (`hana pout "…"`) always changes with its
line, at once.

**The story waits** for a transition before the next line, choice, or pause. The text box
is hidden during one that includes a `scene`; otherwise it stays, empty. A click (or any
key that moves the story on) finishes the transition at once, and the next line then
types as usual. A picture that doesn't change takes no time.

**Saves and rollback.** A transition, pause, or effect is never a place to save or roll
back to: a save made during one stores the line before it, and loading or rolling back
shows that line's picture at once, with no transition.

### shake
```
    shake
    shake large
    shake small horizontal 2.0
```
Shakes the stage picture; the text box and menus stay still. In any order, each at most
once: a size, `small`, `medium` (the default), or `large`; a direction, `horizontal` or
`vertical` (both when left out); and a length from 0.1 to 10 seconds (0.5 when left out).
It starts with whatever is shown next (a line, a choice, a `with`, or a `pause`) and never
holds up the text. A second `shake` before then wins.

### flash
```
    flash
    flash red
    flash "#ffe08a" 0.6
```
Covers the stage with a color, under the text box, that fades back. In any order, each at
most once: a color as for `fade` (white when left out) and a fade-back length from 0.1 to
2 seconds (0.3 when left out). Like `shake`, it starts with what is shown next and never
holds up the text.

**At most 3 flashes a second.** To protect players who are sensitive to flashing, the game
never shows more than 3 flashes in any one second, whatever the script says. Each `flash`
counts, and so does each `fade` shorter than 1 second (it goes dark and back). An extra
flash isn't shown and an extra short fade plays as a dissolve; the story goes on the same,
and the log says so.

**Reduced effects.** Players can turn on **Reduce motion and flashing** in Settings, and
`[effects] reduce = true` turns it on for everyone. Then `shake` doesn't move, and a
`flash` becomes a soft brightening to half strength, at least 0.3 seconds each way and at
most one a second. `cut`, `dissolve`, `fade`, and your `Mask` transitions play as usual.

**Don't let a flash or shake carry the story on its own.** Some players turn effects
down, and some can't see them well. Say what happened in the line too, or play a sound
with it: the example game's firework has both.

### pause
```
    scene bg river_dusk with fade
    pause 1.5
    pause
```
Holds the story: `pause 1.5` for that many seconds (0.1 to 30), `pause` alone until the
player clicks. A click ends a timed pause early. Changes waiting to be shown appear first,
at once, and a `shake` or `flash` written before it starts with it. The text box stays
empty meanwhile, and a pause is never a save point.

### Your own transitions
```
define slow_dissolve = Dissolve(1.5)
define white_fade = Fade(0.6, color="#ffffff")
define lantern = Mask("masks/lantern_glow.png", 1.2)
define lantern_out = Mask("masks/lantern_glow.png", 1.2, reverse=True)
```
A `define` names a transition, used like a built-in one: `with lantern`, or
`with slow_dissolve 2.0` for another length.

| Write | Arguments |
|---|---|
| `Dissolve(seconds)` | seconds 0–30, 0.5 when left out |
| `Fade(seconds, color=…)` | seconds 0–30, 1.0 when left out; `color` `"white"`, `"black"`, `"red"`, or `"#RRGGBB"`, black when left out |
| `Mask(file, seconds, soft=…, reverse=…)` | a picture file (below); seconds 0–30, 1.0 when left out; `soft` 0–0.5, 0.1 when left out; `reverse=True` or `False` |

**Masks.** `Mask` uncovers the new picture through a gray picture: where it is black
first, where it is white last, with a soft edge `soft` wide (a fraction of the way from
black to white). `reverse=True` uncovers the white parts first. The file is a path from
the game folder, like an [image](#image)'s: the example game's is
`game/masks/lantern_glow.png`, darkest in the middle, with its license in
`game/masks/LICENSES.txt`.
- **Use a gray picture no bigger than 640×360**, a PNG whose every pixel has equal red,
  green, and blue. The game reads it exactly and scales it to the screen.
- A colored picture still works, but it is turned gray by an approximate formula, so
  areas you meant to be the same shade may not open together.
- A missing file is a warning at launch. A missing file, or one that can't be used
  (damaged, or over the engine's picture size limits), plays as a `dissolve`.
- Reduced effects don't change a `Mask`, and it never counts as a flash.

`cut`, `dissolve`, and `fade` can't be redefined. `Dissolve`, `Fade`, and `Mask` are engine
names, like `Character`; `Transition` is kept for a later version. A `define` that isn't a
transition is fine until a `with` uses it.

**Settings in `config.toml`.** The lengths and colors used when the script gives none:
```toml
[effects]
dissolve = 0.5            # seconds, 0 to 30
fade = 1.0                # seconds, 0 to 30
shake = 0.5               # seconds, 0.1 to 10
shake_size = "medium"     # small, medium, or large
flash = 0.3               # seconds, 0.1 to 2
reduce = false            # true: reduced effects for every player
timing_assist = "normal"  # the Timing assist a new player starts with: normal, slower, or off

[theme.effects]
flash_color = "#FFFFFF"
fade_color = "#000000"
```

### When something is wrong
Errors stop the launch with the file and line; warnings let the game start.

| Code | Message | Fix |
|---|---|---|
| E190 | `there is no transition "disolve". Did you mean "dissolve"?` / `there is no transition "swirl". The transitions are cut, dissolve, fade, and the ones this game defines: lantern, slow_dissolve.` | Fix the spelling, or `define` the transition. |
| E191 | `with hana: hana is a Character, not a transition. Use cut, dissolve, or fade, or define one, e.g. define slow = Dissolve(1.5).` | Use a transition's name after `with`. |
| E192 | `with dissolve takes a length from 0 to 30 seconds, but this has 90.` / `lengths have no units: write 0.5, not 0.5s.` / `write 0.5, not .5.` | Write plain seconds from 0 to 30. |
| E193 | `"#e0505" isn't a color. Write "#" and six digits or letters a to f in quotes, e.g. "#ffe08a", or use white, black, or red.` / `"pink" isn't a color here. Use white, black, red, or a color in quotes such as "#ffc0cb".` | Write `"#"` and six digits or letters a–f in quotes, or white, black, or red. |
| E194 | `cut takes no length or color.` / `dissolve takes a length but no color; only fade goes through a color.` / `with fade has two lengths; give one.` / `this line has "slowly" left over after with dissolve. with takes a transition name, then a length and, for fade, a color.` / `with lantern: lantern is a Mask, so it takes a length but no color; only fade goes through a color.` | Write the name, then at most one length and, for a fade, one color. |
| E195 | `shake takes small, medium, or large, horizontal or vertical, and a length from 0.1 to 10 seconds, but this has "huge".` / `shake takes a length from 0.1 to 10 seconds, but this has 30.` / `shake has two sizes; give one.` | `small`, `medium`, or `large`; `horizontal` or `vertical`; 0.1 to 10 seconds. |
| E196 | `flash takes a color and a length from 0.1 to 2 seconds, but this has 5.` / `flash has two colors; give one.` | One color and 0.1 to 2 seconds. |
| E197 | `pause takes a length from 0.1 to 30 seconds, or nothing to wait for a click, but this has 45.` | 0.1 to 30 seconds, or nothing. |
| E198 | `dissolve is a built-in transition, so define can't use that name. Pick another, e.g. dissolve_slow.` | Pick another name. |
| E199 | `Mask needs an image file in quotes, e.g. Mask("masks/iris.png", 1.0).` / `Dissolve takes seconds from 0 to 30, but this has -1.` / `Mask's soft takes a number from 0 to 0.5, but this has 2.` / `Mask needs a PNG, JPEG, or WebP image, but "masks/iris.gif" isn't one. Convert it to .png.` | Fix the argument (see [Your own transitions](#your-own-transitions)). |
| W60 | `Mask uses "masks/iris.png", which doesn't exist, so lantern plays as a dissolve. Did you mean "masks/iris.webp"?` (warning) | Add the file, or fix the path. |
| W61 | `the flash from this line wasn't shown, because the game shows at most 3 flashes a second to protect players who are sensitive to flashing.` / `the fade from this line played as a dissolve, because the game shows at most 3 flashes a second to protect players who are sensitive to flashing.` (warning, while playing) | Space the flashes out, or make the fade 1 second or longer. |
| W62 | `the transition "dissolve" couldn't be drawn (MemoryError), so the picture changed instantly. dissolve plays as a cut for the rest of this run.` (warning, while playing) | Nothing to fix in the script: the story goes on. If it keeps happening, close other programs; report it with the log. |

---

## 17. Saves

Players can save at any line or menu and come back to it later. Your script needs nothing
for this: the Save and Load pages, quick saves, and auto-saves come with every game. This
section says what players see, where saves live, how to keep saves working when you update
your game, and how to change the save settings.

- **Save and Load.** Esc opens the game menu. Its **Save** page shows numbered pages of six
  slots; **Load** shows the **Auto** and **Quick** pages first, then the numbered ones. The
  title screen has **Load** too. A slot shows a small picture of the scene, the date and
  time, and the line it was saved at (or its chapter's name, see [chapter](#chapter)).
  Saving over a slot, loading during a game, and deleting a save (the Delete key, or the ×
  on a slot) each ask first.
- **Quick saves.** F5, or **Q.Save** in the quick menu, saves to the Quick page at once and
  shows "Quick saved." F9, or **Q.Load**, loads the newest quick save after asking. The
  Quick page keeps six; each new quick save replaces the oldest.
- **Auto-saves** go to the Auto page, which also keeps six: every 5 minutes of play (time in
  menus doesn't count), when a menu of choices appears, at the first line after each
  `chapter`, and when the player leaves by Main Menu or Quit. Because of that last one, the
  Main Menu and Quit questions leave out "Unsaved progress will be lost."
- **What a save holds:** the line or menu on screen, the backgrounds and sprites, the music
  and looping sounds, every story variable, the choices picked so far, and the `dice`
  results still to come. Loading shows the line again from its start, with the saved music
  (from the beginning of the song, unless that song is already playing). A save made while
  a line is still typing holds that line; one made during a transition or a `pause` holds
  the line before it.
- **Not in a save:** settings, the window size, volumes, and `persistent` data. Loading
  never changes them.

### Where saves live

| Run | Folder |
|---|---|
| While you make the game (`python main.py`, `python -m engine run`) | `saves/` in the game folder |
| A release (`--release`, or a built game) | the player's own folder: `%APPDATA%\vn-engine\<id>\saves` on Windows, `~/Library/Application Support/vn-engine/<id>/saves` on macOS, `~/.local/share/vn-engine/<id>/saves` on Linux |

Each slot is one file named after its page and slot: `auto-1.vnsave`, `quick-2.vnsave`,
`page3-4.vnsave` (page 3, slot 4). Players back up or share a save by copying one file, and
a save copied between Windows, macOS, and Linux loads. The game reads only files with these
names and never deletes any other file in the folder.

- **A release needs `[game] id`.** `<id>` above is `[game] id` in `config.toml`: lowercase
  letters, digits, and `-`, up to 40 characters.

  ```toml
  [game]
  title = "Paper Lanterns"
  id = "paper-lanterns"
  ```

  Without it a release still runs but can't save: Save, Load, Q.Save, and Q.Load are hidden,
  F5 and F9 do nothing, and the log says why. Choose the id once and never change it after
  release: players' saves and persistent data are found by it.
- **Test a release** with `python main.py --release`, or
  `python -m engine run <game folder> --release`. Saves then go to your own per-user folder,
  as a player's would, and you see what a player sees when `[game] id` is missing.
- **Builds leave out `saves/`.** The game folder's `saves/` holds your own test saves, not a
  player's. If you copy the game folder by hand to share it, leave `saves/` out too (and
  `logs/`, `persistent/`, and `settings/`).

### Keeping saves working when you update the game

Players keep their saves when you release a fixed or longer version. A save remembers the
line it was made at and finds that line again in the new script, so these changes are safe:

- **Add, remove, or move other lines, menus, and labels.** A save at a line you didn't
  change loads at that exact line.
- **Give every new variable a `default`.** A save made before the variable existed loads
  with its starting value, so the new scene works for old saves too:

  ```
  default trust = 0
  default met_daichi = False    # new in version 1.1: older saves load with False
  ```

  A variable created only by a `$` line doesn't exist in older saves, and the first line
  that reads it stops the story.
- **Keep label names.** A save inside a label you rename can't find its line any more.
  Rename labels only before your first release.

When the saved line itself was rewritten or deleted, loading asks the player "The story has
changed since this save. Continue from the nearest point?" Yes goes on from the line that
now stands in that place; No leaves everything as it was. When no nearby point can be found
(the label is gone, for example), the slot can't be loaded and the player sees "This save no
longer fits the story and can't be loaded." In a dev run the log names the save's label and
statement, so you can see which edit did it:
`couldn't load Slot 3: the saved line in label bridge (statement 4) is gone; offering the nearest point`.

To check an update, keep a few saves from the old version (copy the `saves/` folder), make
your changes, and load each one.

A save made by a later version of the engine than the one your game ships with shows "Made
by a newer version of the game." on the Load page and isn't loaded; it is never called
damaged, and loading it again in the newer version works. (Each save records the engine's
save revision for this.) Saves from older versions always load.

### Saves are input

A save file is plain text that players can edit and share, so treat what it holds like
anything a player types:

- **A shared save can start the story at any line or menu, with any values** its variables
  can hold: `trust` at 99 before the scene that raises it, or a flag set without its scene.
  Don't count on the story having reached a line "the normal way"; check the values you
  need.
- **`default` runs on the restored values.** When a save from before a `default` is
  loaded, that `default` runs with the save's variables already set, so
  `default ratio = 10 // trust` stops the load (the player sees "This save couldn't be
  loaded.") for a save with `trust` 0. Keep defaults to plain starting values.
- **Never build a file name from a story variable**, in a `$` line or anywhere else: a value
  from a shared save could name any file on the player's computer.
- **Never put values from the player's computer in a story variable**: their user name, a
  folder path, the computer's name. A save carries them to everyone it is shared with, and
  the Load page shows its line and picture.
- **`$` code can read the player's identity** (`getpass.getuser()`, `os.environ`), and
  doing so puts it into saves, history, and persistent data, which players share. Use
  `{username}` instead: it shows the name on screen only, with the player's permission,
  and saves hold "friend" (see [Fourth-wall tricks](#25-fourth-wall-tricks)).

### Settings in config.toml

Every key is optional; the example game's `config.toml` lists them with their defaults.

```toml
[saves]
pages = 10  # numbered pages of 6 slots on the Save and Load pages
autosave_interval = 300  # 5 minutes
autosave_choices = true  # auto-save when a menu of choices appears
autosave_quit = true  # auto-save when the player leaves by Main Menu or Quit
confirm_quick_load = true  # false: F9 and Q.Load load without asking
```

| Key | Default | Allowed |
|---|---|---|
| `[saves] pages` | `10` | 1–100 |
| `[saves] autosave_interval` | `300` | `0` (off) or 60–3600 seconds of play |
| `[saves] autosave_choices` | `true` | `true` or `false` |
| `[saves] autosave_quit` | `true` | `true` or `false`; with `false` the Main Menu and Quit questions say "Unsaved progress will be lost." |
| `[saves] confirm_quick_load` | `true` | `true` or `false` |

With fewer pages, saves on the pages left out stay in the folder but aren't shown; raising
`pages` again brings them back. A value outside its range gets the usual `config.toml`
warning, and the default is used.

**Words.** Every word of the Save and Load pages, their questions, and the notices can be
changed under `[words]`, like the menu words in section 15. Slot names are the word, a
space, and the number ("Slot 3", "Auto 2", "Quick 1"); a failed save shows "Couldn't save:",
a space, and the reason.

| Key | Default |
|---|---|
| `q_save` | "Q.Save" |
| `q_load` | "Q.Load" |
| `save_page_auto` | "Auto" |
| `save_page_quick` | "Quick" |
| `save_slot` | "Slot" |
| `save_newest` | "Newest" |
| `save_empty` | "Empty slot" |
| `save_loading` | "Loading…" |
| `save_no_picture` | "No picture" |
| `save_none` | "No saves yet." |
| `save_damaged` | "Damaged save" |
| `save_newer` | "Made by a newer version of the game." |
| `save_other_game` | "This save is from a different game." |
| `confirm_overwrite` | "Overwrite this save?" |
| `confirm_delete` | "Delete this save?" |
| `confirm_load` | "Load this save? Unsaved progress will be lost." |
| `confirm_nearest` | "The story has changed since this save. Continue from the nearest point?" |
| `confirm_main_menu_autosave` | "Return to the title screen?" |
| `confirm_quit_autosave` | "Quit the game?" |
| `notice_quick_saved` | "Quick saved." |
| `notice_no_quick_save` | "No quick save yet." |
| `notice_cant_save` | "Can't save right now." |
| `notice_save_failed` | "Couldn't save:" |
| `save_reason_disk_full` | "the disk is full." |
| `save_reason_folder` | "the save folder can't be written." |
| `save_reason_other` | "the file couldn't be written." |
| `save_reason_slots` | "every slot on that page holds a save this version can't replace." |
| `notice_too_large` | "This save is too large." |
| `notice_load_damaged` | "This save is damaged and can't be loaded." |
| `notice_load_no_fit` | "This save no longer fits the story and can't be loaded." |
| `notice_load_failed` | "This save couldn't be loaded." |
| `notice_delete_failed` | "Couldn't delete this save." |

A word is plain text, up to 200 characters (the `confirm_` questions up to 1,000).

**Looks.** The slots and the notices (the small messages in the top-right corner, such as
"Quick saved.") follow the menu theme. These settings change them, as in "Every theme
setting" in section 15:

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `save.text_size` | 24 | 24–36 | A slot's date, line, and tags |
| `save.badge.fill_color`, `.fill_opacity`, `.text_color` | `"#FFF4F8"`, 0.90, `"#3D2B36"` | | The tag with the slot's name |
| `save.newest.fill_color`, `.text_color` | `"#A02860"`, `"#FFFFFF"` | | The "Newest" tag |
| `save.placeholder.fill_color`, `.text_color` | `"#F0D0DE"`, `"#3D2B36"` | | An empty or damaged slot |
| `save.no_picture_image` | none | | A picture in `gui/` for a save without one |
| `save.load_fade_ms` | 300 | 0–2000 | The fade from black after a load |
| `notice.fill_color`, `.fill_opacity`, `.border_color` | the panel's | | A notice's box |
| `notice.border_width`, `.corner_radius` | 2, 12 | 0–8, 0–28 | |
| `notice.frame_image`, `.frame_slice_width` | none, 24 | 0–96 | A nine-slice picture instead |
| `notice.text_size`, `.text_color` | 24, the panel's | 24–36 | |
| `notice.marker.fill_color` | the buttons' marker | | The bar of a problem notice |
| `notice.max_width` | 560 | 320–800 | |
| `notice.duration_ms`, `.fade_ms` | 1500, 200 | 1000–10000, 0–1000 | How long a notice shows, and its fade |
| `notice.sound` | none | | A sound in `audio/` played with each notice |

### When something is wrong

These are warnings in the log; the game goes on.

| Code | Message | Fix |
|---|---|---|
| W80 | `saving is off: a release run needs [game] id in config.toml` | Add `id` under `[game]`. |
| W81 | `saves can't be written this session: the save folder <game>/saves is a link` / `… is not a real folder` / `… couldn't be created` | Make `saves/` a real folder in the game folder, or delete it so the game makes one. |
| W82 | `couldn't load Slot 3: the saved line in label bridge (statement 4) is gone; offering the nearest point` / `… is gone and no nearby point was found` / `couldn't load Slot 3: it was made by a different game` (dev runs only) | See "Keeping saves working" above. |
| W83 | `couldn't save to Slot 3: disk full` / `… no permission` / `… couldn't write` / `couldn't delete Slot 3: …` | Free some disk space, or check that the save folder can be written. |

---

## 18. Rollback

Players can step back through the lines and menus they have already read, and forward
again. Your script needs nothing for this: rollback works in every game from the first
line.

- **Back:** mouse wheel up, Page Up, the gamepad's left shoulder button, or **Back** in the
  quick menu. Each notch or press is one step: one line, or one menu with its question.
- **Forward:** wheel down, Page Down, or the right shoulder button, through the lines
  already read. Clicking on a line read before just goes on with the story, as usual.
- **A step looks as it did.** The same backgrounds, sprites, music, variables, history, and
  `dice` results. The line shows complete, with no typing, transition, shake, or flash.
- **Picking again.** Back at a menu, the player can pick any choice. The same pick keeps the
  lines read after it. A different pick drops them, and the story goes on down the new
  branch.
- **Where back stops:** the first line of a new game, the line a save was loaded at, a
  `rollback block`, anything read while rollback is off, and `[rollback] steps` steps back
  (100). There, a small mark appears on the text box and Back in the quick menu is grayed
  out. Neither says why, so a stop never gives away a scare.
- While the player reads the past, a small tag in the top-left corner shows how many steps
  back they are.

### What is and isn't rolled back

| Rolled back | Not rolled back |
|---|---|
| The line or menu on screen, the backgrounds and sprites, the music and looping sounds | `persistent` data |
| Every story variable and meter (`points`) | Which lines were read and which choices were picked (used by skip and the choice marks), and unlocks |
| The `dice` results still to come | The player's settings |
| The choices picked, the History log, and the `call` stack | `define` values (a defined list changed by a `$` line stays changed) |
| Whether rollback is on or off | Anything outside the story: files, the clock, other Python modules |
| | Meta files: `file write` and `file delete` never run twice; each one blocks rollback |

**Going forward runs the story again.** The lines between two steps run again as the player
moves forward, by wheel or by click. Story variables and `dice` come back as they were at
the step, so they give the same results. What isn't rolled back changes a second time:

```
default persistent.count = 0

label festival_end:
    "The last lantern drifted out of sight."
    $ persistent.count += 1
    "Next year, then."
```

A player who reaches "Next year, then.", scrolls back to "The last lantern…", and scrolls
forward again runs `$ persistent.count += 1` twice: one festival, counted 2. Two fixes:

- **Set a value instead of adding to one.** Running `$ persistent.saw_festival = True` twice
  changes nothing.
- **Block rollback right after it.** The player can never step back to a line before the
  block, so the line above it never runs twice:

```
default persistent.count = 0

label festival_end:
    "The last lantern drifted out of sight."
    $ persistent.count += 1
    rollback block
    "Next year, then."
```

The same goes for anything else that stays done, such as a file a `$` line writes: block
rollback right after it. `file write` and `file delete` (see [Meta files](#23-meta-files))
block rollback by themselves.

### Stopping rollback

Four lines control rollback. Each goes on a line of its own inside a label.

| Line | What it does |
|---|---|
| `rollback block` | A wall: the player can't step back past this point. The lines after it roll back as usual. |
| `rollback off` | Turns rollback off. Back does nothing, and no line read while it is off can be stepped back to later. |
| `rollback on` | Turns rollback on again. The first line after it is as far back as the player can go. |
| `rollback fixed` | Goes on the line right above a `menu:`. The player can step back through that menu, but can't change the pick. |

Rollback is on until a `rollback off`. Running one of these lines again, as the story does
going forward, changes nothing more. On and off are saved with the game: a save made while
rollback is off loads with it off.

**A scare** only works once. Block rollback right after it, so the player can't scroll back
and replay it:

```
label shrine:
    "The lanterns along the path went out, one by one."
    flash red
    shake large
    "Something was standing where Hana had been."
    rollback block
    hana "...Did you see that?"
```

**A choice that can't be undone.** Put `rollback block` first in the choice's lines. Once
the player picks it, they can't step back to the menu:

```
default told_daichi = False

label truth:
    menu:
        hana "Will you tell Daichi the truth?"
        "Tell him":
            rollback block
            $ told_daichi = True
            daichi "...Thank you for telling me."
        "Keep it to yourself":
            $ told_daichi = False
```

**A fixed choice** is the softer version. The player can step back through the menu and the
lines before it, but only the choice they picked can be picked again; the others show
locked. The first time the menu appears, or after a load, it is a normal menu.

```
default going = False

label invitation:
    rollback fixed
    menu:
        daichi "The fireworks start at nine. Will you come?"
        "Yes":
            $ going = True
        "Not this year":
            $ going = False
```

**A tense run of lines**, such as a chase, can turn rollback off before it and on after it.
Once it is on again, the player can step back only to the lines after `rollback on`:

```
label chase:
    "Footsteps behind me. Running."
    rollback off
    "I didn't look back."
    "Left at the shrine, down the stone steps, into the crowd."
    rollback on
    hana "There you are! Where did you run off to?"
```

A block never takes away the player's saves or the game menu. Let the words carry a scare
too, not only a flash or shake, for players who turn effects down.

### Settings in config.toml

```toml
[rollback]
steps = 100  # how many steps back a player can go; 0 turns rollback off for the game
marker = true  # false: no tag in the corner while the player reads the past
```

| Key | Default | Allowed |
|---|---|---|
| `[rollback] steps` | `100` | 0–1,000. `0` turns rollback off for the whole game: the wheel does nothing and the quick menu has no Back |
| `[rollback] marker` | `true` | `true` or `false` |

Each step kept holds a copy of the story's variables, so more steps use more memory: about
0.2 MB a step in a game with 1,000 variables. A game whose choices must always stick, such
as a trial, can set `steps = 0`.

**Words and looks.** The quick menu's Back is the word `back` under `[words]` ("Back"). The
mark that shows where back stops is set in `[theme.rollback]`, as in "Every theme setting"
in section 15:

| Setting | Default | Range | What it changes |
|---|---|---|---|
| `rollback.mark.fill_color`, `.border_color`, `.glyph_color` | `"#FFE6F0"`, `"#F0A0C0"`, `"#A02860"` | | The mark: a small pill on the text box's top edge with a bar over an up-arrow |
| `rollback.mark.image` | none | | A picture in `gui/` drawn instead of the pill |
| `rollback.bump_height` | 6 | 0–12 | How far the text box jumps up with the mark; 0: no jump (never with reduced motion) |
| `rollback.limit_sound` | none | | A sound in `audio/` played as the mark appears |

In dev runs a glyph color too close to the fill is warned about: `config.toml:
[theme.rollback.mark] glyph_color #F0B0C8 is hard to see on fill_color #FFE6F0 (1.4:1;
marks need at least 3:1). Pick a darker glyph_color.` A missing picture gives
`config.toml: [theme.rollback.mark] image "gui/mrak.png" doesn't exist, so the drawn limit
mark is used. Did you mean "gui/mark.png"?`

### When something is wrong

The game checks `rollback` lines at launch and lists every mistake with its file and line.
W90 is a warning in the log; the game goes on.

| Code | Message | Fix |
|---|---|---|
| E200 | `rollback needs one word after it: block, off, on, or fixed. Write "rollback block" to stop rollback here.` | Add `block`, `off`, `on`, or `fixed`. |
| E201 | `"of" isn't a rollback word. Did you mean "off"? rollback takes block, off, on, or fixed.` / `"back" isn't a rollback word. rollback takes block, off, on, or fixed.` | Fix the word. |
| E202 | `rollback off takes nothing after "off", but this line goes on with "now". Put anything else on its own line.` | Put the rest on a line of its own. |
| E203 | `rollback doesn't take a block. Remove the ":" and un-indent the lines under it.` | Remove the `:` and un-indent the lines under it. |
| E204 | `rollback fixed must be the line right above a menu: or a minigame line, but the next line here is a line of dialogue (line 31). Move it above the menu or minigame, or use "rollback block".` / `rollback fixed must be the line right above a menu: or a minigame line, but nothing comes after it here. Move it above the menu or minigame, or use "rollback block".` | Move it to the line right above `menu:`, or use `rollback block`. |
| W90 | `Rollback stopped: a step in label "bridge" no longer matches the script (it was changed), so it and older steps were dropped.` / `… uses a different script version, …` / `… failed while filling a default (see the error above), …` | The script changed while the game ran, or a `default` now fails. The player stays on the line they were reading; fix the `default` if the log names one. |

---

## 19. Reserved words
**(proposed, F02)**

These 40 words can't be names, in any capitals. Some aren't available yet; they're
reserved so your script keeps working when they arrive.

| Words | Status |
|---|---|
| `label` `jump` `call` `return` `if` `elif` `else` `define` `include` | available |
| `default` | available |
| `scene` `show` `hide` `at` `behind` `as` `image` | available |
| `window` | coming: text box |
| `menu` | available |
| `play` `stop` `queue` `voice` | available |
| `with` `shake` `flash` `pause` | available |
| `chapter` | available |
| `points` | available |
| `nvl` | available |
| `ending` `lock` `unlock` | available |
| `minigame` | available |
| `effect` | available |
| `file` | available |
| `rollback` | available |
| `flowchart` | available |
| `python` | not supported; use `$` lines |

`tear`, `colorshift`, `static`, and `jitter`, the glitches, aren't reserved: like `on` and
`off`, they mean something only right after `effect`, so `default static = 0` still works.
The same goes for `window_title` and `crash` ([Fourth-wall tricks](#25-fourth-wall-tricks)).
`tip` and `item` aren't reserved: they mean something only right after `lock` or `unlock`,
so `default item = None` still works. `ranks` is the same: it means something only on a
`points` line, right before a quoted label. `codex`, like `dice` and `points`, is an engine name,
so it can't be a variable, a label, or a character.
`gallery` isn't reserved either: it means something only right after `lock` or `unlock`
([lock gallery, unlock gallery](#lock-gallery-unlock-gallery)), so `default gallery = []`
still works. `cg` is no longer reserved: a picture in `images/cg/` is `cg name`, and `cg`
can be a variable.

### New words stay free (the positional-words rule)

The 40 words above are the last ones reserved. Every word the language adds from now on is
a **positional word**: it means something only in its own place, and everywhere else it is
an ordinary name. So a game written today never breaks when a later version adds a word.

- **A word inside a statement** (like `tip`, `item`, `gallery`, `ranks`, `meter`) is that
  word only right where the statement expects it, and usually only when what it needs
  follows (for `ranks`, a quoted label; for `meter`, meter names after `show` or `hide`). Anywhere else it is a name: `points ranks 0 to 10` declares a
  meter called `ranks`.
- **A new statement word** is that statement only at the start of its own line. A line
  that starts with the word and then a quote, like `event "Wait for me!"`, stays dialogue
  by a character of that name. `$` lines, conditions, and values are Python, where the word
  is always a name: `$ event = 3`. The first is `clock` (story time): `clock next` moves
  time, `clock "Tick."` is a character speaking, and when a `clock` line is neither, the
  error says how to write each. `send` and `open` (Messages) work the same way.
- Names an engine name gives you (like `points.highest` and `points.rank`) are taken on
  that name only: a meter can't be called `rank`, but a variable can.

---

## 20. Coming later
**(proposed, F02)**

Every statement follows one pattern: `verb target [modifiers] [with transition]`, e.g.
`show hana happy at left with dissolve`. Text uses the same quotes and escapes as
dialogue, times are plain seconds (`fadein 2.0`), and `with …` comes last. Each statement
gets its own section here when it is planned.

---

## 21. Common errors
**(proposed, F02)**

The game checks every file at launch and lists every problem (up to 50) with file, line,
and what to do. The log also shows the line with a `^` under the exact spot. Messages are
shortened below.

### Files
| Message | Fix |
|---|---|
| `this file isn't saved as UTF-8. …` / `… is saved as UTF-16. …` | Re-save the file as UTF-8. |
| `… doesn't look like a text file. …` | A non-text file has a `.vns` name. Rename or remove it. |
| `this line contains an invisible character (U+0007). …` / `… a hidden line-separator character …` | Delete and retype around the column given. |
| `this line contains a hidden text-direction character (U+202E), …` | Direction marks are only allowed inside dialogue and narration. In a Python string, use an escape instead. |
| `The story has more than 1,000,000 statements …` / `… more than 250,000 pieces of Python …` / `The story's Python adds up to more than 4,000,000 characters …` | Remove unneeded includes; keep large data out of the script. |
| `… is larger than 16 MB. …` / `The story's files add up to more than 256 MB. …` | Split big files; remove unneeded includes. |
| `script/main.vns doesn't exist. Did you mean "Main.vns"? …` | The first file must be named exactly `main.vns`. |
| `script/main.vns is a folder. …` / `… couldn't be read. …` / `… points to a place outside the game folder. …` | Make `main.vns` a normal, readable file inside the game's `script` folder. |

### Indentation
| Message | Fix |
|---|---|
| `this line is indented with a tab, but earlier lines in this file use spaces. …` | Re-indent pasted lines with one kind. |
| `this line is indented with a non-breaking space (U+00A0) …` | Retype the indentation with the space bar or Tab. |
| `this if has no lines under it. …` / `label "bridge" has no lines under it. …` | Indent its lines (comment lines don't count), or write `return`. |
| `this line is indented more than the line above, but the line above doesn't start a block. …` | Line it up with the line above. |
| `this line's indentation doesn't line up with any block above it. Indent it by 0, 4, or 8 spaces.` | Use one of the listed widths. |

### Quotes and text
| Message | Fix |
|---|---|
| `this line uses curly quotes “ ” around the text. …` | Retype the outer quotes as `"`. |
| `this quote is never closed. …` | Add the closing `"`, or indent the next line more if the text continues. |
| `… the text ends with a curly quote ”. …` | Retype the last quote as `"`. |
| `text goes between double quotes, not single quotes. …` | Use `"…"`. |
| `this line has more after the closing quote: … Write a quote inside the text as \".` | Write inner quotes as `\"`. |
| `"\q" is not a special sequence. …` | Use `\\`, `\"`, `\n`, or `{{`. |

### Statements
| Message | Fix |
|---|---|
| `"jmup" is not a statement. Did you mean "jump"?` | Fix the spelling. |
| `"Jump" is not a statement. Statement words are lower case: jump.` | Use lower case. |
| `"The" is not a statement, and this line has no text in quotes. …` / `hana's line has no text in quotes. …` | Put the text in quotes. |
| `"show" is not available yet in this engine version. …` / `"at" can't start a line. …` | Comment the line out for now. |
| `label start needs : at the end of the line. …` / `if needs : …` | Add `:`. |
| `this line is outside any label, so the story can never reach it. …` | Put it under a label. |
| `this elif has no if directly above it at the same indentation. …` | Line `elif`/`else` up under their `if`. |
| `else doesn't take a condition. …` / `write elif instead of else if.` | Use `elif condition:`. |
| `this line of text ends with :, which only menu choices do. …` | Remove the `:`. |
| `python: blocks aren't supported. …` | Use one `$` line per line of Python. |

### Labels, characters, names
| Message | Fix |
|---|---|
| `there is no label named "chapter_2". Did you mean "chapter2"?` | Fix the `jump`/`call` or the label. |
| `… It is defined in script/chapter3.vns, which is not included. Add include "chapter3.vns".` | Add the include. |
| `there is already a label named "rooftop" in … Rename one of them.` | Label names are unique across files. |
| `The story has no label named "start". …` | Add `label start:` to `main.vns`. |
| `no character named "hnaa". Did you mean "hana"?` | Fix the spelling, or `define` the character. |
| `"scene" is a statement word, so it can't be a character name. …` / `"class" is a word Python uses, …` / `"_intro" starts with _, …` / `"chapter-2" can't be a name. …` | Rename it, e.g. as suggested. |
| `the name "…" contains an invisible character (U+3164), …` | Retype the name; it hides a character you can't see. |
| `the name "…" mixes Latin and Cyrillic letters, …` (warning) | Retype it in one alphabet; a lookalike letter slipped in. |
| `"hana" is already defined in script/main.vns, line 5. …` | Define each name once. |
| `define sets a name once, … so it must be at the top level. …` | Move it out of the label, or use `$`. |
| `define trust uses itself, …` / `define a uses b, and b uses a …` | Give the value without the loop. |

### Variables, characters, and modules
Found when the game starts, before the story begins.

| Message | Fix |
|---|---|
| `default sets a variable's starting value before the story begins, so it must be at the top level. …` | Move it out of the label; use `$` to change it later. |
| `"trust" already has a default in … Remove one of them.` / `"trust" is set by define in …, and by default here. …` | One declaration per name: `default` if the story changes it. |
| `"hana" is set by define in …, so the story can't change it. …` | Use `default` for values that change, or `name_from` for a name. |
| `"dice" is a name the engine uses. Pick another name, …` | Rename your variable. |
| `a $ line can't import a module, … Add define math = module("math") …` | Define the module at the top level. |
| `dice.shuffle gives back a shuffled copy and leaves deck unchanged. …` (warning) | Write `$ deck = dice.shuffle(deck)`. |
| `"daichi" speaks in the story (…), but its define gives text, not a character. …` | `define daichi = Character("Daichi")`. |
| `Character has no option "colour". Did you mean "color"? …` / `"#e8a0b" isn't a color. …` | Fix the option; colors are `"#RRGGBB"`. |
| `Character needs the name to show, in quotes, …` / `… either a name or name_from, not both. …` | Give one name in quotes, or `name_from`. |
| `name_from="hana_nmae" doesn't name a default. …` / `name_from takes the variable's name in quotes: …` | Name a `default`, in quotes. |
| `blip is a file in quotes inside the audio folder, e.g. blip="blips/hana.ogg", but this has 3.` / `can't use "..\blips\hana.ogg" for blip: … Paths start in the audio folder and use /, …` / `"blips/hana.m4a" isn't a format the engine plays, so it can't be a blip. Use .ogg, .opus, .flac, .mp3, or .wav.` / `blip paths start inside the audio folder, so write "blips/hana.ogg", not "audio/blips/hana.ogg".` | Write the file as in `play`: inside `audio/`, with `/`, in a format the engine plays. |
| `blip_every must be a whole number from 1 to 10, e.g. blip_every=2, but this has 0.` / `blip_pitch must be a number from 0.0 to 0.5, e.g. blip_pitch=0.1, but this has 2.` / `blip_volume must be a whole number from 0 to 100, e.g. blip_volume=60, but this has 150.` / `blip_every needs blip="…" in the same Character(...).` | Use a value in the range, or add `blip`. |
| `define opening couldn't be set: it uses dice, …` / `define bonus couldn't be set: it uses "trust", which is a story variable …` | Make it a `default`. |
| `define maths couldn't be set: there is no Python module named "maths". …` | Fix the module's name. |

### Backgrounds and sprites
Warnings let the game start; the rest stop the launch.

| Message | Fix |
|---|---|
| `there is no image "hana hapy", so a placeholder will show. Did you mean "hana happy"?` (warning) | Fix the spelling, or add the file. |
| `… Names match files exactly: rename images/hana/Happy.png to happy.png, …` (warning) | Match the capitals. |
| `Some image files have names a script can't use: …` (warning) | Rename the files as suggested. |
| `hana's line has the word "pout", but there are no images for hana, …` (warning) | Add the images, or give the Character an `image_tag`. |
| `there is no position named "rigth". Did you mean "right"?` | Fix it, or add the name to `[stage.positions]`. |
| `1400 is too far right. Positions go from -1280 to 2560; …` / `at takes a position name or one or two numbers, … Numbers have no units.` | Write `at 400` with a number in range. |
| `"at" can't go on a dialogue line; only expression words can. …` | Put a `show` line above it. |
| `hide takes only the tag: write hide hana, not hide hana happy.` | Write only the tag. |
| `"hana/happy.png" is a file, not an image name. …` | Write `show hana happy`. |
| `flip takes on or off: …` / `zoom takes a number from 0.25 to 4, …` / `layer takes a whole number from -100 to 100, …` | Use one of the allowed values. |

### Transitions and effects
Every message for `with`, `shake`, `flash`, `pause`, and transition `define`s is in
[When something is wrong](#when-something-is-wrong-1), at the end of Transitions and
effects. Every message for `effect` and `with glitch` is in
[When something is wrong](#when-something-is-wrong-5), at the end of Glitch effects, except
`effect window_title` and `effect crash`, whose messages are in
[When something is wrong](#when-something-is-wrong-6), at the end of Fourth-wall tricks.

### Rollback
Every message for `rollback` lines is in
[When something is wrong](#when-something-is-wrong-3), at the end of Rollback.

### Full-screen text
Each message in full is in [nvl (full-screen text)](#nvl-full-screen-text).

| Message | Fix |
|---|---|
| `nvl needs on, off, or clear after it, e.g. nvl on.` / `nvl takes on, off, or clear, but this has "of". Did you mean "off"?` / `write nvl on in lower case.` | Write `nvl on`, `nvl off`, or `nvl clear`. |
| `nvl on takes nothing else on its line, …` / `full-screen text appears instantly, so nvl on can't take "with dissolve". …` / `nvl doesn't start a block, so it takes no ":". …` | Put anything else on its own line, and transitions on the `scene` line before it. |
| `this full-screen line needs 2 pages at text size 28, …` / `33 lines have gone by in full-screen text since the last nvl clear, …` (warnings, dev runs) | Split the line; add `nvl clear` where a new page should begin. |
| `config.toml: [theme.nvl] text_color #A0A0A0 on fill_color #FFF4F8 … gives 1.7:1 …` / `rin's color #C060A0 gives 2.5:1 on the full-screen text panel …` (warnings, dev runs) | Pick colors further apart. |

### Audio
Warnings let the game start; the rest stop the launch.

| Message | Fix |
|---|---|
| `play needs a channel before the file, e.g. play music "bgm/festival.ogg" or play sound "sfx/door.ogg".` / `stop needs a channel: stop music, stop sound, or stop voice.` / `"musc" isn't a channel. Did you mean "music"? …` | Write `play music` or `play sound`; `stop music`, `stop sound`, or `stop voice`; `queue music`. |
| `voice lines aren't started with play. Put voice "voice/hana_014.ogg" on the line above the line it voices.` / `only music can be queued. …` | Use `play music`, `play sound`, `queue music`, or `voice` above a line. |
| `play music needs a file in quotes, e.g. play music "bgm/festival.ogg".` / `the file goes in quotes: …` | Put the file in quotes. Names and variables can't stand for a file. |
| `can't use "..\bgm\theme.ogg": … Paths start in the audio folder and use /, …` | Use `/` and stay inside `audio/`. |
| `paths start inside the audio folder, so write "bgm/festival.ogg", not "audio/bgm/festival.ogg".` | Drop `audio/`. |
| `"bgm/festival" needs the file's extension, e.g. "bgm/festival.ogg".` | Add the extension. |
| `play has no option "fadin". Did you mean "fadein"?` / `play doesn't start a block. Remove the :.` / `play doesn't take with; transitions are for pictures. …` | Fix or remove the word; each statement's options are listed above. |
| `this line has fadein twice. Keep one.` / `loop and once can't be used together. Keep one.` | Keep one. |
| `fadeout can't go on play sound, because a new effect never stops the others. To fade effects out, use stop sound fadeout 1.0.` / `restart only works with play music; …` / `stop music stops whatever music is playing, so it doesn't take a file. …` / `voice takes only the file. …` / `crossfade is not available in this engine version. Use fadeout and fadein.` | Remove the option, or use the statement that takes it. |
| `fadein needs a number of seconds after it, e.g. fadein 2.0.` / `volume needs a percentage after it, e.g. volume 50.` / `from needs a time in seconds or current, e.g. from 12.5.` | Add the value. |
| `fadein takes seconds from 0 to 60, e.g. fadein 2.0, but this has 90.` / `… but this has "2s". Numbers have no units.` | Plain seconds: 0 to 60 for fades, up to 3600 for `from`. |
| `volume takes a whole number from 0 to 100 (a percentage), e.g. volume 50 for half, but this has 0.5.` / `write volume 50, without %.` | A whole percentage, e.g. `volume 50`. |
| `this voice has no line of dialogue or narration below it, so it never plays. Put voice directly above the line it voices.` / `voice goes directly above a line, not above an if. …` (warning) | Put `voice` directly above its line, or inside each branch. |
| `"bgm/theme.m4a" is an M4A file, which the engine can't play, so it will be silent. Convert it to .ogg (Ogg Vorbis) in an audio editor.` (warning) | Convert it to `.ogg`. |
| `3 music files loop but are MP3: bgm/festival.mp3, bgm/omen.mp3, and 1 more. MP3 adds a short silence each time a track loops; …` (warning) | Convert looping music to `.ogg`. |
| `there is no file audio/bgm/festval.ogg, so it will be silent. Did you mean "bgm/festival.ogg"?` (warning) | Fix the spelling or capitals, or add the file. |
| `Some voice files don't exist, so those lines have no voice: …` (warning) | Add the recordings; the lines work without them meanwhile. |
| `config.toml: [audio.loop_start] names "bgm/festval.ogg", which doesn't exist. Did you mean "bgm/festival.ogg"?` (warning) | Fix the file name in the key. |
| `config.toml: [audio.loop_start] gives "bgm/festival.mp3" a loop point, but loop points work only in .ogg and .opus files, so it loops from the start. Convert it to .ogg.` (warning) | Convert the file to `.ogg`, or remove the key. |
| `config.toml, line 2: [audio] music_volume must be a whole number from 0 to 100, but found 0.7` / `… [audio] music_fadeout must be seconds from 0 to 60, …` | Fix the value in `config.toml`. |

These appear only in the log, while the game runs, once per file; the game goes on:

| Message | Fix |
|---|---|
| `audio/bgm/festival.ogg is missing, so it plays as silence.` / `… couldn't be read, so it plays as silence. …` / `… can't be played: it is damaged or isn't really an Ogg Vorbis file. Export it again as .ogg.` | Add the file, close the program locking it, or export it again. |
| `audio/bgm/festival.ogg is damaged 1:23 in, so it stopped there. Export it again as .ogg.` | Export it again. |
| `audio/blips/hana.ogg is 1.4 seconds long, so it plays without blip_pitch. Blips with blip_pitch must be at most 0.5 seconds; trim the file to one short sound.` | Trim the blip to one short sound. |
| `[audio.loop_start] "bgm/festival.ogg" = 95 is past the end of the track (1:12), so it loops from the start. Use a time before 1:12.` | Use a loop point before the end. |
| `audio/bgm/festival.ogg can't use its loop point because the file's header has no room for the loop tags, so it loops from the start. …` | Export it again as `.ogg`. |
| `A restored game plays audio/bgm/old_theme.ogg, which is missing, so the music is silent.` | A save names a file that was renamed or removed: put it back under its old name. |
| `No sound device could be opened, so the game runs without sound.` / `The sound device stopped working, so the game continues without sound.` | Nothing to fix in the game: check the speakers or headphones. Sound comes back when a device is plugged in. |

### Text tags
All the tag messages are in [When a tag is wrong](#when-a-tag-is-wrong). Warnings let the
game start; the rest stop the launch.

| Message | Fix |
|---|---|
| `there is no tag "colour". Did you mean "color"?` / `there is no tag "bold". For bold, write {b}…{/b}.` | Use a tag from the table in section 14. |
| `this { never closes. …` | End the tag with `}`, or write `{{` to show a `{`. |
| `tags have no spaces inside: …` / `write {pause=0.6}, with = …` | Write `{name=value}` and nothing else. |
| `"#e0505" isn't a color. …` | `#` and six digits or letters a–f. |
| `{pause=…} takes seconds from 0.1 to 30, but this has 45.` / `{speed=…} takes a number from 0.1 to 10, or instant, …` | Stay in range; numbers have no units. |
| `{/b} closes bold, but no {b} is open here. …` | Remove it, or add the `{b}`. |
| `{/b} closes bold, but {i} was opened inside it and is still open. …` | Close the inner tag first. |
| `{next} goes at the very end of the text, …` | Move it to the end. |
| `{wave} can't go inside {shake}: a character has one effect at a time. …` | Close one effect before opening another. |
| `this {glitch} has 64 characters glitching at medium or large, …` (warning, dev runs) | Glitch fewer words, or use `{glitch=small}`. |
| `text_color must be a color: …` / `character names are shown exactly as written, …` | Fix the `Character` option; names take no tags. |
| `{var=player_nmae} shows a variable that no default or define sets, …` (warning) | Fix the name, or add a `default`. |
| `this line needs 2 text boxes at text size 28, …` (warning, dev runs) | Split the line if you want to choose the break. |
| `hana's name color #f4d0dc is hard to read on the name plate …` (warning W41, dev runs and the check) | Pick a color with more contrast. |
| `config.toml: [theme.textbox] text_font "fonts/Lora-Regular.tff" doesn't exist, so the built-in font is used. …` (warning) | Fix the path. |

### Python
| Message | Fix |
|---|---|
| `this Python has a mistake: "(" was never closed.` | Add the missing `)`; the column points at the `(`. |
| `this condition has a mistake: … Maybe you meant "==" …?` | Compare with `==`. |
| `… it uses a curly quote “. Python needs straight quotes " or '.` | Retype the quotes. |
| `"jump" is a statement, not Python. Remove the $.` | Remove the `$`. |
| `this Python is too long or too deeply nested to check. …` / `… longer than 100,000 characters …` | Split it into several `$` lines. |
| `Python warns: "is" with a literal. Did you mean "=="?` (warning) | Follow Python's hint; the game still starts. |

### Includes
| Message | Fix |
|---|---|
| `can't include "chapter2.vns" because script/chapter2.vns doesn't exist. …` | Match the name exactly; don't start with `script/`. |
| `can't include "../secret.vns": paths must stay inside the script folder …` | Keep files inside `script/` and use `/`. |
| `… only .vns files can be included.` / `… that is a folder. …` | Include each `.vns` file by name. |
| `include can't be inside a label or block, …` / `the file name goes in quotes. …` | Top level, with quotes. |

### Unused and unreached (tidy-up warnings)
These six warnings list scenes no player can reach and things the story never uses. They
never stop the game and never show in Studio's Problems list: Studio lists them in
**Database ▸ Clean up** (see [database.md](database.md#clean-up)), and the `lint` command
below prints them. A game in progress has some; tidy them up before you build.

| Code | Message | Fix |
|---|---|---|
| W237 | `nothing leads to label "old_ending" from start (no jump, call or choice), so players never see it. Add a jump to it, or delete it if you don't need it.` | Add a jump, call or choice to the scene, or delete it. A scene replay's scene counts as reached. |
| W238 | `character "kenji" never speaks and no line names it.` | Give the character a line, or delete its `define`. Studio lists characters after your first Play or Check now. |
| W239 | `picture "hana sad_blink1" isn't shown anywhere in the story.` | Show it, or delete the file. Pictures in `gui/`, `fonts/`, `minigames/`, `files/` and `masks/` are never listed. |
| W240 | `sound "music/old_theme.ogg" isn't played anywhere in the story.` | Play it, or delete the file. The music room counts as a use. |
| W241 | `variable "lantern_count" has a default, but no line reads or changes it.` | Use it in an `if` or a `$` line, or delete the `default`. |
| W242 | `define "max_tries" is defined but never used.` (also `transition`, `position` and `meter`) | Use it, or delete its line. Built-in positions and transitions are never listed. |

#### The lint command
`lint` checks a game the way Studio's Check now does (settings, script, launch) and prints
every problem and every tidy-up warning, for your code editor or an automatic build:

```
python -m engine lint [GAME_DIR] [--json] [--strict]
```

Each line is `file:line:column: severity code: message`; parts it doesn't have are left
out, and paths are inside the game folder, with `/`. The last line counts them:

```
script/main.vns:50: warning W237: nothing leads to label "old_ending" from start (no jump, call or choice), so players never see it. Add a jump to it, or delete it if you don't need it.
images/bg/old_park.png: warning W239: picture "bg old_park" isn't shown anywhere in the story.
0 errors, 2 warnings, 0 notes.
```

- `--json` prints one JSON document instead: `items` (each with `file`, `line`, `column`,
  `severity`, `code`, `text` and `source`, which is `"lint"` for the six warnings above),
  `errors`, `warnings`, `notes`, and `more` (items past the first 1,000).
- `--strict` treats warnings as failures.
- Exit code: 0 with no errors (warnings are fine), 1 with errors (or warnings with
  `--strict`), 2 when the folder isn't a game.
- `lint` writes nothing in the game folder. It runs from the engine's source only; a built
  game says `lint is only available in dev runs`.

To see the results in VS Code's Problems panel, open the game folder in VS Code and save
this as `.vscode/tasks.json`, with `cwd` set to the folder that holds the engine. Then run
**Terminal ▸ Run Task… ▸ Lint the game**:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Lint the game",
      "type": "shell",
      "command": "python -m engine lint \"${workspaceFolder}\"",
      "options": {"cwd": "C:/path/to/vn-engine"},
      "problemMatcher": {
        "owner": "vn-engine",
        "fileLocation": ["relative", "${workspaceFolder}"],
        "pattern": {
          "regexp": "^([^:]+):(\\d+)(?::(\\d+))?: (error|warning|info) ?(\\w*): (.*)$",
          "file": 1, "line": 2, "column": 3, "severity": 4, "code": 5, "message": 6
        }
      }
    }
  ]
}
```

Lines without a line number (a whole file, such as an unused picture) don't match the
pattern; they show in the task's terminal.

---

## 22. Run-time errors

Some mistakes only show while the story runs, such as a misspelled variable in a scene
nobody has reached yet. The story stops on an error screen with the file, the line, and
what to do; players see the same screen and can send you the line. Their saves are safe:
nothing is saved after an error. Messages are shortened below. The code in the first
column isn't shown on the screen; it is the message's name in the engine's documents, so
you can look one up or mention it when you ask for help.

| Code | Message | Fix |
|---|---|---|
| E85b | `there is no variable named "trsut". Did you mean "trust"?` | Fix the spelling. |
| E85b | `there is no variable named "met_daichi" yet. It is set by a $ line … Add default met_daichi = False …` | Add the `default`. |
| E85d | `this adds text and a whole number, which Python can't do. …` | Convert with `int(…)` or `str(…)`. |
| E85g | `this divides by zero. …` | Check the number first with `if`. |
| E85e | `"visited" holds a set, which can't be saved …` / `… holds a function …` / `… holds a module …` | Use a list; put helpers and modules in a `define`. |
| E75h | `hana's name comes from hana_name, which holds a whole number (3), not text. …` | Set the variable to text. |
| E85j | `dice.roll(6, 1) needs the smaller number first. …` / `dice.pick got an empty list, …` | Fix the `dice` call. |
| E85c | `dice has no "rol". Did you mean "roll"? …` / `text has no "uper". Did you mean "upper"?` | Fix the spelling of the call. |
| E45 | `the story ran 100,000 steps without showing a line, so it is probably stuck in a loop …` | A `jump` loop never reaches a line; give it a line or a way out. |
| E45b | `1,000 calls are waiting to return, … Did you mean jump? …` | Use `jump` to move on for good. |
| E85m | `this Python ran for 5 seconds without finishing, so it is probably stuck in a loop. …` | Check any `while` loop in the line and in the helpers it uses. |
| E85i | `this Python ran helpers inside each other too deeply, so a helper may call itself without end. …` | Give the helper a way to stop calling itself. |
| E85f | `this $ line tried to close the game with exit(). …` | End the story with `return`. |
| E85n | `input() can't be used in a game, because there is no console to type into. …` | Remove it; ask the player with a [menu](#menu-choices). |
| E178 | `every choice in this menu is hidden, because all their conditions are false, so the player can't pick anything. …` / `every choice in this menu is locked, …` | Add a choice without `if`, such as `"That's all":`. |
| E170 | `{var=trsut} shows a variable that doesn't exist. Did you mean "trust"?` | Fix the spelling, or add a `default`. |
| E171 | `{var=visited} can show text or a number, but visited holds a list. …` | Show a variable that holds text or a number. |
| E180 | `persistent.met_hana has no value yet. Give it a starting value with default persistent.met_hana = False at the top level of a file.` / `… Did you mean "hana_remembers"?` | Fix the spelling, or add the `default`. |
| E181 | `persistent.visited can't hold a set, because persistent data is saved as plain values. …` / `persistent.bag[…][0] can't hold a set, …` | Store lists, dictionaries with text keys, text, numbers, `True`/`False`, or `None`. |
| E182 | `persistent names starting with _ belong to the engine, so persistent._secret can't be set. …` / `persistent has no "_clera". Did you mean "_clear"?` | Use a plain name; `_clear()` is the engine's one. |
| E183 | `persistent data is now 1.3 MB, over the 1 MB limit, so it can't be saved. …` / `persistent data now has 10,001 names, over the 10,000 limit. …` | Store flags and counts, not long text or big lists. |
| E184 | `default persistent.a.b sets one name after "persistent.", …` (when the game loads) | One name per `default persistent.` line. |
| E185 | `define title couldn't be set: it reads persistent.cleared, but define values are set once at launch …` (at launch) | Use a `lambda` or a `default`. |
| E256 | `Python can't change codex. Use unlock tip, unlock item, and lock item.` / `there is no codex.itmes. Did you mean "items"? codex has tips and items.` / `define hint couldn't be set: it reads codex, …` (at launch) | Read `codex.tips` and `codex.items`; change them with `unlock` and `lock` (see [lock tip, lock item, unlock](#lock-tip-lock-item-unlock-codex)). |
| W56 | `persistent.hana_rememebrs is read here but never set or given a default. …` (warning, dev runs) | Fix the spelling or add a `default`. |
| E272 | `the argument words holds a set, which can't be saved. Use a list instead.` / `lantern_memory can't use pairs=40: …` (the plugin's `check_args` refused it) | Give values a variable can hold, that the minigame accepts. |
| E275 | `minigame stargazing stopped with an error in minigames/stargazing.py, line 88: division by zero. Fix the plugin; the log has the details.` | Fix the plugin at that line. |
| E276 | `stargazing finished with a set, which can't be saved, so it can't go into found. …` | Make the plugin finish with text, a number, a list, or a dictionary. |
| E277 | `minigame stargazing ran for 5 seconds … without finishing, so it is probably stuck in a loop. …` | Check any `while` loop at that line. |
| E279 | `minigame stargazing has no outcome for this headless run. Give one in the inputs, e.g. finish 3, or give the plugin a test outcome.` (headless runs) | Add `finish …` to the inputs, or a `test_outcome` to the plugin. |
| E453 | `there is no variable called invite to send. …` / `line 2 of message invite asks for a reply, but more lines follow it. …` | Keep the message a `define` of text or a list of lines (see [Messages](#messages)). |
| E454 | `inbox.reply needs a message's name in quotes, but it got a number. …` / `inbox can be read, not changed: …` | Write `inbox.reply("invite")`, and only read it. |
| E85 | `this Python stopped with an error: … the log has the details.` | Check the values the line uses. |

When the mistake is inside a helper written in a `define`, the message names the line that
used it and adds `(in define bonus, script/main.vns, line 7)`.

---

## 23. Meta files

A story can put small files beside the game, where the player can find them: a character's
file that vanishes when she leaves, or a note that only a curious player reads. The story
can then check what the player did with them ([a short walkthrough](meta-files.md)). Four
lines do it:

```
default hana_here = False
default answer = None

label start:
    file write "hana.chr"
    file write "read_me.txt" "If you're reading this, don't tell Hana.\nShe can hear you."
    hana "I left something in your game folder."
    file delete "hana.chr"
    file exists "hana.chr" into hana_here
    if hana_here:
        hana "You put me back!"
    file read "answer.txt" into answer
    if answer:
        hana "You wrote back. You said: {var=answer}"
```

| Line | What it does |
|---|---|
| `file write "hana.chr"` | Copies `files/hana.chr` from the game folder into `characters/`. |
| `file write "read_me.txt" "text"` | Writes the text into `characters/read_me.txt`. `\n` starts a new line; `{` is just a `{` (text tags aren't read). |
| `file delete "hana.chr"` | Deletes `characters/hana.chr`. Nothing happens if it isn't there. |
| `file exists "hana.chr" into hana_here` | Sets the story variable to `True` if the file is in `characters/`, else `False`. |
| `file read "answer.txt" into answer` | Sets the story variable to the text the player left in the file (its first 2,000 characters), or `None` if there is no such file or it isn't text. `.txt` files only. |

The example game's bonus scene (`script/bonus.vns`) uses all of them but `file read`.

**The folder.** Every file goes in the `characters/` folder inside the game folder, and
nowhere else. The game makes the folder when it writes the first file. While you test, it
is your project's `characters/` folder; Studio's Play uses it too.

**The names.** A name is written in quotes, never taken from a variable: lowercase letters,
digits, `-` or `_`, up to 32 of them, then `.chr` or `.txt`, such as `"hana.chr"` or
`"read_me.txt"`. Names Windows keeps for itself (`con`, `nul`, `com1`, …) aren't allowed. A
game can use at most 32 names.

**Originals.** A `file write` with no text copies the file of the same name from the
`files/` folder of your game (`files/hana.chr`), at most 4 MB. The game checks it is there
when it loads. The original never changes, so a player can always copy it back. Add an
original in Studio's project panel under **Meta files**; any `.chr` or `.txt` file with a
good name can go there.

**Each change happens once.** A `file write` or `file delete` runs once and is never
undone. The player can't roll back past it: it blocks rollback by itself, as a
`rollback block` line does. Skipping runs it like any line. `file exists` and `file read`
look at the folder each time they run, also when the player goes forward again after
rolling back.

**A new game puts the files back.** The game never writes, deletes, or tidies files by
itself: not on launch, a new game, or Delete progress. So write each file near the start of
the story, as the example game does. Every new game then writes it again, and a player who
deleted Hana gets her back by starting over.

**When the folder can't be written.** A game installed in a read-only folder (such as
`C:\Program Files`) can't write there. The game goes on: `file write` and `file delete` do
nothing, `file exists` gives `False`, and the log has one warning (W197). If your story
depends on a file, check with `file exists` right after the write or delete, as the example
does, and give both answers a line. A file another program has open (an editor, a virus
scanner) can't be changed either: the log has W198 "another program may be using it", and
the story goes on.

**Hot reload.** If you add the first `file` line of your game while it runs from Studio
and the game updates (see [Update the running game](hot-reload.md)), the files reach the
disk only after you start the game again. Until then the story uses a folder in memory, and
the log says so.

**Tell your players.** These files are the player's computer, so:

- A file the player keeps at a name your story uses is replaced or deleted: a player's own
  `characters/hana.chr` is gone after `file delete "hana.chr"`.
- List file deletion in your game's content warning (`[content_warning]` in `config.toml`),
  for example "This game writes and deletes small files in its characters folder."
- A note must never tell players to run programs, change system settings, or move files
  outside the game folder.
- `file` lines can only reach `characters/`, but `$` lines and `define` code are ordinary
  Python and can reach any file. Keep file work in `file` lines.
- When you share your game, `files/` goes with it and your own `characters/` folder never
  does (Studio's build leaves it out), so players start with an empty folder.

### When something is wrong

The game checks `file` lines when it loads and lists every mistake with its file and line.
W196–W200 are warnings in the log while the game runs; the story goes on.

| Code | Message | Fix |
|---|---|---|
| E309 | `file needs what to do and a file name, e.g. file delete "hana.chr". It takes write, delete, exists, or read.` / `"delte" isn't a file word. Did you mean "delete"? file takes write, delete, exists, or read.` / `file delete takes one file name, but this line has "now" left over.` / `file doesn't take a block. Remove the ":" and un-indent the lines under it.` | Write `file`, one of the four words, and a name in quotes. |
| E310 | `a meta file name is in quotes: lowercase letters, digits, - or _, up to 32 of them, then .chr or .txt, such as "hana.chr". "../hana.chr" has a /.` / `a meta file name is in quotes: lowercase letters, digits, - or _, up to 32 of them, then .chr or .txt, such as "hana.chr". "Hana.chr" has capital letters.` / `the file name must be written in quotes, such as "hana.chr", not a variable like name.` | Use a lowercase name in quotes ending in `.chr` or `.txt`. |
| E311 | `the text for "read_me.txt" can be at most 16,000 characters, but this one has 18,200.` | Shorten the text, or copy an original from `files/`. |
| E312 | `file exists needs into and a story variable, e.g. file exists "hana.chr" into hana_here.` / `there is no default named "hana_her". Did you mean "hana_here"?` / `"hana" is set by define, so the story can't change it. Use a variable that has a default.` / `into takes one story variable's name, such as into hana_here, but this has "persistent.hana". To keep it across playthroughs, write $ persistent.hana = hana_here on the next line.` | Name one story variable with a `default`. |
| E313 | `file write "hana.chr" copies files/hana.chr, but there is no such file. Add it to the files folder, or give the text: file write "hana.chr" "your text".` / `files/hana.chr is 5.2 MB, but an original can be at most 4 MB.` | Add the original to `files/`, or make it smaller. |
| E314 | `This game uses 33 meta file names, but at most 32 are allowed. The first one over is "extra.txt" (script/act3.vns, line 40).` | Use fewer names. |
| E315 | `file read reads text, so it works only on .txt files, not "hana.chr". To see whether hana.chr is there, use file exists.` | Use `file exists` for `.chr` files. |
| W196 | `<game>/characters isn't a real folder (it is a link or a file), so file lines do nothing this session and file exists gives False.` | Delete the link or file named `characters` in the game folder. |
| W197 | `<game>/characters can't be written (the game may be installed in a read-only folder), so file write and file delete do nothing this session.` | Install the game in a folder the player can write to, or let the story go on without the files. |
| W198 | `couldn't delete <game>/characters/hana.chr: no permission.` / `couldn't write <game>/characters/read_me.txt: the disk is full.` / `couldn't write <game>/characters/read_me.txt: another program may be using it.` | Close the program using the file; at most 20 of these are logged a session. |
| W199 | `the story made 256 file changes this session, the most allowed, so later file write and file delete lines do nothing until the game restarts.` | A `jump` loop probably writes over and over; write once. |
| W200 | `file read "answer.txt" found no text: the file is over 16 KB.` / `file read "answer.txt" found no text: it isn't UTF-8 text.` | The player's file is too big or not text; the variable is `None`. |

---

## 24. Glitch effects

Glitch effects make the stage picture look broken, for a moment or for as long as you like:
bands of it slide sideways, its colors split apart, static covers it, or one sprite twitches.
They act on the stage only; the text box, choices, and menus never glitch. To glitch a
line's text instead, write [`{glitch}…{/glitch}`](#text-effects) inside it. The example game's
bonus scene, `game/script/bonus.vns`, uses each one with a comment above its first use.

```
label start:
    scene bg river
    show hana happy
    effect tear
    "The picture tears for half a second."
    effect tear large 0.3
    effect jitter hana 1.0
    hana "Did you see that?"
    effect static small on
    effect colorshift on
    effect jitter hana large on
    hana "It's getting worse."
    effect static off
    effect jitter hana off
    "The static stops, but the colors stay split."
    effect off
    "Everything is back to normal."
```

**An `effect` line** is `effect`, then the glitch: `tear`, `colorshift`, `static`, or
`jitter` and a sprite's tag (`effect jitter hana`; only `jitter` takes one). After it, in
any order and each at most once:
- a size: `small`, `medium` (the default), or `large`;
- a length in seconds from 0.1 to 30, with no unit, or `on`, or `off`.

`effect` goes inside a label, like other story lines.

**Bursts and lasting glitches.**
- With a length, or with none, a glitch is a **burst**: `effect tear 0.3` tears the
  picture for 0.3 seconds, then stops by itself. With no length it lasts as long as
  `[effects] glitch` says (0.5 seconds).
- With `on` it **lasts** until you stop it: `effect static on`, later `effect static off`.
  `effect jitter hana off` stops only Hana's jitter. `off` takes no size or length.
- `effect off` on its own stops every glitch, lasting ones and bursts.
- Different glitches run together. For one glitch (one sprite, for `jitter`), the newest
  line wins. A burst over a lasting glitch of the same kind shows its own size for its
  length; then the lasting one comes back.

**When it starts.** Like `shake`, an `effect` line starts with whatever is shown next: a
line, a choice, a `with`, or a `pause`. It never holds up the text, and a burst still
running at the next line plays to its end. Glitches act on the stage after a `shake` and
under a `flash`, keep going behind choices and chapter cards, and stand still while a menu
is open.

| Glitch | What it does | small / medium / large | Changes |
|---|---|---|---|
| `tear` | 2 to 6 bands of the picture slide sideways and wrap around, so no gap shows | slides up to 16 / 40 / 96 units | new bands every 0.1 seconds |
| `colorshift` | A red copy of the picture moves left and a blue copy right; green stays | 2 / 6 / 12 units | still |
| `static` | Gray noise over the stage, with the same average brightness on every frame | 15% / 30% / 50% strength | new noise every 0.1 seconds |
| `jitter <tag>` | The sprite's picture jumps to small offsets around its place | up to 4 / 10 / 24 units | a new offset every 0.08 seconds |

Sizes are in canvas units (the 1280×720 picture), so a glitch looks the same at every
window size. Glitches start and stop at once: they are glitches.

**Jitter and sprites.** A jitter follows its sprite when the sprite changes expression or
position. It ends when the sprite leaves (`hide`, or a `scene`), and showing the sprite
again doesn't bring it back. A tag with no sprite on the stage does nothing; a `--dev` run
logs W184.

**`with glitch`.**
```
    scene bg room with glitch
    show hana sad with glitch 0.8
```
A built-in transition, used like `dissolve`: an optional length from 0 to 30 seconds (0.5
when left out) and no color. The old picture tears harder and harder up to the middle, cuts
to the new one, and the tear calms to nothing. A click finishes it at once, like any
transition. `glitch` is a built-in name, so `define glitch = …` is an error (E198).

**Words.** `effect` is a reserved word. `tear`, `colorshift`, `static`, `jitter`, `on`, and
`off` mean something only right after `effect`, so `default static = 0` still works.

**Flashing.** Glitches never fill the stage with a color and never flash red on their own.
Their patterns change at most 10 times a second (12 for a jitter), and they change the
stage's average brightness only when they start or stop. They share the limit of
[3 flashes a second](#flash) with `flash` and short fades. Counted: a burst shorter than 1
second (never a `jitter`), a `with glitch` shorter than 1 second, and starting, resizing, or
stopping a lasting `static` or `colorshift`. Glitches that start on the same line count
once. An extra burst isn't shown and an extra `with glitch` plays as a dissolve; the story
goes on the same, and the log says so (W182). A lasting glitch over the limit starts a
moment later.

**Reduced effects.** With **Reduce motion and flashing** on in Settings, or `[effects]
reduce = true` for everyone, `tear` and `jitter` draw nothing; `static` is one still frame
at the `small` strength, fading in and out over 0.3 seconds; `colorshift` stays as
written but fades in and out over 0.3 seconds; and `with glitch` plays as a dissolve.
Turning the setting on or off mid-glitch changes the look at once. The story is the same
either way.

**Give each glitch a line or a sound that carries its meaning.** Some players turn effects
down, and some can't see them well, so don't let a glitch tell the story on its own. In the
example game, Hana asks "Did I just disappear from your folder?" while she glitches.

**Don't stack `static` with a `Mask` transition.** Static over a running `Mask` is the
heaviest thing the stage draws, and it can stutter at 1920×1080 on slower computers. Turn
the static off before the `with`, or use `dissolve` there.

**Saves and rollback.** Lasting glitches are part of the story: a save stores them, and
loading or rolling back shows them at once. Bursts are never saved or replayed, and
skipping drops them; lasting glitches stay. A new game or a return to the title clears
every glitch. Glitches never change lines, choices, or variables, and their randomness
never touches the story's `dice`.

**Settings in `config.toml`.** The length and size used when a line gives none:
```toml
[effects]
glitch = 0.5              # a burst's length in seconds, 0.1 to 30
glitch_size = "medium"    # small, medium, or large
```

### When something is wrong
E294 stops the launch with the file and line. W182–W184 are warnings in the log while the
game runs; the story goes on.

| Code | Message | Fix |
|---|---|---|
| E294 | `there is no glitch effect "tare". Did you mean "tear"?` / `there is no glitch effect "wobble". The effects are tear, colorshift, static, and jitter.` / `there is no glitch effect "corrupt". To corrupt a line's text, write {glitch}…{/glitch} inside it.` / `effect needs a glitch: tear, colorshift, static, or jitter, or off to stop them all.` / `effect jitter needs the sprite to jitter, e.g. effect jitter hana.` / `effect static doesn't take a sprite; only jitter does, but this has "hana".` / `effect tear takes a length from 0.1 to 30 seconds, but this has 45.` / `lengths have no units: write 0.5, not 0.5s.` / `write 0.5, not .5.` / `effect tear has two sizes; give one.` / `effect static has both on and a length. on lasts until effect static off, so give one.` / `effect static has both on and off; give one.` / `effect tear off takes no size or length.` / `this line has "slowly" left over after effect tear. effect takes a glitch, then a size and a length, on, or off.` / `this line has "now" left over after effect off. effect off takes nothing after it.` | Write `effect`, a glitch, then a size and a length, `on`, or `off`. For a line's text, use `{glitch}…{/glitch}`. |
| W182 | `the glitch from this line wasn't shown, because the game shows at most 3 flashes a second to protect players who are sensitive to flashing.` / `the glitch transition from this line played as a dissolve, because the game shows at most 3 flashes a second to protect players who are sensitive to flashing.` (warning, while playing) | Space the glitches out, or make bursts 1 second or longer. |
| W183 | `the glitch effect "static" couldn't be drawn (MemoryError), so it is off for the rest of this run.` (warning, while playing) | Nothing to fix in the script: the story goes on. If it keeps happening, close other programs; report it with the log. |
| W184 | `effect jitter daichi: no sprite tagged daichi is on the stage, so nothing jitters. On the stage: hana, monika.` / `effect jitter daichi: no sprite tagged daichi is on the stage, so nothing jitters. On the stage: no sprites.` (warning, `--dev` runs) | Show the sprite before its `effect jitter`, or fix the tag. |

## 25. Fourth-wall tricks

For a moment the game seems to reach outside its window: the title bar changes, a
character says the player's computer user name, or the game seems to crash. Three tricks
do it. The example game's bonus scene, `game/script/bonus.vns`, uses each one with a
comment above its first use.

```
label start:
    scene bg river
    effect window_title "She is still here"
    hana "I know who you are, {username}."
    menu:
        hana "Will you stay a little longer, {username}?"
        "Stay":
            hana happy "Thank you."
        "Go home":
            hana "Then go."
    effect crash "Traceback (most recent call last):\n  File \"hana.chr\", line 7\nHanaError: Hana is not responding"
    hana "...That wasn't me. Was it?"
    effect window_title off
    "Morning came."
```

**`effect window_title "…"`** changes the text in the game window's title bar (and the
taskbar or dock). `effect window_title off` brings back the game's own title, `[game]
title`.
- The title is one text in quotes, at most 100 characters, shown as written: it is plain
  text, so it can't hold tags or `{username}`. Write `{{` for a `{`. `""` empties the
  title bar.
- **The title is part of the story.** A save keeps it, and loading the save or rolling
  back shows it again. New Game, a return to the title, the story's end, and an ending card
  bring back the game's own title, and so does quitting: the next launch starts with
  `[game] title`.
- Only a title your script writes ever reaches the window: a save edited to hold another
  title shows the game's own title instead.

**`effect crash`** shows a fake error screen, as if the game had broken: the engine's
error look, with the heading "The game ran into a problem", your message, the game's title
and version, and the hint "Press Esc or Enter to continue".
- `effect crash` alone shows `[words] fake_crash_message` ("Something went wrong.").
  `effect crash "…"` shows your message: at most 2,000 characters, `\n` for a new line,
  and only `{username}`, `{var=…}`, and `{{` inside. A message too long for the screen
  ends with "…".
- **Nothing moves**: the screen appears with one cut and leaves with one cut (with Reduce
  motion and flashing on, a 300 ms fade). The stage stands still behind it.
- **It can't be clicked away by accident.** For its first half second (0.5 s) every press
  is ignored; then Enter, Space, Esc, a click in the game, or the gamepad's A or B
  continues the story. The game's own keys (save, load, history, skip, auto, the game menu)
  do nothing while it shows.
- **Closing the window quits at once**, with no question. Before the screen shows, the
  game writes everything it remembers, and the quit's auto-save keeps the player's place
  (with no picture; `[saves] autosave_quit`), so nothing is lost.
- **It is a moment, not a place.** Skipping passes it without showing it; Auto waits for
  the player. Rolling back past it and going forward again doesn't show it again, a save
  is never made while it shows, and loading a save never shows it.
- **The hint must tell players how to continue.** `[words] fake_crash_hint` changes it,
  but keep it an honest instruction ("Press any key to go on"), at most 120 characters on
  one line. Players who don't want to be fooled can turn on **Label fake error screens**
  in Settings (the row shows only when your story has an `effect crash`): the screen then
  adds "This is part of the story." (`[words] fake_crash_label`).
- **Don't imitate the computer's own stop screens**: no blue or black "your PC" screens,
  sad faces, QR codes, or percentages, and never a phone number or web address to call or
  visit. The fixed heading, the game's title line, and the hint keep the screen
  recognizably the game's; don't work against them.

**`{username}`** shows the player's computer user name, the name they log in with, in
dialogue, narration, a menu's question, and `effect crash` messages.
- **The game asks each player first.** Turn it on with `[meta] username = true` in
  `config.toml`. At the first launch, after your [content warning](#content-warning) and
  before the title, the game asks: "This game can show your computer's user name in the
  story. It is never saved or sent anywhere. Allow it?" "Don't allow" is focused. "Allow"
  ignores every press for its first half second (0.5 s), so a click meant for the content
  warning can't answer it. Closing the window counts as "Don't allow". The order is
  always: content warning, then the name question, then the title.
- **Only "Allow" shows the name.** Otherwise `{username}` shows `[meta] username_fallback`
  ("friend"), and so it does when the game doesn't offer the name, when you start from a
  label (`--start`, or Studio's "play from here"), and when the name can't be read (the log
  says so once, W188).
- **Players can change their mind.** **Use my computer's user name**, in the Data group
  of Settings, shows only when the game offers the name; turning it off shows "friend" from
  the next frame. **Reset settings** turns it off, and the question comes back at the next
  launch.
- **The name is shown as written**, never as tags: `{b}` in a name shows `{b}`. The
  `DOMAIN\` part is left out (`CORP\aiko` shows `aiko`), and a name is cut to 32 letters.
  A long name can need a second text box; the game continues the line in a new box, as
  for any long line.
- **`{username=player_name}`** shows the name when it is allowed, and otherwise the value of
  the story variable `player_name`, the same as `{var=player_name}`.
- **Not in** a choice (E175), a window title (E300), a chapter or ending title (E302), a
  character's name (E302), or a codex entry (E252): those are kept or shown where the name
  must never go.

**The name is never saved.** Your story only ever sees the fallback word: History, saves
and the line the Load page shows, `persistent` data, and the log all hold "friend", never
the name. Save pictures leave out the text box (and NVL page, and choices)
whenever the name shows on screen, so a picture shows the stage only. The name is read
once, after the player allows it, and kept in memory for that session. It still shows in
the player's own screenshots and streams, which the question's "in the story" covers.

**Tell players first.** List both tricks in your [content warning](#content-warning), e.g.
"It contains a fake error screen, and can show your computer's user name if you allow it."

**Never read the name or the computer's details in `$` code.** Python can read them
(`getpass.getuser()`, `os.getlogin()`, `os.environ["USERNAME"]`), but anything your code
stores goes into saves, history, and persistent data, which players share. Never store it
in a variable, persistent data, a window title, a plugin's result, or the log. Use
`{username}` in text instead: the name then never leaves the screen. A `--dev` run warns
about such code (W190).

**Words.** `window_title` and `crash` mean something only right after `effect`, so
`default crash = 1` still works. `username` isn't reserved either.

**Settings in `config.toml`.**
```toml
[meta]
username = true                # offer {username}; each player is asked first
username_fallback = "friend"   # shown instead: one line, at most 32 characters
```

| Key under `[words]` | Default |
|---|---|
| `fake_crash_message` | "Something went wrong." (`effect crash` with no message) |
| `fake_crash_hint` | "Press Esc or Enter to continue" (one line, up to 120 characters) |
| `fake_crash_label` | "This is part of the story." (one line, up to 120 characters) |
| `settings_username`, `settings_crash_label` | "Use my computer's user name", "Label fake error screens" (the Settings rows) |
| `ask_username`, `ask_username_yes`, `ask_username_no` | "This game can show your computer's user name in the story. It is never saved or sent anywhere. Allow it?", "Allow", "Don't allow" (the first-launch question) |

### When something is wrong
E300 to E302 stop the launch with the file and line. W188 is a warning in the log while the
game runs; W189 and W190 are warnings in `--dev` runs. The story goes on after a warning.

| Code | Message | Fix |
|---|---|---|
| E300 | `effect window_title needs the title in quotes, e.g. effect window_title "Hello?", or off to bring back the game's own title.` / `the window title can be at most 100 characters, but this one has 140.` / `the window title is plain text, so it can't hold {username} or other tags. To show a {, write {{.` / `effect window_title takes a title or off, but this line has "slowly" left over.` | Write `effect window_title "…"` with plain text, or `effect window_title off`. |
| E301 | `effect crash takes one message in quotes, but this line has "again" left over.` / `the fake crash message can be at most 2,000 characters, but this one has 2,400.` / `a fake crash message can hold only {username} and {var=…}, but this one has {b}.` | Write `effect crash` alone or with one message in quotes, using only `{username}`, `{var=…}`, and `{{`. |
| E302 | `{username} shows the player's computer user name, so it can be used only in dialogue, narration, and effect crash messages, not in a character name.` / `{username} shows the player's computer user name, so it can be used only in dialogue, narration, and effect crash messages, not in a title card.` | Move `{username}` into a line of dialogue or narration. A choice (E175) and a codex entry (E252) give the same message. |
| W188 | `the computer's user name couldn't be read, so {username} shows "friend" this session.` (warning, while playing) | Nothing to fix: the computer didn't give a name. The fallback word shows. |
| W189 | `this line uses {username}, but [meta] username is off in config.toml, so every player sees "friend". Set username = true under [meta] to let players choose.` / `…and 4 more lines use {username}.` (warning, `--dev` runs) | Set `username = true` under `[meta]`, or leave it off if "friend" is what you want. |
| W190 | `this Python code reads the computer's user name or environment. Anything it stores goes into saves, history, and persistent data that players share. To show the player's name, use {username} in text instead.` / `…and 2 more lines read identity.` (warning, `--dev` runs) | Remove the code and write `{username}` in the line instead. |

## 26. Dynamic UI

The game's look can change while it runs. A **playthrough look** restyles the title once
players have played before: a new picture, music, and button words for a second
playthrough. A **style** is a second look for the text box, choices, NVL page, and quick
menu that the story switches on and off with `ui style`. The story can also turn off
saving or loading for a while, and delete every save. The example game's bonus scene,
`game/script/bonus.vns`, uses a style, and its endings (`game/script/endings.vns`) set
the playthrough, each with a comment above its first use.

```
label start:
    scene bg room
    # Turn the text box to the [style.ashes] look in config.toml.
    ui style ashes
    hana "The room feels colder now."
    ui saving off "There's nothing left to keep."
    hana "Don't bother saving. It won't help."
    ui saving on
    ui style off
    hana "...Sorry. I don't know what came over me."
    $ persistent.playthrough = 2
    return
```

### Playthrough looks
`persistent.playthrough` is a value the game remembers across playthroughs, like any
[persistent](#persistent-data-across-playthroughs) value. It starts at 0 without a
`default` line, and the engine never changes it: the story sets it, for example
`$ persistent.playthrough = 2` just above an ending, or
`$ persistent.playthrough = len(persistent.endings)`. Your own
`default persistent.playthrough = …` replaces the 0. Delete progress in Settings and
`persistent._clear()` put it back to its starting value.

A `[playthrough.N]` table in `config.toml` (N a whole number from 0 to 99, at most 16
tables) is the title's look from playthrough N on: the table with the largest N that is
not above `persistent.playthrough` is used, and below every N the title keeps its usual
look. A table may hold:

- `[playthrough.N.theme.title]`: any `[theme.title]` key, such as the picture
  (`background_image`, an image in `gui/`), `logo_image`, `music`, and the colors;
- `[playthrough.N.words]`: any `[words]` key, such as `new_game`. These words also show
  in the game menu and the quick menu while that look is chosen;
- `title_entries`: the title's buttons, as `[title] entries`.

**The look is chosen only at the title, at New Game, and at a load.** Setting
`persistent.playthrough` in the middle of the story changes nothing on screen until the
title opens again (after an ending, or Main Menu), a New Game starts, or a save loads.
F33's content warning, shown before the title, uses the chosen look's words and colors.

**The title's Load page is never blocked.** No story runs at the title, so
`ui loading off` can't reach it. To keep players from loading at the title in a later
playthrough, leave `load` out of that look's `title_entries`.

To see a playthrough look while you test, run the game as that playthrough:
`python -m engine run game --playthrough 2`. The run reads the game's persistent data
but keeps it in memory, so nothing is written. In Studio, **Run ▸ Preview title as
playthrough…** does the same.

### Styles
A `[style.<name>]` table (at most 32) is a look the story turns on with
`ui style <name>`. The name is lowercase letters, digits, and `_`, up to 32, starting
with a letter, and not `off` or a reserved word. A style may hold `theme` keys of the
`textbox`, `choice`, `nvl`, and `quick_menu` areas (with their sub-tables, such as
`[style.ashes.theme.choice.focused]`) and `[style.<name>.words]`. Values follow the same
rules as `[theme]`. A key the style doesn't set keeps the usual look. A style may also
name a built-in color scheme, `preset = "amber"` under `[style.<name>.theme]`, which
recolors every box, menu and button except the title screen while the style is on, with
the style's own keys still winning over it (ui-system.md §3, "Color schemes").

```toml
[playthrough.2]
title_entries = ["new_game", "settings", "quit"]

[playthrough.2.theme.title]
music = "bgm/title_quiet.ogg"

[playthrough.2.words]
new_game = "Again?"

[style.ashes.theme.textbox]
fill_color = "#1E1A1C"
text_color = "#EDE3E8"
border_color = "#5A3848"

[style.ashes.words]
save = "Keep"
```

- **`ui style <name>`** makes that style the current one; **`ui style off`** goes back to
  the usual look. One style is on at a time: a second `ui style` replaces the first.
- The text box's colors and frame change at once, on the box already shown; its text
  takes the new font, size, and colors with the next line. The quick menu takes the whole
  style at once. Choices and the NVL page use the style the next time they appear.
- **Player settings win.** The player's text size scales the style's size (a style's
  `text_size = 40` at 150 % is capped at 48), and reduce motion turns fades into cuts
  whatever look set them.
- A style is part of the story: saves keep it, rollback brings back the one that was on,
  and New Game and the title clear it. A save whose style `config.toml` no longer has
  loads with the usual look (W205).
- **Use [Glitch effects](#24-glitch-effects) for flicker, not rapid `ui style` lines.** A
  style switch is cheap, but it isn't meant to flash, and glitches keep to the game's
  flashing limit.

**Layer order.** Each key and word is looked up in the current style first, then in the
chosen playthrough look, then in `[theme]` and `[words]`, then in the engine's default.
A key whose default follows another key (`nvl.fill_color` follows `textbox.fill_color`)
follows the value found. Fonts and pictures in looks and styles are checked at launch like
`[theme]`'s; one that can't be used gives W207 and the `[theme]` key instead. In `--dev`
runs, the text and fill colors of each style and each playthrough look get the contrast
check of [Menus and theme](#15-menus-and-theme) (W67, naming the table).

### Saving and loading off
- **`ui saving off ["reason"]`** turns off saving: the Save page shows the reason instead
  of its slots, quick save says it, and auto-saves stop (the quit auto-save too).
  **`ui saving on`** allows saving again. Without a reason the game's word `saving_off`
  shows, "Saving is turned off here."
- **`ui loading off ["reason"]`** and **`ui loading on`** do the same for loading during
  the story, with the word `loading_off`, "Loading is turned off here."
- A reason is plain text in quotes, 1 to 200 characters, with no text tags (`{{` writes a
  `{`).
- Like a style, the blocks and their reasons are saved, rolled back, and cleared by New
  Game and the title.

### Deleting every save
**`ui delete saves`** deletes every save slot of this game, auto-saves and quick saves
included, and the story goes on at once. It never touches persistent data, settings, or
the player's other files. Rollback can't bring the saves back, and running the line again
deletes again. A headless run and a Studio preview delete nothing; the log says
`ui delete saves: no saves are deleted in a preview.`

**Write `ui saving off` before `ui delete saves`**, because auto-saves can make new saves
right after the delete, and turn saving back on only when the scene is over:

```
label the_end_of_everything:
    ui saving off "There's nothing left to keep."
    ui delete saves
    hana "It's all gone now. Just us."
    ui saving on
    return
```

### When something is wrong
E319 to E321 stop the launch with the file and line. W204 and W205 are warnings in the log
while the game runs; W206 and W207 are warnings at launch (W206 in `--dev` runs). The
story goes on after a warning.

| Code | Message | Fix |
|---|---|---|
| E319 | `ui needs what to change, e.g. ui style ashes, ui saving off, ui loading on, or ui delete saves.` / `ui can change style, saving, loading, or delete saves, but not "colour". Did you mean "color"?` / `ui style needs a style name from config.toml, or off, e.g. ui style ashes.` / `ui saving needs off or on, e.g. ui saving off "Not here." or ui saving on.` / `ui delete needs the word saves: ui delete saves.` / `ui saving on takes nothing more, but this line has "now" left over.` / `ui goes inside a label, because it runs when the story reaches it.` | Write `ui style <name>`, `ui saving off`/`on`, `ui loading off`/`on`, or `ui delete saves`, inside a label. |
| E320 | `there is no UI style "ashs" in config.toml. Did you mean "ashes"? Add a [style.ashs] table, or use ui style off.` / `there is no UI style "glowy" in config.toml. Add a [style.glowy] table, or use ui style off.` | Fix the name, or add the `[style.<name>]` table to `config.toml`. |
| E321 | `the reason needs at least one character, or leave it out to use the game's own words.` / `the reason can be at most 200 characters, but this one has 240.` / `the reason is plain text, so it can't hold {b} or other tags. To show a {, write {{.` | Shorten the reason, or leave it out. |
| W204 | `persistent.playthrough isn't a whole number (it holds text), so the title uses playthrough 0's look.` / `persistent.playthrough isn't a whole number (it holds True or False), so the title uses playthrough 0's look.` (warning, while playing; the value itself is never shown) | Set `persistent.playthrough` to a whole number, such as 2. |
| W205 | `this save uses the UI style "ashes", which config.toml no longer has, so the normal look is used.` (warning, while playing) | Add the `[style.<name>]` table back if old saves should keep their look. |
| W206 | `config.toml: [style.ashes] isn't used by any ui style line.` (warning, `--dev` runs) | Use the style with `ui style <name>`, or remove its table. |
| W207 | `config.toml: [style.ashes.theme.textbox] frame_image "gui/x.png" doesn't exist, so [theme.textbox] frame_image is used.` / `config.toml: [playthrough.2.theme.title] background_image "gui/night.png" couldn't be read as an image, so [theme.title] background_image is used.` (warning, at launch) | Fix the file name, or put the picture or font in the game folder. |

---

## Changelog
- 2026-11-01: Created with the F02 proposal.
- 2026-11-01: Shortened to one short section and example per statement (rules stay in
  02-script.md). Added the errors for `main.vns` being a folder, unreadable, or outside
  the game folder; a 256 MB total; a `define` that uses itself; Python too complex; and
  Python warnings. Noted that continued lines count for the tab/space rule. Messages
  updated to the revised 02-script.md wording.
- 2026-11-01: The Python warning now names conditions and `define` values, which run at
  every launch before the title screen (security Q-S2). Added errors for text-direction
  characters, invisible or mixed-alphabet names, and the story-size limits.
- 2026-11-01: F03 proposal: `default`, Characters (`color`, `name_from`), Story variables,
  Random numbers (`dice`), Python modules (`module`), the F03 launch errors, and Run-time
  errors. Sections 8–11 and 15 are new; Reserved words, Coming later, and Common errors are
  renumbered 12–14.
- 2026-11-01: F04 proposal: new section 12, Backgrounds and sprites (`scene`, `show`,
  `hide`, expressions on dialogue lines, `image`, `[stage]` in `config.toml`), the
  `image_tag` Character option, and its common errors. The seven F04 words are available.
  Sections 12–15 are renumbered 13–16.
- 2026-11-01: F08 proposal: new section 13, Audio: music and sound (`play`, `queue`, `stop`,
  `voice`, formats, `[audio]` and `[audio.loop_start]` in `config.toml`, saving and
  loading), a pointer in section 7, and Audio common errors. `play stop queue voice` are
  available. Sections 13–16 are renumbered 14–17.
- 2026-11-01: F08: `stop sound "<file>"` stops one effect (PR-F08-34); its common error
  now covers a file on `stop music`.
- 2026-11-01: F05 proposal: new section 14, Dialogue text (text tags `{b}` `{i}` `{color}`
  `{size}` `{speed}` `{pause}` `{var}` `{next}` and `{{`, the `text_color` and `text_italic`
  Character options, `[textbox]` in `config.toml`), pointers in sections 3 and 7, Text tags
  common errors, and two run-time errors. Sections 14–17 are renumbered 15–18.
- 2026-11-01: F05: text box look settings are `[theme.textbox]` tokens (`fill_color`,
  `fill_opacity` 0.0–1.0, `text_font`, `bold_font`, …); only `cps` stays in `[textbox]`.
- 2026-11-02: F04 built (step 8): section 12 is no longer proposed. It shows the
  `images/` names as a code block, `at` with names, numbers, and `[stage.positions]`,
  `behind`, `layer`, `zoom`, `flip`, and `as` in code, `with` before transitions, and the
  missing-picture and position messages in full. Examples follow the example game
  (`bg river_dusk`, `by_the_rail`, Daichi's name color `#3a6aa8`).
- 2026-11-02: F08 step 1: section 13's statements (`play`, `queue`, `stop`, `voice`) and
  their load messages are built and no longer proposed; the section says the sound itself
  comes with the audio player, and so do the missing-file warnings. A voice with no line below
  it is warned about when the game starts.
- 2026-11-02: F03 built (step 14): `default` and sections 8–11 and 18 are no longer
  proposed. Random numbers says plainly that `random` and `time` results don't replay and
  repeats the real-Python warning. Run-time errors gives each message's code and adds the
  5-second, helper-depth, `exit()`, and `input()` messages. Character examples use the
  example game's name colors (`#b03070`, `#3a6aa8`).
- 2026-11-02: F05 built (step 7): section 14 and the F05 parts of sections 3, 7, 8, 17, and
  18 are no longer proposed. Section 14 adds every `[theme.textbox]` key with its default,
  readable colors (the dev warnings), the long-line warning in full, and a new "When a tag
  is wrong" with every tag message. Examples use colors that read well on the default box
  (`#9a1c14`, `#1e4a9c`), as the example game does.
- 2026-11-02: F12 built (step 6): `persistent` (data across playthroughs) moves from
  Coming later into section 9 and is no longer proposed, with its limits, `_clear`,
  `--no-persistent`, and the warning that players can edit and share the file. Run-time
  errors drop E85h and list E180–E185 and W56; a dictionary key from the player's file
  shows as `[…]` in E181. Examples use `persistent.flowers`, since `persistent.endings`
  and `persistent.routes` will belong to the engine (F19).
- 2026-11-02: F10 built (step 9): new section 15, Menus and theme: the title picture, logo,
  and music, button frames, `[words]`, `[title]`, `[quick_menu]`, the quick-menu strip,
  every theme setting with its default, and the menu warnings. The example game's
  `config.toml` and `gui/` show each one. Sections 15–18 are renumbered 16–19.
- 2026-11-02: F07 built (step 5): `menu` (choices) is a statement of section 7 and is no
  longer proposed (out of Coming later): questions, conditions, locked choices
  (`[choice] show_locked`), choice text tags, a menu inside a choice, the "Talk" loop,
  saving at a menu, the `[theme.choice]` settings, and every menu message in full (the
  long-choice and missing-sound warnings too). `menu` is available; Run-time errors list
  E178.
- 2026-11-02: F08 built (step 12): section 13 is now "Music and sound" (the contents and the
  pointer in section 7 follow) and its audio is heard. It adds why MP3 loops have gaps, the
  loudness target with how to set it, the example game's audio and its license record,
  `stop music fadeout 0`, a voiced menu question, replay from the History log, skipping,
  the launch's missing-file check, and playing without a sound device. Common errors
  "Audio" gives a message for every load, startup, and launch mistake and adds the
  messages logged while the game runs.
- 2026-11-02: F06 step 1 (proposed, F06): the four blip options in section 8 with a short
  "Blips" note, and their messages in Common errors (the option errors under "Variables,
  characters, and modules", the long-blip warning under "Audio"). Blips are heard from F06
  step 3.
- 2026-11-02: F06 built (step 3): blips are heard and no longer proposed. The "Blips" note in
  section 8 adds how the count runs, the 0.04-second gap and instant text, the pitch steps,
  the lines that never blip, and the example game's blips (section 13 names them too).
- 2026-11-02: F18 built (step 3): `chapter` in section 7 (title cards, the chapter
  auto-save, save names, `[chapter]` and `[theme.chapter]`, its messages), available in
  Reserved words; the example game has a prologue and two chapters.
- 2026-11-02: F09 built (step 5): new section 16, Transitions and effects: `with` (`cut`,
  `dissolve`, `fade`, lengths, fade colors, one transition per moment, waiting, clicking
  through), `shake`, `flash` with the 3-a-second limit and reduced effects, `pause`, your
  own transitions (`Dissolve`, `Fade`, `Mask`, with the 640×360 gray mask advice),
  `[effects]` and `[theme.effects]`, the advice not to let a flash or shake carry the story
  alone, and every message (E190–E199, W60–W62). Section 12's "the picture changes
  instantly for now" note and its warning are gone; section 7 points to the new section;
  `with`, `shake`, `flash`, and `pause` are available. Sections 16–19 are renumbered 17–20.
- 2026-11-02: F11 built (step 12): new section 17, Saves: what players see (the Save and
  Load pages, quick saves, auto-saves), what a save holds, where saves live in dev runs and
  releases, `[game] id` and testing with `--release`, that builds leave out `saves/`, how
  to keep saves working across updates (`default`, keeping labels, the nearest-point
  question), that saves are input (shared saves, `default` on restored values, no file
  names from story variables, nothing from the player's computer), `[saves]`, the 32 save
  words, `[theme.save]` and `[theme.notice]`, and W80–W83. Section 15 names Load, Save,
  Q.Save, and Q.Load. Sections 17–20 are renumbered 18–21.
- 2026-11-02: F22 built (step 3): `points (character stats)` in section 9 (declaring,
  changing, and reading meters, `points.highest`, saves and rollback, the F3 overlay
  lines, and E230–E236 and W120 with fixes); section 7 points to it, section 9 lists
  `points` among the names Python can see, and `points` is available in Reserved words.
  The example game declares meters for Hana and Daichi and branches on
  `points.highest`.
- 2026-11-02: F16 built (step 5): section 15 gains "The Settings page": where it opens,
  its rows, the `config.toml` keys that give the starting values (Settings adds none),
  that only changed values are stored, `[effects] reduce`, that settings aren't story
  state, Reset settings and Delete progress, where `settings.json` lives, the 26 page
  words under `[words]`, and W70–W75. The title, game menu, and quick menu name
  Settings; "Button words" points to the page's words. No script syntax changed.
- 2026-11-02: F14 built (step 6): new section 18, Rollback: what players see and where back
  stops, what is and isn't rolled back, that going forward runs the story again (a
  `$ persistent.count += 1` counted twice, fixed by `= value` or a block), `rollback block`,
  `off`, `on`, and `fixed` with a scare, a choice that can't be undone, a fixed choice, and
  a chase, `[rollback] steps` and `marker`, the `back` word and `[theme.rollback]`, and
  E200–E204 and W90. Section 7 points to it, section 9's persistent note names the block,
  Reserved words lists all 39 words with `rollback` available, and Common errors points to
  the new messages. Sections 18–21 are renumbered 19–22.
- 2026-11-02: F17 built (step 5): `nvl (full-screen text)` in section 7, no longer
  proposed: `nvl on`, `nvl off`, `nvl clear`, pages that fill up by themselves, lines
  longer than a page, menus (choices just under the question, the question-only page when
  they don't fit, a new page after a pick), where the lines may go, transitions and
  `scene`, `chapter` with `nvl clear`, saves and rollback, the 32-line page record, the
  `[theme.nvl]` keys with their defaults and ranges, the dev-run warnings and how lines are
  counted as full-screen (by file order in each label), and E210, E211, W100, W101, and
  W102. `nvl` is available in Reserved words; Common errors has a "Full-screen text" part.
  The E204 row of Rollback names minigame lines (F23).
- 2026-11-02: F19 built (step 6): `ending, lock route, unlock route` in section 7, no
  longer proposed: endings and their card, routes locked `until` endings, `unlock route`,
  `lock route`, and `lock ending` in a label, `persistent.endings` and `persistent.routes`
  as read-only lists, and E240–E246, W130, W131, and W132. `ending`, `lock`, and `unlock`
  are available in Reserved words. The example game has three endings and the promise
  route (`script/endings.vns`).
- 2026-11-02: F21 built (step 5): `lock tip, lock item, unlock (codex)` in section 7: tips
  (kept across playthroughs) and items (this playthrough) declared with a title, a category,
  a picture, and paragraphs; `unlock tip`, `unlock item`, `lock item`, and `lock tip` in a
  label; `codex.tips` and `codex.items` as read-only lists; rollback; the Codex page in the
  game menu and, when listed, on the title; `[codex]`, `[theme.codex]`, the seven words, and
  E250–E256 and W140–W142. Section 6 and Reserved words say `codex` is an engine name and
  `tip` and `item` aren't reserved; section 9 lists `codex`; section 15 names the Codex
  entry; Run-time errors list E256. The example game has two tips and two items.
- 2026-11-02: F20 built (step 9): `flowchart (the story map)` in section 7: what is a box
  with no extra lines, `flowchart scene`, titled and plain menu marks, `flowchart omit`,
  `hidden`, `no jump`, `flowchart forget` (all, or per label), what a jump brings back and
  keeps, jump points as files in the saves folder (Delete progress and `forget` delete them,
  deleting saves doesn't; menu conditions run again at a jump), the four `[flowchart]`
  settings, and E260–E265 and W150–W155. Reserved words list `flowchart` (40 words). The
  example game marks a scene, titles the bridge's last menu, and hides the promise route.
- 2026-11-02: F31 built (step 5): section 23, "Meta files": `file write`, `file delete`,
  `file exists`, and `file read`, the `characters/` folder and the name rules, originals in
  `files/`, each change once and blocking rollback, the new-game pattern, read-only installs
  and locked files, hot reload, what to tell players, and E309–E315 and W196–W200.
  Rollback's table has a meta files row; `file` is available in Reserved words.
- 2026-11-02: F28 step 6: "Glitch effects" (section 24): `effect` with `tear`,
  `colorshift`, `static`, and `jitter`, sizes, bursts and `on`/`off`, `effect off`, `with glitch`,
  the flash limit and reduced effects, saves, `[effects] glitch` and `glitch_size`, and E294,
  W182–W184. `effect` is available in Reserved words; `glitch` is in the `with` table.
- 2026-11-02: F29 step 5: "Text effects" in Dialogue text (section 14): `{shake}`, `{wave}`,
  `{glitch}` and their strengths, one effect at a time, History, the crawl-then-slam recipe,
  Reduce motion, nothing clipped, fonts without the symbols, and long glitches. The tag table
  lists the three; the E160 list and missing-tag rows match the engine again (the old
  "shake in this engine version" row is gone); new rows for the E160 effect hints, E164's
  effect forms, E297, W185, and E175's effect form.
- 2026-11-02: F30 step 6: new section 25, Fourth-wall tricks (`effect window_title`,
  `effect crash`, the `{username}` tag and its first-launch question, what is never saved,
  the content-warning advice, the rule for `$` code that reads identity, `[meta]` and the
  eight `[words]` keys, E300 to E302, W188 to W190), a section 7 pointer, the `{username}`
  row in the tag table, the Data group's two rows, and notes in Saves, Content warning,
  Reserved words, and Common errors.
- 2026-11-02: F32 step 6: new section 26, Dynamic UI (`persistent.playthrough` and
  `[playthrough.N]` title looks, `[style.<name>]` and `ui style`, the layer order, player
  settings winning, `ui saving`/`ui loading` off and on with a reason, `ui delete saves`
  after `ui saving off`, `run --playthrough N`, E319 to E321 and W204 to W207).
- 2026-11-03: F34 W5: section 7's "lock gallery, unlock gallery" (declarations and versions,
  unlock on show, `unlock gallery` and `lock gallery` in a label, the Extras button,
  `run --extras`, `[gallery] show_locked`, the `[theme.gallery]` tokens and words, E342 to
  E345 and W226), and a Reserved words note on `gallery` and `cg`.
- 2026-11-03: F36 W1: section 7's "lock replay (scene replays)" (the declaration with
  `image`, `to` and starting values, unlock on arrival, `unlock replay` and `lock replay` in
  a label, E348 to E352).
- 2026-11-03: F36 W5: "lock replay (scene replays)" gains the Endings page, `[endings] list`
  and `replay`, the rules during a replay (no saves, End Replay, progress put back with
  tracks and achievements kept, W229's skipped lines), `run --replay`, and the seven words.
- 2026-11-03: F37 S2: section 7 "lock achievement (achievements)" (declarations with a
  description, `image`, `hidden` and `when`, `unlock achievement` in a label, the notice,
  the Achievements page, achievements earned in a replay kept, the platform hook, the five
  words, E339, E340, W223, W224).
- 2026-11-03: "lock track (music room)" and "lock achievement (achievements)" name the
  example game's three tracks and four achievements.
- 2026-11-04: F49 W1: Dynamic UI, Styles: a style may name a color scheme (`preset`).
- 2026-11-04: F51: menu (choices) gains **Timed choices** (`menu time N:`, the `timeout`
  choice, Timing assist, saves and going back) and the E368, E369, E370 and W257 rows.
