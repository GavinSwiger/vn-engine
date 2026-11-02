"""Rotation, Newest, and ``seq`` (F11 ``04`` §7.4; SEC-F11-04a, -05): the unit half of
AC-F11-25 and AC-F11-55 (abuse group G). The App S rows (F5 ×3, a locked slot, notices) come
with ``SaveService`` (step 8)."""

import pytest

from engine.persist import limits, saves
from engine.persist.saves import Cause, SlotId, SlotStatus, next_seq, newest, rotation_target
from tests.persist import save_support as ss


def _meta(seq: int) -> saves.SaveMeta:
    return saves.SaveMeta(seq=seq, saved_at=0, description="", chapter=None, game=ss.GAME_ID,
                          game_version="1.0", state_format=1, thumb_len=14, state_len=10)


def h(n: int, status: str = "ok", seq: int = 1, cause: Cause | None = None,
      page="quick") -> saves.SlotHead:
    status_ = SlotStatus(status)
    if status_ is SlotStatus.DAMAGED and cause is None:
        cause = Cause.CONTENT
    meta = _meta(seq) if status_ in (SlotStatus.OK, SlotStatus.OTHER_GAME) else None
    return saves.SlotHead(SlotId(page, n), status_, cause, meta, None, None, "")


def page(*heads: saves.SlotHead) -> list[saves.SlotHead]:
    return list(heads)


def test_the_first_empty_slot_wins():
    heads = page(h(1, seq=5), h(2, seq=1), h(3, "empty"), h(4, "damaged"), h(5, "empty"),
                 h(6, seq=2))
    assert rotation_target(heads) == 3


def test_then_the_first_content_damaged_slot():
    heads = page(h(1, seq=5), h(2, "damaged", cause=Cause.ENTRY), h(3, "newer"),
                 h(4, "damaged"), h(5, seq=1), h(6, "damaged"))
    assert rotation_target(heads) == 4


def test_then_the_oldest_ok_slot_by_seq_never_the_clock():
    heads = page(h(1, seq=50), h(2, seq=7), h(3, seq=9), h(4, seq=8), h(5, seq=60),
                 h(6, seq=70))
    assert rotation_target(heads) == 2


def test_ties_go_to_session_order_then_the_lower_number():
    heads = page(*(h(n, seq=2**53) for n in range(1, 7)))
    assert rotation_target(heads) == 1
    order = {SlotId("quick", 1): 3, SlotId("quick", 2): 1}
    assert rotation_target(heads, order=order) == 3          # 3..6 have order 0, 3 lowest
    order = {SlotId("quick", n): 7 - n for n in range(1, 7)}
    assert rotation_target(heads, order=order) == 6


@pytest.mark.parametrize("statuses", [
    ["newer"] * 6, ["other_game"] * 6, ["newer", "other_game"] * 3,
])
def test_newer_and_other_game_slots_are_never_chosen(statuses):
    """AC-F11-55 (O1): ``save_reason_slots`` rather than overwrite."""
    assert rotation_target(page(*(h(n, s) for n, s in enumerate(statuses, 1)))) is None


def test_entry_damaged_and_failed_slots_are_never_chosen():
    """SEC-F11-05: a locked file (UNREADABLE), a folder at the slot name, and a slot whose
    write failed this session are skipped; quick saves keep going to the others."""
    heads = page(h(1, "damaged", cause=Cause.ENTRY), h(2, seq=4), h(3, seq=3),
                 h(4, seq=2), h(5, seq=5), h(6, seq=6))
    assert rotation_target(heads) == 4
    assert rotation_target(heads, skip={SlotId("quick", 4)}) == 3
    everything = {SlotId("quick", n) for n in range(2, 7)}
    assert rotation_target(heads, skip=everything) is None


def test_skip_also_skips_empty_and_content_damaged():
    heads = page(h(1, "empty"), h(2, "damaged"), h(3, seq=1), h(4, seq=2), h(5, seq=3),
                 h(6, seq=4))
    assert rotation_target(heads, skip={SlotId("quick", 1)}) == 2
    assert rotation_target(heads, skip={SlotId("quick", 1), SlotId("quick", 2)}) == 3


def test_next_seq_ignores_non_ok_heads_and_saturates():
    """SEC-F11-04a / QA G7: DAMAGED, NEWER, OTHER_GAME seqs don't count; 2⁵³ saturates."""
    assert next_seq([]) == 1
    assert next_seq([h(1, seq=41), h(2, "empty")]) == 42
    assert next_seq([h(1, seq=3), h(2, "other_game", seq=2**53), h(3, "newer"),
                     h(4, "damaged")]) == 4
    assert next_seq([h(1, seq=2**53)]) == limits.SEQ_MAX == 2**53
    assert next_seq([h(1, seq=2**53 - 1)]) == 2**53


def test_newest_by_seq_then_session_order_then_lower_number():
    heads = [h(1, seq=5), h(2, seq=9), h(3, "other_game", seq=99), h(4, "damaged")]
    assert newest(heads) == SlotId("quick", 2)
    tied = [h(n, seq=2**53) for n in range(1, 4)]
    assert newest(tied) == SlotId("quick", 1)
    assert newest(tied, order={SlotId("quick", 3): 4, SlotId("quick", 2): 2}) == SlotId("quick", 3)
    assert newest([h(1, "empty"), h(2, "newer")]) is None


def test_a_hostile_seq_file_then_three_saves_all_read_back(tmp_path):
    """Group G: ``seq`` 2⁵³ in a quick slot, then three quick saves through rotation: each
    new file reads OK, and the last written is Newest by session order."""
    folder = tmp_path / "saves"
    ss.write_slot(folder, ss.make_save(seq=2**53), SlotId("quick", 1))
    for n in range(2, 7):
        ss.write_slot(folder, ss.make_save(seq=n), SlotId("quick", n))
    order: dict[SlotId, int] = {}
    written = []
    for counter in range(1, 4):
        heads = [ss.head(folder, slot) for slot in saves.page_slots("quick")]
        target = SlotId("quick", rotation_target(heads, order=order))
        seq = next_seq(heads)
        assert seq <= 2**53
        ss.write_slot(folder, ss.make_save(seq=seq), target)
        order[target] = counter
        written.append(target)
        assert ss.full(folder, target).status is SlotStatus.OK
    heads = [ss.head(folder, slot) for slot in saves.page_slots("quick")]
    assert newest(heads, order=order) == written[-1]
    assert all(head.status is SlotStatus.OK for head in heads)
    assert written == [SlotId("quick", 2), SlotId("quick", 3), SlotId("quick", 4)]
