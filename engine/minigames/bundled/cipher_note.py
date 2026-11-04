"""Coded note (``cipher_note``, F55): a bundled minigame where a letter is written in a code and
the player works out what each sign stands for.

- **The note** (SPEC §4.1): a ``panel.*`` panel x 24–1000, y 24–622. Each coded character is
  a column: its sign on top (``code.*`` tokens) and an F52 letter cell 4 below
  (``api.TextField(cell=True)``, ``allowed`` the alphabet, upper case). A space is half a
  column; characters outside the alphabet sit plain in the cell row. Lines more than fit
  scroll (wheel, Page keys, bumpers; focus scrolls into view).
- **Guessing** (PR-F55-03): typing or turning a letter sets it on every copy of that sign and
  takes it off any other sign; after typing (not turning) focus goes to the next cell whose
  sign has no letter, wrapping. Backspace or Delete clears the sign. While a cell is focused,
  every cell with its sign shows a bar under it. Revealed letters start solved: bold, no
  underline, never focused or cleared.
- **Shift kind** (PR-F55-06): the cells show decoded letters and aren't focusable; one side
  cell ("A is written as [ ]") sets the decoding.
- **Side column** x 1024–1256: Done (once solved), Hints (with ``hints``), Put away.
  Solving locks the cells, shows ``solved`` and focuses Done; Done unlocks ``tip`` and
  finishes ``True``; Put away asks ``confirm``, and Yes finishes ``False``.
- **Hints** (PR-F55-05): F21's codex view of the tips of ``hints`` the player holds; with
  none, the button reads ``no_hints`` and is disabled.
- **Keys** (§4.2): Left/Right go through the unlocked cells in reading order (past the last,
  the side column; Left from there, the last cell); Up/Down turn (F52); LB/RB and Page
  Up/Down go to the first cell of the previous/next line. Right click and east are F23's
  (the game menu).
- **W270** (dev, once per note): characters the game's fonts can't draw.

Presentation only: a save during the note loads it again unsolved (F23's checkpoint).
Imports: ``cipher_rules``, ``engine.minigames.api``, and F10's public widget kit only.
"""

import dataclasses
from typing import TYPE_CHECKING, Final

import pygame

from engine.minigames.api import (Arg, CodexFilter, Minigame, Outcome, PluginEvent, StoryNames,
                                  TextField)
from engine.minigames.bundled import cipher_rules as rules
from engine.render.text import FontSpec, missing_glyphs
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, pitch
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas

RGB = tuple[int, int, int]

# [theme.plugin.cipher_note] (§4.4): each default names the game token it follows.
TOKENS: Final = {
    "code.text_color": "panel.text_color",
    "code.text_size": "panel.text_size",
    "code_font": "ui.text_font",
    "guess.text_color": "panel.heading.text_color",
}
# [words.plugin.cipher_note] (§4.4), final.
WORDS: Final = {
    "title": "Coded note",
    "hint": "Type the letter each sign stands for, or turn it with Up and Down. Left and "
            "Right move.",
    "hint_shift": "Turn the letter until the note makes sense.",
    "shift_label": "is written as",
    "hints": "Hints",
    "no_hints": "No hints yet",
    "put_away": "Put away",
    "confirm": "Put the note away? It stays coded.",
    "solved": "Solved! The note reads clearly now.",
    "done": "Done",
}
CELL_TEXT: Final = 28                 # F52's cells at [theme.button]'s text size
BAR_H: Final = 4                      # the same-sign bar under a cell
WARNED: set[str] = set()              # W270: once per note (message), per process


def _rgb(value: object) -> RGB | None:
    if isinstance(value, (tuple, list)) and len(value) >= 3 \
            and all(type(c) is int and 0 <= c <= 255 for c in value[:3]):
        return int(value[0]), int(value[1]), int(value[2])
    if type(value) is str and len(value) in (7, 9) and value[0] == "#":
        try:
            return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
        except ValueError:
            return None
    return None


class CipherNote(Minigame):
    name = "cipher_note"
    title = "Coded note"
    api = "1.4"
    args = {"message": Arg(), **{key: Arg(default=value) for key, value in
                                 rules.DEFAULTS.items()}}
    test_outcome = Outcome(True)
    skipped_outcome = Outcome(True)
    tokens = TOKENS
    words = WORDS

    # -- API 1.1 hooks --

    def check_args(self, args: dict) -> str | None:
        return rules.problem(args)

    def check_story(self, args: dict, story: StoryNames) -> str | None:
        return rules.story_problem(args, story)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        return rules.fixed_outcome(args)

    # -- the session --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        args = {**rules.DEFAULTS, **dict(ctx.args)}
        self.args = args
        self.c = rules.cipher(args)
        self.board = rules.Board(self.c, args["revealed"] or "")
        self.shift = self.c.kind == "shift"
        self.word = {key: ctx.words.mine(key) for key in WORDS if key != "title"}
        self.colors = {key: self._color(key) for key in ("code.text_color", "guess.text_color")}
        self.scale = float(ctx.settings.text_scale)
        self.solved = False
        self.finished = False
        self.top_line = 0
        self.mode = "note"
        self.view = None
        self.checked_glyphs = False
        self.last_focus = None
        self.columns: list[rules.Column] = []
        self.cells: list[TextField] = []
        self.cell_sign: dict[int, str] = {}             # id(cell) → its sign
        self.cell_line: dict[int, int] = {}
        alphabet = self.c.alphabet
        for col in rules.note_layout(self.c.message, alphabet, 1.0, 1e9):
            if not col.letter:
                continue
            sign = self.c.sign(col.char)
            fixed = sign in self.board.fixed
            cell = TextField(cell=True, allowed=alphabet, case="upper",
                             text=self.board.guess(sign),
                             text_color=self.colors["guess.text_color"],
                             enabled=(lambda: False) if fixed else self._unlocked,
                             focusable=not self.shift and not fixed)
            cell.on_change = (lambda text, me=cell: self._changed(me, text))
            self.cells.append(cell)
            self.cell_sign[id(cell)] = sign
        self.dial = None
        if self.shift:
            self.dial = TextField(cell=True, allowed=alphabet, case="upper",
                                  enabled=self._unlocked,
                                  on_change=lambda text: self._dialed(text))
        self.done_button = Button(lambda: self.word["done"], self._done,
                                  enabled=lambda: self.solved)
        self.hints_button = Button(self._hints_label, self._open_hints,
                                   enabled=self._has_hints)
        self.put_away = Button(lambda: self.word["put_away"], self._ask_put_away,
                               enabled=lambda: not self.solved)
        self.close_button = Button(lambda: ctx.words.get("return"), self._close_hints)
        ctx.heading(False)
        ctx.hint(self.word["hint_shift" if self.shift else "hint"])
        self._layout()
        self._groups()
        self._check_solved(initial=True)

    def _color(self, key: str) -> RGB:
        found = _rgb(self.ctx.theme.mine(key))
        if found is not None:
            return found
        fallback = _rgb(self.ctx.theme.get(TOKENS[key]))
        return fallback if fallback is not None else (0, 0, 0)

    def _unlocked(self) -> bool:
        return not self.solved

    # -- guessing --

    def _changed(self, cell: TextField, text: str) -> None:
        if self.solved:
            return
        sign = self.cell_sign[id(cell)]
        changed = self.board.put(sign, text) if text else self.board.clear(sign)
        for other in self.cells:
            if self.cell_sign[id(other)] in changed:
                other.set_text(self.board.guess(self.cell_sign[id(other)]))
        if text and cell.last_edit == "type":
            self._focus_next_empty(cell)
        self._check_solved()

    def _focus_next_empty(self, cell: TextField) -> None:
        order = self.cells
        start = order.index(cell)
        for step in range(1, len(order) + 1):
            other = order[(start + step) % len(order)]
            sign = self.cell_sign[id(other)]
            if other.focusable and sign not in self.board.guesses:
                self._focus(other)
                return

    def _dialed(self, text: str) -> None:
        if self.solved:
            return
        self.board.dial = text or None
        for cell in self.cells:
            cell.set_text(self.board.decoded(self.cell_sign[id(cell)]))
        self._check_solved()

    def _check_solved(self, initial: bool = False) -> None:
        if self.solved or not self.board.solved():
            return
        self.solved = True
        self.ctx.hint(self.word["solved"])
        self._groups()
        self._focus(self.done_button)

    def _focus(self, w) -> None:
        self.ctx.scope.focus(w, InputKind.KEYS)
        self._into_view(w)

    # -- the side column --

    def _has_hints(self) -> bool:
        hints = self.args.get("hints")
        if type(hints) is not str:
            return False
        tips = dict(self.ctx.story.tip_categories).get(hints, ())
        return any(self.ctx.codex.has("tip", t) for t in tips)

    def _hints_label(self) -> str:
        return self.word["hints"] if self._has_hints() else self.word["no_hints"]

    def _open_hints(self) -> None:
        hints = self.args.get("hints")
        if self.view is None:
            self.view = self.ctx.codex_view(filter=CodexFilter(kinds=frozenset({"tip"}),
                                                               categories=frozenset({hints})))
        self.mode = "hints"
        self._groups()

    def _close_hints(self) -> None:
        self.mode = "note"
        self._groups()
        self._focus(self.hints_button)

    def _done(self) -> None:
        if self.finished or not self.solved:
            return
        tip = self.args.get("tip")
        if type(tip) is str:
            self.ctx.codex.unlock_tip(tip)
        self.finished = True
        self.ctx.finish(True)

    def _ask_put_away(self) -> None:
        def yes() -> None:
            if not self.finished:
                self.finished = True
                self.ctx.finish(False)
        self.ctx.confirm("confirm", yes)

    # -- layout --

    def _sizes(self) -> tuple[int, int, int]:
        """(code text size, cell side, cell text size) at the player's text size."""
        code = self.ctx.theme.mine("code.text_size")
        if type(code) is not int:
            code = self.ctx.theme.get("panel.text_size")
        code = max(1, round((code if type(code) is int else 28) * self.scale))
        cell_text = max(1, round(CELL_TEXT * self.scale))
        return code, rules.cell_side(cell_text), cell_text

    def _layout(self) -> None:
        code, side, _cell_text = self._sizes()
        x0, y0, w, h = rules.NOTE
        pad = rules.NOTE_PAD
        self.inner = Box(x0 + pad, y0 + pad, w - 2 * pad, h - 2 * pad)
        self.column_w = side + rules.COLUMN_EXTRA
        self.sign_h = pitch(code)
        self.side = side
        self.line_h = self.sign_h + rules.SIGN_GAP + side
        self.lines_shown = rules.visible_lines(self.inner.h, self.line_h)
        self.columns = rules.note_layout(self.c.message, self.c.alphabet, self.column_w,
                                         self.inner.w)
        self.lines = max((c.line for c in self.columns), default=0) + 1
        self.top_line = max(0, min(self.top_line, self.lines - self.lines_shown))
        letters = [c for c in self.columns if c.letter]
        for cell, col in zip(self.cells, letters):
            self.cell_line[id(cell)] = col.line
            cell.box = Box(self.inner.x + col.x + rules.COLUMN_EXTRA / 2,
                           self._line_y(col.line) + self.sign_h + rules.SIGN_GAP, side, side)
        bh = button_height(scale=self.scale)
        y = rules.NOTE[1]
        if self.dial is not None:
            y += pitch(code) + rules.SIDE_GAP
            self.dial.box = Box(rules.SIDE_X, y, side, side)
            y += side + rules.SIDE_GAP
        for button in (self.done_button, self.hints_button, self.put_away):
            button.box = Box(rules.SIDE_X, y, rules.SIDE_W, bh)
            if button is not self.done_button or self.solved:
                y += bh + rules.SIDE_GAP
        self.close_button.box = Box(rules.SIDE_X, rules.NOTE[1], rules.SIDE_W, bh)

    def _line_y(self, line: int) -> float:
        return self.inner.y + (line - self.top_line) * (self.line_h + rules.LINE_GAP)

    def _groups(self) -> None:
        scope = self.ctx.scope
        if self.mode == "hints" and self.view is not None:
            box = Box(*rules.NOTE)
            groups = list(self.view.build(box, self.scale))
            groups.append(FocusGroup([self.close_button]))
            scope.set_groups(groups)
            target = self.view.default_widget() or self.close_button
            scope.set_default(target)
            scope.focus(target, InputKind.KEYS, sound=False)
            return
        self._layout()
        side = [w for w in (self.dial,) if w is not None]
        side += [self.done_button] if self.solved else []
        side += [b for b in (self.hints_button,) if self.args.get("hints") is not None]
        side.append(self.put_away)
        scope.set_groups([FocusGroup(self.cells, clip=self.inner),
                          FocusGroup(side, column=True)])
        first = next((c for c in self.cells if c.focusable and c.enabled()), None)
        default = self.done_button if self.solved else (self.dial or first or self.put_away)
        scope.set_default(default)

    def _into_view(self, w) -> None:
        line = self.cell_line.get(id(w))
        if line is None:
            return
        if line < self.top_line:
            self.top_line = line
        elif line >= self.top_line + self.lines_shown:
            self.top_line = line - self.lines_shown + 1
        self._layout()

    def _scroll(self, lines: int) -> None:
        self.top_line = max(0, min(self.top_line + lines, self.lines - self.lines_shown))
        self._layout()

    def layout(self, area) -> None:
        self._layout()

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.scale = float(s.text_scale)
        self._layout()

    # -- input (§4.2) --

    def _open_cells(self) -> list[TextField]:
        return [c for c in self.cells if c.focusable and c.enabled()]

    def handle_event(self, ev: PluginEvent) -> bool:
        nav = ev.nav
        raw = ev.ui.raw
        scope = self.ctx.scope
        if self.mode == "hints":
            if nav is Nav.BACK:
                self._close_hints()
                return True
            if self.view is not None and nav is not None and self.view.on_nav(nav):
                return True
            return False
        if raw.type == pygame.MOUSEWHEEL:
            pos = ev.ui.canvas_pos
            if pos is not None and Box(*rules.NOTE).contains(pos):
                self._scroll(-int(getattr(raw, "y", 0)))
                return True
            return False
        focused = scope.focused
        cells = self._open_cells()
        if nav in (Nav.LEFT, Nav.RIGHT) and cells:
            if focused in cells:
                i = cells.index(focused) + (1 if nav is Nav.RIGHT else -1)
                if 0 <= i < len(cells):
                    self._focus(cells[i])
                elif i >= len(cells):
                    side = self._side_first()
                    if side is not None:
                        self._focus(side)
                return True
            if focused is not None and nav is Nav.LEFT and focused not in self.cells:
                self._focus(cells[-1])
                return True
        if nav in (Nav.PAGE_UP, Nav.PAGE_DOWN) and cells:
            line = self.cell_line.get(id(focused), self.top_line)
            want = line + (-1 if nav is Nav.PAGE_UP else 1)
            target = next((c for c in cells if self.cell_line[id(c)] == want), None)
            if target is not None:
                self._focus(target)
            else:
                self._scroll(-1 if nav is Nav.PAGE_UP else 1)
            return True
        return False

    def _side_first(self):
        for w in (self.dial, self.done_button if self.solved else None,
                  self.hints_button if self.args.get("hints") is not None else None,
                  self.put_away):
            if w is not None and w.enabled():
                return w
        return None

    def update(self, dt: float) -> None:
        if self.mode == "hints" and self.view is not None:
            self.view.update(dt)
            if self.view.groups_changed:
                self._groups()
            return
        focused = self.ctx.scope.focused                    # focus moved: into view
        if focused is not self.last_focus:
            self.last_focus = focused
            if focused is not None and id(focused) in self.cell_line:
                self._into_view(focused)

    # -- drawing --

    def draw(self, canvas: "Canvas") -> None:
        p = self.ctx.painter
        if not self.checked_glyphs:
            self._check_glyphs(canvas)
        if self.mode == "hints" and self.view is not None:
            p.panel(Box(*rules.NOTE))
            self.view.draw(canvas, p)
            return
        p.panel(Box(*rules.NOTE))
        code_size = self._sizes()[0]
        font = self._code_font(code_size)
        plain_font = self.ctx.font(None, self._sizes()[2])
        color = self.colors["code.text_color"]
        guess = self.colors["guess.text_color"]
        focused = self.ctx.scope.focused
        sign_now = self.cell_sign.get(id(focused)) if focused is not None else None
        surface = canvas.surface
        previous = surface.get_clip() if surface is not None else None
        if surface is not None:
            surface.set_clip(previous.clip(canvas.rect_to_px(
                (self.inner.x, self.inner.y, self.inner.w, self.inner.h))))
        try:
            letter_cells = iter(self.cells)
            for col in self.columns:
                if not self.top_line <= col.line < self.top_line + self.lines_shown:
                    if col.letter:
                        next(letter_cells)
                    continue
                y = self._line_y(col.line)
                x = self.inner.x + col.x + self.column_w / 2
                if col.letter:
                    cell = next(letter_cells)
                    sign = self.cell_sign[id(cell)]
                    canvas.draw_text(sign, font, color, (x, y + self.sign_h / 2),
                                     anchor="center")
                    if sign_now is not None and sign == sign_now:     # the same-sign bar
                        p.rect(Box(cell.box.x, cell.box.bottom + 2, cell.box.w, BAR_H), guess)
                else:
                    canvas.draw_text(col.char, plain_font, color,
                                     (x, y + self.sign_h + rules.SIGN_GAP + self.side / 2),
                                     anchor="center")
        finally:
            if surface is not None:
                surface.set_clip(previous)
        if self.dial is not None:
            label = f"{self.c.alphabet[0]} {self.word['shift_label']}"
            canvas.draw_text(label, self.ctx.font(None, code_size), color,
                             (rules.SIDE_X, rules.NOTE[1]))

    def _code_font(self, size: int) -> FontSpec:
        ref = self.ctx.theme.mine("code_font")
        if type(ref) is str and ref and ref != "ui.text_font":
            return self.ctx.font(ref, size)
        return self.ctx.font(None, size)

    def _check_glyphs(self, canvas: "Canvas") -> None:
        """W270 (dev): once per note, the characters the fonts can't draw."""
        self.checked_glyphs = True
        if not self.ctx.dev:
            return
        size = self._sizes()[0]
        font = self._code_font(size)
        handle = canvas.font_handle(dataclasses.replace(font, size=size), size).font
        chars = []
        for ch in rules.encode(self.c) + self.c.alphabet:
            if not ch.isspace() and ch not in chars:
                chars.append(ch)
        missing = missing_glyphs(handle, "".join(chars))
        key = self.c.message
        if missing and key not in WARNED:
            WARNED.add(key)
            self.ctx.log.warning("%s", rules.w270_text(missing), extra={"code": "W270"})


__all__ = ["CipherNote", "TOKENS", "WORDS"]
