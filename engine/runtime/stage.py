"""The stage: what is on screen, as story state, and the statements that change it (F04
``04-technical.md`` §4.1, §5.2, §6.2, §7.3, §9.1; ``02-script.md`` SR-F04-07–20, 26).

Why this module exists: the picture is part of the story. ``StageState`` is a small frozen
value in ``GameState`` holding names and positions as written (no pixels, paths, or sizes),
so a save, a rollback, or a patched game shows the right picture without re-running a
statement (PR-F04-22, 23). The stage statements only change ``interp.stage``; the one
``ShowStage`` of a burst is held by ``flush_stage`` just before the line, so the picture
changes in the same frame as its line (PR-F04-19, TR-F04-01) and never shows an in-between
state.

Layering: ``state.py`` and ``commands.py`` use ``StageState``, and the interpreter calls
``flush_stage``, ``apply_dialogue_words``, and ``lookahead``, so this module sits below the
interpreter and never imports it at load time. The three executors are registered by
``interpreter.py`` with F03's own (``register_executor``); they take ``Step`` from it when
they first run.

Pure (TR-F03-05): no file, clock, or randomness.
"""

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from engine.core.constants import (LAYER_RANGE, STAGE_COORD_RANGE, STAGE_WORDS,
                                   STATEMENT_WORDS_F02, ZOOM_RANGE)
from engine.core.logsetup import get_logger
from engine.runtime import glitch as glitch_mod
from engine.runtime.commands import PrefetchImages, ShowStage
from engine.runtime.limits import STAGE_MAX_SPRITES, STAGE_WORD_MAX_CHARS, saved_tag_ok
from engine.script.messages import format_message
from engine.script.nodes import Call as CallNode
from engine.script.nodes import Jump, Return
from engine.script.nodes import Say as SayNode
from engine.script.nodes import Statement as StatementNode
from engine.script.stage import At, Hide, Scene, Show
from engine.script.words import is_image_word

if TYPE_CHECKING:
    from engine.runtime.character import Character
    from engine.runtime.commands import TitleCard
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.transitions import TransitionSpec
    from engine.script.nodes import Say, Statement

# A position as written: a name, (x,), or (x, y) in canvas units (int or float as written).
Position = str | tuple[int | float] | tuple[int | float, int | float]

# --- Limits of a saved stage (04 §9.1; untrusted data) ----------------------------------------
# STAGE_MAX_SPRITES and STAGE_WORD_MAX_CHARS live in runtime/limits.py (F28 07 I-12).
STAGE_NAME_MAX_CHARS: Final = 512          # an image name, words joined by one space
IMAGE_NAME_MAX_WORDS: Final = 5            # SR-F04-01

# --- Look-ahead (04 §7.6, §12) ------------------------------------------------------------------
# 04 §12 lists these under runtime/limits.py; they live here with STAGE_MAX_SPRITES until the
# limits module is next edited (F04 step 7 doesn't own it).
LOOKAHEAD_MAX_STATEMENTS: Final = 200
LOOKAHEAD_MAX_IMAGES: Final = 8

_STAGE_KEYS: Final = frozenset(("background", "sprites"))
_SPRITE_KEYS: Final = frozenset(("tag", "image", "at", "layer", "zoom", "flip"))


class StageInvalid(Exception):
    """A saved stage ``from_json`` refuses. ``state.py`` turns it into
    ``StateInvalid("stage")``; the text never holds any part of the input."""

    def __init__(self) -> None:
        super().__init__("the saved stage is not valid")


# --- The state (04 §4.1) ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SpriteState:
    """One sprite on stage. ``tag`` is one word, unique on stage; ``image`` is an image name
    (words joined by one space); ``at`` is the position as written (SR-F04-14)."""

    tag: str
    image: str
    at: Position = "center"
    layer: int = 0
    zoom: float = 1.0
    flip: bool = False

    def to_json(self) -> dict[str, object]:
        at = self.at if type(self.at) is str else list(self.at)  # type: ignore[arg-type]
        return {"tag": self.tag, "image": self.image, "at": at, "layer": self.layer,
                "zoom": self.zoom, "flip": self.flip}


@dataclass(frozen=True, slots=True)
class StageState:
    """The whole stage. ``background`` is an image name, or None for the empty stage.
    ``sprites`` is in draw order: layer ascending, then back to front within a layer, so the
    presentation never sorts (UI-F04-08)."""

    background: str | None = None
    sprites: tuple[SpriteState, ...] = ()

    def index_of(self, tag: str) -> int | None:
        """The index of the sprite tagged ``tag``, or None if it isn't on stage."""
        for i, sprite in enumerate(self.sprites):
            if sprite.tag == tag:
                return i
        return None

    def to_json(self) -> dict[str, object]:
        """``{"background", "sprites": [{"tag", "image", "at", "layer", "zoom", "flip"}]}``,
        fresh plain values; numbers keep their type (``400`` int, ``400.5`` float)."""
        return {"background": self.background,
                "sprites": [sprite.to_json() for sprite in self.sprites]}

    @staticmethod
    def from_json(obj: object) -> "StageState":
        """Validate an untrusted saved stage (04 §9.1, F03 §9.1 rules): types, counts, and
        lengths are checked before anything is built. Raises ``StageInvalid`` only."""
        try:
            return _stage_from_json(obj)
        except StageInvalid:
            raise
        except Exception:                   # defensive: the contract is StageInvalid only
            raise StageInvalid() from None


EMPTY_STAGE: Final = StageState()


def first_word(image: str) -> str:
    """An image name's tag: its first word."""
    return image.split(" ", 1)[0]


# --- Changes (04 §6.2; SR-F04-07, 10, 11, 15–18) ---------------------------------------------

def position_of(at: At | None) -> Position | None:
    """The position a ``show``'s ``at`` gives, as written; None when the line has no ``at``."""
    if at is None:
        return None
    if at.name is not None:
        return at.name
    if at.y is None:
        return (at.x,)  # type: ignore[return-value]
    return (at.x, at.y)  # type: ignore[return-value]


def _insert_front(sprites: list[SpriteState], sprite: SpriteState) -> None:
    """In front of its layer: just after the last sprite whose layer is ``<= sprite.layer``."""
    at = 0
    for i, other in enumerate(sprites):
        if other.layer <= sprite.layer:
            at = i + 1
    sprites.insert(at, sprite)


def shown(stage: StageState, stmt: Show) -> StageState:
    """The stage after ``stmt`` (SR-F04-09–11, 15–17)."""
    tag = stmt.tag or first_word(stmt.image)
    sprites = list(stage.sprites)
    i = stage.index_of(tag)
    at = position_of(stmt.at)
    if i is None:                                               # SR-F04-10
        sprite = SpriteState(tag, stmt.image, "center" if at is None else at,
                             0 if stmt.layer is None else stmt.layer,
                             1.0 if stmt.zoom is None else float(stmt.zoom), bool(stmt.flip))
        _insert_front(sprites, sprite)
    else:                                                       # SR-F04-11
        old = sprites[i]
        # The one-word form (``show hana at left``) keeps the current image.
        image = old.image if stmt.image == first_word(old.image) else stmt.image
        sprite = replace(old, image=image, at=old.at if at is None else at,
                         zoom=old.zoom if stmt.zoom is None else float(stmt.zoom),
                         flip=old.flip if stmt.flip is None else bool(stmt.flip))
        if stmt.layer is not None and stmt.layer != old.layer:   # to the front of layer N
            del sprites[i]
            _insert_front(sprites, replace(sprite, layer=stmt.layer))
        else:
            sprites[i] = sprite
    behind = stmt.behind
    if behind is not None and behind != tag:                    # SR-F04-16
        x = next((s for s in sprites if s.tag == behind), None)
        if x is not None:
            k = next(k for k, s in enumerate(sprites) if s.tag == tag)
            moved = replace(sprites.pop(k), layer=x.layer)
            sprites.insert(sprites.index(x), moved)
    return StageState(stage.background, tuple(sprites))


def hidden(stage: StageState, tag: str) -> StageState:
    """The stage without the sprite tagged ``tag``; unchanged if it isn't there (SR-F04-18)."""
    i = stage.index_of(tag)
    if i is None:
        return stage
    return StageState(stage.background, stage.sprites[:i] + stage.sprites[i + 1:])


# --- Executors (04 §6.2; registered by interpreter.py) ---------------------------------------

def _continue() -> "Step":
    from engine.runtime.interpreter import Step     # below the interpreter (module docstring)
    return Step.CONTINUE


def _after_change(interp: "Interpreter", stmt: Scene | Show | Hide) -> "Step":
    """F09 (04 §5.3): a statement with a ``with`` ends a moment (``effects.moment``: the
    picture so far is shown through its transition and the story waits); without one, the
    change waits for the next moment shown."""
    clause = stmt.with_clause
    if clause is None:
        return _continue()
    from engine.runtime.effects import moment        # below the interpreter (docstring)
    from engine.runtime.transitions import spec_for
    return moment(interp, stmt, spec_for(interp, clause, stmt.sid))


def run_scene(interp: "Interpreter", stmt: Scene) -> "Step":
    """``scene [image]``: every sprite leaves; ``image`` (None: the empty stage) is the
    background (SR-F04-07). F07 clears ``kept_line`` here (a question-less menu after a
    ``scene`` hides the textbox, PR-F07-04); F09 sets ``scene_since_line`` (the textbox is
    hidden during the waits until the next line, PR-F09-09). F28 (04 §6.1): every jitter goes
    (``glitch.scene_cleared``)."""
    interp.stage = StageState(stmt.image, ())
    interp.kept_line = None
    interp.scene_since_line = True
    glitch_mod.scene_cleared(interp)
    return _after_change(interp, stmt)


def run_show(interp: "Interpreter", stmt: Show) -> "Step":
    interp.stage = shown(interp.stage, stmt)
    return _after_change(interp, stmt)


def run_hide(interp: "Interpreter", stmt: Hide) -> "Step":
    interp.stage = hidden(interp.stage, stmt.tag)
    glitch_mod.sprite_left(interp, stmt.tag)                # F28 (04 §6.1): its jitter goes
    return _after_change(interp, stmt)


def speaker_tag(c: "Character", speaker: str) -> str:
    """SR-F04-19 (I-3): the Character's ``image_tag``, or else the define name."""
    return c.image_tag or speaker


def apply_dialogue_words(interp: "Interpreter", stmt: "Say", c: "Character") -> str:
    """F03 ``Say`` step 2 (SR-F04-20): with words and the speaker's tag on stage, that
    sprite's image becomes ``<its current tag> <words>``, everything else kept. Words that
    change nothing because the tag isn't on stage log one INFO per statement per session in
    dev runs (PR-F04-12). Returns the speaker's tag."""
    tag = speaker_tag(c, stmt.speaker)  # type: ignore[arg-type]
    words = stmt.attributes
    if not words:
        return tag
    stage = interp.stage
    i = stage.index_of(tag)
    if i is not None:
        old = stage.sprites[i]
        image = first_word(old.image) + " " + " ".join(words)
        if image != old.image:
            sprites = list(stage.sprites)
            sprites[i] = replace(old, image=image)
            interp.stage = StageState(stage.background, tuple(sprites))
    elif interp.dev and stmt.sid not in interp._words_logged:
        interp._words_logged.add(stmt.sid)
        text = format_message("I-stage-words", (tag, " ".join(words)))
        get_logger("stage").info("%s, line %d: %s", stmt.file.ref, stmt.line, text)
    return tag


def position_gone_message(tag: str, name: str) -> str:
    """W15's text (``02`` §5.4): ``render/stage.py`` logs it when a restored stage names a
    position ``config.toml`` no longer has (``render`` can't import ``script``)."""
    return format_message("W15", (tag, name))


# --- Bursts (04 §7.3; architecture.md "Stage flush") -----------------------------------------

def stage_changed(interp: "Interpreter") -> bool:
    """Whether the stage differs from the last one shown (or none has been shown since new
    game or a restore's commit): what ``flush_stage`` would send."""
    return interp._stage_shown is None or interp.stage != interp._stage_shown


def flush_stage(interp: "Interpreter", *, transition: "TransitionSpec | None" = None,
                card: "TitleCard | None" = None) -> bool:
    """Hold one ``ShowStage`` with the current stage, through ``transition`` (None: a cut),
    if it differs from the last one shown (or none has been shown since new game), or (F18)
    if ``card`` differs from the card on screen (``interp.card_shown``, runtime-only); then
    (F09, C4) hold and clear the pending ``Shake`` and ``Flash``, and last (F28) the one
    ``Glitch`` of a change (``glitch.flush``). Return whether a ``ShowStage`` was held.
    ``take_checkpoint`` calls it first, with no transition, so the picture comes before its
    line in the same burst: ``[ShowStage] [Shake] [Flash] [Glitch]``.

    The rule for waits that aren't checkpoints (F09 ``with`` and ``pause``, F23): any wait
    that shows the story without a checkpoint calls ``flush_stage`` before it holds its
    wait command and releases the burst, so a burst never holds more than one ``ShowStage``
    and the picture on screen during the wait is complete."""
    held = stage_changed(interp) or card != interp.card_shown
    if held:
        stage = interp.stage
        interp._hold(ShowStage(stage, transition=transition, card=card))
        interp._stage_shown = stage
        interp.card_shown = card
    if interp.pending_shake is not None:
        interp._hold(interp.pending_shake)
        interp.pending_shake = None
    if interp.pending_flash is not None:
        interp._hold(interp.pending_flash)
        interp.pending_flash = None
    glitch_mod.flush(interp)                                # F28: last (07 I-17)
    return held


def lookahead(interp: "Interpreter", start: "Statement") -> PrefetchImages | None:
    """The images the story may show soon after ``start`` (04 §7.6, PR-F04-21, TR-F04-07),
    or None when it names none. ``take_checkpoint`` holds the result when it differs from
    the last one sent. A hint only: nothing depends on it.

    A breadth-first walk from ``start``'s successor, visiting at most
    ``LOOKAHEAD_MAX_STATEMENTS`` statements once each: sequential successors (F03's
    memoized ``_successor``), each ``if`` branch's first statement and the statement after
    the ``if``, ``jump``/``call`` targets (a ``call`` also queues its successor); it stops at
    ``return`` and the end of a label block. It collects up to ``LOOKAHEAD_MAX_IMAGES``
    names in visit order: ``scene`` images (backgrounds); ``show`` images (sprites; the
    one-word form for a tag on stage keeps its image, so it is skipped); and the dialogue
    words of a speaker whose tag is on the current stage. Stage changes along the walk are
    not simulated. F07 walks a menu's choices through ``blocks()``.

    Pure: reads the program, the stage, and ``G``'s Characters; changes nothing a
    fingerprint sees (the successor memo is a cache)."""
    from engine.runtime.character import Character  # below the interpreter (docstring)

    program = interp.program
    on_stage = {sprite.tag: sprite for sprite in interp.stage.sprites}
    G = interp.G
    backgrounds: list[str] = []
    sprites: list[str] = []
    names: set[str] = set()
    pending: deque["Statement"] = deque()
    queued: set[int] = set()

    def push(stmt: object) -> None:
        if isinstance(stmt, StatementNode) and id(stmt) not in queued:
            queued.add(id(stmt))
            pending.append(stmt)

    def push_label(target: str) -> None:
        label = program.labels.get(target)
        if label is not None and label.block:
            push(label.block[0])

    def add(name: str, into: list[str]) -> None:
        if name not in names:
            names.add(name)
            into.append(name)

    for block in start.blocks():        # F07: a menu's choices come before what follows
        if block:
            push(block[0])
    push(interp._successor(start)[0])
    visits = 0
    while pending and visits < LOOKAHEAD_MAX_STATEMENTS and len(names) < LOOKAHEAD_MAX_IMAGES:
        stmt = pending.popleft()
        visits += 1
        if isinstance(stmt, Scene):
            if stmt.image is not None:
                add(stmt.image, backgrounds)
        elif isinstance(stmt, Show):
            here = on_stage.get(stmt.tag or first_word(stmt.image))
            if not (here is not None and stmt.image == first_word(here.image)):
                add(stmt.image, sprites)
        elif isinstance(stmt, SayNode) and stmt.speaker is not None and stmt.attributes:
            c = G.get(stmt.speaker)
            if isinstance(c, Character):
                here = on_stage.get(speaker_tag(c, stmt.speaker))
                if here is not None:
                    add(first_word(here.image) + " " + " ".join(stmt.attributes), sprites)
        if visits >= LOOKAHEAD_MAX_STATEMENTS:
            break                       # nothing more can be visited: no more successors
        blocks = stmt.blocks()
        if blocks:                      # an if's branches, F07 a menu's choices
            for block in blocks:
                if block:
                    push(block[0])
            push(interp._successor(stmt)[0])
        elif isinstance(stmt, Jump):
            push_label(stmt.target)
        elif isinstance(stmt, CallNode):
            push_label(stmt.target)
            push(interp._successor(stmt)[0])
        elif not isinstance(stmt, Return):
            push(interp._successor(stmt)[0])
    if not names:
        return None
    return PrefetchImages(tuple(backgrounds), tuple(sprites))      # ≤ 8 names in all


# --- Saved stages (04 §9.1) --------------------------------------------------------------------
# Words are checked against the F02 statement words, never the live set (F14 07 I-1): a name
# reserved later (``rollback``) loads, then draws as missing art, or a position falls back (W15).

def _fail() -> StageInvalid:
    return StageInvalid()


def _image_name(value: object) -> str:
    """1–5 words joined by one space, each an image word of at most 100 characters."""
    if type(value) is not str or len(value) > STAGE_NAME_MAX_CHARS:
        raise _fail()
    words = value.split(" ")
    if len(words) > IMAGE_NAME_MAX_WORDS:
        raise _fail()
    for word in words:
        if len(word) > STAGE_WORD_MAX_CHARS or not is_image_word(word, STATEMENT_WORDS_F02):
            raise _fail()
    return value


def _tag(value: object) -> str:
    if not saved_tag_ok(value):
        raise _fail()
    return value  # type: ignore[return-value]


def _coordinate(value: object) -> int | float:
    if type(value) is int:
        ok = STAGE_COORD_RANGE[0] <= value <= STAGE_COORD_RANGE[1]
    elif type(value) is float:
        ok = math.isfinite(value) and STAGE_COORD_RANGE[0] <= value <= STAGE_COORD_RANGE[1]
    else:
        ok = False
    if not ok:
        raise _fail()
    return value  # type: ignore[return-value]


def _position(value: object) -> Position:
    """A position name (one word, not an F02 statement word or a stage word, at most 100
    characters; looked up when drawn, so an unknown one is allowed) or 1–2 numbers in range."""
    if type(value) is str:
        if (0 < len(value) <= STAGE_WORD_MAX_CHARS and value.isidentifier()
                and value.lower() not in STATEMENT_WORDS_F02
                and value.lower() not in STAGE_WORDS):
            return value
        raise _fail()
    if type(value) is list and 1 <= len(value) <= 2:
        return tuple(_coordinate(v) for v in value)  # type: ignore[return-value]
    raise _fail()


def _layer(value: object) -> int:
    if type(value) is not int or not LAYER_RANGE[0] <= value <= LAYER_RANGE[1]:
        raise _fail()
    return value


def _zoom(value: object) -> float:
    if type(value) not in (int, float):
        raise _fail()
    zoom = float(value)  # type: ignore[arg-type]
    if not (math.isfinite(zoom) and ZOOM_RANGE[0] <= zoom <= ZOOM_RANGE[1]):
        raise _fail()
    return zoom


def _flip(value: object) -> bool:
    if type(value) is not bool:
        raise _fail()
    return value


_FIELDS: Final[tuple[tuple[str, Callable[[object], object]], ...]] = (
    ("tag", _tag), ("image", _image_name), ("at", _position), ("layer", _layer),
    ("zoom", _zoom), ("flip", _flip))


def _stage_from_json(obj: object) -> StageState:
    if type(obj) is not dict or obj.keys() != _STAGE_KEYS:
        raise _fail()
    raw_background = obj["background"]
    background = None if raw_background is None else _image_name(raw_background)
    raw_sprites = obj["sprites"]
    if type(raw_sprites) is not list or len(raw_sprites) > STAGE_MAX_SPRITES:
        raise _fail()
    for entry in raw_sprites:                       # shapes first, before any value is read
        if type(entry) is not dict or entry.keys() != _SPRITE_KEYS:
            raise _fail()
    sprites: list[SpriteState] = []
    tags: set[str] = set()
    last_layer = LAYER_RANGE[0]
    for entry in raw_sprites:
        values = {name: check(entry[name]) for name, check in _FIELDS}
        sprite = SpriteState(**values)  # type: ignore[arg-type]
        if sprite.tag in tags or sprite.layer < last_layer:     # unique; draw order
            raise _fail()
        tags.add(sprite.tag)
        last_layer = sprite.layer
        sprites.append(sprite)
    return StageState(background, tuple(sprites))


__all__ = ["EMPTY_STAGE", "LOOKAHEAD_MAX_IMAGES", "LOOKAHEAD_MAX_STATEMENTS", "Position", "SpriteState", "StageInvalid", "StageState",
           "apply_dialogue_words", "first_word", "flush_stage", "hidden", "lookahead",
           "position_gone_message", "position_of", "run_hide", "run_scene", "run_show",
           "shown", "speaker_tag", "stage_changed"]
