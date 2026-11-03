"""Studio's shared field widgets (F47 ``04-technical.md`` §3.2; design §6.2, §6.3, UI-F47-01..03).

Why this module exists: the Database (W2/W3), Game settings (W4) and the statement forms'
pickers (W5) all edit one value per field and apply it the moment the author leaves the
field, with no OK button (RPG Maker's Database). Each field here owns one value, shows it,
and calls ``on_change(value)`` once per real change: on Enter, on focus-out, or on a pick.
``set(value)`` shows a value without calling back. ``FormGrid`` lays fields out in rows
(label, field, optional **Use default**) with the 2 px accent "changed" bar at the left edge.

- ``TextField``: one line of text.
- ``NumberField``: a spinbox clamped to ``lo``..``hi`` (whole numbers or decimals).
- ``ColorField``: a colour swatch, its ``#rrggbb`` text and **Pick…** (Enter or a click on the
  swatch opens the system colour picker, ``ask_color``); optionally "Default" (None).
- ``ChoiceField``: a read-only drop-down of (value, label) pairs.
- ``ToggleField``: a check box.
- ``AssetPicker``: a drop-down of asset refs with a ▶/■ button (sounds) or a thumbnail
  (pictures) beside it.
- ``Gallery``: a wrapping grid of 96 px thumbnails letterboxed on ``raised`` with each name
  under it in ``small`` (UI-F47-03); arrows move, Enter activates.
- ``ScrollFrame``: a frame that scrolls vertically (a long form).
- ``color_dot``: a small round swatch image for list rows.

Every colour comes from ``theme.THEME`` and every size is px at 100 % times ``scale``.
Imports only the standard library and ``theme``.
"""

import re
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from tkinter import colorchooser, ttk
from tkinter import font as tkfont

from engine.tools.editor.theme import ROLES, THEME

HEX = re.compile(r"#[0-9A-Fa-f]{6}")
USE_DEFAULT = "Use default"
PICK = "Pick…"
DEFAULT_COLOR = "Default"
NONE_CHOICE = "None"
PLAY = "▶"
STOP = "■"
PLAY_TIP = "Play"
STOP_TIP = "Stop"
CHANGED_BAR_PX = 2
SWATCH_PX = 20
THUMB_PX = 96
GALLERY_GAP_PX = 12
GALLERY_LABEL_PX = 18


def ask_color(parent: tk.Misc, initial: str | None) -> str | None:
    """The system colour picker; ``#rrggbb`` (lower case) or None when cancelled."""
    try:
        _rgb, chosen = colorchooser.askcolor(color=initial or "#ffffff", parent=parent)
    except tk.TclError:
        return None
    if not chosen:
        return None
    chosen = str(chosen)
    return chosen.lower() if HEX.fullmatch(chosen) else None


def _px(value: float, scale: float) -> int:
    return max(1, round(value * scale))


class _Field:
    """One value and its change callback; subclasses show it in ``widget``."""

    widget: tk.Widget

    def __init__(self, value: object, on_change: Callable[[object], object] | None) -> None:
        self.value = value
        self.on_change = on_change

    def set(self, value: object) -> None:
        """Show ``value`` without calling ``on_change``."""
        self.value = value
        self._show()

    def _show(self) -> None:
        raise NotImplementedError

    def _commit(self, value: object) -> None:
        if value == self.value and type(value) is type(self.value):
            return
        self.value = value
        if self.on_change is not None:
            self.on_change(value)

    def enable(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        try:
            self.widget.configure(state=state)
        except tk.TclError:
            pass


def _commit_keys(widget: tk.Widget, commit: Callable[[], object]) -> None:
    for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
        widget.bind(key, lambda _e: commit(), add="+")


class TextField(_Field):
    """One line of text; ``check(text)`` may refuse a value (the old one comes back)."""

    def __init__(self, parent: tk.Misc, value: str = "", *,
                 on_change: Callable[[object], object] | None = None, width: int = 24,
                 check: Callable[[str], bool] | None = None) -> None:
        super().__init__(value, on_change)
        self.var = tk.StringVar(master=parent, value=value)
        self.widget = self.entry = ttk.Entry(parent, textvariable=self.var, width=width)
        self.check = check
        _commit_keys(self.entry, self._done)
        self.entry.bind("<Escape>", lambda _e: self._show(), add="+")

    def _show(self) -> None:
        self.var.set(str(self.value))

    def _done(self) -> None:
        text = self.var.get()
        if self.check is not None and not self.check(text):
            self.entry.bell()
            self._show()
            return
        self._commit(text)


class NumberField(_Field):
    """A spinbox clamped to ``lo``..``hi``; ``whole`` numbers are ints, else floats."""

    def __init__(self, parent: tk.Misc, value: float, *, lo: float, hi: float,
                 step: float = 1, whole: bool = True,
                 on_change: Callable[[object], object] | None = None, width: int = 6) -> None:
        super().__init__(value, on_change)
        self.lo, self.hi, self.whole = lo, hi, whole
        self.var = tk.StringVar(master=parent, value=self._text(value))
        self.widget = self.spin = ttk.Spinbox(parent, from_=lo, to=hi, increment=step,
                                              textvariable=self.var, width=width,
                                              command=self._done)
        _commit_keys(self.spin, self._done)

    def _text(self, value: object) -> str:
        if self.whole:
            return str(int(value))                                    # type: ignore[call-overload]
        return f"{float(value):g}"                                    # type: ignore[arg-type]

    def _show(self) -> None:
        self.var.set(self._text(self.value))

    def _done(self) -> None:
        try:
            number = float(self.var.get().strip())
        except ValueError:
            self.spin.bell()
            self._show()
            return
        number = min(self.hi, max(self.lo, number))
        value: float = int(round(number)) if self.whole else round(number, 3)
        self.var.set(self._text(value))
        self._commit(value)


class ColorField(_Field):
    """A swatch, its hex text and **Pick…**. With ``allow_none`` an empty text is None,
    shown as ``none_text`` with a crossed-out swatch."""

    def __init__(self, parent: tk.Misc, value: str | None, *,
                 on_change: Callable[[object], object] | None = None,
                 allow_none: bool = False, none_text: str = DEFAULT_COLOR,
                 scale: float = 1.0) -> None:
        super().__init__(value, on_change)
        self.allow_none, self.none_text = allow_none, none_text
        self.widget = self.frame = ttk.Frame(parent)
        side = _px(SWATCH_PX, scale)
        self.swatch = tk.Canvas(self.frame, width=side, height=side, highlightthickness=1,
                                highlightbackground=THEME["border"],
                                highlightcolor=THEME["focusBorder"], borderwidth=0,
                                background=THEME["input.background"], takefocus=1,
                                cursor="hand2")
        self.swatch.pack(side="left")
        self.var = tk.StringVar(master=parent)
        self.entry = ttk.Entry(self.frame, textvariable=self.var, width=9)
        self.entry.pack(side="left", padx=(_px(8, scale), 0))
        self.button = ttk.Button(self.frame, text=PICK, command=self.pick, width=6,
                                 style="Secondary.TButton")
        self.button.pack(side="left", padx=(_px(8, scale), 0))
        self.hint = ttk.Label(self.frame, text="", style="Hint.TLabel")
        self.hint.pack(side="left", padx=(_px(8, scale), 0))
        self.side = side
        _commit_keys(self.entry, self._typed)
        self.entry.bind("<Escape>", lambda _e: self._show(), add="+")
        for key in ("<Return>", "<KP_Enter>", "<space>", "<Button-1>"):
            self.swatch.bind(key, lambda _e: (self.pick(), "break")[1])
        self._show()

    def _show(self) -> None:
        value = self.value if isinstance(self.value, str) else None
        self.var.set(value or "")
        self.hint.configure(text=self.none_text if value is None and self.allow_none else "")
        canvas, side = self.swatch, self.side
        canvas.delete("all")
        if value is not None:
            canvas.create_rectangle(0, 0, side + 1, side + 1, fill=value, outline="")
        else:
            canvas.create_line(2, side - 2, side - 2, 2, fill=THEME["muted"], width=1)

    def _typed(self) -> None:
        text = self.var.get().strip()
        if not text and self.allow_none:
            self._commit(None)
            self._show()
            return
        if not text.startswith("#"):
            text = "#" + text
        if not HEX.fullmatch(text):
            self.entry.bell()
            self._show()
            return
        self._commit(text.lower())
        self._show()

    def pick(self) -> None:
        if str(self.button.cget("state")) == "disabled":
            return
        chosen = ask_color(self.swatch, self.value if isinstance(self.value, str) else None)
        if chosen is not None:
            self._commit(chosen)
            self._show()

    def enable(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        self.entry.configure(state=state)
        self.button.configure(state=state)


class ChoiceField(_Field):
    """A read-only drop-down of ``(value, label)`` choices."""

    def __init__(self, parent: tk.Misc, choices: Sequence[tuple[object, str]], value: object,
                 *, on_change: Callable[[object], object] | None = None,
                 width: int = 18) -> None:
        super().__init__(value, on_change)
        self.choices = list(choices)
        self.var = tk.StringVar(master=parent)
        self.widget = self.box = ttk.Combobox(parent, textvariable=self.var, state="readonly",
                                              width=width,
                                              values=[label for _v, label in self.choices])
        self.box.bind("<<ComboboxSelected>>", lambda _e: self._picked(), add="+")
        self._show()

    def set_choices(self, choices: Sequence[tuple[object, str]]) -> None:
        self.choices = list(choices)
        self.box.configure(values=[label for _v, label in self.choices])
        self._show()

    def label_of(self, value: object) -> str:
        for choice, label in self.choices:
            if choice == value and type(choice) is type(value):
                return label
        return "" if value is None else str(value)

    def _show(self) -> None:
        self.var.set(self.label_of(self.value))

    def _picked(self) -> None:
        index = self.box.current()
        if 0 <= index < len(self.choices):
            self._commit(self.choices[index][0])
        self.box.selection_clear()

    def pick(self, value: object) -> None:
        """Pick ``value`` as the author would (tests, keyboard helpers)."""
        self._commit(value)
        self._show()

    def enable(self, on: bool) -> None:
        self.box.configure(state="readonly" if on else "disabled")


class ToggleField(_Field):
    """A check box."""

    def __init__(self, parent: tk.Misc, text: str, value: bool, *,
                 on_change: Callable[[object], object] | None = None) -> None:
        super().__init__(bool(value), on_change)
        self.var = tk.BooleanVar(master=parent, value=bool(value))
        self.widget = self.check = ttk.Checkbutton(parent, text=text, variable=self.var,
                                                   command=lambda: self._commit(
                                                       bool(self.var.get())))

    def _show(self) -> None:
        self.var.set(bool(self.value))


class AssetPicker(ChoiceField):
    """A drop-down of asset refs (``none_text`` first: None) with ▶/■ (``play(ref)``, for
    sounds) or a thumbnail (``thumb(ref) -> PhotoImage | None``, for pictures) beside it."""

    def __init__(self, parent: tk.Misc, refs: Sequence[str], value: str | None, *,
                 on_change: Callable[[object], object] | None = None,
                 none_text: str = NONE_CHOICE,
                 play: Callable[[str], object] | None = None,
                 thumb: Callable[[str], object] | None = None,
                 width: int = 26, scale: float = 1.0) -> None:
        self.frame = ttk.Frame(parent)
        self.none_text = none_text
        super().__init__(self.frame, self._choices(refs), value, on_change=on_change,
                         width=width)
        self.box.pack(side="left")
        self.widget = self.frame
        self.play_button: ttk.Button | None = None
        self.picture: ttk.Label | None = None
        self.thumb = thumb
        self.play = play
        if play is not None:
            self.play_button = ttk.Button(self.frame, text=PLAY, width=3,
                                          command=self._play, style="Secondary.TButton")
            self.play_button.pack(side="left", padx=(_px(8, scale), 0))
        if thumb is not None:
            self.picture = ttk.Label(self.frame)
            self.picture.pack(side="left", padx=(_px(8, scale), 0))
        self._show()

    def _choices(self, refs: Sequence[str]) -> list[tuple[object, str]]:
        return [(None, self.none_text), *((ref, ref) for ref in refs)]

    def set_refs(self, refs: Sequence[str]) -> None:
        self.set_choices(self._choices(refs))

    def _show(self) -> None:
        super()._show()
        picture = getattr(self, "picture", None)
        if picture is not None and self.thumb is not None:
            image = self.thumb(self.value) if isinstance(self.value, str) else None
            picture.configure(image=image or "")
            picture.image = image                                     # type: ignore[attr-defined]
        button = getattr(self, "play_button", None)
        if button is not None:
            button.configure(state="normal" if isinstance(self.value, str) else "disabled")

    def _picked(self) -> None:
        super()._picked()
        self._show()

    def _play(self) -> None:
        if self.play is not None and isinstance(self.value, str):
            self.play(self.value)

    def set_playing(self, on: bool) -> None:
        """▶ while nothing plays, ■ while this picker's sound plays."""
        if self.play_button is not None:
            self.play_button.configure(text=STOP if on else PLAY)

    def enable(self, on: bool) -> None:
        super().enable(on)
        if self.play_button is not None:
            self.play_button.configure(
                state="normal" if on and isinstance(self.value, str) else "disabled")


# --- Layout ---------------------------------------------------------------------------------

class FormGrid:
    """Rows of (changed bar, label, field, **Use default**) on ``parent``, plus captions.
    ``row`` returns the row's ``FormRow``. ``tips``: label → its plain-words hint, shown as
    the label's tooltip (F47 P3-D: ``fieldhints.database_tips``)."""

    def __init__(self, parent: tk.Misc, *, scale: float = 1.0,
                 label_width: int = 110, tips: Mapping[str, str] | None = None) -> None:
        self.frame = ttk.Frame(parent)
        self.scale = scale
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(1, minsize=_px(label_width, scale))
        self.next_row = 0
        self.tips = tips or {}
        self.tooltips: dict[str, object] = {}           # label → its Tooltip

    def caption(self, text: str, *, button: tuple[str, Callable[[], object]] | None = None
                ) -> ttk.Button | None:
        """An upper-case section caption (the panel-header style), with an optional ghost
        button at its right."""
        top = _px(16 if self.next_row else 0, self.scale)
        line = ttk.Frame(self.frame)
        line.grid(row=self.next_row, column=1, columnspan=3, sticky="ew",
                  pady=(top, _px(6, self.scale)))
        ttk.Label(line, text=text.upper(), style="Caption.TLabel").pack(side="left")
        made = None
        if button is not None:
            made = ttk.Button(line, text=button[0], command=button[1], style="Ghost.TButton")
            made.pack(side="right")
        self.next_row += 1
        return made

    def row(self, label: str, field: _Field | tk.Widget, *,
            on_default: Callable[[], object] | None = None,
            hint: str | None = None) -> "FormRow":
        r, px = self.next_row, self.scale
        bar = tk.Frame(self.frame, width=_px(CHANGED_BAR_PX, px), background=THEME[
            "editor.background"])
        bar.grid(row=r, column=0, sticky="ns", padx=(0, _px(6, px)), pady=_px(3, px))
        text = ttk.Label(self.frame, text=label)
        text.grid(row=r, column=1, sticky="w", pady=_px(3, px), padx=(0, _px(12, px)))
        if self.tips.get(label):
            from engine.tools.editor.playbar import Tooltip     # playbar imports dialogs
            self.tooltips[label] = Tooltip(text, self.tips[label])
        widget = field.widget if isinstance(field, _Field) else field
        widget.grid(row=r, column=2, sticky="w", pady=_px(3, px))
        default = None
        if on_default is not None:
            default = ttk.Button(self.frame, text=USE_DEFAULT, command=on_default,
                                 style="Ghost.TButton")
            default.grid(row=r, column=3, sticky="e", padx=(_px(8, px), 0))
        self.next_row += 1
        hint_label = None
        if hint:
            hint_label = ttk.Label(self.frame, text=hint, style="Hint.TLabel", justify="left")
            hint_label.grid(row=self.next_row, column=2, columnspan=2, sticky="w",
                            pady=(0, _px(4, px)))
            self.next_row += 1
        return FormRow(bar, text, field, default, hint_label)

    def widget(self, widget: tk.Widget, *, pady: tuple[int, int] = (4, 4)) -> tk.Widget:
        """A whole-width widget (a gallery, a message) as the next row."""
        widget.grid(row=self.next_row, column=1, columnspan=3, sticky="ew",
                    pady=tuple(_px(p, self.scale) if p else 0 for p in pady))
        self.next_row += 1
        return widget


class FormRow:
    """One ``FormGrid`` row: ``changed(on)`` shows the 2 px accent bar and enables **Use
    default**."""

    def __init__(self, bar: tk.Frame, label: ttk.Label, field: object,
                 default: ttk.Button | None, hint: ttk.Label | None) -> None:
        self.bar, self.label, self.field, self.default, self.hint = \
            bar, label, field, default, hint

    def changed(self, on: bool) -> None:
        self.bar.configure(background=ROLES["accent"] if on else THEME["editor.background"])
        if self.default is not None:
            self.default.configure(state="normal" if on else "disabled")


class ScrollFrame:
    """``frame`` (the outer widget) scrolls ``inner`` vertically; the bar hides when not
    needed and the mouse wheel scrolls while the pointer is over it."""

    def __init__(self, parent: tk.Misc, *, background: str | None = None) -> None:
        back = background or THEME["editor.background"]
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.frame, background=back, highlightthickness=0,
                                borderwidth=0, takefocus=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._set_bar)
        self.inner.bind("<Configure>", lambda _e: self._fit(), add="+")
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfigure(
            self._window, width=e.width), self._fit()), add="+")
        for widget in (self.canvas, self.inner):
            widget.bind("<Enter>", lambda _e: self._wheel(True), add="+")
            widget.bind("<Leave>", lambda _e: self._wheel(False), add="+")

    def _fit(self) -> None:
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(),
                                            self.inner.winfo_reqheight()))

    def _set_bar(self, first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.bar.grid_remove()
        else:
            self.bar.grid(row=0, column=1, sticky="ns")
        self.bar.set(first, last)

    def _wheel(self, on: bool) -> None:
        if on:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event: tk.Event) -> None:
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def top(self) -> None:
        self.canvas.yview_moveto(0)


# --- Images ----------------------------------------------------------------------------------

def color_dot(master: tk.Misc, color: str | None, px: int) -> tk.PhotoImage:
    """A ``px`` round dot in ``color`` (a muted ring for None) on a clear background."""
    image = tk.PhotoImage(master=master, width=px, height=px)
    r = px / 2 - 0.5
    ring = color is None
    fill = THEME["muted"] if ring else color
    for y in range(px):
        row = []
        for x in range(px):
            d = ((x - r) ** 2 + (y - r) ** 2) ** 0.5
            inside = d <= r - 0.3 and (not ring or d >= r - 1.6)
            row.append(fill if inside else None)
        for x, c in enumerate(row):
            if c is not None:
                image.put(c, (x, y))
    return image


class Gallery:
    """A wrapping grid of thumbnail cells: a ``thumb`` px square on ``raised`` with the
    picture centred (letterboxed) and its label under it. ``set_items([(key, label)])``,
    ``set_image(key, photo)``; a click or the arrows select (``on_select(key)``), Enter or a
    double-click activates (``on_activate(key)``)."""

    def __init__(self, parent: tk.Misc, *, scale: float = 1.0, thumb: int = THUMB_PX,
                 font: tkfont.Font | None = None,
                 on_select: Callable[[str], object] | None = None,
                 on_activate: Callable[[str], object] | None = None,
                 empty_text: str = "") -> None:
        self.scale = scale
        self.side = _px(thumb, scale)
        self.gap = _px(GALLERY_GAP_PX, scale)
        self.label_h = _px(GALLERY_LABEL_PX, scale)
        self.font = font
        self.on_select, self.on_activate = on_select, on_activate
        self.empty_text = empty_text
        self.canvas = tk.Canvas(parent, background=THEME["editor.background"],
                                highlightthickness=1, highlightbackground=THEME[
                                    "editor.background"],
                                highlightcolor=THEME["focusBorder"], borderwidth=0,
                                takefocus=1, height=self.side + self.label_h)
        self.widget = self.canvas
        self.items: list[tuple[str, str]] = []
        self.images: dict[str, object] = {}
        self.selected: str | None = None
        self.columns = 1
        self.canvas.bind("<Configure>", lambda _e: self.draw(), add="+")
        self.canvas.bind("<Button-1>", self._click, add="+")
        self.canvas.bind("<Double-Button-1>", self._double, add="+")
        for key, step in (("<Left>", -1), ("<Right>", 1), ("<Up>", "up"), ("<Down>", "down")):
            self.canvas.bind(key, lambda _e, s=step: (self._move(s), "break")[1])
        for key in ("<Return>", "<KP_Enter>"):
            self.canvas.bind(key, lambda _e: (self._activate(), "break")[1])

    def set_items(self, items: Sequence[tuple[str, str]]) -> None:
        self.items = list(items)
        keys = {key for key, _label in self.items}
        self.images = {k: v for k, v in self.images.items() if k in keys}
        if self.selected not in keys:
            self.selected = None
        self.draw()

    def set_image(self, key: str, image: object) -> None:
        self.images[key] = image
        self.draw()

    def select(self, key: str | None) -> None:
        self.selected = key
        self.draw()

    def labels(self) -> list[str]:
        return [label for _key, label in self.items]

    def _cell(self) -> tuple[int, int]:
        return self.side + self.gap, self.side + self.label_h + self.gap

    def draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        if width <= 1:
            width = int(canvas.cget("width"))
        cw, ch = self._cell()
        self.columns = max(1, (width + self.gap) // cw)
        rows = max(1, -(-len(self.items) // self.columns))
        height = rows * ch - self.gap + _px(4, self.scale)
        if int(float(canvas.cget("height"))) != height:
            canvas.configure(height=height)
        if not self.items and self.empty_text:
            canvas.create_text(2, self.side // 2, text=self.empty_text, anchor="w",
                               fill=THEME["muted"], font=self.font or "TkDefaultFont")
        for index, (key, label) in enumerate(self.items):
            col, row = index % self.columns, index // self.columns
            x, y = col * cw + 1, row * ch + 1
            chosen = key == self.selected
            canvas.create_rectangle(x, y, x + self.side, y + self.side, fill=ROLES["raised"],
                                    outline=THEME["focusBorder"] if chosen else
                                    THEME["border"], width=2 if chosen else 1)
            image = self.images.get(key)
            if image is not None:
                canvas.create_image(x + self.side // 2, y + self.side // 2, image=image)
            text = label
            if self.font is not None:
                while len(text) > 3 and self.font.measure(text) > self.side:
                    text = text[:-2] + "…"
            canvas.create_text(x + self.side // 2, y + self.side + _px(3, self.scale),
                               text=text, anchor="n",
                               fill=THEME["strongForeground"] if chosen else THEME["foreground"],
                               font=self.font or "TkDefaultFont")

    def _index_at(self, x: int, y: int) -> int | None:
        cw, ch = self._cell()
        col, row = int(x // cw), int(y // ch)
        if col >= self.columns:
            return None
        index = row * self.columns + col
        return index if 0 <= index < len(self.items) else None

    def _click(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        index = self._index_at(event.x, event.y)
        if index is not None:
            self._choose(self.items[index][0])

    def _double(self, event: tk.Event) -> None:
        index = self._index_at(event.x, event.y)
        if index is not None:
            self._activate()

    def _choose(self, key: str) -> None:
        self.select(key)
        if self.on_select is not None:
            self.on_select(key)

    def _move(self, step: int | str) -> None:
        if not self.items:
            return
        keys = [key for key, _label in self.items]
        now = keys.index(self.selected) if self.selected in keys else -1
        delta = {"up": -self.columns, "down": self.columns}.get(step, step)  # type: ignore[arg-type]
        target = min(len(keys) - 1, max(0, now + int(delta))) if now >= 0 else 0
        self._choose(keys[target])

    def _activate(self) -> None:
        if self.selected is not None and self.on_activate is not None:
            self.on_activate(self.selected)


__all__ = ["AssetPicker", "ChoiceField", "ColorField", "FormGrid", "FormRow", "Gallery",
           "NumberField", "ScrollFrame", "TextField", "ToggleField", "ask_color",
           "color_dot"]
