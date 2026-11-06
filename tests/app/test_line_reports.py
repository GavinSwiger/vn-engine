"""Line reports, the game side (``core/editorreport.py`` "Line reports"): a dev run with
``--report-to-editor`` writes ``ending`` each time an ``ending`` line runs and ``at`` when the
story's line changes, at most ``AT_PER_S`` a second. Every line is decoded with Studio's own
``decode_report``, so both sides keep to the same shape."""

import io
from types import SimpleNamespace

from engine.app.editor_link import EditorLink
from engine.core.editorreport import AT_PER_S, GAME_EVENT_TEXT_MAX
from engine.tools.editor.preview import GAME, GameEvent, decode_report
from tests.runtime.endings_story import drive, load_e, store_with


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def link_with_clock() -> tuple[EditorLink, io.BytesIO, Clock]:
    out, clock = io.BytesIO(), Clock()
    link = EditorLink(out)
    link.clock = clock
    return link, out, clock


def events(out: io.BytesIO) -> list[GameEvent]:
    found = []
    for line in out.getvalue().splitlines():
        decoded = decode_report(line)
        assert isinstance(decoded, tuple) and decoded[0] == GAME, line
        found.append(decoded[1])
    return found


def stmt(ref: str, line: int, label: str) -> SimpleNamespace:
    return SimpleNamespace(file=SimpleNamespace(ref=ref), line=line, label=label)


def app_on(interp, *, dev: bool = True) -> SimpleNamespace:
    return SimpleNamespace(story=SimpleNamespace(interp=interp), dev=dev, error_mode=False,
                           shell=None)


def test_an_ending_run_is_recorded_on_the_interpreter_and_reported_once(tmp_path):
    interp, _commands = drive(load_e(tmp_path / "g"), store_with())
    count, name, title = interp.ending_reached
    assert (count, name) == (1, "sad") and isinstance(title, str) and title
    link, out, _clock = link_with_clock()
    link.update(app_on(interp))
    link.update(app_on(interp))                 # the same ending: not again
    (event,) = events(out)
    assert event == GameEvent("ending", {"id": "sad", "title": title})


def test_at_is_sent_when_the_line_changes_at_most_ten_a_second():
    interp = SimpleNamespace(ending_reached=None, current=stmt("script/main.vns", 3, "start"))
    link, out, clock = link_with_clock()
    app = app_on(interp)
    link.update(app)
    link.update(app)                            # the same line: nothing
    interp.current = stmt("script/main.vns", 4, "start")
    clock.now += 0.02
    link.update(app)                            # too soon: held
    interp.current = stmt("script/bridge.vns", 14, "bridge")
    clock.now += 1.0 / AT_PER_S
    link.update(app)                            # the newest place wins; line 4 is skipped
    assert [e.data for e in events(out)] == [
        {"file": "script/main.vns", "line": 3, "scene": "start"},
        {"file": "script/bridge.vns", "line": 14, "scene": "bridge"}]


def test_no_line_reports_outside_dev_runs_or_without_a_story():
    interp = SimpleNamespace(ending_reached=(1, "e", "E"), current=stmt("script/a.vns", 1, "s"))
    link, out, _clock = link_with_clock()
    link.update(app_on(interp, dev=False))
    link.update(SimpleNamespace(story=None, dev=True, error_mode=False, shell=None))
    assert out.getvalue() == b""


def test_long_texts_are_cut_and_still_decode():
    long = "x" * (GAME_EVENT_TEXT_MAX + 50)
    interp = SimpleNamespace(ending_reached=(1, "e", long), current=None)
    link, out, _clock = link_with_clock()
    link.update(app_on(interp))
    (event,) = events(out)
    assert len(event.data["title"]) == GAME_EVENT_TEXT_MAX


def test_studio_drops_line_reports_of_the_wrong_shape():
    good = b'VN-EDITOR-REPORT {"v":1,"event":"at","file":"script/a.vns","line":2,"scene":"s"}'
    assert decode_report(good) == (GAME, GameEvent("at", {"file": "script/a.vns", "line": 2,
                                                          "scene": "s"}))
    for bad in (b'{"v":1,"event":"at","file":"script/a.vns","line":0,"scene":"s"}',
                b'{"v":1,"event":"at","file":"","line":2,"scene":"s"}',
                b'{"v":1,"event":"at","file":"a","line":true,"scene":"s"}',
                b'{"v":1,"event":"at","file":"a","line":2,"scene":"s","x":1}',
                b'{"v":1,"event":"ending","id":"","title":"t"}',
                b'{"v":1,"event":"ending","id":"e","title":3}'):
        assert decode_report(b"VN-EDITOR-REPORT " + bad) is None, bad
