"""Shared helpers for the F11 save-file tests (06-acceptance §0.2 "Bytes", "Read spy",
"Loads spy", "Decode spy", "Encoder E").

``p8_state()`` is the checkpoint at line 8 of the reduced Template S below (I-14 A8: App S
rows run on a reduced template until F04, F07, F08, and F09 are built), written out by hand so
the hostile rows don't depend on the interpreter; ``test_save_format`` checks it equals the
real checkpoint. ``make_save`` writes bytes through ``SaveEncoder`` (game id
``f11-template``, ``seq`` 1, ``saved_at`` 1,793,567,040), and the ``with_*`` helpers apply one
row's edit while keeping the other lines byte for byte.
"""

import json
from pathlib import Path
from types import MappingProxyType

from engine.core import safefile
from engine.persist import saves
from engine.runtime.history import HistoryEntry, HistoryState
from engine.runtime.state import GameState

GAME_ID = "f11-template"
SAVED_AT = 1_793_567_040
QUICK_1 = saves.SlotId("quick", 1)

# The reduced Template S (06 §0.4 lines 1–8 and 18–19, without scene, music, or menu).
TEMPLATE_S_REDUCED = '''define hana = Character("Hana")
default trust = 0
label start:
    hana "Hey, have you ever written a poem? I wrote one about paper lanterns last night."
    $ wind = dice.roll(1, 1000)
    "The wind picks up."
    $ trust += 1
    hana "Thanks!"
    "End of the day."
    return
'''

P8_SID = "start/0a6c422ce182"
P8_DICE = 0xBAA582B670050953
# F13 step 1: the checkpoint's history holds the two lines read so far (line 6, then P8).
P8_HISTORY = HistoryState((
    HistoryEntry("line", "start/05ed5fa51da7", "Hana",
                 "Hey, have you ever written a poem? I wrote one about paper lanterns last "
                 "night."),
    HistoryEntry("line", P8_SID, "", "The wind picks up.")))


def p8_state(**variables) -> GameState:
    """The reduced template's ``"The wind picks up."`` checkpoint (seed 42), its F13
    history included."""
    values = {"trust": 0, "wind": 780, **variables}
    return GameState(position=P8_SID, position_at=("start", (2,)), call_stack=(),
                     variables=MappingProxyType(values), dice=P8_DICE, identity_scheme=1,
                     history=P8_HISTORY)


def state_with(variables: dict) -> GameState:
    """P8 with exactly ``variables``."""
    return GameState(position=P8_SID, position_at=("start", (2,)), call_stack=(),
                     variables=MappingProxyType(dict(variables)), dice=P8_DICE,
                     identity_scheme=1, history=P8_HISTORY)


def save_fields(**edits) -> dict:
    fields = {"seq": 1, "saved_at": SAVED_AT, "description": "The wind picks up.",
              "chapter": None, "game": GAME_ID, "game_version": "1.0", "jpeg": None}
    fields.update(edits)
    return fields


def make_save(state: GameState | None = None, **edits) -> bytes:
    """A save file's bytes written by ``SaveEncoder``; ``edits`` replace encoder fields."""
    result = saves.encode_save(p8_state() if state is None else state, **save_fields(**edits))
    assert not isinstance(result, saves.TooLarge), result
    return b"".join(result)


def lines(data: bytes) -> tuple[bytes, bytes, bytes]:
    """Lines 1, 2, 3 of a well-formed file, each with its ``\\n``."""
    first, second, third = data.split(b"\n", 2)
    return first + b"\n", second + b"\n", third


def meta(data: bytes) -> dict:
    return json.loads(lines(data)[0])


def dumps_meta(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def with_meta(data: bytes, **edits) -> bytes:
    """``data`` with meta keys replaced (``drop=`` names keys to remove); lines 2 and 3 and
    their declared lengths kept."""
    drop = edits.pop("drop", ())
    obj = meta(data)
    obj.update(edits)
    for key in drop:
        del obj[key]
    _, second, third = lines(data)
    return dumps_meta(obj) + second + third


def with_line1(data: bytes, line1: bytes) -> bytes:
    _, second, third = lines(data)
    return line1 + second + third


def with_line2(data: bytes, line2: bytes) -> bytes:
    """``data`` with line 2 replaced (with its ``\\n``) and ``thumb`` fixed up."""
    first, _, third = lines(data)
    obj = json.loads(first)
    obj["thumb"] = len(line2)
    return dumps_meta(obj) + line2 + third


def with_line3(data: bytes, line3: bytes) -> bytes:
    """``data`` with line 3 replaced (without its ``\\n``) and ``state`` fixed up."""
    first, second, _ = lines(data)
    obj = json.loads(first)
    obj["state"] = len(line3) + 1
    return dumps_meta(obj) + second + line3 + b"\n"


def state_line(variables_json: bytes, base: GameState | None = None) -> bytes:
    """A state line (no ``\\n``) of ``base`` (P8) whose ``variables`` is the raw JSON text
    ``variables_json``."""
    obj = (base or p8_state()).to_json()
    obj["variables"] = "@@VARIABLES@@"
    text = json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return text.replace(b'"@@VARIABLES@@"', variables_json)


def state_json_line(obj: object, *, allow_nan: bool = False) -> bytes:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=allow_nan).encode("ascii")


def write_slot(folder: Path, data: bytes, slot: saves.SlotId = QUICK_1) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / slot.file_name()
    path.write_bytes(data)
    return path


def head(folder: Path, slot: saves.SlotId = QUICK_1, *, game_id: str | None = GAME_ID,
         thumb: bool = False) -> saves.SlotHead:
    return saves.read_slot_head(folder, slot, game_id=game_id, thumb=thumb)


def full(folder: Path, slot: saves.SlotId = QUICK_1, *,
         game_id: str | None = GAME_ID) -> saves.FullRead:
    return saves.read_slot_full(folder, slot, game_id=game_id)


class ReadSpy(list):
    """The byte counts ``core.safefile`` reads return, one per read call."""

    def install(self, monkeypatch) -> "ReadSpy":
        real = safefile._read_bounded

        def spy(fd, expected, limit):
            data = real(fd, expected, limit)
            self.append(len(data))
            return data

        monkeypatch.setattr(safefile, "_read_bounded", spy)
        return self


class LoadsSpy(list):
    """``(type of the text, kwargs)`` of every ``json.loads`` call."""

    def install(self, monkeypatch) -> "LoadsSpy":
        real = json.loads

        def spy(text, *args, **kwargs):
            self.append((type(text), kwargs))
            return real(text, *args, **kwargs)

        monkeypatch.setattr(json, "loads", spy)
        return self


class DecodeSpy(list):
    """The argument sizes of every ``base64.b64decode`` call made by ``persist/saves.py``."""

    def install(self, monkeypatch) -> "DecodeSpy":
        real = saves.base64.b64decode

        def spy(data, *args, **kwargs):
            self.append(len(data))
            return real(data, *args, **kwargs)

        monkeypatch.setattr(saves.base64, "b64decode", spy)
        return self


class FakeClock:
    """Encoder E's clock: every read advances 1 ms. ``reads`` records each value."""

    def __init__(self, step: float = 0.001) -> None:
        self.now = 0.0
        self.step = step
        self.reads: list[float] = []

    def __call__(self) -> float:
        self.now += self.step
        self.reads.append(self.now)
        return self.now
