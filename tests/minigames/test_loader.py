"""The plugin loader (F23 step 3a; ``04`` §7.10; ADR-0009) through Loader L.

AC-F23-19 (discovery), 20 (load errors), 21 (replacing a bundled minigame; API version), 22
(declarations are copied; its Host U sentence is step 4's), 46–49 (05 groups A–D), 58 (the
INFO records), 59 (W165); AC-F23-56 (step 3b: the plugin phase in ``app/loading.py``). In
each abuse group, one row of each expected-outcome kind runs in the default tier and the rest
are ``slow`` (``06`` §0.4). Link rows skip where the machine
can't make symlinks; junction rows run on Windows; FIFO rows on POSIX. The name rules for
names Windows can't create (``con.py``, ``x\\n.py``) run everywhere through a listing that
offers them, with a read spy proving the name never reaches ``read_file``.
"""

import builtins
import hashlib
import importlib
import inspect
import io
import json
import os
import sys
import threading
import traceback
from pathlib import Path

import pytest

from engine.app.story import Watchdog
from engine.core import paths
from engine.core.minigame_types import REQUIRED, ArgSpec, MeterChange, Outcome, StoryNames
from engine.core.paths import DirListing, GamePaths
from engine.minigames import api, bundled, loader, messages
from engine.minigames.api import Arg, Minigame
from engine.runtime import limits
from tests.minigames.conftest import FIXTURES, plugin, write

PLUGINS = "minigames"
SLOW = pytest.mark.slow


def make_junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junctions exist only on Windows")
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks here (needs a privilege on Windows): {exc}")


@pytest.fixture
def reads(monkeypatch):
    """Every ref passed to ``GamePaths.read_file``."""
    seen: list[str] = []
    real = GamePaths.read_file

    def spy(self, ref, **kwargs):
        seen.append(ref)
        return real(self, ref, **kwargs)

    monkeypatch.setattr(GamePaths, "read_file", spy)
    return seen


@pytest.fixture
def short_watchdog(monkeypatch):
    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.1)
    watchdog = Watchdog(tick=0.02)
    watchdog.start()
    yield watchdog
    watchdog.stop()


@pytest.fixture(autouse=True)
def no_bundled(monkeypatch):
    """These rows count registrations, so they run with an empty bundled list (F24 ``07``
    I-9: F24-1 added ``PoemGame``). AC-F24-01 runs the real list once."""
    monkeypatch.setattr(bundled, "BUNDLED", ())


@pytest.fixture
def one_bundled(monkeypatch):
    class PoemGame(Minigame):
        name = "poem_game"
        title = "Poems"

    monkeypatch.setattr(bundled, "BUNDLED", (PoemGame,))
    return PoemGame


# --- AC-F23-19: discovery ----------------------------------------------------------------------

def test_absent_folder_registers_only_the_bundled_list(game, load, one_bundled):
    loaded = load(game)
    assert loaded.result.ok and loaded.names == ["poem_game"]
    entry = loaded.result.registry.get("poem_game")
    assert entry.cls is one_bundled and entry.sig.source == "engine" and entry.bundled
    assert loaded.warnings() == [] and loaded.infos() == []


def test_wrong_case_folder_gives_w164_in_dev(game, load):
    write(game, "Minigames/a.py", plugin("alpha"))
    loaded = load(game)
    assert loaded.result.ok and loaded.names == []
    assert loaded.warnings("W164") == [messages.w164_wrong_case("Minigames")]
    assert load(game, dev=False).warnings() == []


def test_units_run_in_code_point_order_with_relative_imports(game, load):
    order = "import builtins\nbuiltins.__dict__.setdefault('_vn_order', []).append(__name__)\n"
    write(game, "minigames/b.py", order + plugin("bee"))
    write(game, "minigames/a.py", order + plugin("ay"))
    write(game, "minigames/c/__init__.py", order + "from . import helper\n"
          + plugin("sea", body="    title = helper.TITLE\n"))
    write(game, "minigames/c/helper.py", order + "TITLE = 'Sea game'\n")
    try:
        loaded = load(game)
        assert builtins._vn_order == ["_vn_minigames.a", "_vn_minigames.b", "_vn_minigames.c",
                                      "_vn_minigames.c.helper"]
    finally:
        builtins.__dict__.pop("_vn_order", None)
    assert loaded.result.ok and loaded.names == ["ay", "bee", "sea"]
    assert loaded.result.registry.get("sea").sig.title == "Sea game"
    assert loaded.result.registry.get("sea").sig.source == "minigames/c/"
    assert {"_vn_minigames.a", "_vn_minigames.c.helper"} <= set(sys.modules)


def test_one_file_registering_two_minigames(game, load):
    write(game, "minigames/two.py", plugin("first") + plugin("second").split("\n", 1)[1])
    assert load(game).names == ["first", "second"]


def test_a_unit_registering_nothing_gives_w161_in_dev(game, load):
    write(game, "minigames/helpers.py", "X = 1\n")
    loaded = load(game)
    assert loaded.result.ok
    assert loaded.warnings("W161") == [messages.w161_registers_nothing("minigames/helpers.py")]
    assert load(game, dev=False).warnings() == []


def test_a_folder_without_init_gives_w161_and_is_not_read(game, load, reads):
    write(game, "minigames/parts/x.py", plugin("x"))
    loaded = load(game)
    assert loaded.warnings("W161") == [messages.w161_registers_nothing("minigames/parts/")]
    assert reads == [] and loaded.names == []


def test_other_files_and_underscore_names_are_never_read(game, load, reads):
    for name in ("notes.txt", "art.png", "x.pyc", "x.pyd", "x.so", "x.zip", "x.pth",
                 "_private.py", ".hidden.py", "__init__.py", "__pycache__/x.cpython-312.pyc",
                 "__pycache__/a.py"):
        write(game, f"minigames/{name}", b"raise SystemExit('ran')\n")
    loaded = load(game)
    assert loaded.result.ok and reads == [] and loaded.names == []


def test_a_bad_file_name_is_e273_g(game, load, reads):
    write(game, "minigames/Bad Name.py", plugin("bad"))
    loaded = load(game)
    assert loaded.errors == [messages.e273_bad_file_name("minigames/Bad Name.py")]
    assert loaded.codes == ["E273"] and reads == []


def test_one_step_per_file_read_or_module_run(game):
    write(game, "minigames/a.py", plugin("ay"))
    write(game, "minigames/c/__init__.py", "from . import helper\n" + plugin("sea"))
    write(game, "minigames/c/helper.py", "X = 1\n")
    job = loader.PluginLoadJob(GamePaths.for_game(game), dev=True)
    calls: list[str] = []
    real_read, real_exec = job._read, job._execute
    job._read = lambda ref: calls.append(f"read {ref}") or real_read(ref)
    job._execute = lambda unit: calls.append(f"run {unit.ref}") or real_exec(unit)
    steps = []
    while not job.step():
        steps.append(list(calls))
        calls.clear()
    assert [s for s in steps if len(s) > 1] == []                 # never two in one step
    assert [c for s in steps for c in s] == [
        "read minigames/a.py", "run minigames/a.py", "read minigames/c/__init__.py",
        "read minigames/c/helper.py", "run minigames/c/"]
    assert job.result.ok


# --- AC-F23-20: load errors -----------------------------------------------------------------------

def test_python_mistake_names_the_line(game, load):
    write(game, "minigames/stargazing.py", "\n" * 11 + "x = (\n")
    loaded = load(game)
    assert loaded.errors == ['minigames/stargazing.py, line 12: this minigame plugin has a '
                             'Python mistake: "(" was never closed.']
    record = [r for r in loaded.records if r.levelno >= 40]
    assert len(record) == 1 and "SyntaxError" in record[0].exc_text      # the log has it


def test_stopped_with_an_error_names_the_line_and_logs_the_traceback(game, load):
    write(game, "minigames/stargazing.py", "\n" * 29 + "SKY = sky\n")
    loaded = load(game, dev=False)
    assert loaded.errors == [
        'minigames/stargazing.py, line 30: this minigame plugin stopped with an error while '
        'loading: name "sky" is not defined. Fix the plugin; the log has the details.']
    trace = [r.exc_text for r in loaded.records if r.exc_text]
    assert len(trace) == 1 and '<minigames/stargazing.py>", line 30' in trace[0]
    assert "SKY = sky" in trace[0]                       # the source line, from linecache
    assert "_vn_minigames.stargazing" not in sys.modules


DECLARATIONS = [
    ("no name", "    pass\n", None, messages.E273_NO_NAME),
    ("bad name", "    name = 'Star Gazing'\n", None, messages.e273_bad_name("Star Gazing")),
    ("arg name", "    args = {'2nd': Arg()}\n", "x", messages.e273_bad_arg_name("2nd")),
    ("33 args", "    args = {f'a{i}': Arg() for i in range(33)}\n", "x",
     messages.e273_too_many_args(33, 32)),
    ("set default", "    args = {'pairs': Arg(default={1})}\n", "x",
     "the default of pairs holds a set, which can't be saved. Use a list instead."),
    ("set test", "    test_outcome = Outcome({1})\n", "x",
     "the test outcome holds a set, which can't be saved. Use a list instead."),
    ("set skipped", "    skipped_outcome = Outcome({1})\n", "x",
     "the skipped outcome holds a set, which can't be saved. Use a list instead."),
    ("title property", "    @property\n    def title(self):\n        return 'T'\n", "x",
     messages.e273_not_plain("title")),
    ("name str subclass", "    name = type('S', (str,), {})('stargazing')\n", None,
     messages.e273_not_plain("name")),
]


@pytest.mark.parametrize("label, body, name, expected", DECLARATIONS,
                         ids=[d[0] for d in DECLARATIONS])
def test_declaration_forms(game, load, label, body, name, expected):
    source = ("from engine.minigames.api import Arg, Minigame, Outcome, register\n\n"
              "class Game(Minigame):\n"
              + (f"    name = {name!r}\n" if name else "") + body
              + "\nregister(Game)\n")
    write(game, "minigames/stargazing.py", source)
    loaded = load(game)
    line = source.count("\n")                            # the register(...) line
    assert loaded.errors == [f"minigames/stargazing.py, line {line}: {expected}"]
    assert loaded.names == []


def test_a_caught_declaration_error_is_still_reported(game, load):
    write(game, "minigames/x.py", "from engine.minigames.api import Minigame, register\n"
          "class G(Minigame):\n    pass\ntry:\n    register(G)\nexcept Exception:\n    pass\n")
    assert load(game).errors == [f"minigames/x.py, line 5: {messages.E273_NO_NAME}"]


def test_stuck_top_level_is_stopped_by_the_watchdog(game, load, short_watchdog):
    write(game, "minigames/spin.py", "x = 0\nwhile True:\n    x += 1\n")
    loaded = load(game, guard=short_watchdog)
    assert len(loaded.errors) == 1
    assert loaded.errors[0].startswith("minigames/spin.py, line ")
    assert loaded.errors[0].endswith(messages.e273_stuck(0.1))
    assert "0.1 seconds" in loaded.errors[0]
    assert short_watchdog.consume_fired() is False


@SLOW
def test_sleeping_top_level_is_stopped_by_the_watchdog(game, load, short_watchdog):
    write(game, "minigames/nap.py", "import time\ntime.sleep(60)\n")
    loaded = load(game, guard=short_watchdog)
    assert loaded.errors == [f"minigames/nap.py, line 2: {messages.e273_stuck(0.1)}"]


def test_another_api_major(game, load):
    write(game, "minigames/x.py", plugin("x", body="    api = '0.9'\n"))
    assert load(game).errors == [messages.e273_other_major("minigames/x.py", 0)]


def test_bytes_that_are_not_utf8(game, load):
    write(game, "minigames/x.py", b"X = '\xff'\n")
    loaded = load(game)
    assert loaded.errors == [messages.e273_not_utf8("minigames/x.py")]
    assert "_vn_minigames.x" not in sys.modules


def test_two_units_one_name_is_e274_naming_both(game, load):
    write(game, "minigames/stargazing.py", plugin("stargazing"))
    write(game, "minigames/night_sky/__init__.py", plugin("stargazing"))
    loaded = load(game)
    assert loaded.errors == ['two minigame plugins use the name "stargazing": '
                             "minigames/night_sky/ and minigames/stargazing.py. Rename one of "
                             "them."]
    assert loaded.codes == ["E274"]
    assert loaded.result.registry.get("stargazing").unit == "minigames/night_sky/"


def test_errors_are_capped_at_fifty(game, load, monkeypatch):
    for i in range(53):
        write(game, f"minigames/Bad{i:02}.py", "")
    loaded = load(game)
    assert len(loaded.result.errors) == 50 and loaded.result.error_count == 53


# --- AC-F23-21: replacing a bundled minigame; API version ------------------------------------

def test_a_game_plugin_replaces_a_bundled_one(game, load, one_bundled):
    write(game, "minigames/my_poems.py", plugin("poem_game"))
    loaded = load(game)
    entry = loaded.result.registry.get("poem_game")
    assert entry.unit == "minigames/my_poems.py" and entry.cls is not one_bundled
    assert loaded.warnings("W160") == [messages.w160_replaces("minigames/my_poems.py",
                                                              "poem_game")]
    replaced = [m for m in loaded.infos() if "replaces" in m]
    assert replaced == [messages.info_replaced("minigames/my_poems.py", "poem_game")]
    release = load(game, dev=False)
    assert release.warnings() == []
    assert [m for m in release.infos() if "replaces" in m] == replaced


def test_newer_minor_is_e278(game, load):
    write(game, "minigames/x.py", plugin("x", body="    api = '1.4'\n"))
    loaded = load(game)
    assert loaded.codes == ["E278"]
    assert loaded.errors == ["minigames/x.py needs minigame API 1.4, but this engine has 1.1. "
                             "Update the engine, or use a version of the plugin made for 1.1."]


@pytest.mark.parametrize("version", ["1.0", "1"])
def test_same_api_loads(game, load, version):
    write(game, "minigames/x.py", plugin("x", body=f"    api = {version!r}\n"))
    loaded = load(game)
    assert loaded.result.ok and loaded.result.registry.get("x").api == "1.0"


def test_a_later_engine_minor_keeps_1_0_working(game, load, monkeypatch):
    monkeypatch.setattr(api, "API_VERSION", (1, 3))
    write(game, "minigames/x.py", plugin("x", body="    api = '1.0'\n"))
    write(game, "minigames/y.py", plugin("y", body="    api = '1.3'\n"))
    assert load(game).names == ["x", "y"]


# --- AC-F23-22: a minimal plugin; declarations are copied -------------------------------------

def test_bare_registers_with_the_defaults(game, load):
    write(game, "minigames/bare.py", (FIXTURES / "bare.py").read_bytes())
    entry = load(game).result.registry.get("bare")
    assert entry.sig.title == "bare" and entry.api == "1.0" and entry.sig.args == ()
    assert entry.sig.test is None and entry.sig.skipped is None and entry.over_stage is False
    assert entry.sig.check is None


def test_probe_declarations_are_copied(game, load):
    write(game, "minigames/probe.py", (FIXTURES / "probe.py").read_bytes())
    loaded = load(game)
    entry = loaded.result.registry.get("probe")
    sig = entry.sig
    assert sig.title == "Probe game" and sig.source == "minigames/probe.py"
    assert sig.args == (ArgSpec("pairs", REQUIRED), ArgSpec("hints", False),
                        ArgSpec("label", ""))
    assert sig.test == Outcome(9, (MeterChange("hana", "+=", 1),))
    assert sig.skipped == Outcome("skipped")
    assert entry.tokens == {"card.back_color": "#203040"}
    assert entry.words == {"hint": "Find the pairs"}
    probe = entry.cls
    probe.args = {}
    probe.title = "X"
    assert loaded.result.registry.get("probe").sig == sig
    story = StoryNames((), (), ())
    assert sig.check({"pairs": 6}, story) is None                # I-10: a fresh instance
    assert sig.check({"pairs": "x"}, story) == "pairs must be a whole number from 1 to 12"


def test_a_frozen_default_shares_nothing_with_the_class(game, load):
    write(game, "minigames/x.py", plugin("x", body="    args = {'cards': Arg(default=[1, [2]])}\n"))
    entry = load(game).result.registry.get("x")
    entry.cls.args["cards"].default[1].append(3)
    assert entry.sig.args == (ArgSpec("cards", [1, [2]]),)


def test_register_outside_loading_is_refused():
    class G(Minigame):
        name = "g"

    api._set_registry(None)
    with pytest.raises(RuntimeError):
        api.register(G)


# --- AC-F23-46: group A, only real entries of the real folder ------------------------------

@pytest.mark.parametrize("target", ["outside", "saves", pytest.param("characters", marks=SLOW)])
def test_a_linked_minigames_folder_loads_nothing(game, load, reads, target):
    where = game.parent / "outside" if target == "outside" else game / target
    write(game.parent if target == "outside" else game, f"{target}/x.py", plugin("x"))
    make_junction(game / "minigames", where)
    loaded = load(game)
    assert loaded.errors == [messages.E273_NOT_A_REAL_FOLDER] and reads == []
    assert loaded.names == []


def test_minigames_as_a_file_loads_nothing(game, load):
    write(game, "minigames", b"not a folder")
    assert load(game).errors == [messages.E273_NOT_A_REAL_FOLDER]


@SLOW
def test_a_symlinked_minigames_folder_loads_nothing(game, load):
    write(game, "saves/x.py", plugin("x"))
    make_symlink(game / "minigames", game / "saves", directory=True)
    assert load(game).errors == [messages.E273_NOT_A_REAL_FOLDER]


def test_a_junction_package_is_left_out_with_one_w163(game, load, reads):
    write(game, "saves/pkg/__init__.py", plugin("evil"))
    write(game, "minigames/a.py", plugin("ay"))
    make_junction(game / "minigames" / "pkg", game / "saves" / "pkg")
    loaded = load(game)
    assert loaded.result.ok and loaded.names == ["ay"]
    assert loaded.warnings("W163") == [messages.w163_link("minigames/pkg")]
    assert reads == ["minigames/a.py"]
    assert all("saves" not in m for m in loaded.warnings())          # never the target


@pytest.mark.parametrize("target", ["outside", pytest.param("logs", marks=SLOW)])
def test_a_file_symlink_is_left_out(game, load, reads, target):
    source = game.parent / "evil.py" if target == "outside" else game / "logs" / "latest.log"
    write(source.parent, source.name, plugin("evil"))
    (game / "minigames").mkdir()
    make_symlink(game / "minigames" / "x.py", source)
    loaded = load(game)
    assert loaded.warnings("W163") == [messages.w163_link("minigames/x.py")] and reads == []


@SLOW
def test_a_linked_file_inside_a_package_is_left_out(game, load, reads):
    write(game, "saves/evil.py", "EVIL = 1\n")
    write(game, "minigames/pkg/__init__.py", plugin("pkg"))
    make_symlink(game / "minigames" / "pkg" / "evil.py", game / "saves" / "evil.py")
    loaded = load(game)
    assert loaded.warnings("W163") == [messages.w163_link("minigames/pkg/evil.py")]
    assert reads == ["minigames/pkg/__init__.py"] and loaded.names == ["pkg"]


def test_a_special_file_is_left_out_without_hanging(game, load, reads, monkeypatch):
    """The FIFO/device row on every OS: the listing reports the entry as special."""
    write(game, "minigames/x.py", plugin("x"))
    real_kind = paths._entry_kind
    monkeypatch.setattr(paths, "_entry_kind",
                        lambda e: paths._SPECIAL if e.name == "x.py" else real_kind(e))
    loaded = load(game)
    assert loaded.warnings("W163") == [messages.w163_not_regular("minigames/x.py")]
    assert reads == [] and loaded.names == [] and loaded.result.ok


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs exist only on POSIX")
@SLOW
def test_a_real_fifo_is_left_out_without_hanging(game, load):
    (game / "minigames").mkdir()
    os.mkfifo(game / "minigames" / "x.py")
    loaded = load(game, check_tree=False)
    assert loaded.warnings("W163") == [messages.w163_not_regular("minigames/x.py")]


def test_a_hard_link_to_an_outside_file_loads(game, load):
    outside = write(game.parent, "outside.py", plugin("hard"))
    (game / "minigames").mkdir()
    try:
        os.link(outside, game / "minigames" / "hard.py")
    except OSError as exc:
        pytest.skip(f"cannot create hard links here: {exc}")
    assert load(game).names == ["hard"]


def test_a_link_swapped_in_after_listing_is_not_read(game, load, monkeypatch):
    write(game, "minigames/a.py", plugin("ay"))
    write(game, "minigames/x/__init__.py", plugin("ex"))
    (game / "saves").mkdir()
    real = GamePaths.read_file

    def swap(self, ref, **kwargs):
        if ref == "minigames/x/__init__.py" and not (game / "moved").exists():
            os.replace(game / "minigames" / "x", game / "moved")
            make_junction(game / "minigames" / "x", game / "moved")    # a contained link
        return real(self, ref, **kwargs)

    monkeypatch.setattr(GamePaths, "read_file", swap)
    loaded = load(game, check_tree=False)
    assert loaded.names == ["ay"] and loaded.result.ok
    assert loaded.warnings("W163") == [messages.w163_not_regular("minigames/x/__init__.py")]


def test_a_cloud_placeholder_loads_like_a_file(game, load, monkeypatch):
    write(game, "minigames/a.py", plugin("ay"))
    real_kind = paths._entry_kind
    monkeypatch.setattr(paths, "_entry_kind",
                        lambda e: paths._LINK if e.name in ("minigames", "a.py")
                        else real_kind(e))
    loaded = load(game)
    assert loaded.names == ["ay"] and loaded.warnings() == []


# --- AC-F23-47: group B, one ASCII name rule -----------------------------------------------

def test_json_py_loads_under_the_prefix_and_never_shadows(game, load):
    stdlib = sys.modules["json"]
    write(game, "minigames/json.py", "import json as outer\nOUTER = outer\n" + plugin("jj"))
    write(game, "minigames/other.py", "import json\nSEEN = json\n" + plugin("other"))
    loaded = load(game)
    assert loaded.result.ok and loaded.names == ["jj", "other"]
    assert sys.modules["json"] is stdlib and json is stdlib
    assert sys.modules["_vn_minigames.json"].OUTER is stdlib
    assert sys.modules["_vn_minigames.other"].SEEN is stdlib
    assert importlib.import_module("json") is stdlib


@SLOW
@pytest.mark.parametrize("stem", ["os", "sys", "engine"])
def test_engine_and_stdlib_names_load_under_the_prefix(game, load, stem):
    before = sys.modules[stem]
    write(game, f"minigames/{stem}.py", plugin(f"g_{stem}"))
    assert load(game).names == [f"g_{stem}"]
    assert sys.modules[stem] is before and f"_vn_minigames.{stem}" in sys.modules


BAD_NAMES = [   # (listed name, expected: "bad" | "reserved" | "skip"), default-tier kinds first
    ("Json.py", "bad"), ("con.py", "reserved"), ("_vn_minigames.py", "skip"),
    ("json.PY", "skip"),
    pytest.param("JSON.py", "bad", marks=SLOW), pytest.param("nul.py", "reserved", marks=SLOW),
    pytest.param("aux.py", "reserved", marks=SLOW),
    pytest.param("com1.py", "reserved", marks=SLOW),
    pytest.param("lpt¹.py", "bad", marks=SLOW),
    pytest.param("jsоn.py", "bad", marks=SLOW),              # Cyrillic о
    pytest.param("ｊｓｏｎ.py", "bad", marks=SLOW),
    pytest.param("café.py", "bad", marks=SLOW),         # NFD café
    pytest.param("x\n.py", "bad", marks=SLOW),
    pytest.param("for.py", "reserved", marks=SLOW),
    pytest.param("a" * 41 + ".py", "bad", marks=SLOW),
    pytest.param("__init__.py", "skip", marks=SLOW),
    pytest.param(".x.py", "skip", marks=SLOW),
]


def _offer(monkeypatch, where: str, names: tuple[str, ...], dirs: tuple[str, ...] = ()):
    """A listing of ``where`` that offers these names (files Windows can't create)."""
    real = GamePaths.list_real

    def listing(self, ref):
        if ref == where:
            found = real(self, ref)
            return DirListing(tuple(sorted((*found.files, *names))), found.dirs)
        return real(self, ref)

    monkeypatch.setattr(GamePaths, "list_real", listing)


@pytest.mark.parametrize("name, kind", BAD_NAMES)
def test_bad_names_at_the_top_level(game, load, reads, monkeypatch, name, kind):
    (game / "minigames").mkdir()
    _offer(monkeypatch, "minigames", (name,))
    loaded = load(game)
    ref = f"minigames/{name}"
    expected = {"bad": [messages.e273_bad_file_name(ref)],
                "reserved": [messages.e273_reserved_file_name(ref)], "skip": []}[kind]
    assert loaded.errors == expected and reads == [] and loaded.names == []


@pytest.mark.parametrize("name, kind", BAD_NAMES[:4] + [
    pytest.param("x\n.py", "bad", marks=SLOW), pytest.param(".x.py", "skip", marks=SLOW)])
def test_bad_names_inside_a_package(game, load, reads, monkeypatch, name, kind):
    write(game, "minigames/pkg/__init__.py", plugin("pkg"))
    _offer(monkeypatch, "minigames/pkg", (name,))
    loaded = load(game)
    if kind == "skip":
        assert loaded.result.ok and loaded.names == ["pkg"]
        assert reads == ["minigames/pkg/__init__.py"]
    else:
        assert loaded.names == [] and reads == []
        assert loaded.errors == [messages.e273_reserved_file_name(f"minigames/pkg/{name}")
                                 if kind == "reserved"
                                 else messages.e273_bad_file_name(f"minigames/pkg/{name}")]


def test_init_is_the_only_underscore_name_read_in_a_package(game, load, reads):
    write(game, "minigames/pkg/__init__.py", plugin("pkg"))
    write(game, "minigames/pkg/_private.py", "raise SystemExit\n")
    write(game, "minigames/pkg/__pycache__/x.py", "raise SystemExit\n")
    write(game, "minigames/pkg/.hidden.py", "raise SystemExit\n")
    loaded = load(game)
    assert loaded.names == ["pkg"] and reads == ["minigames/pkg/__init__.py"]


# --- AC-F23-48: group C, the import system never reaches the disk ------------------------------

@pytest.fixture
def opens(monkeypatch):
    seen: list[str] = []
    real_open, real_code = builtins.open, io.open_code

    def spy_open(file, *args, **kwargs):
        seen.append(os.fspath(file) if isinstance(file, (str, os.PathLike)) else repr(file))
        return real_open(file, *args, **kwargs)

    def spy_code(path):
        seen.append(os.fspath(path))
        return real_code(path)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open_code", spy_code)
    return seen


def test_planted_vn_minigames_never_imports(game, load, tmp_path, monkeypatch):
    for where in ("cwd", "on_path"):
        write(tmp_path / where, "_vn_minigames/__init__.py", "import sys\nsys._vn_planted = 1\n")
        write(tmp_path / where, "_vn_minigames/evil.py", "import sys\nsys._vn_planted = 1\n")
    monkeypatch.chdir(tmp_path / "cwd")
    sys.path.insert(0, str(tmp_path / "on_path"))
    sys.path.insert(0, "")
    write(game, "minigames/a.py", "try:\n    import _vn_minigames.evil\nexcept "
          "ModuleNotFoundError:\n    MISSING = True\n" + plugin("ay"))
    try:
        loaded = load(game)
        assert loaded.result.ok and sys.modules["_vn_minigames.a"].MISSING is True
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("_vn_minigames.evil")
        assert not hasattr(sys, "_vn_planted")
    finally:
        sys.__dict__.pop("_vn_planted", None)


def test_only_the_py_text_runs_beside_bytecode_and_extensions(game, load, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    write(game, "minigames/c/__init__.py", "from . import helper\n" + plugin("sea"))
    write(game, "minigames/c/helper.py", "VALUE = 'py'\n")
    for name in ("helper.pyd", "helper.cpython-312.so", "helper.pyc",
                 "__pycache__/helper.cpython-312.pyc"):
        write(game, f"minigames/c/{name}", b"\x00garbage")
    loaded = load(game)                                       # tree unchanged: no .pyc
    assert loaded.result.ok
    helper = sys.modules["_vn_minigames.c.helper"]
    assert helper.VALUE == "py" and helper.__spec__.origin == "<minigames/c/helper.py>"


def test_import_system_shape(game, load):
    write(game, "minigames/a.py", "import sys\nROOT = sys.modules['_vn_minigames']\n"
          "FIRST = sys.meta_path[0]\n" + plugin("ay"))
    write(game, "minigames/c/__init__.py", plugin("sea"))
    modules_before = set(sys.modules)
    loaded = load(game)
    a = sys.modules["_vn_minigames.a"]
    assert a.FIRST is loaded.job.finder and a.ROOT.__path__ == []
    for name in ("_vn_minigames.a", "_vn_minigames.c"):
        spec = sys.modules[name].__spec__
        assert spec.origin == f"<minigames/{name.rsplit('.', 1)[1]}{'.py' if name.endswith('a') else '/__init__.py'}>"
        assert spec.cached is None and spec.has_location is False
        assert not hasattr(sys.modules[name], "__file__")
    assert sys.modules["_vn_minigames.c"].__path__ == []
    assert sys.modules["_vn_minigames.c"].__spec__.submodule_search_locations == []
    assert {n for n in set(sys.modules) - modules_before if not n.startswith("engine.")} == \
        {"_vn_minigames", "_vn_minigames.a", "_vn_minigames.c"}


def test_traceback_lines_come_from_the_text_read_once(game, load, opens):
    write(game, "minigames/boom.py", "def go():\n    raise ValueError('boom')\ngo()\n")
    loaded = load(game)
    assert len([p for p in opens if "minigames" in p.replace("\\", "/")]) == 1   # one read
    logged = [r.exc_text for r in loaded.records if r.exc_text]
    assert len(logged) == 1 and "    raise ValueError('boom')" in logged[0]
    opens.clear()
    source = loaded.job.finder._sources["_vn_minigames.boom"]
    with pytest.raises(ValueError) as caught:
        exec(compile(source.text, source.origin, "exec", dont_inherit=True), {})
    text = "".join(traceback.format_exception(caught.value))
    assert '<minigames/boom.py>", line 2, in go' in text
    assert "    raise ValueError('boom')" in text                # from the seeded linecache
    assert [p for p in opens if "minigames" in p.replace("\\", "/")] == []


def test_a_coding_cookie_changes_nothing(game, load):
    write(game, "minigames/cookie.py",
          "# -*- coding: unicode_escape -*-\n"
          "X = 1  #\\nimport sys; sys._vn_cookie = 1\n" + plugin("cookie"))
    try:
        loaded = load(game)
        assert loaded.result.ok and not hasattr(sys, "_vn_cookie")
    finally:
        sys.__dict__.pop("_vn_cookie", None)


def test_an_unknown_name_under_the_prefix_asks_no_other_finder(game, load):
    write(game, "minigames/a.py", plugin("ay"))
    load(game)
    asked: list[str] = []

    class Spy:
        @staticmethod
        def find_spec(name, path=None, target=None):
            asked.append(name)
            return None

    sys.meta_path.insert(1, Spy)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("_vn_minigames.nosuch")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("_vn_minigames.a.deeper")
    assert asked == []


def test_a_second_load_replaces_the_first(game, load):
    write(game, "minigames/a.py", plugin("ay"))
    first = load(game)
    (game / "minigames" / "a.py").unlink()
    write(game, "minigames/b.py", plugin("bee"))
    second = load(game)
    assert second.names == ["bee"] and "_vn_minigames.a" not in sys.modules
    assert first.job.finder not in sys.meta_path


# --- AC-F23-49: group D, bounds --------------------------------------------------------------

def test_too_many_units(game, load, monkeypatch, reads):
    monkeypatch.setattr(loader, "MAX_UNITS", 3)
    for i in range(4):
        write(game, f"minigames/u{i}.py", plugin(f"u{i}"))
    loaded = load(game)
    assert loaded.errors == [messages.E273_BOUND] and reads == [] and loaded.names == []
    (game / "minigames" / "u3.py").unlink()
    assert load(game).names == ["u0", "u1", "u2"]              # at the bound: loads


@pytest.mark.parametrize("size, ok", [(300, True), (301, False)])
def test_file_size_bound(game, load, monkeypatch, size, ok):
    monkeypatch.setattr(loader, "MAX_FILE_BYTES", 300)
    write(game, "minigames/a.py", plugin("ay"))
    write(game, "minigames/b.py", b"#" * (size - 1) + b"\n")
    write(game, "minigames/c.py", plugin("sea"))
    loaded = load(game)
    if ok:
        assert loaded.result.ok
    else:
        assert loaded.errors == [messages.E273_BOUND] and loaded.names == ["ay"]


@SLOW
def test_real_file_size_bound(game, load):
    write(game, "minigames/b.py", b"#" * (1 << 20) + b"\n")
    assert load(game).errors == [messages.E273_BOUND]


@SLOW
def test_total_size_bound(game, load, monkeypatch):
    monkeypatch.setattr(loader, "MAX_TOTAL_BYTES", 450)    # each file is about 200
    for name in "abc":
        write(game, f"minigames/{name}.py", plugin(name) + "#" * 40 + "\n")
    loaded = load(game)
    assert loaded.errors == [messages.E273_BOUND] and len(loaded.names) == 2


@pytest.mark.parametrize("files, ok", [(4, True), pytest.param(5, False, marks=SLOW)])
def test_package_file_bound(game, load, monkeypatch, files, ok):
    monkeypatch.setattr(loader, "MAX_PACKAGE_FILES", 4)
    write(game, "minigames/pkg/__init__.py", plugin("pkg"))
    for i in range(files - 1):
        write(game, f"minigames/pkg/m{i}.py", "X = 1\n")
    loaded = load(game)
    assert loaded.result.ok is ok
    if not ok:
        assert loaded.errors == [messages.e273_bound_package("minigames/pkg/")]


@pytest.mark.parametrize("depth, ok", [(3, True), (4, False)])
def test_package_depth_bound(game, load, depth, ok):
    folder = "minigames/pkg"
    write(game, f"{folder}/__init__.py", plugin("pkg"))
    for level in range(2, depth + 1):
        folder += f"/d{level}"
        write(game, f"{folder}/__init__.py", "X = 1\n")
    loaded = load(game)
    assert loaded.result.ok is ok
    if not ok:
        assert loaded.errors == [messages.e273_bound_package("minigames/pkg/")]


def test_registration_bound(game, load, monkeypatch):
    monkeypatch.setattr("engine.minigames.registry.MAX_REGISTRATIONS", 3)
    write(game, "minigames/a.py", plugin("a1") + plugin("a2").split("\n", 1)[1])
    write(game, "minigames/b.py", plugin("b1") + plugin("b2").split("\n", 1)[1])
    write(game, "minigames/c.py", plugin("c1"))
    loaded = load(game)
    assert loaded.errors == [messages.E273_BOUND_REGISTRATIONS]
    assert loaded.names == ["a1", "a2"]


@pytest.mark.parametrize("data", [b"X = '\xe9'\n", pytest.param(
    "X = 1\n".encode("utf-16"), marks=SLOW)], ids=["latin1", "utf16"])
def test_not_utf8_encodings(game, load, data):
    write(game, "minigames/x.py", data)
    assert load(game).errors == [messages.e273_not_utf8("minigames/x.py")]


def test_a_utf8_bom_loads(game, load):
    write(game, "minigames/x.py", b"\xef\xbb\xbf" + plugin("x").encode("utf-8"))
    assert load(game).names == ["x"]


# --- AC-F23-58: the loaded plugin set is logged ------------------------------------------------

@pytest.mark.parametrize("dev", [True, False])
def test_one_info_record_per_loaded_unit(game, load, dev):
    source = plugin("ay").encode("utf-8")
    data = source + b"#" * (1234 - len(source) - 1) + b"\n"
    write(game, "minigames/a.py", data)
    write(game, "minigames/c/__init__.py", plugin("sea"))
    loaded = load(game, dev=dev)
    infos = loaded.infos()
    digest = hashlib.sha256(data).hexdigest()[:12]
    assert len(infos) == 2
    assert infos[0] == messages.info_loaded("minigames/a.py", 1234, digest, "1.0")
    assert "minigames/a.py" in infos[0] and "1,234 bytes" in infos[0] and digest in infos[0]
    assert infos[1].startswith("Loaded minigame plugin minigames/c/ (")
    assert all(r.name == "vn.plugin" for r in loaded.records)


# --- AC-F23-59: hidden characters are reported -------------------------------------------------

def test_w165_names_the_first_bidi_line(game, load):
    lines = ["# x\n"] * 40
    lines[11] = "# ‮ reversed\n"
    lines[29] = "# ⁦ isolate\n"
    write(game, "minigames/x.py", "".join(lines) + plugin("x"))
    loaded = load(game)
    assert loaded.names == ["x"]
    assert loaded.warnings("W165") == [messages.w165_bidi("minigames/x.py", 12)]
    assert load(game, dev=False).warnings() == []


# --- SEC-F23-11: the loader captures the main thread ---------------------------------------

def test_registry_records_the_loading_thread(game, load):
    assert load(game).result.registry.main_thread == threading.get_ident()


# --- AC-F23-56: only the folder listing chooses code -------------------------------------------

def test_only_the_folder_listing_chooses_code(game, tmp_path, reads, monkeypatch):
    from types import SimpleNamespace

    from engine.app import loading
    from engine.core.config import load_config
    from engine.core.startvalues import StartOptions
    from engine.script import minigame
    from engine.script.loader import LoadOptions, load_story
    from engine.script.statements import scoped_registry

    assert list(inspect.signature(loader.PluginLoadJob).parameters) == [
        "paths", "guard", "dev", "log"]
    evil = "minigames/evil.py"

    def marking(name: str) -> str:
        return f"import pathlib\npathlib.Path({str(tmp_path / name)!r}).write_text('ran')\n"

    write(game, "minigames/ok.py", marking("ok-ran") + plugin("ok"))
    write(game, "evil.py", marking("evil-ran") + plugin("evil"))          # not in the folder
    write(tmp_path, "x.py", marking("x-ran") + plugin("x"))               # ../x.py
    write(game, "config.toml", f'[game]\ntitle = "{evil}"\nversion = "0.1.0"\n')
    write(game, "saves/1-1.save", f'{{"minigame": "{evil}", "file": "../x.py"}}')
    write(game, "persistent/persistent.json", f'{{"plugin": "{evil}"}}')
    write(game, "script/main.vns", f'default note = ""\nlabel start:\n    "{evil} ../x.py"\n'
                                   "    minigame ok\n    minigame evil\n    return\n")
    monkeypatch.setenv("VN_MINIGAMES", evil)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    listed: list[str] = []
    for method in ("real_dir", "list_real"):
        real = getattr(GamePaths, method)
        monkeypatch.setattr(GamePaths, method, lambda self, ref, _real=real:
                            (listed.append(ref), _real(self, ref))[1])
    paths = GamePaths.for_game(game)
    with scoped_registry():
        minigame.register_words()
        # Read-only tools: LoadOptions.minigames None runs no plugin code (SEC-F23-04 (b)).
        assert load_story(paths, LoadOptions()).program is not None
        assert not (tmp_path / "ok-ran").exists() and listed == []
        assert not any(n.startswith(loader.PREFIX) for n in sys.modules)

        # A launch: the plugin phase, then F02's load with the signatures.
        shown = []
        app = SimpleNamespace(config=load_config(paths).config, paths=paths, dev=True,
                              start=StartOptions("start", (("note", evil),)), loading=False,
                              program=None, minigames=None, no_persistent=True,
                              show_fatal_error=lambda e, **_: shown.append(e))
        screen = loading.story_load_screen(app, paths, on_ready=lambda _: [])
        screen.on_enter()
        for _ in range(50):
            screen.update(0.016, is_top=True)
            if screen.finished:
                break
    assert [r for r in reads if r.endswith(".py")] == ["minigames/ok.py"]
    assert set(listed) == {"minigames"}
    assert (tmp_path / "ok-ran").exists()
    assert not (tmp_path / "evil-ran").exists() and not (tmp_path / "x-ran").exists()
    assert app.minigames.names() == ("ok",) and list(screen.minigames) == ["ok"]
    # The signatures reached the script checks: only the unregistered name is E270.
    assert [[(e.code, e.line) for e in group.errors] for group in shown] == [[("E270", 5)]]
