"""F65 round 3, the device looks' own faces: the terminal draws in the bundled Noto Sans Mono,
a letter's and a pigeon note's heading and signature in Noto Serif (Italic), a game with its
own text font keeps it, and a thought's arrival notice reads in italics."""

from types import SimpleNamespace

import pygame

from engine.app.inbox import AppInboxPort
from engine.core.config_schema import ThemeConfig
from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.render.text import Face
from engine.render.textlayout import FaceSet, FaceSource
from engine.ui.builtin.inbox_view import InboxView
from engine.ui.builtin.kind_page import KindPage
from engine.ui.devicelook import notice_skin
from engine.ui.focus import FocusScope
from engine.ui.notice import NoticeLayer, notice_style
from engine.ui.paint import Painter
from engine.ui.theme import Words, measure_with, plain_theme
from engine.ui.widgets import Look
from tests.render.conftest import make_assets
from tests.ui.test_device_looks import SLOT, FakeCodex, delivery

OWN = FaceSet({face: FaceSource("fonts/Own.ttf", face) for face in (
    Face.REGULAR, Face.BOLD, Face.ITALIC, Face.BOLD_ITALIC)})


def _fonts(look, faces=None):
    """The fonts the Inbox draws ``look``'s message with, and its laid-out pages."""
    theme = plain_theme(ThemeConfig()) if faces is None else plain_theme(ThemeConfig(),
                                                                          faces=faces)
    assets = make_assets(None)
    ui = SimpleNamespace(theme=theme, words=Words(), assets=assets, reduce_motion=True)
    codex = FakeCodex((delivery(look),), {"sender": "Sender"})
    port = AppInboxPort(lambda: codex, lambda: "You")
    host = SimpleNamespace(shell=ui, scope=FocusScope(),
                           painter=SimpleNamespace(text_scale=lambda: 1.0))
    page = KindPage(port, "inbox", view=InboxView)
    host.scope.set_groups(page.build(host, SLOT))
    view = page.view
    for _ in range(20):
        view.update(0.05)
    canvas = Canvas(assets)
    canvas.bind(pygame.Surface(CANVAS_SIZE), Viewport.compute(CANVAS_SIZE, CANVAS_SIZE),
                RenderQuality.FINAL)
    drawn = []
    real = canvas.draw_text

    def spy(text, font, *args, **kwargs):
        drawn.append(font)
        return real(text, font, *args, **kwargs)

    canvas.draw_text = spy                                      # type: ignore[method-assign]
    painter = Painter(theme)
    painter.bind(canvas)
    view.body.draw(painter, Look("normal"))
    body = view._detail.body
    return drawn, body


def _faces(body, index):
    return {glyph.face.bundled for line in body.pages[index].lines for glyph in line.glyphs}


def test_the_terminal_draws_in_noto_sans_mono():
    drawn, _body = _fonts("terminal")
    assert drawn and all(f.ref is None and f.bundled is Face.MONO for f in drawn)


def test_letters_and_pigeon_headings_and_signatures_are_serif():
    for look in ("letter", "pigeon"):
        _drawn, body = _fonts(look)
        roles = [para.role for para in body.looks]
        assert _faces(body, roles.index("via")) == {Face.SERIF_ITALIC}, look
        assert _faces(body, roles.index("sign")) == {Face.SERIF_ITALIC}, look
        assert _faces(body, roles.index("them")) <= {Face.REGULAR, Face.ITALIC}, look


def test_a_game_with_its_own_font_keeps_it_in_every_look():
    drawn, _body = _fonts("terminal", OWN)
    assert drawn and all(f.ref == "fonts/Own.ttf" for f in drawn)
    _drawn, body = _fonts("letter", OWN)
    roles = [para.role for para in body.looks]
    assert _faces(body, roles.index("via")) == {Face.ITALIC}


def test_a_thoughts_notice_reads_in_italics():
    cfg = ThemeConfig()
    theme = plain_theme(cfg)
    assets = make_assets(None)
    assert notice_skin(cfg, "mind").italic and not notice_skin(cfg, "letter").italic
    for look, face in (("mind", Face.ITALIC), ("phone", Face.REGULAR)):
        layer = NoticeLayer(notice_style(theme), measure_with(assets, theme.font(
            cfg.notice.text_size)))
        layer.notify("Hello from Hana.", skin=notice_skin(cfg, look))
        layer.update(1.0)
        canvas = Canvas(assets)
        canvas.bind(pygame.Surface(CANVAS_SIZE), Viewport.compute(CANVAS_SIZE, CANVAS_SIZE),
                    RenderQuality.FINAL)
        drawn = []
        real = canvas.draw_text

        def spy(text, font, *args, drawn=drawn, real=real, **kwargs):
            drawn.append(font)
            return real(text, font, *args, **kwargs)

        canvas.draw_text = spy                                  # type: ignore[method-assign]
        layer.draw(canvas, Painter(theme))
        assert drawn and {f.bundled for f in drawn} == {face}, look
