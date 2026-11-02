"""Story variables for the snapshot benchmark (06-acceptance §5.7, AC-F03-76). Stdlib only.

``python -m tests.fixtures.F03.perf.gen_vars --n 1000 --seed 5`` prints the JSON object.
60% scalars by count (ints within ±10**6, floats, text of 20-40 characters, bools, None),
30% lists of 15 texts of 12-20 characters, 10% dicts of 8 text keys each holding a list of
5 ints. Text lengths are then scaled until ``json.dumps`` is 100 KB ± 5 KB (1 KB = 1,024
bytes), and that is asserted.
"""

import argparse
import json
import random

TARGET = 100 * 1024
TOLERANCE = 5 * 1024


def _text(rng: random.Random, lo: int, hi: int, scale: float) -> str:
    n = max(1, round(rng.randint(lo, hi) * scale))
    return "".join(rng.choice("abcdefghijklmnopqrstuvwxyz ") for _ in range(n))


def _generate(n: int, seed: int, scale: float) -> dict:
    rng = random.Random(seed)
    out: dict = {}
    for i in range(n):
        roll = rng.random()
        if roll < 0.6:
            kind = rng.randrange(5)
            value = (rng.randint(-10**6, 10**6), rng.uniform(-1e6, 1e6),
                     _text(rng, 20, 40, scale), rng.random() < 0.5, None)[kind]
        elif roll < 0.9:
            value = [_text(rng, 12, 20, scale) for _ in range(15)]
        else:
            value = {f"key{j}": [rng.randint(0, 999) for _ in range(5)] for j in range(8)}
        out[f"var{i}"] = value
    return out


def generate(n: int = 1000, seed: int = 5) -> dict:
    """The variables, with ``json.dumps`` size within 100 KB ± 5 KB."""
    scale = 1.0
    for _ in range(40):
        variables = _generate(n, seed, scale)
        size = len(json.dumps(variables))
        if abs(size - TARGET) <= TOLERANCE:
            return variables
        scale *= TARGET / size
    raise AssertionError(f"gen_vars: could not reach 100 KB ± 5 KB (last size {size})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(generate(args.n, args.seed)))


if __name__ == "__main__":
    main()
