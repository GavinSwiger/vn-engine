"""Stage stills, Studio's side (``stagestills``): specs from a sketch's stage, the cache
(coalesced, stale asks dropped, bounded, failures kept), and asking that never waits on the
helper. A fake runner stands in for the child; ``tests/tools/test_helper_stage.py`` draws."""

import json
import time
from types import SimpleNamespace as NS

import pytest

from engine.core.editorreport import HELPER_REQUEST_MAX
from engine.tools.editor import stagestills as ss
from engine.tools.editor.helperrunner import STAGE_TOO_LARGE, HelperReply, HelperRunner
from engine.tools.editor.scenepreview import Sprite, Stage

PNG = "iVBORw0KGgo="          # base64 of the PNG signature: enough for the cache


class FakeRunner:
    """Records stills; ``answer`` replies to the oldest one through ``stills.on_reply``."""

    def __init__(self) -> None:
        self.asked: list[tuple[int, int, bytes | None, dict]] = []
        self.serial = 0

    def still(self, kind, width, config, stage=None):
        assert kind == "stage" and stage is not None
        self.serial += 1
        self.asked.append((self.serial, width, config, stage))
        return self.serial

    def answer(self, stills, ok=True, data=PNG):
        serial = self.asked[-1][0]
        stills.on_reply(HelperReply("still", serial, ok, data=data if ok else None, width=8,
                                    height=4, reason=None if ok else "broken config",
                                    kind="stage"))


def _key(text, width=224, look="saved"):
    return ss.StillKey(ss.StageSpec(background="bg x", images=(("bg x", "#000000"),),
                                    text=text), width, look)


ASSETS = NS(image_refs={"bg room": "images/bg/room.png", "hana happy": "images/hana/happy.png",
                        "hana sad": "images/hana/sad.png"},
            colors={"bg dusk": "#2B2140"})


def test_spec_of_resolves_names_as_the_sketch_does():
    say = NS(who="Hana", color="#e8a", text="Hi.")
    stage = Stage("bg room", False, (Sprite("hana", "left"), Sprite("ghost"),
                                     Sprite("hana sad", None, 900.0, 2.0)))
    spec = ss.spec_of(NS(background="bg room", sprites=stage.sprites, say=say), ASSETS)
    assert spec.background == "bg room"
    assert dict(spec.images) == {"bg room": "images/bg/room.png",
                                 "hana": "images/hana/happy.png",       # a picture of hana
                                 "hana sad": "images/hana/sad.png"}     # ghost: left out
    assert spec.sprites == (("hana", "hana", "left", 1.0, False),
                            ("hana_", "hana sad", (900.0,), 2.0, False))
    assert (spec.who, spec.color, spec.text) == ("Hana", "#ee88aa", "Hi.")
    request = spec.request()
    assert request["sprites"][1][2] == [900.0] and request["images"]["bg room"]
    json.dumps(request)                                        # it goes over the wire as is
    colour = ss.spec_of(NS(background="bg dusk", sprites=()), ASSETS)
    assert dict(colour.images) == {"bg dusk": "#2B2140".lower()} and colour.text is None
    assert hash(spec) == hash(ss.spec_of(NS(background="bg room", sprites=stage.sprites,
                                            say=say), ASSETS))          # a stable key
    assert ss.look_of(None) == ss.SAVED_LOOK != ss.look_of("a") == ss.look_of(b"a")


def test_asks_are_coalesced_stale_ones_dropped_and_owners_told():
    runner, heard = FakeRunner(), []
    stills = ss.StageStills(lambda: runner)
    a, b, c = _key("a"), _key("b"), _key("c")
    stills.ask("preview", [a], config=b"x=1", on_ready=lambda k, s: heard.append(k))
    assert [r[3]["text"] for r in runner.asked] == ["a"] and runner.asked[0][2] == b"x=1"
    # Flipping on while ``a`` draws: only the newest wish waits; ``b`` is never sent.
    stills.ask("preview", [b], on_ready=lambda k, s: heard.append(k))
    stills.ask("preview", [c], on_ready=lambda k, s: heard.append(k))
    stills.ask("preview", [c], on_ready=lambda k, s: heard.append(k))   # coalesced
    assert len(runner.asked) == 1 and stills.in_flight == a
    runner.answer(stills)                       # ``a`` is cached, but no longer wanted
    assert stills.get(a).ok and heard == []
    assert [r[3]["text"] for r in runner.asked] == ["a", "c"]
    runner.answer(stills)
    assert heard == [c] and stills.get(c).data == PNG and stills.wanted() == []
    stills.ask("preview", [c])                  # cached: not asked again
    assert len(runner.asked) == 2
    # Two owners: the most recent asker's keys go first; cancel drops an owner's wishes.
    stills.ask("map", [_key("m1"), _key("m2")])
    stills.ask("preview", [_key("p")])
    assert runner.asked[-1][3]["text"] == "m1"
    runner.answer(stills)
    assert runner.asked[-1][3]["text"] == "p"
    stills.cancel("map")
    runner.answer(stills)
    assert stills.wanted() == [] and len(runner.asked) == 4


def test_failures_are_kept_and_the_cache_is_bounded():
    runner = FakeRunner()
    stills = ss.StageStills(lambda: runner, entries=3, max_bytes=40)
    stills.ask("preview", [_key("bad")])
    runner.answer(stills, ok=False)
    assert not stills.get(_key("bad")).ok and stills.get(_key("bad")).reason
    stills.ask("preview", [_key("bad")])
    assert len(runner.asked) == 1               # a failure isn't asked again
    for text in "abcd":
        stills.ask("preview", [_key(text)])
        runner.answer(stills, data=PNG * 2)
    assert len(stills) <= 3 and stills.bytes <= 40
    assert stills.get(_key("a")) is None and stills.get(_key("d")).ok   # oldest out first
    assert stills.photo(_key("bad"), None) is None                      # no picture: no photo


def test_asking_never_waits_on_the_helper(tmp_path):
    """Through the real ``HelperRunner`` with a child that never answers: asking returns
    at once (the request only queues), and a stage too large to send fails here."""

    class Silent:
        def __init__(self, *a, **k):
            import io
            import os
            read, write = os.pipe()
            self.stdout, self._w = io.open(read, "rb"), write
            self.stdin = io.BytesIO()
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = 0
            import os
            os.close(self._w)

        kill = terminate

    runner = HelperRunner(tmp_path, popen=Silent)
    stills = ss.StageStills(lambda: runner)
    try:
        started = time.perf_counter()
        for i in range(50):
            stills.ask("preview", [_key(f"line {i}")])
        assert time.perf_counter() - started < 0.05
        assert stills.sent == 1                 # one in flight; the rest wait or are stale
        big = ss.StageSpec(text="x" * 600, images=tuple(
            (f"{i:02} " + "n" * 240, "images/" + "y" * 240) for i in range(16)))
        serial = runner.still("stage", 224, None, big.request())
        assert len(json.dumps(big.request())) > HELPER_REQUEST_MAX
        failed = [r for r in runner.poll() if r.serial == serial]
        assert failed and not failed[0].ok and failed[0].reason == STAGE_TOO_LARGE
        with pytest.raises(ValueError):
            runner.still("stage", 224, None)    # a stage still needs its stage
    finally:
        runner.stop(timeout_s=1)
