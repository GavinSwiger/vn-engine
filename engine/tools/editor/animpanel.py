"""Database ▸ Characters' **Blinking and talking** panel (F38 ``SPEC.md`` §4; PR-F38-07,
PR-F38-11; AC-F38-10..12).

Why this module exists: a writer who doesn't code sets up a character's blinking and
talking here, RPG Maker style. F38's naming rule (``script/spriteframes.py``) is the only
storage: ``images/hana/happy_blink1.png`` is a blink frame of ``hana happy``. So the Looks
gallery hides frame pictures and labels a look that has frames ``happy (moves)``; clicking
a look fills this panel under it:

- two rows of 64 px thumbnails, **Blink frames** and **Talking frames**, in play order,
  each with **+ Add … frame…** (one picture through F45's Add files checks, saved under the
  rule's next name, ``spriteframes.next_number``) and **Remove frame** (the selected
  thumbnail, after the Database's delete question, through ``files.delete_file``);
- **▶ Blink** / **▶ Talk** preview: the 192 px picture swaps through ``spriteframes.cycle``
  at the timings Game settings shows (``settingsmodel.section_values``: config.toml, else
  the defaults; 07 I-10), each button **■ Stop** while it plays;
- hints: what a frame is, a frame of another size than its look (the game won't use it,
  W217), and animation turned off in Game settings.

``look_items`` is the gallery's pure half. ``LookPanel`` is hosted by
``database.DatabasePane`` (``pane``: its window, thumbnail loaders, ``config_text`` and
``refresh``). Imports the standard library, ``tkinter``, ``engine.script`` and its own
package; never pygame.
"""

import math
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from tkinter import ttk
from typing import Any

from engine.script import spriteframes as sf
from engine.script.messages import show
from engine.tools.editor import files
from engine.tools.editor.dbmore import DELETE_BUTTONS
from engine.tools.editor.dialogs import ask, show_error
from engine.tools.editor.fieldwidgets import Gallery
from engine.tools.editor.helperrunner import file_stamp
from engine.tools.editor.settingsmodel import section_values
from engine.tools.editor.theme import THEME
from engine.tools.editor.views import read_asset

# --- Texts (SPEC §4, final) ---------------------------------------------------------------------

MOVES = "{look} (moves)"
CAPTION = "Blinking and talking: {look}"
CAPTION_EMPTY = "Blinking and talking"
PICK_LOOK = "Click a look to set up blinking and talking."
ROW_TITLES = {"blink": "Blink frames", "talk": "Talking frames"}
ADD_FRAME = {"blink": "+ Add blink frame…", "talk": "+ Add talking frame…"}
REMOVE_FRAME = "Remove frame"
NONE_YET = "None yet"
ROW_HINTS = {
    "blink": "Pictures of {look} with the eyes closed (or half closed, then closed). "
             "{name} blinks every few seconds.",
    "talk": "Pictures of {look} with the mouth open. The mouth moves while {name}'s lines "
            "type."}
TIP = ("A frame is a copy of {file} with only the eyes or mouth changed, the same size. "
       "Files named {look}_blink1, {look}_talk1, … are found by themselves.")
FULL = {"blink": "A look can have up to 9 blink frames.",
        "talk": "A look can have up to 9 talking frames."}
PLAY = {"blink": "▶ Blink", "talk": "▶ Talk"}
STOP = "■ Stop"
WRONG_SIZE = ("{file} is {w}×{h}, but {look} is {lw}×{lh}, so the game won't use it. "
              "Frames must be the same size as their look.")
ANIMATION_OFF = "Sprite animation is turned off in Game settings ▸ Effects & comfort."
DELETE_FILE_ASK = "Delete {ref} from the game folder? This can't be undone."   # database's

# --- Sizes and timing ---------------------------------------------------------------------------

FRAME_PX = 64
TALK_PREVIEW_S = 2.0            # ▶ Talk loops this long
HINT_WRAP_PX = 300
TIP_WRAP_PX = 520
WIDE_RIGHT_PX = 280           # the frame rows sit beside the picture from this width
ANIMATION = "animation"         # the config section (SPEC §3)


def look_word(name: str) -> str:
    """``hana happy`` → ``happy``; a one-word name stays."""
    parts = name.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else name


@dataclass(frozen=True)
class LookItem:
    """A look in the gallery: its file, image name, label and frames."""

    ref: str
    name: str
    label: str
    frames: sf.LookFrames


def look_items(refs: Sequence[str]) -> tuple[list[LookItem], dict[str, str]]:
    """The Looks gallery for a character folder's picture ``refs`` (in their order): the
    looks without the frame pictures (``spriteframes.frame_of``), a look with frames
    labelled ``happy (moves)``; and every picture's image name → ref."""
    by_name: dict[str, str] = {}
    for ref in refs:
        name = files.image_name_of(ref)
        if name is not None:
            by_name.setdefault(name, ref)
    pictures = frozenset(by_name)
    items = []
    for name, ref in by_name.items():
        if sf.frame_of(name, pictures) is not None:
            continue
        frames = sf.frames_of(name, pictures)
        word = look_word(name)
        items.append(LookItem(ref, name, MOVES.format(look=word) if frames else word, frames))
    return items, by_name


def play_steps(kind: str, frames: Sequence[str], look: str, step_s: float) -> list[str]:
    """The pictures ▶ shows, each for ``step_s``: one blink (``cycle`` then the look), or
    talking (``cycle`` then the look, repeated for ``TALK_PREVIEW_S``)."""
    one = [*sf.cycle(frames), look]
    if kind == "blink" or not frames:
        return one
    rounds = max(1, math.ceil(TALK_PREVIEW_S / (len(one) * step_s)))
    return one * rounds


class _FrameRow:
    """One kind's row: title, + Add, Remove frame, the thumbnails and the hints."""

    def __init__(self, panel: "LookPanel", parent: tk.Misc, kind: sf.FrameKind) -> None:
        px = panel.px
        self.kind = kind
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.title = ttk.Label(self.frame, text=ROW_TITLES[kind], style="Strong.Anim.TLabel")
        self.title.grid(row=0, column=0, sticky="w")
        self.gallery = Gallery(self.frame, scale=panel.scale, thumb=FRAME_PX,
                               font=panel.pane.fonts["small"], empty_text=NONE_YET,
                               on_select=lambda _key: panel.sync_buttons(),
                               on_activate=panel.open_picture)
        self.gallery.canvas.configure(width=px(3 * (FRAME_PX + 12)))
        self.gallery.canvas.bind("<Delete>", lambda _e: (panel.remove_frame(kind),
                                                         "break")[1])
        self.gallery.widget.grid(row=1, column=0, sticky="ew", pady=(px(4), px(2)))
        buttons = ttk.Frame(self.frame)
        buttons.grid(row=2, column=0, sticky="w", pady=(0, px(4)))
        self.add = ttk.Button(buttons, text=ADD_FRAME[kind], style="Secondary.TButton",
                              command=lambda: panel.add_frame(kind))
        self.add.pack(side="left", padx=(0, px(6)))
        self.remove = ttk.Button(buttons, text=REMOVE_FRAME, style="Secondary.TButton",
                                 command=lambda: panel.remove_frame(kind))
        self.remove.pack(side="left")
        self.hint = ttk.Label(self.frame, text="", style="Hint.TLabel", justify="left",
                              wraplength=px(HINT_WRAP_PX))
        self.hint.grid(row=3, column=0, sticky="w")
        self.full = ttk.Label(self.frame, text="", style="Hint.TLabel", justify="left",
                              wraplength=px(HINT_WRAP_PX))
        self.warnings = ttk.Frame(self.frame)
        self.warnings.grid(row=5, column=0, sticky="w")
        self.size_hints: list[ttk.Label] = []


class LookPanel:
    """The Blinking and talking panel of a character's form (module docstring). ``refs``
    are the character folder's pictures; ``character`` the name players see."""

    def __init__(self, pane: Any, parent: tk.Misc, *, folder: str, character: str,
                 refs: Sequence[str], on_look: Callable[[str | None], object]) -> None:
        self.pane = pane
        self.win = pane.win
        self.scale = pane.scale
        self.folder = folder
        self.character = character
        self.on_look = on_look
        self.items, self.by_name = look_items(refs)
        self.pictures = frozenset(self.by_name)
        self.look: LookItem | None = None
        self.playing: str | None = None
        self.played: list[str] = []          # what the running ▶ showed so far (tests)
        self.steps: list[str] = []
        self.step_ms = 0
        self._after: str | None = None
        self.shown_name: str | None = None
        px = self.px
        style = ttk.Style(pane.root)
        back = THEME["editor.background"]
        style.configure("Strong.Anim.TLabel", background=back,
                        foreground=THEME["strongForeground"])
        style.configure("Warn.Anim.TLabel", background=back,
                        foreground=THEME["marker.warning"], font=pane.fonts["small"])

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(1, weight=1)
        self.caption = ttk.Label(self.frame, text="", style="Caption.TLabel")
        self.caption.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(6)))
        self.caption_text = ""
        self.pick = ttk.Label(self.frame, text=PICK_LOOK, style="Hint.TLabel")
        # Left: the 192 px picture and ▶ Blink / ▶ Talk under it. Right (or under it, in
        # a narrow form): the two frame rows.
        self.left = ttk.Frame(self.frame)
        side = px(192) + 2
        self.preview_box = tk.Frame(self.left, width=side, height=side,
                                    background=THEME["border"], borderwidth=0)
        self.preview_box.pack_propagate(False)
        self.preview_box.pack(anchor="w")
        self.preview = tk.Label(self.preview_box, background=THEME["editor.background"],
                                foreground=THEME["muted"], borderwidth=0)
        self.preview.pack(fill="both", expand=True, padx=1, pady=1)
        self.right = ttk.Frame(self.frame)
        self.right.columnconfigure(0, weight=1)
        self.rows = {kind: _FrameRow(self, self.right, kind) for kind in sf.FRAME_KINDS}
        for index, row in enumerate(self.rows.values()):
            row.frame.grid(row=index, column=0, sticky="ew", pady=(0, px(10)))
        line = ttk.Frame(self.left)
        line.pack(anchor="w", pady=(px(8), 0))
        self.wide = True
        self._wrap = px(HINT_WRAP_PX)
        self.frame.bind("<Configure>", self._on_resize, add="+")
        self.frame.bind("<Map>", lambda e: self._fit(self.frame.winfo_width())
                        if e.widget is self.frame else None, add="+")
        self.play_buttons = {}
        for kind in sf.FRAME_KINDS:
            button = ttk.Button(line, text=PLAY[kind], style="Secondary.TButton",
                                command=lambda k=kind: self.toggle(k))
            button.pack(side="left", padx=(0, px(6)))
            self.play_buttons[kind] = button
        self.tip = ttk.Label(self.frame, text="", style="Hint.TLabel", justify="left",
                             wraplength=px(TIP_WRAP_PX))
        self.off = ttk.Label(self.frame, text=ANIMATION_OFF, style="Warn.Anim.TLabel",
                             justify="left", wraplength=px(TIP_WRAP_PX))
        self.frame.bind("<Destroy>", lambda e: self._cancel() if e.widget is self.frame
                        else None, add="+")
        self.show(None)

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget is self.frame:
            self._fit(event.width)

    def _fit(self, width: int) -> None:
        """Side by side or stacked, and the hints' wrap, for the form's ``width``."""
        if not self.frame.winfo_ismapped():
            return          # unmapped, the width follows the wraps: no feedback loop
        wide = width >= self.px(192 + 16 + WIDE_RIGHT_PX)
        right = width - (max(self.left.winfo_reqwidth(), self.px(192)) + self.px(16)
                         if wide else 0)
        wrap = self._wrap = max(self.px(160), right - self.px(8))
        for row in self.rows.values():
            for label in (row.hint, row.full, *row.size_hints):
                if abs(int(str(label.cget("wraplength")) or 0) - wrap) > self.px(8):
                    label.configure(wraplength=wrap)
        tip_wrap = max(self.px(160), width - self.px(8))
        for label in (self.tip, self.off):
            if abs(int(str(label.cget("wraplength")) or 0) - tip_wrap) > self.px(8):
                label.configure(wraplength=tip_wrap)
        if wide != self.wide:
            self.wide = wide
            if self.look is not None:
                self._place()

    def _place(self) -> None:
        """The picture beside the frame rows, or above them in a narrow form."""
        self.left.grid(row=1, column=0, sticky="nw", padx=(0, self.px(16) if self.wide else 0))
        if self.wide:
            self.right.grid(row=1, column=1, columnspan=1, sticky="new", pady=0)
        else:
            self.right.grid(row=2, column=0, columnspan=2, sticky="new", pady=(self.px(12), 0))

    # --- Showing a look -----------------------------------------------------------------

    def item(self, ref: str) -> LookItem | None:
        return next((item for item in self.items if item.ref == ref), None)

    def show(self, ref: str | None) -> None:
        """Fill the panel for the look whose file is ``ref`` (None: the "Click a look"
        state). Stops a running preview."""
        self.stop()
        self.look = self.item(ref) if ref is not None else None
        look = self.look
        if look is None:
            self.caption_text = CAPTION_EMPTY
            self.caption.configure(text=CAPTION_EMPTY.upper())
            for widget in (self.left, self.right, self.tip, self.off):
                widget.grid_remove()
            self.pick.grid(row=1, column=0, columnspan=2, sticky="w")
            return
        self.pick.grid_remove()
        word = look_word(look.name)
        self.caption_text = CAPTION.format(look=word)
        self.caption.configure(text=self.caption_text.upper())
        self._place()
        file_name = look.ref.rsplit("/", 1)[-1]
        self.tip.configure(text=TIP.format(file=file_name, look=file_name.rsplit(".", 1)[0]))
        self.tip.grid(row=4, column=0, columnspan=2, sticky="w", pady=(self.px(10), 0))
        look_size = self._size(look.ref)
        for kind, row in self.rows.items():
            frames = look.frames.of(kind)
            row.hint.configure(text=ROW_HINTS[kind].format(look=word, name=self.character))
            row.gallery.set_items([(self.by_name[name], name[len(look.name) + 1:])
                                   for name in frames])
            for name in frames:
                ref = self.by_name[name]
                image = self.pane.frame_thumbs.get(ref)
                if image is not None:
                    row.gallery.images[ref] = image
                self.pane.previews.get(ref)            # asks for the preview early
            row.gallery.draw()
            for label in row.size_hints:
                label.destroy()
            row.size_hints = []
            for name in frames:
                ref = self.by_name[name]
                size = self._size(ref)
                if look_size is None or size is None or size == look_size:
                    continue
                label = ttk.Label(row.warnings, style="Warn.Anim.TLabel", justify="left",
                                  wraplength=self._wrap, text=WRONG_SIZE.format(
                                      file=ref.rsplit("/", 1)[-1], w=size[0], h=size[1],
                                      look=word, lw=look_size[0], lh=look_size[1]))
                label.pack(anchor="w", pady=(self.px(2), 0))
                row.size_hints.append(label)
        self.sync_hints()
        self.sync_buttons()
        self._show_picture(look.name)
        self.on_look(look.ref)

    def sync_hints(self) -> None:
        """The off hint, from Game settings' ``[animation] enabled`` as it is now."""
        if self.look is None:
            return
        if self.settings()["enabled"] is False:
            self.off.grid(row=3, column=0, columnspan=2, sticky="w", pady=(self.px(6), 0))
        else:
            self.off.grid_remove()

    def sync_buttons(self) -> None:
        look = self.look
        if look is None:
            return
        for kind, row in self.rows.items():
            full = sf.next_number(look.name, kind, self.pictures) is None
            row.add.configure(state="disabled" if full else "normal")
            if full:
                row.full.configure(text=FULL[kind])
                row.full.grid(row=3, column=0, sticky="w")
            else:
                row.full.grid_remove()
            row.remove.configure(state="normal" if row.gallery.selected else "disabled")
            button = self.play_buttons[kind]
            button.configure(text=STOP if self.playing == kind else PLAY[kind],
                             state="normal" if look.frames.of(kind) else "disabled")

    def _size(self, ref: str) -> tuple[int, int] | None:
        cache = self.pane.__dict__.setdefault("_frame_sizes", {})
        key = (ref, file_stamp(self.win.paths.root, ref))
        if key not in cache:
            info = read_asset(self.win.paths, ref)
            cache[key] = (info.width, info.height) if info.width and info.height else None
        return cache[key]

    def _show_picture(self, name: str) -> None:
        ref = self.by_name.get(name)
        image = self.pane.previews.get(ref) if ref is not None else None
        if image is None and self.shown_name is not None and self.playing:
            return                                  # not decoded yet: keep the last one
        self.shown_name = name
        self.preview.configure(image=image or "", text="" if image else "…")
        self.preview.image = image                  # type: ignore[attr-defined]

    def thumb_ready(self, ref: str) -> None:
        """A thumbnail arrived from the helper child."""
        for row in self.rows.values():
            if ref in dict(row.gallery.items):
                image = self.pane.frame_thumbs.get(ref)
                if image is not None:
                    row.gallery.set_image(ref, image)
        if self.shown_name is not None and self.by_name.get(self.shown_name) == ref:
            self._show_picture(self.shown_name)

    def open_picture(self, ref: str) -> None:
        self.win.show_asset(ref)

    # --- ▶ Blink / ▶ Talk ---------------------------------------------------------------

    def settings(self) -> Mapping[str, object]:
        return section_values(ANIMATION, self.pane.config_text())

    def toggle(self, kind: str) -> None:
        """▶ plays ``kind``; ■ Stop (the same kind playing) stops it."""
        if self.playing == kind:
            self.stop()
        else:
            self.play(kind)

    def play(self, kind: str) -> None:
        look = self.look
        self.stop()
        if look is None or not look.frames.of(kind):     # type: ignore[arg-type]
            return
        settings = self.settings()
        step_s = float(settings["blink_frame" if kind == "blink" else "talk_frame"])
        self.steps = play_steps(kind, look.frames.of(kind), look.name,  # type: ignore[arg-type]
                                step_s)
        self.step_ms = max(1, round(step_s * 1000))
        self.playing = kind
        self.played = []
        self.sync_buttons()
        self._next(0)

    def _next(self, index: int) -> None:
        self._after = None
        if self.look is None or index >= len(self.steps):
            self.stop()
            return
        name = self.steps[index]
        self.played.append(name)
        self._show_picture(name)
        self._after = self.pane.root.after(self.step_ms, lambda: self._next(index + 1))

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.pane.root.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        self.playing = None

    def stop(self) -> None:
        """Stop a preview and show the look again."""
        was = self.playing
        self._cancel()
        if was is not None and self.look is not None and self.frame.winfo_exists():
            self._show_picture(self.look.name)
            self.sync_buttons()

    # --- + Add … frame… / Remove frame --------------------------------------------------

    def add_frame(self, kind: sf.FrameKind) -> None:
        """One picture saved as ``<look>_<kind><N><ext>`` (N: ``next_number``)."""
        look = self.look
        if look is None:
            return
        number = sf.next_number(look.name, kind, self.pictures)
        if number is None:
            return
        self.stop()
        stem = look.ref.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        self.win.add_files(target=("images", self.folder),
                           name=sf.frame_name(stem, kind, number),
                           on_done=lambda _refs: self.pane.refresh())

    def remove_frame(self, kind: sf.FrameKind) -> None:
        """The selected thumbnail of ``kind``'s row, after the Database's delete question.
        Other frames keep their numbers."""
        ref = self.rows[kind].gallery.selected
        if self.look is None or ref is None:
            return
        if ask(self.pane.root, DELETE_FILE_ASK.format(ref=show(ref)), DELETE_BUTTONS,
               escape=1, default=1) != 0:
            return
        self.stop()
        result = files.delete_file(self.win.paths, ref)
        if isinstance(result, files.Refusal):
            show_error(self.pane.root, result.text)
            return
        self.win.refresh_project()
        self.pane.refresh()


__all__ = ["ANIMATION_OFF", "CAPTION", "FULL", "LookItem", "LookPanel", "MOVES", "PICK_LOOK",
           "ROW_HINTS", "TIP", "WRONG_SIZE", "look_items", "look_word", "play_steps"]
