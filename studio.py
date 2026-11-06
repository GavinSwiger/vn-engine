"""The Studio app's entry script: ``vn-engine Studio.exe`` (built by ``scripts/build_studio.py``).

Why this file exists: PyInstaller freezes one script into the exe; this one runs
``engine.__main__.studio_app_main``, which opens Studio on a game folder, or with ``--child
COMMAND …`` runs ``python -m engine COMMAND …`` for Studio's own children (the app has no
separate Python to start). Outside the Studio app it does nothing but exit 2: a dev run
uses ``python -m engine edit``, and a built game's exe is made from ``main.py``.

It must stay parseable by old Pythons: the version check runs before any modern engine
code is imported.
"""

import sys

from engine import _bootcheck

if __name__ == "__main__":
    _bootcheck.check_python()
    from engine.__main__ import studio_app_main
    sys.exit(studio_app_main(sys.argv[1:]))
