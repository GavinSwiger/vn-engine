"""The check child's work, in process (F45 ``04`` §4.3, §7.1; ``07`` I-1): ``CheckJob`` on
fixture game S, ``NAME_SOURCES``, and the chunked report lines. AC-F45-06, AC-F45-07,
AC-F45-08 (the full-size rows are ``slow``), TR-F45-03, TR-F45-07 (sources half)."""

import shutil

import pytest

from engine.core import editorreport
from engine.core.editorreport import CHECK_EVENT_MAX_ITEMS, REPORT_MAX_BYTES, REPORT_TEXT_MAX_CHARS
from engine.core.paths import GamePaths
from engine.script.effects import BUILTIN_TRANSITION_NAMES
from engine.script.statement_docs import NAME_KIND_RE, all_docs
from engine.tools import check
from engine.tools.check import NAME_SOURCES, emit_results, encode_event, problem_item
from engine.tools.editor import checker
from engine.tools.editor.checker import CheckItem, LabelLink, NameEntry
from tests.tools.f45_games import check as run_check
from tests.tools.f45_games import edit_line, result_of, run_job, studio

S_LINKS = (LabelLink("start", "club", "call", "script/main.vns", 7),
           LabelLink("start", "bridge", "jump", "script/main.vns", 8),
           # F46 (A-F45-04): the menu link carries its choice's text.
           LabelLink("club", "river", "menu", "script/ch2.vns", 4, "Go to the river", False))
SOURCES = ["config", "load", "launch"]


# --- AC-F45-06: problems, in engine order ----------------------------------------------------

def _config_error(game):
    (game / "config.toml").write_bytes(b'[game]\ntitle = 5\n')
    edit_line(game / "script" / "main.vns", 5, "    show hana sad")


def _unknown_key(game):
    (game / "config.toml").write_bytes(b'[game]\ntitle = "My Game"\ntitel = "x"\n')


def _todo(game):
    ch2 = game / "script" / "ch2.vns"
    ch2.write_bytes(b"# TODO tidy\n" + ch2.read_bytes())


def _sixty(game):
    (game / "script" / "bad.vns").write_bytes(("label bad:\n" + "    jmup x\n" * 60).encode())
    main = game / "script" / "main.vns"
    main.write_bytes(main.read_bytes() + b'include "bad.vns"\n')


ROWS = [
    # (change, launch, expected item rows (severity, code, source, file, line) or a count,
    #  loaded, problem total)
    (lambda game: None, True, [], True, 0),
    (_config_error, True, [("error", "", "config", "config.toml", 2),
                           ("warning", "W12", "launch", "script/main.vns", 5)], True, 2),
    (_unknown_key, True, [("warning", "", "config", "config.toml", 3)], True, 1),
    (lambda game: edit_line(game / "script" / "ch2.vns", 9, "    jump bridg"), True,
     [("error", "E43", "load", "script/ch2.vns", 9)], False, 1),
    (_todo, True, [("info", "TODO", "load", "script/ch2.vns", 1)], True, 1),
    (lambda game: edit_line(game / "script" / "main.vns", 5, "    show hana sad"), True,
     [("warning", "W12", "launch", "script/main.vns", 5)], True, 1),
    (_sixty, True, 50, False, 60),
    (shutil.rmtree, True, [("error", "", "load", None, None)], False, 1),
    # 07 I-1: --no-launch runs no define (this one would be a launch error).
    (lambda game: edit_line(game / "script" / "main.vns", 3, "define boom = 1 / 0"), False,
     [], True, 0),
]


def test_ac_f45_06_problems_in_engine_order(tmp_path):
    for n, (change, launch, items, loaded, total) in enumerate(ROWS):
        game = studio(tmp_path, f"g{n}")
        paths = GamePaths.for_game(game)
        change(game)
        events = run_job(paths, launch=launch)
        order = [e["event"] for e in events]
        assert order == sorted(order, key=["problems", "names", "graph", "done"].index), n
        assert order.count("done") == 1 and order[-1] == "done"
        assert ("graph" in order) == loaded, n
        result = result_of(events)
        rows = [(i.severity, i.code, i.source, i.file, i.line) for i in result.problems]
        if isinstance(items, int):
            assert len(rows) == items, n
        else:
            assert rows == items, n
        assert [r[2] for r in rows] == sorted((r[2] for r in rows), key=SOURCES.index), n
        assert (result.loaded, result.problem_total) == (loaded, total), n
        if not loaded:
            assert result.links is None
        if n == 3:
            text = result.problems[0].text
            assert '"bridg"' in text and 'Did you mean "bridge"' in text
            # Kinds that need no script: config, files, and minigame plugins (2026-11-02),
            # F28's effect kind words, and F32's ui words and style names (off at least).
            assert set(result.names) == {"audio", "position", "transition", "minigame",
                                         "minigame_arg", "glitch", "ui", "style"}
        if n == 7:
            assert "Can't find the game folder" in result.problems[0].text
        if not launch:
            assert "character" not in result.names and result.links == S_LINKS


# --- AC-F45-07: names and graph ---------------------------------------------------------------

def test_ac_f45_07_names_and_graph(tmp_path):
    game = studio(tmp_path)
    result = run_check(game)
    names = dict(result.names)
    assert names["label"] == (
        NameEntry("start", "script/main.vns", 4), NameEntry("club", "script/ch2.vns", 1),
        NameEntry("bridge", "script/ch2.vns", 8), NameEntry("river", "script/ch2.vns", 10),
        NameEntry("side", "script/ch2.vns", 12))
    # images/bg/sky.gif isn't an image the engine shows (IMAGE_SUFFIXES has no .gif), and
    # ``black`` is built in (SR-F04-05): the engine's own index, as F04 builds it.
    assert {e.name for e in names["image"]} == {"hana happy", "bg room", "bg photo", "black"}
    assert names["character"] == (NameEntry("hana", "script/main.vns", 2),)
    assert {e.name for e in names["transition"]} >= set(BUILTIN_TRANSITION_NAMES)
    assert [e.name for e in names["position"]] == ["left", "center", "right"]
    assert [e.name for e in names["audio"]] == ["bgm/theme.ogg"]
    assert result.links == S_LINKS

    def broken(context):
        raise RuntimeError("boom")

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(NAME_SOURCES, "image", broken)
        partial = run_check(game)
    # A kind with no rows isn't sent (the fixture has no tips, endings, …; 2026-11-02).
    assert set(partial.names) == set(result.names) - {"image"}
    assert {k for k, n in result.name_totals.items() if n} == set(result.names)
    assert partial.problems == ()

    listed = {kind for doc in all_docs() for kind in doc.names}
    assert listed and listed <= set(NAME_SOURCES)
    assert editorreport.CHECK_KIND_RE == NAME_KIND_RE.pattern


# --- AC-F45-08: chunked reports round-trip ----------------------------------------------------

def problems_of(n: int, text: str | None = None) -> list[dict]:
    return [problem_item("error", "E43", "load", text or f"p{i}", "script/main.vns", i + 1, 1)
            for i in range(n)]


def round_trip(problems, total, names=None, program=None, max_bytes=REPORT_MAX_BYTES):
    events: list[dict] = []
    emit_results(events.append, problems, total, names or {}, program, 0.1)
    for event in events:
        assert len(encode_event(event)) <= max_bytes
        assert len(event.get("items", event.get("links", ()))) <= CHECK_EVENT_MAX_ITEMS
    sizes = [len(e["items"]) for e in events if e["event"] == "problems"]
    return sizes, result_of(events)


def test_ac_f45_08_chunked_reports_round_trip(tmp_path):
    many, japanese, eleven = problems_of(5_001), problems_of(3, "日" * 10_000), \
        problems_of(11)
    assert len(japanese[0]["text"]) == REPORT_TEXT_MAX_CHARS
    with pytest.MonkeyPatch.context() as mp:
        for module in (check, checker):
            mp.setattr(module, "CHECK_MAX_PROBLEMS", 6_000)
        sizes, result = round_trip(many, 5_001)
    assert sizes == [5_000, 1]
    assert result.problems == tuple(CheckItem(**p) for p in many)
    with pytest.MonkeyPatch.context() as mp:                # split by bytes, not count
        mp.setattr(check, "REPORT_MAX_BYTES", 150_000)
        sizes, result = round_trip(japanese, 3, max_bytes=150_000)
    assert sizes == [2, 1]
    assert result.problems == tuple(CheckItem(**p) for p in japanese)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(check, "CHECK_MAX_PROBLEMS", 10)
        sizes, result = round_trip(eleven, 11)
    assert result.problems == tuple(CheckItem(**p) for p in eleven[:10])
    assert result.problem_total == 11
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(check, "CHECK_MAX_NAMES", 2)
        mp.setattr(check, "CHECK_MAX_LINKS", 2)
        result = run_check(studio(tmp_path))
    assert len(result.names["label"]) == 2 and result.name_totals["label"] == 5
    assert result.links == S_LINKS[:2] and result.link_total == 3


@pytest.mark.slow
def test_ac_f45_08_the_real_totals_round_trip():
    problems = problems_of(1_000)
    names = {kind: [(f"name {kind} {i}", "script/main.vns", i + 1) for i in range(20_000)]
             for kind in ("label", "image", "audio")}
    _, result = round_trip(problems, 1_000, names)
    assert result.problems == tuple(CheckItem(**p) for p in problems)
    for kind, rows in names.items():
        assert result.names[kind] == tuple(NameEntry(*row) for row in rows)
