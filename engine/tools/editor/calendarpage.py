"""Game settings ▸ Calendar (F63 round 2; specs/F63-story-clock/SPEC.md): the page's widgets.

Why this module exists: an author sets up story time (parts of the day, the start, the last
day, how dates read, the day card and the clock's corner) with fields and sees the result in
the game's colors, instead of writing ``[calendar]`` by hand. The page lives in
``settingsview``'s form column, which only calls ``CalendarPage(view, body)`` when the page is
built and ``show()`` after each read of ``config.toml``. Top to bottom:

- the load's warnings about ``[calendar]`` (a start it can't read, …), when there are any;
- **Parts of the day**: an editable list (type a name, Add; select one to Rename, Remove or
  move it; Delete removes it too). Unset, it shows the kit's or the engine's parts and
  says where they come from; the first change writes the whole list;
- **Story time**: Starts on (a day number or a date), Last day, How a date reads (its
  fields, and the start day as it reads);
- **On screen**: Card at a new day, Clock corner (``dbmeters.CornerPicker``);
- **Weekdays, months and seasons**, shown on demand (open by itself when one is set);
- at the top, in view while the first fields change: a live preview of the day card in
  the chapter card's colors and of the clock in its corner on a small stage in the game's
  scheme, side by side.

Every change is one ``tomlpatch`` plan through the view (``set_value``, ``use_default``,
``_apply``): one undo step of ``config.toml``; **Use default** removes the line.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any

from engine.tools.editor import calendarmodel as cm
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor.dbmeters import CornerPicker
from engine.tools.editor.fieldwidgets import FormGrid, FormRow, TextField, ToggleField
from engine.tools.editor.meterdraw import fonts as meter_fonts
from engine.tools.editor.schemecards import fit_text
from engine.tools.editor.theme import ROLES, THEME

LABEL_WIDTH = 150
PREVIEW_W = 208                 # px at 100 %: a 16:9 card and stage, side by side
PREVIEW_H = 117
PREVIEW_GAP = 16

PARTS = "Parts of the day"
IN_ORDER = "In order"
STORY_TIME = "Story time"
ON_SCREEN = "On screen"
MORE = "Weekdays, months and seasons"
SHOW_MORE, HIDE_MORE = "Show", "Hide"
LABELS = {"start": "Starts on", "last_day": "Last day", "day_text": "How a date reads",
          "day_card": "Card at a new day", "place": "Clock corner", "weekdays": "Weekdays",
          "months": "Months", "seasons": "Seasons", "season_days": "Days in a season"}
HINTS = {
    "start": "A day number, or a date such as Monday 1 April.",
    "last_day": "Optional: the day time runs out. clock.days_left() counts down to it.",
    "day_card": "The date fills the screen for a moment, like a chapter card.",
    "place": "Where show clock puts the date and the part of the day.",
    "weekdays": "Names, with commas between. Not set: Monday to Sunday.",
    "months": "Names, with commas between, for dates such as 1 April.",
    "seasons": "Names, with commas between, for dates such as Spring, day 4.",
    "season_days": "Not set: 28.",
}
ADD, RENAME, REMOVE, UP, DOWN = "Add", "Rename", "Remove", "Move up", "Move down"
PARTS_HINT = ("{source}. Type a name under the list and press Add, or change any, to make "
              "the list your own.")
PARTS_OWN = ("Type a name under the list and press Add, or select one to rename, remove "
             "or move it.")
CARD_LABEL = "Day card"
CORNER_LABEL = "Clock"


class CalendarPage:
    """The Calendar page inside ``body``, for the Game settings ``view``."""

    def __init__(self, view: Any, body: ttk.Frame) -> None:
        self.view = view
        px = view._px
        self.fields = sm.fields_by_path()
        self.rows: dict[str, FormRow] = {}
        self.inputs: dict[str, Any] = {}
        self.problem_box, inner = view._note_box(body, ROLES["warning"])
        self.problem_label = view._note_label(inner)
        # The preview first, so it stays in view while the first fields change.
        self.top = ttk.Frame(body)
        self.top.pack(fill="x", pady=(0, px(4)))
        line = view.win.fonts["small"].metrics("linespace")
        self.canvas = tk.Canvas(self.top, width=px(2 * PREVIEW_W + PREVIEW_GAP),
                                height=px(PREVIEW_H) + line + px(4), highlightthickness=0,
                                background=THEME["editor.background"])
        self.canvas.pack(anchor="w")
        tiny, tiny_bold = meter_fonts(self.canvas, view.win.fonts["small"], view.scale)
        self.tiny, self.tiny_bold = tiny, tiny_bold
        family = view.win.fonts["small"].actual("family")
        self.card_font = tkfont.Font(root=self.canvas, family=family, weight="bold",
                                     size=-max(10, round(16 * view.scale)))
        grid = self.grid = FormGrid(body, scale=view.scale, label_width=LABEL_WIDTH)
        grid.frame.pack(fill="x")
        self._parts(grid)
        grid.caption(STORY_TIME)
        self._text_row(grid, "start", 20, check=self._check_start)
        self._text_row(grid, "last_day", 8, check=self._check_day)
        self._text_row(grid, "day_text", 28)
        grid.caption(ON_SCREEN)
        card = ToggleField(grid.frame, "", True, on_change=lambda on: self._set("day_card", on))
        self._row(grid, "day_card", card)
        corner = CornerPicker(grid.frame, None, "top_right", scale=view.scale,
                              on_change=lambda place: self._set("place", place))
        self._row(grid, "place", corner)
        found = cm.own(view.found)
        self.more_open = any(found[key] is not None for key in cm.MORE_KEYS)
        self.more_button = grid.caption(MORE, button=(SHOW_MORE, self.toggle_more))
        self.more_rows: list[tk.Widget] = []
        first = grid.next_row
        for key in ("weekdays", "months", "seasons"):
            self._text_row(grid, key, 36, names=True)
        self._text_row(grid, "season_days", 8, check=self._check_count)
        self.more_rows = [w for w in grid.frame.grid_slaves()
                          if int(w.grid_info()["row"]) >= first]
        self.show()

    # --- Building ---------------------------------------------------------------------------

    def _row(self, grid: FormGrid, key: str, field: Any, hint: str = "") -> FormRow:
        row = grid.row(LABELS.get(key, IN_ORDER), field, hint=hint or HINTS.get(key, " "),
                       on_default=lambda k=key: self._set(k, None))
        row.label.configure(wraplength=self.view._px(LABEL_WIDTH - 12))
        if row.hint is not None:
            row.hint.configure(wraplength=self.view._px(360))
        self.rows[key] = row
        self.inputs[key] = field
        return row

    def _text_row(self, grid: FormGrid, key: str, width: int, *, names: bool = False,
                  check: Any = None) -> None:
        if names:
            def checked(text: str, k: str = key) -> bool:
                found = cm.names_of(text)
                return not found or cm.check_names(k, found)
            check = checked
        field = TextField(grid.frame, "", width=width, check=check,
                          on_change=lambda text, k=key: self._set_text(k, str(text)))
        self._row(grid, key, field)

    def _parts(self, grid: FormGrid) -> None:
        px = self.view._px
        box = ttk.Frame(grid.frame)
        self.parts_list = tk.Listbox(box, height=7, width=22, exportselection=False,
                                     activestyle="none")
        self.parts_list.grid(row=0, column=0, sticky="nw")
        self.parts_list.bind("<<ListboxSelect>>", lambda _e: self._picked_part(), add="+")
        self.parts_list.bind("<Delete>", lambda _e: self.remove_part(), add="+")
        buttons = ttk.Frame(box)
        buttons.grid(row=0, column=1, sticky="nw", padx=(px(8), 0))
        self.part_buttons = {}
        for name, command in ((ADD, self.add_part), (RENAME, self.rename_part),
                              (UP, lambda: self.move_part(-1)),
                              (DOWN, lambda: self.move_part(1)), (REMOVE, self.remove_part)):
            button = ttk.Button(buttons, text=name, style="Secondary.TButton",
                                command=command)
            button.pack(fill="x", pady=(0, px(2)))
            self.part_buttons[name] = button
        self.part_var = tk.StringVar(master=self.view.root)
        self.part_entry = ttk.Entry(box, textvariable=self.part_var, width=22)
        self.part_entry.grid(row=1, column=0, sticky="ew", pady=(px(6), 0))
        for key in ("<Return>", "<KP_Enter>"):
            self.part_entry.bind(key, lambda _e: (self.add_part(), "break")[1], add="+")
        grid.caption(PARTS)
        self._row(grid, "parts", box)

    # --- Showing ----------------------------------------------------------------------------

    def show(self) -> None:
        """The page's state from the open text: every field, the warnings, the preview."""
        if not self.canvas.winfo_exists():
            return
        found = self.view.found
        own = cm.own(found)
        cal = cm.calendar(found)
        for key, row in self.rows.items():
            row.changed(own.get(key) is not None)
        parts = list(cal.parts)
        if list(self.parts_list.get(0, "end")) != parts:
            keep = self.parts_list.curselection()
            self.parts_list.delete(0, "end")
            for name in parts:
                self.parts_list.insert("end", name)
            if keep and keep[0] < len(parts):
                self.parts_list.selection_set(keep[0])
        self.parts_list.configure(foreground=THEME["foreground"] if own["parts"] is not None
                                  else THEME["muted"])
        hint = PARTS_OWN if own["parts"] is not None else PARTS_HINT.format(
            source=cm.source(found, "parts"))
        self._hint("parts", hint)
        self._picked_part()
        start = own["start"]
        self.inputs["start"].set("" if start is None else str(start))
        self._hint("start", f"{HINTS['start']} {cm.READS.format(text=cal.date(cal.start_day))}")
        self.inputs["last_day"].set("" if own["last_day"] is None else str(own["last_day"]))
        text = own["day_text"]
        self.inputs["day_text"].set(text if isinstance(text, str) else "")
        source = "" if text is not None else f"{cm.source(found, 'day_text')}. "
        self._hint("day_text", f"{source}{cm.fields_hint(cal)} "
                               f"{cm.READS.format(text=cal.date(cal.start_day + 3))}")
        self.inputs["day_card"].set(cal.day_card)
        picker = self.inputs["place"]
        picker.fallback = cm.calendar({k: v for k, v in found.items()
                                       if k != f"{cm.SECTION}.place"}).place
        picker.set(own["place"])
        self._hint("place", HINTS["place"] if own["place"] is not None
                   else f"{HINTS['place']} {cm.source(found, 'place')}.")
        for key in ("weekdays", "months", "seasons"):
            self.inputs[key].set(cm.names_text(own[key]))
        days = own["season_days"]
        self.inputs["season_days"].set("" if days is None else str(days))
        self._show_more()
        problems = cm.problems(found)
        if problems:
            self.problem_label.configure(text=" ".join(problems))
            self.problem_box.pack(fill="x", pady=(0, self.view._px(8)), before=self.top)
        else:
            self.problem_box.pack_forget()
        self.draw(cm.preview(found))

    def _hint(self, key: str, text: str) -> None:
        hint = self.rows[key].hint
        if hint is not None:
            hint.configure(text=text)

    def toggle_more(self) -> None:
        self.more_open = not self.more_open
        self._show_more()

    def _show_more(self) -> None:
        if self.more_button is not None:
            self.more_button.configure(text=HIDE_MORE if self.more_open else SHOW_MORE)
        for widget in self.more_rows:
            if self.more_open:
                widget.grid()
            else:
                widget.grid_remove()

    # --- The preview ------------------------------------------------------------------------

    def draw(self, seen: cm.CalendarPreview) -> None:
        canvas, px = self.canvas, self.view._px
        canvas.delete("all")
        w, h = px(PREVIEW_W), px(PREVIEW_H)
        line = self.tiny.metrics("linespace")
        # The day card, on the left.
        canvas.create_text(0, 0, anchor="nw", text=CARD_LABEL.upper(), font=self.tiny_bold,
                           fill=THEME["muted"], tags=("caption",))
        top = line + px(4)
        if seen.card_on:
            canvas.create_rectangle(0, top, w - 1, top + h - 1, fill=seen.card_fill,
                                    outline=THEME["border"], tags=("card",))
            canvas.create_text(w // 2, top + h // 2, text=fit_text(
                seen.card, w - px(16), self.card_font.measure), font=self.card_font,
                fill=seen.card_text, tags=("card", "card_text"))
        else:
            canvas.create_rectangle(0, top, w - 1, top + h - 1, fill=THEME["card.background"],
                                    outline=THEME["border"], dash=(3, 3), tags=("card",))
            canvas.create_text(w // 2, top + h // 2, text=seen.card_caption,
                               font=self.tiny, fill=THEME["muted"], width=w - px(16),
                               justify="center", tags=("card", "card_off"))
        # The stage with the clock in its corner, on the right.
        x0 = w + px(PREVIEW_GAP)
        canvas.create_text(x0, 0, anchor="nw", text=CORNER_LABEL.upper(),
                           font=self.tiny_bold, fill=THEME["muted"], tags=("caption",))
        top2 = top
        fill, text, border, accent, soft, _track = seen.colors
        canvas.create_rectangle(x0, top2, x0 + w - 1, top2 + h - 1, fill=soft,
                                outline=THEME["border"], tags=("stage",))
        box_top = top2 + h - px(30)
        canvas.create_rectangle(x0 + px(5), box_top, x0 + w - px(6), top2 + h - px(5),
                                fill=fill, outline=border, tags=("stage",))
        canvas.create_rectangle(x0 + px(12), box_top - px(5), x0 + px(44), box_top + px(2),
                                fill=accent, outline="", tags=("stage",))
        for n, share in enumerate((0.7, 0.45)):
            y = box_top + px(9 + 7 * n)
            canvas.create_rectangle(x0 + px(12), y, x0 + px(12) + round((w - px(30)) * share),
                                    y + px(2), fill=text, outline="", tags=("stage",))
        room = round(w * 0.45)
        date = fit_text(seen.date, room, self.tiny_bold.measure)
        part = fit_text(seen.part, room, self.tiny.measure)
        width = max(self.tiny_bold.measure(date), self.tiny.measure(part)) + px(12)
        height = 2 * line + px(8)
        inset = px(6)
        left = x0 + inset if seen.place.endswith("left") else x0 + w - inset - width
        y0 = top2 + inset if seen.place.startswith("top") else box_top - px(8) - height
        tags = ("clock", f"place:{seen.place}")
        canvas.create_rectangle(left, y0, left + width, y0 + height, fill=fill, outline=border,
                                tags=tags)
        right = seen.place.endswith("right")
        x = left + width - px(6) if right else left + px(6)
        anchor = "ne" if right else "nw"
        canvas.create_text(x, y0 + px(4), anchor=anchor, text=date, font=self.tiny_bold,
                           fill=text, tags=(*tags, "clock_date"))
        canvas.create_text(x, y0 + px(4) + line, anchor=anchor, text=part, font=self.tiny,
                           fill=text, tags=(*tags, "clock_part"))

    # --- Writing ----------------------------------------------------------------------------

    def _field(self, key: str) -> sm.Field:
        return self.fields[f"{cm.SECTION}.{key}"]

    def _set(self, key: str, value: object) -> bool:
        """Write ``[calendar] key`` (None: Use default) as one undo step."""
        field = self._field(key)
        if value is None:
            if cm.own(self.view.found).get(key) is None:
                self.view.refresh()
                return True
            return self.view.use_default(field)
        return self.view.set_value(field, value)

    def _set_text(self, key: str, text: str) -> bool:
        if key in ("weekdays", "months", "seasons"):
            names = cm.names_of(text)
            return self._set(key, names or None)
        if key == "start":
            return self._set(key, cm.start_value(text))
        if key in ("last_day", "season_days"):
            text = text.strip()
            return self._set(key, int(text) if text else None)
        return self._set(key, text.strip() or None)

    @staticmethod
    def _check_start(text: str) -> bool:
        value = cm.start_value(text)
        return value is None or not isinstance(value, int) or 1 <= value <= 99_999

    @staticmethod
    def _check_day(text: str) -> bool:
        text = text.strip()
        return not text or (text.isdigit() and 1 <= int(text) <= 99_999)

    @staticmethod
    def _check_count(text: str) -> bool:
        text = text.strip()
        return not text or (text.isdigit() and 1 <= int(text) <= 400)

    # --- The parts list ---------------------------------------------------------------------

    def parts(self) -> list[str]:
        return list(cm.calendar(self.view.found).parts)

    def _selected(self) -> int | None:
        found = self.parts_list.curselection()
        return found[0] if found else None

    def _picked_part(self) -> None:
        index = self._selected()
        count = self.parts_list.size()
        on = {UP: index is not None and index > 0,
              DOWN: index is not None and index < count - 1,
              REMOVE: index is not None and count > 1, RENAME: index is not None, ADD: True}
        for name, button in self.part_buttons.items():
            button.configure(state="normal" if on[name] else "disabled")
        if index is not None and self.part_var.get().strip() in ("", *self.parts_list.get(
                0, "end")):
            self.part_var.set(self.parts_list.get(index))

    def _write_parts(self, parts: list[str], select: int | None) -> bool:
        if not cm.check_names("parts", parts):
            self.part_entry.bell()
            return False
        done = self._set("parts", parts)
        if done and select is not None and select < self.parts_list.size():
            self.parts_list.selection_clear(0, "end")
            self.parts_list.selection_set(select)
            self.parts_list.see(select)
            self._picked_part()
        return done

    def add_part(self, name: str | None = None) -> bool:
        """Add: the typed name (``name``: tests) after the selected part, or at the end."""
        name = " ".join((self.part_var.get() if name is None else name).split())
        if not name:
            self.part_entry.bell()
            return False
        parts = self.parts()
        index = self._selected()
        at = len(parts) if index is None else index + 1
        parts.insert(at, name)
        if self._write_parts(parts, at):
            self.part_var.set("")
            return True
        return False

    def rename_part(self, name: str | None = None) -> bool:
        index = self._selected()
        name = " ".join((self.part_var.get() if name is None else name).split())
        if index is None or not name:
            self.part_entry.bell()
            return False
        parts = self.parts()
        parts[index] = name
        return self._write_parts(parts, index)

    def remove_part(self) -> bool:
        index = self._selected()
        parts = self.parts()
        if index is None or len(parts) < 2:
            return False
        del parts[index]
        self.part_var.set("")
        return self._write_parts(parts, min(index, len(parts) - 1))

    def move_part(self, step: int) -> bool:
        index = self._selected()
        parts = self.parts()
        if index is None or not 0 <= index + step < len(parts):
            return False
        parts[index], parts[index + step] = parts[index + step], parts[index]
        return self._write_parts(parts, index + step)


__all__ = ["CalendarPage", "LABELS"]
