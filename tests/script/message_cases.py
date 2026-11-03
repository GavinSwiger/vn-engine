"""The message cases of ``tests/fixtures/F02/messages/cases.toml`` (06 §5.2) and the AC-F02-50
golden file ``expected.txt``.

A case is one row of an AC message table. ``needs = "parse"`` cases run through the
single-file parse (``helpers.parse_text``); ``needs = "load"`` cases build a game folder in a
temporary directory and run ``load_story`` (checklist step 6). Load cases whose codes come
from the whole-game checks (``CHECK_CODES``) run once ``engine/script/checks.py`` exists
(checklist step 7); until then they are only validated as data. The golden file holds the
formatted errors and warnings of every runnable case, in case order.

F03 rows (``feature = "F03"``, ``time = "load" | "launch" | "run"``; F03 ``06-acceptance.md``
§0.4) edit F03's template R instead of template T. Their ``time = "run"`` rows (F03 step 7)
load clean, so they are not runnable here: ``tests/runtime/test_messages_f03.py`` plays them.
F05 rows (``feature = "F05"``; F05 ``06-acceptance.md`` §0.4) edit F05's template X: S is
line 7's text, D replaces line 7, T is line 9. F05's launch and run texts are checked in
``test_messages.py`` until their steps can run them. F06 rows (``feature = "F06"``, all
``time = "launch"``) edit template X too; ``tests/runtime/test_blip_options.py`` plays them
as a define and as a ``$`` line. F04 rows (``feature = "F04"``; F04
``06-acceptance.md`` §0.4) edit F04's template S (S is line 6, T is line 8); their game
folder gets the template's ``config.toml``, and the load gets ``LoadOptions(position_names=
config.stage.positions)`` as bootstrap gives it. F08 rows (``feature = "F08"``; F08
``06-acceptance.md`` §0.4) edit F08's template A (S is line 4, each ``⏎`` line indented like
it unless the row gives its own indent; T is line 7); their game folder gets the template's
``config.toml``. F08's launch rows (``time = "launch"``) come with F08 step 8. F07 rows
(``feature = "F07"``; F07 ``06-acceptance.md`` §0.4) edit F07's template M (``M`` replaces
the menu, lines 6–14; S is line 5; T is appended after line 19); their ``time = "run"`` rows
(E178) are played by ``tests/runtime/test_menu_runtime.py``. F12 rows (``feature = "F12"``;
F12 ``06-acceptance.md`` §0.4) edit F12's template P (S is line 7, T is line 10); their
``time = "launch" | "run"`` rows are played by ``tests/runtime/test_persistent_story.py``.
F09 rows (``feature = "F09"``; F09 ``06-acceptance.md`` §0.4) edit F09's template F (S is
line 6, each ``⏎`` line indented like it unless the row gives its own; T is line 8); their
``time = "launch"`` rows are played by ``tests/runtime/test_transitions.py``. F17 rows
(``feature = "F17"``; F17 ``06-acceptance.md`` §0.4) edit F17's template N (``R`` rows, T is
appended after line 24; no S slot); ``config`` is the game's ``config.toml`` (W100's theme
rows). Their ``time = "launch" | "run"`` rows (W100, W101, W102) are data until F17's launch
and run tests play them. F19 rows (``feature = "F19"``; F19 ``06-acceptance.md`` §0.4) edit
F19's template R (S is line 7, T is line 16); the load runs inside ``scoped_registry()`` with
``routes.register_words()`` (F19 07 I-5: the words are registered only for these rows until
F19 step 3). F21 rows (``feature = "F21"``; F21 ``06-acceptance.md`` §0.4) edit F21's template C
(S is line 10, T is line 12); the load runs inside ``scoped_registry()`` with F19's and then
F21's ``register_words()`` (F21 07 I-4), and is a release load (``dev=False``, so the
template's tips give no W142) except for the W140/W142 rows. F23 rows (``feature = "F23"``; F23
``06-acceptance.md`` §0.3, §5) edit F23's template M (S replaces line 9, the minigame line; T
is appended after line 13); the load runs inside ``scoped_registry()`` with F19's, F21's, and
F23's ``register_words()`` (F19 07 I-5), with ``LoadOptions(minigames=SIGS)`` (``setup``
``"sigs two"``, ``"sigs filler"``, or ``"sigs none"`` picks another map or None), and is a
release load except for warning rows (``dev=False``: the template's ``{var=r}`` gives no W42).
F20 rows (``feature = "F20"``; F20 ``06-acceptance.md`` §0.3, §5) edit F20's template L (S
replaces line 12, label ``stall``'s second statement; T is appended after line 40); the word
registers at import since F20 s1, and the load is a release load (``dev=False``) except for
warning rows and ``setup = "dev"`` rows; F20 s2: the load builds the graph
(``LoadOptions(flowchart=FlowOptions())``). F29 rows (``feature = "F29"``; F29
``06-acceptance.md`` §0.3) edit F05's template X as the F05 rows do (S, D, T); their load is a
dev load for warning rows (W185) and a release load otherwise. F28 rows (``feature = "F28"``;
F28 ``06-acceptance.md`` §0.3) edit F28's template G (S is line 5, T is line 9); they run
inside ``scoped_registry()`` with ``glitch.register_words()`` (F19 07 I-5; since F28 s3
``effect`` registers at import, so the call changes nothing), as a release load except for
warning rows; their ``time = "run"`` W184 rows are played by
``tests/runtime/test_glitch_runtime.py``. F30 rows (``feature = "F30"``; F30 ``06-acceptance.md`` §0.3) edit F30's template
W (S is line 6, T is line 10; the game folder gets its ``config.toml``) and load as F28's rows
do (``effect window_title`` and ``effect crash`` are rows of F28's kind table). F32 rows
(``feature = "F32"``; F32 ``06-acceptance.md`` §0.3) edit F32's template U (S is line 5, T is
line 8; the game folder gets its ``config.toml``); they run inside ``scoped_registry()`` with
``ui.register_words()`` (F19 07 I-5: ``ui`` registers at import from F32 s3), with
``LoadOptions.style_names`` from that config as the app gives it (``setup = "no styles"``: a
config with no ``[style]`` table), as a release load except for warning rows. Their W204–W207
rows (``time = "run" | "launch"``) are data; ``tests/script/test_ui_parse.py`` checks their texts.
F31 rows (``feature = "F31"``; F31 ``06-acceptance.md`` AC-F31-09) edit F31's template (S is line
6, T is line 8); the game folder gets its ``files/hana.chr`` (``setup = "no original"``: none;
``"large original"``: a 5,452,595-byte one). They run inside ``scoped_registry()`` with
``metafiles.register_words()`` (since F31 s3 ``file`` registers at import, so the call changes
nothing). Their W196–W200 rows
(``time = "run"``) are data; ``tests/script/test_metafiles_parse.py`` checks their texts.

Regenerate the golden file only with the reviewed command::

    .venv/Scripts/python -m tests.script.message_cases --write
"""

import importlib.util
import os
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.core.config import load_config
from engine.core.errors import AssetUnreadable
from engine.core.paths import GamePaths
from engine.script.diagnostics import ScriptError, ScriptWarning
from engine.script.flowgraph import FlowOptions
from engine.script.loader import LoadOptions, load_story
from engine.script.messages import format_message
from engine.script.statements import scoped_registry
from tests.script.helpers import (
    F04_TEMPLATE_DIR,
    F08_TEMPLATE_DIR,
    F30_TEMPLATE_DIR,
    F31_TEMPLATE_DIR,
    F32_TEMPLATE_DIR,
    FIXTURES,
    expand,
    parse_text,
    template,
    template_a,
    template_c,
    template_e,
    template_g,
    template_l,
    template_f,
    template_f28,
    template_f30,
    template_f31,
    template_f32,
    template_m,
    template_p,
    template_r,
    template_s,
    template_n,
    template_x,
)

CASES_PATH = FIXTURES / "messages" / "cases.toml"
EXPECTED_PATH = FIXTURES / "messages" / "expected.txt"

PLACEHOLDERS = ("<x>", "<y>", "<z>", "<v>", "<w>")
_REPEAT_RE = re.compile(r"<<(.+?)\*(\d+)>>", re.S)
_WHERE_RE = re.compile(r"^(?:(?P<ref>script/\S+) )?(?P<line>\d+)(?::(?P<col>\d+))?$")
MAIN_REF = "script/main.vns"

# Codes raised by the whole-game checks (04 §6.3 phase G, plus W04): a load case expecting
# one of them runs only once checks.py exists (checklist step 7).
CHECK_CODES = frozenset(("E25", "E26", "E30a", "E30b", "E43", "E47", "E48", "E48b", "E70",
                         "E71", "W04", "W04s"))
CHECKS_BUILT = importlib.util.find_spec("engine.script.checks") is not None


@dataclass(frozen=True)
class Case:
    id: str
    ac: str
    code: str
    needs: str
    edit: dict
    where: str
    expect: dict
    also: tuple[str, ...]
    golden: bool
    setup: str | None
    feature: str = "F02"
    time: str = "load"

    @property
    def runnable(self) -> bool:
        """True if the built checklist steps can run the case through the load. F03's
        launch and run rows load clean and fail later: ``tests/runtime/test_messages_f03.py``
        runs them."""
        if self.time != "load":
            return False
        if self.needs == "parse" or CHECKS_BUILT:
            return True
        return not ({self.code, *self.also} & CHECK_CODES)


@dataclass
class Outcome:
    errors: list[ScriptError]
    warnings: tuple[ScriptWarning, ...]
    error_count: int
    checks_skipped: bool


def _subst(value: Any, items: list[str]) -> Any:
    if isinstance(value, str):
        for mark, item in zip(PLACEHOLDERS, items):
            value = value.replace(mark, item)
        return value
    if isinstance(value, dict):
        return {_subst(k, items): _subst(v, items) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, items) for v in value]
    return value


def load_cases() -> list[Case]:
    """Every case, with ``each`` variants expanded (ids get ``-1``, ``-2``, …)."""
    data = tomllib.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = []
    for raw in data["case"]:
        each = raw.get("each")
        variants = [None] if each is None else [i if isinstance(i, list) else [i] for i in each]
        for number, items in enumerate(variants, 1):
            row = raw if items is None else _subst(
                {k: v for k, v in raw.items() if k != "each"}, items)
            cases.append(Case(
                id=raw["id"] if items is None else f"{raw['id']}-{number}",
                ac=row["ac"], code=row["code"], needs=row.get("needs", "parse"),
                edit=row.get("edit", {}), where=row.get("where", "-"),
                expect=row.get("expect", {}), also=tuple(row.get("also", ())),
                golden=row.get("golden", True), setup=row.get("setup"),
                feature=row.get("feature", "F02"), time=row.get("time", "load")))
    return cases


def repeat(text: str) -> str:
    """``<<text*N>>`` → ``text`` repeated N times."""
    return _REPEAT_RE.sub(lambda m: m.group(1) * int(m.group(2)), text)


def _nested_ifs_50() -> str:
    lines = ["label start:"]
    lines += ["    " * depth + "if True:" for depth in range(1, 51)]
    lines.append("    " * 51 + '"A."')
    return "\n".join(lines) + "\n"


def _w04_21() -> str:
    return template(T="⏎".join(f"define h{{U+0430}}na{i} = 1" for i in range(1, 22)))


def _w02_25() -> dict[str, str]:
    return {f"w{i:02}.vns": "# x" for i in range(1, 26)}


# Named generators (``edit.gen``): main.vns text, or (w02_25) the not-included files.
GENERATORS = {"nested_ifs_50": _nested_ifs_50, "w04_21": _w04_21, "w02_25": _w02_25}


def main_text(case: Case) -> str | bytes:
    """main.vns of a parse case."""
    edit = case.edit
    if "gen" in edit:
        text = GENERATORS[edit["gen"]]()
        assert isinstance(text, str), case.id
    elif "text" in edit:
        text = expand(repeat(edit["text"])) + ("\n" if edit["text"] else "")
    else:
        replace = {int(k): repeat(v) for k, v in edit.get("R", {}).items()}
        S = repeat(edit["S"]) if "S" in edit else None
        T = repeat(edit["T"]) if "T" in edit else None
        if case.feature in ("F05", "F06", "F29"):
            text = template_x(S=S, D=repeat(edit["D"]) if "D" in edit else None, T=T,
                              replace=replace)
        elif case.feature == "F07":
            text = template_m(M=repeat(edit["M"]) if "M" in edit else None, S=S, T=T,
                              replace=replace)
        else:
            build = {"F03": template_r, "F04": template_s, "F08": template_a,
                     "F09": template_f, "F12": template_p,
                     "F17": template_n, "F19": template_e,
                     "F21": template_c, "F23": template_g,
                     "F20": template_l, "F28": template_f28,
                     "F30": template_f30, "F31": template_f31,
                     "F32": template_f32}.get(case.feature, template)
            text = build(S=S, T=T, replace=replace)
    if "prefix_hex" in edit:
        return bytes.fromhex(edit["prefix_hex"]) + text.encode("utf-8")
    return text


def _file_bytes(value: Any) -> bytes | None:
    """A ``files``/``F`` value as bytes; None for ``"<dir>"``."""
    if value == "<dir>":
        return None
    if isinstance(value, dict):
        if "hex" in value:
            return bytes.fromhex(value["hex"])
        text = expand(repeat(value["text"])) + "\n"
        return bytes.fromhex(value.get("prefix_hex", "")) + text.encode("utf-8")
    return (expand(repeat(value)) + "\n").encode("utf-8")


def _link(link: Path, target: Path, *, folder: bool) -> None:
    """A symbolic link (Windows folders: a junction when links aren't permitted); skips the
    test where neither can be made (06 §0.3)."""
    try:
        os.symlink(target, link, target_is_directory=folder)
        return
    except (OSError, NotImplementedError) as exc:
        reason = exc
    if folder and os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return
    import pytest
    pytest.skip(f"symbolic links are not permitted here: {reason}")


class _UnreadablePaths(GamePaths):
    """``read_file`` raises ``AssetUnreadable`` for one ref (the "all OSes" form of the
    unreadable-file rows)."""

    unreadable = ""

    def read_file(self, ref: str, *, max_bytes: int) -> bytes:
        if ref == self.unreadable:
            raise AssetUnreadable(ref)
        return super().read_file(ref, max_bytes=max_bytes)


def _build_game(case: Case, tmp: Path) -> GamePaths:
    """The game folder of a load case under ``tmp`` (``tmp/outside`` is beside it)."""
    edit, setup = case.edit, case.setup or ""
    original = case.feature == "F31" and setup != "no original"
    large = case.feature == "F31" and setup == "large original"
    if case.feature in ("F23", "F31", "F32") or (case.feature == "F20" and setup == "dev"):
        setup = ""          # F23: the setup picks the SIGS; F20: a dev load; F32: the styles
                            # F31: files/hana.chr (below)
    root = tmp / "game"
    script = root / "script"
    outside = tmp / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.vns").write_text("label leaked:\n    return\n", encoding="utf-8")
    (outside / "m.vns").write_text("label start:\n    return\n", encoding="utf-8")
    files: dict[str, Any] = dict(edit.get("files", {}))
    if edit.get("gen") == "w02_25":
        files.update(_w02_25())
        edit = {k: v for k, v in edit.items() if k != "gen"}
    if setup == "no script folder":
        return GamePaths(root.resolve())
    if setup.startswith("script is a symlink"):
        _link(script, outside, folder=True)
        return GamePaths(root.resolve())
    script.mkdir()
    if case.feature in ("F04", "F08", "F30", "F32"):
        folder = {"F04": F04_TEMPLATE_DIR, "F08": F08_TEMPLATE_DIR,
                  "F30": F30_TEMPLATE_DIR, "F32": F32_TEMPLATE_DIR}[case.feature]
        (root / "config.toml").write_bytes((folder / "config.toml").read_bytes())
    if original:                                        # F31: files/hana.chr
        (root / "files").mkdir()
        with open(root / "files" / "hana.chr", "wb") as out:
            out.write((F31_TEMPLATE_DIR / "files" / "hana.chr").read_bytes())
            if large:
                out.truncate(5_452_595)
    if "config" in edit:                                # F17: W100's theme rows
        (root / "config.toml").write_text(expand(edit["config"]) + "\n", encoding="utf-8")
    if edit.get("template", True):
        main = main_text(Case(**{**case.__dict__, "edit": edit}))
        data = main if isinstance(main, bytes) else main.encode("utf-8")
        extra = edit.get("F", {})
        data += "".join(f'include "{name}"\n' for name in extra).encode("utf-8")
        files.update(extra)
        (script / "main.vns").write_bytes(data)
    for name, value in files.items():
        path = script / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = _file_bytes(value)
        if content is None:
            path.mkdir(exist_ok=True)
        else:
            path.write_bytes(content)
    if setup.startswith("script/huge.vns is 16,777,217 bytes"):
        line = b"# padding line\n"
        count, extra_bytes = divmod(16 * 1024 * 1024 + 1, len(line))
        (script / "huge.vns").write_bytes(line * count + b"#" * extra_bytes)
    elif setup.startswith("script/main.vns is a symlink"):
        _link(script / "main.vns", outside / "m.vns", folder=False)
    elif setup.startswith("read_file raises AssetUnreadable for "):
        paths = _UnreadablePaths(root.resolve())
        object.__setattr__(paths, "unreadable", setup.rsplit(" ", 1)[-1])
        return paths
    elif setup:
        raise AssertionError(f"{case.id}: unknown setup {setup!r}")
    return GamePaths(root.resolve())


def run_case(case: Case) -> Outcome:
    """Run a case: a parse case through the single-file parse, a load case through
    ``load_story`` on a game folder built in a temporary directory. F19 rows run with F19's
    words registered (module docstring); F28 and F30 rows with ``effect`` registered; F32
    rows with ``ui`` registered; F31 rows with ``file`` registered."""
    if case.feature == "F31":
        from engine.script import metafiles

        with scoped_registry():
            metafiles.register_words()
            return _run_case(case)
    if case.feature == "F32":
        from engine.script import ui

        with scoped_registry():
            ui.register_words()
            return _run_case(case)
    if case.feature in ("F28", "F30"):
        from engine.script import glitch

        with scoped_registry():
            glitch.register_words()
            return _run_case(case)
    if case.feature in ("F19", "F21", "F23"):
        from engine.script import codex, minigame, routes

        with scoped_registry():
            routes.register_words()
            if case.feature in ("F21", "F23"):
                codex.register_words()
            if case.feature == "F23":
                minigame.register_words()
            return _run_case(case)
    return _run_case(case)


def f23_sigs(setup: str | None):
    """F23 rows: the ``LoadOptions.minigames`` a row's ``setup`` picks (module docstring)."""
    from tests.fixtures.F23.sigs import FILLER, SIGS, TWO

    return {None: SIGS, "sigs two": TWO, "sigs filler": FILLER, "sigs none": None}[setup]


def _run_case(case: Case) -> Outcome:
    if case.needs == "parse":
        parsed = parse_text(main_text(case))
        return Outcome(parsed.errors, parsed.warnings, parsed.ctx.sink.error_count, False)
    with tempfile.TemporaryDirectory() as tmp:
        paths = _build_game(case, Path(tmp))
        options = LoadOptions()
        if case.feature == "F04":
            config = load_config(paths)
            assert not config.errors, config.errors
            options = LoadOptions(position_names=config.config.stage.positions.keys())
        elif case.feature == "F21":
            options = LoadOptions(dev=case.code in ("W140", "W142"))
        elif case.feature == "F23":
            options = LoadOptions(dev=case.code.startswith("W"), minigames=f23_sigs(case.setup))
        elif case.feature == "F20":
            options = LoadOptions(dev=case.code.startswith("W") or case.setup == "dev",
                                  flowchart=FlowOptions())
        elif case.feature in ("F28", "F29", "F30", "F34", "F35", "F36", "F37"):
            options = LoadOptions(dev=case.code.startswith("W"))
        elif case.feature == "F32":
            styles = (frozenset() if case.setup == "no styles"
                      else frozenset(load_config(paths).config.style))
            options = LoadOptions(dev=case.code.startswith("W"), style_names=styles)
        result = load_story(paths, options)
    warnings = result.warnings
    if case.feature == "F23":       # template M's "Roll {var=r}." reads a $ line's r (F05 W42)
        warnings = tuple(w for w in warnings if w.code != "W42")
    return Outcome(list(result.errors), warnings, result.error_count, result.checks_skipped)


def render(case: Case, outcome: Outcome) -> list[str]:
    """The golden-file block of one case: its id, then every formatted error, E100, E99,
    and every formatted warning; ``(loads)`` when there are none."""
    lines = [f"[{case.id}]"]
    lines += [error.format() for error in outcome.errors]
    if outcome.error_count > len(outcome.errors):
        lines.append(format_message("E100", (f"{outcome.error_count - len(outcome.errors):,}",)))
    if outcome.checks_skipped:
        lines.append(format_message("E99"))
    lines += [warning.format() for warning in outcome.warnings]
    if len(lines) == 1:
        lines.append("(loads)")
    return lines


def golden_text(cases: list[Case] | None = None) -> str:
    """expected.txt: the blocks of every runnable golden case, separated by blank lines."""
    cases = load_cases() if cases is None else cases
    blocks = ["\n".join(render(c, run_case(c))) for c in cases if c.runnable and c.golden]
    return "\n\n".join(blocks) + "\n"


def parse_where(where: str) -> tuple[str | None, int | None, int | None] | str:
    """``"game"``/``"file"``/``"-"`` as is; else ``(ref, line, column)``."""
    if where in ("game", "file", "-"):
        return where
    match = _WHERE_RE.fullmatch(where)
    assert match is not None, where
    column = match.group("col")
    return (match.group("ref") or MAIN_REF, int(match.group("line")),
            int(column) if column else None)


def check_case(case: Case, outcome: Outcome) -> None:
    """The row's assertions: one error (plus ``also``), at ``where``, with ``expect``."""
    codes = [e.code for e in outcome.errors]
    if case.code == "-":
        assert not codes and not outcome.warnings, render(case, outcome)
        return
    also = [c for c in case.also if c != "E99"]
    # E99 is the "checks skipped" note, not an error (AC-F02-41).
    assert outcome.checks_skipped == ("E99" in case.also), render(case, outcome)
    if case.code.startswith("W"):
        assert not codes, render(case, outcome)
        found = [w for w in outcome.warnings if w.code == case.code]
        assert found, render(case, outcome)       # W02 rows: the first in code-point order
    else:
        assert codes == [case.code, *also], render(case, outcome)
        assert outcome.error_count == 1 + len(also)
        found = [e for e in outcome.errors if e.code == case.code]
        assert len(found) == 1, render(case, outcome)
    item = found[0]
    where = parse_where(case.where)
    if where == "game":
        assert item.file is None and item.line is None, item.format()
    elif where == "file":
        assert item.line is None, item.format()
        assert item.message.startswith("script/"), item.message
    elif isinstance(where, tuple):
        assert (item.file, item.line, getattr(item, "column", None)) == where, item.format()
    message = item.message
    expect = case.expect
    if "exact" in expect:
        assert message == expect["exact"]
    contains = expect.get("contains", [])
    for part in [contains] if isinstance(contains, str) else contains:
        assert part in message, (part, message)
    if "starts" in expect:
        assert message.startswith(expect["starts"]), message
    if "ends" in expect:
        assert message.endswith(expect["ends"]), message


def main(argv: list[str]) -> int:
    text = golden_text()
    if "--write" in argv:
        EXPECTED_PATH.write_bytes(text.encode("utf-8"))
        print(f"wrote {EXPECTED_PATH}")
        return 0
    same = EXPECTED_PATH.exists() and EXPECTED_PATH.read_bytes() == text.encode("utf-8")
    print("expected.txt is up to date" if same else "expected.txt differs (use --write)")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
