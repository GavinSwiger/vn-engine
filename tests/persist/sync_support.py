"""Harness Y (F12 ``06-acceptance.md`` §0.2) for the sync tests (F12 checklist step 5):
``PersistentSync`` on a real ``<game>/persistent`` folder, a fake clock, and a ``Writer``
that is synchronous unless a test asks for a thread. ``tick(t)`` calls ``update(t)``.

``open_for_launch`` is F12 step 6; ``launch`` here does what it will do for a folder that
exists: read the file into the store (``ReadJob``) and take its stamp. Stdlib only."""

import json
import logging
from pathlib import Path

from engine.core import safefile
from engine.persist import limits
from engine.persist.fileformat import Outcome, ReadJob, decode, encode_bytes, parse
from engine.persist.location import FILE_NAME, display_file
from engine.persist.sync import WRITABLE, Mode, PersistentSync
from engine.persist.writer import Writer
from engine.runtime.persistent import CHOSEN, SEEN, PersistentStore
from tests.persist.helpers import FakeProgram
from tests.persist.writer_support import FakeClock, FakeSleep

LOG = logging.getLogger("vn.persist")


class Harness:
    """One copy of the game: its store, program, clock, writer, and sync."""

    def __init__(self, folder: Path, *, game: Path, program=None, store=None,
                 mode: Mode = WRITABLE, threaded: bool = False, writer: Writer | None = None,
                 clock=None, sleep=None, last_write: float | None = -5.0,
                 defaults: dict | None = None) -> None:
        self.folder = folder
        self.program = program if program is not None else FakeProgram()
        self.store = store if store is not None else PersistentStore(identity_scheme=1)
        self.store.display = display_file(folder, game_root=game)
        self.clock = clock if clock is not None else FakeClock(0.0)
        self.sleep = sleep if sleep is not None else FakeSleep()
        self.writer = writer if writer is not None else Writer(threaded=threaded,
                                                               sleep=self.sleep)
        stamp = None
        if mode is WRITABLE:
            folder.mkdir(parents=True, exist_ok=True)
            stamp = self.launch_read()
        for name, value in (defaults or {}).items():      # phase 2b, after the read
            self.store.set_default(name, value)
        self.sync = PersistentSync(self.store, self.program, mode=mode,
                                   folder=folder if mode is not Mode.MEMORY else None,
                                   stamp=stamp, clock=self.clock, log=LOG, writer=self.writer)
        if last_write is not None:
            self.sync.last_start = last_write
        self.now = 0.0

    def launch_read(self):
        result = safefile.read_regular(self.folder / FILE_NAME, limits.FILE_MAX_BYTES)
        if not result.ok:
            return None
        job = ReadJob(result.data, self.store, self.program)
        assert job.run().kind is Outcome.OK
        return result.stamp

    def tick(self, t: float | None = None) -> None:
        if t is None:
            t = self.now + 1 / 60
        self.now = t
        self.sync.update(t)

    def ticks(self, seconds: float, step: float = 1 / 60) -> None:
        """Ticks from now until ``seconds`` later."""
        end = self.now + seconds
        while self.now + step <= end + 1e-9:
            self.tick(self.now + step)

    @property
    def path(self) -> Path:
        return self.folder / FILE_NAME

    def disk(self) -> dict:
        """The file's content as JSON."""
        return parse(decode(self.path.read_bytes()))

    def encoded(self) -> bytes:
        return encode_bytes(self.store, self.program)


def records(store: PersistentStore, form: str) -> set[str]:
    sep = "/" if form == SEEN else "#"
    return {f"{group}{sep}{key}" for group, run in store.records(form).items()
            for key in run.order}


def disk_records(obj: dict, form: str) -> set[str]:
    sep = "/" if form == SEEN else "#"
    section = obj["seen" if form == SEEN else "chosen"]
    return {f"{group}{sep}{key}" for group, text in section.items() for key in text.split(" ")}


def disk_unlocks(obj: dict) -> set[tuple[str, str]]:
    return {(kind, name) for kind, names in obj["unlocks"].items() for name in names}


def store_unlocks(store: PersistentStore) -> set[tuple[str, str]]:
    return {(kind, name) for kind, entry in store.kind_items() for name in entry.names}


def sid(label: str, n: int) -> str:
    return f"{label}/{n:012x}"


def plant(path: Path, data: bytes) -> None:
    """Another writer replaces the file (a new file ID, as ``os.replace`` gives)."""
    side = path.with_name("side.bin")
    side.write_bytes(data)
    safefile.os.replace(side, path)


def dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")


__all__ = ["CHOSEN", "Harness", "LOG", "SEEN", "dumps", "disk_records", "disk_unlocks",
           "plant", "records", "sid", "store_unlocks"]
