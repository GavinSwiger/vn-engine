"""Studio's writing help: completion, Insert, and Help (F45 ``04-technical.md`` §5, §7.6;
PR-F45-13..16, UI-F45-04, UI-F45-05).

Pure Python, no Tk: the window asks these functions what to show and applies the answer.
Everything comes from the statement doc registry (``script.statement_docs``) and the check
child's name index, so nothing about a statement is hand-listed here (PR-F45-17).

- **Completion.** ``completion_context(line, column)`` reads the text before the cursor and
  says which name kinds may go there, what has been typed (``prefix``), and the column an
  accepted name replaces from (``start``). ``candidates(ctx, names)`` filters the name index
  (``kind → entries``, the ``names`` events of the last good check; an entry is a
  ``NameEntry``, a ``(name, file, line)`` row, or a plain string) and ranks exact-case prefix
  matches before case-insensitive ones, at most ``COMPLETION_MAX``. ``accept`` gives the line
  after picking one. ``auto_open`` is PR-F45-14's "open after the space" rule.
- **Insert.** ``insert_menu()`` lists the menu's groups and entries; ``insert_text`` gives
  the indented example and the range of its first field to select.
- **Help.** ``help_for(line)`` picks the doc for a line; ``help_sections(doc)`` is what the
  Help pane shows, the Docs line left out while a word's docs step is pending (``07`` I-4).
- **Codex names** (2026-11-02, AC-F45-67..69). ``lock tip|item … image <words>`` offers
  picture names; in a Python line (``$``, ``if``, ``elif``, a choice's ``if``) a string
  offers tip and item names (only one kind before ``in codex.tips``/``codex.items``), and
  ``codex.`` offers ``tips`` and ``items``.
- **Verbs and quoted names** (F31 s5, AC-F45-72). After a ``VERB_STATEMENTS`` word (``file``)
  completion offers the second words its docs' syntaxes start with (``write``, ``delete``,
  ``exists``, ``read``); a ``QUOTED_KINDS`` kind (``audio``, ``meta_file``) is offered only
  inside quotes, every other kind only outside them.
- **Text tags** (2026-11-02, AC-F45-56..59). Inside a dialogue or narration string, after
  ``{`` completion offers the tag names and after ``{/`` the innermost open style tag;
  ``tag_help(line, column)`` is the row of the tag the cursor is inside. All of it reads
  ``script.tag_docs``, so a new tag is one row there.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from engine.script.statement_docs import (
    DOC_FORMS, DOC_MODIFIERS, GROUPS, StatementDoc, all_docs, docs_for)
from engine.script.tag_docs import TagDoc, tag_doc, tag_names
from engine.script.words import is_word_char

STATEMENT_KIND: Final = "statement"      # a statement word, from the registry
CHARACTER_KIND: Final = "character"      # a character name (a dialogue line's speaker)
IMAGE_KIND: Final = "image"              # several words: the prefix spans them all
AUDIO_KIND: Final = "audio"              # a file name, offered only inside quotes
META_FILE_KIND: Final = "meta_file"      # F31: a meta file name, offered only inside quotes
QUOTED_KINDS: Final = (AUDIO_KIND, META_FILE_KIND)   # kinds written in quotes
VERB_KIND: Final = "verb"                # the word after a VERB_STATEMENTS word
# Statements whose second word is one of a fixed list, read from their docs' syntaxes.
VERB_STATEMENTS: Final = frozenset(("file",))
COMPLETION_MAX: Final = 200              # rows a list holds (04 §7.6)
COMPLETION_VISIBLE: Final = 10           # rows shown at once (design §6.1)
PREFIX_MAX: Final = 1_024                # a longer typed run completes nothing (huge lines)
NO_HELP: Final = "No help for this line."
EXAMPLE_INDENT: Final = "    "           # the nesting step of every StatementDoc.example
MINIGAME_WORD: Final = "minigame"
MINIGAME_ARG_KIND: Final = "minigame_arg"  # check child rows "<minigame>.<arg>" (F23)
TAG_KIND: Final = "tag"                  # a text tag name, after "{" in a text string
CLOSE_TAG_KIND: Final = "close tag"      # the innermost open style tag, after "{/"
TEXT_KEYS: Final = ("dialogue", "narration")   # the doc keys whose strings hold text tags
CODEX_FIELD_KIND: Final = "codex"        # ``tips``/``items`` after ``codex.`` in Python
CODEX_FIELDS: Final = ("tips", "items")
PYTHON_KEYS: Final = ("$", "if", "elif")  # statement words followed by Python
# Name kinds a syntax's ``<word> <kind>`` pair can name (2026-11-02, AC-F45-52): ``lock route
# <label>``, ``until <ending>``, ``unlock tip|item <name>`` (a ``<name>`` after a choice of
# words is the chosen word's kind). Modifier pairs (``at <position>``) keep DOC_MODIFIERS.
# F28 (07 I-16): ``effect jitter <sprite>``, a sprite tag (``tag`` is the text-tag kind).
# F32 (07 I-10): ``ui style <style>``, a config style name or off.
SLOT_KINDS: Final = frozenset(("label", "ending", "route", "tip", "item", "meter", "minigame",
                               "chapter", "image", "sprite", "style"))

_FIRST_WORD = re.compile(r"[ \t]*([^\s\"]+)")
_SPEAKER = re.compile(r'[ \t]*[^\W\d]\w*(?:[ \t]+[^\s"]+)*[ \t]*"')
_SPACES = re.compile(r"[ \t]+")
_QUOTE_OR_ESCAPE = re.compile(r'\\.|"', re.DOTALL)
_TAG_TYPED = re.compile(r"/?[a-z_]*")
_TAG_NAME_CHARS = re.compile(r"[a-z_]*")
_CHOICE_IF = re.compile(r'"[ \t]+if[ \t]')
_CODEX_DOT = re.compile(r"(?:^|[^\w.])codex\.(\w*)$")
_IN_CODEX = re.compile(r'[^"]*"[ \t]*(?:not[ \t]+)?in[ \t]+codex\.(tips|items)\b')
_WORDS = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class Context:
    """Where completion is: the name ``kinds`` that fit (in offer order), the typed
    ``prefix`` (an image name's runs of spaces read as one space), and the columns an
    accepted name replaces, ``start`` up to the cursor ``column``."""

    kinds: tuple[str, ...]
    prefix: str
    start: int
    column: int
    scope: str = ""                      # MINIGAME_ARG_KIND: the minigame's name


@dataclass(frozen=True, slots=True)
class Candidate:
    """One completion row: the name, then its kind word (shown in the muted color)."""

    text: str
    kind: str


# --- Completion ------------------------------------------------------------------------

def _in_quotes(text: str) -> bool:
    """True if ``text`` ends inside a string (an odd number of unescaped quotes)."""
    inside = False
    for found in _QUOTE_OR_ESCAPE.finditer(text):
        mark = found.group()
        if mark == '"' or (not inside and mark == '\\"'):
            inside = not inside             # outside a string a backslash escapes nothing
    return inside


def _is_file_char(char: str) -> bool:
    """A character of a file name typed after an open quote: ``[\\w/.-]``."""
    return char in "/.-" or is_word_char(char)


def _run_start(text: str, ok: Callable[[str], bool]) -> int | None:
    """Where the run of ``ok`` characters that ends ``text`` starts, or None for a run
    longer than ``PREFIX_MAX`` (a backward scan, so a huge line costs at most that)."""
    start = len(text)
    stop = max(0, start - PREFIX_MAX - 1)
    while start > stop and ok(text[start - 1]):
        start -= 1
    if len(text) - start > PREFIX_MAX:
        return None
    return start


def _kinds_of(docs: Iterable[StatementDoc]) -> tuple[str, ...]:
    kinds: list[str] = []
    for doc in docs:
        kinds.extend(k for k in doc.names if k not in kinds)
    return tuple(kinds)


def slot_words(docs: Iterable[StatementDoc]) -> dict[str, tuple[str, ...]]:
    """Word → the name kinds that follow it, from each doc's syntax (``SLOT_KINDS`` only):
    ``route <label>`` maps ``route`` to ``label``; ``tip|item <name>`` maps ``tip`` to
    ``tip`` and ``item`` to ``item``. The statement word itself is not a slot word."""
    slots: dict[str, list[str]] = {}
    for doc in docs:
        tokens = [t.strip("[],") for t in doc.syntax.split()]
        for word, slot in zip(tokens[1:], tokens[2:]):
            if not (slot.startswith("<") and slot.endswith(">")) or word.startswith("<"):
                continue
            for literal in word.split("|"):
                kind = literal if slot == "<name>" else slot[1:-1]
                if literal.isidentifier() and kind in SLOT_KINDS:
                    found = slots.setdefault(literal, [])
                    if kind not in found:
                        found.append(kind)
    return {word: tuple(kinds) for word, kinds in slots.items()}


def verb_words(word: str) -> tuple[str, ...]:
    """The second words of ``word``'s doc syntaxes, in registration order (``file`` →
    ``write``, ``delete``, ``exists``, ``read``); empty unless ``word`` is a
    ``VERB_STATEMENTS`` word."""
    if word not in VERB_STATEMENTS:
        return ()
    verbs: list[str] = []
    for doc in docs_for(word):
        tokens = doc.syntax.split()
        if len(tokens) > 1 and tokens[1].isidentifier() and tokens[1] not in verbs:
            verbs.append(tokens[1])
    return tuple(verbs)


def statement_words() -> tuple[str, ...]:
    """The registry's statement words (no forms, no modifiers), in registration order."""
    words: list[str] = []
    for doc in all_docs():
        if doc.key not in DOC_FORMS and doc.key not in DOC_MODIFIERS and doc.key not in words:
            words.append(doc.key)
    return tuple(words)


def completion_context(line: str, column: int) -> Context | None:
    """What completes at ``column`` of ``line`` (04 §7.6), or None for no completion.

    - Nothing but indent before the word: statement words and character names.
    - Otherwise the first word's docs give the kinds; the last ``DOC_MODIFIERS`` word
      (``with``, ``at``) between it and the prefix takes over with its own kinds.
    - Inside quotes only ``audio`` stays, and the prefix is the ``[\\w/.-]`` run before the
      cursor; outside quotes ``audio`` is dropped (the same for every ``QUOTED_KINDS`` kind).
    - Right after a ``VERB_STATEMENTS`` word, its verbs (``file w`` offers ``write``).
    - After a word whose doc lists ``image`` (no modifier since), the prefix is every word
      typed after it, since image names have several words.
    """
    column = max(0, min(column, len(line)))
    before = line[:column]
    tag = _tag_context(before)
    if tag is not None:
        return tag
    quoted = _in_quotes(before)
    codex = _codex_context(line, before, quoted)
    if codex is not None:
        return codex
    start = _run_start(before, _is_file_char if quoted else is_word_char)
    if start is None:
        return None
    head = before[:start]
    if not head.strip():
        if quoted:
            return None
        return Context((STATEMENT_KIND, CHARACTER_KIND), before[start:], start, column)
    first = _FIRST_WORD.match(head)
    if first is None:
        return None
    docs = docs_for(first.group(1))
    if not docs:
        return None
    kinds = _kinds_of(docs)
    span_start = first.end()
    slots = slot_words(docs)
    later = head[span_start:].split()
    for found in _WORDS.finditer(head, span_start):
        word = found.group()
        if word in DOC_MODIFIERS:
            kinds = _kinds_of(docs_for(word))
            span_start = -1              # the word after a modifier is one word
        elif word in slots and not _in_quotes(head[:found.start()]):
            kinds = slots[word]
            # image names have several words (lock item … image <words>)
            span_start = found.end() if IMAGE_KIND in kinds else -1
    if not later and not quoted and verb_words(first.group(1)):
        return Context((VERB_KIND,), before[start:], start, column, scope=first.group(1))
    if first.group(1) == MINIGAME_WORD and later and not quoted:
        # minigame <name> <arg>=…: argument names, never after "=" or into (F23).
        if later[-1] == "into" or head[-1:] not in (" ", "\t"):
            return None
        return Context((MINIGAME_ARG_KIND,), before[start:], start, column, scope=later[0])
    if quoted:
        kinds = tuple(k for k in kinds if k in QUOTED_KINDS)
    else:
        kinds = tuple(k for k in kinds if k not in QUOTED_KINDS)
    if not kinds:
        return None
    if IMAGE_KIND in kinds and span_start >= 0 and not quoted:
        span = before[span_start:]
        lead = len(span) - len(span.lstrip(" \t"))
        typed = span[lead:]
        if len(typed) <= PREFIX_MAX and all(c in " \t" or is_word_char(c) for c in typed):
            return Context(kinds, _SPACES.sub(" ", typed), span_start + lead, column)
    return Context(kinds, before[start:], start, column)


def _is_python_line(head: str) -> bool:
    """True if ``head`` (a line's text) starts a statement followed by Python (``$``,
    ``if``, ``elif``) or is a choice with an ``if`` condition."""
    first = _FIRST_WORD.match(head)
    word = first.group(1).rstrip(":") if first else ""
    return word in PYTHON_KEYS or word.startswith("$") or bool(_CHOICE_IF.search(head))


def _codex_context(line: str, before: str, quoted: bool) -> Context | None:
    """In a Python line: ``codex.`` offers ``tips``/``items``; a string typed so far as one
    name offers tip and item names (the kind ``in codex.<kind>`` after it names, if any)."""
    column = len(before)
    if not quoted:
        dot = _CODEX_DOT.search(before)
        if dot is None or not _is_python_line(before):
            return None
        return Context((CODEX_FIELD_KIND,), dot.group(1), column - len(dot.group(1)), column)
    start = _string_start(before)
    if start is None or not _is_python_line(before[:start]):
        return None
    typed = before[start:]
    if len(typed) > PREFIX_MAX or not all(is_word_char(c) for c in typed):
        return None
    after = _IN_CODEX.match(line, column)
    kinds = ("tip", "item") if after is None else (after.group(1)[:-1],)
    return Context(kinds, typed, start, column)


def _string_start(text: str) -> int | None:
    """Where the string that ``text`` ends inside starts (just past its quote), or None
    when ``text`` doesn't end inside a string."""
    start: int | None = None
    for found in _QUOTE_OR_ESCAPE.finditer(text):
        mark = found.group()
        if mark == '"' or (start is None and mark == '\\"'):
            start = found.end() if start is None else None
    return start


def _open_tag(text: str) -> tuple[list[str], int | None]:
    """Read a string's text up to the cursor like F05's parser (``{{`` is a brace): the
    style tags still open, innermost last, and where the tag the cursor is inside starts
    (just past its ``{``), or None when the cursor is in plain text."""
    stack: list[str] = []
    i = 0
    while True:
        j = text.find("{", i)
        if j < 0:
            return stack, None
        if text.startswith("{{", j):
            i = j + 2
            continue
        close = text.find("}", j + 1)
        if close < 0:
            return stack, j + 1
        body = text[j + 1:close]
        if "{" in body:                  # a mistake (E161); read on from the inner "{"
            i = j + 1
            continue
        if body.startswith("/"):
            if body[1:] in stack:
                del stack[len(stack) - 1 - stack[::-1].index(body[1:])]
        else:
            doc = tag_doc(body.partition("=")[0])
            if doc is not None and doc.closes:
                stack.append(doc.name)
        i = close + 1


def _text_tag_at(before: str) -> tuple[list[str], int] | None:
    """(open style tags, offset just past the ``{``) when ``before`` ends inside a text
    tag of a dialogue or narration string, else None."""
    if "{" not in before:
        return None
    start = _string_start(before)
    if start is None:
        return None
    doc = help_for(before[:start])
    if doc is None or doc.key not in TEXT_KEYS:
        return None
    stack, at = _open_tag(before[start:])
    return None if at is None else (stack, start + at)


def _tag_context(before: str) -> Context | None:
    """Completion after ``{`` (tag names) or ``{/`` (the innermost open style tag)."""
    found = _text_tag_at(before)
    if found is None:
        return None
    stack, at = found
    typed = before[at:]
    if _TAG_TYPED.fullmatch(typed) is None:
        return None
    column = len(before)
    if typed.startswith("/"):
        if not stack:
            return None
        return Context((CLOSE_TAG_KIND,), typed[1:], at + 1, column, scope=stack[-1])
    return Context((TAG_KIND,), typed, at, column)


def _name_of(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    name = getattr(entry, "name", None)
    if name is None and isinstance(entry, (tuple, list)) and entry:
        name = entry[0]
    return name if isinstance(name, str) else None


def candidates(ctx: Context, names: Mapping[str, Iterable[object]],
               limit: int = COMPLETION_MAX) -> list[Candidate]:
    """The rows for ``ctx``: names of its kinds that start with the prefix, exact-case
    matches first, then case-insensitive ones, each sorted; at most ``limit``. A name in two
    kinds is listed once, under the first. ``statement`` names come from the registry; every
    other kind from ``names`` (a kind it lacks offers nothing)."""
    prefix = ctx.prefix
    folded = prefix.casefold()
    seen: set[str] = set()
    exact: list[Candidate] = []
    loose: list[Candidate] = []
    for kind in ctx.kinds:
        pool: Iterable[object]
        if kind == STATEMENT_KIND:
            pool = statement_words()
        elif kind == TAG_KIND:
            pool = tag_names()
        elif kind == CLOSE_TAG_KIND:
            pool = (ctx.scope,)
        elif kind == CODEX_FIELD_KIND:
            pool = CODEX_FIELDS
        elif kind == VERB_KIND:
            pool = verb_words(ctx.scope)
        else:
            pool = names.get(kind, ())
        for entry in pool:
            text = _name_of(entry)
            if text is not None and kind == MINIGAME_ARG_KIND:
                scoped = ctx.scope + "."
                text = text[len(scoped):] + "=" if text.startswith(scoped) else None
            if text is None or text in seen:
                continue
            if text.startswith(prefix):
                exact.append(Candidate(text, kind))
            elif text.casefold().startswith(folded):
                loose.append(Candidate(text, kind))
            else:
                continue
            seen.add(text)
    order = lambda c: (c.text.casefold(), c.text)  # noqa: E731
    exact.sort(key=order)
    if len(exact) >= limit:
        return exact[:limit]
    loose.sort(key=order)
    return (exact + loose)[:limit]


def accept(line: str, ctx: Context, candidate: Candidate) -> tuple[str, int]:
    """``line`` with ``candidate`` in place of ``start..column``, and the new cursor
    column."""
    end = ctx.start + len(candidate.text)
    return line[:ctx.start] + candidate.text + line[ctx.column:], end


def auto_open(line: str, column: int) -> bool:
    """PR-F45-14: True right after the space that follows a statement word (or a ``with``/
    ``at``) whose doc lists a name kind that fits there; and right after a text tag's
    ``{`` or ``{/`` (AC-F45-57)."""
    before = line[:column]
    if before.endswith(("{", "{/")):
        ctx = completion_context(line, column)
        return ctx is not None and ctx.kinds in ((TAG_KIND,), (CLOSE_TAG_KIND,))
    if before.endswith("codex."):
        ctx = completion_context(line, column)
        return ctx is not None and ctx.kinds == (CODEX_FIELD_KIND,)
    if not before.endswith((" ", "\t")):
        return False
    words = before.split()
    if not words:
        return False
    if len(words) > 1 and words[-1] not in DOC_MODIFIERS             and words[-1] not in slot_words(docs_for(words[0]))             and not (words[0] == MINIGAME_WORD and words[-1] != "into"):
        return False
    if words[-1] in DOC_FORMS:
        return False
    ctx = completion_context(line, column)
    return ctx is not None and STATEMENT_KIND not in ctx.kinds


# --- Insert ----------------------------------------------------------------------------

def insert_menu() -> tuple[tuple[str, tuple[StatementDoc, ...]], ...]:
    """The Insert menu: ``(group, docs)`` for each ``GROUPS`` entry with an ``insert=True``
    doc, in ``GROUPS`` order, each group's docs in registration order."""
    docs = [d for d in all_docs() if d.insert]
    menu = []
    for group in GROUPS:
        entries = tuple(d for d in docs if d.group == group)
        if entries:
            menu.append((group, entries))
    return tuple(menu)


def insert_text(doc: StatementDoc, indent: str, unit: str) -> tuple[str, tuple[int, int] | None]:
    """``doc.example`` ready to insert at a line indented by ``indent``: each line gets
    ``indent``, and each 4-space nesting step becomes ``unit`` (the file's ``indent_unit``).
    No trailing newline. Also the ``(start, end)`` character offsets, in the returned text,
    of the first match of ``fields[0]`` (to select), or None for a doc with no fields."""
    out = []
    for raw in doc.example.split("\n"):
        depth = 0
        while raw.startswith(EXAMPLE_INDENT, depth * len(EXAMPLE_INDENT)):
            depth += 1
        out.append(indent + unit * depth + raw[depth * len(EXAMPLE_INDENT):])
    text = "\n".join(out)
    if not doc.fields:
        return text, None
    at = text.find(doc.fields[0])
    return text, (None if at < 0 else (at, at + len(doc.fields[0])))


# --- Help ------------------------------------------------------------------------------

def help_for(line: str) -> StatementDoc | None:
    """The doc for the statement on ``line`` (04 §7.6), or None ("No help for this line.").

    A leading ``$`` is ``$``, a leading quote ``narration``, and ``speaker [words] "`` is
    ``dialogue``. A word with several docs picks the one whose ``syntax`` starts with the
    line's first two words (``play music``, ``play sound``), else its first."""
    stripped = line.lstrip(" \t")
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("$"):
        return _first(docs_for("$"))
    if stripped.startswith('"'):
        return _first(docs_for("narration"))
    first = _FIRST_WORD.match(line)
    word = first.group(1).rstrip(":") if first else ""
    docs = docs_for(word) if word not in DOC_FORMS else ()
    if docs:
        two = " ".join(stripped.replace(":", " ").split()[:2])
        for doc in docs:
            if doc.syntax.startswith(two):
                return doc
        return docs[0]
    if _SPEAKER.match(line):
        return _first(docs_for("dialogue"))
    return None


def _first(docs: tuple[StatementDoc, ...]) -> StatementDoc | None:
    return docs[0] if docs else None


def tag_help(line: str, column: int) -> TagDoc | None:
    """The row of the text tag the cursor at ``column`` is inside (between its ``{`` and
    ``}``) in a dialogue or narration string, or None. The name may run on past the
    cursor (``{co|lor=…}``); a closing tag ``{/b}`` gives ``b``'s row."""
    column = max(0, min(column, len(line)))
    found = _text_tag_at(line[:column])
    if found is None:
        return None
    body = line[found[1]:column].removeprefix("/")
    name = body.partition("=")[0]
    if "=" not in body:
        rest = _TAG_NAME_CHARS.match(line, column)
        name += rest.group() if rest is not None else ""
    return tag_doc(name)


def help_sections(doc: StatementDoc | TagDoc | None) -> tuple[tuple[str, str], ...]:
    """What the Help pane shows, as ``(part, text)`` rows in order: ``title``, ``syntax``,
    ``summary``, ``example``, and ``docs`` (``Docs: <heading>``, left out while the docs
    step is pending); a ``TagDoc`` gives the same rows. For None, one ``none`` row with
    ``NO_HELP``."""
    if doc is None:
        return (("none", NO_HELP),)
    rows = [("title", doc.title), ("syntax", doc.syntax), ("summary", doc.summary)]
    if doc.example:                      # a config section with no keys has none
        rows.append(("example", doc.example))
    if doc.docs is not None:
        rows.append(("docs", f"Docs: {doc.docs}"))
    return tuple(rows)


__all__ = ["AUDIO_KIND", "CHARACTER_KIND", "CLOSE_TAG_KIND", "CODEX_FIELD_KIND", "COMPLETION_MAX",
           "COMPLETION_VISIBLE", "Candidate", "Context", "TAG_KIND", "tag_help", "IMAGE_KIND", "MINIGAME_ARG_KIND", "NO_HELP",
           "SLOT_KINDS", "STATEMENT_KIND", "accept", "slot_words",
           "auto_open", "candidates", "completion_context", "help_for", "help_sections",
           "insert_menu", "insert_text", "statement_words", "META_FILE_KIND", "QUOTED_KINDS",
           "VERB_KIND", "VERB_STATEMENTS", "verb_words"]
