"""Helpers for the F02 script tests: template T and its row notation (06 §0.4), and a
single-file parse that stands in for ``load_story`` until the loader exists (checklist
steps 1–5 test the AC rows through unit tests, SPEC.md §6). F03's template R (F03
``06-acceptance.md`` §0.4) is ``template_r``; F05's template X (F05 ``06-acceptance.md``
§0.4) is ``template_x``; F04's template S (F04 ``06-acceptance.md`` §0.4) is ``template_s``;
F08's template A (F08 ``06-acceptance.md`` §0.4) is ``template_a``; F12's template P (F12
``06-acceptance.md`` §0.4) is ``template_p``; F17's template N (F17 ``06-acceptance.md`` §0.4)
is ``template_n``; F19's template R (F19 ``06-acceptance.md`` §0.4) is ``template_e``; F21's
template C (F21 ``06-acceptance.md`` §0.4) is ``template_c``.
"""

import json
import re
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

from engine.script.diagnostics import DiagnosticSink, ScriptError
from engine.script.nodes import If, IfBranch, Label, Node, PyCode, ScriptFile
from engine.script.parser import parse_file
from engine.script.source import decode_script
from engine.script.statements import ParseContext, resolve_no_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F02"
F03_TEMPLATE = FIXTURES.parent / "F03" / "template" / "main.vns"
F05_TEMPLATE = FIXTURES.parent / "F05" / "template" / "script" / "main.vns"
F04_TEMPLATE_DIR = FIXTURES.parent / "F04" / "template"
F04_TEMPLATE = F04_TEMPLATE_DIR / "script" / "main.vns"
F08_TEMPLATE_DIR = FIXTURES.parent / "F08" / "template"
F08_TEMPLATE = F08_TEMPLATE_DIR / "script" / "main.vns"
F07_TEMPLATE_DIR = FIXTURES.parent / "F07" / "template"
F07_TEMPLATE = F07_TEMPLATE_DIR / "script" / "main.vns"
F12_TEMPLATE_DIR = FIXTURES.parent / "F12" / "template"
F12_TEMPLATE = F12_TEMPLATE_DIR / "script" / "main.vns"
F09_TEMPLATE_DIR = FIXTURES.parent / "F09" / "template"
F09_TEMPLATE = F09_TEMPLATE_DIR / "script" / "main.vns"
F17_TEMPLATE_DIR = FIXTURES.parent / "F17" / "template"
F17_TEMPLATE = F17_TEMPLATE_DIR / "script" / "main.vns"
F19_TEMPLATE_DIR = FIXTURES.parent / "F19" / "template"
F19_TEMPLATE = F19_TEMPLATE_DIR / "script" / "main.vns"
F21_TEMPLATE = FIXTURES.parent / "F21" / "template" / "script" / "main.vns"
F23_TEMPLATE = FIXTURES.parent / "F23" / "template" / "script" / "main.vns"
F20_TEMPLATE_DIR = FIXTURES.parent / "F20" / "template"
F20_TEMPLATE = F20_TEMPLATE_DIR / "script" / "main.vns"
F28_TEMPLATE = FIXTURES.parent / "F28" / "template" / "script" / "main.vns"
F30_TEMPLATE_DIR = FIXTURES.parent / "F30" / "template"
F30_TEMPLATE = F30_TEMPLATE_DIR / "script" / "main.vns"
F32_TEMPLATE_DIR = FIXTURES.parent / "F32" / "template"
F32_TEMPLATE = F32_TEMPLATE_DIR / "script" / "main.vns"

# Template T (06 §0.4); "<S>" and "<T>" are the row slots.
TEMPLATE = [
    'define hana = Character("Hana")',
    'define daichi = Character("Daichi")',
    "label start:",
    '    "Start."',
    "    <S>",
    "    jump bridge",
    "label bridge:",
    "    return",
    "<T>",
]

_INDENT_RE = re.compile(r"^((?:\[\d+\]|\[t\])+)")
_CODEPOINT_RE = re.compile(r"\{U\+([0-9A-Fa-f]{4,6})\}")


def expand(row: str) -> str:
    """Row notation → text: ``⏎`` new line, ``[n]``/``[t]`` indentation at a line start,
    ``{U+XXXX}`` the raw character, ``{TAB}`` a tab."""
    row = _CODEPOINT_RE.sub(lambda m: chr(int(m.group(1), 16)), row).replace("{TAB}", "\t")
    lines = []
    for line in row.split("⏎"):
        match = _INDENT_RE.match(line)
        if match is not None:
            marks = re.findall(r"\[(\d+|t)\]", match.group(1))
            indent = "".join("\t" if m == "t" else " " * int(m) for m in marks)
            line = indent + line[match.end():]
        lines.append(line)
    return "\n".join(lines)


def template(*, S: str | None = None, T: str | None = None,
             replace: dict[int, str] | None = None) -> str:
    """Template T with the row's edit. ``replace`` maps a 1-based line to its new text
    (notation applies; ``R3: x`` is ``replace={3: x}``, ``line 5 = x`` is ``{5: x}``)."""
    lines = list(TEMPLATE)
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            # An unused S line stays as a blank line, so T rows keep line 9 (06 §0.4).
            out.append("    " + expand(S) if S is not None else "")
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_r(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F03's template R (``tests/fixtures/F03/template/main.vns``) with the row's edit:
    **S** goes on line 8 after 4 spaces, **T** on line 11; an unused S line becomes
    ``    # -`` and an unused T line is removed (F03 06 §0.4). ``replace`` as ``template``."""
    lines = F03_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            out.append("    " + expand(S) if S is not None else "    # -")
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_p(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F12's template P (``tests/fixtures/F12/template/script/main.vns``, F12 06 §0.4) with
    the row's edit: **S** goes on line 7 after 4 spaces, **T** on line 10; an unused S line
    becomes ``    # -`` and an unused T line is removed. ``replace`` (**Rn**) as
    ``template``."""
    lines = F12_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            out.append("    " + expand(S) if S is not None else "    # -")
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_e(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F19's template R (``tests/fixtures/F19/template/script/main.vns``, F19 06 §0.4) with
    the row's edit: **S** goes on line 7 after 4 spaces, **T** on line 16; an unused S line
    becomes ``    # -`` and an unused T line is removed. ``replace`` (**Rn**) as
    ``template``."""
    return _slots(F19_TEMPLATE, S, T, replace)


def template_c(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F21's template C (``tests/fixtures/F21/template/script/main.vns``, F21 06 §0.4): **S**
    on line 10 after 4 spaces, **T** on line 12, as ``template_e``."""
    return _slots(F21_TEMPLATE, S, T, replace)


def _slots(path: Path, S: str | None, T: str | None,
           replace: dict[int, str] | None) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            out.append("    " + expand(S) if S is not None else "    # -")
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_g(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F23's template M (``tests/fixtures/F23/template/script/main.vns``, F23 06 §5): **S**
    replaces the minigame line, line 9, after 4 spaces (its own ``⏎`` lines as written);
    **T** is appended at the top level after line 13; ``replace`` (**Rn**) as ``template``."""
    lines = F23_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    if S is not None:
        lines[8] = "    " + expand(S)
    if T is not None:
        lines.append(expand(T))
    return "\n".join(lines) + "\n"


def template_f28(*, S: str | None = None, T: str | None = None,
                 replace: dict[int, str] | None = None) -> str:
    """F28's template G (``tests/fixtures/F28/template/script/main.vns``, F28 06 §0.3): **S**
    goes on line 5 after 4 spaces (``⏎`` lines keep that indent unless they give their own),
    **T** on line 9 at the top level; an unused S line becomes ``    # -`` and an unused T
    line is removed. ``replace`` as ``template``."""
    return _indented_slots(F28_TEMPLATE, S=S, T=T, replace=replace)


def template_f30(*, S: str | None = None, T: str | None = None,
                 replace: dict[int, str] | None = None) -> str:
    """F30's template W (``tests/fixtures/F30/template/script/main.vns``, F30 06 §0.3): **S**
    on line 6, **T** on line 10 at the top level, as ``template_f28``."""
    return _indented_slots(F30_TEMPLATE, S=S, T=T, replace=replace)


def template_f32(*, S: str | None = None, T: str | None = None,
                 replace: dict[int, str] | None = None) -> str:
    """F32's template U (``tests/fixtures/F32/template/script/main.vns``, F32 06 §0.3): **S**
    on line 5, **T** on line 8 at the top level, as ``template_f28``."""
    return _indented_slots(F32_TEMPLATE, S=S, T=T, replace=replace)


def _indented_slots(path: Path, *, S: str | None, T: str | None,
                    replace: dict[int, str] | None) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            if S is None:
                out.append("    # -")
            else:
                out += [("    " + row if not row.startswith((" ", "\t")) else row)
                        for row in expand(S).split("\n")]
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_l(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F20's template L (``tests/fixtures/F20/template/script/main.vns``, F20 06 §5): **S**
    replaces line 12 (``"Daichi waves from the stall."``, label ``stall``'s second statement)
    after 4 spaces (its own ``⏎`` lines as written); **T** is appended at the top level after
    line 40; ``replace`` (**Rn**) as ``template``."""
    lines = F20_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    if S is not None:
        lines[11] = "    " + expand(S)
    if T is not None:
        lines.append(expand(T))
    return "\n".join(lines) + "\n"


def template_n(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None, drop: tuple[int, ...] = ()) -> str:
    """F17's template N (``tests/fixtures/F17/template/script/main.vns``, F17 06 §0.4) with
    the row's edit: **Rn** (``replace``) replaces line n with the row's text as written (its
    own indentation, notation applies; ``⏎`` lines follow it), ``drop`` removes lines (the
    "without lines 7, 11, 22" rows), and **T** is appended at the top level after line 24.
    Template N has no S slot."""
    assert S is None, "template N has no S slot (F17 06 §0.4)"
    lines = F17_TEMPLATE.read_text(encoding="utf-8").splitlines()
    out = []
    for number, line in enumerate(lines, 1):
        if number in drop:
            continue
        out.append(expand(replace[number]) if replace and number in replace else line)
    if T is not None:
        out.append(expand(T))
    return "\n".join(out) + "\n"


def template_x(*, S: str | None = None, D: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F05's template X (``tests/fixtures/F05/template/script/main.vns``, F05 06 §0.4) with
    the row's edit: **S** is line 7's text (``    "x"``, so a ``{`` at text offset k is at
    column 6 + k), **D** replaces line 7 with a whole statement (``    x``), **T** goes on
    line 9. With neither S nor D, line 7 is ``    "Hello."``; an unused T line is removed.
    ``replace`` as ``template``."""
    lines = F05_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == '    "<S>"':
            if D is not None:
                out.append("    " + expand(D))
            else:
                out.append('    "' + (expand(S) if S is not None else "Hello.") + '"')
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_s(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F04's template S (``tests/fixtures/F04/template/script/main.vns``, F04 06 §0.4) with
    the row's edit: **S** goes on line 6 after 4 spaces, **T** on line 8 at the top level; an
    unused S line becomes ``    # -`` and an unused T line is removed. ``replace`` as
    ``template``."""
    lines = F04_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            out.append("    " + expand(S) if S is not None else "    # -")
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_f(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F09's template F (``tests/fixtures/F09/template/script/main.vns``, F09 06 §0.4) with
    the row's edit: **S** goes on line 6 after 4 spaces (``⏎`` lines keep that indent unless
    they give their own, ``[4]``), **T** on line 8 at the top level; an unused S line becomes
    ``    # -`` and an unused T line is removed. ``replace`` as ``template``."""
    lines = F09_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            if S is None:
                out.append("    # -")
            else:
                out += [("    " + row if not row.startswith((" ", "\t")) else row)
                        for row in expand(S).split("\n")]
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def template_a(*, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F08's template A (``tests/fixtures/F08/template/script/main.vns``, F08 06 §0.4) with
    the row's edit: **S** goes on line 4 after 4 spaces (``⏎`` lines keep that indent unless
    they give their own), **T** on line 7 at the top level; an unused S line becomes
    ``    # -`` and an unused T line is removed. ``replace`` as ``template``."""
    lines = F08_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        lines[number - 1] = expand(text)
    out = []
    for line in lines:
        if line == "    <S>":
            if S is None:
                out.append("    # -")
            else:
                out += [("    " + row if not row.startswith((" ", "\t")) else row)
                        for row in expand(S).split("\n")]
        elif line == "<T>":
            if T is not None:
                out.append(expand(T))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _indented(text: str, indent: str = "    ") -> list[str]:
    """Rows of an edit: a row with no indentation of its own gets ``indent``."""
    return [(indent + row if not row.startswith((" ", "\t")) else row)
            for row in expand(text).split("\n")]


def template_m(*, M: str | None = None, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> str:
    """F07's template M (``tests/fixtures/F07/template/script/main.vns``, F07 06 §0.4)
    with the row's edit: **M** replaces lines 6–14 (the menu), **S** replaces line 5, **T**
    is appended at the top level after line 19; a row with no indentation of its own gets 4
    spaces. ``replace`` (**Rn**) replaces line n of the template first, keeping that line's
    indentation when the new text gives none."""
    lines = F07_TEMPLATE.read_text(encoding="utf-8").splitlines()
    for number, text in (replace or {}).items():
        old = lines[number - 1]
        indent = old[:len(old) - len(old.lstrip())]
        lines[number - 1] = "\n".join(_indented(text, indent))
    head, line5, menu, tail = lines[:4], lines[4], lines[5:14], lines[14:]
    out = head + (_indented(S) if S is not None else [line5])
    out += _indented(M) if M is not None else menu
    out += tail
    if T is not None:
        out += expand(T).split("\n")
    return "\n".join(out) + "\n"


@dataclass
class Parsed:
    nodes: list[Node]
    ctx: ParseContext
    errors: list[ScriptError]

    @property
    def messages(self) -> list[str]:
        return [error.format() for error in self.errors]

    @property
    def codes(self) -> list[str]:
        return [error.code for error in self.errors]

    @property
    def labels(self) -> dict[str, Label]:
        return {node.name: node for node in self.nodes if isinstance(node, Label)}

    @property
    def warnings(self):
        return self.ctx.warnings.finish()


def parse_text(text: str | bytes, ref: str = "script/main.vns", *,
               ctx: ParseContext | None = None, order: int = 0,
               resolve: bool = True) -> Parsed:
    """Decode (bytes) and parse one file. With ``resolve``, deferred no-text lines are
    decided against this file's defines (what ``checks.py`` will do game-wide)."""
    ctx = ctx or ParseContext(sink=DiagnosticSink())
    file = ScriptFile(ref, ref.removeprefix("script/"), order)
    if isinstance(text, bytes):
        decoded = decode_script(ref, text)
        assert decoded.problem is None, decoded.problem
        text = decoded.text
    nodes = parse_file(file, text, ctx)
    if resolve:
        for item in ctx.collected.no_text:
            ctx.sink.add(resolve_no_text(item, ctx.collected.define_defs))
        ctx.collected.no_text.clear()
    return Parsed(nodes, ctx, list(ctx.sink.errors()))


def one_error(text: str) -> ScriptError:
    parsed = parse_text(text)
    assert len(parsed.errors) == 1, parsed.messages
    return parsed.errors[0]


def message_at(error: ScriptError) -> tuple[str, str]:
    """``("5:11", message)`` / ``("5", message)`` for comparing with an AC row."""
    where = str(error.line) if error.column is None else f"{error.line}:{error.column}"
    return where, error.message


def first_say(parsed: Parsed, label: str = "start", index: int = 1):
    return parsed.labels[label].block[index]


def dump(node: object, *, positions: bool = True) -> object:
    """A plain-data dump of a node tree (06 §0.5 "program dump"), optionally without
    line, end_line, and column."""
    if isinstance(node, (list, tuple)):
        return [dump(item, positions=positions) for item in node]
    if isinstance(node, ScriptFile):
        return node.ref
    if isinstance(node, PyCode):
        out = {"kind": "PyCode", "source": node.source, "mode": node.mode}
        if positions:
            out.update(line=node.line, column=node.column)
        return out
    if is_dataclass(node):
        out = {"kind": type(node).__name__}
        for f in fields(node):
            if not positions and f.name in ("line", "end_line", "column"):
                continue
            out[f.name] = dump(getattr(node, f.name), positions=positions)
        return out
    return node


def dumps(nodes: list[Node], *, positions: bool = True) -> str:
    return json.dumps(dump(nodes, positions=positions), sort_keys=True, ensure_ascii=False)


__all__ = ["F03_TEMPLATE", "F04_TEMPLATE", "F04_TEMPLATE_DIR", "F05_TEMPLATE", "F07_TEMPLATE",
           "F09_TEMPLATE", "F09_TEMPLATE_DIR", "template_f",
           "F07_TEMPLATE_DIR", "F08_TEMPLATE",
           "F08_TEMPLATE_DIR", "FIXTURES", "If", "IfBranch", "Parsed", "dump", "dumps",
           "expand", "first_say", "message_at", "one_error", "parse_text", "template",
           "template_a", "template_e", "template_f28", "template_f30", "template_m", "template_r",
           "template_s", "template_x"]
