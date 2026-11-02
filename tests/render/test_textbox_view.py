"""F05 step 6 — ``TextboxView`` on screen: the box, the name tab, typing, the indicators, the
bob, frame images, and the same glyph places at every window size. AC-F05-13 (geometry),
15, 25, 26, 28, 29, 30, 31, 32.

Pixel probes are window pixels of App A frames (``tests/fakes/text_app.py``; at 1280×720 one
unit is one pixel), with ``06`` §0.6's tolerances: flat fills ± 1, ink cores ± 2, positions
± 1 px.
"""

import math
import random
from pathlib import Path

import pygame
import pytest

from engine.core.config_schema import TextboxTheme
from engine.render.assets import Face, Synth
from engine.render.canvas import Canvas, RenderQuality
from engine.render.textbox import TextboxView, _PageDraw, _TypedLayer, bob_offset, box_geometry
from engine.render.textlayout import LineLayout
from engine.render.typewriter import TypeState
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.text_app import Session, make_text_game

pytestmark = pytest.mark.display

BORDER = (0xF0, 0xA0, 0xC0)
TAB = (0xFF, 0xE6, 0xF0)
BERRY = (0xA0, 0x28, 0x60)
BLACK = (0, 0, 0)
FPS = 60


def session(tmp_path, *, size=(1280, 720), **game) -> Session:
    return Session(make_text_game(tmp_path / "game", **game), size=size)


def close(a, b, tol=1) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def over(fg, a, bg):
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg, bg))


def complete(s: Session):
    yield from s.until(lambda: s.textbox is not None and s.textbox.typer is not None
                       and s.textbox.typer.state is TypeState.COMPLETE)
    yield


def ink_box(s: Session, rect, color, tol=40):
    """Bounding box (x0, y0, x1, y1) of pixels within ``tol`` per channel of ``color``."""
    x, y, w, h = rect
    found = [(px, py) for py in range(y, y + h) for px in range(x, x + w)
             if close(s.px(px, py), color, tol)]
    if not found:
        return None
    xs, ys = [p[0] for p in found], [p[1] for p in found]
    return min(xs), min(ys), max(xs), max(ys)


def darkest(s: Session, rect):
    x0, y0, w, h = rect
    return min((s.px(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)), key=sum)


# --- AC-F05-13 — the geometry function (UI-F05-02's table) ----------------------------------------

@pytest.mark.parametrize("size, pitch, height, top", [
    (20, 28, 184, 504), (28, 39, 184, 504), (38, 53, 215, 473), (42, 59, 216, 472),
    (48, 67, 216, 472)])
def test_ac13_box_geometry(size, pitch, height, top):
    g = box_geometry(TextboxTheme(), size)
    assert (g.pitch, g.box[3], g.top) == (pitch, height, top)
    assert g.box[0] == 140 and g.box[2] == 1000 and g.box[1] + g.box[3] == 688
    assert g.area == (180, top + 28, 920, height - 56)


def test_bob_offset_curve():
    assert bob_offset(0) == 0
    assert math.isclose(bob_offset(0.3), 2.0) and math.isclose(bob_offset(0.6), 4.0)
    assert abs(bob_offset(1.2)) < 1e-9
    assert max(bob_offset(t / 100) for t in range(300)) <= 4.0


# --- AC-F05-25 — the box ---------------------------------------------------------------------------

def test_ac25_the_box_over_black(tmp_path):
    s = session(tmp_path, S="x")
    seen = {}

    def script(s):
        seen["before"] = []
        while not s.said:
            if s.textbox is not None:
                seen["before"].append(s.px(150, 600))
            yield
        yield from complete(s)
        seen["px"] = {p: s.px(*p) for p in [
            (150, 600), (640, 504), (640, 505), (140, 600), (1139, 600), (640, 687),
            (640, 502), (640, 689), (138, 600), (1141, 600), (141, 505), (640, 450)]}

    s.play(script)
    px = seen["px"]
    assert close(px[(150, 600)], (0xCC, 0xC3, 0xC6))
    for p in [(640, 504), (640, 505), (140, 600), (1139, 600), (640, 687)]:
        assert close(px[p], BORDER), p
    for p in [(640, 502), (640, 689), (138, 600), (1141, 600), (141, 505), (640, 450)]:
        assert px[p] == BLACK, p
    assert all(c == BLACK for c in seen["before"])      # no box before the first line


def test_ac25_the_box_over_white(tmp_path):
    s = session(tmp_path, D='scene white⏎    "x"', T='image white = "#FFFFFF"')

    def script(s):
        yield from complete(s)
        s.seen = s.px(150, 600)

    s.play(script)
    assert close(s.seen, (0xFF, 0xF6, 0xF9))


@pytest.mark.parametrize("size, border, background", [(38, 473, 472), (48, 472, 471)])
def test_ac25_the_box_grows_with_the_text_size(tmp_path, size, border, background):
    s = session(tmp_path, S="x", config=f"[theme.textbox]\ntext_size = {size}\n")

    def script(s):
        yield from complete(s)
        s.seen = (s.px(640, border), s.px(640, background))

    s.play(script)
    assert close(s.seen[0], BORDER) and s.seen[1] == BLACK


def test_ac25_narration_and_dialogue_boxes_match_and_stay_between_lines(tmp_path):
    s = session(tmp_path, D='"x"⏎    d "x"')
    seen = {"between": []}

    def rows(s):
        return bytes(b for y in range(506, 688) for x in range(300, 1140, 7)
                     for b in s.px(x, y))

    def script(s):
        yield from complete(s)
        seen["narration"] = rows(s)
        s.key(pygame.K_SPACE)
        for _ in range(3):
            yield
            seen["between"].append(s.px(150, 600))
        yield from complete(s)
        seen["dialogue"] = rows(s)

    s.play(script)
    assert seen["narration"] == seen["dialogue"]
    assert all(close(c, (0xCC, 0xC3, 0xC6)) for c in seen["between"])


# --- AC-F05-26 — the name tab -----------------------------------------------------------------------

def test_ac26_the_name_tab(tmp_path):
    s = session(tmp_path, D='hana "x"⏎    d "x"')
    seen = {}

    def script(s):
        yield from complete(s)
        seen["px"] = {p: s.px(*p) for p in [(172, 500), (275, 505), (300, 505), (160, 500),
                                             (290, 470), (172, 460)]}
        seen["ink"] = darkest(s, (170, 466, 110, 36))
        seen["box"] = ink_box(s, (166, 464, 116, 40), BERRY)
        s.key(pygame.K_SPACE)
        yield from s.until_line("x")
        yield from s.until(lambda: s.textbox.line.speaker == "d")
        yield from complete(s)
        seen["d"] = darkest(s, (170, 466, 110, 36))

    s.play(script)
    px = seen["px"]
    assert close(px[(172, 500)], TAB) and close(px[(275, 505)], TAB)
    assert close(px[(300, 505)], BORDER)
    assert px[(160, 500)] == BLACK and px[(290, 470)] == BLACK and px[(172, 460)] == BLACK
    assert close(seen["ink"], BERRY, 2)
    x0, y0, x1, y1 = seen["box"]
    assert abs((x0 + x1) / 2 - 224) <= 2 and abs((y0 + y1) / 2 - 484) <= 2
    assert close(seen["d"], (0x1E, 0x4A, 0x9C), 2)


def test_ac26_long_and_missing_names(tmp_path, monkeypatch):
    s = session(tmp_path, D='b "x"⏎    w "x"⏎    "x"⏎    thought "x"⏎    e "x"',
                T='define b = Character("Bartholomew Ashcroft")⏎define w = Character("'
                  + "W" * 40 + '")⏎define e = Character(name_from="en")⏎default en = ""')
    seen = []
    with spy_draw_text(monkeypatch) as calls:
        def script(s):
            for _ in range(5):
                yield from complete(s)
                tab = s.textbox.view._names
                seen.append((s.textbox.line.speaker, s.px(655, 500), s.px(668, 500),
                             s.px(172, 500)))
                s.key(pygame.K_SPACE)
                yield
            yield

        s.play(script)
    texts = [c.text for c in calls]
    assert "Bartholomew Ashcroft" in texts
    cut = [c for c in calls if c.text.startswith("WWW")]
    assert cut and cut[0].text.endswith("…")
    font = s.assets.font(None, 28, bundled=Face.BOLD).font
    assert font.size(cut[0].text)[0] <= 460
    by = {speaker: rest for speaker, *rest in seen}
    assert close(by["w"][0], TAB) and by["w"][1] == BLACK            # tab spans 164–663
    for speaker in (None, "thought", "e"):                          # no tab
        assert by[speaker][2] == BLACK, speaker
    assert all(c.font.bundled is Face.BOLD for c in cut)


def test_ac26_a_name_from_change_shows_on_the_next_line(tmp_path):
    s = session(tmp_path, D='r "x"⏎    $ rn = "Hana"⏎    r "y"',
                T='define r = Character(name_from="rn")⏎default rn = "???"')

    def script(s):
        yield from complete(s)
        first = s.textbox.view.name_tab(s.textbox.line.name, s.textbox.geometry).text
        s.key(pygame.K_SPACE)
        yield from s.until_line("y")
        yield from complete(s)
        s.seen = (first, s.textbox.view.name_tab(s.textbox.line.name, s.textbox.geometry).text)

    s.play(script)
    assert s.seen == ("???", "Hana")


# --- AC-F05-29 — the indicators ------------------------------------------------------------------

def _anchor(s: Session):
    tb = s.textbox
    page = tb.layout.page(tb.typer.page)
    return tb.view.indicator_anchor(page, tb._line_id, tb.typer.shown, tb.geometry)


def test_ac29_line_indicator_place_and_shape(tmp_path):
    s = session(tmp_path, S="abc")

    def script(s):
        yield from complete(s)
        x, baseline = _anchor(s)
        tb = s.textbox
        glyph = tb.layout.page(0).lines[0].glyphs[-1]
        s.seen = (x, baseline, 180 + glyph.right + 8,
                  ink_box(s, (round(x) - 4, round(baseline) - 18, 30, 24), BERRY, 90),
                  s.px(round(x) + 8, round(baseline) - 9))

    s.play(script)
    x, baseline, expected_x, box, centre = s.seen
    assert abs(x - expected_x) < 1e-6
    x0, y0, x1, y1 = box
    assert abs(x0 - round(x)) <= 1 and abs((y1 + 1) - round(baseline)) <= 1
    assert abs((x1 - x0 + 1) - 16) <= 1 and abs((y1 - y0 + 1) - 12) <= 2
    assert close(centre, BERRY, 2)


def test_ac29_no_indicator_while_typing(tmp_path):
    s = session(tmp_path, S="a" * 40)

    def script(s):
        yield from s.until(lambda: s.said)
        for _ in range(10):
            yield
        assert s.textbox.typer.state is TypeState.TYPING
        s.seen = ink_box(s, (140, 506, 1000, 182), BERRY, 2)

    s.play(script)
    assert s.seen is None


def test_ac29_page_indicator_two_triangles(tmp_path):
    s = session(tmp_path, S="a\\nb\\nc\\nd")

    def script(s):
        yield from s.until(lambda: s.textbox is not None and s.textbox.typer is not None
                           and s.textbox.typer.state is TypeState.WAIT_PAGE)
        yield
        x, baseline = _anchor(s)
        s.seen = (x, baseline, ink_box(s, (round(x) - 4, round(baseline) - 28, 30, 34), BERRY, 90),
                  s.px(round(x) + 8, round(baseline) - 11))
        s.key(pygame.K_SPACE)                       # next page in the same frame
        yield
        page = s.textbox.layout.page(s.textbox.typer.page)
        s.page_change = (s.textbox.typer.page, s.textbox.typer.shown, page.first_glyph)

    s.play(script)
    x, baseline, box, gap = s.seen
    x0, y0, x1, y1 = box
    assert abs((y1 - y0 + 1) - 22) <= 2 and abs((x1 - x0 + 1) - 16) <= 1
    assert not close(gap, BERRY, 20)
    assert s.page_change == (1, 4, 3)               # "d" shown in the change frame


def test_ac29_empty_line_indicator_at_the_left_edge(tmp_path):
    s = session(tmp_path, S="")

    def script(s):
        yield from complete(s)
        s.seen = _anchor(s)

    s.play(script)
    x, baseline = s.seen
    assert x == 180
    assert 532 < baseline < 532 + 39


def test_ac29_hanging_spaces_clamp_the_indicator(tmp_path):
    s = session(tmp_path, S="a" * 60 + " " * 60)

    def script(s):
        yield from complete(s)
        s.seen = _anchor(s)

    s.play(script)
    assert s.seen[0] <= 180 + 920 + 8


# --- AC-F05-30 — the bob ---------------------------------------------------------------------------

def _indicator_rows(s: Session, frames: int):
    rows = []
    for _ in range(frames):
        x, baseline = _anchor(s)
        box = ink_box(s, (round(x) - 2, round(baseline) - 16, 22, 24), BERRY, 2)
        rows.append(box[3] + 1 - round(baseline))   # offset of the ink bottom below rest
        yield
    s.rows = rows


def test_ac30_the_bob(tmp_path):
    s = session(tmp_path, S="x")

    def script(s):
        yield from s.until(lambda: s.textbox is not None and s.textbox.indicator_kind())
        yield
        yield from _indicator_rows(s, 80)

    s.play(script)
    rows = s.rows
    assert rows[0] == 0
    assert abs(rows[18] - 2) <= 1 and abs(rows[36] - 4) <= 1 and abs(rows[72]) <= 1
    assert max(rows) <= 4


def test_ac30_reduce_motion_holds_it_at_rest(tmp_path):
    s = session(tmp_path, S="x")

    def script(s):
        yield from s.until(lambda: s.textbox is not None)
        s.textbox.settings.reduce_motion = True
        yield from s.until(lambda: s.textbox.indicator_kind())
        yield
        yield from _indicator_rows(s, 180)

    s.play(script)
    assert set(s.rows) == {0}


def test_ac30_hidden_or_covered_stops_the_clock(tmp_path):
    from engine.ui.screen import Screen

    class Cover(Screen):
        opaque = True

    s = session(tmp_path, S="x")

    def script(s):
        yield from s.until(lambda: s.textbox is not None and s.textbox.indicator_kind())
        for _ in range(10):
            yield
        t = s.textbox._bob_t
        cover = Cover()
        s.app.screens.push(cover)
        for _ in range(30):
            yield
        s.covered = (t, s.textbox._bob_t)
        s.app.screens.remove(cover)

    s.play(script)
    assert s.covered[0] == s.covered[1]


# --- AC-F05-31 — faces and styles on screen ---------------------------------------------------------

def test_ac31_faces_and_styles(tmp_path, monkeypatch):
    s = session(tmp_path, S="r {b}b{/b} {i}i{/i} {b}{i}bi{/i}{/b} {color=#9a1c14}llll{/color} "
                            "{size=2}S{/size}")
    requests = []
    real_build = TextboxView.build_glyphs

    def build(self, canvas, page, geometry, scale):
        real_font = self.assets.font

        def font(ref, size_px, **kw):
            requests.append((ref, kw.get("bundled"), kw.get("synth")))
            return real_font(ref, size_px, **kw)

        self.assets.font = font
        try:
            return real_build(self, canvas, page, geometry, scale)
        finally:
            del self.assets.font

    monkeypatch.setattr(TextboxView, "build_glyphs", build)

    def script(s):
        yield from complete(s)
        tb = s.textbox
        line = tb.layout.page(0).lines[0]
        s.line = line
        ls = [g for g in line.glyphs if g.text == "l"]
        x0 = round(180 + ls[0].x)
        x1 = round(180 + ls[-1].right)
        s.llll = darkest(s, (x0, round(532 + line.top), x1 - x0, line.pitch))

    s.play(script)
    faces = {(bundled, synth) for ref, bundled, synth in requests}
    assert faces == {(Face.REGULAR, Synth.NONE), (Face.BOLD, Synth.NONE),
                     (Face.ITALIC, Synth.NONE), (Face.BOLD_ITALIC, Synth.NONE)}
    assert close(s.llll, (0x9A, 0x1C, 0x14), 2)
    assert s.line.pitch == 78


# --- AC-F05-32 — a frame image ----------------------------------------------------------------------

def _frame_png(root: Path) -> None:
    image = pygame.Surface((96, 96))
    image.fill((0, 255, 0))
    image.fill((0, 0, 255), (24, 24, 48, 48))
    for x, y in ((0, 0), (72, 0), (0, 72), (72, 72)):
        image.fill((255, 0, 0), (x, y, 24, 24))
    (root / "gui").mkdir(exist_ok=True)
    pygame.image.save(image, str(root / "gui" / "textbox.png"))


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_ac32_a_frame_image(tmp_path, size):
    root = make_text_game(tmp_path / "game", S="x", config='[theme.textbox]\n'
                          'frame_image = "gui/textbox.png"\nfill_opacity = 1.0\n')
    _frame_png(root)
    s = Session(root, size=size)
    k = size[0] / 1280

    def script(s):
        yield from complete(s)
        s.seen = {p: s.px(round(p[0] * k), round(p[1] * k))
                  for p in [(150, 515), (640, 515), (640, 600)]}
        s.corner = [x for x in range(round(140 * k), round(200 * k))
                    if s.px(x, round(510 * k)) == (255, 0, 0)]
        s.border = ink_box(s, (round(140 * k), round(504 * k), round(1000 * k), 8), BORDER, 3)

    s.play(script)
    assert s.seen[(150, 515)] == (255, 0, 0) and s.seen[(640, 515)] == (0, 255, 0)
    assert s.seen[(640, 600)] == (0, 0, 255)
    assert len(s.corner) == round(24 * k)
    assert s.border is None


def test_ac32_frame_opacity_and_a_vanished_frame(tmp_path):
    root = make_text_game(tmp_path / "game", D='"x"⏎    "y"', config='[theme.textbox]\n'
                          'frame_image = "gui/textbox.png"\nfill_opacity = 0.5\n')
    _frame_png(root)
    s = Session(root)

    def script(s):
        yield from complete(s)
        s.half = s.px(640, 600)
        view = s.textbox.view
        real = s.assets.image

        def image(ref):                             # the file went away after the launch
            found = real(ref)
            from engine.render.assets import ImageRef
            return ImageRef(ref, (256, 256), True, ("placeholder", ref))

        s.assets.image = image
        view._box_key = None                        # the next rebuild sees the placeholder
        s.key(pygame.K_SPACE)
        yield from s.until_line("y")
        yield from complete(s)
        s.after = (s.px(640, 504), s.px(150, 600),
                   ink_box(s, (140, 504, 1000, 184), (255, 0, 255), 10))

    s.play(script)
    assert close(s.half, (0, 0, 0x80), 2)
    assert close(s.after[0], BORDER) and close(s.after[1], (0x7F, 0x7A, 0x7C), 2)
    assert s.after[2] is None


# --- AC-F05-15, 28 — the same places at every window size; typing changes only new glyphs -----------

LONG_LINE = " ".join(["The lanterns drifted {b}slowly{/b} down the {i}river{/i}, "
                      "{color=#9a1c14}red{/color} and gold."] * 12)


@pytest.mark.parametrize("size", [(640, 360), (1280, 720), (1920, 1080), (2560, 1440),
                                  (3840, 2160)])
def test_ac15_glyph_places_at_every_window_size(tmp_path, monkeypatch, size):
    s = session(tmp_path, S=LONG_LINE, size=size, config="[textbox]\ncps = 0\n")
    scale = size[0] / 1280
    sizes = []
    real_font = s.assets.font

    def font(ref, size_px, **kw):
        sizes.append(size_px)
        return real_font(ref, size_px, **kw)

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        s.assets.font = font
        tb = s.textbox
        tb.view.forget_line()
        yield
        page = tb.layout.page(0)
        draw = tb.view._page_draw
        s.result = (page, draw, [l.first_glyph for l in page.lines], tb.layout.all_pages())

    s.play(script)
    page, draw, firsts, pages = s.result
    assert pages >= 3
    if scale == 0.5:
        assert 14 in sizes
    by_index = dict(zip(draw.indices, draw.entries))
    for line in page.lines:
        for glyph in line.glyphs:
            if glyph.index not in by_index:
                continue
            surface, (x, y) = by_index[glyph.index]
            assert abs(x - math.floor((180 + glyph.x) * scale + 0.5)) <= 1


def test_ac15_breaks_do_not_depend_on_the_window(tmp_path):
    breaks = []
    for size in [(640, 360), (1920, 1080)]:
        s = session(tmp_path / f"{size[0]}", S=LONG_LINE, size=size, config="[textbox]\ncps = 0\n")

        def script(s):
            yield from s.until(lambda: s.said)
            yield
            layout = s.textbox.layout
            s.lines = [[(l.first_glyph, l.end_glyph) for l in layout.page(k).lines]
                       for k in range(layout.all_pages())]

        s.play(script)
        breaks.append(s.lines)
    assert breaks[0] == breaks[1]


def stray_pixel(a: pygame.Surface, b: pygame.Surface, allowed) -> tuple[int, int] | None:
    """The first pixel (x, y) that differs between frames ``a`` and ``b`` outside the
    ``allowed`` rects, or None. Done with SDL blits (|b − a| per channel, the allowed rects
    zeroed) and one C-speed byte scan, not a Python loop over 921,600 pixels."""
    diff, back = b.copy(), a.copy()
    diff.blit(a, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
    back.blit(b, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
    diff.blit(back, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    for rect in allowed:
        diff.fill(BLACK, rect)
    data = pygame.image.tobytes(diff, "RGB")
    first = len(data) - len(data.lstrip(b"\0"))
    if first == len(data):
        return None
    pixel = first // 3
    return pixel % diff.get_width(), pixel // diff.get_width()


def test_ac28_typing_changes_only_the_new_glyphs(tmp_path):
    s = session(tmp_path, S="Hello there, the lanterns drift.")
    seen = {"pairs": 0, "stray": []}

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        rects = {}
        for line in s.textbox.layout.page(0).lines:
            for glyph in line.glyphs:
                rects[glyph.index] = pygame.Rect(math.floor(180 + glyph.x) - 3,
                                                 round(532 + line.top),
                                                 math.ceil(glyph.advance) + 6, line.pitch)
        prev = None
        while s.textbox.typer.state is TypeState.TYPING:     # the indicator frame is left out
            shown = s.textbox.typer.shown
            frame = s.fb.copy()
            if prev is not None:
                allowed = [rects[i] for i in range(prev[1], shown)]
                point = stray_pixel(prev[0], frame, allowed)
                if point is not None:
                    seen["stray"].append((point, prev[1], shown))
                seen["pairs"] += 1
            prev = (frame, shown)
            yield

    s.play(script)
    assert seen["stray"] == []
    assert seen["pairs"] >= 20


# --- F05 step 9 perf fix — the typed layer draws what draw_glyphs draws ---------------------------

def _noise(size, seed=5) -> pygame.Surface:
    rng = random.Random(seed)
    return pygame.image.frombytes(rng.randbytes(size[0] * size[1] * 3), size, "RGB")


# Italic "ffff"/"fjord", "AVAWAY", and bold italic ink over their neighbours: spills.
CACHE_SCRIPT = ('define hana = Character("Hana", color="#b03070")\n'
                'label start:\n    scene bg noise\n'
                '    hana "The lanterns {b}drifted{/b} down the {i}river{/i}, '
                '{color=#9a1c14}red{/color} and gold.\\n{i}ffff fjord{/i} AVAWAY\\nc\\n'
                'd {b}{i}Wolf{/i}{/b}\\n{size=2}Wf{/size} e"\n'
                '    "End."\n')


def test_typed_layer_matches_uncached_draw_through_typing_page_break_and_restore(tmp_path):
    """Every frame of a two-page line typed at 120 cps, its page break, and its restore: the
    say window drawn through the typed layer equals the uncached box-then-glyphs draw, byte
    for byte, over a noise background (the translucent box blends every pixel)."""
    root = make_text_game(tmp_path / "game", script=CACHE_SCRIPT,
                          config="[textbox]\ncps = 120\n")
    (root / "images" / "bg").mkdir(parents=True)
    pygame.image.save(_noise((1280, 720), 9), str(root / "images" / "bg" / "noise.png"))
    s = Session(root)
    noise = _noise((1280, 720))
    seen = {"frames": 0, "pages": set(), "restored": 0, "shown": set(), "spills": 0}

    def draw_both(s):
        tb = s.textbox
        view = tb.view
        out = []
        for cached in (True, False):
            surface = noise.copy()
            canvas = Canvas(s.assets)
            canvas.bind(surface, s.app.canvas.viewport, RenderQuality.FINAL)
            if not cached:
                view.draw_typed = view.draw_glyphs          # the uncached path, this draw only
            try:
                tb._draw_box(canvas)
            finally:
                if not cached:
                    del view.draw_typed
            out.append(pygame.image.tobytes(surface, "RGB"))
        assert out[0] == out[1], (tb.typer.page, tb.typer.shown, tb.typer.state)
        assert out[0] != pygame.image.tobytes(noise, "RGB")
        seen["frames"] += 1
        seen["pages"].add(tb.typer.page)
        seen["shown"].add((tb.typer.page, tb.typer.shown))
        seen["restored"] += bool(tb.line.restored)
        seen["spills"] = max(seen["spills"], len(view._layer.spills))

    def script(s):
        yield from s.until(lambda: s.said)
        state = s.app.story.checkpoint()
        tb = s.textbox
        while tb.typer.state is not TypeState.COMPLETE:
            draw_both(s)
            if tb.typer.state is TypeState.WAIT_PAGE:
                s.key(pygame.K_SPACE)                       # the page break
            yield
        draw_both(s)
        assert tb.view._layer is not None and tb.view._layer.count > 0
        outcome = s.app.story.restore(state)
        assert outcome.result.name == "OK"
        yield from s.until(lambda: s.textbox.line.restored)
        for _ in range(3):
            draw_both(s)
            yield

    s.play(script)
    assert seen["pages"] == {0, 1} and seen["restored"] == 3
    assert seen["spills"] > 0                           # the spill path was drawn too
    assert len(seen["shown"]) > 20                      # many typing steps were compared


def test_typed_layer_spills_glyphs_that_ink_over_earlier_ones_or_leave_the_layer():
    """Overlapping translucent "glyphs" and ones outside the layer, appended a few at a time:
    the layer plus its spills give the bytes of blitting each in order."""
    pygame.init()
    rng = random.Random(3)
    entries, indices = [], []
    for i in range(40):
        surface = pygame.Surface((rng.randint(4, 24), rng.randint(4, 24)), pygame.SRCALPHA)
        for _ in range(6):
            surface.fill((rng.randrange(256), rng.randrange(256), rng.randrange(256),
                          rng.randrange(1, 256)),
                         (rng.randrange(surface.get_width()), rng.randrange(surface.get_height()),
                          rng.randint(1, 8), rng.randint(1, 8)))
        entries.append((surface, (rng.randint(-10, 110), rng.randint(-10, 50))))
        indices.append(i)
    draw = _PageDraw(entries, indices)
    rect = pygame.Rect(0, 0, 100, 40)
    layer = None
    for k in (1, 2, 7, 8, 20, 21, 40):
        if layer is None:
            layer = _TypedLayer(draw, rect)
        layer.add(k)
        cached, direct = _noise((130, 70)), _noise((130, 70))
        layer.blit(cached)
        direct.blits(entries[:k], doreturn=False)
        assert pygame.image.tobytes(cached, "RGB") == pygame.image.tobytes(direct, "RGB"), k
    assert layer.spills and layer.bounds is not None
    again = _TypedLayer(draw, rect, layer)                  # reuses the cleared surface
    assert again.surface is layer.surface and again.count == 0
    again.add(40)
    cached, direct = _noise((130, 70)), _noise((130, 70))
    again.blit(cached)
    direct.blits(entries, doreturn=False)
    assert pygame.image.tobytes(cached, "RGB") == pygame.image.tobytes(direct, "RGB")
