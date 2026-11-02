"""Helpers for F04's headless stage tests (F04 ``06-acceptance.md`` §0.2, §0.4, §0.5, §5).

- **Run H** (§0.2): a game folder in ``tmp_path`` with its ``config.toml``, loaded with
  ``LoadOptions(position_names=config.stage.positions)`` as bootstrap does, then
  ``run_headless(program, seed=42, image_files=...)``.
- **Template S** (§0.4) and ``lanterns/`` (§5.3), with the image lists IMG and IMG-L (§5.1).
- **Stage notation** (§0.5): ``stage("bg dusk | hana sad@left, girl_a=lantern_girl@(900)
  flip, railing@center L10")`` builds the ``StageState`` it names.
"""

import functools
import re
import shutil
from collections.abc import Mapping
from pathlib import Path

from engine.core.config import load_config
from engine.core.minigame_types import MinigameSig
from engine.core.paths import GamePaths
from engine.minigames.loader import load_plugins
from engine.runtime.commands import (AudioRestore, Command, EndVoice, PlayMusic, PlaySound,
                                     PlayVoice, PrefetchImages, QueueMusic, ShowStage,
                                     StopMusic, StopSound, StopVoice)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.runtime.stage import SpriteState, StageState
from engine.script.loader import LoadOptions, LoadResult, load_story
from engine.script.program import Program
from tests.script.helpers import template_s

F04 = Path(__file__).resolve().parents[1] / "fixtures" / "F04"
EXAMPLE = Path(__file__).resolve().parents[2] / "game"

IMG = ("images/bg/river_night.png", "images/bg/bridge.png", "images/bg/red.png",
       "images/hana/happy.png", "images/hana/pout.png", "images/hana/sad.png",
       "images/hana/surprised.png", "images/daichi/grin.png", "images/daichi/sigh.png",
       "images/stall.png", "images/desk.png", "images/witness.png", "images/railing.png",
       "images/lantern_girl.png", "images/student/neutral.png", "images/student/angry.png",
       "images/a.png", "images/b.png", "images/c.png")
IMG_L = ("images/bg/river_night.png", "images/stall.png", "images/hana/happy.png",
         "images/hana/pout.png", "images/hana/surprised.png", "images/hana/sad.png",
         "images/daichi/grin.png", "images/daichi/sigh.png", "images/railing.png",
         "images/lantern_girl.png")

TEMPLATE_CONFIG = "[stage.positions]\nstall_spot = 1060\n"


# --- Games --------------------------------------------------------------------------------

def position_names(root: Path) -> frozenset[str]:
    """The ``at`` names ``root/config.toml`` gives (built-ins included), as bootstrap reads
    them before the story."""
    config = load_config(GamePaths(root.resolve()))
    assert not config.errors, config.errors
    return frozenset(config.config.stage.positions.keys())


def load_game(root: Path) -> Program:
    """Load the game folder ``root`` as bootstrap does (config first, then the story)."""
    result = load_story(GamePaths(root.resolve()),
                        LoadOptions(position_names=position_names(root)))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


@functools.cache
def example_minigames() -> Mapping[str, MinigameSig]:
    """The example game's minigame signatures, as the App registers them (``load_plugins``:
    the bundled ones, ``poem_game`` included; ``game/`` has no ``minigames/`` folder). Pass
    them to ``run_headless(minigames=…)`` and ``Interpreter(minigames=…)`` for any run that
    reaches the cross-examination (F25-4) or the poem (F24-4) in ``routes/daichi.vns``;
    ``load_example`` loads with them."""
    result = load_plugins(GamePaths(EXAMPLE.resolve()), dev=False)
    assert result.ok and "poem_game" in result.signatures()
    return result.signatures()


def load_example() -> LoadResult:
    """The example game ``game/`` loaded as bootstrap does: its ``config.toml`` names a
    position the story uses (F04 step 8), so ``load_story`` alone would give E120; the
    minigame signatures (``example_minigames``) are checked against its ``minigame`` line."""
    return load_story(GamePaths(EXAMPLE.resolve()),
                      LoadOptions(position_names=position_names(EXAMPLE),
                                  minigames=example_minigames()))


def write_game(root: Path, files: dict[str, str], config: str = TEMPLATE_CONFIG) -> Path:
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(config, encoding="utf-8")
    for name, text in files.items():
        (script / name).write_bytes(text.encode("utf-8"))
    return root


def template_game(root: Path, *, S: str | None = None, T: str | None = None,
                  replace: dict[int, str] | None = None) -> Program:
    """Template S (§0.4) with the row's edit, loaded."""
    write_game(root, {"main.vns": template_s(S=S, T=T, replace=replace)})
    return load_game(root)


def story_game(root: Path, lines: list[str], *, top: str = "") -> Program:
    """``label start:`` holding ``lines`` (4 spaces each), with the template's defines and
    ``config.toml``; ``top`` goes before the label."""
    text = ('define hana = Character("Hana")\n'
            'define d = Character("Daichi", image_tag="daichi")\n'
            f"{top}label start:\n" + "".join(f"    {line}\n" for line in lines))
    write_game(root, {"main.vns": text})
    return load_game(root)


def lanterns(root: Path) -> Program:
    """``tests/fixtures/F04/lanterns/`` copied to ``root`` and loaded."""
    shutil.copytree(F04 / "lanterns", root)
    return load_game(root)


def run_h(program: Program, images=IMG, **kwargs) -> list[Command]:
    """Run H: ``run_headless(program, seed=42, image_files=images)``."""
    return run_headless(program, seed=42, image_files=images, **kwargs)


def launched(program: Program, **kwargs) -> Interpreter:
    launch = run_launch(program)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, **kwargs)


# --- Commands -------------------------------------------------------------------------------

def stages(commands) -> list[StageState]:
    """§0.5's stage sequence."""
    return [c.stage for c in commands if type(c) is ShowStage]


# F08: audio commands come before their line in the same burst (F08 07 I-2).
_LEADING = frozenset((ShowStage, PrefetchImages, AudioRestore, EndVoice, PlayMusic, PlaySound,
                      PlayVoice, QueueMusic, StopMusic, StopSound, StopVoice))


_AUDIO = _LEADING - {ShowStage, PrefetchImages}
AUDIO_COMMANDS: frozenset[type] = _AUDIO        # F08's command types, for a test's router


def no_audio(commands) -> list[Command]:
    """``commands`` without F08's audio commands, for tests about the stage only."""
    return [c for c in commands if type(c) not in _AUDIO]


def bursts(commands) -> list[list[Command]]:
    """The commands split after each checkpoint command (a ``Say``) and after ``StoryEnded``
    or ``StoryFailed``; a trailing ``PrefetchImages`` stays with its line, and F08's audio
    commands go with the line they come before."""
    out: list[list[Command]] = [[]]
    for c in commands:
        if type(c) is PrefetchImages and len(out) > 1 and not out[-1]:
            out[-2].append(c)
            continue
        out[-1].append(c)
        if type(c) not in _LEADING:
            out.append([])
    return [b for b in out if b]


# --- Stage notation (§0.5) ------------------------------------------------------------------

_SPRITE_RE = re.compile(
    r"(?:(?P<tag>\w+)=)?(?P<image>\w+(?: \w+)*?)@(?P<at>\([^)]*\)|\w+)"
    r"(?P<mods>(?: L-?\d+| z[\d.]+| flip)*)")


def _number(text: str) -> int | float:
    return float(text) if "." in text else int(text)


def stage(text: str) -> StageState:
    """``<background> | <sprite>, …`` → ``StageState``; ``∅`` is no background."""
    background, _, rest = text.partition("|")
    background = background.strip()
    sprites = []
    for m in _SPRITE_RE.finditer(rest):
        image = m["image"]
        at = m["at"]
        position = (tuple(_number(x.strip()) for x in at[1:-1].split(","))
                    if at.startswith("(") else at)
        layer, zoom, flip = 0, 1.0, False
        for mod in m["mods"].split():
            if mod == "flip":
                flip = True
            elif mod.startswith("L"):
                layer = int(mod[1:])
            else:
                zoom = float(mod[1:])
        sprites.append(SpriteState(m["tag"] or image.split(" ")[0], image, position, layer,
                                   zoom, flip))
    return StageState(None if background in ("∅", "") else background, tuple(sprites))


def same_types(a: StageState, b: StageState) -> bool:
    """Equal, with identical number types at every position and zoom (TR-F04-02)."""
    if a != b or len(a.sprites) != len(b.sprites):
        return False
    for x, y in zip(a.sprites, b.sprites):
        if type(x.at) is not type(y.at) or type(x.zoom) is not type(y.zoom):
            return False
        if type(x.at) is tuple and [type(v) for v in x.at] != [type(v) for v in y.at]:
            return False
    return True
