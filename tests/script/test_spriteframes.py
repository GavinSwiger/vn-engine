"""F38 step 1 — AC-F38-01: the frame naming rule (``script/spriteframes.py``; PR-F38-01).
``frames_of``, ``frame_of`` and ``next_number`` over one table of image names: files and
declarations count, solid colors don't; case-exact; unnumbered first, gaps skipped;
``_blink10`` (and 0, 01) not frames; a frame name with no look is an ordinary look."""

import pytest

from engine.runtime.images import ImageFile, ImageIndex, SolidColor
from engine.script import spriteframes as sf
from engine.script.spriteframes import NO_FRAMES, Frame, LookFrames


def _index() -> ImageIndex:
    files = ["hana happy", "hana happy_blink", "hana happy_blink3", "hana happy_blink1",
             "hana happy_blink10", "hana happy_blink0", "hana happy_blink01",
             "hana happy_Blink2", "hana happy_talk1",
             "hana sad", "hana sad_talk9",
             "hana", "hana_blink1",                       # a one-word look
             "hana angry_blink1",                         # no "hana angry": a plain look
             "daichi grin", "daichi grin_talk"]
    images = {name: ImageFile(f"images/{name.replace(' ', '/')}.png") for name in files}
    images["hana festival"] = ImageFile("art/hana_yukata_v3.png")      # a declaration
    images["hana festival_talk2"] = ImageFile("art/hana_yukata_v3_talk.png")
    images["bg dusk"] = SolidColor((43, 33, 64))                       # a color: never counts
    images["bg dusk_blink1"] = ImageFile("images/bg/dusk_blink1.png")
    images["hana sad_blink1"] = SolidColor((0, 0, 0))
    return ImageIndex(images)


FRAMES = [  # look → (blink frames, talk frames), in play order
    ("hana happy", ("hana happy_blink", "hana happy_blink1", "hana happy_blink3"),
     ("hana happy_talk1",)),
    ("hana sad", (), ("hana sad_talk9",)),                   # the color "blink1" is no frame
    ("hana", ("hana_blink1",), ()),
    ("hana festival", (), ("hana festival_talk2",)),
    ("daichi grin", (), ("daichi grin_talk",)),
    ("bg dusk", (), ()),                                     # a color is no look
    ("hana angry", (), ()),                                  # not a name
    ("Hana happy", (), ()),
]
FRAME_OF = [  # name → Frame or None
    ("hana happy_blink", Frame("hana happy", "blink", 0)),
    ("hana happy_blink3", Frame("hana happy", "blink", 3)),
    ("hana happy_talk1", Frame("hana happy", "talk", 1)),
    ("hana_blink1", Frame("hana", "blink", 1)),
    ("hana festival_talk2", Frame("hana festival", "talk", 2)),
    ("hana happy_blink10", None), ("hana happy_blink0", None), ("hana happy_blink01", None),
    ("hana happy_Blink2", None), ("hana angry_blink1", None), ("bg dusk_blink1", None),
    ("hana happy", None), ("hana sad_blink1", None),
]
NEXT = [  # (look, kind) → next number
    ("hana happy", "blink", 4), ("hana happy", "talk", 2), ("hana sad", "talk", None),
    ("hana sad", "blink", 1), ("daichi grin", "talk", 1), ("hana", "blink", 2),
]


def test_ac_f38_01_frame_naming_table():
    names = sf.picture_names(_index().items())
    assert "bg dusk" not in names and "hana festival" in names
    for look, blink, talk in FRAMES:
        assert sf.frames_of(look, names) == LookFrames(blink, talk), look
    assert sf.frames_of("hana sad", names).of("talk") == ("hana sad_talk9",)
    assert not NO_FRAMES and sf.frames_of("bg dusk", names) is NO_FRAMES
    for name, frame in FRAME_OF:
        assert sf.frame_of(name, names) == frame, name
    for look, kind, number in NEXT:
        assert sf.next_number(look, kind, names) == number, (look, kind)
    # Names Studio writes, and the play order (1…N, back down to 1).
    assert [sf.frame_name("hana happy", "blink", n) for n in (0, 1, 9)] == [
        "hana happy_blink", "hana happy_blink1", "hana happy_blink9"]
    assert sf.frame_of(sf.frame_name("hana", "talk", 9), names | {"hana_talk9"}) == Frame(
        "hana", "talk", 9)
    for bad in (("hana", "blink", 10), ("hana", "wink", 1), ("hana", "talk", -1)):
        with pytest.raises(ValueError):
            sf.frame_name(*bad)
    assert [sf.cycle(f) for f in ((), ("a",), ("a", "b"), ("a", "b", "c"))] == [
        (), ("a",), ("a", "b", "a"), ("a", "b", "c", "b", "a")]
