"""F41 P3: the check child's lint phase and the ``lint`` command's engine side
(``engine/tools/check.py``; F41 ``04-technical.md`` §7.3; F43 ``07`` I-6, I-7).

AC-F41-01 (lint items: source, severity, order; none with a load error), AC-F41-03 (one
used and one unused thing of each kind), AC-F41-08 (Database's "Used in N lines" ⇔ no lint
item), AC-F41-14 (the example game's lint output is a reviewed list; the sample game has no
lint items), AC-F41-16 (Studio's wire carries no lint item: Problems, the gutter and the
counts don't change). I-6: the name kinds stay within Studio's 64. I-7: ``run()`` writes
exactly what it wrote before the ``collect()`` split on F45's check fixtures (the golden
file; lint's own name kinds are left out of the comparison)."""

import json
import shutil
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.tools import check as ck
from engine.tools.check import NAME_SOURCES, CheckJob, encode_event, lint_command
from engine.tools.editor import checker
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import files
from engine.tools.editor.checkwiring import check_counts, check_summary, counts_text
from engine.tools.lint import LINT_KINDS
from tests.tools.f45_games import check, edit_line, result_of, run_job, studio

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "F41" / "check_run_golden.txt"
MAIN = "script/main.vns"


# --- I-7: run() output is unchanged by the collect() split -----------------------------------

def _config_error(game: Path) -> None:
    (game / "config.toml").write_bytes(b'[game]\ntitle = 5\n')
    edit_line(game / "script" / "main.vns", 5, "    show hana sad")


def _todo(game: Path) -> None:
    ch2 = game / "script" / "ch2.vns"
    ch2.write_bytes(b"# TODO tidy\n" + ch2.read_bytes())


SCENARIOS = {
    "clean": (lambda game: None, True),
    "clean, no launch": (lambda game: None, False),
    "config error": (_config_error, True),
    "load error": (lambda game: edit_line(game / "script" / "ch2.vns", 9, "    jump bridg"),
                   True),
    "unknown key": (lambda game: (game / "config.toml").write_bytes(
        b'[game]\ntitle = "My Game"\ntitel = "x"\n'), True),
    "todo": (_todo, True),
}


def _without_lint(event: dict) -> dict | None:
    """``event`` as it was before P3: lint's names events dropped, its kinds left out of
    ``done``'s totals (they are added at the end of ``NAME_SOURCES``)."""
    if event["event"] == "names" and event["kind"] in LINT_KINDS:
        return None
    if event["event"] == "done":
        totals = {k: n for k, n in event["name_totals"].items() if k not in LINT_KINDS}
        return {**event, "name_totals": totals}
    return event


def golden_lines(tmp_path: Path) -> list[str]:
    """Every scenario's report lines, as ``run()`` writes them (fixed clock)."""
    lines: list[str] = []
    for n, (name, (change, launch)) in enumerate(SCENARIOS.items()):
        game = studio(tmp_path, f"g{n}")
        change(game)
        events: list[dict] = []
        CheckJob(GamePaths.for_game(game), events.append, launch=launch,
                 clock=lambda: 0.0).run()
        lines.append(f"== {name}")
        lines += [encode_event(e).decode("ascii") for e in map(_without_lint, events)
                  if e is not None]
    return lines


def test_i7_run_output_is_unchanged_on_the_f45_fixtures(tmp_path):
    """I-7 (and 04 §19 (d)): ``run()`` is ``collect()`` then ``emit_results``, byte for byte
    what it wrote before the split. The golden file was written by the pre-P3 ``run()``; a
    later change to F45's fixture or to a name row regenerates it with ``golden_lines``."""
    expected = GOLDEN.read_text(encoding="ascii").splitlines()
    assert golden_lines(tmp_path) == expected


# --- The AC-F41-03 fixture: one used and one unused thing of each kind --------------------------

SCRIPT = """\
define hana = Character("Hana")
define kenji = Character("Kenji")
define slow = Dissolve(0.5)
define quick = Fade(0.2)
define max_tries = 3
define spare = 2
image bg dusk = "#203040"
image bg dawn = "#a0a0ff"
default trust = 0
default lantern_count = 0
points courage 0 to 10
points spare_m 0 to 5
label start:
    scene bg dusk with slow
    show hana happy at far
    hana "You have {var=max_tries} tries."
    $ trust += 1
    points courage += 1
    play music "bgm/theme.ogg"
    jump end
label end:
    scene bg room
    "End."
label old:
    "Old."
"""
CONFIG = '[game]\ntitle = "My Game"\n\n[stage.positions]\nfar = 100\nnear = 300\n'
# (code, kind, name, file, line), in lint order: code, file, line, name.
FOUND = [
    ("W237", "unreached", "old", MAIN, 24),
    ("W238", "unused_character", "kenji", MAIN, 2),
    ("W239", "unused_picture", "bg photo", "images/bg/photo.jpg", None),
    ("W239", "unused_picture", "bg dawn", MAIN, 8),
    ("W240", "unused_sound", "sfx/spare.ogg", "audio/sfx/spare.ogg", None),
    ("W241", "unused_variable", "lantern_count", MAIN, 10),
    ("W242", "unused_position", "near", "config.toml", 6),
    ("W242", "unused_transition", "quick", MAIN, 4),
    ("W242", "unused_define", "spare", MAIN, 6),
    ("W242", "unused_meter", "spare_m", MAIN, 12),
]


def _game(tmp_path: Path, name: str = "my_game") -> Path:
    """F45's game S with ``SCRIPT`` and ``CONFIG`` (ch2.vns gone) and one more sound."""
    game = studio(tmp_path, name)
    (game / "script" / "ch2.vns").unlink()
    (game / "script" / "main.vns").write_text(SCRIPT, encoding="utf-8")
    (game / "config.toml").write_text(CONFIG, encoding="utf-8")
    (game / "audio" / "sfx").mkdir()
    shutil.copy(game / "audio" / "bgm" / "theme.ogg", game / "audio" / "sfx" / "spare.ogg")
    return game


class _Buffer:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    def flush(self) -> None:
        pass


def _lint(monkeypatch, game: Path, *, as_json: bool = True,
          strict: bool = False) -> tuple[int, bytes]:
    """``lint_command`` in process: its output stream is a buffer (fd 1 isn't touched)."""
    out = _Buffer()
    monkeypatch.setattr(ck, "_isolate_stdout", lambda: out)
    monkeypatch.setattr(ck, "_quiet_logs", lambda: None)
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    code = lint_command(game, as_json=as_json, strict=strict)
    return code, out.data


# --- AC-F41-01: lint items ------------------------------------------------------------------

def test_ac_f41_01_lint_items_and_none_with_errors(tmp_path, monkeypatch):
    """AC-F41-01: the CLI's lint items come after the problems, each ``source: "lint"`` and
    ``severity: "warning"``, sorted by code, file, line; the counts take them as warnings
    (exit 0, 1 with ``--strict``). A story with a load error, a config.toml error or a
    launch error has no lint items (decision 4) and no lint names rows (exit 1)."""
    code, data = _lint(monkeypatch, _game(tmp_path))
    doc = json.loads(data.decode("ascii"))
    assert code == 0 and data.isascii() and data.count(b"\n") == 1
    items = [item for item in doc["items"] if item["source"] == "lint"]
    assert [(i["code"], i["file"], i["line"]) for i in items] == [
        (r[0], r[3], r[4]) for r in FOUND]
    assert {(i["severity"], i["column"]) for i in items} == {("warning", None)}
    keys = [(i["code"], i["file"] or "", i["line"] or 0) for i in items]
    assert keys == sorted(keys)
    assert items[0]["text"].startswith('nothing leads to label "old" from start')
    assert (doc["v"], doc["errors"], doc["warnings"], doc["notes"], doc["more"]) == (
        1, 0, len(FOUND), 0, 0)
    code, text = _lint(monkeypatch, _game(tmp_path, "strict"), as_json=False, strict=True)
    lines = text.decode("utf-8").splitlines()
    assert code == 1 and lines[0].startswith(
        'script/main.vns:24: warning W237: nothing leads to label "old"')
    assert lines[2] == ('images/bg/photo.jpg: warning W239: picture "bg photo" isn\'t shown '
                        'anywhere in the story.')
    assert lines[-1] == "0 errors, 10 warnings, 0 notes."
    assert ck.lint_line({"severity": "warning", "code": "", "text": "x", "file": None,
                         "line": None, "column": None}) == "warning: x"
    assert ck.lint_summary(1, 1, 2) == "1 error, 1 warning, 2 notes."

    breaks = {"load": ("script/main.vns", 20, "    jump nowhere"),
              "config": ("config.toml", 2, "title = 5"),
              "launch": ("script/main.vns", 6, "define spare = 1 / 0")}
    for name, (ref, number, text) in breaks.items():
        game = _game(tmp_path, name)
        edit_line(game / ref, number, text)
        code, data = _lint(monkeypatch, game)
        doc = json.loads(data)
        assert code == 1 and doc["errors"] >= 1, name
        assert [i for i in doc["items"] if i["source"] == "lint"] == [], name
        assert not set(check(game).names) & set(LINT_KINDS), name


# --- AC-F41-03: W238-W242 through the check child ---------------------------------------------

def test_ac_f41_03_each_kind_through_the_check_child(tmp_path):
    """AC-F41-03: on one game with a used and an unused thing of each kind, the check child's
    names rows hold exactly the unused ones, at their declaration or file; ``--no-launch``
    leaves out ``unused_character`` (and reads ``quick`` as a transition from its call).
    Without config.toml (F41 P2's fix) the use rows and lint kinds are still sent."""
    game = _game(tmp_path)
    full = check(game)
    assert not full.problems and full.problem_total == 0
    rows = sorted((kind, e.name, e.file, e.line) for kind in LINT_KINDS
                  for e in full.names.get(kind, ()))
    assert rows == sorted(r[1:] for r in FOUND)
    assert {k: full.name_totals[k] for k in LINT_KINDS} == {
        k: sum(1 for r in FOUND if r[1] == k) for k in LINT_KINDS}
    quick = check(game, launch=False)
    assert "unused_character" not in quick.name_totals
    assert {k: quick.names.get(k) for k in LINT_KINDS if k != "unused_character"} == {
        k: full.names.get(k) for k in LINT_KINDS if k != "unused_character"}

    (game / "config.toml").unlink()
    edit_line(game / "script" / "main.vns", 15, "    show hana happy")
    bare = check(game, launch=False)
    assert {"image_use", "variable_use", "define_use"} <= set(bare.names)
    assert bare.name_totals["unused_position"] == 0                   # no config: none
    assert bare.name_totals["unused_sound"] == 1


# --- AC-F41-08: Database and lint agree ----------------------------------------------------------

def test_ac_f41_08_database_counts_agree_with_lint(tmp_path):
    """AC-F41-08: on the AC-F41-03 game, an entry's "Used in N lines" is 0 exactly when lint
    lists it, for characters, pictures, sounds, variables, transitions, positions, meters
    and plain defines (which count transition and define uses, decision 9; Clean up opens
    them in the editor)."""
    game = _game(tmp_path)
    names = check(game).names
    decls = dec.scan({MAIN: SCRIPT})

    def unused(entries) -> set[str]:
        return {entry.name for entry in entries if entry.uses == 0}

    # Backgrounds are a Database list; other pictures (sprites) count the same rows.
    sprites = {row.name for row in names["image"]
               if not row.name.casefold().startswith("bg ") and row.name != "black"}
    database = {
        "unused_character": unused(db.character_entries(decls, names)),
        "unused_picture": unused(db.background_entries(decls, names))
        | {n for n in sprites if not db.uses_of(names, db.BACKGROUND, n)},
        "unused_sound": unused(e for group in db.sound_entries(names).values() for e in group),
        "unused_variable": unused(db.variable_entries(decls, names)),
        "unused_transition": unused(db.transition_entries(decls, names)),
        "unused_position": unused(db.position_entries(CONFIG, names))
        - {"left", "center", "right"},
        "unused_meter": unused(db.meter_entries(decls, names)),
        "unused_define": {n for n in ("max_tries", "spare")
                          if not db.uses_of(names, dec.TRANSITION, n)},
    }
    lint_says = {kind: {e.name for e in names.get(kind, ())} for kind in database}
    assert database == lint_says
    assert all(lint_says.values())                               # one unused of each
    assert sprites and len(db.background_entries(decls, names)) > 2   # and used ones


# --- AC-F41-14: the example and sample games' lint output ----------------------------------------

EXAMPLE_LINT = ["0 errors, 0 warnings, 0 notes."]   # reviewed 2026-11-03 (F41 P3)


@pytest.mark.parametrize("which", ["example", files.TEMPLATE_SAMPLE, files.TEMPLATE_EMPTY])
def test_ac_f41_14_example_and_sample_lint_output(tmp_path, monkeypatch, which):
    """AC-F41-14: the example game's ``lint`` text output is exactly the reviewed list (the
    design's nine false "unused" items are gone; nothing else is listed, so ``--strict``
    passes); a new game from F47's sample (and from the empty starter), made as Studio's
    New game makes it, has no items at all."""
    if which == "example":
        code, data = _lint(monkeypatch, REPO / "game", as_json=False, strict=True)
        assert (code, data.decode("utf-8").splitlines()) == (0, EXAMPLE_LINT)
        return
    game = tmp_path / "My Game"
    for ref, data in files.template_files(which, game.name).items():
        (game / ref).parent.mkdir(parents=True, exist_ok=True)
        (game / ref).write_bytes(data)
    code, data = _lint(monkeypatch, game, strict=True)
    doc = json.loads(data)
    assert (code, doc["items"], doc["more"]) == (0, [], 0)


# --- AC-F41-16: nothing reaches Problems, the gutter or the counts -------------------------------

def test_ac_f41_16_studio_gets_no_lint_items(tmp_path):
    """AC-F41-16: a check whose lint lists things (S: ``side`` unreached; ``bg photo``,
    ``bg room``, the theme and ``trust`` unused) sends them only as names rows: Studio's
    ``CheckResult`` has no problem item (so no Problems row and no gutter marker), the total
    is 0 and the status bar says ``⊗ 0  ⚠ 0``. ``collect()`` holds the findings beside the
    problems, never in them or their counts."""
    game = studio(tmp_path)
    events = run_job(GamePaths.for_game(game))
    assert all(item["source"] != "lint" for e in events if e["event"] == "problems"
               for item in e["items"])
    result = result_of(events)
    assert result.problems == () and result.problem_total == 0
    assert check_counts(result) == (0, 0) and counts_text(result) == "⊗ 0  ⚠ 0"
    assert check_summary(result) == "Checked: no problems."
    assert [e.name for e in result.names["unreached"]] == ["side"]
    assert {e.name for e in result.names["unused_picture"]} == {"bg photo", "bg room"}
    outcome = CheckJob(GamePaths.for_game(game), lambda event: None).collect()
    assert outcome.problems == [] and outcome.total == 0 and len(outcome.lint) == 5
    assert outcome.counts == {"error": 0, "warning": 0, "info": 0}


# --- I-6: the name kinds fit Studio's done line --------------------------------------------------

def test_i6_name_kinds_fit_studios_done_line(tmp_path):
    """I-6: ``NAME_SOURCES`` (49 kinds with F41's lint rows) stays within the 64 kinds a
    ``done`` line may total (``checker._MAX_NAME_KINDS``); a ``done`` naming every kind
    decodes."""
    assert len(NAME_SOURCES) <= checker._MAX_NAME_KINDS
    assert set(LINT_KINDS) <= set(NAME_SOURCES)
    done = {"v": 1, "event": "done", "loaded": True, "problems": 0, "seconds": 0.0,
            "name_totals": dict.fromkeys(NAME_SOURCES, 0), "link_total": 0}
    assert checker.decode_check_line(encode_event(done)) is not None
