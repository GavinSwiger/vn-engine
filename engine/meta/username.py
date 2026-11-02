"""The player's login name for ``{username}`` (F30 ``04`` §6.3; SEC-F30-01, 06).

Why this module exists: a story may show the player's computer user name, but only after the
author offers it (``[meta] username``) and the player allows it. That is the engine's one
opt-in OS identity query, so it lives alone here: this is the only module that calls
``getpass.getuser`` (the privacy scan allows it here and nowhere else), and only
``app/fourthwall.py`` imports it (the import-rule test). ``ui`` and ``render`` get a plain
``Callable[[], str | None]``.

The name is read lazily, once per opt-in, and kept in memory only. Nothing here logs, writes
a file, or reads any other identity source (no other OS call, no profile folder name, no
variable of the process's surroundings); the caller decides what an unreadable name means.

Standard library (``getpass``, ``unicodedata``, ``typing``) and ``engine.core`` only.
"""

import getpass
import unicodedata
from typing import Callable

from engine.core.constants import USERNAME_MAX, USERNAME_MAX_CODE_POINTS, USERNAME_RAW_MAX
from engine.core.graphemes import iter_graphemes

# Removed from the name (SEC-F30-06): controls (C0, C1), format characters (bidi marks,
# ZWJ: D4), lone surrogates, and line or paragraph separators.
_DROPPED_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))


def clean(raw: str) -> str:
    """The name as it may be drawn: at most ``USERNAME_MAX`` graphemes and
    ``USERNAME_MAX_CODE_POINTS`` code points; ``""`` when nothing is left.

    In order: cut to ``USERNAME_RAW_MAX`` code points; keep what follows the last ``\\``
    (``CORP\\aiko`` -> ``aiko``); NFC; drop categories Cc, Cf, Cs, Zl, Zp; strip white
    space; cut to ``USERNAME_MAX`` graphemes, then to ``USERNAME_MAX_CODE_POINTS`` code
    points. Tag-like text (``{b}``) is kept: the name is substituted after tag parsing, so it
    draws literally (SEC-F30-06 (d))."""
    text = raw[:USERNAME_RAW_MAX]
    text = text.rpartition("\\")[2]
    text = unicodedata.normalize("NFC", text)
    text ="".join(c for c in text if unicodedata.category(c) not in _DROPPED_CATEGORIES)
    text = text.strip()
    kept: list[str] = []
    for count, cluster in enumerate(iter_graphemes(text)):
        if count >= USERNAME_MAX:
            break
        kept.append(cluster)
    return "".join(kept)[:USERNAME_MAX_CODE_POINTS].rstrip()


def read_login_name() -> str | None:
    """``clean(getpass.getuser())``, or None when it can't be read. Only ``Exception`` means
    unreadable (SEC-F30-06 (b)): ``KeyboardInterrupt`` and ``SystemExit`` propagate."""
    try:
        raw = getpass.getuser()
    except Exception:
        return None
    if not isinstance(raw, str):
        return None
    return clean(raw)


class UsernameSource:
    """The name for the textbox, read at most once per opt-in (``04`` §6.3, D1).

    ``allowed``: whether the player allows it now (``app``: the ``username_use`` setting
    is 2). ``read``: the reader (tests always pass a fake, SEC-F30-11). ``on_failure``: called
    the first time in the session that a read gives no name (``app`` logs W188, which names
    only the fallback word)."""

    def __init__(self, *, allowed: Callable[[], bool],
                 read: Callable[[], str | None] = read_login_name,
                 on_failure: Callable[[], None]) -> None:
        self._allowed = allowed
        self._read = read
        self._on_failure = on_failure
        self._name: str | None = None
        self._failed = False            # this opt-in's read gave no name
        self._reported = False          # on_failure already called this session

    def name(self) -> str | None:
        """The cleaned name, or None (not allowed, or unreadable in this opt-in)."""
        if not self._allowed():
            return None
        if self._name is not None:
            return self._name
        if self._failed:
            return None
        try:
            value = self._read()
        except Exception:
            value = None
        value = clean(value) if isinstance(value, str) else ""
        if not value:
            self._failed = True
            if not self._reported:
                self._reported = True
                self._on_failure()
            return None
        self._name = value
        return value

    def forget(self) -> None:
        """Drop the cached name and the failed mark (the row turned off); a later opt-in in
        the same session may read once more (D1)."""
        self._name = None
        self._failed = False
