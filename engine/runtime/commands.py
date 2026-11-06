"""Commands (runtime → presentation) and events (presentation → runtime) (F03
``04-technical.md`` §5.1; docs/architecture.md "Runtime → presentation commands").

Why this module exists: the runtime only emits commands and the presentation only answers
with events (invariant 5). These frozen dataclasses are the whole contract between them, so
the window, the headless runner, and tests all see the same values.

Later features add their own commands and events here (F04 ``ShowStage``,
``PrefetchImages``; F07 ``Choose``; F08 audio; F09 ``Shake``, ``Flash``, ``StoryWait``,
``WaitDone``; F28 ``Glitch``; F18 ``TitleCard``, ``ChapterStarted``; F14 ``StepBack``,
``StepForward``; F21 ``CodexAdded``; F23 ``StartMinigame``, ``MinigameDone``,
``MinigameUsed``; F30 ``WindowTitle``, ``FakeCrash``), one router handler each, and one entry
in ``Interpreter.post``'s event table for each event.
F14 adds no command; its ``RollbackView`` (what the driver's ``rollback_view()`` returns) lives
here too, so ``ui`` imports F14's types from this module only (F14 07 I-6). F17 adds
``NvlPage`` and its record type ``NvlLine``, defined here as F18's ``TitleCard`` is (F17 07
I-4), so ``render`` and ``ui`` read the page record from this module only.

F09: ``TransitionSpec`` (``runtime/transitions.py``) is re-exported here, so ``render``
reads ``ShowStage.transition`` from this module only. F06: ``BlipSpec``
(``runtime/character.py``) likewise, for ``Say.blip``.

F23 (``04`` §4.1): ``MeterView`` and ``MinigameBase`` (what the story holds when a minigame
starts) live here with the minigame's command and events, so ``ui``, ``render``, and
``minigames`` read them from this module only. ``StoryNames`` and the change types are
``core/minigame_types.py``'s, re-exported here.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

# F05 §18.2 item 2: the text tag types, re-exported so ``render`` reads ``Say.body`` without
# importing ``script`` (ADR-0002). F29 adds ``TextEffect`` (``Style.effect``); F30 ``NameMark``
# (``{username}``, which layout asserts never reaches it unresolved).
from engine.script.texttags import (
    BASE_STYLE,
    EMPTY_TEXT,
    INSTANT,
    NameMark,
    PauseMark,
    Span,
    Style,
    TaggedText,
    TextEffect,
    VarMark,
    WaitMark,
)

# F09: the spec a ``with`` sends (re-exported; transitions.py never imports this module).
from engine.runtime.transitions import TransitionSpec

# F06: a speaker's blip (``Say.blip``), re-exported; made where ``Character(...)`` runs.
from engine.runtime.character import BlipSpec

# F23: the plain types a minigame's command and result carry (``core``, shared with the
# script checks and the plugin API), re-exported.
from engine.core.minigame_types import Change, CodexChange, MeterChange, StoryNames

if TYPE_CHECKING:                                   # only for the annotations
    from collections.abc import Mapping
    from engine.core.errors import UserFacingError
    from engine.runtime.audio import AudioState     # audio.py imports this module
    from engine.runtime.glitch import GlitchState   # glitch.py imports this module
    from engine.runtime.stage import StageState     # stage.py imports this module


@dataclass(frozen=True, slots=True)
class Command:
    """Base of every runtime → presentation command."""


@dataclass(frozen=True, slots=True)
class Say(Command):
    """One shown line. Built by ``interpreter.say_command`` only (F05 I-1), for both the
    executor and the restore presenter."""

    sid: str                         # identity (F13 history, F15 read marks, F43)
    speaker: str | None              # define name; None for narration
    name: str | None                 # shown name now; None = narration, "" = no name plate
    name_color: str | None           # "#RRGGBB" or None (F05's default)
    attributes: tuple[str, ...]      # dialogue words as written
    text: str                        # as written, tags included
    # F05: the resolved body (no ``VarMark``; the speaker's text style baked in). Rebuilt
    # from the restored variables on restore, never saved. ``EMPTY_TEXT`` only where a
    # ``Say`` is built by hand (tests).
    body: TaggedText = EMPTY_TEXT
    voice: str | None = None         # F08 fills it from the node (C5, I-1); None in F03
    speaker_tag: str | None = None   # F04: image_tag or the define name; None for narration
    restored: bool = False           # re-shown by restore (F08 replays voice)
    blip: BlipSpec | None = None     # F06: the speaker's blip; None for narration


@dataclass(frozen=True, slots=True)
class TitleCard:
    """F18 (SPEC §4–§5): a full-screen card drawn on top of the stage. ``heading`` (None:
    title only) and ``title`` are plain text as shown, never markup; ``name`` is the
    chapter's (a lookup key). ``kind`` picks W110's wording (F19's ``"ending"``). ``render``
    and ``ui`` read it from this module only (F18 07 I-5)."""

    name: str
    heading: str | None
    title: str
    kind: str = "chapter"


@dataclass(frozen=True, slots=True)
class ShowStage(Command):
    """F04: the complete picture for the coming checkpoint (or F09 wait), held by
    ``stage.flush_stage`` before the line. ``restored`` is set by restore, which always
    sends the saved stage. Handler: ``StageView.show`` (F09: ``StageScreen.show_stage``).
    ``card`` (F18): a title card drawn over the stage (None: none; always None when
    ``restored``)."""

    stage: "StageState"
    restored: bool = False
    transition: TransitionSpec | None = None     # F09: None = a cut (always None when restored)
    card: TitleCard | None = None                # F18


@dataclass(frozen=True, slots=True)
class PrefetchImages(Command):
    """F04: image names the story may show soon, nearest first, at most 8 in all. A hint
    only; correctness never depends on it. Handler: ``StageView.prefetch``."""

    backgrounds: tuple[str, ...]
    sprites: tuple[str, ...]


# --- F08 audio (F08 04-technical.md §5.1; every handler is owned by ``AudioService``) ---------
# Files are as written in the script (or the saved state), relative to ``audio/``. A fade of
# None is the config default, resolved by the presentation (F08 07 I-11), so headless runs
# compare unresolved fades. Burst order and the 64-command cap: ``interpreter._hold`` (I-2).

Fade = float | None


@dataclass(frozen=True, slots=True)
class PlayMusic(Command):
    """``play music``: the music sequence becomes this one track (the queue is cleared).
    ``restart`` is True when the line says ``restart`` or gives ``from`` (SR-F08-12);
    ``start`` is ``from N``, and ``from_current`` is ``from current``."""

    file: str
    loop: bool
    volume: int
    fadein: Fade
    fadeout: Fade
    restart: bool
    start: float | None
    from_current: bool


@dataclass(frozen=True, slots=True)
class QueueMusic(Command):
    """``queue music``: the track goes to the end of the sequence; ``loop`` as written
    (only the last track of the sequence really loops, SR-F08-15)."""

    file: str
    loop: bool
    volume: int
    fadein: Fade


@dataclass(frozen=True, slots=True)
class StopMusic(Command):
    """``stop music``: fade the track out and clear the queue."""

    fadeout: Fade


@dataclass(frozen=True, slots=True)
class PlaySound(Command):
    """``play sound``: a one-shot effect, or a loop (``loop``) that is story state."""

    file: str
    loop: bool
    volume: int
    fadein: Fade


@dataclass(frozen=True, slots=True)
class StopSound(Command):
    """``stop sound ["file"]``: ``file`` None stops every effect playing now."""

    file: str | None
    fadeout: Fade


@dataclass(frozen=True, slots=True)
class PlayVoice(Command):
    """The voice of line ``sid``, held just before its ``Say`` (``take_checkpoint``'s
    ``attached``; I-1). ``restored`` as on ``Say``: a restore plays it again."""

    sid: str
    file: str
    restored: bool


@dataclass(frozen=True, slots=True)
class EndVoice(Command):
    """Voiced line ``sid`` was advanced (held by the accepted ``Advance``); the service
    decides whether the voice stops (voice sustain)."""

    sid: str


@dataclass(frozen=True, slots=True)
class StopVoice(Command):
    """``stop voice``."""

    fadeout: Fade


@dataclass(frozen=True, slots=True)
class AudioRestore(Command):
    """Make the presentation match ``state`` (F08 §7.6 reconcile). ``restore``: first in
    a restore burst; ``new_game``: first in a new game's burst; ``sync``: after the last
    audio command kept when a burst went over ``AUDIO_BURST_MAX`` (I-2)."""

    state: "AudioState"
    reason: Literal["restore", "new_game", "sync"]


# --- F07 choice menus (F07 04-technical.md §5.1) ------------------------------------------------

@dataclass(frozen=True, slots=True)
class ShownChoice:
    """One choice of a ``ShowMenu``: its key in the menu, its body resolved when the menu
    was reached (no ``VarMark``, no timing marks), and whether it is locked (shown but never
    pickable, ``[choice] show_locked``). F59: ``check`` is a checked choice's badge
    (``[Logic · Medium · 58%]``), drawn before the text; None for a plain choice."""

    key: str
    body: TaggedText
    locked: bool
    check: str | None = None


@dataclass(frozen=True, slots=True)
class ShowMenu(Command):
    """A menu waits for a pick (the checkpoint command of a ``Menu``). ``sid`` is the
    menu's; ``choices`` are the shown ones in script order (1–6, at least one unlocked).
    ``line`` says what the textbox holds under the choices: the menu's ``question`` (the
    ``Say`` just before), the ``kept`` last line, or ``none`` (the textbox is hidden).
    ``restored`` as on ``Say``. Handler: F07's ``ChoiceController.show``.

    F51 (07 I-1): ``seconds`` is the script's ``menu time N`` (None: untimed, or the player
    is reading the past, ``rollback.fix_menu``); ``timeout`` the key of the choice time
    running out picks (None with ``seconds``). Timing assist is applied by the presentation,
    never here."""

    sid: str
    choices: tuple[ShownChoice, ...]
    line: Literal["question", "kept", "none"]
    restored: bool = False
    seconds: float | None = None
    timeout: str | None = None


# --- F09 transitions and effects (F09 04-technical.md §4.1) ----------------------------------
# A None size, length, or color is the [effects] / [theme.effects] default, resolved by the
# presentation, so headless runs never depend on config.toml. Burst order: [AudioRestore]
# [held] [ShowStage] [Shake] [Flash], then [StoryWait] at a wait or the line's commands.

@dataclass(frozen=True, slots=True)
class Shake(Command):
    """``shake``, held by the next moment shown (the last one written wins). ``size``
    ``small``/``medium``/``large``, ``direction`` ``horizontal``/``vertical`` (None: both).
    Handler: ``StageScreen.shake``."""

    size: str | None
    direction: str | None
    seconds: float | None


@dataclass(frozen=True, slots=True)
class Flash(Command):
    """``flash``, held by the next moment shown (the last one written wins). ``color``
    ``#RRGGBB``; ``sid`` the ``flash`` statement's (W61). Handler: ``StageScreen.flash``."""

    color: str | None
    seconds: float | None
    sid: str


# F28 (04 §4.2): a glitch's key, (kind, jitter tag); ("jitter", None) in ``stops`` is every
# jitter. Burst order: ... [ShowStage] [Shake] [Flash] [Glitch]; a restore or landing burst
# holds [ShowStage(restored)] [Glitch(restored)] only when the saved set isn't empty.
GlitchKey = tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class GlitchBurst:
    """F28: one burst of ``effect <kind> …`` (a length or none): ``size`` and ``seconds``
    None are the ``[effects]`` defaults; ``sid`` the statement's (W182)."""

    kind: str
    tag: str | None
    size: str | None
    seconds: float | None
    sid: str


@dataclass(frozen=True, slots=True)
class Glitch(Command):
    """F28: held last by ``flush_stage`` (``runtime/glitch.flush``), only on a change.
    ``lasting`` is the whole lasting set from now on; ``stops`` the bursts to end first, then
    ``bursts`` start, in run order. ``restored``: a restore or landing shows ``lasting`` at
    once (no envelope, no burst). Handler: ``StageScreen.glitch``."""

    lasting: "GlitchState"
    stops: tuple[GlitchKey, ...] = ()
    bursts: tuple[GlitchBurst, ...] = ()
    restored: bool = False


@dataclass(frozen=True, slots=True)
class StoryWait(Command):
    """The story waits, with no checkpoint (``Interpreter.begin_wait``), until ``WaitDone(
    wait_id)``. ``sid`` the statement that waits; ``seconds`` a timed ``pause`` (None: an
    advance, or the stage); ``for_stage``: ends when the moment's last frame has been drawn
    (a ``with``); ``hide_box``: a ``scene`` ran since the last line (PR-F09-09). Handler:
    ``StageScreen.start_wait``."""

    wait_id: int
    sid: str
    seconds: float | None
    for_stage: bool
    hide_box: bool


# --- F30 fourth-wall tricks (F30 04-technical.md §3, §4.3; 07 I-4) ---------------------------

@dataclass(frozen=True, slots=True)
class WindowTitle(Command):
    """F30: ``effect window_title``, a restore of a saved title, or an ending card's reset.
    ``title`` is the text for the window's title bar as the script wrote it (the presentation
    cleans it); None: ``[game] title``. Handler: ``app/fourthwall.apply_title``."""

    title: str | None


@dataclass(frozen=True, slots=True)
class FakeCrash(StoryWait):
    """F30: ``effect crash``, a story wait (``begin_wait(make=...)``, 07 I-4) that shows a fake
    error screen; ``seconds`` is None and ``for_stage`` False. ``body`` is the resolved
    message (flagged ``{username}`` spans hold the fallback word); None: ``[words]
    fake_crash_message``. Handler: ``app/fourthwall.open_crash`` (by MRO, ``StageScreen``'s
    ``StoryWait`` handler until then)."""

    body: TaggedText | None = None


# --- F32 dynamic UI (F32 04-technical.md §3, §4.3, §5.2; 07 I-1) -------------------------------

@dataclass(frozen=True, slots=True)
class UiStyle(Command):
    """F32: ``ui style <name>`` / ``ui style off``, or a restore of the saved style. ``name``
    is a ``[style.<name>]`` table of ``config.toml``; None: the normal look. Handler:
    ``app/looks.py`` (F32 s4)."""

    name: str | None


@dataclass(frozen=True, slots=True)
class UiBlocks(Command):
    """F32: ``ui saving|loading off|on``, or a restore of the saved blocks: the whole new
    state of both. A reason is the text as shown (``{{`` already ``{``); None with a block:
    ``[words] saving_off`` / ``loading_off``. Handler: ``app/looks.py`` (F11's
    ``set_blocked``, F32 s4)."""

    save: bool
    save_reason: str | None
    load: bool
    load_reason: str | None


@dataclass(frozen=True, slots=True)
class DeleteSaves(Command):
    """F32: ``ui delete saves`` ran live (never on F14's quiet forward re-run, never in a
    restore burst). Handler: ``app/looks.py`` (F11's ``delete_all``; a preview deletes
    nothing); headless logs one INFO line and deletes nothing."""


# --- F31 meta files (F31 04-technical.md §3, §4.2; 07 §3(b)) ---------------------------------

@dataclass(frozen=True, slots=True)
class MetaWrite(Command):
    """F31: a ``file write`` ran live (never on F14's quiet forward re-run, never in a restore
    burst): a record, like ``ChapterStarted`` (PR-F31-18). ``name`` is the listed file name
    only, never a path or the text. Handler: ``app/metafiles.py`` (F31 s4: ``pump()``)."""

    name: str


@dataclass(frozen=True, slots=True)
class MetaDelete(Command):
    """F31: a ``file delete`` ran live (as ``MetaWrite``). ``name`` is the listed file name
    only. Handler: ``app/metafiles.py`` (F31 s4: ``pump()``)."""

    name: str


@dataclass(frozen=True, slots=True)
class ChapterStarted(Command):
    """F18: a ``chapter`` ran (held in run order, card or not, before its ``ShowStage``).
    Handler: ``install_chapters``' (F11's auto-save request); headless records it."""

    name: str
    sid: str


# --- F17 NVL mode (F17 04-technical.md §4, §5.1; 07 I-4) ------------------------------------

@dataclass(frozen=True, slots=True)
class NvlLine:
    """One line of the NVL page record as it was shown (a display record, F17 07 A1): the
    ``Say``'s sid (a menu question's is the menu's), the name as shown (``""``: no name row;
    at most 200 code points), its color (``Say.name_color`` when ``#RRGGBB``, else None: the
    theme's), and the body's spans (``plain()``, ``speed`` 1.0, equal neighbours merged; ``()``
    for an empty line). Built by ``runtime/nvl.line_of`` or read by ``NvlState.from_json``;
    never parsed as markup and never re-resolved."""

    sid: str
    name: str
    color: str | None
    spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class NvlPage(Command):
    """F17: set the text mode (``on``: full-screen text) and replace the page. Live, ``nvl
    on``/``off``/``clear`` hold it when they change the mode or page, and so does a pick in
    NVL, with ``lines`` (); a restore always sends it right after ``AudioRestore`` with the
    whole record. Handler: ``TextboxScreen.show_nvl``."""

    on: bool
    lines: tuple[NvlLine, ...] = ()


# --- F21 codex (F21 04-technical.md §5, §7.6; 06 D3) -------------------------------------------

@dataclass(frozen=True, slots=True)
class CodexAdded(Command):
    """F21: ``unlock tip`` recorded a new tip or ``unlock item`` gave an item (``kind`` is
    ``"tip"`` or ``"item"``; ``title`` is the entry's plain text from the script). Held in run
    order; never by restore, load, or New Game; F14's quiet re-run drops it with the rest of
    its burst. Handler: ``install_codex``'s notice (F21 step 3; until then ``install_story``'s
    stand-in shows nothing); headless records it and shows nothing (06 D3)."""

    kind: str
    name: str
    title: str


@dataclass(frozen=True, slots=True)
class MeterNotice(Command):
    """F62: a ``points`` line with a notice ran (``points hana += 1 "Hana will remember
    that."``); ``text`` is the notice as shown. Held in run order like ``CodexAdded``: never
    by restore, load, or New Game; F14's quiet re-run drops it with the rest of its burst.
    Handler: ``app/points.install_points``'s notice; headless records it and shows nothing."""

    meter: str
    text: str


# --- F23 minigames (F23 04-technical.md §4.1) ----------------------------------------------

@dataclass(frozen=True, slots=True)
class MeterView:
    """One declared meter as the story holds it when a minigame starts: its name, value,
    and range."""

    name: str
    value: int
    low: int
    high: int


@dataclass(frozen=True, slots=True)
class MinigameBase:
    """The story's reads at a minigame's start (PR-F23-15): the declared meters in
    declaration order, the held items in the order obtained, and the unlocked tips in
    declaration order. The host's ledger starts from it."""

    meters: tuple[MeterView, ...]
    items: tuple[str, ...]
    tips: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StartMinigame(Command):
    """A minigame starts: the checkpoint command of a ``Minigame``. ``sid`` is the line's;
    ``run`` the interpreter's ``minigame_run``, echoed by ``MinigameDone``/``MinigameUsed``,
    so a late event from an earlier start is ignored. ``args`` is read-only, in declaration
    order, of frozen values (the plugin gets a plain copy); ``0 <= seed < 2**64``.
    ``restored``: a load or a rollback landing (no dissolve-in). ``names`` (F24 A2): the
    story's declared names, one object per interpreter. Handler: F23's host (s4)."""

    sid: str
    run: int
    name: str
    args: "Mapping[str, object]"
    seed: int
    base: MinigameBase
    skippable: bool
    restored: bool
    names: StoryNames


@dataclass(frozen=True, slots=True)
class StoryEnded(Command):
    """A return with an empty call stack (PR-F03-03)."""


@dataclass(frozen=True, slots=True)
class StoryFailed(Command):
    """The story stopped on an author mistake. ``error`` is a ``StoryError`` at run time,
    or a ``ScriptErrorGroup`` for launch errors (headless). Handler:
    ``App.show_fatal_error``."""

    error: "UserFacingError"


@dataclass(frozen=True, slots=True)
class Event:
    """Base of every presentation → runtime event."""


@dataclass(frozen=True, slots=True)
class Advance(Event):
    """The player dismissed a line. ``sid`` is that line; ignored unless it is the waiting
    line, so two clicks in one frame never dismiss an unseen line."""

    sid: str


@dataclass(frozen=True, slots=True)
class WaitDone(Event):
    """F09: the wait ``wait_id`` is over (its last frame drawn, its time passed, or an
    advance). Ignored unless it is the current wait, so a late one after a restore changes
    nothing. Headless runs post it themselves."""

    wait_id: int


@dataclass(frozen=True, slots=True)
class Choose(Event):
    """F07: the player picked choice ``choice`` (its key) of menu ``sid``. Ignored unless
    ``sid`` is the waiting menu and ``choice`` one of its pickable keys (TR-F07-02)."""

    sid: str
    choice: str


@dataclass(frozen=True, slots=True)
class StepBack(Event):
    """F14: step back ``count`` steps (wheel up, Page Up, LB, the quick menu's Back). A count
    that isn't an ``int`` from 1 to 1,000 is ignored (DEBUG, area ``runtime``)."""

    count: int


@dataclass(frozen=True, slots=True)
class StepForward(Event):
    """F14: step forward ``count`` steps along the remembered path (wheel down, Page Down,
    RB), re-running the script quietly. ``count`` as ``StepBack``'s."""

    count: int


@dataclass(frozen=True, slots=True)
class MinigameDone(Event):
    """F23: the minigame ``sid`` started with ``run`` finished with ``result`` and the
    requested ``changes``, in order. Accepted once, only for the waiting minigame and its
    current ``run``; anything else is ignored (DEBUG, area ``plugin``). Posted by the host at
    the end of its fade-out, or by ``run_headless``."""

    sid: str
    run: int
    result: object
    changes: tuple[Change, ...] = ()


@dataclass(frozen=True, slots=True)
class MinigameUsed(Event):
    """F23 (04 §7.5): the player used an input in the minigame ``sid``/``run`` (the host
    posts it once per session). From then on back is refused there (``minigame_used``)."""

    sid: str
    run: int


@dataclass(frozen=True, slots=True)
class RollbackView:
    """F14 (04 §5.3): what the presentation reads each frame through the driver's
    ``rollback_view()``. Presentation-only data, never saved; all zero once FAILED.
    ``shown``: ``[rollback] steps`` > 0 (the quick menu's Back exists, inputs act).
    ``can_back``: ``back_room`` > 0. ``back_room``: how many back notches can move now.
    ``ahead``: steps forward to the newest (0: not rolled back). ``refused``: the count of
    back requests that couldn't move (the limit cue)."""

    shown: bool
    can_back: bool
    back_room: int
    ahead: int
    refused: int


__all__ = ["Advance", "AudioRestore", "BASE_STYLE", "BlipSpec", "Change", "ChapterStarted",
           "Choose", "CodexAdded", "MeterNotice", "CodexChange", "Command", "DeleteSaves", "EMPTY_TEXT", "EndVoice", "Event",
           "Fade", "FakeCrash", "Flash", "Glitch", "GlitchBurst", "GlitchKey", "INSTANT", "MetaDelete", "MetaWrite", "MeterChange", "MeterView", "MinigameBase",
           "MinigameDone", "MinigameUsed", "NameMark", "NvlLine", "NvlPage", "PauseMark", "PlayMusic", "PlaySound", "PlayVoice", "PrefetchImages", "QueueMusic",
           "RollbackView", "Say", "Shake", "ShowMenu", "ShowStage", "ShownChoice", "Span",
           "StartMinigame", "StepBack", "StepForward", "StopMusic", "StoryNames",
           "StopSound", "StopVoice", "StoryEnded", "StoryFailed", "StoryWait", "Style",
           "TaggedText", "TextEffect", "TitleCard", "TransitionSpec", "UiBlocks", "UiStyle",
           "VarMark", "WaitDone", "WaitMark",
           "WindowTitle"]
