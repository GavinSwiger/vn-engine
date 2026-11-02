"""The texts of persistent data's file warnings W50–W53 and its INFO lines (F12 design §5.4;
``07`` I-7; AC-F12-41).

Why this module exists: the launch (``app/persistence.py``, F12 step 6) and the sync
(``sync.py``) report the same file problems, so their words live in one place. W54, W55, and
W57 are the store's (``runtime/persistent.py``), since the store logs them.

Every text names the file by its display path (``location.display_file``) and gives a fixed
reason word; none holds a value, a stored name, or file content (SEC-F12-09). Forms marked
"draft" have no approved wording yet (narrative review).
"""

from engine.persist.location import BAD_NAME

# W50 reasons are fileformat's (``NOT_VALID_JSON`` …); W52 reasons are the writer's.


def bad_file_text(file: str, reason: str, *, kept: bool, mid_session: bool = False) -> str:
    """W50. ``kept``: the file was moved to ``persistent.bad.json``. Without a copy (a read
    error, or a failed rename) the file is left alone and nothing is saved this session
    (I-7). ``mid_session``: found by a merge, so the game keeps the data it has (draft)."""
    start = f"persistent data in {file} couldn't be used ({reason}), "
    if kept:
        if mid_session:
            return (start + "so this game keeps its own persistent data and saves it there. "
                    f"The old file was kept as {BAD_NAME}.")
        return (start + "so this game starts with fresh persistent data. The old file was "
                f"kept as {BAD_NAME}.")
    if mid_session:
        return (start + "so this game keeps its persistent data in memory and won't save it "
                "this session. The file was left unchanged.")
    return (start + "so this game runs with fresh persistent data that won't be saved this "
            "session. The file was left unchanged.")


def newer_file_text(file: str, *, mid_session: bool = False) -> str:
    """W51. ``mid_session``: another copy wrote it while this one runs (draft)."""
    start = (f"persistent data in {file} was made by a newer engine version, so it isn't used "
             "or changed this session. ")
    if mid_session:
        return start + "The game keeps its persistent data in memory and won't save it."
    return start + "The game runs with fresh persistent data that won't be saved."


def save_failed_text(file: str, reason: str) -> str:
    """W52."""
    return (f"persistent data couldn't be saved to {file} ({reason}). The game keeps it in "
            "memory and tries again at the next change.")


def final_write_skipped_text(file: str) -> str:
    """W52 at quit: the last write didn't finish within ``CLOSE_WAIT_S`` (SEC-F12-07; the
    reason word is ``couldn't write``; draft)."""
    return (f"persistent data couldn't be saved to {file} (couldn't write). The latest changes "
            "were not saved before the game closed.")


NO_ID_TEXT = ("persistent data won't be saved, because config.toml has no [game] id. Set a "
              'unique id under [game], e.g. id = "paper-lanterns", before releasing.')   # W53
SAVED_AGAIN_TEXT = "persistent data saved again"
OFF_TEXT = "persistent data is off for this run (--no-persistent)"


__all__ = ["NO_ID_TEXT", "OFF_TEXT", "SAVED_AGAIN_TEXT", "bad_file_text",
           "final_write_skipped_text", "newer_file_text", "save_failed_text"]
