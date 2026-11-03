"""F31 step 2: the whole-game checks for ``file`` lines (06 AC-F31-10; ``04`` §5.2).

Fixture ``checks/`` is ``tests/fixtures/F31/walk/`` copied to ``tmp_path/aiko/game`` with an
``include "more.vns"`` (06 §5); each row changes it. ``file`` registers at import since F31 s3;
the loads still run inside ``scoped_registry()`` with ``metafiles.register_words()`` (a repeat
changes nothing).
"""

import builtins
import io
import os
import shutil
from pathlib import Path

import pytest

from engine.core.errors import AssetUnreadable
from engine.core.paths import GamePaths
from engine.script import checks, metafiles
from engine.script.loader import LoadOptions, load_story
from engine.script.messages import format_message
from engine.script.statements import scoped_registry

WALK = Path(__file__).resolve().parents[1] / "fixtures" / "F31" / "walk"


class _Unreadable(GamePaths):
    """``read_file`` raises ``AssetUnreadable`` for ``script/more.vns``."""

    def read_file(self, ref, **kwargs):
        if ref == "script/more.vns":
            raise AssetUnreadable(ref)
        return super().read_file(ref, **kwargs)


def _game(tmp_path: Path, name: str) -> Path:
    game = tmp_path / name / "aiko" / "game"
    shutil.copytree(WALK, game)
    main = game / "script" / "main.vns"
    main.write_text('include "more.vns"\n' + main.read_text(encoding="utf-8"), "utf-8")
    (game / "script" / "more.vns").write_text("label more:\n    return\n", "utf-8")
    return game


def _edit(game: Path, old: str, new: str) -> None:
    main = game / "script" / "main.vns"
    text = main.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    main.write_text(text.replace(old, new), "utf-8")


def _load(game: Path, paths_type: type = GamePaths):
    with scoped_registry():
        metafiles.register_words()
        return load_story(paths_type(game.resolve()), LoadOptions(dev=False))


def _errors(result) -> list[tuple[str, int | None, str]]:
    return [(e.code, e.line, e.message) for e in result.errors]


def test_ac10_whole_game_checks_e312_e313_e314(tmp_path, monkeypatch):
    # The fixture loads clean, and loading stats files/hana.chr but never opens it.
    opened: list[str] = []
    sized: list[str] = []
    real_os_open, real_io_open = os.open, io.open
    real_read, real_size = GamePaths.read_file, GamePaths.file_size

    def spy_os_open(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return real_os_open(path, *args, **kwargs)

    def spy_io_open(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)):
            opened.append(os.fspath(file))
        return real_io_open(file, *args, **kwargs)

    def spy_read(self, ref, **kwargs):
        opened.append(ref)
        return real_read(self, ref, **kwargs)

    def spy_size(self, ref):
        sized.append(ref)
        return real_size(self, ref)

    game = _game(tmp_path, "clean")
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", spy_os_open)
        patch.setattr(io, "open", spy_io_open)
        patch.setattr(builtins, "open", spy_io_open)
        patch.setattr(GamePaths, "read_file", spy_read)
        patch.setattr(GamePaths, "file_size", spy_size)
        result = _load(game)
    assert _errors(result) == []
    assert result.program.meta_files == frozenset(("hana.chr", "read_me.txt", "gone.chr",
                                                   "answer.txt"))
    assert "script/main.vns" in opened and sized == ["files/hana.chr"]
    assert not [p for p in opened if "files" in Path(p).parts]

    # E312: no default (did-you-mean), a define, an engine name.
    target = '{{"\n    file exists "hana.chr" into hana_here'      # walk line 8
    for row, new, args in (("her", "hana_her", ("no_default", "hana_her", "hana_here")),
                           ("define", "hana", ("define", "hana")),
                           ("engine", "dice", ("engine", "dice"))):
        game = _game(tmp_path, f"e312-{row}")
        _edit(game, target, target.replace("hana_here", new))
        assert _errors(_load(game)) == [("E312", 9, format_message("E312", args))], row

    # E313 missing: no original, a folder, a link to outside/ (where links can be made).
    missing = [("E313", 7, format_message("E313", ("missing", "hana.chr")))]
    game = _game(tmp_path, "none")
    (game / "files" / "hana.chr").unlink()
    assert _errors(_load(game)) == missing
    game = _game(tmp_path, "folder")
    (game / "files" / "hana.chr").unlink()
    (game / "files" / "hana.chr").mkdir()
    assert _errors(_load(game)) == missing
    game = _game(tmp_path, "link")
    outside = tmp_path / "link" / "outside"
    outside.mkdir()
    (outside / "hana.chr").write_bytes(b"HANA")
    (game / "files" / "hana.chr").unlink()
    try:
        os.symlink(outside / "hana.chr", game / "files" / "hana.chr")
    except OSError:
        pass                                         # no symlink privilege (06 §0.3)
    else:
        assert _errors(_load(game)) == missing

    # E313 large past the cap (patched to 1,024); exactly at the cap loads.
    monkeypatch.setattr(checks, "META_ORIGINAL_MAX_BYTES", 1_024)
    game = _game(tmp_path, "large")
    (game / "files" / "hana.chr").write_bytes(b"x" * 1_025)
    assert _errors(_load(game)) == [
        ("E313", 7, format_message("E313", ("large", "hana.chr", 1_025, 1_024)))]
    (game / "files" / "hana.chr").write_bytes(b"x" * 1_024)
    assert _errors(_load(game)) == []
    monkeypatch.undo()

    # E314: 33 distinct names across two files names the 33rd, its file and line.
    game = _game(tmp_path, "e314")
    more = "label more:\n" + "".join(f'    file write "m{i}.txt" "x"\n' for i in range(1, 30))
    (game / "script" / "more.vns").write_text(more + "    return\n", "utf-8")
    _edit(game, '    "W0"\n', '    "W0"\n    call more\n')
    # Reading order: main.vns's 4 names, then more.vns's 29, so m29 is the 33rd.
    result = _load(game)
    assert _errors(result) == [
        ("E314", None, format_message("E314", (33, "m29.txt", "script/more.vns", 30)))]
    # 32 distinct names, each used 3 times, load.
    (game / "script" / "more.vns").write_text(
        more.replace('    file write "m29.txt" "x"\n', "")
        + "".join(f'    file delete "m{i}.txt"\n    file write "m{i}.txt" "y"\n'
                  for i in range(1, 29)) + "    return\n", "utf-8")
    assert _errors(_load(game)) == []

    # An include that can't be read: no E312 (F23's rule), only the read error.
    game = _game(tmp_path, "unread")
    _edit(game, target, target.replace("hana_here", "hana_her"))
    result = _load(game, _Unreadable)
    assert result.checks_skipped
    assert "E312" not in [code for code, _, _ in _errors(result)]


@pytest.fixture(autouse=True)
def _no_file_word_outside():
    """``file`` is registered at import, before and after each load (F31 s3)."""
    from engine.script.statements import get_spec
    assert get_spec("file") is metafiles.SPEC
    yield
    assert get_spec("file") is metafiles.SPEC
