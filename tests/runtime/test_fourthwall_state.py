"""F30 s3 — the title and flagged NVL spans as saved state (F30 ``06-acceptance.md``
AC-F30-13, AC-F30-16; ``04`` §3, §4.2, §6.1 step 3, §8; TR-F30-01, 02; SEC-F30-09(a)).

Run H on ``walk/`` and ``walk-nvl/`` (``fourthwall_story.py``); saves are made by the tests
from real checkpoints."""

import json
import logging

import pytest

from engine.persist import saves
from engine.runtime.commands import Advance, Span, Style, WaitDone, WindowTitle
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import STATE_FORMAT, GameState, StateInvalid
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)
from tests.persist.save_support import make_save
from tests.runtime.effects_story import of_type, take_all
from tests.runtime.fourthwall_story import F30, launched, walk
from tests.runtime.effects_story import load_game, write_game

FLAG = Style(username=True)


def _at_line(program, n: int):
    """An interpreter waiting at the ``n``-th line (1-based), crashes passed."""
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    for _ in range(n - 1):
        if interp.waiting_for is not None:
            interp.post(WaitDone(interp.waiting_for))
            interp.run(10_000)
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        if interp.waiting_for is not None:
            interp.post(WaitDone(interp.waiting_for))
            interp.run(10_000)
    take_all(interp)
    return interp


def _back(data: dict) -> GameState:
    return GameState.from_json(json.loads(json.dumps(data, ensure_ascii=True)))


def test_ac_f30_13_window_title_and_flagged_spans_round_trip():
    assert STATE_FORMAT == 1
    w2 = _at_line(walk(), 2).checkpoint()
    base = w2.to_json()
    assert w2.window_title == "She is here" and base["window_title"] == "She is here"
    none = _at_line(walk(), 1).checkpoint()
    assert none.window_title is None and "window_title" not in none.to_json()
    assert _back(none.to_json()) == none
    for title in ("", "x" * 100, "\ud800", "Windows Security Alert"):
        state = _back({**base, "window_title": title})
        assert state.window_title == title and _back(state.to_json()) == state
    assert _back({**base, "window_title": None}).window_title is None
    for bad in ("Q" * 101, 5, True, [], {}):
        with pytest.raises(StateInvalid) as refused:
            _back({**base, "window_title": bad})
        assert refused.value.reason == "window_title" and "QQ" not in str(refused.value)

    # walk-nvl: the W2 line's record keeps the flagged span, written last in the span.
    page = _at_line(walk("walk-nvl"), 2).checkpoint().to_json()
    spans = page["nvl"]["page"][1]["spans"]
    assert spans == [{"text": "I know who you are, "}, {"text": "friend", "username": True},
                     {"text": "."}]
    flagged = {"text": "friend", "italic": True, "effect": "wave:small", "username": True}

    def with_spans(*spans):
        data = json.loads(json.dumps(page))
        data["nvl"]["page"][1]["spans"] = list(spans)
        return data
    state = _back(with_spans(flagged))
    assert list(state.to_json()["nvl"]["page"][1]["spans"][0]) == ["text", "italic", "effect",
                                                                   "username"]
    every = with_spans({"text": "friend", "username": True}, {"text": "pal", "username": True})
    assert _back(every).nvl.page[1].spans == (Span("friend", FLAG), Span("pal", FLAG))
    assert _back(every).to_json() == _back(_back(every).to_json()).to_json()
    for bad in (False, 1, "true", None):
        with pytest.raises(StateInvalid) as refused:
            _back(with_spans({"text": "friend", "username": bad}))
        assert refused.value.reason == "nvl"
    for size in (10_000, 13_000):                           # F17's caps decide, as without
        plain, named = ({"text": "a" * size}, {"text": "a" * size, "username": True})
        outcomes = []
        for span in (plain, named):
            try:
                _back(with_spans(span))
                outcomes.append("ok")
            except StateInvalid as e:
                outcomes.append(e.reason)
        assert outcomes[0] == outcomes[1], size


def test_ac_f30_16_a_saved_title_must_be_one_the_script_wrote(tmp_path, caplog):
    text = (F30 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")
    braced = load_game(write_game(tmp_path / "braced", text + 'label unused:\n'
                                  '    effect window_title "a {{b"\n'))
    w2 = _at_line(walk(), 2).checkpoint().to_json()
    rows = [(walk, "She is here", "She is here"),
            (walk, "Windows Security Alert", None), (walk, "\ud800", None), (walk, "", None),
            (walk, "Old title", None), (lambda: braced, "a {b", "a {b")]
    caplog.set_level(logging.DEBUG, logger="vn")
    for make, saved, expected in rows:
        line = json.dumps({**w2, "window_title": saved}).encode("ascii") + b"\n"
        verdict = saves.parse_state_line(line, (0, len(line)))
        assert verdict.status is saves.SlotStatus.OK, saved
        read = saves.parse_full(make_save(verdict.state), game_id=None)
        program = make()
        interp = _at_line(program, 2)                       # the live title is set
        assert interp.window_title == "She is here"
        caplog.clear()
        assert interp.restore(read.state).result is RestoreResult.OK, saved
        burst = take_all(interp)
        assert of_type(burst, WindowTitle) == [WindowTitle(expected)], saved
        assert interp.window_title == expected and interp.checkpoint().window_title == expected
        notes = [r.getMessage() for r in caplog.records if "window title" in r.getMessage()]
        assert len(notes) == (0 if expected == saved else 1), saved
        assert not saved or all(saved not in note for note in notes)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING], saved
