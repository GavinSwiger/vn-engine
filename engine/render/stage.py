"""``StageView``: the stage on screen, composed once per change (F04 ``04-technical.md``
§5.3, §7.4, §7.5; ``03-ui.md`` UI-F04-01 to 13; ADR-0007).

Why this module exists: six large alpha sprites blitted every frame would cost about
20–27 ms on the reference machine (spike S0), over the 16 ms budget. So the view composes
the background and every sprite into one opaque buffer the size of the viewport when the
stage, the viewport size, or the render quality changes, and each frame costs one blit
(TR-F04-03). The buffer sits outside the shared asset cache (ADR-0007): it is one per view,
recreated only when the viewport size changes, and never a subsurface of the framebuffer
(S0 note 2). F09 (C7) adds two more view-owned buffers the same way.

Composition is drawn through a private ``Canvas`` bound to the buffer, so F01's rounding
(``px``, ``rect_to_px``), fills, and device-resolution text apply, and everything clips to
the canvas (UI-F04-06). Scaled art comes from ``AssetManager.variant`` (FINAL variants are
cached in the budget; FAST ones never are); a variant larger than ``CROP_AREA_FACTOR``
viewports is cropped to its visible part before scaling (TR-F04-06).

Names resolve once per ``show``: an ``ImageFile`` through ``assets.image`` (a missing or
broken file gives F01's placeholder ``ImageRef`` and its one log line), a ``SolidColor``,
or nothing (``no image: <name>``). A position name ``config.toml`` no longer has (only a
restored stage can name one, since the load checks E120) draws at ``center`` and logs W15
once per name per session.

Prefetch (§7.7, ADR-0007): ``prefetch`` turns a ``PrefetchImages`` into file refs through the
index and hands them to the ``ImagePrefetcher`` with the size each would be drawn at (the
cover size of a background; a sprite at zoom 1 at center, or where that tag stands now), at
the last FINAL scale, so the worker can pre-scale it under ``variant()``'s own key (I-8).
``update`` pumps it once per frame. An image the stage needs before its prefetch finished
loads synchronously in ``show`` (at most one long frame, PR-F04-21).

Transitions (F09 ``04`` §6.4): a ``ShowStage`` with a ``transition`` keeps the old picture
(the last composite, or the old stage composed on the first frame when it never was) and
its sources held, and composes the new stage into the second buffer (``_spare``, ADR-0007;
never more than two composites). A ``_Run`` then goes PREPARING → RUNNING with at most one
heavy step per frame: the frame that composes the new picture, then one
``prepare_step()`` per frame (a mask has several, ``render/transitions.py``); those frames
show the old picture (p = 0). The clock (``advance``) runs only while RUNNING; at p = 1 the
composite is blitted exactly, ``finished_drawn`` is set, and the old buffer becomes the
spare. ``finish()`` (a click, F15) gives p = 1 at the next draw, also while PREPARING. A kind
that raises ``pygame.error`` or ``MemoryError`` cuts to the new picture and logs W62 once;
that name then plays as a cut for the rest of the run (PR-F09-19).

Resize mid-transition (UI-F09-07, §6.4): during F01's FAST settle the clock stops and the
frame is the old picture (p < 0.5) or the new one (p >= 0.5), scaled. After the settle (or a
size change at FINAL quality) the transition re-prepares at the new size, one heavy step per
frame: first the picture of p's half (recomposed, and shown from then on), then the other,
then the kind's steps; the clock then resumes at the same p. The old picture's sources and
card stay held for this (``_Run.old_art``, ``old_hold``). A buffer of the wrong size is
dropped before its replacement is made, so the view never holds more than two composites,
one ``S``, and one ``B`` (TR-F09-07).

Title cards (F18 SPEC §5, 07 question 2): a ``ShowStage.card`` is painted at the top of the
composite by the injected ``card_painter`` (``ui/builtin/title_card.py``; ``app`` sets it),
so it is part of the picture: transitions, shake, flash, ``picture()``, and reduced effects
act on it as on the stage. An ``opaque`` card skips the background and sprites (they are
still resolved and held, ready for the card's way out). With no painter, a card draws
nothing. A restored stage never has a card.

Picture filter (F28 ``04`` §6.5; ``07`` I-2, I-8): ``set_filter`` takes colorshift's
``ColorShift`` (the one slot). The still stage is drawn as its filtered copy, built one
270-row band a frame after a compose; the previous filtered picture shows meanwhile, so a
cut under colorshift is up to 4 frames late (D3) and never unfiltered. A reduced fade blends
it over the composite. A transition filters both pictures while PREPARING (one band a step,
after composing) and its kind draws from the filtered copies; its last frame is the filtered
new composite. A filter change mid-transition re-prepares as a resize does. FAST frames and
``picture()`` stay plain.

Sprite frames (F38 ``SPEC.md`` §5, ``07`` I-2 to I-7; ADR-0007 F38 amendment): ``show_frames``
takes the animator's wishes (tag → blink or talking frame name; ``frames_of``, injected by
``app``, names a look's frames). A frame is used once it is ready: its file is an image of
exactly the look's size (else W217, once per file, and it is never drawn) and its FINAL
variant at the sprite's size and flip is cached. A change repaints the composite inside that
sprite's visible device rect only (``set_clip``): the background and every sprite in order,
from cached variants only, so the result is the full compose's to the pixel and costs about
1.3 ms at 1080p. At most one sprite is repainted per ``draw``, oldest change first (a tag's
newer wish replaces its pending one in place). Frames don't change during a transition, under
a title card, on a FAST frame, while a picture filter is set, before the stage is composed at
this size, or for a sprite over ``CROP_AREA_FACTOR`` viewports (``oversized``); a filter set
while a frame shows puts the plain looks back with one full compose. Every full compose draws
plain looks, and frames come back once ready. A clipped repaint never scales: a frame not
ready shows the look, and the shown looks' missing frames are asked of the prefetcher (with
``rescale`` when only the variant is missing) whenever it is idle, a few rounds per compose;
a file that can't be read is loaded once by ``assets.image`` so F01 logs it. Going back to the
look when a variant in the clip was evicted is a full compose (one long frame, I-4). A second
``AssetHold`` pins the shown looks' frame variants (I-6). ``picture()`` and F28's
``draw_sprite_copy`` show the frame on screen (I-7).
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.render.assets import AssetHold, AssetManager, ImageRef
from engine.render.canvas import RGB, Canvas, RenderQuality
from engine.render.effects import FADE_COUNTS_UNDER_S
from engine.render.placeholder import draw_placeholder
from engine.render.prefetch import (PREFETCH_ONE_MAX, PREFETCH_THREADED, PREFETCH_TOTAL_MAX,
                                    PrefetchRequest, Target)
from engine.render.transitions import KINDS, KindFrame, MaskStore, TransitionKind, progress
from engine.runtime.commands import PrefetchImages, ShowStage, TitleCard, TransitionSpec
from engine.runtime.images import ImageFile, ImageIndex, SolidColor
from engine.runtime.stage import (EMPTY_STAGE, SpriteState, StageState, first_word,
                                  position_gone_message)
from engine.runtime.glitch import glitch_refused_text
from engine.runtime.transitions import fade_refused_text, transition_failed_text

CROP_AREA_FACTOR: Final = 2              # crop a variant larger than this many viewports
MISSING_FILL: Final[RGB] = (0x20, 0x20, 0x20)       # missing background (UI-F04-09)
# The missing-background placeholder: F01's 256×256, centered (UI-F04-09, 11).
BG_PLACEHOLDER: Final = (512, 232, 256, 256)
BG_LABEL_WRAP: Final = 232
BG_BAND_CENTER_Y: Final = 360
# The missing-sprite placeholder: 320×576 at the sprite's anchor (UI-F04-10, 11).
SPRITE_PLACEHOLDER_SIZE: Final = (320, 576)
SPRITE_LABEL_WRAP: Final = 296
SPRITE_BAND_FROM_TOP: Final = 192        # the band's center, below the placeholder's top
CENTER: Final = "center"
_EPSILON: Final = 1e-9
FRAME_ASK_ROUNDS: Final = 3              # F38: prefetch asks for missing frames per compose
# F09 §12: the lengths a ``with`` leaves out, per kind (``[effects]``); a kind with no key of
# its own (a mask) takes the dissolve's.
DEFAULT_SECONDS: Final = MappingProxyType({"dissolve": 0.5, "fade": 1.0})
FALLBACK_KIND: Final = "dissolve"        # a kind not in KINDS (yet) plays as a dissolve

_log = get_logger("stage")


class ImagePrefetcher(Protocol):
    """``render/prefetch.py``'s ``ImagePrefetcher`` (a fake in tests)."""

    @property
    def pending(self) -> bool: ...

    def request(self, wanted: Iterable[PrefetchRequest]) -> None: ...

    def pump(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _Art:
    """One resolved image name: a usable file (``image``), a solid color (``rgb``), or a
    placeholder (``label``)."""

    image: ImageRef | None = None
    rgb: RGB | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class _Sprite:
    state: SpriteState
    art: _Art
    x: float                              # the anchor (bottom center), canvas units
    y: float


class SpriteFrames(Protocol):
    """F38: a look's frame names (``script/spriteframes.LookFrames``)."""
    blink: Sequence[str]
    talk: Sequence[str]


FramesOf = Callable[[str], SpriteFrames]


def frame_size_text(frame: str, size: tuple[int, int], look: str,
                    look_size: tuple[int, int]) -> str:
    """W217 (F38 §3): a frame of another size than its look is never used. ``frame`` and
    ``look`` are game-relative file refs (shown through ``echo``)."""
    return (f"{echo(frame)} is {size[0]}\u00d7{size[1]}, but its look {echo(look)} is "
            f"{look_size[0]}\u00d7{look_size[1]}, so it isn't used. Make the frame the same "
            f"size as the look.")


@dataclass(frozen=True, slots=True)
class _Place:
    """F38: where a sprite with a picture was composed at FINAL quality: its full device
    rect, its variant's size and flip, and its look."""
    rect: pygame.Rect
    size: tuple[int, int]
    flip: bool
    look: ImageRef
    name: str


_Shown = tuple[str, ImageRef]           # F38: a frame's image name and its picture


class _Admits(Protocol):
    """``render/effects.FlashLimiter`` (§6.8)."""

    def admit(self, now: float, *, reduced: bool) -> bool: ...

    def withdraw(self, at: float) -> None: ...


class CardPainter(Protocol):
    """F18's title-card painter (``ui/builtin/title_card.CardPainter``; F19 reuses it)."""

    @property
    def opaque(self) -> bool: ...

    def paint(self, canvas: Canvas, card: TitleCard) -> None: ...


class _Refusals(Protocol):
    """``render/effects.RefusalLog`` (W61 and F28's W182, once per statement)."""

    def refused(self, sid: str, text: str, code: str = "W61") -> None: ...


class PictureFilter(Protocol):
    """F28's one filter slot (04 §4.3, §6.5; 07 §2.2): ``render/glitch.ColorShift``.
    ``weight`` is 0–1 now (a reduced fade; 1 = filtered only), ``target`` the weight it
    heads to (0 or 1; a transition uses it), ``units`` its look (a change re-prepares a
    transition)."""

    weight: float
    target: float
    units: float

    def filtered(self, picture: pygame.Surface, key: tuple, *,
                 step: bool) -> pygame.Surface | None:
        """The filtered copy for ``key`` (≤ 2 kept). While ``key`` is building, the newest
        complete output of the same size (stale), or None. With ``step``, one band now."""

    def ready(self, picture: pygame.Surface, key: tuple) -> pygame.Surface | None:
        """The complete output for ``key`` only."""

    def newest(self) -> pygame.Surface | None:
        """The newest complete output, of any size."""

    def complete(self, picture: pygame.Surface, key: tuple) -> pygame.Surface | None:
        """The whole output for ``key``, built now (None: the filter failed)."""


class _Run:
    """One transition in play (§6.4): the old picture (``old``, a buffer that becomes the
    spare at the end; composed from ``old_art`` on the first frame when ``old_size`` is not
    the viewport's), the old stage's sources (``old_hold``), the kind, and the clock."""

    __slots__ = ("spec", "kind_name", "seconds", "color", "old", "old_size", "old_art",
                 "old_hold", "kind", "running", "clock", "finish", "size", "counted",
                 "old_key", "shift", "shift_units")

    def __init__(self, spec: TransitionSpec, kind_name: str, seconds: float, color: RGB,
                 old: pygame.Surface | None, old_size: tuple[int, int] | None,
                 old_art: "tuple[_Art, tuple[_Sprite, ...], TitleCard | None]",
                 old_hold: AssetHold | None) -> None:
        self.spec = spec
        self.kind_name = kind_name
        self.seconds = seconds
        self.color = color
        self.old = old
        self.old_size = old_size
        self.old_art = old_art
        self.old_hold = old_hold
        self.kind: TransitionKind | None = None
        self.running = False                     # False: PREPARING (the clock is stopped)
        self.clock = 0.0
        self.finish = False
        self.size: tuple[int, int] | None = None   # the viewport it is drawn at
        # The limiter and start time a short fade was counted at (§6.8): a click-through
        # gives it back (a player-caused cut is not a flash).
        self.counted: "tuple[_Admits, float] | None" = None
        # F28 (04 §6.5): the old picture's composite key (its filtered copy's), and the
        # filter the kind draws through (None: plain pictures) with the look it was made at.
        self.old_key: tuple | None = None
        self.shift: PictureFilter | None = None
        self.shift_units = 0.0


class StageView:
    """The stage's presentation: ``show`` a ``StageState``, ``draw`` it every frame."""

    def __init__(self, assets: AssetManager, index: ImageIndex, *, art_height: int,
                 positions: Mapping[str, tuple[float, float]], empty_color: RGB,
                 prefetcher: ImagePrefetcher | None = None,
                 seconds: Mapping[str, float] = DEFAULT_SECONDS,
                 fade_color: RGB = (0, 0, 0),
                 locate: Callable[[str], str] | None = None,
                 card_painter: CardPainter | None = None,
                 frames_of: FramesOf | None = None) -> None:
        self.assets = assets
        self.index = index
        self.art_height = art_height
        self.positions = positions
        self.empty_color = tuple(empty_color)
        self.prefetcher = prefetcher
        self.stage: StageState = EMPTY_STAGE
        self.generation = 0
        self._background = _Art(rgb=self.empty_color)
        self._sprites: tuple[_Sprite, ...] = ()
        self._card: TitleCard | None = None        # F18: drawn over the stage
        self.card_painter = card_painter            # F18: injected by ``app``
        self._hold: AssetHold | None = None
        self._warned_positions: set[str] = set()
        self._canvas = Canvas(assets)               # the composite's private canvas
        self._composite: pygame.Surface | None = None
        self._composite_key: tuple | None = None    # (generation, vw, vh, quality)
        # The geometry of the last FINAL compose (no surface): prefetch sizes come from it.
        self._final = Canvas(assets)
        # F09: the defaults a spec leaves out (``[effects]``, ``[theme.effects] fade_color``),
        # the ``with`` location formatter ``install_stage`` injects (W62's prefix), the second
        # composite, the dissolve's SRCALPHA scratch ``S``, and the transition in play.
        self.seconds = seconds
        self.fade_color = tuple(fade_color)
        self.locate = locate
        self._spare: pygame.Surface | None = None
        self._scratch: pygame.Surface | None = None
        self._masks = MaskStore(assets)          # the mask kinds' M8 cache, ``B``, bad refs
        self._run: _Run | None = None
        self._broken: set[str] = set()           # names that failed: cuts from now on (W62)
        # Whether the picture of the last ``show`` has been drawn to its last frame. Only the
        # next ``show`` resets it (07 I-4), so a wait dispatched a frame later still ends.
        self.finished_drawn = False
        self._drawn_quality: RenderQuality | None = None   # the last draw's (F28 jitter)
        # F28: the picture filter (colorshift) and the look it was set at (04 §6.5).
        self._filter: PictureFilter | None = None
        self._filter_look: tuple[float, float] | None = None
        # F38: a look's frames (injected by ``app``; None: no sprite animates), the frames in
        # the composite and the changes waiting (oldest first), the sprites' places at the
        # last FINAL compose (valid while ``_places_key`` is the composite's), the frame
        # variants held, and the prefetch rounds asked since that compose.
        self.frames_of = frames_of
        self._shown: dict[str, _Shown] = {}
        self._pending: dict[str, _Shown | None] = {}
        self._places: dict[str, _Place] = {}
        self._places_key: tuple | None = None
        self._oversized: frozenset[str] = frozenset()
        self._frame_hold: AssetHold | None = None
        self._ask_rounds = FRAME_ASK_ROUNDS
        self._frame_images: dict[str, ImageRef] = {}     # frame ref → its picture, once seen
        self._warned_frames: set[str] = set()            # W217, once per file

    # --- commands ------------------------------------------------------------------------------

    def show(self, cmd: ShowStage, *, reduce: bool = False,
             limiter: _Admits | None = None, now: float = 0.0,
             refusals: _Refusals | None = None) -> None:
        """The stage to draw from the next frame on: every name is resolved now (an image
        not in the cache loads here), and the next ``draw`` composes once. With a
        ``transition`` (and not ``restored``), the old picture stays and the transition
        starts PREPARING (§6.4); a running one is finished first. ``reduce``, ``limiter``,
        ``now`` (the effect clock), and ``refusals`` (W61) are ``StageScreen``'s (§6.4 steps
        6–7)."""
        if self._run is not None:
            self._end_run()
        self.finished_drawn = False
        spec = None if cmd.restored else cmd.transition
        card = None if cmd.restored else cmd.card
        plan = None if spec is None else self._plan(spec, reduce, limiter, now, refusals)
        if plan is None:                          # F04's cut path
            self._release(self._set(cmd.stage, card))
            return
        kind_name, seconds, color, counted = plan
        key = self._composite_key
        # The old picture is ready if it was composed for this stage at FINAL quality; else
        # the first transition frame composes it from ``old_art``.
        old_size = (key[1], key[2]) if key is not None and key[0] == self.generation \
            and key[3] is RenderQuality.FINAL else None
        old, old_art = self._composite, (self._background, self._sprites, self._card)
        old_gen = self.generation
        old_hold = self._set(cmd.stage, card)
        self._composite, self._spare, self._composite_key = self._spare, None, None
        run = self._run = _Run(spec, kind_name, seconds, color, old, old_size, old_art,
                               old_hold)
        run.counted = counted
        run.old_key = key if old_size is not None else (old_gen, 0, 0, None)
        self._run_filter(run)

    def _plan(self, spec: TransitionSpec, reduce: bool, limiter: _Admits | None,
              now: float, refusals: _Refusals | None
              ) -> "tuple[str, float, RGB, tuple[_Admits, float] | None] | None":
        """The kind, length, and color a spec plays with (§6.4 steps 5–7), and where a short
        fade was counted, or None for a cut: a zero length, or a name that failed to draw
        before (W62). A short fade over the flash limit plays as a dissolve (W61, except
        when reduced mode's one-per-second rule refused it). F28 (04 §6.6, 07 I-3): a kind
        that ``flashes`` counts only while it plays as itself (a reduced ``with glitch`` is a
        dissolve, never counted); refused, it is a dissolve with W182's transition form."""
        if spec.name in self._broken:
            return None
        seconds = spec.seconds
        if seconds is None:
            seconds = self.seconds.get(spec.kind, self.seconds.get(FALLBACK_KIND, 0.5))
        if seconds <= 0:
            return None
        kind = spec.kind if spec.kind in KINDS else FALLBACK_KIND
        if reduce and not spec.calm:
            kind = FALLBACK_KIND
        counted = None
        if (kind == "fade" or (spec.flashes and kind == spec.kind)) \
                and seconds < FADE_COUNTS_UNDER_S and limiter is not None:
            if limiter.admit(now, reduced=reduce):
                counted = (limiter, now)
            else:
                refused, kind = kind, FALLBACK_KIND
                if refusals is not None and not reduce:
                    if refused == "fade":
                        refusals.refused(spec.sid, fade_refused_text())
                    else:
                        refusals.refused(spec.sid, glitch_refused_text("transition"),
                                         code="W182")
        color = _rgb(spec.color) if spec.color is not None else self.fade_color
        return kind, float(seconds), color, counted

    @property
    def card(self) -> TitleCard | None:
        """F18: the title card of the stage shown last (None: none). Read only."""
        return self._card

    @property
    def transitioning(self) -> bool:
        """A transition is in play (PREPARING or RUNNING)."""
        return self._run is not None

    def set_filter(self, f: PictureFilter | None) -> None:
        """F28's picture filter (04 §4.3, §6.5): from the next draw, the stage picture is
        drawn through ``f`` (None: plain). Cheap when nothing changed, so ``StageScreen``
        may call it every frame; a weight change alone needs nothing. A transition in play
        whose filter (at its target weight) or look changes re-prepares at the same p
        (``_pause``, as after a resize; 07 I-2: going off re-creates only the kind)."""
        look = None if f is None else (f.units, f.target)
        if f is self._filter and look == self._filter_look:
            return
        self._filter, self._filter_look = f, look
        if f is not None and self._shown and self._run is None:
            self._composite_key = None            # F38 (07 I-2): plain looks, one compose
        run = self._run
        if run is not None:
            shift, units = run.shift, run.shift_units
            self._run_filter(run)
            if run.shift is not shift or (shift is not None and run.shift_units != units):
                self._pause(run)

    def _run_filter(self, run: _Run) -> None:
        """A run draws through the filter only when it heads to weight 1 (04 §6.5)."""
        f = self._filter
        run.shift = f if f is not None and f.target >= 1.0 else None
        run.shift_units = f.units if f is not None else 0.0

    def advance(self, dt: float) -> None:
        """The transition clock: runs only once preparation is done (§6.4)."""
        run = self._run
        if run is not None and run.running:
            run.clock += dt

    def finish(self) -> None:
        """p = 1 at the next draw, even while PREPARING (a click, F15; PR-F09-04). A short
        fade clicked through is not counted as a flash (§6.8)."""
        run = self._run
        if run is not None:
            run.finish = True
            if run.counted is not None:
                limiter, at = run.counted
                run.counted = None
                limiter.withdraw(at)

    def cancel(self) -> None:
        """Drop the transition in play (a restore, a new game): the stage shown last is the
        picture from now on, with no transition."""
        if self._run is not None:
            self._end_run()

    def _end_run(self) -> None:
        run = self._run
        assert run is not None
        self._run = None
        self._spare = run.old
        self._release(run.old_hold)

    def prefetch(self, cmd: PrefetchImages) -> None:
        """A hint about images coming soon (§7.7): each name that is an image file goes to
        the prefetcher, backgrounds first, nearest first, with how to size its variant."""
        prefetcher = self.prefetcher
        if prefetcher is None:
            return
        wanted: list[PrefetchRequest] = []
        for name in cmd.backgrounds:
            entry = self.index.get(name)
            if isinstance(entry, ImageFile):
                wanted.append(PrefetchRequest(entry.ref, self._background_target))
        for name in cmd.sprites:
            entry = self.index.get(name)
            if isinstance(entry, ImageFile):
                target = self._sprite_target(name)
                wanted.append(PrefetchRequest(entry.ref, target))
                for _, ref in self._frame_files(name):       # F38 (PR-F38-09)
                    wanted.append(PrefetchRequest(ref, target))
        prefetcher.request(wanted)

    def update(self) -> None:
        """Once per frame: one prefetched image adopted, one more file read and sent."""
        if self.prefetcher is not None:
            self.prefetcher.pump()

    @property
    def prefetch_pending(self) -> bool:
        """Whether prefetching is still going on: queued files or a decode in flight (F15
        I-7: skip may wait on it, briefly). Read only."""
        return self.prefetcher is not None and self.prefetcher.pending

    def clear(self) -> None:
        """The empty stage (a new game, the way back to the title): nothing of the last
        game may show (F10 I-8)."""
        self.cancel()
        self._release(self._set(EMPTY_STAGE))

    def set_index(self, index: ImageIndex) -> None:
        """F39: a rebuilt image index; the current stage is resolved again."""
        self.cancel()
        self.index = index
        self._frame_images.clear()                # F38: frame files may have changed
        self._release(self._set(self.stage, self._card))

    @staticmethod
    def _release(hold: AssetHold | None) -> None:
        if hold is not None:
            hold.release()

    def picture(self) -> pygame.Surface | None:
        """F09's seam: the last complete composite (None before the first ``draw``); during
        a transition whose new picture is not composed yet, the old one."""
        run = self._run
        if run is not None and self._composite_key is None and run.old_size is not None:
            return run.old
        return self._composite

    # --- F38 sprite frames (module docstring; ADR-0007 F38 amendment) --------------------------

    @property
    def oversized(self) -> frozenset[str]:
        """F38: the tags of sprites too big to animate (a variant over
        ``CROP_AREA_FACTOR`` viewports at the last FINAL compose). Read only."""
        return self._oversized

    @property
    def frames_held(self) -> bool:
        """F38 (07 I-2): frames can't change now: a transition, a title card, a picture
        filter, or the last draw was a FAST frame. Read only."""
        return (self._run is not None or self._card is not None or self._filter is not None
                or self._drawn_quality is not RenderQuality.FINAL)

    @property
    def shown_frames(self) -> Mapping[str, str]:
        """F38: tag → the frame name drawn in the composite now. Read only."""
        return MappingProxyType({tag: shown[0] for tag, shown in self._shown.items()})

    def show_frames(self, wanted: Mapping[str, str]) -> None:
        """F38: each sprite shows the frame ``wanted`` names for its tag once that frame is
        ready, else its look; the next draws repaint the changes, one sprite each, oldest
        first. Missing frames of the shown looks are asked of the idle prefetcher."""
        self._ask_frames()
        key = self._composite_key
        if self.frames_held or key is None or key != self._places_key:
            self._pending.clear()
            return
        pending = self._pending
        for tag in list(pending):
            if tag not in self._places:
                del pending[tag]
        for tag, place in self._places.items():
            name = wanted.get(tag)
            image = None if name is None else self._ready_frame(place, name)
            shown = self._shown.get(tag)
            if (None if shown is None else shown[0]) == (None if image is None else name):
                pending.pop(tag, None)
            else:
                pending[tag] = None if image is None or name is None else (name, image)

    def _frame_files(self, look: str) -> list[tuple[str, str]]:
        """``look``'s frames that are image files: ``(frame name, file ref)``, play order."""
        frames_of = self.frames_of
        if frames_of is None:
            return []
        frames = frames_of(look)
        out = []
        for name in (*frames.blink, *frames.talk):
            entry = self.index.get(name)
            if isinstance(entry, ImageFile):
                out.append((name, entry.ref))
        return out

    def _place_sprites(self, vw: int, vh: int) -> None:
        """After a FINAL compose: each sprite's place, the oversized tags, and the second
        ``AssetHold`` on the shown looks' frame variants (07 I-6); the prefetch asks start
        again."""
        places: dict[str, _Place] = {}
        oversized: set[str] = set()
        keys: list[tuple] = []
        c = self._canvas
        for sprite in self._sprites:
            image = sprite.art.image
            if image is None:
                continue
            tag, flip = sprite.state.tag, sprite.state.flip
            rect, size = self._sprite_rect(c, image.size, sprite.x, sprite.y, sprite.state.zoom)
            if size[0] * size[1] > CROP_AREA_FACTOR * vw * vh:
                oversized.add(tag)
                continue
            places[tag] = _Place(pygame.Rect(rect.topleft, size), size, flip, image,
                                 sprite.state.image)
            for _, ref in self._frame_files(sprite.state.image):
                keys.append(("img", ref) if size == image.size and not flip
                            else self.assets.variant_key(ref, size, flip))
        self._places, self._oversized = places, frozenset(oversized)
        self._places_key = self._composite_key
        old, self._frame_hold = self._frame_hold, AssetHold(self.assets.cache, keys)
        self._release(old)
        self._ask_rounds = 0

    def _frame_image(self, ref: str) -> ImageRef | None:
        """The frame file's picture once its source has been in the cache (no load)."""
        image = self._frame_images.get(ref)
        if image is None and self.assets.is_cached(ref):
            image = self.assets.image(ref)        # a cache hit: nothing is read
            if image.is_placeholder:
                return None
            self._frame_images[ref] = image
        return image

    def _ready_frame(self, place: _Place, name: str) -> ImageRef | None:
        """The frame ``name``'s picture when it can be drawn at ``place`` now: an image file
        of the look's size (else W217) whose variant there is cached."""
        entry = self.index.get(name)
        if not isinstance(entry, ImageFile):
            return None
        image = self._frame_image(entry.ref)
        if image is None or not self._same_size(entry.ref, image, place):
            return None
        if self.assets.cached_variant(image, place.size, flip_x=place.flip) is None:
            return None
        return image

    def _same_size(self, ref: str, image: ImageRef, place: _Place) -> bool:
        """W217 once per file when the frame isn't its look's size."""
        look = place.look
        if image.size == look.size:
            return True
        if ref not in self._warned_frames:
            self._warned_frames.add(ref)
            _log.warning("%s", frame_size_text(ref, image.size, look.ref, look.size),
                         extra={"code": "W217"})
        return False

    def _ask_frames(self) -> None:
        """PR-F38-09: while the prefetcher is idle, ask it for the shown looks' frames whose
        variant at the sprite's size and flip isn't cached (``rescale``: the source may be),
        up to ``FRAME_ASK_ROUNDS`` times per compose. From the second round a file that
        can't be read is loaded once by ``assets.image`` (F01 logs it). Under the ``pixel``
        filter (never pre-scaled by the worker) one cached frame is scaled here per call
        (nearest-neighbour, cheap)."""
        if self._ask_rounds >= FRAME_ASK_ROUNDS:
            return
        prefetcher = self.prefetcher
        if prefetcher is not None and prefetcher.pending:
            return
        assets = self.assets
        wanted: list[PrefetchRequest] = []
        for place in self._places.values():
            for _, ref in self._frame_files(place.name):
                image = self._frame_image(ref)
                if image is not None:
                    if not self._same_size(ref, image, place) or assets.cached_variant(
                            image, place.size, flip_x=place.flip) is not None:
                        continue
                    if assets.scale_filter == "pixel":
                        assets.variant(image, place.size, RenderQuality.FINAL,
                                       flip_x=place.flip)
                        return                    # one a frame; the round isn't counted
                elif self._ask_rounds > 0 and assets.read_image_bytes(ref) is None:
                    assets.image(ref)             # F01's one log line; the look shows
                    continue
                wanted.append(PrefetchRequest(ref, _frame_target(place), rescale=True))
        self._ask_rounds = self._ask_rounds + 1 if wanted else FRAME_ASK_ROUNDS
        if wanted and prefetcher is not None:
            prefetcher.request(wanted)

    def _repaint(self, canvas: Canvas) -> None:
        """One pending change, oldest first: a change that can't be drawn now is dropped
        (the next ``show_frames`` asks again) and the next one is tried."""
        while self._pending:
            tag = next(iter(self._pending))
            want = self._pending.pop(tag)
            if self._repaint_one(canvas, tag, want):
                return

    def _repaint_one(self, canvas: Canvas, tag: str, want: _Shown | None) -> bool:
        """``tag`` shows ``want`` (None: its look): the composite is repainted inside the
        sprite's visible rect from cached variants only. True when something was drawn."""
        place = self._places.get(tag)
        composite = self._composite
        if place is None or composite is None:
            return False
        shown = dict(self._shown)
        if want is None:
            shown.pop(tag, None)
        else:
            shown[tag] = want
        vw, vh = composite.get_size()
        clip = place.rect.clip(pygame.Rect(0, 0, vw, vh))
        if clip.width <= 0 or clip.height <= 0:
            self._shown = shown                   # off screen: nothing to draw
            return False
        c = self._canvas
        c.final_scale = canvas.final_scale
        c.bind(composite, Viewport(CANVAS_SIZE[0], CANVAS_SIZE[1], vw, vh, 0, 0, vw, vh),
               RenderQuality.FINAL)
        target = c.surface
        assert target is not None
        try:
            ops, miss = self._clip_ops(c, clip, shown, vw, vh)
            if ops is not None:
                target.set_clip(clip)
                for op in ops:
                    op(c, target)
                target.set_clip(None)
                self._shown = shown
                return True
        finally:
            c.surface = None
        if miss == "art":                         # a look's or the background's variant was
            self._compose(canvas)                 # evicted: plain looks, one compose (I-4)
            return True
        return False                              # the frame waits

    def _clip_ops(self, c: Canvas, clip: pygame.Rect, shown: Mapping[str, _Shown], vw: int,
                  vh: int) -> "tuple[list[Callable[[Canvas, pygame.Surface], object]] | None, str]":
        """The draws of a clipped repaint, in the full compose's order and through its own
        code for the background and looks (so the pixels are the same), or ``(None, what)``
        when a variant isn't cached: ``"art"`` (the background or a look) or ``"frame"``."""
        final = RenderQuality.FINAL
        background = self._background
        if background.image is not None:
            size = _cover_size(background.image.size, vw, vh)
            dest = ((vw - size[0]) // 2, (vh - size[1]) // 2)
            if not self._variant_cached(background.image, size, dest, False, vw, vh):
                return None, "art"
        ops: list[Callable[[Canvas, pygame.Surface], object]] = [
            lambda cc, t: self._draw_background(cc, t, background, vw, vh, final)]
        for sprite in self._sprites:
            image = sprite.art.image
            if image is None:                     # a solid color or a placeholder
                ops.append(lambda cc, t, s=sprite: self._draw_sprite(cc, t, s, vw, vh, final))
                continue
            flip = sprite.state.flip
            rect, size = self._sprite_rect(c, image.size, sprite.x, sprite.y, sprite.state.zoom)
            full = pygame.Rect(rect.topleft, size)
            if not full.colliderect(clip):
                continue
            frame = shown.get(sprite.state.tag)
            if frame is None:
                if not self._variant_cached(image, size, rect.topleft, flip, vw, vh):
                    return None, "art"
                ops.append(lambda cc, t, s=sprite: self._draw_sprite(cc, t, s, vw, vh, final))
                continue
            found = self.assets.cached_variant(frame[1], size, flip_x=flip)
            if found is None:
                return None, "frame"
            art, offset = found
            at = (full.x + offset[0], full.y + offset[1])
            ops.append(lambda cc, t, art=art, at=at: t.blit(art, at))
        return ops, ""

    def _variant_cached(self, image: ImageRef, size: tuple[int, int], dest: tuple[int, int],
                        flip: bool, vw: int, vh: int) -> bool:
        """Whether ``_blit`` would find its variant (cropped like it) in the cache."""
        full = pygame.Rect(dest, size)
        visible = full.clip(pygame.Rect(0, 0, vw, vh))
        if visible.width <= 0 or visible.height <= 0:
            return True
        crop = None
        if size[0] * size[1] > CROP_AREA_FACTOR * vw * vh:
            crop = (visible.x - full.x, visible.y - full.y, visible.width, visible.height)
        return self.assets.cached_variant(image, size, flip_x=flip, crop=crop) is not None

    # --- drawing ---------------------------------------------------------------------------

    def draw(self, canvas: Canvas, offset_px: tuple[int, int] = (0, 0)) -> None:
        """One blit of the composite onto ``canvas.surface`` at ``offset_px`` (F09 step 4's
        shake). FAST quality (F01's resize settle) with a composite of this stage scales the
        last composite, uncached; otherwise a new stage, viewport size, or quality composes
        first (UI-F04-12). A transition in play draws its frame instead (§6.4)."""
        surface = canvas.surface
        assert surface is not None, "Canvas.bind() has not been called"
        size = surface.get_size()
        self._drawn_quality = canvas.quality
        run = self._run
        if run is not None:
            if canvas.quality is not RenderQuality.FAST:
                self._draw_run(canvas, surface, size, run, offset_px)
                return
            if not run.finish:
                self._draw_settling(canvas, surface, size, run, offset_px)
                return
            self._end_run()                       # a click during the settle: the new picture
        composite = self._composite
        key = self._composite_key
        if (canvas.quality is RenderQuality.FAST and composite is not None and key is not None
                and key[0] == self.generation):
            if composite.get_size() != size:
                composite = pygame.transform.scale(composite, size)
            surface.blit(composite, offset_px)
            self.finished_drawn = True
            return
        composed = key != (self.generation, size[0], size[1], canvas.quality)
        if composed:
            self._compose(canvas)
        elif self._pending and self._filter is None and self._card is None \
                and canvas.quality is RenderQuality.FINAL:
            self._repaint(canvas)                 # F38: at most one sprite's rect
        composite = self._composite
        assert composite is not None
        f = self._filter
        if f is None or canvas.quality is RenderQuality.FAST:
            surface.blit(composite, offset_px)
            self.finished_drawn = True
            return
        self._draw_filtered(f, surface, composite, size, offset_px, step=not composed)

    def _draw_filtered(self, f: PictureFilter, surface: pygame.Surface,
                       composite: pygame.Surface, size: tuple[int, int],
                       offset_px: tuple[int, int], *, step: bool) -> None:
        """The still stage through the filter (04 §6.5, 07 I-8): one band built a frame
        (none in a frame that composed). At weight 1 the filtered picture alone, the
        previous one while the new one builds (D3; ``finished_drawn`` waits for the
        current one); below 1 the composite with the current filtered copy over it at
        alpha ``round(255·weight)`` (a reduced fade)."""
        key = self._composite_key
        assert key is not None
        out, current = self._filtered(f, composite, key, size, step=step)
        weight = f.weight
        if weight >= 1.0 and out is not None:
            surface.blit(out, offset_px)
            self.finished_drawn = self.finished_drawn or current
            return
        surface.blit(composite, offset_px)
        self.finished_drawn = True
        if out is not None and current and weight > 0.0:
            out.set_alpha(round(255 * weight))
            surface.blit(out, offset_px)
            out.set_alpha(None)

    @staticmethod
    def _filtered(f: PictureFilter, picture: pygame.Surface, key: tuple,
                  size: tuple[int, int], *, step: bool) -> tuple[pygame.Surface | None, bool]:
        """The filtered copy to show for ``picture`` and whether it is ``key``'s own (07
        I-8): built (with ``step``, one more band first), else the previous one of this
        size, else the newest of another size scaled (after a resize), else the whole copy
        built now (a load, colorshift's first frame). None: the filter failed (plain)."""
        out = f.filtered(picture, key, step=step)
        if out is not None:
            return out, out is f.ready(picture, key)
        stale = f.newest()
        if stale is not None:
            return pygame.transform.scale(stale, size), False
        out = f.complete(picture, key)
        return out, out is not None

    def draw_sprite_copy(self, surface: pygame.Surface, tag: str,
                         offset_px: tuple[int, int]) -> bool:
        """F28 jitter (04 §6.4, 07 §2.2): a copy of sprite ``tag``'s held FINAL variant over
        ``surface`` (the stage viewport this frame's ``draw`` drew into) at its place in the
        composite moved by ``offset_px`` device pixels, clipped to the viewport. It never
        composes or scales: a cropped variant (TR-F04-06) is the composite's own crop. False,
        drawing nothing, while a transition is in play (D2), on a FAST frame, under a title
        card, for a tag not on the shown stage, for a placeholder or solid-color sprite, or
        before the stage is composed at this size. F38 feeds it the current frame."""
        if (self._run is not None or self._drawn_quality is not RenderQuality.FINAL
                or self._card is not None):
            return False
        key = self._composite_key
        vw, vh = surface.get_size()
        if key is None or key[0] != self.generation or (key[1], key[2]) != (vw, vh):
            return False
        sprite = None
        for candidate in self._sprites:
            if candidate.state.tag == tag:
                sprite = candidate
                break
        if sprite is None or sprite.art.image is None:
            return False
        image = sprite.art.image
        shown = self._shown.get(tag)              # F38: the frame on screen, never cropped
        if shown is not None:
            rect, size = self._sprite_rect(self._canvas, image.size, sprite.x, sprite.y,
                                           sprite.state.zoom)
            found = self.assets.cached_variant(shown[1], size, flip_x=sprite.state.flip)
            if found is not None:
                art, offset = found
                surface.blit(art, (rect.x + offset[0] + offset_px[0],
                                   rect.y + offset[1] + offset_px[1]))
                return True
        rect, size = self._sprite_rect(self._canvas, image.size, sprite.x, sprite.y,
                                       sprite.state.zoom)
        full = pygame.Rect(rect.topleft, size)
        visible = full.clip(pygame.Rect(0, 0, vw, vh))
        if visible.width <= 0 or visible.height <= 0:
            return False
        flip = sprite.state.flip
        if size[0] * size[1] > CROP_AREA_FACTOR * vw * vh:
            crop = (visible.x - full.x, visible.y - full.y, visible.width, visible.height)
            art, offset = self.assets.variant(image, size, RenderQuality.FINAL, flip_x=flip,
                                              crop=crop)
        else:
            art, offset = self.assets.variant(image, size, RenderQuality.FINAL, flip_x=flip)
        surface.blit(art, (full.x + offset[0] + offset_px[0], full.y + offset[1] + offset_px[1]))
        return True

    def _draw_settling(self, canvas: Canvas, surface: pygame.Surface, size: tuple[int, int],
                       run: _Run, offset: tuple[int, int]) -> None:
        """A frame of F01's FAST settle mid-transition: the clock stops (re-preparing
        follows) and the picture of p's half is drawn, scaled (UI-F09-07)."""
        self._pause(run)
        run.size = size
        key = self._composite_key
        if progress(run.clock, run.seconds) >= 0.5:
            if key is None or key[0] != self.generation or self._composite is None:
                self._compose(canvas)
            picture = self._composite
        else:
            if run.old is None:                   # never composed: now, at FAST quality
                run.old = self._paint(canvas, None, *run.old_art)
                run.old_size = None               # ...so it is composed again after the settle
            picture = run.old
        assert picture is not None
        if picture.get_size() != size:
            picture = pygame.transform.scale(picture, size)
        surface.blit(picture, offset)

    @staticmethod
    def _pause(run: _Run) -> None:
        """Stop the clock and drop the kind: the transition re-prepares at the new size and
        resumes at the same p."""
        run.running = False
        run.kind = None

    def _draw_run(self, canvas: Canvas, surface: pygame.Surface, size: tuple[int, int],
                  run: _Run, offset: tuple[int, int]) -> None:
        """One frame of the transition, with at most one heavy step (§6.4)."""
        if run.size is not None and run.size != size:
            self._pause(run)                      # a resize at FINAL quality
        run.size = size
        new_ready = self._composite_key == (self.generation, size[0], size[1], canvas.quality)
        p = 1.0 if run.finish else progress(run.clock, run.seconds)
        if run.running or p >= 1.0:
            if p < 1.0 and run.kind is not None:
                try:
                    run.kind.draw(surface, p, offset)
                    return
                except (pygame.error, MemoryError) as exc:
                    self._failed(run, exc)
            self._end_frame(canvas, surface, new_ready, offset)
            return
        # PREPARING (p = 0), or re-preparing after a resize (at the p it stopped at): the
        # picture of p's half is composed first and shown while one heavy step runs. Under
        # F28's filter both pictures are then filtered (one band a step, p's half first;
        # shown filtered meanwhile), and the kind draws from the filtered copies.
        new_half = p >= 0.5
        old_ready = run.old is not None and run.old_size == size
        shift = run.shift
        todo = None
        if new_half and not new_ready:
            self._compose(canvas)
            new_ready = True
        elif not old_ready:
            if run.old is not None and run.old.get_size() != size:
                run.old = None                    # dropped before the new one is made
            run.old = self._paint(canvas, run.old, *run.old_art)
            run.old_size = size
            assert run.old_key is not None
            run.old_key = (run.old_key[0], size[0], size[1], canvas.quality)
        elif not new_ready:
            self._compose(canvas)
        elif shift is not None and (todo := self._unfiltered(run, shift, new_half)):
            shift.filtered(*todo, step=True)      # one band
        else:
            try:
                if run.kind is None:
                    old, new = self._pictures(run, shift)
                    run.kind = KINDS[run.kind_name](KindFrame(
                        old, new, run.color, self._scratch_for, run.spec, self._masks,
                        run.seconds))
                run.running = run.kind.prepare_step()
            except (pygame.error, MemoryError) as exc:
                self._failed(run, exc)
                self._end_frame(canvas, surface, new_ready, offset)
                return
        picture = self._composite if new_half else run.old
        key = self._composite_key if new_half else run.old_key
        assert picture is not None
        if shift is not None and key is not None and picture.get_size() == size:
            picture = self._filtered(shift, picture, key, size, step=False)[0] or picture
        surface.blit(picture, offset)

    def _unfiltered(self, run: _Run, shift: PictureFilter,
                    new_half: bool) -> tuple[pygame.Surface, tuple] | None:
        """The first picture of the run (p's half first) whose filtered copy isn't built."""
        pairs = ((run.old, run.old_key), (self._composite, self._composite_key))
        for picture, key in (pairs[::-1] if new_half else pairs):
            if picture is not None and key is not None and shift.ready(picture, key) is None:
                return picture, key
        return None

    def _pictures(self, run: _Run,
                  shift: PictureFilter | None) -> tuple[pygame.Surface, pygame.Surface]:
        """What the kind draws from: both composites, or their filtered copies (built by
        now; a filter that failed gives the plain ones)."""
        old, new = run.old, self._composite
        assert old is not None and new is not None
        if shift is None:
            return old, new
        old_key, new_key = run.old_key, self._composite_key
        assert old_key is not None and new_key is not None
        return shift.ready(old, old_key) or old, shift.ready(new, new_key) or new

    def _end_frame(self, canvas: Canvas, surface: pygame.Surface, new_ready: bool,
                   offset: tuple[int, int]) -> None:
        """p = 1: the new composite, exactly (under F28's filter its filtered copy, built
        now if it isn't yet: TR-F28-05); the transition is over."""
        if not new_ready:
            self._compose(canvas)
        run = self._run
        shift = run.shift if run is not None else None
        self._end_run()
        picture, key = self._composite, self._composite_key
        assert picture is not None and key is not None
        if shift is not None:
            picture = shift.ready(picture, key) or shift.complete(picture, key) or picture
        surface.blit(picture, offset)
        self.finished_drawn = True

    def _scratch_for(self) -> pygame.Surface:
        """``S``: the one SRCALPHA buffer the size of the viewport (recreated on resize)."""
        run = self._run
        size = run.size if run is not None and run.size is not None else (1, 1)
        if self._scratch is None or self._scratch.get_size() != size:
            self._scratch = None
            self._scratch = pygame.Surface(size, pygame.SRCALPHA, 32)
        return self._scratch

    def _failed(self, run: _Run, exc: BaseException) -> None:
        """W62 (built-in form): the kind failed; this name cuts from now on (PR-F09-19)."""
        name = run.spec.name
        if name in self._broken:
            return
        self._broken.add(name)
        where = self.locate(run.spec.sid) if self.locate is not None else ""
        _log.warning("%s%s", where, transition_failed_text(name, type(exc).__name__),
                     extra={"code": "W62"})

    def _compose(self, canvas: Canvas) -> None:
        """§7.4: the current stage into the composite (one of another size is dropped
        before the new one is made, C7)."""
        surface = canvas.surface
        assert surface is not None
        if self._composite is not None and self._composite.get_size() != surface.get_size():
            self._composite = None
        self._composite = self._paint(canvas, self._composite, self._background,
                                      self._sprites, self._card)
        vw, vh = surface.get_size()
        self._composite_key = (self.generation, vw, vh, canvas.quality)
        self._shown = {}                          # F38 (07 I-3): plain looks
        self._pending.clear()
        if canvas.quality is RenderQuality.FINAL:
            self._final.viewport = self._canvas.viewport
            self._place_sprites(vw, vh)

    def _paint(self, canvas: Canvas, buffer: pygame.Surface | None, background: _Art,
               sprites: tuple[_Sprite, ...], card: TitleCard | None = None
               ) -> pygame.Surface:
        """The background, then each sprite in tuple order, then the card (F18), into
        ``buffer`` (made the viewport's size, in the framebuffer's format, when it isn't).
        An opaque card is all there is to draw."""
        surface = canvas.surface
        assert surface is not None
        vw, vh = surface.get_size()
        quality = canvas.quality
        if buffer is None or buffer.get_size() != (vw, vh):
            buffer = None
            buffer = pygame.Surface((vw, vh), 0, surface)   # framebuffer format
        c = self._canvas
        c.final_scale = canvas.final_scale
        c.bind(buffer, Viewport(CANVAS_SIZE[0], CANVAS_SIZE[1], vw, vh, 0, 0, vw, vh), quality)
        target = c.surface
        assert target is not None
        painter = self.card_painter if card is not None else None
        if painter is None or not painter.opaque:
            self._draw_background(c, target, background, vw, vh, quality)
            for sprite in sprites:
                self._draw_sprite(c, target, sprite, vw, vh, quality)
        if painter is not None:
            assert card is not None
            painter.paint(c, card)
        c.surface = None                          # nothing keeps the buffer's subsurface
        return buffer

    def _draw_background(self, c: Canvas, target: pygame.Surface, art: _Art, vw: int, vh: int,
                         quality: RenderQuality) -> None:
        if art.rgb is not None:                   # the empty stage, or a solid color
            c.fill(art.rgb)
            return
        if art.image is None:                     # missing: #202020 and the placeholder
            c.fill(MISSING_FILL)
            draw_placeholder(c, BG_PLACEHOLDER, art.label or "", wrap=BG_LABEL_WRAP,
                             band_center_y=BG_BAND_CENTER_Y)
            return
        c.fill(self.empty_color)                  # under any transparent pixels
        size = _cover_size(art.image.size, vw, vh)
        dest = ((vw - size[0]) // 2, (vh - size[1]) // 2)
        self._blit(target, art.image, size, dest, False, vw, vh, quality)

    def _draw_sprite(self, c: Canvas, target: pygame.Surface, sprite: _Sprite, vw: int,
                     vh: int, quality: RenderQuality) -> None:
        art = sprite.art
        x, y = sprite.x, sprite.y
        if art.rgb is not None:                   # a solid color fills the canvas (UI-F04-04)
            c.fill(art.rgb)
            return
        if art.image is None:                     # 320×576, never zoomed or mirrored
            pw, ph = SPRITE_PLACEHOLDER_SIZE
            draw_placeholder(c, (x - pw / 2, y - ph, pw, ph), art.label or "",
                             wrap=SPRITE_LABEL_WRAP, band_center_y=y - ph + SPRITE_BAND_FROM_TOP)
            return
        rect, size = self._sprite_rect(c, art.image.size, x, y, sprite.state.zoom)
        self._blit(target, art.image, size, rect.topleft, sprite.state.flip, vw, vh, quality)

    def _sprite_rect(self, c: Canvas, source: tuple[int, int], x: float, y: float,
                     zoom: float) -> tuple[pygame.Rect, tuple[int, int]]:
        """A sprite's device rect at anchor ``(x, y)`` and the size its variant is scaled to
        (UI-F04-05); 1:1 art keeps its source size, so it is blitted unscaled."""
        w, h = source
        k = zoom * CANVAS_SIZE[1] / self.art_height
        rect = c.rect_to_px((x - w * k / 2, y - h * k, w * k, h * k))
        if abs(k * c.scale_x - 1.0) < _EPSILON and abs(k * c.scale_y - 1.0) < _EPSILON:
            return rect, (w, h)
        return rect, (max(1, rect.width), max(1, rect.height))

    # --- prefetch sizes (§7.7) --------------------------------------------------------------

    def _background_target(self, w: int, h: int) -> Target:
        """The cover size at the last FINAL viewport (None before one, or when it's 1:1)."""
        viewport = self._final.viewport
        if viewport is None:
            return None
        size = _cover_size((w, h), viewport.w, viewport.h)
        return None if size == (w, h) else (size, False)

    def _sprite_target(self, name: str):
        """How to size the sprite ``name``: where the sprite showing the same art stands now
        (an expression change keeps its place, zoom, and mirroring), else zoom 1 at
        ``center``. No variant when it would be 1:1 or cropped (TR-F04-06)."""
        word = first_word(name)
        on_stage = [s for s in self._sprites if first_word(s.state.image) == word]
        here = next((s for s in on_stage if s.state.tag == word), None) or \
            (on_stage[0] if on_stage else None)
        if here is not None:
            x, y, zoom, flip = here.x, here.y, here.state.zoom, here.state.flip
        else:
            point = self.positions.get(CENTER, (CANVAS_SIZE[0] / 2, CANVAS_SIZE[1]))
            x, y, zoom, flip = float(point[0]), float(point[1]), 1.0, False

        def target(w: int, h: int) -> Target:
            viewport = self._final.viewport
            if viewport is None:
                return None
            _, size = self._sprite_rect(self._final, (w, h), x, y, zoom)
            if size[0] * size[1] > CROP_AREA_FACTOR * viewport.w * viewport.h:
                return None
            if size == (w, h) and not flip:
                return None
            return size, flip

        return target

    def _blit(self, target: pygame.Surface, image: ImageRef, size: tuple[int, int],
              dest: tuple[int, int], flip: bool, vw: int, vh: int,
              quality: RenderQuality) -> None:
        """``image`` at ``size`` device pixels with its top-left at ``dest``; a variant over
        ``CROP_AREA_FACTOR`` viewports is cropped to the visible part first, and art with
        nothing visible is skipped."""
        full = pygame.Rect(dest, size)
        visible = full.clip(pygame.Rect(0, 0, vw, vh))
        if visible.width <= 0 or visible.height <= 0:
            return
        if size[0] * size[1] > CROP_AREA_FACTOR * vw * vh:
            crop = (visible.x - full.x, visible.y - full.y, visible.width, visible.height)
            surface, offset = self.assets.variant(image, size, quality, flip_x=flip,
                                                  crop=crop)
        else:
            surface, offset = self.assets.variant(image, size, quality, flip_x=flip)
        target.blit(surface, (dest[0] + offset[0], dest[1] + offset[1]))

    # --- resolving -----------------------------------------------------------------------------

    def _set(self, stage: StageState, card: TitleCard | None = None) -> AssetHold | None:
        """Resolve ``stage`` (with ``card`` over it) and hold its sources; returns the
        previous hold, which the caller releases (now, or at a transition's end)."""
        self.stage = stage
        self._card = card
        self.generation += 1
        self._shown = {}                          # F38: a new stage shows plain looks
        self._pending.clear()
        self._places, self._places_key, self._oversized = {}, None, frozenset()
        self._release(self._frame_hold)
        self._frame_hold = None
        held: list[tuple] = []
        background = _Art(rgb=self.empty_color) if stage.background is None \
            else self._resolve(stage.background, held)
        sprites = []
        for state in stage.sprites:
            x, y = self._anchor(state)
            sprites.append(_Sprite(state, self._resolve(state.image, held), x, y))
        self._background = background
        self._sprites = tuple(sprites)
        previous = self._hold
        self._hold = AssetHold(self.assets.cache, held)   # sources stay while on stage
        return previous

    def _resolve(self, name: str, held: list[tuple]) -> _Art:
        entry = self.index.get(name)
        if isinstance(entry, SolidColor):
            return _Art(rgb=entry.rgb)
        if isinstance(entry, ImageFile):
            image = self.assets.image(entry.ref)
            if image.is_placeholder:
                return _Art(label=image.label)
            held.append(image._key)
            return _Art(image=image)
        return _Art(label=f"no image: {echo(name)}")

    def _anchor(self, sprite: SpriteState) -> tuple[float, float]:
        """The sprite's position in canvas units: a name from ``[stage.positions]`` (with
        the built-ins), ``(x,)`` on the bottom edge, or ``(x, y)``."""
        at = sprite.at
        if isinstance(at, str):
            point = self.positions.get(at)
            if point is None:
                if at not in self._warned_positions:
                    self._warned_positions.add(at)
                    _log.warning("%s", position_gone_message(sprite.tag, at))
                point = self.positions.get(CENTER, (CANVAS_SIZE[0] / 2, CANVAS_SIZE[1]))
            return float(point[0]), float(point[1])
        if len(at) == 1:
            return float(at[0]), float(CANVAS_SIZE[1])
        return float(at[0]), float(at[1])        # type: ignore[misc]


def _rgb(color: str) -> RGB:
    """``#RRGGBB`` → RGB (a spec's color is always this form, 04 §5.1)."""
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _frame_target(place: _Place) -> Callable[[int, int], Target]:
    """F38: a frame's pre-scaled variant is its look's (none for another size: W217)."""
    look_size, size, flip = place.look.size, place.size, place.flip

    def target(w: int, h: int) -> Target:
        if (w, h) != look_size or (size == (w, h) and not flip):
            return None
        return size, flip

    return target


def _cover_size(source: tuple[int, int], vw: int, vh: int) -> tuple[int, int]:
    """A background's size covering ``vw × vh`` (UI-F04-03): scaled by the larger ratio,
    rounded up so every pixel is covered."""
    w, h = source
    f = max(vw / w, vh / h)
    return math.ceil(w * f - _EPSILON), math.ceil(h * f - _EPSILON)


__all__ = ["CROP_AREA_FACTOR", "CardPainter", "DEFAULT_SECONDS", "FALLBACK_KIND",
           "FRAME_ASK_ROUNDS", "FramesOf", "ImagePrefetcher", "SpriteFrames",
           "frame_size_text", "MISSING_FILL", "PREFETCH_ONE_MAX", "PREFETCH_THREADED",
           "PREFETCH_TOTAL_MAX", "PictureFilter", "StageView"]
