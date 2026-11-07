"""Picture boxes on the story map (Studio UX 3.1, "Sketch boxes"; 2026-11-06).

Why this module exists: a box on the map says a scene's name, not what it looks like. In
**Pictures** (the map toolbar's switch; **Compact** is F45's small box) each box shows a small
sketch of its opening shot above its name, and a short line ("Chapter 2 · 62 lines"); its
file and line move to the box's tooltip. The map becomes a storyboard wall.

- **Geometry.** Pictures doesn't lay the map out again: the painter draws the same layout
  stretched by ``PICTURE_STRETCH`` (x, y), boxes included, so boxes that don't overlap in
  Compact don't in Pictures, chips stay on their arrows, and F58's incremental layout, pins
  and places are untouched (places stay in Compact's units).
- ``Sketch`` (pure): a scene's line count, its background (a colour picture's colour, or a
  picture file shown as a tiny thumbnail) and a figure per character in its name colour, at
  its stage position. ``scene_sketch`` builds one from the scene's lines with
  ``scenepreview.opening_stage`` (and ``lead_in`` for a scene that carries a background on).
- ``SketchSource`` (Studio): ``source(box)`` gives a box's sketch, cached by the scene's chunk
  digest (open files: the scene index's; closed files: read once per file stamp), so a
  keystroke recomputes only the scene it changed (and the carried ones on screen).
- ``SketchPainter`` (Tk, on ``mapcanvas.MapPainter``): sketches are drawn **only for boxes in
  view**, on idle, a few milliseconds at a time (``SLICE_MS``), and again when the view
  scrolls or the data changes. A box redrawn by an update gets its known sketch at once, so
  the new-box pop-in (``motion.pop_in``) grows it with the box.
- ``SketchImages``: a background picture's thumbnail, cropped to the sketch's shape: a PNG
  or GIF decoded here one per idle slice, a JPEG or WebP from the helper child while it runs
  (sketches never start it).
- ``MapStills`` (3.1 "Real stills"): when the map rests (``views.MAP_IDLE_MS``), the boxes
  in view ask ``stagestills`` for the game's own still of their opening stage, at the
  sketch's width, as one ask that replaces the map's last one (so a box scrolled away is
  never drawn). Each still replaces its sketch when it arrives; the asking never waits.
  The swap is a plain cut, so Reduce motion has nothing to stop.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

from __future__ import annotations

import bisect
import time
import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from engine.core.constants import CANVAS_SIZE
from engine.tools.editor.scenepreview import (
    LEAD_DEPTH, Stage, lead_in, opening_stage, stage_settings)
from engine.tools.editor.theme import THEME, blend

PICTURE_STRETCH: Final = (1.125, 2.7)       # Compact's 160 × 40 box → 180 × 108 in Pictures
THUMB_INSET: Final = 4                      # px at 100 %, around the sketch
THUMB_HEIGHT: Final = 62                    # the sketch is 172 × 62 at 100 %
TEXT_GAP: Final = 4                         # sketch → name
SLICE_MS: Final = 6                         # one idle slice of sketch drawing
TIP_DELAY_MS: Final = 500                   # the box tooltip (file and line)
PLACEHOLDER: Final = blend("#000000", THEME["map.box"], 0.35)
FIGURE_FALLBACK: Final = THEME["muted"]
CHUNK_CACHE: Final = 5_000                  # scenes' lines kept, by digest
STAGE_W: Final = CANVAS_SIZE[0]
# v1 review finding 5: a background is decoded once per file (and stamp), kept shrunk to
# cover SOURCE_AHEAD × the size first asked for, and each zoom level's thumbnail is cut
# from that; both caches drop their oldest entries, never everything at once.
SOURCE_AHEAD: Final = 2                     # zooming in up to 2× needs no new decode
SOURCES_MAX: Final = 64                     # decoded backgrounds kept
THUMBS_MAX: Final = 256                     # thumbnails kept (picture × size)
STAMP_TTL_S: Final = 1.0                    # a file's stamp is read again after this
LINES: Final = "{n} lines"
ONE_LINE: Final = "1 line"
SEP: Final = " · "


@dataclass(frozen=True, slots=True)
class Sketch:
    """A scene's opening shot as the map draws it. ``known`` False: the scene carries its
    background on from one that couldn't be found (the sketch's own colour is shown)."""

    lines: int
    color: str | None = None                # the background's colour (a colour picture)
    ref: str | None = None                  # the background's picture file (images/…)
    figures: tuple[tuple[float, str], ...] = ()     # each character: x share 0–1, colour
    stage: Stage | None = None              # the opening stage (the game's own still)
    known: bool = True


def lines_text(n: int) -> str:
    return ONE_LINE if n == 1 else LINES.format(n=n)


def detail_text(chapter: str | None, sketch: Sketch | None) -> str:
    """A picture box's second line: its chapter, then its line count once known."""
    parts = [chapter] if chapter else []
    if sketch is not None:
        parts.append(lines_text(sketch.lines))
    return SEP.join(parts)


def count_lines(lines: Sequence[str]) -> int:
    """A scene's lines after its label line that aren't blank or a comment."""
    count = 0
    for line in lines[1:]:
        code = line.strip()
        if code and not code.startswith("#"):
            count += 1
    return count


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


def scene_sketch(lines: Sequence[str], *, lead: Sequence[str] = (),
                 came_from: str | None = None, colors: Mapping[str, str] | None = None,
                 refs: Mapping[str, str] | None = None,
                 color_of: Callable[[str], str | None] = lambda _tag: None,
                 positions: Mapping[str, tuple[float, float]] | None = None,
                 count: int | None = None) -> Sketch:
    """The sketch of a scene whose lines (label line first) are ``lines``, after ``lead``
    (``scenepreview.lead_in``'s lines). ``colors``/``refs``: folded picture name → colour /
    file; ``color_of(tag)``: a character's name colour by sprite tag; ``positions``:
    ``scenepreview.stage_settings``'s."""
    stage: Stage = opening_stage(lines, lead, came_from)
    colors, refs = colors or {}, refs or {}
    positions = positions or stage_settings("")[0]
    color = ref = None
    if stage.background is not None:
        folded = _fold(stage.background)
        color = colors.get(folded)
        if color is None:
            ref = refs.get(folded)
    centre = positions.get("center", (STAGE_W / 2, 0.0))
    figures = []
    for sprite in stage.sprites:
        x = sprite.x if sprite.x is not None else positions.get(sprite.at or "center",
                                                                centre)[0]
        tag = sprite.image.split()[0] if sprite.image.split() else sprite.image
        figures.append((max(0.0, min(1.0, x / STAGE_W)), color_of(tag) or FIGURE_FALLBACK))
    known = not stage.carried or stage.came_from is not None
    return Sketch(count_lines(lines) if count is None else count, color, ref, tuple(figures),
                  stage if known else None, known)


# --- Studio: the scenes' lines and their sketches ------------------------------------------------

class SketchSource:
    """``source(box)`` → the box's ``Sketch`` for Studio window ``win`` and its story map
    ``view`` (module docstring). ``changed()``: the map's data changed (carried-on sketches
    are worked out again); ``assets_changed()``: pictures or characters may have changed."""

    def __init__(self, win: Any, view: Any) -> None:
        self.win, self.view = win, view
        self.gen = 0
        self._chunks: dict[tuple[str, bytes], list[str]] = {}
        self._starts: dict[str, tuple[int, list[int], dict[int, Any]]] = {}
        self._closed: dict[str, tuple[object, dict[int, tuple[bytes, list[str]]]]] = {}
        self._stamps: dict[str, tuple[float, object]] = {}
        self._sketches: dict[str, tuple[tuple, Sketch | None]] = {}
        self._places: tuple[int, dict[str, tuple[str, int]]] | None = None
        self._ins: tuple[int, dict[str, list[Any]]] | None = None
        self._assets: Any = None
        self._assets_stale = True
        self._looks: tuple[dict, dict, Callable[[str], str | None], dict] | None = None

    def changed(self) -> None:
        self.gen += 1

    def assets_changed(self) -> None:
        self._assets_stale = True
        self._looks = None
        self._sketches.clear()

    # -- a scene's lines --------------------------------------------------------------------

    def scene(self, ref: str | None, line: int | None) -> tuple[bytes, list[str]] | None:
        """The digest and lines of the scene whose label is at ``ref:line``, or None."""
        if ref is None or line is None:
            return None
        index = getattr(self.win, "scene_indexes", {}).get(ref)
        record = getattr(self.win, "files", {}).get(ref)
        if index is not None and record is not None and getattr(record, "editable", False):
            found = self._open_scene(index, record, line)
            if found is not None:
                return found
        return self._closed_scene(ref, line)

    def _open_scene(self, index: Any, record: Any, line: int
                    ) -> tuple[bytes, list[str]] | None:
        cached = self._starts.get(index.ref)
        if cached is None or cached[0] != id(index):
            by_line = {start: key for key, start in index.starts.items()}
            cached = self._starts[index.ref] = (id(index), sorted(by_line), by_line)
        _ident, starts, by_line = cached
        key = by_line.get(line)
        if key is None:
            return None
        digest = index.digests.get(key)
        if digest is None:
            return None
        lines = self._chunks.get((index.ref, digest))
        if lines is None:
            at = bisect.bisect_right(starts, line)
            end = f"{starts[at]}.0" if at < len(starts) else "end-1c"
            try:
                text = record.widget.get(f"{line}.0", end)
            except tk.TclError:
                return None
            lines = text.split("\n")
            if at < len(starts) and lines and lines[-1] == "":
                lines.pop()
            if len(self._chunks) >= CHUNK_CACHE:
                self._chunks.clear()
            self._chunks[(index.ref, digest)] = lines
        return digest, lines

    def _closed_scene(self, ref: str, line: int) -> tuple[bytes, list[str]] | None:
        from engine.tools.editor import scenes
        stamp = fresh_stamp(self._stamps, self.win.paths.root, ref)
        cached = self._closed.get(ref)
        if cached is None or cached[0] != stamp:
            from engine.tools.editor.document import ScriptDocument, open_document
            try:
                found = open_document(self.win.paths, ref)
            except ValueError:
                return None
            table: dict[int, tuple[bytes, list[str]]] = {}
            if isinstance(found, ScriptDocument):
                all_lines = found.text.split("\n")
                for _name, first, last in scenes.chunks(found.text):
                    part = all_lines[first - 1:last]
                    table[first] = (scenes.digest("\n".join(part)), part)
            cached = self._closed[ref] = (stamp, table)
        return cached[1].get(line)

    # -- looks --------------------------------------------------------------------------------

    def form_assets(self) -> Any:
        story = getattr(self.win, "story", None)
        if self._assets_stale or self._assets is None:
            self._assets_stale = False
            assets = getattr(story, "_form_assets", None)
            try:
                if assets is None and story is not None:
                    assets = story.form_assets()
                elif assets is not None:
                    assets.refresh()
            except Exception:  # noqa: BLE001  (a sketch never stops the map)
                assets = None
            self._assets = assets
        return self._assets

    def looks(self) -> tuple[dict, dict, Callable[[str], str | None], dict]:
        """Colour pictures, picture files, a tag's name colour, and the stage positions."""
        if self._looks is None:
            assets = self.form_assets()
            colors = dict(getattr(assets, "colors", {}) or {})
            refs = dict(getattr(assets, "image_refs", {}) or {})
            found: dict[str, str | None] = {}

            def color_of(tag: str) -> str | None:
                if tag not in found:
                    try:
                        found[tag] = assets.color(tag) if assets is not None else None
                    except Exception:  # noqa: BLE001
                        found[tag] = None
                return found[tag]

            try:
                config = assets._config_text() if assets is not None else ""
            except Exception:  # noqa: BLE001
                config = ""
            self._looks = (colors, refs, color_of, stage_settings(config)[0])
        return self._looks

    # -- sketches ------------------------------------------------------------------------------

    def _place_of(self, name: str) -> tuple[str, int] | None:
        if self._places is None or self._places[0] != self.gen:
            places: dict[str, tuple[str, int]] = {}
            for entry in getattr(self.view, "labels", ()):
                label = getattr(entry, "name", None)
                if label is None and not isinstance(entry, str):
                    label, where, line = tuple(entry)[:3]
                else:
                    where, line = getattr(entry, "file", None), getattr(entry, "line", None)
                if label is not None and where is not None and line is not None:
                    places.setdefault(label, (where, line))
            self._places = (self.gen, places)
        return self._places[1].get(name)

    def __call__(self, box: Any) -> Sketch | None:
        found = self.scene(box.file, box.line)
        if found is None:
            return None
        digest, lines = found
        cached = self._sketches.get(box.name)
        if cached is not None and cached[0][0] == digest and (
                cached[0][1] is None or cached[0][1] == self.gen):
            return cached[1]
        colors, refs, color_of, positions = self.looks()
        sketch = scene_sketch(lines, colors=colors, refs=refs, color_of=color_of,
                              positions=positions)
        carried = not sketch.known
        if carried:
            lead, came_from = lead_in(box.name, self._ways_in(box.name),
                                      self._scene_lines)
            if lead:
                sketch = scene_sketch(lines, lead=lead, came_from=came_from, colors=colors,
                                      refs=refs, color_of=color_of, positions=positions,
                                      count=sketch.lines)
        self._sketches[box.name] = ((digest, self.gen if carried else None), sketch)
        return sketch

    def _ways_in(self, name: str) -> list[Any]:
        """The arrows ``lead_in`` can follow back from ``name`` (``LEAD_DEPTH`` steps), from
        an index of every arrow's target made once per update, so a carried-on sketch
        never scans every arrow of a large story."""
        if self._ins is None or self._ins[0] != self.gen:
            ins: dict[str, list[Any]] = {}
            for link in getattr(self.view, "links", ()):
                ins.setdefault(link.dst, []).append(link)
            self._ins = (self.gen, ins)
        ins = self._ins[1]
        found: list[Any] = []
        seen, here = {name}, [name]
        for _ in range(LEAD_DEPTH):
            step = []
            for target in here:
                for link in ins.get(target, ()):
                    found.append(link)
                    if link.src not in seen:
                        seen.add(link.src)
                        step.append(link.src)
            if not step:
                break
            here = step
        return found

    def _scene_lines(self, name: str) -> tuple[list[str], int] | None:
        place = self._place_of(name)
        if place is None:
            return None
        found = self.scene(*place)
        return (found[1], place[1]) if found is not None else None


def fresh_stamp(known: dict[str, tuple[float, object]], root: Any, ref: str) -> object:
    """``ref``'s file stamp, read at most once per ``STAMP_TTL_S`` into ``known`` (a paint
    asks for every box in view; finding 5 counted 903 stats in 30 pan steps)."""
    now = time.monotonic()
    found = known.get(ref)
    if found is not None and now - found[0] < STAMP_TTL_S:
        return found[1]
    from engine.tools.editor.helperhub import file_stamp
    stamp = file_stamp(root, ref)
    known[ref] = (now, stamp)
    return stamp


# --- Tk: background thumbnails ---------------------------------------------------------------------

class SketchImages:
    """Background thumbnails for sketches: ``get(ref, w, h)`` is a ``tk.PhotoImage`` of at
    most ``w`` × ``h`` (the picture covering it, cropped to the middle), or None until it is
    made; ``on_ready(ref)`` runs when one is. A PNG or GIF is decoded here, one picture per
    idle slice (about 20 ms for a 1280 × 720 picture, once per file); a JPEG or WebP comes
    from the helper child only while one is already running (the sketch keeps its colour
    otherwise; "Real stills" replace it anyway)."""

    def __init__(self, win: Any, master: tk.Misc, on_ready: Callable[[str], object]) -> None:
        self.win, self.master, self.on_ready = win, master, on_ready
        self.cache: OrderedDict[tuple, tk.PhotoImage | None] = OrderedDict()
        # (ref, stamp) → (the decoded picture shrunk, the size it still covers) or None
        self._sources: OrderedDict[tuple, tuple[tk.PhotoImage, tuple[int, int]] | None] =             OrderedDict()
        self._stamps: dict[str, tuple[float, object]] = {}
        self._todo: dict[tuple, None] = {}
        self._queued = False
        self._listening = False

    def _stamp(self, ref: str) -> object:
        return fresh_stamp(self._stamps, self.win.paths.root, ref)

    def get(self, ref: str, w: int, h: int) -> tk.PhotoImage | None:
        key = (ref, self._stamp(ref), max(1, int(w)), max(1, int(h)))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if ref.lower().endswith((".png", ".gif")):
            source = self._sources.get(key[:2], False)
            if source is None or (source and key[2] <= source[1][0]
                                  and key[3] <= source[1][1]):
                self._sources.move_to_end(key[:2])
                image = None if source is None else self._cover(source[0], key[2], key[3])
                self._keep(key, image)
                return image
            self._todo[key] = None
            if not self._queued:
                self._queued = True
                self.master.after_idle(self._decode_one)
            return None
        hub = getattr(self.win, "helper_hub", None)
        if hub is None:
            return None
        if not self._listening:
            hub.listen(self._reply)
            self._listening = True
        from engine.core.editorreport import HELPER_THUMB_MAX
        reply = hub.runner.thumb(ref, max(8, min(HELPER_THUMB_MAX, key[2])))
        if reply is None:
            return None
        image = None
        if getattr(reply, "ok", False) and getattr(reply, "data", None):
            try:
                image = self._cover(tk.PhotoImage(master=self.master, data=reply.data),
                                    key[2], key[3])
            except tk.TclError:
                image = None
        self._keep(key, image)
        return image

    def _keep(self, key: tuple, image: tk.PhotoImage | None) -> None:
        self.cache[key] = image
        self.cache.move_to_end(key)
        while len(self.cache) > THUMBS_MAX:
            self.cache.popitem(last=False)

    def _decode_one(self) -> None:
        """One queued PNG or GIF: decoded, made to cover its sketch, then drawn."""
        self._queued = False
        if not self._todo:
            return
        key = next(iter(self._todo))
        del self._todo[key]
        ref, _stamp, w, h = key
        image = None
        if key not in self.cache:
            import base64
            from engine.tools.editor.views import read_asset
            source = None
            try:
                info = read_asset(self.win.paths, ref)
                if info.data is not None and info.width and info.height:
                    full = tk.PhotoImage(master=self.master,
                                         data=base64.b64encode(info.data).decode("ascii"))
                    source = self._shrink(full, SOURCE_AHEAD * w, SOURCE_AHEAD * h)
                    image = self._cover(source[0], w, h)
            except (tk.TclError, OSError, ValueError):
                image = source = None
            self._sources[key[:2]] = source
            self._sources.move_to_end(key[:2])
            while len(self._sources) > SOURCES_MAX:
                self._sources.popitem(last=False)
            self._keep(key, image)
            self.on_ready(ref)
        if self._todo and not self._queued:
            self._queued = True
            self.master.after_idle(self._decode_one)

    @staticmethod
    def _shrink(full: tk.PhotoImage, w: int, h: int) -> tuple[tk.PhotoImage, tuple[int, int]]:
        """``full`` shrunk by the largest whole step that still covers ``w`` × ``h``, and
        the size it covers (any size when it wasn't shrunk: nothing finer exists)."""
        fw, fh = full.width(), full.height()
        step = max(1, min(fw // max(1, w), fh // max(1, h)))
        if step == 1:
            return full, (1 << 30, 1 << 30)
        return full.subsample(step), (w, h)

    def _cover(self, full: tk.PhotoImage, w: int, h: int) -> tk.PhotoImage:
        """``full`` shrunk by a whole step so it still covers ``w`` × ``h``, cropped to
        the middle."""
        fw, fh = full.width(), full.height()
        step = max(1, min(fw // max(1, w), fh // max(1, h)))
        small = full if step == 1 else full.subsample(step)
        sw, sh = small.width(), small.height()
        if sw <= w and sh <= h:
            return small
        cw, ch = min(sw, w), min(sh, h)
        left, top = (sw - cw) // 2, (sh - ch) // 2
        part = tk.PhotoImage(master=self.master, width=cw, height=ch)
        part.tk.call(part, "copy", small, "-from", left, top, left + cw, top + ch,
                     "-to", 0, 0)
        return part

    def _reply(self, reply: Any) -> None:
        if getattr(reply, "op", None) == "thumb" and getattr(reply, "ref", None):
            self.on_ready(reply.ref)


# --- Tk: the game's own stills on the boxes (3.1 "Real stills") ---------------------------------

STILL_OWNER: Final = "map"                  # the map's asks in ``stagestills``
STILL_TOP: Final = 0.35                     # where the box's crop of a 16:9 still starts


class MapStills:
    """``stills(box, sketch, w, h)``: the game's own still of a box's opening stage, ``w``
    wide and cropped to ``h`` (``STILL_TOP`` of the rest above it), or None while it isn't
    there (it is then wanted). ``flush()`` asks ``stagestills`` for every still wanted
    since ``begin()``, in view order, as one ask (it replaces the map's older one, so a box
    scrolled away is never drawn); ``on_ready()`` runs as each arrives. ``cancel()``: the
    map wants none (Compact, or the map hidden)."""

    def __init__(self, win: Any, master: tk.Misc, assets: Callable[[], Any],
                 on_ready: Callable[[], object]) -> None:
        self.win, self.master, self.assets, self.on_ready = win, master, assets, on_ready
        self._specs: dict[Stage, Any] = {}
        self._look: tuple[bytes | None, str] | None = None
        self._want: dict[Any, None] = {}
        self._crops: dict[tuple, tk.PhotoImage] = {}

    def _stills(self) -> Any:
        from engine.tools.editor.stagestills import stills_for
        return stills_for(self.win)

    def begin(self) -> None:
        """A new pass: the stages' specs and config.toml are read again."""
        from engine.tools.editor import stagestills as ss
        self._specs.clear()
        self._want.clear()
        config = ss.config_of(self.win)
        self._look = (config, ss.look_of(config))

    def key_of(self, sketch: Sketch, w: int) -> Any:
        from engine.tools.editor import stagestills as ss
        if self._look is None:
            self.begin()
        assert self._look is not None and sketch.stage is not None
        spec = self._specs.get(sketch.stage)
        if spec is None:
            spec = self._specs[sketch.stage] = ss.spec_of(sketch.stage, self.assets(),
                                                          self.win.paths.root)
        return ss.StillKey(spec, int(w), self._look[1])

    def __call__(self, box: Any, sketch: Sketch, w: int, h: int) -> tk.PhotoImage | None:
        if sketch.stage is None:
            return None
        key = self.key_of(sketch, w)
        crop = self._crops.get((key, h))
        if crop is not None:
            return crop
        stills = self._stills()
        still = stills.get(key)
        if still is None:
            self._want[key] = None
            return None
        if not still.ok:
            return None                         # failed: the sketch stays
        full = stills.photo(key, self.master)
        if full is None:
            return None
        crop = self._crop(full, w, h)
        if len(self._crops) >= 256:
            self._crops.clear()
        self._crops[(key, h)] = crop
        return crop

    def _crop(self, full: tk.PhotoImage, w: int, h: int) -> tk.PhotoImage:
        fw, fh = full.width(), full.height()
        if fh <= h and fw <= w:
            return full
        cw, ch = min(fw, w), min(fh, h)
        left, top = (fw - cw) // 2, round((fh - ch) * STILL_TOP)
        part = tk.PhotoImage(master=self.master, width=cw, height=ch)
        part.tk.call(part, "copy", full, "-from", left, top, left + cw, top + ch,
                     "-to", 0, 0)
        return part

    def flush(self) -> None:
        if self._look is None:
            return
        keys, self._want = list(self._want), {}
        try:
            self._stills().ask(STILL_OWNER, keys, self._look[0],
                               lambda _key, _still: self.on_ready())
        except Exception:  # noqa: BLE001  (no helper: the sketches stay)
            pass
        self._look = None

    def cancel(self) -> None:
        self._want.clear()
        self._look = None
        stills = getattr(self.win, "stage_stills", None)
        if stills is not None:
            stills.cancel(STILL_OWNER)


# --- Tk: drawing sketches on the map ---------------------------------------------------------------

def thumb_rect(rect: tuple[float, float, float, float], scale: float
               ) -> tuple[float, float, float, float]:
    """The sketch's place inside a picture box's canvas rectangle."""
    x0, y0, x1, _y1 = rect
    inset = THUMB_INSET * scale
    return x0 + inset, y0 + inset, x1 - inset, y0 + inset + THUMB_HEIGHT * scale


def draw_figures(canvas: tk.Canvas, rect: tuple[float, float, float, float],
                 figures: Iterable[tuple[float, str]], tags: tuple[str, ...]) -> list[int]:
    """Each character as a head and shoulders in its name colour, standing on the sketch's
    bottom edge at its stage position."""
    x0, y0, x1, y1 = rect
    th = y1 - y0
    head, wide, neck = 0.09 * th, 0.34 * th, 0.24 * th
    items: list[int] = []
    for share, color in figures:
        fx = max(x0 + wide / 2, min(x1 - wide / 2, x0 + share * (x1 - x0)))
        edge = blend("#000000", color, 0.45)
        items.append(canvas.create_arc(fx - wide / 2, y1 - neck, fx + wide / 2, y1 + neck,
                                       start=0, extent=180, style="chord", fill=color,
                                       outline=edge, tags=tags))
        top = y1 - neck - 1 - 2 * head
        items.append(canvas.create_oval(fx - head, top, fx + head, top + 2 * head,
                                        fill=color, outline=edge, tags=tags))
    return items


@dataclass(slots=True)
class _Drawn:
    found: Any                              # the BoxItems it was drawn into
    sketch: Sketch | None
    items: list[int]
    still: bool = False


class SketchPainter:
    """Sketches on ``painter``'s picture boxes (module docstring). ``source(box)`` gives a
    box's sketch; ``images.get(ref, w, h)`` a background's thumbnail; ``still(box, sketch,
    w, h)`` (3.1 "Real stills") the game's own picture or None."""

    def __init__(self, painter: Any, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.painter = painter
        self.source: Callable[[Any], Sketch | None] | None = None
        self.images: Any = None
        self.still: Callable[[Any, Sketch, int, int], Any] | None = None
        self.known: dict[str, Sketch | None] = {}       # the last sketch seen per box
        self.drawn: dict[str, _Drawn] = {}
        self._clock = clock
        self._queued = False
        self._stills_on = False
        self._passing = False                   # a stills pass goes on in the next slice

    def clear(self) -> None:
        self.drawn.clear()

    # -- one box --------------------------------------------------------------------------------

    def put_known(self, box: Any, found: Any, *, layer: bool) -> None:
        """A picture box just drawn gets the sketch last seen for it, at once (so a pop-in
        grows it with the box); the idle pass checks it again."""
        if box.name in self.known:
            self._draw(box, found, self.known[box.name], layer=layer, still=None)

    def paint_name(self, name: str) -> bool:
        """``paint`` for label ``name``'s box, when it is shown in Pictures."""
        layout = self.painter.layout
        index = layout.index_of(name) if layout is not None and self.painter.pictures             else None
        return index is not None and self.paint(layout.boxes[index])

    def paint(self, box: Any, *, stills: bool = False) -> bool:
        """Box ``box``'s sketch (or still) up to date; True when it drew anything."""
        painter = self.painter
        found = painter.boxes.get(box.name)
        if found is None or getattr(found, "thumb", None) is None or self.source is None:
            return False
        try:
            sketch = self.source(box)
        except Exception:  # noqa: BLE001  (a sketch never stops the map)
            sketch = None
        self.known[box.name] = sketch
        still = None
        if stills and sketch is not None and sketch.known and self.still is not None:
            x0, y0, x1, y1 = thumb_rect(painter.rect_of(box), painter.scale)
            try:
                still = self.still(box, sketch, round(x1 - x0), round(y1 - y0))
            except Exception:  # noqa: BLE001
                still = None
        drawn = self.drawn.get(box.name)
        if drawn is not None and drawn.found is found and drawn.sketch == sketch \
                and (still is None or drawn.still):
            return False                        # as drawn (a still stays while it's true)
        self._draw(box, found, sketch, layer=True, still=still)
        return True

    def _draw(self, box: Any, found: Any, sketch: Sketch | None, *, layer: bool,
              still: Any) -> None:
        painter = self.painter
        canvas, owner = painter.canvas, painter.owner
        old = self.drawn.get(box.name)
        if old is not None and old.found is found:
            for item in old.items:
                canvas.delete(item)
                owner.pop(item, None)
                if item in found.items:
                    found.items.remove(item)
        rect = thumb_rect(painter.rect_of(box), painter.scale)
        tags = ("box", "sketch")
        items: list[int] = []
        fill = PLACEHOLDER
        if sketch is not None and sketch.known and sketch.color:
            fill = sketch.color
        canvas.itemconfigure(found.thumb, fill=fill)
        if still is not None:
            items.append(canvas.create_image((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2,
                                             image=still, tags=tags))
        elif sketch is not None:
            if sketch.known and sketch.ref and self.images is not None:
                image = self.images.get(sketch.ref, round(rect[2] - rect[0]),
                                        round(rect[3] - rect[1]))
                if image is not None:
                    items.append(canvas.create_image((rect[0] + rect[2]) / 2,
                                                     (rect[1] + rect[3]) / 2, image=image,
                                                     tags=tags))
            items += draw_figures(canvas, rect, sketch.figures, tags)
        for item in items:
            owner[item] = ("box", box.name)
            found.items.append(item)
            if layer and painter.markers:
                painter.put(item, "boxes")
        if found.where is not None:
            canvas.itemconfigure(found.where, text=painter.detail_line(box, sketch))
        self.drawn[box.name] = _Drawn(found, sketch, items, still is not None)

    # -- boxes in view ---------------------------------------------------------------------------

    def schedule(self, *, stills: bool = False) -> None:
        """Draw the boxes in view on idle (``stills``: the game's own pictures too)."""
        self._stills_on = self._stills_on or stills
        if not self._queued and self.painter.pictures:
            self._queued = True
            self.painter._idle(self.paint_visible)

    def visible_boxes(self) -> list[Any]:
        painter = self.painter
        layout = painter.layout
        if layout is None:
            return []
        left, top, right, bottom = painter.visible()
        return [box for box in layout.boxes
                if (r := painter.rect_of(box))[2] > left and r[0] < right
                and r[3] > top and r[1] < bottom]

    def paint_visible(self, budget_ms: float = SLICE_MS) -> None:
        """One idle slice: the boxes in view, for ``budget_ms``; the next slice is
        scheduled while any are left."""
        self._queued = False
        painter = self.painter
        if not painter.pictures or painter.layout is None:
            return
        stills, self._stills_on = self._stills_on, False
        stills = stills and self.still is not None
        start = self._clock()
        boxes = self.visible_boxes()
        if stills and hasattr(self.still, "begin") and not self._passing:
            self.still.begin()
        for at, box in enumerate(boxes):
            self.paint(box, stills=stills)
            if (self._clock() - start) * 1000 >= budget_ms and at + 1 < len(boxes):
                self._passing = stills
                self._stills_on = self._stills_on or stills
                self.schedule()
                return
        self._passing = False
        if stills and hasattr(self.still, "flush"):
            self.still.flush()

    def image_ready(self, ref: str) -> None:
        """A background thumbnail arrived: the boxes in view showing it are drawn again."""
        for name, drawn in list(self.drawn.items()):
            if drawn.sketch is not None and drawn.sketch.ref == ref and not drawn.still:
                drawn.sketch = None                     # differs, so ``paint`` redraws it
        self.schedule()


__all__ = ["FIGURE_FALLBACK", "LINES", "MapStills", "PICTURE_STRETCH", "STILL_OWNER", "PLACEHOLDER", "SLICE_MS", "Sketch",
           "SketchImages", "SketchPainter", "SketchSource", "TEXT_GAP", "THUMB_HEIGHT",
           "THUMB_INSET", "TIP_DELAY_MS", "count_lines", "detail_text", "draw_figures",
           "lines_text", "scene_sketch", "thumb_rect"]
