"""F28 step 2: the ``effect`` statement and ``with glitch`` at load (``06-acceptance.md``
AC-F28-05, AC-F28-08's node rows; the Studio rows of ``07`` I-16). AC-F28-06, 07, and 08's
messages are rows of ``tests/fixtures/F02/messages/cases.toml`` (``test_messages.py``).

``effect`` registers at import since F28 s3 (with its executor); the ``effect_word`` fixture
registers it again inside ``scoped_registry()``, which changes nothing (F19 07 I-5)."""

from types import SimpleNamespace

import pytest

import engine.script  # noqa: F401  registers every statement and the docs table
from engine.runtime.interpreter import CHECKPOINT_TYPES, EXECUTORS
from engine.runtime.transitions import BUILTIN_TRANSITIONS, spec_for
from engine.script import glitch
from engine.script.audio_checks import VOICE_TRANSPARENT
from engine.script.effects import BUILTIN_TRANSITION_NAMES
from engine.script.glitch import EFFECT_STATEMENT_KINDS, Effect
from engine.script.statement_docs import docs_for
from engine.script.statements import get_spec, scoped_registry
from engine.tools import check
from engine.tools.editor.assist import candidates, completion_context, slot_words
from tests.script.helpers import parse_text, template_f28
from tests.tools.test_statement_examples import problems_of


@pytest.fixture
def effect_word():
    with scoped_registry():
        glitch.register_words()
        glitch.register_words()                     # a second call does nothing
        yield


def _node(S: str):
    parsed = parse_text(template_f28(S=S))
    assert parsed.codes == [], (S, parsed.codes)
    return parsed.nodes[1].block[2]


# --- AC-F28-05 ---------------------------------------------------------------------------

def test_ac_f28_05_effect_parses(effect_word):
    rows = [
        # S, (kind, tag, size, action, seconds)
        ("effect tear", ("tear", None, None, "burst", None)),
        ("effect tear large 0.3", ("tear", None, "large", "burst", 0.3)),
        ("effect tear 0.3 large", ("tear", None, "large", "burst", 0.3)),
        ("effect tear 0.1", ("tear", None, None, "burst", 0.1)),
        ("effect tear 30", ("tear", None, None, "burst", 30.0)),
        ("effect static small on", ("static", None, "small", "on", None)),
        ("effect static on small", ("static", None, "small", "on", None)),
        ("effect colorshift on", ("colorshift", None, None, "on", None)),
        ("effect colorshift off", ("colorshift", None, None, "off", None)),
        ("effect jitter hana 1.0", ("jitter", "hana", None, "burst", 1.0)),
        ("effect jitter hana large on", ("jitter", "hana", "large", "on", None)),
        ("effect jitter hana off", ("jitter", "hana", None, "off", None)),
        ("effect jitter 紙", ("jitter", "紙", None, "burst", None)),
        ("effect off", (None, None, None, "burst", None)),
    ]
    for S, want in rows:
        node = _node(S)
        assert type(node) is Effect, S
        assert (node.kind, node.tag, node.size, node.action, node.seconds) == want, S
        assert node.identity_key() == ("effect",)
    assert tuple(EFFECT_STATEMENT_KINDS)[:4] == ("tear", "colorshift", "static", "jitter")
    assert Effect not in CHECKPOINT_TYPES
    assert Effect in VOICE_TRANSPARENT                                      # SR-F28-04
    assert get_spec("effect") is glitch.SPEC and get_spec("effect").placement == "story"


def test_effect_registers_with_its_executor():
    """F19 07 I-5: F28 s3 registers ``effect`` at import, with its executor (no more E32)."""
    assert get_spec("effect") is glitch.SPEC and Effect in EXECUTORS
    assert parse_text(template_f28(S="effect tear")).codes == []


# --- AC-F28-08 (node rows; the E192, E194, E198 rows are cases.toml's) ----------------------

def test_ac_f28_08_with_glitch_is_a_built_in_name(effect_word):
    assert BUILTIN_TRANSITION_NAMES[-1] == "glitch" and "glitch" in BUILTIN_TRANSITIONS
    interp = SimpleNamespace(transition_specs={}, G={}, program=None)
    rows = [
        # S, clause seconds, spec seconds (None: [effects] glitch, resolved by the presentation)
        ("scene bg sea with glitch", None, None),
        ("show hana sad with glitch 0.8", 0.8, 0.8),
        ("show hana sad with glitch 30", 30.0, 30.0),
    ]
    for n, (S, seconds, spec_seconds) in enumerate(rows):
        clause = _node(S).with_clause
        assert (clause.name, clause.seconds, clause.color) == ("glitch", seconds, None), S
        spec = spec_for(interp, clause, f"s{n}")
        assert (spec.kind, spec.name, spec.seconds, spec.color) == (
            "glitch", "glitch", spec_seconds, None), S
    zero = _node("show hana sad with glitch 0").with_clause
    assert zero.seconds == 0 and spec_for(interp, zero, "z") is None      # a cut, as dissolve 0


# --- Studio (07 I-16) -----------------------------------------------------------------------

def _complete(line: str, names: dict) -> list[str]:
    ctx = completion_context(line, len(line))
    return [] if ctx is None else [c.text for c in candidates(ctx, names)]


def test_studio_effect_docs_and_completion(effect_word, tmp_path):
    docs = docs_for("effect")
    assert [d.names for d in docs] == [("glitch",), (), ("glitch",), ("glitch",)]   # F30 s6
    assert slot_words(docs) == {"jitter": ("sprite",)}
    for n, doc in enumerate(docs):
        assert problems_of(tmp_path / str(n), doc) == [], doc.syntax
    no_game = SimpleNamespace(program=None, namespace=None)
    names = {"glitch": check.NAME_SOURCES["glitch"](no_game),
             "sprite": [("hana", None, None), ("daichi", None, None)],
             "transition": check.NAME_SOURCES["transition"](no_game)}
    assert [row[0] for row in names["glitch"]] == ["tear", "colorshift", "static", "jitter",
                                                   "window_title", "crash", "off"]
    assert _complete("    effect co", names) == ["colorshift"]
    assert _complete("    effect jitter h", names) == ["hana"]
    assert _complete("    show hana happy with gl", names) == ["glitch"]
    assert check.NAME_SOURCES["sprite"](no_game) is None                  # no program
