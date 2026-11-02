"""F04 step 7 — the prefetcher and its decode worker (``04-technical.md`` §7.7; ADR-0007):
AC-F04-43, 44, 47; ``StageView.prefetch``/``update``/``prefetch_pending`` (F15 I-7).

Most tests run the prefetcher synchronously (``threaded=False``) with a recording decoder;
AC-F04-43's thread rows and AC-F04-44 (a) use the real worker thread, which every test
stops and joins in teardown.
"""

import ast
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pygame
import pytest

from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from engine.render import prefetch as prefetch_module
from engine.render.assets import AssetManager
from engine.render.canvas import RenderQuality
from engine.render.prefetch import (PREFETCH_ONE_MAX, PREFETCH_TOTAL_MAX, DecodeJob, Decoded,
                                    ImagePrefetcher, PrefetchRequest, decode_image)
from engine.render.stage import StageView
from engine.runtime.commands import PrefetchImages, Say, ShowStage
from engine.runtime.images import ImageFile, ImageIndex
from engine.runtime.stage import EMPTY_STAGE
from tests.fixtures.F04 import gen_images as gen
from tests.render.conftest import make_assets
from tests.render.test_stage_view import LANTERN_COLORS, Rig, _image_index, lanterns_game
from tests.runtime.stage_story import IMG_L, load_game, run_h

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]
MAIN = threading.main_thread().ident


class Recorder:
    """A decoder that records each job and the thread it ran on, then decodes for real."""

    def __init__(self) -> None:
        self.jobs: list[DecodeJob] = []
        self.threads: set[int] = set()

    def __call__(self, job: DecodeJob) -> Decoded:
        self.jobs.append(job)
        self.threads.add(threading.get_ident())
        return decode_image(job)

    @property
    def refs(self) -> list[str]:
        return [job.ref for job in self.jobs]


@pytest.fixture
def prefetchers():
    """Builds prefetchers and stops (joins) every one at teardown."""
    made: list[ImagePrefetcher] = []

    def make(assets, **kwargs) -> ImagePrefetcher:
        p = ImagePrefetcher(assets, **kwargs)
        made.append(p)
        return p

    yield make
    for p in made:
        assert p.stop(5.0), "the decode worker did not end"


def pump_until_idle(p: ImagePrefetcher, *, limit_s: float = 20.0, frames: list | None = None
                    ) -> int:
    """Pump once per 'frame' until nothing is pending; returns the frame count."""
    deadline = time.monotonic() + limit_s
    n = 0
    while p.pending:
        assert time.monotonic() < deadline, "prefetch did not finish"
        p.pump()
        n += 1
        if frames is not None:
            frames.append(n)
        if p.pending and p.threaded:
            time.sleep(0.002)
    p.pump()                       # nothing left; a harmless extra frame
    return n


def write_pngs(root: Path, images: dict[str, pygame.Surface | bytes]) -> GamePaths:
    gen.write(root, images)
    return GamePaths.for_game(root)


def solid(w: int, h: int, color=(10, 120, 200)) -> pygame.Surface:
    s = pygame.Surface((w, h), 0, 24)
    s.fill(color)
    return s


# --- AC-F04-43 — inside the budget and the main thread -----------------------------------------

BIG = "images/big.png"
MID = [f"images/mid{n}.png" for n in range(1, 7)]


def _ac43_game(root: Path, *, big: bool = False) -> GamePaths:
    files = {BIG: solid(4096, 4096)} if big else {}
    files.update({ref: solid(1500, 1000, (n * 30, 40, 90)) for n, ref in enumerate(MID)})
    return write_pngs(root, files)


def test_ac_f04_43_budget_rows(tmp_path, prefetchers):
    assets = make_assets(_ac43_game(tmp_path / "game", big=True), cache_mb=64)
    assert 1500 * 1000 * 4 / 2**20 == pytest.approx(5.72, abs=0.01)
    recorder = Recorder()
    p = prefetchers(assets, threaded=False, decode=recorder)
    p.request([PrefetchRequest(BIG)] + [PrefetchRequest(ref) for ref in MID])
    pump_until_idle(p)
    assert BIG not in recorder.refs                          # over 25%: never sent
    assert recorder.refs == MID[:5]                          # the sixth would pass 50%
    assert all(assets.is_cached(ref) for ref in MID[:5])
    assert not assets.is_cached(MID[5]) and not assets.is_cached(BIG)
    assert PREFETCH_ONE_MAX == 0.25 and PREFETCH_TOTAL_MAX == 0.5


def test_ac_f04_43_a_cached_image_sends_nothing(tmp_path, prefetchers, monkeypatch):
    paths = _ac43_game(tmp_path / "game")
    assets = make_assets(paths, cache_mb=64)
    assets.image(MID[0])
    reads = []
    real = GamePaths.read_file
    monkeypatch.setattr(GamePaths, "read_file", lambda self, ref, **kw: (reads.append(ref),
                                                                       real(self, ref, **kw))[1])
    recorder = Recorder()
    p = prefetchers(assets, threaded=False, decode=recorder)
    p.request([PrefetchRequest(MID[0]), PrefetchRequest(MID[1])])
    pump_until_idle(p)
    assert recorder.refs == [MID[1]] and reads == [MID[1]]


def test_ac_f04_43_every_shared_object_is_touched_on_the_main_thread(tmp_path, prefetchers,
                                                                     monkeypatch):
    """The real worker thread: GamePaths, AssetManager, and SizedLru calls all record the
    main thread; the decoder records the worker; one adoption per frame at most."""
    paths = _ac43_game(tmp_path / "game")
    assets = make_assets(paths, cache_mb=64)
    seen: list[tuple[str, int | None]] = []

    def spy(cls, name):
        real = getattr(cls, name)

        def wrapper(*args, **kwargs):
            seen.append((f"{cls.__name__}.{name}", threading.get_ident()))
            return real(*args, **kwargs)

        monkeypatch.setattr(cls, name, wrapper)

    spy(GamePaths, "read_file")
    for name in ("is_cached", "read_image_bytes", "convert", "variant_key", "adopt", "image",
                 "variant", "surface"):
        spy(AssetManager, name)
    for name in ("get", "put", "hold", "release", "discard", "__contains__"):
        spy(SizedLru, name)
    adopts_per_frame: list[int] = []
    real_adopt = AssetManager.adopt              # the spy above

    def counting_adopt(self, *args):
        adopts_per_frame[-1] += 1
        return real_adopt(self, *args)

    monkeypatch.setattr(AssetManager, "adopt", counting_adopt)
    recorder = Recorder()
    p = prefetchers(assets, threaded=True, decode=recorder)
    p.request([PrefetchRequest(ref, lambda w, h: ((w // 2, h // 2), False)) for ref in MID[:3]])
    deadline = time.monotonic() + 20
    while p.pending:
        assert time.monotonic() < deadline
        adopts_per_frame.append(0)
        p.pump()
        time.sleep(0.002)
    assert p.worker is not None and p.worker.daemon
    assert recorder.refs == MID[:3]
    assert recorder.threads and MAIN not in recorder.threads       # decoded on the worker
    assert {name for name, _ in seen} >= {"GamePaths.read_file", "AssetManager.adopt",
                                           "SizedLru.put", "AssetManager.convert"}
    assert {ident for _, ident in seen} == {MAIN}
    assert max(adopts_per_frame) == 1 and sum(adopts_per_frame) == 3
    for ref in MID[:3]:                                   # source and pre-scaled variant
        assert assets.is_cached(ref)
        assert assets.variant_key(ref, (750, 500)) in assets.cache


def test_ac_f04_43_a_corrupt_file_is_dropped_quietly(tmp_path, prefetchers, caplog):
    ref = "images/broken.png"
    paths = write_pngs(tmp_path / "game", {ref: gen.header_only(100, 100)})
    assets = make_assets(paths)
    recorder = Recorder()
    p = prefetchers(assets, threaded=False, decode=recorder)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        p.request([PrefetchRequest(ref)])
        pump_until_idle(p)
        assert recorder.refs == [ref]                       # sent: its header is fine
        assert not assets.is_cached(ref)
        assert [r for r in caplog.records if r.name.startswith("vn")] == []
        image = assets.image(ref)
    assert image.is_placeholder
    lines = [r for r in caplog.records if r.name == "vn.assets" and r.levelno >= logging.WARNING]
    assert len(lines) == 1 and "could not read image images/broken.png" in lines[0].getMessage()


# --- The prefetcher's other rules --------------------------------------------------------------

def test_a_request_replaces_the_queue(tmp_path, prefetchers):
    paths = write_pngs(tmp_path / "game", {f"images/{n}.png": solid(40, 40) for n in "abcd"})
    recorder = Recorder()
    p = prefetchers(make_assets(paths), threaded=False, decode=recorder)
    p.request([PrefetchRequest("images/a.png"), PrefetchRequest("images/b.png")])
    p.pump()                                                   # a decoded
    p.request([PrefetchRequest("images/c.png"), PrefetchRequest("images/a.png"),
               PrefetchRequest("images/c.png")])
    assert p.pending
    pump_until_idle(p)
    assert recorder.refs == ["images/a.png", "images/c.png"]  # b dropped; a in flight, not again


def test_missing_and_unsupported_files_are_skipped_without_a_log(tmp_path, prefetchers, caplog):
    paths = write_pngs(tmp_path / "game", {"images/ok.png": solid(10, 10)})
    (tmp_path / "game" / "images" / "x.gif").write_bytes(b"GIF89a")
    recorder = Recorder()
    p = prefetchers(make_assets(paths), threaded=False, decode=recorder)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        p.request([PrefetchRequest("images/gone.png"), PrefetchRequest("images/x.gif"),
                   PrefetchRequest("images/ok.png")])
        pump_until_idle(p)
    assert recorder.refs == ["images/ok.png"]
    assert [r for r in caplog.records if r.name.startswith("vn")] == []


def test_pixel_filter_is_never_prescaled(tmp_path, prefetchers):
    paths = write_pngs(tmp_path / "game", {"images/a.png": solid(40, 40)})
    assets = make_assets(paths, scale_filter="pixel")
    recorder = Recorder()
    p = prefetchers(assets, threaded=False, decode=recorder)
    p.request([PrefetchRequest("images/a.png", lambda w, h: ((20, 20), False))])
    pump_until_idle(p)
    assert recorder.jobs[0].size is None and assets.is_cached("images/a.png")
    assert not any(key[0] == "variant" for key in assets.cache.keys())


def test_an_image_loaded_meanwhile_is_not_adopted_again(tmp_path, prefetchers, monkeypatch):
    paths = write_pngs(tmp_path / "game", {"images/a.png": solid(40, 40)})
    assets = make_assets(paths)
    p = prefetchers(assets, threaded=False)
    p.request([PrefetchRequest("images/a.png")])
    p.pump()                                                    # decoded, not yet adopted
    assets.image("images/a.png")                                # show() loaded it first
    adopted = []
    monkeypatch.setattr(AssetManager, "adopt", lambda self, *a: adopted.append(a))
    pump_until_idle(p)
    assert adopted == []


def test_stop_ends_the_worker_and_pump_does_nothing_after(tmp_path):
    paths = write_pngs(tmp_path / "game", {"images/a.png": solid(40, 40)})
    p = ImagePrefetcher(make_assets(paths), threaded=True)
    p.request([PrefetchRequest("images/a.png")])
    p.pump()
    worker = p.worker
    assert worker is not None and worker.is_alive() and worker.name == "vn-image-decoder"
    assert p.stop(5.0)
    assert not worker.is_alive()
    p.request([PrefetchRequest("images/a.png")])
    p.pump()
    assert not p.pending and p.worker is None


def test_platform_flag_is_by_platform_only():
    assert prefetch_module.PREFETCH_THREADED is prefetch_module._THREADED_BY_PLATFORM.get(
        sys.platform, True)


# --- StageView.prefetch, update, prefetch_pending ----------------------------------------------

def test_view_sends_image_files_with_their_sizes(tmp_path, prefetchers):
    root = tmp_path / "game"
    paths = write_pngs(root, {"images/bg.png": solid(1920, 1080), "images/hana/happy.png":
                              solid(300, 600), "images/hana/pout.png": solid(300, 600)})
    assets = make_assets(paths)
    index = ImageIndex({"bg x": ImageFile("images/bg.png"),
                        "hana happy": ImageFile("images/hana/happy.png"),
                        "hana pout": ImageFile("images/hana/pout.png")})
    recorder = Recorder()
    view = StageView(assets, index, art_height=1080,
                     positions={"center": (640.0, 720.0), "left": (320.0, 720.0)},
                     empty_color=(0, 0, 0),
                     prefetcher=prefetchers(assets, threaded=False, decode=recorder))
    assert not view.prefetch_pending
    view.prefetch(PrefetchImages(("bg x", "nothing"), ("hana pout",)))
    assert view.prefetch_pending
    while view.prefetch_pending:
        view.update()
    # Before any FINAL compose there is no size to aim for: decode only.
    assert recorder.refs == ["images/bg.png", "images/hana/pout.png"]
    assert [job.size for job in recorder.jobs] == [None, None]
    # After a FINAL compose at 1280×720: the cover size; the sprite at zoom 1 (art 1080).
    from engine.render.canvas import Canvas
    from engine.core.geometry import Viewport
    canvas = Canvas(assets)
    fb = pygame.Surface((1280, 720))
    canvas.bind(fb, Viewport(1280, 720, 1280, 720, 0, 0, 1280, 720), RenderQuality.FINAL)
    from engine.runtime.stage import SpriteState, StageState
    view.show(ShowStage(StageState(None, (SpriteState("hana", "hana happy", "left", 0, 1.0,
                                                      True),))))
    view.draw(canvas)
    assets.cache.discard(("img", "images/bg.png"))
    assets.cache.discard(("img", "images/hana/pout.png"))
    view.prefetch(PrefetchImages(("bg x",), ("hana pout",)))
    while view.prefetch_pending:
        view.update()
    assert [(job.size, job.flip_x) for job in recorder.jobs[2:]] == [
        ((1280, 720), False), ((200, 400), True)]              # hana stays where she is
    surface, _ = assets.variant(assets.image("images/hana/pout.png"), (200, 400),
                                RenderQuality.FINAL, flip_x=True)
    assert assets.cache.get(assets.variant_key("images/hana/pout.png", (200, 400), True),
                            0)[0] is surface               # the adopted variant is the one used


def test_view_without_a_prefetcher(tmp_path):
    view = StageView(make_assets(None), ImageIndex({}), art_height=720, positions={},
                     empty_color=(0, 0, 0))
    view.prefetch(PrefetchImages(("bg",), ()))
    view.update()
    assert view.prefetch_pending is False


# --- AC-F04-44 — the same picture whichever way it was loaded ----------------------------------

def _lantern_stages(root: Path) -> dict[int, object]:
    """The stage shown with lines 5 and 8 of ``lanterns/``."""
    commands = run_h(load_game(root), images=IMG_L)
    stage, out, line = EMPTY_STAGE, {}, 0
    for c in commands:
        if type(c) is ShowStage:
            stage = c.stage
        elif type(c) is Say:
            line += 1
            if line in (5, 8):
                out[line] = stage
    return out


def _names(stage) -> PrefetchImages:
    return PrefetchImages(() if stage.background is None else (stage.background,),
                          tuple(s.image for s in stage.sprites))


@pytest.mark.parametrize("window", [(1280, 720), (1920, 1080)])
def test_ac_f04_44_same_picture_however_loaded(tmp_path, prefetchers, monkeypatch, window):
    root = lanterns_game(tmp_path / "game")
    from engine.core.config import load_config

    stage_config = load_config(GamePaths.for_game(root)).config.stage
    index = _image_index(root, load_game(root))
    shown = _lantern_stages(root)
    assert shown[5].background == "bg river_night" and shown[8].background == "bg dusk"
    assert any(s.flip for s in shown[8].sprites) and shown[8].sprites[-1].tag == "railing"

    def rig(mode: str):
        r = Rig(tmp_path / "game", {}, window=window, art_height=stage_config.art_height,
                positions=dict(stage_config.positions))
        r.view.index = index
        if mode != "sync":
            r.view.prefetcher = prefetchers(r.app.assets, threaded=(mode == "threaded"))
        r.frame(EMPTY_STAGE)                               # a FINAL compose: sizes known
        assert r.view._final.viewport is not None
        return r

    pictures: dict[str, dict[int, bytes]] = {}
    scaled_in_show: dict[str, int] = {}
    for mode in ("threaded", "sync", "main_thread"):
        r = rig(mode)
        pictures[mode] = {}
        calls = 0
        for line in (5, 8):
            if mode != "sync":
                r.view.prefetch(_names(shown[line]))
                pump_until_idle(r.view.prefetcher)
                assert all(r.app.assets.is_cached(index.get(s.image).ref)
                           for s in shown[line].sprites if isinstance(index.get(s.image),
                                                                       ImageFile))
            real = pygame.transform.smoothscale

            def counting(*args, real=real):
                nonlocal calls
                calls += 1
                return real(*args)

            monkeypatch.setattr(pygame.transform, "smoothscale", counting)
            r.frame(shown[line])
            monkeypatch.setattr(pygame.transform, "smoothscale", real)
            pictures[mode][line] = pygame.image.tobytes(r.view.picture(), "RGB")
        scaled_in_show[mode] = calls
    assert pictures["threaded"] == pictures["sync"] == pictures["main_thread"]
    # The prefetched variants were the ones composed: no scaling while showing.
    # The prefetched variants were the ones composed. Line 8 shows lantern_girl twice, one
    # mirrored; one variant is prefetched per file, so the mirrored one is scaled in show.
    expected = 1 if window == (1280, 720) else 0           # 1920×1080: art is 1:1
    assert scaled_in_show["threaded"] == scaled_in_show["main_thread"] == expected
    if window == (1280, 720):
        assert scaled_in_show["sync"] > expected
    assert set(LANTERN_COLORS) >= {s.image for s in shown[5].sprites}


# --- AC-F04-47 — imports, file access, and no code ---------------------------------------------

def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _imported(tree: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.add(node.module or "")
    return out


def test_ac_f04_47_prefetch_imports_and_worker():
    tree = _tree("engine/render/prefetch.py")
    imported = _imported(tree)
    engine = {name for name in imported if name.startswith("engine")}
    assert all(name == "engine.core" or name.startswith("engine.core.") for name in engine)
    allowed_stdlib = {"threading", "queue", "io", "pygame", "sys", "collections",
                      "collections.abc", "dataclasses", "typing"}
    assert imported - engine <= allowed_stdlib, imported - engine
    banned = {"AssetManager", "SizedLru", "GamePaths", "assets", "paths", "cache"}
    worker_side = [node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name in ("_worker",
                                                                          "decode_image")]
    assert len(worker_side) == 2
    for fn in worker_side:
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        assert not (names | attrs) & banned, fn.name
        assert "_log" not in names and "getLogger" not in attrs and "logging" not in names


def test_ac_f04_47_stage_view_imports():
    imported = _imported(_tree("engine/render/stage.py"))
    assert not any(n.startswith(("engine.script", "engine.app")) for n in imported)


IO_CALLS = {"open", "scandir", "listdir", "read_text", "read_bytes", "write_text",
            "write_bytes", "iterdir", "glob", "rglob", "exists", "is_file", "is_dir", "stat",
            "walk"}


@pytest.mark.parametrize("rel", ["engine/runtime/images.py", "engine/runtime/stage_check.py"])
def test_ac_f04_47_runtime_reads_no_files(rel):
    tree = _tree(rel)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            called.add(f.id if isinstance(f, ast.Name) else
                       f.attr if isinstance(f, ast.Attribute) else "")
    assert not called & IO_CALLS, called & IO_CALLS
    assert "Path" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


AUDIT = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from engine.core.paths import GamePaths
from engine.script.loader import load_story
from tests.script.helpers import template_s

TEXT = "__import__('os').system('x')"
root = Path(sys.argv[1])
(root / "script").mkdir(parents=True)
(root / "script" / "main.vns").write_text(template_s(T=f'image bg x = "{TEXT}"'),
                                          encoding="utf-8")
events = []

def hook(event, args):
    if event == "os.system":
        events.append(event)
    elif event == "compile" and args and isinstance(args[0], (str, bytes)):
        source = args[0] if isinstance(args[0], str) else args[0].decode("utf-8", "replace")
        if TEXT in source:
            events.append(event)
    elif event == "exec" and args and hasattr(args[0], "co_consts"):
        if any(isinstance(c, str) and TEXT in c for c in args[0].co_consts):
            events.append(event)

sys.addaudithook(hook)
result = load_story(GamePaths.for_game(root))
print([e.code for e in result.errors], events)
"""


def test_ac_f04_47_an_image_value_is_never_code(tmp_path):
    out = subprocess.run([sys.executable, "-c", AUDIT, str(tmp_path / "game"), str(REPO)],
                         cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "['E132'] []"
