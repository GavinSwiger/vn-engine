"""F39 P2 — the game side of hot reload (``engine/app/hot_reload.py``;
``specs/F39-hot-reload/SPEC.md`` §4.1, §4.3, §5.1, §5.2): AC-F39-04 (game messages),
AC-F39-05 (collection), AC-F39-06 (§4.1's table, headless) and AC-F39-07 (bad frames).
AC-F39-08 is ``tests/runtime/test_rollback_carry.py``; AC-F39-09 is in
``tests/render/test_window.py``."""

import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from engine.app import hot_reload as hr
from engine.app.story import RuntimeStoryDriver
from engine.runtime.interpreter import Status
from engine.runtime.state import GameState
from engine.script.menu import Menu
from engine.ui.shell import Mode
from tests.runtime.story import advance, launched, load_files, start


# --- helpers -----------------------------------------------------------------------------------

def read_all(data: bytes, *, expect_resume: bool = False) -> hr.StdinReader:
    reader = hr.StdinReader(io.BufferedReader(io.BytesIO(data)),
                            expect_resume=expect_resume).start()
    reader.join(5)
    assert reader.closed.is_set()
    return reader


def line(obj: object) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode("ascii") + b"\n"


def frame(lines: list[bytes], *, lost: bool = False, states: int | None = None) -> bytes:
    body = b"".join(lines)
    return line({"v": 1, "msg": "resume", "bytes": len(body),
                 "states": len(lines) if states is None else states, "lost": lost}) + body


def text_at(interp) -> str:
    current = interp.current
    if type(current) is Menu:
        return current.question.text
    return getattr(current, "text", "")


def play_to(interp, text: str) -> None:
    for _ in range(100):
        if interp.status is Status.WAITING and text_at(interp) == text:
            return
        advance(interp)
    raise AssertionError(text)


class Ports:
    """Fake ``ResumePorts``: records what the screen did."""

    def __init__(self, interp, frame_obj=None) -> None:
        self.interp = interp
        self.driver_obj = RuntimeStoryDriver(interp) if interp is not None else None
        self.frame = frame_obj
        self.log: list[tuple] = []

    def ports(self) -> hr.ResumePorts:
        return hr.ResumePorts(
            take_frame=lambda: self.frame, driver=lambda: self.driver_obj,
            enter_game=lambda start: (self.log.append(("enter_game",)), start()),
            start_normally=lambda: self.log.append(("start_normally",)),
            notify=lambda text, kind: self.log.append(("notify", text, kind)),
            show_fatal_error=lambda error: self.log.append(("fatal", error)),
            keep=lambda lines: self.log.append(("keep", len(lines))))


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def run_screen(ports: Ports, clock: Clock | None = None) -> hr.ResumeScreen:
    screen = hr.ResumeScreen(ports.ports(), clock=clock or Clock())
    for _ in range(50):
        screen.update(1 / 60, is_top=True)
        if screen.done is not None:
            return screen
    raise AssertionError("the resume screen never finished")


def notes(ports: Ports) -> list[str]:
    return [entry[1] for entry in ports.log if entry[0] == "notify"]


# --- AC-F39-04: game messages ------------------------------------------------------------------

def test_ac_f39_04_game_messages(capsys, caplog):
    secret = "zz-secret-zz"
    data = b"".join([
        b'{"v":1,"msg":"reload","pad":"' + b"x" * 5000 + b'"}\n',          # too long
        b'{"v":1,"msg":"held","errors":2,"x":"\xc3\xa9"}\n',                # non-ASCII
        b'{"v":1,"msg":"reload"\n',                                         # bad JSON
        line({"v": 2, "msg": "reload"}), line({"v": True, "msg": "reload"}),  # v != 1
        line({"v": 1, "msg": "dance", "who": secret}),                      # unknown
        line({"v": 1, "msg": "held", "errors": 0}),
        line({"v": 1, "msg": "held", "errors": "3"}),
        line({"v": 1, "msg": "resume", "bytes": 0, "states": 0, "lost": False}),
        line({"v": 1, "msg": "held", "errors": 1}),
        line({"v": 1, "msg": "held", "errors": 2}),
        line({"v": 1, "msg": "reload"}), line({"v": 1, "msg": "reload"}),
        b'{"v":1,"msg":"reload"}',                                          # cut at EOF
    ])
    with caplog.at_level(logging.DEBUG):
        reader = read_all(data)                                             # EOF: quiet
        messages = reader.poll()
    assert messages == [hr.Held(1), hr.Held(2), hr.Reload(), hr.Reload()]
    assert reader.poll() == [] and reader.take_frame() is None

    shown, reloads = [], []
    asked = hr.handle_messages(messages, error_mode=False,
                               notify=lambda text, kind: shown.append((text, kind)),
                               reload=lambda: reloads.append(1))
    assert asked and reloads == [1]                                         # once per frame
    assert shown == [
        ("Story not updated: Studio found 1 problem. Fix it and save again.", "problem"),
        ("Story not updated: Studio found 2 problems. Fix them and save again.", "problem")]
    shown.clear()
    hr.handle_messages([hr.Held(3)], error_mode=True,
                       notify=lambda text, kind: shown.append(text), reload=lambda: None)
    assert shown == []                                                      # error mode

    out = capsys.readouterr()                                               # never echoed
    assert out.out == "" and out.err == ""
    assert not any(secret in r.getMessage() or "pad" in r.getMessage() for r in caplog.records)


# --- AC-F39-05: collection ---------------------------------------------------------------------

def test_ac_f39_05_collection(tmp_path, monkeypatch):
    body = "".join(f'    "Line {n}."\n' for n in range(1, 31))
    program = load_files(tmp_path / "long", {"main.vns": "label start:\n" + body})
    interp = start(program)
    for n in range(2, 26):
        play_to(interp, f"Line {n}.")
    checkpoint, t = interp.checkpoint(), interp.timeline
    lines = hr.collect_states(checkpoint, t)

    # Newest first, at most 20, no duplicate; each line parses back to an equal state.
    parsed = [hr.parse_state(each) for each in lines]
    expected = [checkpoint] + [t.states[i] for i in range(t.cursor - 1, -1, -1)][:19]
    assert len(lines) == 20 and parsed == expected
    assert [p.position for p in parsed] == [s.position for s in expected]
    assert len({p.position for p in parsed}) == 20
    assert parsed[0] == checkpoint and isinstance(parsed[0], GameState)

    # Over the byte cap the oldest are dropped.
    monkeypatch.setattr(hr, "FRAME_BYTES_MAX", sum(len(x) for x in lines[:3]))
    assert hr.collect_states(checkpoint, t) == lines[:3]
    monkeypatch.undo()

    # Depth 0 sends only the checkpoint.
    flat = start(program, rollback_steps=0)
    play_to(flat, "Line 4.")
    only = hr.collect_states(flat.checkpoint(), flat.timeline)
    assert [hr.parse_state(x) for x in only] == [flat.checkpoint()]

    # The App: the title, loading and before the first line send none.
    app = SimpleNamespace(story=RuntimeStoryDriver(interp), shell=SimpleNamespace(mode=Mode.GAME),
                          loading=False, error_mode=False)
    assert hr.story_states(app) == lines
    assert hr.story_states(SimpleNamespace(**{**vars(app), "loading": True})) == []
    assert hr.story_states(SimpleNamespace(**{**vars(app),
                                              "shell": SimpleNamespace(mode=Mode.TITLE)})) == []
    idle = SimpleNamespace(**{**vars(app), "story": RuntimeStoryDriver(launched(program))})
    assert hr.story_states(idle) == []

    # Error mode: the fatal hook's list, from the FAILED story, newest = the line before.
    failing = load_files(tmp_path / "fail", {"main.vns": 'label start:\n    "One."\n'
                                             '    "Two."\n    $ boom = 1 / 0\n    "Never."\n'})
    broken = start(failing)
    play_to(broken, "Two.")
    advance(broken)
    assert broken.status is Status.FAILED and broken.checkpoint() is None
    app = SimpleNamespace(story=RuntimeStoryDriver(broken), shell=SimpleNamespace(mode=Mode.GAME),
                          loading=False, error_mode=False)
    kept = [hr.parse_state(x) for x in hr.fatal_states(app)]
    assert [text for text in ("Two.", "One.")] == [
        failing.get(s.position).text for s in kept]


# --- AC-F39-06: where the preview continues (§4.1) ---------------------------------------------

V1 = """define greeting = "Hi"
default trust = 0
label start:
    "One."
    $ trust += 1
    "Two."
    "Three."
    "Five."
    scene black
    menu:
        "Pick?"
        "A":
            "Got A."
        "B":
            "Got B."
    "Four."
"""


def _carry(tmp_path: Path, text: str, at: str) -> list[bytes]:
    interp = start(load_files(tmp_path / "v1", {"main.vns": text}))
    play_to(interp, at)
    return hr.collect_states(interp.checkpoint(), interp.timeline)


def _resume(root: Path, text: str, lines: list[bytes]):
    interp = launched(load_files(root, {"main.vns": text}))
    ports = Ports(interp, hr.ResumeFrame(b"".join(lines), len(lines), False))
    screen = run_screen(ports)
    interp.run(10_000)
    return screen, ports, interp


def test_ac_f39_06_where_the_preview_continues(tmp_path):
    rows = [
        # (name, line on screen, edit, resumed at, note)
        ("other line, define, defaults", "Three.",
         lambda s: s.replace('"One."', '"Uno."').replace('"Hi"', '"Hello"')
         .replace("default trust = 0", "default trust = 7\ndefault mood = \"calm\""),
         "Three.", hr.NOTE_UPDATED),
        ("line reworded", "Three.", lambda s: s.replace('"Three."', '"Three!"'),
         "Three!", hr.NOTE_UPDATED),
        ("lines added above", "Three.",
         lambda s: s.replace('    "One."', '    "Zero."\n    "One."'),
         "Three.", hr.NOTE_UPDATED),
        ("menu choices changed", "Pick?",
         lambda s: s.replace('        "B":', '        "C":\n            "Got C."\n        "B":'),
         "Pick?", hr.NOTE_UPDATED),
        ("deleted, a line at its place", "Two.", lambda s: s.replace('    "Two."\n', ""),
         "Three.", hr.NOTE_UPDATED),
        ("deleted, a scene at its place", "Five.", lambda s: s.replace('    "Five."\n', ""),
         "Three.", hr.NOTE_WENT_BACK),
    ]
    for n, (name, at, edit, resumed, note) in enumerate(rows):
        lines = _carry(tmp_path / f"r{n}", V1, at)
        screen, ports, interp = _resume(tmp_path / f"r{n}" / "v2", edit(V1), lines)
        assert ports.log[0] == ("enter_game",), name
        assert text_at(interp) == resumed and interp.status is Status.WAITING, name
        assert notes(ports) == [note], name
        assert interp.timeline.cursor == len(interp.timeline.states) - 1 >= 1, name  # carried
        if n == 0:                                      # the new define and default; trust kept
            assert interp.G["greeting"] == "Hello" and interp.G["mood"] == "calm"
            assert interp.G["trust"] == 1
        if name == "menu choices changed":
            assert len(interp.choices.waiting.pickable) == 3

    # The scene renamed: no carried line exists, a normal start (N3).
    two = 'label start:\n    jump scene_a\nlabel scene_a:\n    "In A."\n    "A two."\n'
    lines = _carry(tmp_path / "gone", two, "A two.")
    screen, ports, interp = _resume(tmp_path / "gone" / "v2",
                                    two.replace("scene_a", "scene_b"), lines)
    assert ports.log == [("start_normally",), ("notify", hr.NOTE_RESTARTED, "info")]
    assert screen.done == "restarted" and interp.status is Status.IDLE

    # On the title (no states): a normal start with N1.
    ports = Ports(None, hr.ResumeFrame(b"", 0, False))
    run_screen(ports)
    assert ports.log == [("start_normally",), ("notify", hr.NOTE_UPDATED, "info")]


# --- AC-F39-07: bad frames ---------------------------------------------------------------------

def test_ac_f39_07_bad_frames(tmp_path, monkeypatch):
    # Missing for 5 s: a normal start with N4.
    clock = Clock()
    ports = Ports(None, None)
    screen = hr.ResumeScreen(ports.ports(), clock=clock)
    screen.update(0.0, is_top=True)
    clock.now += hr.RESUME_WAIT_S - 0.01
    screen.update(0.0, is_top=True)
    assert screen.done is None and ports.log == []
    clock.now += 0.02
    screen.update(0.0, is_top=True)
    assert ports.log == [("start_normally",), ("notify", hr.NOTE_LOST, "info")]

    # Short, over the caps, a bad header, a lost frame, no frame at all: a bad frame, at once.
    good = _carry(tmp_path / "a", V1, "Three.")
    body = b"".join(good)
    cases = [
        line({"v": 1, "msg": "resume", "bytes": len(body) + 10, "states": 3, "lost": False})
        + body,                                                             # short (EOF)
        line({"v": 1, "msg": "resume", "bytes": hr.FRAME_BYTES_MAX + 1, "states": 1,
              "lost": False}),                                              # over 32 MiB
        line({"v": 1, "msg": "resume", "bytes": 10, "states": 21, "lost": False}) + b"x" * 10,
        b"garbage\n", b"",
    ]
    for data in cases:
        got = read_all(data, expect_resume=True).take_frame()
        assert got is not None and got.body is None, data[:80]
        ports = Ports(None, got)
        run_screen(ports)
        assert ports.log == [("start_normally",), ("notify", hr.NOTE_LOST, "info")]
    lost = read_all(frame([], lost=True), expect_resume=True).take_frame()
    assert lost == hr.ResumeFrame(b"", 0, True)
    ports = Ports(None, lost)
    run_screen(ports)
    assert notes(ports) == [hr.NOTE_LOST]
    # A body that doesn't hold its declared states, or a state line over its cap.
    assert hr.split_frame(body, len(good) + 1) is None
    monkeypatch.setattr(hr, "STATE_LINE_MAX", 10)
    assert hr.split_frame(body, len(good)) is None
    monkeypatch.undo()
    # A refused body of a known length is skipped: later messages still arrive.
    reader = read_all(line({"v": 1, "msg": "resume", "bytes": 5, "states": 0, "lost": False})
                      + b"12345" + line({"v": 1, "msg": "reload"}), expect_resume=True)
    assert reader.take_frame().body is None and reader.poll() == [hr.Reload()]

    # DAMAGED and NEWER states are skipped: the next carried line is used (N2).
    newer = json.loads(good[0])
    newer["format"] = 99
    damaged = b'{"format":1,"position":\n'
    bad_first = [damaged, json.dumps(newer, separators=(",", ":")).encode() + b"\n", *good[1:]]
    reader = read_all(frame(bad_first) + line({"v": 1, "msg": "held", "errors": 1}),
                      expect_resume=True)
    got = reader.take_frame()
    assert got.states == len(bad_first) and reader.poll() == [hr.Held(1)]
    interp = launched(load_files(tmp_path / "b", {"main.vns": V1}))
    ports = Ports(interp, got)
    run_screen(ports)
    interp.run(10_000)
    assert text_at(interp) == "Two." and notes(ports) == [hr.NOTE_WENT_BACK]

    # None usable: a normal start with N4, no exception.
    ports = Ports(launched(load_files(tmp_path / "c", {"main.vns": V1})),
                  hr.ResumeFrame(damaged * 2, 2, False))
    screen = run_screen(ports)
    assert screen.done == "lost"
    assert ports.log == [("start_normally",), ("notify", hr.NOTE_LOST, "info")]
