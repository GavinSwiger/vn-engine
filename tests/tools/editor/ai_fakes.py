"""Fakes for F48's Studio tests (W3 settings, W4 pane): an in-memory keychain, the
``aisettings.AiServices`` seams over it, a ``FakeTransport`` factory, and a wait for the
off-Tk-thread work. No network, no real keychain, no real user folder."""

import json
import time
from pathlib import Path

from engine.tools.assistant import keystore
from engine.tools.assistant.keystore import FileStore, KeyStore, Outcome
from engine.tools.assistant.providers.transport import FakeReply, FakeTransport
from engine.tools.editor import aisettings

ANTHROPIC_KEY = "sk-ant-api03-test-key-0123456789"
OPENAI_KEY = "sk-proj-test-key-0123456789abcdef"


class FakeBackend:
    """A keychain in a dict (slot name -> key); ``calls`` records (action, slot name)."""

    saved_text = keystore.SAVED_WINDOWS

    def __init__(self, keys: dict[str, str] | None = None) -> None:
        self.keys = dict(keys or {})
        self.calls: list[tuple[str, str]] = []

    def write(self, slot, key: str) -> Outcome:
        self.calls.append(("write", slot.name))
        self.keys[slot.name] = key
        return Outcome(keystore.OK)

    def read(self, slot) -> Outcome:
        self.calls.append(("read", slot.name))
        if slot.name in self.keys:
            return Outcome(keystore.OK, self.keys[slot.name])
        return Outcome(keystore.NOT_FOUND)

    def delete(self, slot) -> Outcome:
        self.calls.append(("delete", slot.name))
        return Outcome(keystore.OK if self.keys.pop(slot.name, None) else keystore.NOT_FOUND)


class Transports:
    """``AiServices.transport``: each call makes a new ``FakeTransport`` answering the next
    queued replies (``queue(*replies)``); ``made`` holds them all."""

    def __init__(self) -> None:
        self.made: list[FakeTransport] = []
        self._queued: list[tuple] = []

    def queue(self, *replies) -> None:
        self._queued.append(replies)

    def __call__(self) -> FakeTransport:
        transport = FakeTransport(*(self._queued.pop(0) if self._queued else ()))
        self.made.append(transport)
        return transport

    @property
    def requests(self) -> list:
        return [request for transport in self.made for request in transport.requests]


def services(tmp_path: Path, *, keys: dict[str, str] | None = None,
             environ: dict[str, str] | None = None
             ) -> tuple[aisettings.AiServices, FakeBackend, Transports]:
    """Seams over ``tmp_path``: prefs in ``<tmp>/studio``, the fallback file folder in
    ``<tmp>/studio-local`` (never used: the fake keychain exists)."""
    folder = tmp_path / "studio"
    folder.mkdir(exist_ok=True)
    local = tmp_path / "studio-local"
    local.mkdir(exist_ok=True)
    backend = FakeBackend(keys)
    transports = Transports()
    made = aisettings.AiServices(keys=lambda: KeyStore(backend, FileStore(folder=lambda: local)),
                                 folder=folder, transport=transports,
                                 environ=environ if environ is not None else {})
    return made, backend, transports


def models_reply(*ids: str) -> FakeReply:
    data = json.dumps({"data": [{"id": model} for model in ids]}).encode("utf-8")
    return FakeReply(200, {"content-type": "application/json"}, [data])


def status_reply(status: int, body: object = None, headers: dict | None = None) -> FakeReply:
    data = json.dumps(body if body is not None else {"error": {"message": "nope"}})
    return FakeReply(status, headers or {}, [data.encode("utf-8")])


def wait_for(root, done, timeout: float = 20.0) -> None:
    """Run Tk until ``done()`` (the off-thread work answered)."""
    end = time.monotonic() + timeout
    while not done():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for Studio's background work")
        root.update()
        time.sleep(0.01)
    root.update()
