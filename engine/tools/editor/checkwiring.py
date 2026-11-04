"""Studio's checks and Problems panel (F45 ``04`` §7.2, ``07`` I-1, I-2; F44 ``03`` §3), as
the ``CheckWiring`` mixin of ``window.EditorWindow``.

A check runner is asked for a check at open, after saves, on F7, and ``CHECK_DEBOUNCE_MS``
after typing stops; load-only until the author's first Preview, Save or Check now. Each
finished check heads the Problems panel (a summary, then one row per item), sets gutter
markers on Tk marks that move with edits, drives the status bar's check items, and keeps the
last good check's name index and label links (``check_names``, ``check_links``,
``check_stale``). Then every callback in ``win.on_check_done`` runs with the result (F47:
Database, Guide and Game settings refresh there; F42's relayed build checks too). Every
check event also goes to F39's ``win.hot`` gate, with whether that check carried unsaved
text; ``request_saved_check`` is the gate's check of the saved files only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import tkinter as tk
from collections.abc import Sequence
from dataclasses import dataclass
from tkinter import ttk

from engine.core.editorreport import CHECK_DEBOUNCE_MS, CHECK_SLOW_S, CHECK_TIMEOUT_S
from engine.script.messages import show
from engine.tools.editor import icons
from engine.tools.editor.checker import CheckItem, CheckResult, CheckState, encode_overlay
from engine.tools.editor.document import SaveError, encode
from engine.tools.editor.preview import Report, ReportItem
from engine.tools.editor.syntax import PLAIN_COLOR
from engine.tools.editor.theme import THEME
from engine.tools.editor.views import autohide, panel_header
from engine.tools.editor.studiolook import (
    CHOSEN_BACKGROUND,
    FOCUS_BORDER,
    INACTIVE_SELECTION,
    LINK_FOREGROUND,
    MARKER_LETTERS,
    MARK_PREFIX,
    MESSAGE_FOREGROUND,
    PANEL_BACKGROUND,
    PANEL_INSET,
    PARAGRAPH_GAP,
    PARAGRAPH_PREFIX,
    SELECTION_BACKGROUND,
    SEVERITY_ICON_GAP,
    SEVERITY_ICON_PX,
    TAG_CHOSEN,
    TAG_CLICK,
    TAG_GAP,
    TAG_HINT,
    TAG_ICON_ROW,
    TAG_LINK,
    TEXT_PAD,
    line_of,
    plural,
)

if TYPE_CHECKING:
    from engine.tools.editor.window import OpenFile

PROBLEMS_HEADING = "Problems"
PROBLEMS_HINT = "Problems that stop a preview appear here."
NO_PROBLEMS = "No problems."
# Checks (F45 01 §6.3, §6.5, 04 §7.2 steps 6-8, C-4; amended 2026-11-02: the status bar).
CHECKING = "Checking…"
CHECK_OUT_OF_DATE = "Out of date"
CHECK_UNSAVED_NOT_CHECKED = "unsaved changes not checked"
ERROR_GLYPH = "\u2297"                  # ⊗, VS Code's error count
WARNING_GLYPH = "\u26a0"                # ⚠, its warning count
CHECK_TIMEOUT_TEXT = (f"The check took longer than {CHECK_TIMEOUT_S} seconds and was stopped. "
                      "Press F7 to try again.")
CHECK_CRASHED_TEXT = "The check stopped unexpectedly. Press F7 to try again."
SEVERITY_WORDS = {"error": "Error", "warning": "Warning", "info": "Info"}


def check_location(item: CheckItem) -> str:
    """F02's location form (``script/ch2.vns, line 9[, column 5]``, ``config.toml, line 2``),
    the file alone without a line, or ``""`` without a file."""
    if item.file is None:
        return ""
    where = show(item.file)
    if item.line is None:
        return where
    where += f", line {item.line}"
    return where + (f", column {item.column}" if item.column is not None else "")


def check_row_head(item: CheckItem) -> str:
    """``Error E43 script/ch2.vns, line 9``: the severity word, the code, the location."""
    word = SEVERITY_WORDS.get(item.severity, item.severity.capitalize())
    return " ".join(part for part in (word, item.code, check_location(item)) if part)


def check_row(item: CheckItem) -> str:
    """One problems-panel row: ``<Severity> <code> <location>: <text>`` (04 §7.2 step 7).
    Any ``source`` and code read the same way (PR-F45-08)."""
    return f"{check_row_head(item)}: {item.text}"


def check_counts(result: CheckResult) -> tuple[int, int]:
    """(errors, warnings) of a result. Info rows aren't counted (Gap G7)."""
    errors = sum(1 for item in result.problems if item.severity == "error")
    warnings = sum(1 for item in result.problems if item.severity == "warning")
    return errors, warnings


def check_summary(result: CheckResult) -> str:
    """``Checked: no problems.``, ``Checked: 2 errors, 1 warning.`` (01 §6.3): the problems
    panel's first row."""
    errors, warnings = check_counts(result)
    parts = [plural(count, word) for count, word in ((errors, "error"), (warnings, "warning"))
             if count]
    return "Checked: " + (", ".join(parts) if parts else "no problems") + "."


def counts_text(result: CheckResult) -> str:
    """The status bar's check counts, as VS Code shows them: ``⊗ 2  ⚠ 1`` (01 §6.5)."""
    errors, warnings = check_counts(result)
    return f"{ERROR_GLYPH} {errors}  {WARNING_GLYPH} {warnings}"


@dataclass
class Paragraph:
    """One paragraph in the problems panel."""

    tag: str
    item: ReportItem | CheckItem | None     # None for a head, tail or summary line
    clickable: bool


def _marker_severity(items: Sequence[CheckItem]) -> str | None:
    """``error`` if any item on the line is an error, else ``warning`` for a warning, else
    None (info has no marker)."""
    severities = {item.severity for item in items}
    if "error" in severities:
        return "error"
    return "warning" if "warning" in severities else None


class CheckWiring:
    """Check requests and results, gutter markers, the name index, and the Problems
    panel."""

    _check_overlay = False              # the newest request carried unsaved text (F39)
    _saved_only_check = False           # the newest request is F39's saved-files check

    def focus_problems(self) -> None:
        """A click on the status bar's check items: the keyboard focus to Problems."""
        if not self.closed:
            self.problems.focus_set()

    def _build_problems_panel(self) -> None:
        frame = self.problems_frame
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        panel_header(frame, PROBLEMS_HEADING, self.scale).grid(row=0, column=0, columnspan=2,
                                                               sticky="ew")
        self.problems = tk.Text(
            frame, wrap="word", width=1, height=1, font=self.ui_font,
            background=PANEL_BACKGROUND, foreground=PLAIN_COLOR,
            selectbackground=SELECTION_BACKGROUND, inactiveselectbackground=INACTIVE_SELECTION,
            padx=self._px(PANEL_INSET) - 1, pady=self._px(TEXT_PAD), highlightthickness=1,
            highlightbackground=PANEL_BACKGROUND, highlightcolor=FOCUS_BORDER, borderwidth=0,
            takefocus=1, cursor="arrow")
        panel = self.problems
        panel.tag_configure(TAG_HINT, foreground=MESSAGE_FOREGROUND)
        # Each row starts with its severity's icon; its wrapped lines align after it.
        size = self._px(SEVERITY_ICON_PX)
        self._severity_icons = {
            name: icons.photo(self.root, name, size, THEME[key])
            for name, key in (("error", "marker.error"), ("warning", "marker.warning"),
                              ("info", "info"), ("success", "success"))}
        panel.tag_configure(TAG_ICON_ROW, lmargin2=size + self._px(SEVERITY_ICON_GAP))
        panel.tag_configure(TAG_LINK, foreground=LINK_FOREGROUND, underline=True)
        panel.tag_configure(TAG_GAP, spacing1=self._px(PARAGRAPH_GAP))
        panel.tag_configure(TAG_CHOSEN, background=CHOSEN_BACKGROUND)
        panel.tag_configure("sel", foreground=PLAIN_COLOR)
        panel.tag_bind(TAG_CLICK, "<Enter>", lambda _e: panel.configure(cursor="hand2"))
        panel.tag_bind(TAG_CLICK, "<Leave>", lambda _e: panel.configure(cursor="arrow"))
        panel.tag_raise("sel")
        panel.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(frame, orient="vertical", command=panel.yview,
                            style="Side.Vertical.TScrollbar")
        panel.configure(yscrollcommand=autohide(bar, row=1, column=1, sticky="ns"))
        self.show_hint(PROBLEMS_HINT)
        # A click focuses the panel even though its text is read-only. A click on a link
        # (not a drag that selects text) jumps.
        panel.bind("<Button-1>", lambda _e: panel.focus_set(), add="+")
        panel.bind("<ButtonRelease-1>", self._on_panel_click, add="+")
        panel.bind("<FocusIn>", self._on_panel_focus_in, add="+")
        panel.bind("<FocusOut>", lambda _e: panel.tag_remove(TAG_CHOSEN, "1.0", "end"),
                   add="+")
        panel.bind("<Up>", lambda _e: self._break(self.choose_paragraph, -1))
        panel.bind("<Down>", lambda _e: self._break(self.choose_paragraph, 1))
        for key in ("<Return>", "<KP_Enter>"):
            panel.bind(key, lambda _e: self._break(self.activate_chosen))

    # --- Checks (F45 04 §7.2, 07 I-1, I-2) --------------------------------------------------

    def request_check(self) -> None:
        """Ask the check runner for a check of the saved files plus the unsaved text of every
        dirty document (the overlay; C-4: past its caps, the saved files only, and the
        status says so). Load-only until the window is armed (F45 ``07`` I-1). Never
        blocks."""
        if self.closed:
            return
        self._cancel_debounce()
        self._reindex()                     # the digests this request's text has (04 §6.1.4)
        # F58 Q2: with each file's stamp, so a file that moves before the next listing
        # keeps its old digests (dirty files: None, adopted at the result).
        self._check_snapshot = (self.edit_serial, {
            ref: dict(index.digests) for ref, index in self.scene_indexes.items()}, {
            ref: None if ref in self.files and self.files[ref].dirty else self._stamp_of(ref)
            for ref in self.scene_indexes})
        overlay, unsaved = self._overlay()
        self._check_unsaved = unsaved
        self._check_overlay = overlay is not None
        self._saved_only_check = False
        self._check_serial = self.edit_serial
        self.check_running = True
        self._check_failure = None
        self.check_runner.request(overlay, self.edit_serial, launch=self.armed)
        self._update_check_status()

    def request_saved_check(self) -> None:
        """F39's gate: a full (armed) check of the files as saved, without the unsaved text
        of open files (the status says so while there is any). Once it is done, the usual
        check with that text follows."""
        if self.closed:
            return
        self._cancel_debounce()
        self.armed = True
        self._check_snapshot = None         # its links aren't the editor text's
        self._check_unsaved = bool(self.dirty_files())
        self._check_overlay = False
        self._saved_only_check = True
        self._check_serial = self.edit_serial
        self.check_running = True
        self._check_failure = None
        self.check_runner.request(None, self.edit_serial, launch=True)
        self._update_check_status()

    def _overlay(self) -> tuple[bytes | None, bool]:
        """(overlay, whether unsaved text is left out): ``encode(doc, text)`` of each dirty
        document, or None when there is none or ``encode_overlay`` refuses."""
        dirty = self.dirty_files()
        if not dirty:
            return None, False
        entries: list[tuple[str, bytes]] = []
        for record in dirty:
            assert record.doc is not None
            try:
                entries.append((record.ref, encode(record.doc,
                                                   record.widget.get("1.0", "end-1c"))))
            except SaveError:                   # a lone surrogate: saved files only
                return None, True
        overlay = encode_overlay(entries)
        return overlay, overlay is None

    def check_now(self) -> None:
        """F7: check now; arms the window."""
        self.armed = True
        self.request_check()

    def _schedule_auto_check(self) -> None:
        """Check ``CHECK_DEBOUNCE_MS`` after the last content change (PR-F45-11)."""
        self._cancel_debounce()
        if not self.closed:
            self._debounce_id = self.root.after(CHECK_DEBOUNCE_MS, self._auto_check)

    def _cancel_debounce(self) -> None:
        if self._debounce_id is not None:
            try:
                self.root.after_cancel(self._debounce_id)
            except tk.TclError:
                pass
            self._debounce_id = None

    def _auto_check(self) -> None:
        """The debounced check; paused while the last check took over ``CHECK_SLOW_S``
        (saves and F7 still check)."""
        self._debounce_id = None
        if self.closed or (self.check_result is not None
                           and self.check_result.seconds > CHECK_SLOW_S):
            return
        self.request_check()

    def apply_check_events(self, events: Sequence[object]) -> None:
        """The runner's events (polled every 100 ms): ``DONE`` replaces the result, the
        rows, the markers and the name index in one step; ``TIMEOUT`` and ``CRASHED`` keep
        them and show one status line."""
        changed = False
        for event in events:
            state = getattr(event, "state", None)
            if state not in (CheckState.DONE, CheckState.TIMEOUT, CheckState.CRASHED):
                continue                        # STARTED: still Checking…
            if getattr(event, "serial", -1) >= self._check_serial:
                self.check_running = False
            if state is CheckState.DONE:
                result = getattr(event, "result", None)
                if result is not None:
                    self._apply_result(result)
                    self._check_failure = None
            else:
                self._check_failure = (CHECK_TIMEOUT_TEXT if state is CheckState.TIMEOUT
                                       else CHECK_CRASHED_TEXT)
            changed = True
            saved_only = self._saved_only_check
            self._saved_only_check = False
            hot = getattr(self, "hot", None)
            if hot is not None and not self.closed:     # F39's gate (it may ask again)
                hot.check_event(event, overlay=self._check_overlay)
                self._sync_hot_suffix()         # held, or no longer: the summary's end
            if saved_only and not self._saved_only_check and self.dirty_files():
                self._schedule_auto_check()     # back to checking the editor's text
        if changed and not self.closed:
            self._update_check_status()

    def _apply_result(self, result: CheckResult) -> None:
        self.check_result = result
        # The name index keeps every kind this run didn't send, and the links of the last
        # check that loaded the script (04 §4.2).
        names = dict(self._check_names)
        names.update({kind: tuple(entries) for kind, entries in result.names.items()})
        if result.loaded:            # a kind this run counted 0 of is now empty (2026-11-02)
            names.update({kind: () for kind, total in result.name_totals.items()
                          if total == 0})
        self._check_names = names
        if result.links is not None:
            self._check_links = tuple(result.links)
            snapshot = self._check_snapshot
            if snapshot is not None and snapshot[0] == result.serial:
                # The checked digests (§6.1.4): dirty files now; the others after the
                # first listing that starts after this result (F58 Q2, I-7).
                dirty = {ref: d for ref, d in snapshot[1].items() if snapshot[2].get(ref)
                         is None and ref in self.scene_indexes}
                for ref, digests in dirty.items():
                    self._checked[ref] = digests
                rest = {ref: d for ref, d in snapshot[1].items() if ref not in dirty}
                watch = self.watch
                self._adopt = (watch.started if watch is not None else 0, rest,
                               snapshot[2])
                self._maybe_adopt()
        self._check_stale = result.links is None
        self.big_batch_done()                   # F58 PR-10: S4's check has landed
        self._index_changed()
        for record in self.files.values():
            self._place_marks(record)
        self.render_panel()
        self._schedule_refresh()
        for callback in list(self.on_check_done):     # F47: Database, Guide, Settings
            callback(result)

    def check_status_text(self) -> str:
        """The status bar's check message without the cursor's item (04 §7.2 step 6, 01
        §6.5): the timeout or crash line; ``Checking…`` while a check runs; ``Out of date``
        after an edit the newest result hasn't seen; ``""`` otherwise. ``unsaved changes not
        checked`` is added while the overlay was left out (C-4)."""
        result = self.check_result
        if self._check_failure is not None and not self.check_running:
            return self._check_failure
        if self.check_running:
            text = CHECKING
        elif result is not None and result.serial < self.edit_serial:
            text = CHECK_OUT_OF_DATE
        else:
            text = ""
        if self._check_unsaved:
            unsaved = CHECK_UNSAVED_NOT_CHECKED
            text = f"{text} ({unsaved})" if text else unsaved[0].upper() + unsaved[1:]
        return text

    def _update_check_status(self) -> None:
        """The status bar's check items: the newest result's counts, and the cursor line's
        first check item when it has one, else ``check_status_text``."""
        if self.closed:
            return
        result = self.check_result
        self.check_counts.configure(text=counts_text(result) if result is not None else "")
        text = self.check_status_text()
        record = self.current
        if record is not None and record.marks:
            line = line_of(record.widget.index("insert"))
            items = self._line_items(record, line, line).get(line)
            if items:
                text = items[0].text
        if text != self._check_status_shown:
            self._check_status_shown = text
            self.check_status.configure(text=text)

    # --- Markers (04 §7.2 step 8) -----------------------------------------------------------

    def _place_marks(self, record: OpenFile) -> None:
        """Replace ``record``'s check marks: one Tk mark at ``line.0`` for each item of the
        newest result in its file. Right gravity, so lines inserted at the start of a marked
        line push the mark down with its text."""
        widget = record.widget
        for name in record.marks:
            widget.mark_unset(name)
        record.marks = {}
        result = self.check_result
        if result is None or not record.editable:
            return
        number = 0
        for item in result.problems:
            if item.file != record.ref or item.line is None:
                continue
            name = f"{MARK_PREFIX}{number}"
            number += 1
            widget.mark_set(name, f"{item.line}.0")
            widget.mark_gravity(name, "right")
            record.marks[name] = item

    def _line_items(self, record: OpenFile, first: int,
                    last: int) -> dict[int, list[CheckItem]]:
        """Line -> its check items in result order, for lines ``first``..``last`` only (the
        marks are walked from ``first.0``)."""
        if not record.marks:
            return {}
        found: dict[int, list[tuple[int, CheckItem]]] = {}
        widget = record.widget
        name = widget.mark_next(f"{first}.0")
        while name:
            line = line_of(widget.index(name))
            if line > last:
                break
            item = record.marks.get(name)
            if item is not None:
                found.setdefault(line, []).append((int(name[len(MARK_PREFIX):]), item))
            name = widget.mark_next(name)
        return {line: [item for _n, item in sorted(pairs, key=lambda pair: pair[0])]
                for line, pairs in found.items()}

    def check_markers(self) -> dict[int, str]:
        """Line -> ``E`` or ``W`` for every marked line of the file on screen."""
        record = self.current
        if record is None or not record.marks:
            return {}
        last = line_of(record.widget.index("end-1c"))
        markers = {}
        for line, items in self._line_items(record, 1, last).items():
            letter = _marker_severity(items)
            if letter is not None:
                markers[line] = MARKER_LETTERS[letter]
        return markers

    # --- The last good check's names and links (F45 04 §4.2; step 4 sets them) --------------

    @property
    def check_names(self) -> dict:
        """kind -> name entries (``NameEntry`` or ``(name, file, line)`` rows): what
        completion offers, and the story map's labels with their places."""
        return self._check_names

    @check_names.setter
    def check_names(self, value: dict | None) -> None:
        self._check_names = dict(value or {})
        self._index_changed()

    @property
    def check_links(self) -> tuple:
        """The label links (``LabelLink`` or ``(src, dst, kind, file, line)`` rows)."""
        return self._check_links

    @check_links.setter
    def check_links(self, value: Sequence[object] | None) -> None:
        self._check_links = tuple(value or ())
        self._index_changed()

    @property
    def check_stale(self) -> bool:
        """True while the newest check didn't load the script: the map is "out of date"."""
        return self._check_stale

    @check_stale.setter
    def check_stale(self, value: bool) -> None:
        self._check_stale = bool(value)
        self._index_changed()

    # --- Problems panel (03 §3, §7.6 "Problems panel") -------------------------------------

    def _clear_panel(self) -> tk.Text:
        panel = self.problems
        panel.configure(state="normal")
        panel.delete("1.0", "end")
        for tag in panel.tag_names():
            if tag.startswith(PARAGRAPH_PREFIX):
                panel.tag_delete(tag)
        panel.configure(cursor="arrow")
        self.paragraphs = []
        self._chosen = None
        return panel

    def show_hint(self, text: str) -> None:
        """A gray line instead of preview problems (below the check rows)."""
        self._panel_view = ("hint", text)
        self.render_panel()

    def show_report(self, report: Report) -> None:
        """The report's paragraphs, in the error screen's order and wording, below the check
        rows (PR-F45-08)."""
        self._panel_view = ("report", report)
        self.render_panel()

    def _check_entries(self) -> list[tuple[str, object, bool, int]]:
        """The check part of the panel: (text, item, clickable, link length)."""
        result = self.check_result
        if result is None:
            return []
        summary = check_summary(result) + self.hot_suffix()     # F39: an update held
        entries: list[tuple[str, object, bool, int]] = [(summary, None, False, 0)]
        everything = self.show_warnings.get()
        for item in result.problems:
            if everything or item.severity == "error":
                clickable = item.line is not None and self._openable(item.file)
                entries.append((check_row(item), item, clickable,
                                len(check_row_head(item)) if clickable else 0))
        return entries

    def render_panel(self) -> None:
        """The problems panel: the newest check's summary and rows (warning and info rows
        hidden by the View toggle), then the newest preview or start-value report in F44's
        text, or its gray hint. A paragraph with a line in a file the editor shows is a
        link: its location is underlined in the link color, the pointer is a hand over it, and
        a click or Enter jumps."""
        if self.closed:
            return
        panel = self._clear_panel()
        entries = self._check_entries()
        kind, value = self._panel_view
        hint: str | None = None
        if kind == "report":
            assert isinstance(value, Report)
            if value.head is not None:
                entries.append((value.head, None, False, 0))
            for item in value.items:
                clickable = (item.line is not None
                             and item.file in self.refs)    # the Script group (amended A-28)
                colon = item.text.find(":") if clickable else -1
                entries.append((item.text, item, clickable, max(colon, 0)))
            entries += [(line, None, False, 0) for line in value.tail]
        else:
            hint = str(value)
        for index, (text, item, clickable, link) in enumerate(entries):
            tag = f"{PARAGRAPH_PREFIX}{index}"
            start = panel.index("end-1c")
            if item is not None:        # a row: its severity's icon first (08 §7)
                self._panel_icon(getattr(item, "severity", "error"), "end")
            begin = panel.index("end-1c")
            panel.insert("end", text + ("\n" if index < len(entries) - 1 else ""))
            panel.tag_add(tag, start, "end-1c")
            if item is not None:
                panel.tag_add(TAG_ICON_ROW, start, "end-1c")
            if index:
                panel.tag_add(TAG_GAP, start, f"{start} lineend")
            if clickable:
                if link > 0:
                    panel.tag_add(TAG_LINK, begin, f"{begin}+{self._tk_length(text[:link])}c")
                panel.tag_add(TAG_CLICK, start, "end-1c")
            self.paragraphs.append(Paragraph(tag, item, clickable))   # type: ignore[arg-type]
        if hint is not None:
            if entries:
                start = panel.index("end-1c")
                panel.insert("end", "\n" + hint, TAG_HINT)
                panel.tag_add(TAG_GAP, f"{start}+1c", "end-1c")
            else:
                if hint == NO_PROBLEMS:     # clean: the success icon (08 §9)
                    self._panel_icon("success", "1.0")
                panel.insert("end", hint, TAG_HINT)
        panel.tag_raise("sel")
        panel.configure(state="disabled")
        panel.yview_moveto(0)

    def _panel_icon(self, severity: str, where: str) -> None:
        """A severity icon at ``where`` in Problems: an image, so the panel's text (what
        ``get`` returns) stays the report's wording (UI-F45-03)."""
        image = self._severity_icons.get(severity, self._severity_icons["error"])
        self.problems.image_create(where, image=image, align="center",
                                   padx=self._px(SEVERITY_ICON_GAP) // 2)

    def panel_paragraphs(self) -> list[str]:
        """The panel's paragraphs as shown (for tests and the docs)."""
        panel = self.problems
        texts = []
        for paragraph in self.paragraphs:
            ranges = panel.tag_ranges(paragraph.tag)
            texts.append(panel.get(ranges[0], ranges[1]).removesuffix("\n") if ranges else "")
        return texts

    def _paragraph_at(self, index: str) -> int | None:
        panel = self.problems
        for where in (index, f"{index} -1c"):
            for tag in panel.tag_names(where):
                if tag.startswith(PARAGRAPH_PREFIX) and tag[len(PARAGRAPH_PREFIX):].isdigit():
                    return int(tag[len(PARAGRAPH_PREFIX):])
        return None

    def _on_panel_click(self, event: tk.Event) -> None:
        if self.problems.tag_ranges("sel"):
            return                              # a drag that selected text, not a click
        index = self._paragraph_at(self.problems.index(f"@{event.x},{event.y}"))
        if index is not None:
            self._choose(index)
            self.activate_paragraph(index)

    def _on_panel_focus_in(self, _event: tk.Event) -> None:
        """The first clickable error is selected when the panel gets focus (03 §3)."""
        if not self.paragraphs:
            return
        if self._chosen is None:
            clickable = [i for i, p in enumerate(self.paragraphs) if p.clickable]
            self._chosen = clickable[0] if clickable else 0
        self._choose(self._chosen)

    def choose_paragraph(self, step: int) -> None:
        """Up and Down move the selected paragraph."""
        if not self.paragraphs:
            return
        current = self._chosen if self._chosen is not None else -step
        self._choose(min(len(self.paragraphs) - 1, max(0, current + step)))

    def _choose(self, index: int) -> None:
        panel = self.problems
        self._chosen = index
        panel.tag_remove(TAG_CHOSEN, "1.0", "end")
        ranges = panel.tag_ranges(self.paragraphs[index].tag)
        if ranges:
            panel.tag_add(TAG_CHOSEN, ranges[0], ranges[1])
            panel.see(ranges[0])

    def activate_chosen(self) -> None:
        """Enter in the panel: jump to the selected error if it is clickable."""
        if self._chosen is not None:
            self.activate_paragraph(self._chosen)

    def activate_paragraph(self, index: int) -> None:
        """Jump to paragraph ``index``'s error. Nothing happens for one that can't be
        clicked."""
        paragraph = self.paragraphs[index]
        item = paragraph.item
        if paragraph.clickable and item is not None and item.file is not None and \
                item.line is not None:
            self.jump_to(item.file, item.line, item.column)
