"""F17 step 2 — NVL on screen in App A (``06-acceptance.md`` §0.3): layout never changes the
story (AC-F17-10), the mode switch (14), layout (15), lines as in the textbox (16), lines
longer than a page (17), the restored page (18), input and hide (19), the quick menu and
overlays (20), the in-game reset (21), text size (22), hostile content (32), no viewport
surface (33's rest; the import scan is in ``tests/test_import_rules.py``), the cost guard
(34), and F14 A4's NVL branch of ``cue_anchor``/``set_bump``.

Every run is a real ``App`` loop (``tests/fakes/text_app.py``) on Template N
(``tests/fixtures/F17/template/``) with a red ``images/red.png``, so probe P = (640, 30) is red
without a panel and (255, 207, 211) under it. Restores go through ``driver.restore`` (F03): a
rollback is an earlier checkpoint, a load its JSON round trip with the caches cleared.
"""

import json
import statistics
import time
from pathlib import Path

import pygame
import pytest

from engine.render import nvl as nvl_module
from engine.render.nvl import NvlView
from engine.render.nvllayout import clear_heights, heights_cache_info, nvl_look, nvl_metrics
from engine.render.textbox import TextboxView
from engine.render.textlayout import BUNDLED_FACES, render_safe
from engine.render.typewriter import TypeState
from engine.runtime.commands import Advance, NvlLine, Say, Span, Style
from engine.runtime.nvl import EMPTY_NVL
from engine.runtime.state import GameState, StateInvalid
from engine.ui.builtin import nvl_page, textbox_screen
from engine.ui.builtin.nvl_page import NvlPresenter
from engine.ui.builtin.quick_menu import QuickMenu
from tests.fakes.fixed_font import FixedFontAssets
from tests.fakes.text_app import Session, make_text_game
from tests.script.helpers import template_n

pytestmark = pytest.mark.display

CPS0 = "[textbox]\ncps = 0\n"
CPS40 = "[textbox]\ncps = 40\n"
RED = (255, 0, 0)
PANEL = (255, 207, 211)
P = (640, 30)
# Template N's lines by arrival (06 §0.4, Run N full).
L6, L8, L9, L10, L12, L14, L15, L21, L23 = range(9)


def game(tmp_path: Path, *, config: str = CPS0, name: str = "g", script: str | None = None,
         **edit) -> Path:
    root = make_text_game(tmp_path / name, script=script or template_n(**edit), config=config)
    images = root / "images"
    images.mkdir(exist_ok=True)
    red = pygame.Surface((1280, 720))
    red.fill(RED)
    pygame.image.save(red, str(images / "red.png"))
    return root


def rows(s: Session) -> list[tuple]:
    nvl = s.textbox.nvl
    return [(nvl.entries[r.entry].sid, r.page, r.y) for r in nvl.rows()]


def ys(s: Session) -> list[float]:
    return [r.y for r in s.textbox.nvl.rows()]


def complete(s: Session) -> bool:
    tb = s.textbox
    return tb is not None and tb.line is not None and tb.typer is not None \
        and tb.typer.state is TypeState.COMPLETE


def to_line(s: Session, index: int):
    """Advance (Space; at a menu, Space until a choice is picked) until arrival ``index``
    (0-based) has come; ends in the step right after its arrival frame."""
    while len(s.said) <= index:
        count = len(s.said)
        yield from s.until(lambda: complete(s) or len(s.said) > count)
        if len(s.said) > count:
            continue
        if s.textbox.menu_waiting:
            for _ in range(60):
                if len(s.said) > count:
                    break
                s.key(pygame.K_SPACE)
                for _ in range(8):
                    yield
            continue
        s.key(pygame.K_SPACE)
        yield
        yield from s.until(lambda: len(s.said) > count)


def spy_draws(monkeypatch, s: Session) -> list[tuple[int, str]]:
    """(frame, "nvl" | "adv") for every ``NvlView.draw`` and ``TextboxView.draw_box``."""
    calls: list[tuple[int, str]] = []
    real_nvl, real_box = NvlView.draw, TextboxView.draw_box

    def nvl_draw(self, *a, **k):
        calls.append((s.frame, "nvl"))
        real_nvl(self, *a, **k)

    def box_draw(self, *a, **k):
        calls.append((s.frame, "adv"))
        real_box(self, *a, **k)

    monkeypatch.setattr(NvlView, "draw", nvl_draw)
    monkeypatch.setattr(TextboxView, "draw_box", box_draw)
    return calls


def text_calls(monkeypatch, s: Session) -> list[tuple[str, tuple]]:
    """(text, color) of every ``AssetManager.text_line`` call."""
    calls: list[tuple[str, tuple]] = []
    real = s.assets.text_line

    def text_line(font, text, color):
        calls.append((text, tuple(color)))
        return real(font, text, color)

    monkeypatch.setattr(s.assets, "text_line", text_line)
    return calls


def settled_texts(s: Session) -> list[str]:
    """The record text of every settled row (each entry's spans joined)."""
    nvl = s.textbox.nvl
    return ["".join(span.text for span in nvl.entries[r.entry].spans)
            for r in nvl.rows() if r.entry != nvl.current]


# --- AC-F17-10 — layout never changes the story ------------------------------------------------

def test_ac_f17_10_layout_never_changes_the_story(tmp_path):
    from tests.runtime.nvl_story import bursts, load_n

    def story_json(state: GameState) -> dict:
        out = state.to_json()
        for key in ("dice", "rollback"):          # the seed and F14's window, not the story
            out.pop(key)
        return out

    _, _, states = bursts(load_n(tmp_path / "headless"))
    headless = [story_json(state) for state in states]
    for name, config in (("s28", CPS0), ("s42", CPS0 + "[theme.textbox]\ntext_size = 42\n"),
                         ("w640", CPS0 + "[theme.nvl]\nwidth = 640\n")):
        s = Session(game(tmp_path, name=name, config=config))
        seen: list[dict] = []

        def script(s):
            for index in range(L23 + 1):
                yield from to_line(s, index)
                seen.append(story_json(s.app.story.checkpoint()))

        s.play(script)
        assert seen == headless, name


# --- AC-F17-14 — mode switch frames -------------------------------------------------------------

def test_ac_f17_14_mode_switch_frames(tmp_path, monkeypatch):
    s = Session(game(tmp_path))
    draws = spy_draws(monkeypatch, s)
    seen = {}

    def script(s):
        for index in (L6, L8, L12, L23):
            yield from to_line(s, index)
            frame = s.said[index][0]
            seen[index] = ([kind for f, kind in draws if f == frame], s.px(*P),
                           s.textbox.nvl_on, rows(s), settled_texts(s))

    s.play(script)
    frames: dict[int, list[str]] = {}
    for frame, kind in draws:
        frames.setdefault(frame, []).append(kind)
    assert all(kinds in (["nvl"], ["adv"]) for kinds in frames.values())     # never both
    assert seen[L6][:3] == (["adv"], RED, False)
    kinds, color, on, page, settled = seen[L8]
    assert (kinds, color, on, settled) == (["nvl"], PANEL, True, [])       # Before. gone
    assert [y for _, _, y in page] == [64]
    kinds, color, on, page, settled = seen[L12]
    assert (kinds, on, settled) == (["nvl"], True, [])                     # L8–L10 gone
    assert [(p, y) for _, p, y in page] == [(0, 64)]
    assert seen[L23][:3] == (["adv"], RED, False)


# --- AC-F17-15 — layout on screen ---------------------------------------------------------------

def test_ac_f17_15_layout_on_screen(tmp_path, monkeypatch):
    areas: list[tuple] = []
    real_build, real_draw = TextboxView.build_glyphs, TextboxView.draw_glyphs

    def build(self, canvas, page, geometry, raster_scale):
        draw = real_build(self, canvas, page, geometry, raster_scale)
        areas.append(("settled", geometry.area[:2], draw.entries))
        return draw

    def draw(self, canvas, page, line_id, shown, geometry, **fx):
        areas.append(("current", geometry.area[:2], None))
        real_draw(self, canvas, page, line_id, shown, geometry, **fx)

    monkeypatch.setattr(TextboxView, "build_glyphs", build)
    monkeypatch.setattr(TextboxView, "draw_glyphs", draw)
    w80 = "W" * 80
    runs = {"main": ({}, CPS0, (1280, 720)), "small": ({}, CPS0, (800, 450)),
            "names": ({"T": f'define kai = Character("Kai")⏎define w = Character("{w80}")',
                       "replace": {9: '    kai "Hi."', 10: '    w "Long."'}},
                      CPS0 + '[theme.nvl]\nname.text_color = "#205080"\n', (1280, 720))}
    got = {}
    for name, (edit, config, size) in runs.items():
        s = Session(game(tmp_path, name=name, config=config, **edit), size=size)
        texts = text_calls(monkeypatch, s)
        view = {}

        def script(s):
            yield from to_line(s, L10)
            yield from s.until(lambda: complete(s))
            del areas[:]
            del texts[:]
            s.textbox.nvl.version += 1            # one settled rebuild to watch
            yield
            yield
            view["settled"] = list(s.textbox.nvl_view._settled)
            view["areas"] = [(kind, area) for kind, area, _ in areas]
            view["texts"] = list(texts)

        s.play(script)
        got[name] = view
    main = got["main"]
    assert ("settled", (180, 64)) in main["areas"]                 # L8, no name row
    assert ("settled", (180, 162)) in main["areas"]                # L9 under Hana's row
    assert ("current", (180, 221)) in main["areas"]                # L10, no name row
    assert ("Hana", (0xA0, 0x28, 0x60)) in main["texts"]
    hana = [dest for surface, dest in main["settled"] if surface.get_height() and dest[1] < 162
            and dest[1] >= 123]
    assert hana and min(x for x, _ in hana) == 180
    for surface, (x, y) in main["settled"]:
        assert 180 <= x and x + surface.get_width() <= 1100 + 1
        assert 64 <= y and y + surface.get_height() <= 648
    assert got["small"]["areas"] == main["areas"]                  # canvas units at any size
    names = got["names"]["texts"]
    assert ("Kai", (0x20, 0x50, 0x80)) in names
    cut = [text for text, _ in names if text.startswith("WWW")]
    assert cut and cut[0].endswith("…") and len(cut[0]) < 81


# --- AC-F17-16 — lines behave as in the textbox -------------------------------------------------

class _Events:
    def __init__(self, s: Session) -> None:
        self.s, self.at, self.out = s, None, []

    def _add(self, *event):
        if self.at is not None:
            self.out.append((self.s.frame - self.at,) + event)

    def glyph_shown(self, index, grapheme):
        self._add("glyph", index, grapheme)

    def pause_started(self, seconds):
        self._add("pause", seconds)

    def waiting(self, kind):
        self._add("waiting", kind)

    def completed(self, by_press):
        self._add("completed", by_press)


def test_ac_f17_16_lines_behave_as_in_the_textbox(tmp_path):
    line9 = '    hana "I saw it... {pause=0.6}the {b}{color=#e05050}lantern{/color}{/b} moved."'
    results = {}
    for mode, edit in (("nvl", {"replace": {9: line9}}),
                       ("adv", {"replace": {9: line9}, "drop": (7,)})):
        s = Session(game(tmp_path, name=mode, config=CPS40, **edit))
        events = _Events(s)
        kinds, says, l8_drawn = [], [], []

        def script(s):
            yield from s.until(lambda: s.textbox is not None)
            s.textbox.add_listener(events)
            s.textbox.add_say_listener(says.append)
            yield from to_line(s, L8)
            yield from s.until(lambda: complete(s))
            s.key(pygame.K_SPACE)
            yield from s.until(lambda: len(s.said) > L9)
            events.at = s.said[L9][0]
            for frame in range(1, 90):
                if frame == 12:
                    s.key(pygame.K_SPACE)                  # 0.2 s: completes the line
                kinds.append(s.textbox.indicator_kind())
                if s.textbox.nvl_on:
                    l8_drawn.append(len(s.textbox.nvl_view._settled))
                yield

        s.play(script)
        results[mode] = (events.out, kinds, [c.sid for c in says], l8_drawn)
    nvl, adv = results["nvl"], results["adv"]
    assert nvl[0] == adv[0] and nvl[1] == adv[1]
    assert [e for e in nvl[0] if e[1] == "completed"] == [(nvl[0][-1][0], "completed", True)]
    assert len(nvl[2]) == len(set(nvl[2]))                       # each Say once
    glyphs = sum(1 for ch in "The festival comes once a year." if not ch.isspace())
    assert nvl[3] and set(nvl[3]) == {glyphs}                    # L8 whole in every frame


# --- AC-F17-17 — lines longer than a page --------------------------------------------------------

def test_ac_f17_17_lines_longer_than_a_page(tmp_path):
    rows15 = "\\n".join("abcdefghijklmno")
    s = Session(game(tmp_path, replace={9: f'    "{rows15}"'}))
    seen = {}

    def script(s):
        yield from to_line(s, L9)
        tb = s.textbox
        seen["arrival"] = (rows(s), settled_texts(s), tb.typer.page, tb.indicator_kind())
        s.key(pygame.K_SPACE)
        yield
        yield
        page = tb.layout.page(tb.typer.page)
        seen["page2"] = (tb.typer.page, [g.text for ln in page.lines for g in ln.glyphs],
                         ys(s), tb.indicator_kind())
        yield from to_line(s, L10)
        seen["after"] = rows(s)
        seen["state"] = s.app.story.checkpoint()
        s.app.story.restore(seen["state"])
        yield
        yield
        seen["restored"] = rows(s)

    s.play(script)
    page, settled, typer_page, kind = seen["arrival"]
    assert [(p, y) for _, p, y in page] == [(-1, 64)] and settled == [] and typer_page == 0
    assert kind == "page"                                      # rows a–n, then the page mark
    assert seen["page2"] == (1, ["o"], [64], "line")
    assert [(p, y) for _, p, y in seen["after"]] == [(-1, 64), (0, 123)]
    assert seen["restored"] == seen["after"]                   # the same picture restored


# --- AC-F17-18 — the restored page ---------------------------------------------------------------

def test_ac_f17_18_the_restored_page(tmp_path):
    s = Session(game(tmp_path))
    events = _Events(s)
    states: dict[int, GameState] = {}
    seen = {}

    def restore(s, state, *, size=None):
        if size is not None:
            s.textbox.settings.text_size = size
        s.app.story.restore(state)
        events.at, events.out[:] = s.frame, []
        yield
        yield

    def script(s):
        yield from s.until(lambda: s.textbox is not None)
        s.textbox.add_listener(events)
        for index in range(L23 + 1):
            yield from to_line(s, index)
            states[index] = s.app.story.checkpoint()
        yield from restore(s, states[L10])                     # rollback to line 10
        tb = s.textbox
        seen["10"] = (ys(s), tb.typer.state, tb.indicator_kind(),
                      [e for e in events.out if e[1] == "glyph"],
                      [e.sid for e in tb.nvl.entries], tb.line.sid)
        count = len(s.posted)
        s.key(pygame.K_SPACE)
        yield
        yield
        seen["posted"] = [a for _, a in s.posted[count:]]
        yield from restore(s, states[L14])                     # rollback to line 14
        seen["14"] = [t for t in settled_texts(s)] + ["".join(
            span.text for span in s.textbox.nvl.entries[-1].spans)]
        clear_heights()                                        # load at line 10, size 42
        loaded = GameState.from_json(json.loads(json.dumps(states[L10].to_json())))
        yield from restore(s, loaded, size=42)
        seen["42"] = ys(s)
        s.textbox.settings.text_size = None
        yield from restore(s, states[L6])                      # rollback to line 6
        seen["6"] = (s.textbox.nvl_on, s.textbox.line.text, s.textbox.typer.state, s.px(*P))

    s.play(script)
    page, state, kind, glyphs, sids, current = seen["10"]
    assert page == [64, 123, 221] and state is TypeState.COMPLETE and kind == "line"
    assert glyphs == [] and len(sids) == len(set(sids)) == 3 and current == sids[-1]
    assert seen["posted"] == [Advance(current)]
    assert seen["14"] == ["Three days later, a lantern came.", "It was a letter."]
    assert seen["42"] == [64, 143, 281]                        # Hana's row 143, its text 202
    assert seen["6"] == (False, "Before.", TypeState.COMPLETE, RED)


# --- AC-F17-19 — input, hide, freeze ------------------------------------------------------------

def test_ac_f17_19_input_hide_freeze(tmp_path, monkeypatch):
    s = Session(game(tmp_path, config=CPS40))
    draws = spy_draws(monkeypatch, s)
    results = []

    def hide_inputs():
        yield "H", lambda: s.key(pygame.K_h)
        yield "middle", lambda: s.mouse((640, 360), button=2)
        yield "north", lambda: s.event(pygame.CONTROLLERBUTTONDOWN,
                                       button=pygame.CONTROLLER_BUTTON_Y, instance_id=0)
        yield "set_hidden", None

    def script(s):
        yield from to_line(s, L9)
        tb = s.textbox
        for name, send in hide_inputs():
            if send is None:
                tb.set_hidden(True)
            else:
                send()
            yield
            yield
            before = tb.typer.shown
            frame = s.frame
            for _ in range(5):
                yield
            hidden = (tb.hidden, s.px(*P), [k for f, k in draws if f >= frame],
                      tb.typer.shown == before)
            if send is None:
                tb.set_hidden(False)
            else:
                send()
            yield
            yield
            results.append((name, hidden, tb.hidden, s.px(*P), tb.typer.shown >= before))
        count = len(s.posted)
        s.event(pygame.MOUSEWHEEL, x=0, y=-1, flipped=False, precise_x=0.0, precise_y=-1.0)
        yield
        yield
        results.append(("wheel down", [a for _, a in s.posted[count:]]))

    s.play(script)
    for name, hidden, after_hidden, after_px, resumed in results[:-1]:
        assert hidden == (True, RED, [], True), name           # nothing drawn, typing held
        assert (after_hidden, after_px, resumed) == (False, PANEL, True), name
    assert results[-1] == ("wheel down", [])


# --- AC-F17-20 — quick menu and overlays over the panel ------------------------------------------

def test_ac_f17_20_quick_menu_and_overlays_over_the_panel(tmp_path, monkeypatch):
    s = Session(game(tmp_path))
    order: list[tuple[int, str, bool]] = []
    real_nvl, real_box, real_quick = NvlView.draw, TextboxView.draw_box, QuickMenu.draw

    def nvl_draw(self, *a, **k):
        order.append((s.frame, "panel", True))
        real_nvl(self, *a, **k)

    def box_draw(self, *a, **k):
        order.append((s.frame, "box", True))
        real_box(self, *a, **k)

    def quick_draw(self, canvas, *, box_shown):
        order.append((s.frame, "quick", box_shown))
        real_quick(self, canvas, box_shown=box_shown)

    class Overlay:
        def handle_event(self, event, *, box_shown):
            return False

        def update(self, dt, *, frozen):
            pass

        def draw(self, canvas, *, box_shown):
            order.append((s.frame, "overlay", box_shown))

    monkeypatch.setattr(NvlView, "draw", nvl_draw)
    monkeypatch.setattr(TextboxView, "draw_box", box_draw)
    monkeypatch.setattr(QuickMenu, "draw", quick_draw)
    frames = {}

    def script(s):
        yield from s.until(lambda: s.textbox is not None)
        s.textbox.add_overlay(Overlay())
        yield from to_line(s, L6)
        frames["adv"] = s.said[L6][0]
        yield from to_line(s, L9)
        frames["nvl"] = s.said[L9][0]
        s.textbox.set_hidden(True)
        yield
        frames["hidden"] = s.frame
        yield
        s.textbox.set_hidden(False)

    s.play(script)
    at = lambda frame: [(kind, shown) for f, kind, shown in order if f == frame]  # noqa: E731
    assert at(frames["adv"]) == [("box", True), ("quick", True), ("overlay", True)]
    assert at(frames["nvl"]) == [("panel", True), ("quick", True), ("overlay", True)]
    assert at(frames["hidden"]) == [("quick", False), ("overlay", False)]


# --- AC-F17-21 — in-game reset ------------------------------------------------------------------

def test_ac_f17_21_in_game_reset(tmp_path):
    from engine.ui.builtin.skip_auto import SkipAuto
    s = Session(game(tmp_path))
    seen = {}

    def new_game(s):
        s.app.shell._new_game_cut()                    # Main Menu → Yes, then New Game
        count = len(s.said)
        yield from s.until(lambda: len(s.said) > count)
        s.said[:] = s.said[count:]

    def script(s):
        yield from s.until(lambda: s.textbox is not None and s.app.shell is not None)
        resets = [getattr(fn, "__self__", None) for fn in s.app.shell._resets]
        seen["order"] = [type(r).__name__ for r in resets
                         if isinstance(r, (SkipAuto, textbox_screen.TextboxScreen))]
        yield from to_line(s, L10)
        state = s.app.story.checkpoint()
        yield from new_game(s)
        seen["new"] = (s.px(*P), s.textbox.nvl_on, s.app.story.interp.nvl,
                       s.textbox.line.text)
        yield from to_line(s, L8)
        s.textbox.clear(hide=True)                     # a pending F09 hide
        yield from new_game(s)
        yield from to_line(s, L8)
        seen["shown"] = (s.textbox.box_shown, s.px(*P))
        s.app.shell._reset_in_game()
        s.app.story.restore(state)
        yield
        yield
        seen["restored"] = (ys(s), s.textbox.typer.state)

    s.play(script)
    assert seen["order"] == ["SkipAuto", "TextboxScreen"]          # F17's after F15's (I-7)
    assert seen["new"] == (RED, False, EMPTY_NVL, "Before.")
    assert seen["shown"] == (True, PANEL)
    assert seen["restored"] == ([64, 123, 221], TypeState.COMPLETE)


# --- AC-F17-22 — text size ----------------------------------------------------------------------

def test_ac_f17_22_text_size(tmp_path):
    s = Session(game(tmp_path))
    seen = {}

    def script(s):
        yield from to_line(s, L9)
        s.textbox.settings.text_size = 42
        yield
        seen["kept"] = s.textbox.layout.ctx.text_size
        yield from to_line(s, L10)
        seen["replanned"] = (ys(s), s.textbox.layout.ctx.text_size)

    s.play(script)
    assert seen["kept"] == 28
    assert seen["replanned"] == ([64, 143, 281], 42)          # Hana 143, L9's text 202
    # Theme sizes × text sizes: a 200-character name and Rows(30) stay above 648.
    from engine.core.config_schema import NvlTheme, ThemeConfig
    from tests.fakes.fixed_font import FixedFont
    rows30 = "\n".join("abcdefghijklmnopqrstuvwxyzABCD")
    say = Say("s/1", "hana", "N" * 200, None, (), rows30,
              body=_body(rows30))
    for theme_size in (20, 28, 48):
        look = nvl_look(ThemeConfig(nvl=NvlTheme(text_size=theme_size)))
        for scale in (1.0, 1.3, 1.5):
            m = nvl_metrics(look, scale)
            presenter = NvlPresenter(FixedFontAssets(), BUNDLED_FACES, look)
            presenter.set(True, (), m)
            presenter.arrive(say, m)
            for row in presenter.rows():
                bottom = row.y + m.pitch + presenter.settled_page(row).lines[-1].top \
                    + presenter.settled_page(row).lines[-1].pitch
                assert bottom <= 648, (theme_size, scale)
            view = NvlView(None, look, BUNDLED_FACES, None)            # type: ignore[arg-type]
            assert view._fitted("N" * 200, m, FixedFont(m.size)).endswith("…")


def _body(text: str):
    from engine.runtime.commands import TaggedText
    return TaggedText((Span(text, Style()),))


# --- AC-F17-32 — hostile and odd content --------------------------------------------------------

def test_ac_f17_32_hostile_and_odd_content(tmp_path, monkeypatch):
    s = Session(game(tmp_path, replace={7: '    $ v = "{b}x\\u0007"⏎[4]nvl on',
                                        8: '    "{var=v}"'}))
    texts = text_calls(monkeypatch, s)
    seen = {}

    def script(s):
        yield from to_line(s, L8)
        yield
        seen["drawn"] = {t for t, _ in texts}
        state = s.app.story.checkpoint()
        bad = state.to_json()
        bad["nvl"] = {"on": 1, "page": [], "ZZMARK": "ZZMARK"}
        try:
            GameState.from_json(bad)
        except StateInvalid as error:
            seen["refused"] = str(error)
        seen["kept"] = rows(s)
        odd = NvlLine("zz/000000000000", "W" * 200, None,
                      (Span("祭りは年に一度。", Style()),))
        hostile = state.to_json()
        hostile["nvl"]["page"].insert(0, {"sid": odd.sid, "name": odd.name, "color": None,
                                          "spans": [{"text": "祭りは年に一度。"}]})
        del texts[:]
        s.app.story.restore(GameState.from_json(hostile))
        yield
        yield
        seen["odd"] = ({t for t, _ in texts}, rows(s))

    s.play(script)
    assert {"{", "b", "}", "x", render_safe("\u0007")} <= seen["drawn"]
    assert "ZZMARK" not in seen["refused"] and seen["kept"]
    drawn, page = seen["odd"]
    names = [t for t in drawn if t.startswith("WWW")]
    assert names and names[0].endswith("…") and "祭" in drawn
    assert page[0][0] == "zz/000000000000"                    # drawn, never looked up


# --- AC-F17-33 — no viewport-sized surface while drawing NVL ------------------------------------

def test_ac_f17_33_no_viewport_surface(tmp_path, monkeypatch):
    lines = "".join(f'    "Line {k} of the diary page, typed one grapheme after another."\n'
                    for k in range(10))
    s = Session(game(tmp_path, script="label start:\n    nvl on\n" + lines + "    \"End.\"\n"),
                size=(1920, 1080))
    sizes: list[tuple[int, int]] = []
    real_draw, real_surface = NvlView.draw, pygame.Surface

    class Spy(real_surface):                                   # type: ignore[misc, valid-type]
        def __init__(self, size, *a, **k):
            sizes.append(tuple(size))
            super().__init__(size, *a, **k)

    def draw(self, *a, **k):
        monkeypatch.setattr(pygame, "Surface", Spy)
        try:
            real_draw(self, *a, **k)
        finally:
            monkeypatch.setattr(pygame, "Surface", real_surface)

    monkeypatch.setattr(NvlView, "draw", draw)
    frames = []

    def script(s):
        yield from to_line(s, 9)
        for _ in range(120):
            frames.append(s.frame)
            yield

    s.play(script)
    assert len(frames) == 120
    assert all(w * h < 1920 * 1080 for w, h in sizes)


# --- AC-F17-34 — CI cost guard ------------------------------------------------------------------

def test_ac_f17_34_cost_guard(tmp_path, monkeypatch):
    sentence = "the lanterns drift past the bridge rail while the river runs slow tonight"
    lines = "".join(f'    "{k} {sentence}."\n' for k in range(33))
    s = Session(game(tmp_path, config="[textbox]\ncps = 1000\n",
                     script="label start:\n    nvl on\n" + lines),
                size=(1920, 1080))
    counts = {"layouts": [], "builds": 0, "fits": 0, "blits": 0}
    real_layout = nvl_page.LineLayout
    real_tb_layout = textbox_screen.LineLayout
    real_build, real_fit = TextboxView.build_glyphs, nvl_module.fit_line
    real_draw, real_show = NvlView.draw, textbox_screen.TextboxScreen.show

    def layout(cls):
        def make(body, ctx):
            counts["layouts"].append("".join(getattr(p, "text", "") for p in body.pieces))
            return cls(body, ctx)
        return make

    class Proxy:
        def __init__(self, surface):
            self._surface = surface

        def __getattr__(self, name):
            return getattr(self._surface, name)

        def blits(self, *a, **k):
            counts["blits"] += 1
            return self._surface.blits(*a, **k)

    timings = {"draw": [], "show": []}

    def draw(self, canvas, *a, **k):
        surface = canvas.surface
        canvas.surface = Proxy(surface)
        start = time.perf_counter()
        try:
            real_draw(self, canvas, *a, **k)
        finally:
            canvas.surface = surface
            timings["draw"].append((s.frame, time.perf_counter() - start))

    def show(self, cmd):
        start = time.perf_counter()
        real_show(self, cmd)
        timings["show"].append((s.frame, time.perf_counter() - start))

    monkeypatch.setattr(nvl_page, "LineLayout", layout(real_layout))
    monkeypatch.setattr(textbox_screen, "LineLayout", layout(real_tb_layout))
    monkeypatch.setattr(TextboxView, "build_glyphs", lambda self, *a: (
        counts.__setitem__("builds", counts["builds"] + 1), real_build(self, *a))[1])
    monkeypatch.setattr(nvl_module, "fit_line", lambda *a: (
        counts.__setitem__("fits", counts["fits"] + 1), real_fit(*a))[1])
    monkeypatch.setattr(NvlView, "draw", draw)
    monkeypatch.setattr(textbox_screen.TextboxScreen, "show", show)
    seen = {}

    def reset():
        counts.update(layouts=[], builds=0, fits=0, blits=0)

    def script(s):
        yield from to_line(s, 8)                              # a page of 9 lines
        yield from s.until(lambda: complete(s))
        yield
        reset()
        for _ in range(5):                                    # (a) steady frames
            yield
        seen["steady"] = dict(counts, layouts=list(counts["layouts"]))
        reset()
        yield from to_line(s, 9)                              # (b) an arrival below
        seen["arrival"] = list(counts["layouts"])
        yield from to_line(s, 32)
        yield from s.until(lambda: complete(s))
        state = s.app.story.checkpoint()                      # 32 lines shown
        misses = heights_cache_info()[2]
        reset()
        s.app.story.restore(state)                            # (c) rollback, warm
        yield
        yield
        seen["rollback"] = (heights_cache_info()[2] - misses, len(counts["layouts"]),
                            len(s.textbox.nvl.rows()))
        seen["rollback_frame"] = s.frame - 2

    s.play(script)
    steady = seen["steady"]
    assert steady["layouts"] == [] and steady["builds"] == 0 and steady["fits"] == 0
    assert steady["blits"] <= 2 * 5
    new_line = f"9 {sentence}."
    assert seen["arrival"] and set(seen["arrival"]) == {new_line}
    misses, built, visible = seen["rollback"]
    assert misses == 0 and built <= visible <= 10
    # (d) CI medians: a line arrival's F17 work ≤ 12 ms; the rollback frame ≤ 48 ms.
    shows = dict(timings["show"])
    arrivals = [shows[f] + sum(t for g, t in timings["draw"] if g == f) for f in shows]
    assert statistics.median(arrivals) <= 0.012
    frame = seen["rollback_frame"]
    work = sum(t for g, t in timings["draw"] + timings["show"] if g in (frame, frame + 1))
    assert work <= 0.048


# --- F14 A4 — the NVL branch of cue_anchor and set_bump (I-8) -----------------------------------

def test_f14_cue_anchor_and_bump_follow_the_nvl_window(tmp_path):
    s = Session(game(tmp_path))
    seen = {}

    def script(s):
        yield from to_line(s, L6)
        tb = s.textbox
        seen["adv"] = (tb.nvl_cue, tb.cue_anchor())
        yield from to_line(s, L8)
        tb.set_bump(-6.0)
        seen["nvl"] = (tb.nvl_cue is tb.nvl_view, tb.cue_anchor(), tb.nvl_view.bump)
        tb.set_bump(0.0)
        yield from to_line(s, L23)
        seen["off"] = tb.nvl_cue

    s.play(script)
    x, y, w, _ = (180.0, 0.0, 920.0, 0.0)
    assert seen["adv"][0] is None and seen["adv"][1] != (x + w - 52, 64.0)
    assert seen["nvl"] == (True, (x + w - 52, 64.0), -6.0)
    assert seen["off"] is None


# --- AC-F17-25 — transitions (F09) ----------------------------------------------------------------

def _uniform(s: Session) -> bool:
    """Every pixel of the last frame has one color: the stage alone (a dissolve between two
    plain pictures), with no panel, page, or quick menu over it."""
    fb = s.fb
    mask = pygame.mask.from_threshold(fb, fb.get_at((0, 0)), (2, 2, 2, 255))
    return mask.count() == fb.get_width() * fb.get_height()


HANA9 = """    hana "You're thinking about {b}last year{/b} again." """.rstrip()


def test_ac_f17_25_transitions(tmp_path):
    """The rows dissolve to a plain blue picture, not to ``red`` again: F09 takes no time for
    an unchanged picture (``effects.moment``), so ``scene red with dissolve`` after ``scene
    red`` would not dissolve at all."""
    seen: dict[str, object] = {}
    # R9: a dissolve between L8 and Hana's line; R8: a dissolve right after `nvl on`.
    for name, edit, index in (("r9", {9: "    scene blue with dissolve⏎" + HANA9}, L9),
                              ("r8", {8: "    scene blue with dissolve"}, L8)):
        root = game(tmp_path, name=name, replace=edit)
        blue = pygame.Surface((1280, 720))
        blue.fill((0, 0, 255))
        pygame.image.save(blue, str(root / "images" / "blue.png"))
        s = Session(root)

        def script(s, name=name, index=index):
            during = []
            yield from to_line(s, index - 1)          # the line before the dissolve
            yield from s.until(lambda: complete(s))
            s.key(pygame.K_SPACE)                     # one press; the dissolve plays out
            while len(s.said) <= index:
                yield
                if s.app.stage_screen.view.transitioning:
                    during.append((_uniform(s), s.textbox.box_shown))
            seen[name] = (during, ys(s), settled_texts(s), _uniform(s), s.textbox.box_shown)

        s.play(script)
    for name in ("r9", "r8"):
        during, _, _, uniform, shown = seen[name]
        assert len(during) > 5 and all(d == (True, False) for d in during), name
        assert (uniform, shown) == (False, True), name      # the arrival frame has the panel
    assert seen["r9"][1:3] == ([64, 123], ["The festival comes once a year."])   # page kept
    assert seen["r8"][1:3] == ([64], [])               # the panel comes with the line
    # clear(hide=False) while line 9 types: settled on the page, no indicator, idle press.
    s = Session(game(tmp_path, name="clear", config=CPS40))
    idle: list[int] = []

    def script(s):
        yield from to_line(s, L9)
        yield
        tb = s.textbox
        tb.on_idle_advance = lambda: idle.append(s.frame)
        typing = tb.typer.state is not TypeState.COMPLETE
        tb.clear(hide=False)
        count = len(s.posted)
        yield
        yield
        seen["clear"] = (typing, ys(s), settled_texts(s), tb.line, tb.indicator_kind(),
                         s.px(*P), tb.box_shown)
        s.key(pygame.K_SPACE)
        yield
        yield
        seen["press"] = (len(idle), len(s.posted) - count)

    s.play(script)
    typing, page, settled, line, kind, panel, shown = seen["clear"]
    assert typing and page == [64, 123] and line is None and kind is None
    assert settled == ["The festival comes once a year.",
                       "You're thinking about last year again."]
    assert (panel, shown) == (PANEL, True) and seen["press"] == (1, 0)


# --- AC-F17-27 — skip and auto (F15) ---------------------------------------------------------------

def _story_json(state: GameState) -> dict:
    out = state.to_json()
    for key in ("dice", "rollback"):              # the seed and F14's window, not the story
        out.pop(key)
    return out


def test_ac_f17_27_skip_and_auto(tmp_path):
    from tests.runtime.nvl_story import bursts, load_n

    # Auto at the F15 defaults (base 1,000 ms, 40 ms per grapheme): line 10's own count.
    s = Session(game(tmp_path, name="auto", config=CPS40))
    seen: dict[object, object] = {}

    def auto(s):
        yield from s.until(lambda: getattr(s.app, "skip_auto", None) is not None
                           and s.line_text() is not None)
        s.app.skip_auto.set_auto(True)
        yield from s.until(lambda: len(s.said) > L10, limit=1200)
        sid10 = s.said[L10][1].sid
        yield from s.until(lambda: complete(s), limit=300)
        done = s.frame - 1                          # the frame it completed in
        seen["count"] = s.textbox.shown_count()
        yield from s.until(lambda: any(a.sid == sid10 for _, a in s.posted), limit=300)
        seen["delay"] = next(f for f, a in s.posted if a.sid == sid10) - done
        resets = s.app.shell._resets
        seen["order"] = (resets.index(s.app.skip_auto.reset),
                         resets.index(s.textbox.reset_nvl))

    s.play(auto)
    assert seen["count"] == 16
    assert abs(seen["delay"] / 60 - 1.640) <= 1 / 60 + 1e-9, seen["delay"]
    assert seen["order"][0] < seen["order"][1]           # F17's reset runs after F15's
    # Skip from line 6 to the menu: the same checkpoint at every line as manual advances
    # (AC-F17-10: App A's manual run equals Run N's checkpoints).
    _, _, states = bursts(load_n(tmp_path / "headless"))
    s = Session(game(tmp_path, name="skip", config=CPS40 + "[skip]\nall = true\n"))
    lines: list[dict] = []

    def skip(s):
        yield from s.until(lambda: getattr(s.app, "skip_auto", None) is not None
                           and s.line_text() is not None)
        lines.append(_story_json(s.app.story.checkpoint()))
        count = len(s.said)
        assert s.app.skip_auto.start_skip()
        while True:
            if len(s.said) > count:                   # one checkpoint per line shown
                count = len(s.said)
                lines.append(_story_json(s.app.story.checkpoint()))
            if s.textbox.menu_waiting and complete(s):
                break
            yield
        for _ in range(10):
            yield
        seen["menu"] = (s.app.skip_auto.skipping, len(s.said))

    s.play(skip)
    assert lines == [_story_json(state) for state in states[:7]]
    assert seen["menu"] == (False, 7)                    # skip stops at the menu


# --- AC-F17-28 — blips (F06) -----------------------------------------------------------------------

def test_ac_f17_28_blips(tmp_path):
    from engine.audio.service import AudioService
    from engine.core.config_schema import AudioConfig
    from engine.core.lru import SizedLru
    from engine.ui.blips import BlipPlayer
    from tests.audio.conftest import BlipMixer
    from tests.ui.test_blips_textbox import BLIP, blips

    define = 'define hana = Character("Hana", color="#A02860", blip="blips/a.ogg")'
    results = {}
    for mode, drop in (("nvl", ()), ("adv", (7,))):
        root = game(tmp_path, name=mode, config=CPS40, replace={1: define}, drop=drop)
        (root / "audio" / "blips").mkdir(parents=True, exist_ok=True)
        (root / "audio" / "blips" / "a.ogg").write_bytes(BLIP["blips/a.ogg"])
        s = Session(root)
        mixer = BlipMixer(clock=s.clock)
        mixer.register(BLIP["blips/a.ogg"], "blips/a.ogg", 0.1)
        s.app.audio = AudioService(s.paths, SizedLru(1 << 24), AudioConfig(), backend=mixer,
                                   clock=s.clock)
        log: list[tuple[int, str]] = []
        seen: dict[str, object] = {}

        def spy(self, index, grapheme, real=BlipPlayer.glyph_shown, mixer=mixer, s=s,
                log=log):
            before = blips(mixer)
            real(self, index, grapheme)
            if blips(mixer) > before:
                log.append((s.frame, grapheme))

        def script(s, seen=seen, log=log):
            yield from to_line(s, L9)
            start, mark = s.said[L9][0], len(log)
            yield from s.until(lambda: complete(s), limit=300)
            seen["line9"] = [(f - start, g) for f, g in log[mark:]]
            state = s.app.story.checkpoint()
            yield from to_line(s, L10)                    # L9 now settled on the page
            mark = len(log)
            yield from s.until(lambda: complete(s), limit=300)
            for _ in range(10):
                yield
            seen["settled"] = log[mark:]
            mark = len(log)
            s.app.story.restore(state)                    # line 9 restored
            for _ in range(10):
                yield
            seen["restored"] = log[mark:]

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(BlipPlayer, "glyph_shown", spy)
            s.play(script)
        results[mode] = seen
    nvl, adv = results["nvl"], results["adv"]
    assert nvl["line9"] and len(nvl["line9"]) == len(adv["line9"])
    assert all(g1 == g2 and abs(f1 - f2) <= 1
               for (f1, g1), (f2, g2) in zip(nvl["line9"], adv["line9"]))
    assert nvl["settled"] == [] and nvl["restored"] == []
