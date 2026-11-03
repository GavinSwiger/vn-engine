# Build your game

**File ▸ Build game…** in Studio (Ctrl+Shift+B) makes a folder of your game that players can
run on Windows. They don't need to install anything.

1. Check the **Name** and **Version**. Give the game a **Game ID** once (**Use …** makes one
   from the name) and don't change it after you release: players' saves are kept under it.
2. Pick an **Icon** (a PNG in your game folder), or keep the engine's.
3. **Save to** is a `builds` folder next to your game folder; **Browse…** picks another.
   Keep **Also make a .zip file to share** ticked to get a zip to upload.
4. Press **Build**. Studio saves your open files, writes the details into `config.toml`,
   checks the game, and shows each step. Packing takes about a minute.

When it's done, **Run the game** tries the build and **Open folder** shows it. Send players
the zip; they unzip it and open the `.exe`. Errors stop the build and are listed in
**Problems**; every other stop says what to do. **Cancel build** leaves *Save to* as it was.

The first time, Studio may say the build tool isn't installed: **Install build tool**
downloads it (PyInstaller, about 10 MB). Studio remembers *Save to* and the zip choice in
`.studio/build.json`.

From a terminal: `python -m engine build game --zip` (add `--replace` to replace an earlier
build).
