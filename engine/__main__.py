"""``python -m engine run [GAME_DIR] [options]``: run any game folder.
``python -m engine edit [GAME_DIR]``: open the scene editor on it (F44, dev runs only).
``python -m engine check [GAME_DIR] …``: Studio's check child (F45, dev runs only).

Why this module exists: it is the second launch command (PR-F01-03, TR-F01-02). Like
``main.py`` it runs the Python version check before importing modern engine code, so it
must stay parseable by old Pythons.

``engine.tools.editor`` is imported only inside ``_edit``, so ``run`` never loads it and the
editor process loads nothing of ``engine.app`` but ``cli`` (ADR-0008, F44 I-1, I-12).
Likewise ``engine.tools.check`` is imported only inside ``_check`` (F45 ``04`` §3).
"""

import sys

from engine import _bootcheck


def _edit(game_dir):
    """The ``edit`` handler given to ``cli.main``."""
    from engine.tools.editor import edit_command
    return edit_command(game_dir)


def _check(game_dir, *, report, overlay, launch):
    """The ``check`` handler given to ``cli.main``."""
    from engine.tools.check import check_command
    return check_command(game_dir, report=report, overlay=overlay, launch=launch)


if __name__ == "__main__":
    _bootcheck.check_python()
    from engine.app import cli
    sys.exit(cli.main(sys.argv[1:], editor=_edit, checker=_check))
