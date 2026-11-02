"""Puzzle room (F27): a bundled point-and-click room. A background picture fills the screen;
invisible hotspots on it can be looked at, picked up, used with an item from F21's
``CodexView``, or clicked to leave, and two items can be combined into a third. A run ends
exactly when story state would change (a take, a right use, a combine, or a plain click), and
the story gets ``{"action", "hotspot", "item", "gone"}``, passed back as ``state``.

Step F27-1 built the declarations and the three API 1.1 hooks; every rule they use is in
``room_rules``. Step F27-3 adds the playable session (F27 ``04`` §6):

- ``start`` parses the checked room, works out the run's ``gone`` (``room_rules.run_gone``:
  ``state``'s spent keys plus the take hotspots whose item is held, 07 G6) and the shown
  hotspots, and puts one ``Hotspot`` widget per shown spot in ``ctx.scope`` with the Items
  button (and Put away while an item is selected). Hover is focus (F23 A4), so the focused
  hotspot's ring and name tag are its only look: at most one ring and one tag.
- **Room mode.** Activating a hotspot asks ``room_rules.activate``: a caption replaces the
  hint; a finish makes its ledger request (``give`` for a take) and calls ``ctx.finish`` in
  the same call. Back puts a selection away; Page Up/Down and LB/RB step focus in Tab order
  (``ctx.scope.tab``, C2), so every hotspot is reachable from a gamepad.
- **Picker mode.** Items opens F21's ``CodexView`` (``ctx.codex_view``, A6) over the held
  items: a pick selects an item, or, with an item selected and a ``combine`` in the room,
  combines the two (``take, take, give``, then ``ctx.finish``), or says ``no_combine`` and
  stays open.
- **Lazy layout.** ``layout``, ``settings_changed``, and mode and selection changes set flags;
  ``draw`` recomputes the buttons, Put away's label, the picker, and the tag wraps when
  something changed (W180 runs after each recompute, in dev).
- W179 (at ``start``) and W180 are logged once per distinct text per process (``_WARNED``,
  at most 100), in dev only, in F25's coded form on ``ctx.log``.

Presentation-only: looks, wrong tries, the selection, and the open picker are never saved; a
restore starts the room again from its arguments and the held items.

Imports (AC-F27-01): ``room_rules``, ``engine.minigames.api``, F10's public widget kit with
F25's A7 (``ui.focus``, ``ui.widgets``, ``ui.nav``, ``ui.layouts``), and F26's A8
(``engine.render.frames``).
"""

import dataclasses
from typing import TYPE_CHECKING, Any, Final

from engine.minigames.api import (Arg, CodexFilter, Minigame, Outcome, PickAction,
                                  PluginEvent, StoryNames)
from engine.minigames.bundled import room_rules
from engine.minigames.bundled.room_rules import Caption, Finish
from engine.render.frames import FrameSpec
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, cut_to_width, pitch, wrap_text
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button, Look, Widget, clipped

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter

# [theme.plugin.puzzle_room.<element>] (F27 01 §6.4, 04 §12).
TOKENS = {
    "spot.ring_color": "#FFFFFF",
    "spot.ring_shadow_color": "#1A1A1A",
}

# [words.plugin.puzzle_room] (F27 01 §6.4; hint_using_only is 04 §12's, Q-e). {item} is the
# item's title (A9), replaced with str.replace.
WORDS = {
    "title": "Puzzle Room",
    "hint": "Look around. Pick an item in Items to use it.",
    "hint_using": "Choose where to use {item}, or combine it in Items.",
    "hint_using_only": "Choose where to use {item}.",
    "hint_picker": "Choose an item to use.",
    "hint_combine": "Choose an item to combine with {item}.",
    "items": "Items",
    "back": "Back",
    "use": "Use",
    "combine": "Combine",
    "put_away": "Put away {item}",
    "need_item": "You need something for this.",
    "no_use": "That doesn't work.",
    "no_combine": "Those don't go together.",
}

ROOM, PICKER = "room", "picker"
WARN_MAX: Final = 100                     # distinct W179/W180 texts per process
_SHAPE: Final = FrameSpec((0, 0, 0), slice_width=0)   # an image as one smoothscale (A8)
_PAD_X, _PAD_Y = room_rules.TAG_PAD
_ITEM: Final = room_rules.ITEM

RGB = tuple[int, int, int]

# W179/W180 texts already logged this process (dev only; never saved; at most WARN_MAX).
_WARNED: set[str] = set()


def _rgb(value: object, default: str) -> RGB:
    """A color token: ``"#RRGGBB"`` (the declared default) or an RGB triple (typed config);
    anything else is the default."""
    for v in (value, default):
        if type(v) is str and len(v) in (7, 9) and v[0] == "#":
            try:
                return int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16)
            except ValueError:
                continue
        if isinstance(v, (tuple, list)) and len(v) >= 3 \
                and all(type(c) is int and 0 <= c <= 255 for c in v[:3]):
            return int(v[0]), int(v[1]), int(v[2])
    return (0, 0, 0)


class Hotspot(Widget):
    """One shown hotspot: its box is the room's rect (canvas units, never moved). It draws
    nothing at rest; focused or pressed, the ring and the name tag (hover is focus, A4)."""

    def __init__(self, game: "PuzzleRoom", spot: room_rules.Spot) -> None:
        super().__init__(box=Box(*spot.rect))
        self.game = game
        self.spot = spot

    def activate(self) -> None:
        self.game._activate(self.spot.key)

    def draw(self, p: "Painter", look: Look) -> None:
        if self.game.opened and (look.state == "focused" or (
                look.state == "pressed" and self.game._pressed_shows(self))):
            self.game._draw_focus(self, p)


class _RoomButton(Button):
    """F10's button, drawn at rest in the opening picture (UI-F27-06: nothing focused)."""

    def __init__(self, game: "PuzzleRoom", label, action) -> None:
        super().__init__(label, action)
        self.game = game

    def draw(self, p: "Painter", look: Look) -> None:
        super().draw(p, look if self.game.opened else Look("normal"))


class PuzzleRoom(Minigame):
    name = "puzzle_room"
    title = "Puzzle Room"
    api = "1.1"
    over_stage = False
    args = {"room": Arg(), "state": Arg(default=None)}
    # The static outcomes gate skippable (E271) and E279; outcome_for gives the real ones
    # (PR-F27-11).
    test_outcome = Outcome(None)
    skipped_outcome = Outcome(None)
    tokens = TOKENS
    words = WORDS

    # -- API 1.1 hooks (fresh, never-started instances) --

    def check_args(self, args: dict) -> str | None:
        return room_rules.problem(args)

    def check_story(self, args: dict, story: StoryNames) -> str | None:
        return room_rules.story_problem(args, story)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        """Leave by the first exit, for ``"test"`` and ``"skipped"`` alike (04 §6.4)."""
        if kind not in ("test", "skipped"):
            raise ValueError(f"unknown outcome kind {kind!r}")
        # The run's gone is run_gone (G6: held takes join it), but this hook sees only the
        # declared names, never the held items, so nothing counts as held here.
        room = room_rules.parse(args["room"])
        return room_rules.fixed_outcome(room, room_rules.run_gone(room, args.get("state"), ()))

    # -- the session (04 §6.1) --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        room = self.room = room_rules.parse(ctx.args["room"])
        self.held = tuple(ctx.codex.items())
        # The run's gone (07 G6): held takes count as spent and join every result's gone.
        self.gone = room_rules.run_gone(room, ctx.args["state"], self.held)
        self.keys = room_rules.shown(room, self.gone, self.held)
        self.mode = ROOM
        self.selected: str | None = None
        self.caption: str | None = None
        self.view: Any = None
        self.combining = False
        self.done = False
        self.last_kind = InputKind.MOUSE
        self.flash: str | None = None         # the hotspot activated by keys, until a move
        # The host draws the opening picture before any update (on a cut, after its first
        # focus); the widgets draw at rest until the first update, so it shows no ring.
        self.opened = False
        word = ctx.words.mine
        self.spots = [Hotspot(self, room.spot(k)) for k in self.keys]
        self.items = _RoomButton(self, lambda: word("items"), self._open_picker)
        self.put_away = _RoomButton(self, lambda: self.put_away_text, self._put_away)
        self.back = _RoomButton(self, lambda: word("back"), self._close_picker)
        self.put_away_text = ""
        self._set_room_groups()
        ctx.heading(False)
        self._base_hint()
        self.bg = ctx.image(room.background)
        self.imgs = {s.spot.key: ctx.image(s.spot.image) for s in self.spots
                     if s.spot.image is not None}
        mine = ctx.theme.mine
        self.ring_color = _rgb(mine("spot.ring_color"), TOKENS["spot.ring_color"])
        self.shadow_color = _rgb(mine("spot.ring_shadow_color"),
                                 TOKENS["spot.ring_shadow_color"])
        self.area = ctx.area
        self.dirty = True                     # the buttons, Put away's label, the tags
        self.picker_dirty = False             # the picker's layout and view
        self.lay: room_rules.RoomLayout | None = None
        self.picker: room_rules.PickerLayout | None = None
        self._sizes: tuple[int, int, int] | None = None       # (bh, bs, ts)
        self._tags: dict[tuple[str, int], tuple[tuple[str, ...], float, float]] = {}
        self._fonts: dict[tuple, Any] = {}
        self.text_font = ctx.font(None, room_rules.TAG_SIZE)  # ui.text_font
        self.recomputes = 0                   # lazy recomputes so far (AC-F27-15, 25)
        if ctx.dev:
            text = room_rules.w179_text(room, self.gone, self.held)
            if text is not None:
                self._warn("W179", text)

    def update(self, dt: float) -> None:
        self.opened = True
        # The view lays out its body paragraphs lazily. The held items never change inside a
        # run (every ledger request ends it), so its shown widgets never change either.
        if self.view is not None and not self.done:
            self.view.update(dt)

    def handle_event(self, ev: PluginEvent) -> bool:
        """04 §6.5: Back puts a selection away or closes the picker; in room mode the Page
        keys and shoulders step focus in Tab order (C2); in the picker the view's routes come
        first. Everything else is the host's (F10 routing, hover, clicks, the wheel)."""
        self.last_kind = InputKind.MOUSE if ev.ui.canvas_pos is not None else InputKind.KEYS
        if self.done:
            return False
        nav = ev.nav
        if nav is not None and nav is not Nav.ACTIVATE:
            self.flash = None
        if self.mode == PICKER:
            if nav is Nav.BACK:
                self._close_picker()
                return True
            if nav is not None and self.view is not None:
                return bool(self.view.on_nav(nav))
            return False            # the pointer: the view's widgets, through the host
        if nav is Nav.BACK:
            if self.selected is None:
                return False        # F23's fallback: right click and east open the menu
            self._put_away()
            return True
        if nav is Nav.PAGE_UP or nav is Nav.PAGE_DOWN:
            return bool(self.ctx.scope.tab(nav is Nav.PAGE_DOWN))
        return False

    def layout(self, area) -> None:
        self.area = area
        self.dirty = True
        if self.mode == PICKER:
            self.picker_dirty = True

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.dirty = True
        if self.mode == PICKER:
            self.picker_dirty = True

    def draw(self, canvas: "Canvas") -> None:
        self._settle(canvas)
        p = self.ctx.painter
        self._draw_image(canvas, p, self.bg, room_rules.cover_box(self.bg.size),
                         Box(0, 0, *room_rules.CANVAS))
        for s in self.spots:
            ref = self.imgs.get(s.spot.key)
            if ref is not None:
                self._draw_image(canvas, p, ref, room_rules.fit_box(ref.size, s.spot.rect),
                                 s.box)
        if self.mode == PICKER and self.view is not None and self.picker is not None:
            p.panel(Box(*self.picker.backing))
            self.view.draw(canvas, p)

    # -- room mode (04 §6.2) --

    def _room_groups(self) -> list[FocusGroup]:
        buttons = [self.items] + ([self.put_away] if self.selected is not None else [])
        return [FocusGroup(list(self.spots)), FocusGroup(buttons)]

    def _set_room_groups(self) -> None:
        scope = self.ctx.scope
        scope.set_groups(self._room_groups())
        scope.set_default(self.spots[0] if self.spots else self.items)

    def _title(self, name: str) -> str:
        return self.ctx.codex.title(name)

    def _base_hint(self) -> None:
        """The hint with no caption (04 §6.2, §6.3): in the picker ``hint_combine`` or
        ``hint_picker``; else ``hint``, or with a selection ``hint_using`` (``hint_using_only``
        in a room without ``combine``). ``{item}`` is the selection's title."""
        self.caption = None
        word = self.ctx.words.mine
        selected = self.selected
        if self.mode == PICKER:
            text = word("hint_combine").replace(_ITEM, self._title(selected)) \
                if self.combining and selected is not None else word("hint_picker")
        elif selected is None:
            text = word("hint")
        else:
            key = "hint_using" if self.room.combine else "hint_using_only"
            text = word(key).replace(_ITEM, self._title(selected))
        self.ctx.hint(text)

    def _say(self, text: str) -> None:
        self.caption = text
        self.ctx.hint(text)

    def _activate(self, key: str) -> None:
        if self.done or self.mode != ROOM:
            return
        self.flash = key
        step = room_rules.activate(self.room, key, self.selected, self.gone)
        if isinstance(step, Caption):
            self._say(step.text if step.text is not None
                      else self.ctx.words.mine(step.word))
            return
        self._finish(step)

    def _finish(self, step: Finish) -> None:
        assert not self.done, "the run finished twice"
        if step.give is not None:
            self.ctx.codex.give(step.give)
        self.done = True
        self.ctx.finish(step.result)

    def _focus_or_clear(self, target: Widget) -> None:
        """Keys: focus ``target``; the pointer: nothing focused (04 §6.2, §6.3)."""
        scope = self.ctx.scope
        if self.last_kind is InputKind.KEYS:
            scope.focus(target, InputKind.KEYS)
        else:
            scope.clear()

    def _put_away(self) -> None:
        if self.done or self.selected is None or self.mode != ROOM:
            return
        self.selected = None
        self.dirty = True
        self._set_room_groups()
        self._base_hint()
        self._focus_or_clear(self.items)

    # -- picker mode and combine (04 §6.3) --

    def _open_picker(self) -> None:
        if self.done or self.mode != ROOM:
            return
        ctx = self.ctx
        self.combining = self.selected is not None and bool(self.room.combine)
        word = ctx.words.mine("combine" if self.combining else "use")
        # A fresh view on each open: the pick word depends on the selection.
        self.view = ctx.codex_view(filter=CodexFilter(kinds=frozenset({"item"})),
                                   pick=PickAction(word, self._picked))
        self.mode = PICKER
        self._build_picker()
        default = self.view.default_widget() or self.back
        ctx.scope.set_default(default)
        self._focus_or_clear(default)
        self._base_hint()

    def _build_picker(self) -> None:
        """Lay the picker out in the area (F25's numbers) and build the view in it."""
        ctx = self.ctx
        scale = ctx.painter.text_scale()
        lay = self.picker = room_rules.picker_layout(
            self.area, button_h=button_height(scale=scale))
        groups = self.view.build(Box(*lay.view), scale)
        self.back.box = Box(*lay.back)
        ctx.scope.set_groups([*groups, FocusGroup([self.back])])
        self.picker_dirty = False

    def _close_picker(self) -> None:
        if self.done or self.mode != PICKER:
            return
        self.mode = ROOM
        self.view = None
        self.picker = None
        self.combining = False
        self._set_room_groups()
        self._focus_or_clear(self.items)
        self._base_hint()

    def _picked(self, name: str) -> None:
        if self.done or self.mode != PICKER:
            return
        selected = self.selected
        if not self.combining:
            self.selected = name
            self.dirty = True
            self._close_picker()
            return
        assert selected is not None
        if name == selected:
            self._close_picker()
            return
        made = room_rules.combine_pair(self.room, selected, name)
        if made is None:
            self._say(self.ctx.words.mine("no_combine"))
            return
        codex = self.ctx.codex
        codex.take(selected)
        codex.take(name)
        codex.give(made)
        self.done = True
        self.ctx.finish(room_rules.result_of(self.room, "combine", None, made, self.gone))

    # -- layout (04 §6.6) --

    def _measure(self, canvas: "Canvas", spec: Any):
        """A ``layouts.Measure`` in canvas units with ``spec``'s face (fonts cached)."""
        fonts = self._fonts

        def measure(text: str, size: int) -> float:
            key = (spec.ref, spec.bundled, spec.synth, size)
            font = fonts.get(key)
            if font is None:
                font = fonts[key] = canvas.font_handle(dataclasses.replace(spec, size=size),
                                                       size).font
            return font.size(text)[0] if text else 0
        return measure

    def _settle(self, canvas: "Canvas") -> None:
        """Recompute whatever changed since the last draw (lazy, as F24 §6.5)."""
        p = self.ctx.painter
        scale = p.text_scale()
        button = p.style("button")
        sizes = (button_height(scale=scale), p.scaled_size(button.font.size),
                 p.scaled_size(room_rules.TAG_SIZE))
        if sizes != self._sizes:
            self._sizes = sizes
            self.dirty = True
            if self.mode == PICKER:
                self.picker_dirty = True
        if self.mode == PICKER and self.picker_dirty and self.view is not None:
            self._build_picker()
        if not self.dirty:
            return
        self.dirty = False
        self.recomputes += 1
        bh, bs, _ = sizes
        if self.selected is not None:
            self.put_away_text, w = room_rules.put_away_label(
                self.ctx.words.mine("put_away"), self._title(self.selected), size=bs,
                measure=self._measure(canvas, button.font), cut_to_width=cut_to_width)
        else:
            self.put_away_text, w = "", float(room_rules.PUT_AWAY_W[0])
        lay = self.lay = room_rules.room_layout(self.area, button_h=bh, put_away_w=w)
        self.items.box = Box(*lay.items)
        self.put_away.box = Box(*lay.put_away)
        if self.ctx.dev:
            for text in room_rules.w180_texts(self.room, self.keys, row=lay.row,
                                              area=self.area):
                self._warn("W180", text)

    def _tag(self, canvas: "Canvas", label: str, ts: int) -> tuple[tuple[str, ...], float,
                                                                     float]:
        """The tag's lines and size (07 I-5, G5): the label wrapped (never cut) at
        ``area.w − 24``; the widest line + 24 wide, ``lines × pitch + 12`` tall. Cached per
        (label, size), so a steady frame renders no new text."""
        key = (label, ts)
        found = self._tags.get(key)
        if found is None:
            measure = self._measure(canvas, self.text_font)
            lines = tuple(wrap_text(label, self.area.w - 2 * _PAD_X, ts, measure)) \
                or (label,)
            w = max(measure(line, ts) for line in lines) + 2 * _PAD_X
            h = len(lines) * pitch(ts) + 2 * _PAD_Y
            found = self._tags[key] = (lines, w, h)
        return found

    # -- drawing (04 §6.6) --

    def _draw_image(self, canvas: "Canvas", p: Any, ref: Any, box: room_rules.Box4,
                    clip: Box) -> None:
        """A real image in ``box`` (one cached smoothscale, A8); F04's placeholder centered
        in ``clip`` and clipped to it."""
        if not ref.is_placeholder:
            p.shape(Box(*box), _SHAPE, image=ref)
            return
        with clipped(p, clip):
            canvas.draw_image(ref, clip.center, anchor="center")

    def _pressed_shows(self, hotspot: Hotspot) -> bool:
        """A pressed hotspot shows its ring while the pointer holds it, or for the host's
        key-press flash until the focus moves on (one ring and one tag, C3)."""
        return self.last_kind is InputKind.MOUSE or self.flash == hotspot.spot.key

    def _draw_focus(self, hotspot: Hotspot, p: "Painter") -> None:
        """The focused hotspot's ring (8 fills) and name tag (one panel and its lines)."""
        spot = hotspot.spot
        colors, shadows = room_rules.ring_rects(spot.rect)
        for r in shadows:
            p.rect(Box(*r), self.shadow_color)
        for r in colors:
            p.rect(Box(*r), self.ring_color)
        lay, sizes = self.lay, self._sizes
        if lay is None or sizes is None:
            return
        ts = sizes[2]
        canvas = p.canvas
        lines, w, h = self._tag(canvas, spot.label, ts)
        row = lay.row
        x, y, w, h = room_rules.tag_box(spot.rect, w, h, row_bottom=row[1] + row[3],
                                        area=self.area)
        p.panel(Box(x, y, w, h))
        font = dataclasses.replace(self.text_font, size=ts)
        color = p.style("panel").text_color
        step = pitch(ts)
        for i, line in enumerate(lines):
            canvas.draw_text(line, font, color, (x + _PAD_X, y + _PAD_Y + i * step))

    # -- dev warnings (04 §6.7) --

    def _warn(self, code: str, text: str) -> None:
        if text in _WARNED or len(_WARNED) >= WARN_MAX:
            return
        _WARNED.add(text)
        self.ctx.log.warning("%s", text, extra={"code": code})


__all__ = ["TOKENS", "WORDS", "Hotspot", "PuzzleRoom"]
