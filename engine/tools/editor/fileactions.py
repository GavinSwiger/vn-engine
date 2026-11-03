"""Studio's file operations (F45 PR-F45-02..06, ``04`` §7.5): Add files…, New script file,
Rename, Delete and New game, as the ``FileActions`` mixin of ``window.EditorWindow``.

The work is ``files`` functions; the questions are ``dialogs``'. Add files… copies on a
worker thread and polls its queue every ``ADD_POLL_MS``. F47 adds ``database.vns`` creation
here (``files.new_script``, as New script file does).
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path

from engine.core.errors import UserFacingError
from engine.core.paths import GamePaths, engine_root
from engine.script.messages import show
from engine.tools.editor import files
from engine.tools.editor.dialogs import (
    ask,
    ask_directory,
    ask_open_files,
    ask_text,
    show_error,
    show_info,
)
from engine.tools.editor.document import retarget
from engine.tools.editor.views import entry_enabled, set_entry_enabled
from engine.tools.editor.studiolook import line_of

ADD_BUTTON = "Add files…"
PICK_FOLDER = "Select a group or folder in the project panel first."
NEW_SCRIPT_ASK = "New script file in `{folder}/`:"
NEW_SCRIPT_OPTION = "Add an include line to main.vns"
RENAME_ASK = "New name for `{ref}`:"
ADD_NAME_OK = "Add"
CLASH_BUTTONS = ("Keep both", "Replace", "Skip")
CLASH_CHOICES = ("keep_both", "replace", "skip")
CLASH_ESCAPE = 2                        # Skip
RENAME_BUTTONS = ("Rename", "Cancel")
DELETE_BUTTONS = ("Delete", "Cancel")
DELETE_DEFAULT = 1                      # a destructive button is never the default (UI-F45-06)
ADD_POLL_MS = 50


def launch_studio(folder: Path) -> None:
    """Open Studio on a new game in its own process; this window stays open (a seam)."""
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(files.studio_argv(folder), cwd=engine_root(), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


class FileActions:
    """File ▸ New game…, New script file, Add files…, Rename and Delete, and whether they
    are enabled (off while the game folder can't be found, AC-F45-26)."""

    def _set_file_ops(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for label in self.file_ops:
            set_entry_enabled(self.file_menu, label, enabled)
        self.add_button.configure(state=state)

    def file_ops_enabled(self) -> bool:
        return entry_enabled(self.file_menu, ADD_BUTTON)

    # --- File operations (F45 PR-F45-02..06, 04 §7.5) ---------------------------------------

    def _target_folder(self) -> tuple[str, str] | None:
        """(group key, folder ref) for the selected row: a group or folder itself, or a
        file's folder. None for ``config.toml`` or no selection."""
        node = self.project_view.node(self.project_view.selected())
        if node is None or node.kind == "config":
            return None
        if node.kind == "file":
            return node.group, node.ref.rsplit("/", 1)[0]
        return node.group, node.ref

    def add_files(self, sources: Sequence[Path] | None = None, *,
                  target: tuple[str, str] | None = None,
                  on_done: Callable[[list[str]], object] | None = None) -> None:
        """Add files…: pick files, plan them, settle names and clashes in dialogs, then copy
        them on a worker thread; the summary shows when the last one is done. ``target``
        (group key, folder ref) replaces the project panel's selection (F47's Database);
        ``on_done`` gets the added refs after the summary."""
        if self.closed or self.adding or not self.file_ops_enabled():
            return
        self._add_on_done = on_done
        if target is None:
            target = self._target_folder()
        if target is None:
            show_error(self.root, PICK_FOLDER)
            return
        key, folder_ref = target
        if sources is None:
            sources = ask_open_files(self.root)
        if not sources:
            return
        plans = files.plan_add(self.paths, key, folder_ref, sources)
        jobs: list[tuple[files.AddPlan, str]] = []
        refused: list[files.AddOutcome] = []
        for plan in plans:
            settled = self._settle_name(plan)
            if settled is None:
                continue
            if settled.refusal is not None:
                refused.append(files.AddOutcome(settled.label, reason=settled.refusal))
                continue
            choice = "new"
            if settled.clash is not None:
                answer = ask(self.root, files.clash_message(f"{folder_ref}/{settled.clash}"),
                             CLASH_BUTTONS, escape=CLASH_ESCAPE)
                choice = CLASH_CHOICES[answer]
                if choice == "skip":
                    continue
            jobs.append((settled, choice))
        self._start_adding(jobs, refused)

    def _settle_name(self, plan: files.AddPlan) -> files.AddPlan | None:
        """Ask for a better name while the plan has an image-name problem; None to skip."""
        while plan.refusal is None and plan.problem is not None:
            answer = ask_text(self.root, plan.problem, plan.offer or plan.name,
                              ok=ADD_NAME_OK,
                              hint=lambda name, f=plan.folder_ref: files.show_hint(f, name))
            if answer is None:
                return None
            plan = files.rename_plan(self.paths, plan, answer[0])
        return plan

    def _start_adding(self, jobs: list[tuple[files.AddPlan, str]],
                      refused: list[files.AddOutcome]) -> None:
        self._add_outcomes = list(refused)
        if not jobs:
            if refused:
                show_info(self.root, files.add_summary(self._add_outcomes))
            return
        self.adding = True
        worker_paths = GamePaths(self.paths.root)      # its own listing cache
        out = self._add_queue

        def work() -> None:
            try:
                for plan, choice in jobs:
                    out.put(files.run_add(worker_paths, plan, choice))  # type: ignore[arg-type]
            finally:
                out.put(None)

        threading.Thread(target=work, name="studio-add", daemon=True).start()
        self._add_id = self.root.after(ADD_POLL_MS, self._poll_adding)

    def _poll_adding(self) -> None:
        self._add_id = None
        if self.closed:
            return
        done = False
        while True:
            try:
                item = self._add_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                done = True
                break
            self._add_outcomes.append(item)
        if not done:
            self._add_id = self.root.after(ADD_POLL_MS, self._poll_adding)
            return
        self.adding = False
        added = [o.ref for o in self._add_outcomes if o.ref is not None]
        self.refresh_project()
        if added:
            self.project_view.select(added[-1])
        show_info(self.root, files.add_summary(self._add_outcomes))
        on_done, self._add_on_done = getattr(self, "_add_on_done", None), None
        if on_done is not None:
            on_done(added)

    def new_script_file(self, parent: tk.Misc | None = None) -> str | None:
        """Ctrl+N: a new ``.vns`` file in ``script/`` (or the selected script subfolder),
        with an ``include`` line added to ``main.vns``'s text when the option is ticked.
        From New scene's **New file…** (``parent``: that dialog) the file isn't shown in the
        editor. The new file's ref, or None."""
        if self.closed or not self.file_ops_enabled():
            return None
        owner = self.root if parent is None else parent
        target = self._target_folder() if parent is None else None
        folder = target[1] if target is not None and target[0] == "script" else "script"
        answer = ask_text(owner, NEW_SCRIPT_ASK.format(folder=show(folder)), "new.vns",
                          ok="Create", option=NEW_SCRIPT_OPTION, option_value=True)
        if answer is None:
            return None
        name, include = answer
        result = files.new_script(self.paths, folder, name)
        if isinstance(result, files.Refusal):
            show_error(owner, result.text)
            return None
        self.refresh_project()
        if include and result != files.MAIN_REF:
            self._add_include(result)
        if parent is None:
            self.open_file(result)
            self.select_tab("editor")
        return result

    def _add_include(self, new_ref: str) -> None:
        """Put ``include "<path>"`` into ``main.vns``'s text as one undo step; it stays
        unsaved until the author saves."""
        if files.MAIN_REF not in self.refs:
            return
        record = self._record(files.MAIN_REF)
        if not record.editable:
            return
        widget = record.widget
        line = files.include_position(widget.get("1.0", "end-1c"))
        last = line_of(widget.index("end-1c"))
        text = files.include_line(new_ref)

        def act() -> None:
            if line > last:
                widget.insert("end-1c", "\n" + text)
            else:
                widget.insert(f"{line}.0", text + "\n")

        self._as_one_step(widget, act)

    def rename_selected(self) -> None:
        """F2: rename the selected file in its folder after a confirmation."""
        ref = self.project_view.selected()
        if self.closed or ref is None or not self.file_ops_enabled():
            return
        problem = self._fixed(ref)
        if problem is not None:
            show_error(self.root, problem)
            return
        old_name = ref.rsplit("/", 1)[1]
        answer = ask_text(self.root, RENAME_ASK.format(ref=show(ref)), old_name, ok="Rename",
                          hint=lambda name, f=ref.rsplit("/", 1)[0]: files.show_hint(f, name))
        if answer is None or answer[0] == old_name:
            return
        new_name = answer[0]
        record = self.files.get(ref)
        message = files.rename_message(ref, new_name, unsaved=record is not None
                                       and record.dirty)
        if ask(self.root, message, RENAME_BUTTONS, escape=1) != 0:
            return
        result = files.rename_file(self.paths, ref, new_name)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return
        if record is not None:
            self.files.pop(ref)
            if record.doc is not None:
                try:
                    retarget(record.doc, self.paths, result)
                except UserFacingError:
                    record.widget.destroy()
                    record = None
            if record is not None:
                self._forget_index(ref)
                record.ref = result
                self.files[result] = record
                self._baseline(record)
            elif self.current is not None and self.current.ref == ref:
                self.current = None
        self.refresh_project()
        if self.current is None:
            self._show_empty()
        self.project_view.select(result)
        self._update_marks()

    def delete_selected(self) -> None:
        """Delete: remove the selected file from the disk after a confirmation whose
        default and Esc are Cancel. An open copy closes; its unsaved text is dropped."""
        ref = self.project_view.selected()
        if self.closed or ref is None or not self.file_ops_enabled():
            return
        problem = self._fixed(ref)
        if problem is not None:
            show_error(self.root, problem)
            return
        record = self.files.get(ref)
        message = files.delete_message(ref, unsaved=record is not None and record.dirty)
        if ask(self.root, message, DELETE_BUTTONS, escape=1, default=DELETE_DEFAULT) != 0:
            return
        result = files.delete_file(self.paths, ref)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return
        self.refresh_project()
        self._drop_record(ref)

    def _fixed(self, ref: str) -> str | None:
        """Why the row ``ref`` can't be renamed or deleted, or None."""
        fixed = files.fixed_reason(ref)
        if fixed is not None:
            return fixed
        node = self.project_view.node(ref)
        if node is None or node.kind != "file":
            return files.FOLDER_FIXED
        return None

    def new_game(self) -> None:
        """File ▸ New game…: create a game from the starter in a new or empty folder and
        open it in its own Studio; this window stays open."""
        if self.closed:
            return
        folder = ask_directory(self.root)
        if folder is None:
            return
        result = files.new_game(folder)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return
        launch_studio(result)
