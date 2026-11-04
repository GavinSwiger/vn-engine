"""F58 P1: the incremental story-map layout, pure half (``01-design.md`` AC-F58-16, AC-F58-17;
``04-technical.md`` §7.6, §7.7; ``07`` I-8, I-9). No Tk."""

import random

from engine.tools.editor import storymap
from engine.tools.editor.storymap import (
    COLUMN_STEP, MapStep, Notes, chip_center, chip_size, layout, place_free, relayout)
from tests.perf import gen_map_bench as gen
from tests.tools.editor.live_fakes import count_calls

CHOICES = ("Go on", "Go back", "Ask about the festival lanterns tonight", "川へ行く", "",
           "Wait", "A much longer choice that is cut after twenty-four characters")


def _script(rng: random.Random, n: int) -> tuple[list[tuple], list[tuple]]:
    names = ["start", *(f"s{i}" for i in range(1, n))]
    labels = [(name, "script/a.vns" if i % 3 else "script/b.vns", 10 * i + 1)
              for i, name in enumerate(names)]
    links = []
    for i, name in enumerate(names):
        for _ in range(rng.randint(0, 3)):
            dst = rng.choice(names)
            kind = rng.choice(("jump", "menu", "menu", "call"))
            choice = rng.choice(CHOICES) if kind == "menu" else None
            links.append((name, dst, kind, "script/a.vns", 10 * i + 2, choice or None,
                          rng.random() < 0.3))
    return labels, links


def _edit(rng: random.Random, labels: list, links: list, step: int) -> None:
    what = rng.randrange(7)
    if what == 0:                                   # a new scene mid-file, linked to
        at = rng.randrange(1, len(labels) + 1)
        name = f"new{step}"
        labels.insert(at, (name, "script/a.vns", 5 + step))
        src = labels[rng.randrange(len(labels))][0]
        links.append((src, name, "menu", "script/a.vns", 3, rng.choice(CHOICES) or None,
                      False))
    elif what == 1 and len(labels) > 3:             # a scene removed
        del labels[rng.randrange(1, len(labels))]
    elif what == 2 and links:                       # an arrow removed
        del links[rng.randrange(len(links))]
    elif what == 3:                                 # an arrow added
        src, dst = rng.choice(labels)[0], rng.choice(labels)[0]
        links.insert(rng.randrange(len(links) + 1),
                     (src, dst, "menu", "script/a.vns", 1, rng.choice(CHOICES) or None, True))
    elif what == 4 and links:                       # a choice's text changed
        i = rng.randrange(len(links))
        row = list(links[i])
        row[5] = rng.choice(CHOICES) or None
        links[i] = tuple(row)
    elif what == 5 and len(links) > 1:              # two arrows swap (link order)
        i, j = rng.randrange(len(links)), rng.randrange(len(links))
        links[i], links[j] = links[j], links[i]
    else:                                           # a line shift (line numbers only)
        labels[:] = [(n, f, line + 1) for n, f, line in labels]


def _same(a, b) -> None:
    def by_name(m):
        boxes = {x.name: (x.x, x.y, x.marks, x.line) for x in m.boxes}
        edges = {m.edge_key(i): (e.choice, e.conditional, e.slot, e.lift)
                 for i, e in enumerate(m.edges)}
        return boxes, edges
    assert by_name(a) == by_name(b)
    assert a == b


def test_ac_f58_16_relayout_equals_layout_and_reslots_only_affected_chips(monkeypatch):
    # Property: seeded random scripts and edits; relayout from the last layout, with the
    # pins the window would keep (every automatically placed box) and a few author places,
    # equals a full layout with those as places, by name, slots included.
    for seed in range(12):
        rng = random.Random(seed)
        labels, links = _script(rng, rng.randint(5, 40))
        notes = {labels[1][0]: Notes(chapter="One", endings=("e",))}
        prev, diff = relayout(None, links, labels, notes=notes)
        assert diff.full and prev == layout(links, labels, notes=notes)
        pins = dict(diff.placed)
        places: dict[str, tuple[int, int]] = {}
        for step in range(25):
            _edit(rng, labels, links, step)
            if rng.random() < 0.15:
                places[rng.choice(labels)[0]] = (rng.randrange(0, 2000, 20),
                                                 rng.randrange(0, 900, 20))
            stale = {labels[-1][0]} if rng.random() < 0.2 else set()
            keep = rng.random() < 0.2
            now, diff = relayout(prev, links, labels, notes=notes, stale=stale,
                                 pins=pins, places=places, keep=keep)
            full = layout(links, labels, notes=notes, stale=stale,
                          places={**pins, **places})
            _same(now, full)
            if keep:                                # a dry run leaves prev usable
                again, _ = relayout(prev, links, labels, notes=notes, stale=stale,
                                    pins=pins, places=places)
                _same(again, full)
                now = again
            pins.update(diff.placed)
            prev = now
        # A prev whose cache moved on still lays out right (it slots everything again).
        stale_prev = prev
        relayout(stale_prev, links, labels, pins=pins, places=places)
        _same(relayout(stale_prev, links, labels, pins=pins, places=places)[0],
              layout(links, labels, places={**pins, **places}))

    # Counted chip_slot: a one-scene change on 300 scenes re-slots only the chips near it.
    n = 300
    labels, links = gen.labels(n, start=True), gen.links(n, start=True)
    counted = count_calls(monkeypatch, storymap, "chip_slot")
    first, diff = relayout(None, links, labels)
    assert counted.n == len(links)                  # every chip once in a full layout
    pins = dict(diff.placed)
    counted.n = 0
    same, quiet = relayout(first, links, labels, pins=pins)
    assert counted.n == 0 and not quiet and same == first
    counted.n = 0
    more = links + [type(links[0])("s150", "s9", "menu", gen.MAIN, 1, "Back to the bridge")]
    now, diff = relayout(same, more, labels, pins=pins)
    assert 1 <= counted.n <= 12, counted.n
    assert diff.edges_added == (("s150", "s9", "menu"),) and not diff.moved
    _same(now, layout(more, labels, places=pins))


def test_ac_f58_17_no_layout_file_boxes_stay_and_new_ones_land_beside_their_linker():
    labels = [(f"s{i}" if i else "start", "script/a.vns", 9 * i + 1) for i in range(30)]
    links = [(a[0], b[0], "menu", "script/a.vns", 1, "Go on", False)
             for a, b in zip(labels, labels[1:])]
    first, diff = relayout(None, links, labels)
    pins = dict(diff.placed)
    assert pins == {b.name: (b.x, b.y) for b in first.boxes}
    spots = {b.name: (b.x, b.y) for b in first.boxes}

    # A scene added mid-file: no other box moves; it goes to place_free near its linker.
    added = labels[:12] + [("side", "script/a.vns", 100)] + labels[12:]
    more = links + [("s11", "side", "jump", "script/a.vns", 99)]
    now, diff = relayout(first, more, added, pins=pins)
    at = {b.name: (b.x, b.y) for b in now.boxes}
    assert {k: v for k, v in at.items() if k != "side"} == spots
    near = (spots["s11"][0] + COLUMN_STEP, spots["s11"][1])
    assert at["side"] == place_free(spots.values(), near) == diff.placed["side"]
    assert diff.added == ("side",) and not diff.moved
    pins.update(diff.placed)

    # A scene removed (and its arrows): nothing else moves.
    fewer = [row for row in added if row[0] != "s20"]
    cut = [row for row in more if "s20" not in row[:2]]
    after, diff = relayout(now, cut, fewer, pins=pins)
    assert {b.name: (b.x, b.y) for b in after.boxes} == {k: v for k, v in at.items()
                                                          if k != "s20"}
    assert diff.removed == ("s20",) and not diff.moved and not diff.added


def test_f58_p1_chip_helpers_and_tidy_pins():
    # 07 I-8: wide characters count twice in the estimate; a chip's centre is known.
    assert chip_size("ab")[0] + 2 * storymap.CHIP_CHAR_PX == chip_size("川a")[0] + \
        storymap.CHIP_CHAR_PX
    m = layout([("start", "b", "menu", "f", 1, "Go", False)], ["start", "b"])
    assert chip_center(m, 0) is not None and m.index_of("b") == 1
    # 07 I-9: MapStep.pins is the last field, None by default.
    assert MapStep("Move", {}, {}).pins is None
    step = MapStep("Tidy up", {}, {}, (), ({None: {"a": (0, 0)}}, {None: {"a": (20, 0)}}))
    assert step.pins[1][None]["a"] == (20, 0)
