"""AC-F24-16 (F24 A1; F23 I-19, TR-F23-09): API 1.1's hooks, the ``sig.check`` and
``sig.outcome`` wrappers, the 1.0 gate, and ``closest``.

One Loader L run loads every row's plugin; each plugin records its calls in a class-level
``log`` so a row can assert which methods ran and on how many fresh instances. The E278 row
("this engine has 1.1") is AC-F23-21's, updated in ``test_loader.py`` rather than repeated.
TR-F23-08 (``story_names(interp)`` in declaration order) needs F23 s2's interpreter and is
tested there.
"""

import pytest

from engine.core.minigame_types import MeterChange, Outcome, StoryNames
from engine.minigames import api, messages
from engine.minigames.registry import DeclarationError
from engine.runtime.errors import suggest
from tests.minigames.conftest import plugin, write

D = ("sayori", "natsuki", "yuri", "monika")
STORY = StoryNames(D, ("coin",), ("lanterns",))

_SPY = ("    log = []\n"
        "    def __init__(self):\n"
        "        type(self).log.append('new')\n"
        "    def start(self, ctx):\n"
        "        type(self).log.append('start')\n")
_ARGS = ("    def check_args(self, args):\n"
         "        type(self).log.append('check_args')\n"
         "        return args.get('args_reason')\n")
_STORY = ("    def check_story(self, args, story):\n"
          "        type(self).log.append(('check_story', type(story).__name__, story.meters))\n"
          "        return 'no meter named zed'\n")
_OUTCOME = ("    def outcome_for(self, kind, args, story):\n"
            "        type(self).log.append(('outcome_for', kind, story.meters))\n"
            "        return {'none': None, 'set': Outcome({1, 2}), 'five': 5,\n"
            "                'plain': Outcome([1, {'a': 2}], (add_points('hana', 2),)),\n"
            "                }[args.get('mode', 'plain')]\n")
_EXTRA = "from engine.minigames.api import add_points\n"

PLUGINS = {
    "story": "    api = '1.1'\n" + _SPY + _ARGS + _STORY,
    "old": "    api = '1.0'\n" + _SPY + _ARGS + _STORY + _OUTCOME,
    "old_hooks": "    api = '1.0'\n" + _SPY + _STORY + _OUTCOME,
    "only_out": "    api = '1.1'\n" + _SPY + _OUTCOME,
    "only_story": "    api = '1.1'\n" + _SPY + _STORY,
}


@pytest.fixture
def sigs(game, load):
    for name, body in PLUGINS.items():
        write(game, f"minigames/{name}.py", plugin(name, body=body, extra=_EXTRA))
    loaded = load(game)
    assert loaded.result.ok, loaded.errors
    registry = loaded.result.registry
    return {name: registry.get(name) for name in PLUGINS}


def test_check_and_outcome_wrappers(sigs):
    # (plugin, args, sig.check's answer, the calls logged by that one sig.check)
    checks = [
        ("story", {}, "no meter named zed",
         ["new", "check_args", ("check_story", "StoryNames", D)]),
        ("story", {"args_reason": "bad pairs"}, "bad pairs", ["new", "check_args"]),
        ("old", {}, None, ["new", "check_args"]),                 # the 1.0 gate
        ("only_story", {}, "no meter named zed",
         ["new", ("check_story", "StoryNames", D)]),
    ]
    for name, args, expected, calls in checks:
        entry = sigs[name]
        entry.cls.log.clear()
        assert entry.sig.check(args, STORY) == expected, name
        assert entry.cls.log == calls, name
    for name in ("old_hooks", "only_out"):
        assert sigs[name].sig.check is None, name
    for name in ("old", "old_hooks", "story", "only_story"):
        assert sigs[name].sig.outcome is None, name

    out = sigs["only_out"]
    out.cls.log.clear()
    assert out.sig.outcome("test", {"mode": "none"}, STORY) is None
    for mode in ("set", "five"):
        with pytest.raises(DeclarationError):
            out.sig.outcome("skipped", {"mode": mode}, STORY)
    got = out.sig.outcome("test", {}, STORY)
    assert got == Outcome([1, {"a": 2}], (MeterChange("hana", "+=", 2),))
    assert type(got.result) is list and type(got.result[1]) is dict
    assert type(got.changes) is tuple and type(got.changes[0]) is MeterChange
    assert out.cls.log == ["new", ("outcome_for", "test", D),
                           "new", ("outcome_for", "skipped", D),
                           "new", ("outcome_for", "skipped", D),
                           "new", ("outcome_for", "test", D)]
    # Every call used one fresh instance, and none was ever started.
    for entry in sigs.values():
        assert "start" not in entry.cls.log
    assert sigs["old"].api == "1.0" and sigs["story"].api == "1.1"


def test_a_returned_outcome_is_a_copy(sigs):
    out = sigs["only_out"]
    first = out.sig.outcome("test", {}, STORY)
    first.result[1]["a"] = 99
    assert out.sig.outcome("test", {}, STORY).result == [1, {"a": 2}]


def test_version_exports_and_closest():
    assert api.API_VERSION == (1, 4) and messages.ENGINE_API == "1.4"      # F52
    assert {"StoryNames", "closest"} <= set(api.__all__)
    assert api.StoryNames is StoryNames
    for written, expected in (("sayory", "sayori"), ("Yuri", "yuri"), ("zzz", None)):
        assert api.closest(written, D) == expected == suggest(written, D)
    assert api.closest(3, D) is None
    assert api.closest("yuri2", ["yuri", 7, None]) == "yuri"
    assert api.closest("x", iter(())) is None


def test_ac_f25_18_item_categories_field():
    """AC-F25-18's ``StoryNames`` row (F25 A5, the A5/A7 task): the field is last, with
    default ``()``, so A1's three-field form still builds. ``story_names`` fills it at s2."""
    import dataclasses

    bare = StoryNames((), (), ())
    assert bare.item_categories == ()
    assert [f.name for f in dataclasses.fields(StoryNames)] == [
        "meters", "items", "tips", "item_categories"]
    cats = (("Evidence", ("brass_key", "festival_map")), ("codex_items", ("shrine_photo",)))
    full = StoryNames(("credibility",), ("brass_key", "festival_map", "shrine_photo"), (),
                      cats)
    assert full.item_categories == cats and full != bare
    assert hash(full) == hash(StoryNames(full.meters, full.items, full.tips, cats))   # frozen
