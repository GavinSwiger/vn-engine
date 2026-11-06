"""Stage stills: the game's own picture of a stage, cached per Studio window (Studio UX
shared foundation, 2026-11-06; used by 2.5 Stage preview at any line and 3.1 Picture boxes
on the map, later by drag on the stage, the asset shelf and Start page thumbnails).

Why this module exists: Studio sketches a stage in Tk at once (``scenepreview``), but only
the engine draws it as the player sees it: the art scaled by ``[stage] art_height``, the
``[stage.positions]``, the text box's frame, fonts and name tab. The helper child draws a
``stage`` still with that real code (``tools/helper.draw_stage_still``); this module asks
for them without ever blocking Tk's thread and keeps them.

**API**

- ``StageSpec``: what to draw, frozen and hashable: ``background`` (an image name or
  None), ``images`` (each name used, with its ref or ``#rrggbb`` colour), ``sprites``
  (``(tag, image, at, zoom, flip)``; ``at`` a position name or ``(x,)``/``(x, y)``), and
  the text box: ``who`` (the shown name; None: narration), ``color`` (``#rrggbb``; None:
  the name tab's colour) and ``text`` (None: no box). ``stamps`` holds the pictures' file
  stamps, so a changed picture is a new spec; it is not sent. ``request()`` is the
  helper's ``stage`` object. Studio resolves every name, so the child runs no author code.
- ``spec_of(stage, assets, game_dir)``: the spec of a ``scenepreview.Stage`` (its optional
  ``say`` gives the text box), resolving names as the sketch does through the window's
  ``WindowAssets`` (``image_refs``, ``colors``). A name that resolves to nothing is left
  out, as the sketch leaves it out.
- ``StillKey(spec, width, look)``: the cache key. ``look`` is ``look_of(config_text)``,
  config.toml's digest (the scheme, the text box's look, the positions). The spec is what a
  script's digest and a file and line resolve to: two lines that show the same stage share
  one still, and an edit elsewhere in the script keeps it.
- ``stills_for(win) -> StageStills``: the window's one cache, on the window's helper child
  (``helperhub.hub_for``). ``config_of(win)`` is config.toml's unsaved text, to pass along.

  - ``get(key) -> Still | None``: a finished still (``ok`` with ``data``, base64 PNG, or a
    ``reason``); never asks.
  - ``ask(owner, keys, config=None, on_ready=None)``: ``owner`` (any string, such as
    ``"preview"`` or ``"map"``) wants exactly ``keys`` now, most wanted first; ``config``
    is config.toml's unsaved bytes (None: the saved file). It replaces what ``owner``
    asked before, so a key no owner wants any more is never sent (stale). A key cached or
    in flight isn't asked again (coalesced). ``on_ready(key, still)`` runs on Tk's thread
    (from the window's poll) as each of ``owner``'s keys arrives.
  - ``cancel(owner)``: the same as ``ask(owner, ())``.
  - ``photo(key, master) -> tk.PhotoImage | None``: the still decoded for Tk.

**Rules**

- **Never blocks.** Asking only queues bytes for the helper's writer thread
  (``HelperRunner``). One still is in flight at a time (the child draws one at a time,
  about 25-60 ms warm); the next is sent when its reply arrives, the most recent owner's
  first.
- **Bounded.** At most ``STILLS_MAX_ENTRIES`` stills and ``STILLS_MAX_BYTES`` of PNG data,
  least recently used out first, and at most ``PHOTOS_MAX`` decoded photos. Failures are
  kept too, so a broken config.toml isn't asked again until its text changes.
- **Errors.** Script errors don't matter (the spec comes from the text, and the child loads
  no story). A config the game can't load, a missing or crashed helper, or a stage too large
  to send give a failed ``Still``: the caller keeps its sketch.

Imports the standard library, ``tkinter`` (only in ``photo``) and its own package; never
pygame.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, NamedTuple

from engine.core.editorreport import (
    HELPER_STAGE_MAX_IMAGES,
    HELPER_STAGE_MAX_SPRITES,
    HELPER_STAGE_NAME_MAX,
    HELPER_STAGE_TEXT_MAX,
)
from engine.tools.editor.helperrunner import HelperReply, HelperRunnerLike, file_stamp

STILLS_MAX_ENTRIES: Final = 256
STILLS_MAX_BYTES: Final = 32 * 1024 * 1024     # base64 PNG data kept
PHOTOS_MAX: Final = 48                          # decoded Tk photos kept
LOOKS_MAX: Final = 8                            # config texts kept to send
SAVED_LOOK: Final = "saved"                     # ``look_of(None)``: the saved config.toml


@dataclass(frozen=True, slots=True)
class StageSpec:
    """What a stage still shows (module docstring)."""

    background: str | None = None
    images: tuple[tuple[str, str], ...] = ()
    sprites: tuple[tuple[str, str, object, float, bool], ...] = ()
    who: str | None = None
    color: str | None = None
    text: str | None = None
    stamps: tuple = ()

    def request(self) -> dict:
        """The helper's ``stage`` object (``tools/helper.parse_stage``)."""
        return {"bg": self.background, "images": dict(self.images),
                "sprites": [[tag, image, list(at) if isinstance(at, tuple) else at, zoom, flip]
                            for tag, image, at, zoom, flip in self.sprites],
                "who": self.who, "color": self.color, "text": self.text}


class StillKey(NamedTuple):
    spec: StageSpec
    width: int
    look: str


@dataclass(frozen=True, slots=True)
class Still:
    """A finished still: ``data`` base64 PNG (``ok``), else a ``reason``."""

    ok: bool
    data: str | None = None
    width: int = 0
    height: int = 0
    reason: str | None = None


def look_of(config_text: str | bytes | None) -> str:
    """config.toml's digest for ``StillKey.look`` (None: the saved file)."""
    if config_text is None:
        return SAVED_LOOK
    data = config_text.encode("utf-8") if isinstance(config_text, str) else config_text
    return hashlib.blake2b(data, digest_size=8).hexdigest()


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


def _color(value: object) -> str | None:
    """``#rrggbb`` (``#rgb`` widened), else None."""
    if not isinstance(value, str) or not value.startswith("#"):
        return None
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if len(digits) != 6 or any(c not in "0123456789abcdefABCDEF" for c in digits):
        return None
    return "#" + digits.lower()


def _name(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= HELPER_STAGE_NAME_MAX \
        else None


def spec_of(stage: Any, assets: Any, game_dir: Path | None = None) -> StageSpec:
    """``StageSpec`` of ``stage`` (a ``scenepreview.Stage``: ``background``, ``sprites``
    with ``image``/``at``/``x``/``zoom``, and an optional ``say`` with ``who``/``color``/
    ``text``), resolving names through ``assets`` (``image_refs``, ``colors``; None: no
    names resolve). ``game_dir`` adds the file stamps."""
    refs: dict = getattr(assets, "image_refs", None) or {}
    colors: dict = getattr(assets, "colors", None) or {}
    images: dict[str, str] = {}
    stamps: list = []

    def resolve(name: str) -> str | None:
        if _name(name) is None:
            return None
        if name in images:
            return name
        folded = _fold(name)
        color = _color(colors.get(folded))
        ref = refs.get(folded)
        if color is None and ref is None:   # ``show hana``: a picture of that character
            tag = folded.split(" ", 1)[0]
            found = sorted(r for n, r in refs.items() if n == tag or n.startswith(tag + " "))
            ref = found[0] if found else None
        value = color or ref
        if value is None or _name(value) is None or len(images) >= HELPER_STAGE_MAX_IMAGES:
            return None
        images[name] = value
        if ref is not None and color is None and game_dir is not None:
            stamps.append((ref, file_stamp(game_dir, ref)))
        return name

    background = resolve(stage.background) if getattr(stage, "background", None) else None
    sprites: list[tuple[str, str, object, float, bool]] = []
    tags: set[str] = set()
    for sprite in getattr(stage, "sprites", ())[-HELPER_STAGE_MAX_SPRITES:]:
        name = resolve(sprite.image)
        if name is None:
            continue
        tag = name.split()[0]
        while tag in tags:
            tag += "_"
        tags.add(tag)
        at: object = (float(sprite.x),) if sprite.x is not None else \
            (_name(sprite.at) or "center")
        zoom = min(100.0, max(0.01, float(sprite.zoom)))
        sprites.append((tag, name, at, zoom, False))
    say = getattr(stage, "say", None)
    who = color = text = None
    if say is not None:
        who = _name(getattr(say, "who", None))
        color = _color(getattr(say, "color", None))
        text = str(getattr(say, "text", "") or "")[:HELPER_STAGE_TEXT_MAX]
    return StageSpec(background, tuple(images.items()), tuple(sprites), who, color, text,
                     tuple(stamps))


class StageStills:
    """The cache and the asking (module docstring). ``runner_of()`` gives the helper
    runner (``HelperRunnerLike``; called only when a still is sent); ``on_reply`` must get
    every ``HelperReply`` the runner's poll gives (``stills_for`` listens on the hub)."""

    def __init__(self, runner_of: Callable[[], HelperRunnerLike], *,
                 entries: int = STILLS_MAX_ENTRIES, max_bytes: int = STILLS_MAX_BYTES,
                 photos: int = PHOTOS_MAX) -> None:
        self._runner_of = runner_of
        self.entries, self.max_bytes, self.photos = entries, max_bytes, photos
        self._cache: OrderedDict[StillKey, Still] = OrderedDict()
        self._bytes = 0
        self._photos: OrderedDict[StillKey, Any] = OrderedDict()
        self._owners: dict[str, tuple[list[StillKey], Callable | None]] = {}
        self._configs: OrderedDict[str, bytes | None] = OrderedDict()
        self._inflight: tuple[int, StillKey] | None = None
        self.sent = 0                       # stills asked of the helper (tests read it)

    # --- Reading -----------------------------------------------------------------------

    def get(self, key: StillKey) -> Still | None:
        found = self._cache.get(key)
        if found is not None:
            self._cache.move_to_end(key)
        return found

    def __len__(self) -> int:
        return len(self._cache)

    @property
    def bytes(self) -> int:
        return self._bytes

    @property
    def in_flight(self) -> StillKey | None:
        return self._inflight[1] if self._inflight is not None else None

    def wanted(self) -> list[StillKey]:
        """Every key an owner waits for that isn't cached, the next one to send first."""
        out: dict[StillKey, None] = {}
        for owner in reversed(list(self._owners)):
            for key in self._owners[owner][0]:
                if key not in self._cache:
                    out.setdefault(key)
        return list(out)

    def photo(self, key: StillKey, master: Any) -> Any:
        """The still of ``key`` as a ``tk.PhotoImage`` on ``master`` (None: none, or it
        failed, or Tk can't read it)."""
        found = self._photos.get(key)
        if found is not None:
            self._photos.move_to_end(key)
            return found
        still = self.get(key)
        if still is None or not still.ok or not still.data:
            return None
        import tkinter as tk
        try:
            image = tk.PhotoImage(master=master, data=still.data)
        except tk.TclError:
            return None
        self._photos[key] = image
        while len(self._photos) > self.photos:
            self._photos.popitem(last=False)
        return image

    # --- Asking ------------------------------------------------------------------------

    def ask(self, owner: str, keys: Iterable[StillKey], config: bytes | None = None,
            on_ready: Callable[[StillKey, Still], object] | None = None) -> None:
        keys = list(dict.fromkeys(keys))
        self._owners.pop(owner, None)
        if keys:
            self._owners[owner] = (keys, on_ready)     # the most recent owner goes last
        for look in dict.fromkeys(key.look for key in keys):
            self._configs.pop(look, None)
            self._configs[look] = config
            while len(self._configs) > LOOKS_MAX:
                self._configs.popitem(last=False)
        self._pump()

    def cancel(self, owner: str) -> None:
        self.ask(owner, ())

    def clear(self) -> None:
        """Forget every still (the owners' asks stay)."""
        self._cache.clear()
        self._photos.clear()
        self._bytes = 0
        self._pump()

    # --- Replies -----------------------------------------------------------------------

    def on_reply(self, reply: HelperReply) -> None:
        if not isinstance(reply, HelperReply) or reply.op != "still" \
                or reply.kind != "stage" or self._inflight is None \
                or reply.serial != self._inflight[0]:
            return
        key = self._inflight[1]
        self._inflight = None
        still = Still(True, reply.data, reply.width, reply.height) if reply.ok \
            and reply.data else Still(False, reason=reply.reason or "no picture")
        self._put(key, still)
        for keys, on_ready in list(self._owners.values()):
            if on_ready is not None and key in keys:
                on_ready(key, still)
        self._pump()

    # --- Internals ---------------------------------------------------------------------

    def _put(self, key: StillKey, still: Still) -> None:
        old = self._cache.pop(key, None)
        if old is not None:
            self._bytes -= len(old.data or "")
        self._photos.pop(key, None)
        self._cache[key] = still
        self._bytes += len(still.data or "")
        while self._cache and (len(self._cache) > self.entries or self._bytes > self.max_bytes):
            gone, dropped = self._cache.popitem(last=False)
            self._bytes -= len(dropped.data or "")
            self._photos.pop(gone, None)

    def _pump(self) -> None:
        if self._inflight is not None:
            return
        wanted = self.wanted()
        if not wanted:
            return
        key = wanted[0]
        serial = self._runner_of().still("stage", key.width, self._configs.get(key.look),
                                         key.spec.request())
        self._inflight = (serial, key)
        self.sent += 1


def config_of(win: Any) -> bytes | None:
    """config.toml's editor text (unsaved changes included) as bytes, else None (the
    saved file)."""
    from engine.script.assetgroups import CONFIG_REF
    try:
        record = win.record_for(CONFIG_REF)
        return record.widget.get("1.0", "end-1c").encode("utf-8") if record.editable \
            else None
    except Exception:  # noqa: BLE001  (no config open: the saved file)
        return None


def stills_for(win: Any) -> StageStills:
    """The window's ``StageStills``, made on first use, on the window's helper child."""
    stills = getattr(win, "stage_stills", None)
    if stills is None:
        from engine.tools.editor.helperhub import hub_for
        hub = hub_for(win)
        stills = win.stage_stills = StageStills(lambda: hub.runner)
        hub.listen(stills.on_reply)
    return stills


__all__ = ["PHOTOS_MAX", "STILLS_MAX_BYTES", "STILLS_MAX_ENTRIES", "StageSpec", "StageStills",
           "Still", "StillKey", "config_of", "look_of", "spec_of", "stills_for"]
