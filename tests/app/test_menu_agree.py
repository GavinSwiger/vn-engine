"""F07 step 2 — headless and windowed runs agree (AC-F07-35, TR-F07-03; invariant 5).

Fixture ``tests/fixtures/F07/agree/`` (06 §5, ``show_locked = true``): a question menu with a
locked choice, ``"Between."``, a question-less menu (kept), ``scene black`` and a
question-less menu (none) whose first choice holds a nested question menu. App A plays it by
clicking the same choices ``run_headless`` picks; both command sequences, ``ShowMenu``
bodies included, must be equal, and the presentation posts only ``Advance`` and ``Choose``.

The AC's inputs ``a c2 c1 a a c1`` don't play its own fixture (after the first pick,
``"Between."`` needs an ``a`` before the kept menu's ``c1``); these inputs play every menu
of it to the end.

F07 step 5 adds AC-F07-40's run-time halves here (its AST rows are
``tests/test_import_rules.py``): audit spy A on ``agree/`` against the same story without
menus, and privacy check P on the saved ``choices`` values and the W47/W48 records.
"""

import shutil

import pygame
import pytest

from engine.app import loading
from engine.app import story as story_mod
from engine.runtime.commands import Advance, Choose, ShowMenu
from engine.ui.builtin.choice_screen import ChoiceScreen
from tests.fakes.text_app import NO_TITLE, Session
from tests.runtime.menu_story import F07, load_fixture, menus, run_m, shown

pytestmark = pytest.mark.display

INPUTS = "a c2 a c1 c1 c1 a"


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def test_ac35_windowed_commands_equal_headless(tmp_path, monkeypatch):
    root = tmp_path / "game"
    shutil.copytree(F07 / "agree", root)
    (root / "config.toml").write_text(
        NO_TITLE + "[textbox]\ncps = 0\n" + (F07 / "agree" / "config.toml").read_text(
            encoding="utf-8"), encoding="utf-8")
    pumped: list = []
    posted: list = []
    real_install = story_mod.install_story

    def install(app, interp, **kwargs):
        driver = real_install(app, interp, **kwargs)
        real_pump, real_post = driver.pump, driver.post

        def pump(*args, **kw):
            out = real_pump(*args, **kw)
            pumped.extend(out)
            return out

        def post(event):
            posted.append(event)
            real_post(event)

        driver.pump, driver.post = pump, post
        return driver

    monkeypatch.setattr(loading, "install_story", install)
    s = Session(root)

    def screen():
        return next((x for x in s.app.screens if isinstance(x, ChoiceScreen)), None)

    def script(s):
        yield from s.until(lambda: s.app.story is not None and s.textbox is not None)
        for word in INPUTS.split():
            if word == "a":
                yield from s.until(lambda: s.textbox.line is not None and screen() is None)
                yield
                s.key(pygame.K_SPACE)
                yield
                continue
            yield from s.until(lambda: screen() is not None)
            for _ in range(20):                # past the guard
                yield
            menu = screen()
            n = int(word[1:])
            index = menu.pickable[n - 1]
            x, y, w, h = menu.layout.buttons[index].rect
            s.mouse((round(x + w / 2), round(y + h / 2)))
            yield
            yield
        yield from s.until(lambda: any(type(c).__name__ == "StoryEnded" for c in pumped))

    s.play(script)
    expected = run_m(load_fixture(tmp_path / "h", "agree"), INPUTS, show_locked=True)
    shows = menus(expected)                    # the fixture plays every menu kind to the end
    assert [m.line for m in shows] == ["question", "kept", "none", "question"]
    assert [locked for _, _, locked in shown(shows[0])] == [False, True, False]
    assert type(expected[-1]).__name__ == "StoryEnded"
    assert menus(pumped) == menus(expected)
    assert [type(c) for c in pumped] == [type(c) for c in expected]
    assert pumped == expected
    assert {type(e) for e in posted} == {Advance, Choose}
    assert sum(isinstance(e, Choose) for e in posted) == 4
    assert all(isinstance(m, ShowMenu) for m in menus(pumped))


# --- AC-F07-40 — audit spy A and privacy check P (F07 step 5) ---------------------------------

def test_ac40_agree_opens_no_file_and_compiles_nothing_more_than_without_menus():
    """Audit spy A in a subprocess (``python -m tests.runtime.audit_run --menus``): ``agree/``
    played headless with this file's inputs, and the same story with each menu replaced by
    the lines of the picked choice. Neither opens a file or starts anything; every exec is a
    script code object; ``agree/`` compiles nothing and runs no more author code than its
    menu-less twin (the conditions run once per menu, as the twin's ``if``)."""
    import json
    import re
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, "-m", "tests.runtime.audit_run", "--menus"],
                          cwd=repo, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert [name for name, _ in seen["stories"]] == ["agree", "agree-no-menus"]
    events = seen["events"]
    banned = ("open", "os.listdir", "os.scandir", "os.system", "subprocess.Popen", "import")
    assert [e for e in events if e[1] in banned or e[1].startswith(("os.exec", "socket."))] \
        == []

    def of(story: str, kind: str) -> list[str]:
        return [e[2] for e in events if e[0] == story and e[1] == kind]

    assert of("agree", "compile") == [] or set(of("agree", "compile")) <= set(
        of("agree-no-menus", "compile"))
    assert all(re.fullmatch(r"<script/.+\.vns>", e[2]) for e in events if e[1] == "exec")
    assert 0 < len(of("agree", "exec")) <= len(of("agree-no-menus", "exec"))
    calls = [name for _, name in seen["calls"]]
    assert not {"os.getlogin", "getpass.getuser", "socket.gethostname"} & set(calls)


def test_ac40_saved_choices_and_w47_w48_pass_privacy_check_p(tmp_path, caplog):
    """Every saved ``choices`` value of AC-F07-35's run (each checkpoint's JSON), and the W47
    and W48 records of ``agree/`` with a long choice and a missing sound launched in a dev
    App A from a folder named after the account, pass privacy check P."""
    import getpass
    import json
    import logging
    from pathlib import Path

    from tests.fakes.privacy import check_p
    from tests.runtime.menu_story import go, launched

    program = load_fixture(tmp_path / "h", "agree")
    interp = launched(program, show_locked=True)
    interp.new_game(42)
    interp.run(10_000)
    saved = [json.dumps(interp.checkpoint().to_json()["choices"])]
    for word in INPUTS.split():
        go(interp, word)
        if interp.checkpoint() is not None:
            saved.append(json.dumps(interp.checkpoint().to_json()["choices"]))
    assert any('"waiting": {' in text for text in saved)
    assert '"picks": []' not in saved[-1]

    root = tmp_path / getpass.getuser() / "game"
    shutil.copytree(F07 / "agree", root)
    script = root / "script" / "main.vns"
    script.write_text(script.read_text(encoding="utf-8").replace(
        '        "The paper one":',
        '        "' + "A long and winding choice " * 8 + '":\n'
        '            $ path = "long"\n        "The paper one":'), encoding="utf-8")
    (root / "config.toml").write_text(
        NO_TITLE + "[textbox]\ncps = 0\n[choice]\nshow_locked = true\n"
        '[theme.choice]\npick_sound = "pick.ogg"\n', encoding="utf-8")

    def script_(s):
        yield from s.until_line("The festival is busy.")
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: s.app.choices.screen is not None)

    with caplog.at_level(logging.WARNING):
        Session(root, dev=True).play(script_)
    records = [r.getMessage() for r in caplog.records if r.name == "vn.choice"]
    assert any("this choice needs" in r for r in records)                      # W47
    assert any('pick_sound "pick.ogg" doesn\'t exist' in r for r in records)   # W48
    check_p(saved + records, home=Path.home(), game=root)
