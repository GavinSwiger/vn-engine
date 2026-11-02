"""F23 s5a: ``layouts.minigame_frame`` (F23 ``03`` layout table, "Fit checks"; ``04`` §7.11).
AC-F23-30's unit rows with M20 metrics (20 units per character at 28). The Host U parts
(draw order, Tab, a hint change being a cut) belong to s4's host tests. Pure function."""

from engine.ui.focus import Box
from engine.ui.layouts import minigame_frame
from tests.fakes.fixed_font import FixedFont


def m20(text: str, size: int) -> float:
    return FixedFont(size).size(text)[0]


TWO_LINES = " ".join(["pairs"] * 12)          # 71 graphemes: two lines of 6 words at 36


def test_ac30_frame_layout_rows():
    # Heading and hint on, 100%: 03's drawing.
    f = minigame_frame(1.0, heading="Lantern game", hint="Find the pairs", measure=m20)
    assert f.heading == Box(24, 24, 12 * 23 + 40, 61)                  # pitch(32) + 16
    assert (f.heading_text, f.heading_size) == ("Lantern game", 32)
    assert f.hint == Box(480, 638, 320, 58)                             # 14 × 17 + 48 < 320
    assert f.hint_lines == ("Find the pairs",) and f.hint_size == 24
    assert f.content == Box(24, 101, 1232, 521)                         # y 101–622
    assert f.cue == (748, 638)                                          # hint right − 52, top
    # Both off.
    f = minigame_frame(1.0, heading=None, hint="", measure=m20)
    assert (f.heading, f.hint, f.hint_lines) == (None, None, ())
    assert f.content == Box(24, 24, 1232, 672) and f.cue == (1088, 668)
    # 150%: a 20-character title steps down to fit 560; a 2-line hint at 36.
    f = minigame_frame(1.5, heading="The Lantern Festival", hint=TWO_LINES, measure=m20)
    assert f.heading.h == 83 and f.heading.w <= 560
    assert f.heading_text == "The Lantern Festival" and 24 <= f.heading_size < 48
    assert f.heading_size % 2 == 0 and m20(f.heading_text, f.heading_size + 2) > 520
    assert len(f.hint_lines) == 2 and f.hint_size == 36 and f.hint.h == 2 * 50 + 24
    assert (f.content.y, f.content.bottom) == (123, 556)               # 03's fit check
    assert (f.content.w, f.content.h) == (1232, 433)
    assert f.cue == (f.hint.right - 52, f.hint.y)
    # A 1,000-character hint: 2 lines, the last ending "…", within 1000 − 48.
    f = minigame_frame(1.0, heading=None, hint=("word " * 200)[:1000], measure=m20)
    assert len(f.hint_lines) == 2 and f.hint_lines[-1].endswith("…")
    assert f.hint.w == 1000 and all(m20(line, 24) <= 952 for line in f.hint_lines)
    # A title too long even at 24 is cut with "…"; the plugin's own cue point wins.
    f = minigame_frame(1.0, heading="x" * 80, hint="h", measure=m20, cue_point=(300, 200))
    assert f.heading_size == 24 and f.heading_text.endswith("…") and f.heading.w <= 560
    assert f.cue == (300, 200)
