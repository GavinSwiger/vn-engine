"""Which game-folder entries a build leaves out, and why (F42 PR-F42-05, D3; SEC-F42-06 f).

Why this module exists: the copy walk (``tree.copy_game``) and Studio (a future "what ships"
view) must agree on the rows, so they are one pure function. ``classify(parts, kind)`` takes
an entry's game-relative name parts (``("images", "bg", "club.psd")``) and its kind from a
listing (``paths.dir_entry_kind``'s ``ENTRY_*``; never followed) and returns a ``LeftOut``
or None (ships). Rows, first match wins:

1. Links, junctions, reparse points, devices, FIFOs (``ENTRY_LINK``, ``ENTRY_SPECIAL``) →
   ``LEFT_OUT_LINK``.
2. A name Windows can't write safely (a device name such as ``CON`` or ``com¹.png``, a
   trailing dot or space, ``<>:"/\\|?*``, a control character) → ``LEFT_OUT_BAD_NAME``.
3. Top level, casefold: ``logs``, ``saves``, ``persistent``, ``settings`` →
   ``LEFT_OUT_TESTDATA``; ``characters`` → ``LEFT_OUT_CHARACTERS`` (``files/`` ships).
4. Any depth: a name starting with ``.`` (``.studio`` among them) → ``LEFT_OUT_HIDDEN``;
   ``__pycache__``, ``Thumbs.db``, ``desktop.ini`` (casefold) → ``LEFT_OUT_SYSTEM``.
5. Under ``minigames/``, a file that isn't ``.py``: compiled Python (``.pyc``, ``.pyo``,
   ``.pyd``, ``.so``) → ``LEFT_OUT_COMPILED``; anything else → ``LEFT_OUT_UNUSED``.
6. (D3) Under ``script/``, ``images/``, ``audio/``, a file whose suffix (casefold) its
   ``ASSET_GROUPS`` row doesn't take → ``LEFT_OUT_UNUSED``, unless its name starts with
   ``license``, ``licence``, ``readme``, ``credits`` or ``copying`` (casefold).

Top-level folder names compare in exact case, as the engine reads them (``images/``, not
``Images/``). Shared module (``tools/editor`` may import it): standard library, ``core``,
``script``.
"""

import unicodedata
from dataclasses import dataclass

from engine.core.constants import RESERVED_DIRNAMES, WRITE_ROOT_DIRNAMES
from engine.core.paths import ENTRY_DIR, ENTRY_FILE, ENTRY_LINK, ENTRY_SPECIAL, is_device_name
from engine.script.assetgroups import ASSET_GROUPS
from engine.tools.build import texts

__all__ = ["ENTRY_DIR", "ENTRY_FILE", "ENTRY_LINK", "ENTRY_SPECIAL", "LeftOut", "classify",
           "is_safe_windows_name"]

_RESERVED = frozenset(name.casefold() for name in RESERVED_DIRNAMES)
_TEST_DATA = frozenset(name.casefold() for name in WRITE_ROOT_DIRNAMES) - _RESERVED
_SYSTEM_NAMES = frozenset({"__pycache__", "thumbs.db", "desktop.ini"})
_UNSAFE_CHARS = frozenset('<>:"/\\|?*')
_MINIGAMES = "minigames"
_PYTHON_SUFFIX = ".py"
_COMPILED_SUFFIXES = (".pyc", ".pyo", ".pyd", ".so")
_KEEP_PREFIXES = ("license", "licence", "readme", "credits", "copying")
# D3: the groups whose unusable files are left out, by folder (exact case).
_D3_GROUPS = {group.folder: group for group in ASSET_GROUPS
              if group.key in ("script", "images", "audio")}
_MINIGAMES_GROUP = next(group for group in ASSET_GROUPS if group.folder == _MINIGAMES)


@dataclass(frozen=True, slots=True)
class LeftOut:
    """One left-out entry: its game-relative ``ref`` (``/`` separated; the top-most one, the
    walk never descends into it), the ``LEFT_OUT_*`` ``key``, and for ``LEFT_OUT_UNUSED``
    the group title and the suffixes it takes. ``reason`` and ``line`` are the §6.3 texts."""
    ref: str
    key: str
    group: str = ""
    suffixes: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        return texts.left_out_reason(self.key, self.ref, group=self.group,
                                     suffixes=self.suffixes)

    @property
    def line(self) -> str:
        return texts.left_out_line(self.ref, self.reason)


def is_safe_windows_name(name: str) -> bool:
    """Whether ``name`` can be a file or folder name in the build on Windows: not empty, no
    ``<>:"/\\|?*`` or control character, no trailing dot or space, not a device name
    (SEC-F42-06 f)."""
    if not name or name.endswith((".", " ")) or is_device_name(name):
        return False
    return not any(ch in _UNSAFE_CHARS or unicodedata.category(ch) == "Cc" for ch in name)


def _suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].casefold() if dot > 0 else ""


def classify(parts: tuple[str, ...], kind: int) -> LeftOut | None:
    """The ``LeftOut`` for the entry ``parts`` of kind ``kind``, or None when it ships
    (module docstring for the rows)."""
    ref = "/".join(parts)
    name = parts[-1]
    folded = name.casefold()
    if kind in (ENTRY_LINK, ENTRY_SPECIAL):
        return LeftOut(ref, texts.LEFT_OUT_LINK)
    if not is_safe_windows_name(name):
        return LeftOut(ref, texts.LEFT_OUT_BAD_NAME)
    if len(parts) == 1 and folded in _TEST_DATA:
        return LeftOut(ref, texts.LEFT_OUT_TESTDATA)
    if len(parts) == 1 and folded in _RESERVED:
        return LeftOut(ref, texts.LEFT_OUT_CHARACTERS)
    if name.startswith("."):
        return LeftOut(ref, texts.LEFT_OUT_HIDDEN)
    if folded in _SYSTEM_NAMES:
        return LeftOut(ref, texts.LEFT_OUT_SYSTEM)
    if kind != ENTRY_FILE or len(parts) < 2:
        return None
    suffix = _suffix(name)
    if parts[0] == _MINIGAMES:
        if suffix == _PYTHON_SUFFIX:
            return None
        if suffix in _COMPILED_SUFFIXES:
            return LeftOut(ref, texts.LEFT_OUT_COMPILED)
        return LeftOut(ref, texts.LEFT_OUT_UNUSED, _MINIGAMES_GROUP.title,
                       _MINIGAMES_GROUP.suffixes)
    group = _D3_GROUPS.get(parts[0])
    if group is None or suffix in group.suffixes or folded.startswith(_KEEP_PREFIXES):
        return None
    return LeftOut(ref, texts.LEFT_OUT_UNUSED, group.title, group.suffixes)
