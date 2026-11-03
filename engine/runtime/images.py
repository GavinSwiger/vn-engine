"""The image index: image names from the files under ``images/`` (F04 ``04-technical.md``
§4.2, §7.1; PR-F04-01–03, 25; SR-F04-01, 02, 04, 05).

Why this module exists: a script names pictures by words (``show hana happy``), and those
names come from file paths (``images/hana/happy.png``), with no list to keep. ``ImageScan``
builds the ``ImageIndex`` once per launch (``LaunchJob`` phase 4), one directory per
``step()`` so the loading screen can spread it over frames, and the index then answers
``get(name)`` for the stage, the launch check (W10, W11, W12b), and the renderer.

The module is pure (TR-F03-05): it reads no directory itself. What it may see of the game
folder comes in an ``ImageSource`` (I-7: F03's ``LaunchJob(images=)`` and F04's scan inputs
are one type): a ``list_dir`` that lists one directory (the app passes
``GamePaths.list_dir``) and a ``locate`` that says whether a declared file exists. Headless
runs build one from a list of refs with ``ImageSource.from_files``. No file is opened.

The index is a function of the listed names only: listings are re-sorted here in code-point
order, so it is the same however the scan is sliced and in whatever order a listing comes
(TR-F04-05). Names are compared after ``canonical_name``, so an NFD file name from macOS
gives the same name as the NFC word in the script.
"""

import difflib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from engine.core.errors import AssetRefError
from engine.core.paths import DirListing, check_ref
from engine.runtime.limits import IMAGE_SCAN_MAX_DEPTH, IMAGE_SCAN_MAX_FILES
# F04's naming rules live in script/imagenames.py (F45 04 Q5); re-exported as the same objects.
from engine.script.imagenames import (CHARACTERS, DOT, HYPHEN, IMAGE_NAME_MAX_WORDS, SPACE,
                                      STAGE_WORD, STATEMENT_WORD, TOO_MANY_WORDS, NameProblem,
                                      image_suffix, is_image_word, name_of, word_problem)
# F38's frame rule lives in script/spriteframes.py; ``app`` reaches it through ``look_frames``.
from engine.script.spriteframes import LookFrames, frames_of, picture_names

# --- Limits (04 §12; the scan's two are in runtime/limits.py) -------------------------------
DECLARATION_CHUNK = 256              # declared files located per step

IMAGES_DIR = "images"
BLACK = "black"                      # built in unless a file or declaration gives it (SR-F04-05)

# W11's order: .png wins, then .webp, then .jpg/.jpeg (then the lower ref).
_SUFFIX_RANK = {".png": 0, ".webp": 1, ".jpg": 2, ".jpeg": 2}


# --- Index values -------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ImageFile:
    ref: str                         # "images/hana/happy.png", exact case


@dataclass(frozen=True, slots=True)
class SolidColor:
    rgb: tuple[int, int, int]


Image = ImageFile | SolidColor


@dataclass(frozen=True, slots=True)
class Duplicate:
    """Two files give one name (W11): ``used`` gives it, ``other`` is left out."""
    name: str
    used: str
    other: str


@dataclass(frozen=True, slots=True)
class MissingDeclaration:
    """``image name = "ref"`` names a file that doesn't exist (W12b). The name still gives
    ``ImageFile(ref)``, so a placeholder shows at run time. ``declaration`` is the
    statement (its file and line are the message's place)."""
    name: str
    ref: str
    suggestion: str | None
    declaration: object


class ImageIndex:
    """Image name → ``ImageFile`` or ``SolidColor``, case-exact. Immutable; two indexes
    are equal when every name, ref, problem, duplicate, and missing declaration is."""

    __slots__ = ("_images", "names", "tags", "problems", "duplicates", "declared_missing",
                 "truncated")

    def __init__(self, images: Mapping[str, Image], *,
                 problems: Iterable[NameProblem] = (), duplicates: Iterable[Duplicate] = (),
                 declared_missing: Iterable[MissingDeclaration] = (),
                 truncated: bool = False) -> None:
        set_ = object.__setattr__
        set_(self, "_images", dict(images))
        set_(self, "names", frozenset(self._images))
        set_(self, "tags", frozenset(name.split(" ", 1)[0] for name in self._images))
        set_(self, "problems", tuple(problems))              # W10, in ref code-point order
        set_(self, "duplicates", tuple(duplicates))          # W11, in ref code-point order
        set_(self, "declared_missing", tuple(declared_missing))  # W12b, in reading order
        set_(self, "truncated", truncated)                   # the scan stopped at the cap

    names: frozenset[str]
    tags: frozenset[str]                                     # the first words of names
    problems: tuple[NameProblem, ...]
    duplicates: tuple[Duplicate, ...]
    declared_missing: tuple[MissingDeclaration, ...]
    truncated: bool

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ImageIndex is immutable")

    def get(self, name: str) -> Image | None:
        return self._images.get(name)

    def items(self) -> tuple[tuple[str, Image], ...]:
        """Every (name, image), in name code-point order."""
        return tuple(sorted(self._images.items()))

    def __len__(self) -> int:
        return len(self._images)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ImageIndex):
            return NotImplemented
        return (self._images == other._images and self.problems == other.problems
                and self.duplicates == other.duplicates
                and self.declared_missing == other.declared_missing
                and self.truncated == other.truncated)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f"ImageIndex({len(self._images)} names, {len(self.problems)} problems, "
                f"{len(self.duplicates)} duplicates, "
                f"{len(self.declared_missing)} missing declarations)")


# --- What the scan may see (I-7) ----------------------------------------------------------

ListDir = Callable[[str], DirListing | None]
Locate = Callable[[str], tuple[bool, str | None]]


@dataclass(frozen=True, slots=True)
class ImageSource:
    """The scan's view of the game folder: ``list_dir(ref)`` lists one directory (None if
    missing or not a directory; may raise ``AssetRefError``), and ``locate(ref)`` returns
    ``(exists, suggestion)`` for a declared file. The app builds it from ``GamePaths``;
    ``from_files`` builds it from a list of game-relative refs (headless runs).
    ``game_folder`` is False for ``from_files``: the refs stand in for the image scan only,
    so F09's mask check (W60) is skipped, as F08 skips its file check headless."""
    list_dir: ListDir
    locate: Locate
    game_folder: bool = True

    @classmethod
    def from_files(cls, refs: Iterable[str]) -> "ImageSource":
        tree = _FileTree(refs)
        return cls(tree.list_dir, tree.locate, game_folder=False)


class _FileTree:
    """A game folder made of the given file refs only (no directory is read)."""

    def __init__(self, refs: Iterable[str]) -> None:
        files: dict[str, set[str]] = {}
        dirs: dict[str, set[str]] = {}
        for ref in refs:
            if type(ref) is not str:
                raise TypeError(f"image_files holds refs (str), not {type(ref).__name__}")
            check_ref(ref)
            parent, _, name = ref.rpartition("/")
            files.setdefault(parent, set()).add(name)
            while parent:
                above, _, folder = parent.rpartition("/")
                dirs.setdefault(above, set()).add(folder)
                parent = above
        self._listings = {
            ref: DirListing(tuple(sorted(files.get(ref, ()))), tuple(sorted(dirs.get(ref, ()))))
            for ref in files.keys() | dirs.keys()}

    def list_dir(self, ref: str) -> DirListing | None:
        return self._listings.get(ref) if ref else None

    def locate(self, ref: str) -> tuple[bool, str | None]:
        """Like ``GamePaths.resolve``: a case-only difference or a close name (difflib,
        cutoff 0.8) in the first folder that lacks a segment is the suggestion."""
        walked: list[str] = []
        segments = ref.split("/")
        for index, segment in enumerate(segments):
            listing = self._listings.get("/".join(walked))
            if listing is None:
                return False, None
            last = index == len(segments) - 1
            names = listing.files + listing.dirs
            if segment in (listing.files if last else listing.dirs):
                walked.append(segment)
                continue
            if segment in names:                       # a file where a folder is, or back
                return False, None
            folded = [n for n in names if n.casefold() == segment.casefold()]
            close = folded[0] if len(folded) == 1 else next(
                iter(difflib.get_close_matches(segment, sorted(names), 1, 0.8)), None)
            return False, None if close is None else "/".join([*walked, close])
        return True, None


def _rank(ref: str) -> tuple[int, str]:
    return _SUFFIX_RANK[ref[ref.rfind("."):].lower()], ref


# --- The scan (04 §7.1) -------------------------------------------------------------------

class ImageScan:
    """Builds the ``ImageIndex``: ``step()`` lists one directory per call (breadth first,
    folders in code-point order, depth ≤ 8, ≤ 20,000 entries), then locates the declared
    files ``DECLARATION_CHUNK`` at a time; True once ``result`` is set."""

    def __init__(self, program: object, source: ImageSource) -> None:
        self.source = source
        self._declarations = _declarations(program)
        self._queue: list[tuple[str, int]] = [(IMAGES_DIR, 0)]
        self._queue_at = 0
        self._entries = 0
        self._truncated = False
        self._found: dict[str, list[str]] = {}         # name → refs giving it
        self._problems: list[NameProblem] = []
        self._declared: dict[str, Image] = {}
        self._missing: list[MissingDeclaration] = []
        self._declaration_at = 0
        self._result: ImageIndex | None = None

    @property
    def result(self) -> ImageIndex:
        if self._result is None:
            raise AssertionError("the scan is not done; call step() until it is")
        return self._result

    def step(self) -> bool:
        if self._result is not None:
            return True
        if self._queue_at < len(self._queue) and not self._truncated:
            ref, depth = self._queue[self._queue_at]
            self._queue_at += 1
            self._list(ref, depth)
            return False
        if self._declaration_at < len(self._declarations):
            end = min(self._declaration_at + DECLARATION_CHUNK, len(self._declarations))
            for declaration in self._declarations[self._declaration_at:end]:
                self._declare(declaration)
            self._declaration_at = end
            if end < len(self._declarations):
                return False
        self._result = self._build()
        return True

    def run(self) -> ImageIndex:
        """The scan to the end in one go."""
        while not self.step():
            pass
        return self.result

    def _list(self, ref: str, depth: int) -> None:
        try:
            listing = self.source.list_dir(ref)
        except AssetRefError:                           # a folder name a ref can't hold
            return
        if listing is None:
            return
        folders = set(listing.dirs)
        for name in sorted({*listing.files, *folders}):
            if self._entries >= IMAGE_SCAN_MAX_FILES:
                self._truncated = True
                return
            self._entries += 1
            child = f"{ref}/{name}"
            if name in folders:
                if depth < IMAGE_SCAN_MAX_DEPTH:
                    self._queue.append((child, depth + 1))
            elif image_suffix(name) is not None:
                image, problem = name_of(child)
                if problem is not None:
                    self._problems.append(problem)
                else:
                    self._found.setdefault(image, []).append(child)  # type: ignore[arg-type]

    def _declare(self, declaration: object) -> None:
        name = getattr(declaration, "name")
        color = getattr(declaration, "color", None)
        if color is not None:
            self._declared[name] = SolidColor(tuple(color))  # type: ignore[arg-type]
            return
        ref = getattr(declaration, "ref")
        self._declared[name] = ImageFile(ref)
        exists, suggestion = self.source.locate(ref)
        if not exists:
            self._missing.append(MissingDeclaration(name, ref, suggestion, declaration))

    def _build(self) -> ImageIndex:
        images: dict[str, Image] = {}
        duplicates: list[Duplicate] = []
        for name, refs in self._found.items():
            used, *others = sorted(refs, key=_rank)
            images[name] = ImageFile(used)
            duplicates.extend(Duplicate(name, used, other) for other in others)
        images.update(self._declared)                   # SR-F04-05: no message
        images.setdefault(BLACK, SolidColor((0, 0, 0)))
        return ImageIndex(images,
                          problems=sorted(self._problems, key=lambda p: p.ref),
                          duplicates=sorted(duplicates, key=lambda d: (d.used, d.other)),
                          declared_missing=self._missing, truncated=self._truncated)


def _declarations(program: object) -> tuple[object, ...]:
    """``program.images`` (F04 step 2: the ``image`` declarations, reading order), as a
    tuple; a mapping gives its values. Each has ``name``, ``ref``, and ``color``."""
    images = getattr(program, "images", None)
    if images is None:
        return ()
    if isinstance(images, Mapping):
        return tuple(images.values())
    return tuple(images)


def build_index(program: object, source: ImageSource) -> ImageIndex:
    """``ImageScan`` run to the end in one go (tests and tools)."""
    return ImageScan(program, source).run()


def look_frames(index: "ImageIndex") -> Callable[[str], LookFrames]:
    """F38 (PR-F38-01): ``look → LookFrames`` over ``index``'s picture files (the name set
    built once; a rebuilt index needs a new one)."""
    names = picture_names(index.items())
    return lambda look: frames_of(look, names)


__all__ = ["BLACK", "DOT", "Duplicate", "HYPHEN", "IMAGE_NAME_MAX_WORDS", "IMAGE_SCAN_MAX_DEPTH",
           "IMAGE_SCAN_MAX_FILES", "IMAGES_DIR", "CHARACTERS", "Image", "ImageFile",
           "ImageIndex", "ImageScan", "ImageSource", "MissingDeclaration", "NameProblem",
           "SPACE", "STAGE_WORD", "STATEMENT_WORD", "SolidColor", "TOO_MANY_WORDS",
           "build_index", "image_suffix", "is_image_word", "look_frames", "name_of",
           "word_problem"]
