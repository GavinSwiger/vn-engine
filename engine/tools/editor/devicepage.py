"""Game settings ▸ Devices (F65 round 3; "Studio contacts and devices"): the page's widgets.

Why this module exists: an author sets how each device words and sounds a message (a
pigeon's "A grey bird lands on the sill.", its wing beats, "Arrived by pigeon") with fields,
and sees the arrival notice and a message drawn in the game's colors, instead of writing
``[device.<look>]`` by hand. The page lives in ``settingsview``'s form column, which only
calls ``DevicesPage(view, body)`` when the page is built and ``show()`` after each read of
``config.toml``.

One card per device (phone, letters, pigeon, radio, terminal, mind), the game's own device
first and marked ("The game's device (from the Fantasy kit)"): its name, a live preview
(the arrival notice over a message in that device's look: bubbles, paper, a sealed note, a
transcript with static, a green terminal, a thought's glow; ``devicemodel.preview``), and
the fields **Name**, **Arrival notice**, **Arrival sound** (a sound picker with ▶),
**Line above each message** and **Reads as**. A field left empty shows the engine's own
words in its hint. Every change is one ``tomlpatch`` plan through the view: one undo step
of ``config.toml``; **Use default** removes the line, and the table once it is empty.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any

from engine.core.config_schema import DeviceTable, config_fields
from engine.core.kits import DEVICE_LOOKS
from engine.core.palette import mix
from engine.tools.editor import devicemodel as dm
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor import tomlpatch
from engine.tools.editor.fieldwidgets import ChoiceField, FormGrid, FormRow, TextField
from engine.tools.editor.schemecards import fit_text
from engine.tools.editor.theme import ROLES, THEME

LABEL_WIDTH = 150
PREVIEW_W = 460                 # px at 100 %
PREVIEW_H = 172
NOTICE_H = 34


def rounded(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: float,
            **kw: Any) -> int:
    """A rounded rectangle (a smoothed polygon)."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    points = (x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
              x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)
    return canvas.create_polygon(points, smooth=True, **kw)


class DeviceCard:
    """One device's card: heading, preview and fields, inside ``parent``."""

    def __init__(self, page: "DevicesPage", parent: tk.Misc, look: str) -> None:
        self.page = page
        self.look = look
        view = page.view
        px = view._px
        self.frame = tk.Frame(parent, background=THEME["editor.background"],
                              highlightthickness=1, highlightbackground=THEME["border"])
        top = tk.Frame(self.frame, background=THEME["editor.background"])
        top.pack(fill="x", padx=px(12), pady=(px(10), px(4)))
        self.title = tk.Label(top, text=dm.LOOK_NAMES[look], font=view.win.fonts["bodyStrong"],
                              background=THEME["editor.background"], foreground=THEME["foreground"])
        self.title.pack(side="left")
        self.mark = tk.Label(top, text="", font=view.win.fonts["small"],
                             background=THEME["editor.background"], foreground=ROLES["accent"])
        self.mark.pack(side="left", padx=(px(10), 0))
        self.canvas = tk.Canvas(self.frame, width=px(PREVIEW_W), height=px(PREVIEW_H),
                                highlightthickness=0, background=THEME["editor.background"])
        self.canvas.pack(anchor="w", padx=px(12))
        family = view.win.fonts["small"].actual("family")
        size = -max(9, round(12 * view.scale))
        self.font = tkfont.Font(root=self.canvas, family=family, size=size)
        self.bold = tkfont.Font(root=self.canvas, family=family, size=size, weight="bold")
        self.italic = tkfont.Font(root=self.canvas, family=family, size=size, slant="italic")
        self.mono = tkfont.Font(root=self.canvas, family="Courier New", size=size)
        self.mono_bold = tkfont.Font(root=self.canvas, family="Courier New", size=size,
                                     weight="bold")
        self.rows: dict[str, FormRow] = {}
        self.inputs: dict[str, Any] = {}
        grid = self.grid = FormGrid(self.frame, scale=view.scale, label_width=LABEL_WIDTH)
        grid.frame.pack(fill="x", padx=px(12), pady=(px(6), px(10)))
        for key in ("name", "arrive_text"):
            self._text_row(key, 22 if key == "name" else 40)
        self._sound_row()
        self._text_row("header_text", 28)
        reading = ChoiceField(grid.frame, dm.reading_choices(look), None, width=28,
                              on_change=lambda value: self.set("reading", value))
        self._row("reading", reading)

    # --- Building --------------------------------------------------------------------------

    def _row(self, key: str, field: Any) -> FormRow:
        row = self.grid.row(dm.LABELS[key], field, hint=" ",
                            on_default=lambda k=key: self.set(k, None))
        row.label.configure(wraplength=self.page.view._px(LABEL_WIDTH - 12))
        if row.hint is not None:
            row.hint.configure(wraplength=self.page.view._px(380))
        self.rows[key] = row
        self.inputs[key] = field
        return row

    def _text_row(self, key: str, width: int) -> None:
        field = TextField(self.grid.frame, "", width=width,
                          on_change=lambda text, k=key: self.set(k, str(text)))
        self._row(key, field)

    def _sound_row(self) -> None:
        view = self.page.view
        found = self.page.field(self.look, "arrive_sound")
        widget = view._make_widget(self.grid.frame, found, None)
        widget.on_change = lambda value: self.set("arrive_sound", value)
        self._row("arrive_sound", widget)

    # --- Showing ---------------------------------------------------------------------------

    def show(self, found: dict, game_device: bool) -> None:
        own = dm.own(found, self.look)
        wrap = max(self.page.view._px(160), self.page.view._wrap - self.page.view._px(110))
        for key, row in self.rows.items():
            row.changed(own.get(key) is not None)
            hint = dm.HINTS[key]
            if own.get(key) is None and key != "reading":
                hint = f"{hint} {dm.engine_text(self.look, key)}."
            if row.hint is not None:
                row.hint.configure(text=hint, wraplength=wrap)
        for key in ("name", "arrive_text", "header_text"):
            value = own[key]
            self.inputs[key].set(value if isinstance(value, str) else "")
        sound = self.inputs["arrive_sound"]
        if hasattr(sound, "set_refs"):
            sound.set_refs(self.page.view._refs(self.page.field(self.look, "arrive_sound")))
        sound.set(own["arrive_sound"] if isinstance(own["arrive_sound"], str) else None)
        self.inputs["reading"].set(own["reading"])
        name = dm.words(found, self.look).name
        self.title.configure(text=name if name == dm.LOOK_NAMES[self.look]
                             else f"{name} ({dm.LOOK_NAMES[self.look]})")
        self.mark.configure(text=dm.default_note(found) if game_device else "")
        self.draw(dm.preview(found, self.look))

    # --- The preview -----------------------------------------------------------------------

    def draw(self, seen: dm.DevicePreview) -> None:
        canvas, px = self.canvas, self.page.view._px
        canvas.delete("all")
        c = seen.colors
        w, h = px(PREVIEW_W), px(PREVIEW_H)
        stage = mix(c.page, "#000000", 0.55)
        canvas.create_rectangle(0, 0, w, h, fill=stage, outline="", tags=("stage",))
        self._notice(seen, w, px)
        top = px(NOTICE_H + 18)
        x0, x1 = px(18), w - px(18)
        rounded(canvas, x0, top, x1, h + px(20), px(10), fill=c.page, outline=c.edge,
                tags=("panel",))
        self._message(seen, x0 + px(10), top + px(10), x1 - px(10), h - px(4))

    def _notice(self, seen: dm.DevicePreview, w: int, px) -> None:
        canvas, c, look = self.canvas, seen.colors, seen.look
        text = fit_text(seen.notice, w - px(90), self.font.measure)
        tw = self.font.measure(text)
        x1, y0 = w - px(10), px(8)
        x0, y1 = x1 - tw - px(28), y0 + px(NOTICE_H - 6)
        tags = ("notice",)
        fill = c.card if look in ("phone", "letters", "pigeon", "terminal") and c.card \
            else c.page
        if look == "mind":
            rounded(canvas, x0 - px(6), y0 - px(6), x1 + px(6), y1 + px(6), px(18),
                    fill=mix(c.page, c.accent, 0.25), outline="", tags=tags)
            rounded(canvas, x0, y0, x1, y1, px(14), fill=c.page, outline="", tags=tags)
        elif look == "phone":
            rounded(canvas, x0, y0, x1, y1, px(12), fill=fill, outline="", tags=tags)
            canvas.create_polygon(x0 + px(14), y1 - 1, x0 + px(24), y1 - 1, x0 + px(19),
                                  y1 + px(6), fill=fill, outline="", tags=tags)
        else:
            outline = c.edge
            canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline,
                                    width=2 if look == "terminal" else 1, tags=tags)
        if look == "letters":
            canvas.create_rectangle(x1 - px(12), y0 - px(5), x1 + px(2), y0 + px(11),
                                    fill=c.accent, outline=c.card or c.page, width=2,
                                    tags=tags)
        if look == "pigeon":
            canvas.create_rectangle(x0 + px(4), y0, x0 + px(6), y1, fill=c.mark, outline="",
                                    tags=tags)
            mid = (y0 + y1) / 2
            canvas.create_oval(x0 + px(0), mid - px(5), x0 + px(10), mid + px(5),
                               fill=c.accent, outline="", tags=tags)
        if look == "radio":
            self._static(x0 + px(8), y1 - px(4), x1 - x0 - px(16), c.mark, tags)
        if look == "terminal":
            canvas.create_rectangle(x1 - px(14), y1 - px(7), x1 - px(6), y1 - px(3),
                                    fill=c.text, outline="", tags=tags)
        font = self.mono if look == "terminal" else self.font
        canvas.create_text(x0 + px(14), (y0 + y1) / 2, anchor="w", text=text, font=font,
                           fill=c.text, tags=(*tags, "notice_text"))

    def _static(self, x: float, y: float, width: float, color: str, tags) -> None:
        px = self.page.view._px
        for i in range(int(width // px(4))):
            n = ((i * 374761393) ^ (i >> 3)) & 0xFFFF
            hh = px(1 + n % 5) / 2
            self.canvas.create_rectangle(x + i * px(4), y - hh, x + i * px(4) + 1, y + hh,
                                         fill=color, outline="", tags=tags)

    def _message(self, seen: dm.DevicePreview, x0: float, y0: float, x1: float,
                 bottom: float) -> None:
        canvas, c, look = self.canvas, seen.colors, seen.look
        px = self.page.view._px
        tags = ("message",)
        line = self.font.metrics("linespace")
        if look in ("letters", "pigeon", "terminal"):
            inset = px(60) if look == "pigeon" else 0
            cx0, cx1 = x0 + inset, x1 - inset
            if look == "terminal":
                canvas.create_rectangle(cx0, y0, cx1, bottom + px(30), fill=c.card,
                                        outline=c.edge, width=2, tags=tags)
            else:
                canvas.create_rectangle(cx0 + px(3), y0 + px(3), cx1 + px(3), bottom + px(33),
                                        fill=mix(c.page, c.edge, 0.5), outline="", tags=tags)
                canvas.create_rectangle(cx0, y0, cx1, bottom + px(30), fill=c.card,
                                        outline=c.edge, tags=tags)
            if look == "pigeon":
                canvas.create_rectangle(cx1 - px(22), y0, cx1 - px(19), bottom + px(30),
                                        fill=c.mark, outline="", tags=tags)
                canvas.create_oval(cx1 - px(29), y0 + px(8), cx1 - px(12), y0 + px(25),
                                   fill=c.accent, outline=c.card, tags=tags)
            x0, x1, y0 = cx0 + px(12), cx1 - px(12 if look != "pigeon" else 32), y0 + px(8)
        y = y0
        mono = look == "terminal"
        font = self.mono if mono else self.font
        bold = self.mono_bold if mono else self.bold
        room = x1 - x0
        head = fit_text(seen.header, room - (px(70) if look == "radio" else 0),
                        font.measure if mono else self.italic.measure)
        if look in ("letters", "mind", "phone"):
            canvas.create_text((x0 + x1) / 2, y, anchor="n", text=head,
                               font=font if mono else self.italic, fill=c.heading,
                               tags=(*tags, "header"))
        else:
            canvas.create_text(x0, y, anchor="nw", text=head,
                               font=font if mono else self.italic, fill=c.heading,
                               tags=(*tags, "header"))
        if look == "radio":
            canvas.create_text(x1, y, anchor="ne", text="[signal]", font=self.font,
                               fill=c.me_text, tags=(*tags, "signal"))
            self._static(x0, y + line + px(4), room, c.mark, tags)
            y += px(6)
        if look == "letters":
            mid = (x0 + x1) / 2
            canvas.create_line(mid - px(30), y + line + px(3), mid + px(30), y + line + px(3),
                               fill=c.heading, tags=tags)
            y += px(6)
        y += line + px(4)
        if look == "mind":
            canvas.create_rectangle(x0 + px(20), y - px(2), x1 - px(20), bottom + px(30),
                                    fill=mix(c.page, c.accent, 0.10), outline="", tags=tags)
        if look == "radio":
            canvas.create_line(x0 + px(2), y, x0 + px(2), bottom, fill=c.mark, width=2,
                               tags=tags)
            x0 += px(12)
        for name, text in seen.lines:
            if y + line > bottom:
                break
            if look == "phone":
                mine = name == dm.SAMPLE_ME
                body = fit_text(f"{name}: {text}", room * 0.72, self.font.measure)
                tw = self.font.measure(body) + px(16)
                bx0 = x1 - tw if mine else x0
                rounded(canvas, bx0, y, bx0 + tw, y + line + px(8), px(9),
                        fill=c.me_card if mine else c.card, outline="", tags=tags)
                canvas.create_text(bx0 + px(8), y + px(4), anchor="nw", text=body,
                                   font=self.font, fill=c.me_text if mine else c.text,
                                   tags=(*tags, "line"))
                y += line + px(14)
                continue
            x = x0
            if name:
                label = f"{name}: "
                canvas.create_text(x, y, anchor="nw", text=label, font=bold, fill=c.text,
                                   tags=(*tags, "line"))
                x += bold.measure(label)
            canvas.create_text(x, y, anchor="nw", text=fit_text(text, x1 - x, font.measure),
                               font=self.italic if look == "mind" else font, fill=c.text,
                               tags=(*tags, "line"))
            y += line + px(4)
        if seen.signature and y + line <= bottom + px(8):
            canvas.create_text(x1, y, anchor="ne", text=seen.signature, font=self.italic,
                               fill=c.text, tags=(*tags, "signature"))
        if look == "terminal":
            canvas.create_rectangle(x0, y + px(2), x0 + px(8), y + line - px(2), fill=c.text,
                                    outline="", tags=(*tags, "cursor"))

    # --- Writing ---------------------------------------------------------------------------

    def set(self, key: str, value: object) -> bool:
        return self.page.set(self.look, key, value)


class DevicesPage:
    """The Devices page inside ``body``, for the Game settings ``view``."""

    def __init__(self, view: Any, body: ttk.Frame) -> None:
        self.view = view
        px = view._px
        self._fields: dict[tuple[str, str], sm.Field] = {}
        self.order = self._order(view.found)
        self.cards: dict[str, DeviceCard] = {}
        for look in self.order:
            card = DeviceCard(self, body, look)
            card.frame.pack(fill="x", pady=(0, px(12)))
            self.cards[look] = card
        self.show()

    @staticmethod
    def _order(found: dict) -> tuple[str, ...]:
        first = dm.default_look(found)
        return (first, *(look for look in DEVICE_LOOKS if look != first))

    def field(self, look: str, key: str) -> sm.Field:
        found = self._fields.get((look, key))
        if found is None:
            found = self._fields[(look, key)] = sm._make_field(
                dm.section(look), key, config_fields(DeviceTable)[key])
        return found

    def show(self) -> None:
        """Every card from the open text: fields, hints, the marked device, previews."""
        if not self.cards or not next(iter(self.cards.values())).canvas.winfo_exists():
            return
        found = dict(self.view.found)
        game = dm.default_look(found)
        order = self._order(found)
        if order != self.order:                         # the game's device comes first
            self.order = order
            for look in order:
                self.cards[look].frame.pack_forget()
            for look in order:
                self.cards[look].frame.pack(fill="x", pady=(0, self.view._px(12)))
        for look, card in self.cards.items():
            card.show(found, look == game)

    def set(self, look: str, key: str, value: object) -> bool:
        """Write ``[device.<look>] key`` (None or blank: remove it, and the table once it is
        empty) as one undo step."""
        view = self.view
        text = view.config_text()
        if text is None:
            view.refresh()
            return False
        if isinstance(value, str):
            value = value.strip() or None
        if value is None and dm.own(view.found, look).get(key) is None \
                and f"{dm.section(look)}.{key}" not in view.found:
            view.refresh()
            return True
        plan = tomlpatch.plan_changes(text, dm.changes(look, key, value), drop_empty=True)
        return view._apply(plan, self.field(look, key))


__all__ = ["DeviceCard", "DevicesPage", "rounded"]
