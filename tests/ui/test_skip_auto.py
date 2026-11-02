"""F15 — the ``SkipAuto`` controller and its indicator in unit form (``specs/F15-skip-auto/
SPEC.md`` §4, §7; ``07`` I-1, I-8). AC-F15-07, 08, 10.

AC-F15-07 and 08 are unit ACs: ``SkipAuto`` runs on a stand-in textbox and stage that record
presses on its own clock, with a spy audio for the voice wait. The indicator (AC-F15-10)
draws through a test shell's real ``Painter`` and canvas. The integration ACs (01–06, 09, 11,
12) run on the real ports in ``tests/app/test_skip_auto_app.py``; AC-F15-14 is
``tests/core/test_config_skip_auto.py``.
"""

from types import SimpleNamespace

import pytest

from engine.render.frames import FrameSpec
from engine.render.typewriter import WaitKind
from engine.runtime.commands import Say
from engine.ui.builtin.skip_auto import SkipAuto, SkipAutoSettings, SkipIndicator
from engine.ui.focus import Box
from engine.ui.theme import measure_with
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import TestShell, UiHarness


def say(sid: str, *, restored: bool = False) -> Say:
    return Say(sid, None, None, None, (), "", restored=restored)


class FakeAudio:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, str | None]] = []
        self.voice = lambda sid: False

    def set_skipping(self, on: bool, *, resume: str | None = None) -> None:
        self.calls.append((on, resume))

    def voice_playing(self, sid: str | None = None) -> bool:
        return self.voice(sid)


# --- AC-F15-07, 08 — auto delay and voice wait (unit) -------------------------------------------

class UnitTextbox:
    hidden = False
    menu_waiting = False

    def __init__(self) -> None:
        self.shown = 0
        self.presses: list[float] = []
        self.sa: SkipAuto | None = None

    def focused(self) -> bool:
        return True

    def shown_count(self) -> int:
        return self.shown

    def press(self) -> None:
        self.presses.append(round(self.sa.now, 6))

    def complete_now(self) -> None:
        raise AssertionError("auto never completes")


class UnitStage:
    def __init__(self) -> None:
        self.wait_kind = None
        self.changes = 0
        self.settings = SimpleNamespace(reduce=False)
        self.presses: list[float] = []
        self.sa: SkipAuto | None = None

    def press(self) -> None:
        self.presses.append(round(self.sa.now, 6))

    def finish_now(self) -> None:
        raise AssertionError("auto never finishes a wait")

    drop_effects = finish_now


def unit(audio=None, **kw):
    textbox, stage = UnitTextbox(), UnitStage()
    sa = SkipAuto(textbox, stage, store=None, audio=audio, **kw)
    textbox.sa = stage.sa = sa
    sa.on_say(say("s/x"))
    sa.set_auto(True)
    return sa, textbox, stage


def tick(sa, seconds: float, dt: float = 0.01, *, frozen: bool = False) -> None:
    for _ in range(round(seconds / dt)):
        sa.update(dt, frozen=frozen)


def test_ac07_auto_delay():
    sa, tb, _ = unit()                            # 12 graphemes at defaults: 1.48 s
    tb.shown = 12
    sa.completed(False)
    tick(sa, 1.47)
    assert tb.presses == []
    tick(sa, 0.01)
    assert tb.presses == [1.48]
    sa, tb, _ = unit()                            # click-wait and page: graphemes since the stop
    tb.shown = 5
    sa.waiting(WaitKind.CLICK)
    tick(sa, 2.0)
    tb.shown = 12
    sa.glyph_shown(5, "x")
    sa.waiting(WaitKind.PAGE)
    tick(sa, 2.0)
    tb.shown = 20
    sa.completed(False)
    tick(sa, 2.0)
    assert tb.presses == [1.2, round(2.0 + 1.28, 6), round(4.0 + 1.32, 6)]
    sa, tb, _ = unit()                            # a completing player press counts all shown
    tb.shown = 3
    sa.glyph_shown(2, "c")
    tick(sa, 1.0)
    tb.shown = 12
    sa.completed(True)
    tick(sa, 2.0)
    assert tb.presses == [round(1.0 + 1.48, 6)]
    sa, tb, _ = unit()                            # scale 2, live next frame
    sa.settings = SkipAutoSettings(auto_scale=2)
    tb.shown = 12
    sa.completed(False)
    tick(sa, 4.0)
    assert tb.presses == [2.96]
    sa.settings = SkipAutoSettings(auto_scale=10)
    assert sa.auto_scale() == 4.0
    sa, tb, st = unit()                           # untimed pause: stage.press at delay
    st.wait_kind = "click"
    tick(sa, 0.01)                                # the frame the wait is first seen
    tick(sa, 0.99)
    assert st.presses == []
    tick(sa, 0.01)
    assert st.presses == [1.01] and tb.presses == []
    for kind in ("timed", "stage"):               # timed pause and transition: nothing
        sa, tb, st = unit()
        st.wait_kind = kind
        tick(sa, 10.0)
        assert st.presses == [] and tb.presses == []
    sa, tb, _ = unit()                            # 5 s frozen adds 5 s
    tb.shown = 12
    sa.completed(False)
    tick(sa, 1.0)
    tick(sa, 5.0, frozen=True)
    tick(sa, 0.47)
    assert tb.presses == []
    tick(sa, 0.01)
    assert tb.presses == [1.48]
    # I-1: a line timer pending when a wait starts is cancelled; nothing presses after it.
    sa, tb, st = unit()
    tb.shown = 12
    sa.completed(False)
    tick(sa, 0.5)
    st.wait_kind = "timed"
    tick(sa, 2.0)
    st.wait_kind = None
    tick(sa, 3.0)
    assert tb.presses == [] and st.presses == []


def test_ac08_auto_waits_for_the_lines_own_voice():
    cases = (
        (lambda sid: sid == "s/x" and sa.now < 3.0 - 1e-9, {}, 3.0),   # its voice to 3.0 s
        (lambda sid: sid is None, {}, 1.48),                           # only a replay plays
        (lambda sid: True, {"wait_for_voice": False}, 1.48),
        (None, {}, 1.48),                                              # no audio
        (lambda sid: True, {"settings": False}, 1.48),                 # F16 turns it off
    )
    for voice, kw, expected in cases:
        audio = None
        if voice is not None:
            audio = FakeAudio()
            audio.voice = voice
        settings = kw.pop("settings", None)
        sa, tb, _ = unit(audio, **kw)
        if settings is not None:
            sa.settings = SkipAutoSettings(auto_wait_voice=settings)
        tb.shown = 12
        sa.completed(False)
        tick(sa, 5.0)
        assert tb.presses == [expected], (kw, expected)



# --- AC-F15-10 — the corner indicator ------------------------------------------------------------

def test_ac10_indicator_pill_words_and_cache():
    shell = TestShell()
    harness = UiHarness(shell, window=(1920, 1080))             # device scale 1.5
    canvas = harness.canvas
    canvas.bind(harness.framebuffer, harness.viewport, harness.quality)
    sa, tb, _ = unit(skip_all=True)
    sa.set_auto(False)
    sa.indicator = SkipIndicator(shell)
    q = shell.theme.cfg.quick_menu
    painter = shell.painter
    shapes: list[tuple[Box, FrameSpec]] = []
    with pytest.MonkeyPatch.context() as mp, spy_draw_text(mp) as texts:
        real_shape = painter.shape

        def shape(box, spec, **kw):
            shapes.append((box, spec))
            real_shape(box, spec, **kw)

        mp.setattr(painter, "shape", shape)

        def draw() -> list[tuple[str, Box, FrameSpec]]:
            shapes.clear()
            texts.clear()
            sa.draw(canvas, box_shown=True)
            return [(t.text, b, s) for t, (b, s) in zip(texts, shapes, strict=True)]

        assert draw() == []                                     # both off
        assert sa.start_skip()
        builds = painter.builds
        drawn = [draw() for _ in range(3)]
        width = measure_with(shell.assets, shell.theme.font(q.text_size))("Skip", q.text_size)
        pill = Box(24, 24, width + 2 * q.side_padding, 28)
        look = FrameSpec(q.on.fill_color, q.fill_opacity, border_color=q.on.border_color,
                         border_width=q.on.border_width, corner_radius=q.corner_radius)
        assert drawn == [[("Skip", pill, look)]] * 3
        call = texts[0]
        assert (call.color, call.font.size, call.pos, call.options) == (
            q.text_color, q.text_size, pill.center, {"anchor": "center"})
        assert painter.builds == builds + 1                     # one cached pill for Skip
        sa.set_auto(True)
        assert [t for t, _, _ in draw()] == ["Skip"]            # both on: Skip
        sa.stop_skip()
        assert [t for t, _, _ in draw() + draw()] == ["Auto", "Auto"]
        assert painter.builds == builds + 2                     # ... and one for Auto
        tb.hidden = True
        assert draw() == []
