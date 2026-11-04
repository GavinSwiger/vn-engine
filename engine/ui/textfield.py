"""``TextField``: F52's one-line text widget, its letter cell and its bare form (P4).

Why this module exists: a name question (``ask_text``), F55's coded note and F56's terminal
all need typed text in an F10 screen or a minigame's ``ctx.scope``, with IME, paste, limits
and a gamepad keyboard. The editing rules are ``ui.textedit.EditModel``'s; this widget adds
what an F10 widget has (focus, mouse, looks, drawing) and what text needs (01 §6.1):

- **Input.** ``on_text`` takes ``TEXTINPUT`` (insert at the caret) and ``TEXTEDITING`` (the
  IME's composition, shown underlined at the caret). Key codes never add text. Editing keys
  arrive from ``ui.textrouting`` as ``backspace``/``delete``/``on_nav``; ``submit`` is Enter.
  ``composing`` stays True until the frame ends after the commit that ended a composition
  (04 §4.1's latch, for the macOS and IBus order); ``tick`` ends it.
- **Services** (07 I-3): the field holds none. The router passes the clipboard's text to
  ``paste``; the screen that owns it sets ``word_for`` (the notes' words) when it routes to
  it. ``ime_rect`` is the caret's box for ``app/textinput``.
- **Looks** (01 §6.1, §6.4): the ``text_entry`` paint area. A box (normal, focused with F10's
  fill, border and marker, or disabled), its text clipped and scrolled so the caret stays in
  view, a 2-wide caret blinking 500 ms on and off (steady under reduce motion, shown at once
  after each edit), the composition underlined, an "n/max" counter when ``max_length`` ≤ 60,
  the keyboard icon (mouse only), the placeholder while empty, "•" per grapheme with
  ``mask``, and a 2-second note tag under the box. ``cell=True`` is a square letter cell
  (underlined at rest, bold with no underline when disabled); ``bare=True`` has no box (F56).
- ``plan(...)`` works out what a frame shows (tested as data); ``draw`` paints it.

Delta (build notes): a boxed field's text starts 32 inside the left edge (F10's side
padding), not 16, so the focus marker (x + 12 to x + 24) never covers the first letter.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pygame

from engine.render.frames import FrameSpec
from engine.render.text import Face, FontSpec, Synth, text_width
from engine.ui.focus import Box
from engine.ui.nav import Nav
from engine.ui.paint import frame_state
from engine.ui.textedit import EditModel, Note
from engine.ui.textgeom import (
    BLINK_S,
    CARET_W,
    COUNTER_MAX_LENGTH,
    NOTE_GAP,
    NOTE_MS,
    UNDERLINE,
    UNDERLINE_GAP,
    caret_at,
    counter_size,
    icon_box,
    scroll_x,
    text_view,
)
from engine.ui.widgets import Look, MouseKind, Widget

if TYPE_CHECKING:
    from engine.ui.paint import Painter

RGB = tuple[int, int, int]
AREA: Final = "text_entry"
BOX_TEXT_INSET: Final = 32              # the delta above
NOTE_PAD_X: Final = 12
NOTE_PAD_Y: Final = 4
DEFAULT_WORDS: Final = {Note.FULL.value: "That's as long as it can be.",
                        Note.REFUSED.value: "That character can't be used here."}
_EMPTY = Box(0, 0, 0, 0)


def _default_word(key: str) -> str:
    return DEFAULT_WORDS.get(key, key)


@dataclass(frozen=True)
class FieldPlan:
    """What one frame of a field shows (canvas units; ``text`` as drawn, masked or not)."""
    frame: str | None                # the paint state of the box, or None (bare, cell at rest)
    marker: bool
    text: str                        # committed text before + composition + after, as drawn
    text_x: float                    # where ``text`` starts (after the scroll)
    placeholder: str | None
    composition: tuple[float, float] | None     # its x range, underlined
    caret: Box | None
    underline: Box | None            # bare field focused, cell at rest
    counter: str | None
    icon: Box | None
    note: str | None
    clip: tuple[float, float]        # the text's x range
    bold: bool = False


class TextField(Widget):
    """One line of typed text (module docstring). ``on_change(text)`` after each edit by the
    player; ``on_submit(text)`` on Enter or the keyboard's Done. ``last_edit`` names the
    last player edit (``"type"``, ``"paste"``, ``"delete"``, ``"turn"``, ``"move"``)."""

    takes_text = True

    def __init__(self, *, text: str = "", max_length: int = 40, allowed: str = "any",
                 case: str | None = None, mask: bool = False, placeholder: str = "",
                 cell: bool = False, bare: bool = False, keep_keyboard: bool = False,
                 on_change: Callable[[str], object] | None = None,
                 on_submit: Callable[[str], object] | None = None,
                 enabled: Callable[[], bool] | None = None, box: Box = _EMPTY,
                 focusable: bool = True, font: FontSpec | None = None,
                 text_size: int | None = None, text_color: RGB | None = None,
                 caret_color: RGB | None = None) -> None:
        super().__init__(enabled=enabled, box=box, focusable=focusable)
        self.model = EditModel(text=text, max_length=max_length, allowed=allowed, case=case,
                               cell=cell)
        self.mask = bool(mask)
        self.placeholder = str(placeholder)
        self.cell = bool(cell)
        self.bare = bool(bare) and not self.cell
        self.keep_keyboard = bool(keep_keyboard)
        self.on_change = on_change
        self.on_submit = on_submit
        self.font = font
        self.text_size = text_size
        self.text_color = text_color
        self.caret_color = caret_color
        self.word_for: Callable[[str], str] = _default_word
        self.last_edit: str | None = None
        self.note: Note | None = None
        self.note_text: str | None = None          # show_note's own words
        self.note_left = 0.0
        self._latch = False
        self._blink = 0.0
        self._steady = False
        self._scroll = 0.0
        self._caret_x: float | None = None
        self._bounds: list[float] = []
        self._kb_request = False

    # -- reading --

    @property
    def text(self) -> str:
        return self.model.text

    @property
    def max_length(self) -> int:
        return self.model.max_length

    @property
    def allowed(self):
        return self.model.allowed

    @property
    def case(self) -> str | None:
        return self.model.case

    @property
    def composing(self) -> bool:
        """True while the IME composes, and until the frame ends after its commit."""
        return self.model.composing or self._latch

    def has_icon(self) -> bool:
        return not self.cell and not self.bare

    # -- the program's calls --

    def set_text(self, text: str) -> None:
        """Replace the text (no ``on_change``); the caret goes to the end."""
        self.model.set_text(str(text))
        self._edited(None)

    def submit(self) -> None:
        if self.enabled() and self.on_submit is not None:
            self.on_submit(self.text)

    # -- the player's edits (router and keyboard) --

    def on_text(self, event: object) -> bool:
        raw = getattr(event, "raw", event)
        kind = getattr(raw, "type", None)
        if not self.enabled():
            return kind in (pygame.TEXTINPUT, pygame.TEXTEDITING)
        if kind == pygame.TEXTINPUT:
            was = self.model.composing
            self.type_text(str(getattr(raw, "text", "")))
            if was:
                self._latch = True
            return True
        if kind == pygame.TEXTEDITING:
            was = self.model.composing
            self.model.compose(str(getattr(raw, "text", "")))
            if was and not self.model.composing:
                self._latch = True
            self._blink = 0.0
            return True
        return False

    def type_text(self, text: str) -> None:
        """Typed (or keyboard-key) text at the caret."""
        before = self.text
        note = self.model.insert(text)
        self._show(note)
        self._edited("type", before)

    def paste(self, text: str) -> bool:
        """The clipboard's text (the router read it on the paste key)."""
        if not self.enabled():
            return False
        before = self.text
        self._show(self.model.paste(str(text)))
        self._edited("paste", before)
        return True

    def backspace(self) -> bool:
        before = self.text
        changed = self.enabled() and self.model.backspace()
        self._edited("delete", before)
        return bool(changed)

    def delete(self) -> bool:
        before = self.text
        changed = self.enabled() and self.model.delete()
        self._edited("delete", before)
        return bool(changed)

    def move(self, step: int) -> bool:
        moved = self.model.move(step)
        self._blink = 0.0
        return moved

    def text_lost(self) -> None:
        """Focus or text input left this field: the composition is dropped."""
        self.model.drop_composition()
        self._latch = False

    def show_note(self, text: str) -> None:
        """Show the caller's own note under the field for 2 seconds (``ask_text``'s
        "Type something first.")."""
        self.note, self.note_text = None, str(text)
        self.note_left = NOTE_MS / 1000.0

    def _show(self, note: Note | None) -> None:
        if note is not None:
            self.note, self.note_text = note, None
            self.note_left = NOTE_MS / 1000.0

    def _edited(self, kind: str | None, before: str | None = None) -> None:
        self._blink = 0.0
        if kind is None:
            return
        self.last_edit = kind
        if before is not None and before != self.text and self.on_change is not None:
            self.on_change(self.text)

    # -- F10 widget --

    def on_nav(self, d: Nav) -> bool:
        if not self.enabled():
            return False
        if self.cell:
            if d in (Nav.UP, Nav.DOWN):
                before = self.text
                self.model.turn(-1 if d is Nav.UP else 1)
                self._edited("turn", before)
                return True
            return False
        if d is Nav.LEFT:
            self.move(-1)
        elif d is Nav.RIGHT:
            self.move(1)
        elif d is Nav.HOME:
            self.model.home()
            self._blink = 0.0
        elif d is Nav.END:
            self.model.end()
            self._blink = 0.0
        else:
            return False
        self.last_edit = "move"
        return True

    def activate(self) -> None:
        if not self.cell:
            self.submit()

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        return False                       # a click never submits

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if kind != "down" or not self.enabled():
            return False
        if self.has_icon() and icon_box(self.box).contains(pos):
            self._kb_request = True
            return True
        if self._bounds and not self.cell:
            self.model.set_caret(caret_at(pos[0], self._bounds))
            self._blink = 0.0
        return True

    def take_keyboard_request(self) -> bool:
        """True once after a click on the keyboard icon."""
        asked, self._kb_request = self._kb_request, False
        return asked

    def ime_rect(self) -> Box:
        """The IME candidate window's anchor: the caret (2 wide, the field's height)."""
        x = self._caret_x if self._caret_x is not None else self.box.x
        return Box(x, self.box.y, CARET_W, self.box.h)

    def tick(self, dt: float, reduce_motion: bool = False) -> None:
        """Once per frame: the caret's blink, the note's time, the end of the latch."""
        self._latch = False
        self._steady = bool(reduce_motion)
        self._blink += max(0.0, dt)
        if self.note is not None or self.note_text is not None:
            self.note_left -= max(0.0, dt)
            if self.note_left <= 1e-9:
                self.note = self.note_text = None

    def caret_on(self) -> bool:
        """The blink: on for 500 ms, off for 500 ms, from the last edit; always under reduce
        motion."""
        return self._steady or (self._blink % (2 * BLINK_S)) < BLINK_S - 1e-9

    # -- drawing --

    def _font(self, p: "Painter", state: str) -> FontSpec:
        style = p.style(AREA, state)
        base = self.font if self.font is not None else style.font
        size = p.scaled_size(self.text_size if self.text_size is not None else style.font.size)
        return dataclasses.replace(base, size=size)

    def _measure(self, p: "Painter", font: FontSpec) -> Callable[[str], float]:
        canvas = p.canvas

        def measure(text: str) -> float:
            return float(text_width(canvas.font_handle(font, font.size).font, text))
        return measure

    def plan(self, p: "Painter", look: Look, *, box: Box | None = None,
             echo: bool = False) -> FieldPlan:
        """What this frame shows in ``box`` (default ``self.box``); ``echo`` is the keyboard's
        echo row (text, caret, composition and counter; no frame, icon or note)."""
        box = box if box is not None else self.box
        state = frame_state(look)
        font = self._font(p, state)
        measure = self._measure(p, font)
        focused = look.state in ("focused", "pressed") or echo
        enabled = look.state != "disabled"
        before, comp, after = self.model.display(mask=self.mask)
        counter = None
        if not self.cell and not self.bare and self.max_length <= COUNTER_MAX_LENGTH:
            counter = f"{self.model.length}/{self.max_length}"
        icon = icon_box(box) if self.has_icon() and not echo else None
        counter_w = 0.0
        if counter is not None:
            counter_font = dataclasses.replace(font, size=counter_size(font.size))
            counter_w = float(text_width(p.canvas.font_handle(counter_font,
                                                              counter_font.size).font, counter))
        if self.cell:
            lo, hi = box.x, box.right
            text = before + comp + after
            w = measure(text)
            text_x = box.x + (box.w - w) / 2
            frame = state if focused else None
            underline = None
            if not focused and enabled:
                underline = Box(box.x, box.bottom - UNDERLINE, box.w, UNDERLINE)
            caret = None
            if focused and enabled and self.caret_on() and not text:
                caret = Box(box.x + box.w / 2 - CARET_W / 2, box.y + (box.h - font.size) / 2,
                            CARET_W, font.size)
            self._caret_x = text_x + w
            return FieldPlan(frame, False, text, text_x, None, None, caret, underline, None,
                             None, self._note_text(echo), (lo, hi), bold=not enabled)
        if self.bare:
            lo, hi = box.x, box.right
        else:
            lo, hi = text_view(box, icon=icon is not None, counter_w=counter_w)
            lo = box.x + BOX_TEXT_INSET if not echo else box.x + 16
            hi = max(lo, hi)
        view_w = hi - lo
        w_before, w_comp, w_after = measure(before), measure(comp), measure(after)
        caret_text_x = w_before + w_comp
        self._scroll = scroll_x(caret_text_x, w_before + w_comp + w_after, view_w,
                                self._scroll)
        text_x = lo - self._scroll
        text = before + comp + after
        self._bounds = self._boundaries(measure, text_x)
        caret = None
        caret_x = text_x + caret_text_x
        self._caret_x = caret_x
        if focused and enabled and self.caret_on():
            caret = Box(min(caret_x, hi - CARET_W), box.y + (box.h - font.size) / 2, CARET_W,
                        font.size)
        composition = (text_x + w_before, text_x + w_before + w_comp) if comp else None
        placeholder = self.placeholder if (not text and self.placeholder) else None
        if self.bare:
            frame = None
            underline = Box(box.x, box.bottom - UNDERLINE, box.w, UNDERLINE) \
                if focused and enabled else None
        else:
            frame = None if echo else state
            underline = None
        return FieldPlan(frame, not self.bare and not echo, text, text_x, placeholder,
                         composition, caret, underline, counter, icon, self._note_text(echo),
                         (lo, hi))

    def _note_text(self, echo: bool) -> str | None:
        if echo:
            return None
        if self.note_text is not None:
            return self.note_text
        return None if self.note is None else self.word_for(self.note.value)

    def _boundaries(self, measure: Callable[[str], float], x0: float) -> list[float]:
        """The x of each committed grapheme boundary (for a click)."""
        out = [x0]
        acc = ""
        for g in self.model.graphemes():
            acc += "•" if self.mask else g
            out.append(x0 + measure(acc))
        return out

    def draw(self, p: "Painter", look: Look) -> None:
        self._paint(p, look, self.box, echo=False)

    def draw_echo(self, p: "Painter", box: Box) -> None:
        """The keyboard's echo row: this field's text, caret, composition and counter."""
        self._paint(p, Look("focused"), box, echo=True)

    def _paint(self, p: "Painter", look: Look, box: Box, *, echo: bool) -> None:
        plan = self.plan(p, look, box=box, echo=echo)
        state = frame_state(look)
        style = p.style(AREA, state)
        font = self._font(p, state)
        if plan.bold:
            font = dataclasses.replace(font, bundled=Face.BOLD,
                                       synth=Synth.BOLD if font.ref is not None else Synth.NONE)
        color = self.text_color if self.text_color is not None else style.text_color
        caret_color = self.caret_color if self.caret_color is not None \
            else style.color("caret", style.marker_color)
        placeholder_color = style.color("placeholder", color)
        border_color = style.color("border", color)
        if plan.frame is not None:
            p.widget_frame(box, AREA, look, marker=plan.marker)
        canvas = p.canvas
        cy = box.y + box.h / 2
        lo, hi = plan.clip
        surface = canvas.surface
        if surface is not None:
            previous = surface.get_clip()
            surface.set_clip(previous.clip(canvas.rect_to_px((lo, box.y, max(0.0, hi - lo),
                                                              box.h))))
        try:
            if plan.placeholder is not None and not echo:
                canvas.draw_text(plan.placeholder, font, placeholder_color, (plan.text_x, cy),
                                 anchor="midleft")
            elif plan.text:
                canvas.draw_text(plan.text, font, color, (plan.text_x, cy), anchor="midleft")
            if plan.composition is not None:
                handle = canvas.font_handle(font, font.size).font
                baseline = cy - handle.get_height() / 2 + handle.get_ascent()
                x0, x1 = plan.composition
                p.rect(Box(x0, baseline + UNDERLINE_GAP, max(1.0, x1 - x0), UNDERLINE), color)
            if plan.caret is not None:
                p.rect(plan.caret, caret_color)
        finally:
            if surface is not None:
                surface.set_clip(previous)
        if plan.underline is not None:
            p.rect(plan.underline, caret_color if self.bare else border_color)
        if plan.counter is not None:
            counter_font = dataclasses.replace(font, size=counter_size(font.size))
            right = (plan.icon.x - 8) if plan.icon is not None else box.right - 16
            canvas.draw_text(plan.counter, counter_font, placeholder_color, (right, cy),
                             anchor="midright")
        if plan.icon is not None:
            self._icon(p, plan.icon, color)
        if plan.note is not None:
            self._note(p, plan.note, box)

    @staticmethod
    def _icon(p: "Painter", box: Box, color: RGB) -> None:
        """The keyboard icon: a rounded outline, two rows of three dots, and a bar."""
        p.shape(box, FrameSpec(color, 0.0, color, 2, 4))
        for row in range(2):
            for col in range(3):
                p.rect(Box(box.x + 7 + col * 8, box.y + 5 + row * 6, 3, 3), color)
        p.rect(Box(box.x + 9, box.y + 17, 14, 2), color)

    @staticmethod
    def _note(p: "Painter", text: str, box: Box) -> None:
        style = p.style("panel")
        size = p.scaled_size(style.font.size)
        font = dataclasses.replace(style.font, size=size)
        w = float(text_width(p.canvas.font_handle(font, size).font, text))
        h = size * 1.4 + 2 * NOTE_PAD_Y
        tag = Box(box.x, box.bottom + NOTE_GAP, w + 2 * NOTE_PAD_X, h)
        p.panel(tag)
        p.canvas.draw_text(text, font, style.text_color, (tag.x + NOTE_PAD_X,
                                                          tag.y + h / 2), anchor="midleft")


__all__ = ["AREA", "DEFAULT_WORDS", "FieldPlan", "TextField"]
