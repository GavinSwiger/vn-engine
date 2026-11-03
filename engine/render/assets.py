"""Images, scaled variants, fonts, and text lines, in one memory budget.

Why this module exists: every image and font a game uses comes through here, so this is
where the asset promises are kept. Files are read only through ``GamePaths.read_file``
(containment, SEC-F01-01); image headers are checked before decoding (SEC-F01-06); a bad
reference shows a placeholder and logs once instead of stopping the game (PR-F01-55, 56);
an asset is loaded once and reused (PR-F01-58); and source images, scaled variants, text
lines, font files, and font objects all share the one ``[engine] cache_mb`` budget
(PR-F01-59, ADR-0001 consequences). The costs of bad references are bounded
(SEC-F01-05): the failed-reference map, the placeholder surfaces, and the warn-once set
each have a fixed size.

Fonts (F05 §7.6): ``font(None, …, bundled=)`` gives one of the four bundled Noto Sans faces
(ADR-0004 and its amendment); ``synth=`` thickens or slants an author's font on a font object
of its own; ``check()`` validates a font or image ref at install time without logging, so the
caller's warning (W43) is the only one.

Conversion follows spike S0 (``tests/perf/S0-results.md``): ``convert_alpha()`` needs the
window's ``get_surface()`` to have been called once (``GameWindow`` does that before any
asset loads); where it is not available (no window, e.g. tests), the fallback converts
against a 1×1 per-pixel-alpha surface, because ``convert(32, SRCALPHA)`` returns a surface
that blits as an opaque box (S0 note 4). Loaded images are always converted, since PNGs
decode with a different channel order than the framebuffer (S0 note 10).
"""

import io
import logging
import math
import time as _time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pygame

from engine.core.constants import (
    ASSET_MAX_BYTES,
    ASSET_PROBLEM_LOG_LIMIT,
    ENTRY_OVERHEAD,
    FONT_OBJECT_COST,
    FONT_SUFFIXES,
    IMAGE_MAX_PIXELS,
    IMAGE_MAX_SIDE,
    IMAGE_SUFFIXES,
    MB,
    MISSING_REF_CACHE_ENTRIES,
    PLACEHOLDER_CACHE_ENTRIES,
    REF_MAX_CHARS,
)
from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
)
from engine.core.imageheader import image_dimensions
from engine.core.logsetup import get_logger
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths, check_ref, engine_data_dir
from engine.core.redact import echo
from engine.core.timing import GameTime
from engine.render.canvas import RenderQuality
from engine.render.placeholder import LABEL_FONT_PX, PLACEHOLDER_SIZE, make_placeholder
from engine.render.text import Face, FontHandle, Synth  # Face, Synth re-exported

DEFAULT = "<default>"                      # cache-key stand-in for the bundled font
DEFAULT_FONT_FILE = "fonts/NotoSans-Regular.ttf"   # under engine_data_dir()
ENGINE_ICON_FILE = "icon.png"                      # under engine_data_dir()
CHECK_FONT_PX = 20                         # size at which check() test-measures a font


# Cache-key names and files (under engine_data_dir()) of the bundled faces.
BUNDLED_NAMES: dict[Face, str] = {
    Face.REGULAR: DEFAULT,
    Face.BOLD: "<default-bold>",
    Face.ITALIC: "<default-italic>",
    Face.BOLD_ITALIC: "<default-bold-italic>",
}
BUNDLED_FILES: dict[Face, str] = {
    Face.REGULAR: DEFAULT_FONT_FILE,
    Face.BOLD: "fonts/NotoSans-Bold.ttf",
    Face.ITALIC: "fonts/NotoSans-Italic.ttf",
    Face.BOLD_ITALIC: "fonts/NotoSans-BoldItalic.ttf",
}
_BUNDLED_BY_NAME: dict[str, Face] = {name: face for face, name in BUNDLED_NAMES.items()}


@dataclass(frozen=True)
class AssetProblem:
    """Why ``check()`` found a reference unusable (F05 W43)."""
    kind: Literal["missing", "unreadable"]
    suggestion: str | None          # the correctly cased ref, for "missing" only
SLOW_LOAD_S = 0.008                        # in-loop loads slower than this suggest preload()

MSG_TOO_MANY_PROBLEMS = ("Too many asset problems in this session — further asset "
                         "warnings and errors are not logged")
DAMAGED_IMAGE = "file is damaged or not a PNG, JPEG, or WebP image"
DAMAGED_FONT = "file is damaged or not a TrueType or OpenType font"

_log = get_logger("assets")
_WARNING = logging.WARNING
_ERROR = logging.ERROR


@dataclass(frozen=True, eq=False)
class ImageRef:
    ref: str                          # as written by the author
    size: tuple[int, int]             # canvas units == source pixel size
    is_placeholder: bool
    _key: tuple                       # cache key of the source surface

    @property
    def label(self) -> str | None:
        """The text printed on a placeholder (None for a real image)."""
        return self._key[1] if self.is_placeholder else None


class AssetHold:
    """Keeps a set of images from being evicted until ``release()`` (PR-F01-60)."""

    def __init__(self, cache: SizedLru, keys: list[tuple]) -> None:
        self._cache = cache
        self._keys = keys
        for key in keys:
            cache.hold(key)

    def release(self) -> None:
        keys, self._keys = self._keys, []
        for key in keys:
            self._cache.release(key)

    def __enter__(self) -> "AssetHold":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


class _Problem(Exception):
    """Internal: why an asset could not be used (level and log message)."""

    def __init__(self, level: int, message: str, *, label: str | None = None,
                 reason: str = "", missing: bool = False,
                 suggestion: str | None = None) -> None:
        super().__init__(message)
        self.level = level
        self.message = message
        self.label = label          # placeholder label override (blocked paths)
        self.reason = reason        # the part after the ref, for the icon message
        self.missing = missing      # check(): "missing" rather than "unreadable"
        self.suggestion = suggestion

    def as_asset_problem(self) -> AssetProblem:
        if self.missing:
            return AssetProblem("missing", self.suggestion)
        return AssetProblem("unreadable", None)


class AssetManager:
    """The asset API for screens and later features (F04, F05, F09)."""

    def __init__(self, paths: GamePaths | None, *, budget_bytes: int, scale_filter: str,
                 time: GameTime, format_source: Callable[[], pygame.Surface | None]) -> None:
        """format_source is App's window.framebuffer: a real Surface exists from window
        creation on, so conversion never needs a bound Canvas (review item 19)."""
        self.paths = paths
        self.scale_filter = scale_filter
        self.time = time
        self._format_source = format_source
        self._cache: SizedLru = SizedLru(budget_bytes, on_evict=self._on_evict)
        self._failed: OrderedDict[str, ImageRef] = OrderedDict()
        self._failed_fonts: OrderedDict[str, None] = OrderedDict()
        self._check_problems: OrderedDict[tuple[str, str], AssetProblem] = OrderedDict()
        self._placeholders: OrderedDict[str, pygame.Surface] = OrderedDict()
        self._problem_keys: set[str] = set()
        self._problem_limit_logged = False
        self._engine_icon: pygame.Surface | None = None
        self.in_frame_loop = False      # set by App while the loop runs (slow-load hint)

    @property
    def cache(self) -> SizedLru:
        """Tests and the overlay read it; bootstrap pins the default font file."""
        return self._cache

    # --- images -----------------------------------------------------------------------------

    def image(self, ref: str) -> ImageRef:
        """The image at ``ref`` (game-relative), loaded once and cached. Never raises for
        content problems: a placeholder ``ImageRef`` is returned instead and the problem
        is logged once per reference (§7.11.1)."""
        key = ("img", ref)
        surface = self._cache.get(key, self.time.frame)
        if surface is not None:
            return ImageRef(ref, surface.get_size(), False, key)
        failed = self._failed.get(ref)
        if failed is not None:
            self._failed.move_to_end(ref)
            return failed
        try:
            surface = self._load_image(ref)
        except _Problem as problem:
            self._problem(ref, problem.level, problem.message)
            placeholder = ImageRef(ref, PLACEHOLDER_SIZE, True,
                                   ("placeholder", problem.label or echo(ref)))
            if len(ref) <= REF_MAX_CHARS:
                self._failed[ref] = placeholder
                if len(self._failed) > MISSING_REF_CACHE_ENTRIES:
                    self._failed.popitem(last=False)
            return placeholder
        return ImageRef(ref, surface.get_size(), False, key)

    def surface(self, image: ImageRef) -> pygame.Surface:
        """The source surface of ``image`` (re-loaded if the cache dropped it; the
        placeholder for a placeholder ``ImageRef``). Marks it as used this frame."""
        if image.is_placeholder:
            return self._placeholder_surface(image._key[1])
        surface = self._cache.get(image._key, self.time.frame)
        if surface is None:
            try:
                surface = self._load_image(image.ref)
            except _Problem as problem:
                self._problem(image.ref, problem.level, problem.message)
                return self._placeholder_surface(problem.label or echo(image.ref))
        return surface

    def scaled(self, image: ImageRef, scale_x: float, scale_y: float,
               quality: RenderQuality) -> pygame.Surface:
        """``image`` at device size (§7.6 step 4). Scale 1.0 → the source itself. FINAL:
        ``smoothscale`` (or ``scale`` for the ``pixel`` filter), cached in the budget;
        FAST: ``transform.scale``, never cached."""
        source = self.surface(image)
        if scale_x == 1.0 and scale_y == 1.0:
            return source
        width, height = source.get_size()
        target = (max(1, math.floor(width * scale_x + 0.5)),
                  max(1, math.floor(height * scale_y + 0.5)))
        # F04 I-8: one FINAL-variant path, so the stage and the prefetcher share its keys.
        return self.variant(image, target, quality)[0]

    def variant(self, image: ImageRef, size_px: tuple[int, int], quality: RenderQuality, *,
                flip_x: bool = False, crop: tuple[int, int, int, int] | None = None
                ) -> tuple[pygame.Surface, tuple[int, int]]:
        """``image`` at exactly ``size_px`` device pixels, optionally mirrored left to right,
        or only the ``crop`` part of that full variant (F04 ``04`` §5.3, §7.4). Returns
        ``(surface, its offset in the full variant)``.

        ``crop`` is ``(x, y, w, h)`` in the full (mirrored, when ``flip_x``) variant's pixels.
        Only the matching source sub-rectangle is scaled (its edges floored and ceiled to
        whole source pixels, and mirrored when flipped), so a huge zoomed sprite never
        becomes a huge surface (TR-F04-06) and each edge stays within 1 device pixel of the
        full variant's. FINAL: ``smoothscale`` (``scale`` for the ``pixel`` filter), cached
        in the budget under ``("variant", image._key, size_px, flip_x, crop,
        scale_filter)``; FAST: ``transform.scale``, never cached. ``size_px`` equal to the
        source size with no flip and no crop gives the source itself."""
        source = self.surface(image)
        sw, sh = source.get_size()
        width, height = max(1, int(size_px[0])), max(1, int(size_px[1]))
        if crop is None and not flip_x and (width, height) == (sw, sh):
            return source, (0, 0)
        key = None
        if quality is RenderQuality.FINAL:
            key = self._variant_key(image._key, (width, height), flip_x, crop)
            cached = self._cache.get(key, self.time.frame)
            if cached is not None:
                return cached[0], cached[1]
        if crop is None:
            piece, offset = source, (0, 0)
            target = (width, height)
        else:
            piece, target, offset = _crop_source(source, (width, height), crop, flip_x)
        if piece.get_size() == target:
            surface = piece if flip_x else piece.copy()   # flip() below makes a new one
        elif quality is RenderQuality.FAST or self.scale_filter == "pixel":
            surface = pygame.transform.scale(piece, target)
        else:
            surface = pygame.transform.smoothscale(piece, target)
        if flip_x:
            surface = pygame.transform.flip(surface, True, False)
        if key is not None:
            self._cache.put(key, (surface, offset), _surface_cost(surface), self.time.frame)
        return surface, offset

    def cached_variant(self, image: ImageRef, size_px: tuple[int, int], *, flip_x: bool = False,
                       crop: tuple[int, int, int, int] | None = None
                       ) -> tuple[pygame.Surface, tuple[int, int]] | None:
        """F38 (ADR-0007 amendment): what ``variant(image, size_px, FINAL, …)`` would return,
        but only when it is in the cache now (the source itself at 1:1 with no flip or
        crop); None otherwise. Never loads, scales, or logs; a hit counts as a use."""
        if image.is_placeholder:
            return None
        width, height = max(1, int(size_px[0])), max(1, int(size_px[1]))
        frame = self.time.frame
        if crop is None and not flip_x and (width, height) == image.size:
            source = self._cache.get(image._key, frame)
            return None if source is None else (source, (0, 0))
        cached = self._cache.get(self._variant_key(image._key, (width, height), flip_x, crop),
                                 frame)
        return None if cached is None else (cached[0], cached[1])

    def adopt(self, ref: str, source: pygame.Surface | None,
              variants: dict[tuple, pygame.Surface]) -> None:
        """F04 step 7 (prefetch): put a source decoded and converted elsewhere into the cache
        under ``("img", ref)``, and its pre-scaled variants under ``variant()``'s exact keys
        (I-8), each charged like a load. Main thread only. ``source`` None (F38: a variant
        made for a source already cached) adds the variants only."""
        if source is not None:
            self._cache.put(("img", ref), source, _surface_cost(source), self.time.frame)
        for key, surface in variants.items():
            self._cache.put(key, (surface, (0, 0)), _surface_cost(surface), self.time.frame)

    def is_cached(self, ref: str) -> bool:
        """Whether the source image of ``ref`` is in the cache now (no load, no LRU touch)."""
        return ("img", ref) in self._cache

    def variant_key(self, ref: str, size_px: tuple[int, int], flip_x: bool = False) -> tuple:
        """The cache key ``variant()`` uses for the uncropped FINAL variant of the image file
        ``ref`` at ``size_px`` (I-8: the prefetcher adopts under exactly this key)."""
        return self._variant_key(("img", ref), (int(size_px[0]), int(size_px[1])), flip_x, None)

    def _variant_key(self, image_key: tuple, size: tuple[int, int], flip_x: bool,
                     crop: tuple[int, int, int, int] | None) -> tuple:
        return ("variant", image_key, size, flip_x, None if crop is None else tuple(crop),
                self.scale_filter)

    @property
    def budget_bytes(self) -> int:
        """The ``[engine] cache_mb`` budget, in bytes (F04 prefetch limits)."""
        return self._cache.budget_bytes

    def read_image_bytes(self, ref: str) -> tuple[bytes, str, int, int] | None:
        """F04 prefetch, main thread: ``(bytes, decode hint, width, height)`` of the image
        file ``ref``, read through ``GamePaths.read_file`` and header-checked exactly as
        ``image()`` would (suffix, read, SEC-F01-06 limits), or None for any problem. Never
        logs and caches nothing: a bad file is reported once, by the later ``image()``."""
        if ref in self._failed or _suffix(ref) not in IMAGE_SUFFIXES:
            return None
        try:
            data = self._read(ref)
            self._check_header(ref, data, DAMAGED_IMAGE)
        except _Problem:
            return None
        found = image_dimensions(data)
        assert found is not None                  # _check_header passed
        return data, "image" + _suffix(ref), found[1], found[2]

    def convert(self, surface: pygame.Surface) -> pygame.Surface:
        """``surface`` (decoded elsewhere, e.g. by the F04 decode worker) in the framebuffer's
        pixel layout, by the same rules as a loaded image. Main thread only."""
        return self._convert(surface)

    def preload(self, refs: Iterable[str]) -> None:
        """Load ``refs`` now, so drawing them later reads no file (PR-F01-60)."""
        for ref in refs:
            self.image(ref)

    def hold(self, refs: Iterable[str]) -> AssetHold:
        """Load ``refs`` and keep them from being evicted until ``release()``."""
        keys = []
        for ref in refs:
            image = self.image(ref)
            if not image.is_placeholder:
                keys.append(image._key)
        return AssetHold(self._cache, keys)

    def _load_image(self, ref: str, *, log: bool = True) -> pygame.Surface:
        """Steps 2–7 of §7.11.1. Raises _Problem. ``log=False`` (``check``) skips the
        debug line."""
        started = _time.perf_counter()
        if _suffix(ref) not in IMAGE_SUFFIXES:
            raise _Problem(_WARNING, f"{echo(ref)}: unsupported image format "
                                     f"(use PNG, JPEG, or WebP)")
        data = self._read(ref)
        self._check_header(ref, data, DAMAGED_IMAGE)
        surface = self._decode(ref, data)
        surface = self._convert(surface)
        self._cache.put(("img", ref), surface, _surface_cost(surface), self.time.frame)
        if not log:
            return surface
        elapsed = _time.perf_counter() - started
        width, height = surface.get_size()
        hint = " — consider preloading" if self.in_frame_loop and elapsed > SLOW_LOAD_S else ""
        _log.debug("Loaded %s (%dx%d, %.1f MB) in %.1f ms%s", echo(ref), width, height,
                   _surface_cost(surface) / MB, elapsed * 1000.0, hint)
        return surface

    def _read(self, ref: str) -> bytes:
        """``GamePaths.read_file`` with each failure mapped to its log line."""
        try:
            check_ref(ref)          # syntax first: a rejected ref never reaches read_file
            if self.paths is None:  # no game folder (the session ends on the error screen)
                raise AssetMissing(ref, None)
            return self.paths.read_file(ref, max_bytes=ASSET_MAX_BYTES)
        except AssetRefError as error:
            raise _Problem(_ERROR, error.message, label=f"blocked path: {echo(ref)}",
                           reason=error.reason) from None
        except AssetMissing as error:
            reason = "not found"
            if error.suggestion is not None:
                reason += f" — did you mean {echo(error.suggestion)}?"
            raise _Problem(_WARNING, str(error), reason=reason, missing=True,
                           suggestion=error.suggestion) from None
        except AssetNotFile as error:
            raise _Problem(_WARNING, str(error), reason="it is not a file") from None
        except AssetTooLarge as error:
            raise _Problem(_WARNING, str(error),
                           reason=f"it is larger than {ASSET_MAX_BYTES // MB} MB") from None
        except AssetUnreadable as error:
            raise _Problem(_WARNING, str(error), reason="it could not be read") from None

    @staticmethod
    def _check_header(ref: str, data: bytes, damaged: str) -> None:
        """SEC-F01-06: size from the header bytes, before any decoding (§7.11.2)."""
        found = image_dimensions(data)
        if found is None:
            raise _Problem(_WARNING, f"could not read image {echo(ref)} ({damaged})",
                           reason=damaged)
        _, width, height = found
        if width > IMAGE_MAX_SIDE or height > IMAGE_MAX_SIDE or width * height > IMAGE_MAX_PIXELS:
            raise _Problem(
                _WARNING,
                f"image too large: {echo(ref)} is {width}x{height} (limit "
                f"{IMAGE_MAX_SIDE} px per side and {IMAGE_MAX_PIXELS // 1_000_000} megapixels)",
                reason=f"image too large: {width}x{height}")

    @staticmethod
    def _decode(ref: str, data: bytes) -> pygame.Surface:
        """Decode from memory; only the suffix reaches SDL as a type hint (PR-F01-06)."""
        try:
            return pygame.image.load(io.BytesIO(data), "image" + _suffix(ref))
        except (pygame.error, OSError, ValueError, MemoryError):
            raise _Problem(_WARNING, f"could not read image {echo(ref)} ({DAMAGED_IMAGE})",
                           reason=DAMAGED_IMAGE) from None

    def _convert(self, surface: pygame.Surface) -> pygame.Surface:
        """To the framebuffer's pixel layout (§7.11.1 step 6, with the S0 fallback)."""
        if surface.get_flags() & pygame.SRCALPHA:
            try:
                return surface.convert_alpha()
            except pygame.error:
                return surface.convert(pygame.Surface((1, 1), pygame.SRCALPHA, 32))
        fmt = self._format_source()
        if fmt is not None and fmt.get_width() > 0 and fmt.get_height() > 0:
            try:
                return surface.convert(fmt)
            except pygame.error:
                pass
        return surface.convert(32, 0)

    # --- placeholders -------------------------------------------------------------------------

    def _placeholder_surface(self, label: str) -> pygame.Surface:
        """From the bounded placeholder cache (≤ 64 surfaces, not in the budget)."""
        surface = self._placeholders.get(label)
        if surface is not None:
            self._placeholders.move_to_end(label)
            return surface
        surface = self._convert(make_placeholder(label, self.font(None, LABEL_FONT_PX).font))
        self._placeholders[label] = surface
        if len(self._placeholders) > PLACEHOLDER_CACHE_ENTRIES:
            self._placeholders.popitem(last=False)
        return surface

    # --- fonts and text -----------------------------------------------------------------------

    def font(self, ref: str | None, size_px: int, *, bundled: Face = Face.REGULAR,
             synth: Synth = Synth.NONE) -> FontHandle:
        """The font at ``ref`` at ``size_px`` pixels; ``ref`` None = the bundled Noto Sans
        face ``bundled`` (ADR-0004 and its F05 amendment). A missing, blocked, or broken
        font gives the bundled face ``bundled`` and one log line (PR-F01-55, PR-F01-61).

        ``synth`` makes pygame thicken and/or slant an author's font (F05 §7.6) on a font
        object of its own, cached under ``("font", ref, size_px, synth)``, so the style
        never leaks onto the plain font and measuring matches drawing. It never applies to a
        bundled face: the bundled styles are real faces, and a fallback is the bundled face
        as it is. Font files are charged to the budget once per file; each size and style
        costs FONT_OBJECT_COST (§7.11.6)."""
        size_px = max(1, int(size_px))
        if ref is not None and ref in self._failed_fonts:
            self._failed_fonts.move_to_end(ref)
            ref = None
        if ref is None:
            name, synth = BUNDLED_NAMES[bundled], Synth.NONE
        else:
            name = ref
        handle = self._cache.get(_font_key(name, size_px, synth), self.time.frame)
        if handle is not None:
            return handle
        if ref is None:
            return self._make_font(name, size_px, self._bundled_font_data(bundled))
        try:
            if _suffix(ref) not in FONT_SUFFIXES:
                raise _Problem(_WARNING, _unsupported_font(ref))
            data = self._cache.get(("fontfile", ref), self.time.frame)
            if data is None:
                data = self._read(ref)
            return self._make_font(ref, size_px, data, synth)
        except _Problem as problem:
            message = problem.message
            if problem.level < _ERROR:
                message += " — using the default font"
            self._problem(ref, problem.level, message)
            if len(ref) <= REF_MAX_CHARS:
                self._failed_fonts[ref] = None
                if len(self._failed_fonts) > MISSING_REF_CACHE_ENTRIES:
                    self._failed_fonts.popitem(last=False)
            return self.font(None, size_px, bundled=bundled)

    def check(self, ref: str, kind: Literal["font", "image"]) -> AssetProblem | None:
        """Whether ``ref`` is usable, validated exactly as ``font()``/``image()`` would
        (F05 §7.6: install time, W43). Never logs, so the caller's warning is the only one
        (I-5). A good file stays in the cache, so the later ``font()``/``image()`` reads
        nothing; a problem is remembered (bounded), so asking again reads nothing either."""
        if kind not in ("font", "image"):
            raise ValueError(f"check kind must be 'font' or 'image', not {kind!r}")
        memo_key = (kind, ref)
        problem = self._check_problems.get(memo_key)
        if problem is not None:
            self._check_problems.move_to_end(memo_key)
            return problem
        try:
            if kind == "font":
                self._check_font(ref)
            elif ("img", ref) not in self._cache:
                self._load_image(ref, log=False)
        except _Problem as failure:
            problem = failure.as_asset_problem()
            if len(ref) <= REF_MAX_CHARS:
                self._check_problems[memo_key] = problem
                if len(self._check_problems) > MISSING_REF_CACHE_ENTRIES:
                    self._check_problems.popitem(last=False)
            return problem
        return None

    def _check_font(self, ref: str) -> None:
        """``font()``'s steps without the font object: suffix, read, open and test-measure.
        Leaves the file in the cache (unheld) for ``font()``. Raises _Problem."""
        if ("fontfile", ref) in self._cache:
            return                  # already opened and measured
        if _suffix(ref) not in FONT_SUFFIXES:
            raise _Problem(_WARNING, _unsupported_font(ref))
        data = self._read(ref)
        self._open_font(ref, data, CHECK_FONT_PX)
        self._cache.put(("fontfile", ref), data, len(data), self.time.frame)

    def text_line(self, font: FontHandle, text: str, color: tuple) -> pygame.Surface:
        """One rendered line (anti-aliased, per-pixel alpha), cached in the shared budget
        under ``("text", font.key, color, text)`` with cost ``w*h*4 + ENTRY_OVERHEAD``."""
        key = ("text", font.key, tuple(color), text)
        surface = self._cache.get(key, self.time.frame)
        if surface is None:
            surface = font.font.render(text, True, color)
            width, height = surface.get_size()
            self._cache.put(key, surface, width * height * 4 + ENTRY_OVERHEAD,
                            self.time.frame)
        return surface

    @staticmethod
    def _open_font(name: str, data: bytes, size_px: int) -> "pygame.font.Font":
        """A new font object, test-measured. A bundled face that fails re-raises (a broken
        install); an author's raises _Problem."""
        try:
            font = pygame.font.Font(io.BytesIO(data), size_px)
            # Opening can succeed on garbage bytes; the first measurement fails then.
            font.size("Ag")
        except (pygame.error, OSError, ValueError, MemoryError):
            if name in _BUNDLED_BY_NAME:
                raise
            raise _Problem(_WARNING, f"could not read font {echo(name)} ({DAMAGED_FONT})") \
                from None
        return font

    def _make_font(self, name: str, size_px: int, data: bytes,
                   synth: Synth = Synth.NONE) -> FontHandle:
        file_key = ("fontfile", name)
        font = self._open_font(name, data, size_px)
        if synth in (Synth.BOLD, Synth.BOLD_ITALIC):
            font.bold = True
        if synth in (Synth.ITALIC, Synth.BOLD_ITALIC):
            font.italic = True
        if file_key not in self._cache:
            self._cache.put(file_key, data, len(data), self.time.frame)
        else:
            self._cache.get(file_key, self.time.frame)
        self._cache.hold(file_key)
        key = _font_key(name, size_px, synth)
        handle = FontHandle(font, key, size_px)
        self._cache.put(key, handle, FONT_OBJECT_COST, self.time.frame)
        return handle

    def _bundled_font_data(self, face: Face) -> bytes:
        name = BUNDLED_NAMES[face]
        data = self._cache.get(("fontfile", name), self.time.frame)
        if data is None:
            # A trusted engine file, read directly (§7.11.6).
            data = (engine_data_dir() / BUNDLED_FILES[face]).read_bytes()
            _log.debug("Loaded the bundled font %s (%.1f MB)", BUNDLED_FILES[face],
                       len(data) / MB)
        return data

    def _on_evict(self, key: tuple, _value: object) -> None:
        """A font size leaving the cache releases its hold on the font file."""
        if key[0] == "font":
            file_key = ("fontfile", key[1])
            try:
                self._cache.release(file_key)
            except AssertionError:
                pass

    # --- window icon (§7.11.7) ----------------------------------------------------------------

    def icon_surface(self, ref: str | None) -> pygame.Surface:
        """PR-F01-16 table (§7.11.7). Returns an unconverted surface: SDL accepts any
        format for a window icon, so no display format is needed at startup."""
        if ref is None:
            return self._engine_icon_surface()
        if ref == "" or not ref.lower().endswith(".png"):
            _log.warning('Window icon "%s" must be a PNG file — using the engine icon',
                         echo(ref))
            return self._engine_icon_surface()
        try:
            data = self._read(ref)
            self._check_header(ref, data, "file is damaged or not a PNG image")
            try:
                return pygame.image.load(io.BytesIO(data), "icon.png")
            except (pygame.error, OSError, ValueError, MemoryError):
                raise _Problem(_WARNING, "", reason="file is damaged or not a PNG image") \
                    from None
        except _Problem as problem:
            if problem.level >= _ERROR:
                _log.error("%s — using the engine icon", problem.message)
            else:
                _log.warning("Window icon %s could not be used (%s) — using the engine icon",
                             echo(ref), problem.reason)
            return self._engine_icon_surface()

    def _engine_icon_surface(self) -> pygame.Surface:
        if self._engine_icon is None:
            path: Path = engine_data_dir() / ENGINE_ICON_FILE
            self._engine_icon = pygame.image.load(io.BytesIO(path.read_bytes()), "icon.png")
        return self._engine_icon

    # --- problems -----------------------------------------------------------------------------

    def _problem(self, ref: str, level: int, message: str) -> None:
        """Log once per echoed ref, at most ASSET_PROBLEM_LOG_LIMIT refs per session
        (SEC-F01-05), then one summary line."""
        key = echo(ref)
        if key in self._problem_keys:
            return
        if len(self._problem_keys) >= ASSET_PROBLEM_LOG_LIMIT:
            if not self._problem_limit_logged:
                self._problem_limit_logged = True
                _log.warning(MSG_TOO_MANY_PROBLEMS)
            return
        self._problem_keys.add(key)
        _log.log(level, "%s", message)



def _font_key(name: str, size_px: int, synth: Synth) -> tuple:
    """``("font", name, size_px)``, plus the synth for a synthesized style (F05 §5.3)."""
    if synth is Synth.NONE:
        return ("font", name, size_px)
    return ("font", name, size_px, synth)


def _unsupported_font(ref: str) -> str:
    return f"{echo(ref)}: unsupported font format (use a .ttf or .otf file)"


def _suffix(ref: str) -> str:
    """The lower-cased suffix of the last segment (``""`` if none)."""
    name = ref.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _crop_source(source: pygame.Surface, size: tuple[int, int], crop: tuple[int, int, int, int],
                 flip_x: bool) -> tuple[pygame.Surface, tuple[int, int], tuple[int, int]]:
    """The source sub-rectangle behind ``crop`` of the full ``size`` variant: ``(piece,
    its device size, its offset in the full variant)``. Source edges are floored and ceiled
    so the piece covers the crop; device edges are rounded half up from the exact scale."""
    sw, sh = source.get_size()
    width, height = size
    cx, cy, cw, ch = crop
    if flip_x:                                    # crop is in mirrored coordinates
        cx = width - (cx + cw)
    x0 = max(0, min(sw - 1, math.floor(cx * sw / width)))
    x1 = max(x0 + 1, min(sw, math.ceil((cx + cw) * sw / width)))
    y0 = max(0, min(sh - 1, math.floor(cy * sh / height)))
    y1 = max(y0 + 1, min(sh, math.ceil((cy + ch) * sh / height)))
    dx0 = math.floor(x0 * width / sw + 0.5)
    dx1 = math.floor(x1 * width / sw + 0.5)
    dy0 = math.floor(y0 * height / sh + 0.5)
    dy1 = math.floor(y1 * height / sh + 0.5)
    target = (max(1, dx1 - dx0), max(1, dy1 - dy0))
    piece = source.subsurface(pygame.Rect(x0, y0, x1 - x0, y1 - y0))
    offset_x = width - (dx0 + target[0]) if flip_x else dx0
    return piece, target, (offset_x, dy0)


def _surface_cost(surface: pygame.Surface) -> int:
    width, height = surface.get_size()
    return width * height * surface.get_bytesize() + ENTRY_OVERHEAD

