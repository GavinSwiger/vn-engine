"""F08 step 8 — the launch file check (``engine/runtime/audio_check.py``; ``04-technical.md``
§6.4 with ``07`` I-7; ``02-script.md`` §5.3): AC-F08-06 (W21, W22, W25), W31's launch form
(AC-F08-24's last row), the record cap, when the check is skipped, and the slicing (a
step-work guard like ``test_stage_check.py``'s: work is counted per step, not timed).

Each game is Template A (``06`` §0.4) in ``tmp_path`` with its ``audio/`` files (empty: the
check only lists folders), launched as ``app/loading.py`` builds it: ``LaunchJob(audio=
AudioFiles(paths.list_dir, loop keys))``. The forms ``02`` gives only by example (``06`` G4)
are pinned here so a change is seen.
"""

from pathlib import Path

import pytest

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime import audio_check as check_mod
from engine.runtime.audio_check import (AUDIO_CHECK_CHUNK, AUDIO_CHECK_REFS, AudioFileCheck,
                                        AudioFiles, audio_file_check, w21_text, w22_text,
                                        w25_text, w31_text)
from engine.runtime.images import ImageSource
from engine.runtime.launch import LaunchJob, run_launch
from engine.script import suggest as suggest_mod
from engine.script.limits import SCRIPT_AUDIO_WARN_LIMIT, SCRIPT_SUGGEST_MAX_NAME
from engine.script.suggest import SUGGEST_STEP_WORK
from tests.audio.conftest import TEMPLATE_AUDIO
from tests.runtime.story import load_files
from tests.script.conftest import opened  # noqa: F401  (fixture)
from tests.script.helpers import template_a

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG = '[game]\nid = "f08-a"\n'


def template_game(root: Path, S: str | None = None, C: str = "", *, T: str | None = None,
                  extra: tuple[str, ...] = ()):
    """Template A with ``S`` on line 4 and ``C`` appended to ``config.toml``: the program
    and the check's inputs, as the app builds them."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(CONFIG + C, encoding="utf-8")
    for file in (*TEMPLATE_AUDIO, *extra):
        path = root / "audio" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    program = load_files(root, {"main.vns": template_a(S=S, T=T)})
    paths = GamePaths(root.resolve())
    result = load_config(paths)
    assert not result.errors
    return program, AudioFiles(paths.list_dir, tuple(result.config.audio.loop_start))


def launched(root: Path, S: str | None = None, C: str = "", **kwargs) -> list[tuple[str, str]]:
    program, files = template_game(root, S, C, **kwargs)
    result = run_launch(program, audio=files)
    assert result.namespace is not None                   # the game always starts
    return [(w.code, w.format()) for w in result.warnings]


def at4(text: str) -> str:
    return "script/main.vns, line 4: " + text


W22_HEAD = "Some voice files don't exist, so those lines have no voice:"
SEVEN_VOICES = "⏎".join(f'voice "voice/v{i}.ogg"⏎"a"' for i in range(1, 8))

# --- AC-F08-06 — launch check for missing files (W21, W22, W25) -----------------------------

AC_06 = {
    "W21": ('play music "bgm/festval.ogg"', "", [("W21", at4(
        'there is no file audio/bgm/festval.ogg, so it will be silent. Did you mean '
        '"bgm/festival.ogg"?'))]),
    "W21-case": ('play music "BGM/festival.ogg"', "", [("W21", at4(
        "there is no file audio/BGM/festival.ogg, so it will be silent. Paths match files "
        'exactly: write "bgm/festival.ogg".'))]),
    "W21-none": ('play sound "sfx/zzqx.ogg"', "", [("W21", at4(
        "there is no file audio/sfx/zzqx.ogg, so it will be silent. Add the file, or check "
        "the spelling."))]),
    "W21-stop": ('stop sound "sfx/zzqx.ogg"', "", [("W21", at4(
        "there is no file audio/sfx/zzqx.ogg, so this stops nothing. Add the file, or check "
        "the spelling."))]),
    "W21-four": ("⏎".join(['play music "bgm/festval.ogg"'] * 4), "", [("W21", at4(
        'there is no file audio/bgm/festval.ogg, so it will be silent. Did you mean '
        '"bgm/festival.ogg"? (also on 3 other lines)'))]),
    "W22-seven": (SEVEN_VOICES, "", [("W22", "\n".join(
        [W22_HEAD] + [f"audio/voice/v{i}.ogg (script/main.vns, line {2 + 2 * i})"
                      for i in range(1, 6)] + ["…and 2 more."]))]),
    "W22-suggestion": ('voice "voice/hana_14.ogg"⏎"a"', "", [("W22", W22_HEAD + "\n"
        'audio/voice/hana_14.ogg (script/main.vns, line 4) Did you mean "voice/hana_014.ogg"?')]),
    "W25": (None, '[audio.loop_start]\n"bgm/festval.ogg" = 8.0\n', [("W25",
        'config.toml: [audio.loop_start] names "bgm/festval.ogg", which doesn\'t exist. '
        'Did you mean "bgm/festival.ogg"?')]),
}


@pytest.mark.parametrize("row", list(AC_06))
def test_ac_f08_06(tmp_path, row):
    S, C, expected = AC_06[row]
    assert launched(tmp_path / "g", S, C) == expected


def test_ac_f08_06_files_that_exist_give_nothing(tmp_path):
    S = ('play music "bgm/festival.ogg"⏎queue music "bgm/omen.ogg"⏎play sound "sfx/door.ogg"⏎'
         'stop sound "sfx/door.ogg"⏎voice "voice/hana_014.ogg"⏎hana "Hi."')
    C = '[audio.loop_start]\n"bgm/festival.ogg" = 8.0\n'
    assert launched(tmp_path / "g", S, C) == []


def test_the_record_order(tmp_path):
    """W21 at first use in reading order, then the one W22, then the loop keys in config
    order (W25, W31)."""
    S = ('voice "voice/zz.ogg"⏎"a"⏎play sound "sfx/zzqx.ogg"⏎play music "bgm/festval.ogg"⏎'
         'play sound "sfx/zzqx.ogg"')
    C = '[audio.loop_start]\n"bgm/nope.ogg" = 1.0\n"bgm/x.mp3" = 2.0\n'
    found = launched(tmp_path / "g", S, C, extra=("bgm/x.mp3",))
    assert [(code, text.split(":")[0]) for code, text in found] == [
        ("W21", "script/main.vns, line 6"), ("W21", "script/main.vns, line 7"),
        ("W22", "Some voice files don't exist, so those lines have no voice"),
        ("W25", "config.toml"), ("W31", "config.toml")]
    assert found[0][1].endswith("(also on 1 other line)")


def test_a_menu_voice_is_checked(tmp_path):
    """F07: a ``voice`` above a menu's question belongs to the menu (``Menu.voice``)."""
    S = 'menu:⏎[8]voice "voice/zz.ogg"⏎[8]hana "Hi."⏎[8]"Go":⏎[12]"a"'
    found = launched(tmp_path / "g", S)
    assert found == [("W22", W22_HEAD + "\naudio/voice/zz.ogg (script/main.vns, line 5)")]


def test_unplayable_formats_were_w23_at_load(tmp_path):
    """``04`` §6.2: the statement plays as silence with no second message."""
    program, files = template_game(tmp_path / "g", 'play music "bgm/theme.m4a"⏎'
                                   'voice "voice/a.mid"⏎"a"')
    assert run_launch(program, audio=files).warnings == ()


def test_a_folder_named_like_a_file_is_missing(tmp_path):
    (tmp_path / "g" / "audio" / "sfx" / "zzqx.ogg").mkdir(parents=True)
    assert launched(tmp_path / "g", 'play sound "sfx/zzqx.ogg"') == [("W21", at4(
        "there is no file audio/sfx/zzqx.ogg, so it will be silent. Add the file, or check "
        "the spelling."))]


def test_a_missing_folder_and_a_misspelled_folder(tmp_path):
    found = launched(tmp_path / "g", 'play sound "nowhere/a.ogg"⏎play sound "sxf/door.ogg"')
    assert found == [
        ("W21", at4("there is no file audio/nowhere/a.ogg, so it will be silent. Add the file, "
                    "or check the spelling.")),
        ("W21", "script/main.vns, line 5: there is no file audio/sxf/door.ogg, so it will be "
                'silent. Did you mean "sfx/door.ogg"?')]


# --- W31's launch form (AC-F08-24's last row), W25's other forms -------------------------------

def test_w31_launch_form(tmp_path):
    C = '[audio.loop_start]\n"bgm/festival.mp3" = 8.0\n"bgm/intro.opus" = 1.0\n'
    found = launched(tmp_path / "g", None, C, extra=("bgm/festival.mp3", "bgm/intro.opus"))
    assert found == [("W31", 'config.toml: [audio.loop_start] gives "bgm/festival.mp3" a loop '
                             "point, but loop points work only in .ogg and .opus files, so it "
                             "loops from the start. Convert it to .ogg.")]


def test_a_missing_mp3_key_is_w25_only(tmp_path):
    found = launched(tmp_path / "g", None, '[audio.loop_start]\n"bgm/gone.mp3" = 8.0\n')
    assert [code for code, _ in found] == ["W25"]


@pytest.mark.parametrize("key,tail", [
    ("BGM/omen.ogg", 'Paths match files exactly: write "bgm/omen.ogg".'),
    ("bgm/zzqx.ogg", "Add the file, or check the spelling."),
])
def test_w25_drafted_forms(tmp_path, key, tail):
    found = launched(tmp_path / "g", None, f'[audio.loop_start]\n"{key}" = 1.0\n')
    assert found == [("W25", f'config.toml: [audio.loop_start] names "{key}", which doesn\'t '
                             f"exist. {tail}")]


@pytest.mark.parametrize("text,expected", [
    (w21_text("a.ogg", others=1),
     "there is no file audio/a.ogg, so it will be silent. Add the file, or check the spelling. "
     "(also on 1 other line)"),
    (w21_text("a.ogg", "b.ogg", stops=True, others=2_000),
     'there is no file audio/a.ogg, so this stops nothing. Did you mean "b.ogg"? (also on '
     "2,000 other lines)"),
    (w22_text([("v/a.ogg", "script/x.vns", 3, None)], 1_209),
     W22_HEAD + "\naudio/v/a.ogg (script/x.vns, line 3)\n…and 1,209 more."),
    (w25_text("a.ogg", "b.ogg"),
     'config.toml: [audio.loop_start] names "a.ogg", which doesn\'t exist. Did you mean '
     '"b.ogg"?'),
    (w31_text("a.wav"),
     'config.toml: [audio.loop_start] gives "a.wav" a loop point, but loop points work only '
     "in .ogg and .opus files, so it loops from the start. Convert it to .ogg."),
])
def test_drafted_and_settled_texts(text, expected):
    assert text == expected


def test_texts_are_bounded_and_escaped():
    long = "a" * 900 + ".ogg"
    assert len(w21_text(long, long, others=5)) <= 1_000
    assert "\x1b" not in w21_text("bgm/\x1b[31m.ogg")
    lines = w22_text([(long, "script/a.vns", 1, long)] * 5, 3).split("\n")
    assert len(lines) == 7 and all(len(line) <= 1_000 for line in lines)


# --- The cap: SCRIPT_AUDIO_WARN_LIMIT records, then one W20s line ------------------------------

def test_the_cap_and_the_summary(tmp_path):
    missing = SCRIPT_AUDIO_WARN_LIMIT + 5
    S = "⏎".join(f'play sound "sfx/m{i:03}.ogg"' for i in range(missing))
    S += '⏎voice "voice/zz.ogg"⏎"a"'
    C = '[audio.loop_start]\n"bgm/nope.ogg" = 1.0\n'
    found = launched(tmp_path / "g", S, C)
    codes = [code for code, _ in found]
    assert codes == ["W21"] * SCRIPT_AUDIO_WARN_LIMIT + ["W22", "W20s"]
    assert found[-1][1] == "…and 6 more warnings about voices and audio files."


# --- When the check runs ----------------------------------------------------------------------

def test_headless_runs_skip_it(tmp_path):
    """No ``audio`` (``run_headless``, tools): no phase 6; with images, F04's phases only."""
    program, _ = template_game(tmp_path / "g", 'play music "bgm/festval.ogg"')
    assert run_launch(program).warnings == ()
    assert run_launch(program, images=ImageSource.from_files(())).warnings == ()


def test_a_failing_define_skips_it(tmp_path):
    program, files = template_game(tmp_path / "g", 'play music "bgm/festval.ogg"',
                                   T="define broken = 1 / 0")
    result = run_launch(program, audio=files)
    assert result.namespace is None and result.warnings == ()


def test_it_runs_after_the_stage_check(tmp_path):
    program, files = template_game(tmp_path / "g", 'show nobody⏎play music "bgm/festval.ogg"')
    result = run_launch(program, images=ImageSource.from_files(()), audio=files)
    assert [w.code for w in result.warnings] == ["W12", "W21"]


def test_the_example_game_is_warning_free():
    from tests.runtime.stage_story import load_example

    loaded = load_example()
    assert loaded.program is not None
    paths = GamePaths((REPO / "game").resolve())
    config = load_config(paths).config
    files = AudioFiles(paths.list_dir, tuple(config.audio.loop_start))
    assert audio_file_check(loaded.program, files) == ()


# --- Slicing --------------------------------------------------------------------------------

def test_slicing_does_not_change_the_result(tmp_path, monkeypatch):
    S = "⏎".join(f'play sound "sfx/m{i:02}.ogg"⏎voice "voice/v{i}.ogg"⏎"a"'
                 for i in range(12))
    S += '⏎play music "BGM/festival.ogg"⏎play sound "sfx/door.ogg"'
    program, files = template_game(tmp_path / "g", S, '[audio.loop_start]\n"bgm/x.ogg" = 1.0\n')
    at_once = audio_file_check(program, files)
    monkeypatch.setattr(check_mod, "AUDIO_CHECK_CHUNK", 3)
    monkeypatch.setattr(check_mod, "AUDIO_CHECK_REFS", 2)
    check = AudioFileCheck(program, files)
    steps = 1
    while not check.step():
        steps += 1
    assert [(w.code, w.format()) for w in check.warnings] == [
        (w.code, w.format()) for w in at_once]
    assert len(at_once) == 12 + 2 + 1                       # W21 × 13, W22, W25
    assert steps > 40


def test_launch_job_runs_phase_6_in_steps(tmp_path):
    program, files = template_game(tmp_path / "g", 'play music "bgm/festval.ogg"')
    job = LaunchJob(program, audio=files)
    steps = 1
    while not job.step():
        steps += 1
    plain = LaunchJob(program)
    plain_steps = 1
    while not plain.step():
        plain_steps += 1
    assert [w.code for w in job.result.warnings] == ["W21"]
    assert steps - plain_steps >= 4          # collect, entries, look up (listing), format


FOLDER_FILES = 300                           # existing files beside them, near their names


# AC-F08-06's 10,000 distinct missing refs are ``slow``; the default run checks the same
# bounds with 2,500 (still over AUDIO_CHECK_REFS and AUDIO_CHECK_CHUNK, so steps are full).
@pytest.mark.parametrize("many", [2_500, pytest.param(10_000, marks=pytest.mark.slow)])
def test_ac_f08_06_ten_thousand_missing_refs_are_spread_over_steps(tmp_path, monkeypatch,
                                                                    opened,  # noqa: F811
                                                                    many):
    """No step looks up more than ``AUDIO_CHECK_REFS`` (≤ 2,000) refs or visits more than
    ``AUDIO_CHECK_CHUNK`` statements; a folder listing is a step of its own; a did-you-mean
    does at most ``SUGGEST_STEP_WORK`` units (a table row or a distance) plus one name's per
    step; ``walk_files`` is never called and no file is opened (listings only)."""
    root = tmp_path / "g"
    sfx = root / "audio" / "sfx"
    sfx.mkdir(parents=True)
    for i in range(FOLDER_FILES):
        (sfx / f"effect_{i:04}.ogg").write_bytes(b"")
    lines = ["label start:"]
    lines += [f'    play sound "sfx/effect_{i:05}.ogg"' for i in range(many - 100)]
    lines += [f'    voice "voice/line_{i:03}.ogg"\n    "a"' for i in range(100)]
    lines += ['    play sound "sfx/effect_0001.ogg"', '    "End."']
    (root / "config.toml").write_text(CONFIG, encoding="utf-8")
    program = load_files(root, {"main.vns": "\n".join(lines) + "\n"})
    paths = GamePaths(root.resolve())

    work = {"refs": 0, "statements": 0, "lists": 0, "suggest": 0}

    def counter(owner, name, key):
        real = getattr(owner, name)

        def counted(*args, **kwargs):
            work[key] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, counted)

    counter(AudioFileCheck, "_look_up", "refs")
    counter(AudioFileCheck, "_collect", "statements")
    counter(suggest_mod, "osa_distance", "suggest")
    counter(suggest_mod, "_osa_row", "suggest")

    def list_dir(ref):
        work["lists"] += 1
        return paths.list_dir(ref)

    def no_walk(*args, **kwargs):
        raise AssertionError("walk_files")

    monkeypatch.setattr(GamePaths, "walk_files", no_walk)
    check = AudioFileCheck(program, AudioFiles(list_dir))
    per_step = []
    with opened() as events:
        done = False
        while not done:
            before = dict(work)
            done = check.step()
            per_step.append({k: work[k] - before[k] for k in work})
    assert [e for e, _ in events if e == "open"] == []
    assert max(s["refs"] for s in per_step) == AUDIO_CHECK_REFS <= 2_000
    assert max(s["statements"] for s in per_step) == AUDIO_CHECK_CHUNK
    assert max(s["suggest"] for s in per_step) <= SUGGEST_STEP_WORK + SCRIPT_SUGGEST_MAX_NAME + 1
    assert all(s["lists"] <= 1 for s in per_step)
    assert all(s["refs"] == s["suggest"] == 0 for s in per_step if s["lists"])
    assert sum(s["refs"] for s in per_step) == many + 1                # each distinct ref once
    assert sum(s["suggest"] for s in per_step) > 4 * SUGGEST_STEP_WORK
    codes = [w.code for w in check.warnings]
    assert codes == ["W21"] * SCRIPT_AUDIO_WARN_LIMIT + ["W22", "W20s"]
    assert check.warnings[0].message.endswith('Did you mean "sfx/effect_0000.ogg"?')
    assert check.warnings[-1].message == (
        f"…and {many - 100 - SCRIPT_AUDIO_WARN_LIMIT:,} more warnings about voices and audio "
        "files.")
