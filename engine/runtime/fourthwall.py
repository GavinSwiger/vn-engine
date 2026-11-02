"""F30 fourth-wall tricks at run time (F30 ``04-technical.md`` §3, §4.2, §5.4, §6.1; ``07``
I-4, I-7; run codes E170/E171 at a crash).

Why this module exists: ``effect window_title`` and ``effect crash`` change what the window
shows, but only the title is story state. So the runtime keeps:

- **The title** (``GameState.window_title``, ``str | None``; None is ``[game] title``).
  Runtime-held like ``glitch``: ``interp.window_title`` is the live value, ``take_checkpoint``
  stores it, restore commits the saved one, new game sets None. ``run_title`` sets it and
  holds ``WindowTitle`` at once (not a checkpoint: the next checkpoint stores it). A restore
  uses a saved title only if the loaded program writes it (``title_ok``, SEC-F30-09(a));
  any other is replaced with None and logs one DEBUG line holding no part of it (G9). The
  restore burst holds ``WindowTitle`` iff the restored or the shown title isn't None
  (``interp._title_sent``, runtime-only: the title last held, so a forward landing after a
  quiet re-run still resets a title the re-run changed). ``clear_title`` (an ending card)
  puts the game title back.
- **The crash** is a story wait, never a checkpoint and never saved: ``run_crash`` resolves the
  message (``{var}`` and ``{username=var}`` errors are E170/E171 at the statement; flagged
  ``{username}`` spans hold the fallback word), flushes the stage, and waits through
  ``begin_wait(make=partial(FakeCrash, body=...))`` (07 I-4). A quiet F14 re-run holds no
  ``FakeCrash`` (``begin_wait``'s rule).

``uses_crash`` and ``name_lines`` are read-only program scans for the presentation (the
Settings row rule, W189). Pure: no file, clock, randomness, pygame, or ``engine.meta``.
"""

from collections.abc import Iterator
from functools import partial
from typing import TYPE_CHECKING

from engine.runtime.commands import FakeCrash, NameMark, TaggedText, WindowTitle
from engine.runtime.stage import flush_stage
from engine.runtime.text import resolve_tagged
from engine.script.fourthwall import CrashEffect, TitleEffect
from engine.script.nodes import Say, Statement
from engine.script.program import Program

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.state import GameState


def run_title(interp: "Interpreter", stmt: TitleEffect) -> "Step":
    """``effect window_title``: the live title, held as ``WindowTitle`` (04 §5.4)."""
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    _set(interp, stmt.text)
    return Step.CONTINUE


def run_crash(interp: "Interpreter", stmt: CrashEffect) -> "Step":
    """``effect crash``: the message resolved now, the stage flushed, then a ``FakeCrash``
    wait (04 §5.4, 07 I-4)."""
    body = stmt.body
    if body is not None:
        body = resolve_tagged(interp, body, restoring=False, owner=stmt)
    flush_stage(interp)
    return interp.begin_wait(stmt, seconds=None, for_stage=False,
                             make=partial(FakeCrash, body=body))


def clear_title(interp: "Interpreter") -> None:
    """An ending card (04 §6.1 step 2): the game title, held as ``WindowTitle(None)``, when
    a title is set."""
    if interp.window_title is not None:
        _set(interp, None)


def _set(interp: "Interpreter", title: str | None) -> None:
    interp.window_title = title
    interp._hold(WindowTitle(title))
    if not interp.timeline.replaying:                   # a quiet re-run's holds are dropped
        interp._title_sent = title


def title_ok(program: Program, title: str | None) -> bool:
    """Whether a saved title may be shown (SEC-F30-09(a), 07 I-7): None, or the shown text
    of a ``TitleEffect`` in ``program``."""
    return title is None or title in program.window_titles


def restored_title(program: Program, state: "GameState") -> str | None:
    """Restore's title (04 §6.1 step 3): the saved one if ``title_ok``, else None. Changes
    nothing, so restore's transaction can put it in its snapshot."""
    title = state.window_title
    return title if title_ok(program, title) else None


def hold_restored(interp: "Interpreter", saved: str | None, title: str | None) -> None:
    """Restore step 7 (04 §4.3): a refused ``saved`` title (``title`` is restore's
    ``restored_title``) logs one DEBUG line (area ``runtime``) holding no part of it (G9);
    ``WindowTitle(title)`` is held iff ``title`` or the title shown isn't None; then
    ``title`` is committed."""
    if saved != title:
        interp.log.debug("A saved window title isn't one this script writes; the game "
                         "title is shown instead.")
    if title is not None or interp._title_sent is not None:
        interp._hold(WindowTitle(title))
    interp.window_title = title
    interp._title_sent = title


# --- Program scans (04 §4.2; the presentation's) ---------------------------------------------

def _statements(program: Program) -> Iterator[Statement]:
    for stmt in program.iter_statements():
        yield stmt
        yield from stmt.inner()                         # F07: a menu's question


def uses_crash(program: Program) -> bool:
    """Whether ``program`` has an ``effect crash`` (the Settings row rule, 04 §6.7)."""
    return any(type(stmt) is CrashEffect for stmt in program.iter_statements())


def name_lines(program: Program) -> list[tuple[str, int]]:
    """``(file ref, line)`` of each statement whose text holds ``{username}`` (W189), in
    reading order."""
    out: list[tuple[str, int]] = []
    for stmt in _statements(program):
        body: TaggedText | None = None
        if type(stmt) is Say:
            body = stmt.body
        elif type(stmt) is CrashEffect:
            body = stmt.body
        if body is not None and any(type(p) is NameMark for p in body.pieces):
            out.append((stmt.file.ref, stmt.line))
    return out


__all__ = ["clear_title", "hold_restored", "name_lines", "restored_title", "run_crash",
           "run_title", "title_ok", "uses_crash"]
