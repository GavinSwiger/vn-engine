"""W323: an old spelling read as a deprecated alias (v1 name freeze, 2026-11-06).

Why this module exists: version 1 freezes the public names, and a few changed just before
it. A game written with an old spelling keeps working (each is read as its new name), and
the check, ``engine lint`` and Studio's Problems say once per load which new spelling to
write. Studio itself writes only the new names.

- The device look ``letters`` is ``letter`` (``on letter`` after ``send`` and ``lock
  contact``, ``open letter``, ``[device.letter]``): ``note`` at parse time, once per load.
- Config keys (``core/config`` moves each to its new place and records it in
  ``Config.renamed``): ``config_warnings``, one per key at its line.
- ``codex.count`` / ``codex.items`` are ``items.count`` / ``items.held``:
  ``codex_warnings``, at the first read of each (``bindings.RootUses``).

Pure: no file access, no author code.
"""

from typing import Any, Final

from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message

CODE: Final = "W323"
# ``codex.<old>`` → the spelling to write now (``runtime/codex`` still reads both).
CODEX_RENAMED: Final = {"count": "items.count(...)", "items": "items.held"}


def warning(old: str, new: str, file: str | None, line: int | None) -> ScriptWarning:
    return ScriptWarning(format_message(CODE, (old, new)), code=CODE, file=file, line=line)


def note(ctx: Any, old: str, new: str) -> None:
    """At parse time: W323 for ``old`` at the current line, unless this load has one for
    ``old`` already."""
    log = ctx.warnings.warnings
    found = format_message(CODE, (old, new))
    if any(getattr(w, "code", None) == CODE and w.message == found for w in log):
        return
    raw = ctx.raw
    log.append(ScriptWarning(found, code=CODE, file=raw.file.ref if raw is not None else None,
                             line=raw.line if raw is not None else None))


def config_warnings(config: Any) -> list[ScriptWarning]:
    """One W323 per old config key the game's ``config.toml`` uses (``Config.renamed``)."""
    return [warning(old, new, "config.toml", line)
            for line, old, new in getattr(config, "renamed", ())]


def codex_warnings(reads: dict[str, tuple[str, int]]) -> list[ScriptWarning]:
    """W323 at the first read of each of ``codex.count`` and ``codex.items`` (``reads``:
    ``RootUses.reads_of("codex")``, name → (file ref, line))."""
    return [warning(f"codex.{name}", new, *reads[name])
            for name, new in CODEX_RENAMED.items() if name in reads]


__all__ = ["CODE", "CODEX_RENAMED", "codex_warnings", "config_warnings", "note", "warning"]
