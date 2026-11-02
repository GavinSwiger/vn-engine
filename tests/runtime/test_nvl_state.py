"""F17 ``runtime/nvl.py`` and ``GameState.nvl``: the recording caps and shared lines
(``06-acceptance.md`` AC-F17-06), and the JSON form and its validation (AC-F17-07)."""

import json
import math
from dataclasses import replace

import pytest

from engine.runtime.commands import BASE_STYLE, NvlLine, Say, Span, Style, TaggedText
from engine.runtime.nvl import (EMPTY_NVL, NVL_NAME_MAX, NVL_SPANS_MAX, NVL_TEXT_MAX,
                                NvlState, line_of)
from engine.runtime.state import GameState, StateInvalid
from tests.fakes.fixed_font import tagged
from tests.runtime.nvl_story import F17, bursts, load_n

BOLD = Style(bold=True)
PAIR = chr(0xD83D) + chr(0xDE00)           # U+1F600 as two code units (lone surrogates)


def _say(body: TaggedText, *, name: str | None = None, color: str | None = None) -> Say:
    return Say("start/0123456789ab", "hana" if name is not None else None, name, color, (),
               "x", body=body)


def _text(spans) -> int:
    return sum(len(s.text) for s in spans)


# --- AC-F17-06 — recording caps and shared lines -----------------------------------------------

def _rows() -> list:
    def body(*spans: Span) -> TaggedText:
        return TaggedText(spans)

    alternating = [Span("a", BOLD if i % 2 else BASE_STYLE) for i in range(NVL_SPANS_MAX + 1)]
    return [
        ("marks", _say(tagged("A{pause=0.5}B{pause}C{speed=0.5}D{/speed}"))),
        ("12000", _say(body(Span("a" * NVL_TEXT_MAX, BASE_STYLE)))),
        ("12001", _say(body(Span("a" * 6_000, BASE_STYLE), Span("b" * 6_001, BOLD)))),
        ("4000", _say(body(*alternating[:NVL_SPANS_MAX]))),
        ("4001", _say(body(*alternating))),
        ("name200", _say(body(Span("x", BASE_STYLE)), name="N" * NVL_NAME_MAX)),
        ("name201", _say(body(Span("x", BASE_STYLE)), name="N" * (NVL_NAME_MAX + 1))),
        ("color", _say(body(Span("x", BASE_STYLE)), name="Hana", color="#A02860")),
        ("no color", _say(body(Span("x", BASE_STYLE)), name="Hana", color=None)),
    ]


def test_ac_f17_06_recording_caps_and_shared_lines(tmp_path):
    for row, say in _rows():
        line = line_of(say)
        if row == "marks":
            assert line.spans == (Span("ABCD", BASE_STYLE),)        # marks dropped, speed 1.0
        elif row in ("12000", "4000", "name200", "no color"):
            assert line.spans == say.body.plain() and line.name == (say.name or "")
            assert line.color is None
        elif row == "12001":
            assert _text(line.spans) <= NVL_TEXT_MAX
            assert line.spans[-1].text.endswith("…") and line.spans[-1].style == BOLD
        elif row == "4001":
            assert len(line.spans) == NVL_SPANS_MAX and line.spans[-1].text.endswith("…")
            assert line.spans[:-1] == say.body.plain()[:NVL_SPANS_MAX - 1]
        elif row == "name201":
            assert len(line.name) == NVL_NAME_MAX and line.name.endswith("…")
        elif row == "color":
            assert line.color == "#A02860" and line.name == "Hana"
        state = NvlState(True, (line,))
        assert NvlState.from_json(json.loads(json.dumps(state.to_json()))) == state, row
        assert state.save_problem() is None, row
    plain = line_of(_say(TaggedText((Span("x", BASE_STYLE),)), name="Hana"))
    assert NvlState(True, (replace(plain, name=PAIR),)).save_problem() == "lone_surrogate"
    assert NvlState(True, (replace(plain, spans=(Span(f"a{PAIR}", BASE_STYLE),)),)
                    ).save_problem() == "lone_surrogate"
    # Run N: the checkpoints at lines 9 and 10 share the earlier lines (TR-F17-05).
    _, _, states = bursts(load_n(tmp_path / "n"))
    at9, at10 = states[2].nvl.page, states[3].nvl.page
    assert at9[0] is at10[0] and at9[1] is at10[1] and len(at10) == 3


# --- AC-F17-07 — JSON and validation -----------------------------------------------------------

def _line(**changes) -> dict:
    line = {"sid": "start/0123456789ab", "name": "", "color": None,
            "spans": [{"text": "a"}]}
    line.update(changes)
    return line


class _Str(str):
    pass


def _refused() -> list:
    one = _line()
    return [
        {"on": 1, "page": []}, {"on": "ZZMARK", "page": []}, {"on": True},
        {"on": True, "page": [], "ZZMARK": 1},
        {"on": False, "page": [one]}, {"on": True, "page": [one] * 33},
        {"on": True, "page": [{**one, "ZZMARK": 1}]},
        {"on": True, "page": [{k: v for k, v in one.items() if k != "color"}]},
        {"on": True, "page": [_line(sid=5)]},
        {"on": True, "page": [_line(sid=_Str("start/0123456789ab"))]},
        {"on": True, "page": [_line(sid="ZZMARK/" + "x" * 1_018)]},
        {"on": True, "page": [_line(name=None)]},
        {"on": True, "page": [_line(name="ZZMARK" + "n" * 195)]},
        *({"on": True, "page": [_line(color=c)]}
          for c in ("ZZMARK", "#12345", "#1234567", "#GGGGGG")),
        {"on": True, "page": [_line(spans=[{"text": "a"}] * (NVL_SPANS_MAX + 1))]},
        {"on": True, "page": [_line(spans=[{"text": ""}])]},
        {"on": True, "page": [_line(spans=[{"text": "ZZMARK" + "a" * 5_994},
                                           {"text": "b" * 6_001, "bold": True}])]},
        {"on": True, "page": [_line(spans=[{"text": "ZZMARK", "underline": True}])]},
        *({"on": True, "page": [_line(spans=[{"text": "ZZMARK", **style}])]}
          for style in ({"bold": False}, {"bold": 1}, {"italic": "ZZMARK"},
                        {"size": 1.0}, {"size": 0.49}, {"size": 2.01}, {"size": math.nan},
                        {"color": "#E0505"})),
    ]


def test_ac_f17_07_json_and_validation(tmp_path):
    _, _, states = bursts(load_n(tmp_path / "n"))
    for state in states:
        data = state.to_json()
        assert data["format"] == 1 and "nvl" in data
        assert GameState.from_json(json.loads(json.dumps(data, ensure_ascii=True))) == state
    # A span writes only its non-default keys; 04 §4's example re-writes byte-equal.
    example = (F17 / "states" / "example.json").read_text(encoding="utf-8")
    data = json.loads(example)
    again = GameState.from_json(data).to_json()
    del again["items"]                      # F21's key, always written, came after the example
    del again["minigame"]                   # F23's likewise
    del again["flow"]                       # F20's likewise
    del again["glitch"]                     # F28's likewise
    assert json.dumps(again, ensure_ascii=True, indent=1) + "\n" == example
    assert data["nvl"]["page"][0]["spans"][1] == {"text": "slowest", "italic": True}
    italic = GameState.from_json(data).nvl.page[0].spans[1]
    assert italic == Span("slowest", Style(italic=True))
    full = NvlState(True, (NvlLine("s/0", "", None, (
        Span("a", Style(bold=True, italic=True, color="#9A1C14", size=1.5)),)),))
    assert full.to_json()["page"][0]["spans"] == [
        {"text": "a", "bold": True, "italic": True, "color": "#9A1C14", "size": 1.5}]
    # A state without "nvl" (before F17) is in ADV with an empty page.
    base = states[3].to_json()
    del base["nvl"]
    assert GameState.from_json(base).nvl is EMPTY_NVL
    # Every refused row: StateInvalid("nvl"), nothing echoed.
    for value in _refused():
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**base, "nvl": value})
        assert caught.value.reason == "nvl", value
        assert str(caught.value) == "the story state is not valid (nvl)"
        assert "ZZMARK" not in str(caught.value) and "ZZMARK" not in repr(caught.value)
    # Accepted: an empty line, and 32 lines.
    assert GameState.from_json({**base, "nvl": {"on": True, "page": [_line(spans=[])]}}
                               ).nvl.page[0].spans == ()
    assert len(GameState.from_json({**base, "nvl": {"on": True, "page": [_line()] * 32}}
                                   ).nvl.page) == 32


@pytest.mark.slow
def test_ac_f17_07_caps_round_trip_ascii(tmp_path):
    """``slow``: 32 lines × 12,000 code points of non-ASCII and astral text round-trip
    through ``ensure_ascii``."""
    text = ("祭り😀" * 4_000)[:NVL_TEXT_MAX]
    state = NvlState(True, tuple(NvlLine(f"s/{i}", "ハナ", "#A02860", (Span(text, BOLD),))
                                 for i in range(32)))
    written = json.dumps(state.to_json(), ensure_ascii=True)
    assert written.isascii()
    assert NvlState.from_json(json.loads(written)) == state
