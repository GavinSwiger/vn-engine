"""The documented launcher: ``python main.py [--release] [--bench SECONDS] [--log-level LEVEL]``.

Why this file exists: authors start their game with one command from the project root or
from any other folder (PR-F01-01, PR-F01-02). It always runs ``<repo>/game``, with
``<repo>`` taken from this file's location, never the working directory; use
``python -m engine run <folder>`` for another folder.

It must stay parseable by old Pythons: the version check runs before any modern engine
code is imported.
"""

import sys

from engine import _bootcheck

if __name__ == "__main__":
    _bootcheck.check_python()
    from engine.app.cli import launcher_main
    sys.exit(launcher_main(sys.argv[1:]))
