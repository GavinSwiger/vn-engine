"""F18 step 3 in the real app (App S: an in-process ``launch()``, fake frame clock, unthreaded
writer): ``install_chapters`` wires the card painter, ``ChapterStarted`` → F11's
``request_autosave()``, ``[chapter] autosave``/``name_saves``, and W111.

One test per AC: AC-F18-06 (saves and loads around the card), AC-F18-07 (the chapter Auto
save), AC-F18-09 (skip, auto, reduced effects), AC-F18-11 (config and W111). The rollback
rows of AC-F18-06/07 (I-6) wait for F14's restore. AC-F18-04's card timing in the app is
``tests/ui/test_chapter_card_app.py``.
"""

from dataclasses import replace

import pygame
import pytest

from engine.app.chapters import card_ratio, contrast_warnings
from engine.core.config_schema import ChapterTheme
from engine.persist.saves import SlotId
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.title_card import CardPainter
from engine.ui.builtin.title_screen import TitleScreen
from tests.app.test_autosave_app import advance, autos
from tests.app.test_saves_service import (at_line, full, launch, line_text, make_game, play,
                                          unthreaded, wait)
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

HEAD = ('image bg a = "#c82800"\nimage bg b = "#0050f0"\nlabel start:\n    scene bg a\n'
        '    "L1"\n    scene bg b\n')
SCRIPT = HEAD + '    chapter c "H" "T"\n    "L2"\n    "L3"\n    "L4"\n    return\n'
MENU_AFTER = HEAD + ('    chapter c "H" "T"\n    "L2"\n    menu:\n        "Pick"\n'
                     '        "A":\n            "A."\n    return\n')
NO_ASK = "[saves]\nconfirm_quick_load = false\n"


def game_with(root, script: str = SCRIPT, config: str = NO_ASK):
    game = make_game(root, config)
    (game / "script" / "main.vns").write_text(script, encoding="utf-8")
    return game


def spy_paints(app) -> list:
    """The name of every card the painter paints from now on."""
    painter = app.stage_screen.view.card_painter
    assert isinstance(painter, CardPainter)
    painted: list = []
    real = painter.paint

    def paint(canvas, card):
        painted.append(card.name)
        real(canvas, card)

    painter.paint = paint
    return painted


def interp(app):
    return app.story.interp


def into_card(app, presses: int):
    """From a fully shown "L1": the press that starts the card, then ``presses`` more (one
    finishes the way in, two also end the hold), each a few frames apart."""
    yield from wait(lambda: at_line(app, "L1") and app.textbox.typer.state.name == "COMPLETE")
    for _ in range(presses + 1):
        post_key(pygame.K_SPACE)
        for _ in range(4):
            yield


def advance_to(app, pred):
    while not pred():
        post_key(pygame.K_SPACE)
        yield
        yield


def chapter_metas(game) -> list:
    return [full(game, SlotId("auto", n)).meta.chapter for n in range(1, 7)
            if full(game, SlotId("auto", n)).status.name == "OK"]


# --- AC-F18-06: saving and loading around the card ------------------------------------------------

def test_ac_f18_06_save_and_load_in_each_phase(tmp_path, scripted_app, unthreaded):
    """In each phase (in, hold, out): a quick save stores "L1" with the old chapter; loading
    it brings "L1" back with no card drawn, the stale waits ignored (the story stays at
    "L1"), ``wait_then``/``card_shown`` cleared, no request and no Auto save; advancing
    replays the card, and its Auto save follows at "L2"."""
    for presses, phase in ((0, "in"), (1, "hold"), (2, "out")):
        game = game_with(tmp_path / phase)

        def script(app, out, presses=presses):
            yield from into_card(app, presses)
            out["wait"] = app.stage_screen.wait_kind
            app.saves.quick_save()
            for _ in range(3):
                yield
            painted = spy_paints(app)
            app.saves.quick_load()
            yield from wait(lambda: app.saves.loading_slot is None)
            yield from wait(lambda: at_line(app, "L1"))
            for _ in range(30):
                yield
            out["line"] = line_text(app)
            out["painted"] = list(painted)
            out["cleared"] = (interp(app).wait_then, interp(app).card_shown,
                              app.stage_screen.view.card)
            out["pending"] = app.saves.autosave_pending
            out["autos_at_l1"] = autos(game)
            out["chapter_at_l1"] = interp(app).chapter
            yield from advance(app, "L2")
            out["replayed"] = "c" in painted
            out["autos"] = autos(game)

        out = play(scripted_app, script, last=900)
        assert launch(game) == 0
        assert out["wait"] == ("timed" if phase == "hold" else "stage"), phase
        head = full(game, SlotId("quick", 1))
        assert head.meta.description == "L1" and head.meta.chapter is None, phase
        assert out["line"] == "L1" and out["painted"] == [], phase
        assert out["cleared"] == (None, None, None), phase
        assert out["pending"] is False and out["autos_at_l1"] == [], phase
        assert out["chapter_at_l1"] is None, phase
        assert out["replayed"] and out["autos"] == ["H: T"], phase


# --- AC-F18-07: the chapter Auto save -------------------------------------------------------------

def test_ac_f18_07_one_auto_save_at_the_next_checkpoint(tmp_path, scripted_app, unthreaded):
    two = HEAD + '    chapter c "H" "T"\n    chapter d "Second"\n    "L2"\n    "L3"\n    return\n'
    menu_first = HEAD + ('    chapter c "H" "T"\n    menu:\n        "Pick"\n        "A":\n'
                         '            "A."\n    return\n')
    rows = [  # id, script, config, the Auto saves' descriptions, their chapter meta
        ("one", SCRIPT, "", ["H: T"], ["H: T"]),
        ("menu", menu_first, "[saves]\nautosave_choices = false\n", ["H: T"], ["H: T"]),
        ("two_chapters", two, "", ["Second"], ["Second"]),
        ("autosave_off", SCRIPT, "[chapter]\nautosave = false\n", [], []),
        ("name_saves_off", SCRIPT, "[chapter]\nname_saves = false\n", ["L2"], [None]),
    ]
    for name, text, config, made, metas in rows:
        game = game_with(tmp_path / name, text, config)

        def script(app, out, text=text, game=game):
            yield from wait(lambda: at_line(app, "L1"))
            if text is menu_first:
                yield from advance_to(app, lambda: isinstance(app.screens.top, ChoiceScreen))
                for _ in range(4):
                    yield
                out["at"] = out["after"] = autos(game)
                out["pending"] = app.saves.autosave_pending
                return
            yield from advance(app, "L2")
            out["at"] = autos(game)
            out["pending"] = app.saves.autosave_pending
            yield from advance(app, "L3")
            out["after"] = autos(game)

        out = play(scripted_app, script, last=600)
        assert launch(game) == 0
        assert out["at"] == made and out["after"] == made, name
        assert out["pending"] is False, name
        assert chapter_metas(game) == metas, name

    # Main Menu → Yes during the card: the request goes with the game (I-6); New Game from
    # the title draws no card until the chapter line runs again (AC-F18-06's New Game row).
    game = game_with(tmp_path / "title")
    config = (game / "config.toml").read_text(encoding="utf-8")
    (game / "config.toml").write_text(config.replace("[title]\nenabled = false\n", ""),
                                      encoding="utf-8")

    def to_title(app, out):
        yield from wait(lambda: isinstance(app.screens.top, TitleScreen))
        app.shell.start_new_game()
        yield from into_card(app, 1)
        out["pending_in_card"] = app.saves.autosave_pending
        app.shell.return_to_title()
        yield from wait(lambda: isinstance(app.screens.top, TitleScreen))
        out["pending_title"] = app.saves.autosave_pending
        painted = spy_paints(app)
        app.shell.start_new_game()
        yield from wait(lambda: at_line(app, "L1"))
        for _ in range(10):
            yield
        out["painted"] = list(painted)
        out["cleared"] = (interp(app).wait_then, interp(app).card_shown)

    out = play(scripted_app, to_title, last=900)
    assert launch(game) == 0
    assert out["pending_in_card"] is True and out["pending_title"] is False
    assert out["painted"] == [] and out["cleared"] == (None, None)
    assert autos(game) == []


# --- AC-F18-09: skip, auto, reduced effects -------------------------------------------------------

def test_ac_f18_09_skip_auto_and_reduced_effects(tmp_path, scripted_app, unthreaded):
    """Skip-all calls ``finish_now`` once per phase, draws the card, and reaches the menu
    with the ``GameState`` of a click-through (but the seed's dice); auto waits out the
    3.0 s hold; reduced effects play a card transition that isn't calm as a dissolve both
    ways. The engine's kinds today (``cut``, ``dissolve``, ``fade``) are all calm, so the
    card's ``fade`` marked not calm stands in for F28's ``wipeleft``."""
    from engine.runtime import chapters as runtime_chapters

    runs = {}
    for mode in ("click", "skip"):
        game = game_with(tmp_path / mode, MENU_AFTER, "[skip]\nall = true\n")

        def script(app, out, mode=mode):
            yield from wait(lambda: at_line(app, "L1"))
            stage = app.stage_screen
            waits: list = []
            real = stage.finish_now

            def finish_now():
                if type(interp(app).current).__name__ == "Chapter":
                    waits.append(stage.wait_kind)
                real()

            stage.finish_now = finish_now
            painted = spy_paints(app)
            if mode == "skip":
                app.skip_auto.start_skip()
                yield from wait(lambda: isinstance(app.screens.top, ChoiceScreen))
            else:
                yield from advance_to(app, lambda: isinstance(app.screens.top, ChoiceScreen))
            for _ in range(3):
                yield
            out["phases"] = waits
            out["painted"] = "c" in painted
            state = app.story.checkpoint().to_json()
            state.pop("dice")
            out["state"] = state
            out["card"] = app.stage_screen.view.card

        runs[mode] = play(scripted_app, script, last=900)
        assert launch(game) == 0
    click, skip = runs["click"], runs["skip"]
    assert skip["phases"] == ["stage", "timed", "stage"] and click["phases"] == []
    assert skip["painted"] and skip["card"] is None
    assert skip["state"] == click["state"] and skip["state"]["chapter"] == {"current": "c"}

    game = game_with(tmp_path / "auto")

    def auto(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        app.skip_auto.set_auto(True)
        timed = 0
        while line_text(app) != "L2":
            yield
            timed += app.stage_screen.wait_kind == "timed"
        out["timed"] = timed

    out = play(scripted_app, auto, last=900)
    assert launch(game) == 0
    assert 178 <= out["timed"] <= 184                    # 3.0 s at 60 fps (frame hand-offs)

    real_transition = runtime_chapters.card_transition

    def not_calm(interp_, clause, sid):
        spec = real_transition(interp_, clause, sid)
        return None if spec is None else replace(spec, calm=False)

    for reduce, kind in ((True, "dissolve"), (False, "fade")):
        game = game_with(tmp_path / f"reduce_{reduce}", SCRIPT,
                         f"[effects]\nreduce = {str(reduce).lower()}\n")

        def reduced(app, out):
            yield from wait(lambda: at_line(app, "L1"))
            view = app.stage_screen.view
            kinds: list = []
            real = view._plan

            def plan(spec, *args):
                found = real(spec, *args)
                kinds.append(None if found is None else found[0])
                return found

            view._plan = plan
            yield from advance(app, "L2")
            out["kinds"] = kinds

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(runtime_chapters, "card_transition", not_calm)
            out = play(scripted_app, reduced, last=900)
            assert launch(game) == 0
        assert out["kinds"] == [kind, kind], reduce


# --- AC-F18-11: config and W111 -------------------------------------------------------------------

def test_ac_f18_11_config_tokens_and_w111(tmp_path):
    from itertools import count

    from engine.core.config import load_config
    from engine.core.paths import GamePaths

    folders = count()

    def load(text: str):
        root = tmp_path / f"cfg{next(folders)}"
        root.mkdir()
        (root / "config.toml").write_text(text, encoding="utf-8")
        return load_config(GamePaths.for_game(root))

    result = load("")
    assert result.errors == [] and result.warnings == []
    config = result.config
    assert (config.chapter.autosave, config.chapter.name_saves) == (True, True)
    assert config.theme.chapter == ChapterTheme()
    result = load('[chapter]\nautosave = "x"\n')
    assert [e.format() for e in result.errors] == [
        'config.toml, line 2: [chapter] autosave must be true or false, but found the text "x"']
    assert result.config.chapter.autosave is True
    # Token ranges (SPEC §4): each bound loads, one past it is an error that keeps the default.
    for key, default, lo, hi in (("heading.text_size", 32, 20, 64),
                                 ("title.text_size", 56, 24, 96),
                                 ("gap", 16, 0, 64), ("max_width", 1040, 400, 1240)):
        *tables, name = key.split(".")
        table = ".".join(["chapter", *tables])
        for value, ok in ((lo, True), (hi, True), (lo - 1, False), (hi + 1, False)):
            result = load(f"[theme.{table}]\n{name} = {value}\n")
            got = result.config.theme.chapter
            for part in key.split("."):
                got = getattr(got, part)
            assert (result.errors == []) is ok and got == (value if ok else default), key
    # W111: none at the defaults (title 15.0:1, heading 8.1:1); 2.1:1 warns; a translucent
    # fill is measured over black and over white.
    cfg = ChapterTheme()
    assert card_ratio(cfg, "title") == pytest.approx(15.0, abs=0.15)
    assert card_ratio(cfg, "heading") == pytest.approx(8.1, abs=0.15)
    assert contrast_warnings(cfg) == []
    dim = replace(cfg, title=replace(cfg.title, text_color=(0x60, 0x50, 0x5A)))
    assert contrast_warnings(dim) == [
        'config.toml: [theme.chapter] title.text_color "#60505A" has a contrast of 2.1:1 on '
        "the chapter card, under 4.5:1, so players may not read it."]
    assert len(contrast_warnings(replace(cfg, fill_opacity=0.3))) == 2
