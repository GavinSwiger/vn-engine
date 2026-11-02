"""F13 step 3 in the real app (``scripted_app``): ``install_story`` wires ``install_history``
(I-6), whose ports read the live ``interp.history`` and the ``Program``'s voices
(``voice_of``). AC-F13-05's App rows (quick menu → History opens the menu on the page, Esc
closes the whole menu, nothing is posted and no checkpoint is taken while it is open) and
AC-F13-11's (a voiced row replays its file once through F08; a question uses the menu's
voice), with a *Paper Lanterns*-like festival scene (AC-F13-13's automated part).
"""

from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app.story import RuntimeStoryDriver
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.history_page import HistoryPage
from engine.ui.builtin.textbox_screen import TextboxScreen
from tests.app.test_ui_flow import _click
from tests.fakes.fake_mixer import ogg_bytes
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

SCRIPT = '''define hana = Character("Hana")
define daichi = Character("Daichi")
label start:
    voice "voice/hana_001.ogg"
    hana "The lanterns are lit."
    menu:
        voice "voice/daichi_q.ogg"
        daichi "Will you buy a lantern?"
        "The paper crane":
            voice "voice/hana_014.ogg"
            hana "A crane! Good choice."
        "Nothing":
            "Nothing."
    "The end."
    return
'''
VOICES = ("voice/hana_001.ogg", "voice/daichi_q.ogg", "voice/hana_014.ogg")


def make_game(root: Path) -> Path:
    (root / "script").mkdir(parents=True)
    (root / "config.toml").write_text('[game]\nid = "f13-step3"\n\n[title]\nenabled = false\n'
                                      '\n[textbox]\ncps = 0\n', encoding="utf-8")
    (root / "script" / "main.vns").write_text(SCRIPT, encoding="utf-8")
    for file in VOICES:
        path = root / "audio" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ogg_bytes(30.0, salt=file.encode()))
    return root


class Festival:
    """Plays to Hana's "A crane!" line (Space on lines, 1 on the menu), then runs ``steps``
    ((offset, action(app)), ...) counted from the frame that line shows."""

    def __init__(self, session, steps, *, last: int) -> None:
        self.session = session
        self.steps = steps
        self.start: int | None = None
        for frame in range(2, last):
            session.at(frame, self.tick)
        session.quit_frame = last

    def tick(self, app) -> None:
        frame = self.session.limiters[-1].frame
        if self.start is None:
            top = app.screens.top
            if isinstance(top, ChoiceScreen):
                if frame % 6 == 0:
                    post_key(pygame.K_1)
                return
            line = getattr(getattr(app, "textbox", None), "line", None)
            if not isinstance(top, TextboxScreen) or line is None:
                return
            if line.text != "A crane! Good choice.":
                if frame % 4 == 0:
                    post_key(pygame.K_SPACE)
                return
            self.start = frame
        for offset, action in self.steps:
            if frame == self.start + offset:
                action(app)


def test_quick_history_shows_the_festival_and_replays_hanas_voice(tmp_path, scripted_app,
                                                                   user_roots, monkeypatch):
    game = make_game(tmp_path / "game")
    posted: list = []
    real_post = RuntimeStoryDriver.post
    monkeypatch.setattr(RuntimeStoryDriver, "post",
                        lambda self, event: (posted.append(event), real_post(self, event))[1])
    seen: dict = {}

    def opened(app):
        menu = app.screens.top
        page = menu.page
        seen.update(types=[type(s) for s in app.screens], page=page, posted=len(posted),
                    checkpoint=app.story.checkpoint().to_json(),
                    rows=[(r.kind, r.name, r.lines, r.voice) for r in page.rows],
                    labels=[b.label() for b in menu.buttons],
                    plays=len(scripted_app.mixers[-1].actions("channel_play")),
                    voices=[args[1] for _, _, args in
                            scripted_app.mixers[-1].actions("channel_play") if args[0] == 0])

    def click_hana(app):
        x, y = seen["page"].list.row_box(3).center
        _click(app, pos=(round(x), round(y)))

    def replayed(app):
        plays = scripted_app.mixers[-1].actions("channel_play")[seen["plays"]:]
        seen["replays"] = [args[1] for _, _, args in plays if args[0] == 0]

    def closed(app):
        seen.update(after=[type(s) for s in app.screens], after_posted=len(posted),
                    after_checkpoint=app.story.checkpoint().to_json())

    Festival(scripted_app, [
        (2, lambda app: _click(app, "history")),
        (4, opened),
        (5, click_hana),
        (7, replayed),
        (8, lambda app: post_key(pygame.K_ESCAPE)),
        (24, closed),
    ], last=160)
    assert bootstrap.launch(game, release=True, bench_seconds=None, log_level_override=None,
                            pygame_warning=None) == 0
    assert seen["types"][-1] is GameMenuScreen and isinstance(seen["page"], HistoryPage)
    assert seen["labels"] == ["Return", "History", "Save", "Load", "Settings", "Main Menu",
                              "Quit"]   # F11 step 9 adds Save and Load
    assert seen["rows"] == [
        ("line", "Hana", ("The lanterns are lit.",), "voice/hana_001.ogg"),
        ("line", "Daichi", ("Will you buy a lantern?",), "voice/daichi_q.ogg"),
        ("choice", "", ("The paper crane",), None),
        ("line", "Hana", ("A crane! Good choice.",), "voice/hana_014.ogg")]
    # The fake mixer names a sound by its bytes: the line voices played in order (Hana,
    # the question, Hana's crane line), and the replay is the last one's file again.
    assert len(seen["voices"]) == 3 and len(set(seen["voices"])) == 3
    assert seen["replays"] == [seen["voices"][-1]]
    assert GameMenuScreen not in seen["after"]                 # Esc closed the whole menu
    assert seen["after_posted"] == seen["posted"]              # nothing posted while open
    assert seen["after_checkpoint"] == seen["checkpoint"]      # no checkpoint taken
