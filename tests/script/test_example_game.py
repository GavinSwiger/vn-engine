"""The shipped example story *Paper Lanterns* (PR-F02-41; AC-F02-72, headless part).

``python main.py --bench 1`` with this story (AC-F01-05: exit 0, no WARNING or ERROR) is
``tests/app/test_smoke_launch.py``'s real launch and ``test_session_logs.py``'s in-process one;
the app side of loading it is ``tests/app/test_story_load_screen.py`` (AC-F02-62). The review
step (all text original) is the reviewer's.
"""

from pathlib import Path

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.script import LoadOptions, StoryLoader
from engine.script.nodes import Call, Define, If, Include, Jump, Label, PythonLine, Return, Say

GAME = Path(__file__).resolve().parents[2] / "game"
KINDS = ("include", "define", "label", "$", "narration", "dialogue", "jump", "call", "return",
         "if", "elif", "else")


def _load() -> StoryLoader:
    # As bootstrap does: config.toml's [stage.positions] names come first (F04 step 8).
    positions = load_config(GamePaths.for_game(GAME)).config.stage.positions.keys()
    loader = StoryLoader(GamePaths.for_game(GAME),
                         LoadOptions(collect_todos=True, position_names=positions))
    while not loader.step(1.0):
        pass
    return loader


def _first_uses(nodes) -> dict[str, tuple]:
    """kind → (file order, line, file ref) of its first use in reading order."""
    found: dict[str, tuple] = {}

    def note(kind: str, file, line: int) -> None:
        place = (file.order, line, file.ref)
        if kind not in found or place < found[kind]:
            found[kind] = place

    def walk(statements) -> None:
        for stmt in statements:
            if isinstance(stmt, Say):
                note("dialogue" if stmt.speaker else "narration", stmt.file, stmt.line)
                if stmt.attributes:
                    note("dialogue with an attribute", stmt.file, stmt.line)
            elif isinstance(stmt, PythonLine):
                note("$", stmt.file, stmt.line)
            elif isinstance(stmt, (Jump, Call, Return)):
                note(type(stmt).__name__.lower(), stmt.file, stmt.line)
            elif isinstance(stmt, If):
                for branch in stmt.branches:
                    note(branch.keyword, stmt.file, branch.line)
                    walk(branch.block)

    for node in nodes:
        if isinstance(node, Include):
            note("include", node.file, node.line)
        elif isinstance(node, Define):
            note("define", node.file, node.line)
        elif isinstance(node, Label):
            note("label", node.file, node.line)
            walk(node.block)
    return found


def test_example_story_loads_clean():
    result = _load().result
    assert result.program is not None and not result.no_story
    assert result.errors == () and result.error_count == 0 and not result.checks_skipped
    assert result.warnings == ()                       # no W02, W03, or W04
    assert result.todos == ()                          # nothing left to do in the example


def test_example_story_uses_every_f02_statement_with_a_comment_above():
    loader = _load()
    main_includes = [n for n in loader.nodes
                     if isinstance(n, Include) and n.file.ref == "script/main.vns"]
    assert main_includes
    uses = _first_uses(loader.nodes)
    assert set(KINDS) | {"dialogue with an attribute"} <= set(uses)
    for kind in KINDS:
        _, line, ref = uses[kind]
        lines = (GAME / ref).read_text(encoding="utf-8").splitlines()
        above = next(text for text in reversed(lines[:line - 1]) if text.strip())
        assert above.lstrip().startswith("#"), (kind, ref, line)


def test_example_files_are_plain_utf8_with_lf():
    files = sorted((GAME / "script").rglob("*"))
    assert [p.relative_to(GAME).as_posix() for p in files if p.is_file()] == [
        "script/bonus.vns", "script/chapter1.vns", "script/endings.vns", "script/main.vns",
        "script/routes/daichi.vns"]
    for path in files:
        if path.is_file():
            data = path.read_bytes()
            assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")
            data.decode("utf-8")


def test_ac_f34_15_w226_once_per_picture_and_the_example_is_clean(tmp_path):
    """AC-F34-15: the example's dev load gives no warning (its three gallery pictures all
    show in the story) and its dev launch finds every picture; with the true ending's
    ``scene cg last_lantern`` taken out, W226 names that picture once, at its declaration,
    and nothing else (its version still shows at the sad ending)."""
    import shutil

    from engine.runtime.images import ImageSource
    from engine.runtime.launch import run_launch
    from engine.script import load_story

    positions = tuple(load_config(GamePaths.for_game(GAME)).config.stage.positions.keys())
    options = LoadOptions(dev=True, position_names=positions)
    result = load_story(GamePaths.for_game(GAME), options)
    assert result.errors == () and result.warnings == (), (result.errors, result.warnings)
    images = tuple(sorted(p.relative_to(GAME).as_posix()
                          for p in (GAME / "images").rglob("*.png")))
    launch = run_launch(result.program, dev=True, images=ImageSource.from_files(images))
    assert launch.namespace is not None and launch.warnings == (), launch.warnings

    copy = tmp_path / "game"
    shutil.copytree(GAME / "script", copy / "script")
    shutil.copytree(GAME / "files", copy / "files")
    shutil.copytree(GAME / "audio", copy / "audio")     # the music-room tracks' files (W220)
    shutil.copy(GAME / "config.toml", copy / "config.toml")
    endings = copy / "script" / "endings.vns"
    text = endings.read_bytes().decode("utf-8")
    assert text.count("    scene cg last_lantern with dissolve\n") == 1
    endings.write_bytes(text.replace("    scene cg last_lantern with dissolve\n", "").encode())
    result = load_story(GamePaths.for_game(copy), options)
    assert result.errors == ()
    main = (GAME / "script" / "main.vns").read_text(encoding="utf-8").splitlines()
    line = main.index('lock gallery cg last_lantern "The Last Lantern":') + 1
    assert [(w.code, w.file, w.line, w.message) for w in result.warnings] == [
        ("W226", "script/main.vns", line, 'the gallery picture "cg last_lantern" never shows '
         "in the story and no unlock gallery line names it, so players can't get it.")]
