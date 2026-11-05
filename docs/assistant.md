# AI assistant

An AI can read your game, check it and suggest changes. You can use it two ways:

- **In an AI app**: Claude Code, Claude Desktop and other apps that support MCP can work on
  your game. They run on your plan with that app, so **a Claude Pro or Max plan is all you
  need**: no API key, no API credit. Open **Help ▸ Connect an AI app…** and click **Set up**.
- **In Studio**: the **AI Assistant** pane. Pick **Claude Code (your Claude plan)** to use
  your Claude Pro or Max plan through Claude Code on this computer, or use your own API key
  for Anthropic (Claude), OpenAI (ChatGPT), or a model server on your computer (Ollama,
  LM Studio and others). API use is paid by use and separately from a chat plan such as
  Claude Pro or ChatGPT Plus.

Either way, the AI never changes a file until you say so, and it never runs Python code it
wrote before you apply the change.

## Set up the pane with your Claude plan

1. Install Claude Code from claude.com/claude-code, open a terminal, run `claude` once and
   sign in with your Claude account.
2. In Studio, open **File ▸ Studio settings…** (Ctrl+,), pick the **AI** page and choose
   **Claude Code (your Claude plan)** as the **Provider**. Pick a **Model** (sonnet, opus or
   haiku).
3. Press **Test connection**. It should say "Connected."
4. Open the pane and ask about your game.

Each Send starts Claude Code in the background with only this game's tools, served by Studio
for that request alone. Claude Code reads and checks the game through them, and its changes
come back as cards you apply, the same as with an API key. Studio never sees your Claude
login. The chats also appear in Claude Code's own history for the game folder. Use this for
your own work: Anthropic's terms don't let a product you share offer Claude plan sign-in
without their approval.

## Set up the pane with an API key

1. Open **File ▸ Studio settings…** (Ctrl+,) and pick the **AI** page.
2. Pick a **Provider** and a **Model**.
3. Press **Get a key** to open the provider's API keys page, make a key, copy it and press
   **Paste**. Studio shows only its last 4 characters after that. **Remove** deletes the
   saved key. An Anthropic key starts with `sk-ant-api`; Studio says so if you paste an
   Admin key or the other provider's key.
4. Add credit to your API account on the provider's website if you haven't yet.
5. Press **Test connection**. It should say "Connected."
6. Open the pane with **AI Assistant** on the menu bar or **View ▸ AI Assistant**
   (Ctrl+Shift+A), and ask about your game.

If `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set and no key is saved, settings offer
**Use the key from …** for that provider only.

**Steps** limits how many times the assistant may look something up or check a change before
it stops (send "continue" to let it go on). **Chat token limit** stops a chat that has used
that many tokens; each answer shows the tokens it used. A new chat starts from zero.

## How a change reaches your game

The assistant reads your script files and `config.toml`, runs the check, and proposes
changes. Each change shows as a card with the files, the lines it adds and removes, and what
the check found. Nothing changes until you press **Apply**. Apply puts the change in the open
script files, unsaved, as one undo step per file; saving stays yours. If the file changed
since the assistant wrote the change, Apply refuses and offers **Ask again**.

A change that adds or changes Python code (a `$` line, `define`, `default`, a condition)
shows a warning. Its check runs without the game's code, which runs only after you apply.

The assistant can change your game's settings too. It names a setting and a value, never
`config.toml` text, and Studio writes it the way **Game settings** does: comments and layout
stay, and a value the setting doesn't take is refused. It can also look up every setting
there is, and read these guides.

New games come with `AGENTS.md` and `CLAUDE.md`: notes that tell an AI app (Claude Code
and others) how to work with the game. A build leaves them out.

## What is sent

The first time you use a provider, Studio asks before it sends anything. What it sends: the
open script file around the cursor, the lines you select, the current problems, and any
script file or `config.toml` the assistant asks to read. Pictures and sounds are never sent,
but their file names may be. Each answer lists what was sent ("Sent: …"). The provider
handles it under its own terms, and requests use your API key and your account.

**With a local server, nothing leaves your computer.** Pick **OpenAI-compatible** and an
address such as `http://localhost:11434/v1` (Ollama) or `http://localhost:1234/v1`
(LM Studio). Plain `http://` is allowed only for a server on this computer; anything else
needs `https://`.

## Where the key is kept

Studio keeps each key in your system's keychain: Windows Credential Manager, the macOS
Keychain, or the Secret Service keyring on Linux. Only on a computer with no keyring does it
use a file in your user folder that only you can read. A key goes only to the provider (or
the exact server address) it was saved for, and never into your game folder, `.studio/`,
logs or error messages.

**Programs you run can read the key's store.** That includes games you run, so be careful
with games and tools from people you don't know, and remove a key you no longer use.

Studio's settings and your consent answers are kept per user in `assistant.json` in
Studio's user folder (on Windows, `%APPDATA%\vn-engine\_studio`), never in a game folder.

**Preview, Check and Build don't pass `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` on** to the
game or tools they start. If your game or a plugin needs a variable like that, it won't get
it from Studio.

**Build game** warns when a file it ships looks like it holds an API key, naming the file
and line: "script/main.vns, line 4: this looks like an API key. Remove it before you share
the game." Remove the key and build again.

## Use an AI app (MCP)

Open **Help ▸ Connect an AI app…** and click **Set up** next to Claude Code or Claude Desktop.
Studio adds this game to that app for you; restart the app afterwards (in VS Code, run
**Developer: Reload Window**). Claude Code gets it in every folder you open it in. If Set up
can't finish, it says why, and you can copy the command or settings text shown instead. For
other MCP apps, copy the command, arguments and environment from **Other apps**.

The app can then list and read your script files, read the story map and the
language reference, run the check, and propose changes. With **Let the app change script
files** ticked, the app shows each change first and applies it only through `apply_edit`.
Studio can't undo changes an app makes, so save your work first; if a file is open in Studio,
Studio asks whether to reload it.

From a terminal: `python -P -m engine assist-mcp game` (add `--read-only` to refuse every
change, `--no-launch` to check without running the game's code).

## Be careful with games you didn't write

- **Game files can carry instructions to the AI.** A comment or line of dialogue in a
  template, a mod or a downloaded game can tell the AI to do something you didn't ask for.
  Read every change before you apply it.
- **In an MCP app, the app's own tools can act on those instructions.** Claude Code and
  others can run commands and fetch web pages. Don't auto-approve those tools, or
  `apply_edit`, while the AI works on a game you didn't write.
- **MCP checks run the game's code**, just as `python -m engine lint` and Studio's check do.
  For a game you didn't write, start the server with `--no-launch`.
- **The key's store is readable by programs you run** (see above).
- **A local server keeps everything on your computer.**
