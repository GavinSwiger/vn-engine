"""Line reports, Studio's side: the preview runner keeps the game's ``ending`` and ``at``
reports, and ``RunWiring.on_game_event`` hands them to each listener (see the module
docstring of ``runwiring``)."""

import sys
import time

from engine.app.editor_link import encode_line
from engine.tools.editor.preview import GameEvent, PreviewRunner, PreviewState
from engine.tools.editor.runwiring import RunWiring


def test_the_runner_passes_line_reports_on():
    lines = [{"v": 1, "event": "started"},
             {"v": 1, "event": "at", "file": "script/main.vns", "line": 3, "scene": "start"},
             {"v": 1, "event": "ending", "id": "true_end", "title": "Together"},
             {"v": 1, "event": "at", "file": "x", "line": -1, "scene": ""}]      # bad: dropped
    script = "import sys\n" + "".join(
        f"sys.stdout.buffer.write({encode_line(obj) + chr(10).encode()!r})\n" for obj in lines)
    runner = PreviewRunner(forward=lambda line: None)
    try:
        runner.start([sys.executable, "-c", script])
        end, seen = time.monotonic() + 15, []
        while time.monotonic() < end and PreviewState.CLOSED not in seen:
            seen += [e.state for e in runner.poll()]
            time.sleep(0.02)
        assert PreviewState.CLOSED in seen
        assert runner.game_events() == [
            GameEvent("at", {"file": "script/main.vns", "line": 3, "scene": "start"}),
            GameEvent("ending", {"id": "true_end", "title": "Together"})]
        assert runner.game_events() == []
    finally:
        runner.stop(timeout_s=1.0)


class FakeRunner:
    def __init__(self) -> None:
        self.waiting: list[GameEvent] = []

    def game_events(self) -> list[GameEvent]:
        events, self.waiting = self.waiting, []
        return events


class Wiring(RunWiring):
    def __init__(self) -> None:
        self._runner = FakeRunner()


def test_on_game_event_calls_every_listener_in_order_and_unsubscribes():
    wiring, got, other = Wiring(), [], []
    stop = wiring.on_game_event(lambda kind, data: got.append((kind, data)))

    def broken(kind, data):
        raise RuntimeError("a listener's bug")

    wiring.on_game_event(broken)
    wiring.on_game_event(lambda kind, data: other.append(kind))
    wiring.runner.waiting = [GameEvent("ending", {"id": "e", "title": "E"}),
                             GameEvent("at", {"file": "script/a.vns", "line": 2,
                                              "scene": "s"})]
    wiring._poll_game_events()
    assert got == [("ending", {"id": "e", "title": "E"}),
                   ("at", {"file": "script/a.vns", "line": 2, "scene": "s"})]
    assert other == ["ending", "at"]             # one failing listener stops no other
    got[0][1]["id"] = "changed"                  # each call gets its own dict
    stop()
    stop()                                       # twice is fine
    wiring.runner.waiting = [GameEvent("ending", {"id": "f", "title": "F"})]
    wiring._poll_game_events()
    assert len(got) == 2 and other == ["ending", "at", "ending"]
