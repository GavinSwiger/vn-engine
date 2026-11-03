"""``install_achievements``: F37's achievements wired into one windowed launch (F37 ``SPEC.md``
§5.1, §5.3; F36 ``07-architecture-review.md`` I-13, I-15).

Why this module exists: the interpreter keeps achievements (``runtime/achievements.py``:
the ``"achievement"`` kind, registered in ``Interpreter.__init__``, and the ``when`` checks),
but the player must *see* each new one, the title's Extras must list them, and a store
(Steam and the like) may want to be told. ``ui`` never imports ``script``, ``runtime`` or
``persist``, and ``minigames`` never imports ``app``, so this module joins them:

- **The notice** (PR-F37-04): F12's unlock listener (``PersistentSync.add_unlock_listener``,
  main thread, once per new unlock) shows ``Achievement unlocked: <Title>`` (the
  ``achievement_unlocked`` word) with the achievement's icon through ``shell.notify(icon=)``,
  in the game and on the title alike; then the platform hook is told (``HookRunner.unlocked``:
  the notice first, SPEC §5.3). Two unlocks at one checkpoint come in declaration order
  (``check_pending``), so their notices stack in that order (F11). A name the story doesn't
  declare (an old file's) shows nothing. During a scene replay (F36, ``shell.replay``) the
  notice still shows and the hook is still told: achievements earned in a replay are kept
  (07 decision 2, ``replay_keeps``).
- **The icon**: a picture name through the launch's ``ImageIndex``: a file → its
  ``ImageRef``; a name with no picture → F04's placeholder (the notice draws its frame); a
  solid colour, or no ``image`` → no icon (the notice's own layout).
- **The hook** (§5.3): the launch's one ``HookRunner`` over the hook a plugin registered
  (``app.minigames.achievement_hook``; none: every call does nothing), guarded by the
  interpreter's watchdog guard. ``started(names)`` once, here, after the persistent read
  (``install_persistence`` ran before ``install_story``), with the declared achievements on
  file, in declaration order.
- **The Extras row** (PR-F37-05): ``add_extras_page`` ``achievements`` (shown once a declared
  achievement is unlocked, F34 D6; kind ``"achievement"``, names every declared one for F34's
  dev ``run --extras``, which unlocks them quietly: no notice, no hook call).

``AppAchievementsPort`` is the page's ``AchievementsPort``, read through ``app.story`` on
every call, so F39's reload is followed. This module imports ``engine.script`` only for type
checking.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from engine.app.extras import add_extras_page
from engine.app.gallery import missing_ref
from engine.minigames.achievement_hook import HookRunner
from engine.runtime.achievements import ACHIEVEMENT_KIND, AchievementInfo
from engine.runtime.images import ImageFile, SolidColor
from engine.ui.builtin import achievements_page
from engine.ui.builtin.achievements_page import AchievementsPage, unlocked_notice_text
from engine.ui.menus import MenuEntry

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.render.assets import ImageRef
    from engine.runtime.images import ImageIndex
    from engine.runtime.interpreter import Interpreter

ACHIEVEMENTS_PAGE: Final = achievements_page.HEADING        # "achievements"


class AppAchievementsPort:
    """The Achievements page's ``AchievementsPort`` (module docstring): every declared
    achievement in order, the unlocked names (kept until the program or the store's unlocks
    change; the page asks per frame), and an icon's source (a file ref, a solid colour, or
    F04's placeholder file for a name with no picture)."""

    def __init__(self, interp: "Callable[[], Interpreter]",
                 images: "ImageIndex | None") -> None:
        self._interp = interp
        self.images = images
        self._kept: tuple[object, int, tuple[str, ...]] | None = None

    def achievements(self) -> tuple[AchievementInfo, ...]:
        return tuple(self._interp().achievements.index)

    def unlocked(self) -> tuple[str, ...]:
        interp = self._interp()
        program, gen = interp.program, interp.persistent.unlocks_gen
        kept = self._kept
        if kept is not None and kept[0] is program and kept[1] == gen:
            return kept[2]
        names = tuple(info.name for info in interp.achievements.index.unlocked(interp.persistent))
        self._kept = (program, gen, names)
        return names

    def icon(self, image: str) -> "str | tuple[int, int, int] | None":
        found = self.images.get(image) if self.images is not None else None
        if isinstance(found, ImageFile):
            return found.ref
        if isinstance(found, SolidColor):
            return found.rgb
        return missing_ref(image)


class AchievementNotices:
    """The unlock listener (module docstring): a notice, then the hook."""

    def __init__(self, app: "App", interp: "Callable[[], Interpreter]",
                 port: AppAchievementsPort, runner: HookRunner) -> None:
        self._app = app
        self._interp = interp
        self._port = port
        self.runner = runner

    def icon(self, info: AchievementInfo) -> "ImageRef | None":
        """The notice's icon: an ``ImageRef`` (a placeholder for a name with no picture), or
        None (no ``image``, or a solid colour)."""
        if info.image is None:
            return None
        source = self._port.icon(info.image)
        if not isinstance(source, str):
            return None
        return self._app.assets.image(source)

    def __call__(self, kind: str, name: str) -> None:
        if kind != ACHIEVEMENT_KIND:
            return
        info = self._interp().achievements.index.get(name)
        if info is None:
            return
        shell = self._app.shell
        if shell is not None:
            shell.notify(unlocked_notice_text(shell.words, info.title), icon=self.icon(info))
        self.runner.unlocked(name)


def install_achievements(app: "App", interp: "Interpreter",
                         images: "ImageIndex | None" = None) -> AchievementNotices:
    """The unlock notice and hook, ``HookRunner.started``, and the Extras row (module
    docstring). After ``install_extras``; the ``"achievement"`` kind is the interpreter's."""

    def live() -> "Interpreter":
        story = getattr(app, "story", None)
        found = getattr(story, "interp", None)
        return found if found is not None else interp

    port = AppAchievementsPort(live, images)
    registry = getattr(app, "minigames", None)
    runner = HookRunner(getattr(registry, "achievement_hook", None), guard=interp.guard)
    notices = AchievementNotices(app, live, port, runner)
    persist = getattr(app, "persist", None)
    if persist is not None:
        persist.add_unlock_listener(notices)
    runner.started(tuple(info.name for info in interp.achievements.index.unlocked(
        interp.persistent)))
    add_extras_page(app, MenuEntry(ACHIEVEMENTS_PAGE, page=lambda host: AchievementsPage(port),
                                   visible=lambda: bool(port.unlocked())),
                    kind=ACHIEVEMENT_KIND,
                    names=lambda: [info.name for info in live().achievements.index])
    app.achievements = notices                       # type: ignore[attr-defined]
    return notices


__all__ = ["ACHIEVEMENTS_PAGE", "AchievementNotices", "AppAchievementsPort",
           "install_achievements"]
