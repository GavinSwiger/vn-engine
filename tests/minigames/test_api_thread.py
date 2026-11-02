"""AC-F23-53 (SEC-F23-11; 05 group H): every object a plugin can reach from its ``Context``
checks the calling thread.

Step 3a builds the wrappers; the host's real ports arrive at step 4 (Host U). Here the
ports are recorders, the scope and painter are stand-ins with F10-like methods, and the dice
are the runtime's ``DiceFacade``. The method list is built by introspection
(``public_members``), so a method added later is covered automatically. The E275 mapping of
a ``MinigameThreadError`` raised inside a plugin call is the host's (step 4).
"""

import threading

import pytest

from engine.minigames.api import MinigameThreadError
from engine.minigames.context import Context, ThreadBound, bind, public_members
from engine.runtime.dice import Pcg32, make_dice


class Recorder:
    """A port that records every call and returns a fresh stand-in object."""

    def __init__(self, name: str, calls: list) -> None:
        self._name = name
        self._calls = calls

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)

        def call(*args, **kwargs):
            self._calls.append((self._name, attr))
            if attr in ("music", "codex_view"):
                return Gadget(self._calls, attr)
            return None
        return call


class Gadget:
    """A stand-in engine object (scope, painter, music handle, codex view)."""

    def __init__(self, calls: list, label: str) -> None:
        self._calls = calls
        self._label = label

    def focus(self, *args, **kwargs):
        self._calls.append((self._label, "focus"))

    def refresh(self):
        self._calls.append((self._label, "refresh"))

    @property
    def current(self):
        self._calls.append((self._label, "current"))
        return None


@pytest.fixture
def world():
    calls: list = []
    main = threading.get_ident()
    core = Pcg32(ready=True)
    core.seed(7)
    dice = make_dice(core)
    ctx = Context(main, port=Recorder("port", calls), args={"pairs": 6, "deck": [1, [2]]},
                  points=Recorder("points", calls), codex=Recorder("codex", calls), dice=dice,
                  theme=Recorder("theme", calls), words=Recorder("words", calls),
                  scope=Gadget(calls, "scope"), painter=Gadget(calls, "painter"), dev=True,
                  log=__import__("logging").getLogger("vn.plugin"))
    return ctx, calls, core


def reachable(ctx: Context) -> list[ThreadBound]:
    """Every API object reachable from ``ctx`` (main thread)."""
    return [ctx, ctx.points, ctx.codex, ctx.random, ctx.theme, ctx.words, ctx.scope,
            ctx.painter, ctx.music(), ctx.codex_view(filter=None)]


def _real_views(main: int) -> list[ThreadBound]:
    """F10's real ``FocusScope`` and F21's real ``CodexView`` (bare: ``bind`` reads only the
    type), bound, so the walk covers their read-only fields."""
    from engine.ui.builtin.codex_page import CodexView
    from engine.ui.focus import FocusScope

    view = CodexView.__new__(CodexView)
    view.groups_changed = False
    return [bind(FocusScope(), main), bind(view, main)]


def test_every_public_method_checks_the_thread(world):
    ctx, calls, core = world
    objects = reachable(ctx) + _real_views(threading.get_ident())
    calls.clear()
    state = core.state
    checked: list[str] = []
    failures: list[str] = []

    def worker():
        for obj in objects:
            for name in public_members(obj):
                label = f"{type(obj).__name__}.{name}"
                checked.append(label)
                try:
                    value = getattr(obj, name)            # a property raises here
                    value()                               # a method raises here
                except MinigameThreadError:
                    continue
                except BaseException as e:                # noqa: BLE001
                    failures.append(f"{label}: {type(e).__name__}")
                    continue
                failures.append(f"{label}: no error")

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    assert failures == []
    assert calls == []                                    # no port or engine object touched
    assert core.state == state                            # no dice drawn
    names = set(checked)
    for expected in ("Context.args", "Context.finish", "Context.music", "Context.codex_view",
                     "Context.settings", "Context.area", "Context.log", "Context.confirm",
                     "Context.story",
                     "PointsHandle.add", "PointsHandle.get", "PointsHandle.highest",
                     "CodexHandle.unlock_tip", "CodexHandle.has", "DiceHandle.roll",
                     "DiceHandle.shuffle", "ThemeReader.mine", "WordsReader.mine",
                     "BoundGadget.focus", "BoundGadget.current",
                     "BoundFocusScope.focused", "BoundCodexView.groups_changed"):
        assert expected in names
    assert len(names) >= 40


def test_main_thread_calls_reach_the_ports(world):
    ctx, calls, _ = world
    ctx.points.add("hana", 1)
    ctx.codex.give("paper_lantern")
    ctx.hint("Find the pairs")
    ctx.scope.focus()
    assert calls == [("points", "add"), ("codex", "give"), ("port", "hint"), ("scope", "focus")]
    assert 1 <= ctx.random.roll(1, 6) <= 6
    assert ctx.args == {"pairs": 6, "deck": [1, [2]]} and ctx.dev is True


def test_args_are_a_deep_copy():
    source = {"deck": [1, [2]]}
    ctx = Context(threading.get_ident(), port=None, args=source, points=None, codex=None,
                  dice=None, theme=None, words=None, scope=object(), painter=object(),
                  dev=False, log=None)
    ctx.args["deck"][1].append(3)
    assert source == {"deck": [1, [2]]}


def test_engine_objects_are_never_handed_out_unwrapped(world):
    ctx, _, core = world
    for obj in reachable(ctx):
        assert isinstance(obj, ThreadBound)


def test_a_method_added_later_is_covered():
    class Later(ThreadBound):
        __slots__ = ()

        def new_call(self):
            return 1

    other = Later(-1)                                    # "main" is some other thread
    assert "new_call" in public_members(other)
    with pytest.raises(MinigameThreadError):
        other.new_call()
    bound = bind(Gadget([], "x"), -1)
    with pytest.raises(MinigameThreadError):
        bound.refresh()


def test_ac_f25_19_ctx_story_is_the_names_object():
    """AC-F25-19's ``ctx.story`` row, unit half (F25 A5; the host passes
    ``StartMinigame.names`` at s4): the same object, and checked like every property."""
    from engine.core.minigame_types import StoryNames

    names = StoryNames(("hana",), ("coin",), (), (("codex_items", ("coin",)),))
    main = threading.get_ident()
    ctx = Context(main, port=None, args={}, points=None, codex=None, dice=None, theme=None,
                  words=None, scope=object(), painter=object(), dev=False, log=None,
                  story=names)
    assert ctx.story is names
    bare = Context(main, port=None, args={}, points=None, codex=None, dice=None, theme=None,
                   words=None, scope=object(), painter=object(), dev=False, log=None)
    assert bare.story == StoryNames((), (), ())
    errors = []

    def worker():
        try:
            ctx.story
        except MinigameThreadError as e:
            errors.append(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    assert len(errors) == 1


def _read_off_thread(read) -> list:
    errors: list = []

    def worker():
        try:
            read()
        except MinigameThreadError as e:
            errors.append(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    return errors


def test_scope_focused_is_a_checked_read():
    """``ctx.scope.focused`` (API 1.1, additive): F10's focused widget, live, read-only, and
    checked like every property."""
    from engine.ui.focus import FocusScope

    scope = FocusScope()
    ctx = Context(threading.get_ident(), port=None, args={}, points=None, codex=None,
                  dice=None, theme=None, words=None, scope=scope, painter=object(),
                  dev=False, log=None)
    assert ctx.scope.focused is None
    widget = object()
    scope.focused = widget
    assert ctx.scope.focused is widget
    with pytest.raises(AttributeError):
        ctx.scope.focused = None
    assert scope.focused is widget
    assert "focused" in public_members(ctx.scope)
    assert len(_read_off_thread(lambda: ctx.scope.focused)) == 1


def test_codex_view_groups_changed_is_a_checked_read():
    """A bound ``CodexView``'s ``groups_changed`` (API 1.1, additive): live, read-only, and
    checked like every property."""
    from engine.ui.builtin.codex_page import CodexView

    view = CodexView.__new__(CodexView)              # ``bind`` reads only the type
    view.groups_changed = False
    bound = bind(view, threading.get_ident())
    assert bound.groups_changed is False
    view.groups_changed = True
    assert bound.groups_changed is True
    with pytest.raises(AttributeError):
        bound.groups_changed = False
    assert view.groups_changed is True
    assert "groups_changed" in public_members(bound)
    assert len(_read_off_thread(lambda: bound.groups_changed)) == 1


# --- AC-F27-22 (F27 A9; F23 SPEC I-21): ctx.codex.title ----------------------------------------

class TitlePort:
    """A fake minigame ``CodexPort`` on Template R's codex (F27 ``06`` §5): the A9 rules of
    F23 ``04`` §4.3, with a ledger and a read-mark record that ``title`` must never touch."""

    TITLES = {"rusty_key": "Rusty Key", "string": "String", "magnet": "Magnet",
              "magnet_string": "Magnet on a String", "door_key": "Door Key",
              "lanterns": "Paper Lanterns"}

    def __init__(self, held: tuple[str, ...]) -> None:
        self.held = held
        self.ledger: list = []
        self.marks: list = []
        self.asked: list = []

    def items(self):
        return self.held

    def give(self, name):
        self.ledger.append(("give", name))

    def title(self, name):
        from engine.runtime.codex import UnknownEntry
        self.asked.append(name)
        if type(name) is not str:
            raise TypeError(f"an item or tip name must be text, not {type(name).__name__}")
        if name not in self.TITLES:
            raise UnknownEntry(name, "item", None)
        return self.TITLES[name]


def _ledger_port(held: tuple[str, ...]):
    """F23 s4's real ``LedgerCodexPort`` over Template R's codex (F27 ``06`` §5), its ledger
    and read marks watched: ``title`` must touch neither."""
    from engine.minigames.host import LedgerCodexPort
    from engine.runtime.codex import CodexIndex
    from engine.runtime.commands import MinigameBase
    from engine.runtime.minigame import MinigameLedger, entry_check
    from engine.script.codex import CodexCategory, CodexEntry

    items, tips = CodexCategory("item", None, "codex_items"), CodexCategory("tip", None,
                                                                             "codex_tips")
    entries = tuple(CodexEntry(name, "tip" if name == "lanterns" else "item", title,
                               tips if name == "lanterns" else items, None, (), "s",
                               "script/main.vns", 1)
                    for name, title in TitlePort.TITLES.items())
    index = CodexIndex(entries, (items, tips))
    ledger = MinigameLedger(MinigameBase((), held, ()), check_meter=lambda n: None,
                            check_entry=entry_check(index))
    marks: list = []
    port = LedgerCodexPort(threading.get_ident(), ledger, index, is_read=lambda n: False,
                           mark_read=marks.append, picture=lambda i: None, show_locked=False)
    return port, ledger, marks


@pytest.mark.parametrize("half", ["handle", "port"])
def test_ac_f27_22_codex_title(half):
    """The handle rows run at the A9 task with a fake port: ``title`` forwards to the port
    (held or not; a tip), the port's refusals reach the caller unchanged (the host maps them
    to E275), a worker thread gets ``MinigameThreadError`` before the port is asked, and no
    call makes a ledger request or a read mark."""
    from engine.runtime.codex import UnknownEntry

    class Name(str):
        pass

    main = threading.get_ident()
    if half == "port":
        for held in ((), ("rusty_key",)):
            port, ledger, marks = _ledger_port(held)
            ctx = Context(main, port=None, args={}, points=None, codex=port, dice=None,
                          theme=None, words=None, scope=object(), painter=object(),
                          dev=False, log=None)
            assert ctx.codex.title("rusty_key") == "Rusty Key"
            assert ctx.codex.title("lanterns") == "Paper Lanterns"
            with pytest.raises(UnknownEntry):
                ctx.codex.title("zzz")
            for bad in (3, Name("rusty_key")):
                with pytest.raises(TypeError):
                    ctx.codex.title(bad)
            errors = []

            def port_worker():
                try:
                    port.title("rusty_key")
                except MinigameThreadError as e:
                    errors.append(e)

            thread = threading.Thread(target=port_worker)
            thread.start()
            thread.join(timeout=10)
            assert len(errors) == 1
            assert ledger.changes == () and marks == [] and ledger.items() == held
        return
    for held in ((), ("rusty_key",)):
        port = TitlePort(held)
        ctx = Context(main, port=None, args={}, points=None, codex=port, dice=None,
                      theme=None, words=None, scope=object(), painter=object(), dev=False,
                      log=None)
        assert ctx.codex.title("rusty_key") == "Rusty Key"            # held and not held
        assert ctx.codex.title("lanterns") == "Paper Lanterns"        # a locked tip
        with pytest.raises(UnknownEntry):
            ctx.codex.title("zzz")
        for bad in (3, Name("rusty_key")):
            with pytest.raises(TypeError):
                ctx.codex.title(bad)
        errors = []

        def worker():
            try:
                ctx.codex.title("rusty_key")
            except MinigameThreadError as e:
                errors.append(e)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=10)
        assert len(errors) == 1
        assert port.asked[:2] == ["rusty_key", "lanterns"] and len(port.asked) == 5
        assert port.ledger == [] and port.marks == [] and port.held == held
    assert "title" in public_members(ctx.codex)
