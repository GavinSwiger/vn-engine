"""The shared ``config.toml`` key writer (F47 ``04-technical.md`` §7.2, AC-F47-18; F42
PR-F42-09, SEC-F42-13). Pure: no Tk. The window's ``apply_plan`` is the Tk step's; here
``verify`` is the gate it calls."""

import tomllib
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.tools.editor import tomlpatch as tp
from engine.tools.editor.document import encode, open_config
from engine.tools.editor.files import starter_config
from engine.tools.editor.scriptedit import FIX_FIRST, Plan, Refuse, apply_lines

ROOT = Path(__file__).resolve().parents[3]


def _editor_text(data: bytes) -> str:
    """The editor's text for file bytes: LF breaks (a Windows checkout has CRLF), no final
    break."""
    text = data.decode("utf-8").replace("\r\n", "\n")
    return text[:-1] if text.endswith("\n") else text


STARTER = _editor_text(starter_config("My Game"))
EXAMPLE = _editor_text((ROOT / "game" / "config.toml").read_bytes())
REMOVE = object()
HOSTILE = 'Lantern "Night"\\\n[window]\nwidth = 1\x7f\x00'

CW = '[content_warning]\nshow = "once"\ntext = """\nLine one.\nLine two."""  # shown first\n' \
     'version = 1'
ENTRIES = '[title]\nentries = [\n  "new_game",  # first\n  "quit",\n]\nenabled = true'

# (id, text, section, key, value or REMOVE, outcome):
#   ("swap", old, new) → text with ``old`` replaced once; ("text", t); ("none",);
#   ("refuse", text); ("bytes", file bytes, expected bytes) → CRLF and BOM through the document.
CASES = [
    ("starter-set", STARTER, "game", "version", "0.2.0",
     ("swap", 'version = "0.1.0"', 'version = "0.2.0"')),
    ("starter-escaped", STARTER, "game", "title", HOSTILE,
     ("swap", 'title = "My Game"',
      'title = "Lantern \\"Night\\"\\\\\\n[window]\\nwidth = 1\\u007F\\u0000"')),
    ("starter-commented-section-ignored", STARTER, "content_warning", "show", "once",
     ("text", STARTER + '\n\n[content_warning]\nshow = "once"')),
    ("example-commented-id", EXAMPLE, "game", "id", "my-vn",
     ("swap", '# id = "example-vn"   # set a unique id before you release',
      'id = "my-vn"   # set a unique id before you release')),
    ("example-commented-icon", EXAMPLE, "window", "icon", "gui/logo.png",
     ("swap", '# icon = "gui/icon.png"   # a PNG',
      'icon = "gui/logo.png"   # a PNG')),
    ("example-entry", EXAMPLE, "stage.positions", "by_the_rail", (100, 700),
     ("swap", "by_the_rail = 560\n", "by_the_rail = [100, 700]\n")),
    ("example-remove", EXAMPLE, "stage.positions", "by_the_rail", REMOVE,
     ("swap", "by_the_rail = 560\n", "")),
    ("example-quoted-key-new-section", EXAMPLE, "audio.loop_start", "bgm/festival.ogg", 8.0,
     ("text", EXAMPLE + '\n\n[audio.loop_start]\n"bgm/festival.ogg" = 8.0')),
    ("add-to-section", "[window]\nwidth = 800  # px\n\n[engine]\nfps = 30",
     "window", "height", 600,
     ("text", "[window]\nwidth = 800  # px\nheight = 600\n\n[engine]\nfps = 30")),
    ("add-under-bare-header", "[engine]\n# notes\n\n[game]\ntitle = \"A\"",
     "engine", "fps", 30, ("text", "[engine]\nfps = 30\n# notes\n\n[game]\ntitle = \"A\"")),
    ("keep-spacing-and-comment", "[engine]\n  fps   =   60   # frames", "engine", "fps", 30,
     ("text", "[engine]\n  fps   =   30   # frames")),
    ("multi-line-string", CW, "content_warning", "text", "New.",
     ("swap", '"""\nLine one.\nLine two."""', '"New."')),
    ("multi-line-array", ENTRIES, "title", "entries", ["new_game", "load", "quit"],
     ("text", '[title]\nentries = ["new_game", "load", "quit"]\nenabled = true')),
    ("remove-multi-line", ENTRIES, "title", "entries", REMOVE,
     ("text", "[title]\nenabled = true")),
    ("dotted-key", "[stage]\npositions.by_the_rail = 560", "stage.positions", "by_the_rail",
     600, ("text", "[stage]\npositions.by_the_rail = 600")),
    ("color-new-section-empty-doc", "", "theme.textbox", "text_color", (255, 0, 16),
     ("text", '[theme.textbox]\ntext_color = "#FF0010"')),
    ("float", "[audio]\nmusic_fadeout = 0.5\n", "audio", "music_fadeout", 1.0,
     ("text", "[audio]\nmusic_fadeout = 1.0\n")),
    ("same-value", "[engine]\nfps = 60", "engine", "fps", 60, ("none",)),
    ("remove-absent", "[engine]\nfps = 60", "engine", "cache_mb", REMOVE, ("none",)),
    ("crlf-bom", "", "engine", "fps", 30,
     ("bytes", b"\xef\xbb\xbf# c\r\n[engine]\r\nfps = 60\r\n\r\n[game]\r\ntitle = \"A\"\r\n",
      b"\xef\xbb\xbf# c\r\n[engine]\r\nfps = 30\r\n\r\n[game]\r\ntitle = \"A\"\r\n")),
    ("refuse-inline-table", "[stage]\npositions = { by_the_rail = 560 }",
     "stage.positions", "by_the_rail", 600, ("refuse", tp.COMPLEX)),
    ("refuse-inline-root", 'game = { title = "A" }', "game", "title", "B",
     ("refuse", tp.COMPLEX)),
    ("refuse-array-of-tables", '[[game]]\ntitle = "A"', "game", "title", "B",
     ("refuse", tp.COMPLEX)),
    ("refuse-broken", '[game]\ntitle = "A"\nx = = 1', "game", "title", "B",
     ("refuse", FIX_FIRST.format(file="config.toml", line=3))),
    ("refuse-unknown-key", "[game]", "game", "colour", "red",
     ("refuse", tp.NOT_A_SETTING.format(section="game", key="colour"))),
    ("refuse-bad-value", "[game]", "game", "id", "Bad ID!", ("refuse", "[game] id must be")),
    ("refuse-wrong-type", "[game]", "game", "title", 5, ("refuse", "[game] title must be")),
]


def _plan(text, section, key, value):
    if value is REMOVE:
        return tp.plan_remove(text, section, key)
    return tp.plan_set(text, section, key, value)


@pytest.mark.parametrize("text, section, key, value, outcome",
                         [case[1:] for case in CASES], ids=[case[0] for case in CASES])
def test_toml_patcher_ac_f47_18(tmp_path, text, section, key, value, outcome):
    """AC-F47-18 (and F42 AC-F42-14's `# id`, SEC-F42-13): set, add to a section, new
    section, remove; untouched lines byte-identical; CRLF and BOM kept; refused shapes."""
    kind = outcome[0]
    doc = None
    if kind == "bytes":
        (tmp_path / "config.toml").write_bytes(outcome[1])
        doc = open_config(GamePaths.for_game(tmp_path))
        text = doc.text
    plan = _plan(text, section, key, value)
    if kind == "none":
        assert plan is None
        return
    if kind == "refuse":
        assert isinstance(plan, Refuse) and plan.text.startswith(outcome[1]), plan
        return
    assert isinstance(plan, tp.TomlPlan), plan
    assert tp.verify(plan, text)
    lines = text.split("\n")
    new = "\n".join(apply_lines(lines, plan.edits))
    if kind == "swap":
        assert text.count(outcome[1]) == 1
        assert new == text.replace(outcome[1], outcome[2])
    elif kind == "text":
        assert new == outcome[1]
    else:
        assert encode(doc, new) == outcome[2]
    # Read back: the value as written (the hostile title too), or gone.
    node = tomllib.loads(new)
    for part in section.split("."):
        node = node.get(part, {})
    if value is REMOVE:
        assert key not in node and plan.removed
    else:
        assert node[key] == (list(value) if isinstance(value, tuple) and len(value) == 2
                             else plan.value)
        if isinstance(value, str):
            assert node[key] == value
    # One undo step in F46's plan shape.
    as_plan = plan.as_plan()
    assert isinstance(as_plan, Plan) and len(as_plan.files) == 1
    assert as_plan.files[0].ref == "config.toml" and as_plan.files[0].edits == plan.edits
    # Stale: any guarded line changed → verify fails; a plan writing another value fails.
    for number, old in plan.guards:
        stale = list(lines)
        stale[number - 1] = old + " # changed" if old.strip() else "# changed"
        assert not tp.verify(plan, "\n".join(stale))
    if not plan.removed:
        wrong = tp.TomlPlan(plan.title, plan.ref, plan.section, plan.key, "other",
                            plan.edits, plan.guards)
        assert not tp.verify(wrong, text)


def test_ac_f42_14_build_details_one_plan_strict_parse_back():
    """AC-F42-14 (SEC-F42-13, 07 I-8): Build's changed title/version/id/icon as one plan:
    their lines replaced (``# id``/``# icon`` too), every other line unchanged; ``verify``
    refuses any other parse-level change, even a vanished empty table; a bad icon ref is
    refused before planning."""
    changes = [("game", "title", 'Lanterns "2"'), ("game", "version", "0.2.0"),
               ("game", "id", "lanterns"), ("window", "icon", "gui/logo.png")]
    plan = tp.plan_changes(EXAMPLE, changes)
    assert isinstance(plan, tp.TomlPlan) and len(plan.edits) == 1 and tp.verify(plan, EXAMPLE)
    assert [c[:2] for c in plan.changes] == [c[:2] for c in changes]
    old = EXAMPLE.split("\n")
    new = apply_lines(old, plan.edits)
    assert len(new) == len(old)
    changed = {i + 1: line for i, line in enumerate(new) if line != old[i]}
    assert changed == {5: 'title = "Lanterns \\"2\\""', 6: 'version = "0.2.0"',
                       11: 'id = "lanterns"   # set a unique id before you release',
                       18: 'icon = "gui/logo.png"   # a PNG in the game folder; unset = '
                           'the engine icon'}
    assert tomllib.loads("\n".join(new))["game"]["title"] == 'Lanterns "2"'
    # Parse-back: the same edit plus one unplanned line change is refused.
    edit = plan.edits[0]
    sneaky = [*edit.lines, "width = 1"]          # valid TOML, but not planned
    assert tomllib.loads("\n".join(apply_lines(old, (type(edit)(edit.first, edit.last,
                                                                tuple(sneaky)),))))
    for bad in (tp.TomlPlan(plan.title, plan.ref, plan.section, plan.key, plan.value,
                            (type(edit)(edit.first, edit.last, tuple(sneaky)),), plan.guards,
                            more=plan.more),
                tp.TomlPlan(plan.title, plan.ref, plan.section, plan.key, plan.value,
                            plan.edits, plan.guards, more=plan.more[:-1])):
        assert not tp.verify(bad, EXAMPLE)
    # Strict: a removal may not take an unrelated empty table with it.
    text = "[engine]\nfps = 60\n[audio]"
    gone = tp.TomlPlan("t", "config.toml", "engine", "fps", None,
                       (type(edit)(2, 3, ()),), ((2, "fps = 60"), (3, "[audio]")))
    assert not tp.verify(gone, text)
    assert tp.verify(tp.plan_remove(text, "engine", "fps"), text)
    # The icon is a game-folder ref (check_ref), refused before anything is planned.
    for ref in ("../icon.png", "C:/icon.png", "saves/icon.png"):
        refused = tp.plan_changes(EXAMPLE, [("window", "icon", ref)])
        assert isinstance(refused, Refuse) and refused.text.startswith("[window] icon must")
    assert tp.plan_changes(EXAMPLE, [("game", "version", "0.1.0")]) is None
