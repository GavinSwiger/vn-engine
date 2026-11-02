"""The launch phase's view of the game folder: ``game_has``, ``image_source``, and
``audio_files`` (F45 ``04-technical.md`` §3, §7.1 step 7; lifted from ``app/loading.py``).

Why this module exists: ``LaunchJob`` asks the game folder three things (does ``module()``'s
file exist, F04's image scan inputs, F08's audio file check inputs), and two processes
build those answers from ``GamePaths``: the game (``app/loading.py``) and Studio's check
child (``tools/check.py``), which may not import ``app``. So the builders live here, below
both. Each answer comes from ``GamePaths`` listings and ``resolve``: no file is opened
(invariant 9(a)).

Pure: no clock, entropy, or threads (TR-F03-05); imports ``core`` and ``runtime`` only.
"""

from collections.abc import Callable, Iterable

from engine.core.errors import AssetMissing, AssetRefError
from engine.core.paths import GamePaths
from engine.runtime.audio_check import AudioFiles
from engine.runtime.images import ImageSource


def game_has(paths: GamePaths) -> Callable[[str], bool]:
    """``module()``'s one question about the game folder (F03 ``04-technical.md`` §7.9 step
    3, E89c's game-folder form): does it hold the file ``ref`` (``helpers.py``,
    ``helpers/__init__.py``, ``script/helpers.py``)? Answered from ``GamePaths`` listings, so
    no file is opened (invariant 9(a)): membership in the parent folder's ``list_dir``, and
    for a file at the root (``list_dir`` can't name the root: a ref is never empty)
    ``resolve``, which lists the root and checks the one entry. The runtime asks only when
    ``find_spec`` found nothing."""

    def has(ref: str) -> bool:
        parent, _, name = ref.rpartition("/")
        try:
            if parent:
                listing = paths.list_dir(parent)
                return listing is not None and name in listing.files
            return paths.resolve(ref).is_file()
        except (AssetRefError, AssetMissing, OSError):
            return False

    return has


def image_source(paths: GamePaths) -> ImageSource:
    """F04's image scan inputs (launch phase 4, I-7): ``GamePaths.list_dir`` lists each
    folder under ``images/`` (contained, no file opened), and ``locate`` says whether an
    ``image`` declaration's file exists, with ``GamePaths.resolve``'s suggestion (the one
    file-suggestion mechanism) when it doesn't."""

    def locate(ref: str) -> tuple[bool, str | None]:
        try:
            return paths.resolve(ref).is_file(), None
        except AssetMissing as e:
            return False, e.suggestion
        except (AssetRefError, OSError):
            return False, None

    return ImageSource(paths.list_dir, locate)


def audio_files(paths: GamePaths, loop_keys: Iterable[str]) -> AudioFiles:
    """F08's launch file check inputs (phase 6, I-7): ``GamePaths.list_dir`` (``resolve``
    and its cached listing of one folder; no file opened) and the ``[audio.loop_start]``
    keys in config order (``config.audio.loop_start``)."""
    return AudioFiles(paths.list_dir, tuple(loop_keys))


__all__ = ["audio_files", "game_has", "image_source"]
