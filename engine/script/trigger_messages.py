"""The trigger core's message texts (F65 trigger core, ADR-0011): load E459 and E458 and the
warnings W316 and W315 (``script/triggers.check_triggers``), run E457
(``runtime/triggers.arm``). F65's block is E448–E459 / W311–W316; the trigger core takes from
the top down, the other F65 work from the bottom up. ``script/triggers.py`` adds these to
``messages.TEMPLATES`` when it is imported, so ``messages.py`` needs no edit. Every template
formats with no arguments (the message tests call each with its defaults).

``kind`` is the owning system's word for its blocks (``event``, ``message``, ``place``,
``thought``), so an author reads about their own events, not about triggers.
"""

from collections.abc import Callable

from engine.script.messages import show, show_name


def _a(kind: str) -> str:
    return ("an " if kind[:1] in "aeiou" else "a ") + kind


def _e459(kind: str = "event", name: str = "hana_library", line: int = 12) -> str:
    return (f"there is already {_a(kind)} called {show_name(name)} (line {line}). Give each "
            f"{kind} its own name: saves remember by name which {kind}s have happened.")


def _e458(kind: str = "event", name: str = "hana_library", unit: str = "days",
          count: int = 1) -> str:
    """``unit`` is ``days`` or ``scenes``."""
    head = (f"{kind} {show_name(name)} waits from the start of the game, so \"after {count} "
            f"{unit}\" has nothing to count from.")
    if unit == "scenes":
        return head + (" Use a condition instead, e.g. a variable a scene sets: "
                       "when met_hana.")
    return head + " Use a day instead (day 7), or a condition such as clock.day >= 7."


def _e457(kind: str = "message", limit: int = 1000) -> str:
    return (f"over {limit:,} {kind}s are waiting at once. A loop may be sending the same "
            f"thing again and again; let some arrive first, or send fewer.")


def _w316(form: str = "never", kind: str = "event", name: str = "hana_library",
          a: object = "clock.day > 40", b: object = " on days 1 to 30") -> str:
    """``past_last`` (``a`` the day, ``b`` the last day), ``after`` (``a`` the days, ``b``
    the last day), ``part`` (``a`` the part's number from 1, ``b`` how many parts),
    ``never`` (``a`` the condition as written, ``b`` the days it was read over, or "")."""
    head = f"{kind} {show_name(name)} can never happen: "
    if form == "past_last":
        return head + (f"it waits for day {a}, after [calendar] last_day ({b}). Pick an "
                       "earlier day, or a later last_day.")
    if form == "after":
        return head + (f"after {a} days is past [calendar] last_day ({b}), even counting "
                       "from the first day.")
    if form == "part":
        return head + (f"it waits for part {a} of the day, but this calendar has {b} parts. "
                       "Check [calendar] parts in config.toml.")
    return head + (f"its condition {show(str(a))} is never true{b}. Check the comparison "
                   "(== or !=, and or or) and the numbers.")


def _w315(kind: str = "event", name: str = "library_chat", winner: str = "library_quiet",
          line: int = 8, where: str = "library") -> str:
    at = f" at {show(where)}" if where else ""
    return (f"{kind} {show_name(name)} never happens: {kind} {show_name(winner)} (line {line}) "
            f"comes before it{at}, always fits and repeats, so it is picked every time. Move "
            f"{show_name(name)} above it, give {show_name(winner)} a condition, or make it "
            "once.")


TEMPLATES: dict[str, Callable[..., str]] = {
    "E457": _e457, "E458": _e458, "E459": _e459, "W315": _w315, "W316": _w316,
}

__all__ = ["TEMPLATES"]
