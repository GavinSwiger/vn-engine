"""F45's statement doc registry: its rules and the growth test (``06-acceptance.md`` AC-F45-01,
AC-F45-02; TR-F45-07's registry and label halves; ``07`` I-4).

The growth test is ``missing_docs()``: every registered statement word, ``DOC_FORMS`` key, and
``DOC_MODIFIERS`` word has a ``StatementDoc``, and every doc's ``docs`` is the exact text of a
heading in ``docs/script-language.md``, or None for a key in ``DOCS_PENDING`` (key → the step
that adds its heading; that step removes the key). No word count is hard-coded.
"""

import dataclasses
import re
from pathlib import Path

import pytest

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.script.labelgraph import LINK_RULES, NOT_LINKS
from engine.script.lexer import TAIL_SCRIPT
from engine.script.statement_docs import (
    DOC_FORMS,
    DOC_MODIFIERS,
    GROUPS,
    StatementDoc,
    all_docs,
    docs_for,
    register_doc,
)
from engine.script.statements import StatementSpec, register, registered_words, scoped_registry
from engine.script.words import STATEMENT_WORDS

LANGUAGE_DOC = Path(__file__).resolve().parents[2] / "docs" / "script-language.md"

# 07 I-4: keys whose docs/script-language.md heading is still to come.
DOCS_PENDING = {
    "effect": "F28 s6",              # registered by glitch.register_words() until F28 s3
    "ui": "F32 s6",                  # ui.HEADING; registered by ui.register_words() from F32 s3
    "file": "F31 s5",                # "Meta files"; metafiles.register_words() from F31 s3
}

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")


def headings(text: str) -> set[str]:
    """The text of every ``#`` heading outside fenced code blocks."""
    found, fenced = set(), False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING.match(line)
        if match is not None:
            found.add(match.group(1))
    return found


def missing_docs() -> list[str]:
    """Every gap in the registry (empty when complete)."""
    known = headings(LANGUAGE_DOC.read_text("utf-8"))
    keyed = {doc.key for doc in all_docs()}
    keys = sorted(registered_words()) + list(DOC_FORMS) + list(DOC_MODIFIERS)
    problems = [f"{key}: no StatementDoc" for key in keys if key not in keyed]
    for doc in all_docs():
        if doc.docs is None and doc.key not in DOCS_PENDING:
            problems.append(f"{doc.key} ({doc.syntax}): no docs heading")
        elif doc.docs is not None and doc.docs not in known:
            problems.append(f"{doc.key} ({doc.syntax}): no heading {doc.docs!r} in "
                            "docs/script-language.md")
    return problems


def _doc(key: str = "jump", **changes) -> StatementDoc:
    doc = StatementDoc(key, "Jump to a label", "Story flow", "jump <label> again",
                       "Continues at a label.", "jump river", "jump", "F45",
                       fields=("river",), names=("label",))
    return dataclasses.replace(doc, **changes)


def _unbuilt_word() -> str:
    """A reserved word with no statement and no doc yet (AC-F45-02's ``zzword``: ``register``
    accepts only reserved words)."""
    keyed = {doc.key for doc in all_docs()}
    return sorted(STATEMENT_WORDS - registered_words() - set(DOC_MODIFIERS) - keyed)[0]


def test_ac_f45_01_register_doc_refuses_bad_rows():
    before = all_docs()
    bad = [
        _doc(key="jmup"),
        _doc(group="Misc"),
        _doc(syntax="jump <label>"),                    # docs_table's jump row
        _doc(fields=("bridge",)),
        _doc(names=("Label",)),
        _doc(names=("1x",)),
        _doc(names=("a" * 33,)),
    ]
    with scoped_registry():
        for doc in bad:
            with pytest.raises(ValueError):
                register_doc(doc)
            assert all_docs() == before, doc
        music = _doc("play", syntax='play music "<file>" x', example='play music "a.ogg"',
                     fields=("a.ogg",), names=("audio",))
        sound = _doc("play", syntax='play sound "<file>" x', example='play sound "b.ogg"',
                     fields=("b.ogg",), names=("audio",))
        register_doc(music)
        register_doc(sound)
        assert docs_for("play")[-2:] == (music, sound)
        assert all_docs() == before + (music, sound)
    assert all_docs() == before


def test_ac_f45_02_every_word_form_and_modifier_has_docs():
    assert missing_docs() == []
    assert set(GROUPS) >= {doc.group for doc in all_docs()}
    word = _unbuilt_word()
    with scoped_registry():
        register(StatementSpec(word=word, placement="story", takes_block=False,
                               tail=TAIL_SCRIPT, parse=lambda raw, ctx: None))
        assert missing_docs() == [f"{word}: no StatementDoc"]
        register_doc(_doc(word, syntax=word, example=word, fields=(), names=()))
        assert missing_docs() == []
        register_doc(_doc(word, syntax=f"{word} x", example=word, fields=(), names=(),
                          docs="No such heading"))
        assert missing_docs() == [f"{word} ({word} x): no heading 'No such heading' in "
                                  "docs/script-language.md"]
    assert missing_docs() == []


def test_tr_f45_07_label_docs_have_link_rules():
    """Every doc that lists the ``label`` name kind is a ``LINK_RULES`` or ``NOT_LINKS`` word,
    and each rule's node type is its word's (``LINK_RULES`` keys are statement words)."""
    for doc in all_docs():
        if "label" in doc.names:
            assert doc.key in LINK_RULES or doc.key in NOT_LINKS, doc.key
    assert set(LINK_RULES) <= registered_words() and NOT_LINKS <= registered_words()
