"""F38 step 2 — sprite frames on the stage (``StageView.show_frames``; ADR-0007's F38
amendment; ``07`` I-2 to I-7): AC-F38-04 (the clipped repaint is the full compose's to the
pixel, one sprite per draw), AC-F38-05 (holds), AC-F38-06 (unready and wrong-size frames),
AC-F38-14 (F28's jitter copy draws the frame).

The rig: a game folder of generated PNGs (a background, a look with a blink and a talking
frame, a second sprite, a wrong-size frame), an ``AssetManager`` on it, a ``StageView`` with
``look_frames`` and an unthreaded ``ImagePrefetcher`` (so frames load in ``update``), drawn
into a plain framebuffer under the dummy video driver.
"""

import logging
from pathlib import Path

import pygame
import pytest

from engine.core.constants import BUILTIN_POSITIONS
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.render.canvas import Canvas, RenderQuality
from engine.render.prefetch import ImagePrefetcher
from engine.render.spriteanim import AnimSettings, SpriteAnimator
from engine.render.stage import StageView, frame_size_text
from engine.runtime.commands import ShowStage, TitleCard
from engine.runtime.images import ImageFile, ImageIndex, look_frames
from engine.runtime.stage import SpriteState, StageState
from engine.runtime.transitions import TransitionSpec
from engine.ui.builtin.stage_screen import StageScreen
from tests.render.conftest import make_assets

pytestmark = pytest.mark.display

LOOK = (300, 600)
FILES = {
    "bg room": "images/bg/room.png",
    "a happy": "images/a/happy.png",
    "a happy_blink1": "images/a/happy_blink1.png",
    "a happy_talk1": "images/a/happy_talk1.png",
    "a sad": "images/a/sad.png",
    "a sad_blink1": "images/a/sad_blink1.png",            # the wrong size: W217
    "b x": "images/b/x.png",
}


def _art(size, color, accent) -> pygame.Surface:
    """A soft-edged figure: semi-transparent shapes, so scaling and blending matter."""
    s = pygame.Surface(size, pygame.SRCALPHA)
    s.fill((*color, 0))
    w, h = size
    pygame.draw.ellipse(s, (*color, 255), (w // 8, h // 10, w * 3 // 4, h * 4 // 5))
    pygame.draw.ellipse(s, (*accent, 160), (w // 4, h // 5, w // 2, h // 6))
    pygame.draw.rect(s, (*accent, 90), (0, h // 2, w, h // 7))
    return s


def write_game(root: Path) -> Path:
    pygame.init()
    bg = pygame.Surface((1280, 720))
    for y in range(0, 720, 8):
        bg.fill((y % 256, (y * 3) % 256, 120), (0, y, 1280, 8))
    images = {
        "bg room": bg,
        "a happy": _art(LOOK, (240, 200, 180), (40, 40, 200)),
        "a happy_blink1": _art(LOOK, (240, 200, 180), (200, 40, 40)),
        "a happy_talk1": _art(LOOK, (240, 200, 180), (40, 200, 40)),
        "a sad": _art(LOOK, (200, 200, 240), (40, 40, 200)),
        "a sad_blink1": _art((280, 600), (200, 200, 240), (200, 40, 40)),
        "b x": _art((320, 560), (90, 160, 90), (250, 250, 60)),
    }
    for name, surface in images.items():
        path = root / FILES[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(surface, str(path))
    return root


class Rig:
    def __init__(self, root: Path, size=(1280, 720), *, prefetcher: object = "sync") -> None:
        self.paths = GamePaths.for_game(root)
        self.framebuffer = pygame.Surface(size)
        self.assets = make_assets(self.paths, format_source=lambda: self.framebuffer)
        index = ImageIndex({name: ImageFile(ref) for name, ref in FILES.items()})
        self.prefetcher = ImagePrefetcher(self.assets, threaded=False) \
            if prefetcher == "sync" else prefetcher
        self.view = StageView(self.assets, index, art_height=1080,
                              positions=BUILTIN_POSITIONS, empty_color=(0, 0, 0),
                              prefetcher=self.prefetcher, frames_of=look_frames(index))
        self.canvas = Canvas(self.assets)
        self.resize(size)

    def resize(self, size) -> None:
        self.framebuffer = pygame.Surface(size)
        w, h = size
        self.canvas.bind(self.framebuffer, Viewport(1920, 1080, w, h, 0, 0, w, h),
                         RenderQuality.FINAL)

    def draw(self, quality=RenderQuality.FINAL) -> None:
        self.canvas.quality = quality
        self.view.draw(self.canvas)

    def step(self, wanted) -> None:
        """One frame as ``StageScreen.update`` then ``draw`` run it."""
        self.view.update()
        self.view.show_frames(wanted)
        self.draw()

    def settle(self, wanted, frames: int = 12) -> None:
        for _ in range(frames):
            self.step(wanted)

    def show(self, stage: StageState, **kw) -> None:
        self.view.show(ShowStage(stage, **kw))


def stage(*sprites: SpriteState) -> StageState:
    return StageState("bg room", tuple(sprites))


def spr(tag, image, at="center", zoom=1.0, flip=False, layer=0) -> SpriteState:
    return SpriteState(tag, image, at, layer, zoom, flip)


def pixels(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


@pytest.fixture
def game(tmp_path) -> Path:
    return write_game(tmp_path / "g")


# --- AC-F38-04 -----------------------------------------------------------------------------------

@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_ac_f38_04_clipped_repaint_is_the_full_compose(game, size, monkeypatch):
    cases = {
        "under": (spr("a", "a happy", "left"), spr("b", "b x", (700.0,))),
        "over": (spr("b", "b x", (700.0,)), spr("a", "a happy", (820.0,))),
        "zoom": (spr("b", "b x", "right"), spr("a", "a happy", "center", zoom=1.5)),
        "flip": (spr("a", "a happy", (900.0,), flip=True), spr("b", "b x", (1000.0,))),
    }
    for case, sprites in cases.items():
        for frame in ("a happy_blink1", "a happy_talk1"):
            rig = Rig(game, size)
            rig.show(stage(*sprites))
            rig.settle({"a": frame})
            assert rig.view.shown_frames == {"a": frame}, (case, frame)
            ref = Rig(game, size)
            ref.show(stage(*(spr(s.tag, frame, s.at, s.zoom, s.flip) if s.tag == "a" else s
                             for s in sprites)))
            ref.draw()
            assert pixels(rig.view.picture()) == pixels(ref.view.picture()), (case, frame, size)
            # Back to the look: the plain compose, to the pixel.
            rig.settle({})
            plain = Rig(game, size)
            plain.show(stage(*sprites))
            plain.draw()
            assert rig.view.shown_frames == {}
            assert pixels(rig.view.picture()) == pixels(plain.view.picture()), (case, size)

    # At most one sprite per draw, oldest change first; a repaint never scales.
    rig = Rig(game, size)
    rig.show(stage(spr("a", "a happy", "left"), spr("b", "a happy", "right")))
    rig.settle({})                                       # every frame cached, nothing shown
    calls = []
    for name in ("scale", "smoothscale"):
        real = getattr(pygame.transform, name)
        monkeypatch.setattr(pygame.transform, name,
                            lambda *a, real=real, **k: calls.append(a) or real(*a, **k))
    rig.view.show_frames({"b": "a happy_talk1"})           # b's change is the older one
    rig.view.show_frames({"b": "a happy_talk1", "a": "a happy_blink1"})
    rig.draw()
    assert rig.view.shown_frames == {"b": "a happy_talk1"}
    rig.draw()                                           # a's waited one draw
    assert rig.view.shown_frames == {"b": "a happy_talk1", "a": "a happy_blink1"}
    assert calls == []                                   # cached variants only


# --- AC-F38-05 -----------------------------------------------------------------------------------

class FakeShift:
    """F28's ``ColorShift`` slot, plain: its "filtered" copy is the picture itself."""
    weight = target = 1.0
    units = 4.0

    def filtered(self, picture, key, *, step):
        return picture

    def ready(self, picture, key):
        return picture

    def newest(self):
        return None

    def complete(self, picture, key):
        return picture


def test_ac_f38_05_holds(game):
    want = {"a": "a happy_blink1"}
    rig = Rig(game)
    rig.show(stage(spr("a", "a happy")))
    rig.settle(want)
    assert rig.view.shown_frames == want and not rig.view.frames_held
    # A transition: every full compose shows plain looks, and nothing changes while it runs.
    spec = TransitionSpec("dissolve", "dissolve", "sid-1", 1.0, None, None, 0.1, False, None)
    rig.show(stage(spr("a", "a happy")), transition=spec)
    rig.settle(want, 4)
    rig.view.advance(0.3)
    rig.settle(want, 2)
    assert rig.view.transitioning and rig.view.frames_held and rig.view.shown_frames == {}
    rig.view.finish()
    rig.settle(want)
    assert not rig.view.transitioning and rig.view.shown_frames == want
    # A title card.
    rig.show(stage(spr("a", "a happy")), card=TitleCard("one", None, "One"))
    rig.settle(want)
    assert rig.view.frames_held and rig.view.shown_frames == {}
    rig.show(stage(spr("a", "a happy")))
    rig.settle(want)
    assert rig.view.shown_frames == want
    # A FAST settle frame: the composite (with its frame) is scaled; no change is made.
    rig.view.show_frames({})
    rig.draw(RenderQuality.FAST)
    rig.view.update()
    rig.view.show_frames({})
    rig.draw(RenderQuality.FAST)
    assert rig.view.frames_held and rig.view.shown_frames == want
    rig.settle(want)
    # An oversized sprite never animates.
    rig.show(stage(spr("a", "a happy", zoom=6.0)))
    rig.settle(want)
    assert rig.view.oversized == {"a"} and rig.view.shown_frames == {}
    # Colorshift turning on while a frame shows: the plain looks, one compose.
    rig.show(stage(spr("a", "a happy")))
    rig.settle(want)
    assert rig.view.shown_frames == want
    rig.view.set_filter(FakeShift())
    rig.draw()
    plain = Rig(game)
    plain.show(stage(spr("a", "a happy")))
    plain.draw()
    assert rig.view.shown_frames == {}
    assert pixels(rig.view.picture()) == pixels(plain.view.picture())
    rig.settle(want)
    assert rig.view.frames_held and rig.view.shown_frames == {}
    rig.view.set_filter(None)
    # Reduce motion and ``enabled = false``: the screen's animator holds still.
    for settings, reduce in ((AnimSettings(blink_every=1.0), True),
                             (AnimSettings(enabled=False, blink_every=1.0), False)):
        anim = SpriteAnimator(rig.view.frames_of, __import__("random").Random(1), settings)
        screen = StageScreen(object(), rig.view, anim=anim)
        screen.settings = type(screen.settings)(reduce=reduce)
        screen.show_stage(ShowStage(stage(spr("a", "a happy"))))
        for _ in range(240):                             # 4 s at 60 fps: blinks were due
            screen.update(1 / 60, is_top=True)
            assert anim.wanted() == {}
            screen.draw(rig.canvas)
            assert rig.view.shown_frames == {}
    anim = SpriteAnimator(rig.view.frames_of, __import__("random").Random(1),
                          AnimSettings(blink_every=1.0))
    screen = StageScreen(object(), rig.view, anim=anim)
    screen.show_stage(ShowStage(stage(spr("a", "a happy"))))
    seen = set()
    for _ in range(240):
        screen.update(1 / 60, is_top=True)
        screen.draw(rig.canvas)
        seen.update(rig.view.shown_frames.values())
    assert seen == {"a happy_blink1"}                    # it does blink when not held


# --- AC-F38-06 -----------------------------------------------------------------------------------

class FakePrefetcher:
    pending = False

    def __init__(self) -> None:
        self.requests: list[list] = []

    def request(self, wanted) -> None:
        self.requests.append(list(wanted))

    def pump(self) -> None:
        pass


def test_ac_f38_06_unready_and_wrong_size_frames(game, caplog):
    fake = FakePrefetcher()
    rig = Rig(game, prefetcher=fake)
    rig.show(stage(spr("a", "a happy", "left", flip=True)))
    rig.settle({"a": "a happy_blink1"}, 3)
    assert rig.view.shown_frames == {}                   # not loaded: the look shows
    asked = {r.ref: r for r in fake.requests[0]}
    assert set(asked) == {FILES["a happy_blink1"], FILES["a happy_talk1"]}
    look = rig.assets.image(FILES["a happy"])
    size = rig.view._places["a"].size
    assert size != look.size                             # 1280×720: scaled
    assert all(r.rescale and r.target(*LOOK) == (size, True) for r in asked.values())
    assert asked[FILES["a happy_blink1"]].target(280, 600) is None     # wrong size: none

    # A frame of another size than its look: W217 once, never drawn.
    caplog.set_level(logging.WARNING)
    rig = Rig(game)
    rig.show(stage(spr("a", "a sad")))
    rig.settle({"a": "a sad_blink1"})
    rig.show(stage(spr("a", "a sad", "right")))
    rig.settle({"a": "a sad_blink1"})
    assert rig.assets.is_cached(FILES["a sad_blink1"])
    assert rig.view.shown_frames == {}
    text = frame_size_text(FILES["a sad_blink1"], (280, 600), FILES["a sad"], LOOK)
    assert text == ("images/a/sad_blink1.png is 280×600, but its look images/a/sad.png "
                    "is 300×600, so it isn't used. Make the frame the same size as the "
                    "look.")
    lines = [r for r in caplog.records if getattr(r, "code", None) == "W217"]
    assert [r.getMessage() for r in lines] == [text]


# --- AC-F38-14 -----------------------------------------------------------------------------------

def test_ac_f38_14_jitter_copy_draws_the_frame(game):
    rig = Rig(game)
    rig.show(stage(spr("a", "a happy", flip=True)))
    rig.settle({"a": "a happy_talk1"})
    assert rig.view.shown_frames == {"a": "a happy_talk1"}
    got = pygame.Surface((1280, 720))
    assert rig.view.draw_sprite_copy(got, "a", (5, 0))
    place = rig.view._places["a"]
    talk = rig.assets.image(FILES["a happy_talk1"])
    art, _ = rig.assets.variant(talk, place.size, RenderQuality.FINAL, flip_x=True)
    want = pygame.Surface((1280, 720))
    want.blit(art, (place.rect.x + 5, place.rect.y))
    assert pixels(got) == pixels(want)
    rig.settle({})
    got.fill((0, 0, 0))
    assert rig.view.draw_sprite_copy(got, "a", (5, 0))
    assert pixels(got) != pixels(want)                   # the look again
