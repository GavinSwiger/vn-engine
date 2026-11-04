"""F50 Timing assist, step 1: AC-F50-04 (UI-F50-01, 07 I-5): the Settings page's Timing
assist row, a three-stop slider named by words, between Reduce motion and the Text heading."""

import pygame

from engine.ui.nav import InputKind
from engine.ui.widgets import Slider
from tests.fakes.draw_spy import spy_draw_text
from tests.ui.test_settings_page import H, Rig, ys

WORDS = ("Normal", "Slower", "No time limits")


def test_ac_f50_04_settings_row(monkeypatch):
    for pct in (100, 150):
        rig = Rig(text_size_pct=pct)
        page = rig.open()
        order = [item.word for item in page.column.items]
        at = order.index("timing_assist")
        assert order[at - 1:at + 2] == ["reduce_motion", "timing_assist", "settings_text"]
        row = rig.row("timing_assist")
        assert isinstance(row, Slider) and (row.lo, row.hi, row.step) == (0, 2, 1)
        assert row.label() == "Timing assist"
        positions = ys(page)
        assert positions["reduce_motion"] < positions["timing_assist"] < positions[
            "settings_text"]
        # Every stop's word is drawn whole (no "…") in the value slot, at 100 % and 150 %.
        rig.menu.scope.focus(row, InputKind.KEYS)
        for value, word in enumerate(WORDS):
            rig.port.values["timing_assist"] = value
            assert row.value_text(row.value) == word
            with spy_draw_text(monkeypatch) as calls:
                rig.frame()
            drawn = [c for c in calls if c.text == word]
            assert drawn, (pct, word)
            fit = rig.shell.painter.fit(word, "slider", row.value_width)
            assert fit.text == word, (pct, word)
            assert row.bar_span()[1] < row.box.right - 32 - row.value_width

    # Keys and clicks store at once.
    rig = Rig()
    rig.open()
    row = rig.row("timing_assist")
    port = rig.port
    rig.menu.scope.focus(row, InputKind.KEYS)
    for key, want in ((pygame.K_RIGHT, 1), (pygame.K_RIGHT, 2), (pygame.K_RIGHT, 2),
                      (pygame.K_LEFT, 1), (pygame.K_HOME, 0), (pygame.K_END, 2)):
        rig.frame(H.key(key))
        assert port.values["timing_assist"] == want, key
    assert port.calls == [("set", "timing_assist", v) for v in (1, 2, 1, 0, 2)]
    x0, x1 = row.bar_span()
    by = row.box.y + 40
    for x, want in ((x0, 0), (x0 + (x1 - x0) * 0.45, 1), (x1, 2), (x0 + (x1 - x0) * 0.2, 0)):
        rig.h.click((x, by))
        assert port.values["timing_assist"] == want, x

    # Changed words show.
    rig = Rig(words={"timing_assist": "Zeitlimits", "timing_slower": "Langsamer",
                     "timing_off": "Keine Zeitlimits"}, timing_assist=1)
    rig.open()
    row = rig.row("timing_assist")
    assert row.label() == "Zeitlimits" and row.value_text(1) == "Langsamer"
    assert row.value_text(2) == "Keine Zeitlimits" and row.value_text(0) == "Normal"
