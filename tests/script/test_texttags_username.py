"""F30 step 2: ``{username}`` reaches the runtime only as the fallback word
(``06-acceptance.md`` AC-F30-11, AC-F30-12; ``04`` §4.1, §5.4).

Run H's rows: template W (``tests/fixtures/F30/template``) loaded with ``LoadOptions`` and run
headless. AC-F30-12's crash row (E170 at ``effect crash``) came with F30 s3's executor."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from engine.core.paths import GamePaths
from engine.render.textlayout import LineLayout
from engine.runtime.commands import Say, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.text import format_value, resolve_tagged
from engine.script.flowgraph import plain_title
from engine.script.loader import LoadOptions, load_story
from engine.script.texttags import BASE_STYLE, NameMark, Span, TaggedText
from tests.fakes.fixed_font import m20_context
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)
from tests.runtime.story import launched
from tests.script.helpers import template_f30

IMAGES = ("images/bg/room.png",)
FLAG = replace(BASE_STYLE, username=True)


def _program(root, *, S=None, replace_lines=None, fallback=None):
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    (script / "main.vns").write_text(template_f30(S=S, replace=replace_lines), encoding="utf-8")
    options = LoadOptions() if fallback is None else LoadOptions(username_fallback=fallback)
    result = load_story(GamePaths(root.resolve()), options)
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def _says(program):
    commands = run_headless(program, seed=42, image_files=IMAGES)
    failed = [c.error for c in commands if type(c) is StoryFailed]
    return [c for c in commands if type(c) is Say], failed


def test_ac_f30_11_the_runtime_sees_only_the_fallback(tmp_path):
    says, failed = _says(_program(tmp_path / "w"))
    assert not failed
    l7 = says[1].body
    assert l7.pieces == (Span("I know who you are, ", BASE_STYLE), Span("friend", FLAG),
                         Span(".", BASE_STYLE))
    assert l7.plain() == (Span("I know who you are, friend.", BASE_STYLE),)
    assert l7.plain(names=True) == l7.pieces
    assert "".join(s.text for s in l7.plain()) == "".join(s.text for s in l7.plain(names=True))
    pal, _ = _says(_program(tmp_path / "pal", fallback="pal"))
    assert pal[1].body.pieces[1] == Span("pal", FLAG)

    # Only {username}, twice: no early return, never merged, kept when empty.
    interp = SimpleNamespace(program=SimpleNamespace(username_fallback="friend"), G={})
    twice = TaggedText((NameMark(None, BASE_STYLE), NameMark(None, BASE_STYLE)))
    assert resolve_tagged(interp, twice, restoring=False, owner=None).pieces == (
        Span("friend", FLAG), Span("friend", FLAG))
    interp.program.username_fallback = ""
    assert resolve_tagged(interp, twice, restoring=False, owner=None).pieces == (
        Span("", FLAG), Span("", FLAG))

    assert plain_title(TaggedText((Span("Hi ", BASE_STYLE), NameMark(None, BASE_STYLE)))) == (
        "Hi ", None)                                                    # the flowchart_var word
    with pytest.raises(AssertionError):
        LineLayout(TaggedText((NameMark(None, BASE_STYLE),)), m20_context())

    # No identity reaches the story's names; {var=username} is F05's E170.
    G = launched(_program(tmp_path / "g")).G
    assert not {"username", "login", "getuser"} & set(G)
    _, failed = _says(_program(tmp_path / "v", S='"{var=username}"'))
    assert [e.code for e in failed] == ["E170"]


def test_ac_f30_12_username_takes_a_variable(tmp_path):
    lines = {7: '    hana "Hi {username=v}."'}
    rows = [('"Mika"', "Mika"), ("5", 5), ('"a\\u202eb"', "a‮b"),
            ('"' + "a" * 300 + '"', "a" * 300)]
    for n, (written, value) in enumerate(rows):
        says, failed = _says(_program(tmp_path / str(n), S=f"$ v = {written}",
                                      replace_lines=lines))
        assert not failed, written
        shown = format_value(value)                             # what {var=v} shows
        assert says[1].body.pieces[1] == Span(shown, FLAG), written
    _, failed = _says(_program(tmp_path / "del", S="$ del v", replace_lines=lines))
    assert [e.code for e in failed] == ["E170"]
    # The value is taken as the line starts.
    says, _ = _says(_program(tmp_path / "ren", S='$ v = "Mika"', replace_lines={
        **lines, 8: '    $ v = "Ren"', 9: '    "Bye {username=v}."'}))
    assert [s.body.pieces[1].text for s in says[1:]] == ["Mika", "Ren"]
    # F30 s3: in a crash message, E170 at the crash statement (line 6).
    _, failed = _says(_program(tmp_path / "crash", S='effect crash "{username=nope}"'))
    assert [(e.code, e.line) for e in failed] == [("E170", 6)]
