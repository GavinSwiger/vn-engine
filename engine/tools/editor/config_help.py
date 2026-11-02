"""Studio's writing help for ``config.toml`` (2026-11-02, AC-F45-63..66): completion of
section names, key names, and a key's fixed values, and the Help pane's row for the key or
section under the cursor.

Pure Python, no Tk, like ``assist``. Everything is read from ``core.config_schema``: the
sections (``SECTIONS`` and their ``Table`` fields), each key's validator (its ``expected``
phrase is the type and range), its default, and its description (``key_doc``, the key's
``spec(…, doc=…)``). A new key or section is offered and explained with no change here.

- ``section_at(text)``: the dotted path of the last ``[section]`` header in ``text`` (the
  file above the cursor's line), or None before the first header.
- ``config_context(line, column, section)``: after ``[`` the section paths; at the start of
  a line in a known section its keys; after ``key = `` the key's fixed values (``true`` /
  ``false``, a choice's quoted words). Rows come from ``config_candidates``.
- ``config_help(line, column, section)``: a ``ConfigDoc`` for the header or key on
  ``line`` (``assist.help_sections`` shows it like a statement's doc), or None.
"""

import dataclasses
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from engine.core.config_schema import (
    LOOK_SECTIONS, SECTIONS, Bool, Choice, HexColor, Table, config_fields, key_doc,
    section_class)
from engine.tools.editor.assist import Candidate, Context

SECTION_KIND: Final = "section"
KEY_KIND: Final = "key"
VALUE_KIND: Final = "value"
CONFIG_KINDS: Final = frozenset((SECTION_KIND, KEY_KIND, VALUE_KIND))

_HEADER_TYPED = re.compile(r"[ \t]*\[\[?[ \t]*([A-Za-z0-9_.-]*)")
_HEADER = re.compile(r"[ \t]*\[\[?[ \t]*([A-Za-z0-9_.-]+)[ \t]*\]")
_KEY_TYPED = re.compile(r"[ \t]*([A-Za-z0-9_-]*)")
_KEY_LINE = re.compile(r"[ \t]*([A-Za-z0-9_.-]+)[ \t]*(=|$)")
_VALUE_TYPED = re.compile(r'[ \t]*([A-Za-z0-9_.-]+)[ \t]*=[ \t]*("?[A-Za-z0-9_-]*)')


@dataclass(frozen=True, slots=True)
class ConfigDoc:
    """The Help pane's rows for a config key or section, in ``StatementDoc``'s shape:
    ``title`` (``[section] key``), ``syntax`` (what it accepts), ``summary`` (its
    description), ``example`` (``key = <default>  # default``, or ``""``)."""

    title: str
    syntax: str
    summary: str
    example: str
    docs: None = None


def section_paths() -> tuple[str, ...]:
    """Every section a ``[header]`` can name: the top-level sections, their ``Table``
    fields (``theme.minigame``), and their entry tables (``stage.positions``), in
    declaration order."""
    paths: list[str] = []

    def walk(path: str, cls: type) -> None:
        paths.append(path)
        for key, found in config_fields(cls).items():
            validator = found.metadata["validator"]
            if isinstance(validator, Table):
                walk(f"{path}.{key}", validator.cls)
            elif _is_table_key(found):
                paths.append(f"{path}.{key}")

    for name, cls in SECTIONS.items():
        walk(name, cls)
    paths.extend(LOOK_SECTIONS)            # F32: [style.<name>], [playthrough.N]
    return tuple(paths)


def _is_table_key(found: dataclasses.Field) -> bool:
    """A key whose value is a table of the author's entries (``positions``, ``plugin``)."""
    return isinstance(found.default, Mapping) or (
        found.default_factory is not dataclasses.MISSING
        and not isinstance(found.metadata["validator"], Table))


def section_at(text: str) -> str | None:
    """The path of the last section header in ``text``, or None if there is none."""
    path = None
    for line in text.split("\n"):
        found = _HEADER.match(line)
        if found is not None:
            path = found.group(1)
    return path


def _keys(section: str) -> dict[str, dataclasses.Field]:
    cls = section_class(section)
    if cls is None:
        return {}
    return {key: f for key, f in config_fields(cls).items()
            if not isinstance(f.metadata["validator"], Table)}


def _values(found: dataclasses.Field) -> tuple[str, ...]:
    validator = found.metadata["validator"]
    if isinstance(validator, Bool):
        return ("true", "false")
    if isinstance(validator, Choice):
        return tuple(f'"{option}"' for option in validator.options)
    return ()


def config_context(line: str, column: int, section: str | None) -> Context | None:
    """What completes at ``column`` of a ``config.toml`` line in ``section``, or None."""
    column = max(0, min(column, len(line)))
    before = line[:column]
    if "#" in before:
        return None
    header = _HEADER_TYPED.fullmatch(before)
    if header is not None:
        typed = header.group(1)
        return Context((SECTION_KIND,), typed, column - len(typed), column)
    if section is None:
        return None
    key = _KEY_TYPED.fullmatch(before)
    if key is not None:
        typed = key.group(1)
        return Context((KEY_KIND,), typed, column - len(typed), column, scope=section)
    value = _VALUE_TYPED.fullmatch(before)
    if value is not None:
        found = _keys(section).get(value.group(1))
        if found is not None and _values(found):
            typed = value.group(2)
            return Context((VALUE_KIND,), typed, column - len(typed), column,
                           scope=f"{section}\n{value.group(1)}")
    return None


def config_candidates(ctx: Context) -> list[Candidate]:
    """The rows for a ``config_context``: the names of its kind that start with the
    prefix (exact case first, then any case), in the schema's order."""
    kind = ctx.kinds[0]
    if kind == SECTION_KIND:
        pool: tuple[str, ...] = section_paths()
    elif kind == KEY_KIND:
        pool = tuple(_keys(ctx.scope))
    else:
        section, _, key = ctx.scope.partition("\n")
        found = _keys(section).get(key)
        pool = _values(found) if found is not None else ()
    folded = ctx.prefix.casefold()
    exact = [Candidate(name, kind) for name in pool if name.startswith(ctx.prefix)]
    loose = [Candidate(name, kind) for name in pool
             if not name.startswith(ctx.prefix) and name.casefold().startswith(folded)]
    return exact + loose


def auto_open_config(line: str, column: int, section: str | None) -> bool:
    """True right after a header's ``[`` and right after ``key = `` for a key of
    ``section`` with fixed values (``true``/``false``, a choice)."""
    before = line[:column]
    if before.strip() == "[":
        return True
    if not (before.endswith(" ") and before.rstrip(" \t").endswith("=")):
        return False
    ctx = config_context(line, column, section)
    return ctx is not None and ctx.kinds == (VALUE_KIND,)


def toml_default(found: dataclasses.Field) -> str | None:
    """The key's default as written in ``config.toml``, or None (not set, or a table)."""
    if found.default is dataclasses.MISSING:
        return None
    value = found.default
    if value is None or isinstance(value, Mapping):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, tuple):
        if isinstance(found.metadata["validator"], HexColor) and len(value) == 3:
            return '"#{:02X}{:02X}{:02X}"'.format(*value)
        return "[" + ", ".join(json.dumps(v, ensure_ascii=False) if isinstance(v, str)
                               else repr(v) for v in value) + "]"
    return None


def key_help(section: str, key: str) -> ConfigDoc | None:
    """The Help rows for ``key`` in ``section`` (``key`` may be dotted, ``name_tab.text_size``),
    or None for a key the schema doesn't have."""
    *inner, name = key.split(".")
    path = ".".join([section, *inner])
    cls = section_class(path)
    found = config_fields(cls).get(name) if cls is not None else None
    if found is None:
        return None
    validator = found.metadata["validator"]
    if isinstance(validator, Table):
        return section_help(f"{path}.{name}")
    default = toml_default(found)
    example = f"{name} = {default}   # default" if default is not None else \
        f"# {name} is not set by default"
    accepts = f"Accepts {validator.expected}"
    if _is_table_key(found):
        accepts, example = "A table: one key per entry", f"[{path}.{name}]"
    return ConfigDoc(f"[{path}] {name}", accepts, key_doc(path, name), example)


def section_help(path: str) -> ConfigDoc | None:
    """The Help rows for the section ``[path]``, or None for a path the schema doesn't
    have. A path inside a look table (``[style.ashes.theme.textbox]``) is its base's."""
    if path not in section_paths() and section_class(path) is None:
        return None
    keys = list(_keys(path)) if section_class(path) is not None else []
    shown = ", ".join(keys[:12]) + (", …" if len(keys) > 12 else "")
    return ConfigDoc(f"[{path}]", "Section", key_doc(path, ""),
                     f"Keys: {shown}" if keys else "")


def config_help(line: str, section: str | None) -> ConfigDoc | None:
    """The Help rows for ``line`` of ``config.toml`` (``section``: the header above it):
    a header gives its section, ``key = …`` (or a key being typed) its key."""
    header = _HEADER.match(line)
    if header is not None:
        return section_help(header.group(1))
    if section is None:
        return None
    key = _KEY_LINE.match(line.split("#", 1)[0] if "=" not in line else line)
    if key is None:
        return None
    return key_help(section, key.group(1))


__all__ = ["CONFIG_KINDS", "ConfigDoc", "KEY_KIND", "SECTION_KIND", "VALUE_KIND", "auto_open_config",
           "config_candidates", "config_context", "config_help", "key_help",
           "section_at", "section_help", "section_paths", "toml_default"]
