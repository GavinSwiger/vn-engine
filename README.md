# vn-engine

A game engine for making visual novels in the style of Doki Doki Literature Club.

## Install

You need Python 3.12 or newer and pygame-ce 2.5 (2.5.2 or newer, below 2.6).

```
pip install "pygame-ce>=2.5.2,<2.6"
```

If the original `pygame` package is installed, remove it first: `pip uninstall pygame`.

## Run

From the project folder:

```
python main.py
```

This runs the game in the `game/` folder next to `main.py`. It works from any working
directory, e.g. `python C:/projects/vn-engine/main.py`. Options:

- `--release`: run as a release build (logs go to your per-user folder instead of
  `game/logs/`).
- `--bench SECONDS`: measure frame times for `SECONDS` (1 to 3600) after a 5 s warm-up,
  write the result to the log, and quit.
- `--log-level LEVEL`: lowest level written to the log (`debug`, `info`, `warning`,
  `error`).

## Run another game folder

```
python -m engine run <folder>
```

For example `python -m engine run D:/projects/my-vn`. Without a folder, it runs `game/`.
The same options as above are accepted.

In dev runs, `run` also accepts `--seed N` (0 to 18446744073709551615): every new game
uses that dice seed, so a run can be replayed. With `--release` it is refused.

## Folder layout

```
game/
  config.toml     # game settings (optional; every key has a default)
  script/         # .vns story files
  images/         # backgrounds, sprites, CGs
  audio/          # music, sound effects, voice
  fonts/          # .ttf / .otf
  gui/            # UI art, window icon
  logs/           # written by the engine in development runs
```

A missing subfolder is not an error. The folder name `characters/` is reserved.

## Before you release: set `[game] id`

Open `game/config.toml` and set a unique id for your game in the `[game]` section:

```toml
[game]
id = "my-visual-novel"
```

The id names your game's per-user folders (logs now; saves and settings later), so it
must be unique to your game: 1 to 40 characters, each a lower-case letter, a digit, or
`-`, starting with a letter or digit. The example game ships with the line commented
out, so a copied template never shares an id with another game.

## Licence

vn-engine and vn-engine Studio are copyright (c) 2026 Gavin Swiger, all rights reserved,
and are licensed, not sold:

- [LICENSE.txt](LICENSE.txt): the vn-engine Studio Licence, for using Studio and the
  engine to make games.
- [GAME-TERMS.txt](GAME-TERMS.txt): what you may do with games made with vn-engine. They
  are yours, and you may sell them anywhere, royalty-free, with the engine inside.
- [BETA-LICENCE.txt](BETA-LICENCE.txt): the licence for beta testers of pre-release versions.

The components made by others (Python, pygame-ce, SDL, the Noto fonts and so on) are under
their own licences; a built game carries them in its `licenses/` folder
(`engine/tools/build/notices/`). All three documents are drafts awaiting legal review.
