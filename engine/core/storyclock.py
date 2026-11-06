"""The story clock's calendar (F63 round 1; specs/F63-story-clock/SPEC.md, proposal I-03).

Why this module exists: story time (``clock next``, ``clock.day``, ``clock.weekday``…) is
counted in days and parts of the day, and what those are called comes from ``[calendar]`` in
config.toml, then the kit (``kits.ClockDress``), then the defaults here. The script checks,
the runtime and Studio all need the same answers ("which day is 31 October?", "what is day 9
called?"), so the arithmetic lives once, here, as pure data.

- ``Calendar``: the parts of the day, weekday names, optional months (name, days) and seasons,
  where day 1 falls in the week, the year and the seasons, the day the clock starts on, an
  optional ``last_day``, and the wording of a date (``day_text``, fields such as ``{day}``).
- ``calendar_of(config)``: the game's calendar, ``[calendar]`` > kit > defaults, and the
  problems found on the way (``CalendarProblem``; the story checks give W301 for each).
- ``Calendar.find_date(text, on_or_after)``: the day a written date names ("31 October",
  "Spring 4", "day 9"), or None. A date that repeats (a month or season date) means the first
  such day on or after ``on_or_after``.

Day numbers start at 1. Pure data; imports only ``core``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from engine.core.kits import kit_of

DEFAULT_PARTS: Final = ("Morning", "Afternoon", "Evening", "Night")
WEEKDAYS: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                   "Sunday")
MONTHS: Final = (("January", 31), ("February", 28), ("March", 31), ("April", 30), ("May", 31),
                 ("June", 30), ("July", 31), ("August", 31), ("September", 30),
                 ("October", 31), ("November", 30), ("December", 31))
SEASON_DAYS: Final = 28                 # days in a season when [calendar] doesn't say

DAY_MAX: Final = 99_999                 # the clock never counts past this day
PARTS_MAX: Final = 12
WEEKDAYS_MAX: Final = 14
MONTHS_MAX: Final = 24
SEASONS_MAX: Final = 12
NAME_MAX: Final = 30                    # code points of one part, weekday, month or season
DAYS_IN_MAX: Final = 400                # days in one month or season
TEXT_MAX: Final = 60                    # code points of ``start`` and ``day_text``

# The fields a date's wording may use, and which calendars have them.
TEXT_FIELDS: Final = ("day", "weekday", "month", "month_day", "season", "season_day")
_FIELD_RE: Final = re.compile(r"\{(\w+)\}")
_NUMBER_RE: Final = re.compile(r"\d{1,6}")
_FILLER: Final = frozenset(("day", "the", "of", "on"))


@dataclass(frozen=True)
class CalendarProblem:
    """One thing in ``[calendar]`` that couldn't be used: ``form`` is ``start`` (the start
    date can't be read; ``text`` is it), ``month_days`` (the list's length isn't the months'),
    ``field`` (``day_text`` uses a field the calendar doesn't have; ``text`` is the field)."""
    form: str
    text: str = ""


class DateProblem(ValueError):
    """``Calendar.go_to`` can't go there: ``form`` is ``date`` (``text`` can't be read as a
    date), ``part`` (no part of the day is called ``text``) or ``max`` (past ``DAY_MAX``)."""

    def __init__(self, form: str, text: str) -> None:
        super().__init__(form)
        self.form, self.text = form, text


@dataclass(frozen=True)
class Calendar:
    """A game's calendar (module docstring). ``months`` is ``((name, days), …)``, empty for
    none; ``first_weekday``, ``first_year_day`` and ``first_season_day`` are where day 1 falls
    (0-based) in the week, the months' year and the seasons' cycle."""
    parts: tuple[str, ...] = DEFAULT_PARTS
    weekdays: tuple[str, ...] = WEEKDAYS
    months: tuple[tuple[str, int], ...] = ()
    seasons: tuple[str, ...] = ()
    season_days: int = SEASON_DAYS
    start_day: int = 1
    first_weekday: int = 0
    first_year_day: int = 0
    first_season_day: int = 0
    last_day: int | None = None
    day_text: str = ""
    _year: int = field(default=0, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_year", sum(days for _, days in self.months))

    # Names ---------------------------------------------------------------------------------

    def part_index(self, name: str) -> int | None:
        """The index of the part of the day called ``name`` (any capitals), or None."""
        return _index(self.parts, name)

    def weekday_index(self, name: str) -> int | None:
        return _index(self.weekdays, name)

    # One day -------------------------------------------------------------------------------

    def weekday(self, day: int) -> str:
        return self.weekdays[(self.first_weekday + day - 1) % len(self.weekdays)]

    def month(self, day: int) -> tuple[str, int] | None:
        """``(month, day of the month)`` of ``day``, or None with no months."""
        if not self._year:
            return None
        at = (self.first_year_day + day - 1) % self._year
        for name, days in self.months:
            if at < days:
                return name, at + 1
            at -= days
        return None                                     # not reached

    def season(self, day: int) -> tuple[str, int] | None:
        """``(season, day of the season)`` of ``day``, or None with no seasons."""
        if not self.seasons:
            return None
        at = (self.first_season_day + day - 1) % (len(self.seasons) * self.season_days)
        return self.seasons[at // self.season_days], at % self.season_days + 1

    def fields(self, day: int) -> dict[str, str]:
        """The values of ``TEXT_FIELDS`` for ``day`` that this calendar has."""
        out = {"day": str(day), "weekday": self.weekday(day)}
        month = self.month(day)
        if month is not None:
            out["month"], out["month_day"] = month[0], str(month[1])
        season = self.season(day)
        if season is not None:
            out["season"], out["season_day"] = season[0], str(season[1])
        return out

    def wording(self) -> str:
        """The wording of a date: ``day_text`` when every field it uses is one this calendar
        has, else the default (months: "Monday 1 April"; seasons: "Spring, day 4"; else
        "Day 4")."""
        have = set(self.fields(1))
        if self.day_text and all(f in have for f in _FIELD_RE.findall(self.day_text)):
            return self.day_text
        if self.months:
            return "{weekday} {month_day} {month}"
        if self.seasons:
            return "{season}, day {season_day}"
        return "Day {day}"

    def date(self, day: int) -> str:
        """``day`` in words (``wording`` with the fields filled in)."""
        values = self.fields(day)
        return _FIELD_RE.sub(lambda m: values.get(m.group(1), m.group(0)), self.wording())

    # Written dates -------------------------------------------------------------------------

    def find_date(self, text: str, on_or_after: int = 1) -> int | None:
        """The day ``text`` names, or None if it can't be read with this calendar: "day 9" or
        "9" (that day); a month date ("31 October", "October 31", "Monday 31 October": the
        weekday is not checked) or a season date ("Spring 4", "Spring, day 4"): the first such
        day on or after ``on_or_after``."""
        words = _words(text)
        month, words = _take_name(words, [name for name, _ in self.months])
        season, words = _take_name(words, list(self.seasons)) if month is None else (None, words)
        _weekday, words = _take_name(words, list(self.weekdays))
        words = [w for w in words if w not in _FILLER]
        if len(words) != 1 or _NUMBER_RE.fullmatch(words[0]) is None:
            return None
        number = int(words[0])
        if month is not None:
            name, days = self.months[month]
            if not 1 <= number <= days:
                return None
            at = sum(d for _, d in self.months[:month]) + number - 1
            return _first_on_or_after(at - self.first_year_day, self._year, on_or_after)
        if season is not None:
            if not 1 <= number <= self.season_days:
                return None
            cycle = len(self.seasons) * self.season_days
            at = season * self.season_days + number - 1
            return _first_on_or_after(at - self.first_season_day, cycle, on_or_after)
        return number if 1 <= number <= DAY_MAX else None

    def go_to(self, today: int, now: int, *, day: int | None = None, text: str | None = None,
              part: str | None = None) -> tuple[int, int]:
        """Where ``clock go to`` goes from day ``today``, part ``now``: ``(day, part index)``.
        ``day`` is a day number; ``text`` a written date, or a part of the day when it names
        one and nothing else is given; ``part`` a part's name. A part alone: later today, else
        that part of the next day. A repeating date: the next time it comes (today counts
        while its part is still ahead). A day number may go back. ``DateProblem`` otherwise."""
        if (text is not None and day is None and part is None
                and self.part_index(text) is not None):
            text, part = None, text
        index = 0
        if part is not None:
            found = self.part_index(part)
            if found is None:
                raise DateProblem("part", part)
            index = found
        if day is None and text is None:
            target = today if index >= now else today + 1
        elif text is not None:
            found_day = self.find_date(text, today)
            if found_day is None:
                raise DateProblem("date", text)
            if (found_day, index) < (today, now):
                found_day = self.find_date(text, today + 1) or found_day
            target = found_day
        else:
            target = day                                    # type: ignore[assignment]
        if not 1 <= target <= DAY_MAX:
            raise DateProblem("max", str(target))
        return target, index

    def days_left(self, today: int, target: int) -> int:
        """Days from ``today`` to day ``target``; 0 once it has come."""
        return max(0, target - today)


DEFAULT_CALENDAR: Final = Calendar()


def _index(names: tuple[str, ...], name: str) -> int | None:
    wanted = " ".join(name.split()).casefold()
    for index, own in enumerate(names):
        if own.casefold() == wanted:
            return index
    return None


def _words(text: str) -> list[str]:
    return text.replace(",", " ").casefold().split()


def _take_name(words: list[str], names: list[str]) -> tuple[int | None, list[str]]:
    """The index of the first of ``names`` (one or more words, any capitals) found as whole
    words in ``words``, and ``words`` without it."""
    for index, name in enumerate(names):
        parts = name.casefold().split()
        for start in range(len(words) - len(parts) + 1):
            if words[start:start + len(parts)] == parts:
                return index, words[:start] + words[start + len(parts):]
    return None, words


def _first_on_or_after(offset: int, cycle: int, on_or_after: int) -> int:
    """The first day ``d >= on_or_after`` with ``(d - 1) % cycle == offset % cycle``."""
    day = offset % cycle + 1
    if day < on_or_after:
        day += -(-(on_or_after - day) // cycle) * cycle
    return day


# --- The game's calendar ---------------------------------------------------------------------

def calendar_of(config: Any) -> tuple[Calendar, list[CalendarProblem]]:
    """The calendar ``config`` gives (``[calendar]`` > the kit's ``clock`` > defaults) and the
    problems found. ``config`` None (tools without one): the defaults, no problems."""
    table = getattr(config, "calendar", None)
    found = kit_of(config) if config is not None else None
    dress = found.clock if found is not None else None
    problems: list[CalendarProblem] = []

    def own(key: str) -> Any:
        return getattr(table, key, None) if table is not None else None

    parts = own("parts") or (dress.parts if dress is not None and dress.parts else DEFAULT_PARTS)
    weekdays = own("weekdays") or WEEKDAYS
    start = own("start")
    months: tuple[tuple[str, int], ...] = ()
    names = own("months")
    if names is None and dress is not None and dress.months:
        names = tuple(name for name, _ in MONTHS)
    if names is None and isinstance(start, str) and _take_name(
            _words(start), [name for name, _ in MONTHS])[0] is not None:
        names = tuple(name for name, _ in MONTHS)       # "Monday 1 April" needs no months key
    if names:
        counts = own("month_days")
        english = dict(MONTHS)
        if isinstance(counts, tuple) and len(counts) != len(names):
            problems.append(CalendarProblem("month_days"))
            counts = None
        months = tuple((name, counts[i] if isinstance(counts, tuple)
                        else counts if isinstance(counts, int)
                        else english.get(name, 30)) for i, name in enumerate(names))
    seasons = own("seasons")
    if seasons is None:
        seasons = dress.seasons if dress is not None else ()
    calendar = Calendar(parts=tuple(parts), weekdays=tuple(weekdays), months=months,
                        seasons=tuple(seasons), season_days=own("season_days") or SEASON_DAYS,
                        last_day=own("last_day"),
                        day_text=own("day_text") or (dress.day_text if dress else ""))
    calendar = _with_start(calendar, start, problems)
    text = own("day_text")
    if text:
        have = set(calendar.fields(1))
        problems += [CalendarProblem("field", name) for name in _FIELD_RE.findall(text)
                     if name not in have]
    return calendar, problems


def _with_start(calendar: Calendar, start: object, problems: list[CalendarProblem]) -> Calendar:
    """``calendar`` with ``[calendar] start`` applied: a day number, or a date whose weekday,
    month day or season day day 1 is."""
    from dataclasses import replace
    if start is None:
        return calendar
    if isinstance(start, int):
        return replace(calendar, start_day=start)
    words = _words(str(start))
    weekday, rest = _take_name(words, list(calendar.weekdays))
    changes: dict[str, int] = {}
    if weekday is not None:
        changes["first_weekday"] = weekday
    if rest:
        day = calendar.find_date(" ".join(rest))
        if day is None:
            problems.append(CalendarProblem("start", str(start)))
            return calendar
        month = _take_name(rest, [name for name, _ in calendar.months])[0]
        season = _take_name(rest, list(calendar.seasons))[0]
        if month is not None:
            changes["first_year_day"] = day - 1
        elif season is not None:
            changes["first_season_day"] = day - 1
        else:
            changes["start_day"] = day
    return replace(calendar, **changes)


__all__ = ["Calendar", "CalendarProblem", "DateProblem", "DAY_MAX", "DAYS_IN_MAX",
           "DEFAULT_CALENDAR", "DEFAULT_PARTS", "MONTHS", "MONTHS_MAX", "NAME_MAX", "PARTS_MAX", "SEASONS_MAX",
           "SEASON_DAYS", "TEXT_FIELDS", "TEXT_MAX", "WEEKDAYS", "WEEKDAYS_MAX", "calendar_of"]
