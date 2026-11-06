"""F48 step S9: the build's API-key scan (04 §7.8; 05 SEC-F48-24; 01 PR-F48-32, §6.6):
AC-F48-59 (AB-19), and AC-F48-02's unit half (the real build's needle scan is in
``test_real_build.py``)."""

import json
import subprocess

from engine.core.paths import engine_root
from engine.tools.assistant.reference import PRIMER, PRIMER_NEEDLE
from engine.tools.build import keyscan, procs, spec, texts
from engine.tools.editor import buildmodel, buildrunner
from tests.tools.build.test_command import (FakeChildren, events, fake_deps, make_game,
                                            run)

ANT = "sk-ant-api03-" + "Zq9x" * 10
PROJ = "sk-proj-" + "Ab1_" * 10
BARE = "sk-" + "a1B2c3D4e5" * 3


def plant(game):
    (game / "script" / "start.vns").write_text(
        f'label start:\n    "Hi."\n    $ key = "{ANT}"\n', encoding="utf-8")
    with open(game / "config.toml", "a", encoding="utf-8") as stream:
        stream.write(f'# api = "{PROJ}"\n')
    (game / "plugins").mkdir()
    (game / "plugins" / "helper.py").write_text(f"\n\nKEY = '{BARE}'  # {BARE}\n",
                                                encoding="utf-8")
    (game / "data.json").write_text(json.dumps({"a": 1, "k": ANT}), encoding="utf-8")
    (game / "notes.bin").write_bytes(ANT.encode())               # not a text kind: skipped
    (game / "story.md").write_text("ask-ant-123456 task-proj-x desk-" + "a" * 30,
                                   encoding="utf-8")             # no word boundary


def test_ac_f48_59_key_lines_match_on_word_boundaries():
    text = f"a\n{ANT} and {PROJ}\n\nx={BARE}\nmask-ant-abc sk-short sk-ant-\n"
    assert keyscan.key_lines(text) == [2, 4]
    assert keyscan.key_lines("") == [] and keyscan.key_lines("\r\n" * 3 + ANT) == [4]


def test_ac_f48_59_the_build_warns_with_ref_and_line_only(tmp_path):
    game = make_game(tmp_path / "lanterns")
    plant(game)
    hits = keyscan.scan(game)
    assert [(h.ref, h.line) for h in hits] == [("config.toml", 5), ("data.json", 1),
                                              ("plugins/helper.py", 3),
                                              ("script/start.vns", 3)]
    assert len(keyscan.scan(game, limit=2)) == 2
    # Report mode: build_done.keys, and no key text anywhere in the child's output.
    code, stdout, stderr = run(game, tmp_path / "builds", fake_deps(FakeChildren()),
                               report=True)
    assert code == 0, stderr
    done = events(stdout)[-1]
    assert done["event"] == "build_done"
    assert done["keys"] == [["config.toml", 5], ["data.json", 1], ["plugins/helper.py", 3],
                            ["script/start.vns", 3]]
    # CLI: §6.6's warning lines.
    code, stdout, stderr = run(game, tmp_path / "cli", fake_deps(FakeChildren()))
    assert code == 0, stderr
    assert ("script/start.vns, line 3: this looks like an API key. Remove it before you "
            "share the game.") in stdout.splitlines()
    assert "plugins/helper.py, line 3: this looks like an API key." in stdout
    for output in (stdout, stderr):
        for key in (ANT, PROJ, BARE, ANT[:12], "Zq9x"):
            assert key not in output


def test_ac_f48_59_studio_reads_the_keys_and_lists_them():
    fields = {"folder": "G 1 Windows", "exe": "G.exe", "files": 3, "bytes": 10, "zip": None,
              "zip_bytes": None, "warnings": 0, "left_out": [], "left_out_total": 0,
              "long_paths": 0, "long_path_example": None}
    decode = buildrunner._DECODERS["build_done"]
    assert decode(fields).keys == ()                                   # an older child
    done = decode({**fields, "keys": [["script/a.vns", 7]]})
    assert done.keys == (("script/a.vns", 7),)
    assert buildmodel.finished_texts(done).keys == (texts.key_found_text("script/a.vns", 7),)
    for bad in ([["x", 0]], [["x", "7"]], [["", 1]], [["x"]], "x", [["x", 1]] * 101,
                [["x", True]]):
        assert decode({**fields, "keys": bad}) is None


def test_ac_f48_59_the_build_child_gets_no_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANT)
    monkeypatch.setenv("Openai_Api_Key", PROJ)
    seen = []

    def popen(argv, **kwargs):
        seen.append((argv, kwargs))
        raise OSError(2, "stop here")

    game = make_game(tmp_path / "lanterns")
    runner = buildrunner.BuildRunner(game, popen=popen)
    runner.start(tmp_path / "builds", "G 1 Windows", zip=False, replace=False)
    (argv, kwargs), = seen
    assert not any(key in part for part in argv for key in (ANT, PROJ))
    assert not {k.upper() for k in kwargs["env"]} & procs.PROVIDER_KEY_VARS
    assert ANT not in kwargs["env"].values() and PROJ not in kwargs["env"].values()
    # The build's own grandchild (the check) goes through the same spawn; so does the packer
    # that makes a player runtime (F66, test_runtime).
    children = FakeChildren()
    calls = []
    deps = fake_deps(children, popen=lambda argv, **kw: calls.append(kw) or children(argv))
    assert run(game, tmp_path / "out", deps)[0] == 0
    assert len(calls) == 1 and all(
        not {k.upper() for k in kw["env"]} & procs.PROVIDER_KEY_VARS for kw in calls)


def test_ac_f48_02_no_assistant_module_or_primer_reaches_a_build():
    """The packer leaves ``engine.tools`` (so ``engine.tools.assistant``) out, and the
    primer's needle exists only under ``engine/tools/assistant``."""
    assert "engine.tools" in spec.EXCLUDES
    assert PRIMER_NEEDLE in PRIMER
    holders = [path.relative_to(engine_root()).as_posix()
               for path in (engine_root() / "engine").rglob("*")
               if path.is_file() and path.suffix in (".py", ".txt", ".md", ".json", ".toml")
               and PRIMER_NEEDLE in path.read_text(encoding="utf-8", errors="replace")]
    assert holders == ["engine/tools/assistant/reference.py"]
    assert not any(module.startswith("engine.tools")
                   for module in spec.engine_modules(engine_root()))


def test_primer_needle_is_absent_from_the_shipped_game():
    found = subprocess.run(["git", "grep", "-l", "-F", PRIMER_NEEDLE, "--", "game", "main.py"],
                           cwd=engine_root(), capture_output=True, text=True)
    assert found.stdout.strip() == ""
