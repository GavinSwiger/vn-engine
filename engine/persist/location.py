"""Where persistent data lives (F12 ``04-technical.md`` §3, §7.4 step 2; ADR-0003 §2, §4).

A dev run keeps it beside the game in ``<game>/persistent/``; a release run in the per-user
data folder of ``[game] id``. A release run without an id has no folder (W53). The engine
creates only three names there: ``persistent.json``, ``persistent.bad.json``, and
``.persistent.json.<8 hex>.tmp``. No file name ever comes from the file's content.
"""

import re
from pathlib import Path

from engine.core.paths import display_path, user_data_dir

FOLDER_NAME = "persistent"
FILE_NAME = "persistent.json"
BAD_NAME = "persistent.bad.json"
TEMP_RE = re.compile(r"\.persistent\.json\.[0-9a-f]{8}\.tmp", re.ASCII)


def user_root(folder_name: str, *, game_root: Path, release: bool,
              app_id: str | None) -> Path | None:
    """A data folder of the engine's own (F16 ``07`` I-10): ``<game>/<folder_name>`` in a
    dev run, else ``user_data_dir(app_id)/<folder_name>``. None when a release run has no
    usable id or no absolute per-user base. Not created here (``safefile.ensure_real_dir``
    does that). ``persistent_root``, F16's ``settings_root``, and F11's ``saves_root`` are
    one-line wrappers."""
    if not release:
        return Path(game_root) / folder_name
    if app_id is None:
        return None
    try:
        base = user_data_dir(app_id)
    except ValueError:
        return None
    return None if base is None else base / folder_name


def persistent_root(*, game_root: Path, release: bool, app_id: str | None) -> Path | None:
    """The persistent folder: ``<game>/persistent`` in a dev run, else
    ``user_data_dir(app_id)/persistent`` (``user_root``)."""
    return user_root(FOLDER_NAME, game_root=game_root, release=release, app_id=app_id)


SAVES_FOLDER_NAME = "saves"


def saves_root(*, game_root: Path, release: bool, app_id: str | None) -> Path | None:
    """The saves folder (F11 ``04`` §7.1): ``<game>/saves`` in a dev run, else
    ``user_data_dir(app_id)/saves`` (``user_root``); None for a release run without a
    usable id (W80). Not created here."""
    return user_root(SAVES_FOLDER_NAME, game_root=game_root, release=release, app_id=app_id)


def display_file(folder: Path, *, game_root: Path | None, name: str = FILE_NAME) -> str:
    """``<file>`` in W50–W55 (and F16's W70–W75 with ``name``): the environment-style path
    of the file ``name`` in ``folder`` (PR-F12-16), e.g.
    ``<game>/persistent/persistent.json``."""
    return display_path(Path(folder) / name, game_root=game_root)


def is_engine_name(name: str) -> bool:
    """True for the only names the engine creates in the persistent folder."""
    return name in (FILE_NAME, BAD_NAME) or TEMP_RE.fullmatch(name) is not None


__all__ = ["BAD_NAME", "FILE_NAME", "FOLDER_NAME", "SAVES_FOLDER_NAME", "TEMP_RE", "display_file",
           "is_engine_name", "persistent_root", "saves_root", "user_root"]
