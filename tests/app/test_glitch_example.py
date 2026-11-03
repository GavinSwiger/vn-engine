"""F28 step 6 — the example game's glitches (``06`` AC-F28-27): the bonus scene in
``game/script/bonus.vns`` uses every glitch form, each commented at first use, and the real
app (in-process ``launch()``, hidden window, fake clock) plays it with no warning. The player
clicks through every second frame, faster than the 5 s auto-advance the AC names, so the
flash limit is tried harder (decision, F28 s6). The headless golden is ``test_determinism``'s.
The real ``game/characters/`` is never touched (the copy leaves it out)."""

import logging
import re

import pygame
import pytest

from engine.render import glitch as render_glitch
from tests.fakes.loop import post_key
from tests.app.test_metafiles_app import advance_to
from tests.app.test_metafiles_example import _copy
from tests.app.test_saves_service import launch, play, unthreaded

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]

# Each form AC-F28-27 names → a pattern for the first line that uses it.
FORMS = {
    "effect tear": r"effect tear\b.*",
    "effect colorshift": r"effect colorshift\b.*",
    "effect static": r"effect static\b.*",
    "effect jitter <tag>": r"effect jitter \w+.*",
    "a burst with a length": r"effect \w+( \w+)*? \d+(\.\d+)?( \w+)?",
    "on": r"effect .* on",
    "effect <kind> off": r"effect \w+( \w+)? off",
    "effect off": r"effect off",
    "with glitch": r"(scene|show|hide) .* with glitch( [\d.]+)?",
}


def test_ac_f28_27_the_example_glitch_scene(tmp_path, scripted_app, unthreaded, caplog,
                                            user_roots, monkeypatch):
    game = _copy(tmp_path)
    lines = (game / "script" / "bonus.vns").read_text(encoding="utf-8").splitlines()
    for form, pattern in FORMS.items():
        first = next((n for n, line in enumerate(lines)
                      if re.fullmatch(pattern, line.strip())), None)
        assert first is not None, form
        assert lines[first - 1].strip().startswith("#"), (form, lines[first])

    seen: list = []                                  # every Glitch the stage screen applies
    real_apply = render_glitch.GlitchLayer.apply
    played: list[float] = []                         # with glitch's drawn progress values
    real_draw = render_glitch.GlitchKind.draw

    def apply(self, cmd, now, **kwargs):
        seen.append(cmd)
        return real_apply(self, cmd, now, **kwargs)

    def draw(self, target, p, offset):
        played.append(p)
        return real_draw(self, target, p, offset)

    monkeypatch.setattr(render_glitch.GlitchLayer, "apply", apply)
    monkeypatch.setattr(render_glitch.GlitchKind, "draw", draw)

    def scene(app, out):
        yield from advance_to(app, "That's me in there.")
        for _ in range(90):                          # let the line type out, then watch
            yield                                    # with glitch (0.5 s) play in full
        post_key(pygame.K_SPACE)
        for _ in range(45):
            yield
        yield from advance_to(app, "Paper lanterns drifted")   # chapter1.vns, after it

    with caplog.at_level(logging.DEBUG, logger="vn"):
        out = play(scripted_app, scene, last=4000)
        assert launch(game) == 0                                       # a --dev launch
    assert out.get("done"), out
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
    bursts = {b.kind for cmd in seen for b in cmd.bursts}
    lasting = {e.kind for cmd in seen for e in cmd.lasting.on}
    assert bursts == {"jitter"} and lasting == {"tear", "colorshift", "static"}
    assert any(cmd.stops and not cmd.lasting.on for cmd in seen)       # effect off
    assert played and min(played) < 0.5 <= max(played)                 # with glitch drew
