"""F04's image-name rules (SR-F04-01): the name an ``images/…`` file gives, or why it gives
none (W10).

Lifted from ``runtime/images.py`` (F45 ``04`` Q5), so Studio (``tools/editor``, which may
import only ``core`` and ``script``) offers the same names and renames the launch check uses.
``runtime/images.py`` re-exports every name here as the same object. ``is_image_word`` is
``script/words.py``'s (F45 ``07`` I-6: one object, not two copies).
"""

from dataclasses import dataclass

from engine.core.constants import IMAGE_SUFFIXES, STAGE_WORDS, STATEMENT_WORDS
from engine.script.words import canonical_name, is_image_word, is_word_char

IMAGE_NAME_MAX_WORDS = 5             # SR-F04-01

# NameProblem reasons, in the order a segment is checked.
HYPHEN = "hyphen"                    # "(no - in names)"
SPACE = "space"                      # "(no spaces in names)"
DOT = "dot"                          # "(one dot only, before the extension)"
CHARACTERS = "characters"            # another character a word can't hold
STATEMENT_WORD = "statement_word"    # '("scene" is a statement word)' → my_scene
STAGE_WORD = "stage_word"            # '("zoom" is a word show uses)' → my_zoom
TOO_MANY_WORDS = "too_many_words"    # "move it so its name has at most 5 words."


@dataclass(frozen=True, slots=True)
class NameProblem:
    """One file under ``images/`` that gives no name (W10). ``word`` is the file or folder
    name that breaks a rule, as listed (a file's with its extension); ``rename`` is what
    to rename it to, or None (too many words, or nothing to suggest). ``folder`` is True
    when ``word`` is a folder of ``ref``."""
    ref: str
    reason: str
    word: str | None = None
    rename: str | None = None
    folder: bool = False


def image_suffix(file_name: str) -> str | None:
    """The image extension of a file name, lower-cased, or None if it isn't an image."""
    dot = file_name.rfind(".")
    if dot <= 0:
        return None
    suffix = file_name[dot:].lower()
    return suffix if suffix in IMAGE_SUFFIXES else None


def word_problem(word: str) -> tuple[str, str | None] | None:
    """Why ``word`` (a folder name or a file's stem, as listed) can't be a word of an image
    name, as ``(reason, renamed word)``, or None if it can. A word is an SR-F02-36 word after
    ``canonical_name``, and not a statement word or stage word in any case."""
    name = canonical_name(word)
    if name and all(is_word_char(c) for c in name):
        lowered = name.lower()
        if lowered in STATEMENT_WORDS:
            return STATEMENT_WORD, "my_" + word
        if lowered in STAGE_WORDS:
            return STAGE_WORD, "my_" + word
        return None
    fixed = "".join(c if is_word_char(c) else "_" for c in word)
    if "-" in word:
        reason = HYPHEN
    elif " " in word:
        reason = SPACE
    elif "." in word:
        reason = DOT
    else:
        reason = CHARACTERS
    fixed_name = canonical_name(fixed)
    ok = fixed_name and all(is_word_char(c) for c in fixed_name)
    return reason, fixed if ok else None


def name_of(ref: str) -> tuple[str | None, NameProblem | None]:
    """The image name an ``images/…`` file gives, or the problem that stops it. Not for
    files without an image extension (``image_suffix`` is None)."""
    parts = ref.split("/")[1:]                     # below images/
    file_name = parts[-1]
    suffix_at = file_name.rfind(".")
    words = [*parts[:-1], file_name[:suffix_at]]
    for index, word in enumerate(words):
        found = word_problem(word)
        if found is None:
            continue
        reason, rename = found
        folder = index < len(words) - 1
        if not folder:
            word = file_name
            if rename is not None:
                rename += file_name[suffix_at:]
        return None, NameProblem(ref, reason, word, rename, folder)
    if len(words) > IMAGE_NAME_MAX_WORDS:
        return None, NameProblem(ref, TOO_MANY_WORDS)
    return " ".join(canonical_name(w) for w in words), None


__all__ = ["CHARACTERS", "DOT", "HYPHEN", "IMAGE_NAME_MAX_WORDS", "NameProblem", "SPACE",
           "STAGE_WORD", "STATEMENT_WORD", "TOO_MANY_WORDS", "image_suffix", "is_image_word",
           "name_of", "word_problem"]
