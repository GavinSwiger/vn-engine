"""F03 step 14 — the example game and the corpus played headless (``04-technical.md`` §14,
TR-F03-01; ``06-acceptance.md`` §1.9, §1.14).

ACs: AC-F03-80 (the example game uses F03's features, each with a comment above its first
use, and plays to the end with seeds 1..20 with no warning), AC-F03-55 (every checkpoint of
the example and the corpus survives a JSON round trip with its types and dumps to the same
text; AC-F03-18's values: ``test_restore.py``), AC-F03-56 (continuing from every round-tripped checkpoint of
the example (seed 3) and the corpus gives the original commands). The corpus rows run the
small parts (``flow/``, ``vars/``, ``lanterns/``) by default and the realistic part in
``slow`` (test-review-F03.md); the session fixtures are in ``conftest.py``. The window half of the
example is ``tests/app/test_story_driver.py`` (AC-F03-70) and F04's checks of its stage are
``test_headless_stage.py``.

F07 step 5 (AC-F07-45): the example has menus (a question, a conditional choice, a nested
menu, and a "Talk" loop), each with a comment above its first use; the runs answer them
from ``corpus.EXAMPLE_PICKS`` (the goldens) or with the first choice, and across the
goldens' seeds every choice of every menu is picked. The ``--dev`` launch with no warning
is AC-F03-70's window run.

F11 step 12 (AC-F11-66, headless half): every checkpoint of the goldens' runs goes through a
save file (``SaveEncoder``, then ``parse_full``) into a fresh driver and plays on as the
uninterrupted run; the five committed example saves load at their exact line before and
after the fixture patch (``tests/persist/example_saves.py``); a 10-hour save is under
1 MiB. The window half (Save, Load, Q.Save, Q.Load) is ``tests/app/test_saves_signoff_app.py``.

F19 step 6 (AC-F19-35): the example's three endings, the promise route behind the bridge's
last menu (``show_locked``), and ``lock ending``, played as AC-F19-24's four runs on one
store.

F21 step 5 (AC-F21-40): the example's codex (two tips, two items, one with a picture), with
no launch warning and one ``CodexAdded`` per unlock line reached.
"""

import dataclasses
import json
import logging
import re

import pytest

from engine.runtime.commands import (Advance, Choose, Say, ShowMenu, ShowStage, StoryEnded,
                                     StoryFailed)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.images import ImageSource
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from engine.script.menu import Menu
from engine.script.identity import walk_block
from engine.script.nodes import Jump
from tests.runtime import corpus
from tests.runtime.stage_story import EXAMPLE, example_minigames, load_example
from tests.runtime.test_values import type_tree


# --- AC-F03-80 — the example game ---------------------------------------------------------------

def _reading_order() -> list[str]:
    """``main.vns``, then the files it includes, in order (all of the example's files)."""
    main = (EXAMPLE / "script" / "main.vns").read_text(encoding="utf-8")
    return ["script/main.vns", *(f"script/{ref}" for ref in
                                 re.findall(r'^include "([^"]+)"$', main, re.M))]


# Feature → a pattern its first use matches (a whole line).
FEATURES = {
    "default": r"default \w+ = .+",
    "$ variable change": r"\s+\$ \w+ (=|\+=|-=) .+",
    "if": r"\s+if .+:",
    "elif": r"\s+elif .+:",
    "else": r"\s+else:",
    "call": r"\s+call \w+",
    "return": r"\s+return",
    "name_from": r'define \w+ = Character\(.*name_from="\w+".*\)',
    "dice": r".*\bdice\.(roll|pick|decimal|shuffle)\(.*",
}


def _first_uses() -> dict[str, tuple[str, int, list[str]]]:
    found: dict[str, tuple[str, int, list[str]]] = {}
    for ref in _reading_order():
        lines = (EXAMPLE / ref).read_text(encoding="utf-8").splitlines()
        for number, text in enumerate(lines, 1):
            for feature, pattern in FEATURES.items():
                if feature not in found and re.fullmatch(pattern, text):
                    found[feature] = (ref, number, lines)
    return found


def _comment_above(lines: list[str], number: int) -> bool:
    above = next(text for text in reversed(lines[:number - 1]) if text.strip())
    return above.lstrip().startswith("#")


def test_ac_f03_80_every_feature_has_a_comment_above_its_first_use():
    uses = _first_uses()
    assert sorted(uses) == sorted(FEATURES)
    for feature, (ref, number, lines) in uses.items():
        assert _comment_above(lines, number), (feature, ref, number)
    # The name change: name_from names a default that starts as "???", and a $ line sets it.
    _, number, lines = uses["name_from"]
    variable = re.search(r'name_from="(\w+)"', lines[number - 1]).group(1)
    texts = {ref: (EXAMPLE / ref).read_text(encoding="utf-8").splitlines()
             for ref in _reading_order()}
    assert any(line == f'default {variable} = "???"' for line in texts["script/main.vns"])
    change = next((ref, n) for ref, lines in texts.items()
                  for n, line in enumerate(lines, 1)
                  if re.fullmatch(rf'\s+\$ {variable} = "[^"?]+"', line))
    assert _comment_above(texts[change[0]], change[1]), change


def test_ac_f03_80_the_example_plays_to_the_end_with_seeds_1_to_20(caplog):
    result = load_example()
    assert result.program is not None and result.errors == () and result.warnings == ()
    images = corpus.example_images()
    launch = run_launch(result.program, images=ImageSource.from_files(images))
    assert launch.namespace is not None and launch.warnings == ()
    names = set()
    caplog.set_level(logging.DEBUG)
    for seed in range(1, 21):
        inputs = corpus.play(result.program, seed, images).inputs        # F07: the menus
        commands = run_headless(result.program, seed=seed, image_files=images, inputs=inputs,
                                minigames=example_minigames())
        assert commands[-1] == StoryEnded(), seed
        assert not [c for c in commands if type(c) is StoryFailed], seed
        names |= {c.name for c in commands if type(c) is Say}
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert {"???", "Hana", "Daichi"} <= names                 # the name plate changes


# --- AC-F07-45 — the example's menus --------------------------------------------------------------

def _menus(program) -> list[Menu]:
    return [s for s in program.iter_statements() if type(s) is Menu]


def _label_of(program) -> dict[str, str]:
    """A menu's sid → the label it is in."""
    return {s.sid: name for name, label in program.labels.items()
            for s, _ in walk_block(label.block) if type(s) is Menu}


def _menu_lines(program) -> dict[str, tuple[str, int, list[str]]]:
    """Each menu feature → (file, line, the file's lines) of its first use in reading order:
    a menu with a question, a conditional choice, a menu inside a choice, and a menu whose
    choice jumps back to the menu's own label (the "Talk" loop)."""
    refs = _reading_order()
    files = {ref: (EXAMPLE / ref).read_text(encoding="utf-8").splitlines() for ref in refs}
    labels = _label_of(program)
    nested = {stmt.sid for menu in _menus(program) for choice in menu.choices
              for stmt in choice.block if type(stmt) is Menu}
    found: dict[str, tuple[int, int]] = {}

    def note(feature: str, ref: str, line: int) -> None:
        place = (refs.index(ref), line)
        if feature not in found or place < found[feature]:
            found[feature] = place

    for menu in _menus(program):
        ref = menu.file.ref
        if menu.question is not None:
            note("question", ref, menu.line)
        if menu.sid in nested:
            note("nested menu", ref, menu.line)
        for choice in menu.choices:
            if choice.condition is not None:
                note("conditional choice", ref, choice.line)
            if any(type(s) is Jump and s.target == labels[menu.sid] for s in choice.block):
                note("Talk loop", ref, menu.line)
    return {feature: (refs[i], line, files[refs[i]]) for feature, (i, line) in found.items()}


def test_ac_f07_45_the_example_has_each_menu_feature_with_a_comment_above():
    uses = _menu_lines(corpus.example_program())
    assert sorted(uses) == ["Talk loop", "conditional choice", "nested menu", "question"]
    for feature, (ref, number, lines) in uses.items():
        assert _comment_above(lines, number), (feature, ref, number)


def test_ac_f07_45_the_goldens_pick_every_choice_of_every_menu():
    """The goldens' inputs (``EXAMPLE_PICKS``), seeds 1..5: every run ends, run_headless
    with the same answers gives the same commands, and together the runs pick every choice
    of every menu at least once. F19: the promise route's choice (its condition reads
    ``persistent.routes``) is closed in a fresh store; AC-F19-35 picks it."""
    program, images = corpus.example_program(), corpus.example_images()
    every = {(m.sid, c.key) for m in _menus(program) for c in m.choices
             if c.condition is None or "persistent.routes" not in c.condition.source}
    assert len(_menus(program)) >= 3
    picked = set()
    for seed in corpus.EXAMPLE_SEEDS:
        played = corpus.play(program, seed, images, corpus.EXAMPLE_PICKS[seed])
        assert played.interp.status is Status.ENDED, seed
        assert len(played.answers) == len(played.states)
        picked |= {(p.menu, p.choice) for p in played.interp.choices.picks}
        assert run_headless(program, seed=seed, image_files=images, inputs=played.inputs,
                            minigames=example_minigames()) == played.commands, seed
    assert picked == every, sorted(every - picked)


def test_ac_f07_45_every_menu_has_a_question_so_lines_and_checkpoints_align():
    """``continue_from`` below takes the k-th ``Say`` as the k-th checkpoint's line: true
    while every menu shows its question (one ``Say`` before each ``ShowMenu``)."""
    program, images = corpus.example_program(), corpus.example_images()
    assert all(m.question is not None for m in _menus(program))
    played = corpus.play(program, 1, images, corpus.EXAMPLE_PICKS[1])
    assert sum(type(c) is Say for c in played.commands) == len(played.states)
    assert sum(type(c) is ShowMenu for c in played.commands) == len(
        [a for a in played.answers if a.startswith("choose")])


# --- AC-F03-55 — every checkpoint survives a JSON round trip ------------------------------------

def assert_round_trips(state: GameState) -> None:
    text = json.dumps(state.to_json(), ensure_ascii=True)
    back = GameState.from_json(json.loads(text))
    assert back == state
    for name, value in state.variables.items():
        assert type_tree(back.variables[name]) == type_tree(value), name
    assert json.dumps(back.to_json(), ensure_ascii=True) == text


def test_ac_f03_55_example_checkpoints_round_trip():
    program, images = corpus.example_program(), corpus.example_images()
    count = 0
    for seed in range(1, 6):
        for state in corpus.play(program, seed, images).states:
            assert_round_trips(state)
            count += 1
    assert count >= 5 * 15


def _round_trips(name: str, played: corpus.Played) -> None:
    assert played.interp.status is Status.ENDED, name
    assert played.states, name
    for state in played.states:
        assert_round_trips(state)


def test_ac_f03_55_corpus_checkpoints_round_trip(small_played):
    """Every checkpoint of the small parts. A full 250-entry history (F13) round-trips in
    ``test_history.py``'s AC-F13-04."""
    for name, played in small_played.items():
        _round_trips(name, played)


@pytest.mark.slow
def test_ac_f03_55_realistic_corpus_checkpoints_round_trip(realistic_part):
    """About 4,400 checkpoints with up to 250 history entries each."""
    _round_trips("realistic", corpus.play(realistic_part, 1))


# AC-F03-55's AC-18 rows: test_restore.py's test_ac_f03_18_values_survive_round_trip_and_restore
# (the same VALUE_ROWS, round trip, type tree, and byte-identical dump, then the restore).


# --- AC-F03-56 — continuing from a round-tripped state -------------------------------------------

# The commands F03 and F04 define for a line and the end. Look-ahead requests (F04
# ``PrefetchImages``) and later features' own commands (F08 audio) are theirs to check.
STORY_TYPES = (Say, ShowStage, StoryEnded, StoryFailed)


def _story(commands: list) -> list:
    return [c for c in commands if type(c) in STORY_TYPES]


def _from(commands: list, k: int) -> list:
    """The story commands from the k-th line on."""
    says = [i for i, c in enumerate(commands) if type(c) is Say]
    return _story(commands[says[k]:])


def continue_from(program, images, played: corpus.Played, k: int) -> None:
    """A fresh launch restores the round-tripped checkpoint k and plays on: the original
    commands from k on, with the restore burst's stage and line marked ``restored``. Menus
    (F07) get the run's own answers from k on."""
    state = played.states[k]
    fresh = corpus.launched(program, images)
    restored = GameState.from_json(json.loads(json.dumps(state.to_json(), ensure_ascii=True)))
    assert fresh.restore(restored).result is RestoreResult.OK
    got = corpus.take_all(fresh)
    answers = iter(played.answers[k:])
    while fresh.status is Status.WAITING:
        if corpus.settle(fresh):                     # F09/F18: waits end at once (corpus.play)
            got += corpus.take_all(fresh)
            continue
        answer = next(answers)
        current = fresh.current
        if answer == "advance":
            fresh.post(Advance(current.sid))
        else:
            n = int(answer.removeprefix("choose "))
            fresh.post(Choose(current.sid, fresh.choices.waiting.pickable[n - 1]))
        fresh.run(10_000)
        got += corpus.take_all(fresh)
    got = _story(got)
    first = next(i for i, c in enumerate(got) if type(c) is Say)
    assert got[:first] == [ShowStage(state.stage, restored=True)]      # F04 07 I-1
    assert got[first].restored
    got[first] = dataclasses.replace(got[first], restored=False)
    assert got[first:] == _from(played.commands, k), k


def test_ac_f03_56_example_continues_from_every_checkpoint():
    program, images = corpus.example_program(), corpus.example_images()
    played = corpus.play(program, 3, images, corpus.EXAMPLE_PICKS[3])
    for k in range(len(played.states)):
        continue_from(program, images, played, k)


def _sample(n: int, every: int) -> list[int]:
    return sorted({*range(0, n, every), n - 1})


def test_ac_f03_56_corpus_continues_from_its_checkpoints(small_parts, small_played):
    """Every checkpoint of the small parts (the realistic part: ``slow``, below)."""
    for name, program in small_parts.items():
        played = small_played[name]
        for k in range(len(played.states)):
            continue_from(program, (), played, k)


@pytest.mark.slow
def test_ac_f03_56_realistic_corpus_every_5th_checkpoint(realistic_part):
    """About 890 continuations, 2–3 minutes; every one of the 4,431 would take about 13."""
    program = realistic_part
    played = corpus.play(program, 1)
    for k in _sample(len(played.states), 5):
        continue_from(program, (), played, k)


# --- AC-F11-66 — saves of the example game -------------------------------------------------------

def _saved_and_read(state: GameState) -> GameState:
    """``state`` through a save file: ``SaveEncoder``'s bytes read back by ``parse_full``."""
    from engine.persist import saves

    pieces = saves.encode_save(state, seq=1, saved_at=0, description=saves.describe(state, None),
                               chapter=None, game=None, game_version="0.1.0", jpeg=None)
    assert not isinstance(pieces, saves.TooLarge), pieces
    read = saves.parse_full(b"".join(pieces), game_id=None)
    assert read.status is saves.SlotStatus.OK, read.reason
    assert read.state == state
    return read.state


def _continue_saved(program, images, played: corpus.Played, k: int) -> None:
    """Checkpoint k saved, read back, restored into a fresh launch, and continued with the
    run's own inputs: the same story commands as the uninterrupted run (the restore burst
    marked ``restored``), and every later checkpoint with the same ``dice`` and variables."""
    state = _saved_and_read(played.states[k])
    fresh = corpus.launched(program, images)
    assert fresh.restore(state).result is RestoreResult.OK, k
    got = corpus.take_all(fresh)
    states = []
    answers = iter(played.answers[k:])
    while fresh.status is Status.WAITING:
        if corpus.settle(fresh):
            got += corpus.take_all(fresh)
            continue
        states.append(fresh.checkpoint())
        current = fresh.current
        answer = next(answers)
        if answer == "advance":
            fresh.post(Advance(current.sid))
        else:
            n = int(answer.removeprefix("choose "))
            fresh.post(Choose(current.sid, fresh.choices.waiting.pickable[n - 1]))
        fresh.run(10_000)
        got += corpus.take_all(fresh)
    assert fresh.status is Status.ENDED, k
    got = _story(got)
    first = next(i for i, c in enumerate(got) if type(c) is Say)
    assert got[first].restored
    got[first] = dataclasses.replace(got[first], restored=False)
    assert got[first:] == _from(played.commands, k), k
    expected = played.states[k:]
    assert [s.dice for s in states] == [s.dice for s in expected], k
    assert [dict(s.variables) for s in states] == [dict(s.variables) for s in expected], k


def test_ac_f11_66_every_checkpoint_saved_read_and_continued():
    """The walkthrough's choices (the goldens' five runs): at every checkpoint the state is
    encoded, read back with ``parse_full``, restored into a fresh driver, and continued
    with the same inputs; commands and ``dice`` results equal the uninterrupted run."""
    program, images = corpus.example_program(), corpus.example_images()
    count = 0
    for seed in corpus.EXAMPLE_SEEDS:
        played = corpus.play(program, seed, images, corpus.EXAMPLE_PICKS[seed])
        for k in range(len(played.states)):
            _continue_saved(program, images, played, k)
            count += 1
    assert count >= 5 * 25


def test_ac_f11_66_example_saves_load_at_their_line_after_the_patch(tmp_path):
    """``tests/fixtures/F11/example_saves/`` (five saves of ``game/``) load at their exact
    line in ``game/`` and in ``game/`` with the fixture patch (lines, a ``default``, and a
    label added), then play to the end; and a 10-hour save is under 1 MiB with its
    noise thumbnail (``gen_save_bench.py --hours 10``)."""
    from tests.persist import example_saves, gen_save_bench
    from tests.runtime.stage_story import load_game

    original = load_game(EXAMPLE)
    patched = load_game(example_saves.patched_copy(tmp_path / "game"))
    saved = example_saves.read_saves()
    assert len(saved) == 5
    assert {len(s.call_stack) for s in saved.values()} == {0, 1}
    assert sum(s.choices.waiting is not None for s in saved.values()) == 2
    for name, state in saved.items():
        lines = []
        for program in (original, patched):
            interp = example_saves.fresh(program)
            outcome = interp.restore(state)        # game/ moved the line: regenerate the
            assert outcome.result is RestoreResult.OK, (name, outcome)   # example saves
            cp = interp.checkpoint()
            assert (cp.position, cp.call_stack) == (state.position, state.call_stack), name
            current = interp.current
            lines.append((type(current), getattr(current, "text", None),
                          getattr(current, "question", None) is not None))
            assert ("lanterns_seen" in cp.variables) is (program is patched), name
            corpus.take_all(interp)
            while interp.status is Status.WAITING:          # plays on to the end
                if corpus.settle(interp):
                    continue
                current = interp.current
                if type(current) is Menu:
                    interp.post(Choose(current.sid, interp.choices.waiting.pickable[0]))
                else:
                    interp.post(Advance(current.sid))
                interp.run(10_000)
                corpus.take_all(interp)
            assert interp.status is Status.ENDED, name
        assert lines[0] == lines[1], name                 # the same line, after the patch

    bench = gen_save_bench.bench_save(10)
    from engine.persist import saves
    read = saves.parse_full(bench, game_id=gen_save_bench.GAME_ID)
    assert read.status is saves.SlotStatus.OK and read.meta.thumb_len > 0
    assert len(read.state.choices.picks) == 600 and len(read.state.variables) == 300
    assert len(bench) < 1 << 20, len(bench)


# --- AC-F19-35 — the example's endings and the promise route -----------------------------------

def _night_end(program) -> Menu:
    """The bridge's last menu (``routes/daichi.vns``): its third choice is the promise route."""
    (menu,) = [m for m in _menus(program) if any(
        c.condition is not None and "persistent.routes" in c.condition.source
        for c in m.choices)]
    return menu


def test_ac_f19_35_the_example_endings_and_the_promise_route(caplog):
    """``game/`` has the ``sad``, ``good``, and ``true`` endings, ``lock route promise …
    until sad, good``, ``lock ending`` lines, and ``[choice] show_locked = true``. AC-F19-24's
    runs 1–4 made on the example's last menu with one store and ``show_locked`` (every other
    menu: the first choice) reach the same endings and locks, and a dev load and launch, and
    the dev runs, log no warning."""
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.runtime.commands import TitleCard
    from engine.runtime.interpreter import Interpreter
    from engine.runtime.persistent import PersistentStore
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from engine.script.routes import Lock
    from tests.runtime.stage_story import position_names

    result = load_story(GamePaths(EXAMPLE.resolve()),
                        LoadOptions(dev=True, position_names=position_names(EXAMPLE),
                                    minigames=example_minigames()))
    assert result.program is not None and result.errors == () and result.warnings == ()
    program, images = result.program, corpus.example_images()
    assert [(e.name, e.heading, e.title) for e in program.endings] == [
        ("sad", "Sad End", "Paper Ashes"), ("good", "Good End", "The Lantern Festival"),
        ("true", "True End", "Hana's Promise")]
    assert [(r.name, tuple(r.until)) for r in program.routes] == [("promise", ("sad", "good"))]
    assert sorted((s.unlock, s.kind, s.name) for s in program.iter_statements()
                  if type(s) is Lock) == [(False, "ending", "good"), (False, "ending", "sad")]
    assert load_config(GamePaths(EXAMPLE.resolve())).config.choice.show_locked is True
    last = _night_end(program)
    store = PersistentStore(identity_scheme=program.identity_scheme)
    caplog.set_level(logging.DEBUG)

    def run(pick: int | None):
        """One playthrough on ``store``: the last menu's locks, then (with ``pick``) the
        commands to the end; without, the run stops at the last menu."""
        launch = run_launch(program, dev=True, images=ImageSource.from_files(images),
                            persistent=store)
        assert launch.namespace is not None and launch.warnings == ()
        interp = Interpreter(program, launch.namespace, dev=True, show_locked=True,
                             persistent=store, minigames=example_minigames())
        interp.new_game(1)
        interp.run(10_000)
        commands = corpus.take_all(interp)
        while interp.status is Status.WAITING:
            if corpus.settle(interp):
                commands += corpus.take_all(interp)
                continue
            current = interp.current
            if type(current) is Menu:
                if current.sid == last.sid and pick is None:
                    break
                n = pick if current.sid == last.sid else 1
                interp.post(Choose(current.sid, interp.choices.waiting.pickable[n - 1]))
            else:
                interp.post(Advance(current.sid))
            interp.run(10_000)
            commands += corpus.take_all(interp)
        menus = [c for c in commands if type(c) is ShowMenu]
        locked = [c.locked for c in menus[-1].choices]
        cards = list(dict.fromkeys(c.card.name for c in commands if type(c) is ShowStage
                                   and type(c.card) is TitleCard and c.card.kind == "ending"))
        return commands, locked, cards

    def new_endings() -> list:
        return [u for u in store.take_new_unlocks() if u[0] == "ending"]   # chapters too

    commands, locked, cards = run(1)
    assert commands[-1] == StoryEnded() and locked == [False, False, True] and cards == ["sad"]
    assert store.unlocked("ending") == ("sad",) and store.get("routes") == []
    assert new_endings() == [("ending", "sad")]
    commands, locked, cards = run(2)
    assert commands[-1] == StoryEnded() and locked == [False, False, True] and cards == ["good"]
    assert store.unlocked("ending") == ("sad", "good") and store.get("routes") == ["promise"]
    assert new_endings() == [("ending", "good")]
    commands, locked, cards = run(3)
    assert commands[-1] == StoryEnded() and locked == [False, False, False] and cards == ["true"]
    assert store.unlocked("ending") == ("true",) and store.get("routes") == []
    assert new_endings() == [("ending", "true")]
    commands, locked, cards = run(None)
    assert type(commands[-1]) is ShowMenu and locked == [False, False, True] and cards == []
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# --- AC-F21-40 — the example's codex ----------------------------------------------------------

def test_ac_f21_40_the_example_codex(caplog):
    """``game/`` declares *Paper Lanterns*' codex: two tips in two categories, an item with a
    picture under ``images/items/``, a ``lock item``, and a branch on ``codex.tips``. A dev
    load and launch over the real image files log no W12 or W140–W142, and a dev run with
    the goldens' answers (seed 1) releases a ``CodexAdded`` for each unlock line as the story
    reaches it, logging no warning (no W141)."""
    from engine.core.paths import GamePaths
    from engine.runtime.commands import CodexAdded
    from engine.script import load_story
    from engine.script.codex import CodexLock
    from engine.script.loader import LoadOptions
    from engine.script.nodes import If
    from tests.runtime.stage_story import position_names

    result = load_story(GamePaths(EXAMPLE.resolve()),
                        LoadOptions(dev=True, position_names=position_names(EXAMPLE),
                                    minigames=example_minigames()))
    assert result.program is not None and result.errors == () and result.warnings == ()
    program, images = result.program, corpus.example_images()
    entries = {e.name: e for e in program.codex}
    tips = [e for e in entries.values() if e.kind == "tip"]
    assert len({e.category.text for e in tips}) >= 2 and len(tips) >= 2
    pictured = [e for e in entries.values() if e.kind == "item" and e.image is not None]
    assert pictured and all(f"images/{e.image.replace(' ', '/')}.png" in images
                            for e in pictured)
    lines = [s for s in program.iter_statements() if type(s) is CodexLock]
    assert any(not s.unlock and s.kind == "item" for s in lines)
    conditions = [b.condition.source for s in program.iter_statements() if type(s) is If
                  for b in s.branches if b.condition is not None]
    assert any("codex.tips" in source for source in conditions)
    launch = run_launch(program, dev=True, images=ImageSource.from_files(images))
    assert launch.namespace is not None and launch.warnings == ()
    caplog.set_level(logging.DEBUG)
    inputs = corpus.play(program, 1, images, corpus.EXAMPLE_PICKS[1]).inputs
    commands = run_headless(program, seed=1, image_files=images, inputs=inputs, dev=True,
                            minigames=example_minigames())
    assert commands[-1] == StoryEnded()
    added = [(c.kind, c.name, c.title) for c in commands if type(c) is CodexAdded]
    assert added == [("item", "festival_map", "Festival Map"),       # the prologue (F25-4)
                     ("tip", "lanterns", "Paper Lanterns"),          # the riverbank
                     ("item", "fortune_slip", "Fortune Slip"),       # draw_fortune
                     ("item", "lantern", "Paper Lantern"),           # the stall
                     ("tip", "river_god", "The River God")]          # the bridge talk
    assert {(s.kind, s.name) for s in lines if s.unlock} == {(k, n) for k, n, _ in added}
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# --- AC-F20-71 — the example's flowchart ------------------------------------------------------

def test_ac_f20_71_the_example_flowchart(caplog):
    """*Paper Lanterns* marks one scene (the lantern stall), titles one choice (the bridge's
    last menu), and hides the true route's nodes (``flowchart scene … hidden no jump`` and
    ``flowchart hidden`` above the True End). A dev load with the flowchart gives no warning
    (no W150–W153), and with one store and one ``flow`` holder a headless run reaches the Sad
    End, a jump to the titled choice offers it again, and its second choice reaches the Good
    End, with no warning logged."""
    from engine.core.paths import GamePaths
    from engine.runtime.flowchart import FlowStates
    from engine.runtime.persistent import PersistentStore
    from engine.script import load_story
    from engine.script.flowgraph import FlowOptions
    from engine.script.loader import LoadOptions
    from tests.runtime.stage_story import position_names

    result = load_story(GamePaths(EXAMPLE.resolve()),
                        LoadOptions(dev=True, position_names=position_names(EXAMPLE),
                                    minigames=example_minigames(), flowchart=FlowOptions()))
    assert result.program is not None and result.errors == () and result.warnings == ()
    program, images = result.program, corpus.example_images()
    nodes = {n.id: n for n in program.flowgraph.nodes}
    assert nodes["scene:lantern_stall"].title == ("The Lantern Stall",)
    (choice,) = [n for n in nodes.values() if n.kind == "choice"]
    assert choice.anchor == _night_end(program).sid
    assert choice.title == ("How should the night end?",)
    assert [i for i, n in nodes.items() if n.hidden] == ["scene:promise", "ending:true"]
    assert nodes["scene:promise"].no_jump

    store = PersistentStore(identity_scheme=program.identity_scheme)
    holder = FlowStates()
    caplog.set_level(logging.DEBUG)

    def run(inputs: list[str]) -> list:
        return run_headless(program, seed=1, image_files=images, inputs=inputs, dev=True,
                            minigames=example_minigames(), persistent=store, flow=holder)

    commands = run(corpus.example_inputs(1, corpus.EXAMPLE_PICKS[1]))      # Walk Hana home
    assert commands[-1] == StoryEnded() and holder.reached[-1] == "ending:sad"
    assert choice.id in holder.reached and holder[choice.id] is not None
    commands = run([f"jump {choice.id}", "choose 2"])                    # Stay: the festival
    jumped = next(c for c in commands if type(c) is ShowMenu)
    assert jumped.sid == choice.anchor and jumped.restored
    assert commands[-1] == StoryEnded() and holder.reached[-1] == "ending:good"
    assert store.is_unlocked("ending", "good")
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
