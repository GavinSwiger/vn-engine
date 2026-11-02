"""Corpus generator for the F02 tests (``specs/F02-script-parser/06-acceptance.md`` §5.10).

Standard library only; imports nothing from ``engine``. Two forms::

    python tests/fixtures/F02/gen_corpus.py --words N --files F --seed S --out DIR [--insert K]
                                           [--defaults]
    python tests/fixtures/F02/gen_corpus.py --hostile SHAPE --n N --out DIR [--mib M]
                                           [--piece-chars C] [--last-chars L]

Both write ``DIR/script/…`` and ``DIR/corpus.json`` (words, files, labels, statements,
Python pieces, physical lines, and the SHA-256 of each file). The output is deterministic:
the same arguments give byte-identical files on every OS (LF unless the shape says
otherwise, UTF-8 without BOM, randomness only from ``random.Random(S)``, no ``hash()`` and no
set iteration order). ``DIR/script`` must not exist yet or be empty.

**Realistic corpus** (``--words N --files F``; F counts ``main.vns``): ``main.vns`` defines
``c0``…``c7``, includes ``ch001.vns``…, and holds ``label start:`` (narration lines with its
share of the words, then ``jump ch001_s001``). Each chapter file holds scene labels
``chNNN_sMMM`` (24 dialogue lines, 8 narration lines, 4 ``$`` lines, 1 if-chain, 1 ``call
chNNN_aside``, in an order shuffled per scene, then a ``jump`` to the next scene; the last
scene of the story ends with ``return``) and one ``chNNN_aside`` label (4 dialogue lines and
``return``). Texts are 6–18 words from a fixed 2,000-word list; 10% are continued over two
physical lines, 3% hold one of ``café``, ``“quoted”``, ``—``, ``日本語``, ``😀``, 2% hold a
``\\"`` escape next to a word. One comment line per 10 statements (1 in 20 is ``# TODO``).
Exactly N words over all texts (``len(text.split())``), spread evenly over the files: when a
file's lines overshoot its share, its last lines are cut (each keeps at least one word), so
a file needs at least about 100 words. ``--insert K`` adds K dialogue lines with unique
texts after statement 20 of the anchor label ``ch001_s002`` and changes no other byte
(AC-F02-58); they don't count toward N. ``--defaults`` (F03 ``06-acceptance.md`` §5.8) adds
``default vK = 0`` to ``main.vns``, after the defines, for every ``vK`` the corpus uses, so
the corpus also runs (F03); ``corpus.json`` then holds ``"defaults"``, the count. Without it
the output is byte-identical to before.

**Hostile shapes** (``--hostile SHAPE --n N``), see ``SHAPES``. ``--mib`` (default 16) is
the size of each 16-MiB file of the size shapes; tests use small values.

Extending: add an option in ``build_parser`` and a field in ``Realistic`` (or a function in
``SHAPES``); ``generate(args)`` passes the parsed namespace through.
"""

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

MIB = 1 << 20
SPEAKERS = tuple(f"c{i}" for i in range(8))
ATTRIBUTES = ("happy", "sad", "angry", "surprised", "tired", "smiling", "frowning",
              "blushing", "worried", "calm", "serious", "thinking")
SPECIAL_TOKENS = ("café", "“quoted”", "—", "日本語", "😀")
ANCHOR_LABEL = "ch001_s002"
ANCHOR_AFTER = 20                     # --insert goes after this many statements of the anchor

_ONSETS = ("b", "c", "d", "f", "g", "h", "j", "k", "l", "m", "n", "p", "r", "s", "t", "v",
           "w", "z", "br", "ch", "cl", "dr", "fl", "gr", "pl", "sh", "st", "th", "tr", "wh")
_VOWELS = ("a", "e", "i", "o", "u", "ai", "ea", "ou")
_CODAS = ("", "n", "r", "s", "t", "l", "m", "nd", "st", "p")
_UNWANTED = frozenset(("shit", "tit", "cum"))
# The fixed 2,000-word list: the first 2,000 onset + vowel + coda words in this order,
# leaving out a few that read as rude words.
WORDS: tuple[str, ...] = tuple(w for w in (o + v + c for o in _ONSETS for v in _VOWELS
                                           for c in _CODAS) if w not in _UNWANTED)[:2000]
assert len(WORDS) == len(set(WORDS)) == 2000


# --- Output ------------------------------------------------------------------------------

@dataclass
class Corpus:
    """Files written so far and the counts that go into ``corpus.json``."""

    out: Path
    words: int = 0
    labels: int = 0
    statements: int = 0
    python_pieces: int = 0
    physical_lines: int = 0
    sha256: dict[str, str] = field(default_factory=dict)
    variables: set[int] = field(default_factory=set)     # K of every vK used (--defaults)

    @property
    def script(self) -> Path:
        return self.out / "script"

    def write(self, rel: str, text: str) -> None:
        data = text.encode("utf-8")
        path = self.script / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.sha256[rel] = hashlib.sha256(data).hexdigest()
        lines = data.count(b"\n") + data.count(b"\r") - data.count(b"\r\n")
        if data and not data.endswith((b"\n", b"\r")):
            lines += 1
        self.physical_lines += lines

    def finish(self, **extra: object) -> dict:
        info = {"words": self.words, "files": len(self.sha256), "labels": self.labels,
                "statements": self.statements, "python_pieces": self.python_pieces,
                "physical_lines": self.physical_lines,
                "sha256": dict(sorted(self.sha256.items())), **extra}
        (self.out / "corpus.json").write_text(
            json.dumps(info, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")
        return info


def _prepare(out: Path) -> Corpus:
    script = out / "script"
    if script.exists() and any(script.iterdir()):
        raise SystemExit(f"{script} is not empty; choose a new --out folder")
    script.mkdir(parents=True, exist_ok=True)
    return Corpus(out)


# --- Realistic corpus ------------------------------------------------------------------

@dataclass
class Realistic:
    words: int
    files: int
    seed: int
    insert: int = 0
    defaults: bool = False


@dataclass
class _Say:
    """One dialogue (``speaker`` set) or narration line and its word count."""

    speaker: str | None
    words: int


@dataclass
class _Scene:
    name: str
    items: list = field(default_factory=list)     # _Say | ("py",) | ("call",) | ("if", [[_Say]])
    end: str = "return"                           # "jump <label>" or "return"


def _says(scene: _Scene) -> list[_Say]:
    out: list[_Say] = []
    for item in scene.items:
        if isinstance(item, _Say):
            out.append(item)
        elif item[0] == "if":
            for branch in item[1]:
                out.extend(branch)
    return out


class _Writer:
    """Renders planned labels into lines, drawing texts from the seeded generator."""

    def __init__(self, rng: random.Random, corpus: Corpus) -> None:
        self.rng = rng
        self.corpus = corpus
        self.lines: list[str] = []
        self.since_comment = 0
        self.comments = 0

    def text(self, count: int) -> str:
        rng = self.rng
        words = [rng.choice(WORDS) for _ in range(count)]
        if rng.random() < 0.03:
            words[rng.randrange(count)] = rng.choice(SPECIAL_TOKENS)
        if rng.random() < 0.02:
            i = rng.randrange(count)
            words[i] = f'\\"{words[i]}\\"'
        return " ".join(words)

    def say(self, say: _Say, indent: int) -> None:
        rng = self.rng
        pad = " " * indent
        head = pad
        if say.speaker is not None:
            head += say.speaker
            roll = rng.random()
            if roll < 0.05:
                head += " " + " ".join(rng.sample(ATTRIBUTES, 4))
            elif roll < 0.30:
                head += " " + " ".join(rng.sample(ATTRIBUTES, rng.randint(1, 2)))
            head += " "
        words = self.text(say.words).split(" ")
        self.corpus.words += say.words
        self.corpus.statements += 1
        if len(words) >= 2 and rng.random() < 0.10:
            cut = rng.randint(1, len(words) - 1)
            self.lines.append(head + '"' + " ".join(words[:cut]))
            self.lines.append(pad + "    " + " ".join(words[cut:]) + '"')
        else:
            self.lines.append(head + '"' + " ".join(words) + '"')

    def python(self, indent: int) -> None:
        rng = self.rng
        pad = " " * indent
        k = rng.randrange(8)
        self.corpus.variables.add(k)
        if rng.random() < 1 / 8:
            self.lines.extend([f"{pad}$ v{k} = (v{k}", f"{pad}    + 1", f"{pad}    )"])
        else:
            self.lines.append(f"{pad}$ v{k} = v{k} + 1")
        self.corpus.statements += 1
        self.corpus.python_pieces += 1

    def counted(self, statements: int) -> None:
        """One comment line per 10 statements, at the label body's indentation."""
        self.since_comment += statements
        while self.since_comment >= 10:
            self.since_comment -= 10
            self.comments += 1
            words = " ".join(self.rng.choice(WORDS) for _ in range(3))
            kind = "TODO" if self.comments % 20 == 0 else "note"
            self.lines.append(f"    # {kind} {words}")

    def scene(self, scene: _Scene, aside: str, insert: int) -> None:
        self.lines.append(f"label {scene.name}:")
        self.corpus.labels += 1
        for index, item in enumerate(scene.items, 1):
            if isinstance(item, _Say):
                self.say(item, 4)
                self.counted(1)
            elif item[0] == "py":
                self.python(4)
                self.counted(1)
            elif item[0] == "call":
                self.lines.append(f"    call {aside}")
                self.corpus.statements += 1
                self.counted(1)
            else:
                branches = item[1]
                conditions = ("if v1 > 2:", "elif v2:", "else:")
                self.corpus.variables.update((1, 2))
                for keyword, branch in zip(conditions, branches):
                    self.lines.append("    " + keyword)
                    for say in branch:
                        self.say(say, 8)
                self.corpus.statements += 1
                self.corpus.python_pieces += 2
                self.counted(1 + sum(len(b) for b in branches))
            if insert and scene.name == ANCHOR_LABEL and index == ANCHOR_AFTER:
                for i in range(1, insert + 1):
                    self.lines.append(f'    c0 "inserted line {i} of the anchor scene"')
                    self.corpus.words += 6
                    self.corpus.statements += 1
        self.lines.append(f"    {scene.end}")
        self.corpus.statements += 1
        self.lines.append("")


def _plan_scene(rng: random.Random, name: str) -> _Scene:
    kinds = ["say"] * 24 + ["narration"] * 8 + ["py"] * 4 + ["if", "call"]
    rng.shuffle(kinds)
    scene = _Scene(name)
    for kind in kinds:
        if kind == "say":
            scene.items.append(_Say(rng.choice(SPEAKERS), rng.randint(6, 18)))
        elif kind == "narration":
            scene.items.append(_Say(None, rng.randint(6, 18)))
        elif kind == "if":
            branches = [[_Say(rng.choice(SPEAKERS), rng.randint(6, 18))
                         for _ in range(rng.randint(1, 2))] for _ in range(3)]
            scene.items.append(("if", branches))
        else:
            scene.items.append((kind,))
    return scene


def _cut(says: list[_Say], budget: int, where: str) -> None:
    """Lower the word counts from the last line backwards until they add up to ``budget``
    (each line keeps at least one word)."""
    excess = sum(s.words for s in says) - budget
    for say in reversed(says):
        if excess <= 0:
            break
        take = min(excess, say.words - 1)
        say.words -= take
        excess -= take
    if excess > 0:
        raise SystemExit(f"{where}: too few words for its lines; use more --words or fewer "
                         "--files")


def realistic(opts: Realistic, out: Path) -> dict:
    if opts.words < 0 or opts.files < 1:
        raise SystemExit("--words must be ≥ 0 and --files ≥ 1")
    corpus = _prepare(out)
    rng = random.Random(opts.seed)
    shares = [opts.words // opts.files] * opts.files
    for i in range(opts.words % opts.files):
        shares[i] += 1
    chapters = [f"ch{i:03d}" for i in range(1, opts.files)]

    # Plan every chapter first (scene structure and word counts), then render.
    plans: list[tuple[str, list[_Scene], _Scene]] = []
    for chapter, budget in zip(chapters, shares[1:]):
        aside = _Scene(f"{chapter}_aside",
                       [_Say(rng.choice(SPEAKERS), rng.randint(6, 18)) for _ in range(4)])
        scenes: list[_Scene] = []
        total = sum(s.words for s in _says(aside))
        while total < budget or not scenes:
            scene = _plan_scene(rng, f"{chapter}_s{len(scenes) + 1:03d}")
            scenes.append(scene)
            total += sum(s.words for s in _says(scene))
        says = [s for scene in scenes for s in _says(scene)] + _says(aside)
        _cut(says, budget, f"{chapter}.vns")
        plans.append((chapter, scenes, aside))
    for index, (chapter, scenes, _aside) in enumerate(plans):
        for number, scene in enumerate(scenes):
            if number + 1 < len(scenes):
                scene.end = f"jump {scenes[number + 1].name}"
            elif index + 1 < len(plans):
                scene.end = f"jump {plans[index + 1][1][0].name}"
    if opts.insert and not any(s.name == ANCHOR_LABEL for _, ss, _ in plans for s in ss):
        raise SystemExit(f"--insert needs the anchor label {ANCHOR_LABEL}; use more --words")

    # main.vns
    lines = [f'define {c} = Character("Name {i}")' for i, c in enumerate(SPEAKERS)]
    corpus.python_pieces += len(SPEAKERS)
    lines += [f'include "{chapter}.vns"' for chapter in chapters]
    lines += ["", "label start:"]
    corpus.labels += 1
    main = _Writer(rng, corpus)
    left = shares[0]
    while left > 0:
        count = min(rng.randint(6, 18), left)
        main.say(_Say(None, count), 4)
        left -= count
    lines += main.lines
    lines.append(f"    jump {plans[0][1][0].name}" if plans else "    return")
    corpus.statements += 1

    chapter_texts: list[tuple[str, str]] = []
    for chapter, scenes, aside in plans:
        writer = _Writer(rng, corpus)
        for scene in scenes:
            writer.scene(scene, aside.name, opts.insert)
        writer.lines.append(f"label {aside.name}:")
        corpus.labels += 1
        for say in aside.items:
            writer.say(say, 4)
        writer.lines.append("    return")
        corpus.statements += 1
        chapter_texts.append((f"{chapter}.vns", "\n".join(writer.lines) + "\n"))

    # main.vns is written once the chapters are drawn, so --defaults knows every vK they
    # use; the drawing order (and so every random draw) is the same with or without it.
    extra: dict[str, object] = {}
    if opts.defaults:
        used = sorted(corpus.variables)
        at = len(SPEAKERS)                                # after the defines
        lines[at:at] = [f"default v{k} = 0" for k in used]
        corpus.python_pieces += len(used)
        extra["defaults"] = len(used)
    corpus.write("main.vns", "\n".join(lines) + "\n")
    for rel, text in chapter_texts:
        corpus.write(rel, text)
    return corpus.finish(seed=opts.seed, insert=opts.insert, **extra)


# --- Hostile shapes ----------------------------------------------------------------------

def _fill(header: Callable[[int], str], line: str, size: int, per_label: int) -> str:
    """Up to ``size`` bytes: ``header(k)`` then ``per_label`` copies of ``line``, repeated
    while whole lines fit (ASCII only, so characters are bytes)."""
    parts: list[str] = []
    used = 0
    k = 0
    while True:
        head = header(k)
        room = (size - used - len(head)) // len(line)
        if room <= 0:
            break
        count = min(per_label, room)
        parts.append(head)
        parts.append(line * count)
        used += len(head) + len(line) * count
        k += 1
    return "".join(parts)


def _main_including(corpus: Corpus, refs: list[str], body: str = "    return\n") -> None:
    corpus.write("main.vns", "".join(f'include "{r}"\n' for r in refs)
                 + "label start:\n" + body)
    corpus.labels += 1
    corpus.statements += body.count("\n")


def _size_shape(kind: str) -> Callable[[Corpus, argparse.Namespace], None]:
    def shape(corpus: Corpus, args: argparse.Namespace) -> None:
        size = int(args.mib * MIB)
        refs = []
        counter = [0]                     # define dN numbers run on across the files
        for f in range(args.n):
            name = f"h{f:03d}.vns"
            if kind == "defines":
                parts = []
                used = 0
                while True:
                    line = f"define d{counter[0]} = {counter[0]}\n"
                    if used + len(line) > size:
                        break
                    parts.append(line)
                    used += len(line)
                    counter[0] += 1
                text = "".join(parts)
                corpus.python_pieces += len(parts)
            else:
                line = '    $ x=1\n' if kind == "py-lines" else '    "a"\n'
                text = _fill(lambda k, f=f: f"label h{f:03d}_{k:05d}:\n", line, size, 10_000)
                count = text.count(line)
                corpus.labels += text.count("label ")
                corpus.statements += count
                if kind == "py-lines":
                    corpus.python_pieces += count
                else:
                    corpus.words += count
            corpus.write(name, text)
            refs.append(name)
        _main_including(corpus, refs)
    return shape


def py_piece(target: int, width: int = 9000) -> str:
    """One ``$`` piece's code (``x = [1,1,…]``) of exactly ``target`` characters as stored
    (``len(PyCode.source)``: continuation lines whole, joined with ``\\n``), in lines of at
    most about ``width`` characters, continued inside the brackets. No line ends in a space:
    the reader right-strips stored Python lines."""
    head, tail = "x = [", "        1]"
    rest = target - len(tail) - 1 - len(head)
    if rest < 0:
        raise SystemExit(f"a piece needs at least {len(head) + len(tail) + 1} characters")
    mids: list[str] = []
    mid = " " * 8 + "1," * ((width - 8) // 2)
    while rest > width + 1:
        mids.append(mid)
        rest -= 1 + len(mid)
    pairs, extra = divmod(rest, 2)
    if not extra:
        first = head + "1," * pairs
    elif pairs:
        first = head + "11," + "1," * (pairs - 1)
    else:
        first = "x =[1,"
    source = "\n".join([first, *mids, tail])
    assert len(source) == target
    return source


def _py_total(corpus: Corpus, args: argparse.Namespace) -> None:
    pieces = []
    for i in range(args.n):
        chars = args.last_chars if (args.last_chars is not None and i == args.n - 1) \
            else args.piece_chars
        pieces.append("    $ " + py_piece(chars) + "\n")
    corpus.python_pieces += args.n
    _main_including(corpus, [], "".join(pieces) + "    return\n")


def _repeat_in_start(line: str, *, statements: bool, python: bool = False):
    def shape(corpus: Corpus, args: argparse.Namespace) -> None:
        size = int(args.mib * MIB)
        head = "label start:\n    return\n"
        if line.startswith("#"):
            count = (size - len(head)) // len(line)
            corpus.write("main.vns", head + line * count)
        else:
            tail = "    return\n"
            count = (size - len("label start:\n") - len(tail)) // len(line.encode())
            corpus.write("main.vns", "label start:\n" + line * count + tail)
            corpus.statements += count
            if python:
                corpus.python_pieces += count
        corpus.labels += 1
        corpus.statements += 1
    return shape


def _total_size(corpus: Corpus, args: argparse.Namespace) -> None:
    """``n`` files of ``--mib`` MiB plus ``main.vns`` add up to ``n × mib`` MiB + 1 byte."""
    size = int(args.mib * MIB)
    refs = [f"t{i:03d}.vns" for i in range(args.n)]
    main = "".join(f'include "{r}"\n' for r in refs) + "label start:\n    return\n"
    corpus.write("main.vns", main)
    corpus.labels += 1
    corpus.statements += 1
    line = "# padding\n"
    for i, ref in enumerate(refs):
        want = size - len(main) + 1 if i == len(refs) - 1 else size
        count, extra = divmod(want, len(line))
        corpus.write(ref, line * count + "#" * extra)


def _continuation(corpus, args):
    body = '    "a\n' + "        a\n" * max(args.n - 1, 0) + '        a"\n    return\n'
    _main_including(corpus, [], body)
    corpus.words += args.n + 1


def _blank(corpus, args):
    corpus.write("main.vns", "label start:\n" + "\n" * args.n + "    return\n")
    corpus.labels += 1
    corpus.statements += 1


def _cr_only(corpus, args):
    corpus.write("main.vns", "label start:\r" + '    "a"\r' * args.n + "    return\r")
    corpus.labels += 1
    corpus.statements += args.n + 1
    corpus.words += args.n


def _long_line(corpus, args):
    body = '    "' + "a" * max(args.n - 6, 1) + '"\n    return\n'
    _main_including(corpus, [], body)


def _define_cycle(corpus, args):
    n = args.n
    lines = [f"define d{k} = d{k + 1}\n" for k in range(n - 1)] + [f"define d{n - 1} = d0\n"]
    corpus.write("main.vns", "".join(lines) + "label start:\n    return\n")
    corpus.python_pieces += n
    corpus.labels += 1
    corpus.statements += 1


def _dup_labels(corpus, args):
    corpus.write("main.vns", "label start:\n    return\n" + "label a:\n    return\n" * args.n)
    corpus.labels += args.n + 1
    corpus.statements += args.n + 1


def _long_labels(corpus, args):
    prefix = "a" * 8990
    names = [f"{prefix}{i:010d}" for i in range(args.n)]
    jumps = [name[:-1] + "x" for name in names[:50]]
    text = ["label start:\n"] + [f"    jump {j}\n" for j in jumps] + ["    return\n"]
    text += [f"label {name}:\n    return\n" for name in names]
    corpus.write("main.vns", "".join(text))
    corpus.labels += args.n + 1
    corpus.statements += len(jumps) + 1 + args.n


def _nested_if(corpus, args):
    lines = ["label start:"]
    for depth in range(args.n):
        lines.append(" " * (4 * (depth + 1)) + "if True:")
    lines.append(" " * (4 * (args.n + 1)) + '"a"')
    lines.append("    return")
    corpus.write("main.vns", "\n".join(lines) + "\n")
    corpus.labels += 1
    corpus.statements += args.n + 2
    corpus.python_pieces += args.n


def _bad_lines(corpus, args):
    corpus.write("main.vns", "label start:\n" + "    1.\n" * args.n + "    return\n")
    corpus.labels += 1
    corpus.statements += 1


def _many_files(corpus, args):
    refs = [f"f{i:04d}.vns" for i in range(1, args.n + 1)]
    for i, ref in enumerate(refs, 1):
        corpus.write(ref, f"label f{i:04d}:\n    return\n")
    corpus.labels += args.n
    corpus.statements += args.n
    _main_including(corpus, refs)


def _chain(corpus, args):
    width = max(2, len(str(args.n)))
    refs = [f"c/f{i:0{width}d}.vns" for i in range(1, args.n + 1)]
    for i, ref in enumerate(refs):
        nxt = f'include "{refs[i + 1]}"\n' if i + 1 < len(refs) else ""
        corpus.write(ref, f"{nxt}label c{i + 1:0{width}d}:\n    return\n")
    corpus.labels += args.n
    corpus.statements += args.n
    _main_including(corpus, refs[:1])


# Shape → (generator, AC). ``--n`` is the file count for the size shapes, the piece count
# for py-total, and the line / name / depth count for the others.
SHAPES: dict[str, Callable[[Corpus, argparse.Namespace], None]] = {
    "py-lines": _size_shape("py-lines"),
    "narration": _size_shape("narration"),
    "defines": _size_shape("defines"),
    "py-total": _py_total,
    "todo": _repeat_in_start("# TODO x\n", statements=False),
    "escape-warn": _repeat_in_start('    $ x = "\\d"\n', statements=True, python=True),
    "total-size": _total_size,
    "continuation": _continuation,
    "blank": _blank,
    "cr-only": _cr_only,
    "long-line": _long_line,
    "define-cycle": _define_cycle,
    "dup-labels": _dup_labels,
    "long-labels": _long_labels,
    "nested-if": _nested_if,
    "bad-lines": _bad_lines,
    "many-files": _many_files,
    "chain": _chain,
}


def hostile(args: argparse.Namespace, out: Path) -> dict:
    corpus = _prepare(out)
    SHAPES[args.hostile](corpus, args)
    return corpus.finish(shape=args.hostile, n=args.n)


# --- Command line ------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an F02 test corpus.")
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--words", type=int, help="realistic corpus: total words")
    kind.add_argument("--hostile", choices=sorted(SHAPES), help="hostile shape")
    parser.add_argument("--files", type=int, default=10, help="realistic: files incl. main.vns")
    parser.add_argument("--seed", type=int, default=0, help="realistic: random.Random seed")
    parser.add_argument("--insert", type=int, default=0,
                        help=f"realistic: K dialogue lines after statement {ANCHOR_AFTER} "
                             f"of {ANCHOR_LABEL}")
    parser.add_argument("--defaults", action="store_true",
                        help="realistic: add default vK = 0 for every vK used (F03)")
    parser.add_argument("--n", type=int, default=16, help="hostile: size parameter")
    parser.add_argument("--mib", type=float, default=16,
                        help="hostile size shapes: MiB per file (default 16)")
    parser.add_argument("--piece-chars", type=int, default=99_000,
                        help="py-total: characters per piece")
    parser.add_argument("--last-chars", type=int, default=None,
                        help="py-total: characters of the last piece")
    parser.add_argument("--out", type=Path, required=True, help="output folder")
    return parser


def generate(args: argparse.Namespace) -> dict:
    """Write the corpus the parsed ``args`` describe; returns ``corpus.json``'s content."""
    if args.words is not None:
        return realistic(Realistic(args.words, args.files, args.seed, args.insert,
                                   args.defaults), args.out)
    return hostile(args, args.out)


def main(argv: list[str] | None = None) -> int:
    generate(build_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
