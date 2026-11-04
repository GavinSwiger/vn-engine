"""The Assistant pane in the Studio window, as the ``AssistWiring`` mixin of
``window.EditorWindow`` (F48 ``01-design.md`` §6.1, §6.6, PR-F48-14, -19 to -22, -24;
``04-technical.md`` §3.2, §7.7; ``05-security.md`` SEC-F48-12, -16, -20, -21; ``07`` I-7;
AC-F48-30, -31, -44, -46, -53).

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
- Cards (``assistpane.Card``): Show and Discard act here; Apply, Undo and Ask again call
  ``assist_apply``, ``assist_undo`` and ``assist_ask_again``, which F48 W5 fills in.

Imports ``tkinter``, its own package and ``tools.assistant`` (a Tk module: the import-rule
exception). Logs nothing about the chat (SEC-F48-14: ``chat`` logs the provider, status and
step count).
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Any

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
from engine.tools.assistant.keystore import Slot
from engine.tools.assistant.providers import COMPATIBLE, PANE_NAMES, errors
from engine.tools.assistant.reference import build_reference
from engine.tools.assistant.workspace import CheckService, Snapshot
from engine.tools.editor import studiostate
from engine.tools.editor.aisettings import (
    Background,
    ensure_consent,
    open_ai_settings,
    session_for,
    slot_of,
)
from engine.tools.editor.assistpane import AssistPane, Card, first_line, model_line, new_text
from engine.tools.editor.guidepane import GUIDE_MIN_WIDTH, GUIDE_WIDTH

POLL_MS = 50                            # 04 §7.7
POLL_TIMES_KEPT = 200
MENU = "AI Assistant"                   # View ▸ AI Assistant (Ctrl+Shift+A)
# Done kinds that offer [Open settings] (S8 notes).
SETTINGS_KINDS = frozenset({"key", "no_key", "model", "forbidden", "token_limit"})


class AssistWiring:
    """The pane in the window: showing it, Send/Stop/New chat, the 50 ms poll, consent,
    the cards, and closing."""

    assistant_shown = False
    assist_pane: AssistPane
    assist_run: ChatRun | None = None
    assist_checks: CheckService | None = None

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

    def assist_send(self, *, retried: bool = False) -> None:
        """**Send** (Enter): the request goes out only after the token limit, the key and
        consent pass; Cancel in the consent dialog sends nothing and keeps the text."""
        pane = self.assist_pane
        if self.closed:
            return
        if self.assist_run is not None:
            self.assist_stop()
            return
        request = pane.input_text().strip()
        if not request:
            return
        session = session_for(self)
        prefs = session.reload()
        chat = self.assist_chat
        chat.steps, chat.token_limit = prefs.steps, prefs.token_limit
        blocked = chat.blocked()
        if blocked is not None:
            pane.notice(blocked, settings=True)
            return
        target = session.target()
        if target.error is not None:
            pane.notice(target.error, settings=True)
            return
        slot = slot_of(target)
        if slot is None:
            return
        if not (session.key_known and session.key_slot == slot):
            if retried:
                return
            self._assist_load_key(slot, then=lambda: self.assist_send(retried=True))
            return
        key = session.key
        if key is None and target.provider != COMPATIBLE:
            pane.notice(errors.NO_KEY, settings=True)
            return
        if not ensure_consent(session, self.root, target, fonts=self.fonts):
            return
        snapshot = self.assist_snapshot()
        try:
            provider = session.provider(key=key)
        except errors.AddressError as exc:
            pane.notice(exc.text, settings=True)
            return
        if self.assist_checks is None:
            self.assist_checks = CheckService(self.paths.root)
        pane.clear_input()
        pane.start_exchange(request)
        run = ChatRun(chat, provider, paths=self.paths, snapshot=snapshot, request=request,
                      checks=self.assist_checks)
        self.assist_run = run
        self._assist_pump = EventPump(run.events)
        pane.set_running(True)
        run.start()
        self._assist_schedule()

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
        """**Show**: the first file at its first change; a new file read-only."""
        file = card.proposal.files[0]
        if file.new:
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

    def assist_apply(self, card: Card) -> None:
        """**Apply** (W5): rebase the card's files against the live texts, then
        ``self.apply_plan(plan, verify)``; a stale scene shows §6.3's text."""

    def assist_undo(self, card: Card) -> None:
        """**Undo** (W5): the card's files back, while each still holds the applied text."""

    def assist_ask_again(self, card: Card) -> None:
        """**Ask again** (W5): sends §6.3's "The file changed. …" message."""

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
