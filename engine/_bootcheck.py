"""Python and pygame-ce checks that run before any other engine code.

Why this module exists: an author who runs the engine on an old Python, without
pygame-ce, or with the original ``pygame`` package must get one plain paragraph naming the
problem and the exact fix, not a stack trace (PR-F01-07, TR-F01-03).

It uses the standard library only and must stay parseable by Python 3.6 (no walrus, no
``X | None`` annotations, no positional-only parameters), because it is the code that
tells a Python 3.6 user to upgrade.
"""

import sys

MIN_PYTHON = (3, 12)
MIN_PYGAME = (2, 5, 2)
UNTESTED_PYGAME = (2, 6)
PYGAME_RANGE = "pygame-ce>=2.5.2,<2.6"


def _fail(message):
    """Print one paragraph to stderr (if there is one) and exit with code 1."""
    if sys.stderr is not None:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    sys.exit(1)


def _version_text(parts):
    return ".".join(str(part) for part in parts)


def check_python():
    """Exit with code 1 and a one-paragraph message if Python is older than 3.12."""
    current = tuple(sys.version_info[:3])
    if current[:2] < MIN_PYTHON:
        _fail("vn-engine needs Python 3.12 or newer. You are running Python {}. Install "
              "Python 3.12+ from python.org and run the command again."
              .format(_version_text(current)))


def check_pygame():
    """Exit with code 1 and a one-paragraph message if pygame-ce is missing, replaced by
    the original pygame, or older than 2.5.2. Returns a warning text (to be logged once
    logging has started) if pygame-ce is 2.6 or newer, else None."""
    try:
        import pygame
    except ImportError:
        _fail("pygame-ce is not installed. Run: pip install pygame-ce")
    if not getattr(pygame, "IS_CE", False):
        _fail("The original 'pygame' package is installed instead of pygame-ce. "
              "Run: pip uninstall pygame   then pip install pygame-ce")
    version = tuple(getattr(pygame, "vernum", (0, 0, 0))[:3])
    if version < MIN_PYGAME:
        _fail("pygame-ce {} is too old; vn-engine needs pygame-ce 2.5.2 or newer (below "
              "2.6). Run: pip install --upgrade \"{}\""
              .format(_version_text(version), PYGAME_RANGE))
    if version >= UNTESTED_PYGAME:
        return ("pygame-ce {} is newer than the tested range (2.5.x). If something looks "
                "wrong, run: pip install \"{}\"".format(_version_text(version), PYGAME_RANGE))
    return None
