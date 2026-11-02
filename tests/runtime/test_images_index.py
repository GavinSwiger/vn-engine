"""F04 step 3: the image index (``engine/runtime/images.py``; ``04-technical.md`` §4.2, §7.1,
§7.2 phase 4). AC-F04-01, AC-F04-02, TR-F04-05; the W10 and W11 data AC-F04-39 formats;
AC-F04-04 (step 6: its rows on disk through the launch; the 20,001-file row is ``slow``).

``Program.images`` (the ``image`` declarations) arrives with F04 step 2, so declarations are
stand-ins here with the ``ImageDecl`` fields (``name``, ``ref``, ``color``).
"""

import unicodedata
from types import SimpleNamespace

import pytest

from engine.app.loading import image_source
from engine.core.errors import AssetRefError
from engine.core.paths import DirListing, GamePaths
from engine.runtime import images as images_module
from engine.runtime.commands import Say
from engine.runtime.headless import run_headless
from engine.runtime.images import (CHARACTERS, DOT, HYPHEN, IMAGE_SCAN_MAX_DEPTH,
                                   IMAGE_SCAN_MAX_FILES, SPACE, STAGE_WORD, STATEMENT_WORD,
                                   TOO_MANY_WORDS, Duplicate, ImageFile, ImageIndex, ImageScan,
                                   ImageSource, MissingDeclaration, NameProblem, SolidColor,
                                   build_index, is_image_word, name_of, word_problem)
from engine.runtime.launch import LaunchJob, run_launch
from engine.script.words import canonical_name
from tests.runtime.story import load_r
from tests.script.conftest import opened  # noqa: F401  (fixture)

NO_PROGRAM = SimpleNamespace()
BLACK = SolidColor((0, 0, 0))


def decl(name, ref=None, color=None):
    """A stand-in ``ImageDecl`` (F04 step 2)."""
    return SimpleNamespace(name=name, ref=ref, color=color)


def program_with(*declarations):
    return SimpleNamespace(images=tuple(declarations))


def index_of(files, *declarations) -> ImageIndex:
    return build_index(program_with(*declarations), ImageSource.from_files(files))


def write_files(root, refs):
    for ref in refs:
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


# --- AC-F04-01: image names come from files ----------------------------------------------

CAFE_NFD = unicodedata.normalize("NFD", "café")

AC01_ROWS = [  # file, image name, tag
    ("images/bg/river_night.png", "bg river_night", "bg"),
    ("images/hana/happy.png", "hana happy", "hana"),
    ("images/hana/yukata/happy.png", "hana yukata happy", "hana"),
    ("images/lantern.png", "lantern", "lantern"),
    ("images/hana/Smile.PNG", "hana Smile", "hana"),
    ("images/a/b/c/d/e.webp", "a b c d e", "a"),
    ("images/花/笑顔.jpg", "花 笑顔", "花"),
    (f"images/hana/{CAFE_NFD}.jpeg", "hana café", "hana"),
]
AC01_NOT_IMAGES = ["images/notes.txt", "images/hana/happy.gif"]
AC01_FILES = [file for file, _, _ in AC01_ROWS] + AC01_NOT_IMAGES


@pytest.fixture
def ac01_game(tmp_path):
    write_files(tmp_path, AC01_FILES)
    assert CAFE_NFD in {p.stem for p in (tmp_path / "images" / "hana").iterdir()}
    return GamePaths(tmp_path.resolve())


def test_ac_f04_01_names_come_from_files(ac01_game, opened, monkeypatch):  # noqa: F811
    def no_read(*args, **kwargs):
        raise AssertionError("the scan read a file")

    monkeypatch.setattr(GamePaths, "read_file", no_read)
    with opened() as events:
        index = build_index(NO_PROGRAM, image_source(ac01_game))
    assert not [e for e in events if e[0] == "open"], events
    assert any(e[0] == "os.scandir" for e in events)     # the recorder sees the listings
    assert index.names == {name for _, name, _ in AC01_ROWS} | {"black"}
    for file, name, tag in AC01_ROWS:
        assert index.get(name) == ImageFile(file), name
        assert tag in index.tags
    assert index.tags == {tag for _, _, tag in AC01_ROWS} | {"black"}
    assert index.problems == () and index.duplicates == () and not index.truncated


@pytest.mark.parametrize("spelling", ["hana smile", "Hana happy", "hana  happy", "hana happy ",
                                      "bg river_night.png", "images/lantern", "lantern.png",
                                      "hana " + CAFE_NFD, "hana", "a b c d", "notes",
                                      "hana happy.gif"])
def test_ac_f04_01_no_other_spelling_resolves(ac01_game, spelling):
    assert build_index(NO_PROGRAM, image_source(ac01_game)).get(spelling) is None


def test_ac_f04_01_nfd_file_matches_the_script_word(ac01_game):
    index = build_index(NO_PROGRAM, image_source(ac01_game))
    assert "hana " + canonical_name("café") in index.names
    assert "hana " + canonical_name(CAFE_NFD) in index.names


class Reversed:
    """``list_dir`` with every listing in reversed order."""

    def __init__(self, list_dir):
        self.list_dir = list_dir

    def __call__(self, ref):
        listing = self.list_dir(ref)
        if listing is None:
            return None
        return DirListing(listing.files[::-1], listing.dirs[::-1])


AC02_W10_FILES = ["images/bg/bridge-day.png", "images/club day.png", "images/a.b.png",
                  "images/scene.png", "images/zoom.png", "images/a/b/c/d/e/f.png"]
DUPLICATE_FILES = ["images/hana/happy.png", "images/hana/happy.webp", "images/hana/sad.jpg",
                   "images/hana/sad.webp", "images/x/y.jpg", "images/x/y.jpeg"]


@pytest.mark.parametrize("files", [AC01_FILES, AC02_W10_FILES + DUPLICATE_FILES + AC01_FILES],
                         ids=["ac01", "with-problems"])
def test_tr_f04_05_slicing_and_listing_order(tmp_path, files):
    write_files(tmp_path, files)
    paths = GamePaths(tmp_path.resolve())
    source = image_source(paths)
    scan = ImageScan(NO_PROGRAM, source)
    steps = 1
    while not scan.step():
        steps += 1
    stepped = scan.result
    assert steps > 3                                     # one directory per step
    at_once = build_index(NO_PROGRAM, ImageSource.from_files(files))
    reversed_ = build_index(NO_PROGRAM, ImageSource(Reversed(paths.list_dir), source.locate))
    reversed_memory = build_index(NO_PROGRAM, ImageSource(
        Reversed(ImageSource.from_files(files).list_dir), source.locate))
    assert stepped == at_once == reversed_ == reversed_memory
    assert stepped.items() == at_once.items()
    assert stepped.problems == reversed_.problems and stepped.duplicates == reversed_.duplicates


# --- Naming rules (SR-F04-01; W10's data) -------------------------------------------------

@pytest.mark.parametrize("ref, problem", [
    ("images/a.b.png", NameProblem("images/a.b.png", DOT, "a.b.png", "a_b.png")),
    ("images/a/b/c/d/e/f.png", NameProblem("images/a/b/c/d/e/f.png", TOO_MANY_WORDS)),
    ("images/bg/bridge-day.png",
     NameProblem("images/bg/bridge-day.png", HYPHEN, "bridge-day.png", "bridge_day.png")),
    ("images/club day.png", NameProblem("images/club day.png", SPACE, "club day.png",
                                        "club_day.png")),
    ("images/scene.png", NameProblem("images/scene.png", STATEMENT_WORD, "scene.png",
                                     "my_scene.png")),
    ("images/zoom.png", NameProblem("images/zoom.png", STAGE_WORD, "zoom.png", "my_zoom.png")),
    ("images/Scene.PNG", NameProblem("images/Scene.PNG", STATEMENT_WORD, "Scene.PNG",
                                     "my_Scene.PNG")),
    ("images/hana/LAYER.webp", NameProblem("images/hana/LAYER.webp", STAGE_WORD, "LAYER.webp",
                                           "my_LAYER.webp")),
    ("images/flip.jpg", NameProblem("images/flip.jpg", STAGE_WORD, "flip.jpg", "my_flip.jpg")),
    ("images/hana/at.png", NameProblem("images/hana/at.png", STATEMENT_WORD, "at.png",
                                       "my_at.png")),
    ("images/bg-x/day.png", NameProblem("images/bg-x/day.png", HYPHEN, "bg-x", "bg_x", True)),
    ("images/show/day.png", NameProblem("images/show/day.png", STATEMENT_WORD, "show",
                                        "my_show", True)),
    ("images/hi!.png", NameProblem("images/hi!.png", CHARACTERS, "hi!.png", "hi_.png")),
    ("images/a-b c.png", NameProblem("images/a-b c.png", HYPHEN, "a-b c.png", "a_b_c.png")),
    ("images/x.y.z.png", NameProblem("images/x.y.z.png", DOT, "x.y.z.png", "x_y_z.png")),
    ("images/a b/c d.png", NameProblem("images/a b/c d.png", SPACE, "a b", "a_b", True)),
])
def test_unusable_names(ref, problem):
    assert name_of(ref) == (None, problem)


@pytest.mark.parametrize("ref, name", [
    ("images/2b.png", "2b"),
    ("images/_x.png", "_x"),
    ("images/hana/happy.png", "hana happy"),
    ("images/a/b/c/d/e.png", "a b c d e"),
    ("images/Hana/Happy.JPEG", "Hana Happy"),
    ("images/scenes.png", "scenes"),               # contains a statement word, isn't one
    ("images/zoomed.png", "zoomed"),
    ("images/ｈａｎａ.png", "hana"),                # NFKC, as names are compared
    ("images/花/笑顔.jpg", "花 笑顔"),
])
def test_usable_names(ref, name):
    assert name_of(ref) == (name, None)


@pytest.mark.parametrize("word, ok", [
    ("hana", True), ("2b", True), ("Smile", True), ("café", True), (CAFE_NFD, True),
    ("", False), ("a-b", False), ("a b", False), ("a.b", False), ("show", False),
    ("SHOW", False), ("python", False), ("layer", False), ("Zoom", False), ("with", False),
])
def test_is_image_word(word, ok):
    assert is_image_word(word) is ok
    assert (word_problem(word) is None) is ok


# SR-F04-01 has two implementations (the runtime's and ``engine.script.words``'s); the words
# of both tables (this file's and test_stage_parse.py's), plus a few case-folding edges.
PARITY_WORDS = ["hana", "2b", "Smile", "café", CAFE_NFD, "", "a-b", "a b", "a.b", "show",
                "SHOW", "python", "layer", "Zoom", "with", "hana_happy", "ｈａｎａ", "é",
                "zoom", "call", "SCENE", "hana-happy", "İ", "ß", "ＳＨＯＷ", "_", "x" * 300]


def test_is_image_word_agrees_with_the_script_package():
    from engine.script import words
    assert [w for w in PARITY_WORDS if is_image_word(w) is not words.is_image_word(w)] == []


# --- AC-F04-02: unusable files, duplicates, and black --------------------------------------

def test_ac_f04_02_unusable_files_are_listed_not_named():
    index = index_of(AC02_W10_FILES + ["images/hana/happy.png"])
    assert index.names == {"hana happy", "black"}
    assert [p.ref for p in index.problems] == sorted(AC02_W10_FILES)
    assert [p.ref for p in index.problems] == [
        "images/a.b.png", "images/a/b/c/d/e/f.png", "images/bg/bridge-day.png",
        "images/club day.png", "images/scene.png", "images/zoom.png"]


def test_ac_f04_02_twenty_five_problems_are_all_kept_in_order():
    files = [f"images/x-{i:02}.png" for i in range(25, 0, -1)]
    index = index_of(files)
    assert [p.ref for p in index.problems] == sorted(files)
    assert index.names == {"black"}


@pytest.mark.parametrize("files, name, used, others", [
    (["images/hana/happy.png", "images/hana/happy.webp"], "hana happy", "images/hana/happy.png",
     ["images/hana/happy.webp"]),
    (["images/hana/sad.jpg", "images/hana/sad.webp"], "hana sad", "images/hana/sad.webp",
     ["images/hana/sad.jpg"]),
    (["images/x.jpg", "images/x.jpeg"], "x", "images/x.jpeg", ["images/x.jpg"]),
    (["images/x.jpg", "images/x.JPG"], "x", "images/x.JPG", ["images/x.jpg"]),
    (["images/x.jpeg", "images/x.webp", "images/x.png", "images/x.jpg"], "x", "images/x.png",
     ["images/x.jpeg", "images/x.jpg", "images/x.webp"]),
    (["images/x.PNG", "images/x.webp"], "x", "images/x.PNG", ["images/x.webp"]),
    ([f"images/{CAFE_NFD}.png", "images/café.webp"], "café", f"images/{CAFE_NFD}.png",
     ["images/café.webp"]),
])
def test_ac_f04_02_duplicates(files, name, used, others):
    index = index_of(files)
    assert index.get(name) == ImageFile(used)
    assert index.duplicates == tuple(Duplicate(name, used, other) for other in sorted(others))


def test_ac_f04_02_case_differs_is_no_duplicate():
    index = index_of(["images/hana/happy.png", "images/hana/Happy.png"])
    assert index.duplicates == ()
    assert index.get("hana happy") == ImageFile("images/hana/happy.png")
    assert index.get("hana Happy") == ImageFile("images/hana/Happy.png")


@pytest.mark.parametrize("files, declarations, expected", [
    ([], [], BLACK),
    (["images/hana/happy.png"], [], BLACK),
    (["images/black.png"], [], ImageFile("images/black.png")),
    (["images/black.webp", "images/black.png"], [], ImageFile("images/black.png")),
    ([], [decl("black", color=(16, 16, 16))], SolidColor((16, 16, 16))),
    (["images/black.png"], [decl("black", color=(16, 16, 16))], SolidColor((16, 16, 16))),
    (["art/void.png"], [decl("black", ref="art/void.png")], ImageFile("art/void.png")),
    (["images/Black.png"], [], BLACK),                 # case-exact: "Black" is another name
])
def test_ac_f04_02_black(files, declarations, expected):
    index = index_of(files, *declarations)
    assert index.get("black") == expected
    assert "black" in index.names and "black" in index.tags


def test_ac_f04_02_black_from_a_real_file(tmp_path):
    write_files(tmp_path, ["images/black.png"])
    index = build_index(NO_PROGRAM, image_source(GamePaths(tmp_path.resolve())))
    assert index.get("black") == ImageFile("images/black.png")


# --- Declarations (SR-F04-05; W12b's data) -------------------------------------------------

def test_declarations_override_files_without_a_message():
    files = ["images/hana/happy.png", "art/Hana_V3.png"]
    declarations = [decl("bg dusk", color=(43, 33, 64)), decl("hana happy", ref="art/Hana_V3.png"),
                    decl("bg sky", color=(43, 33, 64))]
    index = index_of(files, *declarations)
    assert index.get("bg dusk") == index.get("bg sky") == SolidColor((43, 33, 64))
    assert index.get("hana happy") == ImageFile("art/Hana_V3.png")
    assert index.duplicates == () and index.declared_missing == () and index.problems == ()
    assert index.tags == {"bg", "hana", "black"}


@pytest.mark.parametrize("files, ref, suggestion", [
    (["art/festival-final.png"], "art/festival_final.png", "art/festival-final.png"),
    (["art/Festival_final.png"], "art/festival_final.png", "art/Festival_final.png"),
    (["art/x.png"], "art/festival_final.png", None),
    ([], "art/festival_final.png", None),
    (["Art/festival_final.png"], "art/festival_final.png", "Art"),
    (["art/festival_final.png/x.png"], "art/festival_final.png", None),   # a folder
])
def test_missing_declared_file(files, ref, suggestion):
    declaration = decl("bg festival", ref=ref)
    index = index_of(files, declaration)
    assert index.get("bg festival") == ImageFile(ref)          # a placeholder at run time
    assert index.declared_missing == (MissingDeclaration("bg festival", ref, suggestion,
                                                         declaration),)


@pytest.mark.parametrize("ref, suggestion", [
    ("art/festival_final.png", "art/festival-final.png"),
    ("art/festival-final.png", None),
    ("../outside.png", None),
])
def test_missing_declared_file_on_disk(tmp_path, ref, suggestion):
    write_files(tmp_path, ["art/festival-final.png"])
    index = build_index(program_with(decl("bg festival", ref=ref)),
                        image_source(GamePaths(tmp_path.resolve())))
    missing = [(m.ref, m.suggestion) for m in index.declared_missing]
    assert missing == ([] if ref == "art/festival-final.png" else [(ref, suggestion)])


def test_declarations_are_located_in_chunks(monkeypatch):
    monkeypatch.setattr(images_module, "DECLARATION_CHUNK", 2)
    declarations = [decl(f"d{i}", ref=f"art/d{i}.png") for i in range(5)]
    scan = ImageScan(program_with(*declarations), ImageSource.from_files(["art/d1.png"]))
    steps = 1
    while not scan.step():
        steps += 1
    assert steps == 4                    # images/ (absent), then 2 + 2 + 1 declarations
    assert [m.name for m in scan.result.declared_missing] == ["d0", "d2", "d3", "d4"]


def test_a_mapping_of_declarations_is_read_in_order():
    program = SimpleNamespace(images={"b": decl("b", color=(1, 2, 3)),
                                      "a": decl("a", ref="art/a.png")})
    index = build_index(program, ImageSource.from_files([]))
    assert index.get("b") == SolidColor((1, 2, 3))
    assert [m.name for m in index.declared_missing] == ["a"]


# --- Bounds (04 §7.1 step 1; the AC-F04-04 rows Step 6 completes) --------------------------

class Spy:
    def __init__(self, list_dir):
        self.list_dir = list_dir
        self.calls: list[str] = []

    def __call__(self, ref):
        self.calls.append(ref)
        return self.list_dir(ref)


@pytest.mark.parametrize("files", [[], ["images"], ["images.png"], ["art/x.png"]],
                         ids=["empty", "images-is-a-file", "no-folder", "elsewhere"])
def test_no_images_folder_gives_only_black(files):
    index = index_of(files)
    assert index.items() == (("black", BLACK),)
    assert index.problems == () and not index.truncated


def test_depth_is_bounded():
    chain = "/".join(f"d{i}" for i in range(1, 11))
    source = ImageSource.from_files([f"images/{chain}/x.png", "images/top.png"])
    spy = Spy(source.list_dir)
    index = build_index(NO_PROGRAM, ImageSource(spy, source.locate))
    depths = [ref.count("/") for ref in spy.calls]
    assert max(depths) == IMAGE_SCAN_MAX_DEPTH
    assert "images/d1/d2/d3/d4/d5/d6/d7/d8" in spy.calls
    assert index.names == {"top", "black"}


def test_the_scan_stops_at_the_file_cap():
    """20,001 valid files in 21 folders: names from at most 20,000 files, one stop flag."""
    files = [f"images/f{f:02}/i{i:04}.png" for f in range(21) for i in range(953)]
    files = files[:20_001]
    assert len(files) == 20_001 and len({ref.split("/")[1] for ref in files}) == 21
    index = index_of(files)
    assert index.truncated
    assert len(index.names - {"black"}) <= IMAGE_SCAN_MAX_FILES
    assert len(index.names) > IMAGE_SCAN_MAX_FILES - 100
    # the cut is the same however the listing is ordered
    source = ImageSource.from_files(files)
    assert build_index(NO_PROGRAM, ImageSource(Reversed(source.list_dir), source.locate)) == index


def test_at_the_cap_nothing_is_cut():
    files = [f"images/i{i:05}.png" for i in range(IMAGE_SCAN_MAX_FILES)]
    index = index_of(files)
    assert not index.truncated and len(index.names) == IMAGE_SCAN_MAX_FILES + 1


def test_a_folder_a_ref_cannot_hold_is_skipped():
    source = ImageSource.from_files(["images/ok/a.png", "images/bad/b.png"])

    def list_dir(ref):
        if ref == "images/bad":
            raise AssetRefError(ref, "nope")
        return source.list_dir(ref)

    assert build_index(NO_PROGRAM, ImageSource(list_dir, source.locate)).names == {
        "ok a", "black"}


# --- ImageSource.from_files ----------------------------------------------------------------

def test_from_files_lists_like_game_paths(tmp_path):
    files = ["images/b.png", "images/a/x.png", "images/a/y.webp", "art/z.png"]
    write_files(tmp_path, files)
    paths = GamePaths(tmp_path.resolve())
    memory = ImageSource.from_files(files)
    for ref in ("images", "images/a", "art", "images/b.png", "missing", "images/missing"):
        assert memory.list_dir(ref) == paths.list_dir(ref), ref


@pytest.mark.parametrize("bad", ["/abs.png", "../x.png", "images\\x.png", ""])
def test_from_files_takes_game_relative_refs(bad):
    with pytest.raises(AssetRefError):
        ImageSource.from_files([bad])


def test_from_files_takes_strings_only():
    with pytest.raises(TypeError):
        ImageSource.from_files([b"images/x.png"])


def test_index_is_immutable():
    index = index_of(["images/x.png"])
    with pytest.raises(AttributeError):
        index.names = frozenset()        # type: ignore[misc]
    with pytest.raises(TypeError):
        hash(index)


# --- LaunchJob phase 4 and run_headless(image_files=) (§7.2) -------------------------------

FILES = ["images/hana/happy.png", "images/bg/river_night.png"]


def test_launch_phase_4_sets_result_images(tmp_path):
    program = load_r(tmp_path)
    result = run_launch(program, images=ImageSource.from_files(FILES))
    assert result.namespace is not None
    assert result.images == index_of(FILES)
    assert result.images.get("hana happy") == ImageFile("images/hana/happy.png")


def test_launch_phase_4_is_sliced_one_directory_per_step(tmp_path):
    program = load_r(tmp_path)

    def steps(files):
        job = LaunchJob(program, images=ImageSource.from_files(files))
        count = 1
        while not job.step():
            count += 1
        return count, job.result.images

    few, small = steps(["images/a.png"])
    many, large = steps(["images/a.png", "images/b/c.png", "images/d/e.png", "images/d/f/g.png"])
    assert many - few == 3 and small != large


@pytest.mark.parametrize("T, images, expected", [
    (None, None, None),                                        # no source: no scan
    ("define e = 1 / 0", ImageSource.from_files(FILES), None),  # a define failed: skipped
])
def test_launch_phase_4_runs_only_with_a_source_and_clean_defines(tmp_path, T, images,
                                                                  expected):
    result = run_launch(load_r(tmp_path, T=T), images=images)
    assert result.images is expected


def test_a_failing_speaker_check_still_scans(tmp_path):
    from tests.runtime.test_launch import load_r2
    program = load_r2(tmp_path, 'define daichi = "Daichi"', S='daichi "Yo."')
    result = run_launch(program, images=ImageSource.from_files(FILES))
    assert result.error_count == 1 and result.images == index_of(FILES)


def test_run_headless_takes_image_files(tmp_path, opened):  # noqa: F811
    program = load_r(tmp_path)
    plain = run_headless(program, seed=42)
    with opened() as events:
        with_files = run_headless(program, seed=42, image_files=FILES)
    assert not events
    assert with_files == plain and any(type(c) is Say for c in plain)


# --- AC-F04-04 on disk: the scan is bounded and opens nothing (with step 6's launch) --------

class ListingSpy:
    """Spies on ``os.scandir`` and ``os.listdir`` (each call with whether it came from inside
    ``GamePaths.list_dir``) and on the folders ``list_dir`` is asked for."""

    def __init__(self, monkeypatch):
        import os

        self.calls: list[tuple[str, str, bool]] = []
        self.listed: list[str] = []
        self._inside = 0
        real_list_dir = GamePaths.list_dir

        def list_dir(paths, ref):
            self.listed.append(ref)
            self._inside += 1
            try:
                return real_list_dir(paths, ref)
            finally:
                self._inside -= 1

        def spy(name, real):
            def call(path=".", *args, **kwargs):
                self.calls.append((name, os.fspath(path), self._inside > 0))
                return real(path, *args, **kwargs)
            return call

        monkeypatch.setattr(GamePaths, "list_dir", list_dir)
        monkeypatch.setattr(os, "scandir", spy("scandir", os.scandir))
        monkeypatch.setattr(os, "listdir", spy("listdir", os.listdir))

    def only_list_dir(self) -> bool:
        return bool(self.calls) and all(inside for _, _, inside in self.calls)


def ac04_launch(root, opened, monkeypatch):  # noqa: F811
    """A story that names no image, loaded from ``root``, then launched over the real
    folder with the image scan and the stage check; returns (result, spy, open events)."""
    from tests.runtime.stage_story import load_game, write_game

    write_game(root, {"main.vns": 'label start:\n    "A."\n'})
    program = load_game(root)
    paths = GamePaths(root.resolve())
    spy = ListingSpy(monkeypatch)
    with opened() as events:
        result = run_launch(program, images=image_source(paths))
    return result, spy, [e for e in events if e[0] == "open"]


@pytest.mark.parametrize("make", ["none", "file"], ids=["no-images", "images-is-a-file"])
def test_ac_f04_04_no_images_folder(tmp_path, opened, monkeypatch, make):  # noqa: F811
    root = tmp_path / "g"
    root.mkdir()
    if make == "file":
        (root / "images").write_bytes(b"not a folder")
    result, spy, opens = ac04_launch(root, opened, monkeypatch)
    assert result.namespace is not None and result.warnings == ()
    assert result.images.items() == (("black", BLACK),)
    assert opens == [] and all(inside for _, _, inside in spy.calls)


@pytest.mark.slow
def test_ac_f04_04_twenty_thousand_and_one_files_on_disk(tmp_path, opened, monkeypatch):  # noqa: F811
    root = tmp_path / "g"
    for f in range(21):
        folder = root / "images" / f"f{f:02}"
        folder.mkdir(parents=True)
        for i in range(953 if f < 20 else 941):
            (folder / f"i{i:04}.png").write_bytes(b"")
    assert sum(1 for _ in (root / "images").rglob("*.png")) == 20_001
    result, spy, opens = ac04_launch(root, opened, monkeypatch)
    assert result.namespace is not None                        # launch continues
    index = result.images
    assert index.truncated and len(index.names - {"black"}) <= IMAGE_SCAN_MAX_FILES
    line = ("Image scan stopped after 20,000 files; image names beyond that were not "
            "checked.")
    assert [w.format() for w in result.warnings if line in w.format()] == [line]
    assert [w.code for w in result.warnings] == ["W10b"]
    assert opens == [] and spy.only_list_dir()


def test_ac_f04_04_a_deep_chain_is_never_listed_past_depth_8(tmp_path, opened, monkeypatch):  # noqa: F811
    root = tmp_path / "g"
    chain = root / "images" / "/".join(f"d{i}" for i in range(1, 11))
    chain.mkdir(parents=True)
    (chain / "x.png").write_bytes(b"")
    (root / "images" / "top.png").write_bytes(b"")
    result, spy, opens = ac04_launch(root, opened, monkeypatch)
    depths = [ref.count("/") for ref in spy.listed if ref.startswith("images")]
    assert max(depths) == IMAGE_SCAN_MAX_DEPTH
    assert result.images.names == {"top", "black"} and result.warnings == ()
    assert opens == [] and spy.only_list_dir()


def test_ac_f04_04_a_directory_link_out_of_the_game_is_not_followed(tmp_path, opened,  # noqa: F811
                                                                    monkeypatch):
    from tests.script.message_cases import _link

    outside = tmp_path / "outside"
    (outside / "secret").mkdir(parents=True)
    (outside / "leak.png").write_bytes(b"")
    (outside / "secret" / "deep.png").write_bytes(b"")
    root = tmp_path / "g"
    (root / "images").mkdir(parents=True)
    (root / "images" / "ok.png").write_bytes(b"")
    _link(root / "images" / "ext", outside, folder=True)
    result, spy, opens = ac04_launch(root, opened, monkeypatch)
    assert result.images.names == {"ok", "black"} and result.warnings == ()
    assert not any(ref.startswith("images/ext") for ref in spy.listed)
    scanned = [path for _, path, _ in spy.calls]
    assert not any(str(outside) in path or "outside" in path for path in scanned), scanned
    assert opens == [] and spy.only_list_dir()
