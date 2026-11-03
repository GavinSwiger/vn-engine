"""F38 step 1 — AC-F38-02, 03: the sprite animator (``render/spriteanim.py``) on a fake clock.
AC-02: blinks play 1…N…1 at ``blink_frame``, gaps are ``Random(1)``'s draws within
0.5–1.5 × ``blink_every``, a due blink waits while the mouth moves (and the holds: still,
held tags, ``enabled`` off). AC-03: the speaker's mouth follows typing: frame 1 on the first
letter, the cycle at ``talk_frame``, closed by a pause, a wait, the end, or 0.25 s idle; never
for a restored line, narration, or a tag not on stage."""

from random import Random

from engine.render.spriteanim import TALK_IDLE_S, AnimSettings, SpriteAnimator
from engine.render.typewriter import WaitKind
from engine.runtime.commands import Say
from engine.runtime.stage import SpriteState, StageState
from engine.script.spriteframes import NO_FRAMES, LookFrames

FRAMES = {
    "hana happy": LookFrames(("b1", "b2", "b3"), ("t1", "t2")),
    "hana sad": LookFrames((), ("s1",)),
    "daichi grin": LookFrames(("d1",), ()),
}
SETTINGS = AnimSettings(blink_every=2.0, blink_frame=0.1, talk_frame=0.1)


def _animator(*sprites: tuple[str, str], seed: int = 1,
              settings: AnimSettings = SETTINGS) -> SpriteAnimator:
    anim = SpriteAnimator(lambda look: FRAMES.get(look, NO_FRAMES), Random(seed), settings)
    anim.set_stage(_stage(*sprites))
    return anim


def _stage(*sprites: tuple[str, str]) -> StageState:
    return StageState("bg", tuple(SpriteState(tag, image) for tag, image in sprites))


def _say(tag: str | None, *, restored: bool = False) -> Say:
    return Say("s1", tag, tag, None, (), "Hi", speaker_tag=tag, restored=restored)


def _blink_gaps(anim: SpriteAnimator, tag: str, count: int, dt: float = 0.01) -> list[float]:
    """Seconds from the end of each blink (or the start) to the next blink's first frame."""
    gaps, waited = [], 0.0
    while len(gaps) < count:
        anim.tick(dt)
        waited += dt
        if anim.wanted().get(tag) is not None:
            gaps.append(waited)
            while anim.wanted().get(tag) is not None:
                anim.tick(dt)
            waited = 0.0
    return gaps


def test_ac_f38_02_blink_order_gaps_and_waiting_while_talking():
    draws = Random(1)
    anim = _animator(("hana", "hana happy"), ("daichi", "daichi grin"), ("kid", "kid"))
    hana_gap = draws.uniform(0.5, 1.5) * 2.0
    daichi_gap = draws.uniform(0.5, 1.5) * 2.0
    assert hana_gap < daichi_gap                              # Random(1)'s first two draws
    anim.tick(hana_gap - 0.01)
    assert anim.wanted() == {}
    shown = []
    for _ in range(6):                                        # 1…N…1, then the look
        anim.tick(0.01 if not shown else 0.1)
        shown.append(anim.wanted().get("hana"))
    assert shown == ["b1", "b2", "b3", "b2", "b1", None]
    # The next gaps are the animator's own draws, each 0.5–1.5 × blink_every (± a tick).
    gaps = _blink_gaps(_animator(("hana", "hana happy"), seed=7), "hana", 25)
    assert all(1.0 - 0.02 <= gap <= 3.0 + 0.02 for gap in gaps) and max(gaps) - min(gaps) > 1

    # A due blink waits while the mouth moves, and starts once it stops.
    anim = _animator(("hana", "hana happy"))
    anim.on_say(_say("hana"))
    for _ in range(40):                                      # 4 s of typing, gap ≤ 3 s
        anim.glyph_shown(0, "a")
        assert anim.wanted().get("hana") in ("t1", "t2", None)
        anim.tick(0.1)
    anim.completed(by_press=False)
    assert anim.wanted() == {}
    anim.tick(0.01)
    assert anim.wanted() == {"hana": "b1"}
    anim.glyph_shown(1, "b")                                  # talking cuts a blink
    assert anim.wanted() == {"hana": "t1"}

    # Holds: still, a held tag, and enabled off show plain looks; timers go on.
    for hold in ({"still": True}, {"held": ("daichi",)}):
        anim = _animator(("daichi", "daichi grin"))
        anim.tick(1.0)
        anim.tick(2.0)                                        # the gap (≤ 3 s) is over
        assert anim.wanted() == {"daichi": "d1"}
        anim.tick(0.01, **hold)
        assert anim.wanted() == {}
        anim.tick(3.0, **hold)
        assert anim.wanted() == {}
        anim.tick(0.01)
        assert anim.wanted() == {"daichi": "d1"}
    anim.settings = AnimSettings(enabled=False)
    anim.tick(0.01)
    assert anim.wanted() == {}


def test_ac_f38_03_talk_follows_typing():
    rare_blinks = AnimSettings(blink_every=30.0, blink_frame=0.1, talk_frame=0.1)
    anim = _animator(("hana", "hana happy"), ("daichi", "daichi grin"), settings=rare_blinks)
    anim.on_say(_say("hana"))
    anim.glyph_shown(0, " ")                                  # not a letter: mouth still
    anim.glyph_shown(1, "…")
    assert anim.wanted() == {} and not anim.talking
    anim.glyph_shown(2, "H")
    assert anim.wanted() == {"hana": "t1"}
    shown = []
    for i in range(6):                                        # t1 t2 t1, look, again
        anim.tick(0.1)
        anim.glyph_shown(3 + i, "a")
        shown.append(anim.wanted().get("hana"))
    assert shown == ["t2", "t1", None, "t1", "t2", "t1"]
    anim.completed(by_press=True)

    # Each stop shows the look; the next letter starts at frame 1 again.
    stops = {
        "timed pause": lambda: anim.pause_started(0.5),
        "click wait": lambda: anim.waiting(WaitKind.CLICK),
        "page wait": lambda: anim.waiting(WaitKind.PAGE),
        "typed to the end": lambda: anim.completed(by_press=False),
        "pressed to the end": lambda: anim.completed(by_press=True),
        "0.25 s idle": lambda: anim.tick(TALK_IDLE_S),
        "a new line": lambda: anim.on_say(_say("hana")),
        "a stage change": lambda: anim.set_stage(_stage(("hana", "hana happy"))),
    }
    for why, stop in stops.items():
        anim.glyph_shown(0, "a")
        anim.tick(0.1)
        assert anim.wanted() == {"hana": "t2"}, why
        stop()
        assert anim.wanted() == {} and not anim.talking, why
        anim.glyph_shown(1, "b")
        assert anim.wanted() == {"hana": "t1"}, why
        anim.completed(by_press=True)
    anim.glyph_shown(0, "a")
    anim.tick(TALK_IDLE_S - 0.01)                             # just under idle: still talking
    assert anim.talking

    # An expression change mid-line: the next letter talks with the new look's frames.
    anim.set_stage(_stage(("hana", "hana sad"), ("daichi", "daichi grin")))
    anim.glyph_shown(5, "c")
    assert anim.wanted() == {"hana": "s1"}

    # Nothing talks: a restored line, narration, a tag not on stage, a look with no talk
    # frames, or before any line.
    for say, stage in [(_say("hana", restored=True), ("hana", "hana happy")),
                       (_say(None), ("hana", "hana happy")),
                       (_say("mei"), ("hana", "hana happy")),
                       (_say("daichi"), ("daichi", "daichi grin")),
                       (None, ("hana", "hana happy"))]:
        anim = _animator(stage)
        if say is not None:
            anim.on_say(say)
        anim.glyph_shown(0, "a")
        assert anim.wanted() == {} and not anim.talking, say
    anim.reset()
    assert anim.speaker is None and anim.wanted() == {}
