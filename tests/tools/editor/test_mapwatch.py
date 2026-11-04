"""F58 P3: the background watch and the scene-index helpers for closed files (``01-design.md``
AC-F58-06, 07, 08, 34; ``04-technical.md`` §7.1, §7.3; ``07`` I-1 to I-3). No Tk."""

import ast
import os
import time
from pathlib import Path

from engine.core import safefile
from engine.script.diagnostics import ScriptError
from engine.tools.editor import livemap, mapwatch, scenes
from engine.tools.editor.document import ScriptDocument
from engine.tools.editor.livemap import IndexBudget, MapModel, Pins, preview_rows
from engine.tools.editor.mapwatch import (
    CAPPED, CHANGED, CHECK_ONLY, REMOVED, UNREADABLE, ScriptWatch, scan)
from tests.tools.editor.conftest import link_dir, link_file
from tests.tools.editor.live_fakes import FakeClock, count_calls

EDITOR = Path(__file__).resolve().parents[3] / "engine" / "tools" / "editor"


def _game(tmp_path: Path, files: dict[str, str]) -> Path:
    for ref, text in files.items():
        path = tmp_path / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    return tmp_path


def _doc(text: str) -> ScriptDocument:
    return ScriptDocument("script/x.vns", Path("x"), False, "\n", True, None, None, (1, 1),
                          Path("."), text=text)


def test_ac_f58_06_scandir_listing_skips_links_and_reads_only_changed_files(tmp_path,
                                                                             monkeypatch):
    game = _game(tmp_path, {"script/main.vns": "label start:\n    pass\n",
                            "script/ch/a.vns": "label a:\n    pass\n",
                            "script/notes.txt": "x", "script/.a.vns.1234.tmp": "x"})
    outside = _game(tmp_path / "out", {"far.vns": "label far:\n    pass\n"})
    link_dir(game / "script" / "linked", outside)
    stats = count_calls(monkeypatch, os, "stat")
    listed = scan(game)
    assert stats.n == 0                                 # no stat beyond DirEntry.stat()
    assert list(listed) == ["script/main.vns", "script/ch/a.vns"]
    try:
        link_file(game / "script" / "l.vns", outside / "far.vns")
        assert "script/l.vns" not in scan(game)
    except BaseException as exc:                        # file links not permitted: fine
        if type(exc).__name__ != "Skipped":
            raise
    watch = ScriptWatch(game)
    reads = count_calls(monkeypatch, watch, "_reader")
    watch.tick()
    assert reads.n == 2 and set(watch.mailbox.take()) == set(listed)
    watch.tick()
    assert reads.n == 2 and not watch.mailbox.take()    # nothing changed: nothing read
    (game / "script" / "ch" / "a.vns").write_bytes(b"label a:\n    jump start\n")
    os.utime(game / "script" / "ch" / "a.vns", ns=(1, 10**18))
    watch.tick()
    assert reads.n == 3 and reads.args[-1] == ("script/ch/a.vns",)
    news = watch.mailbox.take()["script/ch/a.vns"]
    assert news.kind == CHANGED and news.text == "label a:\n    jump start" and news.doc is None
    # PR-24 (fake clock): a listing over 200 ms backs the watch off to 2 s until fast again.
    clock = FakeClock()
    took = [300]

    def slow(root):
        clock.advance(took[0])
        return {}

    slowpoke = ScriptWatch(game, lister=slow, clock=lambda: clock.now() / 1000)
    slowpoke.tick()
    assert slowpoke.interval == mapwatch.SLOW_WATCH_MS
    took[0] = 5
    slowpoke.tick()
    assert slowpoke.interval == mapwatch.WATCH_MS


def test_ac_f58_07_moved_during_the_read_or_undecodable_is_read_next_tick(tmp_path):
    game = _game(tmp_path, {"script/a.vns": "label a:\n"})
    stamps = iter([(1, 9), (2, 9), (2, 9), (2, 9)])     # before/after per read: moved, then not
    outcomes = iter([_doc("one"), _doc("two")])
    watch = ScriptWatch(game, lister=lambda root: {"script/a.vns": (5, 9)},
                        stat=lambda path: next(stamps), reader=lambda ref: next(outcomes))
    watch.tick()
    assert not watch.mailbox.take() and "script/a.vns" not in watch.seen
    watch.tick()
    news = watch.mailbox.take()["script/a.vns"]
    assert news.text == "two" and news.stamp == (2, 9)  # the os.stat after the read (I-2)

    # Bytes that don't decode: retried each tick, posted unreadable after READ_TRIES.
    bad = ScriptWatch(game, lister=lambda root: {"script/a.vns": (5, 9)},
                      stat=lambda path: (7, 9),
                      reader=lambda ref: ScriptError("bad bytes", code="E01a"))
    for _ in range(mapwatch.READ_TRIES - 1):
        bad.tick()
        assert not bad.mailbox.take()
    bad.tick()
    assert bad.mailbox.take()["script/a.vns"].kind == UNREADABLE
    bad.tick()
    assert not bad.mailbox.take()                       # not again at the same stamp

    # I-2: directory-entry stamps that never equal os.stat's cause no read loop.
    reads = []
    lagging = ScriptWatch(game, lister=lambda root: {"script/a.vns": (100, 9)},
                          stat=lambda path: (200, 9),
                          reader=lambda ref: reads.append(ref) or _doc("x"))
    for _ in range(4):
        lagging.tick()
    assert reads == ["script/a.vns"]


def test_ac_f58_08_an_outside_edit_parses_exactly_its_chunk(tmp_path, monkeypatch):
    scenes_text = "".join(f"label s{i}:\n    \"Scene {i}.\"\n    jump s{(i + 1) % 20}\n"
                          for i in range(20))
    game = _game(tmp_path, {"script/main.vns": scenes_text})
    watch = ScriptWatch(game)
    watch.tick()
    text = watch.mailbox.take()["script/main.vns"].text
    index = scenes.slim(scenes.reindex(None, "script/main.vns", text, 0, checked=None))
    model = MapModel()
    model.set_file("script/main.vns", livemap.rows_from_index(index, {
        f"s{i}": [(f"s{i}", f"s{(i + 1) % 20}", "jump", None, False)] for i in range(20)}))
    edited = scenes_text.replace("    jump s8\n", "    jump s8\n    jump s15\n")
    safefile.write_atomic(game / "script" / "main.vns", [edited.encode()])
    watch.tick()
    news = watch.mailbox.take()["script/main.vns"]
    parsed = count_calls(monkeypatch, scenes, "parse_chunk")
    new = scenes.reindex(index, "script/main.vns", news.text, 1, checked=index.checked)
    assert parsed.n == 1 and parsed.args[0][1].startswith("label s7:")
    check = model.check_links("script/main.vns")
    model.set_file("script/main.vns", livemap.rows_from_index(new, check))
    assert ("s7", "s15", "jump", None, False) in model.files["script/main.vns"].edges


def test_ac_f58_34_caps(tmp_path):
    game = _game(tmp_path, {"script/a.vns": "label a:\n"})
    big = 16 * 1024 * 1024 + 1
    listed = {"script/huge.vns": (1, big), **{f"script/f{i}.vns": (1, 10) for i in range(2001)}}
    reads = []
    watch = ScriptWatch(game, lister=lambda root: listed, stat=lambda path: (1, 10),
                        reader=lambda ref: reads.append(ref) or _doc("x"))
    watch.tick()
    news = watch.mailbox.take()
    assert news["script/huge.vns"].kind == CAPPED and "script/huge.vns" not in reads
    capped = [ref for ref, item in news.items() if item.kind == CAPPED]
    assert len(capped) == 2 and len(reads) == 2000      # past 2,000 files: capped (S6)
    budget = IndexBudget()
    assert all(budget.admit(f"f{i}", 15 * 2**20) for i in range(4))     # 60 MiB
    assert not budget.admit("f4", 15 * 2**20)           # past 64 MiB in all
    assert budget.line == livemap.S6
    # A big file with mixed line endings isn't decoded by the watch (the check covers it).
    mixed = _game(tmp_path / "m", {"script/m.vns": "a\r\n" * 300_000 + "b\n" * 300_000})
    watch = ScriptWatch(mixed)
    watch.tick()
    assert watch.mailbox.take()["script/m.vns"].kind == CHECK_ONLY
    # Closed files keep links and digests, no statements; a check's digests drop the reads.
    text = "label a:\n    jump b\nlabel b:\n    \"B.\"\n"
    index = scenes.reindex(None, "script/a.vns", text, 0, checked={})
    assert index.reads[("a", 0)].statements
    thin = scenes.slim(index)
    assert not thin.reads[("a", 0)].statements and thin.reads[("a", 0)].links
    caught = scenes.drop_checked_reads(thin, thin.digests)
    assert not caught.reads and caught.checked == thin.digests
    assert scenes.changed_lines(text.replace("B.", "C."), thin.digests) == 2
    pins = Pins()
    pins.add(None, {f"n{i}": (0, 20 * i) for i in range(10_005)})
    assert len(pins) == livemap.PIN_CAP == 10_000
    model = MapModel()
    many = livemap.FileRows(tuple((f"n{i}", i) for i in range(300)), ())
    assert len(preview_rows(model, {"script/a.vns": many}).boxes_added) == livemap.PREVIEW_CAP


def test_f58_p3_the_thread_posts_news_and_stops_without_waiting(tmp_path):
    game = _game(tmp_path, {"script/a.vns": "label a:\n"})
    watch = ScriptWatch(game)
    watch.baseline(scan(game))
    watch.set_open({"script/a.vns"})
    watch.start()
    try:
        safefile.write_atomic(game / "script" / "a.vns", [b"label a:\n    jump b\n"])
        safefile.write_atomic(game / "script" / "b.vns", [b"label b:\n"])
        end = time.monotonic() + 5
        got: dict = {}
        while time.monotonic() < end and len(got) < 2:
            got.update(watch.mailbox.take())
            time.sleep(0.02)
        assert got["script/a.vns"].doc is not None      # open: the decoded document
        assert got["script/b.vns"].text == "label b:"   # closed: the text only
        os.remove(game / "script" / "b.vns")
        end = time.monotonic() + 5
        while time.monotonic() < end and "script/b.vns" not in (got := watch.mailbox.take()):
            time.sleep(0.02)
        assert got["script/b.vns"].kind == REMOVED
    finally:
        start = time.perf_counter()
        watch.stop()
        assert time.perf_counter() - start < 0.05      # never joins
    end = time.monotonic() + 3
    while watch.alive and time.monotonic() < end:
        time.sleep(0.02)
    assert not watch.alive and watch.failed is None


def test_f58_p3_watch_and_model_modules_are_tk_free():
    for name in ("mapwatch", "livemap"):
        tree = ast.parse((EDITOR / f"{name}.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom)}
        assert "tkinter" not in imported, name
        source = (EDITOR / f"{name}.py").read_text(encoding="utf-8")
        assert ".write_" not in source and "write_atomic" not in source, name
