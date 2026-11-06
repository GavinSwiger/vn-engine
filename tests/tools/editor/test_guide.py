"""The Guide model and Studio's per-game state (F47 ``01-design.md`` PR-F47-26, §6.4;
``04-technical.md`` §3.1, §8.4, §10; the walkthrough plan of 2026-11). The pure half of
AC-F47-25; the Tk half (the pane, Show me opening each place) is ``test_studio_guide``'s.

Every step's tick rule, one by one; the sample baseline (a new sample game has nothing
ticked, and only what the author adds counts); the marks a check leaves; the facts staying
cheap on a long story (only ``start`` is parsed); each step's Read more heading being in the
beginner's guide; and the Guide's state remembered per game in ``.studio/studio.json``."""

import dataclasses
import re
from pathlib import Path

import pytest

from engine.tools.editor import files, guide, guidereader, studiostate
from engine.tools.editor.guide import GuideFacts, MenuFacts, ShowMe
from engine.tools.editor.studiostate import StateProblem, StudioState
from tests.tools.editor.conftest import link_dir
from tests.tools.f45_games import check

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / guide.GUIDE_DOC
FIRST = ["Play the sample", "Name your game", "Add a character", "Give them pictures",
         "Add a background", "Write your first scene", "Add a choice", "Add an ending",
         "Play to an ending"]
EMPTY = GuideFacts(folder_name="my game", title="my game")
OWN_MENU = MenuFacts("start", frozenset({"Stay", "Go"}))
SAMPLE_MENU = MenuFacts("start", frozenset({"Write a wish and send one",
                                           "Just watch this year"}), True, True)


def uses(**kinds: str) -> dict:
    return {kind: frozenset({line}) for kind, line in kinds.items()}


# Each step's facts, alone: they tick that step (and the ones listed after them).
TICKS: dict[str, tuple[dict, set[str]]] = {
    "play_sample": ({"played": True}, set()),
    "name": ({"title": "Night Bakery"}, set()),
    "character": ({"characters": frozenset({"mika"})}, set()),
    "looks": ({"characters": frozenset({"mika"}), "images": frozenset({"mika happy"})},
              {"character"}),
    "background": ({"backgrounds": frozenset({"bg bakery"})}, set()),
    "scene": ({"characters": frozenset({"mika"}), "start_rows": 3,
               "start_speakers": frozenset({"mika"})}, {"character"}),
    "choice": ({"menus": (OWN_MENU,)}, set()),
    "ending": ({"endings": frozenset({"warm"})}, set()),
    "play": ({"reached": frozenset({"warm"})}, set()),
    "kit": ({"theme": {"kit": "cozy"}}, set()),
    "scheme": ({"theme": {"preset": "cozy_cafe"}}, set()),
    "title_screen": ({"theme": {"title": {"background_image": "gui/bakery.png"}}}, set()),
    "music": ({"uses": uses(music='play music "music/x.ogg"')}, set()),
    "sound": ({"uses": uses(sound='play sound "sound/bell.ogg"')}, set()),
    "effect": ({"uses": uses(effect="shake small")}, set()),
    "colors": ({"characters": frozenset({"mika"}), "styled": frozenset({"mika"})},
               {"character"}),
    "stage": ({"marks": frozenset({guide.STAGE_VIEWED})}, set()),
    "variable": ({"variables": frozenset({"helped"})}, set()),
    "set_in_choice": ({"uses": uses(set_in_choice="$ helped = True")}, set()),
    "meter": ({"meters": frozenset({"mood"})}, set()),
    "meter_use": ({"uses": uses(meter_show="show meter mood", points="points mood += 2")},
                  set()),
    "condition": ({"menus": (dataclasses.replace(OWN_MENU, tested=True),)}, {"choice"}),
    "roll": ({"menus": (dataclasses.replace(OWN_MENU, rolled=True),)}, {"choice"}),
    "three_endings": ({"endings": frozenset({"warm", "cold", "apprentice"})}, {"ending"}),
    "unreachable": ({"marks": frozenset({guide.UNREACHABLE_FIXED})}, set()),
    "remembered": ({"remembered": frozenset({"knows_recipe"})}, set()),
    "two_endings": ({"reached": frozenset({"warm", "cold"})}, {"play"}),
    "second_part": ({"script_refs": frozenset({"script/main.vns", "script/night2.vns"})},
                    set()),
    "clock": ({"uses": uses(clock="clock go to day 2 Night")}, set()),
    "items": ({"items": frozenset({"coin"}), "uses": uses(unlock_item="unlock item coin 10")},
              set()),
    "shop": ({"uses": uses(shop="minigame shop stock=s into b")}, set()),
    "letter": ({"contacts": frozenset({"mika"}), "uses": uses(send="send x from mika")},
               set()),
    "reply": ({"uses": uses(reply='if inbox.reply("x") == "yes":')}, set()),
    "tip": ({"tips": frozenset({"sourdough"}), "uses": uses(unlock_tip="unlock tip sourdough")},
            set()),
    "ask_name": ({"uses": uses(ask_text="minigame ask_text into player_name")}, set()),
    "chapter": ({"uses": uses(chapter='chapter night2 "Chapter 2"')}, set()),
    "fix_problem": ({"marks": frozenset({guide.ERROR_FIXED})}, set()),
    "play_scene": ({"marks": frozenset({guide.PLAYED_SCENE})}, set()),
    "hot_update": ({"marks": frozenset({guide.HOT_UPDATED})}, set()),
    "cleanup": ({"marks": frozenset({guide.LEFTOVERS_CLEARED})}, set()),
    "build": ({"marks": frozenset({guide.BUILT})}, set()),
}
# Facts that must not tick their step: half a rule, or the sample's own things.
NOT_YET: dict[str, list[dict]] = {
    "name": [{"title": " my game "}, {"title": None}],
    "looks": [{"characters": frozenset({"mika"}), "images": frozenset({"mika"})},
              {"images": frozenset({"hana happy"})}],
    "scene": [{"characters": frozenset({"mika"}), "start_rows": 2,
               "start_speakers": frozenset({"mika"})},
              {"characters": frozenset({"mika"}), "start_rows": 9,
               "start_speakers": frozenset({"hana"})}],
    "kit": [{"theme": {"kit": ""}}],
    "title_screen": [{"theme": {"title": {}}}],
    "meter_use": [{"uses": uses(meter_show="show meter mood")}],
    "items": [{"items": frozenset({"coin"})}],
    "letter": [{"uses": uses(send="send x from mika")}],
    "remembered": [{"remembered": frozenset({"knows_recipe"}), "errors": 1}],
    "three_endings": [{"endings": frozenset({"warm", "cold"})}],
    "fix_problem": [{"marks": frozenset({guide.ERROR_SEEN})}],
}


def _ticked(facts: GuideFacts, *, sample: bool = False) -> set[str]:
    return {row.key for chapter in guide.chapters(facts, sample=sample)
            for row in chapter.rows if row.done}


def _game_facts(game: Path, **state) -> GuideFacts | None:
    texts = {p.relative_to(game).as_posix(): p.read_text(encoding="utf-8")
             for p in (game / "script").rglob("*.vns")}
    return guide.facts_from(check(game), texts, folder_name=game.name,
                            config_text=(game / "config.toml").read_text(encoding="utf-8"),
                            played=False, **state)


def test_the_chapters_follow_the_beginners_guide():
    chapters = guide.chapters(EMPTY, sample=True)
    assert [c.title for c in chapters] == ["Your first game", "Make it yours",
                                           "Choices that matter", "Bigger games",
                                           "Test and share"]
    assert [len(c.rows) for c in chapters] == [9, 8, 10, 9, 5]
    assert [row.text for row in chapters[0].rows] == FIRST
    assert [c.optional for c in chapters] == [False, False, False, True, False]
    assert chapters[0].current and not any(c.current for c in chapters[1:])
    assert not any(c.done for c in chapters) and not _ticked(EMPTY, sample=True)
    # Without the sample there is no sample to play.
    assert [row.key for row in guide.steps(EMPTY)][:2] == ["name", "character"]
    # Every step has a hint, a Show me and a Read more heading the guide has.
    headings = set(re.findall(r"^#{2,3} (.+?)\s*$", DOC.read_text(encoding="utf-8"), re.M))
    from engine.tools.editor.database import ALL_CATEGORIES
    from engine.tools.editor.guidepane import insert_doc
    places = {guide.SETTINGS, guide.DATABASE, guide.STORY_MAP, guide.INSERT, guide.PLAY,
              guide.MENU, guide.PROBLEMS, guide.UPDATE}
    for chapter in guide.CHAPTERS:
        assert chapter.section in headings, chapter.section
        for step in chapter.steps:
            assert step.hint.endswith(".") and step.section in headings, step.key
            assert step.show_me.place in places, step.key
            if step.show_me.place == guide.DATABASE:
                assert step.show_me.item in ALL_CATEGORIES, step.key
            if step.show_me.place == guide.INSERT:
                assert insert_doc(step.show_me.item) is not None, step.key
    keys = [step.key for chapter in guide.CHAPTERS for step in chapter.steps]
    assert sorted(keys) == sorted(TICKS) and len(set(keys)) == len(keys)


@pytest.mark.parametrize("key", list(TICKS))
def test_each_step_ticks_from_its_own_facts_only(key):
    change, also = TICKS[key]
    facts = dataclasses.replace(EMPTY, **change)
    assert _ticked(facts, sample=True) == {key} | also
    for other in NOT_YET.get(key, []):
        assert key not in _ticked(dataclasses.replace(EMPTY, **other), sample=True), other


def test_the_sample_baseline_counts_only_the_authors_own():
    base = guide.SAMPLE_BASELINE
    sample = dataclasses.replace(
        EMPTY, characters=base.characters, images=frozenset({"hana happy", "daichi grin"}),
        backgrounds=base.backgrounds, endings=base.endings, reached=base.endings,
        variables=base.variables, menus=(SAMPLE_MENU,),
        uses={"music": base.lines, "sound": base.lines, "effect": base.lines,
              "set_in_choice": base.lines},
        start_rows=13, start_speakers=frozenset({"hana", "daichi"}),
        script_refs=base.script_refs, styled=frozenset({"hana"}))
    assert _ticked(sample, sample=True) == set()
    # The same facts in a game that didn't come from the sample are the author's.
    assert {"character", "looks", "background", "scene", "choice", "ending", "play",
            "music", "effect", "variable", "two_endings", "second_part"} <= _ticked(sample)
    # What the author adds next to the sample's counts.
    mine = dataclasses.replace(sample, characters=base.characters | {"mika"},
                               start_speakers=frozenset({"mika"}),
                               menus=(SAMPLE_MENU, OWN_MENU),
                               uses={"music": base.lines | {'play music "m.ogg"'}})
    assert _ticked(mine, sample=True) == {"character", "scene", "choice", "music"}
    # Show me aims at the author's own character and choice.
    rows = {row.key: row for c in guide.chapters(mine, sample=True) for row in c.rows}
    assert rows["looks"].show_me == ShowMe(guide.DATABASE, "character", "mika")
    assert rows["condition"].show_me == ShowMe(guide.STORY_MAP, "start")


def test_a_new_sample_game_ticks_nothing_and_the_authors_work_does(tmp_path):
    game = tmp_path / "Lantern Night"
    assert files.new_game(game) == game.absolute()
    facts = _game_facts(game)
    assert facts is not None
    base = guide.SAMPLE_BASELINE
    assert (facts.characters, facts.backgrounds, facts.endings, facts.variables) == (
        base.characters, base.backgrounds, base.endings, base.variables)
    assert {m.options for m in facts.menus} == set(base.menus)
    assert set().union(*facts.uses.values()) <= base.lines        # the baseline is current
    assert facts.script_refs == base.script_refs
    assert _ticked(facts, sample=True) == set()                    # FRICTION 7

    # Part 1 of the guide, written as the guide writes it.
    (game / "script" / "database.vns").write_text(
        (game / "script" / "database.vns").read_text(encoding="utf-8")
        + 'define mika = Character("Mika", color="#5a3a1a", text_color="#402010")\n'
          'default helped = False\n', encoding="utf-8")
    main = game / "script" / "main.vns"
    text = main.read_text(encoding="utf-8")
    main.write_text(text[:text.index("label start:")] + """label start:
    scene bg river_dusk with fade
    play music "music/lantern_walk.wav" fadein 2.0
    "It is almost midnight."
    mika "Oh! A customer!"
    menu:
        mika "Can I get you something?"
        "Ask for the warmest bread":
            $ helped = True
            jump warm_bread
        "Offer to help" if helped:
            jump warm_bread
        "Say you were just looking":
            jump just_looking

label warm_bread:
    ending warm "Good End" "A Warm Loaf"

label just_looking:
    ending cold "Quiet End" "Just Looking"
""", encoding="utf-8")
    facts = _game_facts(game, reached=["warm", "lantern"])
    assert facts is not None and facts.errors == 0
    assert _ticked(facts, sample=True) == {"character", "scene", "choice", "ending", "play",
                                           "music", "effect", "colors", "variable",
                                           "set_in_choice", "condition"}
    assert guide.facts_from(dataclasses.replace(check(game), loaded=False), {},
                            folder_name=game.name, config_text="", played=False) is None
    assert guide.title_of("[game\ntitle = 1") is None


def test_the_facts_parse_only_the_start_scene(monkeypatch):
    """A check finishes after every typing pause: on a long story the facts read each
    script line by line (cached per text) and parse only ``start``."""
    texts = {f"script/ch{n}.vns": "".join(
        f'label s{n}_{i}:\n    "line"\n    menu:\n        "A":\n            $ x = 1\n'
        f'        "B" if x:\n            jump s{n}_{i}\n' for i in range(20)) for n in range(5)}
    texts["script/main.vns"] = 'label start:\n    "hi"\n    "there"\n    jump s0_0\n'
    parsed: list[str] = []
    real = guide.parse_chunk
    monkeypatch.setattr(guide, "parse_chunk",
                        lambda ref, chunk, **k: parsed.append(chunk) or real(ref, chunk, **k))
    guide.scan_text.cache_clear()
    guide.start_read.cache_clear()
    start_rows, choices, _speakers, menus, found, _decls = guide.scan_scenes(texts)
    assert (start_rows, choices) == (3, 100) and all(m.tested for m in menus)
    assert found["set_in_choice"] == {"$ x = 1"}
    assert len(parsed) == 1 and parsed[0].startswith("label start:")
    guide.scan_scenes(texts)                                        # unchanged: cached
    assert len(parsed) == 1


def test_a_check_marks_a_problem_seen_then_fixed():
    marks = guide.note_check((), errors=2, unreachable=None, leftovers=None)
    assert marks == {guide.ERROR_SEEN}
    marks = guide.note_check(marks, errors=0, unreachable=True, leftovers=True)
    assert marks == {guide.ERROR_SEEN, guide.ERROR_FIXED, guide.UNREACHABLE_SEEN,
                     guide.LEFTOVERS_SEEN}
    same = guide.note_check(marks, errors=0, unreachable=None, leftovers=None)  # can't tell
    assert same == marks
    done = guide.note_check(marks, errors=0, unreachable=False, leftovers=False)
    assert {guide.UNREACHABLE_FIXED, guide.LEFTOVERS_CLEARED} <= done
    # Nothing seen: nothing fixed.
    assert guide.note_check((), errors=0, unreachable=False, leftovers=False) == frozenset()


def test_chapters_open_in_order_and_bigger_games_can_be_skipped():
    first = {key: TICKS[key][0] for key in ("play_sample", "name", "looks", "background",
                                            "scene", "choice", "ending", "play")}
    merged: dict = {}
    for change in first.values():
        for name, value in change.items():
            merged[name] = merged.get(name, frozenset()) | value \
                if isinstance(value, frozenset) else value
    merged["menus"] = (OWN_MENU,)
    facts = dataclasses.replace(EMPTY, **merged)
    chapters = guide.chapters(facts, sample=True)
    assert chapters[0].done and chapters[1].current
    skip = guide.skip_mark("bigger")
    through_three = dataclasses.replace(facts, marks=frozenset({skip}))
    found = guide.chapters(through_three, sample=True)
    assert found[3].skipped and not found[3].current and found[1].current
    # A skipped chapter that is done anyway shows as done.
    assert not guide.chapters(EMPTY, sample=True)[3].skipped


def test_studio_json_remembers_the_guide_per_game(tmp_path):
    game = tmp_path / "Lantern Night"
    files.new_game(game)
    assert studiostate.read_state(game) == StudioState(guide_open=True, sample=True)
    assert studiostate.with_change(game, guide_open=False, played=True,
                                   guide=("stage_viewed", "skip_bigger"),
                                   reached=("warm",)) is None
    assert studiostate.read_state(game) == StudioState(
        played=True, sample=True, guide=("skip_bigger", "stage_viewed"), reached=("warm",))
    raw = studiostate.state_path(game).read_text(encoding="utf-8")
    assert '"guide": ["skip_bigger", "stage_viewed"]' in raw and '"reached": ["warm"]' in raw
    assert b'"guide"' not in studiostate.encode_state(StudioState())  # only when not empty
    odd = b'{"guide": ["ok", 3, "../x"], "reached": ["warm", "' + b"x" * 80 + b'"]}'
    assert studiostate.decode_state(odd) == StudioState(guide=("ok",), reached=("warm",))
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


def test_the_reader_formats_the_guide():
    rows = guidereader.blocks("# Title\n\nSome **bold** and `code`,\nwrapped.\n\n"
                              "- one\n  more\n   - two\n\n```\nlabel start:\n```\n## Part")
    assert rows[0] == ("h1", [("Title", "plain")])
    assert ("p", [("Some ", "plain"), ("bold", "bold"), (" and ", "plain"),
                  ("code", "code"), (", wrapped.", "plain")]) in rows
    assert ("li0", [("•  ", "plain"), ("one more", "plain")]) in rows
    assert ("li1", [("•  ", "plain"), ("two", "plain")]) in rows
    assert ("pre", [("label start:", "code")]) in rows and rows[-1][0] == "h2"
    headings = {"".join(t for t, _s in parts) for kind, parts in
                guidereader.blocks(DOC.read_text(encoding="utf-8")) if kind[0] == "h"}
    assert {s.section for c in guide.CHAPTERS for s in c.steps} <= headings
