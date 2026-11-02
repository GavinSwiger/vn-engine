"""F29 AC-F29-05: the NVL page record carries each span's effect as ``"effect":
"kind:strength"`` (TR-F29-01; ``07`` §2.1, I-1), at ``STATE_FORMAT`` 1. Bodies built by
hand (F29 step 1: no tag makes an effect yet)."""

import json
from pathlib import Path

import pytest

from engine.runtime.commands import NvlLine, Say, Span, Style, TaggedText, TextEffect
from engine.runtime.nvl import EFFECT_KEYS, NvlState, line_of
from engine.runtime.state import STATE_FORMAT, GameState, StateInvalid
from engine.script import texttags

EXAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "F17" / "states" / "example.json"
NINE = [TextEffect(kind, strength) for kind in ("shake", "wave", "glitch")
        for strength in ("small", "medium", "large")]


def _page(spans: tuple[Span, ...]) -> NvlState:
    return NvlState(True, (NvlLine("start/0ff871ab010a", "Hana", "#a02860", spans),))


def _round_trip():
    spans = tuple(Span(f"t{n}", Style(bold=n % 2 == 0, effect=e)) for n, e in enumerate(NINE))
    state = _page(spans)
    data = json.loads(json.dumps(state.to_json(), ensure_ascii=True))
    assert [s["effect"] for s in data["page"][0]["spans"]] == [e.key() for e in NINE]
    assert all(list(s)[-1] == "effect" for s in data["page"][0]["spans"])   # written last
    back = NvlState.from_json(data)
    assert back == state
    assert EFFECT_KEYS == {e.key() for e in NINE} and len(EFFECT_KEYS) == 9
    example = _page((Span("You're not going anywhere.",
                          Style(color="#e05050", effect=TextEffect("glitch", "large"))),))
    assert example.to_json()["page"][0]["spans"] == [
        {"text": "You're not going anywhere.", "color": "#e05050", "effect": "glitch:large"}]


def _no_effect_no_key():
    text = EXAMPLE.read_text(encoding="utf-8")
    data = json.loads(text)
    state = GameState.from_json(data)
    spans = [span for line in state.nvl.page for span in line.spans]
    assert spans and all(span.style.effect is None for span in spans)
    again = state.to_json()
    del again["items"], again["minigame"], again["flow"]    # F21's, F23's, F20's keys
    del again["glitch"]                                     # F28's
    assert json.dumps(again, ensure_ascii=True, indent=1) + "\n" == text
    assert all("effect" not in s for line in again["nvl"]["page"] for s in line["spans"])


REFUSED = ["shake", "shake:Large", "Shake:large", "shake:medium ", "", 1, None,
           ["shake", "large"], "glitch:ZZMARK"]


def _refused():
    base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for value in REFUSED:
        nvl = {"on": True, "page": [{"sid": "s/0", "name": "", "color": None,
                                      "spans": [{"text": "a", "effect": value}]}]}
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**base, "nvl": nvl})
        assert caught.value.reason == "nvl", value
        assert "ZZMARK" not in str(caught.value) and "ZZMARK" not in repr(caught.value)
        with pytest.raises(StateInvalid):
            NvlState.from_json(nvl)


def _format_one():
    base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    nvl = _page((Span("a", Style(effect=TextEffect("wave", "large"))),)).to_json()
    state = GameState.from_json({**base, "nvl": nvl})
    assert state.nvl.page[0].spans[0].style.effect == TextEffect("wave", "large")
    written = state.to_json()
    assert STATE_FORMAT == 1 and written["format"] == 1
    assert GameState.from_json(json.loads(json.dumps(written))) == state


def _line_of():
    shake = TextEffect("shake")
    body = TaggedText((Span("don't", Style(speed=0.2, effect=shake)),))
    say = Say("start/abc", None, None, None, (), "{shake}{speed=0.2}don't{/speed}{/shake}",
              body)
    assert line_of(say).spans == (Span("don't", Style(effect=shake)),)
    assert TextEffect("shake").key() == "shake:medium"
    assert texttags.TextEffect is TextEffect


@pytest.mark.parametrize("row", ["round_trip", "no_effect_no_key", "refused", "format_one",
                                 "line_of"])
def test_ac_f29_05_the_nvl_record_carries_the_effect(row):
    {"round_trip": _round_trip, "no_effect_no_key": _no_effect_no_key, "refused": _refused,
     "format_one": _format_one, "line_of": _line_of}[row]()
