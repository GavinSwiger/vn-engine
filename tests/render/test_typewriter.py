"""F05 ``render/typewriter.py``: the typing timeline (AC-F05-16) and advances while typing
(AC-F05-17), over ``LineLayout`` with the M20 fake font and a fake clock of 1 ms steps
(06 §0.6: times exact ± 1 ms)."""

import ast
import math
from pathlib import Path

import pytest

from engine.render import typewriter
from engine.render.textlayout import LineLayout
from engine.render.typewriter import (
    Completed,
    GlyphShown,
    PauseStarted,
    PressResult,
    TypeState,
    Typewriter,
    WaitKind,
    Waiting,
    deliver,
)
from tests.fakes.fixed_font import m20_context, tagged

STEP = 0.001


def writer(text: str, cps: float = 40) -> Typewriter:
    return Typewriter(LineLayout(tagged(text), m20_context()), lambda: cps)


class Clock:
    """Runs a typewriter in 1 ms ticks and logs (ms, event)."""

    def __init__(self, tw: Typewriter) -> None:
        self.tw = tw
        self.ms = 0
        self.log = [(0, event) for event in tw.run()]

    def advance(self, ms: int) -> None:
        for _ in range(ms):
            self.ms += 1
            self.log += [(self.ms, event) for event in self.tw.tick(STEP)]

    def until(self, state: TypeState, limit_ms: int = 20_000) -> None:
        while self.tw.state is not state:
            assert self.ms < limit_ms, f"never reached {state}"
            self.advance(1)

    def press(self) -> PressResult:
        result = self.tw.press()
        self.log += [(self.ms, event) for event in self.tw.take_events()]
        return result

    def times(self, kind: type) -> list[int]:
        return [ms for ms, event in self.log if type(event) is kind]

    def events(self, kind: type) -> list:
        return [event for _, event in self.log if type(event) is kind]


def close(actual: list[float], expected: list[float]) -> bool:
    return len(actual) == len(expected) and all(abs(a - e) <= 1 for a, e in
                                                zip(actual, expected))


# --- AC-F05-16: typing timeline ----------------------------------------------------------------

# cps, text, glyph times (ms), other expected events (ms, event), run for (ms)
TIMELINE_ROWS = [
    (40, "a" * 40, [25 * i for i in range(40)], [(1000, Completed(False))], 1500),
    (40, "Hello there!", [25 * i for i in range(12)], [(300, Completed(False))], 1000),
    (40, "{speed=0.5}" + "a" * 10 + "{/speed}", [50 * i for i in range(10)],
     [(500, Completed(False))], 1000),
    (40, "{speed=2}" + "a" * 10 + "{/speed}", [math.ceil(12.5 * i) for i in range(10)],
     [(125, Completed(False))], 1000),
    (40, "ab{pause=0.6}cd", [0, 25, 650, 675],
     [(50, PauseStarted(0.6)), (700, Completed(False))], 1500),
    (40, "ab{pause}cd", [0, 25], [(50, Waiting(WaitKind.CLICK))], 10_050),
    (40, "ab{speed=instant}cdef{/speed}gh", [0, 25, 50, 50, 50, 50, 50, 75],
     [(100, Completed(False))], 500),
    (40, "a😀é", [0, 25, 50], [(75, Completed(False))], 500),
    (40, "a b", [0, 25, 50], [(75, Completed(False))], 500),
    (40, "a\nb", [0, 25], [(50, Completed(False))], 500),
    (40, "{b}a{/b}", [0], [(25, Completed(False))], 500),
    (40, "abc{pause=0.5}", [0, 25, 50], [(75, PauseStarted(0.5)), (575, Completed(False))],
     1000),
    (0, "abc{pause=0.5}def", [0, 0, 0, 500, 500, 500],
     [(0, PauseStarted(0.5)), (500, Completed(False))], 1000),
    (0, "abc{pause}d", [0, 0, 0], [(0, Waiting(WaitKind.CLICK))], 1000),
    (0, "{speed=0.1}abc{/speed}", [0, 0, 0], [(0, Completed(False))], 100),
    (1000, "a" * 40, list(range(40)), [(40, Completed(False))], 100),
    (1000, "{speed=10}" + "a" * 40, [math.ceil(0.1 * i) for i in range(40)],
     [(4, Completed(False))], 100),
    # Edge cases beyond the AC table.
    (40, "", [], [(0, Completed(False))], 100),
    (40, "{pause=0.2}", [], [(0, PauseStarted(0.2)), (200, Completed(False))], 500),
    (40, "a\nb\nc\nd", [0, 25, 50], [(75, Waiting(WaitKind.PAGE))], 1000),
    (0, "a\nb\nc\nd", [0, 0, 0], [(0, Waiting(WaitKind.PAGE))], 100),
    (40, "a{pause=0.1}{pause=0.1}b", [0, 225],
     [(25, PauseStarted(0.1)), (125, PauseStarted(0.1)), (250, Completed(False))], 500),
]


@pytest.mark.parametrize("cps, text, glyph_ms, others, run_ms", TIMELINE_ROWS,
                         ids=range(len(TIMELINE_ROWS)))
def test_typing_timeline(cps, text, glyph_ms, others, run_ms):
    clock = Clock(writer(text, cps))
    clock.advance(run_ms)
    assert close(clock.times(GlyphShown), glyph_ms), clock.times(GlyphShown)
    rest = [(ms, event) for ms, event in clock.log if type(event) is not GlyphShown]
    assert [event for _, event in rest] == [event for _, event in others]
    assert close([ms for ms, _ in rest], [ms for ms, _ in others]), rest


@pytest.mark.parametrize("text", ["a" * 40, "Hello there!", "a😀é x\ny",
                                  "ab{pause}cd", "{speed=instant}abc{/speed}d"])
def test_glyph_indices_are_consecutive_and_one_per_grapheme(text):
    clock = Clock(writer(text))
    for _ in range(5):
        clock.advance(1000)
        clock.press()
    shown = clock.events(GlyphShown)
    layout = clock.tw.layout
    assert [e.index for e in shown] == list(range(layout.glyph_count))
    assert "".join(e.grapheme for e in shown) == "".join(text.split("{pause}")) \
        .replace("{speed=instant}", "").replace("{/speed}", "").replace("\n", "")


def test_glyph_zero_is_shown_by_run_and_run_twice_repeats_nothing():
    tw = writer("abc")
    assert tw.run() == [GlyphShown(0, "a")]
    assert tw.run() == []
    assert tw.shown == 1 and tw.state is TypeState.TYPING


def test_a_speed_change_applies_at_once():
    cps = [40]
    tw = Typewriter(LineLayout(tagged("a" * 40), m20_context()), lambda: cps[0])
    clock = Clock(tw)
    clock.advance(500)
    cps[0] = 80
    clock.advance(500)
    assert close(clock.times(Completed), [750])


def test_speed_tags_are_relative_to_the_current_speed():
    clock = Clock(writer("{speed=0.5}" + "a" * 10 + "{/speed}", 80))
    clock.advance(500)
    assert close(clock.times(Completed), [250])


def test_instant_mid_line_still_honors_timed_pauses():
    cps = [40]
    tw = Typewriter(LineLayout(tagged("abcd{pause=0.5}efg"), m20_context()), lambda: cps[0])
    clock = Clock(tw)
    clock.advance(30)
    cps[0] = 0
    clock.advance(1)
    assert clock.tw.shown == 4 and clock.tw.state is TypeState.PAUSED
    clock.advance(600)
    # §7.5: time left over in b's slot (25-31 ms) carries into the pause.
    assert close(clock.times(Completed), [525])


def test_a_pause_is_announced_once():
    clock = Clock(writer("a{pause=1}b"))
    clock.advance(2000)
    assert clock.events(PauseStarted) == [PauseStarted(1)]


def test_nothing_happens_while_waiting():
    clock = Clock(writer("ab{pause}cd"))
    clock.until(TypeState.WAIT_CLICK)
    before = len(clock.log)
    clock.advance(10_000)
    assert len(clock.log) == before and clock.tw.shown == 2


# --- AC-F05-17: an advance while typing --------------------------------------------------------

def test_press_while_typing_completes_up_to_the_click_stop():
    clock = Clock(writer("abcdef{pause}gh"))
    clock.advance(30)
    assert clock.tw.shown == 2
    before = len(clock.events(GlyphShown))
    assert clock.press() is PressResult.COMPLETED
    assert clock.tw.shown == 6 and clock.tw.state is TypeState.WAIT_CLICK
    assert len(clock.events(GlyphShown)) == before          # no glyph events: blips stop
    assert clock.log[-1] == (30, Waiting(WaitKind.CLICK))


def test_press_in_a_timed_pause_completes_the_line():
    clock = Clock(writer("ab{pause=5}cd{pause=5}ef"))
    clock.advance(100)
    assert clock.tw.state is TypeState.PAUSED
    assert clock.press() is PressResult.COMPLETED
    assert clock.tw.shown == 6 and clock.tw.state is TypeState.COMPLETE
    clock.advance(11_000)
    assert clock.events(PauseStarted) == [PauseStarted(5)]
    assert clock.events(Completed) == [Completed(True)]


def test_press_at_a_click_wait_continues():
    clock = Clock(writer("ab{pause}cd"))
    clock.until(TypeState.WAIT_CLICK)
    at = clock.ms
    assert clock.press() is PressResult.CONTINUED
    assert clock.tw.shown == 3 and clock.log[-1] == (at, GlyphShown(2, "c"))
    clock.advance(1000)
    assert close(clock.times(Completed), [at + 50])
    assert clock.events(Completed) == [Completed(False)]


def test_press_at_a_page_wait_shows_the_next_page():
    clock = Clock(writer("a\nb\nc\nd"))
    clock.until(TypeState.WAIT_PAGE)
    assert clock.press() is PressResult.NEXT_PAGE
    assert clock.tw.page == 1 and clock.tw.shown == 4
    assert clock.log[-1] == (clock.ms, GlyphShown(3, "d"))


@pytest.mark.parametrize("page", [0, 1])
def test_press_while_typing_a_page_stops_at_its_break(page):
    clock = Clock(writer("a\nb\nc\nd\ne\nf\ng"))
    for _ in range(page):
        clock.until(TypeState.WAIT_PAGE)
        clock.press()
    clock.advance(10)
    assert clock.press() is PressResult.COMPLETED
    assert clock.tw.state is TypeState.WAIT_PAGE and clock.tw.page == page
    assert clock.tw.shown == 3 * (page + 1)


@pytest.mark.parametrize("text", ["abc", "a{pause}b", "a\nb\nc\nd", ""])
def test_press_when_complete_advances(text):
    clock = Clock(writer(text))
    for _ in range(10):
        if clock.tw.state is TypeState.COMPLETE:
            break
        clock.press()
    assert [clock.press() for _ in range(3)] == [PressResult.ADVANCE] * 3


def test_complete_all_lays_out_every_page():
    tw = writer("a\nb\nc\nd\ne\nf\ng")
    tw.run()
    tw.complete_all()
    assert (tw.page, tw.state, tw.shown, tw.layout.laid_out) == (2, TypeState.COMPLETE, 7, 3)
    assert tw.take_events() == [Completed(True)]
    tw.complete_all()
    assert tw.take_events() == []
    assert tw.press() is PressResult.ADVANCE


def test_complete_all_before_run():
    tw = writer("abc{pause}d")
    tw.complete_all()
    assert tw.run() == [Completed(True)] and tw.shown == 4


# --- Seams --------------------------------------------------------------------------------------

class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def glyph_shown(self, index, grapheme):
        self.calls.append(("glyph", index, grapheme))

    def pause_started(self, seconds):
        self.calls.append(("pause", seconds))

    def waiting(self, kind):
        self.calls.append(("waiting", kind))

    def completed(self, by_press):
        self.calls.append(("completed", by_press))


def test_deliver_fans_events_out_in_order():
    first, second = Recorder(), Recorder()
    deliver([GlyphShown(0, "a"), PauseStarted(0.5), Waiting(WaitKind.PAGE), Completed(True)],
            [first, second])
    assert first.calls == second.calls == [("glyph", 0, "a"), ("pause", 0.5),
                                           ("waiting", WaitKind.PAGE), ("completed", True)]


def test_typewriter_imports_no_pygame_and_no_layout():
    tree = ast.parse(Path(typewriter.__file__).read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}
    engine = {name for name in imported if name.startswith("engine")}
    assert engine == {"engine.runtime.commands"}
    assert not any(name.startswith("pygame") for name in imported)
