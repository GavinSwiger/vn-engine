"""The F11 bench save (``06`` §5 "Bench"): a long playthrough's state, saved as this build
writes it, with a seeded uniform-noise thumbnail (``noise.png`` of ``06`` §5, 320×180, the
JPEG encoder's hardest picture). AC-F11-66 checks a 10-hour save stays under 1 MiB.

``--hours N`` scales a playthrough: 30 story variables and 60 menu picks (choice texts of 40
characters) per hour, F13's history at its cap (250 entries) from the fourth hour, and always
4 sprites, the music, and two looping sounds. The state is built as JSON and checked by
``GameState.from_json``, so it is a state the engine would load::

    .venv/Scripts/python -m tests.persist.gen_save_bench --hours 10 --out bench.vnsave

prints the file's size. Step 13 adds the ``--state-bytes`` and ``--legit-worst`` shapes.
"""

import argparse
import random
from pathlib import Path

import pygame

from engine.persist import saves
from engine.render.thumbnail import encode_jpeg
from engine.runtime.history import HISTORY_MAX
from engine.runtime.state import GameState

SEED = 1
GAME_ID = "f11-bench"
SAVED_AT = 1_793_567_040
WORDS = ("lantern", "river", "bridge", "festival", "paper", "wish", "shrine", "drum",
         "firework", "moon", "stall", "ribbon", "summer", "night", "water", "cousin")


def _sid(rng: random.Random, label: str) -> str:
    return f"{label}/{rng.getrandbits(48):012x}"


def _text(rng: random.Random, length: int) -> str:
    """Words up to exactly ``length`` characters."""
    out = ""
    while len(out) < length:
        out += rng.choice(WORDS) + " "
    return out[:length - 1].rstrip() + "."


def _value(rng: random.Random, i: int) -> object:
    kind = i % 5
    if kind == 0:
        return rng.randrange(-1000, 1000)
    if kind == 1:
        return rng.random() < 0.5
    if kind == 2:
        return _text(rng, rng.randrange(8, 40))
    if kind == 3:
        return [rng.randrange(100) for _ in range(rng.randrange(1, 8))]
    return {"seen": rng.random() < 0.5, "count": rng.randrange(20),
            "name": rng.choice(WORDS)}


def bench_json(hours: int, *, seed: int = SEED) -> dict:
    """The state's JSON (``GameState.to_json`` form) after ``hours`` of play."""
    rng = random.Random(seed)
    labels = [f"scene_{n:03d}" for n in range(40)]
    picks = [{"menu": _sid(rng, rng.choice(labels)), "choice": f"{rng.getrandbits(48):012x}",
              "text": _text(rng, 40), "question": _text(rng, 60)}
             for _ in range(60 * hours)]
    history = []
    for _ in range(min(HISTORY_MAX, 70 * hours)):
        if rng.random() < 0.1:
            history.append({"kind": "choice", "sid": _sid(rng, rng.choice(labels)), "name": "",
                            "text": _text(rng, 40)})
        else:
            history.append({"kind": "line", "sid": _sid(rng, rng.choice(labels)),
                            "name": rng.choice(("", "Hana", "Daichi")),
                            "text": _text(rng, rng.randrange(40, 160))})
    sprites = [{"tag": tag, "image": f"{tag} smile", "at": at, "layer": 0, "zoom": 1.0,
                "flip": False}
               for tag, at in (("hana", "left"), ("daichi", "right"), ("aiko", "center"),
                               ("ren", [900]))]
    return {
        "format": 1,
        "identity_scheme": 1,
        "position": {"sid": _sid(rng, "scene_039"), "at": ["scene_039", [12]]},
        "call_stack": [{"sid": _sid(rng, "scene_020"), "at": ["scene_020", [3]]}],
        "variables": {f"var_{i:03d}": _value(rng, i) for i in range(30 * hours)},
        "dice": f"{rng.getrandbits(64):016x}",
        "stage": {"background": "bg bridge_night", "sprites": sprites},
        "audio": {"music": [{"file": "bgm/bridge_night.ogg", "loop": True, "volume": 100}],
                  "sounds": [{"file": "sfx/river.ogg", "volume": 40},
                             {"file": "sfx/crowd.ogg", "volume": 60}]},
        "choices": {"picks": picks, "waiting": None},
        "history": {"entries": history},
    }


def bench_state(hours: int, *, seed: int = SEED) -> GameState:
    return GameState.from_json(bench_json(hours, seed=seed))


def noise_jpeg(seed: int = SEED) -> bytes:
    """The seeded uniform-noise thumbnail through the engine's encoder."""
    rng = random.Random(seed)
    surface = pygame.Surface((320, 180), 0, 24)
    surface.get_buffer().write(rng.randbytes(surface.get_pitch() * 180))
    jpeg = encode_jpeg(surface)
    assert jpeg is not None, "the noise thumbnail was refused"
    return jpeg


def bench_save(hours: int, *, seed: int = SEED) -> bytes:
    """The save file's bytes, as ``SaveEncoder`` writes them."""
    state = bench_state(hours, seed=seed)
    result = saves.encode_save(state, seq=1, saved_at=SAVED_AT,
                               description=saves.describe(state, None), chapter=None,
                               game=GAME_ID, game_version="1.0", jpeg=noise_jpeg(seed))
    assert not isinstance(result, saves.TooLarge), result
    return b"".join(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=int, required=True)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    data = bench_save(args.hours, seed=args.seed)
    if args.out is not None:
        args.out.write_bytes(data)
    print(f"{args.hours}-hour save: {len(data):,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
