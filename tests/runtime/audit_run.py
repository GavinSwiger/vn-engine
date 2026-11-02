"""AC-F03-69's subprocess (audit spy A, ``06-acceptance.md`` §0.5): load the example game and
the F03 seeded corpus first, then, with an audit hook installed, launch and play each one
headless with ``image_files=[]``, and print what the hook and the spies saw as JSON.

Run as ``python -m tests.runtime.audit_run``. Audit hooks can't be removed, so this is a
process of its own. ``--menus`` (F07 AC-F07-40) plays F07's ``agree/`` fixture with
AC-F07-35's inputs and ``show_locked``, and ``agree/`` without its menus (each menu replaced
by the lines of the choice those inputs pick, conditions kept as ``if``), instead. Loading (which reads the script files) happens before the hook; the
runtime, launch phase included, runs under it. Events are recorded with the story that was
running; the clean-up after the last story is not a story's.
"""

import builtins
import getpass
import json
import logging
import os
import re
import socket
import sys
import tempfile
from pathlib import Path

WATCHED = ("exec", "compile", "import", "open", "os.system", "os.listdir", "os.scandir",
           "subprocess.Popen")
MODULE = re.compile(r"""\bmodule\(\s*["']([\w./\\]+)["']\s*\)""")


def _load(root: Path, files: dict[str, str]):
    from engine.core.paths import GamePaths
    from engine.script import load_story
    for name, text in files.items():
        path = root / "script" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return load_story(GamePaths(root.resolve())).program


def _programs(tmp: Path) -> list[tuple[str, object, list[str]]]:
    """(name, program, modules its ``module(…)`` defines name) for every story that loads
    (a load error never reaches the runtime)."""
    from tests.runtime.corpus import example_program
    from tests.runtime.story import FIXTURES
    from tests.script import message_cases

    stories = [("example", example_program())]
    for folder in sorted((FIXTURES / "seeded").iterdir()):
        files = {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
                 for p in folder.rglob("*.vns")}
        stories.append((f"seeded/{folder.name}", _load(tmp / folder.name, files)))
    for case in message_cases.load_cases():
        if case.feature == "F03" and case.time != "load":
            text = message_cases.main_text(case)
            stories.append((case.id, _load(tmp / f"case{len(stories)}", {"main.vns": text})))
    return [(name, program, sorted({m for d in program.defines
                                    for m in MODULE.findall(d.value.source)}))
            for name, program in stories if program is not None]


# F07: ``agree/`` without menus, as AC-F07-35's inputs play it (``a c2 a c1 c1 c1 a``: the
# paper lantern, stay, Ask Hana, nothing). The gold choice's condition stays as an ``if``.
AGREE_NO_MENUS = """define hana = Character("Hana")
default coins = 1
default path = "start"
label start:
    "The festival is busy."
    hana "Which lantern?"
    if coins >= 2:
        $ path = "gold"
    $ path = "paper"
    "Between."
    $ path += " stay"
    scene black
    hana "Ask me what?"
    $ path += " nothing"
    "End: {var=path}."
    return
"""
AGREE_INPUTS = ["advance", "choose 2", "advance", "choose 1", "choose 1", "choose 1",
                "advance"]


def _menu_programs(tmp: Path) -> list[tuple[str, object, list[str]]]:
    """F07's ``agree/`` (with ``AGREE_INPUTS``) and its menu-less twin."""
    agree = Path(__file__).resolve().parents[1] / "fixtures" / "F07" / "agree" / "script"
    files = {"main.vns": (agree / "main.vns").read_text(encoding="utf-8")}
    return [("agree", _load(tmp / "agree", files), []),
            ("agree-no-menus", _load(tmp / "plain", {"main.vns": AGREE_NO_MENUS}), [])]


def main(argv: list[str] | None = None) -> int:
    menus = "--menus" in (sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        stories = _menu_programs(Path(tmp)) if menus else _programs(Path(tmp))
        from engine.runtime.headless import run_headless
        events: list[list[str]] = []
        calls: list[list[str]] = []
        current = ["-"]

        def hook(event: str, args: tuple) -> None:
            if current[0] == "-":
                return
            if event in WATCHED or event.startswith(("os.exec", "socket.")):
                detail = ""
                if event == "exec" and args:
                    detail = getattr(args[0], "co_filename", type(args[0]).__name__)
                elif event == "compile" and len(args) > 1:
                    detail = str(args[1])
                elif args:
                    detail = str(args[0])
                events.append([current[0], event, detail])

        def spy(name, real):
            def wrapper(*a, **k):
                if current[0] != "-":
                    calls.append([current[0], name])
                return real(*a, **k)
            return wrapper

        builtins.eval = spy("eval", builtins.eval)
        builtins.exec = spy("exec", builtins.exec)
        os.getlogin = spy("os.getlogin", os.getlogin)
        getpass.getuser = spy("getpass.getuser", getpass.getuser)
        socket.gethostname = spy("socket.gethostname", socket.gethostname)
        sys.addaudithook(hook)
        for name, program, _modules in stories:
            current[0] = name
            if name == "agree":
                ended = run_headless(program, seed=42, image_files=[], show_locked=True,
                                     inputs=AGREE_INPUTS)
            else:
                ended = run_headless(program, seed=42, image_files=[])
            current[0] = "-"
            if menus:
                assert type(ended[-1]).__name__ == "StoryEnded", (name, ended[-1])
    print(json.dumps({"events": events, "calls": calls,
                      "stories": [[n, m] for n, _, m in stories]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
