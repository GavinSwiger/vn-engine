"""``SaveService`` (``App.saves``) and ``install_saves``: saving and loading in the running
game (F11 ``04-technical.md`` §5.2, §7.1, §7.3, §7.4, §7.6, §7.8 step 5, §12; ``07`` I-1,
I-3, I-7; SPEC step 8).

Why this module exists: a save must never cost the player a frame or a slot. So the state is
read at the checkpoint the player sees, encoded on the main thread in ≤ 4 ms slices
(``SaveEncoder``; a worker can't read ``GameState``, ADR-0007), and written by the one
``App.writer`` as the ``save`` owner (F16 ``07`` §3): this module starts no thread and
never writes a file itself. A load reads the slot once, restores while the menus are still
up (the story hold keeps the burst), and only then closes them (C8): a refused load changes
nothing and says why in a notice.

Install (§7.1, from ``install_story`` after ``install_ui``): a release run without
``[game] id`` has no saves (W80, entries hidden, F5/F9 do nothing, no file call); otherwise
the ``saves`` root must be a real folder (``ensure_real_dir``; else W81 once: nothing is read
there and every save fails with the folder reason), the ``save`` writer client is registered,
stale temps are removed, the entries and the ``QuickKeys`` overlay are added, and the slot
``IndexJob`` starts.

Per frame (``update``, I-3: every mode but error mode, minimized wakes included): the
writer's results first (index, notice, W83), then the index, then the oldest save job's
encoding (only while fewer than 2 of F11's writes are pending), each until ``SAVE_STEP_S``.

Quick keys: F5 (no Ctrl/Alt/Meta) saves to the Quick page's rotation target with a
"Quick saved." notice once written; F9 loads the newest quick save after
``confirm_load`` (unless ``[saves] confirm_quick_load = false``). Both work only while an
in-game screen is top (the overlay sits on F05's textbox; F07's choice screen passes them on).

Quit (§7.8 steps 4–5, C9): the quit guard first encodes and submits every job still
waiting (so a requested save isn't lost to the quit), then makes the quit save;
``submit_final`` submits every encoded job; ``wait_final(until)``
waits on the shared deadline and ``finish`` logs W83 for failures and jobs the quit didn't
wait for.

Pages (step 9, ``04`` §7.7): ``SaveSlots`` is the pages' ``SlotsPort``. It turns persist's
heads into ``SlotView``s (render-safe text cut to 100 code points, the local date, Newest on
Auto and Quick), reads the shown page's six heads one per ``update`` (unread cells are
"Loading…"; a save in flight wins over a read), and decodes their thumbnails lazily into
``assets.cache`` as ``("save-thumb", slot, stamp)``, held while the page shows. ``save_to``
saves into a numbered slot; ``load_from`` asks first in game (``confirm_load``), shows the
cell's "Loading…" badge for one frame, then loads; ``delete`` waits for that slot's
outstanding save, then removes the entry on the main thread (``safefile.remove_file``).

Auto-saves (step 10, §7.8 steps 1–4, C5, C6, ``07`` I-2, I-3): in mode GAME and not blocked,
the timer runs while the story may run (not under menus, on the title, or minimized; skip
counts). Each new checkpoint is looked at once: one restored by a load, or already
auto-saved, never is; otherwise a pending ``request_autosave()`` (F18, F14: armed for exactly
the next new checkpoint, which clears it either way, F18 ``07`` I-6), a checkpoint waiting at
choices (``[saves] autosave_choices``), or the timer at ``autosave_interval`` (> 0) makes one
Auto save (rotation), which resets the timer. A load, New Game, and the title reset the timer
and the request. With ``[saves] autosave_quit`` and ``can_save()``, Main Menu → Yes
(``add_before_title``: the kept thumbnail; written during the black fade) and a quit (the
quit guard after F10's: ``autosave_now("quit")`` encodes at once and submits, never writes)
make an Auto save, and the Main Menu and Quit questions drop "Unsaved progress will be lost."
(``set_confirm_key``). ``set_blocked`` (F23, F32) blocks saving or loading with a reason the
pages show; while saving is blocked ``can_save()`` is False and F5, the timer, and auto-saves
do nothing (F9 likewise while loading is blocked). F36's ``set_replay_block`` blocks both for a
whole scene replay with ``replay_no_saving``, a layer ``set_blocked`` can't lift (``_reason``).

Load polish (step 11, §7.6 steps 2–6 and the table): the read is checked with
``restore(check_only=True)`` before anything changes; a saved line that is gone is looked
for by F03's location hint (``use_hints=True``), and if a line is there the player is asked
``confirm_nearest`` (Yes loads with hints; No changes nothing). Only the commit changes the
game; on OK ``shell.show_loaded_game()`` closes every menu and fades the game in
(``LoadFadeScreen``). Every refusal is a ``[words]`` notice, never file text, plus W82 in
dev runs (``couldn't load <slot label>: <reason>``; labels and saved names through
``echo()``). A page load of a file over 1 MiB also draws F10's loading indicator in the
badge frame (G3, ``SaveSlots.load_indicator``).

Seams (``04`` §5.2; ``07`` I-4): ``add_load_listener`` (F14, F15: run once per successful
load, never on a failed one), ``note_restore`` (F14: the checkpoint its restore landed on is
never auto-saved), ``set_chapter_provider`` (F18: the save's ``chapter`` and description;
``install_saves`` sets the story's ``ChapterIndex.save_label`` of the checkpoint's chapter,
which F18's ``install_chapters`` may replace, or clear with None for ``name_saves = false``),
``delete_all`` (F12/F16 "delete all data", F32: every slot name of this game's pages, 16 per
frame, each waiting for its own outstanding save; saving is off while it runs and ``delete``
raises), and ``refresh`` (F39: re-index, re-read the shown page). F14 never puts rollback
history in a save (only ``driver.checkpoint()`` is saved). F20's second writer owner can't
delay these writes (the pending count is F11's own). F23 (``04`` §7.8):
``set_minigame_title_provider`` (asked first, with the waiting minigame's name, for the
description of a save made while the state waits at a minigame); the thumbnail comes from
the shell's ``set_thumbnail_source``.

F20 (``07`` I-3): ``load_state`` is steps 4–6 on a state already read (the slot load is
``read_slot_full`` + it; a flowchart jump passes ``fresh_menu``, ``before_commit``, and
``on_result``); ``autosave_now("jump")`` is the quit auto-save for a jump; ``encoding``
tells F20 not to encode or submit in a frame where F11 encodes.
"""

import itertools
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import pygame

from engine.core import safefile
from engine.core.constants import ENTRY_OVERHEAD
from engine.core.logsetup import get_logger
from engine.core.paths import display_path
from engine.core.redact import echo
from engine.persist import limits
from engine.persist import saves as fmt
from engine.persist.location import saves_root
from engine.persist.saves import (Cause, IndexJob, SaveEncoder, SaveMeta, SlotHead, SlotId,
                                  SlotStatus, TooLarge)
from engine.persist.writer import (DISK_FULL, FOLDER_IS_LINK, NO_PERMISSION, Failed, FileWrite,
                                   FileWritten, WriterClient)
from engine.render.thumbnail import decode_jpeg, encode_jpeg
from engine.runtime.interpreter import RestoreOutcome, RestoreResult
from engine.runtime.state import STATE_FORMAT, GameState
from engine.ui.builtin.save_page import SlotView, register_save_pages
from engine.ui.input import UiEvent
from engine.ui.menus import EntryContext, MenuEntry
from engine.ui.nav import InputKind
from engine.ui.notice import clean_text
from engine.ui.shell import Mode

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.render.canvas import Canvas
    from engine.ui.shell import GameShell

_log = get_logger("save")

SaveKind = Literal["quick", "auto", "slot"]
LoadOrigin = Literal["title", "game", "quick"]

# W80, W81 (04 §12): fixed texts; W81's path is a display path (SEC-F11-09).
W80_TEXT = "saving is off: a release run needs [game] id in config.toml"
W81_PREFIX = "saves can't be written this session: the save folder "
FOLDER_LINK = "is a link"
FOLDER_NOT_REAL = "is not a real folder"
FOLDER_NOT_CREATED = "couldn't be created"
QUIT_DIDNT_WAIT = "the quit didn't wait for it"
SHOWN_TEXT_MAX = 100                 # §7.7: a save's text on screen, then "…"
DATE_FORMAT = "%Y-%m-%d %H:%M"
PICTURES_KEPT = 12                   # written pictures shown until their slot is re-read
LOAD_INDICATOR_BYTES = 1 << 20       # G3: a page load of a larger file shows F10's indicator
WIPE_PER_FRAME = 16                  # delete_all: entries removed per frame (§7.7)
# W82 reasons of §7.6's table that F11 words itself (persist words the read's).
NEAREST_OFFERED = "; offering the nearest point"
NO_NEARBY_POINT = " and no nearby point was found"

_BLOCKING_MODS = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI
_PENDING_WRITES_MAX = 2              # encode the next job only while fewer are pending (§7.3)


class _Keep:
    """``set_blocked``'s default: leave that mode's reason as it is."""

    def __repr__(self) -> str:
        return "KEEP"


KEEP: Final = _Keep()


def w83_text(label: str, reason: str) -> str:
    """W83: ``couldn't save to <slot label>: <reason>``."""
    return f"couldn't save to {echo(label)}: {reason}"


def w83_delete_text(label: str, reason: str) -> str:
    """W83: ``couldn't delete <slot label>: <reason>`` (§7.7 Delete)."""
    return f"couldn't delete {echo(label)}: {reason}"


def w82_text(label: str, reason: str) -> str:
    """W82 (dev runs): ``couldn't load <slot label>: <reason>`` (§7.6's table)."""
    return f"couldn't load {echo(label)}: {reason}"


def position_reason(state: GameState, tail: str) -> str:
    """W82's reason for a saved line that is gone: ``the saved line in label <label>
    (statement <path>) is gone`` + ``tail``; the saved label and path through ``echo()``
    (SEC-F11-09b: a hostile 500-character label stays ≤ 120 characters, escaped)."""
    label, path = state.position_at
    where = ".".join(str(part) for part in path)
    return (f"the saved line in label {echo(str(label))} (statement {echo(where)}) "
            f"is gone{tail}")


def shown_text(text: str) -> str:
    """§7.7 render-safe text (PR-F11-20, SEC-F11-03): ``Cc``, ``Cf`` (but ZWJ), ``Zl``,
    ``Zp`` removed, lone surrogates as U+FFFD, F05's ``render_safe``; cut to 100 code
    points plus "…". The page draws it as plain text."""
    cleaned = clean_text(text, SHOWN_TEXT_MAX + 1)
    return cleaned if len(cleaned) <= SHOWN_TEXT_MAX else cleaned[:SHOWN_TEXT_MAX] + "…"


def shown_date(saved_at: int) -> str:
    """``2026-11-01 21:04`` in local time; empty when the platform can't convert it."""
    try:
        return time.strftime(DATE_FORMAT, time.localtime(saved_at))
    except (OverflowError, OSError, ValueError):
        return ""


# --- Jobs ------------------------------------------------------------------------------------

@dataclass(eq=False)
class SaveJob:
    """One requested save: chosen slot, the checkpoint read at capture time, its picture,
    and the optimistic head the index shows until the write's result arrives."""

    slot: SlotId
    kind: SaveKind
    state: GameState
    picture: "pygame.Surface | None"
    head: SlotHead
    order: int                        # this session's write order (ties of ``seq``)
    token: int
    shown: "pygame.Surface | None" = None    # the picture a page shows until it is re-read
    encoder: SaveEncoder | None = None
    pieces: tuple[bytes, ...] | None = field(default=None, repr=False)


# --- The service -----------------------------------------------------------------------------

class SaveService:
    """``App.saves``. Main thread only. ``available`` is False in a release run without
    ``[game] id`` (W80) and in an App without a game folder or writer."""

    def __init__(self, app: "App", shell: "GameShell", *, folder: Path | None,
                 folder_ok: bool, client: WriterClient | None, release: bool,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        config = app.config
        self.app = app
        self.shell = shell
        self.folder = folder
        self.folder_ok = folder_ok
        self.client = client
        self.release = release
        self.available = client is not None and folder is not None
        self.game_id = config.game.id
        self.game_version = config.game.version
        self.pages = config.saves.pages
        self.confirm_quick_load = config.saves.confirm_quick_load
        self._clock = clock
        self.heads: dict[SlotId, SlotHead] = {}       # non-EMPTY slots known on disk
        self.order: dict[SlotId, int] = {}            # completed writes' session order
        self.skip: set[SlotId] = set()                # writes failed this session (SEC-F11-05)
        self.index: IndexJob | None = None
        if self.available and folder_ok:
            assert folder is not None
            self.index = IndexJob(folder, game_id=self.game_id, pages=self.pages)
        self._jobs: deque[SaveJob] = deque()          # waiting to be encoded / submitted
        self._sent: dict[int, SaveJob] = {}           # submitted, result not yet taken
        self._latest: dict[SlotId, SaveJob] = {}      # newest outstanding job per slot
        self._outstanding: dict[SlotId, int] = {}
        self._captures = 0                            # capture requests not yet served
        self._last_encoder: SaveEncoder | None = None
        self._tokens = itertools.count(1)
        self._orders = itertools.count(1)
        self._load_waiting: tuple[SlotId, LoadOrigin, InputKind] | None = None
        self._load_badge = False                      # a page load: one frame for the badge
        self._load_big = False                        # ... of a file over 1 MiB (G3)
        self._deleting: set[SlotId] = set()           # deletes waiting for a slot's save
        self._wipe: deque[SlotId] = deque()           # delete_all: slots left, in order
        self._wiping: set[SlotId] = set()             # ... shown Empty until removed
        self.pictures: OrderedDict[SlotId, tuple[object, pygame.Surface]] = OrderedDict()
        # F32 (step 10's ``set_blocked``): a reason shown in place of a page, per mode.
        self._blocked: dict[str, str | None] = {"save": None, "load": None}
        self._replay_block: str | None = None         # F36: both modes, over _blocked
        self.slots = SaveSlots(self)
        # Seams: the checkpoint a load or ``note_restore`` restored (never auto-saved), the
        # load listeners (``add_load_listener``), F18's chapter provider.
        self._restored_cp: GameState | None = None
        self._load_listeners: list[Callable[[], None]] = []
        self._chapter_provider: Callable[[GameState], str | None] | None = None
        self._minigame_title: Callable[[str], str | None] | None = None      # F23 §7.8
        # Auto-saves (§7.8 steps 1–4): seconds of play since the last auto-save, the last
        # checkpoint looked at, the last one auto-saved, and F18's one-checkpoint request.
        self.autosave_interval = config.saves.autosave_interval
        self.autosave_choices = config.saves.autosave_choices
        self.autosave_quit = config.saves.autosave_quit
        self.timer = 0.0
        self._last_cp: GameState | None = None
        self._autosaved_cp: GameState | None = None
        self._autosave_requested = False

    # --- what can be done ---------------------------------------------------------------------

    def _error_mode(self) -> bool:
        return bool(getattr(self.app, "error_mode", False))

    def can_save(self, *, quitting: bool = False) -> bool:
        """PR-F11-14: in game (mode GAME, no run-time error) at a checkpoint, with saves
        available, not blocked, and no ``delete_all`` running (I-4). Disabled Q.Save look;
        F5 shows ``notice_cant_save`` otherwise (but does nothing while blocked). F30 (C5,
        07 I-6): False while a ``private_picture`` screen (the fake crash) is on the stack,
        unless ``quitting`` (the quit save, which then has no picture)."""
        if (not self.available or self._error_mode() or self.shell.mode is not Mode.GAME
                or self._reason("save") is not None or self._wipe):
            return False
        if not quitting and self._picture_private():
            return False
        driver = self.app.story
        return driver is not None and driver.checkpoint() is not None

    def _picture_private(self) -> bool:
        private = getattr(self.shell, "picture_private", None)
        return bool(private()) if private is not None else False

    def set_blocked(self, *, save: "str | None | _Keep" = KEEP,
                    load: "str | None | _Keep" = KEEP) -> None:
        """F23, F32: block saving and/or loading with a reason the Save or Load page shows in
        place of its grid; None unblocks; an omitted mode keeps its state. While saving is
        blocked, ``can_save()`` is False and F5, the timer, and auto-saves do nothing; while
        loading is blocked F9 does nothing."""
        for mode, reason in (("save", save), ("load", load)):
            if isinstance(reason, _Keep):
                continue
            if reason is not None and not isinstance(reason, str):
                raise TypeError(f"set_blocked: {mode} takes a str or None, not "
                                f"{type(reason).__name__}")
            self._blocked[mode] = reason

    def set_replay_block(self, reason: str | None) -> None:
        """F36 (04 §7.4, 07 I-11): while a scene replay runs, saving and loading are both
        blocked with ``reason`` (``replay_no_saving``), a layer over ``set_blocked`` that F32's
        ``ui saving on``/``ui loading on`` can't lift; None lifts it (what ``set_blocked``
        set shows again). The one gate of saving in a replay: the hidden menu entries are
        cosmetic."""
        if reason is not None and not isinstance(reason, str):
            raise TypeError(f"set_replay_block takes a str or None, not "
                            f"{type(reason).__name__}")
        self._replay_block = reason

    def _reason(self, mode: str) -> str | None:
        """Why ``mode`` (``"save"``/``"load"``) is blocked now: the replay's reason first,
        else ``set_blocked``'s; None: not blocked. Every block check reads this."""
        replay = self._replay_block
        return replay if replay is not None else self._blocked.get(mode)

    # --- requests -----------------------------------------------------------------------------

    def quick_save(self, by: InputKind | None = None) -> None:
        """F5 and Q.Save: save to the Quick page's rotation target (PR-F11-09)."""
        if not self.available or self._reason("save") is not None:
            return
        self._request("quick")

    def quick_load(self, by: InputKind = InputKind.KEYS) -> None:
        """F9 and Q.Load: the newest quick save, after ``confirm_load`` unless
        ``[saves] confirm_quick_load = false``; none → ``No quick save yet.``"""
        if (not self.available or self._error_mode() or self.app.story is None
                or self._reason("load") is not None):
            return
        slot = self.newest_quick()
        if slot is None:
            self.shell.notify(self.shell.words.get("notice_no_quick_save"), kind="info")
            return
        if self.confirm_quick_load:
            self.shell.confirm(self.shell.words.get("confirm_load"),
                               lambda: self._load_later_or_now(slot, "quick", by), by=by)
        else:
            self._load_later_or_now(slot, "quick", by)

    def save_to(self, slot: SlotId) -> None:
        """The Save page: save into numbered ``slot`` (the page asked first if it held
        anything). Auto and Quick slots are chosen by rotation only (§12)."""
        if type(slot.page) is not int:
            raise ValueError(f"save_to takes a numbered slot, not {slot.page!r}")
        if self.available:
            self._request("slot", slot)

    def load_from(self, slot: SlotId, by: InputKind, *, origin: LoadOrigin) -> None:
        """The Load page (§7.6 steps 1–2): in game ``confirm_load`` first; from the title at
        once. The cell's "Loading…" badge is drawn for a frame, then the slot is loaded (a
        save still being written to it first finishes)."""
        if (not self.available or self._error_mode() or self.app.story is None
                or self._reason("load") is not None):
            return
        if origin == "title":
            self._start_load(slot, origin, by)
            return
        self.shell.confirm(self.shell.words.get("confirm_load"),
                           lambda: self._start_load(slot, origin, by), by=by)

    def _start_load(self, slot: SlotId, origin: LoadOrigin, by: InputKind) -> None:
        """§7.6 step 2: the badge frame first; a file over 1 MiB (by the head's stamp) also
        shows F10's loading indicator in it (G3)."""
        stamp = self.view(slot).stamp
        self._load_waiting = (slot, origin, by)
        self._load_badge = True
        self._load_big = stamp is not None and stamp.size > LOAD_INDICATOR_BYTES

    @property
    def loading_slot(self) -> SlotId | None:
        """The slot a load is waiting on (a page load: its cell shows the badge and the
        page takes no input)."""
        return self._load_waiting[0] if self._load_waiting is not None else None

    def delete(self, slot: SlotId) -> None:
        """§7.7 Delete (after ``confirm_delete``): the cell shows Empty at once; a save still
        queued or being written to the slot finishes first; then the entry goes. A delete
        while ``delete_all`` runs is a programmer error (§12)."""
        if self._wipe:
            raise ValueError("SaveService.delete: delete_all is running")
        if not self.available:
            return
        self._deleting.add(slot)
        if slot not in self._latest:
            self._remove(slot)

    def _remove(self, slot: SlotId) -> None:
        """``safefile.remove_file`` on the main thread (SEC-F11-08): a file or link entry
        goes, never a folder's contents. A failure shows the old contents again, the notice,
        and W83."""
        self._deleting.discard(slot)
        self._wiping.discard(slot)
        if self.folder_ok and self.folder is not None:
            outcome = safefile.remove_file(self.folder / slot.file_name())
        else:
            outcome = safefile.RemoveKind.FAILED
        if outcome.gone:
            self.heads.pop(slot, None)
            self.order.pop(slot, None)
            self.pictures.pop(slot, None)
            return
        _log.warning("%s", w83_delete_text(self.slot_label(slot), outcome.value),
                     extra={"code": "W83"})
        self._notice("notice_delete_failed")

    def _request(self, kind: SaveKind, slot: SlotId | None = None) -> bool:
        """§7.3 Request: refuse (``notice_cant_save``) when saving isn't possible or
        ``MAX_REQUESTS`` wait; else ask the shell for this scene's picture."""
        if not self.can_save() or self._waiting() >= limits.MAX_REQUESTS:
            self._notice("notice_cant_save")
            return False
        self._captures += 1
        self.shell.capture_scene(lambda picture: self._captured(kind, slot, picture))
        return True

    def _waiting(self) -> int:
        return self._captures + len(self._jobs) + len(self._sent)

    def _captured(self, kind: SaveKind, slot: SlotId | None,
                  picture: "pygame.Surface | None") -> None:
        """§7.3 ``then(picture)``: the checkpoint now, the slot (rotation), ``seq``, the
        optimistic view, and the job."""
        self._captures -= 1
        driver = self.app.story
        state = driver.checkpoint() if driver is not None and not self._error_mode() else None
        if state is None:
            self._notice("notice_cant_save")
            return
        self.finish_index()
        if slot is None:
            page: Literal["auto", "quick"] = "auto" if kind == "auto" else "quick"
            heads = self._reread_page(page)
            n = fmt.rotation_target(heads, skip=self.skip, order=self._order_view())
            if n is None:
                self._notice_failed("save_reason_slots")
                return
            slot = SlotId(page, n)
        seq = fmt.next_seq(self._all_views())
        saved_at = min(max(int(time.time()), 0), limits.SAVED_AT_MAX)
        chapter = self._chapter(state)
        title = self._minigame_title_of(state)
        description = title if title is not None else fmt.describe(state, chapter)
        if chapter is not None:
            chapter = chapter[:limits.DESCRIPTION_MAX]       # as the encoder writes it
        meta = SaveMeta(seq=seq, saved_at=saved_at,
                        description=description[:limits.DESCRIPTION_MAX], chapter=chapter,
                        game=self.game_id, game_version=self.game_version,
                        state_format=STATE_FORMAT, thumb_len=1, state_len=1)
        head = SlotHead(slot, SlotStatus.OK, None, meta, None, None, "")
        job = SaveJob(slot, kind, state, picture, head, next(self._orders), next(self._tokens),
                      shown=picture)
        self._jobs.append(job)
        self._latest[slot] = job
        self._outstanding[slot] = self._outstanding.get(slot, 0) + 1

    def _minigame_title_of(self, state: GameState) -> str | None:
        """F23 (``04`` §7.8): the waiting minigame's display title from the provider (asked
        only with the name of the state's wait), a non-blank ``str``, else None."""
        provider = self._minigame_title
        waiting = getattr(getattr(state, "minigame", None), "waiting", None)
        if provider is None or waiting is None:
            return None
        title = provider(waiting.name)
        return title if type(title) is str and title.strip() else None

    def _chapter(self, state: GameState) -> str | None:
        """F18's chapter for the description and meta (``set_chapter_provider``): a
        non-blank ``str``, else None (the description is then the line)."""
        provider = self._chapter_provider
        chapter = provider(state) if provider is not None else None
        return chapter if type(chapter) is str and chapter.strip() else None

    # --- the index and views (§7.4) -----------------------------------------------------------

    def finish_index(self) -> None:
        """A save or load needs the whole index: finish it now (≤ 612 × 0.16 ms)."""
        index = self.index
        if index is not None and not index.done:
            index.finish()
        self._take_index()

    def _take_index(self) -> None:
        index = self.index
        if index is not None and index.done:
            for slot, head in index.heads.items():
                self.heads.setdefault(slot, head)
            self.index = None

    def view(self, slot: SlotId) -> SlotHead:
        """What a page shows of ``slot``: EMPTY while it is being deleted; else its newest
        outstanding save's optimistic head, else the head known on disk, else EMPTY."""
        if slot in self._deleting or slot in self._wiping:
            return SlotHead(slot, SlotStatus.EMPTY, None, None, None, None, "")
        job = self._latest.get(slot)
        if job is not None:
            return job.head
        head = self.heads.get(slot)
        return head if head is not None else SlotHead(slot, SlotStatus.EMPTY, None, None, None,
                                                      None, "")

    def known_views(self) -> list[SlotHead]:
        """Every slot's ``view`` that isn't EMPTY (index, reads, saves in flight)."""
        slots = set(self.heads) | set(self._latest)
        return [view for slot in slots
                if (view := self.view(slot)).status is not SlotStatus.EMPTY]

    def _all_views(self) -> list[SlotHead]:
        views = dict(self.heads)
        for slot, job in self._latest.items():
            views[slot] = job.head
        return list(views.values())

    def _order_view(self) -> dict[SlotId, int]:
        order = dict(self.order)
        for slot, job in self._latest.items():
            order[slot] = job.order
        return order

    def _reread_page(self, page: Literal["auto", "quick"]) -> list[SlotHead]:
        """The page's 6 heads read again (a file planted since the index counts), with
        outstanding saves' optimistic views winning (§7.7 "Reading")."""
        out = []
        for slot in fmt.page_slots(page):
            if slot in self._latest:
                out.append(self._latest[slot].head)
                continue
            head = self._read_head(slot)
            if head.status is SlotStatus.EMPTY:
                self.heads.pop(slot, None)
            else:
                self.heads[slot] = head
            out.append(head)
        return out

    def _read_head(self, slot: SlotId) -> SlotHead:
        if not self.folder_ok or self.folder is None:     # a link folder is never read (W81)
            return SlotHead(slot, SlotStatus.EMPTY, None, None, None, None, "")
        return fmt.read_slot_head(self.folder, slot, game_id=self.game_id, thumb=False,
                                  max_bytes=limits.META_MAX)

    def newest_quick(self) -> SlotId | None:
        """Q.Load's target: the OK quick slot with the highest (``seq``, session order)."""
        self.finish_index()
        views = [self.view(slot) for slot in fmt.page_slots("quick")]
        return fmt.newest(views, order=self._order_view())

    @property
    def encoding(self) -> bool:
        """F20 (``07`` I-3): a save is waiting for its picture or its pieces aren't ready,
        so this frame's encoding belongs to F11 (no node state is encoded or submitted)."""
        return self._captures > 0 or any(job.pieces is None for job in self._jobs)

    # --- the frame slot (C9, I-3) -------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Results, then the index, then encoding, until ``SAVE_STEP_S`` has passed."""
        if not self.available:
            return
        clock = self._clock
        deadline = clock() + limits.SAVE_STEP_S
        self._autosave_step(dt)
        self._take_results()
        index = self.index
        if index is not None:
            index.step(deadline, clock)
            self._take_index()
        while self._jobs and clock() < deadline:
            client = self.client
            assert client is not None
            if client.pending >= _PENDING_WRITES_MAX:
                break
            job = self._jobs[0]
            if not self._encode(job, deadline, clock):
                break
            self._jobs.popleft()
            self._submit(job)
        self._take_results()
        for slot in [s for s in self._deleting if s not in self._latest]:
            self._remove(slot)
        if self._wipe:
            self._wipe_step()
        self.slots.step()
        waiting = self._load_waiting
        if waiting is not None and waiting[0] not in self._latest:
            if self._load_badge:
                self._load_badge = False              # this frame draws the badge first
            else:
                self._load_waiting = None
                self._load_big = False
                self._load(*waiting)

    # --- auto-saves (§7.8 steps 1–4; C5, C6; I-2, I-3) ----------------------------------------

    def request_autosave(self) -> None:
        """F18 (a chapter), F14: arm one Auto save for exactly the next new checkpoint. That
        checkpoint clears the request whether it is saved or skipped (restored by a load,
        or already auto-saved; F18 ``07`` I-6); a load, New Game, and the title clear it
        too. Calling it again before then changes nothing."""
        if self.available:
            self._autosave_requested = True

    @property
    def autosave_pending(self) -> bool:
        """Whether a ``request_autosave()`` waits for its checkpoint."""
        return self._autosave_requested

    def _autosave_step(self, dt: float) -> None:
        """§7.8 steps 1–2, at the top of ``update``: in mode GAME, not blocked (error mode
        never reaches ``update``)."""
        if (self.shell.mode is not Mode.GAME or self._error_mode()
                or self._reason("save") is not None or self._wipe):
            return
        app = self.app
        if not getattr(app, "minimized", False) and self.shell.stack.story_may_run():
            self.timer += dt                         # menus and the title hold it; skip counts
        driver = app.story
        cp = driver.checkpoint() if driver is not None else None
        if cp is None or cp is self._last_cp:
            return
        self._last_cp = cp
        requested, self._autosave_requested = self._autosave_requested, False
        if cp is self._restored_cp or cp is self._autosaved_cp:
            return
        interval = self.autosave_interval
        if (requested or (self.autosave_choices and cp.choices.waiting is not None)
                or (interval > 0 and self.timer >= interval)):
            self._autosave(cp)

    def _autosave(self, cp: GameState) -> None:
        if self._request("auto"):
            self.timer = 0.0
            self._autosaved_cp = cp

    def _reset_autosave(self) -> None:
        """The shell's in-game reset (New Game, the title, a load): timer 0, no request, no
        checkpoint looked at (a load then marks its restored one, ``_after_load``)."""
        self.timer = 0.0
        self._autosave_requested = False
        self._last_cp = None
        self._autosaved_cp = None
        self._restored_cp = None

    def _leave_autosaves(self, *, quitting: bool = False) -> bool:
        """I-2: Main Menu → Yes and a quit auto-save only with ``[saves] autosave_quit`` and
        while saving can (``quitting``: the quit's, F30 07 I-6)."""
        return self.autosave_quit and self.can_save(quitting=quitting)

    def before_title(self) -> None:
        """C5 (``add_before_title``): Main Menu → Yes, mode still GAME: an Auto save with the
        kept thumbnail; it is encoded and written during the black fade (I-2, I-3)."""
        if self._leave_autosaves():
            self._autosave_requested = False
            self._request("auto")

    def quit_guard(self) -> bool:
        """§7.8 step 4, after F10's guard (which asked first): first every save already
        requested and still waiting to be encoded (an Auto save at a choice, an F5 held back
        by the writer's backlog) is encoded in full and submitted, oldest first, so the
        quit writes it instead of dropping it with W83; then, in game with
        ``autosave_quit`` and ``can_save()``, ``autosave_now("quit")``. Always True: it
        never vetoes."""
        self._flush_jobs()
        if self._leave_autosaves(quitting=True):
            self.autosave_now("quit")
        return True

    def _flush_jobs(self) -> None:
        """At quit: each waiting job encoded now (no deadline, like ``autosave_now``) and
        submitted in order; the writer writes them on its thread before the quit save."""
        if not self.available or self.client is None or self._error_mode():
            return
        while self._jobs:
            job = self._jobs.popleft()
            self._encode(job, float("inf"), self._clock)
            self._submit(job)

    def autosave_now(self, reason: Literal["quit", "jump"]) -> None:
        """An Auto save encoded in full now and submitted to the writer, which writes it on
        its thread (SEC-F11-10a; quit waits for it on the shared deadline, ``wait_final``).
        The picture is the kept thumbnail (the quit question or game menu is up); with none
        at hand the save has no picture, since no frame follows. ``"jump"`` (F20 ``04``
        §7.6, ``07`` I-3): the same, for the checkpoint before a flowchart jump, called
        from ``load_state``'s ``before_commit`` (rotation, ``seq``, and the skip rules as a
        quit's)."""
        if reason not in ("quit", "jump"):
            raise ValueError(f"autosave_now: unknown reason {reason!r}")
        if not self.can_save(quitting=reason == "quit")                 or self._waiting() >= limits.MAX_REQUESTS:
            return
        served: list = []
        self.shell.capture_scene(served.append)
        before = len(self._jobs)
        self._captures += 1
        self._captured("auto", None, served[0] if served else None)
        if len(self._jobs) == before:
            return                                   # refused (no slot): already said why
        job = self._jobs.pop()
        self._encode(job, float("inf"), self._clock)
        if job.pieces is None:                        # can't happen with no deadline
            return
        self._submit(job)

    def _confirm_key(self, action: Literal["main_menu", "quit"]) -> str:
        """C6: the question's ``[words]`` key: without "Unsaved progress will be lost."
        when leaving makes an Auto save."""
        base = "confirm_main_menu" if action == "main_menu" else "confirm_quit"
        return base + "_autosave" if self._leave_autosaves() else base

    def _encode(self, job: SaveJob, deadline: float, clock: Callable[[], float]) -> bool:
        """One slice of ``job``'s encoding; True when its pieces (or TooLarge) are ready."""
        if job.pieces is not None:
            return True
        if job.encoder is None:
            jpeg = encode_jpeg(job.picture) if job.picture is not None else None
            meta = job.head.meta
            assert meta is not None
            job.encoder = SaveEncoder(job.state, seq=meta.seq, saved_at=meta.saved_at,
                                      description=meta.description, chapter=meta.chapter,
                                      game=self.game_id, game_version=self.game_version,
                                      jpeg=jpeg, pieces_from=self._last_encoder)
            job.picture = None                        # its JPEG is all the file needs
            if clock() >= deadline:
                return False
        encoder = job.encoder
        if not encoder.step(deadline, clock):
            return False
        result = encoder.result
        if isinstance(result, TooLarge):
            self._too_large(job, result.reason)
            job.pieces = ()
            return True
        assert result is not None
        self._last_encoder = encoder                  # its state pieces serve F5 held (§7.3 4)
        job.pieces = result
        return True

    def _submit(self, job: SaveJob) -> None:
        if not job.pieces:                            # TooLarge: already reported
            return
        client = self.client
        assert client is not None and self.folder is not None
        self._sent[job.token] = job
        client.submit(FileWrite(self.folder, job.slot.file_name(), job.pieces,
                                self.release, job.token))
        job.pieces = None
        job.encoder = None

    def _take_results(self) -> None:
        client = self.client
        if client is None:
            return
        for result in client.take():
            self._result(result, notify=True)

    def _result(self, result: object, *, notify: bool) -> None:
        token = getattr(result, "token", 0)
        job = self._sent.pop(token, None)
        if job is None:
            return
        if isinstance(result, FileWritten):
            self.heads[job.slot] = replace(job.head, stamp=result.stamp)
            self.order[job.slot] = job.order
            self.skip.discard(job.slot)
            if job.shown is not None:                 # shown until a page re-reads the slot
                self.pictures[job.slot] = (result.stamp, job.shown)
                self.pictures.move_to_end(job.slot)
                while len(self.pictures) > PICTURES_KEPT:
                    self.pictures.popitem(last=False)
            self._job_done(job)
            if notify and job.kind == "quick":
                self._notice("notice_quick_saved", kind="info")
        elif isinstance(result, Failed):
            self.skip.add(job.slot)
            self._job_done(job)
            _log.warning("%s", w83_text(self.slot_label(job.slot), result.reason),
                         extra={"code": "W83"})
            if result.detail:
                _log.debug("The save's write failed: %s", result.detail)
            if notify:
                self._notice_failed(_reason_word(result.reason))

    def _too_large(self, job: SaveJob, reason: str) -> None:
        self._job_done(job)
        _log.warning("%s", w83_text(self.slot_label(job.slot), f"too large ({reason})"),
                     extra={"code": "W83"})
        self._notice("notice_too_large")

    def _job_done(self, job: SaveJob) -> None:
        """The job ended (written, failed, or refused): the slot's optimistic view goes
        once no later job for it is outstanding (a failure shows the old view again)."""
        slot = job.slot
        left = self._outstanding.get(slot, 0) - 1
        if left > 0:
            self._outstanding[slot] = left
            return
        self._outstanding.pop(slot, None)
        self._latest.pop(slot, None)

    # --- loading (§7.6 steps 3–6 and the table; I-1) -----------------------------------------

    def _load_later_or_now(self, slot: SlotId, origin: LoadOrigin, by: InputKind) -> None:
        """A slot with a save still being written is loaded once its result is in."""
        if slot in self._latest:
            self._load_waiting = (slot, origin, by)
            return
        self._load(slot, origin, by)

    def _load(self, slot: SlotId, origin: LoadOrigin, by: InputKind = InputKind.KEYS) -> bool:
        """Steps 3–4: read the slot once and check it (``check_only``: nothing changes). A
        saved line that is gone but found by its location hint asks ``confirm_nearest``
        (Yes commits with hints). Every refusal changes nothing and shows its notice."""
        driver = self.app.story
        if driver is None or self._error_mode():
            return False
        if not self.folder_ok or self.folder is None:
            self._load_failed(slot, "notice_load_failed", fmt.REASON_UNREADABLE)
            return False
        read = fmt.read_slot_full(self.folder, slot, game_id=self.game_id)
        if read.status is not SlotStatus.OK or read.state is None:
            if read.status is SlotStatus.EMPTY:
                self.heads.pop(slot, None)
            self._load_failed(slot, _read_notice(read), read.reason)
            return False
        state = read.state
        del read
        return self.load_state(state, origin=origin, by=by,
                               warn=lambda reason: self._w82(slot, reason))

    def load_state(self, state: GameState, *, origin: LoadOrigin,
                   by: InputKind = InputKind.KEYS, fresh_menu: bool = False,
                   before_commit: Callable[[], None] | None = None,
                   on_result: "Callable[[RestoreOutcome | None], None] | None" = None,
                   warn: Callable[[str], None] | None = None) -> bool:
        """§7.6 steps 4–6 on a state already read (``07`` I-3: the slot load is
        ``read_slot_full`` + this; F20's jump passes ``fresh_menu=True``). The state is
        checked first (``check_only``: nothing changes); a saved line that is gone but found
        by its location hint asks ``confirm_nearest`` (Yes commits with hints). Then
        ``before_commit()`` (F20: the jump's auto-save, after the nearest Yes, right before
        the commit), the commit, and on OK the menus close and the game fades in. Every
        refusal changes nothing and shows its notice; ``warn(reason)`` gets the dev reason
        (W82 for a slot, W155 for a jump). ``on_result`` gets the final outcome (OK or the
        refusal), or None when the player said No to the nearest point. Touches no file, so
        it works with ``available`` False. True when the game was loaded now."""
        driver = self.app.story
        if driver is None or self._error_mode():
            if on_result is not None:
                on_result(None)
            return False
        warn_fn = warn if warn is not None else _no_warning
        fresh = {"fresh_menu": True} if fresh_menu else {}
        outcome = driver.restore(state, check_only=True, **fresh)  # type: ignore[attr-defined]
        if outcome.result is RestoreResult.POSITION_NOT_FOUND:
            hinted = driver.restore(state, use_hints=True,          # type: ignore[attr-defined]
                                    check_only=True, **fresh)
            if hinted.result is RestoreResult.OK:
                warn_fn(position_reason(state, NEAREST_OFFERED))
                self.shell.confirm(
                    self.shell.words.get("confirm_nearest"),
                    lambda: self._commit(state, hints=True, fresh=fresh, warn=warn_fn,
                                         before_commit=before_commit, on_result=on_result),
                    on_no=(lambda: on_result(None)) if on_result is not None else None, by=by)
                return False
        if outcome.result is not RestoreResult.OK:
            self._refused(state, outcome, warn_fn)
            if on_result is not None:
                on_result(outcome)
            return False
        return self._commit(state, hints=False, fresh=fresh, warn=warn_fn,
                            before_commit=before_commit, on_result=on_result)

    def _commit(self, state: GameState, *, hints: bool, fresh: dict, warn: Callable[[str], None],
                before_commit: Callable[[], None] | None,
                on_result: "Callable[[RestoreOutcome | None], None] | None") -> bool:
        """Step 5: the restore is the transaction (I-1), run while the menus are still up
        (the story hold keeps its burst); only on OK do the menus close (C8) and the game
        fade in. Any other result changed nothing (A6: a commit can still refuse)."""
        driver = self.app.story
        if driver is None or self._error_mode():
            if on_result is not None:
                on_result(None)
            return False
        if before_commit is not None:
            before_commit()
        outcome = driver.restore(state, use_hints=hints, **fresh)  # type: ignore[attr-defined]
        if outcome.result is not RestoreResult.OK:
            self._refused(state, outcome, warn)
            if on_result is not None:
                on_result(outcome)
            return False
        self.shell.show_loaded_game()
        self._after_load()
        if on_result is not None:
            on_result(outcome)
        return True

    def _refused(self, state: GameState, outcome: object, warn: Callable[[str], None]) -> None:
        """§7.6's table for a restore that isn't OK. DEFAULT_FAILED was logged once by
        ``restore`` (C12, QA G6): the warning carries only its code."""
        result = getattr(outcome, "result", None)
        if result is RestoreResult.DEFAULT_FAILED:
            error = getattr(outcome, "error", None)
            code = getattr(error, "code", None) or "?"
            warn(f"the story couldn't set this save up ({echo(str(code))})")
            self._notice("notice_load_failed")
            return
        if result is RestoreResult.SCHEME_MISMATCH:
            program = getattr(getattr(self.app.story, "interp", None), "program", None)
            uses = getattr(program, "identity_scheme", "?")
            reason = (f"made with identity scheme {echo(str(state.identity_scheme))}; "
                      f"this story uses {uses}")
        else:
            reason = position_reason(state, NO_NEARBY_POINT)
        warn(reason)
        self._notice("notice_load_no_fit")

    def _after_load(self) -> None:
        """§7.6 step 5's tail: the restored checkpoint is never auto-saved (step 10), and
        the load listeners run (F14 drops its snapshots, F15)."""
        driver = self.app.story
        self._restored_cp = driver.checkpoint() if driver is not None else None
        for fn in list(self._load_listeners):
            fn()

    def _load_failed(self, slot: SlotId, key: str, reason: str) -> None:
        """Step 6: the problem notice (``[words]`` only, SEC-F11-09a) and W82 (dev)."""
        self._w82(slot, reason)
        self._notice(key)

    def _w82(self, slot: SlotId, reason: str) -> None:
        if not self.release:
            _log.warning("%s", w82_text(self.slot_label(slot), reason), extra={"code": "W82"})

    # --- seams (04 §5.2; I-4) -------------------------------------------------------------------

    def add_load_listener(self, fn: Callable[[], None]) -> None:
        """F14 (drop its snapshots), F15: ``fn()`` runs once after each successful load,
        after the menus closed and the restored checkpoint was marked; never on a refused
        one."""
        self._load_listeners.append(fn)

    def note_restore(self) -> None:
        """F14: the checkpoint its restore (a rollback landing or match) arrived at is
        never auto-saved, as a load's isn't, and a pending ``request_autosave()`` is dropped
        (F18 ``07`` I-6: rolling forward over a chapter makes no second Auto save). Call it
        right after the restore (the driver's report listener, before ``update``)."""
        driver = self.app.story
        self._restored_cp = driver.checkpoint() if driver is not None else None
        self._autosave_requested = False

    def set_minigame_title_provider(self, fn: "Callable[[str], str | None] | None") -> None:
        """F23 (``04`` §7.8): ``fn(name)`` gives the display title of the minigame a save's
        state waits at (from the live registry; None for an unregistered name). Asked
        before F18's chapter and the newest line; None clears it."""
        self._minigame_title = fn

    def set_chapter_provider(self, fn: "Callable[[GameState], str | None] | None") -> None:
        """F18: ``fn(state)`` names the chapter of a save's checkpoint (a non-blank ``str``
        is the save's ``chapter`` and its description); None: no chapter."""
        self._chapter_provider = fn

    def delete_all(self) -> None:
        """F12/F16 "delete all data", F32 (§7.7, I-4): every slot name of this game's pages
        (Auto, Quick, 1 … ``pages``) is removed with ``remove_file``, ``WIPE_PER_FRAME`` a
        frame, each after its own queued or in-flight save; nothing else in the folder is
        touched. The cells show Empty at once; saving is off while it runs. Again while it
        runs: nothing more. Nothing is done when the folder can't be used (W81)."""
        if not self.available or not self.folder_ok or self.folder is None or self._wipe:
            return
        self.finish_index()
        slots = fmt.all_slots(self.pages)
        self._wipe = deque(slots)
        self._wiping = set(slots)

    @property
    def deleting_all(self) -> bool:
        """Whether ``delete_all`` is still running."""
        return bool(self._wipe)

    def _wipe_step(self) -> None:
        removed = 0
        for _ in range(len(self._wipe)):
            if removed >= WIPE_PER_FRAME:
                break
            slot = self._wipe.popleft()
            if slot in self._latest:
                self._wipe.append(slot)               # waits for its save's result (I-4)
                continue
            self._remove(slot)
            removed += 1

    def refresh(self) -> None:
        """F39: the slot index is read again (a file copied in counts) and the shown page
        re-reads its six heads."""
        if not self.available or not self.folder_ok or self.folder is None:
            return
        self.heads = {}
        self.index = IndexJob(self.folder, game_id=self.game_id, pages=self.pages)
        self.slots.reread()

    # --- quit (§7.8 step 5, C9, I-3) ----------------------------------------------------------

    def submit_final(self) -> None:
        """At quit, before F12's close: submit every fully encoded job; the others get W83
        ``the quit didn't wait for it``. Never encodes or writes here."""
        client = self.client
        if not self.available or client is None:
            return
        self._take_results()
        jobs, self._jobs = self._jobs, deque()
        for job in jobs:
            if job.pieces is not None:
                try:
                    self._submit(job)
                    continue
                except RuntimeError:                  # the writer already stopped
                    pass
            if job.pieces != ():                      # TooLarge was already logged
                _log.warning("%s", w83_text(self.slot_label(job.slot), QUIT_DIDNT_WAIT),
                             extra={"code": "W83"})

    def wait_final(self, until: float) -> None:
        """At quit, after F12's close: wait for F11's writes on the shared deadline, then
        ``finish``."""
        client = self.client
        if not self.available or client is None:
            return
        self.finish(client.wait(until))

    def finish(self, results: list) -> None:
        """Log each failure (W83) and each submitted job without a result (W83 ``the quit
        didn't wait for it``); no notice (the window is gone)."""
        for result in results:
            self._result(result, notify=False)
        for job in list(self._sent.values()):
            _log.warning("%s", w83_text(self.slot_label(job.slot), QUIT_DIDNT_WAIT),
                         extra={"code": "W83"})
        self._sent.clear()

    # --- words ---------------------------------------------------------------------------------

    def slot_label(self, slot: SlotId) -> str:
        """``Quick 1``, ``Auto 2``, ``Slot 3``: word + space + number (03 Words)."""
        words = self.shell.words
        key = {"auto": "save_page_auto", "quick": "save_page_quick"}.get(
            slot.page if type(slot.page) is str else "", "save_slot")
        return f"{words.get(key)} {slot.n}"

    def _notice(self, key: str, *, kind: Literal["info", "problem"] = "problem") -> None:
        self.shell.notify(self.shell.words.get(key), kind=kind)

    def _notice_failed(self, reason_key: str) -> None:
        words = self.shell.words
        self.shell.notify(f"{words.get('notice_save_failed')} {words.get(reason_key)}",
                          kind="problem")


def _no_warning(reason: str) -> None:
    """``load_state`` without ``warn``: no dev warning."""


def _reason_word(reason: str) -> str:
    """The writer's reason → the ``[words]`` key after ``Couldn't save:`` (§7.3 Results)."""
    if reason == DISK_FULL:
        return "save_reason_disk_full"
    if reason in (NO_PERMISSION, FOLDER_IS_LINK):
        return "save_reason_folder"
    return "save_reason_other"


def _read_notice(read: fmt.FullRead) -> str:
    """§7.6's table for a read that isn't OK."""
    status = read.status
    if status is SlotStatus.NEWER:
        return "save_newer"
    if status is SlotStatus.OTHER_GAME:
        return "save_other_game"
    if status is SlotStatus.DAMAGED and not (read.cause is Cause.ENTRY
                                             and read.reason == fmt.REASON_UNREADABLE):
        return "notice_load_damaged"
    return "notice_load_failed"                       # gone, or couldn't be read


# --- The pages' port (§7.7) --------------------------------------------------------------------

class SaveSlots:
    """The Save and Load pages' ``SlotsPort`` over ``SaveService`` (``ui`` never imports
    ``persist``, so slot facts cross as ``SlotView``s and plain page values).

    Reading (§7.7 "Reading"): the first ``views(page)`` of an open (or after a page change)
    starts a read of the page's six heads, one per ``SaveService.update`` (≤ ``HEAD_MAX``
    bytes each, line 2 checked only for OK heads); unread cells are "Loading…" and a save in
    flight wins over a read. An OK head's accepted JPEG is decoded once into
    ``assets.cache`` (``("save-thumb", slot, stamp)``, cost w·h·4) and held while the page
    shows; ``remember`` (a page change or close) releases it. A slot written while shown keeps
    its captured picture until it is read again with the new stamp."""

    def __init__(self, service: SaveService) -> None:
        self.service = service
        self._last: dict[str, fmt.SlotPage] = {}
        self._page: fmt.SlotPage | None = None
        self._queue: list[SlotId] = []
        self._read: dict[SlotId, SlotHead] = {}
        self._thumbs: dict[SlotId, pygame.Surface | None] = {}
        self._held: list[tuple] = []
        self.reads = 0                                # heads read for pages (tests)
        self.decodes = 0                              # thumbnails decoded (tests)
        # The last view of each slot and what it was made from: a page asks every frame,
        # and a view is rebuilt (text cleaned, date formatted) only when that changes.
        self._memo: dict[SlotId, tuple[tuple, SlotView]] = {}

    # -- SlotsPort --

    def pages(self, mode: str) -> list[fmt.SlotPage]:
        numbered: list[fmt.SlotPage] = list(range(1, self.service.pages + 1))
        return ["auto", "quick", *numbered] if mode == "load" else numbered

    def page_label(self, page: fmt.SlotPage) -> str:
        if page == "auto":
            return self.service.shell.words.get("save_page_auto")
        if page == "quick":
            return self.service.shell.words.get("save_page_quick")
        return str(page)

    def initial_page(self, mode: str) -> fmt.SlotPage:
        """PR-F11-33: this session's last page of ``mode``; at first, Load opens on the page
        holding the Newest save (Auto or Quick when it is there), Save on page 1."""
        pages = self.pages(mode)
        last = self._last.get(mode)
        if last in pages:
            return last                               # type: ignore[return-value]
        if mode == "load":
            service = self.service
            service.finish_index()
            shown = [h for h in service.known_views() if h.slot.page in pages]
            best = fmt.newest(shown, order=service._order_view())
            if best is not None:
                return best.page
        return pages[0]

    def views(self, page: fmt.SlotPage) -> list[SlotView]:
        if page != self._page:
            self._start(page)
        slots = fmt.page_slots(page)
        heads = [self._head(slot) for slot in slots]
        newest = None
        if type(page) is str:
            newest = fmt.newest([h for h in heads if h is not None],
                                order=self.service._order_view())
        busy = self.service.loading_slot
        return [self._memo_view(slot, head, newest, busy) for slot, head in zip(slots, heads)]

    def _memo_view(self, slot: SlotId, head: SlotHead | None, newest: SlotId | None,
                   busy: SlotId | None) -> SlotView:
        made_from = (head, slot == newest, slot == busy)
        found = self._memo.get(slot)
        if found is not None and found[0] == made_from:
            view = found[1]
            if head is None or head.status is not SlotStatus.OK:
                return view
            thumb, key = self._picture(slot, head)
            if thumb is view.thumb and key == view.thumb_key:
                return view
        view = self._view(slot, head, newest, busy)
        self._memo[slot] = (made_from, view)
        return view

    def default_cell(self, page: fmt.SlotPage) -> int:
        """C1: the cell holding the shown page's newest save, else cell 1 (index 0)."""
        slots = fmt.page_slots(page)
        known = [self._head(slot) or self.service.view(slot) for slot in slots]
        best = fmt.newest(known, order=self.service._order_view())
        return 0 if best is None else best.n - 1

    def blocked(self, mode: str) -> str | None:
        return self.service._reason(mode)

    def no_saves(self) -> bool:
        """PR-F11-37: no slot of any page holds a save (a damaged file counts as one)."""
        self.service.finish_index()
        return not self.service.known_views()

    def busy(self) -> bool:
        return self.service.loading_slot is not None

    def load_indicator(self) -> bool:
        """G3: the load being checked is of a file over 1 MiB (the head's stamp), so the
        badge frame also draws F10's loading indicator."""
        return self.busy() and self.service._load_big

    def remember(self, mode: str, page: fmt.SlotPage) -> None:
        """The page left ``page`` (a page change or close): kept as this session's last page
        of ``mode``; its reading stops and its thumbnails are let go."""
        self._last[mode] = page
        self._stop()

    def choose(self, page: fmt.SlotPage, i: int, mode: str, by: InputKind) -> None:
        """§7.7 Choose. Save: EMPTY saves at once, anything else asks ``confirm_overwrite``.
        Load: an OK slot loads (§7.6); other states do nothing. An unread cell does
        nothing."""
        service = self.service
        slot = SlotId(page, i + 1)
        head = self._head(slot)
        if head is None or service.loading_slot is not None:
            return
        if mode == "save":
            if head.status is SlotStatus.EMPTY:
                service.save_to(slot)
            else:
                service.shell.confirm(service.shell.words.get("confirm_overwrite"),
                                      lambda: service.save_to(slot), by=by)
        elif head.status is SlotStatus.OK:
            origin: LoadOrigin = "title" if service.shell.mode is Mode.TITLE else "game"
            service.load_from(slot, by, origin=origin)

    def delete(self, page: fmt.SlotPage, i: int, by: InputKind) -> None:
        """§7.7 Delete: any slot holding something (not EMPTY, not unread) asks
        ``confirm_delete``; Yes deletes it."""
        service = self.service
        slot = SlotId(page, i + 1)
        head = self._head(slot)
        if (head is None or head.status is SlotStatus.EMPTY or service.loading_slot is not None
                or service.deleting_all):
            return
        service.shell.confirm(service.shell.words.get("confirm_delete"),
                              lambda: service.delete(slot), by=by)

    # -- reading (the frame slot) --

    def step(self) -> None:
        """One head of the shown page, with its thumbnail (``SaveService.update``)."""
        if self._page is None or not self._queue:
            return
        service = self.service
        slot = self._queue.pop(0)
        if service.folder_ok and service.folder is not None:
            head = fmt.read_slot_head(service.folder, slot, game_id=service.game_id,
                                      thumb=True)
        else:                                         # a link folder is never read (W81)
            head = SlotHead(slot, SlotStatus.EMPTY, None, None, None, None, "")
        self.reads += 1
        jpeg = head.jpeg
        head = replace(head, jpeg=None)
        self._read[slot] = head
        if (slot not in service._latest and slot not in service._deleting
                and slot not in service._wiping):
            if head.status is SlotStatus.EMPTY:
                service.heads.pop(slot, None)
            else:
                service.heads[slot] = head
        self._thumbs[slot] = self._decode(slot, head, jpeg)
        shown = service.pictures.get(slot)
        if shown is not None and shown[0] == head.stamp:
            del service.pictures[slot]                # the file's own picture from now on

    def _decode(self, slot: SlotId, head: SlotHead, jpeg: bytes | None) -> pygame.Surface | None:
        """The slot's picture from ``assets.cache``, else decoded from memory once
        (``decode_jpeg``: size re-checked, None → "No picture"); held while shown."""
        if head.status is not SlotStatus.OK or jpeg is None:
            return None
        assets = self.service.shell.assets
        key = ("save-thumb", slot, head.stamp)
        frame = assets.time.frame
        surface = assets.cache.get(key, frame)
        if surface is None:
            surface = decode_jpeg(jpeg)
            self.decodes += 1
            if surface is None:
                return None
            w, h = surface.get_size()
            assets.cache.put(key, surface, w * h * 4 + ENTRY_OVERHEAD, frame)
        assets.cache.hold(key)
        self._held.append(key)
        return surface

    def reread(self) -> None:
        """``refresh()``: the shown page reads its six heads again (unread cells are
        "Loading…" meanwhile)."""
        if self._page is not None:
            self._start(self._page)

    def _start(self, page: fmt.SlotPage) -> None:
        self._stop()
        self._page = page
        self._queue = fmt.page_slots(page)

    def _stop(self) -> None:
        cache = self.service.shell.assets.cache
        for key in self._held:
            cache.release(key)
        self._held = []
        self._page = None
        self._queue = []
        self._read = {}
        self._thumbs = {}
        self._memo = {}

    # -- views --

    def _head(self, slot: SlotId) -> SlotHead | None:
        """What the page knows of ``slot`` now: a delete or a save in flight; else, once read
        this showing, the service's head (kept current by writes and deletes); else None
        (unread: "Loading…"). A head newer than the one read is read again."""
        service = self.service
        if slot in service._deleting or slot in service._wiping or slot in service._latest:
            return service.view(slot)
        read = self._read.get(slot)
        if read is None:
            return None
        known = service.view(slot)
        if known.stamp != read.stamp and slot not in self._queue:
            self._queue.append(slot)                  # written or deleted since: read again
        return known

    def _view(self, slot: SlotId, head: SlotHead | None, newest: SlotId | None,
              busy: SlotId | None) -> SlotView:
        label = self.service.slot_label(slot)
        if head is None:
            return SlotView(label, "loading")
        status = head.status
        if status is SlotStatus.EMPTY:
            return SlotView(label, "empty")
        if status is not SlotStatus.OK or head.meta is None:
            state = {SlotStatus.NEWER: "newer",
                     SlotStatus.OTHER_GAME: "other_game"}.get(status, "damaged")
            return SlotView(label, state, deletable=True)    # type: ignore[arg-type]
        meta = head.meta
        thumb, key = self._picture(slot, head)
        loading = slot == busy
        return SlotView(label, "filled", shown_date(meta.saved_at), shown_text(meta.description),
                        thumb, newest=slot == newest, deletable=not loading, busy=loading,
                        version=None, thumb_key=key)

    def _picture(self, slot: SlotId, head: SlotHead) -> tuple[pygame.Surface | None, tuple | None]:
        """A save in flight: its captured picture; a slot written this showing: that
        picture until it is read again; else the decoded thumbnail of the head read."""
        service = self.service
        job = service._latest.get(slot)
        if job is not None:
            return job.shown, None
        shown = service.pictures.get(slot)
        if shown is not None and shown[0] == head.stamp:
            return shown[1], None
        read = self._read.get(slot)
        if read is None or read.stamp != head.stamp:
            return None, None
        thumb = self._thumbs.get(slot)
        return thumb, (("save-thumb", slot, head.stamp) if thumb is not None else None)


# --- QuickKeys ---------------------------------------------------------------------------------

class QuickKeys:
    """The ``InGameOverlay`` for F5 (quick save) and F9 (quick load), without Ctrl, Alt, or
    Meta. Hosted by F05's textbox after F10's overlays, so it sees keys only while an
    in-game screen is top (never on the title, in menus, or on the error screen)."""

    def __init__(self, saves: SaveService) -> None:
        self.saves = saves

    def handle_event(self, event: UiEvent, *, box_shown: bool) -> bool:
        raw = event.raw
        if raw.type != pygame.KEYDOWN or getattr(raw, "mod", 0) & _BLOCKING_MODS:
            return False
        key = getattr(raw, "key", None)
        if key == pygame.K_F5:
            self.saves.quick_save(InputKind.KEYS)
            return True
        if key == pygame.K_F9:
            self.saves.quick_load(InputKind.KEYS)
            return True
        return False

    def update(self, dt: float, *, frozen: bool) -> None:
        pass

    def draw(self, canvas: "Canvas", *, box_shown: bool) -> None:
        pass


# --- Install (§7.1) ----------------------------------------------------------------------------

def _folder_problem(folder: Path, release: bool) -> str:
    """W81's reason word for a saves root ``ensure_real_dir`` refused."""
    import os
    import stat

    try:
        st = os.lstat(folder)
    except OSError:
        return FOLDER_NOT_CREATED
    if (stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400
            or os.path.isjunction(folder)):
        return FOLDER_LINK
    if not stat.S_ISDIR(st.st_mode):
        return FOLDER_NOT_REAL
    return FOLDER_LINK if not release else FOLDER_NOT_REAL     # a link above a dev folder


def install_saves(app: "App") -> SaveService:
    """§7.1: once per launch, after ``install_ui`` (``app.shell``), beside F13's
    ``install_history``. Sets ``app.saves``."""
    assert getattr(app, "saves", None) is None, "install_saves runs once per launch"
    shell = app.shell
    assert shell is not None, "install_saves needs the shell (install_ui runs first)"
    release = not app.dev
    paths = getattr(app, "paths", None)
    writer = getattr(app, "writer", None)
    game_root = paths.root if paths is not None else None
    folder: Path | None = None
    folder_ok = False
    client: WriterClient | None = None
    if release and app.config.game.id is None:
        _log.warning("%s", W80_TEXT, extra={"code": "W80"})
    elif writer is not None and (game_root is not None or release) and \
            not getattr(app, "try_run", False):             # F47 P2-F: Try it saves nothing
        folder = saves_root(game_root=game_root, release=release,   # type: ignore[arg-type]
                            app_id=app.config.game.id)
    if folder is not None and writer is not None:
        folder_ok = safefile.ensure_real_dir(folder, release=release)
        if not folder_ok:
            _log.warning("%s%s %s", W81_PREFIX, display_path(folder, game_root=game_root),
                         _folder_problem(folder, release), extra={"code": "W81"})
        client = writer.client("save", root=folder, names=fmt.SLOT_NAME_RE)
        if folder_ok:
            safefile.remove_stale_temps(folder, target_pattern=fmt.SLOT_NAME_RE,
                                        max_age_s=limits.TEMP_STALE_S,
                                        max_examined=limits.SAVE_TEMP_SCAN_MAX,
                                        max_removed=limits.TEMP_CLEANUP_MAX)
            writer.start()
    service = SaveService(app, shell, folder=folder, folder_ok=folder_ok, client=client,
                          release=release)
    visible = (lambda: True) if service.available else (lambda: False)
    register_save_pages(shell, service.slots, can_save=service.can_save, visible=visible)
    shell.menus.add("quick", MenuEntry("q_save", action=lambda ctx: _q_save(service, ctx),
                                       enabled=service.can_save, visible=visible))
    shell.menus.add("quick", MenuEntry("q_load", action=lambda ctx: _q_load(service, ctx),
                                       visible=visible))
    textbox = getattr(app, "textbox", None)
    if textbox is not None:
        textbox.add_overlay(QuickKeys(service))
    if service.available:                            # §7.8 steps 3–4, C5, C6
        service.set_chapter_provider(_story_chapter(app))    # F18 may replace it
        shell.add_in_game_reset(service._reset_autosave)
        shell.add_before_title(service.before_title)
        shell.set_confirm_key("main_menu", lambda: service._confirm_key("main_menu"))
        shell.set_confirm_key("quit", lambda: service._confirm_key("quit"))
        app.add_quit_guard(service.quit_guard)       # after F10's (install_ui ran first)
    app.saves = service
    return service


def _story_chapter(app: "App") -> Callable[[GameState], str | None]:
    """F18's save label (``heading: title``, or ``title``) of the checkpoint's chapter,
    from the running story's ``ChapterIndex``; None before any chapter or for a chapter the
    story no longer has (F18 PR-F18-05, ``name_saves``'s default)."""

    def label(state: GameState) -> str | None:
        index = getattr(getattr(app.story, "interp", None), "chapters", None)
        return None if index is None else index.save_label(state.chapter.current)

    return label


def _q_save(service: SaveService, ctx: EntryContext) -> None:
    service.quick_save(ctx.by)


def _q_load(service: SaveService, ctx: EntryContext) -> None:
    service.quick_load(ctx.by)


__all__ = ["KEEP", "LOAD_INDICATOR_BYTES", "NEAREST_OFFERED", "NO_NEARBY_POINT", "QuickKeys",
           "SaveJob", "SaveService", "SaveSlots", "W80_TEXT", "W81_PREFIX", "WIPE_PER_FRAME",
           "install_saves", "position_reason", "shown_date", "shown_text", "w82_text",
           "w83_delete_text", "w83_text"]
