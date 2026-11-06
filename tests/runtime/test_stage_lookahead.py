"""F04 step 7 — look-ahead (``04-technical.md`` §7.6, TR-F04-07): AC-F04-42.

``lookahead`` walks the statements after a checkpoint, without running any, and names the
images the next lines may show; ``take_checkpoint`` holds the result after the line.
"""

import shutil
from dataclasses import replace
from pathlib import Path

from engine.runtime.commands import Advance, PrefetchImages, Say
from engine.runtime.stage import (LOOKAHEAD_MAX_IMAGES, LOOKAHEAD_MAX_STATEMENTS, StageState,
                                  lookahead)
from tests.runtime.stage_story import F04, launched, load_game, story_game
from tests.runtime.story import fingerprint


def _waiting(program, text: str | None = None):
    """A new game run to its first line (or on to the line whose text is ``text``)."""
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    while text is not None and interp.current.text != text:
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
    interp.take_commands(10_000)
    return interp


def _lookahead_game(root: Path):
    shutil.copytree(F04 / "lookahead", root)
    return load_game(root)


# --- AC-F04-42 -----------------------------------------------------------------------------------

def test_ac_f04_42_names_what_comes_next(tmp_path):
    interp = _waiting(_lookahead_game(tmp_path / "game"))
    assert interp.current.text == "A." and interp.stage.index_of("hana") is not None
    found = lookahead(interp, interp.current)
    assert set(found.backgrounds) == {"bg a", "bg b", "bg c"}
    assert set(found.sprites) == {"daichi grin", "hana pout"}   # one-word show hana skipped
    # Nearest first, breadth first: both branches, the statement after the if, the call.
    assert found.backgrounds == ("bg a", "bg b", "bg c")
    assert found.sprites == ("daichi grin", "hana pout")


def test_ac_f04_42_dialogue_words_need_the_speaker_on_stage(tmp_path):
    interp = _waiting(_lookahead_game(tmp_path / "game"))
    interp.stage = StageState(None, ())                 # hana not on stage
    found = lookahead(interp, interp.current)
    # The one-word show hana now puts her on the (simulated) stage as "hana", so her
    # words count; without that show they wouldn't (test_hide_and_scene_...).
    assert found.sprites == ("hana", "daichi grin", "hana pout")
    assert set(found.backgrounds) == {"bg a", "bg b", "bg c"}


def test_ac_f04_42_the_burst_carries_it_after_the_line(tmp_path):
    interp = launched(_lookahead_game(tmp_path / "game"))
    interp.new_game(42)
    interp.run(10_000)
    burst = interp.take_commands(100)
    assert type(burst[-2]) is Say and burst[-1] == PrefetchImages(
        ("bg a", "bg b", "bg c"), ("daichi grin", "hana pout"))


def test_ac_f04_42_at_most_200_statements_and_8_names(tmp_path):
    shows = [f"show s{n} x" for n in range(1, 301)]
    interp = _waiting(story_game(tmp_path / "g1", ['"A."', *shows]))
    calls = []
    real = interp._successor

    def spy(stmt):
        calls.append(stmt)
        return real(stmt)

    interp._successor = spy
    found = lookahead(interp, interp.current)
    assert len(calls) <= LOOKAHEAD_MAX_STATEMENTS
    assert found == PrefetchImages((), tuple(f"s{n} x" for n in range(1, 9)))
    assert LOOKAHEAD_MAX_IMAGES == 8


def test_ac_f04_42_the_walk_stops_after_200_statements(tmp_path):
    for count, seen in ((LOOKAHEAD_MAX_STATEMENTS - 1, True), (LOOKAHEAD_MAX_STATEMENTS, False)):
        lines = ['"A."', *["$ x = 1"] * count, "show far x", '"B."']
        interp = _waiting(story_game(tmp_path / f"g{count}", lines))
        calls = []
        real = interp._successor

        def spy(stmt, real=real, calls=calls):
            calls.append(stmt)
            return real(stmt)

        interp._successor = spy
        found = lookahead(interp, interp.current)
        assert len(calls) <= LOOKAHEAD_MAX_STATEMENTS
        assert (found == PrefetchImages((), ("far x",))) is seen, count
        assert (found is None) is not seen


def test_ac_f04_42_pure_and_repeatable(tmp_path):
    interp = _waiting(_lookahead_game(tmp_path / "game"))
    before = fingerprint(interp)
    first = lookahead(interp, interp.current)
    second = lookahead(interp, interp.current)
    assert first == second
    assert fingerprint(interp) == before


# --- The walk's edges (04 §7.6) ------------------------------------------------------------------

def test_return_and_the_end_of_a_label_stop_the_walk(tmp_path):
    program = story_game(tmp_path / "g", ['"A."', "call side", '"B."', "scene bg after"],
                         top="label side:\n    show inside x\n    return\n    show never x\n")
    interp = _waiting(program)
    found = lookahead(interp, interp.current)
    assert found == PrefetchImages(("bg after",), ("inside x",))


def test_a_loop_is_visited_once(tmp_path):
    program = story_game(tmp_path / "g", ['"A."', "show hana sad", "jump start"])
    interp = _waiting(program)
    calls = []
    real = interp._successor
    interp._successor = lambda stmt: (calls.append(stmt), real(stmt))[1]
    assert lookahead(interp, interp.current) == PrefetchImages((), ("hana sad",))
    assert len(calls) <= 3


def test_image_tag_speakers_and_as_sprites(tmp_path):
    # d's image_tag is "daichi"; girl_a shows lantern_girl art; narration has no speaker.
    program = story_game(tmp_path / "g", [
        "show daichi grin", "show lantern_girl as girl_a", '"A."', 'd sigh "B."',
        '"C."', "show lantern_girl as girl_a at left", "show daichi", "show girl_a"])
    interp = _waiting(program)
    found = lookahead(interp, interp.current)
    # One-word shows that keep a sprite's image are skipped; show girl_a would change
    # girl_a's image to "girl_a" (SR-F04-11), so it is named.
    assert found == PrefetchImages((), ("daichi sigh", "girl_a"))


def test_nothing_ahead_gives_none(tmp_path):
    interp = _waiting(story_game(tmp_path / "g", ['"A."', '"B."']))
    assert lookahead(interp, interp.current) is None
    interp2 = launched(story_game(tmp_path / "g2", ['"A."', '"B."']))
    interp2.new_game(1)
    interp2.run(10_000)
    burst_types = [type(c) for c in interp2.take_commands(100)]
    assert PrefetchImages not in burst_types


def test_a_character_who_enters_ahead_has_their_words_fetched(tmp_path):
    # v1 perf review: "on stage" is simulated along the walk, so hana's first line after
    # she enters names her expression too.
    program = story_game(tmp_path / "g", ['"A."', "show hana happy", 'hana pout "B."'])
    interp = _waiting(program)
    assert interp.stage.index_of("hana") is None
    assert lookahead(interp, interp.current) == PrefetchImages((), ("hana happy", "hana pout"))
    interp.stage = replace(interp.stage)                    # unchanged value, same answer
    assert lookahead(interp, interp.current) == PrefetchImages((), ("hana happy", "hana pout"))


def test_hide_and_scene_take_speakers_off_the_simulated_stage(tmp_path):
    program = story_game(tmp_path / "g", [
        "show hana happy", "show daichi", '"A."', "hide hana", 'hana pout "B."',
        'd grin "C."', "scene bg b", 'd sigh "D."', "show hana", 'hana smile "E."'])
    interp = _waiting(program)
    assert interp.stage.index_of("hana") is not None
    found = lookahead(interp, interp.current)
    assert found == PrefetchImages(("bg b",), ("daichi grin", "hana", "hana smile"))


def test_dialogue_words_change_the_simulated_image(tmp_path):
    # After "hana pout", the one-word show hana keeps "hana pout": nothing new to fetch.
    program = story_game(tmp_path / "g", [
        "show hana happy", '"A."', 'hana pout "B."', "show hana at left", 'hana pout "C."'])
    interp = _waiting(program)
    assert lookahead(interp, interp.current) == PrefetchImages((), ("hana pout",))


def test_each_path_has_its_own_simulated_stage(tmp_path):
    # The scene in one branch doesn't take hana off the other branch's stage.
    program = story_game(tmp_path / "g", [
        "show hana happy", '"A."', "if x:", "    scene bg a", '    hana pout "B."',
        "else:", '    hana smile "C."'], top="default x = False\n")
    interp = _waiting(program)
    assert lookahead(interp, interp.current) == PrefetchImages(("bg a",), ("hana smile",))