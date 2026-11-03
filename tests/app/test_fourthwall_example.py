"""F30 step 6 — the example game's fourth-wall tricks (``06`` AC-F30-37): ``game/config.toml``
offers ``{username}`` and the bonus scene (``game/script/bonus.vns``) uses ``effect
window_title``, ``{username}``, ``effect crash``, and ``effect window_title off``, each first
use under a ``#`` comment. The real app (in-process ``launch()``, hidden window, fake clock,
``--dev``) with Reader Z and the name allowed plays the scene: the line draws the name, the
crash shows it, Space continues the crash once its guard is over (pressed every second frame,
so the first press after c + 30 continues: faster than the AC's 5 s auto-advance, decision
F30 s6), and the window's title is ``[game] title`` afterwards, with no warning and no log
record holding the name. The headless example golden's flagged spans hold only "friend".
The real ``game/characters/`` and ``game/logs/`` are never touched (the copy leaves them
out)."""

import json
import logging
import re

import pytest

from engine.app import fourthwall as fourthwall_module
from engine.app.app import App
from engine.ui.builtin.fake_crash import FakeCrashScreen
from tests.app.test_metafiles_app import advance_to
from tests.app.test_metafiles_example import _copy
from tests.app.test_saves_service import launch, play, unthreaded
from tests.fakes.username import Z, no_real_username, reader  # noqa: F401  (name guard)
from tests.runtime.stage_story import EXAMPLE
from tests.test_f30_name_guard import _flagged_texts

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]

GOLDEN = EXAMPLE.parents[0] / "tests" / "fixtures" / "F03" / "goldens" / "commands_example.json"
TITLE = "Example Visual Novel"
SCRIPTED = "Hana is still here"
# Each form AC-F30-37 names → a pattern for the first line that uses it.
FORMS = {
    'effect window_title "…"': r'effect window_title ".+"',
    "{username}": r'.*"[^"]*\{username\}[^"]*"',
    'effect crash "…"': r'effect crash ".+"',
    "effect window_title off": r"effect window_title off",
}


def test_ac_f30_37_the_example_fourth_wall_scene(tmp_path, scripted_app, unthreaded, caplog,
                                                 user_roots, monkeypatch):
    config = (EXAMPLE / "config.toml").read_text(encoding="utf-8")
    assert re.search(r"^\[meta\]\nusername = true$", config, re.M)
    lines = (EXAMPLE / "script" / "bonus.vns").read_text(encoding="utf-8").splitlines()
    for form, pattern in FORMS.items():
        first = next((n for n, line in enumerate(lines)
                      if re.fullmatch(pattern, line.strip())), None)
        assert first is not None, form
        assert lines[first - 1].strip().startswith("#"), (form, lines[first])

    game = _copy(tmp_path)
    (game / "settings").mkdir()                       # the player already chose "Allow"
    (game / "settings" / "settings.json").write_text(
        json.dumps({"format": 3, "values": {"username_use": 2}}), encoding="utf-8")
    read = reader(Z)
    monkeypatch.setattr(fourthwall_module, "read_login_name", read)
    titles: list[str] = []
    real_set_title = App.set_title

    def set_title(self, title):
        titles.append(title)
        real_set_title(self, title)

    crashes: list[str] = []
    real_draw = FakeCrashScreen.draw

    def draw(self, canvas):
        if not crashes or crashes[-1] != self.message:
            crashes.append(self.message)
        real_draw(self, canvas)

    monkeypatch.setattr(App, "set_title", set_title)
    monkeypatch.setattr(FakeCrashScreen, "draw", draw)

    def scene(app, out):
        yield from advance_to(app, "I can see more from in here")
        for _ in range(60):                           # the line types out with the name
            yield
        out["drawn"] = app.textbox.name_drawn()
        out["title"] = titles[-1]
        yield from advance_to(app, "...Sorry. That wasn't me.")
        yield from advance_to(app, "Paper lanterns drifted")     # chapter1.vns, after it

    with caplog.at_level(logging.DEBUG, logger="vn"):
        out = play(scripted_app, scene, last=4000)
        assert launch(game) == 0                                       # a --dev launch
    assert out.get("done"), out
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert out["drawn"] is True and out["title"] == SCRIPTED and read.calls == 1
    assert crashes == [f"HanaError: Hana is not responding.\nShe is still here, {Z}."]
    assert titles == [SCRIPTED, TITLE], titles                      # off: the game's title
    assert not any(Z.lower() in r.getMessage().lower() for r in caplog.records)

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    flagged = _flagged_texts(golden)
    assert flagged and set(flagged) == {"friend"}
    assert Z not in GOLDEN.read_text(encoding="utf-8")
