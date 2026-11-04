"""F58 P2: the live map's pure model (``01-design.md`` AC-F58-10, 18, 22, 23, 29, 33;
``04-technical.md`` §7.4, §7.5, §7.7, §7.9, §7.10). No Tk; timers run on ``FakeClock``."""

import inspect
import random

from engine.tools.assistant import edits
from engine.tools.assistant.edits import ProposalFile
from engine.tools.editor import livemap, scenes
from engine.tools.editor.livemap import (
    FileRows, FollowClock, GlowSet, MapLine, MapModel, Pins, UpdateBatch, glow_items,
    preview_rows, stale_by_index)
from engine.tools.editor.scriptedit import FilePlan, LineEdit
from engine.tools.editor.storymap import relayout
from tests.tools.editor.live_fakes import FakeClock

A = "script/a.vns"


def _clock_and_follow():
    clock = FakeClock()
    fired: list[tuple[float, bool]] = []
    follow = FollowClock(lambda throttle: fired.append((clock.now(), throttle)),
                         after=clock.after, cancel=clock.after_cancel, now=clock.now)
    return clock, follow, fired


def test_ac_f58_10_follow_debounce_and_throttle_on_a_fake_clock():
    assert (livemap.FOLLOW_MS, livemap.FOLLOW_MAX_MS) == (80, 250)        # C1
    clock, follow, fired = _clock_and_follow()
    follow.changed()
    clock.advance(30)
    follow.changed()                                    # the debounce restarts
    clock.advance(79)
    assert fired == []
    clock.advance(1)
    assert fired == [(110, False)]                      # 80 ms after the last change

    # Changes every 50 ms for 2 s: an update at least every 250 ms, timed from the previous
    # update's start; each a throttle tick, then one pause tick 80 ms after the last change.
    fired.clear()
    start = clock.now()
    for _ in range(40):
        follow.changed()
        clock.advance(50)
    clock.advance(200)
    times = [start] + [t for t, _ in fired]
    assert max(b - a for a, b in zip(times, times[1:])) <= 250
    assert all(throttle for _, throttle in fired[:-1]) and fired[-1] == (start + 1950 + 80,
                                                                          False)
    # An action follows at once and drops the wait.
    fired.clear()
    follow.changed()
    follow.now()
    clock.advance(500)
    assert fired == [(clock.now() - 500, False)] and not follow.pending


def test_ac_f58_18_a_label_renamed_by_typing_keeps_its_spot_and_glows_once():
    before = FileRows((("start", 1), ("festival", 5), ("river", 9)),
                      (("start", "festival", "jump", None, False),
                       ("festival", "river", "menu", "Go", False)))
    after = FileRows((("start", 1), ("fair", 5), ("river", 9)),
                     (("start", "fair", "jump", None, False),
                      ("fair", "river", "menu", "Go", False)))
    model = MapModel()
    model.set_file(A, before)
    shown = model.snapshot()
    old, diff = relayout(None, model.links(), model.labels())
    pins = Pins()
    pins.add(None, diff.placed)
    model.set_file(A, after)
    delta = model.delta(shown)
    assert delta.renamed == (("festival", "fair"),) and not delta.added and not delta.removed
    pins.rename("festival", "fair")
    new, diff = relayout(old, model.links(), model.labels(), pins=pins.of(None))
    spot = lambda m, n: (m.boxes[m.index_of(n)].x, m.boxes[m.index_of(n)].y)  # noqa: E731
    assert spot(new, "fair") == spot(old, "festival") and not diff.placed
    boxes, edges, ghosts, _ = glow_items(delta, old, new, diff)
    assert boxes.count("fair") == 1 and "festival" not in ghosts
    clock = FakeClock()
    glow = GlowSet(clock.now)
    assert glow.start(boxes, edges).changes[0] == (("box", "fair"), 1.0)
    clock.advance(500)
    assert glow.start(["fair"]).changes == ()           # not restarted within 1 s
    assert ("box", "fair") in glow


def test_ac_f58_22_coalescing_one_update_per_tick_and_per_hold():
    batch = UpdateBatch()
    updates = []

    def tick(news):                                     # one watch tick's news, then the poll
        for ref, text in news:
            batch.add(ref, text)
        if batch.ready():
            updates.append(batch.take())

    tick([(A, f"version {i}") for i in range(5)])       # 5 writes in one tick
    assert updates == [{A: "version 4"}]
    updates.clear()
    files = [f"script/f{i}.vns" for i in range(50)]     # a 50-file checkout over two ticks
    tick([(ref, "x") for ref in files[:30]])
    tick([(ref, "y") for ref in files[30:]])
    assert 1 <= len(updates) <= 2 and sum(len(u) for u in updates) == 50
    updates.clear()
    batch.hold("drag")
    batch.hold("hidden")
    for i in range(6):
        tick([(A, f"held {i}"), (files[i], "z")])
    assert updates == [] and len(batch) == 7
    assert not batch.release("drag")
    assert batch.release("hidden")
    tick([])
    assert len(updates) == 1 and updates[0][A] == "held 5"


def test_ac_f58_23_parse_budget_and_the_big_batch():
    clock = FakeClock()
    batch = UpdateBatch()
    for i in range(10):
        batch.add(f"script/f{i}.vns", "text")
    done: list[str] = []

    def work(ref, _text):
        done.append(ref)
        clock.advance(12)                               # 12 ms of parsing each

    assert not batch.step(work, clock.now)
    assert len(done) == 3                               # past 30 ms: the rest waits
    assert not batch.step(work, clock.now) and len(done) == 6
    while not batch.step(work, clock.now):
        pass
    assert len(done) == 10
    big = UpdateBatch()
    for i in range(6):
        big.add(f"script/f{i}.vns", "x")
    assert big.big(lambda ref, text: 10_000)            # 60,000 changed lines
    assert not big.big(lambda ref, text: 8_000)         # 48,000
    assert livemap.s4(6) == "Many changes on disk (6 files). The map updates after the check."


def test_ac_f58_29_preview_text_safety():
    model = MapModel()
    model.set_file(A, FileRows((("start", 1),), ()))
    evil = "evil‮name​"
    after = FileRows((("start", 1), (evil, 5)),
                     (("start", evil, "menu", "Run\x07 ⁦away⁩ and never look back", True),))
    found = preview_rows(model, {A: after})
    shown = found.texts[evil]
    assert "‮" not in shown and "​" not in shown
    assert "\\u202e" in shown and "\\u200b" in shown
    chip = found.texts[("start", evil, "menu")]
    assert "\x07" not in chip and "⁦" not in chip and len(chip) <= 25
    assert chip.endswith("…")
    # The card's title and summary aren't inputs: they can't reach the map.
    assert list(inspect.signature(preview_rows).parameters) == ["model", "after"]


def test_ac_f58_33_status_texts_verbatim():
    assert livemap.s1(["script/ch2.vns"]) == "Updated from disk: `script/ch2.vns`."
    assert livemap.s1(["a", "b"]) == "Updated from disk: 2 files."
    assert livemap.s2("script/ch3.vns") == (
        "`script/ch3.vns` changed on disk, and you have unsaved changes in it. "
        "Studio will ask which to keep.")
    assert livemap.S3 == "The map will update when you finish."
    assert livemap.s4(50) == "Many changes on disk (50 files). The map updates after the check."
    assert livemap.s5(73) == "73 changes on the map."
    assert livemap.S6 == ("Some script files are too large to follow live. They update after "
                          "each check.")
    assert livemap.s7(1, 0, 2, 1) == (
        "Preview of the Assistant's change: 1 new scene, 2 new arrows, 1 removed arrow. "
        "Apply or Discard it in the Assistant pane.")
    assert livemap.s7(0, 2, 0, 0) == ("Preview of the Assistant's change: 2 removed scenes. "
                                      "Apply or Discard it in the Assistant pane.")
    assert livemap.s7(0, 0, 0, 0) == livemap.S8 == \
        "The Assistant's change doesn't change the map."
    assert (livemap.FOLLOW_CHANGES, livemap.REDUCE_MOTION) == ("Follow changes",
                                                                "Reduce motion")
    assert (livemap.MARK_PROPOSED, livemap.MARK_REMOVED) == ("proposed", "removed")
    # Past 200 preview items: ", and {n} more".
    model = MapModel()
    model.set_file(A, FileRows((("start", 1),), ()))
    many = FileRows((("start", 1), *((f"n{i}", i + 2) for i in range(150))),
                    tuple(("start", f"n{i}", "jump", None, False) for i in range(150)))
    found = preview_rows(model, {A: many})
    assert (len(found.boxes_added), len(found.edges_added), found.more) == (150, 50, 100)
    assert found.line == ("Preview of the Assistant's change: 150 new scenes, 50 new arrows, "
                          "and 100 more. Apply or Discard it in the Assistant pane.")
    # The line: S2 outranks the rest; else the newest; S1/S5 clear after 5 s or an update.
    clock = FakeClock()
    line = MapLine(clock.now)
    line.say("S1", livemap.s1(["x"]))
    line.say("S3", livemap.S3)
    assert line.text() == livemap.S3
    line.say("S2", livemap.s2("y"))
    line.say("S5", livemap.s5(60))
    assert line.kind() == "S2"
    line.clear("S2")
    assert line.text() == livemap.s5(60)
    clock.advance(5_000)
    assert line.expire() and line.text() == livemap.S3
    line.say("S1", "u")
    line.update_started()
    assert line.text() == livemap.S3


def test_f58_p2_glow_fades_in_four_steps_or_one_under_reduce_motion():
    clock = FakeClock()
    glow = GlowSet(clock.now)
    glow.start(["a"])
    glow.start(edges=[("a", "b", "jump")], reduce=True)
    seen: list[tuple] = []
    while glow.due() is not None:
        clock.advance(glow.due() - clock.now())
        seen.extend((clock.now(), *change) for change in glow.tick())
    assert seen == [(1400, ("box", "a"), 0.8), (1550, ("box", "a"), 0.6),
                    (1700, ("box", "a"), 0.4), (1850, ("box", "a"), 0.2),
                    (2000, ("box", "a"), None), (2000, ("edge", ("a", "b", "jump")), None)]
    over = glow.start([f"b{i}" for i in range(51)])
    assert over.over == 51 and over.changes == () and len(glow) == 0
    pins = Pins(cap=3)
    pins.add(None, {"a": (0, 0), "b": (20, 0)})
    pins.removed(["a"])
    pins.add("script/x.vns", {"c": (0, 60), "d": (0, 120)})
    assert set(pins.of(None)) == {"b"} and len(pins) == 3   # the removed box's pin went first


def test_f58_p2_stale_by_index_agrees_with_rebase():
    rng = random.Random(7)
    names = [f"s{i}" for i in range(8)]
    for _ in range(60):
        lines = []
        for name in names:
            lines += [f"label {name}:", f'    "{name} one."', f'    "{name} two."']
        text = "\n".join(lines)
        marks_now = {key: (first, digest) for key, first, _, digest in
                     edits._chunk_marks(text, text.split("\n"))}
        picks = rng.sample(names, 2)
        edit_list, touched, marks = [], [], []
        for name in sorted(picks, key=names.index):
            key = (name, 0)
            first = marks_now[key][0]
            edit_list.append(LineEdit(first + 1, first + 1, ('    "Changed."',)))
            touched.append((key,))
            marks.append((key, *marks_now[key]))
        file = ProposalFile(A, "0" * 64, FilePlan(A, (), tuple(edit_list)), False, False, 1, 1,
                            (), touched=tuple(touched), marks=tuple(marks))
        live = lines[:]
        what = rng.randrange(3)
        if what == 0:
            live.insert(0, "label intro:\n    pass")
        elif what == 1:
            live[rng.randrange(len(live))] += "  # touched"
        else:
            live.insert(rng.randrange(1, len(live)), "    pause 1")
        live_text = "\n".join(live)
        index = scenes.reindex(None, A, live_text, 1, checked=None)
        verdict = stale_by_index(file.touched, file.marks, index)
        assert verdict is not None
        assert verdict == (edits.rebase(file, live_text) is None)
