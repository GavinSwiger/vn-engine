"""F06 step 3 — ``BlipPlayer`` on its own (``SPEC.md`` §5): which graphemes blip
(AC-F06-03), every Nth from the line's first (AC-F06-04), the 40 ms gap (AC-F06-05), the
pitch steps (AC-F06-06), and the lines that never blip and ``set_enabled`` (AC-F06-09's
player rows). A spy stands in for ``AudioService.play_blip`` and a list for the clock; the
textbox runs are ``test_blips_textbox.py``."""

from collections import Counter
from random import Random

from engine.audio.pitch import BLIP_STEPS
from engine.core.graphemes import graphemes
from engine.runtime.character import BlipSpec
from engine.runtime.commands import Say
from engine.ui.blips import BLIP_MIN_GAP_S, BlipPlayer, blips_on

HANA = BlipSpec("blips/hana.ogg", 2, 0.1, 80)


class Spy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float, int]] = []

    def play_blip(self, file: str, *, volume: int = 100, spread: float = 0.0,
                  step: int = 0) -> None:
        self.calls.append((file, volume, spread, step))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def player(rng: Random | None = None) -> tuple[BlipPlayer, Spy, Clock]:
    spy, clock = Spy(), Clock()
    return BlipPlayer(spy, clock, rng or Random(0)), spy, clock


def say(blip: BlipSpec | None, **kw) -> Say:
    return Say("s1", "hana", "Hana", None, (), "x", blip=blip, **kw)


def typed(p: BlipPlayer, spy: Spy, clock: Clock, text: str, dt: float) -> list[str]:
    """``text`` shown one grapheme per ``dt`` seconds: the graphemes that blipped."""
    out = []
    for index, g in enumerate(graphemes(text)):
        before = len(spy.calls)
        p.glyph_shown(index, g)
        if len(spy.calls) > before:
            out.append(g)
        clock.now += dt
    return out


def test_ac_f06_03_letters_and_digits_blip_the_rest_is_silent():
    table = [("a", True), ("Z", True), ("5", True), ("é", True), ("ア", True),
             ("漢", True), (" ", False), (".", False), ("!", False), ("'", False),
             ("—", False), ("…", False), ("😀", False), ("\n", False), ("", False)]
    p, spy, clock = player()
    p.on_say(say(BlipSpec("blips/a.ogg", 1)))
    for g, blips in table:
        assert blips_on(g) is blips, g
        before = len(spy.calls)
        p.glyph_shown(0, g)
        clock.now += 1.0
        assert (len(spy.calls) > before) is blips, g
    assert graphemes("é") == ["é"]                # one grapheme (F05 §7.1)


def test_ac_f06_04_every_2nd_from_the_first_and_a_new_say_restarts_the_count():
    p, spy, clock = player()
    p.on_say(say(HANA))
    assert typed(p, spy, clock, "You're late!", 0.025) == list("Yueae")
    assert {(f, v, s) for f, v, s, _ in spy.calls} == {("blips/hana.ogg", 80, 0.1)}
    # Waits and pauses don't touch the count; the next Say does.
    p.on_say(say(HANA))
    p.glyph_shown(0, "a")
    p.pause_started(0.5)
    p.waiting(None)
    clock.now += 1.0
    p.glyph_shown(1, "b")
    clock.now += 1.0
    p.glyph_shown(2, "c")
    p.on_say(say(BlipSpec("blips/hana.ogg", 3)))
    clock.now += 1.0
    assert typed(p, spy, clock, "abcd", 1.0) == ["a", "d"]
    p.completed(True)


def test_ac_f06_05_blips_start_at_least_40_ms_apart():
    p, spy, clock = player()
    p.on_say(say(BlipSpec("blips/a.ogg", 1)))
    times = []
    for k in range(100):                                  # glyphs 10 ms apart
        clock.now = k / 100
        before = len(spy.calls)
        p.glyph_shown(k, "a")
        if len(spy.calls) > before:
            times.append(clock.now)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(times) >= 20 and min(gaps) >= BLIP_MIN_GAP_S - 1e-9
    # Instant text: a whole line in one call (no time passes) gives one blip.
    clock.now += 1.0
    p.on_say(say(BlipSpec("blips/a.ogg", 1)))
    assert typed(p, spy, clock, "All of it at once.", 0.0) == ["A"]


def test_ac_f06_06_steps_are_even_and_spread_0_sends_step_0():
    p, spy, clock = player(Random(1))
    p.on_say(say(BlipSpec("blips/a.ogg", 1, 0.2)))
    for k in range(500):
        clock.now = k * BLIP_MIN_GAP_S * 2
        p.glyph_shown(k, "a")
    counts = Counter(step for *_, step in spy.calls)
    assert sum(counts.values()) == 500 and set(counts) == set(BLIP_STEPS)
    assert all(70 <= n <= 130 for n in counts.values()), counts

    class NoRng:
        def choice(self, seq):
            raise AssertionError("spread 0 draws no step")

    spy0, clock0 = Spy(), Clock()
    p0 = BlipPlayer(spy0, clock0, NoRng())                       # type: ignore[arg-type]
    p0.on_say(say(BlipSpec("blips/a.ogg", 1, 0.0)))
    typed(p0, spy0, clock0, "abc", 1.0)
    assert [c[2:] for c in spy0.calls] == [(0.0, 0)] * 3


def test_ac_f06_09_silent_lines_and_set_enabled():
    rows = [("narration", say(None)), ("restored", say(HANA, restored=True)),
            ("voiced", say(HANA, voice="voice/hana_001.ogg"))]
    for name, cmd in rows:
        p, spy, clock = player()
        p.on_say(cmd)
        assert typed(p, spy, clock, "Hello there", 1.0) == [], name
    p, spy, clock = player()
    p.on_say(say(HANA))
    p.set_enabled(False)
    assert typed(p, spy, clock, "Hello", 1.0) == []
    p.set_enabled(False)
    p.on_say(say(HANA))                                   # off across lines too
    assert typed(p, spy, clock, "Hello", 1.0) == []
    p.glyph_shown(0, "H")
    p.set_enabled(True)
    assert typed(p, spy, clock, ", there", 1.0) == ["t", "e", "e"]   # the next eligible one
    p.set_enabled(True)                                   # already on: the count goes on
    assert typed(p, spy, clock, "abc", 1.0) == ["b"]
