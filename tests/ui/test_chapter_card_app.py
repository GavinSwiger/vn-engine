"""F18 step 2 — the title card in App A (``tests/fakes/text_app.py``: the real ``App`` on a
``FakeWindow`` at 1280×720, a fake clock of exactly 1/60 s per frame, input as pygame events).
The stage is probed at (640, 100), above the card's text.

Step 3's ``install_chapters`` (in ``install_story``) sets the painter and the
``ChapterStarted`` handler; each run counts the commands by wrapping that handler.

Frame rule (F09's, ``test_stage_screen.py``): a ``with`` keeps the old picture for one
preparing frame, so a 1.0 s fade pressed into at frame n shows its last frame at n + 61; a
``WaitDone`` goes out in the next update and the next wait or line arrives a frame later.

AC-F18-04.
"""

import pygame
import pytest

from engine.runtime.commands import ChapterStarted
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.title_card import CardPainter
from tests.fakes.text_app import Session, make_text_game

pytestmark = pytest.mark.display

A, B, FILL = (200, 40, 0), (0, 80, 240), (0x2A, 0x1E, 0x26)
PROBE = (640, 100)
NATURAL_LAST = 245                       # the last frame of the card in full, left alone
SCRIPT = ('image bg a = "#c82800"\nimage bg b = "#0050f0"\nlabel start:\n    scene bg a\n'
          '    "L1"\n    scene bg b\n    chapter c "H" "T"\n    "L2"\n')


class Card:
    """One run: every presented frame's probe, line, and whether the box (and so the quick
    menu) showed, from the press that leaves "L1" (frame ``n``)."""

    def __init__(self, root, act=None) -> None:
        self.act = act or (lambda card, t: None)
        self.frames: dict[int, tuple[tuple[int, int, int], str | None, bool]] = {}
        self.started: list[ChapterStarted] = []
        self.n = 0
        self.s = Session(make_text_game(root, script=SCRIPT))
        self.s.play(self.script)

    def script(self, s: Session):
        yield from s.until_line("L1")
        assert isinstance(s.app.stage_screen.view.card_painter, CardPainter)
        handler = s.app.router._handlers[ChapterStarted]
        s.app.router.unregister(ChapterStarted)
        s.app.router.register(ChapterStarted,
                              lambda cmd: (self.started.append(cmd), handler(cmd)))
        yield from s.until(lambda: s.textbox.typer.state.name == "COMPLETE")
        s.key(pygame.K_SPACE)
        self.n = s.frame
        for _ in range(900):
            self.act(self, s.frame - self.n)
            yield
            self.frames[s.frame - 1] = (s.px(*PROBE), s.line_text(), s.textbox.box_shown)
            if s.line_text() == "L2":
                return

    def first(self, color, after: int = 0) -> int:
        return min(f - self.n for f, (px, _, _) in self.frames.items()
                   if f - self.n >= after and px == color)

    def last(self, color) -> int:
        return max(f - self.n for f, (px, _, _) in self.frames.items() if px == color)


def test_ac_f18_04_card_timing_clicks_keys_and_the_game_menu(tmp_path):
    # Timing, with the press's key still held (repeats at 2.0 s): the frame numbers are the
    # natural ones, so one run covers both the timing and "held key, repeat → nothing".
    def hold_key(card: Card, t: int) -> None:
        if t == 120:
            for _ in range(3):
                card.s.event(pygame.KEYDOWN, key=pygame.K_SPACE, mod=0, unicode="",
                             scancode=0, repeat=True)

    card = Card(tmp_path / "held", hold_key)
    full, out, shown, l2 = card.first(FILL), card.last(FILL), card.first(B), card.first(B) + 1
    assert full == 61                                  # card full at 1.0 s
    assert out == NATURAL_LAST and out - full == 184   # held 3.0 s (+ F09's 4 hand-off frames)
    assert shown == out + 60 == 305                    # stage b at about 5.0 s
    before = [(px, box) for f, (px, line, box) in card.frames.items() if f - card.n < l2]
    assert all(px != B and not box for px, box in before[:shown - 1])
    assert card.frames[card.n + shown + 2][1] == "L2"
    assert len(card.started) == 1

    marks: dict[str, int] = {}

    def click_in(card: Card, t: int) -> None:
        if t == 18:                                    # 0.3 s into the fade
            card.s.mouse((640, 360))
        if card.frames and t > 30 and "hold" not in marks:
            if card.frames[max(card.frames)][0] == FILL:
                marks["hold"] = t + 60                 # 1.0 s into the hold
        if t == marks.get("hold"):
            card.s.mouse((640, 360))

    card = Card(tmp_path / "click", click_in)
    assert card.first(FILL) == 18                      # the click's frame: the card in full
    # The click ends the hold; the way out starts (its preparing frame) in the next frame.
    assert card.last(FILL) == marks["hold"] + 1
    assert card.first(B) == marks["hold"] + 61

    def menu(card: Card, t: int) -> None:
        stack = card.s.app.screens
        if t == 120:                                   # at 2.0 s: 1.0 s into the hold
            card.s.key(pygame.K_ESCAPE)
        if t == 121:
            marks["opened"] = any(isinstance(sc, GameMenuScreen) for sc in stack)
        if t == 120 + 600:                             # 10 s later
            card.s.key(pygame.K_ESCAPE)
        if t > 120 + 600 and "closed" not in marks \
                and not any(isinstance(sc, GameMenuScreen) for sc in stack):
            marks["closed"] = t

    card = Card(tmp_path / "menu", menu)
    assert marks["opened"]
    # The hold froze for every frame the menu was up (its close fade included), so 2.0 s
    # of it (and F09's hand-off frames) were left: the way out starts as in an unbroken run.
    assert card.last(FILL) == NATURAL_LAST + marks["closed"] - 120
