"""F11 step 12: the save words (AC-F11-59) and ``[saves]`` with the save and notice theme
(AC-F11-60), from ``config.toml`` to what the engine shows (``04`` §13; 03-ui "Words").

The keys' defaults and their 200 / 1,000-character limits per key are ``test_config_f11``'s
(steps 5–6); the 22 ``[theme.save]`` and ``[theme.notice]`` ranges per token are there too.
Here each word set to ``ZZ<key>`` reaches the screen (the Save and Load pages on F10's game
rig over a fake port, the service's labels, notices, and confirm keys), and every ``[saves]``
row of AC-F11-60 loads as the table says.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from engine.app.saves import SaveService, SaveSlots
from engine.core.config_schema import SavesConfig
from engine.persist import saves
from engine.persist.saves import SlotId
from engine.ui.builtin.save_page import SlotView, register_save_pages
from engine.ui.theme import resolve_words
from tests.core.test_config_f11 import F11_WORDS, LINE2
from tests.fakes.draw_spy import spy_draw_text
from tests.persist import save_support as ss
from tests.ui.test_game_menu import Game
from tests.ui.test_save_page import FakePort, filled

REPO = Path(__file__).resolve().parents[2]
# The modules that show F11's words: the service (labels, notices, confirms), the pages,
# and F10's menus (the quick-menu entries).
SHOWN_BY = ("engine/app/saves.py", "engine/ui/builtin/save_page.py", "engine/ui/menus.py")
ZZ_WORDS = "[words]\n" + "".join(f'{key} = "ZZ{key}"\n' for key in F11_WORDS)


def _literals(ref: str) -> set[str]:
    tree = ast.parse((REPO / ref).read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
            and type(n.value) is str}


@pytest.fixture
def pygame_ready():
    """The page rig draws with fonts (tests/ui's conftest does this for screen tests)."""
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def _cell(pos: tuple[int, int]) -> int | None:
    """The grid cell (0–5) a text drawn at ``pos`` is in (06 §0.4 cell coordinates)."""
    x, y = pos
    for i in range(6):
        left, top = 416 + 276 * (i % 3), 112 + 241 * (i // 3)
        if left <= x < left + 256 and top <= y < top + 225:
            return i
    return None


def _shown_on_the_auto_page(tmp_path, monkeypatch) -> tuple[dict[int, list[str]], list[str]]:
    """F10's game rig with the ZZ words and F11's pages over a fake port: each cell's drawn
    texts (its label left out) for an Auto page holding every cell state, then the texts of
    a Load page with no saves."""
    game = Game(tmp_path, ZZ_WORDS)
    port = FakePort()
    port.data["auto"] = [filled(newest=True, thumb=None),
                         SlotView("Auto 2", "empty"),
                         SlotView("Auto 3", "damaged", deletable=True),
                         SlotView("Auto 4", "newer", deletable=True),
                         SlotView("Auto 5", "other_game", deletable=True),
                         SlotView("Auto 6", "loading")]
    register_save_pages(game.shell, port, can_save=lambda: True, visible=lambda: True)
    menu = game.open(game.h.key(pygame.K_ESCAPE))
    menu.open_page("load")
    game.frame()
    with spy_draw_text(monkeypatch) as calls:
        game.frame()
    cells: dict[int, list[str]] = {}
    for c in calls:
        i = _cell(c.pos)
        if i is not None and c.text != f"Auto {i + 1}":
            cells.setdefault(i, []).append(c.text)
    port.none = True
    with spy_draw_text(monkeypatch) as calls:
        game.frame()
    return cells, [c.text for c in calls]


# --- AC-F11-59: words -------------------------------------------------------------------------

def test_ac59_every_save_word_reaches_the_screen(load, tmp_path, monkeypatch,
                                                   pygame_ready):
    result = load(ZZ_WORDS)
    assert result.errors == [] and result.warnings == []
    words = resolve_words(result.config.words)
    assert {key: words.get(key) for key in F11_WORDS} == {key: f"ZZ{key}" for key in F11_WORDS}

    # The pages: every cell word and the no-saves message, where the defaults showed (a
    # word wider than its place is cut with "…" or wrapped, as the defaults would be).
    cells, empty = _shown_on_the_auto_page(tmp_path, monkeypatch)
    newest = [text for text in cells[0] if text.startswith("ZZsave_ne")]
    assert "ZZsave_no_picture" in cells[0] and len(newest) == 1
    assert newest[0].endswith("…") and "ZZsave_newest".startswith(newest[0][:-1])
    for i, key in enumerate(("save_empty", "save_damaged", "save_newer", "save_other_game",
                             "save_loading"), 1):
        assert "".join(cells[i]) == f"ZZ{key}", (key, cells[i])
    assert "ZZsave_none" in empty

    # The service: labels are word + space + number, failures word + space + word, and the
    # notices and confirms are the words themselves.
    shown: list[tuple[str, str]] = []
    shell = SimpleNamespace(words=words, notify=lambda text, kind: shown.append((text, kind)))
    service = SimpleNamespace(shell=shell, pages=10)
    assert [SaveService.slot_label(service, slot) for slot in
            (SlotId(3, 1), SlotId("auto", 2), SlotId("quick", 1))] == [
        "ZZsave_slot 1", "ZZsave_page_auto 2", "ZZsave_page_quick 1"]
    port = SaveSlots.__new__(SaveSlots)
    port.service = service
    assert [port.page_label(p) for p in ("auto", "quick", 3)] == [
        "ZZsave_page_auto", "ZZsave_page_quick", "3"]
    for reason in ("save_reason_disk_full", "save_reason_folder", "save_reason_other",
                   "save_reason_slots"):
        SaveService._notice_failed(service, reason)
        assert shown.pop() == (f"ZZnotice_save_failed ZZ{reason}", "problem")
    for key in ("notice_quick_saved", "notice_no_quick_save", "notice_cant_save",
                "notice_too_large", "notice_load_damaged", "notice_load_no_fit",
                "notice_load_failed", "notice_delete_failed"):
        SaveService._notice(service, key)
        assert shown.pop()[0] == f"ZZ{key}"
    for leaves, keys in ((True, ("confirm_main_menu_autosave", "confirm_quit_autosave")),
                         (False, ("confirm_main_menu", "confirm_quit"))):
        asker = SimpleNamespace(_leave_autosaves=lambda leaves=leaves: leaves)
        assert (SaveService._confirm_key(asker, "main_menu"),
                SaveService._confirm_key(asker, "quit")) == keys
    assert words.get("confirm_quit_autosave") == "ZZconfirm_quit_autosave"

    # Nothing shows a default as fixed text: every other key is looked up by name in the
    # modules that show it, and no default is written there.
    literals = set().union(*(_literals(ref) for ref in SHOWN_BY))
    looked_up = set(F11_WORDS) - {"confirm_main_menu_autosave", "confirm_quit_autosave"}
    assert looked_up <= literals, sorted(looked_up - literals)
    hard_coded = {key for key, default in F11_WORDS.items()
                  if default in literals and default not in ("Auto", "Quick", "Slot")}
    assert hard_coded == set(), sorted(hard_coded)

    # Too long: F01's config warning and the default.
    for key, limit in (("save_slot", 200), ("confirm_nearest", 1000)):
        result = load(f'[words]\n{key} = "{"x" * (limit + 1)}"\n')
        assert [e.format() for e in result.errors] == [
            f"{LINE2}[words] {key} must be text of at most {limit} characters, but found the "
            f'text "{"x" * 39}…"']
        assert getattr(result.config.words, key) == F11_WORDS[key]


# --- AC-F11-60: [saves] and the theme ---------------------------------------------------------

BAD_SAVES = [
    ("pages = 0", "[saves] pages must be a whole number from 1 to 100, but found 0"),
    ("pages = 101", "[saves] pages must be a whole number from 1 to 100, but found 101"),
    ('pages = "10"', '[saves] pages must be a whole number from 1 to 100, but found the text '
                     '"10". Remove the quotes.'),
    ("autosave_interval = 59", "[saves] autosave_interval must be a whole number: 0 (off) or "
                               "60–3600, but found 59"),
    ("autosave_interval = 3601", "[saves] autosave_interval must be a whole number: 0 (off) or "
                                 "60–3600, but found 3601"),
    ("autosave_interval = -1", "[saves] autosave_interval must be a whole number: 0 (off) or "
                               "60–3600, but found -1"),
    ("autosave_quit = 1", "[saves] autosave_quit must be true or false, but found 1"),
]
BAD_THEME = [
    ("save", "text_size", 23, 24, 36), ("save", "text_size", 37, 24, 36),
    ("notice", "max_width", 319, 320, 800), ("notice", "max_width", 801, 320, 800),
    ("notice", "duration_ms", 999, 1000, 10000), ("notice", "duration_ms", 10001, 1000, 10000),
    ("notice", "fade_ms", 1001, 0, 1000), ("save", "load_fade_ms", 2001, 0, 2000),
]


def test_ac60_saves_and_theme_configuration(load, tmp_path, monkeypatch):
    result = load("")
    assert result.config.saves == SavesConfig()
    assert (SavesConfig().pages, SavesConfig().autosave_interval) == (10, 300)
    assert SavesConfig().autosave_choices and SavesConfig().autosave_quit
    assert SavesConfig().confirm_quick_load

    for text, stored in (("pages = 1", 1), ("pages = 100", 100)):
        result = load(f"[saves]\n{text}\n")
        assert result.errors == [] and result.config.saves.pages == stored
    for seconds in (0, 60, 3600):
        result = load(f"[saves]\nautosave_interval = {seconds}\n")
        assert result.errors == [] and result.config.saves.autosave_interval == seconds

    for text, message in BAD_SAVES:
        result = load(f"[saves]\n{text}\n")
        assert [e.format() for e in result.errors] == [LINE2 + message], text
        assert result.config.saves == SavesConfig(), text            # the default is used
    for area, key, value, lo, hi in BAD_THEME:
        result = load(f"[theme.{area}]\n{key} = {value}\n")
        assert [e.format() for e in result.errors] == [
            f"{LINE2}[theme.{area}] {key} must be a whole number from {lo} to {hi}, but found "
            f"{value}"], (area, key, value)
        default = getattr(getattr(load("").config.theme, area), key)
        assert getattr(getattr(result.config.theme, area), key) == default

    # pages = 3 with page4-1.vnsave present: the rows end at page 3, and the file is not
    # shown, read, or deleted.
    folder = tmp_path / "saves"
    for slot in (SlotId(3, 1), SlotId(4, 1)):
        ss.write_slot(folder, ss.make_save(), slot)
    page4 = folder / "page4-1.vnsave"
    before = page4.read_bytes()
    read: list[str] = []
    real = saves.read_slot_head

    def spy(folder, slot, **kw):
        read.append(slot.file_name())
        return real(folder, slot, **kw)

    monkeypatch.setattr(saves, "read_slot_head", spy)
    config = load("[saves]\npages = 3\n").config
    service = SaveService(SimpleNamespace(config=config), SimpleNamespace(), folder=folder,
                          folder_ok=True, client=object(), release=False)
    heads = service.index.finish()
    assert service.slots.pages("load") == ["auto", "quick", 1, 2, 3]
    assert service.slots.pages("save") == [1, 2, 3]
    assert set(heads) == {SlotId(3, 1)} and read == ["page3-1.vnsave"]
    assert page4.read_bytes() == before
