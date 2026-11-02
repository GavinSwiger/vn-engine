"""Two seams on Service S: F23's owner-scoped UI sounds (F23 ``07`` C4, I-4; ``04`` §17.1-7:
``play_ui(owner=)``, ``Slot.owner``, ``stop_ui(fadeout, *, owner)``; AC-F23-27 closes at F23
s4) and F15's ``set_skipping(False, resume=sid)`` (F15 ``07`` I-3)."""

from engine.audio.limits import BLIP_CHANNEL, UI_CHANNELS
from engine.runtime.commands import EndVoice, PlayVoice, StopVoice
from tests.audio.conftest import make_service
from tests.audio.test_reconcile import fade_out_of, restore

DOOR, RAIN = "sfx/door.ogg", "sfx/rain.ogg"               # 0.5 s, 2.0 s
HANA_014, HANA_015 = "voice/hana_014.ogg", "voice/hana_015.ogg"
MG = "minigame"


def ui_channel(s, owner: str | None) -> int:
    (channel,) = [c for c, slot in s.service.pool.slots.items() if slot.owner == owner]
    return channel


# --- F23: play_ui(owner=) and stop_ui ------------------------------------------------------------

def test_stop_ui_fades_only_its_owners_sounds(service_s):
    s = service_s
    s.service.play_ui(RAIN)                                     # the engine's
    s.service.play_ui(RAIN, owner=MG)
    s.service.play_blip(DOOR)                                   # F06's channel 1
    engine, mine = ui_channel(s, None), ui_channel(s, MG)
    t0 = s.clock()
    s.mixer.calls.clear()
    s.service.stop_ui(0.1, owner=MG)
    s.run(0.2)
    fade_out_of(s, mine, t0, 100)                               # the engine ramp, then stop
    assert s.service.pool.slots.keys() == {engine} and s.mixer.name_on(engine) == RAIN
    assert s.mixer.name_on(BLIP_CHANNEL) == DOOR
    assert all(args[0] == mine for _, _, args in s.mixer.actions())


def test_stop_ui_at_once_cancels_that_owners_decodes(tmp_path):
    s = make_service(tmp_path, threaded=True)
    s.service.play_ui(RAIN, owner=MG)
    s.decoded()
    mine = ui_channel(s, MG)
    s.service.play_ui(DOOR, owner=MG)                           # still decoding …
    s.service.play_ui(DOOR)                                     # … and the engine's
    s.mixer.calls.clear()
    s.service.stop_ui(0.0, owner=MG)
    assert [c[1:] for c in s.mixer.actions()] == [("channel_stop", (mine,))]
    s.decoded()
    plays = [args for _, _, args in s.mixer.actions("channel_play")]
    assert len(plays) == 1 and plays[0][0] in UI_CHANNELS and plays[0][1] == DOOR
    assert [slot.owner for slot in s.service.pool.slots.values()] == [None]


def test_a_new_ui_sound_takes_a_fading_channel_first(service_s):
    s = service_s
    for owner in (None, MG, None):
        s.service.play_ui(RAIN, owner=owner)
    mine = ui_channel(s, MG)
    s.service.stop_ui(1.0, owner=MG)
    s.service.play_ui(DOOR)
    assert s.mixer.name_on(mine) == DOOR
    assert [slot.owner for slot in s.service.pool.slots.values()] == [None] * 3


# --- F15: set_skipping(False, resume=sid) --------------------------------------------------------

def test_resume_plays_the_skipped_voice_of_that_line_only(tmp_path):
    """I-3: the last ``PlayVoice`` ignored while skipping plays when skip ends with
    ``resume`` = its sid and nothing voice-related came after it."""
    cases = [   # (what came after the skipped s1 voice, resume, the voice that plays)
        (lambda s: None, "s1", HANA_014),
        (lambda s: None, "s2", None),
        (lambda s: None, None, None),                               # a player's stop
        (lambda s: s.feed(PlayVoice("s2", HANA_015, False)), "s1", None),
        (lambda s: s.feed(PlayVoice("s2", HANA_015, False)), "s2", HANA_015),
        (lambda s: s.feed(EndVoice("s1")), "s1", None),
        (lambda s: s.feed(StopVoice(None)), "s1", None),
        (lambda s: s.feed(restore()), "s1", None),
        (lambda s: s.service.stop_story_audio(), "s1", None),
    ]
    for index, (after, resume, plays) in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        s = make_service(root, threaded=True)
        s.service.set_skipping(True)
        s.feed(PlayVoice("s1", HANA_014, False))
        after(s)
        s.service.set_skipping(False, resume=resume)
        sid = {HANA_014: "s1", HANA_015: "s2"}.get(plays)
        assert s.service.voice_playing(sid) == (plays is not None), index   # decoding counts
        s.decoded()
        assert s.mixer.name_on(0) == plays, index
        s.service.shutdown()


def test_a_later_skip_forgets_the_earlier_skipped_voice(service_s):
    s = service_s
    s.service.set_skipping(True)
    s.feed(PlayVoice("s1", HANA_014, False))
    s.service.set_skipping(False)
    s.service.set_skipping(True)
    s.service.set_skipping(False, resume="s1")
    assert s.mixer.actions("channel_play") == []
