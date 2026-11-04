"""Redaction, control-character escaping, and truncation of every outgoing string.

Why this module exists: logs and the error screen are made to be shared, so no output
channel may reveal the player's user name or home path (PR-F01-62, SEC-F01-10/11), and no
content string may forge or hide a log line (SEC-F01-09). Every string that leaves the
process goes through one redactor, and every content string embedded in a message goes
through ``echo()`` (redact, then escape, then cut), so redaction always runs before
truncation.

*Why ``core``:* ``logsetup`` (core) needs it, and core may import nothing higher; ``ui`` and
``app`` import it from here.

Everything here is a pure string function. The redaction roots are **passed in** by
``logsetup``; this module makes no home, environment, or other OS lookup (SEC-F01-10 (d)),
so it also works with ``ctypes`` unavailable.
"""

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from engine.core.constants import ECHO_MAX_CHARS

# Profile folder names that are not a person and are kept as written (SEC-F01-10 (c)(ii)).
_KEPT_SEGMENTS = frozenset({"public", "default", "default user", "all users", "shared"})

# A path separator as it appears in text: doubled (repr form) first, then single.
_SEP = r"(?:\\\\|\\|/)"

# The segment after a profile container (§7.10.4 step 2).
_SEGMENT = r"[^\\/'\"\r\n<>|?*]+"

# Profile containers: <drive>:\Users\, <drive>:\Documents and Settings\, and, at the start
# of a path token, /Users/ and /home/. Case-insensitive, any separator form. A \\?\ prefix
# needs no handling: the drive letter that follows it matches on its own.
_PROFILE_RE = re.compile(
    r"(?P<head>"
    r"(?:[A-Za-z]:" + _SEP + r"(?:Users|Documents and Settings)"
    r"|(?:^|(?<=[\s'\"(=:]))" + _SEP + r"(?:Users|home))"
    + _SEP + r")"
    r"(?P<seg>" + _SEGMENT + r")",
    re.IGNORECASE | re.MULTILINE,
)

# A root never matches inside a longer segment: it must be followed by one of these.
_ROOT_END = r"(?=[\\/'\"\s,;:)\]>]|$)"


@dataclass(frozen=True)
class RedactRoot:
    """One redaction root: an absolute path and the token that replaces it."""

    token: str      # '<game>', '<engine>', '~', '<python>', '%APPDATA%', '%LOCALAPPDATA%', '$XDG_DATA_HOME', '<temp>'
    path: str       # absolute path as a string


def _normalize_root(path: str) -> str | None:
    """The root without trailing separators, or None for an empty or bare drive root."""
    stripped = path.rstrip("\\/")
    if not stripped or re.fullmatch(r"[A-Za-z]:", stripped):
        return None
    return stripped


def _root_forms(path: str) -> list[str]:
    """Every textual form of ``path`` (SEC-F01-10 (b)), longest first."""
    back = path.replace("/", "\\")
    fwd = path.replace("\\", "/")
    doubled = back.replace("\\", "\\\\")
    forms = {back, fwd, doubled,
             "\\\\?\\" + back, "\\\\?\\" + fwd, "\\\\\\\\?\\\\" + doubled}
    return sorted(forms, key=lambda f: (-len(f), f))


class Redactor:
    """Replaces known roots, profile segments, and the home folder's name in text.

    Algorithm (§7.10.4): (1) one regex over every form of every root, longest root first,
    each replaced by its token; (2) the profile-segment rule; (3) the home-name rule.
    """

    def __init__(self, roots: Sequence[RedactRoot], *, home_name: str | None,
                 case_insensitive: bool) -> None:
        flags = re.IGNORECASE if case_insensitive else 0
        normalized: list[tuple[str, str]] = []
        for root in roots:
            path = _normalize_root(root.path)
            if path is not None:
                normalized.append((root.token, path))
        normalized.sort(key=lambda item: -len(item[1]))

        self._tokens: dict[str, str] = {}
        groups = []
        first_chars: set[str] = set()
        for index, (token, path) in enumerate(normalized):
            name = f"r{index}"
            self._tokens[name] = token
            forms = _root_forms(path)
            for form in forms:
                first_chars.update((form[0], form[0].lower(), form[0].upper())
                                   if case_insensitive else form[0])
            alternatives = "|".join(re.escape(form) for form in forms)
            groups.append(f"(?P<{name}>{alternatives})")
        # The leading lookahead on the possible first characters lets the regex engine
        # skip most positions without trying every alternative (about 20x faster on
        # long lines; the matches are the same).
        first = "(?=[" + "".join(re.escape(c) for c in sorted(first_chars)) + "])"
        self._roots_re = (re.compile(first + "(?:" + "|".join(groups) + ")" + _ROOT_END,
                                     flags)
                          if groups else None)

        self._home_re = None
        if home_name and home_name.casefold() not in _KEPT_SEGMENTS:
            self._home_re = re.compile(
                r"(?<=[\\/])" + re.escape(home_name) + r"(?=[\\/'\"\s]|$)",
                re.IGNORECASE | re.MULTILINE)

    def __call__(self, text: str) -> str:
        if not text:
            return text
        if self._roots_re is not None:
            text = self._roots_re.sub(lambda m: self._tokens[m.lastgroup], text)
        text = _PROFILE_RE.sub(_replace_profile_segment, text)
        if self._home_re is not None:
            text = self._home_re.sub("<user>", text)
        return text


def _replace_profile_segment(match: re.Match[str]) -> str:
    if match.group("seg").casefold() in _KEPT_SEGMENTS:
        return match.group(0)
    return match.group("head") + "<user>"


_installed: Redactor | None = None

# F30 (SEC-F30-04, 04 §6.3): the session's one extra term, the player's login name once
# ``app`` has read it. Whole-word and case-insensitive; replaced by ``<user>`` after the
# installed redactor, so it survives ``install()``. Memory only; set and cleared by ``app``.
_session_term: "re.Pattern[str] | None" = None


def install(redactor: Redactor) -> None:
    """Make ``redactor`` the one used by ``redact()`` and ``echo()``."""
    global _installed
    _installed = redactor


def set_session_term(term: str | None) -> None:
    """Also replace ``term`` (whole word, any case) with ``<user>`` in every ``redact()``
    from now on; None (or ``""``) clears it. F30's ``app`` sets the login name here when it
    is first read (names of at least 3 graphemes) and clears it on ``forget()``."""
    global _session_term
    _session_term = (re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
                     if term else None)


# F48 (SEC-F48-14, 07 I-3): API keys. ``KEY_SHAPE_RE`` is the one definition of an
# API-key-shaped text (PR-F48-32: ``sk-ant-…``, ``sk-proj-…``, or ``sk-`` and 20 key
# characters, from a word boundary), masked in every ``redact()`` and used by the build's
# key scan. Each key Studio loads is also registered in a named slot (``set_secret``) and
# replaced exactly, whatever its shape. Both become ``KEY_TOKEN``. Masking can only hide
# text, and these run off the frame path.
KEY_TOKEN = "<key>"
KEY_SHAPE_RE = re.compile(r"\bsk-(?:(?:ant|proj)-[A-Za-z0-9_-]+|[A-Za-z0-9_-]{20,})", re.ASCII)
SECRET_MIN_CHARS = 8                # SEC-F48-13 (a)'s shortest key

_secrets: dict[str, str] = {}       # slot → key; memory only
_secret_re: "re.Pattern[str] | None" = None


def set_secret(slot: str, value: str | None) -> None:
    """Replace ``value`` (exact, case-sensitive) with ``<key>`` in every ``redact()`` from now
    on, under the name ``slot`` (``anthropic``, ``openai``, ``compatible <origin>``); None
    or ``""`` clears that slot. Only ``tools.assistant`` calls this (a test checks), before
    the key's first use, keystore children included (05 §10). A value shorter than
    ``SECRET_MIN_CHARS`` raises ``ValueError``, so a stray short value can't blank common
    words."""
    global _secret_re
    if type(slot) is not str or not slot:
        raise ValueError("a secret slot is a non-empty str")
    if value is not None and type(value) is not str:
        raise ValueError("a secret is a str or None")
    if value:
        if len(value) < SECRET_MIN_CHARS:
            raise ValueError("a secret is at least 8 characters long")
        _secrets[slot] = value
    else:
        _secrets.pop(slot, None)
    values = sorted(set(_secrets.values()), key=lambda v: (-len(v), v))
    _secret_re = (re.compile("|".join(re.escape(v) for v in values)) if values else None)


def redact(text: str) -> str:
    """The registered secrets and key shapes (``<key>``); then the installed redactor (before
    install(), a redactor with no roots that still applies the profile-segment rule); then
    the session term, if one is set."""
    global _installed
    if _installed is None:
        _installed = Redactor((), home_name=None,
                              case_insensitive=sys.platform in ("win32", "darwin"))
    if text:
        secret = _secret_re             # one read: the log writer thread may call this
        if secret is not None:
            text = secret.sub(KEY_TOKEN, text)
        text = KEY_SHAPE_RE.sub(KEY_TOKEN, text)
    text = _installed(text)
    term = _session_term                # one read: the log writer thread may call this
    if term is not None and text:
        text = term.sub("<user>", text)
    return text


def _escape_table(allow_newline: bool) -> dict[int, str]:
    table = {cp: f"\\x{cp:02x}" for cp in range(0x20)}
    table[0x09] = "\\t"
    table[0x0A] = "\\n"
    table[0x0D] = "\\r"
    table[0x7F] = "\\x7f"
    table.update({cp: f"\\x{cp:02x}" for cp in range(0x80, 0xA0)})
    for cp in (0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)):
        table[cp] = f"\\u{cp:04x}"
    if allow_newline:
        del table[0x0A]
    return table


_ESCAPE = _escape_table(allow_newline=False)
_ESCAPE_KEEP_NEWLINE = _escape_table(allow_newline=True)


def escape_controls(text: str, *, allow_newline: bool = False) -> str:
    """Make control, line-separator, and bidi characters visible (§7.10.5).

    ``\\t``, ``\\n``, ``\\r`` become backslash + letter (``\\n`` stays a real newline if
    ``allow_newline``); other C0, U+007F, and C1 characters become ``\\xNN``; U+2028,
    U+2029, U+202A–U+202E, and U+2066–U+2069 become ``\\uNNNN``. Linear time, idempotent.
    """
    return text.translate(_ESCAPE_KEEP_NEWLINE if allow_newline else _ESCAPE)


def truncate(text: str, limit: int) -> str:
    """``text`` if it has at most ``limit`` characters, else its first ``limit - 1``
    characters followed by ``…``."""
    if len(text) <= limit:
        return text
    return text[:max(limit - 1, 0)] + "…"


def echo(text: str, limit: int = ECHO_MAX_CHARS) -> str:
    """truncate(escape_controls(redact(text)), limit). The one way content strings are
    embedded in messages, log lines, and labels. Redaction always runs before truncation."""
    return truncate(escape_controls(redact(text)), limit)
