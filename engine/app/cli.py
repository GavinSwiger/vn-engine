"""Command-line entry points: ``python main.py``, ``python -m engine run``, and
``python -m engine edit``.

Why this module exists: both launch commands share the same options and the same
pre-pygame setup (SDL environment defaults, the pygame-ce version check, the build mode),
and that setup must run before anything imports pygame (PR-F01-20, TR-F01-50). This module
parses arguments, prepares the environment, decides ``release``, and hands over to the
startup sequence.

``_launch`` hands over to ``engine.app.bootstrap.launch`` (§7.1 steps 6 onward). The
bootstrap is imported only then, because later steps import pygame, which must not load
before ``prepare_environment()`` has run.

F44 (dev runs only; a frozen build doesn't define them, I-15): ``run`` gains ``--start
LABEL``, ``--set NAME=VALUE`` and the hidden ``--report-to-editor``, which become
``StartOptions`` and the editor link (``04`` §5.4); value errors are usage errors (exit 2),
found before anything loads. ``main(argv, editor=…)`` adds ``edit [GAME_DIR]``, which runs
the given handler without ``prepare_environment`` or the pygame check: the editor process
imports only this module from ``engine.app`` and never pygame (ADR-0008). ``main.py``'s
launcher has none of these (I-10).

F03 step 13 (``04`` §12.1, PR-F03-16): ``run`` also gains ``--seed N``, dev runs only under
the same rule (refused with ``--release``, not defined in a frozen build, not ``main.py``'s,
F44 I-10). Every new game of the session is seeded with N (``App.seed`` → ``install_story``).

F12 (``04`` §13, ``07`` I-1 item 9): ``run`` also gains ``--no-persistent``, under the same
dev-runs-only rule: persistent data stays in memory for the run and no file is read or
written (``App.no_persistent`` → ``app/persistence.py``).

F45 (``04`` §3, §7.1; ``07`` I-1): ``main(argv, checker=…)`` adds the dev-only ``check
[GAME_DIR] [--report-to-editor] [--stdin-overlay] [--no-launch]``, Studio's check child. Like
``edit`` it runs its handler without ``prepare_environment`` or the pygame check (the check
child never imports pygame); ``--release`` is a usage error and a frozen build doesn't
define it.

F47 (``04`` §3.3, §7.3): ``main(argv, helper=…)`` adds the dev-only ``helper [GAME_DIR]``,
Studio's long-lived helper child (settings stills, thumbnails, ▶). Like ``check`` it runs its
handler without ``prepare_environment`` or the pygame check (the handler sets up SDL itself);
``--release`` is a usage error and a frozen build doesn't define it.

F39 (``SPEC.md`` §5.4): ``run`` also gains the hidden ``--resume-from-editor`` and
``--window-at=X,Y``, which Studio adds when it updates a running preview, under the same
dev-runs-only rule (refused with ``--release``, not defined in a frozen build, not
``main.py``'s). ``--resume-from-editor`` needs ``--report-to-editor`` (the frame arrives on
stdin, which is read only then); ``--window-at`` takes two whole numbers, each at most
100,000 from 0.

F42 (``04`` §3.3, §7.5; architect decisions 1, 8): ``main(argv, builder=…)`` adds the dev-only
``build [GAME_DIR] [--out FOLDER] [--zip] [--replace]`` (and the hidden
``--report-to-editor``); the handler comes from ``engine/__main__.py``, so ``app`` never
imports ``tools``. In a built game (frozen) ``launcher_main`` is the whole parser: it runs
``<exe folder>/game`` (``paths.launcher_game_dir``), first running the frozen prelude
(``_frozen_prelude``), and ``App.dev`` is always false (``_start``).

F47 P2-F (``04`` §7.5): ``run`` also gains ``--try-stdin``, Studio's Try it, under the same
dev-runs-only rule (refused with ``--release``, not defined in a frozen build, not
``main.py``'s). It reads a few script lines from stdin (at most ``TRY_MAX_BYTES``; bad text
is a usage error) and plays them as a throwaway label from the start, with nothing written
(``app/trystory.py``); ``--start`` and ``--resume-from-editor`` can't go with it.

F34 (``04`` §7.3): ``run`` also gains ``--extras [PAGE]``, Studio's "Preview the gallery",
under the same dev-runs-only rule (refused with ``--release``, not defined in a frozen build,
not ``main.py``'s). Persistent data stays in memory (as ``--no-persistent``), everything in
Extras counts as unlocked there, and the title shows with Extras open on PAGE (default
``gallery``); ``--start`` and ``--try-stdin`` can't go with it, and a PAGE that isn't one of
``EXTRAS_PAGES`` is a usage error naming them.

F36 (``04`` §7.4): ``run`` also gains ``--replay LABEL``, Studio's "Play replay", under the
same dev-runs-only rule. The scene replay of LABEL starts at once (no title; a ``lock replay``
of it gives its end scene and starting values) and the game closes at its end. LABEL that
isn't a name is a usage error, and ``--start``, ``--extras`` and ``--try-stdin`` can't go
with it; a LABEL the story doesn't have is an error at launch (``app/replays.py``).

F41 (``04`` §16 W1; PR-F41-08..12): ``main(argv, linter=…)`` adds the dev-only
``lint [GAME_DIR] [--json] [--strict]``, the full check printed for editors and CI. Its
handler (``engine/__main__.py``) has no release mode, so ``--release`` is refused here and a
frozen build doesn't define it.

F48 (``04`` §7.6; ``07`` I-10): ``main(argv, assist_mcp=…)`` adds the dev-only
``assist-mcp [GAME_DIR] [--read-only] [--no-launch]``, the assistant's MCP server for AI apps
(newline-delimited JSON-RPC on stdin and stdout), under the same dev-runs-only rule
(``--release`` is a usage error, a frozen build doesn't define it). Its ``GAME_DIR`` default
is ``lint``'s. Nothing on this path writes to stdout before the handler's ``serve`` takes the
protocol stream: an argument error or ``--help`` exits before the server starts.
"""

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

from engine import _bootcheck
from engine.core import safefile
from engine.core.constants import PLAYTHROUGH_MAX
from engine.core.paths import engine_root, is_frozen, launcher_game_dir
from engine.core.startvalues import StartOptions, parse_set_list

LOG_LEVELS = ("debug", "info", "warning", "error")
BENCH_MIN_SECONDS = 1.0
BENCH_MAX_SECONDS = 3600.0

# Shown when main.py gets a positional argument. The repo path is a literal placeholder,
# so the usage error never reveals a home path (security N3, implementation note I-4).
LAUNCHER_FOLDER_HINT = ("main.py always runs the game in <repo>/game; "
                        "use python -m engine run <folder> for another folder")

# F44 usage errors (04 §5.4, I-9; drafts for the narrative designer, G5).
START_NEEDS_LABEL = "--start needs a label name, like club_poem"
# F03 step 13 (04 §12.1): --seed N, decimal, 0 <= N < 2**64 (draft for the narrative designer).
SEED_MAX = (1 << 64) - 1
SEED_NEEDS_NUMBER = f"--seed needs a whole number from 0 to {SEED_MAX}, like 42"
# F32 (04 §6.8, 07 G7): run --playthrough N previews the title look of playthrough N.
PLAYTHROUGH_NEEDS_NUMBER = "--playthrough needs a whole number from 0 to 99, like 2"
# F39 (SPEC §5.4): the window spot of an updated preview.
WINDOW_AT_MAX = 100_000
WINDOW_AT_NEEDS_NUMBERS = "--window-at needs two whole numbers, like 120,80"
RESUME_NEEDS_REPORT = "--resume-from-editor needs --report-to-editor"
# F34 (04 §7.3): run --extras [PAGE]. The pages are ``ui/menus.DEFAULT_ORDER["extras"]``,
# written out here because this module imports nothing of ``engine.ui`` (Studio imports it).
EXTRAS_PAGES = ("gallery", "endings", "replays", "music_room", "achievements")
EXTRAS_DEFAULT_PAGE = "gallery"
EXTRAS_NEEDS_PAGE = ("--extras takes one of these pages: " + ", ".join(EXTRAS_PAGES)
                     + ", like --extras gallery")
EXTRAS_WITH_START = "--extras can't be used with --start or --try-stdin"
# F36 (04 §7.4): run --replay LABEL.
REPLAY_NEEDS_LABEL = "--replay needs a label name, like festival"
REPLAY_WITH_START = "--replay can't be used with --start, --extras or --try-stdin"
EDITOR_DEV_ONLY = "the editor is only available in dev runs"
CHECK_DEV_ONLY = "check is only available in dev runs"           # F45
HELPER_DEV_ONLY = "helper is only available in dev runs"         # F47
BUILD_DEV_ONLY = "build is only available in dev runs"           # F42 PR-F42-01
LINT_DEV_ONLY = "lint is only available in dev runs"             # F41 PR-F41-12
ASSIST_MCP_DEV_ONLY = "assist-mcp is only available in dev runs"  # F48 04 §7.6
# F42 01 §6.3; the same text as tools/build/texts.py's, kept here because a built game has
# no engine/tools (PR-F42-04).
GAME_FOLDER_MISSING = ("The game folder is missing. "
                       "Keep {exe}, _internal and game together in one folder.")
# F42 I-6: build's default --out folder, beside the game folder (D6).
BUILDS_DIRNAME = "builds"


def dev_only(option: str) -> str:
    """I-9: the ``--release`` message names the option used."""
    return f"{option} is only available in dev runs"


EditorHandler = Callable[[Path], int]
# F45: check_handler(game_dir, report=…, overlay=…, launch=…) -> exit code.
CheckHandler = Callable[..., int]
# F47: helper_handler(game_dir) -> exit code.
HelperHandler = Callable[[Path], int]
# F42: build_handler(game_dir, out=…, zip=…, replace=…, report=…) -> exit code.
BuildHandler = Callable[..., int]
# F41: lint_handler(game_dir, as_json=…, strict=…) -> exit code.
LintHandler = Callable[..., int]
# F48: assist_mcp_handler(game_dir, read_only=…, launch=…) -> exit code.
AssistMcpHandler = Callable[..., int]
# F40: console_factory(app) -> the App's console (``engine/__main__.py``'s ``_console``).
ConsoleFactory = Callable[..., object]


def _bench_seconds(text: str) -> float:
    """argparse type for ``--bench``: a number of seconds from 1 to 3600."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not BENCH_MIN_SECONDS <= value <= BENCH_MAX_SECONDS:
        raise argparse.ArgumentTypeError("the number of seconds must be from 1 to 3600")
    return value


def _seed(text: str) -> int:
    """argparse type for ``--seed``: ASCII decimal digits only (no sign, point, or space),
    0 <= N < 2**64."""
    if not (text.isascii() and text.isdigit()) or int(text) > SEED_MAX:
        raise argparse.ArgumentTypeError(SEED_NEEDS_NUMBER)
    return int(text)


def _playthrough(text: str) -> int:
    """argparse type for ``--playthrough`` (F32 ``04`` §6.8): ASCII digits only, 0 to
    ``PLAYTHROUGH_MAX``."""
    if not (text.isascii() and text.isdigit()) or int(text) > PLAYTHROUGH_MAX:
        raise argparse.ArgumentTypeError(PLAYTHROUGH_NEEDS_NUMBER)
    return int(text)


def _extras_page(text: str) -> str:
    """argparse type for ``--extras PAGE`` (F34): one of ``EXTRAS_PAGES``."""
    if text not in EXTRAS_PAGES:
        raise argparse.ArgumentTypeError(EXTRAS_NEEDS_PAGE)
    return text


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--release", action="store_true",
                        help="run as a release build (logs go to the per-user folder)")
    parser.add_argument("--bench", metavar="SECONDS", type=_bench_seconds, default=None,
                        help="measure frame times for SECONDS (1-3600) after a 5 s warm-up, "
                             "log the result, and quit")
    parser.add_argument("--log-level", metavar="LEVEL", choices=LOG_LEVELS, default=None,
                        help="lowest level written to the log: " + ", ".join(LOG_LEVELS))


def launcher_main(argv: list[str]) -> int:
    """``python main.py [--release] [--bench SECONDS] [--log-level LEVEL]``: always runs
    ``<repo>/game``, or ``<exe folder>/game`` in a built game (F42 PR-F42-03). A positional
    argument prints the usage line and exits 2 (silently in the windowed exe)."""
    frozen = is_frozen()
    if frozen:
        missing = _frozen_prelude()
        if missing is not None:
            return missing
    parser = argparse.ArgumentParser(
        prog=Path(sys.executable).name if frozen else "python main.py",
        description="Run the game in the game folder next to "
                    + ("this program." if frozen else "main.py."))
    _add_options(parser)
    parser.add_argument("unexpected", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.unexpected:
        parser.error(LAUNCHER_FOLDER_HINT)
    return _start(launcher_game_dir(), args)


def _frozen_prelude() -> int | None:
    """F42 04 §7.5 (SEC-F42-01, -09, -14): the built game's first steps, before argparse.
    (1) A windowed exe has no ``sys.stdout``/``sys.stderr``; they become ``os.devnull`` so
    argparse and F01's console handler can't crash (usage errors exit 2 silently).
    (2) Only ``sys.path`` entries under ``_MEIPASS`` stay: nothing is imported from the exe
    folder, ``game/`` or the CWD. (3) No ``__pycache__`` is written. (4) A missing
    ``<exe folder>/game`` shows ``GAME_FOLDER_MISSING`` in the native error box; the answer
    is then 1 (else None)."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))   # noqa: SIM115
    bundle = os.path.normcase(os.path.abspath(getattr(sys, "_MEIPASS", "") or os.sep))
    sys.path[:] = [entry for entry in sys.path if _under(entry, bundle)]
    sys.dont_write_bytecode = True
    if safefile.ensure_real_dir(launcher_game_dir(), release=True, create=False):
        return None
    exe = Path(sys.executable)
    prepare_environment()
    from engine.app import bootstrap

    bootstrap.show_native_error(exe.stem, GAME_FOLDER_MISSING.format(exe=exe.name))
    return 1


def _under(entry: object, bundle: str) -> bool:
    """Whether the ``sys.path`` entry is an absolute path at or below ``bundle``."""
    if not isinstance(entry, str) or not entry or not os.path.isabs(entry):
        return False
    path = os.path.normcase(os.path.abspath(entry))
    return path == bundle or path.startswith(bundle.rstrip("\\/") + os.sep)


def main(argv: list[str], *, editor: EditorHandler | None = None,
         checker: CheckHandler | None = None,
         helper: HelperHandler | None = None,
         builder: BuildHandler | None = None,
         linter: LintHandler | None = None,
         console: ConsoleFactory | None = None,
         assist_mcp: AssistMcpHandler | None = None) -> int:
    """``python -m engine run [GAME_DIR] [options]``, and ``edit [GAME_DIR]`` when
    ``editor`` is given (``engine/__main__.py``) and the build isn't frozen; likewise
    ``check [GAME_DIR] …`` with ``checker`` (F45), ``helper`` (F47), ``build [GAME_DIR]
    [--out FOLDER] [--zip] [--replace]`` with ``builder`` (F42), ``lint [GAME_DIR]
    [--json] [--strict]`` with ``linter`` (F41) and ``assist-mcp [GAME_DIR] [--read-only]
    [--no-launch]`` with ``assist_mcp`` (F48). F40: ``console`` (the developer
    console's factory) reaches ``bootstrap.launch`` only for a dev ``run``; a frozen build
    or ``--release`` drops it. ``GAME_DIR`` defaults to
    ``<repo>/game``; a relative ``GAME_DIR`` (or ``--out``) is resolved against the CWD
    once. ``build``'s ``--out`` defaults to ``builds`` beside the game folder (F42 I-6).
    F39's dev-only ``run`` options belong under ``dev_tools`` too, never in
    ``launcher_main`` (a frozen build defines none of them)."""
    dev_tools = not is_frozen()                         # I-15: none of F44 when frozen
    parser = argparse.ArgumentParser(prog="python -m engine")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    run = commands.add_parser("run", help="run a game folder",
                              description="Run the game in GAME_DIR.")
    run.add_argument("game_dir", nargs="?", metavar="GAME_DIR", default=None,
                     help="the game folder (default: the game folder next to main.py)")
    _add_options(run)
    if dev_tools:
        _add_start_options(run)
    edit = None
    if editor is not None and dev_tools:
        edit = commands.add_parser("edit", help="edit a game's script files",
                                   description="Open the scene editor on GAME_DIR.")
        edit.add_argument("game_dir", nargs="?", metavar="GAME_DIR", default=None,
                          help="the game folder (default: the game folder next to main.py)")
        edit.add_argument("--release", action="store_true", help=argparse.SUPPRESS)
    check = None
    if checker is not None and dev_tools:
        check = commands.add_parser("check", help="check a game folder for Studio",
                                    description="Check the game in GAME_DIR without "
                                                "opening a window (Studio's check child).")
        check.add_argument("game_dir", nargs="?", metavar="GAME_DIR", default=None,
                           help="the game folder (default: the game folder next to main.py)")
        check.add_argument("--report-to-editor", action="store_true",
                           help="write report lines for Studio instead of plain text")
        check.add_argument("--stdin-overlay", action="store_true",
                           help="read unsaved script text from stdin")
        check.add_argument("--no-launch", action="store_true",
                           help="load only: run no define, default, or module() code")
        check.add_argument("--release", action="store_true", help=argparse.SUPPRESS)
    helper_cmd = None
    if helper is not None and dev_tools:                # F47
        helper_cmd = commands.add_parser("helper", help="Studio's preview and sound helper",
                                         description="Answer Studio's still, thumbnail, and "
                                                     "sound requests on stdin for GAME_DIR.")
        helper_cmd.add_argument("game_dir", nargs="?", metavar="GAME_DIR", default=None,
                                help="the game folder (default: the game folder next to "
                                     "main.py)")
        helper_cmd.add_argument("--release", action="store_true", help=argparse.SUPPRESS)
    build = None
    if builder is not None and dev_tools:               # F42 PR-F42-01
        build = commands.add_parser("build", help="build a game players can run on Windows",
                                    description="Make a folder of the game in GAME_DIR that "
                                                "players can run without installing "
                                                "anything.")
        build.add_argument("game_dir", nargs="?", metavar="GAME_DIR", default=None,
                           help="the game folder (default: the game folder next to main.py)")
        build.add_argument("--out", metavar="FOLDER", default=None,
                           help="where to save the build (default: a builds folder next to "
                                "the game folder)")
        build.add_argument("--zip", action="store_true",
                           help="also make a .zip file to share")
        build.add_argument("--replace", action="store_true",
                           help="replace an earlier build of the same version")
        build.add_argument("--report-to-editor", action="store_true", help=argparse.SUPPRESS)
        build.add_argument("--release", action="store_true", help=argparse.SUPPRESS)
    lint = None
    if linter is not None and dev_tools:                # F41 PR-F41-08, PR-F41-12
        lint = commands.add_parser("lint", help="list every problem in a game folder",
                                   description="Check the game in GAME_DIR and print every "
                                               "problem and unused thing, one per line.")
        lint.add_argument("game_dir", nargs="?", metavar="GAME_DIR", default=None,
                          help="the game folder (default: the game folder next to main.py)")
        lint.add_argument("--json", action="store_true",
                          help="print one JSON document instead of lines")
        lint.add_argument("--strict", action="store_true",
                          help="exit 1 on warnings too, not only on errors")
        lint.add_argument("--release", action="store_true", help=argparse.SUPPRESS)
    assist = None
    if assist_mcp is not None and dev_tools:            # F48 04 §7.6
        assist = commands.add_parser(
            "assist-mcp", help="let an AI app (MCP) read, check and edit a game folder",
            description="Serve the game in GAME_DIR to an AI app over MCP: JSON-RPC "
                        "messages, one per line, on stdin and stdout. Started by the app "
                        "(see Studio's Help > Connect an AI app).")
        assist.add_argument("game_dir", nargs="?", metavar="GAME_DIR", default=None,
                            help="the game folder (default: the game folder next to main.py)")
        assist.add_argument("--read-only", action="store_true",
                            help="offer no tool that changes files")
        assist.add_argument("--no-launch", action="store_true",
                            help="checks load only: run no define, default, or module() code")
        assist.add_argument("--release", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.game_dir is None:
        game_dir = engine_root() / "game"
    else:
        game_dir = Path(args.game_dir).absolute()
    if args.command == "edit":
        if args.release:
            edit.error(EDITOR_DEV_ONLY)
        # No prepare_environment and no pygame check: the editor never imports pygame.
        return editor(game_dir)
    if args.command == "check":
        if args.release:
            check.error(CHECK_DEV_ONLY)
        # Likewise: the check child never imports pygame (F45 04 §3).
        return checker(game_dir, report=args.report_to_editor, overlay=args.stdin_overlay,
                       launch=not args.no_launch)
    if args.command == "helper":
        if args.release:
            helper_cmd.error(HELPER_DEV_ONLY)
        return helper(game_dir)
    if args.command == "build":
        if args.release:
            build.error(BUILD_DEV_ONLY)
        # Like check: the build child never imports pygame here (only its icon step does).
        out = (Path(args.out).absolute() if args.out is not None
               else game_dir.parent / BUILDS_DIRNAME)
        return builder(game_dir, out=out, zip=args.zip, replace=args.replace,
                       report=args.report_to_editor)
    if args.command == "lint":
        if args.release:
            lint.error(LINT_DEV_ONLY)
        # Like check: no pygame; the handler writes nothing in the game folder.
        return linter(game_dir, as_json=args.json, strict=args.strict)
    if args.command == "assist-mcp":
        if args.release:
            assist.error(ASSIST_MCP_DEV_ONLY)
        # No prepare_environment, no pygame check and no output: stdout is the protocol's.
        return assist_mcp(game_dir, read_only=args.read_only, launch=not args.no_launch)
    if dev_tools:
        _refuse_dev_options(run, args)
        if args.extras is not None and (args.start is not None or args.try_stdin):
            run.error(EXTRAS_WITH_START)                # F34: the title is needed
        if args.replay is not None:                     # F36: a replay is its own start
            if args.start is not None or args.extras is not None or args.try_stdin:
                run.error(REPLAY_WITH_START)
            if not args.replay.isidentifier():
                run.error(REPLAY_NEEDS_LABEL)
        if args.try_stdin:                              # F47 P2-F: the throwaway label
            from engine.app import trystory     # only here: Studio imports this module

            if args.start is not None or args.resume_from_editor:
                run.error(trystory.TRY_WITH_START)
            args.start = trystory.TRY_LABEL
        args.start_options = _start_options(run, args)
        args.window_position = _window_position(run, args.window_at)
        if args.resume_from_editor and not args.report_to_editor:
            run.error(RESUME_NEEDS_REPORT)
        if args.try_stdin:
            args.try_lines = _try_lines(run)
        args.console = console                          # F40: dev runs only
    return _start(game_dir, args)


def _add_start_options(run: argparse.ArgumentParser) -> None:
    """F44 §5.4 and F03 ``04`` §12.1: ``run``'s dev-run options (never ``main.py``'s,
    I-10). ``--set`` keeps the raw strings; ``_start_options`` checks them as one list
    (I-5)."""
    run.add_argument("--start", metavar="LABEL", default=None,
                     help="start new games at LABEL instead of start (dev runs)")
    run.add_argument("--set", metavar="NAME=VALUE", action="append", default=None,
                     help="start new games with the default NAME set to VALUE, like "
                          "--set \"hana_name='Hana'\" (dev runs; repeatable, at most 100)")
    run.add_argument("--report-to-editor", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--seed", metavar="N", type=_seed, default=None,
                     help="seed the dice of every new game with N (0 to 2^64-1), to replay "
                          "a run (dev runs)")
    run.add_argument("--no-persistent", action="store_true",
                     help="don't read or save persistent data in this run, to test a first "
                          "playthrough (dev runs)")
    run.add_argument("--playthrough", metavar="N", type=_playthrough, default=None,
                     help="show the game as playthrough N (persistent.playthrough = N), "
                          "keeping persistent data in memory, to preview a playthrough's "
                          "title look (dev runs)")
    # F39: Studio's own (hidden); Studio passes ``--window-at=X,Y`` as one item, so a
    # negative X isn't read as an option.
    run.add_argument("--resume-from-editor", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--window-at", metavar="X,Y", default=None, help=argparse.SUPPRESS)
    # F47 P2-F: Studio's Try it.
    run.add_argument("--try-stdin", action="store_true",
                     help="play the script lines read from stdin in a small window, then "
                          "quit; nothing is saved or written (dev runs)")
    # F34: Studio's "Preview the gallery".
    run.add_argument("--extras", metavar="PAGE", nargs="?", const=EXTRAS_DEFAULT_PAGE,
                     type=_extras_page, default=None,
                     help="open Extras on PAGE (default gallery) with everything in it "
                          "unlocked, keeping persistent data in memory (dev runs)")
    # F36: Studio's "Play replay".
    run.add_argument("--replay", metavar="LABEL", default=None,
                     help="play the scene replay of LABEL at once, as from Extras, and close "
                          "the game at its end (dev runs)")


def _try_lines(run: argparse.ArgumentParser) -> tuple[str, ...]:
    """``--try-stdin``'s lines: stdin read to its end (at most ``TRY_MAX_BYTES`` + 1), or a
    usage error (exit 2) before anything loads."""
    from engine.app import trystory

    stream = getattr(sys.stdin, "buffer", None)
    try:
        data = stream.read(trystory.TRY_MAX_BYTES + 1) if stream is not None else b""
    except (OSError, ValueError):
        data = b""
    lines = trystory.parse_try_text(data or b"")
    if isinstance(lines, str):
        run.error(lines)
    return lines


def _refuse_dev_options(run: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """With ``--release``, the first dev-run option used is a usage error naming it (I-9;
    F03 ``04`` §12.1 for ``--seed``; F39 for its two)."""
    if not args.release:
        return
    for option, given in (("--start", args.start is not None),
                          ("--set", args.set is not None),
                          ("--report-to-editor", args.report_to_editor),
                          ("--seed", args.seed is not None),
                          ("--no-persistent", args.no_persistent),
                          ("--playthrough", args.playthrough is not None),
                          ("--resume-from-editor", args.resume_from_editor),
                          ("--window-at", args.window_at is not None),
                          ("--try-stdin", args.try_stdin),
                          ("--extras", args.extras is not None),
                          ("--replay", args.replay is not None)):
        if given:
            run.error(dev_only(option))


def _window_position(run: argparse.ArgumentParser,
                     text: str | None) -> tuple[int, int] | None:
    """F39's ``--window-at X,Y``: two ASCII whole numbers (an optional ``-``, no spaces),
    each at most ``WINDOW_AT_MAX`` from 0; anything else is ``WINDOW_AT_NEEDS_NUMBERS``."""
    if text is None:
        return None
    parts = text.split(",")
    if len(parts) != 2:
        run.error(WINDOW_AT_NEEDS_NUMBERS)
    values = []
    for part in parts:
        digits = part[1:] if part.startswith("-") else part
        if not (digits.isascii() and digits.isdigit()) or len(digits) > 6:
            run.error(WINDOW_AT_NEEDS_NUMBERS)
        value = int(part)
        if abs(value) > WINDOW_AT_MAX:
            run.error(WINDOW_AT_NEEDS_NUMBERS)
        values.append(value)
    return values[0], values[1]


def _start_options(run: argparse.ArgumentParser,
                   args: argparse.Namespace) -> StartOptions | None:
    """The checked ``StartOptions`` (None when neither ``--start`` nor ``--set`` is used).
    Every problem is a usage error (exit 2) found before anything loads; ``--release``
    with any of them was refused first (``_refuse_dev_options``)."""
    if args.start is not None and not args.start.isidentifier():
        run.error(START_NEEDS_LABEL)
    values, problems = parse_set_list(args.set or [])
    if problems:
        run.error("\n".join(problem.message for problem in problems))
    if args.start is None and not values:
        return None
    return StartOptions(label=args.start, values=values)


def prepare_environment() -> None:
    """SDL settings that must be in place before pygame is imported (§7.1 step 3).

    ``SDL_VIDEODRIVER`` is never set, so Linux uses SDL's default X11 driver, including
    XWayland under a Wayland session (PR-F01-63).
    """
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    # F52 (07 I-10): the IME draws its own candidate and composition windows; the engine
    # places them under the caret (``app/textinput``).
    os.environ.setdefault("SDL_IME_SHOW_UI", "1")
    if sys.platform == "win32":
        os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")


def _start(game_dir: Path, args: argparse.Namespace) -> int:
    """Shared tail of both entry points (§7.1 steps 3–5)."""
    try:
        prepare_environment()
        pygame_warning = _bootcheck.check_pygame()
        # Nothing but a frozen build or --release makes a run a release run; nothing else
        # (no environment variable, no config key) affects dev mode (SEC-F01-20).
        release = is_frozen() or args.release
        return _launch(game_dir, release=release, bench_seconds=args.bench,
                       log_level_override=args.log_level, pygame_warning=pygame_warning,
                       start=getattr(args, "start_options", None),
                       editor_report=getattr(args, "report_to_editor", False),
                       seed=getattr(args, "seed", None),
                       no_persistent=getattr(args, "no_persistent", False),
                       playthrough=getattr(args, "playthrough", None),
                       resume=getattr(args, "resume_from_editor", False),
                       window_at=getattr(args, "window_position", None),
                       try_lines=getattr(args, "try_lines", None),
                       extras=getattr(args, "extras", None),
                       replay=getattr(args, "replay", None),
                       console=None if release else getattr(args, "console", None))
    except KeyboardInterrupt:
        return 0        # Ctrl+C before logging starts exits silently (§7.1 step 19)


def _launch(game_dir: Path, *, release: bool, bench_seconds: float | None,
            log_level_override: str | None, pygame_warning: str | None,
            start: StartOptions | None = None, editor_report: bool = False,
            seed: int | None = None, no_persistent: bool = False, resume: bool = False,
            window_at: tuple[int, int] | None = None,
            try_lines: tuple[str, ...] | None = None,
            playthrough: int | None = None, extras: str | None = None,
            replay: str | None = None, console: ConsoleFactory | None = None) -> int:
    """The startup sequence (``engine.app.bootstrap.launch``)."""
    from engine.app import bootstrap

    return bootstrap.launch(game_dir, release=release, bench_seconds=bench_seconds,
                            log_level_override=log_level_override,
                            pygame_warning=pygame_warning, start=start,
                            editor_report=editor_report, seed=seed,
                            no_persistent=no_persistent, resume=resume,
                            window_at=window_at, try_lines=try_lines,
                            playthrough=playthrough, extras=extras, replay=replay,
                            console=console)
