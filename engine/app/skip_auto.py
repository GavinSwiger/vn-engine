"""``install_skip_auto``: F15's skip and auto wired into one launch (F15 ``SPEC.md`` §5;
``07-architecture-review.md`` I-4, I-8, I-11).

Why this module exists: ``ui`` never imports ``engine.app``, so ``SkipAuto`` gets its ports
here: F05's ``TextboxScreen`` (``app.textbox``), F09's ``StageScreen``
(``app.stage_screen``), F08's ``App.audio`` (None: no voice wait), the run's F12
``PersistentStore`` (``interp.persistent``, the store ``App.persist`` writes), and the
``[skip]``/``[auto]`` config. It registers ``SkipAuto`` in its four roles (textbox overlay,
typing listener, say listener, F07 menu listener), the quick menu's Skip and Auto, the
corner indicator, and ``SkipAuto.reset`` as a shell in-game reset (New Game, the way back
to the title, a load: I-4). ``App.skip_auto`` is F16's seam (I-8).

``install_story`` calls it once per launch (windowed only), after ``install_ui`` and the
other entry installs (F13 I-6), before ``install_settings_ui`` (F16 I-11) and
``shell.check_entries()``.
"""

from typing import TYPE_CHECKING

from engine.ui.builtin.skip_auto import SkipAuto, SkipIndicator, register_skip_auto

if TYPE_CHECKING:
    from engine.app.app import App


def install_skip_auto(app: "App") -> SkipAuto | None:
    """Build and register the launch's ``SkipAuto`` and set ``app.skip_auto``. None (and
    nothing registered) without a shell, textbox, or stage (an App wired by hand)."""
    shell, textbox, stage = app.shell, app.textbox, app.stage_screen
    if shell is None or textbox is None or stage is None:
        return None
    config = app.config
    interp = getattr(app.story, "interp", None)
    skip_auto = SkipAuto(textbox, stage, store=getattr(interp, "persistent", None),
                         audio=getattr(app, "audio", None), skip_all=config.skip.all,
                         delay=config.auto.delay, per_char=config.auto.per_char,
                         wait_for_voice=config.auto.wait_for_voice)
    skip_auto.indicator = SkipIndicator(shell)
    textbox.add_overlay(skip_auto)            # after F10's quick menu: its clicks come first
    textbox.add_listener(skip_auto)
    textbox.add_say_listener(skip_auto.on_say)
    choices = getattr(app, "choices", None)
    if choices is not None:
        choices.add_listener(skip_auto)
    shell.add_in_game_reset(skip_auto.reset)
    register_skip_auto(shell, skip_auto)
    app.skip_auto = skip_auto
    return skip_auto


__all__ = ["install_skip_auto"]
