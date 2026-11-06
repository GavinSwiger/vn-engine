"""The command line that starts an engine child (``python -m engine <command> …``).

Why this module exists: Studio starts the engine as a child for Play, Update, the check
job, stage stills, the live map, Build game and New game's second window. In a dev run
that's ``<python> [flags] -m engine <command> …``. The Studio app (``paths.is_editor_build``)
has no Python to run: it starts its own exe in a hidden mode, ``vn-engine Studio.exe
--child <command> …``, which ``engine.__main__.studio_app_main`` hands to the same
``cli.main`` as ``python -m engine``. Every such command line is built here, so the two
forms can't drift apart.

Imports ``core.paths`` and the standard library only.
"""

import sys
from collections.abc import Sequence

from engine.core.paths import is_editor_build

CHILD_SWITCH = "--child"
# The interpreter flags a dev child may take (-B: no __pycache__; -E: no PYTHON* variables;
# -P: no unsafe sys.path entry). The Studio app's frozen interpreter already ignores PYTHON*
# variables and never puts the CWD on sys.path, and its child prelude turns off bytecode
# writing, so there they are dropped.
PYTHON_FLAGS = frozenset({"-B", "-E", "-P"})


def engine_argv(*args: str, python_flags: Sequence[str] = ()) -> list[str]:
    """``[sys.executable, *python_flags, "-m", "engine", *args]`` in a dev run;
    ``[sys.executable, "--child", *args]`` in the Studio app."""
    unknown = [flag for flag in python_flags if flag not in PYTHON_FLAGS]
    if unknown:
        raise ValueError(f"not an interpreter flag: {unknown[0]!r}")
    if is_editor_build():
        return [sys.executable, CHILD_SWITCH, *args]
    return [sys.executable, *python_flags, "-m", "engine", *args]


def server_prefix(python_flags: Sequence[str] = ()) -> list[str]:
    """What comes between the program and the command for a child another app starts (the
    MCP server): ``[*python_flags, "-m", "engine"]``, or ``["--child"]`` in the Studio app."""
    return engine_argv(python_flags=python_flags)[1:]


__all__ = ["CHILD_SWITCH", "PYTHON_FLAGS", "engine_argv", "server_prefix"]
