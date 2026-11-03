"""Build names and the dialog's field checks (F42 ``01`` §4 edge cases, PR-F42-02, -10, -20;
SEC-F42-12).

Why this module exists: the folder, exe and zip names come from the game's title, which is
author text: it may hold characters Windows can't use in a file name, invisible characters
that disguise the exe (``Lanterns\\u202Egnp.exe`` shows as ``Lanternsexe.png``), or a device
name. One cleaning rule serves the CLI, the step machine and Studio's ``Makes:`` hint.

- ``clean_name``: drop ``HIDDEN_CATEGORIES`` (Cc, Cf, Cs, Zl, Zp; F30's set, ``07`` I-2),
  NFC, drop ``<>:"/\\|?*``, collapse white space, strip leading and trailing dots and spaces,
  cut to 60 characters (never inside a grapheme); empty or a device name → the Game ID.
- ``folder_name`` / ``exe_name`` / ``zip_name``: ``<Name> <Version> Windows``,
  ``<Name>.exe``, ``<folder>.zip``.
- ``check_version`` / ``field_problems`` / ``use_slug``: the dialog's field messages.
- ``file_version``: the exe's numeric file version (``1.2-beta`` → ``1.2.0.0``).

Shared module (``tools/editor`` may import it): standard library, ``core`` and ``script``.
"""

import re
import unicodedata

from engine.core.graphemes import HIDDEN_CATEGORIES, iter_graphemes
from engine.core.paths import RESERVED_APP_IDS, is_device_name, is_valid_app_id, slugify
from engine.tools.build import texts

NAME_MAX = 60
PLATFORM_WINDOWS = "Windows"
EXE_SUFFIX = ".exe"
ZIP_SUFFIX = ".zip"
FALLBACK_ID = "game"                     # only when the Game ID itself isn't valid yet

_UNSAFE_CHARS = frozenset('<>:"/\\|?*')
_SPACES = re.compile(r"\s+")
VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z .+_-]{0,31}", re.ASCII)
_LEADING_NUMBERS = re.compile(r"[0-9]+(?:\.[0-9]+){0,3}", re.ASCII)
_VERSION_PART_MAX = 65535                # a Windows version resource part is 16 bits


def _drop_hidden(text: str) -> str:
    """White space (tabs and line breaks among it) becomes a space; other hidden characters
    are dropped."""
    return "".join(" " if ch.isspace() else ch for ch in text
                   if ch.isspace() or unicodedata.category(ch) not in HIDDEN_CATEGORIES)


def _clean(text: str) -> str:
    """The cleaning without the length cut or the fallback."""
    text = unicodedata.normalize("NFC", _drop_hidden(text))
    text = "".join(ch for ch in text if ch not in _UNSAFE_CHARS)
    return _SPACES.sub(" ", text).strip(" .")


def _cut(text: str, limit: int) -> str:
    """At most ``limit`` code points, whole graphemes only."""
    kept: list[str] = []
    total = 0
    for cluster in iter_graphemes(text):
        if total + len(cluster) > limit:
            break
        kept.append(cluster)
        total += len(cluster)
    return "".join(kept)


def clean_name(title: str, app_id: str) -> str:
    """``title`` as a file name Windows can use and players can read (module docstring).
    An empty result or a Windows device name gives ``app_id`` (``game`` if that isn't a
    valid id either)."""
    name = _cut(_clean(title), NAME_MAX).rstrip(" .")
    if not name or is_device_name(name):
        return app_id if is_valid_app_id(app_id) else FALLBACK_ID
    return name


def clean_version(version: str) -> str:
    """``version`` for a file name: a valid version is kept as is; anything else gets
    ``clean_name``'s cleaning (no fallback; may be empty)."""
    if check_version(version) is None:
        return version
    return _cut(_clean(version), 32).rstrip(" .")


def folder_name(title: str, version: str, app_id: str, platform: str = PLATFORM_WINDOWS) -> str:
    """``<Name> <Version> Windows`` (PR-F42-02); the version part is left out when empty."""
    parts = [clean_name(title, app_id), clean_version(version), platform]
    return " ".join(part for part in parts if part)


def exe_name(title: str, app_id: str) -> str:
    """``<Name>.exe``, ending in exactly one ``.exe`` (a title ending in ``.exe`` loses it
    first, so ``Game.exe`` stays ``Game.exe``)."""
    name = clean_name(title, app_id)
    if name.casefold().endswith(EXE_SUFFIX):
        name = name[:-len(EXE_SUFFIX)].rstrip(" .")
        if not name or is_device_name(name):
            name = app_id if is_valid_app_id(app_id) else FALLBACK_ID
    return name + EXE_SUFFIX


def zip_name(folder: str) -> str:
    return folder + ZIP_SUFFIX


def check_version(version: str) -> str | None:
    """None for a valid version, else the ``BAD_VERSION`` key (01 §4: letters, digits,
    ``.+_-`` and spaces, 1 to 32 characters, starting with a letter or digit, not ending in
    a space or dot)."""
    if VERSION_RE.fullmatch(version) is None or version.endswith((" ", ".")):
        return texts.BAD_VERSION
    return None


def file_version(version: str) -> str:
    """The exe's file version (PR-F42-20): the leading dot-separated numbers, padded to
    four parts (``1.2-beta`` → ``1.2.0.0``, ``beta`` → ``0.0.0.0``); a part over 65535
    becomes 65535."""
    match = _LEADING_NUMBERS.match(version)
    numbers = [min(int(part), _VERSION_PART_MAX) for part in match.group().split(".")] \
        if match else []
    numbers += [0] * (4 - len(numbers))
    return ".".join(str(n) for n in numbers)


def check_id(app_id: str) -> str | None:
    """None for a valid Game ID, else ``NO_ID``, ``RESERVED_ID`` or ``BAD_ID``."""
    if app_id == "":
        return texts.NO_ID
    if app_id in RESERVED_APP_IDS:
        return texts.RESERVED_ID
    if not is_valid_app_id(app_id):
        return texts.BAD_ID
    return None


def check_title(title: str) -> str | None:
    """None when the title has something to show, else ``NO_NAME``."""
    return texts.NO_NAME if not _drop_hidden(title).strip() else None


FIELD_NAME, FIELD_VERSION, FIELD_ID = "name", "version", "id"


def field_problems(title: str, version: str, app_id: str) -> dict[str, str]:
    """The dialog's field messages: field (``name``, ``version``, ``id``) → its §6.3 text,
    only for fields with a problem. Empty: every field is valid."""
    problems: dict[str, str] = {}
    for field, key in ((FIELD_NAME, check_title(title)), (FIELD_VERSION, check_version(version)),
                       (FIELD_ID, check_id(app_id))):
        if key is not None:
            problems[field] = texts.FIELD_MESSAGES[key].format(id=app_id)
    return problems


def use_slug(title: str) -> str:
    """The Game ID the dialog offers (PR-F42-10): ``slugify(title)``, always valid."""
    return slugify(title)


def use_slug_text(title: str) -> str:
    """The **Use <slug>** button text."""
    return texts.ID_USE.format(slug=use_slug(title))
