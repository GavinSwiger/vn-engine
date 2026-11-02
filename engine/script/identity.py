"""Stable statement identity (ADR-0006, F02 ``04-technical.md`` §7.8).

A statement's identity (sid) is ``"<label>/<h>"``, or ``"<label>/<h>~<n>"`` for the n-th
(n ≥ 2) statement in that label with the same ``h``, counted in pre-order (an ``If`` before
its branches' statements). ``h`` is the first 6 bytes of BLAKE2b, as 12 lower-case hex
digits, of the UTF-8 encoding of ``"\\x1f".join(("v1",) + stmt.identity_key())``. File,
line, column, indentation, nesting, and line wrapping never enter it.

Labels have the identity ``<label>``, defines ``define:<name>``, includes
``include:<path>``. These are declarations, not positions: ``Program.get`` never returns
them. A later feature's declaration node (F03 ``Default``, F04 ``ImageDecl``) registers its
identity with ``register_declaration`` from its own module.

The ``"v1"`` salt and ``IDENTITY_SCHEME`` change together (ADR-0006 clarification 1):
changing a key, the normalization, the hash, or the format is a new scheme.
"""

import hashlib
from collections.abc import Callable, Iterable, Iterator
from typing import Final

from engine.script.limits import IDENTITY_YIELD_ITEMS  # §7.9; shared with checks.py
from engine.script.nodes import Define, Include, Label, Node, Statement

IDENTITY_SCHEME: Final = 1
IDENTITY_SALT: Final = "v1"          # changes together with IDENTITY_SCHEME
_SEPARATOR: Final = "\x1f"
_DIGEST_BYTES: Final = 6

Path = tuple[int, ...]

_DECLARATIONS: dict[type, Callable[[Node], str]] = {
    Define: lambda node: "define:" + node.name,          # type: ignore[attr-defined]
    Include: lambda node: "include:" + node.path,        # type: ignore[attr-defined]
}


def register_declaration(node_type: type[Node], make_sid: Callable[[Node], str]) -> None:
    """Give a top-level declaration node type its identity (for example F03's
    ``default:<name>``). Statements never register here; they define ``identity_key()``."""
    if issubclass(node_type, (Statement, Label)):
        raise ValueError(f"{node_type.__name__} is not a declaration")
    _DECLARATIONS[node_type] = make_sid


def statement_hash(key: tuple[str, ...]) -> str:
    """The 12 hex digits of ADR-0006 for one ``identity_key()``."""
    data = _SEPARATOR.join((IDENTITY_SALT,) + key).encode("utf-8")
    return hashlib.blake2b(data, digest_size=_DIGEST_BYTES).hexdigest()


def declaration_sid(node: Node) -> str | None:
    """The identity of a label or a registered declaration; None for anything else."""
    if isinstance(node, Label):
        return node.name
    make_sid = _DECLARATIONS.get(type(node))
    return make_sid(node) if make_sid is not None else None


def walk_block(block: Iterable[Statement]) -> Iterator[tuple[Statement, Path]]:
    """Every statement of a label block in pre-order with its ``StmtLocation`` path:
    ``(i,)`` is ``block[i]``; ``p + (b, j)`` is ``blocks()[b][j]`` of the statement at ``p``
    (an ``If``'s branch ``b``; F07, a ``Menu``'s choice ``b``). Iterative, so nesting depth
    costs no recursion."""
    stack: list[tuple[Path, Iterator[tuple[Path, Statement]]]] = [
        ((), (((i,), stmt) for i, stmt in enumerate(block)))]
    while stack:
        prefix, items = stack[-1]
        for index, stmt in items:
            path = prefix + index
            yield stmt, path
            blocks = stmt.blocks()
            if blocks:
                stack.append((path, _block_items(blocks)))
                break
        else:
            stack.pop()


def _block_items(blocks: tuple[tuple[Statement, ...], ...]
                 ) -> Iterator[tuple[Path, Statement]]:
    for b, block in enumerate(blocks):
        for j, stmt in enumerate(block):
            yield (b, j), stmt


def iter_assign(nodes: Iterable[Node]) -> Iterator[None]:
    """Assign identities to the top-level nodes of a whole story, in reading order, and to
    every statement inside its labels (setting ``sid``, ``label``, and ``path``). Yields
    every ``IDENTITY_YIELD_ITEMS`` statements so the loader can slice the work (§7.9).

    Call it once, after all whole-game checks pass: each label starts a fresh ``~n``
    count, so label names must already be unique."""
    done = 0
    for node in nodes:
        sid = declaration_sid(node)
        if sid is not None:
            node.sid = sid
        if not isinstance(node, Label):
            continue
        label = node.name
        counts: dict[str, int] = {}
        for stmt, path in walk_block(node.block):
            h = statement_hash(stmt.identity_key())
            n = counts[h] = counts.get(h, 0) + 1
            stmt.sid = sid = f"{label}/{h}" if n == 1 else f"{label}/{h}~{n}"
            stmt.label = label
            stmt.path = path
            for inner in stmt.inner():                      # F07: a menu's question
                inner.sid = sid
                inner.label = label
                inner.path = path
            done += 1
            if done % IDENTITY_YIELD_ITEMS == 0:
                yield


def assign(nodes: Iterable[Node]) -> None:
    """``iter_assign`` run to the end in one go."""
    for _ in iter_assign(nodes):
        pass


__all__ = ["IDENTITY_SALT", "IDENTITY_SCHEME", "IDENTITY_YIELD_ITEMS", "assign",
           "declaration_sid", "iter_assign", "register_declaration", "statement_hash",
           "walk_block"]
