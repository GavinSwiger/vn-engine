"""``StageScreen``: the stage, the bottom layer of the in-game screens (F04 ``04-technical.md``
§3.1, §5.4, §7.5; ``03-ui.md`` "Screens and elements", UI-F04-01, UI-F04-08; F09 ``04``
§4.4, §6.3).

Why this module exists: the stage covers the whole canvas every frame, so it is an opaque
screen at the bottom of the in-game stack (``bootstrap.in_game_screens``), and every other
in-game layer (F05's ``TextboxScreen``, F07's choices, the menus) draws
above it, a sprite on layer 100 included. It draws its ``StageView`` and takes no input:
events it is offered fall through to nothing (``handle_event`` returns False).

One ``StageScreen`` serves a whole launch: ``app/story.py: install_stage`` builds it once and
registers its handlers (``ShowStage`` → ``show_stage``, ``StoryWait`` → ``start_wait``,
``Shake``, ``Flash``; F09 C6), so the picture survives New Game and the way back to the
title, and ``clear()`` empties it in between (F10 I-8). It is ``in_game`` (F09 C9, F10
C2–C3): the story runs while it is the top in-game screen.

F09 waits (§6.3): the story holds at a ``with`` or a ``pause`` until this screen posts
``WaitDone(wait_id)``. ``start_wait`` clears the textbox (hidden after a ``scene``). The
presentation clock (``update``) runs only while the top screen is ``in_game`` and the window
has focus (F01 draws nothing while minimized), so a menu or focus loss freezes a transition
and a pause as F05's typing freezes. A ``with`` wait ends in the update after its picture
was drawn to the last frame (``StageView.finished_drawn``), so the last frame is always on
screen before the story goes on; a timed pause after its seconds (the arrival frame adds no
time). ``press`` is the textbox's ``on_idle_advance``: it finishes a transition (the event
follows once the new picture is drawn) or ends a pause at once; the press is consumed, so it
never advances the next line (UI-F09-02).

Effects (§6.7, §6.8): ``Shake`` and ``Flash`` play on the effect clock ``now`` through one
``EffectLayer``; each starts in the frame it arrives in (t = 0 there) and outlives its line.
The stage is drawn at the shake's offset over the uncovered band in ``stage.empty_color``,
then the flash over the whole stage; later screens (the textbox) draw above, untouched. One
``FlashLimiter`` counts every flash and every fade under 1 s (W61 once per statement when it
refuses). Reduced effects (``settings.reduce``, ``[effects] reduce`` OR the player's
setting) give no shake, a soft flash, one flash a second, and calm kinds; they act only on
drawing, so the commands never change. Restore, ``on_enter``, and ``drop_effects`` stop the
effects in the next frame.

Glitches (F28 ``04`` §4.4, §6.4; step 4): ``Glitch`` (``glitch``) goes to one ``GlitchLayer``
on the same effect clock and flash limit. It ticks after the effects and draws tear, static,
and jitter copies between the stage and the flash, so the flash covers them and the textbox
above never glitches. A ``ShowStage`` drops the jitter of sprites that left; restore,
``on_enter``, and ``clear`` empty it; ``drop_effects`` drops its bursts (lasting glitches
stay). While a minigame (F23) is open the stage is drawn without glitches (``07`` G8): its
backdrop and its closing dissolve show the plain stage.

Seams: ``finish_now`` (F15, same as a press), ``drop_effects`` (F15 skip; F16 when reduce
turns on, 07 I-6), ``settings`` (F16 replaces the whole ``EffectSettings``), ``wait_kind``
and ``changes`` (F15, read only), ``wait_id`` (F30's fake crash, read only), ``speed``
(the transition clock's multiplier; F15 I-9 leaves it at 1.0).

Sprite animation (F38 ``SPEC.md`` §5; ``07`` I-8): ``anim`` (``render/spriteanim``'s
``SpriteAnimator``, built by ``install_stage``) learns each shown stage (``show_stage``; a
restored one after ``reset``, so a load or rollback shows plain looks) and ticks in
``update`` only while the clock runs, so under a menu or unfocused the sprites stay as they
are. It holds still (plain looks) under reduced effects and while the view can't change
frames (``StageView.frames_held``: a transition, a title card, a FAST frame, colorshift);
sprites too big to repaint (``oversized``) hold too. Its wishes go to
``StageView.show_frames`` each frame. ``clear`` and ``on_enter`` reset it; ``set_index``
(F39) re-reads the frames.

F30 (``04`` §6.2, G3): a fake crash is a ``StoryWait`` this screen owns, under a
``FakeCrashScreen`` that isn't ``in_game``, so the clock, the effects, and the glitches all
freeze while it shows (a reduced fade shows the frozen picture).
"""

from typing import TYPE_CHECKING, Literal

from engine.render.canvas import Canvas
from engine.render.effects import EffectLayer, EffectSettings, FlashLimiter
from engine.render.glitch import GlitchLayer
from engine.render.stage import StageView
from engine.runtime.commands import WaitDone
from engine.runtime.stage import EMPTY_STAGE
from engine.ui.input import UiEvent
from engine.ui.screen import Screen

if TYPE_CHECKING:
    from engine.render.spriteanim import SpriteAnimator
    from engine.render.stage import FramesOf
    from engine.runtime.commands import Flash, Glitch, Shake, ShowStage, StoryWait
    from engine.runtime.images import ImageIndex

_EPSILON = 1e-9

WaitKind = Literal["stage", "timed", "click"]


class StageScreen(Screen):
    """Draws ``view`` every frame; the stage handlers of the launch and the F09 wait."""

    opaque = True
    in_game = True

    def __init__(self, app: object, view: StageView, *, effects: EffectLayer | None = None,
                 settings: EffectSettings | None = None,
                 glitches: GlitchLayer | None = None,
                 anim: "SpriteAnimator | None" = None) -> None:
        self.app = app
        self.view = view
        self.anim = anim                 # F38: ``install_stage`` builds it from [animation]
        self.speed = 1.0                 # the transition clock's multiplier (F15 I-9: 1.0)
        self.now = 0.0                   # the effect clock: effects and the flash limit
        # ``install_stage`` builds both from config; F16 replaces ``settings`` whole.
        self.effects = effects if effects is not None else EffectLayer(
            empty_color=view.empty_color)
        self.settings = settings if settings is not None else EffectSettings()
        self.limiter = FlashLimiter()    # keeps its history across reduce switches (I-6)
        # F28: ``install_stage`` builds it from ``[effects]``; W182 shares W61's statements.
        self.glitches = glitches if glitches is not None else GlitchLayer(
            refusals=self.effects.refusals)
        self.changes = 0                 # F15: non-restored ShowStages handled (read only)
        self._wait: "StoryWait | None" = None
        self._elapsed = 0.0
        self._fresh = False              # the wait's arrival frame adds no time

    # -- handlers --

    def show_stage(self, cmd: "ShowStage") -> None:
        """The router's ``ShowStage`` handler (F09 C6). A restored stage cancels the
        transition and the wait, then cuts (§6.3)."""
        if cmd.restored:
            self._reset()
        else:
            self.changes += 1
        self.view.show(cmd, reduce=self.settings.reduce, limiter=self.limiter, now=self.now,
                       refusals=self.effects.refusals)
        self.glitches.stage_shown(cmd.stage)
        if self.anim is not None:
            self.anim.set_stage(cmd.stage)         # F38: kept blink timers, a closed mouth

    def start_wait(self, cmd: "StoryWait") -> None:
        """The ``StoryWait`` handler: hold the story until this wait is over (§6.3)."""
        textbox = getattr(self.app, "textbox", None)
        if textbox is not None:
            textbox.clear(hide=cmd.hide_box)
        self._wait = cmd
        self._elapsed = 0.0
        self._fresh = True

    def shake(self, cmd: "Shake") -> None:
        """The ``Shake`` handler: replaces any shake in play, from its own t = 0 in this
        frame (§6.7). Reduced effects draw no offset."""
        self.effects.shake(cmd, self.now, pending=True)

    def flash(self, cmd: "Flash") -> None:
        """The ``Flash`` handler: counted by the limiter (§6.8); admitted, it replaces the
        flash in play from this frame on; refused, it is not drawn (W61 once per line)."""
        self.effects.flash(cmd, self.now, reduce=self.settings.reduce, limiter=self.limiter,
                           pending=True)

    def glitch(self, cmd: "Glitch") -> None:
        """The ``Glitch`` handler (F28 ``04`` §6.4): stops, bursts (from this frame, t = 0),
        and the lasting set, counted once by the flash limit (W182 when a burst is refused;
        a refused lasting change waits); a restored one shows its set at once."""
        self.glitches.apply(cmd, self.now, reduce=self.settings.reduce, limiter=self.limiter)

    def drop_effects(self) -> None:
        """No shake, no flash, and no glitch burst from the next frame (F15 skip; F16 when
        reduce turns on); lasting glitches stay. A transition in play keeps its kind; the
        limiter keeps its history (07 I-6)."""
        self.effects.clear()
        self.glitches.drop_bursts()

    @property
    def wait_kind(self) -> "WaitKind | None":
        """F15: the wait the story holds at: ``"stage"`` (a ``with``), ``"timed"`` (``pause
        <n>``), ``"click"`` (an untimed ``pause``), or None."""
        wait = self._wait
        if wait is None:
            return None
        if wait.for_stage:
            return "stage"
        return "click" if wait.seconds is None else "timed"

    @property
    def wait_id(self) -> int | None:
        """F30 (``04`` §4.3): the id of the wait the story holds at, or None. A fake crash
        shows only while this is still its own wait (a press, restore, or New Game ends
        it)."""
        wait = self._wait
        return None if wait is None else wait.wait_id

    def press(self) -> None:
        """An advance with no line awaiting it (``TextboxScreen.on_idle_advance``): a
        transition finishes (its ``WaitDone`` follows the drawn picture), a pause ends now;
        otherwise nothing."""
        wait = self._wait
        if wait is None:
            return
        if wait.for_stage:
            if self.view.transitioning:
                self.view.finish()
            return
        self._done(wait)

    def finish_now(self) -> None:
        """F15 skip: the same as a press."""
        self.press()

    def clear(self) -> None:
        """The empty stage: before a new game and on the way to the title (F10 I-8)."""
        self._reset()
        self.view.clear()

    def set_index(self, index: "ImageIndex",
                  frames_of: "FramesOf | None" = None) -> None:
        """F39 (PR-F38-12): a rebuilt image index: the stage is resolved again and, given
        the new ``frames_of``, the sprites' frames are read again (plain looks first; the
        line's speaker talks again from its next letter)."""
        self.view.set_index(index)
        anim = self.anim
        if frames_of is not None:
            self.view.frames_of = frames_of
            if anim is not None:
                anim.frames_of = frames_of
        if anim is not None:
            anim.set_stage(EMPTY_STAGE)          # forget the old frames, keep the line
            anim.set_stage(self.view.stage)

    def _reset(self) -> None:
        self.view.cancel()
        self.effects.clear()
        self.glitches.clear()
        self._wait = None
        if self.anim is not None:
            self.anim.reset()                      # F38: plain looks, no line talks

    def _done(self, wait: "StoryWait") -> None:
        self._wait = None
        story = getattr(self.app, "story", None)
        if story is not None:
            story.post(WaitDone(wait.wait_id))

    # -- Screen --

    def on_enter(self) -> None:
        self._reset()                              # a new game, the way back from the title

    def handle_event(self, event: UiEvent) -> bool:
        return False                               # the stage takes no input (03 Interaction)

    def _clock_runs(self) -> bool:
        screens = getattr(self.app, "screens", None)
        top = screens.top if screens is not None else self
        return (top is None or bool(top.in_game)) and bool(getattr(self.app, "focused", True))

    def update(self, dt: float, *, is_top: bool) -> None:
        self.view.update()
        if not self._clock_runs():
            return                                 # frozen under a menu or unfocused
        self.now += dt
        self.effects.tick(self.now)
        self.glitches.tick(self.now, reduce=self.settings.reduce)
        # F28 colorshift: the view's picture filter (a no-op unless it changed; none under a
        # minigame, 07 G8).
        self.view.set_filter(None if self._minigame_open()
                             else self.glitches.filter(self.settings.reduce))
        self.view.advance(dt * self.speed)
        self._animate(dt)
        wait = self._wait
        if wait is None:
            return
        if self._fresh:
            self._fresh = False
        else:
            self._elapsed += dt
        if wait.for_stage:
            if self.view.finished_drawn:
                self._done(wait)
        elif wait.seconds is not None and self._elapsed >= wait.seconds - _EPSILON:
            self._done(wait)

    def _animate(self, dt: float) -> None:
        """F38: the animator's frame, then its wishes to the view (holds: module
        docstring)."""
        anim = self.anim
        if anim is None:
            return
        view = self.view
        anim.tick(dt, still=self.settings.reduce or view.frames_held, held=view.oversized)
        view.show_frames(anim.wanted())

    def draw(self, canvas: Canvas) -> None:
        """The stage at the shake's offset (device pixels, over the uncovered band), its
        glitches (F28), then the flash over the whole stage (§6.7)."""
        effects = self.effects
        offset = (0, 0)
        if effects.active:
            ux, uy = effects.offset_units(self.now, reduce=self.settings.reduce)
            if ux or uy:
                offset = canvas.px(ux, uy)       # canvas units → device pixels
                surface = canvas.surface
                assert surface is not None, "Canvas.bind() has not been called"
                effects.draw_band(surface, offset)
        self.view.draw(canvas, offset)
        glitches = self.glitches
        if glitches.active and not self._minigame_open():
            glitches.draw(canvas, self.view, self.now, offset, reduce=self.settings.reduce)
        if effects.active:
            effects.draw_flash(canvas, self.now)

    def _minigame_open(self) -> bool:
        """F23: a minigame session is open (its pictures of the stage show no glitch, G8)."""
        host = getattr(self.app, "minigame_host", None)
        return host is not None and getattr(host, "session", None) is not None


__all__ = ["EffectSettings", "StageScreen", "WaitKind"]
