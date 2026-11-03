"""The console's one value formatter (F40 ``04`` §7.4, ``05`` SEC-F40-05; AC-F40-22, -37).

Why this module exists: the console shows story values that may be huge, self-containing,
deeply nested, or author objects whose ``__repr__`` raises or never returns. Every value
text the console makes (Variables rows, 80; Code output and result texts, 2,000; Studio's
``values``, 200) comes from here, and none of them may hang the game or leak a path.

- **Plain values** (exact ``str``, ``int``, ``float``, ``complex``, ``bool``, ``None``,
  ``list``, ``tuple``, ``dict``, ``set``, ``frozenset``; subclasses are author objects) are
  walked with an explicit stack, never by recursion and never by a full ``repr``: the walk
  stops once the text passes its cap. A container already being shown (a cycle) and nesting
  past ``DEPTH_MAX`` levels show ``…``; an ``int`` over ``INT_BITS_MAX`` bits (about 4,300
  digits) shows ``CANT_SHOW``. No author code runs.
- **Other objects** get a slot. ``TextBatch.texts(call)`` then makes **one** call into
  author code for the whole batch (a Variables refresh, a ``values`` answer, one Code
  result): ``call(fn)`` must run ``fn`` under the console's guard (P1's ``guarded``). Each
  distinct object's ``repr`` is cut to its cap; one that raises shows ``CANT_SHOW``. A
  watchdog stop (``KeyboardInterrupt``) ends the batch: the objects not reached show
  ``CANT_SHOW``. With no ``call``, no author code runs and every object shows ``CANT_SHOW``.
- Every text is redacted, then its control, line-separator and bidi characters are escaped
  (``echo()``'s order), then cut to its cap with ``…``. The walk reads ``_SLACK`` characters
  past the cap so a home path at the edge is still redacted whole.

Texts are made when the console asks (on open, after a change, per ``values`` answer), never
per frame. Imports ``engine.core`` only.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from engine.core.editorreport import CONSOLE_TEXT_MAX, CONSOLE_VALUE_TEXT_MAX
from engine.core.redact import escape_controls, redact

CANT_SHOW = "<can't show this value>"     # 01 §6.3 "Unshowable value"
MORE = "…"                                # a cut text, a cycle, nesting past DEPTH_MAX
ROW_MAX = 80                              # a Variables row (PR-F40-08)
CODE_MAX = CONSOLE_TEXT_MAX               # Code output and result texts (PR-F40-13)
VALUES_MAX = CONSOLE_VALUE_TEXT_MAX       # one Studio ``values`` text (01 §6.4)
DEPTH_MAX = 100                           # containers nested deeper show MORE
INT_BITS_MAX = 14_000                     # about 4,300 digits: larger ints show CANT_SHOW
_SLACK = 256                              # read past the cap so redaction sees whole paths

AuthorCall = Callable[[Callable[[], None]], object]
"""``call(fn)``: run ``fn`` once in the console's guarded author-call path (it absorbs every
exception, a watchdog stop included). Its result is ignored."""


@dataclass(frozen=True, slots=True)
class _Slot:
    """An author object's place in a walked text: ``key`` is its ``id``."""

    key: int


@dataclass(slots=True)
class _Entry:
    parts: list                           # str texts and _Slot places, in order
    cut: bool                             # the walk stopped at its limit
    cap: int


_SEP = ("s", ", ")
_PLAIN_SCALARS = (float, complex)


def _str_text(text: str, room: int) -> str:
    """``repr(text)``, or for a string longer than ``room`` its opening quote and escaped
    first ``room`` characters only (already past the limit, so it will be cut). The quote is
    the one ``repr`` picks for the whole string."""
    if len(text) <= room:
        return repr(text)
    quote = '"' if "'" in text and '"' not in text else "'"
    head = repr(text[:room])
    body = head[1:-1]
    if head[0] != quote and quote == "'":
        body = body.replace("'", "\\'")
    return quote + body


def _int_text(value: int) -> str:
    if value.bit_length() > INT_BITS_MAX:
        return CANT_SHOW
    try:
        return str(value)
    except ValueError:                    # a lower sys.set_int_max_str_digits limit
        return CANT_SHOW


def _sequence(value: list | tuple, depth: int) -> Iterator[tuple]:
    is_tuple = type(value) is tuple
    yield ("s", "(" if is_tuple else "[")
    first = True
    for item in value:
        if not first:
            yield _SEP
        first = False
        yield ("v", item, depth)
    if is_tuple and len(value) == 1:
        yield ("s", ",")
    yield ("s", ")" if is_tuple else "]")
    yield ("x", id(value))


def _set(value: set | frozenset, depth: int) -> Iterator[tuple]:
    frozen = type(value) is frozenset
    if not value:
        yield ("s", "frozenset()" if frozen else "set()")
    else:
        yield ("s", "frozenset({" if frozen else "{")
        first = True
        for item in value:
            if not first:
                yield _SEP
            first = False
            yield ("v", item, depth)
        yield ("s", "})" if frozen else "}")
    yield ("x", id(value))


def _dict(value: dict, depth: int) -> Iterator[tuple]:
    yield ("s", "{")
    first = True
    for key, item in value.items():
        if not first:
            yield _SEP
        first = False
        yield ("v", key, depth)
        yield ("s", ": ")
        yield ("v", item, depth)
    yield ("s", "}")
    yield ("x", id(value))


_CONTAINERS = {list: _sequence, tuple: _sequence, set: _set, frozenset: _set, dict: _dict}


def _walk(value: object, limit: int, objects: dict[int, object]) -> tuple[list, bool]:
    """The parts of ``value``'s text, stopping once they pass ``limit`` characters (a slot
    counts as one). Author objects are added to ``objects`` (by id) and get a ``_Slot``.
    Returns ``(parts, cut)``."""
    parts: list = []
    size = 0
    on_path: set[int] = set()
    stack: list[Iterator[tuple]] = [iter((("v", value, 0),))]
    while stack:
        try:
            action = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        tag = action[0]
        if tag == "x":
            on_path.discard(action[1])
            continue
        if tag == "s":
            text = action[1]
        else:
            item, depth = action[1], action[2]
            kind = type(item)
            if kind is str:
                text = _str_text(item, limit - size + 1)
            elif item is None or kind is bool or kind in _PLAIN_SCALARS:
                text = repr(item)
            elif kind is int:
                text = _int_text(item)
            elif kind in _CONTAINERS:
                if id(item) in on_path or depth >= DEPTH_MAX:
                    text = MORE
                else:
                    on_path.add(id(item))
                    stack.append(_CONTAINERS[kind](item, depth + 1))
                    continue
            else:
                objects.setdefault(id(item), item)
                parts.append(_Slot(id(item)))
                size += 1
                if size > limit:
                    return parts, True
                continue
        parts.append(text)
        size += len(text)
        if size > limit:
            return parts, True
    return parts, False


def _finish(raw: str, cut: bool, cap: int) -> str:
    """Redact, escape, then cut to ``cap`` with ``…`` (always ``…`` when the walk was cut)."""
    text = escape_controls(redact(raw))
    if cut or len(text) > cap:
        return text[:max(cap - 1, 0)] + MORE
    return text


class TextBatch:
    """Value texts made together, so that author objects cost one guarded call in all.

    ``add`` walks a plain value at once (no author code); ``texts(call)`` makes the one
    author call, if any object needs it, and returns every text in ``add`` order."""

    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._objects: dict[int, object] = {}
        self._caps: dict[int, int] = {}

    def add(self, value: object, cap: int) -> int:
        """Queue ``value``'s text, at most ``cap`` (≥ 1) characters. Returns its index."""
        cap = max(int(cap), 1)
        found: dict[int, object] = {}
        parts, cut = _walk(value, cap + _SLACK, found)
        for key, obj in found.items():
            self._objects.setdefault(key, obj)
            self._caps[key] = max(self._caps.get(key, 0), cap)
        self._entries.append(_Entry(parts, cut, cap))
        return len(self._entries) - 1

    @property
    def needs_call(self) -> bool:
        """Whether any queued value holds an author object (``texts`` will call)."""
        return bool(self._objects)

    def texts(self, call: AuthorCall | None = None) -> list[str]:
        """Every queued text, in ``add`` order. Calls ``call`` at most once, and only when
        an author object needs its ``repr``."""
        shown: dict[int, str] = {}
        if self._objects and call is not None:
            objects, caps = list(self._objects.items()), self._caps

            def reprs() -> None:
                for key, obj in objects:
                    try:
                        text = repr(obj)
                    except (Exception, SystemExit, GeneratorExit):
                        text = CANT_SHOW
                    shown[key] = (text[:caps[key] + _SLACK] if type(text) is str
                                  else CANT_SHOW)

            try:
                call(reprs)
            except Exception:             # the guard should absorb everything; be sure
                pass
        return [self._assemble(entry, shown) for entry in self._entries]

    @staticmethod
    def _assemble(entry: _Entry, shown: dict[int, str]) -> str:
        limit = entry.cap + _SLACK
        pieces: list[str] = []
        size = 0
        cut = entry.cut
        for part in entry.parts:
            text = part if type(part) is str else shown.get(part.key, CANT_SHOW)
            pieces.append(text)
            size += len(text)
            if size > limit:
                cut = True
                break
        raw = "".join(pieces)
        return _finish(raw[:limit + 1] if cut else raw, cut, entry.cap)


def value_text(value: object, cap: int, call: AuthorCall | None = None) -> str:
    """One value's text, at most ``cap`` characters (a batch of one: at most one
    ``call``)."""
    batch = TextBatch()
    batch.add(value, cap)
    return batch.texts(call)[0]


__all__ = ["AuthorCall", "CANT_SHOW", "CODE_MAX", "DEPTH_MAX", "INT_BITS_MAX", "MORE",
           "ROW_MAX", "TextBatch", "VALUES_MAX", "value_text"]
