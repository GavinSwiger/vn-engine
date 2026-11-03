"""Reserved words, engine names, and the name rules of the script language.

``STATEMENT_WORDS`` is the set of reserved statement words: the 37 of SR-F02-38 (PR-F02-26,
27; ``STATEMENT_WORDS_F02``; 38 until F34 freed ``cg``), F14's ``rollback``, F20's ``flowchart``, and F32's ``ui``. A line that starts with one is that
statement, never dialogue, and no name may be one of them in any case. ``check_name`` gives the E60–E64 verdict for a name an author defines (SR-F02-34–36);
``canonical_name`` is the NFKC form names are compared and stored in (§7.3.3). F04 adds
``SHOW_MODIFIER_WORDS`` and ``is_image_word`` (the words of image names and sprite tags).
"""

import keyword
import sys
import unicodedata

# SR-F02-38 and F04's stage words live in core (config validation needs them, F04 §17
# item 2); re-exported here as the same objects.
from engine.core.constants import STAGE_WORDS, STATEMENT_WORDS, STATEMENT_WORDS_F02

# Words that only follow a statement; at line start they give E32b (SR-F02-38). F09's
# ``with`` gives E32b too (it is a ``SHOW_MODIFIER_WORDS`` word; parser.py).
MODIFIER_WORDS: frozenset[str] = frozenset(("at", "as", "behind"))

# F04's modifier words (F04 02-script.md §2): the reserved ``at as behind with`` and the stage
# words. They end an image name on a ``show`` line and give E119 on a dialogue line. Not named
# ``MODIFIER_WORDS`` (F04 07 I-4): the stage words stay valid speaker and define names, so
# ``layer "Hi"`` is dialogue, not E32b.
SHOW_MODIFIER_WORDS: frozenset[str] = frozenset(("at", "as", "behind", "with")) | STAGE_WORDS

# Names the engine keeps for itself (SR-F02-35, E62). F09 (SR-F09-09, C10): the transition
# constructors ``Dissolve``, ``Fade``, ``Mask`` (bound in G), and ``Transition``, reserved
# and unbound (F28). F22 (SR-F22-05): ``points``, the meters' read-only view. F21 (07 I-5):
# ``codex``, the tips' and items' read-only view (bound from F21 step 2). A saved state
# never refuses a name added here later: ``from_json`` checks only F03's six (``state.py``),
# and restore drops a saved name that is reserved now (``state.reserved_since_save``).
ENGINE_NAMES: frozenset[str] = frozenset(  # dice, module: F03 (SR-F03-08)
    ("Character", "dice", "module", "persistent", "engine", "narrator",
     "Dissolve", "Fade", "Mask", "Transition", "points", "codex"))

PYTHON_KEYWORDS: frozenset[str] = frozenset(keyword.kwlist)

# E60's role words (04-technical.md §6.1).
ROLE_LABEL = "a label name"
ROLE_CHARACTER = "a character name"
ROLE_NAME = "a name"
ROLE_VARIABLE = "a variable name"                 # F03 default (F03 02-script.md SR-F03-02)
ROLE_METER = "a meter name"                       # F22 points (SPEC SR-F22-01)


def canonical_name(word: str) -> str:
    """The form a name is compared and stored in: the word itself if ASCII, else its NFKC
    normalization (SR-F02-34). Interned, because names are dictionary keys everywhere."""
    if not word.isascii():
        word = unicodedata.normalize("NFKC", word)
    return sys.intern(word)


def is_name(word: str) -> bool:
    """True if ``word`` is a Python identifier after NFKC (SR-F02-34)."""
    return canonical_name(word).isidentifier()


def is_word_char(char: str) -> bool:
    """A character that can be part of a word: ``("a" + c).isidentifier()`` (§7.3.3)."""
    if char.isascii():
        return char.isalnum() or char == "_"
    return ("a" + char).isidentifier()


def is_image_word(word: str, reserved: frozenset[str] = STATEMENT_WORDS) -> bool:
    """True if ``word`` can be one word of an image name or a sprite tag (F04 SR-F04-01): an
    SR-F02-36 word after ``canonical_name``, and not a statement word or stage word in any
    case. Saved data passes ``STATEMENT_WORDS_F02`` as ``reserved`` (F14 07 I-1)."""
    name = canonical_name(word)
    if not name or not all(is_word_char(c) for c in name):
        return False
    lowered = name.lower()
    return lowered not in reserved and lowered not in STAGE_WORDS


def check_name(written: str, role: str = ROLE_NAME) -> tuple[str, tuple] | None:
    """The E60–E64 problem with a name an author defines, as ``(code, args)``, or None.

    ``written`` is the name as written; checks run on its canonical form. The args are what
    ``messages.py`` needs: E60 ``(name, role)``, E61–E63 ``(name,)``, E64 ``(name,)``.
    """
    name = canonical_name(written)
    if not name.isidentifier():
        return "E64", (written,)
    if name.lower() in STATEMENT_WORDS:
        return "E60", (written, role)
    if name in PYTHON_KEYWORDS:
        return "E61", (written,)
    if name in ENGINE_NAMES:
        return "E62", (written,)
    if name.startswith("_"):
        return "E63", (written,)
    return None


__all__ = ["ENGINE_NAMES", "MODIFIER_WORDS", "PYTHON_KEYWORDS", "ROLE_CHARACTER", "ROLE_LABEL",
           "ROLE_METER", "ROLE_NAME", "ROLE_VARIABLE", "SHOW_MODIFIER_WORDS", "STAGE_WORDS",
           "STATEMENT_WORDS", "STATEMENT_WORDS_F02", "canonical_name", "check_name", "is_image_word", "is_name", "is_word_char"]
