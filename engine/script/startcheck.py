"""Load-time checks of the start options (F44 ``04-technical.md`` §5.1; F02 checks step 4b).

The start label (``--start``) and the start-value names (``--set``) come from the command
line, so their errors have no file and no line, and sort after E26 (``FILELESS_ORDER``):

- E26b: the start label is not a label. Its variant follows E43's for the same name
  (case-insensitive suggestion, then "not included" from E43's one lazy scan, then a close
  name, then plain); ``checks.py`` passes that logic in as ``missing_label``.
- E26c: a start-value name is a ``define`` (which never changes), or has no ``default``
  (with a did-you-mean among the defaults).

``checks.py`` skips this step whenever it skips E43 (a file couldn't be read, or a story
limit stopped reading). An explicit start label ``start`` is left to E26.

Until F44 step 1 adds ``core/startvalues.py`` (``StartOptions``), callers pass the label and
the names directly.
"""

from collections.abc import Callable, Collection, Container, Sequence

from engine.script.diagnostics import Diagnostic
from engine.script.suggest import suggest
from engine.script.words import canonical_name

START_LABEL = "start"


def check_start(label: str | None, set_names: Sequence[str], *, labels: Container[str],
                default_names: Collection[str], define_names: Container[str],
                missing_label: Callable[[str], Diagnostic]) -> list[Diagnostic]:
    """E26b for a start label that isn't in ``labels``, then one E26c per start-value name
    that can't be set, in ``set_names`` order. Names are compared in canonical form."""
    found: list[Diagnostic] = []
    if label is not None:
        name = canonical_name(label)
        if name != START_LABEL and name not in labels:
            found.append(missing_label(name))
    for written in set_names:
        name = canonical_name(written)
        if name in define_names:
            found.append(Diagnostic("E26c", args=(name, True)))
        elif name not in default_names:
            found.append(Diagnostic("E26c", args=(name, False, suggest(name, default_names))))
    return found


__all__ = ["START_LABEL", "check_start"]
