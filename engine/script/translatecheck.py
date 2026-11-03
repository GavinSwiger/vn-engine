"""Checking one translation as its kind (F43 PR-F43-04, PR-F43-05, PR-F43-15; ``04-technical.md``
§3, §7.1).

Why this module exists: the game checks each entry on its first lookup, dev runs, ``check``
and build sweep every entry, and Studio's Translate tab checks as you type; all of them must
refuse the same translations with the same words, so one pure function decides. Studio
imports it, so it is standard library plus ``core`` and ``script`` only.

``check_entry(kind, original, translation, key=, limit=, line=)`` returns an ``EntryCheck``:
``use`` (show the translation) and its ``problems`` (``po.PoProblem``, at ``line``):

- **Length** (W248 ``long``, the kind's cap): a translation longer than ``limit`` code points
  (``SourceText.limit``) is skipped.
- **Tags** (W249, carrying the F05/F29/F07 message for the same mistake in a script line,
  from the engine's own parser ``texttags.parse``): lines and questions by F05/F29 tag rules;
  choices also by F07's (``choice=True``, E175); codex paragraphs (``tip:<n>:<k>``,
  ``item:<n>:<k>``) by F19's (E252's ``tag`` form). Plain kinds show their text as written,
  so a text tag in them would show its braces: titles (each key family's own ``tags``
  message: E222, E242, E252, E263, E336, E339, E344, E350; ``{username}`` on a chapter or
  ending card is E302's), names (E302, E169, as ``Character`` refuses them) and
  ``effect window_title`` (E300). Words, values and the game's texts are shown as written
  with no load rule to mirror, so they get only the length check.
- **Variables** (lines, questions, choices): ``{var=…}`` and ``{username}``/``{username=…}``
  names the translation uses and the original doesn't are W250 (refused: the original
  shows). Names the original has and the translation leaves out are W251, a note: the
  translation is used.

An empty translation is New: not used, no problem. The first refusal wins; W251 comes only
with a used translation. ``kind`` is a ``translatekeys.TextKind`` or its value (``"line"``).

``has_rtl``/``rtl_warning`` find right-to-left or joined letters (W254, once per file);
``missing_chars`` lists the characters a font chain can't draw (W252).
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from engine.core.graphemes import iter_graphemes
from engine.script.codex import _bad_tag
from engine.script.messages import TAG_NAMES, format_message
from engine.script.po import PoProblem
from engine.script.texttags import NameMark, TaggedText, TagProblem, VarMark, has_username_tag
from engine.script.texttags import parse as parse_tags

USERNAME: Final = "username"            # W250/W251's name for {username} (the fallback word)
TAGGED_KINDS: Final = frozenset(("line", "question", "choice"))

# Title key families → the code and args of their load-time "tags" message.
_TITLE_TAGS: Final[dict[str, tuple[str, tuple]]] = {
    "chapter": ("E222", ("tags",)),
    "ending": ("E242", ("tags", "ending")),
    "route": ("E242", ("tags", "route")),
    "tip": ("E252", ("tags", "tip")),
    "item": ("E252", ("tags", "item")),
    "codex": ("E252", ("tags", "tip")),
    "gallery": ("E344", ("tags",)),
    "track": ("E336", ("tags",)),
    "replay": ("E350", ("tags",)),
    "achievement": ("E339", ("tags",)),
    "flowchart": ("E263", ("tags",)),
}
_CARDS: Final = frozenset(("chapter", "ending"))
_CODEX: Final = frozenset(("tip", "item"))
# A text tag as F05 reads one: a known name (or its closing form), with or without a value.
_TAG_RE = re.compile(r"\{/?(?:%s)(?:=[^{}]*)?\}" % "|".join(map(re.escape, TAG_NAMES)))


@dataclass(frozen=True, slots=True)
class EntryCheck:
    """``use``: show the translation (else the original). ``problems``: the refusal
    (W248/W249/W250) or W251's note."""

    use: bool
    problems: tuple[PoProblem, ...] = ()


_UNUSED: Final = EntryCheck(False)
_USED: Final = EntryCheck(True)


def _kind_name(kind: object) -> str:
    return str(getattr(kind, "value", kind))


def _parse(text: str, *, choice: bool = False) -> tuple[TaggedText | None, TagProblem | None]:
    found: list[TagProblem] = []
    body = parse_tags(text, lambda offset: (1, offset + 1), found.append, choice=choice)
    return body, (found[0] if found else None)


def _names(body: TaggedText | None) -> list[str]:
    """The variable names a body shows, in text order, once each."""
    out: list[str] = []
    if body is None:
        return out
    for piece in body.pieces:
        if isinstance(piece, VarMark):
            name = piece.name
        elif isinstance(piece, NameMark):
            name = piece.var if piece.var is not None else USERNAME
        else:
            continue
        if name not in out:
            out.append(name)
    return out


def _listed(names: list[str]) -> str | tuple[str, ...]:
    return names[0] if len(names) == 1 else tuple(names)


def _family(key: str) -> tuple[str, str]:
    """A prefixed key's family and its last part (``tip:lanterns:2`` → ``tip``, ``2``)."""
    head, colon, rest = key.partition(":")
    return (head, rest.rpartition(":")[2]) if colon else ("", "")


def _tag_message(kind: str, key: str, translation: str) -> str | None:
    """The load-time message for a tag mistake in ``translation``, or None."""
    if kind in TAGGED_KINDS:
        _, problem = _parse(translation, choice=kind == "choice")
        return problem.message() if problem is not None else None
    if kind == "title":
        family, last = _family(key)
        if family in _CODEX and last.isdigit():             # a codex paragraph (F19)
            body, problem = _parse(translation)
            if problem is not None:
                return problem.message()
            bad = _bad_tag(body) if body is not None else None
            return format_message("E252", ("tag", bad, family)) if bad is not None else None
        if _TAG_RE.search(translation) is None:
            return None
        if family in _CARDS and has_username_tag(translation):
            return format_message("E302", ("title_card",))
        code, args = _TITLE_TAGS.get(family, _TITLE_TAGS["chapter"])
        return format_message(code, args)
    if kind == "name":
        if "{username" in translation:
            return format_message("E302", ("name",))
        if "{" in translation or "}" in translation:
            return format_message("E169", (translation,))
        return None
    if kind == "effect":
        return format_message("E300", ("tags",)) if _TAG_RE.search(translation) else None
    return None


def check_entry(kind: object, original: str, translation: str, *, key: str = "",
                limit: int | None = None, line: int | None = None) -> EntryCheck:
    """Whether ``translation`` of ``original`` can be shown, as ``kind`` (module
    docstring). Never raises for any text."""
    if not translation:
        return _UNUSED
    kind = _kind_name(kind)
    if limit is not None and len(translation) > limit:
        return EntryCheck(False, (PoProblem("W248", ("long", int(limit)), line),))
    message = _tag_message(kind, key, translation)
    if message is not None:
        return EntryCheck(False, (PoProblem("W249", (message,), line),))
    if kind not in TAGGED_KINDS:
        return _USED
    choice = kind == "choice"
    used = _names(_parse(translation, choice=choice)[0])
    if not used and "{" not in original:
        return _USED
    shown = _names(_parse(original, choice=choice)[0])
    extra = [name for name in used if name not in shown]
    if extra:
        return EntryCheck(False, (PoProblem("W250", (_listed(extra),), line),))
    missing = [name for name in shown if name not in used]
    if missing:
        return EntryCheck(True, (PoProblem("W251", (_listed(missing),), line),))
    return _USED


def shown_text(translation: str) -> str:
    """``translation`` without its text tags (``{{`` is a brace): the characters a font
    must draw (W252)."""
    out: list[str] = []
    start = 0
    while (at := translation.find("{", start)) >= 0:
        out.append(translation[start:at])
        if translation.startswith("{{", at):
            out.append("{")
            start = at + 2
            continue
        close = translation.find("}", at + 1)
        if close < 0:
            start = at
            break
        start = close + 1
    out.append(translation[start:])
    return "".join(out)


# --- Right-to-left and joined letters (W254) ---------------------------------------------

_RTL_RE = re.compile(
    "["
    "\u0590-\u08ff"         # Hebrew, Arabic, Syriac, Thaana, NKo, Samaritan, Mandaic, ...
    "\u0900-\u0dff"         # Devanagari ... Sinhala (joined Indic scripts)
    "\u0e00-\u0fff"         # Thai, Lao, Tibetan
    "\u1000-\u109f"         # Myanmar
    "\u1780-\u18af"         # Khmer, Mongolian
    "\ua8e0-\ua8ff"         # Devanagari Extended
    "\ufb1d-\ufdff"         # Hebrew and Arabic presentation forms A
    "\ufe70-\ufefe"         # Arabic presentation forms B (not U+FEFF)
    "\U00010800-\U00010fff"  # historic right-to-left scripts, Hanifi Rohingya, Yezidi, ...
    "\U0001e800-\U0001efff"  # Mende Kikakui, Adlam, Arabic mathematical letters
    "]")


def has_rtl(text: str) -> bool:
    """Whether ``text`` holds right-to-left or joined-script letters (Arabic, Hebrew,
    Devanagari, Thai, ...), which the engine can't draw correctly yet (PR-F43-15)."""
    return _RTL_RE.search(text) is not None


def rtl_warning(file: str, translations: Iterable[str]) -> PoProblem | None:
    """W254 for ``translations/<file>`` once, when any translation has such letters."""
    for text in translations:
        if text and _RTL_RE.search(text) is not None:
            return PoProblem("W254", (file,), None)
    return None


# --- Characters no font draws (W252) -----------------------------------------------------

def missing_chars(texts: Iterable[str], covers: Callable[[str], bool],
                  *, keep: int = 3) -> tuple[int, tuple[str, ...]]:
    """The distinct characters (graphemes; spaces and controls aside) of ``texts`` that
    ``covers(grapheme)`` refuses: their count and the first ``keep`` in text order. Tags
    are removed first (``shown_text``)."""
    seen: set[str] = set()
    first: list[str] = []
    count = 0
    for text in texts:
        for grapheme in iter_graphemes(shown_text(text)):
            if grapheme in seen or grapheme.isspace() or (len(grapheme) == 1
                                                                  and not grapheme.isprintable()):
                continue
            seen.add(grapheme)
            if not covers(grapheme):
                count += 1
                if len(first) < keep:
                    first.append(grapheme)
    return count, tuple(first)


__all__ = ["EntryCheck", "TAGGED_KINDS", "USERNAME", "check_entry", "has_rtl",
           "missing_chars", "rtl_warning", "shown_text"]
