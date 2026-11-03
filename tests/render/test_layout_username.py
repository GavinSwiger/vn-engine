"""F30 step 5 — AC-F30-25: the layout swaps in the player's name, literally (``04`` §6.4
steps 2–3; SEC-F30-06(d); C3). ``LineLayout`` with the M20 fake font."""

import ast
from dataclasses import replace
from pathlib import Path

from engine.render.textlayout import LineLayout
from engine.runtime.commands import Span, Style, TaggedText, TextEffect
from tests.fakes.fixed_font import m20_context
from tests.fakes.username import Z, Z32, no_real_username  # noqa: F401  (name guard)

ENGINE = Path(__file__).resolve().parents[2] / "engine"
FLAGGED = Style(username=True)


def drawn(body: TaggedText, name: str | None, **ctx) -> tuple[str, bool, LineLayout]:
    lay = LineLayout(body, replace(m20_context(**ctx), name=name))
    text = "".join(g.text for k in range(lay.all_pages()) for line in lay.page(k).lines
                   for g in line.glyphs)
    return text, lay.has_name, lay


def test_ac_f30_25_layout_swaps_in_the_name_literally():
    friend = TaggedText((Span("friend", FLAGGED),))
    assert drawn(friend, None)[:2] == ("friend", False)
    assert drawn(friend, Z)[:2] == (Z, True)
    assert drawn(TaggedText((Span("friend", Style()),)), Z)[:2] == ("friend", False)
    # Tag-like names draw as text: no bold, no wait, no brace folding.
    for name in ("{b}x{/b}", "{{", "{w}"):
        text, has, lay = drawn(friend, name)
        assert (text, has) == (name, True)
        assert all(not g.face.ref or "Bold" not in str(g.face.ref)
                   for g in lay.page(0).lines[0].glyphs)
    # Z32 wraps as the same text written literally (40-character line).
    before = "a" * 20 + " "
    body = TaggedText((Span(before, Style()), Span("friend", FLAGGED)))
    literal = TaggedText((Span(before + Z32, Style()),))
    width = 20 * 30
    _, _, lay_named = drawn(body, Z32, width=width)
    _, _, lay_literal = drawn(literal, None, width=width)
    rows = lambda lay: [[g.text for g in line.glyphs] for k in range(lay.all_pages())
                        for line in lay.page(k).lines]
    assert rows(lay_named) == rows(lay_literal)
    # Inside {b} and F29's {wave}: the flagged span keeps its look and effect.
    wave = TextEffect("wave")
    styled = TaggedText((Span("friend", Style(bold=True, effect=wave, username=True)),))
    _, _, lay = drawn(styled, Z)
    glyphs = lay.page(0).lines[0].glyphs
    assert "".join(g.text for g in glyphs) == Z
    assert all(g.effect == wave for g in glyphs)
    plain_bold = LineLayout(TaggedText((Span(Z, Style(bold=True, effect=wave)),)),
                            m20_context()).page(0).lines[0].glyphs
    assert [(g.face, g.x) for g in glyphs] == [(g.face, g.x) for g in plain_bold]

    # Only the textbox (ADV show, NVL ctx_for) passes a name: every other LayoutContext
    # built in engine/ leaves it at None.
    passing = []
    for path in sorted(ENGINE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "LayoutContext(" not in text and "line_context(" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(
                    "LayoutContext") and (len(node.args) > 6
                                         or any(k.arg == "name" for k in node.keywords)):
                passing.append(path.relative_to(ENGINE).as_posix())
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(
                    "line_context") and len(node.args) > 5:
                passing.append(path.relative_to(ENGINE).as_posix())
    assert sorted(set(passing)) == ["render/nvllayout.py", "ui/builtin/nvl_page.py",
                                    "ui/builtin/textbox_screen.py"], passing
