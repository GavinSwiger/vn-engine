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
- ``label_links`` is pure, deterministic, and iterative: nesting depth costs no recursion.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from operator import attrgetter
from types import MappingProxyType
from typing import Final, Literal

from engine.script.menu import Menu
from engine.script.nodes import Call, Jump, Statement
from engine.script.program import Program

LinkKind = Literal["jump", "call", "menu"]


@dataclass(frozen=True, slots=True)
class LabelLink:
    """``src`` leads to ``dst`` from the statement at ``file`` (a ref), ``line``."""

    src: str
    dst: str
    kind: LinkKind
    file: str
    line: int


LINK_RULES: Final[Mapping[str, tuple[type, Callable[[Statement], str]]]] = MappingProxyType({
    "jump": (Jump, attrgetter("target")),
    "call": (Call, attrgetter("target")),
})
NOT_LINKS: Final = frozenset({"label", "flowchart"})


def label_links(program: Program, *, limit: int) -> tuple[tuple[LabelLink, ...], int]:
    """Every link in label order, then statement order (pre-order), at most ``limit`` of
    them, and the total count."""
    rules = {node_type: (word, target) for word, (node_type, target) in LINK_RULES.items()}
    links: list[LabelLink] = []
    total = 0
    for name, label in program.labels.items():
        # (statements left in this block, whether the block is inside a menu choice)
        stack: list[tuple[list[Statement], bool]] = [(list(reversed(label.block)), False)]
        while stack:
            pending, in_menu = stack[-1]
            if not pending:
                stack.pop()
                continue
            stmt = pending.pop()
            rule = rules.get(type(stmt))
            if rule is not None:
                total += 1
                if len(links) < limit:
                    word, target = rule
                    kind = "menu" if in_menu and word == "jump" else word
                    links.append(LabelLink(name, target(stmt), kind,  # type: ignore[arg-type]
                                           stmt.file.ref, stmt.line))
            blocks = stmt.blocks()
            if blocks:
                inner = in_menu or isinstance(stmt, Menu)
                for block in reversed(blocks):
                    stack.append((list(reversed(block)), inner))
    return tuple(links), total


__all__ = ["LINK_RULES", "NOT_LINKS", "LabelLink", "label_links"]
