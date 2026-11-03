"""Studio's label graph: which label leads to which (F45 ``04-technical.md`` §2 Q6, §4.1, §5).

Why this module exists: the story map and "Go to label" need label → label links from a
loaded ``Program``, without F20's flow graph (scenes, gates, budgets). The one fact shared
with F20 is that ``Jump`` and ``Call`` name a label; it lives in ``LINK_RULES`` (F20 s2 tests
that its ``FLOW_RULES`` agree; ``07`` I-11; neither table imports the other).

- ``LINK_RULES`` maps a statement word to its node type and the label it names. A
  statement whose doc lists the ``label`` name kind needs a row here or in ``NOT_LINKS``
  (``label`` names itself, it leads nowhere; F20's ``flowchart forget <label>`` forgets that
  label's flowchart nodes and leads nowhere either); the completeness test enforces it.
- A ``jump`` anywhere inside a menu choice's block (an ``if`` in a choice included) is kind
  ``menu``. A ``call`` stays ``call`` even there: the called label comes back, so it is
  never an ending (``07`` I-9).
- F46 (``04`` §3.4, §3.5): a link inside a menu choice's block carries that choice's text
  (``choice``, the innermost choice when choices nest through an ``if``), and
  ``conditional`` is True when that choice has an ``if`` condition (the map's "if" mark).
  Outside every choice they are None and False. ``block_links`` walks one label block, so
  Studio's scene index (``tools/editor/scenes.py``) reads links from a single parsed chunk.
- ``label_links`` and ``block_links`` are pure, deterministic, and iterative: nesting depth
  costs no recursion.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from operator import attrgetter
from types import MappingProxyType
from typing import Final, Literal

from engine.script.menu import Choice, Menu
from engine.script.nodes import Call, Jump, Statement
from engine.script.program import Program

LinkKind = Literal["jump", "call", "menu"]


@dataclass(frozen=True, slots=True)
class LabelLink:
    """``src`` leads to ``dst`` from the statement at ``file`` (a ref), ``line``; ``choice``
    is the text of the menu choice it sits in (None outside a choice), and ``conditional``
    whether that choice has a condition (F46; added last, so positional builds still work)."""

    src: str
    dst: str
    kind: LinkKind
    file: str
    line: int
    choice: str | None = None
    conditional: bool = False


LINK_RULES: Final[Mapping[str, tuple[type, Callable[[Statement], str]]]] = MappingProxyType({
    "jump": (Jump, attrgetter("target")),
    "call": (Call, attrgetter("target")),
})
NOT_LINKS: Final = frozenset({"label", "flowchart"})
_RULES: Final = {node_type: (word, target) for word, (node_type, target) in LINK_RULES.items()}


def block_links(name: str, block: Sequence[Statement]) -> Iterator[LabelLink]:
    """The links of label ``name``'s ``block``, in statement order (pre-order)."""
    # (statements left in this block, whether it is inside a menu choice, innermost choice)
    stack: list[tuple[list[Statement], bool, Choice | None]] = [
        (list(reversed(block)), False, None)]
    while stack:
        pending, in_menu, choice = stack[-1]
        if not pending:
            stack.pop()
            continue
        stmt = pending.pop()
        rule = _RULES.get(type(stmt))
        if rule is not None:
            word, target = rule
            kind = "menu" if in_menu and word == "jump" else word
            yield LabelLink(name, target(stmt), kind,  # type: ignore[arg-type]
                            stmt.file.ref, stmt.line,
                            None if choice is None else choice.text,
                            choice is not None and choice.condition is not None)
        if isinstance(stmt, Menu):
            for inner in reversed(stmt.choices):
                stack.append((list(reversed(inner.block)), True, inner))
            continue
        for inner_block in reversed(stmt.blocks()):
            stack.append((list(reversed(inner_block)), in_menu, choice))


def label_links(program: Program, *, limit: int) -> tuple[tuple[LabelLink, ...], int]:
    """Every link in label order, then statement order (pre-order), at most ``limit`` of
    them, and the total count."""
    links: list[LabelLink] = []
    total = 0
    for name, label in program.labels.items():
        for link in block_links(name, label.block):
            total += 1
            if len(links) < limit:
                links.append(link)
    return tuple(links), total


__all__ = ["LINK_RULES", "NOT_LINKS", "LabelLink", "block_links", "label_links"]
