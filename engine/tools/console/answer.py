"""The console's answer to Studio (F40 ``04`` §7.5, ``05`` SEC-F40-07; AC-F40-28, -37).

Why this module exists: each Studio ``console`` message gets one report line back on the
game's stdout, ``VN-EDITOR-REPORT {"v":1,"event":"console","do":D,"ok":bool,"text":T}``; a
``values`` answer adds ``"story":bool,"values":[[name,text],…],"left_out":N``. Studio drops a
line over ``REPORT_MAX_BYTES``, and ASCII-escaped non-ASCII text can be six (or twelve) bytes
a character, so 1,000 names can't be assumed to fit: the line is encoded and measured, and
trailing ``values`` are dropped while it is over the cap, counted in ``left_out`` with any
past ``CONSOLE_VALUES_MAX``.

Every string goes through ``echo()`` (redacted, controls and bidi escaped, cut): ``text`` to
``CONSOLE_TEXT_MAX``, names to ``CONSOLE_NAME_MAX``, value texts to
``CONSOLE_VALUE_TEXT_MAX`` (``valuetext`` made them already; ``echo`` is idempotent on its
own output). Nothing here is logged. Imports ``engine.core`` and ``engine.app.editor_link``'s
``encode_line`` (the one report encoder).
"""

import json
from collections.abc import Sequence

from engine.app.editor_link import encode_line
from engine.core.editorreport import (
    CONSOLE_DO,
    CONSOLE_EVENT,
    CONSOLE_NAME_MAX,
    CONSOLE_TEXT_MAX,
    CONSOLE_VALUE_TEXT_MAX,
    CONSOLE_VALUES_MAX,
    REPORT_MAX_BYTES,
    REPORT_VERSION,
)
from engine.core.redact import echo


def _entry_size(entry: list[str]) -> int:
    """The bytes ``entry`` adds to the line: its JSON and one comma."""
    return len(json.dumps(entry, ensure_ascii=True, separators=(",", ":"))) + 1


def console_event(do: str, ok: bool, text: str, *, story: bool = False,
                  values: Sequence[tuple[str, str]] = ()) -> bytes:
    """The answer line (marker and JSON, no line break), at most ``REPORT_MAX_BYTES``.

    ``story`` and ``values`` are sent only for ``do == "values"``: ``values`` are
    ``(name, value_text)`` pairs in the console's order; the ones that don't fit, and any
    past ``CONSOLE_VALUES_MAX``, are left out and counted."""
    if do not in CONSOLE_DO:
        raise ValueError(f"not a console request kind: {do!r}")
    event: dict = {"v": REPORT_VERSION, "event": CONSOLE_EVENT, "do": do, "ok": bool(ok),
                   "text": echo(str(text), CONSOLE_TEXT_MAX)}
    if do != "values":
        return encode_line(event)
    entries = [[echo(str(name), CONSOLE_NAME_MAX), echo(str(shown), CONSOLE_VALUE_TEXT_MAX)]
               for name, shown in values[:CONSOLE_VALUES_MAX]]
    total = len(values)

    def line(count: int) -> bytes:
        return encode_line({**event, "story": bool(story), "values": entries[:count],
                            "left_out": total - count})

    count = len(entries)
    encoded = line(count)
    if len(encoded) > REPORT_MAX_BYTES:
        # Drop entries from the end by their measured size, then confirm (the count's digits
        # can still tip it over by a few bytes).
        size = len(encoded)
        while count and size > REPORT_MAX_BYTES:
            count -= 1
            size -= _entry_size(entries[count])
        encoded = line(count)
        while count and len(encoded) > REPORT_MAX_BYTES:
            count -= 1
            encoded = line(count)
    return encoded


__all__ = ["console_event"]
