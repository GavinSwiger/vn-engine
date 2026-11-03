"""``install_replays``: F36's Endings and Scenes pages and scene replays wired into one launch
(F36 ``04-technical.md`` §3, §7.4, §7.5; ``07`` I-11).

Why this module exists: the Endings page (``ui/builtin/endings_page.py``) and the Scenes page
(``ui/builtin/scenes_page.py``) read the story only through ports, and the shell starts and
ends a replay only through an opaque request and a ``ReplayPort``, because ``ui`` never
imports ``script``, ``runtime`` or ``persist``. This module is those ports over the running
story (read through ``app.story`` on every call, so F39's reload is followed):

- ``AppEndingsPort``: every ending in script order (F19's ``interp.endings``), the reached
  ones (F12 kind ``"ending"``, kept until the store's unlocks or the program change), and
  ``replay_on`` (``[endings] replay``). ``start(name, by)`` replays the label the ending is
  in (``EndingInfo.label``); a ``lock replay`` of that label gives its ``to`` and starting
  values (``replay.run_for``). Extras comes back focused on the ending's row.
- ``AppScenesPort``: the declared replays (``Program.replays``), the unlocked ones (F12 kind
  ``"replay"``), a picture's source from the launch's ``ImageIndex`` (as the Gallery's), the
  launch's one ``ThumbCache``. ``start(label, by)`` replays that scene; Extras comes back
  focused on its tile.
- ``AppReplayPort`` (``shell.replays``): ``start(request)`` blocks saving and loading with
  ``replay_no_saving`` (F11's replay layer, the one gate, 07 I-11), then the driver's
  ``start_replay(run)`` (a fresh seed, or ``--seed``); ``stop()`` stops the replay if it
  still runs (End Replay; one that ended has already put the store back) and lifts the
  block.

A start is checked first: a label the story no longer has (a scene's or an ending's, after
an F39 reload) starts nothing (a log line), so ``new_game`` never meets an unknown label.

Two ``add_extras_page`` rows: ``endings`` (shown with ``[endings] list`` once a declared
ending is reached; kind ``"ending"``, names every ending) and ``replays`` (shown once a
declared replay is unlocked; kind ``"replay"``, names every scene).

Dev ``run --replay LABEL`` (``app.replay_label``): the shell's ``ShellPorts.replay`` is that
replay (page None), started in place of the first game; its end quits. A LABEL the story
doesn't have is a ``ReplayLabelError`` at launch, with did-you-mean.

This module imports ``engine.script`` only for type checking.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from engine.app.extras import add_extras_page
from engine.app.gallery import missing_ref
from engine.core.config import did_you_mean
from engine.core.errors import UserFacingError
from engine.core.logsetup import get_logger
from engine.runtime import replay as replay_mod
from engine.runtime.endings import ENDING_KIND
from engine.runtime.images import ImageFile, SolidColor
from engine.runtime.replay import REPLAY_KIND
from engine.ui.builtin import endings_page, scenes_page
from engine.ui.builtin.endings_page import EndingsPage
from engine.ui.builtin.scenes_page import ScenesPage
from engine.ui.menus import MenuEntry
from engine.ui.nav import InputKind
from engine.ui.shell import ReplayRequest

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.endings import EndingInfo
    from engine.runtime.images import ImageIndex
    from engine.runtime.interpreter import Interpreter
    from engine.script.replay import ReplayEntry
    from engine.ui.thumbs import ThumbCache

ENDINGS_PAGE: Final = endings_page.HEADING          # "endings"
SCENES_PAGE: Final = scenes_page.HEADING            # "replays"
NO_SAVING_WORD: Final = "replay_no_saving"

_log = get_logger("app")


class ReplayLabelError(UserFacingError):
    """Dev ``run --replay LABEL`` names a label the story doesn't have."""


def replay_label_text(label: str, labels: Iterable[str]) -> str:
    """The ``--replay`` launch error: the label, then did-you-mean (or a hint)."""
    text = f'There is no label named "{label}" to replay (--replay).'
    near = did_you_mean(label, labels)
    if near is not None:
        return text + f' Did you mean "{near}"?'
    return text + " Check the spelling, or add that label."


class _Cached:
    """A tuple kept until the program or the store's unlocks change (pages ask per frame)."""

    def __init__(self, make: "Callable[[Interpreter], tuple[str, ...]]") -> None:
        self._make = make
        self._kept: tuple[object, int, tuple[str, ...]] | None = None

    def get(self, interp: "Interpreter") -> tuple[str, ...]:
        program, gen = interp.program, interp.persistent.unlocks_gen
        kept = self._kept
        if kept is not None and kept[0] is program and kept[1] == gen:
            return kept[2]
        names = self._make(interp)
        self._kept = (program, gen, names)
        return names


class AppReplayPort:
    """``shell.replays`` (module docstring)."""

    def __init__(self, app: "App", interp: "Callable[[], Interpreter]") -> None:
        self._app = app
        self._interp = interp

    def request(self, page: str | None, key: object, label: str,
                by: InputKind) -> ReplayRequest | None:
        """The request replaying ``label`` (its declared ``to`` and values apply), or None
        when the story has no such label."""
        program = self._interp().program
        if label not in program.labels:
            _log.warning('The replay of "%s" didn\'t start: the story has no such label.',
                         label)
            return None
        return ReplayRequest(page, key, by, replay_mod.run_for(program, label))

    def start(self, request: ReplayRequest) -> None:
        shell = self._app.shell
        saves = getattr(self._app, "saves", None)
        if saves is not None and shell is not None:
            saves.set_replay_block(shell.words.get(NO_SAVING_WORD))
        story = getattr(self._app, "story", None)
        if story is not None:
            story.start_replay(request.run)                 # type: ignore[attr-defined]

    def stop(self) -> None:
        story = getattr(self._app, "story", None)
        if story is not None:
            story.stop_replay()                              # type: ignore[attr-defined]
        saves = getattr(self._app, "saves", None)
        if saves is not None:
            saves.set_replay_block(None)


class AppEndingsPort:
    """The Endings page's ``EndingsPort`` (module docstring)."""

    def __init__(self, interp: "Callable[[], Interpreter]", replays: AppReplayPort,
                 start: "Callable[[ReplayRequest], None]", *, replay_on: bool) -> None:
        self._interp = interp
        self._replays = replays
        self._start = start
        self._replay_on = replay_on
        self._reached = _Cached(
            lambda i: tuple(n for n in i.persistent.unlocked(ENDING_KIND) if i.endings.has(n)))

    @property
    def replay_on(self) -> bool:
        return self._replay_on

    def endings(self) -> "tuple[EndingInfo, ...]":
        return tuple(self._interp().endings)

    def reached(self) -> tuple[str, ...]:
        return self._reached.get(self._interp())

    def start(self, name: str, by: InputKind) -> None:
        if not self._replay_on:
            return
        info = self._interp().endings.get(name)
        if info is None:
            return
        request = self._replays.request(ENDINGS_PAGE, name, info.label, by)
        if request is not None:
            self._start(request)


class AppScenesPort:
    """The Scenes page's ``ScenesPort`` (module docstring)."""

    def __init__(self, interp: "Callable[[], Interpreter]", replays: AppReplayPort,
                 start: "Callable[[ReplayRequest], None]", images: "ImageIndex | None", *,
                 thumbs: "ThumbCache") -> None:
        self._interp = interp
        self._replays = replays
        self._start = start
        self.images = images
        self.thumbs = thumbs
        self._unlocked = _Cached(lambda i: tuple(
            e.label for e in i.program.replays if i.persistent.is_unlocked(REPLAY_KIND, e.label)))

    def replays(self) -> "tuple[ReplayEntry, ...]":
        return self._interp().program.replays

    def unlocked(self) -> tuple[str, ...]:
        return self._unlocked.get(self._interp())

    def picture(self, name: str) -> "str | tuple[int, int, int]":
        found = self.images.get(name) if self.images is not None else None
        if isinstance(found, ImageFile):
            return found.ref
        if isinstance(found, SolidColor):
            return found.rgb
        return missing_ref(name)

    def start(self, label: str, by: InputKind) -> None:
        request = self._replays.request(SCENES_PAGE, label, label, by)
        if request is not None:
            self._start(request)


def install_replays(app: "App", interp: "Interpreter",
                    images: "ImageIndex | None" = None) -> AppReplayPort:
    """The two Extras rows, the shell's replay port, and dev ``--replay`` (module
    docstring). After ``install_extras`` and ``install_saves``."""

    def live() -> "Interpreter":
        story = getattr(app, "story", None)
        found = getattr(story, "interp", None)
        return found if found is not None else interp

    shell = app.shell
    assert shell is not None, "install_replays needs the shell (install_ui runs first)"
    replays = AppReplayPort(app, live)
    shell.replays = replays
    config = app.config.endings
    endings = AppEndingsPort(live, replays, shell.start_replay, replay_on=config.replay)
    scenes = AppScenesPort(live, replays, shell.start_replay, images,
                           thumbs=app.extras.thumbs)                # type: ignore[attr-defined]
    add_extras_page(app, MenuEntry(ENDINGS_PAGE, page=lambda host: EndingsPage(endings),
                                   visible=lambda: config.list and bool(endings.reached())),
                    kind=ENDING_KIND, names=lambda: [e.name for e in live().endings])
    add_extras_page(app, MenuEntry(SCENES_PAGE, page=lambda host: ScenesPage(scenes),
                                   visible=lambda: bool(scenes.unlocked())),
                    kind=REPLAY_KIND, names=lambda: [e.label for e in live().program.replays])
    label = getattr(app, "replay_label", None)
    if label is not None:
        labels = interp.program.labels
        if label not in labels:
            raise ReplayLabelError(replay_label_text(label, labels))
        request = ReplayRequest(None, label, InputKind.KEYS,
                                replay_mod.run_for(interp.program, label))
        shell.ports = replace(shell.ports, replay=request)
    return replays


__all__ = ["AppEndingsPort", "AppReplayPort", "AppScenesPort", "ReplayLabelError",
           "install_replays", "replay_label_text"]
