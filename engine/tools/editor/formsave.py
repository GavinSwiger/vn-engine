"""Database edits are saved at once (first-game fix, 2026-11-06).

Why this module exists: a Database form (a new character, a variable's starting value, a
minigame data set, a rename everywhere) writes its change into the editor's copy of
``database.vns``, ``main.vns`` or ``config.toml`` as one undo step. Those used to stay
unsaved, so a first-time author, who never opened those files, met "* database.vns" and a
save prompt on closing, and the Guide's ticks waited for a save they didn't know to make.

``apply_saved(win, plan, verify)`` is ``win.apply_plan`` followed by a save of each file the
plan touched that had **no unsaved changes before it**: the form's change is complete and
checked (``verify``) before it is written, so saving it is safe; a file the author was
typing in stays unsaved, so their half-written text is never saved behind their back (Play
and Ctrl+S save it, as before). Ctrl+Z in the file still undoes the change. A save that
fails shows its dialog and leaves the file unsaved, as Ctrl+S does.

No Tk here beyond what ``win`` does; ``win`` is the Studio window (``apply_plan``,
``files``, ``save_record``, ``request_check``, ``after_saves``, ``armed``).
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any


def _dirty(win: Any, ref: str) -> bool:
    record = win.files.get(ref)
    return record is not None and bool(record.dirty)


def save_clean(win: Any, refs: Iterable[str]) -> bool:
    """Save each of ``refs`` that is now unsaved; then arm the window, check and update a
    running game, as a save does. False when a save failed (its dialog was shown)."""
    saved = False
    for ref in refs:
        record = win.files.get(ref)
        if record is None or not record.dirty or not record.editable:
            continue
        if not win.save_record(record):
            return False
        saved = True
    if saved:
        win.armed = True
        win.request_check()
        win.after_saves()
    return True


def apply_saved(win: Any, plan: Any, verify: Callable[[Mapping[str, str]], bool]) -> bool:
    """``win.apply_plan(plan, verify)``, then the files it touched that were saved before
    are saved again (module docstring). False when the plan wasn't applied."""
    clean = [fp.ref for fp in plan.files if not _dirty(win, fp.ref)]
    if not win.apply_plan(plan, verify):
        return False
    save_clean(win, clean)
    return True


__all__ = ["apply_saved", "save_clean"]
