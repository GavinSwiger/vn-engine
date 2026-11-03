"""F04 *Paper Lanterns* headless (``06-acceptance.md`` §1.2, §1.12): AC-F04-06, run H on
fixture ``lanterns/`` with IMG-L; AC-F04-50 (step 8) on the example game ``game/`` with its
real image folder, plus its art and name colors (F05 07 G2). (AC-F04-21 runs with the harness
V tests, I-17.) Stages are in §0.5's notation.
"""

import dataclasses
import json

from engine.app.loading import image_source
from engine.app.text_check import contrast_ratio
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime.character import Character
from engine.runtime.commands import (AudioRestore, FakeCrash, Glitch, NvlPage, PlayVoice, PrefetchImages, Say,
                                     ShowMenu,
                                     ShowStage, StartMinigame, StoryEnded, StoryWait,
                                     UiBlocks, UiStyle, WindowTitle)
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from engine.script import nodes
from engine.script.minigame import Minigame
from engine.script.stage import Hide, Scene, Show
from tests.runtime.stage_story import (EXAMPLE, IMG_L, bursts, example_minigames, lanterns,
                                       load_example, position_names, run_h, same_types, stage,
                                       stages)
from tests.runtime.story import advance, checkpoints, end_waits, start
from tests.runtime import corpus

AC06 = [  # (line starts, stage, speaker_tag)
    ("The festival lanterns", "bg river_night | stall@stall_spot, hana happy@center", None),
    ("You're late!", "bg river_night | stall@stall_spot, hana pout@center", "hana"),
    ("She's been saying", "bg river_night | stall@stall_spot, hana pout@center, "
     "daichi grin@right", "daichi"),
    ("Daichi? You said", "bg river_night | stall@stall_spot, hana surprised@center, "
     "daichi grin@right", "hana"),
    ("Then we'll write three", "bg river_night | stall@stall_spot, hana happy@hana_close, "
     "daichi grin@right", "hana"),
    ("Fine. But I'm not", "bg river_night | stall@stall_spot, hana happy@hana_close, "
     "daichi sigh@right", "daichi"),
    ("He ducked behind", "bg river_night | daichi sigh@(1120), stall@stall_spot, "
     "hana happy@hana_close", None),
    ("Look. Everyone's", "bg dusk | hana sad@left, girl_a=lantern_girl@(900) flip, "
     "girl_b=lantern_girl@(-200), railing@center L10", "hana"),
    ("Two girls ran past", "bg dusk | hana sad@left, girl_a=lantern_girl@(900) flip, "
     "girl_b=lantern_girl@(1100), railing@center L10", None),
]


def test_ac_f04_06_paper_lanterns_plays_as_written(tmp_path):
    program = lanterns(tmp_path / "g")
    launch = run_launch(program, images=ImageSource.from_files(IMG_L))
    assert launch.namespace is not None and launch.warnings == ()
    commands = run_h(program, IMG_L)
    groups = bursts(commands)
    assert len(groups) == 10 and [type(c) for c in groups[-1]] == [StoryEnded]
    assert type(groups[0][0]) is AudioRestore           # F08: the new game's, first
    for group in [groups[0][1:], *groups[1:9]]:
        kinds = [type(c) for c in group]
        assert kinds in ([ShowStage, Say], [ShowStage, Say, PrefetchImages]), kinds
    says = [c for c in commands if type(c) is Say]
    assert [s.text.startswith(line) for s, (line, _, _) in zip(says, AC06)] == [True] * 9
    assert stages(commands) == [stage(text) for _, text, _ in AC06]
    assert [s.speaker_tag for s in says] == [tag for _, _, tag in AC06]
    ints = [sprite.at for s in stages(commands) for sprite in s.sprites
            if type(sprite.at) is tuple]
    assert ints and all(type(x) is int for at in ints for x in at)


# --- AC-F04-50 — the example game (``game/`` as committed) ----------------------------------
# The ``--bench 1`` half (no WARNING or ERROR record) is the real launch in
# ``tests/app/test_smoke_launch.py`` and the in-process ones in ``tests/app/test_session_logs.py``.

BUILTIN = frozenset({"left", "center", "right"})
NAME_TAB = (0xFF, 0xE6, 0xF0)        # F05's default name tab fill, where W41 checks names


def _example():
    """``game/`` loaded and launched as bootstrap does: config first, the real image scan."""
    result = load_example()
    assert result.program is not None, [e.format() for e in result.errors]
    assert result.errors == () and result.warnings == ()
    launch = run_launch(result.program, images=image_source(GamePaths(EXAMPLE.resolve())))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return result.program, launch


def _image_files() -> list[str]:
    return sorted(p.relative_to(EXAMPLE).as_posix() for p in (EXAMPLE / "images").rglob("*")
                  if p.is_file())


def _example_stages() -> list:
    program, _ = _example()
    return [s for seed in range(1, 6)
            for s in stages(run_headless(program, seed=seed, image_files=_image_files(),
                                         inputs=_inputs(program, seed),
                                         minigames=example_minigames()))]


def _inputs(program, seed: int) -> list[str]:
    """F07: the menus' answers of the goldens (``corpus.EXAMPLE_PICKS``)."""
    return corpus.play(program, seed, tuple(_image_files()), corpus.EXAMPLE_PICKS[seed]).inputs


def test_ac_f04_50_no_stage_warning_and_every_name_resolves():
    assert not load_config(GamePaths(EXAMPLE.resolve())).errors
    program, launch = _example()
    assert launch.warnings == ()                          # no W10–W16 on the real folder
    for seed in range(1, 6):
        commands = run_headless(program, seed=seed, image_files=_image_files(),
                                inputs=_inputs(program, seed), minigames=example_minigames())
        assert type(commands[-1]) is StoryEnded
        for s in stages(commands):
            names = [s.background] if s.background else []
            names += [sprite.image for sprite in s.sprites]
            assert [n for n in names if launch.images.get(n) is None] == [], seed


def test_ac_f04_50_stages_use_every_feature():
    shown = _example_stages()
    assert len({s.background for s in shown if s.background}) >= 2
    stored = {sprite.at for s in shown for sprite in s.sprites}
    assert {"left", "center", "right"} <= stored
    assert stored & (position_names(EXAMPLE) - BUILTIN)   # a [stage.positions] name
    assert any(type(at) is tuple for at in stored)        # a numeric at



def _at_name(stmt, names) -> bool:
    return type(stmt) is Show and stmt.at is not None and stmt.at.name in names


FEATURES = {
    "scene": lambda s, custom: type(s) is Scene and s.image is not None,
    "show with an expression": lambda s, custom: type(s) is Show and " " in s.image,
    "dialogue-line expression": lambda s, custom: (type(s) is nodes.Say and s.speaker
                                                   and bool(s.attributes)),
    "center": lambda s, custom: type(s) is Show and (s.at is None or s.at.name == "center"),
    "left": lambda s, custom: _at_name(s, {"left"}),
    "right": lambda s, custom: _at_name(s, {"right"}),
    "a [stage.positions] name": lambda s, custom: _at_name(s, custom),
    "a numeric at": lambda s, custom: type(s) is Show and s.at is not None and s.at.x is not None,
    "hide": lambda s, custom: type(s) is Hide,
    "behind": lambda s, custom: type(s) is Show and s.behind is not None,
}


def test_ac_f04_50_scripts_use_every_feature_with_a_comment_above():
    program, _ = _example()
    custom = position_names(EXAMPLE) - BUILTIN
    statements = sorted(program.iter_statements(), key=lambda s: (s.file.order, s.line))
    scenes = {s.image for s in statements if type(s) is Scene and s.image is not None}
    assert len(scenes) >= 2
    for feature, uses in FEATURES.items():
        first = next((s for s in statements if uses(s, custom)), None)
        assert first is not None, feature
        lines = (EXAMPLE / first.file.ref).read_text(encoding="utf-8").splitlines()
        above = next(text for text in reversed(lines[:first.line - 1]) if text.strip())
        assert above.lstrip().startswith("#"), (feature, first.file.ref, first.line)


def test_ac_f04_50_ac_f03_55_every_checkpoint_round_trips_with_its_stage():
    program, _ = _example()
    for seed in range(1, 6):
        states = checkpoints(start(program, seed=seed))
        assert len(states) >= 10
        for state in states:
            text = json.dumps(state.to_json(), ensure_ascii=True)
            back = GameState.from_json(json.loads(text))
            assert back == state and same_types(back.stage, state.stage)
            assert json.dumps(back.to_json(), ensure_ascii=True) == text


SKIPPED = (PrefetchImages, StoryWait, FakeCrash, StartMinigame)    # F30 s6: a crash is a wait


def _lines_on(commands: list, k: int) -> list:
    """``commands`` from the k-th ``Say`` on, without look-ahead requests, story waits (F09,
    F18: a wait's id counts the run's waits, so a restored run numbers them anew), and the
    poem's ``StartMinigame`` (F24-4: its ``base`` lists the tips held, which are persistent
    data a fresh launch's store doesn't have)."""
    says = [i for i, c in enumerate(commands) if type(c) is Say]
    return [c for c in commands[says[k]:] if type(c) not in SKIPPED]


def test_ac_f04_50_ac_f03_56_continuing_from_every_round_tripped_line():
    program, _ = _example()
    original = start(program, seed=3, minigames=example_minigames())
    end_waits(original)                                 # F18: the prologue's card
    commands = original.take_commands(1 << 30)
    states = []
    while original.status is Status.WAITING:
        if type(original.current) is not Minigame:      # F24-4: the poem has no line
            states.append(original.checkpoint())
        advance(original)
        commands += original.take_commands(1 << 30)
    for k, state in enumerate(states):
        fresh = Interpreter(program, run_launch(program).namespace,
                            minigames=example_minigames())
        restored = GameState.from_json(json.loads(json.dumps(state.to_json())))
        assert fresh.restore(restored).result is RestoreResult.OK
        got = fresh.take_commands(1 << 30)
        while fresh.status is Status.WAITING:
            advance(fresh)
            got += fresh.take_commands(1 << 30)
        first = next(i for i, c in enumerate(got) if type(c) is Say)
        # The restore burst: the saved audio (F08), the saved text mode (F17 I-3), the saved
        # stage (F04 07 I-1), its lasting glitches when there are any (F28: the example's
        # bonus scene), then the line, both restored; a voiced line's voice (F08 step 12)
        # comes just before it.
        say = got[first]
        voice = [PlayVoice(say.sid, say.voice, True)] if say.voice else []
        # F32 s6: the bonus scene's ui style comes back with the saved style.
        looks = [c for c in got[:first] if type(c) in (UiStyle, UiBlocks)]
        assert all(c.name == state.ui.style for c in looks if type(c) is UiStyle)
        assert [c for c in got[:first]
                if type(c) not in (PrefetchImages, UiStyle, UiBlocks)] == [
            AudioRestore(state.audio, "restore"), NvlPage(state.nvl.on, state.nvl.page),
            ShowStage(state.stage, restored=True),
            *([WindowTitle(state.window_title)] if state.window_title is not None else []),
            *([Glitch(state.glitch, restored=True)] if state.glitch.on else []), *voice]
        assert got[first].restored
        got[first] = dataclasses.replace(got[first], restored=False)
        # F07: at a menu the question is followed by its restored ShowMenu.
        after = first + 1
        if after < len(got) and type(got[after]) is ShowMenu:
            assert got[after].restored
            got[after] = dataclasses.replace(got[after], restored=False)
        assert [c for c in got[first:] if type(c) not in SKIPPED] == \
            _lines_on(commands, k), k


# --- The example's art and name colors (F04 step 8; F05 07 G2) -------------------------------

def test_example_art_is_the_generators_and_modest():
    """``game/images/`` holds exactly what ``tests/fixtures/F04/make_example_art.py`` draws:
    PNGs of the stated sizes, under 1 MB in all."""
    import pygame

    from tests.fixtures.F04.make_example_art import ART
    assert _image_files() == sorted(ART)
    total = 0
    for ref, (_, size) in ART.items():
        data = (EXAMPLE / ref).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert pygame.image.load(str(EXAMPLE / ref)).get_size() == size
        total += len(data)
    assert total < 1_000_000, total


def test_example_name_colors_pass_w41_on_the_default_tab():
    """F05 07 G2 (I-7): every speaker's name color has at least 3:1 contrast on the default
    name tab #FFE6F0 (W41's rule for names)."""
    _, launch = _example()
    speakers = {k: v for k, v in launch.namespace.items() if isinstance(v, Character)
                and v.color is not None}          # F05 step 7: thought has no plate
    assert set(speakers) == {"hana", "daichi"}
    ratios = {name: contrast_ratio(tuple(int(c.color[i:i + 2], 16) for i in (1, 3, 5)),
                                   NAME_TAB)
              for name, c in speakers.items()}
    assert all(r >= 3.0 for r in ratios.values()), ratios
    assert {k: round(r, 2) for k, r in ratios.items()} == {"hana": 5.09, "daichi": 4.68}
