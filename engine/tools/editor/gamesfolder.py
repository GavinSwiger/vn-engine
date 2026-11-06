"""The Studio app's games folder: ``<Documents>/vn-engine`` (``paths.games_dir``).

Why this module exists: someone who unzips the Studio app and double-clicks ``vn-engine
Studio.exe`` has no game folder yet, and the app folder itself must never be written to
(it may be read-only, and an update replaces it). So the app opens Studio on the last game
it opened, else on its own copy of the example game, "Paper Lanterns", made in the games
folder the first time (``start_folder``). New game and Open game start there
(``paths.default_games_dir``).

Used only by the Studio app (``engine.__main__.studio_app_main``, ``edit_command``); a dev
run never calls ``start_folder``. Imports ``core`` and the standard library (tkinter only
inside ``show_start_error``).
"""

import os
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from engine.core.paths import engine_root, games_dir, is_editor_build, studio_user_dir

EXAMPLE_GAME_NAME: Final = "Paper Lanterns"
EXAMPLE_GAME_DIRNAME: Final = "game"            # under engine_root(): the bundled example
LAST_GAME_FILE: Final = "last-game.txt"         # in studio_user_dir()
LAST_GAME_MAX_BYTES: Final = 4096
# What a run, a playtest or Studio writes in a game folder: never part of the example copy.
SKIPPED_TOP: Final = frozenset({".studio", "logs", "saves", "persistent", "settings",
                                "characters", "builds"})
SKIPPED_ANYWHERE: Final = frozenset({"__pycache__"})
NO_GAMES_FOLDER: Final = ("vn-engine Studio couldn't find your Documents folder, so it has "
                          "nowhere to keep your games.")
COPY_FAILED: Final = ("vn-engine Studio couldn't make the example game in {folder}: {reason}")


def example_game_dir() -> Path:
    """The example game the app carries (read only): ``engine_root()/game``."""
    return engine_root() / EXAMPLE_GAME_DIRNAME


def _skip(rel: Path, entry: os.DirEntry) -> bool:
    if entry.is_symlink() or entry.name in SKIPPED_ANYWHERE:
        return True
    return len(rel.parts) == 0 and entry.name in SKIPPED_TOP


def copy_example(target: Path, source: Path | None = None) -> None:
    """Copy the example game to ``target`` (which must not exist): every regular file but
    the run-time folders (``SKIPPED_TOP``), ``__pycache__`` and links. Made beside
    ``target`` under a temporary name and renamed at the end, so a half copy is never
    opened. Raises ``OSError``."""
    source = example_game_dir() if source is None else source
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.partial-{os.getpid()}")
    if partial.exists():
        shutil.rmtree(partial)
    try:
        stack: list[Path] = [Path()]
        while stack:
            rel = stack.pop()
            (partial / rel).mkdir(parents=True, exist_ok=True)
            with os.scandir(source / rel) as entries:
                listed = sorted(entries, key=lambda e: e.name)
            for entry in listed:
                if _skip(rel, entry):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(rel / entry.name)
                elif entry.is_file(follow_symlinks=False):
                    shutil.copyfile(entry.path, partial / rel / entry.name)
        os.rename(partial, target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def last_game() -> Path | None:
    """The game folder the Studio app last opened, if it's still a game folder."""
    from engine.tools.editor import game_folder_problem

    folder = studio_user_dir()
    if folder is None:
        return None
    try:
        data = (folder / LAST_GAME_FILE).read_bytes()[:LAST_GAME_MAX_BYTES + 1]
    except OSError:
        return None
    if len(data) > LAST_GAME_MAX_BYTES:
        return None
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if not text or "\n" in text:
        return None
    game = Path(text)
    if not game.is_absolute() or not game.is_dir() or game_folder_problem(game) is not None:
        return None
    return game


def remember_game(game: Path) -> None:
    """Note ``game`` as the Studio app's last game (silently skipped when it can't be)."""
    if not is_editor_build():
        return
    folder = studio_user_dir()
    if folder is None:
        return
    try:
        (folder / LAST_GAME_FILE).write_text(str(Path(game).absolute()), encoding="utf-8")
    except (OSError, ValueError):
        pass


def start_folder() -> Path:
    """The game the Studio app opens with no folder given: the last game, else
    ``<games folder>/Paper Lanterns``, copied from the example game first when missing.
    Raises ``LookupError`` (``NO_GAMES_FOLDER``) or ``OSError`` (the copy failed)."""
    game = last_game()
    if game is not None:
        return game
    games = games_dir()
    if games is None:
        raise LookupError(NO_GAMES_FOLDER)
    example = games / EXAMPLE_GAME_NAME
    if not example.exists():
        copy_example(example)
    return example


def show_start_error(text: str) -> None:
    """A message box with ``text`` (the app has no console); never raises."""
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("vn-engine Studio", text, parent=root)
        root.destroy()
    except Exception:                       # noqa: BLE001  (nowhere else to say it)
        print(text, file=sys.stderr)


def studio_app_start(argv: Sequence[str], *, edit: Callable[[Path], int]) -> int:
    """``vn-engine Studio.exe [GAME_DIR]``: Studio on ``GAME_DIR`` when given, else on
    ``start_folder()``. More than one argument, or an option, exits 2."""
    if len(argv) > 1 or (argv and argv[0].startswith("-")):
        return 2
    if argv:
        return edit(Path(argv[0]).absolute())
    try:
        game = start_folder()
    except LookupError as exc:
        show_start_error(str(exc))
        return 1
    except OSError as exc:
        games = games_dir()
        show_start_error(COPY_FAILED.format(folder=games if games is not None else "",
                                            reason=exc.strerror or type(exc).__name__))
        return 1
    return edit(game)


__all__ = ["COPY_FAILED", "EXAMPLE_GAME_NAME", "LAST_GAME_FILE", "NO_GAMES_FOLDER",
           "SKIPPED_TOP", "copy_example", "example_game_dir", "last_game", "remember_game",
           "show_start_error", "start_folder", "studio_app_start"]
