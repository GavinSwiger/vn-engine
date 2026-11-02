"""F17 step 5 — the launch checks in full-screen text (F17 ``06-acceptance.md`` AC-F17-29, 30;
``04-technical.md`` §7.6; ``07-architecture-review.md`` I-8, I-11).

Each row edits Template N (``06`` §0.4) in a game folder under ``tmp_path`` and launches it in
App A (``tests/fakes/text_app.py``) in dev; the result is every WARNING record up to the frame
after the load screen hands over. The ``feature = "F17"``, ``time = "launch"`` rows of
``tests/fixtures/F02/messages/cases.toml`` (W100, W101) are played here too.
"""

import logging
from pathlib import Path

import pygame
import pytest

from engine.runtime.nvl import Nvl
from tests.fakes.text_app import Session, make_text_game
from tests.script import message_cases
from tests.script.helpers import expand, template_n

pytestmark = pytest.mark.display

RED = (255, 0, 0)
WHERE = "script/main.vns, line {}: "
ROWS_RULE = "\\n"                  # a line break inside a script's quoted text


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def rows(k: int) -> str:
    """Rows(k): k one-letter rows joined by ``\\n`` (06 §0.4)."""
    return ROWS_RULE.join(chr(ord("a") + i % 26) for i in range(k))


def n_game(root: Path, *, script: str | None = None, config: str = "", **edit) -> Path:
    """Template N (with ``edit``, or ``script``) as a game with ``images/red.png``."""
    root = make_text_game(root, script=script or template_n(**edit), config=config)
    images = root / "images"
    images.mkdir(exist_ok=True)
    red = pygame.Surface((1280, 720))
    red.fill(RED)
    pygame.image.save(red, str(images / "red.png"))
    return root


def launch_warnings(root: Path, caplog, *, dev: bool = True) -> list[str]:
    """Every WARNING (or worse) record of an App A launch of ``root``, up to the frame after
    the load screen hands over (a release run's W53/W80 for a game with no id left out)."""
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        s = Session(root, dev=dev)

        def script(s):
            yield from s.until(lambda: s.app.story is not None and not s.app.loading)
            yield

        assert s.play(script) == 0
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
            and getattr(r, "code", None) not in ("W53", "W80")]


def w101(pages: int, size: int, line: int) -> str:
    clicks = "once" if pages == 2 else f"{pages - 1} times"
    return (WHERE.format(line) + f"this full-screen line needs {pages} pages at text size "
            f"{size}, so the player clicks {clicks} partway through. To choose where it "
            "breaks, split it into two lines.")


def w40(boxes: int, line: int) -> str:
    clicks = "once" if boxes == 2 else f"{boxes - 1} times"
    return (WHERE.format(line) + f"this line needs {boxes} text boxes at text size 28, so the "
            f"player clicks {clicks} partway through. To choose where it breaks, split it "
            "into two lines.")


def case_rows(code_prefix: str) -> list[message_cases.Case]:
    return [c for c in message_cases.load_cases()
            if c.feature == "F17" and c.time == "launch" and c.id.startswith(code_prefix)]


def play_case_rows(tmp_path: Path, caplog, prefix: str) -> int:
    """Each ``cases.toml`` launch row with ``prefix``: exactly its one message, at its place
    (besides hana's character form on the dark panel, see ``W100_HANA_DARK``)."""
    cases = case_rows(prefix)
    for case in cases:
        config = expand(case.edit["config"]) + "\n" if "config" in case.edit else ""
        root = n_game(tmp_path / case.id, script=message_cases.main_text(case), config=config)
        place = "" if case.where == "game" else WHERE.format(case.where)
        got = [w for w in launch_warnings(root, caplog) if w != W100_HANA_DARK]
        assert got == [place + case.expect["exact"]], case.id
    return len(cases)


# --- AC-F17-29 — W101, and W40 by file order ---------------------------------------------------

def test_ac_f17_29_w101_and_w40_by_file_order(tmp_path, caplog):
    many = "⏎".join([f'[4]"{rows(15)}"'] * 25)
    table = [
        ("r8-14", dict(replace={8: f'[4]"{rows(14)}"'}), "", []),
        ("r8-4", dict(replace={8: f'[4]"{rows(4)}"'}), "", []),
        ("r8-15", dict(replace={8: f'[4]"{rows(15)}"'}), "", [w101(2, 28, 8)]),
        ("r9-named-14", dict(replace={9: f'[4]hana "{rows(14)}"'}), "", [w101(2, 28, 9)]),
        ("r16-question-14", dict(replace={16: f'[8]hana "{rows(14)}"'}), "",
         [w101(2, 28, 16)]),
        ("r8-29", dict(replace={8: f'[4]"{rows(29)}"'}), "", [w101(3, 28, 8)]),
        ("r6-adv", dict(replace={6: f'[4]"{rows(4)}"'}), "", [w40(2, 6)]),
        ("r23-adv", dict(replace={23: f'[4]"{rows(4)}"'}), "", [w40(2, 23)]),
        ("size20-20", dict(replace={8: f'[4]"{rows(20)}"'}), "[theme.nvl]\ntext_size = 20\n",
         []),
        ("size20-21", dict(replace={8: f'[4]"{rows(21)}"'}), "[theme.nvl]\ntext_size = 20\n",
         [w101(2, 20, 8)]),
        # The nvl on is nested in an if: it still counts; line 8 moved to line 9.
        ("nested-on", dict(replace={7: "[4]if wish:⏎[8]nvl on", 8: f'[4]"{rows(15)}"'}), "",
         [w101(2, 28, 9)]),
        # A label starts in the textbox, even when it is reached by a jump from NVL.
        ("other-label", dict(replace={18: "[12]jump other"},
                             T=f'label other:⏎[4]"{rows(15)}"'), "", [w40(5, 26)]),
        ("25-lines", dict(replace={8: many}), "",
         [w101(2, 28, line) for line in range(8, 28)]
         + ["…and 5 more full-screen lines need more than one page."]),
    ]
    for name, edit, config, expected in table:
        root = n_game(tmp_path / name, config=config, **edit)
        assert launch_warnings(root, caplog) == expected, name
    # Release runs check nothing.
    root = n_game(tmp_path / "release", replace={8: f'[4]"{rows(15)}"'})
    assert launch_warnings(root, caplog, dev=False) == []
    # cases.toml's W101 rows (data until now).
    assert play_case_rows(tmp_path, caplog, "F17-29-") == 3


def test_the_walk_recognises_nvl_through_runtime():
    """07 I-8: ``app/text_check.py`` names the statement through ``runtime/nvl.py``."""
    import ast

    from engine.app import text_check
    from engine.script.nvl import Nvl as ScriptNvl

    assert Nvl is ScriptNvl
    tree = ast.parse(Path(text_check.__file__).read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "engine.runtime.nvl" in modules
    assert not [m for m in modules if m and m.startswith("engine.script")]


# --- AC-F17-30 — W100, NVL contrast --------------------------------------------------------------

W100_TEXT = ("config.toml: [theme.nvl] text_color #A0A0A0 on fill_color #FFF4F8 at fill_opacity "
             "0.85 gives 1.7:1 over a black picture; full-screen text needs at least 4.5:1. "
             "Pick colors further apart.")
W100_WHITE = ("config.toml: [theme.nvl] text_color #D0C0C8 on fill_color #3A2A3F at "
              "fill_opacity 0.6 gives 2.2:1 over a white picture; full-screen text needs at "
              "least 4.5:1. Pick colors further apart.")
W100_NAME = ("config.toml: [theme.nvl] name.text_color #777777 on fill_color #FFF4F8 at "
             "fill_opacity 0.85 gives 2.9:1 over a black picture; full-screen names need at "
             "least 3:1. Pick colors further apart.")
W100_INDICATOR = ("config.toml: [theme.nvl] indicator.fill_color #7A7A7A on fill_color #FFF4F8 "
                  "at fill_opacity 0.85 gives 2.8:1 over a black picture; the full-screen "
                  "indicator needs at least 3:1. Pick colors further apart.")
W100_RIN = (WHERE.format(25) + "rin's color #C060A0 gives 2.5:1 on the full-screen text panel "
            "([theme.nvl]); names need at least 3:1. Pick a darker color, or change "
            "[theme.nvl] fill_color.")
# The dark-panel row also gives Template N's hana (#A02860) the character form: the AC row
# lists only the theme form, but that name color really reads at 1.8:1 on the dark panel.
W100_HANA_DARK = (WHERE.format(1) + "hana's color #A02860 gives 1.8:1 on the full-screen text "
                  "panel ([theme.nvl]); names need at least 3:1. Pick a darker color, or "
                  "change [theme.nvl] fill_color.")
NVL = "[theme.nvl]\n"
RIN = 'define rin = Character("Rin", color="#C060A0")'


def test_ac_f17_30_w100_nvl_contrast(tmp_path, caplog):
    table = [
        ("defaults", {}, "", []),
        ("text", {}, NVL + 'text_color = "#A0A0A0"\n', [W100_TEXT]),
        ("white", {}, NVL + 'fill_color = "#3A2A3F"\nfill_opacity = 0.6\n'
         'text_color = "#D0C0C8"\nname.text_color = "#FFFFFF"\n'
         'indicator.fill_color = "#FFFFFF"\n', [W100_WHITE, W100_HANA_DARK]),
        ("name", {}, NVL + 'name.text_color = "#777777"\n', [W100_NAME]),
        ("name-3.03", {}, NVL + 'name.text_color = "#757575"\n', []),
        ("indicator", {}, NVL + 'indicator.fill_color = "#7A7A7A"\n', [W100_INDICATOR]),
        ("both", {}, NVL + 'text_color = "#A0A0A0"\nname.text_color = "#777777"\n',
         [W100_TEXT, W100_NAME]),
        ("rin", dict(T=RIN), "", [W100_RIN]),
        ("rin-adv", dict(T=RIN, drop=(7, 11, 22)), "", []),
        ("d-3.6", dict(T='define d = Character("D", color="#B04070")'), "", []),
    ]
    for name, edit, config, expected in table:
        root = n_game(tmp_path / name, config=config, **edit)
        assert launch_warnings(root, caplog) == expected, name
    for name, edit, config in (("release-text", {}, NVL + 'text_color = "#A0A0A0"\n'),
                               ("release-rin", dict(T=RIN), "")):
        root = n_game(tmp_path / name, config=config, **edit)
        assert launch_warnings(root, caplog, dev=False) == [], name
    # cases.toml's W100 rows (data until now).
    assert play_case_rows(tmp_path, caplog, "F17-30-") == 5
