"""The F14 rollback bench story ``steps100/`` (06-acceptance §5, AC-F14-34, 35, 36). Stdlib only.

``python -m tests.fixtures.F14.perf.gen_steps [DEST]`` writes ``DEST/script/main.vns``
(default ``tests/fixtures/F14/perf/steps100``, gitignored; the tests write their own copy
under ``tmp_path``): one ``default`` per variable of F03's ``gen_vars.py --n 1000 --seed 5``
(1,000 variables, ``json.dumps`` 100 KB ± 5 KB), then ``label start:`` with 101 lines, each
after one ``$`` that changes one generated variable, then ``return``. Every checkpoint so
freezes the whole 100 KB of variables, and a depth-100 timeline holds 101 such states at the
last line.

``write(dest, variables=…, lines=…)`` makes a smaller story of the same shape for the
default-tier counts (AC-F14-35's CI count).
"""

import argparse
import sys
from pathlib import Path

from tests.fixtures.F03.perf.gen_vars import generate

HERE = Path(__file__).resolve().parent
DEFAULT_DEST = HERE / "steps100"
LINES = 101


def changed(i: int, n: int) -> int:
    """The generated variable the ``$`` before line ``i`` (1-based) sets: a stride of 7
    (coprime with 1,000), so the first 101 lines touch 101 different variables."""
    return (i - 1) * 7 % n


def script(variables: dict, lines: int = LINES) -> str:
    names = list(variables)
    out = ["# Written by tests/fixtures/F14/perf/gen_steps.py (F14 06 §5). Don't edit.", ""]
    out += [f"default {name} = {value!r}" for name, value in variables.items()]
    out += ["", "label start:"]
    for i in range(1, lines + 1):
        out.append(f"    $ {names[changed(i, len(names))]} = {i}")
        out.append(f'    "Line {i}."')
    out += ["    return", ""]
    return "\n".join(out)


def write(dest: Path, *, variables: dict | None = None, lines: int = LINES) -> Path:
    """Write ``dest/script/main.vns`` (the default: the 1,000 benchmark variables and 101
    lines) and return ``dest``."""
    if variables is None:
        variables = generate(1000, 5)
    folder = dest / "script"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.vns").write_text(script(variables, lines), encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dest", nargs="?", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    print(write(args.dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
