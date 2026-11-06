"""Insert ▸ Show meter / Hide meter (F62 round 2; specs/F62-visible-meters/SPEC.md §7).

Why this module exists: ``show meter hana`` puts a meter in the status corner and ``hide meter
hana`` takes it away (``script/showmeter.py``). These two forms let an author pick the meters
from the game's own instead of typing names. A line can name several; the forms pick up to
three (``METER_SLOTS``), and a longer line shows as script.

Pure Python: ``engine.script`` and ``forms`` only; no Tk (ADR-0008). ``forms._line_forms``
imports this module inside the function, as this one imports ``forms``.
"""

from collections.abc import Callable
from typing import Final

from engine.script.nodes import Statement
from engine.script.showmeter import MeterShow
from engine.tools.editor.forms import CommandForm, Field, Values, _join, _tokens

METER_SLOTS: Final = ("meter", "meter2", "meter3")


def _read(shown: bool) -> Callable[[Statement, str], dict[str, str] | None]:
    def read(node: Statement, code: str) -> dict[str, str] | None:
        if not isinstance(node, MeterShow) or node.shown is not shown \
                or len(node.names) > len(METER_SLOTS):
            return None
        if _tokens(code) != ["show" if shown else "hide", "meter", *node.names]:
            return None
        return {slot: (node.names[i] if i < len(node.names) else "")
                for i, slot in enumerate(METER_SLOTS)}
    return read


def names(values: Values) -> list[str]:
    """The picked meters, in order, each once."""
    return list(dict.fromkeys(name for slot in METER_SLOTS
                              if (name := values.get(slot, "").strip())))


def _write(word: str) -> Callable[[Values], str]:
    return lambda values: _join(word, "meter", *names(values))


_FIELDS: Final = (Field("meter", "Meter", "name", "meter"),
                  Field("meter2", "Another meter", "name", "meter", optional=True),
                  Field("meter3", "A third meter", "name", "meter", optional=True))

FORMS: Final[tuple[CommandForm, ...]] = (
    CommandForm("show_meter", "Show meter", "Show meter", (("show", "show meter"),),
                MeterShow, _FIELDS, _read(True), _write("show"),
                lambda v: ", ".join(names(v))),
    CommandForm("hide_meter", "Hide meter", "Hide meter", (("hide", "hide meter"),),
                MeterShow, _FIELDS, _read(False), _write("hide"),
                lambda v: ", ".join(names(v))),
)

__all__ = ["FORMS", "METER_SLOTS", "names"]
