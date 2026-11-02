"""F05 ``render/textlayout.py``: word wrap (AC-F05-12), pages and stops (AC-F05-13's
size-28 rows and UI-F05-02's pitches, ahead of the view), ``count_pages`` (TR-F05-01's
property on a seeded corpus), laziness, positions, and the word cache. All with the M20
fake font (06 §0.6). F29: effects change no layout or timing (AC-F29-07)."""

import random
import re
from dataclasses import replace

import pytest

from engine.render import textlayout
from engine.render.assets import Face, Synth
from engine.render.textlayout import (
    BUNDLED_FACES,
    FaceSet,
    FaceSource,
    LineLayout,
    count_pages,
    face_for,
    render_safe,
)
from engine.render.typewriter import (
    END,
    PAGE_BREAK,
    WAIT,
    GlyphShown,
    GlyphSlot,
    PauseSlot,
    Typewriter,
    TypeState,
)
from engine.runtime.commands import Span, Style, TaggedText, TextEffect, VarMark
from tests.fakes.fixed_font import BASE_COLOR, FixedFontAssets, m20_context, tagged


def layout(text: str, size: int = 28, **kwargs) -> LineLayout:
    return LineLayout(tagged(text), m20_context(size, **kwargs))


def lines_of(lay: LineLayout) -> list[tuple[str, float | None]]:
    """Per line over all pages: the graphemes as drawn (hanging spaces left out) and the x
    of the first drawn non-space grapheme."""
    out = []
    for k in range(lay.all_pages()):
        for line in lay.page(k).lines:
            drawn = [g for g in line.glyphs if not g.hangs]
            first = next((g.x for g in drawn if g.text != " "), None)
            out.append(("".join(g.text for g in drawn), first))
    return out


def stops(lay: LineLayout) -> list[str]:
    """The stops of the whole line in order: click, page, end."""
    names = {WAIT: "click", PAGE_BREAK: "page", END: "end"}
    return [names[slot] for k in range(lay.all_pages()) for slot in lay.timeline(k)
            if slot in names]


# --- AC-F05-12: word wrap -----------------------------------------------------------------------

WRAP_ROWS = [
    ("a" * 46, [("a" * 46, 0)]),
    ("a" * 47, [("a" * 46, 0), ("a", 0)]),
    ("a" * 43 + " bb", [("a" * 43 + " bb", 0)]),
    ("a" * 45 + " bb", [("a" * 45, 0), ("bb", 0)]),
    ("a" * 45 + "   bb", [("a" * 45, 0), ("bb", 0)]),
    ("a" * 42 + " xx{b}yy{/b}", [("a" * 42, 0), ("xxyy", 0)]),
    ("a" * 100, [("a" * 46, 0), ("a" * 46, 0), ("a" * 8, 0)]),
    (" a", [(" a", 20)]),
    ("a\n b", [("a", 0), (" b", 20)]),
    ("a\n\nb", [("a", 0), ("", None), ("b", 0)]),
    ("你好世界" * 20, [("你好世界" * 11 + "你好", 0), ("世界" + "你好世界" * 8, 0)]),
    # Edge cases beyond the AC table.
    ("a" * 45 + " bb", [("a" * 45 + " ", 0), ("bb", 0)]),   # no-break space
    ("a" * 46 + " " + "b" * 46, [("a" * 46, 0), ("b" * 46, 0)]),
    ("aaa　bbb", [("aaa　bbb", 0)]),                          # ideographic space
    ("a" * 50 + " b", [("a" * 46, 0), ("aaaa b", 0)]),                # split, then continue
    ("x " + "a" * 50, [("x", 0), ("a" * 46, 0), ("aaaa", 0)]),        # break, then split
    ("", [("", None)]),
    ("a\n", [("a", 0), ("", None)]),
]


@pytest.mark.parametrize("text, expected", WRAP_ROWS, ids=range(len(WRAP_ROWS)))
def test_word_wrap(text, expected):
    assert lines_of(layout(text)) == expected


def test_a_line_may_end_exactly_at_the_wrap_width():
    line = layout("a" * 43 + " bb").page(0).lines[0]
    assert line.glyphs[-1].right == 920


def test_hanging_spaces_are_kept_for_timing_but_not_drawn():
    lay = layout("a" * 45 + "   bb")
    first = lay.page(0).lines[0]
    assert [g.text for g in first.glyphs if g.hangs] == [" ", " ", " "]
    assert lay.glyph_count == 50
    assert [s.index for s in lay.timeline(0) if type(s) is GlyphSlot] == list(range(50))


def test_a_word_crossing_styles_is_measured_per_face():
    lay = layout("a" * 40 + " x{b}y{/b}", assets=FixedFontAssets({Face.BOLD: 30}))
    line = lay.page(0).lines[0]
    assert [(g.text, g.x, g.advance) for g in line.glyphs[-2:]] == [("x", 820, 20),
                                                                     ("y", 840, 30)]
    # 42 × a + " xxyy" with a 30-unit bold: 860 + 40 + 60 > 920, so the word moves.
    wide = layout("a" * 41 + " xx{b}yy{/b}", assets=FixedFontAssets({Face.BOLD: 30}))
    assert lines_of(wide) == [("a" * 41, 0), ("xxyy", 0)]


def test_breaks_do_not_depend_on_when_pages_are_laid_out():
    text = " ".join(f"word{n}" for n in range(200))
    in_order = layout(text)
    pages = in_order.all_pages()
    reverse = layout(text)
    late = {k: reverse.page(k) for k in reversed(range(pages))}
    assert pages > 2
    assert [in_order.page(k) for k in range(pages)] == [late[k] for k in range(pages)]


# --- Pages and stops (AC-F05-13 size-28 rows; the AC itself needs the view, step 6) ------------

def test_lines_fill_a_page():
    assert layout("a\nb\nc").all_pages() == 1
    seven = layout("a\nb\nc\nd\ne\nf\ng")
    assert [len(seven.page(k).lines) for k in range(seven.all_pages())] == [3, 3, 1]
    assert seven.timeline(0)[-1] is PAGE_BREAK and seven.timeline(1)[0] == GlyphSlot(3, "d")
    assert seven.timeline(1)[-1] is PAGE_BREAK and seven.timeline(2)[0] == GlyphSlot(6, "g")
    assert seven.timeline(2)[-1] is END


STOP_ROWS = [
    ("a\nb\nc{pause}\nd", ["page", "end"]),          # the wait merges into the page break
    ("a\nb\nc{pause}{pause=1}\nd", ["page", "end"]),
    ("ab{pause}", ["end"]),
    ("a{pause}{pause}b", ["click", "end"]),
    ("a{pause}\n{pause}b", ["click", "end"]),        # \n is not shown
    ("a{pause} {pause}b", ["click", "click", "end"]),  # a space is shown
    ("a{pause}{pause=1}{pause}b", ["click", "end"]),
    ("{pause}", ["end"]),
    ("", ["end"]),
    ("a\nb\nc\n", ["end"]),                         # an empty line never starts a page
    ("a\nb\nc\n\n\n\n", ["end"]),
    ("a\nb\nc\n\nd", ["page", "end"]),
]


@pytest.mark.parametrize("text, expected", STOP_ROWS, ids=range(len(STOP_ROWS)))
def test_stops(text, expected):
    assert stops(layout(text)) == expected


def test_a_later_page_starts_at_its_first_shown_line():
    lay = layout("a\nb\nc\n\n\nd")
    assert lay.all_pages() == 2
    assert [line.glyphs[0].text for line in lay.page(1).lines] == ["d"]


def test_marks_stay_in_order_around_glyphs_and_page_breaks():
    lay = layout("{pause=0.1}a\nb\nc{pause=0.2}\n{pause=0.3}d{pause=0.4}")
    assert lay.timeline(0) == (PauseSlot(0.1), GlyphSlot(0, "a"), GlyphSlot(1, "b"),
                               GlyphSlot(2, "c"), PauseSlot(0.2), PauseSlot(0.3), PAGE_BREAK)
    assert lay.timeline(1) == (GlyphSlot(3, "d"), PauseSlot(0.4), END)


def test_styles_cross_lines_and_pages():
    lay = layout("{b}x\ny\nz\nw")
    w = lay.page(1).lines[0].glyphs[0]
    assert (w.text, w.face) == ("w", BUNDLED_FACES.for_style(True, False))


PITCH_ROWS = [  # text size, pitch, lines per page (UI-F05-02)
    (20, 28, 4), (28, 39, 3), (38, 53, 3), (42, 59, 2), (48, 67, 2),
]


@pytest.mark.parametrize("size, pitch, per_page", PITCH_ROWS)
def test_pitch_and_lines_per_page(size, pitch, per_page):
    page = layout("\n".join("abcdefghij"), size).page(0)
    assert [line.pitch for line in page.lines] == [pitch] * per_page


def test_mixed_sizes_share_one_baseline_and_the_larger_pitch():
    lay = layout("a{size=2}B{/size}\nc\nd")
    first = lay.page(0)
    assert [line.pitch for line in first.lines] == [78, 39]
    # The 56-px font: ascent 44, descent 12, so (78 - 56) / 2 + 44.
    assert first.lines[0].baseline == 55
    assert [(g.text, g.size, g.x) for g in first.lines[0].glyphs] == [("a", 28, 0),
                                                                      ("B", 56, 20)]
    assert first.lines[1].top == 78 and first.lines[1].baseline == 78 + 27.5
    assert [line.glyphs[0].text for line in lay.page(1).lines] == ["d"]


def test_a_page_always_holds_one_line():
    lay = layout("\n".join("{size=2}x{/size}" for _ in range(3)), 48)
    assert [[line.pitch for line in lay.page(k).lines] for k in range(lay.all_pages())] \
        == [[134], [134], [134]]


# --- Flattening ---------------------------------------------------------------------------------

SAFE_ROWS = [
    ("plain", "plain"),
    ("a\nb", "a\nb"),
    ("a\tb\rc\x00d\x7f\x85e", "a�b�c�d��e"),
    ("x\ud800y", "x�y"),
    ("é‍👍🏽", "é‍👍🏽"),
]


@pytest.mark.parametrize("text, expected", SAFE_ROWS, ids=range(len(SAFE_ROWS)))
def test_render_safe(text, expected):
    assert render_safe(text) == expected


def test_controls_are_drawn_as_the_replacement_character():
    lay = LineLayout(TaggedText((Span("a\tb", Style()),)), m20_context())
    assert [(g.text, g.x) for g in lay.page(0).lines[0].glyphs] == [("a", 0), ("�", 20),
                                                                     ("b", 40)]


def test_graphemes_are_one_unit_each():
    lay = layout("a😀é🇯🇵")
    assert [(g.text, g.x) for g in lay.page(0).lines[0].glyphs] == [
        ("a", 0), ("😀", 20), ("é", 40), ("🇯🇵", 60)]


def test_glyph_looks():
    lay = layout("{color=#9a1c14}r{/color}{i}i{/i}{size=1.5}s{/size}{speed=0.5}v{/speed}")
    glyphs = lay.page(0).lines[0].glyphs
    assert [(g.color, g.face.bundled, g.size) for g in glyphs] == [
        ("#9a1c14", Face.REGULAR, 28), (BASE_COLOR, Face.ITALIC, 28),
        (BASE_COLOR, Face.REGULAR, 42), (BASE_COLOR, Face.REGULAR, 28)]
    assert [s.speed for s in lay.timeline(0) if type(s) is GlyphSlot] == [1, 1, 1, 0.5]


def test_an_unresolved_var_is_a_programmer_error():
    body = TaggedText((Span("a", Style()), VarMark("name", Style())))
    with pytest.raises(AssertionError):
        LineLayout(body, m20_context())


# --- Faces --------------------------------------------------------------------------------------

@pytest.mark.parametrize("bold, italic, face", [
    (False, False, Face.REGULAR), (True, False, Face.BOLD),
    (False, True, Face.ITALIC), (True, True, Face.BOLD_ITALIC)])
def test_face_for_style(bold, italic, face):
    assert face_for(bold, italic) is face
    assert BUNDLED_FACES.for_style(bold, italic) == FaceSource(None, face)


def test_fonts_are_requested_with_the_face_source():
    custom = FaceSet({Face.REGULAR: FaceSource("fonts/x.ttf", Face.REGULAR),
                      Face.BOLD: FaceSource("fonts/x.ttf", Face.BOLD, Synth.BOLD),
                      Face.ITALIC: FaceSource(None, Face.ITALIC),
                      Face.BOLD_ITALIC: FaceSource(None, Face.BOLD_ITALIC)})
    assets = FixedFontAssets()
    LineLayout(tagged("a{b}b{/b}{i}{size=2}c{/size}{/i}"), m20_context(assets=assets,
                                                                       faces=custom))
    assert set(assets.requests) == {("font", "fonts/x.ttf", 28, Synth.NONE),
                                    ("font", "fonts/x.ttf", 28, Synth.BOLD),
                                    ("font", "<italic>", 56, Synth.NONE)}


# --- Laziness, count_pages, cache ---------------------------------------------------------------

def test_construction_measures_nothing_and_page_k_breaks_up_to_k():
    assets = FixedFontAssets()
    lay = LineLayout(tagged("a\nb\nc\nd\ne\nf\ng"), m20_context(assets=assets))
    font = assets.font(None, 28).font
    assert lay.laid_out == 0 and font.calls == 0
    lay.page(0)
    assert lay.laid_out == 1
    lay.timeline(1)
    assert lay.laid_out == 2
    assert lay.all_pages() == 3 and lay.laid_out == 3


def test_page_past_the_last_is_an_index_error():
    lay = layout("a")
    with pytest.raises(IndexError):
        lay.page(1)
    assert lay.is_last(0)


def _corpus(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    parts = ["word", "a", "longerword", "你好世界", "😀", " ", "  ", "\n", "{b}", "{/b}",
             "{i}", "{/i}", "{size=2}", "{/size}", "{size=0.5}", "{/size}", "{pause}",
             "{pause=0.2}", "é", "x" * 60]
    texts = []
    for _ in range(count):
        out, open_tags = [], []
        for _ in range(rng.randrange(0, 300)):
            part = rng.choice(parts)
            if part.startswith("{/"):
                if not open_tags or open_tags[-1] != part:
                    continue
                open_tags.pop()
            elif part.startswith("{") and "pause" not in part:
                closing = "{/" + part[1:].split("=")[0].rstrip("}") + "}"
                if closing in open_tags:
                    continue
                open_tags.append(closing)
            out.append(part)
        texts.append("".join(out))
    return texts


# 10 texts a size already reach 1–49 pages; the 40-text corpus (~0.7 s a size, mostly the
# M20 fake's grapheme counting) is ``slow``. AC-F05-14 on the real faces: test_text_check.py.
@pytest.mark.parametrize("count", [10, pytest.param(40, marks=pytest.mark.slow)])
@pytest.mark.parametrize("size", [20, 28, 48])
def test_count_pages_equals_the_layout(size, count):
    for text in _corpus(size, count):
        body = tagged(text)
        lay = LineLayout(body, m20_context(size))
        pages = lay.all_pages()
        assert count_pages(body, m20_context(size)) == pages
        # Every grapheme is on exactly one page, in order.
        ranges = [(lay.page(k).first_glyph, lay.page(k).end_glyph) for k in range(pages)]
        assert ranges[0][0] == 0 and ranges[-1][1] == lay.glyph_count
        assert all(a[1] == b[0] for a, b in zip(ranges, ranges[1:]))
        for k in range(pages):
            for line in lay.page(k).lines:
                drawn = [g for g in line.glyphs if not g.hangs]
                assert all(g.right <= 920 for g in drawn) or len(drawn) == 1


def test_a_long_word_line():
    lay = layout("a" * 10_000)
    assert lay.all_pages() == 73                    # 218 lines of 46 (the last 18), 3 a page
    assert [len(line.glyphs) for line in lay.page(72).lines] == [46, 18]


def test_word_widths_are_cached_per_font(monkeypatch):
    assets = FixedFontAssets()
    font = assets.font(None, 28).font
    LineLayout(tagged("same " * 30), m20_context(assets=assets)).all_pages()
    assert font.calls == 2                          # "same" and " "
    monkeypatch.setattr(textlayout, "WORD_CACHE_ENTRIES", 4)
    cache = textlayout.word_cache(font)
    LineLayout(tagged("w1 w2 w3 w4 w5 w6"), m20_context(assets=assets)).all_pages()
    assert len(cache) == 4 and list(cache)[-1] == "w6"


# --- AC-F29-07: effects change no layout and no timing (TR-F29-02) ------------------------------
# F29 step 1 has no effect tags yet, so the effect bodies are built by hand: each effect tag
# becomes a private-use sentinel, the real parser parses the rest (F05's styles, pauses,
# speeds), and the sentinels are turned into ``Style.effect`` (stack semantics).

_FX_TAG = re.compile(r"\{(/?)(shake|wave|glitch)(?:=(small|medium|large))?\}")
_SENTINEL = 0xE000


def _fx_body(text: str) -> TaggedText:
    tags: list[re.Match] = []

    def sentinel(match: re.Match) -> str:
        tags.append(match)
        return chr(_SENTINEL + len(tags) - 1)

    stack: list[TextEffect] = []
    pieces: list = []
    for piece in tagged(_FX_TAG.sub(sentinel, text)).pieces:
        if isinstance(piece, VarMark):
            pieces.append(VarMark(piece.name, replace(piece.style,
                                                      effect=stack[-1] if stack else None)))
            continue
        if not isinstance(piece, Span):
            pieces.append(piece)
            continue
        chunk: list[str] = []
        for char in piece.text + "\0":
            code = ord(char) - _SENTINEL
            if char != "\0" and not 0 <= code < len(tags):
                chunk.append(char)
                continue
            if chunk:
                style = replace(piece.style, effect=stack[-1] if stack else None)
                if pieces and isinstance(pieces[-1], Span) and pieces[-1].style == style:
                    pieces[-1] = Span(pieces[-1].text + "".join(chunk), style)
                else:
                    pieces.append(Span("".join(chunk), style))
                chunk = []
            if char != "\0":
                close, kind, strength = tags[code].groups()
                if close:
                    stack.pop()
                else:
                    stack.append(TextEffect(kind, strength or "medium"))
    return TaggedText(tuple(pieces), tagged(_FX_TAG.sub("", text)).auto_next)


def _strip(body: TaggedText) -> TaggedText:
    """``body`` with every effect set to None, equal neighbours merged (AC-F29-06's T′)."""
    pieces: list = []
    for piece in body.pieces:
        if isinstance(piece, (Span, VarMark)):
            piece = replace(piece, style=replace(piece.style, effect=None))
        if (isinstance(piece, Span) and pieces and isinstance(pieces[-1], Span)
                and pieces[-1].style == piece.style):
            pieces[-1] = Span(pieces[-1].text + piece.text, piece.style)
        else:
            pieces.append(piece)
    return TaggedText(tuple(pieces), body.auto_next)


def _typed(lay: LineLayout) -> list[tuple]:
    """F05's typewriter at 40 cps on a 1/60 s fake clock, pressing at each wait: every event
    with its frame."""
    writer = Typewriter(lay, lambda: 40.0)
    events = [(0, e) for e in writer.run()]
    for frame in range(1, 20_000):
        if writer.state is TypeState.COMPLETE:
            return events
        if writer.state in (TypeState.WAIT_CLICK, TypeState.WAIT_PAGE):
            writer.press()
        events += [(frame, e) for e in writer.tick(1 / 60)]
    raise AssertionError("the line never completed")


def _laid(body: TaggedText, size: int) -> dict:
    lay = LineLayout(body, m20_context(size))
    pages = lay.all_pages()
    out: dict = {"pages": pages, "count": count_pages(body, m20_context(size)),
                 "height": [lay.page_height(k) for k in range(pages)],
                 "slots": [lay.timeline(k) for k in range(pages)], "lines": [], "stops": [],
                 "typed": _typed(LineLayout(body, m20_context(size)))}
    effects = []
    for k in range(pages):
        for line in lay.page(k).lines:
            out["lines"].append((line.top, line.pitch, line.baseline, line.first_glyph,
                                 line.end_glyph, tuple(replace(g, effect=None)
                                                       for g in line.glyphs)))
            # TextboxView._page_stops' tuples: (index, right, baseline) per glyph.
            out["stops"] += [(g.index, g.right, line.baseline) for g in line.glyphs]
            effects += [g.effect for g in line.glyphs]
    return out, effects


_WORDS150 = "".join(f"w{n % 10}xy " for n in range(30))          # 150 graphemes, words of 5
_WAVE150 = (_WORDS150[:30] + "{wave}" + _WORDS150[30:74] + "\n" + _WORDS150[75:120]
            + "{/wave}" + _WORDS150[120:])

FX_LAYOUT_ROWS = [
    ("L4", "I'm {wave}so{/wave} happy you came today!", 28),
    ("L5", "{shake=small}I just... {pause=0.6}{speed=0.2}don't{/speed} want you to leave."
           "{/shake}", 28),
    ("L6", "{glitch=large}You're not going anywhere.{/glitch}", 28),
    ("L7", "My name is {glitch}Hana{/glitch}.", 28),          # {var=hana_name} resolved
    ("L12", "{glitch}It was... {/glitch}{speed=instant}GONE.{/speed}", 28),
    ("L14", "{speed=0.2}It was... {/speed}{speed=instant}{shake=large}GONE.{/shake}{/speed}",
     28),
    ("wave150", _WAVE150, 28),
    ("size2_wave", "{size=2}{wave=large}Hi{/wave}{/size}", 48),
    ("cjk", "{glitch=large}" + "紙" * 40 + "{/glitch}", 28),
    ("family", "{glitch=large}👩‍👩‍👧 ok{/glitch}", 28),
    ("rtl", "{shake}שלום עולם{/shake}", 28),
    ("bang", "{shake}{speed=instant}BANG{/speed}{/shake}", 28),
]


@pytest.mark.parametrize("name, text, size", FX_LAYOUT_ROWS, ids=[r[0] for r in FX_LAYOUT_ROWS])
def test_ac_f29_07_layout_and_timing_do_not_change(name, text, size):
    body, plain = _fx_body(text), tagged(_FX_TAG.sub("", text))
    assert body != plain and _strip(body) == plain             # only the effects differ
    (with_fx, effects), (without, none) = _laid(body, size), _laid(plain, size)
    assert with_fx == without
    assert none == [None] * len(effects) and any(effects)      # the effect reached the glyphs
    if name == "L4":                                           # "so" is graphemes 4–5
        assert [i for i, e in enumerate(effects) if e] == [4, 5]
        assert effects[4] == TextEffect("wave")
    if name == "wave150":
        assert with_fx["pages"] >= 2
        assert [i for i, e in enumerate(effects) if e] == list(range(30, 119))
    if name == "bang":
        assert [(f, e) for f, e in with_fx["typed"] if isinstance(e, GlyphShown)] == [
            (0, GlyphShown(i, c)) for i, c in enumerate("BANG")]
