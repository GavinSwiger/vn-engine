"""F37 S2 — achievements in the game: AC-F37-05 (the notice, with its icon, in the game and
on the title; two in order; the platform hook told after the notice) and AC-F37-08 (the
Extras entry shows once one is unlocked; the page scrolls by keys, Page Up/Down and the
wheel).

Every run is App A (F12's in-process launch, ``scripted_app``: fake frame clock at 1/60 s,
hidden window, dev), scripted frame by frame with a generator (``play``). The game has a
hook plugin in ``game/minigames/`` that writes each call to a file beside the game.
"""

import pygame
import pytest

from engine.app import cli
from engine.runtime.achievements import ACHIEVEMENT_KIND
from engine.ui.builtin.achievements_page import AchievementsPage
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.nav import InputKind
from engine.ui.shell import Mode
from tests.app.test_autosave_app import fake_dt
from tests.app.test_saves_service import line_text, play, unthreaded, wait
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display
__all__ = ["fake_dt", "unthreaded"]            # the fixtures, re-exported for pytest

CONFIG = '[game]\nid = "f37-achievements"\ntitle = "Achievements Test"\nversion = "1.0"\n\n' \
         '[textbox]\ncps = 0\n'
STORY = '''lock achievement first_steps "First Steps" "Finish the prologue." image ach first
lock achievement second "Second Wind"
lock achievement garden "Secret Garden" "Find the hidden garden." hidden
''' + "".join(f'lock achievement extra{i} "Extra {i}" "One more."\n' for i in range(12)) + '''
label start:
    "Start."
    unlock achievement first_steps
    unlock achievement second
    "Two."
'''
HOOK = '''from engine.minigames import api


class Hook:
    def started(self, unlocked):
        with open({path!r}, "a", encoding="utf-8") as f:
            f.write("started " + ",".join(unlocked) + "\\n")

    def unlocked(self, name):
        with open({path!r}, "a", encoding="utf-8") as f:
            f.write("unlocked " + name + "\\n")


api.register_achievement_hook(Hook())
'''


def game_of(tmp_path):
    game = tmp_path / "game"
    (game / "script").mkdir(parents=True)
    (game / "images" / "ach").mkdir(parents=True)
    (game / "minigames").mkdir()
    (game / "config.toml").write_text(CONFIG, encoding="utf-8")
    (game / "script" / "main.vns").write_text(STORY, encoding="utf-8")
    picture = pygame.Surface((64, 64))
    picture.fill((200, 120, 40))
    pygame.image.save(picture, str(game / "images" / "ach" / "first.png"))
    calls = tmp_path / "hook.txt"
    (game / "minigames" / "store_hook.py").write_text(HOOK.format(path=str(calls)),
                                                      encoding="utf-8")
    return game, calls


def on_title(app) -> bool:
    return (not app.loading and app.persist is not None and app.shell is not None
            and app.shell.mode is Mode.TITLE and isinstance(app.screens.top, TitleScreen))


def settle(n: int = 6):
    for _ in range(n):
        yield


def test_ac_f37_05_notice_with_icon_in_game_and_on_title(tmp_path, user_roots, scripted_app):
    """On the title, an unlock (Secret Garden, hidden: its real title) shows its notice
    there. Then New Game: the two unlock lines show two notices in line order,
    ``Achievement unlocked: First Steps`` with its picture (48×48 box) and ``Achievement
    unlocked: Second Wind`` without one; each is told to the hook after its notice. The
    hook's ``started`` came once, at launch, with what was on file (nothing)."""
    game, calls = game_of(tmp_path)

    def script(app, out):
        yield from wait(lambda: on_title(app))
        shell = app.shell
        notified: list = []
        real = shell.notify

        def spy(text, **kw):
            notified.append((text, kw.get("icon"), calls.read_text(encoding="utf-8")
                             if calls.exists() else ""))
            real(text, **kw)

        shell.notify = spy
        out["hook_at_title"] = calls.read_text(encoding="utf-8")
        app.persist.store.unlock(ACHIEVEMENT_KIND, "garden")
        yield from settle(2)
        out["title_notice"] = (shell.mode, list(notified))
        notified.clear()
        shell.start_new_game()
        yield from wait(lambda: line_text(app) == "Start.")
        yield from settle(2)
        post_key(pygame.K_SPACE)
        yield from wait(lambda: line_text(app) == "Two.")
        yield from settle()
        out["views"] = [(v.text, v.icon_box) for v in shell.notices.views()]
        out["in_game"] = list(notified)
        out["hook"] = calls.read_text(encoding="utf-8")

    out = play(scripted_app, script, last=600)
    assert cli.main(["run", str(game)]) == 0
    assert out["done"]
    assert out["hook_at_title"] == "started \n"
    in_game = out["in_game"]
    assert [t for t, _, _ in in_game] == ["Achievement unlocked: First Steps",
                                          "Achievement unlocked: Second Wind"]
    icon = in_game[0][1]
    assert icon is not None and icon.ref == "images/ach/first.png" and not icon.is_placeholder
    assert in_game[1][1] is None
    # Each notice came before the hook heard of its achievement.
    assert in_game[0][2] == "started \nunlocked garden\n"
    assert in_game[1][2] == "started \nunlocked garden\nunlocked first_steps\n"
    boxes = {text: box for text, box in out["views"]}
    box = boxes["Achievement unlocked: First Steps"]
    assert box is not None and (box.w, box.h) == (48, 48)
    assert boxes["Achievement unlocked: Second Wind"] is None
    mode, title_notice = out["title_notice"]
    assert mode is Mode.TITLE
    assert title_notice == [("Achievement unlocked: Secret Garden", None, "started \n")]
    assert out["hook"] == "started \nunlocked garden\nunlocked first_steps\nunlocked second\n"


def test_ac_f37_08_extras_entry_and_scrolling(tmp_path, user_roots, scripted_app):
    """No Achievements entry in Extras until one is unlocked; then it shows, and the page
    (15 rows, about 5 in view) scrolls by Down, Page Down, Page Up and the wheel."""
    game, _calls = game_of(tmp_path)

    def script(app, out):
        yield from wait(lambda: on_title(app))
        menus = app.shell.menus
        out["before"] = [e.id for e in menus.shown("extras")]
        app.persist.store.unlock(ACHIEVEMENT_KIND, "first_steps")
        yield from settle(3)
        out["after"] = [e.id for e in menus.shown("extras")]
        screen = app.shell.open_extras("achievements", by=InputKind.KEYS)
        yield from settle(12)
        assert isinstance(screen, GameMenuScreen)
        page = screen.page
        out["page"] = type(page)
        post_key(pygame.K_RIGHT)                        # into the page: the list
        yield from settle(2)
        scrolls = [page.list.scroll]
        for _ in range(8):
            post_key(pygame.K_DOWN)
            yield
        yield from settle(2)
        scrolls.append(page.list.scroll)
        post_key(pygame.K_PAGEDOWN)
        yield from settle(2)
        scrolls.append(page.list.scroll)
        post_key(pygame.K_PAGEUP)
        yield from settle(2)
        scrolls.append(page.list.scroll)
        page.list.scroll = 0.0
        out["wheel"] = page.on_mouse("wheel", (420, 200), notches=-1) and page.list.scroll > 0
        out["scrolls"] = scrolls

    out = play(scripted_app, script, last=400)
    assert cli.main(["run", str(game)]) == 0
    assert out["done"]
    assert "achievements" not in out["before"]
    assert "achievements" in out["after"]
    assert out["page"] is AchievementsPage
    s = out["scrolls"]
    assert s[0] == 0 and s[1] > 0 and s[2] > s[1] and s[3] < s[2]
    assert out["wheel"] is True
