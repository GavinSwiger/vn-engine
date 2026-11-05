"""Import palette… on Game settings ▸ Color scheme (2026-11-05).

Why this module exists: authors collect palettes on Lospec, Coolors, Adobe Color or in their
art program. Pasting one (or opening its file) should give the whole game those colors,
readable, without picking sixty colors. ``engine.core.palette`` reads the palette and
assigns its colors to the scheme's roles; this window shows the result on a small text box
and two choices before anything is written.

- ``PaletteImport(parent, on_import)``: a box for pasted text (hex colors, a Coolors link, a
  palette file's text), **Open file…** (``.hex .gpl .pal .ase .act .txt .css``), the name
  shown on the card, **Background** Automatic / Light / Dark, the preview, and Import /
  Cancel. Import calls ``on_import(roles, name)`` and closes; the page writes
  ``[theme.scheme]`` as one undo step (``schememodel.import_changes``).
- ``open_palette_import(parent, on_import)``: the window, modal (tests set
  ``PALETTE_MODAL`` False and drive the object).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Final

from engine.core import palette
from engine.core.palette import PaletteError
from engine.tools.editor import dialogs
from engine.tools.editor.theme import THEME

PALETTE_MODAL = True                    # tests set False: the window doesn't wait

TITLE: Final = "Import palette"
HINT: Final = ("Paste colors, a Coolors link, or a palette file's text, or open a file "
               "(.hex, .gpl, .pal, .ase, .act, .txt). Lospec, Coolors and most art programs "
               "save one of these.")
OPEN_FILE: Final = "Open file…"
NAME: Final = "Name"
BACKGROUND: Final = "Background"
WAYS: Final = (("Automatic", None), ("Light", False), ("Dark", True))
FOUND: Final = "{n} colors found. Text and highlights are adjusted so they're easy to read."
FOUND_ONE: Final = "1 color found. The rest are mixed from it."
EMPTY: Final = "Paste colors or open a palette file to see them here."
IMPORT: Final = "Import"
CANCEL: Final = "Cancel"
FILE_TYPES: Final = (("Palettes", "*.hex *.gpl *.pal *.ase *.act *.txt *.css"),
                     ("All files", "*.*"))
SAMPLE_NAME: Final = "Amara"
SAMPLE_LINE: Final = "The lanterns are lit tonight."
SAMPLE_CHOICES: Final = ("Go to the river", "Stay home")
SAMPLE_LOCKED: Final = "Follow the stranger (locked)"
PREVIEW_W: Final = 380
PREVIEW_H: Final = 190


def ask_palette_file(parent: tk.Misc) -> Path | None:
    """Open file…: the OS file dialog. None when cancelled."""
    picked = filedialog.askopenfilename(parent=parent, title=TITLE, filetypes=FILE_TYPES)
    return Path(picked) if picked else None


def name_of(path: Path, data: bytes) -> str:
    """A palette's name: GIMP's ``Name:`` line, else the file name in words."""
    for line in data[:4096].decode("utf-8", "replace").splitlines()[:4]:
        if line.startswith("Name:") and line[5:].strip():
            return line[5:].strip()[:60]
    return " ".join(path.stem.replace("_", " ").replace("-", " ").split()).title()[:60]


class PaletteImport:
    """The window (module docstring). ``roles`` is the preview's roles (None: nothing
    read), ``status`` the line under the preview."""

    def __init__(self, parent: tk.Misc,
                 on_import: Callable[[dict[str, str], str | None], object]) -> None:
        self.on_import = on_import
        self.colors: tuple[str, ...] = ()
        self.roles: dict[str, str] | None = None
        self._after: str | None = None
        window = self.window = dialogs._dialog(parent)
        window.title(TITLE)
        body, scale = dialogs._body(window)
        self.scale = scale
        gap = round(8 * scale)
        ttk.Label(body, text=HINT, style="Dialog.TLabel", wraplength=round(PREVIEW_W * scale),
                  justify="left").pack(anchor="w")
        self.text = tk.Text(body, height=4, width=48, wrap="word", undo=True,
                            background=THEME["input.background"],
                            foreground=THEME["input.foreground"],
                            insertbackground=THEME["input.foreground"], relief="flat",
                            highlightthickness=1, highlightcolor=THEME["focusBorder"],
                            highlightbackground=THEME["input.border"])
        self.text.pack(fill="x", pady=(gap, 0))
        self.text.bind("<<Modified>>", self._modified)
        row = ttk.Frame(body, style="Dialog.TFrame")
        row.pack(fill="x", pady=(gap, 0))
        ttk.Button(row, text=OPEN_FILE, style="Secondary.TButton",
                   command=self.open_file).pack(side="left")
        ttk.Label(row, text=NAME, style="Dialog.TLabel").pack(side="left", padx=(gap * 2, gap))
        self.name = tk.StringVar(master=window)
        ttk.Entry(row, textvariable=self.name, width=22).pack(side="left", fill="x",
                                                             expand=True)
        ways = ttk.Frame(body, style="Dialog.TFrame")
        ways.pack(fill="x", pady=(gap, 0))
        ttk.Label(ways, text=BACKGROUND, style="Dialog.TLabel").pack(side="left",
                                                                    padx=(0, gap))
        self.way = tk.StringVar(master=window, value=WAYS[0][0])
        for word, _dark in WAYS:
            ttk.Radiobutton(ways, text=word, value=word, variable=self.way,
                            style="Dialog.TRadiobutton", command=self.update).pack(
                side="left", padx=(0, gap))
        self.canvas = tk.Canvas(body, width=round(PREVIEW_W * scale),
                                height=round(PREVIEW_H * scale), highlightthickness=0,
                                background=THEME["editor.background"])
        self.canvas.pack(pady=(gap, 0))
        self.status = ttk.Label(body, text=EMPTY, style="Dialog.Hint.TLabel",
                                wraplength=round(PREVIEW_W * scale), justify="left")
        self.status.pack(anchor="w", pady=(gap // 2, 0))
        self.buttons = dialogs._buttons(window, body, (IMPORT, CANCEL), self._pick)
        window.bind("<Escape>", lambda _e: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.update()

    # --- Reading -----------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.update()

    def open_file(self) -> None:
        path = ask_palette_file(self.window)
        if path is None:
            return
        try:
            if path.stat().st_size > palette.MAX_BYTES:
                raise PaletteError(palette.TOO_BIG)
            data = path.read_bytes()
            self.colors = palette.read_palette(data)
        except OSError:
            self._show_problem(f"Couldn't read {path.name}.")
            return
        except PaletteError as problem:
            self._show_problem(problem.text)
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", " ".join(self.colors))
        self.name.set(name_of(path, data))
        self.update()

    def _modified(self, _event: tk.Event) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._after is not None:
            self.window.after_cancel(self._after)
        self._after = self.window.after(200, self.update)

    def update(self) -> None:
        """Read the box again and redraw the preview."""
        self._after = None
        raw = self.text.get("1.0", "end-1c")
        dark = dict(WAYS)[self.way.get()]
        if not raw.strip():
            self.colors, self.roles = (), None
            self._draw()
            self.status.configure(text=EMPTY)
            self._enable(False)
            return
        try:
            self.colors = palette.read_palette(raw)
            self.roles = palette.derive_roles(self.colors, dark).roles
        except PaletteError as problem:
            self._show_problem(problem.text)
            return
        n = len(self.colors)
        self.status.configure(text=FOUND_ONE if n == 1 else FOUND.format(n=n))
        self._draw()
        self._enable(True)

    def _show_problem(self, text: str) -> None:
        self.roles = None
        self._draw()
        self.status.configure(text=text)
        self._enable(False)

    def _enable(self, on: bool) -> None:
        self.buttons[0].state(["!disabled"] if on else ["disabled"])

    # --- The preview -------------------------------------------------------------------

    def _draw(self) -> None:
        c, s = self.canvas, self.scale
        c.delete("all")
        w, h = round(PREVIEW_W * s), round(PREVIEW_H * s)

        def px(v: float) -> int:
            return round(v * s)
        r = self.roles
        if r is None:
            c.create_rectangle(0, 0, w, h, fill=THEME["editor.background"], width=0)
            return
        # A scene behind: the palette's own colors as stripes, as a background picture.
        stripes = self.colors[:12] or (r["fill"],)
        step = w / len(stripes)
        for i, color in enumerate(stripes):
            c.create_rectangle(round(i * step), 0, round((i + 1) * step), h, fill=color,
                               width=0)
        # Two choices and a locked one.
        for i, word in enumerate((*SAMPLE_CHOICES, SAMPLE_LOCKED)):
            top = px(10 + i * 30)
            focused = i == 0
            c.create_rectangle(px(70), top, w - px(70), top + px(24),
                               fill=r["focus"] if focused else r["fill"],
                               outline=r["accent2"] if focused else r["border"],
                               width=px(2) if focused else 1)
            if focused:
                c.create_rectangle(px(78), top + px(9), px(84), top + px(15),
                                   fill=r["accent"], width=0)
            c.create_text(w // 2, top + px(12), text=word,
                          fill=r["muted"] if word == SAMPLE_LOCKED else r["text"])
        # The text box with its name tab.
        top = px(116)
        c.create_rectangle(px(10), top, w - px(10), h - px(8), fill=r["fill"],
                           outline=r["border"])
        c.create_rectangle(px(22), top - px(12), px(96), top + px(10), fill=r["soft"],
                           outline=r["border"])
        c.create_text(px(59), top - px(1), text=SAMPLE_NAME, fill=r["accent"])
        c.create_text(px(24), top + px(30), text=SAMPLE_LINE, fill=r["text"], anchor="w")
        c.create_polygon(w - px(30), h - px(24), w - px(20), h - px(24), w - px(25),
                         h - px(17), fill=r["accent"])

    # --- Closing -----------------------------------------------------------------------

    def _pick(self, index: int) -> None:
        if index == 0:
            self.import_()
        else:
            self.close()

    def import_(self) -> bool:
        """Import: hand the roles and name over and close; False with nothing to import."""
        if self.roles is None:
            return False
        roles, name = dict(self.roles), self.name.get().strip() or None
        self.close()
        self.on_import(roles, name)
        return True

    def close(self) -> None:
        if self._after is not None:
            self.window.after_cancel(self._after)
            self._after = None
        if self.window.winfo_exists():
            self.window.destroy()


def open_palette_import(parent: tk.Misc,
                        on_import: Callable[[dict[str, str], str | None], object]
                        ) -> PaletteImport:
    """The window; modal unless ``PALETTE_MODAL`` is False."""
    found = PaletteImport(parent, on_import)
    if PALETTE_MODAL:
        dialogs._run(parent, found.window, found.text)
    else:
        found.window.deiconify()
    return found


__all__ = ["CANCEL", "EMPTY", "FOUND", "FOUND_ONE", "HINT", "IMPORT", "OPEN_FILE",
           "PALETTE_MODAL", "PaletteImport", "TITLE", "ask_palette_file", "name_of",
           "open_palette_import"]
