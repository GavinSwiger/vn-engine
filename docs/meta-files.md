# Meta files: files beside the game

Some stories reach out of the window: a character's file sits in the game folder, and
when she leaves the story, her file is gone. vn-engine does this with `file` lines. The
rules are in [the script language, "Meta files"](script-language.md#23-meta-files); this
page is the short way through.

## 1. Add the original

Put the file the story copies in your game's `files/` folder, such as `files/hana.chr`.
In Studio, the project panel lists it under **Meta files**; **Add files…** puts a file
there. A name is lowercase letters, digits, `-` or `_` (up to 32), then `.chr` or `.txt`.
An original can be anything up to 4 MB: the example game's `hana.chr` is a picture of Hana
saved under another name.

## 2. Write it at the start of the story

```
default hana_here = False

label start:
    file write "hana.chr"
    file write "read_me.txt" "If you're reading this, don't tell Hana."
```

The game never puts files back by itself, so write each one near the start: every new
game then writes it again. Type `file ` in Studio and pick the word; inside the quotes,
Ctrl+Space lists your names.

## 3. Delete it, and see what the player did

```
    hana "I don't want to be here anymore."
    file delete "hana.chr"
    "..."
    file exists "hana.chr" into hana_here
    if hana_here:
        hana "You... put me back?"
    else:
        "The festival is quiet without her."
```

Leave a few lines between the delete and the check, so a player has time to copy the file
back. A write or delete blocks rollback by itself: the player can't step back past it.

## 4. Test it

Choose **Run ▸ Play** in Studio. The files appear in your project's `characters/` folder; open
it and watch them come and go. Studio's **Outline** tab lists each name with the lines
that use it.

- **Added your first `file` line while the game runs?** An update of the running game
  doesn't reach the disk: start the game again.
- **W198 "another program may be using it"** means another program has the file open
  (an editor, a virus scanner). Close it; the story went on without the change.
- **W197** means the folder can't be written, as in a read-only install. The story goes
  on and `file exists` gives `False`, so give that answer a line too.

## 5. Before you share the game

- Say in your content warning (`[content_warning]` in `config.toml`, or **Game settings**)
  that the game writes and deletes files in its characters folder.
- A note must never tell players to run programs, change system settings, or move files
  outside the game folder.
- A player's own file at one of your names is replaced or deleted.
- **Build game** ships `files/` and leaves your `characters/` folder out.

Back to [Studio](scene-editor.md).
