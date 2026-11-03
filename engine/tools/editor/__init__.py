"""The simple scene editor (F44): a Tk window in its own process that edits ``.vns`` files.

Imports only ``engine.core``, ``engine.script``, and the standard library (ADR-0008); never
pygame, ``app``, ``render``, ``ui``, ``audio``, or ``runtime``. ``tkinter`` is imported only
inside ``run_editor``, so ``document`` and ``syntax`` stay importable without Tk.
"""

import sys
from pathlib import Path

NO_DISPLAY = "The editor needs a desktop session; no display was found."
_NO_TK_LINUX = ("The editor needs Tkinter. Install your system's python3-tk package "
                "(Fedora: python3-tkinter), then try again.")
_NO_TK_WINDOWS = ("The editor needs Tkinter. Run the Python installer again, choose Modify, "
                  "and tick 'tcl/tk and IDLE'.")
_NO_TK_MACOS = ("The editor needs Tkinter. Use the python.org installer, or run: brew "
                "install python-tk@3.{minor}")


def no_tkinter_message(platform: str = sys.platform) -> str:
    """The one line printed when ``tkinter`` can't be imported (``04`` §7.1 step 1)."""
    if platform.startswith("win"):
        return _NO_TK_WINDOWS
    if platform == "darwin":
        return _NO_TK_MACOS.format(minor=sys.version_info.minor)
    return _NO_TK_LINUX


def game_folder_problem(game_dir: Path | str) -> str | None:
    """The ``edit`` command's folder check (AC-F44-13, PR-F44-01): ``run``'s message for a
    folder that isn't a game, or None. A missing folder or a file gets F01's game-folder
    message; a folder with no ``script/`` gets F02's W01 text, the line ``run`` logs for it.
    A ``script/`` with no ``.vns`` files is a game: the editor opens and shows "No .vns files
    in script/" (AC-F44-15). ``run_editor`` itself doesn't check this."""
    from engine.core.errors import AssetRefError, UserFacingError
    from engine.core.paths import GamePaths
    from engine.core.redact import redact
    from engine.script.messages import format_message
    from engine.tools.editor.document import SCRIPT_DIR

    try:
        paths = GamePaths.for_game(Path(game_dir))
    except UserFacingError as error:
        return redact(error.format())
    try:
        listing = paths.list_dir(SCRIPT_DIR)
    except AssetRefError:
        return None                     # script/ leads outside: the editor says so itself
    return format_message("W01") if listing is None else None


def edit_command(game_dir: Path | str) -> int:
    """``python -m engine edit [GAME_DIR]`` (``engine/__main__.py``): the folder check,
    then ``run_editor``. Returns the process exit code."""
    problem = game_folder_problem(game_dir)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 1
    return run_editor(game_dir)


def run_editor(game_dir: Path | str) -> int:
    """Open the editor on ``game_dir`` and run it until the window closes. Returns the
    process exit code: 0, or 1 after printing one line to stderr when Tk, the display, or
    the game folder is missing (``04`` §7.1)."""
    try:
        import tkinter
    except ImportError:
        print(no_tkinter_message(), file=sys.stderr)
        return 1
    from engine.core.errors import UserFacingError
    from engine.core.paths import GamePaths
    from engine.core.redact import redact

    try:
        paths = GamePaths.for_game(Path(game_dir))
    except UserFacingError as error:
        print(redact(error.format()), file=sys.stderr)
        return 1
    from engine.tools.editor.theme import declare_dpi_awareness

    declare_dpi_awareness()             # before Tk reads the screen's DPI (F45 08 §10)
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        print(NO_DISPLAY, file=sys.stderr)
        return 1
    from engine.tools.editor.window import EditorWindow

    try:
        EditorWindow(root, paths)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tkinter.TclError:
            pass                        # already closed by the window
    return 0
