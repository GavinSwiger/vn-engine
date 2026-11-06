"""Database ▸ Meters' setup without code (F62 round 2; specs/F62-visible-meters/SPEC.md §7).

Why this module exists: an author who has never coded should get a working meter in one
click, then pick how it looks on screen while seeing it. ``MeterSetup`` is a mixin of
``dbmore.MoreCategories`` (so of ``database.DatabasePane``):

- **+ Meter** (``meter_menu``): the game's kit's ready-made meters first (range, start and
  ranks set), or a short general list with a link to Game settings ▸ Kit; then **Blank
  meter…**. A preset becomes one ``points`` line (``declarations.meter_line``).
- **On screen** (``_look_rows``): Look, Corner (``CornerPicker``, a small 2 × 2 screen) and
  Label. Unset, each shows what the kit (or the engine) gives, and the line under them says
  so; **Use default** clears one. A change writes ``[meter.<name>]`` in config.toml with
  ``tomlpatch.plan_changes`` as one undo step; clearing the last key takes the table too.
- **Preview**: a small stage in the game's color scheme beside the fields, the meter in its
  look and corner at a sample value with its rank (``meterdraw``), redrawn on every change.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any

from engine.core.kits import MeterSuggestion
from engine.core.skins import CORNER_PLACES, METER_LOOKS
from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, meterdraw, settingsmodel, tomlpatch
from engine.tools.editor import metermodel as mm
from engine.tools.editor.dialogs import show_error
from engine.tools.editor.fieldwidgets import ChoiceField, FormGrid, FormRow, TextField, _Field
from engine.tools.editor.theme import ROLES, THEME

# --- Texts ------------------------------------------------------------------------------------

ON_SCREEN = "On screen"
LABEL_LOOK = "Look"
LABEL_CORNER = "Corner"
LABEL_SHOWN_AS = "Label"
DEFAULT_SUFFIX = "{name} (default)"
SHOW_HINT = "Shown while the story says: show meter {name}"
CONFIG_BROKEN = ("The game's settings file has a mistake, so the meter's look can't be "
                 "saved. Open config.toml in the Editor to fix it.")
LOOK_TITLE = "Meter look: {name}"

# Sizes (px at 100 %).
PREVIEW_W = 176                 # 1280 × 720 at 13.75 %, as wide as a kit card
PREVIEW_H = 99
PREVIEW_METER_W = 76
CORNER_W = 60                   # the corner picker's little screen
CORNER_H = 36
CORNER_CELL = (22, 11)          # one corner's box


class CornerPicker(_Field):
    """Four corners of a small screen, and the picked one's name; click one (or arrows,
    then Space) to pick it. Its ``value`` is a ``skins.CORNER_PLACES`` place, or None for
    the default, drawn as ``fallback`` with a dashed outline and no fill."""

    def __init__(self, parent: tk.Misc, value: str | None, fallback: str, *, scale: float,
                 on_change: Callable[[object], object] | None = None) -> None:
        super().__init__(value, on_change)
        self.fallback = fallback
        self.scale = scale
        self.widget = frame = ttk.Frame(parent)
        px = self._px
        self.canvas = tk.Canvas(frame, width=px(CORNER_W), height=px(CORNER_H),
                                highlightthickness=0, background=THEME["editor.background"],
                                takefocus=True, cursor="hand2")
        self.canvas.pack(side="left")
        self.words = ttk.Label(frame, style="Hint.TLabel")
        self.words.pack(side="left", padx=(px(8), 0))
        self.focus = value or fallback
        self.canvas.bind("<Button-1>", self._click)
        for key, step in (("<Left>", (0, -1)), ("<Right>", (0, 1)), ("<Up>", (-1, 0)),
                          ("<Down>", (1, 0))):
            self.canvas.bind(key, lambda _e, s=step: self._move(s))
        for key in ("<space>", "<Return>"):
            self.canvas.bind(key, lambda _e: self.pick(self.focus))
        self.canvas.bind("<FocusIn>", lambda _e: self._show())
        self.canvas.bind("<FocusOut>", lambda _e: self._show())
        self._show()

    def _px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def set_fallback(self, fallback: str) -> None:
        self.fallback = fallback
        self._show()

    def cell(self, place: str) -> tuple[int, int, int, int]:
        px = self._px
        w, h = px(CORNER_CELL[0]), px(CORNER_CELL[1])
        inset = px(4)
        right, bottom = px(CORNER_W) - 1, px(CORNER_H) - 1
        x0 = inset if place.endswith("left") else right - inset - w
        y0 = inset if place.startswith("top") else bottom - inset - h
        return x0, y0, x0 + w, y0 + h

    def _show(self) -> None:
        canvas, px = self.canvas, self._px
        canvas.delete("all")
        shown = self.value or self.fallback
        canvas.create_rectangle(0, 0, px(CORNER_W) - 1, px(CORNER_H) - 1,
                                fill=THEME["card.background"], outline=THEME["border"])
        has_focus = canvas.focus_get() is canvas if canvas.winfo_exists() else False
        for place in CORNER_PLACES:
            chosen = place == shown
            x0, y0, x1, y1 = self.cell(place)
            canvas.create_rectangle(
                x0, y0, x1, y1, tags=(f"corner:{place}",) + (("chosen",) if chosen else ()),
                fill=ROLES["accent"] if chosen and self.value else
                THEME["editor.background"],
                outline=ROLES["accent"] if chosen else THEME["border"],
                dash=(2, 2) if chosen and not self.value else (),
                width=2 if chosen and not self.value else 1)
            if has_focus and place == self.focus:
                canvas.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2,
                                        outline=THEME["focusBorder"], tags=("focus",))
        self.words.configure(text=mm.PLACE_NAMES[shown])

    def _click(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        for place in CORNER_PLACES:
            x0, y0, x1, y1 = self.cell(place)
            mid_x, mid_y = self._px(CORNER_W) / 2, self._px(CORNER_H) / 2
            if (event.x < mid_x) == place.endswith("left") and \
                    (event.y < mid_y) == place.startswith("top"):
                self.pick(place)
                return

    def _move(self, step: tuple[int, int]) -> None:
        row = 0 if self.focus.startswith("top") else 1
        col = 0 if self.focus.endswith("left") else 1
        row, col = min(1, max(0, row + step[0])), min(1, max(0, col + step[1]))
        self.focus = (("top", "bottom")[row]) + "_" + (("left", "right")[col])
        self._show()

    def pick(self, place: str | None) -> None:
        """Pick ``place`` as the author would (None: the default)."""
        if place is not None:
            self.focus = place
        self._commit(place)
        self._show()


class MeterSetup:
    """+ Meter's presets and a meter's On screen fields and preview (a mixin of
    ``dbmore.MoreCategories``: it uses the pane's writers)."""

    win: Any
    root: Any
    scale: float
    texts: dict[str, str]
    form: Any
    fonts: Any
    new_button: Any
    last_menu: Any
    _px: Callable[[float], int]
    _taken: Callable[[str], frozenset[str]]
    _write: Callable[..., bool]
    _write_toml: Callable[..., bool]
    _live_config: Callable[[], str | None]
    config_text: Callable[[], str | None]
    _script_texts: Callable[[], dict[str, str]]
    select_category: Callable[[str], None]
    new_meter: Callable[[], bool]

    # --- + Meter ----------------------------------------------------------------------------

    def _found(self) -> Mapping[str, object]:
        """config.toml's values now ({} when it can't be read)."""
        return settingsmodel.values(self.config_text() or "") or {}

    def meter_menu(self) -> tk.Menu:
        """+ Meter's menu: the presets (the kit's, else ``metermodel.GENERAL``; one already
        in the game greyed out), then Blank meter…, and without a kit a link to the Kit
        page."""
        offers, kit = mm.offers(self._found())
        self.texts = self._script_texts()
        taken = {name.casefold() for name in self._taken(dec.METER)}
        menu = tk.Menu(self.root, tearoff=False)
        if kit is not None:
            menu.add_command(label=mm.KIT_OFFERS.format(kit=kit.name), state="disabled")
        for offer in offers:
            used = offer.name.casefold() in taken
            menu.add_command(label=mm.offer_text(offer, used),
                             state="disabled" if used else "normal",
                             command=lambda o=offer: self.new_meter_from(o))
        menu.add_separator()
        menu.add_command(label=mm.BLANK, command=self.new_meter)
        if kit is None:
            menu.add_separator()
            menu.add_command(label=mm.KIT_HINT + " ›", command=self.open_kit_page)
        self.last_menu = menu
        return menu

    def show_meter_menu(self) -> None:
        menu = self.meter_menu()
        button = self.new_button
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    def new_meter_from(self, offer: MeterSuggestion) -> bool:
        """Add a preset meter to database.vns, ready to use."""
        self.texts = self._script_texts()
        name = dec.script_name(offer.name, self._taken(dec.METER), dec.METER)
        self.select_category(db.CATEGORY_METER)
        return self._write(declplan.plan_new(dec.METER, name, mm.offer_values(offer),
                                             self.texts), select=f"m:{name}")

    def open_kit_page(self) -> None:
        self.win.show_tab(self.win.tab_index("settings"))
        self.win.settings.select_page("kits")

    # --- On screen --------------------------------------------------------------------------

    def _look_rows(self, outer: FormGrid, form: Any, entry: db.Entry,
                   values: Mapping[str, object]) -> Callable[[db.Entry, Mapping[str, object]],
                                                             None]:
        """The On screen caption, then the Look, Corner and Label rows (a grid of their own,
        so the preview beside them doesn't squeeze the rows above). Returns the function
        that shows them again for ``(entry, values)``."""
        f = form.fields
        state: dict[str, Any] = {"entry": entry, "values": values}
        found = self._found()
        own = mm.own(found, entry.name)
        look, place, _label = mm.fallback(found, entry.name)
        outer.caption(ON_SCREEN)
        box = ttk.Frame(outer.frame)
        box.grid(row=outer.next_row, column=0, columnspan=4, sticky="ew")
        outer.next_row += 1
        grid = FormGrid(box, scale=self.scale)
        grid.frame.grid(row=0, column=0, sticky="nw")

        def write(key: str) -> Callable[[object], object]:
            return lambda value: self._write_look(state["entry"], key, value)

        f["look"] = ChoiceField(grid.frame, self._look_choices(look), own["look"], width=15,
                                on_change=write("look"))
        rows: dict[str, FormRow] = {
            "look": grid.row(LABEL_LOOK, f["look"], on_default=lambda: write("look")(None))}
        f["corner"] = CornerPicker(grid.frame, own["place"], place, scale=self.scale,
                                   on_change=write("place"))
        rows["place"] = grid.row(LABEL_CORNER, f["corner"],
                                 on_default=lambda: write("place")(None))
        f["label"] = TextField(grid.frame, own["label"] or "", width=16,
                               on_change=write("label"))
        rows["label"] = grid.row(LABEL_SHOWN_AS, f["label"],
                                 on_default=lambda: write("label")(None),
                                 hint=mm.label_text(found, entry.name))
        hint = ttk.Label(grid.frame, style="Hint.TLabel", justify="left")
        hint.grid(row=grid.next_row, column=2, columnspan=2, sticky="w")
        grid.next_row += 1
        show_hint = ttk.Label(grid.frame, style="Hint.TLabel", justify="left")
        show_hint.grid(row=grid.next_row, column=2, columnspan=2, sticky="w",
                       pady=(0, self._px(4)))
        grid.next_row += 1
        side = ttk.Frame(box)
        side.grid(row=0, column=1, sticky="nw", padx=(self._px(16), 0), pady=(self._px(3), 0))
        f["preview_box"] = side

        def reflow(_event: object = None) -> None:
            """Beside the fields when the form is wide enough, else under them."""
            room = box.winfo_width()
            need = grid.frame.winfo_reqwidth() + side.winfo_reqwidth() + self._px(16)
            beside = room <= 1 or room >= need
            where = side.grid_info()
            if beside and int(where.get("row", 0)) != 0:
                side.grid(row=0, column=1, padx=(self._px(16), 0), pady=(self._px(3), 0))
            elif not beside and int(where.get("row", 0)) != 1:
                side.grid(row=1, column=0, padx=(self._px(110), 0),
                          pady=(self._px(8), 0))

        box.bind("<Configure>", reflow, add="+")
        canvas = tk.Canvas(side, width=self._px(PREVIEW_W), height=self._px(PREVIEW_H),
                           highlightthickness=0, background=THEME["editor.background"])
        canvas.pack()
        caption = ttk.Label(side, style="Hint.TLabel")
        caption.pack(anchor="w", pady=(self._px(4), 0))
        tiny, tiny_bold = meterdraw.fonts(canvas, self.fonts["small"], self.scale)
        painter = meterdraw.MeterPainter(canvas, self._px, tiny, tiny_bold,
                                         meter_width=PREVIEW_METER_W)
        f["preview"], f["preview_caption"] = canvas, caption

        def show(new_entry: db.Entry, new_values: Mapping[str, object]) -> None:
            state["entry"], state["values"] = new_entry, new_values
            name = new_entry.name
            found = self._found()
            own = mm.own(found, name)
            look, place, _label = mm.fallback(found, name)
            f["look"].set_choices(self._look_choices(look))
            f["look"].set(own["look"])
            f["corner"].fallback = place
            f["corner"].set(own["place"])
            f["label"].set(own["label"] or "")
            for key, row in rows.items():
                row.changed(own[key] is not None)
            assert rows["label"].hint is not None
            rows["label"].hint.configure(text=mm.label_text(found, name))
            hint.configure(text=mm.default_text(found, name))
            show_hint.configure(text=SHOW_HINT.format(name=name))
            seen = mm.preview(found, name, new_values)
            canvas.delete("all")
            painter.stage(("meter_preview",), 0, 0, self._px(PREVIEW_W) - 1,
                          self._px(PREVIEW_H) - 1, seen.colors, seen.look, seen.place,
                          seen.label, meterdraw.Reading(seen.share, seen.number, seen.of,
                                                        seen.rank))
            caption.configure(text=seen.caption)

        show(entry, values)
        return show

    @staticmethod
    def _look_choices(fallback: str) -> list[tuple[object, str]]:
        return [(None, DEFAULT_SUFFIX.format(name=mm.LOOK_NAMES[fallback])),
                *((look, mm.LOOK_NAMES[look]) for look in METER_LOOKS)]

    def _write_look(self, entry: db.Entry, key: str, value: object) -> bool:
        """Set (or, with None or blank, clear) ``[meter.<name>] key`` as one undo step."""
        text = self._live_config()
        if text is None:
            show_error(self.root, CONFIG_BROKEN)
            return False
        plan = tomlpatch.plan_changes(
            text, mm.look_changes(entry.name, key, None if value is None else str(value)),
            title=LOOK_TITLE.format(name=entry.name), ref=CONFIG_REF, drop_empty=True)
        return self._write_toml(plan, select=f"m:{entry.name}")


__all__ = ["CornerPicker", "MeterSetup", "ON_SCREEN"]
