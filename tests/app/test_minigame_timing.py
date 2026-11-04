"""F50 Timing assist: AC-F50-05 (step 2, minigame API 1.3; 07 I-3) in the real App (the
F23 Probe on Template M), and AC-F50-08 (step 3: the story state never changes)."""

import pygame

from engine.app.minigames import player_settings
from engine.minigames.context import PlayerSettings
from engine.minigames.screen import MinigameScreen
from tests.app.test_minigame_app import (  # noqa: F401  (fixtures)
    behavior,
    m_game,
    plugin_modules,
    pygame_ready,
    running_probe,
    top,
)
from tests.fakes.text_app import Session


def test_ac_f50_05_player_settings_follow_timing_assist(tmp_path, user_roots, pygame_ready):
    from engine.app.settings import install_settings_ui
    from engine.ui.builtin.game_menu import GameMenuScreen
    from tests.app.test_settings_service import make as make_settings

    # The snapshot and its rule; the host's fallback without a settings port is Normal.
    for level, want in (("normal", 2.0), ("slower", 4.0), ("off", None)):
        assert PlayerSettings(timing_assist=level).timed(2.0) == want
    assert PlayerSettings().timing_assist == "normal"

    s = Session(m_game(tmp_path / "g"))
    seen: dict = {}

    def script(s: Session):
        def look(b):
            service = make_settings(tmp_path)
            s.app.settings = service
            install_settings_ui(s.app)

        yield from running_probe(s, look)
        app = s.app
        b = behavior(s)
        seen["first"] = (b.ctx.settings.timing_assist, b.ctx.settings.timed(2.0))
        for stored, level in ((1, "slower"), (2, "off"), (0, "normal")):
            app.settings.set("timing_assist", stored)
            seen[level] = player_settings(app).timing_assist
        app.settings.set("timing_assist", 1)              # while the minigame runs
        mark = len(b.calls)
        for _ in range(3):
            yield
        changed = [c[1] for c in b.calls[mark:] if c[0] == "settings_changed"]
        seen["changed"] = [(c.timing_assist, c.timed(2.0)) for c in changed]
        seen["learns"] = b.ctx.settings.timed(2.0)
        # Through the game menu too: one call when the minigame comes back.
        s.key(pygame.K_ESCAPE)
        yield from s.until(lambda: isinstance(top(s), GameMenuScreen))
        app.settings.set("timing_assist", 2)
        mark = len(b.calls)
        s.key(pygame.K_ESCAPE)
        yield from s.until(lambda: isinstance(top(s), MinigameScreen))
        for _ in range(3):
            yield
        seen["menu"] = [c[1].timing_assist for c in b.calls[mark:] if c[0] == "settings_changed"]

    s.play(script)
    assert seen["first"] == ("normal", 2.0)
    assert (seen["slower"], seen["off"], seen["normal"]) == ("slower", "off", "normal")
    assert seen["changed"] == [("slower", 4.0)] and seen["learns"] == 4.0
    assert seen["menu"] == ["off"]



def test_ac_f50_08_settings_stay_outside_the_story(tmp_path, user_roots, pygame_ready):
    """AC-F50-08 (PR-F50-08): changing Timing assist leaves the story's state as it was (the
    docs rows are review)."""
    from engine.app.settings import install_settings_ui
    from tests.app.test_settings_service import make as make_settings

    s = Session(m_game(tmp_path / "g"))
    seen: dict = {}

    def script(s: Session):
        yield from s.until_line("Before.")
        app = s.app
        app.settings = make_settings(tmp_path)
        install_settings_ui(app)
        before = app.story.interp.checkpoint().to_json()
        for stored in (1, 2, 0):
            app.settings.set("timing_assist", stored)
            yield
            seen.setdefault("after", []).append(app.story.interp.checkpoint().to_json())
        seen["before"] = before

    s.play(script)
    assert seen["after"] == [seen["before"]] * 3
