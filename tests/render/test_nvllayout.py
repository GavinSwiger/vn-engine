"""F17 ``render/nvllayout.py``: the metrics (``06-acceptance.md`` AC-F17-11) and the page fold
with its heights cache (AC-F17-12). M20 (F05 §0.6): 46 graphemes per 920-unit row at size 28,
30 at size 42; ``aN`` is one word of N ``a``s."""

import pytest

from engine.core.config_schema import NvlTheme, ThemeConfig
from engine.render import nvllayout
from engine.render.nvllayout import (HEIGHTS_CACHE_MAX, empty_plan, heights,
                                     heights_cache_info, line_context, nvl_look, nvl_metrics,
                                     plan_add, plan_from)
from engine.render.textlayout import BUNDLED_FACES
from engine.runtime.commands import BASE_STYLE, NvlLine, Span
from tests.fakes.fixed_font import FixedFontAssets


def look(**nvl):
    return nvl_look(ThemeConfig(nvl=NvlTheme(**nvl)))


# --- AC-F17-11 — metrics ------------------------------------------------------------------------

@pytest.mark.parametrize("theme, scale, expected", [
    ({}, 1.0, (180, 64, 920, 584, 28, 39, 20)),
    ({}, 1.5, (180, 64, 920, 584, 42, 59, 20)),
    ({"text_size": 34}, 1.3, (None, None, None, None, 44, 62, None)),
    ({"text_size": 48}, 1.5, (None, None, None, None, 48, 67, None)),
    ({"text_size": 20}, 1.0, (None, None, None, None, 20, 28, None)),
    ({"width": 640, "top_gap": 24, "bottom_gap": 40, "line_gap": 0}, 1.0,
     (320, 24, 640, 656, 28, 39, 0)),
])
def test_ac_f17_11_metrics(theme, scale, expected):
    m = nvl_metrics(look(**theme), scale)
    got = (m.left, m.top, m.width, m.height, m.size, m.pitch, m.gap)
    for value, want in zip(got, expected):
        if want is not None:
            assert value == want, (theme, scale, got)


# --- AC-F17-12 — the page fold ------------------------------------------------------------------

def _line(n: int, *, named: bool = False, key: int = 0) -> NvlLine:
    spans = (Span("a" * n, BASE_STYLE),) if n else ()
    return NvlLine(f"s/{key}", "Hana" if named else "", None, spans)


def _fold(lines, *, scale: float = 1.0, **theme):
    """``plan_add`` folded over ``lines``, returning every plan along the way."""
    nvl_look_ = look(**theme)
    m = nvl_metrics(nvl_look_, scale)
    assets = FixedFontAssets()
    plans, plan = [], empty_plan(m)
    for i, line in enumerate(lines):
        ctx = line_context(assets, BUNDLED_FACES, nvl_look_, m, bool(line.name))
        plan = plan_add(plan, i, heights(line, m, ctx), bool(line.name), m)
        plans.append(plan)
    folded = plan_from(lines, m, lambda line: line_context(assets, BUNDLED_FACES, nvl_look_, m,
                                                           bool(line.name)))
    assert folded == plans[-1]                              # plan_from is the same fold
    return plans


def _rows(plan) -> list[tuple]:
    return [(r.entry, r.page, r.y) for r in plan.rows]


def test_ac_f17_12_page_fold():
    a10 = _line(10)
    # A: ten one-row lines; B: an eleventh restarts.
    plans = _fold([a10] * 11)
    assert _rows(plans[9]) == [(k, 0, 64 + 59 * k) for k in range(10)] and plans[9].used == 570
    assert _rows(plans[10]) == [(10, 0, 64)] and plans[10].used == 39
    # C: a named line takes a name row.
    plans = _fold([a10, _line(10, named=True)])
    assert _rows(plans[1]) == [(0, 0, 64), (1, 0, 123)] and plans[1].used == 137
    # D: a600 (14 rows) fills one page; a10 after it restarts.
    plans = _fold([_line(600), a10])
    assert _rows(plans[0]) == [(0, 0, 64)] and plans[0].used == 546
    assert _rows(plans[1]) == [(1, 0, 64)] and plans[1].used == 39
    # E: a named a600 needs two pages (13 + 1); a10 goes under its last part.
    plans = _fold([_line(600, named=True), a10])
    assert _rows(plans[0]) == [(0, -1, 64)] and plans[0].used == 78
    assert _rows(plans[1]) == [(0, -1, 64), (1, 0, 162)] and plans[1].used == 137
    # F: a690 (15 rows, 2 pages) starts a page alone.
    plans = _fold([a10, _line(690), a10])
    assert _rows(plans[1]) == [(1, -1, 64)] and plans[1].used == 39
    assert _rows(plans[2]) == [(1, -1, 64), (2, 0, 123)] and plans[2].used == 98
    # G: an empty line takes one row.
    plans = _fold([_line(0), a10])
    assert _rows(plans[1]) == [(0, 0, 64), (1, 0, 123)] and plans[1].used == 98
    # H: an exact fit at line_gap 38; one unit more restarts.
    plans = _fold([a10, _line(598)], line_gap=38)
    assert _rows(plans[1]) == [(0, 0, 64), (1, 0, 141)] and plans[1].used == 584
    plans = _fold([a10, _line(598)], line_gap=39)
    assert _rows(plans[1]) == [(1, 0, 64)] and plans[1].used == 507
    # I: size 42 holds 7 one-row lines.
    plans = _fold([a10] * 8, scale=1.5)
    assert _rows(plans[6]) == [(k, 0, 64 + 79 * k) for k in range(7)]
    assert _rows(plans[6])[-1][2] == 538 and _rows(plans[7]) == [(7, 0, 64)]
    # J: size 20, no gap, the area 24..680 holds 23 rows.
    plans = _fold([a10] * 24, text_size=20, line_gap=0, top_gap=24, bottom_gap=40)
    assert _rows(plans[22]) == [(k, 0, 24 + 28 * k) for k in range(23)]
    assert _rows(plans[23]) == [(23, 0, 24)]


def test_ac_f17_12_heights_cache():
    nvllayout.clear_heights()
    nvl_look_ = look()
    m28, m42 = nvl_metrics(nvl_look_, 1.0), nvl_metrics(nvl_look_, 1.5)
    assets = FixedFontAssets()
    ctx28 = line_context(assets, BUNDLED_FACES, nvl_look_, m28, False)
    ctx42 = line_context(assets, BUNDLED_FACES, nvl_look_, m42, False)
    one, two = _line(10, key=1), _line(10, key=1)            # equal, built separately
    assert one == two and one is not two
    first = heights(one, m28, ctx28)
    assert heights(two, m28, ctx28) is first                # a cache hit
    assert heights_cache_info() == (1, 1, 1)
    heights(one, m42, ctx42)                                # another size computes again
    assert heights_cache_info()[2] == 2
    for k in range(2_000):
        heights(_line(5, key=k + 10), m28, ctx28)
    assert heights_cache_info()[0] <= HEIGHTS_CACHE_MAX
    nvllayout.clear_heights()


# --- AC-F17-13 — live and restored pages agree (Step 2: the presenter) -------------------------

def _corpus_says(tmp_path, lines: int = 200) -> list:
    """Every ``Say`` of the example game and of F05's corpus (seed 1, ``lines`` lines)."""
    from engine.runtime.commands import Say
    from tests.fixtures.F05.gen_text_corpus import write_game as write_corpus
    from tests.runtime.corpus import play
    from tests.runtime.stage_story import load_game
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    says = []
    for root in (repo / "game", write_corpus(tmp_path / "corpus", seed=1, lines=lines)):
        says += [c for c in play(load_game(root), 1).commands if type(c) is Say]
    return says


def _gen_script(seed: int) -> str:
    """A seeded NVL script (≤ 40 lines of 0–700 graphemes, named and unnamed, empty lines,
    ``nvl clear``, menus of 1–6 choices with or without a question)."""
    import random
    rng = random.Random(seed)
    out = ['define hana = Character("Hana", color="#A02860")', "default picked = 0",
           "label start:", "    nvl on"]

    def text() -> str:
        size = rng.choice((0, rng.randrange(1, 60), rng.randrange(60, 300),
                           rng.randrange(300, 701)))
        words, total = [], 0
        while total < size:
            word = "a" * min(size - total, rng.randrange(1, 12))
            words.append(word)
            total += len(word) + 1
        return (" " if rng.random() < 0.9 else "\\n").join(words)

    for _ in range(rng.randrange(5, 41)):
        roll = rng.random()
        if roll < 0.08:
            out.append("    nvl clear")
        elif roll < 0.16:
            out.append("    menu:")
            if rng.random() < 0.6:
                out.append(f'        hana "{text() or "Well?"}"')
            for k in range(rng.randrange(1, 7)):
                out += [f'        "Choice {k}":', f"            $ picked = {k}"]
        else:
            who = "hana " if rng.random() < 0.4 else ""
            out.append(f'    {who}"{text()}"')
    return "\n".join(out) + "\n"


def _presenter():
    from engine.ui.builtin.nvl_page import NvlPresenter
    return NvlPresenter(FixedFontAssets(), BUNDLED_FACES, look())


def _feed(presenter, commands, m) -> int:
    """Send ``commands``' ``NvlPage``s and ``Say``s to ``presenter``; the Says since its last
    page reset (live: the count that decides the 32-line exception)."""
    from engine.runtime.commands import NvlPage, Say
    count = 0
    for c in commands:
        if type(c) is NvlPage:
            presenter.set(c.on, c.lines, m)
            count = 0
        elif type(c) is Say and presenter.on:
            presenter.arrive(c, m)
            count += 1
    return count


def _shown(presenter) -> list[tuple]:
    return [(presenter.entries[r.entry].sid, r.page, r.y) for r in presenter.rows()]


# The default tier runs a smaller case (5.3 s → about 1 s); the AC's 200 corpus lines and
# 200 generated scripts run nightly (``slow``).
@pytest.mark.parametrize("corpus_lines, scripts", [
    (40, 25), pytest.param(200, 200, marks=pytest.mark.slow)], ids=["small", "ac-size"])
def test_ac_f17_13_live_and_restored_pages_agree(tmp_path, corpus_lines, scripts):
    from engine.render.textlayout import LineLayout
    from engine.runtime.commands import TaggedText
    from engine.runtime.interpreter import Status
    from engine.runtime.nvl import line_of
    from engine.script.menu import Menu
    from tests.runtime.menu_story import ALL, launched, load_text, step

    # (a) Typing body and record spans break alike (TR-F17-02).
    assets = FixedFontAssets()
    says = _corpus_says(tmp_path, corpus_lines)
    assert len(says) > corpus_lines
    for size in (20, 28, 42, 48):
        nvl_look_ = look(text_size=size)
        m = nvl_metrics(nvl_look_, 1.0)
        for say in says:
            ctx = line_context(assets, BUNDLED_FACES, nvl_look_, m, bool(say.name))
            live = LineLayout(say.body, ctx)
            kept = LineLayout(TaggedText(line_of(say).spans), ctx)
            n = live.all_pages()
            assert kept.all_pages() == n, (size, say.text[:40])
            assert [live.page_height(k) for k in range(n)] == \
                [kept.page_height(k) for k in range(n)], (size, say.text[:40])

    # (b) Live rows equal restored rows at every checkpoint (TR-F17-03), seeded scripts.
    m = nvl_metrics(look(), 1.0)
    for seed in range(scripts):
        program = load_text(tmp_path / f"g{seed}", _gen_script(seed)).program
        assert program is not None, seed
        interp, again = launched(program), launched(program)
        live = _presenter()
        interp.new_game(seed)
        interp.run(10_000)
        since = _feed(live, interp.take_commands(ALL), m)
        while interp.status is Status.WAITING:
            if since <= 32:
                restored = _presenter()
                again.restore(interp.checkpoint())
                again.run(10_000)
                _feed(restored, again.take_commands(ALL), m)
                assert _shown(restored) == _shown(live), seed
            step(interp, "choose 1" if type(interp.current) is Menu else None)
            interp.run(10_000)
            burst = interp.take_commands(ALL)
            since = _feed(live, burst, m) + (0 if any(
                type(c).__name__ == "NvlPage" for c in burst) else since)

    # (c) The exception, pinned: 40 one-row lines, restored at the 40th.
    script = "label start:\n    nvl on\n" + "".join(f'    "L{k}"\n' for k in range(1, 41))
    program = load_text(tmp_path / "forty", script).program
    interp = launched(program)
    live = _presenter()
    interp.new_game(1)
    interp.run(10_000)
    _feed(live, interp.take_commands(ALL), m)
    for _ in range(39):
        step(interp, None)
        interp.run(10_000)
        _feed(live, interp.take_commands(ALL), m)
    texts = lambda p: [p.entries[r.entry].spans[0].text for r in p.rows()]   # noqa: E731
    assert texts(live) == [f"L{k}" for k in range(31, 41)]
    restored = _presenter()
    again = launched(program)
    again.restore(interp.checkpoint())
    again.run(10_000)
    _feed(restored, again.take_commands(ALL), m)
    assert texts(restored) == ["L39", "L40"]
    assert [r.y for r in restored.rows()] == [64, 123]
