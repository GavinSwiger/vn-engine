"""F18 step 2 — the title card: ``CardPainter`` (``ui/builtin/title_card.py``) and the card in
``StageView``'s composite (``render/stage.py``).

AC-F18-10 (painter spy at scale 1 and 1.5: fill, tokens, centers, title-only form, a
150-character title cut to 2 lines with W110 once, the layout cache, ``fill_opacity`` 0.6);
UI-F18-01 (the card is part of the stage picture: an opaque card skips the stage,
transitions and the shake offset act on it, a restored stage drops it). F19 step 4:
AC-F19-21 (W110 on an ending card names the ending).
"""

import logging
from contextlib import contextmanager

import pygame
import pytest

from engine.core.constants import BUILTIN_POSITIONS, CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.render.stage import StageView
from engine.render.text import Face, FontSpec
from engine.runtime.commands import ShowStage, TitleCard, TransitionSpec
from engine.runtime.images import ImageIndex, SolidColor
from engine.runtime.stage import StageState
from engine.ui.builtin.title_card import CACHE_SIZE, CardPainter, CardStyle, w110_text
from tests.fakes.draw_spy import spy_draw_text
from tests.render.conftest import make_assets

pytestmark = pytest.mark.display

FILL = (0x2A, 0x1E, 0x26)
HEADING = (0xF0, 0xA0, 0xC0)
TITLE = (0xFF, 0xF4, 0xF8)
SEA = (0, 80, 240)
CARD = TitleCard("festival", "Chapter 2", "The Lantern Festival")


def bound(scale: float) -> Canvas:
    """A canvas bound to a fresh framebuffer at ``scale`` device pixels per unit."""
    w, h = round(CANVAS_SIZE[0] * scale), round(CANVAS_SIZE[1] * scale)
    surface = pygame.Surface((w, h))
    surface.fill(SEA)
    canvas = Canvas(make_assets(None))
    canvas.bind(surface, Viewport(CANVAS_SIZE[0], CANVAS_SIZE[1], w, h, 0, 0, w, h),
                RenderQuality.FINAL)
    return canvas


@contextmanager
def ui_log(caplog):
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        yield lambda: [(r.code, r.getMessage()) for r in caplog.records
                       if r.name == "vn.ui"]


# --- AC-F18-10 — the painter -----------------------------------------------------------------

def test_ac_f18_10_the_painter(caplog):
    # fill, tokens and centers at two scales, and the title-only form
    # Pitches: heading round(1.4 × 32) = 45, title round(1.4 × 56) = 78; the block
    # 45 + 16 + 78 = 139 is centered on y 360, so its top is 290.5.
    heading_font, title_font = FontSpec(None, 32), FontSpec(None, 56, Face.BOLD)
    rows = [  # card, [(text, font, color, center)]
        (CARD, [("Chapter 2", heading_font, HEADING, (640, 313.0)),
                ("The Lantern Festival", title_font, TITLE, (640, 390.5))]),
        (TitleCard("prologue", None, "Prologue"), [("Prologue", title_font, TITLE,
                                                    (640, 360.0))]),
    ]
    painter = CardPainter()
    assert painter.style == CardStyle() and painter.opaque
    for scale in (1.0, 1.5):
        for card, expected in rows:
            canvas = bound(scale)
            with pytest.MonkeyPatch.context() as mp, spy_draw_text(mp) as calls:
                painter.paint(canvas, card)
            assert [(c.text, c.font, c.color, c.pos) for c in calls] == expected
            assert all(c.options == {"anchor": "center"} for c in calls)
            for call in calls:                      # drawn centered, at device size
                left, top, w, h = call.bounds
                assert (left + w / 2, top + h / 2) == pytest.approx(call.pos)
                area = canvas.surface.subsurface(canvas.rect_to_px(call.bounds))
                assert pygame.mask.from_threshold(area, call.color,
                                                  (8, 8, 8, 255)).count() > 0
            surface = canvas.surface
            corners = [(0, 0), (surface.get_width() - 1, surface.get_height() - 1)]
            assert {tuple(surface.get_at(p))[:3] for p in corners} == {FILL}
    # long titles: cut to two lines with W110 once
    spaced = " ".join(["lantern"] * 19)[:150]
    unspaced = "L" * 150
    assert len(spaced) == len(unspaced) == 150
    for title in (spaced, unspaced):
        for dev in (True, False):
            caplog.clear()
            painter = CardPainter(dev=dev)
            card = TitleCard("river", None, title)
            with ui_log(caplog) as records:
                for scale in (1.0, 1.5, 1.0):
                    canvas = bound(scale)
                    layout = painter.layout(canvas, card)
                    painter.paint(canvas, card)
                painter.layout(canvas, TitleCard("river", "H", title))   # same chapter
                lines = [line.text for line in layout.lines]
                assert len(lines) == 2 and lines[1].endswith("…") and layout.cut
                assert layout.kept == len(lines[0]) + len(lines[1]) - 1
                assert records() == ([("W110", w110_text(card, 56, layout.kept))]
                                     if dev else [])
    text = w110_text(TitleCard("festival", None, "x"), 56, 67)
    assert text == ('the title of chapter "festival" needs more than 2 lines on its card at '
                    'size 56, so it is cut with "…". Shorten it to about 60 characters.')
    assert w110_text(TitleCard("bad", None, "x", kind="ending"), 56, 4).startswith(
        'the title of ending "bad" needs') and w110_text(
        TitleCard("bad", None, "x"), 56, 4).endswith("about 10 characters.")
    # the layout cache keeps four
    painter = CardPainter()
    canvas = bound(0.25)
    laid: list[str] = []
    real = CardPainter._layout
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(CardPainter, "_layout",
                   lambda self, c, card: laid.append(card.name) or real(self, c, card))
        painter.paint(canvas, CARD)
        painter.paint(bound(1.0), CARD)                     # a hit, at any scale
        assert laid == ["festival"]
        cards = [TitleCard(f"c{i}", None, f"T{i}") for i in range(CACHE_SIZE)]
        for card in cards:                                  # CARD is evicted by the 4th
            painter.layout(canvas, card)
        painter.layout(canvas, cards[0])
        painter.layout(canvas, CARD)
    assert laid == ["festival", "c0", "c1", "c2", "c3", "festival"]


# --- UI-F18-01 — the card in the stage composite ---------------------------------------------

def view_of(painter: CardPainter | None) -> StageView:
    index = ImageIndex({"bg sea": SolidColor(SEA)})
    return StageView(make_assets(None), index, art_height=720, positions=BUILTIN_POSITIONS,
                     empty_color=(0, 0, 0), card_painter=painter)


def drawn(view: StageView, offset=(0, 0)) -> pygame.Surface:
    canvas = bound(0.25)                                    # 320×180
    canvas.surface.fill((255, 0, 255))
    view.draw(canvas, offset)
    return canvas.surface


def at(surface: pygame.Surface, point=(4, 4)) -> tuple[int, int, int]:
    return tuple(surface.get_at(point))[:3]


def test_ui_f18_01_opacity_and_an_opaque_card_skips_the_stage():
    sea = StageState("bg sea")
    for opacity, expected in ((1.0, FILL), (0.6, tuple(round(f * 0.6 + s * 0.4)
                                                       for f, s in zip(FILL, SEA)))):
        view = view_of(CardPainter(CardStyle(fill_opacity=opacity)))
        with pytest.MonkeyPatch.context() as mp:
            backgrounds = []
            real = StageView._draw_background
            mp.setattr(StageView, "_draw_background",
                       lambda self, *a: backgrounds.append(a) or real(self, *a))
            view.show(ShowStage(sea, card=CARD))
            pixel = at(drawn(view))
        assert all(abs(p - e) <= 1 for p, e in zip(pixel, expected)), (opacity, pixel)
        assert len(backgrounds) == (0 if opacity == 1.0 else 1)
        assert view.card == CARD and view.stage == sea
    view = view_of(None)                                    # no painter: no card drawn
    view.show(ShowStage(sea, card=CARD))
    assert at(drawn(view)) == SEA


def test_ui_f18_01_transitions_shake_and_restore_act_on_the_card():
    fade = TransitionSpec("fade", "fade", "sid-1", 1.0, None, None, 0.1, False, None)
    view = view_of(CardPainter())
    sea = StageState("bg sea")
    view.show(ShowStage(sea))
    assert at(drawn(view)) == SEA
    for card, start, end in ((CARD, SEA, FILL), (None, FILL, SEA)):  # in, then out
        view.show(ShowStage(sea, transition=fade, card=card))
        for _ in range(6):                                  # PREPARING: the old picture
            assert at(drawn(view)) == start
            if view._run.running:
                break
        view.advance(0.25)
        assert at(drawn(view)) == tuple(round(c * 0.5) for c in start)  # half to black
        view.advance(0.25)
        assert at(drawn(view)) == (0, 0, 0)
        view.advance(0.25)
        assert at(drawn(view)) == tuple(round(c * 0.5) for c in end)
        view.finish()
        assert at(drawn(view)) == end and view.finished_drawn and view.card == card
    wipe = TransitionSpec("wipe", "wipeleft", "sid-2", 1.0, None, None, 0.1, False, "left",
                          calm=False)
    view.show(ShowStage(sea, transition=wipe, card=CARD), reduce=True)   # F09's reduction
    assert view._run.kind_name == "dissolve" and view.card == CARD
    view.cancel()
    view.show(ShowStage(sea, card=CARD))
    shaken = drawn(view, (10, 0))                           # F09's shake offset moves it
    assert at(shaken, (9, 4)) == (255, 0, 255) and at(shaken, (10, 4)) == FILL
    view.show(ShowStage(sea, restored=True, card=CARD))     # a restore never has a card
    assert view.card is None and at(drawn(view)) == SEA


# --- AC-F19-21 — W110 on an ending card (F19 step 4) -------------------------------------------

def test_ac_f19_21_w110_names_the_ending(caplog):
    """A 150-character title on an ending card: 2 lines ending in "…", W110 once, naming
    ``ending "sad"`` (``TitleCard.kind``; the text is ``w110_text``'s, 06 D4). A chapter card
    with the same title still gives the chapter text."""
    title = "L" * 150
    painter = CardPainter(dev=True)
    ending = TitleCard("sad", None, title, kind="ending")
    chapter = TitleCard("sad", None, title)
    assert chapter.kind == "chapter"
    with ui_log(caplog) as records:
        for scale in (1.0, 1.5):
            canvas = bound(scale)
            with pytest.MonkeyPatch.context() as mp, spy_draw_text(mp) as calls:
                painter.paint(canvas, ending)
            assert len(calls) == 2 and calls[1].text.endswith("…")
        layout = painter.layout(canvas, ending)
        assert records() == [("W110", w110_text(ending, 56, layout.kept))]
        [(_, text)] = records()
        assert 'ending "sad"' in text and "chapter" not in text
        painter.paint(canvas, chapter)
        assert records()[1:] == [("W110", w110_text(chapter, 56, layout.kept))]
        assert 'chapter "sad"' in records()[1][1]
