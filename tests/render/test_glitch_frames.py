"""F28 step 4 — tear, static, and jitter frames in Screen L (``06-acceptance.md`` §0.3,
``tests/render/glitch_screen.py``) and, for the layers above the stage, App A.

The default tier runs at 640×360 (scale 0.5). Probes and measures read the presented
framebuffer; the control is a rig fed the same stage commands and no ``Glitch``.

AC-F28-13, AC-F28-14, AC-F28-16.
"""

import zlib
from collections import Counter

import pygame
import pytest

from engine.render import glitch as glitch_module
from engine.render.canvas import RenderQuality
from engine.runtime.commands import Flash, Shake, TitleCard, TransitionSpec
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen
from tests.render.glitch_screen import (DAICHI, GRAIN_REF, GREEN, HANA, L, burst, grain,
                                        multiset, on, rows, stage)

pytestmark = pytest.mark.display

LETTERBOX = (0x12, 0x34, 0x56)
CARD = (90, 60, 30)


def dissolve(seconds: float = 1.0) -> TransitionSpec:
    return TransitionSpec("dissolve", "dissolve", "sid-1", seconds, None, None, 0.1, False, None)


def raw(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


def rolled(row: bytes, shift: int) -> bytes:
    """``row`` rolled right by ``shift`` px with wrap."""
    cut = (shift % (len(row) // 3)) * 3
    return row[-cut:] + row[:-cut] if cut else row


def same_row_multisets(frame: pygame.Surface, control: pygame.Surface) -> list[int]:
    """Assert every row keeps the control's multiset; return the rows that changed."""
    changed = []
    for y, (a, b) in enumerate(zip(rows(frame), rows(control))):
        if a != b:
            assert multiset(a) == multiset(b), y
            changed.append(y)
    return changed


def groups(changed: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for y in changed:
        if runs and runs[-1][-1] == y - 1:
            runs[-1].append(y)
        else:
            runs.append([y])
    return runs


def static_pixels(frame: pygame.Surface, control: pygame.Surface, strength: float,
                  step: int = 7) -> set[int]:
    """Assert each sampled pixel is the control × round(255(1 − s)) (MULT) plus one gray
    no larger than round(255·s), ± 1; return the grays seen."""
    gray = glitch_module.static_multiplier(strength)
    top = glitch_module.static_add(255, strength)
    a, b = raw(frame), raw(control)
    seen = set()
    for i in range(0, len(a), 3 * step):
        added = [a[i + c] - ((b[i + c] * gray + 255) >> 8) for c in range(3)]
        assert max(added) - min(added) <= 1 and -1 <= min(added) and max(added) <= top + 1, \
            (i, added)
        seen.add(added[0])
    return seen


class OpaqueCard:
    opaque = True

    def paint(self, canvas, card) -> None:
        canvas.fill(CARD)


class FakeHost:
    session = object()                       # a minigame is open


# --- AC-F28-13 — tear and static on the stage only --------------------------------------------

def test_ac_f28_13_tear_and_static_on_the_stage_only(tmp_path, monkeypatch):
    # `tear large` lasting: row multisets kept; 2–6 bands (runs may touch), ≤ 288 units in
    # all, |dx| in [24, 96] units; the same bands within each 6-frame step.
    rig = L(tmp_path / "tear")
    rig.show(stage(HANA, DAICHI))
    control = rig.frame()
    rig.screen.glitch(on(("tear", "large")))
    frames = rig.frames(13)
    k = rig.scale
    for f, frame in enumerate(frames):
        changed = same_row_multisets(frame, control)
        runs = groups(changed)
        assert 1 <= len(runs) <= 6 and len(changed) <= round(288 * k) + 6, f
        if f == 0:
            for run in runs:
                y = run[len(run) // 2]
                a, b = rows(frame)[y], rows(control)[y]
                assert any(rolled(b, s) == a for size in range(round(24 * k), round(96 * k) + 1)
                           for s in (size, -size)), y
    assert len({raw(f) for f in frames[0:6]}) == 1 and len({raw(f) for f in frames[6:12]}) == 1
    assert raw(frames[5]) != raw(frames[6])

    # `static medium` lasting: pixel = control × 0.70 (MULT) + gray noise × 0.30.
    rig = L(tmp_path / "static")
    rig.show(stage(HANA, DAICHI))
    control = rig.frame()
    rig.screen.glitch(on(("static", "medium")))
    for frame in rig.frames(8):
        assert len(static_pixels(frame, control, 0.30)) > 30          # noise, not a fill

    # tear + static + jitter: jitter copy, then tear, then static (D1).
    rig = L(tmp_path / "order")
    rig.show(stage(HANA, DAICHI))
    rig.frame()
    order: list[str] = []
    real_tear, real_copy, real_noise = (glitch_module.draw_tear, rig.view.draw_sprite_copy,
                                        rig.layer.noise.draw)
    monkeypatch.setattr(glitch_module, "draw_tear",
                        lambda *a: (order.append("tear"), real_tear(*a))[1])
    monkeypatch.setattr(rig.view, "draw_sprite_copy",
                        lambda *a: (order.append("jitter"), real_copy(*a))[1])
    monkeypatch.setattr(rig.layer.noise, "draw",
                        lambda *a: (order.append("static"), real_noise(*a))[1])
    rig.screen.glitch(on(("tear", "large"), ("static", "small"), ("jitter", "large", "hana")))
    rig.frames(3)
    assert order == ["jitter", "tear", "static"] * 3

    # `shake large horizontal` + tear: tear acts on the shaken frame, the band included.
    shaken, torn = L(tmp_path / "shake"), L(tmp_path / "shake_tear")
    for r in (shaken, torn):
        r.show(stage(HANA, DAICHI))
        r.frame()
        r.screen.shake(Shake("large", "horizontal", 1.0))
    torn.screen.glitch(on(("tear", "large")))
    for _ in range(12):
        a, b = shaken.frame(), torn.frame()
        assert same_row_multisets(b, a)

    # flash + static: the flash's first frame is pure white (flash over glitches).
    rig = L(tmp_path / "flash")
    rig.show(stage(HANA, DAICHI))
    rig.screen.glitch(on(("static", "large")))
    rig.frames(2)
    rig.screen.flash(Flash(None, 0.3, "f1"))
    assert tuple(rig.frame().get_at((320, 50)))[:3] == (255, 255, 255)

    # a dissolve under tear: each transition frame keeps the untorn frame's row multisets.
    plain, torn = L(tmp_path / "dis"), L(tmp_path / "dis_tear")
    for r in (plain, torn):
        r.show(stage(HANA, DAICHI))
        r.frame()
    torn.screen.glitch(on(("tear", "large")))
    for r in (plain, torn):
        r.show(stage(background="bg sea"), transition=dissolve())
    for _ in range(14):
        a, b = plain.frame(), torn.frame()
        assert plain.view.transitioning
        assert same_row_multisets(b, a)

    # an F18 title card under static: the card's pixels carry the noise.
    rig = L(tmp_path / "card")
    rig.view.card_painter = OpaqueCard()
    rig.show(stage(HANA), card=TitleCard("c", None, "One"))
    control = rig.frame()
    assert tuple(control.get_at((10, 10)))[:3] == CARD
    rig.screen.glitch(on(("static", "medium")))
    assert len(static_pixels(rig.frame(), control, 0.30)) > 30

    # a minigame (F23) open over the stage: no glitch (07 G8).
    rig = L(tmp_path / "minigame")
    rig.show(stage(HANA, DAICHI))
    control = rig.frame()
    rig.app.minigame_host = FakeHost()
    rig.screen.glitch(on(("tear", "large"), ("static", "large"), ("jitter", "large", "hana")))
    assert all(raw(f) == raw(control) for f in rig.frames(8))

    # App A: an opaque textbox over tear + static equals the control's every frame; with
    # the box hidden (K_h) the glitches keep changing, at most every 6 frames.
    glitched = _app_run(tmp_path / "app", "    effect tear large on\n    effect static on\n")
    control = _app_run(tmp_path / "app_ctl", "")
    assert glitched["box"] == control["box"]
    assert all(a != b for a, b in zip(glitched["stage"], control["stage"]))
    hidden = glitched["hidden"]
    changes = sum(a != b for a, b in zip(hidden, hidden[1:]))
    assert 3 <= changes <= len(hidden) // 6 + 1


def _app_run(root, effects: str) -> dict[str, list[int]]:
    """App A on Template G with an opaque box: 30 frames of "A." (box and stage CRCs), then
    K_h and 30 frames of the whole frame."""
    script = ('define hana = Character("Hana")\nlabel start:\n    scene bg grain\n'
              '    show hana happy at center\n' + effects + '    hana "A."\n    "End."\n')
    root = make_text_game(root, script=script,
                          config="[textbox]\ncps = 0\n[theme.textbox]\nfill_opacity = 1.0\n")
    gen.write(root, {GRAIN_REF: grain(), gen.ref_of("hana happy"): gen.block(300, 600, GREEN)})
    s = Session(root)
    out: dict[str, list[int]] = {"box": [], "stage": [], "hidden": []}

    def script_(s: Session):
        yield from s.until_line("A.")
        fb = s.fb
        x, y, w, h = (round(v) for v in s.textbox.geometry.box)
        for _ in range(30):
            yield
            box = fb.subsurface((x + 16, y + 16, w - 32, h - 32))
            out["box"].append(zlib.crc32(raw(box)))
            out["stage"].append(zlib.crc32(raw(fb.subsurface((0, 0, 1280, y)))))
        s.key(pygame.K_h)
        yield
        for _ in range(30):
            yield
            out["hidden"].append(zlib.crc32(raw(fb)))

    s.play(script_)
    return out


# --- AC-F28-14 — jitter acts on one sprite ----------------------------------------------------

def diff_mask(a: pygame.Surface, b: pygame.Surface) -> pygame.mask.Mask:
    """The pixels where ``a`` and ``b`` differ."""
    d1 = a.copy()
    d1.blit(b, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
    d2 = b.copy()
    d2.blit(a, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
    d1.blit(d2, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    mask = pygame.mask.from_threshold(d1, (0, 0, 0, 255), (1, 1, 1, 255))
    mask.invert()
    return mask


def green_rect(surface: pygame.Surface) -> pygame.Rect:
    return pygame.mask.from_threshold(surface, (*GREEN, 255), (1, 1, 1, 255)) \
        .get_bounding_rects()[0]


def only_inside(frame, control, rect: pygame.Rect, offset: tuple[int, int]) -> None:
    """Pixels differ only inside ``rect`` ∪ ``rect`` moved by ``offset``, and the moved rect
    (clipped) is hana's green."""
    mask = diff_mask(frame, control)
    block = pygame.mask.Mask(rect.size, fill=True)
    moved = rect.move(offset)
    mask.erase(block, rect.topleft)
    mask.erase(block, moved.topleft)
    assert mask.count() == 0
    green = pygame.mask.from_threshold(frame, (*GREEN, 255), (1, 1, 1, 255))
    visible = moved.clip(frame.get_rect())
    assert green.overlap_area(block, moved.topleft) == visible.width * visible.height


class CopySpy:
    def __init__(self, view) -> None:
        self.calls: list[tuple[str, tuple[int, int], bool]] = []
        real = view.draw_sprite_copy

        def spy(surface, tag, offset):
            result = real(surface, tag, offset)
            self.calls.append((tag, offset, result))
            return result

        view.draw_sprite_copy = spy


def test_ac_f28_14_jitter_acts_on_one_sprite(tmp_path):
    far_daichi = ("daichi", "daichi grin", (1150,))
    rig, ctl = L(tmp_path / "j"), L(tmp_path / "c")
    for r in (rig, ctl):
        r.show(stage(HANA, far_daichi))
    control, _ = ctl.frame(), rig.frame()
    rect = green_rect(control)
    spy = CopySpy(rig.view)
    rig.screen.glitch(on(("jitter", "large", "hana")))
    reach = round(24 * rig.scale)
    for _ in range(61):
        only_inside(rig.frame(), control, rect, spy.calls[-1][1])
    offsets = [offset for _, offset, result in spy.calls if result]
    assert len(offsets) == 61 and all(max(abs(dx), abs(dy)) <= reach for dx, dy in offsets)
    assert 0 < sum(a != b for a, b in zip(offsets, offsets[1:])) <= 12

    # `show hana sad at left`: the copy follows the new rect.
    for r in (rig, ctl):
        r.show(stage(("hana", "hana sad", "left"), far_daichi))
    control, frame = ctl.frame(), rig.frame()
    only_inside(frame, control, green_rect(control), spy.calls[-1][1])
    assert spy.calls[-1][2]

    # `hide hana`, then `show hana happy`: no copy from the hide frame on.
    for shown in (stage(far_daichi), stage(HANA, far_daichi)):
        for r in (rig, ctl):
            r.show(shown)
        for _ in range(6):
            assert raw(rig.frame()) == raw(ctl.frame())

    # hana at x = 0 jittering by up to 24 units in a letterboxed window: nothing outside
    # the viewport, no exception.
    rig, ctl = L(tmp_path / "edge", size=(640, 400)), L(tmp_path / "edge_c", size=(640, 400))
    for r in (rig, ctl):
        r.show(stage(("hana", "hana happy", (0,))))
    control, _ = ctl.frame(), rig.frame()
    rig.screen.glitch(on(("jitter", "large", "hana")))
    for _ in range(30):
        frame = rig.frame()
        for y in (0, 19, 380, 399):
            assert raw(frame.subsurface((0, y, 640, 1))) == raw(control.subsurface((0, y, 640, 1)))

    # Skips: a dissolve in play, FAST quality, a title card, placeholder art, an absent tag.
    rig, ctl = L(tmp_path / "skip"), L(tmp_path / "skip_c")
    for r in (rig, ctl):
        r.show(stage(HANA))
        r.frame()
    spy = CopySpy(rig.view)
    rig.screen.glitch(on(("jitter", "large", "hana"), ("jitter", "large", "ghost")))
    for r in (rig, ctl):
        r.show(stage(HANA, ("ghost", "ghost x", (1100,))), transition=dissolve(0.2))
    while True:                                          # the end frame jitters again
        a, b = rig.frame(), ctl.frame()
        if not rig.view.transitioning:
            break
        assert raw(a) == raw(b)
    assert len(spy.calls) >= 10 and not any(result for _, _, result in spy.calls[:-2])
    surface = rig.app.canvas.surface
    assert not rig.view.draw_sprite_copy(surface, "ghost", (5, 5))     # placeholder art
    assert not rig.view.draw_sprite_copy(surface, "daichi", (5, 5))    # not on the stage
    assert rig.view.draw_sprite_copy(surface, "hana", (5, 5))
    for r in (rig, ctl):                                 # FAST: F01's resize settle
        r.window.resize(800, 450)
    assert raw(rig.frame()) == raw(ctl.frame())
    assert rig.app.canvas.quality is RenderQuality.FAST
    assert not rig.view.draw_sprite_copy(rig.app.canvas.surface, "hana", (5, 5))
    rig.view.card_painter = ctl.view.card_painter = OpaqueCard()
    for r in (rig, ctl):
        r.show(stage(HANA), card=TitleCard("c", None, "One"))
    rig.app.canvas.quality = RenderQuality.FINAL
    rig.frame()
    assert not rig.view.draw_sprite_copy(rig.app.canvas.surface, "hana", (5, 5))


# --- AC-F28-16 — never a flash ----------------------------------------------------------------

def _channel_means(data: bytes) -> tuple[float, ...]:
    n = len(data) // 3
    return tuple(sum(data[c::3]) / n for c in range(3))


def _top_share(data: bytes) -> float:
    counts = Counter(data[i:i + 3] for i in range(0, len(data), 3))
    return counts.most_common(1)[0][1] / (len(data) // 3)


@pytest.mark.parametrize("kind", ["tear", "static", "jitter"])
def test_ac_f28_16_never_a_flash(tmp_path, kind):
    """Each look `large`, as `on` and as a 0.5 s burst, reduce off and on, 60 frames each
    at 640×360 (06 §0.4's default tier; the 600-frame sweep of every size isn't built)."""
    ctl = L(tmp_path / "c")
    ctl.show(stage(HANA))
    control = raw(ctl.frame())
    base_mean, base_share = sum(control) / len(control), _top_share(control)
    tag = "hana" if kind == "jitter" else None
    entry = (kind, "large", tag) if tag else (kind, "large")
    for reduce in (False, True):
        for form in ("on", "burst"):
            rig = L(tmp_path / f"{reduce}{form}", reduce=reduce)
            rig.show(stage(HANA))
            rig.frame()
            rig.screen.glitch(on(entry) if form == "on" else
                              burst(kind, "large", 0.5, tag=tag))
            frames = [raw(f) for f in rig.frames(60)]
            means = [sum(f) / len(f) for f in frames]
            if kind == "tear":
                assert all(abs(m - base_mean) <= 0.01 for m in means)
            elif kind == "jitter":
                assert all(abs(m - base_mean) <= 1.0 for m in means)
            elif not reduce:
                look = frames if form == "on" else frames[:30]
                assert all(abs(m - means[0]) <= 0.05 for m in means[:len(look)])
                first = _channel_means(look[0])
                assert all(max(abs(a - b) for a, b in zip(_channel_means(f), first)) <= 0.05
                           for f in look[::10])
                if form == "burst":
                    assert all(f == control for f in frames[30:])
            assert _top_share(frames[10]) <= base_share + 0.02      # no color fill
            if reduce and kind == "static":       # one still frame once faded in (0.3 s)
                assert len(set(frames[18:30])) == 1
            else:
                changes = sum(a != b for a, b in zip(frames, frames[1:]))
                assert changes <= (12 if kind == "jitter" else 10), (reduce, form, changes)
            if reduce and kind != "static":
                assert all(f == control for f in frames)
