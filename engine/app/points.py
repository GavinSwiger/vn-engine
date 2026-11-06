"""``install_points``: F22's meters on the F3 overlay (F22 ``SPEC.md`` UI-F22-01;
``07-architecture-review.md`` I-1, I-10).

Why this module exists: ``render`` draws strings only, and the overlay must not reach into the
runtime, so the lines are built here from the launch's ``Points`` (``interp.points``): one line
per declared meter in declaration order, ``<name> <value>``, plus `` (<low>-<high>)`` when the
declaration gave a range; past ``MAX_METER_LINES`` meters, ``+N more``. Values are live, read
each time the App asks. Nothing is shown before a game starts (the interpreter is idle).

``install_story`` calls it once per launch. Dev runs only: release adds no provider (ADR-0005:
zero cost), and the App calls providers only while the overlay is on, never in error mode.
A meter with ranks (F62) shows its rank after the value, ``hana 5 (0-10) Friend``.

F62 round 1: it also registers the ``MeterNotice`` handler, every launch: the notice goes to
``shell.notify`` like F21's codex notices (none before the shell exists).
"""

from typing import TYPE_CHECKING

from engine.runtime.commands import MeterNotice
from engine.runtime.interpreter import Status

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.interpreter import Interpreter
    from engine.runtime.points import Points

MAX_METER_LINES = 12


def meter_lines(points: "Points") -> list[str]:
    """The overlay lines for ``points`` (module docstring); empty with no meters."""
    names = points.names()
    out: list[str] = []
    for name in names[:MAX_METER_LINES]:
        line = f"{name} {points.get(name)}"
        spec = points.spec(name)
        if spec.ranged:
            line += f" ({spec.low}-{spec.high})"
        if spec.ranks:
            line += f" {spec.rank(points.get(name)) or '-'}"
        out.append(line)
    if len(names) > MAX_METER_LINES:
        out.append(f"+{len(names) - MAX_METER_LINES} more")
    return out


def install_points(app: "App", interp: "Interpreter") -> None:
    """Dev runs: add the meters' provider to ``app.overlay_lines``. Release (or an App wired
    by hand, with no ``overlay_lines``): nothing. Every launch: the ``MeterNotice`` handler."""

    def on_notice(cmd: MeterNotice) -> None:
        shell = getattr(app, "shell", None)
        if shell is not None:
            shell.notify(cmd.text)

    app.router.register(MeterNotice, on_notice)
    providers = getattr(app, "overlay_lines", None)
    if not getattr(app, "dev", False) or providers is None:
        return

    def provider() -> list[str]:
        if interp.status is Status.IDLE:                # no game yet (07 I-10)
            return []
        return meter_lines(interp.points)

    providers.append(provider)
