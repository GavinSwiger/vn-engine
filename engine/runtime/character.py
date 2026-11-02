"""``Character``: who speaks a line (F03 ``04-technical.md`` §7.10; SR-F03-11 to 16).

Why this module exists: a speaker's shown name and color come from one engine object that
the author creates in a ``define``. Its options are checked when it is made, by one table
(``CHARACTER_OPTIONS``) that later features extend (F04 ``image_tag``, F05 style, F06
blips), and it can't be changed afterwards, so the story never depends on a mutated define.

A ``Character`` can't be saved (it isn't plain data); ``values.kind_words`` names it "a
character" in messages. The texts (E75b–E75g, E85c's third form) are in
``engine/script/messages.py``. F06 adds the blip options (E179): ``blip`` is checked like
F08's statement files, and the ``BlipSpec`` is built once, when the character is made
(F06 ``07`` I-7). F30: a name holding ``{username`` is E302's ``name`` form (the player's
name never reaches a speaker). An unquoted name (E75e's second form) and an unquoted
``name_from`` value fail before the call is made, so ``launch.py`` reads those from the
define's AST (§7.6 phase 2, rule 2).
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from engine.core.errors import AssetRefError
from engine.core.paths import check_ref
from engine.runtime.errors import AuthorRefusal
from engine.runtime.values import kind_words, register_kind
from engine.script.audio import AUDIO_FOLDER, PLAYABLE_EXTS, audio_ref, suffix
from engine.script.suggest import suggest
from engine.script.words import canonical_name, is_image_word

_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")

# F06 (SPEC §3): the blip options' ranges (``blip_every`` and ``blip_volume`` whole numbers).
BLIP_EVERY_RANGE = (1, 10)
BLIP_PITCH_RANGE = (0.0, 0.5)
BLIP_VOLUME_RANGE = (0, 100)
BLIP_TUNING = ("blip_every", "blip_pitch", "blip_volume")    # need ``blip`` (SR-F06-02)


class CharacterOptionError(AuthorRefusal):
    """A refused ``Character(...)`` call: E75b to E75g, without the define prefix."""

    prefixed = False


class CharacterLocked(AuthorRefusal):
    """A ``Character``'s attribute was set or deleted after it was made (E85c, third form)."""


@dataclass(frozen=True, slots=True)
class BlipSpec:
    """F06: a speaker's blip, from its ``Character(blip=…)`` options (static define data,
    never saved). ``file`` is relative to ``audio/``; ``every`` 1–10, ``spread`` (the
    author's ``blip_pitch``) 0.0–0.5, ``volume`` 0–100 (% of the sound volume)."""

    file: str
    every: int = 2
    spread: float = 0.0
    volume: int = 100


@dataclass(frozen=True, slots=True)
class OptionSpec:
    """One ``Character`` option. ``check(value, default_names)`` raises
    ``CharacterOptionError`` for a refused value."""

    name: str
    check: Callable[[object, frozenset[str]], None]


def _check_color(value: object, default_names: frozenset[str]) -> None:
    if type(value) is not str:
        raise CharacterOptionError.of("E75c", None)
    if not _COLOR_RE.fullmatch(value):
        raise CharacterOptionError.of("E75c", value)


def _check_name_from(value: object, default_names: frozenset[str]) -> None:
    if type(value) is not str:
        raise CharacterOptionError.of("E75g")
    if value not in default_names:
        raise CharacterOptionError.of("E75f", value, suggest(value, default_names))


def _check_image_tag(value: object, default_names: frozenset[str]) -> None:
    """F04 SR-F04-23: one word, per SR-F04-01's word rules (E135, at launch)."""
    if type(value) is not str:
        raise CharacterOptionError.of("E135", kind_words(value))
    if not is_image_word(value):
        raise CharacterOptionError.of("E135", None, value)


def _check_text_color(value: object, default_names: frozenset[str]) -> None:
    """F05 SR-F05-22: ``"#RRGGBB"``, hex digits in any case (E168)."""
    if type(value) is not str or not _COLOR_RE.fullmatch(value):
        raise CharacterOptionError.of("E168", "text_color")


def _written(value: object) -> str | None:
    """A refused ``text_italic`` (F06: blip option) value as the script wrote it (``"yes"``,
    ``1``, ``True``), for plain
    values only; None otherwise (no author ``__repr__`` runs here). The message's ``show()``
    escapes and cuts it."""
    t = type(value)
    if t is str:
        return '"' + value[:200] + '"'  # type: ignore[index]
    if t is float or t is int or t is bool or value is None:
        try:
            return repr(value)
        except ValueError:                          # an int longer than Python will print
            return None
    return None


def _check_text_italic(value: object, default_names: frozenset[str]) -> None:
    """F05 SR-F05-22: exactly True or False (E168)."""
    if type(value) is not bool:
        raise CharacterOptionError.of("E168", "text_italic", _written(value))


def _shown(value: object) -> str:
    """A refused F06 value for E179's "but this has …": as written for plain values,
    else its kind in words (``a list``)."""
    written = _written(value)
    return written if written is not None else kind_words(value)


def _check_blip(value: object, default_names: frozenset[str]) -> None:
    """F06 SR-F06-01: a file in quotes inside ``audio/``, as F08's statements (E179)."""
    if type(value) is not str:
        raise CharacterOptionError.of("E179", "blip", _shown(value))
    if value[:len(AUDIO_FOLDER)].casefold() == AUDIO_FOLDER:
        raise CharacterOptionError.of("E179", "prefix", value)
    try:
        check_ref(audio_ref(value))
    except AssetRefError as exc:
        raise CharacterOptionError.of("E179", "path", value, exc.reason) from None
    if suffix(value) not in PLAYABLE_EXTS:
        raise CharacterOptionError.of("E179", "format", value)


_Check = Callable[[object, frozenset[str]], None]


def _ranged(name: str, low: float, high: float, whole: bool) -> _Check:
    """F06: a whole number (``type is int``), or with ``whole`` False a finite int or float,
    from ``low`` to ``high``; booleans aren't numbers (E179)."""
    kinds = (int,) if whole else (int, float)

    def check(value: object, default_names: frozenset[str]) -> None:
        # A NaN fails both comparisons and an infinity the range, so finite is implied.
        if type(value) not in kinds or not low <= value <= high:        # type: ignore[operator]
            raise CharacterOptionError.of("E179", name, _shown(value))
    return check


# F03: color and name_from (I-5). F04 adds image_tag; F05 text_color and text_italic; F06,
# F43 add theirs. E75b lists the names sorted.
CHARACTER_OPTIONS: dict[str, OptionSpec] = {
    "color": OptionSpec("color", _check_color),
    "name_from": OptionSpec("name_from", _check_name_from),
    "image_tag": OptionSpec("image_tag", _check_image_tag),          # F04
    "text_color": OptionSpec("text_color", _check_text_color),       # F05
    "text_italic": OptionSpec("text_italic", _check_text_italic),    # F05
    "blip": OptionSpec("blip", _check_blip),                         # F06
    "blip_every": OptionSpec("blip_every", _ranged("blip_every", *BLIP_EVERY_RANGE, True)),
    "blip_pitch": OptionSpec("blip_pitch", _ranged("blip_pitch", *BLIP_PITCH_RANGE, False)),
    "blip_volume": OptionSpec("blip_volume", _ranged("blip_volume", *BLIP_VOLUME_RANGE, True)),
}


class Character:
    """A speaker. ``name`` is the shown name (None with ``name_from``); ``color`` is
    ``"#RRGGBB"`` or None; ``name_from`` names the default holding the shown name;
    ``options`` holds every option given (read-only; F05 reads ``text_color`` and
    ``text_italic`` from it); ``define_name`` is the define that
    made it (set once at launch, for messages); ``image_tag`` (F04) is the tag of the
    speaker's sprites, or None for the define name (SR-F04-19); ``blip`` (F06 I-7) is the
    ``BlipSpec`` built once from the blip options, or None without ``blip``. Fixed once
    made."""

    __slots__ = ("name", "color", "name_from", "options", "define_name", "image_tag", "blip")

    def __init__(self, name: str | None, options: Mapping[str, object]) -> None:
        set_ = object.__setattr__
        set_(self, "name", name)
        set_(self, "color", options.get("color"))
        set_(self, "name_from", options.get("name_from"))
        set_(self, "options", MappingProxyType(dict(options)))
        set_(self, "define_name", None)
        tag = options.get("image_tag")                    # checked: one word (E135)
        set_(self, "image_tag", None if tag is None else canonical_name(str(tag)))
        file = options.get("blip")                        # checked (E179)
        set_(self, "blip", None if file is None else BlipSpec(
            str(file), int(options.get("blip_every", 2)),           # type: ignore[call-overload]
            float(options.get("blip_pitch", 0.0)),                  # type: ignore[arg-type]
            int(options.get("blip_volume", 100))))                  # type: ignore[call-overload]

    def _named(self, define_name: str) -> None:
        """Launch: remember the define's name (first define wins)."""
        if self.define_name is None:
            object.__setattr__(self, "define_name", define_name)

    def __setattr__(self, name: str, value: object) -> None:
        self._refuse(name)

    def __delattr__(self, name: str) -> None:
        self._refuse(name)

    def _refuse(self, name: str) -> None:
        shown = self.define_name or self.name or "this character"
        raise CharacterLocked.of("E85c", str(shown), str(name), None, False, "", True)

    def __repr__(self) -> str:
        if self.name_from is not None:
            return f"Character(name_from={self.name_from!r})"
        return f"Character({self.name!r})"


register_kind(Character, "a character")


class CharacterFactory:
    """``G["Character"]``: checks the call (§7.10) and makes a ``Character``. Holds the
    program's default names, so a ``$``-line call is checked the same way as a define."""

    __slots__ = ("_default_names",)

    def __init__(self, default_names: frozenset[str]) -> None:
        self._default_names = frozenset(default_names)

    def __call__(self, *args: object, **opts: object) -> Character:
        if "name" in opts:
            raise CharacterOptionError.of("E75b", "name", ())
        has_from = "name_from" in opts
        if len(args) > 1:
            raise CharacterOptionError.of("E75d", "count", len(args))
        if args and has_from:
            raise CharacterOptionError.of("E75d", "both")
        if not args and not has_from:
            raise CharacterOptionError.of("E75d", "missing")
        if args and type(args[0]) is not str:
            raise CharacterOptionError.of("E75e", kind_words(args[0]))
        if args and "{username" in args[0]:                 # F30 E302 (04 §5.3), before E169
            raise CharacterOptionError.of("E302", "name")
        if args and ("{" in args[0] or "}" in args[0]):     # F05 E169: names are plain text
            raise CharacterOptionError.of("E169", args[0])
        for key in opts:
            if key not in CHARACTER_OPTIONS:
                names = sorted(CHARACTER_OPTIONS)
                raise CharacterOptionError.of("E75b", key, names, suggest(key, names))
        for key, value in opts.items():
            CHARACTER_OPTIONS[key].check(value, self._default_names)
        if "blip" not in opts:                              # F06 SR-F06-02
            for key in opts:
                if key in BLIP_TUNING:
                    raise CharacterOptionError.of("E179", "needs", key)
        return Character(args[0] if args else None, opts)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        return "Character"


__all__ = ["BLIP_EVERY_RANGE", "BLIP_PITCH_RANGE", "BLIP_TUNING", "BLIP_VOLUME_RANGE",
           "CHARACTER_OPTIONS", "Character", "CharacterFactory", "CharacterLocked",
           "CharacterOptionError", "OptionSpec"]
