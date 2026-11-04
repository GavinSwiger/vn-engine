"""F50 Timing assist, step 3: AC-F50-07 (SPEC §6), Studio's Effects & comfort ▸ Comfort
field and the Settings page words, on a copy of the sample game."""

import pytest

from engine.tools.editor import settingsmodel as sm

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_settings import (  # noqa: E402
    config_text,
    open_settings,
    sample_game,
)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

LABELS = ["Normal", "Slower (twice the time)", "No time limits"]
HINT = "The Timing assist a new player starts with. Players change it on the Settings page."


def test_ac_f50_07_studio_comfort_field_and_words(studio, tmp_path):
    comfort = next(s for s in sm.page("effects").sections if s.title == "Comfort")
    assert [f.path for f in comfort.fields] == ["effects.reduce", "effects.timing_assist"]
    field = comfort.fields[1]
    assert (field.label, field.help, field.widget.kind) == (
        "Timing assist for new players", HINT, "choice")
    assert [field.widget.option_text(o) for o in field.widget.options] == LABELS
    words = next(s for s in sm.page("words").sections if s.title == "Player's Settings page")
    paths = [f.path for f in words.fields]
    at = paths.index("words.reduce_motion")
    assert paths[at + 1:at + 5] == ["words.timing_assist", "words.timing_normal",
                                    "words.timing_slower", "words.timing_off"]
    for key in sm.all_keys():                       # the Settings key coverage rule
        assert key in sm.fields_by_path() or sm.text_only(key) or sm.on_looks_page(key), key

    ed = studio(sample_game(tmp_path), mapped=True)
    pane = open_settings(ed, "effects")
    shown = pane.shown_fields["effects.timing_assist"]
    assert shown.row.label.cget("text") == "Timing assist for new players"
    assert HINT in shown.row.hint.cget("text")
    assert list(shown.widget.box.cget("values")) == LABELS
    assert shown.widget.var.get() == "Normal"
    shown.widget.pick("slower")
    ed.root.update()
    text = config_text(ed)
    assert 'timing_assist = "slower"' in text
    assert text.index("[effects]") < text.index('timing_assist = "slower"')
    pane = open_settings(ed, "effects")
    assert pane.shown_fields["effects.timing_assist"].widget.var.get() == (
        "Slower (twice the time)")
