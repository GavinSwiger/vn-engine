"""Minigame signatures read from plugin source text, without running it (F45 Studio, AC-F45-52;
F23 ``minigame`` lines).

Why this module exists: Studio's completion offers minigame names and their argument names,
and its check child runs no plugin code (F23 loads plugins only in ``app``; F45 ``07`` I-8,
O-1). So the class bodies are read with ``ast``: a class with a ``name = "<word>"`` string is
a minigame; the string keys of its ``args = {...}`` dict are its arguments (``Arg()`` with no
argument is required). A ``**{key: … for key, … in module.DEFAULTS.items()}`` entry is
followed one step into the sibling module's ``DEFAULTS`` dict, the bundled plugins' pattern.

Pure: text in, data out. Never raises on bad source (the signature is just missing).
"""

import ast
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PluginSig:
    """One minigame: its ``name``, the ``line`` of its class, and its arguments in written
    order as ``(arg, required)``."""

    name: str
    line: int
    args: tuple[tuple[str, bool], ...] = ()


def _defaults_ref(node: ast.expr) -> tuple[str, str] | None:
    """``{k: … for k, … in mod.NAME.items()}`` → ``("mod", "NAME")``."""
    if not isinstance(node, ast.DictComp) or len(node.generators) != 1:
        return None
    it = node.generators[0].iter
    if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) \
            and it.func.attr == "items" and isinstance(it.func.value, ast.Attribute) \
            and isinstance(it.func.value.value, ast.Name):
        return it.func.value.value.id, it.func.value.attr
    return None


def dict_keys(text: str, name: str) -> tuple[str, ...]:
    """The string keys of the top-level ``name = {...}`` (or ``name: T = {...}``) in
    ``text``; empty when there is none."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return ()
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and target.id == name and isinstance(value, ast.Dict):
            return tuple(k.value for k in value.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str))
    return ()


def _class_sig(cls: ast.ClassDef, sibling: Callable[[str, str], tuple[str, ...]]) -> PluginSig | None:
    name: str | None = None
    args: list[tuple[str, bool]] = []
    for stmt in cls.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1 \
                or not isinstance(stmt.targets[0], ast.Name):
            continue
        attr, value = stmt.targets[0].id, stmt.value
        if attr == "name" and isinstance(value, ast.Constant) and isinstance(value.value, str):
            name = value.value
        elif attr == "args" and isinstance(value, ast.Dict):
            for key, item in zip(value.keys, value.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    required = isinstance(item, ast.Call) and not item.args \
                        and not item.keywords
                    args.append((key.value, required))
                elif key is None:
                    ref = _defaults_ref(item)
                    if ref is not None:
                        args.extend((k, False) for k in sibling(*ref))
    if not name or not name.isidentifier():
        return None
    return PluginSig(name, cls.lineno, tuple(dict.fromkeys(args)))


def plugin_sigs(text: str, sibling=lambda module, name: ()) -> tuple[PluginSig, ...]:
    """Every minigame class in one plugin source ``text``. ``sibling(module, name)`` gives
    the keys of ``module.name`` (``dict_keys`` on the sibling file), for ``**`` entries."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return ()
    found = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            sig = _class_sig(node, sibling)
            if sig is not None:
                found.append(sig)
    return tuple(found)


__all__ = ["PluginSig", "dict_keys", "plugin_sigs"]
