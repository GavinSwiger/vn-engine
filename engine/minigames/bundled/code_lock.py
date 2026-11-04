"""Lock (F53): a bundled minigame where the player opens a keypad or a combination dial with a
code from the story. The result is True when it opened, else False.

Every rule is in ``lock_rules``; this module is the session (F53 ``01`` §4.1, ``04`` §3.2):

- **Keypad.** Twelve F10 buttons (1–9, Clear, 0, Enter) form one focus group and Step back
  another. A typed digit (the top row, the number pad, or any key whose text is a digit, for
  AZERTY) and a pressed key button both type a digit; a digit when the display is full is
  ignored. Enter is disabled until the display is full; when a typed key or the gamepad
  fills it, focus moves to Enter. Backspace deletes a digit; right click and gamepad B open
  the game menu.
- **Dial.** One ``Wheel`` per code character (a row group) and Open and Step back (a column
  group). Up/Down (keys, D-pad, stick, a click on ▲/▼, or the mouse wheel over a wheel) turn
  it with wrap; a typed symbol sets the focused wheel and moves right; Enter or A on a wheel
  is Open. Wheels start at 0 or A.
- **States.** Entering; a wrong code (the message says so with the tries left; the keypad
  clears and focus moves from Enter to Clear); opened ("Open!", every button disabled, then
  ``finish(True)`` after 0.7 s); out of tries (``locked_out`` and one Continue →
  ``finish(False)``). Step back is ``finish(False)``.
- **Hint bar.** ``hint_keypad``/``hint_dial``; after ``hint_after`` wrong tries,
  ``hint_prefix`` + the hint.
- **Motion.** A dial turn slides the face for 120 ms; a wrong code shakes the display (or the
  wheels) ±8 units for 0.3 s. Reduce motion makes both cuts.
- **Look.** Every color is an engine token (``panel.*``, ``button.*``); the plugin's tokens
  are sizes and sounds only, so every color scheme applies.
- **W280** (dev): at ``start``, once per text per process (``_WARNED``, at most 100).

Presentation-only: nothing here is saved; a restore starts the lock again (F23).
Imports (AC-F53-01's rule): ``lock_rules``, ``engine.minigames.api``, and F10's widget kit.
"""

import dataclasses
from typing import TYPE_CHECKING, Any, Final

import pygame

from engine.minigames.api import Arg, Minigame, Outcome, PluginEvent
from engine.minigames.bundled import lock_rules as rules
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, pitch, scaled
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import fit_label, frame_state
from engine.ui.widgets import Button, Look, Widget, clipped

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter

OWN: Final = "plugin.code_lock."

# [theme.plugin.code_lock] (01 §4.4): a size and three sounds (none by default).
TOKENS = {
    "display.text_size": rules.DISPLAY_TEXT[0],
    "turn_sound": "",
    "wrong_sound": "",
    "open_sound": "",
}

# [words.plugin.code_lock] (01 §4.5).
WORDS = {
    "title": "Lock",
    "hint_keypad": "Enter the code.",
    "hint_dial": "Turn the wheels to the code, then choose Open.",
    "hint_prefix": "Hint: ",
    "clear": "Clear",
    "enter": "Enter",
    "open": "Open",
    "leave": "Step back",
    "wrong": "Wrong code.",
    "tries_left": "{n} tries left.",
    "try_left": "1 try left.",
    "opened": "Open!",
    "locked_out": "No tries left. The lock stays shut.",
    "continue": "Continue",
}

ENTERING, OPENED, OUT = "entering", "opened", "out"
WARN_MAX: Final = 100
_WARNED: set[str] = set()             # W280 texts logged this process (dev only)
_BLOCKING: Final = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI
_DIGIT_KEYS: Final = {**{getattr(pygame, f"K_{d}"): str(d) for d in range(10)},
                      **{getattr(pygame, f"K_KP{d}"): str(d) for d in range(10)}}
ARROW_W, ARROW_H = 24, 14


def typed_symbol(raw: Any) -> str | None:
    """The digit or letter a ``KEYDOWN`` types (upper case), or None: a digit key (top row or
    number pad), else the key's text when it is one ASCII digit or letter. Ctrl, Alt, Meta and
    the system key make it no symbol."""
    if raw.type != pygame.KEYDOWN or int(getattr(raw, "mod", 0)) & _BLOCKING:
        return None
    digit = _DIGIT_KEYS.get(getattr(raw, "key", -1))
    if digit is not None:
        return digit
    text = getattr(raw, "unicode", "")
    if type(text) is str and len(text) == 1 and text.upper() in rules.DIGITS + rules.LETTERS:
        return text.upper()
    return None


class Wheel(Widget):
    """One dial wheel: ▲ zone, the face, ▼ zone. Up/Down and the zones turn it; the mouse
    wheel over it turns it; Enter or A is Open. A click never "activates" it."""

    repeatable = True

    def __init__(self, game: "CodeLock", index: int) -> None:
        super().__init__(enabled=lambda: game.state == ENTERING)
        self.game = game
        self.index = index

    def on_nav(self, d: Nav) -> bool:
        if d is Nav.UP or d is Nav.DOWN:
            self.game.turn(self.index, 1 if d is Nav.UP else -1)
            return True
        return False

    def on_mouse(self, kind, pos, *, notches: int = 0) -> bool:
        if kind == "wheel" and notches:
            self.game.turn(self.index, int(notches))
            return True
        if kind == "down":
            if pos[1] < self.box.y + rules.WHEEL_ZONE:
                self.game.turn(self.index, 1)
                return True
            if pos[1] >= self.box.bottom - rules.WHEEL_ZONE:
                self.game.turn(self.index, -1)
                return True
        return False

    def accepts_click(self, pos) -> bool:
        return False

    def activate(self) -> None:
        self.game.open()

    def draw(self, p: "Painter", look: Look) -> None:
        self.game.draw_wheel(self, p, look)


class CodeLock(Minigame):
    name = "code_lock"
    title = "Lock"
    api = "1.1"
    over_stage = True
    args = {key: (Arg() if key in rules.REQUIRED else Arg(default=value))
            for key, value in rules.DEFAULTS.items()}
    test_outcome = Outcome(True)
    skipped_outcome = Outcome(True)
    tokens = TOKENS
    words = WORDS

    def check_args(self, args: dict) -> str | None:
        return rules.problem(args)

    # -- the session --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        spec = self.spec = rules.parse(dict(ctx.args))
        self.word = {key: ctx.words.mine(key) for key in WORDS}
        self.symbols = rules.alphabet(spec.kind, spec.code)
        self.state = ENTERING
        self.wrong = 0
        self.message = ""
        self.entered = ""                                     # the keypad's digits
        self.wheels = [self.symbols[0]] * spec.size           # the dial's faces
        self.slides: dict[int, tuple[float, int]] = {}        # wheel → (t, by)
        self.shake_t: float | None = None
        self.open_left = 0.0
        self.done = False
        self.last_kind = InputKind.MOUSE
        settings = ctx.settings
        self.reduce = bool(settings.reduce_motion)
        mine = ctx.theme.mine
        self.display_size = rules.clamp_size(mine("display.text_size"), *rules.DISPLAY_TEXT)
        self.sounds = {key: mine(key) for key in ("turn_sound", "wrong_sound", "open_sound")}
        self.area = ctx.area
        self.lay: Any = None
        self._lay_key: tuple | None = None
        entering = lambda: self.state == ENTERING          # noqa: E731
        self.leave_button = Button(lambda: self.word["leave"], self._leave, enabled=entering)
        self.continue_button = Button(lambda: self.word["continue"], self._continue)
        if spec.kind == "keypad":
            self.keys = [Button((lambda d=d: d), (lambda d=d: self.press_digit(d)),
                                enabled=entering) for d in "123456789"]
            self.clear = Button(lambda: self.word["clear"], self._clear, enabled=entering)
            self.enter = Button(lambda: self.word["enter"], self._enter,
                                enabled=lambda: entering() and self.full)
            self.keys += [self.clear, Button(lambda: "0", lambda: self.press_digit("0"),
                                             enabled=entering), self.enter]
            self.focusables: list[Widget] = list(self.keys)
        else:
            self.wheel_widgets = [Wheel(self, i) for i in range(spec.size)]
            self.open_button = Button(lambda: self.word["open"], self.open, enabled=entering)
            self.focusables = [*self.wheel_widgets, self.open_button]
        self._set_groups()
        ctx.heading(True)
        self._hint()
        if ctx.dev:
            text = rules.w280_text(spec)
            if text is not None and text not in _WARNED and len(_WARNED) < WARN_MAX:
                _WARNED.add(text)
                ctx.log.warning("%s", text, extra={"code": "W280"})

    @property
    def full(self) -> bool:
        return len(self.entered) >= self.spec.size

    def _set_groups(self) -> None:
        scope = self.ctx.scope
        leave = [self.leave_button] if self.spec.leave else []
        if self.state == OUT:
            scope.set_groups([FocusGroup([self.continue_button])])
            scope.set_default(self.continue_button)
        elif self.spec.kind == "keypad":
            scope.set_groups([FocusGroup(list(self.keys)), FocusGroup(leave)])
            scope.set_default(self.keys[0])
        else:
            scope.set_groups([FocusGroup(list(self.wheel_widgets)),
                              FocusGroup([self.open_button, *leave], column=True)])
            scope.set_default(self.wheel_widgets[0])

    def _hint(self) -> None:
        spec = self.spec
        if rules.hint_shown(self.wrong, spec.hint_after, spec.hint):
            self.ctx.hint(self.word["hint_prefix"] + str(spec.hint))
        else:
            self.ctx.hint(self.word["hint_keypad" if spec.kind == "keypad" else "hint_dial"])

    def _sound(self, key: str) -> None:
        if self.sounds.get(key):
            self.ctx.play_ui(OWN + key)

    # -- input --

    def handle_event(self, ev: PluginEvent) -> bool:
        raw = ev.ui.raw
        if raw.type in (pygame.KEYDOWN, pygame.CONTROLLERBUTTONDOWN,
                        pygame.CONTROLLERAXISMOTION):
            self.last_kind = InputKind.KEYS
        elif raw.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
            self.last_kind = InputKind.MOUSE
        if self.state != ENTERING:
            return False
        symbol = typed_symbol(raw)
        if self.spec.kind == "keypad":
            if symbol is not None and symbol in rules.DIGITS:
                self.type_digit(symbol, by_keys=True)
                return True
            if ev.nav is Nav.BACK and raw.type == pygame.KEYDOWN and self.entered:
                self.entered = self.entered[:-1]
                return True
            return False
        if symbol is not None and symbol in self.symbols:
            self.set_focused_wheel(symbol)
            return True
        return False

    # -- the keypad --

    def press_digit(self, digit: str) -> None:
        """A key button's action (click, Enter or A on it)."""
        self.type_digit(digit, by_keys=self.last_kind is InputKind.KEYS)

    def type_digit(self, digit: str, *, by_keys: bool) -> None:
        if self.state != ENTERING or self.full:
            return
        self.entered += digit
        if self.full and by_keys:
            self.ctx.scope.focus(self.enter, InputKind.KEYS)

    def _clear(self) -> None:
        if self.state == ENTERING:
            self.entered = ""

    def _enter(self) -> None:
        if self.state == ENTERING and self.full:
            self._judge(self.entered)

    # -- the dial --

    def turn(self, index: int, by: int) -> None:
        if self.state != ENTERING or by == 0:
            return
        self.wheels[index] = rules.turn(self.symbols, self.wheels[index], by)
        self.slides[index] = (0.0, 1 if by > 0 else -1)
        self._sound("turn_sound")

    def set_focused_wheel(self, symbol: str) -> None:
        """A typed symbol: it sets the focused wheel (wheel 0 when none has focus) and focus
        moves right (to the next wheel, or Open)."""
        scope = self.ctx.scope
        focused = scope.focused
        index = focused.index if isinstance(focused, Wheel) else 0
        if self.wheels[index] != symbol:
            self.wheels[index] = symbol
            self.slides[index] = (0.0, 1)
            self._sound("turn_sound")
        nxt = self.wheel_widgets[index + 1] if index + 1 < len(self.wheel_widgets) \
            else self.open_button
        scope.focus(nxt, InputKind.KEYS)

    def open(self) -> None:
        if self.state == ENTERING and self.spec.kind == "dial":
            self._judge("".join(self.wheels))

    # -- judging and the end --

    def _judge(self, entered: str) -> None:
        spec = self.spec
        if rules.matches(entered, spec.code):
            self.state = OPENED
            self.message = ""
            self.open_left = rules.OPEN_HOLD
            self._sound("open_sound")
            return
        self.wrong += 1
        self.shake_t = 0.0
        self._sound("wrong_sound")
        self.message = rules.wrong_message(self.wrong, spec.tries, self.word.__getitem__)
        scope = self.ctx.scope
        if spec.kind == "keypad":
            had_enter = scope.focused is self.enter
            self.entered = ""
            if had_enter:
                scope.focus(self.clear, InputKind.KEYS, sound=False)
        if rules.locked_out(self.wrong, spec.tries):
            self.state = OUT
            self._set_groups()
        self._hint()

    def _leave(self) -> None:
        if self.state == ENTERING:
            self._finish(False)

    def _continue(self) -> None:
        if self.state == OUT:
            self._finish(False)

    def _finish(self, result: bool) -> None:
        if self.done:
            return
        self.done = True
        self.ctx.finish(result)

    def update(self, dt: float) -> None:
        dt = max(0.0, float(dt))
        if self.shake_t is not None:
            self.shake_t += dt
            if self.shake_t >= rules.SHAKE_S:
                self.shake_t = None
        for index, (t, by) in list(self.slides.items()):
            if t + dt >= rules.SLIDE_S:
                del self.slides[index]
            else:
                self.slides[index] = (t + dt, by)
        if self.state == OPENED and not self.done:
            self.open_left -= dt
            if self.open_left <= rules.EPSILON:
                self._finish(True)

    # -- settings and layout --

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.reduce = bool(s.reduce_motion)
        self._lay_key = None

    def layout(self, area) -> None:
        self.area = area
        self._lay_key = None

    def shake(self) -> float:
        """The display's (or the wheels') sideways offset now; 0 under Reduce motion."""
        if self.reduce or self.shake_t is None:
            return 0.0
        return rules.shake_offset(self.shake_t)

    def slide(self, index: int) -> float:
        """Wheel ``index``'s face offset now; 0 under Reduce motion (a cut)."""
        found = self.slides.get(index)
        if self.reduce or found is None or self.lay is None:
            return 0.0
        return rules.slide_offset(found[0], found[1], self.lay.face_h)

    def settle(self) -> Any:
        """The layout for the current area and text size (recomputed only on a change)."""
        p = self.ctx.painter
        scale = p.text_scale()
        a = self.area
        key = (a.x, a.y, a.w, a.h, scale, self.state == OUT)
        if key == self._lay_key and self.lay is not None:
            return self.lay
        bh = button_height(scale=scale)
        line = pitch(scaled(rules.MESSAGE_TEXT, scale))
        area = (a.x, a.y, a.w, a.h)
        if self.spec.kind == "keypad":
            lay = rules.keypad_layout(area, button_h=bh, message_h=line,
                                      leave=self.spec.leave)
            for w, box in zip(self.keys, lay.keys):
                w.box = Box(*box)
        else:
            lay = rules.dial_layout(area, count=self.spec.size, button_h=bh, message_h=2 * line,
                                    face_pitch=pitch(scaled(rules.FACE_TEXT, scale)),
                                    leave=self.spec.leave)
            for w, box in zip(self.wheel_widgets, lay.wheels):
                w.box = Box(*box)
            self.open_button.box = Box(*lay.open)
        if lay.leave is not None:
            self.leave_button.box = Box(*lay.leave)
        self.continue_button.box = Box(*lay.continue_)
        self.lay, self._lay_key = lay, key
        return lay

    # -- drawing --

    def draw(self, canvas: "Canvas") -> None:
        lay = self.settle()
        p = self.ctx.painter
        p.panel(Box(*lay.panel))
        if self.spec.kind == "keypad":
            self._draw_display(canvas, p, Box(*lay.display).moved(self.shake()))
        self._draw_message(canvas, p, Box(*lay.message))

    def _text(self, canvas: "Canvas", p: "Painter", text: str, box: Box, *, area: str,
              size: int, color: Any, lines: int = 1) -> None:
        style = p.style(area)
        px = p.scaled_size(size)
        font = dataclasses.replace(style.font, size=px)
        if lines == 1:
            fit = fit_label(text, lambda s: canvas.font_handle(style.font, s).font, px, box.w,
                            min_size=min(24, px))
            if fit.text:
                canvas.draw_text(fit.text, dataclasses.replace(style.font, size=fit.size),
                                 color, box.center, anchor="center")
            return
        canvas.draw_text(text, font, color, (box.center[0], box.y), anchor="midtop",
                         max_width=box.w, align="center", max_lines=lines)

    def _draw_display(self, canvas: "Canvas", p: "Painter", box: Box) -> None:
        p.widget_frame(box, "button", Look("normal"), marker=False)
        inner = Box(box.x + 16, box.y, box.w - 32, box.h)
        if self.state == OPENED:
            self._text(canvas, p, self.word["opened"], inner, area="button",
                       size=self.display_size, color=p.style("panel.heading").text_color)
            return
        slots = list(self.entered) + ["_"] * (self.spec.size - len(self.entered))
        self._text(canvas, p, " ".join(slots), inner, area="button", size=self.display_size,
                   color=p.style("button").text_color)

    def _draw_message(self, canvas: "Canvas", p: "Painter", box: Box) -> None:
        if self.state == OPENED and self.spec.kind == "dial":
            text, color = self.word["opened"], p.style("panel.heading").text_color
        else:
            text, color = self.message, p.style("panel").text_color
        if text:
            self._text(canvas, p, text, box, area="panel", size=rules.MESSAGE_TEXT,
                       color=color, lines=2)

    def draw_wheel(self, wheel: Wheel, p: "Painter", look: Look) -> None:
        box = wheel.box.moved(self.shake())
        p.widget_frame(box, "button", look, marker=False)
        color = p.style("button", frame_state(look)).text_color
        zone = rules.WHEEL_ZONE
        cx = box.x + box.w / 2
        p.triangle(Box(cx - ARROW_W / 2, box.y + (zone - ARROW_H) / 2, ARROW_W, ARROW_H), color,
                   direction="up")
        p.triangle(Box(cx - ARROW_W / 2, box.bottom - (zone + ARROW_H) / 2, ARROW_W, ARROW_H),
                   color, direction="down")
        face = Box(box.x, box.y + zone, box.w, box.h - 2 * zone)
        canvas = p.canvas
        style = p.style("button")
        px = p.scaled_size(rules.FACE_TEXT)
        font = dataclasses.replace(style.font, size=px)
        offset = self.slide(wheel.index)
        with clipped(p, face):
            canvas.draw_text(self.wheels[wheel.index], font, color,
                             (face.center[0], face.center[1] + offset), anchor="center")


__all__ = ["CodeLock", "TOKENS", "WORDS", "Wheel", "typed_symbol"]
