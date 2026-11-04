"""The pane's chat: its messages and token use, and the worker that runs one request (F48
``04-technical.md`` §3.1, §7.7; 01 §6.1, §6.6, PR-F48-19 to -22, -24, -26, -28, -30;
``05-security.md`` SEC-F48-19, SEC-F48-20, SEC-F48-21).

Why this module exists: a request is a loop the model drives (read, check, propose, read
again), and none of it may hold up Studio. So the Tk thread only takes a ``Snapshot`` and
starts a ``ChatRun``; the worker owns the HTTP stream, the ``ToolBox`` over a
``SnapshotWorkspace`` and the pane's ``CheckService``, and posts plain events to a queue that
Tk drains every 50 ms (``EventPump``, at most 8 KiB of text per poll).

- ``Chat``: the provider-neutral messages (append-only, so every request's prefix is the
  last one's: prompt caching), the chat-start project summary, the tokens used, the token
  limit (``blocked()`` gives 01 §6.6's text; New chat is ``reset()``) and the step limit.
- ``ChatRun(chat, provider, paths=, snapshot=, request=, checks=)``: one Send. The first
  user message opens with the summary data block; every user message carries the Studio
  context and then the author's words. Each model step's tool calls run through
  ``ToolBox(…, MODE_PANE, on_proposal=…)``: the pane has no write tool, and each
  ``propose_edit`` becomes a ``CardEvent`` holding the ``Proposal`` (the card shows the plan,
  never model text). Each tool call is a step; at the step limit the remaining calls get a
  "not run" result and the answer ends with 01 §6.6's step text. At most 16 calls in one
  model step and 200,000 characters of answer.
- One automatic retry on 429, 503 or 529 when the server's hint is at most 30 s, shown as
  "Waiting {seconds} s for {provider}…" (PR-F48-30), and only before any text arrived.
- ``cancel()`` (Stop/Esc) sets the flag, cancels the transport (a socket shutdown) and stops
  a running check child; the partial answer stays and the run ends ``STATUS_STOPPED``.
- The Sent line (SEC-F48-21) is built from the tool layer's ``SentRecord``s (context,
  summary, every tool result), never from model text.
- Usage: "↑ in (cached) ↓ out" per answer, summed over its steps; "Usage not reported." when
  a compatible server sends none (01 §6.1).

Logs the provider, status, step count and duration only: never bodies, model text, tool
arguments or file text (SEC-F48-14).
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from typing import Final

from engine.core.paths import GamePaths
from engine.script.assetgroups import CONFIG_REF
from engine.tools.assistant.context import Context, chat_summary, request_block, studio_context
from engine.tools.assistant.edits import Proposal, check_lines
from engine.tools.assistant.prefs import STEPS_DEFAULT, TOKEN_LIMIT_DEFAULT
from engine.tools.assistant.providers import errors
from engine.tools.assistant.providers.base import (
    EVENT_TEXT, STOP_END, STOP_LENGTH, STOP_REFUSAL, AssistantTurn, Message, Provider,
    StreamEvent, ToolResult, ToolResults, Turn, Usage, UserTurn)
from engine.tools.assistant.providers.errors import KeyMismatchError, ProviderError
from engine.tools.assistant.reference import build_reference
from engine.tools.assistant.refs import one_line
from engine.tools.assistant.textout import SentRecord, ToolText
from engine.tools.assistant.tools import MODE_PANE, ToolBox
from engine.tools.assistant.workspace import CheckService, Snapshot, SnapshotWorkspace

log = logging.getLogger("vn.assistant")

ANSWER_MAX_CHARS: Final = 200_000          # 01 §7.2
POLL_MAX_CHARS: Final = 8 * 1024           # 04 §7.7: text Tk renders per poll
SENT_RANGES_MAX: Final = 12

# --- Texts (01 §6.1, §6.6; the rest are S8 deltas) --------------------------------------------

WORKING: Final = "Working… (step {n})"
STOPPED_MARK: Final = "(stopped)"
USAGE: Final = "↑ {total_in} ({cached} cached) ↓ {output}"
USAGE_NONE: Final = "Usage not reported."
CHAT_TOTAL: Final = "This chat: {n} tokens"
SENT: Final = "Sent: {items}"
SENT_MORE: Final = "…and {n:,} more"
NOT_RUN_LIMIT: Final = "Not run: this request reached its step limit."
NOT_RUN_STOPPED: Final = "Not run: the author stopped this request."
NOT_RUN_CUT: Final = "Not run: the answer was cut off before this call was complete."
INTERNAL: Final = "The assistant stopped because of a problem in Studio. Try again."
TRIED: Final = "Tried {tool}: {reason}"
CHECKED_CHANGE: Final = "Checked the change: {result}"
READ_RANGE: Final = "Read {where}"
ACTIVITY: Final = {
    "language_reference": "Read the language reference",
    "language_docs": "Read the language guide",
    "project_summary": "Read the project summary",
    "list_files": "Listed the game's files",
    "read_script": "Read a script file",
    "search_scripts": "Searched the script files",
    "story_map": "Read the story map",
    "scene": "Read a scene",
    "names": "Looked up the game's names",
    "lookup": "Looked up a name",
    "game_settings": "Read the game settings",
    "run_check": "Checked the game",
    "propose_edit": "Proposed a change",
}

STATUS_DONE: Final = "done"
STATUS_STOPPED: Final = "stopped"
STATUS_FAILED: Final = "failed"
STATUS_STEP_LIMIT: Final = "step_limit"


# --- Formatting -------------------------------------------------------------------------------

def usage_text(usage: Usage) -> str:
    """An answer's usage line (01 §6.1)."""
    if not usage.reported:
        return USAGE_NONE
    return USAGE.format(total_in=f"{usage.total_in:,}", cached=f"{usage.cache_read:,}",
                        output=f"{usage.output:,}")


def chat_total_text(total: int) -> str:
    return CHAT_TOTAL.format(n=f"{total:,}")


def _lines_text(ref: str, first: int, last: int) -> str:
    where = f"line {first}" if first == last else f"lines {first}–{last}"
    return f"{one_line(ref)} {where}"


def sent_text(record: SentRecord, *, selection: bool = False) -> str:
    """SEC-F48-21's Sent line from the tool layer's record."""
    items = ["reference", "summary"]
    items += [_lines_text(*row) for row in record.ranges[:SENT_RANGES_MAX]]
    if len(record.ranges) > SENT_RANGES_MAX:
        items.append(SENT_MORE.format(n=len(record.ranges) - SENT_RANGES_MAX))
    if record.config and not any(ref == CONFIG_REF for ref, _, _ in record.ranges):
        items.append(CONFIG_REF)
    if selection:
        items.append("selection")
    items.append(f"{record.problems:,} problem" + ("" if record.problems == 1 else "s"))
    if record.names:
        items.append("file names")
    return SENT.format(items=", ".join(items))


def activity_text(name: str, result: ToolText, proposal: Proposal | None = None) -> str:
    """The pane's "· …" line for one tool call: engine text and the tool layer's record."""
    if result.is_error:
        reason = one_line(result.text.split("\n", 1)[0], 160)
        return TRIED.format(tool=one_line(name, 60), reason=reason)
    if name == "propose_edit" and proposal is not None:
        lines = check_lines(proposal)
        if lines:
            first = lines[0].rstrip(".:")
            return CHECKED_CHANGE.format(result=first[:1].lower() + first[1:])
    if name in ("read_script", "scene") and result.sent.ranges:
        return READ_RANGE.format(where=_lines_text(*result.sent.ranges[0]))
    return ACTIVITY.get(name, ACTIVITY["read_script"])


def clean_text(text: str) -> str:
    """The author's typed text as valid Unicode (Tk can hand over surrogate pairs)."""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


# --- The chat ---------------------------------------------------------------------------------

class Chat:
    """One chat (memory only, 01 §8 D9). The worker appends to it during a run; the Tk
    thread reads it once the run's ``Done`` arrives."""

    def __init__(self, *, token_limit: int = TOKEN_LIMIT_DEFAULT,
                 steps: int = STEPS_DEFAULT) -> None:
        self.token_limit = token_limit
        self.steps = steps
        self.reset()

    def reset(self) -> None:
        """New chat: no messages, no summary, zero tokens."""
        self.messages: list[Message] = []
        self.summary: Context | None = None
        self.usage = Usage()
        self.total = 0
        self.running = False

    def blocked(self) -> str | None:
        """01 §6.6's token-limit text once the chat has used its limit, else None."""
        if self.total >= self.token_limit:
            return errors.TOKEN_LIMIT.format(n=f"{self.total:,}")
        return None

    @property
    def total_text(self) -> str:
        return chat_total_text(self.total)


# --- Events (worker → Tk) ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Working:
    step: int

    @property
    def text(self) -> str:
        return WORKING.format(n=self.step)


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class Activity:
    text: str
    failed: bool = False


@dataclass(frozen=True, slots=True)
class CardEvent:
    proposal: Proposal


@dataclass(frozen=True, slots=True)
class Waiting:
    seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class SentUpdate:
    text: str


@dataclass(frozen=True, slots=True)
class Done:
    """The run's end. ``message``: 01 §6.6's text for a failure or the step limit (None
    when done or stopped); ``kind``: ``ProviderError.kind`` ("key", "no_key", "model"…
    ask the pane to offer [Open settings]), "token_limit", "refusal", "length",
    "too_long" or "internal"."""

    status: str
    message: str | None
    usage: Usage
    sent: str
    chat_total: int
    steps: int
    kind: str | None = None

    @property
    def usage_text(self) -> str:
        return usage_text(self.usage)


Event = Working | TextDelta | Activity | CardEvent | Waiting | SentUpdate | Done


class EventPump:
    """The Tk side of the queue: ``poll()`` every 50 ms returns the waiting events, adjacent
    text joined and at most ``max_chars`` of text per poll (the rest waits)."""

    def __init__(self, events: "SimpleQueue[Event]") -> None:
        self._events = events
        self._held: str | None = None

    def poll(self, max_chars: int = POLL_MAX_CHARS) -> list[Event]:
        out: list[Event] = []
        budget = max_chars
        pieces: list[str] = []

        def flush() -> None:
            if pieces:
                out.append(TextDelta("".join(pieces)))
                pieces.clear()

        def take(text: str) -> bool:
            nonlocal budget
            part, rest = text[:budget], text[budget:]
            if part:
                pieces.append(part)
                budget -= len(part)
            self._held = rest or None
            return not rest

        if self._held is not None and not take(self._held):
            flush()
            return out
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                break
            if isinstance(event, TextDelta):
                if not take(event.text):
                    break
                continue
            flush()
            out.append(event)
        flush()
        return out


# --- The worker -------------------------------------------------------------------------------

class _Stopped(Exception):
    pass


class _TooLong(Exception):
    pass


class _CancellableChecks:
    """The pane's ``CheckService`` with the run's cancel event passed to every check, so
    Stop ends a check child at once (the worker polls it)."""

    def __init__(self, inner: CheckService, cancel: threading.Event) -> None:
        self._inner = inner
        self._cancel = cancel

    def run(self, overlay, *, launch, cancel=None):
        return self._inner.run(overlay, launch=launch, cancel=cancel or self._cancel)

    def base(self, overlay, *, launch, stamp=None, cancel=None):
        return self._inner.base(overlay, launch=launch, stamp=stamp,
                                cancel=cancel or self._cancel)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class ChatRun(threading.Thread):
    """One Send, on a daemon thread (``start()``; tests may call ``run()``). Events go to
    ``events``; the run ends with exactly one ``Done``."""

    def __init__(self, chat: Chat, provider: Provider, *, paths: GamePaths,
                 snapshot: Snapshot, request: str, checks: CheckService | None = None,
                 events: "SimpleQueue[Event] | None" = None,
                 wait: Callable[[float], bool] | None = None) -> None:
        super().__init__(name="assistant-chat", daemon=True)
        self.chat = chat
        self.provider = provider
        self.request = clean_text(request)
        self.events: SimpleQueue[Event] = events if events is not None else SimpleQueue()
        self.cancelled = threading.Event()
        self._wait = wait if wait is not None else self.cancelled.wait
        inner = checks if checks is not None else CheckService(paths.root)
        self.workspace = SnapshotWorkspace(
            paths, snapshot, checks=_CancellableChecks(inner, self.cancelled))  # type: ignore[arg-type]
        self.toolbox = ToolBox(self.workspace, MODE_PANE, on_proposal=self._proposal)
        self.usage = Usage()
        self.sent = SentRecord()
        self.selection = False
        self.steps = 0
        self._chars = 0
        self._step_text: list[str] = []
        self._proposal_seen: Proposal | None = None
        self.done: Done | None = None

    # -- the Tk side ---------------------------------------------------------------------------

    def cancel(self) -> None:
        """Stop/Esc: never blocks."""
        self.cancelled.set()
        self.provider.transport.cancel()

    # -- posting -------------------------------------------------------------------------------

    def _post(self, event: Event) -> None:
        self.events.put(event)

    def _proposal(self, proposal: Proposal) -> None:
        self._proposal_seen = proposal
        self._post(CardEvent(proposal))

    def _on_event(self, event: StreamEvent) -> None:
        if event.kind != EVENT_TEXT or not event.text:
            return
        self._chars += len(event.text)
        if self._chars > ANSWER_MAX_CHARS:
            raise _TooLong()
        self._step_text.append(event.text)
        self._post(TextDelta(event.text))

    def _sent(self, more: SentRecord) -> None:
        merged = self.sent.merge(more)
        if merged != self.sent:
            self.sent = merged
            self._post(SentUpdate(sent_text(self.sent, selection=self.selection)))

    def _finish(self, status: str, message: str | None = None, kind: str | None = None) -> None:
        self.done = Done(status, message, self.usage,
                         sent_text(self.sent, selection=self.selection), self.chat.total,
                         self.steps, kind)
        self._post(self.done)

    # -- the run -------------------------------------------------------------------------------

    def run(self) -> None:
        started = time.monotonic()
        try:
            self._run()
        except Exception as exc:          # a bug must still end the run, with no detail shown
            log.warning("assistant run failed: %s", type(exc).__name__)
            self._finish(STATUS_FAILED, INTERNAL, "internal")
        finally:
            self.chat.running = False
            if self.done is None:
                self._finish(STATUS_FAILED, INTERNAL, "internal")
            log.info("assistant %s: %s after %d steps in %.1f s", self.provider.id,
                     self.done.status, self.steps, time.monotonic() - started)

    def _run(self) -> None:
        chat = self.chat
        blocked = chat.blocked()
        if blocked is not None:
            self._finish(STATUS_FAILED, blocked, "token_limit")
            return
        chat.running = True
        start = len(chat.messages)
        first = not any(isinstance(m, UserTurn) for m in chat.messages)
        if chat.summary is None:
            chat.summary = chat_summary(self.toolbox)
        context = studio_context(self.workspace)
        self.selection = context.selection
        self.sent = chat.summary.sent.merge(context.sent)
        self._post(SentUpdate(sent_text(self.sent, selection=self.selection)))
        blocks = ((chat.summary.text,) if first else ()) + (
            context.text, request_block(self.request))
        chat.messages.append(UserTurn(blocks, summary=first))
        system = build_reference()
        try:
            self._loop(system)
        except (_Stopped, _TooLong, ProviderError, KeyMismatchError) as exc:
            self._ended(exc, start)

    def _ended(self, exc: Exception, start: int) -> None:
        chat = self.chat
        partial = "".join(self._step_text)
        stopped = isinstance(exc, _Stopped) or (
            isinstance(exc, ProviderError) and exc.kind == "cancelled") or self.cancelled.is_set()
        answered = any(isinstance(m, AssistantTurn) for m in chat.messages[start:])
        if not stopped and not answered and not partial:
            del chat.messages[start:]             # nothing came back: as if never sent
        elif partial:
            chat.messages.append(AssistantTurn(partial))
        if stopped:
            self._finish(STATUS_STOPPED)
        elif isinstance(exc, _TooLong):
            self._finish(STATUS_FAILED, errors.ANSWER_TOO_LONG, "too_long")
        elif isinstance(exc, KeyMismatchError):
            self._finish(STATUS_FAILED, exc.text, "key_elsewhere")
        else:
            assert isinstance(exc, ProviderError)
            self._finish(STATUS_FAILED, exc.text, exc.kind)

    def _model_step(self, system: str) -> Turn:
        for attempt in (0, 1):
            self._step_text = []
            try:
                return self.provider.stream(system, self.chat.messages, self._on_event)
            except ProviderError as exc:
                if attempt or not exc.retryable or self._step_text or self.cancelled.is_set():
                    raise
                seconds = exc.retry_after or 0.0
                self._post(Waiting(seconds, errors.WAITING.format(
                    seconds=errors.seconds_text(seconds), provider=self.provider.name)))
                if self._wait(seconds) or self.cancelled.is_set():
                    raise _Stopped() from None
        raise AssertionError("unreachable")

    def _loop(self, system: str) -> None:
        chat = self.chat
        while True:
            if self.cancelled.is_set():
                raise _Stopped()
            self._post(Working(self.steps + 1))
            turn = self._model_step(system)
            self._step_text = []
            self.usage = self.usage + turn.usage
            chat.usage = chat.usage + turn.usage
            chat.total += turn.usage.total
            if turn.stop == STOP_REFUSAL:
                self._finish(STATUS_FAILED, errors.REFUSED.format(provider=self.provider.name),
                             "refusal")
                return
            message = turn.message
            if message is not None:
                chat.messages.append(message)
            pending = message.calls if message is not None else ()
            if turn.stop == STOP_LENGTH or (turn.stop == STOP_END and pending):
                if pending:
                    chat.messages.append(ToolResults(tuple(
                        ToolResult(call.id, NOT_RUN_CUT, True) for call in pending)))
                if turn.stop == STOP_LENGTH:
                    self._finish(STATUS_FAILED, errors.CUT_OFF, "length")
                else:
                    self._finish(STATUS_DONE)
                return
            if not turn.calls:
                self._finish(STATUS_DONE)
                return
            if self._run_calls(turn):
                return

    def _run_calls(self, turn: Turn) -> bool:
        """Run one step's calls; True when the run ended (stopped or at the step limit)."""
        results: list[ToolResult] = []
        limit = False
        for call in turn.calls:
            if self.cancelled.is_set():
                results.append(ToolResult(call.id, NOT_RUN_STOPPED, True))
                continue
            if self.steps >= self.chat.steps:
                results.append(ToolResult(call.id, NOT_RUN_LIMIT, True))
                limit = True
                continue
            self.steps += 1
            self._post(Working(self.steps))
            self._proposal_seen = None
            out = self.toolbox.call(call.name, call.args)
            self._sent(out.sent)
            self._post(Activity(activity_text(call.name, out, self._proposal_seen),
                                out.is_error))
            results.append(ToolResult(call.id, out.text, out.is_error))
        self.chat.messages.append(ToolResults(tuple(results)))
        if self.cancelled.is_set():
            self._finish(STATUS_STOPPED)
            return True
        if limit:
            self._finish(STATUS_STEP_LIMIT, errors.STEP_LIMIT.format(n=self.chat.steps),
                         "step_limit")
            return True
        return False


__all__ = ["ACTIVITY", "ANSWER_MAX_CHARS", "Activity", "CHAT_TOTAL", "CardEvent", "Chat",
           "ChatRun", "Done", "Event", "EventPump", "INTERNAL", "NOT_RUN_CUT", "NOT_RUN_LIMIT",
           "NOT_RUN_STOPPED", "POLL_MAX_CHARS", "SENT", "STATUS_DONE", "STATUS_FAILED",
           "STATUS_STEP_LIMIT", "STATUS_STOPPED", "STOPPED_MARK", "SentUpdate", "TextDelta",
           "USAGE", "USAGE_NONE", "WORKING", "Waiting", "Working", "activity_text",
           "chat_total_text", "clean_text", "sent_text", "usage_text"]
