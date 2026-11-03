"""F32 dynamic UI at run time (F32 ``04-technical.md`` §3, §4.2, §5.2, §9; ``07`` I-1, I-14;
restore warning W205).

Why this module exists: a ``ui`` line changes the game's own interface, and the style and the
Save/Load blocks are story state (saved, rolled back), so the runtime keeps them as plain data
and only says what changed:

- **The state** (``GameState.ui``, a ``UiState``): runtime-held like F30's title.
  ``interp.ui`` is the live value, ``take_checkpoint`` stores it, restore commits the saved one
  (a style the loaded program's config no longer has becomes None with W205), new game sets
  ``EMPTY_UI``. In JSON it is three optional top-level keys, each written only when set
  (``ui_style``; ``save_block`` and ``load_block``: ``true`` for the game's own words, else the
  reason as shown), so a state that never used ``ui`` writes what it wrote before F32.
- **The commands**: ``run_ui`` holds ``UiStyle`` or ``UiBlocks`` (the whole new block state)
  where the line runs, and ``DeleteSaves`` unless F14's quiet forward re-run is running (rolling
  forward never deletes, 04 D5). Never a checkpoint: the next one stores the value.
- **The restore burst** (07 I-1): ``hold_restored`` holds ``UiStyle`` iff the restored or the
  shown style isn't None, and ``UiBlocks`` iff either has a block, right after F30's
  ``WindowTitle``. "Shown" is ``interp._ui_sent`` (runtime-only: the state last held outside a
  quiet re-run), so a forward landing after a re-run that changed the style still sends it.

Pure: no file, clock, randomness, pygame, or ``engine.app``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from engine.core.constants import STYLE_NAME_RE
from engine.runtime.commands import DeleteSaves, UiBlocks, UiStyle
from engine.script.messages import format_message
from engine.script.program import Program
from engine.script.ui import DELETE, SAVING, STYLE, UiStatement, reason_ok

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step

STYLE_KEY: Final = "ui_style"
SAVE_KEY: Final = "save_block"
LOAD_KEY: Final = "load_block"
JSON_KEYS: Final = (STYLE_KEY, SAVE_KEY, LOAD_KEY)
# A wipe that deletes nothing: headless runs (here) and Studio/--playthrough previews
# (app/looks.py, F32 s4) log it once at INFO (07 G1, I-5).
DELETE_PREVIEW_TEXT: Final = "ui delete saves: no saves are deleted in a preview."


@dataclass(frozen=True, slots=True)
class UiState:
    """``GameState.ui`` (04 §3): the ``ui style`` in force (None: the normal look) and the
    Save/Load blocks. A reason is the text as shown; None with a block: the game's own words
    (``[words] saving_off`` / ``loading_off``); always None without one."""

    style: str | None = None
    save_block: bool = False
    save_reason: str | None = None
    load_block: bool = False
    load_reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.save_block or self.load_block

    def blocks(self) -> UiBlocks:
        """The ``UiBlocks`` command of this state."""
        return UiBlocks(self.save_block, self.save_reason, self.load_block, self.load_reason)

    def to_json(self) -> dict[str, object]:
        """The top-level keys of a ``GameState``'s JSON, only those set (04 §3)."""
        out: dict[str, object] = {}
        if self.style is not None:
            out[STYLE_KEY] = self.style
        if self.save_block:
            out[SAVE_KEY] = True if self.save_reason is None else self.save_reason
        if self.load_block:
            out[LOAD_KEY] = True if self.load_reason is None else self.load_reason
        return out

    def save_problem(self) -> str | None:
        """``ui_style`` when ``from_json`` would refuse the style (only a load given no style
        names, a tool's or a test's, lets such a name through), else None."""
        if self.style is not None and not style_ok(self.style):
            return STYLE_KEY
        return None

    @staticmethod
    def from_json(obj: Mapping[str, object]) -> "UiState":
        """The three keys of a saved state's top-level object (untrusted). A key that is
        absent is the default. A style that isn't a style name, or a block that is neither
        ``true`` nor a string, is ``StateInvalid`` with the key's name, never echoing the
        input. A reason that breaks ``reason_ok`` (empty, over 200 code points) is a block with
        the game's own words."""
        from engine.runtime.state import StateInvalid      # state imports this module

        style = obj.get(STYLE_KEY)
        if STYLE_KEY in obj and not style_ok(style):
            raise StateInvalid(STYLE_KEY)
        save, save_reason = _block(obj, SAVE_KEY)
        load, load_reason = _block(obj, LOAD_KEY)
        if style is None and not save and not load:
            return EMPTY_UI
        return UiState(style, save, save_reason, load, load_reason)  # type: ignore[arg-type]


EMPTY_UI: Final = UiState()


def style_ok(name: object) -> bool:
    """A saved style's shape: a config style name (``STYLE_NAME_RE``)."""
    return type(name) is str and STYLE_NAME_RE.fullmatch(name) is not None


def _block(obj: Mapping[str, object], key: str) -> tuple[bool, str | None]:
    if key not in obj:
        return False, None
    value = obj[key]
    if value is True:
        return True, None
    if type(value) is not str:
        from engine.runtime.state import StateInvalid
        raise StateInvalid(key)
    return True, value if reason_ok(value) else None


# --- Running (04 §5.2) --------------------------------------------------------------------

def run_ui(interp: "Interpreter", stmt: UiStatement) -> "Step":
    """A ``ui`` line: the live state changes and its command is held (module docstring)."""
    from engine.runtime.interpreter import Step         # below the interpreter
    form = stmt.form
    if form == DELETE:
        if not interp.timeline.replaying:               # 04 D5: forward never deletes
            interp._hold(DeleteSaves())
        return Step.CONTINUE
    ui = interp.ui
    if form == STYLE:
        ui = replace(ui, style=stmt.style)
        cmd: UiStyle | UiBlocks = UiStyle(stmt.style)
    else:
        reason = None if stmt.on else stmt.reason
        if form == SAVING:
            ui = replace(ui, save_block=not stmt.on, save_reason=reason)
        else:
            ui = replace(ui, load_block=not stmt.on, load_reason=reason)
        cmd = ui.blocks()
    interp.ui = ui
    interp._hold(cmd)
    if not interp.timeline.replaying:                   # a quiet re-run's holds are dropped
        interp._ui_sent = ui
    return Step.CONTINUE


# --- Restore (04 §5.2, 07 I-1) --------------------------------------------------------------

def restored_ui(ui: UiState, program: Program) -> tuple[UiState, str | None]:
    """Restore's ``ui`` and its W205 text: a style the program's config no longer has
    (``Program.style_names``; None: not checked) becomes None. Changes nothing."""
    names = program.style_names
    if ui.style is None or names is None or ui.style in names:
        return ui, None
    return replace(ui, style=None), format_message("W205", (ui.style,))


def hold_restored(interp: "Interpreter", ui: UiState) -> None:
    """Restore step 7 (07 I-1): ``UiStyle`` iff ``ui`` (restore's, already checked) or the
    shown state has a style, then ``UiBlocks`` iff either has a block; then ``ui`` is
    committed."""
    sent = interp._ui_sent
    if ui.style is not None or sent.style is not None:
        interp._hold(UiStyle(ui.style))
    if ui.blocked or sent.blocked:
        interp._hold(ui.blocks())
    interp.ui = ui
    interp._ui_sent = ui


__all__ = ["DELETE_PREVIEW_TEXT", "EMPTY_UI", "JSON_KEYS", "UiState", "hold_restored", "restored_ui", "run_ui",
           "style_ok"]
