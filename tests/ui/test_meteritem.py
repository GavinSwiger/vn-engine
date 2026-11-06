"""F62 round 2: ``ui/meteritem.MeterItem`` (the five looks, compact rows, live values), the
corner's rank pulse, ``app/meters.MeterCorner`` (follows the shown list; cuts after a reset),
and contrast in every scheme. Layout rows use F05's M20 metrics (17 units per character at
24); pixel probes draw with the bundled font under the dummy driver."""

from types import SimpleNamespace

import pygame
import pytest

from engine.app.meters import MeterCorner
from engine.app.ui_contrast import PAIRS, pair_ratios
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.core.schemes import SCHEMES
from engine.core.skins import METER_LOOKS
from engine.render.canvas import Canvas, RenderQuality
from engine.core.geometry import Viewport
from engine.runtime.interpreter import Status
from engine.runtime.points import MeterSpec, Points
from engine.ui.meteritem import MeterItem, MeterReading, marks, shown_look
from engine.ui.statuscorner import PULSE_S, CornerStyle, StatusCorner, corner_style
from engine.ui.theme import plain_theme
from tests.ui.test_statuscorner import BERRY, corner, game_shell, m20, _frame

S, P = 24, 34                               # the corner text size and its pitch


def ctx(place="top_left"):
    layer = corner(reduce=True)
    return layer._context(CornerStyle(), place)


def item(look, reading, *, label="Hana", narrow=None):
    return MeterItem(look, label, lambda: reading, narrow=lambda: narrow)


HANA = MeterReading(3, 0, 5, "Friend")


def test_marks_one_per_point_then_five_to_ten():
    assert [marks(0, n) for n in (1, 5, 10)] == [1, 5, 10]
    assert marks(0, 100) == 10 and marks(0, 12) == 6 and marks(0, 21) == 7
    assert marks(0, 13) == 10                           # nothing divides: ten
    assert marks(5, 5) == 1


def test_a_meter_with_no_range_is_a_number():
    bare = MeterReading(7)
    assert [shown_look(look, bare) for look in METER_LOOKS] == ["number"] * 5
    assert [shown_look(look, HANA) for look in METER_LOOKS] == list(METER_LOOKS)
    assert shown_look("sparkles", HANA) == "bar"


def test_reading_share():
    assert HANA.share == pytest.approx(0.6)
    assert MeterReading(-4, 0, 10).share == 0.0 and MeterReading(12, 0, 10).share == 1.0


@pytest.mark.parametrize("look,gauge_w,row", [
    ("bar", 6 * S, P), ("number", m20("3", S), P), ("hearts", 4 * 25 + 22, P),
    ("pips", 4 * 20 + 14, P), ("dial", 48 + 6 + m20("3", S), 48)])
def test_layout_per_look(look, gauge_w, row):
    label = m20("Hana", S)
    w, h = item(look, HANA).measure(ctx())
    assert h == row + P                                 # label + gauge, then the rank
    assert w == pytest.approx(max(label + round(S * 0.4) + gauge_w, m20("Friend", S)))
    # no ranks: one row
    assert item(look, MeterReading(3, 0, 5)).measure(ctx())[1] == row


@pytest.mark.parametrize("look", METER_LOOKS)
def test_the_nvl_column_form_fits_its_width(look):
    # NVL's default margin leaves 132 units: label, gauge and rank each take a row
    w, h = item(look, MeterReading(7, 0, 10, "Friend"), label="Sanity", narrow=132).measure(ctx())
    assert w <= 132, (look, w)
    assert h >= 3 * P - 1 if look in ("number", "dial") else h > 2 * P
    # below the first rank the rank row stays (no jump)
    low = item(look, MeterReading(0, 0, 10, ""), label="Sanity", narrow=132)
    assert low.measure(ctx())[1] == h


def test_values_update_live_and_resize():
    points = Points((MeterSpec("coins"),))
    reading = lambda: MeterReading(points.get("coins"))                     # noqa: E731
    shown = MeterItem("number", "Coins", reading)
    layer = corner(reduce=True)
    layer.set_item("c", "top_right", shown)
    before = layer.views()[0].box.w
    points.add("coins", 12345)
    after = layer.views()[0].box.w
    assert after - before == pytest.approx(m20("12,345", S) - m20("0", S))


def test_the_pulse_rises_and_falls_and_reduce_motion_has_none():
    layer = corner()
    layer.set_item("m", "top_left", item("bar", HANA))
    layer.update(1.0)
    layer.pulse("m")
    assert layer.views()[0].pulse == 0.0
    layer.update(PULSE_S / 2)
    assert layer.views()[0].pulse == pytest.approx(1.0)
    layer.update(PULSE_S)
    assert layer.views()[0].pulse == 0.0
    cut = corner(reduce=True)
    cut.set_item("m", "top_left", item("bar", HANA))
    cut.pulse("m")
    cut.update(PULSE_S / 2)
    assert cut.views()[0].pulse == 0.0


def test_set_and_remove_without_a_fade():
    layer = corner()
    layer.set_item("m", "top_left", item("bar", HANA), fade=False)
    assert layer.views()[0].opacity == 1.0
    layer.remove_item("m", fade=False)
    assert layer.keys() == ()


# --- Drawing --------------------------------------------------------------------------------

def _accent_pixels(frame, box):
    return sum(1 for x in range(int(box.x), int(box.right)) for y in range(int(box.y),
               int(box.bottom)) if all(abs(a - b) <= 6 for a, b in
                                       zip(tuple(frame.get_at((x, y)))[:3], BERRY)))


@pytest.mark.parametrize("look", METER_LOOKS)
def test_each_look_draws_its_marks_in_the_accent(look):
    shell, textbox = game_shell()
    shell.corner.set_item("m", "top_right", item(look, MeterReading(4, 0, 5, "Friend")))
    shell.update_layer(0.0, focused=True)
    (view,) = shell.corner.views()
    frame = _frame(shell)
    gauge = view.box
    found = _accent_pixels(frame, gauge)
    if look == "number":
        assert found <= 10, found                       # text only: no accent marks
    else:
        assert found > 40, (look, found)


def test_a_half_mark_is_half_filled():
    shell, _ = game_shell()
    full = item("hearts", MeterReading(100, 0, 100), label="")
    half = item("hearts", MeterReading(95, 0, 100), label="")
    shell.corner.set_item("full", "top_right", full)
    shell.corner.set_item("half", "bottom_right", half)
    shell.update_layer(0.0, focused=True)
    views = {v.key: v.box for v in shell.corner.views()}
    frame = _frame(shell)
    assert _accent_pixels(frame, views["half"]) < _accent_pixels(frame, views["full"])


@pytest.mark.parametrize("scheme", sorted(SCHEMES))
def test_every_scheme_meters_meet_contrast(tmp_path, scheme):
    """A meter draws only the corner's text and accent colors, so the corner's two W67
    pairs (text 4.5:1, marks 3:1, over black and white) are its contrast in every scheme."""
    (tmp_path / "config.toml").write_text(f'[theme]\npreset = "{scheme}"\n', encoding="utf-8")
    cfg = load_config(GamePaths.for_game(tmp_path)).config.theme
    for pair in (p for p in PAIRS if p.fg.startswith("corner.")):
        assert min(pair_ratios(cfg, pair)) >= pair.minimum, (scheme, pair.fg)
    style = corner_style(plain_theme(cfg))
    layer = StatusCorner(style, lambda font: m20, reduce_motion=lambda: True)
    layer.set_item("m", "top_left", item("bar", MeterReading(5, 0, 5), label=""))
    shell, _ = game_shell()
    canvas = Canvas(shell.assets)
    frame = pygame.Surface((1280, 720))
    canvas.bind(frame, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
    layer.draw(canvas, shell.painter)
    box = layer.views()[0].box
    middle = (int(box.x + box.w / 2), int(box.y + box.h / 2))
    assert tuple(frame.get_at(middle))[:3] == tuple(style.accent_color), scheme


# --- MeterCorner: the shown list in the corner ----------------------------------------------

def _owner(points):
    shell, textbox = game_shell()
    interp = SimpleNamespace(points=points, status=Status.WAITING)
    app = SimpleNamespace(shell=shell, textbox=textbox, config=SimpleNamespace(
        theme=SimpleNamespace(kit="romance"), meter={}))
    return shell, MeterCorner(app, interp)


def test_meter_corner_follows_the_shown_list_and_cuts_after_a_reset():
    points = Points((MeterSpec("affection", 0, 10, 0, True, (("Stranger", 0), ("Close", 8))),
                     MeterSpec("courage", 0, 10, 3, True)))
    shell, owner = _owner(points)
    corner_ = shell.corner
    points.show("affection", "courage")
    owner.sync()                                        # the first fill is a cut
    assert corner_.keys("top_right") == (("meter", "affection"), ("meter", "courage"))
    assert all(v.opacity == 1.0 for v in corner_.views())
    first = corner_.item(("meter", "affection"))
    assert (first.look, first.label) == ("hearts", "Affection")     # the romance kit
    assert first.narrow() is None
    owner.app.textbox.nvl = SimpleNamespace(on=True, metrics=SimpleNamespace(
        left=180, top=64, width=920, height=584))
    assert first.narrow() == 180 - 24 - 2 * 12                      # beside NVL's column
    owner.app.textbox.nvl = SimpleNamespace(on=False)
    points.hide("courage")
    owner.sync()
    points.add("affection", 9)                          # Stranger -> Close: a pulse
    owner.sync()
    corner_._reduce_motion = lambda: False
    points.add("affection", -9)
    owner.sync()
    corner_.update(PULSE_S / 2)
    views = {v.key: v for v in corner_.views()}
    assert views[("meter", "affection")].pulse > 0.9
    # a load: the reset drops them at once; the next sync refills as cuts, with no pulse
    owner.reset()
    assert corner_.keys() == ()
    points.install(points.merge(points.state()))
    owner.sync()
    assert [v.opacity for v in corner_.views()] == [1.0]
    assert corner_.views()[0].pulse == 0.0
    # the title (no game): nothing
    owner.interp.status = Status.IDLE
    owner.sync()
    corner_.update(1.0)
    assert corner_.keys() == ()
