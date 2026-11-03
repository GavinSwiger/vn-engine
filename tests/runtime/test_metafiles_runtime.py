"""F31 s3 — ``file`` lines at run time (F31 ``06-acceptance.md`` AC-F31-11, 12, 13, 15, 16;
``04`` §4.2, §5.4, §6.6, §6.7, §8), Run H on ``walk/``, ``caps/``, and ``reads/``
(``metafiles_story.py``), and the step 3 headless golden (06 §9 Step 3 milestone).

AC-F31-12 names F14's ``RuntimeStoryDriver`` (app); this runtime-lane test drives the
interpreter the driver drives (``Advance``, ``StepBack``, ``StepForward``: skip and auto post
the same ``Advance`` events), and F20's jump and F44's play-from-here as F03's restore seam
(06 G7)."""

import builtins
import logging
import os
import shutil
import threading

import pytest

from engine.core.constants import META_CHANGES_MAX
from engine.runtime import headless as headless_mod
from engine.runtime.commands import Command, MetaDelete, MetaWrite, Say, StepBack, StoryEnded
from engine.runtime.headless import HeadlessInputError
from engine.runtime.interpreter import RestoreResult
from engine.runtime.metafiles import MemoryFolder, MetaFiles, decode_note
from engine.runtime.state import STATE_FORMAT, GameState
from engine.script.messages import format_message
from tests.runtime import metafiles_story as story
from tests.runtime.effects_story import load_game, story_game, take_all
from tests.runtime.metafiles_story import GOLDEN, HANA, fixture, run_h, spy, started
from tests.runtime.rollback_story import back, forward, shown_text, step

NOTE = "Line one\nNoteMark7 {b}x{/b} {{"
WORDS = ("W0", "W1", "W2", "W3", "W4", "W5")


def _texts(commands: list[Command]) -> list[str]:
    return ["".join(p.text for p in c.body.pieces) for c in commands if type(c) is Say]


def _between(commands: list[Command], first: str, last: str) -> list[Command]:
    """The commands after the ``Say`` starting ``first`` up to the one starting ``last``."""
    says = {c.text.split(" ")[0]: i for i, c in enumerate(commands) if type(c) is Say}
    return commands[says[first] + 1:says[last]]


def _meta(commands: list[Command]) -> list[Command]:
    return [c for c in commands if type(c) in (MetaWrite, MetaDelete)]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


class _OsRecorder:
    """TR-F31-03's recorder, reduced to the question "any path call at all?": ``open``,
    ``os.open``, ``stat``, ``lstat``, listings, and changes made on this thread."""

    NAMES = ("open", "stat", "lstat", "listdir", "scandir", "replace", "remove", "unlink",
             "mkdir", "rename", "rmdir")

    def __init__(self, monkeypatch) -> None:
        self.calls: list[str] = []
        me = threading.get_ident()

        def wrap(real, name):
            def spy_call(*args, **kwargs):
                if threading.get_ident() == me:
                    self.calls.append(name)
                return real(*args, **kwargs)
            return spy_call
        for name in self.NAMES:
            monkeypatch.setattr(os, name, wrap(getattr(os, name), "os." + name))
        monkeypatch.setattr(os.path, "realpath", wrap(os.path.realpath, "realpath"))
        monkeypatch.setattr(builtins, "open", wrap(builtins.open, "open"))


def test_ac_f31_11_a_headless_run_writes_deletes_and_reacts(monkeypatch, caplog):
    program = fixture("walk")
    folder = spy(originals={"hana.chr": HANA})
    recorder = _OsRecorder(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        commands = run_h(program, files=folder)
    monkeypatch.undo()
    assert recorder.calls == []                                       # no os call
    assert story.golden_text() == GOLDEN.read_text("ascii")
    assert _texts(commands) == ["W0", "W1 True", f"W2 {NOTE.replace(chr(10), ' ')}", "W3 False",
                                "W4 other None", "W5 gone"]
    assert _meta(_between(commands, "W0", "W1")) == [MetaWrite("hana.chr"),
                                                      MetaWrite("read_me.txt")]
    assert _meta(_between(commands, "W2", "W3")) == [MetaDelete("hana.chr"),
                                                      MetaDelete("gone.chr")]
    assert len(_meta(commands)) == 4 and type(commands[-1]) is StoryEnded
    assert folder.entries == {"read_me.txt": NOTE.encode("utf-8")}
    assert _warnings(caplog) == []

    yes = run_h(program, files=spy(entries={"answer.txt": b"yes"}))
    assert _texts(yes)[4] == "W4 yes"

    bare = MemoryFolder()                                             # no original: b"" (D5)
    interp = started(program, bare)
    step(interp)                                                      # W0 → W1
    assert shown_text(interp).startswith("W1") and bare.entries["hana.chr"] == b""
    assert _texts(take_all(interp))[-1] == "W1 True"

    # Each run without files= gets a fresh, empty folder.
    attached: list[tuple[MetaFiles, dict]] = []
    real_attach = headless_mod.attach

    def record(interp, files):
        attached.append((files, dict(files.port.entries)))
        real_attach(interp, files)
    monkeypatch.setattr(headless_mod, "attach", record)
    assert _texts(run_h(program)) == _texts(run_h(program))
    (one, before_one), (two, before_two) = attached
    assert one.port is not two.port and before_one == before_two == {}


def test_ac_f31_12_once_only_walls_reruns_saves(tmp_path):
    program = fixture("walk")

    # A change sets the wall: back at W1 and at W3 is refused.
    folder = spy()
    interp = started(program, folder)
    step(interp)
    refused = interp.timeline.refused
    back(interp)
    assert shown_text(interp).startswith("W1") and interp.timeline.refused == refused + 1
    step(interp)
    step(interp)
    back(interp)
    assert shown_text(interp).startswith("W3") and interp.timeline.refused == refused + 2

    # At W2, back to W1, then forward: the chain reads again and changes nothing.
    folder = spy()
    interp = started(program, folder)
    step(interp)
    step(interp)
    w2 = interp.checkpoint()
    back(interp)
    assert shown_text(interp).startswith("W1")
    folder.calls.clear()
    forward(interp)
    assert shown_text(interp).startswith("W2") and interp.checkpoint() == w2
    assert folder.calls == [("read", "read_me.txt")]

    # At W5 gone, the player restores hana.chr; back to W4, forward: a check re-reads.
    folder = spy()
    interp = started(program, folder)
    for _ in range(5):
        step(interp)
    take_all(interp)
    assert shown_text(interp) == "W5 gone"
    folder.player_restores("hana.chr")
    back(interp)
    assert shown_text(interp).startswith("W4")
    assert _texts(forward(interp)) == ["W5 back"]

    # Skip and auto (every line advanced at once), with back and forward tried at every
    # line: each write and delete runs exactly once, in order.
    folder = spy()
    inputs = ["back", "forward", "advance"] * 6
    run_h(program, files=folder, inputs=inputs)
    assert folder.changes() == [("write", "hana.chr"), ("write", "read_me.txt"),
                                ("delete", "hana.chr"), ("delete", "gone.chr")]

    # Save at W2, play to the end, load the W2 save: no port call at the load; playing on
    # deletes again.
    folder = spy()
    interp = started(program, folder)
    step(interp)
    step(interp)
    saved = GameState.from_json(interp.checkpoint().to_json())
    while interp.status.name == "WAITING":
        step(interp)
    loader = spy()
    fresh = started(program, loader)
    loader.calls.clear()
    assert fresh.restore(saved).result is RestoreResult.OK
    assert loader.calls == []
    while fresh.status.name == "WAITING":
        step(fresh)
    assert loader.changes() == [("delete", "hana.chr"), ("delete", "gone.chr")]

    # An F20 jump and an F44 play-from-here landing at W4 (F03's restore seam): no port call.
    interp = started(program, spy())
    for _ in range(4):
        step(interp)
    w4 = interp.checkpoint()
    for kwargs in ({"fresh_menu": True}, {"use_hints": True}):
        jumper = spy()
        fresh = started(program, jumper)
        jumper.calls.clear()
        assert fresh.restore(w4, **kwargs).result is RestoreResult.OK
        assert jumper.calls == [] and shown_text(fresh).startswith("W4")

    # The W2 save's state: plain values, no new key, the format unchanged.
    data = saved.to_json()
    assert saved.variables["hana_here"] is True and saved.variables["answer"] == NOTE
    first = started(program, spy()).checkpoint().to_json()
    assert set(data) == set(first) and STATE_FORMAT == 1
    assert not any("file" in key or "meta" in key for key in data)

    # The 257th change (capped) still sets the wall, and calls no port.
    capped = story_game(tmp_path / "capped", ['"A"', 'file write "a.txt" "x"', '"B"'])
    folder = spy()
    interp = started(capped, folder)
    interp.files.changes = META_CHANGES_MAX
    step(interp)
    refused = interp.timeline.refused
    back(interp)
    assert shown_text(interp) == "B" and interp.timeline.refused == refused + 1
    assert folder.changes() == []


def _caps(root, n: int):
    """``caps/`` with ``n`` changes (06 §5: 300; ``slow``: 10,000)."""
    shutil.copytree(story.F31 / "caps", root)
    main = root / "script" / "main.vns"
    main.write_text(main.read_text("utf-8").replace("default n = 300", f"default n = {n}"),
                    "utf-8")
    return load_game(root)


@pytest.mark.parametrize("n", [300, pytest.param(10_000, marks=pytest.mark.slow)])
def test_ac_f31_13_session_caps_and_run_warnings(n, caplog, tmp_path):
    program = fixture("caps") if n == 300 else _caps(tmp_path / "caps", n)
    folder = spy()
    with caplog.at_level(logging.WARNING, logger="vn"):
        commands = run_h(program, files=folder)
    assert len(folder.changes()) == META_CHANGES_MAX
    assert type(commands[-1]) is StoryEnded and _texts(commands)[-1] == "End"
    assert _warnings(caplog) == [_warning("W199", (), "caps", 9)]
    assert folder.entries == {"a.txt": b"x"}                         # the capped delete did nothing

    caplog.clear()
    folder = spy(entries={"answer.txt": b"a" * 16_385, "other.txt": b"\xff"})
    with caplog.at_level(logging.WARNING, logger="vn"):
        commands = run_h(fixture("reads"), files=folder)
    assert type(commands[-1]) is StoryEnded
    assert folder.calls.count(("read", "answer.txt")) == 3 == folder.calls.count(("read", "other.txt"))
    assert _warnings(caplog) == [_warning("W200", ("large", "answer.txt"), "reads", 9),
                                 _warning("W200", ("utf8", "other.txt"), "reads", 10)]
    for text in _warnings(caplog):
        assert "aiko" not in text and ":\\" not in text and not text.count("/") > 1


def _warning(code: str, args: tuple, game: str, line: int) -> str:
    from engine.script.diagnostics import ScriptWarning
    return ScriptWarning(format_message(code, args), code=code, file="script/main.vns",
                         line=line).format()


def test_ac_f31_15_a_note_is_inert(caplog):
    note = "NoteMark7 {b}x{/b} {{ } [x] {var=hana_here} {answer} {w}"
    folder = spy(entries={"answer.txt": note.encode("utf-8")})
    with caplog.at_level(logging.DEBUG):
        commands = run_h(files=folder)
    (w4,) = [c for c in commands if type(c) is Say and c.text.startswith("W4")]
    assert [p.text for p in w4.body.pieces] == ["W4 other " + note]
    assert w4.body.pieces[0].style.bold is False
    for c in commands:
        if type(c) is Say and not c.text.startswith("W4"):
            assert "NoteMark7" not in repr(c) or c.text.startswith("W2")
        elif type(c) is not Say:
            assert "NoteMark7" not in repr(c), type(c).__name__
    assert not [r for r in caplog.records if "NoteMark7" in r.getMessage()]
    assert decode_note(note.encode("utf-8")) == note


def test_ac_f31_16_headless_player_inputs():
    program = fixture("walk")
    adv = ["advance"] * 4
    # player restores at W4: W5 back; the input counts but doesn't advance.
    assert _texts(run_h(program, files=spy(), inputs=adv + ["player restores hana.chr"]))[-1] \
        == "W5 back"
    # player deletes at W2: read_me.txt is gone.
    folder = spy()
    run_h(program, files=folder, inputs=["advance", "advance", "player deletes read_me.txt"])
    assert "read_me.txt" not in folder.entries
    # player restores with no original: stored as b"".
    folder = MemoryFolder()
    run_h(program, files=folder, inputs=adv + ["player restores hana.chr"])
    assert folder.entries["hana.chr"] == b""
    # A name no file line uses, or not a name: HeadlessInputError (H-input).
    for text, args in (("player deletes other.chr", (2, "player deletes other.chr", "meta_name")),
                       ("player deletes ../x", (2, "player deletes ../x"))):
        with pytest.raises(HeadlessInputError) as caught:
            run_h(program, files=spy(), inputs=["advance", text])
        assert str(caught.value) == format_message("H-input", args)
