"""The F63 story clock's message texts (specs/F63-story-clock/SPEC.md): load E428–E430
(``script/clock.py``, parse), E431–E434 and W300–W303 (``clock.check_story``), run E435
(``runtime/clock.py``). ``clock.py`` adds them to ``messages.TEMPLATES`` when it is imported, so
``messages.py`` itself needs no edit. Every template formats with no arguments (the message
tests call each with its defaults). Round 2: W304 (``clockshow.picture_warnings``, launch).
"""

from collections.abc import Callable, Sequence

from engine.script.messages import _did_you_mean, show, show_name

_FORMS = "clock next, clock next day, or clock go to day 3"


def _quoted(text: str) -> str:
    return f'"{show(text)}"'


def _e428(form: str = "word", found: str = "nxt", suggestion: str | None = "next") -> str:
    """``word`` (what follows clock; ADR-0010 rule 4: no character clock), ``speaker`` (the
    game has a character clock), ``colon`` (the word after clock)."""
    if form == "colon":
        return (f"clock {show(found)} takes no colon or block after it. Remove the \":\" and "
                "un-indent the lines under it.")
    if form == "speaker":
        return (f"clock is a character here, but this line has no text in quotes. To make "
                f'clock speak, write e.g. clock "Tick." To move story time, write {_FORMS}.')
    text = (f"clock moves story time and needs next or go after it, but found "
            f"{_quoted(found) if found else 'nothing'}.")
    if suggestion is not None and found:
        text += " " + _did_you_mean(suggestion, found)
    return text + f" Write {_FORMS}."


def _e429(form: str = "next", found: str = "days") -> str:
    """``next`` (after ``clock next``), ``day`` (after ``clock next day``)."""
    head = "clock next day" if form == "day" else "clock next"
    return (f"{head} takes nothing more, but found {_quoted(found)}. Write clock next for the "
            "next part of the day, or clock next day for the next morning.")


def _e430(form: str = "to", found: str = "") -> str:
    """``to`` (go without to), ``target`` (nothing, or something unreadable, after go to),
    ``day`` (day without a number), ``range`` (a day number out of range), ``extra``
    (something after the target), ``empty`` (empty quotes)."""
    example = "clock go to day 7, clock go to \"31 October\" or clock go to Evening"
    if form == "to":
        return f"clock go needs to after it, e.g. {example}."
    if form == "day":
        return (f"clock go to day needs a day number after it, but found {_quoted(found)}. "
                "Write e.g. clock go to day 7.")
    if form == "range":
        return (f"the day number {show(found)} is out of range; days count from 1 to 99,999. "
                "Write e.g. clock go to day 7.")
    if form == "extra":
        return (f"clock go to takes a day or date and a part of the day at most, but found "
                f"{_quoted(found)} after them. Put a name with spaces in quotes, e.g. "
                'clock go to day 2 "After school".')
    if form == "empty":
        return f"clock go to has empty quotes. Write e.g. {example}."
    found_text = f"found {_quoted(found)}" if found else "found nothing"
    return f"clock go to needs a day, a date or a part of the day, but {found_text}. Write e.g. " \
           f"{example}."


def _e431(text: str = "31 Octobre", example: str = "3 December") -> str:
    return (f"{_quoted(text)} isn't a date this game's calendar can read. Write a day number "
            f"(day 9) or a date such as {_quoted(example)}; the months and seasons come from "
            "[calendar] in config.toml or the kit.")


def _e432(part: str = "Nite", suggestion: str | None = "Night",
          parts: Sequence[str] = ("Morning", "Afternoon", "Evening", "Night")) -> str:
    text = f'no part of the day is called "{show(part)}".'
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, part)
    shown = ", ".join(show(p) for p in parts[:8])
    return text + f" The parts are {shown}; [calendar] parts in config.toml can rename them."


def _e433(form: str = "no_last_day", text: str = "", example: str = "day 30") -> str:
    """``no_last_day`` (``days_left()`` with no last day), ``date`` (a date it can't read),
    ``args`` (more than one argument)."""
    if form == "args":
        return ("clock.days_left takes one day at most: a day number, a date in quotes, or "
                "nothing for [calendar] last_day.")
    if form == "date":
        return (f"clock.days_left can't read {_quoted(text)} as a date. Give a day number or a "
                f"date such as {_quoted(example)}.")
    return ("clock.days_left() counts down to [calendar] last_day, which config.toml doesn't "
            "set. Set it, e.g. last_day = 30, or give the day: clock.days_left(30).")


def _e434(form: str = "unknown", name: str = "dya", suggestion: str | None = "day") -> str:
    """``unknown`` (an attribute clock doesn't have), ``write``."""
    if form == "write":
        return (f"Python can't change clock.{show_name(name)}. Story time moves only with "
                f"{_FORMS}.")
    text = f"clock has no value called {show_name(name)}."
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, name)
    return text + (" It has day, part, weekday, date, month, season and days_left(…).")


def _e435(form: str = "date", text: str = "31 Octobre") -> str:
    """Run time: ``date``, ``part``, ``max`` (as E430's range), ``write``, ``arg``
    (``days_left`` given something that is no day number or date), ``define`` (a define
    reading the clock before the game starts)."""
    if form == "part":
        return _e432(text, None)
    if form == "max":
        return f"story time can't go past day 99,999 (this line asked for day {show(text)})."
    if form == "write":
        return _e434("write", text, None)
    if form == "arg":
        return (f"clock.days_left needs a day number or a date in quotes, but got {show(text)}.")
    if form == "define":
        return ("it reads clock, which runs only once a game has started. Use a default or a "
                "lambda.")
    return _e431(text, "day 9")


def _w300(value: str = "part", text: str = "Nite", close: str | None = "Night",
          names: Sequence[str] = ("Morning", "Afternoon", "Evening", "Night")) -> str:
    kinds = {"part": "part of the day", "weekday": "weekday", "month": "month",
             "season": "season"}
    if not names:
        return (f"clock.{value} is compared with \"{show(text)}\", but this calendar has no "
                f"{kinds.get(value, value)}s, so it is always \"\". Add them in [calendar].")
    text_out = (f"clock.{value} is never \"{show(text)}\": no {kinds.get(value, value)} is "
                "called that, so this comparison never matches.")
    if close is not None:
        text_out += " " + _did_you_mean(close, text)
    return text_out


def _w301(form: str = "start", text: str = "Fooday 9") -> str:
    """``start``, ``month_days``, ``field``."""
    if form == "month_days":
        return ("[calendar] month_days has a different number of entries than months, so each "
                "month gets its usual length. Give one number per month, or one number for all.")
    if form == "field":
        return (f"[calendar] day_text uses {{{show(text)}}}, which this calendar doesn't have, "
                "so dates use the default wording. The fields are day, weekday, month, "
                "month_day, season and season_day.")
    return (f"[calendar] start {_quoted(text)} isn't a date this calendar can read, so the "
            "story starts on day 1. Write a day number or a date such as \"Monday 1 April\".")


def _w302() -> str:
    return ("this game has its own clock (a define or default), so clock.day and the other "
            "story-time values aren't the story clock here. Rename yours, e.g. default "
            "my_clock = 0.")


def _w303(day: int = 40, last: int = 30) -> str:
    return (f"this goes to day {day}, after [calendar] last_day ({last}), so "
            "clock.days_left() is already 0 there.")


def _w304(line: str = "show clock") -> str:
    return (f"{line} puts the story clock in the corner, not your picture \"clock\". To show "
            f"the picture, say where or how ({line} at center, {line} with dissolve), or "
            "rename the picture.")


TEMPLATES: dict[str, Callable[..., str]] = {
    "E428": _e428, "E429": _e429, "E430": _e430, "E431": _e431, "E432": _e432, "E433": _e433,
    "E434": _e434, "E435": _e435, "W300": _w300, "W301": _w301, "W302": _w302, "W303": _w303,
    "W304": _w304,
}

__all__ = ["TEMPLATES"]
