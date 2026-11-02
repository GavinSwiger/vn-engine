"""The example game and "the corpus" for F03's whole-story checks (06 §0.5, §5.6, §5.8),
and the canonical JSON the determinism goldens hold.

- **Example**: ``game/`` loaded as bootstrap does, played with its own image files listed
  (``image_files``), so no directory is read during the run. Its menus (F07 step 5,
  AC-F07-45) are answered from ``EXAMPLE_PICKS``: across the five seeds every choice of
  every menu is picked at least once. ``example_inputs`` gives ``run_headless`` the same
  answers (default: the first choice at every menu, as Space does in the window).
- **Corpus**: F02's realistic corpus at 50,000 words / 10 files / seed 1 generated with
  ``--defaults`` (§5.8), plus the ``flow/``, ``vars/``, and ``lanterns/`` fixtures.
- **Canonical JSON** (§5.6): ``json.dumps(..., sort_keys=True, ensure_ascii=True)`` of every
  command and the final state. A command is ``{"type": <class>, <field>: …}`` with the
  fields that differ from their default (so a later feature's new field with a default
  doesn't change a golden); a value with ``to_json`` (``StageState``, ``GameState``) is
  written as that. Anything else is a ``TypeError``, so a golden never holds a ``repr``.
"""

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path
from types import MappingProxyType

from engine.core.paths import GamePaths
from engine.runtime.commands import Advance, Choose, Command
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, Status, story_variables
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from engine.script import load_story
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.program import Program
from tests.fixtures.F02 import gen_corpus
from tests.runtime.stage_story import EXAMPLE, example_minigames, load_example
from tests.runtime.story import end_waits, post_test_outcome

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F03"
GOLDENS = FIXTURES / "goldens"
CORPUS_ARGS = ["--words", "50000", "--files", "10", "--seed", "1", "--defaults"]
SMALL = ("flow", "vars", "lanterns")
EXAMPLE_SEEDS = (1, 2, 3, 4, 5)
# F07 (AC-F07-45): the choice picked at each menu, 1-based among its pickable choices; after
# the list, the first. Menus in story order: the lantern stall (Buy / Buy and write Hana's
# name, only with trust >= 2, i.e. seeds 2 and 3's "bad luck" / Not this year), the stall's
# nested "Red or white?" after Buy, then Daichi's talk loop (Hana / the bridge / Let's find
# that spot, each topic hidden once asked), then the night's end (F19: Walk Hana home → the
# sad ending / Stay for the festival → the good ending; the third, "Wait at the bridge", is
# the promise route, closed in a fresh store, so these runs never offer it: AC-F19-35).
EXAMPLE_PICKS: dict[int, tuple[int, ...]] = {
    1: (1, 1, 1, 1, 1),      # Buy, red; Hana, the bridge, leave
    2: (2, 2, 1, 1, 2),      # write Hana's name; the bridge, Hana, leave; the festival
    3: (1, 2, 2, 1, 1),      # Buy, white; the bridge, Hana, leave
    4: (2, 3),               # Not this year (great luck: two choices); leave at once
    5: (1, 1, 1, 2),         # Buy, red; Hana, then leave
}


# --- Stories ---------------------------------------------------------------------------------

def example_images() -> tuple[str, ...]:
    """``game/images/…`` as game-relative refs, sorted (F04's image scan stand-in)."""
    return tuple(sorted(p.relative_to(EXAMPLE).as_posix()
                        for p in (EXAMPLE / "images").rglob("*") if p.is_file()))


def example_program() -> Program:
    result = load_example()
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def make_corpus(root: Path, *, realistic: bool = True) -> dict[str, Path]:
    """Write the corpus under ``root``: one game folder per part, by name. With
    ``realistic=False``, only the ``SMALL`` parts (the default tier's slice: together with the
    example they use every statement kind the realistic part does)."""
    parts: dict[str, Path] = {}
    if realistic:
        parts["realistic"] = root / "realistic"
        gen_corpus.main([*CORPUS_ARGS, "--out", str(parts["realistic"])])
    for name in SMALL:
        shutil.copytree(FIXTURES / name, root / name / "script")
        parts[name] = root / name
    return parts


def load_part(folder: Path) -> Program:
    result = load_story(GamePaths(folder.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


# --- Playing ---------------------------------------------------------------------------------

def launched(program: Program, images: tuple[str, ...] = ()) -> Interpreter:
    """A fresh launch with the example's minigames (the bundled ones; F24-4's poem)."""
    launch = run_launch(program, images=ImageSource.from_files(images))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, minigames=example_minigames())


def take_all(interp: Interpreter) -> list[Command]:
    return interp.take_commands(1 << 30)


def settle(interp: Interpreter) -> int:
    """``end_waits``, and every minigame ended with its test outcome (``post_test_outcome``),
    until the story waits for a line or a menu or stops: the test drivers' answer to the
    example's poem (F24-4), which uses no input, as in ``run_headless``. Returns how many
    waits and minigames were ended."""
    count = 0
    while True:
        count += end_waits(interp)
        current = interp.current
        if interp.status is not Status.WAITING or type(current) is not Minigame:
            return count
        post_test_outcome(interp, current)
        interp.run(10_000)
        count += 1


@dataclasses.dataclass
class Played:
    """A story played to its end: the interpreter, every command in order, and the
    checkpoint of every line."""

    interp: Interpreter
    commands: list[Command]
    states: list[GameState]
    answers: list[str] = dataclasses.field(default_factory=list)   # per wait, as inputs

    @property
    def inputs(self) -> list[str]:
        """``run_headless`` inputs that play the same run: ``answers`` up to the last
        ``choose`` (the lines after it advance by themselves)."""
        last = max((i for i, a in enumerate(self.answers) if a != "advance"), default=-1)
        return self.answers[:last + 1]


def play(program: Program, seed: int, images: tuple[str, ...] = (),
         picks: tuple[int, ...] = ()) -> Played:
    """A fresh launch, ``new_game(seed)``, and every line advanced, as ``run_headless``
    plays. At a menu (F07) the next of ``picks`` is chosen (1-based among the pickable
    choices), or the first once ``picks`` run out. A minigame (F23) ends with its test
    outcome (``settle``), as ``run_headless`` does with no ``finish`` input: it takes no
    answer and has no entry in ``states``, so the k-th state is still the k-th line's."""
    interp = launched(program, images)
    interp.new_game(seed)
    interp.run(10_000)
    commands = take_all(interp)
    states: list[GameState] = []
    answers: list[str] = []
    pending = iter(picks)
    while interp.status is Status.WAITING:
        if settle(interp):                          # F09/F18 waits, F23 minigames: at once
            commands += take_all(interp)
            continue
        states.append(interp.checkpoint())
        current = interp.current
        if type(current) is Menu:
            n = next(pending, 1)
            answers.append(f"choose {n}")
            interp.post(Choose(current.sid,
                               interp.choices.waiting.pickable[n - 1]))  # type: ignore
        else:
            answers.append("advance")
            interp.post(Advance(current.sid))  # type: ignore[union-attr]
        interp.run(10_000)
        commands += take_all(interp)
    return Played(interp, commands, states, answers)


def example_inputs(seed: int, picks: tuple[int, ...] = ()) -> list[str]:
    """``run_headless`` inputs that play the example game to its end with ``seed``: the
    menus answered from ``picks`` (default: the first choice at each)."""
    return play(example_program(), seed, example_images(), picks).inputs


# --- Canonical JSON --------------------------------------------------------------------------

def canon(value: object) -> object:
    if hasattr(value, "to_json"):
        return value.to_json()  # type: ignore[union-attr]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, object] = {"type": type(value).__name__}
        for f in dataclasses.fields(value):
            item = getattr(value, f.name)
            if (f.default is not dataclasses.MISSING and type(item) is type(f.default)
                    and item == f.default):
                continue
            out[f.name] = canon(item)
        return out
    if isinstance(value, (list, tuple)):
        return [canon(v) for v in value]
    if isinstance(value, (dict, MappingProxyType)):
        return {k: canon(v) for k, v in value.items()}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError(f"no canonical form for {type(value).__name__}")


def dumps(document: object) -> str:
    return json.dumps(document, sort_keys=True, ensure_ascii=True, indent=1) + "\n"


def run_document(played: Played) -> dict:
    """Every command of a finished ``play`` and its final state."""
    interp = played.interp
    last = interp.checkpoint()
    return {
        "commands": canon(played.commands),
        "final": {
            "status": interp.status.name,
            "checkpoint": None if last is None else last.to_json(),
            "variables": canon(story_variables(interp.G, interp.reserved)),
            "dice": f"{interp.core.state:016x}",
        },
    }


def example_document() -> dict:
    program = example_program()
    images = example_images()
    return {"seeds": {str(seed): run_document(play(program, seed, images,
                                                   EXAMPLE_PICKS[seed]))
                      for seed in EXAMPLE_SEEDS}}


def corpus_document(parts: dict[str, Path]) -> dict:
    """The small parts in full. The realistic part's commands come to about 1.5 MB, over
    §5's 1 MiB for committed files, so its golden holds their count, the SHA-256 of their
    canonical JSON, and the first 20; the final state is in full."""
    out: dict[str, object] = {}
    for name, folder in parts.items():
        document = run_document(play(load_part(folder), 1))
        if name == "realistic":
            commands = document["commands"]
            text = json.dumps(commands, sort_keys=True, ensure_ascii=True)
            document["commands"] = {
                "count": len(commands),
                "sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
                "first": commands[:20],
            }
        out[name] = document
    return out


def dice_document() -> dict:
    """AC-F03-41's call script (``dice_golden.json``)."""
    from tests.runtime.test_dice import golden_document
    return golden_document()


def documents(corpus_root: Path, *, small: bool = False) -> dict[str, str]:
    """The three determinism documents, as canonical JSON text, by golden file name. With
    ``small``, the corpus document holds only the ``SMALL`` parts."""
    return {
        "commands_example.json": dumps(example_document()),
        "commands_corpus.json": dumps(corpus_document(make_corpus(corpus_root,
                                                                  realistic=not small))),
        "dice_golden.json": dumps(dice_document()),
    }


def main(argv: list[str]) -> int:
    """``python -m tests.runtime.corpus --out FILE --work DIR``: write the documents as one
    JSON object to FILE (AC-F03-67's subprocess; ``--small`` leaves out the realistic part,
    the default tier's run). ``--write-goldens --work DIR``: (re)write
    ``goldens/commands_*.json``; only when a change to the example game, the corpus, or a
    command is meant to change them (dice_golden.json never changes)."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--write-goldens", action="store_true")
    parser.add_argument("--small", action="store_true")
    args = parser.parse_args(argv)
    if args.write_goldens and args.small:
        parser.error("--write-goldens needs the whole corpus")
    docs = documents(args.work, small=args.small)
    if args.out is not None:
        args.out.write_text(json.dumps(docs, sort_keys=True), encoding="ascii")
    if args.write_goldens:
        GOLDENS.mkdir(exist_ok=True)
        for name in ("commands_example.json", "commands_corpus.json"):
            (GOLDENS / name).write_bytes(docs[name].encode("ascii"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
