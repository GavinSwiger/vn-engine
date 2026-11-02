"""F09 step 2 — transitions and waits in App A (``06-acceptance.md`` §0.2: the real ``App``
on a ``FakeWindow`` at 1280×720, a fake clock of exactly 1/60 s per frame, the game started
through ``install_story``, input injected as pygame events). The stage is probed at
(640, 100), above F05's box.

Frame rule (deviation, within §0.3's ±1 frame): ``WaitDone`` goes out in the update after
the last transition frame was drawn (``04`` §6.3) and the story is pumped before the
screens update, so the next line arrives one frame after the ``WaitDone`` frame.

AC-F09-17, 23, 24, 25, 26, 28, 30; AC-F09-40 (``speed``).
"""

import logging
from pathlib import Path

import pygame
import pytest

from engine.render import transitions
from engine.render.typewriter import TypeState
from engine.runtime.commands import WaitDone
from engine.ui.screen import Screen
from tests.fakes.privacy import check_p
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen

pytestmark = pytest.mark.display

EMBER, RIVER, SEA = (200, 40, 0), (0, 0, 255), (0, 80, 240)
PROBE = (640, 100)
HEAD = ('image bg ember = "#c82800"\nimage bg sea = "#0050f0"\nimage bg river = "#0000ff"\n'
        'define hana = Character("Hana")\ndefine slow_dissolve = Dissolve(1.5)\n'
        'label start:\n    scene bg ember\n')
SPRITES = {"hana happy": (0, 255, 0), "hana sad": (0, 255, 0), "daichi grin": (255, 255, 0)}


class Run:
    """One App A session of ``HEAD`` + ``body``: every presented frame's probe and line,
    every ``WaitDone`` with its frame, and the frame of the press that leaves "A."."""

    def __init__(self, root: Path, body: str, config: str = "") -> None:
        self.root = make_text_game(root, script=HEAD + body, config=config)
        gen.write(self.root, {gen.ref_of(name): gen.block(300, 600, color)
                              for name, color in SPRITES.items()})
        self.s = Session(self.root)
        self.frames: dict[int, tuple[tuple[int, int, int], str | None]] = {}
        self.waits: list[tuple[int, int]] = []
        self.n = 0

    def step(self) -> object:
        """One frame; records the frame just presented."""
        yield
        s = self.s
        self.frames[s.frame - 1] = (s.px(*PROBE), s.line_text())

    def steps(self, count: int):
        for _ in range(count):
            yield from self.step()

    def leave_a(self, *, press: bool = True):
        """Until "A." shows, spy on ``WaitDone``, then press Space (frame ``n``)."""
        s = self.s
        yield from s.until_line("A.")
        yield from self.steps(3)
        story = s.app.story
        post = story.post

        def spy(event):
            if isinstance(event, WaitDone):
                self.waits.append((s.frame, event.wait_id))
            post(event)

        story.post = spy
        if press:
            s.key(pygame.K_SPACE)
            self.n = s.frame

    def until(self, predicate, limit: int = 400):
        for _ in range(limit):
            if predicate():
                return
            yield from self.step()
        raise AssertionError("condition not reached")

    def first(self, predicate) -> int:
        return min(f for f, (px, line) in self.frames.items() if f >= self.n
                   and predicate(px, line))

    def play(self, script) -> "Run":
        self.s.play(lambda s: script(self))
        return self


def advances(run: Run, after: int) -> list[int]:
    return [f for f, _ in run.s.posted if f > after]


# --- AC-F09-17 — lengths, and when the story continues ---------------------------------------

@pytest.mark.parametrize("with_, config, speed, P, F", [
    ("dissolve", "", 1.0, 1, 30),
    ("fade", "", 1.0, 1, 60),
    ("slow_dissolve 0.4", "", 1.0, 1, 24),
    ("dissolve", "[effects]\ndissolve = 1.0\n", 1.0, 1, 60),
    ("dissolve", "", 2.0, 1, 15),                        # AC-F09-40: speed halves F
    ("cut", "", 1.0, 0, 0),
])
def test_ac_f09_17_lengths_and_when_the_story_continues(tmp_path, with_, config, speed, P, F):
    def script(r: Run):
        yield from r.leave_a()
        r.s.app.stage_screen.speed = speed
        yield from r.until(lambda: r.s.line_text() == "B.")
        yield from r.steps(2)

    r = Run(tmp_path / "g", f'    "A."\n    scene bg sea with {with_}\n    hana "B."\n',
            config).play(script)
    n = r.n
    assert all(r.frames[f][0] == EMBER for f in range(n, n + P))
    new = r.first(lambda px, line: px == SEA)
    assert new == n + P + F
    assert r.waits == [(new + 1, 1)]
    assert r.first(lambda px, line: line == "B.") == new + 2
    assert advances(r, n) == []                          # no Advance between A. and B.


def test_ac_f09_17_a_timed_pause(tmp_path):
    def script(r: Run):
        yield from r.leave_a()
        yield from r.until(lambda: r.s.line_text() == "B.")

    r = Run(tmp_path / "g", '    "A."\n    pause 1.5\n    "B."\n').play(script)
    assert r.waits == [(r.n + 90, 1)]


# --- AC-F09-23 — only transition frames; upper layers untouched -------------------------------

def test_ac_f09_23_only_transition_frames_and_the_box_untouched(tmp_path):
    hana = (320, 300)                                    # hana's block at left
    blues: list[int] = []
    boxes: set[bytes] = set()

    def script(r: Run):
        s = r.s
        yield from r.leave_a()
        while s.line_text() != "B.":
            yield from r.step()
            blues.append(s.px(*hana)[2])
        yield from r.steps(10)
        s.key(pygame.K_SPACE)
        x, y, w, h = (round(v) for v in s.textbox.geometry.box)
        while s.line_text() != "C.":
            yield from r.step()
            if s.app.stage_screen.view.transitioning:
                boxes.add(pygame.image.tobytes(s.fb.subsurface((x, y, w, h)), "RGB"))

    body = ('    "A."\n    scene bg river\n    show hana happy at left\n'
            '    show daichi grin at right with dissolve\n    show hana sad\n    "B."\n'
            '    show hana happy with dissolve 2.0\n    "C."\n')
    Run(tmp_path / "g", body, "[theme.textbox]\nfill_opacity = 1.0\n").play(script)
    assert len(blues) > 30 and max(blues) <= 2            # no bg river without hana
    assert len(boxes) == 1


# --- AC-F09-24 — a click finishes a transition; an untimed pause ------------------------------

def test_ac_f09_24_a_click_finishes_and_is_consumed(tmp_path):
    def script(r: Run):
        s = r.s
        yield from r.leave_a()
        yield from r.steps(2 + 30)                       # to frame n + P + 30: p = 0.25
        assert r.frames[s.frame - 1][0] == (100, 20, 0)
        s.mouse(PROBE)
        s.mouse(PROBE)                                   # two presses in one frame
        r.click = s.frame
        yield from r.step()
        assert r.frames[r.click][0] == SEA               # the next frame: the new picture
        yield from r.until(lambda: s.line_text() == "B.")
        yield from r.steps(30)
        assert s.line_text() == "B." and advances(r, r.n) == []   # B. needs its own press
        s.key(pygame.K_SPACE)
        r.pause = s.frame
        yield from r.steps(200)                          # the untimed pause: nothing ends it
        assert s.line_text() is None and len(r.waits) == 1
        s.key(pygame.K_RETURN)
        r.end = s.frame
        yield from r.until(lambda: s.line_text() == "C.")

    r = Run(tmp_path / "g", '    "A."\n    scene bg sea with fade 2.0\n    "B."\n    pause\n'
                            '    "C."\n').play(script)
    assert r.waits == [(r.click + 1, 1), (r.end, 2)]
    assert advances(r, r.n) == [r.pause]


# --- AC-F09-25 — no stale text during a wait (and shake/flash are harmless) -------------------

def test_ac_f09_25_no_stale_text_during_a_wait(tmp_path):
    seen: dict[str, set] = {"fade": set(), "dissolve": set(), "pause": set()}

    def script(r: Run):
        s = r.s
        yield from r.leave_a()
        box = s.textbox
        for name, until in (("fade", "B."), ("dissolve", "C."), ("pause", "D.")):
            if name != "fade":
                yield from r.steps(10)                   # the line typed out
                s.key(pygame.K_SPACE)
            for _ in range(200):
                yield from r.step()
                if s.line_text() == until:
                    break
                seen[name].add((box.box_shown, box.line is None))
                if name == "pause" and len(seen["pause"]) == 1:
                    s.key(pygame.K_h)                    # hidden through the pause
        assert box.hidden and s.line_text() == "D."

    body = ('    hana "A."\n    scene bg sea with fade\n    hana "B."\n    shake\n    flash\n'
            '    show hana happy with dissolve\n    hana "C."\n    pause 1.0\n    "D."\n')
    r = Run(tmp_path / "g", body).play(script)
    assert seen["fade"] == {(False, True)}               # a scene ran: nothing drawn
    assert seen["dissolve"] == {(True, True)}            # the empty box, no text
    assert seen["pause"] == {(True, True), (False, True)}
    assert [w for _, w in r.waits] == [1, 2, 3]


# --- AC-F09-26 — timers freeze under menus and when unfocused --------------------------------

class _Menu(Screen):
    opaque = False                                       # the stage still draws under it


def test_ac_f09_26_timers_freeze_under_menus_and_when_unfocused(tmp_path):
    def script(r: Run):
        s = r.s
        yield from r.leave_a()
        yield from r.steps(31)
        menu = _Menu()
        s.app.screens.push(menu)
        held = r.frames[s.frame - 1][0]
        yield from r.steps(60)
        s.app.screens.remove(menu)
        s.event(pygame.WINDOWFOCUSLOST)
        yield from r.steps(60)
        assert {r.frames[f][0] for f in range(s.frame - 120, s.frame)} == {held}
        assert r.waits == []
        s.event(pygame.WINDOWFOCUSGAINED)
        yield from r.until(lambda: s.line_text() == "B.")

    r = Run(tmp_path / "g", '    "A."\n    scene bg sea with fade 2.0\n    "B."\n').play(script)
    assert r.first(lambda px, line: px == SEA) == r.n + 1 + 120 + 120


# --- AC-F09-28 — a restore cancels the transition --------------------------------------------

def test_ac_f09_28_a_restore_cancels_the_transition(tmp_path):
    def script(r: Run):
        s = r.s
        yield from r.leave_a()
        yield from r.steps(1 + 36)                       # p = 0.3 of dissolve 2.0
        story = s.app.story
        story.restore(story.checkpoint())                # the last line: "A."
        r.restored = s.frame
        yield from r.step()
        assert r.frames[r.restored] == (EMBER, "A.")
        assert s.textbox.typer.state is TypeState.COMPLETE
        yield from r.steps(150)                          # the old wait never ends
        assert r.waits == [] and s.line_text() == "A."
        s.key(pygame.K_SPACE)                            # the restored line advances
        yield from r.until(lambda: s.line_text() == "B.")

    r = Run(tmp_path / "g", '    "A."\n    scene bg sea with dissolve 2.0\n    "B."\n'
            ).play(script)
    assert [w for _, w in r.waits] == [2]


# --- AC-F09-30 — a drawing failure cuts (W62) -------------------------------------------------

@pytest.mark.parametrize("error", [pygame.error, MemoryError])
def test_ac_f09_30_a_drawing_failure_cuts(tmp_path, caplog, error):
    real = transitions.Dissolve.draw

    def draw(self, target, p, offset):
        if p >= 0.3:
            raise error("no memory for the scratch")
        real(self, target, p, offset)

    def script(r: Run):
        s = r.s
        yield from r.leave_a()
        yield from r.until(lambda: s.line_text() == "B.")
        yield from r.steps(10)
        s.key(pygame.K_SPACE)
        r.again = s.frame
        yield from r.until(lambda: s.line_text() == "C.")
        yield from r.steps(10)
        s.key(pygame.K_SPACE)
        r.fade = s.frame
        yield from r.until(lambda: s.line_text() == "D.")

    body = ('    "A."\n    scene bg sea with dissolve\n    "B."\n    scene bg ember with dissolve\n'
            '    "C."\n    scene bg sea with fade\n    "D."\n')
    with pytest.MonkeyPatch.context() as mp, caplog.at_level(logging.WARNING):
        mp.setattr(transitions.Dissolve, "draw", draw)
        r = Run(tmp_path / "g", body).play(script)
    n = r.n
    assert r.frames[n + 1 + 9][0] != SEA and r.frames[n + 1 + 9][0] != EMBER
    assert r.frames[n + 1 + 10][0] == SEA                # p = 1/3: that frame cuts
    assert r.frames[r.again][0] == EMBER                 # dissolve now plays as a cut
    assert any(px not in (SEA, EMBER) for f, (px, _) in r.frames.items() if f > r.fade)
    w62 = [rec for rec in caplog.records if getattr(rec, "code", None) == "W62"]
    assert len(w62) == 1
    text = w62[0].getMessage()
    assert text.startswith('script/main.vns, line 9: the transition "dissolve" couldn')
    assert f"({error.__name__})" in text
    check_p([text], home=Path.home(), game=r.root)
