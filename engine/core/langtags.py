"""Language codes: the code check, the built-in names, and the first-launch match (F43
``04`` §3, §7.3; PR-F43-01, 09, 21).

Why this module exists: the settings schema (``core``) checks the stored ``language``, render
and ``ui`` draw a language's own name, ``script`` filters ``translations/<code>.po`` names,
and Studio lists the built-in languages. One pure home in ``core`` serves all of them.

- A **language code** (PR-F43-01) is 2–3 lowercase ASCII letters, optionally ``-`` and 2–8
  ASCII letters or digits (``ja``, ``pt-BR``, ``zh-Hans``, ``es-419``), at most 12 characters.
- ``BUILTIN_LANGUAGES``: 40 rows (code, English name, own name, a font-test sample). Right-to-
  left and shaped scripts (Arabic, Hebrew, Hindi, Thai, ...) are left out: F43 doesn't draw
  them (W254), so Studio doesn't offer them. They still work as "Other code…".
- ``first_language`` (PR-F43-09): the language a first launch opens in, from the system's
  UI language tag (BCP 47 ``zh-Hant-TW`` or POSIX ``pt_BR.UTF-8``).

Standard library only; the table is a literal and nothing is built at import (F05 I-14).
"""

import re
from collections.abc import Sequence
from typing import Final, NamedTuple

MAX_CODE_LENGTH: Final = 12
MAX_SYSTEM_TAG_LENGTH: Final = 64        # longer system tags are ignored (never parsed)

_CODE: Final = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", re.ASCII)
_SUBTAG: Final = re.compile(r"[A-Za-z0-9]{1,8}", re.ASCII)
_PRIMARY: Final = re.compile(r"[A-Za-z]{2,3}", re.ASCII)

# Chinese: the script a region writes in (PR-F43-09: zh-CN → zh-Hans, zh-TW → zh-Hant).
_HANS_REGIONS: Final = frozenset(("cn", "sg", "my"))
_HANT_REGIONS: Final = frozenset(("tw", "hk", "mo"))

FIRST_SYSTEM: Final = "system"
FIRST_SOURCE: Final = "source"
FIRST_ASK: Final = "ask"


class BuiltinLanguage(NamedTuple):
    """One built-in row: ``sample`` is short text with the language's letters, which a
    font must cover to draw the language (Studio's Add language notice, PR-F43-21)."""

    code: str
    english: str
    own: str
    sample: str


BUILTIN_LANGUAGES: Final[tuple[BuiltinLanguage, ...]] = (
    BuiltinLanguage("en", "English", "English", "English"),
    BuiltinLanguage("ja", "Japanese", "日本語", "日本語のテキスト、カタカナ。"),
    BuiltinLanguage("zh-Hans", "Chinese (Simplified)", "简体中文", "简体中文，这是一个说话。"),
    BuiltinLanguage("zh-Hant", "Chinese (Traditional)", "繁體中文", "繁體中文，這是一個說話。"),
    BuiltinLanguage("ko", "Korean", "한국어", "한국어 텍스트입니다."),
    BuiltinLanguage("es", "Spanish", "Español", "Español ¿áéíñóúü?"),
    BuiltinLanguage("es-419", "Spanish (Latin America)", "Español (Latinoamérica)",
                    "Español ¿áéíñóúü?"),
    BuiltinLanguage("pt", "Portuguese", "Português", "Português ãçõáâêó"),
    BuiltinLanguage("pt-BR", "Portuguese (Brazil)", "Português (Brasil)",
                    "Português ãçõáâêó"),
    BuiltinLanguage("fr", "French", "Français", "Français àâçéèêëîïôœùûüÿ"),
    BuiltinLanguage("de", "German", "Deutsch", "Deutsch äöüß ÄÖÜ"),
    BuiltinLanguage("it", "Italian", "Italiano", "Italiano àèéìòù"),
    BuiltinLanguage("nl", "Dutch", "Nederlands", "Nederlands ëïé"),
    BuiltinLanguage("ru", "Russian", "Русский", "Русский язык ёйщъ"),
    BuiltinLanguage("uk", "Ukrainian", "Українська", "Українська мова їєґі"),
    BuiltinLanguage("pl", "Polish", "Polski", "Polski ąćęłńóśźż"),
    BuiltinLanguage("cs", "Czech", "Čeština", "Čeština áčďéěíňřšťůýž"),
    BuiltinLanguage("sk", "Slovak", "Slovenčina", "Slovenčina äčďĺľňôŕšťž"),
    BuiltinLanguage("hu", "Hungarian", "Magyar", "Magyar áéíóöőúüű"),
    BuiltinLanguage("ro", "Romanian", "Română", "Română ăâîșț"),
    BuiltinLanguage("bg", "Bulgarian", "Български", "Български език щъю"),
    BuiltinLanguage("sr", "Serbian", "Српски", "Српски језик ђћџљњ"),
    BuiltinLanguage("hr", "Croatian", "Hrvatski", "Hrvatski čćđšž"),
    BuiltinLanguage("sl", "Slovenian", "Slovenščina", "Slovenščina čšž"),
    BuiltinLanguage("el", "Greek", "Ελληνικά", "Ελληνικά άέήίόύώ"),
    BuiltinLanguage("tr", "Turkish", "Türkçe", "Türkçe çğıöşüİ"),
    BuiltinLanguage("sv", "Swedish", "Svenska", "Svenska åäö"),
    BuiltinLanguage("da", "Danish", "Dansk", "Dansk æøå"),
    BuiltinLanguage("nb", "Norwegian Bokmål", "Norsk bokmål", "Norsk bokmål æøå"),
    BuiltinLanguage("fi", "Finnish", "Suomi", "Suomi äöå"),
    BuiltinLanguage("et", "Estonian", "Eesti", "Eesti õäöü"),
    BuiltinLanguage("lv", "Latvian", "Latviešu", "Latviešu āčēģīķļņšūž"),
    BuiltinLanguage("lt", "Lithuanian", "Lietuvių", "Lietuvių ąčęėįšųūž"),
    BuiltinLanguage("ca", "Catalan", "Català", "Català àçèéíïòóúü"),
    BuiltinLanguage("eu", "Basque", "Euskara", "Euskara ñ"),
    BuiltinLanguage("gl", "Galician", "Galego", "Galego áéíñóú"),
    BuiltinLanguage("vi", "Vietnamese", "Tiếng Việt", "Tiếng Việt ăâđêôơưạảấầẩẫậ"),
    BuiltinLanguage("id", "Indonesian", "Bahasa Indonesia", "Bahasa Indonesia"),
    BuiltinLanguage("ms", "Malay", "Bahasa Melayu", "Bahasa Melayu"),
    BuiltinLanguage("fil", "Filipino", "Filipino", "Filipino ñ"),
)


def is_language_code(text: object) -> bool:
    """Whether ``text`` is a language code (PR-F43-01): a ``str``, ASCII, ≤ 12 characters,
    ``[a-z]{2,3}`` optionally followed by ``-`` and 2–8 letters or digits. Case matters in
    the first part only (``pt-BR`` and ``pt-br`` are both codes; ``PT`` isn't)."""
    return (isinstance(text, str) and len(text) <= MAX_CODE_LENGTH
            and _CODE.fullmatch(text) is not None)


def builtin(code: str) -> BuiltinLanguage | None:
    """The built-in row for ``code`` (exact spelling first, then ignoring case), or None."""
    folded = None
    for row in BUILTIN_LANGUAGES:
        if row.code == code:
            return row
        if folded is None and row.code.lower() == code.lower():
            folded = row
    return folded


def own_name(code: str) -> str:
    """The language's name in itself (``ja`` → 日本語); the code itself when it isn't
    built in (§5.3 ``name``'s default)."""
    row = builtin(code)
    return row.own if row is not None else code


def english_name(code: str) -> str:
    """The language's English name (``ja`` → Japanese); the code itself when it isn't
    built in."""
    row = builtin(code)
    return row.english if row is not None else code


def system_subtags(tag: str | None) -> tuple[str, ...] | None:
    """A system UI language tag as lowercase subtags (``pt_BR.UTF-8`` → ``("pt", "br")``,
    ``zh-Hant-TW`` → ``("zh", "hant", "tw")``), or None when it isn't a language tag
    (``C``, ``POSIX``, empty, too long, non-ASCII). POSIX ``.charset`` and ``@modifier``
    parts are dropped; ``_`` reads as ``-``."""
    if not isinstance(tag, str) or not tag or len(tag) > MAX_SYSTEM_TAG_LENGTH:
        return None
    text = tag.split(".", 1)[0].split("@", 1)[0].replace("_", "-")
    parts = text.split("-")
    if not _PRIMARY.fullmatch(parts[0]) or not all(_SUBTAG.fullmatch(p) for p in parts[1:]):
        return None
    lowered = tuple(part.lower() for part in parts)
    if lowered[0] in ("c", "posix"):
        return None
    return lowered


def first_language(system_tag: str | None, shown: Sequence[str],
                   mode: str = FIRST_SYSTEM) -> str | None:
    """The language a first launch opens in (PR-F43-09): one of ``shown`` (the translated
    languages a player may pick, the original left out) as spelled there, or None for the
    original. Only ``mode == "system"`` matches; ``"source"`` and ``"ask"`` open in the
    original (``ask`` then shows the pick screen).

    The match, ignoring case, first hit wins:

    1. the exact tag (``pt-BR``, ``zh-Hant``);
    2. Chinese by script: a ``Hans``/``Hant`` subtag, else the region (``CN``, ``SG``,
       ``MY`` → ``zh-Hans``; ``TW``, ``HK``, ``MO`` → ``zh-Hant``);
    3. the language with one of its subtags (``sr-Latn-RS`` → ``sr-Latn``, then ``sr-RS``);
    4. the language alone (``pt-PT`` → ``pt``);
    5. another variety of the language in ``shown`` order (``pt-PT`` → ``pt-BR``), except
       Chinese, whose varieties are written differently;
    6. else None (the original).
    """
    if mode != FIRST_SYSTEM:
        return None
    subtags = system_subtags(system_tag)
    if subtags is None:
        return None
    by_folded: dict[str, str] = {}
    for code in shown:
        if is_language_code(code):
            by_folded.setdefault(code.lower(), code)
    primary, rest = subtags[0], subtags[1:]
    candidates = ["-".join(subtags)]
    if primary == "zh":
        script = _chinese_script(rest)
        if script is not None:
            candidates.append(script)
    candidates.extend(f"{primary}-{part}" for part in rest)
    candidates.append(primary)
    for candidate in candidates:
        if candidate in by_folded:
            return by_folded[candidate]
    if primary != "zh":
        for folded, code in by_folded.items():
            if folded.split("-", 1)[0] == primary:
                return code
    return None


def _chinese_script(subtags: Sequence[str]) -> str | None:
    """``zh-hans`` or ``zh-hant`` for a Chinese tag's other subtags: a script subtag wins
    over the region."""
    if "hans" in subtags:
        return "zh-hans"
    if "hant" in subtags:
        return "zh-hant"
    if any(part in _HANS_REGIONS for part in subtags):
        return "zh-hans"
    if any(part in _HANT_REGIONS for part in subtags):
        return "zh-hant"
    return None
