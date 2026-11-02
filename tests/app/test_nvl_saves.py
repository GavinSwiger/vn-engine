"""F17 step 5 — save mid-page, quit, load, with F11's real quick save and load (F17
``06-acceptance.md`` AC-F17-36; ``04-technical.md`` §4, §10).

Every run is an in-process ``launch()`` (``scripted_app``: fake clock at 1/60 s, hidden window
1280×720, dev, unthreaded writer) of Template N (``06`` §0.4) at 40 cps, scripted frame by
frame (``tests/app/test_saves_service.play``). Each relaunch quick-loads the newest quick save
(F9, then Yes), so the four runs are: save while line 10 types; load it, play to the menu,
save; load it, pick, play to line 23, save; load it.
"""

import json
from pathlib import Path

import pygame
import pytest

from engine.persist import saves
from engine.persist.saves import SlotStatus
from engine.render.typewriter import TypeState
from engine.runtime.nvl import EMPTY_NVL
from engine.ui.builtin.choice_screen import ChoiceScreen
from tests.app.test_saves_service import file_of, launch, line_text, play, textbox, unthreaded, wait
from tests.app.test_saves_signoff_app import advance_until, pick_first
from tests.fakes.loop import post_key
from tests.persist import save_support as ss
from tests.script.helpers import template_n

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

GAME_ID = "f17-saves"
CONFIG = f"""[game]
id = "{GAME_ID}"
title = "NVL Saves"
version = "1.0"

[title]
enabled = false

[saves]
autosave_quit = false

[textbox]
cps = 40
"""
RED = (255, 0, 0)
L8 = "The festival comes once a year."
L9 = "You're thinking about last year again."
L10 = "I didn't answer."
L12 = "Three days later, a lantern came."
L14 = "It was a letter."
L15 = "Will you open it?"
L23 = "Back in the box."
# Lines 10 and 12 as written (``Say.text`` keeps the tags).
T10 = "I didn't{pause=0.5} answer."
T12 = "Three days later, {var=wish} came."


def n_game(root: Path) -> Path:
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(template_n(), encoding="utf-8")
    (root / "config.toml").write_text(CONFIG, encoding="utf-8")
    (root / "images").mkdir()
    red = pygame.Surface((1280, 720))
    red.fill(RED)
    pygame.image.save(red, str(root / "images" / "red.png"))
    return root


def page(app) -> list[tuple[str, float]]:
    """(record text, y) of every row the NVL page shows."""
    nvl = textbox(app).nvl
    return [("".join(span.text for span in nvl.entries[r.entry].spans), r.y)
            for r in nvl.rows()]


def quick_load(app, done):
    """F9, then Yes; ends in the first frame where ``done()`` holds after the load."""
    post_key(pygame.K_F9)
    yield
    post_key(pygame.K_LEFT)                                    # to Yes
    yield
    post_key(pygame.K_RETURN)
    yield
    yield from wait(done)


def quick_save(app, game: Path, n: int, out: dict, key: str):
    out[key] = app.story.checkpoint()
    post_key(pygame.K_F5)
    yield from wait(lambda: file_of(game, f"quick-{n}.vnsave").is_file())


def restored_at(app, text: str) -> bool:
    box = textbox(app)
    return box is not None and box.line is not None and box.line.restored \
        and box.line.text == text


def at_menu(app) -> bool:
    choices = getattr(app, "choices", None)
    return isinstance(app.screens.top, ChoiceScreen) and choices is not None \
        and choices.screen is not None and choices.screen.started


def read_quick(game: Path, n: int) -> tuple[saves.FullRead, dict]:
    data = file_of(game, f"quick-{n}.vnsave").read_bytes()
    read = saves.parse_full(data, game_id=GAME_ID)
    assert read.status is SlotStatus.OK, read.reason
    return read, json.loads(ss.lines(data)[2])


# --- AC-F17-36 — save mid-page, quit, load (F11) ---------------------------------------------------

def test_ac_f17_36_save_mid_page_quit_load(tmp_path, scripted_app, unthreaded):
    game = n_game(tmp_path / "game")

    def save_while_typing(app, out):                           # run 1
        yield from wait(lambda: textbox(app) is not None and line_text(app) is not None)
        box = textbox(app)
        yield from advance_until(app, lambda: line_text(app) == T10)
        yield from wait(lambda: box.shown_count() >= 2)
        out["typing"] = box.typer.state is not TypeState.COMPLETE
        yield from quick_save(app, game, 1, out, "cp10")

    def load_line_10_then_save_at_the_menu(app, out):         # run 2
        yield from wait(lambda: line_text(app) == "Before.")
        yield from quick_load(app, lambda: restored_at(app, T10))
        box = textbox(app)
        out["first"] = (box.nvl_on, page(app), box.typer.state, box.indicator_kind(),
                        app.story.checkpoint().to_json())
        yield from wait(lambda: app.screens.top is box)        # the question has gone
        for _ in range(30):                                    # and the load fade
            yield
        post_key(pygame.K_SPACE)                               # one press: line 12
        for _ in range(30):
            yield
        out["one_press"] = line_text(app) == T12
        yield from advance_until(app, lambda: line_text(app) == T12)
        out["next"] = page(app)
        yield from advance_until(app, lambda: at_menu(app))
        for _ in range(12):                                    # past the 120 ms fade
            yield
        yield from quick_save(app, game, 2, out, "cp_menu")

    def load_the_menu_then_save_at_line_23(app, out):         # run 3
        yield from wait(lambda: line_text(app) == "Before.")
        yield from quick_load(app, lambda: at_menu(app))
        for _ in range(12):
            yield
        box, layout = textbox(app), app.choices.screen.layout
        out["menu"] = (box.nvl_on, page(app), layout.tops, box.indicator_kind(),
                       box.typer.state, app.story.checkpoint().to_json())
        yield from pick_first(app)
        yield from wait(lambda: line_text(app) == "After the pick.")
        out["after_pick"] = page(app)
        yield from advance_until(app, lambda: line_text(app) == L23)
        yield from quick_save(app, game, 3, out, "cp23")

    def load_line_23(app, out):                                # run 4
        yield from wait(lambda: line_text(app) == "Before.")
        yield from quick_load(app, lambda: restored_at(app, L23))
        out["adv"] = (textbox(app).nvl_on, app.story.interp.nvl, app.story.checkpoint().to_json())

    runs = []
    for script in (save_while_typing, load_line_10_then_save_at_the_menu,
                   load_the_menu_then_save_at_line_23, load_line_23):
        out = play(scripted_app, script, last=1500)
        assert launch(game) == 0
        assert out.get("done"), (script.__name__, sorted(out))
        runs.append(out)
    one, two, three, four = runs

    # Run 1: saved while line 10 typed; the file's "nvl" holds L8–L10 in 04 §4's form.
    assert one["typing"]
    read, state = read_quick(game, 1)
    assert read.state == one["cp10"]
    sids = {e["text"]: e["sid"] for e in state["history"]["entries"]}
    assert state["nvl"] == {"on": True, "page": [
        {"sid": sids[L8], "name": "", "color": None, "spans": [{"text": L8}]},
        {"sid": sids[L9], "name": "Hana", "color": "#A02860",
         "spans": [{"text": "You're thinking about "}, {"text": "last year", "bold": True},
                   {"text": " again."}]},
        {"sid": sids[L10], "name": "", "color": None,
         "spans": [{"text": L10, "italic": True, "color": "#1e4a9c"}]}]}

    # Run 2: the first frame after the load is AC-F17-18's first row; one press goes on.
    nvl_on, shown, typed, indicator, cp = two["first"]
    assert nvl_on and shown == [(L8, 64), (L9, 123), (L10, 221)]
    assert typed is TypeState.COMPLETE and indicator == "line"
    assert cp == one["cp10"].to_json()
    assert two["one_press"] and two["next"] == [(L12, 64)]

    # Run 3: a save at the menu loads to AC-F17-24's menu picture.
    read, _ = read_quick(game, 2)
    assert read.state == two["cp_menu"] and read.state.choices.waiting is not None
    nvl_on, shown, tops, indicator, typed, cp = three["menu"]
    assert nvl_on and shown == [(L12, 64), (L14, 123), (L15, 182)]
    assert tops == (284, 355) and indicator is None and typed is TypeState.COMPLETE
    assert cp == two["cp_menu"].to_json()
    assert three["after_pick"] == [("After the pick.", 64)]

    # Run 4: a save after nvl off (line 23) loads in ADV.
    read, state = read_quick(game, 3)
    assert read.state == three["cp23"] and state["nvl"] == {"on": False, "page": []}
    nvl_on, nvl, cp = four["adv"]
    assert not nvl_on and nvl == EMPTY_NVL and cp == three["cp23"].to_json()
    assert not file_of(game, "quick-4.vnsave").exists()
