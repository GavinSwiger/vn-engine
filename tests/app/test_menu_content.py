"""F07 step 5 — huge, empty, and Unicode content (AC-F07-41; ``01`` §4 edge cases, PR-F07-08,
PR-F07-20).

Each row of the AC's table is a choice in Template M (``tests/fixtures/F07/template/``), played
two ways: **Run M** (``run_headless``-style on an ``Interpreter``, ``tests/runtime/
menu_story.py``) for what the runtime offers and records (``ShowMenu``, ``Pick.text``), and
**App A** (``tests/fakes/text_app.py``) for what the screen lays out and that a pick still
works (no crash). Line counts on screen come from the live ``ChoiceLayout`` (bundled Noto
Sans); the M20 rows use F05's fixed-width font (``tests/fakes/fixed_font.py``, 36 graphemes
per 720-unit line at 28). W47's forms run F05's ``TextLaunchCheck`` with M20 injected
(``test_choice_install.w47_check``).
"""

import logging

import pygame
import pytest

from engine.core.config_schema import ChoiceTheme
from engine.render.choices import ChoiceArea, ChoiceLayout
from engine.render.text import ELLIPSIS
from engine.render.textlayout import BUNDLED_FACES
from engine.runtime.commands import Choose, ShowMenu
from engine.runtime.menu import plain_text
from tests.app.test_choice_install import choice_game, warnings_of
from tests.fakes.fixed_font import FixedFontAssets, tagged
from tests.fakes.text_app import Session
from tests.runtime.menu_story import K, load_m, menus, play

QUESTION = 'menu:⏎[8]hana "Will you buy a lantern?"⏎'
# F02's text limit, 10,000 characters: 100 words, written as one quoted text continued over
# 100 lines (a source line has its own 10,000-character limit; each break is one space).
WORDS = ["a" * 100] + ["a" * 99] * 99
HUGE = " ".join(WORDS)
LANTERN = "🏮 Lantern 👨‍👩‍👧"
CJK = "赤い提灯にする" * 10                          # 70 graphemes, no spaces
ARABIC = "فانوس أحمر"


def menu_with(*texts: str) -> str:
    """Template M's ``M``: the question, then one choice per text, each setting ``n``. The
    huge text is written continued over its words' lines."""
    out = QUESTION
    for k, text in enumerate(texts, 1):
        written = "⏎[16]".join(WORDS) if text == HUGE else text
        out += f'[8]"{written}":⏎[12]$ n = {k}⏎'
    return out.removesuffix("⏎")


def run_m(tmp_path, *texts: str, S: str | None = None, inputs: str = "a c1"):
    """Run M with the row's choices (``default n = 0`` and ``default v = ""`` added)."""
    program = load_m(tmp_path / "m", M=menu_with(*texts), S=S,
                     T='default n = 0⏎default v = ""')
    interp, commands = play(program, inputs)
    return interp, commands


@pytest.fixture
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def app_a(tmp_path, *texts: str, S: str | None = None, config: str = "", pick: int = 1):
    """App A on the row's menu: past the guard, the layout's lines per button (their texts)
    and the ``Choose`` posted by number key ``pick``."""
    root = choice_game(tmp_path, config, M=menu_with(*texts),
                       T='default n = 0⏎default v = ""', **({"S": S} if S else {}))
    seen: dict = {"posted": []}

    def script(s):
        yield from s.until(lambda: s.app.story is not None and s.textbox is not None)
        real = s.app.story.post
        s.app.story.post = lambda e: (seen["posted"].append(e), real(e))
        yield from s.until(lambda: getattr(s.app, "choices", None) is not None
                           and s.app.choices.screen is not None)
        for _ in range(20):                                     # past the guard and fade
            yield
        screen = s.app.choices.screen
        seen["lines"] = [[_line_text(line) for line in button.lines]
                         for button in screen.layout.buttons]
        s.key(pygame.K_1 + pick - 1)
        yield
        yield
        seen["closed"] = s.app.choices.screen is None
        seen["picks"] = s.app.story.interp.choices.picks

    Session(root).play(script)
    return seen


def _line_text(line) -> str:
    return "".join(g.text for g in line.glyphs if not g.hangs)


def m20(*texts: str) -> ChoiceLayout:
    return ChoiceLayout([tagged(t) for t in texts], assets=FixedFontAssets(),
                        faces=BUNDLED_FACES, theme=ChoiceTheme(), text_size=28,
                        area=ChoiceArea(16, 444.0, 704.0, "center"),
                        colors=["#3d2b36"] * len(texts))


# --- 10,000 characters ------------------------------------------------------------------------

def test_ac41_ten_thousand_characters_run_m(tmp_path):
    interp, commands = run_m(tmp_path, HUGE, "Not this year")
    (shown,) = menus(commands)
    assert plain_text(shown.choices[0].body) == HUGE              # offered whole
    (pick,) = interp.choices.picks
    assert pick.text == HUGE[:999] + "…" and len(pick.text) == 1_000


def test_ac41_ten_thousand_characters_w47_three_plus_form(tmp_path):
    from engine.app.text_check import TextLaunchCheck
    from engine.core.config_schema import TextboxTheme
    from engine.runtime.launch import run_launch

    program = load_m(tmp_path / "m", M=menu_with(HUGE, "Not this year"))
    launch = run_launch(program)
    (record,) = TextLaunchCheck(program, launch.namespace, assets=FixedFontAssets(),
                                faces=BUNDLED_FACES, theme=TextboxTheme(),
                                choice_theme=ChoiceTheme()).run()
    assert record.startswith("script/main.vns, line 8: this choice needs ")
    assert record.endswith('but a choice shows at most 2, so the end is cut with "…". '
                           "Shorten it.")


# --- {var=v} with a million characters -----------------------------------------------------------

def test_ac41_a_million_character_variable(tmp_path):
    interp, commands = run_m(tmp_path, "Take {var=v}", "Not this year",
                             S='$ v = "b" * 1_000_000', inputs="c1")
    (shown,) = menus(commands)
    text = plain_text(shown.choices[0].body)
    assert text == "Take " + "b" * 199 + "…"                    # F05's 200-grapheme cut
    (pick,) = interp.choices.picks
    assert pick.text == text and len(pick.text) <= 1_000


# --- Emoji, CJK, Arabic, a line break -------------------------------------------------------------

def test_ac41_emoji_cjk_arabic_texts_are_kept_run_m(tmp_path):
    for k, text in enumerate((LANTERN, CJK, ARABIC), 1):
        interp, commands = run_m(tmp_path / str(k), text, "Not this year")
        (shown,) = menus(commands)
        assert plain_text(shown.choices[0].body) == text
        assert interp.choices.picks[0].text == text


def test_ac41_cjk_splits_between_graphemes_into_two_lines_at_m20():
    (button,) = m20(CJK).buttons
    lines = [_line_text(line) for line in button.lines]
    assert len(lines) == 2 and "".join(lines) == CJK             # no grapheme dropped or cut
    assert [len(line) for line in lines] == [36, 34]


# --- Six equal texts -------------------------------------------------------------------------------

def test_ac41_six_choices_go_get_numbered_keys_and_c4_runs_the_fourth(tmp_path):
    interp, commands = run_m(tmp_path, *["Go"] * 6, inputs="a c4")
    (shown,) = menus(commands)
    key = K("Go")
    assert [c.key for c in shown.choices] == [key] + [f"{key}~{n}" for n in range(2, 7)]
    assert interp.G["n"] == 4
    assert interp.choices.picks[0].choice == f"{key}~4"


# --- App A: every row on screen in one run ------------------------------------------------------

@pytest.mark.display
def test_ac41_every_row_on_screen_with_a_missing_frame_and_sounds(tmp_path, pygame_ready,
                                                                  caplog):
    """One App A run on a menu of the 10,000-character, emoji, CJK, Arabic, and two-line
    choices, with a missing ``frame_image`` and missing sounds: 2 lines ending in ``…`` for
    the huge one; one line for the emoji and the Arabic; the CJK at most 2 (cut with ``…``
    if cut); ``Two``/``lines``; drawn buttons, silence, W43 and W48; ``3`` picks the CJK.
    The W47 forms are ``test_choice_install::test_ac39_w47`` and the rows above."""
    from engine.ui.builtin.choice_screen import ChoiceController

    config = ('[theme.choice]\nframe_image = "gui/nothing.png"\npick_sound = "pick.ogg"\n'
              'focus_sound = "focus.ogg"\n')
    played: list[str] = []
    real_show = ChoiceController.show

    def show(self, cmd: ShowMenu) -> None:
        self.play = played.append                                # any sound would land here
        real_show(self, cmd)

    with pytest.MonkeyPatch.context() as mp, caplog.at_level(logging.WARNING):
        mp.setattr(ChoiceController, "show", show)
        seen = app_a(tmp_path, HUGE, LANTERN, CJK, ARABIC, "Two\\nlines", config=config,
                     pick=3)
    huge, lantern, cjk, arabic, broken = seen["lines"]
    assert len(huge) == 2 and huge[-1].endswith(ELLIPSIS)
    assert len(lantern) == 1
    assert 1 <= len(cjk) <= 2
    if len(cjk) == 2 and "".join(cjk) != CJK:                     # cut on screen
        assert cjk[-1].endswith(ELLIPSIS)
    assert len(arabic) == 1                                      # drawn per F05 G12
    assert broken == ["Two", "lines"]
    assert seen["closed"] and seen["picks"][0].text == CJK
    assert any(isinstance(e, Choose) for e in seen["posted"])
    assert played == []
    assert warnings_of(caplog, "vn.text") == [
        'config.toml: [theme.choice] frame_image "gui/nothing.png" doesn\'t exist, so the drawn '
        "button is used."]
    assert [w for w in warnings_of(caplog, "vn.choice") if w.startswith("config.toml")] == [
        'config.toml: [theme.choice] focus_sound "focus.ogg" doesn\'t exist, so no sound plays.',
        'config.toml: [theme.choice] pick_sound "pick.ogg" doesn\'t exist, so no sound plays.']
