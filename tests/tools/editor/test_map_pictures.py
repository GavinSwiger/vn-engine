"""Studio UX 3.1 "Picture boxes on the map": the sketches (``mapsketch``), the painter's
Pictures mode (``mapcanvas``), the view's switch and tooltip, and the window's choice and
sketch source. The timed gate is ``tests/perf/test_live_map_perf.py``'s Pictures case."""

import pytest

from engine.tools.editor import mapsketch
from engine.tools.editor.mapsketch import (
    PICTURE_STRETCH, Sketch, count_lines, detail_text, scene_sketch)
from engine.tools.editor.storymap import BOX_HEIGHT, BOX_WIDTH, chip_center, curve_at, relayout
from tests.perf import gen_map_bench as gen

tk = pytest.importorskip("tkinter")


# --- Pure: a scene's sketch ------------------------------------------------------------------

def test_count_lines_skips_the_label_blanks_and_comments():
    assert count_lines(["label a:", "    # note", "", '    "Hi."', "    jump b"]) == 2
    assert detail_text("Chapter 2", Sketch(62)) == "Chapter 2 · 62 lines"
    assert detail_text(None, Sketch(1)) == "1 line"
    assert detail_text("Prologue", None) == "Prologue"


def test_a_sketch_has_its_background_and_a_figure_per_character():
    lines = ["label bridge:", "    scene bg night with fade", "    show hana happy at left",
             "    show daichi at right", '    hana "Look!"', "    show mei at center"]
    sketch = scene_sketch(lines, colors={"bg night": "#102040"},
                          color_of={"hana": "#ff8080"}.get)
    assert sketch.color == "#102040" and sketch.ref is None and sketch.known
    assert sketch.lines == 5
    (left, hana), (right, daichi) = sketch.figures         # mei comes after the first line
    assert hana == "#ff8080" and daichi == mapsketch.FIGURE_FALLBACK
    assert 0 < left < 0.5 < right < 1
    assert sketch.stage.background == "bg night" and len(sketch.stage.sprites) == 2
    file_bg = scene_sketch(lines, refs={"bg night": "images/bg/night.png"})
    assert file_bg.ref == "images/bg/night.png" and file_bg.color is None


def test_a_scene_without_a_background_carries_the_one_before_it_on():
    alone = scene_sketch(["label next:", "    show hana", '    "Then."'])
    assert not alone.known and alone.figures and alone.stage is None
    carried = scene_sketch(["label next:", '    "Then."'], lead=["    scene bg room"],
                           came_from="start", colors={"bg room": "#334455"})
    assert carried.known and carried.color == "#334455" and carried.lines == 1


# --- The painter in Pictures ------------------------------------------------------------------

@pytest.fixture
def canvas():
    from tests.tools.editor.test_window import new_root
    root = new_root()
    root.geometry("900x600")
    widget = tk.Canvas(root, width=900, height=600)
    widget.pack()
    root.update()
    yield widget
    root.destroy()


def _painter(canvas, idle=None):
    from tkinter import font as tkfont

    from engine.tools.editor.mapcanvas import MapPainter
    fonts = [tkfont.Font(root=canvas, family="Segoe UI", size=-px) for px in (13, 11, 12)]
    painter = MapPainter(canvas, name_font=fonts[0], detail_font=fonts[1], chip_font=fonts[2],
                         idle=idle or (lambda fn: None))
    painter.set_pictures(True)
    return painter


@pytest.mark.tk
def test_pictures_stretch_the_same_layout_and_keep_chips_on_their_arrows(canvas):
    labels, links = gen.labels(30, start=True), gen.links(30, start=True)
    layout, _ = relayout(None, links, labels)
    painter = _painter(canvas)
    painter.draw(layout)
    x0, y0, x1, y1 = painter.box_rect("s1")
    kx, ky = PICTURE_STRETCH
    assert (round(x1 - x0), round(y1 - y0)) == (round(BOX_WIDTH * kx), round(BOX_HEIGHT * ky))
    assert (x1 - x0, y1 - y0) == (180, 108)
    rects = [painter.rect_of(b) for b in layout.boxes]
    assert not any(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                   for i, a in enumerate(rects) for b in rects[i + 1:])
    for index, edge in enumerate(layout.edges):
        centre = chip_center(layout, index)
        if centre is None or edge.lift is not None:
            continue
        at = curve_at(painter.edge_points(layout, index), edge.slot)
        drawn = painter.corner(*centre)
        assert abs(at[0] - drawn[0]) < 3 and abs(at[1] - drawn[1]) < 3


@pytest.mark.tk
def test_sketches_are_drawn_on_idle_for_boxes_in_view_only(canvas):
    pending: list = []
    asked: list[str] = []

    def source(box):
        asked.append(box.name)
        return Sketch(9, "#203040", None, ((0.25, "#ff0000"), (0.75, "#00ff00")))

    labels, links = gen.labels(300, start=True), gen.links(300, start=True)
    layout, diff = relayout(None, links, labels)
    painter = _painter(canvas, idle=pending.append)
    painter.sketcher.source = source
    painter.draw(layout)
    assert pending and not asked                        # nothing before the idle pass
    while pending:
        pending.pop(0)()
    shown = {b.name for b in painter.sketcher.visible_boxes()}
    assert set(asked) == shown and 0 < len(shown) < 40
    found = painter.boxes["s1"] if "s1" in shown else painter.boxes[next(iter(shown))]
    assert canvas.itemcget(found.thumb, "fill").lower() == "#203040"
    assert "9 lines" in canvas.itemcget(found.where, "text")
    assert sum(canvas.type(i) in ("arc", "oval") for i in found.items) == 4
    # Nothing changed: the next pass draws nothing again.
    before = len(canvas.find_all())
    asked.clear()
    painter.sketcher.schedule()
    while pending:
        pending.pop(0)()
    assert len(canvas.find_all()) == before
    # A box redrawn by an update gets its known sketch at once (a pop-in grows it).
    name = next(iter(shown))
    now, change = relayout(layout, links, labels + [type(labels[0])("zz", gen.MAIN, 99999)],
                           pins=diff.placed)
    assert painter.apply(now, change)
    painter._draw_box(now.boxes[now.index_of(name)], layer=True)
    assert sum(canvas.type(i) in ("arc", "oval") for i in painter.boxes[name].items) == 4


@pytest.mark.tk
def test_compact_boxes_are_unchanged(canvas):
    layout, _ = relayout(None, gen.links(5, start=True), gen.labels(5, start=True))
    painter = _painter(canvas)
    painter.set_pictures(False)
    painter.draw(layout)
    x0, y0, x1, y1 = painter.box_rect("s1")
    assert (x1 - x0, y1 - y0) == (BOX_WIDTH, BOX_HEIGHT)
    assert painter.boxes["s1"].thumb is None


# --- The view: the switch, places, the tooltip ------------------------------------------------

@pytest.fixture
def root():
    from tests.tools.editor.test_window import new_root
    made = new_root()
    made.geometry("1200x800")
    yield made
    made.destroy()


def map_view(root):
    from engine.tools.editor.views import StoryMapView
    view = StoryMapView(root, background="#1e1e1e", family="Segoe UI", mod="Control",
                        on_open=lambda box: None)
    view.frame.pack(fill="both", expand=True)
    root.update()
    return view


@pytest.mark.tk
def test_the_switch_redraws_and_places_stay_in_compact_units(root):
    from engine.tools.editor import views
    view = map_view(root)
    chosen: list[bool] = []
    view.on_pictures = chosen.append
    view.set_data(gen.labels(12, start=True), gen.links(12, start=True), False)
    root.update()
    assert [b.cget("text") for b in view.look_buttons.values()] == ["Pictures", "Compact"]
    assert str(view.look_buttons[False].cget("style")) == "Secondary.TButton"
    view.look_buttons[True].invoke()
    assert view.pictures and view.painter.pictures and chosen == [True]
    assert str(view.look_buttons[True].cget("style")) == "Secondary.TButton"
    index = view.layout.index_of("s1")
    x0, y0, x1, y1 = view.box_rect(index)
    assert (x1 - x0, y1 - y0) == (180, 108)
    box = view.layout.boxes[index]
    assert view.map_point(round(x0 - view.canvas.canvasx(0)),
                          round(y0 - view.canvas.canvasy(0))) == (box.x, box.y)
    # The tooltip says where the scene is.
    view._show_tip(index)
    texts = [view.canvas.itemcget(i, "text") for i in view._tip
             if view.canvas.type(i) == "text"]
    assert texts == [f"{gen.MAIN}:{box.line}"]
    view._hover(index)
    view._hover(None)
    assert view._tip == [] and view._tip_id is None
    view.set_pictures(False, notify=True)
    assert chosen == [True, False] and view.box_rect(index)[3] - view.box_rect(index)[1] == 40
    assert views.PICTURES_BUTTON == "Pictures"


@pytest.mark.tk
def test_a_new_box_pops_in_with_its_sketch(root):
    from engine.tools.editor import motion
    view = map_view(root)
    view.set_pictures(True)
    view.painter.sketcher.source = lambda box: Sketch(3, "#405060", None, ((0.5, "#ff0000"),))
    labels, links = gen.labels(6, start=True), gen.links(6, start=True)
    view.set_data(labels, links, False)
    root.update()
    popped: list = []
    real = motion.pop_in
    try:
        import engine.tools.editor.views as views_module
        views_module.pop_in = lambda m, c, key, items, **kw: popped.append(list(items))
        new = type(labels[0])("zz", gen.MAIN, 99999)
        view.set_data(labels + [new], links + [type(links[0])("s1", "zz", "jump", gen.MAIN, 3)],
                      False)
    finally:
        views_module.pop_in = real
    assert popped, "the new box pops in"
    assert any(view.canvas.type(i) == "arc" for i in popped[0])


# --- The window: the choice is remembered; the sketches come from the scripts ----------------

window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_storyedit import (  # noqa: E402
    lanterns, studio_l)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401


@pytest.mark.tk
def test_the_window_remembers_the_choice_and_sketches_its_scenes(studio, lanterns):
    from engine.tools.editor import uiprefs
    ed = studio_l(studio, lanterns, compact=False)
    view = ed.story_map
    assert view.pictures                                # Pictures unless Compact was chosen
    source = view.painter.sketcher.source
    sketches = {b.name: source(b) for b in view.layout.boxes}
    assert sketches["start"].ref == "images/bg/room.png" and sketches["start"].lines == 3
    assert sketches["festival"].known and sketches["festival"].ref == "images/bg/room.png"
    assert sketches["river"].figures and sketches["river"].figures[0][0] < 0.5
    view.look_buttons[False].invoke()
    assert uiprefs.load().get("map_pictures") is False
    view.look_buttons[True].invoke()
    assert uiprefs.load().get("map_pictures") is True
    # Typing in a scene's opening changes its sketch (and only its own is read again).
    main = ed.win.files["script/main.vns"]
    at = main.widget.search("scene bg room", "1.0")
    main.widget.insert(f"{at} +1 lines linestart", "    show hana happy at right\n")
    ed.win._reindex()
    view.sketches_changed()
    box = view.layout.boxes[view.layout.index_of("start")]
    assert source(box).figures and source(box).figures[0][0] > 0.5


@pytest.mark.tk
def test_at_rest_the_boxes_in_view_swap_their_sketch_for_the_games_still(studio, lanterns):
    from engine.tools.editor import stagestills as ss
    from engine.tools.editor.mapsketch import STILL_OWNER, THUMB_HEIGHT, THUMB_INSET
    from tests.tools.editor.test_stagestills import FakeRunner
    ed = studio_l(studio, lanterns, compact=False)
    view, win = ed.story_map, ed.win
    runner = FakeRunner()
    stills = win.stage_stills = ss.StageStills(lambda: runner)
    ed.root.update()
    view._rested()
    ed.root.update()
    assert len(runner.asked) == 1                      # one at a time, never waiting
    serial, width, _config, stage = runner.asked[0]
    assert width == round(view.painter.box_size()[0] - 2 * THUMB_INSET * view._scale())
    wanted = stills.wanted()
    assert wanted and all(key.width == width for key in wanted)
    assert len(wanted) <= len(view.painter.sketcher.visible_boxes())
    picture = tk.PhotoImage(master=ed.root, width=width, height=round(width * 9 / 16))
    picture.put("#FF0000", to=(0, 0, picture.width(), picture.height()))
    import base64
    png = ed.root.tk.call(picture, "data", "-format", "png")
    runner.answer(stills, data=base64.b64encode(png).decode("ascii") if isinstance(png, bytes)
                  else str(png))
    ed.root.update()
    drawn = [d for d in view.painter.sketcher.drawn.values() if d.still]
    assert drawn, "a box shows the game's still"
    image = next(i for i in drawn[0].items if view.canvas.type(i) == "image")
    shown = view.canvas.itemcget(image, "image")
    assert int(ed.root.tk.call("image", "height", shown)) == round(THUMB_HEIGHT * view._scale())
    # Compact wants no stills.
    view.set_pictures(False)
    assert STILL_OWNER not in stills._owners


def test_a_background_is_decoded_once_for_every_zoom(root, tmp_path, monkeypatch):
    """v1 finding 5: a background is decoded once; each size up to SOURCE_AHEAD × the
    first comes from that decode; the thumbnail cache drops its oldest entries only; a
    file's stamp is read once per STAMP_TTL_S."""
    from types import SimpleNamespace

    from engine.core.paths import GamePaths
    from engine.tools.editor import helperhub

    game = tmp_path / "game"
    (game / "images" / "bg").mkdir(parents=True)
    picture = tk.PhotoImage(master=root, width=640, height=360)
    picture.put("#336699", to=(0, 0, 640, 360))
    picture.write(str(game / "images" / "bg" / "room.png"), format="png")
    stats: list[str] = []
    stamp = helperhub.file_stamp
    monkeypatch.setattr(helperhub, "file_stamp", lambda r, ref: (stats.append(ref),
                                                                 stamp(r, ref))[1])
    decodes: list[int] = []
    decode = mapsketch.SketchImages._decode_one
    monkeypatch.setattr(mapsketch.SketchImages, "_decode_one",
                        lambda self: (decodes.append(1), decode(self))[1])
    ready: list[str] = []
    images = mapsketch.SketchImages(SimpleNamespace(paths=GamePaths.for_game(game)), root,
                                    ready.append)
    ref = "images/bg/room.png"
    assert images.get(ref, 100, 40) is None
    root.update()
    assert ready == [ref] and len(decodes) == 1
    first = images.get(ref, 100, 40)
    assert first is not None and (first.width(), first.height()) == (100, 40)
    for w, h in ((150, 60), (200, 80), (75, 30)):           # zooms: no new decode
        image = images.get(ref, w, h)
        assert image is not None and image.width() <= w and image.height() <= h
    root.update()
    assert len(decodes) == 1 and stats == [ref]             # one stat within the TTL
    monkeypatch.setattr(mapsketch, "THUMBS_MAX", 3)
    images.get(ref, 90, 36)
    assert len(images.cache) == 3 and (ref, images._stamp(ref), 90, 36) in images.cache
