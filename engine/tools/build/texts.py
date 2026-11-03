"""Every text of F42's build, as tables (F42 ``01`` §6.3; ``07`` I-1; SEC-F42-15).

Why this module exists: the ``build`` command (CLI lines) and Studio's Build dialog show the
same words, so both read them from here. Templates use ``str.format`` fields named after the
§6.3 placeholders (``{name}``, ``{folder}``, ``{save_to}``, ``{n}`` …); the small functions
pick singular or plural forms and format sizes and counts.

- ``STEPS`` / ``steps`` / ``step_text``: the six (or five, without a zip) progress steps.
- ``FAILURES`` / ``failure`` / ``cli_failure_lines``: every ``B_*`` key → (message, fix).
  ``BuildStopped`` carries a key and its values from the code that found the problem to the
  step machine, which reports it (CLI or report event).
- ``LEFT_OUT_REASONS`` / ``left_out_reason``: why a game-folder entry wasn't copied.
- ``FIELD_MESSAGES``: the dialog's field messages (``names.field_problems`` fills them).
- ``readme_text`` / ``readme_bytes``: the players' ``README.txt`` (CRLF, UTF-8, no paths).

Shared module (``tools/editor`` may import it): standard library and ``core`` only.
"""

import unicodedata

from engine.core.graphemes import HIDDEN_CATEGORIES

# --- Dialog, progress, and finished texts (01 §6.3 "Dialog and steps") -----------------------

MENU = "Build game…"
INTRO = ("Make a folder of your game that players can run on Windows. "
         "They don't need to install anything.")
NAME_HINT = "Shown on the window. Game file: {exe}"
ID_HINT = ("Names the folder where players' saves are kept. "
           "Choose it once and don't change it after you release.")
ID_USE = "Use {slug}"
FOR_WINDOWS = "Windows 64-bit (this computer)"
MAKES = "Makes: {folder}"
ZIP = "Also make a .zip file to share"
NOTE = "Studio saves your open files and checks the game first."
HEAD = "Building {name} {version}"
CLI_HEAD = 'Building "{name}" {version} for Windows (64-bit)'
SLOW = "This is the slow part. It usually takes about a minute."
CLI_STEP = "Step {i} of {m}: {text}"
DONE = "Your game is built."
DONE_FOLDER = "{folder} — {size}, {files} files"
CLI_DONE_FOLDER = "Built: {path} ({size}, {files} files)"
DONE_ZIP = "{zip} — {size}"
CLI_DONE_ZIP = "Zip: {path} ({size})"
SHARE = "Send players the zip file. They unzip it and open {exe}."
SHARE_NO_ZIP = "Send players the whole {folder} folder. They open {exe} inside it."
TRUST = "Only do this if you got the game from a place you trust."            # SEC-F42-15
SMARTSCREEN = ('If Windows says "Windows protected your PC", click More info, then Run '
               "anyway. This happens with games that aren't signed. " + TRUST)
WARNINGS_ONE = "Built with 1 warning."
WARNINGS_MANY = "Built with {n} warnings."
WARNINGS_WHERE = " They're listed in Problems."
LEFT_OUT_ONE = "1 file was left out."
LEFT_OUT_MANY = "{n} files were left out."
LONG_PATHS = ("{n} file paths are very long and may not unzip on some PCs. "
              "Shorten folder or file names, like {ref}.")
CANCELLED = "Build stopped. Nothing in {save_to} was changed."
CANCEL_ASK = "Stop the build? Nothing will be saved."
REPLACE_ASK = 'Replace the earlier build "{folder}"? The old folder will be deleted.'
REPLACE_ASK_ZIP = 'Replace the earlier build "{folder}"? The old folder and its zip will be deleted.'
REPLACE = "Replace"
ID_CHANGED = ("You changed the Game ID from {old} to {new}. "
              "Players of your earlier build won't see their saves in this one.")
CLOSE_WHILE_BUILDING = "A build is running. Stop it and close Studio?"
STOP_AND_CLOSE = "Stop and close"
STOP_BUILD = "Stop build"
KEEP_BUILDING = "Keep building"
MAC_NOT_YET = ("Building for Mac isn't available yet. "
               "Build on a Windows PC to make a Windows version.")
GAME_FOLDER_MISSING = ("The game folder is missing. "
                       "Keep {exe}, _internal and game together in one folder.")

# --- Steps (PR-F42-16; M = 6, or 5 without the zip) ------------------------------------------

STEP_CHECK, STEP_COPY, STEP_PACK, STEP_NOTICES, STEP_ZIP, STEP_FINISH = (
    "check", "copy", "pack", "notices", "zip", "finish")
STEPS: dict[str, str] = {
    STEP_CHECK: "Checking your game",
    STEP_COPY: "Copying the game folder ({files} files, {size})",
    STEP_PACK: "Packing the engine and Python",
    STEP_NOTICES: "Adding licenses and the read-me file",
    STEP_ZIP: "Making the zip file",
    STEP_FINISH: "Finishing up",
}
# The copy step before its counts are known (the waiting row in the dialog).
STEP_COPY_WAITING = "Copying the game folder"


def steps(with_zip: bool) -> tuple[str, ...]:
    """The step keys in order; the zip step only ``with_zip``."""
    return tuple(key for key in STEPS if with_zip or key != STEP_ZIP)


def step_text(key: str, *, files: int | None = None, size: int | None = None) -> str:
    """One step's row text; the copy step shows its counts once they are known."""
    if key == STEP_COPY and (files is None or size is None):
        return STEP_COPY_WAITING
    return STEPS[key].format(files=format_count(files or 0), size=format_size(size or 0))


def cli_step_line(i: int, m: int, key: str, **counts: int | None) -> str:
    return CLI_STEP.format(i=i, m=m, text=step_text(key, **counts))


def warnings_text(n: int) -> str:
    head = WARNINGS_ONE if n == 1 else WARNINGS_MANY.format(n=format_count(n))
    return head + WARNINGS_WHERE


def left_out_text(n: int) -> str:
    return LEFT_OUT_ONE if n == 1 else LEFT_OUT_MANY.format(n=format_count(n))


def replace_ask(folder: str, with_zip: bool) -> str:
    return (REPLACE_ASK_ZIP if with_zip else REPLACE_ASK).format(folder=folder)


def share_text(exe: str, folder: str, with_zip: bool) -> str:
    return SHARE.format(exe=exe) if with_zip else SHARE_NO_ZIP.format(folder=folder, exe=exe)


# --- Numbers ---------------------------------------------------------------------------------

_KB = 1024


def format_count(n: int) -> str:
    """``1214`` → ``1,214``."""
    return f"{n:,}"


def format_size(n: int) -> str:
    """A size as Windows Explorer shows it (1,024-based): ``512 bytes``, ``12 KB``,
    ``85 MB``, ``1.4 GB``. Never "0 KB" for a non-empty file: anything under 1 KB is bytes."""
    if n < _KB:
        return "1 byte" if n == 1 else f"{n:,} bytes"
    if n < _KB ** 2:
        return f"{round(n / _KB):,} KB"
    if n < _KB ** 3:
        return f"{round(n / _KB ** 2):,} MB"
    return f"{n / _KB ** 3:,.1f} GB"


# --- Left-out reasons (PR-F42-05; shown as "<ref> — <reason>") --------------------------------

LEFT_OUT_TESTDATA = "LEFT_OUT_TESTDATA"
LEFT_OUT_CHARACTERS = "LEFT_OUT_CHARACTERS"
LEFT_OUT_HIDDEN = "LEFT_OUT_HIDDEN"
LEFT_OUT_SYSTEM = "LEFT_OUT_SYSTEM"
LEFT_OUT_COMPILED = "LEFT_OUT_COMPILED"
LEFT_OUT_LINK = "LEFT_OUT_LINK"
LEFT_OUT_UNUSED = "LEFT_OUT_UNUSED"
LEFT_OUT_BAD_NAME = "LEFT_OUT_BAD_NAME"                     # 07 I-1, SEC-F42-06 (f)

LEFT_OUT_REASONS: dict[str, str] = {
    LEFT_OUT_TESTDATA: "test-run data from your PC; players get their own",
    LEFT_OUT_CHARACTERS: "written by the game while it runs; the originals ship from files/",
    LEFT_OUT_HIDDEN: "hidden file or folder",
    LEFT_OUT_SYSTEM: "made by Windows or Python, not part of the game",
    LEFT_OUT_COMPILED: "compiled code; the game uses the .py files",
    LEFT_OUT_LINK: "a link or shortcut; builds copy only real files and folders",
    LEFT_OUT_UNUSED: "the game can't use this file here ({group} takes {suffixes} files)",
    LEFT_OUT_BAD_NAME: "Windows can't use this name. Rename it to include it.",
}
STUDIO_FOLDER = ".studio"
LEFT_OUT_STUDIO = "Studio's own files"                      # LEFT_OUT_HIDDEN for .studio/


def left_out_reason(key: str, ref: str = "", *, group: str = "",
                    suffixes: tuple[str, ...] = ()) -> str:
    """The reason text for ``key``. ``.studio`` (any depth) gets Studio's wording; the
    ``LEFT_OUT_UNUSED`` group and suffixes read ``Images takes .png, .jpg files``."""
    if key == LEFT_OUT_HIDDEN and ref.rsplit("/", 1)[-1].casefold() == STUDIO_FOLDER:
        return LEFT_OUT_STUDIO
    return LEFT_OUT_REASONS[key].format(group=group, suffixes=", ".join(suffixes))


def left_out_line(ref: str, reason: str) -> str:
    return f"{ref} — {reason}"


# --- Field messages (01 §6.3; names.field_problems) -------------------------------------------

NO_NAME = "NO_NAME"
BAD_VERSION = "BAD_VERSION"
NO_ID = "NO_ID"
BAD_ID = "BAD_ID"
RESERVED_ID = "RESERVED_ID"
BAD_ICON = "BAD_ICON"

FIELD_MESSAGES: dict[str, str] = {
    NO_NAME: "Give your game a name.",
    BAD_VERSION: "Use letters, digits, spaces, dots and dashes, like 1.0 or 1.2-beta.",
    NO_ID: ("Every game needs an ID before it's built. "
            "Players' saves are kept in a folder named after it."),
    BAD_ID: ("Use 1 to 40 lowercase letters, digits and dashes, starting with a letter or "
             "digit, like paper-lanterns."),
    RESERVED_ID: "{id} is a reserved name on Windows. Try {id}-game.",
    BAD_ICON: "The icon must be a PNG file in the game folder, at least 16×16.",
}

# --- Build stopped (01 §6.3; 07 I-1 adds B_EXISTS) --------------------------------------------

_TOOL_FIX = ("Click Install build tool, or run: "
             "python -m pip install --require-hashes -r requirements-build.txt")
_PROBLEMS_FIX = "They're listed in Problems. Fix them and build again."
_OTHER_FOLDER_FIX = "Choose another folder."

TOO_BIG_ENTRIES = "more than 50,000 files"
TOO_BIG_DEPTH = "folders more than 32 deep"
TOO_BIG_BYTES = "more than 8 GB"

FAILURES: dict[str, tuple[str, str]] = {
    "B_NO_TOOL": ("The build tool (PyInstaller) isn't installed.", _TOOL_FIX),
    "B_TOOL_VERSION": ("The build tool is version {x}, but this engine needs {y}.", _TOOL_FIX),
    "B_NO_ID": ("config.toml has no Game ID ([game] id).",
                'Add one in Build game…, or add a line under [game]: id = "{slug}"'),
    "B_CONFIG": ("config.toml has problems, so the game can't be built yet.", _PROBLEMS_FIX),
    "B_ERRORS": ("Your game has {n} errors, so it can't be built yet.", _PROBLEMS_FIX),
    "B_PLUGIN_IMPORT": ("minigames/{ref} uses {module}, which builds can't include.",
                        "Use only Python's standard library and engine.minigames.api in "
                        "minigames."),
    "B_OUT_INSIDE": ("The build can't be saved inside the game folder.",
                     "Choose a folder outside {game}, like the builds folder next to it."),
    "B_EXISTS": ('An earlier build "{folder}" is already in {save_to}.',
                 "Add --replace to replace it, or change the version."),
    "B_NAME_TAKEN": ('A folder named "{folder}" is already in {save_to}, and it isn\'t a build.',
                     "Rename or move that folder, or choose another place to save to."),
    "B_IN_USE": ("The earlier build is still running or open, so it can't be replaced.",
                 "Close the game and any window showing that folder, then build again."),
    "B_NO_SPACE": ("There isn't enough free space: the build needs about {need}, "
                   "and {free} is free.",
                   "Free some space, or choose a folder on another drive."),
    "B_NO_FOLDER": ("{save_to} doesn't exist.", _OTHER_FOLDER_FIX),
    "B_CANT_WRITE": ("Studio can't write to {save_to}: it is read-only or in use.",
                     _OTHER_FOLDER_FIX),
    "B_TOO_BIG": ("The game folder is too big to build: {reason}.",
                  "Move files the game doesn't use out of the game folder."),
    "B_COPY_FAILED": ("{ref} couldn't be copied: it was moved, deleted, or is open in another "
                      "program.",
                      "Close programs using it and build again."),
    "B_PACK_FAILED": ("Packing the engine failed.",
                      "Show details lists what the build tool said. If it happens again, "
                      "report it with that text."),
    "B_CRASHED": ("The build stopped unexpectedly.",
                  "Build again. If it happens again, report it with Show details."),
}
B_ERRORS_ONE = "Your game has 1 error, so it can't be built yet."


class BuildStopped(Exception):
    """A ``B_*`` failure found by a build step: ``key`` (a ``FAILURES`` key) and the values
    its texts name. ``values`` are plain strings and ints (report-event safe); the code that
    raises it passes names relative to *Save to* or the game folder, never full paths."""

    def __init__(self, key: str, **values: object) -> None:
        if key not in FAILURES:
            raise KeyError(key)
        super().__init__(key)
        self.key = key
        self.values = values

    def texts(self) -> tuple[str, str]:
        return failure(self.key, **self.values)


def failure(key: str, **values: object) -> tuple[str, str]:
    """``key``'s (message, fix) with ``values`` filled in."""
    message, fix = FAILURES[key]
    if key == "B_ERRORS" and values.get("n") == 1:
        message = B_ERRORS_ONE
    if key == "B_ERRORS" and isinstance(values.get("n"), int):
        values = {**values, "n": format_count(values["n"])}         # type: ignore[arg-type]
    return message.format(**values), fix.format(**values)


def cli_failure_lines(key: str, **values: object) -> tuple[str, str]:
    """The CLI's two lines: ``Can't build: <message>`` and ``Fix: <fix>``."""
    message, fix = failure(key, **values)
    return f"Can't build: {message}", f"Fix: {fix}"


# --- README.txt (PR-F42-18; SEC-F42-15) -------------------------------------------------------

README_LINES = (
    "{name} {version}",
    "",
    "To play, open {exe}. Keep the game and _internal folders next to it.",
    "Unzip the game into a folder you can write to, like Documents or Desktop.",
    "",
    'If Windows says "Windows protected your PC", click More info, then Run anyway. ' + TRUST,
    "",
    "Saves and settings: %APPDATA%\\vn-engine\\{id}",
    "Logs (useful in bug reports): %LOCALAPPDATA%\\vn-engine\\{id}\\logs",
    "",
    "Made with vn-engine. Licenses are in the licenses folder.",
)


def _one_line(text: str) -> str:
    """``text`` without characters that are invisible or break the line (controls, format
    characters, separators; white space becomes a space), so a value can't add lines or
    hide text in the read-me."""
    return "".join(" " if ch.isspace() else ch for ch in text
                   if ch.isspace() or unicodedata.category(ch) not in HIDDEN_CATEGORIES)


def readme_text(*, name: str, version: str, exe: str, app_id: str) -> str:
    """The players' read-me with CRLF line ends and a final CRLF. Only the given values
    appear: no path of the author's PC (PR-F42-07)."""
    values = {"name": _one_line(name), "version": _one_line(version), "exe": _one_line(exe),
              "id": _one_line(app_id)}
    return "".join(line.format(**values) + "\r\n" for line in README_LINES)


def readme_bytes(*, name: str, version: str, exe: str, app_id: str) -> bytes:
    """``readme_text`` as UTF-8 (no byte-order mark)."""
    return readme_text(name=name, version=version, exe=exe, app_id=app_id).encode("utf-8")
