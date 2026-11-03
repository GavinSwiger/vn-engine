"""F32 step 4: looks in the shell (``06-acceptance.md`` AC-F32-11, 12, 13, 15, 16, 17;
``04`` §6.2, §6.3, §6.6, §6.7).

Every launch is ``LookRig`` (``tests/ui/test_title_playthrough.py``): F10's title rig with
``install_looks`` between ``install_ui`` and ``check_entries``, a fake interpreter whose
persistent store holds ``persistent.playthrough``, and, where a row needs F11, a ``SavesSpy``
standing for ``App.saves`` (F11's own ``set_blocked``/``delete_all`` behavior is AC-F11-61).
"""

import logging
from pathlib import Path

import pygame
import pytest

from engine.app.looks import LookHandlers, read_playthrough
from engine.runtime.commands import DeleteSaves, StoryEnded, UiBlocks, UiStyle
from engine.runtime.ui import DELETE_PREVIEW_TEXT
from engine.runtime.values import kind_words
from engine.script.messages import format_message
from engine.script.ui import UiStatement
from engine.ui.looks import Looks
from engine.ui.shell import Mode
from tests.ui.test_title_playthrough import FakeStore, LookRig

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


class SavesSpy:
    def __init__(self) -> None:
        self.blocked: list[tuple[str | None, str | None]] = []
        self.deletes = 0

    def set_blocked(self, *, save, load) -> None:
        self.blocked.append((save, load))

    def delete_all(self) -> None:
        self.deletes += 1


def coded(caplog, code: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if getattr(r, "code", None) == code]


def style_line(name: str | None) -> UiStatement:
    return UiStatement(file="script/main.vns", line=5, end_line=5, column=4, form="style",
                       style=name)


# --- AC-F32-11 — launch checks: W207, W67, W66 ---------------------------------------------------

def test_ac_f32_11_launch_checks_w207_w67_w66(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    held: list[list[str]] = []

    def spy_hold(assets):
        real = assets.hold

        def hold(refs):
            refs = list(refs)
            held.append(refs)
            return real(refs)

        assets.hold = hold

    config = ('[style.calm.theme.textbox]\nframe_image = "gui/nope.png"\n'
              '[style.bad.theme.textbox]\nframe_image = "gui/bad.png"\n'
              '[style.ashes.theme.textbox]\nfill_color = "#1E1A1C"\ntext_color = "#202020"\n'
              '[style.framed.theme.textbox]\nfill_color = "#1E1A1C"\ntext_color = "#202020"\n'
              'frame_image = "gui/button.png"\n'
              '[style.box.theme.choice]\nfill_color = "#334455"\n'
              '[playthrough.2]\ntitle_entries = ["new_game", "nope"]\n'
              '[playthrough.2.theme.title]\nfill_top_color = "#336699"\n'
              '[playthrough.2.theme.title.logo]\ntext_color = "#336699"\n'
              '[playthrough.3.theme.title]\nbackground_image = "gui/title_bg.png"\n'
              'music = "nope.ogg"\n')
    rig = LookRig(tmp_path / "a", config, before_looks=spy_hold)
    w207 = coded(caplog, "W207")
    assert w207 == [format_message("W207", ("style.bad.theme.textbox", "frame_image",
                                            "gui/bad.png", "image", None)),
                    format_message("W207", ("style.calm.theme.textbox", "frame_image",
                                            "gui/nope.png", "missing", None))]
    assert "doesn't exist, so [theme.textbox] frame_image is used." in w207[1]
    assert "textbox.frame_image" not in rig.looks.styles["calm"].tokens    # [theme] value used
    w67 = coded(caplog, "W67")
    # Style order, then playthroughs; NVL colors follow the text box's (nvl_look); only the
    # pairs a table's tokens touch (box: the choice's plain fill, not its focused one).
    assert [t.split(" #", 1)[0] for t in w67] == [
        "config.toml: [style.ashes.theme.textbox] text_color",
        "config.toml: [style.ashes.theme.nvl] text_color",
        "config.toml: [style.box.theme.choice] text_color",
        "config.toml: [style.framed.theme.nvl] text_color",          # framed: no textbox row
        "config.toml: [playthrough.2.theme.title] logo.text_color"], w67
    assert coded(caplog, "W66") == [
        'config.toml: [playthrough.2] title_entries has "nope", which isn\'t a title-screen '
        'button. The buttons are new_game and quit.']
    assert held == [["gui/button.png"]]                   # non-title look images only, once
    assert len(rig.app.shutdown) == 1                      # released at shutdown
    # No launch warning for a look's music (F08's line when played); release: no W67.
    assert not any("nope.ogg" in r.getMessage() for r in caplog.records)
    caplog.clear()
    LookRig(tmp_path / "b", config, dev=False)
    assert coded(caplog, "W67") == []
    # The F32 Template U config unchanged: no W64, W66, W67, or W207.
    caplog.clear()
    template = (REPO / "tests" / "fixtures" / "F32" / "template" / "config.toml").read_text(
        encoding="utf-8")
    body = template.split("[theme.textbox]", 1)[1]
    body = body.replace('"gui/title_ashes.png"', '"gui/title_bg.png"').replace(
        '"gui/frame_calm.png"', '"gui/button.png"').replace(
        '["new_game", "settings", "quit"]', '["new_game", "quit"]')
    LookRig(tmp_path / "c", "[theme.textbox]" + body)
    assert [r for r in caplog.records
            if getattr(r, "code", None) in ("W64", "W66", "W207")] == []
    # 06 gap: Template U's calm choice fill #334455 under the default choice text #3D2B36 is
    # a real 1.1:1, so its one W67 is right (the 06 row expects none).
    assert [t.split(" #", 1)[0] for t in coded(caplog, "W67")] == [
        "config.toml: [style.calm.theme.choice] text_color"]


# --- AC-F32-12 — W206: an unused style -----------------------------------------------------------

def test_ac_f32_12_w206_unused_styles(tmp_path, caplog):
    config = ('[style.ashes.theme.textbox]\nfill_color = "#1E1A1C"\n'
              '[style.calm.theme.choice]\nfill_color = "#334455"\n'
              '[style.zeta.theme.textbox]\nborder_color = "#5A3848"\n'
              '[style.unused.theme.textbox]\nborder_color = "#5A3848"\n')
    LookRig(tmp_path / "a", config, statements=[style_line("ashes"), style_line(None)])
    assert coded(caplog, "W206") == [format_message("W206", (name,))
                                     for name in ("calm", "unused", "zeta")]
    assert coded(caplog, "W206")[1] == "config.toml: [style.unused] isn't used by any ui style line."
    caplog.clear()
    LookRig(tmp_path / "b", config, dev=False)
    assert coded(caplog, "W206") == []


# --- AC-F32-13 — the look is chosen at four moments only -----------------------------------------

LOOK2 = ('[playthrough.2.words]\nnew_game = "Again?"\n'
         '[playthrough.2.theme.title]\nfill_top_color = "#112233"\n')


def test_ac_f32_13_the_look_is_chosen_at_four_moments(tmp_path, caplog, monkeypatch):
    calls: list[int] = []
    real = Looks.choose
    monkeypatch.setattr(Looks, "choose", lambda self, p: (calls.append(p), real(self, p))[1])
    rig = LookRig(tmp_path / "a", LOOK2, playthrough=2)
    assert calls == [2, 2]                              # set_looks first, then the title
    assert rig.looks.key == (2, None)
    # Stored 0; mid-story the value becomes 2: nothing changes until a title opens.
    rig = LookRig(tmp_path / "b", LOOK2, playthrough=0)
    calls.clear()
    rig.shell.start_new_game()
    rig.frames(60)
    assert rig.shell.mode is Mode.GAME and calls == [0]          # before new_game()
    rig.values["playthrough"] = 2
    rig.frames(5)
    assert calls == [0] and rig.looks.key == (None, None)
    assert rig.shell.words.get("new_game") == "New Game"
    rig.shell.story_ended(StoryEnded())
    rig.frames(90)
    assert rig.shell.mode is Mode.TITLE and rig.looks.key == (2, None) and calls == [0, 2]
    # A load chooses before the in-game screens; a style restored after keeps the table.
    rig.values["playthrough"] = 0
    rig.shell.show_loaded_game()
    assert calls[-1] == 0 and rig.looks.key == (None, None)
    # Below every table, or negative: the base look.
    assert LookRig(tmp_path / "c", LOOK2, playthrough=-1).looks.key == (None, None)
    assert LookRig(tmp_path / "d", LOOK2, playthrough=1).looks.key == (None, None)
    # Not a whole number: 0, with W204 once a session, the kind in words only.
    caplog.clear()
    warned = [False]
    store = FakeStore({})
    kinds = []
    for value in ("two", True, 2.0, [2], "ZZMARK"):
        store.values["playthrough"] = value
        fresh = [False]
        assert read_playthrough(store, fresh) == 0
        kinds.append(coded(caplog, "W204")[-1])
        assert read_playthrough(store, warned) == 0
    assert kinds[:4] == [format_message("W204", (kind_words(v),)) for v in
                         ("two", True, 2.0, [2])]
    assert "text" in kinds[0] and "a decimal number" in kinds[2] and "a list" in kinds[3]
    assert len(coded(caplog, "W204")) == 5 + 1            # one per fresh session, one shared
    assert not any("ZZMARK" in r.getMessage() for r in caplog.records)


# --- AC-F32-15 — saving and loading blocked with a reason ----------------------------------------

STYLE_WORDS = ('[style.ashes.words]\nsaving_off = "Not now."\n'
               '[style.ashes.theme.textbox]\nfill_color = "#1E1A1C"\n')


def test_ac_f32_15_saving_and_loading_blocked_with_a_reason(tmp_path):
    saves = SavesSpy()
    rig = LookRig(tmp_path / "a", STYLE_WORDS, saves=saves)
    router = rig.app.router
    saves.blocked.clear()
    router.dispatch(UiBlocks(save=True, save_reason="There's nothing left to keep.",
                             load=False, load_reason=None))
    assert saves.blocked[-1] == ("There's nothing left to keep.", None)
    router.dispatch(UiBlocks(save=True, save_reason=None, load=True, load_reason=None))
    assert saves.blocked[-1] == ("Saving is turned off here.", "Loading is turned off here.")
    router.dispatch(UiStyle("ashes"))                      # re-applied on the switch
    assert saves.blocked[-1] == ("Not now.", "Loading is turned off here.")
    router.dispatch(UiStyle(None))
    assert saves.blocked[-1] == ("Saving is turned off here.", "Loading is turned off here.")
    rig.shell.start_new_game()                             # the in-game reset: nothing blocked
    rig.frames(60)
    assert saves.blocked[-1] == (None, None) and rig.looks.key[1] is None
    reason = "a {b" + "x" * 196
    router.dispatch(UiBlocks(save=True, save_reason=reason, load=False, load_reason=None))
    assert saves.blocked[-1] == (reason, None)                # drawn literally by F11
    # [words] saving_off is the game's own words.
    saves2 = SavesSpy()
    rig2 = LookRig(tmp_path / "b", '[words]\nsaving_off = "Closed."\n', saves=saves2)
    rig2.app.router.dispatch(UiBlocks(save=True, save_reason=None, load=False,
                                      load_reason=None))
    assert saves2.blocked[-1] == ("Closed.", None)
    # Without App.saves: nothing (and no error).
    LookRig(tmp_path / "c").app.router.dispatch(
        UiBlocks(save=True, save_reason=None, load=False, load_reason=None))


# --- AC-F32-16 — ui delete saves -----------------------------------------------------------------

def test_ac_f32_16_ui_delete_saves(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    saves = SavesSpy()
    rig = LookRig(tmp_path / "a", saves=saves)
    rig.app.router.dispatch(DeleteSaves())
    assert saves.deletes == 1
    assert not any(r.getMessage() == DELETE_PREVIEW_TEXT for r in caplog.records)
    # A Studio preview, and no App.saves: nothing deleted, one INFO line each.
    rig.app.editor_link = object()
    rig.app.router.dispatch(DeleteSaves())
    assert saves.deletes == 1
    LookRig(tmp_path / "b").app.router.dispatch(DeleteSaves())
    lines = [r for r in caplog.records if r.getMessage() == DELETE_PREVIEW_TEXT]
    assert len(lines) == 2 and all(r.levelno == logging.INFO for r in lines)
    assert DELETE_PREVIEW_TEXT == "ui delete saves: no saves are deleted in a preview."


# --- AC-F32-17 — error, crash, and settings rows are untouched -----------------------------------

def test_ac_f32_17_error_and_crash_screens_never_read_a_look(tmp_path):
    rig = LookRig(tmp_path, LOOK2 + STYLE_WORDS, playthrough=2)
    LookHandlers(rig.app, rig.looks).on_style(UiStyle("ashes"))
    assert rig.looks.key == (2, "ashes") and rig.shell.theme is not rig.shell.base_theme
    # C8: the error page, its look, and F30's crash page take nothing from the shell's look.
    for module in ("engine/ui/builtin/error.py", "engine/ui/builtin/error_look.py",
                   "engine/ui/builtin/fake_crash.py"):
        text = (REPO / module).read_text(encoding="utf-8")
        assert "looks" not in text and "shell.theme" not in text, module
    # The base theme the settings page and the error path use is the launch's own.
    assert rig.shell.base_theme.cfg.textbox.fill_color != (0x1E, 0x1A, 0x1C)
