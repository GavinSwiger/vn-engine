"""F04 step 6 — the launch image check (``engine/runtime/stage_check.py``; ``04-technical.md``
§7.2 phase 5; ``02-script.md`` §5.3): AC-F04-39 (the W rows of ``cases.toml``), 40 (what the
check accepts), 41 (order and the 100-record cap, 07 I-9, I-10), and, as run H, AC-F04-03
(``image`` declarations). AC-F04-18 and AC-F04-39's W14 row are retired by F09 (its 07 I-2:
W14 left ``stage_check.py``; ``with`` is now checked by F09's ``TransitionCheck``, tested in
``tests/runtime/test_transitions.py``). The drafted forms 02 leaves open (07 I-12; 06 G2,
G4) are pinned here so a change is seen. F21 step 5 adds AC-F21-37: the ``image`` of each
codex entry is a W12 name too.

Every launch is run H's (``06`` §0.2): ``run_launch(program, images=ImageSource.from_files(
files))``, the launch ``run_headless`` does, so the ``LaunchResult`` can be read.
"""

import shutil
from pathlib import Path

import pytest

from engine.runtime import stage_check as check_mod
from engine.runtime.commands import StoryEnded
from engine.runtime.images import ImageFile, ImageIndex, ImageSource, SolidColor
from engine.runtime.launch import LaunchJob, run_launch
from engine.runtime.limits import IMAGE_SCAN_MAX_FILES, STAGE_WARN_MAX
from engine.runtime.stage_check import StageCheck, stage_check
from engine.script import suggest as suggest_mod
from engine.script.limits import SCRIPT_SUGGEST_MAX_NAME
from engine.script.messages import format_message, w10_line, w10_text
from engine.script.suggest import SUGGEST_STEP_WORK
from tests.runtime.stage_story import (F04, IMG, IMG_L, lanterns, load_game, run_h, stages,
                                       story_game, template_game, write_game)
from tests.script import message_cases


def launch(program, files):
    return run_launch(program, images=ImageSource.from_files(files))


def codes(result) -> list[str]:
    return [w.code for w in result.warnings]


def placed(result) -> list[tuple[str, str | None, int | None]]:
    return [(w.code, w.file, w.line) for w in result.warnings]


def ends(program, files) -> bool:
    """The story still runs to its end (the warnings never stop a game)."""
    return type(run_h(program, files)[-1]) is StoryEnded


# --- AC-F04-39 — launch messages: the W rows ---------------------------------------------------

W_CASES = [c for c in message_cases.load_cases()
           if c.feature == "F04" and c.time == "launch" and c.code.startswith("W")]

W10_FILES = ["images/bg/bridge-day.png", "images/club day.png", "images/a.b.png",
             "images/scene.png", "images/zoom.png", "images/a/b/c/d/e/f.png"]

# The rows' files (06 AC-F04-39 "Edit / files"): (added to IMG, taken out of IMG).
FILES = {
    "F04-39-W10-reasons": (W10_FILES, ()),
    "F04-39-W10-more": ([f"images/x-{i:02}.png" for i in range(1, 26)], ()),
    "F04-39-W11-png": (["images/hana/happy.webp"], ()),
    "F04-39-W11-webp": (["images/hana/sad.jpg", "images/hana/sad.webp"], ["images/hana/sad.png"]),
    "F04-39-W12-case": (["images/hana/Happy.png"], ["images/hana/happy.png"]),
    "F04-39-W12b": (["art/festival-final.png"], ()),
}


def row_files(case_id: str) -> list[str]:
    added, removed = FILES.get(case_id, ((), ()))
    return [f for f in IMG if f not in removed] + list(added)


def test_ac_f04_39_every_warning_has_a_row():
    assert {c.code for c in W_CASES} == {"W10", "W11", "W12", "W12b", "W13", "W16"}  # F09: no W14
    assert set(FILES) <= {c.id for c in W_CASES}
    assert all(not c.runnable for c in W_CASES)          # launch rows: not part of the load


@pytest.mark.parametrize("case", W_CASES, ids=lambda c: c.id)
def test_ac_f04_39(tmp_path, case):
    program = load_game(write_game(tmp_path / "g", {"main.vns": message_cases.main_text(case)}))
    files = row_files(case.id)
    result = launch(program, files)
    assert result.namespace is not None and result.error_count == 0
    assert codes(result) == [case.code], [w.format() for w in result.warnings]
    message_cases.check_case(case, message_cases.Outcome([], result.warnings, 0, False))
    assert ends(program, files)


def test_the_template_alone_launches_with_no_warning(tmp_path):
    program = template_game(tmp_path / "g")
    assert launch(program, IMG).warnings == ()


# --- The drafted forms (07 I-12; 06 G2, G4) ----------------------------------------------------

@pytest.mark.parametrize("problem, line", [
    (("images/bg-x/day.png", "hyphen", "bg-x", "bg_x", True),
     "images/bg-x/day.png: rename the folder bg-x to bg_x (no - in names)."),
    (("images/show/day.png", "statement_word", "show", "my_show", True),
     'images/show/day.png: rename the folder show to my_show ("show" is a statement word).'),
    (("images/zoom/day.png", "stage_word", "zoom", "my_zoom", True),
     'images/zoom/day.png: rename the folder zoom to my_zoom ("zoom" is a word show uses).'),
    (("images/a b/c.png", "space", "a b", "a_b", True),
     "images/a b/c.png: rename the folder a b to a_b (no spaces in names)."),
    (("images/v1.2/c.png", "dot", "v1.2", "v1_2", True),
     "images/v1.2/c.png: rename the folder v1.2 to v1_2 (no dots in folder names)."),
    (("images/hi!.png", "characters", "hi!.png", "hi_.png", False),
     "images/hi!.png: rename it hi_.png (names use letters, digits, and _)."),
    (("images/x.png", "characters", "x.png", None, False),
     "images/x.png: rename it so its name uses only letters, digits, and _."),
    (("images/x/y.png", "characters", "x", None, True),
     "images/x/y.png: rename the folder x so its name uses only letters, digits, and _."),
    (("images/Scene.PNG", "statement_word", "Scene.PNG", "my_Scene.PNG", False),
     'images/Scene.PNG: rename it my_Scene.PNG ("Scene" is a statement word).'),
    (("images/hana/happy‮.png", "characters", "happy‮.png", "happy_.png", False),
     "images/hana/happy\\u202e.png: rename it happy_.png (names use letters, digits, and _)."),
])
def test_w10_lines(problem, line):
    assert w10_line(*problem) == line


def test_w10_lines_come_from_the_index_in_ref_order(tmp_path):
    files = ["images/show/b.png", "images/bg-x/a.png", "images/ok.png"]
    program = template_game(tmp_path / "g")
    (w10,) = launch(program, [*IMG, *files]).warnings
    assert w10.format().splitlines() == [
        "Some image files have names a script can't use:",
        "images/bg-x/a.png: rename the folder bg-x to bg_x (no - in names).",
        'images/show/b.png: rename the folder show to my_show ("show" is a statement word).']


def test_w10_cuts_each_line_not_the_record():
    long = "images/" + "x" * 300 + "-y.png"
    text = w10_text([(long, "hyphen", "x" * 300 + "-y.png", "x" * 300 + "_y.png", False)] * 20,
                    5)
    lines = text.splitlines()
    assert len(lines) == 22 and len(text) > 1_000
    assert all(len(line) <= 1_000 for line in lines) and lines[-1] == "…and 5 more."


@pytest.mark.parametrize("code, args, text", [
    ("W11", ("x", "images/x.webp", "images/x.jpg"),
     'images/x.jpg and images/x.webp both give the image "x". The .webp is used; remove or '
     "rename the other."),
    ("W12", ("Hana happy", "hana happy", ("images/hana", "Hana", True)),
     'there is no image "Hana happy", so a placeholder will show. Names match files exactly: '
     "rename the folder images/hana to Hana, or write hana happy."),
    ("W12", ("bg Dusk", "bg dusk"),
     'there is no image "bg Dusk", so a placeholder will show. Did you mean "bg dusk"?'),
    ("W12", ("lantern2",),
     'there is no image "lantern2", so a placeholder will show. Add images/lantern2.png, or '
     "check the spelling."),
    ("W12b", ("bg festival", "art/festival_final.png", None),
     'image bg festival uses "art/festival_final.png", which doesn\'t exist, so a placeholder '
     "will show."),
    ("W13", ("d", "grin", "daichi"),
     'd\'s line has the word "grin", but there are no images for daichi, so it changes '
     "nothing. Add images/daichi/grin.png, or if the images have another name, change "
     'image_tag="daichi" in define d = Character(…).'),
    ("W13", ("kaito", "yukata happy", None),
     'kaito\'s line has the words "yukata happy", but there are no images for kaito, so it '
     "changes nothing. Add images/kaito/yukata/happy.png, or if the images have another name, "
     'add image_tag="that_name" to define kaito = Character(…).'),
    ("W16", ("zzz", None),
     'behind zzz: no show in the game puts a sprite tagged "zzz" on stage, so this does '
     "nothing."),
    ("W10b", (IMAGE_SCAN_MAX_FILES,),
     "Image scan stopped after 20,000 files; image names beyond that were not checked."),
    ("W10s", (50,), "…and 50 more stage warnings not shown."),
    ("W10s", (1,), "…and 1 more stage warning not shown."),
    ("W10s", (1234,), "…and 1,234 more stage warnings not shown."),
])
def test_drafted_and_settled_texts(code, args, text):
    assert format_message(code, args) == text


def test_w12_case_form_for_a_folder(tmp_path):
    files = [f.replace("images/hana/", "images/Hana/") for f in IMG]
    program = template_game(tmp_path / "g", replace={5: "    show hana pout"})
    (w12,) = launch(program, files).warnings
    assert w12.line == 5
    assert w12.message == ('there is no image "hana pout", so a placeholder will show. Names '
                           "match files exactly: rename the folder images/Hana to hana, or "
                           "write Hana pout.")


def test_w12_case_form_for_a_declared_name_is_a_did_you_mean(tmp_path):
    program = template_game(tmp_path / "g", S="show bg Dusk", T='image bg dusk = "#2b2140"')
    (w12,) = launch(program, IMG).warnings
    assert w12.message.endswith('Did you mean "bg dusk"?')


# --- AC-F04-40 — what the launch check accepts -------------------------------------------------

def lanterns_with(root: Path, lines: list[str], *, top: str = "", extra: str = ""):
    """``lanterns/`` with ``lines`` at the end of ``label bridge:``, ``top`` before its
    labels, and ``extra`` (more top-level text) after them."""
    shutil.copytree(F04 / "lanterns", root)
    chapter = root / "script" / "chapter1.vns"
    text = chapter.read_text(encoding="utf-8").rstrip("\n") + "\n"
    text = top + text + "".join(f"    {line}\n" for line in lines) + extra
    chapter.write_bytes(text.encode("utf-8"))
    return load_game(root)


KAITO = 'define kaito = Character("Kaito")\n'
AS_KAITO = "label elsewhere:\n    show student neutral as kaito\n"
STUDENT = ["images/student/neutral.png", "images/student/angry.png"]
DESK_LATER = "label later:\n    if False:\n        show desk\n"

AC40 = {
    # row: (added lines, top, extra, more files, expected codes)
    "one-word-tags": (["show hana", "show railing", "show girl_a at 200"], "", "", [], []),
    "as-words": (['kaito angry "…"'], KAITO, AS_KAITO, STUDENT, []),
    "as-missing-word": (['kaito blush "…"'], KAITO, AS_KAITO, STUDENT, ["W12"]),
    "image-tag": (['d grin "…"'], "", "", [], []),
    "twice": (["show hana hapy", "show hana hapy"], "", "", [], ["W12", "W12"]),
    "behind-later": (["show witness behind desk"], "", DESK_LATER,
                     ["images/witness.png", "images/desk.png"], []),
}


@pytest.mark.parametrize("row", sorted(AC40))
def test_ac_f04_40(tmp_path, row):
    lines, top, extra, more, expected = AC40[row]
    program = lanterns_with(tmp_path / "g", lines, top=top, extra=extra)
    files = [*IMG_L, *more]
    result = launch(program, files)
    assert result.namespace is not None
    assert codes(result) == expected, [w.format() for w in result.warnings]
    assert all(w.file == "script/chapter1.vns" for w in result.warnings)
    assert ends(program, files)


def test_ac_f04_40_one_w12_per_statement(tmp_path):
    program = lanterns_with(tmp_path / "g", ["show hana hapy", "show hana hapy"])
    first, second = launch(program, IMG_L).warnings
    assert first.message == second.message and second.line == first.line + 1


def test_ac_f04_40_a_word_under_as_names_the_shown_image(tmp_path):
    program = lanterns_with(tmp_path / "g", ['kaito blush "…"'], top=KAITO, extra=AS_KAITO)
    (w12,) = launch(program, [*IMG_L, *STUDENT]).warnings
    assert w12.message == ('there is no image "student blush", so a placeholder will show. '
                           "Add images/student/blush.png, or check the spelling.")


def test_ac_f04_40_a_failing_define_skips_the_check(tmp_path):
    program = lanterns_with(tmp_path / "g", ["show hana hapy"],
                            top="define broken = Character(5)\n")
    result = launch(program, IMG_L)
    assert result.namespace is None and result.error_count == 1
    assert result.warnings == () and result.images is None


def test_ac_f04_06_lanterns_has_no_warning(tmp_path):
    assert launch(lanterns(tmp_path / "g"), IMG_L).warnings == ()


# --- More of §7.2's rules ---------------------------------------------------------------------

@pytest.mark.parametrize("lines, top, expected", [
    (["scene bg nowhere", '"A."'], "", ["W12"]),
    (["scene", "scene black", "scene bg", '"A."'], "", []),          # bg: a tag, one word
    (["show nobody", '"A."'], "", ["W12"]),
    (["show bg river_night as sky", "show sky", '"A."'], "", []),
    (['hana "Plain."', '"Narration."'], "", []),
    (['hana happy "Hi."', 'd sigh "Hi."'], "", []),
    (['ghost boo "Hi."'], 'define ghost = Character("G", image_tag="hana")\n', ["W12"]),
    (['ghost boo "Hi."'], 'define ghost = Character("G", image_tag="spirit")\n', ["W13"]),
    (["show hana behind hana", '"A."'], "", []),
    (["show hana behind ghost", '"A."'], "", ["W16"]),
    (["show nobody behind ghost with dissolve", '"A."'], "", ["W12", "W16"]),   # F09: no W14
])
def test_statement_rules(tmp_path, lines, top, expected):
    program = story_game(tmp_path / "g", lines, top=top)
    result = launch(program, IMG)
    assert codes(result) == expected, [w.format() for w in result.warnings]


def test_w13_names_the_image_tag(tmp_path):
    program = story_game(tmp_path / "g", ['ghost boo "Hi."'],
                         top='define ghost = Character("G", image_tag="spirit")\n')
    (w13,) = launch(program, IMG).warnings
    assert w13.message == format_message("W13", ("ghost", "boo", "spirit"))


def test_w16_without_a_suggestion(tmp_path):
    program = story_game(tmp_path / "g", ["show hana behind qqqqqqq", '"A."'])
    (w16,) = launch(program, IMG).warnings
    assert w16.message.endswith("so this does nothing.")


def test_a_speaker_that_is_not_a_character_is_left_to_the_speaker_check(tmp_path):
    program = story_game(tmp_path / "g", ['teller blush "Hi."'],
                         top='define teller = "N"\n')
    result = launch(program, IMG)
    assert [e.code for e in result.errors] == ["E75"] and result.warnings == ()


def test_no_image_source_means_no_check(tmp_path):
    program = story_game(tmp_path / "g", ["show nobody", '"A."'])
    result = run_launch(program)
    assert result.images is None and result.warnings == ()


# --- AC-F04-41 — warning order and the 100-record cap ------------------------------------------

def order_game(root: Path):
    main = ['include "later.vns"', 'define hana = Character("Hana")',
            'image bg festival = "art/missing.png"', "label start:"]
    main += ['    "A."'] * 5
    for line in (10, 20, 30):
        main += ["    # -"] * (line - 1 - len(main))
        main.append(f"    show hana nope{line}")
    main.append("    jump later")
    later = ["label later:", '    "B."', "    # -", "    # -", "    show hana behind nobody",
             '    "C."']
    write_game(root, {"main.vns": "\n".join(main) + "\n", "later.vns": "\n".join(later) + "\n"})
    return load_game(root)


def test_ac_f04_41_order(tmp_path):
    program = order_game(tmp_path / "g")
    files = [*IMG, "images/bg/bridge-day.png", "images/hana/happy.webp"]
    result = launch(program, files)
    assert placed(result) == [
        ("W10", None, None), ("W11", None, None), ("W12b", "script/main.vns", 3),
        ("W12", "script/main.vns", 10), ("W12", "script/main.vns", 20),
        ("W12", "script/main.vns", 30), ("W16", "script/later.vns", 5)]
    assert result.namespace is not None and ends(program, files)


def many_w12(root: Path, count: int):
    return story_game(root, [f"show hana nope{i}" for i in range(count)] + ['"A."'])


@pytest.mark.parametrize("count, more", [(150, 50), (101, 1), (100, 0), (99, 0)])
def test_ac_f04_41_cap(tmp_path, count, more):
    program = many_w12(tmp_path / "g", count)
    result = launch(program, IMG)
    assert result.namespace is not None
    kept = min(count, STAGE_WARN_MAX)
    assert codes(result) == ["W12"] * kept + (["W10s"] if more else [])
    assert [w.line for w in result.warnings[:kept]] == list(range(4, 4 + kept))
    if more:
        summary = result.warnings[-1]
        assert summary.format() == format_message("W10s", (more,))
        assert (summary.file, summary.line) == (None, None)
    if count == 150:
        assert result.warnings[-1].format() == "…and 50 more stage warnings not shown."


def test_ac_f04_41_the_cap_counts_the_index_records_and_the_stop_line(tmp_path):
    """07 I-9 (G5): every launch stage record counts, the scan stop line (I-10) included."""
    program = many_w12(tmp_path / "g", 98)
    index = ImageIndex({"hana happy": ImageFile("images/hana/happy.png")},
                       problems=[], truncated=True)
    G = run_launch(program).namespace
    warnings = stage_check(program, G, index)
    assert [w.code for w in warnings] == ["W10b"] + ["W12"] * 98
    index = ImageIndex({"hana happy": ImageFile("images/hana/happy.png")}, truncated=True,
                       declared_missing=[], duplicates=[])
    program = many_w12(tmp_path / "h", 100)
    warnings = stage_check(program, G, index)
    assert [w.code for w in warnings] == ["W10b"] + ["W12"] * 99 + ["W10s"]
    assert warnings[0].format() == ("Image scan stopped after 20,000 files; image names "
                                    "beyond that were not checked.")
    assert warnings[-1].format() == "…and 1 more stage warning not shown."


def test_the_stop_line_is_its_own_record_before_w10(tmp_path):
    from engine.runtime.images import NameProblem
    program = story_game(tmp_path / "g", ['"A."'])
    index = ImageIndex({}, problems=[NameProblem("images/a-b.png", "hyphen", "a-b.png",
                                                 "a_b.png")], truncated=True)
    warnings = stage_check(program, run_launch(program).namespace, index)
    assert [w.code for w in warnings] == ["W10b", "W10"]
    assert "stopped" not in warnings[1].format()


# --- Slicing (04 §7.2: 2,000 statements per step) ---------------------------------------------

def test_slicing_does_not_change_the_result(tmp_path, monkeypatch):
    program = many_w12(tmp_path / "g", 120)
    G = run_launch(program).namespace
    index = launch(program, IMG).images
    at_once = stage_check(program, G, index)
    monkeypatch.setattr(check_mod, "STAGE_CHECK_CHUNK", 7)
    check = StageCheck(program, G, index)
    steps = 1
    while not check.step():
        steps += 1
    assert [(w.code, w.format()) for w in check.warnings] == [
        (w.code, w.format()) for w in at_once]
    statements = sum(1 for _ in program.iter_statements())          # 121
    passes = 2 * (statements // 7 + 1)
    assert steps == passes + STAGE_WARN_MAX + 1


def test_launch_job_runs_phase_5_in_steps(tmp_path):
    program = many_w12(tmp_path / "g", 3)
    job = LaunchJob(program, images=ImageSource.from_files(IMG))
    steps = 1
    while not job.step():
        steps += 1
    plain = LaunchJob(program)
    plain_steps = 1
    while not plain.step():
        plain_steps += 1
    assert codes(job.result) == ["W12"] * 3
    assert steps - plain_steps >= 2 + 3                  # two passes, three texts



def test_w12_suggestions_over_10_000_names_are_spread_over_steps(tmp_path, monkeypatch):
    """F04 step 9: one W12 measured all 10,000 image names in one ``step()`` (54–63 ms).
    Now no step does more than ``SUGGEST_STEP_WORK`` units (a table row or a distance) plus
    one name's, and the warnings are the ones made in one go."""
    names = [f"set{f:02} pic{i:02}" for f in range(100) for i in range(100)]
    index = ImageIndex({n: ImageFile(f"images/{n.replace(' ', '/')}.png") for n in names})
    program = story_game(tmp_path / "g", ["show hana happy", "show set0 pic00",
                                          "show set05 pic1x", '"A."'])
    G = run_launch(program).namespace
    at_once = stage_check(program, G, index)
    work = [0]
    distance, row = suggest_mod.osa_distance, suggest_mod._osa_row

    def counted_distance(*args):
        work[0] += 1
        return distance(*args)

    def counted_row(*args):
        work[0] += 1
        return row(*args)

    monkeypatch.setattr(suggest_mod, "osa_distance", counted_distance)
    monkeypatch.setattr(suggest_mod, "_osa_row", counted_row)
    check = StageCheck(program, G, index)
    per_step = []
    done = False
    while not done:
        before = work[0]
        done = check.step()
        per_step.append(work[0] - before)
    assert [w.format() for w in check.warnings] == [w.format() for w in at_once]
    assert [w.message for w in check.warnings] == [
        format_message("W12", ("hana happy",)),
        format_message("W12", ("set0 pic00", "set00 pic00")),
        format_message("W12", ("set05 pic1x", "set05 pic10"))]
    assert sum(per_step) > 4 * SUGGEST_STEP_WORK                    # more than one step's
    assert max(per_step) <= SUGGEST_STEP_WORK + SCRIPT_SUGGEST_MAX_NAME + 1


# --- AC-F04-03 — image declarations (run H) ----------------------------------------------------

def test_ac_f04_03_declarations(tmp_path):
    T = ('image bg dusk = "#2b2140"⏎image hana happy = "art/Hana_V3.png"⏎'
         'image bg sky = "#2B2140"')
    program = template_game(tmp_path / "g", T=T)
    files = [*IMG, "art/Hana_V3.png"]
    result = launch(program, files)
    assert result.warnings == () and result.namespace is not None
    index = result.images
    assert index.get("bg dusk") == SolidColor((43, 33, 64)) == index.get("bg sky")
    assert index.get("hana happy") == ImageFile("art/Hana_V3.png")
    assert ends(program, files)


def test_ac_f04_03_a_missing_declared_file(tmp_path):
    program = template_game(tmp_path / "g", T='image bg festival = "art/festival_final.png"')
    result = launch(program, IMG)
    assert placed(result) == [("W12b", "script/main.vns", 8)]
    assert result.warnings[0].message == format_message(
        "W12b", ("bg festival", "art/festival_final.png", None))
    assert result.namespace is not None
    assert result.images.get("bg festival") == ImageFile("art/festival_final.png")
    assert ends(program, IMG)


# AC-F04-18 (``with`` before F09) is retired by F09 (07 I-2); its fixture now runs in
# tests/runtime/test_transitions.py (AC-F09-07).


# --- AC-F21-37 — codex pictures checked at launch: W12 (F21 step 5) ----------------------------

F21_FILES = ("images/items/red_lantern.png",)
F21_ITEM = 'lock item red_lantern "Red Lantern" in "Things" image '


@pytest.mark.parametrize("image, args", [
    ("items red_lantern", []),
    ("items red_lanten", [("items red_lanten", "items red_lantern")]),
    ("items a b c d", [("items a b c d",)]),                # 5 words, no file
], ids=["found", "misspelled", "five-words"])
def test_ac_f21_37_codex_pictures_are_checked_at_launch(tmp_path, image, args):
    """Template C with line 6's ``image`` changed (S unlocks both tips, so a dev load has no
    W142): a dev and a release launch give F04's W12 at line 6, as for ``show``."""
    from engine.core.paths import GamePaths
    from engine.script import load_story
    from engine.script.loader import LoadOptions
    from tests.script.helpers import template_c

    script = tmp_path / "g" / "script"
    script.mkdir(parents=True)
    (script / "main.vns").write_bytes(template_c(
        S="unlock tip lanterns⏎[4]unlock tip river_god",
        replace={6: F21_ITEM + image}).encode("utf-8"))
    for dev in (True, False):
        result = load_story(GamePaths((tmp_path / "g").resolve()), LoadOptions(dev=dev))
        assert result.program is not None and result.warnings == (), result.errors
        (entry,) = [e for e in result.program.codex if e.name == "red_lantern"]
        assert entry.image == image
        found = run_launch(result.program, dev=dev, images=ImageSource.from_files(F21_FILES))
        assert found.namespace is not None
        assert placed(found) == [("W12", "script/main.vns", 6)] * len(args)
        assert [w.message for w in found.warnings] == [format_message("W12", a) for a in args]
