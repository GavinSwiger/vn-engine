"""The Choice form's Check dialog (F59 SPEC §5): which meter an option tests, and how hard.

Why this module exists: a check is two words in the script (``check logic hard``), but an
author picks it best from the meters they declared and a list of difficulty words, seeing
the odds change as they go. ``ask_check`` returns the check as written (``"logic hard"``),
"" for "No check", or None for Cancel. ``check_label`` is the option row's button text and
``odds_line`` the dialog's live odds (pure, tested without Tk).
"""

import tkinter as tk
from collections.abc import Sequence
from tkinter import ttk
from typing import Final

from engine.script.choicecheck import TIERS, meter_title, odds, parse_difficulty
from engine.tools.editor import dialogs
from engine.tools.editor.formtools import _error_label

TITLE: Final = "Check"
NO_CHECK: Final = "No check"
METER: Final = "Meter"
DIFFICULTY: Final = "Difficulty"
REMOVE: Final = "No check"
CANCEL: Final = "Cancel"
OK: Final = "OK"
EXPLAIN: Final = ("Two dice plus the meter must reach the difficulty. Players see the odds on "
                  "the button and get one try; write what happens under success: and "
                  "failure:.")
PICK_METER: Final = "Pick a meter (declare meters in the Database, under Meters)."
PICK_DIFFICULTY: Final = "Pick a difficulty word, or a number from 1 to 99."
SAMPLE_VALUES: Final = (0, 2, 4, 6, 8, 10)


def check_label(check: str) -> str:
    """The option row's button: ``No check`` or ``Logic · Hard``."""
    parts = check.split()
    if len(parts) != 2:
        return NO_CHECK
    return f"{meter_title(parts[0])} · {parts[1].capitalize()}"


def difficulty_choices() -> list[str]:
    """The Difficulty list: ``medium (10)`` and so on."""
    return [f"{word} ({value})" for word, value in TIERS]


def difficulty_written(text: str) -> str:
    """What the script gets for the Difficulty field: a tier word (``medium (10)`` →
    ``medium``) or the number as typed."""
    word = text.strip().split(" ")[0].lower() if text.strip() else ""
    return word


def odds_line(meter: str, difficulty: str) -> str:
    """``Odds when logic is 0: 3% · 2: 8% · …``, or "" while the fields aren't valid."""
    level = parse_difficulty(difficulty_written(difficulty))
    if not meter.strip() or level is None:
        return ""
    parts = [f"{value}: {odds(value, level)}%" for value in SAMPLE_VALUES]
    return f"Odds when {meter.strip()} is " + " · ".join(parts)


class CheckDialog:
    """Meter (the declared meters), Difficulty (tier words, or a number typed), the odds,
    and OK / No check / Cancel. ``result``: the check as written, "" or None."""

    def __init__(self, parent: tk.Misc, check: str, meters: Sequence[str]) -> None:
        self.result: str | None = None
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(TITLE)
        body, scale = dialogs._body(dialog)
        gap = round(8 * scale)
        ttk.Label(body, text=EXPLAIN, style="Dialog.Hint.TLabel", justify="left",
                  wraplength=round(380 * scale)).pack(anchor="w")
        parts = check.split()
        meter = parts[0] if parts else (meters[0] if len(meters) == 1 else "")
        level = parts[1] if len(parts) > 1 else "medium"
        shown = next((c for c in difficulty_choices() if c.split(" ")[0] == level), level)
        self.meter = tk.StringVar(dialog, value=meter)
        self.level = tk.StringVar(dialog, value=shown)
        grid = ttk.Frame(body, style="Dialog.TFrame")
        grid.pack(anchor="w", fill="x", pady=(gap, 0))
        for row, (label, var, values, width) in enumerate((
                (METER, self.meter, list(meters), 18),
                (DIFFICULTY, self.level, difficulty_choices(), 18))):
            ttk.Label(grid, text=label, style="Dialog.TLabel").grid(
                row=row, column=0, sticky="w", pady=(gap if row else 0, 0))
            box = ttk.Combobox(grid, textvariable=var, values=values, width=width)
            box.grid(row=row, column=1, sticky="w", padx=(gap, 0), pady=(gap if row else 0, 0))
            if row == 0:
                self.meter_box = box
        self.odds = ttk.Label(body, text="", style="Dialog.TLabel")
        self.odds.pack(anchor="w", pady=(gap, 0))
        self.problem = _error_label(body, scale)
        self.problem.pack(anchor="w", pady=(round(4 * scale), 0))
        self.buttons = dialogs._buttons(dialog, body, (OK, REMOVE, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(2))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(2))
        for var in (self.meter, self.level):
            var.trace_add("write", lambda *_a: self._changed())
        self._changed()

    def value(self) -> str:
        return f"{self.meter.get().strip()} {difficulty_written(self.level.get())}".strip()

    def why_not(self) -> str | None:
        meter = self.meter.get().strip()
        if not meter.isidentifier() or meter.startswith("_"):
            return PICK_METER
        if parse_difficulty(difficulty_written(self.level.get())) is None:
            return PICK_DIFFICULTY
        return None

    def _changed(self) -> None:
        why = self.why_not()
        self.problem.configure(text=why or "")
        self.odds.configure(text=odds_line(self.meter.get(), self.level.get()))
        self.buttons[0].state(["disabled"] if why else ["!disabled"])

    def _pick(self, index: int) -> None:
        if index == 0:
            if self.why_not() is not None:
                return
            self.result = self.value()
        elif index == 1:
            self.result = ""
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> str | None:
        dialogs._run(parent, self.dialog, self.meter_box)
        return self.result


def ask_check(parent: tk.Misc, check: str, meters: Sequence[str]) -> str | None:
    """The Check dialog, modal: the check as written, "" for none, or None (Cancel)."""
    return CheckDialog(parent, check, meters).run(parent)


__all__ = ["CheckDialog", "NO_CHECK", "ask_check", "check_label", "difficulty_choices",
           "difficulty_written", "odds_line"]
