"""``install_check_roll``: F59's dice roll in the window (``CheckRolled`` → ``show_roll``).

Why this module exists: the runtime only says what was rolled (a ``CheckRolled`` story
wait); the stage owns waits and ``app`` owns the screens, so the handler lives here, wired
once per launch from ``install_story``. The router picks the most specific type, so the
stage's ``StoryWait`` handler never sees a roll.

``show_roll``: the stage takes the wait first (a press, skip, a restore or New Game ends
it), then ``CheckRollScreen`` goes on top with the current look's choice theme and faces.
While skip runs it shows the landed dice for the frame skip needs to pass the wait, as
Reduce motion shows them at once (``reduce`` is either).
"""

from typing import TYPE_CHECKING

from engine.runtime.commands import CheckRolled, WaitDone
from engine.ui.builtin.check_roll import CheckRollScreen

if TYPE_CHECKING:
    from engine.app.app import App


def show_roll(app: "App", cmd: CheckRolled) -> None:
    """The ``CheckRolled`` handler (module docstring)."""
    stage = app.stage_screen
    choices = getattr(app, "choices", None)
    shell = getattr(app, "shell", None)
    if stage is None or choices is None or shell is None:   # an App wired by hand
        stage_wait = getattr(stage, "start_wait", None)
        if stage_wait is not None:
            stage_wait(cmd)
        elif app.story is not None:
            app.story.post(WaitDone(cmd.wait_id))
        return
    stage.start_wait(cmd)
    textbox = getattr(app, "textbox", None)

    def reduce() -> bool:
        skip = getattr(app, "skip_auto", None)
        if skip is not None and skip.skipping:
            return True
        of = getattr(textbox, "reduce_motion", None)
        return bool(of()) if callable(of) else bool(app.config.effects.reduce)

    def top() -> float | None:
        if textbox is None or getattr(textbox, "nvl_on", False) or textbox.hidden:
            return None
        return float(textbox.tab_top())

    screen = CheckRollScreen(
        cmd, theme=choices.theme, faces=choices.faces, painter=shell.painter,
        stack=app.screens, waiting=lambda: stage.wait_id == cmd.wait_id, reduce=reduce,
        top=top, text_scale=shell.painter.text_scale,
        focused=lambda: bool(getattr(app, "focused", True)))
    app.screens.push(screen)


def install_check_roll(app: "App") -> None:
    """Once per launch, after ``install_choices`` and ``install_ui``: ``CheckRolled`` →
    ``show_roll``."""
    app.router.register(CheckRolled, lambda cmd: show_roll(app, cmd))


__all__ = ["install_check_roll", "show_roll"]
