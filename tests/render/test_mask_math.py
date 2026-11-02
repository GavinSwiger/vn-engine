"""F09 step 3 — progress, easing, fade weights, and the mask LUT, no window
(``06-acceptance.md`` §0.2 unit; ``04`` §6.4–6.6; 07 I-1). AC-F09-19."""

from engine.render.transitions import (ease_in_out, fade_weight, linear, mask_alpha,
                                       mask_palette, progress)


def test_ac_f09_19_progress_easing_and_mask_math():
    assert progress(0.25, 0.5) == 0.5 and progress(0.6, 0.5) == 1.0
    assert linear(0.3) == 0.3
    assert abs(ease_in_out(0.25) - 0.1464) <= 0.0001 and abs(ease_in_out(0.5) - 0.5) < 1e-12
    assert [fade_weight(p) for p in (0.25, 0.5, 0.75)] == [(False, 0.5), (True, 0.0),
                                                          (True, 0.5)]
    rows = [  # (i, p, soft, reverse, allowed α)
        (128, 0.5, 0.1, False, {122, 123}),
        (0, 0.05, 0.1, False, {139, 140, 141}),
        (255, 0.5, 0.1, False, {0}),
        (255, 0.5, 0.1, True, {255}),
        (127, 0.5, 0.0, False, {255}),
        (128, 0.5, 0.0, False, {0}),
        (128, 0.5, 0.5, False, {126, 127}),
    ]
    for i, p, soft, reverse, allowed in rows:
        assert mask_alpha(i, p, soft, reverse) in allowed, (i, p, soft, reverse)
    assert mask_palette(0.5, 0.1, False)[255] == (255, 255, 0)
    # G3 / 07 I-1: never falls as p grows; 0 at p = 0 and 255 at p = 1.
    for soft in (0.0, 0.05, 0.1, 0.5):
        for reverse in (False, True):
            last = [0] * 256
            for step in range(65):
                now = [mask_alpha(i, step / 64, soft, reverse) for i in range(256)]
                assert all(a >= b for a, b in zip(now, last)), (soft, reverse, step)
                assert step or now == [0] * 256
                last = now
            assert last == [255] * 256, (soft, reverse)
