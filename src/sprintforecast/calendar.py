# SPDX-License-Identifier: EUPL-1.2
"""Sprint calendar: following sprints, workdays and holidays."""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import cache

import holidays

from sprintforecast.i18n import t
from sprintforecast.model import AbsenceState, Numbering, Person, Sprint, Team
from sprintforecast.storage import DataError


def _successor(previous_id: str, start_year: int, numbering: Numbering) -> str:
    if numbering is Numbering.SEQUENTIAL:
        return str(int(float(previous_id)) + 1)
    year, sep, counter = previous_id.partition(".")
    if sep and year.isdigit() and int(year) == start_year:
        return f"{year}.{int(counter) + 1}"
    return f"{start_year}.1"


def expected_id_form(numbering: Numbering) -> str:
    """Form of the sprint IDs that ``next_id`` can continue (for messages)."""
    if numbering is Numbering.SEQUENTIAL:
        return t("a number, e.g. 22")
    return t("YYYY.N, e.g. 2026.22")


def next_id(previous_id: str, next_start: date, numbering: Numbering) -> str:
    """ID of the following sprint; raises DataError if ``previous_id`` does not fit numbering."""
    try:
        return _successor(previous_id, next_start.year, numbering)
    except (ValueError, OverflowError) as e:
        raise DataError(
            t(
                (
                    "Sprint ID '{id}' does not match the numbering (expected {expected}); the "
                    "ID of the following sprint cannot be formed. Please correct the ID: with "
                    "sprintforecast rename-sprint or under Settings (without sprint files: the "
                    "ID of the first sprint there)."
                ),
                id=previous_id,
                expected=expected_id_form(numbering),
            )
        ) from e


def id_fits_numbering(sprint_id: str, next_start: date, numbering: Numbering) -> bool:
    """Can the ID of the following sprint starting at ``next_start`` be derived from ``sprint_id``?
    Exactly the condition under which ``next_id`` does not fail: with "YYYY.N" the counter only
    continues within the same year (a counter like "22b" is harmless at a year change), IDs
    without a leading year restart the yearly numbering (numbering change)."""
    try:
        _successor(sprint_id, next_start.year, numbering)
    except ValueError, OverflowError:
        return False
    return True


def following_sprint(team: Team, previous: Sprint | None) -> Sprint:
    """Create the sprint that follows ``previous`` (or the team's first sprint)."""
    length = timedelta(days=team.sprint.length_days)
    if previous is None:
        if team.sprint.first_id is None or team.sprint.first_start is None:
            raise DataError(
                t(
                    (
                        "Team {team}: No sprint has been recorded yet. Please enter the start "
                        "and ID of the first sprint under Settings (in team.yaml: "
                        "sprint.first.id and sprint.first.start)."
                    ),
                    team=team.key,
                )
            )
        start = team.sprint.first_start
        return Sprint(
            id=team.sprint.first_id,
            start=start,
            end=start + length,
            absence_state=AbsenceState.UNKNOWN,
        )
    start = previous.end
    return Sprint(
        id=next_id(previous.id, start, team.sprint.numbering),
        start=start,
        end=start + length,
        absence_state=AbsenceState.UNKNOWN,
    )


WEEKDAYS = {
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


def day_label(d: date) -> str:
    """German "Mi 28.10.2026", English "Wed 28.10.2026"."""
    from sprintforecast.i18n import language

    return f"{WEEKDAYS[language()][d.weekday()]} {d:%d.%m.%Y}"


# Weekend as weekday numbers (Monday = 0): Sat/Sun.
DEFAULT_WEEKEND: frozenset[int] = frozenset({5, 6})
DEFAULT_COUNTRY = "DE"
# Workweeks that can be set independently of the country (value = weekend).
WORKWEEKS: dict[str, frozenset[int]] = {
    "mon-fri": frozenset({5, 6}),
    "sun-thu": frozenset({4, 5}),
    "mon-sat": frozenset({6}),
}


@cache
def countries() -> dict[str, str]:
    """Supported countries: ISO code → name (from the holidays library)."""
    from holidays import registry

    supported = set(holidays.list_supported_countries())
    names = {}
    for cls_name, *codes in registry.COUNTRIES.values():
        code = codes[0]
        if code in supported:
            names[code] = re.sub(r"(?<!^)(?=[A-Z])", " ", cls_name)
    return dict(sorted(names.items()))


@cache
def subdivisions(country: str) -> list[str]:
    """Valid region codes (federal state, state, province …) of a country."""
    return list(holidays.list_supported_countries().get(country.upper(), []))


@cache
def country_weekend(country: str) -> frozenset[int]:
    """Weekend of the country according to the holidays library (e.g. Fri/Sat in Saudi Arabia)."""
    try:
        return frozenset(holidays.country_holidays(country.upper()).weekend)
    except NotImplementedError:
        return DEFAULT_WEEKEND


WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def weekend_from_workweek(value: str | None) -> frozenset[int] | None:
    """Days off for a workweek: a name (``mon-fri``, ``sun-thu``, ``mon-sat``) or a list of
    the workdays like ``mon,tue,wed,thu`` (4-day week).
    None for ``auto``/empty; raises ValueError for unknown values."""
    if value is None or value.strip().lower() in {"", "auto"}:
        return None
    value = value.strip().lower()
    if value in WORKWEEKS:
        return WORKWEEKS[value]
    codes = [part.strip() for part in value.replace(";", ",").replace(" ", ",").split(",")]
    worked = {WEEKDAY_CODES.index(c) for c in codes if c}
    if any(c and c not in WEEKDAY_CODES for c in codes) or not worked:
        raise ValueError(value)
    return frozenset(set(range(7)) - worked)


def team_weekend(team: Team) -> frozenset[int]:
    """Weekend of the team: the configured workweek, otherwise that of the country."""
    try:
        explicit = weekend_from_workweek(team.capacity.workweek)
    except ValueError:
        explicit = None
    return explicit or country_weekend(team.capacity.country)


def person_weekend(team: Team, person: Person) -> frozenset[int]:
    """Days off of a person: own workweek, otherwise the weekend of their country, otherwise
    that of the team."""
    try:
        own = weekend_from_workweek(person.workweek)
    except ValueError:
        own = None
    if own is not None:
        return own
    return country_weekend(person.country) if person.country else team_weekend(team)


def workdays(start: date, end: date, weekend: frozenset[int] = DEFAULT_WEEKEND) -> list[date]:
    """Workdays in the half-open interval [start, end); ``weekend`` = days off."""
    days = []
    day = start
    while day < end:
        if day.weekday() not in weekend:
            days.append(day)
        day += timedelta(days=1)
    return days


def team_workdays(team: Team, start: date, end: date) -> list[date]:
    return workdays(start, end, team_weekend(team))


def workweek_label(team: Team) -> str:
    """Workweek of the team for texts: "Mon–Fri" for consecutive days, otherwise the list
    ("Mon, Tue, Wed, Thu")."""
    from sprintforecast.i18n import language

    names = WEEKDAYS[language()]
    weekend = team_weekend(team)
    worked = [i for i in range(7) if i not in weekend]
    if not worked:
        return "–"
    # Consecutive (also across the weekend, e.g. Sun–Thu): from the first day after a
    # day off to the last workday.
    start = next((i for i in worked if (i - 1) % 7 in weekend), None)
    if start is not None and len(worked) > 2:
        run = [(start + k) % 7 for k in range(len(worked))]
        if all(i not in weekend for i in run):
            return f"{names[run[0]]}–{names[run[-1]]}"
    return ", ".join(names[i] for i in worked)


@cache
def _holiday_calendar(
    country: str, region: str | None, year: int, lang: str = "de"
) -> holidays.HolidayBase:
    # Not every language exists for every country, so the library falls back to the local language.
    # An unknown country or mismatched region does not crash the calculation (the check
    # reports the error); then only the nationwide holidays apply, or none.
    language = "en_US" if lang == "en" else "de"
    for subdiv in (region or None, None):
        try:
            return holidays.country_holidays(
                country.upper(), subdiv=subdiv, years=year, language=language
            )
        except NotImplementedError:
            continue
    return holidays.HolidayBase()


def is_holiday(day: date, region: str | None, country: str = DEFAULT_COUNTRY) -> bool:
    return day in _holiday_calendar(country, region, day.year)


def holiday_name(day: date, region: str | None, country: str = DEFAULT_COUNTRY) -> str | None:
    """Name of the holiday in the configured language, or None."""
    from sprintforecast.i18n import language

    return _holiday_calendar(country, region, day.year, language()).get(day)
