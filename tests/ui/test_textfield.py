"""F52 step P4: ``TextField`` (``ui/textfield.py``): AC-F52-01, 02, 15, 18, 34; and the shared
render API (``ChainFont.covers``, ``render.text.missing_glyphs``, 07 I-5)."""

import pygame
import pytest

from engine.core.fontcmap import Coverage
from engine.render.fontchain import ChainFont
from engine.render.text import missing_glyphs
from engine.ui.focus import Box
from engine.ui.input import UiEvent
from engine.ui.nav import Nav
from engine.ui.textfield import TextField
from engine.ui.widgets import Look
from tests.fakes.ui_shell import TestShell, UiHarness

FOCUSED, NORMAL, DISABLED = Look("focused"), Look("normal"), Look("disabled")
BOX = Box(100, 100, 600, 56)


@pytest.fixture
def p():
    shell = TestShell()
    h = UiHarness(shell)
    h.frame()
    shell.painter.bind(h.canvas)
    return shell.painter


def text_event(text: str) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.TEXTINPUT, text=text), None, False)


def editing(text: str, start: int = 0) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.TEXTEDITING, text=text, start=start,
                                      length=len(text)), None, False)


def key(k: int, unicode: str = "") -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode=unicode), None,
                   False)


# --- AC-F52-01: TEXTINPUT inserts at the caret; key codes never add text ------------------------

def test_ac_f52_01_text_input_only(p):
    changes = []
    f = TextField(text="Rn", box=BOX, on_change=changes.append)
    f.on_nav(Nav.LEFT)
    assert f.on_text(text_event("e")) and f.text == "Ren" and changes == ["Ren"]
    assert not f.on_text(key(pygame.K_a, "a")) and f.text == "Ren"       # a key code: nothing
    f.on_text(text_event("ж"))                                           # any layout, any script
    assert f.text == "Reжn" and f.last_edit == "type"
    f.set_text("Sayo")                                                   # the program's: no on_change
    assert changes == ["Ren", "Reжn"] and f.model.caret == 4


# --- AC-F52-02: composition shown underlined at the caret, uncounted, replaced on commit ----------

def test_ac_f52_02_composition(p):
    f = TextField(text="ab", box=BOX, max_length=3)
    f.on_nav(Nav.LEFT)
    f.on_text(editing("かな"))
    assert f.composing and f.text == "ab" and f.model.length == 2
    plan = f.plan(p, FOCUSED)
    assert plan.text == "aかなb" and plan.composition is not None
    x0, x1 = plan.composition
    assert x0 < x1 and plan.counter == "2/3"                  # not counted
    assert plan.caret is not None and plan.caret.x == pytest.approx(x1, abs=1)
    f.on_text(text_event("仮"))                                # the commit replaces it
    assert f.text == "a仮b" and f.model.caret == 2
    assert f.composing                                        # the latch, until the frame ends
    f.tick(1 / 60)
    assert not f.composing and f.plan(p, FOCUSED).composition is None
    f.on_text(editing("x"))
    f.text_lost()                                             # focus left: dropped
    assert not f.composing and f.text == "a仮b"


# --- AC-F52-15: mask, placeholder, counter ---------------------------------------------------------

def test_ac_f52_15_mask_placeholder_counter(p):
    f = TextField(box=BOX, placeholder="Type here", max_length=60, mask=True)
    plan = f.plan(p, FOCUSED)
    assert plan.placeholder == "Type here" and plan.counter == "0/60"
    f.on_text(editing("ab"))
    assert f.plan(p, FOCUSED).placeholder is None             # not while composing
    f.on_text(text_event("\U0001F468‍\U0001F469‍\U0001F467é"))
    f.tick(0)
    f.on_text(editing("xy"))
    plan = f.plan(p, FOCUSED)
    assert plan.text == "••xy"                                 # one dot per grapheme; composition as typed
    assert TextField(box=BOX, max_length=61).plan(p, FOCUSED).counter is None
    assert TextField(box=BOX, max_length=60).plan(p, FOCUSED).counter == "0/60"


# --- AC-F52-18: the bare field ---------------------------------------------------------------------

def test_ac_f52_18_bare_field(p):
    f = TextField(box=BOX, bare=True, text="dir")
    rest = f.plan(p, NORMAL)
    assert rest.frame is None and rest.icon is None and rest.counter is None
    assert rest.caret is None and rest.underline is None
    focused = f.plan(p, FOCUSED)
    assert focused.frame is None and focused.caret is not None
    assert focused.underline == Box(BOX.x, BOX.bottom - 2, BOX.w, 2)
    boxed = TextField(box=BOX).plan(p, FOCUSED)
    assert boxed.frame == "focused" and boxed.marker and boxed.icon is not None
    # Drawing a bare field paints nothing outside its text, caret and underline.
    surface = p.canvas.surface
    surface.fill((0, 0, 0))
    f.draw(p, NORMAL)
    assert surface.get_at(p.canvas.px(BOX.right - 5, BOX.y + 5))[:3] == (0, 0, 0)


# --- AC-F52-34: the caret blinks 500/500, steady under reduce motion --------------------------------

def test_ac_f52_34_caret_blink(p):
    f = TextField(box=BOX)
    seen = []
    for _ in range(60):                                       # one second at 60 fps
        seen.append(f.plan(p, FOCUSED).caret is not None)
        f.tick(1 / 60)
    assert seen[:30] == [True] * 30 and seen[30:] == [False] * 30
    f.on_text(text_event("a"))                                # shown at once after an edit
    assert f.plan(p, FOCUSED).caret is not None
    for _ in range(90):
        f.tick(1 / 60, reduce_motion=True)
        assert f.plan(p, FOCUSED).caret is not None           # steady
    assert f.plan(p, NORMAL).caret is None                    # unfocused: none


# --- 07 I-5: the shared render API --------------------------------------------------------------

def test_chain_covers_and_missing_glyphs():
    pygame.font.init()
    font = pygame.font.Font(None, 24)
    chain = ChainFont([(font, Coverage.from_ranges([(0x20, 0x7E)]))])
    assert chain.covers("a") is True and chain.covers("ж") is False
    assert ChainFont([(font, None)]).covers("ж") is None    # unknown: the pixel test decides
    assert missing_glyphs(font, "") == [] and missing_glyphs(font, "ab") == []
