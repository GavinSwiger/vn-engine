"""Privacy check P (06-acceptance §0.5) and the channels it is applied to."""

import contextlib
import getpass
import re
from dataclasses import dataclass, field
from pathlib import Path

import pygame

from engine.core.logsetup import LogSetup
from tests.fakes.draw_spy import TextCall, spy_draw_text

REAL_HOME = Path.home()            # read at import, before any test patches HOME


def _forms(path: str) -> set[str]:
    return {path, path.replace("\\", "/"), path.replace("\\", "\\\\"), "\\\\?\\" + path}


def check_p(texts, *, home: Path, game: Path | None = None) -> None:
    """Fail if any text contains ``qauser7``, the account name as a path segment, the
    home folder (patched or real) in any form, or the absolute game root in any form."""
    user = getpass.getuser().lower()
    segment = re.compile(r"(^|[/\\'\"\s])" + re.escape(user) + r"($|[/\\'\"\s])")
    forms: set[str] = set()
    for root in (home, REAL_HOME, Path.home()):
        forms |= _forms(str(root))
    if game is not None:
        forms |= _forms(str(game)) | _forms(str(game.resolve()))
    for text in texts:
        lowered = text.lower()
        assert "qauser7" not in lowered, text[:300]
        assert not segment.search(lowered), text[:300]
        for form in forms:
            assert form.lower() not in lowered, (form, text[:300])


@dataclass
class Channels:
    draws: list[TextCall] = field(default_factory=list)
    clipboard: list[str] = field(default_factory=list)
    tails: list[list[str]] = field(default_factory=list)

    def texts(self) -> list[str]:
        return ([c.text for c in self.draws] + list(self.clipboard)
                + ["\n".join(tail) for tail in self.tails])


@contextlib.contextmanager
def capture_channels(monkeypatch):
    """Spy on draw_text, ``pygame.scrap.put_text``, and the log tail at close."""
    channels = Channels()
    monkeypatch.setattr(pygame.scrap, "put_text", lambda text: channels.clipboard.append(text))
    real_close = LogSetup.close

    def close(self):
        channels.tails.append(list(self.tail))
        real_close(self)

    monkeypatch.setattr(LogSetup, "close", close)
    with spy_draw_text(monkeypatch) as calls:
        channels.draws = calls
        yield channels
