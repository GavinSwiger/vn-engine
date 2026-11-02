"""One copy of a game for AC-F12-39's real pair (``slow``): ``python -I copy_worker.py FOLDER
INDEX OPS OUT [relock]``. Two of these run at once on one persistent folder, each with a
threaded writer, doing ``OPS`` random sets, deletes, marks, and unlocks with a frame tick
after each. With ``relock`` (F19 AC-F19-28's real pair) some unlocks become unlocks and
relocks of this copy's own names ``e<INDEX>_*`` in the revocable kind ``"ending"``.

At the end they take turns so the last write merges everything: each finishes its writes and
says so (``done<i>`` beside the folder); copy 0 then marks one more line, writes, closes, and
says ``closed0``; copy 1 then does the same. ``OUT`` gets the lines and unlocks this copy
made (and, with ``relock``, its own ``"ending"`` names held at the end), as JSON. Run with
``-I``, so the project root is put on ``sys.path`` here."""

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.core import safefile  # noqa: E402
from engine.persist import limits  # noqa: E402
from engine.persist.fileformat import Outcome, ReadJob  # noqa: E402
from engine.persist.location import FILE_NAME  # noqa: E402
from engine.persist.sync import WRITABLE, PersistentSync  # noqa: E402
from engine.persist.writer import Writer  # noqa: E402
from engine.runtime.persistent import PersistentNoValue, PersistentStore  # noqa: E402

WAIT_S = 120.0


def wait_for(path: Path) -> None:
    deadline = time.monotonic() + WAIT_S
    while not path.exists():
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting for {path.name}")
        time.sleep(0.01)


def main(folder_arg: str, index_arg: str, ops_arg: str, out_arg: str, mode: str = "") -> int:
    folder = Path(folder_arg).resolve()
    index, ops = int(index_arg), int(ops_arg)
    relock = mode == "relock"
    store = PersistentStore(identity_scheme=1)
    result = safefile.read_regular(folder / FILE_NAME, limits.FILE_MAX_BYTES)
    if result.ok:
        assert ReadJob(result.data, store, None).run().kind is Outcome.OK
    store.register_kind("cg")
    store.register_kind("ending", revocable=True)
    writer = Writer(threaded=True)
    sync = PersistentSync(store, None, mode=WRITABLE, folder=folder,
                          stamp=result.stamp if result.ok else None, writer=writer)
    rng = random.Random(f"pair:{index}")
    seen: list[str] = []
    unlocks: list[tuple[str, str]] = []
    now = 0.0
    for i in range(ops):
        roll = rng.random()
        if roll < 0.3:
            store.set(f"n{rng.randrange(6)}", i)
        elif roll < 0.4:
            try:
                store.delete(f"n{rng.randrange(6)}")
            except PersistentNoValue:
                pass
        elif roll < 0.85:
            sid = f"c{index}l{rng.randrange(20)}/{rng.randrange(400):012x}"
            store.mark_seen(sid)
            seen.append(sid)
        elif not relock or roll < 0.9:
            name = f"c{index}u{rng.randrange(50)}"
            store.unlock("cg", name)
            unlocks.append(("cg", name))
        else:
            name = f"e{index}_{rng.randrange(20)}"
            if rng.random() < 0.6:
                store.unlock("ending", name)
            else:
                store.relock("ending", name)
        now += 0.25
        sync.update(now)
        time.sleep(0.001)                   # writes finish and the copies interleave
    assert sync.flush_now(writer.now() + 30.0)
    (folder.parent / f"done{index}").write_text("1")
    wait_for(folder.parent / f"done{1 - index}")
    if index == 1:
        wait_for(folder.parent / "closed0")
    final = f"end{index}/{index:012x}"
    store.mark_seen(final)
    seen.append(final)
    assert sync.flush_now(writer.now() + 30.0)
    sync.close()
    writer.stop(writer.now() + 5.0)
    if index == 0:
        (folder.parent / "closed0").write_text("1")
    own = [n for n in store.unlocked("ending") if n.startswith(f"e{index}_")]
    Path(out_arg).write_text(json.dumps({"seen": seen, "unlocks": unlocks, "endings": own,
                                         "requests": sync.requests, "merges": sync.merges}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:6]))
