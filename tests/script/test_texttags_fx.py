"""F29 step 2 — effect tags become a styled body (``06-acceptance.md`` AC-F29-01;
``04-technical.md`` §6.1). Headless: ``texttags.parse`` on line text, no load.

The load messages (AC-F29-02, 03) are rows of ``tests/fixtures/F02/messages/cases.toml``;
W185 (AC-F29-04) is ``test_checks_w185.py``. The resolved ``{var}`` row ("Hana"[glitch]) is
AC-F29-06's headless run (``tests/runtime/test_textfx_headless.py``).
"""

import re
from dataclasses import replace

import pytest

from engine.runtime import commands
from engine.script import texttags
from engine.script.texttags import (EFFECT_KINDS, STRENGTHS, Span, Style, TaggedText,
                                    TextEffect, VarMark, parse)

_FX_TAG = re.compile(r"\{/?(?:shake|wave|glitch)(?:=[a-z]*)?\}")


def _st(*marks: str) -> Style:
    """F29 06 §0.3's notation: ``b``, ``#e05050``, ``s1.5``, ``v0.2``, ``wave``,
    ``shake:large``."""
    style = Style()
    for mark in marks:
        kind, _, strength = mark.partition(":")
        if mark == "b":
            style = replace(style, bold=True)
        elif mark.startswith("#"):
            style = replace(style, color=mark)
        elif mark[0] in "sv" and mark[1:2].isdigit():
            number = float(mark[1:])
            style = replace(style, size=number) if mark[0] == "s" else replace(style, speed=number)
        else:
            assert kind in EFFECT_KINDS, mark
            style = replace(style, effect=TextEffect(kind, strength or "medium"))
    return style


def _sp(text: str, *marks: str) -> Span:
    return Span(text, _st(*marks))


def _parse(text: str) -> TaggedText:
    problems: list = []
    body = parse(text, lambda at: (7, 6 + at), problems.append)
    assert problems == [] and body is not None, [p.message() for p in problems]
    return body


ROWS = [
    ("I'm {wave}so{/wave} happy", (_sp("I'm "), _sp("so", "wave"), _sp(" happy"))),
    ("{shake=small}a{/shake}", (_sp("a", "shake:small"),)),
    ("{wave=medium}a{/wave}", (_sp("a", "wave"),)),
    ("{glitch=large}a{/glitch}", (_sp("a", "glitch:large"),)),
    ("{shake}a{shake=large}b{/shake}c{/shake}",
     (_sp("a", "shake"), _sp("b", "shake:large"), _sp("c", "shake"))),
    ("{shake=small}a{/shake}{shake=small}b{/shake}", (_sp("ab", "shake:small"),)),
    ("{b}{glitch=large}x{/glitch}y{/b}", (_sp("x", "b", "glitch:large"), _sp("y", "b"))),
    ("{color=#e05050}{wave}a{size=1.5}b{/size}{/wave}{/color}",
     (_sp("a", "#e05050", "wave"), _sp("b", "#e05050", "s1.5", "wave"))),
    ("{shake}{speed=0.2}don't{/speed}{/shake}", (_sp("don't", "v0.2", "shake"),)),
    ("{shake}a{/shake}{wave}b{/wave}", (_sp("a", "shake"), _sp("b", "wave"))),
    ("{glitch}{/glitch}x", (_sp("x"),)),
    ("{glitch}   {/glitch}x", (_sp("   ", "glitch"), _sp("x"))),
    ("{shake}open at end", (_sp("open at end", "shake"),)),
    ("a{wave}b\nc{/wave}", (_sp("a"), _sp("b\nc", "wave"))),
    ("My name is {glitch}{var=hana_name}{/glitch}.",
     (_sp("My name is "), VarMark("hana_name", _st("glitch")), _sp("."))),
]


@pytest.mark.parametrize("text,pieces", ROWS, ids=[row[0] for row in ROWS])
def test_ac_f29_01_effect_tags_become_a_styled_body(text, pieces):
    body = _parse(text)
    assert body.pieces == pieces
    # plain() equals the same text with its effect tags removed (and so do its styles).
    same = _parse(_FX_TAG.sub("", text))
    assert "".join(s.text for s in body.plain()) == "".join(s.text for s in same.plain())
    for piece in body.pieces:
        effect = piece.style.effect if isinstance(piece, (Span, VarMark)) else None
        assert effect is None or (type(effect) is TextEffect and effect.kind in EFFECT_KINDS
                                  and effect.strength in STRENGTHS)
    # The "And" clauses: the key, the re-export, the eleven tags (F30's twelfth since).
    assert TextEffect("shake").key() == "shake:medium"
    assert commands.TextEffect is texttags.TextEffect
    assert texttags.TAGS >= set(EFFECT_KINDS) and len(texttags.TAGS) == 12
