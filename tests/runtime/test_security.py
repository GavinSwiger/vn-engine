"""F03's security rows that need the whole app (06 §4: AC-F03-63, 69, 75).

AC-F03-75 (step 8): with F01's sentinel user and the game root under the sentinel home, a
new game with a run-time error, and separately a launch error, leave no user name, home
folder, or game root in the log file, on the error screen (and every drawn text, the
clipboard, the log tail), or on stderr (privacy check P, F01 §0.5). AC-F03-69 (step 14):
audit spy A over the example game and the seeded corpus, in a subprocess. AC-F03-63 is
``test_restore.py``'s.
"""

import pygame
import pytest

from tests.app.test_story_load_screen import launch, make_game
from tests.fakes.loop import post_key
from tests.fakes.privacy import capture_channels, check_p
from tests.script.helpers import template_r

pytestmark = pytest.mark.display

# AC-F03-30's rows, together in one story (each define fails on its own).
LAUNCH_ROWS = ("define opening = dice.roll(1, 3)⏎define bonus = trust * 2⏎"
               "define bonus2 = luck2 * 2⏎define rate = 1 / 0⏎define x = fortunez")


def _texts(game, channels, capfd) -> list[str]:
    log = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    captured = capfd.readouterr()
    return [*channels.texts(), log, captured.err, captured.out]


def test_ac_f03_75_a_run_time_error_carries_no_identity(user_roots, scripted_app, monkeypatch,
                                                        capfd):
    from engine.ui.builtin.error import ErrorScreen

    home = user_roots.home
    game = make_game(home, {"main.vns": template_r(S="$ x = bonus()",
                                                   T="define bonus = lambda: 1 / 0")},
                     name="My Game")
    with (game / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[textbox]\ncps = 0\n")        # F05: "Start." is complete at once
    scripted_app.at(5, lambda app: post_key(pygame.K_SPACE))      # "Start." → line 8 fails
    scripted_app.at(9, lambda app: post_key(pygame.K_c))          # copy the error text
    scripted_app.at(12, lambda app: post_key(pygame.K_ESCAPE))
    scripted_app.quit_frame = 30
    with capture_channels(monkeypatch) as channels:
        assert launch(game) == 1
    top = scripted_app.apps[-1].screens.top
    assert isinstance(top, ErrorScreen)
    assert top.message.startswith("script/main.vns, line 8: this divides by zero (in define "
                                  "bonus, script/main.vns, line 11).")
    texts = _texts(game, channels, capfd)
    assert any("New game" in t or "Traceback (script frames):" in t for t in texts)
    check_p(texts + [top.message], home=home, game=game)


def test_ac_f03_75_a_launch_error_carries_no_identity(user_roots, scripted_app, monkeypatch,
                                                      capfd):
    from engine.ui.builtin.error import ErrorScreen

    home = user_roots.home
    game = make_game(home, {"main.vns": template_r(S="$ luck2 = 1", T=LAUNCH_ROWS)},
                     name="My Game")
    scripted_app.at(6, lambda app: post_key(pygame.K_c))
    scripted_app.at(9, lambda app: post_key(pygame.K_ESCAPE))
    scripted_app.quit_frame = 30
    with capture_channels(monkeypatch) as channels:
        assert launch(game) == 1
    top = scripted_app.apps[-1].screens.top
    assert isinstance(top, ErrorScreen)
    assert top.message.startswith("The script has 5 problems:")
    for code_text in ("it uses dice", 'it uses "trust"', "set by a $ line (script/main.vns, "
                      "line 8)", "this divides by zero", 'Did you mean "fortunes"?'):
        assert code_text in top.message
    assert "\n    define rate = 1 / 0\n" in top.message                # the source line
    texts = _texts(game, channels, capfd)
    check_p(texts + [top.message], home=home, game=game)


# --- AC-F03-69 — the runtime touches no file and runs only script code ------------------------

def test_ac_f03_69_the_runtime_touches_no_file_and_runs_only_script_code():
    """Audit spy A in a subprocess (``tests/runtime/audit_run.py``): the example game and the
    F03 seeded corpus (``seeded/`` and the launch and run rows of ``cases.toml``) played
    headless with ``image_files=[]``. (This row needs no window; the module's ``display``
    mark is harmless.)"""
    import json
    import re
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, "-m", "tests.runtime.audit_run"], cwd=repo,
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-3000:]
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    names = [name for name, _ in seen["stories"]]
    assert "example" in names and sum(n.startswith("seeded/") for n in names) >= 5
    assert len(names) > 100
    events = seen["events"]
    banned = ("open", "os.listdir", "os.scandir", "os.system", "subprocess.Popen")
    assert [e for e in events if e[1] in banned or e[1].startswith(("os.exec", "socket."))] \
        == []
    execs = [e for e in events if e[1] == "exec"]
    assert execs and all(re.fullmatch(r"<script/.+\.vns>", e[2]) for e in execs), \
        {e[2] for e in execs}
    allowed = {story: set(modules) for story, modules in seen["stories"]}
    for story, _, module in (e for e in events if e[1] == "import"):
        top = {m.split(".")[0] for m in allowed[story]}
        assert module in allowed[story] or module.split(".")[0] in top, (story, module)
    calls = [name for _, name in seen["calls"]]
    assert not {"os.getlogin", "getpass.getuser", "socket.gethostname"} & set(calls)
    # Every eval/exec the runtime makes runs one of the story's code objects.
    assert calls.count("eval") + calls.count("exec") == len(execs)
