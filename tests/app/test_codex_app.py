"""F21 step 3 — ``app/codex.py`` (``install_codex``, ``AppCodexPort``) and the page in the real
App: AC-F21-25 (its App rows), 30, 31, 32, 33.

Two App sessions (06 §0.3's cap): AC-30's (the game menu's Codex on the *Paper Lanterns*
walkthrough, ``walk/``, with a 1600×900 lantern picture) and AC-33's (the windowed command
list against ``run_headless``). Both use App A (``tests/fakes/text_app.Session``: the real
``App`` loop on a fake window and clock). The other rows build ``install_codex`` over a fake
App with a real ``MenuRegistry`` and a real interpreter (Run H's helpers)."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from engine.app.codex import AppCodexPort, install_codex, notice_text
from engine.app.dispatch import CommandRouter
from engine.core.config_schema import CodexConfig, Config, WordsConfig
from engine.runtime.commands import CodexAdded, StoryEnded
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageFile, ImageIndex, SolidColor
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.codex_page import CodexPage, CodexView
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.focus import Box, FocusScope
from engine.ui.menus import MenuEntry, MenuRegistry
from engine.ui.notice import NoticeLayer, NoticeStyle
from engine.ui.theme import Words, plain_theme
from tests.fakes.fixed_font import FixedFont, FixedFontAssets
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen
from tests.runtime.codex_story import (CA, F21, WALK_INPUTS, added, launched, load_c, started,
                                       store_with, to_text)
from tests.runtime.corpus import canon
from tests.runtime.effects_story import load_game

WALK = (F21 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")
INSTANT = "[textbox]\ncps = 0\n"
NO_ENTRIES = 'label start:\n    "Hello."\n'


@pytest.fixture
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def walk_game(root: Path, config: str = "") -> Path:
    root = make_text_game(root, script=WALK, config=INSTANT + config)
    gen.write(root, {"images/items/red_lantern.png": gen.block(1600, 900, (200, 40, 40))})
    return root


class FakeApp:
    """What ``install_codex`` uses of the App: router, config, shell (menus, words, notify),
    and the story driver's interpreter."""

    def __init__(self, interp, *, config: Config | None = None, title=None,
                 shell: bool = True) -> None:
        self.router = CommandRouter()
        self.config = config or Config()
        self.story = SimpleNamespace(interp=interp)
        self.notified: list[str] = []
        self.shell = SimpleNamespace(
            menus=MenuRegistry(entries={"title": title}), words=Words(self.config.words),
            notify=self.notified.append) if shell else None


def shown(registry: MenuRegistry, menu: str) -> list[str]:
    return [e.id for e in registry.shown(menu)]


# --- AC-F21-30 (App session 1) and its unit rows ------------------------------------------

@pytest.mark.display
def test_ac30_the_game_menu_entry(tmp_path, user_roots, pygame_ready):
    s = Session(walk_game(tmp_path / "g"))
    seen: dict = {}

    def menu() -> GameMenuScreen:
        top = s.app.screens.top
        assert isinstance(top, GameMenuScreen)
        return top

    def settle(n: int = 12):
        for _ in range(n):
            yield

    def script(s: Session):
        for _ in range(600):
            if s.line_text() == "The bridge.":
                break
            if s.frame % 4 == 0:
                s.key(pygame.K_SPACE)
            yield
        yield from settle(2)
        notices = s.app.shell.notices
        seen["notices"] = [v.text for v in notices.views()] + list(notices.waiting())
        interp = s.app.story.interp
        store = interp.persistent
        seen["before"] = interp.checkpoint().to_json()
        writes: list = []
        real_unlock = store.unlock
        store.unlock = lambda kind, name, **k: (writes.append((kind, name)),
                                                real_unlock(kind, name, **k))[1]
        s.key(pygame.K_ESCAPE)                                   # by keys: Return focused
        yield from settle()
        seen["labels"] = [b.label() for b in menu().buttons]
        s.key(pygame.K_DOWN)
        yield
        s.key(pygame.K_DOWN)
        yield
        s.key(pygame.K_RETURN)
        yield from settle(2)
        m = menu()
        page = m.page
        seen["page"] = (type(page), page.heading, s.app.shell.words.get(page.heading))
        view: CodexView = page.view
        seen["tabs"] = [t.label for t in view.tabs]
        seen["picture"] = view.layout.picture is None             # lanterns: no picture
        s.key(pygame.K_RIGHT)                                    # into the page: its default
        yield from settle(2)
        seen["focus"] = (m.scope.focused is view.list, view.list.focus_row, view.selected)
        seen["writes"] = list(writes)
        seen["after"] = interp.checkpoint().to_json()
        s.key(pygame.K_ESCAPE)                                   # Back: the page closes
        yield from settle(2)
        m = menu()
        seen["back"] = (m.page is None, m.scope.focused is m.button("codex"))
        x, y = m.button("codex").box.center
        s.event(pygame.MOUSEMOTION, pos=(round(x), round(y)), rel=(0, 0), buttons=(0, 0, 0))
        yield
        s.mouse((round(x), round(y)))
        yield
        s.mouse((round(x), round(y)), up=True)
        yield from settle(2)
        m = menu()
        widgets = [w for g in m.page_groups for w in g.widgets]
        seen["mouse"] = (type(m.page), m.scope.focused in widgets)
        view = m.page.view
        view._select_tab(1)                                      # Things: the lantern
        yield from settle(2)
        seen["lantern"] = (view.selected, view.layout.picture is not None,
                           store.is_unlocked("codex_read", "red_lantern"))
        s.key(pygame.K_ESCAPE)
        yield from settle(2)
        s.key(pygame.K_ESCAPE)
        yield from settle()

    s.play(script, last=900)
    assert seen["notices"] == ["New item: Red Lantern", "New tip: Paper Lanterns"]
    assert seen["labels"] == ["Return", "History", "Codex", "Save", "Load",   # App A: no F16
                              "Main Menu", "Quit"]
    assert seen["page"] == (CodexPage, "codex", "Codex")
    assert seen["tabs"] == ["Festival", "Things"] and seen["picture"]
    assert seen["focus"] == (True, 0, "lanterns")
    assert seen["writes"] == [("codex_read", "lanterns")]       # AC-25: the one write
    assert seen["after"] == seen["before"]
    assert seen["back"] == (True, True)
    assert seen["mouse"] == (CodexPage, False)                   # by mouse: nothing focused
    assert seen["lantern"] == ("red_lantern", True, True)


def test_ac30_unit_visibility(tmp_path):
    root = tmp_path / "none"
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(NO_ENTRIES, encoding="utf-8")
    empty = launched(load_game(root))
    app = FakeApp(empty)
    install_codex(app, empty)
    for entry_id in ("return", "history"):
        app.shell.menus.add("game", MenuEntry(entry_id))
    assert shown(app.shell.menus, "game") == ["return", "history"]
    program = load_c(tmp_path / "c")
    interp = launched(program)
    app = FakeApp(interp)
    calls: list[str] = []
    codex = interp.codex
    real_tips = codex.tips
    codex_spy = SimpleNamespace(index=codex.index,
                                tips=lambda: (calls.append("tips"), real_tips())[1])
    interp.codex = codex_spy                                     # what the callables read
    install_codex(app, interp)
    app.shell.menus.add("game", MenuEntry("history"))
    assert shown(app.shell.menus, "game") == ["history", "codex"]
    entry = app.shell.menus.entry("game", "codex")
    assert isinstance(entry.page(None), CodexPage) and not entry.page(None).from_title
    assert calls == []                                           # only the index was read
    app.shell.menus.entry("title", "codex").visible()
    assert calls == ["tips"]


# --- AC-F21-25's App rows: read marks kept across playthroughs ------------------------------

def test_ac25_read_marks_across_playthroughs(tmp_path):
    program = load_c(tmp_path, S="unlock item red_lantern")
    store = store_with()
    interp = started(program, store)
    to_text(interp, "Before.")
    port = AppCodexPort(lambda: interp.codex, None, show_locked=False)
    ui = SimpleNamespace(theme=plain_theme(), words=Words(), assets=FixedFontAssets())
    view = CodexView(port, ui=ui, scope=lambda: FocusScope())
    view.build(Box(416, 112, 808, 552), 1.0)
    assert view.selected == "red_lantern" and store.is_unlocked("codex_read", "red_lantern")
    interp.new_game(42)                                          # New Game: no items
    interp.run(10_000)
    assert interp.codex.items() == ()
    to_text(interp, "Before.")
    assert interp.codex.items() == ("red_lantern",) and port.is_read("red_lantern")
    store.reset()                                                # F16 "delete progress"
    assert not port.is_read("red_lantern")


# --- AC-F21-31 ------------------------------------------------------------------------------

def test_ac31_the_title_entry(tmp_path):
    program = load_c(tmp_path)
    listed = ("start", "load", "codex", "quit")
    for entries, tips, expected in ((None, ("lanterns",), False), ((), ("lanterns",), False),
                                    (listed, (), False), (listed, ("lanterns",), True)):
        interp = launched(program, store_with(tips))
        app = FakeApp(interp, title=entries)
        for entry_id in ("new_game", "load", "quit"):
            app.shell.menus.add("title", MenuEntry(entry_id))
        install_codex(app, interp)
        ids = shown(app.shell.menus, "title")
        assert ("codex" in ids) is expected, (entries, tips)
        if expected:
            assert ids == ["load", "codex", "quit"]              # third of the list
        assert "codex" in app.shell.menus.registered("title")    # so no W66 for it
    page = app.shell.menus.entry("title", "codex").page(None)
    assert isinstance(page, CodexPage) and page.from_title


# --- AC-F21-32 ------------------------------------------------------------------------------

def test_ac32_notices(tmp_path):
    interp = launched(load_c(tmp_path / "c"))
    rows = [((CA("tip", "lanterns"),), Config(), ["New tip: Paper Lanterns"]),
            ((CA("item", "red_lantern"),), Config(), ["New item: Red Lantern"]),
            ((CA("tip", "lanterns"),), Config(words=WordsConfig(codex_new_tip="TIPS")),
             ["TIPS: Paper Lanterns"]),
            ((CA("tip", "lanterns"),), Config(codex=CodexConfig(notify=False)), [])]
    for commands, config, expected in rows:
        app = FakeApp(interp, config=config)
        install_codex(app, interp)
        for cmd in commands:
            app.router.dispatch(cmd)
        assert app.notified == expected
    app = FakeApp(interp, shell=False)
    install_codex(app, interp)
    app.router.dispatch(CA("tip", "lanterns"))                   # no shell: nothing, no error
    # A title with "{{" reaches the notice as written: "A {b} lamp".
    lamp = load_c(tmp_path / "lamp", S="unlock tip lamp", T='lock tip lamp "A {{b} lamp"')
    commands = added(run_headless(lamp, seed=42, persistent=store_with()))
    app = FakeApp(interp)
    install_codex(app, interp)
    for cmd in commands:
        app.router.dispatch(cmd)
    assert app.notified == ["New tip: A {b} lamp"]
    # 20 in one burst: 20 notify calls; F11 shows 3 and keeps 10 waiting.
    layer = NoticeLayer(NoticeStyle(), lambda text, size: FixedFont(size).size(text)[0])
    app = FakeApp(interp)
    calls: list[str] = []
    app.shell.notify = lambda text: (calls.append(text), layer.notify(text, hold=False))
    install_codex(app, interp)
    for i in range(20):
        app.router.dispatch(CodexAdded("tip", f"t{i}", f"Tip {i}"))
    assert len(calls) == 20 and len(layer.views()) == 3 and len(layer.waiting()) == 10
    # Restore, load, and New Game release no further CA.
    run = started(load_c(tmp_path / "s", S="unlock tip lanterns"))
    first = to_text(run, "Before.")
    assert added(first) == [CA("tip", "lanterns")]
    state = run.checkpoint()
    run.restore(state)
    run.new_game(42)
    run.run(10_000)
    assert added(run.take_commands(1 << 30)) == []
    assert notice_text(Words(), CA("item", "brass_key")) == "New item: Brass Key"


def test_ac30_port_pictures():
    """§7.9: the port gives a file's ref, a solid color's RGB, or None."""
    images = ImageIndex({"items red_lantern": ImageFile("images/items/red_lantern.png"),
                         "black": SolidColor((0, 0, 0))})
    port = AppCodexPort(lambda: None, images, show_locked=True)
    assert (port.picture("items red_lantern"), port.picture("black"),
            port.picture("items gone")) == ("images/items/red_lantern.png", (0, 0, 0), None)
    assert AppCodexPort(lambda: None, None, show_locked=False).picture("black") is None


# --- AC-F21-33 (App session 2) --------------------------------------------------------------

@pytest.mark.display
def test_ac33_windowed_equals_headless(tmp_path, user_roots, pygame_ready):
    root = walk_game(tmp_path / "w", "[effects]\nreduce = false\n")
    expected = run_headless(load_game(root), seed=7, inputs=WALK_INPUTS,
                            persistent=store_with())
    s = Session(root, size=(640, 360))
    commands: list = []
    notified: list[str] = []

    def script(s: Session):
        router = s.app.router
        dispatch = router.dispatch

        def spy(command):
            commands.append(command)
            if not isinstance(command, StoryEnded):
                dispatch(command)

        router.dispatch = spy
        line, arrived = None, 0
        for _ in range(1500):
            yield
            if commands and isinstance(commands[-1], StoryEnded):
                return
            shell = s.app.shell
            if shell is not None and not notified and getattr(shell, "_spied", None) is None:
                real = shell.notify
                shell._spied = True
                shell.notify = lambda text, **k: (notified.append(text), real(text, **k))[1]
            if isinstance(s.app.screens.top, ChoiceScreen):
                if s.frame % 6 == 0:
                    s.key(pygame.K_1)
                continue
            text = s.line_text()
            if text != line:
                line, arrived = text, s.frame
            if text is not None and s.frame - arrived == 2:
                s.key(pygame.K_SPACE)
        raise AssertionError("the story did not end")

    s.play(script, last=1600)
    assert canon(commands) == canon(expected)
    assert added(expected) == [CA("item", "red_lantern"), CA("tip", "lanterns"),
                               CA("tip", "river_god")]
    assert notified == ["New item: Red Lantern", "New tip: Paper Lanterns",
                        "New tip: The River God"]
    shutil.rmtree(root)
