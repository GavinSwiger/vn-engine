"""F28 step 1 — glitch math, noise, and the colorshift build, no window (``06-acceptance.md``
§1.1; ``04`` §6.5, §6.6; ``07`` I-4). AC-F28-02, AC-F28-03, AC-F28-04.

The default tier samples the pixel sweeps; ``slow`` runs every row the ACs name."""

from random import Random

import pygame
import pytest

from engine.core.constants import CANVAS_SIZE
from engine.render.glitch import (C, J, JITTER_RATE, NOISE_CELLS, S, STATIC_RATE, T, TEAR_RATE,
                                  ColorShift, Noise, band_rows, colorshift_px, draw_tear,
                                  jitter_offset, look_index, mix64, noise_offset, static_add,
                                  static_multiplier, tear_bands, tear_px)

SEEDS = (0, 1, 7, 2**32 - 1)
SENTINEL = (1, 2, 3)
MARGIN = 4


def grain(size: tuple[int, int], seed: int = 3) -> pygame.Surface:
    """``bg grain`` at ``size``: 8×8-unit blocks of seeded random RGB (``06`` §0.3, IMG9+)."""
    cells = (CANVAS_SIZE[0] // 8, CANVAS_SIZE[1] // 8)
    small = pygame.image.frombytes(Random(seed).randbytes(cells[0] * cells[1] * 3), cells, "RGB")
    return opaque(pygame.transform.scale(small, size))


def random_picture(size: tuple[int, int], seed: int) -> pygame.Surface:
    data = Random(seed).randbytes(size[0] * size[1] * 3)
    return opaque(pygame.image.frombytes(data, size, "RGB"))


def opaque(surface: pygame.Surface) -> pygame.Surface:
    """A 32-bit copy without alpha (the stage's composites are opaque)."""
    out = pygame.Surface(surface.get_size(), 0, 32)
    out.blit(surface, (0, 0))
    return out


def rgb(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


# --- AC-F28-02 — tear bands keep every row's pixels ------------------------------------------

def _check_bands(seed: int, k: int, shift: int) -> tuple:
    bands = tear_bands(seed, k, shift)
    assert tear_bands(seed, k, shift) == bands
    assert 2 <= len(bands) <= 6, (seed, k, shift, bands)
    assert sum(b.h for b in bands) <= 288
    last_end = 0
    for band in bands:                           # sorted by y, so overlap = start < last end
        assert 8 <= band.h <= 80 and 0 <= band.y <= CANVAS_SIZE[1] - band.h
        assert band.y >= last_end, bands
        last_end = band.y + band.h
        assert band.dx != 0 and shift / 4 <= abs(band.dx) <= shift
    return bands


_GRAIN: dict[tuple[int, int], pygame.Surface] = {}


def _check_draw(size: tuple[int, int], bands: tuple) -> None:
    w, h = size
    parent = pygame.Surface((w + 2 * MARGIN, h + 2 * MARGIN), 0, 32)
    parent.fill(SENTINEL)
    view = parent.subsurface((MARGIN, MARGIN, w, h))
    picture = _GRAIN.get(size) or _GRAIN.setdefault(size, grain(size))
    view.blit(picture, (0, 0))
    before = rgb(picture)
    sx, sy = w / CANVAS_SIZE[0], h / CANVAS_SIZE[1]
    draw_tear(view, bands, sx, sy)
    after_parent = rgb(parent)
    pw = 3 * (w + 2 * MARGIN)
    sentinel_row = bytes(SENTINEL) * (w + 2 * MARGIN)
    edge = bytes(SENTINEL) * MARGIN
    for row in range(h + 2 * MARGIN):            # the border around the subsurface is intact
        line = after_parent[row * pw:(row + 1) * pw]
        if row < MARGIN or row >= h + MARGIN:
            assert line == sentinel_row, row
        else:
            assert line[:3 * MARGIN] == edge and line[-3 * MARGIN:] == edge, row
    after = rgb(view)
    shifts = {}
    for band in bands:
        top, bottom = band_rows(band, sy, h)
        for row in range(top, bottom):
            shifts[row] = tear_px(band.dx, sx) % w
    for row in range(h):
        old, new = before[row * 3 * w:(row + 1) * 3 * w], after[row * 3 * w:(row + 1) * 3 * w]
        s = shifts.get(row, 0)
        assert new == (old[-3 * s:] + old[:-3 * s] if s else old), (size, row, s)
    for band in bands:                           # the row multiset, stated
        row = band_rows(band, sy, h)[0]
        old, new = before[row * 3 * w:(row + 1) * 3 * w], after[row * 3 * w:(row + 1) * 3 * w]
        assert sorted(zip(old[0::3], old[1::3], old[2::3])) == \
            sorted(zip(new[0::3], new[1::3], new[2::3]))


@pytest.mark.parametrize("tier", ["sample", pytest.param("full", marks=pytest.mark.slow)])
def test_ac_f28_02_tear_bands_keep_every_rows_pixels(tier):
    """Every band rule for k 0–999 (``slow``; the default tier k 0–249); drawn at both sizes
    for k 0–99 (``slow``; the default tier k 0–1 of seeds 0 and 7)."""
    _GRAIN.clear()                               # surfaces never outlive pygame.quit()
    drawn = 0
    for seed in SEEDS:
        for shift in (16, 40, 96):
            for k in range(1000 if tier == "full" else 250):
                bands = _check_bands(seed, k, shift)
                if (k < 100) if tier == "full" else (k < 2 and seed in (0, 7)):
                    for size in ((1280, 720), (1920, 1080)):
                        _check_draw(size, bands)
                        drawn += 1
    assert drawn >= 24
    assert tear_bands(7, 0, 0) == () and tear_bands(7, 0, -1) == ()


# --- AC-F28-03 — static, jitter, and size numbers --------------------------------------------

def _changes(values: list) -> list[int]:
    return [i for i in range(1, len(values)) if values[i] != values[i - 1]]


def _max_in_a_second(change_frames: list[int], fps: int) -> int:
    """The most changes in any half-open 1 s window starting at a sample."""
    best, j = 0, 0
    for i, start in enumerate(change_frames):
        while j < len(change_frames) and change_frames[j] < start + fps:
            j += 1
        best = max(best, j - i)
    return best


def test_ac_f28_03_static_jitter_and_size_numbers():
    assert (dict(T), dict(C), dict(S), dict(J)) == (
        {"small": 16, "medium": 40, "large": 96}, {"small": 2, "medium": 6, "large": 12},
        {"small": 0.15, "medium": 0.30, "large": 0.50}, {"small": 4, "medium": 10, "large": 24})
    # jitter offsets: integers in [−a, a], never (0, 0), all four signs
    for a in (4, 10, 24):
        signs = set()
        for k in range(10_000):
            dx, dy = jitter_offset(7, k, a)
            assert type(dx) is int and type(dy) is int and (dx or dy)
            assert -a <= dx <= a and -a <= dy <= a
            signs.add((dx > 0, dy > 0))
        assert len(signs) == 4, a
        assert jitter_offset(7, 3, a) == jitter_offset(7, 3, a)
    # rates over 0–10 s on a 1/600 s sweep (07 I-4: jitter 1/12 s)
    fps = 600
    times = [f / fps for f in range(10 * fps + 1)]
    jitter = [jitter_offset(7, look_index(t, JITTER_RATE), 10) for t in times]
    assert 0 < _max_in_a_second(_changes(jitter), fps) <= 12
    for rate in (TEAR_RATE, STATIC_RATE):
        assert _max_in_a_second(_changes([look_index(t, rate) for t in times]), fps) == 10
    # the noise field: 2-unit grain, byte mean 127.5 ± 1.0
    field = Noise(7).field()
    assert len(field) == NOISE_CELLS[0] * NOISE_CELLS[1] == 640 * 360
    assert abs(sum(field) / len(field) - 127.5) <= 1.0
    for size, px in (((1280, 720), 2), ((1920, 1080), 3)):
        noise = Noise(7)
        noise.prepare(pygame.Surface(size, 0, 32))
        cells = pygame.image.tobytes(noise.n8, "P")
        w = size[0]
        for row in range(size[1]):
            line = cells[row * w:(row + 1) * w]
            cell_row = field[(row // px) * 640:(row // px + 1) * 640]
            for i in range(px):
                assert line[i::px] == cell_row, (size, row)
    # Noise.draw: every frame's stage mean equals frame 0's; each pixel MULT then ADD, ± 1
    rng = Random(5)
    for size, ks in (((640, 360), range(21)), ((1280, 720), range(2))):
        picture = grain(size)
        w, h = size
        probes = [(rng.randrange(w), rng.randrange(h)) for _ in range(300)]
        for s in (0.15, 0.30, 0.50):
            noise = Noise(7)
            means = []
            for k in ks:
                frame = picture.copy()
                offset = noise_offset(7, k)
                noise.draw(frame, s, offset)
                data = rgb(frame)
                means.append(sum(data) / len(data))
                ox, oy = offset[0] * w // 640, offset[1] * h // 360
                m = static_multiplier(s)
                assert m == round(255 * (1 - s)) or abs(m - 255 * (1 - s)) == 0.5
                for x, y in probes:
                    cell = noise.n8.get_at_mapped(((x + ox) % w, (y + oy) % h))
                    add = static_add(cell, s)
                    got, src = frame.get_at((x, y)), picture.get_at((x, y))
                    for c in range(3):
                        want = min(255, ((src[c] * m + 255) >> 8) + add)
                        assert abs(got[c] - want) <= 1, (size, s, k, x, y)
            assert all(abs(mean - means[0]) <= 0.05 for mean in means), (size, s, means)
    # mix64: deterministic; another seed changes the bands for ≥ 990 of k 0–999
    assert mix64(7, 3) == mix64(7, 3) and mix64(7, 3) != mix64(8, 3)
    assert 0 <= mix64(-1, -5) < 2**64
    differ = sum(tear_bands(7, k, 40) != tear_bands(8, k, 40) for k in range(1000))
    assert differ >= 990


# --- AC-F28-04 — banded colorshift equals the reference --------------------------------------

def reference(picture: pygame.Surface, d: int) -> bytes:
    """``R(x) = P.R(x + d)`` (0 in the last d columns), ``G = P.G``, ``B(x) = P.B(x − d)``
    (0 in the first d columns)."""
    w, h = picture.get_size()
    data = rgb(picture)
    r, g, b = data[0::3], data[1::3], data[2::3]
    d = min(d, w)
    red = bytearray(r[d:] + bytes(d))
    blue = bytearray(bytes(d) + b[:len(b) - d])
    for c in range(w - d, w):
        red[c::w] = bytes(h)
    for c in range(d):
        blue[c::w] = bytes(h)
    out = bytearray(len(data))
    out[0::3], out[1::3], out[2::3] = red, g, blue
    return bytes(out)


@pytest.mark.parametrize("tier", ["sample", pytest.param("full", marks=pytest.mark.slow)])
def test_ac_f28_04_banded_colorshift_equals_the_reference(tier):
    assert colorshift_px(C["large"], 1280) == 12 and colorshift_px(C["large"], 1920) == 18
    assert colorshift_px(C["small"], 640) == 1
    seeds = range(1, 6) if tier == "full" else range(1, 3)
    for size in ((1280, 720), (1920, 1080), (1000, 541), (333, 811)):
        for seed in seeds:
            picture = random_picture(size, seed)
            for d in (1, 2, 12, 18):
                units = d * CANVAS_SIZE[0] / size[0]
                assert colorshift_px(units, size[0]) == d
                shift = ColorShift(units)
                steps, out = 0, None
                while out is None:
                    out = shift.filtered(picture, ("g", seed), step=True)
                    steps += 1
                assert steps == -(-size[1] // 270)            # one band per step
                assert rgb(out) == reference(picture, d), (size, seed, d)
                assert shift.buffers == 2                     # one output, one band buffer
            whole = ColorShift(C["large"]).complete(picture, ("w",))
            assert rgb(whole) == reference(picture, colorshift_px(C["large"], size[0]))
    # stale while building (07 I-8): the newest complete output, else None; ≤ 2 outputs
    a, b = random_picture((333, 811), 1), random_picture((333, 811), 2)
    shift = ColorShift(C["medium"])
    assert shift.filtered(a, (1,), step=False) is None
    done_a = shift.complete(a, (1,))
    assert shift.filtered(b, (2,), step=True) is done_a
    for _ in range(3):
        done_b = shift.filtered(b, (2,), step=True)
    assert done_b is not done_a and rgb(done_b) == reference(b, colorshift_px(6, 333))
    assert shift.filtered(a, (1,), step=False) is done_a              # still kept
    shift.filtered(a, (3,), step=True)                                # reuses a's slot
    assert shift.buffers == 3
    shift.release()
    assert shift.buffers == 0
