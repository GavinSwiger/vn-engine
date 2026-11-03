"""``python -m engine run [GAME_DIR] [options]``: run any game folder.
``python -m engine edit [GAME_DIR]``: open the scene editor on it (F44, dev runs only).
``python -m engine check [GAME_DIR] …``: Studio's check child (F45, dev runs only).
``python -m engine helper [GAME_DIR]``: Studio's helper child (F47, dev runs only).
``python -m engine build [GAME_DIR] [--out FOLDER] [--zip] [--replace]``: build a game
players can run (F42, dev runs only); ``engine.tools.build`` is imported only inside
``_build``.
``python -m engine lint [GAME_DIR] [--json] [--strict]``: print every problem and unused
thing in a game (F41, dev runs only).

Why this module exists: it is the second launch command (PR-F01-03, TR-F01-02). Like
``main.py`` it runs the Python version check before importing modern engine code, so it
must stay parseable by old Pythons.

``engine.tools.editor`` is imported only inside ``_edit``, so ``run`` never loads it and the
editor process loads nothing of ``engine.app`` but ``cli`` (ADR-0008, F44 I-1, I-12).
Likewise ``engine.tools.check`` is imported only inside ``_check`` (F45 ``04`` §3) and
``_lint`` (F41), and
``engine.tools.helper`` only inside ``_helper`` (F47 ``04`` §3.3).
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


def _helper(game_dir):
    """The ``helper`` handler given to ``cli.main``."""
    from engine.tools.helper import helper_command
    return helper_command(game_dir)


def _build(game_dir, *, out, zip, replace, report):
    """The ``build`` handler given to ``cli.main`` (F42)."""
    from engine.tools.build.command import build_command
    return build_command(game_dir, out=out, zip=zip, replace=replace, report=report)


def _lint(game_dir, *, as_json, strict):
    """The ``lint`` handler given to ``cli.main`` (F41)."""
    from engine.tools.check import lint_command
    return lint_command(game_dir, as_json=as_json, strict=strict)


if __name__ == "__main__":
    _bootcheck.check_python()
    from engine.app import cli
    sys.exit(cli.main(sys.argv[1:], editor=_edit, checker=_check,
                      helper=_helper, builder=_build, linter=_lint))
