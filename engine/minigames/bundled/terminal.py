"""Computer terminal (``terminal``, F56): a bundled minigame where the player types commands
into an old computer, from a table the author writes in Studio.

- **Screen** (01 §7): a screen panel x 24–1256, y 24–550 (radius 8, padding 24, a 2-unit
  border). The prompt line is pinned to its bottom: the prompt text (``prompt_color``), then
  an F52 bare ``TextField`` (80 characters, any text, the keyboard kept open between
  commands). The output sits above it, bottom-anchored and wrapped at the inner width; echo
  and reply lines in ``text_color``, system lines (unknown, not yet, wrong password, hints,
  did-you-mean) in ``dim_color``. "More below" shows while scrolled up. Commands (top-left
  at (24, 566)) and Leave (top-right at (1256, 566)) are F10 buttons.
- **Look** (§6): ``screen="game"`` follows the game's panel colors (F49's Amber Terminal looks
  like an amber monitor); ``screen="dark"`` uses the ``dark.*`` tokens, opaque, in any scheme.
- **Rules** are ``terminal_rules.Session``'s: each Enter feeds it the line; ``clear``, ``exit``
  (a confirm), an ending (Continue replaces the field and takes focus; Commands and Leave are
  disabled), sounds (``key_sound`` per typed character, ``error_sound`` on a miss).
- **Input** (§7): typing and Enter (F52); Up/Down in the field recall earlier command lines,
  newest first (Down past the newest gives an empty line, then the next Down moves to
  Commands); the wheel over the screen, Page Up/Down and the bumpers scroll the output;
  typing or new output returns to the bottom. Backspace never goes back; right click and east
  open the game menu (F23).
- **Commands** list: an F10 panel with a ``ScrollList`` (640 wide, midbottom (640, 550), up to
  8 rows, ``commands_heading``, a last ``close`` row): at the command prompt the commands help
  lists, at the password prompt "Password from: <tip>" or a disabled ``no_password``. A pick
  puts the text in the field (nothing runs) and focuses it. Back closes the list.
- **Warnings** (dev, once per data): W274 (help lists nothing at the start), W275 (a command
  uses a renamed built-in's words), W273 (the screen's font can't draw a character).

Presentation only: a save during the session loads a fresh terminal (F23's checkpoint).
Imports: ``terminal_rules``, ``engine.minigames.api``, and F10's public widget kit only.
"""

import dataclasses
from typing import TYPE_CHECKING, Final

import pygame

from engine.minigames.api import Arg, Minigame, Outcome, PluginEvent, StoryNames, TextField
from engine.minigames.bundled import terminal_rules as rules
from engine.render.frames import FrameSpec
from engine.render.text import FontSpec, missing_glyphs, text_width
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, list_row_height, pitch, wrap_text
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button, ListRow, ScrollList

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas

RGB = tuple[int, int, int]

# [theme.plugin.terminal] (§6): a default naming a game token follows it; dark.* are values.
TOKENS: Final = {
    "screen.fill_color": "panel.fill_color",
    "screen.fill_opacity": "panel.fill_opacity",
    "screen.border_color": "panel.border_color",
    "text_color": "panel.text_color",
    "prompt_color": "panel.heading.text_color",
    "dim_color": "button.disabled.text_color",
    "text_font": "ui.text_font",
    "text_size": 24,
    "dark.fill_color": "#140C02",
    "dark.text_color": "#FFB000",
    "dark.prompt_color": "#FFCC00",
    "dark.dim_color": "#B07A14",
    "dark.border_color": "#9A6800",
    "key_sound": "",
    "error_sound": "",
}
WORDS: Final = rules.WORDS

SCREEN: Final = Box(24, 24, 1232, 526)
PAD: Final = 24
RADIUS: Final = 8
BORDER: Final = 2
BUTTONS_Y: Final = 566
LIST_W: Final = 640
LIST_BOTTOM: Final = (640, 550)
LIST_ROWS: Final = 8
LIST_PAD: Final = 16
TAG_PAD: Final = 8
CONTINUE_W: Final = 240
WARNED: set[str] = set()              # (code, data) keys: once per data, per process


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


class Terminal(Minigame):
    name = "terminal"
    title = "Computer"
    api = "1.4"
    args = {"data": Arg(), **{key: Arg(default=value) for key, value in rules.DEFAULTS.items()}}
    # The static outcomes gate skippable (E271); outcome_for gives the real ones.
    test_outcome = Outcome(None)
    skipped_outcome = Outcome(None)
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
        self.t = rules.parse(args)
        self.word = {key: ctx.words.mine(key) for key in WORDS if key != "title"}
        self.session = rules.Session(
            self.t, self.word, has_tip=lambda name: bool(ctx.codex.has("tip", name)),
            unlock=ctx.codex.unlock_tip, tip_title=self._tip_title,
            hide_passwords=bool(args["hide_passwords"]))
        self.dark = args["screen"] == "dark"
        self.colors = self._colors()
        self.opacity = 1.0 if self.dark else self._opacity()
        self.scale = float(ctx.settings.text_scale)
        self.sources: list[tuple[str, str]] = []          # (text, style), unwrapped
        self._pending: list[tuple[str, str]] = []          # sources not wrapped yet
        self.lines: list[tuple[str, str]] = []            # wrapped, the last 500
        self.wrapped_at: tuple | None = None
        self.scroll = 0                                    # lines above the bottom
        self.hist: int | None = None                       # history recall index
        self.finished = False
        self.panel = "screen"                              # or "commands"
        self.glyphs_checked = False
        self.field = TextField(bare=True, max_length=rules.TYPED_MAX, allowed="any",
                               keep_keyboard=True, on_submit=self._submit,
                               on_change=self._typed, text_color=self.colors["text_color"],
                               caret_color=self.colors["prompt_color"])
        self.commands_button = Button(lambda: self.word["commands"], self._open_commands,
                                      enabled=self._open)
        self.leave_button = Button(lambda: self.word["leave"], self._leave, enabled=self._open)
        self.continue_button = Button(lambda: self.word["continue"], self._continue)
        self.list = ScrollList(self._list_rows, self._picked)
        self.choices: list[tuple[str, str | None]] = []
        if self.t.welcome:
            self._add([(line, rules.PLAIN) for line in self.t.welcome.split("\n")])
        ctx.heading(False)
        ctx.hint(self.word["hint"])
        self._warn_start()
        self._layout()
        self._groups()

    def _tip_title(self, name: str) -> str:
        try:
            return str(self.ctx.codex.title(name))
        except Exception:                            # noqa: BLE001 (an undeclared tip)
            return name

    def _open(self) -> bool:
        return self.session.ended is None and not self.finished

    def _colors(self) -> dict[str, RGB]:
        out: dict[str, RGB] = {}
        for key in ("text_color", "prompt_color", "dim_color"):
            token = f"dark.{key}" if self.dark else key
            out[key] = self._color(token)
        out["fill"] = self._color("dark.fill_color" if self.dark else "screen.fill_color")
        out["border"] = self._color("dark.border_color" if self.dark
                                    else "screen.border_color")
        return out

    def _color(self, key: str) -> RGB:
        theme = self.ctx.theme
        mine = theme.mine(key)
        found = _rgb(mine)
        if found is None and type(mine) is str:
            found = _rgb(theme.get(mine))
        if found is None:
            found = _rgb(theme.get(TOKENS[key])) if not TOKENS[key].startswith("#") else None
        return found if found is not None else (0, 0, 0)

    def _opacity(self) -> float:
        value = self.ctx.theme.mine("screen.fill_opacity")
        if type(value) is str:
            value = self.ctx.theme.get(value)
        return float(value) if type(value) in (int, float) else 1.0

    def _sound(self, key: str) -> None:
        file = self.ctx.theme.mine(key)
        if type(file) is str and file:
            self.ctx.play_sound(file)

    # -- warnings (dev, once per data) --

    def _once(self, code: str, text: str) -> None:
        key = f"{code}:{text}:{repr(self.args['data'])[:20_000]}"
        if key in WARNED:
            return
        WARNED.add(key)
        self.ctx.log.warning("%s", text, extra={"code": code})

    def _warn_start(self) -> None:
        if not self.ctx.dev:
            return
        if rules.w274_needed(self.t, self.session.has_tip):
            self._once("W274", rules.W274_TEXT)
        for text in rules.w275_texts(self.t, self.word):
            self._once("W275", text)

    def _check_glyphs(self, canvas: "Canvas") -> None:
        self.glyphs_checked = True
        if not self.ctx.dev:
            return
        font = self._font()
        handle = canvas.font_handle(font, font.size).font
        missing = missing_glyphs(handle, rules.data_chars(self.t))
        if missing:
            self._once("W273", rules.w273_text(missing))

    # -- typing and Enter --

    def _typed(self, text: str) -> None:
        if self.field.last_edit in ("type", "paste"):
            self._sound("key_sound")
        self.scroll = 0

    def _submit(self, text: str) -> None:
        if not self._open():
            return
        self.field.set_text("")
        self.hist = None
        sub = self.session.submit(text)
        if sub.clear:                                     # an empty screen, echo too
            self.sources, self.lines, self._pending, self.wrapped_at = [], [], [], None
        else:
            self._add(sub.lines)
        if sub.error:
            self._sound("error_sound")
        self.field.mask = bool(self.args["hide_passwords"]) and self.session.mode == "password"
        self.scroll = 0
        if sub.confirm:
            self._confirm_leave()
        if sub.ended:
            self._groups()
            self.ctx.scope.focus(self.continue_button, InputKind.KEYS)

    def _add(self, lines: list[tuple[str, str]]) -> None:
        self.sources.extend(lines)
        self._pending.extend(lines)

    def _confirm_leave(self) -> None:
        def yes() -> None:
            if not self.finished:
                self.finished = True
                self.ctx.finish(self.session.result(self.args["result"]))
        self.ctx.confirm("confirm_leave", yes)

    def _leave(self) -> None:
        if self._open():
            self._confirm_leave()

    def _continue(self) -> None:
        if not self.finished and self.session.ended is not None:
            self.finished = True
            self.ctx.finish(self.session.result(self.args["result"]))

    # -- the Commands list --

    def _list_rows(self) -> list[ListRow]:
        rows = [ListRow(shown, value is not None) for shown, value in self.choices]
        return rows + [ListRow(self.word["close"])]

    def _open_commands(self) -> None:
        if not self._open():
            return
        self.choices = self.session.command_choices()
        self.panel = "commands"
        self.list.focus_row = 0
        self.list.scroll = 0.0
        self._layout()
        self._groups()

    def _picked(self, index: int) -> None:
        if index < len(self.choices):
            value = self.choices[index][1]
            if value is None:
                return
            self.field.set_text(value)
        self._close_commands()

    def _close_commands(self) -> None:
        self.panel = "screen"
        self._groups()
        self.ctx.scope.focus(self.field, InputKind.KEYS)

    # -- layout --

    def _size(self) -> int:
        size = self.ctx.theme.mine("text_size")
        size = size if type(size) is int else 24
        return max(1, round(size * self.scale))

    def _font(self) -> FontSpec:
        ref = self.ctx.theme.mine("text_font")
        size = self._size()
        if type(ref) is str and ref and ref != "ui.text_font":
            return self.ctx.font(ref, size)
        return self.ctx.font(None, size)

    def _layout(self) -> None:
        size = self._size()
        self.pitch = pitch(size)
        inner_x = SCREEN.x + PAD
        self.inner = Box(inner_x, SCREEN.y + PAD, SCREEN.w - 2 * PAD, SCREEN.h - 2 * PAD)
        self.prompt_y = SCREEN.bottom - PAD - self.pitch
        self.visible = max(1, int((self.prompt_y - self.inner.y) // self.pitch))
        bh = button_height(scale=self.scale)
        self.commands_button.box = Box(SCREEN.x, BUTTONS_Y, 240, bh)
        self.leave_button.box = Box(SCREEN.right - 240, BUTTONS_Y, 240, bh)
        self.continue_button.box = Box(inner_x, SCREEN.bottom - PAD - bh, CONTINUE_W, bh)
        row_h = list_row_height(scale=self.scale)
        self.list.row_height = row_h
        rows = min(LIST_ROWS, len(self.choices) + 1)
        head = pitch(max(1, round(32 * self.scale)))
        list_h = rows * row_h
        panel_h = LIST_PAD * 3 + head + list_h
        cx, bottom = LIST_BOTTOM
        self.list_panel = Box(cx - LIST_W / 2, bottom - panel_h, LIST_W, panel_h)
        self.list.box = Box(self.list_panel.x + LIST_PAD,
                            self.list_panel.y + 2 * LIST_PAD + head, LIST_W - 2 * LIST_PAD,
                            list_h)
        self._place_field(None)

    def _place_field(self, prompt_w: float | None) -> None:
        width = prompt_w if prompt_w is not None else len(self.session.prompt()) * self.pitch * 0.5
        x = self.inner.x + width + self.pitch * 0.3
        self.field.box = Box(x, self.prompt_y, self.inner.right - x, self.pitch)

    def _groups(self) -> None:
        scope = self.ctx.scope
        if self.panel == "commands":
            scope.set_groups([FocusGroup([self.list])])
            scope.set_default(self.list)
            scope.focus(self.list, InputKind.KEYS, sound=False)
            return
        buttons = FocusGroup([self.commands_button, self.leave_button])
        if self.session.ended is not None:
            scope.set_groups([FocusGroup([self.continue_button]), buttons])
            scope.set_default(self.continue_button)
            return
        scope.set_groups([FocusGroup([self.field]), buttons])
        scope.set_default(self.field)

    def layout(self, area) -> None:
        self._layout()

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.scale = float(s.text_scale)
        self.wrapped_at = None
        self._layout()

    # -- input --

    def handle_event(self, ev: PluginEvent) -> bool:
        nav = ev.nav
        raw = ev.ui.raw
        if self.panel == "commands":
            if nav is Nav.BACK:
                self._close_commands()
                return True
            return False
        if raw.type == pygame.MOUSEWHEEL:
            pos = ev.ui.canvas_pos
            if pos is not None and SCREEN.contains(pos):
                self._scroll_by(int(getattr(raw, "y", 0)) * 3)
                return True
            return False
        if nav in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            step = max(1, self.visible - 1)
            self._scroll_by(step if nav is Nav.PAGE_UP else -step)
            return True
        if self.ctx.scope.focused is self.field and nav in (Nav.UP, Nav.DOWN) \
                and self.session.mode == "command":
            return self._recall(nav is Nav.UP)
        return False

    def _recall(self, up: bool) -> bool:
        history = self.session.history
        if up:
            if not history:
                return True
            self.hist = len(history) - 1 if self.hist is None else max(0, self.hist - 1)
            self.field.set_text(history[self.hist])
            return True
        if self.hist is None:                             # past the newest: Commands
            if self.commands_button.enabled():
                self.ctx.scope.focus(self.commands_button, InputKind.KEYS)
            return True
        if self.hist < len(history) - 1:
            self.hist += 1
            self.field.set_text(history[self.hist])
        else:
            self.hist = None
            self.field.set_text("")
        return True

    def _scroll_by(self, lines: int) -> None:
        top = max(0, len(self.lines) - self.visible)
        self.scroll = max(0, min(top, self.scroll + lines))

    def update(self, dt: float) -> None:
        pass

    # -- drawing --

    def _wrap(self, canvas: "Canvas") -> None:
        font = self._font()
        key = (font, round(self.inner.w))
        handle = canvas.font_handle(font, font.size).font

        def measure(text: str, _size: int) -> float:
            return float(text_width(handle, text))

        if key != self.wrapped_at:
            self.wrapped_at = key
            todo, self.lines = list(self.sources), []
        else:
            todo = self._pending
        self._pending = []
        for text, style in todo:
            body = text.lstrip(" ")
            indent = text[:len(text) - len(body)]          # help's two-space indent stays
            width = max(1.0, self.inner.w - measure(indent, font.size))
            for k, line in enumerate(wrap_text(body, width, font.size, measure) or [""]):
                self.lines.append(((indent if k == 0 else "") + line, style))
        if len(self.lines) > rules.OUTPUT_MAX:
            self.lines = self.lines[-rules.OUTPUT_MAX:]
            self.sources = self.sources[-rules.OUTPUT_MAX:]
        self.scroll = min(self.scroll, max(0, len(self.lines) - self.visible))

    def draw(self, canvas: "Canvas") -> None:
        p = self.ctx.painter
        if not self.glyphs_checked:
            self._check_glyphs(canvas)
        self._wrap(canvas)
        p.shape(SCREEN, FrameSpec(self.colors["fill"], self.opacity, self.colors["border"],
                                  BORDER, RADIUS))
        font = self._font()
        handle = canvas.font_handle(font, font.size).font
        styles = {rules.ECHO: self.colors["text_color"], rules.PLAIN: self.colors["text_color"],
                  rules.SYSTEM: self.colors["dim_color"]}
        bottom = self.prompt_y
        end = len(self.lines) - self.scroll
        y = bottom
        for line, style in reversed(self.lines[max(0, end - self.visible):end]):
            y -= self.pitch
            if line:
                canvas.draw_text(line, font, styles[style], (self.inner.x, y))
        if self.session.ended is None:
            prompt = self.session.prompt()
            canvas.draw_text(prompt, font, self.colors["prompt_color"],
                             (self.inner.x, self.prompt_y))
            self._place_field(float(text_width(handle, prompt)))
        if self.scroll > 0:
            text = self.word["more_below"]
            w = float(text_width(handle, text)) + 2 * TAG_PAD
            tag = Box(self.inner.right - w, bottom - self.pitch, w, self.pitch)
            p.shape(tag, FrameSpec(self.colors["fill"], 1.0, self.colors["border"], BORDER,
                                   RADIUS))
            canvas.draw_text(text, font, self.colors["dim_color"], tag.center,
                             anchor="center")
        if self.panel == "commands":
            p.panel(self.list_panel)
            p.heading(self.word["commands_heading"],
                      (self.list_panel.x + LIST_PAD, self.list_panel.y + LIST_PAD))


__all__ = ["TOKENS", "Terminal", "WORDS"]
