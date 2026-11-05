"""``apply_edit`` and ``undo_apply``: the MCP server's only writes (F48 ``04-technical.md``
§7.4; ``05-security.md`` SEC-F48-02, SEC-F48-03; 01 PR-F48-10, PR-F48-11, §6.3; ADR-0008
Amendment 5 as accepted in ``07`` §2.10 and I-5).

Why this module exists: an MCP client applies a proposal by its id, maybe minutes after it
was made, while the author may have edited, moved or linked the files. So a write happens
only when the bytes on disk are exactly the ones the proposal was built and shown on, and
every check ``files.py`` makes before its own writes is made again at that moment.

- ``ProposalStore`` keeps this session's last ``PROPOSALS_KEPT`` proposals under ids
  ``<session>-<n>`` (the session part is random, so another server's id is unknown here) and
  hands each out once: ``apply`` pops it before anything else, so an id never works twice,
  even after a refusal.
- ``apply`` checks every file first, writing nothing until all pass: (F) the folder is a real
  folder (``GamePaths.real_dir``: no link or junction on the way, ``script/`` included); (E)
  the target is a listed regular file, read once with ``safefile.read_regular`` (a link is
  refused, never followed); its whole-file SHA-256 is the proposal's base; the plan still
  verifies; the result encodes (``document.encode`` keeps BOM, line endings and every
  untouched byte) within ``SCRIPT_FILE_MAX_BYTES``. Then each file is written with
  ``safefile.write_atomic(check=True, expected=<the stamp read>)``, keeping its mode; a new
  file is created by ``files.new_script`` (exclusive) after ``new_ref_problem`` passes again,
  only in a folder that already exists. A failure after a write names the files written:
  "Wrote {files}, then stopped: {reason}".
- ``undo_last`` undoes the newest applied proposal (``UNDO_KEPT`` kept, memory only) while
  every file holds exactly the bytes the apply wrote: a changed file restores its old bytes,
  and a file this server process created is removed with ``safefile.remove_file``. Nothing
  else is ever removed.

Imports ``engine.core``, ``engine.script``, the pure editor modules ``document``, ``files``
and ``scriptedit``, and its own package.
"""

import os
import secrets
import stat
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core import safefile
from engine.core.errors import AssetRefError
from engine.core.paths import GamePaths, RealDir
from engine.script.assetgroups import CONFIG_REF
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.script.messages import format_message
from engine.tools.assistant.edits import Proposal, ProposalFile, verify_file
from engine.tools.assistant.refs import ToolError, check_keys, new_ref_problem, one_line
from engine.tools.assistant.textout import ToolText
from engine.tools.assistant.workspace import DiskWorkspace, bytes_sha, read_disk
from engine.tools.editor import files
from engine.tools.editor.document import SaveError, encode, list_scripts
from engine.tools.editor.scriptedit import Plan, apply_lines, verify

PROPOSALS_KEPT: Final = 50
UNDO_KEPT: Final = 20
ID_MAX_CHARS: Final = 64

# --- Texts (01 §6.3; the rest worded here) --------------------------------------------------

GONE: Final = "That change isn't available any more. Propose it again."
PARTIAL: Final = "Wrote {files}, then stopped: {reason}"
APPLIED: Final = "Wrote {files}. undo_apply undoes it while those files stay as written."
CHANGED: Final = ("{file} changed after this change was proposed, so nothing was written. "
                  "Read it again and propose the change again.")
NOT_OWN: Final = files.NOT_OWN_FILE                  # "`{ref}` is a link or not a regular file…"
NOT_FOLDER: Final = files.NOT_A_FOLDER               # "`{folder}/` is a link or not a folder…"
TOO_LARGE: Final = "the result would be larger than a script file may be"
UNSAFE_NOW: Final = "{file} no longer fits this change, so nothing was written."
WRITE_FAILED: Final = "Couldn't change `{ref}`: {reason}"
NOTHING_TO_UNDO: Final = "There is no applied change to undo."
UNDONE: Final = "Undid the change to {files}."
UNDO_CHANGED: Final = ("{file} changed after the change was applied, so nothing was undone. "
                       "Change it back with propose_edit instead.")
REASON_LOCKED: Final = "the file is read-only or locked."
REASON_CHANGED: Final = "it changed on disk while it was being written."
REASON_SYSTEM: Final = "the system reported an error."


# --- Records --------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Written:
    """One file an apply wrote: its old bytes (None: this process created it), the SHA-256
    of what was written, and the mode it keeps."""

    ref: str
    before: bytes | None
    applied_sha: str
    mode: int | None


@dataclass(frozen=True, slots=True)
class _Ready:
    """One file checked and ready to write."""

    file: ProposalFile
    data: bytes
    target: Path | None = None              # existing files
    stamp: safefile.Stamp | None = None
    before: bytes | None = None
    mode: int | None = None


class _Refused(Exception):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


# --- (F) and (E) at write time (SEC-F48-03 (a)) -----------------------------------------------

def _folder(paths: GamePaths, ref: str) -> RealDir:
    folder_ref = ref.rpartition("/")[0]
    if ref == CONFIG_REF:                   # propose_settings: the game folder itself
        return RealDir("", paths.root)
    paths.invalidate_listings()
    try:
        found = paths.real_dir(folder_ref)
    except AssetRefError:
        found = None
    if not isinstance(found, RealDir):
        raise _Refused(NOT_FOLDER.format(folder=one_line(folder_ref)))
    return found


def _plain_config(target: Path) -> bool:
    """``config.toml`` is a regular file (not a link) whose real path is its own."""
    try:
        if not stat.S_ISREG(target.lstat().st_mode):
            return False
        return os.path.normcase(os.path.realpath(target)) == os.path.normcase(str(target))
    except OSError:
        return False


def _existing(paths: GamePaths, ref: str) -> tuple[Path, safefile.ReadResult, int | None]:
    """(F) and (E): the listed regular file ``ref`` read once (bytes and ``fstat`` stamp)."""
    folder = _folder(paths, ref)
    name = ref.rpartition("/")[2]
    target = folder.path / name
    if ref == CONFIG_REF:
        if not _plain_config(target):       # Studio's own rule (document.open_config)
            raise _Refused(NOT_OWN.format(ref=one_line(ref)))
    else:
        listing = paths.list_real(folder.ref)
        if listing is None or name not in listing.files:
            raise _Refused(NOT_OWN.format(ref=one_line(ref)))
    read = safefile.read_regular(target, SCRIPT_FILE_MAX_BYTES)
    if read.kind is safefile.ReadKind.TOO_LARGE:
        raise _Refused(format_message("E05", (ref,)))
    if not read.ok or read.data is None or read.stamp is None:
        raise _Refused(NOT_OWN.format(ref=one_line(ref)))
    try:
        mode: int | None = stat.S_IMODE(Path(target).lstat().st_mode)
    except OSError:
        mode = None
    return target, read, mode


def _prepare(paths: GamePaths, file: ProposalFile) -> _Ready:
    """Every check for one file, writing nothing."""
    shown = one_line(file.ref)
    if file.new:
        problem = new_ref_problem(paths, file.ref, list_scripts(paths))
        if problem is not None:
            raise _Refused(problem)
        if not verify(Plan("", (file.plan,)), {file.ref: ""}):
            raise _Refused(UNSAFE_NOW.format(file=shown))
        text = "\n".join(apply_lines([""], file.plan.edits)) + "\n"
        return _Ready(file, text.encode("utf-8"))
    target, read, mode = _existing(paths, file.ref)
    if bytes_sha(read.data) != file.base_sha:                   # type: ignore[arg-type]
        raise _Refused(CHANGED.format(file=shown))
    try:
        doc, data = read_disk(paths, file.ref)                  # the same bytes, as a document
    except ToolError as exc:
        raise _Refused(exc.text) from None
    if bytes_sha(data) != file.base_sha:
        raise _Refused(CHANGED.format(file=shown))
    if not verify_file(file, doc.text):      # config.toml: tomlpatch's own gate
        raise _Refused(UNSAFE_NOW.format(file=shown))
    try:
        result = encode(doc, "\n".join(apply_lines(doc.text.split("\n"), file.plan.edits)))
    except (SaveError, ValueError):
        raise _Refused(UNSAFE_NOW.format(file=shown)) from None
    if len(result) > SCRIPT_FILE_MAX_BYTES:
        raise _Refused(WRITE_FAILED.format(ref=shown, reason=TOO_LARGE + "."))
    return _Ready(file, result, target, read.stamp, read.data, mode)


def _reason(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return REASON_LOCKED
    return REASON_SYSTEM


def _write(paths: GamePaths, ready: _Ready) -> Written:
    """Write one checked file. ``_Refused`` (its text names only ``ready``'s file)."""
    ref = ready.file.ref
    shown = one_line(ref)
    if ready.file.new:
        problem = new_ref_problem(paths, ref, list_scripts(paths))    # again, right before
        if problem is not None:
            raise _Refused(problem)
        folder_ref, _, name = ref.rpartition("/")
        made = files.new_script(paths, folder_ref, name, text=ready.data.decode("utf-8"))
        if isinstance(made, files.Refusal):
            raise _Refused(made.text)
        return Written(ref, None, bytes_sha(ready.data), None)
    folder = _folder(paths, ref)                                      # (F) again
    target = folder.path / ref.rpartition("/")[2]
    if target != ready.target:
        raise _Refused(NOT_OWN.format(ref=shown))
    try:
        safefile.write_atomic(target, (ready.data,), check=True, expected=ready.stamp,
                              mode=ready.mode, replace_tries=1)
    except safefile.TargetChanged:
        raise _Refused(WRITE_FAILED.format(ref=shown, reason=REASON_CHANGED)) from None
    except OSError as exc:
        raise _Refused(WRITE_FAILED.format(ref=shown, reason=_reason(exc))) from None
    return Written(ref, ready.before, bytes_sha(ready.data), ready.mode)


def _names(refs: list[str]) -> str:
    return ", ".join(one_line(ref) for ref in refs)


def apply(paths: GamePaths, proposal: Proposal) -> tuple[ToolText, tuple[Written, ...]]:
    """Write ``proposal`` (SEC-F48-03). Returns the result and what was written."""
    try:
        ready = [_prepare(paths, file) for file in proposal.files]
    except _Refused as refused:
        return ToolText.error(refused.text), ()
    written: list[Written] = []
    for item in ready:
        try:
            written.append(_write(paths, item))
        except _Refused as refused:
            if not written:
                return ToolText.error(refused.text), ()
            text = PARTIAL.format(files=_names([w.ref for w in written]), reason=refused.text)
            return ToolText.error(text), tuple(written)
    paths.invalidate_listings()
    return ToolText(APPLIED.format(files=_names([w.ref for w in written]))), tuple(written)


def undo_last(paths: GamePaths, history: "deque[tuple[Written, ...]]") -> ToolText:
    """Undo the newest applied proposal while each file holds exactly what was written."""
    if not history:
        return ToolText.error(NOTHING_TO_UNDO)
    record = history[-1]
    checked: list[tuple[Written, Path, safefile.Stamp]] = []
    try:
        for item in record:
            target, read, _ = _existing(paths, item.ref)
            if bytes_sha(read.data) != item.applied_sha:          # type: ignore[arg-type]
                raise _Refused(UNDO_CHANGED.format(file=one_line(item.ref)))
            checked.append((item, target, read.stamp))            # type: ignore[arg-type]
    except _Refused as refused:
        return ToolText.error(refused.text)
    history.pop()
    done: list[str] = []
    for item, target, stamp in checked:
        shown = one_line(item.ref)
        try:
            if item.before is None:
                if safefile.current_stamp(target) != stamp:
                    raise _Refused(WRITE_FAILED.format(ref=shown, reason=REASON_CHANGED))
                if safefile.remove_file(target) is not safefile.RemoveKind.REMOVED:
                    raise _Refused(WRITE_FAILED.format(ref=shown, reason=REASON_LOCKED))
            else:
                try:
                    safefile.write_atomic(target, (item.before,), check=True,
                                          expected=stamp, mode=item.mode, replace_tries=1)
                except safefile.TargetChanged:
                    raise _Refused(WRITE_FAILED.format(ref=shown,
                                                       reason=REASON_CHANGED)) from None
                except OSError as exc:
                    raise _Refused(WRITE_FAILED.format(ref=shown,
                                                       reason=_reason(exc))) from None
        except _Refused as refused:
            if not done:
                return ToolText.error(refused.text)
            return ToolText.error(PARTIAL.format(files=_names(done), reason=refused.text))
        done.append(item.ref)
    paths.invalidate_listings()
    return ToolText(UNDONE.format(files=_names(done)))


# --- The store (ToolBox's writer) -----------------------------------------------------------

class ProposalStore:
    """This session's proposals and applies: ``ToolBox(…, writer=ProposalStore(ws))``."""

    def __init__(self, workspace: DiskWorkspace) -> None:
        self.ws = workspace
        self._session = secrets.token_hex(4)
        self._count = 0
        self._kept: OrderedDict[str, Proposal] = OrderedDict()
        self.history: deque[tuple[Written, ...]] = deque(maxlen=UNDO_KEPT)

    def keep(self, proposal: Proposal) -> str:
        self._count += 1
        found = f"{self._session}-{self._count}"
        self._kept[found] = proposal
        while len(self._kept) > PROPOSALS_KEPT:
            self._kept.popitem(last=False)
        return found

    def apply(self, args: object) -> ToolText:
        args = check_keys(args, ("id",))
        found = args["id"]
        proposal = self._kept.pop(found, None) \
            if type(found) is str and len(found) <= ID_MAX_CHARS else None
        if proposal is None:
            return ToolText.error(GONE)
        result, written = apply(self.ws.paths, proposal)
        if written:
            self.history.append(written)
        return result

    def undo(self, args: object) -> ToolText:
        check_keys(args)
        return undo_last(self.ws.paths, self.history)


__all__ = ["APPLIED", "CHANGED", "GONE", "NOTHING_TO_UNDO", "PARTIAL", "PROPOSALS_KEPT",
           "ProposalStore", "UNDONE", "UNDO_CHANGED", "UNDO_KEPT", "Written", "apply",
           "undo_last"]
