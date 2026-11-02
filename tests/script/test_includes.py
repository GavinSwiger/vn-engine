"""Discovery, includes, and story limits through ``load_story`` (F02 checklist step 6;
``04-technical.md`` §7.1, §7.6.1, §7.6.2).

AC-F02-01, 02, 03 (abuse parts; each message row also runs as a ``cases.toml`` case), 04, 05,
06 (rows beyond ``cases.toml``), 07, 41, 51, 52, and the loader part of AC-F02-35. Parts that
need the whole-game checks (E25, E26, E43, E70) skip until ``engine/script/checks.py``
exists (checklist step 7).
"""

import importlib.util
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from engine.core.constants import MB
from engine.core.errors import AssetUnreadable
from engine.core.paths import GamePaths
from engine.script import limits
from engine.script.diagnostics import ScriptErrorGroup
from engine.script.loader import LoadResult, is_skipped_name, load_story
from engine.script.messages import format_message
from tests.script.conftest import load_gen_corpus, write_tree
from tests.script.helpers import FIXTURES, template

INCLUDES = FIXTURES / "includes"
CHECKS_BUILT = importlib.util.find_spec("engine.script.checks") is not None
needs_checks = pytest.mark.skipif(not CHECKS_BUILT,
                                  reason="needs the whole-game checks (checklist step 7)")


# --- Helpers -----------------------------------------------------------------------------

def copy_game(fixture: Path, tmp_path: Path) -> Path:
    """A game root under ``tmp_path`` whose ``script/`` is a copy of ``fixture``."""
    root = tmp_path / "game"
    shutil.copytree(fixture, root / "script")
    return root


def load(root: Path, paths_type: type[GamePaths] = GamePaths) -> LoadResult:
    return load_story(paths_type(root.resolve()))


def messages(result: LoadResult) -> list[str]:
    return [error.format() for error in result.errors]


def codes(result: LoadResult) -> list[str]:
    return [error.code for error in result.errors]


def warning_texts(result: LoadResult, code: str | None = None) -> list[str]:
    return [w.format() for w in result.warnings if code is None or w.code == code]


def loads(result: LoadResult) -> None:
    """06 §0.5 "loads clean"."""
    assert result.program is not None, messages(result)
    assert result.errors == () and result.error_count == 0
    assert result.warnings == (), warning_texts(result)
    assert not result.checks_skipped and not result.no_story


def link(path: Path, target: Path, *, folder: bool) -> str:
    """A symbolic link, or on Windows a junction for a folder when links aren't permitted.
    Returns "symlink" or "junction"; skips where neither can be made (06 §0.3)."""
    try:
        os.symlink(target, path, target_is_directory=folder)
        return "symlink"
    except (OSError, NotImplementedError) as exc:
        reason = exc
    if folder and os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(path))
        return "junction"
    pytest.skip(f"symbolic links are not permitted here: {reason}")


def outside_of(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    write_tree(outside, {"secret.vns": "label leaked:\n    return\n",
                         "taxes_2025.vns": "label taxes:\n    return\n",
                         "m.vns": "label start:\n    return\n"})
    return outside.resolve()


def all_output(result: LoadResult) -> str:
    return "\n".join(messages(result) + warning_texts(result)
                     + [ScriptErrorGroup.from_result(result).format()])


def inside_script(events: list[tuple[str, str]], root: Path) -> None:
    """Abuse conditions Y: no file opened (and no folder listed) outside ``<root>``, and
    no file opened outside ``<root>/script``."""
    script = (root / "script").resolve()
    for event, path in events:
        real = Path(os.path.abspath(path))
        if event == "open":
            assert real.is_relative_to(script) or real == script, (event, path)
        else:
            assert real.is_relative_to(root.resolve()), (event, path)


# --- AC-F02-01 ---------------------------------------------------------------------------

def test_ac01_story_is_main_and_its_includes(tmp_path):
    result = load(copy_game(INCLUDES / "basic", tmp_path))
    assert result.program is not None and result.errors == (), messages(result)
    assert [f.ref for f in result.program.files] == [
        "script/main.vns", "script/a.vns", "script/routes/b.vns", "script/routes/x.vns"]
    assert set(result.program.labels) == {"start", "a_scene", "b_scene"}
    assert [w.code for w in result.warnings] == ["W02"]
    assert warning_texts(result) == [
        'script/stray.vns is not included, so it is not part of the game. Add include '
        '"stray.vns" to a file that is.']


def test_ac01_paths_are_relative_to_the_script_folder(tmp_path):
    root = copy_game(INCLUDES / "basic", tmp_path)
    (root / "script" / "routes" / "x.vns").write_text('include "b.vns"\n', encoding="utf-8")
    result = load(root)
    assert codes(result) == ["E91"]
    assert messages(result)[0].startswith(
        'script/routes/x.vns, line 1: can\'t include "b.vns" because script/b.vns doesn\'t '
        "exist.")


# --- AC-F02-02 ---------------------------------------------------------------------------

def test_ac02_each_file_loads_once(tmp_path):
    result = load(copy_game(INCLUDES / "cycle", tmp_path))
    loads(result)
    assert [f.ref for f in result.program.files] == [
        "script/main.vns", "script/a.vns", "script/b.vns"]


def _program_shape(result: LoadResult) -> dict:
    """Labels, statements, and sids, ignoring positions and file refs."""
    program = result.program
    assert program is not None, messages(result)
    shape = {}
    for name, label in program.labels.items():
        shape[name] = [(type(s).__name__, s.sid, s.identity_key())
                       for s in program.statements_in(name)]
    return shape


def test_ac02_include_order_does_not_matter(tmp_path):
    one = load(copy_game(INCLUDES / "order1", tmp_path / "1"))
    two = load(copy_game(INCLUDES / "order2", tmp_path / "2"))
    loads(one)
    loads(two)
    assert _program_shape(one) == _program_shape(two)
    assert {d.name for d in one.program.defines} == {d.name for d in two.program.defines}


def test_ac02_same_mistakes_give_the_same_messages(tmp_path):
    results = []
    for name in ("order1", "order2"):
        root = copy_game(INCLUDES / name, tmp_path / name)
        script = root / "script"
        for file, old, new in (("main.vns", '    hana "Hi."', '    hana “Hi.”'),
                               ("a.vns", '    daichi "From a."', "    daichi"),
                               ("b.vns", '    hana "From b."', '    hana "From b." x')):
            text = (script / file).read_text(encoding="utf-8")
            assert old in text
            (script / file).write_text(text.replace(old, new), encoding="utf-8")
        results.append(load(root))
    one, two = results
    assert one.error_count == two.error_count == 3, messages(one)
    assert set(messages(one)) == set(messages(two))


# --- AC-F02-03 (abuse A1, A2, and the E99 rule) -----------------------------------------

@pytest.mark.parametrize("path", ["../secret.vns", "/etc/x.vns", "C:/x.vns", "//srv/s/x.vns",
                                  "routes\\x.vns", "con.vns", "a.vns.", "x/" * 550 + "x.vns",
                                  "routes/．．/x.vns", "routes∕..∕x.vns"])
def test_ac03_escaping_includes_are_never_read(tmp_path, monkeypatch, opened, path):
    outside_of(tmp_path)
    root = tmp_path / "game"
    write_tree(root / "script", {"main.vns": template(T=f'include "{path}"')})
    reads = []
    real_read = GamePaths.read_file

    def spy(self, ref, *, max_bytes):
        reads.append(ref)
        return real_read(self, ref, max_bytes=max_bytes)

    monkeypatch.setattr(GamePaths, "read_file", spy)
    with opened() as events:
        result = load(root)
    assert reads == ["script/main.vns"]
    inside_script(events, root)
    assert codes(result) == (["E91"] if "．" in path or "∕" in path else ["E92"])
    assert result.checks_skipped
    message = messages(result)[0]
    assert message.startswith('script/main.vns, line 9: can\'t include "')
    quoted = message.split('"')[1]
    assert len(quoted) <= 120


@pytest.mark.parametrize("row,skipped", [
    ('S: include "a.vns"', False),           # E90
    ("T: include chapter2.vns", False),      # E95
    ('T: include "a.vns" "b.vns"', False),   # E96
    ('T: include "nothing.vns"', True),      # E91
    ('T: include "notes.txt"', True),        # E93
    ('T: include "routes"', True),           # E94
])
def test_ac03_which_include_errors_skip_the_checks(game, row, skipped):
    slot, text = row.split(": ", 1)
    main = template(S=text) if slot == "S" else template(T=text)
    result = load_story(game({"main.vns": main, "a.vns": "label a:\n    return\n",
                              "routes": None}))
    assert result.error_count == 1, messages(result)
    assert result.checks_skipped is skipped
    assert result.program is None


# --- AC-F02-04 ---------------------------------------------------------------------------

def test_ac04_a3_file_link_outside(tmp_path, opened):
    outside = outside_of(tmp_path)
    root = tmp_path / "game"
    write_tree(root / "script", {"main.vns": template(T='include "x.vns"')})
    link(root / "script" / "x.vns", outside / "secret.vns", folder=False)
    with opened() as events:
        result = load(root)
    inside_script(events, root)
    assert codes(result) == ["E92"]
    assert messages(result)[0].endswith(
        'can\'t include "x.vns": paths must stay inside the script folder and use forward '
        "slashes, e.g. routes/hana.vns.")
    text = all_output(result)
    for word in ("leaked", "secret", str(outside), "outside"):
        assert word not in text


def test_ac04_a3_folder_link_outside(tmp_path, opened):
    outside = outside_of(tmp_path)
    root = tmp_path / "game"
    write_tree(root / "script", {"main.vns": template(T='include "ext/secret.vns"')})
    link(root / "script" / "ext", outside, folder=True)
    with opened() as events:
        result = load(root)
    inside_script(events, root)
    assert not any(Path(os.path.abspath(p)).is_relative_to(outside) for _, p in events)
    assert codes(result) == ["E92"]
    text = all_output(result)
    assert "taxes_2025" not in text and "leaked" not in text and str(outside) not in text


def test_ac04_a4_in_folder_links_load_a_file_once(tmp_path):
    root = tmp_path / "game"
    write_tree(root / "script", {
        "main.vns": template(T='include "l1/b.vns"⏎include "l2/b.vns"'),
        "routes/b.vns": "label routes_b:\n    return\n"})
    link(root / "script" / "l1", root / "script" / "routes", folder=True)
    link(root / "script" / "l2", root / "script" / "routes", folder=True)
    result = load(root)
    assert result.program is not None, messages(result)
    assert [f.ref for f in result.program.files] == ["script/main.vns", "script/l1/b.vns"]
    assert result.warnings == ()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX only")
def test_ac04_a6_fifo_is_e97_without_blocking(tmp_path):
    root = tmp_path / "game"
    write_tree(root / "script", {"main.vns": template(T='include "f.vns"')})
    os.mkfifo(root / "script" / "f.vns")
    start = time.monotonic()
    result = load(root)
    assert time.monotonic() - start < 2
    assert codes(result) == ["E97"]


def test_ac04_a7_link_loops_end(tmp_path):
    root = tmp_path / "game"
    write_tree(root / "script", {"main.vns": template(), "x.vns": "# x\n"})
    link(root / "script" / "loop", root / "script", folder=True)
    link(root / "script" / "up", root, folder=True)
    start = time.monotonic()
    result = load(root)
    assert time.monotonic() - start < 10
    assert result.errors == ()
    assert 1 <= len(result.warnings) <= 21


def test_ac04_a8_hard_links_are_distinct_files(tmp_path):
    root = tmp_path / "game"
    write_tree(root / "script", {
        "main.vns": template(T='include "h1.vns"⏎include "h2.vns"'),
        "h1.vns": "label dup:\n    return\n"})
    try:
        os.link(root / "script" / "h1.vns", root / "script" / "h2.vns")
    except OSError as exc:
        pytest.skip(f"hard links are not permitted here: {exc}")
    result = load(root)
    if CHECKS_BUILT:
        assert codes(result) == ["E25"]
    else:
        assert result.program is not None
        assert [f.ref for f in result.program.files][1:] == ["script/h1.vns", "script/h2.vns"]


# --- AC-F02-05 ---------------------------------------------------------------------------

def test_ac05_link_into_saves_is_e92(tmp_path, opened):
    root = tmp_path / "game"
    write_tree(root, {"script/main.vns": template(T='include "s/x.vns"'),
                      "saves/x.vns": "label from_saves:\n    return\n"})
    link(root / "script" / "s", root / "saves", folder=True)
    with opened() as events:
        result = load(root)
    assert codes(result) == ["E92"]
    saves = (root / "saves").resolve()
    assert not any(e == "open" and Path(os.path.abspath(p)).is_relative_to(saves)
                   for e, p in events)
    assert "from_saves" not in all_output(result)
    assert result.warnings == ()          # script/s/x.vns is outside script/: no W02


def test_ac05_script_folder_overlapping_a_write_root(tmp_path, opened):
    root = tmp_path / "game"
    write_tree(root, {"characters/main.vns": template()})
    link(root / "script", root / "characters", folder=True)
    with opened() as events:
        result = load(root)
    assert result.program is None
    assert result.error_count == 1 and codes(result) == ["E08e"]
    assert result.checks_skipped is True
    characters = (root / "characters").resolve()
    assert not any(e == "open" and Path(os.path.abspath(p)).is_relative_to(characters)
                   for e, p in events)


def test_ac05_write_root_names_come_from_constants():
    from engine.core import constants
    from engine.script import loader
    assert loader.WRITE_ROOT_NAMES == (constants.LOGS_DIRNAME, *constants.SAVE_DIRNAMES,
                                       *constants.RESERVED_DIRNAMES)
    source = Path(loader.__file__).read_text(encoding="utf-8")
    for name in ('"saves"', '"persistent"', '"characters"', '"logs"'):
        assert name not in source


# --- AC-F02-06 (rows beyond cases.toml) --------------------------------------------------

def test_ac06_script_folder_in_the_wrong_case_is_no_story(tmp_path):
    root = tmp_path / "game"
    write_tree(root / "Script", {"main.vns": template()})
    result = load(root)
    assert result.no_story and result.program is None and result.errors == ()
    assert warning_texts(result) == ["No story found: script/main.vns doesn't exist."]


@pytest.mark.parametrize("files,code,skipped", [
    ({"Main.vns": "# x\n"}, "E08", False),
    ({"a.vns": "# x\n", "b.vns": "# x\n"}, "E09", False),
    ({"main.vns": None}, "E08c", True),
])
def test_ac06_discovery_errors_stop_the_load(game, files, code, skipped):
    result = load_story(game(files))
    assert codes(result) == [code] and result.error_count == 1
    assert result.checks_skipped is skipped
    assert result.program is None and not result.no_story
    assert result.warnings == ()


def test_ac06_e09_with_two_files_has_no_count(game):
    result = load_story(game({"intro.vns": "# x\n", "chapter1.vns": "# x\n"}))
    assert result.errors[0].message == (
        "script/main.vns doesn't exist, but script/ has other .vns files: chapter1.vns and "
        "intro.vns. Rename the file where your story begins to main.vns.")


def test_ac06_unreadable_main_is_e08b(game):
    class Locked(GamePaths):
        def read_file(self, ref, *, max_bytes):
            raise AssetUnreadable(ref)

    paths = game({"main.vns": template()})
    result = load_story(Locked(paths.root))
    assert codes(result) == ["E08b"] and result.checks_skipped


@needs_checks
def test_ac06_empty_main_is_e26(game):
    result = load_story(game({"main.vns": b""}))
    assert codes(result) == ["E26"] and not result.no_story


# --- AC-F02-07 ---------------------------------------------------------------------------

SKIPPED = ["chapter1 - Copy.vns", "old_ch2.vns", "ch3.backup2.vns", "Draft.vns", "COPY2.vns",
           "chapter1~.vns"]
WARNED = ["golden.vns", "scaffold.vns", "copyright.vns", "drafts.vns", "bold.vns",
          "routes/x.vns"]


def test_ac07_backup_names():
    for name in SKIPPED:
        assert is_skipped_name("script/" + name), name
    for name in WARNED:
        assert not is_skipped_name("script/" + name), name


def test_ac07_files_left_out_are_warned_once(game):
    files = {"main.vns": template()} | {name: "# x\n" for name in SKIPPED + WARNED}
    result = load_story(game(files))
    assert result.program is not None and result.errors == ()
    texts = warning_texts(result)
    assert codes(result) == [] and len(texts) == len(WARNED)
    for name in WARNED:
        assert (f"script/{name} is not included, so it is not part of the game. "
                f'Add include "{name}" to a file that is.') in texts
    assert texts == sorted(texts)


def test_ac07_twenty_then_a_summary(game):
    files = {"main.vns": template()} | {f"w{i:02}.vns": "# x\n" for i in range(1, 26)}
    result = load_story(game(files))
    texts = warning_texts(result)
    assert len(texts) == 21
    assert texts[0].startswith("script/w01.vns ") and texts[19].startswith("script/w20.vns ")
    assert texts[20] == "…and 5 more .vns files are not included."


def test_ac07_w02_is_logged_also_with_errors(game):
    result = load_story(game({"main.vns": template(S="hana"), "golden.vns": "# x\n"}))
    assert result.error_count == 1 and result.errors[0].code in ("E30a", "E30b", "E71")
    assert [w.code for w in result.warnings] == ["W02"]


def test_ac07_walk_limit_is_w02b(game, monkeypatch):
    monkeypatch.setattr(limits, "SCRIPT_WALK_MAX_ENTRIES", 10)
    files = {"main.vns": template()} | {f"n{i:02}.txt": "x" for i in range(11)}
    result = load_story(game(files))
    assert result.program is not None
    assert warning_texts(result, "W02b") == [
        "script/ holds more than 10,000 files and folders, so only the first ones were "
        "checked for files that aren't included."]


@pytest.mark.slow
def test_ac07_walk_limit_real_size(game):
    files = {"main.vns": template()} | {f"n{i:05}.txt": "" for i in range(10_000)}
    result = load_story(game(files))
    assert result.program is not None
    assert [w.code for w in result.warnings] == ["W02b"]


# --- AC-F02-41 ---------------------------------------------------------------------------

def test_ac41_checks_skipped_after_an_unreadable_file(game):
    class Locked(GamePaths):
        def read_file(self, ref, *, max_bytes):
            if ref == "script/locked.vns":
                raise AssetUnreadable(ref)
            return super().read_file(ref, max_bytes=max_bytes)

    main = template(S='jump nowhere⏎[4]kaito "Hi"', T='include "locked.vns"',
                    replace={3: "label begin:"})
    paths = game({"main.vns": main, "locked.vns": "label locked:\n    return\n"})
    result = load_story(Locked(paths.root))
    assert codes(result) == ["E97"]
    assert result.checks_skipped is True and result.error_count == 1
    group = ScriptErrorGroup.from_result(result).format()
    assert group.startswith("The script has 1 problem:")
    assert group.endswith(format_message("E99"))


def test_ac41_e01a_does_not_skip_the_checks(game):
    result = load_story(game({"main.vns": template(T='include "c.vns"'),
                              "c.vns": b"label c:\n    return\n# caf\xe9\n"}))
    assert codes(result) == ["E01a"] and not result.checks_skipped


# --- AC-F02-51 ---------------------------------------------------------------------------

def _main_of_size(size: int) -> bytes:
    text = template().encode("utf-8")
    line = b"# padding comment line\n"
    count, extra = divmod(size - len(text), len(line))
    return text + line * count + b"#" * extra


@pytest.mark.slow
def test_ac51_one_file_16_mib(game, tmp_path):
    assert load_story(game({"main.vns": _main_of_size(16 * MB)})).program is not None
    result = load_story(game({"main.vns": _main_of_size(16 * MB + 1)}))
    assert codes(result) == ["E05"] and result.checks_skipped
    assert result.errors[0].format() == (
        "script/main.vns is larger than 16 MB. Split it into several files and include them.")


@pytest.mark.parametrize("extra,code", [(0, None), (1, "E05b")])
def test_ac51_total_size(game, monkeypatch, extra, code):
    monkeypatch.setattr(limits, "SCRIPT_TOTAL_MAX_BYTES", MB)
    main = template(T='include "big.vns"').encode("utf-8")
    line = b"# padding\n"
    count, rest = divmod(MB - len(main) + extra, len(line))
    result = load_story(game({"main.vns": main, "big.vns": line * count + b"#" * rest}))
    if code is None:
        assert result.program is not None and result.errors == ()
        return
    assert codes(result) == ["E05b"] and result.checks_skipped and result.error_count == 1
    assert result.errors[0].format() == (
        "The story's files add up to more than 256 MB, which is the limit. "
        "Remove unneeded includes.")


def _hostile(tmp_path: Path, *args: str) -> Path:
    out = tmp_path / "corpus"
    load_gen_corpus().main(["--hostile", *args, "--out", str(out)])
    return out


@pytest.mark.parametrize("n,code", [(19, None), (20, "E06")])
def test_ac51_file_count_patched(tmp_path, monkeypatch, n, code):
    monkeypatch.setattr(limits, "SCRIPT_MAX_FILES", 20)
    result = load(_hostile(tmp_path, "many-files", "--n", str(n)))
    if code is None:
        assert result.program is not None and len(result.program.files) == 20
        return
    assert codes(result) == ["E06"] and result.checks_skipped and result.error_count == 1
    assert "1,000" in result.errors[0].message     # the real limit, never the patched one


@pytest.mark.slow
@pytest.mark.parametrize("n,code", [(999, None), (1000, "E06")])
def test_ac51_file_count(tmp_path, n, code):
    result = load(_hostile(tmp_path, "many-files", "--n", str(n)))
    if code is None:
        assert result.program is not None and len(result.program.files) == 1000
        assert result.errors == ()
        return
    assert codes(result) == ["E06"] and result.checks_skipped and result.error_count == 1
    assert result.errors[0].format() == (
        "The story includes more than 1,000 .vns files, which is the limit. "
        "Combine some of them.")


@pytest.mark.parametrize("n,code", [(50, None), (51, "E07")])
def test_ac51_include_depth(tmp_path, n, code):
    result = load(_hostile(tmp_path, "chain", "--n", str(n)))
    if code is None:
        assert result.program is not None and len(result.program.files) == 51
        assert result.program.files[-1].depth == 50
        return
    assert codes(result) == ["E07"] and result.checks_skipped and result.error_count == 1
    assert result.errors[0].format() == (
        "The includes from script/main.vns to script/c/f51.vns chain more than 50 files, "
        "which is the limit. Include f51.vns from a file nearer main.vns.")


# --- AC-F02-52 ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.parametrize("last,code", [(40_000, None), (40_001, "E06d")])
def test_ac52_python_total(tmp_path, last, code):
    root = _hostile(tmp_path, "py-total", "--n", "41", "--last-chars", str(last))
    result = load(root)
    if code is None:
        assert result.program is not None, messages(result)
        return
    assert codes(result) == ["E06d"] and result.checks_skipped and result.error_count == 1


def test_ac52_piece_size_counts_the_stored_source():
    gen = load_gen_corpus()
    assert len(gen.py_piece(99_000)) == 99_000 and len(gen.py_piece(40_001)) == 40_001


@pytest.mark.parametrize("count,code", [(1000, None), (1001, "E06b")])
def test_ac52_statement_count(game, monkeypatch, count, code):
    monkeypatch.setattr(limits, "SCRIPT_MAX_STATEMENTS", 1000)
    main = "label start:\n" + '    "a"\n' * (count - 2) + "    return\n"
    result = load_story(game({"main.vns": main}))
    if code is None:
        assert result.program is not None and result.errors == ()
        assert result.program.stats.statements == count - 1      # the label isn't one
        return
    assert codes(result) == ["E06b"] and result.checks_skipped and result.error_count == 1
    text = result.errors[0].format()
    assert text == ("The story has more than 1,000,000 statements, which is the limit. "
                    "Remove unneeded includes.")
    assert "1,000 " not in text and "1000" not in text


@pytest.mark.parametrize("count,code", [(100, None), (101, "E06c")])
def test_ac52_python_piece_count(game, monkeypatch, count, code):
    monkeypatch.setattr(limits, "SCRIPT_MAX_PY_PIECES", 100)
    main = ("define x = 1\nlabel start:\n    if True:\n        \"a\"\n"
            + "    $ y = 1\n" * (count - 2) + "    return\n")
    result = load_story(game({"main.vns": main}))
    if code is None:
        assert result.program is not None and result.errors == ()
        return
    assert codes(result) == ["E06c"] and result.checks_skipped and result.error_count == 1
    assert result.errors[0].format() == (
        "The story has more than 250,000 pieces of Python ($ lines, conditions, define "
        "values), which is the limit. Combine repeated Python.")


def test_ac52_a_limit_stops_reading_mid_file(game, monkeypatch):
    monkeypatch.setattr(limits, "SCRIPT_MAX_STATEMENTS", 10)
    main = "label start:\n" + '    "a"\n' * 5000 + '    hana “x”\n' + "    return\n"
    result = load_story(game({"main.vns": main}))
    assert codes(result) == ["E06b"]      # the E50 at line 5,002 is never reached


# --- AC-F02-35 (loader part): compile() never opens a file outside script/ ---------------

def test_ac35_compile_attempts_stay_in_the_script_folder(tmp_path, opened):
    root = tmp_path / "game"
    write_tree(root / "script", {"main.vns": template(S="$ x = = 1")})
    with opened() as events:
        result = load(root)
    assert codes(result) == ["E80"]
    inside_script(events, root)
    attempts = [p for e, p in events if e == "open" and "<vns-" in p]
    script = str((root / "script").resolve())
    assert all(p.startswith(script) for p in attempts), attempts


def test_load_story_never_raises_on_odd_roots(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    (root / "script").write_text("not a folder", encoding="utf-8")
    result = load(root)
    assert result.no_story and result.errors == ()
    assert sys.getrecursionlimit() > 0
