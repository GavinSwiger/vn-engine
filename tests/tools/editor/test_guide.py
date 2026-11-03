"""F47 P1-I: the Guide model and Studio's per-game state (``01-design.md`` PR-F47-26, §6.4;
``04-technical.md`` §3.1, §8.4, §10). The pure half of AC-F47-25; the Tk half (the pane,
Show me opening each place) is W6's.

One test: the seven steps tick from check data as §4.7 says (on a new sample game only what
the author adds counts, so two steps start ticked), each step has its Show me target, and the
Guide's open/closed state and "played" are remembered per game in ``.studio/studio.json``
(missing or damaged → defaults; a junction stops writing)."""

import dataclasses
from pathlib import Path

from engine.tools.editor import files, guide, studiostate
from engine.tools.editor.guide import GuideFacts, ShowMe
from engine.tools.editor.studiostate import StateProblem, StudioState
from tests.tools.editor.conftest import link_dir
from tests.tools.f45_games import check

TEXTS = ["Name your game", "Add a character", "Add a background", "Write your first scene",
         "Add a choice", "Add an ending", "Play it"]


def _facts(game: Path, *, played: bool = False) -> GuideFacts | None:
    texts = {p.relative_to(game).as_posix(): p.read_text(encoding="utf-8")
             for p in (game / "script").rglob("*.vns")}
    return guide.facts_from(check(game), guide.read_scenes(texts), folder_name=game.name,
                            config_text=(game / "config.toml").read_text(encoding="utf-8"),
                            played=played)


def _ticked(facts: GuideFacts, *, sample: bool) -> list[int]:
    return [row.number for row in guide.steps(facts, sample=sample) if row.done]


def test_ac_f47_25_guide_steps_tick_and_state_is_remembered(tmp_path):
    # The steps, their §6.4 texts and Show me targets; nothing ticked → everything ticked.
    empty = guide.steps(GuideFacts(folder_name="my game", title="my game"))
    assert [row.text for row in empty] == TEXTS
    assert [row.number for row in empty] == list(range(1, 8))
    assert not any(row.done for row in empty) and not guide.all_done(empty)
    assert [row.show_me for row in empty] == [
        ShowMe(guide.SETTINGS, "game"), ShowMe(guide.DATABASE, "characters"),
        ShowMe(guide.DATABASE, "pictures"), ShowMe(guide.STORY_MAP, "start"),
        ShowMe(guide.INSERT, "choice"), ShowMe(guide.INSERT, "ending"), ShowMe(guide.PLAY)]
    full = GuideFacts(folder_name="my game", title="Night Ferry", characters=frozenset({"rin"}),
                      backgrounds=frozenset({"bg pier"}), endings=frozenset({"good"}),
                      start_rows=3, choices=1, played=True)
    assert guide.all_done(guide.steps(full))
    assert guide.DONE_TEXT == "Your game runs from start to an ending. Well done!"
    for change, step in (({"title": " my game "}, 1), ({"title": None}, 1),
                         ({"characters": frozenset()}, 2), ({"backgrounds": frozenset()}, 3),
                         ({"start_rows": 2}, 4), ({"choices": 0}, 5),
                         ({"endings": frozenset()}, 6), ({"played": False}, 7)):
        rows = guide.steps(dataclasses.replace(full, **change))
        assert [row.number for row in rows if not row.done] == [step], change

    # A new sample game: only the author's own additions count, so 4 and 5 start ticked.
    game = tmp_path / "Lantern Night"
    assert files.new_game(game) == game.absolute()
    facts = _facts(game)
    assert facts is not None
    base = guide.SAMPLE_BASELINE
    assert (facts.characters, facts.backgrounds, facts.endings) == (
        base.characters, base.backgrounds, base.endings)
    assert _ticked(facts, sample=True) == [4, 5]
    assert _ticked(facts, sample=False) == [2, 3, 4, 5, 6]
    database = game / "script" / "database.vns"
    database.write_text(database.read_text(encoding="utf-8")
                        + 'define rin = Character("Rin")\n', encoding="utf-8")
    config = game / "config.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(
        'title = "Lantern Night"', 'title = "Rin\'s Night"'), encoding="utf-8")
    assert _ticked(_facts(game, played=True), sample=True) == [1, 2, 4, 5, 7]
    assert guide.facts_from(dataclasses.replace(check(game), loaded=False), [],
                            folder_name=game.name, config_text="", played=False) is None
    assert guide.title_of("[game\ntitle = 1") is None

    # Remembered per game: New game wrote the Guide open; changes round-trip.
    assert studiostate.read_state(game) == StudioState(guide_open=True, sample=True)
    assert studiostate.with_change(game, guide_open=False, played=True) is None
    assert studiostate.read_state(game) == StudioState(played=True, sample=True)
    other = tmp_path / "other"
    other.mkdir()
    assert studiostate.read_state(other) == StudioState()           # missing → defaults
    target = studiostate.state_path(game)
    for data, expected in ((b"{nope", StateProblem("damaged")),
                           (b'{"guide_open": NaN}', StateProblem("damaged")),
                           (b"[]", StateProblem("damaged")),
                           (b'{"guide_open": 1, "played": true, "x": 2}',
                            StudioState(played=True))):
        target.write_bytes(data)
        assert studiostate.read_state(game) == expected, data
    assert studiostate.with_change(game, guide_open=True) is None   # damaged → rewritten
    assert studiostate.read_state(game) == StudioState(guide_open=True, played=True)

    # A junction for .studio: read says so, and nothing is written through it.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    link_dir(linked / ".studio", elsewhere)
    problem = studiostate.read_state(linked)
    assert isinstance(problem, StateProblem) and problem.link
    assert isinstance(studiostate.with_change(linked, played=True), StateProblem)
    assert list(elsewhere.iterdir()) == []
