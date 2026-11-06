"""``show hotbar`` / ``hide hotbar``: the item quick slots in the status corner (F64 round 2,
specs/F64-items/SPEC.md "Round 2: Use and the hotbar"; proposal I-13 "Hotbar").

Why this module exists: an item declared with ``use <scene>`` has a Use button in the bag. The
items a player uses often (a match, a potion) also want a strip of quick slots on screen,
used with the number keys. ``show hotbar`` puts that strip in a corner of the screen and
``hide hotbar`` takes it away; whether it is shown is story state (``ItemsState.bar``), so
saves, loads and going back keep it, as ``show meter`` does. What the slots hold, how many
there are and which corner come from ``[hotbar]`` in config.toml (``app/hotbar.py``).

**Positional words** (ADR-0010 rule 2). ``hotbar`` is no new statement word: ``show hotbar``
and ``hide hotbar`` are the hotbar form only when nothing else is on the line. Anything after
(``show hotbar at left``, ``hide hotbar with dissolve``) is the picture form, as before, so
``hotbar`` stays a free name. A game that has a picture whose tag is ``hotbar`` gets W309 at
launch for each bare line (``picture_warnings``), which says how to show the picture.

**Checks.** W308 (``check_story``, at load with the config): a name in ``[hotbar] items``
that is no item, or an item with no ``use`` scene (did-you-mean among the usable items).

``HotbarShow`` is not a checkpoint and never branches: the story map and reach treat it as a
plain line.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from engine.core.constants import CONFIG_FILENAME
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import TEMPLATES, _did_you_mean, format_message, show, show_name
from engine.script.nodes import Node, Statement
from engine.script.suggest import suggest
from engine.script.words import canonical_name

WORD_HOTBAR: Final = "hotbar"


# --- Messages (F64's W308, W309) ---------------------------------------------------------------

def _w308(name: str = "potoin", form: str = "unknown", suggestion: str | None = None) -> str:
    """``unknown`` (no item has the name); ``tip`` (a tip); ``no_use`` (an item with no
    ``use`` scene)."""
    shown = show_name(name)
    if form == "tip":
        return (f"[hotbar] items names tip {shown}, but only items go in the hotbar. Remove "
                "it from the list.")
    if form == "no_use":
        return (f"[hotbar] items names item {shown}, which has no Use scene, so its slot "
                f"could never be used. Add use and a scene to its lock item line, e.g. "
                f'lock item {shown} "Title" use use_{shown}, or remove it from the list.')
    text = f"[hotbar] items names {shown}, but no item has that name."
    if suggestion is not None:
        return text + " " + _did_you_mean(str(suggestion), str(name))
    return text + " Use the name of an item from a lock item line."


def _w309(line: str = "show hotbar") -> str:
    return (f"{show(line)} shows the hotbar now, not your picture hotbar. To show the "
            "picture, add where it goes, e.g. show hotbar at center; to hide it, add a "
            "transition, e.g. hide hotbar with dissolve. Or rename the picture.")


TEMPLATES.update({"W308": _w308, "W309": _w309})


# --- The statement ---------------------------------------------------------------------------

@dataclass(slots=True, kw_only=True)
class HotbarShow(Statement):
    """``show hotbar`` (``shown`` True) or ``hide hotbar`` (False). Not a checkpoint."""

    shown: bool

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_HOTBAR, "show" if self.shown else "hide")

    def written(self) -> str:
        return f"{'show' if self.shown else 'hide'} {WORD_HOTBAR}"


def is_hotbar_line(chunks: list[Any], colon: bool, is_word: str) -> bool:
    """Whether a ``show``/``hide`` line whose chunks after the word are ``chunks`` is the
    hotbar form: ``hotbar`` and nothing else (module docstring)."""
    return (len(chunks) == 1 and not colon and chunks[0].kind == is_word
            and chunks[0].text == WORD_HOTBAR)


def parse_hotbar_line(raw: Any, word: str) -> HotbarShow:
    return HotbarShow(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                      shown=word == "show")


# --- Checks ------------------------------------------------------------------------------------

def check_story(nodes: Iterable[Node], config: Any = None) -> list[ScriptWarning]:
    """W308 for each name in ``config.hotbar.items`` that isn't an item with a ``use`` scene.
    ``config`` None (tools without one): nothing."""
    names: Sequence[str] = getattr(getattr(config, "hotbar", None), "items", ()) or ()
    if not names:
        return []
    from engine.script.codex import WORD_ITEM, CodexEntryDecl
    decls = {n.name: n for n in nodes if isinstance(n, CodexEntryDecl)}
    usable = tuple(name for name, d in decls.items() if d.kind == WORD_ITEM and d.use)
    out: list[ScriptWarning] = []
    for written in names:
        name = canonical_name(written)
        decl = decls.get(name)
        if decl is not None and decl.kind == WORD_ITEM and decl.use:
            continue
        if decl is None:
            args: tuple = (written, "unknown", suggest(name, usable))
        elif decl.kind != WORD_ITEM:
            args = (written, "tip")
        else:
            args = (written, "no_use")
        out.append(ScriptWarning(format_message("W308", args), code="W308",
                                 file=CONFIG_FILENAME, line=None))
    return out


def picture_warnings(statements: Iterable[Statement], tags: Iterable[str]
                     ) -> list[ScriptWarning]:
    """W309 at each ``show hotbar`` / ``hide hotbar`` when the game has a picture whose tag
    is ``hotbar`` (``tags``: the image index's tags)."""
    if WORD_HOTBAR not in set(tags):
        return []
    return [ScriptWarning(format_message("W309", (stmt.written(),)), code="W309",
                          file=stmt.file.ref, line=stmt.line)
            for stmt in statements if isinstance(stmt, HotbarShow)]


# Studio's docs rows (Insert, help) for show hotbar / hide hotbar are in docs_table.py, after
# the sprite rows, so a plain show/hide line's help stays the sprite's.
DOCS_HEADING: Final = "show hotbar, hide hotbar"          # docs/script-language.md


__all__ = ["DOCS_HEADING", "HotbarShow", "WORD_HOTBAR", "check_story", "is_hotbar_line",
           "parse_hotbar_line", "picture_warnings"]
