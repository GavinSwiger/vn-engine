"""F13 step 3 — the History page on a real ``GameShell`` (test_game_menu's ``Game`` rig, no
frame loop): AC-F13-05 (unit rows), 06, 07, 09, 10 (wrap cost), 11, 12. The page reads
``HistoryPorts`` built here (fixed entries, a voice table, an F08 spy); the App's ports
(``app/history.py``) are covered in ``tests/app/test_history_app.py``.

Geometry at the default text size: s 28, p 39; the body slot is (416, 112, 808×552), so
page keys and the tall-row step are 552 − 39 = 513 and a wheel notch 3 × (39 + 8) = 141.
"""

import random
import time

import pygame
import pytest

from engine.render.text import Face, text_width
from engine.render.textlayout import clear_word_cache, word_cache
from engine.runtime.history import HistoryEntry
from engine.ui.builtin import history_page
from engine.ui.builtin.history_page import (CHOICE_WIDTH, TEXT_WIDTH, HistoryPage,
                                            HistoryPorts, HistoryWraps, RowStyle,
                                            layout_rows, open_from_quick, register_history,
                                            slack, wrap_history_text)
from engine.ui.focus import Box
from engine.ui.menu_screen import Phase
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import Painter
from tests.fakes.draw_spy import spy_draw_text
from tests.ui.test_game_menu import FADE, Game, H

BODY = Box(416, 112, 808, 552)
P = 39
STEP = 552 - P                         # 513
NOTCH = 3 * (P + 8)                    # 141


class ReplaySpy:
    """F08's two seams the page uses."""

    def __init__(self) -> None:
        self.replays: list[str] = []
        self.stops = 0

    def replay_voice(self, file: str) -> None:
        self.replays.append(file)

    def stop_replay(self) -> None:
        self.stops += 1


def line(sid: str, text: str, name: str = "") -> HistoryEntry:
    return HistoryEntry("line", sid, name, text)


def choice(sid: str, text: str) -> HistoryEntry:
    return HistoryEntry("choice", sid, "", text)


FESTIVAL = (line("q1", "Will you buy a lantern?", "Daichi"),
            choice("q1", "The paper crane (2 coins)"),
            line("h1", "A crane! Good choice.", "Hana"))


class Hist:
    """A game in progress with F13's entries registered over fixed ports."""

    def __init__(self, tmp_path, entries=FESTIVAL, *, voices=None, audio: bool = True) -> None:
        self.g = Game(tmp_path)
        self.audio = ReplaySpy() if audio else None
        self.entries = tuple(entries)
        self.voices = dict(voices or {})
        self.asked: list[str] = []
        self.ports = HistoryPorts(lambda: self.entries, self._voice, self.audio)
        register_history(self.g.shell, self.ports)

    def _voice(self, sid: str) -> str | None:
        self.asked.append(sid)
        return self.voices.get(sid)

    def open(self, *, by_keys: bool = True) -> tuple:
        """The game menu, then its History page (by keys: Down, Return)."""
        g = self.g
        menu = g.open()
        if by_keys:
            g.frame(H.key(pygame.K_DOWN))
            g.frame(H.key(pygame.K_RETURN))
        else:
            button = g.button("history")
            g.frame(H.motion(button.box.center))
            g.h.click(button.box.center)
        assert menu.page_id == "history"
        return menu, menu.page

    def frame(self, *events):
        return self.g.frame(*events)


def long_text(words: int, seed: int = 1) -> str:
    rng = random.Random(seed)
    vocab = ["lantern", "river", "the", "paper", "crane", "a", "festival", "Hana", "night",
             "quietly", "glowing", "water", "and", "I", "watched", "drift", "away", "summer"]
    return " ".join(rng.choice(vocab) for _ in range(words))


# --- AC-F13-05 — opening and closing (unit rows) -------------------------------------------

def test_ac05_game_menu_history_shows_the_heading_and_back_closes_the_page(tmp_path,
                                                                           monkeypatch):
    h = Hist(tmp_path)
    g = h.g
    menu = g.open()
    assert g.labels() == ["Return", "History", "Main Menu", "Quit"]
    with spy_draw_text(monkeypatch) as calls:
        g.frame(H.key(pygame.K_DOWN))
        g.frame(H.key(pygame.K_RETURN))
    page = menu.page
    assert isinstance(page, HistoryPage) and g.button("history").is_selected()
    assert any(c.text == "History" and c.pos == (416, 56) for c in calls)
    assert page.list.box == BODY and not page.close_menu_on_back
    g.frame(H.key(pygame.K_ESCAPE))                    # Back closes the page only
    assert menu.page is None and menu.phase is Phase.OPEN
    assert menu.scope.focused is g.button("history")
    assert h.audio.stops == 1                          # I-5: leaving stops a replay
    g.frame(H.key(pygame.K_ESCAPE))
    assert menu.phase is Phase.CLOSING
    assert "history" not in g.shell.menus.registered("title")     # the title has none
    assert g.shell.menus.registered("game") == ["return", "history", "main_menu", "quit"]


def test_ac05_quick_menu_history_opens_the_page_and_back_closes_the_menu(tmp_path):
    """Esc, right click and east each close the whole menu (a fresh game each); by keys the
    newest row is focused; hidden from the game menu, only the menu opens."""
    backs = {"esc": [H.key(pygame.K_ESCAPE)],
             "right-click": [H.down((640, 360), 3), H.up((640, 360), 3)],
             "east": [H.pad(pygame.CONTROLLER_BUTTON_B)]}
    for name, back in backs.items():
        h = Hist(tmp_path / name)
        g = h.g
        quick = g.shell.quick_menu
        assert [e.id for e in quick.shown().entries] == ["history", "hide", "menu"]
        entry = g.shell.menus.entry("quick", "history")
        entry.action(history_page.EntryContext(g.shell, InputKind.MOUSE))
        menu = g.menu
        assert menu.page_id == "history" and menu.page.close_menu_on_back
        assert menu.scope.focused is None              # by mouse: nothing focused
        g.frames(FADE + 1)
        g.frame(*back)
        assert menu.phase is Phase.CLOSING, name
        g.frames(FADE + 1)
        assert g.shell.game_menu() is None and h.audio.stops == 1, name
    h = Hist(tmp_path / "keys")
    open_from_quick(h.g.shell, InputKind.KEYS)
    menu = h.g.menu
    page = menu.page
    assert menu.scope.focused is page.list and page.list.focus_row == 2
    open_from_quick(h.g.shell, InputKind.KEYS)        # a menu is open: nothing more
    assert h.g.menu is menu
    h = Hist(tmp_path / "hidden")
    h.g.shell.overrides.set_hidden("game", "history", True)
    open_from_quick(h.g.shell, InputKind.MOUSE)
    assert h.g.menu.page is None


# --- AC-F13-06 — the rows as drawn -----------------------------------------------------------

def _row_calls(calls, page, index):
    box = page.list.row_box(index)
    return [c for c in calls if box.y <= c.pos[1] < box.bottom and BODY.contains(c.pos)]


def test_ac06_rows_in_order_with_name_text_and_choice(tmp_path, monkeypatch):
    h = Hist(tmp_path)
    menu, page = h.open()
    rects: list = []
    real_rect = Painter.rect
    monkeypatch.setattr(Painter, "rect", lambda self, box, color: (
        rects.append((box, tuple(color))), real_rect(self, box, color))[1])
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    theme = h.g.shell.theme.cfg
    heading, text_color = tuple(theme.panel.heading.text_color), tuple(theme.panel.text_color)
    marker = tuple(theme.button.marker.fill_color)
    heights = [page.rows[i].height for i in range(3)]
    assert heights == [24 + 2 * P, 24 + P, 24 + 2 * P]
    boxes = [page.list.row_box(i) for i in range(3)]
    assert boxes[0].y == BODY.y and boxes[1].y == boxes[0].bottom
    drawn = [(c.text, c.pos[0] - BODY.x, c.pos[1] - box.y - P / 2, c.color, c.font)
             for i, box in enumerate(boxes) for c in _row_calls(calls, page, i)]
    assert [d[:4] for d in drawn] == [
        ("Daichi", 32, 12, heading), ("Will you buy a lantern?", 32, 12 + P, text_color),
        ("The paper crane (2 coins)", 48, 12, heading),
        ("Hana", 32, 12, heading), ("A crane! Good choice.", 32, 12 + P, text_color)]
    assert all(c.options.get("anchor") == "midleft" for c in calls if BODY.contains(c.pos))
    name_font, text_font = drawn[0][4], drawn[1][4]
    assert name_font.size == text_font.size == 28
    assert name_font.bundled is Face.BOLD and text_font.bundled is Face.REGULAR
    bar = Box(BODY.x + 32, boxes[1].y + 12, 4, heights[1] - 24)
    assert (bar, marker) in rects


def test_ac06_long_text_wraps_39_apart_within_696(tmp_path, monkeypatch):
    entries = (line("s1", long_text(35), "Hana"), choice("m1", long_text(25, seed=2)))
    h = Hist(tmp_path, entries)
    menu, page = h.open()
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    for index, limit in ((0, TEXT_WIDTH), (1, CHOICE_WIDTH)):
        rows = _row_calls(calls, page, index)[1 - index:]          # the text lines
        assert len(rows) >= 3
        ys = [c.pos[1] for c in rows]
        assert all(b - a == P for a, b in zip(ys, ys[1:]))
        assert all(c.bounds[2] <= limit for c in rows)
        assert page.rows[index].height == 24 + P * (len(rows) + (1 - index))


def test_ac06_ac07_opens_at_the_bottom_clipped_page_keys_and_wheel(tmp_path, monkeypatch):
    """AC-06: opened at the bottom, only rows in view draw, clipped. AC-07: PgUp/PgDn
    ±513, Home/End, and the wheel ±141 per notch (one 40-row page for all three)."""
    entries = [line(f"s{i}", f"Line {i}.", "Hana") for i in range(40)]
    h = Hist(tmp_path, entries)
    menu, page = h.open()
    lst = page.list
    assert lst.max_scroll() > 0 and lst.scroll == lst.max_scroll()
    assert lst.focus_row == 39
    clips: list = []
    real = history_page.draw_history_row

    def spy(p, row, box, look, style):
        clips.append((row, p.canvas.surface.get_clip()))
        real(p, row, box, look, style)

    monkeypatch.setattr(history_page, "draw_history_row", spy)
    h.frame()
    shown = list(lst.visible_range())
    assert [r for r, _ in clips] == [page.rows[i] for i in shown] and shown[-1] == 39
    assert len(shown) < 40
    body_px = h.g.h.canvas.rect_to_px((BODY.x, BODY.y, BODY.w, BODY.h))
    assert all(clip == body_px for _, clip in clips)
    end = lst.scroll
    assert lst.on_nav(Nav.PAGE_UP) and lst.scroll == end - STEP
    assert lst.on_nav(Nav.PAGE_DOWN) and lst.scroll == end
    assert lst.on_nav(Nav.HOME) and lst.scroll == 0 and lst.focus_row == 0
    assert lst.on_nav(Nav.END) and lst.scroll == end and lst.focus_row == 39
    h.frame(H.wheel(BODY.center, 1))
    assert lst.scroll == end - NOTCH
    h.frame(H.wheel(BODY.center, -1))
    assert lst.scroll == end


def test_ac06_an_empty_history_draws_list_empty(tmp_path, monkeypatch):
    h = Hist(tmp_path, ())
    menu, page = h.open()
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    assert any(c.text == "Nothing here yet." and c.pos == BODY.center for c in calls)
    h.frame(H.key(pygame.K_RIGHT))                    # nothing to enter
    assert menu.scope.focused is h.g.button("history")


# --- AC-F13-07 — input -----------------------------------------------------------------------

def test_ac07_a_tall_row_scrolls_513_per_down_until_its_bottom_shows(tmp_path):
    tall = "\n".join(f"Line {i}" for i in range(38))          # 24 + 38 × 39 = 1,506
    h = Hist(tmp_path, [line("a", "Before."), line("b", tall), line("c", "After.")])
    menu, page = h.open()
    lst = page.list
    assert page.rows[1].height == 1506
    assert lst.on_nav(Nav.HOME) and lst.scroll == 0 and lst.focus_row == 0
    assert lst.on_nav(Nav.DOWN) and lst.focus_row == 1
    top = lst.row_box(1).y - BODY.y + lst.scroll
    assert lst.scroll == top                                   # near edge aligned
    steps = []
    while True:
        before = lst.scroll
        assert lst.on_nav(Nav.DOWN)
        if lst.focus_row != 1:
            break
        steps.append(lst.scroll - before)
    assert steps[:-1] == [STEP] * (len(steps) - 1) and 0 < steps[-1] <= STEP
    assert lst.focus_row == 2


def test_ac07_entering_ends_and_an_unvoiced_row(tmp_path, monkeypatch):
    """Entering by keys focuses the newest row (by mouse none); Up/Down leave the list at its
    ends; activating an unvoiced row does nothing."""
    h = Hist(tmp_path)
    menu, page = h.open(by_keys=True)
    assert menu.scope.focused is h.g.button("history")
    marks: list = []
    real = Painter.triangle
    monkeypatch.setattr(Painter, "triangle", lambda self, box, color, **kw: (
        marks.append(box), real(self, box, color, **kw))[1])
    h.frame(H.key(pygame.K_RIGHT))
    h.frame()
    assert menu.scope.focused is page.list and page.list.focus_row == 2
    newest = page.list.row_box(2)
    assert any(m.x == newest.x + 12 and newest.y + 12 <= m.y < newest.y + 12 + P
               for m in marks)                             # the marker on its first line
    lst = page.list
    assert lst.on_nav(Nav.DOWN) is False
    h.frame(H.key(pygame.K_RETURN))                       # the newest row has no voice
    assert h.audio.replays == [] and menu.page is page
    assert lst.on_nav(Nav.UP) and lst.on_nav(Nav.UP) and lst.focus_row == 0
    assert lst.on_nav(Nav.UP) is False
    h2 = Hist(tmp_path / "mouse")
    menu2, page2 = h2.open(by_keys=False)
    assert menu2.scope.focused is not page2.list


# --- AC-F13-09 — wrapping ----------------------------------------------------------------------

def test_ac09_newlines_graphemes_and_replacement(tmp_path):
    """``\\n`` breaks; C0 controls and lone surrogates draw as U+FFFD; a 2,000-character
    word splits by grapheme within 696."""
    font = Game(tmp_path).shell.assets.font(None, 28).font
    assert wrap_history_text(font, "One\nTwo", TEXT_WIDTH) == ("One", "Two")
    assert wrap_history_text(font, "One\n\nTwo", TEXT_WIDTH) == ("One", "", "Two")
    assert wrap_history_text(font, "a\x01b\x7f\ud800c\td", TEXT_WIDTH) == (
        "a�b��c�d",)
    word = "é" * 1000                           # 2,000 code points, 1,000 graphemes
    lines = wrap_history_text(font, word, TEXT_WIDTH)
    assert len(lines) > 1 and "".join(lines) == word
    assert all(text_width(font, part) <= TEXT_WIDTH for part in lines)
    assert all(part.startswith("e") and part.endswith("́") for part in lines)
    wide = "W" * 2000
    lines = wrap_history_text(font, "Hi " + wide, TEXT_WIDTH)
    assert lines[0] == "Hi" and "".join(lines[1:]) == wide
    assert all(0 < text_width(font, part) <= TEXT_WIDTH for part in lines)


def test_ac09_lines_stay_within_the_width(tmp_path):
    """Greedy wrapping of plain prose at 28, then narrow and kerned words at 28 and 42."""
    assets = Game(tmp_path).shell.assets
    font = assets.font(None, 28).font
    text = long_text(400, seed=7)
    lines = wrap_history_text(font, text, TEXT_WIDTH)
    assert " ".join(lines) == text
    assert all(text_width(font, part) <= TEXT_WIDTH for part in lines)
    words = text.split(" ")
    # Greedy by the summed word widths: the next line's first word didn't fit (a kerned
    # line may draw a few units narrower than its sum, so a break comes early, never late).
    cache = word_cache(font)
    for a, b in zip(lines, lines[1:]):
        summed = sum(cache[w] + cache[" "] for w in (a + " " + b.split(" ")[0]).split(" "))
        assert summed - cache[" "] > TEXT_WIDTH - slack(len(a.split(" ")) + 1)
    assert len(words) == sum(len(part.split(" ")) for part in lines)
    pool = ["a", "i", "I", "l", "ll", "W", "WW", "AV", "To", "y.", '"Yes,"', "f", "...",
            "Wolkenkratzer", "—", "é", "1", "11"]
    for size in (28, 42):
        font = assets.font(None, size).font
        rng = random.Random(size)
        for _ in range(150):
            text = " ".join(rng.choice(pool) for _ in range(rng.randint(1, 150)))
            lines = wrap_history_text(font, text, TEXT_WIDTH)
            assert " ".join(lines) == text, size
            assert all(text_width(font, part) <= TEXT_WIDTH for part in lines), size


def test_ac09_a_reopen_with_one_new_entry_wraps_only_that_one(tmp_path):
    h = Hist(tmp_path)
    menu, page = h.open()
    wraps = h.ports.wraps
    first = wraps.wraps
    assert first == 5                                   # 3 texts, 2 names
    h.frame(H.key(pygame.K_ESCAPE))
    h.entries = h.entries + (line("h2", "Shall we go on?", "Hana"),)
    h.frame(H.key(pygame.K_RETURN))                     # History again (focused)
    assert menu.page is not page and wraps.wraps == first + 1
    assert [r.lines for r in menu.page.rows][-1] == ("Shall we go on?",)
    # A full history (same count) whose newest entry changed while open: new heights.
    page = menu.page
    h.entries = h.entries[1:] + (line("s9", "One\nTwo\nThree"),)
    h.frame()
    assert page.rows[-1].height == 24 + 3 * P
    assert page.list.row_box(3).h == 24 + 3 * P


# --- AC-F13-10 — the cost of a cold open -------------------------------------------------------

def test_ac10_cold_open_of_250_entries_of_150_characters(tmp_path):
    g = Game(tmp_path)
    painter = g.shell.painter
    painter.bind(g.h.canvas)
    rng = random.Random(3)
    entries = []
    for i in range(250):
        text = long_text(40, seed=i)[:150]
        entries.append(line(f"s{i}", text, rng.choice(["Hana", "Daichi", ""])))
    style = RowStyle.of(painter)
    layout_rows(entries[:1], style, g.shell.assets, HistoryWraps(), None)   # fonts loaded
    best = 1.0
    for _ in range(3):
        clear_word_cache()
        start = time.perf_counter()
        rows = layout_rows(entries, style, g.shell.assets, HistoryWraps(), None)
        best = min(best, time.perf_counter() - start)
    assert len(rows) == 250
    assert best <= 0.015, f"cold open took {best * 1000:.1f} ms"   # dev goal 3 ms (bench)


# --- AC-F13-11 — voice replay ------------------------------------------------------------------

def _icons(monkeypatch) -> list:
    boxes: list = []
    real = history_page.draw_speaker
    monkeypatch.setattr(history_page, "draw_speaker",
                        lambda p, box, color: (boxes.append(box), real(p, box, color))[1])
    return boxes


def test_ac11_voice_icons_and_replay(tmp_path, monkeypatch):
    voices = {"h1": "voice/hana_014.ogg", "q1": "voice/daichi_q.ogg"}
    h = Hist(tmp_path, voices=voices)
    menu, page = h.open()
    icons = _icons(monkeypatch)
    h.frame()
    rows = [page.list.row_box(i) for i in range(3)]
    assert [r.voice for r in page.rows] == ["voice/daichi_q.ogg", None, "voice/hana_014.ogg"]
    assert len(icons) == 2
    hana = icons[-1]
    assert (hana.right, hana.w, hana.h) == (rows[2].right - 32, 20, 20)
    assert hana.y == rows[2].y + 12 + (P - 20) / 2                 # on line 1 (the name)
    assert "q1" in h.asked and h.asked.count("q1") == 1        # the choice row never asks
    centre = rows[2].center
    h.frame(H.motion(centre))
    h.g.h.click(centre)
    assert h.audio.replays == ["voice/hana_014.ogg"]
    h.g.h.click(rows[1].center)                                  # the choice row: nothing
    assert h.audio.replays == ["voice/hana_014.ogg"]
    # Unknown sids and no audio: no icon and no call.
    h = Hist(tmp_path / "silent", voices={"h1": "voice/hana.ogg"}, audio=False)
    menu, page = h.open()
    icons = _icons(monkeypatch)
    h.frame()
    assert icons == [] and h.asked == [] and all(r.voice is None for r in page.rows)
    page.list.focus_row = 2
    page.list.activate()                                         # no audio: no call, no error
    h2 = Hist(tmp_path / "unknown", voices={})
    menu2, page2 = h2.open()
    icons2 = _icons(monkeypatch)
    h2.frame()
    page2.list.focus_row = 2
    page2.list.activate()
    assert icons2 == [] and h2.audio.replays == []


# --- AC-F13-12 — 150 % text ---------------------------------------------------------------------

def test_ac12_at_150_percent_rebuild_rewraps_with_the_bottom_row_anchored(tmp_path,
                                                                          monkeypatch):
    entries = [line(f"s{i}", long_text(20, seed=i), "Hana") for i in range(30)]
    h = Hist(tmp_path, entries)
    menu, page = h.open()
    lst = page.list
    lst.scroll = lst.max_scroll() / 2
    shown = list(lst.visible_range())
    anchor = shown[-1]
    below = lst.row_box(anchor).bottom - BODY.bottom
    monkeypatch.setattr(h.g.shell.painter, "_text_scale", lambda: 1.5)
    menu.rebuild()
    assert page.style.pitch == 59 and page.style.text_font.size == 42
    assert page.style.name_font.size == 42
    assert all(r.height == 24 + 59 * (len(r.lines) + 1) for r in page.rows)
    assert lst.row_box(anchor).bottom - BODY.bottom == pytest.approx(below)
    assert lst.box == BODY
    clips: list = []
    real = history_page.draw_history_row

    def spy(p, row, box, look, style):
        clips.append(p.canvas.surface.get_clip())
        real(p, row, box, look, style)

    monkeypatch.setattr(history_page, "draw_history_row", spy)
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    body_px = h.g.h.canvas.rect_to_px((BODY.x, BODY.y, BODY.w, BODY.h))
    assert clips and all(clip == body_px for clip in clips)
    rows = [c for c in calls if c.font.size == 42 and c.text != "History"]
    assert rows and all(c.bounds[2] <= TEXT_WIDTH for c in rows)
    # At the bottom, a rebuild stays at the bottom.
    h = Hist(tmp_path / "bottom", [line(f"s{i}", f"Line {i}.", "Hana") for i in range(30)])
    menu, page = h.open()
    monkeypatch.setattr(h.g.shell.painter, "_text_scale", lambda: 1.5)
    menu.rebuild()
    assert page.list.scroll == page.list.max_scroll() > 0
