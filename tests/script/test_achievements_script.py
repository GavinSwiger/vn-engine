"""F37 S2: achievements' script side (``script/achievements.py``, ``program.py``,
``checks.py``, ``bindings.py``): AC-F37-01 (every §3 form parses to its values in reading
order; ``achievement``, ``hidden`` and ``when`` stay usable as variables; ``unlock
achievement`` in a label is F19's ``Lock``) and AC-F37-02 (E340's limit forms and W224 only
in dev loads). Every E339 text, E340's twice and unknown forms with did-you-mean and W224's
text are rows of ``tests/fixtures/F02/messages/cases.toml`` (AC-F37-01, 02, 08)."""

from engine.script import LoadOptions, load_story
from engine.script.identity import walk_block
from engine.script.routes import Lock
from tests.runtime.menu_story import write_game

DECLS = ('lock achievement first_steps "First Steps" "Finish the {{prologue}." '
         'image achievements first_steps\n'
         'include "database.vns"\n'
         'lock achievement completionist "Completionist" "See every ending." '
         'when "good" in persistent.endings and "true" in persistent.endings  # both\n')
DATABASE = ('lock  achievement  garden  "Secret Garden"  "Find the hidden garden."  hidden\n'
            'lock achievement lantern "Lantern" image cg lantern hidden when achievement > 2\n'
            'lock achievement plain "Plain"\n')


def test_ac_f37_01_declarations_and_names_still_free(tmp_path):
    story = (DECLS + "default achievement = 0\ndefault hidden = False\ndefault when = 1\n"
             "label start:\n    $ achievement += when\n    if hidden:\n"
             "        unlock achievement plain\n    unlock achievement garden\n"
             '    "End."\n')
    root = tmp_path / "g"
    paths = write_game(root, story)
    (root / "script" / "database.vns").write_text(DATABASE, encoding="utf-8")
    result = load_story(paths, LoadOptions(dev=True))
    assert result.errors == (), [e.format() for e in result.errors]
    rows = [(a.name, a.title, a.description, a.image, a.hidden, a.when, a.sid, a.file.ref,
             a.line) for a in result.program.achievements]
    assert rows == [                                      # reading order (includes after)
        ("first_steps", "First Steps", "Finish the {prologue}.", "achievements first_steps",
         False, None, "achievement:first_steps", "script/main.vns", 1),
        ("completionist", "Completionist", "See every ending.", None, False,
         '"good" in persistent.endings and "true" in persistent.endings',
         "achievement:completionist", "script/main.vns", 3),
        ("garden", "Secret Garden", "Find the hidden garden.", None, True, None,
         "achievement:garden", "script/database.vns", 1),
        ("lantern", "Lantern", "", "cg lantern", True, "achievement > 2",
         "achievement:lantern", "script/database.vns", 2),
        ("plain", "Plain", "", None, False, None, "achievement:plain", "script/database.vns",
         3),
    ]
    program = result.program
    assert program.achievements[0].when_code is None
    assert eval(program.achievements[1].when_code,                       # compiled once
                {"persistent": type("P", (), {"endings": ["good", "true"]})}) is True
    assert eval(program.achievements[3].when_code, {"achievement": 3}) is True
    locks = [(s.unlock, s.kind, s.name) for s, _ in walk_block(program.labels["start"].block)
             if isinstance(s, Lock)]
    assert locks == [(True, "achievement", "plain"), (True, "achievement", "garden")]
    # W224 (dev): first_steps has no when and no line; completionist and lantern have when.
    assert [(w.code, w.line) for w in result.warnings if w.code == "W224"] == [("W224", 1)]


def test_ac_f37_02_limits_and_w224_only_in_dev(tmp_path):
    """E340's many (over 200) and when (over 64) forms, once each, for the whole game; W224
    in dev loads only."""
    many = "".join(f'lock achievement a{i} "A{i}"' + (f" when n == {i}" if i < 65 else "") + "\n"
                   for i in range(201))
    paths = write_game(tmp_path / "many", "default n = 0\n" + many +
                       'label start:\n    "Hi."\n')
    result = load_story(paths, LoadOptions(dev=False))
    texts = [e.format() for e in result.errors if e.code == "E340"]
    assert texts == ["this story has 201 achievements; the engine allows 200.",
                     "this story has 65 achievements with when; the engine allows 64."]
    one = 'lock achievement lonely "Lonely"\nlabel start:\n    "Hi."\n'
    release = load_story(write_game(tmp_path / "r", one), LoadOptions(dev=False))
    dev = load_story(write_game(tmp_path / "d", one), LoadOptions(dev=True))
    assert release.errors == () and dev.errors == ()
    assert [w.code for w in release.warnings] == []
    assert [w.code for w in dev.warnings] == ["W224"]
