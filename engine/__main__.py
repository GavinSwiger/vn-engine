"""``python -m engine run [GAME_DIR] [options]``: run any game folder.
``python -m engine edit [GAME_DIR]``: open the scene editor on it (F44, dev runs only).
``python -m engine check [GAME_DIR] …``: Studio's check child (F45, dev runs only).
``python -m engine helper [GAME_DIR]``: Studio's helper child (F47, dev runs only).
``python -m engine build [GAME_DIR] [--out FOLDER] [--zip] [--replace]``: build a game
players can run (F42, dev runs only); ``engine.tools.build`` is imported only inside
``_build``.
``python -m engine lint [GAME_DIR] [--json] [--strict]``: print every problem and unused
thing in a game (F41, dev runs only).
``python -m engine assist-mcp [GAME_DIR] [--read-only] [--no-launch]``: the assistant's MCP
server for AI apps, over stdin and stdout (F48, dev runs only).
``vn-engine Studio.exe`` (the Studio app, ``studio.py``) runs ``studio_app_main``: its
``--child COMMAND …`` is ``python -m engine COMMAND …`` for an app with no Python installed.
``run`` in a dev run gets the developer console (F40): ``engine.tools.console`` is imported
only inside ``_console``, which the bootstrap calls once with the App.

Why this module exists: it is the second launch command (PR-F01-03, TR-F01-02). Like
``main.py`` it runs the Python version check before importing modern engine code, so it
must stay parseable by old Pythons.

``engine.tools.editor`` is imported only inside ``_edit``, so ``run`` never loads it and the
editor process loads nothing of ``engine.app`` but ``cli`` (ADR-0008, F44 I-1, I-12).
Likewise ``engine.tools.check`` is imported only inside ``_check`` (F45 ``04`` §3) and
``_lint`` (F41), and
``engine.tools.helper`` only inside ``_helper`` (F47 ``04`` §3.3), and
``engine.tools.assistant`` only inside ``_assist_mcp`` (F48 ``04`` §7.6, AC-F48-01: the one
place outside ``engine/tools`` that imports it). Nothing on that path writes to stdout before
``serve`` takes it (``07`` I-10).
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


def _assist_mcp(game_dir, *, read_only, launch):
    """The ``assist-mcp`` handler given to ``cli.main`` (F48): imports the server only
    now, and prints nothing first, since stdout is the protocol stream."""
    from pathlib import Path

    from engine.tools.assistant.mcp import serve
    return serve(Path(game_dir), read_only=read_only, launch=launch)


def _console(app):
    """The console factory given to ``cli.main`` (F40): called by ``bootstrap.launch``
    only in a dev run."""
    from engine.tools.console import install_console
    return install_console(app)


def main(argv):
    """``python -m engine …`` with every handler: what ``python -m engine`` runs, and what
    the Studio app runs for ``--child``."""
    from engine.app import cli
    return cli.main(argv, editor=_edit, checker=_check,
                    helper=_helper, builder=_build, linter=_lint,
                    console=_console, assist_mcp=_assist_mcp)


# The Studio app's hidden child mode; equals ``engine.core.childcmd.CHILD_SWITCH``.
CHILD_SWITCH = "--child"


def studio_app_main(argv):
    """``vn-engine Studio.exe`` (``studio.py``, the Studio app's entry): ``--child COMMAND
    …`` is ``python -m engine COMMAND …`` (Studio's own children: Play, the check job, the
    helper, Build game, a new Studio window); anything else opens Studio on a game folder
    (the one given, else the last game or Paper Lanterns in Documents/vn-engine). Only the
    Studio app (an editor build) gets past ``cli.editor_prelude``: a built game, or this
    function in a dev run, exits 2."""
    from engine.app import cli
    if not cli.editor_prelude():
        return 2
    if argv[:1] == [CHILD_SWITCH]:
        return main(argv[1:])
    from engine.tools.editor.gamesfolder import studio_app_start
    return studio_app_start(argv, edit=_edit)


if __name__ == "__main__":
    _bootcheck.check_python()
    sys.exit(main(sys.argv[1:]))
