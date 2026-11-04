"""The on-screen keyboard's pages (F52 ``01`` §6.5, ``04`` §3 and §4.4, P2).

Why this module exists: a gamepad player types with the keyboard panel, whose keys must be
the characters the field accepts, in the game's language, and only ones a font of the game
can draw (PR-F52-16). The page tables are engine data (the user's decision 9: no config
key); this module picks and filters them, with no pygame:

- ``pages_for(language, allowed, case, can_draw)``: the current language's pages first
  (Cyrillic, Greek or kana), then ABC, abc and 123; a Latin-script language (any other)
  gets ÀÉ and àé after 123. An explicit ``allowed`` string makes its own pages instead, 40
  keys each, labelled by their first three characters. Keys are filtered by ``allowed``
  (after case folding) and by ``can_draw``; with ``case`` set, the other case's pages go;
  empty pages are dropped.
- ``undrawable(...)``: the keys ``can_draw`` refused, for W267 (dev runs).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from engine.ui.textedit import Allowed, fold

PAGE_KEYS: Final = 40                         # 10 × 4 grid
_PUNCT: Final = ".,'-"
_MARKS: Final = "!\"#$%&'()*+,-./:;<=>?@[\\]_{|}~"     # the 30 ASCII marks besides ^ and `

CYRILLIC_LANGUAGES: Final = frozenset({"ru", "uk", "be", "bg", "sr", "mk", "kk", "ky", "mn",
                                       "tg"})
GREEK_LANGUAGES: Final = frozenset({"el"})
KANA_LANGUAGES: Final = frozenset({"ja"})


def _span(first: str, last: str, skip: str = "") -> str:
    return "".join(chr(c) for c in range(ord(first), ord(last) + 1) if chr(c) not in skip)


_HIRAGANA: Final = (
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
    "がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ"
    "ぁぃぅぇぉっゃゅょゎー")
_KATAKANA: Final = "".join(chr(ord(c) + 0x60) if c != "ー" else c for c in _HIRAGANA)


@dataclass(frozen=True)
class Page:
    """One keyboard page: its page-row label and up to 40 keys."""
    label: str
    keys: tuple[str, ...]


def _numbered(label: str, chars: str) -> list[tuple[str, str]]:
    chunks = [chars[i:i + PAGE_KEYS] for i in range(0, len(chars), PAGE_KEYS)]
    return [(f"{label}{n}", chunk) for n, chunk in enumerate(chunks, start=1)]


# (label, characters, case): case "upper"/"lower" pages go when the field folds to the other.
BASE_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("ABC", _span("A", "Z") + _PUNCT, "upper"),
    ("abc", _span("a", "z") + _PUNCT, "lower"),
    ("123", _span("0", "9") + _MARKS, None),
)
LATIN_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("ÀÉ", _span("À", "Þ", "×") + "ŒŸ", "upper"),
    ("àé", _span("à", "þ", "÷") + "ßœÿ", "lower"),
)
CYRILLIC_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("АБВ", _span("А", "Я") + "Ё", "upper"),
    ("абв", _span("а", "я") + "ё", "lower"),
)
GREEK_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("ΑΒΓ", _span("Α", "Ω", "΢"), "upper"),
    ("αβγ", _span("α", "ω"), "lower"),
)
KANA_PAGES: Final[tuple[tuple[str, str, str | None], ...]] = (
    *((label, chars, None) for label, chars in _numbered("あ", _HIRAGANA)),
    *((label, chars, None) for label, chars in _numbered("ア", _KATAKANA)),
)


def language_pages(language: str) -> tuple[tuple[str, str, str | None], ...]:
    """The page table for ``language`` (a code like ``"ja"`` or ``"pt-BR"``), in order."""
    base = (language or "en").split("-")[0].lower()
    if base in CYRILLIC_LANGUAGES:
        return (*CYRILLIC_PAGES, *BASE_PAGES)
    if base in GREEK_LANGUAGES:
        return (*GREEK_PAGES, *BASE_PAGES)
    if base in KANA_LANGUAGES:
        return (*KANA_PAGES, *BASE_PAGES)
    return (*BASE_PAGES, *LATIN_PAGES)


def _keep(chars: Sequence[str], allowed: Allowed, case: str | None) -> list[str]:
    keys: list[str] = []
    for ch in chars:
        if fold(ch, case) != ch:             # the field would type another character
            continue
        if allowed.accepts(ch) and ch not in keys:
            keys.append(ch)
    return keys


def _candidates(language: str, allowed: Allowed,
                case: str | None) -> list[tuple[str, list[str]]]:
    """(label, keys) before the font filter."""
    if allowed.explicit:
        chars = [c for c in (allowed.chars or ()) if c != " "]
        out = []
        for i in range(0, len(chars), PAGE_KEYS):
            chunk = chars[i:i + PAGE_KEYS]
            out.append(("".join(chunk[:3]), chunk))
        return out
    out = []
    for label, chars, page_case in language_pages(language):
        if case is not None and page_case is not None and page_case != case:
            continue
        out.append((label, _keep(list(chars), allowed, case)))
    return out


def pages_for(language: str, allowed: "Allowed | str", case: str | None,
              can_draw: Callable[[str], bool]) -> list[Page]:
    """The keyboard's pages (module docstring); never a page with no keys."""
    allowed = allowed if isinstance(allowed, Allowed) else Allowed(allowed)
    pages = []
    for label, keys in _candidates(language, allowed, case):
        shown = tuple(k for k in keys if can_draw(k))
        if shown:
            pages.append(Page(label, shown))
    return pages


def undrawable(language: str, allowed: "Allowed | str", case: str | None,
               can_draw: Callable[[str], bool]) -> list[str]:
    """The keys the keyboard leaves out because ``can_draw`` refused them, in page order."""
    allowed = allowed if isinstance(allowed, Allowed) else Allowed(allowed)
    missing: list[str] = []
    for _label, keys in _candidates(language, allowed, case):
        for k in keys:
            if k not in missing and not can_draw(k):
                missing.append(k)
    return missing


_LISTED: Final = 10


def w267_text(chars: Sequence[str]) -> str:
    """W267 (dev): the allowed characters no font of the game draws."""
    count = len(chars)
    shown = ", ".join(chars[:_LISTED]) + (", …" if count > _LISTED else "")
    noun = "character" if count == 1 else "characters"
    pronoun = "it" if count == 1 else "them"
    return (f"this text field allows {count} {noun} no font of the game can draw ({shown}), "
            f"so the on-screen keyboard leaves {pronoun} out. Add a font that has {pronoun} "
            "to [theme] ui.text_font, or allow other characters.")


__all__ = ["BASE_PAGES", "CYRILLIC_LANGUAGES", "PAGE_KEYS", "Page", "language_pages",
           "pages_for", "undrawable", "w267_text"]
