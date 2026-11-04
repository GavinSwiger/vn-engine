"""``install_rollback``: F14's rollback wired into one launch (F14 ``04-technical.md`` §5.3,
§10; ``07-architecture-review.md`` §3.4 A6, §3.5, I-3, I-6).

Why this module exists: ``ui`` never imports ``engine.app``, so ``RollbackKeys`` gets its
ports here: the story driver (``rollback_view``, ``post``), F05's ``TextboxScreen``, and the
App's game time. It registers the overlay and say listener on the textbox (after F10's and
F11's overlays, before F15's: the install order is ``install_saves``, ``install_rollback``,
``install_skip_auto``, then F17's ``install_nvl``), the quick menu's ``back`` (enabled
exactly while ``can_back``; absent with ``[rollback] steps = 0``), the overlay's reset as a
shell in-game reset, and two driver listeners:

- **report** (landings and matched arrivals) → ``App.saves.note_restore()``: the checkpoint
  arrived at is never auto-saved, and a pending chapter auto-save request is dropped (F18
  ``07`` I-6). It runs at the end of the pump, before ``saves.update`` (§3.5).
- **landing** (real rollback steps only) → ``App.skip_auto.reset()``: skip and auto end. A
  matched click, skip, or auto arrival doesn't call it, so seen-mode skip passes those lines
  (``06`` G1).

The timeline frees the states it drops a few per frame (07 I-11: ``defer_release``, and
``App.rollback_release`` after the story pump), and all that are left at shutdown.

Both are looked up when called (F15 installs after F14), as is F15's ``indicator_right``
for the rewind tag. The overlay's ``LimitCue`` (the textbox's anchor and bump, the shell's
theme and ``play_ui``) becomes the shell's cue layer (A3), and ``[rollback] marker`` turns
the tag on or off. ``engine.script`` is not imported.
"""

from typing import TYPE_CHECKING

from engine.ui.builtin.rollback import LimitCue, RollbackKeys
from engine.ui.menus import MenuEntry

if TYPE_CHECKING:
    from engine.app.app import App


def install_rollback(app: "App") -> RollbackKeys | None:
    """Build and register the launch's ``RollbackKeys`` and keep it on
    ``app.rollback_keys``. None (and nothing registered) without a shell, textbox, or a
    driver with ``rollback_view`` (an App wired by hand)."""
    shell = getattr(app, "shell", None)
    textbox = getattr(app, "textbox", None)
    story = getattr(app, "story", None)
    if shell is None or textbox is None or not hasattr(story, "rollback_view"):
        return None
    time = getattr(app, "time", None)
    clock = (lambda: time.now) if time is not None else None
    config = getattr(app, "config", None)
    marker = config.rollback.marker if config is not None else True
    cue = LimitCue(textbox, theme=shell.theme, play=shell.play_ui)
    keys = RollbackKeys(story, textbox, clock=clock, cue=cue, shell=shell, marker=marker,
                        skip_indicator=lambda: _indicator_right(app))
    textbox.add_overlay(keys)                 # after F10's and F11's, before F15's (A6)
    textbox.add_say_listener(keys.on_say)
    shell.set_cue_layer(cue)                  # layer 6 (A3)
    shell.add_look_listener(cue.restyle)      # F49 (07 I-1): a style's scheme colors
    view = story.rollback_view
    shell.menus.add("quick", MenuEntry("back", action=lambda ctx: keys.request_back(),
                                       enabled=lambda: view().can_back,
                                       visible=lambda: view().shown))
    shell.add_in_game_reset(keys.reset)
    timeline = getattr(getattr(story, "interp", None), "timeline", None)
    if timeline is not None:                  # 07 I-11: free dropped states a few per frame
        timeline.defer_release = True
        app.rollback_release = timeline.release
        add_shutdown = getattr(app, "add_shutdown", None)
        if add_shutdown is not None:          # an App wired by hand (tests) may lack it
            add_shutdown(lambda: timeline.release(None))
    story.add_report_listener(lambda: _note_restore(app))
    story.add_landing_listener(lambda: _reset_skip_auto(app))
    app.rollback_keys = keys
    return keys


def _note_restore(app: "App") -> None:
    saves = getattr(app, "saves", None)
    if saves is not None:
        saves.note_restore()


def _indicator_right(app: "App") -> float | None:
    skip_auto = getattr(app, "skip_auto", None)
    return skip_auto.indicator_right() if skip_auto is not None else None


def _reset_skip_auto(app: "App") -> None:
    skip_auto = getattr(app, "skip_auto", None)
    if skip_auto is not None:
        skip_auto.reset()


__all__ = ["install_rollback"]
