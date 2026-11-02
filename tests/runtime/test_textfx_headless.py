"""F29 step 2 — a headless run of Template T and T′: bodies, history, nothing else saved
(``06-acceptance.md`` AC-F29-06; ``04-technical.md`` §6.4, §9 item 7).

Template T is ``tests/fixtures/F29/template`` (06 §0.3); T′ is T with every effect tag
removed by one regex. Both run as Run R (seed 42, advancing at every line) on an
``Interpreter``, so each line's checkpoint and the history can be read. A line's sid hashes
its text (ADR-0006), so T's and T′'s sids differ: they are compared by line number.
"""

import dataclasses
import re
import shutil
from pathlib import Path

from engine.runtime.commands import Say, Span, Style
from engine.runtime.interpreter import Status
from engine.script.loader import load_story
from engine.script.texttags import TextEffect
from tests.runtime.menu_story import ALL, launched, step
from tests.runtime.story import end_waits

TEMPLATE_T = Path(__file__).resolve().parents[1] / "fixtures" / "F29" / "template"
FX_TAG = re.compile(r"\{/?(?:shake|wave|glitch)(?:=[a-z]*)?\}")

# Each line's effects (06 §0.3 notation), and L7, L12's whole bodies.
EFFECTS = {4: {"wave:medium"}, 5: {"shake:small"}, 6: {"glitch:large"}, 7: {"glitch:medium"},
           9: {"wave:large"}, 10: {"shake:medium"}, 11: {"shake:medium"},
           12: {"glitch:medium"}, 14: {"shake:large"}, 15: set()}
GLITCH = Style(effect=TextEffect("glitch"))
BODIES = {7: (Span("My name is ", Style()), Span("Hana", GLITCH), Span(".", Style())),
          12: (Span("It was... ", GLITCH), Span("GONE.", Style(speed=0.0)))}
HISTORY = ["I'm so happy you came today!", "I just... don't want you to leave.",
           "You're not going anywhere.", "My name is Hana.", "The river was quiet.",
           "Did you hear that?", "Did you hear that?", "It was... GONE.", "It was... GONE.",
           "End."]


def _game(root: Path, *, plain: bool) -> Path:
    shutil.copytree(TEMPLATE_T, root)
    if plain:
        main = root / "script" / "main.vns"
        main.write_text(FX_TAG.sub("", main.read_text(encoding="utf-8")), encoding="utf-8",
                        newline="\n")
    return root


def _run(root: Path):
    """Run R: every command, the checkpoint at each line, and the line number of each sid."""
    from engine.core.paths import GamePaths

    result = load_story(GamePaths(root.resolve()))
    assert not result.errors and result.program is not None
    program = result.program
    lines = {s.sid: f"L{s.line}" for s in program.iter_statements()}
    interp = launched(program)
    interp.new_game(42)
    commands, states = [], []
    while True:
        interp.run(10_000)
        end_waits(interp)
        commands.extend(interp.take_commands(ALL))
        if interp.status is not Status.WAITING:
            break
        states.append(interp.checkpoint())
        step(interp, None)
    return commands, states, lines, interp


def _norm(value, lines: dict[str, str]):
    """A command as plain data: sids as line numbers, written text without effect tags, and
    every style's effect dropped (so T's equals T′'s when only styles differ)."""
    if isinstance(value, Style):
        value = dataclasses.replace(value, effect=None)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return (type(value).__name__,
                tuple(_norm(getattr(value, f.name), lines) for f in dataclasses.fields(value)))
    if isinstance(value, str):
        return lines.get(value, FX_TAG.sub("", value))
    if isinstance(value, (tuple, list)):
        out: list = []
        for item in (_norm(v, lines) for v in value):
            # Neighbouring spans whose styles are equal once effects are dropped merge, as
            # the parser merges T′'s.
            if out and _is_span(item) and _is_span(out[-1]) and out[-1][1][1] == item[1][1]:
                out[-1] = ("Span", (out[-1][1][0] + item[1][0], item[1][1]))
            else:
                out.append(item)
        return tuple(out)
    if isinstance(value, dict):
        return tuple(sorted((_norm(k, lines), _norm(v, lines)) for k, v in value.items()))
    return value


def _is_span(item) -> bool:
    return isinstance(item, tuple) and len(item) == 2 and item[0] == "Span"


def _json(value, lines: dict[str, str], effects: list[str]):
    """Checkpoint JSON with sids as line numbers; each span's ``"effect"`` is taken out
    into ``effects``, and neighbouring spans that are then alike merge (as T′'s are)."""
    if isinstance(value, dict):
        if "effect" in value and "text" in value:
            effects.append(value["effect"])
            value = {k: v for k, v in value.items() if k != "effect"}
        return {lines.get(k, k): _json(v, lines, effects) for k, v in value.items()}
    if isinstance(value, list):
        out: list = []
        for item in (_json(v, lines, effects) for v in value):
            if (out and isinstance(item, dict) and isinstance(out[-1], dict) and "text" in item
                    and "text" in out[-1]
                    and {**out[-1], "text": ""} == {**item, "text": ""}):
                out[-1] = {**out[-1], "text": out[-1]["text"] + item["text"]}
            else:
                out.append(item)
        return out
    if isinstance(value, str):
        return lines.get(value, value)
    return value


def _effects(body) -> set[str]:
    return {p.style.effect.key() for p in body.pieces
            if isinstance(p, Span) and p.style.effect is not None}


def test_ac_f29_06_headless_run_bodies_history_nothing_else_saved(tmp_path):
    t_cmds, t_states, t_lines, t_interp = _run(_game(tmp_path / "t", plain=False))
    p_cmds, p_states, p_lines, p_interp = _run(_game(tmp_path / "p", plain=True))

    # Bodies: each line's effects; with every effect set to None, T′'s bodies.
    t_says = [c for c in t_cmds if type(c) is Say]
    p_says = [c for c in p_cmds if type(c) is Say]
    by_line = {int(t_lines[s.sid][1:]): s for s in t_says}
    assert {n: _effects(s.body) for n, s in by_line.items()} == EFFECTS
    for n, pieces in BODIES.items():
        assert by_line[n].body.pieces == pieces
    assert [_norm(s.body, t_lines) for s in t_says] == [_norm(s.body, p_lines) for s in p_says]
    assert all(not _effects(s.body) for s in p_says)

    # The command lists are equal apart from body styles (and the written text's tags).
    assert [_norm(c, t_lines) for c in t_cmds] == [_norm(c, p_lines) for c in p_cmds]

    # Every checkpoint equals T′'s but for the NVL page spans' "effect" keys (L9–L12); the
    # story RNG state is part of the checkpoint, so it is equal too.
    assert len(t_states) == len(p_states) == 10          # L4–L7, L9–L12, L14, L15
    seen: list[str] = []
    for t_state, p_state in zip(t_states, p_states):
        effects: list[str] = []
        assert _json(t_state.to_json(), t_lines, effects) == _json(p_state.to_json(), p_lines,
                                                                   [])
        assert set(effects) <= {"wave:large", "shake:medium", "glitch:medium"}
        seen += effects
        assert t_state.dice == p_state.dice                  # the story RNG (PCG32)
    assert {"wave:large", "shake:medium", "glitch:medium"} == set(seen)
    nvl_pages = [s.nvl.page for s in t_states]
    for page in nvl_pages:                               # only L9–L12 rows carry an effect
        for line in page:
            has = any(span.style.effect is not None for span in line.spans)
            assert has == (t_lines[line.sid] in ("L9", "L10", "L11", "L12"))
    assert t_interp.persistent.value_count == p_interp.persistent.value_count == 1  # F32's
    assert t_interp.persistent.peek("playthrough") == 0               # built-in only

    # History: the plain texts, equal in both runs.
    t_hist = [e.text for e in t_interp.checkpoint().history.entries]
    assert t_hist == [e.text for e in p_interp.checkpoint().history.entries] == HISTORY
