"""The ``.vnsave`` format and its encoder (F11 ``04`` §4, §7.2, §7.3, §7.5): AC-F11-01 (names
and the three lines), AC-F11-02 (every engine-written save reads back; TR-F11-01), AC-F11-05
(too large, the encoder rows), AC-F11-06 (description), AC-F11-07 (slot status), and
SEC-F11-04 (every file the engine writes passes its own reader)."""

import json
import random
import re
from types import MappingProxyType, SimpleNamespace

import pytest

from engine.persist import limits, saves
from engine.persist.saves import SLOT_NAME_RE, SaveEncoder, SlotId, SlotStatus, TooLarge
from engine.runtime import limits as runtime_limits
from engine.runtime.state import GameState
from tests.persist import save_support as ss
from tests.persist.helpers import STRING_PARTS

META_KEYS = ["vnsave", "game", "seq", "saved_at", "description", "chapter", "game_version",
             "state_format", "thumb", "state"]


# --- AC-F11-01: names and the three lines ------------------------------------------------------

@pytest.mark.parametrize("slot, name", [
    (SlotId("auto", 2), "auto-2.vnsave"), (SlotId("quick", 1), "quick-1.vnsave"),
    (SlotId(3, 6), "page3-6.vnsave"), (SlotId(100, 6), "page100-6.vnsave"),
])
def test_file_names(slot, name):
    assert slot.file_name() == name
    assert SLOT_NAME_RE.fullmatch(name)
    assert SlotId.from_name(name) == slot


@pytest.mark.parametrize("page, n", [("auto", 7), (0, 1), (101, 1), ("Auto", 1), (True, 1),
                                     (1.0, 1), ("quick", 0), ("quick", True), (None, 1)])
def test_slot_ids_out_of_range_raise(page, n):
    with pytest.raises(ValueError):
        SlotId(page, n)


@pytest.mark.parametrize("name", ["QUICK-1.vnsave", "quick-7.vnsave", "page0-1.vnsave",
                                  "page101-1.vnsave", "page03-1.vnsave", "quick-1.vnsave.bak",
                                  ".quick-1.vnsave.0123abcd.tmp", "quick-1.VNSAVE",
                                  "quick-1.vnsave\n", "auto-١.vnsave", "notes.txt"])
def test_slot_name_re_refuses_look_alikes(name):
    assert SLOT_NAME_RE.fullmatch(name) is None
    assert SlotId.from_name(name) is None


def test_every_slot_name_is_generated_once():
    slots = saves.all_slots(100)
    names = [s.file_name() for s in slots]
    assert len(names) == len(set(names)) == 612
    assert all(SLOT_NAME_RE.fullmatch(n) for n in names)
    assert names[:2] == ["auto-1.vnsave", "auto-2.vnsave"] and names[-1] == "page100-6.vnsave"


def test_a_p8_save_has_three_lines():
    from tests.fakes import jpegs
    jpeg = jpegs.engine_jpeg("flat")
    state = ss.p8_state()
    data = ss.make_save(state, jpeg=jpeg)
    assert data.isascii() and data.count(b"\n") == 3 and data.endswith(b"\n")
    first, second, third = ss.lines(data)
    meta = json.loads(first)
    assert list(meta) == META_KEYS
    assert first == json.dumps(meta, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    assert meta == {"vnsave": 1, "game": "f11-template", "seq": 1, "saved_at": ss.SAVED_AT,
                    "description": "The wind picks up.", "chapter": None, "game_version": "1.0",
                    "state_format": 1, "thumb": len(second), "state": len(third)}
    assert len(first) + meta["thumb"] + meta["state"] == len(data)
    assert re.fullmatch(rb'\{"jpeg":(null|"[A-Za-z0-9+/]*={0,2}")\}\n', second)
    assert third == json.dumps(state.to_json(), ensure_ascii=True, separators=(",", ":"),
                               allow_nan=False).encode() + b"\n"
    assert saves.parse_full(data, game_id=ss.GAME_ID).state == state


def test_a_save_without_a_picture_writes_null():
    data = ss.make_save(jpeg=None)
    assert ss.lines(data)[1] == b'{"jpeg":null}\n'


@pytest.mark.parametrize("jpeg", [b"not a jpeg", b"", "text", 5])
def test_only_engine_jpegs_are_written(jpeg):
    """§7.3 step 1: bytes ``check_engine_jpeg`` refuses are written as ``null``."""
    assert ss.lines(ss.make_save(jpeg=jpeg))[1] == b'{"jpeg":null}\n'


def test_svg_confusion_is_never_written():
    from tests.fakes import jpegs
    assert ss.lines(ss.make_save(jpeg=jpegs.svg_confusion()))[1] == b'{"jpeg":null}\n'


# --- AC-F11-07: slot status ------------------------------------------------------------------

@pytest.mark.parametrize("make, game_id, head, full", [
    (lambda: None, ss.GAME_ID, "empty", "empty"),
    (lambda: ss.make_save(), ss.GAME_ID, "ok", "ok"),
    (lambda: ss.make_save(game=None), ss.GAME_ID, "ok", "ok"),
    (lambda: ss.make_save(game="other-game"), ss.GAME_ID, "other_game", "other_game"),
    (lambda: ss.make_save(game="other-game"), None, "ok", "ok"),
    (lambda: b'{"vnsave":2,\x00\xff garbage\n\x01garbage\n{garbage\n', ss.GAME_ID,
     "newer", "newer"),
    (lambda: ss.with_meta(ss.make_save(), state_format=2), ss.GAME_ID, "newer", "newer"),
    (lambda: ss.with_line3(ss.make_save(), ss.state_json_line(
        {**ss.p8_state().to_json(), "format": 2})), ss.GAME_ID, "ok", "newer"),
    (lambda: ss.with_line3(ss.make_save(), ss.state_json_line(
        {**ss.p8_state().to_json(), "history2": {}})), ss.GAME_ID, "ok", "newer"),
], ids=["missing", "p8", "game null", "other game", "other game, no id", "vnsave 2 garbage",
        "state_format 2", "line 3 format 2", "line 3 unknown key"])
def test_slot_status(make, game_id, head, full, tmp_path):
    data = make()
    if data is not None:
        ss.write_slot(tmp_path, data)
    h = ss.head(tmp_path, game_id=game_id, thumb=True)
    f = ss.full(tmp_path, game_id=game_id)
    assert (h.status.value, f.status.value) == (head, full)
    if full == "ok":
        assert f.state == ss.p8_state() and f.reason == ""
    if head == "other_game":
        assert "other-game" not in h.reason and "other-game" not in f.reason   # SEC-F11-09a
    if head == "empty":
        assert (h.reason, f.reason) == ("", saves.REASON_GONE)


def test_head_stamp_and_meta(tmp_path):
    path = ss.write_slot(tmp_path, ss.make_save(seq=7, chapter="Chapter 2"))
    h = ss.head(tmp_path)
    assert h.stamp is not None and h.stamp.size == path.stat().st_size
    assert h.meta == saves.SaveMeta(seq=7, saved_at=ss.SAVED_AT, description="The wind picks up.",
                                    chapter="Chapter 2", game=ss.GAME_ID, game_version="1.0",
                                    state_format=1, thumb_len=h.meta.thumb_len,
                                    state_len=h.meta.state_len)


def test_entries_that_are_not_files_are_damaged_by_entry(tmp_path):
    (tmp_path / "quick-1.vnsave").mkdir()
    for result in (ss.head(tmp_path), ss.full(tmp_path)):
        assert (result.status, result.cause) == (SlotStatus.DAMAGED, saves.Cause.ENTRY)
        assert result.reason == saves.REASON_NOT_REGULAR


def test_symlinked_slot_is_never_followed(tmp_path):
    outside = tmp_path / "outside.vnsave"
    outside.write_bytes(ss.make_save())
    link = tmp_path / "saves" / "quick-1.vnsave"
    link.parent.mkdir()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need a privilege here")
    for result in (ss.head(tmp_path / "saves"), ss.full(tmp_path / "saves")):
        assert (result.status, result.cause) == (SlotStatus.DAMAGED, saves.Cause.ENTRY)


def test_hard_link_to_a_valid_save_is_read_and_validated(tmp_path):
    outside = tmp_path / "outside.vnsave"
    outside.write_bytes(ss.make_save())
    (tmp_path / "saves").mkdir()
    try:
        (tmp_path / "saves" / "quick-1.vnsave").hardlink_to(outside)
    except OSError:
        pytest.skip("hard links unsupported here")
    assert ss.full(tmp_path / "saves").status is SlotStatus.OK


def test_unreadable_file_is_damaged_by_entry(tmp_path, monkeypatch):
    from engine.core import safefile
    ss.write_slot(tmp_path, ss.make_save())

    def locked(path):
        raise PermissionError(13, "locked")

    monkeypatch.setattr(safefile, "_open_for_reading", locked)
    for result in (ss.head(tmp_path), ss.full(tmp_path)):
        assert (result.status, result.cause, result.reason) == (
            SlotStatus.DAMAGED, saves.Cause.ENTRY, saves.REASON_UNREADABLE)


# --- AC-F11-02 / TR-F11-01: every engine-written save reads back ---------------------------------

NAME_START = ["a", "b", "é", "花", "x_", "Ω", "z", "あ"]
NAME_MORE = ["a", "1", "_", "é", "花", "ß", "9", "q"]
EXTRA_PARTS = [" ", "\U0001f338", "中文", "\\u0000", "‍", "‮"]


def _name(rng: random.Random) -> str:
    from engine.runtime import state as state_module
    while True:
        name = rng.choice(NAME_START) + "".join(rng.choice(NAME_MORE)
                                                 for _ in range(rng.randint(0, 6)))
        if state_module._valid_name(name):
            return name


_PAIRED = re.compile("([\ud800-\udbff])(?=[\udc00-\udfff])")


def _text(rng: random.Random, high: int = 12) -> str:
    """Random text with lone surrogates, but never a lone high one right before a lone low
    one: JSON reads ``\\ud800\\udfff`` back as one astral character, so such a string can't
    round-trip through any JSON file (see ``test_adjacent_lone_surrogates_join``)."""
    text = "".join(rng.choice(STRING_PARTS + EXTRA_PARTS) for _ in range(rng.randint(0, high)))
    return _PAIRED.sub(r"\1x", text)


def test_adjacent_lone_surrogates_join():
    """A known JSON limit, not a save bug: two lone surrogates that form a pair come back as
    one character, so the state is not equal (TR-F11-01's generators avoid them, and C11's
    ``save_problem`` refuses such a state before a byte is written)."""
    state = ss.p8_state(s="𐏿")
    read = saves.parse_full(ss.make_save(state), game_id=ss.GAME_ID)
    assert read.status is SlotStatus.OK and read.state.variables["s"] == "\U000103ff"
    paired = ss.p8_state(s="\ud800\udfff")
    assert saves.encode_save(paired, **ss.save_fields()) == TooLarge("lone_surrogate")


def _value(rng: random.Random, depth: int = 0):
    kind = rng.randrange(9 if depth < 4 else 7)
    if kind == 0:
        return None
    if kind == 1:
        return rng.random() < 0.5
    if kind == 2:
        return rng.choice((0, -1, 2**53 + 1, -(2**63), 10**300, rng.randint(-1000, 1000)))
    if kind == 3:
        return rng.choice((0.5, -0.0, 1e-300, -2.5e300, 0.1, 3.0))
    if kind in (4, 5, 6):
        return _text(rng)
    if kind == 7:
        return [_value(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    return {_text(rng, 6): _value(rng, depth + 1) for _ in range(rng.randint(0, 5))}


def random_state(rng: random.Random) -> GameState:
    variables = {_name(rng): _value(rng) for _ in range(rng.randint(0, 12))}
    return ss.state_with(variables)


def random_fields(rng: random.Random) -> dict:
    return {"seq": rng.choice((1, 2, 2**53, 2**53 + 5, 0, -3, 10**30)),
            "saved_at": rng.choice((0, ss.SAVED_AT, -1, 253_402_300_800, 10**20)),
            "description": _text(rng, 300) + "x" * rng.choice((0, 300)),
            "chapter": rng.choice((None, _text(rng, 30), "c" * 300, "\ud800" * 250)),
            "game": rng.choice((ss.GAME_ID, None, "../x", "CON", "a" * 41, "con")),
            "game_version": rng.choice(("1.0", "v" * 100, _text(rng, 80), "花" * 70))}


def test_every_engine_written_save_reads_back():
    for seed in range(50):
        _check_written_save(seed)


def _check_written_save(seed: int) -> None:
    rng = random.Random(seed)
    state = random_state(rng)
    fields = random_fields(rng)
    result = saves.encode_save(state, jpeg=None, **fields)
    assert not isinstance(result, TooLarge)
    data = b"".join(result)
    assert data.isascii() and data.count(b"\n") == 3
    read = saves.parse_full(data, game_id=ss.GAME_ID)
    assert read.status is SlotStatus.OK, (read.reason, fields)
    assert read.state == state
    meta = read.meta
    assert meta.description == fields["description"][:200]
    assert meta.chapter == (None if fields["chapter"] is None else fields["chapter"][:200])
    assert meta.game_version == fields["game_version"][:64]
    assert meta.game == (fields["game"] if fields["game"] in (ss.GAME_ID,) else None)
    assert 1 <= meta.seq <= 2**53 and 0 <= meta.saved_at <= limits.SAVED_AT_MAX
    assert meta.seq == min(max(fields["seq"], 1), 2**53)
    assert meta.saved_at == min(max(fields["saved_at"], 0), limits.SAVED_AT_MAX)
    head = saves.classify_head(data[:limits.HEAD_MAX], len(data), ss.QUICK_1,
                               game_id=ss.GAME_ID, thumb=True)
    assert head.status is SlotStatus.OK and head.meta == meta


@pytest.mark.parametrize("key", ["\"", "\\", " ", "\ud800", "\udfff", "花",
                                 "\U0001f338", "{", "[", ",", ":", "\n"])
def test_hostile_strings_in_keys_and_values(key):
    """SEC-F11-04(d): every key and value through ``json.dumps(ensure_ascii=True)``."""
    state = ss.p8_state(bag={key: [key, {key: key * 3}]}, s=key * 5)
    data = ss.make_save(state, description=key * 300, chapter=key, game_version=key * 100)
    read = saves.parse_full(data, game_id=ss.GAME_ID)
    assert read.status is SlotStatus.OK and read.state == state
    assert read.meta.description == (key * 300)[:200]


@pytest.mark.slow
def test_every_engine_written_save_reads_back_10000():
    for seed in range(1_000, 11_000):
        _check_written_save(seed)


# --- AC-F11-05: too large (encoder rows) ---------------------------------------------------------

def _filler(target_line3: int) -> GameState:
    """P8 with one string variable sized so line 3 (with its \\n) is ``target_line3``."""
    base = len(b"".join(saves.iter_pieces(ss.p8_state(pad="").to_json()))) + 1
    return ss.p8_state(pad="x" * (target_line3 - base))


def test_state_one_byte_over_the_cap_is_too_large(monkeypatch):
    monkeypatch.setattr(limits, "STATE_MAX_BYTES", 65_536)
    over = saves.encode_save(_filler(65_537), **ss.save_fields())
    assert over == TooLarge(saves.TOO_LARGE_STATE)
    at = saves.encode_save(_filler(65_536), **ss.save_fields())
    data = b"".join(at)
    assert len(ss.lines(data)[2]) == 65_536
    assert saves.parse_full(data, game_id=ss.GAME_ID).status is SlotStatus.OK


@pytest.mark.slow
def test_state_one_byte_over_the_real_cap_is_too_large():
    cap = limits.STATE_MAX_BYTES
    assert saves.encode_save(_filler(cap + 1), **ss.save_fields()) == TooLarge(
        saves.TOO_LARGE_STATE)
    data = b"".join(saves.encode_save(_filler(cap), **ss.save_fields()))
    assert saves.parse_full(data, game_id=ss.GAME_ID).status is SlotStatus.OK


def test_too_much_structure_is_too_large(monkeypatch):
    """At a bound lowered to 2,000 (the constant itself is AC-F11-62's). A refused state keeps
    no pieces."""
    monkeypatch.setattr(limits, "SAVE_PRESCAN_MAX", 2_000)
    state = ss.p8_state(v=[[] for _ in range(1_001)])
    encoder = SaveEncoder(state, **ss.save_fields())
    assert encoder.run() == TooLarge(saves.TOO_LARGE_STRUCTURE)
    assert encoder.state_pieces is None


@pytest.mark.parametrize("state, reason", [
    (lambda: ss.state_with({f"v{i}": 0 for i in range(runtime_limits.STATE_MAX_NAMES + 1)}),
     "too_many_names"),
    (lambda: GameState(position="s" * 1025, position_at=("start", (2,)), call_stack=(),
                       variables=MappingProxyType({}), dice=ss.P8_DICE), "position"),
    (lambda: GameState(position=ss.P8_SID, position_at=("l" * 1025, (2,)), call_stack=(),
                       variables=MappingProxyType({}), dice=ss.P8_DICE), "hint"),
    (lambda: ss.p8_state(bag={"k": ["ok", "a\ud800\udc00"]}), "lone_surrogate"),
    (lambda: ss.p8_state(bag={"\ud800\udfff": 1}), "lone_surrogate"),
], ids=["100,001 variables", "sid of 1,025", "hint label of 1,025", "lone surrogate value",
        "lone surrogate key"])
def test_save_problem_refuses_before_any_piece(state, reason, monkeypatch):
    pieces = []
    monkeypatch.setattr(saves, "iter_pieces", lambda *a, **k: pieces.append(1) or iter(()))
    result = SaveEncoder(state(), **ss.save_fields()).run()
    assert result == TooLarge(reason) and pieces == []


def test_save_problem_is_f03s_method(monkeypatch):
    """C11: the encoder's check is F03's ``GameState.save_problem()``."""
    state = ss.p8_state()
    fake = SimpleNamespace(save_problem=lambda: "f03_word")
    assert saves.save_problem(fake) == "f03_word"
    assert saves.save_problem(state) is None


def test_save_problem_counts_members():
    big = ss.p8_state(a=[0] * (runtime_limits.STATE_MAX_ITEMS // 2),
                      b=[[0, 0]] * (runtime_limits.STATE_MAX_ITEMS // 6 + 1))
    assert saves.save_problem(big) == "too_many_items"


def test_pieces_are_reused_for_the_same_checkpoint(monkeypatch):
    """§7.3 step 4: F5 held on one checkpoint encodes the state once."""
    state = ss.p8_state(text="x" * 1000)
    first = SaveEncoder(state, **ss.save_fields())
    first.run()
    calls = []
    monkeypatch.setattr(saves, "iter_pieces", lambda *a, **k: calls.append(1) or iter(()))
    second = SaveEncoder(state, **ss.save_fields(seq=2), pieces_from=first)
    other = SaveEncoder(ss.p8_state(text="x" * 1000), **ss.save_fields(), pieces_from=first)
    data = b"".join(second.run())
    other.run()
    assert calls == [1]                                   # only the other checkpoint
    read = saves.parse_full(data, game_id=ss.GAME_ID)
    assert read.status is SlotStatus.OK and read.meta.seq == 2 and read.state == state


# --- AC-F11-06: description ---------------------------------------------------------------------

def _with_history(*entries) -> SimpleNamespace:
    return SimpleNamespace(history=SimpleNamespace(entries=tuple(
        SimpleNamespace(kind=kind, sid="start/0", name=name, text=text)
        for kind, name, text in entries)))


@pytest.mark.parametrize("entries, chapter, expected", [
    ([("line", "Hana", "Hey, have you ever written a poem? I wrote one about paper lanterns "
                       "last night.")], None,
     "Hana: Hey, have you ever written a poem? I wrote one abo…"),
    ([("line", "", "The wind picks up.")], None, "The wind picks up."),
    ([("line", "", "The wind picks up."), ("line", "Hana", "Where should we go?")], None,
     "Hana: Where should we go?"),
    ([("line", "Hana", "Where should we go?"), ("choice", "", "Go home")], None,
     "Hana: Where should we go?"),
    ([("line", "", "a\n\nb    c\t d")], None, "a b c d"),
    ([], None, ""),
    ([("line", "", "The wind picks up.")], "Chapter 2: The Poem", "Chapter 2: The Poem"),
    ([("line", "", "The wind picks up.")], "   ", "The wind picks up."),
    ([("line", "", "x" * 50)], None, "x" * 50),
    ([("line", "", "x" * 51)], None, "x" * 50 + "…"),
    ([], "c" * 300, "c" * 200),
])
def test_describe(entries, chapter, expected):
    assert saves.describe(_with_history(*entries), chapter) == expected


def test_describe_p8_and_no_history():
    """AC-F11-06: the real P8 checkpoint describes its newest line; no history → ""."""
    import dataclasses

    from engine.runtime.history import EMPTY_HISTORY

    assert saves.describe(ss.p8_state(), None) == "The wind picks up."
    assert saves.describe(ss.p8_state(), "Chapter 1") == "Chapter 1"
    empty = dataclasses.replace(ss.p8_state(), history=EMPTY_HISTORY)
    assert saves.describe(empty, None) == ""


# --- split_lines and strict_loads ---------------------------------------------------------------

def test_split_lines():
    data = ss.make_save()
    first, second, third = ss.lines(data)
    meta = json.loads(first)
    lines = saves.split_lines(data, len(data), (meta["thumb"], meta["state"]))
    assert lines.meta == first[:-1]
    assert lines.thumb == (len(first), len(first) + len(second))
    assert lines.state == (len(first) + len(second), len(data))
    assert saves.split_lines(data, len(data) + 1, (meta["thumb"], meta["state"])) == "line lengths"
    assert saves.split_lines(b"x" * limits.META_MAX + b"\n", 0) == "meta line"
    head = data[:len(first) + 10]                          # a short head: line 2 not all read
    assert isinstance(saves.split_lines(head, len(data), (meta["thumb"], meta["state"])),
                      saves.Lines)


@pytest.mark.parametrize("line, ok", [(b'{"a":1}', True), (memoryview(b'[1,2]'), True),
                                      (b'{"a":1,"a":2}', False), (b"NaN", False),
                                      (b'"\xc3\xa9"', False), (b"1" * 4301, False),
                                      (b"[" * 5000 + b"]" * 5000, False)])
def test_strict_loads(line, ok):
    if ok:
        strict = saves.strict_loads(line)
        assert strict == json.loads(bytes(line))
    else:
        with pytest.raises(saves.PARSE_ERRORS):
            saves.strict_loads(line)


def test_saves_root(tmp_path, user_roots):
    from engine.core.paths import user_data_dir
    from engine.persist.location import saves_root
    game = tmp_path / "game"
    assert saves_root(game_root=game, release=False, app_id=None) == game / "saves"
    assert saves_root(game_root=game, release=True, app_id="paper-lanterns") == (
        user_data_dir("paper-lanterns") / "saves")
    assert saves_root(game_root=game, release=True, app_id=None) is None
    assert saves_root(game_root=game, release=True, app_id="../x") is None


def test_saves_module_runs_no_code_and_stays_pure():
    """SEC-F11-07a / TR-F11-05 (the ``persist/saves.py`` half): stdlib and engine imports
    only; no pickle, threads, ``shutil``, pygame, or subprocesses; no ``eval``/``exec``/
    ``open``; ``json.loads`` only through F12's ``fileformat.parse``."""
    import ast
    import sys
    from pathlib import Path
    source = Path(saves.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    top = {name.split(".")[0] for name in imported}
    assert top - {"engine"} <= sys.stdlib_module_names
    assert not top & {"pickle", "marshal", "shelve", "importlib", "ctypes", "subprocess",
                      "shutil", "threading", "queue", "_thread", "pygame", "logging"}
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"eval", "exec", "compile", "__import__", "open", "print"}
    attributes = {f"{node.value.id}.{node.attr}" for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)}
    assert "json.loads" not in attributes and "fileformat.parse" in attributes
    assert not any(name.endswith(".rmtree") for name in attributes)
