"""The statement doc registry (F45 ``04-technical.md`` §4.1, §5; ``07`` O-2, I-4, I-5).

Why this module exists: Studio's Insert menu, Help panel, and statement-word completion read
one list of doc entries, so a new statement shows up in all three by registering one
``StatementDoc``, and nothing is hand-listed in the editor (PR-F45-17).

- A feature calls ``register_doc`` in the same place and at the same time as its
  ``register(StatementSpec)`` (``07`` I-5). Words registered before F45 step 1 have rows in
  ``docs_table.py``.
- Keys are statement words (``STATEMENT_WORDS``), the built-in forms ``DOC_FORMS``, and the
  modifiers ``DOC_MODIFIERS``. A word may have several entries (``play music``, ``play
  sound``); ``docs_for`` keeps registration order.
- ``scoped_registry()`` (``statements.py``) also saves and restores this registry
  (``_snapshot``, ``_restore``), so a doc registered inside a test's scope is gone after it.
- ``docs`` is the exact text of a heading in ``docs/script-language.md``, or None while the
  word's docs step is pending (the completeness test's ``DOCS_PENDING``; ``07`` I-4).

Imports only ``words`` from the script package, so ``statements`` can import this module
without a cycle.
"""

import re
from dataclasses import dataclass
from typing import Final

from engine.script.words import STATEMENT_WORDS

GROUPS: Final = ("Text", "Story flow", "Choices", "Logic", "Time", "Stage", "Audio",
                 "Effects", "Minigames", "Declarations", "Files")
# Minigames: 2026-11-02, AC-F45-53. Time: F63's clock (Insert ▸ Time).
DOC_FORMS: Final = ("dialogue", "narration", "$")
DOC_MODIFIERS: Final = ("with", "at")
# A name kind (``names``): the same pattern as the check child's ``CHECK_KIND_RE`` (04 §4.3).
NAME_KIND_RE: Final = re.compile(r"[a-z][a-z_]{0,31}")


@dataclass(frozen=True, slots=True)
class StatementDoc:
    """One Insert entry and Help page. ``example`` is ``\\n``-separated with 4-space nesting
    and loads and launches cleanly in ``tests/fixtures/docgame/`` (TR-F45-01). ``fields`` are
    substrings of the example; ``fields[0]`` is selected on insert. ``names`` are the name
    kinds that may follow the word (``"label"``, ``"image"``, ``"audio"``, …).
    ``insert=False``: Help only (``elif``, ``else``)."""

    key: str
    title: str
    group: str
    syntax: str
    summary: str
    example: str
    docs: str | None
    feature: str
    fields: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    insert: bool = True


_DOCS: list[StatementDoc] = []


def _problem(doc: StatementDoc) -> str | None:
    from engine.script.statements import _POSITIONAL    # ADR-0010: positional words too
    if doc.key not in STATEMENT_WORDS and doc.key not in DOC_FORMS \
            and doc.key not in DOC_MODIFIERS and doc.key not in _POSITIONAL:
        return f"{doc.key!r} is not a statement word, form, or modifier"
    if doc.group not in GROUPS:
        return f"{doc.key!r}: group {doc.group!r} is not one of GROUPS"
    if any(d.key == doc.key and d.syntax == doc.syntax for d in _DOCS):
        return f"{doc.key!r}: a doc with syntax {doc.syntax!r} is already registered"
    for name in doc.fields:
        if not name or name not in doc.example:
            return f"{doc.key!r}: field {name!r} is not in the example"
    for kind in doc.names:
        if not isinstance(kind, str) or NAME_KIND_RE.fullmatch(kind) is None:
            return f"{doc.key!r}: name kind {kind!r} doesn't match {NAME_KIND_RE.pattern}"
    return None


def register_doc(doc: StatementDoc) -> None:
    """Add ``doc``. ``ValueError`` (at import, so a bad row fails every test) for a key that
    is no statement word, form, or modifier; a group not in ``GROUPS``; a repeated (key,
    syntax); a field not in the example; or a name kind that isn't ``NAME_KIND_RE``."""
    problem = _problem(doc)
    if problem is not None:
        raise ValueError(problem)
    _DOCS.append(doc)


def docs_for(key: str) -> tuple[StatementDoc, ...]:
    """The entries for ``key``, in registration order (empty when it has none)."""
    return tuple(d for d in _DOCS if d.key == key)


def all_docs() -> tuple[StatementDoc, ...]:
    """Every entry, in registration order."""
    return tuple(_DOCS)


def _snapshot() -> tuple[StatementDoc, ...]:
    """For ``statements.scoped_registry``."""
    return tuple(_DOCS)


def _restore(saved: tuple[StatementDoc, ...]) -> None:
    _DOCS[:] = saved


__all__ = ["DOC_FORMS", "DOC_MODIFIERS", "GROUPS", "NAME_KIND_RE", "StatementDoc", "all_docs",
           "docs_for", "register_doc"]
