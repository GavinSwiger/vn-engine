"""F20 step 6: the jump through F11's load path (06 §0.3 Service S with the real
``SaveService.load_state`` and a ``RuntimeStoryDriver`` over Template L): AC-F20-27 (the call
sites; slot loads keep the saved menu while a jump offers it again), AC-F20-31 (a refused
jump), AC-F20-32 (a moved point). The shell is a stand-in that records notices, confirms, and
``show_loaded_game``; the App F end-to-end rows wait for the page (s8).
"""

import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.app.flowchart import CHANGED, NO_STATE, FlowService
from engine.app.saves import SaveService
from engine.app.story import RuntimeStoryDriver
from engine.core.config_schema import Config
from engine.core.safefile import ReadKind, ReadResult
from engine.persist.nodestates import NODE_NAME_RE, NodeEncoder, NodeFolder, node_file
from engine.persist.writer import Writer
from engine.runtime.endings import ENDING_KIND
from engine.runtime.flowchart import FLOW_KIND
from engine.ui.nav import InputKind
from engine.ui.shell import Mode
from engine.ui.theme import Words
from tests.persist import save_support as ss
from tests.runtime.flow_story import at_line, key, launched, load_l, play

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = (REPO / "tests" / "fixtures" / "F20" / "template" / "script" / "main.vns").read_text(
    encoding="utf-8")
GAME_ID = "f20-template"
STALL = "scene:stall"
WORDS = Words(Config().words)


class Shell:
    """What ``SaveService.load_state`` uses of ``GameShell``."""

    def __init__(self) -> None:
        self.mode = Mode.TITLE
        self.words = WORDS
        self.notices: list[str] = []
        self.confirms: list = []
        self.loaded = 0

    def notify(self, text: str, *, kind: str = "info") -> None:
        self.notices.append(text)

    def confirm(self, message, on_yes, *, on_no=None, by, **kwargs):
        self.confirms.append((message, on_yes, on_no))

    def show_loaded_game(self) -> None:
        self.loaded += 1


class J:
    """A jump harness: ``driver_program``'s interpreter behind the real ``SaveService``, and
    a ``FlowService`` whose recorder is ``holder``'s (disk mode under ``root`` when given)."""

    def __init__(self, driver_program, holder, *, root: Path | None = None) -> None:
        self.interp = launched(driver_program)
        self.driver = RuntimeStoryDriver(self.interp)
        self.shell = Shell()
        app = SimpleNamespace(config=Config(), story=self.driver, error_mode=False)
        self.saves = SaveService(app, self.shell, folder=None, folder_ok=False, client=None,
                                 release=False)
        folder = client = writer = None
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
            folder = NodeFolder(root, release=False)
            writer = Writer(threaded=False)
            client = writer.client("flow", root=root, names=NODE_NAME_RE)
        self.flow = FlowService(recorder=lambda: holder.flowchart,
                                node_ids=[n.id for n in driver_program.flowgraph.nodes],
                                folder=folder, client=client, writer=writer, saves=self.saves,
                                notify=lambda k: self.shell.notify(WORDS.get(k)),
                                game_id=GAME_ID, release=False, clock=ss.FakeClock(0.0001))
        self.flow.update(0.0)                         # the listing

    def jump(self, node_id: str) -> None:
        self.flow.jump(node_id, origin="title", by=InputKind.KEYS)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Template L played to line 12 (``scene:stall``'s state is held) and its program."""
    program = load_l(tmp_path_factory.mktemp("l") / "game")
    interp = launched(program)
    play(interp, until=at_line(12))
    assert interp.flowchart.state(STALL) is not None
    return SimpleNamespace(program=program, interp=interp, factory=tmp_path_factory)


def variant(run, text: str):
    return load_l(run.factory.mktemp("v") / "game", text)


# --- AC-F20-27: only the two jump paths pass fresh_menu -----------------------------------------

def test_ac_f20_27_only_the_jump_paths_pass_fresh_menu(run):
    users = set()
    for path in sorted((REPO / "engine").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.keyword) and node.arg == "fresh_menu"
                    and isinstance(node.value, ast.Constant) and node.value.value is True):
                users.add(path.relative_to(REPO).as_posix())
    assert "engine/app/flowchart.py" in users
    # F39 §4.1: a hot-reload resume is a jump too (its menu shows its current choices).
    assert users <= {"engine/app/flowchart.py", "engine/runtime/headless.py",
                     "engine/app/hot_reload.py"}
    # Behaviour: at M21 with ``promise`` opened since, a slot load presents the saved
    # waiting; a jump offers the menu again.
    holder = launched(run.program)
    play(holder, ["Buy the red one"])                   # waits at M21
    k21 = holder.checkpoint()
    m21 = next(n.id for n in run.program.flowgraph.nodes if n.kind == "choice")
    j = J(run.program, holder)
    for ending in ("sad", "good"):
        j.interp.persistent.unlock(ENDING_KIND, ending)
    texts = {c.key: c.text for c in j.interp.program.get(k21.position).choices}
    assert j.saves.load_state(k21, origin="title")
    assert [texts[k] for k in j.interp.choices.waiting.pickable] == [
        "By the river", "From the shrine steps"]
    j.jump(m21)
    assert j.shell.loaded == 2
    assert "Wait at the bridge" in [texts[k] for k in j.interp.choices.waiting.pickable]


# --- AC-F20-31: a refused jump -------------------------------------------------------------------

def _file(state, *, game: str = GAME_ID) -> bytes:
    return b"".join(NodeEncoder(state, node_id=STALL, game=game).run())


def test_ac_f20_31_a_refused_jump(run, tmp_path, monkeypatch):
    k12 = run.interp.flowchart.state(STALL)
    holder = launched(run.program)                     # no states held: the file is read
    root = tmp_path / "aiko" / "game" / "saves"
    name = node_file(STALL)
    good = _file(k12)
    reads = {
        "notice_load_damaged": b"garbage\n",
        "save_newer": good.replace(b'{"vnnode":1', b'{"vnnode":2', 1),
        "save_other_game": _file(k12, game="other-game"),
        "notice_load_failed": None,                    # MISSING (no file)
    }
    for notice, data in reads.items():
        if root.exists():
            for entry in root.iterdir():
                entry.unlink()
        if data is not None:
            root.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(data)
        j = J(run.program, holder, root=root)
        j.jump(STALL)
        assert j.shell.notices == [WORDS.get(notice)] and j.flow.reason(STALL) == NO_STATE
        assert j.shell.loaded == 0
    (root / name).write_bytes(good)                    # UNREADABLE
    monkeypatch.setattr(NodeFolder, "read",
                        lambda self, n: ReadResult(ReadKind.UNREADABLE, None, None))
    j = J(run.program, holder, root=root)
    j.jump(STALL)
    monkeypatch.undo()
    assert j.shell.notices == [WORDS.get("notice_load_failed")]
    # Restore refusals: DEFAULT_FAILED keeps Jump enabled; SCHEME_MISMATCH → changed.
    raising = variant(run, TEMPLATE.replace('default lantern = "none"\n',
                                            'default lantern = "none"\ndefault boom = int("x")\n'))
    j = J(raising, holder, root=root)
    j.jump(STALL)
    assert j.shell.notices == [WORDS.get("notice_load_failed")] and j.flow.can_jump(STALL)
    other = launched(run.program)
    other.flowchart._keep(STALL, replace(k12, identity_scheme=k12.identity_scheme + 1))
    j = J(run.program, other)
    j.jump(STALL)
    assert j.shell.notices == [WORDS.get("notice_load_no_fit")]
    assert j.flow.reason(STALL) == CHANGED and j.shell.loaded == 0


# --- AC-F20-32: a moved point --------------------------------------------------------------------

def test_ac_f20_32_a_moved_point(run):
    store = run.interp.persistent
    visited = store.is_unlocked(FLOW_KIND, key(run.program.flowgraph, "stall"))
    moved = variant(run, TEMPLATE.replace('"Daichi waves from the stall."',
                                          '"Daichi waves from his stall."'))
    j = J(moved, run.interp)
    j.jump(STALL)
    [(message, yes, _)] = j.shell.confirms
    assert message == WORDS.get("confirm_nearest") and j.shell.loaded == 0
    yes()
    assert j.shell.loaded == 1 and j.interp.current.line == 12
    stall = TEMPLATE.index("label stall:")
    gone = variant(run, TEMPLATE[:stall].replace("jump stall", "jump river")
                   + TEMPLATE[TEMPLATE.index("label river:"):])
    j = J(gone, run.interp)
    j.jump(STALL)
    assert j.shell.notices == [WORDS.get("notice_load_no_fit")] and j.shell.confirms == []
    assert j.flow.reason(STALL) == CHANGED
    assert visited and store.is_unlocked(FLOW_KIND, key(run.program.flowgraph, "stall"))
