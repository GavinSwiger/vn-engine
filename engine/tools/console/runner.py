"""The console's one way into author code, and its Code line (F40 ``04`` §7.3; ``05``
SEC-F40-02, -04, -08, -11; AC-F40-13, -14, -15, -16, -36).

Why this module exists: the Code tab runs real author Python, and an author object's
``__repr__`` is author code too. Any of it may raise anything (``SystemExit``,
``KeyboardInterrupt``, ``MemoryError``, ``StoryError``, ``AuthorRefusal``, …) or never
return. None of that may end the story, reach the error screen, or reach the log, stderr,
or stdout. So every console call into author code goes through ``guarded``:

- ``G["__builtins__"]["print"]`` is swapped for a collector (one line per call, at most
  ``CODE_MAX`` characters in all; nothing is logged) and put back in a ``finally``.
- The call is ``interp.author_call``: between ``guard.enter()`` and ``guard.exit()``, so
  the watchdog can stop it, counted in ``author_calls`` as a ``$`` line is.
- Every ``BaseException`` is caught. When the guard fired (``consume_fired()``) the result
  is ``TOO_LONG``; otherwise one error line ``{type}: {message}`` (the message is itself
  author code, so it is read in a guarded call of its own), redacted and escaped by
  ``echo()``, at most ``CODE_MAX`` characters.
- When the guard fired but no ``KeyboardInterrupt`` arrived (the call returned just as the
  watchdog fired, or caught the interrupt), the watchdog's SIGINT is still on its way: it
  is drained here (``_sleep`` in steps of ``DRAIN_STEP_S`` for up to ``DRAIN_S``), so it
  can't land later as ``App.run``'s E85m.

``run_code(interp, line)``: ``check_line`` first (a refused line runs nothing and changes
nothing), then the line runs in ``interp.console_change`` (04 §7.2: one transaction joined
to the current step, undone when it fails or can't be saved). Its output lines are the
``print`` lines, then the expression's value (``value_text``, its author ``repr`` in one
more guarded call) or ``DONE``, or the error line; then W190's text when the line reads OS
identity (SEC-F40-11: it still runs). The caller checks the context first (04 §7.1: the
story WAITING, no replay, minigame, fake crash or name question); ``run_code`` raises
``ValueError`` when the story isn't waiting.

Imports ``core``, ``script`` and ``runtime`` only; logs nothing.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from engine.core.redact import echo
from engine.runtime.interpreter import Interpreter, Status
from engine.tools.console.codecheck import Refused, check_line, clean_line, message_text
from engine.tools.console.valuetext import CODE_MAX, value_text

DONE = "Done."                                        # 01 §6.3 "Code done" (a statement)
TOO_LONG = "That ran too long and was stopped."       # 01 §6.3 "Too long"
DRAIN_S = 0.5                                         # waiting for a late watchdog SIGINT
DRAIN_STEP_S = 0.01

# Tests replace these to fake a late SIGINT (AC-F40-36).
_sleep: Callable[[float], None] = time.sleep
_clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True, slots=True)
class Guarded:
    """One guarded call: ``ok`` with its ``value``, or ``error`` (one shown line:
    ``TOO_LONG`` or ``{type}: {message}``). ``printed``: its ``print`` lines, each through
    ``echo()``, at most ``CODE_MAX`` characters in all. ``too_long``: the watchdog stopped
    it."""

    ok: bool
    value: object = None
    error: str | None = None
    printed: tuple[str, ...] = ()
    too_long: bool = False


@dataclass(frozen=True, slots=True)
class CodeResult:
    """A Code line's outcome. ``lines``: the output lines to show, in order. ``ran``: author
    code ran (False for a refused line). ``ok``: it ran without an error and the change was
    kept. ``undone``: the reason ``console_change`` undid a change that ran without an
    error (E85e's message or ``save_problem``'s word: the caller shows 01 §6.3's
    "Can't be saved" text with it; ``lines`` then hold only the ``print`` lines and W190's,
    not the value or ``DONE``); else None. ``source``: the line as checked (one line,
    controls dropped, at most 2,000 characters)."""

    source: str
    lines: tuple[str, ...]
    ok: bool
    ran: bool
    undone: str | None = None


class _Printer:
    """The ``print`` a guarded call sees: one line per call, nothing logged or written."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.room = CODE_MAX

    def __call__(self, *args: object, sep: object = " ", end: object = "\n",
                 **kwargs: object) -> None:
        room = self.room
        if room <= 0:
            return
        joiner = sep if isinstance(sep, str) else " "
        parts: list[str] = []
        size = 0
        for arg in args:
            text = str(arg)[:room + 1]            # author __str__: inside the guarded call
            parts.append(text)
            size += len(text) + len(joiner)
            if size > room:
                break
        text = joiner.join(parts)
        if len(text) > room:
            text = text[:max(room - 1, 0)] + "…"
        self.room = room - len(text)
        self.lines.append(text)

    def shown(self) -> tuple[str, ...]:
        return tuple(echo(text, CODE_MAX) for text in self.lines)


def _drain() -> None:
    """Absorb the watchdog's SIGINT that is still on its way (at most ``DRAIN_S``)."""
    deadline = _clock() + DRAIN_S
    try:
        while _clock() < deadline:
            _sleep(DRAIN_STEP_S)
    except KeyboardInterrupt:
        pass


def _call(interp: Interpreter, fn: Callable[..., Any],
          args: tuple) -> tuple[bool, object, BaseException | None, bool]:
    """``interp.author_call(fn, *args)`` with every exception caught: ``(ok, value, error,
    too_long)``. A watchdog stop is ``too_long`` (its late SIGINT drained)."""
    interrupted = False
    error: BaseException | None = None
    value: object = None
    try:
        value = interp.author_call(fn, *args)
    except KeyboardInterrupt as exc:
        interrupted, error = True, exc
    except BaseException as exc:            # SystemExit, MemoryError, StoryError, … (SEC-04)
        error = exc
    try:
        fired = interp.guard.consume_fired()
        if fired and not interrupted:
            _drain()
    except KeyboardInterrupt:               # the late SIGINT landed here instead
        fired = True
    if fired:
        return False, None, error, True
    return error is None, value, error, False


def _exception_text(exc: BaseException) -> str:
    message = str(exc)
    return message if type(message) is str else ""


def _error_line(interp: Interpreter, exc: BaseException) -> str:
    """``{type}: {message}`` through ``echo()``. ``str(exc)`` may be author code (an author
    exception, or an author object in its args), so it is read in a guarded call; when
    that fails too, the type alone is shown."""
    name = type(exc).__name__
    ok, message, _, too_long = _call(interp, _exception_text, (exc,))
    if too_long:
        return TOO_LONG
    text = message[:CODE_MAX + 256] if ok and type(message) is str else ""
    return echo(f"{name}: {text}" if text else name, CODE_MAX)


def guarded(interp: Interpreter, fn: Callable[..., Any], *args: object) -> Guarded:
    """Run ``fn(*args)`` as console author code (module docstring). Never raises."""
    printer = _Printer()
    builtins = interp.G.get("__builtins__")
    swap = type(builtins) is dict
    before = builtins.get("print") if swap else None      # type: ignore[union-attr]
    line: str | None = None
    try:
        if swap:
            builtins["print"] = printer                   # type: ignore[index]
        ok, value, error, too_long = _call(interp, fn, args)
        if too_long:
            line = TOO_LONG
        elif not ok:                                      # its str() may print: still swapped
            line = _error_line(interp, error)             # type: ignore[arg-type]
    finally:
        if swap:
            builtins["print"] = before                    # type: ignore[index]
    if line is not None:
        return Guarded(False, error=line, printed=printer.shown(), too_long=line == TOO_LONG)
    return Guarded(True, value, printed=printer.shown())


def _identity_line() -> str:
    return message_text("W190")


def run_code(interp: Interpreter, line: str) -> CodeResult:
    """Check and run one Code line (module docstring). The story must be WAITING."""
    if interp.status is not Status.WAITING or interp.current is None:
        raise ValueError("run_code: the story isn't waiting")
    checked = check_line(line, interp.program)
    if isinstance(checked, Refused):
        return CodeResult(clean_line(line), (checked.text,), ok=False, ran=False)
    out: list[str] = []
    shown: list[str] = []                   # the value or DONE, kept only with the change

    def apply() -> bool:
        run = eval if checked.mode == "eval" else exec
        result = guarded(interp, run, checked.code, interp.G)
        out.extend(result.printed)
        if not result.ok:
            out.append(result.error or "")
            return False
        if checked.mode == "eval":          # an author repr runs inside the change too
            shown.append(value_text(result.value, CODE_MAX,
                                    lambda fn: guarded(interp, fn)))
        else:
            shown.append(DONE)
        return True

    reason = interp.console_change(apply)
    if reason is None:
        out.extend(shown)
    if checked.reads_identity:
        out.append(_identity_line())
    return CodeResult(checked.source, tuple(out), ok=reason is None, ran=True,
                      undone=reason or None)


__all__ = ["CodeResult", "DONE", "DRAIN_S", "Guarded", "TOO_LONG", "guarded", "run_code"]
