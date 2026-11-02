"""Fuzzing the load (F02 checklist step 11; ``04-technical.md`` §14): AC-F02-55.

Each case starts from the ``compat/`` corpus (06 §5.8) and applies 1–5 mutations drawn
from ``random.Random(20261101 + i)``: a random byte inserted, deleted, or flipped; truncation;
duplicated or deleted lines; deep nesting; a 12,000-character line; random Unicode from every
plane (surrogate-range bytes, U+FEFF, and bidi controls included); and random indentation
changes. One of the three files is mutated per case. Every case must end in a ``LoadResult``
within 2 s, with no exception and no ``Traceback`` on stderr, and loading it twice must give
identical results.

The cases run in chunks of 100, so a failure names its chunk. The default run takes chunk 0
(100 cases, which already hit every mutation kind by case 17); chunks 1–9 are ``slow``, and CI
runs them in their own step (``.github/workflows/ci.yml``), so every CI run still loads the
AC's 1,000 cases. The 10,000 cases of the release run are ``slow`` too (06 §0.3; ``-m slow``
runs all of them). A failing case is re-run with
``.venv/Scripts/python -m tests.script.test_fuzz CASE`` (it prints the mutations and the
result).
"""

import json
import random
import sys
import time
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import LoadResult, load_story
from tests.script.helpers import FIXTURES

SEED = 20261101
COMPAT = FIXTURES / "compat"
FILES = ("main.vns", "part.vns", "tabs/t.vns")
CASE_SECONDS = 2.0
BIDI = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f"


def _base() -> dict[str, bytes]:
    return {name: (COMPAT / name).read_bytes() for name in FILES}


# --- Mutations ---------------------------------------------------------------------------

def _random_char(rng: random.Random) -> str:
    """A code point from any plane, biased toward the interesting ones."""
    pick = rng.random()
    if pick < 0.2:
        return rng.choice(BIDI + "\ufeff\u200b\u00a0\u3000\t\r\x00\x1b\u0085\u2028")
    if pick < 0.4:
        return chr(rng.randrange(0x20, 0x7f))
    plane = rng.randrange(17)
    code = plane * 0x10000 + rng.randrange(0x10000)
    if 0xD800 <= code <= 0xDFFF:
        code = 0xFFFD                        # str can't hold a lone surrogate; bytes can
    return chr(code)


def _lines(data: bytes) -> list[bytes]:
    return data.split(b"\n")


def m_byte_insert(data: bytes, rng: random.Random) -> bytes:
    at = rng.randrange(len(data) + 1)
    return data[:at] + bytes([rng.randrange(256)]) + data[at:]


def m_byte_delete(data: bytes, rng: random.Random) -> bytes:
    if not data:
        return data
    at = rng.randrange(len(data))
    return data[:at] + data[at + 1:]


def m_byte_flip(data: bytes, rng: random.Random) -> bytes:
    if not data:
        return data
    at = rng.randrange(len(data))
    return data[:at] + bytes([data[at] ^ (1 << rng.randrange(8))]) + data[at + 1:]


def m_truncate(data: bytes, rng: random.Random) -> bytes:
    return data[:rng.randrange(len(data) + 1)]


def m_duplicate_lines(data: bytes, rng: random.Random) -> bytes:
    lines = _lines(data)
    start = rng.randrange(len(lines))
    chunk = lines[start:start + rng.randint(1, 8)]
    at = rng.randrange(len(lines) + 1)
    return b"\n".join(lines[:at] + chunk * rng.randint(1, 3) + lines[at:])


def m_delete_lines(data: bytes, rng: random.Random) -> bytes:
    lines = _lines(data)
    start = rng.randrange(len(lines))
    del lines[start:start + rng.randint(1, 8)]
    return b"\n".join(lines)


def m_deep_nesting(data: bytes, rng: random.Random) -> bytes:
    depth = rng.choice((10, 49, 50, 51, 60, 200))
    unit = rng.choice((b"    ", b"\t", b" "))
    block = [unit * (k + 1) + rng.choice((b"if True:", b"if x:", b"else:", b"label q:"))
             for k in range(depth)]
    block.append(unit * (depth + 1) + b'"deep"')
    lines = _lines(data)
    at = rng.randrange(len(lines) + 1)
    return b"\n".join(lines[:at] + block + lines[at:])


def m_long_line(data: bytes, rng: random.Random) -> bytes:
    body = rng.choice((b"a", b"x ", b'\\"', "é".encode(), b"1+"))
    line = rng.choice((b'    "', b"    $ x = ", b"# ", b"    hana ")) + body * (12_000 // len(body))
    lines = _lines(data)
    at = rng.randrange(len(lines) + 1)
    return b"\n".join(lines[:at] + [line] + lines[at:])


def m_unicode(data: bytes, rng: random.Random) -> bytes:
    if rng.random() < 0.25:
        piece = bytes([0xED, rng.randrange(0xA0, 0xC0), rng.randrange(0x80, 0xC0)])
    else:
        piece = "".join(_random_char(rng) for _ in range(rng.randint(1, 4))).encode(
            "utf-8", "surrogatepass")
    at = rng.randrange(len(data) + 1)
    return data[:at] + piece + data[at:]


def m_indentation(data: bytes, rng: random.Random) -> bytes:
    lines = _lines(data)
    for _ in range(rng.randint(1, 5)):
        k = rng.randrange(len(lines))
        stripped = lines[k].lstrip(b" \t")
        lines[k] = rng.choice((b"", b" ", b"  ", b"\t", b"    " * rng.randint(1, 4),
                               b" \t", "\u00a0".encode(), "\u3000".encode())) + stripped
    return b"\n".join(lines)


MUTATIONS = (m_byte_insert, m_byte_delete, m_byte_flip, m_truncate, m_duplicate_lines,
             m_delete_lines, m_deep_nesting, m_long_line, m_unicode, m_indentation)


def make_case(index: int, base: dict[str, bytes]) -> tuple[dict[str, bytes], list[str]]:
    """Case ``index``: the corpus with one file mutated; also the mutation names."""
    rng = random.Random(SEED + index)
    files = dict(base)
    name = rng.choice(FILES)
    data = files[name]
    done = []
    for _ in range(rng.randint(1, 5)):
        mutation = rng.choice(MUTATIONS)
        data = mutation(data, rng)
        done.append(f"{name}:{mutation.__name__}")
    files[name] = data
    return files, done


# --- Running a case ----------------------------------------------------------------------

def snapshot(result: LoadResult) -> str:
    """Everything a load produces except its wall time."""
    program = result.program
    data: dict[str, object] = {
        "errors": [e.format() for e in result.errors],
        "error_count": result.error_count,
        "checks_skipped": result.checks_skipped,
        "no_story": result.no_story,
        "warnings": [w.format() for w in result.warnings],
    }
    if program is not None:
        data["program"] = {
            "files": [f.ref for f in program.files],
            "sids": [s.sid for s in program.iter_statements()],
            "defines": [d.sid for d in program.defines],
            "stats": [program.stats.files, program.stats.labels, program.stats.statements,
                      program.stats.words],
        }
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


class Folder:
    """One game folder reused by every case: only the files that differ are rewritten. The
    cases never add or remove a file, so one ``GamePaths`` (whose listing cache holds no file
    contents or sizes) serves them all, as one serves a whole launch."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.written: dict[str, bytes] = {}
        self._paths: GamePaths | None = None

    def paths(self, files: dict[str, bytes]) -> GamePaths:
        for name, data in files.items():
            if self.written.get(name) != data:
                path = self.root / "script" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                self.written[name] = data
        if self._paths is None:
            self._paths = GamePaths(self.root.resolve())
        return self._paths


def run_case(index: int, base: dict[str, bytes], folder: Folder) -> tuple[float, str]:
    """Load case ``index`` twice; returns the longer load time and the snapshot. Raises
    AssertionError if the two loads differ."""
    files, done = make_case(index, base)
    times, snaps = [], []
    for _ in range(2):
        paths = folder.paths(files)
        start = time.perf_counter()
        result = load_story(paths)
        times.append(time.perf_counter() - start)
        assert isinstance(result, LoadResult)
        snaps.append(snapshot(result))
    assert snaps[0] == snaps[1], (index, done)
    return max(times), snaps[0]


def _run_range(cases: range, tmp_path: Path, capfd) -> list[dict]:
    """Runs the cases; returns their snapshots as dicts."""
    base = _base()
    folder = Folder(tmp_path / "game")
    slow, snaps = [], []
    for index in cases:
        seconds, snap = run_case(index, base, folder)
        snaps.append(json.loads(snap))
        if seconds > CASE_SECONDS:
            slow.append((index, round(seconds, 2), make_case(index, base)[1]))
    assert slow == []
    err = capfd.readouterr().err
    assert "Traceback" not in err, err[-2000:]
    return snaps


CHUNK = 100


FIRST = 40                    # the cases run by default (under 1 s); the rest are ``slow``


@pytest.mark.parametrize("start, stop", [
    (0, FIRST), pytest.param(FIRST, CHUNK, marks=pytest.mark.slow),
    *(pytest.param(c * CHUNK, (c + 1) * CHUNK, marks=pytest.mark.slow) for c in range(1, 10))])
def test_ac55_one_thousand_cases(start, stop, tmp_path, capfd):
    snaps = _run_range(range(start, stop), tmp_path, capfd)
    if start == 0:
        # The mutations are strong enough to break most cases, and some still load.
        first = snaps[:40]
        assert any("program" in snap for snap in first)
        assert sum(snap["error_count"] > 0 for snap in first) > 15


@pytest.mark.slow
@pytest.mark.parametrize("chunk", range(10, 100))
def test_ac55_ten_thousand_cases(chunk, tmp_path, capfd):
    _run_range(range(chunk * CHUNK, (chunk + 1) * CHUNK), tmp_path, capfd)


def test_ac55_mutations_are_deterministic_and_varied():
    base = _base()
    assert make_case(7, base) == make_case(7, base)
    kinds = {name.split(":")[1] for i in range(300) for name in make_case(i, base)[1]}
    assert kinds == {m.__name__ for m in MUTATIONS}
    counts = {len(make_case(i, base)[1]) for i in range(300)}
    assert counts == {1, 2, 3, 4, 5}


if __name__ == "__main__":
    import tempfile

    case = int(sys.argv[1])
    with tempfile.TemporaryDirectory() as tmp:
        seconds, snap = run_case(case, _base(), Folder(Path(tmp) / "game"))
    print(make_case(case, _base())[1])
    print(f"{seconds:.3f} s")
    print(snap)
