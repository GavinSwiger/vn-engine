"""F32 looks in the app: the launch's checks, the three ``ui`` command handlers, and the
playthrough number (F32 ``04`` §6.2, §6.3, §6.6, §6.7; W204, W206, W207).

Why this module exists: ``ui/looks.py`` builds looks but reads no file and knows nothing of
saves or persistent data, and the runtime only says what changed (``UiStyle``, ``UiBlocks``,
``DeleteSaves``). Something in ``app`` has to check the look tables' fonts and pictures once,
hand the shell its ``Looks``, and turn the commands into F11 calls:

- **Launch** (``install_looks``, right after ``install_ui``): every font and image token of
  each ``[style.<name>]`` and ``[playthrough.N]`` table is checked (``AssetManager.check``,
  which logs nothing); a problem is W207 (area ``ui``) and that token is dropped from the
  copy ``Looks`` gets, so the ``[theme]`` value shows. Good non-title look images are held
  for the session (a style switch draws from the cache); title pictures never are. The shell
  gets the ``Looks`` and ``read_playthrough`` (``GameShell.set_looks`` chooses the launch
  look there). Step 5: the ``[theme]`` refs the parts use join ``LookChecks``
  (``check_base_refs``); the ``"textbox"`` and ``"choice"`` parts (``textbox_look``,
  ``choice_look``) are added, and the textbox and ``app.choices`` get the ``Looks``. Dev
  only: W67 for each table's look (``LOOK_PAIRS`` too, only the pairs its tokens touch) and
  W206 for each style no ``ui style`` line names.
- **Handlers**: ``UiStyle`` → ``Looks.set_style``, then the last ``UiBlocks`` again (a
  style may rename ``saving_off``); ``UiBlocks`` → ``SaveService.set_blocked`` with the
  reason or the current look's word; ``DeleteSaves`` → ``SaveService.delete_all``, except in
  a Studio preview or without saves (one INFO line, nothing deleted).
- **In-game reset** (New Game, the title, a load): no style, no blocks. So the title's Load
  page is never blocked (C4); a load's restore burst then sends the saved ones again.
- ``read_playthrough``: ``persistent.playthrough`` by ``peek`` with an exact ``int`` check;
  anything else is 0 with W204 once a session (the value's kind in words, never the value).
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from engine.app.choices import choice_look
from engine.app.text_check import textbox_look
from engine.app.ui_contrast import LOOK_PAIRS, PAIRS, contrast_warnings
from engine.core.config_schema import LookTable, ThemeConfig
from engine.core.logsetup import get_logger
from engine.runtime.commands import DeleteSaves, UiBlocks, UiStyle
from engine.runtime.errors import format_message
from engine.runtime.persistent import Missing
from engine.runtime.ui import DELETE_PREVIEW_TEXT, UiStatement
from engine.runtime.values import kind_words
from engine.ui.looks import Looks
from engine.ui.theme import UiTheme

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.interpreter import Interpreter
    from engine.runtime.persistent import PersistentStore

_log = get_logger("ui")

PLAYTHROUGH_NAME = "playthrough"
TITLE_AREA = "title"
_W207_KIND = {"font": "font", "image": "image"}


def ref_kind(path: str) -> str | None:
    """``"font"`` or ``"image"`` for a token path that names a file, else None."""
    last = path.rsplit(".", 1)[-1]
    if last.endswith("_font"):
        return "font"
    if last.endswith("_image"):
        return "image"
    return None


@dataclass
class LookChecks:
    """The look refs that can be used (W207 dropped the others); step 5's parts ask
    ``usable``. Base refs are asked through the same memoized ``AssetManager.check``."""
    fonts: set[str] = field(default_factory=set)
    images: set[str] = field(default_factory=set)
    held: list[str] = field(default_factory=list)

    def usable(self, ref: str, kind: str) -> bool:
        return ref in (self.fonts if kind == "font" else self.images)


def check_tables(assets, tables: Mapping[object, LookTable], section: str,
                 checks: LookChecks, log=_log) -> dict[object, LookTable]:
    """Each table with its unusable font and image tokens dropped (one W207 each)."""
    out: dict[object, LookTable] = {}
    for name in sorted(tables, key=str):
        table = tables[name]
        kept: dict[str, object] = {}
        for path, value in table.tokens.items():
            kind = ref_kind(path)
            if kind is None or not isinstance(value, str):
                kept[path] = value
                continue
            problem = assets.check(value, kind)
            if problem is None:
                (checks.fonts if kind == "font" else checks.images).add(value)
                if kind == "image" and not path.startswith(TITLE_AREA + "."):
                    checks.held.append(value)
                kept[path] = value
                continue
            area, key = path.rsplit(".", 1)
            what = "missing" if problem.kind == "missing" else _W207_KIND[kind]
            log.warning("%s", format_message("W207", (f"{section}.{name}.theme.{area}", key,
                                                      value, what, problem.suggestion)),
                        extra={"code": "W207"})
        out[name] = dataclasses.replace(table, tokens=MappingProxyType(kept))
    return out


BASE_REFS: tuple[tuple[str, str], ...] = (
    ("textbox.text_font", "font"), ("textbox.bold_font", "font"),
    ("textbox.italic_font", "font"), ("textbox.bold_italic_font", "font"),
    ("textbox.name_tab.text_font", "font"), ("textbox.frame_image", "image"),
    ("textbox.name_tab.frame_image", "image"), ("textbox.indicator.line_image", "image"),
    ("textbox.indicator.page_image", "image"), ("choice.text_font", "font"),
    ("choice.frame_image", "image"), ("choice.focused.frame_image", "image"))


def check_base_refs(assets, cfg: ThemeConfig, checks: LookChecks) -> None:
    """The ``[theme]`` refs the textbox and choice parts use, through the same memoized
    ``AssetManager.check`` the installs already asked (no log line): good ones join
    ``checks``, so building a part asks only sets (04 §6.2 step 1)."""
    for path, kind in BASE_REFS:
        node: object = cfg
        for name in path.split("."):
            node = getattr(node, name)
        if isinstance(node, str) and assets.check(node, kind) is None:
            (checks.fonts if kind == "font" else checks.images).add(node)


def add_parts(looks: Looks, checks: LookChecks, choices: object | None) -> None:
    """F32 step 5 (04 §6.2 step 3): the ``"textbox"`` and ``"choice"`` parts, both pure.
    The choice part keeps ``[theme.choice]``'s W48-checked sounds when a look doesn't set
    its own."""
    usable = checks.usable
    looks.add_part("textbox", lambda cfg: textbox_look(cfg, usable))
    base = looks.base.cfg.choice
    sounds = {key: (getattr(base, key), getattr(choices, key, getattr(base, key)))
              for key in ("focus_sound", "pick_sound")}
    looks.add_part("choice", lambda cfg: choice_look(cfg, looks.part("textbox").faces,
                                                     usable, sounds))


def read_playthrough(store: "PersistentStore | None", warned: list[bool]) -> int:
    """``persistent.playthrough`` (04 §6.3): an exact ``int`` as is; missing gives 0; any
    other value gives 0 and, the first time in the session, W204 with its kind in words."""
    if store is None:
        return 0
    value = store.peek(PLAYTHROUGH_NAME)
    if value is Missing:
        return 0
    if type(value) is int:
        return value
    if not warned[0]:
        warned[0] = True
        _log.warning("%s", format_message("W204", (kind_words(value),)),
                     extra={"code": "W204"})
    return 0


def look_warnings(looks: Looks, styles: Mapping[str, LookTable],
                  playthroughs: Mapping[int, LookTable]) -> list[str]:
    """W67 (dev) for each table's own look: ``(None, style)`` and ``(N, None)``, keeping the
    pairs that show a token the table sets (04 §6.7)."""
    out: list[str] = []
    base = looks.base
    for name in sorted(styles):
        table = styles[name]
        if table.tokens:
            theme = looks.look((None, name)).theme
            out += contrast_warnings(theme, pairs=PAIRS + LOOK_PAIRS,
                                     section=f"style.{name}.theme", only=set(table.tokens))
    for n in sorted(playthroughs):
        table = playthroughs[n]
        if table.tokens:
            theme = _with_title_pictures(looks.look((n, None)).theme, base)
            out += contrast_warnings(theme, pairs=PAIRS + LOOK_PAIRS,
                                     section=f"playthrough.{n}.theme", only=set(table.tokens))
    return out


def _with_title_pictures(theme: UiTheme, base: UiTheme) -> UiTheme:
    """``theme`` with ``logo``/``background`` standing for its own title pictures, so the
    title pairs drawn only without a picture are judged on this look's pictures."""
    title, base_title = theme.cfg.title, base.cfg.title
    logo = base.logo if title.logo_image == base_title.logo_image else \
        (True if title.logo_image is not None else None)
    background = base.background if title.background_image == base_title.background_image \
        else (True if title.background_image is not None else None)
    return UiTheme(theme.cfg, theme.faces, theme.frames, logo, background)   # type: ignore


def unused_styles(program, styles: Mapping[str, LookTable]) -> list[str]:
    """The style names no ``ui style`` line names, in name order (W206)."""
    used = {stmt.style for stmt in program.iter_statements()
            if isinstance(stmt, UiStatement) and stmt.form == "style"}
    return sorted(name for name in styles if name not in used)


class LookHandlers:
    """The three ``ui`` command handlers and the in-game reset (04 §6.6)."""

    def __init__(self, app: "App", looks: Looks) -> None:
        self.app = app
        self.looks = looks
        self.last_blocks: UiBlocks | None = None

    def _saves(self):
        return getattr(self.app, "saves", None)

    def on_style(self, cmd: UiStyle) -> None:
        self.looks.set_style(cmd.name)
        if self.last_blocks is not None:
            self.on_blocks(self.last_blocks)          # a style may rename saving_off

    def on_blocks(self, cmd: UiBlocks) -> None:
        self.last_blocks = cmd
        saves = self._saves()
        if saves is None:
            return
        saves.set_blocked(save=self._reason(cmd.save, cmd.save_reason, "saving_off"),
                          load=self._reason(cmd.load, cmd.load_reason, "loading_off"))

    def _reason(self, blocked: bool, reason: str | None, key: str) -> str | None:
        if not blocked:
            return None
        return reason if reason is not None else self.app.shell.words.get(key)

    def on_delete(self, cmd: DeleteSaves) -> None:
        saves = self._saves()
        if getattr(self.app, "editor_link", None) is not None or saves is None:
            _log.info("%s", DELETE_PREVIEW_TEXT)
            return
        saves.delete_all()

    def reset(self) -> None:
        """The in-game reset: no style and no blocks (C4)."""
        self.looks.set_style(None)
        self.last_blocks = None
        saves = self._saves()
        if saves is not None:
            saves.set_blocked(save=None, load=None)


def install_looks(app: "App", interp: "Interpreter") -> Looks:
    """Once per launch, right after ``install_ui`` (04 §6.2): W207 checks and holds, the
    shell's ``Looks`` (the launch look chosen), the three handlers, the in-game reset, and
    (dev) the looks' W67 rows and W206."""
    shell = app.shell
    assert shell is not None, "install_looks needs the shell (install_ui first)"
    config, assets = app.config, app.assets
    checks = LookChecks()
    styles = check_tables(assets, config.style, "style", checks)
    playthroughs = check_tables(assets, config.playthrough, "playthrough", checks)
    if checks.held:
        hold = assets.hold(dict.fromkeys(checks.held))
        app.add_shutdown(hold.release)
    looks = Looks(shell.base_theme, styles=MappingProxyType(styles),
                  playthroughs=MappingProxyType(playthroughs), overrides=shell.overrides,
                  image=assets.image)
    check_base_refs(assets, shell.base_theme.cfg, checks)
    choices = getattr(app, "choices", None)
    add_parts(looks, checks, choices)
    store = getattr(interp, "persistent", None)
    warned = [False]
    shell.set_looks(looks, lambda: read_playthrough(store, warned))
    textbox = getattr(app, "textbox", None)
    if textbox is not None:
        textbox.set_looks(looks)
    if choices is not None:
        choices.set_looks(looks)
    handlers = LookHandlers(app, looks)
    router = app.router
    router.register(UiStyle, handlers.on_style)
    router.register(UiBlocks, handlers.on_blocks)
    router.register(DeleteSaves, handlers.on_delete)
    shell.add_in_game_reset(handlers.reset)
    if app.dev:
        for text in look_warnings(looks, styles, playthroughs):
            _log.warning("%s", text, extra={"code": "W67"})
        for name in unused_styles(interp.program, styles):
            _log.warning("%s", format_message("W206", (name,)), extra={"code": "W206"})
    return looks


__all__ = ["BASE_REFS", "LookChecks", "LookHandlers", "add_parts", "check_base_refs",
           "check_tables", "install_looks", "look_warnings",
           "read_playthrough", "ref_kind", "unused_styles"]
