"""The text tag doc table (F45 Studio follow-up, 2026-11-02, user: keep Studio updated;
AC-F45-56..59).

Why this module exists: Studio's tag completion and the Help pane's tag rows read one table
keyed by the engine's own tag list (``texttags.TAGS``, F05 §3.1), so nothing about a tag is
hand-listed in the editor. A test fails when the engine gains a tag without a row here (or a
row names no engine tag), so a feature that adds a tag (F29's ``{shake}``, ``{wave}``,
``{glitch}``, ``07`` I-12) adds one ``TagDoc`` row to ``TAG_DOCS`` and nothing else in Studio.

Each row is the tag's ``syntax``, a one-line ``summary``, and an ``example`` dialogue line
whose text parses cleanly. Whether a tag closes (``{/b}``) comes from the engine's
``STYLE_TAGS``, not from the row.

Headless and pure: imports only ``texttags`` (no pygame).
"""

from dataclasses import dataclass
from typing import Final

from engine.script.texttags import STYLE_TAGS

# The heading in docs/script-language.md that documents every tag.
TAG_DOCS_HEADING: Final = "Text tags"


@dataclass(frozen=True, slots=True)
class TagDoc:
    """One tag's Help rows. ``name`` is the tag as the engine knows it (``TAGS``)."""

    name: str
    syntax: str
    summary: str
    example: str

    @property
    def title(self) -> str:
        return f"Text tag {{{self.name}}}"

    @property
    def docs(self) -> str:
        return TAG_DOCS_HEADING

    @property
    def closes(self) -> bool:
        """True for a style tag, which ``{/name}`` closes."""
        return self.name in STYLE_TAGS


TAG_DOCS: Final[tuple[TagDoc, ...]] = (
    TagDoc("b", "{b}…{/b}", "Bold text.", 'hana "That was {b}not{/b} me."'),
    TagDoc("i", "{i}…{/i}", "Italic text.", 'hana "It turned {i}upstream{/i}."'),
    TagDoc("color", "{color=#rrggbb}…{/color}",
           "Colored text: # and six digits or letters a-f.",
           'hana "The {color=#9a1c14}lantern{/color} moved."'),
    TagDoc("size", "{size=1.5}…{/size}", "Bigger or smaller text: 0.5 to 2 times the size.",
           'hana "{size=1.5}Look!{/size}"'),
    TagDoc("speed", "{speed=0.5}…{/speed}",
           "Types slower or faster: 0.1 to 10 times the player's speed, or instant.",
           'hana "{speed=0.5}Slowly,{/speed} it turned."'),
    TagDoc("pause", "{pause} or {pause=0.6}",
           "Stops typing until the player clicks, or for 0.1 to 30 seconds.",
           'hana "I saw it... {pause=0.6}the lantern moved."'),
    TagDoc("var", "{var=name}", "Shows a story variable's value as the line starts.",
           'hana "{var=player_name}, look!"'),
    TagDoc("next", "{next}", "At the very end: goes on to the next line without a click.",
           'daichi "Hana, it is a paper bag with a candle in i-{next}"'),
    # F29 (07 I-12): the effects, each with an optional strength.
    TagDoc("shake", "{shake}…{/shake} or {shake=small|medium|large}…{/shake}",
           "Trembling letters (medium with no strength); they hold still under Reduce motion.",
           'hana "{shake}No!{/shake}"'),
    TagDoc("wave", "{wave}…{/wave} or {wave=small|medium|large}…{/wave}",
           "Letters ripple up and down (medium with no strength); they hold still under "
           "Reduce motion.",
           'hana "La la {wave=large}laaa{/wave}~"'),
    TagDoc("glitch", "{glitch}…{/glitch} or {glitch=small|medium|large}…{/glitch}",
           "Letters flicker into symbols such as # and % (medium with no strength); History "
           "shows the real words.",
           'hana "{glitch=large}You\'re not going anywhere.{/glitch}"'),
    # F30 (04 §5.3): the player's name, only where they allow it.
    TagDoc("username", "{username} or {username=name}",
           "The player's computer user name if the game offers it and the player allows it; "
           "otherwise the fallback word ([meta] username_fallback) or the variable's value. "
           "Dialogue, narration, and effect crash only.",
           'hana "I know who you are, {username}."'),
)


def _check(rows: tuple[TagDoc, ...]) -> None:
    seen: set[str] = set()
    for row in rows:
        if row.name in seen:
            raise ValueError(f"tag {row.name!r} has two rows")
        if "{" + row.name not in row.example:
            raise ValueError(f"tag {row.name!r}: the example doesn't use it")
        seen.add(row.name)


_check(TAG_DOCS)
_BY_NAME: Final = {row.name: row for row in TAG_DOCS}


def tag_doc(name: str) -> TagDoc | None:
    """The row for tag ``name``, or None."""
    return _BY_NAME.get(name)


def tag_names() -> tuple[str, ...]:
    """Every tag with a row, in table order."""
    return tuple(row.name for row in TAG_DOCS)


__all__ = ["TAG_DOCS", "TAG_DOCS_HEADING", "TagDoc", "tag_doc", "tag_names"]
