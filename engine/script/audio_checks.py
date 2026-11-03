"""The load checks of the audio statements that look past one line (F08 ``04-technical.md``
§6.2; ``02-script.md`` SR-F08-02, SR-F08-19; W20, W23, W24).

Why this module exists: a ``voice`` voices the line below it, and only the whole block tells
which line that is. ``iter_attach_voices`` runs once in the whole-game checks (phase G, before
identities): for each ``Voice`` it finds the next statement in the same block that isn't
``VOICE_TRANSPARENT``; a ``Say`` there gets ``Say.voice = file``, anything else (another
``voice``, an ``if``, ``jump``, ``call``, ``return``, F07's ``menu``, or the block's end) is
W20 and the voice never plays. The same pass gives W23 for each file the engine can't play
(the statement stays and plays as silence) and one W24 summary for looping MP3s.

F07 (its ``04-technical.md`` §3.2): a ``voice`` directly above a menu's question is the
menu's own (``Menu.voice``) and voices the question (``question.voice``); with no question
it is W20's first form. A ``voice`` above ``menu:`` stays W20's ``menu`` form (``Menu`` is
not ``VOICE_TRANSPARENT``, F08 Q3). Choice blocks are walked like ``if`` branches.

W20 and W23 are line records in reading order, at most ``SCRIPT_AUDIO_WARN_LIMIT`` of them,
then one W20s line. The walk is iterative and yields every ``IDENTITY_YIELD_ITEMS``
statements. The launch half of ``audio_checks`` (``AudioFileCheck``: W21, W22, W25) comes
with F08 step 8.
"""

from collections.abc import Generator, Iterable, Iterator

from engine.script.audio import (
    PLAYABLE_EXTS,
    PlayAudio,
    QueueMusic,
    StopAudio,
    Voice,
    suffix,
)
from engine.script.codex import CodexLock
from engine.script.diagnostics import ScriptWarning
from engine.script.effects import Flash, Pause, Shake
from engine.script.fourthwall import CrashEffect, TitleEffect
from engine.script.glitch import Effect
from engine.script.limits import IDENTITY_YIELD_ITEMS, SCRIPT_AUDIO_WARN_LIMIT
from engine.script.messages import format_message
from engine.script.menu import Menu
from engine.script.metafiles import MetaFile
from engine.script.nodes import If, Label, Node, PythonLine, Say, Statement
from engine.script.nvl import Nvl
from engine.script.points import PointsChange
from engine.script.rollback import Rollback
from engine.script.routes import Lock
from engine.script.stage import Hide, Scene, Show

# The statements a voice looks past to find its line (07 I-12): ``$`` lines, the audio
# statements, and F04's stage statements. Comments are no statements. Later features name
# their statements here in their own specs (F09 C10: shake, flash, pause; F22 I-3: points;
# F14 04 §2: rollback; F17 04 §3: nvl; F19: lock/unlock; F21 04 §3: codex lock/unlock;
# F28 SR-F28-04: effect; F30 04 §5.3: effect window_title, effect crash; F31 04 §2.2: file).
VOICE_TRANSPARENT: frozenset[type[Statement]] = frozenset(
    (PythonLine, PlayAudio, QueueMusic, StopAudio, Scene, Show, Hide, Shake, Flash, Pause,
     PointsChange, Rollback, Nvl, Lock, CodexLock, Effect, TitleEffect, CrashEffect,
     MetaFile))

_FILE_NODES = (PlayAudio, QueueMusic, StopAudio, Voice)


def _blocks(nodes: Iterable[Node]) -> Iterator[tuple[Statement, ...]]:
    """Every block of every label: the label's own, then the blocks nested in its
    statements (``blocks()``: ``if`` branches, F07 menu choices; any order, the records are
    sorted). No recursion."""
    for node in nodes:
        if not isinstance(node, Label):
            continue
        stack = [node.block]
        while stack:
            block = stack.pop()
            yield block
            for stmt in block:
                stack.extend(stmt.blocks())


def _w20_form(stmt: Statement | None) -> str:
    """The W20 form for what follows a voice: another voice, an ``if``, a ``menu`` (F07's
    node, by its class name), or anything else."""
    if isinstance(stmt, Voice):
        return "voice"
    if isinstance(stmt, If):
        return "if"
    if stmt is not None and type(stmt).__name__ == "Menu":
        return "menu"
    return "none"


def _line_of(block: tuple[Statement, ...], index: int) -> Statement | None:
    """The first statement after ``block[index]`` that isn't voice-transparent."""
    for stmt in block[index + 1:]:
        if type(stmt) not in VOICE_TRANSPARENT:
            return stmt
    return None


def iter_attach_voices(nodes: Iterable[Node]) -> Generator[None, None, list[ScriptWarning]]:
    """Attach each voice to its line (``Say.voice``) and return the W20, W23 (with the W20s
    summary) and W24 warnings, in that order (module docstring)."""
    records: list[tuple[int, int, int, str, tuple, str]] = []
    mp3: dict[str, tuple[int, int]] = {}
    count = 0
    for block in _blocks(nodes):
        for index, stmt in enumerate(block):
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
            if isinstance(stmt, Menu):
                voice = stmt.voice                          # F07: the question's voice
                if voice is None:
                    continue
                if stmt.question is not None:
                    stmt.question.voice = voice.audio_file
                else:
                    records.append((voice.file.order, voice.line, len(records), "W20",
                                    ("none",), voice.file.ref))
                stmt = voice
            elif not isinstance(stmt, _FILE_NODES):
                continue
            file = stmt.audio_file
            order = stmt.file.order
            if file is not None:
                ext = suffix(file)
                if ext not in PLAYABLE_EXTS:
                    records.append((order, stmt.line, len(records), "W23", (file, ext),
                                    stmt.file.ref))
                elif ext == ".mp3" and isinstance(stmt, (PlayAudio, QueueMusic)) and stmt.loop:
                    first = mp3.get(file)
                    if first is None or (order, stmt.line) < first:
                        mp3[file] = (order, stmt.line)
            if isinstance(stmt, Voice) and stmt is block[index]:
                line = _line_of(block, index)
                if isinstance(line, Say):
                    line.voice = file
                else:
                    records.append((order, stmt.line, len(records), "W20",
                                    (_w20_form(line),), stmt.file.ref))
    records.sort()
    cap = SCRIPT_AUDIO_WARN_LIMIT
    warnings = [ScriptWarning(format_message(code, args), code=code, file=ref, line=line)
                for _, line, _, code, args, ref in records[:cap]]
    if len(records) > cap:
        warnings.append(ScriptWarning(format_message("W20s", (f"{len(records) - cap:,}",)),
                                      code="W20s"))
    if mp3:
        files = sorted(mp3, key=lambda name: mp3[name])
        warnings.append(ScriptWarning(format_message("W24", (tuple(files[:2]), len(files))),
                                      code="W24"))
    return warnings


def attach_voices(nodes: Iterable[Node]) -> list[ScriptWarning]:
    """``iter_attach_voices`` run to the end in one go."""
    job = iter_attach_voices(nodes)
    while True:
        try:
            next(job)
        except StopIteration as stop:
            return stop.value


__all__ = ["VOICE_TRANSPARENT", "attach_voices", "iter_attach_voices"]
