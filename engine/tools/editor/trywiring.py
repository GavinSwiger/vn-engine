"""Studio's **Try it** (F47 ``01-design.md`` PR-F47-20, §6 "Try it"; ``04-technical.md``
§7.5 P2-F; AC-F47-30).

Why this module exists: an author previews an effect in one click. Try it starts the game
as its own child, ``python -m engine run GAME --report-to-editor --try-stdin``, writes the
lines ``stageat`` built on its stdin and closes it; the child plays them in a small window
and closes itself after the 2-second hold. It is launched like Preview (``preview``'s
runner, ``POLL_INTERVAL_MS`` polling through ``RunWiring.join_runner``), but it is not
Play's runner, so a running game isn't touched. One try window at a time: a second Try it
ends the first. Nothing is saved first, and the child writes nothing (``app/trystory.py``).

A failure ("Didn't start", an error, an unexpected stop) goes to the requester's
``on_problem`` as ``COULDNT_TRY`` with the first reason, without the throwaway label's
file and line.

Imports the standard library and its own package; never pygame or tkinter.
"""

import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from engine.core.childcmd import engine_argv
from engine.tools.editor import stageat
from engine.tools.editor.preview import PreviewEvent, PreviewRunner, PreviewState, Report

TRY_IT = "Try it"
COULDNT_TRY = "Couldn't try it: {reason}"
STOPPED = "the game window stopped unexpectedly."
NO_GAME = "there's no game folder open."
_PLACE = re.compile(r"^script/main\.vns, line \d+: ")
Problem = Callable[[str], None]


def try_argv(game_dir: Path) -> list[str]:
    """The try child's command line (04 §7.5)."""
    return engine_argv("run", str(game_dir), "--report-to-editor", "--try-stdin")


def try_bytes(lines: Sequence[str]) -> bytes:
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def reason_of(event: PreviewEvent) -> str | None:
    """The failure text of ``event`` (``COULDNT_TRY``), or None when it isn't one."""
    if event.state is PreviewState.STOPPED_UNEXPECTED:
        return COULDNT_TRY.format(reason=STOPPED)
    if event.state not in (PreviewState.DIDNT_START, PreviewState.STOPPED_ERROR):
        return None
    report: Report | None = event.report
    items = report.items if report is not None else ()
    text = items[0].text if items else (report.paragraphs()[0] if report is not None and
                                        report.paragraphs() else STOPPED)
    return COULDNT_TRY.format(reason=_PLACE.sub("", text))


class TryRunner(PreviewRunner):
    """``PreviewRunner`` whose child gets the try lines on stdin, which is then closed."""

    data = b""

    def play(self, argv: Sequence[str], data: bytes) -> None:
        self.data = data
        self.start(argv)

    def _spawn(self, argv: list[str], stdin_data: bytes | None = None) -> None:
        super()._spawn(argv, self.data)
        child = self._child
        if child is not None:
            child.writer.close()                    # the lines end there (EOF)


class TryIt:
    """A Studio window's Try it: the runner, joined to the window's poll loop on first
    use, and the last requester's ``on_problem``."""

    def __init__(self, win: Any, runner: Any = None) -> None:
        self.win = win
        self.runner = runner if runner is not None else TryRunner()
        self.on_problem: Problem | None = None
        win.join_runner(self.runner, self.events)

    def play(self, lines: Sequence[str], on_problem: Problem | None = None) -> None:
        """Play ``lines`` (``stageat``'s) in a new try window."""
        self.on_problem = on_problem
        paths = getattr(self.win, "paths", None)
        if paths is None:
            self._problem(COULDNT_TRY.format(reason=NO_GAME))
            return
        self.runner.play(try_argv(paths.root), try_bytes(lines))

    def events(self, events: Sequence[PreviewEvent]) -> None:
        for event in events:
            text = reason_of(event)
            if text is not None:
                self._problem(text)

    def _problem(self, text: str) -> None:
        if self.on_problem is not None:
            try:
                self.on_problem(text)
            except Exception:   # noqa: BLE001  (the form that asked may be closed)
                pass


def try_it(win: Any) -> TryIt:
    """``win``'s ``TryIt``, made on first use."""
    found = win.__dict__.get("try_it")
    if found is None:
        found = win.__dict__["try_it"] = TryIt(win)
    return found


def row_stage(win: Any) -> tuple[str, ...]:
    """The stage at the Events tab's selected row (the row a form edits, or the one Insert
    goes above): ``stageat.stage_at`` over the scene's lines above it; empty (black) when
    there is none."""
    story = getattr(win, "story", None)
    if story is None or getattr(story, "ref", None) is None:
        return ()
    index = story.view.selected()
    line = story.line_of(index) if index is not None else None
    record = win.files.get(story.ref)
    start = getattr(story, "start", None)
    if line is None or record is None or start is None:
        return ()
    text = record.widget.get("1.0", "end-1c")
    return stageat.stage_at(text.split("\n")[start - 1:line - 1])


def try_form_line(win: Any, line: str, on_problem: Problem | None = None) -> None:
    """A form's Try it: ``line`` over the stage at its row."""
    try:
        lines = stageat.form_try_lines(row_stage(win), line)
    except ValueError:
        return
    try_it(win).play(lines, on_problem)
