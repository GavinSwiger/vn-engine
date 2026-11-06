"""Present at a menu (F64 SPEC-present): ``present:`` in a menu, a reaction per item and
``else:``.

Why this module exists: a menu can let the player show any item they hold (F25's item
picker) instead of picking a written choice. The option has its own small grammar (the
``present:`` line, one ``<item>:`` line per reaction, then ``else:``), a node the
interpreter branches at, and whole-game checks (item names, key items with no reaction).

::

    menu:
        hana "What's that in your hand?"
        "Nothing.":
            $ pass
        present:
            red_lantern:
                hana happy "You kept it!"
            else:
                hana "...Why are you showing me that?"

- ``PresentOption``: ``Menu.present``, a statement on the ``present:`` line. ``blocks()``
  is one block per reaction (items in script order, ``else`` last), so every walk (paths,
  sids, the story map, reach) sees them like an if/elif/else. ``Menu.blocks()`` ends with
  ``(present,)``. Its key in the menu is ``PRESENT_KEY`` (never a choice text's hash).
- ``present`` is a positional word (ADR-0010): only a menu line ``present:`` or ``present
  if <condition>:`` is the option; ``present "Hi"`` stays dialogue, and ``present`` stays
  free as a name. The lexer reads the condition after ``present if`` as Python.
- Load codes (E442–E446) here; E447 (an unknown item, did-you-mean) and W310 (a key item
  with no reaction) are ``check_story``'s.
- W310's key items: the items this scene unlocks before the menu (``unlock item`` lines
  earlier in the same label). The player has just been given them, so a reaction is
  expected; ``else`` still answers them.
"""

from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import Final

from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.identity import statement_hash, walk_block
from engine.script.lexer import COLON, HEAD_WORD, NAME, RANK_BLOCK, RawStatement
from engine.script.limits import SCRIPT_MAX_BLOCK_DEPTH
from engine.script.messages import format_message
from engine.script.nodes import Label, Node, PyCode, Statement
from engine.script.statements import ParseContext, condition_of
from engine.script.suggest import suggest
from engine.script.words import canonical_name, is_name

WORD_PRESENT: Final = "present"
WORD_ELSE: Final = "else"
# The option's key in its menu (``MenuWait``, ``Pick.choice``): 12 hex like a choice key,
# from a key no choice text can hash to.
PRESENT_KEY: Final = statement_hash(("present-option",))
KEY_ITEMS_SHOWN: Final = 3                 # W310 names this many, then "and N more"


@dataclass(slots=True, kw_only=True)
class Reaction:
    """``<item>:`` (``item`` its canonical name) or ``else:`` (``item`` None) under
    ``present:``, with its block."""

    item: str | None
    line: int
    column: int
    block: tuple[Statement, ...] = ()


@dataclass(slots=True, kw_only=True)
class PresentOption(Statement):
    """``present [if condition]:`` in a menu. Running it enters the reaction for the item
    the pick showed (``Pick.item``), else the ``else`` reaction (always last)."""

    condition: PyCode | None = None
    reactions: tuple[Reaction, ...] = ()

    def identity_key(self) -> tuple[str, ...]:
        return ("present",)

    @property
    def key(self) -> str:
        """Its key in the menu, as a ``Choice``'s (``MenuWait``, ``Pick.choice``)."""
        return PRESENT_KEY

    def blocks(self) -> tuple[tuple[Statement, ...], ...]:
        return tuple(reaction.block for reaction in self.reactions)

    def items(self) -> tuple[str, ...]:
        """The items with a reaction, in script order."""
        return tuple(r.item for r in self.reactions if r.item is not None)

    def reaction_for(self, item: str | None) -> Reaction | None:
        """The reaction for ``item``, else the ``else`` one (None only on a broken node)."""
        fallback = None
        for reaction in self.reactions:
            if reaction.item is None:
                fallback = reaction
            elif reaction.item == item:
                return reaction
        return fallback


def reaction_text(item: str | None) -> str:
    """A reaction as Studio's map and reach name it, in place of a choice's text:
    ``Show red_lantern``, or ``Show any other item`` for ``else``."""
    return f"Show {item}" if item is not None else "Show any other item"


def present_code(condition: str | None = None) -> str:
    """The option's line as Studio writes it: ``present:`` or ``present if <c>:``."""
    return f"{WORD_PRESENT} if {condition}:" if condition else f"{WORD_PRESENT}:"


# --- Parsing (called by script/menu.py) -----------------------------------------------------------

def is_present_line(raw: RawStatement) -> bool:
    """A menu body line that is the option: ``present`` as its first word and a ``:`` at its
    end (or a condition read after ``present if``). ``present "Hi"`` (no colon) is not."""
    return (raw.head == HEAD_WORD and raw.word == WORD_PRESENT
            and (raw.py is not None or raw.ends_with_colon))


def _no_node(raw: RawStatement, ctx: ParseContext) -> None:
    return None


def _header(raw: RawStatement, ctx: ParseContext) -> PresentOption | None:
    """``present:`` or ``present if <condition>:`` (E442 ``words`` for anything else)."""
    condition: PyCode | None = None
    if raw.py is not None:
        condition = condition_of(raw, ctx, keyword="if")
        if condition is None:
            return None
    else:
        tokens = raw.tokens
        if len(tokens) != 2 or tokens[1].kind != COLON:
            colon = tokens[-1].column if tokens[-1].kind == COLON else None
            text = raw.texts.get(raw.line, "")
            start = tokens[1].column - 1
            found = text[start:colon - 1 if colon is not None else None].strip()
            ctx.error("E442", "words", found[:30])
            return None
    return PresentOption(file=raw.file, line=raw.line, end_line=raw.end_line,
                         column=raw.column, condition=condition)


def _reaction_word(raw: RawStatement) -> str | None:
    """``else`` or an item's canonical name when the line is exactly that word and ``:``."""
    tokens = raw.tokens
    if (raw.head == HEAD_WORD and raw.py is None and len(tokens) == 2
            and tokens[0].kind == NAME and tokens[1].kind == COLON and is_name(raw.word)
            and not raw.word[:1].isdigit()):
        return WORD_ELSE if raw.word == WORD_ELSE else canonical_name(raw.word)
    return None


def parse_present(api, line: RawStatement, after: RawStatement | None, depth: int,
                  widths: tuple[int, ...], earlier: bool
                  ) -> Generator[None, None, PresentOption | None]:
    """The ``present`` line (``line``, already consumed and counted) and the lines under it
    (``after`` is the next statement). ``depth`` is the reactions' depth; ``earlier``: the
    menu already has an option (E442 ``twice``, its lines skipped). The node is None after
    an error that leaves no usable option."""
    ctx = api.ctx
    w = line.width
    deeper = after is not None and after.width > w
    if earlier:
        line.error("E442", ("twice",))
        api.parse_line(line, depth - 1, _no_node)
        if deeper:
            yield from api.skip_deeper(w, quiet=True)
        return None
    node, error = api.parse_line(line, depth - 1, _header)
    if not deeper:
        if not error:
            _add(api, line, "E444", ("present",))
        return None
    if node is None:
        yield from api.skip_deeper(w, quiet=True)
        return None
    reactions: list[Reaction] = []
    seen: dict[str, Reaction] = {}
    bad = False
    block_w = after.width                                    # type: ignore[union-attr]
    phantom: int | None = None
    while True:
        sub = yield from api.peek()
        if sub is None or sub.width <= w:
            break
        phantom = api.check_width(sub, block_w, phantom, widths)
        api.reader.next()
        ctx.statement_count += 1
        nxt = yield from api.peek()
        sub_deeper = nxt is not None and nxt.width > sub.width
        word = _reaction_word(sub)
        problem: tuple | None = None
        if word is None:
            problem = ("other",)
        elif WORD_ELSE in seen and word not in seen:
            problem = ("after_else", word)
        if problem is not None:
            sub.error("E443", problem)
            bad = True
            api.parse_line(sub, depth, _no_node)
            if sub_deeper:
                yield from api.skip_deeper(sub.width, quiet=True)
            continue
        api.parse_line(sub, depth, _no_node)
        reaction = Reaction(item=None if word == WORD_ELSE else word, line=sub.line,
                            column=sub.column)
        if word in seen:
            _add(api, sub, "E446", (word, seen[word].line))
            bad = True
            if sub_deeper:
                yield from api.skip_deeper(sub.width, quiet=True)
            continue
        seen[word] = reaction                                # type: ignore[index]
        if not sub_deeper:
            _add(api, sub, "E444", ("reaction", word))
            bad = True
        elif depth + 1 > SCRIPT_MAX_BLOCK_DEPTH:
            nxt.error("E15", rank=RANK_BLOCK)                # type: ignore[union-attr]
            yield from api.skip_deeper(sub.width, quiet=False)
            bad = True
        else:
            block = yield from api.parse_block(sub.width, nxt.width, depth + 1,
                                               widths + (nxt.width,))
            reaction.block = tuple(s for s in block if isinstance(s, Statement))
        reactions.append(reaction)
        if api.due():
            yield
    if WORD_ELSE not in seen:
        if not bad:
            _add(api, line, "E445", ())
        return None
    if bad:
        return None
    node.reactions = tuple(reactions)                        # type: ignore[union-attr]
    return node                                              # type: ignore[return-value]


def _add(api, raw: RawStatement, code: str, args: tuple) -> None:
    api.ctx.sink.add(Diagnostic(code, api.file, raw.line, None, args,
                                source_line=raw.texts.get(raw.line), stmt=raw.line))


# --- Whole game: E447, W310 --------------------------------------------------------------------------

def _options(nodes: list[Node]) -> Iterable[tuple[Label, list]]:
    """Each label with its statements in walk order."""
    for node in nodes:
        if isinstance(node, Label):
            yield node, [stmt for stmt, _ in walk_block(node.block)]


def check_story(nodes: Iterable[Node], add: Callable[[Diagnostic], None]
                ) -> list[ScriptWarning]:
    """E447 at each reaction naming no declared item (did-you-mean among the items; a tip's
    own form); W310 at each option whose scene unlocks an item before the menu that the
    option has no reaction for."""
    from engine.script.codex import CodexEntryDecl, CodexLock   # codex sits above this module
    from engine.script.menu import Menu
    nodes = list(nodes)
    kinds: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, CodexEntryDecl):
            kinds.setdefault(node.name, node.kind)
    items = [name for name, kind in kinds.items() if kind == "item"]
    out: list[ScriptWarning] = []
    for label, stmts in _options(nodes):
        given: list[str] = []
        for stmt in stmts:
            if isinstance(stmt, CodexLock):
                if stmt.unlock and stmt.kind == "item" and stmt.name not in given:
                    given.append(stmt.name)
                continue
            if not isinstance(stmt, Menu) or stmt.present is None:
                continue
            option = stmt.present
            source = stmt.file
            for reaction in option.reactions:
                name = reaction.item
                if name is None or kinds.get(name) == "item":
                    continue
                args = (("tip", name) if kinds.get(name) == "tip"
                        else ("unknown", name, suggest(name, items)))
                add(Diagnostic("E447", source, reaction.line, None, args, stmt=reaction.line))
            missing = [name for name in given if name not in option.items()
                       and kinds.get(name) == "item"]
            if missing:
                shown = missing[:KEY_ITEMS_SHOWN]
                out.append(ScriptWarning(
                    format_message("W310", (tuple(shown), len(missing) - len(shown))),
                    code="W310", file=source.ref, line=option.line))
    return out


__all__ = ["KEY_ITEMS_SHOWN", "PRESENT_KEY", "PresentOption", "Reaction", "WORD_ELSE",
           "WORD_PRESENT", "check_story", "is_present_line", "parse_present",
           "present_code", "reaction_text"]
