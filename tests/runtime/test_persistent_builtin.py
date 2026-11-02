"""F32 step 1: the built-in ``persistent.playthrough`` (F32 ``06-acceptance.md`` AC-F32-03;
``04`` §1.2 C5, §4.2; 07 I-11).

Run on F12's template P with an in-memory store per "file": a relaunch reuses the store
(the values a file would hold), and a deleted ``persistent.json`` is a fresh store.
"""

import pytest

from engine.runtime.commands import StoryEnded
from engine.runtime.headless import run_headless
from engine.runtime.launch import LaunchJob, run_launch
from engine.runtime.persistent import PersistentStore
from tests.runtime.test_persistent_story import load_p

AUTHOR = "default persistent.playthrough = 1"
READ = "$ persistent.read = persistent.playthrough"


def run(root, store, **edit):
    """Run P; the value the story read (``READ``), else None."""
    commands = run_headless(load_p(root, **edit), seed=42, persistent=store)
    assert type(commands[-1]) is StoryEnded, commands[-1]
    return store.peek("read") if edit.get("S") == READ else None


@pytest.mark.parametrize("author", [False, True], ids=["builtin", "author"])
def test_ac_f32_03_the_builtin_playthrough(tmp_path, monkeypatch, author):
    T = AUTHOR if author else None
    launch_value = 1 if author else 0
    # No file: reading it never stops the story (no E180); an author default wins (no E184).
    store = PersistentStore(identity_scheme=1)
    assert run(tmp_path / "a", store, S=READ, T=T) == launch_value
    # Stored 3, relaunch: 3. Then _clear() and F16's reset return to the launch value.
    store.set("playthrough", 3)
    assert run(tmp_path / "b", store, S=READ, T=T) == 3
    run(tmp_path / "c", store, S="$ persistent._clear()", T=T)
    assert store.peek("playthrough") == launch_value
    store.set("playthrough", 3)
    store.reset()
    assert store.peek("playthrough") == launch_value
    # persistent.json deleted, then relaunch: a fresh store.
    fresh = PersistentStore(identity_scheme=1)
    run_launch(load_p(tmp_path / "d", T=T), persistent=fresh)
    assert fresh.peek("playthrough") == launch_value
    # The author sets it; the next launch reads it.
    run(tmp_path / "e", fresh, S="$ persistent.playthrough = len(persistent.endings) + 2", T=T)
    assert fresh.peek("playthrough") == 2
    assert run(tmp_path / "f", fresh, S=READ, T=T) == 2

    # Call order: after the last author default, before W56 (dev); with an author default it
    # changes nothing.
    calls = []
    spy = PersistentStore(identity_scheme=1)
    for name in ("set_default", "set_builtin_default"):
        real = getattr(spy, name)
        monkeypatch.setattr(spy, name, lambda n, v, _real=real, _name=name: (
            calls.append((_name, n, v)), _real(n, v))[1])
    w56 = LaunchJob._w56
    monkeypatch.setattr(LaunchJob, "_w56", lambda job, s: (calls.append(("W56",)), w56(job, s))[1])
    result = run_launch(load_p(tmp_path / "g", S="$ x = persistent.playthrough", T=T),
                        persistent=spy, dev=True)
    assert result.namespace is not None and result.warnings == ()
    at = calls.index(("set_builtin_default", "playthrough", 0))
    assert calls[-1] == ("W56",) and calls.count(("W56",)) == 1
    assert [c[1] for c in calls[:at]] == \
        ["festivals", "hana_remembers", *(["playthrough"] if author else [])]
    assert calls[at + 1:-1] == ([] if author else [("set_default", "playthrough", 0)])
    assert spy.peek("playthrough") == launch_value
