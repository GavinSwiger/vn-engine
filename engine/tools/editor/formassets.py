"""The window's answers for the statement forms' pickers (F47 W5; design §4.5, PR-F47-12;
AC-F47-13, AC-F47-22).

Why this module exists: ``formdialogs.FormDialog`` shows thumbnails, ▶/■ and colour dots
through a ``formdialogs.FormAssets``, so it needs no window. ``WindowAssets`` is that
provider for a Studio window, built from what the Database shows:

- characters (name colour, shown name, ``image_tag``) and colour backgrounds from the
  scripts' declarations (``declarations.scan`` of the editor texts, as the Database reads
  them), so an unsaved edit in the Database shows at once;
- pictures from the project's ``images/`` files (``files.image_name_of``) plus the check's
  ``image`` names; a look is the rest of an image name after its sprite tag
  (``dbmodel.looks_in``: F38's blink and talking frames are not looks);
- thumbnails from ``helperhub.ThumbLoader`` (PNG/GIF in-process, JPEG/WebP via the helper
  child; ``changed()`` when one arrives); a colour background is its colour;
- sounds through the window's ``HelperHub`` (one at a time; ``changed()`` on its replies);
- the condition builder's names (F47 P2): story and remembered variables
  (``persistent.<name>``), meters, codex tips and items, and routes, as declared;
- W9: the Meta file form's names from ``files/`` (F31's originals) and the Game UI form's
  styles from ``config.toml``'s open text (``[style.<name>]``, then ``off``).

``refresh()`` re-reads all of it; the Events tab calls it each time a form opens.
Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Sequence
from typing import Any

from engine.core.paths import is_meta_name
from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import declarations as dec
from engine.tools.editor import files
from engine.tools.editor.dbmodel import looks_in
from engine.tools.editor.fieldwidgets import THUMB_PX
from engine.tools.editor.forms_files_ui import STYLE_OFF
from engine.tools.editor.settingsmodel import style_names
from engine.tools.editor.formdialogs import FormAssets
from engine.tools.editor.helperhub import ThumbLoader, hub_for
from engine.tools.editor.theme import scale_of

AUDIO_PREFIX = "audio/"
META_FILE_KIND = "meta_file"                    # W9: the Meta file form's names
META_GROUP = "files"                            # F31's asset group of originals
STYLE_KIND = "style"                            # W9: the Game UI form's styles
# Declaration kinds → the name kind the forms' pickers ask for.
_DECLARED = {dec.VARIABLE: "variable", dec.PERSISTENT: "variable", dec.METER: "meter",
             dec.TIP: "tip", dec.ITEM: "item", dec.ROUTE: "route"}


def _names(entries: Sequence[object]) -> list[str]:
    out = []
    for entry in entries:
        name = entry if isinstance(entry, str) else getattr(entry, "name", None)
        if name is None and isinstance(entry, (tuple, list)) and entry:
            name = entry[0]
        if isinstance(name, str):
            out.append(name)
    return out


class WindowAssets(FormAssets):
    """``FormAssets`` for Studio window ``win`` (module docstring)."""

    def __init__(self, win: Any) -> None:
        self.win = win
        self.on_change = None
        self.px = round(THUMB_PX * scale_of(win.root))
        self.loader = ThumbLoader(win, win.root, self.px, lambda _ref: self.changed())
        self.characters: dict[str, dict] = {}
        self.colors: dict[str, str] = {}               # colour picture name (folded) → hex
        self.image_refs: dict[str, str] = {}           # image name (folded) → images/… ref
        self.image_names: list[str] = []
        self.declared: dict[str, list[str]] = {}
        self._swatches: dict[str, tk.PhotoImage] = {}
        self._listening = False
        self.refresh()

    def refresh(self) -> None:
        """Read the declarations, pictures and the check's names again."""
        from engine.tools.editor.database import script_texts   # Tk-heavy; only when used
        try:
            decls = dec.scan(script_texts(self.win))
        except Exception:  # noqa: BLE001  (a form still opens without colours)
            decls = ()
        self.characters = {d.name: dict(d.values) for d in decls
                           if d.kind == dec.CHARACTER and d.values is not None}
        self.colors = {d.name.casefold(): str(d.values["color"]) for d in decls
                       if d.kind == dec.COLOR and d.values is not None}
        self.declared: dict[str, list[str]] = {}
        for d in decls:
            kind = _DECLARED.get(d.kind)
            if kind is not None:
                name = f"persistent.{d.name}" if d.kind == dec.PERSISTENT else d.name
                self.declared.setdefault(kind, []).append(name)
        project = getattr(self.win, "project", None)
        refs = project.file_refs("images") if project is not None else []
        self.image_refs = {}
        names: dict[str, str] = {}
        for ref in refs:
            name = files.image_name_of(ref)
            if name is not None:
                self.image_refs.setdefault(name.casefold(), ref)
                names.setdefault(name.casefold(), name)
        check = getattr(self.win, "check_names", {}) or {}
        for name in _names(check.get("image", ())):
            names.setdefault(name.casefold(), name)
        self.image_names = sorted(names.values(), key=str.casefold)

    # --- FormAssets ---------------------------------------------------------------------

    def names(self, kind: str) -> Sequence[str]:
        if kind == "character":
            return tuple(self.characters)
        if kind == "image":
            return tuple(self.image_names)
        if kind in self.declared:
            return tuple(self.declared[kind])
        if kind == "sprite":
            tags = {name.split()[0] for name in self.image_names if len(name.split()) > 1}
            return tuple(sorted((t for t in tags if t.casefold() != dec.BACKGROUND_TAG),
                                key=str.casefold))
        if kind == META_FILE_KIND:
            return self.meta_files()
        if kind == STYLE_KIND:
            return (*style_names(self._config_text()), STYLE_OFF)
        return ()

    # --- W9: meta file originals and config styles ----------------------------------------

    def meta_files(self) -> tuple[str, ...]:
        """The originals in ``files/`` (F31's names only), so a new one is offered before
        the next check."""
        project = getattr(self.win, "project", None)
        refs = project.file_refs(META_GROUP) if project is not None else []
        names = (ref.rpartition("/")[2] for ref in refs)
        return tuple(sorted(n for n in names if is_meta_name(n)))

    def _config_text(self) -> str:
        """``config.toml``'s editor text (unsaved changes included), or ""."""
        try:
            record = self.win.record_for(CONFIG_REF)
            return record.widget.get("1.0", "end-1c") if record.editable else ""
        except Exception:  # noqa: BLE001  (no config open: no styles to offer)
            return ""

    def _character_of(self, who: str) -> dict | None:
        """``who``'s Character values: by its ``define`` name, else by its sprite tag."""
        found = self.characters.get(who)
        if found is not None:
            return found
        folded = who.casefold()
        for name, values in self.characters.items():
            if str(values.get("image_tag") or name).casefold() == folded:
                return values
        return None

    def tag(self, who: str) -> str:
        values = self.characters.get(who)
        return str(values.get("image_tag") or who) if values is not None else who

    def looks(self, tag: str) -> Sequence[str]:
        # F38: blink and talking frames are not offered as looks (dbmodel.looks_in).
        colors = {name for name in self.image_names if name.casefold() in self.colors}
        return looks_in(tag, self.image_names, colors)

    def color(self, who: str) -> str | None:
        values = self._character_of(who)
        color = values.get("color") if values is not None else None
        return color if isinstance(color, str) else None

    def shown(self, who: str) -> str | None:
        values = self._character_of(who)
        if values is None:
            return None
        name = values.get(dec.NAME)
        return name if isinstance(name, str) and name else None

    def thumb(self, image: str) -> object | None:
        folded = " ".join(image.split()).casefold()
        color = self.colors.get(folded)
        if color is not None:
            return self._swatch(color)
        ref = self.image_refs.get(folded)
        return self.loader.get(ref) if ref is not None else None

    def _swatch(self, color: str) -> tk.PhotoImage:
        image = self._swatches.get(color)
        if image is None:
            width, height = self.px, round(self.px * 9 / 16)
            image = self._swatches[color] = tk.PhotoImage(master=self.win.root, width=width,
                                                          height=height)
            image.put(color, to=(0, 0, width, height))
        return image

    def _hub(self) -> Any:
        hub = hub_for(self.win)
        if not self._listening:
            hub.listen(lambda _reply: self.changed())
            self._listening = True
        return hub

    def play(self, audio: str) -> None:
        self._hub().play(AUDIO_PREFIX + audio)

    def stop(self) -> None:
        hub = getattr(self.win, "helper_hub", None)
        if hub is not None and hub.playing is not None:
            hub.stop_sound()

    def playing(self) -> str | None:
        hub = getattr(self.win, "helper_hub", None)
        ref = hub.playing if hub is not None else None
        return ref.removeprefix(AUDIO_PREFIX) if isinstance(ref, str) else None


__all__ = ["WindowAssets"]
