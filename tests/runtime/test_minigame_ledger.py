"""F23 s4 — ``MinigameLedger`` (``04`` §7.3): AC-F23-25, unit. The ledger is pure; its
preview must equal what the runtime's real ``Points``/``Codex`` make of ``changes``."""

import random
import threading

import pygame
import pytest

from engine.core.minigame_types import CodexChange, MeterChange
from engine.minigames.host import LedgerCodexPort
from engine.runtime.codex import READ_KIND, TIP_KIND, Codex, CodexIndex
from engine.runtime.commands import MeterView, MinigameBase
from engine.runtime.minigame import MinigameLedger, entry_check
from engine.runtime.persistent import PersistentStore
from engine.runtime.points import Points
from engine.script.codex import CodexCategory, CodexEntry
from engine.script.points import MeterSpec
from engine.ui.builtin.codex_page import CodexFilter, CodexView
from engine.ui.focus import Box
from engine.ui.theme import Words, plain_theme
from tests.render.conftest import make_assets

ITEMS = CodexCategory("item", None, "codex_items")
TIPS = CodexCategory("tip", None, "codex_tips")


def _entry(name: str, kind: str) -> CodexEntry:
    return CodexEntry(name, kind, name.title(), ITEMS if kind == "item" else TIPS, None, (),
                      "s", "script/main.vns", 1)


INDEX = CodexIndex((_entry("coin", "item"), _entry("lantern", "item"),
                    _entry("paper", "item"), _entry("moon", "tip"),
                    _entry("lanterns", "tip")), (ITEMS, TIPS))
SPEC = MeterSpec("hana", 0, 10, 0, True)


def ledger(base: MinigameBase | None = None) -> MinigameLedger:
    points = Points((SPEC,))
    base = base or MinigameBase((MeterView("hana", 0, 0, 10),), ("coin",), ("moon",))
    return MinigameLedger(base, check_meter=points.spec, check_entry=entry_check(INDEX),
                          game="probe")


class UiBits:
    def __init__(self) -> None:
        self.theme = plain_theme()
        self.words = Words()
        self.assets = make_assets(None)


@pytest.fixture
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


def test_ac25_seeing_your_own_changes(pygame_ready):
    led = ledger()
    assert led.add("hana", 2) == 2 and led.meter("hana") == 2
    assert led.set("hana", 12) == 10 and led.meter("hana") == 10
    led.give("lantern")
    assert led.items()[-1] == "lantern"
    port = LedgerCodexPort(threading.get_ident(), led, INDEX, is_read=lambda n: False,
                           mark_read=lambda n: None, picture=lambda i: None,
                           show_locked=False)
    view = CodexView(port, ui=UiBits(), filter=CodexFilter(frozenset({"item"})))
    view.build(Box(0, 0, 808, 552), 1.0)
    assert [row.entry.name for tab in view.tabs for row in tab.rows] == ["coin", "lantern"]
    led.take("coin")
    assert "coin" not in led.items()
    led.unlock_tip("lanterns")
    assert "lanterns" in led.tips() and led.has("lanterns") and led.has("tip", "moon")
    assert led.changes == (MeterChange("hana", "+=", 2), MeterChange("hana", "=", 12),
                           CodexChange("give", "lantern"), CodexChange("take", "coin"),
                           CodexChange("unlock_tip", "lanterns"))
    # 20 random request sequences: the real Points/Codex from the base equal the preview.
    rng = random.Random(3)
    names = ("coin", "lantern", "paper")
    for _ in range(20):
        led = ledger()
        for _ in range(rng.randint(0, 50)):
            pick = rng.randrange(5)
            if pick == 0:
                led.add("hana", rng.randint(-15, 15))
            elif pick == 1:
                led.set("hana", rng.randint(-5, 15))
            elif pick == 2:
                led.give(rng.choice(names))
            elif pick == 3:
                led.take(rng.choice(names))
            else:
                led.unlock_tip(rng.choice(("moon", "lanterns")))
        points = Points((SPEC,))
        store = PersistentStore(identity_scheme=1)
        store.register_kind(TIP_KIND, known=INDEX.is_tip, revocable=True)
        store.register_kind(READ_KIND, known=INDEX.has)
        codex = Codex(INDEX, store, lambda cmd: None)
        codex.give("coin")
        codex.unlock_tip("moon")
        for change in led.changes:
            if type(change) is MeterChange:
                points.change(change.name, change.op, change.amount)
            else:
                getattr(codex, change.verb)(change.name)
        assert points.get("hana") == led.meter("hana")
        assert codex.items() == led.items()
        assert set(codex.tips()) == set(led.tips())
