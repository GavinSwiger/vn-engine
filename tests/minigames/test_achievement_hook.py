"""F37 step 1 (pure): the achievement platform hook (API 1.2) and "local only".

AC-F37-09: registration through Loader L (a hook-only plugin file loads with no W161; both
registration error forms, E273 P with file and line: F37 §3 calls them E272's plugin form,
but they are load-time declaration errors, F23's E273), then ``HookRunner`` with a fake hook
and clock: ``started`` once with the recorded names, ``unlocked`` per call, raising → W225
and off, slow → W225 once, the watchdog → W225. Calling ``unlocked`` after the notice is
F37-S2's (``app/achievements.py``; AC-F37-05).
AC-F37-10: importing and running the achievements modules adds no network module to
``sys.modules`` (a fresh interpreter), and none of them imports one; a game with no hook
works (``HookRunner(None)``).
"""

import ast
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from engine.minigames import achievement_hook, messages
from engine.minigames.achievement_hook import AchievementHook, HookRunner
from tests.minigames.conftest import write

REPO = Path(__file__).resolve().parents[2]
NETWORK = ("socket", "ssl", "http", "urllib", "_socket", "_ssl")

HOOK_ONLY = """\
from engine.minigames import api


class StoreHook:
    def __init__(self):
        self.calls = []

    def started(self, unlocked):
        self.calls.append(("started", unlocked))

    def unlocked(self, name):
        self.calls.append(("unlocked", name))


HOOK = StoreHook()
api.register_achievement_hook(HOOK)
"""


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FiringGuard:
    def __init__(self) -> None:
        self.fired = False

    def enter(self) -> None:
        pass

    def exit(self) -> None:
        pass

    def consume_fired(self) -> bool:
        fired, self.fired = self.fired, False
        return fired


@pytest.fixture(autouse=True)
def no_bundled(monkeypatch):
    from engine.minigames import bundled
    monkeypatch.setattr(bundled, "BUNDLED", ())


def test_ac_f37_09_hook_registration_and_runner(game, load, caplog):
    write(game, "minigames/store.py", HOOK_ONLY)
    loaded = load(game)
    assert loaded.result.ok and loaded.warnings("W161") == [] and loaded.names == []
    hook = loaded.result.registry.achievement_hook
    assert hook is not None and hook.unit == "minigames/store.py"
    module = sys.modules["_vn_minigames.store"]
    assert hook.unlocked.__self__ is module.HOOK and hook.started.__self__ is module.HOOK

    write(game, "minigames/twice.py", HOOK_ONLY.replace("HOOK = StoreHook()",
                                                        "HOOK = StoreHook()\n\n"))
    write(game, "minigames/z_shape.py", "from engine.minigames import api\n\n\n"
                                        "class Nope:\n    pass\n\n\n"
                                        "api.register_achievement_hook(Nope())\n")
    write(game, "minigames/z_class.py", HOOK_ONLY.replace("register_achievement_hook(HOOK)",
                                                          "register_achievement_hook(StoreHook)"))
    loaded = load(game)
    assert loaded.codes == ["E273", "E273", "E273"]
    assert loaded.errors == [
        "minigames/twice.py, line 18: " + messages.E273_HOOK_TWICE,
        "minigames/z_class.py, line 16: " + messages.E273_HOOK_SHAPE,
        "minigames/z_shape.py, line 8: " + messages.E273_HOOK_SHAPE]
    assert loaded.result.registry.achievement_hook.unit == "minigames/store.py"
    assert messages.E273_HOOK_SHAPE == ("register_achievement_hook needs an object with an "
                                        "unlocked(name) method.")

    caplog.set_level(logging.WARNING, logger="vn.plugin")
    calls: list[tuple] = []
    clock = Clock()

    def unlocked(name):
        calls.append(("unlocked", name))
        if name == "slow":
            clock.now += 0.4
        if name == "boom":
            raise RuntimeError("store offline at 10.0.0.1")

    runner = HookRunner(AchievementHook("minigames/store.py", unlocked,
                                        lambda names: calls.append(("started", names))),
                        clock=clock)
    runner.started(("first_steps",))
    runner.started(("again",))                                      # once per session
    runner.unlocked("garden")
    runner.unlocked("slow")
    runner.unlocked("slow")                                         # slow form once
    assert runner.active
    runner.unlocked("boom")
    runner.unlocked("later")                                        # off: not called
    assert calls == [("started", ("first_steps",)), ("unlocked", "garden"),
                     ("unlocked", "slow"), ("unlocked", "slow"), ("unlocked", "boom")]
    assert not runner.active and runner.off
    w225 = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W225"]
    assert w225 == [
        "the achievement platform hook took 0.4 s in unlocked; keep hook calls under 0.1 s so "
        "the game doesn't stall.",
        "the achievement platform hook failed in unlocked (RuntimeError), so it is off until "
        "the game restarts. Achievements are still kept on this computer."]
    assert achievement_hook.SLOW_S == 0.1

    guard = FiringGuard()

    def stuck(_names):
        guard.fired = True
        raise KeyboardInterrupt

    caplog.clear()
    runner = HookRunner(AchievementHook("u", lambda n: None, stuck), guard=guard)
    runner.started(())
    assert runner.off and [r.getMessage() for r in caplog.records] == [
        messages.w225_failed("started", "it ran too long")]
    no_started = HookRunner(AchievementHook("u", lambda n: calls.append(n)))
    no_started.started(("x",))
    no_started.unlocked("y")
    assert calls[-1] == "y"


def test_ac_f37_10_no_network_module_and_no_hook_works():
    sources = [REPO / "engine" / p for p in ("runtime/achievements.py",
                                             "ui/builtin/achievements_page.py",
                                             "minigames/achievement_hook.py")]
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n.split(".")[0] in NETWORK for n in names), (path, names)
    script = textwrap.dedent(f"""
        import sys
        import engine.runtime.interpreter, engine.ui.menus, engine.ui.widgets
        import engine.minigames.api, engine.ui.notice
        NETWORK = {NETWORK!r}
        before = {{m for m in sys.modules if m.split(".")[0] in NETWORK}}
        from types import SimpleNamespace
        from engine.runtime import achievements
        from engine.runtime.persistent import PersistentStore
        from engine.runtime.guard import NO_GUARD
        from engine.minigames.achievement_hook import HookRunner
        from engine.ui.builtin import achievements_page
        decl = SimpleNamespace(name="done", title="Done", description="", image=None,
                               hidden=False, when="True", when_code=compile("True", "w", "eval"),
                               line=1, file=None)
        interp = SimpleNamespace(program=SimpleNamespace(achievements=[decl]),
                                 persistent=PersistentStore(identity_scheme=1),
                                 _test=lambda code: bool(eval(code, {{}})), guard=NO_GUARD)
        achievements.register(interp)
        assert achievements.check_pending(interp) == ("done",)
        runner = HookRunner(None)
        runner.started(("done",))
        runner.unlocked("done")
        assert not runner.active
        class Port:
            def achievements(self): return [decl]
            def unlocked(self): return {{"done"}}
            def icon(self, image): return None
        model = achievements_page.achievements_model(Port(), None)
        assert model.unlocked == 1
        after = {{m for m in sys.modules if m.split(".")[0] in NETWORK}}
        print(sorted(after - before))
    """)
    done = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "[]"
