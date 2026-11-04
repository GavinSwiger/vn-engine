"""The Assistant pane in the Studio window, as the ``AssistWiring`` mixin of
``window.EditorWindow`` (F48 ``01-design.md`` §6.1, §6.6, PR-F48-14, -19 to -22, -24;
``04-technical.md`` §3.2, §7.4, §7.7; ``05-security.md`` SEC-F48-12, -16, -20, -21; ``07``
I-7; AC-F48-30, -31, -44, -46 to -49, -53, -56).

Why this module exists: the pane must never hold Studio up, and nothing may leave the
computer before the author agrees. So a Send, on the Tk thread, only checks the token
limit, the key and consent, takes a ``Snapshot`` of the unsaved editor texts, the cursor and
the selection, and starts a ``ChatRun`` (a daemon thread) with a fresh provider and the
pane's own ``CheckService``. Tk then polls the run's queue every 50 ms through
``EventPump`` (at most 8 KiB of text per poll) and draws what came: the Sent line (from the
tool layer's record), the streamed answer, activity lines, cards and the usage line.

- The pane shares the Guide's right-edge column: opening one hides the other; whether it is
  open is remembered per game (``studiostate.assistant_open``). The Play bar's **AI
  Assistant**, View ▸ AI Assistant and Ctrl+Shift+A toggle it; F6 reaches it after Help.
- With no key (Anthropic, OpenAI) the pane shows its empty state and Studio sends nothing.
  Keys and settings come from ``aisettings.AiSession`` (``win.ai``); every keystore call is
  off the Tk thread.
- Stop and Esc cancel the run (never blocking); the partial answer stays, "(stopped)".
- Closing the window cancels the run and stops the pane's check child as well as the
  window's own (07 I-7). The pane's ``CheckService`` runs its child without the key
  variables (``procs.without_keys``, through ``CheckRunner``).
- Cards (``assistpane.Card``, §6.3, PR-F48-23, -29; 04 §7.4): **Apply** moves each file's
  plan onto its live editor text (``edits.rebase``; a changed scene is Stale and nothing
  changes), makes a new file empty through F45's New script file, then ``apply_plan`` (one
  undo step per file, unsaved, the check scheduled). Nothing else reaches the disk until
  the author saves. **Undo** follows F46's map-undo rule (every file's ``changes`` token
  unchanged; a made file is deleted through F45's Delete). **Ask again** sends §6.3's
  message with a fresh snapshot.
- F58 (PR-14, 15; 04 §7.10): the newest open card's effect shows on the story map as a
  dashed preview, cleared on Apply (its new boxes land where the preview put them),
  Discard, Stale, New chat and the pane closing; a card whose touched scene changes goes
  Stale at once. Preview reads of closed files are capped at ``PREVIEW_READ_MAX`` (I-12);
  nothing is written before Apply (SEC-F48-04, -09, -12, -20 unchanged).

Imports ``tkinter``, its own package and ``tools.assistant`` (a Tk module: the import-rule
exception). Logs nothing about the chat (SEC-F48-14: ``chat`` logs the provider, status and
step count).
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Any

from collections.abc import Sequence

from engine.core.constants import BUILTIN_POSITIONS
from engine.script.assetgroups import CONFIG_REF
from engine.tools.assistant.chat import (
    STATUS_STOPPED,
    Activity,
    CardEvent,
    Chat,
    ChatRun,
    Done,
    EventPump,
    SentUpdate,
    TextDelta,
    Waiting,
    Working,
    chat_total_text,
)
from engine.tools.assistant.edits import rebase
from engine.tools.assistant.keystore import Slot
from engine.tools.assistant.providers import CLAUDE_CODE, COMPATIBLE, PANE_NAMES, errors
from engine.tools.assistant.reference import build_reference
from engine.tools.assistant.workspace import CheckService, Snapshot
from engine.tools.editor import document, files, livemap, scenes, studiostate
from engine.tools.editor.aisettings import (
    Background,
    ensure_consent,
    open_ai_settings,
    session_for,
    slot_of,
)
from engine.tools.editor.assistpane import (
    APPLIED,
    APPLIED_MANY,
    ASK_AGAIN_TEXT,
    STALE,
    UNDO_REFUSED,
    UNDONE,
    AssistPane,
    Card,
    first_line,
    model_line,
    new_text,
)
from engine.tools.editor.declarations import position_rows
from engine.tools.editor.files import Refusal
from engine.tools.editor.guidepane import GUIDE_MIN_WIDTH, GUIDE_WIDTH
from engine.tools.editor.livemap import stale_by_index
from engine.tools.editor.scriptedit import FilePlan, Plan, apply_lines, verify

POLL_MS = 50                            # 04 §7.7
POLL_TIMES_KEPT = 200
MENU = "AI Assistant"                   # View ▸ AI Assistant (Ctrl+Shift+A)
# Done kinds that offer [Open settings] (S8 notes).
SETTINGS_KINDS = frozenset({"key", "no_key", "model", "forbidden", "token_limit"})
PREVIEW_READ_MAX = 1024 * 1024          # F58 I-12: a closed file read on Tk for the preview
PREVIEW_NEW_MAX = 64 * 1024             # F58: a new file's proposed text, parsed in memory


def _script_ref(ref: str) -> bool:
    """SEC-F48-12: Apply touches only ``script/**.vns``."""
    return ref.startswith("script/") and ref.endswith(".vns")


def _disk_text(paths: object, ref: str) -> str | None:
    """``ref``'s text on disk as Studio opens it; None when it can't be read."""
    return getattr(document.open_document(paths, ref), "text", None)  # type: ignore[arg-type]


class AssistWiring:
    """The pane in the window: showing it, Send/Stop/New chat, the 50 ms poll, consent,
    the cards, and closing."""

    assistant_shown = False
    assist_pane: AssistPane
    assist_run: ChatRun | None = None
    assist_checks: CheckService | None = None
    _assist_preview_key: tuple | None = None       # F58: what the preview was built from
    _assist_preview: tuple | None = None           # (card, Preview, dry-run layout)

    # --- Building and showing --------------------------------------------------------------

    def _build_assistant(self) -> None:
        """Made after the Guide; shown when this game's pane was left open (and the Guide
        wasn't: they share the column)."""
        self.assist_pane = AssistPane(
            self.hpane, fonts=self.fonts, scale=self.scale, on_send=self.assist_send,
            on_stop=self.assist_stop, on_new_chat=self.assist_new_chat,
            on_close=self.toggle_assistant, on_settings=self.assist_settings,
            on_connect=self.connect_ai_app, on_link=self.assist_link,
            on_card=self.assist_card_action, listed=self._assist_listed)
        self.assist_chat = Chat()
        self.assist_run = None
        self.assist_checks = None
        self.assist_cards: list[Card] = []
        self.assist_poll_times: list[float] = []
        self._assist_pump: EventPump | None = None
        self._assist_poll_id: str | None = None
        self._assist_bg: Background | None = None
        self._assist_loading: Slot | None = None
        self._assist_listening = False
        state = studiostate.read_state(self.paths.root)
        if isinstance(state, studiostate.StudioState) and state.assistant_open \
                and not self.guide_shown:
            self.show_assistant(True, save=False)

    def assistant_open(self) -> bool:
        return bool(self.assist_pane.frame.winfo_manager())

    def toggle_assistant(self) -> None:
        """The Play bar's AI Assistant, View ▸ AI Assistant and Ctrl+Shift+A: show the pane
        (its input focused) or hide it."""
        if self.closed:
            return
        shown = not self.assistant_shown
        self.show_assistant(shown)
        if shown:
            self.assist_pane.focus_input()

    def show_assistant(self, shown: bool, *, save: bool = True) -> None:
        """Show or hide the pane in the Guide's column (the Guide closes first)."""
        if shown == self.assistant_shown:
            return
        frame = self.assist_pane.frame
        if shown:
            if self.guide_shown:
                self.toggle_guide()                 # hides the Guide and remembers that
            self.hpane.add(frame, after=self.vpane, width=self._px(GUIDE_WIDTH),
                           minsize=self._px(GUIDE_MIN_WIDTH), stretch="never")
            self._assist_start_session()
        else:
            self.hpane.forget(frame)
            self.assist_clear_preview()             # F58 PR-15: the pane closed
        self.assistant_shown = shown
        self.play_bar.set_assistant(shown)
        if save:
            self.save_studio_state(assistant_open=shown)

    def show_guide(self, shown: bool) -> None:
        """The Guide and the pane share the column: showing the Guide hides the pane."""
        if shown and self.assistant_shown:
            self.show_assistant(False)
        super().show_guide(shown)                   # type: ignore[misc]

    # --- Settings and the key --------------------------------------------------------------

    def _assist_start_session(self) -> None:
        """First show: the settings (``win.ai``), its listener, and the key (off the Tk
        thread). Nothing is read before the pane opens."""
        session = session_for(self)
        if not self._assist_listening:
            session.listeners.append(self._assist_settings_changed)
            self._assist_listening = True
            # The language reference (~18 KB, cached) is built now, off the Tk thread, so
            # the first Send's worker doesn't spend its first poll on it.
            self._assist_background().run(build_reference, lambda _r: None)
        self._assist_settings_changed()

    def _assist_background(self) -> Background:
        if self._assist_bg is None:
            self._assist_bg = Background(self.root)
        return self._assist_bg

    def _assist_settings_changed(self) -> None:
        """Settings or the key changed: the model line, the empty state, and a key load
        when the current slot's key isn't known yet."""
        if self.closed:
            return
        session = session_for(self)
        prefs = session.prefs
        target = session.target()
        name = PANE_NAMES.get(prefs.provider, target.host or target.name)
        self.assist_pane.set_model_line(model_line(name, prefs.model()))
        slot = slot_of(target)
        known = session.key_known and session.key_slot == slot
        if slot is not None and not known:
            self._assist_load_key(slot)
        self.assist_pane.show_empty(not self._assist_configured())

    def _assist_configured(self) -> bool:
        """A request could go out: a compatible server (a key is optional), or a key for
        the current provider. Until the key load answers, the empty state shows."""
        session = session_for(self)
        target = session.target()
        if target.provider == COMPATIBLE:
            return target.error is None
        return session.key is not None and session.key_slot == slot_of(target)

    def _assist_load_key(self, slot: Slot, then: Any = None) -> None:
        if self._assist_loading == slot and then is None:
            return
        self._assist_loading = slot
        session = session_for(self)
        use_env = slot.provider in session.prefs.env

        def done(result: Any) -> None:
            if self._assist_loading == slot:
                self._assist_loading = None
            if self.closed:
                return
            if slot_of(session.target()) == slot:
                session.set_key(slot, result)
            if then is not None:
                then()

        self._assist_background().run(lambda: session.resolve_key(slot, use_env), done)

    def assist_settings(self) -> None:
        """⚙, [Set up AI…] and [Open settings]: Studio settings ▸ AI."""
        open_ai_settings(self)

    # --- Send, Stop, New chat --------------------------------------------------------------

    def assist_send(self, *, retried: bool = False, request: str | None = None) -> bool:
        """**Send** (Enter): the request goes out only after the token limit, the key and
        consent pass; Cancel in the consent dialog sends nothing and keeps the text.
        ``request`` (a card's Ask again) is sent in place of the input, which is kept. True
        when a run started now."""
        pane = self.assist_pane
        if self.closed:
            return False
        if self.assist_run is not None:
            if request is None:
                self.assist_stop()
            return False
        typed = request is None
        request = (pane.input_text() if request is None else request).strip()
        if not request:
            return False
        session = session_for(self)
        prefs = session.reload()
        chat = self.assist_chat
        chat.steps, chat.token_limit = prefs.steps, prefs.token_limit
        blocked = chat.blocked()
        if blocked is not None:
            pane.notice(blocked, settings=True)
            return False
        target = session.target()
        if target.provider == CLAUDE_CODE:      # the author's own Claude Code: no key
            if not ensure_consent(session, self.root, target, fonts=self.fonts):
                return False
            from engine.tools.assistant.providers.claudecode import ClaudeCodeRun
            snapshot = self.assist_snapshot()
            return self._assist_start(
                lambda: ClaudeCodeRun(chat, model=prefs.model(CLAUDE_CODE), paths=self.paths,
                                      snapshot=snapshot, request=request,
                                      checks=self.assist_checks),
                request, typed)
        if target.error is not None:
            pane.notice(target.error, settings=True)
            return False
        slot = slot_of(target)
        if slot is None:
            return False
        if not (session.key_known and session.key_slot == slot):
            if retried:
                return False
            again = None if typed else request
            self._assist_load_key(slot, then=lambda: self.assist_send(retried=True,
                                                                      request=again))
            return False
        key = session.key
        if key is None and target.provider != COMPATIBLE:
            pane.notice(errors.NO_KEY, settings=True)
            return False
        if not ensure_consent(session, self.root, target, fonts=self.fonts):
            return False
        snapshot = self.assist_snapshot()
        try:
            provider = session.provider(key=key)
        except errors.AddressError as exc:
            pane.notice(exc.text, settings=True)
            return False
        return self._assist_start(
            lambda: ChatRun(chat, provider, paths=self.paths, snapshot=snapshot,
                            request=request, checks=self.assist_checks),
            request, typed)

    def _assist_start(self, make_run: Any, request: str, typed: bool) -> bool:
        """Start the run ``make_run()`` builds (after the check service exists)."""
        pane = self.assist_pane
        if self.assist_checks is None:
            self.assist_checks = CheckService(self.paths.root)
        if typed:
            pane.clear_input()
        pane.start_exchange(request)
        run = make_run()
        self.assist_run = run
        self._assist_pump = EventPump(run.events)
        pane.set_running(True)
        run.start()
        self._assist_schedule()
        return True

    def assist_snapshot(self) -> Snapshot:
        """The worker's view, taken here on the Tk thread: every unsaved document's editor
        text, the open file, the cursor (line, column from 0) and the selection."""
        texts: dict[str, str] = {}
        docs: dict[str, Any] = {}
        for record in self.dirty_files():
            if record.editable:
                texts[record.ref] = record.widget.get("1.0", "end-1c")
                docs[record.ref] = record.doc
        record = self.current
        open_file = cursor = selection = None
        if record is not None and record.editable and (record.ref in self.refs
                                                       or record.ref == CONFIG_REF):
            open_file = record.ref
            widget = record.widget
            line, column = (int(part) for part in str(widget.index("insert")).split("."))
            cursor = (line, column)
            found = widget.tag_ranges("sel")
            if len(found) >= 2:
                first = [int(p) for p in str(found[0]).split(".")]
                last = [int(p) for p in str(found[1]).split(".")]
                selection = (first[0], first[1], last[0], last[1])
        return Snapshot(texts=texts, docs=docs, armed=bool(self.armed),
                        check=self.check_result, open_file=open_file, cursor=cursor,
                        selection=selection)

    def assist_stop(self) -> None:
        """Stop / Esc: cancel the run (never blocks); its Done arrives at the next poll."""
        run = self.assist_run
        if run is not None:
            run.cancel()

    def assist_new_chat(self) -> None:
        """New chat: a running request stops; the transcript and the token count start
        from zero (the old run writes only into its own chat)."""
        self.assist_stop()
        self._assist_drop_run()
        self.assist_chat = Chat()
        self.assist_cards = []
        self.assist_clear_preview()                 # F58 PR-15
        self.assist_pane.clear()
        self.assist_pane.set_total(chat_total_text(0))
        self.assist_pane.show_empty(not self._assist_configured())

    def _assist_drop_run(self) -> None:
        self.assist_run = None
        self._assist_pump = None
        if self._assist_poll_id is not None:
            try:
                self.root.after_cancel(self._assist_poll_id)
            except tk.TclError:
                pass
            self._assist_poll_id = None
        self.assist_pane.set_running(False)

    # --- The 50 ms poll --------------------------------------------------------------------

    def _assist_schedule(self) -> None:
        if self._assist_poll_id is None and not self.closed:
            self._assist_poll_id = self.root.after(POLL_MS, self._assist_poll)

    def _assist_poll(self) -> None:
        """Draw what the worker posted (≤ 8 KiB of text); again in 50 ms until its Done."""
        self._assist_poll_id = None
        pump = self._assist_pump
        if self.closed or pump is None:
            return
        started = time.perf_counter()
        done = False
        for event in pump.poll():
            done = self._assist_event(event) or done
        self.assist_poll_times.append(time.perf_counter() - started)
        del self.assist_poll_times[:-POLL_TIMES_KEPT]
        if done:
            self._assist_drop_run()
        else:
            self._assist_schedule()

    def _assist_event(self, event: Any) -> bool:
        """One worker event onto the pane; True for the run's Done."""
        pane = self.assist_pane
        if isinstance(event, TextDelta):
            pane.answer_text(event.text)
        elif isinstance(event, (Working, Waiting)):
            pane.set_status(event.text)
        elif isinstance(event, SentUpdate):
            pane.set_sent(event.text)
        elif isinstance(event, Activity):
            pane.activity(event.text, event.failed)
        elif isinstance(event, CardEvent):
            self.assist_cards.append(pane.add_card(event.proposal))
            self.assist_preview()                   # F58 PR-14: the newest open card
        elif isinstance(event, Done):
            pane.set_sent(event.sent)
            pane.finish(stopped=event.status == STATUS_STOPPED, usage=event.usage_text)
            if event.message:
                pane.notice(event.message, settings=event.kind in SETTINGS_KINDS)
            pane.set_total(chat_total_text(event.chat_total))
            return True
        return False

    # --- Links and cards -------------------------------------------------------------------

    def _assist_listed(self) -> tuple[str, ...]:
        return (*self.refs, CONFIG_REF)

    def assist_link(self, ref: str, line: int) -> None:
        """A listed ``file:line`` in model text: the place in the editor."""
        if ref in self._assist_listed():
            self.jump_to(ref, line)

    def assist_card_action(self, action: str, card: Card) -> None:
        if self.closed:
            return
        {"apply": self.assist_apply, "show": self.assist_show,
         "discard": self.assist_discard, "undo": self.assist_undo,
         "ask_again": self.assist_ask_again}[action](card)

    def assist_show(self, card: Card) -> None:
        """**Show**: the first file at its first change; a new file not yet made read-only
        (once Apply made it, the file in the editor)."""
        file = card.proposal.files[0]
        if file.new and file.ref not in card.created:
            self._assist_show_new(file.ref, new_text(file))
            return
        if file.ref in self._assist_listed():
            self.jump_to(file.ref, first_line(file))

    def _assist_show_new(self, ref: str, text: str) -> None:
        """A new file's proposed text in a small read-only window (nothing is written)."""
        from engine.tools.assistant.refs import one_line
        from engine.tools.editor import dialogs
        from engine.tools.editor.assistpane import NEW_FILE_TITLE, shown_text
        from engine.tools.editor.theme import THEME, dark_title_bar
        window = dialogs._dialog(self.root)
        window.resizable(True, True)
        window.title(NEW_FILE_TITLE.format(ref=one_line(ref)))
        rows = text.count("\n") + 1
        box = tk.Text(window, wrap="none", font=self.fonts["codeSmall"], width=80,
                      height=max(4, min(30, rows)), background=THEME["editor.background"],
                      foreground=THEME["editor.foreground"], borderwidth=0,
                      highlightthickness=0, padx=self._px(8), pady=self._px(6),
                      selectbackground=THEME["editor.selection"])
        box.insert("1.0", shown_text(text))
        box.configure(state="disabled")
        box.pack(fill="both", expand=True)
        window.bind("<Escape>", lambda _e: window.destroy())
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        dialogs._center(window, self.root.winfo_toplevel())
        window.deiconify()
        dark_title_bar(window)
        box.focus_set()
        self.assist_new_view = window

    def assist_discard(self, card: Card) -> None:
        """**Discard**: the card collapses to "Discarded: {title}"."""
        card.discard()
        self.assist_preview()                       # F58: its preview ends

    def assist_apply(self, card: Card) -> None:
        """**Apply** (PR-F48-23, SEC-F48-12; 04 §7.4): each existing file's plan is moved
        onto its live editor text (``edits.rebase``, opening a file that isn't open); a
        file that changed under the change gives §6.3's Stale and nothing changes. A new
        file is made empty through F45's New script file (``files.new_script``), its text
        arriving unsaved. Then ``apply_plan``: one undo step per file, the files unsaved,
        the check scheduled by the change hook. The only disk write is that empty file."""
        if self.closed or card.state != "open":
            return
        proposal = card.proposal
        plans: dict[str, FilePlan] = {}
        for file in proposal.files:
            if not _script_ref(file.ref):
                self._assist_stale(card)            # never: the tool layer refuses these
                return
            if file.new:
                if file.ref in self.refs or file.ref in self.files:
                    self._assist_stale(card)        # made since the proposal
                    return
                continue
            if file.ref not in self.refs:
                self._assist_stale(card)
                return
            record = self.record_for(file.ref)
            live = record.widget.get("1.0", "end-1c")
            moved = rebase(file, live) if record.editable else None
            if moved is None:
                self._assist_stale(card)
                return
            plans[file.ref] = moved
        created: list[str] = []
        for file in proposal.files:
            if file.new:
                folder, name = file.ref.rsplit("/", 1)
                made = files.new_script(self.paths, folder, name, text="")
                if isinstance(made, Refusal):
                    self._assist_remove(created)
                    card.show_status(made.text)
                    return
                created.append(made)
                plans[file.ref] = file.plan
        if created:
            self.refresh_project()
        plan = Plan(proposal.summary, tuple(plans[f.ref] for f in proposal.files))
        positions = self._assist_positions()
        if not self.apply_plan(plan, lambda texts: verify(plan, texts, positions=positions)):
            self._assist_remove(created)
            self._assist_stale(card)
            return
        self._assist_seed_pins(card)            # F58 PR-15: new boxes at preview spots
        card.state = "applied"
        self.assist_clear_preview()
        self.follow_now("pane")                 # F58 Q5: on the map at once
        card.tokens = tuple((fp.ref, self.files[fp.ref].changes) for fp in plan.files)
        card.created = tuple(created)
        count = len(plan.files)
        card.show_status(APPLIED if count == 1 else APPLIED_MANY.format(n=count))
        card.show_buttons("show", "undo")
        self._update_marks()

    def _assist_stale(self, card: Card) -> None:
        """§6.3 Stale: nothing changed; [Ask again] and Discard."""
        card.state = "stale"
        card.show_status(STALE)
        card.show_buttons("ask_again", "discard")
        if self._assist_preview is not None and self._assist_preview[0] is card:
            self.assist_clear_preview()             # F58 PR-15

    def _assist_remove(self, refs: Sequence[str]) -> Refusal | None:
        """Delete files Apply made (F45's Delete, ``files.delete_file``) and close their
        documents; the first refusal, if any."""
        refused = None
        for ref in refs:
            result = files.delete_file(self.paths, ref)
            if isinstance(result, Refusal) and refused is None:
                refused = result
        if refs:
            self.refresh_project()
        for ref in refs:
            if ref not in self.refs:
                self._drop_record(ref)
        return refused

    def _assist_positions(self) -> frozenset[str]:
        """The stage positions for ``verify``: the check's names, the built-ins and the
        live ``config.toml``'s (as ``propose`` parsed with)."""
        names = set(self._positions()) | set(BUILTIN_POSITIONS)
        record = self.files.get(CONFIG_REF)
        if record is not None and record.editable:
            text = record.widget.get("1.0", "end-1c")
        else:
            text = getattr(document.open_config(self.paths), "text", "")
        names.update(row.name for row in position_rows(text) or ())
        return frozenset(names)

    def assist_undo(self, card: Card) -> None:
        """**Undo** (PR-F48-29, the F46 map-undo rule): only while every file the card
        changed still has its token (``OpenFile.changes`` right after Apply); then each
        file's text undo runs once, and a file the card created is deleted through F45's
        Delete (while its disk text is still empty or the applied text). Otherwise §6.3's
        refused text, and Undo here goes."""
        if self.closed or card.state != "applied" or card.tokens is None:
            return
        records = {ref: self.files.get(ref) for ref, _token in card.tokens}
        ready = all(records[ref] is not None and records[ref].editable
                    and records[ref].changes == token for ref, token in card.tokens)
        for ref in card.created if ready else ():
            text = records[ref].widget.get("1.0", "end-1c")
            if _disk_text(self.paths, ref) not in ("", text):
                ready = False
        if not ready:
            card.tokens = None
            card.show_status(UNDO_REFUSED)
            card.show_buttons("show")
            return
        refused = self._assist_remove(card.created)
        if refused is not None:
            card.show_status(refused.text)
            return
        for ref, record in records.items():
            if ref not in card.created and record is not None:
                try:
                    record.widget.edit_undo()
                except tk.TclError:
                    pass
        self.follow_now("pane")                 # F58 Q5
        card.tokens, card.created = None, ()
        card.state = "open"
        card.show_status(UNDONE)
        card.show_buttons("apply", "show", "discard")
        self._update_marks()
        self.assist_preview()                       # F58: open again, so it previews

    def assist_ask_again(self, card: Card) -> None:
        """**Ask again** (a stale card): sends §6.3's "The file changed. …" with the
        current editor texts (a fresh snapshot); the author's typed input stays."""
        if self.closed or card.state != "stale" or self.assist_run is not None:
            return
        if self.assist_send(request=ASK_AGAIN_TEXT):
            card.show_buttons("discard")

    # --- The map preview of the newest open card (F58 PR-14, 15; 04 §7.10; 07 I-12) -------

    def _assist_newest(self) -> Card | None:
        """The newest open card (D5: only it previews)."""
        for card in reversed(self.assist_cards):
            if card.state == "open":
                return card
        return None

    def assist_texts_changed(self) -> None:
        """After a map update (typing, an action, disk, a check): every open card whose
        touched scene changed goes Stale at once (Apply's own test, D6), and the newest
        open card's preview follows its files. Nothing to do without open cards."""
        if self.closed or not getattr(self, "assist_cards", None):
            if self._assist_preview_key is not None:
                self.assist_clear_preview()
            return
        for card in list(self.assist_cards):
            if card.state == "open" and self._assist_card_stale(card):
                self._assist_stale(card)
        self.assist_preview()

    def _assist_card_stale(self, card: Card) -> bool:
        """Apply's Stale test without its writes: ``stale_by_index`` in O(touched) where an
        index of exactly the live text exists, else ``edits.rebase``. Files that aren't
        open and have no index are tested at Apply (no read here)."""
        for file in card.proposal.files:
            if file.new:
                if file.ref in self.refs or file.ref in self.files:
                    return True                     # made since the proposal
                continue
            if not _script_ref(file.ref) or file.ref not in self.refs:
                return True
            live, index = self._assist_live(file.ref, read=False)
            if live is None:
                continue
            found = None if index is None else stale_by_index(file.touched, file.marks,
                                                              index)
            if found is None:
                found = rebase(file, live, index=index) is None
            if found:
                return True
        return False

    def _assist_live(self, ref: str, *, read: bool = True
                     ) -> tuple[str | None, scenes.SceneIndex | None]:
        """``ref``'s live text and, when it is exactly that text's, its scene index. A
        closed file is read only with ``read`` and at most ``PREVIEW_READ_MAX`` (I-12),
        from the watch's document when its stamp holds (R2)."""
        record = self.files.get(ref)
        index = self.scene_indexes.get(ref)
        if record is not None:
            if not record.editable:
                return None, None
            text = record.widget.get("1.0", "end-1c")
            exact = index is not None and index.changes == record.changes
            return text, index if exact else None
        if not read:
            return None, None
        path = self.paths.root / ref
        stamp = self._stat(path)
        if stamp is None or stamp[1] > PREVIEW_READ_MAX:
            return None, None
        kept = self._closed_docs.get(ref)
        if kept is not None and kept.stamp == stamp and kept.text:
            text = kept.text
        else:
            got = document.open_document(self.paths, ref)
            if not isinstance(got, document.ScriptDocument) or got.stamp != stamp:
                return None, None
            text = got.text
            self._keep_doc(got)                 # R2: Apply opens it without a read
        if index is None or self._closed_stamps.get(ref) != stamp:
            # The first index of a closed file is its checked baseline (07 ruling 15);
            # kept, so Apply's open neither chunks nor digests it again (R2).
            index = scenes.reindex(None, ref, text, 0, checked=None,
                                   positions=self._positions())
            self.scene_indexes[ref] = scenes.slim(index)
            self._checked.setdefault(ref, index.checked)
            self._closed_stamps[ref] = stamp
        return text, index

    def assist_preview(self) -> None:
        """Draw what the newest open card's Apply would do (PR-14): its plans applied in
        memory to the live texts (``rebase``, ``apply_lines``), only the changed scenes
        parsed, ``preview_rows`` against what the map shows, a dry-run layout on a copy of
        the pins; S7 or S8. Nothing runs and nothing is written (SEC-F48-04, -12); only
        plan rows reach the map, never the card's title or summary (SEC-F48-09, -20)."""
        view = self.story_map
        card = self._assist_newest()
        shown = view._shown_rows
        if card is None or shown is None or view.layout is None:
            self.assist_clear_preview()
            return
        key = (id(card), view.painter.layout is not None, *(
            (f.ref, id(self.scene_indexes.get(f.ref)), self._stamp_of(f.ref),
             self.files[f.ref].changes if f.ref in self.files else -1)
            for f in card.proposal.files))
        if key == self._assist_preview_key and (view.painter.preview_items
                                                or self._assist_preview is None):
            return
        self._assist_preview_key = key
        model = livemap.MapModel()
        model.files, model.order = dict(shown), list(shown)
        after: dict[str, livemap.FileRows] = {}
        for file in card.proposal.files:
            rows = self._assist_rows(card, file, model)
            if rows is None:
                self._assist_drop_preview()
                return
            after[file.ref] = rows
        found = livemap.preview_rows(model, after)
        trial = model.copy()
        for ref, rows in after.items():
            trial.set_file(ref, rows)
        layout = view.painter.preview(found, trial.links(), trial.labels(),
                                      pins=view.pins.of(view.file), places=view.places,
                                      file=view.file)
        self._assist_preview = (card, found, layout)
        self.map_line.clear("S7")
        self.map_line.clear("S8")
        self.map_line.say("S7" if found else "S8", found.line)
        self._show_map_line()
        if layout is not None and found.boxes_added and view.follow_var.get() \
                and not view.holding:
            j = layout.index_of(found.boxes_added[0])
            if j is not None:                       # Follow changes: the preview too
                view.see_rect(view.painter.rect_of(layout.boxes[j]))

    def _assist_rows(self, card: Card, file: Any, model: livemap.MapModel
                     ) -> livemap.FileRows | None:
        """One card file's rows after Apply, or None (no preview; a stale card goes
        Stale)."""
        positions = self._positions()
        if file.new:
            text = new_text(file)
            if len(text.encode("utf-8")) > PREVIEW_NEW_MAX:
                return None
            index = scenes.reindex(None, file.ref, text, 0, checked={}, positions=positions)
            return livemap.rows_from_index(index)
        live, index = self._assist_live(file.ref)
        if live is None:
            return None                             # I-12: too large to read here
        stale = None if index is None else stale_by_index(file.touched, file.marks, index)
        moved = None if stale else rebase(file, live, index=index)
        if moved is None:
            self._assist_stale(card)
            return None
        try:
            lines = apply_lines(live.split("\n"), moved.edits)
        except ValueError:
            return None
        base = index if index is not None else scenes.reindex(
            None, file.ref, live, 0, checked=None, positions=positions)
        result = scenes.reindex(base, file.ref, "\n".join(lines), 0, checked=base.digests,
                                positions=positions)
        return livemap.rows_from_index(result, model.check_links(file.ref))

    def _assist_drop_preview(self) -> None:
        self.story_map.painter.clear_preview()
        self._assist_preview = None
        self.map_line.clear("S7")
        self.map_line.clear("S8")
        self._show_map_line()

    def assist_clear_preview(self) -> None:
        """The preview ends (Apply, Discard, Stale, New chat, the pane closing)."""
        self._assist_preview_key = None
        self._assist_drop_preview()

    def _assist_seed_pins(self, card: Card) -> None:
        """Apply: the new boxes land where the preview showed them (PR-15)."""
        held = self._assist_preview
        if held is None or held[0] is not card or held[2] is None:
            return
        _card, found, layout = held
        view = self.story_map
        spots = {}
        for name in found.boxes_added:
            j = layout.index_of(name)
            if j is not None and name not in view.places:
                spots[name] = (layout.boxes[j].x, layout.boxes[j].y)
        if spots:
            view.pins.add(view.file, spots)

    # --- Focus and closing -----------------------------------------------------------------

    def assist_focus_widget(self) -> tk.Widget | None:
        """F6's stop in the pane (its input) while it is shown."""
        return self.assist_pane.input if self.assistant_open() else None

    def assist_has_focus(self, widget: object) -> bool:
        if not self.assistant_open() or not isinstance(widget, tk.Misc):
            return False
        frame = str(self.assist_pane.frame)
        return str(widget) == frame or str(widget).startswith(frame + ".")

    def close_assistant(self) -> None:
        """Window close (07 I-7): cancel the run and stop the pane's check child."""
        run = self.assist_run
        if run is not None:
            run.cancel()
        if self._assist_poll_id is not None:
            try:
                self.root.after_cancel(self._assist_poll_id)
            except tk.TclError:
                pass
            self._assist_poll_id = None
        if self.assist_checks is not None:
            self.assist_checks.stop()
        if self._assist_bg is not None:
            self._assist_bg.close()
        dialog = getattr(self, "ai_settings", None)
        if dialog is not None and dialog.alive:
            dialog.background.close()


__all__ = ["AssistWiring", "MENU", "POLL_MS", "SETTINGS_KINDS"]
