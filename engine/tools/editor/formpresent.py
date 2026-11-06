"""The Choice form's "Accept an item" (F64 SPEC-present): a menu's ``present:`` option in
Studio. Pure: no Tk.

Why this module exists: the Choice form reads and patches a menu without regenerating it
(``forms.choice_patches``); the present option is one more unit at the menu's end, with a
reaction per item and one for any other item. This module reads it into ``PresentValues``,
writes it back as line patches, and gives the Events rows under the menu.

- ``read_present``: the option's condition and reactions. A reaction whose lines are one
  ``jump`` (or ``$ pass``) is editable ("Goes to"); anything else is kept as written
  (``in_text``), as a choice's lines are.
- ``present_patch``: the whole option rewritten from its old units (comments and reaction
  lines kept; only headers and managed ``jump``/``$ pass`` lines change), a new option
  appended after the choices, or the option removed. Removing the option, or a reaction,
  that has lines of its own is refused (``PRESENT_REMOVE_TEXT``).
- ``present_problems``: an item left empty, or one item twice.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.script.choicepresent import WORD_ELSE, PresentOption, present_code
from engine.script.menu import Menu
from engine.tools.editor.scenes import SceneRead

ACCEPT_ITEM: Final = "Accept an item"
ANY_OTHER_ITEM: Final = "Any other item"
SHOWS: Final = "Shows {item}"                 # an Events row of a reaction
PRESENT_ITEM_TEXT: Final = "Pick an item for each reaction."
PRESENT_TWICE_TEXT: Final = "Each item can have one reaction. Pick another item."
PRESENT_REMOVE_TEXT: Final = ("To remove a reaction with lines of its own, edit its lines in "
                              "the script.")


@dataclass(frozen=True, slots=True)
class ReactionItem:
    """One reaction: the item (``""`` for "any other item"), where it goes (a scene, or None
    for "continues here"), ``in_text`` (its lines stay as written) and ``old`` (the index of
    the reaction it was read from, else is last; None: new)."""

    item: str = ""
    goes: str | None = None
    in_text: bool = False
    old: int | None = None


@dataclass(frozen=True, slots=True)
class PresentValues:
    """The option: its "Only show when" condition, the item reactions in order, and the
    reaction for any other item (``else``)."""

    condition: str = ""
    reactions: tuple[ReactionItem, ...] = ()
    other: ReactionItem = field(default_factory=ReactionItem)


def present_index(scene: SceneRead, menu: int) -> int | None:
    """The statement index of the menu's present option, or None."""
    path = scene.statements[menu].path
    node = scene.statements[menu].node
    if not isinstance(node, Menu) or node.present is None:
        return None
    want = path + (len(node.choices), 0)
    return next((i for i, s in enumerate(scene.statements) if s.path == want), None)


def menu_index(scene: SceneRead, stmt: int) -> int:
    """``stmt``, or for a present option the menu that holds it."""
    read = scene.statements[stmt]
    if not isinstance(read.node, PresentOption):
        return stmt
    owner = read.path[:-2]
    return next((i for i, s in enumerate(scene.statements) if s.path == owner), stmt)


def _reaction_blocks(scene: SceneRead, option: int) -> list[int]:
    from engine.tools.editor.forms import _choice_blocks
    return _choice_blocks(scene, option)


def read_present(scene: SceneRead, menu: int) -> PresentValues | None:
    """The form's values for the menu's present option, or None without one."""
    from engine.tools.editor.forms import _goes
    at = present_index(scene, menu)
    if at is None:
        return None
    node = scene.statements[at].node
    assert isinstance(node, PresentOption)
    items: list[ReactionItem] = []
    other = ReactionItem()
    for n, (reaction, block) in enumerate(zip(node.reactions,
                                              _reaction_blocks(scene, at))):
        goes, in_text = _goes(scene, scene.blocks[block].members)
        item = ReactionItem(reaction.item or "", goes, in_text, n)
        if reaction.item is None:
            other = item
        else:
            items.append(item)
    condition = node.condition.source if node.condition is not None else ""
    return PresentValues(condition, tuple(items), other)


def present_problems(values: PresentValues | None) -> str | None:
    """The form's problem line for the option, or None."""
    if values is None:
        return None
    names = [r.item.strip() for r in values.reactions]
    if any(not name for name in names):
        return PRESENT_ITEM_TEXT
    if len(set(names)) != len(names) or WORD_ELSE in names:
        return PRESENT_TWICE_TEXT
    return None


def summary_of(reaction: ReactionItem) -> str:
    """Where a reaction goes, as the form shows it."""
    from engine.tools.editor.forms import CONTINUES, IN_TEXT
    if reaction.in_text:
        return IN_TEXT
    return CONTINUES if reaction.goes is None else reaction.goes


def new_lines(values: PresentValues, indent: str, unit: str) -> list[str]:
    """A new option's lines at ``indent`` (the choices' indent)."""
    from engine.tools.editor.forms import _target_code
    out = [indent + present_code(values.condition.strip())]
    for reaction in (*values.reactions, values.other):
        word = WORD_ELSE if reaction is values.other else reaction.item.strip()
        out += [indent + unit + f"{word}:", indent + unit + unit + _target_code(reaction.goes)]
    return out


def present_patch(scene: SceneRead, menu: int, lines: Sequence[str],
                  old: PresentValues | None, new: PresentValues | None, *,
                  choice_indent: str, step: str) -> tuple[int, int, tuple[str, ...]] | str | None:
    """The one patch for the option (``(first, last, lines)``, chunk-relative; ``last =
    first - 1`` inserts), None when nothing changes, or a refusal text. A new option is
    returned with ``first`` 0: the caller puts it after the choices."""
    from engine.tools.editor.forms import _apply, _goes_patch_lines, _indent, code_of
    if new is None and old is None:
        return None
    if new is None:
        assert old is not None
        if any(r.in_text for r in (*old.reactions, old.other)):
            return PRESENT_REMOVE_TEXT
        at = present_index(scene, menu)
        assert at is not None
        span = scene.statements[at].unit
        return (span.first, span.last, ())
    if old is None:
        return (0, -1, tuple(new_lines(new, choice_indent, step)))
    at = present_index(scene, menu)
    assert at is not None
    option = scene.statements[at]
    blocks = [scene.blocks[b] for b in _reaction_blocks(scene, at)]
    olds = {r.old: r for r in (*old.reactions, old.other)}
    kept = {r.old for r in (*new.reactions, new.other) if r.old is not None}
    if any(r.in_text and r.old not in kept for r in olds.values()):
        return PRESENT_REMOVE_TEXT
    head = option.head
    _, comment = code_of(lines[head.first - 1:head.last])
    out = [_indent(lines[head.first - 1]) + present_code(new.condition.strip()) + comment]
    react_indent = next((_indent(lines[b.head.first - 1]) for b in blocks if b.head),
                        choice_indent + step)
    for reaction in (*new.reactions, new.other):
        word = WORD_ELSE if reaction is new.other else reaction.item.strip()
        if reaction.old is None or reaction.old not in olds or reaction.old >= len(blocks):
            out += [react_indent + f"{word}:",
                    react_indent + step + ("$ pass" if reaction.goes is None
                                           else f"jump {reaction.goes}")]
            continue
        block, was = blocks[reaction.old], olds[reaction.old]
        unit = block.unit
        assert unit is not None and block.head is not None
        body = list(lines[unit.first - 1:unit.last])
        patches = _goes_patch_lines(scene, lines, block, was.goes, was.in_text,
                                    reaction.goes)
        body = _apply(body, unit.first, patches)
        index = block.head.first - unit.first
        if word != (was.item or WORD_ELSE):
            _, c = code_of([body[index]])
            body[index] = _indent(body[index]) + f"{word}:" + c
        out += body
    span = option.span
    if tuple(out) == tuple(lines[span.first - 1:span.last]):
        return None
    return (span.first, span.last, tuple(out))


def rows_for(scene: SceneRead, menu: int, block: int, depth: int,
             branches) -> list[tuple]:
    """The Events tasks under a menu for its option: ``("present", option, block, depth)``
    then, per reaction, ``("reaction", option, reaction block, depth + 1, item)`` and its
    lines (``("block", b, depth + 2, 0)``)."""
    at = present_index(scene, menu)
    if at is None:
        return []
    node = scene.statements[at].node
    assert isinstance(node, PresentOption)
    out: list[tuple] = [("present", at, block, depth)]
    for b, reaction in zip(branches(at), node.reactions):
        out += [("reaction", at, b, depth + 1, reaction.item), ("block", b, depth + 2, 0)]
    return out


def reaction_word(item: str | None) -> str:
    """An Events row's word for a reaction."""
    return SHOWS.format(item=item) if item else ANY_OTHER_ITEM


__all__ = ["ACCEPT_ITEM", "ANY_OTHER_ITEM", "PRESENT_ITEM_TEXT", "PRESENT_REMOVE_TEXT",
           "PRESENT_TWICE_TEXT", "PresentValues", "ReactionItem", "menu_index", "new_lines",
           "present_index", "present_patch", "present_problems", "reaction_word",
           "read_present", "rows_for", "summary_of"]
