"""``CheckRollScreen``: a checked choice's roll on screen (F59, proposal I-05 "a short dice
roll, then the branch").

Why this module exists: the runtime holds the story on a ``CheckRolled`` wait right after a
checked pick; the player should see the dice that decided it, so failure reads as part of
the story rather than a hidden coin flip. The screen draws one small card over the stage
and under nothing else: two dice tumbling, landing on the rolled faces, then the sum
against the difficulty and the result word.

- **Timing** (``roll_frame``, pure): the faces change every ``FACE_STEP_S`` with a small
  bounce until ``LAND_S``, then show the rolled faces; the total and the result appear at
  ``LAND_S``. The story's wait (``ROLL_S`` in ``runtime/menu.py``) ends the screen: a press
  (the textbox's idle advance → ``StageScreen.press``), skip, a restore or New Game all end
  the stage's wait, and the screen removes itself on its next update. Under Reduce motion
  (``reduce``) it shows the landed dice and the result at once, with no bounce. The clock
  only runs while the screen is on top and the window has focus, as the stage's does.
- **Input**: none. Every event goes down to the textbox, whose idle advance ends the wait,
  so a click, Space or Enter skips the roll and Esc still opens the game menu.
- **Colors** (``roll_colors``): the choice buttons' tokens, so all 28 color schemes, a
  ``[style.*]`` look and imported palettes style it: the card is ``choice.fill_color`` at
  ``max(choice.fill_opacity, 0.9)`` with a ``choice.marker.fill_color`` border; the dice are
  ``choice.fill_color`` with marker outlines and pips; text is ``choice.text_color``;
  "Success" is the marker color, "Failure" the text color (a failure is part of the story,
  not an error). Text on the fill is W67's ``choice.text_color`` pair; the marker on the
  fill is the pair F59's badge already relies on (≥ 4.47:1 in every scheme).
- **Text** (``title_text``, ``sum_text``, ``result_text``): "Empathy check", "Dice 9 +
  Empathy 3 = 12 vs 10", "Success" (a double six or one says so). English, as the badge.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.constants import CANVAS_SIZE
from engine.render.frames import FrameSpec
from engine.render.text import FontSpec
from engine.ui.focus import Box
from engine.ui.screen import Screen, ScreenStack

if TYPE_CHECKING:
    from engine.core.config_schema import ChoiceTheme
    from engine.render.canvas import Canvas
    from engine.render.textlayout import FaceSet
    from engine.runtime.commands import CheckRolled
    from engine.ui.paint import Painter

RGB = tuple[int, int, int]
CANVAS_W, CANVAS_H = CANVAS_SIZE

LAND_S: Final = 0.6                 # the dice tumble until here, then show the roll
FACE_STEP_S: Final = 0.075          # a tumbling die shows a new face this often
BOUNCE: Final = 14.0                # the tumble's highest lift, canvas units
DIE: Final = 64.0                   # a die's side, canvas units (× text scale, capped)
DIE_GAP: Final = 24.0
CARD_W: Final = 400.0
CARD_PAD: Final = 18.0
CARD_BORDER: Final = 3
CARD_RADIUS: Final = 14
DIE_BORDER: Final = 3
CARD_OPACITY_MIN: Final = 0.9
TITLE_SIZE: Final = 22
SUM_SIZE: Final = 20
RESULT_SIZE: Final = 30
SCALE_MAX: Final = 1.5
# Pip centers per face on a 3 × 3 grid (0, 1, 2 across and down).
PIPS: Final = {1: ((1, 1),), 2: ((0, 0), (2, 2)), 3: ((0, 0), (1, 1), (2, 2)),
               4: ((0, 0), (2, 0), (0, 2), (2, 2)),
               5: ((0, 0), (2, 0), (1, 1), (0, 2), (2, 2)),
               6: ((0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2))}


@dataclass(frozen=True, slots=True)
class RollColors:
    fill: RGB
    opacity: float
    border: RGB                     # the marker: card border, die outline and pips
    text: RGB


def roll_colors(theme: "ChoiceTheme") -> RollColors:
    return RollColors(theme.fill_color, max(theme.fill_opacity, CARD_OPACITY_MIN),
                      theme.marker.fill_color, theme.text_color)


@dataclass(frozen=True, slots=True)
class RollFrame:
    """What the card shows ``t`` seconds in: each die's face and lift, and whether the
    roll has landed (the total and the result show then)."""

    faces: tuple[int, int]
    lifts: tuple[float, float]
    landed: bool


def tumble_face(seed: int, step: int, die: int) -> int:
    """A tumbling die's face at ``step``: varied, never the same twice in a row, and the
    same every time for the same roll (no randomness, so a test or a screenshot repeats)."""
    face = (seed * 7 + step * (3 + die) + die * 4) % 6 + 1
    previous = (seed * 7 + (step - 1) * (3 + die) + die * 4) % 6 + 1
    return face % 6 + 1 if step and face == previous else face


def roll_frame(cmd: "CheckRolled", t: float, *, reduce: bool) -> RollFrame:
    if reduce or t >= LAND_S:
        return RollFrame(cmd.dice, (0.0, 0.0), True)
    step = int(t / FACE_STEP_S)
    left = 1.0 - t / LAND_S                        # the bounces shrink as the dice settle
    lifts = tuple(BOUNCE * left * abs(_wave(t, die)) for die in (0, 1))
    return RollFrame((tumble_face(cmd.wait_id, step, 0), tumble_face(cmd.wait_id, step, 1)),
                     lifts, False)                 # type: ignore[arg-type]


def _wave(t: float, die: int) -> float:
    return math.sin((t * 3.0 + die * 0.35) * math.pi)


def title_text(cmd: "CheckRolled") -> str:
    return f"{cmd.meter} check"


def sum_text(cmd: "CheckRolled", landed: bool) -> str:
    """``Dice 9 + Empathy 3 = 12 vs 10`` once landed; ``Needs 10`` while tumbling."""
    if not landed:
        return f"Needs {cmd.difficulty}"
    a, b = cmd.dice
    sign = "-" if cmd.value < 0 else "+"
    return (f"Dice {a + b} {sign} {cmd.meter} {abs(cmd.value)} = {a + b + cmd.value} "
            f"vs {cmd.difficulty}")


def result_text(cmd: "CheckRolled") -> str:
    word = "Success" if cmd.ok else "Failure"
    a, b = cmd.dice
    if a == b and a in (1, 6):
        word += f" (double {'six' if a == 6 else 'one'})"
    return word


class CheckRollScreen(Screen):
    """The roll card for ``cmd`` while ``waiting()`` (the stage still holds its wait).
    ``theme``/``faces``: the choice theme and faces now; ``reduce``: Reduce motion (read
    each frame); ``top``: the say window's top (the card centers above it; None: the
    canvas middle); ``text_scale``: F16's text scale; ``focused``: the window has focus."""

    opaque = False
    in_game = True

    def __init__(self, cmd: "CheckRolled", *, theme: "ChoiceTheme", faces: "FaceSet",
                 painter: "Painter", stack: ScreenStack, waiting: Callable[[], bool],
                 reduce: Callable[[], bool], top: Callable[[], float | None] = lambda: None,
                 text_scale: Callable[[], float] = lambda: 1.0,
                 focused: Callable[[], bool] = lambda: True) -> None:
        self.cmd = cmd
        self.theme = theme
        self.faces = faces
        self.painter = painter
        self._stack = stack
        self._waiting = waiting
        self._reduce = reduce
        self._top = top
        self._text_scale = text_scale
        self._focused = focused
        self.elapsed = 0.0

    # -- state --

    def frame(self) -> RollFrame:
        return roll_frame(self.cmd, self.elapsed, reduce=bool(self._reduce()))

    def card(self) -> Box:
        """The card's box (canvas units): ``CARD_W`` wide, centered across, and centered
        in the space above the say window."""
        scale = self._scale()
        h = (2 * CARD_PAD + TITLE_SIZE * scale * 1.4 + DIE * scale + 2 * BOUNCE
             + SUM_SIZE * scale * 1.4 + RESULT_SIZE * scale * 1.4)
        w = max(CARD_W, 2 * DIE * scale + DIE_GAP + 2 * CARD_PAD)
        top = self._top()
        space = float(CANVAS_H) if top is None else max(h + 48.0, float(top))
        return Box((CANVAS_W - w) / 2, max(24.0, (space - h) / 2), w, h)

    def _scale(self) -> float:
        return max(1.0, min(SCALE_MAX, float(self._text_scale())))

    # -- Screen --

    def handle_event(self, event) -> bool:
        return False                    # the textbox's idle advance ends the wait

    def update(self, dt: float, *, is_top: bool) -> None:
        if not self._waiting():
            self._stack.remove(self)    # a press, skip, a restore, New Game
            return
        if is_top and self._focused():
            self.elapsed += max(0.0, dt)

    def draw(self, canvas: "Canvas") -> None:
        if not self._waiting():
            return
        colors = roll_colors(self.theme)
        frame = self.frame()
        scale = self._scale()
        card = self.card()
        painter = self.painter
        painter.bind(canvas)
        painter.shape(card, FrameSpec(colors.fill, colors.opacity, colors.border, CARD_BORDER,
                                      CARD_RADIUS))
        cx = card.x + card.w / 2
        y = card.y + CARD_PAD
        canvas.draw_text(title_text(self.cmd), self._font(TITLE_SIZE * scale), colors.text,
                         (cx, y), anchor="midtop")
        y += TITLE_SIZE * scale * 1.4 + BOUNCE
        side = DIE * scale
        left = cx - side - DIE_GAP / 2
        for die, (face, lift) in enumerate(zip(frame.faces, frame.lifts)):
            box = Box(left + die * (side + DIE_GAP), y - lift, side, side)
            self._die(box, face, colors)
        y += side + BOUNCE * 0.5
        canvas.draw_text(sum_text(self.cmd, frame.landed), self._font(SUM_SIZE * scale),
                         colors.text, (cx, y), anchor="midtop")
        y += SUM_SIZE * scale * 1.4
        if frame.landed:
            canvas.draw_text(result_text(self.cmd), self._font(RESULT_SIZE * scale, bold=True),
                             colors.border if self.cmd.ok else colors.text, (cx, y),
                             anchor="midtop")

    def _die(self, box: Box, face: int, colors: RollColors) -> None:
        painter = self.painter
        painter.shape(box, FrameSpec(colors.fill, 1.0, colors.border, DIE_BORDER,
                                     round(box.w * 0.18)))
        pip = box.w * 0.17
        step = box.w * 0.27
        for gx, gy in PIPS[face]:
            x = box.x + box.w / 2 + (gx - 1) * step - pip / 2
            y = box.y + box.h / 2 + (gy - 1) * step - pip / 2
            painter.ellipse(Box(x, y, pip, pip), colors.border)

    def _font(self, size: float, *, bold: bool = False) -> FontSpec:
        face = self.faces.for_style(bold, False)
        return FontSpec(face.ref, max(1, round(size)), face.bundled, face.synth)


__all__ = ["CheckRollScreen", "FACE_STEP_S", "LAND_S", "RollColors", "RollFrame", "result_text",
           "roll_colors", "roll_frame", "sum_text", "title_text", "tumble_face"]
